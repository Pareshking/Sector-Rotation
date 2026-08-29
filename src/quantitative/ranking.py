from __future__ import annotations

import pandas as pd

from .returns import LOOKBACK_DAYS, dual_momentum


def cross_sectional_zscore(values: pd.Series) -> pd.Series:
    clean = values.astype(float)
    mean = clean.mean(skipna=True)
    std = clean.std(skipna=True, ddof=0)
    if pd.isna(std) or std == 0:
        return pd.Series(0.0, index=clean.index)
    return (clean - mean) / std


def percentile_rank(values: pd.Series) -> pd.Series:
    return values.rank(pct=True, method="average") * 100.0


def rank_exposures(prices: pd.DataFrame, benchmark: pd.Series) -> pd.DataFrame:
    rows: list[dict[str, float | str]] = []
    for name in prices.columns:
        asset = prices[name].dropna()
        row: dict[str, float | str] = {"exposure": name}
        for label, days in LOOKBACK_DAYS.items():
            row[f"return_{label}"] = (period := _safe_return(asset, days))
            row[f"relative_{label}"] = dual_momentum(asset, benchmark, days)
        rows.append(row)
    frame = pd.DataFrame(rows).set_index("exposure")
    for label in LOOKBACK_DAYS:
        frame[f"z_{label}"] = cross_sectional_zscore(frame[f"relative_{label}"])
        frame[f"percentile_{label}"] = percentile_rank(frame[f"relative_{label}"])
    zcols = [f"z_{x}" for x in LOOKBACK_DAYS]
    frame["momentum_z"] = frame[zcols].mean(axis=1, skipna=True)
    frame["rank"] = frame["momentum_z"].rank(ascending=False, method="min")
    return frame.sort_values("rank")


def _safe_return(series: pd.Series, days: int) -> float:
    if len(series) <= days:
        return float("nan")
    return float(series.iloc[-1] / series.iloc[-days - 1] - 1.0)
