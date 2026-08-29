from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

import pandas as pd

from src.data.amfi import fetch_amfi_nav
from src.data.amfi_history import fetch_amfi_history, find_scheme_codes
from src.data.mfapi import fetch_etf_nav
from src.data.index_data import download_history
from src.models.exposure import ETFMapping


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

    The returned series is NAV-like when MFAPI is available and market-close-like
    when Yahoo is used. Source labels make this distinction explicit for telemetry.
    """
    etf_list = list(etfs)
    columns: dict[str, pd.Series] = {}
    sources: dict[str, str] = {}
    resolved_codes: dict[str, int] = {}
    market_symbols = [etf.yfinance_symbol for etf in etf_list if etf.yfinance_symbol]
    market = download_market_history(market_symbols, years=years)
    if not market.empty:
        reverse = {etf.yfinance_symbol: etf.symbol for etf in etf_list if etf.yfinance_symbol and etf.symbol}
        for yahoo_symbol, etf_symbol in reverse.items():
            if yahoo_symbol in market:
                series = market[yahoo_symbol].dropna()
                if not series.empty:
                    columns[etf_symbol] = series.rename(etf_symbol)
                    sources[etf_symbol] = "yahoo"
    for etf in etf_list:
        key = etf.symbol or etf.name
        try:
            result = fetch_etf_nav(key, scheme_code=etf.scheme_code, expected_name=etf.name)
            if not result.frame.empty:
                columns[key] = result.frame["adjusted_close"].rename(key)
                sources[key] = "mfapi"
                resolved_codes[key] = result.scheme_code
                continue
        except Exception:
            pass
        if key not in columns or columns[key].dropna().size < 20:
            try:
                fallback = _amfi_fallback(etf)
            except Exception:
                fallback = pd.Series(dtype="float64", name=key)
            if not fallback.empty:
                columns[key] = fallback
                sources[key] = "amfi"
    return pd.DataFrame(columns).sort_index(), sources, resolved_codes
