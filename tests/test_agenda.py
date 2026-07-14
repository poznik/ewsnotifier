from __future__ import annotations

from datetime import UTC, datetime
from datetime import time as dt_time

from notifier.agenda import MIN_GAP_MINUTES, build_day_layout, format_day_title

from .conftest import make_meeting, make_settings


def _utc(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 7, 14, hour, minute, tzinfo=UTC)


class TestDayBounds:
    def test_day_starts_at_workday_start(self):
        settings = make_settings()
        # 10:00–11:00 MSK
        layout = build_day_layout([make_meeting(start_utc=_utc(7), end_utc=_utc(8))], settings)
        local_start = layout.day_start_utc.astimezone(settings.local_timezone)
        assert (local_start.hour, local_start.minute) == (9, 0)

    def test_day_starts_at_first_meeting_when_it_precedes_workday(self):
        settings = make_settings()
        # 08:00–09:00 MSK, before WORKDAY_START
        layout = build_day_layout([make_meeting(start_utc=_utc(5), end_utc=_utc(6))], settings)
        assert layout.day_start_utc == _utc(5)

    def test_custom_workday_start_respected(self):
        settings = make_settings(workday_start=dt_time(8, 0))
        layout = build_day_layout([make_meeting(start_utc=_utc(7), end_utc=_utc(8))], settings)
        local_start = layout.day_start_utc.astimezone(settings.local_timezone)
        assert (local_start.hour, local_start.minute) == (8, 0)

    def test_empty_day(self):
        layout = build_day_layout([], make_settings())
        assert layout.is_empty
        assert layout.gaps == []
        assert layout.busy_minutes == 0

    def test_all_day_alone_is_still_an_empty_calendar(self):
        all_day = make_meeting(id="ad", is_all_day=True)
        layout = build_day_layout([all_day], make_settings())
        assert layout.is_empty
        assert layout.all_day == [all_day]

    def test_zero_length_meeting_ignored(self):
        layout = build_day_layout(
            [make_meeting(start_utc=_utc(7), end_utc=_utc(7))], make_settings()
        )
        assert layout.is_empty


class TestGaps:
    def test_gap_before_first_meeting(self):
        layout = build_day_layout(
            [make_meeting(start_utc=_utc(7), end_utc=_utc(8))], make_settings()
        )
        assert [gap.minutes for gap in layout.gaps] == [60]  # 09:00–10:00 MSK

    def test_gap_between_meetings(self):
        first = make_meeting(id="a", start_utc=_utc(6), end_utc=_utc(7))  # 09:00–10:00
        second = make_meeting(id="b", start_utc=_utc(8), end_utc=_utc(9))  # 11:00–12:00
        layout = build_day_layout([first, second], make_settings())
        assert [gap.minutes for gap in layout.gaps] == [60]

    def test_back_to_back_meetings_have_no_gap(self):
        first = make_meeting(id="a", start_utc=_utc(6), end_utc=_utc(7))
        second = make_meeting(id="b", start_utc=_utc(7), end_utc=_utc(8))
        layout = build_day_layout([first, second], make_settings())
        assert layout.gaps == []

    def test_short_dash_between_meetings_is_not_a_window(self):
        first = make_meeting(id="a", start_utc=_utc(6), end_utc=_utc(7))
        second = make_meeting(id="b", start_utc=_utc(7, MIN_GAP_MINUTES - 5), end_utc=_utc(8))
        layout = build_day_layout([first, second], make_settings())
        assert layout.gaps == []

    def test_biggest_gap_is_the_longest_one(self):
        first = make_meeting(id="a", start_utc=_utc(7), end_utc=_utc(8))  # 10:00–11:00
        second = make_meeting(id="b", start_utc=_utc(11), end_utc=_utc(12))  # 14:00–15:00
        layout = build_day_layout([first, second], make_settings())
        assert layout.biggest_gap is not None
        assert layout.biggest_gap.minutes == 180  # 11:00–14:00 beats 09:00–10:00


class TestBusyAndFree:
    def test_busy_counts_overlap_once(self):
        first = make_meeting(id="a", start_utc=_utc(7), end_utc=_utc(9))  # 2 h
        second = make_meeting(id="b", start_utc=_utc(8), end_utc=_utc(10))  # 2 h, 1 h shared
        layout = build_day_layout([first, second], make_settings())
        assert layout.busy_minutes == 180  # not 240

    def test_free_is_the_rest_of_the_day(self):
        meeting = make_meeting(start_utc=_utc(7), end_utc=_utc(8))  # 10:00–11:00 MSK
        layout = build_day_layout([meeting], make_settings())
        # day spans 09:00–11:00, one hour of it busy
        assert layout.busy_minutes == 60
        assert layout.free_minutes == 60


class TestOverlaps:
    def test_overlap_detected_with_its_stretch(self):
        first = make_meeting(id="a", start_utc=_utc(7), end_utc=_utc(8))
        second = make_meeting(id="b", start_utc=_utc(7, 30), end_utc=_utc(8, 30))
        layout = build_day_layout([first, second], make_settings())
        assert len(layout.overlaps) == 1
        assert layout.overlaps[0].minutes == 30
        assert layout.clashes(first) and layout.clashes(second)

    def test_back_to_back_is_not_an_overlap(self):
        first = make_meeting(id="a", start_utc=_utc(7), end_utc=_utc(8))
        second = make_meeting(id="b", start_utc=_utc(8), end_utc=_utc(9))
        layout = build_day_layout([first, second], make_settings())
        assert layout.overlaps == []
        assert not layout.clashes(first)

    def test_all_day_never_overlaps(self):
        all_day = make_meeting(id="ad", is_all_day=True)
        meeting = make_meeting(id="a", start_utc=_utc(7), end_utc=_utc(8))
        layout = build_day_layout([all_day, meeting], make_settings())
        assert layout.overlaps == []

    def test_three_way_overlap_yields_three_pairs(self):
        a = make_meeting(id="a", start_utc=_utc(7), end_utc=_utc(9))
        b = make_meeting(id="b", start_utc=_utc(8), end_utc=_utc(10))
        c = make_meeting(id="c", start_utc=_utc(8, 30), end_utc=_utc(9, 30))
        layout = build_day_layout([a, b, c], make_settings())
        assert len(layout.overlaps) == 3


class TestLanes:
    def test_sequential_meetings_share_one_lane(self):
        first = make_meeting(id="a", start_utc=_utc(7), end_utc=_utc(8))
        second = make_meeting(id="b", start_utc=_utc(9), end_utc=_utc(10))
        layout = build_day_layout([first, second], make_settings())
        assert layout.lane_count == 1
        assert layout.lanes == {"a": 0, "b": 0}

    def test_overlapping_meetings_get_separate_lanes(self):
        first = make_meeting(id="a", start_utc=_utc(7), end_utc=_utc(9))
        second = make_meeting(id="b", start_utc=_utc(8), end_utc=_utc(10))
        layout = build_day_layout([first, second], make_settings())
        assert layout.lane_count == 2
        assert layout.lanes == {"a": 0, "b": 1}

    def test_three_parallel_meetings_get_three_lanes(self):
        a = make_meeting(id="a", start_utc=_utc(7), end_utc=_utc(10))
        b = make_meeting(id="b", start_utc=_utc(8), end_utc=_utc(10))
        c = make_meeting(id="c", start_utc=_utc(8, 30), end_utc=_utc(10))
        layout = build_day_layout([a, b, c], make_settings())
        assert layout.lane_count == 3

    def test_lone_meeting_widens_across_empty_lanes(self):
        # a and b overlap (two lanes), c is alone later and should fill both
        a = make_meeting(id="a", start_utc=_utc(7), end_utc=_utc(9))
        b = make_meeting(id="b", start_utc=_utc(8), end_utc=_utc(10))
        c = make_meeting(id="c", start_utc=_utc(11), end_utc=_utc(12))
        layout = build_day_layout([a, b, c], make_settings())
        assert layout.lane_span(c) == 2
        assert layout.lane_span(a) == 1  # b sits next to it


class TestDayTitle:
    def test_russian_weekday_and_month(self):
        assert format_day_title(datetime(2026, 7, 14)) == "Вторник, 14 июля"
