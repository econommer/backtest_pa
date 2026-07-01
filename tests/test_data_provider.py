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
