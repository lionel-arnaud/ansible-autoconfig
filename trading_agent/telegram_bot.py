"""Telegram transport.

Deliberately thin. All the logic it carries lives elsewhere and is tested
without it: commands in commands.py, question wording and reply parsing in
consultation.py. This file moves bytes.

That split is not tidiness — it is why the kill switch works. ACCEPTANCE B4
requires /stop to take effect while the reasoning loop is wedged, and it does
because the path from a received message to a halted state runs through
commands.handle_command() into SQLite, sharing no lock and no thread with the
loop. Keeping this file dumb keeps that true.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

log = logging.getLogger(__name__)

API = "https://api.telegram.org"


class TelegramError(RuntimeError):
    pass


@dataclass
class Telegram:
    token: str
    chat_id: str
    # Annotated, or @dataclass treats it as a class attribute rather than a
    # field and the constructor silently rejects it. Injectable so tests never
    # touch the network, and so a send failure is exercised rather than hoped
    # about.
    opener: object = None

    def _call(self, method: str, params: dict) -> dict:
        url = f"{API}/bot{self.token}/{method}"
        data = urllib.parse.urlencode(params).encode()
        try:
            if self.opener is not None:
                return self.opener(url, data)
            with urllib.request.urlopen(url, data=data, timeout=30) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as exc:
            # Telegram puts the actual reason in the body of a 4xx. Discarding
            # it is how "the question was not sent" stayed unexplained.
            try:
                body = json.loads(exc.read().decode())
            except Exception:  # noqa: BLE001
                raise TelegramError(f"{method} failed: {exc}") from exc
            raise TelegramError(
                f"{method} failed: {body.get('description', exc)}"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise TelegramError(f"{method} failed: {exc}") from exc

    def send(self, text: str) -> bool:
        """Send a message. Returns False rather than raising.

        Notification is not worth failing a trading cycle over: a missed
        message is an inconvenience, an aborted cycle is a position left
        unmanaged.
        """
        body = {"chat_id": self.chat_id,
                "text": text[:4096]}  # Telegram's hard limit; truncate, not fail
        try:
            r = self._call("sendMessage", {**body, "parse_mode": "Markdown"})
            if r.get("ok"):
                return True
            reason = r.get("description", "")
        except TelegramError as exc:
            reason = str(exc)

        # Most of what this bot sends is model prose about clinical trials,
        # which is full of asterisks, underscores and brackets that Telegram
        # reads as broken markup and rejects outright. An unformatted question
        # is worth far more than a formatted one that never arrives.
        log.warning("telegram rejected a formatted message (%s); "
                    "resending as plain text", reason)
        try:
            return bool(self._call("sendMessage", body).get("ok"))
        except TelegramError as exc:
            log.error("telegram send failed: %s", exc)
            return False

    def updates(self, offset: int = 0) -> list[dict]:
        """Fetch new messages. An empty list on failure, never an exception —
        a polling error must not take the process down."""
        try:
            r = self._call("getUpdates", {"offset": offset, "timeout": 0})
        except TelegramError:
            return []
        return r.get("result", []) if r.get("ok") else []

    def messages_from_owner(self, offset: int = 0) -> tuple[list[str], int]:
        """Text sent by the configured chat only, plus the next offset.

        Filtering on chat id matters: the bot token is a bearer credential, and
        anyone who finds the bot can message it. Only the owner may drive it.
        """
        texts: list[str] = []
        next_offset = offset
        for u in self.updates(offset):
            next_offset = max(next_offset, int(u.get("update_id", 0)) + 1)
            msg = u.get("message") or u.get("edited_message") or {}
            if str((msg.get("chat") or {}).get("id")) != str(self.chat_id):
                continue
            text = msg.get("text")
            if text:
                texts.append(text)
        return texts, next_offset
