from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


TaxAuditChangeKind = Literal["added", "removed", "changed"]
TaxAuditCause = Literal[
    "new_import",
    "previously_unconsidered_source",
    "fifo_lot_assignment",
    "price_or_fx_change",
    "holding_period_classification",
    "rewards_mining_staking",
    "derivatives",
    "correction_or_deletion",
    "unknown",
]
TaxAuditReconciliationStatus = Literal[
    "reconciled",
    "reconciliation_failed",
    "not_available",
]
TaxAuditSourceRole = Literal["primary", "aggregator_mirror", "unknown"]
TaxAuditSourceValidationStatus = Literal[
    "matched_primary_transfer",
    "matched_aggregator_mirror",
    "unmatched_review",
    "not_applicable",
]
TaxAuditTaxInclusionStatus = Literal[
    "included_current_runtime",
    "not_independent_tax_event",
    "pending_review",
    "not_applicable",
]


class TaxAuditSnapshotMetadata(BaseModel):
    snapshot_id: str
    package_name: str
    package_sha256: str
    manifest_sha256: str
    package_generated_at_utc: str | None = None
    package_generated_at_europe_berlin: str | None = None
    created_at_utc: str | None = None
    created_at_europe_berlin: str | None = None
    software_version: str
    method_version: str
    database_fingerprint_sha256: str | None = None
    runtime_fingerprint_sha256: str | None = None
    filing_usage_confirmed: bool = False
    filing_usage_confirmation_event_id: str | None = None
    filing_usage_confirmation_statement: str | None = None
    integrity_status: str
    source_kind: str
    confirmation_scope: str


class TaxAuditEndpointEvidence(BaseModel):
    endpoint: str
    query_timestamp_utc: str
    query_timestamp_europe_berlin: str
    payload_sha256: str | None = None
    source: Literal["reference_package", "current_runtime"]
    available: bool
    note: str | None = None


class TaxAuditDelta(BaseModel):
    position_kind: Literal["tax_line", "reward_income_position", "derivative_line"]
    change_kind: TaxAuditChangeKind
    stable_event_id_or_fingerprint: str
    source: str | None = None
    import_filename: str | None = None
    import_file_sha256: str | None = None
    import_row_number: int | None = None
    event_datetime_utc: str | None = None
    event_datetime_europe_berlin: str | None = None
    asset: str | None = None
    quantity_old: Decimal | None = None
    quantity_new: Decimal | None = None
    quantity_delta: Decimal | None = None
    acquisition_cost_old_eur: Decimal | None = None
    acquisition_cost_new_eur: Decimal | None = None
    acquisition_cost_delta_eur: Decimal | None = None
    disposal_proceeds_old_eur: Decimal | None = None
    disposal_proceeds_new_eur: Decimal | None = None
    disposal_proceeds_delta_eur: Decimal | None = None
    fifo_lot_old: str | None = None
    fifo_lot_new: str | None = None
    old_value_eur: Decimal | None = None
    new_value_eur: Decimal | None = None
    value_delta_eur: Decimal | None = None
    holding_days_old: int | None = None
    holding_days_new: int | None = None
    taxable_old: bool | None = None
    taxable_new: bool | None = None
    classification_policy_old: str | None = None
    classification_policy_new: str | None = None
    cause: TaxAuditCause
    cause_explanation: str
    source_role: TaxAuditSourceRole = "unknown"
    source_validation_status: TaxAuditSourceValidationStatus = "not_applicable"
    logical_event_group_id: str | None = None
    counterpart_event_ids: list[str] = Field(default_factory=list)
    tax_inclusion_status: TaxAuditTaxInclusionStatus = "not_applicable"
    review_required: bool = True
    human_approval_status: Literal["required", "approved", "not_provided"] = "required"
    human_approval_actor: str | None = None
    human_approval_at_utc: str | None = None


class TaxAuditAggregateReconciliation(BaseModel):
    key: str
    label: str
    reference_value_eur: Decimal
    current_value_eur: Decimal
    aggregate_delta_eur: Decimal
    individual_delta_eur: Decimal | None = None
    residual_eur: Decimal | None = None
    status: TaxAuditReconciliationStatus
    source: str
    explanation: str


class TaxAuditCashSeparation(BaseModel):
    trade_swap_volume_eur: Decimal
    actual_eur_deposits_eur: Decimal | None = None
    actual_eur_withdrawals_eur: Decimal | None = None
    taxable_gain_loss_eur: Decimal
    tax_free_gain_loss_eur: Decimal
    internal_transfers_eur: Decimal | None = None
    actual_eur_deposits_status: str
    actual_eur_withdrawals_status: str
    internal_transfers_status: str
    notes: list[str] = Field(default_factory=list)


class TaxAuditSourceEvent(BaseModel):
    event_id: str
    source: str
    source_role: TaxAuditSourceRole
    event_type: str
    source_ref: str | None = None
    tx_id: str | None = None
    event_datetime_utc: str
    asset: str
    quantity: Decimal
    import_filename: str | None = None
    import_file_sha256: str | None = None
    import_row_number: int | None = None
    reported_integration: str | None = None
    tax_inclusion_status: TaxAuditTaxInclusionStatus


class TaxAuditMirrorMatch(BaseModel):
    logical_event_group_id: str
    asset: str
    match_basis: str
    events: list[TaxAuditSourceEvent] = Field(default_factory=list)


class TaxAuditSourceReconciliation(BaseModel):
    status: Literal["verified", "review_required"]
    primary_sources: list[str] = Field(default_factory=list)
    aggregator_sources: list[str] = Field(default_factory=list)
    source_role_counts: dict[str, int] = Field(default_factory=dict)
    matched_mirror_group_count: int = 0
    matched_mirror_event_count: int = 0
    matched_primary_transfer_group_count: int = 0
    matched_primary_transfer_event_count: int = 0
    unmatched_aggregator_event_count: int = 0
    unmatched_aggregator_tax_line_count: int = 0
    unmatched_aggregator_derivative_count: int = 0
    mirror_matches: list[TaxAuditMirrorMatch] = Field(default_factory=list)
    open_review_points: list[str] = Field(default_factory=list)


class TaxAuditReproducibility(BaseModel):
    snapshot_hashes_identical: bool
    tax_line_count_identical: bool
    sums_identical: bool
    delta_list_identical: bool
    status: Literal["reproducible", "not_reproducible", "not_verifiable"]
    reference_input_fingerprint: str
    current_input_fingerprint: str
    differences: list[str] = Field(default_factory=list)


class TaxFilingAuditReport(BaseModel):
    schema_version: str = "tax-filing-audit-v2"
    year: int
    report_id: str
    generated_at_utc: str
    generated_at_europe_berlin: str
    status: Literal["reconciled", "reconciliation_failed", "integrity_blocked", "review_required"]
    reference: TaxAuditSnapshotMetadata | None = None
    current: TaxAuditSnapshotMetadata
    endpoints: list[TaxAuditEndpointEvidence] = Field(default_factory=list)
    deltas: list[TaxAuditDelta] = Field(default_factory=list)
    cause_counts: dict[str, int] = Field(default_factory=dict)
    reconciliation: list[TaxAuditAggregateReconciliation] = Field(default_factory=list)
    cash_separation: TaxAuditCashSeparation
    source_reconciliation: TaxAuditSourceReconciliation
    reproducibility: TaxAuditReproducibility
    tax_line_count_reference: int | None = None
    tax_line_count_current: int
    source_files: list[dict[str, object]] = Field(default_factory=list)
    open_review_points: list[str] = Field(default_factory=list)
    human_approval_required_for_material_changes: bool = True
    human_approvals: list[dict[str, object]] = Field(default_factory=list)
    automatic_tax_correction: bool = False
    database_mutated: bool = False
    report_content_sha256: str
    markdown_content_sha256: str
    json_artifact_endpoint: str
    markdown_artifact_endpoint: str
    methodology: str
