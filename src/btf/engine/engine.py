"""Generic event-driven engine interface — knows nothing about VCP.

Advances the clock bar-by-bar: builds a Context (data <= today), calls the
strategy for Signals, sizes them via PositionSizer, simulates fills via Broker,
updates the portfolio, and returns a BacktestResult (BACKTESTING_PLAN.md §2.2).
"""
from __future__ import annotations

from typing import Mapping, Protocol, runtime_checkable

from btf.broker.broker import Broker
from btf.data.provider import DataProvider
from btf.metrics.result import BacktestResult
from btf.risk.sizer import PositionSizer
from btf.strategies.base import Strategy


@runtime_checkable
class Engine(Protocol):
    """Orchestrates one backtest run over a strategy, data, broker, and sizer."""

    def run(
        self,
        strategy: Strategy,
        data: DataProvider,
        broker: Broker,
        sizer: PositionSizer,
        config: Mapping,
    ) -> BacktestResult:
        """Run the full backtest and return its result. Enforces no look-ahead."""
        ...
