from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

ParityStatus = Literal["match", "diff", "missing_v2"]
ParityDecisionStatus = Literal[
    "unreviewed",
    "v1_known_wrong",
    "v2_missing_data",
    "v2_corrected",
    "needs_manual_evidence",
    "accepted_difference",
]


class V1ReferenceMetricCreate(BaseModel):
    scope: str = Field(min_length=1)
    metric: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    value: Decimal
    year: int | None = None
    asset: str | None = None
    source: str | None = None
    note: str | None = None


class V1ReferenceMetric(V1ReferenceMetricCreate):
    reference_id: str
    created_at: datetime


class V1ReferenceDeleteResult(BaseModel):
    reference_id: str
    deleted: bool


class V1WisoReferenceImportRequest(BaseModel):
    file_path: str | None = None
    content: str | None = None
    label: str = "wiso"


class V1WisoReferenceImportResult(BaseModel):
    label: str
    tax_year: int
    rows_read: int
    references_created: int
    assets: list[str]


class V1ParityRow(BaseModel):
    reference: V1ReferenceMetric
    v2_value: Decimal | None
    difference: Decimal | None
    absolute_difference: Decimal | None
    status: ParityStatus


class V1ParitySummary(BaseModel):
    rows: list[V1ParityRow]
    compared: int
    matches: int
    differences: int
    missing_v2: int
    max_absolute_difference: Decimal


class V1ParityIssueGroup(BaseModel):
    scope: str
    year: int | None
    asset: str | None
    status: ParityStatus
    decision_status: ParityDecisionStatus = "unreviewed"
    decision_id: str | None = None
    decision_title: str | None = None
    issue_count: int
    metrics: list[str]
    v1_total_eur: Decimal
    v2_total_eur: Decimal
    absolute_difference_eur: Decimal
    max_absolute_difference: Decimal


class V1ParityDiagnostics(BaseModel):
    compared: int
    matches: int
    differences: int
    missing_v2: int
    groups: list[V1ParityIssueGroup]


class V1ParityReleaseReadiness(BaseModel):
    release_ready: bool
    compared: int
    matches: int
    differences: int
    missing_v2: int
    groups_total: int
    unresolved_groups: int
    blocking_groups: int
    accepted_groups: int
    max_absolute_difference: Decimal
    blocking_difference_eur: Decimal
    blocking_groups_top: list[V1ParityIssueGroup]


class V1ParityGroupMetricDetail(BaseModel):
    metric: str
    unit: str
    v1_value: Decimal
    v2_value: Decimal | None = None
    difference: Decimal | None = None
    absolute_difference: Decimal | None = None


class V1ParityTaxSourceSummary(BaseModel):
    source: str
    account: str | None = None
    filename: str | None = None
    tax_lines: int
    event_count: int
    quantity: Decimal
    disposal_proceeds_eur: Decimal
    acquisition_cost_eur: Decimal
    gain_loss_eur: Decimal
    first_disposed_at: datetime | None = None
    last_disposed_at: datetime | None = None


class V1ParityTaxEventSample(BaseModel):
    event_time: datetime
    source: str
    account: str | None = None
    source_ref: str | None = None
    filename: str | None = None
    raw_object_id: str | None = None
    quantity: Decimal
    quote_asset: str | None = None
    quote_quantity: Decimal | None = None
    disposal_proceeds_eur: Decimal
    acquisition_cost_eur: Decimal
    gain_loss_eur: Decimal
    payload: dict[str, object] = Field(default_factory=dict)


class V1ParityGroupDetail(BaseModel):
    scope: str
    year: int | None = None
    asset: str | None = None
    status: ParityStatus | None = None
    decision_status: ParityDecisionStatus = "unreviewed"
    metrics: list[V1ParityGroupMetricDetail]
    tax_source_summaries: list[V1ParityTaxSourceSummary] = Field(default_factory=list)
    tax_event_samples: list[V1ParityTaxEventSample] = Field(default_factory=list)


class HntWalletBridgeRow(BaseModel):
    source: str
    account: str | None = None
    event_type: str
    direction: str
    event_count: int
    quantity: Decimal
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None


class HntWalletBridgeReport(BaseModel):
    year: int
    v1_quantity_disposed: Decimal | None = None
    v2_quantity_disposed: Decimal
    quantity_difference: Decimal | None = None
    pionex_buys: Decimal
    pionex_sells: Decimal
    pionex_net: Decimal
    wallet_mining_in: Decimal
    wallet_transfer_in: Decimal
    wallet_fees_out: Decimal
    binance_in: Decimal
    binance_out: Decimal
    rows: list[HntWalletBridgeRow]
    interpretation: str


class HntFifoProvenanceEvent(BaseModel):
    event_id: str
    event_time: datetime
    source: str
    event_type: str
    direction: str
    quantity: Decimal
    account: str | None = None
    counterparty_account: str | None = None
    tx_id: str | None = None
    source_ref: str | None = None
    filename: str | None = None
    current_portfolio_account: bool = False
    fifo_relevant: bool = False
    note: str


class HntFifoProvenanceLot(BaseModel):
    lot_id: str
    acquired_at: datetime
    quantity_total: Decimal
    quantity_remaining: Decimal
    cost_basis_eur_total: Decimal
    source_event_id: str
    source: str | None = None
    source_ref: str | None = None
    account: str | None = None
    tx_id: str | None = None


class HntFifoProvenanceTaxLine(BaseModel):
    tax_line_id: str
    lot_id: str
    acquired_at: datetime
    disposed_at: datetime
    quantity: Decimal
    acquisition_cost_eur: Decimal
    disposal_proceeds_eur: Decimal
    gain_loss_eur: Decimal
    holding_days: int
    source_event_id: str
    disposal_source: str | None = None
    disposal_account: str | None = None
    source_ref: str | None = None
    tx_id: str | None = None


class HntFifoProvenanceTimelineStep(BaseModel):
    label: str
    role: str
    account: str | None = None
    event_count: int
    quantity_in: Decimal
    quantity_out: Decimal
    net_quantity: Decimal
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None
    note: str


class HntFifoProvenanceReport(BaseModel):
    generated_at: datetime
    asset: str = "HNT"
    event_limit: int
    filter_source: str | None = None
    filter_account: str | None = None
    filter_from: datetime | None = None
    filter_to: datetime | None = None
    current_portfolio_accounts: list[str]
    transfer_counterparty_accounts: list[str]
    current_portfolio_events: int
    transfer_counterparty_events: int
    fifo_relevant_events: int
    open_lots: int
    disposals: int
    timeline: list[HntFifoProvenanceTimelineStep]
    events: list[HntFifoProvenanceEvent]
    open_fifo_lots: list[HntFifoProvenanceLot]
    disposal_tax_lines: list[HntFifoProvenanceTaxLine]
    methodology: str


class V1ParityDecisionCreate(BaseModel):
    scope: str = Field(min_length=1)
    decision_status: ParityDecisionStatus
    title: str
    rationale: str
    evidence_ref: str | None = None


class V1ParityDecisionResult(BaseModel):
    decision_id: str
    scope: str
    decision_status: ParityDecisionStatus
