# PA Strategy Backtesting Framework — Project Guide (for Claude Code)

Read **`BACKTESTING_PLAN.md`** in this folder first — it is the authoritative design doc. This file is a quick orientation + conventions.

## What this is
A **reproducible, quantitatively verifiable backtesting framework** that operationalizes the trading knowledge in the sibling knowledge base at `../wiki/` (an Obsidian/markdown "brain"). The first concrete strategy is **VCP**; the engine must stay strategy-agnostic so Pocket Pivot and Buyable Gap Up can plug in later.

> Domain reminder (from the brain): this is for **studying and backtesting** price-action strategies. Document and measure — never place live trades, move money, or give buy/sell recommendations.

## Locked decisions (see Decision Log in the plan)
1. **Data:** prototype on free data first (`yfinance`/Stooq), move to a paid survivorship-free provider (Norgate preferred) in Phase 2. TradingView is a manual-validation tool only, not a programmatic data backbone.
2. **Engine:** build a **lightweight custom event-driven engine** (no zipline/backtrader/vectorbt).
3. **First VCP scope:** daily bars + US equities; Relative Strength approximated by whole-universe ROC ranking; industry RS deferred to Phase 2.

## Non-negotiable architecture principle
**Strategy ⟂ Engine.** The engine knows nothing about "VCP." It feeds data, collects a strategy's *intentions* (`Signal`s), simulates execution + bookkeeping, and computes metrics. Strategies live in `src/btf/strategies/` and depend only on the `Strategy` interface + the `Context` the engine passes in. Data access goes through the `DataProvider` interface — never bind a strategy or the engine to a specific vendor.

## Layout (see plan §8)
```
src/btf/{data,engine,broker,risk,portfolio,context,regime,metrics,strategies}
scripts/        # runnable entry points (fetch_snapshot, run_vcp, run_asset_classes)
tests/          # invariants (esp. no look-ahead) — run: python -m pytest
docs/superpowers/{plans,specs}/   # per-milestone design docs
config/         # (target) one YAML = one fully-defined run — not built yet, lands with M5
```

## Conventions
- **Python**, type hints everywhere, `Protocol`-based interfaces. Reporting via matplotlib/plotly.
- **Config-driven runs**: a run is fully defined by a YAML (universe / period / params / cost assumptions). Same config ⇒ same result.
- **Metrics in R units** (`R = initial risk`): win rate, avg win/loss R, **expectancy**, max losing streak, max drawdown, profit factor, regime breakdown, benchmark vs buy-and-hold. Output should drop into the brain's `vcp-breakout` backtest-notes template.
- **Tests guard invariants**, especially: the engine must never expose future bars to a strategy.

## Bias defenses are enforced by the framework (the brain insists on these)
- **Look-ahead:** `Context` exposes only data ≤ current bar; signals on close, fills on a later bar; RS/industry must be point-in-time.
- **Survivorship:** Phase 2 uses delisted-inclusive universe; Phase 1 must clearly flag the bias in reports.
- **Overfitting:** in-sample/out-of-sample split, walk-forward, parameter-sensitivity reporting; treat <30-trade samples conservatively.
- **Realistic costs:** slippage + commission + **gap-through stops** (a gap can jump a stop → fill at the open).

## Brain cross-references (the "why" behind the rules)
`../wiki/concepts/relative-strength.md`, `initial-stop-and-r-multiple.md`, `expectancy-and-position-sizing.md`, `trailing-stops.md`, `volatility-contraction.md`, `gap-risk.md`, `situation-awareness.md`; setup `../wiki/setups/vcp-breakout.md`; playbook `../wiki/playbooks/momentum-trend-trading-system.md`. When implementing a rule, trace it back to its source page.

## Status / next step
**M0–M4 done** (interfaces frozen → engine + fake data → yfinance/Stooq adapters + parquet cache → R-metrics/regime/benchmark → mechanized VCP with first real-data report; 83 tests green, `ruff` + `mypy src` clean). See README.md roadmap table and `docs/superpowers/` for the per-milestone designs.

Next milestone is **M5: bias defenses** — in-sample/out-of-sample split, walk-forward, and parameter-sensitivity reporting on top of the existing engine (plan §6/§9). Config-driven YAML runs (core principle 5) are still unimplemented and are the natural substrate for M5's parameter sweeps — build that first.

## Tooling
Recommended dev workflow plugin: **Superpowers** (TDD + planning methodology). Install it inside Claude Code — see `SETUP_SUPERPOWERS.md`.
