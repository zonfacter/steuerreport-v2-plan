from __future__ import annotations

from pydantic import BaseModel


class ImportCoverageRow(BaseModel):
    file_path: str
    source: str
    file_format: str
    row_count: int
    can_import: bool
    missing_required_groups: list[str]
    columns: list[str]
    error: str | None = None


class ImportCoverageSummary(BaseModel):
    root_path: str
    files_total: int = 0
    files_scanned: int
    importable: int
    blocked: int
    scan_truncated: bool = False
    scan_seconds: float = 0
    rows: list[ImportCoverageRow]
