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
        assert "встреч нет" in text

    def test_no_carriage_returns(self):
        settings = make_settings()
        text = build_today_list([make_meeting()], settings)
        assert "\r" not in text

    def test_time_range_precedes_subject(self):
        # the whole point of the refresh: time first, so the column lines up
        settings = make_settings()
        meeting = make_meeting(start_utc=_utc(7), end_utc=_utc(8))  # 10:00–11:00 MSK
        text = build_today_list([meeting], settings)
        line = next(ln for ln in text.split("\n") if "Планёрка" in ln)
        assert line.index("10:00") < line.index("Планёрка")
        assert "10:00–11:00" in text

    def test_summary_header(self):
        settings = make_settings()
        meetings = [
            make_meeting(id="a", start_utc=_utc(7), end_utc=_utc(8)),
            make_meeting(id="b", start_utc=_utc(9), end_utc=_utc(10)),
        ]
        text = build_today_list(meetings, settings)
        assert "Сегодня" in text
        assert "2 встречи" in text
        assert "занято" in text

    def test_free_window_before_first_meeting(self):
        settings = make_settings()
        # 10:00–11:00 MSK, workday starts 09:00 → free 09:00–10:00
        meeting = make_meeting(start_utc=_utc(7), end_utc=_utc(8))
        text = build_today_list([meeting], settings)
        assert "09:00–10:00" in text
        assert "свободно 1 ч" in text

    def test_free_window_respects_custom_workday_start(self):
        settings = make_settings(workday_start=dt_time(8, 0))
        meeting = make_meeting(start_utc=_utc(7), end_utc=_utc(8))
        text = build_today_list([meeting], settings)
        assert "08:00–10:00" in text
        assert "свободно 2 ч" in text

    def test_gap_between_meetings(self):
        settings = make_settings()
        first = make_meeting(id="a", start_utc=_utc(6), end_utc=_utc(7))
        second = make_meeting(id="b", start_utc=_utc(8), end_utc=_utc(9))
        text = build_today_list([first, second], settings)
        assert "10:00–11:00" in text  # gap 10:00–11:00 MSK

    def test_clash_marked_in_schedule(self):
        settings = make_settings()
        first = make_meeting(id="a", subject="Демо", start_utc=_utc(7), end_utc=_utc(8))
        second = make_meeting(id="b", subject="Собес", start_utc=_utc(7, 30), end_utc=_utc(8, 30))
        text = build_today_list([first, second], settings)
        assert "⚠️" in text

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
        assert "09:00–10:00" in text

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


class TestBuildCheckList:
    def test_no_overlaps_message(self):
        settings = make_settings()
        text = build_check_list([], settings)
        assert "Пересечений нет" in text

    def test_back_to_back_has_no_overlap(self):
        settings = make_settings()
        first = make_meeting(id="a", start_utc=_utc(7), end_utc=_utc(8))
        second = make_meeting(id="b", start_utc=_utc(8), end_utc=_utc(9))
        text = build_check_list([first, second], settings)
        assert "Пересечений нет" in text

    def test_overlap_shows_stretch_and_minutes(self):
        settings = make_settings()
        first = make_meeting(id="a", subject="Демо", start_utc=_utc(7), end_utc=_utc(8))
        second = make_meeting(id="b", subject="Собес", start_utc=_utc(7, 30), end_utc=_utc(8, 30))
        text = build_check_list([first, second], settings)
        assert "1 пересечение" in text
        assert "10:30–11:00" in text  # the exact collision stretch, MSK
        assert "30 мин" in text
        assert "Демо" in text and "Собес" in text

    def test_all_day_excluded(self):
        settings = make_settings()
        all_day = make_meeting(
            id="ad",
            start_utc=datetime(2026, 7, 13, 21, 0, tzinfo=UTC),
            end_utc=datetime(2026, 7, 14, 21, 0, tzinfo=UTC),
            is_all_day=True,
        )
        first = make_meeting(id="a", start_utc=_utc(7), end_utc=_utc(8))
        second = make_meeting(id="b", start_utc=_utc(9), end_utc=_utc(10))
        text = build_check_list([all_day, first, second], settings)
        assert "Пересечений нет" in text

    def test_three_way_overlap_lists_pairs(self):
        # a:10–12, b:11–13, c:12:30–14 → pairs a-b and b-c (a and c don't touch)
        settings = make_settings()
        a = make_meeting(id="a", start_utc=_utc(7), end_utc=_utc(9))
        b = make_meeting(id="b", start_utc=_utc(8), end_utc=_utc(10))
        c = make_meeting(id="c", start_utc=_utc(9, 30), end_utc=_utc(11))
        text = build_check_list([a, b, c], settings)
        assert "2 пересечения" in text


class TestBuildMeetingMessage:
    def test_subject_is_the_first_line(self):
        settings = make_settings()
        meeting = make_meeting(subject="Строка1\nСтрока2")
        text = build_meeting_message(meeting, settings, now_utc=_utc(6, 45))
        first_line = text.split("\n")[0]
        assert "Строка1 Строка2" in first_line
        assert first_line.startswith("🔔")

    def test_reminder_lead_and_time_range(self):
        settings = make_settings()
        meeting = make_meeting(start_utc=_utc(7), end_utc=_utc(8, 30))  # 10:00–11:30 MSK
        text = build_meeting_message(meeting, settings, now_utc=_utc(6, 45))
        assert "Через 15 минут" in text
        assert "10:00–11:30" in text
        assert "1 ч 30 мин" in text

    def test_minute_plural_agreement(self):
        settings = make_settings()
        meeting = make_meeting(start_utc=_utc(7), end_utc=_utc(8))
        assert "Через 1 минуту" in build_meeting_message(meeting, settings, now_utc=_utc(6, 59))
        assert "Через 2 минуты" in build_meeting_message(meeting, settings, now_utc=_utc(6, 58))
        assert "Через 5 минут " in build_meeting_message(meeting, settings, now_utc=_utc(6, 55))

    def test_starts_now(self):
        settings = make_settings()
        meeting = make_meeting(start_utc=_utc(7), end_utc=_utc(8))
        text = build_meeting_message(meeting, settings, now_utc=_utc(7))
        assert "Начинается сейчас" in text

    def test_no_date_in_message(self):
        # the full date was noise: the reminder fires minutes before, today
        settings = make_settings()
        meeting = make_meeting(start_utc=_utc(7), end_utc=_utc(8))
        text = build_meeting_message(meeting, settings, now_utc=_utc(6, 45))
        assert "2026" not in text

    def test_online_place_is_a_clickable_link(self):
        settings = make_settings()
        meeting = make_meeting(
            location="Teams <https://teams.example.com/j/1>",
            join_url="https://teams.example.com/j/1",
        )
        text = build_meeting_message(meeting, settings, now_utc=_utc(6, 45))
        # the place name links to the meeting; the URL lives in the text now
        assert "📍 [Teams](https://teams.example.com/j/1)" in text

    def test_bare_url_labelled_by_host(self):
        # location is just the join link → show the meeting's domain, not a generic word
        settings = make_settings()
        url = "https://nexign.ktalk.ru/BSS_Project_Status"
        meeting = make_meeting(location=url, join_url=url)
        text = build_meeting_message(meeting, settings, now_utc=_utc(6, 45))
        # dots in the host are MarkdownV2 special chars → escaped in the label
        assert f"📍 [nexign\\.ktalk\\.ru]({url})" in text

    def test_host_label_drops_www(self):
        settings = make_settings()
        url = "https://www.trueconf.nexign.com/r/42"
        meeting = make_meeting(location=url, join_url=url)
        text = build_meeting_message(meeting, settings, now_utc=_utc(6, 45))
        # label drops the www.; the URL keeps it untouched
        assert f"[trueconf\\.nexign\\.com]({url})" in text

    def test_link_url_escapes_only_paren_and_backslash(self):
        settings = make_settings()
        meeting = make_meeting(
            location="Комната",
            join_url="https://x.io/meet(room1)?id=42",
        )
        text = build_meeting_message(meeting, settings, now_utc=_utc(6, 45))
        # closing paren escaped so it does not end the link; the rest untouched
        assert "[Комната](https://x.io/meet(room1\\)?id=42)" in text

    def test_physical_location_is_not_a_link(self):
        settings = make_settings()
        meeting = make_meeting(location="Переговорка 5")
        text = build_meeting_message(meeting, settings, now_utc=_utc(6, 45))
        assert "📍 Переговорка 5" in text
        assert "](" not in text  # no markdown link when there is no join URL

    def test_no_place_line_when_nothing(self):
        settings = make_settings()
        meeting = make_meeting(location="", join_url=None)
        text = build_meeting_message(meeting, settings, now_utc=_utc(6, 45))
        assert "📍" not in text

    def test_organizer_shown(self):
        settings = make_settings()
        meeting = make_meeting(organizer="Иван Иванов")
        text = build_meeting_message(meeting, settings, now_utc=_utc(6, 45))
        assert "👤 Иван Иванов" in text


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
