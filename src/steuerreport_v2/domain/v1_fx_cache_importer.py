from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from steuerreport_v2.contracts.prices import (
    PricePointCreate,
    V1FxCacheImportPreview,
    V1FxCacheImportRow,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.valuation import PriceCoverageService


class V1FxCacheImporter:
    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def preview(self, db_path: str) -> V1FxCacheImportPreview:
        importable, missing, requirements_count, missing_asset_usd, missing_usd_eur = self._collect(db_path)
        return V1FxCacheImportPreview(
            db_path=str(Path(db_path).expanduser()),
            requirements_count=requirements_count,
            importable_count=len(importable),
            missing_asset_usd_count=missing_asset_usd,
            missing_usd_eur_count=missing_usd_eur,
            importable=importable[:200],
            missing=missing[:200],
        )

    def to_price_points(
        self,
        db_path: str,
        confidence: Decimal,
    ) -> tuple[V1FxCacheImportPreview, list[PricePointCreate]]:
        importable, missing, requirements_count, missing_asset_usd, missing_usd_eur = self._collect(db_path)
        preview = V1FxCacheImportPreview(
            db_path=str(Path(db_path).expanduser()),
            requirements_count=requirements_count,
            importable_count=len(importable),
            missing_asset_usd_count=missing_asset_usd,
            missing_usd_eur_count=missing_usd_eur,
            importable=importable[:200],
            missing=missing[:200],
        )
        prices = [
            PricePointCreate(
                asset=row.asset,
                price_eur=row.price_eur,
                priced_at=datetime.combine(row.price_date, datetime.min.time(), tzinfo=timezone.utc),
                source=f"v1_fx_cache:{row.asset_source}:usd_eur:{row.fx_source}",
                confidence=confidence,
            )
            for row in importable
        ]
        return preview, prices

    def _collect(
        self,
        db_path: str,
    ) -> tuple[list[V1FxCacheImportRow], list[dict[str, str]], int, int, int]:
        path = Path(db_path).expanduser()
        requirements = PriceCoverageService(self.store).requirements().requirements
        if not path.exists():
            return (
                [],
                [
                    {
                        "asset": item.asset,
                        "price_date": item.price_date.isoformat(),
                        "reason": "v1_db_missing",
                    }
                    for item in requirements[:200]
                ],
                len(requirements),
                len(requirements),
                0,
            )

        importable: list[V1FxCacheImportRow] = []
        missing: list[dict[str, str]] = []
        missing_asset_usd = 0
        missing_usd_eur = 0
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            for item in requirements:
                date_str = item.price_date.isoformat()
                asset_row = self._fx_exact(con, date_str, item.asset, "USD")
                if asset_row is None:
                    missing_asset_usd += 1
                    missing.append(
                        {"asset": item.asset, "price_date": date_str, "reason": "asset_usd_missing"}
                    )
                    continue
                fx_row = self._fx_on_or_before(con, date_str, "USD", "EUR")
                if fx_row is None:
                    missing_usd_eur += 1
                    missing.append(
                        {"asset": item.asset, "price_date": date_str, "reason": "usd_eur_missing"}
                    )
                    continue
                price_usd = Decimal(str(asset_row["rate"]))
                usd_eur = Decimal(str(fx_row["rate"]))
                if price_usd <= 0 or usd_eur <= 0:
                    missing.append(
                        {"asset": item.asset, "price_date": date_str, "reason": "non_positive_rate"}
                    )
                    continue
                importable.append(
                    V1FxCacheImportRow(
                        asset=item.asset,
                        price_date=item.price_date,
                        price_usd=price_usd,
                        usd_eur=usd_eur,
                        price_eur=price_usd * usd_eur,
                        asset_source=str(asset_row["source"]),
                        fx_source=str(fx_row["source"]),
                        source_rate_date=str(fx_row["rate_date"]),
                    )
                )

        return (
            importable,
            missing,
            len(requirements),
            missing_asset_usd,
            missing_usd_eur,
        )

    def _fx_exact(
        self,
        con: sqlite3.Connection,
        rate_date: str,
        base_ccy: str,
        quote_ccy: str,
    ) -> sqlite3.Row | None:
        return con.execute(
            """
            select rate_date, base_ccy, quote_ccy, rate, source, source_rate_date
            from fx_cache
            where rate_date = ? and base_ccy = ? and quote_ccy = ?
            """,
            (rate_date, base_ccy.upper(), quote_ccy.upper()),
        ).fetchone()

    def _fx_on_or_before(
        self,
        con: sqlite3.Connection,
        rate_date: str,
        base_ccy: str,
        quote_ccy: str,
    ) -> sqlite3.Row | None:
        return con.execute(
            """
            select rate_date, base_ccy, quote_ccy, rate, source, source_rate_date
            from fx_cache
            where rate_date <= ? and base_ccy = ? and quote_ccy = ?
            order by rate_date desc
            limit 1
            """,
            (rate_date, base_ccy.upper(), quote_ccy.upper()),
        ).fetchone()
