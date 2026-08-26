from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from steuerreport_v2.contracts.sources import SourceConnectorAttempt


SourceRegistrySourceType = Literal[
    "wallet",
    "exchange",
    "legacy_wallet",
    "service",
    "onramp",
    "infrastructure",
]
SourceRegistryOwnership = Literal["owned", "owned_historical_route", "third_party", "infrastructure"]
SourceRegistryPortfolioPolicy = Literal["include", "exclude", "expected_zero"]
SourceRegistryFifoPolicy = Literal["owned_pool", "transfer_bridge", "evidence_only", "counterparty"]
SourceRegistryCoverageStatus = Literal["complete", "partial", "evidence_only"]
SourceRegistryCoverageLimitation = Literal[
    "none",
    "provider_api_history_boundary",
    "provider_export_field_gap",
    "missing_original_account_history",
    "documented_transfer_route_only",
]
SourceRegistryCoverageGateStatus = Literal[
    "satisfied",
    "documented_route",
    "provider_gap",
    "missing_evidence",
]
SourceRegistryLiveSnapshotStatus = Literal[
    "current",
    "stale",
    "missing",
    "not_applicable",
]
SourceRegistryLiveBalanceBasis = Literal[
    "current_live_snapshot",
    "ledger_fallback",
    "not_applicable",
]


class SourceRegistryIdentifier(BaseModel):
    kind: Literal["account", "wallet", "address", "canonical_source", "canonical_source_prefix"]
    value: str


class SourceRegistryEntry(BaseModel):
    source_id: str
    label: str
    source_type: SourceRegistrySourceType
    ownership: SourceRegistryOwnership
    role: str
    portfolio_policy: SourceRegistryPortfolioPolicy
    fifo_policy: SourceRegistryFifoPolicy
    valid_from: datetime
    valid_to: datetime | None = None
    coverage_status: SourceRegistryCoverageStatus
    coverage_limitation: SourceRegistryCoverageLimitation = "none"
    coverage_limitation_note: str | None = None
    additional_user_evidence_required: bool = False
    coverage_from: datetime | None = None
    coverage_to: datetime | None = None
    identifiers: list[SourceRegistryIdentifier] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    note: str | None = None


class SourceRegistryLedgerAdjustment(BaseModel):
    adjustment_id: str
    source_id: str
    target_source_id: str | None = None
    event_time: datetime
    asset: str
    quantity_delta: Decimal
    tx_id: str
    reason: Literal["missing_transfer_counterpart"]
    review_status: Literal["approved_evidence_overlay"]
    evidence_refs: list[str] = Field(default_factory=list)
    note: str | None = None


class SourceRegistryTransferEvidence(BaseModel):
    evidence_id: str
    tx_id: str
    source_id: str
    target_source_id: str
    event_time: datetime
    asset: str
    quantity: Decimal
    fee_quantity: Decimal = Decimal("0")
    evidence_status: Literal["approved_complete"]
    evidence_refs: list[str] = Field(default_factory=list)
    note: str | None = None


class SourceRegistryConfig(BaseModel):
    registry_version: str
    entries: list[SourceRegistryEntry] = Field(default_factory=list)
    ledger_adjustments: list[SourceRegistryLedgerAdjustment] = Field(default_factory=list)
    transfer_evidence: list[SourceRegistryTransferEvidence] = Field(default_factory=list)


class SourceRegistryObservation(BaseModel):
    canonical_source: str
    account: str | None = None
    events_count: int = 0
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None
    matched_source_id: str | None = None
    match_kind: str | None = None


class SourceRegistryQuantityDelta(BaseModel):
    asset: str
    raw_ledger_quantity: Decimal = Decimal("0")
    ledger_adjustment_quantity: Decimal = Decimal("0")
    ledger_quantity: Decimal = Decimal("0")
    raw_live_anchored_quantity: Decimal = Decimal("0")
    live_nonledger_accrual_quantity: Decimal = Decimal("0")
    live_anchored_quantity: Decimal = Decimal("0")
    quantity_delta: Decimal = Decimal("0")
    value_delta_eur: Decimal = Decimal("0")


class SourceRegistryEntryStatus(BaseModel):
    source_id: str
    label: str
    source_type: SourceRegistrySourceType
    ownership: SourceRegistryOwnership
    role: str
    portfolio_policy: SourceRegistryPortfolioPolicy
    fifo_policy: SourceRegistryFifoPolicy
    valid_from: datetime
    valid_to: datetime | None = None
    coverage_status: SourceRegistryCoverageStatus
    coverage_limitation: SourceRegistryCoverageLimitation = "none"
    coverage_limitation_note: str | None = None
    additional_user_evidence_required: bool = False
    coverage_gate_status: SourceRegistryCoverageGateStatus = "satisfied"
    coverage_from: datetime | None = None
    coverage_to: datetime | None = None
    observed_events_count: int = 0
    observed_first_event_at: datetime | None = None
    observed_last_event_at: datetime | None = None
    observed_accounts: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    current_ledger_value_eur: Decimal = Decimal("0")
    current_ledger_adjustment_value_eur: Decimal = Decimal("0")
    current_reconciled_ledger_value_eur: Decimal = Decimal("0")
    current_live_anchored_value_eur: Decimal = Decimal("0")
    current_live_nonledger_accrual_value_eur: Decimal = Decimal("0")
    current_reconciliation_live_value_eur: Decimal = Decimal("0")
    current_value_delta_eur: Decimal = Decimal("0")
    live_snapshot_status: SourceRegistryLiveSnapshotStatus = "not_applicable"
    latest_live_snapshot_at: datetime | None = None
    live_balance_basis: SourceRegistryLiveBalanceBasis = "not_applicable"
    last_connector_attempt: SourceConnectorAttempt | None = None
    ledger_adjustments: list[SourceRegistryLedgerAdjustment] = Field(default_factory=list)
    quantity_gate_status: Literal["not_applicable", "matched", "review", "blocked"] = "not_applicable"
    quantity_deltas: list[SourceRegistryQuantityDelta] = Field(default_factory=list)
    strict_ready: bool = False
    findings: list[str] = Field(default_factory=list)


class SourceRegistryRunReport(BaseModel):
    generated_at: datetime
    registry_version: str
    status: Literal["blocked", "review", "strict_ready"]
    strict_ready: bool = False
    config_sha256: str
    semantic_sha256: str
    entries_count: int = 0
    owned_entries_count: int = 0
    complete_entries_count: int = 0
    partial_entries_count: int = 0
    provider_coverage_gap_entries_count: int = 0
    user_evidence_gap_entries_count: int = 0
    documented_route_entries_count: int = 0
    observed_groups_count: int = 0
    unregistered_observations_count: int = 0
    portfolio_policy_violations_count: int = 0
    quantity_blocker_entries_count: int = 0
    ledger_adjustments_count: int = 0
    applied_ledger_adjustments_count: int = 0
    transfer_evidence_count: int = 0
    approved_transfer_evidence_count: int = 0
    invalid_entries: list[str] = Field(default_factory=list)
    unregistered_observations: list[SourceRegistryObservation] = Field(default_factory=list)
    portfolio_policy_violations: list[str] = Field(default_factory=list)
    entries: list[SourceRegistryEntryStatus] = Field(default_factory=list)
    observations: list[SourceRegistryObservation] = Field(default_factory=list)
    artifact_path: str
    config_path: str
    findings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    methodology: str
