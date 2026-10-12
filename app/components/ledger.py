"""Ledger tables: the Paresh app's clean, sortable HTML table, with explicit column formats.

``st.dataframe`` is a canvas grid: it cannot colour a sign, draw a badge or
show a dash for a gap. These tables are one small HTML document per table
(rendered in an ``st.iframe``), with a sticky header and click-to-sort on the
raw value of every cell (``data-v``), never on its formatted text.

A column is ``Col(field, kind, label)``. Kinds:

    text     plain text                       name     bold first column
    pct      a percent, signed and coloured    pctp     a percent, plain (weights)
    rupee    ₹ with Indian digit grouping      rupees   ₹, signed and coloured
    num      two decimals                      int      whole number
    units    whole, or three decimals
    date     "01 Oct 2026"                     badge    an action or status pill
"""

from __future__ import annotations

import html
import math
from dataclasses import dataclass
from typing import Sequence

import pandas as pd
import streamlit as st

DASH = "—"
ROW_PX, HEAD_PX = 44, 42

# Records say what happened (Bought / Sold / Held), as the Paresh app's do.
_BADGES = {
    "BUY": ("Bought", "g"), "SELL": ("Sold", "r"), "HOLD": ("Held", "n"), "TRIM": ("Trimmed", "y"),
    "OPEN": ("Open", "g"), "CLOSED": ("Closed", "n"), "CASH": ("Cash", "b"),
}


@dataclass(frozen=True)
class Col:
    field: str
    kind: str = "text"
    label: str | None = None


def inr(value: float, decimals: int = 0) -> str:
    """Indian digit grouping: 12,34,567."""
    negative = value < 0
    whole, _, frac = f"{abs(value):.{decimals}f}".partition(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return ("−" if negative else "") + whole + (f".{frac}" if frac else "")


def _missing(value) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _cell(value, kind: str) -> tuple[str, str, str]:
    """(display html, css class, sort value)."""
    if _missing(value) or (isinstance(value, str) and not value.strip()):
        return DASH, "c mute", ""
    if kind in ("text", "name"):
        text = html.escape(str(value))
        return (f"<b>{text}</b>" if kind == "name" else text), "l", str(value).lower()
    if kind == "badge":
        label, tone = _BADGES.get(str(value).upper(), (str(value).title(), "n"))
        return f'<span class="pill {tone}">{html.escape(label)}</span>', "c", label
    if kind == "date":
        stamp = pd.Timestamp(value)
        return f"{stamp:%d %b %Y}", "r", f"{stamp:%Y%m%d}"
    number = float(value)
    if not math.isfinite(number):
        return DASH, "c mute", ""
    sort = repr(number)
    if kind == "pct":
        tone = "up" if number > 0 else ("dn" if number < 0 else "mute")
        return f'{"+" if number > 0 else ("−" if number < 0 else "")}{abs(number):.1f}%', f"r {tone}", sort
    if kind == "pctp":
        return f"{number:.1f}%", "r", sort
    if kind == "rupee":
        return f"₹{inr(number)}", "r", sort
    if kind == "rupees":
        tone = "up" if number > 0 else ("dn" if number < 0 else "mute")
        return f'{"+" if number > 0 else ""}₹{inr(number)}', f"r {tone}", sort
    if kind == "price":
        return f"₹{inr(number, 2)}", "r", sort
    if kind == "int":
        return inr(round(number)), "r", sort
    if kind == "units":  # whole ETF units, or index-fund units to three decimals
        return (inr(number) if float(number).is_integer() else f"{number:,.3f}"), "r", sort
    return f"{number:,.2f}", "r", sort


_CSS = """
*{box-sizing:border-box}html,body{margin:0;background:transparent}
body{font-family:'Geist',system-ui,-apple-system,'Segoe UI',sans-serif;color:#0E1726}
.w{width:100%;max-height:var(--h);overflow:auto;border:1px solid #E3E6EB;border-radius:10px;background:#fff;
box-shadow:0 1px 2px rgba(14,23,38,.03);scrollbar-width:thin}
table{width:max-content;min-width:100%;border-collapse:separate;border-spacing:0;font-size:13.5px;white-space:nowrap}
th{position:sticky;top:0;z-index:2;background:#F4F5F8;color:#5E6878;font-size:12px;font-weight:600;height:42px;
padding:0 12px;border-bottom:1px solid #E3E6EB;cursor:pointer;user-select:none;text-align:right}
th:hover{background:#E9EBF0;color:#0E1726}th.l{text-align:left}th.c{text-align:center}
th[data-dir=asc]:after{content:' ▲';font-size:8px;color:#4F46E5}th[data-dir=desc]:after{content:' ▼';font-size:8px;color:#4F46E5}
td{height:44px;padding:0 12px;border-bottom:1px solid #EDEFF3;background:#fff;text-align:right}
tr:last-child td{border-bottom:0}tr:hover td{background:#F7F8FA}
td.l{text-align:left}td.c{text-align:center}
td.r{font-family:'Geist Mono',ui-monospace,monospace;font-variant-numeric:tabular-nums;font-size:13px}
td b{font-weight:650;font-size:14px}
.up{color:#067647}.dn{color:#B42318}.mute{color:#98A1AE}
.pill{display:inline-block;font-family:'Geist Mono',ui-monospace,monospace;font-size:12px;font-weight:600;padding:2px 8px;border-radius:7px;border:1px solid}
.pill.g{background:#E8F5EE;color:#067647;border-color:#B7E0C8}.pill.r{background:#FDEDEB;color:#912018;border-color:#F3C7C1}
.pill.n{background:#F4F5F8;color:#5E6878;border-color:#E3E6EB}.pill.y{background:#FEF6EA;color:#B54708;border-color:#F7D7A8}
.pill.b{background:#EFF7FC;color:#0369A1;border-color:#BFDDF0}
td.wrap{white-space:normal;min-width:260px;max-width:520px;font-family:inherit;font-size:12.5px;color:#3C4657;text-align:left;line-height:1.4;padding:8px 12px}
@media(max-width:640px){th:first-child,td:first-child{position:sticky;left:0;z-index:1;box-shadow:6px 0 8px -8px rgba(14,23,38,.35)}th:first-child{z-index:3}}
"""

_JS = """
document.querySelectorAll('th').forEach((th,i)=>th.addEventListener('click',()=>{
  const dir=th.dataset.dir==='desc'?'asc':'desc';
  document.querySelectorAll('th').forEach(o=>delete o.dataset.dir);th.dataset.dir=dir;
  const body=document.querySelector('tbody');const rows=[...body.rows];
  rows.sort((a,b)=>{const x=a.cells[i].dataset.v,y=b.cells[i].dataset.v;
    if(x===''||y==='')return x===y?0:(x===''?1:-1);
    const nx=parseFloat(x),ny=parseFloat(y);
    const c=(!isNaN(nx)&&!isNaN(ny)&&String(nx)!=='NaN'&&/^[-0-9.e+]+$/i.test(x)&&/^[-0-9.e+]+$/i.test(y))?nx-ny:x.localeCompare(y);
    return dir==='asc'?c:-c;});
  rows.forEach(r=>body.appendChild(r));}));
"""


def table_html(frame: pd.DataFrame, columns: Sequence[Col], max_height: int = 620, wrap: Sequence[str] = ()) -> str:
    present = [c for c in columns if c.field in frame.columns]
    head = "".join(
        f'<th class="{"l" if c.kind in ("text", "name") else ("c" if c.kind == "badge" else "")}">'
        f"{html.escape(c.label or c.field)}</th>"
        for c in present
    )
    rows = []
    for record in frame.to_dict("records"):
        cells = []
        for c in present:
            shown, cls, sort = _cell(record.get(c.field), c.kind)
            if c.field in wrap and cls == "l":
                cls = "wrap"
            cells.append(f'<td class="{cls}" data-v="{html.escape(sort, quote=True)}">{shown}</td>')
        rows.append(f"<tr>{''.join(cells)}</tr>")
    height = min(max_height, HEAD_PX + ROW_PX * max(len(frame), 1) + 4)
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<link rel='preconnect' href='https://fonts.googleapis.com'>"
        "<link href='https://fonts.googleapis.com/css2?family=Geist:wght@400..700&family=Geist+Mono:wght@400..700"
        "&display=swap' rel='stylesheet'>"
        f"<style>:root{{--h:{height}px}}{_CSS}</style></head><body>"
        f"<div class='w'><table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
        f"<script>{_JS}</script></body></html>"
    ), height


def ledger_table(frame: pd.DataFrame, columns: Sequence[Col], max_height: int = 620, wrap: Sequence[str] = (),
                 empty: str = "Nothing to show yet.") -> None:
    """Render ``frame`` as a sortable ledger table showing only ``columns``, in order."""
    if frame is None or frame.empty:
        st.caption(empty)
        return
    markup, height = table_html(frame, columns, max_height, wrap)
    # A wrapped column grows rows; give the frame room rather than an inner scrollbar.
    extra = 0 if not wrap else min(max_height, height + 18 * len(frame)) - height
    st.iframe(markup, height=height + extra + 6)


__all__ = ["Col", "DASH", "inr", "ledger_table", "table_html"]
