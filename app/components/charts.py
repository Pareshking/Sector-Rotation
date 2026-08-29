from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def ranking_bar(summary: pd.DataFrame) -> go.Figure:
    frame = summary.sort_values("rank").copy()
    fig = px.bar(frame, x="momentum_z", y="exposure", color="stage", orientation="h", hover_data=["rank", "return_1M", "return_3M", "return_6M", "return_12M"])
    fig.update_layout(height=max(420, 24 * len(frame)), margin=dict(l=10, r=10, t=20, b=20), legend_title_text="Stage")
    return fig


def rs_heatmap(summary: pd.DataFrame) -> go.Figure:
    cols = [c for c in ["return_1M", "return_3M", "return_6M", "return_12M", "momentum_z"] if c in summary]
    matrix = summary.set_index("exposure")[cols]
    fig = px.imshow(matrix, text_auto=".2f", aspect="auto", color_continuous_scale="RdYlGn", origin="lower")
    fig.update_layout(height=max(420, 24 * len(matrix)), margin=dict(l=10, r=10, t=20, b=20))
    return fig


def rs_trajectory(rs: pd.DataFrame, exposure: str, window: int = 252) -> go.Figure:
    series = rs[exposure].dropna().tail(window)
    fig = go.Figure(go.Scatter(x=series.index, y=series.values, mode="lines", name=exposure))
    fig.add_hline(y=0, line_dash="dash")
    fig.update_layout(height=420, xaxis_title="Date", yaxis_title="Mansfield RS (%)", margin=dict(l=10, r=10, t=20, b=20))
    return fig
