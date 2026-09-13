# PLAN — autonomous trading agent

Dependency-ordered. `[P]` = parallelisable with its siblings, `[S]` = must follow
its predecessor.

## Where things live, and why

Code ships **in this repo** and is already on the Pi: `ansible-pull` clones to
`/opt/ansible-pull`, so the agent source arrives with every pull for free. No
copy step, no second deployment path, and the running code is always exactly
what is committed.

Mutable state lives **outside** that checkout, because the pull runs
`git clean -fd` on it:

| Path | Holds | Why there |
|---|---|---|
| `/opt/ansible-pull/trading_agent/` | source | arrives via the pull |
| `/opt/trading-agent/venv/` | virtualenv | survives `git clean` |
| `/opt/trading-agent/state.db` | SQLite | survives `git clean` |
| `/opt/trading-agent/logs/` | audit log | survives `git clean` |
| `/etc/trading-agent/env` | secrets | rendered from vault, 0600 root |

## Module contracts

Written before the code so tasks can be built in isolation.

### `config.py`
- **in** environment (from `/etc/trading-agent/env`)
- **out** frozen `Config`; raises at import if a required key is missing
- **contract** `config.endpoint` returns the PAPER url unless BOTH
  `TRADING_MODE=live` AND `LIVE_CONFIRMED=yes` are set. Two independent
  variables, so no single edit or typo can reach live. (ACCEPTANCE E1-E3)

### `state.py`
- **in** sqlite path
- **out** `State` — kill-switch flag, day counters, pending intents, positions
- **contract** every write is a transaction; kill-switch and counters survive
  restart. No other module writes this file. (B1, C2, D1)

### `guardrails.py` — the load-bearing module
- **in** `OrderIntent(symbol, side, notional, …)` + `State` + `Config`
- **out** `Decision(allowed: bool, reason: str)`
- **contract** pure, synchronous, no network, no LLM, no clock beyond an
  injected `now`. Every rejection names which limit it hit. (A1-A7)

### `broker.py`
- **in** an *approved* `OrderIntent`
- **out** broker order id
- **contract** the ONLY module importing the Alpaca order client. Its submit
  function refuses an intent that does not carry a guardrail approval token, so
  the check cannot be skipped by calling it directly. (A6)

### `universe.py`
- **in** cached XBI/IBB holdings
- **out** `is_biotech(symbol) -> bool`, `universe() -> set[str]`
- **contract** refresh is explicit; a stale cache is usable and logged, never
  fatal. Trading must not stop because a CDN was slow.

### `catalysts.py`
- **in** ClinicalTrials.gov API + Alpaca news
- **out** `Catalyst(symbol, title, date, source, url)`
- **contract** read-only; failure returns empty, never raises into the loop.

### `reasoning.py`
- **in** prompt + tool schema
- **out** structured decision
- **contract** talks to opencode on serverannah. **Unreachable backend means
  no new positions** — never guess, never retry into a trade. (O-02)

### `audit.py`
- **contract** one correlation id per decision chain, threaded through
  reasoning → intent → guardrail → broker. Rotating file handler with a byte
  cap. (F1-F3)

## Task graph

### Wave 0 — foundations `[P]`
- **T0.1** Python package skeleton, pyproject, pinned deps
- **T0.2** pytest harness wired into `scripts/lint.sh`
- **T0.3** `.claude/agents/` specialist definitions

### Wave 1 — pure core, no network `[P]` (needs T0)
- **T1.1** `config.py` + paper/live tests (E1-E3)
- **T1.2** `state.py` + persistence tests (B1, C2)
- **T1.3** `guardrails.py` + limit tests (A1-A5, A7)
- **T1.4** `audit.py` + rotation test (F1, F3)

### Wave 2 — boundaries `[S]` after Wave 1
- **T2.1** `broker.py` against a fake Alpaca; the A6 static check
- **T2.2** `universe.py` XBI/IBB cache
- **T2.3** `telegram_bot.py` — `/stop`, `/resume`, `/status`
- **T2.4** kill-switch-under-load test (B4)

### Wave 3 — integration `[S]`
- **T3.1** `catalysts.py`
- **T3.2** `reasoning.py` opencode client + fail-closed test
- **T3.3** `agent.py` LangGraph loop
- **T3.4** reconciliation on startup (D1, D2)

### Wave 4 — deployment `[S]`
- **T4.1** `roles/trading_agent/` — venv, env from vault, systemd unit
- **T4.2** `OnFailure=` wiring (G5), idempotency proof (G2)
- **T4.3** deploy to raspi, verify against live paper account

### Wave 5 — verification
- **T5.1** walk ACCEPTANCE item by item, each mapped to a passing check

## Order of attack
Wave 1 needs **no credentials and no network**, and contains the entire safety
layer. It is built and proven first: if the guardrails are not obviously correct
in isolation, nothing above them is worth writing.
