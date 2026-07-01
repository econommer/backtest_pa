# M0 Interface Freeze — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze the backtesting framework's contract — Protocol interfaces plus concrete frozen value objects — with structural contract tests, no behavior.

**Architecture:** A shared `btf/core.py` holds all enums and frozen dataclasses (value objects). Each Protocol interface lives in its plan-designated package (`data/`, `strategies/`, `risk/`, `broker/`, `context/`, `engine/`, `metrics/`) and imports value objects from `core`. Dependency graph is a DAG rooted at `core`; no cycles. Interfaces have `...` bodies with docstrings only. Contract tests assert field lists, frozenness, enum members, and Protocol satisfiability.

**Tech Stack:** Python ≥ 3.11, `dataclasses`, `typing.Protocol` / `runtime_checkable`, `pandas`, `numpy`; `pytest` for tests.

## Global Constraints

- Python ≥ 3.11 (runtime `X | None` unions, modern typing).
- Every module begins with `from __future__ import annotations`.
- All value objects are `@dataclass(frozen=True, slots=True)`; mutable defaults use `field(default_factory=...)`.
- All interfaces are `@runtime_checkable` `Protocol` with `...` method bodies and a docstring per method; **no behavior**.
- Type hints everywhere (project convention, `code/CLAUDE.md`).
- Strategy ⟂ Engine: nothing in `engine/` or `core/` may reference a concrete strategy.
- Docstrings cite the relevant brain page by name where one exists (e.g. `expectancy-and-position-sizing`).
- Commit after each task. Commit message trailer: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.
- Run tests with `python -m pytest`.

---

### Task 1: Project scaffolding & tooling

**Files:**
- Create: `pyproject.toml`
- Create: `src/btf/__init__.py`
- Create: `src/btf/data/__init__.py`, `src/btf/strategies/__init__.py`, `src/btf/risk/__init__.py`, `src/btf/broker/__init__.py`, `src/btf/context/__init__.py`, `src/btf/engine/__init__.py`, `src/btf/metrics/__init__.py`
- Create: `tests/__init__.py`, `tests/test_scaffolding.py`

**Interfaces:**
- Consumes: nothing.
- Produces: an importable `btf` package installed in editable mode; `btf.__version__` string.

- [ ] **Step 1: Write the failing test**

`tests/test_scaffolding.py`:
```python
import importlib


def test_btf_imports():
    mod = importlib.import_module("btf")
    assert isinstance(mod.__version__, str)


def test_subpackages_import():
    for pkg in ("data", "strategies", "risk", "broker", "context", "engine", "metrics"):
        importlib.import_module(f"btf.{pkg}")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scaffolding.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'btf'`.

- [ ] **Step 3: Create `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "btf"
version = "0.0.0"
description = "PA Strategy Backtesting Framework"
requires-python = ">=3.11"
dependencies = ["pandas>=2.0", "numpy>=1.24"]

[project.optional-dependencies]
dev = ["pytest>=8.0", "mypy>=1.8", "ruff>=0.4"]

[tool.hatch.build.targets.wheel]
packages = ["src/btf"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

Note: `pythonpath = ["src"]` lets pytest import `btf` without an install step.

- [ ] **Step 4: Create package files**

`src/btf/__init__.py`:
```python
"""PA Strategy Backtesting Framework (btf).

Strategy-agnostic, event-driven backtester. See BACKTESTING_PLAN.md.
"""
from __future__ import annotations

__version__ = "0.0.0"
```

Each of the seven subpackage `__init__.py` files (`data`, `strategies`, `risk`, `broker`, `context`, `engine`, `metrics`) and `tests/__init__.py`: create empty (zero bytes).

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_scaffolding.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/btf tests
git commit -m "chore: scaffold btf package and tooling"
```

---

### Task 2: Core value objects & enums (`btf/core.py`)

**Files:**
- Create: `src/btf/core.py`
- Test: `tests/test_core.py`

**Interfaces:**
- Consumes: nothing (pure module, stdlib only).
- Produces:
  - Enums `SignalKind`, `Direction`, `OrderType`, `FillKind`, `Regime`.
  - Frozen dataclasses `Bar`, `Signal`, `Order`, `Fill`, `Position`, `Trade` with fields exactly as below.
  - `Signal(symbol, kind, direction=LONG, order_type=STOP, trigger_price=None, stop_price=None, sizing_hint=None, reason="", meta={})`.
  - `Order(symbol, direction, kind, order_type, quantity, trigger_price, stop_price, risk_per_share, reason="", meta={})`.
  - `Fill(symbol, ts, price, quantity, direction, kind, commission=0.0, slippage=0.0, reason="")`.
  - `Position(symbol, direction, quantity, avg_price, stop_price, entry_ts, risk_per_share)`.
  - `Trade(symbol, direction, entry_ts, entry_price, exit_ts, exit_price, quantity, initial_stop, r_multiple, pnl, regime, reason_entry="", reason_exit="")`.
  - `Bar(symbol, ts, open, high, low, close, volume)`.

- [ ] **Step 1: Write the failing test**

`tests/test_core.py`:
```python
from dataclasses import FrozenInstanceError, fields
from datetime import date

import pytest

from btf.core import (
    Bar,
    Direction,
    Fill,
    FillKind,
    Order,
    OrderType,
    Position,
    Regime,
    Signal,
    SignalKind,
    Trade,
)


def _names(cls):
    return {f.name for f in fields(cls)}


def test_enum_members():
    assert {m.name for m in SignalKind} == {"ENTRY", "ADD", "EXIT", "REDUCE"}
    assert {m.name for m in Direction} == {"LONG", "SHORT"}
    assert {m.name for m in OrderType} == {"MARKET", "STOP", "LIMIT"}
    assert {m.name for m in FillKind} == {"ENTRY", "ADD", "EXIT", "STOP_OUT"}
    assert {m.name for m in Regime} == {"BULL", "BEAR", "RANGE", "UNKNOWN"}


def test_bar_fields():
    assert _names(Bar) == {"symbol", "ts", "open", "high", "low", "close", "volume"}


def test_signal_fields_and_defaults():
    assert _names(Signal) == {
        "symbol", "kind", "direction", "order_type", "trigger_price",
        "stop_price", "sizing_hint", "reason", "meta",
    }
    s = Signal(symbol="AAPL", kind=SignalKind.ENTRY)
    assert s.direction is Direction.LONG
    assert s.order_type is OrderType.STOP
    assert s.trigger_price is None and s.stop_price is None and s.sizing_hint is None
    assert s.reason == "" and s.meta == {}


def test_order_fields():
    assert _names(Order) == {
        "symbol", "direction", "kind", "order_type", "quantity",
        "trigger_price", "stop_price", "risk_per_share", "reason", "meta",
    }


def test_fill_fields_and_defaults():
    assert _names(Fill) == {
        "symbol", "ts", "price", "quantity", "direction", "kind",
        "commission", "slippage", "reason",
    }
    f = Fill(symbol="AAPL", ts=date(2026, 1, 2), price=10.0, quantity=1,
             direction=Direction.LONG, kind=FillKind.ENTRY)
    assert f.commission == 0.0 and f.slippage == 0.0 and f.reason == ""


def test_position_fields():
    assert _names(Position) == {
        "symbol", "direction", "quantity", "avg_price",
        "stop_price", "entry_ts", "risk_per_share",
    }


def test_trade_fields():
    assert _names(Trade) == {
        "symbol", "direction", "entry_ts", "entry_price", "exit_ts",
        "exit_price", "quantity", "initial_stop", "r_multiple", "pnl",
        "regime", "reason_entry", "reason_exit",
    }


def test_meta_defaults_are_independent():
    a, b = Signal(symbol="A", kind=SignalKind.ENTRY), Signal(symbol="B", kind=SignalKind.ENTRY)
    assert a.meta is not b.meta  # default_factory, not shared mutable


def test_frozen():
    s = Signal(symbol="AAPL", kind=SignalKind.ENTRY)
    with pytest.raises(FrozenInstanceError):
        s.symbol = "MSFT"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_core.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'btf.core'`.

- [ ] **Step 3: Write the implementation**

`src/btf/core.py`:
```python
"""Core value objects and enums for the backtesting framework.

Every Protocol interface references these frozen dataclasses; they live in one
module to keep the dependency graph a DAG (no import cycles). Value objects
carry data only — no behavior.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class SignalKind(Enum):
    """Intention a strategy expresses about a position."""

    ENTRY = "entry"
    ADD = "add"
    EXIT = "exit"
    REDUCE = "reduce"


class Direction(Enum):
    """Trade direction. VCP is long-only; kept generic for other strategies."""

    LONG = "long"
    SHORT = "short"


class OrderType(Enum):
    """How an order fills. STOP = breakout of ``trigger_price`` (VCP pivot)."""

    MARKET = "market"
    STOP = "stop"
    LIMIT = "limit"


class FillKind(Enum):
    """What a fill did to the book. STOP_OUT is a protective-stop exit."""

    ENTRY = "entry"
    ADD = "add"
    EXIT = "exit"
    STOP_OUT = "stop_out"


class Regime(Enum):
    """Market regime label (situation-awareness). UNKNOWN = not yet classified."""

    BULL = "bull"
    BEAR = "bear"
    RANGE = "range"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Bar:
    """A single daily OHLCV bar for one symbol."""

    symbol: str
    ts: date
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True, slots=True)
class Signal:
    """A strategy's *intention* — what & why, never how many shares.

    Carries the strategy-computed initial ``stop_price`` (e.g. pivot - k*ATR;
    see initial-stop-and-r-multiple) and the ``trigger_price`` pivot, but no
    quantity or cash logic. The PositionSizer converts this into an Order.
    """

    symbol: str
    kind: SignalKind
    direction: Direction = Direction.LONG
    order_type: OrderType = OrderType.STOP
    trigger_price: float | None = None
    stop_price: float | None = None
    sizing_hint: float | None = None
    reason: str = ""
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Order:
    """A sized instruction ready for the broker (PositionSizer output).

    ``risk_per_share`` = entry-to-stop distance in price; the engine uses it to
    express results in R units (expectancy-and-position-sizing).
    """

    symbol: str
    direction: Direction
    kind: SignalKind
    order_type: OrderType
    quantity: int
    trigger_price: float | None
    stop_price: float | None
    risk_per_share: float
    reason: str = ""
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Fill:
    """A simulated execution produced by the Broker."""

    symbol: str
    ts: date
    price: float
    quantity: int
    direction: Direction
    kind: FillKind
    commission: float = 0.0
    slippage: float = 0.0
    reason: str = ""


@dataclass(frozen=True, slots=True)
class Position:
    """Read-only snapshot of a holding handed to the strategy via Context."""

    symbol: str
    direction: Direction
    quantity: int
    avg_price: float
    stop_price: float | None
    entry_ts: date
    risk_per_share: float


@dataclass(frozen=True, slots=True)
class Trade:
    """A closed round-trip trade. Maps to the vcp-breakout backtest template."""

    symbol: str
    direction: Direction
    entry_ts: date
    entry_price: float
    exit_ts: date
    exit_price: float
    quantity: int
    initial_stop: float
    r_multiple: float
    pnl: float
    regime: Regime
    reason_entry: str = ""
    reason_exit: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_core.py -v`
Expected: PASS (all tests).

- [ ] **Step 5: Commit**

```bash
git add src/btf/core.py tests/test_core.py
git commit -m "feat: freeze core value objects and enums"
```

---

### Task 3: Context layer (`btf/context/market.py`, `btf/context/context.py`)

**Files:**
- Create: `src/btf/context/market.py`
- Create: `src/btf/context/context.py`
- Test: `tests/test_context.py`

**Interfaces:**
- Consumes: `Regime`, `Bar`, `Position` from `btf.core`.
- Produces:
  - `MarketContext(as_of, regime, index_trend=None, breadth=None, meta={})` — frozen dataclass.
  - `Context` — `@runtime_checkable Protocol` with properties `as_of`, `cash`, `equity`, `positions`, `market`, `universe` and methods `history(symbol, lookback=None) -> pd.DataFrame`, `bar(symbol) -> Bar | None`.

- [ ] **Step 1: Write the failing test**

`tests/test_context.py`:
```python
from dataclasses import FrozenInstanceError, fields
from datetime import date

import pandas as pd
import pytest

from btf.context.context import Context
from btf.context.market import MarketContext
from btf.core import Bar, Regime


def test_market_context_fields_and_defaults():
    assert {f.name for f in fields(MarketContext)} == {
        "as_of", "regime", "index_trend", "breadth", "meta",
    }
    mc = MarketContext(as_of=date(2026, 1, 2), regime=Regime.BULL)
    assert mc.index_trend is None and mc.breadth is None and mc.meta == {}


def test_market_context_frozen():
    mc = MarketContext(as_of=date(2026, 1, 2), regime=Regime.BULL)
    with pytest.raises(FrozenInstanceError):
        mc.regime = Regime.BEAR


def test_context_protocol_is_runtime_checkable():
    class StubContext:
        as_of = date(2026, 1, 2)
        cash = 0.0
        equity = 0.0
        positions: dict = {}
        market = MarketContext(as_of=date(2026, 1, 2), regime=Regime.UNKNOWN)
        universe: list = []

        def history(self, symbol, lookback=None):
            return pd.DataFrame()

        def bar(self, symbol):
            return None

    assert isinstance(StubContext(), Context)


def test_incomplete_context_fails_protocol():
    class Missing:
        as_of = date(2026, 1, 2)

    assert not isinstance(Missing(), Context)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_context.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'btf.context.context'`.

- [ ] **Step 3: Write the implementations**

`src/btf/context/market.py`:
```python
"""Market regime / breadth snapshot (situation-awareness).

Reusable across strategies as an entry gate ("trade only with a tailwind").
Belongs to no single strategy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from btf.core import Regime


@dataclass(frozen=True, slots=True)
class MarketContext:
    """Point-in-time market state handed to the strategy inside Context."""

    as_of: date
    regime: Regime
    index_trend: float | None = None
    breadth: float | None = None
    meta: dict = field(default_factory=dict)
```

`src/btf/context/context.py`:
```python
"""The per-bar Context — the look-ahead firewall.

The engine constructs a Context each bar and hands it to ``Strategy.on_bar``.
Every accessor exposes only data with timestamp <= ``as_of``; the strategy
therefore cannot see future bars (bias defense, BACKTESTING_PLAN.md §6).
"""
from __future__ import annotations

from datetime import date
from typing import Mapping, Protocol, Sequence, runtime_checkable

import pandas as pd

from btf.context.market import MarketContext
from btf.core import Bar, Position


@runtime_checkable
class Context(Protocol):
    """Read-only view of the world at ``as_of`` handed to a strategy."""

    @property
    def as_of(self) -> date:
        """Timestamp of the current (most recent visible) bar."""
        ...

    @property
    def cash(self) -> float:
        """Available cash in the portfolio."""
        ...

    @property
    def equity(self) -> float:
        """Total portfolio equity (cash + marked-to-market positions)."""
        ...

    @property
    def positions(self) -> Mapping[str, Position]:
        """Open positions keyed by symbol (read-only snapshots)."""
        ...

    @property
    def market(self) -> MarketContext:
        """Current market regime / breadth (situation-awareness)."""
        ...

    @property
    def universe(self) -> Sequence[str]:
        """Point-in-time tradable symbols as of ``as_of``."""
        ...

    def history(self, symbol: str, lookback: int | None = None) -> pd.DataFrame:
        """OHLCV history for ``symbol`` with timestamps <= ``as_of``.

        ``lookback`` limits to the most recent N bars; None returns all
        available history. Never includes future bars.
        """
        ...

    def bar(self, symbol: str) -> Bar | None:
        """The current (``as_of``) bar for ``symbol``, or None if not trading."""
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_context.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/btf/context/market.py src/btf/context/context.py tests/test_context.py
git commit -m "feat: freeze MarketContext and Context look-ahead firewall"
```

---

### Task 4: DataProvider interface (`btf/data/provider.py`)

**Files:**
- Create: `src/btf/data/provider.py`
- Test: `tests/test_data_provider.py`

**Interfaces:**
- Consumes: `pandas` only (returns `DataFrame` / `Series`); no `btf.core` dependency.
- Produces: `DataProvider` — `@runtime_checkable Protocol` with `trading_calendar`, `universe`, `history`, `industry`, `earnings_dates`, `index`.

- [ ] **Step 1: Write the failing test**

`tests/test_data_provider.py`:
```python
from datetime import date

import pandas as pd

from btf.data.provider import DataProvider


def test_data_provider_protocol_stub():
    class StubProvider:
        def trading_calendar(self, start, end):
            return []

        def universe(self, on):
            return []

        def history(self, symbols, start, end, fields=("open", "high", "low", "close", "volume")):
            return pd.DataFrame()

        def industry(self, symbol, on):
            return None

        def earnings_dates(self, symbol):
            return []

        def index(self, name, start, end):
            return pd.Series(dtype=float)

    assert isinstance(StubProvider(), DataProvider)


def test_incomplete_provider_fails():
    class Missing:
        def universe(self, on):
            return []

    assert not isinstance(Missing(), DataProvider)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_data_provider.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'btf.data.provider'`.

- [ ] **Step 3: Write the implementation**

`src/btf/data/provider.py`:
```python
"""Vendor-agnostic market-data interface.

Neither the engine nor strategies bind to any data vendor; adapters (yfinance,
Stooq, Norgate, ...) implement this Protocol. Phase-1 free adapters carry
survivorship bias, which reports must flag (BACKTESTING_PLAN.md §3).
"""
from __future__ import annotations

from datetime import date
from typing import Protocol, Sequence, runtime_checkable

import pandas as pd


@runtime_checkable
class DataProvider(Protocol):
    """Point-in-time OHLCV, universe, and reference data."""

    def trading_calendar(self, start: date, end: date) -> list[date]:
        """Trading days in ``[start, end]`` inclusive."""
        ...

    def universe(self, on: date) -> list[str]:
        """Symbols that were index/universe members on ``on`` (delisted-inclusive in Phase 2)."""
        ...

    def history(
        self,
        symbols: Sequence[str],
        start: date,
        end: date,
        fields: Sequence[str] = ("open", "high", "low", "close", "volume"),
    ) -> pd.DataFrame:
        """Daily bars for ``symbols`` over ``[start, end]`` for the given ``fields``."""
        ...

    def industry(self, symbol: str, on: date) -> str | None:
        """Point-in-time sector/industry for ``symbol`` (optional; None if unknown)."""
        ...

    def earnings_dates(self, symbol: str) -> list[date]:
        """Known earnings-announcement dates (gap-risk: avoid pre-earnings entries)."""
        ...

    def index(self, name: str, start: date, end: date) -> pd.Series:
        """Benchmark index close series over ``[start, end]``."""
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_data_provider.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/btf/data/provider.py tests/test_data_provider.py
git commit -m "feat: freeze DataProvider interface"
```

---

### Task 5: Strategy, PositionSizer, Broker interfaces

**Files:**
- Create: `src/btf/strategies/base.py`
- Create: `src/btf/risk/sizer.py`
- Create: `src/btf/broker/broker.py`
- Test: `tests/test_strategy_risk_broker.py`

**Interfaces:**
- Consumes: `Signal`, `Order`, `Fill`, `Position`, `Bar` from `btf.core`; `Context` from `btf.context.context`.
- Produces:
  - `Strategy` — Protocol: attrs `name: str`, `warmup_bars: int`; method `on_bar(ctx) -> list[Signal]`.
  - `PositionSizer` — Protocol: `size(signals, ctx) -> list[Order]`.
  - `Broker` — Protocol: `execute(orders, bars) -> list[Fill]`, `sweep_stops(positions, bars) -> list[Fill]`.

- [ ] **Step 1: Write the failing test**

`tests/test_strategy_risk_broker.py`:
```python
from btf.broker.broker import Broker
from btf.risk.sizer import PositionSizer
from btf.strategies.base import Strategy


def test_strategy_protocol_stub():
    class StubStrategy:
        name = "stub"
        warmup_bars = 0

        def on_bar(self, ctx):
            return []

    assert isinstance(StubStrategy(), Strategy)


def test_strategy_missing_attr_fails():
    class NoWarmup:
        name = "x"

        def on_bar(self, ctx):
            return []

    assert not isinstance(NoWarmup(), Strategy)


def test_position_sizer_protocol_stub():
    class StubSizer:
        def size(self, signals, ctx):
            return []

    assert isinstance(StubSizer(), PositionSizer)


def test_broker_protocol_stub():
    class StubBroker:
        def execute(self, orders, bars):
            return []

        def sweep_stops(self, positions, bars):
            return []

    assert isinstance(StubBroker(), Broker)


def test_broker_missing_method_fails():
    class NoSweep:
        def execute(self, orders, bars):
            return []

    assert not isinstance(NoSweep(), Broker)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_strategy_risk_broker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'btf.strategies.base'`.

- [ ] **Step 3: Write the implementations**

`src/btf/strategies/base.py`:
```python
"""Strategy interface — emits *intentions* only, never touches cash or fills.

A strategy sees the world only through Context (data <= as_of), enforcing the
Strategy-perpendicular-Engine principle (code/CLAUDE.md).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from btf.context.context import Context
from btf.core import Signal


@runtime_checkable
class Strategy(Protocol):
    """Produces Signals from a per-bar Context. Knows nothing about execution."""

    name: str
    warmup_bars: int  # history needed before it can compute (MA200, ATR, ...)

    def on_bar(self, ctx: Context) -> list[Signal]:
        """Return the strategy's intentions for the current bar (may be empty)."""
        ...
```

`src/btf/risk/sizer.py`:
```python
"""Position sizing / risk interface.

Converts strategy Signals into sized Orders using the brain formula
size = R$ / stop_distance (expectancy-and-position-sizing), subject to
per-trade risk %, portfolio heat, and max-position limits.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from btf.context.context import Context
from btf.core import Order, Signal


@runtime_checkable
class PositionSizer(Protocol):
    """Turns intentions into sized orders. Owns cash/heat/max-position rules."""

    def size(self, signals: list[Signal], ctx: Context) -> list[Order]:
        """Return sized Orders for the given Signals (some may be dropped)."""
        ...
```

`src/btf/broker/broker.py`:
```python
"""Execution / broker model interface.

Simulates fills with slippage and commission, and models gap-through stops:
a gap that jumps a stop fills at the open, not the stop price (gap-risk).
"""
from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable

from btf.core import Bar, Fill, Order, Position


@runtime_checkable
class Broker(Protocol):
    """Turns Orders and stop conditions into simulated Fills."""

    def execute(self, orders: list[Order], bars: Mapping[str, Bar]) -> list[Fill]:
        """Fill pending orders against the execution bar (slippage + commission)."""
        ...

    def sweep_stops(self, positions: Mapping[str, Position], bars: Mapping[str, Bar]) -> list[Fill]:
        """Check each position's stop against ``bars``; gap-through fills at the open."""
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_strategy_risk_broker.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/btf/strategies/base.py src/btf/risk/sizer.py src/btf/broker/broker.py tests/test_strategy_risk_broker.py
git commit -m "feat: freeze Strategy, PositionSizer, and Broker interfaces"
```

---

### Task 6: Result objects & Engine interface

**Files:**
- Create: `src/btf/metrics/result.py`
- Create: `src/btf/engine/engine.py`
- Test: `tests/test_result_engine.py`

**Interfaces:**
- Consumes: `Trade`, `Regime` from `btf.core`; `pandas`; `Strategy`, `DataProvider`, `Broker`, `PositionSizer` from their modules.
- Produces:
  - `Metrics(num_trades, win_rate, avg_win_r, avg_loss_r, expectancy, profit_factor, max_losing_streak, max_drawdown_r, max_drawdown_pct, exposure)` — frozen dataclass, all required.
  - `BacktestResult(config, equity_curve, metrics, benchmark_curve=None, trades=[], regime_breakdown={})` — frozen dataclass.
  - `Engine` — Protocol: `run(strategy, data, broker, sizer, config) -> BacktestResult`.

- [ ] **Step 1: Write the failing test**

`tests/test_result_engine.py`:
```python
from dataclasses import fields

import pandas as pd

from btf.engine.engine import Engine
from btf.metrics.result import BacktestResult, Metrics


def test_metrics_fields():
    assert {f.name for f in fields(Metrics)} == {
        "num_trades", "win_rate", "avg_win_r", "avg_loss_r", "expectancy",
        "profit_factor", "max_losing_streak", "max_drawdown_r",
        "max_drawdown_pct", "exposure",
    }


def test_backtest_result_fields_and_defaults():
    assert {f.name for f in fields(BacktestResult)} == {
        "config", "equity_curve", "metrics", "benchmark_curve",
        "trades", "regime_breakdown",
    }
    m = Metrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0.0)
    r = BacktestResult(config={}, equity_curve=pd.Series(dtype=float), metrics=m)
    assert r.benchmark_curve is None
    assert r.trades == [] and r.regime_breakdown == {}


def test_engine_protocol_stub():
    class StubEngine:
        def run(self, strategy, data, broker, sizer, config):
            return None

    assert isinstance(StubEngine(), Engine)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_result_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'btf.metrics.result'`.

- [ ] **Step 3: Write the implementations**

`src/btf/metrics/result.py`:
```python
"""Backtest output objects. All metrics are in R units (initial-stop-and-r-multiple).

expectancy = win_rate * avg_win_R - loss_rate * avg_loss_R  (BACKTESTING_PLAN.md §4).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

import pandas as pd

from btf.core import Regime, Trade


@dataclass(frozen=True, slots=True)
class Metrics:
    """Summary statistics for a set of trades, in R units."""

    num_trades: int
    win_rate: float
    avg_win_r: float
    avg_loss_r: float
    expectancy: float
    profit_factor: float
    max_losing_streak: int
    max_drawdown_r: float
    max_drawdown_pct: float
    exposure: float


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """The complete, reproducible output of one backtest run."""

    config: Mapping
    equity_curve: pd.Series
    metrics: Metrics
    benchmark_curve: pd.Series | None = None
    trades: list[Trade] = field(default_factory=list)
    regime_breakdown: dict[Regime, Metrics] = field(default_factory=dict)
```

`src/btf/engine/engine.py`:
```python
"""Generic event-driven engine interface — knows nothing about VCP.

Advances the clock bar-by-bar: builds a Context (data <= today), calls the
strategy for Signals, sizes them via PositionSizer, simulates fills via Broker,
updates the portfolio, and returns a BacktestResult (BACKTESTING_PLAN.md §2.2).
"""
from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable

from btf.broker.broker import Broker
from btf.data.provider import DataProvider
from btf.metrics.result import BacktestResult
from btf.risk.sizer import PositionSizer
from btf.strategies.base import Strategy


@runtime_checkable
class Engine(Protocol):
    """Orchestrates one backtest run over a strategy, data, broker, and sizer."""

    def run(
        self,
        strategy: Strategy,
        data: DataProvider,
        broker: Broker,
        sizer: PositionSizer,
        config: Mapping,
    ) -> BacktestResult:
        """Run the full backtest and return its result. Enforces no look-ahead."""
        ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_result_engine.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest -v`
Expected: PASS (all tests across all files).

- [ ] **Step 6: Commit**

```bash
git add src/btf/metrics/result.py src/btf/engine/engine.py tests/test_result_engine.py
git commit -m "feat: freeze BacktestResult, Metrics, and Engine interface"
```

---

## Self-Review

**Spec coverage** (against `2026-07-01-m0-interfaces-design.md`):
- §3 module layout → Tasks 1–6 create every listed file. ✓
- §5 value objects + enums → Task 2. ✓
- §6 interfaces: DataProvider → Task 4; Strategy/PositionSizer/Broker → Task 5; Context/MarketContext → Task 3; Engine → Task 6. ✓
- §7 result objects → Task 6. ✓
- §8 contract tests (import, field lists, frozenness, enum members, Protocol stubs, defaults) → distributed across each task's test. ✓
- §9 tooling (pyproject, deps, gitignore) → Task 1 (`.gitignore` already committed with the spec). ✓
- §10 out-of-scope: no behavior implemented anywhere. ✓

**Placeholder scan:** No TBD/TODO; every code and test step shows complete content. ✓

**Type consistency:** `Context` referenced identically in Tasks 3/5/6; `Signal`/`Order`/`Fill`/`Position`/`Trade`/`Regime` field lists match the design §5/§7 and are asserted verbatim in tests. `BacktestResult` field order (config, equity_curve, metrics, then defaulted benchmark_curve/trades/regime_breakdown) is consistent between Task 6 impl and test. ✓

**Note:** `slots=True` is added to all frozen dataclasses (not in the design's prose but consistent with "frozen value objects"; improves memory/attr-safety and still passes `fields()` introspection). Enum `.value` strings are lowercase labels; tests assert on `.name`, so label choice is free.
