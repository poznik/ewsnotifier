from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo


_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_MD_V2_ESCAPE_CHARS = r"_*[]()~`>#+-=|{}.!\\"
_MD_V2_ESCAPE_TABLE = str.maketrans(
    {ch: f"\\{ch}" for ch in _MD_V2_ESCAPE_CHARS}
)


def extract_url(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    match = _URL_RE.search(text)
    return match.group(0) if match else None


def format_local_dt(dt_utc: datetime, tz: ZoneInfo, with_date: bool = True) -> str:
    local_dt = dt_utc.astimezone(tz)
    if with_date:
        return local_dt.strftime("%Y-%m-%d %H:%M")
    return local_dt.strftime("%H:%M")


def format_duration(start_utc: datetime, end_utc: datetime) -> str:
    delta = end_utc - start_utc
    if delta.total_seconds() < 0:
        delta = timedelta(0)
    total_minutes = int(delta.total_seconds() // 60)
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours}:{minutes:02d}"


def build_preview(text: str, max_chars: int = 200, max_lines: int = 2) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    preview_lines = lines[:max_lines]
    preview = "\n".join(preview_lines)
    if len(preview) > max_chars:
        preview = preview[:max_chars].rstrip()
    return preview


def escape_markdown_v2(text: str) -> str:
    return text.translate(_MD_V2_ESCAPE_TABLE)


def format_markdown_quote(text: str) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    if not lines:
        return ""
    escaped_lines = [escape_markdown_v2(line) for line in lines]
    return "\n".join(f"> {line}" for line in escaped_lines)


def contains_keyword(text: str, keywords: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(keyword.lower() in lowered for keyword in keywords)
