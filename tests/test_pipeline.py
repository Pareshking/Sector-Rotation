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
