"""Menschliche Bestaetigung einer importierten Preis-ID, keine Jahresfreigabe."""
from __future__ import annotations

import base64
import binascii
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from steuerreport_v2.contracts.price_evidence import (
    EvidenceDatetime, EvidenceDecimal, EvidenceHash, EvidenceKind, EvidenceText,
    PriceEvidenceAdmission, PriceEvidenceIdentity, PriceEvidenceMethod, PriceEvidenceObservation,
)
from steuerreport_v2.contracts.price_import_evidence import PriceImportOriginalRef
from steuerreport_v2.contracts.review import ReviewDecision


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    @field_validator("*", mode="after")
    @classmethod
    def nonblank(cls, value):
        if isinstance(value, str) and not value.strip():
            raise ValueError("price_admission_text_empty")
        return value


class PriceAdmissionFxInput(_Input):
    base: Literal["USD", "EUR"]
    quote: Literal["USD", "EUR"]
    rate: EvidenceDecimal
    reference_at: EvidenceDatetime
    published_at: EvidenceDatetime
    evidence_sha256: EvidenceHash
    locator: EvidenceText
    source: EvidenceText


class PriceAdmissionObservationInput(_Input):
    identity: PriceEvidenceIdentity
    quote_currency: Literal["EUR", "USD"]
    value: EvidenceDecimal
    kind: EvidenceKind
    observed_at: EvidenceDatetime | None = None
    period_start: EvidenceDatetime | None = None
    period_end: EvidenceDatetime | None = None
    published_at: EvidenceDatetime
    evidence_sha256: EvidenceHash
    locator: EvidenceText
    source: EvidenceText
    fx: PriceAdmissionFxInput | None = None


class PriceMethodOriginal(_Input):
    filename: str = Field(strict=True, min_length=1, max_length=180)
    media_type: str = Field(strict=True, min_length=1, max_length=100)
    content_base64: str = Field(strict=True, min_length=4, max_length=2_800_000)

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value):
        if value in {".", ".."} or "/" in value or "\\" in value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("price_admission_filename_invalid")
        return value

    @field_validator("media_type")
    @classmethod
    def safe_media_type(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+", value):
            raise ValueError("price_admission_media_type_invalid")
        return value

    @field_validator("content_base64")
    @classmethod
    def bounded_content(cls, value):
        try:
            body = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("price_admission_original_invalid") from None
        if not body or len(body) > 2 * 1024 * 1024:
            raise ValueError("price_admission_original_size_invalid")
        return value


class PriceAdmissionFacts(_Input):
    preview_sha256: EvidenceHash
    price_fingerprint: EvidenceHash
    valuation_at: EvidenceDatetime
    identity: PriceEvidenceIdentity
    observation: PriceAdmissionObservationInput
    method: PriceEvidenceMethod
    actor: EvidenceText
    rationale: EvidenceText


class PriceAdmissionDraftRequest(PriceAdmissionFacts):
    request_id: UUID
    method_original: PriceMethodOriginal


class PriceMethodDescriptor(_Input):
    sha256: EvidenceHash
    byte_length: int = Field(strict=True, ge=1, le=2 * 1024 * 1024)
    filename: str = Field(strict=True, min_length=1, max_length=180)
    media_type: str = Field(strict=True, min_length=1, max_length=100)

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value):
        return PriceMethodOriginal.safe_filename(value)

    @field_validator("media_type")
    @classmethod
    def safe_media_type(cls, value):
        return PriceMethodOriginal.safe_media_type(value)


class PriceAdmissionStoredPoint(_Input):
    price_id: EvidenceText
    asset: EvidenceText
    price_eur: EvidenceDecimal
    priced_at: EvidenceDatetime
    source: EvidenceText
    confidence: EvidenceDecimal


class PriceAdmissionStoredDraft(_Input):
    format_version: Literal[1] = 1
    request_id: UUID
    preview_id: UUID
    price_id: UUID
    created_at: EvidenceDatetime
    validation_policy_sha256: EvidenceHash
    facts: PriceAdmissionFacts
    point: PriceAdmissionStoredPoint
    originals: list[PriceImportOriginalRef] = Field(min_length=1, max_length=1000)
    method_original: PriceMethodDescriptor
    request_sha256: EvidenceHash
    binding_sha256: EvidenceHash
    draft_sha256: EvidenceHash


class PriceAdmissionApply(_Input):
    draft_sha256: EvidenceHash
    acknowledge_original_verified: bool = Field(strict=True)
    acknowledge_scope_limited: bool = Field(strict=True)

    @model_validator(mode="after")
    def explicit_approval(self):
        if not self.acknowledge_original_verified or not self.acknowledge_scope_limited:
            raise ValueError("price_admission_acknowledgement_required")
        return self


class PriceAdmissionRevoke(_Input):
    draft_sha256: EvidenceHash
    actor: EvidenceText
    rationale: EvidenceText
    acknowledge_revocation: bool = Field(strict=True)

    @model_validator(mode="after")
    def explicit_revocation(self):
        if not self.acknowledge_revocation:
            raise ValueError("price_admission_revocation_acknowledgement_required")
        return self


class PriceAdmissionReport(_Input):
    format_version: Literal[1] = 1
    status: Literal["prepared", "blocked", "human_approved", "revoked", "rejected"]
    request_id: UUID
    preview_id: UUID
    price_id: UUID
    draft_sha256: EvidenceHash
    price_fingerprint: EvidenceHash
    created_at: EvidenceDatetime
    validation_policy_sha256: EvidenceHash
    valuation_at: EvidenceDatetime
    identity: PriceEvidenceIdentity
    observation: PriceEvidenceObservation
    method: PriceEvidenceMethod
    actor: EvidenceText
    rationale: EvidenceText
    assessment: PriceEvidenceAdmission
    can_apply: bool = Field(strict=True)
    decision: ReviewDecision | None = None
    revocation: ReviewDecision | None = None
    method_original: PriceImportOriginalRef
    originals: list[PriceImportOriginalRef]
    explanation: str = (
        "Menschlich bestaetigte Zuordnung nur dieser Preis-ID, Methode und dieses "
        "Bewertungszeitpunkts. Keine automatische Echtheits-, Token-, Steuerjahres- "
        "oder Rechtsfreigabe; bestehende Preiswahl und weitere Gates bleiben getrennt."
    )

    @model_validator(mode="after")
    def consistent_status(self):
        approved = self.status == "human_approved"
        if approved != self.assessment.strict_eligible or approved != (self.assessment.status == "human_approved"):
            raise ValueError("price_admission_report_inconsistent")
        if approved and (self.decision is None or self.revocation is not None or self.can_apply):
            raise ValueError("price_admission_report_approval_invalid")
        if self.can_apply and (self.status != "prepared" or self.assessment.reason_codes != ["approval_missing"]):
            raise ValueError("price_admission_report_apply_invalid")
        return self
