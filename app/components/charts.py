"""Plotly figures, in the design system's colours.

Backgrounds are transparent and axis text is left to Streamlit's chart theme, so
every figure reads correctly in light and dark mode; trace colours come from the
active token set (``theme.palette``) so "positive" is the same emerald in a
chart, a chip and a KPI card.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from app.components.theme import palette, stage_colors
from src.quantitative.analytics import repair_level_shifts as _repair

CHART_CONFIG = {"displaylogo": False, "responsive": True, "displayModeBar": False}
TRANSPARENT = "rgba(0,0,0,0)"
SERIES = ("accent", "pos", "warn", "info", "neg")


def _rgba(hex_colour: str, alpha: float) -> str:
    colour = hex_colour.lstrip("#")
    if len(colour) != 6:
        return hex_colour
    r, g, b = (int(colour[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def _finish(fig: go.Figure, height: int = 360, **layout) -> go.Figure:
    tokens = palette()
    fig.update_layout(
        height=height,
        autosize=True,
        paper_bgcolor=TRANSPARENT,
        plot_bgcolor=TRANSPARENT,
        margin=dict(l=8, r=12, t=18, b=8),
        font=dict(family="Inter, ui-sans-serif, system-ui, sans-serif", size=12),
        hoverlabel=dict(font=dict(family="Inter, ui-sans-serif, sans-serif", size=12)),
        legend=dict(orientation="h", y=1.02, x=0, yanchor="bottom", font=dict(size=11), bgcolor=TRANSPARENT),
        dragmode=False,
        uirevision="sector-rotation",
        **layout,
    )
    fig.update_xaxes(showline=False, zeroline=False, gridcolor=_rgba(tokens["faint"], 0.18))
    fig.update_yaxes(showline=False, zeroline=False, gridcolor=_rgba(tokens["faint"], 0.18))
    return fig


def _baseline(fig: go.Figure, y: float, **kwargs) -> None:
    fig.add_hline(y=y, line=dict(color=palette()["faint"], width=1, dash=kwargs.pop("dash", "solid")), **kwargs)


# --------------------------------------------------------------------------- #
# backtest
# --------------------------------------------------------------------------- #
def equity_curve(equity: pd.DataFrame, height: int = 440) -> go.Figure:
    """Growth of ₹100 for the strategy and Nifty 50 TRI, with both drawdowns beneath."""
    tokens = palette()
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05)
    if equity is None or equity.empty:
        return _finish(fig, height)
    bench = equity["benchmark"].astype(float)
    strat = equity["strategy"].astype(float)
    fig.add_trace(
        go.Scatter(x=equity.index, y=bench, name="Nifty 50 TRI", mode="lines",
                   line=dict(width=1.7, color=tokens["faint"], dash="dot"),
                   hovertemplate="Nifty 50 TRI ₹%{y:.1f}<extra></extra>"),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(x=equity.index, y=strat, name="Strategy (net)", mode="lines",
                   line=dict(width=2.4, color=tokens["accent"]),
                   hovertemplate="Strategy ₹%{y:.1f}<extra></extra>"),
        row=1, col=1,
    )
    for series, colour, name in ((bench, tokens["faint"], "Nifty 50 TRI"), (strat, tokens["neg"], "Strategy")):
        drawdown = series / series.cummax() - 1.0
        fig.add_trace(
            go.Scatter(x=equity.index, y=drawdown, name=f"{name} drawdown", mode="lines", showlegend=False,
                       line=dict(width=1.2, color=colour), fill="tozeroy",
                       fillcolor=_rgba(colour, 0.14 if name == "Strategy" else 0.08),
                       hovertemplate=f"{name} drawdown %{{y:.1%}}<extra></extra>"),
            row=2, col=1,
        )
    fig.update_yaxes(title_text="Growth of ₹100", row=1, col=1)
    fig.update_yaxes(title_text="Drawdown", tickformat=".0%", row=2, col=1)
    return _finish(fig, height, hovermode="x unified")


def excess_distribution(windows: pd.DataFrame, height: int = 280) -> go.Figure:
    """How often, and by how much, a 12-month window beat Nifty 50."""
    tokens = palette()
    fig = go.Figure()
    if windows is None or windows.empty:
        return _finish(fig, height)
    excess = windows["excess"].astype(float)
    edges = np.linspace(min(excess.min(), 0.0), max(excess.max(), 0.0), 21)
    counts, edges = np.histogram(excess, bins=edges)
    mids = (edges[:-1] + edges[1:]) / 2
    fig.add_trace(
        go.Bar(x=mids, y=counts, width=np.diff(edges) * 0.92,
               marker=dict(color=[tokens["pos"] if m > 0 else tokens["neg"] for m in mids], line=dict(width=0)),
               customdata=np.column_stack([edges[:-1], edges[1:]]),
               hovertemplate="Excess %{customdata[0]:.0%} to %{customdata[1]:.0%}<br>%{y} windows<extra></extra>",
               showlegend=False)
    )
    fig.add_vline(x=0, line=dict(color=tokens["faint"], width=1.2))
    median = float(excess.median())
    fig.add_vline(x=median, line=dict(color=tokens["accent"], width=1.4, dash="dot"))
    fig.add_annotation(x=median, y=1, yref="paper", text=f"median {median:+.1%}", showarrow=False,
                       yanchor="bottom", font=dict(size=10, color=tokens["accent"]))
    return _finish(fig, height, bargap=0.04, xaxis=dict(title="Excess over Nifty 50 TRI, 12 months", tickformat=".0%"),
                   yaxis=dict(title="Windows"))


def rolling_excess(windows: pd.DataFrame, height: int = 280) -> go.Figure:
    """Every rolling 12-month window's excess, in time order."""
    tokens = palette()
    fig = go.Figure()
    if windows is None or windows.empty:
        return _finish(fig, height)
    excess = windows["excess"].astype(float)
    fig.add_trace(
        go.Bar(x=pd.to_datetime(windows["end"]), y=excess,
               marker=dict(color=[tokens["pos"] if v > 0 else tokens["neg"] for v in excess], line=dict(width=0)),
               customdata=windows[["strategy", "benchmark"]].to_numpy(),
               hovertemplate=("12 months to <b>%{x|%b %Y}</b><br>Strategy %{customdata[0]:.1%}"
                              "<br>Nifty 50 %{customdata[1]:.1%}<br><b>Excess %{y:+.1%}</b><extra></extra>"),
               showlegend=False)
    )
    _baseline(fig, 0)
    return _finish(fig, height, bargap=0.2, yaxis=dict(title="Excess, 12 months ending", tickformat=".0%"))


def monthly_excess(monthly: pd.DataFrame, height: int = 250) -> go.Figure:
    tokens = palette()
    fig = go.Figure()
    if monthly is None or monthly.empty:
        return _finish(fig, height)
    excess = monthly["excess_return"].astype(float)
    fig.add_trace(
        go.Bar(x=pd.to_datetime(monthly["period_end"]), y=excess,
               marker=dict(color=[tokens["pos"] if v >= 0 else tokens["neg"] for v in excess], line=dict(width=0)),
               customdata=monthly[["holdings", "strategy_return", "benchmark_return"]].to_numpy(),
               hovertemplate=("<b>%{x|%b %Y}</b><br>Held: %{customdata[0]}<br>Strategy %{customdata[1]:.2%}"
                              "<br>Nifty 50 %{customdata[2]:.2%}<br><b>Excess %{y:+.2%}</b><extra></extra>"),
               showlegend=False)
    )
    _baseline(fig, 0)
    return _finish(fig, height, bargap=0.3, yaxis=dict(title="Excess vs Nifty 50", tickformat=".0%"))


# --------------------------------------------------------------------------- #
# rankings
# --------------------------------------------------------------------------- #
def rrg_scatter(frame: pd.DataFrame, height: int = 520) -> go.Figure:
    """RS ratio against RS velocity, with crosshair spikes. Display context only."""
    tokens = palette()
    colours = stage_colors()
    data = frame.dropna(subset=["rs_ratio", "rs_momentum"])
    fig = go.Figure()
    if data.empty:
        return _finish(fig, height)
    x_pad = max(abs(data["rs_ratio"] - 1).max() * 1.15, 0.05)
    y_pad = max(data["rs_momentum"].abs().max() * 1.15, 1.0)
    quadrants = (("Leading", 1, 1 + x_pad, 0, y_pad), ("Weakening", 1, 1 + x_pad, -y_pad, 0),
                 ("Lagging", 1 - x_pad, 1, -y_pad, 0), ("Improving", 1 - x_pad, 1, 0, y_pad))
    for stage, x0, x1, y0, y1 in quadrants:
        fig.add_shape(type="rect", x0=x0, x1=x1, y0=y0, y1=y1, line=dict(width=0),
                      fillcolor=_rgba(colours[stage], 0.06), layer="below")
        fig.add_annotation(x=x1 if x1 > 1 else x0, y=y1 if y1 > 0 else y0, text=stage, showarrow=False,
                           xanchor="right" if x1 > 1 else "left", yanchor="top" if y1 > 0 else "bottom",
                           font=dict(size=11, color=colours[stage]))
    for stage in ("Leading", "Weakening", "Lagging", "Improving"):
        part = data[data["stage"] == stage]
        if part.empty:
            continue
        fig.add_trace(
            go.Scatter(x=part["rs_ratio"], y=part["rs_momentum"], mode="markers+text", name=stage,
                       text=part["exposure"], textposition="top center", textfont=dict(size=10),
                       marker=dict(size=11, color=colours[stage], line=dict(width=1, color=tokens["bg"])),
                       hovertemplate="<b>%{text}</b><br>RS ratio %{x:.3f}<br>RS velocity %{y:+.2f}<extra></extra>")
        )
    fig.add_vline(x=1.0, line=dict(color=tokens["line2"], width=1.4))
    fig.add_hline(y=0.0, line=dict(color=tokens["line2"], width=1.4))
    spikes = dict(showspikes=True, spikemode="across", spikesnap="cursor", spikethickness=1,
                  spikedash="dot", spikecolor=tokens["muted"])
    fig.update_xaxes(range=[1 - x_pad, 1 + x_pad], title="RS ratio · vs its own 52-week average", **spikes)
    fig.update_yaxes(range=[-y_pad, y_pad], title="RS velocity · 13-week change", **spikes)
    return _finish(fig, height, showlegend=False, hovermode="closest", hoverdistance=24, spikedistance=-1)


# --------------------------------------------------------------------------- #
# one exposure
# --------------------------------------------------------------------------- #
def rs_trajectory(rs: pd.DataFrame, exposure: str, window: int = 156, height: int = 320) -> go.Figure:
    """Mansfield RS against Nifty 50, weekly: above zero the exposure is ahead of its own trend."""
    tokens = palette()
    fig = go.Figure()
    series = (pd.to_numeric(rs[exposure], errors="coerce").dropna().tail(window)
              if exposure in getattr(rs, "columns", []) else pd.Series(dtype=float))
    if series.empty:
        return _finish(fig, height)
    for part, colour in ((series.clip(lower=0), tokens["pos"]), (series.clip(upper=0), tokens["neg"])):
        fig.add_trace(go.Scatter(x=series.index, y=part, mode="lines", line=dict(width=0), fill="tozeroy",
                                 fillcolor=_rgba(colour, 0.16), hoverinfo="skip", showlegend=False))
    fig.add_trace(go.Scatter(x=series.index, y=series, mode="lines", line=dict(width=2, color=tokens["text2"]),
                             showlegend=False, hovertemplate="%{x|%d %b %Y}<br>Mansfield RS %{y:+.2f}%<extra></extra>"))
    _baseline(fig, 0, dash="dot")
    return _finish(fig, height, yaxis=dict(title="Mansfield RS vs Nifty 50 (%)", ticksuffix="%"))


def trailing_volatility(level: pd.Series, height: int = 300) -> go.Figure:
    """Annualised volatility of daily log returns over 63 and 252 sessions."""
    tokens = palette()
    fig = go.Figure()
    prices = pd.to_numeric(level, errors="coerce").dropna()
    if len(prices) < 70:
        return _finish(fig, height)
    daily = np.log(prices).diff()
    for window, colour, name, width in ((63, tokens["warn"], "3-month", 1.6), (252, tokens["accent"], "12-month", 2.2)):
        vol = (daily.rolling(window).std() * np.sqrt(252)).dropna()
        fig.add_trace(go.Scatter(x=vol.index, y=vol, mode="lines", name=f"{name} volatility",
                                 line=dict(width=width, color=colour),
                                 hovertemplate=f"{name} vol %{{y:.1%}}<extra></extra>"))
    return _finish(fig, height, hovermode="x unified", yaxis=dict(title="Annualised volatility", tickformat=".0%"))


def drawdown_chart(level: pd.Series, height: int = 260) -> go.Figure:
    tokens = palette()
    fig = go.Figure()
    prices = pd.to_numeric(level, errors="coerce").dropna()
    if prices.empty:
        return _finish(fig, height)
    drawdown = prices / prices.cummax() - 1.0
    fig.add_trace(go.Scatter(x=drawdown.index, y=drawdown, mode="lines", line=dict(width=1.4, color=tokens["neg"]),
                             fill="tozeroy", fillcolor=_rgba(tokens["neg"], 0.15), showlegend=False,
                             hovertemplate="%{x|%d %b %Y}<br>Drawdown %{y:.1%}<extra></extra>"))
    _baseline(fig, 0)
    return _finish(fig, height, yaxis=dict(title="Drawdown from high", tickformat=".0%"))


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


def etf_comparison(prices: pd.DataFrame, keys: list[str], height: int = 320) -> tuple[go.Figure, str]:
    """Every vehicle rebased to ₹100 on the window they all share.

    Each fund on its own full history would make the longest-listed one look
    strongest purely because it started earlier.
    """
    tokens = palette()
    cleaned = {}
    for key in keys:
        if key in prices.columns:
            series, _ = repair_level_shifts(prices[key])
            if not series.empty:
                cleaned[key] = series
    fig = go.Figure()
    if not cleaned:
        return _finish(fig, height), ""
    start = max(s.index.min() for s in cleaned.values())
    end = min(s.index.max() for s in cleaned.values())
    for i, (key, series) in enumerate(cleaned.items()):
        window = series.loc[start:end]
        if window.empty:
            continue
        rebased = window / float(window.iloc[0]) * 100.0
        fig.add_trace(go.Scatter(x=rebased.index, y=rebased, mode="lines", name=key,
                                 line=dict(width=1.8, color=tokens[SERIES[i % len(SERIES)]]),
                                 hovertemplate=f"<b>{key}</b> ₹%{{y:.1f}}<extra></extra>"))
    _baseline(fig, 100, dash="dot")
    return _finish(fig, height, hovermode="x unified", yaxis=dict(title="Growth of ₹100")), (
        f"Common window {start:%d %b %Y} → {end:%d %b %Y}"
    )


def nav_sparkline(nav: pd.Series, height: int = 200) -> go.Figure:
    tokens = palette()
    fig = go.Figure()
    series = pd.to_numeric(nav, errors="coerce").dropna()
    if series.empty:
        return _finish(fig, height)
    fig.add_trace(go.Scatter(x=series.index, y=series, mode="lines", line=dict(width=1.8, color=tokens["info"]),
                             fill="tozeroy", fillcolor=_rgba(tokens["info"], 0.08), showlegend=False,
                             hovertemplate="%{x|%d %b %Y}<br>NAV ₹%{y:,.2f}<extra></extra>"))
    lo, hi = float(series.min()), float(series.max())
    pad = (hi - lo) * 0.08 or 1.0
    return _finish(fig, height, yaxis=dict(title="NAV ₹", range=[lo - pad, hi + pad]))
