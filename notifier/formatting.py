"""Builders for every Telegram message the bot sends.

Pure functions: cached data + settings in, MarkdownV2 text out.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime

from notifier.config import Settings
from notifier.models import MailItem, Meeting
from notifier.utils import (
    contains_keyword,
    escape_markdown_v2,
    format_duration,
    format_local_dt,
    format_markdown_quote,
)

# Telegram rejects messages longer than 4096 characters; we split earlier
# to leave headroom for the closing of multi-byte sequences and entities.
MESSAGE_CHUNK_LIMIT = 4000

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


def build_meeting_message(
    meeting: Meeting, settings: Settings, now_utc: datetime | None = None
) -> str:
    if now_utc is None:
        now_utc = datetime.now(UTC)
    minutes_to = max(0, int((meeting.start_utc - now_utc).total_seconds() // 60))

    subject = escape_markdown_v2(meeting_subject(meeting, settings))
    organizer_raw = normalize_subject(meeting.organizer) if meeting.organizer.strip() else "-"
    organizer = escape_markdown_v2(organizer_raw)
    start_local_dt = meeting.start_utc.astimezone(settings.local_timezone)
    start_local = escape_markdown_v2(start_local_dt.strftime("%d.%m.%Y %H:%M"))
    duration = escape_markdown_v2(format_duration(meeting.start_utc, meeting.end_utc))
    header = f"🔔 Через {minutes_to} мин: {subject}"
    lines = [
        f"*{header}*",
        f"Организатор: *{organizer}*",
        f"Начало: {start_local}",
        f"Длительность: {duration}",
    ]
    location_value = (meeting.location or "").strip()
    if meeting.join_url:
        lines.append(f"Ссылка: {escape_markdown_v2(meeting.join_url)}")
    elif location_value:
        lines.append(f"Место: {escape_markdown_v2(normalize_subject(location_value))}")
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


def _window_line(start_utc: datetime, end_utc: datetime, settings: Settings) -> str:
    window_start = format_local_dt(start_utc, settings.local_timezone, with_date=False)
    window_duration = format_duration(start_utc, end_utc)
    window_rest = f": начало {window_start}, длительность {window_duration}"
    return f"> *Окно*{escape_markdown_v2(window_rest)}"


def build_today_list(meetings: Iterable[Meeting], settings: Settings) -> str:
    today_local = datetime.now(settings.local_timezone)
    header = f"*Сегодня {escape_markdown_v2(today_local.strftime('%d.%m.%Y'))}*"
    lines = [header, ""]

    all_day = sorted(
        (m for m in meetings if m.is_all_day),
        key=lambda item: meeting_subject(item, settings),
    )
    timed = sorted(
        (m for m in meetings if not m.is_all_day),
        key=lambda item: item.start_utc,
    )

    if not all_day and not timed:
        lines.append(escape_markdown_v2("Встреч нет"))
        return "\n".join(lines)

    for meeting in all_day:
        lines.append(escape_markdown_v2(f"◦ Весь день: {meeting_subject(meeting, settings)}"))

    if timed:
        first_local = timed[0].start_utc.astimezone(settings.local_timezone)
        workday_start = first_local.replace(
            hour=settings.workday_start.hour,
            minute=settings.workday_start.minute,
            second=0,
            microsecond=0,
        )
        if workday_start < first_local:
            lines.append(
                _window_line(
                    workday_start.astimezone(UTC),
                    timed[0].start_utc,
                    settings,
                )
            )
    for index, meeting in enumerate(timed):
        subject = meeting_subject(meeting, settings)
        start = format_local_dt(meeting.start_utc, settings.local_timezone, with_date=False)
        duration = format_duration(meeting.start_utc, meeting.end_utc)
        lines.append(escape_markdown_v2(f"‣{subject}, {start}, {duration}"))
        if index < len(timed) - 1:
            next_meeting = timed[index + 1]
            if meeting.end_utc < next_meeting.start_utc:
                lines.append(_window_line(meeting.end_utc, next_meeting.start_utc, settings))
    return "\n".join(lines)


def _overlap_minutes(group: list[Meeting]) -> int:
    events: list[tuple[datetime, int]] = []
    for meeting in group:
        if meeting.end_utc <= meeting.start_utc:
            continue
        events.append((meeting.start_utc, 1))
        events.append((meeting.end_utc, -1))
    events.sort(key=lambda item: (item[0], item[1]))

    active = 0
    last_time: datetime | None = None
    overlap_seconds = 0.0
    for moment, delta in events:
        if last_time is not None and active >= 2:
            overlap_seconds += (moment - last_time).total_seconds()
        active += delta
        last_time = moment
    return max(0, int(overlap_seconds // 60))


def find_overlaps(meetings: Iterable[Meeting]) -> list[list[Meeting]]:
    """Group timed meetings into clusters that overlap in time.

    All-day events are ignored: they would trivially "overlap" the whole
    day (audit finding C1).
    """
    timed = sorted(
        (m for m in meetings if not m.is_all_day),
        key=lambda item: item.start_utc,
    )
    overlaps: list[list[Meeting]] = []
    current_group: list[Meeting] = []
    current_end: datetime | None = None

    for meeting in timed:
        if not current_group:
            current_group = [meeting]
            current_end = meeting.end_utc
            continue
        if current_end is not None and meeting.start_utc < current_end:
            current_group.append(meeting)
            if meeting.end_utc > current_end:
                current_end = meeting.end_utc
        else:
            if len(current_group) > 1:
                overlaps.append(current_group)
            current_group = [meeting]
            current_end = meeting.end_utc

    if len(current_group) > 1:
        overlaps.append(current_group)
    return overlaps


def build_check_list(meetings: Iterable[Meeting], settings: Settings) -> str:
    overlaps = find_overlaps(meetings)

    header = escape_markdown_v2(f"Всего пересечений: {len(overlaps)}\n")
    lines = [header]

    for index, group in enumerate(overlaps, start=1):
        title = escape_markdown_v2(f"Пересечение {index}:")
        minutes_text = escape_markdown_v2(f"{_overlap_minutes(group)} мин")
        lines.append(f"*{title}* {minutes_text}")
        for meeting in group:
            subject = meeting_subject(meeting, settings)
            start = format_local_dt(meeting.start_utc, settings.local_timezone, with_date=False)
            duration = format_duration(meeting.start_utc, meeting.end_utc)
            lines.append(escape_markdown_v2(f"{subject}, {start}, {duration}"))
        if index < len(overlaps):
            lines.append("")

    return "\n".join(lines)
