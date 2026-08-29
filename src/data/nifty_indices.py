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
NSE_HEADERS = {"User-Agent": HEADERS["User-Agent"], "Accept": "application/json,text/plain,*/*", "Accept-Language": HEADERS["Accept-Language"], "Referer": "https://www.nseindia.com/", "Connection": "keep-alive"}

INDEX_NAME_ALIASES = {
    "telecom": "NIFTY TELECOMMUNICATIONS", "nifty telecom": "NIFTY TELECOMMUNICATIONS", "telecommunications": "NIFTY TELECOMMUNICATIONS", "nifty telecommunications": "NIFTY TELECOMMUNICATIONS",
    "nbfc": "NIFTY FINANCIAL SERVICES EX-BANK", "nifty nbfc": "NIFTY FINANCIAL SERVICES EX-BANK", "financial-services-ex-bank": "NIFTY FINANCIAL SERVICES EX-BANK", "nifty financial services ex-bank": "NIFTY FINANCIAL SERVICES EX-BANK",
    "healthcare": "NIFTY HEALTHCARE", "nifty healthcare": "NIFTY HEALTHCARE", "healthcare index": "NIFTY HEALTHCARE", "nifty healthcare index": "NIFTY HEALTHCARE",
    "power": "NIFTY POWER", "nifty power": "NIFTY POWER", "capital-goods": "NIFTY CAPITAL GOODS", "capital goods": "NIFTY CAPITAL GOODS", "nifty capital goods": "NIFTY CAPITAL GOODS",
    "consumer-services": "NIFTY CONSUMER SERVICES", "consumer services": "NIFTY CONSUMER SERVICES", "nifty consumer services": "NIFTY CONSUMER SERVICES", "financial-services": "NIFTY FINANCIAL SERVICES", "financial services": "NIFTY FINANCIAL SERVICES",
    "oil-gas": "NIFTY OIL & GAS", "nifty oil & gas": "NIFTY OIL & GAS", "defence": "NIFTY INDIA DEFENCE", "nifty defence": "NIFTY INDIA DEFENCE", "nifty india defence": "NIFTY INDIA DEFENCE",
    "ev-new-energy-auto": "NIFTY EV & NEW AGE AUTOMOTIVE", "nifty ev & new age automotive": "NIFTY EV & NEW AGE AUTOMOTIVE", "manufacturing": "NIFTY INDIA MANUFACTURING", "nifty india manufacturing": "NIFTY INDIA MANUFACTURING",
    "infrastructure": "NIFTY INFRASTRUCTURE", "infrastructure-logistics": "NIFTY INDIA INFRASTRUCTURE & LOGISTICS", "railways": "NIFTY INDIA RAILWAYS PSU", "consumption": "NIFTY INDIA CONSUMPTION", "digital": "NIFTY INDIA DIGITAL", "internet": "NIFTY INDIA INTERNET", "tourism": "NIFTY INDIA TOURISM",
    "energy": "NIFTY ENERGY", "commodities": "NIFTY COMMODITIES", "capital-markets": "NIFTY CAPITAL MARKETS", "mnc": "NIFTY MNC", "pse": "NIFTY PSE", "cpse": "NIFTY CPSE", "services": "NIFTY SERVICES SECTOR", "rural": "NIFTY RURAL", "mobility": "NIFTY MOBILITY", "reit-invit": "NIFTY REITS & INVITS", "nifty reits & invits": "NIFTY REITS & INVITS",
}
INDEX_NAME_ALTERNATES = {"healthcare": ("NIFTY HEALTHCARE", "NIFTY HEALTHCARE INDEX"), "nifty healthcare": ("NIFTY HEALTHCARE", "NIFTY HEALTHCARE INDEX"), "healthcare index": ("NIFTY HEALTHCARE", "NIFTY HEALTHCARE INDEX"), "nifty healthcare index": ("NIFTY HEALTHCARE", "NIFTY HEALTHCARE INDEX")}
VALID_YAHOO_INDEX_SYMBOLS = {"nifty50": "^NSEI", "niftybank": "^NSEBANK", "bank": "^NSEBANK", "it": "^CNXIT", "auto": "^CNXAUTO"}
YAHOO_INDEX_SYMBOLS = VALID_YAHOO_INDEX_SYMBOLS
AUTHORITATIVE_CATALOGUE_SEED = (
    ("NIFTY 50", "Broad Market Indices"), ("NIFTY AUTO", "Sectoral Indices"), ("NIFTY BANK", "Sectoral Indices"), ("NIFTY FINANCIAL SERVICES", "Sectoral Indices"), ("NIFTY FMCG", "Sectoral Indices"), ("NIFTY IT", "Sectoral Indices"), ("NIFTY MEDIA", "Sectoral Indices"), ("NIFTY METAL", "Sectoral Indices"), ("NIFTY PHARMA", "Sectoral Indices"), ("NIFTY PRIVATE BANK", "Sectoral Indices"), ("NIFTY PSU BANK", "Sectoral Indices"), ("NIFTY REALTY", "Sectoral Indices"), ("NIFTY CONSUMER DURABLES", "Sectoral Indices"), ("NIFTY OIL & GAS", "Sectoral Indices"), ("NIFTY HEALTHCARE", "Sectoral Indices"), ("NIFTY FINANCIAL SERVICES EX-BANK", "Sectoral Indices"), ("NIFTY CHEMICALS", "Sectoral Indices"), ("NIFTY CEMENT", "Sectoral Indices"), ("NIFTY TELECOMMUNICATIONS", "Sectoral Indices"), ("NIFTY POWER", "Sectoral Indices"), ("NIFTY NBFC", "Sectoral Indices"), ("NIFTY CONSUMER SERVICES", "Sectoral Indices"), ("NIFTY CAPITAL GOODS", "Sectoral Indices"), ("NIFTY INDIA DEFENCE", "Thematic Indices"), ("NIFTY EV & NEW AGE AUTOMOTIVE", "Thematic Indices"), ("NIFTY INDIA MANUFACTURING", "Thematic Indices"), ("NIFTY INFRASTRUCTURE", "Thematic Indices"), ("NIFTY INDIA INFRASTRUCTURE & LOGISTICS", "Thematic Indices"), ("NIFTY INDIA RAILWAYS PSU", "Thematic Indices"), ("NIFTY INDIA CONSUMPTION", "Thematic Indices"), ("NIFTY INDIA DIGITAL", "Thematic Indices"), ("NIFTY INDIA INTERNET", "Thematic Indices"), ("NIFTY INDIA TOURISM", "Thematic Indices"), ("NIFTY ENERGY", "Thematic Indices"), ("NIFTY COMMODITIES", "Thematic Indices"), ("NIFTY CAPITAL MARKETS", "Thematic Indices"), ("NIFTY MNC", "Thematic Indices"), ("NIFTY PSE", "Thematic Indices"), ("NIFTY CPSE", "Thematic Indices"), ("NIFTY SERVICES SECTOR", "Thematic Indices"), ("NIFTY RURAL", "Thematic Indices"), ("NIFTY MOBILITY", "Thematic Indices"), ("NIFTY REITS & INVITS", "Thematic Indices"),
)

def normalize_index_name(value: str) -> str:
    text = str(value).casefold().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\bindex\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def _canonical_name(name: str) -> str: return " ".join(str(name).strip().upper().split())

def _parse_api_payload(payload: object) -> list[object]:
    if isinstance(payload, list): return payload
    if not isinstance(payload, dict): return []
    raw = payload.get("d")
    if isinstance(raw, str):
        try: decoded = json.loads(raw)
        except json.JSONDecodeError: return []
        return decoded if isinstance(decoded, list) else []
    if isinstance(raw, list): return raw
    for key in ("data", "result", "results"):
        value = payload.get(key)
        if isinstance(value, list): return value
    return []

def _make_session(session=None):
    if session is None:
        session = cloudscraper.create_scraper(browser={"browser":"chrome","platform":"windows","mobile":False}) if cloudscraper is not None else requests.Session()
    headers = getattr(session, "headers", None)
    if hasattr(headers, "update"): headers.update(HEADERS)
    return session

def _post_json(url, payload, timeout=DEFAULT_TIMEOUT, session=None):
    try:
        response = _make_session(session).post(url, headers=HEADERS, json=payload, timeout=timeout); response.raise_for_status(); return _parse_api_payload(response.json())
    except Exception: return []

def _seed_catalogue(): return pd.DataFrame(AUTHORITATIVE_CATALOGUE_SEED, columns=["name","category"])

def _merge_catalogues(*frames):
    rows, seen = [], set()
    for frame in frames:
        if frame is None or frame.empty: continue
        for row in frame.to_dict(orient="records"):
            name=row.get("name")
            if not name: continue
            key=normalize_index_name(name)
            if key and key not in seen: rows.append({"name":_canonical_name(name),"category":str(row.get("category") or "")}); seen.add(key)
    return pd.DataFrame(rows, columns=["name","category"])

def _discover_index_catalogue_uncached(timeout=DEFAULT_TIMEOUT):
    subtypes=[]
    for row in _post_json(SUBTYPE_ENDPOINT,{"cinfo":{"indextype":"Equity","indexgroup":""}},timeout=timeout):
        value=(row.get("indextype") or row.get("indexType") or row.get("name")) if isinstance(row,dict) else row
        if value: subtypes.append(str(value).strip())
    if not subtypes: subtypes=["Broad Market Indices","Sectoral Indices","Thematic Indices","Strategy Indices"]
    records=[]
    for subtype in dict.fromkeys(subtypes):
        for row in _post_json(INDEX_CATALOGUE_ENDPOINT,{"cinfo":{"indextype":subtype,"indexgroup":"Equity"}},timeout=timeout):
            value=(row.get("indextype") or row.get("indexType") or row.get("indexName") or row.get("Index Name") or row.get("name")) if isinstance(row,dict) else row
            if value: records.append({"name":_canonical_name(value),"category":subtype})
    return _merge_catalogues(pd.DataFrame(records,columns=["name","category"]),_seed_catalogue())

@lru_cache(maxsize=8)
def _discover_index_catalogue_memory(timeout): return _discover_index_catalogue_uncached(timeout)

def discover_index_catalogue(force_refresh=False, cache_seconds=CATALOGUE_CACHE_SECONDS, timeout=DEFAULT_TIMEOUT):
    if not force_refresh and CATALOGUE_CACHE_FILE.exists():
        try:
            import time
            if time.time()-CATALOGUE_CACHE_FILE.stat().st_mtime<=cache_seconds:
                frame=pd.DataFrame(read_json_cache(CATALOGUE_CACHE_FILE))
                if not frame.empty: return frame
        except Exception: pass
    frame=_discover_index_catalogue_uncached(timeout) if force_refresh else _discover_index_catalogue_memory(timeout)
    if not frame.empty:
        try:
            CATALOGUE_CACHE_FILE.parent.mkdir(parents=True,exist_ok=True); write_json_cache(frame.to_dict(orient="records"),CATALOGUE_CACHE_FILE)
        except Exception: pass
    return frame

def resolve_catalogue_name(name,catalogue=None):
    key, alias_target=str(name).strip().casefold(),INDEX_NAME_ALIASES.get(str(name).strip().casefold())
    requested, requested_norm=_canonical_name(alias_target or name),normalize_index_name(alias_target or name)
    if catalogue is None or catalogue.empty: return alias_target or requested
    names=[str(v) for v in catalogue["name"].dropna().tolist()]; normalized={normalize_index_name(c):c for c in names}
    if requested_norm in normalized: return normalized[requested_norm]
    for candidate in INDEX_NAME_ALTERNATES.get(key,()):
        if normalize_index_name(candidate) in normalized: return normalized[normalize_index_name(candidate)]
    scored=[]
    for candidate in names:
        cn=normalize_index_name(candidate); overlap=len(set(requested_norm.split())&set(cn.split()))/max(len(set(requested_norm.split())|set(cn.split())),1); scored.append((.65*overlap+.35*SequenceMatcher(None,requested_norm,cn).ratio(),candidate))
    if scored:
        score,candidate=max(scored)
        if score>=.72: return candidate
    return alias_target or requested

def resolve_index_names(name,catalogue=None):
    key=str(name).strip().casefold(); candidates=list(INDEX_NAME_ALTERNATES.get(key,())); resolved=resolve_catalogue_name(name,catalogue)
    if resolved: candidates.insert(0,resolved)
    if key in INDEX_NAME_ALIASES: candidates.append(INDEX_NAME_ALIASES[key])
    candidates.append(_canonical_name(name)); return list(dict.fromkeys(candidates))

def _request_endpoint(endpoint_candidates,name,start,end,timeout=DEFAULT_TIMEOUT,session=None):
    payload={"cinfo":"{'name':'%s','startDate':'%s','endDate':'%s','indexName':'%s'}"%(name,start.strftime("%d-%b-%Y"),end.strftime("%d-%b-%Y"),name)}; s=_make_session(session)
    for endpoint in endpoint_candidates:
        try:
            response=s.post(endpoint,headers=HEADERS,json=payload,timeout=timeout); response.raise_for_status(); rows=_parse_api_payload(response.json())
            if rows: return [row for row in rows if isinstance(row,dict)]
        except Exception: continue
    return []

def _rows_to_series(name,rows,tri=False):
    if not rows: return pd.Series(dtype="float64",name=name)
    frame=pd.DataFrame(rows); dates=pd.Series(pd.NaT,index=frame.index,dtype="datetime64[ns]")
    for column in (["Date","HistoricalDate","EOD_TIMESTAMP"] if tri else ["HistoricalDate","Date","EOD_TIMESTAMP"]):
        if column in frame:
            raw=frame[column].astype("string")
            for fmt in ("%d %b %Y","%d-%b-%Y","%d-%m-%Y","%Y-%m-%d"): dates=dates.fillna(pd.to_datetime(raw,format=fmt,errors="coerce"))
    values=pd.Series(pd.NA,index=frame.index,dtype="object")
    for column in (["TotalReturnsIndex","TRI","NTR_Value"] if tri else ["CLOSE","Close","Closing Index Value","EOD_CLOSE_INDEX_VAL"]):
        if column in frame: values=values.fillna(frame[column])
    numeric=pd.to_numeric(values.astype("string").str.replace(",","",regex=False),errors="coerce"); valid=dates.notna()&numeric.notna()&numeric.gt(0)
    if not valid.any(): return pd.Series(dtype="float64",name=name)
    return pd.Series(numeric.loc[valid].to_numpy(float),index=pd.DatetimeIndex(dates.loc[valid]),name=name).groupby(level=0).last().sort_index()

def _request_history(name,start,end,timeout=DEFAULT_TIMEOUT,tri=True): return _rows_to_series(name,_request_endpoint(TRI_ENDPOINTS if tri else PRICE_ENDPOINTS,name,start,end,timeout),tri=tri)

def fetch_nifty_index_history(name,years=5,start=None,end=None,retries=1,timeout=DEFAULT_TIMEOUT,catalogue=None):
    end_date,end_start=end or date.today(),start or (end or date.today())-timedelta(days=365*years+10); catalogue_frame=catalogue if catalogue is not None else discover_index_catalogue(timeout=timeout)
    for _ in range(max(retries,1)):
        for candidate in resolve_index_names(name,catalogue_frame):
            tri=_request_history(candidate,end_start,end_date,timeout,True)
            if len(tri.dropna())>=MIN_OBSERVATIONS: tri.attrs.update(source="niftyindices_tri",resolved_name=candidate); return tri
            pr=_request_history(candidate,end_start,end_date,timeout,False)
            if len(pr.dropna())>=MIN_OBSERVATIONS: pr.attrs.update(source="niftyindices_pr",resolved_name=candidate); return pr
    return pd.Series(dtype="float64",name=name)

def fetch_nse_api_index_history(name,start,end,timeout=DEFAULT_TIMEOUT,catalogue=None):
    catalogue_frame=catalogue if catalogue is not None else discover_index_catalogue(timeout=timeout)
    for index_type in resolve_index_names(name,catalogue_frame):
        try:
            response=_make_session().get(NSE_API_URL,params={"indexType":index_type,"from":start.strftime("%d-%m-%Y"),"to":end.strftime("%d-%m-%Y")},headers=NSE_HEADERS,timeout=timeout); response.raise_for_status(); payload=response.json(); data=payload.get("data",{}) if isinstance(payload,dict) else {}; rows=data.get("indexCloseOnlineRecords",[]) if isinstance(data,dict) else []; series=_rows_to_series(name,rows)
            if len(series.dropna())>=MIN_OBSERVATIONS: series.attrs.update(source="nse_api",resolved_name=index_type); return series
        except Exception: continue
    return pd.Series(dtype="float64",name=name)

def fetch_nse_api_indices(names,start,end,workers=4):
    if not names: return pd.DataFrame(),{}
    catalogue=discover_index_catalogue(); results={}
    def one(item):
        eid,name=item; return eid,fetch_nse_api_index_history(name,start,end,catalogue=catalogue)
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures=[executor.submit(one,item) for item in names.items()]
        for future in as_completed(futures):
            try: eid,series=future.result()
            except Exception: continue
            if len(series.dropna())>=MIN_OBSERVATIONS: results[eid]=series.rename(eid)
    return pd.DataFrame(results).sort_index(),{eid:name for eid,name in names.items() if eid not in results}

def _fetch_archive_day(day,wanted,timeout):
    s=_make_session()
    for template in NSE_ARCHIVE_URLS:
        try:
            response=s.get(template.format(date=day.strftime("%d%m%Y")),headers={**NSE_HEADERS,"Accept":"text/csv,*/*;q=0.8"},timeout=timeout)
            if response.status_code!=200 or len(response.content)<300: continue
            frame=pd.read_csv(StringIO(response.content.decode("utf-8",errors="replace")))
            if "Index Name" not in frame.columns or "Closing Index Value" not in frame.columns: continue
            frame["_canonical"]=frame["Index Name"].astype(str).map(_canonical_name); selected=frame[frame["_canonical"].isin(wanted)].copy()
            if selected.empty: continue
            raw_date=selected["Index Date"].astype("string"); selected["date"]=pd.to_datetime(raw_date,format="%d-%b-%Y",errors="coerce").fillna(pd.to_datetime(raw_date,format="%d-%m-%Y",errors="coerce")); selected["close"]=pd.to_numeric(selected["Closing Index Value"],errors="coerce")
            return selected.dropna(subset=["date","close"])[["_canonical","date","close"]]
        except Exception: continue
    return pd.DataFrame()

def fetch_nse_archive_indices(names,start,end,timeout=DEFAULT_TIMEOUT,workers=12):
    wanted={_canonical_name(name):name for name in names}
    if not wanted: return pd.DataFrame()
    days=list(pd.bdate_range(start=max(start,end-timedelta(days=ARCHIVE_FALLBACK_DAYS)),end=end)); rows=[]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures=[executor.submit(_fetch_archive_day,day,set(wanted),timeout) for day in days]
        for future in as_completed(futures):
            try: frame=future.result()
            except Exception: frame=pd.DataFrame()
            if not frame.empty: rows.append(frame)
    if not rows: return pd.DataFrame()
    all_rows=pd.concat(rows,ignore_index=True).drop_duplicates(subset=["_canonical","date"])
    return pd.DataFrame({original:all_rows.loc[all_rows["_canonical"].eq(canonical)].set_index("date")["close"].sort_index() for canonical,original in wanted.items() if not all_rows.loc[all_rows["_canonical"].eq(canonical)].empty}).sort_index()

def _yahoo_candidates(exposure_id,index_name):
    symbol=VALID_YAHOO_INDEX_SYMBOLS.get(exposure_id); return [symbol] if symbol else []

def _fetch_yahoo_fallback(names,years):
    if not names: return pd.DataFrame(),{}
    try: import yfinance as yf
    except ImportError: return pd.DataFrame(),{}
    symbol_to_exposures={}
    for exposure_id,index_name in names.items():
        for symbol in _yahoo_candidates(exposure_id,index_name): symbol_to_exposures.setdefault(symbol,[]).append(exposure_id)
    if not symbol_to_exposures: return pd.DataFrame(),{}
    try:
        market=yf.download(list(symbol_to_exposures),start=(date.today()-timedelta(days=365*years+10)).isoformat(),end=(date.today()+timedelta(days=1)).isoformat(),auto_adjust=True,progress=False,group_by="column",threads=True,timeout=10)
    except Exception: return pd.DataFrame(),{}
    if market.empty: return pd.DataFrame(),{}
    if isinstance(market.columns,pd.MultiIndex): close=market["Close"] if "Close" in market.columns.get_level_values(0) else market.xs("Close",axis=1,level=0)
    else: close=market[["Close"]].rename(columns={"Close":next(iter(symbol_to_exposures))})
    close.index=pd.to_datetime(close.index).tz_localize(None); result,source={},{}
    for symbol,exposure_ids in symbol_to_exposures.items():
        if symbol not in close: continue
        series=close[symbol].dropna()
        if len(series)<MIN_OBSERVATIONS: continue
        for exposure_id in exposure_ids: result[exposure_id]=series.rename(exposure_id); source[exposure_id]="yahoo"
    return pd.DataFrame(result).sort_index(),source

ETF_PROXY_KEYS={"auto":("AUTOBEES","AUTOIETF"),"bank":("BANKBEES","BANKNIFTY1"),"fmcg":("FMCGIETF",),"healthcare":("HEALTHIETF","HEALTHADD"),"it":("ITBEES","SBIETFIT","TECH"),"metal":("METALIETF",),"pharma":("PHARMABEES",),"psu-bank":("PSUBNKBEES",),"infrastructure":("INFRABEES",),"consumption":("CONSUMBEES",),"ev-new-energy-auto":("EVINDIA",),"defence":("GROWWDEFNC","Motilal Oswal Nifty India Defence ETF"),"pse":("ICICIB22","MOPSE","GROWWPSE"),"cpse":("CPSEETF",)}

def _proxy_from_etfs(missing,etf_histories):
    if etf_histories is None or (isinstance(etf_histories,pd.DataFrame) and etf_histories.empty) or (isinstance(etf_histories,dict) and not etf_histories): return pd.DataFrame(),{}
    result,source={},{}
    for exposure_id in missing:
        for key in ETF_PROXY_KEYS.get(exposure_id,()):
            if key in etf_histories and len(etf_histories[key].dropna())>=MIN_OBSERVATIONS: result[exposure_id]=etf_histories[key].dropna().rename(exposure_id); source[exposure_id]="etf_proxy"; break
    return pd.DataFrame(result).sort_index(),source

def _load_seed_indices(names):
    for path in SEED_PATHS:
        if not path.exists(): continue
        try: frame=pd.read_parquet(path)
        except Exception: continue
        if frame.empty: continue
        frame.index=pd.to_datetime(frame.index).tz_localize(None); output,sources={},{}
        for exposure_id,index_name in names.items():
            matched=next((candidate for candidate in [exposure_id,index_name,_canonical_name(index_name)]+resolve_index_names(index_name) if candidate in frame.columns),None)
            if matched:
                series=pd.to_numeric(frame[matched],errors="coerce").dropna()
                if len(series)>=MIN_OBSERVATIONS: output[exposure_id]=series.rename(exposure_id); sources[exposure_id]="seed_cache"
        if output: return pd.DataFrame(output).sort_index(),sources
    return pd.DataFrame(),{}

# Broad, explicit fallback benchmarks. These use real resolved market observations;
# they are not synthetic index levels and are marked separately in metadata.
BENCHMARK_PROXY_MAP={
    "capital-goods":"auto","cement":"auto","chemicals":"metal","consumer-durables":"auto","consumer-services":"nifty50","media":"nifty50","oil-gas":"nifty50","power":"bank","private-bank":"bank","realty":"nifty50","telecom":"nifty50","manufacturing":"auto","infrastructure":"nifty50","infrastructure-logistics":"auto","railways":"bank","digital":"it","internet":"it","tourism":"nifty50","energy":"nifty50","commodities":"metal","capital-markets":"bank","mnc":"nifty50","services":"nifty50","rural":"fmcg","mobility":"auto","reit-invit":"nifty50",
}

def _proxy_from_resolved_indices(missing,frame,names):
    result,source,resolved={},{},{}
    for eid in missing:
        proxy_id=BENCHMARK_PROXY_MAP.get(eid)
        if proxy_id and proxy_id in frame and len(frame[proxy_id].dropna())>=MIN_OBSERVATIONS:
            result[eid]=frame[proxy_id].dropna().rename(eid); source[eid]="benchmark_proxy"; resolved[eid]=f"{names[eid]} <- {proxy_id} benchmark proxy"
    return pd.DataFrame(result).sort_index(),source,resolved

def fetch_missing_indices(names: Mapping[str,str] | Iterable[tuple[str,str]],existing=None,years=5,etf_histories=None):
    mapping,frame=dict(names),(existing.copy() if existing is not None else pd.DataFrame()); source_by_exposure=dict(frame.attrs.get("source_by_exposure",{})); resolved_by_exposure=dict(frame.attrs.get("resolved_name_by_exposure",{})); catalogue=discover_index_catalogue()
    missing={eid:name for eid,name in mapping.items() if eid not in frame.columns or len(frame[eid].dropna())<MIN_OBSERVATIONS}; start=date.today()-timedelta(days=365*years+10)
    if missing:
        def one(item):
            eid,name=item; return eid,fetch_nifty_index_history(name,years=years,start=start,end=date.today(),retries=1,catalogue=catalogue)
        with ThreadPoolExecutor(max_workers=min(5,len(missing))) as ex:
            futures=[ex.submit(one,item) for item in missing.items()]
            for fut in as_completed(futures):
                try: eid,series=fut.result()
                except Exception: continue
                if len(series.dropna())>=MIN_OBSERVATIONS:
                    frame=frame.drop(columns=[eid],errors="ignore").join(series.rename(eid),how="outer"); source_by_exposure[eid]=series.attrs.get("source","niftyindices"); resolved_by_exposure[eid]=series.attrs.get("resolved_name",mapping[eid]); missing.pop(eid,None)
    if missing:
        api_frame,_=fetch_nse_api_indices(missing,start,date.today(),workers=5)
        for eid in list(missing):
            if eid in api_frame and len(api_frame[eid].dropna())>=MIN_OBSERVATIONS:
                frame=frame.drop(columns=[eid],errors="ignore").join(api_frame[eid].rename(eid),how="outer"); source_by_exposure[eid]="nse_api"; resolved_by_exposure[eid]=mapping[eid]; missing.pop(eid,None)
    if missing:
        archive=fetch_nse_archive_indices([mapping[eid] for eid in missing],start=date.today()-timedelta(days=ARCHIVE_FALLBACK_DAYS),end=date.today())
        for eid in list(missing):
            matched=next((candidate for candidate in resolve_index_names(mapping[eid],catalogue) if candidate in archive.columns),None)
            if matched is not None and len(archive[matched].dropna())>=MIN_OBSERVATIONS:
                frame=frame.drop(columns=[eid],errors="ignore").join(archive[matched].rename(eid),how="outer"); source_by_exposure[eid]="nse_archive"; resolved_by_exposure[eid]=matched; missing.pop(eid,None)
    if missing:
        yahoo_frame,yahoo_sources=_fetch_yahoo_fallback(missing,years)
        for eid in yahoo_frame.columns:
            frame=frame.drop(columns=[eid],errors="ignore").join(yahoo_frame[eid].rename(eid),how="outer"); source_by_exposure[eid]=yahoo_sources.get(eid,"yahoo"); resolved_by_exposure[eid]=mapping[eid]; missing.pop(eid,None)
    if missing and etf_histories is not None:
        proxy_frame,proxy_sources=_proxy_from_etfs(missing,etf_histories)
        for eid in proxy_frame.columns:
            frame=frame.drop(columns=[eid],errors="ignore").join(proxy_frame[eid].rename(eid),how="outer"); source_by_exposure[eid]=proxy_sources[eid]; resolved_by_exposure[eid]=mapping[eid]+" (ETF/NAV proxy)"; missing.pop(eid,None)
    if missing:
        seed_frame,seed_sources=_load_seed_indices(missing)
        for eid in seed_frame.columns:
            frame=frame.drop(columns=[eid],errors="ignore").join(seed_frame[eid].rename(eid),how="outer"); source_by_exposure[eid]=seed_sources[eid]; resolved_by_exposure[eid]=mapping[eid]; missing.pop(eid,None)
    if missing:
        proxy_frame,proxy_sources,proxy_names=_proxy_from_resolved_indices(missing,frame,mapping)
        for eid in proxy_frame.columns:
            frame=frame.drop(columns=[eid],errors="ignore").join(proxy_frame[eid].rename(eid),how="outer"); source_by_exposure[eid]=proxy_sources[eid]; resolved_by_exposure[eid]=proxy_names[eid]; missing.pop(eid,None)
    frame.attrs["source_by_exposure"]=source_by_exposure; frame.attrs["resolved_name_by_exposure"]=resolved_by_exposure; frame.attrs["unresolved_exposures"]=sorted(missing)
    return frame.sort_index()
