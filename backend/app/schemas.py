from pydantic import BaseModel

from app.domain.enums import MetricType


class MeasurementSlotOut(BaseModel):
    id: int
    label: str
    sort_order: int
    category_id: int | None = None


class SlotCreate(BaseModel):
    label: str
    description: str | None = None


class SlotUpdate(BaseModel):
    label: str | None = None
    description: str | None = None


class SlotOut(BaseModel):
    id: int
    label: str
    sort_order: int
    description: str | None = None
    usage_count: int = 0
    usage_metric_names: list[str] = []


class CategoryCreate(BaseModel):
    name: str
    parent_id: int | None = None


class CategoryUpdate(BaseModel):
    name: str | None = None
    parent_id: int | None = None


class CategoryOut(BaseModel):
    id: int
    name: str
    parent_id: int | None = None
    sort_order: int
    children: list["CategoryOut"] = []


class MetricDefinitionCreate(BaseModel):
    slug: str | None = None
    name: str
    description: str | None = None
    category_id: int | None = None
    new_category_name: str | None = None
    new_category_parent_id: int | None = None
    icon: str = ""
    type: MetricType
    enabled: bool = True
    sort_order: int = 0
    scale_min: int | None = None
    scale_max: int | None = None
    scale_step: int | None = None
    scale_labels: dict[str, str] | None = None
    slot_configs: list[dict] | None = None  # [{slot_id: int, category_id: int | None}]
    formula: list[dict] | None = None
    result_type: str | None = None
    provider: str | None = None
    metric_key: str | None = None
    filter_name: str | None = None
    filter_query: str | None = None
    activitywatch_category_id: int | None = None
    app_name: str | None = None
    enum_options: list[str] | None = None
    multi_select: bool | None = None
    private: bool = False
    hide_in_cards: bool = False
    is_checkpoint: bool = False
    interval_binding: str = "daily"
    interval_start_slot_id: int | None = None
    condition_metric_id: int | None = None
    condition_type: str | None = None
    condition_value: bool | int | list[int] | None = None


class MetricDefinitionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category_id: int | None = None
    icon: str | None = None
    enabled: bool | None = None
    sort_order: int | None = None
    scale_min: int | None = None
    scale_max: int | None = None
    scale_step: int | None = None
    scale_labels: dict[str, str] | None = None
    slot_configs: list[dict] | None = None  # [{slot_id: int, category_id: int | None}]
    formula: list[dict] | None = None
    result_type: str | None = None
    enum_options: list[dict] | None = None  # [{id?: int, label: str}]
    multi_select: bool | None = None
    private: bool | None = None
    hide_in_cards: bool | None = None
    is_checkpoint: bool | None = None
    interval_binding: str | None = None
    interval_start_slot_id: int | None = None
    condition_metric_id: int | None = None
    condition_type: str | None = None
    condition_value: bool | int | list[int] | None = None
    remove_condition: bool = False


class MetricDefinitionOut(BaseModel):
    id: int
    slug: str
    name: str
    description: str | None = None
    category_id: int | None = None
    icon: str = ""
    type: MetricType
    enabled: bool
    sort_order: int
    scale_min: int | None = None
    scale_max: int | None = None
    scale_step: int | None = None
    scale_labels: dict[str, str] | None = None
    slots: list[MeasurementSlotOut] = []
    formula: list[dict] | None = None
    result_type: str | None = None
    provider: str | None = None
    metric_key: str | None = None
    value_type: str | None = None
    filter_name: str | None = None
    filter_query: str | None = None
    activitywatch_category_id: int | None = None
    config_app_name: str | None = None
    enum_options: list[dict] | None = None  # [{id, label, sort_order, enabled}]
    multi_select: bool | None = None
    private: bool = False
    hide_in_cards: bool = False
    is_checkpoint: bool = False
    interval_binding: str = "daily"
    interval_start_slot_id: int | None = None
    condition_metric_id: int | None = None
    condition_type: str | None = None
    condition_value: bool | int | list[int] | None = None


class EntryCreate(BaseModel):
    metric_id: int
    date: str  # YYYY-MM-DD
    value: bool | str | int | list[int]  # list[int] for enum option IDs
    slot_id: int | None = None


class EntryUpdate(BaseModel):
    value: bool | str | int | list[int]


class EntryOut(BaseModel):
    id: int
    metric_id: int
    date: str
    recorded_at: str
    value: bool | str | int | list[int] | None
    slot_id: int | None = None
    slot_label: str = ""


# Auth schemas
class UserRegister(BaseModel):
    username: str
    password: str


class UserLogin(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class UserOut(BaseModel):
    id: int
    username: str
    created_at: str


# ActivityWatch schemas
class AWEvent(BaseModel):
    timestamp: str
    duration: float
    data: dict


class AWSyncRequest(BaseModel):
    date: str  # YYYY-MM-DD
    window_events: list[AWEvent]
    afk_events: list[AWEvent]
    web_events: list[AWEvent] | None = None


# Notes schemas (text metric type)
class NoteCreate(BaseModel):
    metric_id: int
    date: str  # YYYY-MM-DD
    text: str


class NoteUpdate(BaseModel):
    text: str


class NoteOut(BaseModel):
    id: int
    metric_id: int
    date: str
    text: str
    created_at: str


class PrivacyModeUpdate(BaseModel):
    enabled: bool


# Metric conversion schemas
class ConversionPreview(BaseModel):
    total_entries: int
    entries_by_value: list[dict]  # [{"value": "0", "display": "0", "count": 15}, ...]


class MetricConvertRequest(BaseModel):
    target_type: MetricType
    value_mapping: dict[str, str | None]  # old_value_str -> new_value_str or None (delete)
    # For scale→scale and enum→scale:
    scale_min: int | None = None
    scale_max: int | None = None
    scale_step: int | None = None
    scale_labels: dict[str, str] | None = None
    # For bool→enum:
    enum_options: list[str] | None = None
    multi_select: bool = False


class MetricConvertResponse(BaseModel):
    converted: int
    deleted: int


# Insight schemas
class InsightMetricItem(BaseModel):
    metric_id: int | None = None
    custom_label: str | None = None


class InsightCreate(BaseModel):
    text: str
    metrics: list[InsightMetricItem] = []


class InsightUpdate(BaseModel):
    text: str | None = None
    metrics: list[InsightMetricItem] | None = None


class InsightMetricOut(BaseModel):
    id: int
    metric_id: int | None
    metric_name: str | None
    metric_icon: str | None
    custom_label: str | None
    sort_order: int


class InsightOut(BaseModel):
    id: int
    text: str
    metrics: list[InsightMetricOut]
    created_at: str
    updated_at: str
