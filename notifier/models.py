from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Meeting:
    id: str
    subject: str
    start_utc: datetime
    end_utc: datetime
    organizer: str
    location: str
    join_url: str | None
    is_all_day: bool = False
    is_private: bool = False


@dataclass(frozen=True)
class MailItem:
    id: str
    subject: str
    sender: str
    sent_utc: datetime
    preview: str
