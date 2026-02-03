from __future__ import annotations

from dataclasses import dataclass
from datetime import time as dt_time
from typing import List
import os

from dotenv import load_dotenv
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Settings:
    ews_server: str
    ews_email: str
    ews_username: str
    ews_password: str
    ews_auth_type: str
    ews_verify_ssl: bool
    update_interval: int
    appointment_refresh_interval: int
    appointment_notify_interval: int
    mail_refresh_interval: int
    appointment_bot_token: str
    mail_bot_token: str
    allowed_chat_ids: List[int]
    admin_chat_id: int
    local_timezone: ZoneInfo
    keywords: List[str]
    mention_text: str
    agenda_time: dt_time | None
    log_level: str


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        raise ValueError(f"Missing required env var: {name}")
    return value


def _get_int(name: str, default: int | None = None) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        if default is None:
            raise ValueError(f"Missing required env var: {name}")
        return default
    return int(value)


def _get_bool(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_list(name: str) -> List[str]:
    value = os.getenv(name, "")
    if value == "":
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_chat_ids(name: str) -> List[int]:
    raw = _get_list(name)
    if not raw:
        raise ValueError(f"Missing required env var: {name}")
    return [int(item) for item in raw]


def _get_time(name: str) -> dt_time | None:
    value = os.getenv(name, "").strip()
    if not value:
        return None
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(f"Invalid time format for {name}. Expected HH:MM")
    hour, minute = (int(part) for part in parts)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid time value for {name}. Expected HH:MM")
    return dt_time(hour=hour, minute=minute)


def load_settings() -> Settings:
    load_dotenv(override=False)

    ews_server = _require_env("EWS_SERVER")
    ews_email = _require_env("EWS_EMAIL")
    ews_username = _require_env("EWS_USERNAME")
    ews_password = _require_env("EWS_PASSWORD")
    ews_auth_type = os.getenv("EWS_AUTH_TYPE", "NTLM")
    ews_verify_ssl = _get_bool("EWS_VERIFY_SSL", True)

    update_interval = _get_int("UPDATE_INTERVAL")
    appointment_refresh_interval = _get_int("APPOINTMENT_REFRESH_INTERVAL")
    appointment_notify_interval = _get_int("APPOINTMENT_NOTIFY_INTERVAL")
    mail_refresh_interval = _get_int("MAIL_REFRESH_INTERVAL")

    appointment_bot_token = _require_env("APPOINTMENT_BOT_TOKEN")
    mail_bot_token = _require_env("MAIL_BOT_TOKEN")

    allowed_chat_ids = _parse_chat_ids("ALLOWED_CHAT_IDS")
    admin_chat_id = int(_require_env("ADMIN_CHAT_ID"))

    local_timezone = ZoneInfo(_require_env("LOCAL_TIMEZONE"))
    keywords = _get_list("KEYWORDS")
    mention_text = os.getenv("MENTION_TEXT", "@poznik").strip()
    agenda_time = _get_time("AGENDA_TIME")

    log_level = os.getenv("LOG_LEVEL", "INFO")

    return Settings(
        ews_server=ews_server,
        ews_email=ews_email,
        ews_username=ews_username,
        ews_password=ews_password,
        ews_auth_type=ews_auth_type,
        ews_verify_ssl=ews_verify_ssl,
        update_interval=update_interval,
        appointment_refresh_interval=appointment_refresh_interval,
        appointment_notify_interval=appointment_notify_interval,
        mail_refresh_interval=mail_refresh_interval,
        appointment_bot_token=appointment_bot_token,
        mail_bot_token=mail_bot_token,
        allowed_chat_ids=allowed_chat_ids,
        admin_chat_id=admin_chat_id,
        local_timezone=local_timezone,
        keywords=keywords,
        mention_text=mention_text,
        agenda_time=agenda_time,
        log_level=log_level,
    )
