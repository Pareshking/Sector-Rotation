"""The app's seven pages: one definition for the page list, the routes and the phone nav.

``app/streamlit_app.py`` builds ``st.navigation`` from ``PAGES`` and renders
``mobile_nav`` from the same list, so the two can never disagree about what
exists or where it lives.
"""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from app.components.theme import _esc


@dataclass(frozen=True)
class PageSpec:
    file: str
    title: str
    url_path: str
    icon: str | None
    default: bool = False


# The Screener is the home page, as it is in the Paresh app (owner, 12 Oct 2026).
PAGES: tuple[PageSpec, ...] = (
    PageSpec("2_Rankings.py", "Screener", "Screener", None, default=True),
    PageSpec("1_Portfolio.py", "Portfolio", "Portfolio", None),
    PageSpec("7_Actions.py", "Actions", "Actions", None),
    PageSpec("4_Exposure.py", "Exposure", "Exposure", None),
    PageSpec("3_Evidence.py", "Evidence", "Evidence", None),
    PageSpec("5_Data_Health.py", "Data Health", "Data_Health", None),
    PageSpec("6_Method.py", "Method", "Method", None),
)

# The ☰ menu's sections on a phone, by index into PAGES.
GROUPS = {"Research": [0, 1, 2, 3], "Monitoring": [4, 5], "System": [6]}

# The default page is served at the root. Streamlit does not route a default
# page's url_path, so linking to "/Portfolio" would answer "Page not found".
HOME_PATH = next(page.url_path for page in PAGES if page.default)


def nav_href(path: str) -> str:
    return "/" if path == HOME_PATH else f"/{path}"


def mobile_nav(active: str = "") -> None:
    """Horizontal, scrollable page bar for narrow screens.

    Streamlit hides its own top navigation below ~768px, so without this every
    page sits two taps deep behind a chevron on a phone.
    """
    links = "".join(
        f'<a class="{"on" if page.url_path == active else ""}" href="{nav_href(page.url_path)}" '
        f'target="_self">{_esc(page.title)}</a>'
        for page in PAGES
    )
    st.markdown(f'<nav class="ds-mnav">{links}</nav>', unsafe_allow_html=True)
