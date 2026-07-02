"""One-at-a-time parameter-sensitivity sweep (M5, plan §6 — overfitting defense).

For each param in the grid, vary *only that param* around the baseline config
and rerun. A robust edge degrades gently as a param moves; a sharp cliff right
next to the chosen value means the number was fit to noise (plan §5: "every
parameter is config-adjustable for sensitivity analysis — but watch out for
overfitting").

Sweep points that equal the baseline's effective value (explicit param or the
strategy constructor's default) reuse the baseline result instead of rerunning,
and are flagged ``is_baseline`` so reports can mark the anchor row.
"""
from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Mapping

from btf.config.builder import STRATEGIES, build_provider, run_from_config
from btf.config.schema import RunConfig
from btf.data.provider import DataProvider
from btf.metrics.result import BacktestResult


@dataclass(frozen=True, slots=True)
class SweepPoint:
    """One (param, value) run of the sweep."""

    param: str
    value: object
    is_baseline: bool
    result: BacktestResult


@dataclass(frozen=True, slots=True)
class SensitivityResult:
    """Baseline plus every sweep point, grouped by insertion order of the grid."""

    config: RunConfig
    baseline: BacktestResult
    points: tuple[SweepPoint, ...]


def run_sensitivity(
    cfg: RunConfig,
    grid: Mapping[str, tuple[object, ...]] | None = None,
    provider: DataProvider | None = None,
) -> SensitivityResult:
    """Run the baseline once, then one run per off-baseline (param, value) point.

    ``grid`` defaults to ``cfg.validation.sensitivity``. The provider (built
    once for the full period unless injected) is shared by all runs.
    """
    sweep = grid if grid is not None else cfg.validation.sensitivity
    if not sweep:
        raise ValueError("no sensitivity grid given and none set in cfg.validation")
    unknown = [p for p in sweep if p not in _strategy_param_names(cfg)]
    if unknown:
        raise ValueError(
            f"sensitivity params not accepted by strategy {cfg.strategy.name!r}: {unknown}"
        )

    data = provider if provider is not None else build_provider(cfg)
    baseline = run_from_config(cfg, data)
    baseline_values = _effective_params(cfg)

    points: list[SweepPoint] = []
    for param, values in sweep.items():
        for value in values:
            if value == baseline_values.get(param):
                points.append(SweepPoint(param, value, is_baseline=True, result=baseline))
                continue
            result = run_from_config(cfg.with_strategy_params(**{param: value}), data)
            points.append(SweepPoint(param, value, is_baseline=False, result=result))
    return SensitivityResult(config=cfg, baseline=baseline, points=tuple(points))


def _strategy_param_names(cfg: RunConfig) -> set[str]:
    factory = STRATEGIES.get(cfg.strategy.name)
    if factory is None:
        raise ValueError(f"unknown strategy {cfg.strategy.name!r} (known: {sorted(STRATEGIES)})")
    return set(inspect.signature(factory).parameters)


def _effective_params(cfg: RunConfig) -> dict[str, object]:
    """Explicit config params merged over the strategy constructor's defaults."""
    factory = STRATEGIES[cfg.strategy.name]
    defaults = {
        name: p.default
        for name, p in inspect.signature(factory).parameters.items()
        if p.default is not inspect.Parameter.empty
    }
    return {**defaults, **dict(cfg.strategy.params)}
