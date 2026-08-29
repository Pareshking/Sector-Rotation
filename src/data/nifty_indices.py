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
except ImportError:  # pragma: no cover - optional hardening dependency
    cloudscraper = None

from src.data.cache import read_json_cache, write_json_cache

BASE_URLS = ("https://www.niftyindices.com", "https://niftyindices.com")
BASE_URL = BASE_URLS[0]
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

HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
    "Connection": "keep-alive",
    "Content-Type": "application/json; charset=UTF-8",
    "Origin": BASE_URL,
    "Referer": HISTORICAL_PAGE,
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
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

# Only symbols that are established Yahoo index symbols are included. Newer/thematic
# indices deliberately remain on official Nifty/NSE paths rather than substituting an ETF.
YAHOO_INDEX_SYMBOLS: dict[str, str] = {
    "auto": "^CNXAUTO",
    "bank": "^NSEBANK",
    "financial-services": "^CNXFINANCE",
    "fmcg": "^CNXFMCG",
    "it": "^CNXIT",
    "media": "^CNXMEDIA",
    "metal": "^CNXMETAL",
    "pharma": "^CNXPHARMA",
    "psu-bank": "^CNXPSUBANK",
    "realty": "^CNXREALTY",
    "oil-gas": "^CNXENERGY",
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


def _make_session() -> requests.Session:
    if cloudscraper is not None:
        session = cloudscraper.create_scraper(browser={"browser": "chrome", "platform": "windows", "mobile": False})
    else:
        session = requests.Session()
    session.headers.update(HEADERS)
    try:
        session.get(HISTORICAL_PAGE, headers=HEADERS, timeout=DEFAULT_TIMEOUT, allow_redirects=True)
    except requests.RequestException:
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
            if isinstance(row, dict):
                value = row.get("indextype") or row.get("indexType") or row.get("name")
                if value:
                    subtypes.append(str(value).strip())
            elif isinstance(row, str) and row.strip():
                subtypes.append(row.strip())
    except (requests.RequestException, ValueError, json.JSONDecodeError):
        pass
    if not subtypes:
        subtypes = ["Broad Market Indices", "Sectoral Indices", "Thematic Indices", "Strategy Indices"]

    records: list[dict[str, str]] = []
    seen: set[str] = set()
    for subtype in dict.fromkeys(subtypes):
        payload = {"cinfo": {"indextype": subtype, "indexgroup": "Equity"}}
        try:
            rows = _post_json(INDEX_CATALOGUE_ENDPOINT, payload, timeout=timeout)
        except (requests.RequestException, ValueError, json.JSONDecodeError):
            rows = []
        for row in rows:
            if isinstance(row, dict):
                value = row.get("indextype") or row.get("indexType") or row.get("indexName") or row.get("Index Name") or row.get("name")
            else:
                value = row if isinstance(row, str) else None
            if not value:
                continue
            name = _canonical_name(str(value))
            key = normalize_index_name(name)
            if key and key not in seen:
                records.append({"name": name, "category": subtype})
                seen.add(key)
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
    alias_target = INDEX_NAME_ALIASES.get(str(name).strip().casefold())
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
    if alias_target:
        alias_match = normalized.get(normalize_index_name(alias_target))
        if alias_match:
            return alias_match
    request_tokens = set(requested_norm.split())
    scored: list[tuple[float, str]] = []
    for candidate in names:
        candidate_norm = normalize_index_name(candidate)
        candidate_tokens = set(candidate_norm.split())
        union = request_tokens | candidate_tokens
        overlap = len(request_tokens & candidate_tokens) / max(len(union), 1)
        sequence = SequenceMatcher(None, requested_norm, candidate_norm).ratio()
        scored.append((0.65 * overlap + 0.35 * sequence, candidate))
    if not scored:
        return alias_target or requested
    best_score, best_name = max(scored, key=lambda item: item[0])
    return best_name if best_score >= 0.72 else (alias_target or requested)


def resolve_index_names(name: str, catalogue: pd.DataFrame | None = None) -> list[str]:
    key = str(name).strip().casefold()
    candidates: list[str] = list(INDEX_NAME_ALTERNATES.get(key, ()))
    resolved = resolve_catalogue_name(name, catalogue=catalogue)
    if resolved:
        candidates.insert(0, resolved)
    alias_target = INDEX_NAME_ALIASES.get(key)
    if alias_target:
        candidates.append(alias_target)
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
        except (requests.RequestException, json.JSONDecodeError, ValueError) as exc:
            last_error = exc
    if last_error:
        raise RuntimeError(f"NiftyIndices endpoint failed for {name!r}: {last_error}") from last_error
    return []


def _rows_to_series(name: str, rows: list[dict[str, object]], tri: bool = False) -> pd.Series:
    if not rows:
        return pd.Series(dtype="float64", name=name)
    frame = pd.DataFrame(rows)
    date_columns = ["Date", "HistoricalDate", "EOD_TIMESTAMP"] if tri else ["HistoricalDate", "Date", "EOD_TIMESTAMP"]
    date_values = pd.Series(pd.NaT, index=frame.index, dtype="datetime64[ns]")
    for column in date_columns:
        if column not in frame:
            continue
        raw_dates = frame[column].astype("string")
        for fmt in ("%d %b %Y", "%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d"):
            date_values = date_values.fillna(pd.to_datetime(raw_dates, format=fmt, errors="coerce"))
    close_columns = ["TotalReturnsIndex", "TRI", "NTR_Value"] if tri else ["CLOSE", "Close", "Closing Index Value", "EOD_CLOSE_INDEX_VAL"]
    close_values = pd.Series(pd.NA, index=frame.index, dtype="object")
    for column in close_columns:
        if column in frame:
            close_values = close_values.fillna(frame[column])
    close_numeric = pd.to_numeric(close_values.astype("string").str.replace(",", "", regex=False), errors="coerce")
    valid = date_values.notna() & close_numeric.notna() & close_numeric.gt(0)
    if not valid.any():
        return pd.Series(dtype="float64", name=name)
    series = pd.Series(close_numeric.loc[valid].to_numpy(dtype=float), index=pd.DatetimeIndex(date_values.loc[valid]), name=name)
    return series[~series.index.duplicated(keep="last")].sort_index()


def _request_history(name: str, start: date, end: date, timeout: int | tuple[float, float], tri: bool) -> pd.Series:
    return _rows_to_series(name, _request_endpoint(TRI_ENDPOINTS if tri else PRICE_ENDPOINTS, name, start, end, timeout), tri=tri)


def fetch_nifty_index_history(name: str, years: int = 5, start: date | None = None, end: date | None = None, retries: int = 1, timeout: int | tuple[float, float] = DEFAULT_TIMEOUT, catalogue: pd.DataFrame | None = None) -> pd.Series:
    end_date = end or date.today()
    start_date = start or (end_date - timedelta(days=365 * years + 10))
    catalogue_frame = catalogue if catalogue is not None else discover_index_catalogue(timeout=timeout)
    candidates = resolve_index_names(name, catalogue=catalogue_frame)
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
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
            except (RuntimeError, requests.RequestException, ValueError) as exc:
                last_error = exc
    raise RuntimeError(f"Nifty Indices request failed for {name!r}: {last_error or 'no usable history'}")


def fetch_nse_api_index_history(name: str, start: date, end: date, timeout: int | tuple[float, float] = DEFAULT_TIMEOUT, catalogue: pd.DataFrame | None = None) -> pd.Series:
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    try:
        session.get("https://www.nseindia.com/", headers=NSE_HEADERS, timeout=DEFAULT_TIMEOUT)
    except requests.RequestException:
        pass
    catalogue_frame = catalogue if catalogue is not None else discover_index_catalogue(timeout=timeout)
    for index_type in resolve_index_names(name, catalogue=catalogue_frame):
        try:
            response = session.get(NSE_API_URL, params={"indexType": index_type, "from": start.strftime("%d-%m-%Y"), "to": end.strftime("%d-%m-%Y")}, headers=NSE_HEADERS, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data", {}) if isinstance(payload, dict) else {}
            rows = data.get("indexCloseOnlineRecords", []) if isinstance(data, dict) else []
            series = _rows_to_series(name, rows) if isinstance(rows, list) else pd.Series(dtype="float64", name=name)
            if series.dropna().size >= MIN_OBSERVATIONS:
                series.attrs["source"] = "nse_api"
                series.attrs["resolved_name"] = index_type
                return series
        except (requests.RequestException, ValueError, json.JSONDecodeError):
            continue
    return pd.Series(dtype="float64", name=name)


def _api_fetch_one(exposure_id: str, index_name: str, start: date, end: date, catalogue: pd.DataFrame) -> tuple[str, str, pd.Series]:
    try:
        series = fetch_nse_api_index_history(index_name, start, end, catalogue=catalogue)
    except (RuntimeError, requests.RequestException, ValueError):
        series = pd.Series(dtype="float64", name=index_name)
    return exposure_id, index_name, series


def fetch_nse_api_indices(names: Mapping[str, str], start: date, end: date, workers: int = 4) -> tuple[pd.DataFrame, dict[str, str]]:
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
    session = requests.Session()
    session.headers.update(NSE_HEADERS)
    content: bytes | None = None
    for template in NSE_ARCHIVE_URLS:
        try:
            response = session.get(template.format(date=day.strftime("%d%m%Y")), headers={**NSE_HEADERS, "Accept": "text/csv,*/*;q=0.8"}, timeout=timeout)
            if response.status_code == 200 and len(response.content) >= 300:
                content = response.content
                break
        except requests.RequestException:
            continue
    if content is None:
        return pd.DataFrame()
    try:
        frame = pd.read_csv(StringIO(content.decode("utf-8", errors="replace")))
        if "Index Name" not in frame.columns or "Closing Index Value" not in frame.columns:
            return pd.DataFrame()
        frame["_canonical"] = frame["Index Name"].astype(str).map(_canonical_name)
        selected = frame[frame["_canonical"].isin(wanted)].copy()
        if selected.empty:
            return pd.DataFrame()
        raw_date = selected["Index Date"].astype("string")
        selected["date"] = pd.to_datetime(raw_date, format="%d-%b-%Y", errors="coerce").fillna(pd.to_datetime(raw_date, format="%d-%m-%Y", errors="coerce"))
        selected["close"] = pd.to_numeric(selected["Closing Index Value"], errors="coerce")
        return selected.dropna(subset=["date", "close"])[["_canonical", "date", "close"]]
    except (UnicodeDecodeError, ValueError, pd.errors.ParserError):
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


def _fetch_yahoo_fallback(names: Mapping[str, str], years: int) -> tuple[pd.DataFrame, dict[str, str]]:
    if not names:
        return pd.DataFrame(), {}
    try:
        import yfinance as yf
    except ImportError:
        return pd.DataFrame(), {}
    symbols = {exposure_id: YAHOO_INDEX_SYMBOLS.get(exposure_id) for exposure_id in names}
    symbols = {key: value for key, value in symbols.items() if value}
    if not symbols:
        return pd.DataFrame(), {}
    start = date.today() - timedelta(days=365 * years + 10)
    try:
        market = yf.download(list(symbols.values()), start=start.isoformat(), end=(date.today() + timedelta(days=1)).isoformat(), auto_adjust=True, progress=False, group_by="column", threads=True, timeout=10)
    except Exception:
        return pd.DataFrame(), {}
    if market.empty:
        return pd.DataFrame(), {}
    if isinstance(market.columns, pd.MultiIndex):
        close = market["Close"] if "Close" in market.columns.get_level_values(0) else market.xs("Close", axis=1, level=0)
    else:
        close = market[["Close"]].rename(columns={"Close": next(iter(symbols.values()))})
    close.index = pd.to_datetime(close.index).tz_localize(None)
    result: dict[str, pd.Series] = {}
    source: dict[str, str] = {}
    for exposure_id, symbol in symbols.items():
        if symbol not in close:
            continue
        series = close[symbol].dropna()
        if series.size >= MIN_OBSERVATIONS:
            result[exposure_id] = series.rename(exposure_id)
            source[exposure_id] = "yahoo"
    return pd.DataFrame(result).sort_index(), source


def fetch_missing_indices(names: Mapping[str, str] | Iterable[tuple[str, str]], existing: pd.DataFrame | None = None, years: int = 5) -> pd.DataFrame:
    mapping = dict(names)
    frame = existing.copy() if existing is not None else pd.DataFrame()
    missing: dict[str, str] = {}
    source_by_exposure: dict[str, str] = {str(key): str(value) for key, value in frame.attrs.get("source_by_exposure", {}).items()}
    resolved_by_exposure: dict[str, str] = {str(key): str(value) for key, value in frame.attrs.get("resolved_name_by_exposure", {}).items()}
    catalogue = discover_index_catalogue()

    def fetch_one(exposure_id: str, index_name: str) -> tuple[str, str, pd.Series]:
        try:
            series = fetch_nifty_index_history(index_name, years=years, retries=1, catalogue=catalogue)
        except RuntimeError:
            series = pd.Series(dtype="float64", name=index_name)
        return exposure_id, index_name, series

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(fetch_one, exposure_id, index_name) for exposure_id, index_name in mapping.items() if exposure_id not in frame.columns or frame[exposure_id].dropna().size < MIN_OBSERVATIONS]
        for future in as_completed(futures):
            exposure_id, index_name, fetched = future.result()
            if fetched.dropna().size >= MIN_OBSERVATIONS:
                frame = frame.drop(columns=[exposure_id], errors="ignore").join(fetched.rename(exposure_id), how="outer")
                source_by_exposure[exposure_id] = str(fetched.attrs.get("source", "niftyindices"))
                resolved_by_exposure[exposure_id] = str(fetched.attrs.get("resolved_name", resolve_catalogue_name(index_name, catalogue=catalogue) or index_name))
            else:
                missing[exposure_id] = index_name

    if missing:
        api_frame, unresolved = fetch_nse_api_indices(missing, start=date.today() - timedelta(days=365 * years + 10), end=date.today())
        if not api_frame.empty:
            frame = frame.join(api_frame, how="outer")
            for exposure_id in api_frame.columns:
                source_by_exposure[exposure_id] = "nse_api"
                resolved_by_exposure[exposure_id] = resolve_catalogue_name(mapping[exposure_id], catalogue=catalogue) or mapping[exposure_id]
            missing = {key: value for key, value in missing.items() if key not in api_frame.columns}
        else:
            unresolved = missing

    if missing:
        yahoo_frame, yahoo_sources = _fetch_yahoo_fallback(missing, years=years)
        if not yahoo_frame.empty:
            frame = frame.join(yahoo_frame, how="outer")
            for exposure_id in yahoo_frame.columns:
                source_by_exposure[exposure_id] = yahoo_sources.get(exposure_id, "yahoo")
                resolved_by_exposure[exposure_id] = mapping[exposure_id]
            missing = {key: value for key, value in missing.items() if key not in yahoo_frame.columns}

    if missing:
        archive = fetch_nse_archive_indices(missing.values(), start=date.today() - timedelta(days=ARCHIVE_FALLBACK_DAYS), end=date.today())
        for exposure_id, index_name in list(missing.items()):
            candidates = resolve_index_names(index_name, catalogue=catalogue)
            matched = next((candidate for candidate in candidates if candidate in archive.columns), None)
            if matched is not None and archive[matched].dropna().size >= MIN_OBSERVATIONS:
                frame = frame.drop(columns=[exposure_id], errors="ignore").join(archive[matched].rename(exposure_id), how="outer")
                source_by_exposure[exposure_id] = "nse_archive"
                resolved_by_exposure[exposure_id] = matched

    for exposure_id in mapping:
        if exposure_id in frame.columns and frame[exposure_id].dropna().size >= MIN_OBSERVATIONS:
            source_by_exposure.setdefault(exposure_id, "niftyindices")
            resolved_by_exposure.setdefault(exposure_id, resolve_catalogue_name(mapping[exposure_id], catalogue=catalogue) or mapping[exposure_id])
    frame.attrs["source_by_exposure"] = source_by_exposure
    frame.attrs["resolved_name_by_exposure"] = resolved_by_exposure
    return frame.sort_index()
