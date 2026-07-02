"""Offline stand-ins for the Bloomberg session (tests never import blpapi)."""
from __future__ import annotations

from datetime import date
from typing import Mapping, Sequence

import numpy as np
import pandas as pd


def raw_bars(start: str, periods: int, seed: int = 0) -> pd.DataFrame:
    """A plausible raw daily OHLCV frame as the session would return it."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(start, periods=periods)
    close = 100 + np.cumsum(rng.normal(0, 1, periods))
    return pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": rng.integers(1e5, 1e6, periods).astype(float),
        },
        index=idx,
    )


class FakeSession:
    """SessionLike double: canned members per month-end, canned bars per security."""

    def __init__(
        self,
        members_by_month: Mapping[date, list[str]] | None = None,
        bars: Mapping[str, pd.DataFrame] | None = None,
    ) -> None:
        self.members_by_month = dict(members_by_month or {})
        self.bars = dict(bars or {})  # keyed by SECURITY string ("AAPL US Equity")
        self.calls: list[tuple] = []

    def index_members(self, index_security: str, on: date) -> list[str]:
        self.calls.append(("members", index_security, on))
        return list(self.members_by_month[on])

    def daily_bars(
        self, securities: Sequence[str], start: date, end: date
    ) -> dict[str, pd.DataFrame]:
        self.calls.append(("bars", tuple(securities), start, end))
        # Securities absent from self.bars simply return nothing (Bloomberg
        # securityError behaves the same from the caller's viewpoint).
        return {s: self.bars[s] for s in securities if s in self.bars}
