"""End-to-end smoke test on REAL data — BuyAndHold over the pinned snapshot (M2).

Runs offline against the cached parquet snapshot (see ``btf.data.phase1_snapshot``
and ``scripts/fetch_snapshot.py``). If the snapshot is not on disk (e.g. a fresh
checkout, or a sandbox that can't reach Yahoo), the test SKIPS with instructions
rather than hitting the network — keeping CI deterministic.

Asserts: books reconcile, the equity curve is sane (positive, no NaN, right
length, actually moves), and the benchmark overlay lines up. Also surfaces the
Phase-1 survivorship-bias flag in the output.
"""
from __future__ import annotations

import pytest

pytest.importorskip("pyarrow")

from btf.broker.simple_broker import SimpleBroker
from btf.data import phase1_snapshot as snap
from btf.engine.basic_engine import BasicEngine
from btf.risk.fixed_risk_sizer import FixedRiskSizer
from btf.strategies.buy_and_hold import BuyAndHold


def _require_snapshot():
    if not snap.is_cached():
        pytest.skip(
            "Phase-1 data snapshot not cached. Populate it in a network-enabled "
            "env with:  pip install -e '.[data]' && python scripts/fetch_snapshot.py "
            f"(missing: {snap.missing_symbols()})"
        )


def _no_network_fetch(symbol, start, end):
    raise AssertionError(f"smoke test must run offline; would have fetched {symbol}")


def test_smoke_buy_and_hold_real_data(capsys):
    _require_snapshot()
    # fetch_fn raises → proves we never touch the network (everything is cached).
    provider = snap.build_provider(fetch_fn=_no_network_fetch)

    starting_cash = 100_000.0
    result = BasicEngine().run(
        strategy=BuyAndHold(nominal_stop_pct=0.9),  # far stop → hold, don't get stopped
        data=provider,
        broker=SimpleBroker(commission_per_share=0.005, slippage_pct=0.0005),
        sizer=FixedRiskSizer(risk_pct=0.02),
        config={
            "start": snap.START,
            "end": snap.END,
            "starting_cash": starting_cash,
            "symbols": snap.SYMBOLS,
            "benchmark": snap.BENCHMARK,
        },
    )

    # --- books reconcile ---------------------------------------------------
    assert 1 <= len(result.trades) <= len(snap.SYMBOLS)
    total_pnl = sum(t.pnl for t in result.trades)
    final_equity = float(result.equity_curve.iloc[-1])
    assert starting_cash + total_pnl == pytest.approx(final_equity, rel=1e-9)

    # --- equity curve is sane ---------------------------------------------
    eq = result.equity_curve
    calendar = provider.trading_calendar(snap.START, snap.END)
    assert len(eq) == len(calendar)
    assert not eq.isna().any()
    assert (eq > 0).all()
    assert eq.max() > eq.min()  # it actually moves; not a flat line
    # sane magnitude: buy-and-hold large-caps shouldn't 10x or lose 90% here
    assert 0.3 * starting_cash < final_equity < 10 * starting_cash

    # --- benchmark overlay works ------------------------------------------
    bench = result.benchmark_curve
    assert bench is not None
    assert list(bench.index) == list(eq.index)  # aligned to the equity curve
    assert (bench > 0).all()
    assert float(bench.iloc[0]) == pytest.approx(starting_cash, rel=1e-6)  # normalized

    # --- survivorship bias is flagged in output ---------------------------
    warning = snap.survivorship_warning()
    assert "SURVIVORSHIP" in warning
    print(warning)
    print(
        f"BuyAndHold {snap.SYMBOLS} {snap.START}..{snap.END}: "
        f"final=${final_equity:,.0f} vs benchmark=${float(bench.iloc[-1]):,.0f} "
        f"({len(result.trades)} trades)"
    )
    assert "SURVIVORSHIP" in capsys.readouterr().out
