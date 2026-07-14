from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as dt_time
from typing import Any
from zoneinfo import ZoneInfo

from exchangelib import BASIC, DELEGATE, DIGEST, NTLM, Account, Configuration, Credentials
from exchangelib.errors import (
    ErrorAccessDenied,
    ErrorMailboxLogonFailed,
    ErrorNonExistentMailbox,
    UnauthorizedError,
)
from exchangelib.protocol import BaseProtocol, NoVerifyHTTPAdapter

from notifier.config import Settings
from notifier.models import MailItem, Meeting
from notifier.utils import build_preview, extract_url

_AUTH_ERRORS = (
    ErrorAccessDenied,
    ErrorMailboxLogonFailed,
    ErrorNonExistentMailbox,
    UnauthorizedError,
)

_AUTH_TYPES = {"NTLM": NTLM, "BASIC": BASIC, "DIGEST": DIGEST}

# Sensitivity values that should be treated as private (see MASK_PRIVATE_MEETINGS).
_PRIVATE_SENSITIVITIES = {"Private", "Confidential"}

_MEETING_FIELDS = (
    "subject",
    "start",
    "end",
    "location",
    "id",
    "organizer",
    "is_all_day",
    "is_cancelled",
    "sensitivity",
)
_MAIL_FIELDS = (
    "subject",
    "datetime_sent",
    "datetime_received",
    "sender",
    "text_body",
    "id",
)


def _to_utc_datetime(value: datetime | date, tz: ZoneInfo) -> datetime:
    """Normalize an EWS start/end value to an aware UTC datetime.

    exchangelib returns aware EWSDateTime for regular items but plain
    EWSDate (a ``date`` subclass without tzinfo) for all-day events —
    passing those through unchecked was audit finding C1.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return datetime(
                value.year,
                value.month,
                value.day,
                value.hour,
                value.minute,
                value.second,
                value.microsecond,
                tzinfo=UTC,
            )
        return datetime.fromtimestamp(value.timestamp(), tz=UTC)
    return datetime.combine(value, dt_time(0, 0), tzinfo=tz).astimezone(UTC)


def _meeting_from_item(item: Any, tz: ZoneInfo) -> Meeting | None:
    start = item.start
    end = item.end
    if start is None or end is None:
        return None
    is_all_day = bool(item.is_all_day)
    if is_all_day and not isinstance(start, datetime):
        # All-day items arrive as dates; the end date is inclusive.
        start_utc = _to_utc_datetime(start, tz)
        end_utc = _to_utc_datetime(end + timedelta(days=1), tz)
    else:
        start_utc = _to_utc_datetime(start, tz)
        end_utc = _to_utc_datetime(end, tz)
    location = item.location or ""
    organizer = ""
    if item.organizer is not None:
        organizer = item.organizer.name or item.organizer.email_address or ""
    return Meeting(
        id=item.id,
        subject=item.subject or "(без темы)",
        start_utc=start_utc,
        end_utc=end_utc,
        organizer=organizer,
        location=location,
        join_url=extract_url(location),
        is_all_day=is_all_day,
        is_private=str(item.sensitivity) in _PRIVATE_SENSITIVITIES,
    )


def _mail_from_item(item: Any) -> MailItem | None:
    sent = item.datetime_sent
    if sent is None:
        return None
    sender = ""
    if item.sender is not None:
        sender = item.sender.name or item.sender.email_address or ""
    return MailItem(
        id=item.id,
        subject=item.subject or "(без темы)",
        sender=sender,
        sent_utc=_to_utc_datetime(sent, UTC),  # type: ignore[arg-type]
        preview=build_preview(item.text_body or ""),
    )


@dataclass
class EwsSnapshot:
    meetings: list[Meeting]
    mails: list[MailItem]


class EwsClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._account: Account | None = None
        self._logger = logging.getLogger("notifier.ews")

        if not settings.ews_verify_ssl:
            self._logger.warning(
                "TLS certificate verification is DISABLED (EWS_VERIFY_SSL=false). "
                "Credentials can be intercepted on untrusted networks; for "
                "self-signed certificates prefer REQUESTS_CA_BUNDLE with your CA."
            )
            BaseProtocol.HTTP_ADAPTER_CLS = NoVerifyHTTPAdapter

    def _build_account(self) -> Account:
        credentials = Credentials(
            username=self.settings.ews_username,
            password=self.settings.ews_password,
        )
        config = Configuration(
            server=self.settings.ews_server,
            credentials=credentials,
            auth_type=_AUTH_TYPES[self.settings.ews_auth_type],
        )
        return Account(
            primary_smtp_address=self.settings.ews_email,
            credentials=credentials,
            autodiscover=False,
            config=config,
            access_type=DELEGATE,
        )

    def _account_or_create(self) -> Account:
        if self._account is None:
            self._account = self._build_account()
        return self._account

    def fetch_snapshot(self, start_utc: datetime, end_utc: datetime) -> EwsSnapshot:
        account = self._account_or_create()
        meetings = self._fetch_meetings(account, start_utc, end_utc)
        mails = self._fetch_unread_mails(account)
        return EwsSnapshot(meetings=meetings, mails=mails)

    def _fetch_meetings(
        self, account: Account, start_utc: datetime, end_utc: datetime
    ) -> list[Meeting]:
        items = (
            account.calendar.view(start=start_utc, end=end_utc)
            .only(*_MEETING_FIELDS)
            .order_by("start")
            .all()
        )
        meetings: list[Meeting] = []
        for item in items:
            if item.is_cancelled:
                continue
            meeting = _meeting_from_item(item, self.settings.local_timezone)
            if meeting is not None:
                meetings.append(meeting)
        return meetings

    def _fetch_unread_mails(self, account: Account) -> list[MailItem]:
        cutoff = datetime.now(UTC) - timedelta(days=self.settings.mail_lookback_days)
        items = (
            account.inbox.filter(is_read=False, datetime_received__gt=cutoff)
            .only(*_MAIL_FIELDS)
            .order_by("-datetime_received")
        )[: self.settings.mail_fetch_limit]
        mails: list[MailItem] = []
        for item in items:
            mail = _mail_from_item(item)
            if mail is not None:
                mails.append(mail)
        return mails

    @staticmethod
    def is_auth_error(exc: Exception) -> bool:
        return isinstance(exc, _AUTH_ERRORS)
