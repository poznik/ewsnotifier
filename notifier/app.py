"""Application wiring: bots, background tasks, lifecycle."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from telegram.ext import AIORateLimiter, ApplicationBuilder, CommandHandler, ExtBot
from telegram.request import HTTPXRequest

from notifier import __version__
from notifier.cache import Cache
from notifier.config import ConfigError, load_settings
from notifier.ews_client import EwsClient
from notifier.handlers import check_handler, today_handler
from notifier.loops import (
    agenda_loop,
    appointment_notify_loop,
    mail_notify_loop,
    update_loop,
)
from notifier.state import StateStore

TELEGRAM_CONNECT_TIMEOUT = 10
TELEGRAM_READ_TIMEOUT = 30
TELEGRAM_WRITE_TIMEOUT = 30
TELEGRAM_POOL_TIMEOUT = 30


def _build_request() -> HTTPXRequest:
    return HTTPXRequest(
        connect_timeout=TELEGRAM_CONNECT_TIMEOUT,
        read_timeout=TELEGRAM_READ_TIMEOUT,
        write_timeout=TELEGRAM_WRITE_TIMEOUT,
        pool_timeout=TELEGRAM_POOL_TIMEOUT,
    )


async def run_async() -> int:
    settings = load_settings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logger = logging.getLogger("notifier.app")
    logger.info("Starting ewsnotifier %s", __version__)

    store = StateStore(settings.state_file)
    cache = Cache(store.load())
    ews_client = EwsClient(settings)

    application = (
        ApplicationBuilder()
        .token(settings.appointment_bot_token)
        .request(_build_request())
        .rate_limiter(AIORateLimiter())
        .build()
    )
    application.add_handler(CommandHandler("today", today_handler))
    application.add_handler(CommandHandler("check", check_handler))
    application.bot_data["settings"] = settings
    application.bot_data["cache"] = cache

    mail_bot = ExtBot(
        token=settings.mail_bot_token,
        request=_build_request(),
        rate_limiter=AIORateLimiter(),
    )

    updater = application.updater
    if updater is None:  # ApplicationBuilder always creates one
        raise RuntimeError("Telegram application has no updater")

    await application.initialize()
    await application.start()
    await updater.start_polling(drop_pending_updates=True)
    await mail_bot.initialize()

    appointment_bot = application.bot

    ready_event = asyncio.Event()
    tasks = [
        asyncio.create_task(
            update_loop(settings, cache, appointment_bot, ews_client, ready_event, store),
            name="update_loop",
        ),
        asyncio.create_task(
            appointment_notify_loop(settings, cache, appointment_bot, ready_event, store),
            name="appointment_notify_loop",
        ),
        asyncio.create_task(
            mail_notify_loop(settings, cache, mail_bot, ready_event, store),
            name="mail_notify_loop",
        ),
    ]
    if settings.agenda_time is not None:
        tasks.append(
            asyncio.create_task(
                agenda_loop(settings, cache, appointment_bot, ready_event, store),
                name="agenda_loop",
            )
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

    exit_code = 0
    stop_task = asyncio.create_task(stop_event.wait(), name="stop")
    try:
        # Supervision: a background loop finishing means it crashed —
        # shut down with a non-zero code so Docker restarts the container.
        done, _ = await asyncio.wait([stop_task, *tasks], return_when=asyncio.FIRST_COMPLETED)
        if stop_task in done:
            logger.info("Shutdown signal received")
        else:
            crashed = next(iter(done))
            exc = crashed.exception()
            logger.critical(
                "Task %s terminated unexpectedly%s; shutting down",
                crashed.get_name(),
                f": {exc!r}" if exc else "",
            )
            exit_code = 1
    finally:
        stop_task.cancel()
        for task in tasks:
            task.cancel()
        await asyncio.gather(stop_task, *tasks, return_exceptions=True)
        await updater.stop()
        await application.stop()
        await application.shutdown()
        await mail_bot.shutdown()
    return exit_code


def run() -> None:
    try:
        exit_code = asyncio.run(run_async())
    except ConfigError as exc:
        print(f"ewsnotifier: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    except KeyboardInterrupt:
        raise SystemExit(130) from None
    raise SystemExit(exit_code)
