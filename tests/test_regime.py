"""M3 — regime engine + benchmark comparison (design spec §6)."""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from btf.broker.simple_broker import SimpleBroker
from btf.context.context import Context
from btf.core import Regime, Signal
from btf.engine.basic_engine import BasicEngine
from btf.regime.classifier import RegimeClassifier, SmaRegimeClassifier
from btf.risk.fixed_risk_sizer import FixedRiskSizer
from btf.strategies.buy_and_hold import BuyAndHold
from tests.m1_fixtures import uptrend_provider_with_benchmark


def _series(values):
    dates = [date(2020, 1, d) for d in range(1, len(values) + 1)]
    return pd.Series([float(v) for v in values], index=pd.DatetimeIndex(dates))


# --- Classifier units --------------------------------------------------------

def test_classifier_is_protocol():
    assert isinstance(SmaRegimeClassifier(), RegimeClassifier)


def test_classifier_bull_bear_range_unknown():
    clf = SmaRegimeClassifier(window=3, slope_lookback=1)
    assert clf.classify(_series([1, 2]))[0] is Regime.UNKNOWN            # < window
    bull, trend = clf.classify(_series([10, 11, 12, 13, 14]))
    assert bull is Regime.BULL and trend > 0
    bear, trend = clf.classify(_series([14, 13, 12, 11, 10]))
    assert bear is Regime.BEAR and trend < 0
    # oscillate tightly around a level → close ≈ sma → RANGE
    assert clf.classify(_series([10, 10, 10, 10, 10]))[0] is Regime.RANGE


# --- No look-ahead for the regime --------------------------------------------

class SpyClassifier:
    """Wraps a real classifier and records the last timestamp of each history it sees."""

    def __init__(self) -> None:
        self.warmup_bars = 0
        self._inner = SmaRegimeClassifier(window=2, slope_lookback=1)
        self.seen_max_ts: list[date] = []

    def classify(self, index_history):
        if len(index_history):
            self.seen_max_ts.append(max(index_history.index).date())
        else:
            self.seen_max_ts.append(None)
        return self._inner.classify(index_history)


def test_regime_uses_only_history_up_to_as_of():
    prov = uptrend_provider_with_benchmark(days=8)
    spy = SpyClassifier()
    BasicEngine(classifier=spy).run(
        strategy=BuyAndHold(nominal_stop_pct=0.5),
        data=prov,
        broker=SimpleBroker(),
        sizer=FixedRiskSizer(risk_pct=0.02),
        config={"start": date(2020, 1, 1), "end": date(2020, 1, 8),
                "starting_cash": 100_000.0, "benchmark": "SPX"},
    )
    calendar = prov.trading_calendar(date(2020, 1, 1), date(2020, 1, 8))
    assert spy.seen_max_ts == calendar  # each day's regime saw benchmark bars up to exactly that day


# --- Engine feeds real regime + tags trades ----------------------------------

def _run_with_benchmark(days=8):
    prov = uptrend_provider_with_benchmark(days=days)
    return prov, BasicEngine(classifier=SmaRegimeClassifier(window=2, slope_lookback=1)).run(
        strategy=BuyAndHold(nominal_stop_pct=0.5),
        data=prov,
        broker=SimpleBroker(),
        sizer=FixedRiskSizer(risk_pct=0.02),
        config={"start": date(2020, 1, 1), "end": date(2020, 1, days),
                "starting_cash": 100_000.0, "benchmark": "SPX"},
    )


def test_context_regime_is_bull_after_warmup_and_trade_tagged():
    seen_regimes: list[Regime] = []

    class RegimeSpyStrategy:
        def __init__(self):
            self.name = "regime-spy"
            self.warmup_bars = 0
            self._inner = BuyAndHold(nominal_stop_pct=0.5)

        def on_bar(self, ctx: Context) -> list[Signal]:
            seen_regimes.append(ctx.market.regime)
            return self._inner.on_bar(ctx)

    prov = uptrend_provider_with_benchmark(days=8)
    result = BasicEngine(classifier=SmaRegimeClassifier(window=2, slope_lookback=1)).run(
        strategy=RegimeSpyStrategy(),
        data=prov,
        broker=SimpleBroker(),
        sizer=FixedRiskSizer(risk_pct=0.02),
        config={"start": date(2020, 1, 1), "end": date(2020, 1, 8),
                "starting_cash": 100_000.0, "benchmark": "SPX"},
    )
    assert Regime.BULL in seen_regimes                 # real regime fed into the context
    assert result.trades and result.trades[0].regime is Regime.BULL  # tagged at entry (day 2)


def test_benchmark_curve_normalised_to_starting_cash():
    _, result = _run_with_benchmark(days=8)
    bc = result.benchmark_curve
    assert bc is not None
    assert list(bc.index) == list(result.equity_curve.index)
    assert float(bc.iloc[0]) == pytest.approx(100_000.0)


def test_regime_breakdown_partitions_trades():
    _, result = _run_with_benchmark(days=8)
    assert result.regime_breakdown  # non-empty when a benchmark is configured
    total = sum(m.num_trades for m in result.regime_breakdown.values())
    assert total == len(result.trades)


# --- Backward compatibility (no benchmark) -----------------------------------

def test_no_benchmark_matches_m1_behaviour():
    from tests.m1_fixtures import uptrend_provider

    result = BasicEngine().run(
        strategy=BuyAndHold(nominal_stop_pct=0.5),
        data=uptrend_provider("AAA", days=6),
        broker=SimpleBroker(),
        sizer=FixedRiskSizer(risk_pct=0.02),
        config={"start": date(2020, 1, 1), "end": date(2020, 1, 6), "starting_cash": 100_000.0},
    )
    assert result.benchmark_curve is None
    assert result.regime_breakdown == {}
    assert result.trades and result.trades[0].regime is Regime.UNKNOWN
