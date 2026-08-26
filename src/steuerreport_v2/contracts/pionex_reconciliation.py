from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class PionexHntReconciliationDecisionLayer(BaseModel):
    config_enabled: bool = False
    source_files_integrity_valid: bool = False
    source_exports_reconcile: bool = False
    executed_canceled_partials_complete: bool = False
    historical_api_exhausted: bool = False
    database_primary_import_complete: bool = False
    adjustment_event_bound: bool = False
    balance_reconciles: bool = False
    zero_cost_tax_lot_bound: bool = False
    tax_treatment_explicit: bool = False


class PionexHntReconciliationReport(BaseModel):
    generated_at: datetime
    status: str
    preflight_ready: bool = False
    reconciliation_ready: bool = False
    wallet_fifo_ready: bool = False
    strict_ready: bool = False
    missing_primary_acquisition_evidence: bool = True
    config_path: str
    source_dir: str
    api_probe_path: str
    raw_export_sha256: str = ""
    summary_export_sha256: str = ""
    api_probe_sha256: str = ""
    raw_export_rows: int = 0
    summary_export_rows: int = 0
    aggregate_groups: int = 0
    canceled_partial_fills_count: int = 0
    canceled_buy_quantity: Decimal = Decimal("0")
    canceled_sell_quantity: Decimal = Decimal("0")
    canceled_base_fee_quantity: Decimal = Decimal("0")
    canceled_net_quantity: Decimal = Decimal("0")
    imported_raw_objects: int = 0
    imported_canceled_events: int = 0
    account: str
    asset: str
    deficit_event_time: datetime
    adjustment_event_time: datetime
    adjustment_quantity: Decimal
    adjustment_cost_basis_eur: Decimal
    adjustment_event_id: str | None = None
    balance_min_quantity: Decimal | None = None
    balance_final_quantity: Decimal | None = None
    expected_balance_min_quantity: Decimal
    expected_balance_final_quantity: Decimal
    zero_cost_lot_ids: list[str] = Field(default_factory=list)
    zero_cost_lot_consumed_quantity: Decimal = Decimal("0")
    zero_cost_lot_proceeds_eur: Decimal = Decimal("0")
    zero_cost_lot_gain_loss_eur: Decimal = Decimal("0")
    historical_api_rows: int = 0
    decision_layer: PionexHntReconciliationDecisionLayer
    evidence_refs: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    methodology: str
