"""Table surfaces for the ranked decision set.

Two complementary renderers:

* ``action_board`` — a compact HTML scan of what to do, laid out as a CSS grid
  so it stays readable on a phone instead of collapsing one cell per line.
* ``ranked_table`` — the analytical surface. A native ``st.dataframe`` so every
  column sorts on click, with the relative-strength trend embedded as a real
  sparkline column.
"""

from __future__ import annotations

from typing import Sequence

import pandas as pd
import streamlit as st

from app.components.theme import (
    _esc,
    _sign_class,
    _zbar,
    action_pill,
    fmt_num,
    fmt_pct,
    fmt_signed,
    stage_cell,
)


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
    "rank": ("Rank", "int", "Composite momentum rank across the universe"),
    "exposure": ("Exposure", "text", ""),
    "exposure_id": ("ID", "text", "Internal identifier"),
    "category": ("Type", "text", "Sector or thematic"),
    "benchmark": ("Benchmark", "text", "Configured canonical index"),
    "resolved_official_index_name": ("Resolved index", "text", "Index NSE actually served"),
    "data_source": ("Source", "text", "Where the history came from"),
    "value_type": ("Value", "text", "TRI = total return; CLOSE = price index; NAV = fund"),
    "model_action": ("Action", "text", "BUY / REDUCE / WATCH"),
    "watch_kind": ("Watch type", "text", "Rolling over, holding, or early turn"),
    "stage": ("Stage", "text", "Leading, Weakening, Lagging or Improving"),
    "decision_reason": ("Why", "text", ""),
    "analysis_note": ("Note", "text", ""),
    "shares_index_with": ("Shares index with", "text", "Same underlying index as this exposure"),
    "decision_eligible": ("Decision-grade", "bool", "Has an authoritative history"),
    "tradeable": ("Buyable", "bool", "A listed ETF that trades, or an open-ended index fund"),
    "momentum_z": ("Momentum Z", "z", "Cross-sectional Z of relative returns · 0 = universe average"),
    "rs_ratio": ("RS ratio", "ratio3", "1.00 = in line with Nifty 50"),
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


def audit_frame(frame: pd.DataFrame, key: str | None = None, height: int = 420) -> None:
    """Raw model inputs, in the same vocabulary as every other table."""
    if frame is None or frame.empty:
        st.caption("Nothing to audit.")
        return
    known = [c for c in COLUMNS if c in frame.columns]
    rest = [c for c in frame.columns if c not in known]
    st.dataframe(
        frame[known + rest],
        column_config=column_config(known),
        hide_index=True,
        width="stretch",
        height=height,
        key=key,
    )


LOOKBACKS = ("1M", "3M", "6M", "12M")

# This is a relative-strength model: what matters is a sector's return *against*
# Nifty 50, not its raw return. In a rising market almost everything is up, so
# ranking on absolute return mostly re-ranks the market itself. Relative is the
# default; absolute stays one click away because it is what a holder actually
# earns.
BASIS_RELATIVE = "vs Nifty 50"
BASIS_ABSOLUTE = "Absolute"
BASES = (BASIS_RELATIVE, BASIS_ABSOLUTE)


def _column_for(period: str, basis: str) -> str:
    if period == "Composite":
        return "momentum_z"
    prefix = "relative_" if basis == BASIS_RELATIVE else "return_"
    return f"{prefix}{period}"


def rs_trend_column(frame: pd.DataFrame, rs: pd.DataFrame | None, window: int = 26) -> list[list[float]]:
    if rs is None or rs.empty or "exposure_id" not in frame.columns:
        return [[] for _ in range(len(frame))]
    return [
        rs[str(eid)].dropna().tail(window).tolist() if str(eid) in rs.columns else []
        for eid in frame["exposure_id"]
    ]


def ranked_table(
    frame: pd.DataFrame,
    rs: pd.DataFrame | None = None,
    sort_by: str = "Composite",
    basis: str = BASIS_RELATIVE,
    height: int | None = None,
    key: str | None = None,
) -> None:
    """Sortable, scannable ranking. Click any header to re-sort."""
    if frame is None or frame.empty:
        st.markdown('<div class="note">No exposures match the current filter.</div>', unsafe_allow_html=True)
        return

    column = _column_for(sort_by, basis)
    view = frame.copy()
    # Fall back to absolute when a dataset predates the relative_* columns.
    if column not in view.columns:
        column = _column_for(sort_by, BASIS_ABSOLUTE)
        basis = BASIS_ABSOLUTE
    if column in view.columns:
        view = view.sort_values(column, ascending=False, na_position="last")
    view = view.reset_index(drop=True)
    view.insert(0, "position", range(1, len(view) + 1))
    view["rs_trend"] = rs_trend_column(view, rs)

    # Column order is the mobile contract: on a narrow screen only the first few
    # survive before horizontal scroll, so the decision itself comes before the
    # supporting evidence, and the category label goes last.
    prefix = "relative_" if basis == BASIS_RELATIVE else "return_"
    period_cols = [f"{prefix}{p}" for p in LOOKBACKS]
    display_cols = [
        "position", "exposure", "model_action", "momentum_z", "stage",
        "rs_trend", "rs_ratio", "rs_momentum", *period_cols,
        "consistency_overall", "consistency_downside", "alpha", "beta",
        "sharpe_3y", "max_drawdown", "tradeable", "category",
    ]
    display_cols = [c for c in display_cols if c in view.columns]

    config = column_config(display_cols)
    # The period columns carry a measure-dependent label, so override just those.
    suffix = " vs N50" if basis == BASIS_RELATIVE else ""
    help_text = (
        "Exposure return minus Nifty 50 over the same window"
        if basis == BASIS_RELATIVE
        else "Index return over the window"
    )
    for period in LOOKBACKS:
        key = f"{prefix}{period}"
        if key in config:
            config[key] = st.column_config.NumberColumn(
                f"{period}{suffix}", format="percent", width="small", help=help_text
            )
    config["exposure"] = st.column_config.TextColumn("Exposure", width="medium", pinned=True)
    config["rs_trend"] = st.column_config.LineChartColumn(
        "RS trend", width="small", help="Mansfield relative strength, last 26 weeks"
    )

    st.dataframe(
        view[display_cols],
        column_config=config,
        hide_index=True,
        width="stretch",
        height=height or min(56 + 35 * len(view), 620),
        key=key,
    )


def action_board(columns: Sequence[tuple[str, str, pd.DataFrame, str]], limit: int = 8) -> None:
    """Side-by-side BUY / WATCH / REDUCE columns; stacks to one column on a phone.

    columns: (title, tone, frame, empty_text)
    """
    blocks = []
    for title, tone, frame, empty in columns:
        items = []
        if frame is None or frame.empty:
            items.append(f'<div class="bempty">{_esc(empty)}</div>')
        else:
            for row in frame.head(limit).to_dict("records"):
                z = pd.to_numeric(row.get("momentum_z"), errors="coerce")
                z_text = f"{z:+.2f}" if z == z else "—"
                flag = "" if row.get("tradeable", True) else '<span class="pill pill-grey">no fund</span>'
                items.append(
                    '<div class="bitem">'
                    f'<div class="bnm">{_esc(row.get("exposure"))}{flag}</div>'
                    f'<div class="bz {_sign_class(z)}">{z_text}</div>'
                    f'<div class="bmet">{stage_cell(row.get("stage", "—"))}'
                    f'<span>RS <b>{fmt_num(row.get("rs_ratio"))}</b></span>'
                    f'<span>Vel <b>{fmt_signed(row.get("rs_momentum"), 1)}</b></span>'
                    f'<span>3M <b>{fmt_pct(row.get("return_3M"))}</b></span>'
                    f'<span>vs N50 <b>{fmt_pct(row.get("relative_3M"))}</b></span></div>'
                    "</div>"
                )
            extra = len(frame) - limit
            if extra > 0:
                items.append(f'<div class="bempty">+{extra} more in the table below</div>')
        count = 0 if frame is None else len(frame)
        blocks.append(
            f'<div class="bcol"><div class="bhead bhead-{tone}"><span>{_esc(title)}</span>'
            f'<span class="bcount">{count}</span></div>{"".join(items)}</div>'
        )
    st.markdown(f'<div class="board">{"".join(blocks)}</div>', unsafe_allow_html=True)


def signal_rows(frame: pd.DataFrame, rs: pd.DataFrame | None = None, limit: int | None = None) -> None:
    """Compact HTML rows — used where a phone-first scan beats a wide table."""
    if frame is None or frame.empty:
        st.markdown('<div class="note">Nothing to show here.</div>', unsafe_allow_html=True)
        return
    view = frame if limit is None else frame.head(limit)
    scale = pd.to_numeric(view.get("momentum_z"), errors="coerce").abs().max()
    scale = float(scale) if scale == scale and scale else 1.0
    rows = []
    for row in view.to_dict("records"):
        rank = pd.to_numeric(row.get("rank"), errors="coerce")
        flag = "" if row.get("tradeable", True) else ' <span class="pill pill-grey">no fund</span>'
        shares = row.get("shares_index_with")
        cat = str(row.get("category", "") or "")
        rows.append(
            '<div class="sig">'
            f'<div class="sig-rank">{int(rank) if rank == rank else "—"}</div>'
            f'<div class="sig-name"><span class="rt-nm">{_esc(row.get("exposure"))}{flag}</span>'
            f'<span class="rt-cat">{_esc(cat + (" · shares index with " + str(shares) if shares else ""))}</span></div>'
            f'<div class="sig-act">{action_pill(row.get("model_action"))}</div>'
            f'<div class="sig-meta">{stage_cell(row.get("stage", "—"))}'
            f'{_zbar(row.get("momentum_z"), scale)}'
            f'<span>RS <b>{fmt_num(row.get("rs_ratio"))}</b></span>'
            f'<span>1M <b>{fmt_pct(row.get("return_1M"))}</b></span>'
            f'<span>3M <b>{fmt_pct(row.get("return_3M"))}</b></span>'
            f'<span>3M vs N50 <b>{fmt_pct(row.get("relative_3M"))}</b></span>'
            f'<span>12M <b>{fmt_pct(row.get("return_12M"))}</b></span></div>'
            "</div>"
        )
    st.markdown(f'<div class="rt">{"".join(rows)}</div>', unsafe_allow_html=True)


_PRETTY_NA = {"none", "nan", "nat", "<na>", ""}


def clean_table(frame: pd.DataFrame, columns: Sequence[tuple[str, str]]) -> pd.DataFrame:
    """Audit table with real em-dashes instead of the literal string 'None'."""
    pairs = [(key, label) for key, label in columns if key in frame.columns]
    display = frame[[key for key, _ in pairs]].copy()
    for key, _ in pairs:
        if key.startswith("return_") or key.startswith("relative_"):
            display[key] = display[key].map(fmt_pct)
        elif key in {"momentum_z", "rs_ratio", "rs_momentum", "expense_ratio", "tracking_error"}:
            display[key] = display[key].map(fmt_num)
        else:
            display[key] = display[key].map(
                lambda v: "—" if v is None or str(v).strip().lower() in _PRETTY_NA else str(v)
            )
    return display.rename(columns=dict(pairs))
