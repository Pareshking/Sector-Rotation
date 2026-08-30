from __future__ import annotations

import pandas as pd

from .returns import LOOKBACK_DAYS, dual_momentum

# How much each horizon contributes to the composite momentum score. Equal
# weight is the neutral prior: it assumes nothing about which horizon predicts
# best, which is the honest default when the sample is too short to tell.
# Changing these changes every ranking in the app *and* the backtest, so the
# live board and the test can never disagree about what "rank 1" means.
DEFAULT_WEIGHTS: dict[str, float] = {"1M": 0.25, "3M": 0.25, "6M": 0.25, "12M": 0.25}


def normalise_weights(weights: dict[str, float] | None) -> dict[str, float]:
    """Drop unknown horizons, clamp negatives, and rescale to sum to 1."""
    if not weights:
        return dict(DEFAULT_WEIGHTS)
    clean = {k: max(float(v), 0.0) for k, v in weights.items() if k in LOOKBACK_DAYS}
    total = sum(clean.values())
    if total <= 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: v / total for k, v in clean.items() if v > 0}


def cross_sectional_zscore(values: pd.Series) -> pd.Series:
    clean = values.astype(float)
    mean = clean.mean(skipna=True)
    std = clean.std(skipna=True, ddof=0)
    if pd.isna(std) or std == 0:
        return pd.Series(0.0, index=clean.index)
    return (clean - mean) / std


def percentile_rank(values: pd.Series) -> pd.Series:
    return values.rank(pct=True, method="average") * 100.0


def rank_exposures(
    prices: pd.DataFrame,
    benchmark: pd.Series,
    weights: dict[str, float] | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, float | str]] = []
    for name in prices.columns:
        asset = prices[name].dropna()
        row: dict[str, float | str] = {"exposure": name}
        for label, days in LOOKBACK_DAYS.items():
            row[f"return_{label}"] = _safe_return(asset, days)
            row[f"relative_{label}"] = dual_momentum(asset, benchmark, days)
        rows.append(row)

    frame = pd.DataFrame(rows).set_index("exposure")
    for label in LOOKBACK_DAYS:
        frame[f"z_{label}"] = cross_sectional_zscore(frame[f"relative_{label}"])
        frame[f"percentile_{label}"] = percentile_rank(frame[f"relative_{label}"])

    # Weighted mean of the per-horizon Z-scores. A horizon with no data for an
    # exposure drops out of both the numerator and the denominator, so a short
    # history is scored on what it has rather than being penalised to zero.
    active = normalise_weights(weights)
    contributions = pd.DataFrame(
        {label: frame[f"z_{label}"] * w for label, w in active.items()}
    )
    applied = pd.DataFrame(
        {label: frame[f"z_{label}"].notna() * w for label, w in active.items()}
    )
    denominator = applied.sum(axis=1).replace(0.0, float("nan"))
    frame["momentum_z"] = contributions.sum(axis=1, skipna=True) / denominator

    # Rank is an ordinal presentation field. Equal scores still receive a
    # deterministic unique position so the dashboard never shows misleading
    # duplicate ranks. The score itself remains unchanged.
    ordered = frame.sort_values(
        ["momentum_z"], ascending=False, kind="mergesort", na_position="last"
    )
    ordered["rank"] = pd.Series(range(1, len(ordered) + 1), index=ordered.index, dtype="int64")
    return ordered


def _safe_return(series: pd.Series, days: int) -> float:
    if len(series) <= days:
        return float("nan")
    return float(series.iloc[-1] / series.iloc[-days - 1] - 1.0)
