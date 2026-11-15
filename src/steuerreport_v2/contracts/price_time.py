"""Versioniertes Leseassessment fuer unbelegte Legacy-Preiszeitwerte."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PriceTimeAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_id: Literal["stichtag-temporal-evidence"] = "stichtag-temporal-evidence"
    policy_version: Literal[1] = 1
    asset: str
    status: Literal["fixed_eur_identity", "unverified_time", "missing", "future_reference", "non_positive"]
    strict_eligible: bool = Field(default=False, strict=True)
    reference_kind: Literal[
        "fixed_identity", "daily_reference_candidate", "derived_reference_candidate", "unknown",
    ] = "unknown"
    stored_reference_at: datetime | None = None
    observed_at: datetime | None = None
    period_start: datetime | None = None
    period_end: datetime | None = None
    price_published_at: datetime | None = None
    fx_published_at: datetime | None = None
    valuation_method_id: str | None = None
    valuation_method_version: int | None = None
    price_evidence_ref: str | None = None
    fx_evidence_ref: str | None = None
    reason_codes: list[str] = Field(default_factory=list)
    explanation: str

    @field_validator("policy_version", mode="before")
    @classmethod
    def version_is_integer(cls, value):
        if type(value) is not int or value != 1:
            raise ValueError("price_time_policy_version_invalid")
        return value

    @field_validator("stored_reference_at")
    @classmethod
    def reference_is_utc(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("price_time_stored_reference_timezone_missing")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def legacy_evidence_limits(self):
        identity = self.status == "fixed_eur_identity"
        if self.strict_eligible != identity:
            raise ValueError("price_time_eligibility_inconsistent")
        if (self.reference_kind == "fixed_identity") != identity:
            raise ValueError("price_time_identity_kind_inconsistent")
        if identity and (self.asset != "EUR" or self.stored_reference_at is not None):
            raise ValueError("price_time_identity_is_not_a_quote_event")
        evidence_fields = (
            "observed_at", "period_start", "period_end", "price_published_at", "fx_published_at",
            "valuation_method_id", "valuation_method_version", "price_evidence_ref", "fx_evidence_ref",
        )
        if any(getattr(self, field) is not None for field in evidence_fields):
            raise ValueError("price_time_legacy_has_no_original_evidence")
        return self
