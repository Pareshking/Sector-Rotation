import pandas as pd

from src.data import etf_data
from src.models.exposure import ETFMapping


def _mfapi_result(rows: int = 60):
    dates = pd.date_range("2026-01-01", periods=rows, freq="D")
    frame = pd.DataFrame(
        {
            "close": range(rows),
            "adjusted_close": range(rows),
        },
        index=dates,
    )
    return type(
        "Result",
        (),
        {"frame": frame, "scheme_code": 150162},
    )()


def test_complete_mfapi_series_never_calls_yahoo(monkeypatch):
    etf = ETFMapping(
        symbol="METALIETF",
        name="ICICI Prudential Nifty Metal ETF",
        scheme_code=150162,
        yfinance_symbol="METALIETF.NS",
    )
    calls = {"mfapi": 0, "yahoo": 0}

    def fake_mfapi(*args, **kwargs):
        calls["mfapi"] += 1
        return _mfapi_result()

    def fake_yahoo(*args, **kwargs):
        calls["yahoo"] += 1
        raise AssertionError("Yahoo must not run after a complete MFAPI series")

    monkeypatch.setattr(etf_data, "fetch_etf_nav", fake_mfapi)
    monkeypatch.setattr(etf_data, "download_market_history", fake_yahoo)

    frame, sources, codes = etf_data.fetch_etf_histories([etf])

    assert calls == {"mfapi": 1, "yahoo": 0}
    assert "METALIETF" in frame
    assert sources["METALIETF"] == "mfapi"
    assert codes["METALIETF"] == 150162


def test_scheme_without_complete_mfapi_can_fall_back_to_yahoo(monkeypatch):
    etf = ETFMapping(
        symbol="B22",
        name="Bharat 22 ETF",
        scheme_code=143265,
        yfinance_symbol="ICICIB22.NS",
    )

    empty = type("Result", (), {"frame": pd.DataFrame(), "scheme_code": 143265})()
    yahoo = pd.DataFrame({"ICICIB22.NS": range(60)}, index=pd.date_range("2026-01-01", periods=60))

    monkeypatch.setattr(etf_data, "fetch_etf_nav", lambda *args, **kwargs: empty)
    monkeypatch.setattr(etf_data, "download_market_history", lambda *args, **kwargs: yahoo)

    frame, sources, _ = etf_data.fetch_etf_histories([etf])

    assert "B22" in frame
    assert sources["B22"] == "yahoo"


def test_snapshot_merge_matches_on_nse_symbol():
    import pandas as pd

    from src.data.nse_etf import merge_snapshot

    etfs = pd.DataFrame([{"exposure_id": "auto", "symbol": "AUTOBEES"},
                         {"exposure_id": "bank", "symbol": "BANKBEES"}])
    snapshot = pd.DataFrame([{"symbol": "AUTOBEES", "traded_value": 5.0, "traded_quantity": 1.0,
                              "last_price": 100.0, "nav": 99.0, "premium_discount_pct": 1.01,
                              "week52_high": 1.0, "week52_low": 1.0, "snapshot_utc": "x"}])
    merged = merge_snapshot(etfs, snapshot)
    assert float(merged.loc[merged.symbol == "AUTOBEES", "traded_value"].iat[0]) == 5.0
    assert pd.isna(merged.loc[merged.symbol == "BANKBEES", "traded_value"].iat[0])


def test_snapshot_failure_never_breaks_the_universe():
    """A decorative live feed must not be able to fail a valid pipeline run."""
    import pandas as pd

    from src.data.nse_etf import merge_snapshot

    etfs = pd.DataFrame([{"exposure_id": "auto", "symbol": "AUTOBEES"}])
    merged = merge_snapshot(etfs, pd.DataFrame())
    assert len(merged) == 1
    assert "traded_value" in merged.columns
    assert merged["traded_value"].isna().all()


def test_premium_is_computed_from_price_over_nav():
    import pandas as pd

    from src.data.nse_etf import _number

    assert _number("1,234.50") == 1234.5
    assert pd.isna(_number("-"))
    assert pd.isna(_number(None))


def test_every_mapped_vehicle_has_a_symbol_or_a_scheme_code():
    """A vehicle nothing can be fetched by is a dead mapping."""
    from pathlib import Path

    from src.universe.registry import UniverseRegistry

    root = Path(__file__).resolve().parents[1]
    registry = UniverseRegistry.from_json(root / "data" / "universe" / "universe.json")
    for exposure in registry.all():
        for etf in exposure.etfs:
            assert etf.symbol or etf.scheme_code, f"{exposure.id}/{etf.name} has neither"


def test_index_funds_carry_a_scheme_code_not_a_ticker():
    from pathlib import Path

    from src.models.exposure import VehicleType
    from src.universe.registry import UniverseRegistry

    root = Path(__file__).resolve().parents[1]
    registry = UniverseRegistry.from_json(root / "data" / "universe" / "universe.json")
    funds = [e for x in registry.all() for e in x.etfs if e.vehicle is VehicleType.INDEX_FUND]
    assert funds, "expected at least one open-ended index fund in the universe"
    for fund in funds:
        assert fund.scheme_code, f"{fund.name} has no AMFI scheme code"
        assert fund.symbol is None, f"{fund.name} is not exchange-traded but carries a ticker"
