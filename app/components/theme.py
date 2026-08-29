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
        .sr-chip{display:inline-block;padding:4px 8px;border-radius:999px;font-size:.64rem;font-weight:800;letter-spacing:.025em;white-space:nowrap}.sr-chip-buy{background:#ecfdf5;color:var(--good)}.sr-chip-sell{background:#fff1f2;color:var(--bad)}.sr-chip-watch{background:#fffbeb;color:var(--warn)}.sr-chip-proxy{background:#f1f5f9;color:#475569}
        .sr-callout{border:1px solid #fde68a;background:#fffbeb;color:#78350f;border-radius:12px;padding:10px 12px;font-size:.76rem;line-height:1.45}.sr-callout-good{border-color:#a7f3d0;background:#ecfdf5;color:#065f46}.sr-callout-bad{border-color:#fecdd3;background:#fff1f2;color:#881337}.sr-small{color:var(--muted);font-size:.72rem;line-height:1.45}
        .sr-decision{border:1px solid var(--line);border-radius:14px;padding:12px;background:#fff;margin-bottom:8px}.sr-decision-head{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px}.sr-name{font-weight:800;font-size:.9rem}.sr-meta{color:var(--muted);font-size:.68rem}.sr-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.sr-stat{background:var(--soft);border-radius:9px;padding:7px 8px}.sr-stat-label{color:var(--muted);font-size:.58rem;text-transform:uppercase;letter-spacing:.06em;font-weight:800}.sr-stat-value{font-size:.78rem;font-weight:750;margin-top:2px;font-variant-numeric:tabular-nums}.sr-empty{border:1px dashed var(--line);border-radius:14px;padding:18px 14px;color:var(--muted);text-align:center;font-size:.78rem}
        .sr-table-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:12px}.sr-table{width:100%;border-collapse:collapse;font-size:.73rem;min-width:720px}.sr-table th{text-align:left;color:var(--muted);background:var(--soft);font-size:.62rem;text-transform:uppercase;letter-spacing:.05em;padding:8px}.sr-table td{padding:8px;border-top:1px solid #eef2f7;font-variant-numeric:tabular-nums}
        [data-testid="stMetric"]{background:var(--soft);border:1px solid var(--line);border-radius:14px;padding:10px 12px;min-height:84px}[data-testid="stMetricLabel"]{color:var(--muted);font-size:.66rem;font-weight:700;text-transform:uppercase;letter-spacing:.06em}[data-testid="stMetricValue"]{color:var(--ink);font-variant-numeric:tabular-nums}
        @media(max-width:640px){[data-testid="stMainBlockContainer"]{padding-left:.5rem;padding-right:.5rem;padding-top:.25rem}h1{font-size:1.62rem!important}h2{font-size:1.06rem!important}.sr-subtitle{font-size:.84rem}.sr-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.sr-card{padding:11px 12px}[data-testid="stMetric"]{min-height:72px;padding:8px 9px}[data-testid="stMetricValue"]{font-size:1.18rem!important}}
        </style>
        """, unsafe_allow_html=True)


def page_header(kicker: str, title: str, subtitle: str = "") -> None:
    st.markdown(f'<div class="sr-kicker">{html.escape(kicker)}</div><h1>{html.escape(title)}</h1>', unsafe_allow_html=True)
    if subtitle: st.markdown(f'<div class="sr-subtitle">{html.escape(subtitle)}</div>', unsafe_allow_html=True)


def section(title: str) -> None:
    st.markdown(f'<div class="sr-section">{html.escape(title)}</div>', unsafe_allow_html=True)


def fmt_pct(value: object, digits: int = 1) -> str:
    try:
        value=float(value)
        return "—" if pd.isna(value) else f"{value*100:.{digits}f}%"
    except (TypeError,ValueError): return "—"


def fmt_num(value: object, digits: int = 2) -> str:
    try:
        value=float(value)
        return "—" if pd.isna(value) else f"{value:.{digits}f}"
    except (TypeError,ValueError): return "—"


def action_chip(action: str) -> str:
    action=str(action or "WATCH")
    cls="sr-chip-buy" if action=="BUY CANDIDATE" else "sr-chip-sell" if action=="REDUCE / EXIT" else "sr-chip-proxy" if "PROXY" in action else "sr-chip-watch"
    return f'<span class="sr-chip {cls}">{html.escape(action)}</span>'


def render_decision_cards(frame: pd.DataFrame, limit: int = 6, empty_text: str = "No qualifying exposures.") -> None:
    if frame.empty:
        st.markdown(f'<div class="sr-empty">{html.escape(empty_text)}</div>', unsafe_allow_html=True); return
    out=[]
    for r in frame.head(limit).itertuples():
        out.append(f'''<div class="sr-decision"><div class="sr-decision-head"><div><div class="sr-name">{html.escape(str(r.exposure))}</div><div class="sr-meta">Rank {int(r.rank)} · {html.escape(str(getattr(r,"category","")))} · {html.escape(str(getattr(r,"stage","")))}</div></div>{action_chip(getattr(r,"model_action","WATCH"))}</div><div class="sr-grid"><div class="sr-stat"><div class="sr-stat-label">Momentum Z</div><div class="sr-stat-value">{fmt_num(getattr(r,"momentum_z",None))}</div></div><div class="sr-stat"><div class="sr-stat-label">RS Ratio</div><div class="sr-stat-value">{fmt_num(getattr(r,"rs_ratio",None))}</div></div><div class="sr-stat"><div class="sr-stat-label">RS Velocity</div><div class="sr-stat-value">{fmt_num(getattr(r,"rs_momentum",None))}</div></div><div class="sr-stat"><div class="sr-stat-label">1M / 3M</div><div class="sr-stat-value">{fmt_pct(getattr(r,"return_1M",None))} · {fmt_pct(getattr(r,"return_3M",None))}</div></div></div><div class="sr-small" style="margin-top:7px">{html.escape(str(getattr(r,"decision_reason","")))}</div></div>''')
    st.markdown("".join(out), unsafe_allow_html=True)


def render_compact_table(frame: pd.DataFrame, columns: Iterable[tuple[str,str]], limit: int = 15) -> None:
    rows=[]
    for r in frame.head(limit).itertuples():
        cells=[]
        for key,label in columns:
            value=getattr(r,key,None)
            text=fmt_pct(value) if key.startswith("return_") else fmt_num(value) if key in {"momentum_z","rs_ratio","rs_momentum"} else str(value) if value is not None else "—"
            cells.append(f"<td>{html.escape(text)}</td>")
        rows.append("<tr>"+"".join(cells)+"</tr>")
    headers="".join(f"<th>{html.escape(label)}</th>" for _,label in columns)
    st.markdown(f'<div class="sr-table-wrap"><table class="sr-table"><thead><tr>{headers}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>', unsafe_allow_html=True)
