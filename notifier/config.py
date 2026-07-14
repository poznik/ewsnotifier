from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time as dt_time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

_VALID_AUTH_TYPES = ("NTLM", "BASIC", "DIGEST")
_VALID_LOG_LEVELS = ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG")
_VALID_AGENDA_FORMATS = ("image", "text")


class ConfigError(ValueError):
    """One or more configuration values are missing or invalid."""


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
    allowed_chat_ids: frozenset[int]
    admin_chat_id: int | None
    local_timezone: ZoneInfo
    keywords: list[str]
    mention_text: str
    agenda_time: dt_time | None
    agenda_format: str
    workday_start: dt_time
    mail_lookback_days: int
    mail_fetch_limit: int
    state_file: str
    health_file: str
    mask_private_meetings: bool
    auth_retry_interval: int
    log_level: str

    @property
    def alert_chat_ids(self) -> frozenset[int]:
        """Where operational alerts go: ADMIN_CHAT_ID if set, else the
        same chats that receive meeting notifications."""
        if self.admin_chat_id is not None:
            return frozenset({self.admin_chat_id})
        return self.allowed_chat_ids


def _require_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or value == "":
        raise ValueError(f"{name} is required")
    return value


def _get_int(name: str, default: int | None = None, minimum: int = 1) -> int:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        if default is None:
            raise ValueError(f"{name} is required")
        return default
    try:
        parsed = int(value)
    except ValueError:
        raise ValueError(f"{name}: expected an integer, got {value!r}") from None
    if parsed < minimum:
        raise ValueError(f"{name}: must be >= {minimum}, got {parsed}")
    return parsed


def _get_bool(name: str, default: bool = True) -> bool:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_list(name: str) -> list[str]:
    value = os.getenv(name, "")
    if value == "":
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_chat_ids(name: str) -> frozenset[int]:
    raw = _get_list(name)
    if not raw:
        raise ValueError(f"{name} is required (comma-separated chat ids)")
    ids = []
    for item in raw:
        try:
            ids.append(int(item))
        except ValueError:
            raise ValueError(f"{name}: {item!r} is not a valid chat id") from None
    return frozenset(ids)


def _get_time(name: str, default: dt_time | None = None) -> dt_time | None:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(f"{name}: expected HH:MM, got {value!r}")
    try:
        hour, minute = (int(part) for part in parts)
    except ValueError:
        raise ValueError(f"{name}: expected HH:MM, got {value!r}") from None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"{name}: expected HH:MM, got {value!r}")
    return dt_time(hour=hour, minute=minute)


def _get_auth_type() -> str:
    value = (os.getenv("EWS_AUTH_TYPE") or "NTLM").strip().upper()
    if value not in _VALID_AUTH_TYPES:
        raise ValueError(
            f"EWS_AUTH_TYPE: expected one of {', '.join(_VALID_AUTH_TYPES)}, got {value!r}"
        )
    return value


def _get_agenda_format() -> str:
    value = (os.getenv("AGENDA_FORMAT") or "image").strip().lower()
    if value not in _VALID_AGENDA_FORMATS:
        raise ValueError(
            f"AGENDA_FORMAT: expected one of {', '.join(_VALID_AGENDA_FORMATS)}, got {value!r}"
        )
    return value


def _get_log_level() -> str:
    value = (os.getenv("LOG_LEVEL") or "INFO").strip().upper()
    if value not in _VALID_LOG_LEVELS:
        raise ValueError(
            f"LOG_LEVEL: expected one of {', '.join(_VALID_LOG_LEVELS)}, got {value!r}"
        )
    return value


def _get_timezone() -> ZoneInfo:
    name = _require_env("LOCAL_TIMEZONE")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(
            f"LOCAL_TIMEZONE: unknown IANA timezone {name!r} (example: Europe/Moscow)"
        ) from None


def _get_admin_chat_id() -> int | None:
    raw = os.getenv("ADMIN_CHAT_ID", "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"ADMIN_CHAT_ID: {raw!r} is not a valid chat id") from None


def load_settings() -> Settings:
    load_dotenv(override=False)

    errors: list[str] = []
    values: dict[str, object] = {}

    def collect(key: str, loader, *args, **kwargs) -> None:
        try:
            values[key] = loader(*args, **kwargs)
        except ValueError as exc:
            errors.append(str(exc))

    collect("ews_server", _require_env, "EWS_SERVER")
    collect("ews_email", _require_env, "EWS_EMAIL")
    collect("ews_username", _require_env, "EWS_USERNAME")
    collect("ews_password", _require_env, "EWS_PASSWORD")
    collect("ews_auth_type", _get_auth_type)
    collect("update_interval", _get_int, "UPDATE_INTERVAL")
    collect("appointment_refresh_interval", _get_int, "APPOINTMENT_REFRESH_INTERVAL")
    collect("appointment_notify_interval", _get_int, "APPOINTMENT_NOTIFY_INTERVAL")
    collect("mail_refresh_interval", _get_int, "MAIL_REFRESH_INTERVAL")
    collect("appointment_bot_token", _require_env, "APPOINTMENT_BOT_TOKEN")
    collect("mail_bot_token", _require_env, "MAIL_BOT_TOKEN")
    collect("allowed_chat_ids", _parse_chat_ids, "ALLOWED_CHAT_IDS")
    collect("admin_chat_id", _get_admin_chat_id)
    collect("local_timezone", _get_timezone)
    collect("agenda_time", _get_time, "AGENDA_TIME")
    collect("agenda_format", _get_agenda_format)
    collect("workday_start", _get_time, "WORKDAY_START", dt_time(hour=9, minute=0))
    collect("mail_lookback_days", _get_int, "MAIL_LOOKBACK_DAYS", 7)
    collect("mail_fetch_limit", _get_int, "MAIL_FETCH_LIMIT", 100)
    collect("auth_retry_interval", _get_int, "AUTH_RETRY_INTERVAL", 1800)
    collect("log_level", _get_log_level)

    if errors:
        raise ConfigError("configuration errors:\n  - " + "\n  - ".join(errors))

    return Settings(
        ews_server=str(values["ews_server"]),
        ews_email=str(values["ews_email"]),
        ews_username=str(values["ews_username"]),
        ews_password=str(values["ews_password"]),
        ews_auth_type=str(values["ews_auth_type"]),
        ews_verify_ssl=_get_bool("EWS_VERIFY_SSL", True),
        update_interval=values["update_interval"],  # type: ignore[arg-type]
        appointment_refresh_interval=values["appointment_refresh_interval"],  # type: ignore[arg-type]
        appointment_notify_interval=values["appointment_notify_interval"],  # type: ignore[arg-type]
        mail_refresh_interval=values["mail_refresh_interval"],  # type: ignore[arg-type]
        appointment_bot_token=str(values["appointment_bot_token"]),
        mail_bot_token=str(values["mail_bot_token"]),
        allowed_chat_ids=values["allowed_chat_ids"],  # type: ignore[arg-type]
        admin_chat_id=values["admin_chat_id"],  # type: ignore[arg-type]
        local_timezone=values["local_timezone"],  # type: ignore[arg-type]
        keywords=_get_list("KEYWORDS"),
        mention_text=os.getenv("MENTION_TEXT", "").strip(),
        agenda_time=values["agenda_time"],  # type: ignore[arg-type]
        agenda_format=str(values["agenda_format"]),
        workday_start=values["workday_start"],  # type: ignore[arg-type]
        mail_lookback_days=values["mail_lookback_days"],  # type: ignore[arg-type]
        mail_fetch_limit=values["mail_fetch_limit"],  # type: ignore[arg-type]
        state_file=os.getenv("STATE_FILE", "state.json").strip() or "state.json",
        health_file=os.getenv("HEALTH_FILE", "/tmp/notifier-healthy").strip()
        or "/tmp/notifier-healthy",
        mask_private_meetings=_get_bool("MASK_PRIVATE_MEETINGS", False),
        auth_retry_interval=values["auth_retry_interval"],  # type: ignore[arg-type]
        log_level=str(values["log_level"]),
    )
