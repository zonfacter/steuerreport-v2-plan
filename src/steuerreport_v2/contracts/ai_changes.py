from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AiDataQuery(StrictInput):
    kind: Literal["event", "price"] = "event"
    year: int = Field(default=2025, ge=2000, le=2100)
    asset: str = Field(default="", max_length=128)
    source: str = Field(default="", max_length=128)
    offset: int = Field(default=0, ge=0, le=1_000_000)
    limit: int = Field(default=20, ge=1, le=50)


class AiDataRow(BaseModel):
    kind: Literal["event", "price"]
    target_id: str
    revision: str
    values: dict[str, str | None]
    provenance: dict[str, str | int | None]


class AiDataContext(BaseModel):
    context_sha256: str
    total: int
    rows: list[AiDataRow]


class AiChange(StrictInput):
    kind: Literal["event", "price"]
    target_id: str = Field(min_length=1, max_length=128)
    before_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    patch: dict[Annotated[str, Field(max_length=64)], Annotated[str, Field(max_length=2048)] | None] = Field(min_length=1, max_length=12)
    reason: str = Field(min_length=10, max_length=2000)
    evidence_ref: str = Field(min_length=3, max_length=1000)


class AiChangeDraft(StrictInput):
    summary: str = Field(min_length=3, max_length=2000)
    changes: list[AiChange] = Field(min_length=1, max_length=25)


class AiChangeGenerate(StrictInput):
    request_id: str = Field(default_factory=lambda: uuid4().hex, pattern=r"^[a-f0-9]{32}$")
    query: AiDataQuery
    selected_ids: list[str] = Field(min_length=1, max_length=25)
    context_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    instruction: str = Field(min_length=10, max_length=4000)
    confirm_external: bool = False
    provider_revision: str


class AiChangeSet(BaseModel):
    change_set_id: str
    status: Literal["proposed", "previewed", "applied", "rejected"]
    draft: AiChangeDraft
    before: list[AiDataRow]
    origin: str
    model: str | None = None
    configuration_sha256: str | None = None
    created_at: datetime
    preview: dict | None = None
    approval: dict | None = None
    parent_id: str | None = None
    generation: dict | None = None


class AiChangePreview(StrictInput):
    selected_indices: list[int] = Field(min_length=1, max_length=25)


class AiChangeApply(StrictInput):
    preview_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    actor: str = Field(min_length=2, max_length=128)
    rationale: str = Field(min_length=10, max_length=2000)
    confirm: Literal[True]
    evidence_checked: Literal[True]


class AiChangeRevert(StrictInput):
    reason: str = Field(min_length=10, max_length=2000)
