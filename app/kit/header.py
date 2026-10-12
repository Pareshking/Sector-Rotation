"""The top bar and market line, as the Paresh app draws them (render_header_kpi_bar).

Brand, the page links (a ☰ menu below 900px), a green "Prices · close of …"
pill that turns amber when the data is stale, and the market strip beneath.
The CSS is the Paresh stylesheet (app/kit/theme.py); only the figures differ:
this strategy's regime is Nifty 50 TRI's 12-month return against the liquid
fund's, and its universe is sector and theme indices.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass

import streamlit as st


@dataclass(frozen=True)
class Market:
    regime: str = ""                 # "RISK-ON" / "RISK-OFF"
    benchmark_level: float | None = None
    vs_200d: float | None = None     # fraction above (+) or below (-) the 200-session average
    benchmark_12m: float | None = None
    hurdle_12m: float | None = None
    universe: int = 0
    beating_cash: int = 0
    tradeable: int = 0
    prices_as_of: str = ""
    stale: bool = False


def _pill(market: Market) -> str:
    if not market.prices_as_of:
        return ""
    lead = "Data stale · closes of " if market.stale else "Prices · close of "
    cls = "hdr-pill hdr-pill-warn" if market.stale else "hdr-pill"
    return (f'<span class="{cls}" title="{html.escape(lead + market.prices_as_of)}"><span class="hdr-dot"></span>'
            f'<span><span class="hdr-pill-lead">{html.escape(lead)}</span>{html.escape(market.prices_as_of)}</span></span>')


def _strip(m: Market) -> str:
    up = m.regime == "RISK-ON"
    items = [f'<div class="mkt-item mkt-regime-item"><span class="{"mkt-up" if up else "mkt-down"} mkt-regime">'
             f'<span class="mkt-dot">●</span>{"Risk-on" if up else "Risk-off"}</span></div>']
    if m.benchmark_level is not None:
        items.append(f'<div class="mkt-item mkt-index"><span class="mkt-label">Nifty 50 TRI</span>'
                     f'<strong>{m.benchmark_level:,.0f}</strong></div>')
    if m.vs_200d is not None:
        word = "above" if m.vs_200d >= 0 else "below"
        items.append(f'<div class="mkt-item mkt-distance"><strong class="{"mkt-up" if m.vs_200d >= 0 else "mkt-down"}">'
                     f'{abs(m.vs_200d) * 100:.1f}% {word}</strong><span class="mkt-label">200D average</span></div>')
    if m.benchmark_12m is not None and m.hurdle_12m is not None:
        items.append(f'<div class="mkt-item"><span class="mkt-label">12M · Nifty 50 TRI vs liquid fund</span>'
                     f'<strong>{m.benchmark_12m:+.1%} <em>vs {m.hurdle_12m:.1%}</em></strong></div>')
    items.append(f'<div class="mkt-item"><span class="mkt-label">Universe</span><strong>{m.universe}</strong></div>')
    if m.universe:
        items.append(f'<div class="mkt-item"><span class="mkt-label">Beating cash · 12M</span><strong>{m.beating_cash} '
                     f'<em>({m.beating_cash / m.universe * 100:.0f}%)</em></strong></div>')
        items.append(f'<div class="mkt-item"><span class="mkt-label">Tradeable</span><strong>{m.tradeable} '
                     f'<em>({m.tradeable / m.universe * 100:.0f}%)</em></strong></div>')
    return f'<div role="status" aria-label="Market status" class="mkt-snapshot">{"".join(items)}</div>'


def render_header(market: Market, nav_pages: list, active_page: object, groups: dict[str, list[int]]) -> None:
    """Brand and links on one line, the status pill on the right, the market strip below."""
    slug = re.sub(r"[^A-Za-z0-9_-]", "_", str(getattr(active_page, "url_path", "") or "home"))
    with st.container(key="app_header_shell", width="stretch", horizontal=True,
                      vertical_alignment="center", gap="small", wrap=False):
        with st.container(key="app_brand", width="content"):
            st.page_link(nav_pages[0], label="Dual Momentum")
        with st.container(key="app_toplinks", horizontal=True, vertical_alignment="center", gap=None, width="stretch"):
            for i, page in enumerate(nav_pages):
                state = "navon" if page is active_page else "navoff"
                with st.container(key=f"{state}_top_{i}", width="content"):
                    st.page_link(page)
        pill = _pill(market)
        if pill:
            st.html(pill, width="content")
        # Phones and tablets only: the stylesheet hides this trigger on a desktop.
        with st.popover("☰", type="tertiary", help="Open navigation", width=320, key=f"app_nav_menu_{slug}"):
            for title, indices in groups.items():
                st.markdown(f"**{title}**")
                for i in indices:
                    state = "navon" if nav_pages[i] is active_page else "navoff"
                    with st.container(key=f"{state}_{title.lower()}_{i}", width="stretch"):
                        st.page_link(nav_pages[i])
    if market.stale:
        st.html('<div class="stale-notice" role="alert">&#9888;&#65039; The published data is older than it should be; '
                'see Data Health.</div>')
    st.html(_strip(market))
