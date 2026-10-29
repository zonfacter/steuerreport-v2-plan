from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator


class InstallationField(BaseModel):
    key: str
    label: str
    group: str
    kind: Literal["account", "path", "url", "text"]
    value: str
    source: Literal["environment", "profile", "empty"]
    editable: bool


class InstallationSettings(BaseModel):
    fields: list[InstallationField]
    revision: str
    restart_required: bool
    profile_writable: bool
    encrypted_secrets_available: bool
    providers: dict[str, bool]
    profile_issue: str | None = None
    server_time_utc: datetime | None = None
    storage_checks: list[dict[str, str]] = Field(default_factory=list)
    demo_mode: bool = False


class InstallationSettingsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str
    values: dict[str, str] = Field(max_length=100)


class ProviderSecretWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    api_key: str = Field(min_length=1, max_length=4096, repr=False)


class PrivateConfigWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str
    content: str = Field(max_length=1_000_000, repr=False)


class PrivateConfigDocument(BaseModel):
    filename: str
    content: str
    revision: str
    exists: bool = True
    valid: bool = True
    validation_error: str | None = None


class SolanaV1OwnershipScopeConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    outside_owned_wallet_scope_txids: list[StrictStr] = Field(default_factory=list)

    @field_validator("outside_owned_wallet_scope_txids")
    @classmethod
    def validate_txids(cls, values: list[str]) -> list[str]:
        if any(not value or value != value.strip() or len(value) > 512 for value in values):
            raise ValueError("solana_ownership_txid_invalid")
        return values
