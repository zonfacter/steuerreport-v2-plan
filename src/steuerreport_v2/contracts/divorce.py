from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from steuerreport_v2.contracts.divorce_inheritance import (
    DivorceInheritanceOriginReport,
)


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


class DivorceCapitalContributionRow(BaseModel):
    flow_id: str
    label: str
    amount_eur: Decimal = Decimal("0")
    transaction_evidence_status: Literal["confirmed", "provisional"]
    capital_origin: Literal[
        "unclassified",
        "claimed_inheritance",
        "inheritance",
        "marital_funds",
        "other_separate_property",
    ]
    capital_origin_evidence_status: Literal["pending", "documented"] = "pending"
    evidence_ref: str | None = None
    note: str


class DivorceCapitalOutflowRow(BaseModel):
    event_id: str
    event_time: datetime
    source: str
    account: str | None = None
    asset: str
    quantity: Decimal
    value_eur: Decimal | None = None
    classification: Literal[
        "internal_transfer_confirmed",
        "internal_product_transfer",
        "internal_service_position_loss",
        "trade_or_service_route",
        "technical_fee",
        "operational_adjustment_review",
        "external_distribution_confirmed",
        "external_distribution_review",
    ]
    evidence_status: Literal["confirmed", "review", "immaterial"]
    material: bool = False
    affects_flow_adjusted_change: bool = False
    tx_id: str | None = None
    raw_object_id: str | None = None
    evidence_ref: str | None = None
    note: str


class DivorceCapitalFlowGate(BaseModel):
    cutoff_at: datetime
    valuation_at: datetime
    materiality_threshold_eur: Decimal = Decimal("1")
    opening_value_eur: Decimal = Decimal("0")
    closing_value_eur: Decimal = Decimal("0")
    confirmed_contributions_eur: Decimal = Decimal("0")
    provisional_contributions_eur: Decimal = Decimal("0")
    total_contributions_eur: Decimal = Decimal("0")
    confirmed_external_distributions_eur: Decimal = Decimal("0")
    review_outflow_value_eur: Decimal = Decimal("0")
    internal_transfer_value_eur: Decimal = Decimal("0")
    internal_service_position_loss_value_eur: Decimal = Decimal("0")
    technical_fee_value_eur: Decimal = Decimal("0")
    operational_adjustment_value_eur: Decimal = Decimal("0")
    flow_adjusted_change_eur: Decimal = Decimal("0")
    flow_adjusted_change_if_all_review_outflows_are_external_eur: Decimal | None = None
    outflows_count: int = 0
    internal_outflows_count: int = 0
    confirmed_service_position_loss_count: int = 0
    confirmed_external_distributions_count: int = 0
    material_review_outflows_count: int = 0
    unpriced_review_outflows_count: int = 0
    capital_origin_pending_count: int = 0
    strict_ready: bool = False
    status: Literal["blocked", "review", "strict_ready"] = "blocked"
    contributions: list[DivorceCapitalContributionRow] = Field(default_factory=list)
    outflows: list[DivorceCapitalOutflowRow] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    methodology: str


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
    price_age_days: int | None = None
    price_status: str = "missing"
    valuation_flag: str = "valued"
    note: str | None = None


class DivorceEqualizationAccountRow(BaseModel):
    account: str
    source_accounts: list[str] = Field(default_factory=list)
    classification: str = "portfolio_account"
    valuation_basis: str = "current_snapshot"
    cutoff_value_eur: Decimal = Decimal("0")
    valuation_value_eur: Decimal = Decimal("0")
    valuation_review_value_eur: Decimal = Decimal("0")
    valuation_value_without_review_assets_eur: Decimal = Decimal("0")
    gross_change_eur: Decimal = Decimal("0")
    external_invest_since_cutoff_eur: Decimal = Decimal("0")
    adjusted_gain_loss_eur: Decimal = Decimal("0")
    position_count_cutoff: int = 0
    position_count_valuation: int = 0
    assets_cutoff: int = 0
    assets_valuation: int = 0
    asset_labels_cutoff: list[str] = Field(default_factory=list)
    asset_labels_valuation: list[str] = Field(default_factory=list)
    cutoff_assets: list[DivorceEqualizationAccountAssetRow] = Field(
        default_factory=list
    )
    valuation_assets: list[DivorceEqualizationAccountAssetRow] = Field(
        default_factory=list
    )
    note: str | None = None


class DivorceValuationGate(BaseModel):
    valuation_at: datetime
    materiality_threshold_eur: Decimal = Decimal("1")
    positions_count: int = 0
    material_positions_count: int = 0
    same_day_price_count: int = 0
    prior_day_price_count: int = 0
    stale_price_count: int = 0
    missing_price_count: int = 0
    review_asset_count: int = 0
    accepted_review_asset_count: int = 0
    strict_ready: bool = False
    status: str = "blocked"
    affected_assets: list[str] = Field(default_factory=list)
    accepted_review_assets: list[str] = Field(default_factory=list)
    token_review_evidence_refs: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)


class DivorceStichtagContext(BaseModel):
    separation_date: date
    separation_at_utc: datetime
    end_asset_date: date
    end_asset_at_utc: datetime
    timezone: str = "Europe/Berlin"
    end_asset_legal_basis: str = "§ 1384 BGB"
    end_asset_date_source: Literal["user_provided"] = "user_provided"
    court_evidence_status: Literal["pending_document", "documented"] = (
        "pending_document"
    )
    court_evidence_reference: str | None = None
    court_evidence_note: str


class DivorceEqualizationSummary(BaseModel):
    generated_at: datetime
    stichtage: DivorceStichtagContext
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
    confirmed_external_invest_since_cutoff_eur: Decimal = Decimal("0")
    confirmed_onramp_invest_since_cutoff_eur: Decimal = Decimal("0")
    provisional_onramp_invest_since_cutoff_eur: Decimal = Decimal("0")
    adjusted_gain_loss_excluding_new_invest_eur: Decimal = Decimal("0")
    adjusted_gain_loss_without_review_assets_eur: Decimal = Decimal("0")
    cutoff_missing_price_assets: list[str] = Field(default_factory=list)
    valuation_missing_price_assets: list[str] = Field(default_factory=list)
    fiat_deposits_since_cutoff_eur: Decimal = Decimal("0")
    direct_eur_buys_since_cutoff_eur: Decimal = Decimal("0")
    eur_asset_spent_without_quote_since_cutoff_eur: Decimal = Decimal("0")
    inheritance_origin_gate: DivorceInheritanceOriginReport
    capital_flow_gate: DivorceCapitalFlowGate
    cutoff_price_gate: DivorceValuationGate
    valuation_price_gate: DivorceValuationGate
    marital_pre_cutoff: DivorceEqualizationBucket
    post_cutoff_direct_eur_invest: DivorceEqualizationBucket
    post_cutoff_all_lots: DivorceEqualizationBucket
    accounts: list[DivorceEqualizationAccountRow] = Field(default_factory=list)
    live_reconciliation: list[DivorceEqualizationLiveReconciliationRow] = Field(
        default_factory=list
    )
    bmf_tax_boundary: DivorceEqualizationBmfTaxBoundary
    cash_flows: list[DivorceEqualizationCashFlow] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    legal_note: str
    methodology: str
