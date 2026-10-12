"""BSE Index Services history: parsing, validation, provider routing. No network."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import requests
from pydantic import ValidationError

import src.data.bse_indices as bse
from src.data.calendar import TradingCalendar
from src.models.exposure import Exposure, IndexProvider

# A real response for BSE Insurance (id 154), 1-15 Sep 2026, as the endpoint
# serves it: a JSON *string* holding a header array and a values array joined
# by "#@#". 14 Sep 2026 was a market holiday.
REAL_PAYLOAD = (
    '[{ "currDate":"Tue Sep 01 2026 00:00:00","PreClose":"1432.78","MinLow":"1400","MaxLow":"1550",'
    '"Scrip":"INSURE","LatestVal":"1521.41","LatestTime":"Tue Sep 01 2026 00:00:00","source":"DB"}]#@#'
    '[{ "date":"Tue Sep 01 2026 00:00:00", "value":"1521.41"},{ "date":"Wed Sep 02 2026 00:00:00", "value":"1504.76"},'
    '{ "date":"Thu Sep 03 2026 00:00:00", "value":"1505.42"},{ "date":"Fri Sep 04 2026 00:00:00", "value":"1526.06"},'
    '{ "date":"Mon Sep 07 2026 00:00:00", "value":"1503.99"},{ "date":"Tue Sep 08 2026 00:00:00", "value":"1488.16"},'
    '{ "date":"Wed Sep 09 2026 00:00:00", "value":"1466.02"},{ "date":"Thu Sep 10 2026 00:00:00", "value":"1474.47"},'
    '{ "date":"Fri Sep 11 2026 00:00:00", "value":"1472.70"},{ "date":"Tue Sep 15 2026 00:00:00", "value":"1432.78"}]'
)
# What the endpoint answers for a window with no sessions in it.
EMPTY_PAYLOAD = "#@#[]"


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(bse, "_sleep", sleeps.append)
    return sleeps


def _payload(code: str, days: pd.DatetimeIndex, start: float = 1000.0, drop=()) -> str:
    header = [{"currDate": f"{days[0]:%a %b %d %Y} 00:00:00", "Scrip": code, "source": "DB"}]
    rows = [
        {"date": f"{d:%a %b %d %Y} 00:00:00", "value": f"{start + i:.2f}"}
        for i, d in enumerate(days)
        if d not in drop
    ]
    return json.dumps(header) + "#@#" + json.dumps(rows)


def _serve(monkeypatch, *payloads):
    """Answer successive requests with ``payloads`` (an exception instance is raised)."""
    urls: list[str] = []
    queue = list(payloads)

    def get(url):
        urls.append(url)
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(bse, "_get", get)
    return urls


SESSIONS = pd.bdate_range("2026-03-02", "2026-09-30")


def test_the_real_payload_is_parsed_with_its_index_code():
    code, series = bse.parse_payload(REAL_PAYLOAD, "BSE Insurance")
    assert code == "INSURE"
    assert len(series) == 10
    assert series.index[0] == pd.Timestamp("2026-09-01")
    assert pd.Timestamp("2026-09-14") not in series.index
    assert series.loc["2026-09-15"] == pytest.approx(1432.78)
    assert series.index.is_monotonic_increasing


def test_an_empty_window_parses_to_an_empty_series():
    code, series = bse.parse_payload(EMPTY_PAYLOAD)
    assert code is None and series.empty


def test_the_latest_point_fallback_is_not_a_value_for_the_window():
    """An unrecognised request is answered with today's level under ``value1``."""
    payload = '[{"Scrip":"INSURE"}]#@#[{ "date":"Mon Oct 12 2026 00:00:00", "value1":"1469.92"}]'
    assert bse.parse_payload(payload)[1].empty


def test_an_html_block_page_is_a_retryable_error():
    with pytest.raises(ValueError):
        bse.parse_payload("<html>Access Denied</html>")


def test_the_request_asks_for_the_date_range_by_numeric_id():
    url = bse._url(154, date(2021, 10, 1), date(2026, 10, 12))
    assert url.startswith(bse.BASE_URL)
    assert "index=154" in url and "seriesid=DT" in url
    assert "frd=20211001" in url and "tod=20261012" in url


def test_a_complete_series_is_labelled_as_a_bse_price_index(monkeypatch):
    _serve(monkeypatch, _payload("INSURE", SESSIONS))
    series = bse.fetch_bse_index(
        "BSE Insurance", date(2026, 3, 2), date(2026, 9, 30),
        calendar=TradingCalendar(SESSIONS), source_id=154, index_code="INSURE",
    )
    assert len(series) == len(SESSIONS)
    assert series.attrs["value_type"] == "CLOSE"  # never presented as total return
    assert series.attrs["source"] == "bseindices"
    assert series.attrs["index_code"] == "INSURE"


def test_a_response_for_another_index_is_refused_without_retrying(monkeypatch, _no_backoff_sleep):
    urls = _serve(monkeypatch, _payload("BSHOSP", SESSIONS))
    series = bse.fetch_bse_index(
        "BSE Insurance", date(2026, 3, 2), date(2026, 9, 30), source_id=158, index_code="INSURE"
    )
    assert series.empty
    assert "served BSHOSP, not INSURE" in series.attrs["errors"][0]
    assert len(urls) == 1 and not _no_backoff_sleep


def test_a_truncated_series_is_retried_then_reported(monkeypatch, _no_backoff_sleep):
    holed = SESSIONS[(SESSIONS >= "2026-05-01") & (SESSIONS <= "2026-06-15")]
    urls = _serve(monkeypatch, _payload("INSURE", SESSIONS, drop=set(holed)))
    series = bse.fetch_bse_index(
        "BSE Insurance", date(2026, 3, 2), date(2026, 9, 30),
        calendar=TradingCalendar(SESSIONS), source_id=154, index_code="INSURE",
    )
    assert series.empty
    assert "IncompleteSeries" in series.attrs["errors"][0]
    assert len(urls) == bse.RETRY_ATTEMPTS
    assert _no_backoff_sleep == [2.0, 4.0]


def test_a_dropped_connection_recovers_on_retry(monkeypatch):
    urls = _serve(monkeypatch, requests.ConnectionError("reset"), _payload("INSURE", SESSIONS))
    series = bse.fetch_bse_index(
        "BSE Insurance", date(2026, 3, 2), date(2026, 9, 30), source_id=154, index_code="INSURE"
    )
    assert len(series) == len(SESSIONS) and len(urls) == 2


def test_a_total_return_continuation_is_refused_not_mislabelled(monkeypatch):
    """A stored TRI series must never be extended with BSE's price index."""
    urls = _serve(monkeypatch, _payload("INSURE", SESSIONS))
    series = bse.fetch_bse_index(
        "BSE Insurance", date(2026, 3, 2), date(2026, 9, 30),
        value_types=("TRI",), source_id=154, index_code="INSURE",
    )
    assert series.empty and not urls
    assert "price index only" in series.attrs["errors"][0]


# ---------------------------------------------------------------- the model
def test_an_exposure_defaults_to_an_nse_index():
    exposure = Exposure(id="auto", name="Auto", category="sector", benchmark="Nifty Auto")
    assert exposure.index_provider is IndexProvider.NSE


def test_a_bse_exposure_needs_its_provider_identifiers():
    with pytest.raises(ValidationError, match="index_source_id and index_code"):
        Exposure(id="insurance", name="Insurance", category="thematic", benchmark="BSE Insurance",
                 index_provider="bse")
    with pytest.raises(ValidationError, match="BSE indices only"):
        Exposure(id="auto", name="Auto", category="sector", benchmark="Nifty Auto", index_code="INSURE")


def test_the_shipped_bse_exposures_are_fully_identified():
    from src.universe.registry import UniverseRegistry

    root = Path(__file__).resolve().parents[1]
    registry = UniverseRegistry.from_json(root / "data" / "universe" / "universe.json")
    bse_ids = {e.id: (e.index_source_id, e.index_code) for e in registry.all() if e.index_provider is IndexProvider.BSE}
    assert bse_ids == {"insurance": (154, "INSURE"), "hospitals": (158, "BSHOSP")}
    for exposure_id in bse_ids:
        exposure = registry.get(exposure_id)
        assert exposure.launch_date and exposure.base_date and "bseindices.com" in exposure.dates_source
        assert exposure.etfs and all(v.isin and v.inception_date for v in exposure.etfs)


# ------------------------------------------------------------- the pipeline
def test_bse_exposures_are_fetched_from_bse_and_kept_as_authoritative(monkeypatch, tmp_path):
    """BSE indices go to the BSE fetcher by id and code, land in the store, and stay in the panel."""
    import pipeline.run_pipeline as rp
    import src.data.ingest as ingest
    from src.config import load_strategy_config
    from src.universe.registry import UniverseRegistry

    calls: list[dict] = []

    def make(provider):
        def fetch(name, start, end, calendar=None, value_types=("TRI", "CLOSE"), min_observations=60, **ids):
            calls.append({"provider": provider, "name": name, "value_types": value_types, **ids})
            index = pd.bdate_range(start, end)
            series = pd.Series(1000.0 + (index - index[0]).days.to_numpy(), index=index, name=name)
            if provider == "bse":
                series.attrs.update(source="bseindices", value_type="CLOSE", index_code=ids["index_code"])
            else:
                series.attrs.update(source="niftyindices_jugaad", value_type="TRI")
            return series

        return fetch

    monkeypatch.setattr(ingest, "_fetcher", lambda provider="nse": make(provider))
    monkeypatch.setattr(rp, "fetch_etf_histories", lambda etfs, years: (pd.DataFrame(), {}, {}))
    monkeypatch.setattr(
        rp, "ingest_cash",
        lambda store, code, name, fetch=None: (pd.Series(dtype=float, name="nav"),
                                               ingest.SeriesIngest(str(code), "seed", error="offline")),
    )
    registry = UniverseRegistry.from_json(rp.UNIVERSE_PATH)
    prices, _, _, _, _, health = rp.build_live(
        registry, load_strategy_config(), store_root=tmp_path, today=date(2026, 9, 30)
    )

    bse_calls = {c["name"]: c for c in calls if c["provider"] == "bse"}
    assert set(bse_calls) == {"BSE Insurance", "BSE Hospitals"}
    assert bse_calls["BSE Insurance"]["source_id"] == 154
    assert bse_calls["BSE Hospitals"]["index_code"] == "BSHOSP"
    assert not any(c["name"].startswith("BSE") for c in calls if c["provider"] == "nse")
    for eid in ("insurance", "hospitals"):
        assert eid in prices.columns
        assert health["source_by_canonical_exposure"][eid] == "bseindices"
        assert health["value_type_by_canonical_exposure"][eid] == "CLOSE"
        assert (tmp_path / "index" / eid).exists()
    assert health["source_by_canonical_exposure"]["auto"] == "niftyindices_jugaad"
    assert health["source_counts"]["bseindices"] == 2


def test_the_fixture_build_labels_bse_exposures_as_price_indices():
    import pipeline.run_pipeline as rp
    from src.universe.registry import UniverseRegistry

    *_, health = rp.build_fixture(UniverseRegistry.from_json(rp.UNIVERSE_PATH), days=300)
    assert health["value_type_by_canonical_exposure"]["hospitals"] == "CLOSE"
    assert health["source_by_canonical_exposure"]["insurance"] == "bseindices"
    assert health["value_type_by_canonical_exposure"]["auto"] == "TRI"
