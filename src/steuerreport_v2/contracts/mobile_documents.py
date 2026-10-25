from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


MobileDocumentKind = Literal[
    "bank_statement",
    "exchange_statement",
    "purchase_receipt",
    "tax_notice",
    "inheritance_evidence",
    "portfolio_statement",
    "other",
]
MobileDocumentReviewStatus = Literal["pending_review", "reviewed", "rejected"]


class MobileDocumentInboxSummary(BaseModel):
    status: Literal["empty", "review_required", "stored"] = "empty"
    total_documents: int = 0
    pending_review_documents: int = 0
    reviewed_documents: int = 0
    rejected_documents: int = 0
    stored_bytes: int = 0
    total_upload_attempts: int = 0


class MobileDocumentEvidence(BaseModel):
    document_id: str
    document_sha256: str = Field(min_length=64, max_length=64)
    original_filename: str
    media_type: Literal["application/pdf", "image/jpeg", "image/png"]
    size_bytes: int
    document_kind: MobileDocumentKind
    source_hint: str | None = None
    note: str | None = None
    captured_at: datetime | None = None
    first_uploaded_at: datetime
    last_uploaded_at: datetime
    upload_count: int = 1
    first_uploaded_by_session_id: str | None = None
    last_uploaded_by_session_id: str | None = None
    review_status: MobileDocumentReviewStatus = "pending_review"
    evidence_ref: str
    content_download_path: str
    tax_effect: Literal["none_pending_review"] = "none_pending_review"


class MobileDocumentInboxReport(MobileDocumentInboxSummary):
    generated_at: datetime
    returned_documents: int = 0
    max_file_bytes: int
    supported_media_types: list[str] = Field(default_factory=list)
    documents: list[MobileDocumentEvidence] = Field(default_factory=list)
    methodology: str


class MobileDocumentUploadResult(BaseModel):
    document: MobileDocumentEvidence
    already_present: bool = False
    content_restored: bool = False
    inbox: MobileDocumentInboxSummary
