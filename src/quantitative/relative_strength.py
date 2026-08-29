from __future__ import annotations

import pandas as pd


def relative_strength(asset: pd.Series, benchmark: pd.Series) -> pd.Series:
    joined = pd.concat([asset.rename("asset"), benchmark.rename("benchmark")], axis=1).dropna()
    return joined["asset"] / joined["benchmark"]


def mansfield_relative_strength(asset: pd.Series, benchmark: pd.Series, window: int = 52) -> pd.Series:
    rs = relative_strength(asset, benchmark)
    baseline = rs.rolling(window, min_periods=window).mean()
    return ((rs / baseline) - 1.0) * 100.0


def rs_ratio(asset: pd.Series, benchmark: pd.Series, window: int = 52) -> pd.Series:
    rs = relative_strength(asset, benchmark)
    baseline = rs.rolling(window, min_periods=window).mean()
    return rs / baseline


def rs_momentum(mrs: pd.Series, periods: int = 13) -> pd.Series:
    return mrs.diff(periods)


def rs_stage(rs_ratio_value: float, rs_momentum_value: float) -> str:
    if pd.isna(rs_ratio_value) or pd.isna(rs_momentum_value):
        return "Insufficient Data"
    if rs_ratio_value >= 1.0 and rs_momentum_value >= 0:
        return "Leading"
    if rs_ratio_value >= 1.0 and rs_momentum_value < 0:
        return "Weakening"
    if rs_ratio_value < 1.0 and rs_momentum_value < 0:
        return "Lagging"
    return "Improving"
