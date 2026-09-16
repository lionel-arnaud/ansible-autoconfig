"""The operator's daily page.

Rendered on the Raspberry Pi during the nightly backup push, from the same
consistent database snapshots that get backed up, then served by the server as
a static file behind its password. That arrangement is the point:

- the server never reads the agent's databases or holds a broker credential,
  and nothing new is able to reach the Pi from outside;
- rendering touches snapshots only, opened read-only, so it cannot disturb the
  running agent or the backup it rides along with;
- the page is at most a day old and says so, because the operator asked for a
  standing reminder rather than a guarantee of freshness.

Every value that comes out of a database is HTML-escaped: notes are dictated
free text.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import sqlite3
from pathlib import Path

from trading_agent.audit import AuditLog
from trading_agent.views import ViewStore

STALE_AFTER_HOURS = 36
_STANCE = {
    "positive": "Yes, it will succeed",
    "negative": "No, it will not",
    "no_opinion": "Skip, no view",
}
_AGENT_EVENTS = ("reconcile", "catalysts", "startup_reconcile")


def _read_only(path: Path) -> sqlite3.Connection | None:
    if not path.exists():
        return None
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def collect(root: Path, *, broker_summary: dict, limits: dict,
            now: dt.datetime, days: int = 7) -> dict:
    """Gather everything the page shows. Each source degrades on its own: a
    missing or unreadable one empties its section and nothing else."""
    root = Path(root)
    today = now.date().isoformat()

    agent = {"kill_switch": False, "trades_today": 0, "loss_breaker": False}
    open_question = None
    titles: dict[str, str] = {}
    db = _read_only(root / "state.db")
    if db is not None:
        try:
            row = db.execute("SELECT value FROM flags WHERE key='kill_switch'").fetchone()
            agent["kill_switch"] = bool(row and row[0] == "1")
            agent["trades_today"] = db.execute(
                "SELECT count(*) FROM trades WHERE day=?", (today,)).fetchone()[0]
            row = db.execute("SELECT loss_breaker_tripped FROM daily WHERE day=?",
                             (today,)).fetchone()
            agent["loss_breaker"] = bool(row and row[0])
            for key, symbol, title, opened_at, is_open in db.execute(
                    "SELECT event_key,symbol,title,opened_at,open FROM threads"
                    " ORDER BY opened_at"):
                titles[key] = title
                if is_open:
                    open_question = {"event_key": key, "symbol": symbol,
                                     "title": title, "opened_at": opened_at}
        except sqlite3.Error:
            pass
        finally:
            db.close()

    try:
        raw = json.loads((root / "universe.json").read_text())
        names = {k.upper(): v for k, v in (raw.get("names") or {}).items() if v}
    except Exception:  # noqa: BLE001 — names are cosmetic
        names = {}

    log = AuditLog.reader(root / "logs" / "audit.log")
    entries = log.entries()
    history: dict[tuple, list] = {}
    for e in entries:
        if e.get("event") in ("view_recorded", "view_updated"):
            d = e.get("data") or {}
            history.setdefault((d.get("symbol"), d.get("event")), []).append(
                {"ts": e.get("ts", ""), "stance": d.get("stance"),
                 "confidence": d.get("confidence")})

    answers: list[dict] = []
    scoreboard = None
    if (root / "views.db").exists():
        store = ViewStore.read_only(root / "views.db")
        try:
            outcomes = store.outcome_map()
            for v in store.all_views():
                outcome = outcomes.get((v["symbol"], v["event_id"]))
                correct = (None if outcome is None or v["stance"] == "no_opinion"
                           else v["stance"] == outcome)
                answers.append({
                    **v,
                    "company": names.get(v["symbol"], ""),
                    "title": titles.get(v["event_id"], ""),
                    "outcome": outcome,
                    "correct": correct,
                    "changes": max(0, len(history.get((v["symbol"], v["event_id"]), [])) - 1),
                })
            scoreboard = store.scoreboard()
        except sqlite3.Error:
            pass
        finally:
            store.close()

    reports = []
    for i in range(days):
        day = (now.date() - dt.timedelta(days=i)).isoformat()
        text = log.day_report(day)
        if "nothing recorded" not in text:
            reports.append({"day": day, "text": text})

    if open_question:
        open_question["company"] = names.get(open_question["symbol"], "")

    return {
        "generated_at": now.isoformat(),
        "agent": agent,
        "last_cycle": max((e.get("ts", "") for e in entries
                           if e.get("event") in _AGENT_EVENTS), default=""),
        "broker": broker_summary or {"available": False},
        "limits": limits or {},
        "open_question": open_question,
        "answers": answers,
        "scoreboard": scoreboard,
        "reports": reports,
    }


# --------------------------------------------------------------------------- #
# Rendering

def _e(value) -> str:
    return html.escape("" if value is None else str(value))


def _money(value) -> str:
    try:
        return f"${float(value):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _when(ts: str) -> str:
    try:
        moment = dt.datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return ts or "—"
    return moment.astimezone(dt.timezone.utc).strftime("%d %b %Y, %H:%M UTC")


def _who(company: str, symbol: str) -> str:
    return f"{company} ({symbol})" if company else symbol


def _registry(event_id: str) -> str:
    if not (event_id or "").upper().startswith("NCT"):
        return ""
    return (f' <a href="https://clinicaltrials.gov/study/{_e(event_id)}"'
            f' rel="noopener noreferrer">registry page</a>')


_CSS = """
/* Palette chosen by the operator: deep navy through to a single orange accent.
   Gains and losses keep a green and a red, because on a money page colour is
   information rather than decoration, and navy-on-navy cannot carry it. */
:root{--bg:#f5f7fb;--fg:#253c6d;--muted:#455b8a;--card:#ffffff;--line:#dbe2f0;
--accent:#f2842f;--accent-bg:#fdefe1;--good:#1f7a4d;--bad:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#1b2a4e;--fg:#eef2fa;--muted:#a9b8d8;
--card:#253c6d;--line:#455b8a;--accent:#f2842f;--accent-bg:#30497d;
--good:#6fd3a0;--bad:#ff9a8f}}
*{box-sizing:border-box}body{margin:0;font:15px/1.5 system-ui,sans-serif;
background:var(--bg);color:var(--fg)}main{max-width:980px;margin:0 auto;padding:16px}
h1{font-size:22px;margin:8px 0 2px;color:var(--fg)}
h2{font-size:17px;margin:0 0 10px;color:var(--fg)}
section{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:14px 16px;margin:12px 0}.muted{color:var(--muted)}
.banner{background:var(--accent-bg);border-left:4px solid var(--accent);
border-radius:10px;padding:10px 14px}
.banner.stale{background:var(--accent);border-left-color:#253c6d;color:#253c6d;
font-weight:600}
.badge{display:inline-block;padding:1px 8px;border-radius:99px;border:1px solid var(--line);
font-size:12px;font-weight:600}.good{color:var(--good)}.bad{color:var(--bad)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.kpi{border:1px solid var(--line);border-radius:8px;padding:8px 10px}
.kpi b{display:block;font-size:18px}.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:6px 8px;
border-bottom:1px solid var(--line);vertical-align:top}th{font-size:12px;color:var(--muted)}
pre{white-space:pre-wrap;font:inherit;margin:0}a{color:var(--accent)}
"""

_AGE_SCRIPT = """
(function(){var g=new Date(document.body.getAttribute('data-generated'));
var h=(Date.now()-g.getTime())/36e5,el=document.getElementById('age');
if(!el||isNaN(h))return;el.textContent=h<1?'less than an hour ago':Math.round(h)+' hours ago';
if(h>%d){document.getElementById('banner').className='banner stale';
el.textContent+=' (older than expected: the nightly push may have failed)';}})();
""" % STALE_AFTER_HOURS


def render(data: dict) -> str:
    agent, broker, limits = data["agent"], data["broker"], data["limits"]
    mode = ("LIVE MONEY" if limits.get("live") else "PAPER") if limits else "UNKNOWN"
    parts = []

    parts.append(
        '<div class="banner" id="banner"><b>Daily snapshot, not live.</b> '
        f'Generated {_e(_when(data["generated_at"]))} (<span id="age">see time</span>). '
        'Refreshed once a day, overnight, so everything below may be up to a day '
        'old. For the current state, send /status or /today to the agent.</div>'
    )

    status = ('<span class="bad">HALTED</span>' if agent["kill_switch"]
              else '<span class="good">running</span>')
    breaker = (' <span class="bad">Daily loss breaker tripped.</span>'
               if agent["loss_breaker"] else "")
    parts.append(
        '<section><h2>The agent</h2><div class="grid">'
        f'<div class="kpi">Trading<b>{status}</b></div>'
        f'<div class="kpi">Last activity<b>{_e(_when(data["last_cycle"]))}</b></div>'
        f'<div class="kpi">Trades that day<b>{_e(agent["trades_today"])}</b></div>'
        f'<div class="kpi">Account<b>{_e(mode)}</b></div>'
        f'</div>{breaker}'
        + (f'<p class="muted">Hard limits, enforced in code: at most '
           f'{_money(limits.get("max_position_usd"))} per position, '
           f'{_money(limits.get("max_deployed_usd"))} invested in total, '
           f'{_e(limits.get("max_trades_per_day"))} trades a day, and trading stops '
           f'for the day after a {_money(limits.get("daily_loss_limit_usd"))} loss.</p>'
           if limits else "")
        + '</section>'
    )

    if broker.get("available"):
        positions = broker.get("positions") or []
        invested = sum(p.get("market_value", 0.0) for p in positions)
        rows = "".join(
            f'<tr><td>{_e(p["symbol"])}</td><td>{_e(round(p["qty"], 4))}</td>'
            f'<td>{_money(p["market_value"])}</td>'
            f'<td class="{"good" if p["unrealized_pl"] >= 0 else "bad"}">'
            f'{_money(p["unrealized_pl"])} ({p["unrealized_plpc"] * 100:+.1f}%)</td></tr>'
            for p in positions)
        parts.append(
            '<section><h2>Portfolio</h2><div class="grid">'
            f'<div class="kpi">Account value<b>{_money(broker.get("equity"))}</b></div>'
            f'<div class="kpi">Cash<b>{_money(broker.get("cash"))}</b></div>'
            f'<div class="kpi">Invested<b>{_money(invested)}</b></div></div>'
            + (f'<div class="scroll"><table><tr><th>Stock</th><th>Shares</th>'
               f'<th>Value</th><th>Gain or loss</th></tr>{rows}</table></div>'
               if positions else '<p class="muted">No positions held.</p>')
            + '</section>')
    else:
        parts.append('<section><h2>Portfolio</h2><p class="muted">Portfolio '
                     'unavailable: the broker could not be reached when this page '
                     'was generated.</p></section>')

    q = data["open_question"]
    if q:
        parts.append(
            '<section><h2>Waiting for your answer</h2>'
            f'<p><b>{_e(_who(q.get("company", ""), q["symbol"]))}</b>: {_e(q["title"])}'
            f'{_registry(q["event_key"])}</p>'
            f'<p class="muted">Asked {_e(_when(q["opened_at"]))}. Reply on Telegram, '
            f'starting with {_e(q["symbol"])}:</p></section>')
    else:
        parts.append('<section><h2>Waiting for your answer</h2>'
                     '<p class="muted">No question waiting.</p></section>')

    answers = data["answers"]
    if answers:
        def result(a):
            if a["outcome"] is None:
                return '<span class="muted">awaiting results</span>'
            if a["correct"] is None:
                return f'result: {_e(a["outcome"])}, not scored'
            return ('<span class="good">you were right</span>' if a["correct"]
                    else '<span class="bad">you were wrong</span>')
        rows = "".join(
            f'<tr><td><b>{_e(_who(a["company"], a["symbol"]))}</b><br>'
            f'<span class="muted">{_e(a["title"])}</span>{_registry(a["event_id"])}</td>'
            f'<td>{_e(_STANCE.get(a["stance"], a["stance"]))}'
            + (f'<br>confidence {_e(a["confidence"])}/5' if a["stance"] != "no_opinion" else "")
            + (f'<br><span class="muted">changed {_e(a["changes"])} time(s)</span>'
               if a["changes"] else "")
            + f'</td><td>{_e(a["note"]) or "<span class=muted>—</span>"}</td>'
            f'<td>{_e(_when(a["recorded_at"]))}</td><td>{result(a)}</td></tr>'
            for a in answers)
        parts.append(
            '<section><h2>Your calls</h2><div class="scroll"><table><tr>'
            '<th>Company and trial</th><th>Your answer</th><th>Your reasoning</th>'
            '<th>Answered</th><th>Result</th></tr>'
            f'{rows}</table></div><p class="muted">To change a call before its '
            'results, reply on Telegram starting with the ticker.</p></section>')
    else:
        parts.append('<section><h2>Your calls</h2>'
                     '<p class="muted">No calls recorded yet.</p></section>')

    s = data["scoreboard"]
    if s and s.get("scored"):
        caveat = ("" if s.get("significant") else
                  '<p class="muted">Fewer than 30 scored calls: any edge shown here '
                  'is still mostly noise.</p>')
        edge = s.get("edge_over_base")
        parts.append(
            '<section><h2>Scoreboard</h2><div class="grid">'
            f'<div class="kpi">Scored calls<b>{_e(s["scored"])}</b></div>'
            f'<div class="kpi">Right<b>{s["accuracy"] * 100:.0f}%</b></div>'
            f'<div class="kpi">Chance alone<b>{s["base_rate"] * 100:.0f}%</b></div>'
            f'<div class="kpi">Your edge<b class="{"good" if (edge or 0) > 0 else "bad"}">'
            f'{(edge or 0) * 100:+.0f} pts</b></div></div>{caveat}</section>')
    else:
        parts.append('<section><h2>Scoreboard</h2><p class="muted">Nothing scored '
                     'yet: a call is scored once its trial reports.</p></section>')

    reports = "".join(
        f'<h3 class="muted" style="font-size:14px;margin:12px 0 4px">{_e(r["day"])}</h3>'
        f'<pre>{_e(r["text"].replace("*", ""))}</pre>' for r in data["reports"])
    parts.append('<section><h2>The last seven days</h2>'
                 + (reports or '<p class="muted">No activity recorded.</p>')
                 + '</section>')

    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex,nofollow">'
        '<title>Trading agent — daily snapshot</title>'
        f'<style>{_CSS}</style></head>'
        f'<body data-generated="{_e(data["generated_at"])}"><main>'
        '<h1>Trading agent</h1><p class="muted">Daily snapshot of the biotech '
        'research assistant.</p>'
        + "".join(parts)
        + f'</main><script>{_AGE_SCRIPT}</script></body></html>'
    )


# --------------------------------------------------------------------------- #
# Entry point

def _load_env_file(path: str) -> None:
    """KEY=VALUE lines, read the way systemd reads them and never handed to a
    shell: the values include passwords, and a shell would act on their
    punctuation."""
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Render the operator's daily page.")
    parser.add_argument("--root", required=True, help="directory of snapshots")
    parser.add_argument("--out", required=True, help="HTML file to write")
    parser.add_argument("--env-file", help="systemd-style environment file")
    args = parser.parse_args(argv)
    if args.env_file:
        _load_env_file(args.env_file)

    now = dt.datetime.now(dt.timezone.utc)
    summary: dict = {"available": False}
    limits: dict = {}
    try:
        from trading_agent.broker import Broker
        from trading_agent.config import Config

        config = Config.from_env()
        limits = {
            "live": config.is_live,
            "max_position_usd": config.max_position_usd,
            "max_deployed_usd": config.max_deployed_usd,
            "max_trades_per_day": config.max_trades_per_day,
            "daily_loss_limit_usd": config.daily_loss_limit_usd,
        }
        summary = Broker.from_config(config).account_summary()
    except Exception:  # noqa: BLE001 — a page without a portfolio beats no page
        pass

    page = render(collect(Path(args.root), broker_summary=summary,
                          limits=limits, now=now))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(page, encoding="utf-8")
    os.replace(tmp, out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
