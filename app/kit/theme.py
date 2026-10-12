import hashlib
import re
import time
from html import escape as _esc

import numpy as np
import pandas as pd
import streamlit as st



TICK_TRUE = frozenset({"✅", "TRUE", "1", "YES", "Y"})


def is_tick_true(value) -> bool:
    """Whether a qualification cell means "yes".

    "Above 50 EMA" and "Near 52W High" carry tick marks, not booleans, so every
    consumer has to decode them. Defined once here -- the leaf module both the
    components layer and the row renderers can import -- because the copies
    drifted apart before: one of them omitted .strip(), and the vectorised
    copies used .map(), which preserves the source dtype on an empty frame and
    produced a str-dtype mask that crashed the Qualified tab.
    """
    return value is True or (
        value is not None and str(value).strip().upper() in TICK_TRUE
    )


def clean_html(html_str: str) -> str:
    """Strips leading whitespace from every line to ensure Markdown NEVER interprets HTML as code blocks."""
    return re.sub(r"^[ \t]+", "", html_str, flags=re.MULTILINE).strip()


FORMAT_MAP: dict[str, str] = {
    # Currency & Prices (Integer rounded with commas)
    "CMP": "{:,.0f}",
    "Stop Loss": "{:,.0f}",
    "Chand Exit": "{:,.0f}",
    "52W High": "{:,.0f}",
    "52W Low": "{:,.0f}",
    "Target Value (₹)": "{:,.0f}",
    "Actual Value (₹)": "{:,.0f}",
    "Capital Sized": "{:,.0f}",
    "Allocated Capital": "{:,.0f}",
    "Market Cap (Cr)": "{:,.0f}",
    "Total MCap (Cr)": "{:,.0f}",
    "Total_MCap_Cr": "{:,.0f}",
    # Quantities & Counts (Integer)
    "Shares to Buy": "{:,.0f}",
    "Stocks": "{:,.0f}",
    "Count": "{:,.0f}",
    "Holdings": "{:,.0f}",
    "Horizons Scored": "{:.0f}",
    "Trades": "{:,.0f}",
    "Total Trades": "{:,.0f}",
    "Rank": "{:.0f}",
    "Rank (-1M)": "{:.0f}",
    "Rank (-3M)": "{:.0f}",
    "Rank Δ 1M": "{:+.0f}",
    "Rank Δ 3M": "{:+.0f}",
    "Sharpe Rank": "{:.0f}",
    "Composite Rank": "{:.0f}",
    # Decimal Ratios (1 decimal place with % sign)
    "3M Return": "{:+.1%}",
    "6M Return": "{:+.1%}",
    "1M Return": "{:+.1%}",
    "6M Net Return": "{:+.1%}",
    "6M Alpha": "{:+.1%}",
    "Return %": "{:+.1%}",
    "MTD %": "{:+.1%}",
    "Strategy Net": "{:+.1%}",
    "Benchmark": "{:+.1%}",
    "Outperform": "{:+.1%}",
    "CAGR": "{:+.1%}",
    "Max Drawdown": "{:.1%}",
    "Win Rate": "{:.0%}",
    # Pre-calculated Percentages (already multiplied by 100)
    "% High": "{:.1f}%",
    "% 50 EMA": "{:+.1f}%",
    "% 20 EMA": "{:.1f}%",
    "% 52W High": "{:.1f}%",
    "ATR %": "{:.1f}%",
    "Persistence": "{:.1f}%",
    "Max DD 3M": "{:.1f}%",
    "FFill %": "{:.1f}%",
    "Weight %": "{:.2f}%",
    "Del %": "{:.1f}%",
    "Del% 20D Avg": "{:.1f}%",
    "Del% Prev20D": "{:.1f}%",
    "Turnover %": "{:.1f}%",
    "Cost Drag %": "{:.2f}%",
    "Day Chg %": "{:+.1f}%",
    "Price_Chg_%": "{:+.1f}%",
    # Ratios & Alpha Scores (2 decimal places)
    "3M Sharpe": "{:.2f}",
    "6M Sharpe": "{:.2f}",
    "Del_Surge_Daily": "{:.2f}×",
    "Del_Surge_20D": "{:.2f}×",
    "Vol_Surge_Daily": "{:.2f}×",
    "Vol_Surge_20D": "{:.2f}×",
    "RS_Ratio": "{:.1f}",
    "RS_Momentum": "{:.1f}",
    "Sharpe": "{:.2f}",
    "Sortino": "{:.2f}",
    "Calmar": "{:.2f}",
    # A fraction, like every other alpha in this codebase: stats["alpha"] is
    # total_s_net - total_b. It sat under "Ratios" as a bare {:+.2f}, left over
    # from the residual-alpha SCORE columns that were removed -- so a 26.3%
    # alpha would have printed as "+0.26" in this renderer while the other one
    # printed "+26.3%".
    "Alpha": "{:+.1%}",
    "Beta": "{:.2f}",
    "Score": "{:.2f}",
}

def inject_custom_css() -> None:
    """Injects comprehensive Pure Paper White styling with 5-Font institutional typography."""
    st.markdown(
        clean_html("""
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Geist:wght@400..700&family=Geist+Mono:wght@400..700&display=swap" rel="stylesheet">

        <style>
        /* ── Design tokens: "Clear Ledger", light only ──────────────────
           The owner asked for a light app, so there is no dark override: a
           reader whose OS is in dark mode still gets the light palette the
           design was checked against (4.5:1 text contrast, 12px minimum). */
        :root {
            --c-bg: #F6F7F9;
            --c-bg-subtle: #F4F5F8;
            --c-surface: #FFFFFF;
            --c-border: #E3E6EB;
            --c-border-strong: #D0D5DD;
            --c-text-primary: #0E1726;
            --c-text-secondary: #3C4657;
            --c-text-muted: #5E6878;
            --c-accent: #4F46E5;
            --c-accent-text: #4338CA;
            --c-bull: #067647;
            --c-bull-tint: #E8F5EE;
            --c-bear: #B42318;
            --c-bear-tint: #FDEDEB;
            --c-caution: #B54708;
            --font-ui: 'Geist', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            --font-display: var(--font-ui);
            --font-mono: 'Geist Mono', ui-monospace, SFMono-Regular, Menlo, monospace;

            /* UI kit v2 scale: one set of steps for type, corners, depth and
               spacing, so identical kinds of block read with identical weight. */
            --fs-11: 11px; --fs-12: 12px; --fs-13: 13px; --fs-14: 14px;
            --fs-15: 15px; --fs-17: 17px; --fs-20: 20px; --fs-26: 26px;
            --r-sm: 6px; --r-md: 10px; --r-lg: 12px; --r-xl: 16px;
            --sh-1: 0 1px 2px rgba(14, 23, 38, 0.04);
            --sh-2: 0 4px 12px -2px rgba(14, 23, 38, 0.08);
            --sh-pop: 0 12px 32px -8px rgba(14, 23, 38, 0.18);
            --sp-1: 4px; --sp-2: 8px; --sp-3: 12px; --sp-4: 16px;
            --sp-5: 20px; --sp-6: 24px; --sp-8: 32px;
            --c-caution-tint: #FEF6EA;
            --c-caution-ink: #7A2E0E;
            --c-accent-tint: #EEF0FF;
        }

        /* ── Base Reset & Typography Hierarchy ── */
        html, body, [class*="css"] {
            font-family: var(--font-ui) !important;
            color: #0E1726 !important;
            background-color: #F6F7F9 !important;
            -webkit-font-smoothing: antialiased;
        }

        /* ── Typography Classes ── */
        .font-display, h1, h2, h3, h4, [data-testid="stMetricValue"] {
            font-family: var(--font-ui) !important;
            letter-spacing: -0.02em !important;
        }
        .font-mono, [data-testid="stMetricDelta"] {
            font-family: var(--font-mono) !important;
            font-variant-numeric: tabular-nums !important;
        }
        .font-code, code, pre {
            font-family: var(--font-mono) !important;
        }
.font-sans {
            font-family: var(--font-ui) !important;
        }

        /* ── Completely Hide Clunky Grey Native Scrollbars Everywhere (Across All 11 Tabs) ── */
        *, *::before, *::after {
            scrollbar-width: none !important;
            -ms-overflow-style: none !important;
        }
        *::-webkit-scrollbar, 
        ::-webkit-scrollbar,
        [data-testid="stDataFrame"] *::-webkit-scrollbar,
        [data-testid="stTable"] *::-webkit-scrollbar,
        [data-testid="stHorizontalBlock"] *::-webkit-scrollbar,
        .stDataFrame *::-webkit-scrollbar,
        div[data-testid="stTable"] *::-webkit-scrollbar,
        div[role="grid"] *::-webkit-scrollbar,
        div[class*="glideDataGrid"] *::-webkit-scrollbar,
        div[class*="dvn-scroller"] *::-webkit-scrollbar,
        .element-container *::-webkit-scrollbar,
        iframe *::-webkit-scrollbar {
            width: 0px !important;
            height: 0px !important;
            display: none !important;
            background: transparent !important;
        }

        .stApp {
            background-color: #F6F7F9 !important;
        }

        /* ── Completely Eliminate Top Space & Streamlit Header ── */
        header, [data-testid="stHeader"], .stApp > header {
            display: none !important;
            height: 0px !important;
            min-height: 0px !important;
            max-height: 0px !important;
            padding: 0px !important;
            margin: 0px !important;
            visibility: hidden !important;
            overflow: hidden !important;
        }

        #MainMenu, footer {
            display: none !important;
            visibility: hidden !important;
        }

        /* ── Remove Left Sidebar (100% Full Viewport Width) ── */
        [data-testid="stSidebar"], [data-testid="stSidebarNav"], section[data-testid="stSidebar"] {
            display: none !important;
        }

        /* ── Flush 0px Top Padding on Main Container ── */
        .main, .stMain, [data-testid="stMain"] {
            padding-top: 0px !important;
            margin-top: 0px !important;
        }

        .main .block-container, [data-testid="stMainBlockContainer"], [data-testid="block-container"] {
            /* Use the full width already granted by Streamlit's native
               layout="wide" setting. All pages share this global container. */
            max-width: 100% !important;
            width: 100% !important;
            margin-left: auto !important;
            margin-right: auto !important;
            padding-top: 0.15rem !important;
            padding-bottom: 2rem !important;
            padding-left: 1.5rem !important;
            padding-right: 1.5rem !important;
            margin-top: 0px !important;
        }

        /* ── Phones get their screen back ──────────────────────────────────
           1.5rem a side is 48px, and on a 412px phone that is 12% of the
           display spent on empty margin -- measured, not estimated. The
           screener table is the widest thing in the app and scrolls
           horizontally inside its frame, so every pixel returned here is one
           more pixel of columns visible before the reader has to scroll.
           8px still reads as a gutter rather than content touching the bezel.

           This has been the layout since the first commit; nothing recent
           narrowed it. Verified by rendering both revisions at 412px, which
           came out identical at 364px usable. */
        @media (max-width: 640px) {
            .main .block-container,
            [data-testid="stMainBlockContainer"],
            [data-testid="block-container"] {
                padding-left: 0.5rem !important;
                padding-right: 0.5rem !important;
            }

            /* Tab bar: scroll horizontally instead of squishing 10 tabs into 375px. */
            .stTabs [data-baseweb="tab-list"] {
                padding: 3px 3px !important;
                overflow-x: auto !important;
                overflow-y: hidden !important;
                flex-wrap: nowrap !important;
                scrollbar-width: none !important;
                -ms-overflow-style: none !important;
            }
            .stTabs [data-baseweb="tab-list"]::-webkit-scrollbar {
                display: none !important;
            }
            /* Each tab holds its natural width instead of flex-shrinking to zero. */
            .stTabs [data-baseweb="tab"] {
                flex: 0 0 auto !important;
                font-size: 11px !important;
                padding: 0 6px !important;
                height: 32px !important;
            }

            /* Stack all st.columns() vertically on mobile.
               260px min-width means no two columns fit in a 375px viewport,
               so every column wraps to its own full-width row.
               Content is never cramped; users scroll vertically instead. */
            [data-testid="stHorizontalBlock"] {
                flex-wrap: wrap !important;
            }
            [data-testid="column"] {
                min-width: 260px !important;
            }
        }

        /* ── Sleek Top Tab Navigation Menu (Equally Spaced Menu Bar) ── */
        .stTabs [data-baseweb="tab-list"] {
            display: flex !important;
            width: 100% !important;
            gap: 4px !important;
            background-color: #F4F5F8 !important;
            padding: 4px 5px !important;
            border-radius: 9px !important;
            border: 1px solid #E3E6EB !important;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02) !important;
            margin-bottom: 0.85rem !important;
        }

        .stTabs [data-baseweb="tab-border"],
        .stTabs [data-baseweb="tab-highlight"] {
            display: none !important;
        }

        .stTabs [data-baseweb="tab"] {
            flex: 1 1 0px !important;
            min-width: 0 !important;
            display: flex !important;
            justify-content: center !important;
            align-items: center !important;
            text-align: center !important;
            height: 36px !important;
            border-radius: 7px !important;
            padding: 0 4px !important;
            background-color: transparent !important;
            border: 1px solid transparent !important;
            font-family: var(--font-ui) !important;
            font-size: 12.5px !important;
            font-weight: 600 !important;
            color: #5E6878 !important;
            white-space: nowrap !important;
            transition: all 0.15s ease !important;
            cursor: pointer !important;
        }

        .stTabs [data-baseweb="tab"]:hover {
            background-color: #ffffff !important;
            color: #0E1726 !important;
            border-color: #E3E6EB !important;
        }

        .stTabs [aria-selected="true"] {
            background-color: #ffffff !important;
            color: #4f46e5 !important;
            font-weight: 700 !important;
            border-color: #c7d2fe !important;
            box-shadow: 0 1px 3px rgba(79, 70, 229, 0.08) !important;
        }

        /* ── Responsive Header Navigation ──────────────────────────────
           Desktop exposes the full primary navigation directly. The compact
           popover is reserved for narrower viewports where the links no longer fit. */
        .st-key-app_header_shell {
            position: relative !important;
            margin: 6px 0 4px 0 !important;
            min-height: 60px !important;
            padding: 8px 14px !important;
            border: 1px solid #E3E6EB !important;
            border-radius: 14px !important;
            background: #FFFFFF !important;
            box-shadow: 0 1px 2px rgba(14, 23, 38, 0.04) !important;
            overflow: visible !important;
            gap: 18px !important;
        }

        /* Brand: mark + name. */
        .hdr-title {
            font-family: var(--font-display); font-size: 17px; font-weight: 700;
            letter-spacing: -0.2px; color: #0E1726;
        }

        /* Brand: "Paresh Patel", a link home to the Screener. */
        .st-key-app_brand [data-testid="stPageLink"] a {
            padding: 4px 6px !important; background: transparent !important;
            text-decoration: none !important; border-radius: 8px !important;
        }
        .st-key-app_brand [data-testid="stPageLink"] a p,
        .st-key-app_brand [data-testid="stPageLink"] a span {
            font-family: var(--font-display) !important; font-size: 19px !important;
            font-weight: 700 !important; letter-spacing: -0.3px !important;
            color: #0E1726 !important; white-space: nowrap !important;
        }
        .st-key-app_brand [data-testid="stPageLink"] a:hover { background: #F4F5F8 !important; }

        /* Desktop link row. Underlined, not boxed: it is a menu, not buttons. */
        .st-key-app_toplinks { gap: 2px !important; flex-wrap: nowrap !important; overflow: hidden !important; }
        .st-key-app_toplinks [data-testid="stPageLink"] a {
            padding: 8px 10px !important;
            border-radius: 8px !important;
            border-bottom: 2px solid transparent !important;
            color: #3C4657 !important;
            text-decoration: none !important;
            white-space: nowrap !important;
            background: transparent !important;
        }
        .st-key-app_toplinks [data-testid="stPageLink"] a p,
        .st-key-app_toplinks [data-testid="stPageLink"] a span {
            font-family: var(--font-ui) !important;
            font-size: 14px !important;
            font-weight: 500 !important;
            color: inherit !important;
        }
        .st-key-app_toplinks [data-testid="stPageLink"] a:hover {
            background: #F4F5F8 !important;
            color: #0E1726 !important;
        }
        .st-key-app_toplinks [class*="st-key-navon_"] [data-testid="stPageLink"] a {
            color: #0E1726 !important;
            border-bottom-color: #4F46E5 !important;
            border-radius: 8px 8px 0 0 !important;
        }
        .st-key-app_toplinks [class*="st-key-navon_"] [data-testid="stPageLink"] a p {
            font-weight: 650 !important;
        }

        /* Data status pill. Green when every source is current, amber naming
           the stale one otherwise. */
        .hdr-pill {
            display: inline-flex; align-items: center; gap: 8px; white-space: nowrap;
            height: 32px; padding: 0 12px; border-radius: 999px;
            background: #E8F5EE; color: #054F31; font-size: 13px; font-weight: 600;
        }
        .hdr-pill .hdr-dot { width: 8px; height: 8px; border-radius: 50%; background: #067647; }
        .hdr-pill-warn { background: #FEF6EA; color: #7A2E0E; }
        .hdr-pill-warn .hdr-dot { background: #B54708; }
        .stale-notice { margin: 6px 0 2px; padding: 9px 14px; border-radius: 10px; background: #FEF6EA; border: 1px solid #F7D9B0; color: #7A2E0E; font-size: 13.5px; font-weight: 600; line-height: 1.4; }
        .stale-notice-info { background: #F4F6F9; border-color: #E3E6EB; color: #3B4655; font-weight: 500; }

        /* Compact market snapshot: same footprint as the legacy market line,
           but with a stronger visual hierarchy and the same design language as
           the rest of the page. Desktop stays one row; mobile becomes two
           compact rows without adding vertical bulk. */
        .mkt-snapshot {
            display: flex; align-items: stretch; flex-wrap: nowrap;
            min-height: 40px; margin: 4px 0 8px; overflow: hidden;
            border: 1px solid #E3E6EB; border-radius: 12px;
            background: #FFFFFF;
        }
        .mkt-item {
            display: flex; align-items: center; gap: 7px;
            min-width: 0; padding: 7px 12px;
            border-right: 1px solid #EDEFF3;
            color: #3C4657; white-space: nowrap;
            font-size: 12.5px; line-height: 1.1;
        }
        .mkt-item:last-child { border-right: 0; }
        .mkt-item strong {
            color: #0E1726; font-weight: 650;
            font-variant-numeric: tabular-nums;
        }
        .mkt-label { color: #5E6878; font-weight: 550; }
        .mkt-item em {
            color: #5E6878; font-style: normal; font-weight: 500;
            margin-left: 2px;
        }
        .mkt-regime {
            display: inline-flex; align-items: center; gap: 5px;
            font-weight: 700;
        }
        .mkt-dot { font-size: 11px; }
        .mkt-up, .mkt-item strong.mkt-up { color: #067647 !important; }
        .mkt-down, .mkt-item strong.mkt-down { color: #B42318 !important; }
        .mkt-regime.mkt-down { color: #B42318; }
        .mkt-regime.mkt-up { color: #067647; }
        .mkt-regime-item { padding-left: 12px; padding-right: 14px; }
        .mkt-index { gap: 8px; }
        .mkt-index strong { font-family: var(--font-display); font-size: 15px; }
        .mkt-distance { gap: 5px; }
        .mkt-distance strong { font-size: 12.5px; }
        
        @media (min-width: 1101px) {
            [class*="st-key-app_nav_menu_"] { display: none !important; }
        }
        @media (max-width: 1100px) {
            .st-key-app_toplinks { display: none !important; }
            .st-key-app_header_shell { padding-right: 60px !important; }
        }
        @media (max-width: 640px) {
            .st-key-app_header_shell { min-height: 52px !important; padding: 6px 56px 6px 10px !important; gap: 10px !important; flex-wrap: nowrap !important; justify-content: space-between !important; }
            .hdr-pill-lead { display: none; }

            /* Mobile market snapshot — Concept 1: one compact horizontal row.
               Every metric remains intact; the strip scrolls horizontally rather
               than wrapping into a second row or truncating labels. */
            .mkt-snapshot {
                display: flex;
                flex-wrap: nowrap;
                align-items: stretch;
                min-height: 38px;
                margin: 3px 0 8px;
                border-radius: 11px;
                overflow-x: auto;
                overflow-y: hidden;
                scrollbar-width: none !important;
                -ms-overflow-style: none !important;
                -webkit-overflow-scrolling: touch;
            }
            .mkt-snapshot::-webkit-scrollbar { display: none !important; }

            .mkt-item {
                flex: 0 0 auto;
                min-width: max-content;
                min-height: 38px;
                padding: 5px 9px;
                gap: 4px;
                border-right: 1px solid #EDEFF3;
                font-size: 11px;
                line-height: 1.05;
                overflow: visible;
                justify-content: center;
            }

            .mkt-regime-item {
                padding-left: 9px;
                padding-right: 10px;
                background: #FDEDEB;
            }
            .mkt-regime {
                gap: 4px;
                font-size: 11.5px;
            }
            .mkt-dot { font-size: 11px; }

            .mkt-index {
                gap: 5px;
                flex-direction: row;
                align-items: center;
                justify-content: center;
            }
            .mkt-index .mkt-label {
                display: inline;
                font-size: 11px;
                line-height: 1;
                overflow: visible;
                max-width: none;
            }
            .mkt-index strong {
                font-size: 12px;
                line-height: 1;
                overflow: visible;
                max-width: none;
            }

            .mkt-distance {
                gap: 4px;
                flex-direction: row;
                align-items: center;
                justify-content: center;
                background: #FDEDEB;
            }
            .mkt-distance .mkt-label {
                display: inline;
                font-size: 11px;
                line-height: 1;
                overflow: visible;
                max-width: none;
            }
            .mkt-distance strong {
                font-size: 11.5px;
                line-height: 1;
                overflow: visible;
                max-width: none;
            }

            /* Breadth metrics stay compact chips instead of becoming a second row. */
            .mkt-item:nth-child(n+4) {
                justify-content: center;
            }
            .mkt-item:nth-child(n+4) .mkt-label {
                font-size: 11px;
                line-height: 1;
                overflow: visible;
                max-width: none;
            }
            .mkt-item:nth-child(n+4) strong {
                font-size: 11.5px;
                line-height: 1;
                overflow: visible;
                max-width: none;
            }
            .mkt-item em { font-size: 11px; }
        }

        /* Keep the Streamlit popover out of normal flow so mobile flex
           stacking cannot move it underneath the header. */
        .st-key-app_header_shell [class*="st-key-app_nav_menu_"] {
            position: absolute !important;
            top: 50% !important;
            transform: translateY(-50%) !important;
            right: 7px !important;
            z-index: 20 !important;
            width: 40px !important;
            min-width: 40px !important;
            margin: 0 !important;
        }

        [class*="st-key-app_nav_menu_"] button {
            min-height: 40px !important;
            width: 40px !important;
            padding: 0 !important;
            border: 1px solid #E3E6EB !important;
            border-radius: 8px !important;
            background: #F4F5F8 !important;
            color: #3C4657 !important;
            font-size: 18px !important;
            line-height: 1 !important;
        }

        [class*="st-key-app_nav_menu_"] button:hover {
            background: #ffffff !important;
            border-color: #c7d2fe !important;
            color: #4f46e5 !important;
        }

        /* Page links inside the floating navigation menu. */
        [data-testid="stPopover"] [data-testid="stPageLink"] a,
        [data-testid="stPopoverBody"] [data-testid="stPageLink"] a {
            min-height: 38px !important;
            padding: 7px 10px !important;
            border-radius: 7px !important;
            color: #3C4657 !important;
            text-decoration: none !important;
            font-family: var(--font-ui) !important;
            font-size: 13px !important;
            font-weight: 600 !important;
        }

        [data-testid="stPopover"] [data-testid="stPageLink"] a:hover,
        [data-testid="stPopoverBody"] [data-testid="stPageLink"] a:hover {
            background: #F4F5F8 !important;
            color: #0E1726 !important;
        }

        [data-testid="stPopover"] [class*="st-key-navon_"] [data-testid="stPageLink"] a,
        [data-testid="stPopoverBody"] [class*="st-key-navon_"] [data-testid="stPageLink"] a {
            background: #eef2ff !important;
            color: #4f46e5 !important;
            border: 1px solid #c7d2fe !important;
            font-weight: 700 !important;
        }

        /* ── Screener page (redesign phase 2) ─────────────────────────── */
        .scr-head h1 {
            margin: 0 !important; padding: 0 !important;
            font-family: var(--font-display) !important; font-size: 34px !important;
            font-weight: 700 !important; letter-spacing: -0.6px !important; color: #0E1726 !important;
        }
        .scr-head p { margin: 4px 0 0; font-size: 14.5px; color: #3C4657; }
        .mkt-strip {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
            background: #FFFFFF; border: 1px solid #E3E6EB; border-radius: 16px; overflow: hidden;
        }
        .ms-tile { display: flex; flex-direction: column; gap: 6px; padding: 16px 20px; border-right: 1px solid #EDEFF3; }
        .ms-tile:last-child { border-right: 0; }
        .ms-k { font-size: 12.5px; font-weight: 600; color: #5E6878; }
        .ms-v { font-family: var(--font-display); font-size: 26px; font-weight: 700; line-height: 1.1; color: #0E1726; }
        .ms-s { font-size: 13px; color: #3C4657; line-height: 1.4; }
        .ms-s b { font-weight: 600; }
        .mkt-strip .up { color: #067647; } .mkt-strip .down { color: #B42318; }
        .t50 { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }
        .t50-grid { display:flex; flex-direction:column; gap:14px; width:100%; margin-top:4px; }
        .t50-card { width:100%; overflow:hidden; background:#FFFFFF; border:1px solid #E3E6EB; border-radius:16px; box-shadow:0 1px 3px rgba(14,23,38,0.04); }
        .t50-card-head { display:flex; align-items:center; justify-content:space-between; gap:16px; min-height:82px; padding:16px 20px; background:#F0FBF5; border-bottom:1px solid #D8F1E2; }
        .t50-card-heading { display:flex; align-items:center; gap:14px; min-width:0; }
        .t50-icon { flex:0 0 52px; width:52px; height:52px; display:grid; place-items:center; border-radius:10px; background:#12A05C; color:#FFFFFF; font-size:29px; font-weight:700; line-height:1; }
        .t50-card h2 { margin:0 !important; padding:0 !important; color:#0E1726 !important; font-family:var(--font-ui) !important; font-size:23px !important; font-weight:750 !important; letter-spacing:-0.02em !important; }
        .t50-card p { margin:4px 0 0 !important; color:#526070 !important; font-size:13.5px !important; line-height:1.35 !important; }
        .t50-table-wrap { width:100%; overflow-x:auto; -webkit-overflow-scrolling:touch; }
        .t50-table { width:100%; min-width:0; display:grid; font-family:var(--font-ui); }
        .t50-col-head, .t50-row { display:grid; grid-template-columns:52px minmax(150px,1.5fr) 1fr 1fr 0.9fr; align-items:center; column-gap:14px; padding:0 20px; }
        .t50-col-head { min-height:42px; background:#FAFBFC; border-bottom:1px solid #E3E6EB; color:#667080; font-size:12px; font-weight:650; }
        .t50-row { min-height:55px; border-bottom:1px solid #EDEFF3; color:#0E1726; font-size:14px; }
        .t50-row:last-child { border-bottom:0; } .t50-row:hover { background:#FAFBFC; }
        .t50-num { color:#667080; font-family:var(--font-mono); font-size:12px; } .t50-stock-cell { min-width:0; }
        .t50-stock { color:#0E1726 !important; text-decoration:none !important; font-weight:700; letter-spacing:0.01em; }
        .t50-stock:hover { color:#4338CA !important; text-decoration:underline !important; }
        .t50-cell { min-width:0; } .t50-change,.t50-rank,.t50-return { font-family:var(--font-mono); font-variant-numeric:tabular-nums; }
        .t50-delta { font-weight:750; } .t50-delta.positive { color:#12A05C; } .t50-delta.negative { color:#B42318; } .t50-delta.flat { color:#667080; }
        .t50-return { font-weight:700; color:#12A05C; } .t50-return.negative { color:#B42318; } .t50-return.flat { color:#667080; } .t50-trend { display:flex; align-items:center; height:36px; color:#12A05C; }
        .t50-trend svg { width:132px; height:34px; display:block; } .t50-no-trend { color:#98A2B3; }
        .t50-entered .t50-card-head { background:#F3F7FF; border-bottom-color:#DDE8FF; } .t50-entered .t50-icon { background:#2563EB; }
        .t50-left .t50-card-head { background:#FFF5F4; border-bottom-color:#F3D8D4; } .t50-left .t50-icon { background:#B42318; }
        .t50-table:has(.t50-extra) .t50-row:last-child { border-bottom:1px solid #EDEFF3; }
        .t50-more { margin:0; border-top:0; cursor:pointer; min-height:46px; padding:0 20px; display:flex; align-items:center; justify-content:center; gap:8px; color:#0E1726; font-size:13.5px; font-weight:700; }
        .t50-more:hover { background:#FAFBFC; } .t50-more span span { font-size:17px; }
        .t50-toggle { position:absolute; opacity:0; width:1px; height:1px; pointer-events:none; }
        .t50-extra, .t50-when-open { display:none; }
        .t50-toggle:checked ~ .t50-table-wrap .t50-extra { display:grid; }
        .t50-toggle:checked ~ .t50-more .t50-when-closed { display:none; }
        .t50-toggle:checked ~ .t50-more .t50-when-open { display:inline; }
        .t50-toggle:focus-visible ~ .t50-more { outline:2px solid #4338CA; outline-offset:-2px; }
        .t50-note { margin:6px 2px 0; color:#667080; font-size:12px; line-height:1.4; }
        @media (max-width:640px) {
            .t50-grid { gap:10px; } .t50-card { border-radius:14px; } .t50-card-head { min-height:78px; padding:14px; gap:10px; }
            .t50-card-heading { gap:10px; } .t50-icon { flex-basis:44px; width:44px; height:44px; border-radius:9px; font-size:24px; }
            .t50-card h2 { font-size:19px !important; } .t50-card p { font-size:12.5px !important; }
            .t50-col-head,.t50-row { padding:0 10px; column-gap:6px; grid-template-columns:28px minmax(120px,1.7fr) 72px 62px 58px; }
            .t50-col-head { min-height:38px; font-size:11px; } .t50-row { min-height:50px; font-size:12px; } .t50-table { min-width:0; } .t50-change,.t50-rank,.t50-return { font-size:11px; } .t50-num { font-size:11px; }
        }
        .st-key-scr_toolbar { gap: 10px !important; }
        .st-key-scr_toolbar [data-testid="stPopoverButton"] { height: 40px !important; }
        .sig-row { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
        .sig-chip {
            display: inline-flex; align-items: center; height: 30px; padding: 0 12px;
            border: 1px solid; border-radius: 9px; font-size: 13px; font-weight: 600;
            white-space: nowrap;
        }
        .st-key-scr_head { row-gap: 8px !important; }
        @media (max-width: 640px) {
            .scr-head h1 { font-size: 28px !important; }
            .scr-head p { font-size: 13.5px; }
            .sig-chip { height: 28px; font-size: 12px; white-space: normal; }
            /* One sideways-scrolling row of cards, so the list starts sooner. */
            .mkt-strip { display: flex; overflow-x: auto; background: transparent; border: 0; border-radius: 0; gap: 10px; }
            .ms-tile { flex: 0 0 158px; padding: 12px 14px; background: #FFFFFF; border: 1px solid #E3E6EB !important; border-radius: 14px; gap: 3px; }
            .st-key-dl_rank_csv { display: none !important; }
            /* Page figures read as a 2-wide block, not a sideways scroll. */
            .mkt-strip.pg-strip { display: grid; grid-template-columns: 1fr 1fr; overflow: visible; }
            .mkt-strip.pg-strip .ms-tile { flex: none; min-width: 0; }
            /* Filters & sort opens as a bottom sheet on a phone. The panel is
               portalled outside the page, so it is found by what it holds. */
            [data-testid="stPopoverBody"]:has(.st-key-scr_filters) {
                position: fixed !important; left: 0 !important; right: 0 !important;
                bottom: 0 !important; top: auto !important; transform: none !important;
                width: 100vw !important; max-width: 100vw !important;
                max-height: 82vh !important; overflow-y: auto !important;
                border-radius: 18px 18px 0 0 !important;
                box-shadow: 0 -8px 30px rgba(14, 23, 38, 0.18) !important;
                padding: 18px 16px 24px !important;
            }
            .ms-v { font-size: 20px; }
            .ms-s { font-size: 12px; }
            .st-key-scr_toolbar [data-testid="stSelectbox"] { width: 100% !important; }
        }

        /* ── Page kit (src/ui/page_kit.py): every other page ───────────── */
        /* Portfolio KPI strip: centered, icon-free frozen design.
           Desktop keeps six equal cards; tablet uses a 2x3 grid; phone stacks
           one card per row. */
        .mkt-strip.pg-strip {
            grid-template-columns: repeat(6, minmax(0, 1fr));
        }
        .mkt-strip.pg-strip .ms-tile {
            align-items: center;
            justify-content: center;
            text-align: center;
            min-width: 0;
            min-height: 152px;
            padding: 18px 16px;
        }
        .mkt-strip.pg-strip .ms-k,
        .mkt-strip.pg-strip .ms-v,
        .mkt-strip.pg-strip .ms-s {
            text-align: center;
            width: 100%;
        }
        .mkt-strip.pg-strip .ms-k { font-size: 14px; }
        .mkt-strip.pg-strip .ms-v { font-size: 28px; }
        .mkt-strip.pg-strip .ms-s { font-size: 14px; }
        .mkt-strip.pg-strip .ms-s:empty { display: none; }

        @media (min-width: 641px) and (max-width: 1279px) {
            .mkt-strip.pg-strip {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }

        @media (max-width: 640px) {
            .mkt-strip.pg-strip {
                grid-template-columns: 1fr;
            }
            .mkt-strip.pg-strip .ms-tile {
                min-height: 126px;
                padding: 18px 14px;
            }
            .mkt-strip.pg-strip .ms-k { font-size: 13px; }
            .mkt-strip.pg-strip .ms-v { font-size: 24px; }
            .mkt-strip.pg-strip .ms-s { font-size: 13px; }
        }
        .mkt-strip .warn { color: #B54708; }
        .pg-note {
            padding: 12px 16px; border-radius: 12px; background: #FEF6EA; border: 1px solid #F5D7A8;
            font-size: 13.5px; line-height: 1.5; color: #7A2E0E;
        }
        .pg-note b { font-weight: 700; }
        [class*="st-key-pgcard_"] {
            background: #FFFFFF; border: 1px solid #E3E6EB; border-radius: 16px;
            padding: 18px 22px !important; gap: 12px !important;
        }
        .pg-card-h { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
        .pg-card-h h2 {
            margin: 0 !important; padding: 0 !important; font-family: var(--font-ui) !important;
            font-size: 17px !important; font-weight: 650 !important; letter-spacing: 0 !important; color: #0E1726 !important;
        }
        .pg-card-h span { font-size: 12.5px; color: #5E6878; }
        .pg-cap { margin: 0; font-size: 12.5px; line-height: 1.5; color: #5E6878; }
        .pg-bars { display: flex; flex-direction: column; gap: 4px; }
        .pg-bar { display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr) 150px; align-items: center; gap: 12px; min-height: 30px; }
        .pg-bar-l { font-size: 13.5px; color: #0E1726; }
        .pg-bar-t { position: relative; height: 10px; border-radius: 5px; background: #EDEFF3; }
        .pg-bar-t i { position: absolute; left: 0; top: 0; height: 10px; border-radius: 5px; background: #4F46E5; }
        .pg-bar-t i.warn { background: #B54708; }
        .pg-bar-v { font-family: var(--font-mono); font-size: 13px; text-align: right; color: #0E1726; }
        @media (min-width: 641px) { .pg-bar-v { white-space: nowrap; } }
        [class*="st-key-pg_actions_"] { gap: 10px !important; }
        /* Exit watch */
        .xw { border: 1px solid #E3E6EB; border-radius: 12px; overflow: hidden; }
        .xw-row { display: grid; grid-template-columns: 150px 150px 1fr 1fr 1fr minmax(0, 1.4fr) 80px;
            gap: 16px; align-items: center; padding: 10px 16px; border-bottom: 1px solid #EDEFF3; background: #FFFFFF; }
        .xw-row:last-child { border-bottom: 0; }
        .xw-row:nth-child(odd):not(.xw-head) { background: #FAFBFC; }
        .xw-row.sell { background: #FFFBFA !important; }
        .xw-head { min-height: 40px; padding-top: 6px; padding-bottom: 6px; background: #F4F5F8 !important;
            font-size: 12px; font-weight: 600; color: #5E6878; }
        .xw-s { display: flex; flex-direction: column; min-width: 0; }
        .xw-s a { font-size: 14px; font-weight: 700; color: #0E1726 !important; text-decoration: none !important; }
        .xw-s a:hover { color: #4338CA !important; }
        .xw-s small { font-size: 12px; color: #5E6878; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .xw-pill { justify-self: start; font-size: 12px; font-weight: 650; padding: 3px 10px; border-radius: 999px; white-space: nowrap; }
        .xw-pill.sell { background: #FDEDEB; color: #B42318; }
        .xw-pill.watch { background: #FEF6EA; color: #7A2E0E; }
        .xw-pill.clear { background: #E8F5EE; color: #067647; }
        .xw-pill.unknown { background: #F1F3F6; color: #5E6878; }
        .xw-g { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
        .xw-g b { font-family: var(--font-mono); font-size: 13px; font-weight: 500; color: #0E1726; white-space: nowrap; }
        .xw-g > i { display: block; position: relative; height: 6px; border-radius: 3px; background: #EDEFF3; }
        .xw-g > i > i { display: block; position: absolute; left: 0; top: 0; bottom: 0; border-radius: 3px; background: #067647; }
        .xw-g.tight > i > i { background: #B54708; }
        .xw-g.broken b { color: #B42318; }
        .xw-g.broken > i { background: #FDEDEB; }
        .xw-g.broken > i > i { background: #B42318; }
        .xw-why { font-size: 12.5px; line-height: 1.4; color: #3C4657; }
        .xw-ret { font-family: var(--font-mono); font-size: 13px; text-align: right; }
        .xw-head .xw-ret, .xw-ret.hdr { font-family: var(--font-ui); font-size: 12px; }
        .xw-ret.up { color: #067647; } .xw-ret.down { color: #B42318; }
        .st-key-xw_editbar { gap: 10px !important; }
        .ac-row { display: grid; align-items: center; gap: 16px; padding: 12px 16px; border-bottom: 1px solid #EDEFF3; }
        .ac-row:last-child { border-bottom: 0; }
        .ac-row.sell { grid-template-columns: 170px minmax(0, 1fr) 130px 80px; background: #FFFBFA; }
        .ac-row.buy { grid-template-columns: 170px 80px minmax(0, 1fr) 110px 80px 80px 110px; background: #F7FCF9; }
        .ac-row.ac-head { background: #F4F5F8 !important; padding-top: 9px; padding-bottom: 9px; font-size: 12px; font-weight: 600; color: #5E6878; }
        .ac-row .n { font-family: var(--font-mono); font-size: 13.5px; text-align: right; }
        .ac-row .ac-head .n, .ac-head .n { font-family: var(--font-ui); font-size: 12px; }
        .ac-row .up { color: #067647; }
        .ac-why { font-size: 13.5px; color: #0E1726; }
        .ac-why b { font-weight: 650; color: #B42318; }
        .ac-why b.up { color: #067647; }
        .ac-when { font-size: 12.5px; color: #3C4657; }
        .ac-next { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12.5px; color: #5E6878; }
        .t50-chip {
            display: inline-flex; align-items: center; gap: 7px; min-height: 30px;
            padding: 4px 10px 4px 6px; border-radius: 999px;
            background: #F0F1FF; color: #172554 !important;
            text-decoration: none !important; font-size: 12.5px; font-weight: 700;
            white-space: nowrap; border: 1px solid #E2E4FF;
            transition: background .15s ease, border-color .15s ease, transform .15s ease;
        }
        .t50-chip:hover {
            background: #E8E9FF; border-color: #C7C9FF; transform: translateY(-1px);
        }
        .t50-rank {
            display: inline-flex; align-items: center; justify-content: center;
            width: 22px; height: 22px; border-radius: 50%;
            background: #4F46E5; color: #FFFFFF; font-family: var(--font-mono);
            font-size: 11px; font-weight: 700; line-height: 1;
        }
        @media (max-width: 900px) {
            .ac-row.sell, .ac-row.buy { grid-template-columns: minmax(0, 1fr) auto; gap: 4px 12px; }
            .ac-row.ac-head { display: none; }
            .ac-row .ac-why { grid-column: 1 / -1; order: 3; }
            .ac-row.buy .n:not(:nth-of-type(2)) { display: none; }
            .ac-row.sell .ac-when { display: none; }
        }
        @media (max-width: 900px) {
            .xw-row { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px 10px; padding: 12px 14px; }
            .xw-head { display: none !important; }
            .xw-s { grid-column: 1 / 3; }
            .xw-pill { grid-column: 3; justify-self: end; }
            .xw-why { grid-column: 1 / -1; }
            .xw-ret { display: none; }
            .xw-g b { font-size: 12px; white-space: normal; }
        }
        .cfg-top { display: flex; align-items: flex-end; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
        .cfg-pills { display: flex; gap: 8px; flex-wrap: wrap; }
        .cfg-pill { display: inline-flex; align-items: center; gap: 7px; height: 30px; padding: 0 12px; border-radius: 999px; background: #F1F3F6; color: #3C4657; font-size: 12.5px; font-weight: 600; }
        .cfg-pill.ok { background: #E8F5EE; color: #054F31; }
        .cfg-pill i { width: 7px; height: 7px; border-radius: 50%; background: #067647; }
        .cfg-index {
            position: sticky; top: 8px; z-index: 5; display: inline-flex; flex-wrap: wrap; gap: 4px;
            padding: 5px; border-radius: 12px; background: #ECEEF2; width: max-content; max-width: 100%;
            box-shadow: 0 4px 14px rgba(14, 23, 38, 0.06);
        }
        .cfg-index a {
            padding: 7px 14px; border-radius: 9px; font-size: 13.5px; font-weight: 600;
            color: #3C4657 !important; text-decoration: none !important;
        }
        .cfg-index a:hover { background: #FFFFFF; color: #0E1726 !important; }
        [class*="st-key-cfgsec_"] {
            background: #FFFFFF; border: 1px solid #E3E6EB; border-radius: 16px; overflow: hidden;
            scroll-margin-top: 70px; padding: 0 !important; gap: 0 !important;
        }
        [class*="st-key-cfgsec_"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] { gap: 0 !important; align-items: stretch; }
        [class*="st-key-cfgsec_"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child {
            background: #FAFBFC; border-right: 1px solid #EDEFF3; padding: 22px 24px;
        }
        [class*="st-key-cfgsec_"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child {
            padding: 22px 26px;
        }
        .cfg-intro { display: flex; flex-direction: column; gap: 8px; scroll-margin-top: 80px; }
        .cfg-intro span { font-size: 12px; font-weight: 700; color: #5E6878; }
        .cfg-intro h2 { margin: 0 !important; padding: 0 !important; font-family: var(--font-ui) !important;
            font-size: 19px !important; font-weight: 700 !important; letter-spacing: 0 !important; color: #0E1726 !important; }
        .cfg-intro p { margin: 0; font-size: 13.5px; line-height: 1.55; color: #3C4657; }
        .cfg-intro small { margin-top: 4px; font-size: 12.5px; color: #5E6878; }
        .cfg-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
        .cfg-stats > div { padding: 12px 14px; border-radius: 12px; background: #F4F5F8; display: flex; flex-direction: column; gap: 2px; }
        .cfg-stats > div.warn { background: #FEF6EA; }
        .cfg-stats span { font-size: 12px; font-weight: 600; color: #5E6878; }
        .cfg-kv { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; margin: 0 0 18px; padding: 0; background: #E3E6EB; border: 1px solid #E3E6EB; border-radius: 12px; overflow: hidden; }
        .cfg-kv > div { background: #FFFFFF; padding: 12px 16px; }
        .cfg-kv span { display: block; font-size: 12px; font-weight: 600; color: #5E6878; margin: 0 0 3px; }
        .cfg-kv b { display: block; font-size: 15px; font-weight: 600; color: #0E1726; }
        @media (max-width: 640px) { .cfg-kv { grid-template-columns: 1fr 1fr; } }
        .cfg-stats b { font-family: var(--font-mono); font-size: 17px; font-weight: 600; color: #0E1726; }
        .cfg-stats .warn b { color: #B54708; }
        .cfg-stats em { font-style: normal; font-size: 12px; color: #3C4657; }
        .cfg-wbar-h { font-size: 13.5px; color: #0E1726; margin-bottom: 8px; }
        .cfg-wbar { display: flex; height: 34px; border-radius: 10px; overflow: hidden; }
        .cfg-wbar span { display: flex; align-items: center; justify-content: center; font-size: 12px;
            font-weight: 600; white-space: nowrap; overflow: hidden; }
        .cfg-guide { width: 100%; border-collapse: separate; border-spacing: 0; border: 1px solid #E3E6EB;
            border-radius: 12px; overflow: hidden; font-size: 13.5px; }
        .cfg-guide th { background: #F4F5F8; text-align: left; font-size: 12px; font-weight: 600; color: #5E6878;
            padding: 9px 14px; border-bottom: 1px solid #E3E6EB; }
        .cfg-guide td { padding: 9px 14px; border-bottom: 1px solid #EDEFF3; color: #0E1726; }
        .cfg-guide tr:last-child td { border-bottom: 0; }
        .cfg-guide .n { text-align: right; font-family: var(--font-mono); }
        .cfg-rule { height: 1px; background: #EDEFF3; margin: 4px 0; }
        .cfg-sub { font-size: 14px; font-weight: 650; color: #0E1726; margin-top: 6px; }
        .st-key-cfg_sync_row { gap: 10px !important; flex-wrap: wrap; }
        @media (max-width: 760px) {
            [class*="st-key-cfgsec_"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:first-child {
                border-right: 0; border-bottom: 1px solid #EDEFF3; padding: 16px;
            }
            [class*="st-key-cfgsec_"] > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:last-child { padding: 16px; }
            .cfg-index { position: static; }
            .cfg-guide td:nth-child(3), .cfg-guide th:nth-child(3) { display: none; }
        }
        .bt-sum {
            display: flex; flex-wrap: wrap; align-items: center; gap: 8px 22px; padding: 14px 20px;
            background: #FFFFFF; border: 1px solid #E3E6EB; border-radius: 16px; font-size: 13.5px; color: #3C4657;
        }
        .bt-sum > b { font-size: 13px; font-weight: 600; color: #5E6878; }
        .bt-sum span b { color: #0E1726; font-weight: 650; }
        .gc-legend { display: flex; flex-wrap: wrap; gap: 6px 18px; font-size: 13px; color: #3C4657; }
        .gc-legend span { display: inline-flex; align-items: center; gap: 6px; }
        .gc-legend i { width: 14px; height: 3px; border-radius: 2px; background: #98A1AE; }
        .gc-ls i { background: #4F46E5 !important; }
        .gc-legend b { font-family: var(--font-mono); font-weight: 600; color: #0E1726; }
        .mo-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px; }
        .mo { padding: 12px 14px; border-radius: 12px; display: flex; flex-direction: column; gap: 3px; background: #F4F5F8; }
        .mo.up { background: #E8F5EE; } .mo.down { background: #FDEDEB; }
        .mo.live { background: #FFFFFF; border: 1.5px dashed #C7D2FE; }
        .mo-h { display: flex; justify-content: space-between; gap: 8px; font-size: 12.5px; font-weight: 600; color: #3C4657; }
        .mo-h em { font-style: normal; font-size: 11px; font-weight: 600; padding: 1px 6px; border-radius: 6px; background: rgba(255,255,255,0.7); color: #5E6878; }
        .mo-v { font-family: var(--font-mono); font-size: 18px; font-weight: 600; }
        .mo-v.up { color: #067647; } .mo-v.down { color: #B42318; }
        .mo-s { font-size: 12px; color: #3C4657; }
        /* Sectors: industry leaderboard */
        .ib { border: 1px solid #E3E6EB; border-radius: 12px; overflow: hidden; }
        .ib-row {
            display: grid; align-items: center; gap: 12px; padding: 0 16px; min-height: 46px;
            grid-template-columns: 32px minmax(0, 1.6fr) 56px 190px 76px 96px 104px 76px 72px minmax(0, 1.3fr);
            border-bottom: 1px solid #EDEFF3; font-size: 14px; background: #FFFFFF;
        }
        .ib-row:nth-child(odd):not(.ib-head) { background: #FAFBFC; }
        .ib-row:last-child { border-bottom: 0; }
        .ib-head { min-height: 40px; background: #F4F5F8 !important; font-size: 12px; font-weight: 600; color: #5E6878; }
        .ib-head .ib-num { font-family: var(--font-ui); font-size: 12px; }
        .ib-n { font-family: var(--font-mono); font-weight: 600; }
        .ib-name { display: flex; flex-direction: column; min-width: 0; }
        .ib-name b { font-weight: 650; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .ib-name small { display: none; font-size: 12px; color: #5E6878; }
        .ib-num { font-family: var(--font-mono); font-size: 13.5px; text-align: right; }
        .ib-3m { display: flex; align-items: center; justify-content: flex-end; gap: 8px; }
        .ib-3m b { font-family: var(--font-mono); font-size: 13.5px; font-weight: 500; width: 62px; text-align: right; }
        .ib-bar { position: relative; width: 96px; height: 8px; border-radius: 4px; background: #EDEFF3; }
        .ib-bar i { position: absolute; top: 0; height: 8px; border-radius: 4px; background: #98A1AE; }
        .ib-bar i.up { background: #067647; } .ib-bar i.down { background: #B42318; }
        .ib-bar em { position: absolute; left: 50%; top: -2px; width: 1px; height: 12px; background: #98A1AE; }
        .ib .up { color: #067647; } .ib .down { color: #B42318; }
        .ib-leads { display: flex; gap: 6px; overflow: hidden; }
        .ib-lead {
            font-size: 12px; font-weight: 650; padding: 2px 7px; border-radius: 6px; background: #F4F5F8;
            color: #0E1726 !important; text-decoration: none !important; white-space: nowrap;
        }
        .ib-lead:hover { background: #EEF0FF; }
        @media (max-width: 1100px) { .ib-leads, .ib-head .ib-d:last-child { display: none; } .ib-row { grid-template-columns: 32px minmax(0, 1.6fr) 56px 190px 76px 96px 104px 76px 72px; } }
        @media (max-width: 760px) {
            .ib-row { grid-template-columns: 24px minmax(0, 1fr) 80px; padding: 8px 12px; }
            .ib-d { display: none !important; }
            .ib-name small { display: block; }
            .ib-bar { display: none; }
            .ib-head .ib-3m { justify-content: flex-end; }
        }
        @media (max-width: 640px) {
            [class*="st-key-pgcard_"] { padding: 14px 14px !important; border-radius: 14px; }
            .pg-bar { grid-template-columns: minmax(0, 1.4fr) minmax(0, 1fr) 64px; gap: 8px; }
            /* Four figures read as a 2 x 2 block, not four tall tiles. */
            [class*="st-key-mrow_"] { display: grid !important; grid-template-columns: 1fr 1fr; gap: 8px !important; }
            [class*="st-key-mrow_"] > div { width: auto !important; min-width: 0 !important; }
            [class*="st-key-mrow_"] [data-testid="stMetric"] { padding: 10px 12px !important; }
            [class*="st-key-mrow_"] [data-testid="stMetricLabel"] { font-size: 11px; }
        }

        /* The watchlist bridge has no visible output. */
        .st-key-wl_store { display: none !important; }

        /* ── Stock page (redesign phase 3) ────────────────────────────── */
        .st-key-stock_page_back button {
            border: 0 !important; background: transparent !important; padding: 0 !important;
            min-height: 32px !important; color: #4338CA !important; font-weight: 600 !important;
        }
        .st-key-stock_page_back button:hover { color: #312E81 !important; text-decoration: underline; }
        .sp-card { background: #FFFFFF; border: 1px solid #E3E6EB; border-radius: 18px; padding: 20px 22px; }
        .sp-card h2, .sp-sec h2 {
            margin: 0 !important; padding: 0 !important; font-family: var(--font-ui) !important;
            font-size: 17px !important; font-weight: 650 !important; letter-spacing: 0 !important; color: #0E1726 !important;
        }
        .sp-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 16px; margin-bottom: 14px; }
        .sp-id { display: flex; flex-direction: column; gap: 10px; }
        .sp-chips { display: flex; gap: 8px; flex-wrap: wrap; }
        .sp-sym { font-family: var(--font-mono); font-size: 13px; font-weight: 600; padding: 4px 9px; border-radius: 7px; background: #0E1726; color: #FFFFFF; }
        .sp-tag { font-size: 12.5px; font-weight: 600; padding: 4px 9px; border-radius: 7px; background: #F1F3F6; color: #3C4657; }
        .sp-cls { font-size: 13.5px; color: #5E6878; }
        h1.sp-name {
            margin: 0 !important; padding: 0 !important; font-family: var(--font-display) !important;
            font-size: 38px !important; font-weight: 700 !important; letter-spacing: -0.8px !important;
            line-height: 1.1 !important; color: #0E1726 !important;
        }
        .sp-price-row { display: flex; align-items: flex-end; gap: 22px; flex-wrap: wrap; }
        .sp-price-col { display: flex; flex-direction: column; gap: 4px; }
        .sp-price { font-family: var(--font-mono); font-size: 36px; font-weight: 600; color: #0E1726; line-height: 1.1; }
        .sp-close { font-size: 13px; color: #5E6878; }
        .sp-changes { display: flex; gap: 8px; flex-wrap: wrap; padding-bottom: 4px; }
        .sp-changes { display: flex; gap: 8px; flex-wrap: wrap; padding-bottom: 2px; }
        .sp-chg { min-width: 82px; display: flex; flex-direction: column; gap: 2px; padding: 7px 11px; border-radius: 10px; }
        .sp-chg i { font-style: normal; font-size: 11.5px; font-weight: 650; color: #5E6878; }
        .sp-chg b { font-family: var(--font-mono); font-size: 13.5px; font-weight: 700; }
        .sp-chg.up { background: #E8F5EE; color: #067647; } .sp-chg.down { background: #FDEDEB; color: #B42318; }
        .sp-chg.flat { background: #F1F3F6; color: #5E6878; }
        .sp-rank { display: flex; flex-direction: column; gap: 10px; }
        .sp-k { font-size: 12.5px; font-weight: 600; color: #5E6878; }
        .sp-rank-big { display: flex; align-items: baseline; gap: 10px; }
        .sp-rank-big span { font-family: var(--font-display); font-size: 56px; font-weight: 800; line-height: 1; color: #0E1726; }
        .sp-rank-big i { font-style: normal; font-size: 15px; color: #3C4657; }
        .sp-path { display: flex; align-items: center; gap: 6px; }
        .sp-step { display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 6px 8px; border-radius: 10px; background: #F4F5F8; min-width: 50px; }
        .sp-step b { font-family: var(--font-mono); font-size: 13px; color: #0E1726; }
        .sp-step i { font-style: normal; font-size: 11.5px; color: #5E6878; }
        .sp-step.now { background: #EEF0FF; } .sp-step.now b { color: #3730A3; }
        .sp-arrow { color: #98A1AE; font-size: 12px; }
        .sp-facts { display: flex; gap: 16px; flex-wrap: wrap; font-size: 13px; color: #3C4657; }
        .sp-facts b { font-family: var(--font-mono); font-weight: 600; color: #0E1726; }
        .sp-verdict { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); grid-template-rows: auto 1fr; border-radius: 16px; margin-bottom: 14px; border: 1px solid; overflow: hidden; }
        .sp-verdict.pass { background: #F1FAF5; border-color: #BFE3CD; }
        .sp-verdict.part { background: #FEF8EE; border-color: #F5D7A8; }
        .sp-verdict.fail { background: #FDF3F2; border-color: #F3C7C1; }
        .sv-head { grid-column: 1 / -1; display: flex; align-items: center; gap: 12px; padding: 16px 20px; border-bottom: 1px solid rgba(14, 23, 38, 0.08); }
        .sv-head-mark { width: 38px; height: 38px; flex-shrink: 0; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: #FFFFFF; font-weight: 800; font-size: 19px; background: #067647; }
        .sp-verdict.part .sv-head-mark { background: #B54708; } .sp-verdict.fail .sv-head-mark { background: #B42318; }
        .sv-head b { display: block; font-family: var(--font-ui); font-size: 14px; line-height: 1.2; font-weight: 700; color: #0E1726; }
        .sv-head i { display: block; margin-top: 2px; font-family: var(--font-ui); font-style: normal; font-size: 11.5px; line-height: 1.25; color: #3C4657; }
        .sv-state { margin-left: auto; padding: 9px 18px; border-radius: 999px; background: #DDF7E9; color: #067647; font-weight: 750; font-size: 13px; }
        .sp-verdict.part .sv-state { background: #FEF0D5; color: #9A6700; } .sp-verdict.fail .sv-state { background: #FDE5E2; color: #B42318; }
        .sv-card { display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 12px; padding: 18px 20px; min-width: 0; }
        .sv-card + .sv-card { border-left: 1px solid rgba(14, 23, 38, 0.08); }
        .sv-main { min-width: 0; display: flex; flex-direction: column; gap: 3px; }
        .sv-k { font-size: 12px; line-height: 1.2; font-weight: 650; color: #0E1726; }
        .sv-main strong { font-family: var(--font-display); font-size: 18px; line-height: 1.1; font-weight: 700; color: #067647; white-space: nowrap; }
        .sp-verdict.fail .sv-main strong { color: #B42318; }
        .sv-price { font-family: var(--font-mono); font-size: 14px; line-height: 1.2; font-weight: 600; color: #0E1726; }
        .sv-side { min-width: 72px; display: flex; flex-direction: column; align-items: flex-end; gap: 3px; padding-left: 14px; border-left: 1px solid rgba(14, 23, 38, 0.08); }
        .sv-side em { font-style: normal; font-size: 13px; font-weight: 750; padding: 8px 14px; border-radius: 999px; background: #DDF7E9; color: #067647; }
        .sv-side em.fail { background: #FDE5E2; color: #B42318; }
        .sv-side em.bonus { background: #FFF0C9; color: #A66A00; }
        .sv-side span { font-size: 12px; color: #5E6878; }
        .sv-side b { font-family: var(--font-mono); font-size: 14px; font-weight: 600; color: #3C4657; text-align: right; }
        .sp-notice { background: #FEF6EA; border: 1px solid #F5D7A8; border-radius: 16px; padding: 16px 20px; margin-bottom: 14px; color: #7A2E0E; }
        .sp-exit { display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; margin: 4px 0 14px; padding: 0 2px; color: #0E1726; line-height: 1.45; }
        .sp-exit .lbl { color: #0E1726; }
        .sp-exit b { font-weight: 700; }
        .sp-exit span { color: #0E1726; }
        .sp-exit a { margin-left: 2px; color: #4338CA !important; text-decoration: none !important; white-space: nowrap; }
        .sp-exit a:hover { text-decoration: underline !important; }
        .sp-notice p { margin: 6px 0 0; font-size: 14px; line-height: 1.5; color: #3C4657; }
        .sp-sec { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin: 6px 2px 6px; }
        .sp-sec span { font-size: 12.5px; color: #5E6878; }
        .sp-ladder { margin: 14px 0; }
        .sp-range { margin: 16px 0 6px; }
        .sp-range .track { position: relative; height: 10px; border-radius: 5px; background: #EDEFF3; }
        .sp-range .fill { height: 10px; border-radius: 5px; background: linear-gradient(90deg, #C7D2FE, #4F46E5); }
        .sp-range .dot { position: absolute; top: -4px; width: 18px; height: 18px; margin-left: -9px; border-radius: 50%; background: #4F46E5; border: 3px solid #FFFFFF; box-shadow: 0 0 0 1px #4F46E5; box-sizing: border-box; }
        /* Marks ON the bar only. Unscoped, this also took the legend's two
           swatches out of the legend: they floated above the section as a
           stray "|" under the chart, and the legend lost its colours. */
        .sp-range .track i.m-line, .sp-range .track i.m-ema { position: absolute; top: -5px; width: 3px; height: 20px; margin-left: -1.5px; border-radius: 1px; }
        .sp-range i.m-line { background: #B54708; }
        .sp-range i.m-ema { background: #0E1726; }
        .sp-range .ends { display: flex; justify-content: space-between; gap: 10px; margin-top: 8px; font-size: 12.5px; color: #5E6878; flex-wrap: wrap; }
        .sp-range .key { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
        .sp-range .key i { display: inline-block; position: static; width: 3px; height: 12px; margin-left: 6px; border-radius: 1px; }
        .sp-ladder .list { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 10px; margin-top: 14px; }
        .sp-ladder .li { display: flex; flex-direction: column; gap: 3px; padding: 12px 14px; border-radius: 12px; background: #F6F7F9; }
        .sp-ladder .lk { font-size: 12.5px; font-weight: 600; color: #3C4657; }
        .sp-ladder .lv { font-family: var(--font-mono); font-size: 17px; font-weight: 600; color: #0E1726; }
        .sp-ladder .lv.up { color: #067647; } .sp-ladder .lv.down { color: #B42318; } .sp-ladder .lv.warn { color: #B54708; }
        .sp-ladder .ls { font-size: 12.5px; color: #5E6878; }
        .sp-gp { margin-bottom: 14px; }
        .gp-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 8px; }
        .gp-legend { display: flex; gap: 14px; flex-wrap: wrap; font-size: 12.5px; color: #5E6878; }
        .gp-legend span { display: flex; align-items: center; gap: 6px; }
        .gp-legend i { display: inline-block; }
        .gp-legend .k-dd { width: 12px; height: 12px; border-radius: 3px; background: #F2B8B0; }
        .gp-legend .k-ret { width: 12px; height: 12px; border-radius: 3px; background: #067647; }
        .gp-legend .k-nb { width: 14px; height: 4px; border-radius: 2px; background: #98A1AE; }
        .gp-legend .k-med { width: 0; height: 14px; border-left: 2px dashed #5E6878; }
        .gp-row { display: grid; grid-template-columns: 96px minmax(150px, 290px) 1px minmax(0, 1fr) 140px 110px; align-items: center; min-height: 62px; border-bottom: 1px solid #F1F3F6; }
        .gp-row.gp-hdr { min-height: 30px; font-size: 12px; font-weight: 600; color: #5E6878; border-bottom: 1px solid #EDEFF3; }
        .gp-row.gp-hdr .r { text-align: right; padding-right: 10px; }
        .gp-row.gp-hdr span:nth-child(4) { padding-left: 10px; }
        .gp-w b { display: block; font-size: 15px; font-weight: 650; }
        .gp-w i { display: block; font-style: normal; font-size: 11.5px; color: #5E6878; }
        .gp-dd { position: relative; height: 28px; margin-right: 10px; }
        .gp-dd .bar { position: absolute; right: 0; top: 4px; height: 20px; border-radius: 6px 0 0 6px; background: #F2B8B0; }
        .gp-dd .lbl { position: absolute; top: 5px; font-family: var(--font-mono); font-size: 12.5px; font-weight: 600; color: #B42318; white-space: nowrap; }
        .gp-med { position: absolute; top: -2px; height: 32px; z-index: 1; border-left: 2px dashed #5E6878; }
        .gp-axis { height: 44px; background: #0E1726; }
        .gp-ret { position: relative; height: 34px; margin: 0 20px 0 10px; }
        .gp-ret .bar { position: absolute; left: 0; top: 2px; height: 18px; border-radius: 0 6px 6px 0; background: linear-gradient(90deg, #0B8A55, #067647); }
        .gp-ret .bar.neg { background: #F2B8B0; }
        .gp-ret .lbl { position: absolute; top: 2px; font-family: var(--font-mono); font-size: 13.5px; font-weight: 700; color: #054F31; white-space: nowrap; }
        .gp-ret .lbl.neg { color: #B42318; }
        .gp-ret .nb { position: absolute; left: 0; top: 25px; height: 4px; border-radius: 0 2px 2px 0; background: #98A1AE; }
        .gp-ret .nl { position: absolute; top: 20px; font-size: 11px; color: #5E6878; white-space: nowrap; }
        .gp-sh { display: flex; align-items: center; justify-content: flex-end; gap: 8px; padding-right: 10px; }
        .gp-sh .dots { display: flex; gap: 3px; }
        .gp-sh .dots i { width: 9px; height: 9px; border-radius: 50%; background: #E3E6EB; }
        .gp-sh .dots i.on { background: #4F46E5; } .gp-sh .dots i.half { background: rgba(79, 70, 229, 0.35); }
        .gp-sh b { font-family: var(--font-mono); font-size: 15px; font-weight: 600; width: 42px; text-align: right; }
        .gp-top { display: flex; justify-content: flex-end; padding-right: 4px; }
        .gp-top em { font-style: normal; font-size: 11.5px; font-weight: 700; padding: 3px 8px; border-radius: 999px; }
        .gp-top em.good { background: #E8F5EE; color: #054F31; } .gp-top em.poor { background: #F1F3F6; color: #3C4657; }
        .gp-foot { padding-top: 10px; font-size: 12.5px; color: #5E6878; line-height: 1.5; }
        .sp-peers { padding: 0; overflow: hidden; margin-bottom: 14px; }
        .sp-peers .ph { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; padding: 16px 20px; }
        .sp-peers .ph span { font-size: 13px; color: #5E6878; }
        .sp-peers .tw { overflow-x: auto; }
        .sp-peers table { width: 100%; border-collapse: collapse; }
        .sp-peers th { background: #F4F5F8; font-size: 12px; font-weight: 600; color: #5E6878; text-align: right; padding: 10px 16px; border-top: 1px solid #E3E6EB; border-bottom: 1px solid #E3E6EB; white-space: nowrap; }
        .sp-peers td { padding: 12px 16px; text-align: right; font-family: var(--font-mono); font-size: 13.5px; border-bottom: 1px solid #EDEFF3; white-space: nowrap; }
        .sp-peers .l { text-align: left; }
        .sp-peers td.s { font-family: var(--font-ui); font-weight: 650; }
        .sp-peers td.s a { color: #0E1726 !important; text-decoration: none !important; }
        .sp-peers td.s a:hover { color: #4338CA !important; }
        .sp-peers td.s em { margin-left: 8px; font-style: normal; font-size: 11px; font-weight: 700; padding: 2px 7px; border-radius: 6px; background: #EEF0FF; color: #3730A3; }
        .sp-peers tr.hl td { background: #F4F3FF; }
        .sp-peers .up { color: #067647; } .sp-peers .down { color: #B42318; }
        .sp-checks { display: flex; flex-wrap: wrap; gap: 8px; }
        .sp-checks span { font-size: 13.5px; padding: 8px 12px; border-radius: 10px; background: #F6F7F9; color: #3C4657; }
        .sp-checks span.bad { background: #FEF6EA; color: #7A2E0E; font-weight: 600; }
        @media (max-width: 900px) {
            .sp-hero { grid-template-columns: 1fr; }
            .sp-verdict { grid-template-columns: 1fr; }
            .sv-head { grid-column: auto; }
            .sv-card + .sv-card { border-left: 0; border-top: 1px solid rgba(14, 23, 38, 0.08); }
            .sp-path { gap: 4px; }
            .sp-step { min-width: 46px; padding: 6px 5px; }
            .sp-step b { font-size: 12.5px; }
        }
        @media (max-width: 640px) {
            .sp-card { padding: 16px; border-radius: 16px; }
            .sp-exit { gap: 6px; font-size: 14px; line-height: 1.5; }
            .sp-exit .lbl, .sp-exit b, .sp-exit span, .sp-exit a { display: inline; }
            h1.sp-name { font-size: 28px !important; }
            .sp-price { font-size: 30px; }
            .sp-rank-big span { font-size: 44px; }
            .sp-path { width: 100%; justify-content: space-between; }
            .sp-step { flex: 1 1 0; min-width: 0; max-width: 72px; }
            .sp-arrow { flex: 0 0 auto; }
            /* Phone: each window stacks -- label and Sharpe, the return bar,
               the drawdown bar -- with the values in a right-hand column. */
            .gp-row {
                grid-template-columns: minmax(0, 1fr) auto;
                grid-template-areas: "w sh" "ret ret" "dd dd";
                row-gap: 6px; padding: 10px 0; min-height: 0;
            }
            .gp-row.gp-hdr, .gp-axis, .gp-top, .gp-med, .gp-ret .nl { display: none !important; }
            .gp-w { grid-area: w; } .gp-w b { display: inline; } .gp-w i { display: inline; margin-left: 6px; }
            .gp-sh { grid-area: sh; padding-right: 0; }
            .gp-sh b { width: auto; font-size: 14px; }
            .gp-ret { grid-area: ret; margin: 0 78px 0 0; height: 26px; }
            .gp-ret .lbl { left: auto !important; right: -76px; width: 72px; text-align: right; font-size: 13px; }
            .gp-ret .nb { top: 21px; }
            .gp-dd { grid-area: dd; margin: 0 78px 0 0; height: 14px; }
            .gp-dd .bar { left: 0; right: auto; top: 2px; height: 10px; border-radius: 0 5px 5px 0; }
            .gp-dd .lbl { right: -76px !important; width: 72px; text-align: right; top: -2px; font-size: 12px; }
            .sp-ladder .list { grid-template-columns: 1fr 1fr; }
        }

        /* ── Command Bar & Quick Filter Pills Styling ── */
        [data-testid="stPills"] {
            display: flex !important;
            gap: 6px !important;
            align-items: center !important;
            flex-wrap: nowrap !important;
            white-space: nowrap !important;
            overflow-x: auto !important;
            scrollbar-width: none !important;
        }

        [data-testid="stPills"] button {
            border-radius: 999px !important;
            font-size: 14px !important;
            font-weight: 500 !important;
            padding: 2px 14px !important;
            height: 40px !important;
            border: 1px solid #E3E6EB !important;
            background-color: #F4F5F8 !important;
            color: #3C4657 !important;
            white-space: nowrap !important;
            flex-shrink: 0 !important;
            transition: all 0.15s ease !important;
        }

        [data-testid="stPills"] button:hover {
            background-color: #ffffff !important;
            color: #4f46e5 !important;
            border-color: #D0D5DD !important;
        }

        [data-testid="stPills"] button[aria-checked="true"] {
            background-color: #EEEDFD !important;
            color: #0E1726 !important;
            border: 1.5px solid #4F46E5 !important;
            box-shadow: none !important;
            font-weight: 600 !important;
        }

        /* ── Segmented Control (Table / Cards Switcher) ── */
        [data-testid="stSegmentedControl"] {
            height: 36px !important;
            border-radius: 8px !important;
            background-color: #F4F5F8 !important;
            border: 1px solid #E3E6EB !important;
            padding: 2px !important;
        }

        [data-testid="stSegmentedControl"] button {
            height: 30px !important;
            border-radius: 6px !important;
            font-size: 0.78rem !important;
            font-weight: 600 !important;
            padding: 0 10px !important;
            color: #5E6878 !important;
            border: none !important;
        }

        [data-testid="stSegmentedControl"] button[aria-checked="true"] {
            background-color: #ffffff !important;
            color: #4f46e5 !important;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05) !important;
            font-weight: 700 !important;
        }

        /* ── Harmonized Selectbox Inputs ── */
        div[data-testid="stSelectbox"] > div {
            min-height: 36px !important;
            border-radius: 8px !important;
            border-color: #E3E6EB !important;
            font-size: 0.82rem !important;
        }

        /* ── RRG Active Selection Buttons: Universal Left Alignment ── */
        /* RRG: the chart's frame, the selection bar, the quadrant lists */
        .st-key-rrg_frame iframe { height: 780px !important; width: 100% !important; }
        .st-key-rrg_selbar { gap: 8px !important; flex-wrap: wrap !important; }
        .st-key-rrg_selbar button { min-height: 32px !important; height: 32px !important; padding: 0 12px !important;
            border-radius: 999px !important; font-size: 12.5px !important; font-weight: 600 !important; }
        .st-key-rrg_selbar button p { font-size: 12.5px !important; font-weight: 600 !important; }
        [class*="st-key-btn_rrg_lead_"] button { background: #E8F5EE !important; border-color: #BFE3CD !important; color: #067647 !important; border-radius: 10px !important; }
        [class*="st-key-btn_rrg_imp_"] button { background: #EAF1FE !important; border-color: #C3D6FB !important; color: #2563EB !important; border-radius: 10px !important; }
        [class*="st-key-btn_rrg_weak_"] button { background: #FEF6EA !important; border-color: #F5D7A8 !important; color: #B54708 !important; border-radius: 10px !important; }
        [class*="st-key-btn_rrg_lag_"] button { background: #FDEDEB !important; border-color: #F3C7C1 !important; color: #B42318 !important; border-radius: 10px !important; }
        [class*="st-key-btn_rrg_lead_"] button p { color: #067647 !important; }
        [class*="st-key-btn_rrg_imp_"] button p { color: #2563EB !important; }
        [class*="st-key-btn_rrg_weak_"] button p { color: #B54708 !important; }
        [class*="st-key-btn_rrg_lag_"] button p { color: #B42318 !important; }
        [class*="st-key-del_rrg_"] button { background: #FFFFFF !important; border: 1px solid #E3E6EB !important; }
        /* Phone rules come after the base ones so they win at equal specificity. */
        @media (max-width: 760px) {
            .st-key-rrg_frame iframe { height: 480px !important; }
            .st-key-rrg_frame .stElementContainer { height: auto !important; flex: 0 0 auto !important; }
            /* One row that scrolls sideways, so the chart starts sooner. */
            .st-key-rrg_selbar { flex-wrap: nowrap !important; overflow-x: auto !important; padding-bottom: 4px; }
            .st-key-rrg_selbar > div { flex: none !important; }
            .st-key-rrg_selbar button p { white-space: nowrap !important; }
        }
        .rq-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
        .rq { border: 1px solid #E3E6EB; border-radius: 14px; overflow: hidden; background: #FFFFFF; }
        .rq-h { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; padding: 10px 14px; }
        .rq-h b { font-size: 14px; }
        .rq-h span { font-size: 12px; color: #3C4657; }
        .rq.lead .rq-h { background: #E8F5EE; } .rq.lead .rq-h b { color: #067647; }
        .rq.imp .rq-h { background: #EAF1FE; } .rq.imp .rq-h b { color: #2563EB; }
        .rq.weak .rq-h { background: #FEF6EA; } .rq.weak .rq-h b { color: #B54708; }
        .rq.lag .rq-h { background: #FDEDEB; } .rq.lag .rq-h b { color: #B42318; }
        .rq-i { display: flex; justify-content: space-between; gap: 8px; margin: 0 14px; padding: 7px 0;
            border-bottom: 1px solid #EDEFF3; font-size: 13px; }
        .rq-i:last-child { border-bottom: 0; }
        .rq-i span { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .rq-i a { color: #0E1726 !important; text-decoration: none !important; font-weight: 600; }
        .rq-i b { font-family: var(--font-mono); font-size: 12px; font-weight: 500; color: #3C4657; white-space: nowrap; }
        .rq-none { color: #5E6878; }
        @media (max-width: 900px) { .rq-grid { grid-template-columns: 1fr; } }



        /* ── Headings & Badges ── */
        h1, h2, h3, h4, h5, h6 {
            color: #0E1726 !important;
            font-weight: 700 !important;
            letter-spacing: -0.02em !important;
        }

        p, [data-testid="stMarkdownContainer"] p {
            color: #3C4657 !important;
            font-size: 0.88rem;
        }

        [data-testid="stCaptionContainer"] {
            font-size: 0.78rem !important;
            color: #5E6878 !important;
        }

        /* ── Slim Left Sidebar ── */
        [data-testid="stSidebar"] {
            background-color: #F4F5F8 !important;
            border-right: 1px solid #E3E6EB !important;
            box-shadow: 1px 0 3px rgba(0, 0, 0, 0.02) !important;
        }

        [data-testid="stSidebarContent"] {
            background-color: #F4F5F8 !important;
            padding: 1.2rem 1.1rem !important;
        }


        /* ── Sidebar Radio Navigation Items ── */
        [data-testid="stSidebar"] [data-testid="stRadio"] > div {
            gap: 3px !important;
        }
        [data-testid="stSidebar"] [data-testid="stRadio"] label {
            padding: 7px 10px !important;
            border-radius: 8px !important;
            border: 1px solid transparent !important;
            background-color: transparent !important;
            font-weight: 600 !important;
            font-size: 0.85rem !important;
            color: #3C4657 !important;
            transition: all 0.15s ease !important;
            cursor: pointer !important;
            width: 100% !important;
        }
        [data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
            background-color: #ffffff !important;
            border-color: #E3E6EB !important;
            color: #4f46e5 !important;
        }
        [data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) {
            background-color: #ffffff !important;
            border-color: #c7d2fe !important;
            color: #4f46e5 !important;
            box-shadow: 0 1px 3px rgba(79, 70, 229, 0.08) !important;
        }

        [data-testid="stSidebar"] .stButton > button {
            background-color: #ffffff !important;
            border: 1px solid #E3E6EB !important;
            color: #1F2A3A !important;
            font-weight: 600 !important;
            border-radius: 8px !important;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03) !important;
            transition: all 0.15s ease-in-out !important;
        }

        [data-testid="stSidebar"] .stButton > button:hover {
            background-color: #eef2ff !important;
            border-color: #c7d2fe !important;
            color: #4f46e5 !important;
        }

        /* ── UI kit v2 ───────────────────────────────────────────────────
           Shared by the page_kit helpers. st.metric(border=True) draws its own
           1px border; this sets the radius, surface and depth so a figure in a
           card looks the same on every page. Sits after the Command Bar marker,
           outside every block the legibility tests slice. */
        [data-testid="stMetric"] {
            background: var(--c-surface) !important;
            border-radius: var(--r-lg) !important;
            box-shadow: var(--sh-1) !important;
            min-width: 0;
        }
        [data-testid="stMetric"] [data-testid="stMetricValue"] {
            font-variant-numeric: tabular-nums;
        }
        [class*="st-key-mrow_"] { align-items: stretch; }
        [class*="st-key-mrow_"] > [data-testid="stMetric"],
        [class*="st-key-mrow_"] > div { flex: 1 1 180px; min-width: 0; }

        .pg-callout {
            border-left: 3px solid var(--c-border-strong);
            background: var(--c-bg-subtle);
            border-radius: var(--r-md);
            padding: 10px 14px;
            margin: 0;
            font-size: var(--fs-13);
            line-height: 1.45;
            color: var(--c-text-secondary);
        }
        .pg-callout b { display: block; font-size: var(--fs-13); color: var(--c-text-primary); }
        .pg-callout span { display: block; margin-top: 4px; }
        .pg-callout.up { border-left-color: var(--c-bull); background: var(--c-bull-tint); }
        .pg-callout.up b { color: var(--c-bull); }
        .pg-callout.down { border-left-color: var(--c-bear); background: var(--c-bear-tint); }
        .pg-callout.down b { color: var(--c-bear); }
        .pg-callout.warn { border-left-color: var(--c-caution); background: var(--c-caution-tint); }
        .pg-callout.warn b { color: var(--c-caution-ink); }

        a.pg-link {
            display: inline-flex; align-items: center; gap: 6px;
            padding: 8px 14px; border: 1px solid var(--c-border-strong);
            border-radius: var(--r-md); background: var(--c-surface);
            color: var(--c-accent-text) !important; font-size: var(--fs-13);
            font-weight: 600; text-decoration: none;
        }
        a.pg-link:hover { border-color: var(--c-accent); background: var(--c-accent-tint); }

        [data-testid="stDialog"] [role="dialog"] {
            border-radius: var(--r-xl) !important;
            box-shadow: var(--sh-pop) !important;
        }

        /* ── Metric Containers ── */
        [data-testid="metric-container"] {
            background-color: #ffffff !important;
            border: 1px solid #E3E6EB !important;
            border-radius: 14px !important;
            padding: 1.1rem 1.3rem !important;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.04), 0 1px 2px rgba(0, 0, 0, 0.02) !important;
            transition: transform 0.1s ease, box-shadow 0.1s ease;
        }

        [data-testid="metric-container"]:hover {
            border-color: #D0D5DD !important;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.06), 0 2px 4px -1px rgba(0, 0, 0, 0.04) !important;
        }

        [data-testid="stMetricLabel"] {
            font-family: var(--font-mono) !important;
            font-size: 0.72rem !important;
            font-weight: 600 !important;
            text-transform: uppercase !important;
            letter-spacing: 0.08em !important;
            color: #5E6878 !important;
        }

        [data-testid="stMetricValue"] {
            font-family: var(--font-mono) !important;
            font-size: 1.6rem !important;
            font-weight: 700 !important;
            color: #0E1726 !important;
        }

        [data-testid="stMetricDelta"] {
            font-family: var(--font-mono) !important;
            font-size: 0.78rem !important;
            font-weight: 600 !important;
        }

        /* ── Navigation Tabs ── */
        [data-baseweb="tab-list"] {
            background-color: #F4F5F8 !important;
            border: 1px solid #E3E6EB !important;
            border-radius: 12px !important;
            padding: 0.35rem !important;
            gap: 0.25rem !important;
            margin-bottom: 1.4rem !important;
        }

        [data-baseweb="tab"] {
            border-radius: 8px !important;
            padding: 0.45rem 1rem !important;
            font-family: var(--font-mono) !important;
            font-size: 0.8rem !important;
            font-weight: 600 !important;
            color: #5E6878 !important;
            border: none !important;
            transition: all 0.15s ease !important;
        }

        [data-baseweb="tab"]:hover {
            color: #0E1726 !important;
            background-color: #F1F3F6 !important;
        }

        [aria-selected="true"][data-baseweb="tab"] {
            background-color: #ffffff !important;
            color: #4f46e5 !important;
            border: 1px solid #E3E6EB !important;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05) !important;
        }

        [data-baseweb="tab-highlight"], [data-baseweb="tab-border"] {
            display: none !important;
        }


        /* ── Financial High-Density DataTables ── */
        [data-testid="stDataFrame"] {
            border: 1px solid #E3E6EB !important;
            border-radius: 12px !important;
            overflow: hidden !important;
            background-color: #ffffff !important;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03) !important;
        }

        /* ── Form Inputs & Buttons ── */
        .stButton > button {
            background-color: #ffffff !important;
            border: 1px solid #D0D5DD !important;
            border-radius: 8px !important;
            color: #3C4657 !important;
            font-size: 0.84rem !important;
            font-weight: 600 !important;
            padding: 0.4rem 0.9rem !important;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.03) !important;
            transition: all 0.15s ease !important;
        }

        .stButton > button:hover {
            border-color: #4f46e5 !important;
            color: #4f46e5 !important;
            background-color: #F4F5F8 !important;
        }

        /* The page's one main action: indigo, per the design. */
        .stButton > button[kind="primary"] {
            background-color: #4F46E5 !important; border-color: #4F46E5 !important; color: #FFFFFF !important;
        }
        .stButton > button[kind="primary"]:hover {
            background-color: #4338CA !important; border-color: #4338CA !important; color: #FFFFFF !important;
        }

        [data-testid="stDownloadButton"] button {
            background-color: #FFFFFF !important;
            color: #0E1726 !important;
            border: 1px solid #D0D5DD !important;
            font-weight: 600 !important;
            border-radius: 10px !important;
            min-height: 40px !important;
        }

        [data-testid="stDownloadButton"] button:hover {
            background-color: #F4F5F8 !important;
            border-color: #4F46E5 !important;
            color: #4338CA !important;
        }

        [data-testid="stDownloadButton"] button[kind="primary"] {
            background-color: #4F46E5 !important; color: #FFFFFF !important; border-color: #4F46E5 !important;
        }
        [data-testid="stDownloadButton"] button[kind="primary"]:hover {
            background-color: #4338CA !important; color: #FFFFFF !important;
        }
        /* A page-wide paragraph colour reached into primary buttons and left
           their labels grey on indigo. */
        [data-testid="stBaseButton-primary"] p,
        [data-testid="stBaseButton-primary"] span { color: #FFFFFF !important; }
        /* A form's submit button (the Backtest page's Apply) is its own kind,
           stBaseButton-primaryFormSubmit, and the rules above missed it: its
           label read dark on indigo (owner's phone, 9 Oct 2026). */
        [data-testid="stBaseButton-primaryFormSubmit"] {
            background-color: #4F46E5 !important; border-color: #4F46E5 !important; color: #FFFFFF !important;
        }
        [data-testid="stBaseButton-primaryFormSubmit"]:hover {
            background-color: #4338CA !important; border-color: #4338CA !important; color: #FFFFFF !important;
        }
        [data-testid="stBaseButton-primaryFormSubmit"] p,
        [data-testid="stBaseButton-primaryFormSubmit"] span { color: #FFFFFF !important; }

        [data-baseweb="select"] > div {
            background-color: #ffffff !important;
            border: 1px solid #D0D5DD !important;
            border-radius: 8px !important;
            color: #0E1726 !important;
        }

        [data-baseweb="input"] input, [data-baseweb="textarea"] textarea {
            background-color: #ffffff !important;
            border: 1px solid #D0D5DD !important;
            color: #0E1726 !important;
            border-radius: 8px !important;
            font-size: 0.85rem !important;
        }

        [data-baseweb="input"] input:focus, [data-baseweb="textarea"] textarea:focus {
            border-color: #4f46e5 !important;
            box-shadow: 0 0 0 1px #4f46e5 !important;
        }

        [data-testid="stExpander"] {
            background-color: #ffffff !important;
            border: 1px solid #E3E6EB !important;
            border-radius: 12px !important;
            box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02) !important;
            margin-bottom: 0.8rem !important;
        }

        [data-testid="stExpander"] summary {
            font-size: 0.86rem !important;
            font-weight: 600 !important;
            color: #1F2A3A !important;
        }

        [data-testid="stSlider"] [role="slider"] {
            background-color: #4f46e5 !important;
            border-color: #4f46e5 !important;
        }

        hr {
            border-color: #F1F3F6 !important;
            margin: 1.2rem 0 !important;
        }
        </style>
        """),
        unsafe_allow_html=True,
    )


def _spark_window_key(sub_prices: pd.DataFrame) -> str:
    """Fingerprint the 60-session window the sparklines are drawn from.

    Same shape as src/engine/pipeline.frame_memo_key and for the same
    reason: within a trading day the window's last date and shape do not
    change, only the numbers in the final row do, so hashing that row is what
    makes an intraday refresh miss the cache instead of serving this morning's
    lines under this afternoon's prices. Everything before the last row is
    settled history, and a change there moves the shape or the date anyway.
    """
    try:
        last = pd.to_numeric(sub_prices.iloc[-1], errors="coerce").to_numpy(dtype="float64")
        digest = hashlib.md5(last.tobytes()).hexdigest()[:12]
        return f"{sub_prices.index[-1]}_{sub_prices.shape[0]}x{sub_prices.shape[1]}_{digest}"
    except Exception:
        # Un-fingerprintable means un-cacheable: return a value that never
        # repeats, so the map is recomputed rather than wrongly reused.
        return f"nokey_{id(sub_prices)}_{time.time()}"


# ── Column headers ──────────────────────────────────────────────────────────
# Module level, and the ONLY place the table's shape is written down. The
# density labels used to carry their own hand-typed column counts -- "Full
# Quant (35)" over a table that emitted 36 -- because a second copy of a
# number is a copy that drifts. `screener_column_count` now reads the count
# back out of these very blocks, so a column added here reaches the label
# with no second edit.
# ── Percentage units ────────────────────────────────────────────────────────
# Two conventions meet in these tables. Some columns carry a FRACTION (0.0734
# means +7.34%); others carry a value already multiplied by 100 (7.34 means
# +7.34%). The renderer used to tell them apart by magnitude -- "<= 1.0, so it
# must be a fraction" -- and magnitude cannot recover a unit. It failed on
# precisely the rows that matter most:
#
#   Return % = 1.31 on a stock that gained 131%  ->  printed "+1.3%"
#   Max DD 3M = -0.8, an 0.8% drawdown           ->  printed "-80.0%"
#
# so a multibagger read as a rounding error, and the blotter's entry and exit
# prices refused to reconcile with the return beside them. The unit is a
# property of the column, so it is declared per column here. Any percentage
# column that is not declared now fails loudly instead of guessing from its
# magnitude.
FRACTION_PERCENT_COLUMNS: frozenset[str] = frozenset({
    # Backtest — trades, periods and stats
    "RETURN %", "MTD %", "STRATEGY NET", "BENCHMARK", "ALPHA VS BENCHMARK",
    "TOTAL RETURN", "GROSS RETURN", "NET RETURN", "ALPHA", "OUTPERFORM",
    "CAGR", "ANN RETURN", "WIN RATE", "MAX DRAWDOWN", "MAX DD",
    "6M NET RETURN", "6M ALPHA",
    "% OF 52W HIGH START", "% OF 52W HIGH END",
    # Shares of a group (sector cards) and a corporate-action move (close / previous - 1).
    "EMA %", "NEAR %", "PASS %", "MOVE %",
})

SCALED_PERCENT_COLUMNS: frozenset[str] = frozenset({
    # Already multiplied by 100 at source
    "TURNOVER", "TURNOVER %", "COST DRAG %", "WEIGHT %",
    "% HIGH", "% ATH", "% 50 EMA", "% 20 EMA", "% 52W HIGH",
    "ATR %", "PERSISTENCE", "FFILL %",
    "DEL %", "DEL% 20D AVG", "DEL% PREV20D",
    "DAY CHG %", "PRICE_CHG_%", "P&L %", "DAY P&L %", "TARGET WEIGHT %", "WEIGHT DRIFT %",
    # The backtest's live book stores the entry weight x 100 (backtester: w * 100);
    # undeclared, it raised on the Backtest page's current book (7 Oct 2026).
    "ENTRY WEIGHT %",
    # exit_watch copies "% 50 EMA" and "% High", already x 100.
    "VS 50 EMA %", "VS 52W HIGH %",
})

# Window-parameterised families, so adding a horizon to MOMENTUM_WINDOWS does
# not silently reintroduce the guess for that column.
_FRACTION_PATTERNS = (re.compile(r"^\d+M RETURN$"),)
_SCALED_PATTERNS = (re.compile(r"^MAX DD \d+M$"),)


def percent_unit(column: object) -> str | None:
    """"fraction", "scaled", or None when the column has not declared a unit."""
    name = str(column).strip().upper()
    if name in FRACTION_PERCENT_COLUMNS or any(
        p.match(name) for p in _FRACTION_PATTERNS
    ):
        return "fraction"
    if name in SCALED_PERCENT_COLUMNS or any(p.match(name) for p in _SCALED_PATTERNS):
        return "scaled"
    return None


# Per-share prices are quoted to the paisa. Rounding them to the rupee -- which
# is what "two decimals only below 100" did to every stock above 100 rupees --
# means an entry of 157.65 and an exit of 168.40 print as 158 and 168, and the
# +6.8% beside them looks wrong because, at the precision shown, it is.
_PER_SHARE_PRICE_KEYS = ("CMP", "PRICE", "STOP LOSS", "CHAND", "ENTRY", "EXIT")
_AGGREGATE_MONEY_KEYS = ("VALUE", "CAPITAL", "MCAP", "P&L", "DAY P&L")


def render_saas_table(
    df: pd.DataFrame,
    max_height: int | None = None,
    variant: str = "default",
) -> None:
    """Render a borderless SaaS table with optional page-specific presentation variants."""
    if df.empty:
        st.info("No data available to display.")
        return

    n_rows = len(df)
    if max_height is None:
        table_h = min(600, (n_rows * 44) + 48)
    else:
        table_h = max_height

    headers_html = []
    for col in df.columns:
        c_str = str(col).upper()
        if any(
            w in c_str
            for w in [
                "RANK",
                "DELTA",
                "Δ",
                "GAP",
                "STATUS",
                "STOCKS",
                "COUNT",
                "HOLDINGS",
                "TRADES",
                "IN ALL TOP",
                "QUADRANT",
                "ACTION",
            ]
        ):
            headers_html.append(f'<th class="th-center">{_esc(str(col))}</th>')
        elif any(
            w in c_str
            for w in [
                "SYMBOL",
                "INDUSTRY",
                "SECTOR",
                "STRATEGY",
                "TAXONOMY",
                "DESCRIPTION",
                "NAME",
                "COMPANY",
                "PERIOD",
                "MODEL",
                "OBJECTIVE",
                "REGIME",
                "WINDOW",
                "REASON",
                "MONTH",
            ]
        ):
            headers_html.append(f'<th class="th-left">{_esc(str(col))}</th>')
        else:
            headers_html.append(f'<th class="th-right">{_esc(str(col))}</th>')

    portfolio_class = "portfolio" if variant == "portfolio" else ""
    rows_html = []
    # Plain dicts rather than iterrows(): a Series per row is ~3.4x the cost
    # over a large frame and nothing here needs one. Unlike the screener table
    # this renderer takes arbitrary frames, some of which are homogeneously
    # numeric -- where iterrows() hands back numpy scalars rather than boxing
    # to native Python. That is safe here only because the value branches below
    # test (int, np.integer) and (float, np.floating), so a native int and a
    # numpy int64 land in the same branch either way. Keep those numpy arms if
    # this loop is ever rewritten.
    for row in df.to_dict("records"):
        cells_html = []
        for col in df.columns:
            val = row[col]
            c_str = str(col).upper()
            portfolio_sign_class = ""
            if variant == "portfolio" and c_str in {"P&L (₹)", "P&L %", "DAY P&L (₹)", "DAY P&L %"}:
                portfolio_sign_class = "portfolio-pos" if val > 0 else ("portfolio-neg" if val < 0 else "portfolio-flat")

            if pd.isna(val) or val is None or str(val).strip() in ("", "nan", "None"):
                cells_html.append('<td class="td-center text-muted">—</td>')
                continue

            # Special column formatting
            if "SYMBOL" in c_str:
                cells_html.append(
                    f'<td class="td-left"><span class="stock-ticker">{_esc(str(val))}</span></td>'
                )
            elif "QUADRANT" in c_str:
                q_val = str(val).capitalize()
                q_badge = {
                    "Leading": "badge-green",
                    "Weakening": "badge-yellow",
                    "Lagging": "badge-red",
                    "Improving": "badge-blue",
                }.get(q_val, "badge-neutral")
                q_ico = {
                    "Leading": "🟢",
                    "Weakening": "🟡",
                    "Lagging": "🔴",
                    "Improving": "🔵",
                }.get(q_val, "⚪")
                cells_html.append(
                    f'<td class="td-center"><span class="badge-pill {q_badge}">{q_ico} {_esc(q_val)}</span></td>'
                )
            elif "STATUS" in c_str:
                status_str = str(val).strip()
                status_class = (
                    "badge-green" if status_str.upper() in {"HELD", "OPEN", "ACTIVE"}
                    else ("badge-red" if status_str.upper() in {"CLOSED", "SOLD"}
                          else "badge-neutral")
                )
                cells_html.append(
                    f'<td class="td-center"><span class="badge-pill {status_class}">{_esc(status_str)}</span></td>'
                )
            elif "ACTION" in c_str:
                # Every Action column is a record of trades, so it says what
                # happened: Bought / Sold / Held (owner, 12 Oct 2026). Plans
                # (the Actions page, filters) say Buy / Sell / Hold. The
                # engine's own codes ("🟢 BUY (Entry)", "⚪ HELD") are unchanged.
                act_str = str(val).upper()
                if "BUY" in act_str or "BOUGHT" in act_str:
                    cells_html.append(
                        '<td class="td-center"><span class="badge-pill badge-green">🟢 Bought</span></td>'
                    )
                elif "SELL" in act_str or "SOLD" in act_str:
                    cells_html.append(
                        '<td class="td-center"><span class="badge-pill badge-red">🔴 Sold</span></td>'
                    )
                elif any(w in act_str for w in ("HOLD", "HELD", "RETAINED")):
                    cells_html.append(
                        '<td class="td-center"><span class="badge-pill badge-neutral">⚪ Held</span></td>'
                    )
                else:
                    cells_html.append(
                        f'<td class="td-center"><span class="badge-pill badge-neutral">{_esc(str(val))}</span></td>'
                    )
            elif isinstance(val, (int, np.integer)) and not isinstance(val, bool):
                if any(w in c_str for w in ["DELTA", "Δ"]):
                    clr = (
                        "badge-green"
                        if val > 0
                        else ("badge-red" if val < 0 else "badge-neutral")
                    )
                    symbol = "▲" if val > 0 else ("▼" if val < 0 else "—")
                    cells_html.append(
                        f'<td class="td-center"><span class="badge-pill {clr}">{symbol} {abs(int(val))}</span></td>'
                    )
                elif any(
                    w in c_str
                    for w in ["RANK", "STOCKS", "COUNT", "HOLDINGS", "TRADES"]
                ):
                    cells_html.append(
                        f'<td class="td-center"><strong>{int(val)}</strong></td>'
                    )
                else:
                    cells_html.append(f'<td class="td-right">{int(val):,}</td>')
            elif isinstance(val, (float, np.floating)):
                if any(w in c_str for w in ["DELTA", "Δ"]):
                    clr = (
                        "badge-green"
                        if val > 0
                        else ("badge-red" if val < 0 else "badge-neutral")
                    )
                    symbol = "▲" if val > 0 else ("▼" if val < 0 else "—")
                    cells_html.append(
                        f'<td class="td-center"><span class="badge-pill {clr}">{symbol} {abs(round(val))}</span></td>'
                    )
                elif any(
                    w in c_str
                    for w in ["RANK", "STOCKS", "COUNT", "HOLDINGS", "TRADES"]
                ):
                    cells_html.append(
                        f'<td class="td-center"><strong>{round(val)}</strong></td>'
                    )
                # Whole-number counts that arrive as float (a NaN anywhere in
                # the column makes pandas store it that way): "3.00 buys" and
                # "42.00 days" read as measurements, not counts.
                elif any(w in c_str for w in ["BUYS", "SELLS", "(DAYS)", "SHARES"]) and float(val).is_integer():
                    cells_html.append(f'<td class="td-right">{int(val):,}</td>')
                # 1. Returns & Alphas & Monthly returns (e.g. M-1, M-2, Strategy Net, Benchmark)
                elif (
                    any(
                        w in c_str
                        for w in [
                            "RETURN",
                            "RET",
                            "P&L %",
                            "MTD",
                            "ALPHA",
                            "CAGR",
                            "DAY CHG",
                            "NET",
                            "BENCHMARK",
                        ]
                    )
                    or c_str.startswith("M-")
                    or "MONTH" in c_str
                ):
                    clr = (
                        "ret-pos"
                        if val > 0
                        else ("ret-neg" if val < 0 else "text-muted")
                    )
                    unit = percent_unit(col)
                    if unit is None:
                        raise ValueError(
                            f"Undeclared percentage unit for column {col!r}; "
                            "add it to FRACTION_PERCENT_COLUMNS or SCALED_PERCENT_COLUMNS."
                        )
                    as_fraction = unit == "fraction"
                    if as_fraction:
                        combined_clr = portfolio_sign_class or clr
                        cells_html.append(
                            f'<td class="td-right {combined_clr}"><strong>{val:+.1%}</strong></td>'
                        )
                    else:
                        combined_clr = portfolio_sign_class or clr
                        cells_html.append(
                            f'<td class="td-right {combined_clr}"><strong>{val:+.1f}%</strong></td>'
                        )
                # 2. Percentages (e.g. Del %, Win Rate, Turnover %, Cost Drag %, ATR %, Weight %)
                elif any(
                    w in c_str
                    for w in [
                        "%",
                        "DD",
                        "DRAWDOWN",
                        "WIN RATE",
                        "TURNOVER",
                        "DEL",
                        "DRAG",
                        "FFILL",
                        "HIGH",
                        "EMA",
                        "WEIGHT",
                    ]
                ):
                    clr = (
                        "ret-neg"
                        if any(w in c_str for w in ["DD", "DRAWDOWN", "DRAG"])
                        else ""
                    )
                    unit = percent_unit(col)
                    if unit is None:
                        raise ValueError(
                            f"Undeclared percentage unit for column {col!r}; "
                            "add it to FRACTION_PERCENT_COLUMNS or SCALED_PERCENT_COLUMNS."
                        )
                    as_fraction = unit == "fraction"
                    if as_fraction:
                        cells_html.append(f'<td class="td-right {clr}">{val:.1%}</td>')
                    else:
                        cells_html.append(f'<td class="td-right {clr}">{val:.1f}%</td>')
                # 3. Currency / Prices (e.g. CMP, Entry Price, Exit Price, Value, Capital)
                elif any(
                    w in c_str for w in _PER_SHARE_PRICE_KEYS + _AGGREGATE_MONEY_KEYS
                ):
                    if any(w in c_str for w in _PER_SHARE_PRICE_KEYS):
                        cells_html.append(
                            f'<td class="td-right">₹{float(val):,.2f}</td>'
                        )
                    else:
                        cells_html.append(
                            f'<td class="td-right {portfolio_sign_class}">₹{float(val):,.0f}</td>'
                        )
                # 4. Multipliers & Ratios (e.g. Sharpe, Sortino, Calmar, Beta, Surge, Multiplier, Profit Factor, RS_Ratio, RS_Momentum)
                elif any(
                    w in c_str
                    for w in [
                        "SHARPE",
                        "SORTINO",
                        "CALMAR",
                                                "RATIO",
                        "BETA",
                        "SURGE",
                        "MULTIPLIER",
                        "FACTOR",
                        "PERSISTENCE",
                        "RS_RATIO",
                        "RS_MOMENTUM",
                    ]
                ):
                    if any(w in c_str for w in ["SURGE", "MULTIPLIER", "FACTOR"]):
                        cells_html.append(
                            f'<td class="td-right td-sharpe">{float(val):.2f}×</td>'
                        )
                    else:
                        cells_html.append(
                            f'<td class="td-right td-sharpe">{float(val):.2f}</td>'
                        )
                # 5. Generic Float Fallback (Guarantees clean 2 decimals max!)
                else:
                    cells_html.append(f'<td class="td-right">{val:.2f}</td>')
            elif any(w in c_str for w in ["INDUSTRY", "SECTOR"]):
                cells_html.append(f'<td class="td-left td-sector">{_esc(str(val))}</td>')
            elif isinstance(val, bool):
                cells_html.append(
                    f'<td class="td-center">{"🟢 Yes" if val else "⚪ No"}</td>'
                )
            else:
                cells_html.append(f'<td class="td-left">{_esc(str(val))}</td>')

        rows_html.append(f'<tr class="screener-row">{"".join(cells_html)}</tr>')

    saas_page_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Geist:wght@400..700&family=Geist+Mono:wght@400..700&display=swap" rel="stylesheet">
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
    background: transparent;
    font-family: 'Geist', -apple-system, BlinkMacSystemFont, sans-serif;
    color: #0E1726;
    -webkit-font-smoothing: antialiased;
    padding: 2px;
}}
.saas-table-wrapper {{
    width: 100%;
    max-height: {table_h}px;
    overflow: auto;
    border: 1px solid #E3E6EB;
    border-radius: 10px;
    background: #ffffff;
    box-shadow: 0 1px 2px rgba(0,0,0,0.02);
    scrollbar-width: none !important;
    -ms-overflow-style: none !important;
}}
.saas-table-wrapper::-webkit-scrollbar,
body::-webkit-scrollbar,
*::-webkit-scrollbar {{
    width: 0px !important;
    height: 0px !important;
    display: none !important;
    background: transparent !important;
}}
.saas-table {{
    width: max-content;
    min-width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    font-family: 'Geist', -apple-system, BlinkMacSystemFont, sans-serif;
    font-size: 13.5px;
    color: #0E1726;
    white-space: nowrap;
}}
.saas-table thead tr th {{
    position: sticky;
    top: 0;
    z-index: 10;
    background: #F4F5F8;
    color: #5E6878;
    font-family: 'Geist', sans-serif;
    font-size: 12px;
    font-weight: 600;
    height: 42px;
    padding: 0 10px;
    border-bottom: 1px solid #E3E6EB;
    border-left: none;
    border-right: none;
    cursor: pointer;
    user-select: none;
    transition: background-color 0.15s ease, color 0.15s ease;
}}
.saas-table thead tr th:hover {{
    background-color: #E3E6EB !important;
    color: #0E1726 !important;
}}
.saas-table thead tr th.th-left {{ text-align: left; }}
.saas-table thead tr th.th-center {{ text-align: center; }}
.saas-table thead tr th.th-right {{ text-align: right; }}
.sort-indicator {{
    display: inline-block;
    margin-left: 4px;
    font-size: 8.5px;
    color: #4f46e5;
    vertical-align: middle;
}}

.saas-table-wrapper {{
    -webkit-overflow-scrolling: touch;
    overscroll-behavior-x: contain;
    touch-action: pan-x pan-y;
}}

/* Portfolio: sign colours only; type weight follows the other tables. */
.saas-table-wrapper.portfolio .portfolio-pos {{ color: #067647 !important; }}
.saas-table-wrapper.portfolio .portfolio-neg {{ color: #912018 !important; }}
.saas-table-wrapper.portfolio .portfolio-flat {{ color: #5E6878 !important; }}
@media (max-width: 640px) {{
    .saas-table thead tr th {{
        padding: 0 8px;
    }}
    .saas-table td {{
        padding: 0 8px;
    }}
    .saas-table th:first-child,
    .saas-table td:first-child {{
        position: sticky;
        left: 0;
        z-index: 12;
        background: #FFFFFF;
        box-shadow: 6px 0 8px -8px rgba(14, 23, 38, 0.35);
    }}
    .saas-table thead th:first-child {{
        background: #F4F5F8;
    }}
}}
.saas-table tbody tr.screener-row {{
    border-bottom: 1px solid #F1F3F6;
    transition: background-color 0.12s ease;
}}
.saas-table tbody tr.screener-row:hover td {{
    background-color: #F4F5F8 !important;
}}
.saas-table td {{
    height: 44px;
    padding: 0 10px;
    vertical-align: middle;
    font-family: 'Geist', sans-serif;
    font-size: 13.5px;
    border-bottom: 1px solid #EDEFF3;
    border-left: none;
    border-right: none;
    background: #ffffff;
}}
.saas-table td.td-left {{ text-align: left; }}
.saas-table td.td-center {{ text-align: center; }}
.saas-table td.td-right {{ text-align: right; font-family: 'Geist Mono', ui-monospace, monospace; font-variant-numeric: tabular-nums; }}
.saas-table td.td-sector {{
    font-family: 'Geist', sans-serif;
    color: #3C4657;
    max-width: 180px;
    overflow: hidden;
    text-overflow: ellipsis;
}}
.stock-ticker {{
    font-family: 'Geist', sans-serif;
    font-weight: 650;
    font-size: 14px;
    color: #0E1726;
}}
.badge-pill {{
    display: inline-block;
    font-family: 'Geist Mono', monospace;
    font-size: 12px;
    font-weight: 600;
    padding: 2px 7px;
    border-radius: 7px;
}}
.badge-green {{ background: #E8F5EE; color: #067647; border: 1px solid #bbf7d0; }}
.badge-yellow {{ background: #fefce8; color: #a16207; border: 1px solid #fef08a; }}
.badge-red {{ background: #FDEDEB; color: #912018; border: 1px solid #F3C7C1; }}
.badge-blue {{ background: #eff6ff; color: #1d4ed8; border: 1px solid #bfdbfe; }}
.badge-neutral {{ background: #F4F5F8; color: #5E6878; border: 1px solid #E3E6EB; }}
.ret-pos {{ color: #067647; font-weight: 700; }}
.ret-neg {{ color: #912018; font-weight: 700; }}
.td-sharpe {{ color: #067647; font-weight: 600; }}
.text-muted {{ color: #667080; }}
</style>
</head>
<body>
<div class="saas-table-wrapper {portfolio_class}">
    <table class="saas-table">
        <thead>
            <tr>{"".join(headers_html)}</tr>
        </thead>
        <tbody>
            {"".join(rows_html)}
        </tbody>
    </table>
</div>
<script>
document.addEventListener('DOMContentLoaded', function() {{
    const table = document.querySelector('.saas-table');
    if (!table) return;
    const thList = table.querySelectorAll('thead tr th');
    const tbody = table.querySelector('tbody');

    thList.forEach((th, colIdx) => {{
        let currentDir = 'none';

        th.addEventListener('click', function() {{
            currentDir = (currentDir === 'asc') ? 'desc' : 'asc';

            thList.forEach(otherTh => {{
                const icon = otherTh.querySelector('.sort-indicator');
                if (icon) icon.remove();
                if (otherTh !== th) otherTh.removeAttribute('data-sort-dir');
            }});

            th.setAttribute('data-sort-dir', currentDir);
            const ind = document.createElement('span');
            ind.className = 'sort-indicator';
            ind.textContent = currentDir === 'asc' ? ' ▲' : ' ▼';
            th.appendChild(ind);

            const rows = Array.from(tbody.querySelectorAll('tr.screener-row'));
            rows.sort((rowA, rowB) => {{
                const cellA = rowA.children[colIdx];
                const cellB = rowB.children[colIdx];
                if (!cellA || !cellB) return 0;

                let txtA = cellA.innerText.trim();
                let txtB = cellB.innerText.trim();

                // Blanks sink to the bottom in both directions. Two blanks
                // compare EQUAL: returning 1 for both orders made the
                // comparator inconsistent, and the browser's sort may then
                // scramble the rows.
                const blankA = (txtA === '—' || txtA === '');
                const blankB = (txtB === '—' || txtB === '');
                if (blankA || blankB) return (blankA === blankB) ? 0 : (blankA ? 1 : -1);

                if (txtA.startsWith('▲') || txtA.startsWith('▼') || txtA.startsWith('—')) {{
                    let numA = parseFloat(txtA.replace(/[▲▼—\\s]/g, '')) * (txtA.startsWith('▼') ? -1 : 1);
                    let numB = parseFloat(txtB.replace(/[▲▼—\\s]/g, '')) * (txtB.startsWith('▼') ? -1 : 1);
                    if (!isNaN(numA) && !isNaN(numB)) {{
                        return currentDir === 'asc' ? (numA - numB) : (numB - numA);
                    }}
                }}

                let cleanA = txtA.replace(/[₹,×%+#]/g, '').trim();
                let cleanB = txtB.replace(/[₹,×%+#]/g, '').trim();
                let valA = parseFloat(cleanA);
                let valB = parseFloat(cleanB);

                if (!isNaN(valA) && !isNaN(valB) && cleanA !== '' && cleanB !== '') {{
                    return currentDir === 'asc' ? (valA - valB) : (valB - valA);
                }}

                return currentDir === 'asc' ? txtA.localeCompare(txtB) : txtB.localeCompare(txtA);
            }});

            rows.forEach(r => tbody.appendChild(r));
        }});
    }});
}});
</script>
</body>
</html>"""
    st.iframe(saas_page_html, height=table_h + 10)