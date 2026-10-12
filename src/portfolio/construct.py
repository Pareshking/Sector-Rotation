"""The one function that decides what the portfolio holds.

``construct_target_portfolio`` is pure: prices, metadata, the previous target
and the strategy config in; a target portfolio out. No I/O, no Streamlit, no
clock. The live dashboard, the alert tool and every rebalance in the backtest
call it — through ``decision_chain`` — so there is exactly one rule set and the
backtest is a test of the portfolio the dashboard shows.

The rule (strategy v1.0, ``src/config/strategy.json``):

1. Score every exposure with a full 12-month history (``score.py``).
2. Eligible = scorable and, when ``require_investable``, buyable on the date.
   Rank the eligible exposures by score (1 = best).
3. A current holding is kept while its rank is <= M (``retention_buffer_m``)
   and it clears the hurdle; otherwise it is sold.
4. Vacant slots are filled in rank order from ranks <= N (``target_holdings_n``)
   — never deeper. A rank <= N name that fails the hurdle leaves its slot in
   cash rather than handing it to a weaker name (classic dual momentum:
   relative momentum picks, absolute momentum decides whether to be invested).
5. Hurdle (``dual_momentum_cash_hurdle``): the exposure's own 12-month return
   must exceed the 12-month cash return — what the configured liquid fund's NAV
   actually returned over the same year, or the constant before its history.
6. Each slot is 1/N of the book; unfilled slots are cash.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from src.config import StrategyConfig
from src.portfolio.cash import trailing_12m
from src.portfolio.score import rank_by_score, score_exposures
from src.portfolio.universe import ExposureMeta

CASH = "__cash__"

BUY, HOLD, TRIM, SELL = "BUY", "HOLD", "TRIM", "SELL"
ACTIONS = (BUY, HOLD, TRIM, SELL)
_ACTION_ORDER = {BUY: 0, HOLD: 1, TRIM: 2, SELL: 3}

# Status of every exposure in the ranking table, so "why not X?" always has an answer.
STATUS_HELD = "held"
STATUS_NEW = "new entry"
STATUS_BELOW_BUFFER = "below retention buffer"
STATUS_HURDLE = "fails cash hurdle"
STATUS_WAITING = "inside buffer, entry needs rank <= N"
STATUS_SLOTS_FULL = "slots full"
STATUS_BELOW_ENTRY = "rank too low"
STATUS_NO_VEHICLE = "no buyable vehicle on this date"
STATUS_PRELAUNCH = "before index launch (back-calculated history)"
STATUS_NO_HISTORY = "insufficient history"

_EPS = 1e-12


@dataclass(frozen=True)
class Decision:
    exposure_id: str
    action: str
    prior_weight: float
    target_weight: float
    rank: int | None
    score: float | None
    reason: str


@dataclass(frozen=True)
class TargetPortfolio:
    as_of: pd.Timestamp
    weights: Mapping[str, float]
    decisions: tuple[Decision, ...]
    ranking: pd.DataFrame = field(repr=False)
    config_version: str = ""
    config_hash: str = ""
    eligible_count: int = 0
    notes: tuple[str, ...] = ()
    cash_hurdle_12m: float = float("nan")
    cash_hurdle_source: str = ""

    @property
    def holdings(self) -> tuple[str, ...]:
        """Held exposures in rank order (cash excluded)."""
        held = [k for k, w in self.weights.items() if k != CASH and w > _EPS]
        ranks = self.ranking["rank"] if "rank" in self.ranking else pd.Series(dtype=float)
        return tuple(sorted(held, key=lambda e: (_num(ranks.get(e), 1e9), e)))

    @property
    def cash_weight(self) -> float:
        return float(self.weights.get(CASH, 0.0))

    def to_dict(self) -> dict[str, object]:
        """Canonical, JSON-safe form. Floats keep full precision; NaN becomes null."""
        ranking = self.ranking.reset_index().rename(columns={"index": "exposure_id"})
        return {
            "as_of": pd.Timestamp(self.as_of).isoformat(),
            "config_version": self.config_version,
            "config_hash": self.config_hash,
            "eligible_count": int(self.eligible_count),
            "weights": {k: float(v) for k, v in sorted(self.weights.items())},
            "decisions": [
                {
                    "exposure_id": d.exposure_id,
                    "action": d.action,
                    "prior_weight": float(d.prior_weight),
                    "target_weight": float(d.target_weight),
                    "rank": d.rank,
                    "score": _json_float(d.score),
                    "reason": d.reason,
                }
                for d in self.decisions
            ],
            "notes": list(self.notes),
            "cash_hurdle_12m": _json_float(self.cash_hurdle_12m),
            "cash_hurdle_source": self.cash_hurdle_source,
            "ranking": [
                {k: _json_value(v) for k, v in row.items()}
                for row in ranking.to_dict("records")
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _num(value: object, default: float) -> float:
    try:
        out = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return default if math.isnan(out) else out


def _json_float(value: object) -> float | None:
    if value is None:
        return None
    out = float(value)  # type: ignore[arg-type]
    return None if math.isnan(out) or math.isinf(out) else out


def _json_value(value: object) -> object:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, np.datetime64):
        value = pd.Timestamp(value)
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return _json_float(value)
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    return value


def _clean_prior(prior_weights: Mapping[str, float] | None) -> dict[str, float]:
    prior = {str(k): float(v) for k, v in (prior_weights or {}).items() if float(v) > _EPS}
    return prior or {CASH: 1.0}


def construct_target_portfolio(
    current_date: pd.Timestamp,
    price_history: pd.DataFrame,
    universe_metadata: Mapping[str, ExposureMeta] | None,
    prior_weights: Mapping[str, float] | None,
    config: StrategyConfig,
    cash_nav: pd.Series | None = None,
) -> TargetPortfolio:
    """Target weights, signals and reasons for a rebalance at the close of ``current_date``.

    Only ``price_history.loc[:current_date]`` is read. ``prior_weights`` is the
    previous target (exposure id -> weight, cash under ``CASH``); empty means
    the book is in cash.
    """
    as_of = pd.Timestamp(current_date)
    meta = dict(universe_metadata or {})
    n, m = int(config.target_holdings_n), int(config.retention_buffer_m)
    # What cash actually returned over the same year, from the liquid fund's NAV;
    # the constant only before the fund had a year of history.
    hurdle, hurdle_source = trailing_12m(cash_nav, as_of, config.risk_free_rate_annual)
    use_hurdle = config.absolute_momentum_filter == "dual_momentum_cash_hurdle"
    exclude_prelaunch = config.backfill_policy == "exclude_prelaunch"

    scores = score_exposures(price_history, as_of, config)
    table = scores.copy()
    table["name"] = [meta[e].name if e in meta else str(e) for e in table.index]
    table["category"] = [meta[e].category if e in meta else "" for e in table.index]
    table["investable"] = [bool(meta[e].investable_on(as_of)) if e in meta else False for e in table.index]
    table["launch_date"] = [meta[e].launch_date if e in meta else None for e in table.index]
    table["backcalculated"] = [bool(meta[e].backcalculated_on(as_of)) if e in meta else False for e in table.index]
    eligible = table["valid"] & (table["investable"] if config.require_investable else True)
    if exclude_prelaunch:
        eligible &= ~table["backcalculated"].astype(bool)
    table["eligible"] = eligible.astype(bool)
    table["rank"] = rank_by_score(table.loc[table["eligible"], "score"]).reindex(table.index)
    table["hurdle_pass"] = (
        table["return_12m"].astype(float).gt(hurdle) if use_hurdle else table["valid"].astype(bool)
    )
    table["status"] = ""
    table["reason"] = ""

    rank = table["rank"]
    order = [e for e in rank.dropna().sort_values().index]  # eligible, best first
    prior = _clean_prior(prior_weights)
    held_before = [e for e in prior if e != CASH]

    def describe(e: str) -> str:
        r = rank.get(e)
        x = table.at[e, "return_12m"] if e in table.index else float("nan")
        bits = []
        if pd.notna(r):
            bits.append(f"rank {int(r)} of {len(order)} eligible")
        if pd.notna(table.at[e, "score"]) if e in table.index else False:
            bits.append(f"score {float(table.at[e, 'score']):+.2f}")
        if pd.notna(x):
            relation = ">" if x > hurdle else "<="
            bits.append(f"12M return {float(x):+.1%} {relation} cash {hurdle:.2%}")
        return ", ".join(bits)

    keep: list[str] = []
    sell_reason: dict[str, str] = {}
    for e in sorted(held_before, key=lambda x: (_num(rank.get(x), 1e9), x)):
        if e not in table.index or not bool(table.at[e, "valid"]):
            sell_reason[e] = "No longer scorable: the price history needed for a 12-month score is missing."
            continue
        if config.require_investable and not bool(table.at[e, "investable"]):
            sell_reason[e] = "Not buyable: no mapped vehicle had incepted by this date."
            continue
        if exclude_prelaunch and bool(table.at[e, "backcalculated"]):
            sell_reason[e] = "The index had not launched by this date; its history here is back-calculated."
            continue
        r = rank.get(e)
        if pd.isna(r) or int(r) > m:
            where = f"Rank {int(r)}" if pd.notna(r) else "Its rank"
            sell_reason[e] = f"{where} fell outside the retention buffer (rank <= {m}); {describe(e)}."
            table.at[e, "status"] = STATUS_BELOW_BUFFER
            continue
        if use_hurdle and not bool(table.at[e, "hurdle_pass"]):
            sell_reason[e] = f"Failed the cash hurdle; {describe(e)}."
            table.at[e, "status"] = STATUS_HURDLE
            continue
        keep.append(e)
    # If N was lowered, the best-ranked survivors keep their slots.
    for e in keep[n:]:
        sell_reason[e] = f"More holdings than slots (N = {n}); the better-ranked are kept; {describe(e)}."
    keep = keep[:n]
    retained = set(keep)

    entries: list[str] = []
    blocked: list[str] = []
    for e in order:
        r = int(rank[e])
        if r > n or len(keep) + len(entries) >= n:
            break
        if e in retained:
            continue
        if use_hurdle and not bool(table.at[e, "hurdle_pass"]):
            blocked.append(e)
            continue
        entries.append(e)
    target_ids = keep + entries
    weights: dict[str, float] = {e: 1.0 / n for e in target_ids}
    cash = 1.0 - len(target_ids) / n
    if cash > _EPS:
        weights[CASH] = cash

    # Status and reason for every exposure in the table.
    for e in table.index:
        if table.at[e, "status"]:
            pass
        elif e in retained:
            table.at[e, "status"] = STATUS_HELD
        elif e in entries:
            table.at[e, "status"] = STATUS_NEW
        elif not bool(table.at[e, "valid"]):
            table.at[e, "status"] = STATUS_NO_HISTORY
        elif config.require_investable and not bool(table.at[e, "investable"]):
            table.at[e, "status"] = STATUS_NO_VEHICLE
        elif exclude_prelaunch and bool(table.at[e, "backcalculated"]):
            table.at[e, "status"] = STATUS_PRELAUNCH
        elif e in blocked or (use_hurdle and not bool(table.at[e, "hurdle_pass"]) and int(rank[e]) <= n):
            table.at[e, "status"] = STATUS_HURDLE
        elif int(rank[e]) <= n:
            table.at[e, "status"] = STATUS_SLOTS_FULL
        elif int(rank[e]) <= m:
            table.at[e, "status"] = STATUS_WAITING
        else:
            table.at[e, "status"] = STATUS_BELOW_ENTRY
        table.at[e, "reason"] = describe(e) if bool(table.at[e, "valid"]) else STATUS_NO_HISTORY

    decisions: list[Decision] = []
    for e in sorted(set(held_before) | set(target_ids)):
        before, after = prior.get(e, 0.0), weights.get(e, 0.0)
        r = rank.get(e)
        score = table.at[e, "score"] if e in table.index else None
        if before <= _EPS:
            action = BUY
            reason = f"New entry at rank <= {n}: {describe(e)}."
        elif after <= _EPS:
            action = SELL
            reason = sell_reason.get(e, "Not in the target portfolio.")
        elif after < before - _EPS:
            action = TRIM
            reason = f"Held, cut to {after:.0%} of the book: {describe(e)}."
        elif after > before + _EPS:
            action = BUY
            reason = f"Held, raised to {after:.0%} of the book: {describe(e)}."
        else:
            action = HOLD
            reason = f"Retained inside the buffer (rank <= {m}): {describe(e)}."
        decisions.append(
            Decision(
                exposure_id=e,
                action=action,
                prior_weight=float(before),
                target_weight=float(after),
                rank=int(r) if pd.notna(r) else None,
                score=_json_float(score) if score is not None and pd.notna(score) else None,
                reason=reason,
            )
        )
    decisions.sort(key=lambda d: (_ACTION_ORDER[d.action], d.rank or 10**6, d.exposure_id))

    notes: list[str] = []
    eligible_count = int(table["eligible"].sum())
    if eligible_count == 0:
        notes.append("No exposure is eligible on this date; the book is in cash.")
    for e in blocked:
        notes.append(
            f"{table.at[e, 'name']} ranks {int(rank[e])} but fails the cash hurdle "
            f"({describe(e)}); its slot stays in cash."
        )
    if cash > _EPS:
        earning = (
            f"the liquid fund returned {hurdle:.1%} over the last 12 months"
            if hurdle_source == "nav"
            else f"assumed {hurdle:.1%} a year (before the liquid fund's NAV history)"
        )
        notes.append(f"{cash:.0%} of the book is in cash; {earning}.")

    table["target_weight"] = [weights.get(e, 0.0) for e in table.index]
    table["prior_weight"] = [prior.get(e, 0.0) for e in table.index]
    table["_order"] = table["rank"].astype("Float64").fillna(1e9)
    table["_id"] = table.index.astype(str)
    table = table.sort_values(["_order", "_id"], kind="mergesort").drop(columns=["_order", "_id"])
    table.index.name = "exposure_id"
    return TargetPortfolio(
        as_of=as_of,
        weights=dict(sorted(weights.items())),
        decisions=tuple(decisions),
        ranking=table,
        config_version=config.version,
        config_hash=config.config_hash,
        eligible_count=eligible_count,
        notes=tuple(notes),
        cash_hurdle_12m=float(hurdle),
        cash_hurdle_source=hurdle_source,
    )


def decision_chain(
    price_history: pd.DataFrame,
    universe_metadata: Mapping[str, ExposureMeta] | None,
    config: StrategyConfig,
    signal_dates: Sequence[pd.Timestamp],
    initial_weights: Mapping[str, float] | None = None,
    cash_nav: pd.Series | None = None,
) -> list[TargetPortfolio]:
    """Every rebalance decision in order, each one's target becoming the next one's prior.

    The retention buffer makes the strategy path-dependent — whether a rank-3
    name is held depends on whether it was held last month — so a live target
    is the end of this chain, never a one-off call on today's prices.
    """
    prior: Mapping[str, float] = dict(initial_weights or {CASH: 1.0})
    chain: list[TargetPortfolio] = []
    for when in signal_dates:
        target = construct_target_portfolio(when, price_history, universe_metadata, prior, config, cash_nav)
        chain.append(target)
        prior = target.weights
    return chain
