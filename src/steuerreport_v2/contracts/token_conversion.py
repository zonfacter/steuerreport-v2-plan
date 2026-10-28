from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


class TokenConversionMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mapping_id: str = Field(min_length=1, max_length=100)
    enabled: StrictBool = False
    kind: Literal["redenomination", "wrapping"]
    source_event_id: str
    target_event_id: str
    source_event_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    target_event_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_raw_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    target_raw_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    ratio_numerator: Decimal = Field(gt=0, allow_inf_nan=False)
    ratio_denominator: Decimal = Field(gt=0, allow_inf_nan=False)
    tax_treatment: Literal["carry_original_basis_and_date"]
    actor: str = Field(min_length=1, max_length=100)
    rationale: str = Field(min_length=20, max_length=2000)
    evidence_ref: str = Field(min_length=5, max_length=1000)
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    acknowledge_same_economic_asset: Literal[True]
    acknowledge_no_automatic_tax_approval: Literal[True]

    @field_validator("acknowledge_same_economic_asset", "acknowledge_no_automatic_tax_approval", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("explicit_conversion_confirmation_required")
        return value

    @field_validator("actor", "rationale", "evidence_ref")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("conversion_evidence_or_actor_missing")
        return value.strip()


class TokenConversionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    mappings: list[TokenConversionMapping] = Field(default_factory=list)
