"""The morning agenda drawn as a calendar, not written as a list.

The day is a vertical timeline, the way Outlook draws it: the hour scale runs
down the left, a block's height is its duration, meetings that overlap stand in
neighbouring lanes, and free windows are the green stretches between them.

Rendering is 2x and downscaled by Telegram, which re-encodes photos as JPEG:
at 1x the labels would come out mushy.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from notifier.agenda import DayLayout, Gap, build_day_layout, format_day_title
from notifier.config import Settings
from notifier.formatting import meeting_subject
from notifier.models import Meeting
from notifier.utils import format_duration, format_minutes, plural_meetings

_LOGGER = logging.getLogger("notifier.agenda")

SCALE = 2  # rendered at 2x, so JPEG re-encoding does not eat the labels
WIDTH = 460  # logical points; physical width is WIDTH * SCALE
PAD = 16
TIME_COLUMN = 46
PX_PER_MINUTE = 1.05
MIN_BLOCK_HEIGHT = 30  # fits one line of text with its padding
MAX_LANES = 3  # more than three parallel meetings would shred the width

BACKGROUND = "#FFFFFF"
INK = "#111827"
MUTED = "#6B7280"
GRID = "#E9EDF2"

BUSY_BG, BUSY_ACCENT, BUSY_INK = "#EAF2FE", "#3B82F6", "#1D4ED8"
CLASH_BG, CLASH_ACCENT, CLASH_INK = "#FDECEC", "#EF4444", "#B91C1C"
FREE_BG, FREE_INK = "#F1FBF4", "#15803D"
ALLDAY_BG, ALLDAY_ACCENT, ALLDAY_INK = "#F4F1FE", "#8B5CF6", "#6D28D9"

# Debian slim ships no fonts at all; fonts-dejavu-core is installed in the image.
# The Windows and macOS paths are there so the renderer also works outside Docker.
_REGULAR_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
)
_BOLD_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/seguisb.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


class AgendaRenderError(RuntimeError):
    """The agenda could not be drawn; the caller falls back to plain text."""


def _font_path(candidates: tuple[str, ...]) -> str:
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    raise AgendaRenderError(
        "no usable font found (install fonts-dejavu-core), tried: " + ", ".join(candidates)
    )


@lru_cache(maxsize=16)
def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = _BOLD_CANDIDATES if bold else _REGULAR_CANDIDATES
    return ImageFont.truetype(_font_path(candidates), size * SCALE)


def _line_height(font: ImageFont.FreeTypeFont) -> int:
    ascent, descent = font.getmetrics()
    return ascent + descent


def _scaled(value: float) -> int:
    return int(value * SCALE)


def _clip(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return text.rstrip() + "…"


def _wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    max_lines: int,
) -> list[str]:
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == max_lines - 1:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if not lines:
        return [_clip(draw, text, font, max_width)]
    lines[-1] = _clip(draw, lines[-1], font, max_width)
    return lines


def _local_time(moment: datetime, settings: Settings) -> str:
    return moment.astimezone(settings.local_timezone).strftime("%H:%M")


def _summary(layout: DayLayout) -> str:
    return (
        f"{plural_meetings(len(layout.timed))}   ·   "
        f"занято {format_minutes(layout.busy_minutes)}   ·   "
        f"свободно {format_minutes(layout.free_minutes)}"
    )


def render_agenda_png(meetings: list[Meeting], settings: Settings) -> bytes | None:
    """Draw the day. Returns None when there is no calendar to draw.

    Raises AgendaRenderError when drawing is impossible (no font, for instance);
    the agenda loop then falls back to the plain-text summary.
    """
    layout = build_day_layout(meetings, settings)
    if layout.is_empty:
        return None

    font_title = _font(19, bold=True)
    font_summary = _font(12)
    font_badge = _font(12, bold=True)
    font_subject = _font(13, bold=True)
    font_meta = _font(11)
    font_scale = _font(11)
    font_free = _font(12, bold=True)

    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))

    # Header height first: the calendar starts under however many badges there are.
    header_height = PAD + 26 + 22 + 30 * (len(layout.all_day) + len(layout.overlaps)) + 10
    calendar_minutes = (layout.day_end_utc - layout.day_start_utc).total_seconds() / 60
    height = header_height + calendar_minutes * PX_PER_MINUTE + 14 + PAD

    image = Image.new("RGB", (_scaled(WIDTH), _scaled(height)), BACKGROUND)
    draw = ImageDraw.Draw(image)

    y = PAD
    title = format_day_title(layout.day_start_utc.astimezone(settings.local_timezone))
    draw.text((_scaled(PAD), _scaled(y)), title, font=font_title, fill=INK)
    y += 26
    draw.text((_scaled(PAD), _scaled(y)), _summary(layout), font=font_summary, fill=MUTED)
    y += 22

    badge_width = _scaled(WIDTH - 2 * PAD - 24)
    for meeting in layout.all_day:
        _badge(
            draw,
            y,
            f"Весь день · {meeting_subject(meeting, settings)}",
            font_badge,
            badge_width,
            ALLDAY_BG,
            ALLDAY_ACCENT,
            ALLDAY_INK,
            probe,
        )
        y += 30

    for overlap in layout.overlaps:
        text = (
            f"Пересечение {_local_time(overlap.start_utc, settings)}–"
            f"{_local_time(overlap.end_utc, settings)} · "
            f"{meeting_subject(overlap.first, settings)} × "
            f"{meeting_subject(overlap.second, settings)}"
        )
        _badge(
            draw,
            y,
            text,
            font_badge,
            badge_width - _scaled(16),
            CLASH_BG,
            CLASH_ACCENT,
            CLASH_INK,
            probe,
            warning=True,
        )
        y += 30

    _draw_calendar(
        draw,
        probe,
        layout,
        settings,
        top=header_height,
        fonts=(font_scale, font_free, font_subject, font_meta),
    )

    buffer = io.BytesIO()
    image.save(buffer, "PNG", optimize=True)
    _LOGGER.debug("Agenda image: %s×%s, %s bytes", image.width, image.height, buffer.tell())
    return buffer.getvalue()


def _badge(
    draw: ImageDraw.ImageDraw,
    y: float,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    background: str,
    accent: str,
    ink: str,
    probe: ImageDraw.ImageDraw,
    warning: bool = False,
) -> None:
    draw.rounded_rectangle(
        [_scaled(PAD), _scaled(y), _scaled(WIDTH - PAD), _scaled(y + 24)],
        radius=_scaled(6),
        fill=background,
    )
    draw.rounded_rectangle(
        [_scaled(PAD), _scaled(y), _scaled(PAD + 3), _scaled(y + 24)],
        radius=_scaled(2),
        fill=accent,
    )
    text_x = PAD + 12
    if warning:
        # Pillow cannot draw colour emoji, so the warning sign is a real triangle.
        cx, cy, r = _scaled(PAD + 16), _scaled(y + 12), _scaled(5)
        draw.polygon([(cx, cy - r), (cx - r, cy + r), (cx + r, cy + r)], fill=accent)
        text_x = PAD + 28
    draw.text(
        (_scaled(text_x), _scaled(y + 5)),
        _clip(probe, text, font, max_width),
        font=font,
        fill=ink,
    )


def _draw_calendar(
    draw: ImageDraw.ImageDraw,
    probe: ImageDraw.ImageDraw,
    layout: DayLayout,
    settings: Settings,
    top: float,
    fonts: tuple[
        ImageFont.FreeTypeFont,
        ImageFont.FreeTypeFont,
        ImageFont.FreeTypeFont,
        ImageFont.FreeTypeFont,
    ],
) -> None:
    font_scale, font_free, font_subject, font_meta = fonts
    lane_count = min(MAX_LANES, layout.lane_count)
    lane_x0 = PAD + TIME_COLUMN
    lane_width = (WIDTH - PAD - lane_x0 - (lane_count - 1) * 4) / lane_count

    def y_of(moment: datetime) -> int:
        minutes = (moment - layout.day_start_utc).total_seconds() / 60
        return _scaled(top + minutes * PX_PER_MINUTE)

    _draw_hour_scale(draw, layout, settings, y_of, font_scale, lane_x0)

    # A meeting shorter than MIN_BLOCK_HEIGHT is drawn taller than it really is,
    # so the window behind it must start below the block, not at its true end.
    visual_bottom = {
        m.id: max(y_of(m.end_utc), y_of(m.start_utc) + _scaled(MIN_BLOCK_HEIGHT))
        for m in layout.timed
    }

    biggest = layout.biggest_gap
    for gap in layout.gaps:
        _draw_gap(draw, probe, gap, layout, visual_bottom, y_of, font_free, lane_x0, biggest)

    for meeting in layout.timed:
        _draw_meeting(
            draw,
            probe,
            meeting,
            layout,
            settings,
            y_of,
            font_subject,
            font_meta,
            lane_x0,
            lane_width,
            lane_count,
        )


def _draw_hour_scale(
    draw: ImageDraw.ImageDraw,
    layout: DayLayout,
    settings: Settings,
    y_of,
    font: ImageFont.FreeTypeFont,
    lane_x0: float,
) -> None:
    local_start = layout.day_start_utc.astimezone(settings.local_timezone)
    hour = local_start.replace(minute=0, second=0, microsecond=0)
    if hour < local_start:
        hour += timedelta(hours=1)
    while hour <= layout.day_end_utc.astimezone(settings.local_timezone):
        y = y_of(hour)
        draw.line(
            [(_scaled(lane_x0 - 6), y), (_scaled(WIDTH - PAD), y)],
            fill=GRID,
            width=max(1, SCALE // 2),
        )
        draw.text(
            (_scaled(lane_x0 - 12), y - _scaled(7)),
            hour.strftime("%H:%M"),
            font=font,
            fill=MUTED,
            anchor="ra",
        )
        hour += timedelta(hours=1)


def _draw_gap(
    draw: ImageDraw.ImageDraw,
    probe: ImageDraw.ImageDraw,
    gap: Gap,
    layout: DayLayout,
    visual_bottom: dict[str, int],
    y_of,
    font: ImageFont.FreeTypeFont,
    lane_x0: float,
    biggest: Gap | None,
) -> None:
    top = max(
        y_of(gap.start_utc),
        max(
            (visual_bottom[m.id] for m in layout.timed if m.end_utc <= gap.start_utc),
            default=y_of(gap.start_utc),
        ),
    )
    bottom = y_of(gap.end_utc)
    if bottom - top < _scaled(18):
        return

    draw.rounded_rectangle(
        [_scaled(lane_x0), top + _scaled(1), _scaled(WIDTH - PAD), bottom - _scaled(1)],
        radius=_scaled(6),
        fill=FREE_BG,
    )
    label = f"свободно {format_minutes(gap.minutes)}"
    if biggest is not None and gap.start_utc == biggest.start_utc and len(layout.gaps) > 1:
        label += "   ← самое большое окно"
    draw.text(
        ((_scaled(lane_x0) + _scaled(WIDTH - PAD)) // 2, (top + bottom) // 2),
        _clip(probe, label, font, _scaled(WIDTH - PAD - lane_x0 - 16)),
        font=font,
        fill=FREE_INK,
        anchor="mm",
    )


def _draw_meeting(
    draw: ImageDraw.ImageDraw,
    probe: ImageDraw.ImageDraw,
    meeting: Meeting,
    layout: DayLayout,
    settings: Settings,
    y_of,
    font_subject: ImageFont.FreeTypeFont,
    font_meta: ImageFont.FreeTypeFont,
    lane_x0: float,
    lane_width: float,
    lane_count: int,
) -> None:
    clash = layout.clashes(meeting)
    background, accent, ink = (
        (CLASH_BG, CLASH_ACCENT, CLASH_INK) if clash else (BUSY_BG, BUSY_ACCENT, BUSY_INK)
    )

    lane = min(layout.lanes[meeting.id], lane_count - 1)
    span = min(layout.lane_span(meeting), lane_count - lane)
    x0 = _scaled(lane_x0 + lane * (lane_width + 4))
    x1 = x0 + _scaled(lane_width * span + 4 * (span - 1))
    top = y_of(meeting.start_utc)
    bottom = max(y_of(meeting.end_utc), top + _scaled(MIN_BLOCK_HEIGHT))

    draw.rounded_rectangle(
        [x0, top + _scaled(1), x1, bottom - _scaled(1)], radius=_scaled(6), fill=background
    )
    draw.rounded_rectangle(
        [x0, top + _scaled(1), x0 + _scaled(3), bottom - _scaled(1)],
        radius=_scaled(2),
        fill=accent,
    )

    subject = meeting_subject(meeting, settings)
    start = _local_time(meeting.start_utc, settings)
    end = _local_time(meeting.end_utc, settings)
    meta = f"{start}–{end} · {format_duration(meeting.start_utc, meeting.end_utc)}"

    inner_width = int(x1 - x0 - _scaled(20))
    text_x = x0 + _scaled(12)
    padding = _scaled(5)
    available = (bottom - top) - 2 * padding
    subject_line = _line_height(font_subject)
    meta_line = _line_height(font_meta)

    # Two lines only when they physically fit: in a half-hour block they do not,
    # and the meta line used to spill onto the bottom edge.
    if available >= 2 * subject_line + meta_line:
        body = _wrap(probe, subject, font_subject, inner_width, 2)
    elif available >= subject_line + meta_line:
        body = [_clip(probe, subject, font_subject, inner_width)]
    else:
        body = []

    if body:
        y = top + padding
        for line in body:
            draw.text((text_x, y), line, font=font_subject, fill=ink)
            y += subject_line
        draw.text((text_x, y), _clip(probe, meta, font_meta, inner_width), font=font_meta, fill=ink)
    else:
        single = f"{subject} · {start}–{end}"
        draw.text(
            (text_x, top + (bottom - top) // 2),
            _clip(probe, single, font_subject, inner_width),
            font=font_subject,
            fill=ink,
            anchor="lm",
        )
