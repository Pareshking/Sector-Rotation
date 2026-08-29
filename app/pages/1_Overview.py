from __future__ import annotations

import streamlit as st

from app.components.charts import ranking_bar, rrg_quadrant
from app.components.metrics import data_health_banner, load_metadata, metric_row
from app.streamlit_app import load_summary

st.title("Overview")
data_health_banner(load_metadata())
summary = load_summary()
if summary.empty:
    st.warning("No prepared dataset found. Run the data pipeline first.")
    st.stop()
metric_row(summary)
st.subheader("RRG-style rotation map")
st.plotly_chart(rrg_quadrant(summary), use_container_width=True)
st.subheader("Cross-sectional momentum")
st.plotly_chart(ranking_bar(summary), use_container_width=True)
st.dataframe(summary.sort_values("rank"), use_container_width=True, hide_index=True)
