import pandas as pd

from src.quantitative.quality import FLATLINE_DAYS, check_dataset


def _prices(days: int = 60, flat: bool = False) -> pd.DataFrame:
    index = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=days)
    values = [100.0] * days if flat else [100.0 + i for i in range(days)]
    return pd.DataFrame({"auto": values, "bank": [100.0 + i for i in range(days)]}, index=index)


def test_etf_coverage_regression_is_reported():
    """31 -> 29 passed silently in production; it must not."""
    report = check_dataset({"etf_valid_series": 29}, {"etf_valid_series": 31}, _prices())
    assert any(a["check"] == "coverage_regression" for a in report.warnings)


def test_canonical_coverage_regression_is_an_error():
    report = check_dataset({"valid_canonical_series": 40}, {"valid_canonical_series": 47}, _prices())
    assert not report.ok
    assert any(a["check"] == "coverage_regression" for a in report.errors)


def test_a_dropped_canonical_exposure_is_an_error():
    report = check_dataset(
        {"source_by_canonical_exposure": {"auto": "x"}},
        {"source_by_canonical_exposure": {"auto": "x", "bank": "x"}},
        _prices(),
    )
    assert not report.ok
    assert any("bank" in a["message"] for a in report.errors)


def test_truncated_history_is_an_error():
    """A parser change can truncate a history without any request failing."""
    report = check_dataset({"observations": 700}, {"observations": 1246}, _prices())
    assert not report.ok
    assert any(a["check"] == "history_truncated" for a in report.errors)


def test_a_flat_index_series_is_an_error():
    report = check_dataset({}, {}, _prices(days=FLATLINE_DAYS + 5, flat=True))
    assert not report.ok
    assert any(a["check"] == "flatline" for a in report.errors)


def test_stale_data_is_flagged():
    index = pd.bdate_range(end=pd.Timestamp.now().normalize() - pd.Timedelta(days=30), periods=40)
    stale = pd.DataFrame({"auto": range(40)}, index=index)
    report = check_dataset({}, {}, stale)
    assert any(a["check"] == "stale_data" for a in report.warnings)


def test_a_healthy_run_is_clean():
    meta = {"valid_canonical_series": 47, "etf_valid_series": 29, "observations": 1246}
    report = check_dataset(meta, meta, _prices())
    assert report.ok
    assert [a["check"] for a in report.alerts] == ["clean"]


def test_first_run_without_history_skips_regression_checks():
    report = check_dataset({"valid_canonical_series": 47}, None, _prices())
    assert report.ok
    assert any(a["check"] == "baseline" for a in report.alerts)
