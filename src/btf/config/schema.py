"""Run-configuration schema — one config = one fully-defined, reproducible run (M5).

Core principle 5 (BACKTESTING_PLAN.md §0): a run is fully defined by a config
(universe / period / params / cost assumptions); the same config produces the
same result. M5's bias defenses build directly on this: an out-of-sample split,
a walk-forward window, or a sensitivity sweep point is just a *derived*
``RunConfig`` — same engine, same look-ahead firewall, different period/params.

Frozen dataclasses, data only. ``with_period`` / ``with_strategy_params`` return
modified copies so validation sweeps can never mutate the baseline config.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from typing import Mapping


@dataclass(frozen=True, slots=True)
class DataConfig:
    """Which DataProvider to build and how (vendor stays behind the interface)."""

    source: str = "yfinance"  # registry key — see btf.config.builder.PROVIDERS
    cache_dir: str = "data_cache"
    benchmark: str | None = "SPY"


@dataclass(frozen=True, slots=True)
class CostsConfig:
    """Realistic-costs assumptions (plan §6: no perfect fills)."""

    commission_per_share: float = 0.005
    slippage_pct: float = 0.0005


@dataclass(frozen=True, slots=True)
class RiskConfig:
    """R-based sizing inputs (expectancy-and-position-sizing)."""

    risk_pct: float = 0.01
    starting_cash: float = 100_000.0


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    """Strategy registry key + constructor params (kept vendor/engine-agnostic)."""

    name: str
    params: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ValidationConfig:
    """The run's bias-defense protocol (M5, plan §6). Every part is optional.

    - ``oos_start``: first day of the out-of-sample period; tune on data before
      it, confirm once on data from it.
    - ``walk_forward_windows``: split the period into N contiguous windows and
      require the edge to hold across them, not just in aggregate.
    - ``sensitivity``: strategy param -> list of values; one-at-a-time sweeps
      around the baseline. A cliff next to the chosen value = overfit.
    """

    oos_start: date | None = None
    walk_forward_windows: int | None = None
    sensitivity: Mapping[str, tuple[object, ...]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RunConfig:
    """Everything needed to reproduce one backtest run."""

    name: str
    symbols: tuple[str, ...]
    start: date
    end: date
    strategy: StrategyConfig
    data: DataConfig = field(default_factory=DataConfig)
    costs: CostsConfig = field(default_factory=CostsConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)

    def with_period(self, start: date, end: date) -> "RunConfig":
        """Copy with a different backtest period (OOS split / walk-forward windows)."""
        return replace(self, start=start, end=end)

    def with_strategy_params(self, **params: object) -> "RunConfig":
        """Copy with strategy params merged over the current ones (sweep points)."""
        merged: dict[str, object] = {**dict(self.strategy.params), **params}
        return replace(self, strategy=replace(self.strategy, params=merged))

    def engine_config(self) -> dict[str, object]:
        """The Mapping handed to ``Engine.run`` (and echoed into BacktestResult).

        Includes the run name and strategy spec beyond what the engine reads, so
        a stored result is self-describing.
        """
        return {
            "run_name": self.name,
            "start": self.start,
            "end": self.end,
            "starting_cash": self.risk.starting_cash,
            "symbols": list(self.symbols),
            "benchmark": self.data.benchmark,
            "strategy": self.strategy.name,
            "strategy_params": dict(self.strategy.params),
        }
