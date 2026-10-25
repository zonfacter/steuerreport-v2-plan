from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
from pathlib import Path
import re
import unicodedata

from pypdf import PdfReader

from steuerreport_v2.contracts.divorce_inheritance import (
    SparkasseStatementConnectorStatus,
    SparkasseStatementCryptoDebitEvidence,
    SparkasseStatementDocumentEvidence,
)


@dataclass(frozen=True)
class SparkasseCamtInvestmentEvidence:
    booking_date: date
    provider: str
    amount_eur: Decimal
    transaction_reference_sha256: str


class SparkasseStatementDocumentService:
    SUPPORTED_SUFFIXES = {".pdf"}
    MAX_FILE_BYTES = 50 * 1024 * 1024
    MAX_PDF_PAGES = 250
    MAX_EXTRACTED_TEXT_CHARS = 2_000_000
    _CANONICAL_STATEMENT_FILENAME = re.compile(
        r"^Konto_\d+-Auszug_\d{4}_\d+\.pdf$",
        re.IGNORECASE,
    )
    PROVIDER_MARKERS = {
        "trade republic": "trade_republic",
        "moonpay": "moonpay",
        "coinbase": "coinbase",
        "binance": "binance",
        "bifinity": "binance",
    }
    _TRANSACTION_START = re.compile(
        r"^\s*(?P<date>\d{2}\.\d{2}\.\d{4})\s+(?P<label>.+?)\s*$"
    )
    _SIGNED_MONEY = re.compile(
        r"(?<!\d)(?P<amount>-\s*[0-9][0-9. ]*,[0-9]{2})(?!\d)"
    )
    _BALANCE = re.compile(
        r"Kontostand\s+am\s+(?P<date>\d{2}\.\d{2}\.\d{4})[^\n]*?"
        r"(?P<amount>-?\s*[0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2})\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    _STATEMENT = re.compile(
        r"Kontoauszug\s+(?P<number>\d+)\s*/\s*(?P<year>\d{4})"
        r"(?P<duplicate>\s*\(Duplikat\))?",
        re.IGNORECASE,
    )
    _MERCHANT_TIME = re.compile(
        r"(?P<value>20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?)"
    )
    _GERMAN_DATE = re.compile(
        r"(?P<day>\d{1,2})\.\s+(?P<month>[A-Za-z\u00c4\u00d6\u00dc\u00e4\u00f6\u00fc]+)\s+"
        r"(?P<year>20\d{2})"
    )
    _MONTHS = {
        "januar": 1,
        "februar": 2,
        "marz": 3,
        "april": 4,
        "mai": 5,
        "juni": 6,
        "juli": 7,
        "august": 8,
        "september": 9,
        "oktober": 10,
        "november": 11,
        "dezember": 12,
    }

    def scan(
        self,
        root: Path,
        *,
        camt_investments: list[SparkasseCamtInvestmentEvidence],
    ) -> SparkasseStatementConnectorStatus:
        paths = self.statement_paths(root)
        manifest: list[dict[str, object]] = []
        documents_by_hash: dict[str, SparkasseStatementDocumentEvidence] = {}
        for path in paths:
            size_bytes = path.stat().st_size
            if size_bytes > self.MAX_FILE_BYTES:
                document_sha256 = self._file_sha256(path)
                manifest.append(
                    {
                        "document_sha256": document_sha256,
                        "filename_sha256": self._sha256(path.name.encode("utf-8")),
                        "size_bytes": size_bytes,
                    }
                )
                documents_by_hash.setdefault(
                    document_sha256,
                    self._error_document(
                        document_sha256=document_sha256,
                        size_bytes=size_bytes,
                        evidence_ref=(
                            f"sparkasse-statement:sha256:{document_sha256}"
                        ),
                        finding="PDF-Dateigroesse ueberschreitet das Sicherheitslimit.",
                    ),
                )
                continue
            content = path.read_bytes()
            document_sha256 = self._sha256(content)
            manifest.append(
                {
                    "document_sha256": document_sha256,
                    "filename_sha256": self._sha256(path.name.encode("utf-8")),
                    "size_bytes": len(content),
                }
            )
            if document_sha256 in documents_by_hash:
                continue
            documents_by_hash[document_sha256] = self._parse_document(
                content,
                document_sha256=document_sha256,
                camt_investments=camt_investments,
            )

        documents = sorted(
            documents_by_hash.values(),
            key=lambda item: (
                item.period_from or date.max,
                item.account_last4 or "",
                item.document_sha256,
            ),
        )
        parsed_documents = [
            item for item in documents if item.extraction_status == "parsed"
        ]
        parse_errors = [
            item for item in documents if item.extraction_status != "parsed"
        ]
        debits = [item for document in documents for item in document.crypto_debits]
        exact = sum(item.camt_match_status == "exact" for item in debits)
        ambiguous = sum(item.camt_match_status == "ambiguous" for item in debits)
        missing = sum(item.camt_match_status == "missing" for item in debits)
        period_from_values = [
            item.period_from for item in parsed_documents if item.period_from is not None
        ]
        period_to_values = [
            item.period_to for item in parsed_documents if item.period_to is not None
        ]
        status = (
            "missing"
            if not documents
            else "failed"
            if not parsed_documents
            else "partial"
            if parse_errors
            else "parsed"
        )
        findings = []
        if exact:
            findings.append(
                f"{exact} PDF-Kryptobuchung(en) sind exakt gegen CAMT.052 belegt und werden nicht doppelt als Investment gezaehlt."
            )
        if ambiguous:
            findings.append(
                f"{ambiguous} PDF-Kryptobuchung(en) besitzen mehrere gleichartige CAMT-Kandidaten."
            )
        if missing:
            findings.append(
                f"{missing} PDF-Kryptobuchung(en) besitzen im konfigurierten CAMT-Zeitraum keinen exakten Gegenbeleg."
            )
        if documents and not debits:
            findings.append(
                "Die Kontoauszuege enthalten keine automatisch erkannten Kryptoplattform-Abbuchungen."
            )
        return SparkasseStatementConnectorStatus(
            generated_at=datetime.now(timezone.utc),
            document_root=str(root),
            document_files_count=len(documents),
            document_manifest_sha256=(
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
            ),
            status=status,
            parsed_documents_count=len(parsed_documents),
            parse_error_count=len(parse_errors),
            period_from=min(period_from_values, default=None),
            period_to=max(period_to_values, default=None),
            crypto_debits_count=len(debits),
            crypto_debits_eur=sum(
                (item.amount_eur for item in debits), Decimal("0")
            ),
            exact_camt_matches_count=exact,
            ambiguous_camt_matches_count=ambiguous,
            missing_camt_matches_count=missing,
            duplicate_investment_flows_prevented_count=exact,
            documents=documents,
            findings=findings,
            methodology=(
                "Read-only Sparkassen-Kontoauszugbeleg. PDF-Text, Kontoauszugszeitraum, "
                "Salden und Kryptoplattform-Abbuchungen werden lokal extrahiert und per "
                "SHA-256 gebunden. Kontonummern werden nur als letzte vier Stellen und "
                "als Hash ausgegeben. Datum, Anbieter und EUR-Betrag werden gegen bereits "
                "strukturierte CAMT.052-Buchungen abgeglichen. Ein exakter PDF-Treffer ist "
                "ein zusaetzlicher Primaerbeleg, aber kein neuer Investmentfluss."
            ),
        )

    @classmethod
    def statement_paths(cls, root: Path) -> list[Path]:
        """Return actual account statements, with a legacy fallback for old folders."""
        if not root.is_dir():
            return []
        pdf_paths = sorted(
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in cls.SUPPORTED_SUFFIXES
        )
        canonical_paths = [
            path
            for path in pdf_paths
            if cls._CANONICAL_STATEMENT_FILENAME.fullmatch(path.name)
        ]
        return canonical_paths or pdf_paths

    def csv(self, report: SparkasseStatementConnectorStatus) -> str:
        output = io.StringIO()
        fieldnames = [
            "document_sha256",
            "account_last4",
            "ownership_scope",
            "statement_number",
            "statement_year",
            "period_from",
            "period_to",
            "opening_balance_eur",
            "closing_balance_eur",
            "booking_date",
            "provider",
            "amount_eur",
            "page_number",
            "camt_match_status",
            "camt_transaction_reference_sha256",
            "evidence_ref",
            "calculation_effect",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for document in report.documents:
            rows = document.crypto_debits or [None]
            for debit in rows:
                writer.writerow(
                    {
                        "document_sha256": document.document_sha256,
                        "account_last4": document.account_last4 or "",
                        "ownership_scope": document.ownership_scope,
                        "statement_number": document.statement_number or "",
                        "statement_year": document.statement_year or "",
                        "period_from": document.period_from or "",
                        "period_to": document.period_to or "",
                        "opening_balance_eur": document.opening_balance_eur
                        if document.opening_balance_eur is not None
                        else "",
                        "closing_balance_eur": document.closing_balance_eur
                        if document.closing_balance_eur is not None
                        else "",
                        "booking_date": debit.booking_date if debit else "",
                        "provider": debit.provider if debit else "",
                        "amount_eur": debit.amount_eur if debit else "",
                        "page_number": debit.page_number if debit else "",
                        "camt_match_status": debit.camt_match_status if debit else "",
                        "camt_transaction_reference_sha256": (
                            debit.camt_transaction_reference_sha256 or ""
                            if debit
                            else ""
                        ),
                        "evidence_ref": (
                            debit.evidence_ref if debit else document.evidence_ref
                        ),
                        "calculation_effect": (
                            debit.calculation_effect
                            if debit
                            else report.calculation_effect
                        ),
                    }
                )
        return output.getvalue()

    def _parse_document(
        self,
        content: bytes,
        *,
        document_sha256: str,
        camt_investments: list[SparkasseCamtInvestmentEvidence],
    ) -> SparkasseStatementDocumentEvidence:
        evidence_ref = f"sparkasse-statement:sha256:{document_sha256}"
        if (
            not content.startswith(b"%PDF-")
            or not content
            or len(content) > self.MAX_FILE_BYTES
        ):
            return self._error_document(
                document_sha256=document_sha256,
                size_bytes=len(content),
                evidence_ref=evidence_ref,
                finding="PDF-Dateisignatur oder Dateigroesse ist ungueltig.",
            )
        try:
            reader = PdfReader(io.BytesIO(content), strict=False)
            if reader.is_encrypted and reader.decrypt("") == 0:
                raise ValueError("encrypted")
            if len(reader.pages) > self.MAX_PDF_PAGES:
                raise ValueError("too_many_pages")
            page_texts = [page.extract_text() or "" for page in reader.pages]
        except Exception:
            return self._error_document(
                document_sha256=document_sha256,
                size_bytes=len(content),
                evidence_ref=evidence_ref,
                finding="PDF-Text konnte nicht extrahiert werden.",
            )
        text = "\n".join(page_texts)[: self.MAX_EXTRACTED_TEXT_CHARS]
        if not text.strip():
            return self._error_document(
                document_sha256=document_sha256,
                size_bytes=len(content),
                pages_count=len(reader.pages),
                evidence_ref=evidence_ref,
                finding="PDF besitzt keine maschinenlesbare Textebene; OCR waere erforderlich.",
                extraction_status="text_unavailable",
            )
        return self._parse_text(
            text,
            page_texts=page_texts,
            document_sha256=document_sha256,
            size_bytes=len(content),
            evidence_ref=evidence_ref,
            camt_investments=camt_investments,
        )

    def _parse_text(
        self,
        text: str,
        *,
        page_texts: list[str],
        document_sha256: str,
        size_bytes: int,
        evidence_ref: str,
        camt_investments: list[SparkasseCamtInvestmentEvidence],
    ) -> SparkasseStatementDocumentEvidence:
        statement_match = self._STATEMENT.search(text)
        balances = [
            (self._parse_date(match.group("date")), self._decimal(match.group("amount")))
            for match in self._BALANCE.finditer(text)
        ]
        balances = [
            (balance_date, amount)
            for balance_date, amount in balances
            if balance_date is not None and amount is not None
        ]
        opening_date, opening_balance = balances[0] if balances else (None, None)
        closing_date, closing_balance = balances[-1] if balances else (None, None)
        account_number, iban, ownership_scope = self._account_identity(text)
        crypto_debits: list[SparkasseStatementCryptoDebitEvidence] = []
        for page_number, page_text in enumerate(page_texts, 1):
            crypto_debits.extend(
                self._crypto_debits(
                    page_text,
                    page_number=page_number,
                    document_sha256=document_sha256,
                    camt_investments=camt_investments,
                )
            )
        findings: list[str] = []
        if not statement_match:
            findings.append("Kontoauszugsnummer konnte nicht extrahiert werden.")
        if opening_balance is None or closing_balance is None:
            findings.append("Anfangs- oder Endsaldo konnte nicht eindeutig extrahiert werden.")
        if not iban:
            findings.append("Kontofingerprint konnte nicht extrahiert werden.")
        exact_matches = sum(
            item.camt_match_status == "exact" for item in crypto_debits
        )
        period_from = (
            opening_date + timedelta(days=1) if opening_date is not None else None
        )
        if (
            period_from is not None
            and closing_date is not None
            and period_from > closing_date
        ):
            period_from = closing_date
        return SparkasseStatementDocumentEvidence(
            document_sha256=document_sha256,
            size_bytes=size_bytes,
            pages_count=len(page_texts),
            extraction_status="parsed",
            statement_number=(
                int(statement_match.group("number")) if statement_match else None
            ),
            statement_year=(
                int(statement_match.group("year")) if statement_match else None
            ),
            duplicate_statement=bool(
                statement_match and statement_match.group("duplicate")
            ),
            issue_date=self._issue_date(text),
            period_from=period_from,
            period_to=closing_date,
            account_last4=(account_number[-4:] if account_number else None),
            account_fingerprint_sha256=(
                self._sha256(iban.encode("ascii")) if iban else None
            ),
            ownership_scope=ownership_scope,
            opening_balance_eur=opening_balance,
            closing_balance_eur=closing_balance,
            crypto_debits_count=len(crypto_debits),
            crypto_debits_eur=sum(
                (item.amount_eur for item in crypto_debits), Decimal("0")
            ),
            exact_camt_matches_count=exact_matches,
            evidence_ref=evidence_ref,
            findings=findings,
            crypto_debits=crypto_debits,
        )

    def _crypto_debits(
        self,
        text: str,
        *,
        page_number: int,
        document_sha256: str,
        camt_investments: list[SparkasseCamtInvestmentEvidence],
    ) -> list[SparkasseStatementCryptoDebitEvidence]:
        blocks: list[tuple[str, list[str]]] = []
        current_date: str | None = None
        current_lines: list[str] = []
        for line in text.splitlines():
            match = self._TRANSACTION_START.match(line)
            if match:
                if current_date is not None:
                    blocks.append((current_date, current_lines))
                current_date = match.group("date")
                current_lines = [match.group("label")]
            elif current_date is not None:
                current_lines.append(line)
        if current_date is not None:
            blocks.append((current_date, current_lines))

        result: list[SparkasseStatementCryptoDebitEvidence] = []
        for raw_date, lines in blocks:
            block = "\n".join(lines)
            provider = self._provider(block)
            if provider is None:
                continue
            amounts = [
                self._decimal(match.group("amount"))
                for match in self._SIGNED_MONEY.finditer(block)
            ]
            negative_amounts = [
                abs(amount) for amount in amounts if amount is not None and amount < 0
            ]
            booking_date = self._parse_date(raw_date)
            if booking_date is None or not negative_amounts:
                continue
            amount = negative_amounts[-1]
            matches = [
                item
                for item in camt_investments
                if item.booking_date == booking_date
                and item.provider == provider
                and item.amount_eur == amount
            ]
            match_status = (
                "exact" if len(matches) == 1 else "ambiguous" if matches else "missing"
            )
            merchant_match = self._MERCHANT_TIME.search(block)
            merchant_time = (
                datetime.fromisoformat(merchant_match.group("value"))
                if merchant_match
                else None
            )
            result.append(
                SparkasseStatementCryptoDebitEvidence(
                    booking_date=booking_date,
                    provider=provider,
                    amount_eur=amount,
                    merchant_time=merchant_time,
                    page_number=page_number,
                    document_sha256=document_sha256,
                    evidence_ref=(
                        f"sparkasse-statement:sha256:{document_sha256}#page={page_number}"
                    ),
                    camt_match_status=match_status,
                    camt_transaction_reference_sha256=(
                        matches[0].transaction_reference_sha256
                        if len(matches) == 1
                        else None
                    ),
                )
            )
        return result

    @classmethod
    def _account_identity(cls, text: str) -> tuple[str | None, str | None, str]:
        account_number = None
        iban = None
        ownership_scope = "unknown"
        for line in text.splitlines():
            if "Konto-Nr." not in line:
                continue
            match = re.search(
                r"Konto-Nr\.\s*(?P<account>\d+),\s*(?P<iban>DE(?:\s*\d){20})",
                line,
                flags=re.IGNORECASE,
            )
            if match:
                account_number = match.group("account")
                iban = re.sub(r"\s+", "", match.group("iban")).upper()
            tail = line[match.end() :] if match else line
            if " und " in cls._canonical(tail):
                ownership_scope = "joint"
            elif match and tail.strip(" ,"):
                ownership_scope = "individual"
        return account_number, iban, ownership_scope

    @classmethod
    def _issue_date(cls, text: str) -> date | None:
        for match in cls._GERMAN_DATE.finditer(text[:5000]):
            month = cls._MONTHS.get(cls._canonical(match.group("month")))
            if month is None:
                continue
            try:
                return date(
                    int(match.group("year")), month, int(match.group("day"))
                )
            except ValueError:
                continue
        return None

    @classmethod
    def _provider(cls, value: str) -> str | None:
        canonical = cls._canonical(value)
        for marker, provider in cls.PROVIDER_MARKERS.items():
            if marker in canonical:
                return provider
        return None

    @staticmethod
    def _parse_date(value: str) -> date | None:
        try:
            return datetime.strptime(value.strip(), "%d.%m.%Y").date()
        except ValueError:
            return None

    @staticmethod
    def _decimal(value: str) -> Decimal | None:
        normalized = value.replace(" ", "").replace(".", "").replace(",", ".")
        try:
            return Decimal(normalized)
        except InvalidOperation:
            return None

    @staticmethod
    def _canonical(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value.casefold())
        return "".join(char for char in normalized if not unicodedata.combining(char))

    @staticmethod
    def _sha256(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _error_document(
        *,
        document_sha256: str,
        size_bytes: int,
        evidence_ref: str,
        finding: str,
        pages_count: int = 0,
        extraction_status: str = "parse_error",
    ) -> SparkasseStatementDocumentEvidence:
        return SparkasseStatementDocumentEvidence(
            document_sha256=document_sha256,
            size_bytes=size_bytes,
            pages_count=pages_count,
            extraction_status=extraction_status,
            evidence_ref=evidence_ref,
            findings=[finding],
        )
