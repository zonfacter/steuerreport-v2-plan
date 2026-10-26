"""Verbindungsvertraege: Secrets nur als Schreibfelder, nie in Antworten.

Alle Routen unter /api/v1/admin/connections liefern ApiResponse[data].
POST / und PUT /{id}: ConnectionCreate / ConnectionUpdate -> Connection.
DELETE /{id}/credentials -> Connection (keine Loeschung der Verbindung).
POST /{id}/test und /sync: ConnectionAction -> ConnectionJob, HTTP 202.
GET /jobs -> ConnectionJobs; POST /jobs/{id}/cancel -> ConnectionJob.
GET / -> ConnectionList; GET /{id}/snapshots -> ConnectionSnapshots.
Leere oder ausgelassene Secret-Felder im Update behalten den alten Wert.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, field_validator

from steuerreport_v2.contracts.portfolio import PortfolioLiveBalanceSnapshot

Provider = Literal["binance", "bitget", "coinbase", "pionex"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]


class ConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)

    provider: Provider
    label: str = Field(min_length=1, max_length=120)
    account: str = Field(default="", max_length=120)
    subaccount: str = Field(default="", max_length=120)
    origin: Literal["manual", "api", "import"] = "manual"
    budget_group: str = Field(default="ip:global", pattern=r"^(ip:global|budget:[a-z0-9_-]{1,48})$")
    api_key: SecretStr | None = None
    api_secret: SecretStr | None = None
    passphrase: SecretStr | None = None


class ConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, hide_input_in_errors=True)

    label: str | None = Field(default=None, min_length=1, max_length=120)
    account: str | None = Field(default=None, max_length=120)
    subaccount: str | None = Field(default=None, max_length=120)
    budget_group: str | None = Field(default=None, pattern=r"^(ip:global|budget:[a-z0-9_-]{1,48})$")
    api_key: SecretStr | None = None
    api_secret: SecretStr | None = None
    passphrase: SecretStr | None = None


class CredentialMetadata(BaseModel):
    status: Literal["missing", "incomplete", "configured", "unavailable", "invalid"]
    has_api_key: bool = False
    has_api_secret: bool = False
    has_passphrase: bool = False
    encrypted: bool = False
    updated_at: datetime | None = None


class Connection(BaseModel):
    id: UUID
    provider: Provider
    label: str
    account: str = ""
    subaccount: str = ""
    origin: str = "manual"
    budget_group: str = "ip:global"
    credentials: CredentialMetadata
    last_test_at: datetime | None = None
    last_sync_at: datetime | None = None
    last_error_code: str | None = None
    created_at: datetime
    updated_at: datetime
    tax_source_activated: Literal[False] = False


class LegacyConnection(BaseModel):
    id: str
    provider: Provider
    label: str
    origin: Literal["legacy"] = "legacy"
    read_only: Literal[True] = True
    credentials: CredentialMetadata
    budget_group: Literal["ip:global"] = "ip:global"
    tax_source_activated: Literal[False] = False


class ConnectionList(BaseModel):
    connections: list[Connection] = Field(default_factory=list)
    legacy_connections: list[LegacyConnection] = Field(default_factory=list)
    vault_ready: bool
    automatic_migration: Literal[False] = False


class ConnectionAction(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    confirm_external_request: Literal[True]
    confirm_balance_snapshot: StrictBool = False
    deadline_seconds: int = Field(default=120, ge=1, le=300)

    @field_validator("confirm_external_request", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("connection_effect_confirmation_required")
        return value


class ConnectionJob(BaseModel):
    id: UUID
    connection_id: UUID
    provider: Provider
    action: Literal["test", "sync"]
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    deadline_at: datetime
    cancel_requested: bool = False
    slot_reserved: bool = Field(
        default=False,
        description="Worker-Platz noch reserviert; auch nach Deadline bis zum Abschluss moeglich. Keine HTTP-Parallelitaetsmessung.",
    )
    error_code: str | None = None
    snapshot_count: int = 0
    effect: Literal["read_only_connection_test", "connection_balance_snapshot"]


class ConnectionJobs(BaseModel):
    jobs: list[ConnectionJob] = Field(default_factory=list)
    max_active: int = 4
    max_retained: int = 100


class ConnectionSnapshots(BaseModel):
    connection_id: UUID
    fetched_at: datetime | None = None
    snapshots: list[PortfolioLiveBalanceSnapshot] = Field(default_factory=list)
    tax_source_activated: Literal[False] = False
