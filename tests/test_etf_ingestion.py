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
