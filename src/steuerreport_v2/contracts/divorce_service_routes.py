from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from steuerreport_v2.contracts.review import ReviewDecision


class DivorceServiceRouteDecisionLayer(BaseModel):
    canonical_event_bound: bool = False
    owned_wallet_registry_bound: bool = False
    opening_transaction_successful: bool = False
    opening_time_matches_event: bool = False
    owned_wallet_signed_opening: bool = False
    wallet_debit_matches_event: bool = False
    wallet_debit_reconciles_components: bool = False
    jupiter_perps_program_bound: bool = False
    instant_increase_position_bound: bool = False
    wsol_collateral_transfer_bound: bool = False
    position_account_bound: bool = False
    collateral_log_bound: bool = False
    full_liquidation_before_end_date: bool = False
    liquidation_position_account_bound: bool = False
    no_successful_activity_after_liquidation: bool = False
    residual_account_rent_same_day_priced: bool = False
    residual_account_rent_below_materiality: bool = False


class DivorceServiceRouteLifecycleRow(BaseModel):
    tx_id: str
    block_time: datetime | None = None
    slot: int | None = None
    successful: bool = False
    instruction: str | None = None
    note: str


class DivorceServiceRouteEvidenceFile(BaseModel):
    kind: Literal[
        "opening_get_transaction",
        "position_signatures",
        "liquidation_get_transaction",
    ]
    path: str
    media_type: str = "application/gzip"
    size_bytes: int
    sha256: str


class DivorceServiceRouteEvidenceRefreshRequest(BaseModel):
    tx_id: str = Field(
        min_length=64, max_length=128, pattern=r"^[1-9A-HJ-NP-Za-km-z]+$"
    )
    end_asset_date: date = date(2026, 7, 24)
    materiality_threshold_eur: Decimal = Field(default=Decimal("1"), ge=0)
    timeout_seconds: int = Field(default=20, ge=3, le=60)


class DivorceServiceRouteEvidenceReport(BaseModel):
    generated_at: datetime
    status: Literal["ready_for_review", "review_required", "failed"]
    strict_ready: bool = False
    provider: Literal["solana_public_rpc"] = "solana_public_rpc"
    end_asset_date: date
    materiality_threshold_eur: Decimal
    tx_id: str
    canonical_event_id: str | None = None
    canonical_event_time: datetime | None = None
    canonical_asset: str | None = None
    canonical_quantity: Decimal | None = None
    wallet: str | None = None
    wallet_source_id: str | None = None
    opening_slot: int | None = None
    opening_block_time: datetime | None = None
    opening_fee_lamports: int | None = None
    wallet_debit_lamports: int | None = None
    collateral_lamports: int | None = None
    position_account_rent_lamports: int | None = None
    wrapped_account_rent_return_lamports: int | None = None
    position_account: str | None = None
    collateral_quantity: Decimal | None = None
    collateral_added_usd: Decimal | None = None
    opening_fee_usd: Decimal | None = None
    opening_price_usd: Decimal | None = None
    lifecycle_signatures_count: int = 0
    successful_lifecycle_count: int = 0
    failed_lifecycle_count: int = 0
    liquidation_tx_id: str | None = None
    liquidation_slot: int | None = None
    liquidation_block_time: datetime | None = None
    liquidation_instruction: str | None = None
    liquidation_exit_price_usd: Decimal | None = None
    liquidation_fee_usd: Decimal | None = None
    liquidation_net_loss_usd: Decimal | None = None
    residual_position_account_lamports: int | None = None
    residual_position_account_quantity: Decimal | None = None
    residual_position_account_price_eur: Decimal | None = None
    residual_position_account_priced_at: datetime | None = None
    residual_position_account_price_source: str | None = None
    residual_position_account_value_eur: Decimal | None = None
    decision_layer: DivorceServiceRouteDecisionLayer
    lifecycle: list[DivorceServiceRouteLifecycleRow] = Field(default_factory=list)
    evidence_files: list[DivorceServiceRouteEvidenceFile] = Field(default_factory=list)
    artifact_path: str | None = None
    semantic_sha256: str
    errors: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    methodology: str


class DivorceServiceRouteDecisionRequest(BaseModel):
    tx_id: str = Field(
        min_length=64, max_length=128, pattern=r"^[1-9A-HJ-NP-Za-km-z]+$"
    )
    semantic_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    rationale: str | None = None
    actor: str = "user"


class DivorceServiceRouteDecisionResult(BaseModel):
    already_recorded: bool = False
    decision: ReviewDecision
    evidence: DivorceServiceRouteEvidenceReport


class DivorceServiceRouteAcceptedDecision(BaseModel):
    tx_id: str
    evidence_semantic_sha256: str
    decision: ReviewDecision


class DivorceServiceRouteEvidenceBundle(BaseModel):
    generated_at: datetime
    reports_count: int = 0
    reports: list[DivorceServiceRouteEvidenceReport] = Field(default_factory=list)
    accepted_decisions_count: int = 0
    accepted_decisions: list[DivorceServiceRouteAcceptedDecision] = Field(
        default_factory=list
    )
    classification_effect: Literal["divorce_capital_flow_only"] = (
        "divorce_capital_flow_only"
    )
    import_effect: Literal["none"] = "none"
    ledger_effect: Literal["none"] = "none"
    fifo_effect: Literal["none"] = "none"
    tax_classification_effect: Literal["none"] = "none"
