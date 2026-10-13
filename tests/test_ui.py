"""The seven-page app: structure, routes, and what each page must answer."""

import re
from html import unescape
from pathlib import Path

import pytest

from app.components.navigation import HOME_PATH, PAGES, nav_href

ROOT = Path(__file__).resolve().parents[1]
VIEWS = ROOT / "app" / "views"
HAS_DATA = (ROOT / "data" / "processed" / "index_prices.parquet").exists()
needs_data = pytest.mark.skipif(not HAS_DATA, reason="no published dataset")


def _text(value: str) -> str:
    value = re.sub(r"<style.*?</style>", "", value, flags=re.S)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value.replace("<br>", " | ")))).strip()


def _page_text(at) -> str:
    """Text of every markdown and st.html element, tags stripped."""
    parts = [m.value for m in at.markdown] + [str(getattr(h, "proto", h).body) for h in at.get("html")]
    return " ".join(_text(p) for p in parts)


def _render(page_file: str):
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(str(VIEWS / page_file), default_timeout=300).run()


# --------------------------------------------------------------------------- #
# Structure and routes
# --------------------------------------------------------------------------- #
def test_the_app_has_exactly_seven_pages_in_order():
    """The Screener is home and Actions follows Portfolio, as in the Paresh app."""
    assert [p.title for p in PAGES] == [
        "Screener", "Portfolio", "Actions", "Exposure", "Evidence", "Data Health", "Method"
    ]
    assert [p.file for p in PAGES] == [
        "2_Rankings.py", "1_Portfolio.py", "7_Actions.py", "4_Exposure.py", "3_Evidence.py", "5_Data_Health.py",
        "6_Method.py",
    ]
    assert sum(p.default for p in PAGES) == 1 and PAGES[0].default
    assert len({p.url_path for p in PAGES}) == len(PAGES)
    assert all(p.icon is None for p in PAGES), "the header links are text, as in the Paresh app"


def test_the_views_folder_holds_only_the_seven_pages():
    """The merged and renamed pages (Overview, Sectors, Themes, Backtest...) are gone."""
    assert sorted(p.name for p in VIEWS.glob("*.py") if p.name != "__init__.py") == sorted(p.file for p in PAGES)


def test_the_app_shell_builds_navigation_from_the_single_definition():
    source = (ROOT / "app" / "streamlit_app.py").read_text(encoding="utf-8")
    assert "for page in PAGES" in source
    assert not re.search(r'st\.Page\(VIEWS_DIR / "\d_', source), "page files must come from PAGES"


def test_every_link_resolves_and_the_default_page_is_at_the_root():
    """A default page's url_path is not routed: '/Screener' would answer 'Page not found'."""
    assert HOME_PATH == "Screener"
    assert nav_href("Screener") == "/"
    assert [nav_href(p.url_path) for p in PAGES[1:]] == [
        "/Portfolio", "/Actions", "/Exposure", "/Evidence", "/Data_Health", "/Method"
    ]


def test_the_phone_menu_groups_every_page_once_with_actions_under_research():
    from app.components.navigation import GROUPS

    assert sorted(i for indices in GROUPS.values() for i in indices) == list(range(len(PAGES)))
    assert [PAGES[i].title for i in GROUPS["Research"]] == ["Screener", "Portfolio", "Actions", "Exposure"]


def test_the_brand_links_home_through_the_header():
    source = (ROOT / "app" / "kit" / "header.py").read_text(encoding="utf-8")
    assert 'st.page_link(nav_pages[0], label="Dual Momentum")' in source


def test_the_shell_renders_the_paresh_header_once_for_every_page():
    """The shell draws the header and stylesheet; a page drawing either itself would draw it twice."""
    shell = (ROOT / "app" / "streamlit_app.py").read_text(encoding="utf-8")
    assert 'st.navigation(pages, position="hidden")' in shell
    assert "inject_custom_css()" in shell and "render_header(market_state(), pages, current, GROUPS)" in shell
    for page in PAGES:
        source = (VIEWS / page.file).read_text(encoding="utf-8")
        assert "render_header(" not in source and "inject_custom_css(" not in source, page.file


def test_the_phone_nav_marks_only_the_active_page(monkeypatch):
    from app.components import navigation

    rendered = []
    monkeypatch.setattr(navigation.st, "markdown", lambda body, **_: rendered.append(body))
    navigation.mobile_nav("Evidence")
    links = re.findall(r'<a class="([^"]*)" href="([^"]+)"', rendered[0])
    assert [href for _, href in links] == [nav_href(p.url_path) for p in PAGES]
    assert [cls for cls, _ in links] == ["on" if p.url_path == "Evidence" else "" for p in PAGES]


def test_the_header_shows_one_regime_the_hurdle_the_date_the_version_and_freshness():
    from app.components.header import HeaderState, header_html

    state = HeaderState(regime="RISK-OFF", benchmark_12m=-0.083, cash_12m=0.0657, cash_source="nav",
                        as_of="09 Oct 2026", version="1.1", config_hash="e0c03c7a46ae",
                        updated="2026-10-12T10:00:00+00:00", age_hours=4.0)
    text = _text(header_html(state))
    assert text.count("RISK-") == 1 and "RISK-OFF" in text
    for part in ("Nifty 50 TRI · 12M -8.3%", "liquid fund 12M 6.57%", "As of 09 Oct 2026",
                 "Data fresh · updated 4h ago"):
        assert part in text, part
    assert "e0c03c7a46ae" not in text, "the config fingerprint belongs on the Method page"

    stale = _text(header_html(HeaderState(regime="RISK-ON", benchmark_12m=0.1, cash_12m=0.065,
                                          cash_source="constant", age_hours=50.0)))
    assert "assumed cash 12M" in stale and "Data stale · updated 2d ago" in stale


def test_the_header_degrades_without_data():
    from app.components.header import HeaderState, header_html

    text = _text(header_html(HeaderState()))
    assert "RISK-" not in text and "Data stale · age unknown" in text


def test_exploratory_backtests_are_cached_with_a_bound():
    source = (ROOT / "app" / "data.py").read_text(encoding="utf-8")
    for name in ("_backtest", "_sensitivity"):
        decorator = re.search(rf"@st\.cache_data\(([^)]*)\)\s*\ndef {name}\(", source)
        assert decorator and "max_entries=32" in decorator.group(1), name


# --------------------------------------------------------------------------- #
# Every page renders on the published data
# --------------------------------------------------------------------------- #
@needs_data
@pytest.mark.parametrize("page", [p.file for p in PAGES])
def test_every_page_renders_without_exceptions(page):
    at = _render(page)
    assert not at.exception, [e.message for e in at.exception]


@needs_data
def test_the_shell_renders_the_status_header_above_the_default_page():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=300).run()
    assert not at.exception, [e.message for e in at.exception]
    text = _page_text(at)
    assert len(re.findall(r"Risk-(?:on|off)", text)) == 1, "one regime in the market strip"
    assert re.search(r"(Prices · close of|Data stale · closes of) \d{2} \w{3}", text)
    assert "Universe" in text and "200D average" in text


@needs_data
def test_the_portfolio_page_is_the_model_book_dashboard():
    """Six readings, then the Paresh layout: book, mix, co-movement, equity, calendar, record, trades, rebalances."""
    at = _render("1_Portfolio.py")
    assert not at.exception, [e.message for e in at.exception]
    text = _page_text(at)
    for reading in ("Portfolio value", "Since inception", "Unrealised P&L", "Day P&L", "Cash / realised balance"):
        assert reading in text, reading
    assert "Invested: ₹2,000,000" in text
    for card in ("Current book", "Sector exposure", "Equity & drawdown", "Calendar returns", "Trades", "Rebalances"):
        assert card in text, card
    assert [p.options for p in at.get("button_group")][:2] == [["All", "Winners", "Losers", "Open"],
                                                                ["All", "Buy", "Sell", "Hold"]]


@needs_data
def test_the_actions_page_is_the_paresh_layout_for_the_book_and_typed_holdings():
    """Readings, then Sell, Buy and Hold cards and the ranked list; typed ETF symbols map to exposures."""
    at = _render("7_Actions.py")
    assert not at.exception, [e.message for e in at.exception]
    text = _page_text(at)
    assert "Next rebalance if prices hold. Checked" in text
    for part in ("Sell", "Buy", "Hold", "Next rebalance", "sessions away · fills"):
        assert part in text, part
    assert [p.options for p in at.get("button_group")][0] == ["Model book", "My holdings"]
    assert "Buy candidates · the ranked list" in [e.label for e in at.expander]
    assert any(n.value == 2_000_000 for n in at.number_input), "the Kite basket starts at the ₹20 lakh book"

    at.button_group[0].set_value("My holdings").run()
    at.text_input(key="xw_text").set_value("PHARMABEES 22, NOTAFUND").run()
    at.button(key="xw_save").click().run()
    assert not at.exception, [e.message for e in at.exception]
    text = _page_text(at)
    assert "PHARMABEES" in text and "Not ranked" in text and "1 of your symbols is not in the universe." in text


@needs_data
def test_ledger_tables_escape_reasons_and_dash_gaps():
    """A reason contains 'rank <= 4'; unescaped, '<=' would swallow the rest of the cell."""
    import pandas as pd

    from app.components.ledger import Col, table_html

    frame = pd.DataFrame({"Why": ["rank <= 4 & held"], "Return %": [float("nan")], "Units": [12.0]})
    markup, _ = table_html(frame, [Col("Why"), Col("Return %", "pct"), Col("Units", "units")])
    assert "rank &lt;= 4 &amp; held" in markup
    assert '<td class="c mute" data-v="">—</td>' in markup
    assert ">12</td>" in markup


@needs_data
def test_the_rankings_filter_counts_come_from_the_data():
    """The Screener's preset pills count rows of the data; Tradeable is the default."""
    import pandas as pd

    summary = pd.read_parquet(ROOT / "data" / "processed" / "summary_rankings.parquet")
    counts = summary["category"].value_counts()
    at = _render("2_Rankings.py")
    assert not at.exception
    presets = list(at.button_group[0].options)
    assert presets[0].startswith("Tradeable ") and presets[1] == f"All {len(summary)}"
    assert f"Sectors {counts['sector']}" in presets and f"Themes {counts['thematic']}" in presets
    assert at.session_state["rank_quick_pills"] == "Tradeable"
    assert [list(g.options) for g in at.button_group[1:]] == [
        ["Sector", "Theme"], ["Rank", "1M Δ", "1M", "3M", "6M", "12M", "Max DD 3M"], ["Absolute", "vs Nifty 50"]]
    assert at.selectbox[0].placeholder == "Search exposure or index"
    assert [e.label for e in at.expander] == ["RRG view"]
    from app.components.screener import PRESETS

    for preset in PRESETS[1:]:
        at.button_group(key="rank_quick_pills").set_value(preset).run()
        assert not at.exception, preset
    at.button_group(key="rank_basis").set_value("vs Nifty 50").run()
    at.button_group(key="rank_sort_by").set_value("Max DD 3M").run()
    assert not at.exception


@needs_data
def test_the_screener_table_shows_every_tradeable_exposure_by_rank():
    """The default view numbers the tradeable exposures 1, 2, 3 … with 1M Δ and 3M Δ from the decision chain."""
    from app.components import screener as scr
    from app.data import (
        current_regime,
        load_backtest,
        load_decisions,
        load_index_panel,
        vehicle_frame,
    )
    from app.kit.screener_table import table_html

    decisions = load_decisions()
    panel, _ = load_index_panel()
    regime = current_regime()
    chain = load_backtest().decisions
    table = scr.display_frame(decisions, panel.ffill().iloc[-1], scr.fund_counts(vehicle_frame(), panel.index.max()),
                              regime.cash_12m if regime else None, ranks_1m=scr.past_ranks(chain, 1),
                              ranks_3m=scr.past_ranks(chain, 3), drawdown_3m=scr.max_drawdown(panel),
                              portfolio_ranked=True)
    tradeable = decisions["tradeable"].astype(bool)
    view = scr.sort_frame(table[tradeable], "Rank")
    assert view["Rank"].tolist() == list(range(1, int(tradeable.sum()) + 1))
    # The last rebalance is the chain's last decision, so 1M Δ agrees with decision_rank.
    assert (view["1M rank"] == decisions.loc[view.index, "decision_rank"]).all()
    assert view["3M Δ"].notna().sum() > 0 and view["Max DD 3M"].le(0).all()
    markup = table_html(view, panel)
    assert markup.count("<tr data-stock=") == int(tradeable.sum())
    body = markup[markup.index("<tbody>"):markup.index("</tbody>")]
    assert "None" not in body and ">nan" not in body


@needs_data
def test_the_evidence_page_leads_with_the_live_rules_net_of_costs():
    at = _render("3_Evidence.py")
    text = " ".join(_text(m.value) for m in at.markdown)
    for card in ("Net CAGR", "Net total return", "Max drawdown", "Net excess vs Nifty", "Deflated Sharpe"):
        assert card in text, card
    assert "Parameter Sensitivity (Unvalidated)" in [e.label for e in at.expander]
    assert any(t.label == "Include back-calculated index history" for t in at.toggle)
    comparison = at.dataframe[0].value
    assert set(comparison["Back-calculated history"]) == {"Included", "Excluded"}


@needs_data
def test_a_screener_row_link_opens_that_exposure():
    """A Screener row navigates to Exposure?exposure=<id>; the page selects it once."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(VIEWS / "4_Exposure.py"), default_timeout=300)
    at.query_params["exposure"] = "metal"
    at.run()
    assert not at.exception
    assert at.selectbox(key="detail_exposure").value == "Metals"
    at.selectbox(key="detail_exposure").set_value("Pharma").run()
    assert at.selectbox(key="detail_exposure").value == "Pharma"  # not undone by the link


@needs_data
def test_choosing_an_exposure_in_the_screener_search_opens_its_page():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=300).run()
    assert not at.exception
    at.selectbox(key="rank_search_predictive").set_value("Defence").run()
    assert not at.exception
    assert at.selectbox(key="detail_exposure").value == "Defence"


@needs_data
def test_the_exposure_page_sizes_a_position_from_the_book_slider():
    at = _render("4_Exposure.py")
    slider = next(s for s in at.slider if s.label == "Book size (₹ lakh)")
    assert (slider.min, slider.max) == (10, 100)
    text = " ".join(_text(m.value) for m in at.markdown)
    assert "Implementation matrix" in text and "Position sizing" in text
    slider.set_value(100).run()
    assert not at.exception
    assert at.session_state["book_size"] == 10_000_000


@needs_data
def test_the_method_worked_example_reproduces_the_live_score():
    at = _render("6_Method.py")
    text = " ".join(_text(m.value) for m in at.markdown)
    assert "identical to the score the portfolio used" in text
    assert any(r"S_{\text{" in latex.value for latex in at.get("latex"))


# --------------------------------------------------------------------------- #
# Pure helpers behind the pages
# --------------------------------------------------------------------------- #
class _Decision:
    def __init__(self, exposure_id, target_weight, prior_weight, action):
        self.exposure_id, self.target_weight, self.prior_weight = exposure_id, target_weight, prior_weight
        self.action, self.reason = action, f"{action} reason"


class _Target:
    def __init__(self, decisions, ranking=None):
        self.decisions = decisions
        self.weights = {d.exposure_id: d.target_weight for d in decisions}
        self.cash_weight = 1.0 - sum(self.weights.values())
        self.ranking = ranking


def test_allocation_rows_end_in_cash_and_sum_to_one():
    import pandas as pd

    from app.components.allocation import allocation_frame, allocation_rows

    target = _Target([_Decision("a", 0.25, 0.25, "HOLD"), _Decision("b", 0.25, 0.0, "BUY"),
                      _Decision("c", 0.0, 0.25, "SELL")])
    rows = allocation_rows(target, {"a": "Alpha"}, lambda _: None, 3_000_000, 25.0, "Liquid fund", "hurdle")
    table = allocation_frame(rows)
    assert list(table["Exposure"]) == ["Alpha", "b", "c", "Cash"]
    assert abs(table["Target"].sum() - 1.0) < 1e-12 and abs(table["Held now"].sum() - 1.0) < 1e-12
    assert list(table["Est. cost (bps of book)"]) == [0.0, 6.25, 6.25, 0.0]
    assert list(table["Best vehicle"])[:3] == ["No buyable vehicle"] * 3
    assert pd.isna(table["Days to build"].iloc[2])


def test_the_edge_panel_holds_only_ranks_inside_the_buffer():
    import pandas as pd

    from app.components.allocation import edge_frame

    ranking = pd.DataFrame(
        {"rank": [1, 2, 3, 4, 5], "score": [0.9, 0.8, 0.7, 0.6, 0.5], "return_12m": [0.2] * 5,
         "status": ["held"] * 5},
        index=["a", "b", "c", "d", "e"],
    )
    target = _Target([_Decision("a", 0.5, 0.5, "HOLD"), _Decision("d", 0.5, 0.5, "HOLD")], ranking)
    edge = edge_frame(target, {}, n=2, m=4)
    assert list(edge["exposure_id"]) == ["c", "d"]
    assert list(edge["role"]) == ["Next in line", "Held via buffer"]
