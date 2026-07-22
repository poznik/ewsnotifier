"""Builders for every Telegram message the bot sends.

Pure functions: cached data + settings in, MarkdownV2 text out.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime

from notifier.agenda import build_day_layout, format_day_title
from notifier.config import Settings
from notifier.models import MailItem, Meeting
from notifier.utils import (
    contains_keyword,
    escape_markdown_v2,
    escape_markdown_v2_url,
    format_duration,
    format_local_dt,
    format_markdown_quote,
    format_minutes,
    plural_meetings,
    plural_minutes,
)

# Telegram rejects messages longer than 4096 characters; we split earlier
# to leave headroom for the closing of multi-byte sequences and entities.
MESSAGE_CHUNK_LIMIT = 4000

# Telegram's hard cap on a photo caption.
CAPTION_LIMIT = 1024

_WHITESPACE_RE = re.compile(r"\s+")


def normalize_subject(subject: str | None) -> str:
    cleaned = _WHITESPACE_RE.sub(" ", subject or "").strip()
    return cleaned or "(без темы)"


def meeting_subject(meeting: Meeting, settings: Settings) -> str:
    if settings.mask_private_meetings and meeting.is_private:
        return "Приватная встреча"
    return normalize_subject(meeting.subject)


def split_message(text: str, limit: int = MESSAGE_CHUNK_LIMIT) -> list[str]:
    """Split a message into chunks below Telegram's length limit.

    Splits on line boundaries so single-line MarkdownV2 entities stay intact;
    a single line longer than the limit is split hard.
    """
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def _hm(dt: datetime, settings: Settings) -> str:
    return format_local_dt(dt, settings.local_timezone, with_date=False)


def _reminder_lead(minutes_to: int) -> str:
    if minutes_to <= 0:
        return "Начинается сейчас"
    if minutes_to < 60:
        return f"Через {plural_minutes(minutes_to)}"
    return f"Через {format_minutes(minutes_to)}"


def _place_label(meeting: Meeting) -> str:
    """Human-readable location without the raw URL.

    "Teams <https://…>" → "Teams"; a bare join URL → "Онлайн-встреча"; the join
    link itself lives on the button, so it never appears as text here.
    """
    text = _WHITESPACE_RE.sub(" ", meeting.location or "").strip()
    if meeting.join_url:
        text = text.replace(meeting.join_url, "")
        text = _WHITESPACE_RE.sub(" ", text).strip(" <>()[]—–·|")
        return text or "Онлайн-встреча"
    return text


def build_meeting_message(
    meeting: Meeting, settings: Settings, now_utc: datetime | None = None
) -> str:
    if now_utc is None:
        now_utc = datetime.now(UTC)
    minutes_to = max(0, int((meeting.start_utc - now_utc).total_seconds() // 60))

    subject = escape_markdown_v2(meeting_subject(meeting, settings))
    span = f"{_hm(meeting.start_utc, settings)}–{_hm(meeting.end_utc, settings)}"
    duration = format_duration(meeting.start_utc, meeting.end_utc)
    timing = f"{_reminder_lead(minutes_to)} · {span} ({duration})"
    lines = [f"🔔 *{subject}*", escape_markdown_v2(timing)]

    organizer = normalize_subject(meeting.organizer) if meeting.organizer.strip() else ""
    if organizer:
        lines.append(f"👤 {escape_markdown_v2(organizer)}")
    place = _place_label(meeting)
    if place:
        label = escape_markdown_v2(place)
        # Online meetings: keep the join link in the text as a tidy inline link,
        # so it survives forwarding and can be copied — the button cannot.
        if meeting.join_url:
            label = f"[{label}]({escape_markdown_v2_url(meeting.join_url)})"
        lines.append(f"📍 {label}")
    return "\n".join(lines)


def build_mail_message(mail: MailItem, settings: Settings) -> str:
    subject_raw = normalize_subject(mail.subject)
    sender_raw = normalize_subject(mail.sender) if mail.sender.strip() else "-"
    sent_raw = format_local_dt(mail.sent_utc, settings.local_timezone, with_date=True)
    preview_raw = mail.preview or ""

    needs_mention = contains_keyword(
        f"{subject_raw}\n{sender_raw}\n{preview_raw}", settings.keywords
    )
    mention_text = settings.mention_text.strip()

    subject = escape_markdown_v2(subject_raw)
    sender = escape_markdown_v2(sender_raw)
    sent = escape_markdown_v2(sent_raw)
    preview = format_markdown_quote(preview_raw)

    if preview:
        message = f"*{subject}*\nОт: {sender}\nОтправлено: {sent}\n\n{preview}"
    else:
        message = f"*{subject}*\nОт: {sender}\nОтправлено: {sent}"
    if needs_mention:
        if mention_text:
            message = f"‼️{message}\n{escape_markdown_v2(mention_text)}"
        else:
            message = f"‼️{message}"
    return message


def build_agenda_caption(meetings: Iterable[Meeting], settings: Settings) -> str:
    """The text under the agenda picture.

    This is the part that survives as text: it lands in the push notification,
    it is searchable in the chat and a screen reader can read it. Telegram caps
    a caption at 1024 characters, so it stays a digest — the detail lives in the
    picture.
    """
    layout = build_day_layout(list(meetings), settings)
    if layout.is_empty:
        local = datetime.now(settings.local_timezone)
    else:
        local = layout.day_start_utc.astimezone(settings.local_timezone)

    lines = [f"📅 *{escape_markdown_v2(format_day_title(local))}*"]

    if layout.is_empty:
        lines.append(escape_markdown_v2("Встреч нет — день свободен"))
    else:
        summary = (
            f"{plural_meetings(len(layout.timed))} · "
            f"занято {format_minutes(layout.busy_minutes)} · "
            f"свободно {format_minutes(layout.free_minutes)}"
        )
        lines.append(escape_markdown_v2(summary))

    for overlap in layout.overlaps:
        start = format_local_dt(overlap.start_utc, settings.local_timezone, with_date=False)
        end = format_local_dt(overlap.end_utc, settings.local_timezone, with_date=False)
        detail = (
            f"Пересечение {start}–{end} ({format_minutes(overlap.minutes)}): "
            f"{meeting_subject(overlap.first, settings)} × "
            f"{meeting_subject(overlap.second, settings)}"
        )
        lines.append(f"⚠️ {escape_markdown_v2(detail)}")

    for meeting in layout.all_day:
        lines.append(f"🏖 {escape_markdown_v2('Весь день: ' + meeting_subject(meeting, settings))}")

    caption = "\n".join(lines)
    if len(caption) > CAPTION_LIMIT:
        kept: list[str] = []
        for line in lines:
            if len("\n".join([*kept, line])) > CAPTION_LIMIT:
                break
            kept.append(line)
        caption = "\n".join(kept)
    return caption


def _plural_overlaps(count: int) -> str:
    if 11 <= count % 100 <= 14:
        return f"{count} пересечений"
    last = count % 10
    if last == 1:
        return f"{count} пересечение"
    if last in (2, 3, 4):
        return f"{count} пересечения"
    return f"{count} пересечений"


def build_today_list(meetings: Iterable[Meeting], settings: Settings) -> str:
    """The day as a scannable timeline: time first, windows and clashes inline.

    Reads the same DayLayout the agenda picture does, so /today speaks the same
    visual language as the caption under the morning image.
    """
    layout = build_day_layout(list(meetings), settings)

    if layout.is_empty and not layout.all_day:
        tail = escape_markdown_v2("— встреч нет, день свободен")
        return f"📅 *{escape_markdown_v2('Сегодня')}* {tail}"

    if layout.timed:
        tail = (
            f"{plural_meetings(len(layout.timed))} · "
            f"занято {format_minutes(layout.busy_minutes)} · "
            f"свободно {format_minutes(layout.free_minutes)}"
        )
        head = f"📅 *{escape_markdown_v2('Сегодня')}* · {escape_markdown_v2(tail)}"
    else:
        head = f"📅 *{escape_markdown_v2('Сегодня')}*"
    lines = [head, ""]

    for meeting in layout.all_day:
        lines.append("🏖 " + escape_markdown_v2(f"Весь день: {meeting_subject(meeting, settings)}"))
    if layout.all_day and layout.timed:
        lines.append("")

    biggest = layout.biggest_gap
    rows: list[tuple[datetime, str]] = []
    for gap in layout.gaps:
        mark = ""
        if biggest is not None and gap.start_utc == biggest.start_utc and len(layout.gaps) > 1:
            mark = "  ← самое большое"
        span = f"{_hm(gap.start_utc, settings)}–{_hm(gap.end_utc, settings)}"
        label = f"{span} · свободно {format_minutes(gap.minutes)}{mark}"
        rows.append((gap.start_utc, "🟢 " + escape_markdown_v2(label)))
    for meeting in layout.timed:
        rng = f"{_hm(meeting.start_utc, settings)}–{_hm(meeting.end_utc, settings)}"
        clash = " ⚠️" if layout.clashes(meeting) else ""
        subject = escape_markdown_v2(meeting_subject(meeting, settings))
        rows.append((meeting.start_utc, f"*{escape_markdown_v2(rng)}*  {subject}{clash}"))
    for _, text in sorted(rows, key=lambda item: item[0]):
        lines.append(text)
    return "\n".join(lines)


def build_check_list(meetings: Iterable[Meeting], settings: Settings) -> str:
    """Overlapping meetings, each pair with the exact stretch they collide in."""
    layout = build_day_layout(list(meetings), settings)
    overlaps = layout.overlaps

    if not overlaps:
        return "✅ " + escape_markdown_v2("Пересечений нет")

    lines = [f"⚠️ *{escape_markdown_v2(_plural_overlaps(len(overlaps)))}*", ""]
    for overlap in overlaps:
        rng = f"{_hm(overlap.start_utc, settings)}–{_hm(overlap.end_utc, settings)}"
        minutes = escape_markdown_v2(f"({format_minutes(overlap.minutes)}):")
        lines.append(f"*{escape_markdown_v2(rng)}* {minutes}")
        for meeting in (overlap.first, overlap.second):
            item = (
                f"{_hm(meeting.start_utc, settings)}–{_hm(meeting.end_utc, settings)}  "
                f"{meeting_subject(meeting, settings)}"
            )
            lines.append("  • " + escape_markdown_v2(item))
        lines.append("")
    return "\n".join(lines).rstrip()
