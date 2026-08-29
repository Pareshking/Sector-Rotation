from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import drawdown_chart, performance_chart, price_chart, rs_trajectory
from app.components.metrics import decision_frame
from app.components.theme import inject_theme, page_header, section
from app.data import load_etf_prices, load_etfs, load_rs, load_summary

inject_theme()
page_header("Implementation", "ETF Detail", "Find the implementation vehicle behind a signal, then validate its price history and drawdown.")
etfs = load_etfs()
summary = load_summary()
rs = load_rs()
etf_prices = load_etf_prices()
if etfs.empty:
    st.info("No ETF metadata is available in the prepared dataset.")
    st.stop()

exposure_options = etfs["exposure"].drop_duplicates().tolist()
exposure = st.selectbox("Exposure", exposure_options)
selected = etfs[etfs["exposure"] == exposure].copy()
decisions = decision_frame(summary)
row = decisions[decisions["exposure"] == exposure]

section("Decision context")
if not row.empty:
    signal = row.iloc[0]
    action = str(signal.get("model_action", "WATCH"))
    chip = "sr-chip-buy" if "BUY" in action else "sr-chip-sell" if "EXIT" in action else "sr-chip-proxy" if "PROXY" in action else "sr-chip-watch"
    st.markdown(
        f'<div class="sr-card"><div class="sr-card-label">Model action</div><div class="sr-card-value">{action}</div><div class="sr-card-note">{signal.get("decision_reason", "")}</div></div>',
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns(3)
    c1.metric("Momentum Z", f"{float(signal.get('momentum_z', 0)):.2f}")
    c2.metric("RS Ratio", f"{float(signal.get('rs_ratio', 0)):.2f}")
    c3.metric("RS Velocity", f"{float(signal.get('rs_momentum', 0)):.2f}")

section("Implementation vehicle")
st.dataframe(selected, width="stretch", hide_index=True)

if not row.empty:
    exposure_id = row.iloc[0].get("exposure_id")
    if exposure_id in rs.columns:
        section("Mansfield relative strength · 52 weeks")
        st.plotly_chart(rs_trajectory(rs, exposure_id), width="stretch", config={"displaylogo": False, "responsive": True})

for symbol in selected["symbol"].dropna().tolist():
    if symbol not in etf_prices.columns:
        continue
    series = etf_prices[symbol]
    section(f"{symbol} · validated price history")
    st.markdown('<div class="sr-small">The first chart is the validated NAV/Close series. A second chart rebases the series to ₹100 so splits or unit changes cannot masquerade as investment losses.</div>', unsafe_allow_html=True)
    st.plotly_chart(price_chart(series, symbol), width="stretch", config={"displaylogo": False, "responsive": True})
    st.plotly_chart(performance_chart(series, symbol), width="stretch", config={"displaylogo": False, "responsive": True})
    st.plotly_chart(drawdown_chart(series), width="stretch", config={"displaylogo": False, "responsive": True})
