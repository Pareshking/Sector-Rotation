from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, Mapping

import pandas as pd
import yfinance as yf

from src.data.nifty_indices import fetch_missing_indices

MIN_OBSERVATIONS = 60
YAHOO_TIMEOUT = 10


def download_history(symbols: Iterable[str], years: int = 5) -> pd.DataFrame:
    clean = [str(s) for s in symbols if s]
    if not clean:
        return pd.DataFrame()
    start = date.today() - timedelta(days=365 * years + 10)
    data = yf.download(clean, start=start.isoformat(), end=(date.today() + timedelta(days=1)).isoformat(), auto_adjust=True, progress=False, group_by="column", threads=True, timeout=YAHOO_TIMEOUT)
    if data.empty:
        return pd.DataFrame()
    if isinstance(data.columns, pd.MultiIndex):
        close = data["Close"] if "Close" in data.columns.get_level_values(0) else data.xs("Close", axis=1, level=0)
    else:
        close = data[["Close"]].rename(columns={"Close": clean[0]})
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close.dropna(how="all").sort_index()


def download_canonical_indices(exposure_names: Mapping[str, str], yfinance_symbols: Mapping[str, str | None], years: int = 5, etf_histories: pd.DataFrame | None = None) -> pd.DataFrame:
    """Resolve canonical benchmarks without inventing Yahoo symbols."""
    prices = fetch_missing_indices(exposure_names, years=years, etf_histories=etf_histories)
    resolved = dict(prices.attrs.get("resolved_name_by_exposure", {}))
    sources = dict(prices.attrs.get("source_by_exposure", {}))
    unresolved = {eid: name for eid, name in exposure_names.items() if eid not in prices.columns or prices[eid].dropna().size < MIN_OBSERVATIONS}
    if unresolved:
        yahoo_symbols = {eid: yfinance_symbols.get(eid) for eid in unresolved if yfinance_symbols.get(eid)}
        if yahoo_symbols:
            market = download_history(yahoo_symbols.values(), years=years)
            if not market.empty:
                for eid, symbol in yahoo_symbols.items():
                    if symbol not in market: continue
                    series = market[symbol].dropna()
                    if series.size < MIN_OBSERVATIONS: continue
                    prices = prices.drop(columns=[eid], errors="ignore").join(series.rename(eid), how="outer")
                    sources[eid] = "yahoo"; resolved[eid] = exposure_names[eid]
    prices.attrs["source_by_exposure"] = sources
    prices.attrs["resolved_name_by_exposure"] = resolved
    prices.attrs["unresolved_exposures"] = [eid for eid in exposure_names if eid not in prices.columns or prices[eid].dropna().size < MIN_OBSERVATIONS]
    return prices.sort_index()
