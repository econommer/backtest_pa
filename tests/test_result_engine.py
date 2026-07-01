from dataclasses import fields

import pandas as pd

from btf.engine.engine import Engine
from btf.metrics.result import BacktestResult, Metrics


def test_metrics_fields():
    assert {f.name for f in fields(Metrics)} == {
        "num_trades", "win_rate", "avg_win_r", "avg_loss_r", "expectancy",
        "profit_factor", "max_losing_streak", "max_drawdown_r",
        "max_drawdown_pct", "exposure",
    }


def test_backtest_result_fields_and_defaults():
    assert {f.name for f in fields(BacktestResult)} == {
        "config", "equity_curve", "metrics", "benchmark_curve",
        "trades", "regime_breakdown",
    }
    m = Metrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0.0)
    r = BacktestResult(config={}, equity_curve=pd.Series(dtype=float), metrics=m)
    assert r.benchmark_curve is None
    assert r.trades == [] and r.regime_breakdown == {}


def test_engine_protocol_stub():
    class StubEngine:
        def run(self, strategy, data, broker, sizer, config):
            return None

    assert isinstance(StubEngine(), Engine)
