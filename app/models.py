from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, field_validator


class Status(str, Enum):
    investigating = "investigating"
    outage = "outage"
    restoring = "restoring"
    resolved = "resolved"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class IncidentInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    area_id: int = Field(gt=0)
    status: Status
    started_at: datetime
    eta_minutes: int | None = Field(default=None, ge=0, le=10080)
    source_note: str = Field(min_length=3, max_length=500)

    @field_validator("started_at")
    @classmethod
    def aware_datetime(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Include a timezone offset")
        if value > datetime.now(timezone.utc):
            raise ValueError("Start time cannot be in the future")
        return value.astimezone(timezone.utc)


class IncidentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Status
    eta_minutes: int | None = Field(default=None, ge=0, le=10080)
    source_note: str = Field(min_length=3, max_length=500)


class AreaInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=3, max_length=100)
    zone: str = Field(min_length=2, max_length=80)
    contact: str = Field(min_length=3, max_length=120)
    contact_source: str = Field(min_length=3, max_length=160)


class ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=64)
    arguments: dict = Field(default_factory=dict, max_length=8)


class AreaArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    area_id: int = Field(gt=0)


class ListArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(default="", max_length=80)


class ContactArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    area_id: int = Field(gt=0)
