from __future__ import annotations

import sys
from pathlib import Path
import streamlit as st

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from app.components.charts import ranking_bar
from app.components.metrics import decision_frame
from app.components.theme import inject_theme,page_header,render_compact_table,render_decision_cards,section
from app.data import load_summary

inject_theme(); page_header("Quantitative Ranking","Rankings","Cross-sectional momentum across 1M, 3M, 6M and 12M horizons. Returns are shown as percentages; proxy-only histories are excluded by default.")
summary=load_summary()
if summary.empty: st.info("No prepared ranking dataset is available."); st.stop()
category=st.segmented_control("Universe",["All","sector","thematic"],default="All")
frame=summary if category=="All" else summary[summary.category==category]
frame=decision_frame(frame).sort_values("rank")
only=st.toggle("Decision-grade only",value=True,help="Hide benchmark-proxy histories from actionable ranking.")
if only: frame=frame[frame.decision_eligible]

section("Action board")
render_decision_cards(frame[frame.model_action=="BUY CANDIDATE"],limit=5,empty_text="No BUY CANDIDATE currently.")
render_decision_cards(frame[frame.model_action=="REDUCE / EXIT"],limit=5,empty_text="No REDUCE / EXIT currently.")

section("Momentum ranking")
st.plotly_chart(ranking_bar(frame,limit=min(15,len(frame))),width="stretch",config={"displaylogo":False,"responsive":True})
section("Rank table")
render_compact_table(frame,[
    ("rank","Rank"),("exposure","Exposure"),("model_action","Action"),("stage","Stage"),
    ("momentum_z","Momentum Z"),("rs_ratio","RS Ratio"),("rs_momentum","RS Vel."),
    ("return_1M","1M"),("return_3M","3M"),("return_6M","6M"),("return_12M","12M")],limit=20)
with st.expander("Raw ranking data",expanded=False): st.dataframe(frame,width="stretch",hide_index=True)
