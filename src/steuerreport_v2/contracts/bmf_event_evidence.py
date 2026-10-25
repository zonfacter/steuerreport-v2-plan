from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


BmfEventEvidenceStatus = Literal[
    "blocked",
    "review",
    "ready_for_professional_review",
]
BmfEventEvidenceLineStatus = Literal["blocked", "review", "ready"]
BmfEventEvidenceGroupStatus = Literal[
    "blocked",
    "review",
    "ready",
    "not_applicable",
]
BmfEventPriceQuality = Literal[
    "not_required",
    "independent_current",
    "derived_review",
    "stale_review",
    "derived_stale_review",
    "missing",
]
BmfEventEvidenceScopeMode = Literal["priority_delta", "full_ledger"]
BmfOpeningBalanceDocumentationStatus = Literal[
    "documented_minimum_reconstruction",
    "balance_adjustment_only",
    "undocumented",
]
BmfOriginClassification = Literal[
    "potential_business_inventory",
    "separate_income_review",
    "documented_swap_acquisition",
    "internal_transfer_fifo_carry_review",
    "opening_reconstruction_limit",
    "origin_classification_review",
    "non_reward_origin",
    "missing_origin",
]
BmfOriginTaxSphere = Literal[
    "business_inventory",
    "separate_income",
    "private_acquisition",
    "fifo_carry_forward",
    "opening_reconstruction",
    "non_reward",
    "unclassified",
]


class BmfFifoEventEvidenceRunRequest(BaseModel):
    limit: int = Field(default=200, ge=1, le=5000)
    issue_limit: int = Field(default=500, ge=1, le=20000)
    min_abs_delta_eur: Decimal = Field(default=Decimal("0.01"), ge=0)
    scope_mode: BmfEventEvidenceScopeMode = "priority_delta"


class BmfEventPriceEvidence(BaseModel):
    role: Literal["received", "given"]
    asset: str
    quantity: Decimal = Decimal("0")
    price_id: str | None = None
    price_eur: Decimal | None = None
    priced_at: datetime | None = None
    source: str | None = None
    confidence: Decimal | None = None
    age_hours: Decimal | None = None
    value_eur: Decimal | None = None
    quality: BmfEventPriceQuality


class BmfEventSourceEvidence(BaseModel):
    raw_object_id: str | None = None
    batch_id: str | None = None
    batch_source: str | None = None
    filename: str | None = None
    file_hash: str | None = None
    row_number: int | None = None
    raw_payload_sha256: str | None = None
    identifier_kind: Literal[
        "tx_id",
        "source_ref",
        "raw_batch_row",
        "missing",
    ]
    identifier_value: str | None = None
    status: BmfEventEvidenceLineStatus
    issue_codes: list[str] = Field(default_factory=list)


class BmfOriginResolution(BaseModel):
    classification: BmfOriginClassification
    status: Literal["documented", "review", "blocked"]
    tax_sphere: BmfOriginTaxSphere
    evidence_markers: list[str] = Field(default_factory=list)
    fifo_carry_forward_required: bool = False
    decision_basis: str


class BmfCanonicalEventEvidence(BaseModel):
    event_id: str
    event_time: datetime | None = None
    source: str | None = None
    source_ref: str | None = None
    event_type: str | None = None
    asset: str | None = None
    quantity: Decimal | None = None
    quote_asset: str | None = None
    quote_quantity: Decimal | None = None
    tx_id: str | None = None
    wallet: str | None = None
    account: str | None = None
    confidence: Decimal | None = None
    tax_graph_roles: list[Literal["acquisition", "disposal"]] = Field(
        default_factory=list
    )
    synthetic_derivation: str | None = None
    parent_event_ids: list[str] = Field(default_factory=list)
    parent_source_evidence: list[BmfEventSourceEvidence] = Field(
        default_factory=list
    )
    source_evidence: BmfEventSourceEvidence
    origin_resolution: BmfOriginResolution | None = None
    received_price: BmfEventPriceEvidence | None = None
    given_price: BmfEventPriceEvidence | None = None
    status: BmfEventEvidenceLineStatus
    issue_codes: list[str] = Field(default_factory=list)
    evidence_digest: str


class BmfOriginEvidenceGroup(BaseModel):
    classification: str
    source: str | None = None
    event_type: str | None = None
    asset: str | None = None
    canonical_event_assets: list[str] = Field(default_factory=list)
    unique_origin_events_count: int = 0
    affected_discrepancy_rows_count: int = 0
    raw_evidence_ready_count: int = 0
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None
    status: Literal["documented", "review", "blocked"]
    tax_sphere: BmfOriginTaxSphere
    evidence_markers: list[str] = Field(default_factory=list)
    fifo_carry_forward_required: bool = False
    decision_basis: str
    evidence_digest: str


class BmfOpeningBalanceEvidence(BaseModel):
    event_id: str
    event_time: datetime
    source: str
    account: str | None = None
    asset: str
    quantity: Decimal
    source_ref: str | None = None
    tx_id: str | None = None
    raw_object_id: str | None = None
    raw_filename: str | None = None
    raw_row_number: int | None = None
    raw_payload_sha256: str | None = None
    documentation_status: BmfOpeningBalanceDocumentationStatus
    original_transaction_available: bool = False
    fifo_effect: Literal["initial_lot_only"] = "initial_lot_only"
    live_balance_effect: Literal["none"] = "none"
    tax_event_effect: Literal["none"] = "none"
    limitations: list[str] = Field(default_factory=list)
    evidence_digest: str


class BmfLedgerEvidenceGroup(BaseModel):
    year: int
    source: str
    event_type: str
    events_count: int = 0
    tax_graph_events_count: int = 0
    ready_events_count: int = 0
    review_events_count: int = 0
    blocked_events_count: int = 0
    raw_evidence_ready_count: int = 0
    independent_price_ready_count: int = 0
    derived_price_review_count: int = 0
    stale_price_review_count: int = 0
    missing_price_count: int = 0
    issue_codes: list[str] = Field(default_factory=list)


class BmfFifoDiscrepancyEvidenceRow(BaseModel):
    scope_key: str
    year: int
    asset: str
    disposal_event_id: str
    disposed_at: datetime
    source: str | None = None
    account: str | None = None
    tx_id: str | None = None
    active_global_gain_loss_eur: Decimal = Decimal("0")
    received_first_global_gain_loss_eur: Decimal = Decimal("0")
    active_wallet_gain_loss_eur: Decimal = Decimal("0")
    received_first_wallet_gain_loss_eur: Decimal = Decimal("0")
    price_policy_delta_eur: Decimal = Decimal("0")
    wallet_scope_delta_eur: Decimal = Decimal("0")
    combined_delta_eur: Decimal = Decimal("0")
    interaction_delta_eur: Decimal = Decimal("0")
    disposal_evidence_status: BmfEventEvidenceLineStatus
    acquisition_events_count: int = 0
    acquisition_ready_count: int = 0
    acquisition_review_count: int = 0
    acquisition_blocked_count: int = 0
    acquisition_raw_ready_count: int = 0
    acquisition_independent_price_count: int = 0
    acquisition_issue_event_ids: list[str] = Field(default_factory=list)
    acquisition_issue_event_ids_truncated: bool = False
    acquisition_evidence_digest: str
    origin_classifications: list[str] = Field(default_factory=list)
    status: BmfEventEvidenceLineStatus
    issue_codes: list[str] = Field(default_factory=list)
    asset_fifo_drilldown_endpoint: str


class BmfFifoEventEvidenceGroup(BaseModel):
    scope_key: str
    label: str
    years: list[int] = Field(default_factory=list)
    assets: list[str] = Field(default_factory=list)
    status: BmfEventEvidenceGroupStatus
    discrepancy_rows_count: int = 0
    unique_events_count: int = 0
    ready_events_count: int = 0
    review_events_count: int = 0
    blocked_events_count: int = 0
    raw_evidence_ready_count: int = 0
    independent_price_ready_count: int = 0
    derived_price_review_count: int = 0
    stale_price_review_count: int = 0
    missing_price_count: int = 0
    signed_combined_delta_eur: Decimal = Decimal("0")
    absolute_combined_delta_eur: Decimal = Decimal("0")
    issue_codes: list[str] = Field(default_factory=list)


class BmfFifoEventEvidenceReport(BaseModel):
    run_id: str
    generated_at: datetime
    status: BmfEventEvidenceStatus
    strict_ready: Literal[False] = False
    read_only: Literal[True] = True
    staging_run_id: str
    staging_generated_at: datetime
    staging_input_fingerprint_digest: str
    current_input_fingerprint_digest: str
    staging_matches_current_input: bool = False
    staging_productive_tax_component_sha256: str
    current_productive_tax_component_sha256: str
    staging_matches_current_tax_component: bool = False
    productive_tax_tables_unchanged: bool = False
    scope_complete_for_staging_artifact: bool = True
    full_ledger_scope: bool = False
    ledger_events_count: int = 0
    tax_graph_events_count: int = 0
    tax_graph_missing_events_count: int = 0
    unknown_event_type_count: int = 0
    unknown_tax_graph_events_count: int = 0
    staging_rows_count: int = 0
    selected_discrepancy_rows_count: int = 0
    unique_events_count: int = 0
    ready_events_count: int = 0
    review_events_count: int = 0
    blocked_events_count: int = 0
    raw_evidence_ready_count: int = 0
    independent_price_ready_count: int = 0
    derived_price_review_count: int = 0
    stale_price_review_count: int = 0
    missing_price_count: int = 0
    missing_canonical_events_count: int = 0
    missing_raw_evidence_count: int = 0
    missing_required_identifiers_count: int = 0
    unresolved_origin_rows_count: int = 0
    documented_business_inventory_rows_count: int = 0
    documented_swap_acquisition_rows_count: int = 0
    internal_transfer_fifo_carry_rows_count: int = 0
    opening_reconstruction_rows_count: int = 0
    unclassified_origin_rows_count: int = 0
    separate_income_review_rows_count: int = 0
    opening_balance_events_count: int = 0
    signed_combined_delta_eur: Decimal = Decimal("0")
    absolute_combined_delta_eur: Decimal = Decimal("0")
    groups: list[BmfFifoEventEvidenceGroup] = Field(default_factory=list)
    ledger_groups: list[BmfLedgerEvidenceGroup] = Field(default_factory=list)
    origin_evidence_groups: list[BmfOriginEvidenceGroup] = Field(
        default_factory=list
    )
    opening_balance_evidence: list[BmfOpeningBalanceEvidence] = Field(
        default_factory=list
    )
    discrepancy_rows: list[BmfFifoDiscrepancyEvidenceRow] = Field(
        default_factory=list
    )
    discrepancy_rows_truncated: bool = False
    event_issues: list[BmfCanonicalEventEvidence] = Field(default_factory=list)
    event_issues_truncated: bool = False
    artifact_path: str
    latest_artifact_path: str
    all_event_evidence_artifact_path: str | None = None
    all_event_evidence_artifact_sha256: str | None = None
    all_event_evidence_artifact_bytes: int = 0
    all_event_evidence_compression: Literal["gzip-jsonl"] | None = None
    findings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    methodology: str
