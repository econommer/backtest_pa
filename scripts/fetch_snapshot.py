#!/usr/bin/env python3
"""Populate the pinned Phase-1 data snapshot cache (run once, with network).

Downloads adjusted daily bars for the fixed universe defined in
``btf.data.phase1_snapshot`` and writes them to the parquet cache. After this
runs, the smoke test (``tests/test_smoke_real_data.py``) and any backtest reading
the same ``CACHE_DIR`` work fully offline and deterministically.

Usage (in an environment allowed to reach Yahoo Finance)::

    pip install -e '.[data]'          # yfinance + pyarrow
    python scripts/fetch_snapshot.py  # writes ./data_cache/yfinance/*.parquet

Then commit ./data_cache (or set BTF_CACHE_DIR to a shared location) to pin the
snapshot. Re-running is a no-op for already-cached symbols.
"""
from __future__ import annotations

import sys

from btf.data import phase1_snapshot as snap


def main() -> int:
    print(f"Snapshot: {snap.SYMBOLS} + benchmark {snap.BENCHMARK}")
    print(f"Range   : {snap.START} .. {snap.END}  (adjusted={snap.ADJUSTED})")
    print(f"Cache   : {snap.CACHE_DIR}")
    missing = snap.missing_symbols()
    if not missing:
        print("All symbols already cached — nothing to do.")
        return 0
    print(f"Fetching {len(missing)} missing symbol(s): {missing}")

    # fetch_fn=None → the adapter's default yfinance downloader (needs network).
    snap.build_provider(fetch_fn=None)

    still_missing = snap.missing_symbols()
    if still_missing:
        print(f"ERROR: still missing after fetch: {still_missing}", file=sys.stderr)
        print("(No data returned — check the ticker / date range / network.)", file=sys.stderr)
        return 1
    print("Done. Snapshot cached; the smoke test will now run offline.")
    print(snap.survivorship_warning())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
