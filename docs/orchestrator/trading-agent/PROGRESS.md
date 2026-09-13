# PROGRESS — autonomous trading agent

## Status: waves 1-4 largely built. 62/62 tests green.

Branch `feat/trading-agent`, pushed. Tests run inside `scripts/lint.sh`, so the
pre-commit hook gates them with the Ansible linting.

### Complete
| Task | Module | Acceptance |
|---|---|---|
| T1.1 | `config.py` — two-signal live gate | E1-E3 |
| T1.2 | `state.py` — SQLite, survives restart | B1, C2 |
| T1.3 | `guardrails.py` — the deterministic layer | A1-A7 |
| T1.4 | `audit.py` — correlation ids, rotation, redaction | F1-F3 |
| T2.1 | `broker.py` — sole Alpaca path, idempotency | A6, D1-D2 |
| T2.2 | `universe.py` — ETF-derived, offline seed | — |
| T2.3 | `commands.py` — /stop /resume /status | B1-B4 |
| T3.1 | `catalysts.py` — ClinicalTrials.gov + news | — |
| T3.2 | `reasoning.py` — opencode, fail-closed | O-02 |
| —    | `market.py` — regular hours only | H1 |
| T4.1 | `roles/trading_agent/` — venv, env, unit | G1 |

### Verified here, not taken on trust
Every figure above was re-run by the orchestrator after implementation:
`pytest tests/ -q` -> 62 passed. Two tests are structural rather than
behavioural (only `broker.py` imports Alpaca; only `config.py` names the live
endpoint) and grep the tree, so they keep holding as the code grows.

### Remaining
- `telegram_bot.py` — transport. `commands.py` already holds the logic and is
  tested independently of it, which is what makes B4 hold.
- `agent.py` — the LangGraph loop tying catalysts -> reasoning -> guardrail ->
  broker.
- `main.py` — entrypoint: reconcile, then loop.
- Wave 4 deploy to raspi and the live paper-account check (H2).
- Wave 5 ACCEPTANCE walk.

### Blockers
`OPENCODE_URL` is unset — needed before the loop can reason. Everything else is
credential-free and done.

### Budget
Comfortable. State flushed to disk and committed after each step.

## 2026-09-11 — Phase 4/5: deployed to raspi, acceptance walked

Branch `feat/trading-agent`, 222 tests green. Deployed via the real
`ansible-pull` mechanism on the branch, eleven runs.

Host-level items, verified on raspi rather than by unit test:

- **G1** deployed by `roles/trading_agent`, never by hand. First run failed:
  pip builds a local directory in place and the pull checkout is root-owned
  while the build runs as the agent user. Source is now mirrored to
  `/opt/trading-agent/src` with `rsync --delete`.
- **G2** `changed=0` on a consecutive run (pull4.log). The one earlier flip was
  the base role re-chowning files that the git update had re-rooted, which
  settles by the following run. The reinstall is gated on the mirror changing
  or the venv being empty, because `pip install --upgrade <dir>` reports
  success unconditionally.
- **D3** `systemctl is-enabled` = enabled; `kill -9` produced a new PID and
  `NRestarts=1`; a full reboot brought the unit back on its own.
- **G5** proven by an unplanned failure: the unit crash-looped once on a real
  bug, `OnFailure=` fired, and a notification with journal context arrived on
  the raspi ntfy topic. `StartLimit*` were in `[Service]`, where systemd
  ignores them — the rate limit was never in effect. Moved to `[Unit]`.
- **G6** `/etc/trading-agent/env` is 0600 root, rendered from the vault, every
  key present. Its only inputs are the vault file and role defaults.

**H2 remains open** and is the only one: a paper order needs a recorded view,
and a view needs the operator to answer a Telegram question. Everything up to
that point runs — the agent proposed BMRN $100 off a real Phase 3 readout and
its own view gate held it.

### What the deploy found that the tests could not

Every one of these passed 200+ green tests and was still wrong in production:

1. `CatalystFeed(universe)` was built with no HTTP clients. Both methods
   return `[]` by contract when their client is missing, so the agent ran
   clean cycles reporting zero catalysts and nothing failed.
2. The whole consultation subsystem was orphaned — nothing in the codebase
   constructed an `Event`. The agent could propose a trade and then refuse
   itself forever for a view it had no way to ask for.
3. `ReasoningClient` had no `ask()`. `research()` caught the AttributeError
   and returned `ok=False`, so every brief failed silently.
4. The registry was searched by ticker. `query.term=ACAD` matched "Academy"
   and "Acute"; the first question ever sent asked about an obesity study run
   by a company the agent cannot trade.
5. ClinicalTrials.gov 429'd an unspaced 149-symbol sweep, so most of the
   universe came back empty and the agent reasoned over a partial picture
   without knowing it was partial.
6. Telegram rejected the first well-sourced question as unparseable Markdown
   and `send()` discarded the reason.

The lesson is in `tests/test_main_wiring.py`: the tests asserted behaviour of
components and never that production actually connected them.
