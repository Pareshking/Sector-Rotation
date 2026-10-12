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


def test_every_page_marks_itself_active_in_the_phone_nav():
    for page in PAGES:
        source = (VIEWS / page.file).read_text(encoding="utf-8")
        assert f'mobile_nav("{page.url_path}")' in source, page.file


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
def test_the_portfolio_page_answers_the_five_second_questions():
    at = _render("1_Portfolio.py")
    text = " ".join(_text(m.value) for m in at.markdown)
    assert re.search(r"Dual Momentum \| RISK-(ON|OFF) \|", text), "one regime chip in the header"
    assert "Next rebalance" in text and "Strategy v" in text
    assert "Holdings steady" in text or "Rebalance at the" in text
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
    assert "Score" in table.columns and "Stage (display only)" in table.columns
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
