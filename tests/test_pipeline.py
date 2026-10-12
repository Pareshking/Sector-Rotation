from __future__ import annotations

from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "data_pipeline.yml"


def test_production_workflow_runs_the_pipeline_strict():
    """A quality error must stop the run, not just get logged into metadata.json.

    run_pipeline.py only raises on an error-level alert when --strict is passed;
    the flag defaulting to off is invisible from inside the module itself, so
    the thing that actually needs pinning down is the production workflow's
    own invocation.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    line = next(line for line in text.splitlines() if "pipeline.run_pipeline --mode live" in line)
    assert "--strict" in line


def test_the_pipeline_imports_the_jugaad_patches_module():
    """jugaad-data's HTTP layer issues requests with no read timeout and chunks
    date ranges three times wider than NSE's own response cap allows — see
    src/data/_jugaad_patches.py, which fixes both. Importing the production
    entrypoint must pull that module in transitively (via etf_data/nse_equity
    and index_data/jugaad_indices) so the fix is never accidentally dropped
    from the import chain. The patches' own effects are exercised directly in
    test_jugaad_patches.py.
    """
    import sys

    import pipeline.run_pipeline  # noqa: F401

    assert "src.data._jugaad_patches" in sys.modules


def _panel(days: int = 30):
    import numpy as np
    import pandas as pd

    index = pd.bdate_range("2026-01-01", periods=days)
    prices = pd.DataFrame({"auto": np.linspace(100, 130, days), "bank": np.linspace(50, 40, days)}, index=index)
    benchmark = pd.Series(np.linspace(1000, 1100, days), index=index)
    return prices, benchmark


def test_clean_price_inputs_pass_validation():
    from pipeline.run_pipeline import price_input_problems

    assert price_input_problems(*_panel()) == []


def test_a_non_positive_index_level_is_caught_before_ranking():
    from pipeline.run_pipeline import price_input_problems

    prices, benchmark = _panel()
    prices.iloc[10, 0] = 0.0
    problems = price_input_problems(prices, benchmark)
    assert any("canonical index panel" in p and "non-positive" in p for p in problems)
    assert any("infinite" in p for p in problems)


def test_a_duplicated_date_is_caught_before_ranking():
    import pandas as pd

    from pipeline.run_pipeline import price_input_problems

    prices, benchmark = _panel()
    prices = pd.concat([prices, prices.iloc[[-1]]])
    assert any("duplicate dates" in p for p in price_input_problems(prices, benchmark))


def test_a_bad_benchmark_is_caught_before_ranking():
    from pipeline.run_pipeline import price_input_problems

    prices, benchmark = _panel()
    benchmark.iloc[5] = -1.0
    assert any(p.startswith("benchmark:") for p in price_input_problems(prices, benchmark))


def test_invalid_prices_stop_the_run_before_anything_is_written(monkeypatch, tmp_path):
    import pytest

    import pipeline.run_pipeline as rp

    monkeypatch.setattr(rp, "OUTPUT", tmp_path)
    real_fixture = rp.build_fixture

    def broken(registry):
        prices, benchmark, etfs, etf_prices, health = real_fixture(registry, days=400)
        prices.iloc[100, 0] = -5.0
        return prices, benchmark, etfs, etf_prices, health

    monkeypatch.setattr(rp, "build_fixture", broken)
    with pytest.raises(ValueError, match="Price validation failed before ranking"):
        rp.run("fixture")
    assert not any(tmp_path.iterdir())


def test_the_live_build_records_the_benchmark_value_type_and_uses_its_calendar(monkeypatch):
    """The benchmark's own value type reaches metadata; it is never assumed to be TRI."""
    import pandas as pd

    import pipeline.run_pipeline as rp
    from src.universe.registry import UniverseRegistry

    registry = UniverseRegistry.from_json(rp.UNIVERSE_PATH)
    index = pd.bdate_range("2025-01-01", periods=300)
    benchmark = pd.Series(range(1, 301), index=index, dtype=float)
    benchmark.attrs.update(source="niftyindices_jugaad", value_type="CLOSE")
    seen = {}

    def canonical(names, years, etf_histories, canonical_etf_keys, calendar):
        seen["calendar"] = calendar
        frame = pd.DataFrame({"auto": benchmark.to_numpy()}, index=index)
        frame.attrs.update(
            source_by_exposure={"auto": "niftyindices_jugaad"},
            resolved_name_by_exposure={"auto": "NIFTY AUTO"},
            value_type_by_exposure={"auto": "TRI"},
            fetch_errors={"bank": "TRI: Timeout: slow"},
        )
        return frame

    monkeypatch.setattr(rp, "fetch_etf_histories", lambda etfs, years: (pd.DataFrame(), {}, {}))
    monkeypatch.setattr(rp, "download_benchmark", lambda name, years: benchmark)
    monkeypatch.setattr(rp, "download_canonical_indices", canonical)
    _, _, _, _, health = rp.build_live(registry)
    assert health["benchmark_value_type"] == "CLOSE"
    assert health["benchmark_source"] == "niftyindices_jugaad"
    assert health["canonical_fetch_errors"] == {"bank": "TRI: Timeout: slow"}
    assert seen["calendar"].equals(index)


def test_an_unreachable_benchmark_reports_why(monkeypatch):
    import pandas as pd
    import pytest

    import pipeline.run_pipeline as rp
    from src.universe.registry import UniverseRegistry

    empty = pd.Series(dtype=float)
    empty.attrs["errors"] = ["TRI: ConnectionError: down", "CLOSE: ConnectionError: down"]
    monkeypatch.setattr(rp, "fetch_etf_histories", lambda etfs, years: (pd.DataFrame(), {}, {}))
    monkeypatch.setattr(rp, "download_benchmark", lambda name, years: empty)
    with pytest.raises(RuntimeError, match="ConnectionError: down"):
        rp.build_live(UniverseRegistry.from_json(rp.UNIVERSE_PATH))
