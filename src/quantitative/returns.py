from __future__ import annotations

import pandas as pd

LOOKBACK_DAYS = {"1M": 21, "3M": 63, "6M": 126, "12M": 252}


def period_return(series: pd.Series, days: int) -> float:
    values = series.dropna()
    if len(values) <= days:
        return float("nan")
    return float(values.iloc[-1] / values.iloc[-days - 1] - 1.0)


def multi_period_returns(prices: pd.DataFrame, periods: dict[str, int] | None = None) -> pd.DataFrame:
    periods = periods or LOOKBACK_DAYS
    return pd.DataFrame({name: prices.apply(lambda s: period_return(s, days)) for name, days in periods.items()})


def dual_momentum(asset: pd.Series, benchmark: pd.Series, days: int = 126) -> float:
    a = period_return(asset, days)
    b = period_return(benchmark, days)
    if pd.isna(a) or pd.isna(b):
        return float("nan")
    return float(a - b)
