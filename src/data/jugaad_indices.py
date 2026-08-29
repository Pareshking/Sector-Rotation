from __future__ import annotations

from datetime import date, timedelta
from typing import Mapping

import pandas as pd

from jugaad_data.nse import index_raw, index_tri_raw

MIN_OBSERVATIONS = 60


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

    date_col = next((c for c in ("HistoricalDate", "Date", "Index Date", "EOD_TIMESTAMP") if c in frame.columns), None)
    value_col = next((c for c in ("TRI", "TotalReturnsIndex", "NTR_Value", "CLOSE", "Close", "Closing Index Value") if c in frame.columns), None)
    if date_col is None or value_col is None:
        return pd.Series(dtype="float64", name=name)

    dates = pd.to_datetime(frame[date_col], errors="coerce", dayfirst=True)
    values = pd.to_numeric(frame[value_col].astype("string").str.replace(",", "", regex=False), errors="coerce")
    valid = dates.notna() & values.notna() & values.gt(0)
    if not valid.any():
        return pd.Series(dtype="float64", name=name)
    series = pd.Series(values.loc[valid].to_numpy(float), index=pd.DatetimeIndex(dates.loc[valid]), name=name)
    return series.groupby(level=0).last().sort_index()


def fetch_jugaad_index(name: str, start: date, end: date) -> pd.Series:
    """Fetch official Nifty history through jugaad-data's maintained index API.

    TRI is preferred; ordinary index close is retained as a fallback. The source
    remains NSE/NiftyIndices data exposed through jugaad-data, not a synthetic proxy.
    """
    candidates = [name]
    for candidate in candidates:
        try:
            tri = _records_to_series(name, index_tri_raw(candidate, candidate, start, end))
            if len(tri) >= MIN_OBSERVATIONS:
                tri.attrs.update(source="niftyindices_jugaad", resolved_name=candidate, value_type="TRI")
                return tri
        except Exception:
            pass
        try:
            raw = _records_to_series(name, index_raw(candidate, start, end))
            if len(raw) >= MIN_OBSERVATIONS:
                raw.attrs.update(source="niftyindices_jugaad", resolved_name=candidate, value_type="CLOSE")
                return raw
        except Exception:
            pass
    return pd.Series(dtype="float64", name=name)


def fetch_jugaad_canonical_indices(
    exposure_names: Mapping[str, str],
    years: int = 5,
    workers: int = 4,
) -> tuple[pd.DataFrame, dict[str, str], dict[str, str]]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    start = date.today() - timedelta(days=365 * years + 10)
    results: dict[str, pd.Series] = {}
    sources: dict[str, str] = {}
    resolved: dict[str, str] = {}

    def one(item):
        eid, name = item
        series = fetch_jugaad_index(name, start, date.today())
        return eid, name, series

    with ThreadPoolExecutor(max_workers=min(workers, max(len(exposure_names), 1))) as pool:
        futures = [pool.submit(one, item) for item in exposure_names.items()]
        for future in as_completed(futures):
            try:
                eid, name, series = future.result()
            except Exception:
                continue
            if len(series) >= MIN_OBSERVATIONS:
                results[eid] = series.rename(eid)
                sources[eid] = series.attrs.get("source", "niftyindices_jugaad")
                resolved[eid] = series.attrs.get("resolved_name", name)

    return (pd.DataFrame(results).sort_index() if results else pd.DataFrame()), sources, resolved
