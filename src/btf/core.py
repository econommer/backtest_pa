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
    meta: dict[str, object] = field(default_factory=dict)


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
    meta: dict[str, object] = field(default_factory=dict)


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
