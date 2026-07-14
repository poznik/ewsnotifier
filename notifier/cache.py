from __future__ import annotations

import asyncio

from notifier.models import MailItem, Meeting
from notifier.state import NotificationState


class Cache:
    """In-memory snapshot of Exchange data plus persistent notification state.

    All fields are read and mutated under ``lock``.
    """

    def __init__(self, state: NotificationState | None = None) -> None:
        self.meetings: dict[str, Meeting] = {}
        self.mail: dict[str, MailItem] = {}
        self.state = state if state is not None else NotificationState()
        self.lock = asyncio.Lock()
