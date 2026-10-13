import numpy as np
import pandas as pd

from src.portfolio.book import ModelBook, monthly_returns
from src.portfolio.record import RECORDED, apply_record, extend_record, read_record


def _book(values, start="2026-10-01"):
    idx = pd.bdate_range(start, periods=len(values))
    equity = pd.Series(values, index=idx, dtype=float)
    bench = equity * 0.5
    return ModelBook(1.0, idx[-1], idx[0], equity, bench, 0.0, pd.DataFrame(), pd.DataFrame(),
                     pd.DataFrame(), monthly_returns(equity, bench))


def test_only_closed_months_from_start_are_recorded():
    book = _book(np.linspace(100, 130, 70))  # Oct, Nov, Dec 2026 and part of Jan 2027
    record = extend_record(read_record("does-not-exist.csv"), book.monthly, "2027-01-05")
    assert list(record["Period"]) == ["2026-11", "2026-12"]  # not Oct (before start), not Jan (running)


def test_recorded_months_are_never_rewritten():
    book = _book(np.linspace(100, 130, 70))
    record = extend_record(read_record("none.csv"), book.monthly, "2027-01-05")
    revised = _book(np.linspace(100, 160, 70))
    again = extend_record(record, revised.monthly, "2027-01-06")
    pd.testing.assert_frame_equal(record, again)


def test_book_is_pinned_to_the_record():
    book = _book(np.linspace(100, 130, 70))
    record = extend_record(read_record("none.csv"), book.monthly, "2027-01-05")
    revised = _book(np.linspace(100, 160, 70))  # a later data revision
    pinned = apply_record(revised, record)
    nov = pinned.monthly.set_index("Period").loc["2026-11"]
    assert nov["Origin"] == RECORDED
    assert np.isclose(nov["Strategy"], record.set_index("Period").loc["2026-11", "Strategy"])
    assert np.isclose(nov["Benchmark"], record.set_index("Period").loc["2026-11", "Benchmark"])
    assert pinned.monthly.set_index("Period").loc["2026-10", "Origin"] == "Backfilled"
    assert pinned.monthly["Origin"].iloc[-1] == "MTD"
    # October is untouched by the record.
    assert np.isclose(pinned.equity.iloc[0], revised.equity.iloc[0])


def test_empty_record_leaves_the_book_alone():
    book = _book(np.linspace(100, 130, 70))
    assert apply_record(book, read_record("none.csv")) is book
