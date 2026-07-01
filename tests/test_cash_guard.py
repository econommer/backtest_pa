"""Fill-time cash guard: a t+1 open gap-up must never drive cash negative (M2).

The sizer budgets against the *t-close* price, but the fill happens at the *t+1
open*. A gap up can make the fill cost more than the cash on hand. Per the M2
decision, ``apply_entry`` then **skips the entry entirely** — no lot, no cash
movement — rather than short-filling.
"""
from __future__ import annotations

from datetime import date

import pytest

from btf.broker.simple_broker import SimpleBroker
from btf.core import Direction, FillKind, Fill, Order, OrderType, SignalKind
from btf.data.memory_provider import InMemoryDataProvider
from btf.engine.basic_engine import BasicEngine
from btf.portfolio.portfolio import Portfolio
from btf.risk.fixed_risk_sizer import FixedRiskSizer
from btf.strategies.buy_and_hold import BuyAndHold
from tests.m1_fixtures import make_frame


def _entry(symbol: str, qty: int, price: float, stop: float) -> tuple[Fill, Order]:
    fill = Fill(
        symbol=symbol,
        ts=date(2020, 1, 2),
        price=price,
        quantity=qty,
        direction=Direction.LONG,
        kind=FillKind.ENTRY,
    )
    order = Order(
        symbol=symbol,
        direction=Direction.LONG,
        kind=SignalKind.ENTRY,
        order_type=OrderType.MARKET,
        quantity=qty,
        trigger_price=None,
        stop_price=stop,
        risk_per_share=price - stop,
    )
    return fill, order


def test_apply_entry_skips_when_fill_exceeds_cash():
    pf = Portfolio(starting_cash=1_000.0)
    # 10 shares @ 200 = 2000 > 1000 cash → skip.
    fill, order = _entry("AAA", qty=10, price=200.0, stop=150.0)
    pf.apply_entry(fill, order)
    assert pf.cash == 1_000.0  # untouched
    assert pf.open_symbols() == []  # no lot opened


def test_apply_entry_allows_affordable_fill():
    pf = Portfolio(starting_cash=1_000.0)
    fill, order = _entry("AAA", qty=4, price=200.0, stop=150.0)  # 800 <= 1000
    pf.apply_entry(fill, order)
    assert pf.cash == pytest.approx(200.0)
    assert pf.open_symbols() == ["AAA"]


def test_apply_entry_exact_cash_is_allowed():
    pf = Portfolio(starting_cash=800.0)
    fill, order = _entry("AAA", qty=4, price=200.0, stop=150.0)  # exactly 800
    pf.apply_entry(fill, order)
    assert pf.cash == pytest.approx(0.0)
    assert pf.open_symbols() == ["AAA"]


def test_gap_up_open_overshoots_budget_no_position_and_cash_intact():
    """End-to-end: entry sized at t-close, t+1 opens far higher → skipped."""
    dates = [date(2020, 1, d) for d in range(1, 4)]
    # Day 1 close 100 (sizer budgets here); day 2 GAPS UP to open 400.
    opens = [100.0, 400.0, 410.0]
    closes = [100.0, 405.0, 415.0]
    highs = [101.0, 420.0, 430.0]
    lows = [99.0, 395.0, 405.0]
    prov = InMemoryDataProvider({"AAA": make_frame(dates, opens, highs, lows, closes)})

    starting_cash = 1_000.0
    result = BasicEngine().run(
        strategy=BuyAndHold(nominal_stop_pct=0.5),
        data=prov,
        broker=SimpleBroker(),
        sizer=FixedRiskSizer(risk_pct=1.0),  # aggressive → cash is the binding cap
        config={"start": dates[0], "end": dates[-1], "starting_cash": starting_cash},
    )
    # The gap-up fill (>=400/share) exceeds the ~1000 budget → entry skipped.
    assert result.trades == []
    # Books reconcile and cash never went negative.
    final_equity = float(result.equity_curve.iloc[-1])
    assert final_equity == pytest.approx(starting_cash)
    assert (result.equity_curve >= 0).all()
