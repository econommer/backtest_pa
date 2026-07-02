"""YAML/dict -> ``RunConfig`` with strict validation (M5).

Strictness is a reproducibility defense: an unknown or misspelled key fails
loudly instead of silently falling back to a default — a config that loads is a
config that ran with exactly what it says. Dates accept ``datetime.date``
(PyYAML parses bare ISO dates natively) or ISO strings.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping

import yaml

from btf.config.schema import (
    CostsConfig,
    DataConfig,
    RiskConfig,
    RunConfig,
    StrategyConfig,
    ValidationConfig,
)


class ConfigError(ValueError):
    """A run config is malformed — message says which key and why."""


def load_config(path: str | Path) -> RunConfig:
    """Parse a YAML file into a validated ``RunConfig``."""
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{path}: top level must be a mapping, got {type(raw).__name__}")
    return config_from_dict(raw)


def config_from_dict(d: Mapping[str, Any]) -> RunConfig:
    """Build a ``RunConfig`` from a plain mapping (the YAML document shape)."""
    _reject_unknown(d, {"name", "period", "universe", "data", "costs", "risk",
                        "strategy", "validation"}, where="top level")

    name = _require(d, "name", str)
    period = _require(d, "period", Mapping)
    _reject_unknown(period, {"start", "end"}, where="period")
    start = _to_date(_require(period, "start", object), "period.start")
    end = _to_date(_require(period, "end", object), "period.end")
    if end <= start:
        raise ConfigError(f"period.end ({end}) must be after period.start ({start})")

    universe = _require(d, "universe", Mapping)
    _reject_unknown(universe, {"symbols"}, where="universe")
    symbols = _require(universe, "symbols", list)
    if not symbols or not all(isinstance(s, str) for s in symbols):
        raise ConfigError("universe.symbols must be a non-empty list of strings")

    strategy_raw = _require(d, "strategy", Mapping)
    _reject_unknown(strategy_raw, {"name", "params"}, where="strategy")
    params = strategy_raw.get("params") or {}
    if not isinstance(params, Mapping):
        raise ConfigError("strategy.params must be a mapping")
    strategy = StrategyConfig(name=_require(strategy_raw, "name", str), params=dict(params))

    return RunConfig(
        name=name,
        symbols=tuple(symbols),
        start=start,
        end=end,
        strategy=strategy,
        data=_data_config(d.get("data")),
        costs=_section(d.get("costs"), CostsConfig, "costs"),
        risk=_section(d.get("risk"), RiskConfig, "risk"),
        validation=_validation_config(d.get("validation"), start, end),
    )


# ---- section parsers ---------------------------------------------------------

def _data_config(raw: Any) -> DataConfig:
    if raw is None:
        return DataConfig()
    if not isinstance(raw, Mapping):
        raise ConfigError("data must be a mapping")
    _reject_unknown(raw, {"source", "cache_dir", "benchmark"}, where="data")
    defaults = DataConfig()
    return DataConfig(
        source=raw.get("source", defaults.source),
        cache_dir=raw.get("cache_dir", defaults.cache_dir),
        benchmark=raw.get("benchmark", defaults.benchmark),
    )


def _section(raw: Any, cls: type, where: str) -> Any:
    """Parse a flat numeric section (costs / risk) into its dataclass."""
    if raw is None:
        return cls()
    if not isinstance(raw, Mapping):
        raise ConfigError(f"{where} must be a mapping")
    fields = set(cls.__dataclass_fields__)  # type: ignore[attr-defined]
    _reject_unknown(raw, fields, where=where)
    kwargs = {k: float(v) for k, v in raw.items()}
    return cls(**kwargs)


def _validation_config(raw: Any, start: date, end: date) -> ValidationConfig:
    if raw is None:
        return ValidationConfig()
    if not isinstance(raw, Mapping):
        raise ConfigError("validation must be a mapping")
    _reject_unknown(raw, {"oos_start", "walk_forward_windows", "sensitivity"},
                    where="validation")

    oos_start: date | None = None
    if raw.get("oos_start") is not None:
        oos_start = _to_date(raw["oos_start"], "validation.oos_start")
        if not (start < oos_start <= end):
            raise ConfigError(
                f"validation.oos_start ({oos_start}) must fall inside the period "
                f"({start} .. {end}]"
            )

    windows: int | None = None
    if raw.get("walk_forward_windows") is not None:
        windows = int(raw["walk_forward_windows"])
        if windows < 2:
            raise ConfigError("validation.walk_forward_windows must be >= 2")

    sensitivity_raw = raw.get("sensitivity") or {}
    if not isinstance(sensitivity_raw, Mapping):
        raise ConfigError("validation.sensitivity must map param name -> list of values")
    sensitivity: dict[str, tuple[object, ...]] = {}
    for param, values in sensitivity_raw.items():
        if not isinstance(values, list) or not values:
            raise ConfigError(
                f"validation.sensitivity.{param} must be a non-empty list of values"
            )
        sensitivity[param] = tuple(values)

    return ValidationConfig(
        oos_start=oos_start, walk_forward_windows=windows, sensitivity=sensitivity
    )


# ---- primitives ---------------------------------------------------------------

def _require(d: Mapping[str, Any], key: str, typ: type) -> Any:
    if key not in d or d[key] is None:
        raise ConfigError(f"missing required key: {key!r}")
    value = d[key]
    if typ is not object and not isinstance(value, typ):
        raise ConfigError(f"{key!r} must be {typ.__name__}, got {type(value).__name__}")
    return value


def _reject_unknown(d: Mapping[str, Any], allowed: set[str], *, where: str) -> None:
    unknown = set(d) - allowed
    if unknown:
        raise ConfigError(
            f"unknown key(s) in {where}: {sorted(unknown)} (allowed: {sorted(allowed)})"
        )


def _to_date(value: Any, where: str) -> date:
    if isinstance(value, datetime):  # check before date: datetime IS a date
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as exc:
            raise ConfigError(f"{where}: not an ISO date: {value!r}") from exc
    raise ConfigError(f"{where}: expected a date, got {type(value).__name__}")
