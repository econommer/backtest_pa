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
