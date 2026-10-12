"""Fill authoritative dates into data/universe/universe.json.

Run by hand and review the diff like code; the nightly pipeline never runs it.
The dates decide what the strategy may hold and which history is real, so they
are metadata with a source, not numbers re-derived from whatever a night's
download returned.

* Index ``launch_date`` / ``base_date`` — read from the NSE Indices factsheet
  for the exact index (``https://www.niftyindices.com/reports/index-factsheet``
  lists one PDF per index). History before ``launch_date`` is back-calculated.
* Vehicle ``inception_date`` — the first published NAV in AMFI's record for
  the scheme code, via MFAPI. A fund cannot be bought before it has a NAV.

A date that cannot be parsed is left empty and reported, never guessed.

    python tools/refresh_universe_dates.py            # update universe.json
    python tools/refresh_universe_dates.py --dry-run  # report only
"""

from __future__ import annotations

import argparse
import html
import io
import json
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE = ROOT / "data" / "universe" / "universe.json"
METADATA = ROOT / "data" / "processed" / "metadata.json"
LISTING = "https://www.niftyindices.com/reports/index-factsheet"
MFAPI = "https://api.mfapi.in/mf/{code}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/134.0 Safari/537.36"
}
DATE_PATTERNS = (
    (r"[A-Z][a-z]+ \d{1,2}, \d{4}", "%B %d, %Y"),
    (r"\d{1,2}-[A-Z][a-z]{2}-\d{4}", "%d-%b-%Y"),
    (r"\d{1,2} [A-Z][a-z]+ \d{4}", "%d %B %Y"),
)


def _get(url: str, attempts: int = 5) -> requests.Response:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            response = requests.get(url, headers=HEADERS, timeout=60)
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower().replace("&", "and"))


def factsheet_links() -> dict[str, str]:
    """Normalised index name -> factsheet PDF URL, from the NSE Indices listing."""
    page = _get(LISTING).text
    links: dict[str, str] = {}
    for href, label in re.findall(r'<a[^>]+href="([^"]+\.pdf)"[^>]*>(.*?)</a>', page, re.I | re.S):
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", label))).strip()
        if text:
            url = href if href.startswith("http") else "https:" + href if href.startswith("//") else "https://www.niftyindices.com" + href
            links.setdefault(_norm(text), url)
    return links


def _parse_date(text: str) -> date | None:
    for pattern, fmt in DATE_PATTERNS:
        match = re.search(pattern, text)
        if match:
            try:
                return datetime.strptime(match.group(0), fmt).date()
            except ValueError:
                continue
    return None


def factsheet_dates(url: str) -> tuple[date | None, date | None]:
    """(launch_date, base_date) from the factsheet's layout text."""
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(_get(url).content))
    launch = base = None
    for page in reader.pages[:2]:
        for line in page.extract_text(extraction_mode="layout").splitlines():
            stripped = line.strip()
            if launch is None and stripped.startswith("Launch Date"):
                launch = _parse_date(stripped[len("Launch Date"):])
            if base is None and stripped.startswith("Base Date"):
                base = _parse_date(stripped[len("Base Date"):])
        if launch and base:
            break
    return launch, base


def first_nav_date(code: int) -> date | None:
    rows = _get(MFAPI.format(code=code)).json().get("data") or []
    dates = [datetime.strptime(r["date"], "%d-%m-%Y").date() for r in rows if r.get("date")]
    return min(dates) if dates else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    raw = UNIVERSE.read_text(encoding="utf-8")
    universe = json.loads(raw)
    resolved = {}
    if METADATA.exists():
        resolved = json.loads(METADATA.read_text(encoding="utf-8")).get("resolved_official_index_names", {})
    today = date.today().isoformat()
    links = factsheet_links()
    problems: list[str] = []

    for exposure in universe["exposures"]:
        names = [exposure["benchmark"], resolved.get(exposure["id"], "")]
        url = next((links[_norm(n)] for n in names if n and _norm(n) in links), None)
        if url is None:
            problems.append(f"{exposure['id']}: no factsheet matches {names}")
        else:
            launch, base = factsheet_dates(url)
            if launch is None or base is None:
                problems.append(f"{exposure['id']}: could not read launch/base date from {url}")
            if launch:
                exposure["launch_date"] = launch.isoformat()
            if base:
                exposure["base_date"] = base.isoformat()
            if launch or base:
                exposure["dates_source"] = f"NSE Indices factsheet {url} (retrieved {today})"
            print(f"{exposure['id']:28s} launch {launch}  base {base}")
        for vehicle in exposure.get("etfs", []):
            code = vehicle.get("scheme_code")
            if not code:
                problems.append(f"{exposure['id']}/{vehicle.get('name')}: no scheme code")
                continue
            inception = first_nav_date(int(code))
            if inception is None:
                problems.append(f"{exposure['id']}/{vehicle.get('name')}: MFAPI returned no NAV history")
                continue
            vehicle["inception_date"] = inception.isoformat()
            vehicle["inception_source"] = (
                f"First published NAV in AMFI's record for scheme {code}, via MFAPI (retrieved {today})"
            )

    print(f"\n{len(problems)} problem(s)")
    for line in problems:
        print("  -", line)
    if not args.dry_run:
        UNIVERSE.write_text(json.dumps(universe, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote {UNIVERSE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
