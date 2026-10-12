"""The versioned strategy specification.

``strategy.json`` is the single source of every parameter that decides what
the portfolio holds. The live dashboard, the alert tool and the backtest all
load it through ``load_strategy_config``; nothing else may hard-code a top-N,
a buffer, a score weighting, a hurdle or a cost. Its hash is stamped on every
target portfolio so a published decision always names the rules that made it.
"""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

STRATEGY_PATH = Path(__file__).with_name("strategy.json")

# Non-overlapping return segments, in trading sessions back from the signal
# date: (newer edge, older edge). Together they tile the last 252 sessions
# exactly once, so a segment weight means what it says. The overlapping
# 1M/3M/6M/12M composite this replaces weighted the latest month ~7.9x the
# oldest six through overlap alone.
SEGMENTS: dict[str, tuple[int, int]] = {
    "1M": (0, 21),
    "3M-1M": (21, 63),
    "6M-3M": (63, 126),
    "12M-6M": (126, 252),
}
FULL_HISTORY_SESSIONS = 252


class VolAdjustedSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    return_lookback_days: int = Field(252, ge=21)
    ewma_span_days: int = Field(126, ge=10)


class ScoreSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    method: Literal["segment_composite", "vol_adjusted_12m"] = "segment_composite"
    segments: dict[str, float] = Field(default_factory=lambda: {k: 0.25 for k in SEGMENTS})
    vol_adjusted: VolAdjustedSpec = Field(default_factory=VolAdjustedSpec)

    @field_validator("segments")
    @classmethod
    def _known_segments(cls, value: dict[str, float]) -> dict[str, float]:
        unknown = set(value) - set(SEGMENTS)
        if unknown:
            raise ValueError(f"unknown segments {sorted(unknown)}; expected {list(SEGMENTS)}")
        if any(w < 0 for w in value.values()):
            raise ValueError("segment weights must be non-negative")
        if sum(value.values()) <= 0:
            raise ValueError("segment weights must sum to more than zero")
        total = sum(value.values())
        return {k: float(value.get(k, 0.0)) / total for k in SEGMENTS}


class StrategyConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: str
    description: str = ""
    target_holdings_n: int = Field(ge=1)
    retention_buffer_m: int = Field(ge=1)
    rebalance_months: int = Field(1, ge=1, le=12)
    score_weights: ScoreSpec = Field(default_factory=ScoreSpec)
    absolute_momentum_filter: Literal["dual_momentum_cash_hurdle", "none"] = (
        "dual_momentum_cash_hurdle"
    )
    risk_free_rate_annual: float = Field(0.065, ge=0.0, le=0.5)
    require_investable: bool = True
    execution_fill: Literal["t_plus_1_close"] = "t_plus_1_close"
    cost_bps_per_side: float = Field(25.0, ge=0.0, le=500.0)

    @model_validator(mode="after")
    def _buffer_not_tighter_than_entry(self) -> StrategyConfig:
        if self.retention_buffer_m < self.target_holdings_n:
            raise ValueError(
                f"retention_buffer_m ({self.retention_buffer_m}) must be at least "
                f"target_holdings_n ({self.target_holdings_n}): a holding would be sold the "
                "moment it was bought"
            )
        return self

    def replace(self, **changes) -> StrategyConfig:
        """A validated copy with some fields changed (for what-if runs, never the live rules)."""
        return StrategyConfig.model_validate({**self.model_dump(), **changes})

    @property
    def config_hash(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]

    @property
    def cash_hurdle_12m(self) -> float:
        """The 12-month cash return an exposure must beat."""
        return float(self.risk_free_rate_annual)


@lru_cache(maxsize=4)
def _load(path: str) -> StrategyConfig:
    return StrategyConfig.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def load_strategy_config(path: str | Path | None = None) -> StrategyConfig:
    return _load(str(path or STRATEGY_PATH))
