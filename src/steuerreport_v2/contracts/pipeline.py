from __future__ import annotations

from pydantic import BaseModel


class PipelineResult(BaseModel):
    normalized_events: int
    balance_entries: int
    flow_entries: int
    tax_lines: int
    derivative_lines: int = 0
    review_issues_open: int
    allow_export: bool


class DemoSeedResult(BaseModel):
    batch_id: str
    imported_rows: int
    pipeline: PipelineResult


class ImportRunResult(BaseModel):
    batch_id: str
    imported_rows: int
    normalized_events: int
    skipped_raw_objects: int
    pipeline: PipelineResult


class ImportDeleteResult(BaseModel):
    batch_id: str
    deleted: bool
    pipeline: PipelineResult
