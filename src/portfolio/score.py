"""Cross-sectional momentum scores at one date.

Pure pandas/numpy. Everything is computed from ``price_history.loc[:as_of]``,
so a score can never see a price from after the date it is scored on.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import FULL_HISTORY_SESSIONS, SEGMENTS, StrategyConfig

TRADING_DAYS = 252
# A missing session or two is bridged with the previous close; a series that
# has not printed for longer than this is stale and cannot be scored.
FFILL_LIMIT = 5

SCORE_COLUMNS = (
    "valid",
    *(f"seg_{name}" for name in SEGMENTS),
    "return_12m",
    "volatility",
    "score",
    "universe_rank",
)


def _zscore(values: pd.Series) -> pd.Series:
    mean = values.mean()
    std = values.std(ddof=0)
    if not np.isfinite(std) or std == 0:
        return pd.Series(0.0, index=values.index)
    return (values - mean) / std


def score_exposures(
    price_history: pd.DataFrame, as_of: pd.Timestamp, config: StrategyConfig
) -> pd.DataFrame:
    """One row per exposure: segment log returns, 12-month return, score and rank.

    An exposure is ``valid`` when every price the score needs exists on the
    shared session calendar: the latest close and the closes 21, 63, 126 and
    252 sessions earlier. Lookbacks are positions on that one calendar, so
    every exposure is measured over exactly the same sessions.

    ``segment_composite`` z-scores the log return of each non-overlapping
    segment across the valid exposures and combines them with the configured
    weights; the most recent month is a full segment, never skipped.
    ``vol_adjusted_12m`` divides the 12-month log return by the annualised
    EWMA volatility of daily log returns.
    """
    columns = list(price_history.columns)
    out = pd.DataFrame(index=pd.Index(columns, name="exposure_id"), columns=list(SCORE_COLUMNS))
    out["valid"] = False
    panel = price_history.loc[: pd.Timestamp(as_of)].sort_index().ffill(limit=FFILL_LIMIT)
    if panel.empty:
        numeric = [c for c in SCORE_COLUMNS if c not in ("valid", "universe_rank")]
        out[numeric] = out[numeric].astype(float)
        out["universe_rank"] = pd.array([pd.NA] * len(out), dtype="Int64")
        return out.astype({"valid": bool})

    logp = np.log(panel.where(panel > 0))
    last = len(panel) - 1

    def back(sessions: int) -> pd.Series:
        if last - sessions < 0:
            return pd.Series(np.nan, index=panel.columns)
        return logp.iloc[last - sessions]

    for name, (newer, older) in SEGMENTS.items():
        out[f"seg_{name}"] = back(newer) - back(older)
    log_12m = back(0) - back(FULL_HISTORY_SESSIONS)
    out["return_12m"] = np.expm1(log_12m)

    spec = config.score_weights.vol_adjusted
    daily = logp.diff()
    vol = daily.ewm(span=spec.ewma_span_days, min_periods=spec.ewma_span_days).std().iloc[last]
    out["volatility"] = vol * np.sqrt(TRADING_DAYS)

    segment_cols = [f"seg_{name}" for name in SEGMENTS]
    valid = out[segment_cols].notna().all(axis=1) & out["return_12m"].notna()
    if config.score_weights.method == "vol_adjusted_12m":
        valid &= out["volatility"].gt(0)
    out["valid"] = valid.astype(bool)

    score = pd.Series(np.nan, index=out.index, dtype=float)
    if valid.any():
        if config.score_weights.method == "segment_composite":
            weights = config.score_weights.segments
            composite = pd.Series(0.0, index=out.index[valid])
            for name in SEGMENTS:
                composite += weights[name] * _zscore(out.loc[valid, f"seg_{name}"].astype(float))
            score.loc[valid] = composite
        else:
            lookback = spec.return_lookback_days
            log_ret = back(0) - back(lookback)
            score.loc[valid] = (log_ret[valid] / out.loc[valid, "volatility"]).astype(float)
    out["score"] = score
    numeric = [c for c in SCORE_COLUMNS if c not in ("valid", "universe_rank")]
    out[numeric] = out[numeric].astype(float)
    out["universe_rank"] = rank_by_score(out.loc[valid, "score"]).reindex(out.index)
    return out.astype({"valid": bool})


def rank_by_score(scores: pd.Series) -> pd.Series:
    """1 = best. Ties break on exposure id so the order never depends on input order."""
    if scores.empty:
        return pd.Series(dtype="Int64")
    frame = pd.DataFrame({"score": scores.astype(float), "id": scores.index.astype(str)})
    ordered = frame.sort_values(["score", "id"], ascending=[False, True], kind="mergesort")
    return pd.Series(range(1, len(ordered) + 1), index=ordered.index, dtype="Int64")
