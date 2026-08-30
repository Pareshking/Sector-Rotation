from datetime import date

import pandas as pd

import src.data.jugaad_indices as jugaad
from src.data.canonical import promote_etf_histories
from src.data.index_data import download_canonical_indices


def _rows(column: str, value_key: str, periods: int = 80) -> list[dict[str, str]]:
    dates = pd.bdate_range("2026-05-18", periods=periods)
    return [
        {column: day.strftime("%d %b %Y"), value_key: f"{25010 + i * 2:.2f}"}
        for i, day in enumerate(dates)
    ]


def test_close_payload_is_parsed() -> None:
    series = jugaad._records_to_series("NIFTY FINANCIAL SERVICES", _rows("HistoricalDate", "CLOSE"))
    assert len(series) == 80
    assert float(series.iloc[-1]) == 25168.0


def test_tri_payload_is_parsed() -> None:
    series = jugaad._records_to_series("NIFTY 50", _rows("Date", "TotalReturnsIndex"))
    assert len(series) == 80
    assert float(series.iloc[-1]) == 25168.0


def test_total_return_series_is_preferred_and_labelled(monkeypatch) -> None:
    monkeypatch.setattr(jugaad, "index_tri_raw", lambda a, b, s, e: _rows("Date", "TRI"))
    monkeypatch.setattr(jugaad, "index_raw", lambda a, s, e: _rows("HistoricalDate", "CLOSE"))
    series = jugaad.fetch_jugaad_index("NIFTY 50", date(2026, 5, 18), date(2026, 9, 4))
    assert series.attrs["value_type"] == "TRI"
    assert series.attrs["source"] == "niftyindices_jugaad"


def test_price_close_is_labelled_when_total_return_is_unavailable(monkeypatch) -> None:
    """A price-index series must never be presented as a total-return series."""
    monkeypatch.setattr(jugaad, "index_tri_raw", lambda a, b, s, e: [])
    monkeypatch.setattr(jugaad, "index_raw", lambda a, s, e: _rows("HistoricalDate", "CLOSE"))
    series = jugaad.fetch_jugaad_index("NIFTY CEMENT", date(2026, 5, 18), date(2026, 9, 4))
    assert series.attrs["value_type"] == "CLOSE"


def test_unmapped_exposure_is_never_filled_by_an_unrelated_etf() -> None:
    etf_prices = pd.DataFrame(
        {"AUTOBEES": pd.Series(range(1, 101), index=pd.bdate_range("2026-01-01", periods=100))}
    )
    promoted, sources, _ = promote_etf_histories(
        {"capital-goods": "NIFTY CAPITAL GOODS"}, etf_prices, {"auto": "AUTOBEES"}
    )
    assert promoted == {}
    assert sources == {}


def test_explicitly_mapped_etf_is_promoted() -> None:
    etf_prices = pd.DataFrame(
        {"AUTOBEES": pd.Series(range(1, 101), index=pd.bdate_range("2026-01-01", periods=100))}
    )
    promoted, sources, resolved = promote_etf_histories(
        {"auto": "NIFTY AUTO"}, etf_prices, {"auto": "AUTOBEES"}
    )
    assert list(promoted) == ["auto"]
    assert sources["auto"] == "etf_nav_authoritative"
    assert resolved["auto"] == "ETF/NAV:AUTOBEES"


def test_canonical_download_records_provenance(monkeypatch) -> None:
    index = pd.bdate_range("2026-01-01", periods=100)
    monkeypatch.setattr(
        "src.data.index_data.fetch_jugaad_canonical_indices",
        lambda names, years, workers: (
            pd.DataFrame({"auto": pd.Series(range(1, 101), index=index, dtype=float)}),
            {"auto": "niftyindices_jugaad"},
            {"auto": "NIFTY AUTO"},
            {"auto": "TRI"},
        ),
    )
    prices = download_canonical_indices({"auto": "NIFTY AUTO"}, years=1)
    assert prices.attrs["source_by_exposure"]["auto"] == "niftyindices_jugaad"
    assert prices.attrs["value_type_by_exposure"]["auto"] == "TRI"
    assert prices.attrs["unresolved_exposures"] == []
