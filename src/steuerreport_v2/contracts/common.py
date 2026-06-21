from __future__ import annotations

from typing import Generic, Literal, TypeVar
from uuid import uuid4

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiMessage(BaseModel):
    code: str
    message: str
    field: str | None = None


class ApiResponse(BaseModel, Generic[T]):
    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    status: Literal["ok", "warning", "error"] = "ok"
    data: T | None = None
    errors: list[ApiMessage] = Field(default_factory=list)
    warnings: list[ApiMessage] = Field(default_factory=list)
