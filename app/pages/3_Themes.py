from __future__ import annotations

import streamlit as st
from app.streamlit_app import load_summary
from app.components.charts import rs_heatmap

st.title("Themes")
summary = load_summary()
frame = summary[summary["category"] == "thematic"].sort_values("rank") if not summary.empty else summary
if frame.empty:
    st.info("No thematic observations are available.")
    st.stop()
st.plotly_chart(rs_heatmap(frame), use_container_width=True)
st.dataframe(frame, use_container_width=True, hide_index=True)
