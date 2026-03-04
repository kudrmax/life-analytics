from pydantic import BaseModel
from enum import Enum


class MetricType(str, Enum):
    bool = "bool"
    time = "time"
    number = "number"
    scale = "scale"
    computed = "computed"
    integration = "integration"


class MeasurementSlotOut(BaseModel):
    id: int
    label: str
    sort_order: int


class MetricDefinitionCreate(BaseModel):
    slug: str
    name: str
    category: str = ""
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


class MetricDefinitionUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    icon: str | None = None
    enabled: bool | None = None
    sort_order: int | None = None
    scale_min: int | None = None
    scale_max: int | None = None
    scale_step: int | None = None
    slot_labels: list[str] | None = None
    formula: list[dict] | None = None
    result_type: str | None = None


class MetricDefinitionOut(BaseModel):
    id: int
    slug: str
    name: str
    category: str
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


class EntryCreate(BaseModel):
    metric_id: int
    date: str  # YYYY-MM-DD
    value: bool | str | int  # bool for bool, "HH:MM" for time, int for number
    slot_id: int | None = None


class EntryUpdate(BaseModel):
    value: bool | str | int


class EntryOut(BaseModel):
    id: int
    metric_id: int
    date: str
    recorded_at: str
    value: bool | str | int | None
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
