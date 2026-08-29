from __future__ import annotations

from datetime import date, timedelta
from io import StringIO
from typing import Iterable

import pandas as pd
import requests

AMFI_HISTORY_URL = "https://portal.amfiindia.com/DownloadNAVHistoryReport_Po.aspx"


def _parse_history(text: str) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    for line in StringIO(text):
        parts = [part.strip() for part in line.rstrip("\r\n").split(";")]
        if len(parts) >= 8 and parts[0].isdigit():
            rows.append({"scheme_code": parts[0], "scheme_name": parts[1], "isin_growth": parts[2], "isin_dividend": parts[3], "nav": parts[4], "date": parts[7]})
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["nav"] = pd.to_numeric(frame["nav"], errors="coerce")
        frame["date"] = pd.to_datetime(frame["date"], dayfirst=True, errors="coerce")
        frame = frame.dropna(subset=["scheme_code", "nav", "date"])
    return frame


def fetch_amfi_history(start: date, end: date, scheme_codes: Iterable[str] | None = None, timeout: int = 45, chunk_days: int = 7) -> pd.DataFrame:
    """Fetch official AMFI historical NAVs in bounded date chunks."""
    wanted = {str(code) for code in scheme_codes or []}
    chunks: list[pd.DataFrame] = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=chunk_days - 1), end)
        response = requests.get(
            AMFI_HISTORY_URL,
            params={"frmdt": cursor.strftime("%d-%b-%Y"), "todt": chunk_end.strftime("%d-%b-%Y")},
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 Sector-Rotation/1.0"},
        )
        response.raise_for_status()
        frame = _parse_history(response.text)
        if not frame.empty and wanted:
            frame = frame[frame["scheme_code"].isin(wanted)]
        if not frame.empty:
            chunks.append(frame)
        cursor = chunk_end + timedelta(days=1)
    if not chunks:
        return pd.DataFrame(columns=["scheme_code", "scheme_name", "isin_growth", "isin_dividend", "nav", "date"])
    return pd.concat(chunks, ignore_index=True).drop_duplicates(subset=["scheme_code", "date"]).sort_values(["scheme_code", "date"])


def find_scheme_codes(current_nav: pd.DataFrame, scheme_names: Iterable[str]) -> dict[str, str]:
    """Resolve exact/unique AMFI scheme names to scheme codes."""
    if current_nav.empty or "scheme_name" not in current_nav.columns:
        return {}
    normalized = current_nav.assign(_name=current_nav["scheme_name"].astype(str).str.upper().str.replace(r"[^A-Z0-9]", "", regex=True))
    result: dict[str, str] = {}
    for requested in scheme_names:
        key = "".join(ch for ch in str(requested).upper() if ch.isalnum())
        exact = normalized[normalized["_name"] == key]
        if len(exact) == 1:
            result[str(requested)] = str(exact.iloc[0]["scheme_code"])
            continue
        candidates = normalized[normalized["_name"].str.contains(key, regex=False)] if key else pd.DataFrame()
        if len(candidates) == 1:
            result[str(requested)] = str(candidates.iloc[0]["scheme_code"])
    return result
