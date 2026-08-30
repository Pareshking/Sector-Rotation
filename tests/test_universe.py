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
    symbols = [
        etf.symbol
        for exposure in registry.all()
        for etf in exposure.etfs
        if etf.symbol is not None
    ]
    assert len(symbols) == len(set(symbols))


def test_legacy_aliases_are_accepted() -> None:
    etf = ETFMapping(symbol="BANKNIFTY1", name="Kotak Nifty Bank ETF", yfinance_symbol="BANKNIFTY1.NS", aliases=["KOTAKBKETF"])
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


def test_two_exposures_may_not_share_one_benchmark_index():
    """One index behind two exposures is one bet occupying two ranks."""
    from src.models.exposure import Exposure
    from src.universe.validation import validate_universe

    report = validate_universe([
        Exposure(id="nbfc", name="NBFC", category="sector", benchmark="NIFTY FIN EX-BANK"),
        Exposure(id="fx", name="Fin ex Bank", category="sector", benchmark="nifty fin ex-bank"),
    ])
    assert not report.valid
    assert any("shared by 2 exposures" in e for e in report.errors)


def test_the_shipped_universe_has_no_shared_benchmarks():
    import json
    from pathlib import Path

    from src.universe.registry import UniverseRegistry
    from src.universe.validation import validate_universe

    root = Path(__file__).resolve().parents[1]
    registry = UniverseRegistry.from_json(root / "data" / "universe" / "universe.json")
    report = validate_universe(registry.all())
    assert report.valid, report.errors
    del json


def test_vehicle_type_defaults_to_etf_and_accepts_index_funds():
    """An index fund transacts at NAV; an ETF at a price that can differ from it."""
    from src.models.exposure import ETFMapping, VehicleType

    assert ETFMapping(name="X ETF", symbol="X").vehicle is VehicleType.ETF
    fund = ETFMapping(name="Y Index Fund", scheme_code=151911, vehicle="index_fund")
    assert fund.vehicle is VehicleType.INDEX_FUND
    assert fund.symbol is None


def test_index_funds_are_excluded_from_exchange_traded():
    from src.models.exposure import ETFMapping, Exposure

    exposure = Exposure(
        id="realty", name="Realty", category="sector", benchmark="Nifty Realty",
        etfs=[ETFMapping(name="MO Realty ETF", symbol="MOREALTY"),
              ETFMapping(name="HDFC Realty Index Fund", scheme_code=152522, vehicle="index_fund")],
    )
    assert exposure.tradable
    assert [e.symbol for e in exposure.exchange_traded] == ["MOREALTY"]
