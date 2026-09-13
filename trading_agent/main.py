"""Entrypoint.

Two loops, deliberately not one:

  * the **command loop** runs in the main thread and polls Telegram every few
    seconds. It is the only thing that must never be slow.
  * the **work loop** runs in a daemon thread and does everything expensive —
    reconciliation, catalysts, research, the trading cycle.

That split is ACCEPTANCE B4. A wedged model call blocks the work loop; it must
not block /stop. Each loop opens its own SQLite handle on the same file —
sqlite3 refuses a connection shared across threads, and WAL makes independent
handles safe — so the command loop can halt trading while the work loop is
stuck inside a network call it cannot interrupt.
"""
from __future__ import annotations

import datetime as dt
import logging
import signal
import threading
import time

from trading_agent.agent import run_cycle
from trading_agent.audit import AuditLog, new_correlation_id
from trading_agent.broker import Broker
from trading_agent.catalysts import CatalystFeed
from trading_agent.dialogue import ask_next, handle_reply, to_events
from trading_agent.sources import (alpaca_assets_client, alpaca_news_client,
                                   ctgov_client, etf_holdings_fetcher)
from trading_agent.commands import handle_command
from trading_agent.config import Config
from trading_agent.reasoning import ReasoningClient
from trading_agent.state import State
from trading_agent.telegram_bot import Telegram
from trading_agent.universe import Universe
from trading_agent.views import ViewStore

log = logging.getLogger("trading_agent")

COMMAND_POLL_SECONDS = 3
CYCLE_INTERVAL_SECONDS = 900  # 15 minutes; catalysts do not move by the second
# One question at a time and one at a time is the point: the operator answers
# these between other things, and a queue of them is a channel that gets muted.
CONSULTATION_INTERVAL_SECONDS = 1800

_stop = threading.Event()


def _install_signal_handlers() -> None:
    def handler(signum, _frame):
        # systemd sends SIGTERM on stop and on restart. Exiting cleanly means
        # in-flight SQLite writes finish rather than being torn off.
        log.info("signal %s received, shutting down", signum)
        _stop.set()

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)


def build_worker(config: Config, paths: dict) -> dict:
    """Construct the work loop's collaborators, fully wired.

    Separated from work_loop so a test can assert that every injection point
    actually received something. The feed, the universe and the command handler
    all take their network clients as arguments and default to None, which is
    right for testing and silently wrong in production: the first deploy ran
    clean cycles for twenty minutes reporting zero catalysts, because the feed
    had been built with no HTTP client at all.
    """
    universe = Universe(paths["universe_cache"],
                        fetcher=etf_holdings_fetcher(),
                        name_lookup=alpaca_assets_client(config))
    return {
        "state": State(paths["state_db"]),
        "views": ViewStore(paths["views_db"]),
        "audit": AuditLog(paths["audit_log"]),
        "universe": universe,
        "broker": Broker.from_config(config),
        "reasoner": ReasoningClient.from_config(config),
        "feed": CatalystFeed(universe,
                             http=ctgov_client(),
                             news=alpaca_news_client(config)),
        "telegram": Telegram(config.telegram_bot_token, config.telegram_chat_id),
    }


def work_loop(config: Config, paths: dict) -> None:
    """Everything expensive. Its own state handle; never touches the main one."""
    parts = build_worker(config, paths)
    state, views, audit = parts["state"], parts["views"], parts["audit"]
    universe, broker = parts["universe"], parts["broker"]
    reasoner, feed, tg = parts["reasoner"], parts["feed"], parts["telegram"]

    # Refresh the tradable universe once at startup. Never fatal: a failure
    # leaves the cache, or the in-tree seed, in place.
    audit.record("universe_refresh", new_correlation_id(), universe.refresh())

    # Reconcile once before anything else. Starting a trading process on an
    # unverified picture of the account is the one thing worth refusing to do.
    cid = new_correlation_id()
    try:
        audit.record("startup_reconcile", cid, broker.reconcile(state))
    except Exception as exc:  # noqa: BLE001
        audit.record("startup_reconcile_failed", cid, {"error": str(exc)})
        log.error("startup reconciliation failed: %s", exc)

    while not _stop.is_set():
        try:
            result = run_cycle(
                state=state, config=config, broker=broker, feed=feed,
                reasoner=reasoner, audit=audit, views=views,
                ask=lambda key, payload: tg.send(
                    f"*Approval needed* `{key[:8]}`\n"
                    f"{payload['side']} {payload['symbol']} "
                    f"${payload['notional_usd']:.0f}\n\n"
                    f"{payload.get('rationale', '')}"
                ),
                now=dt.datetime.now(dt.timezone.utc),
            )
            log.info("cycle: ran=%s submitted=%s skipped=%s",
                     result.ran, result.submitted, result.skipped_reason)
        except Exception as exc:  # noqa: BLE001
            # A cycle that throws must not kill the process: the kill switch
            # and the command loop still need to be answering.
            log.exception("cycle failed: %s", exc)
            audit.record("cycle_failed", new_correlation_id(), {"error": str(exc)})

        _stop.wait(CYCLE_INTERVAL_SECONDS)


def consultation_loop(config: Config, paths: dict) -> None:
    """Asking the operator. Its own thread, because it is the slow one.

    A research brief sends the model off to read, and measured against the real
    backend it has run past ten minutes with no upper bound worth trusting.
    Sharing a thread with trading meant order management queued behind a
    question — so it does not share one. Its own State and ViewStore handles,
    like every other loop, because sqlite3 refuses a connection across threads.
    """
    parts = build_worker(config, paths)
    state, views, audit = parts["state"], parts["views"], parts["audit"]
    reasoner, feed, tg = parts["reasoner"], parts["feed"], parts["telegram"]

    while not _stop.is_set():
        cid = new_correlation_id()
        try:
            catalysts = feed.upcoming_trials() + feed.recent_news()
            ask_next(to_events(catalysts), views=views, state=state,
                     telegram=tg, reasoner=reasoner, audit=audit,
                     now=dt.datetime.now(dt.timezone.utc), correlation_id=cid)
        except Exception as exc:  # noqa: BLE001 — a failed question must not
            # end the conversation. Nothing here can reach an order.
            log.exception("consultation failed: %s", exc)
            audit.record("consultation_failed", cid, {"error": str(exc)})

        _stop.wait(CONSULTATION_INTERVAL_SECONDS)


def command_loop(config: Config, paths: dict) -> None:
    """Telegram commands. Kept trivial so it is always responsive."""
    state = State(paths["state_db"])
    views = ViewStore(paths["views_db"])
    audit = AuditLog(paths["audit_log"])
    reasoner = ReasoningClient.from_config(config)
    tg = Telegram(config.telegram_bot_token, config.telegram_chat_id)
    # /stop must also pull the agent's resting orders, or a halt leaves limit
    # orders that can still fill. Its own broker handle: this loop shares
    # nothing with the work loop, which is what keeps it responsive.
    broker = Broker.from_config(config)
    offset = 0
    while not _stop.is_set():
        texts, offset = tg.messages_from_owner(offset)
        for text in texts:
            result = handle_command(text, state=state,
                                    on_halt=broker.cancel_all_orders,
                                    journal=audit.day_report)
            if result.handled:
                if result.text:
                    tg.send(result.text)
                if result.changed:
                    log.warning("operator command applied: %s", text.split()[0])
                continue

            # Not a command, so it is part of the conversation: a view on the
            # open question, or a follow-up about it.
            try:
                kind = handle_reply(
                    text, views=views, state=state, telegram=tg,
                    reasoner=reasoner, audit=audit,
                    now=dt.datetime.now(dt.timezone.utc),
                    correlation_id=new_correlation_id(),
                )
                log.info("operator message handled as %s", kind)
            except Exception as exc:  # noqa: BLE001 — this loop must stay
                # responsive; /stop is the thing it exists to deliver.
                log.exception("reply handling failed: %s", exc)
        _stop.wait(COMMAND_POLL_SECONDS)


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    _install_signal_handlers()

    config = Config.from_env()
    import os

    root = os.environ.get("TRADING_AGENT_ROOT", "/opt/trading-agent")
    paths = {
        "state_db": os.environ.get("STATE_DB", f"{root}/state.db"),
        "views_db": f"{root}/views.db",
        "audit_log": f"{os.environ.get('LOG_DIR', root + '/logs')}/audit.log",
        "universe_cache": f"{root}/universe.json",
    }

    log.info("starting: endpoint=%s live=%s", config.endpoint, config.is_live)
    if config.is_live:
        # Loud on purpose. This line in the journal is the last cheap warning
        # before real money is involved.
        log.warning("LIVE TRADING ENABLED — real money is at risk")

    threads = [
        threading.Thread(target=work_loop, args=(config, paths), daemon=True),
        threading.Thread(target=consultation_loop, args=(config, paths),
                         daemon=True),
    ]
    for thread in threads:
        thread.start()
    try:
        command_loop(config, paths)
    finally:
        _stop.set()
        for thread in threads:
            thread.join(timeout=10)
    log.info("stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
