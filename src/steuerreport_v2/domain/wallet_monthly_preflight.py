from __future__ import annotations

from steuerreport_v2.private_settings import private_template, private_value

import csv
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from steuerreport_v2.contracts.wallet_monthly import (
    WalletMonthlyPeriodTotal,
    WalletMonthlyPreflightReport,
)
from steuerreport_v2.paths import USERTRANSFER_ROOT


DEFAULT_WALLET_MONTHLY_FILE = (
    USERTRANSFER_ROOT
    / private_template('Wallet.{primary_solana_wallet}-month.csv')
)
DEFAULT_WALLET = private_value('primary_solana_wallet', '')


class WalletMonthlyPreflightService:
    def inspect(
        self,
        *,
        file_path: str = str(DEFAULT_WALLET_MONTHLY_FILE),
        wallet: str = DEFAULT_WALLET,
        asset: str = "IOT",
        cutoff_at: str = "2024-02-23T21:01:15",
        required_quantity: Decimal = Decimal("339834.071782"),
    ) -> WalletMonthlyPreflightReport:
        cutoff = datetime.fromisoformat(cutoff_at)
        rows = 0
        gateways: set[str] = set()
        by_period: defaultdict[datetime, Decimal] = defaultdict(lambda: Decimal("0"))
        asset_upper = asset.upper()
        path = Path(file_path)

        if path.is_file():
            with path.open(newline="", encoding="utf-8-sig") as handle:
                for row in csv.DictReader(handle):
                    period_raw = str(row.get("Period Start (UTC)") or "").strip()
                    if not period_raw:
                        continue
                    period = datetime.strptime(period_raw, "%d.%m.%y")
                    quantity = self._asset_quantity(row, asset_upper)
                    if quantity == 0:
                        continue
                    rows += 1
                    gateway = str(row.get("Gateway Address") or "").strip()
                    if gateway:
                        gateways.add(gateway)
                    by_period[period] += quantity

        monthly_totals = [
            WalletMonthlyPeriodTotal(
                period_start=period.date().isoformat(),
                asset=asset_upper,
                quantity=quantity,
            )
            for period, quantity in sorted(by_period.items())
        ]
        total_quantity = sum(by_period.values(), Decimal("0"))
        quantity_until_cutoff = sum(
            quantity
            for period, quantity in by_period.items()
            if period <= cutoff
        )
        coverage_ratio = (
            quantity_until_cutoff / required_quantity
            if required_quantity != 0
            else Decimal("0")
        )
        periods = sorted(by_period)
        return WalletMonthlyPreflightReport(
            file_path=str(path),
            wallet=wallet,
            asset=asset_upper,
            cutoff_at=cutoff.isoformat(),
            required_quantity=required_quantity,
            rows=rows,
            gateways=len(gateways),
            first_period=periods[0].date().isoformat() if periods else None,
            last_period=periods[-1].date().isoformat() if periods else None,
            total_quantity=total_quantity,
            quantity_until_cutoff=quantity_until_cutoff,
            covers_required_quantity=quantity_until_cutoff >= required_quantity,
            coverage_ratio=coverage_ratio,
            monthly_totals=monthly_totals,
            target_changed=False,
        )

    def _asset_quantity(self, row: dict[str, str], asset: str) -> Decimal:
        iot_token = str(row.get("IOT Token") or "").strip().upper()
        mobile_token = str(row.get("MOBILE Token") or "").strip().upper()
        if asset == "IOT" and iot_token in {"", "IOT"}:
            return self._decimal(row.get("IOT Tokens"))
        if asset == "MOBILE" and mobile_token in {"", "MOBILE"}:
            return self._decimal(row.get("MOBILE Tokens"))
        if asset == iot_token:
            return self._decimal(row.get("IOT Tokens"))
        return Decimal("0")

    def _decimal(self, value: str | None) -> Decimal:
        try:
            return Decimal(str(value or "0").strip().replace(",", "."))
        except InvalidOperation:
            return Decimal("0")
