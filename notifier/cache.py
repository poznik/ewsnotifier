from __future__ import annotations

import asyncio
from typing import Dict, Set

from notifier.models import Meeting, MailItem


class Cache:
    def __init__(self) -> None:
        self.meetings: Dict[str, Meeting] = {}
        self.mail: Dict[str, MailItem] = {}
        self.notified_meetings: Set[str] = set()
        self.notified_mail: Set[str] = set()
        self.lock = asyncio.Lock()
