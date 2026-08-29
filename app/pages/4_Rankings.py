from __future__ import annotations

import streamlit as st
from app.streamlit_app import load_summary
from app.components.charts import ranking_bar

st.title("Rankings")
summary = load_summary()
if summary.empty:
    st.info("No prepared ranking dataset is available.")
    st.stop()
category = st.selectbox("Universe", ["All", "sector", "thematic"])
frame = summary if category == "All" else summary[summary["category"] == category]
st.plotly_chart(ranking_bar(frame), use_container_width=True)
st.dataframe(frame.sort_values("rank"), use_container_width=True, hide_index=True)
