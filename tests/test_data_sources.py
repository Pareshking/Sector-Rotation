import json
from datetime import date

import pandas as pd

from src.data.nifty_indices import fetch_nifty_index_history, resolve_index_names


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, str]:
        dates = pd.bdate_range("2026-05-18", periods=80)
        rows = [
            {
                "indexName": "Nifty Financial Services",
                "HistoricalDate": day.strftime("%d %b %Y"),
                "OPEN": f"{25000 + i * 2:.2f}",
                "HIGH": f"{25020 + i * 2:.2f}",
                "LOW": f"{24980 + i * 2:.2f}",
                "CLOSE": f"{25010 + i * 2:.2f}",
            }
            for i, day in enumerate(dates)
        ]
        return {"d": json.dumps(rows)}


class _Session:
    def get(self, *args, **kwargs):
        return _Response()

    def post(self, *args, **kwargs):
        return _Response()


def test_nifty_indices_parser(monkeypatch) -> None:
    monkeypatch.setattr("src.data.nifty_indices.cloudscraper.create_scraper", lambda **kwargs: _Session())
    series = fetch_nifty_index_history("Nifty Financial Services", start=date(2026, 5, 18), end=date(2026, 9, 4))
    assert isinstance(series, pd.Series)
    assert len(series) == 80
    assert len(series.dropna()) >= 60
    assert float(series.iloc[-1]) == 25168.0


def test_official_index_aliases() -> None:
    assert resolve_index_names("telecom")[0] == "NIFTY TELECOMMUNICATIONS"
    assert resolve_index_names("NBFC")[0] == "NIFTY FINANCIAL SERVICES EX-BANK"
    assert resolve_index_names("healthcare")[:2] == ["NIFTY HEALTHCARE", "NIFTY HEALTHCARE INDEX"]
    assert resolve_index_names("power")[0] == "NIFTY POWER"
    assert resolve_index_names("capital-goods")[0] == "NIFTY CAPITAL GOODS"
    assert resolve_index_names("consumer-services")[0] == "NIFTY CONSUMER SERVICES"
