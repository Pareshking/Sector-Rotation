"""Forward recording: each closed month of the model book, frozen once.

The model book (``book.py``) is a fresh replay on every load, so a revised
NAV or index value can quietly rewrite a month already shown. From Nov 2026
each month is written to an append-only record once it has closed (a later
month exists in the book), and a month in the record is never changed again.

The book is then pinned to the record: inside a recorded month the curve
keeps the replay's daily shape, but the month ends exactly where the
recorded return puts it, and every later session is chained from there.
Those months are labelled "Recorded"; earlier ones stay "Backfilled".
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pandas as pd

from src.portfolio.book import BACKFILLED, ModelBook, monthly_returns

# Owner, 14 Oct 2026: months are recorded from Nov 2026.
RECORD_FROM = "2026-11"
RECORDED = "Recorded"
RECORD_COLUMNS = ["Period", "Strategy", "Benchmark", "Recorded on"]


def read_record(path: Path) -> pd.DataFrame:
    if not Path(path).exists():
        return pd.DataFrame(columns=RECORD_COLUMNS)
    frame = pd.read_csv(path, dtype={"Period": str})
    return frame[RECORD_COLUMNS]


def extend_record(record: pd.DataFrame, monthly: pd.DataFrame, recorded_on: str,
                  start: str = RECORD_FROM) -> pd.DataFrame:
    """``record`` plus every closed month from ``start`` it lacks; existing rows untouched.

    A month is closed once a later month exists in ``monthly``: its last
    session is then behind the book, and the running month is never recorded.
    """
    if monthly is None or len(monthly) < 2:
        return record.copy()
    have = set(record["Period"].astype(str))
    closed = monthly.iloc[:-1]
    closed = closed[(closed["Origin"] == BACKFILLED)
                    & (pd.PeriodIndex(closed["Period"], freq="M") >= pd.Period(start, freq="M"))
                    & ~closed["Period"].astype(str).isin(have)]
    if closed.empty:
        return record.copy()
    new = closed[["Period", "Strategy", "Benchmark"]].assign(**{"Recorded on": recorded_on})
    out = pd.concat([record, new], ignore_index=True) if not record.empty else new.reset_index(drop=True)
    return out[RECORD_COLUMNS].sort_values("Period").reset_index(drop=True)


def _pin(series: pd.Series, recorded: dict[str, float]) -> pd.Series:
    """``series`` re-chained so each recorded month returns exactly its recorded figure."""
    if series.empty or not recorded:
        return series
    values = series.astype(float).to_numpy().copy()
    months = series.index.to_period("M").astype(str)
    prev_pinned = prev_raw = float(series.iloc[0])
    start = 0
    n = len(values)
    while start < n:
        end = start
        while end + 1 < n and months[end + 1] == months[start]:
            end += 1
        raw = series.iloc[start:end + 1].astype(float).to_numpy()
        values[start:end + 1] = prev_pinned * raw / prev_raw
        if months[start] in recorded:
            values[end] = prev_pinned * (1.0 + recorded[months[start]])
        prev_pinned, prev_raw = float(values[end]), float(raw[-1])
        start = end + 1
    return pd.Series(values, index=series.index, name=series.name)


def apply_record(book: ModelBook, record: pd.DataFrame) -> ModelBook:
    """The book with its recorded months frozen at their recorded returns."""
    if not book.ok or record is None or record.empty:
        return book
    strategy = dict(zip(record["Period"].astype(str), record["Strategy"].astype(float)))
    benchmark = dict(zip(record["Period"].astype(str), record["Benchmark"].astype(float)))
    equity = _pin(book.equity, strategy)
    bench = _pin(book.benchmark.reindex(book.equity.index).ffill(), benchmark)
    monthly = monthly_returns(equity, bench)
    monthly.loc[monthly["Period"].isin(strategy.keys()), "Origin"] = RECORDED
    return dataclasses.replace(book, equity=equity, benchmark=bench, monthly=monthly)


__all__ = ["RECORDED", "RECORD_FROM", "apply_record", "extend_record", "read_record"]
