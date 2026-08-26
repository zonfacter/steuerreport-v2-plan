from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class ServiceSwapTaxMappingDecisionLayer(BaseModel):
    config_enabled: bool = False
    evidence_integrity_valid: bool = False
    evidence_sha_matches: bool = False
    evidence_route_ready: bool = False
    source_event_matches: bool = False
    funding_event_matches: bool = False
    deposit_event_matches: bool = False
    deposit_mirrors_reconcile: bool = False
    swap_timestamp_matches: bool = False
    asset_quantities_reconcile: bool = False
    direct_costs_reconcile: bool = False
    pools_explicit: bool = False
    tax_treatment_explicit: bool = False


class ServiceSwapTaxMappingRecord(BaseModel):
    mapping_id: str
    year: int
    status: str
    tax_mapping_ready: bool = False
    evidence_semantic_sha256: str
    source_event_id: str
    source_event_time: datetime
    funding_event_id: str
    funding_event_time: datetime
    deposit_event_id: str
    deposit_event_time: datetime
    deposit_mirror_event_ids: list[str] = Field(default_factory=list)
    swap_tx_id: str
    swap_event_time: datetime
    source_asset: str
    source_quantity: Decimal
    acquired_asset: str
    acquired_quantity: Decimal
    source_direct_cost_quantity: Decimal
    funding_direct_cost_quantity: Decimal
    direct_cost_asset: str
    direct_cost_quantity: Decimal
    output_withheld_quantity: Decimal
    source_pool_id: str
    deposit_evidence_pool_id: str
    target_pool_id: str
    valuation_method: str
    direct_cost_treatment: str
    tax_treatment: str
    decision_layer: ServiceSwapTaxMappingDecisionLayer
    evidence_ref: str
    bmf_reference: str


class ServiceSwapTaxMappingReport(BaseModel):
    generated_at: datetime
    status: str
    strict_ready: bool = False
    config_path: str
    evidence_dir: str
    mappings_count: int = 0
    ready_count: int = 0
    review_count: int = 0
    records: list[ServiceSwapTaxMappingRecord] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    methodology: str
