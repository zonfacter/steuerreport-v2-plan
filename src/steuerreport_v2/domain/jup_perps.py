from __future__ import annotations

from steuerreport_v2.private_settings import private_template

import csv
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

from steuerreport_v2.contracts.jup_perps import (
    JupPerpsAssetSummary,
    JupPerpsPreview,
    JupPerpsPreviewRow,
)


DEFAULT_JUP_PERPS_FILE = (
    Path("/workspace/steuerreport/usertransfer")
    / "jup"
    / private_template('{primary_solana_wallet}.csv')
)
DEFAULT_V1_FX_DB = Path("/root/.local/share/steuerreport/steuerreport.db")


@dataclass
class _Accumulator:
    rows: int = 0
    increases: int = 0
    decreases: int = 0
    trade_size_usd: Decimal = Decimal("0")
    collateral_flow_usd: Decimal = Decimal("0")
    realized_pnl_usd: Decimal = Decimal("0")
    trade_fee_usd: Decimal = Decimal("0")
    liquidation_fee_usd: Decimal = Decimal("0")
    net_result_usd: Decimal = Decimal("0")
    net_result_eur: Decimal = Decimal("0")


class JupPerpsPreviewService:
    def preview(
        self,
        *,
        file_path: str = str(DEFAULT_JUP_PERPS_FILE),
        v1_fx_db_path: str = str(DEFAULT_V1_FX_DB),
        sample_limit: int = 20,
    ) -> JupPerpsPreview:
        path = Path(file_path)
        rows = self._read_rows(path)
        fx_cache: dict[str, Decimal] = {}
        asset_totals: defaultdict[str, _Accumulator] = defaultdict(_Accumulator)
        total = _Accumulator()
        missing_fx_count = 0
        sample_rows: list[JupPerpsPreviewRow] = []

        for raw in rows:
            parsed = self._parse_row(raw, Path(v1_fx_db_path), fx_cache)
            if parsed.usd_eur <= 0:
                missing_fx_count += 1
            self._add(total, parsed)
            self._add(asset_totals[parsed.asset], parsed)
            if len(sample_rows) < max(sample_limit, 0):
                sample_rows.append(parsed)

        return JupPerpsPreview(
            file_path=str(path),
            row_count=len(rows),
            assets=sorted(asset_totals),
            increases=total.increases,
            decreases=total.decreases,
            collateral_flow_usd=total.collateral_flow_usd,
            realized_pnl_usd=total.realized_pnl_usd,
            trade_fee_usd=total.trade_fee_usd,
            liquidation_fee_usd=total.liquidation_fee_usd,
            net_result_usd=total.net_result_usd,
            net_result_eur=total.net_result_eur,
            missing_fx_count=missing_fx_count,
            asset_summaries=[
                JupPerpsAssetSummary(asset=asset, **acc.__dict__)
                for asset, acc in sorted(asset_totals.items())
            ],
            sample_rows=sample_rows,
        )

    def _read_rows(self, path: Path) -> list[dict[str, str]]:
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, skipinitialspace=True)
            return [
                {
                    str(key).strip(): str(value or "").strip()
                    for key, value in row.items()
                    if key is not None
                }
                for row in reader
            ]

    def _parse_row(
        self,
        row: dict[str, str],
        fx_db_path: Path,
        fx_cache: dict[str, Decimal],
    ) -> JupPerpsPreviewRow:
        event_time = self._parse_datetime(row["Created at"])
        day = event_time.date().isoformat()
        usd_eur = fx_cache.get(day)
        if usd_eur is None:
            usd_eur = self._usd_eur_rate(fx_db_path, day)
            fx_cache[day] = usd_eur
        realized_pnl_usd = self._decimal(row.get("Profit / Loss ($)"))
        trade_fee_usd = self._decimal(row.get("Trade fee ($)"))
        liquidation_fee_usd = self._decimal(row.get("Liquidation fee ($)"))
        net_result_usd = realized_pnl_usd - trade_fee_usd - liquidation_fee_usd
        return JupPerpsPreviewRow(
            event_time=event_time,
            tx_id=row.get("Transaction ID", ""),
            asset=row.get("Asset", "").upper(),
            position=row.get("Position", ""),
            position_change=row.get("Position change", ""),
            order_type=row.get("Order type", ""),
            collateral_flow_usd=self._decimal(row.get("Deposit / Withdraw ($)")),
            execution_price_usd=self._decimal(row.get("Execution price ($)")),
            trade_size_usd=self._decimal(row.get("Trade size ($)")),
            realized_pnl_usd=realized_pnl_usd,
            trade_fee_usd=trade_fee_usd,
            liquidation_fee_usd=liquidation_fee_usd,
            net_result_usd=net_result_usd,
            usd_eur=usd_eur,
            net_result_eur=net_result_usd * usd_eur,
        )

    def _add(self, accumulator: _Accumulator, row: JupPerpsPreviewRow) -> None:
        accumulator.rows += 1
        change = row.position_change.strip().lower()
        if change == "increase":
            accumulator.increases += 1
        if change == "decrease":
            accumulator.decreases += 1
        accumulator.trade_size_usd += row.trade_size_usd
        accumulator.collateral_flow_usd += row.collateral_flow_usd
        accumulator.realized_pnl_usd += row.realized_pnl_usd
        accumulator.trade_fee_usd += row.trade_fee_usd
        accumulator.liquidation_fee_usd += row.liquidation_fee_usd
        accumulator.net_result_usd += row.net_result_usd
        accumulator.net_result_eur += row.net_result_eur

    def _parse_datetime(self, value: str) -> datetime:
        normalized = re.sub(r"\s+\([^)]*\)$", "", value.strip())
        parsed = datetime.strptime(normalized, "%a %b %d %Y %H:%M:%S GMT%z")
        return parsed.astimezone(timezone.utc)

    def _usd_eur_rate(self, db_path: Path, rate_date: str) -> Decimal:
        if not db_path.exists():
            return Decimal("0")
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
            row = con.execute(
                """
                select rate
                from fx_cache
                where rate_date <= ? and base_ccy = 'USD' and quote_ccy = 'EUR'
                order by rate_date desc
                limit 1
                """,
                (rate_date,),
            ).fetchone()
        if row is None:
            return Decimal("0")
        return self._decimal(row[0])

    def _decimal(self, value: object) -> Decimal:
        if value in (None, ""):
            return Decimal("0")
        try:
            return Decimal(str(value).strip().replace(",", "."))
        except (InvalidOperation, ValueError):
            return Decimal("0")
