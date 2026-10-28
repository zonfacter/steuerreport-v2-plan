from __future__ import annotations

import base64
import csv
import hashlib
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any

import pandas as pd

from steuerreport_v2.contracts.imports import CsvImportPreview, ImportBatch
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.source_profiles import (
    inspect_profile_columns,
    profile_for_source,
)


class FileRawImporter:
    def __init__(self, csv_importer: CsvRawImporter) -> None:
        self.csv_importer = csv_importer

    def preview_base64(
        self,
        source: str,
        filename: str,
        content_base64: str,
        sheet_name: str | None = None,
        mexc=None,
    ) -> CsvImportPreview:
        content = self._decode(content_base64)
        if source.strip().lower() == "mexc":
            from steuerreport_v2.importers.mexc_native import MexcNativeImporter
            return MexcNativeImporter(self.csv_importer.store).prepare(filename, content, sheet_name, mexc)[0]
        rows, columns, file_format, selected_sheet, sheet_names = self._rows_from_bytes(
            filename,
            content,
            sheet_name,
        )
        file_hash = self._file_hash(content, selected_sheet)
        duplicate = self.csv_importer.store.get_import_batch_by_file_hash(
            source,
            file_hash,
        )
        profile = profile_for_source(source)
        matched, missing = inspect_profile_columns(profile, columns)
        sample_rows = rows[:5]
        return CsvImportPreview(
            source=source,
            filename=filename,
            profile_label=profile.label,
            file_format=file_format,
            sheet_name=selected_sheet,
            sheet_names=sheet_names,
            row_count=len(rows),
            columns=columns,
            matched_columns=matched,
            missing_required_groups=missing,
            sample_rows=sample_rows,
            can_import=len(missing) == 0 and len(rows) > 0,
            duplicate_batch_id=duplicate.batch_id if duplicate is not None else None,
            file_sha256=self._file_hash(content, None),
            import_fingerprint=file_hash,
        )

    def import_base64(
        self,
        source: str,
        filename: str,
        content_base64: str,
        sheet_name: str | None = None,
        mexc=None,
    ) -> ImportBatch:
        content = self._decode(content_base64)
        if source.strip().lower() == "mexc":
            from steuerreport_v2.importers.mexc_native import MexcNativeImporter
            return MexcNativeImporter(self.csv_importer.store).import_file(filename, content, sheet_name, mexc)
        rows, _, _, selected_sheet, _ = self._rows_from_bytes(filename, content, sheet_name)
        file_hash = self._file_hash(content, selected_sheet)
        return self.csv_importer.import_rows(
            source=source,
            filename=filename,
            file_hash=file_hash,
            rows=rows,
        )

    def _decode(self, content_base64: str) -> bytes:
        return base64.b64decode(content_base64, validate=True)

    def _file_hash(self, content: bytes, sheet_name: str | None) -> str:
        digest = hashlib.sha256(content).hexdigest()
        if sheet_name is None:
            return "sha256:" + digest
        return "sha256:" + digest + "#sheet=" + sheet_name

    def _rows_from_bytes(
        self,
        filename: str,
        content: bytes,
        sheet_name: str | None = None,
    ) -> tuple[list[dict[str, str | None]], list[str], str, str | None, list[str]]:
        try:
            return self._parse_rows_from_bytes(filename, content, sheet_name)
        except Exception:
            raise ValueError("Datei konnte nicht gelesen werden. UTF-8-CSV oder eine gueltige Excel-Datei und das Tabellenblatt pruefen.") from None

    def _parse_rows_from_bytes(
        self, filename: str, content: bytes, sheet_name: str | None,
    ) -> tuple[list[dict[str, str | None]], list[str], str, str | None, list[str]]:
        suffix = Path(filename).suffix.lower()
        if suffix in {".xlsx", ".xls"}:
            return self._excel_rows(filename, content, sheet_name)
        text = content.decode("utf-8-sig")
        detected = self._csv_frame_with_detected_header(text)
        if detected is not None:
            detected = detected.where(pd.notna(detected), None)
            columns = [str(column) for column in detected.columns]
            rows = [
                self._stringify_row({str(key): value for key, value in row.items()})
                for row in detected.to_dict(orient="records")
            ]
            return rows, columns, "csv", None, []
        reader = csv.DictReader(
            StringIO(text),
            dialect=CsvRawImporter._dialect_for_text(text),
            skipinitialspace=True,
        )
        columns = list(reader.fieldnames or [])
        rows = [self._stringify_row(row) for row in reader]
        return rows, columns, "csv", None, []

    def _csv_frame_with_detected_header(self, text: str) -> pd.DataFrame | None:
        dialect = CsvRawImporter._dialect_for_text(text)
        raw = pd.read_csv(
            StringIO(text),
            header=None,
            dtype=object,
            sep=dialect.delimiter,
            skipinitialspace=True,
            engine="python",
        )
        header_index = self._detected_header_index(raw)
        if header_index is None:
            return None
        header = [str(value).strip() if pd.notna(value) else "" for value in raw.iloc[header_index].tolist()]
        data = raw.iloc[header_index + 1 :].copy()
        data.columns = header
        data = data[[column for column in data.columns if column]]
        data = data.dropna(how="all")
        return data

    def _excel_rows(
        self,
        filename: str,
        content: bytes,
        sheet_name: str | None = None,
    ) -> tuple[list[dict[str, str | None]], list[str], str, str | None, list[str]]:
        suffix = Path(filename).suffix.lower()
        engine = "openpyxl" if suffix == ".xlsx" else "xlrd"
        excel = pd.ExcelFile(BytesIO(content), engine=engine)
        sheet_names = [str(name) for name in excel.sheet_names]
        selected_sheet = sheet_name or sheet_names[0]
        if selected_sheet not in sheet_names:
            raise ValueError(f"unknown sheet_name: {selected_sheet}")
        detected = self._frame_with_detected_header(excel, selected_sheet)
        if detected is None and sheet_name is None:
            for candidate_sheet in sheet_names[1:]:
                candidate = self._frame_with_detected_header(excel, candidate_sheet)
                if candidate is not None:
                    selected_sheet = candidate_sheet
                    detected = candidate
                    break
        frame = pd.read_excel(excel, sheet_name=selected_sheet, dtype=object)
        if detected is not None:
            frame = detected
        frame = frame.where(pd.notna(frame), None)
        columns = [str(column) for column in frame.columns]
        rows = [
            self._stringify_row({str(key): value for key, value in row.items()})
            for row in frame.to_dict(orient="records")
        ]
        return rows, columns, suffix.removeprefix("."), selected_sheet, sheet_names

    def _frame_with_detected_header(
        self,
        excel: pd.ExcelFile,
        sheet_name: str,
    ) -> pd.DataFrame | None:
        raw = pd.read_excel(excel, sheet_name=sheet_name, header=None, dtype=object)
        embedded_csv = self._embedded_csv_frame(raw)
        if embedded_csv is not None:
            return embedded_csv
        header_index = None
        for index, row in raw.iterrows():
            values = {str(value).strip() for value in row.tolist() if pd.notna(value)}
            if self._looks_like_header(values):
                header_index = index
                break
        if header_index is None:
            return None
        header = [str(value).strip() if pd.notna(value) else "" for value in raw.iloc[header_index].tolist()]
        data = raw.iloc[header_index + 1 :].copy()
        data.columns = header
        data = data[[column for column in data.columns if column]]
        data = data.dropna(how="all")
        return data

    def _detected_header_index(self, raw: pd.DataFrame) -> int | None:
        for index, row in raw.iterrows():
            values = {str(value).strip() for value in row.tolist() if pd.notna(value)}
            if self._looks_like_header(values):
                return int(index)
        return None

    def _looks_like_header(self, values: set[str]) -> bool:
        strong_headers = {
            "User_ID",
            "Order Number",
            "Order no.",
            "Transaction hash(txid)",
            "Timestamp UTC+8 (Completion)",
            "Creation timestamp (+8 UTC)",
            "Timestamp UTC+8 (Created)",
            "Gateway Address",
            "Period Start (UTC)",
            "IOT Tokens",
            "MOBILE Tokens",
            "Created at",
            "Transaction ID",
            "Position change",
            "Deposit / Withdraw ($)",
            "Trade fee ($)",
        }
        generic_headers = {
            "Time",
            "Date",
            "Date(UTC)",
            "Date(UTC+2)",
            "Coin",
            "Market",
            "Asset",
            "Amount",
            "Type",
            "Price",
            "Receive Amount",
            "UTC_Time",
            "Operation",
            "Change",
            "Order Type",
            "Trading Pair",
            "Trading pair",
        }
        if values & strong_headers:
            return True
        return len(values & generic_headers) >= 2

    def _embedded_csv_frame(self, raw: pd.DataFrame) -> pd.DataFrame | None:
        if raw.empty or len(raw.columns) != 1:
            return None
        lines = [str(value).strip() for value in raw.iloc[:, 0].tolist() if pd.notna(value)]
        if not lines or "," not in lines[0]:
            return None
        header = {part.strip() for part in lines[0].split(",")}
        if not (header & {"Hotspot Name", "Date", "Mining Rewards HNT", "Sender", "Receiver"}):
            return None
        frame = pd.read_csv(StringIO("\n".join(lines)), dtype=object)
        return frame.where(pd.notna(frame), None)

    def _stringify_row(self, row: dict[str, Any]) -> dict[str, str | None]:
        result: dict[str, str | None] = {}
        for key, value in row.items():
            if value is None:
                result[str(key)] = None
            else:
                result[str(key)] = str(value)
        return result
