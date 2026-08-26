from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from steuerreport_v2.contracts.divorce import DivorceEqualizationSummary, DivorceValuationGate


class DivorceValuationRunRequest(BaseModel):
    separation_date: date | None = None
    end_asset_date: date | None = None
    court_evidence_reference: str | None = None
    cutoff_at: datetime | None = None
    valuation_at: datetime | None = None
    materiality_threshold_eur: Decimal = Field(default=Decimal("1"), ge=0)
    material_delta_threshold_eur: Decimal = Field(default=Decimal("0.01"), ge=0)


class DivorceValuationFifoCheckpoint(BaseModel):
    label: Literal["cutoff", "valuation"]
    run_id: str
    as_of: datetime
    reused_existing_run: bool = False
    status: Literal["blocked", "review", "ready_for_method_review"]
    strict_ready: bool = False
    years: list[int] = Field(default_factory=list)
    unmatched_count: int = 0
    unmatched_classification_complete: bool = False
    provider_basis_gap_count: int = 0
    unexplained_unmatched_count: int = 0
    unresolved_inbound_provenance_count: int = 0
    transfer_evidence_review_count: int = 0
    acquisition_cost_evidence_review_count: int = 0
    event_set_mismatch_years: list[int] = Field(default_factory=list)
    valuation_review_years: list[int] = Field(default_factory=list)
    method_gap_classification_complete: bool = False
    provider_basis_event_set_gap_groups_count: int = 0
    provider_basis_quantity_gap_groups_count: int = 0
    unexplained_method_gap_groups_count: int = 0
    bitget_strategy_gap_status: str | None = None
    bitget_strategy_gap_quantity_reconciled: bool = False
    bitget_strategy_gap_groups_count: int = 0
    bitget_strategy_gap_linked_disposals_count: int = 0
    bitget_strategy_gap_unallocated_disposals_count: int = 0
    bitget_strategy_gap_semantic_sha256: str | None = None
    bitget_strategy_gap_report_url: str | None = None
    semantic_sha256: str
    report_url: str
    evidence_urls: list[str] = Field(default_factory=list)


class DivorceValuationEvidenceFile(BaseModel):
    kind: str
    path: str
    media_type: str
    size_bytes: int = 0
    sha256: str
    download_url: str | None = None


class DivorceValuationRunReport(BaseModel):
    run_id: str
    generated_at: datetime
    status: Literal["blocked", "review", "strict_ready"]
    strict_ready: bool = False
    cutoff_at: datetime
    valuation_at: datetime
    materiality_threshold_eur: Decimal
    material_delta_threshold_eur: Decimal
    cutoff_value_eur: Decimal = Decimal("0")
    valuation_value_eur: Decimal = Decimal("0")
    gross_change_eur: Decimal = Decimal("0")
    external_invest_eur: Decimal = Decimal("0")
    adjusted_gain_loss_eur: Decimal = Decimal("0")
    cutoff_price_gate: DivorceValuationGate
    valuation_price_gate: DivorceValuationGate
    fifo_checkpoints: list[DivorceValuationFifoCheckpoint] = Field(default_factory=list)
    source_registry_status: str = "missing"
    source_registry_strict_ready: bool = False
    source_provider_coverage_gap_count: int = 0
    source_user_evidence_gap_count: int = 0
    source_quantity_blocker_count: int = 0
    source_registry_semantic_sha256: str | None = None
    source_registry_report_url: str = "/api/v1/sources/registry/runs/latest"
    source_accounts: list[str] = Field(default_factory=list)
    semantic_sha256: str
    evidence_files: list[DivorceValuationEvidenceFile] = Field(default_factory=list)
    artifact_path: str
    latest_artifact_path: str
    findings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    methodology: str
    summary: DivorceEqualizationSummary
