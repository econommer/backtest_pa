"""M5 bias defenses: IS/OOS split, walk-forward, parameter sensitivity (plan §6)."""
from btf.validation.report import (
    MIN_SIGNIFICANT_TRADES,
    SMALL_SAMPLE_LEGEND,
    TABLE_HEADER,
    metrics_row,
    result_row,
    sensitivity_report,
    split_report,
    walk_forward_report,
)
from btf.validation.sensitivity import SensitivityResult, SweepPoint, run_sensitivity
from btf.validation.split import SplitResult, run_oos_split
from btf.validation.walk_forward import (
    WalkForwardResult,
    WalkForwardWindow,
    run_walk_forward,
)

__all__ = [
    "MIN_SIGNIFICANT_TRADES",
    "SMALL_SAMPLE_LEGEND",
    "TABLE_HEADER",
    "SensitivityResult",
    "SplitResult",
    "SweepPoint",
    "WalkForwardResult",
    "WalkForwardWindow",
    "metrics_row",
    "result_row",
    "run_oos_split",
    "run_sensitivity",
    "run_walk_forward",
    "sensitivity_report",
    "split_report",
    "walk_forward_report",
]
