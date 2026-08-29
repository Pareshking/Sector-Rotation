from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from src.models.exposure import Exposure, ExposureCategory


class UniverseRegistry:
    def __init__(self, exposures: Iterable[Exposure], benchmark_name: str = "Nifty 50", benchmark_symbol: str = "^NSEI") -> None:
        self._exposures = tuple(exposures)
        self.benchmark_name = benchmark_name
        self.benchmark_symbol = benchmark_symbol
        self._by_id = {item.id: item for item in self._exposures}
        if len(self._by_id) != len(self._exposures):
            raise ValueError("Exposure IDs must be unique")

    @classmethod
    def from_json(cls, path: str | Path) -> "UniverseRegistry":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        exposures = [Exposure.model_validate(item) for item in payload.get("exposures", [])]
        benchmark = payload.get("benchmark", {})
        return cls(exposures, benchmark.get("name", "Nifty 50"), benchmark.get("yfinance_symbol", "^NSEI"))

    def all(self) -> tuple[Exposure, ...]:
        return self._exposures

    def sectors(self) -> tuple[Exposure, ...]:
        return tuple(x for x in self._exposures if x.category is ExposureCategory.SECTOR)

    def themes(self) -> tuple[Exposure, ...]:
        return tuple(x for x in self._exposures if x.category is ExposureCategory.THEMATIC)

    def get(self, exposure_id: str) -> Exposure:
        if exposure_id not in self._by_id:
            raise KeyError(f"Unknown exposure: {exposure_id}")
        return self._by_id[exposure_id]

    def etf_index(self) -> dict[str, Exposure]:
        return {etf.symbol: exposure for exposure in self._exposures for etf in exposure.etfs}
