#!/usr/bin/env python3
"""Run a YAML-defined backtest, optionally with its M5 bias-defense protocol.

One YAML = one fully-defined run (core principle 5): universe, period, costs,
risk, strategy params, and the validation protocol all live in the config —
same config + same data snapshot => same result.

Usage (network on first run; cached to the config's cache_dir afterwards):

    pip install -e '.[data]'
    python scripts/run_config.py config/vcp_phase1.yaml             # base run
    python scripts/run_config.py config/vcp_phase1.yaml --validate  # + M5 defenses
"""
from __future__ import annotations

import argparse

from btf.config import build_provider, load_config, run_from_config
from btf.validation import (
    SMALL_SAMPLE_LEGEND,
    TABLE_HEADER,
    result_row,
    run_oos_split,
    run_sensitivity,
    run_walk_forward,
    sensitivity_report,
    split_report,
    walk_forward_report,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", help="path to a run-config YAML")
    parser.add_argument(
        "--validate", action="store_true",
        help="also run the config's validation sections (oos split / walk-forward / sensitivity)",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    provider = build_provider(cfg)  # one data snapshot shared by every run below

    print(f"{cfg.name}  {cfg.start}..{cfg.end}  {len(cfg.symbols)} symbols  "
          f"strategy={cfg.strategy.name}  risk={cfg.risk.risk_pct:.1%}/trade\n")
    result = run_from_config(cfg, provider)
    print(TABLE_HEADER)
    print("-" * len(TABLE_HEADER))
    print(result_row("base run", result))
    print(f"\nfinal equity: ${float(result.equity_curve.iloc[-1]):,.0f}  "
          f"(start ${cfg.risk.starting_cash:,.0f})")
    print(SMALL_SAMPLE_LEGEND)

    if args.validate:
        v = cfg.validation
        ran_any = False
        if v.oos_start is not None:
            print("\n" + "=" * 78 + "\n")
            print(split_report(run_oos_split(cfg, provider=provider)))
            ran_any = True
        if v.walk_forward_windows is not None:
            print("\n" + "=" * 78 + "\n")
            print(walk_forward_report(run_walk_forward(cfg, provider=provider)))
            ran_any = True
        if v.sensitivity:
            print("\n" + "=" * 78 + "\n")
            print(sensitivity_report(run_sensitivity(cfg, provider=provider)))
            ran_any = True
        if not ran_any:
            print("\n--validate given, but the config has no validation section.")

    if cfg.data.source == "bloomberg":
        missing = sorted(getattr(provider, "missing_symbols", []))
        print("\nData: Bloomberg snapshot — survivorship-free PIT S&P 500 universe "
              "(monthly membership granularity; see M6 spec).")
        if missing:
            head = ", ".join(missing[:15]) + (" ..." if len(missing) > 15 else "")
            print(f"[!] coverage: {len(missing)} member(s) without cached bars: {head}")
    else:
        print("\n[!] SELECTION / SURVIVORSHIP BIAS (Phase-1): hand-picked, currently-listed "
              "symbols; no delisted names. Expectancy is upward-biased until M6's "
              "survivorship-free data. See BACKTESTING_PLAN.md §6.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
