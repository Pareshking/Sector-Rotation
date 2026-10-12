"""Highcharts, vendored and inlined into an st.iframe page.

Used where the chart is not a time series (the Relative Rotation Graph, the
correlation heatmap). Time series use TradingView Lightweight Charts
(app/kit/lw_chart.py). Highcharts is under the Highsoft EULA, non-commercial
personal use; see app/kit/vendor/HIGHCHARTS_LICENSE.txt.
"""
from __future__ import annotations

import json
from pathlib import Path

_VENDOR = Path(__file__).parent / "vendor"


def lib(*modules: str) -> str:
    """The Highcharts Stock core plus the named optional modules, as one script body."""
    names = ["highstock.js", *modules]
    out = []
    for name in names:
        try:
            out.append((_VENDOR / name).read_text(encoding="utf-8"))
        except OSError:
            out.append("")
    return "\n".join(out)


def script_json(obj) -> str:
    # "</" would close the <script> block that carries the data.
    return json.dumps(obj, separators=(",", ":")).replace("</", "<\\/")
