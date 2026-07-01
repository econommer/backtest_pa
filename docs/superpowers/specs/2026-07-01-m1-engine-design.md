# M1 — Skeleton + Fake Data (Design Spec)

- **Date:** 2026-07-01
- **Milestone:** M1 (see `BACKTESTING_PLAN.md` §9)
- **Scope:** Make the frozen M0 contract actually run end-to-end — the smallest thing that executes one backtest with the books reconciling.
- **Status:** Approved for implementation.
- **Depends on:** M0 (interfaces frozen, merged).

> Domain reminder: for **studying and backtesting** only. Document and measure — never place live
> trades, move money, or give buy/sell recommendations.

---

## 1. Goal

Turn the frozen M0 interfaces into a working, verifiable event-driven backtest:

- a concrete `Engine.run()` loop (bar-by-bar; builds `Context` with no look-ahead; `Strategy` →
  `PositionSizer` → `Broker` → portfolio bookkeeping → `BacktestResult`),
- an in-memory fake `DataProvider` (hand-made symbols, no network),
- a trivial `Broker` (next-open MARKET fills + gap-through stop sweep),
- a trivial R-based `PositionSizer`,
- a dummy buy-and-hold `Strategy`,
- internal `Portfolio` bookkeeping that assembles closed `Trade`s in R units.

**Acceptance:** one buy-and-hold backtest runs to completion; books reconcile; the no-look-ahead
invariant and the stop-out path are proven by tests; all 25 M0 contract tests stay green.

## 2. Non-negotiables (from `code/CLAUDE.md`)

- **Strategy ⟂ Engine.** The engine must not know what "buy-and-hold" or "VCP" is. It only feeds
  `Context`, collects `Signal`s, sizes, simulates fills, bookkeeps, and computes metrics.
- **No look-ahead.** `Context` exposes only data with timestamp ≤ `as_of`; signals computed on the
  close of bar *t* fill no earlier than bar *t+1*'s open.
- **No M0 contract change.** Every new class implements a frozen Protocol or uses a frozen value
  object. Confirmed feasible against `src/btf/` — no re-freeze required.

## 3. Locked decisions (this spec)

| # | Decision |
|---|----------|
| D1 | **Force-liquidate** open positions at the final bar's close → every position becomes a closed `Trade`; books fully reconcile. (M1 convention.) |
| D2 | **Compute core `Metrics` honestly** in M1 from trades + equity curve. `regime_breakdown={}`, `benchmark_curve=None` deferred to M3. |
| D3 | **Costs plumbed but zero by default.** `SimpleBroker` takes commission/slippage params; M1 runs default them to 0. |
| D4 | **Include a stop-out test.** Dummy strategy stays pure buy-and-hold; a targeted test feeds gap-through data to exercise `sweep_stops` → `STOP_OUT` → `Trade`. |
| D5 | **Trailing stops stay on approach (a)** for M1 (strategy would emit next-bar EXIT signals); nothing is implemented since buy-and-hold never trails. See §9 for the M4 recommendation. |

## 4. Architecture — the daily loop

`BasicEngine.run(strategy, data, broker, sizer, config)` loads all history once into an internal
per-symbol store (`dict[str, pandas.DataFrame]` indexed by date), then iterates
`data.trading_calendar(start, end)`. It carries one piece of cross-day state: `pending_orders`
(orders decided on day *t−1*, to execute at *t*'s open).

**Per trading day _t_:**

1. Resolve bar *t* for each active symbol (`{symbol: Bar}`).
2. **Execute `pending_orders` at _t_'s open** → `broker.execute(pending_orders, bars_t)` → Fills
   (entries + exits, at open + costs). `Portfolio` applies them: entry Fills open lots and debit
   cash; exit Fills (from EXIT orders) close lots → `Trade`s.
3. **Sweep resting stops against bar _t_** → `broker.sweep_stops(open_positions, bars_t)` →
   `STOP_OUT` Fills (gap-through: if the bar gapped past the stop, fill at the open; else at the
   stop price). `Portfolio` closes those lots → `Trade`s. Runs *after* step 2, so a lot already
   closed by an exit this bar is not double-closed.
4. **Mark-to-market at _t_'s close**; `Portfolio.record_equity(t)` (`equity = cash + Σ qty·close`).
5. **Build `BacktestContext` as-of _t_**: price store sliced ≤ *t*; current cash/equity/position
   snapshots; `MarketContext(as_of=t, regime=Regime.UNKNOWN)`; `universe = data.universe(t)`.
6. If bar-index ≥ `strategy.warmup_bars`: `signals = strategy.on_bar(ctx)`; else `signals = []`.
7. `orders = sizer.size(signals, ctx)`.
8. `pending_orders = orders` (carried to day *t+1*).

**After the loop:** force-liquidate any still-open lots at the final bar's close → exit Fills →
`Trade`s. Any orders decided on the final bar are dropped (no *t+1*) and logged.

**Look-ahead safety (why this is correct):** the strategy at step 6 sees *t*'s close (a legal
close-of-bar decision); its orders fill at step 2 of the *next* iteration = *t+1*'s open, strictly
after the signal bar. `BacktestContext` slices the store to ≤ `as_of` on every call and exposes no
future-reaching accessor. Both properties are asserted by tests (§8).

**Ordering rationale:** execute-before-sweep prevents double-closing; mark-at-close before building
`Context` means `ctx.equity` reflects *t*'s close for sizing; sizing on close + fill next open is the
canonical event-driven anti-look-ahead pattern.

## 5. Components (new files — all implement frozen M0 Protocols)

```
src/btf/
  engine/basic_engine.py       # BasicEngine(Engine): the loop; owns Portfolio; builds BacktestResult
  context/backtest_context.py  # BacktestContext(Context): slices price store <= as_of (the firewall)
  portfolio/portfolio.py       # Portfolio: cash, open lots, equity curve, closed Trades
  data/memory_provider.py      # InMemoryDataProvider(DataProvider): hand-made dict[str, DataFrame]
  broker/simple_broker.py      # SimpleBroker(Broker): MARKET fill @ open + cost hooks; gap-through sweep
  risk/fixed_risk_sizer.py     # FixedRiskSizer(PositionSizer): size = risk_pct*equity / stop_distance
  strategies/buy_and_hold.py   # BuyAndHold(Strategy): buy each symbol once (MARKET + nominal stop), hold
  metrics/compute.py           # compute_metrics(trades, equity_curve) -> Metrics
tests/                         # see §8
```

Each unit is small, single-purpose, and independently testable. `BacktestContext` takes plain data
(store reference, `as_of`, position snapshots, cash, equity, market, universe) — it does **not**
import `Portfolio`, so the firewall is testable in isolation.

### 5.1 `InMemoryDataProvider`
Constructed from `dict[str, pandas.DataFrame]` (one frame per symbol, DatetimeIndex, columns
open/high/low/close/volume) and an optional static universe + optional benchmark `Series`.
- `trading_calendar(start, end)` = sorted union of all frames' dates within `[start, end]`.
- `universe(on)` = the static symbol list (point-in-time membership is trivial in M1).
- `history(symbols, start, end, fields)` = concatenated slice.
- `industry` → `None`; `earnings_dates` → `[]`; `index(name, start, end)` → the stored benchmark
  series (or a `KeyError` if none was provided — M1 doesn't use it).

### 5.2 `SimpleBroker`
Params: `commission_per_share=0.0`, `slippage_pct=0.0`.
- `execute(orders, bars)`: for each `Order` with `order_type == MARKET`, fill at
  `bars[symbol].open` adjusted by slippage (buy: `·(1+slippage_pct)`, sell: `·(1−slippage_pct)`),
  commission = `commission_per_share · quantity`. Emit `Fill(kind=ENTRY)` for ENTRY/ADD orders and
  `Fill(kind=EXIT)` for EXIT/REDUCE orders. Non-MARKET order types are out of scope for M1 (the
  dummy uses MARKET only); raise `NotImplementedError` so a future strategy can't silently no-op.
- `sweep_stops(positions, bars)`: for each long `Position` with a `stop_price`, if
  `bar.low <= stop_price` the stop triggers: fill price = `bar.open` if `bar.open < stop_price`
  (gapped through → worse) else `stop_price`. Emit `Fill(kind=STOP_OUT)`. (Short side deferred; VCP
  is long-only.)

### 5.3 `FixedRiskSizer`
Params: `risk_pct` (fraction of equity risked per trade), sizing basis = signal bar close.
- For each ENTRY signal with a `stop_price`: `ref = ctx.bar(sym).close`;
  `risk_per_share = ref − stop_price` (assert > 0, else drop);
  `qty = floor(risk_pct · ctx.equity / risk_per_share)`; cap so `qty · ref` fits a running cash
  budget for the bar; drop if `qty < 1`. Emit `Order(kind=ENTRY, order_type=MARKET, quantity=qty,
  trigger_price=None, stop_price=stop_price, risk_per_share=risk_per_share)`.
- For each EXIT signal: `qty = ctx.positions[sym].quantity`; emit `Order(kind=EXIT,
  order_type=MARKET, quantity=qty, stop_price=None, risk_per_share=0.0)`.
- Portfolio heat / max-position limits are deferred (noted in §9).

### 5.4 `BuyAndHold`
`name="buy-and-hold"`, `warmup_bars=0`, param `nominal_stop_pct` (default e.g. 0.5, i.e. a stop far
enough below entry that it never triggers on the fake up-trending data — a plumbing device so
R-based sizing is well-defined). `on_bar(ctx)`: for each symbol in `ctx.universe` with no open
position and not already entered, emit `Signal(kind=ENTRY, order_type=MARKET,
stop_price=close·(1−nominal_stop_pct), reason="buy-and-hold entry")`. Never emits EXIT (held to
liquidation).

### 5.5 `Portfolio`
Internal mutable state: `cash`, `_lots: dict[str, _OpenLot]` (one lot per symbol in M1), `equity_curve:
list[(date, equity)]`, `trades: list[Trade]`. `_OpenLot` records symbol, quantity, entry_price,
stop_price, entry_ts, risk_per_share, cost paid.
- `apply_entry(fill, order)`: open a lot, `cash -= fill.price·qty + fill.commission`, set
  `stop_price = order.stop_price` and `risk_per_share = fill.price − order.stop_price` (R denominated
  by the actual fill). Takes the `order` explicitly because the frozen `Fill` carries no stop field —
  the engine, which owns the order↔fill correlation, threads the originating entry order in.
- `apply_exit(fill)`: close the lot (no order needed — the lot already stores `stop_price` and
  `risk_per_share`): `cash += fill.price·qty − fill.commission`; build `Trade`
  (`r_multiple = (exit − entry)/risk_per_share`, `pnl = (exit − entry)·qty − total_costs`,
  `regime = Regime.UNKNOWN`, `reason_entry`/`reason_exit` from the lot / fill). Used for EXIT-order
  fills, `STOP_OUT` sweeps, and final liquidation alike. Guard: closing a non-existent lot is a
  no-op (handles the exit-then-sweep-same-bar case).
- `snapshot_positions() -> dict[str, Position]`; `mark(bars_close) -> equity`;
  `record_equity(date)`.
- No contract change: `Fill` is unchanged; the stop is recovered from the entry `Order` at
  `apply_entry`, and thereafter lives on the internal lot.

### 5.6 `compute_metrics(trades, equity_curve) -> Metrics`
- From trades: `num_trades`, `win_rate`, `avg_win_r`, `avg_loss_r`,
  `expectancy = win_rate·avg_win_r − loss_rate·avg_loss_r`,
  `profit_factor = gross_profit$ / gross_loss$` (→ `float('inf')` when there are no losers and
  wins > 0; `0.0` when there are no trades), `max_losing_streak`,
  `max_drawdown_r` = deepest peak-to-trough drop of the cumulative closed-trade-R curve.
- From equity curve: `max_drawdown_pct` = deepest peak-to-trough % decline.
- `exposure` = fraction of recorded days with ≥ 1 open position.

## 6. Configuration

`config: Mapping[str, object]` for M1 carries **run-level** params only:
`{"start": date, "end": date, "starting_cash": float}` (and optionally `"symbols": list[str]`;
if absent, the engine takes the universe from `data.universe(as_of)`). Cost params live on the
`SimpleBroker` instance; `risk_pct` on the `FixedRiskSizer`; `nominal_stop_pct` on the `BuyAndHold`
instance. Same config + same components ⇒ same result (reproducibility).

## 7. Data flow (one entry's lifecycle)

```
day t   BuyAndHold.on_bar -> Signal(ENTRY, MARKET, stop=close*0.5)
        FixedRiskSizer.size -> Order(qty, stop, risk_per_share)     [queued]
day t+1 SimpleBroker.execute @ open -> Fill(ENTRY)
        Portfolio.apply_fill -> open lot, risk_per_share = open - stop
        ... held; sweep_stops each bar (never triggers on up-trend) ...
day T   force-liquidate @ close -> Fill(EXIT)
        Portfolio.apply_fill -> Trade(r_multiple, pnl, regime=UNKNOWN)
```

## 8. Tests (TDD, red→green→refactor)

1. **No-look-ahead invariant** (`tests/test_no_lookahead.py`): a spy strategy asserts, on every
   `on_bar`, `max(ctx.history(sym).index).date() == ctx.as_of` and `ctx.bar(sym).ts == ctx.as_of`;
   and after the run, every `Trade.entry_ts` is strictly greater than the `as_of` of the bar its
   entry signal fired on. **This is the milestone's defining invariant.**
2. **Books reconcile** (`tests/test_reconcile.py`): after a buy-and-hold run,
   `starting_cash + Σ trade.pnl == final_cash` (within float tolerance) and end `equity == cash`
   (flat after liquidation); exactly one `Trade` per symbol.
3. **Stop-out path** (`tests/test_stopout.py`): hand-made gap-through data fires a resting stop —
   asserts a `STOP_OUT` Fill priced at the gapped open (< stop), a `Trade` with negative
   `r_multiple`, and correct `initial_stop`.
4. **Component units** (`tests/test_units_m1.py`): `InMemoryDataProvider` slicing respects bounds;
   `FixedRiskSizer` quantity math (`floor(risk_pct·equity / stop_distance)`, cash cap, drops);
   `SimpleBroker` fill prices (open, slippage sign, gap-through); `Portfolio` fill→Trade R and cash
   conservation; `compute_metrics` expectancy and drawdown on a known series.
5. **Protocol conformance** (`tests/test_m1_conformance.py`): each new class `isinstance`-satisfies
   its Protocol (`BasicEngine`→`Engine`, `InMemoryDataProvider`→`DataProvider`, etc.).
6. **M0 contract green:** the existing 25 contract tests remain unchanged and passing.

Run all tests with `.venv/Scripts/python.exe -m pytest`.

## 9. Non-goals / deferred

Not in M1: trailing (moving) stops, regime/breadth engine, benchmark comparison, non-zero costs by
default, pyramiding / multi-lot / ADD / REDUCE, short selling, portfolio heat / max-position caps,
walk-forward / out-of-sample, real (network) data, YAML config loading, reporting/plots.

**M4 trailing-stops recommendation — adopt (b):** model trailing stops as **resting broker-swept
stops** that can trigger intrabar, updated via a small additive `SignalKind.UPDATE_STOP` member plus
an engine step that applies UPDATE_STOP signals to the live `Position.stop_price` *before*
`sweep_stops`. Rationale: `Broker.sweep_stops` + `Position.stop_price` + gap-through are already
frozen and already used by M1's static stops; approach (a) (strategy emits next-bar EXIT) would
delay every trailed exit to the next open, never fill intrabar, and systematically mis-model the
gap-through-stop risk the brain emphasises (`gap-risk`, `trailing-stops`). `UPDATE_STOP` is an
*additive* enum change (non-breaking for existing implementers), but it **is** a contract change, so
it must be a conscious M4 decision — flagged here, not implemented now.

## 10. Brain traceability

`initial-stop-and-r-multiple` (risk_per_share, R), `expectancy-and-position-sizing` (FixedRiskSizer,
Metrics.expectancy), `gap-risk` (SimpleBroker.sweep_stops gap-through), `situation-awareness`
(MarketContext placeholder), setup `vcp-breakout` (Trade fields feed its backtest template).
