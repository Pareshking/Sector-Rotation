import numpy as np
import pandas as pd

from app.components.metrics import decision_frame
from app.components.theme import fmt_pct
from src.config import load_strategy_config
from src.portfolio.construct import construct_target_portfolio
from src.portfolio.universe import ExposureMeta

INDEX = pd.bdate_range(end="2026-08-31", periods=300)
PRICES = pd.DataFrame(
    {k: 100 * np.exp(v * np.arange(len(INDEX)))
     for k, v in dict(a=0.0012, b=0.0010, c=0.0008, d=0.0006).items()},
    index=INDEX,
)


def _portfolio(prior=None, meta=None):
    meta = meta if meta is not None else {
        e: ExposureMeta(e, e.upper(), "sector", pd.Timestamp("2020-01-01")) for e in PRICES
    }
    return construct_target_portfolio(INDEX[-1], PRICES, meta, prior, load_strategy_config())


def _summary(ids=("a", "b", "c", "d"), **overrides):
    return pd.DataFrame([_row(exposure=e.upper(), exposure_id=e, **overrides) for e in ids])


def test_actions_come_from_the_target_portfolio_not_the_rrg_stage():
    """Every row is marked Leading here; only the portfolio decides who is held."""
    out = decision_frame(_summary(stage="Leading"), _portfolio(prior={"c": 0.5, "d": 0.5})).set_index("exposure_id")
    assert out.loc["c", "model_action"] == "HOLD"
    assert out.loc["d", "model_action"] == "HOLD"
    assert out.loc["a", "model_action"] == "NOT HELD"
    assert out.loc["c", "target_weight"] == 0.5
    assert out.loc["a", "decision_status"] == "slots full"
    assert out.loc["a", "decision_rank"] == 1


def test_buys_and_sells_are_relative_to_the_previous_target():
    out = decision_frame(_summary(), _portfolio(prior={"a": 0.5, "d": 0.5})).set_index("exposure_id")
    assert out.loc["a", "model_action"] == "HOLD"
    assert out.loc["d", "model_action"] == "HOLD"  # rank 4 is inside the buffer
    fresh = decision_frame(_summary(), _portfolio()).set_index("exposure_id")
    assert list(fresh.loc[["a", "b"], "model_action"]) == ["BUY", "BUY"]


def test_without_a_portfolio_nothing_is_actionable():
    out = decision_frame(_summary(), None)
    assert set(out["model_action"]) == {"DATA UNAVAILABLE"}
    assert not out["decision_eligible"].any()


def test_an_unscorable_exposure_is_data_unavailable():
    prices_meta = {e: ExposureMeta(e, e, "sector", pd.Timestamp("2020-01-01")) for e in PRICES}
    out = decision_frame(_summary(ids=("a", "b", "zz")), _portfolio(meta=prices_meta)).set_index("exposure_id")
    assert out.loc["zz", "model_action"] == "DATA UNAVAILABLE"
    assert not out.loc["zz", "decision_eligible"]


def test_buyable_follows_vehicle_history_on_the_decision_date():
    meta = {e: ExposureMeta(e, e, "sector", pd.Timestamp("2020-01-01") if e != "a" else None) for e in PRICES}
    out = decision_frame(_summary(), _portfolio(meta=meta)).set_index("exposure_id")
    assert not out.loc["a", "tradeable"]
    assert out.loc["b", "tradeable"]
    assert out.loc["a", "model_action"] == "NOT HELD"




def test_a_proxy_history_is_never_actionable_even_if_held():
    summary = _summary(ids=("a", "b"))
    summary.loc[summary.exposure_id == "a", "data_source"] = "benchmark_proxy"
    out = decision_frame(summary, _portfolio()).set_index("exposure_id")
    assert out.loc["a", "model_action"] == "DATA UNAVAILABLE"
    assert not out.loc["a", "decision_eligible"]
    assert out.loc["b", "model_action"] == "BUY"


def test_returns_are_displayed_as_percentages():
    assert fmt_pct(0.0621) == "6.2%"
    assert fmt_pct(-0.031) == "-3.1%"


def _row(**overrides):
    base = {
        "exposure": "X",
        "exposure_id": "x",
        "data_source": "niftyindices_jugaad",
        "stage": "Leading",
        "rs_ratio": 1.2,
        "rs_momentum": 2.0,
        "momentum_z": 1.0,
        "rank": 1,
        "resolved_official_index_name": "NIFTY X",
    }
    base.update(overrides)
    return base


def test_exposures_sharing_one_index_are_flagged_not_deduplicated():
    frame = pd.DataFrame([
        _row(exposure="NBFC", exposure_id="nbfc", resolved_official_index_name="NIFTY FIN EX-BANK"),
        _row(exposure="Financial ex Bank", exposure_id="fx", resolved_official_index_name="NIFTY FIN EX-BANK"),
        _row(exposure="Pharma", exposure_id="ph", resolved_official_index_name="NIFTY PHARMA"),
    ])
    out = decision_frame(frame).set_index("exposure")
    assert len(out) == 3
    assert out.loc["NBFC", "shares_index_with"] == "Financial ex Bank"
    assert out.loc["Financial ex Bank", "shares_index_with"] == "NBFC"
    assert out.loc["Pharma", "shares_index_with"] is None


def test_ranking_defaults_to_return_relative_to_the_benchmark():
    """A relative-strength model must rank on relative return, not raw return.

    In a rising market ranking on absolute return largely re-ranks the market.
    """
    from app.components.tables import BASIS_ABSOLUTE, BASIS_RELATIVE, _column_for

    assert _column_for("3M", BASIS_RELATIVE) == "relative_3M"
    assert _column_for("3M", BASIS_ABSOLUTE) == "return_3M"
    assert _column_for("Composite", BASIS_RELATIVE) == "momentum_z"
    assert _column_for("Composite", BASIS_ABSOLUTE) == "momentum_z"


def test_relative_ranking_reorders_versus_absolute():
    from app.components.tables import BASIS_ABSOLUTE, BASIS_RELATIVE, _column_for

    frame = pd.DataFrame([
        {"exposure": "Beta chaser", "return_3M": 0.20, "relative_3M": 0.01},
        {"exposure": "True leader", "return_3M": 0.12, "relative_3M": 0.09},
    ])
    by_abs = frame.sort_values(_column_for("3M", BASIS_ABSOLUTE), ascending=False)
    by_rel = frame.sort_values(_column_for("3M", BASIS_RELATIVE), ascending=False)
    assert by_abs.exposure.iat[0] == "Beta chaser"
    assert by_rel.exposure.iat[0] == "True leader"


def test_notes_state_the_decision_date_and_never_claim_a_benchmark_comparison():
    out = decision_frame(_summary(), _portfolio(prior={"c": 0.5, "d": 0.5}))
    for note in out["analysis_note"]:
        assert note.startswith("Decision at the 31 Aug 2026 close.")
        assert "the benchmark" not in note


def test_the_rs_ratio_column_help_does_not_claim_a_benchmark_comparison():
    from app.components.tables import COLUMNS

    _, _, help_text = COLUMNS["rs_ratio"]
    assert "52-week moving average" in help_text
    assert "Nifty" not in help_text


def test_navigation_links_to_the_default_page_at_the_root():
    """'/Overview' answers 'Page not found': the default page is served at '/'."""
    from app.components.theme import NAV_ITEMS, nav_href

    assert nav_href("Overview") == "/"
    assert nav_href("Backtest") == "/Backtest"
    assert all(nav_href(path) != "/Overview" for _, path, _ in NAV_ITEMS)


def test_the_logo_links_to_the_site_root():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py").read_text(encoding="utf-8")
    assert 'link="https://dualmomentum.streamlit.app/"' in source
    assert "streamlit.app/Overview" not in source


def test_dashboard_reasons_are_escaped_not_parsed_as_html():
    """A reason contains 'rank <= 4'; rendered raw, '<=' swallowed the rest of the line."""
    from pathlib import Path

    import pytest
    from streamlit.testing.v1 import AppTest

    root = Path(__file__).resolve().parents[1]
    if not (root / "data" / "processed" / "index_prices.parquet").exists():
        pytest.skip("no published dataset")
    at = AppTest.from_file(str(root / "app" / "views" / "1_Overview.py"), default_timeout=240).run()
    assert not at.exception
    held_notes = [m.value for m in at.markdown if "Retained inside the buffer" in m.value or "New entry" in m.value]
    assert held_notes
    for value in held_notes:
        assert "&lt;=" in value
        assert "(rank cash" not in value
