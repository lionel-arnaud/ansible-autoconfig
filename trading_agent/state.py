"""Durable safety state.

Everything here must survive a restart, because the things it holds are exactly
the things you cannot afford to forget: whether trading is halted, how much has
already been risked today, and which decisions are still in flight.

SQLite rather than JSON: the Telegram handler and the reasoning loop touch this
concurrently, and an interrupted write to a JSON file is a corrupted file
whereas an interrupted SQLite transaction is a rolled-back one.
"""
from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS flags (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS trades (id INTEGER PRIMARY KEY, day TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS daily (
    day TEXT PRIMARY KEY,
    pnl_usd REAL NOT NULL DEFAULT 0.0,
    -- Latched separately from pnl: once the breaker trips the day is over,
    -- even if the position recovers. A breaker that un-trips is not a breaker.
    loss_breaker_tripped INTEGER NOT NULL DEFAULT 0
);
-- The consultation with the operator. One thread is open at a time, so a
-- reply is never ambiguous about which trial it answers.
CREATE TABLE IF NOT EXISTS threads (
    event_key TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    opened_at TEXT NOT NULL,
    -- Kept after the thread closes: an answered question must not be asked
    -- again the moment its view expires, and an unanswered one must not be
    -- re-sent every cycle.
    open INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    -- pending | granted | denied. An expired request becomes denied and stays
    -- on the row: a "yes" that arrives after the deadline must land on a closed
    -- record, not silently open a new one.
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL DEFAULT 0.0
);
"""


def _day(now: dt.datetime) -> str:
    return now.date().isoformat()


class State:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Two handles exist by design (the command loop and the work loop), and
        # on a restart the new process opens the file while the old one is still
        # letting go of it. Without these the first statement raises "database
        # is locked" and systemd restarts into the same race.
        self._db = sqlite3.connect(self.path, isolation_level=None, timeout=30.0)
        self._db.execute("PRAGMA busy_timeout=30000")
        # Switching journal mode takes an exclusive lock, so ask for it only
        # when the database is not already in WAL — which, after the first run,
        # it always is.
        mode = self._db.execute("PRAGMA journal_mode").fetchone()[0]
        if str(mode).lower() != "wal":
            self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """CREATE TABLE IF NOT EXISTS leaves an older database on its old
        columns, so new ones are added here rather than assumed."""
        have = {r[1] for r in self._db.execute("PRAGMA table_info(approvals)")}
        if "status" not in have:
            self._db.execute(
                "ALTER TABLE approvals ADD COLUMN "
                "status TEXT NOT NULL DEFAULT 'pending'"
            )
        if "created_at" not in have:
            self._db.execute(
                "ALTER TABLE approvals ADD COLUMN created_at REAL NOT NULL DEFAULT 0.0"
            )

    # --- kill switch --------------------------------------------------------

    def set_kill_switch(self, engaged: bool) -> None:
        self._db.execute(
            "INSERT INTO flags(key,value) VALUES('kill_switch',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            ("1" if engaged else "0",),
        )

    def kill_switch_engaged(self) -> bool:
        row = self._db.execute(
            "SELECT value FROM flags WHERE key='kill_switch'"
        ).fetchone()
        return bool(row and row[0] == "1")

    # --- trade rate ---------------------------------------------------------

    def record_trade(self, now: dt.datetime) -> None:
        self._db.execute("INSERT INTO trades(day) VALUES(?)", (_day(now),))

    def trades_today(self, now: dt.datetime) -> int:
        row = self._db.execute(
            "SELECT COUNT(*) FROM trades WHERE day=?", (_day(now),)
        ).fetchone()
        return int(row[0]) if row else 0

    # --- capital and P&L ----------------------------------------------------

    def set_deployed_usd(self, amount: float) -> None:
        self._db.execute(
            "INSERT INTO flags(key,value) VALUES('deployed',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(amount),),
        )

    def deployed_usd(self) -> float:
        row = self._db.execute(
            "SELECT value FROM flags WHERE key='deployed'"
        ).fetchone()
        return float(row[0]) if row else 0.0

    def set_daily_pnl_usd(self, pnl: float, now: dt.datetime) -> None:
        self._db.execute(
            "INSERT INTO daily(day,pnl_usd) VALUES(?,?) "
            "ON CONFLICT(day) DO UPDATE SET pnl_usd=excluded.pnl_usd",
            (_day(now), pnl),
        )

    def daily_pnl_usd(self, now: dt.datetime) -> float:
        row = self._db.execute(
            "SELECT pnl_usd FROM daily WHERE day=?", (_day(now),)
        ).fetchone()
        return float(row[0]) if row else 0.0

    def trip_loss_breaker(self, now: dt.datetime) -> None:
        self._db.execute(
            "INSERT INTO daily(day,pnl_usd,loss_breaker_tripped) VALUES(?,0.0,1) "
            "ON CONFLICT(day) DO UPDATE SET loss_breaker_tripped=1",
            (_day(now),),
        )

    def loss_breaker_tripped(self, now: dt.datetime) -> bool:
        row = self._db.execute(
            "SELECT loss_breaker_tripped FROM daily WHERE day=?", (_day(now),)
        ).fetchone()
        return bool(row and row[0])

    # --- pending approvals --------------------------------------------------

    def add_pending_approval(
        self, request_id: str, payload: dict, now: dt.datetime | None = None
    ) -> None:
        ts = (now or dt.datetime.now(dt.timezone.utc)).timestamp()
        self._db.execute(
            "INSERT INTO approvals(id,payload,status,created_at) "
            "VALUES(?,?,'pending',?) "
            "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            (request_id, json.dumps(payload), ts),
        )

    def pending_approvals(self) -> dict[str, dict]:
        return {
            r[0]: json.loads(r[1])
            for r in self._db.execute(
                "SELECT id,payload FROM approvals WHERE status='pending'"
            )
        }

    def approval_status(self, request_id: str) -> str | None:
        """None means never requested, which is not the same as denied — the
        caller decides what to do about each, and neither one is approval."""
        row = self._db.execute(
            "SELECT status FROM approvals WHERE id=?", (request_id,)
        ).fetchone()
        return row[0] if row else None

    def set_approval(self, request_id: str, status: str) -> None:
        if status not in ("granted", "denied"):
            raise ValueError(f"not an approval outcome: {status!r}")
        # Only a pending request can be answered. Re-answering a closed one is a
        # no-op, so a duplicate Telegram tap cannot resurrect a denial.
        self._db.execute(
            "UPDATE approvals SET status=? WHERE id=? AND status='pending'",
            (status, request_id),
        )

    def expire_approvals(self, now: dt.datetime, ttl_seconds: float) -> list[str]:
        """Deadline reached means DENIED. Silence is never consent: the only way
        an order gets through this gate is a human saying yes in time."""
        cutoff = now.timestamp() - ttl_seconds
        ids = [
            r[0]
            for r in self._db.execute(
                "SELECT id FROM approvals WHERE status='pending' AND created_at < ?",
                (cutoff,),
            )
        ]
        for request_id in ids:
            self._db.execute(
                "UPDATE approvals SET status='denied' WHERE id=?", (request_id,)
            )
        return ids

    # --- consultation threads -----------------------------------------------

    def open_thread_for(self, event_key: str, symbol: str, title: str,
                        now: dt.datetime) -> None:
        self._db.execute(
            "INSERT INTO threads(event_key,symbol,title,opened_at,open) "
            "VALUES(?,?,?,?,1) ON CONFLICT(event_key) DO UPDATE SET open=1",
            (event_key, symbol.upper(), title, now.isoformat()),
        )

    def open_thread(self) -> dict | None:
        row = self._db.execute(
            "SELECT event_key,symbol,title,opened_at FROM threads "
            "WHERE open=1 ORDER BY opened_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return {"event_key": row[0], "symbol": row[1], "title": row[2],
                "opened_at": row[3]}

    def close_thread(self) -> None:
        self._db.execute("UPDATE threads SET open=0 WHERE open=1")

    def was_asked(self, event_key: str) -> bool:
        """Asked at some point, answered or not. A question the operator chose
        not to answer is a kind of answer, and re-sending it every cycle is how
        a useful channel becomes one that gets muted."""
        return self._db.execute(
            "SELECT 1 FROM threads WHERE event_key=?", (event_key,)
        ).fetchone() is not None

    def resolve_approval(self, request_id: str) -> None:
        self._db.execute("DELETE FROM approvals WHERE id=?", (request_id,))
