from __future__ import annotations

import json
import time
from datetime import date, timedelta
from typing import Iterable, Mapping

import pandas as pd
import requests

BASE_URL = "https://www.niftyindices.com"
HISTORICAL_URL = f"{BASE_URL}/Backpage.aspx/getHistoricaldatatabletoString"
HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/json; charset=UTF-8",
    "Origin": BASE_URL,
    "Referer": f"{BASE_URL}/reports/historical-data",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36 Sector-Rotation/1.0",
    "X-Requested-With": "XMLHttpRequest",
}


def _canonical_name(name: str) -> str:
    return " ".join(str(name).strip().upper().split())


def _request(name: str, start: date, end: date, timeout: int = 45) -> list[dict[str, object]]:
    canonical = _canonical_name(name)
    payload = {
        "cinfo": json.dumps(
            {
                "name": canonical,
                "startDate": start.strftime("%d-%b-%Y"),
                "endDate": end.strftime("%d-%b-%Y"),
                "indexName": canonical,
            },
            separators=(",", ":"),
        ).replace('"', "'")
    }
    response = requests.post(HISTORICAL_URL, headers=HEADERS, json=payload, timeout=timeout)
    response.raise_for_status()
    body = response.json()
    raw = body.get("d", "[]")
    if isinstance(raw, str):
        rows = json.loads(raw)
    else:
        rows = raw
    if not isinstance(rows, list):
        raise ValueError(f"Unexpected Nifty Indices response for {name!r}")
    return [row for row in rows if isinstance(row, dict)]


def fetch_nifty_index_history(
    name: str,
    years: int = 5,
    start: date | None = None,
    end: date | None = None,
    retries: int = 3,
) -> pd.Series:
    """Fetch authoritative Nifty price-index history from NSE Indices.

    The endpoint is the same historical-data service used by niftyindices.com.
    Yahoo Finance remains the preferred fast path; this adapter is used for
    canonical index gaps and does not fabricate observations.
    """
    end_date = end or date.today()
    start_date = start or (end_date - timedelta(days=365 * years + 10))
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            rows = _request(name, start_date, end_date)
            records: list[tuple[pd.Timestamp, float]] = []
            for row in rows:
                raw_date = row.get("HistoricalDate") or row.get("Date")
                raw_close = row.get("CLOSE") or row.get("Close") or row.get("Closing Price")
                if raw_date is None or raw_close in (None, "", "-"):
                    continue
                parsed_date = pd.to_datetime(raw_date, dayfirst=True, errors="coerce")
                parsed_close = pd.to_numeric(str(raw_close).replace(",", ""), errors="coerce")
                if pd.notna(parsed_date) and pd.notna(parsed_close) and float(parsed_close) > 0:
                    records.append((pd.Timestamp(parsed_date).tz_localize(None), float(parsed_close)))
            if not records:
                return pd.Series(dtype="float64", name=name)
            return pd.Series(dict(records)).sort_index().rename(name)
        except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(1.5 * attempt)
    raise RuntimeError(f"Nifty Indices request failed for {name!r}: {last_error}") from last_error


def fetch_missing_indices(
    names: Mapping[str, str] | Iterable[tuple[str, str]],
    existing: pd.DataFrame | None = None,
    years: int = 5,
) -> pd.DataFrame:
    """Fetch only missing/invalid canonical index series.

    `names` maps the repository exposure ID to the official Nifty index name.
    """
    mapping = dict(names)
    frame = existing.copy() if existing is not None else pd.DataFrame()
    for exposure_id, index_name in mapping.items():
        series = frame[exposure_id] if exposure_id in frame.columns else pd.Series(dtype="float64")
        if series.dropna().size >= 60:
            continue
        fetched = fetch_nifty_index_history(index_name, years=years)
        if not fetched.empty:
            frame = frame.drop(columns=[exposure_id], errors="ignore").join(fetched.rename(exposure_id), how="outer")
    return frame.sort_index()
