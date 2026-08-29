from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.charts import ranking_bar, rrg_quadrant
from app.components.metrics import data_health_banner, decision_frame, get_metadata, metric_row
from app.components.theme import inject_theme, page_header, section
from app.data import load_summary

inject_theme()
page_header(
    "Quantitative Research Terminal",
    "India Sector Rotation",
    "A decision-first view of relative strength, momentum and ETF implementation. Start here for the current model signal.",
)
metadata = get_metadata()
data_health_banner(metadata)
summary = load_summary()
if summary.empty:
    st.warning("Prepared data is not available yet. Run the data pipeline first.")
    st.stop()

metric_row(summary)
decisions = decision_frame(summary).sort_values("rank")

section("What the model is saying")
buy = decisions[decisions["model_action"] == "BUY CANDIDATE"].sort_values("rank").head(5)
reduce = decisions[decisions["model_action"] == "REDUCE / EXIT"].sort_values("rank").head(5)
proxy = decisions[decisions["model_action"] == "PROXY ONLY"].sort_values("rank").head(3)

left, right = st.columns(2)
with left:
    if buy.empty:
        st.markdown('<div class="sr-card"><div class="sr-card-label">Buy candidates</div><div class="sr-card-value">None</div><div class="sr-card-note">No exposure currently satisfies all model entry conditions.</div></div>', unsafe_allow_html=True)
    else:
        rows = "".join(
            f'<div style="display:flex;justify-content:space-between;gap:8px;padding:8px 0;border-bottom:1px solid #eef2f7;"><strong>{r.exposure}</strong><span class="sr-chip sr-chip-buy">BUY CANDIDATE</span></div>'
            for r in buy.itertuples()
        )
        st.markdown(f'<div class="sr-card"><div class="sr-card-label">Buy candidates</div>{rows}<div class="sr-small" style="margin-top:8px;">Rule: Leading + RS ratio &gt; 1 + positive RS velocity + positive momentum.</div></div>', unsafe_allow_html=True)
with right:
    if reduce.empty:
        st.markdown('<div class="sr-card"><div class="sr-card-label">Reduce / exit</div><div class="sr-card-value">None</div><div class="sr-card-note">No decision-grade exposure currently satisfies the exit conditions.</div></div>', unsafe_allow_html=True)
    else:
        rows = "".join(
            f'<div style="display:flex;justify-content:space-between;gap:8px;padding:8px 0;border-bottom:1px solid #eef2f7;"><strong>{r.exposure}</strong><span class="sr-chip sr-chip-sell">REDUCE / EXIT</span></div>'
            for r in reduce.itertuples()
        )
        st.markdown(f'<div class="sr-card"><div class="sr-card-label">Reduce / exit</div>{rows}<div class="sr-small" style="margin-top:8px;">Rule: Weakening/Lagging + RS ratio &lt; 1 + negative RS velocity.</div></div>', unsafe_allow_html=True)

if not proxy.empty:
    st.markdown(
        f'<div class="sr-callout" style="margin-top:10px;"><strong>Data-quality boundary:</strong> {len(decisions[decisions["model_action"] == "PROXY ONLY"])} exposures currently use benchmark-proxy histories. They remain visible for coverage, but the app will not call them buy/sell candidates.</div>',
        unsafe_allow_html=True,
    )

section("Market rotation")
left, right = st.columns([1.15, 1])
with left:
    st.plotly_chart(rrg_quadrant(decisions), width="stretch", config={"displaylogo": False, "responsive": True})
with right:
    st.plotly_chart(ranking_bar(decisions[decisions["decision_eligible"]].head(12)), width="stretch", config={"displaylogo": False, "responsive": True})

section("Current leaderboard")
compact_cols = [c for c in ["rank", "exposure", "model_action", "stage", "momentum_z", "rs_ratio", "rs_momentum", "return_1M", "return_3M"] if c in decisions]
st.dataframe(decisions[compact_cols].head(15), width="stretch", hide_index=True)

with st.expander("Detailed model inputs", expanded=False):
    detail_cols = [c for c in [
        "rank", "exposure", "exposure_id", "category", "stage", "model_action",
        "decision_reason", "momentum_z", "rs_ratio", "rs_momentum",
        "return_1M", "return_3M", "return_6M", "return_12M", "data_source",
    ] if c in decisions]
    st.dataframe(decisions[detail_cols], width="stretch", hide_index=True)

st.caption("Decision labels are deterministic outputs of the current quantitative model; they are not discretionary investment advice. Verify the underlying ETF implementation before placing an order.")
