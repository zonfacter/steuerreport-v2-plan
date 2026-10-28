from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from io import StringIO

from steuerreport_v2.contracts.imports import (
    CsvImportPreview,
    ImportBatch,
    ImportBatchCreate,
    RawObjectCreate,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.importers.source_profiles import (
    inspect_profile_columns,
    profile_for_source,
)


class CsvRawImporter:
    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def import_text(self, source: str, filename: str, content: str, mexc=None) -> ImportBatch:
        if source.strip().lower() == "mexc":
            from steuerreport_v2.importers.mexc_native import MexcNativeImporter
            return MexcNativeImporter(self.store).import_file(filename, content.encode("utf-8"), mexc=mexc)
        file_hash = self.hash_text(content)
        reader = self._dict_reader(content)
        return self.import_rows(
            source=source,
            filename=filename,
            file_hash=file_hash,
            rows=reader,
        )

    def import_rows(
        self,
        source: str,
        filename: str,
        file_hash: str,
        rows: Iterable[dict[str, object]],
    ) -> ImportBatch:
        if source.strip().lower() == "mexc":
            raise ValueError("MEXC benoetigt den nativen Dateiimport mit Konto-/Exportartzuordnung.")
        existing = self.store.get_import_batch_by_file_hash(source, file_hash)
        if existing is not None:
            return existing

        batch = self.store.create_import_batch(
            ImportBatchCreate(source=source, filename=filename, file_hash=file_hash)
        )

        payloads = [
                RawObjectCreate(
                    row_number=row_number,
                    payload_json=json.dumps(
                        self._stringify_row(row),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
            )
            for row_number, row in enumerate(rows, start=1)
            if not self._is_ignorable_row(source, row)
        ]
        self.store.add_raw_objects(batch.batch_id, payloads)
        updated = self.store.get_import_batch(batch.batch_id)
        if updated is None:
            raise RuntimeError("import batch disappeared during CSV import")
        return updated

    def preview_text(
        self,
        source: str,
        filename: str,
        content: str,
        sample_limit: int = 5,
        mexc=None,
    ) -> CsvImportPreview:
        if source.strip().lower() == "mexc":
            from steuerreport_v2.importers.mexc_native import MexcNativeImporter
            return MexcNativeImporter(self.store).prepare(filename, content.encode("utf-8"), mexc=mexc)[0]
        reader = self._dict_reader(content)
        columns = list(reader.fieldnames or [])
        profile = profile_for_source(source)
        matched, missing = inspect_profile_columns(profile, columns)
        file_hash = self.hash_text(content)
        duplicate = self.store.get_import_batch_by_file_hash(source, file_hash)
        sample_rows: list[dict[str, str | None]] = []
        row_count = 0
        for row in reader:
            row_count += 1
            if len(sample_rows) < sample_limit:
                sample_rows.append(dict(row))
        return CsvImportPreview(
            source=source,
            filename=filename,
            profile_label=profile.label,
            file_format="csv",
            sheet_name=None,
            sheet_names=[],
            row_count=row_count,
            columns=columns,
            matched_columns=matched,
            missing_required_groups=missing,
            sample_rows=sample_rows,
            can_import=len(missing) == 0 and row_count > 0,
            duplicate_batch_id=duplicate.batch_id if duplicate is not None else None,
            file_sha256=file_hash,
            import_fingerprint=file_hash,
        )

    def hash_text(self, content: str) -> str:
        return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()

    @classmethod
    def _dict_reader(cls, content: str) -> csv.DictReader:
        return csv.DictReader(
            StringIO(content),
            dialect=cls._dialect_for_text(content),
            skipinitialspace=True,
        )

    @staticmethod
    def _dialect_for_text(content: str) -> csv.Dialect:
        sample = content[:4096]
        first_line = next((line for line in sample.splitlines() if line.strip()), "")
        if first_line.count(";") > first_line.count(","):
            class SemicolonDialect(csv.excel):
                delimiter = ";"

            return SemicolonDialect
        try:
            return csv.Sniffer().sniff(sample, delimiters=",;")
        except csv.Error:
            return csv.excel

    def _stringify_row(self, row: dict[str, object]) -> dict[str, str | None]:
        result: dict[str, str | None] = {}
        for key, value in row.items():
            if value is None:
                result[str(key)] = None
            else:
                result[str(key)] = str(value)
        return result

    def _is_ignorable_row(self, source: str, row: dict[str, object]) -> bool:
        values = {str(key).strip().lower().replace("_", " "): value for key, value in row.items()}
        if not self._has_any_value(values):
            return True
        if (
            source == "pionex"
            and str(values.get("state") or "").strip().upper() == "CANCELED"
            and not self._pionex_row_has_execution(values)
        ):
            return True
        if not self._has_any_value(
            {
                key: value
                for key, value in values.items()
                if key
                in {
                    "time",
                    "time iso",
                    "date",
                    "timestamp",
                    "timestamp utc",
                    "utc time",
                    "date(utc+0)",
                    "period start (utc)",
                }
            }
        ) and not self._has_any_value(
            {
                key: value
                for key, value in values.items()
                if key
                in {
                    "amount",
                    "rewards",
                    "principal",
                    "amount usdt",
                    "quantity",
                    "change",
                    "received quantity",
                    "buy amount",
                    "surplus/deduction (after fee)",
                    "surplus/deduction (before fee)",
                    "incoming amount",
                    "outgoing amount",
                    "fee amount (optional)",
                    "hnt amount",
                    "iot amount",
                    "iot tokens",
                    "mobile amount",
                    "mobile tokens",
                }
            }
        ):
            return True
        helium_amounts = [
            values.get("hnt amount"),
            values.get("iot amount"),
            values.get("mobile amount"),
            values.get("iot tokens"),
            values.get("mobile tokens"),
            values.get("mining rewards hnt"),
            values.get("mining rewards iot"),
            values.get("mining rewards mobile"),
        ]
        if any(value is not None for value in helium_amounts):
            return all(self._decimal_or_zero(value) == 0 for value in helium_amounts)
        return False

    def _has_any_value(self, values: dict[str, object]) -> bool:
        return any(value not in (None, "") for value in values.values())

    def _decimal_or_zero(self, value: object) -> Decimal:
        if value in (None, ""):
            return Decimal("0")
        try:
            return Decimal(str(value).replace(",", "."))
        except InvalidOperation:
            return Decimal("0")

    def _pionex_row_has_execution(self, values: dict[str, object]) -> bool:
        return any(
            self._decimal_or_zero(values.get(key)) != 0
            for key in (
                "executed qty",
                "executed quantity",
                "executed amount",
                "filled amount",
                "filled quantity",
                "filled size",
            )
        )
