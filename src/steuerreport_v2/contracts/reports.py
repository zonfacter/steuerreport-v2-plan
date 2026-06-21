from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from steuerreport_v2.contracts.exports import ExportPackage

ReportArtifactKind = Literal["pdf", "audit_json", "elster_prep", "csv", "json", "evidence_package"]
ReportArtifactStatus = Literal["ready", "not_created", "blocked", "available", "planned"]
EvidenceManifestGroup = Literal["tax", "review", "hnt", "solana_fifo", "prices_parity", "structure", "other"]
ReportWarningSeverity = Literal["low", "medium", "high"]


class ReportAction(BaseModel):
    action_id: str
    label: str
    kind: ReportArtifactKind
    method: Literal["GET", "POST"]
    path: str
    enabled: bool = True
    blocked_reason: str | None = None
    description: str


class ReportArtifact(BaseModel):
    artifact_id: str
    label: str
    kind: ReportArtifactKind
    status: ReportArtifactStatus
    endpoint: str | None = None
    package_id: str | None = None
    file_index: int | None = None
    page_count: int | None = None
    created_at: datetime | None = None
    note: str | None = None


class EvidenceManifestFile(BaseModel):
    file_id: str
    label: str
    kind: ReportArtifactKind
    endpoint: str
    group: EvidenceManifestGroup = "other"
    group_label: str = "Sonstige Belege"
    required: bool = True
    note: str | None = None


class EvidenceManifest(BaseModel):
    generated_at: datetime
    label: str = "steuerreport-v2-evidence-manifest"
    files: list[EvidenceManifestFile] = Field(default_factory=list)
    methodology: str


class EvidencePackageIndexFile(BaseModel):
    path: str
    file_id: str
    label: str
    group: EvidenceManifestGroup
    group_label: str
    required: bool
    source_endpoint: str
    size_bytes: int | None = None
    sha256: str | None = None


class EvidencePackageIndexGroup(BaseModel):
    group: EvidenceManifestGroup
    folder: str
    files_count: int = 0
    required_count: int = 0


class EvidencePackageIndex(BaseModel):
    generated_at: datetime
    label: str = "steuerreport-v2-evidence-package-index"
    manifest_label: str
    files_count: int = 0
    groups: list[EvidencePackageIndexGroup] = Field(default_factory=list)
    files: list[EvidencePackageIndexFile] = Field(default_factory=list)
    methodology: str


class ReportQualityWarning(BaseModel):
    code: str
    severity: ReportWarningSeverity
    message: str
    count: int = 1
    blocks_export: bool = False
    action_path: str | None = None


class ReportEvidenceHealth(BaseModel):
    status: str
    traces_count: int = 0
    canonical_count: int = 0
    legacy_ref_count: int = 0
    missing_decision_count: int = 0
    action_path: str = "/api/v1/review/evidence-traces"
    detail: str


class ReportYearCard(BaseModel):
    year: int
    label: str
    tax_state: str
    export_blocked: bool
    pdf_status: ReportArtifactStatus
    audit_status: ReportArtifactStatus
    elster_prep_status: ReportArtifactStatus
    csv_status: ReportArtifactStatus
    tax_lines_count: int = 0
    review_issues_count: int = 0
    realized_gain_loss_eur: str = "0"
    rewards_mining_staking_income_eur: str = "0"
    derivative_pnl_eur: str = "0"
    tax_free_private_disposals_eur: str = "0"
    tax_free_lines_count: int = 0
    filing_summary: str = ""
    filing_status: str = "empty"
    filing_status_label: str = "Keine V2-Eingabewerte"
    evidence_status: str = "archive_only"
    evidence_status_label: str = "Archivieren"
    evidence_summary: str = ""
    package_status: str = "available"
    package_status_label: str = "Jahrespaket abrufbar"
    next_action_label: str = ""
    required_evidence_labels: list[str] = Field(default_factory=list)
    filing_endpoint: str
    evidence_endpoint: str
    evidence_package_endpoint: str
    wallet_fifo_endpoint: str
    wallet_fifo_gaps_endpoint: str
    required_evidence_refs: list[str] = Field(default_factory=list)
    required_evidence_count: int = 0
    expected_package_files_count: int = 0
    cex_fifo_anchor_status: str = "none"
    cex_fifo_anchor_status_label: str = "Keine CEX-FIFO-Anker"
    cex_fifo_anchor_decisions_count: int = 0
    cex_fifo_anchor_endpoint: str | None = None
    primary_action: str
    latest_pdf_created_at: datetime | None = None


class ReportCenterStatus(BaseModel):
    generated_at: datetime
    export_allowed: bool
    export_status: str
    max_pdf_pages_per_file: int
    packages_count: int = 0
    created_pdf_packages_count: int = 0
    blocked_pdf_packages_count: int = 0
    latest_package_created_at: datetime | None = None
    years: list[ReportYearCard] = Field(default_factory=list)
    artifacts: list[ReportArtifact] = Field(default_factory=list)
    csv_exports: list[ReportArtifact] = Field(default_factory=list)
    actions: list[ReportAction] = Field(default_factory=list)
    quality_warnings: list[ReportQualityWarning] = Field(default_factory=list)
    evidence_health: ReportEvidenceHealth | None = None
    packages: list[ExportPackage] = Field(default_factory=list)
    methodology: str
