from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

TaxYearState = Literal["finished", "blocked", "open", "historical_open", "empty"]
TaxYearFilingActionStatus = Literal["ready", "conservative_ready", "review", "blocked"]


class TaxYearIssue(BaseModel):
    code: str
    severity: str
    message: str
    count: int = 1
    blocks_export: bool = True


class TaxYearAssetBreakdown(BaseModel):
    asset: str
    gain_loss_eur: Decimal = Decimal("0")
    proceeds_eur: Decimal = Decimal("0")
    acquisition_cost_eur: Decimal = Decimal("0")
    tax_line_count: int = 0


class TaxYearStatus(BaseModel):
    year: int
    state: TaxYearState
    label: str
    is_closed_historical_year: bool = False
    export_blocked: bool = False
    realized_gain_loss_eur: Decimal = Decimal("0")
    taxable_disposal_proceeds_eur: Decimal = Decimal("0")
    acquisition_cost_eur: Decimal = Decimal("0")
    tax_lines_count: int = 0
    tax_free_gain_loss_eur: Decimal = Decimal("0")
    tax_free_disposal_proceeds_eur: Decimal = Decimal("0")
    tax_free_acquisition_cost_eur: Decimal = Decimal("0")
    tax_free_lines_count: int = 0
    rewards_income_eur: Decimal = Decimal("0")
    rewards_events_count: int = 0
    derivative_pnl_eur: Decimal = Decimal("0")
    derivative_lines_count: int = 0
    fees_eur: Decimal = Decimal("0")
    missing_price_groups: int = 0
    unmatched_disposals: int = 0
    review_issues_count: int = 0
    top_assets: list[TaxYearAssetBreakdown] = Field(default_factory=list)
    issues: list[TaxYearIssue] = Field(default_factory=list)


class TaxYearsSummary(BaseModel):
    years: list[TaxYearStatus] = Field(default_factory=list)
    available_years: list[int] = Field(default_factory=list)
    methodology: str


class TaxPaymentChecklistItem(BaseModel):
    category: Literal["eintragen", "beleg", "pruefen"]
    label: str
    amount_eur: Decimal | None = None
    target: str
    detail: str
    evidence_ref: str | None = None
    severity: Literal["info", "warning", "blocker"] = "info"


class TaxPaymentOverviewRow(BaseModel):
    year: int
    status: str
    private_disposals_gain_loss_eur: Decimal = Decimal("0")
    rewards_mining_staking_income_eur: Decimal = Decimal("0")
    derivative_pnl_eur: Decimal = Decimal("0")
    tax_free_private_disposals_eur: Decimal = Decimal("0")
    declaration_bucket: str
    where_to_enter: str
    what_to_do: str
    evidence_refs: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    checklist: list[TaxPaymentChecklistItem] = Field(default_factory=list)
    display_line: str


class TaxPaymentOverview(BaseModel):
    generated_at: str
    rows: list[TaxPaymentOverviewRow] = Field(default_factory=list)
    ascii_table: str
    methodology: str


class TaxYearDetail(TaxYearStatus):
    asset_breakdown: list[TaxYearAssetBreakdown] = Field(default_factory=list)
    missing_price_assets: list[str] = Field(default_factory=list)
    sample_unmatched_ids: list[str] = Field(default_factory=list)
    sample_tax_line_ids: list[str] = Field(default_factory=list)
    methodology: str


class TaxDeclarationGuideEntry(BaseModel):
    section: str
    field_label: str
    amount_eur: Decimal
    sign: Literal["gain", "loss", "income", "neutral"]
    evidence_ref: str
    note: str


class TaxYearReviewDecisionSummary(BaseModel):
    decision_id: str
    decision_type: str
    scope: str
    title: str
    evidence_ref: str | None = None
    category: Literal["beleg", "pruefen"] = "beleg"
    effect_summary: str
    created_at: str


class TaxDeclarationGuide(BaseModel):
    year: int
    generated_at: str
    export_ready: bool
    realized_gain_loss_eur: Decimal = Decimal("0")
    taxable_disposal_proceeds_eur: Decimal = Decimal("0")
    acquisition_cost_eur: Decimal = Decimal("0")
    tax_free_gain_loss_eur: Decimal = Decimal("0")
    tax_free_disposal_proceeds_eur: Decimal = Decimal("0")
    tax_free_acquisition_cost_eur: Decimal = Decimal("0")
    tax_free_lines_count: int = 0
    rewards_income_eur: Decimal = Decimal("0")
    derivative_pnl_eur: Decimal = Decimal("0")
    hnt_gain_loss_eur: Decimal = Decimal("0")
    hnt_disposal_proceeds_eur: Decimal = Decimal("0")
    hnt_acquisition_cost_eur: Decimal = Decimal("0")
    hnt_tax_line_count: int = 0
    loss_assets: list[TaxYearAssetBreakdown] = Field(default_factory=list)
    gain_assets: list[TaxYearAssetBreakdown] = Field(default_factory=list)
    entries: list[TaxDeclarationGuideEntry] = Field(default_factory=list)
    review_decisions: list[TaxYearReviewDecisionSummary] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    evidence_exports: list[str] = Field(default_factory=list)
    methodology: str


class TaxYearFilingSummaryLine(BaseModel):
    order: int
    topic: Literal["private_disposal", "income", "derivative", "tax_free", "appendix", "evidence", "review"]
    label: str
    amount_eur: Decimal | None = None
    tax_treatment: str
    declaration_target: str
    evidence_ref: str | None = None
    note: str


class TaxYearFilingChecklistItem(BaseModel):
    order: int
    category: Literal["eintragen", "beilegen", "archivieren", "pruefen"]
    label: str
    action: str
    source_topic: str
    amount_eur: Decimal | None = None
    evidence_ref: str | None = None
    done_when: str
    note: str


class TaxYearFilingSummary(BaseModel):
    year: int
    generated_at: str
    export_ready: bool
    status_label: str
    plain_language_summary: str
    taxable_private_disposals_eur: Decimal = Decimal("0")
    taxable_disposal_proceeds_eur: Decimal = Decimal("0")
    acquisition_cost_eur: Decimal = Decimal("0")
    rewards_mining_staking_income_eur: Decimal = Decimal("0")
    derivative_pnl_eur: Decimal = Decimal("0")
    tax_free_private_disposals_eur: Decimal = Decimal("0")
    tax_free_lines_count: int = 0
    bmf_closure_appendix_status: str | None = None
    bmf_closure_appendix_items_count: int = 0
    bmf_closure_appendix_manual_evidence_required_count: int = 0
    can_file_with_conservative_appendix: bool = False
    lines: list[TaxYearFilingSummaryLine] = Field(default_factory=list)
    checklist: list[TaxYearFilingChecklistItem] = Field(default_factory=list)
    review_decisions: list[TaxYearReviewDecisionSummary] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    ascii_table: str
    checklist_ascii: str
    methodology: str


class TaxYearFilingMatrixRow(BaseModel):
    year: int
    status_label: str
    export_ready: bool
    action_status: TaxYearFilingActionStatus
    next_action: str
    taxable_private_disposals_eur: Decimal = Decimal("0")
    rewards_mining_staking_income_eur: Decimal = Decimal("0")
    derivative_pnl_eur: Decimal = Decimal("0")
    tax_free_private_disposals_eur: Decimal = Decimal("0")
    checklist_counts: dict[str, int] = Field(default_factory=dict)
    bmf_closure_appendix_status: str | None = None
    bmf_closure_appendix_items_count: int = 0
    bmf_closure_appendix_manual_evidence_required_count: int = 0
    warnings_count: int = 0
    review_decisions_count: int = 0
    filing_summary_endpoint: str
    filing_checklist_csv_endpoint: str
    evidence_package_endpoint: str
    display_line: str


class TaxYearFilingMatrix(BaseModel):
    generated_at: str
    rows: list[TaxYearFilingMatrixRow] = Field(default_factory=list)
    ready_years: list[int] = Field(default_factory=list)
    conservative_ready_years: list[int] = Field(default_factory=list)
    review_years: list[int] = Field(default_factory=list)
    blocked_years: list[int] = Field(default_factory=list)
    ascii_table: str
    methodology: str


class TaxYearCorrectionMapLine(BaseModel):
    order: int
    topic: str
    label: str
    action_category: Literal["eintragen", "korrigieren_pruefen", "beilegen", "archivieren", "pruefen"]
    amount_eur: Decimal | None = None
    declaration_target: str
    evidence_ref: str | None = None
    correction_note: str
    risk_level: Literal["info", "review", "blocked"] = "info"


class TaxYearCorrectionMap(BaseModel):
    year: int
    generated_at: str
    filing_status: str
    amendment_review_recommended: bool = False
    amendment_reason: str
    taxable_private_disposals_eur: Decimal = Decimal("0")
    rewards_mining_staking_income_eur: Decimal = Decimal("0")
    derivative_pnl_eur: Decimal = Decimal("0")
    tax_free_private_disposals_eur: Decimal = Decimal("0")
    lines: list[TaxYearCorrectionMapLine] = Field(default_factory=list)
    ascii_table: str
    methodology: str


class TaxYearsCorrectionMap(BaseModel):
    generated_at: str
    years: list[TaxYearCorrectionMap] = Field(default_factory=list)
    amendment_review_years: list[int] = Field(default_factory=list)
    archive_only_years: list[int] = Field(default_factory=list)
    blocked_years: list[int] = Field(default_factory=list)
    ascii_table: str
    methodology: str


class TaxYearFilingClosureRow(BaseModel):
    year: int
    filing_status: TaxYearFilingActionStatus
    filing_status_label: str
    export_ready: bool
    declaration_bucket: str
    where_to_enter: str
    private_disposals_gain_loss_eur: Decimal = Decimal("0")
    rewards_mining_staking_income_eur: Decimal = Decimal("0")
    derivative_pnl_eur: Decimal = Decimal("0")
    tax_free_private_disposals_eur: Decimal = Decimal("0")
    eintragen_count: int = 0
    beilegen_count: int = 0
    pruefen_count: int = 0
    archivieren_count: int = 0
    amendment_review_recommended: bool = False
    amendment_reason: str
    next_action: str
    correction_action: str
    filing_summary_endpoint: str
    filing_checklist_csv_endpoint: str
    correction_map_endpoint: str
    correction_map_csv_endpoint: str
    evidence_package_endpoint: str
    display_line: str


class TaxYearsFilingClosureOverview(BaseModel):
    generated_at: str
    rows: list[TaxYearFilingClosureRow] = Field(default_factory=list)
    ready_years: list[int] = Field(default_factory=list)
    conservative_ready_years: list[int] = Field(default_factory=list)
    review_years: list[int] = Field(default_factory=list)
    blocked_years: list[int] = Field(default_factory=list)
    amendment_review_years: list[int] = Field(default_factory=list)
    total_private_disposals_gain_loss_eur: Decimal = Decimal("0")
    total_rewards_mining_staking_income_eur: Decimal = Decimal("0")
    total_derivative_pnl_eur: Decimal = Decimal("0")
    total_tax_free_private_disposals_eur: Decimal = Decimal("0")
    ascii_table: str
    methodology: str


class TaxIncomeAssetBreakdown(BaseModel):
    asset: str
    event_type: str
    classification: str
    events_count: int = 0
    quantity: Decimal = Decimal("0")
    income_eur: Decimal = Decimal("0")
    missing_value_count: int = 0
    sources: list[str] = Field(default_factory=list)


class TaxIncomeEventPreview(BaseModel):
    event_id: str
    event_time: str
    event_type: str
    source: str
    account: str | None = None
    asset: str
    quantity: Decimal
    income_eur: Decimal | None = None
    price_source: str | None = None
    priced_at: str | None = None
    valuation_status: str
    classification: str


class TaxIncomeReport(BaseModel):
    year: int
    generated_at: str
    total_income_eur: Decimal = Decimal("0")
    reward_income_eur: Decimal = Decimal("0")
    generic_income_eur: Decimal = Decimal("0")
    declaration_income_eur: Decimal = Decimal("0")
    review_only_income_eur: Decimal = Decimal("0")
    taxable_reward_events_count: int = 0
    review_only_events_count: int = 0
    events_count: int = 0
    valued_events_count: int = 0
    missing_value_count: int = 0
    ignored_non_positive_count: int = 0
    classification_counts: dict[str, int] = Field(default_factory=dict)
    assets: list[TaxIncomeAssetBreakdown] = Field(default_factory=list)
    missing_assets: list[str] = Field(default_factory=list)
    events: list[TaxIncomeEventPreview] = Field(default_factory=list)
    methodology: str


class TaxRewardTradingSeparationRow(BaseModel):
    year: int
    asset: str
    reward_income_eur: Decimal = Decimal("0")
    reward_quantity: Decimal = Decimal("0")
    reward_events_count: int = 0
    reward_event_types: list[str] = Field(default_factory=list)
    reward_sources: list[str] = Field(default_factory=list)
    trade_taxable_gain_loss_eur: Decimal = Decimal("0")
    trade_taxable_proceeds_eur: Decimal = Decimal("0")
    trade_taxable_acquisition_cost_eur: Decimal = Decimal("0")
    trade_taxable_lines_count: int = 0
    trade_tax_free_gain_loss_eur: Decimal = Decimal("0")
    trade_tax_free_proceeds_eur: Decimal = Decimal("0")
    trade_tax_free_acquisition_cost_eur: Decimal = Decimal("0")
    trade_tax_free_lines_count: int = 0
    total_trade_gain_loss_eur: Decimal = Decimal("0")
    tax_note: str
    income_guide_endpoint: str
    asset_fifo_drilldown_endpoint: str


class TaxRewardTradingSeparationReport(BaseModel):
    generated_at: str
    years: list[int] = Field(default_factory=list)
    assets: list[str] = Field(default_factory=list)
    total_reward_income_eur: Decimal = Decimal("0")
    total_trade_taxable_gain_loss_eur: Decimal = Decimal("0")
    total_trade_tax_free_gain_loss_eur: Decimal = Decimal("0")
    rows: list[TaxRewardTradingSeparationRow] = Field(default_factory=list)
    ascii_table: str
    methodology: str


class TaxYearGainLossRealityAssetRow(BaseModel):
    year: int
    asset: str
    realized_taxable_gain_loss_eur: Decimal = Decimal("0")
    realized_taxable_proceeds_eur: Decimal = Decimal("0")
    realized_taxable_acquisition_cost_eur: Decimal = Decimal("0")
    realized_taxable_lines_count: int = 0
    realized_tax_free_gain_loss_eur: Decimal = Decimal("0")
    realized_tax_free_lines_count: int = 0
    open_quantity: Decimal = Decimal("0")
    open_current_value_eur: Decimal = Decimal("0")
    open_cost_basis_eur: Decimal = Decimal("0")
    open_unrealized_gain_loss_eur: Decimal = Decimal("0")
    open_lots_count: int = 0
    open_tax_free_now_value_eur: Decimal = Decimal("0")
    open_not_yet_tax_free_value_eur: Decimal = Decimal("0")
    potential_loss_not_realized_eur: Decimal = Decimal("0")
    current_price_source: str | None = None
    note: str
    asset_fifo_drilldown_endpoint: str


class TaxYearGainLossRealityCheck(BaseModel):
    year: int
    generated_at: str
    taxable_gain_loss_eur: Decimal = Decimal("0")
    tax_free_gain_loss_eur: Decimal = Decimal("0")
    gross_disposal_proceeds_eur: Decimal = Decimal("0")
    open_current_value_eur: Decimal = Decimal("0")
    open_cost_basis_eur: Decimal = Decimal("0")
    open_unrealized_gain_loss_eur: Decimal = Decimal("0")
    potential_loss_not_realized_eur: Decimal = Decimal("0")
    rows: list[TaxYearGainLossRealityAssetRow] = Field(default_factory=list)
    plain_language_summary: str
    caveats: list[str] = Field(default_factory=list)
    ascii_table: str
    methodology: str


class TaxYearGainEvidenceLine(BaseModel):
    tax_line_id: str
    asset: str
    acquired_at: str
    disposed_at: str
    holding_days: int
    quantity: Decimal
    acquisition_cost_eur: Decimal
    disposal_proceeds_eur: Decimal
    gain_loss_eur: Decimal
    gain_loss_ratio_pct: Decimal = Decimal("0")
    lot_id: str
    acquisition_event_id: str | None = None
    acquisition_source: str | None = None
    acquisition_event_type: str | None = None
    acquisition_quote_asset: str | None = None
    acquisition_quote_quantity: Decimal | None = None
    acquisition_raw_object_id: str | None = None
    acquisition_raw_evidence: str
    acquisition_price_asset: str | None = None
    acquisition_price_eur: Decimal | None = None
    acquisition_price_source: str | None = None
    acquisition_priced_at: str | None = None
    acquisition_price_age_days: int | None = None
    acquisition_expected_cost_eur: Decimal | None = None
    acquisition_cost_delta_eur: Decimal | None = None
    acquisition_cost_delta_pct: Decimal | None = None
    disposal_event_id: str | None = None
    disposal_source: str | None = None
    disposal_event_type: str | None = None
    disposal_quote_asset: str | None = None
    disposal_quote_quantity: Decimal | None = None
    disposal_raw_object_id: str | None = None
    disposal_raw_evidence: str
    disposal_price_asset: str | None = None
    disposal_price_eur: Decimal | None = None
    disposal_price_source: str | None = None
    disposal_priced_at: str | None = None
    disposal_price_age_days: int | None = None
    disposal_expected_proceeds_eur: Decimal | None = None
    disposal_proceeds_delta_eur: Decimal | None = None
    disposal_proceeds_delta_pct: Decimal | None = None
    absolute_price_delta_eur: Decimal = Decimal("0")
    open_price_delta_eur: Decimal = Decimal("0")
    max_price_delta_pct: Decimal = Decimal("0")
    delta_classification: str = "no_material_delta"
    delta_explanation: str
    delta_recommended_action: str
    event_level_status: str | None = None
    event_level_delta_eur: Decimal | None = None
    event_level_delta_pct: Decimal | None = None
    event_level_reconciled: bool = False
    event_level_note: str | None = None
    acquisition_event_level_status: str | None = None
    acquisition_event_level_delta_eur: Decimal | None = None
    acquisition_event_level_delta_pct: Decimal | None = None
    acquisition_event_level_reconciled: bool = False
    acquisition_event_level_note: str | None = None
    valuation_path: str
    risk_level: Literal["ok", "review", "high"]
    review_reasons: list[str] = Field(default_factory=list)
    asset_fifo_drilldown_endpoint: str


class TaxYearGainEvidenceDeltaGroup(BaseModel):
    year: int
    classification: str
    risk_level: Literal["ok", "review", "high"]
    lines_count: int = 0
    gain_loss_eur: Decimal = Decimal("0")
    absolute_delta_eur: Decimal = Decimal("0")
    open_delta_eur: Decimal = Decimal("0")
    max_delta_pct: Decimal = Decimal("0")
    assets: list[str] = Field(default_factory=list)
    quote_assets: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    explanation: str
    recommended_action: str


class TaxYearGainEvidencePriceDeltaLine(BaseModel):
    year: int
    tax_line_id: str
    asset: str
    acquired_at: str
    disposed_at: str
    gain_loss_eur: Decimal = Decimal("0")
    classification: str
    dominant_side: Literal["acquisition", "disposal", "both", "none"]
    acquisition_delta_eur: Decimal = Decimal("0")
    acquisition_delta_pct: Decimal = Decimal("0")
    disposal_delta_eur: Decimal = Decimal("0")
    disposal_delta_pct: Decimal = Decimal("0")
    absolute_delta_eur: Decimal = Decimal("0")
    max_delta_pct: Decimal = Decimal("0")
    acquisition_quote_asset: str | None = None
    acquisition_quote_quantity: Decimal | None = None
    acquisition_event_id: str | None = None
    acquisition_event_split_count: int = 0
    acquisition_side_diagnosis: str
    disposal_quote_asset: str | None = None
    disposal_quote_quantity: Decimal | None = None
    disposal_event_id: str | None = None
    disposal_event_split_count: int = 0
    disposal_side_diagnosis: str
    event_level_status: str | None = None
    event_level_delta_eur: Decimal | None = None
    event_level_delta_pct: Decimal | None = None
    event_level_explanation: str | None = None
    root_cause: str
    explanation: str
    recommended_action: str
    asset_fifo_drilldown_endpoint: str


class TaxYearGainEvidencePriceDeltaDrilldown(BaseModel):
    year: int
    generated_at: str
    classification_filter: str | None = None
    lines_count: int = 0
    gain_loss_eur: Decimal = Decimal("0")
    absolute_delta_eur: Decimal = Decimal("0")
    acquisition_delta_eur: Decimal = Decimal("0")
    disposal_delta_eur: Decimal = Decimal("0")
    dominant_acquisition_count: int = 0
    dominant_disposal_count: int = 0
    dominant_both_count: int = 0
    split_line_review_count: int = 0
    root_cause_counts: dict[str, int] = Field(default_factory=dict)
    event_level_reconciled_count: int = 0
    event_level_review_count: int = 0
    event_level_unchecked_count: int = 0
    lines: list[TaxYearGainEvidencePriceDeltaLine] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    methodology: str


class TaxYearGainEvidenceEventDeltaLine(BaseModel):
    year: int
    disposal_event_id: str
    disposed_at: str
    source: str | None = None
    event_type: str | None = None
    event_asset: str | None = None
    event_quantity: Decimal | None = None
    quote_asset: str | None = None
    quote_quantity: Decimal | None = None
    price_asset: str | None = None
    price_eur: Decimal | None = None
    price_source: str | None = None
    priced_at: str | None = None
    price_age_days: int | None = None
    tax_line_count: int = 0
    assets: list[str] = Field(default_factory=list)
    taxable_disposed_quantity: Decimal = Decimal("0")
    total_event_disposed_quantity: Decimal | None = None
    taxable_event_fraction: Decimal | None = None
    event_total_proceeds_eur: Decimal | None = None
    actual_proceeds_eur: Decimal = Decimal("0")
    expected_proceeds_eur: Decimal | None = None
    event_delta_eur: Decimal | None = None
    event_delta_pct: Decimal | None = None
    split_line_absolute_delta_eur: Decimal = Decimal("0")
    split_line_count: int = 0
    status: Literal["event_level_ok", "event_level_review", "missing_price_evidence"]
    explanation: str
    recommended_action: str


class TaxYearGainEvidenceEventDeltaReview(BaseModel):
    year: int
    generated_at: str
    events_count: int = 0
    event_level_ok_count: int = 0
    event_level_review_count: int = 0
    missing_price_count: int = 0
    tax_line_count: int = 0
    actual_proceeds_eur: Decimal = Decimal("0")
    expected_proceeds_eur: Decimal = Decimal("0")
    event_delta_eur: Decimal = Decimal("0")
    split_line_absolute_delta_eur: Decimal = Decimal("0")
    lines: list[TaxYearGainEvidenceEventDeltaLine] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    methodology: str


class TaxYearGainEvidenceAcquisitionEventDeltaLine(BaseModel):
    year: int
    acquisition_event_id: str
    acquired_at: str
    source: str | None = None
    event_type: str | None = None
    event_asset: str | None = None
    event_quantity: Decimal | None = None
    quote_asset: str | None = None
    quote_quantity: Decimal | None = None
    price_asset: str | None = None
    price_eur: Decimal | None = None
    price_source: str | None = None
    priced_at: str | None = None
    price_age_days: int | None = None
    tax_line_count: int = 0
    assets: list[str] = Field(default_factory=list)
    taxable_consumed_quantity: Decimal = Decimal("0")
    total_event_acquired_quantity: Decimal | None = None
    taxable_event_fraction: Decimal | None = None
    event_total_cost_eur: Decimal | None = None
    actual_cost_eur: Decimal = Decimal("0")
    expected_cost_eur: Decimal | None = None
    event_delta_eur: Decimal | None = None
    event_delta_pct: Decimal | None = None
    status: Literal["event_level_ok", "event_level_review", "missing_price_evidence"]
    explanation: str
    recommended_action: str


class TaxYearGainEvidenceAcquisitionEventDeltaReview(BaseModel):
    year: int
    generated_at: str
    events_count: int = 0
    event_level_ok_count: int = 0
    event_level_review_count: int = 0
    missing_price_count: int = 0
    tax_line_count: int = 0
    actual_cost_eur: Decimal = Decimal("0")
    expected_cost_eur: Decimal = Decimal("0")
    event_delta_eur: Decimal = Decimal("0")
    lines: list[TaxYearGainEvidenceAcquisitionEventDeltaLine] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    methodology: str


class TaxYearGainEvidenceReview(BaseModel):
    year: int
    generated_at: str
    taxable_gain_loss_eur: Decimal = Decimal("0")
    reviewed_gain_loss_eur: Decimal = Decimal("0")
    reviewed_lines_count: int = 0
    high_risk_lines_count: int = 0
    review_lines_count: int = 0
    ok_lines_count: int = 0
    price_delta_lines_count: int = 0
    event_level_reconciled_lines_count: int = 0
    acquisition_event_level_reconciled_lines_count: int = 0
    material_price_delta_eur: Decimal = Decimal("0")
    open_price_delta_eur: Decimal = Decimal("0")
    delta_groups: list[TaxYearGainEvidenceDeltaGroup] = Field(default_factory=list)
    lines: list[TaxYearGainEvidenceLine] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    ascii_table: str
    methodology: str


class TaxLossRealizationLot(BaseModel):
    lot_id: str
    asset: str
    acquired_at: str
    tax_free_at: str
    last_tax_relevant_disposal_date: str
    days_until_tax_free: int
    bucket: str
    status: Literal["tax_relevant_loss_if_sold_now", "loss_window_expired", "not_a_loss"]
    quantity_remaining: Decimal = Decimal("0")
    cost_basis_eur_remaining: Decimal = Decimal("0")
    current_value_eur: Decimal = Decimal("0")
    unrealized_gain_loss_eur: Decimal = Decimal("0")
    current_price_eur: Decimal = Decimal("0")
    price_source: str
    priced_at: str
    source_event_id: str
    source: str | None = None
    account: str | None = None
    evidence_note: str
    action_note: str


class TaxLossRealizationPlanner(BaseModel):
    generated_at: str
    as_of: str
    min_loss_eur: Decimal = Decimal("0")
    min_value_eur: Decimal = Decimal("0")
    tax_relevant_loss_if_sold_now_eur: Decimal = Decimal("0")
    expired_loss_not_tax_relevant_eur: Decimal = Decimal("0")
    unrealized_gain_eur: Decimal = Decimal("0")
    tax_relevant_lots_count: int = 0
    expired_loss_lots_count: int = 0
    rows: list[TaxLossRealizationLot] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    ascii_table: str
    methodology: str


class TaxYearDriverLine(BaseModel):
    tax_line_id: str
    asset: str
    acquired_at: str
    disposed_at: str
    holding_days: int
    quantity: Decimal
    acquisition_cost_eur: Decimal
    disposal_proceeds_eur: Decimal
    gain_loss_eur: Decimal
    taxable: bool
    source_event_id: str
    lot_id: str


class TaxYearDriverReport(BaseModel):
    year: int
    generated_at: str
    taxable_gain_loss_eur: Decimal = Decimal("0")
    tax_free_gain_loss_eur: Decimal = Decimal("0")
    top_taxable_assets: list[TaxYearAssetBreakdown] = Field(default_factory=list)
    top_tax_free_assets: list[TaxYearAssetBreakdown] = Field(default_factory=list)
    top_taxable_lines: list[TaxYearDriverLine] = Field(default_factory=list)
    top_tax_free_lines: list[TaxYearDriverLine] = Field(default_factory=list)
    methodology: str


class TaxYearAssetFifoEvent(BaseModel):
    event_id: str | None = None
    source: str | None = None
    source_ref: str | None = None
    event_time: str | None = None
    event_type: str | None = None
    asset: str | None = None
    quantity: Decimal | None = None
    quote_asset: str | None = None
    quote_quantity: Decimal | None = None
    tx_id: str | None = None
    wallet: str | None = None
    account: str | None = None
    raw_object_id: str | None = None


class TaxYearAssetFifoRawEvidence(BaseModel):
    raw_object_id: str | None = None
    batch_id: str | None = None
    source: str | None = None
    filename: str | None = None
    row_number: int | None = None
    payload_json: str | None = None


class TaxYearAssetFifoLine(BaseModel):
    tax_line_id: str
    asset: str
    quantity: Decimal
    acquired_at: str
    disposed_at: str
    holding_days: int
    taxable: bool
    acquisition_cost_eur: Decimal
    disposal_proceeds_eur: Decimal
    gain_loss_eur: Decimal
    source_event_id: str
    lot_id: str
    acquisition_event: TaxYearAssetFifoEvent | None = None
    disposal_event: TaxYearAssetFifoEvent | None = None
    acquisition_raw: TaxYearAssetFifoRawEvidence | None = None
    disposal_raw: TaxYearAssetFifoRawEvidence | None = None


class TaxYearAssetFifoDrilldown(BaseModel):
    year: int
    asset: str
    generated_at: str
    lines_count: int = 0
    taxable_lines_count: int = 0
    tax_free_lines_count: int = 0
    acquisition_cost_eur: Decimal = Decimal("0")
    disposal_proceeds_eur: Decimal = Decimal("0")
    gain_loss_eur: Decimal = Decimal("0")
    taxable_gain_loss_eur: Decimal = Decimal("0")
    tax_free_gain_loss_eur: Decimal = Decimal("0")
    quote_asset_occurrences: dict[str, int] = Field(default_factory=dict)
    lines: list[TaxYearAssetFifoLine] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    methodology: str


class TaxYearAssetFifoPlausibilityRow(BaseModel):
    year: int
    asset: str
    risk_level: Literal["ok", "review", "high"]
    direct_tax_lines_count: int = 0
    direct_gain_loss_eur: Decimal = Decimal("0")
    direct_disposal_proceeds_eur: Decimal = Decimal("0")
    linked_tax_lines_count: int = 0
    linked_gain_loss_eur: Decimal = Decimal("0")
    linked_disposal_proceeds_eur: Decimal = Decimal("0")
    total_related_gain_loss_eur: Decimal = Decimal("0")
    hidden_quote_gain_loss_eur: Decimal = Decimal("0")
    quote_assets: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    drilldown_endpoint: str


class TaxYearAssetFifoPlausibilityReport(BaseModel):
    year: int
    generated_at: str
    assets_count: int = 0
    high_risk_assets_count: int = 0
    review_assets_count: int = 0
    ok_assets_count: int = 0
    min_abs_gain_eur: Decimal = Decimal("0")
    rows: list[TaxYearAssetFifoPlausibilityRow] = Field(default_factory=list)
    methodology: str


class TaxYearAssetFifoCorrectionReviewRow(BaseModel):
    year: int
    asset: str
    risk_level: Literal["ok", "review", "high"]
    recommended_action: Literal[
        "no_action",
        "keep_tax_sum_review_presentation",
        "verify_quote_leg_attribution",
        "verify_normalizer_or_missing_asset_side",
    ]
    tax_sum_impact: Literal[
        "none_expected",
        "already_in_existing_tax_lines",
        "possible_recalculation_after_review",
    ]
    direct_gain_loss_eur: Decimal = Decimal("0")
    linked_gain_loss_eur: Decimal = Decimal("0")
    total_related_gain_loss_eur: Decimal = Decimal("0")
    direct_tax_lines_count: int = 0
    linked_tax_lines_count: int = 0
    related_raw_evidence_count: int = 0
    related_missing_raw_evidence_count: int = 0
    conclusion: str
    next_step: str
    reasons: list[str] = Field(default_factory=list)
    drilldown_endpoint: str


class TaxYearAssetFifoCorrectionReviewReport(BaseModel):
    year: int
    generated_at: str
    rows_count: int = 0
    possible_recalculation_assets_count: int = 0
    attribution_review_assets_count: int = 0
    no_action_assets_count: int = 0
    rows: list[TaxYearAssetFifoCorrectionReviewRow] = Field(default_factory=list)
    methodology: str


class TaxYearTurnoverAssetBreakdown(BaseModel):
    asset: str
    tax_line_count: int = 0
    gross_disposal_proceeds_eur: Decimal = Decimal("0")
    acquisition_cost_eur: Decimal = Decimal("0")
    gain_loss_eur: Decimal = Decimal("0")
    taxable_gain_loss_eur: Decimal = Decimal("0")
    tax_free_gain_loss_eur: Decimal = Decimal("0")
    stablecoin_like: bool = False


class TaxYearTurnoverSourceBreakdown(BaseModel):
    source: str
    event_type: str
    asset: str
    quote_asset: str | None = None
    tax_line_count: int = 0
    gross_disposal_proceeds_eur: Decimal = Decimal("0")
    acquisition_cost_eur: Decimal = Decimal("0")
    gain_loss_eur: Decimal = Decimal("0")


class TaxYearTurnoverAudit(BaseModel):
    year: int
    generated_at: str
    gross_disposal_proceeds_eur: Decimal = Decimal("0")
    taxable_gain_loss_eur: Decimal = Decimal("0")
    tax_free_gain_loss_eur: Decimal = Decimal("0")
    combined_gain_loss_eur: Decimal = Decimal("0")
    taxable_disposal_proceeds_eur: Decimal = Decimal("0")
    tax_free_disposal_proceeds_eur: Decimal = Decimal("0")
    stablecoin_gross_disposal_proceeds_eur: Decimal = Decimal("0")
    stablecoin_gain_loss_eur: Decimal = Decimal("0")
    tax_lines_count: int = 0
    tax_free_lines_count: int = 0
    external_inflows_review_count: int = 0
    external_inflows_unmatched_count: int = 0
    external_inflows_review_unmatched_value_eur: Decimal = Decimal("0")
    plain_language_summary: str
    caveats: list[str] = Field(default_factory=list)
    top_assets_by_proceeds: list[TaxYearTurnoverAssetBreakdown] = Field(default_factory=list)
    top_assets_by_gain: list[TaxYearTurnoverAssetBreakdown] = Field(default_factory=list)
    top_sources_by_proceeds: list[TaxYearTurnoverSourceBreakdown] = Field(default_factory=list)
    top_taxable_lines_by_gain: list[TaxYearDriverLine] = Field(default_factory=list)
    top_lines_by_proceeds: list[TaxYearDriverLine] = Field(default_factory=list)
    methodology: str


class TaxYearTurnoverAuditSummaryRow(BaseModel):
    year: int
    risk_level: Literal["ok", "review", "high"]
    gross_disposal_proceeds_eur: Decimal = Decimal("0")
    taxable_gain_loss_eur: Decimal = Decimal("0")
    tax_free_gain_loss_eur: Decimal = Decimal("0")
    stablecoin_gross_disposal_proceeds_eur: Decimal = Decimal("0")
    stablecoin_gain_loss_eur: Decimal = Decimal("0")
    stablecoin_gain_ratio_pct: Decimal = Decimal("0")
    external_inflows_review_unmatched_value_eur: Decimal = Decimal("0")
    external_inflows_review_count: int = 0
    external_inflows_unmatched_count: int = 0
    caveats_count: int = 0
    reasons: list[str] = Field(default_factory=list)
    audit_endpoint: str


class TaxYearsTurnoverAuditSummary(BaseModel):
    generated_at: str
    years: list[TaxYearTurnoverAuditSummaryRow] = Field(default_factory=list)
    high_risk_years_count: int = 0
    review_years_count: int = 0
    ok_years_count: int = 0
    methodology: str


class TaxSolanaProgramIncomeAssetSummary(BaseModel):
    year: int
    asset: str
    events_count: int = 0
    quantity: Decimal = Decimal("0")
    value_eur: Decimal = Decimal("0")


class TaxSolanaProgramIncomeYearSummary(BaseModel):
    year: int
    events_count: int = 0
    value_eur: Decimal = Decimal("0")
    assets_count: int = 0
    top_assets: list[TaxSolanaProgramIncomeAssetSummary] = Field(default_factory=list)


class TaxSolanaProgramIncomeRow(BaseModel):
    event_id: str
    event_time: str
    source: str
    account: str | None = None
    asset: str
    quantity: Decimal
    value_eur: Decimal | None = None
    tx_id: str | None = None
    tx_total_count: int = 0
    tx_positive_count: int = 0
    tx_negative_count: int = 0
    tx_zero_count: int = 0
    tx_assets: str = ""
    classification: str = "solana_program_or_swap_income_review"
    review_reason: str


class TaxSolanaProgramIncomeReview(BaseModel):
    generated_at: str
    year: int | None = None
    events_count: int = 0
    total_value_eur: Decimal = Decimal("0")
    years: list[TaxSolanaProgramIncomeYearSummary] = Field(default_factory=list)
    assets: list[TaxSolanaProgramIncomeAssetSummary] = Field(default_factory=list)
    rows: list[TaxSolanaProgramIncomeRow] = Field(default_factory=list)
    methodology: str


class TaxStablecoinFifoAssetSummary(BaseModel):
    year: int
    asset: str
    tax_line_count: int = 0
    disposal_proceeds_eur: Decimal = Decimal("0")
    acquisition_cost_eur: Decimal = Decimal("0")
    gain_loss_eur: Decimal = Decimal("0")
    acquisition_raw_evidence_count: int = 0
    acquisition_missing_raw_evidence_count: int = 0
    taxable_gain_loss_eur: Decimal = Decimal("0")
    tax_free_gain_loss_eur: Decimal = Decimal("0")


class TaxStablecoinFifoSourceSummary(BaseModel):
    year: int
    asset: str
    disposal_source: str
    disposal_event_type: str
    disposal_quote_asset: str | None = None
    acquisition_source: str | None = None
    acquisition_event_type: str | None = None
    tax_line_count: int = 0
    disposal_proceeds_eur: Decimal = Decimal("0")
    acquisition_cost_eur: Decimal = Decimal("0")
    gain_loss_eur: Decimal = Decimal("0")
    acquisition_raw_evidence_count: int = 0
    acquisition_missing_raw_evidence_count: int = 0


class TaxStablecoinFifoLine(BaseModel):
    tax_line_id: str
    year: int
    asset: str
    quantity: Decimal
    acquired_at: str
    disposed_at: str
    holding_days: int
    taxable: bool
    acquisition_cost_eur: Decimal
    disposal_proceeds_eur: Decimal
    gain_loss_eur: Decimal
    disposal_event_id: str
    disposal_source: str | None = None
    disposal_event_type: str | None = None
    disposal_quote_asset: str | None = None
    disposal_quote_quantity: Decimal | None = None
    disposal_tx_id: str | None = None
    disposal_account: str | None = None
    disposal_raw_object_id: str | None = None
    disposal_batch_id: str | None = None
    disposal_batch_filename: str | None = None
    disposal_row_number: int | None = None
    lot_id: str
    acquisition_event_id: str | None = None
    acquisition_source: str | None = None
    acquisition_event_type: str | None = None
    acquisition_quote_asset: str | None = None
    acquisition_quote_quantity: Decimal | None = None
    acquisition_tx_id: str | None = None
    acquisition_account: str | None = None
    acquisition_raw_object_id: str | None = None
    acquisition_batch_id: str | None = None
    acquisition_batch_filename: str | None = None
    acquisition_row_number: int | None = None
    acquisition_evidence_status: str = "missing_raw_evidence"
    acquisition_classification: str
    review_reason: str


class TaxStablecoinFifoReview(BaseModel):
    generated_at: str
    year: int | None = None
    tax_line_count: int = 0
    disposal_proceeds_eur: Decimal = Decimal("0")
    acquisition_cost_eur: Decimal = Decimal("0")
    gain_loss_eur: Decimal = Decimal("0")
    taxable_gain_loss_eur: Decimal = Decimal("0")
    tax_free_gain_loss_eur: Decimal = Decimal("0")
    assets: list[TaxStablecoinFifoAssetSummary] = Field(default_factory=list)
    sources: list[TaxStablecoinFifoSourceSummary] = Field(default_factory=list)
    rows: list[TaxStablecoinFifoLine] = Field(default_factory=list)
    methodology: str


class TaxStablecoinQuoteLegSummary(BaseModel):
    year: int
    source: str
    stable_asset: str
    stable_role: str
    events_count: int = 0
    expected_tax_line_events_count: int = 0
    missing_expected_tax_line_events_count: int = 0
    stable_tax_lines_count: int = 0
    stable_gain_loss_eur: Decimal = Decimal("0")
    stable_disposal_proceeds_eur: Decimal = Decimal("0")


class TaxStablecoinQuoteLegRow(BaseModel):
    event_id: str
    year: int
    event_time: str
    source: str
    account: str | None = None
    event_type: str
    asset: str
    quantity: Decimal
    quote_asset: str | None = None
    quote_quantity: Decimal | None = None
    tx_id: str | None = None
    stable_asset: str
    stable_role: str
    expected_tax_effect: str
    expected_tax_line: bool = False
    stable_tax_lines_count: int = 0
    stable_disposal_proceeds_eur: Decimal = Decimal("0")
    stable_gain_loss_eur: Decimal = Decimal("0")
    raw_object_id: str | None = None
    batch_id: str | None = None
    batch_filename: str | None = None
    row_number: int | None = None
    review_reason: str


class TaxStablecoinQuoteLegReview(BaseModel):
    generated_at: str
    year: int | None = None
    events_count: int = 0
    expected_tax_line_events_count: int = 0
    missing_expected_tax_line_events_count: int = 0
    same_stable_pair_events_count: int = 0
    stable_to_stable_events_count: int = 0
    stable_tax_lines_count: int = 0
    stable_disposal_proceeds_eur: Decimal = Decimal("0")
    stable_gain_loss_eur: Decimal = Decimal("0")
    summaries: list[TaxStablecoinQuoteLegSummary] = Field(default_factory=list)
    rows: list[TaxStablecoinQuoteLegRow] = Field(default_factory=list)
    methodology: str


class TaxSolanaStablecoinSwapAssetSummary(BaseModel):
    year: int
    asset: str
    quote_asset: str | None = None
    events_count: int = 0
    stable_tax_lines_count: int = 0
    stable_gain_loss_eur: Decimal = Decimal("0")
    stable_disposal_proceeds_eur: Decimal = Decimal("0")
    raw_evidence_count: int = 0


class TaxSolanaStablecoinSwapContextRow(BaseModel):
    event_id: str
    year: int
    event_time: str
    account: str | None = None
    asset: str
    quantity: Decimal
    quote_asset: str | None = None
    quote_quantity: Decimal | None = None
    tx_id: str | None = None
    stable_role: str
    expected_tax_effect: str
    stable_tax_lines_count: int = 0
    stable_disposal_proceeds_eur: Decimal = Decimal("0")
    stable_gain_loss_eur: Decimal = Decimal("0")
    tx_total_count: int = 0
    tx_positive_count: int = 0
    tx_negative_count: int = 0
    tx_zero_count: int = 0
    tx_assets: str = ""
    tx_event_types: str = ""
    raw_evidence_count: int = 0
    raw_filenames: list[str] = Field(default_factory=list)
    jupiter_asset_status: str = "unknown"
    jupiter_quote_status: str = "unknown"
    classification: str
    confidence: str
    review_reason: str
    recommended_action: str


class TaxSolanaStablecoinSwapContextReview(BaseModel):
    generated_at: str
    year: int | None = None
    events_count: int = 0
    material_events_count: int = 0
    stable_to_stable_events_count: int = 0
    missing_raw_evidence_count: int = 0
    verified_or_known_token_events_count: int = 0
    stable_tax_lines_count: int = 0
    stable_disposal_proceeds_eur: Decimal = Decimal("0")
    stable_gain_loss_eur: Decimal = Decimal("0")
    assets: list[TaxSolanaStablecoinSwapAssetSummary] = Field(default_factory=list)
    rows: list[TaxSolanaStablecoinSwapContextRow] = Field(default_factory=list)
    methodology: str


class TaxSolanaStablecoinFxAssetSummary(BaseModel):
    year: int
    stable_asset: str
    price_source: str | None = None
    events_count: int = 0
    material_events_count: int = 0
    stable_quantity: Decimal = Decimal("0")
    stable_disposal_proceeds_eur: Decimal = Decimal("0")
    stable_gain_loss_eur: Decimal = Decimal("0")
    max_price_age_days: int = 0
    max_abs_price_delta_pct: Decimal = Decimal("0")


class TaxSolanaStablecoinFxRow(BaseModel):
    event_id: str
    year: int
    event_time: str
    asset: str
    quantity: Decimal
    stable_asset: str
    stable_quantity: Decimal
    tx_id: str | None = None
    stable_tax_lines_count: int = 0
    stable_disposal_proceeds_eur: Decimal = Decimal("0")
    stable_gain_loss_eur: Decimal = Decimal("0")
    implied_stable_price_eur: Decimal | None = None
    selected_price_eur: Decimal | None = None
    selected_price_source: str | None = None
    selected_priced_at: str | None = None
    price_age_days: int | None = None
    price_delta_pct: Decimal | None = None
    fx_basis_status: str
    review_reason: str
    recommended_action: str


class TaxSolanaStablecoinFxReview(BaseModel):
    generated_at: str
    year: int | None = None
    events_count: int = 0
    material_events_count: int = 0
    missing_price_count: int = 0
    stale_price_count: int = 0
    derived_price_count: int = 0
    fx_backed_price_count: int = 0
    market_price_count: int = 0
    stable_disposal_proceeds_eur: Decimal = Decimal("0")
    stable_gain_loss_eur: Decimal = Decimal("0")
    assets: list[TaxSolanaStablecoinFxAssetSummary] = Field(default_factory=list)
    rows: list[TaxSolanaStablecoinFxRow] = Field(default_factory=list)
    methodology: str


class TaxYearEvidenceItem(BaseModel):
    evidence_id: str
    category: Literal["eintragen", "beleg", "pruefen", "paket"]
    label: str
    endpoint: str
    file_format: Literal["csv", "json", "zip"]
    record_count: int = 0
    amount_eur: Decimal | None = None
    status: Literal["available", "empty", "review", "blocked"] = "available"
    required: bool = True
    note: str


class TaxYearEvidenceReport(BaseModel):
    year: int
    generated_at: str
    export_ready: bool
    items: list[TaxYearEvidenceItem] = Field(default_factory=list)
    methodology: str


class TaxYearBmfClosureAppendixItem(BaseModel):
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
    recommended_tax_treatment: str
    filing_disclosure: str
    manual_evidence_required: bool = True
    conservative_treatment_available: bool = False
    evidence_refs: list[str] = Field(default_factory=list)
    recommended_action: str


class TaxYearBmfClosureAppendix(BaseModel):
    year: int
    generated_at: str
    status: Literal["ready", "review", "blocked"]
    items_count: int = 0
    conservative_items_count: int = 0
    manual_evidence_required_count: int = 0
    tax_neutral_candidates_count: int = 0
    can_file_with_conservative_appendix: bool = False
    items: list[TaxYearBmfClosureAppendixItem] = Field(default_factory=list)
    methodology: str


class TaxExternalInflowMatch(BaseModel):
    inflow_event_id: str
    event_time: str
    source: str
    account: str | None = None
    asset: str
    quantity: Decimal
    value_eur: Decimal | None = None
    tx_id: str | None = None
    status: str
    best_match_score: int = 0
    matched_event_id: str | None = None
    matched_time: str | None = None
    matched_source: str | None = None
    matched_account: str | None = None
    matched_quantity: Decimal | None = None
    matched_tx_id: str | None = None
    amount_delta: Decimal | None = None
    time_delta_seconds: int | None = None
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TaxExternalInflowReport(BaseModel):
    year: int
    generated_at: str
    inflows_count: int = 0
    matched_count: int = 0
    review_count: int = 0
    unmatched_count: int = 0
    total_value_eur: Decimal = Decimal("0")
    matched_value_eur: Decimal = Decimal("0")
    review_value_eur: Decimal = Decimal("0")
    unmatched_value_eur: Decimal = Decimal("0")
    assets: list[str] = Field(default_factory=list)
    rows: list[TaxExternalInflowMatch] = Field(default_factory=list)
    methodology: str
