"""Highcharts, inlined into an st.iframe page, for charts that are not time series.

Time series use TradingView Lightweight Charts (``lw_chart.py``). Both are
vendored in ``app/components/vendor`` and drawn exactly as the Paresh app draws
them. Highcharts is used under its non-commercial licence: this app is for the
owner's personal use (see ``vendor/HIGHCHARTS_LICENSE.txt``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

_VENDOR = Path(__file__).parent / "vendor"
FONT = "<link href='https://fonts.googleapis.com/css2?family=Geist:wght@400..700&display=swap' rel='stylesheet'>"


def lib(*modules: str) -> str:
    """Highcharts Stock plus the named optional modules, as one script body."""
    out = []
    for name in ("highstock.js", *modules):
        try:
            out.append((_VENDOR / name).read_text(encoding="utf-8"))
        except OSError:
            out.append("")
    return "\n".join(out)


def script_json(obj) -> str:
    # "</" would close the <script> block that carries the data.
    return json.dumps(obj, separators=(",", ":")).replace("</", "<\\/")


def correlation_heatmap(corr: pd.DataFrame, labels: dict[str, str] | None = None) -> None:
    """Pairwise correlation as a heatmap: darker indigo moves together more."""
    keys = [k for k in corr.index if k in corr.columns]
    if len(keys) < 2:
        return
    names = [str((labels or {}).get(k, k)) for k in keys]
    data = [[xi, yi, round(float(corr.at[a, b]), 2)]
            for yi, b in enumerate(keys) for xi, a in enumerate(keys) if pd.notna(corr.at[a, b])]
    height = min(560, 70 + 44 * len(keys))
    page = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>" + FONT + "<style>*{box-sizing:border-box;margin:0}"
        "html,body{background:transparent;font-family:'Geist',system-ui,sans-serif}</style></head>"
        f"<body><div id='c' style='width:100%;height:{height}px'></div><script>"
        + lib("highcharts-heatmap.js") + "</script><script>(function(){"
        "const names=" + script_json(names) + ", data=" + script_json(data) + ";"
        "Highcharts.chart('c',{chart:{type:'heatmap',backgroundColor:'transparent',spacing:[4,4,4,4],"
        "style:{fontFamily:'Geist,system-ui,sans-serif'},animation:false},"
        "credits:{enabled:false},accessibility:{enabled:false},title:{text:null},exporting:{enabled:false},"
        "legend:{enabled:true,align:'right',layout:'vertical',verticalAlign:'middle',symbolHeight:140,"
        "itemStyle:{color:'#5E6878',fontSize:'11px'}},"
        "xAxis:{categories:names,opposite:true,labels:{style:{color:'#3C4657',fontSize:'12px'}},lineWidth:0,tickLength:0},"
        "yAxis:{categories:names,reversed:true,title:{text:null},labels:{style:{color:'#3C4657',fontSize:'12px'}},gridLineWidth:0},"
        "colorAxis:{min:-0.2,max:1,startOnTick:false,endOnTick:false,tickPositions:[0,0.25,0.5,0.75,1],"
        "labels:{format:'{value:.2f}',style:{color:'#5E6878',fontSize:'11px'}},"
        "stops:[[0,'#F4F5F8'],[0.17,'#FFFFFF'],[0.6,'#A5A0F0'],[1,'#4338CA']]},"
        "tooltip:{useHTML:true,backgroundColor:'rgba(15,23,42,.94)',borderWidth:0,shadow:false,style:{color:'#fff',fontSize:'12px'},"
        "formatter:function(){const s=this.series.xAxis.categories,t=this.series.yAxis.categories;"
        "return '<b>'+t[this.point.y]+' \\u00d7 '+s[this.point.x]+'</b><br>Correlation <b>'+this.point.value.toFixed(2)+'</b>';}},"
        "plotOptions:{heatmap:{borderWidth:2,borderColor:'#fff',animation:false}},"
        "series:[{name:'Correlation',data:data,dataLabels:{enabled:true,style:{fontSize:'12px',fontWeight:'600',textOutline:'none'},"
        "formatter:function(){return this.point.value.toFixed(2);}}}]});"
        "})();</script></body></html>"
    )
    st.iframe(page, height=height + 8)
