from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field

from steuerreport_v2.contracts.pipeline import PipelineResult


class BlockpitSolanaClassPreflight(BaseModel):
    row_class: str
    rows: int
    status: str
    missing_latest_price_assets: list[str]
    required_opening_balance: dict[str, Decimal]
    gross_positive_movements: dict[str, Decimal]
    gross_negative_movements: dict[str, Decimal]
    blocker_codes: list[str]


class BlockpitSolanaOpeningBalanceEvidenceCandidate(BaseModel):
    score: int
    event_time: str
    source: str
    event_type: str
    account: str | None = None
    quantity: Decimal
    required_quantity: Decimal
    quantity_delta: Decimal
    tx_id: str | None = None
    source_ref: str | None = None
    reasons: list[str]


class BlockpitSolanaOpeningBalanceIncident(BaseModel):
    asset: str
    required_quantity: Decimal
    first_deficit_at: str
    row_class: str
    balance_before: Decimal
    movement_quantity: Decimal
    balance_after: Decimal
    source_row: dict[str, str]
    evidence_candidates: list[BlockpitSolanaOpeningBalanceEvidenceCandidate] = Field(
        default_factory=list
    )


class BlockpitSolanaCombinedReadiness(BaseModel):
    status: str
    required_opening_balance: dict[str, Decimal]
    incidents: list[BlockpitSolanaOpeningBalanceIncident]
    gross_positive_movements: dict[str, Decimal]
    gross_negative_movements: dict[str, Decimal]


class BlockpitSolanaPriceSourceStatus(BaseModel):
    asset: str
    configured: bool
    provider_id: str | None = None
    status: str


class BlockpitSolanaHistoricalPriceRequirement(BaseModel):
    asset: str
    price_date: date
    row_class: str
    event_count: int
    gross_quantity: Decimal
    provider_id: str | None = None
    status: str


class BlockpitSolanaPreflightReport(BaseModel):
    file_path: str
    integration: str
    max_year: int | None
    account: str
    filtered_rows: int
    skipped_unknown_assets: int
    skipped_class_counts: dict[str, int]
    class_counts: dict[str, int]
    classes: list[BlockpitSolanaClassPreflight]
    combined_readiness: BlockpitSolanaCombinedReadiness
    price_source_status: list[BlockpitSolanaPriceSourceStatus]
    historical_price_requirements: list[BlockpitSolanaHistoricalPriceRequirement]
    importable_classes: list[str]
    blocked_classes: list[str]
    target_changed: bool = False


class BlockpitSolanaPriceProbeRequest(BaseModel):
    file_path: str = "/workspace/steuerreport/usertransfer/blockpit/blockpit 09052026 Transactions.csv"
    integration: str = "Solana"
    max_year: int | None = 2024
    account: str = "Solana"
    price_config_path: str = "/workspace/steuerreport-v2-plan/configs/crypto_price_sources.json"
    v1_fx_db_path: str = "/root/.local/share/steuerreport/steuerreport.db"
    provider: str = "auto"
    assets: list[str] = Field(default_factory=list)
    max_requests: int = 25
    timeout_seconds: int = 20
    confidence: Decimal = Decimal("1.0")
    dry_run: bool = True


class BlockpitSolanaPriceProbeJob(BaseModel):
    asset: str
    price_date: date
    row_class: str
    event_count: int
    gross_quantity: Decimal
    provider_id: str | None = None
    status: str
    reason: str | None = None
    price_usd: Decimal | None = None
    usd_eur: Decimal | None = None
    price_eur: Decimal | None = None
    source: str | None = None


class BlockpitSolanaPriceProbeResult(BaseModel):
    requirements_count: int
    asset_filter: list[str]
    attempted: int
    available: int
    skipped: int
    failed: int
    max_requests: int
    imported_prices: int = 0
    dry_run: bool = True
    target_changed: bool = False
    jobs: list[BlockpitSolanaPriceProbeJob]
    pipeline: PipelineResult | None = None
