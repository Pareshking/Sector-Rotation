import pandas as pd

from app.components.metrics import decision_frame
from app.components.theme import fmt_pct


def test_benchmark_proxy_is_never_actionable():
    frame = pd.DataFrame([
        {"exposure": "Proxy Theme", "data_source": "benchmark_proxy", "stage": "Leading", "rs_ratio": 1.2, "rs_momentum": 2.0, "momentum_z": 2.0, "rank": 1},
        {"exposure": "Real Index", "data_source": "nse_archive", "stage": "Leading", "rs_ratio": 1.2, "rs_momentum": 2.0, "momentum_z": 2.0, "rank": 7},
    ])
    out = decision_frame(frame)
    assert out.loc[out.exposure == "Proxy Theme", "model_action"].iat[0] == "DATA UNAVAILABLE"
    assert bool(out.loc[out.exposure == "Proxy Theme", "decision_eligible"].iat[0]) is False
    assert out.loc[out.exposure == "Real Index", "model_action"].iat[0] == "BUY"
    assert "Rank 7" in out.loc[out.exposure == "Real Index", "analysis_note"].iat[0]


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


def test_improving_exposure_is_flagged_as_an_early_turn():
    """rs_stage puts Improving below the benchmark, so the bucket must not
    require rs_ratio > 1 — that combination can never occur."""
    frame = pd.DataFrame([_row(exposure="Early", stage="Improving", rs_ratio=0.98, rs_momentum=8.9)])
    out = decision_frame(frame)
    assert out["model_action"].iat[0] == "WATCH / IMPROVING"
    assert out["watch_kind"].iat[0] == "Early turn"


def test_leader_with_negative_velocity_is_marked_rolling_over():
    frame = pd.DataFrame([_row(exposure="Fading", stage="Weakening", rs_ratio=1.23, rs_momentum=-8.4)])
    out = decision_frame(frame)
    assert out["model_action"].iat[0] == "WATCH"
    assert out["watch_kind"].iat[0] == "Rolling over"


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
