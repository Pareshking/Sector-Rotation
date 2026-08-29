from __future__ import annotations

import streamlit as st

from app.components.charts import ranking_bar, rrg_quadrant
from app.components.metrics import data_health_banner, get_metadata, metric_row
from app.components.theme import inject_theme, page_header, section
from app.data import load_etf_prices, load_etfs, load_rs, load_summary

st.set_page_config(page_title="India Sector Rotation", page_icon="📊", layout="wide", initial_sidebar_state="expanded")
inject_theme()

# Re-export prepared-data loaders for backwards compatibility with notebooks/tests.
__all__ = ["load_summary", "load_rs", "load_etfs", "load_etf_prices"]


def main() -> None:
    metadata = get_metadata()
    summary = load_summary()
    page_header(
        "Quantitative Research Terminal",
        "India Sector Rotation",
        "Exposure-first view of relative strength, momentum and implementation.",
    )
    data_health_banner(metadata)
    if summary.empty:
        st.warning("Prepared data is not available yet. Run the data pipeline first.")
        st.stop()

    metric_row(summary)

    section("Market rotation")
    left, right = st.columns([1.15, 1])
    with left:
        st.plotly_chart(rrg_quadrant(summary), width="stretch")
    with right:
        st.plotly_chart(ranking_bar(summary.head(12)), width="stretch")

    section("Current leaderboard")
    display_cols = [c for c in [
        "rank", "exposure", "category", "stage", "momentum_z",
        "return_1M", "return_3M", "return_6M", "return_12M", "data_source",
    ] if c in summary.columns]
    st.dataframe(summary.sort_values("rank")[display_cols].head(20), width="stretch", hide_index=True)

    section("Research navigation")
    st.caption("Use the sidebar to move from the overview into sector/theme heatmaps, rankings, ETF implementation and system lineage.")


if __name__ == "__main__":
    main()
