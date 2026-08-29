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
    data = yf.download(
        clean,
        start=start.isoformat(),
        end=(date.today() + timedelta(days=1)).isoformat(),
        auto_adjust=True,
        progress=False,
        group_by="column",
        threads=True,
        timeout=YAHOO_TIMEOUT,
    )
    if data.empty:
        return pd.DataFrame()
    if isinstance(data.columns, pd.MultiIndex):
        close = (
            data["Close"]
            if "Close" in data.columns.get_level_values(0)
            else data.xs("Close", axis=1, level=0)
        )
    else:
        close = data[["Close"]].rename(columns={"Close": clean[0]})
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close.dropna(how="all").sort_index()


def download_canonical_indices(
    exposure_names: Mapping[str, str],
    yfinance_symbols: Mapping[str, str | None],
    years: int = 5,
) -> pd.DataFrame:
    """Build canonical index history with NiftyIndices-first source priority.

    Source hierarchy:
      1. Official NiftyIndices catalogue + TRI/PR history.
      2. NSE historical API/archive recovery.
      3. Yahoo Finance ticker fallback.
    """
    prices = fetch_missing_indices(exposure_names, years=years)

    resolved = {
        str(key): str(value)
        for key, value in prices.attrs.get("resolved_name_by_exposure", {}).items()
    }
    sources = {
        str(key): str(value)
        for key, value in prices.attrs.get("source_by_exposure", {}).items()
    }

    unresolved = {
        exposure_id: index_name
        for exposure_id, index_name in exposure_names.items()
        if exposure_id not in prices.columns
        or prices[exposure_id].dropna().size < MIN_OBSERVATIONS
    }

    if unresolved:
        yahoo_symbols = {
            exposure_id: yfinance_symbols.get(exposure_id)
            for exposure_id in unresolved
            if yfinance_symbols.get(exposure_id)
        }
        if yahoo_symbols:
            market = download_history(yahoo_symbols.values(), years=years)
            if not market.empty:
                for exposure_id, symbol in yahoo_symbols.items():
                    if symbol not in market:
                        continue
                    series = market[symbol].dropna()
                    if series.size < MIN_OBSERVATIONS:
                        continue
                    prices = prices.drop(columns=[exposure_id], errors="ignore").join(
                        series.rename(exposure_id),
                        how="outer",
                    )
                    sources[exposure_id] = "yahoo"
                    resolved[exposure_id] = exposure_names[exposure_id]

    prices.attrs["source_by_exposure"] = sources
    prices.attrs["resolved_name_by_exposure"] = resolved
    return prices.sort_index()
