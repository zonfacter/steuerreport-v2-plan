from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class SolanaStakingPositionDecisionLayer(BaseModel):
    config_approved: bool = False
    outbound_event_bound: bool = False
    return_event_bound: bool = False
    reward_split_bound: bool = False
    program_route_bound: bool = False
    quantity_equation_reconciles: bool = False
    canonical_balance_effect_preserved: bool = False
    deterministic_event_ids_bound: bool = False
    wallet_fifo_principal_carry_complete: bool = False
    reward_tax_lot_and_price_bound: bool = False
    native_rent_settlement_bound: bool = False


class SolanaStakingPositionReconciliationReport(BaseModel):
    generated_at: datetime
    status: str
    strict_ready: bool = False
    reconciliation_id: str
    year: int
    wallet: str
    program_id: str
    asset: str
    mint: str
    outbound_event_id: str | None = None
    principal_return_event_id: str | None = None
    reward_event_id: str | None = None
    native_settlement_event_id: str | None = None
    principal_quantity: Decimal = Decimal("0")
    received_quantity: Decimal = Decimal("0")
    reward_quantity: Decimal = Decimal("0")
    reward_income_eur: Decimal = Decimal("0")
    reward_lot_ids: list[str] = Field(default_factory=list)
    wallet_fifo_run_id: str | None = None
    wallet_fifo_lots_moved: int = 0
    wallet_fifo_carried_cost_basis_eur: Decimal = Decimal("0")
    native_settlement_quantity: Decimal = Decimal("0")
    decision_layer: SolanaStakingPositionDecisionLayer
    evidence_refs: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    semantic_sha256: str
    methodology: str
