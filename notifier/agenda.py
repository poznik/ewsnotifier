"""Day layout for the morning agenda: free windows, overlaps, calendar lanes.

Pure computation, no rendering and no Telegram: the image renderer and the
caption builder both read the same layout, so the picture and the text under
it can never describe different days.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from notifier.config import Settings
from notifier.models import Meeting

# A dash between two meetings is not a free window; below this it is noise.
MIN_GAP_MINUTES = 20

WEEKDAYS = (
    "Понедельник",
    "Вторник",
    "Среда",
    "Четверг",
    "Пятница",
    "Суббота",
    "Воскресенье",
)
MONTHS = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def format_day_title(local: datetime) -> str:
    """«Вторник, 14 июля» — the heading shared by the picture and its caption."""
    return f"{WEEKDAYS[local.weekday()]}, {local.day} {MONTHS[local.month - 1]}"


@dataclass(frozen=True)
class Gap:
    """A stretch of the workday with no meeting in it."""

    start_utc: datetime
    end_utc: datetime

    @property
    def minutes(self) -> int:
        return max(0, int((self.end_utc - self.start_utc).total_seconds() // 60))


@dataclass(frozen=True)
class Overlap:
    """Two meetings that share time, and the stretch they share."""

    first: Meeting
    second: Meeting
    start_utc: datetime
    end_utc: datetime

    @property
    def minutes(self) -> int:
        return max(0, int((self.end_utc - self.start_utc).total_seconds() // 60))


@dataclass(frozen=True)
class DayLayout:
    """Everything the agenda needs to know about one day."""

    day_start_utc: datetime
    day_end_utc: datetime
    timed: list[Meeting]
    all_day: list[Meeting]
    gaps: list[Gap]
    overlaps: list[Overlap]
    lanes: dict[str, int]
    lane_count: int
    busy_minutes: int
    free_minutes: int

    @property
    def is_empty(self) -> bool:
        """No timed meetings: there is no calendar to draw."""
        return not self.timed

    @property
    def biggest_gap(self) -> Gap | None:
        if not self.gaps:
            return None
        return max(self.gaps, key=lambda gap: gap.minutes)

    def clashes(self, meeting: Meeting) -> bool:
        return any(
            overlap.first.id == meeting.id or overlap.second.id == meeting.id
            for overlap in self.overlaps
        )

    def lane_span(self, meeting: Meeting) -> int:
        """How many lanes the block may occupy: it widens right while empty.

        A meeting alone in its stretch of the day fills the whole width, the
        way Outlook and Google Calendar draw it.
        """
        span = 1
        for lane in range(self.lanes[meeting.id] + 1, self.lane_count):
            taken = any(
                other.id != meeting.id
                and self.lanes[other.id] == lane
                and _intersects(other, meeting)
                for other in self.timed
            )
            if taken:
                break
            span += 1
        return span


def _intersects(a: Meeting, b: Meeting) -> bool:
    return a.start_utc < b.end_utc and b.start_utc < a.end_utc


def _busy_minutes(timed: list[Meeting]) -> int:
    """Occupied time, counting overlapping meetings once."""
    merged: list[list[datetime]] = []
    for meeting in timed:
        if merged and meeting.start_utc <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], meeting.end_utc)
        else:
            merged.append([meeting.start_utc, meeting.end_utc])
    return int(sum((end - start).total_seconds() for start, end in merged) // 60)


def _free_gaps(timed: list[Meeting], day_start_utc: datetime) -> list[Gap]:
    gaps: list[Gap] = []
    cursor = day_start_utc
    for meeting in timed:
        if meeting.start_utc > cursor:
            gaps.append(Gap(cursor, meeting.start_utc))
        cursor = max(cursor, meeting.end_utc)
    return [gap for gap in gaps if gap.minutes >= MIN_GAP_MINUTES]


def _overlaps(timed: list[Meeting]) -> list[Overlap]:
    overlaps: list[Overlap] = []
    for index, first in enumerate(timed):
        for second in timed[index + 1 :]:
            if not _intersects(first, second):
                continue
            overlaps.append(
                Overlap(
                    first=first,
                    second=second,
                    start_utc=max(first.start_utc, second.start_utc),
                    end_utc=min(first.end_utc, second.end_utc),
                )
            )
    return overlaps


def _assign_lanes(timed: list[Meeting]) -> tuple[dict[str, int], int]:
    """Greedy calendar packing: first lane that is free when the meeting starts."""
    lane_end: list[datetime] = []
    lanes: dict[str, int] = {}
    for meeting in timed:
        for lane, end in enumerate(lane_end):
            if meeting.start_utc >= end:
                lanes[meeting.id] = lane
                lane_end[lane] = meeting.end_utc
                break
        else:
            lanes[meeting.id] = len(lane_end)
            lane_end.append(meeting.end_utc)
    return lanes, max(1, len(lane_end))


def _day_start(first: Meeting, settings: Settings) -> datetime:
    """Workday start, or the first meeting if the day begins even earlier."""
    first_local = first.start_utc.astimezone(settings.local_timezone)
    workday_start = first_local.replace(
        hour=settings.workday_start.hour,
        minute=settings.workday_start.minute,
        second=0,
        microsecond=0,
    )
    return min(workday_start.astimezone(UTC), first.start_utc)


def build_day_layout(meetings: list[Meeting], settings: Settings) -> DayLayout:
    timed = sorted(
        (m for m in meetings if not m.is_all_day and m.end_utc > m.start_utc),
        key=lambda m: m.start_utc,
    )
    all_day = sorted((m for m in meetings if m.is_all_day), key=lambda m: m.subject)

    if not timed:
        now = datetime.now(UTC)
        return DayLayout(
            day_start_utc=now,
            day_end_utc=now,
            timed=[],
            all_day=all_day,
            gaps=[],
            overlaps=[],
            lanes={},
            lane_count=1,
            busy_minutes=0,
            free_minutes=0,
        )

    day_start_utc = _day_start(timed[0], settings)
    day_end_utc = max(m.end_utc for m in timed)
    gaps = _free_gaps(timed, day_start_utc)
    lanes, lane_count = _assign_lanes(timed)
    busy = _busy_minutes(timed)
    span_minutes = int((day_end_utc - day_start_utc).total_seconds() // 60)

    return DayLayout(
        day_start_utc=day_start_utc,
        day_end_utc=day_end_utc,
        timed=timed,
        all_day=all_day,
        gaps=gaps,
        overlaps=_overlaps(timed),
        lanes=lanes,
        lane_count=lane_count,
        busy_minutes=busy,
        free_minutes=max(0, span_minutes - busy),
    )
