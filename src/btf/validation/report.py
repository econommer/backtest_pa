"""Plain-text reports for the M5 bias defenses.

Every table carries the brain's small-sample rule (expectancy-and-position-
sizing): metrics from fewer than ``MIN_SIGNIFICANT_TRADES`` trades are marked
``!`` and must be read as anecdote, not evidence. Formatting lives here (not in
scripts) so it is unit-testable; output pastes into the vcp-breakout
backtest-notes template.
"""
from __future__ import annotations

from datetime import timedelta

from btf.metrics.result import BacktestResult, Metrics
from btf.validation.sensitivity import SensitivityResult
from btf.validation.split import SplitResult
from btf.validation.walk_forward import WalkForwardResult

#: Below this trade count, treat metrics as not statistically meaningful.
MIN_SIGNIFICANT_TRADES = 30

TABLE_HEADER = (
    f"{'':<24} {'Trades':>6} {'Win%':>6} {'AvgW':>6} {'AvgL':>6} "
    f"{'Expect':>7} {'PF':>6} {'MaxDD':>6}"
)
SMALL_SAMPLE_LEGEND = (
    f"[!] fewer than {MIN_SIGNIFICANT_TRADES} trades — not statistically significant"
)


def metrics_row(label: str, m: Metrics) -> str:
    """One fixed-width table row; small samples get a trailing ``!``."""
    flag = " !" if m.num_trades < MIN_SIGNIFICANT_TRADES else ""
    pf = f"{m.profit_factor:>6.2f}" if m.profit_factor != float("inf") else f"{'inf':>6}"
    return (
        f"{label:<24} {m.num_trades:>6} {m.win_rate:>5.0%} "
        f"{m.avg_win_r:>5.2f}R {m.avg_loss_r:>5.2f}R {m.expectancy:>6.2f}R "
        f"{pf} {m.max_drawdown_pct:>5.0%}{flag}"
    )


def result_row(label: str, r: BacktestResult) -> str:
    return metrics_row(label, r.metrics)


def split_report(s: SplitResult) -> str:
    """IS vs OOS side by side — the OOS row is the one that counts."""
    cfg = s.config
    lines = [
        f"In-sample / out-of-sample split — {cfg.name}  (OOS from {s.oos_start})",
        TABLE_HEADER,
        "-" * len(TABLE_HEADER),
        result_row(f"IS  {cfg.start}..{s.oos_start - timedelta(days=1)}", s.in_sample),
        result_row(f"OOS {s.oos_start}..{cfg.end}", s.out_of_sample),
        "-" * len(TABLE_HEADER),
        SMALL_SAMPLE_LEGEND,
        "Read: tune on IS only; OOS is spent once. IS good + OOS flat/negative = overfit.",
    ]
    return "\n".join(lines)


def walk_forward_report(w: WalkForwardResult) -> str:
    """Per-window rows — the edge must hold across windows, not just in aggregate."""
    positive = sum(1 for win in w.windows if win.result.metrics.expectancy > 0)
    lines = [
        f"Walk-forward — {w.config.name}  ({len(w.windows)} windows, fixed params)",
        TABLE_HEADER,
        "-" * len(TABLE_HEADER),
        *[result_row(f"{win.start}..{win.end}", win.result) for win in w.windows],
        "-" * len(TABLE_HEADER),
        f"Windows with positive expectancy: {positive}/{len(w.windows)}",
        SMALL_SAMPLE_LEGEND,
        "Read: a real edge repeats across windows; one lucky window carrying the total = fragile.",
    ]
    return "\n".join(lines)


def sensitivity_report(s: SensitivityResult) -> str:
    """One block per swept param; ``*`` marks the baseline value's row."""
    lines = [f"Parameter sensitivity — {s.config.name}  (one param varied at a time)"]
    params = list(dict.fromkeys(p.param for p in s.points))
    for param in params:
        lines += ["", f"{param}:", TABLE_HEADER, "-" * len(TABLE_HEADER)]
        for point in s.points:
            if point.param != param:
                continue
            mark = " *" if point.is_baseline else ""
            lines.append(result_row(f"  {param}={point.value}{mark}", point.result))
    lines += [
        "",
        "* baseline value",
        SMALL_SAMPLE_LEGEND,
        "Read: expectancy should degrade gently as a param moves; a cliff next to the "
        "baseline means the value was fit to noise.",
    ]
    return "\n".join(lines)
