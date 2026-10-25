from __future__ import annotations

from steuerreport_v2.paths import configured_import_path

import re
from pathlib import Path

from steuerreport_v2.contracts.parser_preflight import (
    ParserPreflightFile,
    ParserPreflightReport,
)
from steuerreport_v2.domain.import_policy import ImportPolicyService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.file_raw_importer import FileRawImporter


class ParserPreflightService:
    def __init__(self, csv_importer: CsvRawImporter) -> None:
        self.csv_importer = csv_importer
        self.file_importer = FileRawImporter(csv_importer)

    def inspect(
        self,
        root_path: str = str(configured_import_path("import_root")),
        limit: int = 20,
    ) -> ParserPreflightReport:
        audit = ImportPolicyService().audit(root_path)
        parser_needed = [
            decision for decision in audit.decisions if decision.category == "parser_needed"
        ]
        files = [
            self._inspect_file(Path(decision.file_path), decision)
            for decision in parser_needed[: max(limit, 0)]
        ]
        return ParserPreflightReport(
            root_path=audit.root_path,
            parser_needed=len(parser_needed),
            inspected=len(files),
            files=files,
        )

    def _inspect_file(self, path: Path, decision: object) -> ParserPreflightFile:
        warnings: list[str] = []
        file_format = None
        sheet_name = None
        sheet_names: list[str] = []
        row_count = None
        columns: list[str] = []
        sample_rows: list[dict[str, str | None]] = []
        if not path.exists():
            warnings.append("Datei existiert nicht.")
        elif not path.is_file():
            warnings.append("Pfad ist keine Datei.")
        else:
            try:
                content = path.read_bytes()
                rows, columns, file_format, sheet_name, sheet_names = (
                    self.file_importer._rows_from_bytes(path.name, content)
                )
                row_count = len(rows)
                sample_rows = self._redact_sample_rows(rows[:5])
                if row_count == 0:
                    warnings.append("Datei enthaelt keine Datenzeilen.")
                if not columns:
                    warnings.append("Keine Spalten erkannt.")
                if self._looks_like_no_data_export(rows):
                    warnings.append("Export enthaelt nach erkanntem Header keine Nutzdaten.")
            except Exception as exc:
                warnings.append(f"Preflight konnte Datei nicht lesen: {exc}")

        relative_path = str(getattr(decision, "relative_path"))
        return ParserPreflightFile(
            file_path=str(path),
            relative_path=relative_path,
            category=str(getattr(decision, "category")),
            action=str(getattr(decision, "action")),
            reason=str(getattr(decision, "reason")),
            parser_kind=self._parser_kind(relative_path),
            file_format=file_format,
            sheet_name=sheet_name,
            sheet_names=sheet_names,
            row_count=row_count,
            columns=columns,
            sample_rows=sample_rows,
            warnings=warnings,
            can_realimport=False,
        )

    def _parser_kind(self, relative_path: str) -> str:
        lowered = relative_path.lower()
        if "c2c" in lowered:
            return "binance_c2c"
        if "export-solscan" in lowered:
            return "solscan"
        if lowered.startswith("jup/"):
            return "jup_perps"
        if "wallet." in lowered and "month" in lowered:
            return "wallet_month"
        return "unknown_parser_needed"

    def _redact_sample_rows(
        self,
        rows: list[dict[str, str | None]],
    ) -> list[dict[str, str | None]]:
        return [self._redact_row(row) for row in rows]

    def _redact_row(self, row: dict[str, str | None]) -> dict[str, str | None]:
        result = dict(row)
        keys = list(result)
        sensitive_labels = {"name", "email", "e-mail", "address", "user id", "uid"}
        for index, key in enumerate(keys):
            value = result[key]
            if value is None:
                continue
            stripped = str(value).strip()
            if self._looks_sensitive_value(stripped):
                result[key] = "[redacted]"
                continue
            if stripped.lower() in sensitive_labels and index + 1 < len(keys):
                next_key = keys[index + 1]
                if result.get(next_key):
                    result[next_key] = "[redacted]"
        return result

    def _looks_sensitive_value(self, value: str) -> bool:
        if re.search(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            return True
        return False

    def _looks_like_no_data_export(self, rows: list[dict[str, str | None]]) -> bool:
        return any(
            str(value or "").strip().lower() == "no data matches the criteria."
            for row in rows[:5]
            for value in row.values()
        )
