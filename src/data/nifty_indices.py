from __future__ import annotations

import json
import time
from datetime import date, timedelta
from io import StringIO
from typing import Iterable, Mapping

import pandas as pd
import requests

BASE_URL = "https://www.niftyindices.com"
HISTORICAL_PAGE = f"{BASE_URL}/reports/historical-data"
HISTORICAL_URL = f"{BASE_URL}/Backpage.aspx/getHistoricaldatatabletoString"
NSE_ARCHIVE_URLS = (
    "https://archives.nseindia.com/content/indices/ind_close_all_{date}.csv",
    "https://nsearchives.nseindia.com/content/indices/ind_close_all_{date}.csv",
)
HEADERS = {"Accept": "application/json, text/javascript, */*; q=0.01", "Content-Type": "application/json; charset=UTF-8", "Origin": BASE_URL, "Referer": HISTORICAL_PAGE, "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36 Sector-Rotation/1.0", "X-Requested-With": "XMLHttpRequest"}
NSE_HEADERS = {"User-Agent": HEADERS["User-Agent"], "Accept": "text/csv,*/*;q=0.8", "Referer": "https://www.nseindia.com/"}


def _canonical_name(name: str) -> str:
    return " ".join(str(name).strip().upper().split())


def _request(name: str, start: date, end: date, timeout: int = 45) -> list[dict[str, object]]:
    canonical = _canonical_name(name)
    payload = {"cinfo": "{'name':'%s','startDate':'%s','endDate':'%s','indexName':'%s'}" % (canonical, start.strftime("%d-%b-%Y"), end.strftime("%d-%b-%Y"), canonical)}
    session = requests.Session()
    try:
        session.get(HISTORICAL_PAGE, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=8)
    except requests.RequestException:
        pass
    response = session.post(HISTORICAL_URL, headers=HEADERS, json=payload, timeout=timeout)
    response.raise_for_status()
    body = response.json()
    raw = body.get("d", "[]")
    rows = json.loads(raw) if isinstance(raw, str) else raw
    if not isinstance(rows, list):
        raise ValueError(f"Unexpected Nifty Indices response for {name!r}")
    return [row for row in rows if isinstance(row, dict)]


def _rows_to_series(name: str, rows: list[dict[str, object]]) -> pd.Series:
    records: list[tuple[pd.Timestamp, float]] = []
    for row in rows:
        raw_date = row.get("HistoricalDate") or row.get("Date")
        raw_close = row.get("CLOSE") or row.get("Close") or row.get("Closing Index Value")
        if raw_date is None or raw_close in (None, "", "-"):
            continue
        parsed_date = pd.to_datetime(raw_date, dayfirst=True, errors="coerce")
        parsed_close = pd.to_numeric(str(raw_close).replace(",", ""), errors="coerce")
        if pd.notna(parsed_date) and pd.notna(parsed_close) and float(parsed_close) > 0:
            records.append((pd.Timestamp(parsed_date).tz_localize(None), float(parsed_close)))
    return pd.Series(dict(records)).sort_index().rename(name) if records else pd.Series(dtype="float64", name=name)


def fetch_nifty_index_history(name: str, years: int = 5, start: date | None = None, end: date | None = None, retries: int = 1) -> pd.Series:
    """Fetch authoritative Nifty price-index history from NSE Indices."""
    end_date = end or date.today()
    start_date = start or (end_date - timedelta(days=365 * years + 10))
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return _rows_to_series(name, _request(name, start_date, end_date))
        except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"Nifty Indices request failed for {name!r}: {last_error}") from last_error


def fetch_nse_archive_indices(names: Iterable[str], start: date, end: date, timeout: int = 10) -> pd.DataFrame:
    """Backfill requested indices from NSE's daily multi-index archive."""
    wanted = {_canonical_name(name): name for name in names}
    if not wanted:
        return pd.DataFrame()
    session = requests.Session()
    try:
        session.get("https://www.nseindia.com/", headers=NSE_HEADERS, timeout=8)
    except requests.RequestException:
        pass
    rows: list[pd.DataFrame] = []
    for day in pd.bdate_range(start=start, end=end):
        content: bytes | None = None
        for template in NSE_ARCHIVE_URLS:
            try:
                response = session.get(template.format(date=day.strftime("%d%m%Y")), headers=NSE_HEADERS, timeout=timeout)
                if response.status_code == 200 and len(response.content) >= 300:
                    content = response.content
                    break
            except requests.RequestException:
                continue
        if content is None:
            continue
        try:
            frame = pd.read_csv(StringIO(content.decode("utf-8", errors="replace")))
            if "Index Name" not in frame.columns or "Closing Index Value" not in frame.columns:
                continue
            frame["_canonical"] = frame["Index Name"].astype(str).map(_canonical_name)
            selected = frame[frame["_canonical"].isin(wanted)].copy()
            if selected.empty:
                continue
            selected["date"] = pd.to_datetime(selected["Index Date"], dayfirst=True, errors="coerce")
            selected["close"] = pd.to_numeric(selected["Closing Index Value"], errors="coerce")
            rows.append(selected.dropna(subset=["date", "close"])[["_canonical", "date", "close"]])
        except (UnicodeDecodeError, ValueError, pd.errors.ParserError):
            continue
    if not rows:
        return pd.DataFrame()
    all_rows = pd.concat(rows, ignore_index=True).drop_duplicates(subset=["_canonical", "date"])
    result: dict[str, pd.Series] = {}
    for canonical, original in wanted.items():
        subset = all_rows[all_rows["_canonical"] == canonical]
        if not subset.empty:
            result[original] = subset.set_index("date")["close"].sort_index().rename(original)
    return pd.DataFrame(result).sort_index()


def fetch_missing_indices(names: Mapping[str, str] | Iterable[tuple[str, str]], existing: pd.DataFrame | None = None, years: int = 5) -> pd.DataFrame:
    """Fill missing canonical series using Nifty Indices, then NSE archive."""
    mapping = dict(names)
    frame = existing.copy() if existing is not None else pd.DataFrame()
    missing: dict[str, str] = {}
    nifty_available = True
    items = list(mapping.items())
    for position, (exposure_id, index_name) in enumerate(items):
        series = frame[exposure_id] if exposure_id in frame.columns else pd.Series(dtype="float64")
        if series.dropna().size >= 60:
            continue
        if not nifty_available:
            missing[exposure_id] = index_name
            continue
        try:
            fetched = fetch_nifty_index_history(index_name, years=years, retries=1)
        except RuntimeError:
            nifty_available = False
            missing[exposure_id] = index_name
            for remaining_id, remaining_name in items[position + 1:]:
                remaining = frame[remaining_id] if remaining_id in frame.columns else pd.Series(dtype="float64")
                if remaining.dropna().size < 60:
                    missing[remaining_id] = remaining_name
            break
        if fetched.dropna().size >= 60:
            frame = frame.drop(columns=[exposure_id], errors="ignore").join(fetched.rename(exposure_id), how="outer")
        else:
            missing[exposure_id] = index_name
    if missing:
        archive = fetch_nse_archive_indices(missing.values(), start=date.today() - timedelta(days=365 * years + 10), end=date.today())
        for exposure_id, index_name in missing.items():
            if index_name in archive.columns and archive[index_name].dropna().size >= 60:
                frame = frame.drop(columns=[exposure_id], errors="ignore").join(archive[index_name].rename(exposure_id), how="outer")
    return frame.sort_index()
