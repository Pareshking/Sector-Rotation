from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExposureCategory(str, Enum):
    SECTOR = "sector"
    THEMATIC = "thematic"


class TrackingMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    aum_crore: Optional[float] = Field(default=None, ge=0)
    expense_ratio: Optional[float] = Field(default=None, ge=0)
    liquidity_score: Optional[float] = Field(default=None, ge=0, le=100)
    tracking_error: Optional[float] = Field(default=None, ge=0)


class ETFMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    symbol: str = Field(min_length=1)
    name: str = Field(min_length=1)
    yfinance_symbol: Optional[str] = None
    exchange: str = "NSE"
    aliases: list[str] = Field(default_factory=list)
    tracking: TrackingMetrics = Field(default_factory=TrackingMetrics)

    @field_validator("symbol", "exchange")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("aliases")
    @classmethod
    def normalize_aliases(cls, value: list[str]) -> list[str]:
        return sorted({item.strip().upper() for item in value if item.strip()})


class Exposure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1)
    category: ExposureCategory
    benchmark: str = Field(min_length=1)
    yfinance_symbol: Optional[str] = None
    etfs: list[ETFMapping] = Field(default_factory=list)

    @property
    def is_sector(self) -> bool:
        return self.category is ExposureCategory.SECTOR

    @property
    def is_thematic(self) -> bool:
        return self.category is ExposureCategory.THEMATIC

    @property
    def tradable(self) -> bool:
        return bool(self.etfs)
