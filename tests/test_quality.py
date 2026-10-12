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


def test_stale_publication_is_an_error():
    """A timeout reports as 'cancelled' in Actions, so catch the symptom instead."""
    import datetime as dt

    from src.quantitative.quality import MAX_DATA_AGE_HOURS

    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=MAX_DATA_AGE_HOURS + 6)).isoformat()
    report = check_dataset({"last_updated_utc": old}, {}, _prices())
    assert not report.ok
    assert any(a["check"] == "stale_publication" for a in report.errors)


def test_fresh_publication_passes():
    import datetime as dt

    fresh = dt.datetime.now(dt.timezone.utc).isoformat()
    report = check_dataset({"last_updated_utc": fresh}, {}, _prices())
    assert not any(a["check"] == "stale_publication" for a in report.alerts)


def test_unparseable_timestamp_does_not_crash_the_check():
    report = check_dataset({"last_updated_utc": "not a date"}, {}, _prices())
    assert report.ok


# --------------------------------------------------------------------------- #
# Value types: what kind of return each series carries
# --------------------------------------------------------------------------- #
def _typed(benchmark: str | None = "TRI", **exposures: str) -> dict:
    meta = {"value_type_by_canonical_exposure": exposures or {"auto": "TRI", "bank": "TRI"}}
    if benchmark is not None:
        meta["benchmark_value_type"] = benchmark
    return meta


def _checks(report, severity: str) -> set[str]:
    return {a["check"] for a in report.alerts if a["severity"] == severity}


def test_a_consistent_total_return_dataset_is_clean():
    report = check_dataset(_typed(), _typed(), _prices())
    assert report.ok
    assert [a["check"] for a in report.alerts] == ["clean"]


def test_benchmark_falling_from_tri_to_close_is_an_error():
    """Nifty 50 alone switching to the price index inflates all 47 relative returns."""
    report = check_dataset(
        _typed("CLOSE", auto="CLOSE", bank="CLOSE"), _typed("TRI", auto="CLOSE", bank="CLOSE"), _prices()
    )
    assert not report.ok
    assert "benchmark_value_type_regression" in _checks(report, "error")
    assert any("TRI to CLOSE" in a["message"] for a in report.errors)


def test_benchmark_gaining_return_content_is_only_a_warning():
    report = check_dataset(_typed("TRI"), _typed("CLOSE"), _prices())
    assert "benchmark_value_type_changed" in _checks(report, "warning")
    assert "benchmark_value_type_regression" not in _checks(report, "error")


def test_an_unknown_benchmark_value_type_is_an_error():
    report = check_dataset(_typed("UNKNOWN"), _typed("TRI"), _prices())
    assert not report.ok
    assert "benchmark_value_type_unknown" in _checks(report, "error")


def test_a_price_benchmark_under_total_return_exposures_is_an_error_even_on_a_first_run():
    """No previous run is needed to know the two sides do not match."""
    report = check_dataset(_typed("CLOSE", auto="TRI", bank="CLOSE"), None, _prices())
    assert not report.ok
    mismatch = [a for a in report.errors if a["check"] == "value_type_mismatch"]
    assert mismatch and "auto" in mismatch[0]["message"] and "bank" not in mismatch[0]["message"]


def test_a_nav_exposure_against_a_price_benchmark_is_a_mismatch():
    report = check_dataset(_typed("CLOSE", auto="NAV", bank="CLOSE"), _typed("CLOSE", auto="NAV", bank="CLOSE"), _prices())
    assert "value_type_mismatch" in _checks(report, "error")


def test_exposures_below_a_total_return_benchmark_are_not_a_mismatch():
    """A price-index exposure is understated, never inflated, against a TRI benchmark."""
    report = check_dataset(_typed("TRI", auto="CLOSE", bank="NAV"), None, _prices())
    assert "value_type_mismatch" not in _checks(report, "error")


def test_an_exposure_falling_from_tri_to_close_is_an_error():
    report = check_dataset(_typed("TRI", auto="CLOSE", bank="TRI"), _typed("TRI", auto="TRI", bank="TRI"), _prices())
    assert not report.ok
    regression = [a for a in report.errors if a["check"] == "value_type_regression"]
    assert regression and "auto TRI→CLOSE" in regression[0]["message"]
    assert "bank" not in regression[0]["message"]


def test_an_exposure_falling_from_tri_to_nav_is_an_error():
    report = check_dataset(_typed("TRI", auto="NAV", bank="TRI"), _typed("TRI", auto="TRI", bank="TRI"), _prices())
    assert "value_type_regression" in _checks(report, "error")


def test_an_exposure_gaining_return_content_is_informational():
    report = check_dataset(_typed("TRI", auto="TRI", bank="TRI"), _typed("TRI", auto="CLOSE", bank="TRI"), _prices())
    assert report.ok
    assert "value_type_upgraded" in _checks(report, "info")


def test_an_exposure_new_this_run_is_not_a_regression():
    report = check_dataset(_typed("TRI", auto="TRI", bank="CLOSE"), _typed("TRI", auto="TRI"), _prices())
    assert "value_type_regression" not in _checks(report, "error")


def test_metadata_without_a_benchmark_type_is_not_judged():
    """Metadata written before the benchmark type was recorded must not fail retroactively."""
    report = check_dataset(_typed(None), _typed(None), _prices())
    assert report.ok


def test_a_value_type_regression_fails_the_strict_pipeline(monkeypatch, tmp_path):
    """--strict must turn the regression into a failed run, after the dataset is written."""
    import json

    import pipeline.run_pipeline as rp

    monkeypatch.setattr(rp, "OUTPUT", tmp_path)
    previous = {"benchmark_value_type": "TRI", "value_type_by_canonical_exposure": {}}
    (tmp_path / "metadata.json").write_text(json.dumps(previous), encoding="utf-8")

    real_fixture = rp.build_fixture

    def close_benchmark(registry):
        prices, benchmark, etfs, etf_prices, health = real_fixture(registry, days=400)
        health["benchmark_value_type"] = "CLOSE"
        health["value_type_by_canonical_exposure"] = {k: "CLOSE" for k in health["value_type_by_canonical_exposure"]}
        return prices, benchmark, etfs, etf_prices, health

    monkeypatch.setattr(rp, "build_fixture", close_benchmark)
    import pytest

    with pytest.raises(SystemExit, match="Data-quality check failed"):
        rp.run("fixture", strict=True)
    written = json.loads((tmp_path / "metadata.json").read_text(encoding="utf-8"))
    assert written["benchmark_value_type"] == "CLOSE"
    assert any(a["check"] == "benchmark_value_type_regression" for a in written["quality_alerts"])
