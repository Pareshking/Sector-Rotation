import pandas as pd

from src.quantitative.alerts import diff_actions, render_markdown
from src.universe.tradeability import attach_tradeability, investable_exposure_ids


def _frame(actions: dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"exposure_id": k, "exposure": k.title(), "model_action": v,
             "stage": "Leading", "rank": i + 1, "tradeable": True}
            for i, (k, v) in enumerate(actions.items())
        ]
    )


def test_entering_buy_is_reported():
    alerts = diff_actions(_frame({"auto": "WATCH"}), _frame({"auto": "BUY"}))
    assert [a["to"] for a in alerts.entered] == ["BUY"]
    assert not alerts.exited


def test_leaving_an_actionable_state_is_reported():
    alerts = diff_actions(_frame({"auto": "BUY"}), _frame({"auto": "WATCH"}))
    assert [a["from"] for a in alerts.exited] == ["BUY"]
    assert not alerts.entered


def test_an_unchanged_board_raises_nothing():
    same = _frame({"auto": "BUY", "bank": "WATCH"})
    assert not diff_actions(same, same).any
    assert render_markdown(diff_actions(same, same)) == ""


def test_watch_drifting_between_watch_states_is_not_actionable():
    """Only entering or leaving BUY / REDUCE should interrupt anyone."""
    alerts = diff_actions(_frame({"it": "WATCH"}), _frame({"it": "WATCH / IMPROVING"}))
    assert not alerts.entered and not alerts.exited
    assert len(alerts.changed) == 1


def test_a_new_exposure_only_alerts_when_it_lands_actionable():
    assert diff_actions(_frame({}), _frame({"new": "WATCH"})).any is False
    assert diff_actions(_frame({}), _frame({"new": "BUY"})).entered


def test_report_names_the_exposure_and_the_transition():
    body = render_markdown(diff_actions(_frame({"auto": "WATCH"}), _frame({"auto": "BUY"})))
    assert "Auto" in body and "WATCH → **BUY**" in body


def test_index_funds_count_as_investable_without_exchange_turnover():
    """An index fund transacts at NAV and is never listed, so turnover is absent."""
    etfs = pd.DataFrame([
        {"exposure_id": "a", "symbol": None, "name": "X Index Fund",
         "vehicle": "index_fund", "traded_value": None},
        {"exposure_id": "b", "symbol": "YETF", "name": "Y ETF",
         "vehicle": "etf", "traded_value": 0},
    ])
    assert investable_exposure_ids(etfs) == {"a"}


def test_tradeability_attaches_the_same_answer_everywhere():
    etfs = pd.DataFrame([
        {"exposure_id": "a", "symbol": "AETF", "name": "A ETF",
         "vehicle": "etf", "traded_value": 5_000_000},
    ])
    out = attach_tradeability(_frame({"a": "BUY", "b": "BUY"}), etfs)
    assert list(out["tradeable"]) == [True, False]
