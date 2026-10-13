"""Highcharts charts that are not time series, copied from the Paresh app."""
from __future__ import annotations

import pandas as pd
import streamlit as st


def render_correlation_heatmap(corr: pd.DataFrame, syms: list[str]) -> None:
    """Pairwise correlation of the given stocks as a Highcharts heatmap.

    Darker indigo = move together more; the tooltip names both stocks and the
    value, and cells carry the number when there is room for it.
    """
    from app.kit.highcharts_lib import lib, script_json

    syms = [s for s in syms if s in corr.index]
    if len(syms) < 2:
        return
    sub = corr.loc[syms, syms]
    data = []
    for yi, b in enumerate(syms):
        for xi, a in enumerate(syms):
            v = sub.at[a, b]
            if pd.notna(v):
                data.append([xi, yi, round(float(v), 2)])
    n = len(syms)
    height = min(720, 90 + 26 * n)
    page = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><style>*{box-sizing:border-box;margin:0}"
        "html,body{background:transparent;font-family:'Geist',system-ui,sans-serif}</style></head>"
        "<body><div id='c' style='width:100%;height:" + str(height) + "px'></div><script>"
        + lib("highcharts-heatmap.js") + "</script><script>(function(){"
        "const syms=" + script_json(syms) + ", data=" + script_json(data) + ";"
        "const wide=document.getElementById('c').clientWidth/syms.length>=30;"
        "Highcharts.chart('c',{chart:{type:'heatmap',backgroundColor:'transparent',spacing:[4,4,4,4],"
        "style:{fontFamily:'Geist,system-ui,sans-serif'},animation:false},"
        "credits:{enabled:false},accessibility:{enabled:false},title:{text:null},legend:{enabled:true,"
        "align:'right',layout:'vertical',verticalAlign:'middle',symbolHeight:150,itemStyle:{color:'#5E6878',fontSize:'11px'}},"
        "exporting:{enabled:false},"
        "xAxis:{categories:syms,opposite:true,labels:{rotation:-60,style:{color:'#3C4657',fontSize:'11px'}},lineWidth:0,tickLength:0},"
        "yAxis:{categories:syms,reversed:true,title:{text:null},labels:{style:{color:'#3C4657',fontSize:'11px'}},gridLineWidth:0},"
        "colorAxis:{min:-0.2,max:1,startOnTick:false,endOnTick:false,tickPositions:[0,0.25,0.5,0.75,1],labels:{format:'{value:.2f}',style:{color:'#5E6878',fontSize:'11px'}},stops:[[0,'#F4F5F8'],[0.17,'#FFFFFF'],[0.6,'#A5A0F0'],[1,'#4338CA']]},"
        "tooltip:{useHTML:true,backgroundColor:'rgba(15,23,42,.94)',borderWidth:0,shadow:false,style:{color:'#fff',fontSize:'12px'},"
        "formatter:function(){const s=this.series.xAxis.categories,t=this.series.yAxis.categories;"
        "const e=v=>String(v).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "return '<b>'+e(t[this.point.y])+' \\u00d7 '+e(s[this.point.x])+'</b><br>Correlation <b>'+this.point.value.toFixed(2)+'</b>';}},"
        "plotOptions:{heatmap:{borderWidth:1,borderColor:'#fff',animation:false}},"
        "series:[{name:'Correlation',data:data,dataLabels:{enabled:wide,style:{fontSize:'10px',fontWeight:'500',textOutline:'none'},"
        "formatter:function(){return this.point.value.toFixed(2);}}}]});"
        "})();</script></body></html>"
    )
    st.iframe(page, height=height + 8)


def render_columns(
    categories: list[str],
    values: list[float],
    colors: list[str],
    *,
    height: int = 260,
    unit: str = "",
    lines: list[tuple[float, str, str]] | None = None,
    x_title: str | None = None,
) -> None:
    """A Highcharts column chart for a distribution: one bar per category.

    `lines` are vertical markers in category-index units, (position, colour,
    label), e.g. zero or a median falling between two bins. The tooltip names
    the category and the value with `unit`.
    """
    from app.kit.highcharts_lib import lib, script_json

    if not categories:
        return
    data = [{"y": float(v), "color": c} for v, c in zip(values, colors)]
    marks = [{"value": float(p), "color": c, "width": 1.4, "dashStyle": "ShortDot", "zIndex": 5,
              "label": {"text": t, "rotation": 0, "y": 12, "style": {"color": c, "fontSize": "11px"}}}
             for p, c, t in (lines or [])]
    page = (
        "<!DOCTYPE html><html><head><meta charset='utf-8'><style>*{box-sizing:border-box;margin:0}"
        "html,body{background:transparent;font-family:'Geist',system-ui,sans-serif}</style></head>"
        "<body><div id='c' style='width:100%;height:" + str(height) + "px'></div><script>"
        + lib() + "</script><script>(function(){"
        "const cats=" + script_json(categories) + ", data=" + script_json(data) + ", marks="
        + script_json(marks) + ", unit=" + script_json(unit) + ", xt=" + script_json(x_title) + ";"
        "Highcharts.chart('c',{chart:{type:'column',backgroundColor:'transparent',spacing:[8,4,4,4],"
        "style:{fontFamily:'Geist,system-ui,sans-serif'},animation:false},"
        "credits:{enabled:false},accessibility:{enabled:false},title:{text:null},legend:{enabled:false},"
        "exporting:{enabled:false},navigator:{enabled:false},scrollbar:{enabled:false},rangeSelector:{enabled:false},"
        "xAxis:{categories:cats,lineColor:'#E3E6EB',tickLength:0,plotLines:marks,"
        "title:{text:xt,style:{color:'#5E6878',fontSize:'11px'}},"
        "labels:{style:{color:'#5E6878',fontSize:'10px'}}},"
        "yAxis:{title:{text:null},gridLineColor:'#EDEFF3',allowDecimals:false,"
        "labels:{style:{color:'#5E6878',fontSize:'11px'}}},"
        "tooltip:{useHTML:true,backgroundColor:'rgba(15,23,42,.94)',borderWidth:0,shadow:false,"
        "style:{color:'#fff',fontSize:'12px'},"
        "formatter:function(){const e=v=>String(v).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));"
        "return '<b>'+e(cats[this.point.index])+'</b><br>'+this.y+(unit?' '+e(unit):'');}},"
        "plotOptions:{column:{borderWidth:0,borderRadius:2,groupPadding:0.04,pointPadding:0.02,animation:false}},"
        "series:[{name:'Count',data:data}]});"
        "})();</script></body></html>"
    )
    st.iframe(page, height=height + 8)
