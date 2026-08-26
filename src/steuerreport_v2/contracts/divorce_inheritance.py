from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class DivorceInheritanceCreditEvidence(BaseModel):
    booking_date: date
    amount_eur: Decimal
    evidence_status: Literal["bank_primary_evidence", "review"]
    evidence_source: Literal["bank_camt", "supporting_document"] = "bank_camt"
    date_basis: Literal["bank_booking_date", "document_date"] = "bank_booking_date"
    credit_kind: Literal[
        "estate_account_transfer",
        "estate_asset_realization",
        "estate_refund",
    ] = "estate_account_transfer"
    classification_source: Literal["camt_marker", "review_decision"] = "camt_marker"
    transaction_reference_sha256: str
    source_file_sha256: str
    evidence_ref: str
    supporting_evidence_ref: str | None = None
    review_decision_id: str | None = None
    note: str


class InheritanceBankCreditCandidate(BaseModel):
    booking_date: date
    amount_eur: Decimal
    transaction_reference_sha256: str
    source_file_sha256: str
    automatic_inheritance_marker: bool = False
    review_status: Literal["unclassified", "automatic", "reviewed"]
    credit_kind: (
        Literal[
            "estate_account_transfer",
            "estate_asset_realization",
            "estate_refund",
        ]
        | None
    ) = None
    evidence_ref: str
    supporting_evidence_ref: str | None = None
    review_decision_id: str | None = None


class InheritanceBankCreditCandidateReport(BaseModel):
    generated_at: datetime
    separation_date: date
    end_asset_date: date
    bank_manifest_sha256: str | None = None
    candidates_count: int = 0
    classified_count: int = 0
    unclassified_count: int = 0
    candidates: list[InheritanceBankCreditCandidate] = Field(default_factory=list)
    parse_errors: list[str] = Field(default_factory=list)
    methodology: str


class InheritanceBankCreditDecisionRequest(BaseModel):
    transaction_reference_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    credit_kind: Literal[
        "estate_asset_realization",
        "estate_refund",
    ]
    supporting_evidence_ref: str | None = None
    actor: str = "user"
    rationale: str | None = None


class InheritanceBankCreditDecisionResult(BaseModel):
    decision_id: str
    already_recorded: bool = False
    transaction_reference_sha256: str
    credit_kind: Literal["estate_asset_realization", "estate_refund"]
    origin_report: "DivorceInheritanceOriginReport"


class InheritanceDocumentCreditDecisionRequest(BaseModel):
    document_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    document_date: date
    amount_eur: Decimal = Field(gt=0)
    credit_kind: Literal[
        "estate_asset_realization",
        "estate_refund",
    ]
    actor: str = "user"
    rationale: str | None = None


class InheritanceDocumentCreditDecisionResult(BaseModel):
    decision_id: str
    already_recorded: bool = False
    document_sha256: str
    transaction_reference_sha256: str
    credit_kind: Literal["estate_asset_realization", "estate_refund"]
    amount_eur: Decimal
    origin_report: "DivorceInheritanceOriginReport"


class DivorceInheritanceInvestmentFlow(BaseModel):
    flow_id: str
    provider: Literal["binance", "moonpay", "coinbase", "trade_republic"]
    booking_date: date
    amount_eur: Decimal
    evidence_source: Literal["bank_camt", "platform_ledger"]
    transaction_reference_sha256: str
    capital_origin: Literal["claimed_inheritance", "inheritance"]
    capital_origin_evidence_status: Literal["user_declared", "documented"]
    portfolio_coverage_status: Literal["tracked", "not_connected", "platform_only"]
    end_asset_valuation_status: Literal[
        "covered_by_crypto_ledger",
        "missing_source_documents",
        "not_applicable",
    ]
    note: str


class DivorceInheritanceProviderSummary(BaseModel):
    provider: Literal["binance", "moonpay", "coinbase", "trade_republic"]
    label: str
    bank_transactions_count: int = 0
    bank_outflow_eur: Decimal = Decimal("0")
    platform_only_transactions_count: int = 0
    platform_only_outflow_eur: Decimal = Decimal("0")
    identified_investment_eur: Decimal = Decimal("0")
    capital_origin: Literal["claimed_inheritance", "inheritance"]
    capital_origin_evidence_status: Literal["user_declared", "documented"]
    portfolio_coverage_status: Literal["tracked", "not_connected", "partial"]
    end_asset_valuation_status: Literal["covered", "missing", "partial"]
    end_asset_value_eur: Decimal | None = None
    end_asset_evidence_ref: str | None = None
    evidence_ref: str
    finding: str


class TradeRepublicDocumentEvidence(BaseModel):
    document_sha256: str
    container_sha256: str | None = None
    source_kind: Literal["pdf", "csv", "zip_member", "zip_archive"]
    media_type: str
    document_type: Literal[
        "portfolio_statement",
        "account_statement",
        "tax_statement",
        "transaction_statement",
        "transaction_export",
        "archive",
        "unknown",
    ]
    extraction_status: Literal[
        "parsed",
        "text_unavailable",
        "parse_error",
        "unsupported",
    ]
    statement_date: date | None = None
    period_from: date | None = None
    period_to: date | None = None
    end_asset_date_match_source: Literal["none", "filename", "content"] = "none"
    cash_value_eur: Decimal | None = None
    securities_value_eur: Decimal | None = None
    total_value_eur: Decimal | None = None
    valuation_status: Literal[
        "missing",
        "candidate",
        "exact_date_candidate",
        "ambiguous",
        "not_applicable",
    ] = "missing"
    evidence_ref: str
    findings: list[str] = Field(default_factory=list)


class TradeRepublicConnectorStatus(BaseModel):
    official_psd2_api_available: bool = True
    direct_retail_api_available: bool = False
    access_model: str = "licensed_tpp_with_eidas_qseal"
    confirmed_api_scope: str = "cash_accounts_balances_booked_transactions"
    securities_depot_api_scope_confirmed: bool = False
    selected_ingestion_mode: Literal["official_document_import"] = (
        "official_document_import"
    )
    official_api_guide_url: str
    official_statement_help_url: str
    document_root: str
    document_files_count: int = 0
    document_manifest_sha256: str | None = None
    document_parse_status: Literal["missing", "parsed", "partial", "failed"] = "missing"
    parsed_documents_count: int = 0
    parse_error_count: int = 0
    exact_date_documents_count: int = 0
    valuation_candidates_count: int = 0
    end_asset_statement_status: Literal[
        "missing",
        "candidate_present",
        "exact_date_candidate",
        "ambiguous",
        "reviewed",
    ] = "missing"
    valuation_review_status: Literal[
        "missing",
        "ready",
        "ambiguous",
        "reviewed",
    ] = "missing"
    valuation_review_ready: bool = False
    candidate_end_asset_value_eur: Decimal | None = None
    candidate_cash_value_eur: Decimal | None = None
    candidate_securities_value_eur: Decimal | None = None
    candidate_document_sha256: str | None = None
    candidate_evidence_ref: str | None = None
    accepted_end_asset_value_eur: Decimal | None = None
    accepted_evidence_ref: str | None = None
    documents: list[TradeRepublicDocumentEvidence] = Field(default_factory=list)
    required_documents: list[str] = Field(default_factory=list)
    note: str


class TradeRepublicDocumentUploadResult(BaseModel):
    document_sha256: str
    size_bytes: int
    already_present: bool = False
    connector: TradeRepublicConnectorStatus


class InheritanceDocumentEvidence(BaseModel):
    document_sha256: str
    media_type: Literal["application/pdf", "image/jpeg", "image/png"]
    size_bytes: int
    source_kind: Literal["configured_path", "managed_upload"]
    review_status: Literal["candidate", "reviewed"]
    evidence_ref: str


class InheritanceDocumentConnectorStatus(BaseModel):
    document_root: str
    document_files_count: int = 0
    document_manifest_sha256: str | None = None
    status: Literal["missing", "candidate_present", "reviewed"] = "missing"
    review_ready: bool = False
    accepted_document_sha256: str | None = None
    accepted_evidence_ref: str | None = None
    documents: list[InheritanceDocumentEvidence] = Field(default_factory=list)
    note: str


class InheritanceDocumentUploadResult(BaseModel):
    document_sha256: str
    size_bytes: int
    already_present: bool = False
    connector: InheritanceDocumentConnectorStatus


class CoinbaseValuationAssetEvidence(BaseModel):
    asset: str
    quantity: Decimal
    value_eur: Decimal | None = None
    price_source: str | None = None
    priced_at: datetime | None = None


class CoinbaseConnectorStatus(BaseModel):
    official_accounts_api_url: str
    official_transactions_api_url: str
    official_statements_help_url: str
    credential_status: Literal["configured", "missing"]
    latest_live_snapshot_at: datetime | None = None
    latest_live_assets_count: int = 0
    history_batches_count: int = 0
    history_events_count: int = 0
    history_from: datetime | None = None
    history_to: datetime | None = None
    history_manifest_sha256: str | None = None
    history_status: Literal["missing", "imported_pending_review", "reviewed"] = (
        "missing"
    )
    valuation_review_ready: bool = False
    candidate_end_asset_value_eur: Decimal | None = None
    accepted_end_asset_value_eur: Decimal | None = None
    accepted_evidence_ref: str | None = None
    missing_price_assets: list[str] = Field(default_factory=list)
    negative_quantity_assets: list[str] = Field(default_factory=list)
    assets: list[CoinbaseValuationAssetEvidence] = Field(default_factory=list)
    note: str


class SparkasseStatementCryptoDebitEvidence(BaseModel):
    booking_date: date
    provider: Literal["binance", "moonpay", "coinbase", "trade_republic"]
    amount_eur: Decimal
    merchant_time: datetime | None = None
    page_number: int
    document_sha256: str
    evidence_ref: str
    camt_match_status: Literal["exact", "ambiguous", "missing"]
    camt_transaction_reference_sha256: str | None = None
    calculation_effect: Literal["corroboration_only_no_duplicate_flow"] = (
        "corroboration_only_no_duplicate_flow"
    )


class SparkasseStatementDocumentEvidence(BaseModel):
    document_sha256: str
    size_bytes: int
    pages_count: int = 0
    extraction_status: Literal["parsed", "text_unavailable", "parse_error"]
    statement_number: int | None = None
    statement_year: int | None = None
    duplicate_statement: bool = False
    issue_date: date | None = None
    period_from: date | None = None
    period_to: date | None = None
    account_last4: str | None = None
    account_fingerprint_sha256: str | None = None
    ownership_scope: Literal["individual", "joint", "unknown"] = "unknown"
    opening_balance_eur: Decimal | None = None
    closing_balance_eur: Decimal | None = None
    crypto_debits_count: int = 0
    crypto_debits_eur: Decimal = Decimal("0")
    exact_camt_matches_count: int = 0
    evidence_ref: str
    findings: list[str] = Field(default_factory=list)
    crypto_debits: list[SparkasseStatementCryptoDebitEvidence] = Field(
        default_factory=list
    )


class SparkasseStatementConnectorStatus(BaseModel):
    generated_at: datetime
    document_root: str
    document_files_count: int = 0
    document_manifest_sha256: str | None = None
    status: Literal["missing", "parsed", "partial", "failed"] = "missing"
    parsed_documents_count: int = 0
    parse_error_count: int = 0
    period_from: date | None = None
    period_to: date | None = None
    crypto_debits_count: int = 0
    crypto_debits_eur: Decimal = Decimal("0")
    exact_camt_matches_count: int = 0
    ambiguous_camt_matches_count: int = 0
    missing_camt_matches_count: int = 0
    duplicate_investment_flows_prevented_count: int = 0
    calculation_effect: Literal["corroboration_only_no_duplicate_flow"] = (
        "corroboration_only_no_duplicate_flow"
    )
    documents: list[SparkasseStatementDocumentEvidence] = Field(
        default_factory=list
    )
    findings: list[str] = Field(default_factory=list)
    methodology: str


class DivorceInheritanceOriginReport(BaseModel):
    generated_at: datetime
    separation_date: date
    end_asset_date: date
    status: Literal["blocked", "review", "strict_ready"]
    strict_ready: bool = False
    bank_statement_status: Literal["missing", "partial", "complete"]
    bank_statement_from: date | None = None
    bank_statement_to: date | None = None
    bank_files_count: int = 0
    bank_manifest_sha256: str | None = None
    opening_balance_eur: Decimal | None = None
    end_asset_closing_balance_eur: Decimal | None = None
    minimum_closing_balance_after_inheritance_eur: Decimal | None = None
    mixed_account: bool = True
    inheritance_credit: DivorceInheritanceCreditEvidence | None = None
    inheritance_credits: list[DivorceInheritanceCreditEvidence] = Field(
        default_factory=list
    )
    inheritance_credit_count: int = 0
    inheritance_credit_eur: Decimal = Decimal("0")
    user_declaration_status: Literal["missing", "recorded"] = "missing"
    formal_inheritance_document_status: Literal["missing", "documented"] = "missing"
    formal_inheritance_document_sha256: str | None = None
    formal_inheritance_connector: InheritanceDocumentConnectorStatus
    bank_identified_investment_eur: Decimal = Decimal("0")
    platform_only_investment_eur: Decimal = Decimal("0")
    total_identified_investment_eur: Decimal = Decimal("0")
    declared_inheritance_headroom_eur: Decimal | None = None
    crypto_tracked_investment_eur: Decimal = Decimal("0")
    external_asset_investment_eur: Decimal = Decimal("0")
    external_asset_end_value_eur: Decimal | None = None
    external_asset_gain_loss_eur: Decimal | None = None
    provider_summaries: list[DivorceInheritanceProviderSummary] = Field(
        default_factory=list
    )
    investment_flows: list[DivorceInheritanceInvestmentFlow] = Field(
        default_factory=list
    )
    sparkasse_statement_connector: SparkasseStatementConnectorStatus
    trade_republic_connector: TradeRepublicConnectorStatus
    coinbase_connector: CoinbaseConnectorStatus
    findings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    semantic_sha256: str
    methodology: str


class TradeRepublicValuationDecisionRequest(BaseModel):
    end_asset_date: date = date(2026, 7, 24)
    document_sha256: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    actor: str = "user"
    rationale: str | None = None


class TradeRepublicValuationDecisionResult(BaseModel):
    decision_id: str
    already_recorded: bool = False
    provider: Literal["trade_republic"] = "trade_republic"
    valuation_date: date
    value_eur: Decimal
    evidence_ref: str
    source_document_sha256: str
    origin_report: DivorceInheritanceOriginReport


class InheritanceDocumentDecisionRequest(BaseModel):
    document_sha256: str = Field(
        min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$"
    )
    actor: str = "user"
    rationale: str | None = None


class InheritanceDocumentDecisionResult(BaseModel):
    decision_id: str
    already_recorded: bool = False
    document_sha256: str
    evidence_ref: str
    origin_report: DivorceInheritanceOriginReport


class BankCamtUploadResult(BaseModel):
    uploaded_files: int = 0
    already_present_files: int = 0
    document_sha256s: list[str] = Field(default_factory=list)
    origin_report: DivorceInheritanceOriginReport


class CoinbaseValuationDecisionRequest(BaseModel):
    end_asset_date: date = date(2026, 7, 24)
    history_manifest_sha256: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )
    actor: str = "user"
    rationale: str | None = None


class CoinbaseValuationDecisionResult(BaseModel):
    decision_id: str
    already_recorded: bool = False
    provider: Literal["coinbase"] = "coinbase"
    valuation_date: date
    value_eur: Decimal
    evidence_ref: str
    history_manifest_sha256: str
    origin_report: DivorceInheritanceOriginReport
