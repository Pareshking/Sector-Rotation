"""The six-page app: structure, routes, and what each page must answer."""

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


def _render(page_file: str):
    from streamlit.testing.v1 import AppTest

    return AppTest.from_file(str(VIEWS / page_file), default_timeout=300).run()


# --------------------------------------------------------------------------- #
# Structure and routes
# --------------------------------------------------------------------------- #
def test_the_app_has_exactly_six_pages_in_order():
    assert [p.title for p in PAGES] == ["Portfolio", "Rankings", "Evidence", "Exposure", "Data Health", "Method"]
    assert [p.file for p in PAGES] == [
        "1_Portfolio.py", "2_Rankings.py", "3_Evidence.py", "4_Exposure.py", "5_Data_Health.py", "6_Method.py"
    ]
    assert sum(p.default for p in PAGES) == 1 and PAGES[0].default
    assert len({p.url_path for p in PAGES}) == len(PAGES)


def test_the_views_folder_holds_only_the_six_pages():
    """The merged and renamed pages (Overview, Sectors, Themes, Backtest...) are gone."""
    assert sorted(p.name for p in VIEWS.glob("*.py") if p.name != "__init__.py") == sorted(p.file for p in PAGES)


def test_the_app_shell_builds_navigation_from_the_single_definition():
    source = (ROOT / "app" / "streamlit_app.py").read_text(encoding="utf-8")
    assert "for page in PAGES" in source
    assert not re.search(r'st\.Page\(VIEWS_DIR / "\d_', source), "page files must come from PAGES"


def test_every_link_resolves_and_the_default_page_is_at_the_root():
    """A default page's url_path is not routed: '/Portfolio' would answer 'Page not found'."""
    assert HOME_PATH == "Portfolio"
    assert nav_href("Portfolio") == "/"
    assert [nav_href(p.url_path) for p in PAGES[1:]] == [
        "/Rankings", "/Evidence", "/Exposure", "/Data_Health", "/Method"
    ]
    assert all(nav_href(p.url_path) != "/Portfolio" for p in PAGES)


def test_the_logo_links_to_the_site_root():
    source = (ROOT / "app" / "streamlit_app.py").read_text(encoding="utf-8")
    assert 'link="https://dualmomentum.streamlit.app/"' in source


def test_the_shell_renders_the_header_and_phone_nav_once_for_every_page():
    """The shell marks the running page active; a page calling either itself would render it twice."""
    shell = (ROOT / "app" / "streamlit_app.py").read_text(encoding="utf-8")
    assert "global_header()" in shell
    assert "mobile_nav(next((page.url_path for page in PAGES if page.title == current.title)" in shell
    for page in PAGES:
        source = (VIEWS / page.file).read_text(encoding="utf-8")
        assert "mobile_nav(" not in source and "global_header(" not in source, page.file


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
                 "Strategy v1.1 · e0c03c7a46ae", "Data fresh · updated 4h ago"):
        assert part in text, part

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
    text = " ".join(_text(m.value) for m in at.markdown)
    assert len(re.findall(r"Dual Momentum RISK-(?:ON|OFF) ", text)) == 1, "one regime chip in the header"
    assert "As of" in text and "Strategy v" in text and re.search(r"Data (fresh|stale)", text)
    assert "What to hold, what to trade" in text, "the default page runs beneath the header"


@needs_data
def test_the_portfolio_page_answers_the_five_second_questions():
    at = _render("1_Portfolio.py")
    text = " ".join(_text(m.value) for m in at.markdown)
    assert "Next rebalance" in text and "strategy v" in text
    assert "Holdings steady until Next Rebalance" in text or "Rebalance at the" in text
    for heading in ("Target allocation", "Trade execution log", "On the edge"):
        assert heading in text, heading
    table = at.dataframe[0].value
    assert list(table.columns) == [
        "Exposure", "Best vehicle", "Target", "Held now", "Action", "Est. cost (bps of book)", "Days to build"
    ]
    assert table["Exposure"].iloc[-1] == "Cash"
    assert abs(table["Target"].sum() - 1.0) < 1e-9
    assert set(table["Action"]) <= {"BUY", "HOLD", "TRIM", "SELL", "—"}
    # The front page carries no RRG chart, no action board and no raw dump.
    assert not at.get("plotly_chart")
    assert "Leading" not in text and "Action board" not in text and "Model inputs" not in text


@needs_data
def test_portfolio_reasons_are_escaped_not_parsed_as_html():
    """A reason contains 'rank <= 4'; rendered raw, '<=' swallowed the rest of the line."""
    at = _render("1_Portfolio.py")
    why = [m.value for m in at.markdown if "Retained inside the buffer" in m.value or "New entry" in m.value]
    assert why and all("&lt;=" in v and "(rank cash" not in v for v in why)


@needs_data
def test_the_rankings_filter_counts_come_from_the_data():
    import pandas as pd

    summary = pd.read_parquet(ROOT / "data" / "processed" / "summary_rankings.parquet")
    counts = summary["category"].value_counts()
    at = _render("2_Rankings.py")
    labels = [list(group.options) for group in at.button_group]
    assert [f"All ({len(summary)})", f"Sectors ({counts['sector']})", f"Themes ({counts['thematic']})"] in labels
    table = at.dataframe[0].value
    assert list(table.columns[:3]) == ["Rank", "Exposure", "Category"]
    assert list(table.columns[3:8]) == ["1M", "3M", "6M", "12M", "Score"]
    assert "Quadrant (display only)" in table.columns
    assert table["Rank"].is_monotonic_increasing
    assert [e.label for e in at.expander][0] == "RRG Quadrant View (Display Context)"


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
