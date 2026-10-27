"""V1-unabhaengige Tagespreisplanung und explizite Uebernahme."""
from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PriceMapping(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    asset: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_:./-]+$")
    coingecko_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,100}$")
    defillama_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]+:[A-Za-z0-9_-]+$")

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
