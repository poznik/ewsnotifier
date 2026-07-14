from __future__ import annotations

from datetime import time as dt_time

import pytest

from notifier.config import ConfigError, load_settings

REQUIRED_ENV = {
    "EWS_SERVER": "mail.example.com",
    "EWS_EMAIL": "user@example.com",
    "EWS_USERNAME": "DOMAIN\\user",
    "EWS_PASSWORD": "secret",
    "UPDATE_INTERVAL": "60",
    "APPOINTMENT_REFRESH_INTERVAL": "30",
    "APPOINTMENT_NOTIFY_INTERVAL": "900",
    "MAIL_REFRESH_INTERVAL": "60",
    "APPOINTMENT_BOT_TOKEN": "123:abc",
    "MAIL_BOT_TOKEN": "456:def",
    "ALLOWED_CHAT_IDS": "111,222",
    "LOCAL_TIMEZONE": "Europe/Moscow",
}

# Set explicitly to "" so that values from a developer's real .env file
# (load_dotenv does not override existing variables) cannot leak into tests.
OPTIONAL_ENV = (
    "EWS_AUTH_TYPE",
    "EWS_VERIFY_SSL",
    "ADMIN_CHAT_ID",
    "KEYWORDS",
    "MENTION_TEXT",
    "AGENDA_TIME",
    "WORKDAY_START",
    "MAIL_LOOKBACK_DAYS",
    "MAIL_FETCH_LIMIT",
    "STATE_FILE",
    "HEALTH_FILE",
    "MASK_PRIVATE_MEETINGS",
    "AUTH_RETRY_INTERVAL",
    "LOG_LEVEL",
)


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for key, value in REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    for key in OPTIONAL_ENV:
        monkeypatch.setenv(key, "")
    return monkeypatch


class TestDefaults:
    def test_full_valid_config(self, env):
        settings = load_settings()
        assert settings.ews_server == "mail.example.com"
        assert settings.allowed_chat_ids == frozenset({111, 222})
        assert settings.ews_auth_type == "NTLM"
        assert settings.ews_verify_ssl is True
        assert settings.mention_text == ""
        assert settings.agenda_time is None
        assert settings.workday_start == dt_time(9, 0)
        assert settings.mail_lookback_days == 7
        assert settings.mail_fetch_limit == 100
        assert settings.auth_retry_interval == 1800
        assert settings.state_file == "state.json"
        assert settings.log_level == "INFO"
        assert settings.mask_private_meetings is False

    def test_admin_chat_defaults_to_allowed_chats(self, env):
        settings = load_settings()
        assert settings.admin_chat_id is None
        assert settings.alert_chat_ids == settings.allowed_chat_ids

    def test_admin_chat_override(self, env):
        env.setenv("ADMIN_CHAT_ID", "999")
        settings = load_settings()
        assert settings.admin_chat_id == 999
        assert settings.alert_chat_ids == frozenset({999})


class TestParsing:
    def test_log_level_lowercase_accepted(self, env):
        env.setenv("LOG_LEVEL", "info")
        assert load_settings().log_level == "INFO"

    def test_auth_type_lowercase_accepted(self, env):
        env.setenv("EWS_AUTH_TYPE", "basic")
        assert load_settings().ews_auth_type == "BASIC"

    def test_agenda_time_parsed(self, env):
        env.setenv("AGENDA_TIME", "06:10")
        assert load_settings().agenda_time == dt_time(6, 10)

    def test_workday_start_parsed(self, env):
        env.setenv("WORKDAY_START", "08:30")
        assert load_settings().workday_start == dt_time(8, 30)

    def test_keywords_parsed(self, env):
        env.setenv("KEYWORDS", "срочно, asap ,,")
        assert load_settings().keywords == ["срочно", "asap"]

    def test_backslash_kept_verbatim(self, env):
        # .env values are literal: a single backslash must stay single (G3)
        settings = load_settings()
        assert settings.ews_username == "DOMAIN\\user"


class TestValidation:
    def test_zero_interval_rejected(self, env):
        env.setenv("UPDATE_INTERVAL", "0")
        with pytest.raises(ConfigError, match="UPDATE_INTERVAL"):
            load_settings()

    def test_bad_log_level_rejected(self, env):
        env.setenv("LOG_LEVEL", "verbose")
        with pytest.raises(ConfigError, match="LOG_LEVEL"):
            load_settings()

    def test_bad_auth_type_rejected(self, env):
        env.setenv("EWS_AUTH_TYPE", "KERBEROS")
        with pytest.raises(ConfigError, match="EWS_AUTH_TYPE"):
            load_settings()

    def test_bad_agenda_time_rejected(self, env):
        env.setenv("AGENDA_TIME", "6:70")
        with pytest.raises(ConfigError, match="AGENDA_TIME"):
            load_settings()

    def test_bad_timezone_rejected(self, env):
        env.setenv("LOCAL_TIMEZONE", "Nowhere/Land")
        with pytest.raises(ConfigError, match="LOCAL_TIMEZONE"):
            load_settings()

    def test_missing_required_named(self, env):
        env.setenv("EWS_SERVER", "")
        with pytest.raises(ConfigError, match="EWS_SERVER"):
            load_settings()

    def test_errors_are_aggregated(self, env):
        env.setenv("UPDATE_INTERVAL", "abc")
        env.setenv("ALLOWED_CHAT_IDS", "111,oops")
        env.setenv("LOCAL_TIMEZONE", "Nowhere/Land")
        with pytest.raises(ConfigError) as excinfo:
            load_settings()
        message = str(excinfo.value)
        assert "UPDATE_INTERVAL" in message
        assert "ALLOWED_CHAT_IDS" in message
        assert "LOCAL_TIMEZONE" in message
