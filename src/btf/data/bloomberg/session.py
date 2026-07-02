"""Bloomberg session seam (M6 spec §4).

``SessionLike`` is what the fetch pipeline types against; tests inject a fake.
The real ``BlpSession`` (added with the CLI task) is the ONLY code in the repo
that imports ``blpapi`` — lazily, so the package is an optional dependency.
"""
from __future__ import annotations

from datetime import date
from typing import Protocol, Sequence, runtime_checkable

import pandas as pd


class BloombergError(RuntimeError):
    """Bloomberg session/API failure with an actionable message."""


@runtime_checkable
class SessionLike(Protocol):
    """The two Bloomberg operations the M6 pipeline needs."""

    def index_members(self, index_security: str, on: date) -> list[str]:
        """Index members as of ``on`` (INDX_MWEIGHT_HIST with END_DATE_OVERRIDE)."""
        ...

    def daily_bars(
        self, securities: Sequence[str], start: date, end: date
    ) -> dict[str, pd.DataFrame]:
        """Raw daily OHLCV per security; securities with no data are absent."""
        ...
