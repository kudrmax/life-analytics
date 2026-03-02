from pydantic import BaseModel
from enum import Enum


class MetricType(str, Enum):
    bool = "bool"


class MetricDefinitionCreate(BaseModel):
    slug: str
    name: str
    category: str = ""
    type: MetricType
    enabled: bool = True
    sort_order: int = 0


class MetricDefinitionUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    enabled: bool | None = None
    sort_order: int | None = None


class MetricDefinitionOut(BaseModel):
    id: int
    slug: str
    name: str
    category: str
    type: MetricType
    enabled: bool
    sort_order: int


class EntryCreate(BaseModel):
    metric_id: int
    date: str  # YYYY-MM-DD
    value: bool


class EntryUpdate(BaseModel):
    value: bool


class EntryOut(BaseModel):
    id: int
    metric_id: int
    date: str
    recorded_at: str
    value: bool


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
