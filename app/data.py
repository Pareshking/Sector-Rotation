from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "processed"
UNIVERSE_PATH = ROOT / "data" / "universe" / "universe.json"


def _mtime(name: str) -> int:
    try:
        return (DATA_DIR / name).stat().st_mtime_ns
    except OSError:
        return 0


def _stamp(*names: str) -> int:
    try:
        universe = UNIVERSE_PATH.stat().st_mtime_ns
    except OSError:
        universe = 0
    return sum(_mtime(name) for name in names) + universe


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


def load_cash_nav():
    """The liquid fund's NAV (the cash return), or None before the pipeline has written it."""
    from src.portfolio.live import cash_series

    return cash_series(read_parquet("cash_nav.parquet", _mtime("cash_nav.parquet")))


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
    from src.portfolio.live import load_registry
    from src.portfolio.universe import build_universe_metadata

    panel, _ = load_index_panel()
    return build_universe_metadata(panel.columns, load_registry(UNIVERSE_PATH), _names(), exposure_categories())


def universe_metadata():
    """Exposure id -> name, category, launch date and the first date a vehicle could be bought.

    From universe.json's authoritative dates, never from the nightly fund prices.
    """
    return _universe_metadata(_stamp("index_prices.parquet", "summary_rankings.parquet"))


@st.cache_data(show_spinner="Building the target portfolio…")
def _portfolio(modified_ns: int = 0):
    del modified_ns
    from src.portfolio.live import live_portfolio

    panel, _ = load_index_panel()
    if panel.empty:
        return None
    return live_portfolio(panel, universe_metadata(), strategy_config(), load_cash_nav())


def load_portfolio():
    """The current ``LivePortfolio``: the latest decision of the strategy's own chain.

    Built by ``src/portfolio`` from the published index panel and fund
    histories — the same call the backtest's final decision comes from.
    """
    return _portfolio(_stamp("index_prices.parquet", "cash_nav.parquet", "summary_rankings.parquet"))


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
    return _decisions(_stamp("summary_rankings.parquet", "index_prices.parquet", "cash_nav.parquet"))


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
    exclude_backcalculated: bool | None = None,
):
    """The live strategy config with what-if overrides. ``None`` keeps the live value."""
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
    if exclude_backcalculated is not None:
        changes["backfill_policy"] = "exclude_prelaunch" if exclude_backcalculated else "include"
    return base.replace(**changes) if changes else base


# Bounded: every what-if combination is a separate cache entry, and the page
# exposes thousands of them. Without a cap a long session grows without limit.
@st.cache_data(show_spinner="Running the backtest…", max_entries=32)
def _backtest(config_json: str, months: int | None, category: str, modified_ns: int = 0):
    del modified_ns
    from src.config import StrategyConfig
    from src.quantitative.backtest import run_backtest

    panel, benchmark = load_index_panel()
    panel = _restrict(panel, category)
    config = StrategyConfig.model_validate_json(config_json)
    return run_backtest(panel, benchmark, config, universe_metadata(), months=months, cash_nav=load_cash_nav())


def load_backtest(config=None, months: int | None = None, category: str = "All"):
    config = config or strategy_config()
    stamp = _stamp("index_prices.parquet", "cash_nav.parquet", "summary_rankings.parquet")
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


@st.cache_data(show_spinner="Testing every score specification…", max_entries=32)
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
    return weight_sensitivity(panel, benchmark, schemes, universe_metadata(), months=months, cash_nav=load_cash_nav())


def load_sensitivity(config=None, months: int | None = None, category: str = "All"):
    """How much the result depends on the score specification rather than the strategy."""
    config = config or strategy_config()
    stamp = _stamp("index_prices.parquet", "cash_nav.parquet", "summary_rankings.parquet")
    return _sensitivity(config.model_dump_json(), months, category, stamp)


# --------------------------------------------------------------------------- #
# The what-if grid, defined once: the Evidence page builds its controls from it
# and the Deflated Sharpe ratio counts its strategy-defining options as trials.
# --------------------------------------------------------------------------- #
STRATEGY_OPTIONS: dict[str, list[object]] = {
    "Hold top N": [1, 2, 3, 5],
    "Retention buffer": ["M = 2N", "Off (M = N)"],
    "Holding period (months)": [1, 2, 3, 6],
    "Cash hurdle": ["On", "Off"],
    "Back-calculated history": ["Included", "Excluded"],
    "Score specification": list(SCORE_SCHEMES),
}
EVALUATION_OPTIONS: dict[str, list[object]] = {
    "Universe": ["Buyable (strategy)", "All indices (signal)"],
    "History window": ["All", 24, 36, 48],
    "Which exposures": ["All", "Sectors", "Themes"],
    "Cost per side (bps)": [0, 10, 25, 50],
}


def _product(options: dict[str, list[object]]) -> int:
    total = 1
    for values in options.values():
        total *= len(values)
    return total


STRATEGY_TRIALS = _product(STRATEGY_OPTIONS)
EVALUATION_SETTINGS = _product(EVALUATION_OPTIONS)


@st.cache_data(show_spinner=False)
def _vehicle_frame(modified_ns: int = 0) -> pd.DataFrame:
    """Every vehicle with its authoritative inception date (universe.json) and its NSE snapshot.

    Inception dates come from the registry, never from the snapshot file, so a
    dataset published before the dates existed still chooses correctly.
    """
    del modified_ns
    from src.portfolio.live import load_registry

    rows = [
        {
            "exposure_id": exposure.id,
            "symbol": vehicle.symbol,
            "name": vehicle.name,
            "vehicle": vehicle.vehicle.value,
            "scheme_code": vehicle.scheme_code,
            "inception_date": pd.Timestamp(vehicle.inception_date) if vehicle.inception_date else pd.NaT,
        }
        for exposure in load_registry(UNIVERSE_PATH).all()
        for vehicle in exposure.etfs
    ]
    frame = pd.DataFrame(rows)
    snapshot = load_etfs()
    if not snapshot.empty:
        keep = [c for c in ("traded_value", "premium_discount_pct", "last_price", "nav") if c in snapshot.columns]
        snap = snapshot.assign(_key=snapshot["symbol"].fillna(snapshot["name"]))[["exposure_id", "_key", *keep]]
        frame = frame.assign(_key=frame["symbol"].fillna(frame["name"])).merge(
            snap, on=["exposure_id", "_key"], how="left"
        ).drop(columns="_key")
    return frame


def vehicle_frame(exposure_id: str | None = None) -> pd.DataFrame:
    """Every mapped vehicle (or one exposure's), with inception date and NSE snapshot."""
    frame = _vehicle_frame(_stamp("etf_universe.parquet"))
    if exposure_id is None or frame.empty:
        return frame
    return frame[frame["exposure_id"].astype(str) == str(exposure_id)].reset_index(drop=True)


def best_vehicle(exposure_id: str, as_of):
    """The fund to buy ``exposure_id`` through on ``as_of`` (src/portfolio/vehicles.py)."""
    from src.portfolio.vehicles import choose_vehicle

    frame = _vehicle_frame(_stamp("etf_universe.parquet"))
    return choose_vehicle(exposure_id, as_of, frame, vehicle_tracking(exposure_id))


def current_regime():
    """RISK-ON / RISK-OFF: Nifty 50 TRI's 12-month return against cash's (display only)."""
    from src.portfolio.regime import market_regime

    _, benchmark = load_index_panel()
    if benchmark.empty:
        return None
    return market_regime(benchmark, load_cash_nav(), strategy_config().risk_free_rate_annual)
