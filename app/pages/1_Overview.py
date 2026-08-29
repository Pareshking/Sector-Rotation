from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))

from app.components.charts import ranking_bar, rrg_quadrant
from app.components.metrics import data_health_banner, decision_frame, get_metadata, metric_row
from app.components.theme import inject_theme, page_header, render_compact_table, render_decision_cards, section
from app.data import load_summary

inject_theme()
page_header("Quantitative Research Terminal","India Sector Rotation","Decision-first sector and theme rotation. Only decision-grade histories can become BUY or REDUCE/EXIT candidates.")
metadata=get_metadata(); data_health_banner(metadata)
summary=load_summary()
if summary.empty:
    st.warning("Prepared data is not available yet. Run the data pipeline first."); st.stop()

metric_row(summary)
decisions=decision_frame(summary).sort_values("rank")
buy=decisions[decisions.model_action=="BUY CANDIDATE"].sort_values("rank")
sell=decisions[decisions.model_action=="REDUCE / EXIT"].sort_values("rank")
watch=decisions[decisions.model_action.isin(["WATCH / IMPROVING","WATCH"]) & decisions.decision_eligible].sort_values("rank")
proxy=decisions[decisions.model_action=="PROXY ONLY"].sort_values("rank")

section("Decision board")
left,right=st.columns(2)
with left:
    st.markdown('<div class="sr-card"><div class="sr-card-label">BUY CANDIDATES</div><div class="sr-card-note">All four conditions must pass: Leading + RS ratio &gt; 1 + positive 13W RS velocity + positive momentum Z.</div></div>',unsafe_allow_html=True)
    render_decision_cards(buy,limit=5,empty_text="No exposure currently meets every buy condition.")
with right:
    st.markdown('<div class="sr-card"><div class="sr-card-label">REDUCE / EXIT</div><div class="sr-card-note">Weakening/Lagging + RS ratio &lt; 1 + negative 13W RS velocity. This is a model exit flag, not an order instruction.</div></div>',unsafe_allow_html=True)
    render_decision_cards(sell,limit=5,empty_text="No exposure currently meets the model exit conditions.")

section("Watchlist")
render_decision_cards(watch,limit=6,empty_text="No decision-grade watchlist entries.")

if not proxy.empty:
    st.markdown(f'<div class="sr-callout" style="margin-top:10px"><strong>Coverage-only data:</strong> {len(proxy)} exposures use benchmark-proxy histories. They are intentionally excluded from BUY/SELL decisions. Their returns and RS values should not be interpreted as authoritative sector-index performance.</div>',unsafe_allow_html=True)

section("Market rotation · decision-grade only")
left,right=st.columns([1.15,1])
with left: st.plotly_chart(rrg_quadrant(decisions),width="stretch",config={"displaylogo":False,"responsive":True})
with right: st.plotly_chart(ranking_bar(decisions[decisions.decision_eligible].head(12)),width="stretch",config={"displaylogo":False,"responsive":True})

section("Current leaderboard")
render_compact_table(decisions[decisions.decision_eligible],[
    ("rank","Rank"),("exposure","Exposure"),("model_action","Action"),("stage","Stage"),
    ("momentum_z","Momentum Z"),("rs_ratio","RS Ratio"),("rs_momentum","RS Vel."),
    ("return_1M","1M"),("return_3M","3M")],limit=15)

with st.expander("Raw prepared data · advanced",expanded=False):
    st.dataframe(decisions, width="stretch", hide_index=True)

st.caption("The dashboard separates coverage from decision quality. Verify the underlying ETF, liquidity and implementation before placing an order.")
