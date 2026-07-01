# M3 — Regime Engine + Benchmark Comparison (Design Spec)

- **Date:** 2026-07-01
- **Milestone:** M3 (see `BACKTESTING_PLAN.md` §9)
- **Scope:** Discharge the two `BacktestResult` fields M1 deliberately stubbed and deferred to M3:
  `regime_breakdown` and `benchmark_curve` — plus the strategy-agnostic **regime engine** needed to
  make the breakdown honest.
- **Status:** Approved for implementation.
- **Depends on:** M1 (engine runs end-to-end, merged).

> **Scope provenance.** The master `BACKTESTING_PLAN.md` (which numbers the milestones) is not in the
> repo, so M3's scope here is **derived from the only authoritative in-repo source**: M1 design spec
> decision **D2** — *"Compute core `Metrics` honestly in M1 … `regime_breakdown={}`,
> `benchmark_curve=None` deferred to M3."* If the master plan defines M3 differently, revisit before
> merge. (M2 is likewise defined only in the missing plan and is intentionally not addressed here.)

> Domain reminder: for **studying and backtesting** only. Document and measure — never place live
> trades, move money, or give buy/sell recommendations.

---

## 1. Goal

Make a backtest **regime-aware** and **benchmark-relative** without changing the frozen M0 contract:

- a concrete, reusable `RegimeClassifier` (situation-awareness) that labels each day BULL/BEAR/RANGE/
  UNKNOWN from a benchmark index — belongs to no single strategy,
- the engine feeds the **real** regime into `MarketContext` each bar (instead of `Regime.UNKNOWN`) and
  tags each `Trade` with the regime **at entry**,
- `BacktestResult.regime_breakdown` = per-regime `Metrics`,
- `BacktestResult.benchmark_curve` = a buy-and-hold-the-benchmark equity curve, comparable to the
  strategy's `equity_curve`.

**Acceptance:** with a benchmark configured, `ctx.market.regime` is a real (non-UNKNOWN) label after
warmup, trades carry their entry regime, `benchmark_curve` starts at `starting_cash`, and
`regime_breakdown` partitions the trades by regime; **all 45 M0+M1 tests stay green** (no benchmark ⇒
identical M1 behaviour: `regime_breakdown={}`, `benchmark_curve=None`).

## 2. Non-negotiables

- **No M0 contract change.** `Trade.regime`, `MarketContext.regime/index_trend`,
  `BacktestResult.regime_breakdown/benchmark_curve` are all already frozen fields — M3 only *populates*
  them. The regime engine is a new internal component, not a contract change.
- **Strategy ⟂ Engine.** The classifier reads only the benchmark index; it knows nothing about any
  strategy. Strategies *may* read `ctx.market.regime` as an entry gate later, but M1's `BuyAndHold`
  ignores it, so its results are unchanged.
- **No look-ahead.** The regime for day *t* is computed from benchmark history with timestamp ≤ *t*
  only — same firewall as prices. Classified at the **top** of each iteration so entries filled that
  day are tagged with a regime that used no future data.

## 3. Locked decisions

| # | Decision |
|---|----------|
| E1 | **Regime is computed from a single benchmark index** (`config["benchmark"]`, e.g. `"SPX"`), fetched via `DataProvider.index`. No benchmark configured ⇒ classifier never runs, regime stays UNKNOWN, and the result matches M1 exactly. |
| E2 | **Default classifier = `SmaRegimeClassifier`** (close vs N-day SMA + SMA slope). Pluggable via `BasicEngine(classifier=...)`; `run()`'s frozen signature is untouched. |
| E3 | **A trade's regime = the regime on its entry-fill day.** Recovered by threading the day's regime into `Portfolio.apply_entry`; stop-outs and final liquidation keep the entry regime (a trade has one regime, set when the risk was taken). |
| E4 | **`benchmark_curve` is normalised to `starting_cash`**: `starting_cash · index / index.iloc[0]`, reindexed onto the equity-curve dates (ffill). It is a buy-and-hold-the-index equity curve, directly comparable to `equity_curve`. |
| E5 | **Per-regime `Metrics` reuse `compute_metrics`** on that regime's trade subset + the equity-curve days tagged with that regime. Trade-derived fields are exact; equity-derived fields (`max_drawdown_pct`, `exposure`) are over that regime's (possibly non-contiguous) days — approximate but honest; noted in §7. |
| E6 | **`breadth` stays `None`** in M3 (needs universe-wide advance/decline data); deferred. `index_trend` **is** populated (relative distance of the index from its SMA). |

## 4. Components

```
src/btf/
  regime/__init__.py
  regime/classifier.py     # RegimeClassifier (Protocol) + SmaRegimeClassifier
  metrics/compute.py       # + compute_regime_breakdown(trades, equity_curve, day_regimes)
  portfolio/portfolio.py   # apply_entry gains `regime`; lot stores entry_regime; Trade tagged
  engine/basic_engine.py   # loads benchmark, classifies per day, feeds MarketContext, builds
                           #   benchmark_curve + regime_breakdown
```

### 4.1 `RegimeClassifier` / `SmaRegimeClassifier`
- `RegimeClassifier` Protocol: `warmup_bars: int`; `classify(index_history: pd.Series) ->
  tuple[Regime, float | None]` where `index_history` is ascending benchmark closes with ts ≤ as_of and
  the return is `(regime, index_trend)`.
- `SmaRegimeClassifier(window=200, slope_lookback=20, band=0.0)`:
  - `warmup_bars = window`.
  - `len(history) < window` → `(UNKNOWN, None)`.
  - `sma = mean(last window closes)`; `close = last`; `index_trend = (close - sma) / sma`.
  - `slope`: compare `sma` to the SMA `slope_lookback` bars earlier (if enough history), giving
    `rising` / `falling` (both `False` when the slope isn't yet computable).
  - **BULL** if `close > sma·(1+band)` and not `falling`; **BEAR** if `close < sma·(1−band)` and not
    `rising`; else **RANGE**. (Deterministic; with `band=0` and no slope it is pure close-vs-SMA.)

### 4.2 `compute_regime_breakdown(trades, equity_curve, day_regimes) -> dict[Regime, Metrics]`
For each regime present among the trades: `metrics_r = compute_metrics([t for t in trades if
t.regime == r], equity_curve[days whose regime == r])`. Keyed by `Regime`. `day_regimes` is a
`Mapping[date, Regime]` the engine accumulates during the loop.

### 4.3 Engine changes (loop order)
Per day *t*, **before** executing fills:

0. **Classify** `regime_t, index_trend_t` from `benchmark[:t]` (or `UNKNOWN, None` if no benchmark).
   Record `day_regimes[t] = regime_t`.

Then the M1 steps 2–8, with two edits: entry fills call `portfolio.apply_entry(fill, order,
regime_t)`; the `MarketContext` is built with `regime=regime_t, index_trend=index_trend_t`.

**After the loop:** build `benchmark_curve` (E4) if a benchmark was configured; build
`regime_breakdown` via §4.2 if a benchmark was configured, else `{}`.

## 5. Configuration

`config` gains an optional `"benchmark": str`. Absent ⇒ no classification, `benchmark_curve=None`,
`regime_breakdown={}` (identical to M1). Classifier params live on the `SmaRegimeClassifier` instance
passed to `BasicEngine(classifier=...)` (default `SmaRegimeClassifier()`).

## 6. Tests (TDD)

1. **Classifier units** (`tests/test_regime.py`): rising series → BULL; falling → BEAR; flat/oscillating
   → RANGE; `< window` bars → UNKNOWN; `index_trend` sign matches.
2. **No-look-ahead for regime:** the day-*t* regime uses only benchmark bars ≤ *t* (spy asserts the
   sliced history's max ts == as_of).
3. **Engine feeds real regime:** with a rising benchmark, `ctx.market.regime` is BULL after warmup and
   trades are tagged BULL at entry.
4. **`benchmark_curve`:** populated, indexed like `equity_curve`, first value == `starting_cash`.
5. **`regime_breakdown`:** partitions trades — `Σ regime_breakdown[r].num_trades == len(trades)` (over
   tagged regimes); each bucket's `Metrics` matches `compute_metrics` on that subset.
6. **Backward-compat:** no `"benchmark"` ⇒ `benchmark_curve is None`, `regime_breakdown == {}`, and all
   45 M0+M1 tests remain green.

## 7. Non-goals / deferred

Not in M3: breadth (advance/decline) — `MarketContext.breadth` stays `None`; multi-factor / ML regime
models; regime-gated strategies (a strategy *may* read the regime, but none ships here); per-regime
equity curves as first-class objects (breakdown reuses the single equity curve — E5 caveat); trailing
stops (M4); non-zero costs by default; real network data adapters.

## 8. Brain traceability

`situation-awareness` (RegimeClassifier, MarketContext.regime/index_trend), `expectancy-and-position-
sizing` (per-regime expectancy in regime_breakdown), `initial-stop-and-r-multiple` (Trade.regime tags
each R outcome with the regime it was taken in).
