from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


CockpitTaskPriority = Literal["high", "medium", "low"]


class CockpitMetric(BaseModel):
    label: str
    value: Decimal | int | str | bool | None = None
    status: str | None = None
    detail: str | None = None


class CockpitTopAsset(BaseModel):
    asset: str
    quantity: Decimal
    value_eur: Decimal
    share_pct: Decimal
    price_status: str
    accounts: int
    value_basis: str = "ledger"
    open_cost_basis_eur: Decimal = Decimal("0")
    unrealized_return_eur: Decimal = Decimal("0")
    unrealized_return_pct: Decimal | None = None
    performance_status: str = "unknown"
    price_sources: list[str] = Field(default_factory=list)
    priced_at_latest: datetime | None = None


class CockpitTopSource(BaseModel):
    source_group: str
    source_type: str
    value_eur: Decimal
    share_pct: Decimal
    account_count: int
    assets: int
    current_status: str
    value_basis: str = "ledger"
    ledger_value_eur: Decimal | None = None
    live_value_eur: Decimal | None = None
    delta_value_eur: Decimal | None = None
    last_live_at: datetime | None = None
    live_anchor_source: str | None = None
    display_warning: str | None = None
    note: str | None = None
    accounts: list[str] = Field(default_factory=list)


class CockpitPriceCoverage(BaseModel):
    priced_assets: int
    total_assets: int
    missing_assets: list[str] = Field(default_factory=list)
    missing_event_price_groups: int = 0
    status_counts: dict[str, int] = Field(default_factory=dict)
    coverage_pct: Decimal


class CockpitLiveReconciliation(BaseModel):
    status: str
    stored_live_connectors: int
    stored_live_assets: int
    latest_live_snapshot_at: datetime | None = None
    missing_wallets: list[str] = Field(default_factory=list)
    expected_zero_sources_open_value_eur: Decimal = Decimal("0")
    live_unverified_value_eur: Decimal = Decimal("0")
    blocker_count: int = 0
    warning_count: int = 0
    detail: str


class CockpitPortfolioPerformance(BaseModel):
    display_value_eur: Decimal = Decimal("0")
    display_value_basis: str = "calculated_ledger"
    live_value_eur: Decimal | None = None
    calculated_value_eur: Decimal = Decimal("0")
    open_cost_basis_eur: Decimal = Decimal("0")
    unrealized_return_eur: Decimal = Decimal("0")
    unrealized_return_pct: Decimal | None = None
    net_fiat_invested_eur: Decimal = Decimal("0")
    cost_basis_status: str = "empty"
    detail: str


class CockpitEvidenceHealth(BaseModel):
    status: str
    traces_count: int = 0
    canonical_count: int = 0
    legacy_ref_count: int = 0
    missing_decision_count: int = 0
    detail: str
    target: str = "review"


class CockpitTask(BaseModel):
    priority: CockpitTaskPriority
    title: str
    detail: str
    target: str
    count: int | None = None


class CockpitQuickAction(BaseModel):
    label: str
    target: str
    action_type: str
    enabled: bool = True


class CockpitPipelineStatus(BaseModel):
    last_import_at: datetime | None = None
    last_import_source: str | None = None
    last_canonical_event_at: datetime | None = None
    import_batches: int = 0


class CockpitSummary(BaseModel):
    generated_at: datetime
    portfolio_value_eur: Decimal
    export_allowed: bool
    export_status: str
    open_tasks: int
    top_assets: list[CockpitTopAsset] = Field(default_factory=list)
    top_sources: list[CockpitTopSource] = Field(default_factory=list)
    portfolio_performance: CockpitPortfolioPerformance
    price_coverage: CockpitPriceCoverage
    live_reconciliation: CockpitLiveReconciliation
    evidence_health: CockpitEvidenceHealth
    review: CockpitMetric
    pipeline: CockpitPipelineStatus
    tasks: list[CockpitTask] = Field(default_factory=list)
    quick_actions: list[CockpitQuickAction] = Field(default_factory=list)
    methodology: str
