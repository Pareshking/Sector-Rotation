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


def test_two_vehicles_sharing_a_scheme_code_or_isin_is_an_error():
    """TECH and ITETF once shared scheme 148560, so both read one stranger's NAV."""
    from src.models.exposure import ETFMapping, Exposure
    from src.universe.validation import validate_universe

    exposure = Exposure(
        id="it", name="IT", category="sector", benchmark="Nifty IT",
        etfs=[ETFMapping(name="A IT ETF", symbol="AIT", scheme_code=148560, isin="INF000000001"),
              ETFMapping(name="B IT ETF", symbol="BIT", scheme_code=148560, isin="INF000000001")],
    )
    errors = validate_universe([exposure]).errors
    assert any("Duplicate scheme code: 148560" in e for e in errors)
    assert any("Duplicate ISIN: INF000000001" in e for e in errors)


def test_every_shipped_vehicle_records_an_isin_and_every_index_a_launch_date():
    from pathlib import Path

    from src.universe.registry import UniverseRegistry

    root = Path(__file__).resolve().parents[1]
    exposures = UniverseRegistry.from_json(root / "data" / "universe" / "universe.json").all()
    missing_isin = [f"{x.id}/{v.symbol or v.name}" for x in exposures for v in x.etfs if not v.isin]
    assert not missing_isin
    assert not [x.id for x in exposures if x.launch_date is None]
    bounded = {x.id for x in exposures if x.launch_date_is_upper_bound}
    assert bounded == {"it", "mnc", "pse", "services"}


def test_every_shipped_etf_has_an_nse_symbol():
    """Without one, NSE's turnover and premium can never be matched to the fund."""
    root = Path(__file__).resolve().parents[1]
    exposures = UniverseRegistry.from_json(root / "data" / "universe" / "universe.json").all()
    unmatched = [f"{x.id}/{v.name}" for x in exposures for v in x.etfs if v.vehicle == "etf" and not v.symbol]
    assert not unmatched


def test_proxy_vehicles_name_the_index_they_actually_track():
    """GROWWPOWER tracks BSE Power, not NIFTY POWER; the entry must say so."""
    root = Path(__file__).resolve().parents[1]
    exposures = UniverseRegistry.from_json(root / "data" / "universe" / "universe.json").all()
    tracked = {v.symbol: v.tracked_index for x in exposures for v in x.etfs if v.tracked_index}
    assert tracked == {"GROWWPOWER": "BSE Power", "ICICIB22": "BSE Bharat 22"}


def test_tracked_index_equal_to_the_benchmark_is_rejected():
    """tracked_index marks a proxy, so repeating the benchmark is a mislabel."""
    etf = ETFMapping(symbol="X", name="X Power ETF", tracked_index="nifty power")
    exposure = Exposure(id="power", name="Power", category=ExposureCategory.SECTOR, benchmark="NIFTY POWER", etfs=[etf])
    assert any("tracked_index repeats the benchmark" in e for e in validate_universe([exposure]).errors)
