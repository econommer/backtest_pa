"""On-disk parquet cache for fetched OHLCV, keyed by source+symbol+range (M2).

Cache-hit reads skip the network entirely, so reruns are fast and — crucially —
*deterministic*: a backtest run pins its data snapshot to whatever parquet files
sit in the cache directory. Commit the cache dir (or point runs at a shared one)
to freeze the snapshot for reproducibility (BACKTESTING_PLAN.md §0, principle 5).

Frames are stored already-normalized (see ``_normalize``); the read path returns
them ready to serve.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd


def cache_path(
    cache_dir: str | Path,
    source: str,
    symbol: str,
    start: date,
    end: date,
    adjusted: bool,
) -> Path:
    """Deterministic parquet path for one symbol's fetched range.

    Symbols are slugged so path-hostile tickers (``BRK.B``, ``^GSPC``) stay safe.
    """
    slug = symbol.replace("/", "-").replace("\\", "-").replace("^", "_").replace(".", "-")
    adj = "adj" if adjusted else "raw"
    fname = f"{slug}__{start.isoformat()}__{end.isoformat()}__{adj}.parquet"
    return Path(cache_dir) / source / fname


def read_cache(path: str | Path) -> pd.DataFrame | None:
    """Return the cached frame, or ``None`` on a miss."""
    p = Path(path)
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    # Parquet widens the datetime resolution (s → ms); coerce back so a cache-hit
    # frame is byte-identical to a freshly normalized one. Midnight → no loss.
    if isinstance(df.index, pd.DatetimeIndex):
        df.index = df.index.as_unit("s")
    df.index.name = "ts"
    return df


def write_cache(path: str | Path, df: pd.DataFrame) -> None:
    """Persist ``df`` to ``path`` (creating parent dirs)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p)
