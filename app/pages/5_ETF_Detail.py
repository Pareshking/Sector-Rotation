from __future__ import annotations

import streamlit as st

from app.streamlit_app import load_etf_prices, load_etfs, load_rs, load_summary
from app.components.charts import drawdown_chart, price_chart, rs_trajectory

st.title("ETF Detail")
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
st.dataframe(selected, use_container_width=True, hide_index=True)
row = summary[summary["exposure"] == exposure]
if not row.empty:
    st.subheader("Exposure signal")
    st.dataframe(row, use_container_width=True, hide_index=True)
    exposure_id = row.iloc[0]["exposure_id"]
    if exposure_id in rs.columns:
        st.plotly_chart(rs_trajectory(rs, exposure_id), use_container_width=True)

for symbol in selected["symbol"].tolist():
    if symbol in etf_prices.columns:
        st.subheader(f"{symbol} — historical NAV / Close")
        st.plotly_chart(price_chart(etf_prices[symbol], symbol), use_container_width=True)
        st.plotly_chart(drawdown_chart(etf_prices[symbol]), use_container_width=True)
