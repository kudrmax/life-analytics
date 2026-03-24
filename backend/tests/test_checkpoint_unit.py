"""Unit tests for checkpoint auto-sources: delta, trend, range."""

import pytest

from app.analytics.auto_sources.registry import (
    AutoSourceInput,
    compute_auto_source,
)
from app.source_key import AutoSourceType


class TestComputeDelta:
    def test_basic(self):
        start_data = {"2026-01-01": 3.0, "2026-01-02": 5.0, "2026-01-03": 2.0}
        end_data = {"2026-01-01": 7.0, "2026-01-02": 4.0, "2026-01-03": 8.0}
        inp = AutoSourceInput(
            all_dates=["2026-01-01", "2026-01-02", "2026-01-03"],
            start_slot_data=start_data,
            end_slot_data=end_data,
        )
        result = compute_auto_source(AutoSourceType.DELTA, inp)
        assert result == {"2026-01-01": 4.0, "2026-01-02": -1.0, "2026-01-03": 6.0}

    def test_missing_day(self):
        """If one checkpoint is missing for a day, that day is skipped."""
        start_data = {"2026-01-01": 3.0, "2026-01-02": 5.0}
        end_data = {"2026-01-01": 7.0}  # missing 2026-01-02
        inp = AutoSourceInput(
            all_dates=["2026-01-01", "2026-01-02"],
            start_slot_data=start_data,
            end_slot_data=end_data,
        )
        result = compute_auto_source(AutoSourceType.DELTA, inp)
        assert result == {"2026-01-01": 4.0}

    def test_bool_values(self):
        """Bool values: true=1.0, false=0.0, delta in {-1, 0, +1}."""
        start_data = {"2026-01-01": 0.0, "2026-01-02": 1.0, "2026-01-03": 1.0}
        end_data = {"2026-01-01": 1.0, "2026-01-02": 0.0, "2026-01-03": 1.0}
        inp = AutoSourceInput(
            all_dates=["2026-01-01", "2026-01-02", "2026-01-03"],
            start_slot_data=start_data,
            end_slot_data=end_data,
        )
        result = compute_auto_source(AutoSourceType.DELTA, inp)
        assert result == {"2026-01-01": 1.0, "2026-01-02": -1.0, "2026-01-03": 0.0}

    def test_empty_start(self):
        inp = AutoSourceInput(
            all_dates=["2026-01-01"],
            start_slot_data=None,
            end_slot_data={"2026-01-01": 5.0},
        )
        assert compute_auto_source(AutoSourceType.DELTA, inp) == {}

    def test_empty_end(self):
        inp = AutoSourceInput(
            all_dates=["2026-01-01"],
            start_slot_data={"2026-01-01": 5.0},
            end_slot_data=None,
        )
        assert compute_auto_source(AutoSourceType.DELTA, inp) == {}


class TestComputeTrend:
    def test_basic(self):
        first = {"2026-01-01": 3.0, "2026-01-02": 5.0}
        last = {"2026-01-01": 7.0, "2026-01-02": 2.0}
        inp = AutoSourceInput(
            all_dates=["2026-01-01", "2026-01-02"],
            slot_data=[first, last],
        )
        result = compute_auto_source(AutoSourceType.TREND, inp)
        assert result == {"2026-01-01": 4.0, "2026-01-02": -3.0}

    def test_missing_endpoints(self):
        """Trend requires both first and last checkpoint to be filled."""
        first = {"2026-01-01": 3.0}
        last = {"2026-01-02": 7.0}  # different days
        inp = AutoSourceInput(
            all_dates=["2026-01-01", "2026-01-02"],
            slot_data=[first, last],
        )
        result = compute_auto_source(AutoSourceType.TREND, inp)
        assert result == {}  # no common days

    def test_single_checkpoint(self):
        """Trend needs at least 2 checkpoints."""
        inp = AutoSourceInput(
            all_dates=["2026-01-01"],
            slot_data=[{"2026-01-01": 5.0}],
        )
        assert compute_auto_source(AutoSourceType.TREND, inp) == {}

    def test_three_checkpoints_uses_first_and_last(self):
        first = {"2026-01-01": 2.0}
        middle = {"2026-01-01": 10.0}  # ignored by trend
        last = {"2026-01-01": 8.0}
        inp = AutoSourceInput(
            all_dates=["2026-01-01"],
            slot_data=[first, middle, last],
        )
        result = compute_auto_source(AutoSourceType.TREND, inp)
        assert result == {"2026-01-01": 6.0}  # 8 - 2, not 10 - 2


class TestComputeRange:
    def test_basic(self):
        s1 = {"2026-01-01": 3.0, "2026-01-02": 5.0}
        s2 = {"2026-01-01": 7.0, "2026-01-02": 2.0}
        s3 = {"2026-01-01": 5.0, "2026-01-02": 8.0}
        inp = AutoSourceInput(
            all_dates=["2026-01-01", "2026-01-02"],
            slot_data=[s1, s2, s3],
        )
        result = compute_auto_source(AutoSourceType.RANGE, inp)
        assert result == {"2026-01-01": 4.0, "2026-01-02": 6.0}  # 7-3, 8-2

    def test_single_checkpoint(self):
        """Range with a single checkpoint gives 0 (max - min = 0)."""
        inp = AutoSourceInput(
            all_dates=["2026-01-01"],
            slot_data=[{"2026-01-01": 5.0}],
        )
        result = compute_auto_source(AutoSourceType.RANGE, inp)
        assert result == {"2026-01-01": 0.0}

    def test_empty_slot_data(self):
        inp = AutoSourceInput(
            all_dates=["2026-01-01"],
            slot_data=None,
        )
        assert compute_auto_source(AutoSourceType.RANGE, inp) == {}
