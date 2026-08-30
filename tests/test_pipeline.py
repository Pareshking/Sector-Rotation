from __future__ import annotations

import socket
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


def test_importing_the_pipeline_sets_a_socket_timeout():
    """jugaad-data's HTTP layer issues requests with no read timeout, so a single
    stalled NSE response hangs its thread forever and drags the whole run past
    the CI budget with nothing committed. Importing the pipeline must install a
    process-wide default so that failure mode cannot come back silently.
    """
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(None)
    try:
        import pipeline.run_pipeline  # noqa: F401
        import importlib

        importlib.reload(pipeline.run_pipeline)
        assert socket.getdefaulttimeout() is not None
        assert 0 < socket.getdefaulttimeout() <= 60
    finally:
        socket.setdefaulttimeout(previous)
