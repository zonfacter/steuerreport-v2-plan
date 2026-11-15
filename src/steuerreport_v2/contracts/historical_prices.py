"""V1-unabhaengige Tagespreisplanung und explizite Uebernahme."""
import base64
import binascii
from datetime import date, datetime
from decimal import Decimal
import re
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator


class PriceMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    asset: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_:./-]+$")
    coingecko_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,100}$")
    defillama_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]+:[A-Za-z0-9_-]+$")
    solana_mint: str | None = Field(default=None, pattern=r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
    network: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9:_-]{0,60}$")
    contract_address: str | None = Field(default=None, min_length=1, max_length=150)
    decimals: int | None = Field(default=None, strict=True, ge=0, le=255)

    @model_validator(mode="after")
    def validate_contract(self):
        if self.contract_address is not None:
            from steuerreport_v2.domain.asset_identity import identity_from_payload
            identity = identity_from_payload({"network": self.network, "contract_address": self.contract_address,
                "decimals": self.decimals}, role="asset", source="", quantity=Decimal("0"))
            self.network, self.contract_address = identity.network, identity.contract
        return self

    @model_validator(mode="before")
    @classmethod
    def preserve_address_identity(cls, value, info: ValidationInfo):
        if isinstance(value, dict) and value.get("solana_mint") is None:
            if info.context and info.context.get("stored_mapping"):
                # Gespeicherte Asset-Aliase haben ihre originale Schreibweise verloren.
                identifier = value.get("defillama_id")
                original = (
                    identifier.removeprefix("solana:")
                    if isinstance(identifier, str) and identifier.startswith("solana:") else None
                )
            else:
                original = value.get("asset")
            if isinstance(original, str) and re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", original):
                return {**value, "solana_mint": original}
        return value

    @field_validator("asset")
    @classmethod
    def normalize(cls, value):
        return value.upper()


class HistoricalPriceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    year: int | None = Field(default=None, ge=2009, le=2100)
    assets: list[str] = Field(default_factory=list, max_length=100)
    provider: Literal["defillama", "coingecko"] = "defillama"
    max_requests: int = Field(default=10, ge=1, le=50)
    scope: Literal["tax_required", "all_observed"] = "tax_required"
    page: int = Field(default=1, ge=1, le=100_000)
    page_size: int = Field(default=25, ge=1, le=100)
    strategy: Literal["standard", "automatic"] = "standard"
    max_total_requests: int | None = Field(default=None, ge=1, le=1000)

    @field_validator("assets")
    @classmethod
    def normalize(cls, values):
        return sorted({PriceMapping(asset=value.strip()).asset for value in values if value.strip()})


class ManualPriceEvidenceFile(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    filename: str = Field(min_length=1, max_length=180)
    media_type: str = Field(min_length=1, max_length=100)
    source_name: str = Field(min_length=1, max_length=200)
    source_reference: str | None = Field(default=None, max_length=500)
    source_observed_at: datetime
    content_base64: str = Field(min_length=4, max_length=2_800_000)

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value):
        if value in {".", ".."} or "/" in value or "\\" in value or any(ord(char) < 32 for char in value):
            raise ValueError("historical_price_manual_filename_invalid")
        return value

    @field_validator("source_name")
    @classmethod
    def source_required(cls, value):
        if not value.strip():
            raise ValueError("historical_price_manual_source_required")
        return value.strip()

    @field_validator("media_type")
    @classmethod
    def valid_media_type(cls, value):
        if not re.fullmatch(r"[A-Za-z0-9!#$&^_.+-]+/[A-Za-z0-9!#$&^_.+-]+", value.strip()):
            raise ValueError("historical_price_manual_media_type_invalid")
        return value.strip().lower()

    @field_validator("source_reference")
    @classmethod
    def clean_reference(cls, value):
        return value.strip() if value and value.strip() else None

    @field_validator("source_observed_at")
    @classmethod
    def observed_time_is_explicit(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("historical_price_manual_timezone_required")
        return value

    @field_validator("content_base64")
    @classmethod
    def validate_bounded_base64(cls, value):
        try:
            content = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError):
            raise ValueError("historical_price_manual_evidence_invalid") from None
        if not content or len(content) > 2 * 1024 * 1024:
            raise ValueError("historical_price_manual_evidence_size_invalid")
        return value


class ManualFxObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    date: date
    base: Literal["USD", "EUR"]
    quote: Literal["USD", "EUR"]
    rate: Decimal
    source: str = Field(min_length=1, max_length=200)

    @field_validator("rate")
    @classmethod
    def positive_finite_rate(cls, value):
        if not value.is_finite() or value <= 0:
            raise ValueError("historical_price_fx_value_invalid")
        return value

    @field_validator("source")
    @classmethod
    def clean_source(cls, value):
        if not value.strip():
            raise ValueError("historical_price_fx_source_required")
        return value.strip()

    @model_validator(mode="after")
    def distinct_currencies(self):
        if self.base == self.quote:
            raise ValueError("historical_price_fx_pair_invalid")
        return self


class ManualHistoricalPricePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    request_id: UUID
    query: HistoricalPriceQuery
    plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    asset: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_:./-]+$")
    price_date: date
    price_value: Decimal
    price_currency: Literal["EUR", "USD"]
    price_unit: Literal["currency_per_asset"] = "currency_per_asset"
    priced_at: datetime
    price_evidence: ManualPriceEvidenceFile
    fx_evidence: ManualPriceEvidenceFile | None = None
    fx_observations: list[ManualFxObservation] = Field(default_factory=list, max_length=50)

    @field_validator("asset")
    @classmethod
    def normalize_asset(cls, value):
        return value.strip().upper()

    @field_validator("price_value")
    @classmethod
    def positive_finite_price(cls, value):
        if not value.is_finite() or value <= 0:
            raise ValueError("historical_price_value_invalid")
        return value

    @field_validator("priced_at")
    @classmethod
    def price_time_is_explicit(cls, value):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("historical_price_manual_timezone_required")
        return value

    @model_validator(mode="after")
    def direct_eur_has_no_fx(self):
        if self.price_currency == "EUR" and (self.fx_evidence is not None or self.fx_observations):
            raise ValueError("historical_price_unexpected_fx_evidence")
        return self


class HistoricalPriceFetch(HistoricalPriceQuery):
    request_id: UUID
    plan_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirm_external_request: Literal[True]

    @field_validator("confirm_external_request", mode="before")
    @classmethod
    def consent(cls, value):
        if value is not True:
            raise ValueError("historical_price_confirmation_required")
        return value


class HistoricalPriceApply(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    preview_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    actor: str = Field(min_length=1, max_length=100)
    confirm_prices: Literal[True]
    confirm_recalculation: Literal[True]

    @field_validator("actor")
    @classmethod
    def actor_name(cls, value):
        if not value.strip():
            raise ValueError("historical_price_actor_required")
        return value.strip()

    @field_validator("confirm_prices", "confirm_recalculation", mode="before")
    @classmethod
    def consent(cls, value):
        if value is not True:
            raise ValueError("historical_price_confirmation_required")
        return value


class HistoricalPriceContinue(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    request_id: UUID
    preview_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirm_external_request: Literal[True]
    retry_open: bool = False

    @field_validator("confirm_external_request", mode="before")
    @classmethod
    def consent(cls, value):
        if value is not True:
            raise ValueError("historical_price_confirmation_required")
        return value


class HistoricalPriceRow(BaseModel):
    asset: str
    price_date: date
    event_count: int
    provider_id: str | None = None
    status: str
    reason: str | None = None
    price_eur: Decimal | None = None
    priced_at: str | None = None
    fx_date: str | None = None
    source: str | None = None
    evidence_sha256: list[str] = Field(default_factory=list)


class HistoricalPricePreviewListItem(BaseModel):
    """Integritaetszustand einer Vorschau, keine Inhalts- oder Methodenfreigabe."""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    id: str = Field(strict=True)
    created_at: str | None = Field(default=None, strict=True)
    prices_count: int | None = Field(default=None, strict=True, ge=0)
    status: Literal["ready", "no_prices", "blocked", "unavailable"]
    applied: bool | None = Field(default=None, strict=True)
    preview_sha256: str | None = Field(default=None, strict=True, pattern=r"^[a-f0-9]{64}$")
    pending_count: int | None = Field(default=None, strict=True, ge=0)
    open_count: int | None = Field(default=None, strict=True, ge=0)
    parent_preview_id: str | None = Field(default=None, strict=True)
    collection_complete: bool | None = Field(default=None, strict=True)
    manual: bool | None = Field(default=None, strict=True)
    integrity_status: Literal["verified", "unavailable"]
    error_code: Literal[
        "historical_price_evidence_changed",
        "historical_price_apply_decision_invalid",
        "historical_price_preview_unavailable",
    ] | None = None

    @field_validator("id", "parent_preview_id")
    @classmethod
    def canonical_uuid(cls, value):
        if value is not None and str(UUID(value)) != value:
            raise ValueError("historical_price_preview_id_invalid")
        return value

    @field_validator("created_at")
    @classmethod
    def document_timestamp(cls, value):
        if value is not None:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                raise ValueError("historical_price_preview_timestamp_invalid")
        return value

    @model_validator(mode="after")
    def consistent_integrity(self):
        metadata = (
            self.created_at, self.prices_count, self.applied, self.preview_sha256,
            self.pending_count, self.open_count, self.parent_preview_id,
            self.collection_complete, self.manual,
        )
        if self.integrity_status == "unavailable":
            if self.status != "unavailable" or self.error_code is None or any(value is not None for value in metadata):
                raise ValueError("historical_price_preview_unavailable_metadata")
        elif (self.status == "unavailable" or self.error_code is not None
              or any(value is None for value in metadata[:4])):
            raise ValueError("historical_price_preview_verified_metadata")
        return self
