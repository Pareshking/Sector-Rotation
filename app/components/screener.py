"""What the Screener page shows, as pure functions over ``load_decisions()``.

The page (app/views/2_Rankings.py) draws; these decide which rows and figures.
Kept free of Streamlit so the presets, the rank change and the movers can be
tested on a small frame.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.portfolio.score import rank_by_score

CATEGORY_LABEL = {"sector": "Sector", "thematic": "Theme"}
HELD = {"BUY", "HOLD", "TRIM"}

# Preset values are fixed strings: session state stores them. Labels are built
# from the counts on every run.
PRESETS = ("Tradeable", "All", "Held", "Top", "Beating cash", "Sectors", "Themes")
DEFAULT_PRESET = "Tradeable"
SORTS = ("Rank", "Rank Δ", "1M", "3M", "6M", "12M", "Max DD")


def _num(series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _flag(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(False, index=frame.index)
    return frame[column].fillna(False).astype(bool)


def portfolio_rank(decisions: pd.DataFrame) -> pd.Series:
    """Today's rank among the tradeable exposures: the ranking the portfolio acts on.

    ``rank`` is across the whole universe; the month-end ``decision_rank``
    counts only exposures with a fund, so the two cannot be subtracted. This is
    the provisional score re-ranked over the same set as decision_rank, by the
    portfolio's own tie-break (src/portfolio/score.rank_by_score).
    """
    ids = decisions["exposure_id"].astype(str)
    score = pd.Series(_num(decisions["momentum_z"]).to_numpy(), index=ids)
    eligible = _flag(decisions, "tradeable").to_numpy() & score.notna().to_numpy()
    ranks = rank_by_score(score[eligible]).astype(float)
    return ids.map(ranks).astype(float).set_axis(decisions.index)


def rank_change(decisions: pd.DataFrame) -> pd.Series:
    """Places gained since the last rebalance (+ = climbed); NaN without both ranks."""
    return _num(decisions["decision_rank"]) - portfolio_rank(decisions)


def preset_masks(decisions: pd.DataFrame, hurdle: float | None, buffer: int) -> dict[str, pd.Series]:
    """One boolean row mask per preset."""
    tradeable = _flag(decisions, "tradeable")
    r12 = _num(decisions.get("return_12M"))
    category = decisions.get("category", pd.Series("", index=decisions.index)).astype(str)
    return {
        "Tradeable": tradeable,
        "All": pd.Series(True, index=decisions.index),
        "Held": decisions.get("model_action", pd.Series("", index=decisions.index)).isin(HELD),
        "Top": portfolio_rank(decisions) <= buffer,
        "Beating cash": (r12 > hurdle) if hurdle is not None else pd.Series(False, index=decisions.index),
        "Sectors": category == "sector",
        "Themes": category == "thematic",
    }


def preset_label(preset: str, count: int, buffer: int) -> str:
    """'Tradeable 37'. The top-of-buffer preset is 'Top 4' alone: its count is
    the 4 again, unless fewer exposures than that are tradeable."""
    if preset == "Top":
        return f"Top {buffer}" if count == buffer else f"Top {buffer} {count}"
    return f"{preset} {count}"


def fund_counts(vehicles: pd.DataFrame, as_of=None) -> pd.Series:
    """Funds per exposure that had incepted by ``as_of`` (all mapped funds without a date)."""
    if vehicles is None or vehicles.empty or "exposure_id" not in vehicles:
        return pd.Series(dtype=int)
    frame = vehicles
    if as_of is not None and "inception_date" in frame:
        started = pd.to_datetime(frame["inception_date"], errors="coerce")
        frame = frame[started.isna() | (started <= pd.Timestamp(as_of))]
    return frame.groupby(frame["exposure_id"].astype(str)).size()


def search_options(decisions: pd.DataFrame) -> tuple[list[str], dict[str, str], dict[str, list[str]]]:
    """Exposure names in rank order, then each index name once.

    Returns the options, exposure name → exposure_id, and index option → the
    exposure ids on that index (two exposures can share one).
    """
    names = decisions["exposure"].astype(str).tolist()
    by_name = dict(zip(names, decisions["exposure_id"].astype(str)))
    indices: dict[str, list[str]] = {}
    for bench, eid in zip(decisions.get("benchmark", pd.Series(dtype=str)), decisions["exposure_id"].astype(str)):
        bench = str(bench or "").strip()
        if bench and bench not in ("None", "nan"):
            indices.setdefault(f"[INDEX] {bench}", []).append(eid)
    return names + sorted(indices, key=str.lower), by_name, indices


def _dash(value) -> str:
    return "" if value is None or (isinstance(value, float) and np.isnan(value)) or str(value) in ("None", "nan") else str(value)


def display_frame(decisions: pd.DataFrame, levels: pd.Series, funds: pd.Series, hurdle: float | None,
                  relative: bool = False) -> pd.DataFrame:
    """The table's rows: one per exposure, in the columns app/kit/screener_table.py reads."""
    ids = decisions["exposure_id"].astype(str)
    prefix = "relative_" if relative else "return_"
    n_funds = ids.map(funds).fillna(0).astype(int) if len(funds) else pd.Series(0, index=decisions.index)
    category = decisions.get("category", pd.Series("", index=decisions.index)).map(CATEGORY_LABEL).fillna("")
    sub = [
        " · ".join(p for p in (c, _dash(b), ("1 fund" if n == 1 else f"{n} funds") if n else "No fund") if p)
        for c, b, n in zip(category, decisions.get("benchmark", pd.Series("", index=decisions.index)), n_funds)
    ]
    r12_abs = _num(decisions.get("return_12M"))
    out = pd.DataFrame({
        "exposure_id": ids.to_numpy(),
        "Rank": _num(decisions["rank"]).to_numpy(),
        "Exposure": decisions["exposure"].astype(str).to_numpy(),
        "Sub": sub,
        "Category": category.to_numpy(),
        "Index": decisions.get("benchmark", pd.Series("", index=decisions.index)).map(_dash).to_numpy(),
        "Funds": n_funds.to_numpy(),
        "Level": ids.map(levels).astype(float).to_numpy() if len(levels) else np.nan,
        "Rank Δ": rank_change(decisions).to_numpy(),
        "Rebalance rank": _num(decisions["decision_rank"]).to_numpy(),
        "Portfolio rank": portfolio_rank(decisions).to_numpy(),
        **{p: _num(decisions.get(f"{prefix}{p}")).to_numpy() for p in ("1M", "3M", "6M", "12M")},
        "12M vs cash": (r12_abs - hurdle).to_numpy() if hurdle is not None else np.nan,
        "Score": _num(decisions["momentum_z"]).to_numpy(),
        "Portfolio": [
            a if t else "No fund"
            for a, t in zip(decisions.get("model_action", pd.Series("", index=decisions.index)).fillna(""),
                            _flag(decisions, "tradeable"))
        ],
        "Quadrant": decisions.get("stage", pd.Series("", index=decisions.index)).map(_dash).to_numpy(),
        "Max DD": _num(decisions.get("max_drawdown")).to_numpy(),
    }, index=decisions.index)
    out["Portfolio"] = out["Portfolio"].replace({"NOT HELD": "Not held"})
    return out


# Sort option → (table column key for the header arrow, ascending).
SORT_KEYS = {"Rank": ("rank", True), "Rank Δ": ("dlt", False), "1M": ("r1", False), "3M": ("r3", False),
             "6M": ("r6", False), "12M": ("r12", False), "Max DD": ("dd", False)}


def sort_frame(view: pd.DataFrame, sort_by: str) -> pd.DataFrame:
    """Best first: rank 1, the biggest climb, the highest return, the shallowest drawdown."""
    column = sort_by if sort_by in SORT_KEYS and sort_by in view else "Rank"
    ascending = SORT_KEYS[column][1]
    return view.sort_values(column, ascending=ascending, na_position="last", kind="mergesort")


def movers(view: pd.DataFrame, n: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The exposures that climbed and fell most places since the last rebalance."""
    moved = view.dropna(subset=["Rank Δ"])
    risers = moved[moved["Rank Δ"] > 0].sort_values(["Rank Δ", "Portfolio rank"], ascending=[False, True])
    fallers = moved[moved["Rank Δ"] < 0].sort_values(["Rank Δ", "Portfolio rank"], ascending=[True, True])
    return risers.head(n), fallers.head(n)
