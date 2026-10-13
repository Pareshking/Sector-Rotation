"""Screener: the Paresh app's Screener (src/ui/views/ranking_view.py), on sector and theme indices.

The layout, the toolbar, the table and the movement cards are Paresh's own
(``app/kit``). What differs is only the data: one row per exposure from
``load_decisions()`` instead of one per stock, and a row opens the Exposure
page instead of a stock page. The figures are decided in
``app/components/screener.py``.
"""

from __future__ import annotations

import html
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.components import screener as scr  # noqa: E402
from app.data import (  # noqa: E402
    current_regime,
    load_backtest,
    load_decisions,
    load_index_panel,
    load_portfolio,
    strategy_config,
    vehicle_frame,
)
from app.kit.screener_table import (  # noqa: E402
    exposure_href,
    render_screener_table,
    signed_pct,
)

BASES = ("Absolute", "vs Nifty 50")
_SORT_MIRROR = "_rank_sort_by_idx"
_BASIS_MIRROR = "_rank_basis_idx"


def _head():
    """One row: the title and Export CSV, as Paresh draws it (no subtitle)."""
    head = st.container(key="scr_head", horizontal=True, vertical_alignment="center", gap="medium", wrap=True)
    head.html('<div class="scr-head"><h1>Screener</h1></div>', width="content")
    head.html("<span></span>", width="stretch")
    return head.container(width="content")


decisions = load_decisions()
if decisions.empty:
    _head()
    st.info("No prepared ranking dataset is available.")
    st.stop()

panel, _ = load_index_panel()
regime = current_regime()
hurdle = regime.cash_12m if regime is not None else None
buffer = int(strategy_config().retention_buffer_m)
live = load_portfolio()
rebalance = pd.Timestamp(live.target.as_of) if live is not None else None
as_of = panel.index.max() if not panel.empty else pd.Timestamp.today().normalize()
levels = panel.ffill().iloc[-1] if not panel.empty else pd.Series(dtype=float)
funds = scr.fund_counts(vehicle_frame(), as_of)
# The month-end decision chain, for 1M Δ and 3M Δ: the same TargetPortfolio
# objects the backtest and the live book are built from (cached across pages).
backtest = load_backtest()
chain = backtest.decisions if backtest is not None and backtest.ok else []
ranks_1m, ranks_3m = scr.past_ranks(chain, 1), scr.past_ranks(chain, 3)
drawdown_3m = scr.max_drawdown(panel)
search_opts, by_name, by_index = scr.search_options(decisions)

c_export = _head()

# ── Search, presets, sort ───────────────────────────────────────────────────
masks = scr.preset_masks(decisions, hurdle, buffer)
counts = {p: int(m.sum()) for p, m in masks.items()}


def _open_searched_exposure() -> None:
    # Choosing an exposure opens its page, like every other exposure link, so
    # the search box is how you get to any exposure by name. An index filters.
    val = st.session_state.get("rank_search_predictive")
    if val in by_name:
        st.session_state["detail_exposure"] = val
        st.session_state["_scr_open_exposure"] = True
        st.session_state["rank_search_predictive"] = None


def _reset_screener_filters() -> None:
    # Popped, not assigned: each widget passes its own default, and a
    # session-state value on top of a default makes Streamlit warn on the page.
    for key in ("rank_category_filter", "rank_sort_by", "rank_basis", "rank_quick_pills"):
        st.session_state.pop(key, None)
    st.session_state[_SORT_MIRROR] = 0
    st.session_state[_BASIS_MIRROR] = 0


def _mirror(key: str, size: int) -> int:
    value = st.session_state.get(key, 0)
    return value if isinstance(value, int) and 0 <= value < size else 0


with st.container(key="scr_toolbar", horizontal=True, vertical_alignment="center", gap="small"):
    selected_search = st.selectbox(
        "Search exposure or index",
        options=search_opts,
        index=None,
        placeholder="Search exposure or index",
        key="rank_search_predictive",
        label_visibility="collapsed",
        on_change=_open_searched_exposure,
        width=260,
    )
    preset = st.pills(
        "Presets",
        list(scr.PRESETS),
        default=scr.DEFAULT_PRESET,
        required=True,
        format_func=lambda o: scr.preset_label(o, counts[o], buffer),
        key="rank_quick_pills",
        label_visibility="collapsed",
        width="content",
    ) or scr.DEFAULT_PRESET
    with st.popover("Filters & sort", icon=":material/tune:", width="content"), \
            st.container(key="scr_filters"):
        # On a phone theme.py pins this panel to the bottom of the screen as a
        # sheet; on a desktop it is an ordinary dropdown.
        categories = st.pills(
            "Category", ["sector", "thematic"], selection_mode="multi",
            format_func=lambda c: scr.CATEGORY_LABEL.get(c, c), key="rank_category_filter",
        )
        # Resolved through a mirror: under st.navigation a widget key is
        # discarded when the reader visits another page, and `default` is what
        # brings the choice back.
        sort_by = st.segmented_control(
            "Sort by", list(scr.SORTS), default=scr.SORTS[_mirror(_SORT_MIRROR, len(scr.SORTS))],
            required=True, key="rank_sort_by",
        ) or scr.SORTS[0]
        st.session_state[_SORT_MIRROR] = scr.SORTS.index(sort_by)
        basis = st.segmented_control(
            "Returns", list(BASES), default=BASES[_mirror(_BASIS_MIRROR, len(BASES))],
            required=True, key="rank_basis",
        ) or BASES[0]
        st.session_state[_BASIS_MIRROR] = BASES.index(basis)
        st.caption("Click a column header in the table to sort by it too.")
        st.button("Reset", key="rank_filters_reset", type="tertiary", on_click=_reset_screener_filters)

if st.session_state.pop("_scr_open_exposure", False):
    st.switch_page("views/4_Exposure.py")

relative = basis == BASES[1]
table = scr.display_frame(decisions, levels, funds, hurdle, relative=relative, ranks_1m=ranks_1m,
                          ranks_3m=ranks_3m, drawdown_3m=drawdown_3m,
                          portfolio_ranked=preset in scr.PORTFOLIO_RANKED)
rows = masks.get(preset, masks[scr.DEFAULT_PRESET])
if selected_search in by_index:
    rows = rows & decisions["exposure_id"].astype(str).isin(by_index[selected_search])
if categories:
    rows = rows & decisions["category"].isin(categories)
view = scr.sort_frame(table[rows], sort_by)

key, ascending = scr.SORT_KEYS[sort_by]
render_screener_table(view, panel, sorted_by=key, ascending=ascending,
                      group_labels={w: f"{w} vs Nifty 50" for w in ("1M", "3M", "6M", "12M")} if relative else None)

# Export every column the ranking carries, the on-screen ones first, so the
# file can be audited against the score behind the rank.
shown = view.drop(columns=["Sub"])
extra = decisions.loc[view.index, [c for c in decisions.columns if c not in shown.columns]]
export_df = pd.concat([shown, extra], axis=1)
c_export.download_button(
    "Export CSV",
    export_df.to_csv(index=False).encode(),
    f"sector_rotation_screener_{as_of:%Y%m%d}.csv",
    "text/csv",
    key="dl_rank_csv",
    icon=":material/download:",
    help=f"The {len(view)} exposures shown, with all {export_df.shape[1]} ranking columns.",
    width="stretch",
)


# ── Movement since the last rebalance (Paresh's render_top50_changes) ───────
def render_rank_changes(frame: pd.DataFrame) -> None:
    risers, fallers = scr.movers(frame)
    if risers.empty and fallers.empty:
        return
    since = f"the {rebalance:%d %b} rebalance" if rebalance is not None else "the last rebalance"

    def esc(value) -> str:
        return html.escape(str(value))

    def row_html(i: int, row, extra: bool = False) -> str:
        delta = int(row["1M Δ"])
        tone = "positive" if delta > 0 else ("negative" if delta < 0 else "flat")
        ret = signed_pct(None if pd.isna(row["1M"]) else float(row["1M"]))
        ret_tone = "negative" if ret.startswith("−") else ("flat" if ret == "—" else "positive")
        return (
            f'<div class="t50-row{" t50-extra" if extra else ""}">'
            f'<span class="t50-num">{i}</span>'
            f'<span class="t50-stock-cell"><a class="t50-stock" href="{exposure_href(row["exposure_id"])}" '
            f'target="_self">{esc(row["Exposure"])}</a></span>'
            f'<span class="t50-cell t50-change"><span class="t50-delta {tone}">{"+" if delta > 0 else ""}{delta}'
            '</span></span>'
            f'<span class="t50-cell t50-rank">{int(row["Portfolio rank"])}</span>'
            f'<span class="t50-cell t50-return {ret_tone}">{esc(ret)}</span>'
            "</div>"
        )

    def card(title: str, subtitle: str, icon: str, tone: str, rows) -> str:
        # A hidden checkbox holds the open/closed state; the "View all" button
        # under the rows is its label, so it works without JS.
        rows = list(rows)
        toggle_id = f"t50-more-{tone}"
        more = len(rows) > 5
        toggle_label = (
            '<span class="t50-when-closed">View all <span>→</span></span>'
            '<span class="t50-when-open">Show less <span>↑</span></span>'
        )
        head = ('<div class="t50-col-head"><span>#</span><span>Exposure</span><span>Rank change</span>'
                "<span>New rank</span><span>1M %</span></div>")
        body = '<div class="t50-table-wrap"><div class="t50-table">' + head
        body += "".join(row_html(i, row) for i, row in enumerate(rows[:5], 1))
        body += "".join(row_html(i, row, extra=True) for i, row in enumerate(rows[5:], 6))
        body += "</div></div>"
        if more:
            body += f'<label class="t50-more" for="{toggle_id}">{toggle_label}</label>'
        return (
            f'<section class="t50-card t50-{tone}">'
            + (f'<input type="checkbox" class="t50-toggle" id="{toggle_id}">' if more else "")
            + '<div class="t50-card-head"><div class="t50-card-heading">'
            f'<div class="t50-icon" aria-hidden="true">{icon}</div>'
            f"<div><h2>{esc(title)}</h2><p>{esc(subtitle)}</p></div></div>"
            "</div>" + body + "</section>"
        )

    n = int(frame["Portfolio rank"].notna().sum())
    st.html(
        '<div id="t50-movement" class="t50-grid">'
        + card("Biggest Risers", f"Largest rank gains since {since}", "↑", "jump", risers.to_dict("records"))
        + card("Biggest Fallers", f"Largest rank losses since {since}", "↓", "left", fallers.to_dict("records"))
        + f'</div><div class="t50-note">Rank among the {n} tradeable exposures, the ranking the portfolio '
        "acts on.</div>"
    )


render_rank_changes(table)

with st.expander("RRG view", expanded=False):
    from app.components.charts import CHART_CONFIG, rrg_scatter
    from app.components.theme import stage_legend

    stage_legend()
    st.plotly_chart(rrg_scatter(decisions.loc[view.index]), width="stretch", config=CHART_CONFIG)
    st.caption("Display only: the strategy's decisions do not use the quadrant.")
