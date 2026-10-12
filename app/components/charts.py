"""Plotly figures for the rotation views.

Stage colour is consistent everywhere: Leading green, Weakening amber, Lagging
red, Improving blue — so a bar, a badge and a table dot all mean the same thing.
"""

from __future__ import annotations


import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.components.theme import STAGE_COLORS
from src.quantitative.analytics import repair_level_shifts as _repair

INK = "#0B1220"
MUTED = "#64748B"
GRID = "#EEF2F7"
LINE = "#E5E9F0"

_LAYOUT = dict(
    paper_bgcolor="white",
    plot_bgcolor="white",
    font=dict(family="Inter, ui-sans-serif, -apple-system, sans-serif", color=INK, size=12),
    margin=dict(l=10, r=12, t=16, b=10),
    hoverlabel=dict(
        bgcolor="white",
        bordercolor=LINE,
        font=dict(color=INK, family="Inter, sans-serif", size=12),
    ),
    dragmode=False,
)

# Diverging scale for returns. Distinct lightness at each end so the sign is
# still legible without relying on red/green discrimination alone.
RETURN_SCALE = [
    [0.0, "#9F1239"],
    [0.25, "#FB7185"],
    [0.5, "#F6F8FB"],
    [0.75, "#34D399"],
    [1.0, "#046C4E"],
]

CHART_CONFIG = {"displaylogo": False, "responsive": True, "displayModeBar": False}


def _finish(fig: go.Figure, height: int = 400) -> go.Figure:
    fig.update_layout(**_LAYOUT, height=height, autosize=True, uirevision="sector-rotation")
    fig.update_xaxes(showline=False, zeroline=False, gridcolor=GRID, tickfont=dict(size=11, color=MUTED))
    fig.update_yaxes(showline=False, zeroline=False, gridcolor=GRID, tickfont=dict(size=11, color=MUTED))
    return fig


def _stage_colour(stage: object) -> str:
    return STAGE_COLORS.get(str(stage), STAGE_COLORS["Insufficient Data"])


# --------------------------------------------------------------------------- #
# ranking + returns
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# single-exposure series
# --------------------------------------------------------------------------- #
def rs_trajectory(rs: pd.DataFrame, exposure: str, window: int = 104, height: int = 300) -> go.Figure:
    series = (
        pd.to_numeric(rs[exposure], errors="coerce").dropna().tail(window)
        if exposure in getattr(rs, "columns", [])
        else pd.Series(dtype=float)
    )
    fig = go.Figure()
    if series.empty:
        return _finish(fig, height)
    positive = series.clip(lower=0)
    negative = series.clip(upper=0)
    fig.add_trace(go.Scatter(x=series.index, y=positive, mode="lines", line=dict(width=0),
                             fill="tozeroy", fillcolor="rgba(5,150,105,.14)", hoverinfo="skip",
                             showlegend=False))
    fig.add_trace(go.Scatter(x=series.index, y=negative, mode="lines", line=dict(width=0),
                             fill="tozeroy", fillcolor="rgba(225,29,72,.12)", hoverinfo="skip",
                             showlegend=False))
    fig.add_trace(
        go.Scatter(
            x=series.index, y=series.values, mode="lines",
            line=dict(width=1.9, color="#334155"), showlegend=False,
            hovertemplate="%{x|%d %b %Y}<br>Mansfield RS %{y:+.2f}%<extra></extra>",
        )
    )
    fig.add_hline(y=0, line_dash="dot", line_color="#94A3B8", line_width=1)
    fig.update_layout(
        yaxis_title="Mansfield RS (%)",
        yaxis=dict(title_font=dict(size=11, color=MUTED), ticksuffix="%"),
    )
    return _finish(fig, height)


@st.cache_data(show_spinner=False)
def repair_level_shifts(series: pd.Series) -> tuple[pd.Series, list[dict[str, object]]]:
    """Cached wrapper over the shared split repair, plus what it corrected."""
    raw = pd.to_numeric(series, errors="coerce").dropna().astype(float).sort_index()
    fixed = _repair(raw)
    repairs: list[dict[str, object]] = []
    if len(raw) == len(fixed) and not raw.empty:
        ratio = (fixed / raw).round(6)
        changes = ratio.ne(ratio.shift()).fillna(False)
        for stamp in ratio.index[changes][1:]:
            repairs.append({"date": stamp, "factor": float(ratio.loc[stamp])})
    return fixed, repairs


def etf_comparison(prices: pd.DataFrame, symbols: list[str], height: int = 320) -> tuple[go.Figure, str]:
    """Rebase every ETF for one exposure onto their common overlapping window.

    Charting each ETF on its own full history made a 5-year series look far
    stronger than an 18-month one purely because of start date. Comparison is
    only meaningful from a shared origin.
    """
    cleaned: dict[str, pd.Series] = {}
    for symbol in symbols:
        if symbol in prices.columns:
            series, _ = repair_level_shifts(prices[symbol])
            if not series.empty:
                cleaned[symbol] = series
    fig = go.Figure()
    if not cleaned:
        return _finish(fig, height), ""

    start = max(series.index.min() for series in cleaned.values())
    end = min(series.index.max() for series in cleaned.values())
    palette = ["#4338CA", "#047857", "#B45309", "#0E7490", "#BE123C", "#7C3AED"]
    for i, (symbol, series) in enumerate(cleaned.items()):
        window = series.loc[start:end]
        if window.empty:
            continue
        rebased = window / float(window.iloc[0]) * 100.0
        fig.add_trace(
            go.Scatter(
                x=rebased.index, y=rebased.values, mode="lines", name=symbol,
                line=dict(width=1.9, color=palette[i % len(palette)]),
                hovertemplate=f"<b>{symbol}</b><br>%{{x|%d %b %Y}}<br>₹%{{y:.1f}}<extra></extra>",
            )
        )
    fig.add_hline(y=100, line_dash="dot", line_color="#94A3B8", line_width=1)
    fig.update_layout(
        yaxis_title="Growth of ₹100",
        yaxis=dict(title_font=dict(size=11, color=MUTED)),
        legend=dict(orientation="h", y=1.03, x=0, yanchor="bottom", font=dict(size=11)),
    )
    label = f"Common window · {start:%d %b %Y} → {end:%d %b %Y}"
    return _finish(fig, height), label


def performance_chart(prices: pd.Series, name: str, height: int = 300) -> go.Figure:
    clean, _ = repair_level_shifts(prices)
    fig = go.Figure()
    if clean.empty:
        return _finish(fig, height)
    rebased = clean / float(clean.iloc[0]) * 100.0
    fig.add_trace(
        go.Scatter(
            x=rebased.index, y=rebased.values, mode="lines", name=name,
            line=dict(width=1.9, color="#4338CA"), fill="tozeroy",
            fillcolor="rgba(67,56,202,.07)",
            hovertemplate="%{x|%d %b %Y}<br>₹%{y:.1f}<extra></extra>",
        )
    )
    fig.add_hline(y=100, line_dash="dot", line_color="#94A3B8", line_width=1)
    fig.update_layout(yaxis_title="Growth of ₹100", showlegend=False,
                      yaxis=dict(title_font=dict(size=11, color=MUTED)))
    return _finish(fig, height)


def drawdown_chart(prices: pd.Series, height: int = 220) -> go.Figure:
    clean, _ = repair_level_shifts(prices)
    fig = go.Figure()
    if clean.empty:
        return _finish(fig, height)
    drawdown = clean / clean.cummax() - 1.0
    fig.add_trace(
        go.Scatter(
            x=drawdown.index, y=drawdown.values, mode="lines",
            line=dict(width=1.4, color="#BE123C"), fill="tozeroy",
            fillcolor="rgba(190,18,60,.13)", showlegend=False,
            hovertemplate="%{x|%d %b %Y}<br>Drawdown %{y:.1%}<extra></extra>",
        )
    )
    fig.add_hline(y=0, line_color="#94A3B8", line_width=1)
    fig.update_layout(
        yaxis_tickformat=".0%", yaxis_title="Drawdown", showlegend=False,
        yaxis=dict(title_font=dict(size=11, color=MUTED)),
    )
    return _finish(fig, height)


def price_chart(prices: pd.Series, name: str, height: int = 280) -> go.Figure:
    clean, repairs = repair_level_shifts(prices)
    fig = go.Figure()
    if clean.empty:
        return _finish(fig, height)
    fig.add_trace(
        go.Scatter(x=clean.index, y=clean.values, mode="lines", name=name,
                   line=dict(width=1.7, color="#334155"), showlegend=False,
                   hovertemplate="%{x|%d %b %Y}<br>₹%{y:.2f}<extra></extra>")
    )
    fig.update_layout(yaxis_title="Validated NAV / Close",
                      yaxis=dict(title_font=dict(size=11, color=MUTED)))
    if repairs:
        fig.add_annotation(
            x=1, y=1.06, xref="paper", yref="paper", xanchor="right", showarrow=False,
            text=f"{len(repairs)} structural discontinuity corrected for display",
            font=dict(size=9.5, color="#B45309"),
        )
    return _finish(fig, height)


# --------------------------------------------------------------------------- #
# backtest
# --------------------------------------------------------------------------- #
def equity_curve(equity: pd.DataFrame, height: int = 330) -> go.Figure:
    fig = go.Figure()
    if equity is None or equity.empty:
        return _finish(fig, height)
    fig.add_trace(
        go.Scatter(
            x=equity.index, y=equity["benchmark"], mode="lines", name="Nifty 50",
            line=dict(width=1.8, color="#94A3B8", dash="dot"),
            hovertemplate="%{x|%b %Y}<br>Nifty 50 ₹%{y:.1f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=equity.index, y=equity["strategy"], mode="lines", name="Top-N rotation",
            line=dict(width=2.4, color="#4338CA"), fill="tonexty",
            fillcolor="rgba(67,56,202,.08)",
            hovertemplate="%{x|%b %Y}<br>Strategy ₹%{y:.1f}<extra></extra>",
        )
    )
    fig.add_hline(y=100, line_dash="dot", line_color="#CBD5E1", line_width=1)
    fig.update_layout(
        yaxis_title="Growth of ₹100",
        yaxis=dict(title_font=dict(size=11, color=MUTED)),
        legend=dict(orientation="h", y=1.03, x=0, yanchor="bottom", font=dict(size=11)),
        hovermode="x unified",
    )
    return _finish(fig, height)


def monthly_excess(monthly: pd.DataFrame, height: int = 240) -> go.Figure:
    """Per-month strategy return versus benchmark, as the excess that decides it."""
    fig = go.Figure()
    if monthly is None or monthly.empty:
        return _finish(fig, height)
    excess = monthly["excess_return"].astype(float)
    labels = pd.to_datetime(monthly["period_end"])
    fig.add_trace(
        go.Bar(
            x=labels, y=excess,
            marker=dict(
                color=["#047857" if v >= 0 else "#BE123C" for v in excess], line=dict(width=0)
            ),
            customdata=monthly[["holdings", "strategy_return", "benchmark_return"]].to_numpy(),
            hovertemplate=(
                "<b>%{x|%b %Y}</b><br>Held: %{customdata[0]}"
                "<br>Strategy %{customdata[1]:.2%}<br>Nifty 50 %{customdata[2]:.2%}"
                "<br><b>Excess %{y:+.2%}</b><extra></extra>"
            ),
            showlegend=False,
        )
    )
    fig.add_hline(y=0, line_color="#94A3B8", line_width=1)
    fig.update_layout(
        yaxis_title="Excess vs Nifty 50",
        yaxis=dict(tickformat=".0%", title_font=dict(size=11, color=MUTED)),
        bargap=0.35,
    )
    return _finish(fig, height)


def rolling_excess(windows: pd.DataFrame, height: int = 280) -> go.Figure:
    """Every overlapping window's excess return, in time order.

    One headline number depends on when the test started and stopped; this shows
    how often the strategy was actually ahead.
    """
    fig = go.Figure()
    if windows is None or windows.empty:
        return _finish(fig, height)
    excess = windows["excess"].astype(float)
    fig.add_trace(
        go.Bar(
            x=pd.to_datetime(windows["end"]), y=excess,
            marker=dict(color=["#047857" if v > 0 else "#BE123C" for v in excess], line=dict(width=0)),
            customdata=windows[["strategy", "benchmark", "cash_periods"]].to_numpy(),
            hovertemplate=(
                "12 months to <b>%{x|%b %Y}</b><br>Strategy %{customdata[0]:.1%}"
                "<br>Nifty 50 %{customdata[1]:.1%}<br><b>Excess %{y:+.1%}</b>"
                "<br>Cash in %{customdata[2]:.0%} of periods<extra></extra>"
            ),
            showlegend=False,
        )
    )
    fig.add_hline(y=0, line_color="#94A3B8", line_width=1)
    median = float(excess.median())
    fig.add_hline(y=median, line_dash="dot", line_color="#4338CA", line_width=1.4)
    fig.add_annotation(
        x=1, y=median, xref="paper", xanchor="right", yanchor="bottom", showarrow=False,
        text=f"median {median:+.1%}", font=dict(size=10, color="#4338CA"),
    )
    fig.update_layout(
        yaxis_title="Excess over the 12 months ending",
        yaxis=dict(tickformat=".0%", title_font=dict(size=11, color=MUTED)),
        bargap=0.25,
    )
    return _finish(fig, height)


def rrg_scatter(frame: pd.DataFrame, height: int = 460) -> go.Figure:
    """Relative-rotation view: RS ratio (vs its 52-week average) against RS velocity.

    Display context only — the portfolio is built from the strategy score, not
    from these quadrants.
    """
    data = frame.dropna(subset=["rs_ratio", "rs_momentum"])
    fig = go.Figure()
    for stage in ["Leading", "Weakening", "Lagging", "Improving"]:
        part = data[data["stage"] == stage]
        if part.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=part["rs_ratio"], y=part["rs_momentum"], mode="markers+text", name=stage,
                text=part["exposure"], textposition="top center",
                textfont=dict(size=10, color=MUTED),
                marker=dict(size=10, color=_stage_colour(stage), line=dict(width=1, color="white")),
                hovertemplate="<b>%{text}</b><br>RS ratio %{x:.3f}<br>RS velocity %{y:+.2f}<extra></extra>",
            )
        )
    fig.add_vline(x=1.0, line=dict(color=LINE, width=1.5))
    fig.add_hline(y=0.0, line=dict(color=LINE, width=1.5))
    for x, y, label in ((1, 1, "Leading"), (1, 0, "Weakening"), (0, 0, "Lagging"), (0, 1, "Improving")):
        fig.add_annotation(
            x=x, y=y, xref="paper", yref="paper", text=label, showarrow=False,
            xanchor="right" if x else "left", yanchor="top" if y else "bottom",
            font=dict(size=11, color=_stage_colour(label)),
        )
    fig.update_layout(
        **_LAYOUT,
        height=height,
        showlegend=False,
        xaxis=dict(title="RS ratio · RS line relative to its own 52-week average", gridcolor=GRID, zeroline=False),
        yaxis=dict(title="RS velocity · 13-week change", gridcolor=GRID, zeroline=False),
    )
    return fig
