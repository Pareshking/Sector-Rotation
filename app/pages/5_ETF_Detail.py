from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import drawdown_chart, performance_chart, price_chart, rs_trajectory
from app.components.metrics import decision_frame
from app.components.theme import fmt_pct, fmt_num, inject_theme, page_header, render_compact_table, section
from app.data import load_etf_prices, load_etfs, load_rs, load_summary

inject_theme()
page_header(
    "Implementation",
    "ETF Detail",
    "Start with the model decision, understand why it was reached, then validate the implementation vehicle.",
)
etfs = load_etfs()
summary = load_summary()
rs = load_rs()
etf_prices = load_etf_prices()
if etfs.empty:
    st.info("No ETF metadata is available in the prepared dataset.")
    st.stop()

exposure_options = etfs["exposure"].drop_duplicates().tolist()
exposure = st.selectbox("Exposure", exposure_options)
selected = etfs[etfs.exposure == exposure].copy()
decisions = decision_frame(summary)
row = decisions[decisions.exposure == exposure]

section("Decision")
if row.empty:
    st.info("No prepared model row is available for this exposure.")
else:
    signal = row.iloc[0]
    action = str(signal.get("model_action", "WATCH"))
    source = str(signal.get("data_source", "unknown"))
    if action == "DATA UNAVAILABLE":
        st.warning("This exposure is outside the decision set because an authoritative history is unavailable. No synthetic benchmark proxy is used.")
    st.markdown(f"### {action}")
    st.write(signal.get("analysis_note", signal.get("decision_reason", "")))
    st.caption(f"Data source: {source}")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Rank", int(signal.get("rank")) if signal.get("rank") == signal.get("rank") else "—")
    c2.metric("Momentum Z", fmt_num(signal.get("momentum_z")))
    c3.metric("RS Ratio", fmt_num(signal.get("rs_ratio")))
    c4.metric("RS Velocity", fmt_num(signal.get("rs_momentum")))

    section("Model returns")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("1M", fmt_pct(signal.get("return_1M")))
    r2.metric("3M", fmt_pct(signal.get("return_3M")))
    r3.metric("6M", fmt_pct(signal.get("return_6M")))
    r4.metric("12M", fmt_pct(signal.get("return_12M")))

section("Implementation vehicle")
if selected.empty:
    st.info("No mapped ETF/fund is currently available for this exposure.")
else:
    cols = [c for c in ["symbol", "name", "yfinance_symbol", "aum_crore", "expense_ratio", "liquidity_score", "tracking_error"] if c in selected]
    render_compact_table(selected, [(c, c.replace("_", " ").title()) for c in cols], limit=10)

if not row.empty:
    exposure_id = row.iloc[0].get("exposure_id")
    if exposure_id in rs.columns:
        section("Mansfield relative strength · 52-week baseline")
        st.plotly_chart(rs_trajectory(rs, exposure_id), width="stretch", config={"displaylogo": False, "responsive": True})

for symbol in selected["symbol"].dropna().tolist():
    if symbol not in etf_prices.columns:
        continue
    series = etf_prices[symbol]
    section(f"{symbol} · normalized performance")
    st.caption("Primary performance is rebased to ₹100 so splits and unit changes do not appear as fake returns. Raw NAV/Close is retained only for auditability.")
    st.plotly_chart(performance_chart(series, symbol), width="stretch", config={"displaylogo": False, "responsive": True})
    st.plotly_chart(drawdown_chart(series), width="stretch", config={"displaylogo": False, "responsive": True})
    with st.expander(f"Raw validated NAV / Close · {symbol}", expanded=False):
        st.plotly_chart(price_chart(series, symbol), width="stretch", config={"displaylogo": False, "responsive": True})
