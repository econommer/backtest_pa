#!/usr/bin/env python3
"""Fast, offline iteration on the M6 Phase-2 VCP run (base run only).

The full protocol (``run_config.py … --validate``) re-runs the backtest ~26×
(base + OOS split + 5 walk-forward windows + the sensitivity sweep). While the
survivorship-free Bloomberg snapshot is still filling in day by day, that is too
slow to re-run every time new bars land. This script does ONE base run on the
bars currently cached, prints coverage + the standard R-metrics, and (optionally)
writes a compact, data-driven HTML report — so the numbers can be watched as the
snapshot grows, without waiting on the validation suite.

It changes nothing about the engine or the strategy: same config, same provider,
same ``run_from_config`` as the real run — just the base leg, timed, plus a
coverage read-out. Reads only cached data (the Bloomberg provider never fetches).

Usage:

    python scripts/vcp_fast_m6.py                                  # phase-2 config
    python scripts/vcp_fast_m6.py config/vcp_phase2_bloomberg.yaml
    python scripts/vcp_fast_m6.py --html reports/vcp_fast.html     # + HTML report
    python scripts/vcp_fast_m6.py --top 40                         # more trades listed
"""
from __future__ import annotations

import argparse
import html
import sys
import time
from pathlib import Path

import pandas as pd

# Never let a stray non-cp1252 glyph crash a long run on a Windows console.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

from btf.config import RunConfig, build_provider, load_config, run_from_config
from btf.data.provider import DataProvider
from btf.metrics.result import BacktestResult
from btf.validation import (
    SMALL_SAMPLE_LEGEND,
    TABLE_HEADER,
    metrics_row,
    result_row,
)

DEFAULT_CONFIG = "config/vcp_phase2_bloomberg.yaml"


def _coverage(cfg: RunConfig, provider: DataProvider) -> tuple[int, int, int]:
    """(cached, total, missing) member counts for the run's universe."""
    total = len(cfg.symbols)
    missing = len(getattr(provider, "missing_symbols", []))
    return total - missing, total, missing


def _return_pct(curve: pd.Series | None) -> float | None:
    if curve is None or len(curve) == 0:
        return None
    first = float(curve.iloc[0])
    if first == 0:
        return None
    return float(curve.iloc[-1]) / first - 1.0


def print_report(
    cfg: RunConfig,
    provider: DataProvider,
    result: BacktestResult,
    timings: dict[str, float],
    top: int,
) -> None:
    cached, total, missing = _coverage(cfg, provider)
    pct = cached / total if total else 0.0
    print(
        f"{cfg.name}  {cfg.start}..{cfg.end}  {total} members  "
        f"strategy={cfg.strategy.name}  risk={cfg.risk.risk_pct:.1%}/trade"
    )
    print(
        f"coverage: {cached}/{total} members have cached bars ({pct:.0%})"
        + (f"  |  {missing} missing (partial snapshot)" if missing else "  |  complete")
    )
    print()
    print(TABLE_HEADER)
    print("-" * len(TABLE_HEADER))
    print(result_row("base run", result))

    strat_ret = _return_pct(result.equity_curve)
    bench_ret = _return_pct(result.benchmark_curve)
    start_cash = cfg.risk.starting_cash
    final_eq = float(result.equity_curve.iloc[-1]) if len(result.equity_curve) else start_cash
    line = f"\nfinal equity: ${final_eq:,.0f}  (start ${start_cash:,.0f}"
    if strat_ret is not None:
        line += f", {strat_ret:+.1%}"
    line += ")"
    if bench_ret is not None:
        line += f"   benchmark {cfg.data.benchmark or 'SPX'}: {bench_ret:+.1%}"
    print(line)

    if result.regime_breakdown:
        print("\nby regime:")
        print(TABLE_HEADER)
        print("-" * len(TABLE_HEADER))
        for regime, m in result.regime_breakdown.items():
            print(metrics_row(regime.value, m))

    print(SMALL_SAMPLE_LEGEND)

    if result.trades and top > 0:
        shown = sorted(result.trades, key=lambda t: t.exit_ts)[-top:]
        print(f"\nlast {len(shown)} of {len(result.trades)} trades (R):")
        for t in shown:
            print(
                f"  {t.symbol:<10} {t.entry_ts}..{t.exit_ts}  "
                f"{t.r_multiple:>6.2f}R  {t.regime.value:<7} {t.reason_exit}"
            )

    total_s = timings.get("import", 0) + timings["load"] + timings["run"]
    print(
        f"\ntiming: load {timings['load']:.1f}s + run {timings['run']:.1f}s"
        + (f" (+ import {timings['import']:.1f}s)" if "import" in timings else "")
        + f" = {total_s:.1f}s  [base run only; --validate would be ~26×]"
    )
    if missing:
        print(
            "\n[!] TENTATIVE: partial snapshot. Coverage grows as "
            "fetch_bloomberg_snapshot.py --stage bars runs on subsequent days."
        )


# --------------------------------------------------------------------------- #
# Optional self-contained HTML report (data-driven; no external assets)        #
# --------------------------------------------------------------------------- #

def _sparkline(curve: pd.Series, color: str, width: int = 720, height: int = 200,
               base: tuple[float, float] | None = None) -> str:
    """An SVG polyline for an equity/price series, normalised to its own start."""
    if curve is None or len(curve) < 2:
        return ""
    s = curve.astype(float)
    first = float(s.iloc[0]) or 1.0
    norm = s / first * 100.0
    if base is not None:
        lo, hi = base
    else:
        lo, hi = float(norm.min()), float(norm.max())
    span = (hi - lo) or 1.0
    n = len(norm)
    step = max(1, n // 600)  # cap points for a light SVG
    pts = []
    for i in range(0, n, step):
        x = i / (n - 1) * width
        y = height - (float(norm.iloc[i]) - lo) / span * height
        pts.append(f"{x:.1f},{y:.1f}")
    return f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{" ".join(pts)}"/>'


def _card(value: str, label: str, cls: str = "") -> str:
    return f'<div class="card"><div class="v {cls}">{value}</div><div class="l">{label}</div></div>'


def write_html(path: Path, cfg: RunConfig, provider: DataProvider,
               result: BacktestResult, top: int) -> None:
    cached, total, missing = _coverage(cfg, provider)
    m = result.metrics
    strat_ret = _return_pct(result.equity_curve)
    bench_ret = _return_pct(result.benchmark_curve)

    def pc(x: float | None) -> str:
        return "—" if x is None else f"{x:+.1%}"

    def cls(x: float | None) -> str:
        return "" if x is None else ("pos" if x >= 0 else "neg")

    # normalise both curves to a shared y-range so they overlay sensibly
    curves = [c for c in (result.equity_curve, result.benchmark_curve) if c is not None and len(c) > 1]
    norm_all = [c.astype(float) / float(c.iloc[0] or 1.0) * 100.0 for c in curves]
    lo = min(float(n.min()) for n in norm_all) if norm_all else 0.0
    hi = max(float(n.max()) for n in norm_all) if norm_all else 100.0
    eq_line = _sparkline(result.equity_curve, "#4fc3f7", base=(lo, hi))
    bench_line = _sparkline(result.benchmark_curve, "#8a949e", base=(lo, hi)) if result.benchmark_curve is not None else ""

    pf = "inf" if m.profit_factor == float("inf") else f"{m.profit_factor:.2f}"
    banner = ""
    if missing:
        banner = (
            f'<div class="banner"><b>Tentative</b> — partial snapshot: '
            f'{cached}/{total} members ({cached / total:.0%}) have cached bars. '
            f'{missing} still missing; metrics will shift as the fetch completes.</div>'
        )
    rows = []
    for t in sorted(result.trades, key=lambda t: t.exit_ts)[-top:][::-1]:
        r_cls = "pos" if t.r_multiple >= 0 else "neg"
        rows.append(
            f"<tr><td>{html.escape(t.symbol)}</td><td>{t.entry_ts}</td><td>{t.exit_ts}</td>"
            f'<td class="{r_cls}">{t.r_multiple:.2f}</td><td>{t.regime.value}</td>'
            f"<td>{html.escape(t.reason_exit)}</td></tr>"
        )
    trades_table = "".join(rows) or '<tr><td colspan="6">no closed trades</td></tr>'

    doc = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>VCP Phase-2 (M6) — Fast Report</title>
<style>
:root{{--bg:#0f1419;--card:#1a2129;--ink:#e6e8ea;--mut:#8a949e;--acc:#4fc3f7;--pos:#66bb6a;--neg:#ef5350;--warn:#ffb74d;--line:#2a333d}}
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:var(--bg);color:var(--ink);font:15px/1.55 -apple-system,'Segoe UI',Roboto,sans-serif;padding:28px 4vw 60px}}
h1{{font-size:23px}} h2{{font-size:16px;margin:30px 0 10px;color:var(--acc)}}
.sub{{color:var(--mut);font-size:13px;margin-bottom:6px}}
.banner{{background:#3a2b12;border:1px solid var(--warn);border-radius:10px;padding:12px 16px;margin:16px 0;font-size:14px}}
.banner b{{color:var(--warn)}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin:16px 0}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px 14px}}
.card .v{{font-size:21px;font-weight:700}} .card .l{{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.5px}}
.pos{{color:var(--pos)}} .neg{{color:var(--neg)}}
.chartbox{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin:10px 0;overflow-x:auto}}
.legend{{font-size:12px;color:var(--mut);margin-top:6px}}
.legend .k{{display:inline-block;width:22px;height:0;border-top:2px solid;vertical-align:middle;margin-right:5px}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}}
th,td{{padding:7px 10px;text-align:right;border-bottom:1px solid var(--line)}}
th{{color:var(--mut);font-weight:600}} th:first-child,td:first-child{{text-align:left}}
td:last-child,th:last-child{{text-align:left}} tr:hover td{{background:#212a34}}
svg{{display:block;width:100%;max-width:720px}}
</style></head><body>
<h1>VCP Breakout — Phase-2 (M6) Fast Report</h1>
<div class="sub">S&amp;P 500 point-in-time universe (incl. delisted) · Bloomberg daily bars ·
{cfg.start} → {cfg.end} · engine: btf · base run only (no validation suite)</div>
{banner}
<div class="cards">
{_card(str(m.num_trades), 'Trades')}
{_card(f'{m.win_rate:.0%}', 'Win rate')}
{_card(f'{m.expectancy:.2f}R', 'Expectancy', 'pos' if m.expectancy >= 0 else 'neg')}
{_card(pf, 'Profit factor')}
{_card(f'{m.avg_win_r:.2f}R', 'Avg win')}
{_card(f'{m.avg_loss_r:.2f}R', 'Avg loss')}
{_card(f'{m.max_drawdown_pct:.0%}', 'Max drawdown')}
{_card(pc(strat_ret), 'Strategy return', cls(strat_ret))}
{_card(pc(bench_ret), f"{cfg.data.benchmark or 'SPX'} return", cls(bench_ret))}
{_card(f'{cached}/{total}', 'Coverage')}
</div>
<h2>Equity curve (strategy vs benchmark, start = 100)</h2>
<div class="chartbox">
<svg viewBox="0 0 720 200" preserveAspectRatio="none">{bench_line}{eq_line}</svg>
<div class="legend"><span class="k" style="border-color:#4fc3f7"></span>strategy
&nbsp;&nbsp;<span class="k" style="border-color:#8a949e"></span>{cfg.data.benchmark or 'SPX'}</div>
</div>
<h2>Last {min(top, len(result.trades))} trades</h2>
<table><thead><tr><th>Symbol</th><th>Entry</th><th>Exit</th><th>R</th><th>Regime</th><th>Exit reason</th></tr></thead>
<tbody>{trades_table}</tbody></table>
<p class="sub" style="margin-top:18px">Generated by scripts/vcp_fast_m6.py — same config &amp; engine as
run_config.py, base leg only. Not financial advice; a study artifact.</p>
</body></html>"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc, encoding="utf-8")
    print(f"\nHTML report written: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("config", nargs="?", default=DEFAULT_CONFIG,
                        help=f"run-config YAML (default: {DEFAULT_CONFIG})")
    parser.add_argument("--html", metavar="PATH",
                        help="also write a self-contained HTML report to PATH")
    parser.add_argument("--top", type=int, default=20,
                        help="how many recent trades to list (default: 20)")
    args = parser.parse_args()

    timings: dict[str, float] = {}
    t = time.time()
    cfg = load_config(args.config)
    provider = build_provider(cfg)
    timings["load"] = time.time() - t

    t = time.time()
    result = run_from_config(cfg, provider)
    timings["run"] = time.time() - t

    print_report(cfg, provider, result, timings, args.top)
    if args.html:
        write_html(Path(args.html), cfg, provider, result, args.top)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
