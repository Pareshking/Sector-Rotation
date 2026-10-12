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


def _stamp(*names: str) -> int:
    return sum(_mtime(name) for name in names)


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


def strategy_config():
    from src.config import load_strategy_config

    return load_strategy_config()


@st.cache_data(show_spinner=False)
def exposure_categories() -> dict[str, str]:
    """exposure_id -> 'sector' or 'thematic'."""
    summary = load_summary()
    if summary.empty or "category" not in summary.columns:
        return {}
    return {str(k): str(v) for k, v in zip(summary["exposure_id"], summary["category"])}


def _names() -> dict[str, str]:
    summary = load_summary()
    if summary.empty or "exposure" not in summary.columns:
        return {}
    return {str(k): str(v) for k, v in zip(summary["exposure_id"], summary["exposure"])}


@st.cache_data(show_spinner=False)
def _universe_metadata(modified_ns: int = 0):
    del modified_ns
    from src.portfolio.universe import build_universe_metadata

    panel, _ = load_index_panel()
    return build_universe_metadata(
        panel.columns, load_etfs(), load_etf_prices(), _names(), exposure_categories()
    )


def universe_metadata():
    """Exposure id -> name, category and the first date a vehicle could be bought."""
    return _universe_metadata(_stamp("index_prices.parquet", "etf_universe.parquet", "etf_prices.parquet"))


@st.cache_data(show_spinner="Building the target portfolio…")
def _portfolio(modified_ns: int = 0):
    del modified_ns
    from src.portfolio.live import live_portfolio

    panel, _ = load_index_panel()
    if panel.empty:
        return None
    return live_portfolio(panel, universe_metadata(), strategy_config())


def load_portfolio():
    """The current ``LivePortfolio``: the latest decision of the strategy's own chain.

    Built by ``src/portfolio`` from the published index panel and fund
    histories — the same call the backtest's final decision comes from.
    """
    return _portfolio(_stamp("index_prices.parquet", "etf_universe.parquet", "etf_prices.parquet"))


@st.cache_data(show_spinner=False)
def _decisions(modified_ns: int = 0) -> pd.DataFrame:
    del modified_ns
    from app.components.metrics import decision_frame
    from src.portfolio.score import score_exposures

    summary = load_summary()
    if summary.empty:
        return summary
    summary = summary.copy()
    panel, _ = load_index_panel()
    if not panel.empty and "exposure_id" in summary.columns:
        # The screen ranks on the strategy's own score as of the latest session,
        # so "rank" on every page is the same measure the portfolio is built on
        # (the portfolio itself only acts on month-end ranks: decision_rank).
        screen = score_exposures(panel, panel.index.max(), strategy_config())
        ids = summary["exposure_id"].astype(str)
        summary["momentum_z"] = ids.map(screen["score"]).astype(float).to_numpy()
        summary["rank"] = ids.map(screen["universe_rank"]).astype(float).to_numpy()
    live = load_portfolio()
    frame = decision_frame(summary, live.target if live else None)
    order = pd.to_numeric(frame.get("rank"), errors="coerce")
    return frame.assign(_order=order).sort_values("_order", na_position="last", kind="mergesort").drop(
        columns="_order"
    ).reset_index(drop=True)


def load_decisions() -> pd.DataFrame:
    """Summary rows annotated with the target portfolio's action for each, cached once."""
    return _decisions(_stamp("summary_rankings.parquet", "index_prices.parquet", "etf_universe.parquet", "etf_prices.parquet"))


def _restrict(panel: pd.DataFrame, category: str) -> pd.DataFrame:
    """Sectors and themes rotate differently, so they can be tested apart."""
    if category in ("", "All", None):
        return panel
    wanted = {"Sectors": "sector", "Themes": "thematic"}.get(category, category)
    lookup = exposure_categories()
    keep = [c for c in panel.columns if lookup.get(str(c)) == wanted]
    return panel[keep] if keep else panel.iloc[:, :0]


def backtest_config(
    top_n: int | None = None,
    buffer_m: int | None = None,
    hold_months: int | None = None,
    absolute_filter: bool | None = None,
    investable_only: bool | None = None,
    cost_bps: float | None = None,
):
    """The live strategy config with what-if overrides. ``None`` keeps the v1.0 value."""
    base = strategy_config()
    changes: dict[str, object] = {}
    if top_n is not None:
        changes["target_holdings_n"] = int(top_n)
    if buffer_m is not None:
        changes["retention_buffer_m"] = int(buffer_m)
    if hold_months is not None:
        changes["rebalance_months"] = int(hold_months)
    if absolute_filter is not None:
        changes["absolute_momentum_filter"] = "dual_momentum_cash_hurdle" if absolute_filter else "none"
    if investable_only is not None:
        changes["require_investable"] = bool(investable_only)
    if cost_bps is not None:
        changes["cost_bps_per_side"] = float(cost_bps)
    return base.replace(**changes) if changes else base


@st.cache_data(show_spinner="Running the backtest…")
def _backtest(config_json: str, months: int | None, category: str, modified_ns: int = 0):
    del modified_ns
    from src.config import StrategyConfig
    from src.quantitative.backtest import run_backtest

    panel, benchmark = load_index_panel()
    panel = _restrict(panel, category)
    config = StrategyConfig.model_validate_json(config_json)
    return run_backtest(panel, benchmark, config, universe_metadata(), months=months)


def load_backtest(config=None, months: int | None = None, category: str = "All"):
    config = config or strategy_config()
    stamp = _stamp("index_prices.parquet", "etf_prices.parquet", "etf_universe.parquet")
    return _backtest(config.model_dump_json(), months, category, stamp)


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
    return _tracking(exposure_id, _stamp("etf_prices.parquet", "index_prices.parquet"))


# Alternative score specifications for the sensitivity grid. v1.0 is the first;
# none of the others is a candidate to replace it on this sample's evidence.
SCORE_SCHEMES: dict[str, dict[str, object]] = {
    "Equal segments (v1.0)": {"method": "segment_composite",
                              "segments": {"1M": 1, "3M-1M": 1, "6M-3M": 1, "12M-6M": 1}},
    "Recent tilt 4/3/2/1": {"method": "segment_composite",
                            "segments": {"1M": 4, "3M-1M": 3, "6M-3M": 2, "12M-6M": 1}},
    "Long tilt 1/2/3/4": {"method": "segment_composite",
                          "segments": {"1M": 1, "3M-1M": 2, "6M-3M": 3, "12M-6M": 4}},
    "No 12M-6M segment": {"method": "segment_composite",
                          "segments": {"1M": 1, "3M-1M": 1, "6M-3M": 1, "12M-6M": 0}},
    "1M only": {"method": "segment_composite",
                "segments": {"1M": 1, "3M-1M": 0, "6M-3M": 0, "12M-6M": 0}},
    "12M return / EWMA vol": {"method": "vol_adjusted_12m"},
}


@st.cache_data(show_spinner="Testing every score specification…")
def _sensitivity(config_json: str, months: int | None, category: str = "All", modified_ns: int = 0):
    del modified_ns
    from src.config import ScoreSpec, StrategyConfig
    from src.quantitative.backtest import weight_sensitivity

    panel, benchmark = load_index_panel()
    panel = _restrict(panel, category)
    if panel.empty:
        return pd.DataFrame()
    base = StrategyConfig.model_validate_json(config_json)
    schemes = {
        label: base.replace(score_weights=ScoreSpec.model_validate(
            {**base.score_weights.model_dump(), **spec}).model_dump())
        for label, spec in SCORE_SCHEMES.items()
    }
    return weight_sensitivity(panel, benchmark, schemes, universe_metadata(), months=months)


def load_sensitivity(config=None, months: int | None = None, category: str = "All"):
    """How much the result depends on the score specification rather than the strategy."""
    config = config or strategy_config()
    stamp = _stamp("index_prices.parquet", "etf_prices.parquet", "etf_universe.parquet")
    return _sensitivity(config.model_dump_json(), months, category, stamp)
