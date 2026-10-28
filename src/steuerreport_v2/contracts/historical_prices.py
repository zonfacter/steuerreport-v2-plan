"""V1-unabhaengige Tagespreisplanung und explizite Uebernahme."""
from datetime import date
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
