"""Yahoo Finance adapter — ETF traded prices only.

Yahoo is never used for a canonical index history: an index symbol that quietly
resolves to the wrong series would corrupt a decision-grade benchmark. ETF
market prices are a different question — they are explicitly symbol-mapped and
cross-checked against AMFI/MFAPI NAV, so Yahoo is an acceptable fast path there.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

import pandas as pd
import yfinance as yf

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
