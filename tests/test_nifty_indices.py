from __future__ import annotations

from datetime import date

import pandas as pd

import src.data.nifty_indices as nifty


CANONICAL_NAMES = {
    "capital-goods": "NIFTY CAPITAL GOODS",
    "cement": "NIFTY CEMENT",
    "chemicals": "NIFTY CHEMICALS",
    "consumer-durables": "NIFTY CONSUMER DURABLES",
    "consumer-services": "NIFTY CONSUMER SERVICES",
    "financial-services": "NIFTY FINANCIAL SERVICES",
    "financial-ex-bank": "NIFTY FINANCIAL SERVICES EX-BANK",
    "healthcare": "NIFTY HEALTHCARE INDEX",
    "oil-gas": "NIFTY OIL & GAS",
    "power": "NIFTY POWER",
    "private-bank": "NIFTY PRIVATE BANK",
    "telecom": "NIFTY TELECOMMUNICATIONS",
    "defence": "NIFTY INDIA DEFENCE",
    "ev-new-energy-auto": "NIFTY EV & NEW AGE AUTOMOTIVE",
    "manufacturing": "NIFTY INDIA MANUFACTURING",
    "infrastructure": "NIFTY INFRASTRUCTURE",
    "infrastructure-logistics": "NIFTY INDIA INFRASTRUCTURE & LOGISTICS",
    "railways": "NIFTY INDIA RAILWAYS PSU",
    "consumption": "NIFTY INDIA CONSUMPTION",
    "digital": "NIFTY INDIA DIGITAL",
    "internet": "NIFTY INDIA INTERNET",
    "tourism": "NIFTY INDIA TOURISM",
    "energy": "NIFTY ENERGY",
    "commodities": "NIFTY COMMODITIES",
    "capital-markets": "NIFTY CAPITAL MARKETS",
    "mnc": "NIFTY MNC",
    "pse": "NIFTY PSE",
    "cpse": "NIFTY CPSE",
    "services": "NIFTY SERVICES SECTOR",
    "rural": "NIFTY RURAL",
    "mobility": "NIFTY MOBILITY",
    "reit-invit": "NIFTY REITS & INVITS",
    "nbfc": "NIFTY NBFC",
}

UNIVERSE_BENCHMARKS = {
    "capital-goods": "NIFTY CAPITAL GOODS",
    "cement": "Nifty Cement",
    "chemicals": "Nifty Chemicals",
    "consumer-durables": "Nifty Consumer Durables",
    "consumer-services": "NIFTY CONSUMER SERVICES",
    "financial-services": "NIFTY FINANCIAL SERVICES",
    "financial-ex-bank": "NIFTY FINANCIAL SERVICES EX-BANK",
    "healthcare": "NIFTY HEALTHCARE",
    "oil-gas": "Nifty OIL & GAS",
    "power": "NIFTY POWER",
    "private-bank": "Nifty Private Bank",
    "telecom": "NIFTY TELECOMMUNICATIONS",
    "defence": "Nifty India Defence",
    "ev-new-energy-auto": "Nifty EV & New Age Automotive",
    "manufacturing": "Nifty India Manufacturing",
    "infrastructure": "Nifty Infrastructure",
    "infrastructure-logistics": "Nifty India Infrastructure & Logistics",
    "railways": "Nifty India Railways PSU",
    "consumption": "Nifty India Consumption",
    "digital": "Nifty India Digital",
    "internet": "Nifty India Internet",
    "tourism": "Nifty India Tourism",
    "energy": "Nifty Energy",
    "commodities": "Nifty Commodities",
    "capital-markets": "Nifty Capital Markets",
    "mnc": "Nifty MNC",
    "pse": "Nifty PSE",
    "cpse": "Nifty CPSE",
    "services": "Nifty Services Sector",
    "rural": "Nifty Rural",
    "mobility": "Nifty Mobility",
    "reit-invit": "Nifty REITs & InvITs",
    "nbfc": "Nifty NBFC",
}


def _catalogue() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "name": list(CANONICAL_NAMES.values()),
            "category": ["Sectoral Indices"] * 13 + ["Thematic Indices"] * 20,
        }
    )


def test_catalogue_resolution_covers_all_currently_problematic_exposures() -> None:
    catalogue = _catalogue()
    for exposure_id, official_name in CANONICAL_NAMES.items():
        assert nifty.resolve_catalogue_name(UNIVERSE_BENCHMARKS[exposure_id], catalogue=catalogue) == official_name


def test_explicit_aliases_resolve_to_official_names() -> None:
    catalogue = _catalogue()
    expected = {
        "telecom": "NIFTY TELECOMMUNICATIONS",
        "nbfc": "NIFTY NBFC",
        "healthcare": "NIFTY HEALTHCARE INDEX",
        "power": "NIFTY POWER",
        "capital-goods": "NIFTY CAPITAL GOODS",
        "consumer-services": "NIFTY CONSUMER SERVICES",
    }
    for alias, official_name in expected.items():
        assert nifty.resolve_catalogue_name(alias, catalogue=catalogue) == official_name
        assert official_name in nifty.resolve_index_names(alias, catalogue=catalogue)


def test_catalogue_discovery_uses_official_hierarchy(monkeypatch, tmp_path) -> None:
    calls: list[tuple[str, object]] = []

    def fake_post(url: str, payload: object, timeout: int = 15) -> list[object]:
        calls.append((url, payload))
        if url == nifty.TYPE_ENDPOINT:
            return [
                {"indextype": "Broad Market Indices"},
                {"indextype": "Sectoral Indices"},
                {"indextype": "Thematic Indices"},
            ]
        subtype = payload["cinfo"]["indextype"]
        names = {
            "Broad Market Indices": [{"indextype": "NIFTY 50"}],
            "Sectoral Indices": [
                {"indextype": "NIFTY TELECOMMUNICATIONS"},
                {"indextype": "NIFTY HEALTHCARE INDEX"},
            ],
            "Thematic Indices": [
                {"indextype": "NIFTY INDIA DEFENCE"},
                {"indextype": "NIFTY MOBILITY"},
            ],
        }
        return names.get(subtype, [])

    monkeypatch.setattr(nifty, "_post_json", fake_post)
    monkeypatch.setattr(nifty, "CATALOGUE_CACHE_FILE", tmp_path / "catalogue.json")
    frame = nifty.discover_index_catalogue(force_refresh=True, cache_seconds=0)
    assert set(frame["name"]) == {
        "NIFTY 50",
        "NIFTY TELECOMMUNICATIONS",
        "NIFTY HEALTHCARE INDEX",
        "NIFTY INDIA DEFENCE",
        "NIFTY MOBILITY",
    }
    assert len(calls) == 4


def test_historical_parser_accepts_90_consecutive_rows() -> None:
    dates = pd.bdate_range("2026-01-02", periods=90)
    rows = [
        {"HistoricalDate": timestamp.strftime("%d %b %Y"), "CLOSE": f"{1000 + i:.2f}"}
        for i, timestamp in enumerate(dates)
    ]
    series = nifty._rows_to_series("NIFTY CAPITAL GOODS", rows)
    assert len(series) == 90
    assert series.index.is_monotonic_increasing
    assert series.iloc[0] == 1000.0
    assert series.iloc[-1] == 1089.0
    assert len(series.dropna()) >= nifty.MIN_OBSERVATIONS


def test_tri_parser_uses_total_return_index_column() -> None:
    rows = [
        {"Date": "02 Jan 2026", "TotalReturnsIndex": "100.00"},
        {"Date": "05 Jan 2026", "TotalReturnsIndex": "101.50"},
    ]
    series = nifty._rows_to_series("NIFTY TELECOMMUNICATIONS", rows, tri=True)
    assert series.tolist() == [100.0, 101.5]


def test_tri_is_preferred_before_price_index(monkeypatch) -> None:
    calls: list[bool] = []

    def fake_request_history(name: str, start: date, end: date, timeout: int, tri: bool) -> pd.Series:
        calls.append(tri)
        return pd.Series(
            range(60),
            index=pd.bdate_range("2026-01-01", periods=60),
            dtype="float64",
            name=name,
        )

    monkeypatch.setattr(nifty, "_request_history", fake_request_history)
    series = nifty.fetch_nifty_index_history(
        "healthcare",
        start=date(2026, 1, 1),
        end=date(2026, 4, 1),
        retries=1,
        catalogue=_catalogue(),
    )
    assert len(series) == 60
    assert calls == [True]
    assert series.attrs["source"] == "niftyindices_tri"
    assert series.attrs["resolved_name"] == "NIFTY HEALTHCARE INDEX"
