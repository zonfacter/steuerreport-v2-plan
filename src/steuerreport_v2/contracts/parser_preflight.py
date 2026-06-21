from __future__ import annotations

from pydantic import BaseModel


class ParserPreflightFile(BaseModel):
    file_path: str
    relative_path: str
    category: str
    action: str
    reason: str
    parser_kind: str
    file_format: str | None = None
    sheet_name: str | None = None
    sheet_names: list[str] = []
    row_count: int | None = None
    columns: list[str] = []
    sample_rows: list[dict[str, str | None]] = []
    warnings: list[str] = []
    can_realimport: bool = False


class ParserPreflightReport(BaseModel):
    root_path: str
    parser_needed: int
    inspected: int
    files: list[ParserPreflightFile]
