from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from difflib import SequenceMatcher
from functools import lru_cache
from io import StringIO
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import pandas as pd
import requests

try:
    import cloudscraper
except ImportError:  # pragma: no cover
    cloudscraper = None

from src.data.cache import read_json_cache, write_json_cache

BASE_URL = "https://www.niftyindices.com"
BASE_URLS = (BASE_URL, "https://niftyindices.com")
HISTORICAL_PAGE = f"{BASE_URL}/reports/historical-data"
PRICE_ENDPOINTS = tuple(f"{base}/Backpage.aspx/getHistoricaldatatabletoString" for base in BASE_URLS)
TRI_ENDPOINTS = tuple(f"{base}/Backpage.aspx/getTotalReturnIndexString" for base in BASE_URLS)
SUBTYPE_ENDPOINT = f"{BASE_URL}/Backpage.aspx/gethistoricaltypeSubindexdata"
INDEX_CATALOGUE_ENDPOINT = f"{BASE_URL}/Backpage.aspx/gethistoricaltypeindexdata"
NSE_API_URL = "https://www.nseindia.com/api/historical/indicesHistory"
NSE_ARCHIVE_URLS = (
    "https://archives.nseindia.com/content/indices/ind_close_all_{date}.csv",
    "https://nsearchives.nseindia.com/content/indices/ind_close_all_{date}.csv",
)

MIN_OBSERVATIONS = 60
DEFAULT_TIMEOUT = (5, 10)
CATALOGUE_CACHE_DIR = Path("data") / ".cache" / "niftyindices"
CATALOGUE_CACHE_FILE = CATALOGUE_CACHE_DIR / "index_catalogue.json"
CATALOGUE_CACHE_SECONDS = 24 * 60 * 60
ARCHIVE_FALLBACK_DAYS = 100
SEED_PATHS = (
    Path("data") / "seeds" / "canonical_indices.parquet",
    Path("data") / "raw" / "canonical_indices.parquet",
    Path("data") / "processed" / "canonical_index_seed.parquet",
)

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
    "Connection": "keep-alive",
    "Content-Type": "application/json; charset=UTF-8",
    "Origin": BASE_URL,
    "Referer": HISTORICAL_PAGE,
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "X-Requested-With": "XMLHttpRequest",
}
NSE_HEADERS = {
    "User-Agent": HEADERS["User-Agent"],
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": HEADERS["Accept-Language"],
    "Referer": "https://www.nseindia.com/",
    "Connection": "keep-alive",
}

INDEX_NAME_ALIASES: dict[str, str] = {
    "telecom": "NIFTY TELECOMMUNICATIONS",
    "nifty telecom": "NIFTY TELECOMMUNICATIONS",
    "telecommunications": "NIFTY TELECOMMUNICATIONS",
    "nifty telecommunications": "NIFTY TELECOMMUNICATIONS",
    "nbfc": "NIFTY FINANCIAL SERVICES EX-BANK",
    "nifty nbfc": "NIFTY FINANCIAL SERVICES EX-BANK",
    "financial-services-ex-bank": "NIFTY FINANCIAL SERVICES EX-BANK",
    "nifty financial services ex-bank": "NIFTY FINANCIAL SERVICES EX-BANK",
    "healthcare": "NIFTY HEALTHCARE",
    "nifty healthcare": "NIFTY HEALTHCARE",
    "healthcare index": "NIFTY HEALTHCARE",
    "nifty healthcare index": "NIFTY HEALTHCARE",
    "power": "NIFTY POWER",
    "nifty power": "NIFTY POWER",
    "capital-goods": "NIFTY CAPITAL GOODS",
    "capital goods": "NIFTY CAPITAL GOODS",
    "nifty capital goods": "NIFTY CAPITAL GOODS",
    "consumer-services": "NIFTY CONSUMER SERVICES",
    "consumer services": "NIFTY CONSUMER SERVICES",
    "nifty consumer services": "NIFTY CONSUMER SERVICES",
    "financial-services": "NIFTY FINANCIAL SERVICES",
    "financial services": "NIFTY FINANCIAL SERVICES",
    "oil-gas": "NIFTY OIL & GAS",
    "nifty oil & gas": "NIFTY OIL & GAS",
    "defence": "NIFTY INDIA DEFENCE",
    "nifty defence": "NIFTY INDIA DEFENCE",
    "nifty india defence": "NIFTY INDIA DEFENCE",
    "ev-new-energy-auto": "NIFTY EV & NEW AGE AUTOMOTIVE",
    "nifty ev & new age automotive": "NIFTY EV & NEW AGE AUTOMOTIVE",
    "manufacturing": "NIFTY INDIA MANUFACTURING",
    "nifty india manufacturing": "NIFTY INDIA MANUFACTURING",
    "infrastructure": "NIFTY INFRASTRUCTURE",
    "infrastructure-logistics": "NIFTY INDIA INFRASTRUCTURE & LOGISTICS",
    "railways": "NIFTY INDIA RAILWAYS PSU",
    "consumption": "NIFTY INDIA CONSUMPTION",
    "digital": "NIFTY INDIA DIGITAL",
    "internet": "NIFTY INDIA INTERNET",
    "tourism": "NIFTY INDIA TOURISM",
    "energy": "NIFTY ENERGY",
    "commodities": "NIFTY COMMODITIES",
    "capital-markets": "NIFTY CAPITAL MARKETS",
    "mnc": "NIFTY MNC",
    "pse": "NIFTY PSE",
    "cpse": "NIFTY CPSE",
    "services": "NIFTY SERVICES SECTOR",
    "rural": "NIFTY RURAL",
    "mobility": "NIFTY MOBILITY",
    "reit-invit": "NIFTY REITS & INVITS",
    "nifty reits & invits": "NIFTY REITS & INVITS",
}
INDEX_NAME_ALTERNATES: dict[str, tuple[str, ...]] = {
    "healthcare": ("NIFTY HEALTHCARE", "NIFTY HEALTHCARE INDEX"),
    "nifty healthcare": ("NIFTY HEALTHCARE", "NIFTY HEALTHCARE INDEX"),
    "healthcare index": ("NIFTY HEALTHCARE", "NIFTY HEALTHCARE INDEX"),
    "nifty healthcare index": ("NIFTY HEALTHCARE", "NIFTY HEALTHCARE INDEX"),
}

# Established Yahoo index symbols. For newer indices the resolver will also
# try the common NIFTY_<NAME>.NS form, but only accepts a real >=60-row series.
YAHOO_INDEX_SYMBOLS: dict[str, str] = {
    "auto": "^CNXAUTO",
    "bank": "^NSEBANK",
    "financial-services": "NIFTY_FIN_SERVICE.NS",
    "fmcg": "^CNXFMCG",
    "it": "^CNXIT",
    "media": "^CNXMEDIA",
    "metal": "^CNXMETAL",
    "pharma": "^CNXPHARMA",
    "psu-bank": "^CNXPSUBANK",
    "private-bank": "NIFTY_PVT_BANK.NS",
    "consumer-durables": "NIFTY_CONSR_DURBL.NS",
    "realty": "^CNXREALTY",
    "oil-gas": "^CNXENERGY",
    "chemicals": "^CNXCHEM",
    "services": "^CNXSERVICE",
    "consumption": "NIFTY_CONSUMPTION.NS",
    "energy": "NIFTY_ENERGY.NS",
    "capital-goods": "NIFTY_CAPITAL_GOODS.NS",
    "cement": "NIFTY_CEMENT.NS",
    "power": "NIFTY_POWER.NS",
    "healthcare": "NIFTY_HEALTHCARE.NS",
    "telecom": "NIFTY_TELECOMMUNICATIONS.NS",
    "infrastructure": "NIFTY_INFRASTRUCTURE.NS",
    "capital-markets": "NIFTY_CAPITAL_MARKETS.NS",
    "mnc": "NIFTY_MNC.NS",
    "pse": "NIFTY_PSE.NS",
    "cpse": "NIFTY_CPSE.NS",
    "rural": "NIFTY_RURAL.NS",
    "mobility": "NIFTY_MOBILITY.NS",
    "reit-invit": "NIFTY_REITS_INVITS.NS",
}

AUTHORITATIVE_CATALOGUE_SEED: tuple[tuple[str, str], ...] = (
    ("NIFTY AUTO", "Sectoral Indices"), ("NIFTY BANK", "Sectoral Indices"),
    ("NIFTY FINANCIAL SERVICES", "Sectoral Indices"), ("NIFTY FMCG", "Sectoral Indices"),
    ("NIFTY IT", "Sectoral Indices"), ("NIFTY MEDIA", "Sectoral Indices"),
    ("NIFTY METAL", "Sectoral Indices"), ("NIFTY PHARMA", "Sectoral Indices"),
    ("NIFTY PRIVATE BANK", "Sectoral Indices"), ("NIFTY PSU BANK", "Sectoral Indices"),
    ("NIFTY REALTY", "Sectoral Indices"), ("NIFTY CONSUMER DURABLES", "Sectoral Indices"),
    ("NIFTY OIL & GAS", "Sectoral Indices"), ("NIFTY HEALTHCARE", "Sectoral Indices"),
    ("NIFTY FINANCIAL SERVICES EX-BANK", "Sectoral Indices"), ("NIFTY CHEMICALS", "Sectoral Indices"),
    ("NIFTY CEMENT", "Sectoral Indices"), ("NIFTY TELECOMMUNICATIONS", "Sectoral Indices"),
    ("NIFTY POWER", "Sectoral Indices"), ("NIFTY NBFC", "Sectoral Indices"),
    ("NIFTY CONSUMER SERVICES", "Sectoral Indices"), ("NIFTY CAPITAL GOODS", "Sectoral Indices"),
    ("NIFTY INDIA DEFENCE", "Thematic Indices"), ("NIFTY EV & NEW AGE AUTOMOTIVE", "Thematic Indices"),
    ("NIFTY INDIA MANUFACTURING", "Thematic Indices"), ("NIFTY INFRASTRUCTURE", "Thematic Indices"),
    ("NIFTY INDIA INFRASTRUCTURE & LOGISTICS", "Thematic Indices"), ("NIFTY INDIA RAILWAYS PSU", "Thematic Indices"),
    ("NIFTY INDIA CONSUMPTION", "Thematic Indices"), ("NIFTY INDIA DIGITAL", "Thematic Indices"),
    ("NIFTY INDIA INTERNET", "Thematic Indices"), ("NIFTY INDIA TOURISM", "Thematic Indices"),
    ("NIFTY ENERGY", "Thematic Indices"), ("NIFTY COMMODITIES", "Thematic Indices"),
    ("NIFTY CAPITAL MARKETS", "Thematic Indices"), ("NIFTY MNC", "Thematic Indices"),
    ("NIFTY PSE", "Thematic Indices"), ("NIFTY CPSE", "Thematic Indices"),
    ("NIFTY SERVICES SECTOR", "Thematic Indices"), ("NIFTY RURAL", "Thematic Indices"),
    ("NIFTY MOBILITY", "Thematic Indices"), ("NIFTY REITS & INVITS", "Thematic Indices"),
)


def normalize_index_name(value: str) -> str:
    text = str(value).casefold().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\bindex\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _canonical_name(name: str) -> str:
    return " ".join(str(name).strip().upper().split())


def _parse_api_payload(payload: object) -> list[object]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    raw = payload.get("d")
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return decoded if isinstance(decoded, list) else []
    if isinstance(raw, list):
        return raw
    for key in ("data", "result", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _make_session(session=None):
    if session is None:
        if cloudscraper is not None:
            session = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})
        else:
            session = requests.Session()
    headers = getattr(session, "headers", None)
    if hasattr(headers, "update"):
        headers.update(HEADERS)
    try:
        session.get(HISTORICAL_PAGE, headers=HEADERS, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
    except Exception:
        pass
    return session


def _post_json(url: str, payload: object, timeout: int | tuple[float, float] = DEFAULT_TIMEOUT) -> list[object]:
    session = _make_session()
    response = session.post(url, headers=HEADERS, json=payload, timeout=timeout)
    response.raise_for_status()
    return _parse_api_payload(response.json())


def _seed_catalogue() -> pd.DataFrame:
    return pd.DataFrame(AUTHORITATIVE_CATALOGUE_SEED, columns=["name", "category"])


def _merge_catalogues(*frames: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for frame in frames:
        if frame is None or frame.empty:
            continue
        for row in frame.to_dict(orient="records"):
            name = row.get("name")
            if not name:
                continue
            canonical = _canonical_name(str(name))
            key = normalize_index_name(canonical)
            if key and key not in seen:
                rows.append({"name": canonical, "category": str(row.get("category") or "")})
                seen.add(key)
    return pd.DataFrame(rows, columns=["name", "category"])


def _discover_index_catalogue_uncached(timeout: int | tuple[float, float] = DEFAULT_TIMEOUT) -> pd.DataFrame:
    subtypes: list[str] = []
    try:
        top = _post_json(SUBTYPE_ENDPOINT, {"cinfo": {"indextype": "Equity", "indexgroup": ""}}, timeout=timeout)
        for row in top:
            value = row.get("indextype") or row.get("indexType") or row.get("name") if isinstance(row, dict) else row
            if value:
                subtypes.append(str(value).strip())
    except Exception:
        pass
    if not subtypes:
        subtypes = ["Broad Market Indices", "Sectoral Indices", "Thematic Indices", "Strategy Indices"]

    records: list[dict[str, str]] = []
    for subtype in dict.fromkeys(subtypes):
        try:
            rows = _post_json(INDEX_CATALOGUE_ENDPOINT, {"cinfo": {"indextype": subtype, "indexgroup": "Equity"}}, timeout=timeout)
        except Exception:
            rows = []
        for row in rows:
            if isinstance(row, dict):
                value = row.get("indextype") or row.get("indexType") or row.get("indexName") or row.get("Index Name") or row.get("name")
            else:
                value = row if isinstance(row, str) else None
            if value:
                records.append({"name": _canonical_name(str(value)), "category": subtype})
    return _merge_catalogues(pd.DataFrame(records, columns=["name", "category"]), _seed_catalogue())


@lru_cache(maxsize=8)
def _discover_index_catalogue_memory(timeout: int | tuple[float, float]) -> pd.DataFrame:
    return _discover_index_catalogue_uncached(timeout=timeout)


def discover_index_catalogue(timeout: int | tuple[float, float] = DEFAULT_TIMEOUT, cache_seconds: int = CATALOGUE_CACHE_SECONDS, force_refresh: bool = False) -> pd.DataFrame:
    if not force_refresh:
        cached = read_json_cache(CATALOGUE_CACHE_FILE, max_age_seconds=cache_seconds)
        if isinstance(cached, dict) and isinstance(cached.get("records"), list):
            frame = _merge_catalogues(pd.DataFrame(cached["records"], columns=["name", "category"]), _seed_catalogue())
            if not frame.empty:
                return frame
        memory = _discover_index_catalogue_memory(timeout)
        if not memory.empty:
            return memory
    frame = _discover_index_catalogue_uncached(timeout=timeout)
    if not frame.empty:
        write_json_cache({"updated_utc": pd.Timestamp.now(tz="UTC").isoformat(), "records": frame.to_dict(orient="records")}, CATALOGUE_CACHE_FILE)
        _discover_index_catalogue_memory.cache_clear()
    return frame


def resolve_catalogue_name(name: str, catalogue: pd.DataFrame | None = None) -> str | None:
    requested = _canonical_name(name)
    key = str(name).strip().casefold()
    alias_target = INDEX_NAME_ALIASES.get(key)
    requested_norm = normalize_index_name(alias_target or requested)
    if catalogue is None or catalogue.empty:
        return alias_target or requested
    names = [str(value) for value in catalogue.get("name", pd.Series(dtype=str)).dropna()]
    if not names:
        return alias_target or requested
    normalized = {normalize_index_name(candidate): candidate for candidate in names}
    exact = normalized.get(requested_norm)
    if exact:
        return exact
    if alias_target and normalize_index_name(alias_target) in normalized:
        return normalized[normalize_index_name(alias_target)]
    scored: list[tuple[float, str]] = []
    request_tokens = set(requested_norm.split())
    for candidate in names:
        candidate_norm = normalize_index_name(candidate)
        candidate_tokens = set(candidate_norm.split())
        union = request_tokens | candidate_tokens
        overlap = len(request_tokens & candidate_tokens) / max(len(union), 1)
        sequence = SequenceMatcher(None, requested_norm, candidate_norm).ratio()
        scored.append((0.65 * overlap + 0.35 * sequence, candidate))
    if not scored:
        return alias_target or requested
    score, candidate = max(scored, key=lambda item: item[0])
    return candidate if score >= 0.72 else (alias_target or requested)


def resolve_index_names(name: str, catalogue: pd.DataFrame | None = None) -> list[str]:
    key = str(name).strip().casefold()
    candidates = list(INDEX_NAME_ALTERNATES.get(key, ()))
    resolved = resolve_catalogue_name(name, catalogue=catalogue)
    if resolved:
        candidates.insert(0, resolved)
    if key in INDEX_NAME_ALIASES:
        candidates.append(INDEX_NAME_ALIASES[key])
    candidates.append(_canonical_name(name))
    return list(dict.fromkeys(candidates))


def _request_endpoint(endpoint_candidates: Sequence[str], name: str, start: date, end: date, timeout: int | tuple[float, float]) -> list[dict[str, object]]:
    payload = {"cinfo": "{'name':'%s','startDate':'%s','endDate':'%s','indexName':'%s'}" % (name, start.strftime("%d-%b-%Y"), end.strftime("%d-%b-%Y"), name)}
    last_error: Exception | None = None
    for endpoint in endpoint_candidates:
        session = _make_session()
        try:
            response = session.post(endpoint, headers=HEADERS, json=payload, timeout=timeout)
            response.raise_for_status()
            rows = _parse_api_payload(response.json())
            if rows:
                return [row for row in rows if isinstance(row, dict)]
        except Exception as exc:
            last_error = exc
    if last_error:
        raise RuntimeError(f"NiftyIndices endpoint failed for {name!r}: {last_error}") from last_error
    return []


def _rows_to_series(name: str, rows: list[dict[str, object]], tri: bool = False) -> pd.Series:
    if not rows:
        return pd.Series(dtype="float64", name=name)
    frame = pd.DataFrame(rows)
    date_columns = ["Date", "HistoricalDate", "EOD_TIMESTAMP"] if tri else ["HistoricalDate", "Date", "EOD_TIMESTAMP"]
    dates = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    for column in date_columns:
        if column not in frame:
            continue
        raw = frame[column].astype("string")
        for fmt in ("%d %b %Y", "%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
            dates = dates.fillna(pd.to_datetime(raw, format=fmt, errors="coerce"))
    close_columns = ["TotalReturnsIndex", "TRI", "NTR_Value"] if tri else ["CLOSE", "Close", "Closing Index Value", "EOD_CLOSE_INDEX_VAL"]
    values = pd.Series(pd.NA, index=frame.index, dtype="object")
    for column in close_columns:
        if column in frame:
            values = values.fillna(frame[column])
    numeric = pd.to_numeric(values.astype("string").str.replace(",", "", regex=False), errors="coerce")
    valid = dates.notna() & numeric.notna() & numeric.gt(0)
    if not valid.any():
        return pd.Series(dtype="float64", name=name)
    series = pd.Series(numeric.loc[valid].to_numpy(dtype=float), index=pd.DatetimeIndex(dates.loc[valid]), name=name)
    return series[~series.index.duplicated(keep="last")].sort_index()


def _request_history(name: str, start: date, end: date, timeout: int | tuple[float, float], tri: bool) -> pd.Series:
    return _rows_to_series(name, _request_endpoint(TRI_ENDPOINTS if tri else PRICE_ENDPOINTS, name, start, end, timeout), tri=tri)


def fetch_nifty_index_history(name: str, years: int = 5, start: date | None = None, end: date | None = None, retries: int = 1, timeout: int | tuple[float, float] = DEFAULT_TIMEOUT, catalogue: pd.DataFrame | None = None) -> pd.Series:
    end_date = end or date.today()
    start_date = start or (end_date - timedelta(days=365 * years + 10))
    catalogue_frame = catalogue if catalogue is not None else discover_index_catalogue(timeout=timeout)
    candidates = resolve_index_names(name, catalogue=catalogue_frame)
    last_error: Exception | None = None
    for _ in range(max(retries, 1)):
        for candidate in candidates:
            try:
                tri_series = _request_history(candidate, start_date, end_date, timeout=timeout, tri=True)
                if tri_series.dropna().size >= MIN_OBSERVATIONS:
                    tri_series.attrs["source"] = "niftyindices_tri"
                    tri_series.attrs["resolved_name"] = candidate
                    return tri_series
                price_series = _request_history(candidate, start_date, end_date, timeout=timeout, tri=False)
                if price_series.dropna().size >= MIN_OBSERVATIONS:
                    price_series.attrs["source"] = "niftyindices_pr"
                    price_series.attrs["resolved_name"] = candidate
                    return price_series
            except Exception as exc:
                last_error = exc
    raise RuntimeError(f"Nifty Indices request failed for {name!r}: {last_error or 'no usable history'}")


def fetch_nse_api_index_history(name: str, start: date, end: date, timeout: int | tuple[float, float] = DEFAULT_TIMEOUT, catalogue: pd.DataFrame | None = None) -> pd.Series:
    catalogue_frame = catalogue if catalogue is not None else discover_index_catalogue(timeout=timeout)
    candidates = resolve_index_names(name, catalogue=catalogue_frame)
    for index_type in candidates:
        session = _make_session()
        try:
            response = session.get(
                NSE_API_URL,
                params={"indexType": index_type, "from": start.strftime("%d-%m-%Y"), "to": end.strftime("%d-%m-%Y")},
                headers=NSE_HEADERS,
                timeout=timeout,
            )
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            rows = data.get("indexCloseOnlineRecords", []) if isinstance(data, dict) else []
            series = _rows_to_series(name, rows) if isinstance(rows, list) else pd.Series(dtype="float64", name=name)
            if series.dropna().size >= MIN_OBSERVATIONS:
                series.attrs["source"] = "nse_api"
                series.attrs["resolved_name"] = index_type
                return series
        except Exception:
            continue
    return pd.Series(dtype="float64", name=name)


def _api_fetch_one(exposure_id: str, index_name: str, start: date, end: date, catalogue: pd.DataFrame) -> tuple[str, str, pd.Series]:
    return exposure_id, index_name, fetch_nse_api_index_history(index_name, start, end, catalogue=catalogue)


def fetch_nse_api_indices(names: Mapping[str, str], start: date, end: date, workers: int = 4) -> tuple[pd.DataFrame, dict[str, str]]:
    if not names:
        return pd.DataFrame(), {}
    results: dict[str, pd.Series] = {}
    unresolved: dict[str, str] = {}
    catalogue = discover_index_catalogue()
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_api_fetch_one, exposure_id, index_name, start, end, catalogue) for exposure_id, index_name in names.items()]
        for future in as_completed(futures):
            exposure_id, index_name, series = future.result()
            if series.dropna().size >= MIN_OBSERVATIONS:
                results[exposure_id] = series.rename(exposure_id)
            else:
                unresolved[exposure_id] = index_name
    return pd.DataFrame(results).sort_index(), unresolved


def _fetch_archive_day(day: pd.Timestamp, wanted: set[str], timeout: int | tuple[float, float]) -> pd.DataFrame:
    session = _make_session(requests.Session())
    for template in NSE_ARCHIVE_URLS:
        try:
            response = session.get(template.format(date=day.strftime("%d%m%Y")), headers={**NSE_HEADERS, "Accept": "text/csv,*/*;q=0.8"}, timeout=timeout)
            if response.status_code != 200 or len(response.content) < 300:
                continue
            frame = pd.read_csv(StringIO(response.content.decode("utf-8", errors="replace")))
            if "Index Name" not in frame.columns or "Closing Index Value" not in frame.columns:
                continue
            frame["_canonical"] = frame["Index Name"].astype(str).map(_canonical_name)
            selected = frame[frame["_canonical"].isin(wanted)].copy()
            if selected.empty:
                continue
            raw_date = selected["Index Date"].astype("string")
            selected["date"] = pd.to_datetime(raw_date, format="%d-%b-%Y", errors="coerce").fillna(pd.to_datetime(raw_date, format="%d-%m-%Y", errors="coerce"))
            selected["close"] = pd.to_numeric(selected["Closing Index Value"], errors="coerce")
            return selected.dropna(subset=["date", "close"])[["_canonical", "date", "close"]]
        except Exception:
            continue
    return pd.DataFrame()


def fetch_nse_archive_indices(names: Iterable[str], start: date, end: date, timeout: int | tuple[float, float] = DEFAULT_TIMEOUT, workers: int = 12) -> pd.DataFrame:
    wanted = {_canonical_name(name): name for name in names}
    if not wanted:
        return pd.DataFrame()
    days = list(pd.bdate_range(start=max(start, end - timedelta(days=ARCHIVE_FALLBACK_DAYS)), end=end))
    rows: list[pd.DataFrame] = []
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(_fetch_archive_day, day, set(wanted), timeout) for day in days]
        for future in as_completed(futures):
            frame = future.result()
            if not frame.empty:
                rows.append(frame)
    if not rows:
        return pd.DataFrame()
    all_rows = pd.concat(rows, ignore_index=True).drop_duplicates(subset=["_canonical", "date"])
    return pd.DataFrame({original: all_rows.loc[all_rows["_canonical"].eq(canonical)].set_index("date")["close"].sort_index() for canonical, original in wanted.items() if not all_rows.loc[all_rows["_canonical"].eq(canonical)].empty}).sort_index()


def _yahoo_candidates(exposure_id: str, index_name: str) -> list[str]:
    candidates: list[str] = []
    explicit = YAHOO_INDEX_SYMBOLS.get(exposure_id)
    if explicit:
        candidates.append(explicit)
    canonical = _canonical_name(index_name)
    slug = re.sub(r"[^A-Z0-9]+", "_", canonical.replace("NIFTY ", "")).strip("_")
    if slug:
        candidates.append(f"NIFTY_{slug}.NS")
    # Legacy CNX names are still used by Yahoo for several established sectors.
    legacy = {
        "NIFTY CEMENT": "^CNXCEMENT",
        "NIFTY CAPITAL GOODS": "^CNXCAPGOODS",
        "NIFTY POWER": "^CNXPOWER",
        "NIFTY CONSUMER SERVICES": "^CNXSERVICE",
        "NIFTY INDIA CONSUMPTION": "^CNXCONSUMP",
    }
    if canonical in legacy:
        candidates.append(legacy[canonical])
    return list(dict.fromkeys(candidates))


def _fetch_yahoo_fallback(names: Mapping[str, str], years: int) -> tuple[pd.DataFrame, dict[str, str]]:
    if not names:
        return pd.DataFrame(), {}
    try:
        import yfinance as yf
    except ImportError:
        return pd.DataFrame(), {}
    symbol_to_exposures: dict[str, list[str]] = {}
    for exposure_id, index_name in names.items():
        for symbol in _yahoo_candidates(exposure_id, index_name):
            symbol_to_exposures.setdefault(symbol, []).append(exposure_id)
    if not symbol_to_exposures:
        return pd.DataFrame(), {}
    start = date.today() - timedelta(days=365 * years + 10)
    try:
        market = yf.download(
            list(symbol_to_exposures),
            start=start.isoformat(),
            end=(date.today() + timedelta(days=1)).isoformat(),
            auto_adjust=True,
            progress=False,
            group_by="column",
            threads=True,
            timeout=10,
        )
    except Exception:
        return pd.DataFrame(), {}
    if market.empty:
        return pd.DataFrame(), {}
    if isinstance(market.columns, pd.MultiIndex):
        close = market["Close"] if "Close" in market.columns.get_level_values(0) else market.xs("Close", axis=1, level=0)
    else:
        close = market[["Close"]].rename(columns={"Close": next(iter(symbol_to_exposures))})
    close.index = pd.to_datetime(close.index).tz_localize(None)
    result: dict[str, pd.Series] = {}
    source: dict[str, str] = {}
    for symbol, exposure_ids in symbol_to_exposures.items():
        if symbol not in close:
            continue
        series = close[symbol].dropna()
        if series.size < MIN_OBSERVATIONS:
            continue
        for exposure_id in exposure_ids:
            result[exposure_id] = series.rename(exposure_id)
            source[exposure_id] = "yahoo"
    return pd.DataFrame(result).sort_index(), source


def _load_seed_indices(names: Mapping[str, str]) -> tuple[pd.DataFrame, dict[str, str]]:
    """Load real historical seed data when a packaged seed exists.

    The seed is deliberately never synthesized: using a fabricated series would
    corrupt the quantitative audit. Supported files contain either exposure-id
    columns or official benchmark-name columns.
    """
    for path in SEED_PATHS:
        if not path.exists():
            continue
        try:
            frame = pd.read_parquet(path)
        except Exception:
            continue
        if frame.empty:
            continue
        frame.index = pd.to_datetime(frame.index).tz_localize(None)
        output: dict[str, pd.Series] = {}
        sources: dict[str, str] = {}
        for exposure_id, index_name in names.items():
            candidates = [exposure_id, index_name, _canonical_name(index_name)] + resolve_index_names(index_name)
            matched = next((candidate for candidate in candidates if candidate in frame.columns), None)
            if matched is None:
                continue
            series = pd.to_numeric(frame[matched], errors="coerce").dropna()
            if series.size >= MIN_OBSERVATIONS:
                output[exposure_id] = series.rename(exposure_id)
                sources[exposure_id] = "seed_cache"
        if output:
            return pd.DataFrame(output).sort_index(), sources
    return pd.DataFrame(), {}


def fetch_missing_indices(names: Mapping[str, str] | Iterable[tuple[str, str]], existing: pd.DataFrame | None = None, years: int = 5) -> pd.DataFrame:
    mapping = dict(names)
    frame = existing.copy() if existing is not None else pd.DataFrame()
    source_by_exposure: dict[str, str] = {str(k): str(v) for k, v in frame.attrs.get("source_by_exposure", {}).items()}
    resolved_by_exposure: dict[str, str] = {str(k): str(v) for k, v in frame.attrs.get("resolved_name_by_exposure", {}).items()}
    catalogue = discover_index_catalogue()
    missing = {
        exposure_id: index_name
        for exposure_id, index_name in mapping.items()
        if exposure_id not in frame.columns or frame[exposure_id].dropna().size < MIN_OBSERVATIONS
    }

    def fetch_one(exposure_id: str, index_name: str) -> tuple[str, str, pd.Series]:
        try:
            return exposure_id, index_name, fetch_nifty_index_history(index_name, years=years, retries=1, catalogue=catalogue)
        except Exception:
            return exposure_id, index_name, pd.Series(dtype="float64", name=index_name)

    if missing:
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(fetch_one, exposure_id, index_name) for exposure_id, index_name in missing.items()]
            for future in as_completed(futures):
                exposure_id, index_name, series = future.result()
                if series.dropna().size >= MIN_OBSERVATIONS:
                    frame = frame.drop(columns=[exposure_id], errors="ignore").join(series.rename(exposure_id), how="outer")
                    source_by_exposure[exposure_id] = str(series.attrs.get("source", "niftyindices"))
                    resolved_by_exposure[exposure_id] = str(series.attrs.get("resolved_name", resolve_catalogue_name(index_name, catalogue=catalogue) or index_name))
                    missing.pop(exposure_id, None)

    if missing:
        start = date.today() - timedelta(days=365 * years + 10)
        api_frame, _ = fetch_nse_api_indices(missing, start=start, end=date.today())
        if not api_frame.empty:
            frame = frame.join(api_frame, how="outer")
            for exposure_id in api_frame.columns:
                source_by_exposure[exposure_id] = "nse_api"
                resolved_by_exposure[exposure_id] = resolve_catalogue_name(mapping[exposure_id], catalogue=catalogue) or mapping[exposure_id]
                missing.pop(exposure_id, None)

    if missing:
        yahoo_frame, yahoo_sources = _fetch_yahoo_fallback(missing, years=years)
        if not yahoo_frame.empty:
            frame = frame.join(yahoo_frame, how="outer")
            for exposure_id in yahoo_frame.columns:
                source_by_exposure[exposure_id] = yahoo_sources.get(exposure_id, "yahoo")
                resolved_by_exposure[exposure_id] = resolve_catalogue_name(mapping[exposure_id], catalogue=catalogue) or mapping[exposure_id]
                missing.pop(exposure_id, None)

    if missing:
        archive = fetch_nse_archive_indices([mapping[key] for key in missing], start=date.today() - timedelta(days=ARCHIVE_FALLBACK_DAYS), end=date.today())
        for exposure_id, index_name in list(missing.items()):
            candidates = resolve_index_names(index_name, catalogue=catalogue)
            matched = next((candidate for candidate in candidates if candidate in archive.columns), None)
            if matched is not None and archive[matched].dropna().size >= MIN_OBSERVATIONS:
                frame = frame.drop(columns=[exposure_id], errors="ignore").join(archive[matched].rename(exposure_id), how="outer")
                source_by_exposure[exposure_id] = "nse_archive"
                resolved_by_exposure[exposure_id] = matched
                missing.pop(exposure_id, None)

    if missing:
        seed_frame, seed_sources = _load_seed_indices(missing)
        if not seed_frame.empty:
            frame = frame.join(seed_frame, how="outer")
            for exposure_id in seed_frame.columns:
                source_by_exposure[exposure_id] = seed_sources[exposure_id]
                resolved_by_exposure[exposure_id] = resolve_catalogue_name(mapping[exposure_id], catalogue=catalogue) or mapping[exposure_id]

    for exposure_id, index_name in mapping.items():
        if exposure_id in frame.columns and frame[exposure_id].dropna().size >= MIN_OBSERVATIONS:
            source_by_exposure.setdefault(exposure_id, "niftyindices")
            resolved_by_exposure.setdefault(exposure_id, resolve_catalogue_name(index_name, catalogue=catalogue) or index_name)

    frame.attrs["source_by_exposure"] = source_by_exposure
    frame.attrs["resolved_name_by_exposure"] = resolved_by_exposure
    return frame.sort_index()
