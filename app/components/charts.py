from __future__ import annotations

import math

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


_LAYOUT = dict(
    paper_bgcolor="white",
    plot_bgcolor="white",
    font=dict(family="Inter, Arial, sans-serif", color="#0f172a", size=12),
    margin=dict(l=8, r=8, t=18, b=12),
    hoverlabel=dict(bgcolor="white", bordercolor="#e2e8f0", font=dict(color="#0f172a")),
)


def _finish(fig: go.Figure, height: int = 420) -> go.Figure:
    fig.update_layout(**_LAYOUT, height=height, autosize=True, uirevision="sector-rotation")
    fig.update_xaxes(showline=False, zeroline=False, gridcolor="#eef2f7", fixedrange=False)
    fig.update_yaxes(showline=False, zeroline=False, gridcolor="#eef2f7", fixedrange=False)
    return fig


def _mobile_config() -> dict[str, object]:
    return {"displaylogo": False, "responsive": True, "scrollZoom": False}


def ranking_bar(summary: pd.DataFrame, limit: int = 12) -> go.Figure:
    frame = summary.sort_values("rank").head(limit).copy()
    frame = frame.sort_values("momentum_z")
    fig = px.bar(
        frame,
        x="momentum_z",
        y="exposure",
        color="stage",
        orientation="h",
        hover_data=[c for c in ["rank", "return_1M", "return_3M", "return_6M", "return_12M", "data_source"] if c in frame],
        color_discrete_map={
            "Leading": "#2563eb",
            "Improving": "#60a5fa",
            "Weakening": "#f97316",
            "Lagging": "#e11d48",
            "Insufficient Data": "#94a3b8",
            "Proxy Only": "#64748b",
        },
    )
    fig.update_layout(
        xaxis_title="Momentum Z-score",
        yaxis_title="",
        legend_title_text="Stage",
        legend=dict(orientation="h", y=1.04, x=0, yanchor="bottom"),
        bargap=.28,
    )
    fig.add_vline(x=0, line_color="#cbd5e1", line_width=1)
    return _finish(fig, max(300, 30 * len(frame)))


def rs_heatmap(summary: pd.DataFrame, limit: int = 18) -> go.Figure:
    cols = [c for c in ["return_1M", "return_3M", "return_6M", "return_12M", "momentum_z"] if c in summary]
    frame = summary.sort_values("momentum_z", ascending=False).head(limit).copy()
    matrix = frame.set_index("exposure")[cols].replace([math.inf, -math.inf], pd.NA)
    matrix = matrix.dropna(how="all")
    fig = px.imshow(
        matrix,
        text_auto=".2f",
        aspect="auto",
        color_continuous_scale="RdYlGn",
        zmid=0,
        origin="upper",
    )
    fig.update_layout(
        coloraxis_colorbar_title="Score",
        coloraxis_colorbar=dict(len=.72, thickness=12),
        xaxis_title="Horizon / score",
        yaxis_title="",
        margin=dict(l=8, r=8, t=10, b=50),
    )
    fig.update_xaxes(tickangle=-35, tickfont=dict(size=10))
    fig.update_yaxes(tickfont=dict(size=10))
    return _finish(fig, max(360, 27 * len(matrix)))


def rrg_quadrant(summary: pd.DataFrame, label_limit: int = 6) -> go.Figure:
    frame = summary.dropna(subset=["rs_ratio", "rs_momentum"]).copy()
    frame = frame.sort_values("rank")
    fig = px.scatter(
        frame,
        x="rs_ratio",
        y="rs_momentum",
        color="stage",
        hover_name="exposure",
        hover_data=[c for c in ["rank", "category", "momentum_z", "data_source"] if c in frame],
        color_discrete_map={
            "Leading": "#2563eb",
            "Improving": "#60a5fa",
            "Weakening": "#f97316",
            "Lagging": "#e11d48",
            "Insufficient Data": "#94a3b8",
            "Proxy Only": "#64748b",
        },
    )
    # Only label the strongest few observations. The rest remain discoverable
    # through hover, avoiding the unreadable label pile-up seen on phones.
    labels = frame.head(label_limit)
    fig.add_trace(
        go.Scatter(
            x=labels["rs_ratio"],
            y=labels["rs_momentum"],
            mode="text",
            text=labels["exposure"],
            textposition="top center",
            textfont=dict(size=9, color="#334155"),
            hoverinfo="skip",
            showlegend=False,
        )
    )
    fig.add_vline(x=1.0, line_dash="dash", line_color="#cbd5e1", line_width=1)
    fig.add_hline(y=0.0, line_dash="dash", line_color="#cbd5e1", line_width=1)
    fig.add_annotation(x=.98, y=1, text="IMPROVING", showarrow=False, xref="x", yref="paper", font=dict(size=9, color="#94a3b8"))
    fig.add_annotation(x=1.02, y=1, text="LEADING", showarrow=False, xref="x", yref="paper", font=dict(size=9, color="#94a3b8"))
    fig.update_traces(marker=dict(size=9, line=dict(width=1, color="white")))
    fig.update_layout(
        xaxis_title="RS Ratio · 1.00 = benchmark",
        yaxis_title="RS Momentum · 0 = neutral",
        legend=dict(orientation="h", y=1.04, x=0, yanchor="bottom"),
    )
    return _finish(fig, 430)


def rs_trajectory(rs: pd.DataFrame, exposure: str, window: int = 52) -> go.Figure:
    series = rs[exposure].dropna().tail(window) if exposure in rs.columns else pd.Series(dtype=float)
    fig = go.Figure(go.Scatter(x=series.index, y=series.values, mode="lines", name=exposure, line=dict(width=2)))
    fig.add_hline(y=0, line_dash="dash", line_color="#cbd5e1")
    fig.update_layout(xaxis_title="Date", yaxis_title="Mansfield RS (%)", showlegend=False)
    return _finish(fig, 350)


def _repair_level_shifts(series: pd.Series) -> tuple[pd.Series, list[dict[str, object]]]:
    """Repair obvious unit/split discontinuities without hiding normal volatility.

    A correction is made only when a large one-day level jump is followed by a
    persistent level ratio. The conservative 2.5x / 0.4x thresholds deliberately
    avoid treating ordinary market crashes as corporate actions.
    """
    clean = pd.to_numeric(series, errors="coerce").dropna().astype(float).sort_index().copy()
    if len(clean) < 25:
        return clean, []
    repairs: list[dict[str, object]] = []
    for _ in range(4):
        values = clean.to_numpy(copy=True)
        changed = False
        for i in range(10, len(values) - 10):
            previous = float(values[i - 1])
            current = float(values[i])
            if previous <= 0 or current <= 0:
                continue
            day_ratio = current / previous
            pre = float(pd.Series(values[i - 10:i]).median())
            post = float(pd.Series(values[i:i + 10]).median())
            if pre <= 0:
                continue
            level_ratio = post / pre
            if not (level_ratio >= 2.5 or level_ratio <= 0.4):
                continue
            if abs(math.log(day_ratio / level_ratio)) > 0.18:
                continue
            clean.iloc[:i] *= level_ratio
            repairs.append({"date": clean.index[i], "factor": level_ratio})
            changed = True
            break
        if not changed:
            break
    return clean, repairs


def price_chart(prices: pd.Series, name: str) -> go.Figure:
    clean, repairs = _repair_level_shifts(prices)
    fig = go.Figure(go.Scatter(x=clean.index, y=clean.values, mode="lines", name=name, line=dict(width=2)))
    fig.update_layout(xaxis_title="Date", yaxis_title="Validated NAV / Close", showlegend=False)
    if repairs:
        fig.add_annotation(
            x=1, y=1.04, xref="paper", yref="paper", xanchor="right", showarrow=False,
            text="Structural price discontinuity corrected for display",
            font=dict(size=9, color="#b45309"),
        )
    return _finish(fig, 350)


def performance_chart(prices: pd.Series, name: str) -> go.Figure:
    clean, _ = _repair_level_shifts(prices)
    if clean.empty:
        return _finish(go.Figure(), 320)
    rebased = clean / float(clean.iloc[0]) * 100.0
    fig = go.Figure(go.Scatter(x=rebased.index, y=rebased.values, mode="lines", name=name, line=dict(width=2)))
    fig.add_hline(y=100, line_dash="dot", line_color="#cbd5e1")
    fig.update_layout(xaxis_title="Date", yaxis_title="Growth of ₹100", showlegend=False)
    return _finish(fig, 320)


def drawdown_chart(prices: pd.Series) -> go.Figure:
    clean, _ = _repair_level_shifts(prices)
    running_max = clean.cummax()
    drawdown = clean / running_max - 1.0
    fig = go.Figure(go.Scatter(x=drawdown.index, y=drawdown.values, mode="lines", name="Drawdown", line=dict(width=2)))
    fig.add_hline(y=0, line_color="#cbd5e1")
    fig.update_layout(yaxis_tickformat=".0%", xaxis_title="Date", yaxis_title="Drawdown", showlegend=False)
    return _finish(fig, 320)
