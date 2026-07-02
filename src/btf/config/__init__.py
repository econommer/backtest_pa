"""Config-driven runs (core principle 5): one YAML = one fully-defined run."""
from btf.config.builder import build_provider, build_strategy, run_from_config
from btf.config.loader import ConfigError, config_from_dict, load_config
from btf.config.schema import (
    CostsConfig,
    DataConfig,
    RiskConfig,
    RunConfig,
    StrategyConfig,
    ValidationConfig,
)

__all__ = [
    "ConfigError",
    "CostsConfig",
    "DataConfig",
    "RiskConfig",
    "RunConfig",
    "StrategyConfig",
    "ValidationConfig",
    "build_provider",
    "build_strategy",
    "config_from_dict",
    "load_config",
    "run_from_config",
]
