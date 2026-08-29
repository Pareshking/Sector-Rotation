from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from components.metrics import data_health_banner, load_metadata

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "processed"

st.set_page_config(page_title="India Sector Rotation", page_icon="📊", layout="wide")


def _mtime(name: str) -> int:
    path = DATA_DIR / name
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


@st.cache_data(show_spinner=False)
def _read(name: str, modified_ns: int = 0) -> pd.DataFrame:
    del modified_ns
    path = DATA_DIR / name
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def load_summary() -> pd.DataFrame:
    return _read("summary_rankings.parquet", _mtime("summary_rankings.parquet"))


def load_rs() -> pd.DataFrame:
    return _read("rs_matrix.parquet", _mtime("rs_matrix.parquet"))


def load_etfs() -> pd.DataFrame:
    return _read("etf_universe.parquet", _mtime("etf_universe.parquet"))


def load_etf_prices() -> pd.DataFrame:
    return _read("etf_prices.parquet", _mtime("etf_prices.parquet"))


def main() -> None:
    st.title("India Sector Rotation")
    st.caption("Exposure-first quantitative view of Indian sectors and themes")
    data_health_banner(load_metadata())
    summary = load_summary()
    if summary.empty:
        st.warning("Prepared data is not available yet. Run `python -m pipeline.run_pipeline --mode fixture` locally or trigger the GitHub data pipeline.")
        st.stop()
    st.markdown("Use the pages in the sidebar to inspect sectors, themes, rankings and ETF implementations.")
    st.dataframe(summary.sort_values("rank").head(10), use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
