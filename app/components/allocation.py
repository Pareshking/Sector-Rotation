"""What the Portfolio page shows, as plain rows: testable without rendering anything.

Every number comes from the strategy's own ``TargetPortfolio``
(``src/portfolio/construct.py``) and vehicle rule (``src/portfolio/vehicles.py``);
this module only arranges them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

import pandas as pd

from src.portfolio.vehicles import days_to_build

CASH_LABEL = "Cash"


@dataclass(frozen=True)
class AllocationRow:
    exposure_id: str
    exposure: str
    vehicle: str
    vehicle_reason: str
    target: float
    held: float
    action: str
    cost_bps: float
    days_to_build: float | None
    reason: str
    is_cash: bool = False


def allocation_rows(
    target,
    names: Mapping[str, str],
    vehicle_for: Callable[[str], object],
    book_rupees: float,
    cost_bps_per_side: float,
    cash_name: str,
    cash_reason: str,
) -> list[AllocationRow]:
    """One row per decision in the target, then cash. Targets sum to one."""
    rows: list[AllocationRow] = []
    for decision in target.decisions:
        choice = vehicle_for(decision.exposure_id)
        traded = abs(float(decision.target_weight) - float(decision.prior_weight))
        days = days_to_build(choice, decision.target_weight * book_rupees) if decision.target_weight > 0 else None
        rows.append(
            AllocationRow(
                exposure_id=decision.exposure_id,
                exposure=names.get(decision.exposure_id, decision.exposure_id),
                vehicle=choice.label if choice is not None else "No buyable vehicle",
                vehicle_reason=choice.reason if choice is not None else "",
                target=float(decision.target_weight),
                held=float(decision.prior_weight),
                action=str(decision.action),
                cost_bps=traded * float(cost_bps_per_side),
                days_to_build=days,
                reason=str(decision.reason),
            )
        )
    prior_cash = max(0.0, 1.0 - sum(float(d.prior_weight) for d in target.decisions))
    rows.append(
        AllocationRow(
            exposure_id="__cash__",
            exposure=CASH_LABEL,
            vehicle=cash_name,
            vehicle_reason="",
            target=float(target.cash_weight),
            held=prior_cash,
            action="—",
            cost_bps=0.0,
            days_to_build=1.0 if target.cash_weight > 0 else None,
            reason=cash_reason,
            is_cash=True,
        )
    )
    return rows


def allocation_frame(rows: list[AllocationRow]) -> pd.DataFrame:
    """The rows as the table a reader would export."""
    return pd.DataFrame(
        {
            "Exposure": [r.exposure for r in rows],
            "Best vehicle": [r.vehicle for r in rows],
            "Target": [r.target for r in rows],
            "Held now": [r.held for r in rows],
            "Action": [r.action for r in rows],
            "Est. cost (bps of book)": [r.cost_bps for r in rows],
            "Days to build": [r.days_to_build for r in rows],
        }
    )


def edge_frame(target, names: Mapping[str, str], n: int, m: int) -> pd.DataFrame:
    """Ranks n+1..m: held only because of the retention buffer, or next in line to enter."""
    ranking = target.ranking
    if ranking is None or ranking.empty or "rank" not in ranking:
        return pd.DataFrame(columns=["rank", "exposure_id", "exposure", "held", "role", "score", "return_12m", "status"])
    ranked = ranking[pd.to_numeric(ranking["rank"], errors="coerce").notna()]
    ranks = ranked["rank"].astype(int)
    edge = ranked[(ranks > n) & (ranks <= m)]
    held = [float(target.weights.get(e, 0.0)) > 0 for e in edge.index]
    return pd.DataFrame(
        {
            "rank": edge["rank"].astype(int).to_numpy(),
            "exposure_id": list(edge.index),
            "exposure": [names.get(e, e) for e in edge.index],
            "held": held,
            "role": ["Held via buffer" if h else "Next in line" for h in held],
            "score": pd.to_numeric(edge.get("score"), errors="coerce").to_numpy(),
            "return_12m": pd.to_numeric(edge.get("return_12m"), errors="coerce").to_numpy(),
            "status": edge.get("status", pd.Series("", index=edge.index)).fillna("").astype(str).to_numpy(),
        }
    ).sort_values("rank", kind="mergesort").reset_index(drop=True)
