"""A score taken apart: the Method page's worked example, from the live decision.

Uses the decision's own ranking table and the scoring module's own z-score, so
the arithmetic shown is the arithmetic the portfolio ran, not a re-derivation.
"""

from __future__ import annotations

from typing import Mapping

import pandas as pd

from src.config import SEGMENTS
from src.portfolio.score import _zscore


def score_breakdown(ranking: pd.DataFrame, exposure_id: str, weights: Mapping[str, float]) -> pd.DataFrame:
    """One row per segment: the exposure's log return, the universe's mean and s.d., z, weight, contribution."""
    valid = ranking[ranking["valid"].astype(bool)]
    rows = []
    for name, (newer, older) in SEGMENTS.items():
        values = valid[f"seg_{name}"].astype(float)
        z = _zscore(values)
        rows.append(
            {
                "Segment": name,
                "Sessions back": f"{newer}–{older}",
                "Log return": float(values.get(exposure_id, float("nan"))),
                "Universe mean": float(values.mean()),
                "Universe s.d.": float(values.std(ddof=0)),
                "z": float(z.get(exposure_id, float("nan"))),
                "Weight": float(weights[name]),
            }
        )
    frame = pd.DataFrame(rows)
    frame["Contribution"] = frame["z"] * frame["Weight"]
    return frame
