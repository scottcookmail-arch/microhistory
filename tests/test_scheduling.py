"""Tests for scheduling CSV format and content."""

import csv
import io
from datetime import datetime

import pytest

from microhistory.models import CalendarEntry, VideoType
from microhistory.scheduler import generate_schedule, write_schedule


class TestScheduleGeneration:
    """Test schedule generation logic."""

    def test_calendar_not_empty(self):
        schedule = generate_schedule("Test Topic", num_shorts=4)
        assert len(schedule.calendar) > 0

    def test_calendar_has_both_types(self):
        schedule = generate_schedule("Test Topic", num_shorts=4)
        types = {e.video_type for e in schedule.calendar}
        assert VideoType.LONG in types
        assert VideoType.SHORT in types

    def test_calendar_covers_30_days(self):
        schedule = generate_schedule("Test Topic")
        dates = {e.date for e in schedule.calendar}
        # Should span at least 25 days (some days might not have entries)
        assert len(dates) >= 25

    def test_recommendation_not_empty(self):
        schedule = generate_schedule("Test Topic")
        assert len(schedule.recommendation_md) > 100

    def test_checklist_not_empty(self):
        schedule = generate_schedule("Test Topic")
        assert len(schedule.checklist_md) > 100
        assert "YouTube Studio" in schedule.checklist_md


class TestScheduleCSVFormat:
    """Test the upload_calendar.csv output format."""

    def test_csv_headers(self, tmp_path):
        schedule = generate_schedule("Test Topic")
        write_schedule(schedule, tmp_path)

        csv_path = tmp_path / "scheduling" / "upload_calendar.csv"
        assert csv_path.exists()

        reader = csv.reader(io.StringIO(csv_path.read_text()))
        headers = next(reader)
        assert headers == ["date", "time", "type", "topic", "title_draft", "cta", "asset_notes"]

    def test_csv_data_rows(self, tmp_path):
        schedule = generate_schedule("Test Topic", num_shorts=3)
        write_schedule(schedule, tmp_path)

        csv_path = tmp_path / "scheduling" / "upload_calendar.csv"
        reader = csv.DictReader(io.StringIO(csv_path.read_text()))
        rows = list(reader)

        assert len(rows) > 0
        for row in rows:
            # Date format check
            datetime.strptime(row["date"], "%Y-%m-%d")
            # Time format check (HH:MM)
            assert ":" in row["time"]
            parts = row["time"].split(":")
            assert 0 <= int(parts[0]) <= 23
            assert 0 <= int(parts[1]) <= 59
            # Type must be Long or Short
            assert row["type"] in ("Long", "Short")
            # Topic not empty
            assert len(row["topic"]) > 0

    def test_csv_long_form_frequency(self, tmp_path):
        """Long-form videos should appear 2-3 times per week."""
        schedule = generate_schedule("Test Topic")
        write_schedule(schedule, tmp_path)

        csv_path = tmp_path / "scheduling" / "upload_calendar.csv"
        reader = csv.DictReader(io.StringIO(csv_path.read_text()))
        rows = list(reader)

        long_count = sum(1 for r in rows if r["type"] == "Long")
        # Over 30 days, expect 12-15 long-form videos (≈3/week * 4.3 weeks)
        assert 10 <= long_count <= 20


class TestCalendarEntryModel:
    """Test the CalendarEntry Pydantic model."""

    def test_valid_entry(self):
        entry = CalendarEntry(
            date="2025-01-15",
            time="15:00",
            video_type=VideoType.LONG,
            topic="Test",
            title_draft="Test Title",
            cta="Subscribe!",
            asset_notes="Ready",
        )
        assert entry.video_type == VideoType.LONG

    def test_short_entry(self):
        entry = CalendarEntry(
            date="2025-01-15",
            time="08:00",
            video_type=VideoType.SHORT,
            topic="Test Short",
        )
        assert entry.video_type == VideoType.SHORT
