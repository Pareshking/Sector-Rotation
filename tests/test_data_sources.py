import json
from datetime import date

import pandas as pd

from src.data.nifty_indices import fetch_nifty_index_history, resolve_index_names


class _Response:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, str]:
        return {"d": json.dumps([
            {"indexName": "Nifty Financial Services", "HistoricalDate": "28 Aug 2026", "OPEN": "25000", "HIGH": "25100", "LOW": "24900", "CLOSE": "25050"},
            {"indexName": "Nifty Financial Services", "HistoricalDate": "27 Aug 2026", "OPEN": "24900", "HIGH": "25050", "LOW": "24850", "CLOSE": "24950"},
        ])}


class _Session:
    def get(self, *args, **kwargs):
        return _Response()

    def post(self, *args, **kwargs):
        return _Response()


def test_nifty_indices_parser(monkeypatch) -> None:
    monkeypatch.setattr("src.data.nifty_indices.cloudscraper.create_scraper", lambda **kwargs: _Session())
    series = fetch_nifty_index_history("Nifty Financial Services", start=date(2026, 8, 27), end=date(2026, 8, 28))
    assert isinstance(series, pd.Series)
    assert len(series) == 2
    assert float(series.iloc[-1]) == 25050.0


def test_official_index_aliases() -> None:
    assert resolve_index_names("telecom")[0] == "NIFTY TELECOMMUNICATIONS"
    assert resolve_index_names("NBFC")[0] == "NIFTY FINANCIAL SERVICES EX-BANK"
    assert resolve_index_names("healthcare")[:2] == ["NIFTY HEALTHCARE", "NIFTY HEALTHCARE INDEX"]
    assert resolve_index_names("power")[0] == "NIFTY POWER"
    assert resolve_index_names("capital-goods")[0] == "NIFTY CAPITAL GOODS"
    assert resolve_index_names("consumer-services")[0] == "NIFTY CONSUMER SERVICES"
