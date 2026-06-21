from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from steuerreport_v2.contracts.valuation import MissingPriceCoverageItem


class ReviewDecisionAuditItem(BaseModel):
    decision_id: str
    decision_type: str
    scope: str
    title: str
    rationale: str
    evidence_ref: str | None = None
    actor: str
    source: str | None = None
    affected_ids: list[str]
    payload: dict[str, object]
    created_at: datetime
    updated_at: datetime | None = None


class HntProvenanceAuditSummary(BaseModel):
    asset: str = "HNT"
    current_portfolio_events: int = 0
    transfer_counterparty_events: int = 0
    fifo_relevant_events: int = 0
    open_lots: int = 0
    disposals: int = 0
    current_portfolio_accounts: list[str] = Field(default_factory=list)
    transfer_counterparty_accounts: list[str] = Field(default_factory=list)
    methodology: str


class TokenRiskDocumentationAuditItem(BaseModel):
    decision_id: str
    scope: str
    asset: str | None = None
    token_symbol: str | None = None
    token_name: str | None = None
    token_mint: str | None = None
    token_risk_status: str | None = None
    quantity: str | None = None
    value_eur: str | None = None
    accounts: list[str] = Field(default_factory=list)
    evidence_ref: str | None = None
    import_effect: str | None = None
    ledger_effect: str | None = None
    fifo_effect: str | None = None
    tax_line_effect: str | None = None
    created_at: datetime


class TokenRiskDocumentationAuditSummary(BaseModel):
    documented_count: int = 0
    total_value_eur: str = "0"
    items: list[TokenRiskDocumentationAuditItem] = Field(default_factory=list)
    methodology: str = (
        "Token-Risiko-Dokumentation ist ein read-only Review-Nachweis. "
        "Sie dokumentiert Spam/Dust-Einstufungen ohne Import-, Ledger-, FIFO-, "
        "Preis- oder Steuerzeilenwirkung."
    )


class AuditExport(BaseModel):
    generated_at: datetime
    import_batches: int
    raw_objects: int
    canonical_events: int
    balance_entries: int
    flow_entries: int
    export_packages: int
    review_allow_export: bool
    export_ready: bool
    review_issues_open: int
    review_issues_current_open: int = 0
    review_issues_historical_open: int = 0
    review_issues_open_total: int = 0
    review_blocking_issues_open: int = 0
    parity_release_ready: bool = True
    parity_unresolved_groups: int = 0
    parity_blocking_groups: int = 0
    parity_blocking_difference_eur: str = "0"
    parity_accepted_groups: int = 0
    parity_groups_total: int = 0
    review_decisions_count: int = 0
    review_decisions: list[ReviewDecisionAuditItem] = Field(default_factory=list)
    price_gaps_count: int = 0
    price_gap_assets: list[str] = Field(default_factory=list)
    price_gaps: list[MissingPriceCoverageItem] = Field(default_factory=list)
    hnt_provenance: HntProvenanceAuditSummary | None = None
    token_risk_documentation: TokenRiskDocumentationAuditSummary = Field(
        default_factory=TokenRiskDocumentationAuditSummary
    )
    transfer_context_note: str | None = None


class ElsterPrepExport(BaseModel):
    generated_at: datetime
    direct_eric_submission: bool
    tax_lines_count: int
    export_ready: bool
    parity_release_ready: bool = True
    parity_blocking_groups: int = 0
    token_risk_documentation_count: int = 0
    notes: list[str]
