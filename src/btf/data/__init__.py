"""Data layer: vendor-agnostic ``DataProvider`` interface + adapters."""
from btf.data.memory_provider import InMemoryDataProvider
from btf.data.provider import DataProvider
from btf.data.stooq_provider import StooqDataProvider
from btf.data.yfinance_provider import YFinanceDataProvider

__all__ = [
    "DataProvider",
    "InMemoryDataProvider",
    "StooqDataProvider",
    "YFinanceDataProvider",
]
