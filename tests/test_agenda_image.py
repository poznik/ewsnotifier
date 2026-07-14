"""The renderer is checked for what a picture can be checked for: that it is a
valid PNG of a sane size, that it survives the awkward days, and that it never
takes the agenda down with it when the font is missing."""

from __future__ import annotations

import io
from datetime import UTC, datetime

import pytest
from PIL import Image

from notifier import agenda_image
from notifier.agenda_image import AgendaRenderError, render_agenda_png

from .conftest import make_meeting, make_settings


def _utc(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, 14, hour, minute, tzinfo=UTC)


def _open(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png))


class TestRender:
    def test_empty_day_draws_nothing(self):
        assert render_agenda_png([], make_settings()) is None

    def test_all_day_only_draws_nothing(self):
        all_day = make_meeting(id="ad", is_all_day=True)
        assert render_agenda_png([all_day], make_settings()) is None

    def test_ordinary_day_is_a_png(self):
        meetings = [
            make_meeting(
                id="a", subject="Планёрка команды", start_utc=_utc(7), end_utc=_utc(7, 30)
            ),
            make_meeting(id="b", subject="Синк по релизу", start_utc=_utc(8), end_utc=_utc(9)),
        ]
        png = render_agenda_png(meetings, make_settings())
        assert png is not None
        image = _open(png)
        assert image.format == "PNG"
        assert image.width == agenda_image.WIDTH * agenda_image.SCALE
        # 09:00–12:00 MSK plus the header: tall, but nowhere near a Telegram limit
        assert 400 < image.height < 2000

    def test_overlapping_day_renders(self):
        meetings = [
            make_meeting(id="a", subject="Демо", start_utc=_utc(9), end_utc=_utc(10, 30)),
            make_meeting(id="b", subject="Собеседование", start_utc=_utc(10), end_utc=_utc(11)),
        ]
        png = render_agenda_png(meetings, make_settings())
        assert png is not None
        assert _open(png).format == "PNG"

    def test_three_way_overlap_renders(self):
        meetings = [
            make_meeting(id="a", subject="Архсовет", start_utc=_utc(7), end_utc=_utc(9)),
            make_meeting(id="b", subject="Статус", start_utc=_utc(8), end_utc=_utc(10)),
            make_meeting(id="c", subject="Инцидент", start_utc=_utc(8, 30), end_utc=_utc(9, 30)),
        ]
        png = render_agenda_png(meetings, make_settings())
        assert png is not None
        assert _open(png).format == "PNG"

    def test_short_meeting_renders(self):
        # 15 minutes: the block is stretched to the minimum height, and the gap
        # behind it must not be drawn over the block
        meetings = [
            make_meeting(id="a", subject="Стендап", start_utc=_utc(6, 30), end_utc=_utc(6, 45)),
            make_meeting(id="b", subject="Интервью", start_utc=_utc(7, 15), end_utc=_utc(8, 15)),
        ]
        png = render_agenda_png(meetings, make_settings())
        assert png is not None
        assert _open(png).format == "PNG"

    def test_long_subject_does_not_break_render(self):
        meetings = [
            make_meeting(
                id="a",
                subject="Обсуждение архитектуры платформы " * 5,
                start_utc=_utc(7),
                end_utc=_utc(8),
            )
        ]
        png = render_agenda_png(meetings, make_settings())
        assert png is not None

    def test_private_meeting_is_masked(self, monkeypatch):
        drawn: list[str] = []
        original = agenda_image.meeting_subject

        def spy(meeting, settings):
            subject = original(meeting, settings)
            drawn.append(subject)
            return subject

        monkeypatch.setattr(agenda_image, "meeting_subject", spy)
        meeting = make_meeting(
            subject="Секретное", is_private=True, start_utc=_utc(7), end_utc=_utc(8)
        )
        render_agenda_png([meeting], make_settings(mask_private_meetings=True))
        assert "Секретное" not in drawn
        assert "Приватная встреча" in drawn


class TestMissingFont:
    def test_no_font_raises_so_the_caller_can_fall_back(self, monkeypatch):
        monkeypatch.setattr(agenda_image, "_REGULAR_CANDIDATES", ("/nowhere/none.ttf",))
        monkeypatch.setattr(agenda_image, "_BOLD_CANDIDATES", ("/nowhere/none-bold.ttf",))
        agenda_image._font.cache_clear()
        meeting = make_meeting(start_utc=_utc(7), end_utc=_utc(8))
        with pytest.raises(AgendaRenderError):
            render_agenda_png([meeting], make_settings())
        agenda_image._font.cache_clear()
