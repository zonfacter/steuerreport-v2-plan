from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class PortfolioPosition(BaseModel):
    account: str
    asset: str
    quantity: Decimal
    price_eur: Decimal | None = None
    value_eur: Decimal | None = None
    price_source: str | None = None
    priced_at: datetime | None = None
    token_name: str | None = None
    token_symbol: str | None = None
    token_mint: str | None = None
    token_verified: bool | None = None
    token_risk_status: str | None = None


class PortfolioAssetSummary(BaseModel):
    asset: str
    quantity: Decimal
    value_eur: Decimal
    position_count: int
    accounts: int
    price_sources: list[str] = Field(default_factory=list)
    priced_at_latest: datetime | None = None
    price_age_days: int | None = None
    price_status: str = "missing"
    token_name: str | None = None
    token_symbol: str | None = None
    token_mint: str | None = None
    token_verified: bool | None = None
    token_risk_status: str | None = None


class PortfolioAccountSummary(BaseModel):
    account: str
    value_eur: Decimal
    position_count: int
    assets: int


class PortfolioAccountAlias(BaseModel):
    alias: str
    canonical_account: str


class PortfolioVirtualWallet(BaseModel):
    label: str
    cutoff_date: str
    positions: list[PortfolioPosition] = Field(default_factory=list)
    total_value_eur: Decimal
    missing_price_assets: list[str] = Field(default_factory=list)
    methodology: str


class PortfolioTrendPoint(BaseModel):
    date: str
    total_value_eur: Decimal
    missing_price_assets: list[str] = Field(default_factory=list)


class PortfolioInvestmentLocation(BaseModel):
    account: str
    asset: str
    quantity: Decimal
    price_eur: Decimal | None = None
    value_eur: Decimal | None = None
    price_source: str | None = None
    priced_at: datetime | None = None


class PortfolioPriceQuality(BaseModel):
    asset: str
    price_eur: Decimal | None = None
    price_source: str | None = None
    priced_at: datetime | None = None
    price_age_days: int | None = None
    status: str
    warning: str | None = None


class PortfolioSeparationLot(BaseModel):
    lot_id: str
    asset: str
    acquired_at: datetime
    quantity_remaining: Decimal
    cost_basis_eur: Decimal
    current_value_eur: Decimal | None = None
    unrealized_gain_loss_eur: Decimal | None = None
    price_eur: Decimal | None = None
    price_source: str | None = None
    priced_at: datetime | None = None
    price_age_days: int | None = None
    price_status: str
    source_event_id: str
    source: str | None = None
    account: str | None = None
    event_type: str | None = None


class PortfolioSeparationReport(BaseModel):
    label: str
    cutoff_date: str
    valuation_at: datetime
    virtual_wallet: PortfolioVirtualWallet
    trend: list[PortfolioTrendPoint] = Field(default_factory=list)
    investment_locations: list[PortfolioInvestmentLocation] = Field(default_factory=list)
    unrealized_lots: list[PortfolioSeparationLot] = Field(default_factory=list)
    price_quality: list[PortfolioPriceQuality] = Field(default_factory=list)
    unmatched_lot_assets: list[str] = Field(default_factory=list)
    cost_basis_eur_total: Decimal = Decimal("0")
    current_value_eur_total: Decimal = Decimal("0")
    unrealized_gain_loss_eur_total: Decimal = Decimal("0")
    grafana_hint: str


class PortfolioFiatDeposit(BaseModel):
    time_utc: datetime
    source: str
    account: str | None = None
    asset: str
    receive_amount_eur: Decimal
    deposit_amount_original: str | None = None
    method: str | None = None
    status: str | None = None
    transaction_id: str | None = None
    source_file: str | None = None
    source_row: int | None = None
    raw_object_id: str | None = None


class PortfolioFiatDepositReport(BaseModel):
    cutoff_date: str
    target_source: str
    rows: list[PortfolioFiatDeposit] = Field(default_factory=list)
    rows_count: int
    total_receive_amount_eur: Decimal
    total_deposit_amount_eur: Decimal | None = None
    total_fee_or_difference_eur: Decimal | None = None
    methodology: str


class PortfolioSnapshot(BaseModel):
    positions: list[PortfolioPosition]
    total_value_eur: Decimal
    asset_summary: list[PortfolioAssetSummary] = Field(default_factory=list)
    account_summary: list[PortfolioAccountSummary] = Field(default_factory=list)
    excluded_account_summary: list[PortfolioAccountSummary] = Field(default_factory=list)
    excluded_value_eur: Decimal = Decimal("0")
    missing_price_assets: list[str]
    separation_virtual_wallet: PortfolioVirtualWallet | None = None
    resolved_account_aliases: list[PortfolioAccountAlias] = Field(default_factory=list)
    unresolved_truncated_accounts: list[str] = Field(default_factory=list)


class PortfolioValuationAuditRow(BaseModel):
    asset: str
    quantity: Decimal
    current_price_eur: Decimal | None = None
    current_value_eur: Decimal
    current_price_source: str | None = None
    current_priced_at: datetime | None = None
    current_price_status: str
    previous_price_eur: Decimal | None = None
    previous_value_eur: Decimal | None = None
    previous_price_source: str | None = None
    previous_priced_at: datetime | None = None
    price_delta_pct: Decimal | None = None
    value_delta_eur: Decimal | None = None
    accounts: int = 0
    position_count: int = 0
    note: str


class PortfolioValuationAuditReport(BaseModel):
    generated_at: datetime
    total_value_eur: Decimal
    previous_total_value_eur: Decimal | None = None
    value_delta_eur: Decimal | None = None
    rows: list[PortfolioValuationAuditRow] = Field(default_factory=list)
    methodology: str


class PortfolioAsOfSnapshot(BaseModel):
    as_of: datetime
    label: str
    positions: list[PortfolioPosition]
    total_value_eur: Decimal
    asset_summary: list[PortfolioAssetSummary] = Field(default_factory=list)
    account_summary: list[PortfolioAccountSummary] = Field(default_factory=list)
    excluded_account_summary: list[PortfolioAccountSummary] = Field(default_factory=list)
    excluded_value_eur: Decimal = Decimal("0")
    missing_price_assets: list[str] = Field(default_factory=list)
    resolved_account_aliases: list[PortfolioAccountAlias] = Field(default_factory=list)
    unresolved_truncated_accounts: list[str] = Field(default_factory=list)
    methodology: str
    transfer_context_note: str | None = None


class PortfolioSourceAsset(BaseModel):
    asset: str
    quantity: Decimal
    value_eur: Decimal
    position_count: int
    token_name: str | None = None
    token_symbol: str | None = None
    token_mint: str | None = None
    token_verified: bool | None = None
    token_risk_status: str | None = None


class PortfolioSourceAccount(BaseModel):
    account: str
    source_group: str
    source_type: str
    value_eur: Decimal
    position_count: int
    assets: int
    current_status: str = "ledger_current"
    note: str | None = None
    asset_summary: list[PortfolioSourceAsset] = Field(default_factory=list)


class PortfolioSourceGroup(BaseModel):
    source_group: str
    source_type: str
    value_eur: Decimal
    account_count: int
    position_count: int
    assets: int
    current_status: str = "ledger_current"
    note: str | None = None
    accounts: list[PortfolioSourceAccount] = Field(default_factory=list)
    asset_summary: list[PortfolioSourceAsset] = Field(default_factory=list)


class PortfolioSourceOverview(BaseModel):
    total_value_eur: Decimal
    groups: list[PortfolioSourceGroup] = Field(default_factory=list)
    accounts: list[PortfolioSourceAccount] = Field(default_factory=list)
    methodology: str


class PortfolioTokenRiskRow(BaseModel):
    asset: str
    token_name: str | None = None
    token_symbol: str | None = None
    token_mint: str | None = None
    token_verified: bool | None = None
    token_risk_status: str
    quantity: Decimal
    value_eur: Decimal
    position_count: int
    accounts: int
    price_status: str
    priced_at_latest: datetime | None = None
    discovered_sources: list[str] = Field(default_factory=list)
    positions: list[PortfolioPosition] = Field(default_factory=list)


class PortfolioTokenRiskReport(BaseModel):
    generated_at: datetime
    risk_status: str
    min_value_eur: Decimal
    total_value_eur: Decimal
    rows_count: int
    spam_review_count: int = 0
    review_count: int = 0
    unverified_plausible_count: int = 0
    verified_count: int = 0
    rows: list[PortfolioTokenRiskRow] = Field(default_factory=list)
    methodology: str


class PortfolioReconciliationRow(BaseModel):
    source_group: str
    source_type: str
    asset: str | None = None
    ledger_quantity: Decimal | None = None
    ledger_value_eur: Decimal
    external_quantity: Decimal | None = None
    external_value_eur: Decimal | None = None
    delta_quantity: Decimal | None = None
    delta_value_eur: Decimal | None = None
    status: str
    severity: str
    evidence: str
    next_action: str


class PortfolioReconciliationReport(BaseModel):
    generated_at: datetime
    total_ledger_value_eur: Decimal
    expected_zero_ledger_value_eur: Decimal
    live_unverified_ledger_value_eur: Decimal
    missing_wallets: list[str] = Field(default_factory=list)
    rows: list[PortfolioReconciliationRow] = Field(default_factory=list)
    connector_actions: list[str] = Field(default_factory=list)
    methodology: str


class PortfolioLiveBalanceSnapshot(BaseModel):
    snapshot_id: str
    connector_id: str
    asset: str
    quantity: Decimal
    source: str
    fetched_at: datetime
    account_type: str | None = None
    product_id: str | None = None
    position_id: str | None = None
    event_type: str | None = None


class PortfolioReconciliationRefreshConnectorResult(BaseModel):
    connector_id: str
    status: str
    snapshots: int = 0
    previous_snapshot_at: datetime | None = None
    message: str


class PortfolioReconciliationRefreshResult(BaseModel):
    fetched_at: datetime
    connectors: list[str] = Field(default_factory=list)
    imported_snapshots: int
    snapshots: list[PortfolioLiveBalanceSnapshot] = Field(default_factory=list)
    connector_results: list[PortfolioReconciliationRefreshConnectorResult] = Field(default_factory=list)
    report: PortfolioReconciliationReport


class PortfolioWalletHistoryImportRequest(BaseModel):
    wallet_address: str | None = None
    before_signature: str | None = None
    max_signatures: int = Field(default=1000, ge=1, le=50000)
    max_transactions: int = Field(default=1000, ge=1, le=50000)
    aggregate_jupiter: bool = True
    jupiter_window_seconds: int = Field(default=2, ge=1, le=30)


class PortfolioWalletHistoryImportResult(BaseModel):
    wallet_address: str
    source: str
    batch_id: str
    filename: str
    fetched_rows: int
    signature_count: int
    first_signature: str | None = None
    last_signature: str | None = None
    duplicate_batch: bool = False
    normalized_events: int
    skipped_raw_objects: int
    pipeline: dict[str, object]
    warnings: list[dict[str, str]] = Field(default_factory=list)
