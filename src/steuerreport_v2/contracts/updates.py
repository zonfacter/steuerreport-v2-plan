from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool


UpdateChannel = Literal["stable", "stable_rc"]
UpdateCheckMode = Literal["manual", "automatic"]


class UpdateSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: UpdateChannel = "stable"
    automatic: StrictBool = False


class UpdateCheckRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: UpdateCheckMode = "manual"


class UpdateRelease(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    release_id: int = Field(gt=0, strict=True)
    tag: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=128)
    channel: Literal["stable", "rc"]
    github_prerelease: StrictBool
    published_at: datetime
    url: str = Field(max_length=512)
    body: str = Field(max_length=8000)
    source_commit: None = None
    image_reference: None = None
    image_digest: None = None
    open_checks: list[str] = Field(max_length=10)
    snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class UpdateStatus(BaseModel):
    installed_version: str | None
    status: Literal[
        "disabled",
        "not_checked",
        "checking",
        "up_to_date",
        "update_available",
        "unavailable",
    ]
    settings: UpdateSettings
    checked_at: datetime | None = None
    last_success_at: datetime | None = None
    retry_at: datetime | None = None
    stale: bool = False
    incomplete: bool = False
    message: str
    releases: list[UpdateRelease] = Field(default_factory=list)
    latest: UpdateRelease | None = None
    check_allowed: bool
    settings_writable: bool


class UpdateHandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    release_id: int = Field(gt=0, strict=True)
    snapshot_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class UpdateHandoff(BaseModel):
    handoff_schema_version: Literal[1] = 1
    installed_version: str | None
    target: UpdateRelease
    text: str
    created_at: datetime
