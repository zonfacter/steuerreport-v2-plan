from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


WalletFifoMigrationRehearsalStatus = Literal[
    "blocked",
    "ready_for_method_decision",
    "ready_for_controlled_migration",
    "already_active",
]


class WalletFifoMigrationRehearsalRequest(BaseModel):
    run_id: str | None = None


class WalletFifoMigrationCheck(BaseModel):
    key: str
    label: str
    gate: Literal["technical", "governance"]
    passed: bool
    blocking: bool = True
    detail: str


class WalletFifoMigrationYearCheck(BaseModel):
    year: int
    source_wallet_gain_loss_eur: Decimal = Decimal("0")
    staging_gain_loss_eur: Decimal = Decimal("0")
    delta_eur: Decimal = Decimal("0")
    source_wallet_tax_lines_count: int = 0
    staging_tax_lines_count: int = 0
    parity: bool = False


class WalletFifoMigrationRehearsalReport(BaseModel):
    rehearsal_id: str
    generated_at: datetime
    status: WalletFifoMigrationRehearsalStatus
    run_id: str
    run_generated_at: datetime
    run_as_of: datetime
    run_semantic_sha256: str
    input_fingerprint_digest: str
    input_fingerprint_current: bool = False
    method_version: str
    decision_status: str
    decision_id: str | None = None
    decision_ready: bool = False
    approved_decision_bound: bool = False
    active_fifo_scope: str
    target_fifo_scope: str
    technical_ready: bool = False
    migration_ready: bool = False
    production_write_performed: bool = False
    production_tax_semantic_unchanged: bool = False
    provider_basis_gap_count: int = 0
    unexplained_unmatched_count: int = 0
    source_all_lots_count: int = 0
    source_open_lots_count: int = 0
    source_tax_lines_count: int = 0
    staging_lots_count: int = 0
    staging_open_lots_count: int = 0
    staging_tax_lines_count: int = 0
    staging_orphan_tax_lines_count: int = 0
    staging_negative_lots_count: int = 0
    staging_arithmetic_delta_eur: Decimal = Decimal("0")
    staging_tax_lots_semantic_sha256: str
    staging_tax_lines_semantic_sha256: str
    semantic_sha256: str
    year_checks: list[WalletFifoMigrationYearCheck] = Field(default_factory=list)
    checks: list[WalletFifoMigrationCheck] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    artifact_path: str
    latest_artifact_path: str
    methodology: str


WalletFifoMigrationApplyReadinessStatus = Literal[
    "blocked",
    "ready_for_controlled_apply",
    "already_active",
]


class WalletFifoMigrationApplyCheck(BaseModel):
    key: str
    label: str
    gate: Literal["technical", "governance", "operational"]
    passed: bool
    blocking: bool = True
    detail: str


class WalletFifoMigrationApplyReadinessReport(BaseModel):
    generated_at: datetime
    status: WalletFifoMigrationApplyReadinessStatus
    ready: bool = False
    run_id: str | None = None
    rehearsal_id: str | None = None
    decision_id: str | None = None
    decision_status: str = "pending"
    input_fingerprint_current: bool = False
    rehearsal_bound: bool = False
    active_fifo_scope: str
    target_fifo_scope: str
    backup_root: str
    required_backup_bytes: int = 0
    available_backup_bytes: int = 0
    checks: list[WalletFifoMigrationApplyCheck] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    methodology: str


class WalletFifoMigrationApplyRequest(BaseModel):
    run_id: str
    rehearsal_id: str
    rehearsal_semantic_sha256: str
    decision_id: str
    actor: str = Field(min_length=2)
    rationale: str = Field(min_length=20)
    execute: bool = False
    confirmation_phrase: str = ""
    acknowledge_verified_backup: bool = False
    acknowledge_material_tax_delta: bool = False
    acknowledge_report_regeneration: bool = False


class WalletFifoMigrationApplyReport(BaseModel):
    migration_id: str
    generated_at: datetime
    status: Literal["dry_run", "applied", "already_active"]
    applied: bool = False
    run_id: str
    rehearsal_id: str
    decision_id: str
    actor: str
    source_fifo_scope: str
    target_fifo_scope: str
    input_fingerprint_digest: str
    lots_count: int = 0
    open_lots_count: int = 0
    tax_lines_count: int = 0
    backup_path: str | None = None
    backup_size_bytes: int = 0
    backup_sha256: str | None = None
    year_checks: list[WalletFifoMigrationYearCheck] = Field(default_factory=list)
    readiness: WalletFifoMigrationApplyReadinessReport
    artifact_path: str | None = None
    latest_artifact_path: str | None = None
    methodology: str
