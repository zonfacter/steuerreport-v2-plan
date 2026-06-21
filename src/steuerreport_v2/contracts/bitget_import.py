from __future__ import annotations

from pydantic import BaseModel

from steuerreport_v2.contracts.binance_earn_import import BinanceEarnHarvestImportPreview
from steuerreport_v2.contracts.bitget import BitgetWithdrawalPreview
from steuerreport_v2.contracts.imports import ImportBatch
from steuerreport_v2.contracts.pipeline import ImportRunResult


class BitgetWithdrawalApiImportRequest(BaseModel):
    since: str | None = None
    until: str | None = None
    assets: list[str] = []
    max_records: int = 5000
    execute: bool = False


class BitgetWithdrawalApiImportResult(BaseModel):
    api_preview: BitgetWithdrawalPreview
    import_preview: BinanceEarnHarvestImportPreview
    batch: ImportBatch | None = None
    run: ImportRunResult | None = None

