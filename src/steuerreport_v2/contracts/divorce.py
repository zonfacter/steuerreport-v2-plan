from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class DivorceEqualizationAssetRow(BaseModel):
    asset: str
    quantity_open: Decimal = Decimal("0")
    open_cost_basis_eur: Decimal = Decimal("0")
    open_value_eur: Decimal = Decimal("0")
    unrealized_gain_loss_eur: Decimal = Decimal("0")
    sold_quantity: Decimal = Decimal("0")
    sold_cost_basis_eur: Decimal = Decimal("0")
    sold_proceeds_eur: Decimal = Decimal("0")
    realized_gain_loss_eur: Decimal = Decimal("0")
    total_cost_basis_eur: Decimal = Decimal("0")
    total_value_or_proceeds_eur: Decimal = Decimal("0")
    total_gain_loss_eur: Decimal = Decimal("0")
    latest_price_eur: Decimal | None = None
    latest_price_at: datetime | None = None
    latest_price_source: str | None = None
    missing_price_count: int = 0


class DivorceEqualizationBucket(BaseModel):
    bucket_id: str
    label: str
    description: str
    open_lots_count: int = 0
    sold_lines_count: int = 0
    open_cost_basis_eur: Decimal = Decimal("0")
    open_value_eur: Decimal = Decimal("0")
    unrealized_gain_loss_eur: Decimal = Decimal("0")
    sold_cost_basis_eur: Decimal = Decimal("0")
    sold_proceeds_eur: Decimal = Decimal("0")
    realized_gain_loss_eur: Decimal = Decimal("0")
    total_cost_basis_eur: Decimal = Decimal("0")
    total_value_or_proceeds_eur: Decimal = Decimal("0")
    total_gain_loss_eur: Decimal = Decimal("0")
    missing_price_assets: list[str] = Field(default_factory=list)
    assets: list[DivorceEqualizationAssetRow] = Field(default_factory=list)


class DivorceEqualizationCashFlow(BaseModel):
    label: str
    amount_eur: Decimal = Decimal("0")
    note: str


class DivorceEqualizationBmfTaxBoundary(BaseModel):
    bmf_reference: str
    bmf_reference_url: str
    tax_methodology_summary_endpoint: str
    tax_year_methodology_endpoint_template: str
    tax_year_evidence_package_endpoint_template: str
    boundary_notes: list[str] = Field(default_factory=list)


class DivorceEqualizationLiveReconciliationRow(BaseModel):
    source_group: str
    source_type: str
    asset: str | None = None
    ledger_quantity: Decimal | None = None
    ledger_value_eur: Decimal = Decimal("0")
    external_quantity: Decimal | None = None
    external_value_eur: Decimal | None = None
    delta_quantity: Decimal | None = None
    delta_value_eur: Decimal | None = None
    status: str
    severity: str
    evidence: str
    next_action: str


class DivorceEqualizationAccountAssetRow(BaseModel):
    asset: str
    quantity: Decimal = Decimal("0")
    value_eur: Decimal = Decimal("0")
    price_source: str | None = None
    priced_at: datetime | None = None
    valuation_flag: str = "valued"
    note: str | None = None


class DivorceEqualizationAccountRow(BaseModel):
    account: str
    classification: str = "portfolio_account"
    valuation_basis: str = "current_snapshot"
    cutoff_value_eur: Decimal = Decimal("0")
    valuation_value_eur: Decimal = Decimal("0")
    valuation_review_value_eur: Decimal = Decimal("0")
    valuation_value_without_review_assets_eur: Decimal = Decimal("0")
    gross_change_eur: Decimal = Decimal("0")
    position_count_cutoff: int = 0
    position_count_valuation: int = 0
    assets_cutoff: int = 0
    assets_valuation: int = 0
    asset_labels_cutoff: list[str] = Field(default_factory=list)
    asset_labels_valuation: list[str] = Field(default_factory=list)
    valuation_assets: list[DivorceEqualizationAccountAssetRow] = Field(default_factory=list)
    note: str | None = None


class DivorceEqualizationSummary(BaseModel):
    generated_at: datetime
    cutoff_at: datetime
    valuation_at: datetime | None = None
    latest_event_at: datetime | None = None
    latest_price_at: datetime | None = None
    cutoff_portfolio_value_eur: Decimal = Decimal("0")
    valuation_portfolio_value_eur: Decimal = Decimal("0")
    valuation_review_value_eur: Decimal = Decimal("0")
    valuation_dust_value_eur: Decimal = Decimal("0")
    valuation_value_without_review_assets_eur: Decimal = Decimal("0")
    gross_portfolio_change_eur: Decimal = Decimal("0")
    gross_portfolio_change_without_review_assets_eur: Decimal = Decimal("0")
    net_external_invest_since_cutoff_eur: Decimal = Decimal("0")
    adjusted_gain_loss_excluding_new_invest_eur: Decimal = Decimal("0")
    adjusted_gain_loss_without_review_assets_eur: Decimal = Decimal("0")
    cutoff_missing_price_assets: list[str] = Field(default_factory=list)
    valuation_missing_price_assets: list[str] = Field(default_factory=list)
    fiat_deposits_since_cutoff_eur: Decimal = Decimal("0")
    direct_eur_buys_since_cutoff_eur: Decimal = Decimal("0")
    eur_asset_spent_without_quote_since_cutoff_eur: Decimal = Decimal("0")
    marital_pre_cutoff: DivorceEqualizationBucket
    post_cutoff_direct_eur_invest: DivorceEqualizationBucket
    post_cutoff_all_lots: DivorceEqualizationBucket
    accounts: list[DivorceEqualizationAccountRow] = Field(default_factory=list)
    live_reconciliation: list[DivorceEqualizationLiveReconciliationRow] = Field(default_factory=list)
    bmf_tax_boundary: DivorceEqualizationBmfTaxBoundary
    cash_flows: list[DivorceEqualizationCashFlow] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    legal_note: str
    methodology: str
