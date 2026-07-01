"""Shared hand-made fixtures for the M1 tests (no network, deterministic)."""
from __future__ import annotations

from datetime import date

import pandas as pd

from btf.data.memory_provider import InMemoryDataProvider


def make_frame(dates: list[date], opens, highs, lows, closes, volumes=None) -> pd.DataFrame:
    n = len(dates)
    if volumes is None:
        volumes = [1000.0] * n
    return pd.DataFrame(
        {"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes},
        index=pd.DatetimeIndex(dates),
    )


def uptrend_provider(symbol: str = "AAA", days: int = 10) -> InMemoryDataProvider:
    """A single symbol trending straight up — stops never trigger."""
    dates = [date(2020, 1, d) for d in range(1, days + 1)]
    opens = [100.0 + i for i in range(days)]
    closes = [100.5 + i for i in range(days)]
    highs = [c + 1.0 for c in closes]
    lows = [o - 1.0 for o in opens]
    return InMemoryDataProvider({symbol: make_frame(dates, opens, highs, lows, closes)})


def gap_through_provider(symbol: str = "AAA") -> InMemoryDataProvider:
    """Up for a few bars (so an entry fills), then a gap-down that jumps a resting stop."""
    dates = [date(2020, 1, d) for d in range(1, 7)]
    # bars 1-3 uptrend; bar 4 opens far below the prior lows → gaps through any stop.
    opens = [100.0, 101.0, 102.0, 70.0, 71.0, 72.0]
    closes = [101.0, 102.0, 103.0, 69.0, 72.0, 73.0]
    highs = [102.0, 103.0, 104.0, 71.0, 73.0, 74.0]
    lows = [99.0, 100.0, 101.0, 68.0, 70.0, 71.0]
    return InMemoryDataProvider({symbol: make_frame(dates, opens, highs, lows, closes)})
