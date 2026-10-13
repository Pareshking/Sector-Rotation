"""The Actions page's pure helpers: the plan, the cushions, the holdings parser and the Kite basket.

Every plan here is read off ``construct_target_portfolio`` itself, so the page
can only show what the strategy would do.
"""

import numpy as np
import pandas as pd
import pytest

from app.components.actions import (
    CLEAR,
    SELL,
    UNKNOWN,
    WATCH,
    Rules,
    assess,
    buy_orders,
    holdings_from_kite_csv,
    map_symbols,
    next_rebalance,
    parse_holdings,
    plan_rebalance,
    prior_weights,
    sessions_between,
)
from src.config import load_strategy_config
from src.portfolio.calendar import rebalance_dates
from src.portfolio.construct import BUY, CASH, HOLD, SELL as SELL_ACTION, construct_target_portfolio, decision_chain
from src.portfolio.universe import ExposureMeta

INDEX = pd.bdate_range(end="2026-08-31", periods=300)
AS_OF = INDEX[-1]
RULES = Rules(top_n=2, buffer_m=4)


def _drifts(**drifts: float) -> pd.DataFrame:
    """Constant daily log drift per exposure: rank order equals drift order."""
    t = np.arange(len(INDEX))
    return pd.DataFrame({k: 100 * np.exp(v * t) for k, v in drifts.items()}, index=INDEX)


# Ranks a..f = 1..6; f's 12M return (~5%) is below the 6.5% hurdle, e's (~10.6%) is above.
SIX = _drifts(a=0.0012, b=0.0010, c=0.0008, d=0.0006, e=0.0004, f=0.0002)


def _meta(prices):
    return {e: ExposureMeta(e, e.upper(), "sector", pd.Timestamp("2020-01-01")) for e in prices.columns}


def _preview(holdings, prices=SIX, config=None):
    config = config or load_strategy_config()
    return construct_target_portfolio(
        AS_OF, prices, _meta(prices), prior_weights(holdings, int(config.target_holdings_n)), config
    )


# --------------------------------------------------------------------------- #
# The plan
# --------------------------------------------------------------------------- #
def test_prior_weights_give_each_holding_one_slot_and_the_rest_cash():
    assert prior_weights([], 2) == {CASH: 1.0}
    assert prior_weights(["a"], 2) == {"a": 0.5, CASH: 0.5}
    assert prior_weights(["a", "b", "a"], 2) == {"a": 0.5, "b": 0.5}


def test_a_holding_inside_the_buffer_is_held_and_one_past_it_is_sold():
    preview = _preview(["c", "e"])          # c ranks 3 (inside M = 4); e ranks 5 (past it)
    plan = plan_rebalance(preview, ["c", "e"])
    assert plan.holds == ["c"] and plan.sells == ["e"] and plan.buys == ["a"]
    assert plan.weights.to_dict() == {"a": 0.5, "c": 0.5}
    assert plan.next_in_line == ["b", "d"], "best-ranked first, beating cash, neither bought nor being sold"


def test_from_cash_the_top_n_are_bought():
    plan = plan_rebalance(_preview([]), [])
    assert plan.buys == ["a", "b"] and plan.sells == [] and plan.holds == []
    assert plan.cash_weight == 0.0


def test_a_top_name_below_the_hurdle_leaves_its_slot_in_cash():
    prices = _drifts(a=0.0012, b=0.00015, c=0.0001)   # b ranks 2 but returns < 6.5% a year
    plan = plan_rebalance(_preview([], prices), [])
    assert plan.buys == ["a"] and plan.cash_weight == pytest.approx(0.5)
    assert "b" not in plan.next_in_line, "a name below the hurdle is not a candidate"


def test_the_plan_is_the_live_decision_when_nothing_changes():
    """Struck at a month-end close from the previous decision, the preview is that decision."""
    config = load_strategy_config()
    prices = SIX.copy()
    august = prices.index >= "2026-08-01"            # b falls 2% a session in its last month
    prices.loc[august, "b"] = prices.loc[august, "b"].iloc[0] * np.exp(-0.02 * np.arange(int(august.sum())))
    chain = decision_chain(prices, _meta(prices), config, rebalance_dates(prices.index))
    last, previous = chain[-1], chain[-2]
    held = list(previous.holdings)
    assert held == ["a", "b"]
    preview = construct_target_portfolio(last.as_of, prices, _meta(prices), previous.weights, config)
    plan = plan_rebalance(preview, held)
    assert preview.weights == last.weights
    assert (plan.sells, plan.buys, plan.holds) == (["b"], ["c"], ["a"])
    actions = {d.exposure_id: d.action for d in last.decisions}
    assert set(plan.holds) == {e for e, a in actions.items() if a == HOLD}
    assert set(plan.buys) == {e for e, a in actions.items() if a == BUY}
    assert set(plan.sells) == {e for e, a in actions.items() if a == SELL_ACTION}


def test_holdings_outside_the_ranking_are_left_out_of_the_plan():
    plan = plan_rebalance(_preview(["a"]), ["a", "zzz"])
    assert plan.holds == ["a"] and "zzz" not in plan.sells + plan.buys


# --------------------------------------------------------------------------- #
# Cushions
# --------------------------------------------------------------------------- #
def test_cushions_are_rank_room_and_the_12m_margin_over_cash():
    preview = _preview(["c", "d"])
    plan = plan_rebalance(preview, ["c", "d"])
    a = assess(preview, ["c", "d", "NOPE"], plan, RULES).set_index("exposure_id")
    hurdle = preview.cash_hurdle_12m
    assert a.loc["c", "rank_room"] == 1 and a.loc["d", "rank_room"] == 0
    assert a.loc["c", "hurdle_cushion"] == pytest.approx(preview.ranking.at["c", "return_12m"] - hurdle)
    assert a.loc["d", "status"] == WATCH and "0 places from the buffer" in a.loc["d", "why"]
    assert a.loc["NOPE", "status"] == UNKNOWN
    assert list(a.index)[-1] == "NOPE", "unknowns are listed last"


def test_a_sale_names_the_rule_it_breaks():
    preview = _preview(["e", "f"])          # e: past the buffer; f: past it and below cash
    plan = plan_rebalance(preview, ["e", "f"])
    a = assess(preview, ["e", "f"], plan, RULES).set_index("exposure_id")
    assert set(a["status"]) == {SELL}
    assert a.loc["e", "why"] == "ranks #5, past the top 4"
    assert "ranks #6, past the top 4" in a.loc["f", "why"] and "below cash" in a.loc["f", "why"]
    assert not a.loc["f", "hurdle_ok"] and a.loc["f", "hurdle_cushion"] < 0


def test_a_clear_holding_has_room_on_both_rules():
    preview = _preview(["a"])
    plan = plan_rebalance(preview, ["a"])
    row = assess(preview, ["a"], plan, RULES).iloc[0]
    assert row["status"] == CLEAR and row["why"] == "" and row["rank_room"] == 3


def test_the_tightest_holding_comes_first_within_a_status():
    preview = _preview(["a", "b"])
    plan = plan_rebalance(preview, ["a", "b"])
    a = assess(preview, ["a", "b"], plan, RULES)
    assert list(a["exposure_id"]) == ["b", "a"], "b has less room on both rules"


# --------------------------------------------------------------------------- #
# Holdings, the basket and the calendar
# --------------------------------------------------------------------------- #
def test_parse_holdings_reads_symbols_and_optional_buy_prices():
    assert parse_holdings("metal 11.3, MODEFENCE@105; bankbees\nMETAL 12, bad sym!") == [
        ("METAL", 11.3), ("MODEFENCE", 105.0), ("BANKBEES", None)
    ]


def test_kite_holdings_csv_gives_symbols_and_average_cost():
    frame = pd.DataFrame({"Instrument": ["METAL", "PHARMABEES-BE"], "Qty.": [10, 5], "Avg. cost": [11.2, np.nan]})
    assert holdings_from_kite_csv(frame) == [("METAL", 11.2), ("PHARMABEES", None)]
    with pytest.raises(ValueError):
        holdings_from_kite_csv(pd.DataFrame({"x": [1]}))


def test_symbols_map_to_exposures_through_the_registry():
    vehicles = pd.DataFrame({"exposure_id": ["metal", "metal", "pharma", "pharma"],
                             "symbol": ["METAL", "METALIETF", "PHARMABEES", None]})
    mapped, unknown = map_symbols([("metal", 11.0), ("METALIETF", None), ("PHARMABEES", None), ("TCS", 1.0)],
                                  vehicles)
    assert mapped == {"metal": ("metal", 11.0), "pharma": ("PHARMABEES", None)}
    assert unknown == ["TCS"]


def test_the_basket_buys_whole_units_at_target_weight_and_skips_index_funds():
    preview = _preview([])
    plan = plan_rebalance(preview, [])                  # buys a and b at 50% each
    funds = {"a": ("AETF", 33.0, "A ETF"), "b": (None, 12.0, "B Index Fund")}
    orders = buy_orders(plan, funds, 2_000_000)
    assert list(orders.columns) == ["Instrument", "Exchange", "Order Type", "Action", "Quantity", "Price",
                                    "ProductType", "TriggerPrice"]
    assert orders.to_dict("records") == [{"Instrument": "AETF", "Exchange": "NSE", "Order Type": "MARKET",
                                          "Action": "BUY", "Quantity": 30303, "Price": 0, "ProductType": "CNC",
                                          "TriggerPrice": 0}]
    assert buy_orders(plan, {"a": ("AETF", 0.0, "")}, 2_000_000).empty, "no price, no order"


def test_next_rebalance_is_the_month_end_and_fills_the_next_weekday():
    check, fill = next_rebalance(pd.Timestamp("2026-10-12"), pd.Timestamp("2026-09-30"))
    assert (check, fill) == (pd.Timestamp("2026-10-30"), pd.Timestamp("2026-11-02"))
    assert sessions_between(pd.Timestamp("2026-10-12"), check) == 14
    # On the month-end close itself, that close is the check.
    check, fill = next_rebalance(pd.Timestamp("2026-10-30"), pd.Timestamp("2026-10-30"))
    assert (check, fill) == (pd.Timestamp("2026-10-30"), pd.Timestamp("2026-11-02"))
