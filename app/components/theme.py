from __future__ import annotations

import html
from typing import Iterable

import pandas as pd
import streamlit as st


def inject_theme() -> None:
    st.markdown(
        """
        <style>
        :root{--ink:#0f172a;--muted:#64748b;--line:#e2e8f0;--soft:#f8fafc;--accent:#4f46e5;--good:#047857;--bad:#be123c;--warn:#b45309}
        html,body,[class*="css"]{font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif!important;color:var(--ink);-webkit-font-smoothing:antialiased}
        .stApp{background:#fff}[data-testid="stHeader"]{background:rgba(255,255,255,.96)}
        [data-testid="stMainBlockContainer"]{max-width:1440px;padding-top:.5rem;padding-bottom:3rem}
        h1,h2,h3,h4{color:var(--ink)!important;letter-spacing:-.035em!important}h1{font-size:2.05rem!important;line-height:1.08!important;margin-bottom:.15rem!important}h2{font-size:1.18rem!important;margin-top:1.15rem!important}
        .sr-kicker{color:var(--accent);font-size:.66rem;font-weight:800;letter-spacing:.14em;text-transform:uppercase;margin-bottom:.28rem}.sr-subtitle{color:var(--muted);font-size:.92rem;line-height:1.5;margin-bottom:1rem;max-width:900px}
        .sr-section{display:flex;align-items:center;gap:10px;margin:1.25rem 0 .68rem;font-weight:800;font-size:.92rem}.sr-section:after{content:"";height:1px;flex:1;background:var(--line)}
        .sr-card{border:1px solid var(--line);border-radius:14px;background:#fff;padding:13px 14px;box-shadow:0 1px 2px rgba(15,23,42,.03)}.sr-card-label{color:var(--muted);font-size:.65rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase}.sr-card-value{font-size:1.28rem;font-weight:800;margin-top:3px}.sr-card-note{color:var(--muted);font-size:.75rem;margin-top:4px;line-height:1.4}
        .sr-callout{border:1px solid #fde68a;background:#fffbeb;color:#78350f;border-radius:12px;padding:10px 12px;font-size:.76rem;line-height:1.45}.sr-callout-good{border-color:#a7f3d0;background:#ecfdf5;color:#065f46}.sr-callout-bad{border-color:#fecdd3;background:#fff1f2;color:#881337}.sr-small{color:var(--muted);font-size:.72rem;line-height:1.45}
        [data-testid="stMetric"]{background:var(--soft);border:1px solid var(--line);border-radius:14px;padding:10px 12px;min-height:84px}[data-testid="stMetricLabel"]{color:var(--muted);font-size:.66rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em}[data-testid="stMetricValue"]{color:var(--ink);font-variant-numeric:tabular-nums}
        @media(max-width:640px){[data-testid="stMainBlockContainer"]{padding-left:.5rem;padding-right:.5rem;padding-top:.25rem}h1{font-size:1.62rem!important}h2{font-size:1.06rem!important}.sr-subtitle{font-size:.84rem}.sr-card{padding:11px 12px}[data-testid="stMetric"]{min-height:72px;padding:8px 9px}[data-testid="stMetricValue"]{font-size:1.18rem!important}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def page_header(kicker: str, title: str, subtitle: str = "") -> None:
    st.markdown(f'<div class="sr-kicker">{html.escape(kicker)}</div><h1>{html.escape(title)}</h1>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="sr-subtitle">{html.escape(subtitle)}</div>', unsafe_allow_html=True)


def section(title: str) -> None:
    st.markdown(f'<div class="sr-section">{html.escape(title)}</div>', unsafe_allow_html=True)


def fmt_pct(value: object, digits: int = 1) -> str:
    try:
        value = float(value)
        return "—" if pd.isna(value) else f"{value * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def fmt_num(value: object, digits: int = 2) -> str:
    try:
        value = float(value)
        return "—" if pd.isna(value) else f"{value:.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _action_text(action: str) -> str:
    action = str(action or "WATCH")
    if action == "BUY":
        return "BUY"
    if action == "REDUCE / EXIT":
        return "REDUCE / EXIT"
    if action == "DATA UNAVAILABLE":
        return "DATA UNAVAILABLE"
    return action


def render_decision_cards(frame: pd.DataFrame, limit: int = 20, empty_text: str = "No qualifying exposures.") -> None:
    if frame.empty:
        st.info(empty_text)
        return
    for r in frame.head(limit).itertuples():
        with st.container(border=True):
            head_left, head_right = st.columns([3.2, 1])
            with head_left:
                st.markdown(f"**{html.escape(str(r.exposure))}**")
                st.caption(f"Rank {int(r.rank)} · {html.escape(str(getattr(r, 'stage', '')))}")
            with head_right:
                st.markdown(f"**{_action_text(getattr(r, 'model_action', 'WATCH'))}**")
            values = st.columns(4)
            values[0].metric("Momentum Z", fmt_num(getattr(r, "momentum_z", None)))
            values[1].metric("RS Ratio", fmt_num(getattr(r, "rs_ratio", None)))
            values[2].metric("RS Velocity", fmt_num(getattr(r, "rs_momentum", None)))
            values[3].metric("1M / 3M", f"{fmt_pct(getattr(r, 'return_1M', None))} / {fmt_pct(getattr(r, 'return_3M', None))}")
            st.caption(f"Why: {getattr(r, 'analysis_note', getattr(r, 'decision_reason', ''))}")


def render_rank_list(frame: pd.DataFrame, limit: int = 20) -> None:
    if frame.empty:
        st.info("No decision-grade ranking data is available.")
        return
    header = st.columns([0.45, 2.2, 1.25, 1.15, 0.9, 0.9])
    for col, text in zip(header, ["#", "Exposure", "Action", "Stage", "1M", "3M"]):
        col.caption(text)
    st.divider()
    for r in frame.head(limit).itertuples():
        cols = st.columns([0.45, 2.2, 1.25, 1.15, 0.9, 0.9])
        cols[0].write(int(r.rank))
        cols[1].write(str(r.exposure))
        cols[2].write(_action_text(getattr(r, "model_action", "WATCH")))
        cols[3].write(str(getattr(r, "stage", "—")))
        cols[4].write(fmt_pct(getattr(r, "return_1M", None)))
        cols[5].write(fmt_pct(getattr(r, "return_3M", None)))
        st.divider()


def render_compact_table(frame: pd.DataFrame, columns: Iterable[tuple[str, str]], limit: int = 15) -> None:
    """Audit-only table. Main decision pages should use render_rank_list instead."""
    if frame.empty:
        st.info("No data available.")
        return
    display = frame.head(limit).copy()
    for key, _ in columns:
        if key.startswith("return_") and key in display:
            display[key] = display[key].map(fmt_pct)
        elif key in {"momentum_z", "rs_ratio", "rs_momentum"} and key in display:
            display[key] = display[key].map(fmt_num)
    st.dataframe(display[[key for key, _ in columns if key in display.columns]], width="stretch", hide_index=True)
