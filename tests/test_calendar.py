import pandas as pd

from src.data.calendar import TradingCalendar
from src.data.jugaad_indices import completeness_problems
from src.portfolio.calendar import fill_date

# 2 Oct 2026 (Gandhi Jayanti) is an NSE holiday: the benchmark has no value that day.
SESSIONS = pd.bdate_range("2026-09-21", "2026-10-09").drop(pd.Timestamp("2026-10-02"))
BENCHMARK = pd.Series(range(len(SESSIONS)), index=SESSIONS, dtype=float)
CAL = TradingCalendar.from_series(BENCHMARK)


def test_the_calendar_is_the_benchmarks_sessions():
    assert CAL.sessions.equals(SESSIONS)
    assert len(CAL) == len(SESSIONS)
    assert (CAL.first, CAL.last) == (SESSIONS[0], SESSIONS[-1])


def test_construction_sorts_dedups_and_drops_gaps():
    messy = pd.Series([1.0, None, 2.0, 3.0], index=pd.DatetimeIndex(["2026-10-05", "2026-10-02", "2026-10-01", "2026-10-05"]))
    cal = TradingCalendar.from_series(messy)
    assert list(cal.sessions) == [pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-05")]


def test_a_holiday_is_not_a_session():
    assert CAL.is_session("2026-10-01")
    assert not CAL.is_session("2026-10-02")
    assert not CAL.is_session("2026-10-03")  # Saturday


def test_the_next_session_skips_holidays_and_weekends():
    """A signal at the 1 Oct close fills at the 5 Oct close: 2 Oct is a holiday, then a weekend."""
    assert CAL.next_session("2026-10-01") == pd.Timestamp("2026-10-05")
    assert CAL.next_session("2026-09-30") == pd.Timestamp("2026-10-01")
    assert CAL.next_session("2026-10-09") is None
    assert fill_date(SESSIONS, pd.Timestamp("2026-10-01")) == CAL.next_session("2026-10-01")


def test_previous_and_on_or_before():
    assert CAL.previous_session("2026-10-05") == pd.Timestamp("2026-10-01")
    assert CAL.session_on_or_before("2026-10-03") == pd.Timestamp("2026-10-01")
    assert CAL.session_on_or_before("2026-09-01") is None
    assert CAL.previous_session(SESSIONS[0]) is None


def test_counting_sessions_back():
    assert CAL.sessions_back("2026-10-09", 4) == pd.Timestamp("2026-10-05")
    assert CAL.sessions_back("2026-10-10", 4) == pd.Timestamp("2026-10-05")  # anchored on 9 Oct
    assert CAL.sessions_back("2026-10-09", 999) == SESSIONS[0]  # clipped, never before the data


def test_between_is_inclusive():
    window = CAL.between("2026-10-01", "2026-10-06")
    assert list(window) == [pd.Timestamp(d) for d in ("2026-10-01", "2026-10-05", "2026-10-06")]


def test_missing_sessions_are_counted_from_the_series_first_value():
    series = pd.Series(1.0, index=SESSIONS.drop(pd.Timestamp("2026-10-06")))
    assert list(CAL.missing(series)) == [pd.Timestamp("2026-10-06")]
    late = series.loc["2026-10-01":]
    assert list(CAL.missing(late)) == [pd.Timestamp("2026-10-06")]  # not the sessions before its start
    assert len(CAL.missing(pd.Series(dtype=float), "2026-10-01", "2026-10-09")) == 6


def test_the_holiday_does_not_count_as_a_missing_session():
    exposure = BENCHMARK.copy()
    assert CAL.missing(exposure).empty


def test_completeness_checks_accept_a_trading_calendar():
    from datetime import date

    long_sessions = pd.bdate_range("2026-01-01", "2026-09-30")
    cal = TradingCalendar(long_sessions)
    series = pd.Series(range(1, len(long_sessions) + 1), index=long_sessions, dtype=float)
    assert completeness_problems(series, date(2026, 1, 1), date(2026, 9, 30), cal) == []
    thinned = series.drop(long_sessions[66:126:2])
    assert completeness_problems(thinned, date(2026, 1, 1), date(2026, 9, 30), cal)
