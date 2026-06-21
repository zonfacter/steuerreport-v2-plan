from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel


class WalletMonthlyPeriodTotal(BaseModel):
    period_start: str
    asset: str
    quantity: Decimal


class WalletMonthlyPreflightReport(BaseModel):
    file_path: str
    wallet: str
    asset: str
    cutoff_at: str
    required_quantity: Decimal
    rows: int
    gateways: int
    first_period: str | None = None
    last_period: str | None = None
    total_quantity: Decimal
    quantity_until_cutoff: Decimal
    covers_required_quantity: bool
    coverage_ratio: Decimal
    monthly_totals: list[WalletMonthlyPeriodTotal]
    target_changed: bool = False
