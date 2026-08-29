from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import drawdown_chart, price_chart, rs_trajectory
from app.components.theme import inject_theme, page_header, section
from app.data import load_etf_prices, load_etfs, load_rs, load_summary

inject_theme()
page_header("Implementation", "ETF Detail", "Inspect implementation vehicle, NAV / Close history and relative strength")
etfs = load_etfs()
summary = load_summary()
rs = load_rs()
etf_prices = load_etf_prices()
if etfs.empty:
    st.info("No ETF metadata is available in the prepared dataset.")
    st.stop()
exposure_options = etfs["exposure"].drop_duplicates().tolist()
exposure = st.selectbox("Exposure", exposure_options)
selected = etfs[etfs["exposure"] == exposure]
section("Implementation")
st.dataframe(selected, width="stretch", hide_index=True)
row = summary[summary["exposure"] == exposure]
if not row.empty:
    section("Exposure signal")
    st.dataframe(row, width="stretch", hide_index=True)
    exposure_id = row.iloc[0]["exposure_id"]
    if exposure_id in rs.columns:
        section("Mansfield relative strength")
        st.plotly_chart(rs_trajectory(rs, exposure_id), width="stretch")

for symbol in selected["symbol"].dropna().tolist():
    if symbol in etf_prices.columns:
        section(f"{symbol} · historical NAV / Close")
        c1, c2 = st.columns(2)
        with c1:
            st.plotly_chart(price_chart(etf_prices[symbol], symbol), width="stretch")
        with c2:
            st.plotly_chart(drawdown_chart(etf_prices[symbol]), width="stretch")
