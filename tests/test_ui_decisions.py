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
