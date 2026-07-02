"""``RunConfig`` -> engine parts -> ``BacktestResult`` (M5).

The registries are the only place a config string meets a concrete class;
strategies and the engine stay ignorant of both (Strategy ⟂ Engine, plan §0).
Every run — baseline or validation sub-run — goes through ``run_from_config``,
so bias defenses inherit the same look-ahead firewall and cost model.

A fresh strategy instance is built per run: strategies may hold state (e.g.
``BuyAndHold._entered``), so instances must never be shared across runs.

``provider`` is an injectable seam: validation sweeps build one provider for
the full baseline period and reuse it for every sub-period run (providers slice
``history(start, end)`` inclusively), and tests inject ``InMemoryDataProvider``
to stay offline.
"""
from __future__ import annotations

from typing import Callable

from btf.broker.simple_broker import SimpleBroker
from btf.config.schema import RunConfig
from btf.data.provider import DataProvider
from btf.engine.basic_engine import BasicEngine
from btf.metrics.result import BacktestResult
from btf.risk.fixed_risk_sizer import FixedRiskSizer
from btf.strategies.base import Strategy
from btf.strategies.buy_and_hold import BuyAndHold
from btf.strategies.vcp import VcpStrategy

STRATEGIES: dict[str, Callable[..., Strategy]] = {
    "buy_and_hold": BuyAndHold,
    "vcp": VcpStrategy,
}


def _yfinance_provider(cfg: RunConfig) -> DataProvider:
    from btf.data.yfinance_provider import YFinanceDataProvider

    return YFinanceDataProvider(
        list(cfg.symbols), cfg.start, cfg.end,
        cache_dir=cfg.data.cache_dir, benchmark_symbol=cfg.data.benchmark,
    )


def _stooq_provider(cfg: RunConfig) -> DataProvider:
    from btf.data.stooq_provider import StooqDataProvider

    return StooqDataProvider(
        list(cfg.symbols), cfg.start, cfg.end,
        cache_dir=cfg.data.cache_dir, benchmark_symbol=cfg.data.benchmark,
    )


PROVIDERS: dict[str, Callable[[RunConfig], DataProvider]] = {
    "yfinance": _yfinance_provider,
    "stooq": _stooq_provider,
}


def build_strategy(cfg: RunConfig) -> Strategy:
    """A fresh strategy instance with the config's params applied."""
    factory = STRATEGIES.get(cfg.strategy.name)
    if factory is None:
        raise ValueError(
            f"unknown strategy {cfg.strategy.name!r} (known: {sorted(STRATEGIES)})"
        )
    try:
        return factory(**dict(cfg.strategy.params))
    except TypeError as exc:
        raise ValueError(
            f"bad params for strategy {cfg.strategy.name!r}: {exc}"
        ) from exc


def build_provider(cfg: RunConfig) -> DataProvider:
    """The config's DataProvider, covering the config's full period."""
    factory = PROVIDERS.get(cfg.data.source)
    if factory is None:
        raise ValueError(
            f"unknown data source {cfg.data.source!r} (known: {sorted(PROVIDERS)})"
        )
    return factory(cfg)


def run_from_config(cfg: RunConfig, provider: DataProvider | None = None) -> BacktestResult:
    """Run one backtest fully defined by ``cfg`` (same config ⇒ same result).

    Pass ``provider`` to reuse one data snapshot across derived runs (validation
    windows/sweeps) or to inject a fake in tests; it must cover ``cfg``'s period.
    """
    return BasicEngine().run(
        strategy=build_strategy(cfg),
        data=provider if provider is not None else build_provider(cfg),
        broker=SimpleBroker(
            commission_per_share=cfg.costs.commission_per_share,
            slippage_pct=cfg.costs.slippage_pct,
        ),
        sizer=FixedRiskSizer(risk_pct=cfg.risk.risk_pct),
        config=cfg.engine_config(),
    )
