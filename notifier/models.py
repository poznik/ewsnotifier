from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass(frozen=True)
class Meeting:
    id: str
    subject: str
    start_utc: datetime
    end_utc: datetime
    organizer: str
    location: Optional[str]
    join_url: Optional[str]


@dataclass(frozen=True)
class MailItem:
    id: str
    subject: str
    sender: str
    sent_utc: datetime
    preview: str
