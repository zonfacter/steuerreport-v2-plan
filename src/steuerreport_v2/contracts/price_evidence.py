"""Explizite menschliche Originalzuordnung, keine globale Bewertungsfreigabe."""
from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator, model_validator


def _decimal(value):
    if isinstance(value, (bool, float)) or not isinstance(value, (Decimal, str, int)):
        raise ValueError("evidence_decimal_required")
    try:
        number = Decimal(value)
    except ArithmeticError:
        raise ValueError("evidence_decimal_invalid") from None
    if not number.is_finite():
        raise ValueError("evidence_decimal_not_finite")
    return number


def _aware(value):
    if not isinstance(value, (datetime, str)):
        raise ValueError("evidence_datetime_required")
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("evidence_datetime_invalid") from None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("evidence_timezone_required")
    return value.astimezone(UTC)


EvidenceDecimal = Annotated[Decimal, BeforeValidator(_decimal)]
EvidenceDatetime = Annotated[datetime, BeforeValidator(_aware)]
EvidenceHash = Annotated[str, Field(strict=True, pattern=r"^[0-9a-f]{64}$")]
EvidenceText = Annotated[str, Field(strict=True, min_length=1, max_length=4096)]
EvidenceKind = Literal["observed_quote", "daily_reference"]


class _EvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def no_blank_text(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError("evidence_text_empty")
        return value


class PriceEvidenceIdentity(_EvidenceModel):
    asset: EvidenceText
    network: EvidenceText
    contract: EvidenceText
    decimals: int = Field(strict=True, ge=0, le=255)


class PriceEvidenceFx(_EvidenceModel):
    base: Literal["USD", "EUR"]
    quote: Literal["USD", "EUR"]
    rate: EvidenceDecimal
    reference_at: EvidenceDatetime
    published_at: EvidenceDatetime
    captured_at: EvidenceDatetime
    evidence_sha256: EvidenceHash
    locator: EvidenceText
    source: EvidenceText

    @model_validator(mode="after")
    def distinct_currencies(self):
        if self.base == self.quote:
            raise ValueError("evidence_fx_pair_invalid")
        return self


class PriceEvidenceObservation(_EvidenceModel):
    identity: PriceEvidenceIdentity
    quote_currency: Literal["EUR", "USD"]
    value: EvidenceDecimal
    kind: EvidenceKind
    observed_at: EvidenceDatetime | None = None
    period_start: EvidenceDatetime | None = None
    period_end: EvidenceDatetime | None = None
    published_at: EvidenceDatetime
    captured_at: EvidenceDatetime
    evidence_sha256: EvidenceHash
    locator: EvidenceText
    source: EvidenceText
    fx: PriceEvidenceFx | None = None


class PriceEvidenceMethod(_EvidenceModel):
    method_id: EvidenceText
    version: int = Field(strict=True, ge=1)
    kind: EvidenceKind
    daily_statistic: Literal["daily_mean", "daily_fixed_time", "daily_close"] | None = None
    daily_time: time | None = None
    timezone: EvidenceText
    availability_rule: Literal["available_at_cutoff", "retrospective_daily_reference"]
    fx_max_age_days: int | None = Field(default=None, strict=True, ge=0, le=7)
    evidence_sha256: EvidenceHash

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("evidence_timezone_invalid") from None
        return value

    @field_validator("daily_time", mode="before")
    @classmethod
    def local_time(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            try:
                value = time.fromisoformat(value)
            except ValueError:
                raise ValueError("evidence_daily_time_invalid") from None
        if not isinstance(value, time) or value.tzinfo is not None:
            raise ValueError("evidence_daily_time_invalid")
        return value


class PriceEvidenceApproval(_EvidenceModel):
    decision_id: EvidenceText
    decision_type: Literal["stichtag_price_time_admission"] = "stichtag_price_time_admission"
    binding_sha256: EvidenceHash
    actor: EvidenceText
    rationale: EvidenceText
    approved_at: EvidenceDatetime
    updated_at: EvidenceDatetime | None = None
    acknowledge_original_verified: bool = Field(strict=True)
    acknowledge_scope_limited: bool = Field(strict=True)


class PriceEvidenceAdmission(_EvidenceModel):
    policy_id: Literal["stichtag-price-evidence-admission"] = "stichtag-price-evidence-admission"
    policy_version: int = Field(default=1, strict=True, ge=1, le=1)
    status: Literal["human_approved", "not_approved", "rejected"]
    strict_eligible: bool = Field(strict=True)
    binding_sha256: EvidenceHash
    decision_id: EvidenceText | None = None
    reason_codes: list[str] = Field(default_factory=list)
    original_integrity_verified: bool = Field(strict=True)
    evidence_origin: Literal["operator_confirmed", "unverified"]

    @model_validator(mode="after")
    def consistent_admission(self):
        positive = self.status == "human_approved"
        if self.strict_eligible != positive or (self.evidence_origin == "operator_confirmed") != positive:
            raise ValueError("evidence_admission_inconsistent")
        if positive and (not self.original_integrity_verified or not self.decision_id or self.reason_codes):
            raise ValueError("evidence_admission_inconsistent")
        return self
