from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable, Mapping

import pandas as pd
import yfinance as yf

from src.data.nifty_indices import fetch_missing_indices


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
    )
    if data.empty:
        return pd.DataFrame()
    if isinstance(data.columns, pd.MultiIndex):
        close = data["Close"] if "Close" in data.columns.get_level_values(0) else data.xs("Close", axis=1, level=0)
    else:
        close = data[["Close"]].rename(columns={"Close": clean[0]})
    close.index = pd.to_datetime(close.index).tz_localize(None)
    return close.dropna(how="all").sort_index()


def download_canonical_indices(
    exposure_names: Mapping[str, str],
    yfinance_symbols: Mapping[str, str | None],
    years: int = 5,
) -> pd.DataFrame:
    """Download canonical benchmark series with official Nifty fallback."""
    yf_map = {exposure_id: symbol for exposure_id, symbol in yfinance_symbols.items() if symbol}
    frame = download_history(yf_map.values(), years=years)
    if not frame.empty:
        frame = frame.rename(columns={symbol: exposure_id for exposure_id, symbol in yf_map.items()})
    return fetch_missing_indices(exposure_names, existing=frame, years=years)
