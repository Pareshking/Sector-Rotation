"""One column vocabulary for every table in the app, and the raw audit view.

Pages build their own focused tables; this module keeps labels, formats and
help text consistent across them, and renders the full model-input audit.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

DASH = "—"



# --------------------------------------------------------------------------- #
# One taxonomy for every table in the app
# --------------------------------------------------------------------------- #
# Label and format live here and nowhere else, so a column reads the same in the
# ranking, the screener and the raw audit dump. The audit expander previously
# showed bare frames — "return_3M", 0.0556 — which is a different vocabulary for
# the same numbers.
PERCENT = "percent"
COLUMNS: dict[str, tuple[str, str, str]] = {
    # key: (label, kind, help)
    "position": ("#", "int", "Order under the selected lookback"),
    "rank": ("Rank", "int", "Strategy score rank across the universe at the latest session (provisional between rebalances)"),
    "exposure": ("Exposure", "text", ""),
    "exposure_id": ("ID", "text", "Internal identifier"),
    "category": ("Type", "text", "Sector or thematic"),
    "benchmark": ("Benchmark", "text", "Configured canonical index"),
    "resolved_official_index_name": ("Resolved index", "text", "Index NSE actually served"),
    "data_source": ("Source", "text", "Where the history came from"),
    "value_type": ("Value", "text", "TRI = total return; CLOSE = price index; NAV = fund"),
    "model_action": ("Action", "text", "What the target portfolio does at the latest rebalance: BUY / HOLD / TRIM / SELL, or NOT HELD"),
    "target_weight": ("Target weight", PERCENT, "Share of the book in the target portfolio"),
    "decision_rank": ("Decision rank", "int", "Rank among eligible exposures at the latest month-end rebalance"),
    "decision_status": ("Status", "text", "Why the exposure is or is not held"),
    "stage": ("Stage", "text", "Leading, Weakening, Lagging or Improving"),
    "decision_reason": ("Why", "text", ""),
    "analysis_note": ("Note", "text", ""),
    "shares_index_with": ("Shares index with", "text", "Same underlying index as this exposure"),
    "decision_eligible": ("Decision-grade", "bool", "Has the authoritative 12-month history the score needs"),
    "tradeable": ("Buyable", "bool", "A mapped ETF or index fund had incepted by the decision date (recorded inception date)"),
    "momentum_z": ("Score", "z", "Strategy score: weighted z-scores of the 1M, 3M-1M, 6M-3M and 12M-6M returns · 0 = universe average"),
    "rs_ratio": ("RS ratio", "ratio3", "RS line relative to its own 52-week moving average; 1.00 = at the average"),
    "rs_momentum": ("RS vel", "signed1", "13-week change in Mansfield RS"),
    "rs_trend": ("RS trend", "spark", "Mansfield relative strength, last 26 weeks"),
    "return_1M": ("1M", PERCENT, "Index return over the window"),
    "return_3M": ("3M", PERCENT, "Index return over the window"),
    "return_6M": ("6M", PERCENT, "Index return over the window"),
    "return_12M": ("12M", PERCENT, "Index return over the window"),
    "relative_1M": ("1M vs N50", PERCENT, "Exposure return minus Nifty 50 over the window"),
    "relative_3M": ("3M vs N50", PERCENT, "Exposure return minus Nifty 50 over the window"),
    "relative_6M": ("6M vs N50", PERCENT, "Exposure return minus Nifty 50 over the window"),
    "relative_12M": ("12M vs N50", PERCENT, "Exposure return minus Nifty 50 over the window"),
    "alpha": ("Alpha", PERCENT, "Annualised Jensen's alpha vs Nifty 50, after beta"),
    "beta": ("Beta", "ratio2", "Sensitivity to Nifty 50"),
    "r_squared": ("R²", "ratio2", "Share of movement explained by Nifty 50"),
    "information_ratio": ("Info ratio", "signed2", "Active return divided by tracking error"),
    "tracking_error": ("Tracking err", PERCENT, "Annualised volatility of active return"),
    "volatility_3y": ("Vol 3Y", PERCENT, "Annualised standard deviation"),
    "sharpe_3y": ("Sharpe 3Y", "signed2", "Risk-free 6.5%"),
    "sortino_3y": ("Sortino 3Y", "signed2", "Risk-free 6.5%, downside deviation only"),
    "rolling_3y_median": ("Roll 3Y med", PERCENT, "Median rolling 3-year CAGR"),
    "rolling_3y_min": ("Roll 3Y min", PERCENT, "Worst rolling 3-year CAGR"),
    "rolling_3y_positive": ("Roll 3Y +ve", PERCENT, "Share of rolling 3-year windows above zero"),
    "consistency_overall": ("Win rate", PERCENT, "Rolling 1-year windows beating Nifty 50"),
    "consistency_upside": ("Win ↑mkt", PERCENT, "Win rate when Nifty 50 rose"),
    "consistency_downside": ("Win ↓mkt", PERCENT, "Win rate when Nifty 50 fell"),
    "max_drawdown": ("Max DD", PERCENT, "Worst peak-to-trough fall over five years"),
    "drawdown_from_high": ("Off high", PERCENT, "Distance below the all-time high today"),
}

_FORMATS = {
    "percent": "percent", "z": "%+.2f", "signed1": "%+.1f", "signed2": "%+.2f",
    "ratio2": "%.2f", "ratio3": "%.3f", "int": "%d",
}


def column_config(keys) -> dict[str, object]:
    """Streamlit column_config for any subset of the taxonomy."""
    config: dict[str, object] = {}
    for key in keys:
        if key not in COLUMNS:
            continue
        label, kind, help_text = COLUMNS[key]
        common = {"width": "small", "help": help_text or None}
        if kind == "text":
            config[key] = st.column_config.TextColumn(label, **common)
        elif kind == "bool":
            config[key] = st.column_config.CheckboxColumn(label, **common)
        elif kind == "spark":
            config[key] = st.column_config.LineChartColumn(label, **common)
        else:
            config[key] = st.column_config.NumberColumn(label, format=_FORMATS[kind], **common)
    return config


def _tint(value: object, cap: float) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return ""
    if value != value or value == 0:
        return ""
    alpha = 0.06 + 0.30 * min(abs(value) / cap, 1.0)
    rgb = "16,185,129" if value > 0 else "244,63,94"
    return f"background-color: rgba({rgb},{alpha:.3f})"


def tinted(frame: pd.DataFrame, columns, cap: float = 0.25):
    """A Styler shading each return cell by sign and size; legible on light and dark.

    ``cap`` is the magnitude at which the tint saturates, so one outlier does
    not wash every other cell out.
    """
    present = [c for c in columns if c in frame.columns]
    return frame.style.map(lambda v: _tint(v, cap), subset=present)


def _compact(value: float) -> str:
    """Rupee amounts the Indian way: lakh and crore."""
    size = abs(value)
    if size >= 1e7:
        return f"{value / 1e7:,.2f} Cr"
    if size >= 1e5:
        return f"{value / 1e5:,.2f} L"
    return f"{value:,.0f}"


def _formatter(config: dict | None):
    kind = ((config or {}).get("type_config") or {}).get("type")
    fmt = ((config or {}).get("type_config") or {}).get("format")
    if kind in {"date", "datetime"}:
        return lambda v: pd.Timestamp(v).strftime("%d %b %Y")
    if fmt == "percent":
        return lambda v: f"{float(v):.2%}"
    if fmt == "compact":
        return lambda v: _compact(float(v))
    if isinstance(fmt, str) and "%" in fmt:
        return lambda v: fmt % float(v)
    return lambda v: f"{v:g}" if isinstance(v, float) else str(v)


def dashed(frame: pd.DataFrame, config: dict) -> tuple[pd.DataFrame, dict]:
    """Show a missing value as a dash rather than Streamlit's grey "None".

    ``st.dataframe`` has no setting for how it draws an empty cell, so only the
    columns that actually have a gap are turned into right-aligned text, in the
    format their column config already asks for. Those columns then sort as
    text; every column without a gap keeps its numeric sort.
    """
    out, config = frame.copy(), dict(config)
    for column in out.columns:
        if not out[column].isna().any():
            continue
        current = config.get(column) or {}
        kind = (current.get("type_config") or {}).get("type")
        if kind in {"progress", "checkbox", "line_chart", "bar_chart", "area_chart"}:
            continue
        show = _formatter(current)
        out[column] = [DASH if pd.isna(v) else show(v) for v in out[column]]
        config[column] = st.column_config.TextColumn(
            current.get("label"), width=current.get("width"), help=current.get("help"),
            pinned=current.get("pinned"), alignment="left" if kind == "text" else "right",
        )
    return out, config


def show_table(data, column_config: dict | None = None, **kwargs):
    """``st.dataframe`` with missing values shown as a dash (see ``dashed``)."""
    if isinstance(data, pd.DataFrame):
        data, column_config = dashed(data, column_config or {})
    return st.dataframe(data, column_config=column_config, **kwargs)


def audit_frame(frame: pd.DataFrame, key: str | None = None, height: int = 420) -> None:
    """Raw model inputs, in the same vocabulary as every other table."""
    if frame is None or frame.empty:
        st.caption("Nothing to audit.")
        return
    known = [c for c in COLUMNS if c in frame.columns]
    rest = [c for c in frame.columns if c not in known]
    show_table(
        frame[known + rest],
        column_config=column_config(known),
        hide_index=True,
        width="stretch",
        height=height,
        key=key,
    )





_PRETTY_NA = {"none", "nan", "nat", "<na>", ""}
