"""Plotly figures for the rotation views.

Stage colour is consistent everywhere: Leading green, Weakening amber, Lagging
red, Improving blue — so a bar, a badge and a table dot all mean the same thing.
"""

from __future__ import annotations

import math

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
def momentum_bar(frame: pd.DataFrame, limit: int = 16, height: int | None = None) -> go.Figure:
    """Composite momentum Z-score, coloured by rotation stage.

    A Z-score is standardised to a mean of exactly zero, so roughly half the
    universe sits below the line by construction. A bar pointing left means
    *below the universe average*, not a loss — several of those exposures are up
    on the period. The axis and the hover both say so, because a negative bar
    reads as a loss otherwise.
    """
    data = frame.sort_values("momentum_z", ascending=False).head(limit).sort_values("momentum_z")
    fig = go.Figure()
    if data.empty:
        return _finish(fig, height or 320)

    has_returns = {"return_3M", "relative_3M"}.issubset(data.columns)
    custom = (
        data[["stage", "model_action", "return_3M", "relative_3M"]].to_numpy()
        if has_returns and "model_action" in data.columns
        else data[["stage", "stage"]].to_numpy()
    )
    hover = (
        "<b>%{y}</b><br>Momentum Z %{x:+.2f} vs universe average"
        "<br>%{customdata[0]} · %{customdata[1]}"
        "<br>3M return %{customdata[2]:.2%}<br>3M vs Nifty 50 %{customdata[3]:+.2%}<extra></extra>"
        if has_returns and "model_action" in data.columns
        else "<b>%{y}</b><br>Momentum Z %{x:+.2f} vs universe average<extra></extra>"
    )
    fig.add_trace(
        go.Bar(
            x=data.momentum_z, y=data.exposure, orientation="h",
            marker=dict(color=[_stage_colour(s) for s in data.stage], line=dict(width=0)),
            customdata=custom, hovertemplate=hover, showlegend=False,
        )
    )
    fig.add_vline(x=0, line_color="#64748B", line_width=1.4)
    fig.add_annotation(
        x=0, y=1.0, yref="paper", yanchor="bottom", xanchor="center", showarrow=False,
        text="universe average", font=dict(size=9.5, color=MUTED), yshift=4,
    )
    fig.update_layout(
        xaxis_title="Composite momentum Z-score · 0 = universe average, not zero return",
        xaxis=dict(title_font=dict(size=11, color=MUTED), zeroline=False),
        yaxis=dict(tickfont=dict(size=11, color=INK)),
        bargap=0.3,
    )
    return _finish(fig, height or max(260, 26 * len(data) + 80))


def returns_heatmap(frame: pd.DataFrame, limit: int = 20, height: int | None = None) -> go.Figure:
    cols = [c for c in ["return_1M", "return_3M", "return_6M", "return_12M"] if c in frame.columns]
    data = frame.sort_values("momentum_z", ascending=False).head(limit)
    if data.empty or not cols:
        return _finish(go.Figure(), height or 320)
    matrix = data.set_index("exposure")[cols].replace([math.inf, -math.inf], pd.NA).dropna(how="all")
    if matrix.empty:
        return _finish(go.Figure(), height or 320)
    values = matrix.to_numpy(dtype=float)
    bound = float(pd.DataFrame(values).abs().max().max() or 0.01)
    text = matrix.map(lambda v: "—" if pd.isna(v) else f"{v * 100:.1f}")
    fig = go.Figure(
        go.Heatmap(
            z=values,
            x=[c.replace("return_", "") for c in matrix.columns],
            y=list(matrix.index),
            text=text.to_numpy(),
            texttemplate="%{text}",
            textfont=dict(size=10.5, family="Inter, sans-serif"),
            colorscale=RETURN_SCALE,
            zmid=0, zmin=-bound, zmax=bound,
            xgap=2, ygap=2,
            hovertemplate="<b>%{y}</b><br>%{x} return %{z:.2%}<extra></extra>",
            colorbar=dict(
                title=dict(text="Return %", font=dict(size=10, color=MUTED)),
                thickness=9, len=0.75, outlinewidth=0, tickfont=dict(size=10, color=MUTED),
                tickformat=".0%",
            ),
        )
    )
    fig.update_layout(margin=dict(l=10, r=10, t=8, b=24))
    fig.update_xaxes(side="top", tickfont=dict(size=11, color=INK), showgrid=False)
    fig.update_yaxes(tickfont=dict(size=11, color=INK), showgrid=False, autorange="reversed")
    return _finish(fig, height or max(300, 25 * len(matrix) + 70))


def stage_distribution(frame: pd.DataFrame, height: int = 62) -> go.Figure:
    """Breadth bar: how much of the universe sits in each rotation stage."""
    order = ["Leading", "Weakening", "Lagging", "Improving"]
    counts = frame["stage"].value_counts()
    present = [s for s in order if counts.get(s, 0) > 0]
    fig = go.Figure()
    for stage in present:
        fig.add_trace(
            go.Bar(
                x=[int(counts[stage])], y=["breadth"], orientation="h", name=stage,
                marker=dict(color=_stage_colour(stage), line=dict(width=0)),
                text=[f"{stage} {int(counts[stage])}"], textposition="inside",
                insidetextanchor="middle", textangle=0, cliponaxis=False, constraintext="inside",
                textfont=dict(color="white", size=11.5, family="Inter, sans-serif"),
                hovertemplate=f"<b>{stage}</b>: %{{x}} exposures<extra></extra>",
            )
        )
    fig.update_layout(
        barmode="stack", showlegend=False,
        margin=dict(l=4, r=4, t=4, b=4),
        xaxis=dict(visible=False), yaxis=dict(visible=False),
    )
    fig.update_layout(**{k: v for k, v in _LAYOUT.items() if k != "margin"}, height=height,
                      autosize=True, uirevision="breadth")
    return fig


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
