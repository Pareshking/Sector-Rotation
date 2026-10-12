"""The Screener's pure helpers (app/components/screener.py) and its table markup (app/kit/screener_table.py)."""

import math

import pandas as pd

from app.components import screener as scr
from app.kit.screener_table import exposure_href, signed_pct, table_html


def _decisions() -> pd.DataFrame:
    # e is not tradeable and ranks first in the universe; the portfolio ranks a-d only.
    return pd.DataFrame({
        "exposure_id": ["e", "a", "b", "c", "d"],
        "exposure": ["Telecom", "Pharma", "Metals", "Banks", "FMCG"],
        "category": ["sector", "sector", "sector", "thematic", "thematic"],
        "benchmark": ["Nifty Telecom", "Nifty Pharma", "Nifty Metal", "Nifty Bank", None],
        "rank": [1.0, 2.0, 3.0, 4.0, 5.0],
        "decision_rank": [float("nan"), 3.0, 1.0, 2.0, 4.0],
        "momentum_z": [1.5, 0.9, 0.5, 0.1, -0.4],
        "return_1M": [0.01, 0.02, -0.03, 0.0, float("nan")],
        "return_3M": [0.05, 0.04, -0.01, 0.02, -0.02],
        "return_6M": [0.1, 0.08, 0.02, 0.01, -0.05],
        "return_12M": [0.3, 0.2, 0.05, 0.08, -0.1],
        "relative_1M": [0.0] * 5, "relative_3M": [0.0] * 5, "relative_6M": [0.0] * 5,
        "relative_12M": [0.01, 0.02, 0.03, 0.04, 0.05],
        "model_action": ["NOT HELD", "NOT HELD", "HOLD", "HOLD", "NOT HELD"],
        "tradeable": [False, True, True, True, True],
        "stage": ["Leading", "Leading", "Weakening", None, "Lagging"],
        "max_drawdown": [-0.3, -0.2, -0.33, -0.25, float("nan")],
    })


def test_rank_change_compares_ranks_over_the_same_tradeable_set():
    """decision_rank counts only exposures with a fund, so today's rank is re-ranked over that set."""
    d = _decisions()
    assert scr.portfolio_rank(d).tolist()[1:] == [1.0, 2.0, 3.0, 4.0]
    assert math.isnan(scr.portfolio_rank(d).iloc[0])
    # Pharma 3 -> 1 climbed two places; Metals 1 -> 2 fell one; FMCG stayed.
    assert scr.rank_change(d).tolist()[1:] == [2.0, -1.0, -1.0, 0.0]


def test_presets_count_from_the_data():
    d = _decisions()
    masks = scr.preset_masks(d, hurdle=0.07, buffer=2)
    counts = {p: int(m.sum()) for p, m in masks.items()}
    assert counts == {"Tradeable": 4, "All": 5, "Held": 2, "Top": 2, "Beating cash": 3,
                      "Sectors": 3, "Themes": 2}
    assert list(d.loc[masks["Top"], "exposure"]) == ["Pharma", "Metals"]
    assert scr.DEFAULT_PRESET == "Tradeable" and tuple(masks) == scr.PRESETS


def test_preset_labels_carry_counts_without_repeating_the_buffer():
    assert scr.preset_label("Tradeable", 37, 4) == "Tradeable 37"
    assert scr.preset_label("Top", 4, 4) == "Top 4"
    assert scr.preset_label("Top", 3, 4) == "Top 4 3"


def test_search_lists_exposures_then_each_index_once():
    d = _decisions()
    d.loc[4, "benchmark"] = "Nifty Bank"  # two exposures on one index
    options, by_name, by_index = scr.search_options(d)
    assert options[:5] == ["Telecom", "Pharma", "Metals", "Banks", "FMCG"]
    assert options[5:] == ["[INDEX] Nifty Bank", "[INDEX] Nifty Metal", "[INDEX] Nifty Pharma",
                           "[INDEX] Nifty Telecom"]
    assert by_name["Banks"] == "c" and by_index["[INDEX] Nifty Bank"] == ["c", "d"]


def test_fund_counts_only_funds_that_have_started():
    vehicles = pd.DataFrame({"exposure_id": ["a", "a", "b"],
                             "inception_date": pd.to_datetime(["2020-01-01", "2027-01-01", None])})
    counts = scr.fund_counts(vehicles, "2026-10-12")
    assert counts.to_dict() == {"a": 1, "b": 1}


def test_display_frame_sub_line_hurdle_and_status():
    d = _decisions()
    levels = pd.Series({"a": 100.0, "b": 200.0})
    out = scr.display_frame(d, levels, pd.Series({"a": 2, "b": 1}), hurdle=0.07)
    assert out.loc[1, "Sub"] == "Sector · Nifty Pharma · 2 funds"
    assert out.loc[2, "Sub"] == "Sector · Nifty Metal · 1 fund"
    assert out.loc[4, "Sub"] == "Theme · No fund"  # no index name: never "None"
    assert out["Portfolio"].tolist() == ["No fund", "Not held", "HOLD", "HOLD", "Not held"]
    assert round(out.loc[1, "12M vs cash"], 6) == 0.13
    relative = scr.display_frame(d, levels, pd.Series(dtype=int), hurdle=None, relative=True)
    assert relative["12M"].tolist() == [0.01, 0.02, 0.03, 0.04, 0.05]
    assert relative["12M vs cash"].isna().all()


def test_sort_puts_the_best_first_and_gaps_last():
    out = scr.display_frame(_decisions(), pd.Series(dtype=float), pd.Series(dtype=int), hurdle=None)
    assert scr.sort_frame(out, "Rank Δ")["Exposure"].tolist() == ["Pharma", "FMCG", "Metals", "Banks", "Telecom"]
    assert scr.sort_frame(out, "Max DD")["Exposure"].tolist()[:2] == ["Pharma", "Banks"]
    assert scr.sort_frame(out, "Max DD")["Exposure"].tolist()[-1] == "FMCG"
    assert scr.sort_frame(out, "nonsense")["Rank"].tolist() == [1, 2, 3, 4, 5]


def test_movers_split_risers_and_fallers():
    out = scr.display_frame(_decisions(), pd.Series(dtype=float), pd.Series(dtype=int), hurdle=None)
    risers, fallers = scr.movers(out)
    assert risers["Exposure"].tolist() == ["Pharma"]
    assert fallers["Exposure"].tolist() == ["Metals", "Banks"]


def test_table_markup_dashes_gaps_and_links_rows_to_the_exposure_page():
    d = _decisions()
    out = scr.display_frame(d, pd.Series({"a": 1234.6}), pd.Series({"a": 2}), hurdle=0.07)
    panel = pd.DataFrame({"a": range(1, 30)}, index=pd.bdate_range("2026-01-01", periods=29), dtype=float)
    markup = table_html(out, panel, sorted_by="dlt", ascending=False)
    body = markup[markup.index("<tbody>"):markup.index("</tbody>")]
    assert "None" not in body and "nan" not in body.lower()
    assert '<tr data-stock="a">' in markup and exposure_href("a") in markup
    assert ">1,235<span" in markup and "₹" not in markup  # an index level, not a price
    assert '<span class="chip up">▲ 2</span>' in markup
    assert '<span class="badge up">Hold</span>' in markup
    assert "<polyline" in markup  # the 12-month path for the exposure with prices
    assert 'class="t-left" data-type=""' not in markup
    assert 'data-type="num" data-dir="desc"' in markup  # the header arrow follows the sort
    assert "Momentum" in markup and "Rank dynamics" in markup


def test_signed_pct_uses_a_true_minus_and_dashes_missing():
    assert signed_pct(0.1234) == "+12.3%"
    assert signed_pct(-0.05) == "−5.0%"
    assert signed_pct(None) == "—"
