"""Every M1 class isinstance-satisfies its frozen M0 Protocol (design spec §8.5)."""
from __future__ import annotations

from datetime import date

from btf.broker.broker import Broker
from btf.broker.simple_broker import SimpleBroker
from btf.context.backtest_context import BacktestContext
from btf.context.context import Context
from btf.context.market import MarketContext
from btf.core import Regime
from btf.data.memory_provider import InMemoryDataProvider
from btf.data.provider import DataProvider
from btf.engine.basic_engine import BasicEngine
from btf.engine.engine import Engine
from btf.risk.fixed_risk_sizer import FixedRiskSizer
from btf.risk.sizer import PositionSizer
from btf.strategies.base import Strategy
from btf.strategies.buy_and_hold import BuyAndHold
from tests.m1_fixtures import uptrend_provider


def test_m1_classes_satisfy_protocols():
    assert isinstance(BasicEngine(), Engine)
    assert isinstance(uptrend_provider(), InMemoryDataProvider)
    assert isinstance(uptrend_provider(), DataProvider)
    assert isinstance(SimpleBroker(), Broker)
    assert isinstance(FixedRiskSizer(risk_pct=0.01), PositionSizer)
    assert isinstance(BuyAndHold(), Strategy)
    ctx = BacktestContext({}, date(2020, 1, 1), 0.0, 0.0, {},
                          MarketContext(date(2020, 1, 1), Regime.UNKNOWN), [])
    assert isinstance(ctx, Context)
