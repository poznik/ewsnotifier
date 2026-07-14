from __future__ import annotations

import asyncio

import pytest
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut

import notifier.delivery as delivery
from notifier.delivery import SendResult, send_to_chat, send_to_chats

from .conftest import make_settings


class FakeBot:
    """Yields the given outcomes (exception => raise) per send call."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls: list[dict] = []
        self.photo_calls: list[dict] = []

    def _next(self):
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
        return None

    async def send_message(self, **kwargs):
        self.calls.append(kwargs)
        return self._next()

    async def send_photo(self, **kwargs):
        self.photo_calls.append(kwargs)
        return self._next()


@pytest.fixture
def no_sleep(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(delivery.asyncio, "sleep", fake_sleep)
    return sleeps


class TestErrorClassification:
    def test_bad_request_is_permanent_and_not_retried(self, no_sleep):
        bot = FakeBot([BadRequest("can't parse entities")])
        result = asyncio.run(send_to_chat(bot, 1, "text"))
        assert result is SendResult.PERMANENT_FAILURE
        assert len(bot.calls) == 1  # инверсия из B1 исправлена: без ретраев

    def test_forbidden_is_permanent(self, no_sleep):
        bot = FakeBot([Forbidden("bot was blocked")])
        result = asyncio.run(send_to_chat(bot, 1, "text"))
        assert result is SendResult.PERMANENT_FAILURE
        assert len(bot.calls) == 1

    def test_retry_after_is_waited_and_retried(self, no_sleep):
        bot = FakeBot([RetryAfter(3), None])
        result = asyncio.run(send_to_chat(bot, 1, "text"))
        assert result is SendResult.DELIVERED
        assert len(bot.calls) == 2
        assert any(s >= 3 for s in no_sleep)

    def test_network_errors_retried_then_transient(self, no_sleep):
        bot = FakeBot([TimedOut(), TimedOut(), TimedOut()])
        result = asyncio.run(send_to_chat(bot, 1, "text"))
        assert result is SendResult.TRANSIENT_FAILURE
        assert len(bot.calls) == delivery.NETWORK_RETRIES

    def test_network_error_then_success(self, no_sleep):
        bot = FakeBot([NetworkError("boom"), None])
        result = asyncio.run(send_to_chat(bot, 1, "text"))
        assert result is SendResult.DELIVERED
        assert len(bot.calls) == 2

    def test_unexpected_error_is_permanent(self, no_sleep):
        bot = FakeBot([RuntimeError("?")])
        result = asyncio.run(send_to_chat(bot, 1, "text"))
        assert result is SendResult.PERMANENT_FAILURE


class TestAggregation:
    def test_delivered_if_any_chat_succeeds(self, no_sleep):
        bot = FakeBot([Forbidden("blocked"), None])
        result = asyncio.run(send_to_chats(bot, [1, 2], "text"))
        assert result is SendResult.DELIVERED

    def test_permanent_if_all_permanent(self, no_sleep):
        bot = FakeBot([Forbidden("blocked"), BadRequest("bad")])
        result = asyncio.run(send_to_chats(bot, [1, 2], "text"))
        assert result is SendResult.PERMANENT_FAILURE

    def test_transient_wins_over_permanent(self, no_sleep):
        bot = FakeBot([Forbidden("blocked"), TimedOut(), TimedOut(), TimedOut()])
        result = asyncio.run(send_to_chats(bot, [1, 2], "text"))
        assert result is SendResult.TRANSIENT_FAILURE

    def test_empty_chat_list(self, no_sleep):
        bot = FakeBot([])
        result = asyncio.run(send_to_chats(bot, [], "text"))
        assert result is SendResult.PERMANENT_FAILURE
        assert bot.calls == []


class TestChunking:
    def test_long_message_sent_in_chunks_markup_on_last(self, no_sleep):
        bot = FakeBot([])
        text = "\n".join("строка " + "x" * 100 for _ in range(80))
        markup = object()
        result = asyncio.run(send_to_chat(bot, 1, text, reply_markup=markup))
        assert result is SendResult.DELIVERED
        assert len(bot.calls) >= 2
        assert all(call["reply_markup"] is None for call in bot.calls[:-1])
        assert bot.calls[-1]["reply_markup"] is markup


class TestPhoto:
    def test_photo_sent_with_caption_to_every_chat(self, no_sleep):
        bot = FakeBot([])
        asyncio.run(
            delivery.send_photo_to_chats_persistent(bot, [1, 2], b"\x89PNG", caption="сводка")
        )
        assert [call["chat_id"] for call in bot.photo_calls] == [1, 2]
        assert all(call["photo"] == b"\x89PNG" for call in bot.photo_calls)
        assert all(call["caption"] == "сводка" for call in bot.photo_calls)

    def test_photo_flood_control_is_waited_out(self, no_sleep):
        bot = FakeBot([RetryAfter(3), None])
        asyncio.run(delivery.send_photo_to_chats_persistent(bot, [1], b"png", caption="c"))
        assert len(bot.photo_calls) == 2
        assert any(s >= 3 for s in no_sleep)

    def test_photo_rejected_by_telegram_is_not_retried(self, no_sleep):
        bot = FakeBot([BadRequest("PHOTO_INVALID_DIMENSIONS")])
        asyncio.run(delivery.send_photo_to_chats_persistent(bot, [1], b"png", caption="c"))
        assert len(bot.photo_calls) == 1

    def test_photo_transient_failure_is_retried_across_attempts(self, no_sleep):
        # one whole send_to_chat worth of network failures, then success
        outcomes = [TimedOut()] * delivery.NETWORK_RETRIES + [None]
        bot = FakeBot(outcomes)
        asyncio.run(delivery.send_photo_to_chats_persistent(bot, [1], b"png"))
        assert len(bot.photo_calls) == delivery.NETWORK_RETRIES + 1


class TestAdminAlert:
    def test_alert_goes_to_allowed_chats_by_default(self, no_sleep):
        settings = make_settings()
        bot = FakeBot([])
        asyncio.run(delivery.send_admin_alert(bot, settings, "тест"))
        assert {call["chat_id"] for call in bot.calls} == set(settings.allowed_chat_ids)

    def test_alert_goes_to_admin_chat_when_set(self, no_sleep):
        settings = make_settings(admin_chat_id=999)
        bot = FakeBot([])
        asyncio.run(delivery.send_admin_alert(bot, settings, "тест"))
        assert [call["chat_id"] for call in bot.calls] == [999]

    def test_alert_never_raises(self, no_sleep):
        settings = make_settings(admin_chat_id=999)
        bot = FakeBot([RuntimeError("x")])
        asyncio.run(delivery.send_admin_alert(bot, settings, "тест"))
