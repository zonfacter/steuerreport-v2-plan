from __future__ import annotations

from pydantic import BaseModel

from steuerreport_v2.contracts.binance_earn import BinanceCapitalWithdrawalPreview, BinanceEarnHistoryApiPreview
from steuerreport_v2.contracts.imports import ImportBatch
from steuerreport_v2.contracts.pipeline import ImportRunResult


class BinanceEarnHarvestImportRequest(BaseModel):
    harvest_path: str
    execute: bool = False


class BinanceEarnApiImportRequest(BaseModel):
    since: str | None = None
    until: str | None = None
    assets: list[str] = []
    max_pages: int = 200
    max_records: int = 50000
    execute: bool = False


class BinanceCapitalWithdrawalApiImportRequest(BaseModel):
    since: str | None = None
    until: str | None = None
    assets: list[str] = []
    max_records: int = 5000
    execute: bool = False


class BinanceEarnHarvestImportPreview(BaseModel):
    harvest_path: str
    can_execute: bool
    blocked_reason: str | None = None
    records_total: int = 0
    rows_prepared: int = 0
    assets: list[str] = []
    record_types: dict[str, int] = {}
    duplicate_batch_id: str | None = None
    warnings: list[str] = []


class BinanceEarnHarvestImportResult(BaseModel):
    preview: BinanceEarnHarvestImportPreview
    batch: ImportBatch | None = None
    run: ImportRunResult | None = None


class BinanceEarnApiImportResult(BaseModel):
    api_preview: BinanceEarnHistoryApiPreview
    import_preview: BinanceEarnHarvestImportPreview
    batch: ImportBatch | None = None
    run: ImportRunResult | None = None


class BinanceCapitalWithdrawalApiImportResult(BaseModel):
    api_preview: BinanceCapitalWithdrawalPreview
    import_preview: BinanceEarnHarvestImportPreview
    batch: ImportBatch | None = None
    run: ImportRunResult | None = None
