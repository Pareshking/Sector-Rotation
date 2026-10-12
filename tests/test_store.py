"""The append-only raw store and the store-and-merge ingestion built on it."""

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

from src.data.calendar import TradingCalendar
from src.data.ingest import (
    INCREMENTAL,
    SEED,
    STORED,
    ingest_cash,
    ingest_vehicles,
    update_index,
)
from src.data.store import RawStore, SeriesMismatch, panel

INDEX = pd.bdate_range("2025-11-03", "2026-02-27")


def _series(index=INDEX, start: float = 100.0) -> pd.Series:
    return pd.Series([start + i for i in range(len(index))], index=index, dtype=float)


@pytest.fixture
def store(tmp_path) -> RawStore:
    return RawStore(tmp_path)


# --------------------------------------------------------------------------- #
# Layout and append-only semantics
# --------------------------------------------------------------------------- #
def test_partitions_are_one_file_per_calendar_year(store, tmp_path):
    store.merge("index", "auto", _series(), "TRI", "niftyindices_jugaad")
    files = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.parquet"))
    assert files == ["index/auto/2025.parquet", "index/auto/2026.parquet"]
    rows = pd.read_parquet(tmp_path / "index" / "auto" / "2025.parquet")
    assert list(rows.columns) == ["date", "value", "value_type", "source", "fetched_at"]
    assert (rows["date"].dt.year == 2025).all()


def test_reading_back_returns_the_series_with_its_type_and_source(store):
    store.merge("index", "auto", _series(), "TRI", "niftyindices_jugaad")
    back = store.series("index", "auto")
    pd.testing.assert_series_equal(back, _series().rename("auto"), check_freq=False)
    assert back.attrs == {"value_type": "TRI", "source": "niftyindices_jugaad"}
    assert store.last_date("index", "auto") == INDEX[-1]
    assert store.ids("index") == ["auto"]


def test_an_empty_store_has_no_history(store):
    assert store.series("index", "nope").empty
    assert store.last_date("index", "nope") is None
    assert store.window_start("index", "nope") is None


def test_merging_the_same_data_again_adds_no_rows(store):
    store.merge("index", "auto", _series(), "TRI", "x")
    result = store.merge("index", "auto", _series(), "TRI", "x")
    assert result.new_sessions == 0 and result.unchanged_overlap == len(INDEX)
    assert len(store.rows("index", "auto")) == len(INDEX)


def test_new_sessions_are_appended_and_nothing_is_dropped(store):
    full = _series()
    store.merge("index", "auto", full.iloc[:60], "TRI", "x")
    result = store.merge("index", "auto", full.iloc[50:], "TRI", "x")  # 10-session overlap
    assert result.new_sessions == len(INDEX) - 60
    assert result.unchanged_overlap == 10
    back = store.series("index", "auto")
    assert back.index.min() == INDEX[0] and back.index.max() == INDEX[-1]
    assert len(store.rows("index", "auto")) == len(INDEX)


def test_a_restated_value_is_appended_and_recorded_never_overwritten(store):
    store.merge("index", "auto", _series(), "TRI", "x", fetched_at=pd.Timestamp("2026-03-01", tz="UTC"))
    revised = _series().copy()
    revised.iloc[-3] += 2.5  # NSE corrects one close
    result = store.merge("index", "auto", revised.iloc[-10:], "TRI", "x", fetched_at=pd.Timestamp("2026-03-02", tz="UTC"))
    assert len(result.restatements) == 1
    item = result.restatements[0]
    assert item.date == INDEX[-3] and item.fetched - item.stored == pytest.approx(2.5)
    assert item.as_dict()["date"] == f"{INDEX[-3]:%Y-%m-%d}"
    rows = store.rows("index", "auto")
    versions = rows[rows["date"] == INDEX[-3]]
    assert len(versions) == 2  # the original is kept
    assert store.series("index", "auto")[INDEX[-3]] == pytest.approx(revised.iloc[-3])  # the latest wins


def test_rounding_noise_is_not_a_restatement(store):
    store.merge("index", "auto", _series(), "TRI", "x")
    noisy = _series() + 0.001
    assert store.merge("index", "auto", noisy, "TRI", "x").restatements == []


def test_a_different_value_type_is_refused(store):
    """A TRI history is never continued with a price index."""
    store.merge("index", "auto", _series(), "TRI", "x")
    with pytest.raises(SeriesMismatch, match="stored as TRI"):
        store.merge("index", "auto", _series(pd.bdate_range("2026-03-02", periods=5)), "CLOSE", "x")


def test_a_wholly_different_series_is_refused_as_a_discontinuity(store):
    """Most of the overlap moving by >2% is another series (a swapped response), not a correction."""
    store.merge("index", "auto", _series(), "TRI", "x")
    other = _series(start=5000.0).iloc[-10:]
    with pytest.raises(SeriesMismatch, match="different series"):
        store.merge("index", "auto", other, "TRI", "x")
    assert len(store.rows("index", "auto")) == len(INDEX)


def test_the_incremental_window_starts_overlap_sessions_before_the_last_stored(store):
    store.merge("index", "auto", _series(), "TRI", "x")
    assert store.window_start("index", "auto", 10) == INDEX[-11]
    holiday_calendar = TradingCalendar(INDEX.drop(INDEX[-2]))
    assert store.window_start("index", "auto", 10, holiday_calendar) == INDEX[-12]


def test_unsafe_ids_and_unknown_kinds_are_rejected(store):
    with pytest.raises(ValueError, match="unsafe"):
        store.merge("index", "../etc", _series(), "TRI", "x")
    with pytest.raises(ValueError, match="unknown store kind"):
        store.series("prices", "auto")


def test_panel_assembles_current_series(store):
    store.merge("index", "a", _series(), "TRI", "x")
    store.merge("index", "b", _series(INDEX[10:]), "TRI", "x")
    frame = panel(store, "index", ["a", "b", "missing"])
    assert list(frame.columns) == ["a", "b"]
    assert frame["b"].first_valid_index() == INDEX[10]


# --------------------------------------------------------------------------- #
# Ingestion on top of the store
# --------------------------------------------------------------------------- #
def _nse(calls, fail=False, value_type="TRI", bump=None):
    def fetch(name, start, end, calendar=None, value_types=("TRI", "CLOSE"), min_observations=60):
        calls.append({"start": pd.Timestamp(start), "value_types": value_types, "min_observations": min_observations})
        if fail:
            empty = pd.Series(dtype=float)
            empty.attrs["errors"] = ["TRI: Timeout: slow"]
            return empty
        index = pd.bdate_range(start, end)
        out = pd.Series([1000.0 + (d - pd.Timestamp("2020-01-01")).days for d in index], index=index)
        if bump is not None and bump in out.index:
            out[bump] += 7.0
        out.attrs.update(value_type=value_type, source="niftyindices_jugaad")
        return out

    return fetch


def test_an_empty_store_is_seeded_with_the_full_history(store):
    calls = []
    current, report = update_index(store, "auto", "NIFTY AUTO", date(2026, 2, 27), seed_years=1, fetch=_nse(calls))
    assert report.mode == SEED
    assert calls[0]["value_types"] == ("TRI", "CLOSE")  # a fresh series may fall back to the price index
    assert calls[0]["start"] == pd.Timestamp(date(2026, 2, 27)) - pd.Timedelta(days=375)
    assert report.new_sessions == len(current) > 250


def test_the_next_run_fetches_only_the_overlap_and_new_sessions(store):
    calls = []
    update_index(store, "auto", "NIFTY AUTO", date(2026, 2, 27), seed_years=1, fetch=_nse(calls))
    calls.clear()
    current, report = update_index(store, "auto", "NIFTY AUTO", date(2026, 3, 6), seed_years=1, fetch=_nse(calls))
    assert report.mode == INCREMENTAL and report.new_sessions == 5
    assert calls[0]["start"] == pd.Timestamp("2026-02-13")  # 10 sessions before 27 Feb
    assert calls[0]["value_types"] == ("TRI",) and calls[0]["min_observations"] == 1
    assert current.index.max() == pd.Timestamp("2026-03-06")


def test_a_failed_fetch_keeps_the_stored_history(store):
    update_index(store, "auto", "NIFTY AUTO", date(2026, 2, 27), seed_years=1, fetch=_nse([]))
    before = store.series("index", "auto")
    current, report = update_index(store, "auto", "NIFTY AUTO", date(2026, 3, 6), fetch=_nse([], fail=True))
    assert report.mode == STORED and "Timeout" in report.error
    pd.testing.assert_series_equal(current, before)


def test_restatements_in_the_overlap_are_reported(store):
    update_index(store, "auto", "NIFTY AUTO", date(2026, 2, 27), seed_years=1, fetch=_nse([]))
    _, report = update_index(
        store, "auto", "NIFTY AUTO", date(2026, 3, 6), fetch=_nse([], bump=pd.Timestamp("2026-02-20"))
    )
    assert [r["date"] for r in report.restatements] == ["2026-02-20"]


def test_a_benchmark_that_starts_late_is_rejected(store):
    """The benchmark is the calendar; a missing first chunk cannot be checked against itself."""

    def late(name, start, end, calendar=None, **_):
        index = pd.bdate_range(pd.Timestamp(start) + pd.Timedelta(days=120), end)
        out = pd.Series(1.0, index=index)
        out.attrs.update(value_type="TRI", source="niftyindices_jugaad")
        return out

    current, report = update_index(
        store, "nifty-50", "NIFTY 50", date(2026, 2, 27), seed_years=1, fetch=late, is_benchmark=True
    )
    assert current.empty and "days after the requested start" in report.error


def test_a_vehicle_missing_from_tonights_fetch_keeps_its_history(store):
    keys = {"AUTOBEES": 149465, "HDFC Auto Fund": 154427}
    night1 = pd.DataFrame({"AUTOBEES": _series(), "HDFC Auto Fund": _series(start=50.0)})
    ingest_vehicles(store, night1, {"AUTOBEES": "mfapi", "HDFC Auto Fund": "mfapi"}, keys)
    night2 = pd.DataFrame({"HDFC Auto Fund": _series(start=50.0)})  # AUTOBEES failed tonight
    frame, reports = ingest_vehicles(store, night2, {"HDFC Auto Fund": "mfapi"}, keys)
    assert reports["AUTOBEES"].mode == STORED
    pd.testing.assert_series_equal(frame["AUTOBEES"].dropna(), _series().rename("AUTOBEES"), check_freq=False)
    assert (store.root / "vehicle" / "149465").exists()


def _mfapi(name: str, nav: pd.Series):
    return lambda code: SimpleNamespace(scheme_name=name, frame=nav.to_frame("close"))


def test_the_cash_series_is_refused_unless_the_scheme_name_matches(store):
    """The spec's code 119598 is an equity fund; a wrong code must never become the cash return."""
    nav = pd.Series([10.0, 10.001], index=pd.DatetimeIndex(["2026-01-01", "2026-01-02"]))
    cash, report = ingest_cash(store, 119598, "Nippon India Liquid Fund - Direct Plan - Growth Option",
                               fetch=_mfapi("SBI Large Cap Fund - Direct Plan - Growth", nav))
    assert cash.empty and "refusing it as the cash return" in report.error


def test_the_cash_series_is_stored_and_returned(store):
    nav = pd.Series([2798.271, 2798.80], index=pd.DatetimeIndex(["2013-01-01", "2013-01-02"]))
    name = "Nippon India Liquid Fund - Direct Plan - Growth Option"
    cash, report = ingest_cash(store, 118701, name, fetch=_mfapi(name, nav))
    assert cash.name == "nav" and len(cash) == 2 and not report.error
    assert store.series("vehicle", "118701").attrs["value_type"] == "NAV"
