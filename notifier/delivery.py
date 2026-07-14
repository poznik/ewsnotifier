"""Sending messages to Telegram with error-class-aware retries.

python-telegram-bot's exception hierarchy is counter-intuitive (audit
finding B1): ``BadRequest`` inherits from ``NetworkError`` although it is
permanent, while ``RetryAfter`` — the one error that explicitly asks for a
retry — does not. This module classifies errors explicitly:

- ``RetryAfter``: wait the announced time, then retry;
- ``Forbidden`` / ``BadRequest``: permanent, never retried;
- ``TimedOut`` / other ``NetworkError``: transient, retried with backoff.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from datetime import timedelta
from enum import Enum

from telegram import Bot, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut

from notifier.config import Settings
from notifier.formatting import split_message

_LOGGER = logging.getLogger("notifier.telegram")

NETWORK_RETRIES = 3
NETWORK_RETRY_BASE_DELAY = 1.0
RATE_LIMIT_RETRIES = 5
PERSISTENT_MAX_ATTEMPTS = 10
PERSISTENT_RETRY_INTERVAL = 60


class SendResult(Enum):
    DELIVERED = "delivered"
    TRANSIENT_FAILURE = "transient"
    PERMANENT_FAILURE = "permanent"


def _retry_after_seconds(exc: RetryAfter) -> float:
    delay = exc.retry_after
    if isinstance(delay, timedelta):
        return delay.total_seconds()
    return float(delay)


async def _send_text(
    bot: Bot,
    chat_id: int,
    text: str,
    parse_mode: ParseMode | None,
    reply_markup: InlineKeyboardMarkup | None,
) -> SendResult:
    network_attempts = 0
    rate_limit_hits = 0
    while True:
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
                disable_web_page_preview=True,
            )
            return SendResult.DELIVERED
        except RetryAfter as exc:
            rate_limit_hits += 1
            if rate_limit_hits > RATE_LIMIT_RETRIES:
                _LOGGER.warning(
                    "Chat %s: still rate-limited after %s waits, giving up for now",
                    chat_id,
                    RATE_LIMIT_RETRIES,
                )
                return SendResult.TRANSIENT_FAILURE
            wait = _retry_after_seconds(exc) + 0.5
            _LOGGER.info("Chat %s: flood control, waiting %.1fs", chat_id, wait)
            await asyncio.sleep(wait)
        except Forbidden as exc:
            _LOGGER.error("Chat %s: bot is blocked or lacks access (%s)", chat_id, exc)
            return SendResult.PERMANENT_FAILURE
        except BadRequest as exc:
            _LOGGER.error("Chat %s: Telegram rejected the message (%s)", chat_id, exc)
            return SendResult.PERMANENT_FAILURE
        except (TimedOut, NetworkError) as exc:
            network_attempts += 1
            if network_attempts >= NETWORK_RETRIES:
                _LOGGER.warning(
                    "Chat %s: network failure after %s attempts (%s)",
                    chat_id,
                    network_attempts,
                    exc,
                )
                return SendResult.TRANSIENT_FAILURE
            await asyncio.sleep(NETWORK_RETRY_BASE_DELAY * (2 ** (network_attempts - 1)))
        except Exception:
            _LOGGER.exception("Chat %s: unexpected error while sending", chat_id)
            return SendResult.PERMANENT_FAILURE


async def send_to_chat(
    bot: Bot,
    chat_id: int,
    text: str,
    parse_mode: ParseMode | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> SendResult:
    chunks = split_message(text)
    for index, chunk in enumerate(chunks):
        markup = reply_markup if index == len(chunks) - 1 else None
        result = await _send_text(bot, chat_id, chunk, parse_mode, markup)
        if result is not SendResult.DELIVERED:
            return result
    return SendResult.DELIVERED


async def send_to_chats(
    bot: Bot,
    chat_ids: Iterable[int],
    text: str,
    parse_mode: ParseMode | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> SendResult:
    """Send to every chat; the aggregate drives notified-state marking (B2).

    DELIVERED as soon as at least one chat received the message,
    TRANSIENT_FAILURE if nothing was delivered but a later retry may help.
    """
    results = [
        await send_to_chat(bot, chat_id, text, parse_mode, reply_markup) for chat_id in chat_ids
    ]
    if not results:
        return SendResult.PERMANENT_FAILURE
    if any(result is SendResult.DELIVERED for result in results):
        return SendResult.DELIVERED
    if any(result is SendResult.TRANSIENT_FAILURE for result in results):
        return SendResult.TRANSIENT_FAILURE
    return SendResult.PERMANENT_FAILURE


async def send_to_chats_persistent(
    bot: Bot,
    chat_ids: Iterable[int],
    text: str,
    parse_mode: ParseMode | None = None,
) -> None:
    """Retry transient failures for a long time (daily agenda, finding B3).

    Permanent failures are not retried: a message Telegram already rejected
    will not become valid on the eleventh attempt.
    """
    for chat_id in chat_ids:
        for attempt in range(1, PERSISTENT_MAX_ATTEMPTS + 1):
            result = await send_to_chat(bot, chat_id, text, parse_mode, None)
            if result is not SendResult.TRANSIENT_FAILURE:
                break
            if attempt < PERSISTENT_MAX_ATTEMPTS:
                _LOGGER.warning(
                    "Chat %s: attempt %s/%s failed, retrying in %ss",
                    chat_id,
                    attempt,
                    PERSISTENT_MAX_ATTEMPTS,
                    PERSISTENT_RETRY_INTERVAL,
                )
                await asyncio.sleep(PERSISTENT_RETRY_INTERVAL)
        else:
            _LOGGER.warning(
                "Chat %s: giving up after %s attempts",
                chat_id,
                PERSISTENT_MAX_ATTEMPTS,
            )


async def send_admin_alert(bot: Bot, settings: Settings, text: str) -> None:
    """Best-effort operational alert (audit finding A2).

    Goes to ADMIN_CHAT_ID when configured, otherwise to the same chats
    that receive meeting notifications. Plain text on purpose: alert
    bodies contain arbitrary error strings.
    """
    try:
        await send_to_chats(bot, settings.alert_chat_ids, text)
    except Exception:
        _LOGGER.exception("Failed to send admin alert")
