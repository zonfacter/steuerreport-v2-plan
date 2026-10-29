"""Native MEXC-Dateibelege: Menge ist keine steuerliche Klassifikation."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MexcExportKind = Literal[
    "spot_statement", "funding_other", "asset_snapshot", "futures_capital_flow",
    "futures_statement", "earn_fixed", "earn_flexible", "send_history",
]


class MexcRowDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["link_existing", "separate"]
    target_raw_object_id: str | None = Field(default=None, max_length=128)
    reason: str = Field(min_length=10, max_length=1000)
    input_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("reason")
    @classmethod
    def sufficient_reason(cls, value: str) -> str:
        if len(value.strip()) < 10:
            raise ValueError("Begruendung muss mindestens zehn Zeichen enthalten.")
        return value.strip()


class MexcImportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    export_kind: MexcExportKind | None = None
    account: str = Field(default="", max_length=128)
    timezone: Literal["UTC", "UTC+01:00", "UTC+08:00", "Europe/Berlin"] | None = None
    decisions: dict[str, MexcRowDecision] = Field(default_factory=dict, max_length=10000)

    @field_validator("account")
    @classmethod
    def valid_account(cls, value: str) -> str:
        value = value.strip()
        if any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Kontobezeichnung enthaelt Steuerzeichen.")
        return value


class MexcCandidate(BaseModel):
    raw_object_id: str
    filename: str | None = None
    row_number: int | None = None
    export_kind: str
    provider_id: str | None = None


class MexcRowPreview(BaseModel):
    row_number: int
    status: Literal["ready", "review", "duplicate_candidate", "linked", "evidence_only", "invalid"]
    reason: str
    asset: str | None = None
    quantity: str | None = None
    event_time: str | None = None
    candidates: list[MexcCandidate] = Field(default_factory=list)
    input_digest: str = ""
    decision_stale: bool = False


class MexcImportPreview(BaseModel):
    detected_kind: str | None = None
    disposition: Literal["transactions", "evidence_only", "empty", "unsupported"]
    raw_rows: int
    bookable_rows: int = 0
    linked_rows: int = 0
    review_rows: int = 0
    snapshot_rows: int = 0
    bonus_rows: int = 0
    blocking_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    rows: list[MexcRowPreview] = Field(default_factory=list)
