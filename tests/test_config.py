"""M5 config layer: YAML/dict -> RunConfig -> engine run (core principle 5).

Invariants:
- a valid document round-trips into a fully-typed RunConfig (dates coerced);
- malformed configs fail loudly (unknown keys, missing keys, bad values);
- derived configs (with_period / with_strategy_params) are copies, never mutations;
- run_from_config drives the real engine and is deterministic: same config +
  same data => identical equity curve and trades (reproducibility).

All offline: engine runs inject InMemoryDataProvider.
"""
from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from btf.config import (
    ConfigError,
    RunConfig,
    StrategyConfig,
    build_strategy,
    config_from_dict,
    load_config,
    run_from_config,
)
from btf.data.memory_provider import InMemoryDataProvider
from btf.strategies.vcp import VcpStrategy

# ---- fixtures -----------------------------------------------------------------

MINIMAL = {
    "name": "test-run",
    "period": {"start": date(2020, 1, 1), "end": date(2020, 12, 31)},
    "universe": {"symbols": ["AAA", "BBB"]},
    "strategy": {"name": "buy_and_hold"},
}


def minimal_dict() -> dict:
    """Fresh deep-ish copy so tests can mutate freely."""
    return {
        "name": MINIMAL["name"],
        "period": dict(MINIMAL["period"]),  # type: ignore[arg-type]
        "universe": {"symbols": list(MINIMAL["universe"]["symbols"])},  # type: ignore[index]
        "strategy": dict(MINIMAL["strategy"]),  # type: ignore[arg-type]
    }


def make_provider(n_days: int = 60) -> InMemoryDataProvider:
    """Two gently up-trending symbols + a benchmark, business days from 2020-01-01."""
    idx = pd.bdate_range("2020-01-01", periods=n_days)
    frames = {}
    for sym, base in [("AAA", 50.0), ("BBB", 100.0)]:
        closes = [base + i * 0.5 for i in range(n_days)]
        frames[sym] = pd.DataFrame(
            {
                "open": closes,
                "high": [c + 1 for c in closes],
                "low": [c - 1 for c in closes],
                "close": closes,
                "volume": [1000.0] * n_days,
            },
            index=idx,
        )
    bench = pd.Series([300.0 + i for i in range(n_days)], index=idx)
    return InMemoryDataProvider(frames, benchmark=bench)


def engine_cfg(**overrides) -> RunConfig:
    d = minimal_dict()
    d["period"] = {"start": date(2020, 1, 1), "end": date(2020, 3, 24)}
    d["data"] = {"benchmark": "SPY"}
    cfg = config_from_dict(d)
    return cfg if not overrides else cfg.with_period(
        overrides.get("start", cfg.start), overrides.get("end", cfg.end)
    )


# ---- parsing ------------------------------------------------------------------

def test_minimal_dict_parses_with_defaults():
    cfg = config_from_dict(minimal_dict())
    assert cfg.name == "test-run"
    assert cfg.symbols == ("AAA", "BBB")
    assert cfg.start == date(2020, 1, 1) and cfg.end == date(2020, 12, 31)
    assert cfg.strategy.name == "buy_and_hold" and cfg.strategy.params == {}
    # defaults filled in
    assert cfg.data.source == "yfinance"
    assert cfg.costs.commission_per_share == 0.005
    assert cfg.risk.starting_cash == 100_000.0
    assert cfg.validation.oos_start is None


def test_iso_string_dates_coerced():
    d = minimal_dict()
    d["period"] = {"start": "2020-01-01", "end": "2020-12-31"}
    cfg = config_from_dict(d)
    assert cfg.start == date(2020, 1, 1) and cfg.end == date(2020, 12, 31)


def test_full_document_parses():
    d = minimal_dict()
    d["data"] = {"source": "stooq", "cache_dir": "snap", "benchmark": "SPY"}
    d["costs"] = {"commission_per_share": 0.01, "slippage_pct": 0.001}
    d["risk"] = {"risk_pct": 0.02, "starting_cash": 50_000}
    d["strategy"] = {"name": "vcp", "params": {"tight_window": 8}}
    d["validation"] = {
        "oos_start": date(2020, 7, 1),
        "walk_forward_windows": 3,
        "sensitivity": {"tight_window": [6, 8, 10]},
    }
    cfg = config_from_dict(d)
    assert cfg.data.source == "stooq" and cfg.data.cache_dir == "snap"
    assert cfg.costs.slippage_pct == 0.001
    assert cfg.risk.risk_pct == 0.02
    assert cfg.strategy.params == {"tight_window": 8}
    assert cfg.validation.oos_start == date(2020, 7, 1)
    assert cfg.validation.walk_forward_windows == 3
    assert cfg.validation.sensitivity == {"tight_window": (6, 8, 10)}


@pytest.mark.parametrize(
    "mutate, match",
    [
        (lambda d: d.pop("name"), "name"),
        (lambda d: d.pop("strategy"), "strategy"),
        (lambda d: d.update(typo=1), "unknown key"),
        (lambda d: d["period"].update(begin="2020-01-01"), "unknown key"),
        (lambda d: d["universe"].update(symbols=[]), "non-empty"),
        (lambda d: d["period"].update(end=date(2019, 1, 1)), "after"),
        (lambda d: d["period"].update(start="not-a-date"), "ISO date"),
        (lambda d: d.update(validation={"oos_start": date(2030, 1, 1)}), "inside the period"),
        (lambda d: d.update(validation={"walk_forward_windows": 1}), ">= 2"),
        (lambda d: d.update(validation={"sensitivity": {"tight_window": []}}), "non-empty"),
    ],
)
def test_malformed_configs_fail_loudly(mutate, match):
    d = minimal_dict()
    mutate(d)
    with pytest.raises(ConfigError, match=match):
        config_from_dict(d)


def test_load_config_yaml_roundtrip(tmp_path):
    yaml_text = """
name: yaml-run
period: {start: 2020-01-01, end: 2020-12-31}
universe:
  symbols: [AAA, BBB]
strategy:
  name: vcp
  params: {tight_window: 8}
validation:
  sensitivity:
    trail_ma: [20, 50]
"""
    path = tmp_path / "run.yaml"
    path.write_text(yaml_text)
    cfg = load_config(path)
    assert cfg.name == "yaml-run"
    assert cfg.start == date(2020, 1, 1)  # PyYAML parses bare ISO dates natively
    assert cfg.strategy.params == {"tight_window": 8}
    assert cfg.validation.sensitivity == {"trail_ma": (20, 50)}


def test_repo_example_config_loads():
    cfg = load_config("config/vcp_phase1.yaml")
    assert cfg.strategy.name == "vcp"
    assert cfg.validation.oos_start is not None
    assert cfg.validation.walk_forward_windows is not None
    assert cfg.validation.sensitivity


# ---- derived configs ----------------------------------------------------------

def test_with_period_and_params_are_copies():
    cfg = config_from_dict(minimal_dict())
    shifted = cfg.with_period(date(2021, 1, 1), date(2021, 6, 30))
    tweaked = cfg.with_strategy_params(nominal_stop_pct=0.25)
    assert cfg.start == date(2020, 1, 1) and cfg.strategy.params == {}  # baseline untouched
    assert shifted.start == date(2021, 1, 1) and shifted.symbols == cfg.symbols
    assert tweaked.strategy.params == {"nominal_stop_pct": 0.25}


def test_with_strategy_params_merges_over_existing():
    cfg = config_from_dict(minimal_dict()).with_strategy_params(a=1, b=2)
    assert dict(cfg.with_strategy_params(b=3).strategy.params) == {"a": 1, "b": 3}


# ---- building -----------------------------------------------------------------

def test_build_strategy_applies_params():
    cfg = RunConfig(
        name="x", symbols=("AAA",), start=date(2020, 1, 1), end=date(2020, 2, 1),
        strategy=StrategyConfig("vcp", {"tight_window": 7, "trail_ma": 20}),
    )
    strat = build_strategy(cfg)
    assert isinstance(strat, VcpStrategy)
    assert strat.tight_window == 7 and strat.trail_ma == 20


def test_build_strategy_fresh_instance_per_call():
    cfg = config_from_dict(minimal_dict())
    assert build_strategy(cfg) is not build_strategy(cfg)  # strategies may hold state


@pytest.mark.parametrize(
    "strategy, params, match",
    [
        ("nope", {}, "unknown strategy"),
        ("vcp", {"not_a_param": 1}, "bad params"),
    ],
)
def test_build_strategy_rejects_bad_spec(strategy, params, match):
    cfg = RunConfig(
        name="x", symbols=("AAA",), start=date(2020, 1, 1), end=date(2020, 2, 1),
        strategy=StrategyConfig(strategy, params),
    )
    with pytest.raises(ValueError, match=match):
        build_strategy(cfg)


def test_unknown_data_source_rejected():
    d = minimal_dict()
    d["data"] = {"source": "unknownsource"}
    cfg = config_from_dict(d)
    with pytest.raises(ValueError, match="unknown data source"):
        run_from_config(cfg)


# ---- running ------------------------------------------------------------------

def test_run_from_config_drives_engine_end_to_end():
    cfg = engine_cfg()
    result = run_from_config(cfg, make_provider())
    assert len(result.equity_curve) > 0
    assert len(result.trades) == 2  # buy-and-hold liquidates both symbols at the end
    # books reconcile: final equity = starting cash + total trade P&L
    total_pnl = sum(t.pnl for t in result.trades)
    assert abs(cfg.risk.starting_cash + total_pnl - float(result.equity_curve.iloc[-1])) < 1e-4
    # result echoes the self-describing config
    assert result.config["run_name"] == "test-run"
    assert result.config["strategy"] == "buy_and_hold"


def test_same_config_same_data_same_result():
    cfg = engine_cfg()
    provider = make_provider()
    a = run_from_config(cfg, provider)
    b = run_from_config(cfg, provider)
    pd.testing.assert_series_equal(a.equity_curve, b.equity_curve)
    assert a.trades == b.trades
    assert a.metrics == b.metrics


# ---- universe.file support -----------------------------------------------------------

def test_universe_file_loads_symbols(tmp_path):
    (tmp_path / "u.txt").write_text("# generated\nAAA\n\nBBB\n")
    d = minimal_dict()
    d["universe"] = {"file": "u.txt"}
    cfg = config_from_dict(d, base_dir=tmp_path)
    assert cfg.symbols == ("AAA", "BBB")


def test_universe_requires_exactly_one_of_symbols_or_file(tmp_path):
    d = minimal_dict()
    d["universe"] = {}
    with pytest.raises(ConfigError):
        config_from_dict(d, base_dir=tmp_path)
    d["universe"] = {"symbols": ["AAA"], "file": "u.txt"}
    with pytest.raises(ConfigError):
        config_from_dict(d, base_dir=tmp_path)


def test_universe_file_missing_or_empty_fails_loudly(tmp_path):
    d = minimal_dict()
    d["universe"] = {"file": "absent.txt"}
    with pytest.raises(ConfigError):
        config_from_dict(d, base_dir=tmp_path)
    (tmp_path / "empty.txt").write_text("# only comments\n")
    d["universe"] = {"file": "empty.txt"}
    with pytest.raises(ConfigError):
        config_from_dict(d, base_dir=tmp_path)


def test_bloomberg_provider_registered():
    from btf.config.builder import PROVIDERS
    assert "bloomberg" in PROVIDERS
