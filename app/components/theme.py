"""Design system: colour tokens for both themes, typography, and HTML primitives.

Everything visual lives here. Pages compose these primitives and never write
their own CSS, so a colour, a chip or a card means the same thing on every page.

Dense summaries (KPI cards, allocation cards, chips) are semantic HTML on a CSS
grid rather than ``st.columns`` stacks: Streamlit collapses every column into a
full-width block on a phone, while a grid with ``auto-fit`` keeps two cards to
a row and emits one DOM write instead of dozens of widgets. Long tables stay
``st.dataframe``, which already sorts, scrolls and keeps its header sticky.

Colours are one light token set, "Clear Ledger" (the Paresh app's design); the
native widgets follow the same values in ``.streamlit/config.toml``.
"""

from __future__ import annotations

import html
from contextlib import contextmanager
from typing import Iterable, Iterator, Sequence

import pandas as pd
import streamlit as st

# --------------------------------------------------------------------------- #
# tokens
# --------------------------------------------------------------------------- #
# Semantic roles, not hues: "pos" is outperformance / risk-on (emerald), "neg"
# is drawdown / risk-off (crimson), "accent" is the active selection (indigo),
# "info" is neutral information (sky), "warn" asks for attention (amber).
# "Clear Ledger", the light design of the Paresh app, and the only theme: a
# white, quiet page where colour is kept for what it means (owner, 12 Oct 2026).
# "bg" is the page, "surface" a card on it.
LIGHT = {
    "bg": "#F6F7F9", "surface": "#FFFFFF", "surface2": "#F4F5F8",
    "line": "#E3E6EB", "line2": "#D0D5DD",
    "text": "#0E1726", "text2": "#3C4657", "muted": "#5E6878", "faint": "#98A1AE",
    "pos": "#067647", "pos_bg": "#E8F5EE", "pos_line": "#B7E0C8",
    "neg": "#B42318", "neg_bg": "#FDEDEB", "neg_line": "#F5C2BC",
    "warn": "#B54708", "warn_bg": "#FEF6EA", "warn_line": "#F7D7A8",
    "accent": "#4F46E5", "accent_bg": "#EEF0FF", "accent_line": "#C9CCFB",
    "info": "#0369A1", "info_bg": "#EFF7FC", "info_line": "#BFDDF0",
    "shadow": "0 1px 2px rgba(14,23,38,.04)",
    "header_bg": "rgba(255,255,255,.92)",
}

TONES = ("pos", "neg", "warn", "accent", "info")

# Target-portfolio actions (src/portfolio/construct.py) mapped to a tone.
ACTION_TONE = {
    "BUY": "pos",
    "HOLD": "accent",
    "TRIM": "warn",
    "SELL": "neg",
    "NOT HELD": "",
    "DATA UNAVAILABLE": "",
    "CASH": "info",
}
# Kept for callers that still use the earlier name.
ACTION_CLASS = ACTION_TONE

# RRG quadrants, display context only. The same hue in the chart and the chip.
STAGE_TONE = {"Leading": "pos", "Weakening": "warn", "Lagging": "neg", "Improving": "info"}


def palette() -> dict[str, str]:
    """The token set, for charts and inline colours. Light only."""
    return LIGHT


def stage_colors() -> dict[str, str]:
    tokens = palette()
    colours = {stage: tokens[tone] for stage, tone in STAGE_TONE.items()}
    colours["Insufficient Data"] = tokens["faint"]
    return colours


# The light values, for code that needs a colour outside a page render.
STAGE_COLORS = {stage: LIGHT[tone] for stage, tone in STAGE_TONE.items()} | {"Insufficient Data": LIGHT["faint"]}


def _vars(tokens: dict[str, str]) -> str:
    return ";".join(f"--{key.replace('_', '-')}:{value}" for key, value in tokens.items())


_CSS = """
:root{%(vars)s;--r:12px;--r-sm:8px;--nav-h:3.75rem}
.stApp{background:var(--bg);font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}
.stApp,.stApp p,.stApp li{color:var(--text)}
/* --- clean defaults: no decoration bar, no dead space above the first line --- */
[data-testid="stDecoration"]{display:none}
[data-testid="stHeader"]{background:var(--header-bg);backdrop-filter:saturate(180%%) blur(10px);border-bottom:1px solid var(--line)}
/* Full width of layout="wide", as the Paresh app does; a fixed cap left wide screens two empty bands. */
[data-testid="stMainBlockContainer"]{max-width:100%%;padding:calc(var(--nav-h) + .75rem) 1.5rem 4rem}
h1,h2,h3,h4{letter-spacing:-.025em;color:var(--text)}
h1{font-size:1.9rem!important;line-height:1.08!important;margin:0!important;padding:0!important}
.stMarkdown p,.stMarkdown li{font-size:.9rem;line-height:1.62}
.stMarkdown code{font-size:.82em;border-radius:6px}
hr{border-color:var(--line)!important}

/* --- page header --- */
.ds-kicker{color:var(--accent);font-size:.68rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;margin:.2rem 0 .35rem}
.ds-sub{color:var(--muted);font-size:.9rem;line-height:1.55;margin:.45rem 0 .25rem;max-width:78ch}
.ds-section{display:flex;align-items:baseline;gap:12px;margin:1.9rem 0 .7rem}
.ds-section-t{font-weight:700;font-size:.76rem;letter-spacing:.09em;text-transform:uppercase;color:var(--text2);white-space:nowrap}
.ds-section-n{font-size:.78rem;color:var(--faint);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ds-section:after{content:"";height:1px;flex:1;min-width:16px;background:var(--line)}

/* --- global status header: sticky below Streamlit's nav --- */
[data-testid="stElementContainer"]:has(.ds-header){position:sticky;top:var(--nav-h);z-index:90}
.ds-header{display:flex;flex-wrap:wrap;align-items:center;gap:8px 18px;padding:9px 14px;margin:-.25rem 0 .4rem;
border:1px solid var(--line);border-radius:var(--r);background:var(--header-bg);backdrop-filter:saturate(180%%) blur(10px);box-shadow:var(--shadow)}
.ds-brand{font-weight:750;font-size:.95rem;letter-spacing:-.02em;white-space:nowrap}
.ds-stat{display:flex;flex-direction:column;gap:1px;min-width:0}
.ds-stat-l{font-size:.6rem;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--faint)}
.ds-stat-v{font-size:.82rem;font-weight:650;color:var(--text);white-space:nowrap}
.ds-header .ds-sep{width:1px;align-self:stretch;background:var(--line)}
.ds-fresh{margin-left:auto;display:flex;align-items:center;gap:7px;font-size:.76rem;color:var(--muted);white-space:nowrap}
.ds-pulse{width:8px;height:8px;border-radius:50%%;background:var(--pos);box-shadow:0 0 0 3px var(--pos-bg)}
.ds-pulse.stale{background:var(--warn);box-shadow:0 0 0 3px var(--warn-bg)}

/* --- chips: regime, trade actions, stages --- */
.ds-chip{display:inline-flex;align-items:center;gap:6px;padding:3px 9px;border-radius:999px;border:1px solid var(--line);
background:var(--surface2);color:var(--text2);font-size:.66rem;font-weight:750;letter-spacing:.07em;text-transform:uppercase;white-space:nowrap;line-height:1.35}
.ds-chip-lg{font-size:.74rem;padding:4px 11px}
.ds-chip i{width:7px;height:7px;border-radius:50%%;background:currentColor;display:inline-block}
%(tone_rules)s

/* --- KPI cards --- */
.ds-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:10px;margin:.2rem 0 .3rem}
.ds-kpi{border:1px solid var(--line);border-radius:var(--r);background:var(--surface);padding:12px 14px;box-shadow:var(--shadow);min-width:0}
.ds-kpi-l{color:var(--muted);font-size:.64rem;font-weight:700;letter-spacing:.09em;text-transform:uppercase;line-height:1.25}
.ds-kpi-v{font-size:1.55rem;font-weight:750;letter-spacing:-.03em;line-height:1.15;margin-top:5px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ds-kpi-n{color:var(--muted);font-size:.74rem;margin-top:4px;line-height:1.4}

/* --- readings: one bordered row of centred figures; only the value carries colour --- */
.ds-reads{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));border:1px solid var(--line);border-radius:var(--r);
background:var(--surface);box-shadow:var(--shadow);overflow:hidden;margin:.4rem 0 .9rem}
.ds-read{padding:16px 12px;text-align:center;border-right:1px solid var(--line);min-width:0}
.ds-read:last-child{border-right:0}
.ds-read-l{font-size:.78rem;color:var(--muted);font-weight:600}
.ds-read-v{font-size:1.6rem;font-weight:750;letter-spacing:-.03em;line-height:1.2;margin-top:4px;white-space:nowrap;color:var(--text)}
.ds-read-v.up{color:var(--pos)}.ds-read-v.down{color:var(--neg)}.ds-read-v.warn{color:var(--warn)}
.ds-read-n{font-size:.74rem;color:var(--muted);margin-top:3px}
.ds-cardhead{display:flex;justify-content:space-between;align-items:baseline;gap:12px;margin:0 0 4px}
.ds-cardhead b{font-size:1rem;font-weight:700;letter-spacing:-.01em;color:var(--text)}
.ds-cardhead span{font-size:.78rem;color:var(--muted);text-align:right}
.ds-bars{display:grid;grid-template-columns:minmax(150px,1.2fr) 3fr auto;gap:9px 14px;align-items:center;font-size:.82rem}
.ds-bars .t{height:8px;border-radius:4px;background:var(--surface2);overflow:hidden}
.ds-bars .t i{display:block;height:100%%;background:var(--accent);border-radius:4px}
.ds-bars .t i.cash{background:var(--info)}
.ds-bars .v{text-align:right;font-variant-numeric:tabular-nums;color:var(--text2);font-weight:600}
.ds-calw{overflow-x:auto}
.ds-cal{width:100%%;border-collapse:collapse;font-size:.78rem;font-variant-numeric:tabular-nums}
.ds-cal th{color:var(--muted);font-weight:650;text-align:right;padding:6px 8px;border-bottom:1px solid var(--line)}
.ds-cal td{padding:5px 8px;text-align:right;border-bottom:1px solid var(--line);color:var(--text)}
.ds-cal th:first-child,.ds-cal td:first-child,.ds-cal th:nth-child(2),.ds-cal td:nth-child(2){text-align:left}
.ds-cal td.s{color:var(--muted);font-size:.72rem}
.ds-cal td.yr{font-weight:700}
.ds-cal tr.first td{border-top:1px solid var(--line2)}

/* --- status bar (hero) --- */
.ds-status{display:flex;align-items:center;gap:14px;flex-wrap:wrap;border:1px solid var(--line);border-left:4px solid var(--accent);
border-radius:var(--r);background:var(--surface);padding:14px 18px;margin:.6rem 0 .4rem;box-shadow:var(--shadow)}
.ds-status-t{font-size:1.06rem;font-weight:750;letter-spacing:-.015em;color:var(--text)}
.ds-status-d{font-size:.85rem;color:var(--text2);line-height:1.5}
.ds-status-r{margin-left:auto;text-align:right}
.ds-status-big{font-size:1.5rem;font-weight:750;letter-spacing:-.03em;line-height:1.1;color:var(--text)}
.ds-status-cap{font-size:.66rem;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--muted)}

/* --- cards and card grids --- */
.ds-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px;align-items:stretch}
.ds-card{border:1px solid var(--line);border-radius:var(--r);background:var(--surface);padding:14px 16px;box-shadow:var(--shadow);
display:flex;flex-direction:column;gap:10px;min-width:0}
.ds-card-h{display:flex;align-items:flex-start;justify-content:space-between;gap:10px}
.ds-card-t{font-weight:700;font-size:.98rem;letter-spacing:-.01em;color:var(--text);line-height:1.25}
.ds-card-s{font-size:.76rem;color:var(--muted);line-height:1.4;margin-top:2px}
.ds-weight{display:flex;align-items:baseline;gap:8px}
.ds-weight b{font-size:2rem;font-weight:750;letter-spacing:-.035em;line-height:1;color:var(--text)}
.ds-weight span{font-size:.78rem;color:var(--muted)}
.ds-bar{height:6px;border-radius:3px;background:var(--surface2);overflow:hidden}
.ds-bar i{display:block;height:100%%;border-radius:3px;background:var(--accent)}
.ds-dl{display:grid;grid-template-columns:auto 1fr;gap:5px 14px;font-size:.78rem;margin:0}
.ds-dl dt{color:var(--muted)}
.ds-dl dd{margin:0;text-align:right;color:var(--text);font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ds-card-cash{background:var(--info-bg);border-color:var(--info-line)}
.ds-card-active{border-color:var(--accent-line);box-shadow:0 0 0 1px var(--accent-line),var(--shadow)}

/* --- trade log --- */
.ds-log{display:flex;flex-direction:column;gap:8px}
.ds-log-i{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;align-items:start;border:1px solid var(--line);border-radius:var(--r-sm);
background:var(--surface);padding:11px 14px}
.ds-log-i .ds-chip{grid-row:span 2;margin-top:1px}
.ds-log-t{font-weight:650;font-size:.86rem;color:var(--text)}
.ds-log-d{font-size:.8rem;color:var(--text2);line-height:1.55}
.ds-log-v{grid-column:2;font-size:.74rem;color:var(--muted);line-height:1.5}

/* --- edge list --- */
.ds-rows{border:1px solid var(--line);border-radius:var(--r);overflow:hidden;background:var(--surface)}
.ds-row{display:grid;grid-template-columns:34px minmax(0,1fr) auto;gap:4px 12px;align-items:center;padding:10px 14px;border-top:1px solid var(--line)}
.ds-row:first-child{border-top:none}
.ds-row-rank{font-weight:750;color:var(--faint);font-size:.84rem}
.ds-row-name{font-weight:650;font-size:.86rem;color:var(--text);min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ds-row-meta{grid-column:2/-1;display:flex;flex-wrap:wrap;gap:3px 14px;font-size:.74rem;color:var(--muted)}
.ds-row-meta b{color:var(--text2);font-weight:650}
@media(min-width:900px){.ds-row{grid-template-columns:34px minmax(160px,1fr) auto minmax(300px,1.4fr)}.ds-row-meta{grid-column:auto;justify-content:flex-end}}

/* --- notes --- */
.ds-note{border:1px solid var(--line);border-radius:var(--r-sm);background:var(--surface);padding:11px 14px;font-size:.82rem;line-height:1.6;color:var(--text2)}
.ds-note b{color:var(--text);font-weight:700}
.ds-note-warn{background:var(--warn-bg);border-color:var(--warn-line)}
.ds-note-pos{background:var(--pos-bg);border-color:var(--pos-line)}
.ds-note-neg{background:var(--neg-bg);border-color:var(--neg-line)}
.ds-note-info{background:var(--info-bg);border-color:var(--info-line)}
.ds-legend{display:flex;flex-wrap:wrap;gap:6px 18px;font-size:.76rem;color:var(--muted);margin:.1rem 0 .5rem}
.ds-legend span{display:inline-flex;align-items:center;gap:6px}
.ds-legend i{width:8px;height:8px;border-radius:50%%;display:inline-block}
.ds-mono{font-family:var(--font-mono,ui-monospace,SFMono-Regular,Menlo,Consolas,monospace);font-size:.84em}

/* --- formula blocks (Method) --- */
.ds-step{display:grid;grid-template-columns:30px 1fr;gap:4px 14px;margin:.4rem 0}
.ds-step-n{width:26px;height:26px;border-radius:50%%;display:flex;align-items:center;justify-content:center;
background:var(--accent-bg);color:var(--accent);font-weight:750;font-size:.8rem;border:1px solid var(--accent-line)}
.ds-step-t{font-weight:700;font-size:.95rem;color:var(--text);padding-top:2px}
.ds-step-b{grid-column:2;font-size:.86rem;color:var(--text2);line-height:1.6}

/* --- Streamlit widget polish --- */
[data-testid="stExpander"] details{border:1px solid var(--line)!important;border-radius:var(--r)!important;background:var(--surface)}
[data-testid="stExpander"] summary{font-weight:650}
[data-testid="stExpander"] summary:hover{color:var(--accent)}
[data-testid="stDataFrame"]{border-radius:var(--r-sm)}
.stPlotlyChart{border:1px solid var(--line);border-radius:var(--r);background:var(--surface);padding:6px 6px 2px;box-shadow:var(--shadow)}
[data-testid="stMetricValue"]{letter-spacing:-.02em}
[data-testid="stVerticalBlockBorderWrapper"]{border-color:var(--line)!important;border-radius:var(--r)!important;background:var(--surface)}
[data-testid="stTabs"] [data-baseweb="tab-list"]{gap:2px;border-bottom:1px solid var(--line)}
[data-testid="stTabs"] button[role="tab"]{font-weight:600}

/* --- phone navigation: Streamlit drops its top nav below 768px --- */
.ds-mnav{display:none}
@media(max-width:768px){
[data-testid="stSidebarCollapsedControl"],[data-testid="stExpandSidebarButton"]{display:none!important}
.ds-mnav{display:flex;gap:6px;overflow-x:auto;scrollbar-width:none;padding:2px 0 8px;margin:0 -.5rem .3rem;padding-inline:.5rem}
.ds-mnav::-webkit-scrollbar{display:none}
.ds-mnav a{flex:0 0 auto;padding:6px 12px;border-radius:999px;border:1px solid var(--line);background:var(--surface);
color:var(--text2)!important;text-decoration:none!important;font-size:.78rem;font-weight:600;white-space:nowrap}
.ds-mnav a.on{background:var(--accent-bg);border-color:var(--accent-line);color:var(--accent)!important}
[data-testid="stMainBlockContainer"]{padding-inline:.75rem}
h1{font-size:1.45rem!important}
.ds-kpis{grid-template-columns:1fr 1fr;gap:8px}
.ds-kpi{padding:10px 12px}.ds-kpi-v{font-size:1.2rem}
.ds-header{gap:6px 12px;padding:8px 11px}.ds-header .ds-sep{display:none}
.ds-fresh{margin-left:0;width:100%%}
.ds-status-r{margin-left:0;text-align:left}
}
"""


def _tone_rules() -> str:
    rules = []
    for tone in TONES:
        rules.append(
            f".ds-chip-{tone}{{color:var(--{tone});background:var(--{tone}-bg);border-color:var(--{tone}-line)}}"
            f".ds-kpi-{tone}{{background:var(--{tone}-bg);border-color:var(--{tone}-line)}}"
            f".ds-kpi-{tone} .ds-kpi-v{{color:var(--{tone})}}"
            f".ds-status-{tone}{{border-left-color:var(--{tone})}}"
        )
    return "\n".join(rules)


def css(tokens: dict[str, str] | None = None) -> str:
    return _CSS % {"vars": _vars(tokens or palette()), "tone_rules": _tone_rules()}


def inject_theme() -> None:
    st.markdown(f"<style>{css()}</style>", unsafe_allow_html=True)


# --------------------------------------------------------------------------- #
# formatting
# --------------------------------------------------------------------------- #
def fmt_pct(value: object, digits: int = 1) -> str:
    try:
        value = float(value)
        return "—" if pd.isna(value) else f"{value * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def fmt_signed_pct(value: object, digits: int = 1) -> str:
    try:
        value = float(value)
        return "—" if pd.isna(value) else f"{value * 100:+.{digits}f}%"
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


def fmt_rupees(value: object) -> str:
    """Indian units: ₹4.2 Cr, ₹30.0 L, ₹8,500."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return "—"
    if pd.isna(value):
        return "—"
    if abs(value) >= 1e7:
        return f"₹{value / 1e7:.2f} Cr"
    if abs(value) >= 1e5:
        return f"₹{value / 1e5:.1f} L"
    return f"₹{value:,.0f}"


def tone_of(value: object, neutral: float = 0.0) -> str:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return ""
    if pd.isna(value) or value == neutral:
        return ""
    return "pos" if value > neutral else "neg"


def _esc(value: object) -> str:
    return html.escape(str(value if value is not None else ""))


# --------------------------------------------------------------------------- #
# primitives: each returns HTML, or renders it
# --------------------------------------------------------------------------- #
def html_block(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


def chip(text: str, tone: str = "", large: bool = False, dot: bool = False) -> str:
    cls = "ds-chip" + (f" ds-chip-{tone}" if tone in TONES else "") + (" ds-chip-lg" if large else "")
    return f'<span class="{cls}">{"<i></i>" if dot else ""}{_esc(text)}</span>'


def action_chip(action: str, large: bool = False) -> str:
    return chip(action, ACTION_TONE.get(str(action).upper(), ""), large=large)


def page_header(kicker: str, title: str, subtitle: str = "") -> None:
    sub = f'<div class="ds-sub">{_esc(subtitle)}</div>' if subtitle else ""
    html_block(f'<div class="ds-kicker">{_esc(kicker)}</div><h1>{_esc(title)}</h1>{sub}')


def section(title: str, note_text: str = "") -> None:
    sub = f'<div class="ds-section-n">{_esc(note_text)}</div>' if note_text else ""
    html_block(f'<div class="ds-section"><div class="ds-section-t">{_esc(title)}</div>{sub}</div>')


def note(text_html: str, tone: str = "") -> None:
    """A callout. ``text_html`` is trusted markup: escape any data with ``_esc`` first."""
    if tone == "amber":
        tone = "warn"
    cls = f"ds-note ds-note-{tone}" if tone in TONES else "ds-note"
    html_block(f'<div class="{cls}">{text_html}</div>')


def kpi_html(label: str, value: object, sub: str = "", tone: str = "") -> str:
    if tone == "amber":
        tone = "warn"
    elif tone in ("buy", "green"):
        tone = "pos"
    elif tone == "red":
        tone = "neg"
    elif tone == "blue":
        tone = "accent"
    cls = f"ds-kpi ds-kpi-{tone}" if tone in TONES else "ds-kpi"
    sub_html = f'<div class="ds-kpi-n">{_esc(sub)}</div>' if sub else ""
    return (
        f'<div class="{cls}"><div class="ds-kpi-l">{_esc(label)}</div>'
        f'<div class="ds-kpi-v">{_esc(value)}</div>{sub_html}</div>'
    )


def kpi_grid(items: Sequence[tuple[str, object, str, str]]) -> None:
    """items: (label, value, note, tone); tone is '' or one of TONES."""
    html_block(f'<div class="ds-kpis">{"".join(kpi_html(*item) for item in items)}</div>')


# The earlier name, kept so nothing that imported it breaks.
kpi_strip = kpi_grid


def status_bar(title: str, detail_html: str = "", tone: str = "accent", right: tuple[str, str] | None = None) -> None:
    """The one-line answer at the top of a page. ``right`` is (caption, big value)."""
    tone = tone if tone in TONES else "accent"
    right_html = (
        f'<div class="ds-status-r"><div class="ds-status-cap">{_esc(right[0])}</div>'
        f'<div class="ds-status-big">{_esc(right[1])}</div></div>'
        if right
        else ""
    )
    html_block(
        f'<div class="ds-status ds-status-{tone}"><div><div class="ds-status-t">{_esc(title)}</div>'
        f'<div class="ds-status-d">{detail_html}</div></div>{right_html}</div>'
    )


def card_grid(cards: Iterable[str]) -> None:
    html_block(f'<div class="ds-grid">{"".join(cards)}</div>')


def stage_legend() -> None:
    colours = stage_colors()
    items = "".join(
        f'<span><i style="background:{colours[stage]}"></i>{_esc(stage)}</span>' for stage in STAGE_TONE
    )
    html_block(f'<div class="ds-legend">{items}</div>')


def steps(items: Sequence[tuple[str, str]]) -> None:
    """Numbered steps: (title, body_html)."""
    html_block(
        "".join(
            f'<div class="ds-step"><div class="ds-step-n">{i}</div><div class="ds-step-t">{_esc(title)}</div>'
            f'<div class="ds-step-b">{body}</div></div>'
            for i, (title, body) in enumerate(items, start=1)
        )
    )


def readings(items: Sequence[tuple[str, str, str, str]]) -> None:
    """A row of centred figures. items: (label, value, note, direction); direction is up, down, warn or ''."""
    cells = "".join(
        f'<div class="ds-read"><div class="ds-read-l">{_esc(label)}</div>'
        f'<div class="ds-read-v {direction if direction in ("up", "down", "warn") else ""}">{_esc(value)}</div>'
        + (f'<div class="ds-read-n">{_esc(sub)}</div>' if sub else "") + "</div>"
        for label, value, sub, direction in items
    )
    html_block(f'<div class="ds-reads">{cells}</div>')


@contextmanager
def card(title: str, aside: str = "") -> Iterator[None]:
    """A bordered container with a title, and a short figure or count on the right."""
    with st.container(border=True):
        html_block(f'<div class="ds-cardhead"><b>{_esc(title)}</b><span>{_esc(aside)}</span></div>')
        yield


def bar_list(rows: Sequence[tuple[str, float, str, bool]], scale: float | None = None) -> str:
    """Horizontal bars: (label, value, shown value, is_cash). ``scale`` is the full-width value."""
    top = scale or max((float(r[1]) for r in rows), default=1.0) or 1.0
    body = "".join(
        f'<span>{_esc(label)}</span><span class="t"><i class="{"cash" if is_cash else ""}" '
        f'style="width:{max(min(float(value) / top, 1.0), 0.0) * 100:.1f}%%"></i></span><span class="v">{_esc(shown)}</span>'
        for label, value, shown, is_cash in rows
    ).replace("%%", "%")
    return f'<div class="ds-bars">{body}</div>'


def _cell_tint(value: float, cap: float = 0.08) -> str:
    if value != value or value == 0:
        return ""
    alpha = 0.08 + 0.32 * min(abs(value) / cap, 1.0)
    rgb = "16,185,129" if value > 0 else "244,63,94"
    return f' style="background:rgba({rgb},{alpha:.3f})"'


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def calendar_html(grids: Sequence[tuple[str, pd.DataFrame]]) -> str:
    """Years down, months across, one row per series (e.g. Strategy, Nifty 50, Alpha) within each year."""
    years = sorted({int(y) for _, grid in grids for y in grid.index}, reverse=True)
    head = "<tr><th>Year</th><th></th>" + "".join(f"<th>{m}</th>" for m in MONTHS) + "<th>Year</th></tr>"
    rows = []
    for year in years:
        for i, (name, grid) in enumerate(grids):
            if year not in grid.index:
                continue
            row = grid.loc[year]
            cells = []
            for month in [*MONTHS, "Year"]:
                value = row.get(month)
                value = float(value) if value is not None and pd.notna(value) else float("nan")
                text = "" if value != value else f"{value:+.1%}"
                cls = ' class="yr"' if month == "Year" else ""
                cells.append(f"<td{cls}{_cell_tint(value, 0.25 if month == 'Year' else 0.08)}>{text}</td>")
            rows.append(f'<tr class="{"first" if i == 0 else ""}"><td>{year if i == 0 else ""}</td>'
                        f'<td class="s">{_esc(name)}</td>{"".join(cells)}</tr>')
    return f'<div class="ds-calw"><table class="ds-cal"><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>'
