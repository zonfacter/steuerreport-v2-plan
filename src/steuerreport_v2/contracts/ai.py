from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

AiTaskStatus = Literal["queued", "done", "failed"]


class AiTaskCreate(BaseModel):
    task_type: str
    prompt: str
    allow_external: bool = False


class AiTask(BaseModel):
    task_id: str
    task_type: str
    prompt: str
    status: AiTaskStatus
    result_json: str | None = None
    allow_external: bool = False
    created_at: datetime
    updated_at: datetime


class AiTaskDeleteResult(BaseModel):
    task_id: str
    deleted: bool


class LocalAiYearPackageQaYear(BaseModel):
    year: int
    export_ready: bool | None = None
    zip_file_count: int = 0
    manifest_file_count: int = 0
    tax_line_years: list[str] = Field(default_factory=list)
    findings_count: int = 0


class LocalAiYearPackageQaStatus(BaseModel):
    status: str
    llm_status: str | None = None
    latest_run_id: str | None = None
    latest_run_path: str | None = None
    generated_at: datetime | None = None
    findings_count: int = 0
    years: list[LocalAiYearPackageQaYear] = Field(default_factory=list)
    summary_md: str | None = None
    local_ai_review_md: str | None = None
    service_name: str = "steuerreport-v2-local-ai-year-package-qa-20260614.service"
    methodology: str


class LocalAiAssetFifoCorrectionYear(BaseModel):
    year: int
    rows_count: int = 0
    possible_recalculation_assets_count: int = 0
    attribution_review_assets_count: int = 0
    candidate_assets: list[str] = Field(default_factory=list)


class LocalAiAssetFifoCorrectionCandidate(BaseModel):
    year: int
    asset: str
    tax_sum_impact: str
    direct_gain_loss_eur: str | None = None
    linked_gain_loss_eur: str | None = None
    related_tax_lines_count: int = 0
    related_tax_lines_csv: str | None = None


class LocalAiAssetFifoCorrectionStatus(BaseModel):
    status: str
    llm_status: str | None = None
    latest_run_id: str | None = None
    latest_run_path: str | None = None
    generated_at: datetime | None = None
    candidates_count: int = 0
    years: list[LocalAiAssetFifoCorrectionYear] = Field(default_factory=list)
    candidates: list[LocalAiAssetFifoCorrectionCandidate] = Field(default_factory=list)
    summary_md: str | None = None
    local_ai_review_md: str | None = None
    service_name: str = "steuerreport-v2-local-ai-asset-fifo-correction-review-20260620.service"
    methodology: str


class LocalAiWalletFifoProvenanceYear(BaseModel):
    year: int
    bmf_status: str | None = None
    blocking_items_count: int = 0
    wallet_unmatched_count: int = 0
    wallet_delta_gain_loss_eur: str | None = None
    groups_count: int = 0
    likely_causes: dict[str, int] = Field(default_factory=dict)


class LocalAiWalletFifoProvenanceStatus(BaseModel):
    status: str
    llm_status: str | None = None
    latest_run_id: str | None = None
    latest_run_path: str | None = None
    generated_at: datetime | None = None
    groups_count: int = 0
    blocking_groups_count: int = 0
    groups_csv: str | None = None
    years: list[LocalAiWalletFifoProvenanceYear] = Field(default_factory=list)
    summary_md: str | None = None
    local_ai_review_md: str | None = None
    service_name: str = "steuerreport-v2-local-ai-wallet-fifo-provenance-review-20260620.service"
    methodology: str
