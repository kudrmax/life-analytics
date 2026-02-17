from pydantic import BaseModel
from typing import Any


class MetricFieldConfig(BaseModel):
    name: str
    type: str
    label: str = ""
    condition: str | None = None


class MetricConfigCreate(BaseModel):
    id: str
    name: str
    category: str = ""
    type: str  # scale, boolean, number, time, enum, compound
    frequency: str = "daily"  # daily, multiple
    source: str = "manual"  # manual, todoist, google_calendar
    config: dict[str, Any] = {}
    enabled: bool = True
    sort_order: int = 0


class MetricConfigUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    type: str | None = None
    frequency: str | None = None
    source: str | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None
    sort_order: int | None = None


class MetricConfigOut(BaseModel):
    id: str
    name: str
    category: str
    type: str
    frequency: str
    source: str
    config: dict[str, Any]
    enabled: bool
    sort_order: int


class EntryCreate(BaseModel):
    metric_id: str
    date: str  # YYYY-MM-DD
    timestamp: str | None = None  # ISO datetime, auto-filled if None
    value: dict[str, Any]


class EntryUpdate(BaseModel):
    value: dict[str, Any]


class EntryOut(BaseModel):
    id: int
    metric_id: str
    date: str
    timestamp: str
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
