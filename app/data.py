from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "processed"


def _mtime(name: str) -> int:
    try:
        return (DATA_DIR / name).stat().st_mtime_ns
    except OSError:
        return 0


@st.cache_data(show_spinner=False)
def read_parquet(name: str, modified_ns: int = 0) -> pd.DataFrame:
    del modified_ns
    path = DATA_DIR / name
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def load_summary() -> pd.DataFrame:
    return read_parquet("summary_rankings.parquet", _mtime("summary_rankings.parquet"))


def load_rs() -> pd.DataFrame:
    return read_parquet("rs_matrix.parquet", _mtime("rs_matrix.parquet"))


def load_etfs() -> pd.DataFrame:
    return read_parquet("etf_universe.parquet", _mtime("etf_universe.parquet"))


def load_etf_prices() -> pd.DataFrame:
    return read_parquet("etf_prices.parquet", _mtime("etf_prices.parquet"))


@st.cache_data(show_spinner=False)
def _decisions(modified_ns: int = 0) -> pd.DataFrame:
    del modified_ns
    from app.components.metrics import decision_frame

    summary = load_summary()
    if summary.empty:
        return summary
    frame = decision_frame(summary).sort_values("rank", ignore_index=True)
    if "exposure_id" in frame.columns:
        frame["tradeable"] = frame["exposure_id"].astype(str).isin(tradeable_exposure_ids())
    return frame


def load_decisions() -> pd.DataFrame:
    """Summary rows with the decision boundary already applied, cached once.

    The previous pages recomputed this two or three times per render.
    """
    return _decisions(_mtime("summary_rankings.parquet"))


BENCHMARK_COLUMN = "__benchmark__"


def load_index_panel() -> tuple[pd.DataFrame, pd.Series]:
    """Canonical index levels and the Nifty 50 benchmark, split apart.

    Returns empty frames when the pipeline has not written the panel yet, so the
    rest of the app keeps working on an older dataset.
    """
    panel = read_parquet("index_prices.parquet", _mtime("index_prices.parquet"))
    if panel.empty or BENCHMARK_COLUMN not in panel.columns:
        return pd.DataFrame(), pd.Series(dtype=float)
    benchmark = panel[BENCHMARK_COLUMN].dropna()
    return panel.drop(columns=[BENCHMARK_COLUMN]), benchmark


@st.cache_data(show_spinner=False)
def vehicles_by_exposure() -> dict[str, list[str]]:
    """Exposure id -> the price-series keys of every vehicle mapped to it."""
    etfs = load_etfs()
    if etfs.empty or "exposure_id" not in etfs.columns:
        return {}
    keyed = etfs.assign(key=etfs["symbol"].fillna(etfs["name"]))
    return {
        str(k): list(v) for k, v in keyed.groupby("exposure_id")["key"].apply(list).items()
    }


@st.cache_data(show_spinner=False)
def exposure_categories() -> dict[str, str]:
    """exposure_id -> 'sector' or 'thematic'."""
    summary = load_summary()
    if summary.empty or "category" not in summary.columns:
        return {}
    return {str(k): str(v) for k, v in zip(summary["exposure_id"], summary["category"])}


def _restrict(panel: pd.DataFrame, category: str) -> pd.DataFrame:
    """Sectors and themes rotate differently, so they can be tested apart."""
    if category in ("", "All", None):
        return panel
    wanted = {"Sectors": "sector", "Themes": "thematic"}.get(category, category)
    lookup = exposure_categories()
    keep = [c for c in panel.columns if lookup.get(str(c)) == wanted]
    return panel[keep] if keep else panel.iloc[:, :0]


@st.cache_data(show_spinner="Running the backtest…")
def _backtest(
    top_n: int,
    months: int,
    hold_months: int,
    absolute_filter: bool,
    investable_only: bool,
    require_buy: bool,
    max_rank_depth: int,
    category: str,
    modified_ns: int = 0,
):
    del modified_ns
    from src.quantitative.backtest import run_backtest

    panel, benchmark = load_index_panel()
    panel = _restrict(panel, category)
    return run_backtest(
        panel,
        benchmark,
        top_n=top_n,
        months=months,
        hold_months=hold_months,
        absolute_filter=absolute_filter,
        investable_only=investable_only,
        require_buy=require_buy,
        max_rank_depth=max_rank_depth,
        vehicle_prices=load_etf_prices() if investable_only else None,
        vehicles_by_exposure=vehicles_by_exposure() if investable_only else None,
    )


def load_backtest(
    top_n: int = 2,
    months: int = 12,
    hold_months: int = 1,
    absolute_filter: bool = True,
    investable_only: bool = False,
    require_buy: bool = False,
    max_rank_depth: int = 3,
    category: str = "All",
):
    stamp = _mtime("index_prices.parquet") + _mtime("etf_prices.parquet") + _mtime("etf_universe.parquet")
    return _backtest(
        top_n, months, hold_months, absolute_filter,
        investable_only, require_buy, max_rank_depth, category, stamp,
    )


@st.cache_data(show_spinner=False)
def _tradeable_ids(modified_ns: int = 0) -> set[str]:
    del modified_ns
    from src.universe.tradeability import investable_exposure_ids

    return investable_exposure_ids(load_etfs(), load_etf_prices())


def tradeable_exposure_ids() -> set[str]:
    """Exposures with a listed ETF that trades, or an open-ended index fund."""
    return _tradeable_ids(_mtime("etf_universe.parquet") + _mtime("etf_prices.parquet"))


@st.cache_data(show_spinner=False)
def _liquidity(modified_ns: int = 0) -> pd.DataFrame:
    del modified_ns
    etfs = load_etfs()
    if etfs.empty or "traded_value" not in etfs.columns:
        return pd.DataFrame()
    frame = etfs.copy()
    frame["traded_value"] = pd.to_numeric(frame["traded_value"], errors="coerce")
    best = frame.sort_values("traded_value", ascending=False).groupby("exposure_id", as_index=False).first()
    return best[["exposure_id", "symbol", "traded_value", "premium_discount_pct"]]


def exposure_liquidity() -> pd.DataFrame:
    """Most-traded ETF per exposure, with its premium or discount to NAV."""
    return _liquidity(_mtime("etf_universe.parquet"))


@st.cache_data(show_spinner=False)
def _tracking(exposure_id: str, modified_ns: int = 0) -> pd.DataFrame:
    del modified_ns
    from src.quantitative.analytics import vehicle_tracking_table

    panel, _ = load_index_panel()
    if panel.empty or exposure_id not in panel.columns:
        return pd.DataFrame()
    etfs = load_etfs()
    if etfs.empty:
        return pd.DataFrame()
    vehicles = etfs[etfs["exposure_id"].astype(str) == str(exposure_id)]
    return vehicle_tracking_table(load_etf_prices(), vehicles, panel[exposure_id])


def vehicle_tracking(exposure_id: str) -> pd.DataFrame:
    """Tracking difference and error for each vehicle against its own index."""
    return _tracking(
        exposure_id, _mtime("etf_prices.parquet") + _mtime("index_prices.parquet")
    )


WEIGHT_SCHEMES: dict[str, dict[str, float]] = {
    "Equal (live default)": {"1M": 25, "3M": 25, "6M": 25, "12M": 25},
    "Short 1/3/6": {"1M": 33, "3M": 33, "6M": 34, "12M": 0},
    "Tilted 10/50/40": {"1M": 10, "3M": 50, "6M": 40, "12M": 0},
    "Classic 6-12": {"1M": 0, "3M": 0, "6M": 50, "12M": 50},
    "3M only": {"1M": 0, "3M": 100, "6M": 0, "12M": 0},
    "12M only": {"1M": 0, "3M": 0, "6M": 0, "12M": 100},
}


@st.cache_data(show_spinner="Testing every weighting…")
def _sensitivity(
    top_n: int, months: int, hold_months: int, absolute_filter: bool,
    investable_only: bool, require_buy: bool, max_rank_depth: int,
    category: str = "All", modified_ns: int = 0,
):
    del modified_ns
    from src.quantitative.backtest import weight_sensitivity

    panel, benchmark = load_index_panel()
    panel = _restrict(panel, category)
    if panel.empty:
        return pd.DataFrame()
    return weight_sensitivity(
        panel, benchmark, WEIGHT_SCHEMES,
        top_n=top_n, months=months, hold_months=hold_months,
        absolute_filter=absolute_filter, investable_only=investable_only,
        require_buy=require_buy, max_rank_depth=max_rank_depth,
        vehicle_prices=load_etf_prices() if investable_only else None,
        vehicles_by_exposure=vehicles_by_exposure() if investable_only else None,
    )


def load_sensitivity(
    top_n: int = 2, months: int = 60, hold_months: int = 1, absolute_filter: bool = True,
    investable_only: bool = True, require_buy: bool = True, max_rank_depth: int = 3,
    category: str = "All",
):
    """How much the result depends on the weighting rather than the strategy."""
    stamp = _mtime("index_prices.parquet") + _mtime("etf_prices.parquet")
    return _sensitivity(
        top_n, months, hold_months, absolute_filter,
        investable_only, require_buy, max_rank_depth, category, stamp,
    )
