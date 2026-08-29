from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components.metrics import decision_frame
from app.components.theme import inject_theme, page_header, render_decision_cards, render_rank_list, section
from app.data import load_summary

inject_theme()
page_header(
    "Exposure Universe",
    "Themes",
    "Thematic rotation with the same hard decision boundary: authoritative history first, signal second, rank third.",
)
summary = load_summary()
frame = summary[summary.category == "thematic"].sort_values("rank") if not summary.empty else summary
if frame.empty:
    st.info("No thematic observations are available.")
    st.stop()

frame = decision_frame(frame)
actionable = frame[frame.decision_eligible].sort_values("rank")
buy = actionable[actionable.model_action == "BUY"]
sell = actionable[actionable.model_action == "REDUCE / EXIT"]
watch = actionable[actionable.model_action.isin(["WATCH / IMPROVING", "WATCH"])]

section("BUY")
render_decision_cards(buy, limit=20, empty_text="No theme currently satisfies the complete BUY rule.")

section("REDUCE / EXIT")
render_decision_cards(sell, limit=20, empty_text="No theme currently satisfies the REDUCE / EXIT rule.")

section("WATCH")
render_decision_cards(watch, limit=20, empty_text="No decision-grade theme is currently on WATCH.")

section("Theme ranking")
render_rank_list(actionable, limit=40)

with st.expander("Unavailable theme histories", expanded=False):
    unavailable = frame[~frame.decision_eligible]
    if unavailable.empty:
        st.info("No theme histories are currently excluded.")
    else:
        for r in unavailable.itertuples():
            st.write(f"• {r.exposure} — {getattr(r, 'decision_reason', 'Authoritative history unavailable.')}")
