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


@st.cache_data(show_spinner="Running the monthly backtest…")
def _backtest(top_n: int, months: int, absolute_filter: bool, modified_ns: int = 0):
    del modified_ns
    from src.quantitative.backtest import run_backtest

    panel, benchmark = load_index_panel()
    return run_backtest(
        panel, benchmark, top_n=top_n, months=months, absolute_filter=absolute_filter
    )


def load_backtest(top_n: int = 2, months: int = 12, absolute_filter: bool = True):
    return _backtest(top_n, months, absolute_filter, _mtime("index_prices.parquet"))


@st.cache_data(show_spinner=False)
def _tradeable_ids(modified_ns: int = 0) -> set[str]:
    del modified_ns
    etfs = load_etfs()
    if etfs.empty or "exposure_id" not in etfs.columns:
        return set()
    # NSE's own listed-ETF feed reporting turnover is stronger evidence that an
    # instrument can be bought than whether our pipeline happened to ingest its
    # NAV history — MFAPI outages routinely leave a live, liquid ETF with no
    # series on disk.
    # An open-ended index fund transacts at NAV with no exchange listing, so it
    # is investable even though NSE reports no turnover for it.
    is_fund = etfs.get("vehicle", pd.Series("etf", index=etfs.index)).eq("index_fund")
    if "traded_value" in etfs.columns:
        traded = pd.to_numeric(etfs["traded_value"], errors="coerce").fillna(0) > 0
        investable = traded | is_fund
        if investable.any():
            return set(etfs.loc[investable, "exposure_id"].dropna().astype(str))
    if is_fund.any():
        return set(etfs.loc[is_fund, "exposure_id"].dropna().astype(str))
    prices = load_etf_prices()
    if prices.empty:
        return set()
    keyed = etfs.assign(key=etfs["symbol"].fillna(etfs["name"]))
    with_history = keyed[keyed["key"].isin(prices.columns)]
    return set(with_history["exposure_id"].dropna().astype(str))


def tradeable_exposure_ids() -> set[str]:
    """Exposures with a listed ETF that actually trades.

    A BUY on an exposure with no instrument is research, not a trade.
    """
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
