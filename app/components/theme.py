"""Design system: tokens, typography, and dense HTML primitives.

Data-dense views are rendered as semantic HTML/CSS grid rather than as
``st.columns`` + ``st.metric`` stacks. Streamlit collapses every column into a
full-width block below ~640px, which turned a 43-row ranking into a 25,000px
mobile scroll. A CSS grid keeps a row a row on a phone, and emits one DOM write
instead of several hundred widgets.
"""

from __future__ import annotations

import html
from typing import Iterable, Sequence

import pandas as pd
import streamlit as st

# Standard RRG quadrant convention: green leads, amber tops out, red lags,
# blue turns up. Shared by the CSS badges and the Plotly traces so a colour
# means the same thing in a chart and in a table.
STAGE_COLORS = {
    "Leading": "#059669",
    "Weakening": "#D97706",
    "Lagging": "#E11D48",
    "Improving": "#2563EB",
    "Insufficient Data": "#94A3B8",
}

ACTION_CLASS = {
    "BUY": "buy",
    "REDUCE / EXIT": "red",
    "WATCH / IMPROVING": "blue",
    "WATCH": "slate",
    "DATA UNAVAILABLE": "grey",
}

_CSS = """
<style>
:root{
--ink:#0B1220;--ink2:#1E293B;--muted:#64748B;--faint:#94A3B8;
--line:#E5E9F0;--line2:#CBD5E1;--bg:#FFFFFF;--bg2:#F8FAFC;--bg3:#F1F5F9;
--brand:#4338CA;--brand-bg:#EEF2FF;
--buy:#047857;--buy-bg:#ECFDF5;--buy-line:#A7F3D0;
--red:#BE123C;--red-bg:#FFF1F2;--red-line:#FECDD3;
--amber:#B45309;--amber-bg:#FFFBEB;--amber-line:#FDE68A;
--blue:#1D4ED8;--blue-bg:#EFF6FF;--blue-line:#BFDBFE;
--slate:#475569;--slate-bg:#F1F5F9;--slate-line:#E2E8F0;
--r:12px;--shadow:0 1px 2px rgba(11,18,32,.04),0 1px 3px rgba(11,18,32,.03);
--mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace;
}
html,body,[class*="css"]{font-family:Inter,ui-sans-serif,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif!important;color:var(--ink);-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
.stApp{background:var(--bg)}
[data-testid="stMainBlockContainer"]{max-width:1400px;padding-top:.35rem;padding-bottom:3.5rem}
[data-testid="stHeader"]{background:rgba(255,255,255,.9);backdrop-filter:saturate(180%) blur(8px)}
h1,h2,h3,h4{color:var(--ink)!important;letter-spacing:-.028em!important;font-weight:750!important}
h1{font-size:1.86rem!important;line-height:1.06!important;margin:0 0 .1rem!important;letter-spacing:-.036em!important}
.block-container p{font-size:.875rem}

/* ---------- page header ---------- */
.sr-kicker{color:var(--brand);font-size:.66rem;font-weight:800;letter-spacing:.15em;text-transform:uppercase;margin:.15rem 0 .3rem}
.sr-sub{color:var(--muted);font-size:.855rem;line-height:1.55;margin:.35rem 0 .2rem;max-width:74ch}
.sr-section{display:flex;align-items:baseline;gap:10px;margin:1.5rem 0 .55rem}
.sr-section-t{font-weight:800;font-size:.735rem;letter-spacing:.09em;text-transform:uppercase;color:var(--ink2);white-space:nowrap}
.sr-section-n{font-size:.735rem;color:var(--faint);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sr-section:after{content:"";height:1px;flex:1;background:var(--line);min-width:12px}

/* ---------- pills & dots ---------- */
.pill{display:inline-flex;align-items:center;gap:5px;padding:2px 8px;border-radius:999px;font-size:.645rem;font-weight:800;letter-spacing:.05em;text-transform:uppercase;white-space:nowrap;border:1px solid}
.pill-buy{color:var(--buy);background:var(--buy-bg);border-color:var(--buy-line)}
.pill-red{color:var(--red);background:var(--red-bg);border-color:var(--red-line)}
.pill-blue{color:var(--blue);background:var(--blue-bg);border-color:var(--blue-line)}
.pill-amber{color:var(--amber);background:var(--amber-bg);border-color:var(--amber-line)}
.pill-slate{color:var(--slate);background:var(--slate-bg);border-color:var(--slate-line)}
.pill-grey{color:var(--faint);background:var(--bg3);border-color:var(--line)}
.dot{width:7px;height:7px;border-radius:50%;display:inline-block;flex:none}

/* ---------- KPI strip: 4-up desktop, 2-up phone, never 1-up ---------- */
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:.15rem 0 .2rem}
.kpi{border:1px solid var(--line);border-radius:var(--r);background:var(--bg2);padding:11px 13px;box-shadow:var(--shadow)}
.kpi-l{color:var(--muted);font-size:.635rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;line-height:1.2}
.kpi-v{font-size:1.5rem;font-weight:800;letter-spacing:-.03em;font-variant-numeric:tabular-nums;line-height:1.15;margin-top:4px}
.kpi-n{color:var(--muted);font-size:.7rem;margin-top:3px;line-height:1.35}
.kpi-buy{background:var(--buy-bg);border-color:var(--buy-line)}.kpi-buy .kpi-v{color:var(--buy)}
.kpi-red{background:var(--red-bg);border-color:var(--red-line)}.kpi-red .kpi-v{color:var(--red)}
.kpi-blue{background:var(--blue-bg);border-color:var(--blue-line)}.kpi-blue .kpi-v{color:var(--blue)}
.kpi-amber{background:var(--amber-bg);border-color:var(--amber-line)}.kpi-amber .kpi-v{color:var(--amber)}

/* ---------- health strip ---------- */
.hs{display:flex;flex-wrap:wrap;align-items:center;gap:8px 14px;border:1px solid var(--line);border-left:3px solid var(--buy);
border-radius:10px;background:var(--bg2);padding:9px 13px;margin:.5rem 0 .1rem;font-size:.75rem;color:var(--ink2)}
.hs-warn{border-left-color:var(--amber);background:var(--amber-bg);border-color:var(--amber-line)}
.hs b{font-variant-numeric:tabular-nums}
.hs-sep{color:var(--line2)}
.hs-time{margin-left:auto;color:var(--muted);font-size:.72rem;white-space:nowrap}

/* ---------- signal rows: one exposure per row, never collapses ---------- */
.rt{border:1px solid var(--line);border-radius:var(--r);overflow:hidden;background:var(--bg);box-shadow:var(--shadow)}
.rt-nm{font-weight:650;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;line-height:1.25;font-size:.815rem}
.rt-cat{color:var(--faint);font-size:.635rem;letter-spacing:.04em;text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rt-pos{color:var(--buy)}.rt-neg{color:var(--red)}.rt-zero{color:var(--faint)}
.sig{display:grid;align-items:center;column-gap:10px;row-gap:5px;padding:9px 12px;border-top:1px solid var(--line);
grid-template-columns:24px 1fr auto;grid-template-areas:"rank name act" "meta meta meta"}
.sig:first-child{border-top:none}
.sig:hover{background:var(--bg2)}
.sig-rank{grid-area:rank;color:var(--faint);font-size:.7rem;font-weight:700;font-variant-numeric:tabular-nums}
.sig-name{grid-area:name;min-width:0;display:flex;flex-direction:column;gap:1px}
.sig-act{grid-area:act;justify-self:end}
.sig-meta{grid-area:meta;display:flex;flex-wrap:wrap;align-items:center;gap:4px 12px;font-size:.72rem;color:var(--muted)}
.sig-meta b{color:var(--ink2);font-variant-numeric:tabular-nums;font-weight:650}
.sig-meta .zwrap{width:104px;flex:none}
@media(min-width:900px){
.sig{grid-template-columns:28px minmax(150px,1fr) 112px minmax(320px,1.35fr);
grid-template-areas:"rank name act meta";row-gap:0;min-height:44px}
.sig-meta{justify-content:flex-end;flex-wrap:nowrap}
}
/* momentum bar: zero-centred so sign is readable without parsing the number */
.zwrap{display:flex;align-items:center;gap:7px}
.ztrack{position:relative;flex:1;height:6px;border-radius:3px;background:var(--bg3);overflow:hidden}
.ztrack:before{content:"";position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--line2)}
.zfill{position:absolute;top:0;bottom:0;border-radius:3px}
.znum{font-variant-numeric:tabular-nums;font-size:.72rem;font-weight:650;width:38px;text-align:right;flex:none}

/* ---------- action board ---------- */
.board{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px;align-items:start}
.bcol{border:1px solid var(--line);border-radius:var(--r);background:var(--bg);overflow:hidden;box-shadow:var(--shadow)}
.bhead{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:9px 12px;border-bottom:1px solid var(--line);
font-size:.68rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase}
.bhead-buy{background:var(--buy-bg);color:var(--buy);border-bottom-color:var(--buy-line)}
.bhead-red{background:var(--red-bg);color:var(--red);border-bottom-color:var(--red-line)}
.bhead-blue{background:var(--blue-bg);color:var(--blue);border-bottom-color:var(--blue-line)}
.bhead-amber{background:var(--amber-bg);color:var(--amber);border-bottom-color:var(--amber-line)}
.bcount{font-variant-numeric:tabular-nums;font-size:.8rem;font-weight:800}
.bitem{display:grid;grid-template-columns:1fr auto;align-items:center;column-gap:8px;row-gap:2px;padding:8px 12px;border-top:1px solid var(--line)}
.bitem:first-of-type{border-top:none}
.bitem:hover{background:var(--bg2)}
.bnm{font-size:.815rem;font-weight:650;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.bmet{grid-column:1/-1;display:flex;flex-wrap:wrap;gap:3px 9px;font-size:.685rem;color:var(--muted)}
.bmet b{color:var(--ink2);font-variant-numeric:tabular-nums;font-weight:650}
.bz{font-variant-numeric:tabular-nums;font-size:.78rem;font-weight:750}
.bempty{padding:14px 12px;color:var(--faint);font-size:.76rem}

/* ---------- hero decision card + legend ---------- */
.hero{border:1px solid var(--line);border-left:4px solid var(--slate);border-radius:var(--r);
background:var(--bg2);padding:14px 16px;box-shadow:var(--shadow)}
.hero-buy{border-left-color:var(--buy);background:var(--buy-bg);border-color:var(--buy-line)}
.hero-red{border-left-color:var(--red);background:var(--red-bg);border-color:var(--red-line)}
.hero-blue{border-left-color:var(--blue);background:var(--blue-bg);border-color:var(--blue-line)}
.hero-grey{border-left-color:var(--faint)}
.hero-top{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.hero-act{font-size:1.35rem;font-weight:800;letter-spacing:-.02em}
.hero-buy .hero-act{color:var(--buy)}.hero-red .hero-act{color:var(--red)}.hero-blue .hero-act{color:var(--blue)}
.hero-why{margin-top:7px;font-size:.815rem;line-height:1.55;color:var(--ink2)}
.hero-src{margin-top:6px;font-size:.685rem;color:var(--muted);letter-spacing:.03em;text-transform:uppercase}
.legend{display:flex!important;flex-wrap:wrap;gap:5px 18px;font-size:.72rem;color:var(--muted);margin:.2rem 0 .5rem}
.legend span{display:inline-flex!important;align-items:center;gap:6px;white-space:nowrap}

/* ---------- notes / callouts ---------- */
.note{border:1px solid var(--line);background:var(--bg2);border-radius:10px;padding:10px 12px;font-size:.765rem;line-height:1.5;color:var(--ink2)}
.note-amber{border-color:var(--amber-line);background:var(--amber-bg);color:#78350F}
.note-buy{border-color:var(--buy-line);background:var(--buy-bg);color:#065F46}
.note-red{border-color:var(--red-line);background:var(--red-bg);color:#881337}
.note b{font-weight:750}
.rule{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:10px}
.small{color:var(--muted);font-size:.72rem;line-height:1.5}

/* ---------- streamlit widget polish ---------- */
[data-testid="stMetric"]{background:var(--bg2);border:1px solid var(--line);border-radius:var(--r);padding:10px 12px}
[data-testid="stMetricValue"]{font-variant-numeric:tabular-nums;letter-spacing:-.02em}
[data-testid="stMetricLabel"]{color:var(--muted);font-size:.64rem;font-weight:800;text-transform:uppercase;letter-spacing:.07em}
[data-testid="stDataFrame"]{border-radius:10px}
.stPlotlyChart{border:1px solid var(--line);border-radius:var(--r);padding:6px 4px 2px;background:var(--bg);box-shadow:var(--shadow)}
[data-testid="stExpander"] details{border:1px solid var(--line)!important;border-radius:10px!important;background:var(--bg2)}
[data-testid="stExpander"] summary{font-size:.775rem!important;font-weight:650}
div[data-baseweb="select"]>div{border-radius:9px;border-color:var(--line2)}

@media(max-width:760px){
[data-testid="stMainBlockContainer"]{padding-left:.6rem;padding-right:.6rem;padding-top:.15rem}
h1{font-size:1.44rem!important}
.sr-sub{font-size:.8rem}
.kpis{grid-template-columns:1fr 1fr;gap:8px}
.kpi{padding:9px 11px}.kpi-v{font-size:1.24rem}
.hs{font-size:.72rem;gap:6px 10px}.hs-time{margin-left:0;width:100%}
.board{grid-template-columns:1fr}
}
</style>
"""


def inject_theme() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# formatting
# --------------------------------------------------------------------------- #
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


def fmt_signed(value: object, digits: int = 2) -> str:
    try:
        value = float(value)
        return "—" if pd.isna(value) else f"{value:+.{digits}f}"
    except (TypeError, ValueError):
        return "—"


def _sign_class(value: object) -> str:
    try:
        value = float(value)
        if pd.isna(value):
            return "rt-zero"
        return "rt-pos" if value > 0 else ("rt-neg" if value < 0 else "rt-zero")
    except (TypeError, ValueError):
        return "rt-zero"


def _esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""))


# --------------------------------------------------------------------------- #
# layout primitives
# --------------------------------------------------------------------------- #
def page_header(kicker: str, title: str, subtitle: str = "") -> None:
    parts = [f'<div class="sr-kicker">{_esc(kicker)}</div><h1>{_esc(title)}</h1>']
    if subtitle:
        parts.append(f'<div class="sr-sub">{_esc(subtitle)}</div>')
    st.markdown("".join(parts), unsafe_allow_html=True)


def section(title: str, note: str = "") -> None:
    note_html = f'<div class="sr-section-n">{_esc(note)}</div>' if note else ""
    st.markdown(
        f'<div class="sr-section"><div class="sr-section-t">{_esc(title)}</div>{note_html}</div>',
        unsafe_allow_html=True,
    )


def note(text_html: str, tone: str = "") -> None:
    cls = f"note note-{tone}" if tone else "note"
    st.markdown(f'<div class="{cls}">{text_html}</div>', unsafe_allow_html=True)


def kpi_strip(items: Sequence[tuple[str, object, str, str]]) -> None:
    """items: (label, value, note, tone) where tone is ''|'buy'|'red'|'blue'|'amber'."""
    cards = []
    for label, value, sub, tone in items:
        cls = f"kpi kpi-{tone}" if tone else "kpi"
        sub_html = f'<div class="kpi-n">{_esc(sub)}</div>' if sub else ""
        cards.append(
            f'<div class="{cls}"><div class="kpi-l">{_esc(label)}</div>'
            f'<div class="kpi-v">{_esc(value)}</div>{sub_html}</div>'
        )
    st.markdown(f'<div class="kpis">{"".join(cards)}</div>', unsafe_allow_html=True)


def action_pill(action: str) -> str:
    action = str(action or "WATCH")
    return f'<span class="pill pill-{ACTION_CLASS.get(action, "slate")}">{_esc(action)}</span>'


def stage_cell(stage: str) -> str:
    colour = STAGE_COLORS.get(str(stage), "#94A3B8")
    return f'<span class="dot" style="background:{colour}"></span>{_esc(stage)}'


def _zbar(value: object, scale: float) -> str:
    try:
        z = float(value)
    except (TypeError, ValueError):
        z = float("nan")
    if pd.isna(z) or scale <= 0:
        return '<div class="zwrap"><div class="ztrack"></div><span class="znum rt-zero">—</span></div>'
    width = min(abs(z) / scale, 1.0) * 50.0
    left = 50.0 if z >= 0 else 50.0 - width
    colour = "var(--buy)" if z >= 0 else "var(--red)"
    cls = "rt-pos" if z >= 0 else "rt-neg"
    return (
        f'<div class="zwrap"><div class="ztrack">'
        f'<i class="zfill" style="left:{left:.1f}%;width:{width:.1f}%;background:{colour}"></i>'
        f'</div><span class="znum {cls}">{z:+.2f}</span></div>'
    )


def sparkline(values: Iterable[float], width: int = 52, height: int = 16) -> str:
    """Inline SVG trend of the recent relative-strength path."""
    series = [float(v) for v in values if v == v]
    if len(series) < 4:
        return '<span class="rt-zero" style="font-size:.7rem">—</span>'
    lo, hi = min(series), max(series)
    span = (hi - lo) or 1.0
    step = width / (len(series) - 1)
    points = " ".join(
        f"{i * step:.1f},{height - 1 - (v - lo) / span * (height - 2):.1f}"
        for i, v in enumerate(series)
    )
    colour = "#059669" if series[-1] >= series[0] else "#E11D48"
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="none" aria-hidden="true">'
        f'<polyline points="{points}" fill="none" stroke="{colour}" stroke-width="1.4" '
        f'stroke-linejoin="round" stroke-linecap="round"/></svg>'
    )


def stage_legend() -> None:
    items = "".join(
        f'<span><i class="dot" style="background:{colour}"></i>{_esc(stage)}</span>'
        for stage, colour in STAGE_COLORS.items()
        if stage != "Insufficient Data"
    )
    st.markdown(f'<div class="legend">{items}</div>', unsafe_allow_html=True)
