from pathlib import Path

from src.models.exposure import ETFMapping, Exposure, ExposureCategory
from src.universe.registry import UniverseRegistry
from src.universe.validation import validate_universe


def test_universe_loads() -> None:
    root = Path(__file__).resolve().parents[1]
    registry = UniverseRegistry.from_json(root / "data" / "universe" / "universe.json")
    assert len(registry.all()) >= 40
    assert len(registry.sectors()) > 0
    assert len(registry.themes()) > 0
    assert validate_universe(registry.all()).valid


def test_etf_symbols_are_unique() -> None:
    root = Path(__file__).resolve().parents[1]
    registry = UniverseRegistry.from_json(root / "data" / "universe" / "universe.json")
    symbols = [etf.symbol for exposure in registry.all() for etf in exposure.etfs]
    assert len(symbols) == len(set(symbols))


def test_legacy_aliases_are_accepted() -> None:
    etf = ETFMapping(symbol="BANKNIFTY1", name="Kotak Nifty Bank ETF", yfinance_symbol="BANKNIFTY1.NS", aliases=["kotakbketf"])
    exposure = Exposure(id="bank", name="Banking", category=ExposureCategory.SECTOR, benchmark="Nifty Bank", etfs=[etf])
    report = validate_universe([exposure])
    assert report.valid
    assert "KOTAKBKETF" in etf.aliases


def test_invalid_nse_symbol_is_rejected() -> None:
    etf = ETFMapping(symbol="bad symbol", name="Bad ETF", yfinance_symbol="BAD.NS")
    exposure = Exposure(id="bad", name="Bad", category=ExposureCategory.SECTOR, benchmark="Nifty Bad", etfs=[etf])
    report = validate_universe([exposure])
    assert not report.valid
    assert any("invalid NSE symbol" in error for error in report.errors)
