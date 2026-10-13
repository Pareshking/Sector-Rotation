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
SORTS = ("Rank", "1M Δ", "1M", "3M", "6M", "12M", "Max DD 3M")
# Presets drawn from the tradeable set number their rows by the portfolio's own
# ranking (1, 2, 3 …); the rest use the universe rank.
PORTFOLIO_RANKED = {"Tradeable", "Held", "Top"}


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


def past_ranks(chain: list, months_back: int) -> pd.Series:
    """The portfolio's rank of each exposure ``months_back`` month-end decisions ago.

    ``chain`` is the backtest's decision chain (``load_backtest().decisions``,
    one TargetPortfolio per month-end, the last being the latest rebalance).
    Its ``ranking["rank"]`` is ranked over the exposures buyable on that date,
    the same set ``portfolio_rank`` ranks over today. Empty when the chain is
    shorter than that.
    """
    if not chain or len(chain) < months_back:
        return pd.Series(dtype=float)
    ranking = chain[-months_back].ranking
    if ranking is None or "rank" not in ranking:
        return pd.Series(dtype=float)
    return pd.to_numeric(ranking["rank"], errors="coerce").astype(float).rename(lambda i: str(i))


def max_drawdown(panel: pd.DataFrame, sessions: int = 63) -> pd.Series:
    """Deepest fall from a running peak over the last ``sessions`` sessions (63 ≈ 3 months)."""
    if panel is None or panel.empty:
        return pd.Series(dtype=float)
    window = panel.iloc[-min(sessions, len(panel)):].apply(pd.to_numeric, errors="coerce")
    dd = (window / window.cummax() - 1.0).min()
    return dd.where(window.notna().sum() >= 2).rename(lambda i: str(i))


# All-caps words in NSE index names that are not ordinary words.
_KEEP_UPPER = {"IT", "PSU", "PSE", "CPSE", "FMCG", "MNC", "EV", "BSE", "TRI", "ETF"}
_SPECIAL = {"MIDSMALL": "MidSmall", "REITS": "REITs", "INVITS": "InvITs"}


def index_name(name) -> str:
    """'NIFTY MIDSMALL IT & TELECOM' → 'Nifty MidSmall IT & Telecom'; mixed-case names stay as they are."""
    text = _dash(name).strip()
    if not text or text != text.upper():
        return text

    def word(w: str) -> str:
        core = w.strip("()")
        if core in _SPECIAL:
            return w.replace(core, _SPECIAL[core])
        if core in _KEEP_UPPER:
            return w
        return "-".join(part.capitalize() for part in w.split("-"))

    return " ".join(word(w) for w in text.split(" "))


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
                  relative: bool = False, *, ranks_1m: pd.Series | None = None,
                  ranks_3m: pd.Series | None = None, drawdown_3m: pd.Series | None = None,
                  portfolio_ranked: bool = False) -> pd.DataFrame:
    """The table's rows: one per exposure, in the columns app/kit/screener_table.py reads.

    ``ranks_1m`` / ``ranks_3m`` are the portfolio's ranks one and three
    month-end decisions ago (``past_ranks``); 1M Δ and 3M Δ compare them with
    today's tradeable rank. ``portfolio_ranked`` numbers the Rank column by
    that tradeable rank instead of the universe rank.
    """
    ids = decisions["exposure_id"].astype(str)
    prefix = "relative_" if relative else "return_"
    n_funds = ids.map(funds).fillna(0).astype(int) if len(funds) else pd.Series(0, index=decisions.index)
    category = decisions.get("category", pd.Series("", index=decisions.index)).map(CATEGORY_LABEL).fillna("")
    # A CLOSE series is a price index (dividends left out, e.g. BSE Insurance),
    # so its returns are not comparable with a TRI row's without saying so.
    price_only = decisions.get("value_type", pd.Series("", index=decisions.index)).astype(str).str.upper() == "CLOSE"
    sub = [
        " · ".join(p for p in (c, index_name(b), ("1 fund" if n == 1 else f"{n} funds") if n else "No fund",
                               "price index" if close else "") if p)
        for c, b, n, close in zip(category, decisions.get("benchmark", pd.Series("", index=decisions.index)),
                                  n_funds, price_only)
    ]
    r12_abs = _num(decisions.get("return_12M"))
    universe = _num(decisions["rank"])
    tradeable_rank = portfolio_rank(decisions)

    def then(ranks: pd.Series | None) -> pd.Series:
        if ranks is None:
            return pd.Series(np.nan, index=decisions.index)
        return ids.map(ranks).astype(float).set_axis(decisions.index)

    was_1m = then(ranks_1m) if ranks_1m is not None else _num(decisions["decision_rank"])
    was_3m = then(ranks_3m)
    out = pd.DataFrame({
        "exposure_id": ids.to_numpy(),
        "Rank": (tradeable_rank if portfolio_ranked else universe).to_numpy(),
        "Universe rank": universe.to_numpy(),
        "Portfolio rank": tradeable_rank.to_numpy(),
        "Exposure": decisions["exposure"].astype(str).to_numpy(),
        "Sub": sub,
        "Category": category.to_numpy(),
        "Price index": price_only.to_numpy(),
        "Index": decisions.get("benchmark", pd.Series("", index=decisions.index)).map(index_name).to_numpy(),
        "Funds": n_funds.to_numpy(),
        "Level": ids.map(levels).astype(float).to_numpy() if len(levels) else np.nan,
        "1M Δ": (was_1m - tradeable_rank).to_numpy(),
        "3M Δ": (was_3m - tradeable_rank).to_numpy(),
        "1M rank": was_1m.to_numpy(),
        "3M rank": was_3m.to_numpy(),
        **{p: _num(decisions.get(f"{prefix}{p}")).to_numpy() for p in ("1M", "3M", "6M", "12M")},
        "Max DD 3M": (ids.map(drawdown_3m).astype(float).to_numpy()
                      if drawdown_3m is not None and len(drawdown_3m) else np.nan),
        "12M vs cash": (r12_abs - hurdle).to_numpy() if hurdle is not None else np.nan,
        "Score": _num(decisions["momentum_z"]).to_numpy(),
        "Portfolio": [
            a if t else "No fund"
            for a, t in zip(decisions.get("model_action", pd.Series("", index=decisions.index)).fillna(""),
                            _flag(decisions, "tradeable"))
        ],
        "Quadrant": decisions.get("stage", pd.Series("", index=decisions.index)).map(_dash).to_numpy(),
    }, index=decisions.index)
    out["Portfolio"] = out["Portfolio"].replace({"NOT HELD": "Not held"})
    return out


# Sort option → (table column key for the header arrow, ascending).
SORT_KEYS = {"Rank": ("rank", True), "1M Δ": ("d1m", False), "1M": ("r1", False), "3M": ("r3", False),
             "6M": ("r6", False), "12M": ("r12", False), "Max DD 3M": ("dd3", False)}


def sort_frame(view: pd.DataFrame, sort_by: str) -> pd.DataFrame:
    """Best first: rank 1, the biggest climb, the highest return, the shallowest drawdown."""
    column = sort_by if sort_by in SORT_KEYS and sort_by in view else "Rank"
    ascending = SORT_KEYS[column][1]
    return view.sort_values(column, ascending=ascending, na_position="last", kind="mergesort")


def movers(view: pd.DataFrame, n: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    """The exposures that climbed and fell most places since the last rebalance (1M Δ)."""
    moved = view.dropna(subset=["1M Δ"])
    risers = moved[moved["1M Δ"] > 0].sort_values(["1M Δ", "Portfolio rank"], ascending=[False, True])
    fallers = moved[moved["1M Δ"] < 0].sort_values(["1M Δ", "Portfolio rank"], ascending=[True, True])
    return risers.head(n), fallers.head(n)
