"""Schemas for every artifact the pipeline publishes; the run fails closed on any breach.

The app, the alert tool and the backtest all trust ``data/processed/``. Each
file therefore has a contract — required columns, types, value ranges, index
shape — checked before anything is written. A violation stops the run with
every problem listed, so a malformed dataset is never published in the first
place rather than discovered on the dashboard.

Plain pandas and pydantic (already dependencies), so the checks run wherever
the pipeline does.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Literal, Mapping

import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

VALUE_TYPES = {"TRI", "CLOSE", "NAV"}
STAGES = {"Leading", "Weakening", "Lagging", "Improving", "Insufficient Data"}
ACTIONS = {"BUY", "HOLD", "TRIM", "SELL", "CASH"}


class ContractViolation(ValueError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__("Artifact contract violated:\n  - " + "\n  - ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Column:
    kind: Literal["float", "int", "str", "bool", "datetime", "any"]
    nullable: bool = True
    min: float | None = None
    max: float | None = None
    allowed: frozenset | None = None
    unique: bool = False


_KIND_CHECK: dict[str, Callable[[pd.Series], bool]] = {
    "float": lambda s: pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s),
    "int": lambda s: pd.api.types.is_integer_dtype(s) or (
        pd.api.types.is_float_dtype(s) and bool((s.dropna() % 1 == 0).all())
    ),
    "str": lambda s: pd.api.types.is_string_dtype(s) or pd.api.types.is_object_dtype(s),
    "bool": lambda s: pd.api.types.is_bool_dtype(s),
    "datetime": lambda s: pd.api.types.is_datetime64_any_dtype(s),
    "any": lambda s: True,
}


@dataclass(frozen=True)
class FrameContract:
    name: str
    columns: Mapping[str, Column] = field(default_factory=dict)
    datetime_index: bool = False
    min_rows: int = 1
    # Applied to every column not named in ``columns`` (e.g. one per exposure).
    other_columns: Column | None = None
    checks: tuple[Callable[[pd.DataFrame], list[str]], ...] = ()

    def problems(self, frame: pd.DataFrame | None) -> list[str]:
        name = self.name
        if frame is None or not isinstance(frame, pd.DataFrame):
            return [f"{name}: not a DataFrame"]
        out: list[str] = []
        if len(frame) < self.min_rows:
            out.append(f"{name}: {len(frame)} rows, need at least {self.min_rows}")
        if self.datetime_index:
            if not isinstance(frame.index, pd.DatetimeIndex):
                out.append(f"{name}: index must be a DatetimeIndex")
            else:
                if frame.index.has_duplicates:
                    out.append(f"{name}: duplicate dates in the index")
                if not frame.index.is_monotonic_increasing:
                    out.append(f"{name}: index is not sorted ascending")
                if frame.index.hasnans:
                    out.append(f"{name}: missing dates in the index")
        for column, rule in self.columns.items():
            if column not in frame.columns:
                out.append(f"{name}: missing required column {column!r}")
                continue
            out += _column_problems(name, column, frame[column], rule)
        if self.other_columns is not None:
            for column in frame.columns:
                if column not in self.columns:
                    out += _column_problems(name, column, frame[column], self.other_columns)
        for check in self.checks:
            out += [f"{name}: {p}" for p in check(frame)]
        return out


def _column_problems(name: str, column: str, values: pd.Series, rule: Column) -> list[str]:
    label = f"{name}.{column}"
    out: list[str] = []
    present = values.dropna()
    if not rule.nullable and len(present) != len(values):
        out.append(f"{label}: {len(values) - len(present)} missing value(s) in a required column")
    if len(present) and not _KIND_CHECK[rule.kind](present if rule.kind != "bool" else values):
        out.append(f"{label}: expected {rule.kind}, got {values.dtype}")
        return out
    if rule.kind in ("float", "int") and len(present):
        numeric = pd.to_numeric(present, errors="coerce").astype(float)
        if np.isinf(numeric).any():
            out.append(f"{label}: infinite values")
        if rule.min is not None and (numeric < rule.min).any():
            out.append(f"{label}: {int((numeric < rule.min).sum())} value(s) below {rule.min}")
        if rule.max is not None and (numeric > rule.max).any():
            out.append(f"{label}: {int((numeric > rule.max).sum())} value(s) above {rule.max}")
    if rule.allowed is not None and len(present):
        bad = sorted({str(v) for v in present if v not in rule.allowed})
        if bad:
            out.append(f"{label}: unexpected value(s) {bad[:5]}")
    if rule.unique and present.duplicated().any():
        out.append(f"{label}: duplicate values {sorted(present[present.duplicated()].astype(str).unique())[:5]}")
    return out


# --------------------------------------------------------------------------- #
# Frame contracts
# --------------------------------------------------------------------------- #
POSITIVE_PRICE = Column("float", nullable=True, min=1e-12)


def _benchmark_complete(frame: pd.DataFrame) -> list[str]:
    if "__benchmark__" in frame.columns and frame["__benchmark__"].isna().any():
        return ["__benchmark__ has gaps: it is the session calendar and must be complete"]
    return []


def _no_empty_series(frame: pd.DataFrame) -> list[str]:
    empty = [c for c in frame.columns if frame[c].dropna().empty]
    return [f"series with no values: {empty[:8]}"] if empty else []


def _has_exposures(frame: pd.DataFrame) -> list[str]:
    return [] if any(c != "__benchmark__" for c in frame.columns) else ["no exposure columns"]


INDEX_PRICES = FrameContract(
    "index_prices",
    columns={"__benchmark__": Column("float", nullable=False, min=1e-12)},
    datetime_index=True,
    min_rows=253,
    other_columns=POSITIVE_PRICE,
    checks=(_benchmark_complete, _no_empty_series, _has_exposures),
)

ETF_PRICES = FrameContract(
    "etf_prices", datetime_index=True, min_rows=0, other_columns=POSITIVE_PRICE, checks=(_no_empty_series,)
)


def _plausible_liquid_fund(frame: pd.DataFrame) -> list[str]:
    nav = frame["nav"].dropna() if "nav" in frame else pd.Series(dtype=float)
    moves = nav.pct_change().dropna().abs()
    # A liquid fund moves basis points a day. A large jump is a wrong series.
    return [f"nav moved {moves.max():.1%} in a day; not a liquid fund"] if len(moves) and moves.max() > 0.05 else []


CASH_NAV = FrameContract(
    "cash_nav",
    columns={"nav": Column("float", nullable=False, min=1e-12)},
    datetime_index=True,
    min_rows=1,
    checks=(_plausible_liquid_fund,),
)


SUMMARY_RANKINGS = FrameContract(
    "summary_rankings",
    columns={
        "exposure_id": Column("str", nullable=False, unique=True),
        "exposure": Column("str", nullable=False),
        "category": Column("str", nullable=False, allowed=frozenset({"sector", "thematic"})),
        "benchmark": Column("str", nullable=False),
        "data_source": Column("str", nullable=False),
        "value_type": Column("str", nullable=False, allowed=frozenset(VALUE_TYPES)),
        "stage": Column("str", nullable=False, allowed=frozenset(STAGES)),
        "rank": Column("int", nullable=True, min=1),
        "momentum_z": Column("float", nullable=True),
        "rs_ratio": Column("float", nullable=True, min=0),
        "return_1M": Column("float", nullable=True, min=-1),
        "return_12M": Column("float", nullable=True, min=-1),
        "relative_12M": Column("float", nullable=True),
    },
)

ETF_UNIVERSE = FrameContract(
    "etf_universe",
    columns={
        "exposure_id": Column("str", nullable=False),
        "name": Column("str", nullable=False),
        "vehicle": Column("str", nullable=False, allowed=frozenset({"etf", "index_fund"})),
        "scheme_code": Column("int", nullable=True, min=1),
        "inception_date": Column("datetime", nullable=True),
    },
)


def _weights_sum_to_one(frame: pd.DataFrame) -> list[str]:
    if "weight" not in frame:
        return []
    total = float(frame["weight"].sum())
    return [] if abs(total - 1.0) <= 1e-9 else [f"weights sum to {total:.12f}, not 1"]


def _single_decision_date(frame: pd.DataFrame) -> list[str]:
    if "as_of" not in frame or frame["as_of"].nunique() == 1:
        return []
    return [f"{frame['as_of'].nunique()} decision dates in one target portfolio"]


PORTFOLIO_TARGET = FrameContract(
    "portfolio_target",
    columns={
        "as_of": Column("datetime", nullable=False),
        "exposure_id": Column("str", nullable=False, unique=True),
        "action": Column("str", nullable=False, allowed=frozenset(ACTIONS)),
        "weight": Column("float", nullable=False, min=0, max=1),
        "prior_weight": Column("float", nullable=False, min=0, max=1),
        "reason": Column("str", nullable=False),
        "config_version": Column("str", nullable=False),
        "config_hash": Column("str", nullable=False),
    },
    checks=(_weights_sum_to_one, _single_decision_date),
)

FRAME_CONTRACTS: dict[str, FrameContract] = {
    "index_prices": INDEX_PRICES,
    "etf_prices": ETF_PRICES,
    "cash_nav": CASH_NAV,
    "summary_rankings": SUMMARY_RANKINGS,
    "etf_universe": ETF_UNIVERSE,
    "portfolio_target": PORTFOLIO_TARGET,
}


# --------------------------------------------------------------------------- #
# metadata.json
# --------------------------------------------------------------------------- #
class QualityAlert(BaseModel):
    model_config = ConfigDict(extra="forbid")
    severity: Literal["error", "warning", "info"]
    check: str = Field(min_length=1)
    message: str


class MetadataContract(BaseModel):
    """The fields every consumer of ``metadata.json`` relies on. Extra keys are allowed."""

    model_config = ConfigDict(extra="allow")

    mode: Literal["fixture", "live"]
    last_updated_utc: datetime
    benchmark: str = Field(min_length=1)
    benchmark_value_type: Literal["TRI", "CLOSE", "NAV"]
    benchmark_source: str = Field(min_length=1)
    observations: int = Field(ge=253)
    valid_series: int = Field(ge=1)
    total_canonical_exposures: int = Field(ge=1)
    valid_canonical_series: int = Field(ge=0)
    canonical_coverage_ratio: float = Field(ge=0, le=1)
    index_panel_start: str
    index_panel_end: str
    source_by_canonical_exposure: dict[str, str]
    value_type_by_canonical_exposure: dict[str, Literal["TRI", "CLOSE", "NAV"]]
    strategy_version: str = Field(min_length=1)
    strategy_hash: str = Field(min_length=12, max_length=12)
    quality_alerts: list[QualityAlert]
    restatements: list[dict]
    cash_proxy: dict

    @field_validator("last_updated_utc")
    @classmethod
    def _aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("must carry a timezone")
        return value


def metadata_problems(metadata: Mapping) -> list[str]:
    try:
        MetadataContract.model_validate(dict(metadata))
    except ValidationError as exc:
        return [
            f"metadata.{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        ]
    return []


def validate_artifacts(frames: Mapping[str, pd.DataFrame], metadata: Mapping | None = None) -> list[str]:
    """Every contract breach across the artifacts, as plain sentences."""
    problems: list[str] = []
    for name, frame in frames.items():
        contract = FRAME_CONTRACTS.get(name)
        if contract is None:
            problems.append(f"{name}: no contract defined; every published artifact needs one")
            continue
        problems += contract.problems(frame)
    if metadata is not None:
        problems += metadata_problems(metadata)
    return problems


def enforce(frames: Mapping[str, pd.DataFrame], metadata: Mapping | None = None) -> None:
    problems = validate_artifacts(frames, metadata)
    if problems:
        raise ContractViolation(problems)
