from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TaxMethodologyStatus = Literal["ok", "review", "blocked", "empty"]
TaxMethodologySeverity = Literal["info", "warning", "blocker"]
TaxBmfComplianceStatus = Literal["satisfied", "review", "blocked", "not_applicable"]
TaxBmfImplementationStatus = Literal["implemented", "partial", "missing", "not_applicable"]
TaxTimeBoundaryClassification = Literal[
    "local_calendar_shift_required",
    "source_period_aggregate_preserved",
]


class TaxMethodologyPolicy(BaseModel):
    method_version: str
    fifo_scope: str
    valuation_policy: str
    timezone_policy: str
    rounding_policy: str
    transfer_policy: str
    source_policy: str
    bmf_reference: str


class TaxTimeBoundaryEvent(BaseModel):
    event_id: str
    event_time_utc: datetime
    event_time_europe_berlin: datetime
    utc_year: int
    reporting_year: int
    classification: TaxTimeBoundaryClassification
    source_period_year: int | None = None
    source: str
    event_type: str
    asset: str
    quantity: Decimal
    tx_id: str | None = None
    source_ref: str | None = None
    raw_object_id: str | None = None
    raw_filename: str | None = None
    tax_lines_count: int = 0
    tax_lines_gain_loss_eur: Decimal = Decimal("0")
    income_cost_basis_eur: Decimal = Decimal("0")


class TaxTimePrecisionAudit(BaseModel):
    generated_at: datetime
    policy_version: str
    status: Literal["satisfied", "blocked"]
    reporting_policy_applied: bool = False
    storage_timezone: Literal["UTC"] = "UTC"
    reporting_timezone: Literal["Europe/Berlin"] = "Europe/Berlin"
    rounding_policy: str
    boundary_events_count: int = 0
    source_period_aggregate_events_count: int = 0
    reporting_year_shift_events_count: int = 0
    reporting_year_shift_tax_lines_count: int = 0
    reporting_year_shift_tax_gain_loss_eur: Decimal = Decimal("0")
    reporting_year_shift_income_events_count: int = 0
    reporting_year_shift_income_cost_basis_eur: Decimal = Decimal("0")
    affected_utc_years: list[int] = Field(default_factory=list)
    affected_reporting_years: list[int] = Field(default_factory=list)
    events: list[TaxTimeBoundaryEvent] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    methodology: str


class TaxMethodologyGap(BaseModel):
    code: str
    severity: TaxMethodologySeverity
    message: str
    count: int = 1
    action: str
    evidence_ref: str | None = None
    blocks_bmf_ready: bool = False


class TaxTraceabilityMetric(BaseModel):
    key: str
    label: str
    status: TaxMethodologyStatus
    value: Decimal | int | str
    target: Decimal | int | str
    detail: str


class TaxYearComplianceStatus(BaseModel):
    year: int
    status: TaxMethodologyStatus
    label: str
    bmf_ready: bool = False
    tax_lines_count: int = 0
    income_events_count: int = 0
    derivative_lines_count: int = 0
    unmatched_disposals: int = 0
    missing_price_groups: int = 0
    review_issues_count: int = 0
    external_inflows_review_count: int = 0
    external_inflows_unmatched_count: int = 0
    traceability_score: Decimal = Decimal("0")
    gaps_count: int = 0
    blocking_gaps_count: int = 0
    methodology_endpoint: str
    evidence_package_endpoint: str


class TaxMethodologyReport(BaseModel):
    year: int
    generated_at: str
    status: TaxMethodologyStatus
    label: str
    bmf_ready: bool = False
    policy: TaxMethodologyPolicy
    metrics: list[TaxTraceabilityMetric] = Field(default_factory=list)
    gaps: list[TaxMethodologyGap] = Field(default_factory=list)
    tax_lines_count: int = 0
    income_events_count: int = 0
    derivative_lines_count: int = 0
    sources: list[str] = Field(default_factory=list)
    accounts_count: int = 0
    assets_count: int = 0
    traceability_score: Decimal = Decimal("0")
    methodology: str


class TaxMethodologySummary(BaseModel):
    generated_at: str
    years: list[TaxYearComplianceStatus] = Field(default_factory=list)
    available_years: list[int] = Field(default_factory=list)
    policy: TaxMethodologyPolicy
    ok_years: int = 0
    review_years: int = 0
    blocked_years: int = 0
    empty_years: int = 0
    methodology: str


class TaxBmfComplianceMetric(BaseModel):
    key: str
    label: str
    value: Decimal | int | str | bool
    target: str
    status: TaxBmfComplianceStatus
    detail: str


class TaxBmfComplianceRequirement(BaseModel):
    requirement_id: str
    title: str
    bmf_paragraphs: list[str] = Field(default_factory=list)
    requirement: str
    implementation_status: TaxBmfImplementationStatus
    evidence_status: TaxBmfComplianceStatus
    strict_ready: bool = False
    affected_years: list[int] = Field(default_factory=list)
    metrics: list[TaxBmfComplianceMetric] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    next_action: str


class TaxBmfComplianceMatrix(BaseModel):
    generated_at: str
    matrix_version: str
    bmf_reference: str
    bmf_reference_url: str
    scope_years: list[int] = Field(default_factory=list)
    strict_bmf_ready: bool = False
    strict_ready_years: list[int] = Field(default_factory=list)
    conservative_years: list[int] = Field(default_factory=list)
    review_years: list[int] = Field(default_factory=list)
    blocked_years: list[int] = Field(default_factory=list)
    requirements_count: int = 0
    satisfied_count: int = 0
    review_count: int = 0
    blocked_count: int = 0
    not_applicable_count: int = 0
    requirements: list[TaxBmfComplianceRequirement] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    methodology: str


class TaxBmfActionItem(BaseModel):
    year: int
    category: Literal[
        "wallet_fifo",
        "wallet_fifo_delta",
        "asset_fifo",
        "external_inflow",
        "price",
        "review",
        "traceability",
        "activity",
        "income",
    ]
    severity: TaxMethodologySeverity
    code: str
    title: str
    detail: str
    count: int = 1
    blocks_bmf_ready: bool = False
    evidence_ref: str | None = None
    action: str


class TaxBmfActionPlan(BaseModel):
    generated_at: str
    available_years: list[int] = Field(default_factory=list)
    ready_years: list[int] = Field(default_factory=list)
    review_years: list[int] = Field(default_factory=list)
    blocked_years: list[int] = Field(default_factory=list)
    empty_years: list[int] = Field(default_factory=list)
    blocking_items_count: int = 0
    review_items_count: int = 0
    info_items_count: int = 0
    items: list[TaxBmfActionItem] = Field(default_factory=list)
    methodology: str


class TaxBmfFilingReadinessYear(BaseModel):
    year: int
    filing_status: Literal["bmf_ready", "conservative_appendix", "review_required", "blocked", "empty"]
    status_label: str
    methodology_status: TaxMethodologyStatus
    bmf_ready: bool = False
    can_file_with_conservative_appendix: bool = False
    appendix_status: Literal["ready", "review", "blocked"] | None = None
    appendix_items_count: int = 0
    appendix_manual_evidence_required_count: int = 0
    taxable_private_disposals_eur: Decimal = Decimal("0")
    rewards_mining_staking_income_eur: Decimal = Decimal("0")
    derivative_pnl_eur: Decimal = Decimal("0")
    blocking_gap_codes: list[str] = Field(default_factory=list)
    review_gap_codes: list[str] = Field(default_factory=list)
    next_action: str
    methodology_endpoint: str
    filing_summary_endpoint: str
    bmf_closure_appendix_endpoint: str
    evidence_package_endpoint: str
    display_line: str


class TaxBmfFilingReadinessReport(BaseModel):
    generated_at: str
    input_binding_sha256: str | None = None
    binding_version: str | None = None
    latest_tax_run_id: str | None = None
    years: list[TaxBmfFilingReadinessYear] = Field(default_factory=list)
    available_years: list[int] = Field(default_factory=list)
    ready_years: list[int] = Field(default_factory=list)
    conservative_appendix_years: list[int] = Field(default_factory=list)
    review_years: list[int] = Field(default_factory=list)
    blocked_years: list[int] = Field(default_factory=list)
    empty_years: list[int] = Field(default_factory=list)
    ascii_table: str
    methodology: str


class TaxBmfFilingReadinessSnapshotRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["years_2021_2025"]
    expected_input_binding_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    expected_latest_tax_run_id: str | None


class TaxBmfFilingReadinessSnapshot(BaseModel):
    generated_at: str
    snapshot_exists: bool = False
    artifact_path: str
    report: TaxBmfFilingReadinessReport | None = None
    years_count: int = 0
    available_years: list[int] = Field(default_factory=list)
    ready_years: list[int] = Field(default_factory=list)
    conservative_appendix_years: list[int] = Field(default_factory=list)
    review_years: list[int] = Field(default_factory=list)
    blocked_years: list[int] = Field(default_factory=list)
    empty_years: list[int] = Field(default_factory=list)
    binding_status: Literal["current", "stale", "unbound", "missing"] | None = None
    status: Literal["available", "missing", "invalid"] = "missing"
    note: str


class TaxBmfFilingReadinessSnapshotRefreshResult(BaseModel):
    operation_id: str
    scope: Literal["years_2021_2025"]
    status: Literal["completed", "stale"]
    started_at: datetime
    completed_at: datetime
    binding_status: Literal["current", "stale", "unbound"]
    report: TaxBmfFilingReadinessReport
    final_approval_granted: Literal[False] = False
    tax_data_changed: Literal[False] = False
    external_provider_calls_made: Literal[False] = False


class TaxBmfFinalizationRequirement(BaseModel):
    key: Literal[
        "fifo_traceability",
        "income_rewards_mining",
        "private_disposals",
        "transfers_provenance",
        "prices_fx",
        "declaration_help",
        "evidence_package",
    ]
    label: str
    status: Literal["ok", "review", "blocked", "empty"]
    detail: str
    evidence_ref: str | None = None


class TaxBmfFinalizationYear(BaseModel):
    year: int
    finalization_status: Literal["bmf_ready", "conservative_ready", "review_required", "blocked", "empty"]
    status_label: str
    can_submit: bool = False
    can_submit_conservative: bool = False
    correction_review_recommended: bool = False
    taxable_private_disposals_eur: Decimal = Decimal("0")
    rewards_mining_staking_income_eur: Decimal = Decimal("0")
    derivative_pnl_eur: Decimal = Decimal("0")
    tax_free_private_disposals_eur: Decimal = Decimal("0")
    blocking_count: int = 0
    review_count: int = 0
    evidence_refs: list[str] = Field(default_factory=list)
    requirements: list[TaxBmfFinalizationRequirement] = Field(default_factory=list)
    next_action: str
    filing_summary_endpoint: str
    correction_map_endpoint: str
    evidence_package_endpoint: str
    display_line: str


class TaxBmfFinalizationMatrix(BaseModel):
    generated_at: str
    years: list[TaxBmfFinalizationYear] = Field(default_factory=list)
    available_years: list[int] = Field(default_factory=list)
    ready_years: list[int] = Field(default_factory=list)
    conservative_ready_years: list[int] = Field(default_factory=list)
    review_years: list[int] = Field(default_factory=list)
    blocked_years: list[int] = Field(default_factory=list)
    empty_years: list[int] = Field(default_factory=list)
    total_taxable_private_disposals_eur: Decimal = Decimal("0")
    total_rewards_mining_staking_income_eur: Decimal = Decimal("0")
    total_derivative_pnl_eur: Decimal = Decimal("0")
    ascii_table: str
    methodology: str


class TaxBmfSubmissionGuideYear(BaseModel):
    year: int
    status: Literal["ready", "conservative_ready", "review_required", "blocked", "empty"]
    status_label: str
    can_submit: bool = False
    can_submit_conservative: bool = False
    correction_review_recommended: bool = False
    declaration_bucket: str
    where_to_enter: str
    taxable_private_disposals_eur: Decimal = Decimal("0")
    rewards_mining_staking_income_eur: Decimal = Decimal("0")
    derivative_pnl_eur: Decimal = Decimal("0")
    tax_free_private_disposals_eur: Decimal = Decimal("0")
    enter_count: int = 0
    attach_count: int = 0
    review_count: int = 0
    archive_count: int = 0
    blocking_count: int = 0
    review_requirements_count: int = 0
    technical_review_requirements_count: int = 0
    declaration_compare_required: bool = False
    amendment_reason: str | None = None
    filing_sentence: str
    attachment_sentence: str
    archive_sentence: str
    review_sentence: str
    next_action: str
    filing_summary_endpoint: str
    filing_checklist_csv_endpoint: str
    correction_map_endpoint: str
    correction_map_csv_endpoint: str
    evidence_package_endpoint: str
    display_line: str


class TaxBmfSubmissionGuide(BaseModel):
    generated_at: str
    years: list[TaxBmfSubmissionGuideYear] = Field(default_factory=list)
    available_years: list[int] = Field(default_factory=list)
    ready_years: list[int] = Field(default_factory=list)
    conservative_ready_years: list[int] = Field(default_factory=list)
    review_years: list[int] = Field(default_factory=list)
    blocked_years: list[int] = Field(default_factory=list)
    empty_years: list[int] = Field(default_factory=list)
    amendment_review_years: list[int] = Field(default_factory=list)
    total_taxable_private_disposals_eur: Decimal = Decimal("0")
    total_rewards_mining_staking_income_eur: Decimal = Decimal("0")
    total_derivative_pnl_eur: Decimal = Decimal("0")
    total_tax_free_private_disposals_eur: Decimal = Decimal("0")
    ascii_table: str
    methodology: str


class TaxBmfPriorFilingComparisonYear(BaseModel):
    year: int
    status: Literal["match", "delta_review", "missing_declared_values", "declared_values_untrusted", "empty"]
    status_label: str
    declared_values_configured: bool = False
    declared_values_source: Literal[
        "none", "admin_setting", "confirmed_filing_snapshot"
    ] = "none"
    declared_values_snapshot_id: str | None = None
    declared_values_package_sha256: str | None = None
    submission_timestamp_known: bool = False
    elster_field_verification_required: bool = False
    declared_values_status: Literal["declared_values", "unknown", "probably_wrong", "not_filed"] = "unknown"
    declared_values_note: str | None = None
    v2_taxable_private_disposals_eur: Decimal = Decimal("0")
    declared_taxable_private_disposals_eur: Decimal | None = None
    delta_taxable_private_disposals_eur: Decimal | None = None
    v2_rewards_mining_staking_income_eur: Decimal = Decimal("0")
    declared_rewards_mining_staking_income_eur: Decimal | None = None
    delta_rewards_mining_staking_income_eur: Decimal | None = None
    v2_derivative_pnl_eur: Decimal = Decimal("0")
    declared_derivative_pnl_eur: Decimal | None = None
    delta_derivative_pnl_eur: Decimal | None = None
    v2_tax_free_private_disposals_eur: Decimal = Decimal("0")
    declared_tax_free_private_disposals_eur: Decimal | None = None
    delta_tax_free_private_disposals_eur: Decimal | None = None
    absolute_delta_eur: Decimal = Decimal("0")
    amendment_review_recommended: bool = False
    next_action: str
    setting_key: str
    filing_summary_endpoint: str
    correction_map_endpoint: str
    evidence_package_endpoint: str
    display_line: str


class TaxBmfPriorFilingComparison(BaseModel):
    generated_at: str
    setting_key: str
    setting_exists: bool = False
    years: list[TaxBmfPriorFilingComparisonYear] = Field(default_factory=list)
    available_years: list[int] = Field(default_factory=list)
    match_years: list[int] = Field(default_factory=list)
    delta_review_years: list[int] = Field(default_factory=list)
    missing_declared_years: list[int] = Field(default_factory=list)
    untrusted_declared_years: list[int] = Field(default_factory=list)
    confirmed_snapshot_years: list[int] = Field(default_factory=list)
    empty_years: list[int] = Field(default_factory=list)
    total_delta_taxable_private_disposals_eur: Decimal = Decimal("0")
    total_delta_rewards_mining_staking_income_eur: Decimal = Decimal("0")
    total_delta_derivative_pnl_eur: Decimal = Decimal("0")
    total_absolute_delta_eur: Decimal = Decimal("0")
    example_setting_json: str
    ascii_table: str
    methodology: str


class TaxBmfPriorFilingDeclaredYear(BaseModel):
    year: int
    declared_values_status: Literal["declared_values", "unknown", "probably_wrong", "not_filed"] = "declared_values"
    note: str | None = None
    taxable_private_disposals_eur: Decimal = Decimal("0")
    rewards_mining_staking_income_eur: Decimal = Decimal("0")
    derivative_pnl_eur: Decimal = Decimal("0")
    tax_free_private_disposals_eur: Decimal = Decimal("0")


class TaxBmfPriorFilingDeclaredAmounts(BaseModel):
    setting_key: str
    years: list[TaxBmfPriorFilingDeclaredYear] = Field(default_factory=list)
    example_setting_json: str
    methodology: str


class TaxBmfPriorFilingDeclaredAmountsWrite(BaseModel):
    years: list[TaxBmfPriorFilingDeclaredYear] = Field(default_factory=list)


class TaxBmfPriorFilingDeclaredAmountsWriteResult(BaseModel):
    setting_key: str
    written_years: list[int] = Field(default_factory=list)
    comparison: TaxBmfPriorFilingComparison


class TaxBmfAmendmentWorklistYear(BaseModel):
    year: int
    priority: int = 0
    status: Literal["prepare_correction_review", "compare_declared_values", "archive_only", "blocked"]
    status_label: str
    prior_filing_status: str
    prior_filing_values_source: str = "none"
    prior_filing_snapshot_id: str | None = None
    prior_filing_absolute_delta_eur: Decimal = Decimal("0")
    elster_field_verification_required: bool = False
    v2_taxable_private_disposals_eur: Decimal = Decimal("0")
    v2_rewards_mining_staking_income_eur: Decimal = Decimal("0")
    v2_derivative_pnl_eur: Decimal = Decimal("0")
    v2_tax_free_private_disposals_eur: Decimal = Decimal("0")
    technical_review_requirements_count: int = 0
    amendment_review_recommended: bool = False
    correction_reason: str
    next_action: str
    filing_summary_endpoint: str
    correction_map_endpoint: str
    correction_map_csv_endpoint: str
    evidence_package_endpoint: str
    display_line: str


class TaxBmfAmendmentWorklist(BaseModel):
    generated_at: str
    years: list[TaxBmfAmendmentWorklistYear] = Field(default_factory=list)
    available_years: list[int] = Field(default_factory=list)
    correction_review_years: list[int] = Field(default_factory=list)
    compare_declared_years: list[int] = Field(default_factory=list)
    archive_only_years: list[int] = Field(default_factory=list)
    blocked_years: list[int] = Field(default_factory=list)
    total_v2_taxable_private_disposals_eur: Decimal = Decimal("0")
    total_v2_rewards_mining_staking_income_eur: Decimal = Decimal("0")
    total_v2_derivative_pnl_eur: Decimal = Decimal("0")
    ascii_table: str
    methodology: str


class TaxBmfClosureBacklogItem(BaseModel):
    year: int
    priority: int = 0
    category: Literal[
        "wallet_fifo_provenance",
        "solana_batch",
        "asset_fifo_review",
        "wallet_fifo_delta",
        "exchange_sequencing",
        "documentation",
    ]
    blocker_type: str
    severity: TaxMethodologySeverity
    asset: str | None = None
    source: str | None = None
    pool_id: str | None = None
    events_count: int = 0
    quantity_total: Decimal = Decimal("0")
    exposure_eur: Decimal = Decimal("0")
    closure_status: str | None = None
    required_evidence: str
    next_action: str
    evidence_refs: list[str] = Field(default_factory=list)


class TaxBmfClosureBacklogYear(BaseModel):
    year: int
    status: TaxMethodologyStatus
    bmf_ready: bool = False
    blocker_items_count: int = 0
    review_items_count: int = 0
    total_exposure_eur: Decimal = Decimal("0")
    top_actions: list[str] = Field(default_factory=list)
    items: list[TaxBmfClosureBacklogItem] = Field(default_factory=list)


class TaxBmfClosureBacklogReport(BaseModel):
    generated_at: str
    available_years: list[int] = Field(default_factory=list)
    years: list[TaxBmfClosureBacklogYear] = Field(default_factory=list)
    blocker_items_count: int = 0
    review_items_count: int = 0
    total_exposure_eur: Decimal = Decimal("0")
    next_year_to_close: int | None = None
    methodology: str


class TaxBmfClosureBacklogSnapshot(BaseModel):
    generated_at: str
    snapshot_exists: bool = False
    artifact_path: str
    report: TaxBmfClosureBacklogReport | None = None
    status: Literal["available", "missing", "invalid"] = "missing"
    note: str


class TaxRewardBmfRecheckYear(BaseModel):
    year: int
    status: TaxMethodologyStatus
    bmf_ready: bool = False
    reward_income_eur: Decimal = Decimal("0")
    reward_events_count: int = 0
    income_guide_reward_eur: Decimal = Decimal("0")
    income_guide_events_count: int = 0
    reward_income_candidate_count: int = 0
    exchange_or_wrapper_review_count: int = 0
    solana_external_or_airdrop_review_count: int = 0
    missing_income_value_count: int = 0
    evidence_required: bool = False
    consistency_status: Literal["ok", "review"] = "ok"
    flags: list[str] = Field(default_factory=list)
    income_guide_endpoint: str
    methodology_endpoint: str
    evidence_package_endpoint: str


class TaxRewardBmfRecheckReport(BaseModel):
    generated_at: str
    years: list[TaxRewardBmfRecheckYear] = Field(default_factory=list)
    available_years: list[int] = Field(default_factory=list)
    total_reward_income_eur: Decimal = Decimal("0")
    total_reward_events_count: int = 0
    years_with_rewards_count: int = 0
    review_years_count: int = 0
    methodology: str
