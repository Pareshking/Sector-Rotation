"""Calendar returns: the Paresh app's year-separated grid, copied as is.

``grid`` has one row per (YEAR, SERIES) with JAN..DEC, CY RETURN, FY RETURN and
Q1..Q4 as fractions; ``build_grid`` makes it from a monthly return frame.
"""
from __future__ import annotations

import html

import numpy as np
import pandas as pd
import streamlit as st

MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]


def _compound(values) -> float:
    valid = [float(v) for v in values if pd.notna(v)]
    return float(np.prod([1.0 + v for v in valid]) - 1.0) if valid else np.nan


def build_grid(monthly: pd.DataFrame, series: dict[str, str]) -> pd.DataFrame:
    """monthly: a Period column (YYYY-MM) plus one fraction column per series.

    series maps a column to the row label ("Strategy", "Nifty 50", "Alpha"). The
    calendar year compounds its months; the Indian financial year runs April to
    March and is shown on the year it ends in; quarters are calendar quarters.
    Alpha's summaries are strategy minus benchmark, not a compounded alpha.
    """
    if monthly is None or monthly.empty:
        return pd.DataFrame()
    periods = pd.PeriodIndex(monthly["Period"], freq="M")
    rows = []
    labels = list(series.items())
    for year in sorted(set(periods.year)):
        values = {}
        for column, label in labels:
            by_month = {p.month: float(v) for p, v in zip(periods, monthly[column]) if p.year == year and pd.notna(v)}
            fy = [float(v) for p, v in zip(periods, monthly[column])
                  if pd.notna(v) and ((p.year == year and p.month <= 3) or (p.year == year - 1 and p.month >= 4))]
            row = {"YEAR": year, "SERIES": label}
            for m, name in enumerate(MONTHS, start=1):
                row[name] = by_month.get(m, np.nan)
            row["CY RETURN"] = _compound(by_month.values())
            row["FY RETURN"] = _compound(fy)
            for q in range(4):
                row[f"Q{q + 1}"] = _compound([by_month.get(m) for m in range(3 * q + 1, 3 * q + 4) if m in by_month])
            values[label] = row
            rows.append(row)
    grid = pd.DataFrame(rows)
    alpha = [label for _, label in labels if label.lower() == "alpha"]
    if alpha and len(labels) >= 3:
        strategy, benchmark = labels[0][1], labels[1][1]
        for column in ["CY RETURN", "FY RETURN", "Q1", "Q2", "Q3", "Q4"]:
            s = grid.loc[grid["SERIES"] == strategy, column].to_numpy()
            b = grid.loc[grid["SERIES"] == benchmark, column].to_numpy()
            grid.loc[grid["SERIES"] == alpha[0], column] = s - b
    return grid.sort_values(["YEAR"], ascending=False, kind="mergesort").reset_index(drop=True)


def render_calendar_returns(grid: pd.DataFrame) -> None:
    """Render the calendar return grid as year-separated, responsive HTML tables.

    The underlying grid remains the engine's canonical compounded monthly/CY/FY
    data. This is presentation only: no returns are recalculated here.
    """
    if grid.empty:
        st.info("No full month in this window yet.")
        return

    month_cols = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                  "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    summary_cols = ["CY RETURN", "FY RETURN", "Q1", "Q2", "Q3", "Q4"]
    columns = month_cols + summary_cols

    def cell(value, *, summary=False):
        if value is None or pd.isna(value):
            return '<td class="cr-empty">—</td>'
        number = float(value)
        tone = "positive" if number > 0 else "negative" if number < 0 else "flat"
        extra = " cr-summary" if summary else ""
        return f'<td class="cr-value {tone}{extra}">{number:+.1%}</td>'

    blocks = []
    for year, year_df in grid.groupby("YEAR", sort=False):
        rows = []
        for _, row in year_df.iterrows():
            series = str(row.get("SERIES", ""))
            series_class = (
                "strategy" if series.lower() == "strategy"
                else "alpha" if series.lower() == "alpha"
                else "benchmark"
            )
            cells = "".join(cell(row.get(col), summary=col in summary_cols)
                            for col in columns)
            rows.append(
                f'<tr><th scope="row" class="cr-series {series_class}">'
                f'{html.escape(series)}</th>{cells}</tr>'
            )
        header = "".join(
            f'<th class="{"cr-summary-head" if col in summary_cols else ""}">{col}</th>'
            for col in columns
        )
        blocks.append(
            f'<section class="cr-year"><div class="cr-year-head">'
            f'<div><span class="cr-kicker">CALENDAR YEAR</span>'
            f'<h3>{int(year)}</h3></div>'
            f'<span class="cr-year-note">Monthly returns · compounded summaries</span>'
            f'</div><div class="cr-scroll"><table class="cr-table">'
            f'<thead><tr><th class="cr-series-head">Series</th>{header}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div></section>'
        )

    st.html("""
    <style>
      .cr-wrap { display:grid; gap:14px; font-family:inherit; color:#172033; }
      .cr-year { background:#fff; border:1px solid #e2e7ef; border-radius:13px;
        overflow:hidden; box-shadow:0 2px 8px rgba(20,32,54,.035); }
      .cr-year-head { display:flex; align-items:center; justify-content:space-between;
        gap:12px; padding:13px 16px; background:linear-gradient(110deg,#f7f8ff,#fff);
        border-bottom:1px solid #e8ebf2; }
      .cr-kicker { display:block; font-size:9px; font-weight:800; letter-spacing:.13em;
        color:#68738a; }
      .cr-year-head h3 { margin:2px 0 0; font-size:21px; line-height:1.2;
        letter-spacing:-.04em; color:#172033; font-weight:750; }
      .cr-year-note { color:#778196; font-size:11px; text-align:right; }
      .cr-scroll { overflow-x:auto; -webkit-overflow-scrolling:touch; }
      .cr-table { border-collapse:separate; border-spacing:0; width:100%;
        min-width:980px; font-size:11px; font-variant-numeric:tabular-nums; }
      .cr-table th,.cr-table td { padding:10px 8px; text-align:center;
        border-bottom:1px solid #edf0f5; white-space:nowrap; }
      .cr-table thead th { background:#f8f9fc; color:#6b7486; font-size:9px;
        font-weight:800; letter-spacing:.045em; }
      .cr-table thead th:first-child { text-align:left; padding-left:15px; }
      .cr-table tbody tr:last-child th,.cr-table tbody tr:last-child td { border-bottom:0; }
      .cr-table tbody tr:hover { background:#fafbff; }
      .cr-series { text-align:left !important; padding-left:15px !important;
        font-size:11px; font-weight:750; color:#253047; min-width:86px; }
      .cr-series.strategy { border-left:3px solid #4f46e5; }
      .cr-series.benchmark { border-left:3px solid #94a3b8; }
      .cr-series.alpha { border-left:3px solid #d97706; }
      .cr-value { font-weight:650; }
      .cr-value.positive { color:#087443; }
      .cr-value.negative { color:#b42318; }
      .cr-value.flat,.cr-empty { color:#a0a8b7; }
      .cr-empty { background:#fbfcfe; }
      .cr-summary-head { background:#eef1ff !important; color:#4542a7 !important; }
      .cr-summary { background:#f7f8ff; font-weight:800; }
      .cr-table td.cr-summary { border-left:1px solid #e8eaff; }
      @media(max-width:640px) {
        .cr-year-head { padding:11px 12px; }
        .cr-year-head h3 { font-size:19px; }
        .cr-year-note { max-width:130px; font-size:10px; }
        .cr-table { min-width:940px; }
        .cr-table th,.cr-table td { padding:10px 7px; }
      }
    </style>
    """)
    st.html('<div class="cr-wrap">' + "".join(blocks) + '</div>')
