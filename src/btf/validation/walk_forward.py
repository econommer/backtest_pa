"""Walk-forward consistency check (M5, plan §6 — overfitting defense).

Splits the period into N contiguous, non-overlapping calendar windows and runs
the *same fixed params* on each, standalone. An aggregate expectancy that hides
one lucky year fails here: the edge has to show up window after window.

(Per-window parameter re-optimization — classic walk-forward *optimization* —
is a deliberate non-goal for v1: params are fixed a priori from the brain's
rules, so every window is genuinely out-of-sample for them.)

Each window re-warms up internally (first ``warmup_bars`` are signal-blind), so
windows must be comfortably longer than the strategy's warmup — for VCP
(~170 bars ≈ 8 months) use windows of a year or more; a window with zero trades
in the report is the symptom of cutting this too fine.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from btf.config.builder import build_provider, run_from_config
from btf.config.schema import RunConfig
from btf.data.provider import DataProvider
from btf.metrics.result import BacktestResult


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    """One window's period and its standalone result."""

    start: date
    end: date
    result: BacktestResult


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    """All windows for one config, in chronological order."""

    config: RunConfig
    windows: tuple[WalkForwardWindow, ...]


def run_walk_forward(
    cfg: RunConfig,
    n_windows: int | None = None,
    provider: DataProvider | None = None,
) -> WalkForwardResult:
    """Run ``cfg`` over N equal contiguous calendar windows.

    ``n_windows`` defaults to ``cfg.validation.walk_forward_windows``. The
    provider (built once for the full period unless injected) is shared by all
    windows.
    """
    n = n_windows if n_windows is not None else cfg.validation.walk_forward_windows
    if n is None:
        raise ValueError("no n_windows given and none set in cfg.validation")
    if n < 2:
        raise ValueError(f"walk-forward needs >= 2 windows, got {n}")
    total_days = (cfg.end - cfg.start).days
    if total_days < n:
        raise ValueError(f"period too short to split into {n} windows")

    data = provider if provider is not None else build_provider(cfg)
    windows: list[WalkForwardWindow] = []
    for i in range(n):
        w_start = cfg.start + timedelta(days=round(i * total_days / n))
        # Last window ends exactly at cfg.end; others stop the day before the next starts.
        w_end = (
            cfg.end
            if i == n - 1
            else cfg.start + timedelta(days=round((i + 1) * total_days / n) - 1)
        )
        result = run_from_config(cfg.with_period(w_start, w_end), data)
        windows.append(WalkForwardWindow(start=w_start, end=w_end, result=result))
    return WalkForwardResult(config=cfg, windows=tuple(windows))
