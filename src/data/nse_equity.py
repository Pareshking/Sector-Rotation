"""NSE traded-price history for exchange-listed instruments.

An ETF is an NSE-listed security, so the exchange itself has its full traded
history — there is no reason to ask a third-party mirror first. This is the
primary source for anything with an NSE symbol; MFAPI/AMFI NAV follows for
instruments that are not exchange-traded, and Yahoo is last.
"""

from __future__ import annotations

import warnings
from datetime import date, timedelta

import pandas as pd

import src.data._jugaad_patches  # noqa: F401 — timeout + wider date-chunking, side effects only
from jugaad_data.nse import stock_df

MIN_OBSERVATIONS = 60
SOURCE = "nse"


def _trading_dates(values: pd.Series) -> pd.Series:
    """Normalise NSE timestamps to the IST trading date.

    jugaad returns UTC instants, so an IST session date arrives as the previous
    calendar day at 18:30. Left alone, every NSE series is shifted one day
    against the index panel and silently fails to align with it at all.
    """
    parsed = pd.to_datetime(values, errors="coerce", utc=True)
    if parsed.notna().any():
        return parsed.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None).dt.normalize()
    return pd.to_datetime(values, errors="coerce").dt.normalize()


def fetch_nse_history(symbol: str, years: int = 5) -> pd.Series:
    """Daily close for one NSE symbol. Empty series when NSE cannot serve it."""
    if not symbol:
        return pd.Series(dtype="float64", name=symbol)
    start = date.today() - timedelta(days=365 * years + 10)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            frame = stock_df(symbol=symbol, from_date=start, to_date=date.today(), series="EQ")
    except Exception:
        return pd.Series(dtype="float64", name=symbol)
    if frame is None or len(frame) == 0:
        return pd.Series(dtype="float64", name=symbol)

    date_col = next((c for c in ("DATE", "Date", "date") if c in frame.columns), None)
    close_col = next((c for c in ("CLOSE", "Close", "close") if c in frame.columns), None)
    if date_col is None or close_col is None:
        return pd.Series(dtype="float64", name=symbol)

    dates = _trading_dates(frame[date_col])
    values = pd.to_numeric(frame[close_col], errors="coerce")
    ok = dates.notna() & values.notna() & values.gt(0)
    if not ok.any():
        return pd.Series(dtype="float64", name=symbol)
    series = pd.Series(
        values.loc[ok].to_numpy(float), index=pd.DatetimeIndex(dates.loc[ok]), name=symbol
    )
    series = series.groupby(level=0).last().sort_index()
    series.attrs.update(source=SOURCE, value_type="CLOSE")
    return series


def fetch_nse_histories(symbols, years: int = 5, workers: int = 12) -> dict[str, pd.Series]:
    from concurrent.futures import ThreadPoolExecutor, as_completed

    clean = [s for s in symbols if s]
    if not clean:
        return {}
    out: dict[str, pd.Series] = {}
    with ThreadPoolExecutor(max_workers=min(workers, len(clean))) as pool:
        futures = {pool.submit(fetch_nse_history, s, years): s for s in clean}
        for future in as_completed(futures):
            try:
                series = future.result()
            except Exception:
                continue
            if len(series) >= MIN_OBSERVATIONS:
                out[futures[future]] = series
    return out
