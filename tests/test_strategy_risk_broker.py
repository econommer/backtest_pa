from btf.broker.broker import Broker
from btf.risk.sizer import PositionSizer
from btf.strategies.base import Strategy


def test_strategy_protocol_stub():
    class StubStrategy:
        name = "stub"
        warmup_bars = 0

        def on_bar(self, ctx):
            return []

    assert isinstance(StubStrategy(), Strategy)


def test_strategy_missing_attr_fails():
    class NoWarmup:
        name = "x"

        def on_bar(self, ctx):
            return []

    assert not isinstance(NoWarmup(), Strategy)


def test_position_sizer_protocol_stub():
    class StubSizer:
        def size(self, signals, ctx):
            return []

    assert isinstance(StubSizer(), PositionSizer)


def test_broker_protocol_stub():
    class StubBroker:
        def execute(self, orders, bars):
            return []

        def sweep_stops(self, positions, bars):
            return []

    assert isinstance(StubBroker(), Broker)


def test_broker_missing_method_fails():
    class NoSweep:
        def execute(self, orders, bars):
            return []

    assert not isinstance(NoSweep(), Broker)
