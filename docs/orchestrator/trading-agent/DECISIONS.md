# DECISIONS — autonomous trading agent

## ASSUMED (defaulted; say the word and any of these changes)

- **A-01 Lives in this repo** as `roles/trading_agent/`, not a separate repo.
  Follows the amendment that this repo's conventions win, and means a rebuilt Pi
  restores the agent automatically.
- **A-02 Secrets are vault-encrypted in the repo**, not hand-placed on the Pi.
  A vault password now exists at `~/secret.txt` on raspi, so a nightly
  `ansible-pull` can decrypt. This beats host-only files on the one axis that
  matters here: a rebuilt SD card restores the keys with no manual step, which
  host-only files cannot.
- **A-03 The `.env` is rendered by Ansible** from vaulted values, not
  hand-edited. The brief asked for a gitignored `.env`; the file still exists
  and is still gitignored, but it is generated, so it survives a rebuild.
- **A-04 SQLite, not JSON**, for state. Concurrent reads from the Telegram
  handler and the reasoning loop, plus the need for atomic writes around order
  submission, are exactly what a JSON file handles badly.
- **A-05 Reasoning loop is event-driven**, triggered by a schedule during market
  hours and by incoming Telegram messages — not a tight poll. Cheaper in tokens
  and easier to reason about.
- **A-06 One systemd unit**, not separate agent/bot services. Two processes
  sharing SQLite state and a kill switch is a distributed-systems problem this
  project does not need.
- **A-07 Client-side idempotency key** on every order so a crash between
  "decided" and "submitted" cannot double-fill on restart (D2).
- **A-08 US equities only** for v1, regular hours, no options/crypto/shorting.
  Narrower blast radius while the guardrails are still unproven.
- **A-09 Approval timeout = DENY.** An unanswered approval must never become an
  approval. Timeout value goes in config.
- **A-10 Unattended nightly upgrades stay ON.** Operator decision, made
  knowingly. Accepted risk, recorded rather than silently inherited: a nightly
  `apt upgrade dist` can restart services or replace the Python under a venv
  mid-session. Mitigations that follow from it: the venv pins its own
  interpreter, the unit restarts on failure, and `OnFailure=` alerts.

- **A-11 NOT LangGraph** — flagged, because the brief named it explicitly.

  LangGraph earns its weight through branching, tool orchestration and
  human-in-the-loop nodes. Two of those three are now gone: reasoning happens
  inside opencode (O-02), which runs its own agent loop, and mandatory approval
  was removed (O-01). What remains is a straight line — reconcile, gather,
  reason, guardrail, submit — and `agent.py` expresses it in about eighty lines
  with no framework.

  Adding langchain + langgraph to a Raspberry Pi to express a straight line
  would be weight without benefit, and every dependency sitting near an order
  path is a liability on a host that dist-upgrades itself nightly.

  Easy to revisit: if the flow later grows real branching, the cycle is one
  function and the stages are already separate modules.

  **This contradicts the brief and is the operator's call to overturn.**

- **O-09 Research is rationed, deliberately.** Deep research per catalyst costs
  real tokens on the operator's own account, so most events must not qualify.
  Two gates:

  * materiality — only HIGH events are always researched; MEDIUM only when no
    view exists; LOW never;
  * an existing view suppresses further research, because a held view is the
    answer research was trying to produce. Only a HIGH event overrides that,
    since an amendment or a termination can genuinely invalidate an earlier
    read.

- **O-10 Views are keyed on the trial, not the news item.** One read on NCT123
  answers for its interim analysis, its amendments and its final readout. Both
  cheaper and closer to how the judgment actually works — an opinion is about
  the science, not about a headline.

- **O-11 Financial events are surfaced but never scored.** Earnings move prices
  and are worth reading, but a call on one says nothing about biotech judgment.
  Scoring them would dilute the single number meant to measure domain skill.

- **O-12 Operator context that shapes output.** Recorded because it changes
  what the model should produce, not as trivia:

  * Paid subscriptions to **Le Monde** and **The New York Times**. A paywalled
    link they cannot open is worse than no link — it looks like evidence and is
    not. Primary sources still outrank all journalism.
  * They **dictate** most replies, so long answers are cheap and terse ones are
    not the target. The reply format asks for a stance word first, then
    whatever they want to say, and keeps all of it.
  * They read biotech as a professional. Briefs are written for someone who
    understands clinical development, not for a retail investor.

- **O-13 Follow-up questions cannot move money.** A follow-up thread answers
  questions and nothing else — structurally unable to reach the broker or the
  guardrail, enforced by a test. Positions change only through a recorded view,
  so the chattiest possible conversation still cannot place a trade.

  Ambiguous messages route to "question" rather than "answer", deliberately
  asymmetric: an answer misread as a question gets asked back, whereas a
  question misread as an answer would record a view the operator never gave.

## ACCEPTED RISKS
- **R-01** Nightly unattended upgrades on a machine running a financial process
  (see A-10). Operator-accepted; amount at risk is small.
- **R-02** The Alpaca paper keys were pasted into a chat transcript. Paper only,
  so the exposure is limited to a simulated account, but they should still be
  rotated before real use. See QUESTIONS.

## OPERATOR OVERRIDES (round 2) — decisions that changed the design

- **O-01 CORRECTED.** Originally recorded as "no human in the loop", which
  conflated two different things. The operator removed *blocking approval on
  every trade*; they did not remove *consultation*, which was the actual reason
  Telegram is in this design at all. See O-06 — the corrected shape.

- **O-06 Consultation, batched and ahead of time.** The agent asks the operator
  for a view on upcoming catalysts in a periodic session (weekly, or when a
  catalyst window opens), stores those views, and the trading loop reads them
  later. It never blocks on a reply.

  Why this beats a mid-decision interrupt: questions arrive when there is time
  to think rather than when the market forces it, the loop stays the straight
  line it is, and a stored view is a *prediction made before the outcome* —
  which makes it scoreable afterwards.

  That scoring is the point. The operator's stated main objective is learning
  the field, and "you have called 9 of 12 phase-3 oncology readouts correctly"
  is worth more than any amount of model cleverness. It costs almost nothing
  once views carry timestamps.

- **O-07 A stored view gates 100% of opening trades.** This makes the operator's
  judgment the alpha source and the agent the execution-and-discipline layer,
  rather than an LLM guessing at biotech outcomes — a worse product that also
  teaches nothing. Consequence, accepted deliberately: in a week with no
  answers, the agent opens nothing. That is correct behaviour, not a fault.

  One exception: **closing** a position needs no view. Getting out is risk
  reduction and must not wait on anyone's availability.

- **O-08 Not n8n.** Good glue for scheduled API plumbing, but scheduling here is
  already systemd timers, and the parts that matter — guardrails, idempotency,
  reconciliation — need tested code rather than a visual flow. Money-critical
  logic that cannot be unit-tested is the wrong trade, and it would add a
  container plus a database to a Pi for glue that is not needed.

- **O-01 (original text) No mandatory human approval.** The original brief listed
  human-in-the-loop as non-negotiable; the operator has deliberately reversed
  that, wanting to see what the agent does autonomously with a small, isolated,
  written-off amount. Recorded as a reversal rather than quietly dropped,
  because it removes one of the two brakes the brief was built around.

  Consequence, stated plainly: **the deterministic guardrails become the ONLY
  thing standing between the agent and the account.** Every acceptance item in
  section A gets stricter as a result, not looser.

  Implementation: the approval code path is still built, with the threshold
  defaulting to "never ask". Re-enabling it is then a config change rather than
  a rewrite — which matters the first time something surprising happens.
  The agent may still *ask for an opinion*; it just does not *block* on one.

- **O-02 Reasoning runs through opencode on serverannah** (option (a)), so the
  provider can be swapped without touching this code.

  Consequence: the Pi now depends on another host being up. For a process that
  can hold positions, that is a real failure mode, so it is handled explicitly —
  losing opencode must mean **stop opening new positions**, never retry blindly
  or guess. The guardrails and kill switch are deliberately LLM-free and keep
  working when serverannah does not.

- **O-03 Account: $1000 to start**, cap configurable.
- **O-04 Instrument selection by exchange + sector filter**, not a hand-kept
  list. See QUESTIONS: Alpaca's asset API does not carry a usable sector field,
  so the filter needs a concrete data source before it can be enforced
  deterministically.
- **O-05 News from Alpaca**, included with the existing keys.

## OPEN — see QUESTIONS in the Phase 0 output
Language choice (Python vs Rust), the meaning of "pauto", risk parameters, the
instrument universe, and the missing credentials.
