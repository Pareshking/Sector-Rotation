from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

import pandas as pd

from src.data.amfi import fetch_amfi_nav
from src.data.amfi_history import fetch_amfi_history, find_scheme_codes
from src.data.index_data import download_history
from src.data.mfapi import fetch_etf_nav
from src.models.exposure import ETFMapping

MIN_OBSERVATIONS = 60


def download_market_history(symbols: Iterable[str], years: int = 5) -> pd.DataFrame:
    clean = [symbol for symbol in symbols if symbol]
    if not clean:
        return pd.DataFrame()
    return download_history(clean, years=years)


def _amfi_fallback(etf: ETFMapping, days: int = 90) -> pd.Series:
    current = fetch_amfi_nav()
    codes = find_scheme_codes(current, [etf.name])
    code = codes.get(etf.name)
    if not code:
        return pd.Series(dtype="float64", name=etf.symbol or etf.name)
    history = fetch_amfi_history(date.today() - timedelta(days=days), date.today(), scheme_codes=[code])
    if history.empty:
        return pd.Series(dtype="float64", name=etf.symbol or etf.name)
    return history.loc[history["scheme_code"].eq(code)].set_index("date")["nav"].rename(etf.symbol or etf.name).sort_index()


def fetch_etf_histories(etfs: Iterable[ETFMapping], years: int = 5) -> tuple[pd.DataFrame, dict[str, str], dict[str, int]]:
    """Build ETF history using MFAPI NAV -> Yahoo market close -> AMFI fallback.

    A mapped AMFI scheme is authoritative for the continuous NAV leg. Yahoo is
    deliberately bypassed when MFAPI supplies at least MIN_OBSERVATIONS rows.
    Instruments without a scheme code go directly to Yahoo; AMFI remains the
    emergency final fallback.
    """
    etf_list = list(etfs)
    columns: dict[str, pd.Series] = {}
    sources: dict[str, str] = {}
    resolved_codes: dict[str, int] = {}
    unresolved: list[ETFMapping] = []

    for etf in etf_list:
        key = etf.symbol or etf.name
        if etf.scheme_code is None:
            unresolved.append(etf)
            continue
        try:
            result = fetch_etf_nav(key, scheme_code=etf.scheme_code, expected_name=etf.name)
            series = result.frame["adjusted_close"].dropna() if not result.frame.empty else pd.Series(dtype="float64")
            if series.size >= MIN_OBSERVATIONS:
                columns[key] = series.rename(key)
                sources[key] = "mfapi"
                resolved_codes[key] = result.scheme_code
                continue
        except Exception:
            pass
        unresolved.append(etf)

    # Secondary market-price leg: only instruments without a complete MFAPI
    # series reach Yahoo. This prevents unnecessary calls for mapped schemes.
    market_symbols = [etf.yfinance_symbol for etf in unresolved if etf.yfinance_symbol]
    market = download_market_history(market_symbols, years=years)
    if not market.empty:
        reverse = {etf.yfinance_symbol: etf.symbol or etf.name for etf in unresolved if etf.yfinance_symbol}
        for yahoo_symbol, etf_key in reverse.items():
            if yahoo_symbol not in market:
                continue
            series = market[yahoo_symbol].dropna()
            if series.size < MIN_OBSERVATIONS:
                continue
            columns[etf_key] = series.rename(etf_key)
            sources[etf_key] = "yahoo"

    # Emergency official AMFI history for anything still unresolved. This path
    # is intentionally last so it cannot cause broad Yahoo/MFAPI duplication.
    for etf in unresolved:
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

    return pd.DataFrame(columns).sort_index(), sources, resolved_codes
