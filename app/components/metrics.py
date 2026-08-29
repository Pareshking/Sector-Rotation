from __future__ import annotations

import pandas as pd
import streamlit as st


def metric_row(summary: pd.DataFrame) -> None:
    total = len(summary)
    leading = int((summary.get("stage", pd.Series(dtype=str)) == "Leading").sum())
    improving = int((summary.get("stage", pd.Series(dtype=str)) == "Improving").sum())
    st.metric("Exposures", total)
    cols = st.columns(3)
    cols[0].metric("Leading", leading)
    cols[1].metric("Improving", improving)
    cols[2].metric("Top Rank", summary.iloc[0]["exposure"] if not summary.empty else "—")
