from __future__ import annotations

import base64
import time
import warnings
from pathlib import Path

from steuerreport_v2.contracts.coverage import ImportCoverageRow, ImportCoverageSummary
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.file_raw_importer import FileRawImporter

SUPPORTED_SUFFIXES = {".csv", ".xlsx", ".xls"}


class ImportCoverageService:
    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def scan(
        self,
        root_path: str,
        limit: int = 80,
        max_seconds: float = 8.0,
    ) -> ImportCoverageSummary:
        started = time.perf_counter()
        root = Path(root_path)
        rows: list[ImportCoverageRow] = []
        if not root.exists():
            return ImportCoverageSummary(
                root_path=str(root),
                files_total=0,
                files_scanned=0,
                importable=0,
                blocked=0,
                scan_truncated=False,
                scan_seconds=round(time.perf_counter() - started, 3),
                rows=[
                    ImportCoverageRow(
                        file_path=str(root),
                        source="unknown",
                        file_format="missing",
                        row_count=0,
                        can_import=False,
                        missing_required_groups=[],
                        columns=[],
                        error="Pfad existiert nicht",
                    )
                ],
            )

        files = [
            path
            for path in sorted(root.rglob("*"))
            if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
        ]
        for path in files[:limit]:
            if rows and time.perf_counter() - started >= max_seconds:
                break
            rows.append(self._preview_file(path))
        return ImportCoverageSummary(
            root_path=str(root),
            files_total=len(files),
            files_scanned=len(rows),
            importable=sum(1 for row in rows if row.can_import),
            blocked=sum(1 for row in rows if not row.can_import),
            scan_truncated=len(rows) < min(len(files), limit),
            scan_seconds=round(time.perf_counter() - started, 3),
            rows=rows,
        )

    def _preview_file(self, path: Path) -> ImportCoverageRow:
        source = self._guess_source(path)
        try:
            content_base64 = base64.b64encode(path.read_bytes()).decode("ascii")
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                preview = FileRawImporter(CsvRawImporter(self.store)).preview_base64(
                    source=source,
                    filename=path.name,
                    content_base64=content_base64,
                )
            return ImportCoverageRow(
                file_path=str(path),
                source=source,
                file_format=preview.file_format,
                row_count=preview.row_count,
                can_import=preview.can_import,
                missing_required_groups=preview.missing_required_groups,
                columns=preview.columns,
            )
        except Exception as exc:
            return ImportCoverageRow(
                file_path=str(path),
                source=source,
                file_format=path.suffix.lower().removeprefix("."),
                row_count=0,
                can_import=False,
                missing_required_groups=[],
                columns=[],
                error=str(exc),
            )

    def _guess_source(self, path: Path) -> str:
        lower = str(path).lower()
        if "pionex" in lower:
            return "pionex"
        if "binance" in lower:
            return "binance"
        if "bitget" in lower:
            return "bitget"
        if "blockpit" in lower:
            return "blockpit"
        if "helium" in lower or "fairspot" in lower:
            return "helium"
        return "manual-csv"
