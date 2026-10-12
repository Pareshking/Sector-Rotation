"""Store-and-merge ingestion: what the nightly pipeline fetches, and how.

* **Index histories** (NSE via jugaad) are fetched incrementally: only from
  ``overlap`` sessions before the last stored session onwards. The overlap is
  re-fetched on purpose; a value that changed there is a restatement, recorded
  and appended, never silently overwritten. An empty store is seeded with a
  full ``seed_years`` history once. A stored series is only ever extended with
  the same value type (a TRI history is never continued with a price index).
* **Vehicle histories** are merged into the store by AMFI scheme code after
  each fetch. MFAPI returns a fund's whole NAV history in one request, so a
  windowed request would save nothing; what the store adds is that a fund
  whose fetch fails one night keeps its history instead of vanishing.
* **Cash** is the configured liquid fund's NAV, refused unless AMFI's scheme
  name matches the configured one exactly.

A fetch that fails falls back to what is stored, and says so.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Mapping

import pandas as pd

from src.data.calendar import TradingCalendar
from src.data.store import DEFAULT_OVERLAP_SESSIONS, RawStore, SeriesMismatch

logger = logging.getLogger(__name__)

BENCHMARK_ID = "nifty-50"
SEED = "seed"
INCREMENTAL = "incremental"
STORED = "stored"  # the fetch failed; the stored history was used as it was

NAV_SOURCES = {"mfapi", "amfi"}


@dataclass
class SeriesIngest:
    series_id: str
    mode: str
    new_sessions: int = 0
    restatements: list[dict] = field(default_factory=list)
    error: str = ""
    value_type: str | None = None
    source: str | None = None

    def as_dict(self) -> dict[str, object]:
        out = {"mode": self.mode, "new_sessions": self.new_sessions}
        if self.error:
            out["error"] = self.error
        if self.value_type:
            out["value_type"] = self.value_type
        return out


def _fetcher():
    from src.data.jugaad_indices import fetch_jugaad_index

    return fetch_jugaad_index


def update_index(
    store: RawStore,
    series_id: str,
    nse_name: str,
    today: date,
    seed_years: int = 5,
    overlap: int = DEFAULT_OVERLAP_SESSIONS,
    calendar: TradingCalendar | None = None,
    fetch: Callable | None = None,
    is_benchmark: bool = False,
) -> tuple[pd.Series, SeriesIngest]:
    """Extend one stored index series and return the whole stored history."""
    fetch = fetch or _fetcher()
    start = store.window_start("index", series_id, overlap, calendar)
    stored = store.series("index", series_id)
    if start is None:
        mode, begin = SEED, today - timedelta(days=365 * seed_years + 10)
        kwargs = {}
    else:
        mode, begin = INCREMENTAL, start.date()
        kwargs = {"value_types": (stored.attrs.get("value_type"),), "min_observations": 1}
    report = SeriesIngest(series_id, mode)
    # The benchmark *is* the calendar, so it is checked only for holes in itself.
    fetched = fetch(nse_name, begin, today, calendar=None if is_benchmark else calendar, **kwargs)
    if fetched is None or fetched.empty:
        report.error = "; ".join(getattr(fetched, "attrs", {}).get("errors", [])) or "no data returned"
    else:
        lead = (fetched.index.min() - pd.Timestamp(begin)).days
        if is_benchmark and mode == SEED and lead > 10:
            report.error = f"first observation {fetched.index.min():%Y-%m-%d} is {lead} days after the requested start"
        else:
            try:
                merged = store.merge(
                    "index", series_id, fetched,
                    value_type=str(fetched.attrs.get("value_type") or stored.attrs.get("value_type")),
                    source=str(fetched.attrs.get("source") or "niftyindices_jugaad"),
                )
                report.new_sessions = merged.new_sessions
                report.restatements = [r.as_dict() for r in merged.restatements]
            except SeriesMismatch as exc:
                report.error = str(exc)
    if report.error:
        logger.error("index/%s: %s", series_id, report.error)
        if not store.series("index", series_id).empty:
            report.mode = STORED
    current = store.series("index", series_id)
    report.value_type = current.attrs.get("value_type")
    report.source = current.attrs.get("source")
    return current, report


def ingest_indices(
    store: RawStore,
    exposure_names: Mapping[str, str],
    calendar: TradingCalendar,
    today: date,
    seed_years: int = 5,
    overlap: int = DEFAULT_OVERLAP_SESSIONS,
    workers: int = 10,
    fetch: Callable | None = None,
) -> tuple[pd.DataFrame, dict[str, SeriesIngest]]:
    """Update every exposure's index series; return the full stored panel and per-series reports."""
    reports: dict[str, SeriesIngest] = {}
    series: dict[str, pd.Series] = {}

    def one(item):
        eid, name = item
        return eid, update_index(store, eid, name, today, seed_years, overlap, calendar, fetch)

    with ThreadPoolExecutor(max_workers=min(workers, max(len(exposure_names), 1))) as pool:
        futures = [pool.submit(one, item) for item in exposure_names.items()]
        for future in as_completed(futures):
            eid, (current, report) = future.result()
            reports[eid] = report
            if not current.empty:
                series[eid] = current.rename(eid)
    frame = pd.DataFrame(series).sort_index() if series else pd.DataFrame()
    return frame, reports


def ingest_vehicles(
    store: RawStore,
    histories: pd.DataFrame,
    sources: Mapping[str, str],
    scheme_codes: Mapping[str, int],
) -> tuple[pd.DataFrame, dict[str, SeriesIngest]]:
    """Merge tonight's vehicle histories into the store; return full stored histories.

    ``scheme_codes`` maps each vehicle key (symbol, else fund name) to its AMFI
    scheme code, which is its store id. A vehicle missing from ``histories``
    keeps its stored history.
    """
    columns: dict[str, pd.Series] = {}
    reports: dict[str, SeriesIngest] = {}
    for key, code in scheme_codes.items():
        sid = str(int(code))
        source = sources.get(key)
        report = SeriesIngest(sid, INCREMENTAL if store.last_date("vehicle", sid) is not None else SEED)
        tonight = histories[key].dropna() if histories is not None and key in histories.columns else pd.Series(dtype=float)
        if not tonight.empty and source:
            try:
                merged = store.merge(
                    "vehicle", sid, tonight,
                    value_type="NAV" if source in NAV_SOURCES else "CLOSE",
                    source=source,
                )
                report.new_sessions = merged.new_sessions
                report.restatements = [r.as_dict() for r in merged.restatements]
            except SeriesMismatch as exc:
                report.error = str(exc)
        else:
            report.error = "not fetched tonight"
        current = store.series("vehicle", sid, source if source and not report.error else None)
        if report.error and not current.empty:
            report.mode = STORED
        if not current.empty:
            columns[key] = current.rename(key)
        report.value_type, report.source = current.attrs.get("value_type"), current.attrs.get("source")
        reports[key] = report
    frame = pd.DataFrame(columns).sort_index() if columns else pd.DataFrame()
    return frame, reports


def ingest_cash(
    store: RawStore,
    scheme_code: int,
    expected_name: str,
    fetch: Callable | None = None,
) -> tuple[pd.Series, SeriesIngest]:
    """The liquid fund's NAV history: fetched, name-checked, merged, returned in full."""
    if fetch is None:
        from src.data.mfapi import fetch_scheme_history

        fetch = fetch_scheme_history
    sid = str(int(scheme_code))
    report = SeriesIngest(sid, INCREMENTAL if store.last_date("vehicle", sid) is not None else SEED)
    try:
        result = fetch(int(scheme_code))
        if result.scheme_name.strip().casefold() != expected_name.strip().casefold():
            raise SeriesMismatch(
                f"scheme {scheme_code} is {result.scheme_name!r}, not the configured "
                f"{expected_name!r}; refusing it as the cash return"
            )
        nav = result.frame["close"] if "close" in result.frame else pd.Series(dtype=float)
        merged = store.merge("vehicle", sid, nav, value_type="NAV", source="mfapi")
        report.new_sessions = merged.new_sessions
        report.restatements = [r.as_dict() for r in merged.restatements]
    except Exception as exc:  # network, payload or name mismatch: fall back to the store
        report.error = f"{type(exc).__name__}: {exc}"
        logger.error("cash/%s: %s", sid, report.error)
    current = store.series("vehicle", sid)
    if report.error and not current.empty:
        report.mode = STORED
    report.value_type, report.source = current.attrs.get("value_type"), current.attrs.get("source")
    return current.rename("nav"), report


def restatements(reports: Mapping[str, SeriesIngest]) -> list[dict]:
    return [item for report in reports.values() for item in report.restatements]
