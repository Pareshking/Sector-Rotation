"""NSE / NiftyIndices historical index retrieval through the jugaad-data adapter.

Provenance note: jugaad-data is a *retrieval adapter* over NSE's published index
history. It is not itself an authority, and the series it returns is not
automatically a Total Return Index. Each series therefore records which value
type was actually served — ``TRI`` when the total-return endpoint answered, or
``CLOSE`` when only the price-index endpoint did — so the UI can state what a
number is instead of implying total returns everywhere.
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Mapping

import pandas as pd

import src.data._jugaad_patches  # noqa: F401 — timeout + wider date-chunking, side effects only
from jugaad_data.nse import index_raw, index_tri_raw

MIN_OBSERVATIONS = 60

SOURCE = "niftyindices_jugaad"
VALUE_TRI = "TRI"
VALUE_CLOSE = "CLOSE"


# NSE serves dates as "28 Aug 2026". Letting pandas infer the format is not
# safe: with ``dayfirst=True`` and no explicit format, pandas 3.x resolves the
# format from the first row and then returns NaT for every later row whose
# day-of-month is <= 12, because those are ambiguous against a month-first
# reading. That silently deletes roughly 40% of an index history instead of
# raising. Trying explicit formats first removes the ambiguity entirely.
_DATE_FORMATS = ("%d %b %Y", "%d-%b-%Y", "%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d")


def _parse_dates(values: pd.Series) -> pd.Series:
    text = values.astype("string").str.strip()
    best = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    best_hits = 0
    for fmt in _DATE_FORMATS:
        parsed = pd.to_datetime(text, format=fmt, errors="coerce")
        hits = int(parsed.notna().sum())
        if hits > best_hits:
            best, best_hits = parsed, hits
        if best_hits == len(text):
            return best
    if best_hits < len(text):
        inferred = pd.to_datetime(text, errors="coerce", dayfirst=True, format="mixed")
        if int(inferred.notna().sum()) > best_hits:
            return inferred
    return best


def _records_to_series(name: str, records) -> pd.Series:
    if records is None:
        return pd.Series(dtype="float64", name=name)
    if isinstance(records, pd.DataFrame):
        frame = records.copy()
    elif isinstance(records, list):
        frame = pd.DataFrame(records)
    else:
        return pd.Series(dtype="float64", name=name)
    if frame.empty:
        return pd.Series(dtype="float64", name=name)

    date_col = next(
        (c for c in ("HistoricalDate", "Date", "Index Date", "EOD_TIMESTAMP") if c in frame.columns),
        None,
    )
    value_col = next(
        (
            c
            for c in ("TRI", "TotalReturnsIndex", "NTR_Value", "CLOSE", "Close", "Closing Index Value")
            if c in frame.columns
        ),
        None,
    )
    if date_col is None or value_col is None:
        return pd.Series(dtype="float64", name=name)

    dates = _parse_dates(frame[date_col])
    values = pd.to_numeric(
        frame[value_col].astype("string").str.replace(",", "", regex=False), errors="coerce"
    )
    valid = dates.notna() & values.notna() & values.gt(0)
    if not valid.any():
        return pd.Series(dtype="float64", name=name)
    series = pd.Series(
        values.loc[valid].to_numpy(float), index=pd.DatetimeIndex(dates.loc[valid]), name=name
    )
    return series.groupby(level=0).last().sort_index()


def fetch_jugaad_index(name: str, start: date, end: date) -> pd.Series:
    """Fetch one NSE index history. Total-return series preferred, price close accepted.

    ``series.attrs['value_type']`` records which of the two was actually served.
    """
    try:
        tri = _records_to_series(name, index_tri_raw(name, name, start, end))
        if len(tri) >= MIN_OBSERVATIONS:
            tri.attrs.update(source=SOURCE, resolved_name=name, value_type=VALUE_TRI)
            return tri
    except Exception:
        pass
    try:
        raw = _records_to_series(name, index_raw(name, start, end))
        if len(raw) >= MIN_OBSERVATIONS:
            raw.attrs.update(source=SOURCE, resolved_name=name, value_type=VALUE_CLOSE)
            return raw
    except Exception:
        pass
    return pd.Series(dtype="float64", name=name)


def fetch_jugaad_canonical_indices(
    exposure_names: Mapping[str, str],
    years: int = 5,
    workers: int = 4,
) -> tuple[pd.DataFrame, dict[str, str], dict[str, str], dict[str, str]]:
    """Return (prices, source_by_exposure, resolved_name_by_exposure, value_type_by_exposure)."""
    start = date.today() - timedelta(days=365 * years + 10)
    results: dict[str, pd.Series] = {}
    sources: dict[str, str] = {}
    resolved: dict[str, str] = {}
    value_types: dict[str, str] = {}
    t0 = time.time()
    total = len(exposure_names)
    print(f"[{time.strftime('%H:%M:%S')}] Canonical indices: fetching {total}...", file=sys.stderr, flush=True)

    def one(item):
        eid, name = item
        return eid, name, fetch_jugaad_index(name, start, date.today())

    done = 0
    with ThreadPoolExecutor(max_workers=min(workers, max(len(exposure_names), 1))) as pool:
        futures = [pool.submit(one, item) for item in exposure_names.items()]
        for future in as_completed(futures):
            done += 1
            try:
                eid, name, series = future.result()
            except Exception:
                continue
            if len(series) >= MIN_OBSERVATIONS:
                results[eid] = series.rename(eid)
                sources[eid] = series.attrs.get("source", SOURCE)
                resolved[eid] = series.attrs.get("resolved_name", name)
                value_types[eid] = series.attrs.get("value_type", VALUE_CLOSE)
            if done % 10 == 0 or done == total:
                print(
                    f"[{time.strftime('%H:%M:%S')}] Canonical indices: {done}/{total} attempted, "
                    f"{len(results)} resolved, {time.time() - t0:.0f}s elapsed",
                    file=sys.stderr,
                    flush=True,
                )

    prices = pd.DataFrame(results).sort_index() if results else pd.DataFrame()
    return prices, sources, resolved, value_types


def fetch_benchmark(name: str = "NIFTY 50", years: int = 5) -> pd.Series:
    """Benchmark history from the same adapter as every exposure.

    Using one source for both sides keeps relative returns internally consistent;
    mixing a Yahoo benchmark with NSE exposure histories introduces a calendar
    and dividend-treatment mismatch into every relative number.
    """
    start = date.today() - timedelta(days=365 * years + 10)
    return fetch_jugaad_index(name, start, date.today())
