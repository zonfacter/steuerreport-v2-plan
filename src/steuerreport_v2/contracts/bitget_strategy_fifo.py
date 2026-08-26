from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class BitgetStrategyApiHistoryBoundary(BaseModel):
    status: Literal["historical_api_unavailable", "not_required"]
    requested_year: int
    retention_days: int = 90
    classic_spot_history_endpoint: str
    uta_history_endpoint: str
    official_documentation_urls: list[str] = Field(default_factory=list)
    older_data_retrieval: str
    finding: str


class BitgetSupportFileEvidence(BaseModel):
    filename: str
    path: str
    file_sha256: str
    size_bytes: int = 0
    records_count: int = 0
    columns: list[str] = Field(default_factory=list)
    evidence_role: Literal[
        "transfer_evidence",
        "spot_balance_ledger",
        "spot_execution_evidence",
        "derivative_cashflow_ledger",
        "derivative_execution_evidence",
        "strategy_summary_evidence",
    ]
    ledger_imported: bool = False
    contains_individual_executions: bool = False
    contains_strategy_link_field: bool = False
    note: str


class BitgetSupportStrategyMatch(BaseModel):
    settlement_group_id: str
    strategy_id: str
    strategy_row_number: int
    strategy_file_sha256: str
    asset: str
    trading_pair: str
    strategy_type: str
    created_at: datetime
    terminated_at: datetime
    settlement_delta_seconds: Decimal
    investment_amount: Decimal
    total_gains: Decimal
    fee_base_asset: Decimal
    fee_quote_asset: Decimal
    status_upon_termination: str | None = None
    reason_of_termination: str | None = None
    same_pair_window_execution_rows_count: int = 0
    strategy_linked_fill_rows_count: int = 0
    exact_settlement_match: bool = False
    tax_basis_use: Literal["strategy_context_only_not_fifo_cost_basis"] = (
        "strategy_context_only_not_fifo_cost_basis"
    )


class BitgetSupportPackageAudit(BaseModel):
    status: Literal[
        "complete_provider_package_fill_fields_absent",
        "complete_provider_package_exact_fills_available",
        "incomplete_support_package",
        "support_package_unavailable",
    ]
    root_path: str
    expected_files_count: int = 6
    available_files_count: int = 0
    missing_files: list[str] = Field(default_factory=list)
    package_complete: bool = False
    additional_user_export_required: bool = False
    provider_export_field_gap: bool = False
    files: list[BitgetSupportFileEvidence] = Field(default_factory=list)
    strategy_rows_count: int = 0
    spot_execution_rows_count: int = 0
    relevant_strategy_matches_count: int = 0
    strategy_linked_fill_rows_count: int = 0
    same_pair_window_execution_rows_count: int = 0
    relevant_strategy_matches: list[BitgetSupportStrategyMatch] = Field(
        default_factory=list
    )
    findings: list[str] = Field(default_factory=list)
    semantic_sha256: str


class BitgetStrategyReferenceEvidence(BaseModel):
    available: bool = False
    path: str | None = None
    file_sha256: str | None = None
    row_number: int | None = None
    transaction_id: str | None = None
    integration_name: str | None = None
    label: str | None = None
    incoming_asset: str | None = None
    incoming_amount: Decimal | None = None
    comment: str | None = None
    source_type: str | None = None
    source_name: str | None = None
    classification_conflict: bool = False
    reward_classification_effect: Literal["none"] = "none"
    tax_line_effect: Literal["none"] = "none"
    note: str


class BitgetStrategyLinkedDisposal(BaseModel):
    settlement_group_id: str
    source_event_id: str
    event_time: datetime
    asset: str
    pool_id: str
    disposal_quantity: Decimal
    matched_wallet_lot_quantity: Decimal
    missing_wallet_lot_quantity: Decimal
    allocated_strategy_gap_quantity: Decimal
    quantity_fully_allocated: bool = False
    reason: str
    order_number: str | None = None
    quote_asset: str | None = None
    quote_quantity: Decimal | None = None
    raw_object_id: str | None = None
    source_batch_id: str | None = None
    source_filename: str | None = None
    source_file_hash: str | None = None
    source_row_number: int | None = None
    raw_payload_sha256: str | None = None


class BitgetStrategySettlementGap(BaseModel):
    settlement_group_id: str
    year: int
    asset: str
    pool_id: str
    settlement_event_id: str
    settlement_transaction_id: str
    settlement_at: datetime
    settlement_quantity: Decimal
    settlement_reference_value_usdt: Decimal | None = None
    reference_value_tax_use: Literal["plausibility_only_not_cost_basis"] = (
        "plausibility_only_not_cost_basis"
    )
    preview_basis_covered_at_settlement: Decimal = Decimal("0")
    preview_basis_missing_at_settlement: Decimal = Decimal("0")
    predecessor_strategy_out_event_id: str | None = None
    predecessor_strategy_out_transaction_id: str | None = None
    predecessor_strategy_out_at: datetime | None = None
    predecessor_strategy_out_quantity: Decimal = Decimal("0")
    supported_principal_carried_quantity: Decimal = Decimal("0")
    strategy_quantity_without_cost_basis: Decimal = Decimal("0")
    linked_disposals_count: int = 0
    linked_disposal_quantity: Decimal = Decimal("0")
    linked_matched_wallet_lot_quantity: Decimal = Decimal("0")
    allocated_missing_quantity: Decimal = Decimal("0")
    residual_quantity: Decimal = Decimal("0")
    dust_tolerance_quantity: Decimal = Decimal("0")
    quantity_reconciled: bool = False
    quantity_equation: str
    acquisition_time_status: Literal["missing_original_bot_fills"] = (
        "missing_original_bot_fills"
    )
    acquisition_cost_status: Literal["missing_original_bot_fill_cost_basis"] = (
        "missing_original_bot_fill_cost_basis"
    )
    final_tax_status: Literal["strategy_settlement_basis_pending"] = (
        "strategy_settlement_basis_pending"
    )
    reward_classification_effect: Literal["none"] = "none"
    basis_gap_responsibility: Literal[
        "provider_export_field_gap",
        "support_package_incomplete",
        "not_applicable",
    ] = "not_applicable"
    settlement_raw_object_id: str | None = None
    settlement_batch_id: str | None = None
    settlement_filename: str | None = None
    settlement_file_hash: str | None = None
    settlement_row_number: int | None = None
    settlement_raw_payload_sha256: str | None = None
    blockpit_reference: BitgetStrategyReferenceEvidence
    support_strategy_match: BitgetSupportStrategyMatch | None = None
    linked_disposals: list[BitgetStrategyLinkedDisposal] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class BitgetStrategyAssetTotals(BaseModel):
    asset: str
    groups_count: int = 0
    strategy_quantity_without_cost_basis: Decimal = Decimal("0")
    allocated_missing_quantity: Decimal = Decimal("0")
    residual_quantity: Decimal = Decimal("0")


class BitgetStrategyFifoGapReport(BaseModel):
    run_id: str
    generated_at: datetime
    as_of: datetime
    source_run_input_fingerprint_digest: str
    status: Literal[
        "no_gap",
        "quantity_reconciled_basis_pending",
        "blocked_unallocated_quantity",
        "evidence_error",
    ]
    strict_ready: bool = False
    read_only: bool = True
    productive_tables_unchanged: bool = True
    quantity_reconciled: bool = False
    original_acquisition_basis_complete: bool = False
    groups_count: int = 0
    assets: list[str] = Field(default_factory=list)
    years: list[int] = Field(default_factory=list)
    unmatched_disposals_count: int = 0
    out_of_scope_bitget_unmatched_disposals_count: int = 0
    linked_unmatched_disposals_count: int = 0
    unallocated_unmatched_disposals_count: int = 0
    asset_totals: list[BitgetStrategyAssetTotals] = Field(default_factory=list)
    blockpit_reference_count: int = 0
    blockpit_classification_conflict_count: int = 0
    support_package: BitgetSupportPackageAudit
    api_history_boundary: BitgetStrategyApiHistoryBoundary
    groups: list[BitgetStrategySettlementGap] = Field(default_factory=list)
    unallocated_disposals: list[BitgetStrategyLinkedDisposal] = Field(
        default_factory=list
    )
    findings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    semantic_sha256: str
    methodology: str
