from __future__ import annotations

import html
import re
from collections.abc import Iterable
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
_TEXT_URL_RE = re.compile(r"\[https?://[^\]]+\]|https?://\S+", re.IGNORECASE)
_HTML_LINEBREAK_RE = re.compile(r"(?is)<br\s*/?>|</p\s*>")
_HTML_TAG_RE = re.compile(r"(?is)<[^>]+>")
_CID_RE = re.compile(r"\[cid:[^\]]+\]|cid:[\w.@-]+", re.IGNORECASE)
_NOISE_LINE_RE = re.compile(r"^\[?(cid|image|img):", re.IGNORECASE)
_MD_V2_ESCAPE_CHARS = r"_*[]()~`>#+-=|{}.!\\"
_MD_V2_ESCAPE_TABLE = str.maketrans({ch: f"\\{ch}" for ch in _MD_V2_ESCAPE_CHARS})
# Punctuation that commonly wraps a URL in calendar locations ("<https://…>",
# "(https://…)") but is never part of the URL itself.
_URL_TRAILING_CHARS = ">)]}.,;:!?'\"»…"


def extract_url(text: str | None) -> str | None:
    if not text:
        return None
    match = _URL_RE.search(text)
    if not match:
        return None
    url = match.group(0).rstrip(_URL_TRAILING_CHARS)
    return url or None


def format_local_dt(dt_utc: datetime, tz: ZoneInfo, with_date: bool = True) -> str:
    local_dt = dt_utc.astimezone(tz)
    if with_date:
        return local_dt.strftime("%Y-%m-%d %H:%M")
    return local_dt.strftime("%H:%M")


def format_minutes(total_minutes: int) -> str:
    hours, minutes = divmod(max(0, total_minutes), 60)
    if hours and minutes:
        return f"{hours} ч {minutes} мин"
    if hours:
        return f"{hours} ч"
    return f"{minutes} мин"


def format_duration(start_utc: datetime, end_utc: datetime) -> str:
    delta = end_utc - start_utc
    if delta.total_seconds() < 0:
        delta = timedelta(0)
    return format_minutes(int(delta.total_seconds() // 60))


def plural_meetings(count: int) -> str:
    """Russian noun agreement: 1 встреча, 2 встречи, 5 встреч."""
    if 11 <= count % 100 <= 14:
        return f"{count} встреч"
    last = count % 10
    if last == 1:
        return f"{count} встреча"
    if last in (2, 3, 4):
        return f"{count} встречи"
    return f"{count} встреч"


def plural_minutes(count: int) -> str:
    """Accusative case for "через N минут": 1 минуту, 2 минуты, 5 минут."""
    if 11 <= count % 100 <= 14:
        return f"{count} минут"
    last = count % 10
    if last == 1:
        return f"{count} минуту"
    if last in (2, 3, 4):
        return f"{count} минуты"
    return f"{count} минут"


def _clean_mail_text(text: str) -> str:
    cleaned = text.replace("\xa0", " ")
    if "<" in cleaned and ">" in cleaned:
        cleaned = _HTML_LINEBREAK_RE.sub("\n", cleaned)
        cleaned = _HTML_TAG_RE.sub(" ", cleaned)
        cleaned = html.unescape(cleaned)
    cleaned = _TEXT_URL_RE.sub(" ", cleaned)
    cleaned = _CID_RE.sub(" ", cleaned)
    return cleaned


def build_preview(text: str, max_chars: int = 200, max_lines: int = 2) -> str:
    cleaned = _clean_mail_text(text)
    lines = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _NOISE_LINE_RE.match(stripped):
            continue
        lines.append(stripped)
        if len(lines) >= max_lines:
            break
    preview_lines = lines[:max_lines]
    preview = "\n".join(preview_lines)
    if len(preview) > max_chars:
        preview = preview[:max_chars].rstrip()
    return preview


def escape_markdown_v2(text: str) -> str:
    return text.translate(_MD_V2_ESCAPE_TABLE)


def escape_markdown_v2_url(url: str) -> str:
    """Escape a URL for the ``(...)`` part of a MarkdownV2 inline link.

    Only ``)`` and ``\\`` are special there — running a URL through the full
    ``escape_markdown_v2`` would escape ``.``/``-``/``_`` and break the link.
    """
    return url.replace("\\", "\\\\").replace(")", "\\)")


def format_markdown_quote(text: str) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    if not lines:
        return ""
    escaped_lines = [escape_markdown_v2(line) for line in lines]
    return "\n".join(f"> {line}" for line in escaped_lines)


def contains_keyword(text: str, keywords: Iterable[str]) -> bool:
    for keyword in keywords:
        stripped = keyword.strip()
        if not stripped:
            continue
        # Match whole words/phrases only: "ok" must not fire on "broken".
        pattern = r"(?<!\w)" + re.escape(stripped) + r"(?!\w)"
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False
