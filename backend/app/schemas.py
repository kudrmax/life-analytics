from pydantic import BaseModel
from typing import Any
from enum import Enum


class MetricType(str, Enum):
    bool = "bool"
    number = "number"
    scale = "scale"
    time = "time"


class NumberDisplayMode(str, Enum):
    number_only = "number_only"
    bool_number = "bool_number"


class MetricDefinitionCreate(BaseModel):
    slug: str
    name: str
    category: str = ""
    type: MetricType
    enabled: bool = True
    sort_order: int = 0
    measurements_per_day: int = 1
    measurement_labels: list[str] = []
    config: dict[str, Any] = {}


class MetricDefinitionUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    enabled: bool | None = None
    sort_order: int | None = None
    measurements_per_day: int | None = None
    measurement_labels: list[str] | None = None
    config: dict[str, Any] | None = None


class MetricDefinitionOut(BaseModel):
    id: int
    slug: str
    name: str
    category: str
    type: MetricType
    enabled: bool
    sort_order: int
    measurements_per_day: int
    measurement_labels: list[str]
    config: dict[str, Any]


class EntryCreate(BaseModel):
    metric_id: int
    date: str  # YYYY-MM-DD
    measurement_number: int = 1
    value: dict[str, Any]


class EntryUpdate(BaseModel):
    value: dict[str, Any]


class EntryOut(BaseModel):
    id: int
    metric_id: int
    date: str
    measurement_number: int
    recorded_at: str
    value: dict[str, Any]


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
