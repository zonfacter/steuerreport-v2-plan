from __future__ import annotations

import csv
import io
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from steuerreport_v2.contracts.parity import (
    V1ReferenceMetricCreate,
    V1WisoReferenceImportResult,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore


class WisoReferenceImporter:
    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def import_path(self, file_path: str, label: str = "wiso") -> V1WisoReferenceImportResult:
        path = Path(file_path)
        return self.import_text(path.read_text(encoding="utf-8-sig"), label=label)

    def import_text(self, content: str, label: str = "wiso") -> V1WisoReferenceImportResult:
        lines = [line for line in content.splitlines() if line.strip()]
        if len(lines) < 2:
            raise ValueError("WISO CSV enthaelt keine auswertbaren Zeilen")
        tax_year = self._tax_year(lines[0])
        self.store.delete_v1_reference_metrics_by_source(label)
        rows = list(csv.DictReader(io.StringIO("\n".join(lines[1:]))))
        aggregates: defaultdict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
        assets: set[str] = set()

        for row in rows:
            asset = str(row.get("Currency") or "").strip().upper()
            if not asset:
                continue
            assets.add(asset)
            aggregates[(asset, "quantity_disposed")] += self._decimal(row.get("Amount"))
            aggregates[(asset, "disposal_proceeds_eur")] += self._decimal(row.get("Proceeds"))
            aggregates[(asset, "acquisition_cost_eur")] += self._decimal(row.get("Cost Basis"))
            aggregates[(asset, "gain_loss_eur")] += self._decimal(row.get("Gain / Loss"))

        created = 0
        for (asset, metric), value in sorted(aggregates.items()):
            unit = asset if metric == "quantity_disposed" else "EUR"
            self.store.add_v1_reference_metric(
                V1ReferenceMetricCreate(
                    scope="tax",
                    metric=metric,
                    unit=unit,
                    value=value,
                    year=tax_year,
                    asset=asset,
                    source=label,
                    note="WISO Steuer CSV aggregiert",
                )
            )
            created += 1

        return V1WisoReferenceImportResult(
            label=label,
            tax_year=tax_year,
            rows_read=len(rows),
            references_created=created,
            assets=sorted(assets),
        )

    def _tax_year(self, metadata_line: str) -> int:
        for part in metadata_line.split(","):
            if part.startswith("Tax_Year:"):
                return int(part.split(":", 1)[1])
        raise ValueError("WISO CSV enthaelt kein Tax_Year-Metadatum")

    def _decimal(self, value: str | None) -> Decimal:
        if value is None or value.strip() == "":
            return Decimal("0")
        return Decimal(value.strip().replace(",", "."))
