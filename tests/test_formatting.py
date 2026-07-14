from __future__ import annotations

from datetime import UTC, datetime
from datetime import time as dt_time

from notifier.formatting import (
    CAPTION_LIMIT,
    build_agenda_caption,
    build_check_list,
    build_mail_message,
    build_meeting_message,
    build_today_list,
    find_overlaps,
    normalize_subject,
    split_message,
)
from notifier.models import MailItem

from .conftest import make_meeting, make_settings


def _utc(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, 14, hour, minute, tzinfo=UTC)


class TestNormalizeSubject:
    def test_collapses_whitespace(self):
        assert normalize_subject("Тема\nс переносом\t строк") == "Тема с переносом строк"

    def test_empty_fallback(self):
        assert normalize_subject(None) == "(без темы)"
        assert normalize_subject("   ") == "(без темы)"


class TestSplitMessage:
    def test_short_text_single_chunk(self):
        assert split_message("привет") == ["привет"]

    def test_splits_on_line_boundaries(self):
        lines = [f"строка {i} " + "x" * 90 for i in range(100)]
        text = "\n".join(lines)
        chunks = split_message(text, limit=1000)
        assert len(chunks) > 1
        assert all(len(chunk) <= 1000 for chunk in chunks)
        assert "\n".join(chunks) == text

    def test_hard_split_of_monster_line(self):
        text = "y" * 9000
        chunks = split_message(text, limit=4000)
        assert [len(c) for c in chunks] == [4000, 4000, 1000]
        assert "".join(chunks) == text


class TestBuildTodayList:
    def test_empty_day(self):
        settings = make_settings()
        text = build_today_list([], settings)
        assert "Встреч нет" in text

    def test_no_carriage_returns(self):
        settings = make_settings()
        text = build_today_list([make_meeting()], settings)
        assert "\r" not in text

    def test_window_before_first_meeting_uses_workday_start(self):
        settings = make_settings()
        # 10:00–11:00 MSK
        meeting = make_meeting(start_utc=_utc(7), end_utc=_utc(8))
        text = build_today_list([meeting], settings)
        assert "начало 09:00" in text
        assert "1 ч" in text

    def test_window_respects_custom_workday_start(self):
        settings = make_settings(workday_start=dt_time(8, 0))
        meeting = make_meeting(start_utc=_utc(7), end_utc=_utc(8))
        text = build_today_list([meeting], settings)
        assert "начало 08:00" in text
        assert "2 ч" in text

    def test_gap_between_meetings(self):
        settings = make_settings()
        first = make_meeting(id="a", start_utc=_utc(6), end_utc=_utc(7))
        second = make_meeting(id="b", start_utc=_utc(8), end_utc=_utc(9))
        text = build_today_list([first, second], settings)
        # gap 10:00–11:00 MSK
        assert "начало 10:00" in text

    def test_all_day_listed_separately(self):
        settings = make_settings()
        all_day = make_meeting(
            id="ad",
            subject="Отпуск Пети",
            start_utc=datetime(2026, 7, 13, 21, 0, tzinfo=UTC),
            end_utc=datetime(2026, 7, 14, 21, 0, tzinfo=UTC),
            is_all_day=True,
        )
        timed = make_meeting(id="t", start_utc=_utc(7), end_utc=_utc(8))
        text = build_today_list([all_day, timed], settings)
        assert "Весь день: Отпуск Пети" in text
        # the all-day entry must not поглотить окно до первой обычной встречи
        assert "начало 09:00" in text

    def test_private_meeting_masked(self):
        settings = make_settings(mask_private_meetings=True)
        meeting = make_meeting(subject="Собеседование кандидата", is_private=True)
        text = build_today_list([meeting], settings)
        assert "Собеседование" not in text
        assert "Приватная встреча" in text

    def test_private_meeting_not_masked_by_default(self):
        settings = make_settings()
        meeting = make_meeting(subject="Собеседование кандидата", is_private=True)
        text = build_today_list([meeting], settings)
        assert "Собеседование кандидата" in text


class TestBuildAgendaCaption:
    def test_summary_line(self):
        settings = make_settings()
        meeting = make_meeting(start_utc=_utc(7), end_utc=_utc(8))  # 10:00–11:00 MSK
        text = build_agenda_caption([meeting], settings)
        assert "Вторник, 14 июля" in text
        assert "1 встреча" in text
        assert "занято 1 ч" in text

    def test_plural_agreement(self):
        settings = make_settings()
        meetings = [
            make_meeting(id="a", start_utc=_utc(7), end_utc=_utc(8)),
            make_meeting(id="b", start_utc=_utc(9), end_utc=_utc(10)),
        ]
        assert "2 встречи" in build_agenda_caption(meetings, settings)

    def test_overlap_is_spelled_out(self):
        settings = make_settings()
        first = make_meeting(id="a", subject="Демо", start_utc=_utc(7), end_utc=_utc(8))
        second = make_meeting(
            id="b", subject="Интервью", start_utc=_utc(7, 30), end_utc=_utc(8, 30)
        )
        text = build_agenda_caption([first, second], settings)
        assert "Пересечение" in text
        assert "Демо" in text and "Интервью" in text

    def test_all_day_listed(self):
        settings = make_settings()
        all_day = make_meeting(id="ad", subject="Отпуск Пети", is_all_day=True)
        timed = make_meeting(id="t", start_utc=_utc(7), end_utc=_utc(8))
        text = build_agenda_caption([all_day, timed], settings)
        assert "Весь день: Отпуск Пети" in text

    def test_empty_day(self):
        text = build_agenda_caption([], make_settings())
        assert "Встреч нет" in text

    def test_private_meeting_masked(self):
        settings = make_settings(mask_private_meetings=True)
        first = make_meeting(
            id="a", subject="Секретное", is_private=True, start_utc=_utc(7), end_utc=_utc(8)
        )
        second = make_meeting(id="b", subject="Обычное", start_utc=_utc(7, 30), end_utc=_utc(8, 30))
        text = build_agenda_caption([first, second], settings)
        assert "Секретное" not in text
        assert "Приватная встреча" in text

    def test_caption_never_exceeds_telegram_limit(self):
        settings = make_settings()
        # a wall of mutually overlapping meetings: one badge line per pair
        meetings = [
            make_meeting(
                id=f"m{i}",
                subject=f"Очень длинная тема встречи номер {i} " * 3,
                start_utc=_utc(7),
                end_utc=_utc(10),
            )
            for i in range(12)
        ]
        text = build_agenda_caption(meetings, settings)
        assert len(text) <= CAPTION_LIMIT


class TestFindOverlapsAndCheckList:
    def test_no_overlaps_back_to_back(self):
        first = make_meeting(id="a", start_utc=_utc(7), end_utc=_utc(8))
        second = make_meeting(id="b", start_utc=_utc(8), end_utc=_utc(9))
        assert find_overlaps([first, second]) == []

    def test_overlap_detected_with_minutes(self):
        settings = make_settings()
        first = make_meeting(id="a", start_utc=_utc(7), end_utc=_utc(8))
        second = make_meeting(id="b", start_utc=_utc(7, 30), end_utc=_utc(8, 30))
        text = build_check_list([first, second], settings)
        assert "Всего пересечений: 1" in text
        assert "30 мин" in text

    def test_all_day_excluded_from_overlaps(self):
        all_day = make_meeting(
            id="ad",
            start_utc=datetime(2026, 7, 13, 21, 0, tzinfo=UTC),
            end_utc=datetime(2026, 7, 14, 21, 0, tzinfo=UTC),
            is_all_day=True,
        )
        first = make_meeting(id="a", start_utc=_utc(7), end_utc=_utc(8))
        second = make_meeting(id="b", start_utc=_utc(9), end_utc=_utc(10))
        assert find_overlaps([all_day, first, second]) == []

    def test_zero_overlaps_message(self):
        settings = make_settings()
        text = build_check_list([], settings)
        assert "Всего пересечений: 0" in text

    def test_three_way_overlap_chain(self):
        # a: 10-12, b: 11-13, c: 12:30-14 — одна группа из трёх
        a = make_meeting(id="a", start_utc=_utc(7), end_utc=_utc(9))
        b = make_meeting(id="b", start_utc=_utc(8), end_utc=_utc(10))
        c = make_meeting(id="c", start_utc=_utc(9, 30), end_utc=_utc(11))
        groups = find_overlaps([a, b, c])
        assert len(groups) == 1
        assert [m.id for m in groups[0]] == ["a", "b", "c"]


class TestBuildMeetingMessage:
    def test_subject_newline_normalized(self):
        settings = make_settings()
        meeting = make_meeting(subject="Строка1\nСтрока2")
        text = build_meeting_message(meeting, settings, now_utc=_utc(6, 45))
        first_line = text.split("\n")[0]
        assert "Строка1 Строка2" in first_line

    def test_minutes_and_duration(self):
        settings = make_settings()
        meeting = make_meeting(start_utc=_utc(7), end_utc=_utc(8, 30))
        text = build_meeting_message(meeting, settings, now_utc=_utc(6, 45))
        assert "Через 15 мин" in text
        assert "1 ч 30 мин" in text

    def test_join_url_line(self):
        settings = make_settings()
        meeting = make_meeting(
            location="Teams <https://teams.example.com/j/1>",
            join_url="https://teams.example.com/j/1",
        )
        text = build_meeting_message(meeting, settings, now_utc=_utc(6, 45))
        assert "Ссылка:" in text

    def test_location_fallback(self):
        settings = make_settings()
        meeting = make_meeting(location="Переговорка 5")
        text = build_meeting_message(meeting, settings, now_utc=_utc(6, 45))
        assert "Место: Переговорка 5" in text


class TestBuildMailMessage:
    def _mail(self, **overrides) -> MailItem:
        defaults = dict(
            id="mail1",
            subject="Отчёт за квартал",
            sender="Пётр Петров",
            sent_utc=_utc(7),
            preview="Добрый день\nво вложении отчёт",
        )
        defaults.update(overrides)
        return MailItem(**defaults)

    def test_basic_fields(self):
        settings = make_settings()
        text = build_mail_message(self._mail(), settings)
        assert "Отчёт за квартал" in text
        assert "Пётр Петров" in text
        assert "> Добрый день" in text

    def test_mention_added_for_keyword(self):
        settings = make_settings(keywords=["срочно"], mention_text="@duty")
        text = build_mail_message(self._mail(subject="Срочно: сервер упал"), settings)
        assert text.startswith("‼️")
        assert "@duty" in text

    def test_no_mention_without_keyword(self):
        settings = make_settings(keywords=["срочно"], mention_text="@duty")
        text = build_mail_message(self._mail(), settings)
        assert "‼️" not in text
        assert "@duty" not in text

    def test_subject_newline_normalized(self):
        settings = make_settings()
        text = build_mail_message(self._mail(subject="Тема\nс переносом"), settings)
        assert text.split("\n")[0] == "*Тема с переносом*"
