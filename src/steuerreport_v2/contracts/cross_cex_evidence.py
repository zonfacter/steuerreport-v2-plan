from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class CrossCexTransferDecisionLayer(BaseModel):
    registry_approval_present: bool = False
    source_and_target_owned: bool = False
    source_withdrawal_log_bound: bool = False
    target_transaction_id_bound: bool = False
    source_and_target_raw_hashes_bound: bool = False
    deterministic_event_ids_bound: bool = False
    time_window_reconciles: bool = False
    quantity_and_fee_reconcile: bool = False
    wallet_fifo_lot_carry_complete: bool = False


class CrossCexTransferEvidenceRecord(BaseModel):
    evidence_id: str
    year: int
    tx_id: str
    asset: str
    quantity: Decimal
    fee_quantity: Decimal
    source_id: str
    target_source_id: str
    source_pool_id: str
    target_pool_id: str
    source_event_id: str
    target_event_id: str
    source_event_time: datetime
    target_event_time: datetime
    time_delta_seconds: Decimal
    source_filename: str
    source_file_hash: str
    source_row_number: int | None = None
    target_filename: str
    target_file_hash: str
    target_row_number: int | None = None
    lots_moved: int = 0
    carried_cost_basis_eur: Decimal = Decimal("0")
    status: str
    ready: bool = False
    decision_layer: CrossCexTransferDecisionLayer
    evidence_refs: list[str] = Field(default_factory=list)


class CrossCexTransferEvidenceReport(BaseModel):
    generated_at: datetime
    status: str
    strict_ready: bool = False
    config_path: str
    latest_wallet_fifo_run_path: str
    source_run_id: str | None = None
    source_run_semantic_sha256: str | None = None
    transfer_trace_sha256: str | None = None
    records_count: int = 0
    ready_count: int = 0
    review_count: int = 0
    years: list[int] = Field(default_factory=list)
    records: list[CrossCexTransferEvidenceRecord] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    semantic_sha256: str
    methodology: str
