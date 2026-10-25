from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
