"""The Screener's ranking table: the Paresh app's src/ui/screener_table.py, on exposures.

One HTML table serves the desktop and the phone. It lives in an st.iframe so
it can sort by column and keep its header and first two columns pinned; below
640px its own CSS turns it into the compact phone list (rank, exposure,
12-month line, level and 3M), because Streamlit cannot tell Python how wide the
screen is.

The markup, stylesheet and script are Paresh's. What differs is the column
registry (an exposure has an index level, a score and a portfolio status where
a stock has a price, a market cap and technical filters) and the click target:
a row opens the Exposure page instead of a stock page. There is one column set,
so Paresh's Executive / Core / Full Quant densities are not carried over.
"""
from __future__ import annotations

from html import escape as _esc
from urllib.parse import quote

import numpy as np
import pandas as pd
import streamlit as st

from app.kit.theme import _spark_window_key

# (key, header, sort type). The phone list keeps only rank, exposure, path and
# the level cell, which carries the 3M return under the level.
PERIOD_WINDOWS = (1, 3, 6, 12)
_ALL = {
    "rank": ("Rank", "num"), "stock": ("Exposure", "text"), "price": ("Level", "num"),
    "dlt": ("Rank Δ", "num"),
    **{f"r{w}": (f"{w}M Ret", "num") for w in PERIOD_WINDOWS},
    "hurdle": ("12M vs cash", "num"),
    "score": ("Score", "num"), "status": ("Portfolio", "text"), "quad": ("Quadrant", "text"),
    "dd": ("Max DD", "num"),
    "spark": ("12M Path", None),
}
_KEYS = ("rank", "stock", "price", "dlt", "r1", "r3", "r6", "r12", "hurdle",
         "score", "status", "quad", "dd", "spark")
# Group labels over the columns, in order.
_GROUPS = (
    ("Identity", ("rank", "stock", "price")),
    ("Rank dynamics", ("dlt",)),
    ("Momentum", ("r1", "r3", "r6", "r12", "hurdle")),
    ("Model", ("score", "status", "quad")),
    ("Risk", ("dd",)),
    ("Trend", ("spark",)),
)
PHONE_KEEP = {"rank", "stock", "spark", "price"}

ROW_PX = 44
PHONE_ROW_PX = 44
VISIBLE_ROWS = 25

# Model action → chip tone; anything else is drawn muted.
_STATUS_TONE = {"BUY": "up", "HOLD": "up", "TRIM": "warn", "SELL": "down"}
_QUAD_TONE = {"Leading": "up", "Improving": "info", "Weakening": "warn", "Lagging": "down"}


def columns() -> list[tuple[str, str, str | None]]:
    return [(k, *_ALL[k]) for k in _KEYS]


def exposure_href(exposure_id: str) -> str:
    """The relative link to an exposure's page (the Exposure page reads ?exposure=)."""
    return f"Exposure?exposure={quote(str(exposure_id), safe='')}"


@st.cache_data(show_spinner=False, ttl=3600)
def _year_paths(window_key: str, _prices: pd.DataFrame) -> dict[str, tuple[str, bool]]:
    """Each exposure's last year of levels as a polyline, built once per window.

    About 50 points: one per week is as much as an 88px line can show.
    """
    out: dict[str, tuple[str, bool]] = {}
    step = max(1, len(_prices) // 50)
    for col in _prices.columns:
        s = pd.to_numeric(_prices[col], errors="coerce").dropna().to_numpy(dtype="float64")
        if len(s) < 5:
            continue
        pts = np.append(s[::step], s[-1]) if (len(s) - 1) % step else s[::step]
        lo, hi = float(pts.min()), float(pts.max())
        span = (hi - lo) or 1.0
        n = len(pts) - 1
        poly = " ".join(
            f"{2 + i * 84 / n:.1f},{24 - (v - lo) / span * 21:.1f}" for i, v in enumerate(pts)
        )
        out[str(col)] = (poly, bool(s[-1] >= s[0]))
    return out


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(f) else f


def signed_pct(v: float | None) -> str:
    """+12.3% / −4.5% (a true minus sign) / — for a missing value."""
    if v is None:
        return "—"
    return f"{'+' if v > 0 else '−' if v < 0 else ''}{abs(v) * 100:.1f}%"


def _pct_cell(v: float | None, cls_extra: str = "") -> str:
    if v is None:
        return f'<td class="n muted {cls_extra}" data-v="">—</td>'
    cls = "pos" if v > 0 else "neg" if v < 0 else ""
    return f'<td class="n {cls} {cls_extra}" data-v="{v:.6f}">{signed_pct(v)}</td>'


def _text(v) -> str:
    """A display string; '' for None, NaN and the literal 'None'/'nan'."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return ""
    s = str(v).strip()
    return "" if s in ("None", "nan", "NaT", "<NA>") else s


def _row_html(row: dict, cols: list, paths: dict) -> str:
    eid = _text(row.get("exposure_id"))
    eid_s = _esc(eid)
    name = _text(row.get("Exposure")) or eid
    sub = _text(row.get("Sub"))
    rank = _num(row.get("Rank"))
    level = _num(row.get("Level"))
    r3 = _num(row.get("3M"))
    cells: dict[str, str] = {}

    cells["rank"] = (f'<td class="c-rank" data-v="{rank if rank is not None else ""}">'
                     f'{int(rank) if rank is not None else "—"}</td>')
    cells["stock"] = (
        f'<td class="c-stock" data-v="{_esc(name)}"><a href="{exposure_href(eid)}" '
        f'data-stock="{eid_s}" title="Open {_esc(name)}"><span class="sym">{_esc(name)}</span>'
        f'<span class="sub">{_esc(sub)}</span></a></td>'
    )
    r3_cls = "" if r3 is None else ("pos" if r3 > 0 else "neg" if r3 < 0 else "")
    cells["price"] = (
        f'<td class="n c-price" data-v="{level if level is not None else ""}">'
        f'{format(level, ",.0f") if level is not None else "—"}'
        f'<span class="m-only {r3_cls}">{signed_pct(r3)} 3M</span></td>'
    )
    d = _num(row.get("Rank Δ"))
    if d is None:
        cells["dlt"] = '<td class="n muted" data-v="">—</td>'
    else:
        was = _num(row.get("Rebalance rank"))
        now = _num(row.get("Portfolio rank"))
        title = (f' title="#{int(was)} at the rebalance, #{int(now)} today"'
                 if was is not None and now is not None else "")
        chip = ("up", f"▲ {int(d)}") if d > 0 else ("down", f"▼ {abs(int(d))}") if d < 0 else ("flat", "— 0")
        cells["dlt"] = f'<td class="n" data-v="{d}"{title}><span class="chip {chip[0]}">{chip[1]}</span></td>'
    for w in PERIOD_WINDOWS:
        cells[f"r{w}"] = _pct_cell(_num(row.get(f"{w}M")))
    cells["hurdle"] = _pct_cell(_num(row.get("12M vs cash")))
    sc = _num(row.get("Score"))
    cells["score"] = (f'<td class="n{"" if sc is None else " pos" if sc > 0 else " neg"}" '
                      f'data-v="{"" if sc is None else sc}">{"—" if sc is None else f"{sc:+.2f}"}</td>')
    status = _text(row.get("Portfolio"))
    tone = _STATUS_TONE.get(status.upper())
    status_html = (f'<span class="badge {tone}">{_esc(status.title())}</span>' if tone
                   else f'<span class="muted">{_esc(status) or "—"}</span>')
    cells["status"] = f'<td data-v="{_esc(status)}">{status_html}</td>'
    quad = _text(row.get("Quadrant"))
    q_tone = _QUAD_TONE.get(quad, "")
    cells["quad"] = (f'<td data-v="{_esc(quad)}">'
                     + (f'<span class="badge {q_tone}">{_esc(quad)}</span>' if quad else '<span class="muted">—</span>')
                     + "</td>")
    dd = _num(row.get("Max DD"))
    cells["dd"] = (f'<td class="n neg" data-v="{"" if dd is None else dd}">'
                   f'{"—" if dd is None else f"−{abs(dd) * 100:.1f}%"}</td>')
    poly, up = paths.get(eid, ("", True))
    cells["spark"] = (
        f'<td class="c-path"><svg width="88" height="26" viewBox="0 0 88 26" aria-hidden="true">'
        f'<polyline fill="none" stroke="{"#067647" if up else "#B42318"}" stroke-width="1.7" '
        f'stroke-linejoin="round" stroke-linecap="round" points="{poly}"/></svg></td>'
        if poly else '<td class="c-path muted">—</td>'
    )
    return f'<tr data-stock="{eid_s}">' + "".join(cells[c[0]] for c in cols) + "</tr>"


# Paresh's stylesheet, plus .badge for the portfolio and quadrant columns.
_CSS = """
*{box-sizing:border-box}
body{margin:0;font-family:'Geist',-apple-system,'Segoe UI',Roboto,sans-serif;color:#0E1726;background:transparent;-webkit-font-smoothing:antialiased}
.wrap{height:100vh;overflow:auto;background:#FFFFFF;border:1px solid #E3E6EB;border-radius:16px}
table{border-collapse:separate;border-spacing:0;width:100%;min-width:1180px}
thead th{position:sticky;top:0;z-index:3;background:#F4F5F8;border-bottom:1px solid #E3E6EB;height:42px;padding:0 10px;
  font-size:12px;font-weight:600;color:#5E6878;text-align:right;white-space:nowrap;cursor:pointer;user-select:none}
thead th.t-left{text-align:left}
thead th{text-transform:uppercase;letter-spacing:.04em;font-size:11.5px}
thead tr.grp-row th{font-size:11px}
td.n.pos,td.n.neg{font-weight:600}
thead tr.grp-row th{top:0;height:28px;font-size:11px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;text-align:center;color:#5E6878;border-bottom:1px solid #E3E6EB;border-left:1px solid #E3E6EB;cursor:default}
thead tr.grp-row + tr.hdr th{top:28px}
.badge{display:inline-block;font-size:11.5px;font-weight:600;padding:1px 7px;border-radius:6px;background:#F1F3F6;color:#3C4657;border:1px solid #E3E6EB}
.badge.up{background:#E8F5EE;color:#067647;border-color:#CDEBDA}.badge.down{background:#FDEDEB;color:#B42318;border-color:#F6D3CE}
.badge.warn{background:#FFF6E6;color:#B54708;border-color:#F8E1B8}.badge.info{background:#EEF0FF;color:#3730A3;border-color:#DCDFFB}
td.c-stock .sub{display:none}
thead th[data-type=""]{cursor:default}
thead th .ar{color:#A5ACB8;margin-left:3px}
thead th.on{color:#0E1726}
thead th.on .ar{color:#4F46E5}
td{height:""" + str(ROW_PX) + """px;padding:0 10px;border-bottom:1px solid #EDEFF3;font-size:13.5px;white-space:nowrap;background:#FFFFFF}
tbody tr:nth-child(even) td{background:#FAFBFC}
tbody tr:hover td{background:#F1F0FF;cursor:pointer}
td.n{text-align:right;font-family:'Geist Mono',ui-monospace,Menlo,monospace;font-variant-numeric:tabular-nums}
.pos{color:#067647}.neg{color:#B42318}.muted{color:#667080}
th:nth-child(1),td.c-rank{position:sticky;left:0;z-index:2;width:52px;min-width:52px;text-align:left}
thead th:nth-child(1){z-index:4}
th:nth-child(2),td.c-stock{position:sticky;left:52px;z-index:2;text-align:left;max-width:380px;box-shadow:1px 0 0 #EDEFF3}
thead th:nth-child(2){z-index:4}
td.c-rank{font-family:'Geist Mono',ui-monospace,monospace;font-weight:600}
td.c-stock a{display:flex;flex-direction:column;align-items:flex-start;gap:1px;min-width:0;line-height:1.2;text-decoration:none;color:inherit}
td.c-stock .sym{font-weight:650;font-size:14px;color:#0E1726}
td.c-stock .sub{font-size:12px;color:#5E6878;overflow:hidden;text-overflow:ellipsis;max-width:340px}
.chip{display:inline-block;font-family:'Geist Mono',ui-monospace,monospace;font-size:12px;font-weight:600;padding:2px 7px;border-radius:7px}
.chip.up{background:#E8F5EE;color:#067647}.chip.down{background:#FDEDEB;color:#B42318}.chip.flat{background:#F1F3F6;color:#5E6878}
td.c-path{padding-left:14px}
.m-only{display:none}
@media (min-width:641px){td.c-stock .sub{display:block}}
@media (max-width:640px){
  table{min-width:0}
  th,td{padding:0 8px}
  td{height:""" + str(PHONE_ROW_PX) + """px}
  .d-only{display:none}
  th:nth-child(1),td.c-rank{width:34px;min-width:34px}
  th:nth-child(2),td.c-stock{left:34px;box-shadow:none;max-width:150px}
  td.c-stock .sym{font-size:14px;overflow:hidden;text-overflow:ellipsis;max-width:140px}
  td.c-stock .sub{display:block;font-size:12px;max-width:130px}
  tr.grp-row{display:none}
  thead tr.hdr th{top:0}
  td.c-path{padding-left:0}
  td.c-path svg{width:54px}
  th .lbl-d{display:none}
  td.c-price{line-height:1.25}
  .m-only{display:block;font-size:12px;font-weight:600}
}
"""

# Opening an exposure. This frame may not navigate the page around it (no
# allow-top-navigation), but it has allow-same-origin, so it adds a script to
# the parent document -- which navigates itself, as it is always allowed to.
# The Exposure page sits next to the Screener, so its path is the parent's with
# the last segment replaced (that keeps Streamlit Cloud's /~/+/ prefix).
# If the parent is ever cross-origin the injection throws, and allow-popups
# opens the exposure in a new tab instead.
_JS = """
function openStock(id){
  const rel='Exposure?exposure='+encodeURIComponent(id);
  try{const host=window.parent;const base=host.location.pathname.replace(/[^\\/]*$/,'');
      const s=host.document.createElement('script');
      s.textContent='window.location.href='+JSON.stringify(base+rel)+';';
      host.document.body.appendChild(s);s.remove();}
  catch(e){window.open(rel,'_blank');}
}
document.addEventListener('click',function(ev){
  const tr=ev.target.closest?ev.target.closest('tr[data-stock]'):null;
  if(!tr)return;
  if(ev.target.closest('a')&&(ev.metaKey||ev.ctrlKey||ev.shiftKey||ev.button===1))return;
  ev.preventDefault();openStock(tr.getAttribute('data-stock'));
});
const ths=document.querySelectorAll('thead tr.hdr th');const tbody=document.querySelector('tbody');
ths.forEach(function(th,i){
  const type=th.getAttribute('data-type');if(!type)return;
  th.addEventListener('click',function(){
    const dir=th.getAttribute('data-dir')==='asc'?'desc':'asc';
    ths.forEach(function(o){o.removeAttribute('data-dir');o.classList.remove('on');const a=o.querySelector('.ar');if(a&&o.getAttribute('data-type'))a.textContent='↕';});
    th.setAttribute('data-dir',dir);th.classList.add('on');th.querySelector('.ar').textContent=dir==='asc'?'↑':'↓';
    const rows=Array.from(tbody.rows);
    rows.sort(function(a,b){
      const va=a.cells[i].getAttribute('data-v'),vb=b.cells[i].getAttribute('data-v');
      const ea=(va===null||va===''),eb=(vb===null||vb==='');
      if(ea||eb)return ea===eb?0:(ea?1:-1);
      if(type==='num'){const d=parseFloat(va)-parseFloat(vb);return dir==='asc'?d:-d;}
      return dir==='asc'?va.localeCompare(vb):vb.localeCompare(va);
    });
    rows.forEach(function(r){tbody.appendChild(r);});
  });
});
"""


def table_html(view: pd.DataFrame, prices_df: pd.DataFrame | None, *, sorted_by: str = "rank",
               ascending: bool = True, group_labels: dict[str, str] | None = None) -> str:
    """The whole table document, for st.iframe. Split out so tests can read it.

    `view` carries the display columns built by app/components/screener.py
    (Rank, Exposure, Sub, Level, Rank Δ, 1M … 12M, 12M vs cash, Score,
    Portfolio, Quadrant, Max DD) and exposure_id; `prices_df` is the index
    panel, one column per exposure_id. `sorted_by` is the column key whose
    header carries the arrow; `group_labels` renames a group (the Momentum
    group reads "vs Nifty 50" when the returns are relative).
    """
    cols = columns()
    paths: dict = {}
    if prices_df is not None and not prices_df.empty:
        window = prices_df.iloc[-min(252, len(prices_df)):]
        paths = _year_paths(_spark_window_key(window), window)
    head_cells = []
    for k, label, t in cols:
        cls = ("t-left " if (k in ("rank", "stock") or t == "text") else "") + (
            "" if k in PHONE_KEEP else "d-only")
        on = k == sorted_by
        if on:
            cls += " on"
        arrow = ('<span class="ar">' + (("↑" if ascending else "↓") if on else "↕") + "</span>") if t else ""
        dir_attr = f' data-dir="{"asc" if ascending else "desc"}"' if on else ""
        head_cells.append(
            f'<th class="{cls.strip()}" data-type="{t or ""}"{dir_attr}>'
            f'<span class="{"lbl-d" if k == "spark" else ""}">{_esc(label)}</span>{arrow}</th>'
        )
    head = "".join(head_cells)
    present = [c[0] for c in cols]
    renames = group_labels or {}
    parts = []
    for label, keys in _GROUPS:
        n = sum(1 for k in keys if k in present)
        if n:
            parts.append(f'<th colspan="{n}" class="grp">{_esc(renames.get(label, label))}</th>')
    group_row = '<tr class="grp-row">' + "".join(parts) + "</tr>"
    body_html = "".join(_row_html(row, cols, paths) for row in view.to_dict("records"))
    # Desktop-only cells are hidden by position too, so the phone hides whole
    # columns rather than leaving a header without its cells.
    hide = [i for i, c in enumerate(cols) if c[0] not in PHONE_KEEP]
    extra = "@media (max-width:640px){" + ",".join(f"td:nth-child({i + 1})" for i in hide) + "{display:none}}"
    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<link rel='preconnect' href='https://fonts.googleapis.com'>"
        "<link href='https://fonts.googleapis.com/css2?family=Geist:wght@400..700&"
        "family=Geist+Mono:wght@400..700&display=swap' rel='stylesheet'>"
        f"<style>{_CSS}@media (min-width:641px){{table{{min-width:{max(1180, len(cols) * 92)}px}}}}{extra}</style></head>"
        f"<body><div class='wrap'><table>"
        f"<thead>{group_row}<tr class=\"hdr\">{head}</tr></thead><tbody>{body_html}</tbody></table></div>"
        f"<script>{_JS}</script></body></html>"
    )


def render_screener_table(view: pd.DataFrame, prices_df: pd.DataFrame | None, **kwargs) -> None:
    if view.empty:
        st.info("No exposures match these filters. Clear the search or pick another preset.")
        return
    rows = min(len(view), VISIBLE_ROWS)
    height = 44 + rows * ROW_PX + 4 + 28
    st.iframe(table_html(view, prices_df, **kwargs), height=height)
