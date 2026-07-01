"""Shared OHLCV normalization — vendor frame → engine-ready hygiene (M2).

Every network adapter (yfinance, Stooq, ...) funnels its raw vendor frame through
:func:`normalize_ohlcv` so the output matches ``InMemoryDataProvider`` exactly and
never surprises the engine:

* lowercase ``open/high/low/close/volume`` columns, ``float64`` dtype;
* a tz-naive ``DatetimeIndex`` normalized to midnight (BACKTESTING_PLAN.md §6 —
  the engine looks bars up with ``pd.Timestamp(date)``; a tz-aware or intraday
  index would miss every bar);
* NaN rows dropped, duplicate days de-duped (keep last), index sorted ascending.

Adjusted prices (splits/dividends) are the *fetcher's* job (e.g. yfinance
``auto_adjust=True``); this module assumes the incoming frame is already adjusted.
"""
from __future__ import annotations

from typing import Sequence

import pandas as pd

_OHLCV = ("open", "high", "low", "close", "volume")


def normalize_ohlcv(
    raw: pd.DataFrame, fields: Sequence[str] = _OHLCV
) -> pd.DataFrame:
    """Return a single-symbol frame conforming to the provider contract.

    Idempotent: re-normalizing an already-clean frame is a no-op, so cached
    frames can be round-tripped safely.
    """
    fields = list(fields)
    empty = pd.DataFrame(
        columns=fields, index=pd.DatetimeIndex([], name="ts")
    ).astype(float)
    if raw is None or len(raw) == 0:
        return empty

    df = raw.copy()

    # yfinance hands back MultiIndex columns (field, ticker) for a single ticker;
    # collapse to the field level.
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # Case-insensitive column pick: map lowercased vendor names → our fields.
    lower_map: dict[str, str] = {}
    for col in df.columns:
        key = str(col).lower()
        if key in fields and key not in lower_map:
            lower_map[key] = col
    missing = [f for f in fields if f not in lower_map]
    if missing:
        raise KeyError(f"raw frame missing required field(s): {missing}")
    df = df[[lower_map[f] for f in fields]]
    df.columns = fields

    # Index → tz-naive midnight.
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    df.index = idx.normalize()
    df.index.name = "ts"

    df = df.astype(float)
    df = df.dropna(how="any")
    df = df[~df.index.duplicated(keep="last")]
    df = df.sort_index()
    return df
