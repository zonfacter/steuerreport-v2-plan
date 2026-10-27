from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from steuerreport_v2.contracts.prices import (
    PriceCsvPreview,
    PriceCsvPreviewRow,
    PricePointCreate,
)

REQUIRED_COLUMNS = ["asset", "price_eur", "priced_at"]


class PriceCsvImporter:
    def preview(self, content: str, default_source: str = "manual-price-csv") -> PriceCsvPreview:
        rows = self._parse_rows(content, default_source)
        return PriceCsvPreview(
            row_count=len(rows),
            valid_rows=sum(1 for row in rows if not row.errors),
            invalid_rows=sum(1 for row in rows if row.errors),
            can_import=bool(rows) and all(not row.errors for row in rows),
            required_columns=REQUIRED_COLUMNS,
            rows=rows[:50],
        )

    def to_price_points(
        self,
        content: str,
        default_source: str = "manual-price-csv",
    ) -> tuple[PriceCsvPreview, list[PricePointCreate]]:
        preview = self.preview(content, default_source)
        if not preview.can_import:
            return preview, []
        prices = [
            PricePointCreate(
                asset=row.asset or "",
                price_eur=row.price_eur or Decimal("0"),
                priced_at=row.priced_at or datetime.now(timezone.utc),
                source=row.source or default_source,
                confidence=row.confidence or Decimal("1.0"),
            )
            for row in self._parse_rows(content, default_source)
        ]
        return preview, prices

    def _parse_rows(self, content: str, default_source: str) -> list[PriceCsvPreviewRow]:
        reader = csv.DictReader(io.StringIO(content.strip()))
        if reader.fieldnames is None:
            return []
        fieldnames = {field.strip().lower() for field in reader.fieldnames if field is not None}
        missing_columns = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
        rows: list[PriceCsvPreviewRow] = []
        for index, raw_row in enumerate(reader, start=2):
            normalized = {
                str(key).strip().lower(): (value.strip() if isinstance(value, str) else value)
                for key, value in raw_row.items()
                if key is not None
            }
            row = self._preview_row(index, normalized, default_source)
            row.errors.extend(f"missing_column:{column}" for column in missing_columns)
            rows.append(row)
        if missing_columns and not rows:
            rows.append(
                PriceCsvPreviewRow(
                    row_number=1,
                    source=default_source,
                    errors=[f"missing_column:{column}" for column in missing_columns],
                )
            )
        return rows

    def _preview_row(
        self,
        row_number: int,
        raw_row: dict[str, str | None],
        default_source: str,
    ) -> PriceCsvPreviewRow:
        errors: list[str] = []
        asset = (raw_row.get("asset") or "").strip().upper()
        if not asset:
            errors.append("asset_required")

        price_eur = self._decimal(raw_row.get("price_eur"), "price_eur", errors)
        if price_eur is not None and price_eur <= 0:
            errors.append("price_eur_must_be_positive")

        priced_at = self._datetime(raw_row.get("priced_at") or raw_row.get("price_date"), errors)
        source = (raw_row.get("source") or default_source).strip() or default_source
        confidence = self._decimal(raw_row.get("confidence") or "1.0", "confidence", errors)
        if confidence is not None and (confidence <= 0 or confidence > 1):
            errors.append("confidence_must_be_between_0_and_1")

        return PriceCsvPreviewRow(
            row_number=row_number,
            asset=asset or None,
            price_eur=price_eur,
            priced_at=priced_at,
            source=source,
            confidence=confidence,
            errors=errors,
        )

    def _decimal(
        self,
        raw_value: str | None,
        field: str,
        errors: list[str],
    ) -> Decimal | None:
        value = (raw_value or "").strip().replace(",", ".")
        if not value:
            errors.append(f"{field}_required")
            return None
        try:
            return Decimal(value)
        except InvalidOperation:
            errors.append(f"{field}_invalid_decimal")
            return None

    def _datetime(self, raw_value: str | None, errors: list[str]) -> datetime | None:
        value = (raw_value or "").strip()
        if not value:
            errors.append("priced_at_required")
            return None
        if len(value) == 10:
            value = f"{value}T00:00:00+00:00"
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            errors.append("priced_at_invalid_datetime")
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
