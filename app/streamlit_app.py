"""App shell: page config, the Paresh stylesheet, navigation and the header every page shares.

Run with ``streamlit run app/streamlit_app.py``. Each page in ``app/views`` is a
read-only consumer of the published artifacts (``data/processed``,
``data/universe/universe.json``) through ``app/data.py``; nothing here computes
a decision of its own.

The look is the Paresh app's, from its own code (``app/kit``): the stylesheet,
the header with page links and a dated status pill, and the market strip.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _drop_stale_modules() -> None:
    """Re-import app/ and src/ after a deploy changed them.

    Streamlit Cloud pulls each push into the running server and reruns the
    page scripts, but modules they import stay as first loaded: a change to
    the kit's stylesheet or to src/ did not reach the live site until a
    reboot. When any .py file under app/ or src/ has changed since the last
    run, those modules are dropped so this run imports them fresh.
    """
    stamp = sum(p.stat().st_mtime_ns for folder in ("app", "src") for p in (ROOT / folder).rglob("*.py"))
    previous = getattr(sys, "_sector_rotation_code_stamp", None)
    sys._sector_rotation_code_stamp = stamp
    if previous is not None and previous != stamp:
        for name in [n for n in sys.modules if n == "app" or n.startswith(("app.", "src.")) or n == "src"]:
            del sys.modules[name]


_drop_stale_modules()

st.set_page_config(
    page_title="Dual Momentum",
    page_icon=":material/donut_small:",
    layout="wide",
    initial_sidebar_state="collapsed",
)

from app.components.navigation import GROUPS, PAGES  # noqa: E402
from app.components.theme import inject_theme  # noqa: E402
from app.data import market_state  # noqa: E402
from app.kit.header import render_header  # noqa: E402
from app.kit.theme import inject_custom_css  # noqa: E402

# Deliberately not "pages/": Streamlit auto-discovers that directory name and
# builds a second, filename-derived sidebar nav alongside the explicit one below.
VIEWS_DIR = ROOT / "app" / "views"

# ``url_path`` is set explicitly so page URLs stay stable when files are renamed.
pages = [
    st.Page(VIEWS_DIR / page.file, title=page.title, icon=page.icon, url_path=page.url_path, default=page.default)
    for page in PAGES
]
# Hidden: the header below draws the links, as the Paresh app's does.
current = st.navigation(pages, position="hidden")

# This app's own primitives first, then the Paresh stylesheet, whose global
# rules (page, header, widgets) win.
inject_theme()
inject_custom_css()
render_header(market_state(), pages, current, GROUPS)
current.run()
