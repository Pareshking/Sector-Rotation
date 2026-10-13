"""The parts every page is built from, so they all read alike.

The Screener set the pattern: a header that says what the page is for, one
strip of readings in plain words, cards for each block, at most one amber note
placed above what it qualifies. These helpers draw exactly that, with the
classes the shared stylesheet in src/ui/theme.py already styles.
"""
from __future__ import annotations

import html
import math
from urllib.parse import quote
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Literal

import pandas as pd
import streamlit as st


@dataclass(frozen=True)
class Reading:
    """One tile of a readings strip: label, figure, and what it means."""

    label: str
    value: str
    note: str = ""
    tone: str = ""  # "", "up", "down" or "warn"


def page_head(title: str, sub: str, *, actions: bool = False):
    """Title and one plain sentence. With actions=True, returns a container on
    the right for the page's main buttons (a download, a picker)."""
    head = (f'<div class="scr-head"><h1>{html.escape(title)}</h1>'
            f'<p>{html.escape(sub)}</p></div>')
    if not actions:
        st.html(head)
        return None
    left, right = st.columns([2.2, 1.8], vertical_alignment="bottom")
    with left:
        st.html(head)
    return right.container(horizontal=True, horizontal_alignment="right",
                           key=f"pg_actions_{_slug(title)}")


def _name_class(value: str) -> str:
    """A tile value that is a name (an industry), not a figure, reads smaller."""
    return " ms-name" if sum(c.isalpha() for c in value) > 8 else ""


def readings(tiles: list[Reading], label: str) -> None:
    """The strip of big figures under the header."""
    cells = "".join(
        f'<div class="ms-tile"><span class="ms-k">{html.escape(t.label)}</span>'
        f'<span class="ms-v {t.tone}{_name_class(t.value)}" title="{html.escape(t.value)}">'
        f'{html.escape(t.value)}</span>'
        + (f'<span class="ms-s">{html.escape(t.note)}</span>' if t.note else "")
        + "</div>"
        for t in tiles
    )
    st.html(f'<section class="mkt-strip pg-strip" aria-label="{html.escape(label)}">{cells}</section>')


def note(lead: str, text: str = "") -> None:
    """The page's one amber note: a bold first line, then the detail."""
    st.html(f'<div class="pg-note" role="note"><b>{html.escape(lead)}</b>'
            + (f" {html.escape(text)}" if text else "") + "</div>")


@contextmanager
def card(title: str, key: str, aside: str = "") -> Iterator[None]:
    """A white card with a heading; anything drawn inside lands in it."""
    with st.container(key=f"pgcard_{key}"):
        st.html(f'<div class="pg-card-h"><h2>{html.escape(title)}</h2>'
                + (f'<span>{html.escape(aside)}</span>' if aside else "") + "</div>")
        yield


def bar_list(rows: list[tuple[str, float, str, bool]], scale: float) -> str:
    """Label, bar and figure per row. `scale` is the value of a full bar; a
    flagged row (at a cap, say) is drawn in amber."""
    out = []
    for label, value, shown, flagged in rows:
        w = 0.0 if scale <= 0 else max(0.0, min(100.0, value / scale * 100))
        out.append(
            f'<div class="pg-bar"><span class="pg-bar-l">{html.escape(label)}</span>'
            f'<span class="pg-bar-t"><i class="{"warn" if flagged else ""}" style="width:{w:.1f}%"></i></span>'
            f'<span class="pg-bar-v">{html.escape(shown)}</span></div>'
        )
    return f'<div class="pg-bars">{"".join(out)}</div>'


@dataclass(frozen=True)
class Metric:
    """One figure inside a card: a label, the figure, and optionally how it moved.

    `tone` is st.metric's delta_color: "normal" (up is good), "inverse" (up is
    bad) or "off" (no colour). Delta colour is the only judgement drawn here.
    """

    label: str
    value: str
    delta: str | None = None
    tone: Literal["normal", "inverse", "off"] = "off"
    help: str | None = None


def pct(x: float | None, signed: bool = True) -> str:
    """A fraction as a percentage for display; an em dash when it is not a
    finite number. Formatting only: no figure is computed here."""
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "\u2014"
    if not math.isfinite(v):
        return "\u2014"
    return f"{v:+.1%}" if signed else f"{v:.1%}"


def metric_tile(m: Metric) -> None:
    """One bordered figure. Every tile in the app is drawn by this call, so a
    figure has the same border, radius and delta colouring on every page."""
    st.metric(m.label, m.value, delta=m.delta, delta_color=m.tone, help=m.help,
              border=True)


def metric_row(tiles: list[Metric], key: str) -> None:
    """A row of bordered figures, aligned to one baseline. The row wraps on a
    phone instead of squeezing four columns into 360px."""
    with st.container(horizontal=True, gap="small", vertical_alignment="top",
                      key=f"mrow_{key}"):
        for m in tiles:
            metric_tile(m)


def toolbar(key: str):
    """The bar that holds a page's pickers and buttons, centred on one line."""
    return st.container(horizontal=True, vertical_alignment="center",
                        gap="small", key=f"tb_{key}")


def callout(title: str, body: str = "", tone: str = "muted") -> None:
    """A bordered, tinted block for a result that needs a word of explanation.
    Tones: "up", "down", "warn" or "muted". Text is escaped."""
    tone = tone if tone in ("up", "down", "warn", "muted") else "muted"
    st.html(f'<div class="pg-callout {tone}" role="note"><b>{html.escape(title)}</b>'
            + (f"<span>{html.escape(body)}</span>" if body else "") + "</div>")


_BADGE_COLOURS = {"up": "green", "down": "red", "warn": "orange", "info": "blue"}


def badge(label: str, tone: str = "") -> None:
    """A small status pill, drawn by Streamlit so it follows the theme."""
    st.badge(label, color=_BADGE_COLOURS.get(tone, "gray"))


def df_card(title: str, key: str, df: pd.DataFrame, *, column_config: dict | None = None,
            aside: str = "", height: int | str = "auto") -> None:
    """A card holding a configured st.dataframe, for tables that need no
    per-cell colouring or stock links (those stay on the HTML table renderers)."""
    with card(title, key, aside):
        st.dataframe(df, hide_index=True, width="stretch", height=height,
                     column_config=column_config or None)


def col_pct(label: str, *, fmt: str = "percent", help: str | None = None):
    """A column of fractions shown as percentages (0.123 -> 12.3%)."""
    return st.column_config.NumberColumn(label, format=fmt, help=help)


def col_rupee(label: str, *, help: str | None = None):
    """A column of rupee amounts, whole rupees with thousands separators."""
    return st.column_config.NumberColumn(label, format="\u20b9%,.0f", help=help)


def col_num(label: str, fmt: str = "%.2f", *, help: str | None = None):
    return st.column_config.NumberColumn(label, format=fmt, help=help)


def col_rank(label: str = "Rank", *, top: int = 750):
    """A rank drawn as a bar scaled to the list length (a longer bar is a
    larger rank number, i.e. a worse position)."""
    return st.column_config.ProgressColumn(label, min_value=0, max_value=top,
                                           format="%d")


# ── Data grids ────────────────────────────────────────────────────────────
# One column vocabulary for every st.dataframe that lists stocks, so Rank,
# returns and flags read the same in the Screener grid, the Portfolio grid and
# the stock dialogs. Units follow the ranking frame: returns are fractions
# (0.123 = 12.3%); "% High", "% 50 EMA", "Max DD" and the Portfolio's
# weight and P&L % columns are already in percent.
_FRACTION_COLS = ("1M Return", "3M Return", "6M Return", "9M Return", "12M Return")


def tradingview_url(symbol: str) -> str:
    """The symbol's chart on TradingView: an external site, so a new tab is right."""
    return "https://www.tradingview.com/chart/?symbol=" + quote(f"NSE:{symbol}", safe="")


def stock_grid_config(columns, *, score_range: tuple[float, float] | None = None) -> dict:
    """st.column_config entries for whichever of `columns` are stock columns."""
    cc = st.column_config
    known: dict = {
        "Rank": cc.NumberColumn("#", format="%d", width="small", pinned=True),
        "Current Rank": cc.NumberColumn("Rank", format="%d", width="small"),
        "Symbol": cc.TextColumn("Stock", width="medium", pinned=True),
        "Industry": cc.TextColumn("Industry"),
        "Sector / Industry": cc.TextColumn("Industry"),
        "Company": cc.TextColumn("Company"),
        "Indices": cc.TextColumn("Index"),
        "Rank Δ 1M": cc.NumberColumn("Rank Δ 1M", format="%+d", width="small"),
        "Rank Δ 3M": cc.NumberColumn("Rank Δ 3M", format="%+d", width="small"),
        "CMP": cc.NumberColumn("Price", format="₹%,.2f"),
        "Current Price": cc.NumberColumn("Price", format="₹%,.2f"),
        "% High": cc.NumberColumn("From 52W high", format="%.1f%%",
                                  help="Distance of the price from its 52-week high"),
        "% ATH": cc.NumberColumn("From ATH", format="%.1f%%"),
        "% 50 EMA": cc.NumberColumn("vs 50D EMA", format="%+.1f%%"),
        "Max DD 12M": cc.NumberColumn("Max DD 12M", format="%.1f%%"),
        "Market Cap (Cr)": cc.NumberColumn("Mkt cap (₹ Cr)", format="%,.0f"),
        "Above 50 EMA": cc.CheckboxColumn("Above 50D EMA", width="small"),
        "Near 52W High": cc.CheckboxColumn("Near 52W high", width="small"),
        "At ATH": cc.CheckboxColumn("At ATH", width="small"),
        "Score": cc.ProgressColumn("Score", format="%.2f",
                                   min_value=float(score_range[0]) if score_range else 0.0,
                                   max_value=float(score_range[1]) if score_range else 1.0),
        "Chart": cc.LinkColumn("Chart", display_text="TradingView ↗", width="small",
                               help="Opens the chart on TradingView in a new tab"),
        "Shares": cc.NumberColumn("Shares", format="%,d"),
        "P&L (₹)": cc.NumberColumn("P&L (₹)", format="₹%,.0f"),
        "Day P&L (₹)": cc.NumberColumn("Day P&L (₹)", format="₹%,.0f"),
        "Current Value (₹)": cc.NumberColumn("Value (₹)", format="₹%,.0f"),
        "Invested Value (₹)": cc.NumberColumn("Invested (₹)", format="₹%,.0f"),
        "Entry Price": cc.NumberColumn("Entry price", format="₹%,.2f"),
        "Holding Days": cc.NumberColumn("Days held", format="%d", width="small"),
    }
    for c in _FRACTION_COLS:
        known.setdefault(c, cc.NumberColumn(c, format="percent"))
    for c in ("1M Sharpe", "3M Sharpe", "6M Sharpe", "9M Sharpe", "12M Sharpe"):
        known[c] = cc.NumberColumn(c, format="%.2f", width="small")
    # Portfolio weights and P&L are percentages already; weight shows as a bar.
    known["Weight %"] = cc.ProgressColumn("Weight", format="%.1f%%", min_value=0.0,
                                          max_value=20.0)
    known["P&L %"] = cc.NumberColumn("P&L %", format="%+.1f%%")
    known["Target Weight %"] = cc.NumberColumn("Target", format="%.1f%%")
    known["Weight Drift %"] = cc.NumberColumn("Drift", format="%+.1f%%")
    known["Day P&L %"] = cc.NumberColumn("Day %", format="%+.1f%%")
    return {c: known[c] for c in columns if c in known}


def caption(text: str) -> None:
    st.html(f'<p class="pg-cap">{html.escape(text)}</p>')


def _slug(s: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in s).strip("_")


def equity_chart(
    dates,
    strategy: list[float],
    benchmark: list[float] | None,
    names: tuple[str, str] = ("Strategy", "Nifty 500"),
    key: str = "equity",
    fmt: str = "rupee",
    drawdown: list[float] | None = None,
) -> None:
    """Strategy against benchmark on real dates, with the drawdown under it when
    given. Values are drawn as passed (rupees, not growth factors), so a
    growth-factor formatter cannot multiply a portfolio value by 100. Hover for
    the date and every value."""
    from app.kit import lw_chart as lw

    if len(strategy) < 2:
        return
    series = [{"name": names[0], "type": "line", "color": lw.INDIGO, "fmt": fmt,
               "data": lw.series_points(dates, strategy)}]
    if benchmark:
        series.append({"name": names[1], "type": "line", "color": lw.GREY, "fmt": fmt,
                       "data": lw.series_points(dates, benchmark)})
    panes = [{"height": 300, "series": series}]
    if drawdown:
        panes.append({"height": 150, "series": [
            {"name": "Drawdown", "type": "baseline", "color": lw.RED, "negColor": lw.RED,
             "fmt": "pct", "data": lw.series_points(dates, drawdown, scale=100.0)}]})
    lw.render(panes, key=key)


def growth_chart(
    dates,
    strategy: list[float],
    benchmark: list[float] | None,
    names: tuple[str, str] = ("Strategy", "Nifty 500"),
    key: str = "growth",
) -> None:
    """Growth of 100: `strategy` and `benchmark` are growth factors (1.0 = the
    start), re-based to a start of 100 and drawn by equity_chart so the two
    charts cannot drift apart."""
    equity_chart(
        dates,
        [float(v) * 100.0 for v in strategy],
        None if not benchmark else [float(v) * 100.0 for v in benchmark],
        names=names, key=f"growth_{key}", fmt="num",
    )
