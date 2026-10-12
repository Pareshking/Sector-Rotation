from __future__ import annotations

import pandas as pd


def relative_strength(asset: pd.Series, benchmark: pd.Series, weekly: bool = True) -> pd.Series:
    joined = pd.concat([asset.rename("asset"), benchmark.rename("benchmark")], axis=1).dropna()
    if weekly:
        joined = joined.resample("W-FRI").last().dropna()
    return joined["asset"] / joined["benchmark"]


def mansfield_relative_strength(asset: pd.Series, benchmark: pd.Series, window: int = 52, weekly: bool = True) -> pd.Series:
    rs = relative_strength(asset, benchmark, weekly=weekly)
    baseline = rs.rolling(window, min_periods=window).mean()
    return ((rs / baseline) - 1.0) * 100.0


def rs_ratio(asset: pd.Series, benchmark: pd.Series, window: int = 52, weekly: bool = True) -> pd.Series:
    rs = relative_strength(asset, benchmark, weekly=weekly)
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


def signal_panel(prices: pd.DataFrame, benchmark: pd.Series) -> dict[str, pd.DataFrame]:
    """Mansfield RS ratio and velocity for every date, per exposure (display only).

    The RRG stage is a description of where an exposure sits in the rotation
    cycle; since strategy v1.0 it decides nothing. Both inputs are
    backward-looking — a 52-week rolling mean and a 13-week difference — so
    row ``t`` uses only data available on day ``t``.
    """
    out: dict[str, pd.DataFrame] = {}
    for column in prices.columns:
        mrs = mansfield_relative_strength(prices[column], benchmark)
        if mrs.dropna().empty:
            continue
        frame = pd.DataFrame({"ratio": 1.0 + mrs / 100.0, "velocity": rs_momentum(mrs)}).dropna()
        if not frame.empty:
            out[column] = frame
    return out


def signal_at(panel: dict[str, pd.DataFrame], exposure_id: str, asof: pd.Timestamp):
    frame = panel.get(exposure_id)
    if frame is None:
        return None
    window = frame.loc[:asof]
    if window.empty:
        return None
    row = window.iloc[-1]
    return float(row["ratio"]), float(row["velocity"])
