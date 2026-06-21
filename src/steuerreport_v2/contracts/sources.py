from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class SourceAssetStatus(BaseModel):
    asset: str
    quantity: Decimal
    value_eur: Decimal
    share_pct: Decimal
    position_count: int
    price_status: str | None = None
    value_basis: str = "ledger"
    price_source: str | None = None
    priced_at_latest: datetime | None = None
    token_name: str | None = None
    token_symbol: str | None = None
    token_mint: str | None = None
    token_verified: bool | None = None
    token_risk_status: str | None = None


class SourceAccountStatus(BaseModel):
    account: str
    display_account: str
    full_account: str
    value_eur: Decimal
    assets: int
    position_count: int


class SourceReconciliationStatus(BaseModel):
    status: str
    severity: str
    ledger_value_eur: Decimal
    live_value_eur: Decimal | None = None
    delta_value_eur: Decimal | None = None
    last_live_at: datetime | None = None
    live_anchor_source: str | None = None
    evidence: str | None = None
    next_action: str | None = None


class SourceStatus(BaseModel):
    source_id: str
    label: str
    source_type: str
    value_eur: Decimal
    share_pct: Decimal
    account_count: int
    asset_count: int
    position_count: int
    current_status: str
    value_basis: str = "ledger"
    last_imported_at: datetime | None = None
    last_live_at: datetime | None = None
    live_age_days: int | None = None
    live_freshness: str = "missing"
    ledger_value_eur: Decimal
    live_value_eur: Decimal | None = None
    delta_value_eur: Decimal | None = None
    live_anchor_source: str | None = None
    display_warning: str | None = None
    open_price_issues: int = 0
    open_reconciliation_issues: int = 0
    import_batches: int = 0
    last_evidence_files: list[str] = Field(default_factory=list)
    top_assets: list[SourceAssetStatus] = Field(default_factory=list)
    accounts: list[SourceAccountStatus] = Field(default_factory=list)
    note: str | None = None


class SourceOverviewHealthIssue(BaseModel):
    source_id: str
    label: str
    severity: str
    issue: str
    detail: str
    next_action: str
    live_age_days: int | None = None
    last_live_at: datetime | None = None


class SourceOverviewHealth(BaseModel):
    status: str
    sources_count: int = 0
    live_connected_sources: int = 0
    ledger_only_sources: int = 0
    stale_live_sources: int = 0
    warning_sources: int = 0
    blocker_sources: int = 0
    missing_live_sources: int = 0
    total_open_reconciliation_issues: int = 0
    total_open_price_issues: int = 0
    issues: list[SourceOverviewHealthIssue] = Field(default_factory=list)
    detail: str


class SourceOverview(BaseModel):
    generated_at: datetime
    total_value_eur: Decimal
    sources: list[SourceStatus] = Field(default_factory=list)
    health: SourceOverviewHealth | None = None
    methodology: str


class SourceConnectorDiagnostic(BaseModel):
    source_id: str
    label: str
    connector_id: str
    connector_type: str
    status: str
    credential_status: str
    credential_issue: str | None = None
    credential_keys_present: int = 0
    credential_keys_required: int = 0
    credential_updated_at_latest: datetime | None = None
    last_snapshot_at: datetime | None = None
    last_snapshot_age_days: int | None = None
    last_snapshot_assets: int = 0
    last_snapshot_value_eur: Decimal | None = None
    message: str
    next_action: str


class SourceConnectorDiagnosticsReport(BaseModel):
    generated_at: datetime
    diagnostics: list[SourceConnectorDiagnostic] = Field(default_factory=list)
    missing_credentials: int = 0
    stale_snapshots: int = 0
    missing_snapshots: int = 0
    methodology: str


class SourceEventPreview(BaseModel):
    event_id: str
    event_time: datetime
    source: str
    event_type: str
    asset: str
    quantity: Decimal
    account: str | None = None
    counterparty_account: str | None = None
    raw_type: str | None = None
    match_basis: str = "canonical_account"
    tx_id: str | None = None


class SourceDetail(SourceStatus):
    assets: list[SourceAssetStatus] = Field(default_factory=list)
    reconciliation: SourceReconciliationStatus
    recent_events: list[SourceEventPreview] = Field(default_factory=list)
    open_issues: list[dict[str, object]] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    full_accounts: list[str] = Field(default_factory=list)
    methodology: str


class SourceReconciliationAssetRow(BaseModel):
    asset: str
    ledger_quantity: Decimal
    ledger_value_eur: Decimal
    live_quantity: Decimal | None = None
    live_value_eur: Decimal | None = None
    delta_quantity: Decimal | None = None
    delta_value_eur: Decimal | None = None
    price_eur: Decimal | None = None
    price_source: str | None = None
    price_status: str = "missing"
    live_components: int = 0
    live_account_types: list[str] = Field(default_factory=list)
    live_products: list[str] = Field(default_factory=list)
    status: str
    severity: str
    next_action: str


class SourceLiveComponent(BaseModel):
    asset: str
    quantity: Decimal
    value_eur: Decimal | None = None
    account_type: str | None = None
    product_id: str | None = None
    position_id: str | None = None
    event_type: str | None = None
    price_eur: Decimal | None = None
    price_source: str | None = None


class BinanceEvidenceEventSummary(BaseModel):
    year: int
    asset: str
    event_type: str
    account: str | None = None
    event_count: int
    quantity_sum: Decimal


class BinanceEvidenceImportBatch(BaseModel):
    filename: str
    status: str
    created_at: datetime


class BinanceEvidenceAssetReport(BaseModel):
    asset: str
    ledger_quantity: Decimal
    ledger_value_eur: Decimal
    live_quantity: Decimal | None = None
    live_value_eur: Decimal | None = None
    delta_quantity: Decimal | None = None
    delta_value_eur: Decimal | None = None
    live_components: list[SourceLiveComponent] = Field(default_factory=list)
    event_summaries: list[BinanceEvidenceEventSummary] = Field(default_factory=list)
    unknown_event_count: int = 0
    suspected_gap: str
    next_action: str


class BinanceEvidenceHistoryRequirement(BaseModel):
    asset: str
    account_type: str | None = None
    product_id: str | None = None
    requirement: str
    current_status: str
    evidence_refs: list[str] = Field(default_factory=list)
    gap_reason: str
    recommended_source: str


class BinanceReconciliationEvidenceReport(BaseModel):
    generated_at: datetime
    source_id: str = "binance"
    since: datetime
    assets: list[str]
    ledger_value_eur: Decimal
    live_value_eur: Decimal | None = None
    delta_value_eur: Decimal | None = None
    last_live_at: datetime | None = None
    import_batches: list[BinanceEvidenceImportBatch] = Field(default_factory=list)
    history_requirements: list[BinanceEvidenceHistoryRequirement] = Field(default_factory=list)
    asset_reports: list[BinanceEvidenceAssetReport] = Field(default_factory=list)
    methodology: str


class BinanceEarnHistoryProduct(BaseModel):
    asset: str
    account_type: str
    product_id: str | None = None
    position_id: str | None = None
    live_quantity: Decimal
    live_value_eur: Decimal | None = None
    live_event_types: list[str] = Field(default_factory=list)
    required_movements: list[str] = Field(default_factory=list)
    import_status: str
    evidence_refs: list[str] = Field(default_factory=list)
    api_probe_payload: dict[str, str | None] = Field(default_factory=dict)
    next_action: str


class BinanceEarnHistoryPreflightReport(BaseModel):
    generated_at: datetime
    source_id: str = "binance"
    status: str
    products: list[BinanceEarnHistoryProduct] = Field(default_factory=list)
    missing_products: int = 0
    partial_products: int = 0
    covered_products: int = 0
    connector_endpoint: str
    methodology: str


class SourceReconciliationBreakdown(BaseModel):
    generated_at: datetime
    source_id: str
    label: str
    source_type: str
    ledger_value_eur: Decimal
    live_value_eur: Decimal | None = None
    delta_value_eur: Decimal | None = None
    last_live_at: datetime | None = None
    live_anchor_source: str | None = None
    display_warning: str | None = None
    status: str
    severity: str
    rows: list[SourceReconciliationAssetRow] = Field(default_factory=list)
    live_components: list[SourceLiveComponent] = Field(default_factory=list)
    methodology: str
