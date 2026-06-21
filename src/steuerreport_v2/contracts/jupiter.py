from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class JupiterTokenSearchRequest(BaseModel):
    query: str


class JupiterApiKeyWrite(BaseModel):
    api_key: str


class JupiterApiKeyWriteResult(BaseModel):
    status: str
    written_keys: list[str] = Field(default_factory=list)
    message: str


class JupiterTokenAudit(BaseModel):
    mint_authority_disabled: bool | None = None
    freeze_authority_disabled: bool | None = None
    top_holders_percentage: Decimal | None = None
    dev_mints: int | None = None


class JupiterTokenSearchItem(BaseModel):
    id: str
    name: str | None = None
    symbol: str | None = None
    icon: str | None = None
    decimals: int | None = None
    token_program: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    website: str | None = None
    twitter: str | None = None
    dev: str | None = None
    holder_count: int | None = None
    organic_score: Decimal | None = None
    organic_score_label: str | None = None
    is_verified: bool | None = None
    tags: list[str] = Field(default_factory=list)
    fdv_usd: Decimal | None = None
    market_cap_usd: Decimal | None = None
    usd_price: Decimal | None = None
    price_block_id: int | None = None
    liquidity_usd: Decimal | None = None
    audit: JupiterTokenAudit | None = None


class JupiterTokenSearchResult(BaseModel):
    generated_at: datetime
    query: str
    configured: bool
    status: str
    tokens: list[JupiterTokenSearchItem] = Field(default_factory=list)
    tokens_count: int = 0
    source_url: str = "https://api.jup.ag/tokens/v2/search"
    methodology: str


class JupiterTokenMetadataCacheItem(BaseModel):
    mint: str
    symbol: str | None = None
    name: str | None = None
    decimals: int | None = None
    icon: str | None = None
    token_program: str | None = None
    is_verified: bool | None = None
    organic_score: Decimal | None = None
    organic_score_label: str | None = None
    holder_count: int | None = None
    liquidity_usd: Decimal | None = None
    usd_price: Decimal | None = None
    market_cap_usd: Decimal | None = None
    risk_status: str
    source: str = "jupiter_tokens_v2"
    discovered_sources: list[str] = Field(default_factory=list)
    refreshed_at: datetime
    jupiter_updated_at: datetime | None = None


class JupiterTokenMetadataCacheResult(BaseModel):
    generated_at: datetime
    configured: bool
    status: str
    candidates_count: int
    cached_count: int
    uncached_count: int
    items: list[JupiterTokenMetadataCacheItem] = Field(default_factory=list)
    methodology: str


class JupiterTokenMetadataRefreshResult(BaseModel):
    generated_at: datetime
    configured: bool
    status: str
    candidates_count: int
    requested_count: int
    refreshed_count: int
    cached_count: int
    uncached_count: int
    skipped_count: int
    items: list[JupiterTokenMetadataCacheItem] = Field(default_factory=list)
    methodology: str


class JupiterTokenRiskReviewResult(BaseModel):
    generated_at: datetime
    status: str
    risk_status: str
    items_count: int
    spam_review_count: int
    review_count: int
    unverified_plausible_count: int
    verified_count: int
    items: list[JupiterTokenMetadataCacheItem] = Field(default_factory=list)
    methodology: str
