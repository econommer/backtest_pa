# M0 — Freeze Interfaces (Design Spec)

- **Date:** 2026-07-01
- **Milestone:** M0 (see `BACKTESTING_PLAN.md` §9)
- **Scope:** Interfaces + concrete value objects + docstrings + contract tests. **No behavior.**
- **Status:** Approved for implementation.

> Domain reminder: this framework is for **studying and backtesting** price-action strategies.
> Document and measure — never place live trades, move money, or give buy/sell recommendations.

---

## 1. Goal

Freeze the contract that every later milestone builds against: `DataProvider`, `Strategy`,
`Engine`, `Broker`, `PositionSizer`, `Context`, and `BacktestResult` (including the `Signal`,
`Order`, `Fill`, `Position`, `Trade`, and `Metrics` value objects). Getting these boundaries right
now is what lets VCP / Pocket Pivot / Buyable Gap Up later run on the same engine and be compared
with the same metrics (plan §1).

The non-negotiable principle (`code/CLAUDE.md`): **Strategy ⟂ Engine.** The engine knows nothing
about "VCP." Interfaces enforce that separation structurally.

## 2. Locked decisions (this spec)

| # | Decision |
|---|----------|
| D1 | **Data representation = pandas.** OHLCV history as `DataFrame`, index/benchmark as `Series`. |
| D2 | **M0 = Protocols + concrete data models.** Value objects are fully-defined frozen dataclasses; interfaces are `@runtime_checkable Protocol` with `...` bodies. |
| D3 | **Contract/structural tests** guard the frozen contract (no behavior to test yet). |
| D4 | **`code/` is its own git repo.** |
| D5 | Shared value objects live in a single `btf/core.py` to prevent import cycles (deviation from plan §8, which scattered them). Protocols stay in their plan-designated directories. |
| D6 | `PositionSizer` (Risk) is part of the frozen M0 contract, not deferred. |

## 3. Module layout

```
src/btf/
  __init__.py
  core.py                # value objects + enums (shared, import-cycle-free)
  data/
    __init__.py
    provider.py          # DataProvider Protocol
  strategies/
    __init__.py
    base.py              # Strategy Protocol
  risk/
    __init__.py
    sizer.py             # PositionSizer Protocol
  broker/
    __init__.py
    broker.py            # Broker Protocol
  context/
    __init__.py
    market.py            # MarketContext dataclass, Regime enum
    context.py           # Context Protocol (per-bar look-ahead firewall)
  engine/
    __init__.py
    engine.py            # Engine Protocol
  metrics/
    __init__.py
    result.py            # BacktestResult, Metrics dataclasses
tests/
  test_contract.py       # structural/contract tests
pyproject.toml
.gitignore
```

## 4. Data flow (intention → order → fill → trade)

The strategy emits *intentions* only; the firewall between "what to do" and "how many shares / what
price" is structural, not a convention:

```
Strategy.on_bar(ctx)        -> list[Signal]   # what & why, NO quantity, NO cash
PositionSizer.size(sigs,ctx)-> list[Order]    # applies size = R$ / stop_distance, heat/max-pos caps
Broker.execute(orders, ...) -> list[Fill]     # fill price, slippage, commission
Broker.sweep_stops(pos, ...)-> list[Fill]     # gap-through stops: gap jumps stop -> fill at open
(Portfolio bookkeeping)     -> Trade          # closed round-trip, in R units
```

- **Look-ahead firewall:** `Context` exposes only data with timestamp ≤ `as_of`. Signals compute on
  the close of the current bar; fills happen on a later bar. (plan §6)
- **Sizing firewall:** `Signal` has no `quantity`; only `PositionSizer` produces `quantity`. A
  strategy therefore *cannot* touch cash or position size.

## 5. Value objects (`btf/core.py`) — all `@dataclass(frozen=True)`

### Enums
- `SignalKind` = `ENTRY | ADD | EXIT | REDUCE`
- `Direction` = `LONG | SHORT`  (VCP is long-only; kept generic)
- `OrderType` = `MARKET | STOP | LIMIT`
- `FillKind` = `ENTRY | ADD | EXIT | STOP_OUT`
- `Regime` = `BULL | BEAR | RANGE | UNKNOWN`

### `Bar`
Single OHLCV bar. Fields: `symbol: str`, `ts: date`, `open: float`, `high: float`, `low: float`,
`close: float`, `volume: float`.

### `Signal` — strategy output
| field | type | notes |
|---|---|---|
| `symbol` | `str` | |
| `kind` | `SignalKind` | |
| `direction` | `Direction = LONG` | |
| `order_type` | `OrderType = STOP` | STOP = breakout of `trigger_price` |
| `trigger_price` | `float \| None` | pivot for STOP/LIMIT; `None` for MARKET |
| `stop_price` | `float \| None` | strategy-computed initial stop (pivot − k·ATR). Required for ENTRY. |
| `sizing_hint` | `float \| None` | optional risk fraction; Risk module may honor or ignore |
| `reason` | `str = ""` | provenance for brain audit (which rule fired) |
| `meta` | `dict = {}` | extensibility |

### `Order` — post-sizing (adds quantity, drops `sizing_hint`)
`symbol`, `direction`, `kind: SignalKind`, `order_type`, `quantity: int`, `trigger_price: float | None`,
`stop_price: float | None`, `risk_per_share: float`, `reason: str = ""`, `meta: dict = {}`.

### `Fill` — broker output
`symbol`, `ts: date`, `price: float`, `quantity: int`, `direction`, `kind: FillKind`,
`commission: float = 0.0`, `slippage: float = 0.0`, `reason: str = ""`.

### `Position` — read-only snapshot handed to strategy
`symbol`, `direction`, `quantity: int`, `avg_price: float`, `stop_price: float | None`,
`entry_ts: date`, `risk_per_share: float`.

### `Trade` — closed round-trip (pastes into `vcp-breakout` backtest template)
`symbol`, `direction`, `entry_ts: date`, `entry_price: float`, `exit_ts: date`, `exit_price: float`,
`quantity: int`, `initial_stop: float`, `r_multiple: float`, `pnl: float`, `regime: Regime`,
`reason_entry: str = ""`, `reason_exit: str = ""`.

## 6. Interfaces

All are `@runtime_checkable Protocol`, bodies are `...`, every method carries a docstring that cites
its brain page where one exists.

### `DataProvider` (`data/provider.py`) — vendor-agnostic
- `trading_calendar(start: date, end: date) -> list[date]`
- `universe(on: date) -> list[str]`  — point-in-time members (incl. delisted in Phase 2)
- `history(symbols, start, end, fields=("open","high","low","close","volume")) -> pd.DataFrame`
- `industry(symbol, on: date) -> str | None`  — optional
- `earnings_dates(symbol) -> list[date]`  — optional (`gap-risk`: avoid pre-earnings)
- `index(name, start, end) -> pd.Series`  — benchmark

### `Strategy` (`strategies/base.py`) — emits intentions only
- attr `name: str`
- attr `warmup_bars: int`  — history needed before it can compute (MA200, ATR…)
- `on_bar(ctx: Context) -> list[Signal]`

### `PositionSizer` (`risk/sizer.py`)
- `size(signals: list[Signal], ctx: Context) -> list[Order]`
  — applies `size = R$ / stop_distance` (`expectancy-and-position-sizing`), per-trade risk %,
  portfolio heat, max positions.

### `Broker` (`broker/broker.py`) — execution model
- `execute(orders: list[Order], bars: Mapping[str, Bar]) -> list[Fill]`
  — fill model (next open / limit), slippage, commission.
- `sweep_stops(positions: Mapping[str, Position], bars: Mapping[str, Bar]) -> list[Fill]`
  — gap-through stops: a gap that jumps the stop fills at the open (`gap-risk`).

### `Context` (`context/context.py`) — per-bar look-ahead firewall
Read-only accessor handed to the strategy each bar. Exposes **only** data with ts ≤ `as_of`.
- prop `as_of: date`
- prop `cash: float`
- prop `equity: float`
- prop `positions: Mapping[str, Position]`
- prop `market: MarketContext`
- prop `universe: Sequence[str]`
- `history(symbol: str, lookback: int | None = None) -> pd.DataFrame`  — OHLCV ≤ `as_of`
- `bar(symbol: str) -> Bar | None`  — the current (`as_of`) bar

### `MarketContext` (`context/market.py`) — `@dataclass(frozen=True)`
`as_of: date`, `regime: Regime`, `index_trend: float | None = None`, `breadth: float | None = None`,
`meta: dict = {}`. Reusable regime/breadth gate (`situation-awareness`); belongs to no single strategy.

### `Engine` (`engine/engine.py`) — generic loop, knows nothing about VCP
- `run(strategy: Strategy, data: DataProvider, broker: Broker, sizer: PositionSizer,
   config: Mapping) -> BacktestResult`

## 7. Result objects (`metrics/result.py`) — `@dataclass(frozen=True)`

### `Metrics`
`num_trades: int`, `win_rate: float`, `avg_win_r: float`, `avg_loss_r: float`, `expectancy: float`,
`profit_factor: float`, `max_losing_streak: int`, `max_drawdown_r: float`, `max_drawdown_pct: float`,
`exposure: float`. (All in R units per plan §4; `expectancy = win_rate·avg_win_R − loss_rate·avg_loss_R`.)

### `BacktestResult`
`config: Mapping`, `equity_curve: pd.Series`, `benchmark_curve: pd.Series | None`,
`trades: list[Trade]`, `metrics: Metrics`, `regime_breakdown: dict[Regime, Metrics]`.

## 8. Contract tests (`tests/test_contract.py`)

No behavior exists, so tests guard the *shape* of the contract:
1. Every `btf.*` module imports cleanly.
2. Each frozen dataclass has exactly its specified fields and raises on mutation
   (`FrozenInstanceError`).
3. Each enum has exactly its specified members.
4. Each Protocol is `runtime_checkable`, and a minimal in-test stub satisfies `isinstance(stub, P)`.
5. Default-carrying fields (`direction=LONG`, `order_type=STOP`, `meta={}`) construct without those args.

These give M1 a red/green harness to implement against.

## 9. Tooling / deps

- `pyproject.toml`: runtime `pandas`, `numpy`; dev `pytest`, `mypy`, `ruff`. Python ≥ 3.11
  (for `X | None` in annotations at runtime and modern typing).
- `.gitignore`: Python standard (`__pycache__/`, `*.pyc`, `.venv/`, `.pytest_cache/`, `.mypy_cache/`,
  `.ruff_cache/`, build artifacts).

## 10. Explicitly out of scope for M0

No engine loop, no data adapters, no sizing math, no fill simulation, no metric computation, no VCP.
Those are M1+ per plan §9. M0 ends when the contract tests pass green against interface stubs.

## 11. Brain traceability

Docstrings at M0 cite the pages that map to a frozen interface: `initial-stop-and-r-multiple`
(Signal.stop_price), `expectancy-and-position-sizing` (Order.risk_per_share / PositionSizer / Metrics),
`gap-risk` (Broker.sweep_stops, DataProvider.earnings_dates), `situation-awareness` (MarketContext),
setup `vcp-breakout` (Trade template). Deferred to the strategy/behavior milestones (M4+), so not yet
cited in code: `relative-strength` (RS ranking) and `trailing-stops` (trail exits).
