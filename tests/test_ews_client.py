from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from notifier.ews_client import _mail_from_item, _meeting_from_item, _to_utc_datetime

MSK = ZoneInfo("Europe/Moscow")


def _calendar_item(**overrides) -> SimpleNamespace:
    defaults = dict(
        id="item1",
        subject="Планёрка",
        start=datetime(2026, 7, 14, 7, 0, tzinfo=UTC),
        end=datetime(2026, 7, 14, 8, 0, tzinfo=UTC),
        location="",
        organizer=SimpleNamespace(name="Иван", email_address="ivan@example.com"),
        is_all_day=False,
        is_cancelled=False,
        sensitivity="Normal",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestToUtcDatetime:
    def test_aware_datetime_converted(self):
        value = datetime(2026, 7, 14, 10, 0, tzinfo=MSK)
        assert _to_utc_datetime(value, MSK) == datetime(2026, 7, 14, 7, 0, tzinfo=UTC)

    def test_naive_datetime_assumed_utc(self):
        value = datetime(2026, 7, 14, 7, 0)
        result = _to_utc_datetime(value, MSK)
        assert result == datetime(2026, 7, 14, 7, 0, tzinfo=UTC)

    def test_plain_date_becomes_local_midnight(self):
        # C1: EWSDate (all-day) must not crash and maps to local midnight
        result = _to_utc_datetime(date(2026, 7, 14), MSK)
        assert result == datetime(2026, 7, 13, 21, 0, tzinfo=UTC)


class TestMeetingFromItem:
    def test_regular_meeting(self):
        meeting = _meeting_from_item(_calendar_item(), MSK)
        assert meeting is not None
        assert meeting.subject == "Планёрка"
        assert meeting.organizer == "Иван"
        assert meeting.is_all_day is False
        assert meeting.is_private is False

    def test_all_day_dates_converted_inclusive_end(self):
        item = _calendar_item(
            start=date(2026, 7, 14),
            end=date(2026, 7, 14),  # exchangelib: конец включительно
            is_all_day=True,
        )
        meeting = _meeting_from_item(item, MSK)
        assert meeting is not None
        assert meeting.is_all_day is True
        assert meeting.start_utc == datetime(2026, 7, 13, 21, 0, tzinfo=UTC)
        assert meeting.end_utc == datetime(2026, 7, 14, 21, 0, tzinfo=UTC)

    def test_missing_start_returns_none(self):
        assert _meeting_from_item(_calendar_item(start=None), MSK) is None

    def test_private_sensitivity(self):
        meeting = _meeting_from_item(_calendar_item(sensitivity="Private"), MSK)
        assert meeting is not None
        assert meeting.is_private is True

    def test_join_url_extracted_and_cleaned(self):
        item = _calendar_item(location="Teams <https://teams.example.com/j/1>")
        meeting = _meeting_from_item(item, MSK)
        assert meeting is not None
        assert meeting.join_url == "https://teams.example.com/j/1"

    def test_organizer_email_fallback(self):
        item = _calendar_item(
            organizer=SimpleNamespace(name=None, email_address="ivan@example.com")
        )
        meeting = _meeting_from_item(item, MSK)
        assert meeting is not None
        assert meeting.organizer == "ivan@example.com"


class TestMailFromItem:
    def test_regular_mail(self):
        item = SimpleNamespace(
            id="mail1",
            subject="Отчёт",
            datetime_sent=datetime(2026, 7, 14, 7, 0, tzinfo=UTC),
            sender=SimpleNamespace(name="Пётр", email_address="p@example.com"),
            text_body="Добрый день!\nВо вложении отчёт.",
        )
        mail = _mail_from_item(item)
        assert mail is not None
        assert mail.subject == "Отчёт"
        assert mail.sender == "Пётр"
        assert "Добрый день!" in mail.preview

    def test_missing_sent_returns_none(self):
        item = SimpleNamespace(
            id="mail1", subject="x", datetime_sent=None, sender=None, text_body=""
        )
        assert _mail_from_item(item) is None

    def test_empty_body_gives_empty_preview(self):
        item = SimpleNamespace(
            id="mail1",
            subject="x",
            datetime_sent=datetime(2026, 7, 14, 7, 0, tzinfo=UTC),
            sender=None,
            text_body=None,
        )
        mail = _mail_from_item(item)
        assert mail is not None
        assert mail.preview == ""
        assert mail.sender == ""
