from __future__ import annotations

from io import StringIO

import pandas as pd
import requests

AMFI_NAV_URL = "https://portal.amfiindia.com/spages/NAVAll.txt"


def fetch_amfi_nav(
    url: str = AMFI_NAV_URL,
    timeout: int = 30,
) -> pd.DataFrame:
    response = requests.get(
        url,
        timeout=timeout,
        headers={"User-Agent": "Sector-Rotation/1.0"},
    )
    response.raise_for_status()
    rows: list[dict[str, str]] = []
    for line in StringIO(response.text):
        parts = [part.strip() for part in line.rstrip("\n").split(";")]
        if len(parts) >= 6 and parts[0].isdigit():
            rows.append(
                {
                    "scheme_code": parts[0],
                    "isin_growth": parts[1],
                    "isin_dividend": parts[2],
                    "scheme_name": parts[3],
                    "nav": parts[4],
                    "date": parts[5],
                }
            )
    frame = pd.DataFrame(rows)
    if not frame.empty:
        frame["nav"] = pd.to_numeric(frame["nav"], errors="coerce")
        dates = frame["date"].astype("string")
        frame["date"] = pd.to_datetime(
            dates,
            format="%d-%b-%Y",
            errors="coerce",
        )
        frame["date"] = frame["date"].fillna(
            pd.to_datetime(
                dates,
                format="%d-%m-%Y",
                errors="coerce",
            )
        )
    return frame
