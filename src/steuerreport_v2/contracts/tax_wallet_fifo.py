from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class WalletFifoPreviewLot(BaseModel):
    lot_id: str
    pool_id: str
    asset: str
    acquired_at: datetime
    quantity_total: Decimal
    quantity_remaining: Decimal
    cost_basis_eur_total: Decimal
    source_event_id: str
    origin_lot_id: str | None = None


class WalletFifoPreviewLine(BaseModel):
    tax_line_id: str
    pool_id: str
    asset: str
    acquired_at: datetime
    disposed_at: datetime
    quantity: Decimal
    acquisition_cost_eur: Decimal
    disposal_proceeds_eur: Decimal
    gain_loss_eur: Decimal
    holding_days: int
    source_event_id: str
    lot_id: str


class WalletFifoPreviewUnmatched(BaseModel):
    source_event_id: str
    event_time: datetime
    event_type: str
    pool_id: str
    asset: str
    quantity: Decimal
    matched_quantity: Decimal
    missing_quantity: Decimal
    reason: str


class WalletFifoTransferTrace(BaseModel):
    tx_id: str
    asset: str
    event_time: datetime
    source_pool_id: str
    target_pool_id: str
    quantity: Decimal
    fee_quantity: Decimal | None = None
    lots_moved: int = 0
    carried_cost_basis_eur: Decimal = Decimal("0")
    status: str
    source_event_id: str
    target_event_id: str


class WalletFifoYearDelta(BaseModel):
    year: int
    asset: str
    pool_id: str | None = None
    global_gain_loss_eur: Decimal = Decimal("0")
    wallet_gain_loss_eur: Decimal = Decimal("0")
    delta_eur: Decimal = Decimal("0")
    global_tax_lines_count: int = 0
    wallet_tax_lines_count: int = 0


class WalletFifoPreviewReport(BaseModel):
    generated_at: datetime
    method_version: str
    status: str
    pools_count: int = 0
    lots_count: int = 0
    tax_lines_count: int = 0
    unmatched_count: int = 0
    transfer_traces_count: int = 0
    unresolved_inbound_provenance_count: int = 0
    global_gain_loss_eur: Decimal = Decimal("0")
    wallet_gain_loss_eur: Decimal = Decimal("0")
    delta_gain_loss_eur: Decimal = Decimal("0")
    year_deltas: list[WalletFifoYearDelta] = Field(default_factory=list)
    unmatched: list[WalletFifoPreviewUnmatched] = Field(default_factory=list)
    transfer_traces: list[WalletFifoTransferTrace] = Field(default_factory=list)
    sample_lines: list[WalletFifoPreviewLine] = Field(default_factory=list)
    methodology: str


class LegacyHeliumWalletSummary(BaseModel):
    address: str
    label: str
    role: Literal["main_legacy_wallet", "staking_counterparty", "migration_target"]
    included_in_portfolio: bool = False
    current_portfolio_value_eur: Decimal = Decimal("0")
    canonical_events_count: int = 0
    mining_events_count: int = 0
    transfer_events_count: int = 0
    fee_events_count: int = 0
    net_hnt_quantity: Decimal = Decimal("0")
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None
    note: str
    evidence_url: str | None = None


class LegacyHeliumTransferEvidence(BaseModel):
    raw_object_id: str
    source: str
    filename: str | None = None
    row_number: int | None = None
    event_time: str | None = None
    tx_id: str | None = None
    asset: str = "HNT"
    quantity: Decimal = Decimal("0")
    payer: str | None = None
    payee: str | None = None
    direction: Literal["main_to_fairspot", "fairspot_to_main", "other_legacy_transfer"]
    fifo_classification: str = "transfer_counterparty"
    included_in_portfolio: bool = False
    evidence_ref: str


class LegacyHeliumOverviewReport(BaseModel):
    generated_at: datetime
    asset: str = "HNT"
    main_legacy_wallet: str
    fairspot_staking_wallet: str
    solana_migration_wallet: str
    wallets: list[LegacyHeliumWalletSummary] = Field(default_factory=list)
    fairspot_transfers: list[LegacyHeliumTransferEvidence] = Field(default_factory=list)
    fairspot_transfers_count: int = 0
    included_in_portfolio_count: int = 0
    total_canonical_events_count: int = 0
    total_net_hnt_quantity: Decimal = Decimal("0")
    methodology: str


class WalletFifoGapCandidateEvent(BaseModel):
    event_id: str
    event_time: datetime
    event_type: str
    source: str
    account: str | None = None
    pool_id: str
    asset: str
    quantity: Decimal
    quote_asset: str | None = None
    quote_quantity: Decimal | None = None
    tx_id: str | None = None
    source_ref: str | None = None
    raw_object_id: str | None = None
    relation: str
    seconds_before_gap: int | None = None


class WalletFifoGapDiagnosis(BaseModel):
    gap_id: str
    event_time: datetime
    pool_id: str
    asset: str
    missing_quantity: Decimal
    disposal_event_id: str
    disposal_event_type: str
    reason: str
    likely_cause: str
    recommended_action: str
    candidate_events: list[WalletFifoGapCandidateEvent] = Field(default_factory=list)


class WalletFifoGapDiagnosisReport(BaseModel):
    generated_at: datetime
    year: int
    gaps_count: int = 0
    affected_assets: list[str] = Field(default_factory=list)
    affected_pools: list[str] = Field(default_factory=list)
    likely_causes: dict[str, int] = Field(default_factory=dict)
    diagnoses: list[WalletFifoGapDiagnosis] = Field(default_factory=list)
    methodology: str


class WalletFifoOriginRawEvidence(BaseModel):
    raw_object_id: str
    batch_id: str
    source: str | None = None
    filename: str | None = None
    row_number: int | None = None
    payload: dict[str, str | int | float | None] = Field(default_factory=dict)


class WalletFifoOriginTrace(BaseModel):
    trace_id: str
    year: int
    asset: str
    pool_id: str
    missing_quantity: Decimal
    gap_event_id: str
    gap_event_time: datetime
    likely_cause: str
    candidate_event: WalletFifoGapCandidateEvent | None = None
    transaction_history_evidence: WalletFifoOriginRawEvidence | None = None
    deposit_history_evidence: WalletFifoOriginRawEvidence | None = None
    onchain_tx_id: str | None = None
    deposit_address: str | None = None
    network: str | None = None
    recommended_action: str


class WalletFifoOriginTraceReport(BaseModel):
    generated_at: datetime
    year: int
    traces_count: int = 0
    traces: list[WalletFifoOriginTrace] = Field(default_factory=list)
    methodology: str


class WalletFifoCexDepositTransferEvidence(BaseModel):
    evidence_id: str
    year: int
    cex: str
    asset: str
    network: str | None = None
    onchain_time: datetime | None = None
    cex_credit_time: datetime | None = None
    credited_quantity: Decimal
    onchain_quantity: Decimal | None = None
    quantity_delta: Decimal | None = None
    sender_address: str | None = None
    deposit_address: str | None = None
    cex_main_wallet: str | None = None
    tx_id: str | None = None
    deposit_raw_object_id: str | None = None
    deposit_row_number: int | None = None
    cex_event_id: str | None = None
    cex_account: str | None = None
    fifo_transfer_status: str
    fifo_source_pool_id: str | None = None
    fifo_target_pool_id: str | None = None
    fifo_lots_moved: int = 0
    carried_cost_basis_eur: Decimal = Decimal("0")
    tax_label: str
    holding_period_continues: bool = False
    evidence_status: str
    missing_evidence: list[str] = Field(default_factory=list)
    recommended_action: str


class WalletFifoCexDepositTransferEvidenceReport(BaseModel):
    generated_at: datetime
    year: int
    cex: str = "binance"
    network: str | None = None
    deposits_count: int = 0
    transfer_neutral_count: int = 0
    evidence_ready_count: int = 0
    missing_evidence_count: int = 0
    total_credited_quantity_by_asset: dict[str, Decimal] = Field(default_factory=dict)
    total_carried_cost_basis_eur: Decimal = Decimal("0")
    deposits: list[WalletFifoCexDepositTransferEvidence] = Field(default_factory=list)
    methodology: str


class WalletFifoCexSenderOwnershipDecision(BaseModel):
    txid: str
    timestamp_utc: datetime | None = None
    asset: str
    amount: Decimal
    provider_status: str
    onchain_sender: str | None = None
    onchain_sender_label: str | None = None
    sender_classification: str | None = None
    primary_signer: str | None = None
    deposit_address: str | None = None
    cex_account: str | None = None
    fifo_transfer_status: str | None = None
    carried_cost_basis_eur: Decimal = Decimal("0")
    program_ids: list[str] = Field(default_factory=list)
    decision_layer: dict[str, bool] = Field(default_factory=dict)
    final_tax_status: str
    review_note: str


class WalletFifoCexSenderOwnershipSummaryReport(BaseModel):
    generated_at: datetime
    year: int
    cex: str = "binance"
    network: str | None = None
    artifact_path: str | None = None
    artifact_exists: bool = False
    transactions_count: int = 0
    status_counts: dict[str, int] = Field(default_factory=dict)
    tax_neutral_candidates: int = 0
    complex_route_review: int = 0
    unverified_third_party: int = 0
    pending_review: int = 0
    decisions: list[WalletFifoCexSenderOwnershipDecision] = Field(default_factory=list)
    methodology: str


CexSenderOwnershipDecisionStatus = Literal[
    "tax_neutral_transfer_reviewed",
    "exchange_outflow_evidence_required",
    "unverified_sender_review_open",
]


class WalletFifoCexSenderOwnershipReviewDecisionCreate(BaseModel):
    txid: str
    decision_status: CexSenderOwnershipDecisionStatus
    title: str | None = None
    rationale: str | None = None


class WalletFifoCexSenderOwnershipReviewDecisionResult(BaseModel):
    decision_id: str
    scope: str
    decision_status: CexSenderOwnershipDecisionStatus
    txid: str


CexExchangeOutflowDecisionStatus = Literal[
    "transfer_neutral_fifo_carry_forward_reviewed",
    "exchange_outflow_evidence_review_open",
]


class WalletFifoCexExchangeOutflowReviewDecisionCreate(BaseModel):
    deposit_txid: str
    decision_status: CexExchangeOutflowDecisionStatus
    title: str | None = None
    rationale: str | None = None


class WalletFifoCexExchangeOutflowReviewDecisionResult(BaseModel):
    decision_id: str
    scope: str
    decision_status: CexExchangeOutflowDecisionStatus
    deposit_txid: str


class WalletFifoCexExchangeOutflowCandidate(BaseModel):
    event_id: str
    event_time: datetime
    source: str
    account: str | None = None
    asset: str
    quantity: Decimal
    seconds_delta: int
    amount_delta: Decimal
    tx_id: str | None = None
    raw_object_id: str | None = None
    withdrawal_tx_id: str | None = None
    withdrawal_address: str | None = None
    withdrawal_network: str | None = None
    withdrawal_amount: Decimal | None = None
    withdrawal_fee: Decimal | None = None
    evidence_status: str
    recommended_action: str


class WalletFifoCexExchangeOutflowEvidenceRow(BaseModel):
    deposit_txid: str
    deposit_time: datetime | None = None
    target_cex: str = "binance"
    source_exchange: str = "bitget"
    source_sender: str | None = None
    source_sender_label: str | None = None
    deposit_address: str | None = None
    asset: str
    amount: Decimal
    status: str
    candidates_count: int = 0
    best_candidate: WalletFifoCexExchangeOutflowCandidate | None = None
    candidates: list[WalletFifoCexExchangeOutflowCandidate] = Field(default_factory=list)
    recommended_action: str


class WalletFifoCexExchangeOutflowEvidenceReport(BaseModel):
    generated_at: datetime
    year: int
    source_exchange: str = "bitget"
    target_cex: str = "binance"
    network: str | None = None
    window_hours: int = 72
    rows_count: int = 0
    ready_count: int = 0
    missing_count: int = 0
    rows: list[WalletFifoCexExchangeOutflowEvidenceRow] = Field(default_factory=list)
    methodology: str


class WalletFifoCexExchangeOutflowAnchorFeasibilityItem(BaseModel):
    decision_id: str | None = None
    deposit_txid: str
    year: int
    source_exchange: str = "bitget"
    target_cex: str = "binance"
    network: str | None = None
    asset: str
    amount: Decimal
    decision_status: str | None = None
    evidence_status: str | None = None
    anchor_status: str
    anchor_ready: bool = False
    existing_fifo_trace_status: str | None = None
    existing_fifo_source_pool_id: str | None = None
    existing_fifo_target_pool_id: str | None = None
    exchange_outflow_raw_object_id: str | None = None
    exchange_outflow_tx_id: str | None = None
    exchange_outflow_fee: Decimal | None = None
    amount_delta: Decimal | None = None
    time_delta_seconds: int | None = None
    missing_requirements: list[str] = Field(default_factory=list)
    recommended_action: str


class WalletFifoCexExchangeOutflowAnchorFeasibilityReport(BaseModel):
    generated_at: datetime
    year: int
    source_exchange: str = "bitget"
    target_cex: str = "binance"
    network: str | None = None
    decisions_count: int = 0
    evidence_ready_count: int = 0
    anchor_ready_count: int = 0
    anchor_missing_count: int = 0
    items: list[WalletFifoCexExchangeOutflowAnchorFeasibilityItem] = Field(default_factory=list)
    methodology: str


class WalletFifoProvenancePrioritySample(BaseModel):
    event_id: str
    event_time: datetime
    tx_id: str | None = None
    quantity: Decimal
    raw_object_id: str | None = None
    has_raw_evidence: bool = False
    has_deposit_evidence: bool = False
    onchain_tx_id: str | None = None
    deposit_address: str | None = None
    network: str | None = None


class WalletFifoProvenanceOutflowSummary(BaseModel):
    event_id: str | None = None
    source: str
    account: str | None = None
    event_time: datetime
    asset: str
    quantity: Decimal
    tx_id: str | None = None
    seconds_delta: int
    amount_delta: Decimal
    evidence_category: str
    exchange_evidence_status: str | None = None
    withdrawal_evidence_status: str | None = None
    withdrawal_tx_id: str | None = None
    withdrawal_address: str | None = None
    withdrawal_network: str | None = None
    withdrawal_amount: Decimal | None = None
    withdrawal_fee: Decimal | None = None
    raw_object_id: str | None = None
    recommended_action: str


class WalletFifoProvenancePriorityGroup(BaseModel):
    year: int
    asset: str
    pool_id: str
    source: str
    account: str | None = None
    events_count: int = 0
    quantity_total: Decimal = Decimal("0")
    carried_cost_basis_eur_total: Decimal = Decimal("0")
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None
    raw_evidence_count: int = 0
    deposit_evidence_count: int = 0
    onchain_tx_id_count: int = 0
    missing_tx_id_count: int = 0
    local_outflow_candidate_count: int = 0
    exchange_outflow_candidate_count: int = 0
    exchange_internal_context_count: int = 0
    withdrawal_evidence_ready_count: int = 0
    evidence_status: str
    event_status_counts: dict[str, int] = Field(default_factory=dict)
    priority_score: Decimal = Decimal("0")
    origin_trace_endpoint: str
    recommended_action: str
    best_outflow_candidate: WalletFifoProvenanceOutflowSummary | None = None
    samples: list[WalletFifoProvenancePrioritySample] = Field(default_factory=list)


class WalletFifoProvenanceStatusBreakdown(BaseModel):
    evidence_status: str
    events_count: int = 0
    quantity_total: Decimal = Decimal("0")
    carried_cost_basis_eur_total: Decimal = Decimal("0")
    local_outflow_candidate_count: int = 0
    exchange_outflow_candidate_count: int = 0
    exchange_internal_context_count: int = 0
    withdrawal_evidence_ready_count: int = 0
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None
    recommended_action: str
    best_outflow_candidate: WalletFifoProvenanceOutflowSummary | None = None


class WalletFifoProvenancePriorityReport(BaseModel):
    generated_at: datetime
    year: int
    unresolved_inbound_provenance_count: int = 0
    groups_count: int = 0
    groups: list[WalletFifoProvenancePriorityGroup] = Field(default_factory=list)
    status_breakdown: list[WalletFifoProvenanceStatusBreakdown] = Field(default_factory=list)
    methodology: str


class WalletFifoYearProvenanceClosureItem(BaseModel):
    category: str
    closure_status: str
    asset: str
    pool_id: str
    source: str
    account: str | None = None
    events_count: int = 0
    quantity_total: Decimal = Decimal("0")
    carried_cost_basis_eur_total: Decimal = Decimal("0")
    evidence_status: str
    requires_review: bool = True
    tax_treatment_hint: str
    evidence_refs: list[str] = Field(default_factory=list)
    recommended_action: str


class WalletFifoYearProvenanceClosureReport(BaseModel):
    generated_at: datetime
    year: int
    unresolved_inbound_provenance_count: int = 0
    groups_count: int = 0
    documented_non_live_count: int = 0
    documented_fiat_purchase_count: int = 0
    documented_legacy_cex_deposit_count: int = 0
    documented_legacy_cex_deposit_mirror_count: int = 0
    documented_fairspot_staking_return_count: int = 0
    documented_legacy_counterparty_mirror_count: int = 0
    documented_legacy_hnt_external_payment_count: int = 0
    documented_token_redenomination_count: int = 0
    documented_manual_cex_deposit_count: int = 0
    documented_exchange_deposit_history_count: int = 0
    external_or_unknown_count: int = 0
    unverified_cex_count: int = 0
    tax_neutral_candidate_count: int = 0
    review_required_count: int = 0
    items: list[WalletFifoYearProvenanceClosureItem] = Field(default_factory=list)
    methodology: str


class WalletFifoProvenanceEvent(BaseModel):
    event_id: str
    event_time: datetime
    source: str
    account: str | None = None
    asset: str
    pool_id: str
    quantity: Decimal
    carried_cost_basis_eur: Decimal = Decimal("0")
    tx_id: str | None = None
    raw_object_id: str | None = None
    has_raw_evidence: bool = False
    has_deposit_evidence: bool = False
    onchain_tx_id: str | None = None
    deposit_address: str | None = None
    network: str | None = None
    best_outflow_candidate: WalletFifoProvenanceOutflowSummary | None = None
    evidence_status: str
    recommended_action: str


class WalletFifoProvenanceEventReport(BaseModel):
    generated_at: datetime
    year: int
    asset: str | None = None
    pool_id: str | None = None
    offset: int = 0
    limit: int = 100
    events_count: int = 0
    events: list[WalletFifoProvenanceEvent] = Field(default_factory=list)
    methodology: str


class WalletFifoRawProvenanceBreakdownGroup(BaseModel):
    year: int
    evidence_status: str
    raw_pattern: str
    asset: str
    pool_id: str
    source: str
    account: str | None = None
    raw_source: str | None = None
    raw_filename: str | None = None
    events_count: int = 0
    quantity_total: Decimal = Decimal("0")
    carried_cost_basis_eur_total: Decimal = Decimal("0")
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None
    tx_id_count: int = 0
    tiny_quantity_count: int = 0
    sample_event_ids: list[str] = Field(default_factory=list)
    sample_tx_ids: list[str] = Field(default_factory=list)
    recommended_action: str


class WalletFifoRawProvenanceBreakdownReport(BaseModel):
    generated_at: datetime
    year: int
    groups_count: int = 0
    raw_transaction_evidence_only_count: int = 0
    solana_tiny_raw_credit_count: int = 0
    groups: list[WalletFifoRawProvenanceBreakdownGroup] = Field(default_factory=list)
    methodology: str


class WalletFifoOpeningBalanceEvidence(BaseModel):
    event_id: str
    event_time: datetime
    source: str
    account: str | None = None
    asset: str
    pool_id: str
    quantity: Decimal
    carried_cost_basis_eur: Decimal = Decimal("0")
    raw_object_id: str | None = None
    raw_source: str | None = None
    raw_filename: str | None = None
    raw_row_number: int | None = None
    raw_payload: dict[str, str | int | float | None] = Field(default_factory=dict)
    provenance_status: str
    tax_classification: str = "opening_balance_evidence"
    fifo_effect: str = "initial_lot_documented_pending_origin_evidence"
    live_balance_effect: str = "none"
    recommended_action: str


class WalletFifoOpeningBalanceEvidenceReport(BaseModel):
    generated_at: datetime
    year: int
    asset: str | None = None
    pool_id: str | None = None
    rows_count: int = 0
    total_quantity_by_asset: dict[str, Decimal] = Field(default_factory=dict)
    total_cost_basis_eur: Decimal = Decimal("0")
    rows: list[WalletFifoOpeningBalanceEvidence] = Field(default_factory=list)
    methodology: str


class WalletFifoExchangeEvidenceGap(BaseModel):
    gap_id: str
    year: int
    asset: str
    pool_id: str
    inbound_event_id: str
    inbound_event_time: datetime
    inbound_source: str
    inbound_account: str | None = None
    inbound_quantity: Decimal
    inbound_tx_id: str | None = None
    inbound_raw_evidence: WalletFifoOriginRawEvidence | None = None
    outflow_candidate: WalletFifoProvenanceOutflowSummary
    outflow_raw_evidence: WalletFifoOriginRawEvidence | None = None
    missing_fields: list[str] = Field(default_factory=list)
    evidence_status: str
    expected_evidence_source: str
    recommended_action: str


class WalletFifoExchangeEvidenceGapReport(BaseModel):
    generated_at: datetime
    year: int
    gaps_count: int = 0
    gaps: list[WalletFifoExchangeEvidenceGap] = Field(default_factory=list)
    methodology: str


class WalletFifoSolanaProvenanceClassification(BaseModel):
    event_id: str
    signature: str
    status: str
    evidence_source: str = "rpc"
    asset: str
    expected_amount: Decimal
    matched_amount: Decimal | None = None
    wallet_delta_quantity: Decimal | None = None
    sender_owner: str | None = None
    receiver_owner: str | None = None
    sender_is_known_own_wallet: bool = False
    receiver_is_known_own_wallet: bool = False
    block_time: str | None = None
    slot: int | None = None
    reason: str | None = None
    recommended_action: str


class WalletFifoSolanaProvenanceClassificationReport(BaseModel):
    generated_at: datetime
    year: int
    asset: str
    pool_id: str | None = None
    offset: int = 0
    limit: int = 5
    requested_events_count: int = 0
    classified_count: int = 0
    own_transfer_candidates_count: int = 0
    external_or_unknown_count: int = 0
    failed_count: int = 0
    classifications: list[WalletFifoSolanaProvenanceClassification] = Field(default_factory=list)
    methodology: str


class WalletFifoSolanaProvenanceBatchLatest(BaseModel):
    generated_at: datetime | None = None
    year: int
    asset: str
    pool_id: str | None = None
    provider: str | None = None
    run_id: str | None = None
    artifact_path: str
    exists: bool = False
    total_events: int = 0
    classified_count: int = 0
    remaining_count: int = 0
    progress_percent: Decimal = Decimal("0")
    own_transfer_candidates_count: int = 0
    external_or_unknown_count: int = 0
    failed_count: int = 0
    batches_count: int = 0
    last_batch_offset: int | None = None
    last_batch_failed_count: int | None = None
    last_batch_status: str | None = None
    methodology: str


class WalletFifoSolanaRawProvenancePriority(BaseModel):
    event_id: str
    event_time: datetime
    evidence_status: str
    asset: str
    pool_id: str
    quantity: Decimal
    carried_cost_basis_eur: Decimal = Decimal("0")
    signature: str | None = None
    classification_status: str | None = None
    evidence_source: str | None = None
    sender_owner: str | None = None
    receiver_owner: str | None = None
    matched_amount: Decimal | None = None
    wallet_delta_quantity: Decimal | None = None
    origin_hint: str | None = None
    evidence_needed: str | None = None
    wallet_is_signer: bool = False
    signers: list[str] = Field(default_factory=list)
    program_ids: list[str] = Field(default_factory=list)
    primary_program: str | None = None
    route_classification: str | None = None
    bmf_evidence_priority: str = "medium"
    evidence_checklist: list[str] = Field(default_factory=list)
    sender_is_known_own_wallet: bool = False
    receiver_is_known_own_wallet: bool = False
    block_time: str | None = None
    classification_reason: str | None = None
    recommended_action: str


class WalletFifoSolanaRawProvenancePriorityReport(BaseModel):
    generated_at: datetime
    year: int
    asset: str = "SOL"
    pool_id: str | None = None
    artifact_path: str
    artifact_exists: bool = False
    events_count: int = 0
    priorities_count: int = 0
    raw_transaction_evidence_only_count: int = 0
    solana_tiny_raw_credit_count: int = 0
    total_quantity: Decimal = Decimal("0")
    total_cost_basis_eur: Decimal = Decimal("0")
    priorities: list[WalletFifoSolanaRawProvenancePriority] = Field(default_factory=list)
    methodology: str


class WalletFifoSolanaRawProvenanceSenderSummary(BaseModel):
    sender_owner: str
    receiver_owner: str | None = None
    classification_status: str | None = None
    events_count: int = 0
    raw_transaction_evidence_only_count: int = 0
    solana_tiny_raw_credit_count: int = 0
    quantity_total: Decimal = Decimal("0")
    carried_cost_basis_eur_total: Decimal = Decimal("0")
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None
    top_signature: str | None = None
    top_quantity: Decimal | None = None
    top_cost_basis_eur: Decimal | None = None
    origin_hint: str | None = None
    evidence_needed: str | None = None
    sample_signatures: list[str] = Field(default_factory=list)
    wallet_signed_events_count: int = 0
    sample_signers: list[str] = Field(default_factory=list)
    sample_program_ids: list[str] = Field(default_factory=list)
    primary_program: str | None = None
    route_classification: str | None = None
    bmf_evidence_priority: str = "medium"
    evidence_checklist: list[str] = Field(default_factory=list)
    recommended_action: str


class WalletFifoSolanaRawProvenanceSenderSummaryReport(BaseModel):
    generated_at: datetime
    year: int
    asset: str = "SOL"
    pool_id: str | None = None
    senders_count: int = 0
    events_count: int = 0
    raw_transaction_evidence_only_count: int = 0
    solana_tiny_raw_credit_count: int = 0
    total_quantity: Decimal = Decimal("0")
    total_cost_basis_eur: Decimal = Decimal("0")
    senders: list[WalletFifoSolanaRawProvenanceSenderSummary] = Field(default_factory=list)
    methodology: str


class WalletFifoSolanaRawBmfEvidenceGroup(BaseModel):
    route_classification: str
    bmf_evidence_priority: str
    events_count: int = 0
    senders_count: int = 0
    raw_transaction_evidence_only_count: int = 0
    solana_tiny_raw_credit_count: int = 0
    quantity_total: Decimal = Decimal("0")
    carried_cost_basis_eur_total: Decimal = Decimal("0")
    wallet_signed_events_count: int = 0
    primary_programs: list[str] = Field(default_factory=list)
    sample_senders: list[str] = Field(default_factory=list)
    sample_signatures: list[str] = Field(default_factory=list)
    evidence_checklist: list[str] = Field(default_factory=list)
    recommended_action: str


class WalletFifoSolanaRawBmfEvidenceSummaryReport(BaseModel):
    generated_at: datetime
    year: int
    asset: str = "SOL"
    pool_id: str | None = None
    groups_count: int = 0
    high_priority_events_count: int = 0
    high_priority_cost_basis_eur: Decimal = Decimal("0")
    total_quantity: Decimal = Decimal("0")
    total_cost_basis_eur: Decimal = Decimal("0")
    groups: list[WalletFifoSolanaRawBmfEvidenceGroup] = Field(default_factory=list)
    methodology: str


class WalletFifoSolanaRawBmfEvidenceDrilldownEvent(BaseModel):
    event_id: str
    event_time: datetime
    asset: str
    pool_id: str
    quantity: Decimal
    carried_cost_basis_eur: Decimal = Decimal("0")
    signature: str | None = None
    sender_owner: str | None = None
    receiver_owner: str | None = None
    wallet_is_signer: bool = False
    signers: list[str] = Field(default_factory=list)
    primary_signer: str | None = None
    primary_program: str | None = None
    program_ids: list[str] = Field(default_factory=list)
    route_classification: str
    bmf_evidence_priority: str
    evidence_needed: str | None = None
    evidence_checklist: list[str] = Field(default_factory=list)
    decision_suggestion: str
    decision_reason: str


class WalletFifoSolanaRawBmfEvidenceSignerGroup(BaseModel):
    primary_signer: str
    primary_program: str | None = None
    route_classification: str
    bmf_evidence_priority: str
    events_count: int = 0
    quantity_total: Decimal = Decimal("0")
    carried_cost_basis_eur_total: Decimal = Decimal("0")
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None
    sample_senders: list[str] = Field(default_factory=list)
    sample_signatures: list[str] = Field(default_factory=list)
    decision_suggestion: str
    evidence_checklist: list[str] = Field(default_factory=list)


class WalletFifoSolanaRawBmfEvidenceDrilldownReport(BaseModel):
    generated_at: datetime
    year: int
    asset: str = "SOL"
    pool_id: str | None = None
    route_filter: str | None = None
    priority_filter: str | None = None
    events_count: int = 0
    groups_count: int = 0
    total_quantity: Decimal = Decimal("0")
    total_cost_basis_eur: Decimal = Decimal("0")
    signer_groups: list[WalletFifoSolanaRawBmfEvidenceSignerGroup] = Field(default_factory=list)
    events: list[WalletFifoSolanaRawBmfEvidenceDrilldownEvent] = Field(default_factory=list)
    methodology: str


class WalletFifoSolanaSenderClusterSample(BaseModel):
    event_id: str
    signature: str
    block_time: str | None = None
    expected_amount: Decimal
    matched_amount: Decimal | None = None
    reason: str | None = None


class WalletFifoSolanaSenderCluster(BaseModel):
    sender_owner: str
    receiver_owner: str | None = None
    status: str
    events_count: int = 0
    expected_amount_total: Decimal = Decimal("0")
    matched_amount_total: Decimal = Decimal("0")
    first_block_time: str | None = None
    last_block_time: str | None = None
    own_wallet_sender: bool = False
    own_wallet_receiver: bool = False
    local_raw_sender_hits: int = 0
    local_signature_evidence_count: int = 0
    local_canonical_signature_count: int = 0
    recommended_action: str
    samples: list[WalletFifoSolanaSenderClusterSample] = Field(default_factory=list)


class WalletFifoSolanaSenderClusterReport(BaseModel):
    generated_at: datetime
    year: int
    asset: str
    artifact_path: str
    artifact_exists: bool = False
    run_id: str | None = None
    total_events: int = 0
    clusters_count: int = 0
    own_transfer_candidate_events: int = 0
    external_or_unknown_events: int = 0
    failed_events: int = 0
    clusters: list[WalletFifoSolanaSenderCluster] = Field(default_factory=list)
    methodology: str


class WalletFifoSolanaNearbyOutflowCandidate(BaseModel):
    event_id: str | None = None
    source: str
    account: str | None = None
    event_time: datetime
    event_type: str
    asset: str
    quantity: Decimal
    tx_id: str | None = None
    source_ref: str | None = None
    seconds_delta: int
    amount_delta: Decimal
    evidence_category: str
    exchange_evidence_status: str | None = None
    raw_object_id: str | None = None
    raw_source: str | None = None
    raw_filename: str | None = None
    raw_row_number: int | None = None
    withdrawal_evidence_status: str | None = None
    withdrawal_raw_object_id: str | None = None
    withdrawal_tx_id: str | None = None
    withdrawal_address: str | None = None
    withdrawal_network: str | None = None
    withdrawal_amount: Decimal | None = None
    withdrawal_fee: Decimal | None = None
    recommended_action: str


class WalletFifoSolanaSenderClusterOutflowSample(BaseModel):
    inbound_event_id: str
    inbound_signature: str
    inbound_block_time: str | None = None
    inbound_sender_owner: str
    inbound_receiver_owner: str | None = None
    inbound_amount: Decimal
    candidates: list[WalletFifoSolanaNearbyOutflowCandidate] = Field(default_factory=list)


class WalletFifoSolanaSenderClusterOutflowReport(BaseModel):
    generated_at: datetime
    year: int
    asset: str
    artifact_path: str
    artifact_exists: bool = False
    sender_owner: str | None = None
    checked_events_count: int = 0
    events_with_candidates_count: int = 0
    candidates_count: int = 0
    window_hours: int = 48
    amount_tolerance_percent: Decimal = Decimal("1")
    samples: list[WalletFifoSolanaSenderClusterOutflowSample] = Field(default_factory=list)
    methodology: str


class WalletFifoSolanaTokenDelta(BaseModel):
    owner: str | None = None
    mint: str
    asset: str
    pre_quantity: Decimal = Decimal("0")
    post_quantity: Decimal = Decimal("0")
    delta_quantity: Decimal = Decimal("0")


class WalletFifoSolanaOriginTrace(BaseModel):
    signature: str
    status: str
    block_time: str | None = None
    slot: int | None = None
    asset: str
    expected_amount: Decimal | None = None
    deposit_address: str | None = None
    sender_owner: str | None = None
    receiver_owner: str | None = None
    sender_is_known_own_wallet: bool = False
    receiver_is_deposit_address: bool = False
    matched_amount: Decimal | None = None
    token_deltas: list[WalletFifoSolanaTokenDelta] = Field(default_factory=list)
    known_wallets: list[str] = Field(default_factory=list)
    recommended_action: str
    reason: str | None = None


class WalletFifoSolanaOriginTraceReport(BaseModel):
    generated_at: datetime
    year: int
    traces_count: int = 0
    traces: list[WalletFifoSolanaOriginTrace] = Field(default_factory=list)
    methodology: str


class WalletFifoWithdrawalCandidate(BaseModel):
    event_id: str
    event_time: datetime
    source: str
    account: str | None = None
    pool_id: str
    asset: str
    quantity: Decimal
    raw_object_id: str | None = None
    transaction_history_evidence: WalletFifoOriginRawEvidence | None = None
    withdrawal_history_evidence: WalletFifoOriginRawEvidence | None = None
    onchain_tx_id: str | None = None
    to_address: str | None = None
    network: str | None = None
    evidence_status: str
    recommended_action: str


class WalletFifoWithdrawalGapTrace(BaseModel):
    gap_id: str
    year: int
    asset: str
    pool_id: str
    missing_quantity: Decimal
    gap_event_time: datetime
    candidates: list[WalletFifoWithdrawalCandidate] = Field(default_factory=list)
    recommended_action: str


class WalletFifoWithdrawalGapReport(BaseModel):
    generated_at: datetime
    year: int
    traces_count: int = 0
    traces: list[WalletFifoWithdrawalGapTrace] = Field(default_factory=list)
    methodology: str
