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
