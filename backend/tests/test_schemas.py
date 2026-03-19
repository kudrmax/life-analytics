import pytest
import pytest_asyncio
from pydantic import ValidationError

from app.schemas import (
    AWSyncRequest,
    AWEvent,
    CategoryCreate,
    EntryCreate,
    EntryUpdate,
    InsightCreate,
    InsightMetricItem,
    MetricDefinitionCreate,
    MetricType,
    NoteCreate,
    PrivacyModeUpdate,
)


# Override autouse DB cleanup from conftest.py — these are pure unit tests
# that do not need a PostgreSQL connection.
@pytest_asyncio.fixture(autouse=True)
async def cleanup() -> None:  # type: ignore[override]
    yield  # type: ignore[misc]


class TestMetricTypeEnum:
    def test_has_all_nine_values(self) -> None:
        expected = {
            "bool", "enum", "time", "number", "scale",
            "computed", "integration", "duration", "text",
        }
        actual = {member.value for member in MetricType}
        assert actual == expected

    def test_member_count_is_nine(self) -> None:
        assert len(MetricType) == 9


class TestMetricDefinitionCreate:
    def test_valid_with_defaults(self) -> None:
        m = MetricDefinitionCreate(name="Sleep", type=MetricType.bool)
        assert m.name == "Sleep"
        assert m.type == MetricType.bool
        assert m.enabled is True
        assert m.sort_order == 0
        assert m.icon == ""
        assert m.slug is None
        assert m.private is False

    def test_valid_with_all_fields(self) -> None:
        m = MetricDefinitionCreate(
            slug="mood",
            name="Mood",
            category_id=1,
            icon="smile",
            type=MetricType.scale,
            enabled=False,
            sort_order=5,
            scale_min=1,
            scale_max=10,
            scale_step=1,
            private=True,
        )
        assert m.slug == "mood"
        assert m.scale_min == 1
        assert m.scale_max == 10
        assert m.scale_step == 1
        assert m.enabled is False
        assert m.private is True

    def test_missing_required_name_raises(self) -> None:
        with pytest.raises(ValidationError):
            MetricDefinitionCreate(type=MetricType.bool)  # type: ignore[call-arg]

    def test_missing_required_type_raises(self) -> None:
        with pytest.raises(ValidationError):
            MetricDefinitionCreate(name="Test")  # type: ignore[call-arg]


class TestEntryCreate:
    def test_with_bool_value(self) -> None:
        e = EntryCreate(metric_id=1, date="2026-03-17", value=True)
        assert e.value is True
        assert e.slot_id is None

    def test_with_string_value_for_time(self) -> None:
        e = EntryCreate(metric_id=2, date="2026-03-17", value="14:30")
        assert e.value == "14:30"

    def test_with_int_value(self) -> None:
        e = EntryCreate(metric_id=3, date="2026-03-17", value=42)
        assert e.value == 42

    def test_with_list_int_value_for_enum(self) -> None:
        e = EntryCreate(metric_id=4, date="2026-03-17", value=[1, 3, 5])
        assert e.value == [1, 3, 5]

    def test_missing_required_fields_raises(self) -> None:
        with pytest.raises(ValidationError):
            EntryCreate(metric_id=1, date="2026-03-17")  # type: ignore[call-arg]


class TestEntryUpdate:
    def test_valid(self) -> None:
        u = EntryUpdate(value=99)
        assert u.value == 99

    def test_missing_value_raises(self) -> None:
        with pytest.raises(ValidationError):
            EntryUpdate()  # type: ignore[call-arg]


class TestInsightCreate:
    def test_with_text_and_empty_metrics(self) -> None:
        i = InsightCreate(text="Sleep correlates with mood")
        assert i.text == "Sleep correlates with mood"
        assert i.metrics == []

    def test_with_metrics(self) -> None:
        i = InsightCreate(
            text="Important finding",
            metrics=[
                InsightMetricItem(metric_id=1),
                InsightMetricItem(custom_label="Custom metric"),
                InsightMetricItem(metric_id=5, custom_label="Override"),
            ],
        )
        assert len(i.metrics) == 3
        assert i.metrics[0].metric_id == 1
        assert i.metrics[0].custom_label is None
        assert i.metrics[1].metric_id is None
        assert i.metrics[1].custom_label == "Custom metric"
        assert i.metrics[2].metric_id == 5
        assert i.metrics[2].custom_label == "Override"


class TestNoteCreate:
    def test_valid(self) -> None:
        n = NoteCreate(metric_id=10, date="2026-03-17", text="Journal entry")
        assert n.metric_id == 10
        assert n.date == "2026-03-17"
        assert n.text == "Journal entry"

    def test_missing_text_raises(self) -> None:
        with pytest.raises(ValidationError):
            NoteCreate(metric_id=10, date="2026-03-17")  # type: ignore[call-arg]


class TestAWSyncRequest:
    def test_valid_with_web_events_none(self) -> None:
        event = AWEvent(timestamp="2026-03-17T10:00:00Z", duration=60.0, data={"app": "Chrome"})
        req = AWSyncRequest(
            date="2026-03-17",
            window_events=[event],
            afk_events=[event],
        )
        assert req.web_events is None
        assert len(req.window_events) == 1
        assert len(req.afk_events) == 1

    def test_valid_with_web_events(self) -> None:
        event = AWEvent(timestamp="2026-03-17T10:00:00Z", duration=30.0, data={"url": "https://example.com"})
        req = AWSyncRequest(
            date="2026-03-17",
            window_events=[event],
            afk_events=[],
            web_events=[event],
        )
        assert req.web_events is not None
        assert len(req.web_events) == 1


class TestCategoryCreate:
    def test_without_parent_id(self) -> None:
        c = CategoryCreate(name="Health")
        assert c.name == "Health"
        assert c.parent_id is None

    def test_with_parent_id(self) -> None:
        c = CategoryCreate(name="Sleep", parent_id=3)
        assert c.parent_id == 3


class TestPrivacyModeUpdate:
    def test_valid(self) -> None:
        p = PrivacyModeUpdate(enabled=True)
        assert p.enabled is True

    def test_missing_enabled_raises(self) -> None:
        with pytest.raises(ValidationError):
            PrivacyModeUpdate()  # type: ignore[call-arg]
