"""M5 bias defenses: OOS split, walk-forward, sensitivity, reports (plan §6).

Invariants:
- the split halves and walk-forward windows tile the period exactly — contiguous,
  non-overlapping, first starts at cfg.start, last ends at cfg.end — and every
  sub-run's equity curve stays inside its window (no leakage across boundaries);
- sensitivity varies exactly one param per point, reuses (not reruns) the
  baseline result for baseline-valued points, and rejects unknown params;
- reports flag small samples (< MIN_SIGNIFICANT_TRADES trades).

All offline via InMemoryDataProvider.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest

from btf.config import config_from_dict
from btf.data.memory_provider import InMemoryDataProvider
from btf.validation import (
    MIN_SIGNIFICANT_TRADES,
    metrics_row,
    run_oos_split,
    run_sensitivity,
    run_walk_forward,
    sensitivity_report,
    split_report,
    walk_forward_report,
)

START, END = date(2020, 1, 1), date(2020, 12, 31)
N_DAYS = 262  # business days covering 2020


def make_provider() -> InMemoryDataProvider:
    idx = pd.bdate_range(START.isoformat(), periods=N_DAYS)
    closes = [50.0 + i * 0.2 for i in range(N_DAYS)]
    frame = pd.DataFrame(
        {
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1000.0] * N_DAYS,
        },
        index=idx,
    )
    bench = pd.Series([300.0 + i for i in range(N_DAYS)], index=idx)
    return InMemoryDataProvider({"AAA": frame}, benchmark=bench)


def make_cfg(validation: dict | None = None):
    d: dict = {
        "name": "val-test",
        "period": {"start": START, "end": END},
        "universe": {"symbols": ["AAA"]},
        "strategy": {"name": "buy_and_hold"},
        "data": {"benchmark": "SPY"},
    }
    if validation is not None:
        d["validation"] = validation
    return config_from_dict(d)


def curve_dates(result) -> tuple[date, date]:
    idx = result.equity_curve.index
    return idx[0].date(), idx[-1].date()


# ---- OOS split ------------------------------------------------------------------

def test_split_halves_tile_the_period():
    boundary = date(2020, 7, 1)
    cfg = make_cfg({"oos_start": boundary})
    s = run_oos_split(cfg, provider=make_provider())
    is_first, is_last = curve_dates(s.in_sample)
    oos_first, oos_last = curve_dates(s.out_of_sample)
    assert is_first >= START and is_last < boundary  # IS strictly before the boundary
    assert oos_first >= boundary and oos_last <= END  # OOS never sees IS days
    assert s.oos_start == boundary


def test_split_explicit_arg_overrides_config():
    cfg = make_cfg({"oos_start": date(2020, 7, 1)})
    s = run_oos_split(cfg, oos_start=date(2020, 10, 1), provider=make_provider())
    assert s.oos_start == date(2020, 10, 1)


def test_split_requires_a_boundary():
    with pytest.raises(ValueError, match="oos_start"):
        run_oos_split(make_cfg(), provider=make_provider())


def test_split_rejects_boundary_outside_period():
    with pytest.raises(ValueError, match="inside the period"):
        run_oos_split(make_cfg(), oos_start=date(2030, 1, 1), provider=make_provider())


# ---- walk-forward ----------------------------------------------------------------

def test_walk_forward_windows_tile_the_period():
    cfg = make_cfg({"walk_forward_windows": 4})
    w = run_walk_forward(cfg, provider=make_provider())
    assert len(w.windows) == 4
    assert w.windows[0].start == START and w.windows[-1].end == END
    for prev, nxt in zip(w.windows, w.windows[1:]):
        assert nxt.start == prev.end + timedelta(days=1)  # contiguous, non-overlapping
    for win in w.windows:
        first, last = curve_dates(win.result)
        assert win.start <= first and last <= win.end  # each run stays inside its window


def test_walk_forward_explicit_arg_overrides_config():
    cfg = make_cfg({"walk_forward_windows": 4})
    w = run_walk_forward(cfg, n_windows=2, provider=make_provider())
    assert len(w.windows) == 2


@pytest.mark.parametrize("n, match", [(None, "n_windows"), (1, ">= 2")])
def test_walk_forward_rejects_bad_window_count(n, match):
    with pytest.raises(ValueError, match=match):
        run_walk_forward(make_cfg(), n_windows=n, provider=make_provider())


# ---- sensitivity ------------------------------------------------------------------

def test_sensitivity_sweeps_one_param_at_a_time():
    cfg = make_cfg({"sensitivity": {"nominal_stop_pct": [0.25, 0.5, 0.75]}})
    s = run_sensitivity(cfg, provider=make_provider())
    assert [p.value for p in s.points] == [0.25, 0.5, 0.75]
    # 0.5 is BuyAndHold's constructor default -> baseline point, result reused not rerun
    baseline_points = [p for p in s.points if p.is_baseline]
    assert [p.value for p in baseline_points] == [0.5]
    assert baseline_points[0].result is s.baseline
    # off-baseline points really ran: a tighter nominal stop changes R-based sizing
    off = {p.value: p.result for p in s.points if not p.is_baseline}
    assert not off[0.25].equity_curve.equals(s.baseline.equity_curve)


def test_sensitivity_baseline_detects_explicit_config_value():
    cfg = make_cfg({"sensitivity": {"nominal_stop_pct": [0.25, 0.5]}})
    cfg = cfg.with_strategy_params(nominal_stop_pct=0.25)
    s = run_sensitivity(cfg, provider=make_provider())
    assert [p.value for p in s.points if p.is_baseline] == [0.25]


def test_sensitivity_rejects_unknown_param():
    cfg = make_cfg({"sensitivity": {"not_a_param": [1, 2]}})
    with pytest.raises(ValueError, match="not_a_param"):
        run_sensitivity(cfg, provider=make_provider())


def test_sensitivity_requires_a_grid():
    with pytest.raises(ValueError, match="grid"):
        run_sensitivity(make_cfg(), provider=make_provider())


# ---- reports ---------------------------------------------------------------------

def test_reports_render_and_flag_small_samples():
    provider = make_provider()
    boundary = date(2020, 7, 1)
    cfg = make_cfg(
        {
            "oos_start": boundary,
            "walk_forward_windows": 2,
            "sensitivity": {"nominal_stop_pct": [0.25, 0.5]},
        }
    )
    split_txt = split_report(run_oos_split(cfg, provider=provider))
    wf_txt = walk_forward_report(run_walk_forward(cfg, provider=provider))
    sens_txt = sensitivity_report(run_sensitivity(cfg, provider=provider))

    assert str(boundary) in split_txt and "IS " in split_txt and "OOS" in split_txt
    assert "2 windows" in wf_txt and "positive expectancy" in wf_txt
    assert "nominal_stop_pct" in sens_txt and "*" in sens_txt  # baseline marked
    # buy-and-hold on one symbol = 1 trade per run -> every table flags small samples
    for txt in (split_txt, wf_txt, sens_txt):
        assert "!" in txt and str(MIN_SIGNIFICANT_TRADES) in txt


def test_metrics_row_flags_small_sample_only():
    from btf.metrics.result import Metrics

    small = Metrics(num_trades=5, win_rate=0.6, avg_win_r=2.0, avg_loss_r=0.5,
                    expectancy=1.0, profit_factor=2.0, max_losing_streak=1,
                    max_drawdown_r=1.0, max_drawdown_pct=0.1, exposure=0.5)
    big = Metrics(num_trades=50, win_rate=0.6, avg_win_r=2.0, avg_loss_r=0.5,
                  expectancy=1.0, profit_factor=2.0, max_losing_streak=1,
                  max_drawdown_r=1.0, max_drawdown_pct=0.1, exposure=0.5)
    assert metrics_row("small", small).endswith("!")
    assert not metrics_row("big", big).endswith("!")
