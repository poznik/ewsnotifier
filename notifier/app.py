from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import signal
from typing import Iterable, List

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import NetworkError, TimedOut
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes
from telegram.request import HTTPXRequest

from notifier.cache import Cache
from notifier.config import Settings, load_settings
from notifier.ews_client import EwsClient
from notifier.models import Meeting, MailItem
from notifier.utils import (
    contains_keyword,
    escape_markdown_v2,
    format_duration,
    format_local_dt,
    format_markdown_quote,
)

TELEGRAM_CONNECT_TIMEOUT = 10
TELEGRAM_READ_TIMEOUT = 30
TELEGRAM_WRITE_TIMEOUT = 30
TELEGRAM_POOL_TIMEOUT = 30
TELEGRAM_SEND_RETRIES = 3
TELEGRAM_RETRY_BASE_DELAY = 1.0
AGENDA_MAX_ATTEMPTS = 10
AGENDA_SEND_INTERVAL = 60
AGENDA_POLL_INTERVAL = 30


async def send_to_chats(
    bot: Bot,
    chat_ids: Iterable[int],
    text: str,
    parse_mode: ParseMode | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    logger = logging.getLogger("notifier.telegram")
    for chat_id in chat_ids:
        delay = TELEGRAM_RETRY_BASE_DELAY
        for attempt in range(TELEGRAM_SEND_RETRIES):
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                    disable_web_page_preview=True,
                )
                break
            except (TimedOut, NetworkError):
                if attempt < TELEGRAM_SEND_RETRIES - 1:
                    await asyncio.sleep(delay)
                    delay *= 2
                    continue
                logger.warning(
                    "Timeout отправки сообщения в чат %s после %s попыток",
                    chat_id,
                    TELEGRAM_SEND_RETRIES,
                )
            except Exception:
                logger.exception("Failed to send message to chat %s", chat_id)
            break


async def send_to_chats_until_success(
    bot: Bot,
    chat_ids: Iterable[int],
    text: str,
    parse_mode: ParseMode | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    logger = logging.getLogger("notifier.telegram")
    for chat_id in chat_ids:
        attempt = 0
        while attempt < AGENDA_MAX_ATTEMPTS:
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    parse_mode=parse_mode,
                    reply_markup=reply_markup,
                    disable_web_page_preview=True,
                )
                break
            except Exception:
                attempt += 1
                logger.warning(
                    "Не удалось отправить сообщение в чат %s, попытка %s, повтор через %s сек",
                    chat_id,
                    attempt,
                    AGENDA_SEND_INTERVAL,
                    exc_info=True,
                )
                if attempt < AGENDA_MAX_ATTEMPTS:
                    await asyncio.sleep(AGENDA_SEND_INTERVAL)
        if attempt >= AGENDA_MAX_ATTEMPTS:
            logger.warning(
                "Превышен лимит попыток отправки сообщения в чат %s (%s)",
                chat_id,
                AGENDA_MAX_ATTEMPTS,
            )


def build_meeting_message(
    meeting: Meeting, settings: Settings, now_utc: datetime | None = None
) -> str:
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    minutes_to = max(0, int((meeting.start_utc - now_utc).total_seconds() // 60))

    subject = escape_markdown_v2(meeting.subject)
    organizer_raw = meeting.organizer or "-"
    organizer = escape_markdown_v2(organizer_raw)
    start_local_dt = meeting.start_utc.astimezone(settings.local_timezone)
    start_local = escape_markdown_v2(start_local_dt.strftime("%d.%m.%Y %H:%M"))
    duration_minutes = max(
        0, int((meeting.end_utc - meeting.start_utc).total_seconds() // 60)
    )
    duration = escape_markdown_v2(f"{duration_minutes} минут")
    header = f"🔔 Через {minutes_to} мин: {subject}"
    lines = [
        f"*{header}*",
        f"Организатор: *{organizer}*",
        f"Начало: {start_local}",
        f"Длительность: {duration}",
    ]
    location_value = (meeting.location or "").strip()
    if meeting.join_url:
        link_text = escape_markdown_v2(meeting.join_url)
        lines.append(f"Ссылка: {link_text}")
    elif location_value:
        place_text = escape_markdown_v2(location_value)
        lines.append(f"Место: {place_text}")
    return "\n".join(lines)


def build_mail_message(mail: MailItem, settings: Settings) -> str:
    subject_raw = mail.subject or "(без темы)"
    sender_raw = mail.sender or "-"
    sent_raw = format_local_dt(mail.sent_utc, settings.local_timezone, with_date=True)
    preview_raw = mail.preview or ""

    needs_mention = contains_keyword(
        f"{subject_raw}\n{sender_raw}\n{preview_raw}", settings.keywords
    )
    mention_text = settings.mention_text.strip()

    subject = escape_markdown_v2(subject_raw)
    sender = escape_markdown_v2(sender_raw)
    sent = escape_markdown_v2(sent_raw)
    preview = format_markdown_quote(preview_raw)

    if preview:
        message = (
            f"*{subject}*\n"
            f"От: : {sender}\n"
            f"Отправлено: {sent}\n\n"
            f"{preview}"
        )
    else:
        message = (
            f"*{subject}*\n"
            f"От: {sender}\n"
            f"Отправлено: {sent}"
        )
    if needs_mention:
        if mention_text:
            message = f"‼️{message}\n{escape_markdown_v2(mention_text)}"
        else:
            message = f"‼️{message}"
    return message


def build_today_list(meetings: Iterable[Meeting], settings: Settings) -> str:
    today_local = datetime.now(settings.local_timezone)
    today_text = escape_markdown_v2(today_local.strftime("%d.%m.%Y"))
    header = f"*Сегодня {today_text}*\r\n"
    lines = [header]
    sorted_meetings = sorted(meetings, key=lambda item: item.start_utc)
    if sorted_meetings:
        first_local = sorted_meetings[0].start_utc.astimezone(settings.local_timezone)
        workday_start = first_local.replace(
            hour=9, minute=0, second=0, microsecond=0
        )
        if workday_start < first_local:
            window_start = workday_start.strftime("%H:%M")
            window_duration = format_duration(
                workday_start.astimezone(timezone.utc),
                sorted_meetings[0].start_utc,
            )
            window_rest = f": начало {window_start}, длительность {window_duration}"
            lines.append(f"> *Окно*{escape_markdown_v2(window_rest)}")
    for index, meeting in enumerate(sorted_meetings):
        subject = meeting.subject.replace("\n", " ").strip() or "(без темы)"
        start = format_local_dt(
            meeting.start_utc, settings.local_timezone, with_date=False
        )
        duration = format_duration(meeting.start_utc, meeting.end_utc)
        line_text = f"‣{subject}, {start}, {duration}"
        lines.append(f"{escape_markdown_v2(line_text)}")
        if index < len(sorted_meetings) - 1:
            next_meeting = sorted_meetings[index + 1]
            if meeting.end_utc < next_meeting.start_utc:
                window_start = format_local_dt(
                    meeting.end_utc, settings.local_timezone, with_date=False
                )
                window_duration = format_duration(meeting.end_utc, next_meeting.start_utc)
                window_rest = (
                    f": начало {window_start}, длительность {window_duration}"
                )
                lines.append(f"> *Окно*{escape_markdown_v2(window_rest)}")
    if not lines:
        return escape_markdown_v2("Сегодня встреч нет")
    return "\n".join(lines)


def build_check_list(meetings: Iterable[Meeting], settings: Settings) -> str:
    sorted_meetings = sorted(meetings, key=lambda item: item.start_utc)
    overlaps: List[List[Meeting]] = []

    current_group: List[Meeting] = []
    current_end: datetime | None = None

    for meeting in sorted_meetings:
        if not current_group:
            current_group = [meeting]
            current_end = meeting.end_utc
            continue
        if current_end is not None and meeting.start_utc < current_end:
            current_group.append(meeting)
            if meeting.end_utc > current_end:
                current_end = meeting.end_utc
        else:
            if len(current_group) > 1:
                overlaps.append(current_group)
            current_group = [meeting]
            current_end = meeting.end_utc

    if len(current_group) > 1:
        overlaps.append(current_group)

    def _overlap_minutes(group: List[Meeting]) -> int:
        events: List[tuple[datetime, int]] = []
        for meeting in group:
            if meeting.end_utc <= meeting.start_utc:
                continue
            events.append((meeting.start_utc, 1))
            events.append((meeting.end_utc, -1))
        events.sort(key=lambda item: (item[0], item[1]))

        active = 0
        last_time: datetime | None = None
        overlap_seconds = 0.0
        for moment, delta in events:
            if last_time is not None and active >= 2:
                overlap_seconds += (moment - last_time).total_seconds()
            active += delta
            last_time = moment
        return max(0, int(overlap_seconds // 60))

    header = escape_markdown_v2(f"Всего пересечений: {len(overlaps)}\n")
    lines = [header]

    for index, group in enumerate(overlaps, start=1):
        title = escape_markdown_v2(f"Пересечение {index}:")
        minutes_text = escape_markdown_v2(f"{_overlap_minutes(group)} минут")
        lines.append(f"*{title}* {minutes_text}")
        for meeting in group:
            subject = meeting.subject.replace("\n", " ").strip() or "(без темы)"
            start = format_local_dt(
                meeting.start_utc, settings.local_timezone, with_date=False
            )
            duration = format_duration(meeting.start_utc, meeting.end_utc)
            line_text = f"{subject}, {start}, {duration}"
            lines.append(escape_markdown_v2(line_text))
        if index < len(overlaps):
            lines.append("")

    return "\n".join(lines)


def is_allowed(chat_id: int, allowed_chat_ids: Iterable[int]) -> bool:
    return chat_id in set(allowed_chat_ids)


async def today_handler(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    cache: Cache = context.bot_data["cache"]
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None or not is_allowed(chat_id, settings.allowed_chat_ids):
        return
    if update.message is None:
        return
    async with cache.lock:
        meetings = list(cache.meetings.values())
    text = build_today_list(meetings, settings)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


async def check_handler(update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    cache: Cache = context.bot_data["cache"]
    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id is None or not is_allowed(chat_id, settings.allowed_chat_ids):
        return
    if update.message is None:
        return
    async with cache.lock:
        meetings = list(cache.meetings.values())
    text = build_check_list(meetings, settings)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN_V2)


async def update_loop(
    settings: Settings,
    cache: Cache,
    ews_client: EwsClient,
) -> None:
    logger = logging.getLogger("notifier.update")
    while True:
        async with cache.lock:
            previous_mail_ids = set(cache.mail.keys())
            previous_meetings = dict(cache.meetings)

        now_local = datetime.now(settings.local_timezone)
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)
        start_utc = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)

        logger.info("Начало обновления информации из Exchange")
        try:
            snapshot = await asyncio.to_thread(
                ews_client.fetch_snapshot, start_utc, end_utc
            )
        except Exception as exc:
            if ews_client.is_auth_error(exc):
                logger.exception("Exchange auth failure")
                break
            logger.exception("Exchange update failed")
            await asyncio.sleep(settings.update_interval)
            continue

        now_utc = datetime.now(timezone.utc)
        future_meetings = [
            meeting for meeting in snapshot.meetings if meeting.start_utc > now_utc
        ]
        future_count = len(future_meetings)
        next_minutes: int | None = None
        if future_meetings:
            nearest_start = min(meeting.start_utc for meeting in future_meetings)
            delta = nearest_start - now_utc
            next_minutes = max(0, int(delta.total_seconds() // 60))

        new_unread_mail = sum(
            1 for mail in snapshot.mails if mail.id not in previous_mail_ids
        )

        async with cache.lock:
            for meeting in snapshot.meetings:
                previous_meeting = previous_meetings.get(meeting.id)
                if (
                    previous_meeting
                    and meeting.id in cache.notified_meetings
                    and meeting.start_utc > previous_meeting.start_utc
                ):
                    cache.notified_meetings.discard(meeting.id)

            current_ids = {meeting.id for meeting in snapshot.meetings}
            cache.notified_meetings.intersection_update(current_ids)
            cache.meetings = {meeting.id: meeting for meeting in snapshot.meetings}
            cache.mail = {mail.id: mail for mail in snapshot.mails}

        next_minutes_text = str(next_minutes) if next_minutes is not None else "нет"
        logger.info(
            "Завершено обновление Exchange: будущих встреч %s, до ближайшей %s мин, новых писем %s",
            future_count,
            next_minutes_text,
            new_unread_mail,
        )

        await asyncio.sleep(settings.update_interval)


async def appointment_notify_loop(
    settings: Settings,
    cache: Cache,
    bot: Bot,
) -> None:
    logger = logging.getLogger("notifier.appointment")
    notify_delta = timedelta(seconds=settings.appointment_notify_interval)

    while True:
        now = datetime.now(timezone.utc)
        due_meetings: List[Meeting] = []

        async with cache.lock:
            for meeting in cache.meetings.values():
                if meeting.id in cache.notified_meetings:
                    continue
                if meeting.start_utc < now:
                    continue
                if meeting.start_utc <= now + notify_delta:
                    due_meetings.append(meeting)
                    cache.notified_meetings.add(meeting.id)

        logger.info(
            "Начало оповещения о встречах: %s, следующее через %s сек",
            len(due_meetings),
            settings.appointment_refresh_interval,
        )

        for meeting in due_meetings:
            try:
                message = build_meeting_message(meeting, settings, now_utc=now)
                reply_markup = None
                if meeting.join_url:
                    reply_markup = InlineKeyboardMarkup(
                        [[InlineKeyboardButton("Подключиться", url=meeting.join_url)]]
                    )
                await send_to_chats(
                    bot,
                    settings.allowed_chat_ids,
                    message,
                    parse_mode=ParseMode.MARKDOWN_V2,
                    reply_markup=reply_markup,
                )
            except Exception:
                logger.exception("Failed to send meeting notification")

        await asyncio.sleep(settings.appointment_refresh_interval)


async def mail_notify_loop(
    settings: Settings,
    cache: Cache,
    bot: Bot,
) -> None:
    logger = logging.getLogger("notifier.mail")
    while True:
        new_mail: List[MailItem] = []
        async with cache.lock:
            for mail in cache.mail.values():
                if mail.id in cache.notified_mail:
                    continue
                new_mail.append(mail)
                cache.notified_mail.add(mail.id)

        logger.info(
            "Начало оповещения о почте: %s, следующее через %s сек",
            len(new_mail),
            settings.mail_refresh_interval,
        )

        for mail in new_mail:
            try:
                message = build_mail_message(mail, settings)
                await send_to_chats(
                    bot,
                    settings.allowed_chat_ids,
                    message,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
            except Exception:
                logger.exception("Failed to send mail notification")

        await asyncio.sleep(settings.mail_refresh_interval)


async def agenda_loop(
    settings: Settings,
    cache: Cache,
    bot: Bot,
) -> None:
    if settings.agenda_time is None:
        return

    logger = logging.getLogger("notifier.agenda")
    last_sent_date = None

    while True:
        now_local = datetime.now(settings.local_timezone)
        if now_local.weekday() < 5:
            if (
                last_sent_date != now_local.date()
                and now_local.time() >= settings.agenda_time
            ):
                logger.info(
                    "Отправка ежедневной сводки за %s",
                    now_local.strftime("%d.%m.%Y"),
                )
                async with cache.lock:
                    meetings = list(cache.meetings.values())
                today_text = build_today_list(meetings, settings)
                check_text = build_check_list(meetings, settings)

                await send_to_chats_until_success(
                    bot,
                    settings.allowed_chat_ids,
                    today_text,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
                await send_to_chats_until_success(
                    bot,
                    settings.allowed_chat_ids,
                    check_text,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
                last_sent_date = now_local.date()

        await asyncio.sleep(AGENDA_POLL_INTERVAL)


async def run_async() -> None:
    settings = load_settings()
    logging.basicConfig(level=settings.log_level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    cache = Cache()
    ews_client = EwsClient(settings)

    request = HTTPXRequest(
        connect_timeout=TELEGRAM_CONNECT_TIMEOUT,
        read_timeout=TELEGRAM_READ_TIMEOUT,
        write_timeout=TELEGRAM_WRITE_TIMEOUT,
        pool_timeout=TELEGRAM_POOL_TIMEOUT,
    )
    application = (
        ApplicationBuilder()
        .token(settings.appointment_bot_token)
        .request(request)
        .build()
    )
    application.add_handler(CommandHandler("today", today_handler))
    application.add_handler(CommandHandler("check", check_handler))
    application.bot_data["settings"] = settings
    application.bot_data["cache"] = cache

    await application.initialize()
    await application.start()
    await application.updater.start_polling()

    appointment_bot = application.bot
    mail_bot = Bot(token=settings.mail_bot_token, request=request)
    await mail_bot.initialize()

    tasks = [
        asyncio.create_task(update_loop(settings, cache, ews_client)),
        asyncio.create_task(appointment_notify_loop(settings, cache, appointment_bot)),
        asyncio.create_task(mail_notify_loop(settings, cache, mail_bot)),
    ]
    if settings.agenda_time is not None:
        tasks.append(
            asyncio.create_task(agenda_loop(settings, cache, appointment_bot))
        )

    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            continue

    try:
        await stop_event.wait()
    finally:
        for task in tasks:
            task.cancel()
        await application.updater.stop()
        await application.stop()
        await application.shutdown()
        await mail_bot.shutdown()


def run() -> None:
    try:
        asyncio.run(run_async())
    except KeyboardInterrupt:
        pass
