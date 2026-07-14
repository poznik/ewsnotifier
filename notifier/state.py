"""Persistent notification state.

Keeps track of what has already been sent to Telegram so that a restart
does not re-notify every unread email and does not resend the daily agenda
(audit findings A3/A4). The state is a small JSON file written atomically;
if it cannot be read or written the application keeps working with
in-memory state only.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

_LOGGER = logging.getLogger("notifier.state")

_STATE_VERSION = 1


@dataclass
class NotificationState:
    notified_meetings: set[str] = field(default_factory=set)
    # mail item id -> when it was first notified (UTC); timestamps drive pruning
    notified_mail: dict[str, datetime] = field(default_factory=dict)
    agenda_last_sent: date | None = None
    mail_baseline_done: bool = False

    def prune_mail(self, current_ids: set[str], max_age: timedelta) -> None:
        """Drop mail ids that are gone from the unread view and too old to return."""
        cutoff = datetime.now(UTC) - max_age
        for item_id in list(self.notified_mail):
            if item_id in current_ids:
                continue
            if self.notified_mail[item_id] < cutoff:
                del self.notified_mail[item_id]


def _parse_stamp(value: object) -> datetime:
    try:
        stamp = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return datetime.now(UTC)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp


class StateStore:
    def __init__(self, path: str) -> None:
        self._path = path
        self._save_failed = False

    @property
    def path(self) -> str:
        return self._path

    def load(self) -> NotificationState:
        try:
            with open(self._path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except FileNotFoundError:
            _LOGGER.info("No state file at %s; starting with empty state", self._path)
            return NotificationState()
        except (OSError, json.JSONDecodeError) as exc:
            _LOGGER.warning(
                "Could not read state file %s (%s); starting with empty state",
                self._path,
                exc,
            )
            return NotificationState()

        try:
            notified_mail = {
                str(item_id): _parse_stamp(stamp)
                for item_id, stamp in dict(raw.get("notified_mail", {})).items()
            }
            agenda_raw = raw.get("agenda_last_sent")
            agenda_last_sent = date.fromisoformat(agenda_raw) if agenda_raw else None
            return NotificationState(
                notified_meetings={str(item) for item in raw.get("notified_meetings", [])},
                notified_mail=notified_mail,
                agenda_last_sent=agenda_last_sent,
                mail_baseline_done=bool(raw.get("mail_baseline_done", False)),
            )
        except (TypeError, ValueError, AttributeError) as exc:
            _LOGGER.warning(
                "State file %s is malformed (%s); starting with empty state",
                self._path,
                exc,
            )
            return NotificationState()

    def save(self, state: NotificationState) -> None:
        payload = {
            "version": _STATE_VERSION,
            "notified_meetings": sorted(state.notified_meetings),
            "notified_mail": {
                item_id: stamp.isoformat() for item_id, stamp in state.notified_mail.items()
            },
            "agenda_last_sent": (
                state.agenda_last_sent.isoformat() if state.agenda_last_sent else None
            ),
            "mail_baseline_done": state.mail_baseline_done,
        }
        directory = os.path.dirname(os.path.abspath(self._path))
        tmp_path: str | None = None
        try:
            fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".state-", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            os.replace(tmp_path, self._path)
            tmp_path = None
            if self._save_failed:
                self._save_failed = False
                _LOGGER.info("State persistence to %s recovered", self._path)
        except OSError as exc:
            if not self._save_failed:
                self._save_failed = True
                _LOGGER.warning(
                    "Cannot persist state to %s (%s); notifications will not be "
                    "deduplicated across restarts",
                    self._path,
                    exc,
                )
        finally:
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
