import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from src.config import load_strategy_config
from src.portfolio.construct import construct_target_portfolio
from src.portfolio.universe import ExposureMeta
from src.quantitative.alerts import diff_targets, render_markdown

INDEX = pd.bdate_range(end="2026-08-31", periods=300)
PRICES = pd.DataFrame(
    {k: 100 * np.exp(v * np.arange(len(INDEX)))
     for k, v in dict(a=0.0012, b=0.0010, c=0.0008, d=0.0006, e=0.0004).items()},
    index=INDEX,
)
META = {e: ExposureMeta(e, e.upper(), "sector", pd.Timestamp("2020-01-01")) for e in PRICES}


def _target(prior=None, **changes):
    config = load_strategy_config().replace(**changes) if changes else load_strategy_config()
    return construct_target_portfolio(INDEX[-1], PRICES, META, prior, config)


def test_a_new_holding_is_a_buy_and_a_dropped_one_a_sell():
    previous = _target(prior={"d": 0.5, "e": 0.5})  # holds a and d
    current = _target(prior={"b": 0.5, "c": 0.5})  # holds b and c
    alerts = diff_targets(previous, current, {"b": "Bank"})
    assert {e["exposure_id"] for e in alerts.entered} == {"b", "c"}
    assert {e["exposure_id"] for e in alerts.exited} == {"a", "d"}
    assert all(e["action"] == "BUY" for e in alerts.entered)
    assert all(e["action"] == "SELL" for e in alerts.exited)
    assert alerts.entered[0]["exposure"] == "Bank"


def test_an_unchanged_target_raises_nothing():
    """Between rebalances both nights produce the same decision."""
    same = _target()
    alerts = diff_targets(same, _target())
    assert not alerts.any
    assert render_markdown(alerts) == ""


def test_a_resize_is_reported_separately():
    previous = _target()  # a, b at 50%
    current = _target(prior={"a": 0.5, "b": 0.5}, target_holdings_n=4, retention_buffer_m=8)
    alerts = diff_targets(previous, current)
    resized = {e["exposure_id"]: e for e in alerts.changed}
    assert set(resized) == {"a", "b"}
    assert resized["a"]["action"] == "TRIM" and resized["a"]["to"] == "25%"


def test_a_first_run_reports_every_holding_as_a_buy():
    alerts = diff_targets(None, _target())
    assert {e["exposure_id"] for e in alerts.entered} == {"a", "b"}
    assert not alerts.exited


def test_the_report_names_orders_weights_and_reasons():
    body = render_markdown(diff_targets(_target(prior={"d": 0.5, "e": 0.5}), _target(prior={"b": 0.5, "c": 0.5})))
    assert "New target portfolio at the **31 Aug 2026** close" in body
    assert "| **BUY** | 0% → 50% |" in body
    assert "| **SELL** | 50% → 0% |" in body
    assert "next session's close" in body


def test_the_alert_tool_does_not_import_the_streamlit_app():
    """The nightly alert job must not depend on the UI package."""
    root = Path(__file__).resolve().parents[1]
    code = (
        "import sys; sys.path.insert(0, '.'); import tools.detect_alerts; "
        "print('streamlit' in sys.modules, any(m.startswith('app.') for m in sys.modules))"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False False"
