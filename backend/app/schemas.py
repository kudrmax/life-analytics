from pydantic import BaseModel
from enum import Enum


class MetricType(str, Enum):
    bool = "bool"
    enum = "enum"
    time = "time"
    number = "number"
    scale = "scale"
    computed = "computed"
    integration = "integration"
    duration = "duration"


class MeasurementSlotOut(BaseModel):
    id: int
    label: str
    sort_order: int


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
    slug: str
    name: str
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
    slot_labels: list[str] | None = None
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


class MetricDefinitionUpdate(BaseModel):
    name: str | None = None
    category_id: int | None = None
    icon: str | None = None
    enabled: bool | None = None
    sort_order: int | None = None
    scale_min: int | None = None
    scale_max: int | None = None
    scale_step: int | None = None
    slot_labels: list[str] | None = None
    formula: list[dict] | None = None
    result_type: str | None = None
    enum_options: list[dict] | None = None  # [{id?: int, label: str}]
    multi_select: bool | None = None


class MetricDefinitionOut(BaseModel):
    id: int
    slug: str
    name: str
    category_id: int | None = None
    icon: str = ""
    type: MetricType
    enabled: bool
    sort_order: int
    scale_min: int | None = None
    scale_max: int | None = None
    scale_step: int | None = None
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
