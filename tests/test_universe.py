from pathlib import Path

from src.universe.registry import UniverseRegistry
from src.universe.validation import validate_universe


def test_universe_loads() -> None:
    root = Path(__file__).resolve().parents[1]
    registry = UniverseRegistry.from_json(root / "data" / "universe" / "universe.json")
    assert len(registry.all()) >= 20
    assert len(registry.sectors()) > 0
    assert len(registry.themes()) > 0
    assert validate_universe(registry.all()).valid


def test_etf_symbols_are_unique() -> None:
    root = Path(__file__).resolve().parents[1]
    registry = UniverseRegistry.from_json(root / "data" / "universe" / "universe.json")
    symbols = [etf.symbol for exposure in registry.all() for etf in exposure.etfs]
    assert len(symbols) == len(set(symbols))
