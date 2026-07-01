"""Books reconcile after a buy-and-hold run (design spec §8.2)."""
from __future__ import annotations

from datetime import date

import pytest

from btf.broker.simple_broker import SimpleBroker
from btf.engine.basic_engine import BasicEngine
from btf.risk.fixed_risk_sizer import FixedRiskSizer
from btf.strategies.buy_and_hold import BuyAndHold
from btf.data.memory_provider import InMemoryDataProvider
from tests.m1_fixtures import make_frame, uptrend_provider


def test_books_reconcile_single_symbol():
    starting_cash = 100_000.0
    result = BasicEngine().run(
        strategy=BuyAndHold(nominal_stop_pct=0.5),
        data=uptrend_provider("AAA", days=10),
        broker=SimpleBroker(),
        sizer=FixedRiskSizer(risk_pct=0.02),
        config={"start": date(2020, 1, 1), "end": date(2020, 1, 10), "starting_cash": starting_cash},
    )
    assert len(result.trades) == 1  # exactly one Trade per symbol
    total_pnl = sum(t.pnl for t in result.trades)
    final_equity = float(result.equity_curve.iloc[-1])
    # starting_cash + Σ pnl == final cash == final equity (flat after liquidation).
    assert starting_cash + total_pnl == pytest.approx(final_equity)


def test_books_reconcile_two_symbols():
    dates = [date(2020, 1, d) for d in range(1, 8)]
    a = make_frame(dates, [100 + i for i in range(7)], [102 + i for i in range(7)],
                   [99 + i for i in range(7)], [101 + i for i in range(7)])
    b = make_frame(dates, [50 + i for i in range(7)], [52 + i for i in range(7)],
                   [49 + i for i in range(7)], [51 + i for i in range(7)])
    prov = InMemoryDataProvider({"AAA": a, "BBB": b})
    starting_cash = 50_000.0
    result = BasicEngine().run(
        strategy=BuyAndHold(nominal_stop_pct=0.5),
        data=prov,
        broker=SimpleBroker(),
        sizer=FixedRiskSizer(risk_pct=0.02),
        config={"start": date(2020, 1, 1), "end": date(2020, 1, 7), "starting_cash": starting_cash},
    )
    assert len(result.trades) == 2
    total_pnl = sum(t.pnl for t in result.trades)
    final_equity = float(result.equity_curve.iloc[-1])
    assert starting_cash + total_pnl == pytest.approx(final_equity)
