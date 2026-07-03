#!/usr/bin/env python3
# scripts/fetch_assets_snapshot.py
"""Budgeted Bloomberg fetch for ARBITRARY securities (commodities / FX futures /
country indices). DRY-RUN BY DEFAULT — nothing is requested without --confirm.

Additive companion to fetch_bloomberg_snapshot.py (which is S&P-membership-
driven): this one takes a symbols file of FULL Bloomberg securities (yellow key
included, e.g. "CL1 Comdty", "EC1 Curncy", "NKY Index") and caches each under
that same string as the framework symbol. Shares the same usage ledger and
failures file, so equity and asset-class fetches draw on one daily budget.

    python scripts/fetch_assets_snapshot.py                  # plan only
    python scripts/fetch_assets_snapshot.py --confirm        # fetch

Requires the Bloomberg Terminal running + logged in on this machine.
"""
from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from btf.data._cache import cache_path, write_cache
from btf.data._normalize import normalize_ohlcv
from btf.data.bloomberg.fetch import (
    FAILURES_FILENAME,
    _load_failures,
    _save_failures,
    bloomberg_dir,
)
from btf.data.bloomberg.ledger import UsageLedger


def read_symbols(path: str | Path) -> list[str]:
    out = []
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols-file", default="config/universe_asset_classes.txt")
    parser.add_argument("--confirm", action="store_true",
                        help="actually fetch (default: dry-run plan only)")
    parser.add_argument("--max-new-per-day", type=int, default=300)
    parser.add_argument("--cache-dir", default="data_cache")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2010, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2025, 12, 31))
    parser.add_argument("--batch-size", type=int, default=50)
    args = parser.parse_args()
    today = date.today()

    bdir = bloomberg_dir(args.cache_dir)
    ledger = UsageLedger.load(bdir / "usage_ledger.json")
    failures = _load_failures(bdir)
    symbols = read_symbols(args.symbols_file)

    cached = [s for s in symbols
              if cache_path(args.cache_dir, "bloomberg", s, args.start, args.end, True).exists()]
    todo = [s for s in symbols if s not in set(cached) and s not in failures]
    failed = [s for s in symbols if s in failures]
    allowance = ledger.allowance(today, args.max_new_per_day)
    print(f"ledger: {ledger.known_count} unique securities ever, "
          f"{ledger.new_on(today)} new today, allowance today = {allowance}")
    print(f"assets plan: {len(symbols)} securities | {len(cached)} cached | "
          f"{len(failed)} failed previously | {len(todo)} to fetch | "
          f"{min(len(todo), allowance)} allowed today")
    if not args.confirm:
        print("dry-run only. Re-run with --confirm to fetch.")
        return 0
    if not todo:
        print("nothing to fetch.")
        return 0

    from btf.data.bloomberg.session import BlpSession
    session = BlpSession()
    try:
        fetched: list[str] = []
        new_failed: dict[str, str] = {}
        budget_stopped = False
        i = 0
        while i < len(todo):
            batch = todo[i:i + args.batch_size]  # security string IS the symbol
            allowance = ledger.allowance(today, args.max_new_per_day)
            n_new = len(ledger.new_securities(batch))
            if n_new > allowance:
                keep, new_seen = 0, 0
                for s in batch:  # longest prefix that fits the allowance
                    new_seen += 1 if ledger.new_securities([s]) else 0
                    if new_seen > allowance:
                        break
                    keep += 1
                batch = batch[:keep]
                budget_stopped = True
                if not batch:
                    break
            ledger.record(batch, today)  # count first — failed requests still count
            frames = session.daily_bars(batch, args.start, args.end)
            for sym in batch:
                raw = frames.get(sym)
                if raw is None or len(raw) == 0:
                    new_failed[sym] = "no data"
                    continue
                frame = normalize_ohlcv(raw)
                write_cache(cache_path(args.cache_dir, "bloomberg", sym,
                                       args.start, args.end, True), frame)
                fetched.append(sym)
            if budget_stopped:
                break
            i += args.batch_size
        if new_failed:
            _save_failures(bdir, {**failures, **new_failed})
        remaining = len(todo) - len(fetched) - len(new_failed)
        print(f"fetched {len(fetched)} | failed {len(new_failed)} "
              f"({FAILURES_FILENAME}) | remaining {remaining}"
              + (" | STOPPED at daily budget" if budget_stopped else ""))
        return 0
    finally:
        session.close()  # ledger persists itself on every record()


if __name__ == "__main__":
    raise SystemExit(main())
