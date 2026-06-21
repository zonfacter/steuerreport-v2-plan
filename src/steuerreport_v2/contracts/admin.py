from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class AdminSettingWrite(BaseModel):
    key: str
    value_json: str


class AdminSetting(AdminSettingWrite):
    updated_at: datetime


class AdminSettingDeleteResult(BaseModel):
    key: str
    deleted: bool


class AdminStatus(BaseModel):
    database: dict
    settings_count: int
    local_ai_enabled: bool
    external_ai_enabled: bool


class CexCredentialWrite(BaseModel):
    connector_id: str
    api_key: str
    api_secret: str
    passphrase: str | None = None


class CexCredentialWriteResult(BaseModel):
    connector_id: str
    status: str
    written_keys: list[str]
    diagnostic_status: str
    credential_status: str
    credential_issue: str | None = None
    message: str


class ApiKeyWrite(BaseModel):
    api_key: str


class ApiKeyWriteResult(BaseModel):
    provider: str
    status: str
    written_keys: list[str]
    message: str


class V1CexCredentialTakeoverItem(BaseModel):
    connector_id: str
    status: str
    can_take_over: bool
    has_api_key: bool
    has_api_secret: bool
    has_passphrase: bool = False
    keys_present: int = 0
    keys_required: int = 0
    credential_issue: str | None = None
    next_action: str


class V1CexCredentialTakeoverReport(BaseModel):
    generated_at: datetime
    items: list[V1CexCredentialTakeoverItem]
    transferable: int
    blocked: int
    methodology: str


class V1CexCredentialTakeoverRequest(BaseModel):
    connectors: list[str] | None = None


class V1CexCredentialTakeoverResult(BaseModel):
    generated_at: datetime
    imported: list[CexCredentialWriteResult]
    skipped: list[V1CexCredentialTakeoverItem]
    methodology: str
