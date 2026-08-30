from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import CHART_CONFIG, drawdown_chart, etf_comparison, price_chart, rs_trajectory
from app.components.metrics import source_label
from app.components.theme import (
    ACTION_CLASS,
    _esc,
    fmt_num,
    fmt_pct,
    inject_theme,
    kpi_strip,
    note,
    page_header,
    section,
)
from app.data import load_decisions, load_etf_prices, load_etfs, load_rs

inject_theme()
page_header(
    "Implementation",
    "Exposure Detail",
    "Start with the model decision, understand why it was reached, then validate the vehicle you "
    "would actually buy.",
)

decisions = load_decisions()
if decisions.empty:
    st.info("No prepared model data is available.")
    st.stop()

etfs = load_etfs()
rs = load_rs()
etf_prices = load_etf_prices()

# Every exposure is selectable, not only the ones with a mapped ETF. Restricting
# the picker to ETF rows hid 25 of 43 exposures from this page entirely.
options = decisions.exposure.tolist()
exposure = st.selectbox("Exposure", options, key="detail_exposure")
signal = decisions[decisions.exposure == exposure].iloc[0]
selected = etfs[etfs.exposure == exposure].copy() if not etfs.empty else pd.DataFrame()

action = str(signal.get("model_action", "WATCH"))
tone = ACTION_CLASS.get(action, "slate")
tone = tone if tone in {"buy", "red", "blue", "grey"} else ""
shares = signal.get("shares_index_with")
value_type = str(signal.get("value_type", "") or "")
source_bits = [source_label(signal.get("data_source"))]
if value_type:
    source_bits.append(f"{value_type} series")
source_bits.append(str(signal.get("resolved_official_index_name", "")))

section("Model decision")
st.markdown(
    f'<div class="hero hero-{tone or "grey"}"><div class="hero-top">'
    f'<span class="hero-act">{_esc(action)}</span>'
    f'<span class="pill pill-slate">{_esc(signal.get("stage", "—"))}</span>'
    f'<span class="pill pill-grey">Rank {int(signal["rank"]) if signal["rank"] == signal["rank"] else "—"}</span>'
    f'</div><div class="hero-why">{_esc(signal.get("analysis_note", ""))}</div>'
    f'<div class="hero-src">{_esc(" · ".join(b for b in source_bits if b))}</div></div>',
    unsafe_allow_html=True,
)

if shares:
    note(
        f"This exposure resolves to the same underlying index as <b>{_esc(str(shares))}</b>. "
        "They will always move together — holding both is one bet, not two.",
        tone="amber",
    )

kpi_strip(
    [
        ("Momentum Z", fmt_num(signal.get("momentum_z")), "cross-sectional", ""),
        ("RS ratio", fmt_num(signal.get("rs_ratio"), 3), "1.00 = Nifty 50", ""),
        ("RS velocity", fmt_num(signal.get("rs_momentum"), 1), "13-week change", ""),
        ("12M return", fmt_pct(signal.get("return_12M")), "index level", ""),
    ]
)
kpi_strip(
    [
        ("1M", fmt_pct(signal.get("return_1M")), "", ""),
        ("3M", fmt_pct(signal.get("return_3M")), "", ""),
        ("6M", fmt_pct(signal.get("return_6M")), "", ""),
        ("12M", fmt_pct(signal.get("return_12M")), "", ""),
    ]
)

exposure_id = str(signal.get("exposure_id", ""))
if exposure_id in getattr(rs, "columns", []):
    section("Relative strength", "Mansfield RS against Nifty 50 · 52-week baseline")
    st.plotly_chart(rs_trajectory(rs, exposure_id), width="stretch", config=CHART_CONFIG)

section("Implementation vehicle")
if selected.empty:
    note(
        "No listed ETF or fund is currently mapped to this exposure. The index signal stands, but "
        "there is no direct instrument in the universe to express it."
    )
else:
    vehicles = selected.sort_values("traded_value", ascending=False) if "traded_value" in selected else selected
    st.dataframe(
        vehicles,
        hide_index=True,
        width="stretch",
        column_order=[
            c for c in ["symbol", "name", "traded_value", "premium_discount_pct",
                        "last_price", "nav", "expense_ratio", "tracking_error"]
            if c in vehicles.columns
        ],
        column_config={
            "symbol": st.column_config.TextColumn("Symbol", width="small", pinned=True),
            "name": st.column_config.TextColumn("Fund", width="large"),
            "vehicle": st.column_config.TextColumn(
                "Type", width="small",
                help="etf = bought on exchange at a price that can differ from NAV; "
                     "index_fund = bought from the AMC at NAV, no spread or premium",
            ),
            "traded_value": st.column_config.NumberColumn(
                "Turnover ₹", format="compact", width="small",
                help="Value traded on NSE at the last pipeline snapshot. Thin turnover means a "
                     "wide spread, whatever the signal says.",
            ),
            "premium_discount_pct": st.column_config.NumberColumn(
                "Prem/disc %", format="%+.2f", width="small",
                help="Last price against NAV. A persistent premium is a permanent cost on entry.",
            ),
            "last_price": st.column_config.NumberColumn("Price", format="%.2f", width="small"),
            "nav": st.column_config.NumberColumn("NAV", format="%.2f", width="small"),
            "expense_ratio": st.column_config.NumberColumn("Expense", format="%.2f", width="small"),
            "tracking_error": st.column_config.NumberColumn("Tracking err", format="%.2f", width="small"),
        },
    )
    if "premium_discount_pct" in vehicles.columns:
        rich = vehicles[pd.to_numeric(vehicles["premium_discount_pct"], errors="coerce") > 1.0]
        if not rich.empty:
            note(
                "<b>Trading above NAV.</b> "
                + ", ".join(f"{r.symbol} +{r.premium_discount_pct:.2f}%" for r in rich.itertuples())
                + ". Buying at a premium hands back part of the signal's edge on day one.",
                tone="amber",
            )
    if "vehicle" in vehicles.columns and (vehicles["vehicle"] == "index_fund").any():
        note(
            "<b>An index fund is often the better vehicle for a monthly rebalance.</b> It "
            "transacts at NAV with no spread and no premium, so none of the signal's edge is "
            "lost on entry — at the cost of same-day execution and intraday pricing."
        )
    st.caption(
        "Turnover, price, NAV and premium are a point-in-time NSE snapshot taken when the pipeline "
        "last ran, not a history. AUM, expense ratio and tracking error are not published on any "
        "endpoint this project reads, so they stay blank rather than invented — check the AMC "
        "factsheet before you trade."
    )

    symbols = [s for s in selected["symbol"].dropna().tolist() if s in etf_prices.columns]
    if symbols:
        section("Fund performance", "Rebased to ₹100 over the window every fund shares")
        figure, window = etf_comparison(etf_prices, symbols)
        if window:
            st.caption(
                f"{window}. Comparing funds over their own full histories would make the "
                "longest-listed one look strongest purely because it started earlier."
            )
        st.plotly_chart(figure, width="stretch", config=CHART_CONFIG)

        for symbol in symbols:
            with st.expander(f"Drawdown and raw series · {symbol}", expanded=False):
                st.plotly_chart(
                    drawdown_chart(etf_prices[symbol]), width="stretch",
                    config=CHART_CONFIG, key=f"dd_{symbol}",
                )
                st.plotly_chart(
                    price_chart(etf_prices[symbol], symbol), width="stretch",
                    config=CHART_CONFIG, key=f"px_{symbol}",
                )
    missing = [s for s in selected["symbol"].dropna().tolist() if s not in etf_prices.columns]
    if missing:
        st.caption(f"No price history ingested for: {', '.join(missing)}.")
