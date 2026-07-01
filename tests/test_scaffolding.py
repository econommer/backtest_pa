import importlib


def test_btf_imports():
    mod = importlib.import_module("btf")
    assert isinstance(mod.__version__, str)


def test_subpackages_import():
    for pkg in ("data", "strategies", "risk", "broker", "context", "engine", "metrics"):
        importlib.import_module(f"btf.{pkg}")
