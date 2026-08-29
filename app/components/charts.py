from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


_LAYOUT = dict(
    paper_bgcolor="white",
    plot_bgcolor="white",
    font=dict(family="Inter, Arial, sans-serif", color="#0f172a", size=12),
    margin=dict(l=12, r=12, t=24, b=18),
    hoverlabel=dict(bgcolor="white", bordercolor="#e5e7eb", font=dict(color="#0f172a")),
)


def _finish(fig: go.Figure, height: int = 460) -> go.Figure:
    fig.update_layout(**_LAYOUT, height=height)
    fig.update_xaxes(showline=False, zeroline=False, gridcolor="#f1f5f9")
    fig.update_yaxes(showline=False, zeroline=False, gridcolor="#f1f5f9")
    return fig


def ranking_bar(summary: pd.DataFrame) -> go.Figure:
    frame = summary.sort_values("rank").copy()
    fig = px.bar(
        frame,
        x="momentum_z",
        y="exposure",
        color="stage",
        orientation="h",
        hover_data=["rank", "return_1M", "return_3M", "return_6M", "return_12M"],
    )
    fig.update_layout(legend_title_text="Stage", xaxis_title="Composite momentum Z-score", yaxis_title="")
    return _finish(fig, max(420, 25 * len(frame)))


def rs_heatmap(summary: pd.DataFrame) -> go.Figure:
    cols = [c for c in ["return_1M", "return_3M", "return_6M", "return_12M", "momentum_z"] if c in summary]
    matrix = summary.set_index("exposure")[cols].replace([float("inf"), float("-inf")], pd.NA).dropna(how="all")
    fig = px.imshow(matrix, text_auto=".2f", aspect="auto", color_continuous_scale="RdYlGn", origin="lower")
    fig.update_layout(coloraxis_colorbar_title="Score", xaxis_title="Horizon / score", yaxis_title="")
    return _finish(fig, max(420, 28 * len(matrix)))


def rrg_quadrant(summary: pd.DataFrame) -> go.Figure:
    frame = summary.dropna(subset=["rs_ratio", "rs_momentum"]).copy()
    fig = px.scatter(frame, x="rs_ratio", y="rs_momentum", color="stage", text="exposure", hover_data=["rank", "category", "data_source"])
    fig.add_vline(x=1.0, line_dash="dash", line_color="#cbd5e1")
    fig.add_hline(y=0.0, line_dash="dash", line_color="#cbd5e1")
    fig.update_traces(textposition="top center", marker=dict(size=10))
    fig.update_layout(xaxis_title="RS Ratio", yaxis_title="RS Momentum", legend_title_text="Stage")
    return _finish(fig, 540)


def rs_trajectory(rs: pd.DataFrame, exposure: str, window: int = 52) -> go.Figure:
    series = rs[exposure].dropna().tail(window)
    fig = go.Figure(go.Scatter(x=series.index, y=series.values, mode="lines", name=exposure, line=dict(width=2)))
    fig.add_hline(y=0, line_dash="dash", line_color="#cbd5e1")
    fig.update_layout(xaxis_title="Date", yaxis_title="Mansfield RS (%)", showlegend=False)
    return _finish(fig, 420)


def price_chart(prices: pd.Series, name: str) -> go.Figure:
    clean = prices.dropna()
    fig = go.Figure(go.Scatter(x=clean.index, y=clean.values, mode="lines", name=name, line=dict(width=2)))
    fig.update_layout(xaxis_title="Date", yaxis_title="NAV / Close", showlegend=False)
    return _finish(fig, 360)


def drawdown_chart(prices: pd.Series) -> go.Figure:
    clean = prices.dropna()
    running_max = clean.cummax()
    drawdown = clean / running_max - 1.0
    fig = go.Figure(go.Scatter(x=drawdown.index, y=drawdown.values, mode="lines", name="Drawdown", line=dict(width=2)))
    fig.add_hline(y=0, line_color="#cbd5e1")
    fig.update_layout(yaxis_tickformat=".0%", xaxis_title="Date", yaxis_title="Drawdown", showlegend=False)
    return _finish(fig, 360)
