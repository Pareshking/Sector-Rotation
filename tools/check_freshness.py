"""Independent freshness watchdog for the currently published dataset.

quality.py's own staleness check cannot do this job: it stamps
``last_updated_utc`` with the current time and then checks that same run's
metadata, so it always compares "now" to "now" and can never fire — and if
the pipeline fails to run at all, nothing calls it either way. This script
is the actual mechanism: it reads whatever is already committed in the repo
and reports how old it is, on its own schedule, regardless of whether the
data pipeline ran, succeeded, or was cancelled.

Deliberately stdlib-only. If the pipeline's own dependencies ever break, this
must still be able to run and report the truth rather than fail alongside it.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Keep in sync with src/quantitative/quality.MAX_DATA_AGE_HOURS. Duplicated
# rather than imported so this watchdog has no dependency on that module (or
# on pandas, which it pulls in) ever loading successfully.
MAX_DATA_AGE_HOURS = 36

METADATA_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / "metadata.json"


def check(metadata_path: Path = METADATA_PATH) -> tuple[bool, str]:
    if not metadata_path.exists():
        return False, f"No dataset has ever been published: {metadata_path} does not exist."
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"{metadata_path} is not valid JSON: {exc}"

    stamp = metadata.get("last_updated_utc")
    if not stamp:
        return False, f"{metadata_path} has no last_updated_utc field."
    try:
        published = datetime.fromisoformat(str(stamp))
    except ValueError:
        return False, f"last_updated_utc {stamp!r} is not a parseable timestamp."
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)

    hours = (datetime.now(timezone.utc) - published).total_seconds() / 3600.0
    if hours > MAX_DATA_AGE_HOURS:
        return False, (
            f"Published dataset is {hours:.1f} hours old, past the {MAX_DATA_AGE_HOURS}-hour "
            "limit. The scheduled data pipeline is not completing — check whether it timed out "
            "(Actions reports a timeout as 'cancelled', not 'failed', so it can look unremarkable "
            "in the run list)."
        )
    return True, f"Published dataset is {hours:.1f} hours old (limit {MAX_DATA_AGE_HOURS}h). OK."


if __name__ == "__main__":
    ok, message = check()
    print(message)
    sys.exit(0 if ok else 1)
