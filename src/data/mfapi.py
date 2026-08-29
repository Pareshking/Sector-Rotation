from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from src.data.cache import cache_key, read_json_cache, write_json_cache

BASE_URL = "https://api.mfapi.in/mf"
DEFAULT_CACHE_DIR = Path("data") / ".cache" / "mfapi"
DEFAULT_TIMEOUT = (5, 10)
HEADERS = {"Accept": "application/json", "User-Agent": "Sector-Rotation/1.0"}


@dataclass(frozen=True)
class MFAPIResult:
    frame: pd.DataFrame
    scheme_code: int
    scheme_name: str
    source: str = "mfapi"


def _get_json(
    url: str,
    params: dict[str, str] | None,
    cache_dir: Path,
    timeout: tuple[float, float],
    cache_seconds: int,
) -> Any:
    key = cache_key(url, params)
    cached = read_json_cache(cache_dir / f"{key}.json", max_age_seconds=cache_seconds)
    if cached is not None:
        return cached
    response = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    write_json_cache(payload, cache_dir / f"{key}.json")
    return payload


def search_schemes(
    query: str,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    timeout: tuple[float, float] = DEFAULT_TIMEOUT,
    cache_seconds: int = 86400,
) -> pd.DataFrame:
    """Search MFAPI schemes and return normalized scheme-code/name rows."""
    clean = str(query).strip()
    if not clean:
        return pd.DataFrame(columns=["scheme_code", "scheme_name"])
    payload = _get_json(f"{BASE_URL}/search", {"q": clean}, Path(cache_dir), timeout, cache_seconds)
    rows = payload if isinstance(payload, list) else payload.get("data", []) if isinstance(payload, dict) else []
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = row.get("schemeCode") or row.get("scheme_code") or row.get("code")
        name = row.get("schemeName") or row.get("scheme_name") or row.get("name")
        try:
            code_int = int(str(code))
        except (TypeError, ValueError):
            continue
        if name:
            normalized.append({"scheme_code": code_int, "scheme_name": str(name).strip()})
    return pd.DataFrame(normalized).drop_duplicates("scheme_code")


def _best_candidate(candidates: pd.DataFrame, target: str) -> int | None:
    if candidates.empty:
        return None
    target_cf = target.casefold().strip()
    exact = candidates[candidates["scheme_name"].str.casefold().eq(target_cf)]
    if not exact.empty:
        return int(exact.iloc[0]["scheme_code"])
    tokens = [token for token in target_cf.replace("-", " ").split() if len(token) > 2]
    if not tokens:
        return None
    scored = candidates.assign(
        _score=candidates["scheme_name"].str.casefold().map(
            lambda value: sum(token in value for token in tokens)
        )
    )
    best = scored.sort_values(["_score", "scheme_code"], ascending=[False, True]).iloc[0]
    threshold = max(1, len(tokens) // 2)
    return int(best["scheme_code"]) if int(best["_score"]) >= threshold else None


def resolve_scheme_code(
    query: str,
    expected_name: str | None = None,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
) -> int | None:
    """Resolve an ETF to a numeric MFAPI scheme code without guessing."""
    candidates = search_schemes(query, cache_dir=cache_dir, timeout=DEFAULT_TIMEOUT)
    code = _best_candidate(candidates, expected_name or query)
    if code is not None:
        return code
    if expected_name and expected_name.casefold() != query.casefold():
        return _best_candidate(
            search_schemes(expected_name, cache_dir=cache_dir, timeout=DEFAULT_TIMEOUT),
            expected_name,
        )
    return None


def fetch_scheme_history(
    scheme_code: int,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    timeout: tuple[float, float] = DEFAULT_TIMEOUT,
    cache_seconds: int = 86400,
) -> MFAPIResult:
    """Fetch complete historical NAV data for a numeric AMFI scheme code."""
    code = int(scheme_code)
    payload = _get_json(f"{BASE_URL}/{code}", None, Path(cache_dir), timeout, cache_seconds)
    if not isinstance(payload, dict):
        raise ValueError(f"MFAPI returned an invalid payload for scheme {code}")
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    rows = payload.get("data") if isinstance(payload.get("data"), list) else []
    raw_dates = pd.Series(
        [row.get("date") if isinstance(row, dict) else None for row in rows],
        dtype="string",
    )
    parsed_dates = pd.to_datetime(raw_dates, format="%d-%m-%Y", errors="coerce")
    records: list[dict[str, Any]] = []
    for row, parsed_date in zip(rows, parsed_dates):
        if not isinstance(row, dict) or pd.isna(parsed_date):
            continue
        nav = pd.to_numeric(row.get("nav"), errors="coerce")
        if pd.notna(nav) and float(nav) > 0:
            records.append(
                {
                    "date": pd.Timestamp(parsed_date),
                    "close": float(nav),
                    "adjusted_close": float(nav),
                }
            )
    frame = pd.DataFrame(records, columns=["date", "close", "adjusted_close"])
    if not frame.empty:
        frame = frame.drop_duplicates("date").set_index("date").sort_index()
    name = str(meta.get("scheme_name") or meta.get("schemeName") or code)
    return MFAPIResult(frame=frame, scheme_code=code, scheme_name=name)


def fetch_etf_nav(
    query: str,
    scheme_code: int | None = None,
    expected_name: str | None = None,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    timeout: tuple[float, float] = DEFAULT_TIMEOUT,
) -> MFAPIResult:
    code = (
        int(scheme_code)
        if scheme_code is not None
        else resolve_scheme_code(query, expected_name=expected_name, cache_dir=cache_dir)
    )
    if code is None:
        raise LookupError(f"MFAPI scheme code could not be resolved for {query!r}")
    return fetch_scheme_history(code, cache_dir=cache_dir, timeout=timeout)
