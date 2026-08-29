from __future__ import annotations

import streamlit as st


def inject_theme() -> None:
    """Compact institutional UI inspired by the Umiya design language."""
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600&display=swap');
        :root { --ink:#111827; --muted:#64748b; --line:#e5e7eb; --soft:#f8fafc; --accent:#4f46e5; --good:#059669; --bad:#dc2626; }
        html, body, [class*="css"] { font-family:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif !important; color:var(--ink); }
        .stApp { background:#fff; }
        [data-testid="stHeader"] { background:rgba(255,255,255,.92); }
        [data-testid="stMainBlockContainer"] { max-width:1400px; padding-top:1.2rem; padding-bottom:3rem; }
        h1,h2,h3 { letter-spacing:-.035em !important; color:#0f172a !important; }
        h1 { font-size:2.35rem !important; margin-bottom:.15rem !important; }
        h2 { font-size:1.35rem !important; margin-top:1.5rem !important; }
        h3 { font-size:1.05rem !important; }
        [data-testid="stMetric"] { background:var(--soft); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }
        [data-testid="stMetricLabel"] { color:var(--muted); font-size:.78rem; font-weight:600; text-transform:uppercase; letter-spacing:.04em; }
        [data-testid="stMetricValue"] { color:#0f172a; font-family:"JetBrains Mono",monospace !important; font-size:1.55rem !important; }
        [data-testid="stDataFrame"] { border:1px solid var(--line); border-radius:12px; overflow:hidden; }
        [data-testid="stSidebar"] { border-right:1px solid var(--line); }
        [data-testid="stSidebarNav"] { padding-top:1rem; }
        .sr-kicker { color:var(--accent); font-size:.72rem; font-weight:700; letter-spacing:.12em; text-transform:uppercase; margin-bottom:.25rem; }
        .sr-subtitle { color:var(--muted); font-size:.95rem; margin-bottom:1rem; }
        .sr-section { display:flex; align-items:center; gap:10px; margin:1.5rem 0 .65rem; font-weight:700; font-size:.95rem; }
        .sr-section:after { content:""; height:1px; flex:1; background:var(--line); }
        .sr-source { display:inline-flex; align-items:center; gap:6px; padding:4px 9px; border-radius:999px; background:#eef2ff; color:#3730a3; font-size:.72rem; font-weight:600; }
        @media (max-width:640px) { [data-testid="stMainBlockContainer"] { padding-left:.65rem; padding-right:.65rem; } h1 { font-size:1.8rem !important; } }
        </style>
        """,
        unsafe_allow_html=True,
    )


def page_header(kicker: str, title: str, subtitle: str = "") -> None:
    st.markdown(f'<div class="sr-kicker">{kicker}</div><h1>{title}</h1>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="sr-subtitle">{subtitle}</div>', unsafe_allow_html=True)


def section(title: str) -> None:
    st.markdown(f'<div class="sr-section">{title}</div>', unsafe_allow_html=True)
