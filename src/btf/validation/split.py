"""In-sample / out-of-sample split (M5, plan §6 — overfitting defense).

Tune parameters on the in-sample period only; the out-of-sample period is spent
*once* to confirm. If IS expectancy is positive but OOS collapses, the params
are fit to noise (expectancy-and-position-sizing warns exactly about this).

Both halves run standalone through the same engine: the strategy re-warms up
inside each half (its first ``warmup_bars`` produce no signals), so the OOS run
sees nothing from the IS period — no leakage, at the cost of a short blind
stretch at each half's start.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from btf.config.builder import build_provider, run_from_config
from btf.config.schema import RunConfig
from btf.data.provider import DataProvider
from btf.metrics.result import BacktestResult


@dataclass(frozen=True, slots=True)
class SplitResult:
    """Paired IS/OOS results for one config."""

    config: RunConfig
    oos_start: date
    in_sample: BacktestResult
    out_of_sample: BacktestResult


def run_oos_split(
    cfg: RunConfig,
    oos_start: date | None = None,
    provider: DataProvider | None = None,
) -> SplitResult:
    """Run ``cfg`` on [start, oos_start) and [oos_start, end] separately.

    ``oos_start`` defaults to ``cfg.validation.oos_start``. The provider (built
    once for the full period unless injected) is shared by both halves.
    """
    boundary = oos_start if oos_start is not None else cfg.validation.oos_start
    if boundary is None:
        raise ValueError("no oos_start given and none set in cfg.validation")
    if not (cfg.start < boundary <= cfg.end):
        raise ValueError(
            f"oos_start ({boundary}) must fall inside the period ({cfg.start} .. {cfg.end}]"
        )
    data = provider if provider is not None else build_provider(cfg)
    return SplitResult(
        config=cfg,
        oos_start=boundary,
        in_sample=run_from_config(cfg.with_period(cfg.start, boundary - timedelta(days=1)), data),
        out_of_sample=run_from_config(cfg.with_period(boundary, cfg.end), data),
    )
