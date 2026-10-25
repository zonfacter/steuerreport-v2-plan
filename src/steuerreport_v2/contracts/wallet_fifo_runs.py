from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from steuerreport_v2.contracts.tax_wallet_fifo import WalletFifoYearDelta


class WalletFifoParallelRunRequest(BaseModel):
    years: list[int] = Field(default_factory=lambda: [2021, 2022, 2023, 2024, 2025], min_length=1)
    as_of: datetime | None = None
    material_delta_threshold_eur: Decimal = Field(default=Decimal("0.01"), ge=0)


class WalletFifoRunInputFingerprint(BaseModel):
    algorithm: Literal["sha256"] = "sha256"
    digest: str
    schema_version: str
    fingerprint_version: str = "wallet_fifo_input_v1"
    component_sha256: dict[str, str] = Field(default_factory=dict)
    canonical_events_count: int = 0
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None
    tax_lines_count: int = 0
    raw_objects_count: int = 0
    review_decisions_count: int = 0
    price_points_count: int = 0


class WalletFifoEvidenceFile(BaseModel):
    kind: str
    path: str
    media_type: str
    records_count: int = 0
    size_bytes: int = 0
    sha256: str
    semantic_sha256: str
    download_url: str | None = None


class WalletFifoAssetReconciliation(BaseModel):
    year: int
    asset: str
    global_quantity: Decimal = Decimal("0")
    wallet_quantity: Decimal = Decimal("0")
    explicit_fee_quantity: Decimal = Decimal("0")
    reconciled_wallet_quantity: Decimal = Decimal("0")
    quantity_delta: Decimal = Decimal("0")
    global_proceeds_eur: Decimal = Decimal("0")
    wallet_proceeds_eur: Decimal = Decimal("0")
    proceeds_delta_eur: Decimal = Decimal("0")
    global_cost_basis_eur: Decimal = Decimal("0")
    wallet_cost_basis_eur: Decimal = Decimal("0")
    cost_basis_delta_eur: Decimal = Decimal("0")
    gain_loss_delta_eur: Decimal = Decimal("0")
    quantity_parity: bool = False
    proceeds_parity: bool = False
    event_set_parity: bool = False
    material_basis_delta: bool = False
    classification: Literal[
        "exact_match",
        "explicit_fee_disposal",
        "method_basis_delta",
        "method_basis_delta_with_explicit_fee",
        "valuation_delta",
        "event_set_mismatch",
    ]


WalletFifoMethodDeltaDriver = Literal[
    "event_set_gap",
    "quantity_gap",
    "proceeds_valuation_delta",
    "quote_asset_fee_netting",
    "quantity_proceeds_allocation",
    "pool_fifo_cost_basis_reordering",
    "explicit_fee_treatment",
    "rounding_only",
    "exact_match",
]


class WalletFifoMethodDeltaEvent(BaseModel):
    year: int
    asset: str
    source_event_id: str
    disposed_at: datetime
    source: str | None = None
    account: str | None = None
    tx_id: str | None = None
    global_quantity: Decimal = Decimal("0")
    wallet_quantity: Decimal = Decimal("0")
    quantity_delta: Decimal = Decimal("0")
    global_proceeds_eur: Decimal = Decimal("0")
    wallet_proceeds_eur: Decimal = Decimal("0")
    proceeds_delta_eur: Decimal = Decimal("0")
    expected_proceeds_delta_eur: Decimal = Decimal("0")
    unexplained_proceeds_delta_eur: Decimal = Decimal("0")
    proceeds_delta_reconciled: bool = False
    quote_asset_fee_netting: bool = False
    global_quote_fee_netting_applied: bool = False
    wallet_quote_fee_netting_applied: bool = False
    fee_asset: str | None = None
    fee_quantity: Decimal = Decimal("0")
    fee_value_eur: Decimal = Decimal("0")
    global_cost_basis_eur: Decimal = Decimal("0")
    wallet_cost_basis_eur: Decimal = Decimal("0")
    cost_basis_delta_eur: Decimal = Decimal("0")
    global_gain_loss_eur: Decimal = Decimal("0")
    wallet_gain_loss_eur: Decimal = Decimal("0")
    gain_loss_delta_eur: Decimal = Decimal("0")
    global_tax_lines_count: int = 0
    wallet_tax_lines_count: int = 0
    explicit_fee_event: bool = False
    global_acquired_at_min: datetime | None = None
    global_acquired_at_max: datetime | None = None
    wallet_acquired_at_min: datetime | None = None
    wallet_acquired_at_max: datetime | None = None
    wallet_pool_ids: list[str] = Field(default_factory=list)
    global_acquisition_sources_count: int = 0
    wallet_acquisition_sources_count: int = 0
    global_acquisition_source_event_ids: list[str] = Field(default_factory=list)
    wallet_acquisition_source_event_ids: list[str] = Field(default_factory=list)
    drivers: list[WalletFifoMethodDeltaDriver] = Field(default_factory=list)
    explanation: str


class WalletFifoMethodDeltaGroup(BaseModel):
    year: int
    asset: str
    global_event_ids_count: int = 0
    wallet_event_ids_count: int = 0
    compared_events_count: int = 0
    material_events_count: int = 0
    explicit_fee_events_count: int = 0
    event_set_gap_events_count: int = 0
    quantity_gap_events_count: int = 0
    proceeds_delta_events_count: int = 0
    quote_asset_fee_events_count: int = 0
    reconciled_proceeds_delta_events_count: int = 0
    pool_reordering_events_count: int = 0
    global_quantity: Decimal = Decimal("0")
    wallet_quantity: Decimal = Decimal("0")
    explicit_fee_quantity: Decimal = Decimal("0")
    reconciled_wallet_quantity: Decimal = Decimal("0")
    quantity_delta: Decimal = Decimal("0")
    global_proceeds_eur: Decimal = Decimal("0")
    wallet_proceeds_eur: Decimal = Decimal("0")
    proceeds_delta_eur: Decimal = Decimal("0")
    expected_proceeds_delta_eur: Decimal = Decimal("0")
    unexplained_proceeds_delta_eur: Decimal = Decimal("0")
    proceeds_reconciliation_ready: bool = False
    global_cost_basis_eur: Decimal = Decimal("0")
    wallet_cost_basis_eur: Decimal = Decimal("0")
    cost_basis_delta_eur: Decimal = Decimal("0")
    global_gain_loss_eur: Decimal = Decimal("0")
    wallet_gain_loss_eur: Decimal = Decimal("0")
    gain_loss_delta_eur: Decimal = Decimal("0")
    event_set_parity: bool = False
    quantity_parity: bool = False
    proceeds_parity: bool = False
    drivers: list[WalletFifoMethodDeltaDriver] = Field(default_factory=list)
    top_events: list[WalletFifoMethodDeltaEvent] = Field(default_factory=list)
    explanation: str


class WalletFifoMethodDeltaExplanationReport(BaseModel):
    run_id: str
    generated_at: datetime
    as_of: datetime
    method_version: str
    status: Literal["blocked", "review", "ready_for_method_review"]
    method_acceptance_required: bool = True
    input_fingerprint_digest: str
    semantic_sha256: str
    years: list[int] = Field(default_factory=list)
    assets: list[str] = Field(default_factory=list)
    material_delta_threshold_eur: Decimal = Decimal("0.01")
    groups_count: int = 0
    material_groups_count: int = 0
    event_set_gap_groups_count: int = 0
    quantity_gap_groups_count: int = 0
    proceeds_delta_groups_count: int = 0
    reconciled_proceeds_delta_groups_count: int = 0
    unexplained_proceeds_delta_groups_count: int = 0
    quote_asset_fee_netting_groups_count: int = 0
    quote_asset_fee_netting_events_count: int = 0
    pool_reordering_groups_count: int = 0
    exact_groups_count: int = 0
    compared_events_count: int = 0
    global_gain_loss_eur: Decimal = Decimal("0")
    wallet_gain_loss_eur: Decimal = Decimal("0")
    gain_loss_delta_eur: Decimal = Decimal("0")
    global_proceeds_eur: Decimal = Decimal("0")
    wallet_proceeds_eur: Decimal = Decimal("0")
    turnover_delta_eur: Decimal = Decimal("0")
    proceeds_contribution_to_gain_delta_eur: Decimal = Decimal("0")
    unexplained_proceeds_delta_eur: Decimal = Decimal("0")
    global_cost_basis_eur: Decimal = Decimal("0")
    wallet_cost_basis_eur: Decimal = Decimal("0")
    cost_basis_delta_eur: Decimal = Decimal("0")
    cost_basis_contribution_to_gain_delta_eur: Decimal = Decimal("0")
    extra_turnover_detected: bool = False
    material_turnover_delta_detected: bool = False
    groups: list[WalletFifoMethodDeltaGroup] = Field(default_factory=list)
    source_run_report_url: str
    full_event_csv_download_url: str
    findings: list[str] = Field(default_factory=list)
    methodology: str


class WalletFifoRunYearResult(BaseModel):
    year: int
    status: Literal["blocked", "review", "ready_for_method_review"]
    global_gain_loss_eur: Decimal = Decimal("0")
    wallet_gain_loss_eur: Decimal = Decimal("0")
    delta_gain_loss_eur: Decimal = Decimal("0")
    material_delta: bool = False
    global_tax_lines_count: int = 0
    wallet_tax_lines_count: int = 0
    unmatched_count: int = 0
    provider_basis_gap_count: int = 0
    unexplained_unmatched_count: int = 0
    transfer_traces_count: int = 0
    unresolved_inbound_provenance_count: int = 0
    transfer_evidence_review_count: int = 0
    acquisition_cost_evidence_review_count: int = 0
    affected_assets: list[str] = Field(default_factory=list)
    event_set_parity: bool = False
    proceeds_parity: bool = False
    event_set_mismatch_assets: list[str] = Field(default_factory=list)
    valuation_review_assets: list[str] = Field(default_factory=list)
    explicit_fee_assets: list[str] = Field(default_factory=list)
    basis_method_delta_assets: list[str] = Field(default_factory=list)
    asset_deltas: list[WalletFifoYearDelta] = Field(default_factory=list)
    asset_reconciliations: list[WalletFifoAssetReconciliation] = Field(default_factory=list)


class WalletFifoParallelRunReport(BaseModel):
    run_id: str
    generated_at: datetime
    as_of: datetime
    years: list[int]
    report_schema_version: str = "wallet_fifo_run_v1"
    method_version: str
    status: Literal["blocked", "review", "ready_for_method_review"]
    strict_ready: bool = False
    method_acceptance_required: bool = True
    material_delta_threshold_eur: Decimal
    input_fingerprint: WalletFifoRunInputFingerprint
    semantic_sha256: str
    input_events_count: int = 0
    pools_count: int = 0
    all_lots_count: int = 0
    open_lots_count: int = 0
    wallet_tax_lines_count: int = 0
    unmatched_count: int = 0
    provider_basis_gap_count: int = 0
    unexplained_unmatched_count: int = 0
    transfer_traces_count: int = 0
    unresolved_inbound_provenance_count: int = 0
    transfer_evidence_review_count: int = 0
    acquisition_cost_evidence_review_count: int = 0
    global_gain_loss_eur: Decimal = Decimal("0")
    wallet_gain_loss_eur: Decimal = Decimal("0")
    delta_gain_loss_eur: Decimal = Decimal("0")
    material_delta_years: list[int] = Field(default_factory=list)
    event_set_parity_years: list[int] = Field(default_factory=list)
    event_set_mismatch_years: list[int] = Field(default_factory=list)
    proceeds_parity_years: list[int] = Field(default_factory=list)
    valuation_review_years: list[int] = Field(default_factory=list)
    blocked_years: list[int] = Field(default_factory=list)
    review_years: list[int] = Field(default_factory=list)
    ready_for_method_review_years: list[int] = Field(default_factory=list)
    year_results: list[WalletFifoRunYearResult] = Field(default_factory=list)
    evidence_files: list[WalletFifoEvidenceFile] = Field(default_factory=list)
    method_delta_explanation_url: str | None = None
    method_delta_explanation_status: Literal[
        "blocked", "review", "ready_for_method_review"
    ] | None = None
    method_delta_explanation_semantic_sha256: str | None = None
    method_delta_event_set_gap_groups_count: int = 0
    method_delta_quantity_gap_groups_count: int = 0
    method_delta_pool_reordering_groups_count: int = 0
    method_delta_unexplained_proceeds_groups_count: int = 0
    method_delta_quote_asset_fee_groups_count: int = 0
    bitget_strategy_gap_report_url: str | None = None
    bitget_strategy_gap_status: str | None = None
    bitget_strategy_gap_semantic_sha256: str | None = None
    bitget_strategy_gap_groups_count: int = 0
    bitget_strategy_gap_linked_disposals_count: int = 0
    bitget_strategy_gap_unallocated_disposals_count: int = 0
    bitget_strategy_gap_quantity_reconciled: bool = False
    bitget_strategy_reconstruction_report_url: str | None = None
    bitget_strategy_reconstruction_csv_url: str | None = None
    bitget_strategy_reconstruction_status: str | None = None
    bitget_strategy_reconstruction_semantic_sha256: str | None = None
    bitget_strategy_reconstruction_groups_count: int = 0
    bitget_strategy_reconstruction_disposals_count: int = 0
    published_as_latest: bool = True
    artifact_path: str
    latest_artifact_path: str | None = None
    findings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    methodology: str


WalletFifoMethodDecisionStatus = Literal[
    "pending",
    "approved_for_controlled_migration",
    "retain_global_fifo_pending_professional_review",
    "rejected_requires_rework",
]


class WalletFifoMethodAcceptanceCheck(BaseModel):
    key: str
    label: str
    passed: bool
    blocking: bool = True
    detail: str


class WalletFifoMethodAcceptanceReport(BaseModel):
    generated_at: datetime
    run_id: str | None = None
    run_generated_at: datetime | None = None
    run_as_of: datetime | None = None
    method_version: str | None = None
    run_status: str = "missing"
    method_delta_status: str = "missing"
    run_input_fingerprint_digest: str | None = None
    current_input_fingerprint_digest: str | None = None
    run_semantic_sha256: str | None = None
    method_delta_semantic_sha256: str | None = None
    input_fingerprint_current: bool = False
    provider_basis_gap_count: int = 0
    unexplained_unmatched_count: int = 0
    provider_basis_event_set_gap_groups_count: int = 0
    provider_basis_quantity_gap_groups_count: int = 0
    unexplained_method_gap_groups_count: int = 0
    provider_basis_resolution_required: bool = False
    decision_ready: bool = False
    decision_status: WalletFifoMethodDecisionStatus = "pending"
    decision_id: str | None = None
    decision_at: datetime | None = None
    decision_actor: str | None = None
    decision_rationale: str | None = None
    method_acceptance_required: bool = True
    active_fifo_scope: str
    target_fifo_scope: str = "wallet_depot_fifo"
    activation_applied: bool = False
    activation_ready: bool = False
    strict_ready: bool = False
    checks: list[WalletFifoMethodAcceptanceCheck] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    methodology: str


class WalletFifoMethodAcceptanceRequest(BaseModel):
    decision: Literal[
        "approved_for_controlled_migration",
        "retain_global_fifo_pending_professional_review",
        "rejected_requires_rework",
    ]
    rationale: str = Field(min_length=20, max_length=2000)
    actor: str = Field(default="user", min_length=2, max_length=120)
    acknowledge_material_tax_delta: Literal[True]
    acknowledge_consistent_application: Literal[True]
    acknowledge_no_automatic_activation: Literal[True]


class WalletFifoMethodAcceptanceResult(BaseModel):
    decision_id: str
    created: bool
    report: WalletFifoMethodAcceptanceReport
