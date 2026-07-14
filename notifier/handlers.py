"""Telegram command handlers (/today, /check)."""

from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from notifier.cache import Cache
from notifier.config import Settings
from notifier.formatting import build_check_list, build_today_list, split_message


async def _reply_meeting_report(
    update: Update, context: ContextTypes.DEFAULT_TYPE, builder
) -> None:
    settings: Settings = context.bot_data["settings"]
    cache: Cache = context.bot_data["cache"]
    chat = update.effective_chat
    if chat is None or chat.id not in settings.allowed_chat_ids:
        return
    if update.message is None:
        return
    async with cache.lock:
        meetings = list(cache.meetings.values())
    text = builder(meetings, settings)
    for chunk in split_message(text):
        await update.message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN_V2)


async def today_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply_meeting_report(update, context, build_today_list)


async def check_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _reply_meeting_report(update, context, build_check_list)
