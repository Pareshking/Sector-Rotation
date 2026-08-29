import pandas as pd

from src.data.mfapi import fetch_scheme_history, resolve_scheme_code, search_schemes


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_mfapi_search_and_resolution(monkeypatch, tmp_path):
    payload = [{"schemeCode": "140107", "schemeName": "CPSE ETF"}]
    monkeypatch.setattr("src.data.mfapi.requests.get", lambda *args, **kwargs: _Response(payload))
    found = search_schemes("CPSEETF", cache_dir=tmp_path)
    assert int(found.iloc[0]["scheme_code"]) == 140107
    assert resolve_scheme_code("CPSEETF", expected_name="CPSE ETF", cache_dir=tmp_path) == 140107


def test_mfapi_history_normalizes_nav(monkeypatch, tmp_path):
    payload = {
        "meta": {"scheme_name": "CPSE ETF"},
        "data": [{"date": "28-08-2026", "nav": "123.45"}, {"date": "27-08-2026", "nav": "122.00"}],
    }
    monkeypatch.setattr("src.data.mfapi.requests.get", lambda *args, **kwargs: _Response(payload))
    result = fetch_scheme_history(140107, cache_dir=tmp_path)
    assert list(result.frame.columns) == ["close", "adjusted_close"]
    assert isinstance(result.frame.index, pd.DatetimeIndex)
    assert float(result.frame.iloc[-1]["adjusted_close"]) == 123.45
    assert result.scheme_name == "CPSE ETF"


def test_mfapi_adjusted_close_repairs_persistent_unit_split(monkeypatch, tmp_path):
    dates = pd.bdate_range("2026-01-01", periods=50)
    values = [100.0 + i for i in range(25)] + [12.5 + i * 0.125 for i in range(25)]
    payload = {
        "meta": {"scheme_name": "Synthetic ETF"},
        "data": [
            {"date": d.strftime("%d-%m-%Y"), "nav": f"{v:.4f}"}
            for d, v in zip(reversed(dates), reversed(values))
        ],
    }
    monkeypatch.setattr("src.data.mfapi.requests.get", lambda *args, **kwargs: _Response(payload))
    result = fetch_scheme_history(999999, cache_dir=tmp_path)
    raw = result.frame["close"]
    adjusted = result.frame["adjusted_close"]
    assert raw.iloc[24] > 100
    assert raw.iloc[25] < 20
    assert adjusted.iloc[24] / adjusted.iloc[25] < 1.5
