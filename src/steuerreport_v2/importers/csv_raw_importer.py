from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import StringIO

from steuerreport_v2.contracts.imports import (
    CsvImportPreview,
    ImportBatch,
    ImportBatchCreate,
    RawObjectCreate,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.import_context import bitget_import_context
from steuerreport_v2.importers.bitget_csv import dict_reader as bitget_dict_reader
from steuerreport_v2.importers.binance_spot_lock import BINANCE_SPOT_IMPORT_LOCK
from steuerreport_v2.importers.source_profiles import (
    inspect_profile_columns,
    profile_for_source,
)


class CsvRawImporter:
    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    @staticmethod
    def canonical_source(source: str) -> str:
        return "bitget" if source.strip().lower() == "bitget" else source

    def import_text(
        self, source: str, filename: str, content: str,
        connection_id: str | None = None, mexc=None,
        import_context: dict[str, str] | None = None,
    ) -> ImportBatch:
        if source.strip().lower() == "mexc":
            from steuerreport_v2.importers.mexc_native import MexcNativeImporter
            return MexcNativeImporter(self.store).import_file(filename, content.encode("utf-8"), mexc=mexc)
        file_hash = self.hash_text(content)
        reader = self._dict_reader(content, source)
        if source.strip().lower() == "bitget":
            reader = list(reader)
        return self.import_rows(
            source=source,
            filename=filename,
            file_hash=file_hash,
            rows=reader,
            connection_id=connection_id,
            import_context=import_context,
        )

    def import_rows(
        self,
        source: str,
        filename: str,
        file_hash: str,
        rows: Iterable[dict[str, object]],
        connection_id: str | None = None,
        import_context: dict[str, str] | None = None,
        allow_binance_history_overlap: bool = False,
    ) -> ImportBatch:
        source = self.canonical_source(source)
        if source.strip().lower() == "binance":
            with BINANCE_SPOT_IMPORT_LOCK:
                return self._import_rows_locked(
                    source, filename, file_hash, rows, connection_id, import_context,
                    allow_binance_history_overlap,
                )
        return self._import_rows_locked(
            source, filename, file_hash, rows, connection_id, import_context,
            allow_binance_history_overlap,
        )

    def _import_rows_locked(
        self,
        source: str,
        filename: str,
        file_hash: str,
        rows: Iterable[dict[str, object]],
        connection_id: str | None,
        import_context: dict[str, str] | None,
        allow_binance_history_overlap: bool,
    ) -> ImportBatch:
        import_context = dict(import_context or {})
        if source.strip().lower() == "bitget" and not import_context:
            import_context = bitget_import_context(
                export_timezone=None, product_scope=None, margin_pair=None,
                allow_legacy_defaults=True,
            )
        existing = self.store.get_import_batch_by_file_hash(source, file_hash, connection_id)
        if source.strip().lower() == "mexc":
            raise ValueError("MEXC benoetigt den nativen Dateiimport mit Konto-/Exportartzuordnung.")
        if existing is not None:
            if source.strip().lower() == "bitget" and (
                existing.connection_id != connection_id
                or existing.import_context != import_context
            ):
                raise ValueError("duplicate_import_scope_mismatch")
            return existing
        if (source.strip().lower() == "binance" and not allow_binance_history_overlap
                and self._has_binance_spot_history(connection_id)):
            raise ValueError("binance_spot_history_requires_guided_import")

        batch = self.store.create_import_batch(
            ImportBatchCreate(
                source=source, filename=filename, file_hash=file_hash,
                connection_id=connection_id,
                import_context=import_context,
            )
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

    def _has_binance_spot_history(self, connection_id: str | None) -> bool:
        where = (
            "lower(b.source)='binance' and "
            "coalesce(json_extract_string(r.payload_json, '$.history_scope_identity'), '')<>''"
        )
        params: list[object] = []
        if connection_id is not None:
            where += " and b.connection_id=?"
            params.append(connection_id)
        with self.store.connect() as con:
            payloads = con.execute(
                f"""select r.payload_json from raw_objects r
                    join raw_import_batches b using(batch_id) where {where}""",
                params,
            ).fetchall()
        for (payload_json,) in payloads:
            raw = json.loads(payload_json)
            record = raw.get("raw_history_record")
            if isinstance(record, str):
                try:
                    record = json.loads(record)
                except json.JSONDecodeError:
                    continue
            if isinstance(record, dict) and record.get("endpoint") == "/api/v3/myTrades":
                return True
        return False

    def preview_text(
        self,
        source: str,
        filename: str,
        content: str,
        sample_limit: int = 5,
        connection_id: str | None = None,
        mexc=None,
        import_context: dict[str, str] | None = None,
        allow_legacy_bitget_context: bool = True,
    ) -> CsvImportPreview:
        source = self.canonical_source(source)
        if source.strip().lower() == "mexc":
            from steuerreport_v2.importers.mexc_native import MexcNativeImporter
            return MexcNativeImporter(self.store).prepare(filename, content.encode("utf-8"), mexc=mexc)[0]
        reader = self._dict_reader(content, source)
        columns = list(reader.fieldnames or [])
        profile = profile_for_source(source)
        matched, missing = inspect_profile_columns(profile, columns)
        file_hash = self.hash_text(content)
        duplicate = self.store.get_import_batch_by_file_hash(source, file_hash, connection_id)
        import_context = dict(import_context or {})
        if source.strip().lower() == "bitget" and not import_context and allow_legacy_bitget_context:
            import_context = bitget_import_context(
                export_timezone=None, product_scope=None, margin_pair=None,
                allow_legacy_defaults=True,
            )
        sample_rows: list[dict[str, str | None]] = []
        blocking_reasons: list[str] = []
        validate_row = self._bitget_row_validator(source, import_context)
        row_count = 0
        for row in reader:
            row_count += 1
            if validate_row is not None:
                blocking_reasons.extend(validate_row(row, row_count))
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
            blocking_reasons=blocking_reasons,
            sample_rows=sample_rows,
            can_import=len(missing) == 0 and row_count > 0 and not blocking_reasons,
            duplicate_batch_id=duplicate.batch_id if duplicate is not None else None,
            duplicate_batch_connection_id=duplicate.connection_id if duplicate is not None else None,
            connection_id=connection_id,
            import_context=import_context,
            duplicate_batch_import_context=(
                duplicate.import_context if duplicate is not None else None
            ),
            file_sha256=file_hash,
            import_fingerprint=file_hash,
        )

    def hash_text(self, content: str) -> str:
        return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _bitget_row_validator(self, source: str, import_context: dict[str, str] | None):
        timezone_name = (import_context or {}).get("export_timezone")
        if source.strip().lower() != "bitget" or not timezone_name:
            return None
        from steuerreport_v2.domain.import_context import timezone_from_name
        from steuerreport_v2.importers.raw_normalizer import RawNormalizer

        default_timezone = timezone_from_name(timezone_name)
        normalizer = RawNormalizer(self.store)
        profile = profile_for_source(source)

        def validate(row: dict[str, str | None], row_number: int) -> list[str]:
            if self._is_ignorable_row("bitget", row):
                return []
            normalized = {normalizer._normalize_key(key): value for key, value in row.items()}
            time_value = normalizer._first_value(normalized, list(profile.time_columns))
            if not time_value:
                return [f"Zeile {row_number}: Zeitstempel fehlt oder ist leer."]
            try:
                parsed = normalizer._parse_event_datetime_for_row(
                    str(time_value), profile, row, default_timezone=default_timezone,
                )
                header_timezone = normalizer._timezone_from_column_names(row)
                if header_timezone:
                    text = str(time_value).strip().replace("\xa0", " ").replace("Z", "+00:00").replace(" at ", " ")
                    for suffix in (" UTC", " GMT"):
                        if text.endswith(suffix):
                            text = text.removesuffix(suffix) + "+00:00"
                    try:
                        explicit = datetime.fromisoformat(text).utcoffset()
                    except ValueError:
                        explicit = None
                    if explicit is not None and explicit != header_timezone.utcoffset(None):
                        return [f"Zeile {row_number}: UTC-Offset im Zeitwert widerspricht dem Spaltenkopf; Originalexport pruefen."]
                    if explicit is None and import_context.get("timezone_basis") == "operator_selected":
                        selected = normalizer._parse_event_datetime(
                            str(time_value), profile, default_timezone=default_timezone,
                        )
                        if selected != parsed:
                            return [f"Zeile {row_number}: UTC-Offset im Spaltenkopf widerspricht der ausgewaehlten Exportzeitzone; Originalexport pruefen."]
            except (ValueError, OverflowError, TypeError) as exc:
                reason = str(exc)
                if reason == "bitget_local_time_is_ambiguous_in_selected_timezone":
                    return [f"Zeile {row_number}: lokale Uhrzeit ist in der ausgewaehlten Zeitzone mehrdeutig; Export mit Offset waehlen."]
                if reason == "bitget_local_time_does_not_exist_in_selected_timezone":
                    return [f"Zeile {row_number}: lokale Uhrzeit existiert in der ausgewaehlten Zeitzone nicht; Export mit Offset waehlen."]
                return [f"Zeile {row_number}: Zeitstempel ist ungueltig oder fuer die ausgewaehlte Zeitzone nicht interpretierbar."]
            if import_context.get("product_scope") == "isolated_margin":
                fee_raw = normalizer._first_value(normalized, list(profile.fee_quantity_columns))
                fee = normalizer._decimal_or_none(fee_raw)
                fee_asset = normalizer._first_value(normalized, list(profile.fee_asset_columns))
                if fee_raw and (fee is None or not fee.is_finite()):
                    return [f"Zeile {row_number}: Margin-Gebuehreintrag ist nicht als Zahl interpretierbar; Originalbeleg pruefen."]
                if fee is not None and fee != 0 and not fee_asset:
                    return [f"Zeile {row_number}: Margin-Gebuehr ohne belegte Gebuehrenwaehrung; Originalbeleg und separates Gebuehrenkonto pruefen."]
            return []

        return validate

    @classmethod
    def _dict_reader(cls, content: str, source: str | None = None) -> csv.DictReader:
        dialect = cls._dialect_for_text(content)
        if source is not None and source.strip().lower() == "bitget":
            return bitget_dict_reader(content, dialect)
        return csv.DictReader(
            StringIO(content),
            dialect=dialect,
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
