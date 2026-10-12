"""Best-vehicle choice, days to build, and the display regime."""

import numpy as np
import pandas as pd
import pytest

from src.portfolio.regime import RISK_OFF, RISK_ON, market_regime
from src.portfolio.vehicles import VehicleChoice, choose_vehicle, days_to_build

AS_OF = pd.Timestamp("2026-09-30")


def _vehicles(*rows):
    return pd.DataFrame(
        [
            {"exposure_id": "auto", "symbol": None, "vehicle": "etf", "scheme_code": i + 1,
             "traded_value": None, **row}
            for i, row in enumerate(rows)
        ]
    )


def _tracking(*rows):
    return pd.DataFrame(rows)


def test_the_fund_that_gave_up_least_wins():
    vehicles = _vehicles(
        {"symbol": "AUTOBEES", "name": "Nippon Auto ETF", "inception_date": "2022-01-24", "traded_value": 9e7},
        {"symbol": "AUTOIETF", "name": "ICICI Auto ETF", "inception_date": "2022-01-20", "traded_value": 1e6},
        {"name": "HDFC Auto Index Fund", "vehicle": "index_fund", "inception_date": "2024-01-01"},
    )
    tracking = _tracking(
        {"symbol": "AUTOBEES", "name": "Nippon Auto ETF", "tracking_difference": -0.0060, "history_years": 4.6},
        {"symbol": "AUTOIETF", "name": "ICICI Auto ETF", "tracking_difference": -0.0031, "history_years": 4.6},
        {"symbol": None, "name": "HDFC Auto Index Fund", "tracking_difference": -0.0010, "history_years": 0.6},
    )
    choice = choose_vehicle("auto", AS_OF, vehicles, tracking)
    assert choice.key == "AUTOIETF"  # the index fund tracks better but has under a year of record
    assert "Least tracking difference" in choice.reason
    assert choice.label == "AUTOIETF · ICICI Auto ETF"


def test_a_fund_that_had_not_incepted_is_never_chosen():
    vehicles = _vehicles(
        {"symbol": "OLD", "name": "Old ETF", "inception_date": "2020-01-01"},
        {"symbol": "NEW", "name": "New ETF", "inception_date": "2026-10-15"},
    )
    tracking = _tracking(
        {"symbol": "OLD", "name": "Old ETF", "tracking_difference": -0.02, "history_years": 5},
        {"symbol": "NEW", "name": "New ETF", "tracking_difference": -0.001, "history_years": 3},
    )
    assert choose_vehicle("auto", AS_OF, vehicles, tracking).key == "OLD"


def test_without_tracking_the_most_traded_etf_then_the_oldest_fund():
    vehicles = _vehicles(
        {"symbol": "A", "name": "A ETF", "inception_date": "2023-01-01", "traded_value": 5e6},
        {"symbol": "B", "name": "B ETF", "inception_date": "2024-01-01", "traded_value": 8e7},
    )
    assert choose_vehicle("auto", AS_OF, vehicles).key == "B"
    funds = _vehicles(
        {"name": "Later Fund", "vehicle": "index_fund", "inception_date": "2025-01-01"},
        {"name": "Earlier Fund", "vehicle": "index_fund", "inception_date": "2023-06-01"},
    )
    assert choose_vehicle("auto", AS_OF, funds).key == "Earlier Fund"


def test_no_incepted_vehicle_means_no_choice():
    vehicles = _vehicles({"symbol": "NEW", "name": "New ETF", "inception_date": "2027-01-01"})
    assert choose_vehicle("auto", AS_OF, vehicles) is None
    assert choose_vehicle("auto", AS_OF, pd.DataFrame()) is None


def _choice(vehicle: str, turnover: float | None) -> VehicleChoice:
    return VehicleChoice("auto", "X", "X", vehicle, "X", 1, "", traded_value=turnover)


def test_days_to_build():
    assert days_to_build(_choice("index_fund", None), 1_500_000) == 1.0  # fills at the next NAV
    assert days_to_build(_choice("etf", 5_000_000), 1_500_000) == 3.0  # 10% of ₹50 lakh a day
    assert days_to_build(_choice("etf", 90_000_000), 1_500_000) == 1.0
    assert days_to_build(_choice("etf", None), 1_500_000) is None  # no turnover: cannot judge
    assert days_to_build(None, 1_500_000) is None


def _bench(annual: float, days: int = 400) -> pd.Series:
    index = pd.bdate_range(end="2026-10-09", periods=days)
    return pd.Series(100 * (1 + annual) ** (np.arange(days) / 252), index=index)


def _nav(annual: float) -> pd.Series:
    days = pd.date_range("2013-01-01", "2026-12-31", freq="D")
    return pd.Series(1000 * (1 + annual) ** ((days - days[0]).days / 365.25), index=days)


def test_the_regime_compares_the_benchmarks_year_with_cashs():
    on = market_regime(_bench(0.12), _nav(0.065), 0.065)
    off = market_regime(_bench(-0.08), _nav(0.065), 0.065)
    assert on.label == RISK_ON and off.label == RISK_OFF
    assert on.benchmark_12m == pytest.approx(0.12, abs=1e-9)
    assert on.cash_source == "nav" and on.cash_12m == pytest.approx(0.065, abs=1e-3)


def test_a_benchmark_beaten_by_cash_is_risk_off():
    """+5% equity against a 6.5% liquid fund: holding cash paid more."""
    assert market_regime(_bench(0.05), _nav(0.065), 0.065).label == RISK_OFF


def test_the_regime_falls_back_to_the_constant_and_needs_a_year():
    assert market_regime(_bench(0.10), None, 0.065).cash_source == "constant"
    assert market_regime(_bench(0.10, days=200), None, 0.065) is None
