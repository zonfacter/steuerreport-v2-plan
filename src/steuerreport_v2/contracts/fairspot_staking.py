from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class FairspotStakingDecisionLayer(BaseModel):
    config_approved: bool = False
    primary_source_hash_bound: bool = False
    independent_source_hash_bound: bool = False
    independent_routes_complete: bool = False
    quantity_equation_reconciles: bool = False
    canonical_principal_reward_split_bound: bool = False
    canonical_balance_effect_preserved: bool = False
    deterministic_event_ids_bound: bool = False
    wallet_fifo_principal_carry_complete: bool = False
    reward_tax_lot_bound: bool = False


class FairspotStakingReconciliationReport(BaseModel):
    generated_at: datetime
    status: str
    strict_ready: bool = False
    config_path: str
    independent_source_path: str
    primary_source_sha256: str = ""
    independent_source_sha256: str = ""
    main_wallet: str
    staking_wallet: str
    outbound_events_count: int = 0
    return_events_count: int = 0
    reward_events_count: int = 0
    principal_outbound_quantity: Decimal = Decimal("0")
    principal_return_quantity: Decimal = Decimal("0")
    total_received_quantity: Decimal = Decimal("0")
    reward_quantity: Decimal = Decimal("0")
    independent_principal_outbound_quantity: Decimal = Decimal("0")
    independent_total_received_quantity: Decimal = Decimal("0")
    reward_income_eur: Decimal = Decimal("0")
    reward_event_id: str | None = None
    reward_lot_ids: list[str] = Field(default_factory=list)
    source_run_id: str | None = None
    decision_layer: FairspotStakingDecisionLayer
    evidence_refs: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    semantic_sha256: str
    methodology: str
