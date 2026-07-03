#!/usr/bin/env python3
# scripts/fetch_bloomberg_snapshot.py
"""Budgeted Bloomberg snapshot fetch (M6). DRY-RUN BY DEFAULT — nothing is
requested without --confirm, and a hard daily budget (--max-new-per-day)
stops the run BEFORE Bloomberg's opaque unique-security cap is at risk.

Two stages (spec D5):

    python scripts/fetch_bloomberg_snapshot.py --stage membership            # plan
    python scripts/fetch_bloomberg_snapshot.py --stage membership --confirm  # ~1 unique security
    python scripts/fetch_bloomberg_snapshot.py --stage bars                  # exact plan
    python scripts/fetch_bloomberg_snapshot.py --stage bars --confirm        # repeat daily until done

Requires the Bloomberg Terminal running + logged in on this machine, and:
    pip install blpapi --index-url=https://blpapi.bloomberg.com/repository/releases/python/simple/
"""
from __future__ import annotations

import argparse
from datetime import date

from btf.data.bloomberg import fetch
from btf.data.bloomberg.ledger import UsageLedger


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=["membership", "bars"], required=True)
    parser.add_argument("--confirm", action="store_true",
                        help="actually fetch (default: dry-run plan only)")
    parser.add_argument("--max-new-per-day", type=int, default=300)
    parser.add_argument("--cache-dir", default="data_cache")
    parser.add_argument("--start", type=date.fromisoformat, default=date(2010, 1, 1))
    parser.add_argument("--end", type=date.fromisoformat, default=date(2025, 12, 31))
    parser.add_argument("--universe-out", default="config/universe_spx_2010_2025.txt")
    args = parser.parse_args()
    today = date.today()

    ledger = UsageLedger.load(fetch.bloomberg_dir(args.cache_dir) / "usage_ledger.json")
    print(f"ledger: {ledger.known_count} unique securities ever, "
          f"{ledger.new_on(today)} new today, "
          f"allowance today = {ledger.allowance(today, args.max_new_per_day)}")

    if args.stage == "membership":
        months = fetch.month_ends(args.start, args.end)
        print(f"membership plan: {len(months)} monthly snapshots of {fetch.INDEX_SECURITY} "
              f"= 1 unique security, ~{len(months) + 1} requests (incl. SPX bars)")
        if not args.confirm:
            print("dry-run only. Re-run with --confirm to fetch.")
            return 0
        from btf.data.bloomberg.session import BlpSession
        session = BlpSession()
        try:
            m = fetch.fetch_membership(session, ledger, args.cache_dir,
                                       args.start, args.end, on=today,
                                       max_new_per_day=args.max_new_per_day)
            fetch.fetch_benchmark(session, ledger, args.cache_dir,
                                  args.start, args.end, on=today)
        finally:
            session.close()
        symbols = fetch.write_universe_file(m, args.universe_out)
        per_month = m.groupby("snapshot")["symbol"].count()
        print(f"membership: {len(symbols)} distinct members over {len(per_month)} months "
              f"(min {per_month.min()}, max {per_month.max()} per month)")
        print(f"universe file written: {args.universe_out}")
        return 0

    # stage == "bars"
    try:
        plan = fetch.plan_bars(ledger, args.cache_dir, args.start, args.end,
                               on=today, max_new_per_day=args.max_new_per_day)
    except FileNotFoundError:
        print("no membership snapshot yet — run --stage membership first")
        return 1
    print(f"bars plan: {plan.members} members | {plan.cached} cached | "
          f"{plan.failed} failed previously | {plan.todo} to fetch | "
          f"{plan.allowed_today} allowed today")
    if not args.confirm:
        print("dry-run only. Re-run with --confirm to fetch.")
        return 0
    from btf.data.bloomberg.session import BlpSession
    session = BlpSession()
    try:
        res = fetch.fetch_bars(session, ledger, args.cache_dir, args.start, args.end,
                               on=today, max_new_per_day=args.max_new_per_day)
    finally:
        session.close()
    print(f"fetched {len(res.fetched)}, failed {len(res.failed)}, "
          f"remaining {res.remaining}")
    if res.budget_stopped:
        print(f"daily budget ({args.max_new_per_day} new securities) reached — "
              f"re-run tomorrow to continue. Nothing exceeded the cap.")
    elif res.remaining == 0:
        print("snapshot complete. Next: "
              "python scripts/run_config.py config/vcp_phase2_bloomberg.yaml --validate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
