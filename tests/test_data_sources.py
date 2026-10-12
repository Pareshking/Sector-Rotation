from datetime import date

import pandas as pd
import pytest
import requests

import src.data.jugaad_indices as jugaad
from src.data.canonical import promote_etf_histories
from src.data.index_data import download_canonical_indices


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch):
    """Retries back off for real seconds in production; record them here instead."""
    sleeps: list[float] = []
    monkeypatch.setattr(jugaad, "_sleep", sleeps.append)
    return sleeps


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
        lambda names, years, workers, calendar=None: (
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


# --------------------------------------------------------------------------- #
# Retries, completeness and the shared-client race
# --------------------------------------------------------------------------- #
START, END = date(2026, 1, 1), date(2026, 9, 4)
CALENDAR = pd.bdate_range(START, END)


def _rows_on(dates, column: str = "Date", key: str = "TRI") -> list[dict[str, str]]:
    return [{column: d.strftime("%d %b %Y"), key: f"{20000 + i:.2f}"} for i, d in enumerate(dates)]


def _without_second_chunk() -> list[dict[str, str]]:
    """A response with one 90-day request chunk silently missing."""
    from jugaad_data.util import break_dates

    lo, hi = break_dates(START, END)[1]
    keep = CALENDAR[(CALENDAR < pd.Timestamp(lo)) | (CALENDAR > pd.Timestamp(hi))]
    return _rows_on(keep)


def _sequence(*outcomes):
    """A fake endpoint that raises or returns each outcome in turn, then repeats the last."""
    calls = []

    def endpoint(*args):
        outcome = outcomes[min(len(calls), len(outcomes) - 1)]
        calls.append(args)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    return endpoint, calls


def test_transient_failures_are_retried_with_exponential_backoff(monkeypatch, _no_backoff_sleep):
    tri, calls = _sequence(requests.ConnectionError("reset"), requests.Timeout("slow"), _rows_on(CALENDAR))
    monkeypatch.setattr(jugaad, "index_tri_raw", tri)
    monkeypatch.setattr(jugaad, "index_raw", lambda *a: pytest.fail("price endpoint must not be needed"))
    series = jugaad.fetch_jugaad_index("NIFTY 50", START, END, calendar=CALENDAR)
    assert series.attrs["value_type"] == "TRI"
    assert len(calls) == 3
    assert _no_backoff_sleep == [2.0, 4.0]


def test_a_non_json_block_page_is_treated_as_transient(monkeypatch, _no_backoff_sleep):
    tri, calls = _sequence(ValueError("Expecting value: line 1 column 1"), _rows_on(CALENDAR))
    monkeypatch.setattr(jugaad, "index_tri_raw", tri)
    series = jugaad.fetch_jugaad_index("NIFTY 50", START, END, calendar=CALENDAR)
    assert series.attrs["value_type"] == "TRI"
    assert len(calls) == 2


def test_retries_are_bounded_then_the_price_index_is_tried(monkeypatch, _no_backoff_sleep):
    tri, tri_calls = _sequence(requests.ConnectionError("down"))
    monkeypatch.setattr(jugaad, "index_tri_raw", tri)
    monkeypatch.setattr(jugaad, "index_raw", lambda *a: _rows_on(CALENDAR, "HistoricalDate", "CLOSE"))
    series = jugaad.fetch_jugaad_index("NIFTY CEMENT", START, END, calendar=CALENDAR)
    assert len(tri_calls) == jugaad.RETRY_ATTEMPTS
    assert series.attrs["value_type"] == "CLOSE"


def test_a_defect_is_logged_and_not_retried(monkeypatch, caplog, _no_backoff_sleep):
    """Only network-shaped failures are retried; a KeyError will not fix itself."""
    tri, calls = _sequence(KeyError("unexpected payload shape"))
    monkeypatch.setattr(jugaad, "index_tri_raw", tri)
    monkeypatch.setattr(jugaad, "index_raw", lambda *a: _rows_on(CALENDAR, "HistoricalDate", "CLOSE"))
    with caplog.at_level("ERROR", logger="src.data.jugaad_indices"):
        series = jugaad.fetch_jugaad_index("NIFTY AUTO", START, END, calendar=CALENDAR)
    assert len(calls) == 1
    assert _no_backoff_sleep == []
    assert any("non-retryable" in r.getMessage() for r in caplog.records)
    assert series.attrs["value_type"] == "CLOSE"


def test_a_missing_chunk_is_caught_against_the_benchmark_calendar(monkeypatch):
    """The TRI response lacks one 90-day chunk: it must be rejected, not accepted with a hole."""
    monkeypatch.setattr(jugaad, "index_tri_raw", lambda *a: _without_second_chunk())
    monkeypatch.setattr(jugaad, "index_raw", lambda *a: _rows_on(CALENDAR, "HistoricalDate", "CLOSE"))
    series = jugaad.fetch_jugaad_index("NIFTY AUTO", START, END, calendar=CALENDAR)
    assert series.attrs["value_type"] == "CLOSE"
    assert len(series) == len(CALENDAR)


def test_a_truncated_chunk_that_recovers_on_retry_is_accepted(monkeypatch, _no_backoff_sleep):
    tri, calls = _sequence(_without_second_chunk(), _rows_on(CALENDAR))
    monkeypatch.setattr(jugaad, "index_tri_raw", tri)
    series = jugaad.fetch_jugaad_index("NIFTY AUTO", START, END, calendar=CALENDAR)
    assert series.attrs["value_type"] == "TRI"
    assert len(calls) == 2
    assert _no_backoff_sleep == [2.0]


def test_when_no_endpoint_is_complete_the_series_is_empty_and_says_why(monkeypatch):
    monkeypatch.setattr(jugaad, "index_tri_raw", lambda *a: _without_second_chunk())
    monkeypatch.setattr(jugaad, "index_raw", lambda *a: [])
    series = jugaad.fetch_jugaad_index("NIFTY AUTO", START, END, calendar=CALENDAR)
    assert series.empty
    errors = series.attrs["errors"]
    assert errors[0].startswith("TRI: IncompleteSeries") and "chunk" in errors[0]
    assert errors[1].startswith("CLOSE: IncompleteSeries")


def _complete(dates=CALENDAR) -> pd.Series:
    return pd.Series(range(1, len(dates) + 1), index=dates, dtype=float)


def test_a_complete_series_has_no_completeness_problems():
    assert jugaad.completeness_problems(_complete(), START, END, CALENDAR) == []


def test_a_one_session_lag_and_a_single_missing_date_are_tolerated():
    """The newest close can lag the benchmark by a day; NSE occasionally omits one date."""
    series = _complete().drop([CALENDAR[-1], CALENDAR[40]])
    assert jugaad.completeness_problems(series, START, END, CALENDAR) == []


def test_a_thinned_chunk_is_reported_even_without_any_long_hole():
    """Every other session missing: no gap exceeds a long weekend, but the chunk is truncated."""
    series = _complete().drop(CALENDAR[66:126:2])
    assert series.index.to_series().diff().dt.days.max() <= 4
    problems = jugaad.completeness_problems(series, START, END, CALENDAR)
    assert problems and all("benchmark sessions" in p for p in problems)


def test_a_dropped_block_is_reported_as_a_hole_and_a_short_chunk():
    series = _complete().drop(CALENDAR[70:100])
    problems = jugaad.completeness_problems(series, START, END, CALENDAR)
    assert any("hole" in p for p in problems)
    assert any("benchmark sessions" in p for p in problems)


def test_a_missing_newest_chunk_is_reported():
    """The latest chunk matters most and is the easiest to lose quietly."""
    series = _complete()[_complete().index < pd.Timestamp("2026-08-01")]
    assert jugaad.completeness_problems(series, START, END, CALENDAR)


def test_a_long_hole_is_reported_even_without_a_calendar():
    series = _complete().drop(CALENDAR[50:70])
    problems = jugaad.completeness_problems(series, START, END)
    assert any("hole" in p for p in problems)


def test_an_index_launched_inside_the_window_is_not_penalised():
    launched = _complete(CALENDAR[CALENDAR >= pd.Timestamp("2026-04-15")])
    assert jugaad.completeness_problems(launched, START, END, CALENDAR) == []


class _Response:
    def __init__(self, payload, status: int = 200) -> None:
        self.payload, self.status_code = payload, status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def json(self):
        return self.payload


def test_the_index_client_parses_its_own_response_not_the_shared_one(monkeypatch):
    """Upstream parses self.r, which a concurrent request may already have replaced."""
    client = jugaad._IndexClient()
    mine = _Response([{"Date": "01 Sep 2026", "TRI": "100"}])
    other = _Response([{"Date": "01 Sep 2026", "TRI": "999999"}])

    def post(path_name, params):
        client.r = other  # what another thread's request leaves behind upstream
        return mine

    monkeypatch.setattr(client, "_post_json", post)
    assert client._index_tri("NIFTY 50", "NIFTY 50", START, END) == mine.payload
    assert client._index("NIFTY 50", START, END) == mine.payload


def test_the_index_client_does_not_cache_chunks(monkeypatch):
    """A cached truncated chunk would turn every retry into a re-read of the same bad data."""
    client = jugaad._IndexClient()
    responses = iter([_Response([{"n": 1}]), _Response([{"n": 2}])])
    monkeypatch.setattr(client, "_post_json", lambda path_name, params: next(responses))
    assert client._index_tri("NIFTY 50", "NIFTY 50", START, END) == [{"n": 1}]
    assert client._index_tri("NIFTY 50", "NIFTY 50", START, END) == [{"n": 2}]


def test_an_http_error_status_raises_a_retryable_error(monkeypatch):
    client = jugaad._IndexClient()
    monkeypatch.setattr(client, "_post_json", lambda path_name, params: _Response([], status=503))
    with pytest.raises(requests.HTTPError):
        client._index("NIFTY 50", START, END)
    assert issubclass(requests.HTTPError, jugaad.RETRYABLE)


def test_each_thread_gets_its_own_client_and_fetches_chunks_in_order():
    import threading

    seen = []
    worker = threading.Thread(target=lambda: seen.append(jugaad._client()))
    worker.start()
    worker.join()
    mine = jugaad._client()
    assert mine is jugaad._client()
    assert seen[0] is not mine
    assert mine.workers == 1


def test_canonical_fetch_records_why_an_index_did_not_resolve(monkeypatch):
    def fetch(name, start, end, calendar=None):
        if name == "NIFTY AUTO":
            series = _complete().rename(name)
            series.attrs.update(source="niftyindices_jugaad", resolved_name=name, value_type="TRI")
            return series
        empty = pd.Series(dtype="float64", name=name)
        empty.attrs["errors"] = ["TRI: ConnectionError: down", "CLOSE: ConnectionError: down"]
        return empty

    monkeypatch.setattr(jugaad, "fetch_jugaad_index", fetch)
    prices, sources, _, _ = jugaad.fetch_jugaad_canonical_indices(
        {"auto": "NIFTY AUTO", "bank": "NIFTY BANK"}, years=1, workers=2, calendar=CALENDAR
    )
    assert list(prices.columns) == ["auto"]
    assert set(sources) == {"auto"}
    assert prices.attrs["fetch_errors"] == {
        "bank": "TRI: ConnectionError: down; CLOSE: ConnectionError: down"
    }


def test_the_calendar_and_fetch_errors_flow_through_download(monkeypatch):
    received = {}

    def fetch(names, years, workers, calendar=None):
        received["calendar"] = calendar
        frame = pd.DataFrame({"auto": _complete()})
        frame.attrs["fetch_errors"] = {"bank": "TRI: Timeout: slow"}
        return frame, {"auto": "niftyindices_jugaad"}, {"auto": "NIFTY AUTO"}, {"auto": "TRI"}

    monkeypatch.setattr("src.data.index_data.fetch_jugaad_canonical_indices", fetch)
    prices = download_canonical_indices({"auto": "NIFTY AUTO", "bank": "NIFTY BANK"}, years=1, calendar=CALENDAR)
    assert received["calendar"] is CALENDAR
    assert prices.attrs["fetch_errors"] == {"bank": "TRI: Timeout: slow"}


def test_a_benchmark_that_starts_late_is_rejected(monkeypatch):
    """The benchmark is the calendar; a missing first chunk cannot be checked against itself."""
    late = _complete(pd.bdate_range("2026-04-01", END))
    late.attrs.update(source="niftyindices_jugaad", resolved_name="NIFTY 50", value_type="TRI")
    monkeypatch.setattr(jugaad, "fetch_jugaad_index", lambda name, start, end, calendar=None: late)
    series = jugaad.fetch_benchmark("NIFTY 50", years=1)
    assert series.empty
    assert "days late" in series.attrs["errors"][0]
