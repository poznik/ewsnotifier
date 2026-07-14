from __future__ import annotations

from datetime import UTC, datetime
from datetime import time as dt_time
from zoneinfo import ZoneInfo

import pytest

from notifier.config import Settings
from notifier.models import Meeting

MSK = ZoneInfo("Europe/Moscow")


def make_settings(**overrides) -> Settings:
    defaults: dict = dict(
        ews_server="mail.example.com",
        ews_email="user@example.com",
        ews_username="DOMAIN\\user",
        ews_password="secret",
        ews_auth_type="NTLM",
        ews_verify_ssl=True,
        update_interval=60,
        appointment_refresh_interval=30,
        appointment_notify_interval=900,
        mail_refresh_interval=60,
        appointment_bot_token="123:abc",
        mail_bot_token="456:def",
        allowed_chat_ids=frozenset({111, 222}),
        admin_chat_id=None,
        local_timezone=MSK,
        keywords=[],
        mention_text="",
        agenda_time=None,
        agenda_format="image",
        workday_start=dt_time(9, 0),
        mail_lookback_days=7,
        mail_fetch_limit=100,
        state_file="state.json",
        health_file="/tmp/notifier-healthy-test",
        mask_private_meetings=False,
        auth_retry_interval=1800,
        log_level="INFO",
    )
    defaults.update(overrides)
    return Settings(**defaults)


def make_meeting(
    *,
    id: str = "m1",
    subject: str = "Планёрка",
    start_utc: datetime | None = None,
    end_utc: datetime | None = None,
    organizer: str = "Иван Иванов",
    location: str = "",
    join_url: str | None = None,
    is_all_day: bool = False,
    is_private: bool = False,
) -> Meeting:
    if start_utc is None:
        start_utc = datetime(2026, 7, 14, 7, 0, tzinfo=UTC)  # 10:00 MSK
    if end_utc is None:
        end_utc = datetime(2026, 7, 14, 8, 0, tzinfo=UTC)  # 11:00 MSK
    return Meeting(
        id=id,
        subject=subject,
        start_utc=start_utc,
        end_utc=end_utc,
        organizer=organizer,
        location=location,
        join_url=join_url,
        is_all_day=is_all_day,
        is_private=is_private,
    )


@pytest.fixture
def settings() -> Settings:
    return make_settings()
