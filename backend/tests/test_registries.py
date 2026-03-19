"""Tests for integration registries — Todoist and ActivityWatch."""

from app.integrations.todoist.registry import TODOIST_METRICS, TODOIST_ICON
from app.integrations.activitywatch.registry import ACTIVITYWATCH_METRICS, ACTIVITYWATCH_ICON


class TestTodoistRegistry:
    """Tests for TODOIST_METRICS registry."""

    EXPECTED_KEYS = {"completed_tasks_count", "filter_tasks_count", "query_tasks_count"}
    REQUIRED_FIELDS = {"name", "value_type", "config_fields"}

    def test_has_exactly_3_metrics(self) -> None:
        assert len(TODOIST_METRICS) == 3

    def test_expected_keys_present(self) -> None:
        assert set(TODOIST_METRICS.keys()) == self.EXPECTED_KEYS

    def test_each_metric_has_required_fields(self) -> None:
        for key, metric in TODOIST_METRICS.items():
            for field in self.REQUIRED_FIELDS:
                assert field in metric, f"{key} missing field '{field}'"

    def test_all_value_types_are_number(self) -> None:
        for key, metric in TODOIST_METRICS.items():
            assert metric["value_type"] == "number", (
                f"{key} has value_type='{metric['value_type']}', expected 'number'"
            )

    def test_filter_tasks_count_config_fields(self) -> None:
        assert TODOIST_METRICS["filter_tasks_count"]["config_fields"] == ["filter_name"]

    def test_query_tasks_count_config_fields(self) -> None:
        assert TODOIST_METRICS["query_tasks_count"]["config_fields"] == ["filter_query"]

    def test_completed_tasks_count_no_config_fields(self) -> None:
        assert TODOIST_METRICS["completed_tasks_count"]["config_fields"] == []

    def test_icon_is_non_empty_string(self) -> None:
        assert isinstance(TODOIST_ICON, str)
        assert len(TODOIST_ICON) > 0


class TestActivityWatchRegistry:
    """Tests for ACTIVITYWATCH_METRICS registry."""

    EXPECTED_KEYS = {
        "active_screen_time",
        "total_screen_time",
        "first_activity",
        "last_activity",
        "afk_time",
        "longest_session",
        "context_switches",
        "break_count",
        "unique_apps",
        "category_time",
        "app_time",
    }
    REQUIRED_FIELDS = {"name", "description", "value_type", "config_fields"}

    def test_has_exactly_11_metrics(self) -> None:
        assert len(ACTIVITYWATCH_METRICS) == 11

    def test_expected_keys_present(self) -> None:
        assert set(ACTIVITYWATCH_METRICS.keys()) == self.EXPECTED_KEYS

    def test_each_metric_has_required_fields(self) -> None:
        for key, metric in ACTIVITYWATCH_METRICS.items():
            for field in self.REQUIRED_FIELDS:
                assert field in metric, f"{key} missing field '{field}'"

    def test_category_time_config_fields(self) -> None:
        assert ACTIVITYWATCH_METRICS["category_time"]["config_fields"] == [
            "activitywatch_category_id"
        ]

    def test_app_time_config_fields(self) -> None:
        assert ACTIVITYWATCH_METRICS["app_time"]["config_fields"] == ["app_name"]

    def test_first_activity_value_type_is_time(self) -> None:
        assert ACTIVITYWATCH_METRICS["first_activity"]["value_type"] == "time"

    def test_last_activity_value_type_is_time(self) -> None:
        assert ACTIVITYWATCH_METRICS["last_activity"]["value_type"] == "time"

    def test_icon_is_non_empty_string(self) -> None:
        assert isinstance(ACTIVITYWATCH_ICON, str)
        assert len(ACTIVITYWATCH_ICON) > 0
