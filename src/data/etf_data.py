from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Iterable

import pandas as pd

from src.data.amfi import fetch_amfi_nav
from src.data.amfi_history import fetch_amfi_history, find_scheme_codes
from src.data.mfapi import fetch_etf_nav
from src.data.nse_equity import fetch_nse_histories
from src.data.yahoo import download_history
from src.models.exposure import ETFMapping

MIN_OBSERVATIONS = 60
# The vehicle count roughly tripled (32 -> 104) when index funds were added, and
# the run outgrew its 45-minute CI budget at the old fan-out. These are IO-bound
# HTTP fetches, so more threads is the cheap fix; both hosts tolerate this rate.
MAX_MFAPI_WORKERS = 12
NETWORK_TIMEOUT = (5, 10)


def _progress(message: str) -> None:
    """Print immediately, not buffered until the process exits.

    A run that goes silent for a long stretch is indistinguishable from a
    hung one otherwise — this is what makes a stage actually observable while
    it's happening, in a CI log tail or a background process alike.
    """
    print(f"[{time.strftime('%H:%M:%S')}] {message}", file=sys.stderr, flush=True)


def download_market_history(symbols: Iterable[str], years: int = 5) -> pd.DataFrame:
    clean = [symbol for symbol in symbols if symbol]
    if not clean:
        return pd.DataFrame()
    return download_history(clean, years=years)


def _amfi_fallback_batch(etfs: list[ETFMapping], days: int = 90) -> dict[str, pd.Series]:
    """Resolve every vehicle AMFI must serve from one shared download, not one per vehicle.

    AMFI's historical-NAV report returns every scheme's NAV for the requested
    date window regardless of which single scheme you actually want — it is a
    market-wide dump, not a per-scheme lookup, and it can take minutes to fully
    stream (its read-timeout only resets per chunk received, so a slow trickle
    never actually trips it). Looping this per vehicle re-downloads that same
    multi-year, whole-market report once for every vehicle that needs it; a
    handful of vehicles falling through NSE and MFAPI on one run was enough to
    turn a multi-minute pipeline into one that never finished. Fetching scheme
    codes and history once for the whole batch turns that into one download.
    """
    if not etfs:
        return {}
    named = [etf for etf in etfs if etf.scheme_code is None]
    resolved_codes: dict[str, str] = {}
    if named:
        current = fetch_amfi_nav(timeout=NETWORK_TIMEOUT)
        resolved_codes = find_scheme_codes(current, [etf.name for etf in named])

    code_by_key: dict[str, str] = {}
    for etf in etfs:
        key = etf.symbol or etf.name
        code = str(etf.scheme_code) if etf.scheme_code is not None else resolved_codes.get(etf.name)
        if code:
            code_by_key[key] = code
    if not code_by_key:
        return {}

    history = fetch_amfi_history(
        date.today() - timedelta(days=days),
        date.today(),
        scheme_codes=list(set(code_by_key.values())),
        timeout=NETWORK_TIMEOUT,
        chunk_days=365,
    )
    if history.empty:
        return {}

    results: dict[str, pd.Series] = {}
    for key, code in code_by_key.items():
        series = (
            history.loc[history["scheme_code"].eq(code)]
            .set_index("date")["nav"]
            .rename(key)
            .sort_index()
        )
        if series.size >= MIN_OBSERVATIONS:
            results[key] = series
    return results


def _fetch_one_mfapi(etf: ETFMapping) -> tuple[ETFMapping, pd.Series, int | None]:
    key = etf.symbol or etf.name
    try:
        result = fetch_etf_nav(
            key,
            scheme_code=etf.scheme_code,
            expected_name=etf.name,
            timeout=NETWORK_TIMEOUT,
        )
        series = (
            result.frame["adjusted_close"].dropna()
            if not result.frame.empty
            else pd.Series(dtype="float64")
        )
        if series.size >= MIN_OBSERVATIONS:
            return etf, series.rename(key), result.scheme_code
    except Exception:
        pass
    return etf, pd.Series(dtype="float64"), None


def fetch_all_mfapi_histories(
    scheme_records: list[ETFMapping], max_workers: int = MAX_MFAPI_WORKERS
) -> tuple[dict[str, pd.Series], dict[str, int], list[ETFMapping]]:
    """Fetch mapped MFAPI histories concurrently with bounded fan-out."""
    columns: dict[str, pd.Series] = {}
    resolved_codes: dict[str, int] = {}
    unresolved: list[ETFMapping] = []

    if not scheme_records:
        return columns, resolved_codes, unresolved

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch_one_mfapi, etf): etf for etf in scheme_records}
        for future in as_completed(futures):
            etf = futures[future]
            try:
                resolved_etf, series, scheme_code = future.result()
            except Exception:
                unresolved.append(etf)
                continue
            key = resolved_etf.symbol or resolved_etf.name
            if not series.empty and scheme_code is not None:
                columns[key] = series
                resolved_codes[key] = scheme_code
            else:
                unresolved.append(etf)

    return columns, resolved_codes, unresolved


def fetch_etf_histories(
    etfs: Iterable[ETFMapping], years: int = 5
) -> tuple[pd.DataFrame, dict[str, str], dict[str, int]]:
    """Build ETF history with the exchange first and Yahoo last.

    Order is NSE -> MFAPI -> AMFI -> Yahoo. An ETF is an NSE-listed security, so
    the exchange has its traded history and there is no reason to ask a
    third-party mirror first; open-ended index funds are not listed at all and
    resolve through AMFI's scheme NAV. Yahoo remains only as a last resort,
    because a Yahoo outage previously dropped three otherwise healthy ETFs
    (ITBEES, HEALTHIETF, SBIETFIT) out of the dataset entirely.
    """
    etf_list = list(etfs)
    columns: dict[str, pd.Series] = {}
    sources: dict[str, str] = {}
    resolved_codes: dict[str, int] = {}
    _progress(f"ETF fetch starting: {len(etf_list)} vehicles")

    # 1. NSE, for anything with a trading symbol.
    listed = {etf.symbol: etf for etf in etf_list if etf.symbol}
    if listed:
        t0 = time.time()
        for symbol, series in fetch_nse_histories(list(listed), years=years, workers=12).items():
            columns[symbol] = series.rename(symbol)
            sources[symbol] = "nse"
        _progress(
            f"NSE: {sum(1 for v in sources.values() if v == 'nse')}/{len(listed)} resolved "
            f"in {time.time() - t0:.0f}s"
        )

    def _done(etf) -> bool:
        return (etf.symbol or etf.name) in columns

    # 2. MFAPI scheme NAV for whatever NSE could not serve.
    mapped = [etf for etf in etf_list if etf.scheme_code is not None and not _done(etf)]
    unresolved: list[ETFMapping] = [etf for etf in etf_list if etf.scheme_code is None and not _done(etf)]
    if mapped:
        t0 = time.time()
        mfapi_columns, mfapi_codes, mfapi_unresolved = fetch_all_mfapi_histories(mapped)
        columns.update(mfapi_columns)
        resolved_codes.update(mfapi_codes)
        sources.update({key: "mfapi" for key in mfapi_columns})
        unresolved.extend(mfapi_unresolved)
        _progress(
            f"MFAPI: {len(mfapi_columns)}/{len(mapped)} resolved, "
            f"{len(mfapi_unresolved)} falling through, in {time.time() - t0:.0f}s"
        )

    # 3. AMFI official NAV before any third-party mirror. One shared download
    # for the whole remaining batch — see _amfi_fallback_batch for why looping
    # this per vehicle was the actual cause of runs that never finished.
    if unresolved:
        t0 = time.time()
        _progress(f"AMFI: resolving {len(unresolved)} remaining vehicle(s) in one shared download...")
        try:
            amfi_columns = _amfi_fallback_batch(list(unresolved), days=365 * years + 30)
        except Exception:
            amfi_columns = {}
        for key, series in amfi_columns.items():
            columns[key] = series
            sources[key] = "amfi"
        _progress(f"AMFI: {len(amfi_columns)}/{len(unresolved)} resolved in {time.time() - t0:.0f}s")

    unresolved = [etf for etf in unresolved if (etf.symbol or etf.name) not in columns]

    # 4. Yahoo, last. Only instruments no authoritative source could serve.
    market_symbols = [etf.yfinance_symbol for etf in unresolved if etf.yfinance_symbol]
    if market_symbols:
        t0 = time.time()
        market = download_market_history(market_symbols, years=years)
        if not market.empty:
            reverse = {
                etf.yfinance_symbol: etf.symbol or etf.name
                for etf in unresolved
                if etf.yfinance_symbol
            }
            for yahoo_symbol, etf_key in reverse.items():
                if yahoo_symbol not in market:
                    continue
                series = market[yahoo_symbol].dropna()
                if series.size < MIN_OBSERVATIONS:
                    continue
                columns[etf_key] = series.rename(etf_key)
                sources[etf_key] = "yahoo"
        _progress(
            f"Yahoo: {sum(1 for v in sources.values() if v == 'yahoo')}/{len(market_symbols)} "
            f"resolved in {time.time() - t0:.0f}s"
        )

    _progress(f"ETF fetch done: {len(columns)}/{len(etf_list)} vehicles resolved")
    return pd.DataFrame(columns).sort_index(), sources, resolved_codes
