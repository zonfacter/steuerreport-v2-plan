from __future__ import annotations

from pydantic import BaseModel


class ImportPolicyDecision(BaseModel):
    file_path: str
    relative_path: str
    category: str
    can_be_realimport: bool
    action: str
    reason: str
    imported: bool = False
    imported_batch_ids: list[str] = []
    imported_sources: list[str] = []


class ImportPolicyAudit(BaseModel):
    root_path: str
    files_total: int
    classified: int
    unclassified: int
    curated_primary: int
    staging_required: int
    parser_needed: int
    reference_only: int
    imported_files: int = 0
    unused_curated_primary: int = 0
    unused_staging_required: int = 0
    unused_parser_needed: int = 0
    unused_reference_only: int = 0
    decisions: list[ImportPolicyDecision]
