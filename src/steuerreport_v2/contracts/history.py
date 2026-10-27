"""Quellengebundener Abruf, isolierte Vorschau und explizite Importfreigabe."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator


class HistoryCapability(BaseModel):
    source_ref: str
    label: str
    provider: str | None = None
    supported: bool = False
    ready: bool = False
    blocked_reason: str | None = None
    requires_symbols: bool = False
    coverage_notes: list[str] = Field(default_factory=list)
    default_start: date = date(2020, 1, 1)


class HistoryStart(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    request_id: UUID
    confirm_external_request: Literal[True]
    start: date = date(2020, 1, 1)
    end: date | None = None
    symbols: list[str] = Field(default_factory=list, max_length=200)
    public_rpc_only: StrictBool = True
    max_records: int = Field(default=100000, ge=1, le=1000000)

    @field_validator("confirm_external_request", mode="before")
    @classmethod
    def explicit_consent(cls, value):
        if value is not True:
            raise ValueError("history_external_confirmation_required")
        return value

    @field_validator("symbols")
    @classmethod
    def symbol_names(cls, values):
        import re
        result = list(dict.fromkeys(value.strip().upper() for value in values))
        if any(not re.fullmatch(r"[A-Z0-9_/-]{2,40}", value) for value in result):
            raise ValueError("history_symbols_invalid")
        return result

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.end is not None and self.end < self.start:
            raise ValueError("history_date_range_invalid")
        return self


class HistoryResume(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    confirm_external_request: Literal[True]
    max_records: int | None = Field(default=None, ge=1, le=1000000)

    @field_validator("confirm_external_request", mode="before")
    @classmethod
    def explicit_consent(cls, value):
        if value is not True:
            raise ValueError("history_external_confirmation_required")
        return value


class HistoryApprove(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    preview_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    actor: str = Field(min_length=1, max_length=120)
    confirm_import: Literal[True]
    confirm_recalculation: Literal[True]

    @field_validator("actor")
    @classmethod
    def named_reviewer(cls, value):
        if not value.strip():
            raise ValueError("history_actor_required")
        return value.strip()

    @field_validator("confirm_import", "confirm_recalculation", mode="before")
    @classmethod
    def explicit_consent(cls, value):
        if value is not True:
            raise ValueError("history_import_confirmation_required")
        return value


class HistoryJob(BaseModel):
    id: UUID
    source_ref: str
    label: str
    provider: str
    status: Literal["queued", "running", "paused", "ready", "importing", "succeeded", "failed", "cancelled"]
    phase: str
    created_at: datetime
    updated_at: datetime
    start: date
    end: date
    records_fetched: int = 0
    pages_fetched: int = 0
    new_records: int = 0
    duplicate_records: int = 0
    imported_events: int = 0
    requests: int = 0
    max_records: int = 100000
    preview_sha256: str | None = None
    sample_rows: list[dict[str, object]] = Field(default_factory=list)
    before_summary: dict[str, object] | None = None
    after_summary: dict[str, object] | None = None
    review_issues_open: int | None = None
    error_code: str | None = None
    coverage_notes: list[str] = Field(default_factory=list)
    complete_history_proven: bool = False
    can_resume: bool = False
    approval: dict[str, object] | None = None


class HistoryView(BaseModel):
    capability: HistoryCapability
    jobs: list[HistoryJob] = Field(default_factory=list)
