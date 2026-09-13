"""Operator commands.

Deliberately separate from the Telegram transport and from the reasoning loop.
The kill switch has to work when the agent is misbehaving, so the code path
from "operator typed /stop" to "state is halted" touches nothing that the
reasoning loop can block: no shared lock, no queue, no model call. It writes to
SQLite and returns.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandResult:
    text: str
    changed: bool = False
    # False means "this was not a command": the caller should treat the message
    # as conversation. Distinct from a command that ran and had nothing to say.
    handled: bool = True


def handle_command(text: str, *, state, on_halt=None, journal=None) -> CommandResult:
    """Handle one operator command.

    `on_halt` runs AFTER the kill switch is set, never before. Cancelling open
    orders means talking to a broker that may be slow or unreachable, and the
    halt itself must never wait on that — ACCEPTANCE B4 requires /stop to take
    effect regardless of what else is stuck.
    """
    cmd = (text or "").strip().split()[0].lower() if (text or "").strip() else ""

    if cmd == "/stop":
        # Flag first, and it is already durable before anything slow is tried.
        state.set_kill_switch(True)
        note = ""
        if on_halt is not None:
            try:
                outcome = on_halt()
                note = (f"\nOpen orders: {outcome.get('cancelled', 0)} cancelled"
                        f", {outcome.get('failed', 0)} failed.")
                if outcome.get("error"):
                    note = f"\nCould not reach the broker to cancel: {outcome['error']}"
            except Exception as exc:  # noqa: BLE001 — the halt still stands
                note = f"\nCancellation failed: {exc}. The halt is in effect regardless."
        return CommandResult(
            "HALTED. No new orders will be placed. Send /resume to restart." + note,
            changed=True,
        )

    if cmd == "/resume":
        # The only thing that clears it. No timeout, no automatic recovery, and
        # no path from the model — if the agent could resume itself the switch
        # would be advisory.
        state.set_kill_switch(False)
        return CommandResult("Resumed. Trading re-enabled.", changed=True)

    if cmd == "/status":
        halted = state.kill_switch_engaged()
        return CommandResult(
            f"{'HALTED' if halted else 'running'} | "
            f"deployed ${state.deployed_usd():.2f} | "
            f"{len(state.pending_approvals())} pending"
        )

    if cmd in ("/today", "/report"):
        if journal is None:
            return CommandResult("No journal available.")
        import datetime as _dt

        day = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
        return CommandResult(journal(day))

    if cmd == "/help":
        return CommandResult("/stop  /resume  /status  /today  /help")

    if cmd.startswith("/"):
        # A mistyped command must not be parsed as an answer to the open
        # question. "/stopp" becoming a view on a clinical trial is exactly the
        # kind of silent misreading this whole layer exists to prevent.
        return CommandResult(f"Unknown command {cmd}. Try: /stop /resume "
                             "/status /help")

    # Anything else is conversation for the agent, not a command. Notably it
    # must NOT clear a halt: a chatty message is not consent to resume.
    return CommandResult("", handled=False)
