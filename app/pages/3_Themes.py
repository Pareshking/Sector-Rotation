from __future__ import annotations

import sys
from pathlib import Path
import streamlit as st

ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from app.components.charts import rs_heatmap
from app.components.metrics import decision_frame
from app.components.theme import inject_theme,page_header,render_compact_table,render_decision_cards,section
from app.data import load_summary

inject_theme(); page_header("Exposure Universe","Themes","Thematic rotation with a hard boundary between decision-grade histories and benchmark-proxy coverage.")
summary=load_summary(); frame=summary[summary.category=="thematic"].sort_values("rank") if not summary.empty else summary
if frame.empty: st.info("No thematic observations are available."); st.stop()
frame=decision_frame(frame); proxy=frame[frame.model_action=="PROXY ONLY"]; actionable=frame[frame.decision_eligible]
if not proxy.empty: st.markdown(f'<div class="sr-callout">{len(proxy)} thematic histories are benchmark proxies. They remain visible for coverage but cannot become BUY/SELL candidates.</div>',unsafe_allow_html=True)

section("Theme momentum · decision-grade")
st.plotly_chart(rs_heatmap(actionable,limit=len(actionable)),width="stretch",config={"displaylogo":False,"responsive":True})
section("Theme action board")
render_decision_cards(actionable[actionable.model_action=="BUY CANDIDATE"],limit=6,empty_text="No thematic BUY CANDIDATE.")
render_decision_cards(actionable[actionable.model_action=="REDUCE / EXIT"],limit=6,empty_text="No thematic REDUCE / EXIT.")
section("Theme leaderboard")
render_compact_table(actionable,[
    ("rank","Rank"),("exposure","Theme"),("model_action","Action"),("stage","Stage"),
    ("momentum_z","Momentum Z"),("rs_ratio","RS Ratio"),("rs_momentum","RS Vel."),
    ("return_1M","1M"),("return_3M","3M")],limit=25)
with st.expander("Coverage-only theme histories",expanded=False):
    render_compact_table(proxy,[("exposure","Theme"),("stage","Stage"),("data_source","Source"),("return_1M","1M"),("return_3M","3M")],limit=40)
