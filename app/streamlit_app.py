from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "processed"

st.set_page_config(page_title="India Sector Rotation", page_icon="📊", layout="wide")


def load_summary() -> pd.DataFrame:
    path = DATA_DIR / "summary_rankings.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def load_rs() -> pd.DataFrame:
    path = DATA_DIR / "rs_matrix.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def load_etfs() -> pd.DataFrame:
    path = DATA_DIR / "etf_universe.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def main() -> None:
    st.title("India Sector Rotation")
    st.caption("Exposure-first quantitative view of Indian sectors and themes")
    summary = load_summary()
    if summary.empty:
        st.warning("Prepared data is not available yet. Run `python -m pipeline.run_pipeline --mode fixture` locally or trigger the GitHub data pipeline.")
        st.stop()
    st.markdown("Use the pages in the sidebar to inspect sectors, themes, rankings and ETF implementations.")
    top = summary.sort_values("rank").head(10)
    st.dataframe(top, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
