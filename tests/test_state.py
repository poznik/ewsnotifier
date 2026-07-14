from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, timedelta

from notifier.state import NotificationState, StateStore


class TestStateStore:
    def test_missing_file_returns_empty_state(self, tmp_path):
        store = StateStore(str(tmp_path / "state.json"))
        state = store.load()
        assert state.notified_meetings == set()
        assert state.notified_mail == {}
        assert state.agenda_last_sent is None
        assert state.mail_baseline_done is False

    def test_roundtrip(self, tmp_path):
        path = str(tmp_path / "state.json")
        store = StateStore(path)
        stamp = datetime(2026, 7, 14, 10, 0, tzinfo=UTC)
        state = NotificationState(
            notified_meetings={"m1", "m2"},
            notified_mail={"mail1": stamp},
            agenda_last_sent=date(2026, 7, 14),
            mail_baseline_done=True,
        )
        store.save(state)

        loaded = StateStore(path).load()
        assert loaded.notified_meetings == {"m1", "m2"}
        assert loaded.notified_mail == {"mail1": stamp}
        assert loaded.agenda_last_sent == date(2026, 7, 14)
        assert loaded.mail_baseline_done is True

    def test_corrupt_file_returns_empty_state(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("{not json", encoding="utf-8")
        state = StateStore(str(path)).load()
        assert state.notified_meetings == set()
        assert state.mail_baseline_done is False

    def test_malformed_structure_returns_empty_state(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text(json.dumps({"agenda_last_sent": "not-a-date"}), encoding="utf-8")
        state = StateStore(str(path)).load()
        assert state.agenda_last_sent is None

    def test_no_tmp_files_left_behind(self, tmp_path):
        path = str(tmp_path / "state.json")
        store = StateStore(path)
        store.save(NotificationState(notified_meetings={"m1"}))
        store.save(NotificationState(notified_meetings={"m2"}))
        leftovers = [name for name in os.listdir(tmp_path) if name != "state.json"]
        assert leftovers == []

    def test_save_failure_does_not_raise(self, tmp_path):
        store = StateStore(str(tmp_path / "no-such-dir" / "state.json"))
        store.save(NotificationState())  # must only log, never raise

    def test_naive_timestamp_upgraded_to_utc(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text(
            json.dumps({"notified_mail": {"m": "2026-07-14T10:00:00"}}),
            encoding="utf-8",
        )
        state = StateStore(str(path)).load()
        assert state.notified_mail["m"].tzinfo is not None


class TestPruneMail:
    def test_prune_rules(self):
        now = datetime.now(UTC)
        old = now - timedelta(days=30)
        state = NotificationState(
            notified_mail={
                "still_unread_old": old,
                "gone_old": old,
                "gone_recent": now - timedelta(hours=1),
            }
        )
        state.prune_mail(current_ids={"still_unread_old"}, max_age=timedelta(days=10))
        assert set(state.notified_mail) == {"still_unread_old", "gone_recent"}
