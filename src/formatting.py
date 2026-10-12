"""Plain-text formatting shared by the app and the command-line tools (no Streamlit)."""

from __future__ import annotations

from datetime import datetime, timezone


def format_updated(raw: object) -> tuple[str, str]:
    """Return (absolute, relative) labels for the pipeline timestamp.

    The raw value is a microsecond ISO string, which is unreadable in a header.
    """
    text = str(raw or "")
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return (text or "unknown", "")
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    absolute = stamp.strftime("%d %b %Y · %H:%M UTC")
    hours = (datetime.now(timezone.utc) - stamp).total_seconds() / 3600.0
    if hours < 1:
        relative = "just now"
    elif hours < 24:
        relative = f"{int(hours)}h ago"
    else:
        relative = f"{int(hours // 24)}d ago"
    return absolute, relative
