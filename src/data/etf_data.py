from __future__ import annotations

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
MAX_MFAPI_WORKERS = 5
NETWORK_TIMEOUT = (5, 10)


def download_market_history(symbols: Iterable[str], years: int = 5) -> pd.DataFrame:
    clean = [symbol for symbol in symbols if symbol]
    if not clean:
        return pd.DataFrame()
    return download_history(clean, years=years)


def _amfi_fallback(etf: ETFMapping, days: int = 90) -> pd.Series:
    code = str(etf.scheme_code) if etf.scheme_code is not None else None
    if code is None:
        current = fetch_amfi_nav(timeout=NETWORK_TIMEOUT)
        codes = find_scheme_codes(current, [etf.name])
        code = codes.get(etf.name)
    if not code:
        return pd.Series(dtype="float64", name=etf.symbol or etf.name)
    history = fetch_amfi_history(
        date.today() - timedelta(days=days),
        date.today(),
        scheme_codes=[code],
        timeout=NETWORK_TIMEOUT,
        chunk_days=365,
    )
    if history.empty:
        return pd.Series(dtype="float64", name=etf.symbol or etf.name)
    return (
        history.loc[history["scheme_code"].eq(code)]
        .set_index("date")["nav"]
        .rename(etf.symbol or etf.name)
        .sort_index()
    )


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

    # 1. NSE, for anything with a trading symbol.
    listed = {etf.symbol: etf for etf in etf_list if etf.symbol}
    if listed:
        for symbol, series in fetch_nse_histories(list(listed), years=years).items():
            columns[symbol] = series.rename(symbol)
            sources[symbol] = "nse"

    def _done(etf) -> bool:
        return (etf.symbol or etf.name) in columns

    # 2. MFAPI scheme NAV for whatever NSE could not serve.
    mapped = [etf for etf in etf_list if etf.scheme_code is not None and not _done(etf)]
    unresolved: list[ETFMapping] = [etf for etf in etf_list if etf.scheme_code is None and not _done(etf)]
    if mapped:
        mfapi_columns, mfapi_codes, mfapi_unresolved = fetch_all_mfapi_histories(mapped)
        columns.update(mfapi_columns)
        resolved_codes.update(mfapi_codes)
        sources.update({key: "mfapi" for key in mfapi_columns})
        unresolved.extend(mfapi_unresolved)

    # 3. AMFI official NAV before any third-party mirror.
    for etf in list(unresolved):
        key = etf.symbol or etf.name
        if key in columns:
            continue
        try:
            fallback = _amfi_fallback(etf, days=365 * years + 30)
        except Exception:
            fallback = pd.Series(dtype="float64", name=key)
        if fallback.size >= MIN_OBSERVATIONS:
            columns[key] = fallback.rename(key)
            sources[key] = "amfi"

    unresolved = [etf for etf in unresolved if (etf.symbol or etf.name) not in columns]

    # 4. Yahoo, last. Only instruments no authoritative source could serve.
    market_symbols = [etf.yfinance_symbol for etf in unresolved if etf.yfinance_symbol]
    if market_symbols:
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

    return pd.DataFrame(columns).sort_index(), sources, resolved_codes
