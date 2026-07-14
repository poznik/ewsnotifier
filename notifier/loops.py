"""Background loops: Exchange refresh, notifications, daily agenda."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from notifier.cache import Cache
from notifier.config import Settings
from notifier.delivery import (
    SendResult,
    send_admin_alert,
    send_to_chats,
    send_to_chats_persistent,
)
from notifier.ews_client import EwsClient
from notifier.formatting import (
    build_check_list,
    build_mail_message,
    build_meeting_message,
    build_today_list,
)
from notifier.models import MailItem, Meeting
from notifier.state import StateStore

AGENDA_POLL_INTERVAL = 30
# One alert (not one per interval) after this many consecutive refresh failures.
UPDATE_FAILURE_ALERT_THRESHOLD = 10
# Keep pruned mail ids a bit longer than the fetch window so that an email
# briefly toggled read/unread is not re-notified.
MAIL_PRUNE_GRACE = timedelta(days=3)


def _brief(exc: BaseException, limit: int = 200) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _touch_health_marker(path: str) -> None:
    """Freshness marker for the Docker HEALTHCHECK (audit finding E3)."""
    try:
        with open(path, "a", encoding="utf-8"):
            pass
        os.utime(path, None)
    except OSError:
        pass


async def update_loop(
    settings: Settings,
    cache: Cache,
    bot: Bot,
    ews_client: EwsClient,
    ready_event: asyncio.Event,
    store: StateStore,
) -> None:
    logger = logging.getLogger("notifier.update")
    mail_max_age = timedelta(days=settings.mail_lookback_days) + MAIL_PRUNE_GRACE
    auth_alert_sent = False
    consecutive_failures = 0

    while True:
        async with cache.lock:
            previous_mail_ids = set(cache.mail.keys())
            previous_meetings = dict(cache.meetings)

        now_local = datetime.now(settings.local_timezone)
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)
        start_utc = start_local.astimezone(UTC)
        end_utc = end_local.astimezone(UTC)

        logger.debug("Refreshing data from Exchange")
        try:
            snapshot = await asyncio.to_thread(ews_client.fetch_snapshot, start_utc, end_utc)
        except Exception as exc:
            if ews_client.is_auth_error(exc):
                logger.critical(
                    "Exchange authentication failed, retrying in %s s: %s",
                    settings.auth_retry_interval,
                    exc,
                )
                if not auth_alert_sent:
                    auth_alert_sent = True
                    await send_admin_alert(
                        bot,
                        settings,
                        "⚠️ Ошибка авторизации в Exchange.\n"
                        f"{_brief(exc)}\n"
                        "Проверьте EWS_USERNAME / EWS_PASSWORD. "
                        f"Повторная попытка каждые {settings.auth_retry_interval // 60} мин.",
                    )
                await asyncio.sleep(settings.auth_retry_interval)
            else:
                consecutive_failures += 1
                logger.exception("Exchange update failed (%s in a row)", consecutive_failures)
                if consecutive_failures == UPDATE_FAILURE_ALERT_THRESHOLD:
                    await send_admin_alert(
                        bot,
                        settings,
                        "⚠️ Обновление данных из Exchange не удаётся "
                        f"уже {consecutive_failures} раз подряд.\n"
                        f"{_brief(exc)}\n"
                        "Продолжаю попытки.",
                    )
                await asyncio.sleep(settings.update_interval)
            continue

        if auth_alert_sent:
            auth_alert_sent = False
            await send_admin_alert(bot, settings, "✅ Доступ к Exchange восстановлен.")
        if consecutive_failures >= UPDATE_FAILURE_ALERT_THRESHOLD:
            await send_admin_alert(
                bot, settings, "✅ Обновление данных из Exchange снова работает."
            )
        consecutive_failures = 0

        now_utc = datetime.now(UTC)
        future_meetings = [meeting for meeting in snapshot.meetings if meeting.start_utc > now_utc]
        next_minutes: int | None = None
        if future_meetings:
            nearest_start = min(meeting.start_utc for meeting in future_meetings)
            next_minutes = max(0, int((nearest_start - now_utc).total_seconds() // 60))
        new_unread_mail = sum(1 for mail in snapshot.mails if mail.id not in previous_mail_ids)

        async with cache.lock:
            state = cache.state
            for meeting in snapshot.meetings:
                previous = previous_meetings.get(meeting.id)
                if (
                    previous
                    and meeting.id in state.notified_meetings
                    and meeting.start_utc != previous.start_utc
                ):
                    # Rescheduled in either direction -> notify again (C3).
                    state.notified_meetings.discard(meeting.id)

            current_meeting_ids = {meeting.id for meeting in snapshot.meetings}
            state.notified_meetings.intersection_update(current_meeting_ids)
            cache.meetings = {meeting.id: meeting for meeting in snapshot.meetings}
            cache.mail = {mail.id: mail for mail in snapshot.mails}

            if not state.mail_baseline_done:
                # First run ever (or fresh state file): existing unread mail is
                # backlog, not news — do not flood the chats (A3).
                stamp = datetime.now(UTC)
                for mail in snapshot.mails:
                    state.notified_mail.setdefault(mail.id, stamp)
                state.mail_baseline_done = True
                if snapshot.mails:
                    logger.info(
                        "First run: marked %s existing unread email(s) as already notified",
                        len(snapshot.mails),
                    )

            state.prune_mail(set(cache.mail.keys()), mail_max_age)
            store.save(state)

        _touch_health_marker(settings.health_file)

        if not ready_event.is_set():
            logger.info(
                "Initial Exchange snapshot loaded: %s meeting(s) today, %s unread email(s)",
                len(snapshot.meetings),
                len(snapshot.mails),
            )
            ready_event.set()

        logger.debug(
            "Refresh done: %s upcoming meeting(s), next in %s min, %s new unread email(s)",
            len(future_meetings),
            next_minutes if next_minutes is not None else "-",
            new_unread_mail,
        )

        await asyncio.sleep(settings.update_interval)


async def appointment_notify_loop(
    settings: Settings,
    cache: Cache,
    bot: Bot,
    ready_event: asyncio.Event,
    store: StateStore,
) -> None:
    logger = logging.getLogger("notifier.appointment")
    notify_delta = timedelta(seconds=settings.appointment_notify_interval)

    await ready_event.wait()

    while True:
        now = datetime.now(UTC)
        due_meetings: list[Meeting] = []

        async with cache.lock:
            for meeting in cache.meetings.values():
                if meeting.is_all_day:
                    continue
                if meeting.id in cache.state.notified_meetings:
                    continue
                if meeting.start_utc < now:
                    continue
                if meeting.start_utc <= now + notify_delta:
                    due_meetings.append(meeting)

        if due_meetings:
            logger.info("Sending %s meeting notification(s)", len(due_meetings))
        else:
            logger.debug("No meeting notifications due")

        state_changed = False
        for meeting in due_meetings:
            try:
                message = build_meeting_message(meeting, settings, now_utc=now)
                reply_markup = None
                if meeting.join_url:
                    reply_markup = InlineKeyboardMarkup(
                        [[InlineKeyboardButton("Подключиться", url=meeting.join_url)]]
                    )
                result = await send_to_chats(
                    bot,
                    settings.allowed_chat_ids,
                    message,
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=reply_markup,
                )
            except Exception:
                logger.exception("Failed to send meeting notification")
                result = SendResult.PERMANENT_FAILURE
            # Mark as notified only after the send attempt (B2). Transient
            # failures stay unmarked and are retried on the next tick.
            if result is not SendResult.TRANSIENT_FAILURE:
                async with cache.lock:
                    cache.state.notified_meetings.add(meeting.id)
                state_changed = True

        if state_changed:
            async with cache.lock:
                store.save(cache.state)

        await asyncio.sleep(settings.appointment_refresh_interval)


async def mail_notify_loop(
    settings: Settings,
    cache: Cache,
    bot: Bot,
    ready_event: asyncio.Event,
    store: StateStore,
) -> None:
    logger = logging.getLogger("notifier.mail")
    await ready_event.wait()

    while True:
        async with cache.lock:
            pending: list[MailItem] = sorted(
                (mail for mail in cache.mail.values() if mail.id not in cache.state.notified_mail),
                key=lambda mail: mail.sent_utc,  # oldest first (C9)
            )

        if pending:
            logger.info("Sending %s mail notification(s)", len(pending))
        else:
            logger.debug("No mail notifications due")

        state_changed = False
        for mail in pending:
            try:
                message = build_mail_message(mail, settings)
                result = await send_to_chats(
                    bot,
                    settings.allowed_chat_ids,
                    message,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            except Exception:
                logger.exception("Failed to send mail notification")
                result = SendResult.PERMANENT_FAILURE
            if result is not SendResult.TRANSIENT_FAILURE:
                async with cache.lock:
                    cache.state.notified_mail[mail.id] = datetime.now(UTC)
                state_changed = True

        if state_changed:
            async with cache.lock:
                store.save(cache.state)

        await asyncio.sleep(settings.mail_refresh_interval)


async def agenda_loop(
    settings: Settings,
    cache: Cache,
    bot: Bot,
    ready_event: asyncio.Event,
    store: StateStore,
) -> None:
    if settings.agenda_time is None:
        return

    logger = logging.getLogger("notifier.agenda")

    await ready_event.wait()

    async with cache.lock:
        if cache.state.agenda_last_sent is None:
            now_local = datetime.now(settings.local_timezone)
            if now_local.time() >= settings.agenda_time:
                # Fresh state and we are already past today's agenda time:
                # a restart must not fire a late agenda (A4).
                cache.state.agenda_last_sent = now_local.date()
                store.save(cache.state)

    while True:
        now_local = datetime.now(settings.local_timezone)
        if now_local.weekday() < 5:
            async with cache.lock:
                already_sent = cache.state.agenda_last_sent == now_local.date()
                meetings = list(cache.meetings.values())
            if not already_sent and now_local.time() >= settings.agenda_time:
                logger.info("Sending daily agenda for %s", now_local.strftime("%d.%m.%Y"))
                today_text = build_today_list(meetings, settings)
                check_text = build_check_list(meetings, settings)

                await send_to_chats_persistent(
                    bot,
                    settings.allowed_chat_ids,
                    today_text,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
                await send_to_chats_persistent(
                    bot,
                    settings.allowed_chat_ids,
                    check_text,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
                async with cache.lock:
                    cache.state.agenda_last_sent = now_local.date()
                    store.save(cache.state)

        await asyncio.sleep(AGENDA_POLL_INTERVAL)
