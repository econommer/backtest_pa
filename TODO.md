# TODO / Backlog

Parked items — **not now**. Revisit **after the engine is complete** (M1 done; ideally through M4 VCP so the design has proven itself on a real strategy).

---

## 1. Project overview / design doc  ⏸ deferred
Write a single doc that explains the whole project so a newcomer (human or agent) can get it fast. Should cover:
- **The ideas / intent** — what this project is and why (operationalize the brain's PA knowledge into a measurable backtester).
- **Code structure** — the layers (`data / engine / broker / risk / portfolio / context / regime / metrics / strategies`), what each is responsible for, and the Strategy⟂Engine boundary.
- **What it can support** — what kinds of strategies/data/metrics the current design handles (and what it deliberately doesn't yet).
- **Design roadmap** — where we are on the M0→M7 milestones and what's next (keep in sync with `BACKTESTING_PLAN.md` §9).
- **How to use it** — a worked example: define a run (config), plug a strategy + data adapter, run, read the report.

_(This is documentation of the finished design — worth doing once the engine + first real strategy are stable, so it doesn't churn.)_

## 2. Expand to other strategies  ⏸ deferred
VCP is the first strategy; add more on the **same frozen `Strategy` interface** so they run on the same engine and compare via the brain's `setup-scorecard`:
- Pocket Pivot  (brain `pocket-pivot-buy`)
- Buyable Gap Up  (brain `buyable-gap-up-entry`)
- False-breakout / reversal  (brain `false-breakouts`)
- Each: mechanize the rules, cite the brain page in docstrings, add its own tests, then backtest and backfill the setup page's Evidence.

_(Blocked on: engine complete + M4 VCP as the reference implementation to copy the pattern from.)_

---

_Added 2026-07-01. Keep this list short; move anything active into a superpowers plan under `docs/superpowers/plans/`._
