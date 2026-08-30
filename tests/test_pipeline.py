from __future__ import annotations

import socket


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
