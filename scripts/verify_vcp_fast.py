#!/usr/bin/env python3
"""Trust-gate for the M6 Phase-2 fast run — is the snapshot + result safe to read?

``vcp_fast_m6.py`` will happily print metrics off a half-filled snapshot. Before
those numbers get pasted into the brain's Evidence section, this script answers a
narrower question: *can we trust this run at all?* It runs the same base backtest
and asserts a checklist of invariants, exiting non-zero (CI-style) if any HARD
check fails. WARN-level findings (partial coverage, small sample) are surfaced
but do not fail — they are expected while the Bloomberg snapshot is still filling.

Checks
  HARD (exit 1 on failure):
    - membership snapshot present and the point-in-time universe is non-empty
    - benchmark curve present, positive, finite
    - at least one member has cached bars (coverage > 0)
    - sampled cached bars are non-empty with strictly-positive closes
    - equity curve is finite and strictly positive throughout
    - metrics are a pure function of the trades + equity curve (internal identity)
    - every closed trade has a finite R-multiple; win rate in [0, 1]
    - (--repro) a second identical run yields identical metrics + equity curve
  WARN (reported, non-fatal):
    - coverage < 100 % (partial snapshot)
    - fewer than 30 trades (not statistically significant)

Usage:

    python scripts/verify_vcp_fast.py                                 # phase-2 config
    python scripts/verify_vcp_fast.py config/vcp_phase2_bloomberg.yaml
    python scripts/verify_vcp_fast.py --repro                         # + reproducibility (2nd run)
    python scripts/verify_vcp_fast.py --sample 50                     # spot-check more symbols
"""
from __future__ import annotations

import argparse
import math
import sys

import pandas as pd

# Keep the checklist printable on a Windows cp1252 console (em-dash separators).
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

from btf.config import RunConfig, build_provider, load_config, run_from_config
from btf.metrics.compute import compute_metrics
from btf.metrics.result import BacktestResult
from btf.validation import MIN_SIGNIFICANT_TRADES

DEFAULT_CONFIG = "config/vcp_phase2_bloomberg.yaml"


class Gate:
    """Accumulates checks; ``ok`` is False if any HARD check failed."""

    def __init__(self) -> None:
        self.ok = True
        self.lines: list[str] = []

    def hard(self, name: str, passed: bool, detail: str = "") -> bool:
        mark = "PASS" if passed else "FAIL"
        self.lines.append(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))
        if not passed:
            self.ok = False
        return passed

    def warn(self, name: str, clean: bool, detail: str = "") -> None:
        mark = "ok  " if clean else "WARN"
        self.lines.append(f"  [{mark}] {name}" + (f" — {detail}" if detail else ""))

    def report(self) -> None:
        print("\n".join(self.lines))


def _finite_positive(series: pd.Series) -> bool:
    arr = series.to_numpy(dtype=float)
    return bool(len(arr)) and bool((arr > 0).all()) and not bool(pd.isna(arr).any())


def verify(cfg: RunConfig, provider: object, result: BacktestResult,
           gate: Gate, sample: int) -> None:
    # --- snapshot / universe -------------------------------------------------
    pit = provider.universe(cfg.end)  # type: ignore[attr-defined]
    gate.hard("point-in-time universe non-empty at end date",
              bool(pit), f"{len(pit)} members on/before {cfg.end}")

    # --- coverage ------------------------------------------------------------
    total = len(cfg.symbols)
    missing = list(getattr(provider, "missing_symbols", []))
    cached = total - len(missing)
    gate.hard("coverage > 0", cached > 0, f"{cached}/{total} members cached")
    gate.warn("coverage complete", not missing,
              f"{cached}/{total} ({cached / total:.0%})" if total else "no members")

    # --- benchmark -----------------------------------------------------------
    bench = result.benchmark_curve
    gate.hard("benchmark curve present, positive, finite",
              bench is not None and len(bench) > 1 and _finite_positive(bench),
              f"{len(bench)} points" if bench is not None else "missing")

    # --- sampled bar integrity ----------------------------------------------
    cached_syms = [s for s in cfg.symbols if s not in set(missing)][:sample]
    bad: list[str] = []
    if cached_syms:
        hist = provider.history(cached_syms, cfg.start, cfg.end, ("close",))  # type: ignore[attr-defined]
        for sym in cached_syms:
            try:
                closes = hist.xs(sym, level="symbol")["close"].dropna()
            except KeyError:
                bad.append(sym)
                continue
            if closes.empty or not bool((closes.to_numpy(dtype=float) > 0).all()):
                bad.append(sym)
    gate.hard(f"sampled bars valid (n={len(cached_syms)})", not bad,
              "all closes present & > 0" if not bad else f"suspect: {bad[:5]}")

    # --- equity curve --------------------------------------------------------
    eq = result.equity_curve
    gate.hard("equity curve finite & strictly positive",
              len(eq) > 0 and _finite_positive(eq),
              f"{len(eq)} days, final ${float(eq.iloc[-1]):,.0f}" if len(eq) else "empty")

    # --- metrics internal identity (metrics are a pure fn of trades+equity) --
    recomputed = compute_metrics(result.trades, result.equity_curve)
    gate.hard("metrics == recompute(trades, equity)",
              recomputed == result.metrics,
              "consistent" if recomputed == result.metrics
              else "reported metrics disagree with recomputation")

    m = result.metrics
    gate.hard("win rate in [0, 1]", 0.0 <= m.win_rate <= 1.0, f"{m.win_rate:.0%}")
    finite_metrics = all(
        math.isfinite(x) for x in (m.expectancy, m.avg_win_r, m.avg_loss_r, m.max_drawdown_pct)
    )
    gate.hard("summary metrics finite", finite_metrics)

    bad_r = [t.symbol for t in result.trades if not math.isfinite(t.r_multiple)]
    gate.hard("all trades have finite R", not bad_r,
              f"{len(result.trades)} trades" if not bad_r else f"non-finite: {bad_r[:5]}")

    gate.warn("statistically significant sample (>= 30 trades)",
              m.num_trades >= MIN_SIGNIFICANT_TRADES, f"{m.num_trades} trades")


def check_reproducible(cfg: RunConfig, provider: object,
                       first: BacktestResult, gate: Gate) -> None:
    second = run_from_config(cfg, provider)
    same_metrics = second.metrics == first.metrics
    same_equity = first.equity_curve.equals(second.equity_curve)
    gate.hard("reproducible: identical metrics on re-run", same_metrics)
    gate.hard("reproducible: identical equity curve on re-run", same_equity)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("config", nargs="?", default=DEFAULT_CONFIG,
                        help=f"run-config YAML (default: {DEFAULT_CONFIG})")
    parser.add_argument("--repro", action="store_true",
                        help="also assert a second identical run reproduces exactly (2nd backtest)")
    parser.add_argument("--sample", type=int, default=25,
                        help="how many cached symbols to spot-check for bar integrity (default: 25)")
    args = parser.parse_args()

    cfg = load_config(args.config)
    provider = build_provider(cfg)
    result = run_from_config(cfg, provider)

    gate = Gate()
    print(f"verify: {cfg.name}  {cfg.start}..{cfg.end}  strategy={cfg.strategy.name}\n")
    verify(cfg, provider, result, gate, args.sample)
    if args.repro:
        check_reproducible(cfg, provider, result, gate)

    gate.report()
    print("\n" + ("VERIFIED — all hard checks passed." if gate.ok
                  else "FAILED — one or more hard checks did not pass."))
    return 0 if gate.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
