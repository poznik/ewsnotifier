from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import List, Tuple

from exchangelib import Account, Configuration, Credentials, DELEGATE, EWSTimeZone
from exchangelib.protocol import BaseProtocol, NoVerifyHTTPAdapter
from exchangelib.errors import (
    ErrorAccessDenied,
    ErrorMailboxLogonFailed,
    ErrorNonExistentMailbox,
    UnauthorizedError,
)
from exchangelib import NTLM, BASIC, DIGEST

from notifier.config import Settings
from notifier.models import Meeting, MailItem
from notifier.utils import build_preview, extract_url


_AUTH_ERRORS = (
    ErrorAccessDenied,
    ErrorMailboxLogonFailed,
    ErrorNonExistentMailbox,
    UnauthorizedError,
)


def _to_utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return datetime(
            value.year,
            value.month,
            value.day,
            value.hour,
            value.minute,
            value.second,
            value.microsecond,
            tzinfo=timezone.utc,
        )
    return datetime.fromtimestamp(value.timestamp(), tz=timezone.utc)


@dataclass
class EwsSnapshot:
    meetings: List[Meeting]
    mails: List[MailItem]


def _resolve_auth_type(value: str):
    upper = value.strip().upper()
    if upper == "NTLM":
        return NTLM
    if upper == "BASIC":
        return BASIC
    if upper == "DIGEST":
        return DIGEST
    return NTLM


class EwsClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._account: Account | None = None
        self._logger = logging.getLogger("notifier.ews")

        if not settings.ews_verify_ssl:
            BaseProtocol.HTTP_ADAPTER_CLS = NoVerifyHTTPAdapter

    def _build_account(self) -> Account:
        credentials = Credentials(
            username=self.settings.ews_username,
            password=self.settings.ews_password,
        )
        config = Configuration(
            server=self.settings.ews_server,
            credentials=credentials,
            auth_type=_resolve_auth_type(self.settings.ews_auth_type),
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
    ) -> List[Meeting]:
        view = account.calendar.view(start=start_utc, end=end_utc)
        items = (
            view.only("subject", "start", "end", "location", "id", "organizer")
            .order_by("start")
            .all()
        )
        meetings: List[Meeting] = []
        for item in items:
            start = item.start
            end = item.end
            if start is None or end is None:
                continue
            start_utc = _to_utc_datetime(start)
            end_utc = _to_utc_datetime(end)
            location = item.location or ""
            organizer = ""
            if item.organizer is not None:
                organizer = item.organizer.name or item.organizer.email_address or ""
            join_url = extract_url(location)
            meetings.append(
                Meeting(
                    id=item.id,
                    subject=item.subject or "(без темы)",
                    start_utc=start_utc,
                    end_utc=end_utc,
                    organizer=organizer,
                    location=location,
                    join_url=join_url,
                )
            )
        return meetings

    def _fetch_unread_mails(self, account: Account) -> List[MailItem]:
        items = (
            account.inbox.filter(is_read=False)
            .only("subject", "datetime_sent", "sender", "text_body", "body", "id")
            .order_by("-datetime_sent")
            .all()
        )
        mails: List[MailItem] = []
        for item in items:
            sent = item.datetime_sent
            if sent is None:
                continue
            sent_utc = _to_utc_datetime(sent)
            sender = ""
            if item.sender is not None:
                sender = item.sender.name or item.sender.email_address or ""
            body = item.text_body or ""
            if not body:
                body = str(item.body or "")
            preview = build_preview(body)
            mails.append(
                MailItem(
                    id=item.id,
                    subject=item.subject or "(без темы)",
                    sender=sender,
                    sent_utc=sent_utc,
                    preview=preview,
                )
            )
        return mails

    @staticmethod
    def is_auth_error(exc: Exception) -> bool:
        return isinstance(exc, _AUTH_ERRORS)
