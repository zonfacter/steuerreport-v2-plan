from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


class JobState(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid4()))
    type: str
    status: Literal["queued", "running", "done", "failed"] = "queued"
    progress: float = 0.0
    result: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
