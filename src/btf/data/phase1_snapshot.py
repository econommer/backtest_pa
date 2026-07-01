"""Pinned Phase-1 data snapshot — the fixed universe the smoke test runs on (M2).

One place defines *which* real tickers, *what* date range, and *where* the cached
parquet lives, so the fetch script (``scripts/fetch_snapshot.py``) and the smoke
test agree on the exact same snapshot. A backtest run pins its data to whatever
parquet files sit under :data:`CACHE_DIR`; commit that directory (or share it) to
freeze the snapshot for reproducible reruns.

**Survivorship bias (Phase 1).** This universe is a *static, currently-listed*
handful of large-caps. It excludes every company that was delisted/merged/went
to zero over the window, so any performance it produces is upward-biased. Phase 2
(a delisted-inclusive provider) removes this; until then, reports must say so —
see :func:`survivorship_warning`.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from btf.data._cache import cache_path

# Repo root: src/btf/data/phase1_snapshot.py -> parents[3].
_REPO_ROOT = Path(__file__).resolve().parents[3]

#: Static Phase-1 universe (currently-listed large-caps — survivorship-biased).
SYMBOLS: list[str] = ["AAPL", "MSFT", "KO", "JNJ", "PG"]
#: Benchmark for the buy-and-hold-the-index overlay.
BENCHMARK: str = "SPY"
START: date = date(2018, 1, 1)
END: date = date(2023, 1, 1)
SOURCE: str = "yfinance"
ADJUSTED: bool = True

#: Cache location; override with BTF_CACHE_DIR to point runs at a shared snapshot.
CACHE_DIR: Path = Path(os.environ.get("BTF_CACHE_DIR", _REPO_ROOT / "data_cache"))


def _all_symbols() -> list[str]:
    return [*SYMBOLS, BENCHMARK]


def is_cached(cache_dir: Path | None = None) -> bool:
    """True only if every snapshot symbol (incl. benchmark) is on disk."""
    cdir = cache_dir or CACHE_DIR
    return all(
        cache_path(cdir, SOURCE, sym, START, END, ADJUSTED).exists()
        for sym in _all_symbols()
    )


def missing_symbols(cache_dir: Path | None = None) -> list[str]:
    cdir = cache_dir or CACHE_DIR
    return [
        sym
        for sym in _all_symbols()
        if not cache_path(cdir, SOURCE, sym, START, END, ADJUSTED).exists()
    ]


def build_provider(cache_dir: Path | None = None, fetch_fn=None):
    """Construct the ``YFinanceDataProvider`` for the pinned snapshot.

    With everything cached, ``fetch_fn`` is never called (safe offline). Pass a
    real (or default) fetcher only when populating the cache.
    """
    from btf.data.yfinance_provider import YFinanceDataProvider

    return YFinanceDataProvider(
        SYMBOLS,
        START,
        END,
        cache_dir=cache_dir or CACHE_DIR,
        benchmark_symbol=BENCHMARK,
        fetch_fn=fetch_fn,
        adjusted=ADJUSTED,
    )


def survivorship_warning() -> str:
    """A one-line bias disclaimer to stamp on any Phase-1 output."""
    return (
        "⚠ SURVIVORSHIP BIAS: Phase-1 static universe "
        f"({', '.join(SYMBOLS)}) — currently-listed only; delisted names excluded. "
        "Results are upward-biased. Fix in Phase 2 (delisted-inclusive provider)."
    )
