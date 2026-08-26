from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


BitgetStrategyBasisDecisionStatus = Literal[
    "pending",
    "retain_provider_gap_pending_professional_review",
    "approve_zero_basis_estimate_for_staging",
    "approve_settlement_value_proxy_estimate_for_staging",
    "rejected_requires_rework",
]

BitgetStrategyBasisSelectedMethod = Literal[
    "none",
    "zero_basis_estimate",
    "settlement_value_proxy_estimate",
]


class BitgetStrategyBasisDecisionCheck(BaseModel):
    key: str
    label: str
    passed: bool
    blocking: bool = True
    detail: str


class BitgetStrategyBasisDecisionReport(BaseModel):
    generated_at: datetime
    run_id: str | None = None
    run_as_of: datetime | None = None
    run_input_fingerprint_digest: str | None = None
    current_input_fingerprint_digest: str | None = None
    input_fingerprint_current: bool = False
    gap_semantic_sha256: str | None = None
    reconstruction_semantic_sha256: str | None = None
    status: Literal[
        "missing",
        "blocked",
        "ready_for_professional_decision",
        "decision_recorded",
    ] = "missing"
    decision_ready: bool = False
    decision_status: BitgetStrategyBasisDecisionStatus = "pending"
    selected_method: BitgetStrategyBasisSelectedMethod = "none"
    decision_id: str | None = None
    decision_at: datetime | None = None
    decision_actor: str | None = None
    decision_rationale: str | None = None
    support_package_complete: bool = False
    provider_export_field_gap: bool = False
    quantity_reconciled: bool = False
    price_evidence_complete: bool = False
    holding_period_classification_complete: bool = False
    linked_disposals_count: int = 0
    attributable_disposal_proceeds_total_eur: Decimal = Decimal("0")
    selected_estimated_cost_basis_total_eur: Decimal | None = None
    selected_estimated_gain_loss_total_eur: Decimal | None = None
    estimate_selected_for_staging: bool = False
    strict_ready: bool = False
    staging_only: bool = True
    productive_tax_effect: Literal["none"] = "none"
    checks: list[BitgetStrategyBasisDecisionCheck] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    methodology: str


class BitgetStrategyBasisDecisionRequest(BaseModel):
    decision: Literal[
        "retain_provider_gap_pending_professional_review",
        "approve_zero_basis_estimate_for_staging",
        "approve_settlement_value_proxy_estimate_for_staging",
        "rejected_requires_rework",
    ]
    rationale: str = Field(min_length=30, max_length=3000)
    actor: str = Field(default="user", min_length=2, max_length=120)
    acknowledge_provider_fill_data_missing: Literal[True]
    acknowledge_estimate_not_observed_transaction: Literal[True]
    acknowledge_consistent_application: Literal[True]
    acknowledge_no_automatic_tax_effect: Literal[True]
    acknowledge_professional_review_before_filing: Literal[True]


class BitgetStrategyBasisDecisionResult(BaseModel):
    decision_id: str
    created: bool
    report: BitgetStrategyBasisDecisionReport
