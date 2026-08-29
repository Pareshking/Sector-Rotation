from __future__ import annotations

import streamlit as st


def inject_theme() -> None:
    """Mobile-first research-terminal design system.

    No remote font or asset imports: the UI remains self-contained and the
    application never needs a browser-side network dependency for styling.
    """
    st.markdown(
        """
        <style>
        :root {
            --sr-ink:#0f172a;
            --sr-muted:#64748b;
            --sr-line:#e2e8f0;
            --sr-soft:#f8fafc;
            --sr-accent:#4f46e5;
            --sr-good:#047857;
            --sr-bad:#be123c;
            --sr-warn:#b45309;
        }
        html, body, [class*="css"] {
            font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont,
                         "Segoe UI", sans-serif !important;
            color:var(--sr-ink);
            -webkit-font-smoothing:antialiased;
        }
        .stApp { background:#fff; }
        [data-testid="stHeader"] { background:rgba(255,255,255,.96); }
        [data-testid="stMainBlockContainer"] {
            max-width:1440px;
            padding-top:.7rem;
            padding-bottom:3rem;
        }
        h1,h2,h3,h4 {
            color:var(--sr-ink) !important;
            letter-spacing:-.035em !important;
        }
        h1 { font-size:2.15rem !important; line-height:1.08 !important; margin-bottom:.15rem !important; }
        h2 { font-size:1.25rem !important; margin-top:1.25rem !important; }
        h3 { font-size:1rem !important; }
        [data-testid="stMetric"] {
            background:var(--sr-soft);
            border:1px solid var(--sr-line);
            border-radius:14px;
            padding:12px 14px;
            min-height:94px;
        }
        [data-testid="stMetricLabel"] {
            color:var(--sr-muted);
            font-size:.72rem;
            font-weight:700;
            text-transform:uppercase;
            letter-spacing:.07em;
        }
        [data-testid="stMetricValue"] {
            color:var(--sr-ink);
            font-variant-numeric:tabular-nums;
            letter-spacing:-.02em;
        }
        [data-testid="stDataFrame"] {
            border:1px solid var(--sr-line);
            border-radius:12px;
            overflow:hidden;
        }
        .sr-kicker {
            color:var(--sr-accent);
            font-size:.68rem;
            font-weight:800;
            letter-spacing:.14em;
            text-transform:uppercase;
            margin-bottom:.3rem;
        }
        .sr-subtitle {
            color:var(--sr-muted);
            font-size:.94rem;
            line-height:1.55;
            margin-bottom:1rem;
            max-width:850px;
        }
        .sr-section {
            display:flex;
            align-items:center;
            gap:10px;
            margin:1.35rem 0 .7rem;
            font-weight:800;
            font-size:.94rem;
            letter-spacing:-.01em;
        }
        .sr-section:after { content:""; height:1px; flex:1; background:var(--sr-line); }
        .sr-card {
            border:1px solid var(--sr-line);
            border-radius:14px;
            background:#fff;
            padding:14px 15px;
            box-shadow:0 1px 2px rgba(15,23,42,.03);
        }
        .sr-card-label {
            color:var(--sr-muted);
            font-size:.67rem;
            font-weight:800;
            letter-spacing:.08em;
            text-transform:uppercase;
        }
        .sr-card-value { font-size:1.35rem; font-weight:800; margin-top:3px; }
        .sr-card-note { color:var(--sr-muted); font-size:.76rem; margin-top:4px; line-height:1.35; }
        .sr-chip {
            display:inline-block;
            padding:4px 8px;
            border-radius:999px;
            font-size:.68rem;
            font-weight:800;
            letter-spacing:.03em;
        }
        .sr-chip-buy { background:#ecfdf5; color:var(--sr-good); }
        .sr-chip-sell { background:#fff1f2; color:var(--sr-bad); }
        .sr-chip-watch { background:#fffbeb; color:var(--sr-warn); }
        .sr-chip-proxy { background:#f1f5f9; color:#475569; }
        .sr-callout {
            border:1px solid #fde68a;
            background:#fffbeb;
            color:#78350f;
            border-radius:12px;
            padding:10px 12px;
            font-size:.78rem;
            line-height:1.45;
        }
        .sr-callout-good {
            border-color:#a7f3d0;
            background:#ecfdf5;
            color:#065f46;
        }
        .sr-callout-bad {
            border-color:#fecdd3;
            background:#fff1f2;
            color:#881337;
        }
        .sr-small { color:var(--sr-muted); font-size:.74rem; line-height:1.45; }
        @media (max-width:640px) {
            [data-testid="stMainBlockContainer"] {
                padding-left:.55rem;
                padding-right:.55rem;
                padding-top:.35rem;
            }
            h1 { font-size:1.72rem !important; }
            h2 { font-size:1.12rem !important; }
            .sr-subtitle { font-size:.86rem; }
            [data-testid="stMetric"] { min-height:78px; padding:9px 10px; }
            [data-testid="stMetricValue"] { font-size:1.25rem !important; }
            [data-testid="stMetricLabel"] { font-size:.64rem; }
            .sr-section { margin-top:1rem; }
            .sr-card { padding:11px 12px; }
        }
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
