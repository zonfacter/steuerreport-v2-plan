from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path
import re
import unicodedata
import zipfile

from pypdf import PdfReader

from steuerreport_v2.contracts.divorce_inheritance import (
    TradeRepublicConnectorStatus,
    TradeRepublicDocumentEvidence,
)


class TradeRepublicDocumentService:
    OFFICIAL_API_GUIDE = (
        "https://assets.traderepublic.com/assets/files/TPP_API_Guide_v2.pdf"
    )
    OFFICIAL_STATEMENT_HELP = "https://support.traderepublic.com/de-de/267"
    SUPPORTED_SUFFIXES = {".pdf", ".csv", ".zip"}
    MAX_FILE_BYTES = 100 * 1024 * 1024
    MAX_ARCHIVE_MEMBER_BYTES = 25 * 1024 * 1024
    MAX_ARCHIVE_TOTAL_BYTES = 250 * 1024 * 1024
    MAX_ARCHIVE_MEMBERS = 2000
    MAX_PDF_PAGES = 1000
    MAX_EXTRACTED_TEXT_CHARS = 5_000_000

    _DATE_VALUE = r"(?:\d{2}\.\d{2}\.\d{4}|\d{4}-\d{2}-\d{2})"
    _MONEY = re.compile(
        r"(?:(?:EUR|\u20ac)\s*(?P<prefix>-?\s*[0-9][0-9. ,'\u00a0]*[,.][0-9]{2})"
        r"|(?P<suffix>-?\s*[0-9][0-9. ,'\u00a0]*[,.][0-9]{2})\s*(?:EUR|\u20ac))",
        re.IGNORECASE,
    )
    _TOTAL_LABELS = (
        "gesamtwert",
        "portfoliowert",
        "gesamtvermogen",
        "wert des portfolios",
        "total value",
        "net asset value",
    )
    _CASH_LABELS = (
        "cashbestand",
        "cash balance",
        "verrechnungskonto",
        "cash",
    )
    _SECURITIES_LABELS = (
        "depotwert",
        "wertpapierbestand",
        "wertpapiere",
        "securities value",
    )

    def scan(
        self,
        root: Path,
        *,
        end_asset_date: date,
        accepted_value_eur: Decimal | None = None,
        accepted_evidence_ref: str | None = None,
    ) -> TradeRepublicConnectorStatus:
        files = (
            sorted(
                path
                for path in root.rglob("*")
                if path.is_file() and path.suffix.lower() in self.SUPPORTED_SUFFIXES
            )
            if root.is_dir()
            else []
        )
        manifest: list[dict[str, object]] = []
        documents: list[TradeRepublicDocumentEvidence] = []
        for path in files:
            file_sha256 = self._file_sha256(path)
            manifest.append(
                {
                    "relative_path": str(path.relative_to(root)),
                    "size_bytes": path.stat().st_size,
                    "sha256": file_sha256,
                }
            )
            documents.extend(
                self._parse_path(
                    path,
                    file_sha256=file_sha256,
                    end_asset_date=end_asset_date,
                )
            )

        manifest_sha256 = (
            self._sha256(
                json.dumps(
                    manifest,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("utf-8")
            )
            if manifest
            else None
        )
        parsed_count = sum(
            item.extraction_status == "parsed" for item in documents
        )
        parse_error_count = sum(
            item.extraction_status in {"parse_error", "text_unavailable"}
            for item in documents
        )
        exact_documents = [
            item
            for item in documents
            if item.end_asset_date_match_source == "content"
        ]
        exact_candidates = [
            item
            for item in exact_documents
            if item.total_value_eur is not None
            and item.valuation_status == "exact_date_candidate"
        ]
        distinct_values = sorted(
            {item.total_value_eur for item in exact_candidates if item.total_value_eur is not None}
        )
        candidate = exact_candidates[0] if len(distinct_values) == 1 else None
        filename_candidates = any(
            item.end_asset_date_match_source == "filename" for item in documents
        )

        if accepted_value_eur is not None and accepted_evidence_ref:
            statement_status = "reviewed"
            review_status = "reviewed"
        elif len(distinct_values) > 1:
            statement_status = "ambiguous"
            review_status = "ambiguous"
        elif candidate is not None:
            statement_status = "exact_date_candidate"
            review_status = "ready"
        elif exact_documents or filename_candidates:
            statement_status = "candidate_present"
            review_status = "missing"
        else:
            statement_status = "missing"
            review_status = "missing"

        if not files:
            parse_status = "missing"
        elif parsed_count == 0:
            parse_status = "failed"
        elif parse_error_count:
            parse_status = "partial"
        else:
            parse_status = "parsed"

        if statement_status == "reviewed":
            note = (
                "Der Trade-Republic-Stichtagswert wurde durch eine Review Decision "
                "mit Belegreferenz freigegeben. Dokumente und Freigabe bleiben getrennt."
            )
        elif statement_status == "exact_date_candidate":
            note = (
                "Ein exakt datierter Depotwert wurde aus einem offiziellen Dokument "
                "extrahiert. Er wird erst nach ausdruecklicher Review-Freigabe verwendet."
            )
        elif statement_status == "ambiguous":
            note = (
                "Mehrere offizielle Dokumente liefern unterschiedliche Stichtagswerte. "
                "Vor einer Freigabe muss der richtige Beleg ausgewaehlt werden."
            )
        else:
            note = (
                "Die offizielle PSD2-API richtet sich an lizenzierte AISP/PISP und "
                "bestaetigt Cash-Konten, Salden und gebuchte Umsaetze. Eine direkte "
                "private Depot-API ist nicht ausgewiesen; V2 verarbeitet deshalb "
                "offizielle PDF-, CSV- und ZIP-Dokumente lokal und datensparsam."
            )

        return TradeRepublicConnectorStatus(
            official_api_guide_url=self.OFFICIAL_API_GUIDE,
            official_statement_help_url=self.OFFICIAL_STATEMENT_HELP,
            document_root=str(root),
            document_files_count=len(files),
            document_manifest_sha256=manifest_sha256,
            document_parse_status=parse_status,
            parsed_documents_count=parsed_count,
            parse_error_count=parse_error_count,
            exact_date_documents_count=len(exact_documents),
            valuation_candidates_count=len(exact_candidates),
            end_asset_statement_status=statement_status,
            valuation_review_status=review_status,
            valuation_review_ready=candidate is not None and accepted_value_eur is None,
            candidate_end_asset_value_eur=(candidate.total_value_eur if candidate else None),
            candidate_cash_value_eur=(candidate.cash_value_eur if candidate else None),
            candidate_securities_value_eur=(
                candidate.securities_value_eur if candidate else None
            ),
            candidate_document_sha256=(candidate.document_sha256 if candidate else None),
            candidate_evidence_ref=(candidate.evidence_ref if candidate else None),
            accepted_end_asset_value_eur=accepted_value_eur,
            accepted_evidence_ref=accepted_evidence_ref,
            documents=documents,
            required_documents=[
                "Kontoauszuege fuer den gesamten Zeitraum ab der ersten Einzahlung",
                "Einzelabrechnungen aller Kaeufe, Verkaeufe, Dividenden und Zinsen",
                f"Depotauszug sowie Cash-Bestand exakt zum {end_asset_date.strftime('%d.%m.%Y')}",
                "Jahressteuerbescheinigung und Verlustverrechnungstoepfe 2025/2026",
            ],
            note=note,
        )

    def _parse_path(
        self,
        path: Path,
        *,
        file_sha256: str,
        end_asset_date: date,
    ) -> list[TradeRepublicDocumentEvidence]:
        if path.stat().st_size > self.MAX_FILE_BYTES:
            return [
                self._error_evidence(
                    document_sha256=file_sha256,
                    source_kind=self._source_kind(path.suffix),
                    media_type=self._media_type(path.suffix),
                    end_asset_date_match_source=self._filename_date_match(
                        path.name, end_asset_date
                    ),
                    finding="Datei ueberschreitet das lokale Sicherheitslimit.",
                )
            ]
        try:
            content = path.read_bytes()
        except OSError:
            return [
                self._error_evidence(
                    document_sha256=file_sha256,
                    source_kind=self._source_kind(path.suffix),
                    media_type=self._media_type(path.suffix),
                    end_asset_date_match_source=self._filename_date_match(
                        path.name, end_asset_date
                    ),
                    finding="Datei konnte nicht gelesen werden.",
                )
            ]
        suffix = path.suffix.lower()
        if suffix == ".zip":
            return self._parse_archive(
                content,
                archive_sha256=file_sha256,
                end_asset_date=end_asset_date,
            )
        return [
            self._parse_blob(
                content,
                suffix=suffix,
                name=path.name,
                document_sha256=file_sha256,
                container_sha256=None,
                source_kind=self._source_kind(suffix),
                end_asset_date=end_asset_date,
            )
        ]

    def _parse_archive(
        self,
        content: bytes,
        *,
        archive_sha256: str,
        end_asset_date: date,
    ) -> list[TradeRepublicDocumentEvidence]:
        try:
            archive = zipfile.ZipFile(io.BytesIO(content))
        except (OSError, zipfile.BadZipFile):
            return [
                self._error_evidence(
                    document_sha256=archive_sha256,
                    source_kind="zip_archive",
                    media_type="application/zip",
                    finding="ZIP-Archiv ist nicht lesbar.",
                    document_type="archive",
                )
            ]
        infos = sorted(
            (item for item in archive.infolist() if not item.is_dir()),
            key=lambda item: item.filename,
        )
        if len(infos) > self.MAX_ARCHIVE_MEMBERS:
            return [
                self._error_evidence(
                    document_sha256=archive_sha256,
                    source_kind="zip_archive",
                    media_type="application/zip",
                    finding="ZIP-Archiv enthaelt zu viele Dateien.",
                    document_type="archive",
                )
            ]
        if sum(item.file_size for item in infos) > self.MAX_ARCHIVE_TOTAL_BYTES:
            return [
                self._error_evidence(
                    document_sha256=archive_sha256,
                    source_kind="zip_archive",
                    media_type="application/zip",
                    finding="ZIP-Archiv ueberschreitet das Entpacklimit.",
                    document_type="archive",
                )
            ]
        result: list[TradeRepublicDocumentEvidence] = []
        for info in infos:
            suffix = Path(info.filename).suffix.lower()
            if suffix not in {".pdf", ".csv"}:
                continue
            if info.flag_bits & 0x1 or info.file_size > self.MAX_ARCHIVE_MEMBER_BYTES:
                result.append(
                    self._error_evidence(
                        document_sha256=archive_sha256,
                        container_sha256=archive_sha256,
                        source_kind="zip_member",
                        media_type=self._media_type(suffix),
                        end_asset_date_match_source=self._filename_date_match(
                            info.filename, end_asset_date
                        ),
                        finding="ZIP-Mitglied ist verschluesselt oder ueberschreitet das Dateilimit.",
                    )
                )
                continue
            try:
                member_content = archive.read(info)
            except (OSError, RuntimeError, zipfile.BadZipFile):
                result.append(
                    self._error_evidence(
                        document_sha256=archive_sha256,
                        container_sha256=archive_sha256,
                        source_kind="zip_member",
                        media_type=self._media_type(suffix),
                        finding="ZIP-Mitglied konnte nicht gelesen werden.",
                    )
                )
                continue
            result.append(
                self._parse_blob(
                    member_content,
                    suffix=suffix,
                    name=info.filename,
                    document_sha256=self._sha256(member_content),
                    container_sha256=archive_sha256,
                    source_kind="zip_member",
                    end_asset_date=end_asset_date,
                )
            )
        if result:
            return result
        return [
            self._error_evidence(
                document_sha256=archive_sha256,
                source_kind="zip_archive",
                media_type="application/zip",
                finding="ZIP-Archiv enthaelt keine unterstuetzten PDF-/CSV-Dokumente.",
                document_type="archive",
                extraction_status="unsupported",
            )
        ]

    def _parse_blob(
        self,
        content: bytes,
        *,
        suffix: str,
        name: str,
        document_sha256: str,
        container_sha256: str | None,
        source_kind: str,
        end_asset_date: date,
    ) -> TradeRepublicDocumentEvidence:
        filename_match = self._filename_date_match(name, end_asset_date)
        if suffix == ".csv":
            return self._parse_csv(
                content,
                document_sha256=document_sha256,
                container_sha256=container_sha256,
                source_kind=source_kind,
                filename_match=filename_match,
                end_asset_date=end_asset_date,
            )
        try:
            reader = PdfReader(io.BytesIO(content), strict=False)
            if reader.is_encrypted and reader.decrypt("") == 0:
                raise ValueError("encrypted")
            pages = reader.pages[: self.MAX_PDF_PAGES]
            text = "\n".join((page.extract_text() or "") for page in pages)
        except Exception:
            return self._error_evidence(
                document_sha256=document_sha256,
                container_sha256=container_sha256,
                source_kind=source_kind,
                media_type="application/pdf",
                end_asset_date_match_source=filename_match,
                finding="PDF-Text konnte nicht extrahiert werden.",
            )
        if not text.strip():
            return self._error_evidence(
                document_sha256=document_sha256,
                container_sha256=container_sha256,
                source_kind=source_kind,
                media_type="application/pdf",
                end_asset_date_match_source=filename_match,
                finding="PDF enthaelt keinen maschinenlesbaren Text; OCR oder CSV erforderlich.",
                extraction_status="text_unavailable",
            )
        return self._parse_text(
            text[: self.MAX_EXTRACTED_TEXT_CHARS],
            document_sha256=document_sha256,
            container_sha256=container_sha256,
            source_kind=source_kind,
            media_type="application/pdf",
            filename_match=filename_match,
            end_asset_date=end_asset_date,
        )

    def _parse_csv(
        self,
        content: bytes,
        *,
        document_sha256: str,
        container_sha256: str | None,
        source_kind: str,
        filename_match: str,
        end_asset_date: date,
    ) -> TradeRepublicDocumentEvidence:
        text = self._decode_csv(content)
        if text is None:
            return self._error_evidence(
                document_sha256=document_sha256,
                container_sha256=container_sha256,
                source_kind=source_kind,
                media_type="text/csv",
                end_asset_date_match_source=filename_match,
                finding="CSV-Zeichensatz oder Tabellenstruktur ist nicht lesbar.",
            )
        try:
            sample = text[:8192]
            delimiter = csv.Sniffer().sniff(sample, delimiters=";,\t,").delimiter
        except csv.Error:
            delimiter = ";"
        try:
            rows = list(csv.DictReader(io.StringIO(text), delimiter=delimiter))
        except csv.Error:
            rows = []
        if not rows:
            return self._error_evidence(
                document_sha256=document_sha256,
                container_sha256=container_sha256,
                source_kind=source_kind,
                media_type="text/csv",
                end_asset_date_match_source=filename_match,
                finding="CSV enthaelt keine strukturierten Datenzeilen.",
            )

        date_aliases = {"valuationdate", "stichtag", "datum", "date", "stand"}
        total_aliases = {
            "totalvalueeur",
            "gesamtwert",
            "portfoliowert",
            "gesamtvermoegen",
            "netassetvalue",
        }
        cash_aliases = {"casheur", "cash", "cashbestand", "verrechnungskonto"}
        securities_aliases = {
            "securitiesvalueeur",
            "securities",
            "wertpapiere",
            "wertpapierbestand",
            "depotwert",
        }
        exact_values: list[tuple[Decimal | None, Decimal | None, Decimal | None]] = []
        row_dates: list[date] = []
        has_valuation_columns = False
        for row in rows:
            normalized = {self._header(key): value for key, value in row.items() if key}
            row_date = self._first_date(normalized, date_aliases)
            if row_date is not None:
                row_dates.append(row_date)
            total = self._first_amount(normalized, total_aliases)
            cash = self._first_amount(normalized, cash_aliases)
            securities = self._first_amount(normalized, securities_aliases)
            has_valuation_columns = has_valuation_columns or any(
                value is not None for value in (total, cash, securities)
            )
            if row_date == end_asset_date and any(
                value is not None for value in (total, cash, securities)
            ):
                if total is None and cash is not None and securities is not None:
                    total = cash + securities
                exact_values.append((total, cash, securities))

        totals = sorted({item[0] for item in exact_values if item[0] is not None})
        cash_values = sorted({item[1] for item in exact_values if item[1] is not None})
        securities_values = sorted(
            {item[2] for item in exact_values if item[2] is not None}
        )
        exact = bool(exact_values)
        ambiguous = len(totals) > 1
        total = totals[0] if len(totals) == 1 else None
        cash_value = cash_values[0] if len(cash_values) == 1 else None
        securities_value = (
            securities_values[0] if len(securities_values) == 1 else None
        )
        statement_date = (
            end_asset_date
            if exact
            else row_dates[0]
            if len(set(row_dates)) == 1
            else None
        )
        findings: list[str] = []
        if ambiguous:
            findings.append("CSV enthaelt mehrere unterschiedliche Gesamtwerte am Stichtag.")
        elif exact and total is None:
            findings.append("Stichtagszeile erkannt, aber kein eindeutiger Gesamtwert extrahiert.")
        elif total is not None:
            findings.append("Expliziter CSV-Stichtagswert extrahiert; Review bleibt erforderlich.")
        elif not has_valuation_columns:
            findings.append("Transaktionsexport erkannt; kein Depot-Stichtagswert enthalten.")

        return TradeRepublicDocumentEvidence(
            document_sha256=document_sha256,
            container_sha256=container_sha256,
            source_kind=source_kind,
            media_type="text/csv",
            document_type=(
                "portfolio_statement" if has_valuation_columns else "transaction_export"
            ),
            extraction_status="parsed",
            statement_date=statement_date,
            end_asset_date_match_source="content" if exact else filename_match,
            cash_value_eur=cash_value,
            securities_value_eur=securities_value,
            total_value_eur=total,
            valuation_status=(
                "ambiguous"
                if ambiguous
                else "exact_date_candidate"
                if exact and total is not None
                else "candidate"
                if exact or filename_match == "filename"
                else "not_applicable"
                if not has_valuation_columns
                else "missing"
            ),
            evidence_ref=f"trade-republic:sha256:{document_sha256}",
            findings=findings,
        )

    def _parse_text(
        self,
        text: str,
        *,
        document_sha256: str,
        container_sha256: str | None,
        source_kind: str,
        media_type: str,
        filename_match: str,
        end_asset_date: date,
    ) -> TradeRepublicDocumentEvidence:
        lines = [line.strip() for line in text.replace("\u00a0", " ").splitlines() if line.strip()]
        canonical = self._canonical("\n".join(lines))
        document_type = self._document_type(canonical)
        statement_date = self._labeled_date(canonical)
        period_from, period_to = self._period(canonical)
        exact = statement_date == end_asset_date
        total_values = self._labeled_amounts(lines, self._TOTAL_LABELS)
        cash_values = self._labeled_amounts(lines, self._CASH_LABELS)
        securities_values = self._labeled_amounts(lines, self._SECURITIES_LABELS)
        total = next(iter(total_values)) if len(total_values) == 1 else None
        cash_value = next(iter(cash_values)) if len(cash_values) == 1 else None
        securities_value = (
            next(iter(securities_values)) if len(securities_values) == 1 else None
        )
        if total is None and cash_value is not None and securities_value is not None:
            total = cash_value + securities_value
        ambiguous = len(total_values) > 1 or (
            len(total_values) == 0
            and (len(cash_values) > 1 or len(securities_values) > 1)
        )
        findings: list[str] = []
        if ambiguous:
            findings.append("Mehrere unterschiedliche Depotwerte im Dokument erkannt.")
        elif exact and total is not None:
            findings.append("Exakter PDF-Stichtagswert extrahiert; Review bleibt erforderlich.")
        elif exact:
            findings.append("Exakter Stichtag erkannt, aber kein eindeutiger Gesamtwert extrahiert.")
        elif filename_match == "filename":
            findings.append("Stichtag steht nur im Dateinamen und ist inhaltlich noch nicht belegt.")
        elif document_type not in {"portfolio_statement", "account_statement"}:
            findings.append("Dokument enthaelt keinen Depot-Stichtagswert.")

        return TradeRepublicDocumentEvidence(
            document_sha256=document_sha256,
            container_sha256=container_sha256,
            source_kind=source_kind,
            media_type=media_type,
            document_type=document_type,
            extraction_status="parsed",
            statement_date=statement_date,
            period_from=period_from,
            period_to=period_to,
            end_asset_date_match_source="content" if exact else filename_match,
            cash_value_eur=cash_value,
            securities_value_eur=securities_value,
            total_value_eur=total,
            valuation_status=(
                "ambiguous"
                if ambiguous
                else "exact_date_candidate"
                if exact and total is not None
                else "candidate"
                if exact or filename_match == "filename"
                else "not_applicable"
                if document_type not in {"portfolio_statement", "account_statement"}
                else "missing"
            ),
            evidence_ref=f"trade-republic:sha256:{document_sha256}",
            findings=findings,
        )

    def _labeled_amounts(
        self,
        lines: list[str],
        labels: tuple[str, ...],
    ) -> set[Decimal]:
        result: set[Decimal] = set()
        for index, line in enumerate(lines):
            canonical_line = self._canonical(line)
            if not any(label in canonical_line for label in labels):
                continue
            matches = list(self._MONEY.finditer(line))
            if not matches and index + 1 < len(lines):
                matches = list(self._MONEY.finditer(lines[index + 1]))
            for match in matches:
                value = self._parse_amount(match.group("prefix") or match.group("suffix"))
                if value is not None:
                    result.add(value)
        return result

    @classmethod
    def _labeled_date(cls, canonical: str) -> date | None:
        patterns = (
            rf"(?:stichtag|bewertungstag|stand(?: zum)?|depotauszug (?:zum|per))\s*:?\s*({cls._DATE_VALUE})",
            rf"(?:portfolio|depot)\s+(?:zum|per)\s+({cls._DATE_VALUE})",
        )
        values: list[date] = []
        for pattern in patterns:
            for raw in re.findall(pattern, canonical, flags=re.IGNORECASE):
                parsed = cls._parse_date(raw)
                if parsed is not None:
                    values.append(parsed)
        return values[0] if values and len(set(values)) == 1 else None

    @classmethod
    def _period(cls, canonical: str) -> tuple[date | None, date | None]:
        match = re.search(
            rf"(?:zeitraum|periode)?\s*(?:von)?\s*({cls._DATE_VALUE})\s*(?:bis|-)\s*({cls._DATE_VALUE})",
            canonical,
            flags=re.IGNORECASE,
        )
        if not match:
            return None, None
        return cls._parse_date(match.group(1)), cls._parse_date(match.group(2))

    @staticmethod
    def _document_type(canonical: str) -> str:
        if any(
            marker in canonical
            for marker in (
                "depotauszug",
                "depotubersicht",
                "portfolioubersicht",
                "portfolio overview",
            )
        ):
            return "portfolio_statement"
        if "kontoauszug" in canonical or "account statement" in canonical:
            return "account_statement"
        if "steuerbescheinigung" in canonical or "tax certificate" in canonical:
            return "tax_statement"
        if any(
            marker in canonical
            for marker in ("wertpapierabrechnung", "abrechnung", "trade confirmation")
        ):
            return "transaction_statement"
        return "unknown"

    @classmethod
    def _filename_date_match(cls, name: str, end_asset_date: date) -> str:
        markers = {
            end_asset_date.isoformat(),
            end_asset_date.strftime("%Y%m%d"),
            end_asset_date.strftime("%d.%m.%Y"),
        }
        return "filename" if any(marker in name for marker in markers) else "none"

    @staticmethod
    def _source_kind(suffix: str) -> str:
        return "csv" if suffix.lower() == ".csv" else "pdf" if suffix.lower() == ".pdf" else "zip_archive"

    @staticmethod
    def _media_type(suffix: str) -> str:
        return {
            ".pdf": "application/pdf",
            ".csv": "text/csv",
            ".zip": "application/zip",
        }.get(suffix.lower(), "application/octet-stream")

    @staticmethod
    def _decode_csv(content: bytes) -> str | None:
        for encoding in ("utf-8-sig", "utf-16", "cp1252"):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                continue
        return None

    @classmethod
    def _first_date(cls, row: dict[str, str | None], aliases: set[str]) -> date | None:
        for key in aliases:
            parsed = cls._parse_date(row.get(key))
            if parsed is not None:
                return parsed
        return None

    @classmethod
    def _first_amount(
        cls,
        row: dict[str, str | None],
        aliases: set[str],
    ) -> Decimal | None:
        for key in aliases:
            value = cls._parse_amount(row.get(key))
            if value is not None:
                return value
        return None

    @staticmethod
    def _header(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", TradeRepublicDocumentService._canonical(value))

    @staticmethod
    def _canonical(value: str) -> str:
        return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()

    @staticmethod
    def _parse_date(value: str | None) -> date | None:
        if not value:
            return None
        text = str(value).strip()
        for pattern in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
            try:
                return datetime.strptime(text, pattern).date()
            except ValueError:
                continue
        return None

    @staticmethod
    def _parse_amount(value: str | None) -> Decimal | None:
        if value is None:
            return None
        text = re.sub(r"[^0-9,.-]", "", str(value)).strip()
        if not text or text in {"-", ".", ","}:
            return None
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        elif "," in text:
            text = text.replace(".", "").replace(",", ".")
        try:
            return Decimal(text)
        except InvalidOperation:
            return None

    @staticmethod
    def _error_evidence(
        *,
        document_sha256: str,
        source_kind: str,
        media_type: str,
        finding: str,
        container_sha256: str | None = None,
        document_type: str = "unknown",
        end_asset_date_match_source: str = "none",
        extraction_status: str = "parse_error",
    ) -> TradeRepublicDocumentEvidence:
        return TradeRepublicDocumentEvidence(
            document_sha256=document_sha256,
            container_sha256=container_sha256,
            source_kind=source_kind,
            media_type=media_type,
            document_type=document_type,
            extraction_status=extraction_status,
            end_asset_date_match_source=end_asset_date_match_source,
            valuation_status=(
                "candidate" if end_asset_date_match_source == "filename" else "missing"
            ),
            evidence_ref=f"trade-republic:sha256:{document_sha256}",
            findings=[finding],
        )

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _sha256(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()
