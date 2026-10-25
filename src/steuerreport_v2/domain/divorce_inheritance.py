from __future__ import annotations

from collections import defaultdict
import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import os
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from uuid import uuid4
from zoneinfo import ZoneInfo

from steuerreport_v2.contracts.divorce_inheritance import (
    BankCamtUploadResult,
    CoinbaseConnectorStatus,
    CoinbaseValuationAssetEvidence,
    CoinbaseValuationDecisionRequest,
    CoinbaseValuationDecisionResult,
    DivorceInheritanceCreditEvidence,
    DivorceInheritanceInvestmentFlow,
    DivorceInheritanceOriginReport,
    DivorceInheritanceProviderSummary,
    InheritanceBankCreditCandidate,
    InheritanceBankCreditCandidateReport,
    InheritanceBankCreditDecisionRequest,
    InheritanceBankCreditDecisionResult,
    InheritanceDocumentConnectorStatus,
    InheritanceDocumentCreditDecisionRequest,
    InheritanceDocumentCreditDecisionResult,
    InheritanceDocumentDecisionRequest,
    InheritanceDocumentDecisionResult,
    InheritanceDocumentUploadResult,
    SparkasseStatementConnectorStatus,
    TradeRepublicConnectorStatus,
    TradeRepublicDocumentUploadResult,
    TradeRepublicValuationDecisionRequest,
    TradeRepublicValuationDecisionResult,
)
from steuerreport_v2.contracts.review import ReviewDecision, ReviewDecisionCreate
from steuerreport_v2.contracts.portfolio import PortfolioAsOfSnapshot
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.inheritance_documents import InheritanceDocumentService
from steuerreport_v2.domain.bank_camt_documents import BankCamtDocumentService
from steuerreport_v2.domain.secrets import resolve_secret_value
from steuerreport_v2.domain.sparkasse_statements import (
    SparkasseCamtInvestmentEvidence,
    SparkasseStatementDocumentService,
)
from steuerreport_v2.domain.trade_republic_documents import (
    TradeRepublicDocumentService,
)


@dataclass(frozen=True)
class _BankEntry:
    booking_date: date
    amount_eur: Decimal
    direction: str
    provider: str | None
    is_inheritance_credit: bool
    reference_sha256: str
    source_file_sha256: str


@dataclass(frozen=True)
class _BankBalance:
    balance_date: date
    balance_eur: Decimal
    balance_type: str


@dataclass(frozen=True)
class _ExternalValuation:
    value_eur: Decimal
    evidence_ref: str | None


class DivorceInheritanceOriginService:
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    DEFAULT_DB_PATH = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
    DEFAULT_BANK_CAMT_ROOT = Path("/workspace/steuerreport/usertransfer/Sparkasse")
    DEFAULT_SPARKASSE_STATEMENT_DISCOVERY_ROOT = Path(
        "/workspace/steuerreport/usertransfer"
    )
    DEFAULT_TRADE_REPUBLIC_DOCUMENT_ROOT = Path(
        "/workspace/steuerreport/usertransfer/TradeRepublic"
    )
    DEFAULT_INHERITANCE_DOCUMENT_ROOT = Path(
        "/workspace/steuerreport/usertransfer/Inheritance"
    )
    DEFAULT_SEPARATION_DATE = date(2025, 6, 13)
    DEFAULT_END_ASSET_DATE = date(2026, 7, 24)
    MAX_TRADE_REPUBLIC_DOCUMENT_BYTES = TradeRepublicDocumentService.MAX_FILE_BYTES
    MAX_INHERITANCE_DOCUMENT_BYTES = InheritanceDocumentService.MAX_FILE_BYTES
    MAX_BANK_CAMT_UPLOAD_BYTES = BankCamtDocumentService.MAX_UPLOAD_BYTES
    OFFICIAL_TRADE_REPUBLIC_API_GUIDE = (
        "https://assets.traderepublic.com/assets/files/TPP_API_Guide_v2.pdf"
    )
    OFFICIAL_TRADE_REPUBLIC_STATEMENT_HELP = (
        "https://support.traderepublic.com/de-de/267"
    )
    OFFICIAL_COINBASE_ACCOUNTS_API = (
        "https://docs.cdp.coinbase.com/coinbase-business/track-apis/accounts"
    )
    OFFICIAL_COINBASE_TRANSACTIONS_API = (
        "https://docs.cdp.coinbase.com/coinbase-business/track-apis/transactions"
    )
    OFFICIAL_COINBASE_STATEMENTS_HELP = (
        "https://help.coinbase.com/en-in/coinbase/taxes/tools/statements"
    )
    PROVIDER_LABELS = {
        "binance": "Binance",
        "moonpay": "MoonPay",
        "coinbase": "Coinbase",
        "trade_republic": "Trade Republic",
    }
    PROVIDER_FLOW_IDS = {
        "binance": "binance_fiat_deposits",
        "moonpay": "moonpay_apple_pay_onramp",
        "coinbase": "coinbase_bank_transfers",
        "trade_republic": "trade_republic_bank_transfers",
    }

    def __init__(
        self,
        store: DuckDbStore,
        *,
        bank_camt_dir: Path | None = None,
        sparkasse_statement_root: Path | None = None,
        trade_republic_document_root: Path | None = None,
        inheritance_document_root: Path | None = None,
        inheritance_document_path: Path | None = None,
    ) -> None:
        self.store = store
        use_instance_defaults = (
            self.store.path.resolve() == self.DEFAULT_DB_PATH.resolve()
        )
        configured_bank = os.getenv("STEUERREPORT_SPARKASSE_CAMT_DIR")
        if bank_camt_dir is not None:
            self.bank_camt_dir = bank_camt_dir
        elif configured_bank:
            self.bank_camt_dir = Path(configured_bank)
        elif use_instance_defaults:
            self.bank_camt_dir = (
                self._discover_bank_camt_dir()
                or self.DEFAULT_BANK_CAMT_ROOT / "camt52v8Booked-managed"
            )
        else:
            self.bank_camt_dir = self.store.path.parent / "Sparkasse"
        configured_statements = os.getenv("STEUERREPORT_SPARKASSE_STATEMENT_DIR")
        self.sparkasse_statement_root = sparkasse_statement_root or (
            Path(configured_statements)
            if configured_statements
            else self._discover_sparkasse_statement_dir()
            if use_instance_defaults
            else self.store.path.parent / "SparkasseStatements"
        )
        configured_trade_republic = os.getenv(
            "STEUERREPORT_TRADE_REPUBLIC_DOCUMENT_ROOT"
        )
        self.trade_republic_document_root = trade_republic_document_root or (
            Path(configured_trade_republic)
            if configured_trade_republic
            else self.DEFAULT_TRADE_REPUBLIC_DOCUMENT_ROOT
            if use_instance_defaults
            else self.store.path.parent / "TradeRepublic"
        )
        configured_inheritance_root = os.getenv(
            "STEUERREPORT_INHERITANCE_DOCUMENT_ROOT"
        )
        self.inheritance_document_root = inheritance_document_root or (
            Path(configured_inheritance_root)
            if configured_inheritance_root
            else self.DEFAULT_INHERITANCE_DOCUMENT_ROOT
            if use_instance_defaults
            else self.store.path.parent / "Inheritance"
        )
        configured_inheritance_document = os.getenv(
            "STEUERREPORT_INHERITANCE_DOCUMENT_PATH"
        )
        self.inheritance_document_path = inheritance_document_path or (
            Path(configured_inheritance_document)
            if configured_inheritance_document
            else None
        )

    def report(
        self,
        *,
        separation_date: date = DEFAULT_SEPARATION_DATE,
        end_asset_date: date = DEFAULT_END_ASSET_DATE,
        valuation_portfolio: PortfolioAsOfSnapshot | None = None,
    ) -> DivorceInheritanceOriginReport:
        generated_at = datetime.now(timezone.utc)
        entries, balances, bank_files, bank_manifest_sha256, parse_errors = (
            self._load_bank_data()
        )
        sparkasse_statement_connector = self._sparkasse_statement_connector(entries)
        relevant_entries = [
            item
            for item in entries
            if separation_date < item.booking_date <= end_asset_date
        ]
        bank_credit_decisions = self._inheritance_bank_credit_decisions()
        bank_inheritance_credits = [
            self._credit_evidence(
                item,
                bank_credit_decisions.get(item.reference_sha256),
            )
            for item in relevant_entries
            if item.direction == "CRDT"
            and (
                item.is_inheritance_credit
                or item.reference_sha256 in bank_credit_decisions
            )
        ]
        document_inheritance_credits = self._document_inheritance_credits(
            end_asset_date=end_asset_date
        )
        inheritance_credits = sorted(
            [*bank_inheritance_credits, *document_inheritance_credits],
            key=lambda item: (item.booking_date, item.transaction_reference_sha256),
        )
        inheritance_credit = self._primary_credit_evidence(inheritance_credits)
        credit_amount = sum(
            (item.amount_eur for item in inheritance_credits),
            Decimal("0"),
        )
        bank_investments = [
            item
            for item in relevant_entries
            if item.direction == "DBIT" and item.provider is not None
        ]
        platform_only_binance = self._platform_only_binance(
            bank_investments,
            separation_date=separation_date,
            end_asset_date=end_asset_date,
        )
        decisions = self._capital_origin_decisions()
        flows = self._investment_flows(
            bank_investments,
            platform_only_binance,
            decisions,
        )
        coinbase_connector = self._coinbase_connector(
            end_asset_date,
            valuation_portfolio=valuation_portfolio,
        )
        provider_summaries = self._provider_summaries(
            flows,
            decisions,
            end_asset_date,
            coinbase_connector=coinbase_connector,
        )
        bank_total = sum(
            (item.amount_eur for item in flows if item.evidence_source == "bank_camt"),
            Decimal("0"),
        )
        platform_only_total = sum(
            (
                item.amount_eur
                for item in flows
                if item.evidence_source == "platform_ledger"
            ),
            Decimal("0"),
        )
        total_investment = bank_total + platform_only_total
        crypto_tracked = sum(
            (
                item.identified_investment_eur
                for item in provider_summaries
                if item.provider in {"binance", "moonpay"}
            ),
            Decimal("0"),
        )
        external_investment = sum(
            (
                item.identified_investment_eur
                for item in provider_summaries
                if item.provider in {"coinbase", "trade_republic"}
            ),
            Decimal("0"),
        )
        external_values = [
            item.end_asset_value_eur
            for item in provider_summaries
            if item.provider in {"coinbase", "trade_republic"}
            and item.identified_investment_eur > 0
        ]
        external_end_value = (
            sum((value for value in external_values if value is not None), Decimal("0"))
            if external_values and all(value is not None for value in external_values)
            else None
        )
        bank_dates = [item.balance_date for item in balances] or [
            item.booking_date for item in entries
        ]
        coverage_intervals: list[tuple[date, date]] = []
        if bank_dates:
            coverage_intervals.append((min(bank_dates), max(bank_dates)))
        if sparkasse_statement_connector.status in {"parsed", "partial"}:
            coverage_intervals.extend(
                (document.period_from, document.period_to)
                for document in sparkasse_statement_connector.documents
                if document.extraction_status == "parsed"
                and document.period_from is not None
                and document.period_to is not None
            )
        bank_statement_status, statement_from, statement_to = (
            self._bank_statement_coverage(
                coverage_intervals,
                required_from=separation_date,
                required_to=end_asset_date,
            )
        )
        opening_balance = self._opening_balance(balances)
        closing_balance = self._closing_balance(balances, end_asset_date)
        minimum_after_inheritance = self._minimum_balance_after_credit(
            balances,
            self._first_bank_inheritance_credit_date(bank_inheritance_credits),
            end_asset_date,
        )
        formal_inheritance_connector = self._formal_inheritance_connector()
        formal_document_sha256 = formal_inheritance_connector.accepted_document_sha256
        formal_document_status = "documented" if formal_document_sha256 else "missing"
        positive_providers = {
            item.provider
            for item in provider_summaries
            if item.identified_investment_eur > 0
        }
        documented_providers = {
            item.provider
            for item in provider_summaries
            if item.capital_origin_evidence_status == "documented"
        }
        user_declaration_status = (
            "recorded"
            if positive_providers and positive_providers <= documented_providers
            else "missing"
        )
        trade_republic_connector = self._trade_republic_connector(end_asset_date)
        missing_external_valuations = [
            item.provider
            for item in provider_summaries
            if item.identified_investment_eur > 0
            and item.provider in {"coinbase", "trade_republic"}
            and item.end_asset_valuation_status != "covered"
        ]
        headroom = credit_amount - total_investment if inheritance_credits else None
        strict_ready = bool(
            bank_statement_status == "complete"
            and inheritance_credits
            and user_declaration_status == "recorded"
            and formal_document_status == "documented"
            and headroom is not None
            and headroom >= 0
            and not missing_external_valuations
            and not parse_errors
        )
        status = "strict_ready" if strict_ready else "blocked"
        findings = self._findings(
            bank_statement_status=bank_statement_status,
            statement_from=statement_from,
            inheritance_credits=inheritance_credits,
            headroom=headroom,
            formal_document_status=formal_document_status,
            user_declaration_status=user_declaration_status,
            missing_external_valuations=missing_external_valuations,
            flows=flows,
            parse_errors=parse_errors,
        )
        next_actions = self._next_actions(
            bank_statement_status=bank_statement_status,
            separation_date=separation_date,
            statement_from=statement_from,
            formal_document_status=formal_document_status,
            user_declaration_status=user_declaration_status,
            missing_external_valuations=missing_external_valuations,
            trade_republic_connector=trade_republic_connector,
            coinbase_connector=coinbase_connector,
        )
        semantic_payload = {
            "separation_date": separation_date.isoformat(),
            "end_asset_date": end_asset_date.isoformat(),
            "bank_manifest_sha256": bank_manifest_sha256,
            "inheritance_credit": (
                inheritance_credit.model_dump(mode="json")
                if inheritance_credit
                else None
            ),
            "inheritance_credits": [
                item.model_dump(mode="json") for item in inheritance_credits
            ],
            "flows": [item.model_dump(mode="json") for item in flows],
            "provider_summaries": [
                item.model_dump(mode="json") for item in provider_summaries
            ],
            "formal_inheritance_document_sha256": formal_document_sha256,
            "formal_inheritance_connector": formal_inheritance_connector.model_dump(
                mode="json"
            ),
            "sparkasse_statement_connector": (
                sparkasse_statement_connector.model_dump(mode="json")
            ),
            "trade_republic_document_manifest_sha256": (
                trade_republic_connector.document_manifest_sha256
            ),
            "trade_republic_connector": trade_republic_connector.model_dump(
                mode="json"
            ),
            "coinbase_connector": coinbase_connector.model_dump(mode="json"),
            "findings": findings,
        }
        semantic_sha256 = self._sha256(
            json.dumps(
                semantic_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        )
        return DivorceInheritanceOriginReport(
            generated_at=generated_at,
            separation_date=separation_date,
            end_asset_date=end_asset_date,
            status=status,
            strict_ready=strict_ready,
            bank_statement_status=bank_statement_status,
            bank_statement_from=statement_from,
            bank_statement_to=statement_to,
            bank_files_count=len(bank_files),
            bank_manifest_sha256=bank_manifest_sha256,
            opening_balance_eur=opening_balance,
            end_asset_closing_balance_eur=closing_balance,
            minimum_closing_balance_after_inheritance_eur=minimum_after_inheritance,
            mixed_account=True,
            inheritance_credit=inheritance_credit,
            inheritance_credits=inheritance_credits,
            inheritance_credit_count=len(inheritance_credits),
            inheritance_credit_eur=credit_amount,
            user_declaration_status=user_declaration_status,
            formal_inheritance_document_status=formal_document_status,
            formal_inheritance_document_sha256=formal_document_sha256,
            formal_inheritance_connector=formal_inheritance_connector,
            bank_identified_investment_eur=bank_total,
            platform_only_investment_eur=platform_only_total,
            total_identified_investment_eur=total_investment,
            declared_inheritance_headroom_eur=headroom,
            crypto_tracked_investment_eur=crypto_tracked,
            external_asset_investment_eur=external_investment,
            external_asset_end_value_eur=external_end_value,
            external_asset_gain_loss_eur=(
                external_end_value - external_investment
                if external_end_value is not None
                else None
            ),
            provider_summaries=provider_summaries,
            investment_flows=flows,
            sparkasse_statement_connector=sparkasse_statement_connector,
            trade_republic_connector=trade_republic_connector,
            coinbase_connector=coinbase_connector,
            findings=findings,
            next_actions=next_actions,
            semantic_sha256=semantic_sha256,
            methodology=(
                "Read-only Mittelherkunftsnachweis. Native CAMT.052-Dateien werden "
                "strukturiert geparst und per SHA-256 gebunden. Automatische "
                "Nachlassmarker sowie einzeln freigegebene Bank- oder Dokumentgutschriften "
                "werden als Erbmittelzufluesse aggregiert; jede Teilposition bleibt separat "
                "nachweisbar. Die Summe ist eine Mittelherkunftsspur und keine automatische "
                "familienrechtliche Bewertung nach Paragraph 1374 BGB. Tagesabschlusssalden "
                "und Investmentabfluesse zu bekannten Anbietern werden reduziert. "
                "Kontonummern, Gegenparteien und Verwendungszwecke verlassen den "
                "Parser nicht. Binance-Plattformbelege werden nach Datum und Bruttobetrag "
                "gegen Bankabfluesse abgeglichen; nur unmatched Plattformzufluesse werden "
                "zusaetzlich gezaehlt. Sparkassen-PDF-Auszugbelege werden per Hash gebunden "
                "und gegen CAMT abgeglichen, aber niemals als zweiter Investmentfluss "
                "gezaehlt. Nutzerangabe, Bankspur, formaler Erbnachweis und "
                "Stichtagswert externer Depots bleiben getrennte Gates. Der Report aendert "
                "weder Bankdaten noch Canonical Events, FIFO, Ledger, Preise oder Steuerdaten."
            ),
        )

    def csv(self, **kwargs: object) -> str:
        report = self.report(**kwargs)
        return self.csv_for_report(report)

    def inheritance_credits_csv(self, **kwargs: object) -> str:
        report = self.report(**kwargs)
        return self.inheritance_credits_csv_for_report(report)

    @staticmethod
    def inheritance_credits_csv_for_report(
        report: DivorceInheritanceOriginReport,
    ) -> str:
        output = io.StringIO()
        fieldnames = [
            "booking_date",
            "amount_eur",
            "credit_kind",
            "evidence_source",
            "date_basis",
            "classification_source",
            "transaction_reference_sha256",
            "source_file_sha256",
            "evidence_ref",
            "supporting_evidence_ref",
            "review_decision_id",
            "note",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for item in report.inheritance_credits:
            row = item.model_dump(mode="json")
            writer.writerow({key: row.get(key) for key in fieldnames})
        return output.getvalue()

    def inheritance_bank_credit_candidates(
        self,
        *,
        separation_date: date = DEFAULT_SEPARATION_DATE,
        end_asset_date: date = DEFAULT_END_ASSET_DATE,
    ) -> InheritanceBankCreditCandidateReport:
        generated_at = datetime.now(timezone.utc)
        entries, _balances, _files, bank_manifest_sha256, parse_errors = (
            self._load_bank_data()
        )
        decisions = self._inheritance_bank_credit_decisions()
        candidates: list[InheritanceBankCreditCandidate] = []
        for item in entries:
            if (
                item.direction != "CRDT"
                or item.amount_eur <= 0
                or not (separation_date < item.booking_date <= end_asset_date)
            ):
                continue
            decision = decisions.get(item.reference_sha256)
            if item.is_inheritance_credit:
                review_status = "automatic"
                credit_kind = "estate_account_transfer"
            elif decision is not None:
                review_status = "reviewed"
                credit_kind = str(decision.payload.get("credit_kind") or "")
            else:
                review_status = "unclassified"
                credit_kind = None
            candidates.append(
                InheritanceBankCreditCandidate(
                    booking_date=item.booking_date,
                    amount_eur=item.amount_eur,
                    transaction_reference_sha256=item.reference_sha256,
                    source_file_sha256=item.source_file_sha256,
                    automatic_inheritance_marker=item.is_inheritance_credit,
                    review_status=review_status,
                    credit_kind=credit_kind,
                    evidence_ref=self._bank_credit_evidence_ref(item),
                    supporting_evidence_ref=(
                        decision.evidence_ref if decision is not None else None
                    ),
                    review_decision_id=(
                        decision.decision_id if decision is not None else None
                    ),
                )
            )
        candidates.sort(
            key=lambda item: (item.booking_date, item.transaction_reference_sha256)
        )
        classified_count = sum(
            item.review_status != "unclassified" for item in candidates
        )
        return InheritanceBankCreditCandidateReport(
            generated_at=generated_at,
            separation_date=separation_date,
            end_asset_date=end_asset_date,
            bank_manifest_sha256=bank_manifest_sha256,
            candidates_count=len(candidates),
            classified_count=classified_count,
            unclassified_count=len(candidates) - classified_count,
            candidates=candidates,
            parse_errors=parse_errors,
            methodology=(
                "Datensparsame Reviewliste aller positiven CAMT-Gutschriften im "
                "angeforderten Zeitraum. Gegenparteien, IBAN und Verwendungszwecke werden "
                "nicht ausgegeben. Eine Gutschrift wird nur durch einen eindeutigen "
                "Nachlassmarker oder eine hashgebundene Review Decision zu Erbmitteln."
            ),
        )

    def accept_inheritance_bank_credit(
        self,
        payload: InheritanceBankCreditDecisionRequest,
        *,
        separation_date: date = DEFAULT_SEPARATION_DATE,
        end_asset_date: date = DEFAULT_END_ASSET_DATE,
    ) -> InheritanceBankCreditDecisionResult:
        candidates = self.inheritance_bank_credit_candidates(
            separation_date=separation_date,
            end_asset_date=end_asset_date,
        )
        candidate = next(
            (
                item
                for item in candidates.candidates
                if item.transaction_reference_sha256
                == payload.transaction_reference_sha256
            ),
            None,
        )
        if candidate is None:
            raise ValueError(
                "Die angegebene Gutschrift ist im aktuellen CAMT-Zeitraum nicht vorhanden."
            )
        if candidate.review_status == "automatic":
            raise ValueError(
                "Diese Gutschrift ist bereits durch einen CAMT-Nachlassmarker klassifiziert."
            )
        existing = self._inheritance_bank_credit_decisions().get(
            payload.transaction_reference_sha256
        )
        if existing is not None:
            existing_kind = str(existing.payload.get("credit_kind") or "")
            if existing_kind != payload.credit_kind:
                raise ValueError(
                    "Fuer diese Gutschrift ist bereits eine abweichende Klassifikation gespeichert."
                )
            return InheritanceBankCreditDecisionResult(
                decision_id=existing.decision_id,
                already_recorded=True,
                transaction_reference_sha256=payload.transaction_reference_sha256,
                credit_kind=payload.credit_kind,
                origin_report=self.report(
                    separation_date=separation_date,
                    end_asset_date=end_asset_date,
                ),
            )
        if payload.supporting_evidence_ref:
            known_refs = {
                item.evidence_ref for item in self.inheritance_documents().documents
            }
            if payload.supporting_evidence_ref not in known_refs:
                raise ValueError(
                    "Der angegebene ergaenzende Erbnachweis ist nicht im Dokumentroot vorhanden."
                )
        decision = self.store.add_review_decision(
            ReviewDecisionCreate(
                decision_type="divorce_inheritance_bank_credit",
                scope=(
                    "divorce:inheritance-bank-credit:"
                    f"{payload.transaction_reference_sha256}"
                ),
                title="Weitere CAMT-Gutschrift als Erbmittel geprueft",
                rationale=payload.rationale
                or (
                    "Die CAMT-Gutschrift wurde gegen den Originalbeleg geprueft und als "
                    "Realisierung oder Erstattung eines geerbten Vermoegenswerts eingestuft."
                ),
                evidence_ref=(
                    payload.supporting_evidence_ref or candidate.evidence_ref
                ),
                actor=payload.actor,
                source="api:/api/v1/divorce/inheritance-credit-decisions",
                affected_ids=[payload.transaction_reference_sha256],
                payload={
                    "transaction_reference_sha256": (
                        payload.transaction_reference_sha256
                    ),
                    "credit_kind": payload.credit_kind,
                    "bank_evidence_ref": candidate.evidence_ref,
                    "supporting_evidence_ref": payload.supporting_evidence_ref,
                    "import_effect": "review_decision_only",
                },
            )
        )
        return InheritanceBankCreditDecisionResult(
            decision_id=decision.decision_id,
            transaction_reference_sha256=payload.transaction_reference_sha256,
            credit_kind=payload.credit_kind,
            origin_report=self.report(
                separation_date=separation_date,
                end_asset_date=end_asset_date,
            ),
        )

    def accept_inheritance_document_credit(
        self,
        payload: InheritanceDocumentCreditDecisionRequest,
        *,
        separation_date: date = DEFAULT_SEPARATION_DATE,
        end_asset_date: date = DEFAULT_END_ASSET_DATE,
    ) -> InheritanceDocumentCreditDecisionResult:
        connector = self.inheritance_documents()
        candidate = next(
            (
                item
                for item in connector.documents
                if item.document_sha256 == payload.document_sha256
            ),
            None,
        )
        if candidate is None:
            raise ValueError(
                "Der angegebene Erbmittelbeleg ist nicht im Dokumentroot vorhanden."
            )
        amount_text = format(payload.amount_eur, "f")
        transaction_reference_sha256 = self._sha256(
            "|".join(
                (
                    "supporting_document",
                    payload.document_sha256,
                    payload.document_date.isoformat(),
                    amount_text,
                    payload.credit_kind,
                )
            ).encode("utf-8")
        )
        for existing in self.store.list_review_decisions():
            if existing.decision_type != "divorce_inheritance_document_credit":
                continue
            existing_reference = str(
                existing.payload.get("transaction_reference_sha256") or ""
            )
            if existing_reference == transaction_reference_sha256:
                return InheritanceDocumentCreditDecisionResult(
                    decision_id=existing.decision_id,
                    already_recorded=True,
                    document_sha256=payload.document_sha256,
                    transaction_reference_sha256=transaction_reference_sha256,
                    credit_kind=payload.credit_kind,
                    amount_eur=payload.amount_eur,
                    origin_report=self.report(
                        separation_date=separation_date,
                        end_asset_date=end_asset_date,
                    ),
                )
            if (
                str(existing.payload.get("document_sha256") or "")
                == payload.document_sha256
            ):
                raise ValueError(
                    "Fuer dieses Dokument ist bereits ein abweichender Erbmittelbetrag gespeichert."
                )
        decision = self.store.add_review_decision(
            ReviewDecisionCreate(
                decision_type="divorce_inheritance_document_credit",
                scope=(
                    "divorce:inheritance-document-credit:"
                    f"{transaction_reference_sha256}"
                ),
                title="Dokumentierten Erbmittelzufluss geprueft",
                rationale=payload.rationale
                or (
                    "Der Nettobetrag wurde gegen den Originalbeleg geprueft. Nur der nach "
                    "Kosten verbleibende Auszahlungsbetrag wird als Erbmittelzufluss erfasst."
                ),
                evidence_ref=candidate.evidence_ref,
                actor=payload.actor,
                source="api:/api/v1/divorce/inheritance-document-credit-decisions",
                affected_ids=[payload.document_sha256, transaction_reference_sha256],
                payload={
                    "document_sha256": payload.document_sha256,
                    "document_date": payload.document_date.isoformat(),
                    "amount_eur": amount_text,
                    "credit_kind": payload.credit_kind,
                    "transaction_reference_sha256": transaction_reference_sha256,
                    "date_basis": "document_date",
                    "import_effect": "review_decision_only",
                },
            )
        )
        return InheritanceDocumentCreditDecisionResult(
            decision_id=decision.decision_id,
            document_sha256=payload.document_sha256,
            transaction_reference_sha256=transaction_reference_sha256,
            credit_kind=payload.credit_kind,
            amount_eur=payload.amount_eur,
            origin_report=self.report(
                separation_date=separation_date,
                end_asset_date=end_asset_date,
            ),
        )

    def trade_republic_documents(
        self,
        *,
        end_asset_date: date = DEFAULT_END_ASSET_DATE,
    ) -> TradeRepublicConnectorStatus:
        return self._trade_republic_connector(end_asset_date)

    def sparkasse_statements(self) -> SparkasseStatementConnectorStatus:
        entries, _balances, _files, _manifest, _errors = self._load_bank_data()
        return self._sparkasse_statement_connector(entries)

    def sparkasse_statements_csv(self) -> str:
        connector = self.sparkasse_statements()
        return SparkasseStatementDocumentService().csv(connector)

    def trade_republic_documents_csv(
        self,
        *,
        end_asset_date: date = DEFAULT_END_ASSET_DATE,
    ) -> str:
        connector = self.trade_republic_documents(end_asset_date=end_asset_date)
        return self.trade_republic_documents_csv_for_connector(connector)

    @staticmethod
    def trade_republic_documents_csv_for_connector(
        connector: TradeRepublicConnectorStatus,
    ) -> str:
        output = io.StringIO()
        fieldnames = [
            "document_sha256",
            "container_sha256",
            "source_kind",
            "document_type",
            "extraction_status",
            "statement_date",
            "period_from",
            "period_to",
            "end_asset_date_match_source",
            "cash_value_eur",
            "securities_value_eur",
            "total_value_eur",
            "valuation_status",
            "evidence_ref",
            "findings",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for item in connector.documents:
            writer.writerow(
                {
                    "document_sha256": item.document_sha256,
                    "container_sha256": item.container_sha256 or "",
                    "source_kind": item.source_kind,
                    "document_type": item.document_type,
                    "extraction_status": item.extraction_status,
                    "statement_date": item.statement_date.isoformat()
                    if item.statement_date
                    else "",
                    "period_from": item.period_from.isoformat()
                    if item.period_from
                    else "",
                    "period_to": item.period_to.isoformat() if item.period_to else "",
                    "end_asset_date_match_source": item.end_asset_date_match_source,
                    "cash_value_eur": str(item.cash_value_eur)
                    if item.cash_value_eur is not None
                    else "",
                    "securities_value_eur": (
                        str(item.securities_value_eur)
                        if item.securities_value_eur is not None
                        else ""
                    ),
                    "total_value_eur": str(item.total_value_eur)
                    if item.total_value_eur is not None
                    else "",
                    "valuation_status": item.valuation_status,
                    "evidence_ref": item.evidence_ref,
                    "findings": " | ".join(item.findings),
                }
            )
        return output.getvalue()

    def inheritance_documents(self) -> InheritanceDocumentConnectorStatus:
        return self._formal_inheritance_connector()

    def store_bank_camt_document(
        self,
        *,
        filename: str,
        content: bytes,
        separation_date: date = DEFAULT_SEPARATION_DATE,
        end_asset_date: date = DEFAULT_END_ASSET_DATE,
    ) -> BankCamtUploadResult:
        documents = BankCamtDocumentService.extract_validated_xml(filename, content)
        unique_documents = {self._sha256(document): document for document in documents}
        root = self.bank_camt_dir
        if root is None:
            raise ValueError(
                "Es ist kein lokales Sparkassen-CAMT-Verzeichnis konfiguriert."
            )
        root.mkdir(parents=True, exist_ok=True)
        existing_hashes = {
            self._file_sha256(path) for path in root.glob("*.xml") if path.is_file()
        }
        uploaded = 0
        already_present = 0
        for document_sha256, document in unique_documents.items():
            if document_sha256 in existing_hashes:
                already_present += 1
                continue
            target = root / f"camt-{document_sha256[:24]}.xml"
            if target.exists():
                raise ValueError("Hashbasierter CAMT-Zielname ist bereits belegt.")
            temporary = root / f".{target.name}.{uuid4().hex}.tmp"
            try:
                temporary.write_bytes(document)
                temporary.replace(target)
            finally:
                if temporary.exists():
                    temporary.unlink()
            existing_hashes.add(document_sha256)
            uploaded += 1
        return BankCamtUploadResult(
            uploaded_files=uploaded,
            already_present_files=already_present,
            document_sha256s=sorted(unique_documents),
            origin_report=self.report(
                separation_date=separation_date,
                end_asset_date=end_asset_date,
            ),
        )

    def coinbase_connector(
        self,
        *,
        end_asset_date: date = DEFAULT_END_ASSET_DATE,
    ) -> CoinbaseConnectorStatus:
        return self._coinbase_connector(end_asset_date)

    def coinbase_connector_csv(
        self,
        *,
        end_asset_date: date = DEFAULT_END_ASSET_DATE,
    ) -> str:
        return self.coinbase_connector_csv_for_connector(
            self._coinbase_connector(end_asset_date)
        )

    @staticmethod
    def coinbase_connector_csv_for_connector(
        connector: CoinbaseConnectorStatus,
    ) -> str:
        output = io.StringIO()
        fieldnames = [
            "history_manifest_sha256",
            "history_batches_count",
            "history_events_count",
            "history_from",
            "history_to",
            "history_status",
            "asset",
            "quantity",
            "value_eur",
            "price_source",
            "priced_at",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        assets = connector.assets or [None]
        for item in assets:
            writer.writerow(
                {
                    "history_manifest_sha256": connector.history_manifest_sha256 or "",
                    "history_batches_count": connector.history_batches_count,
                    "history_events_count": connector.history_events_count,
                    "history_from": connector.history_from.isoformat()
                    if connector.history_from
                    else "",
                    "history_to": connector.history_to.isoformat()
                    if connector.history_to
                    else "",
                    "history_status": connector.history_status,
                    "asset": item.asset if item else "",
                    "quantity": str(item.quantity) if item else "",
                    "value_eur": str(item.value_eur)
                    if item and item.value_eur is not None
                    else "",
                    "price_source": item.price_source
                    if item and item.price_source
                    else "",
                    "priced_at": item.priced_at.isoformat()
                    if item and item.priced_at
                    else "",
                }
            )
        return output.getvalue()

    def accept_coinbase_valuation(
        self,
        payload: CoinbaseValuationDecisionRequest,
    ) -> CoinbaseValuationDecisionResult:
        connector = self._coinbase_connector(payload.end_asset_date)
        evidence_ref = f"coinbase-history:sha256:{payload.history_manifest_sha256}"
        scope = (
            "divorce:external-asset-valuation:coinbase:"
            f"{payload.end_asset_date.isoformat()}"
        )
        for existing in self.store.list_review_decisions():
            if existing.decision_type != "divorce_external_asset_valuation":
                continue
            if str(existing.payload.get("provider") or "") != "coinbase":
                continue
            if (
                str(existing.payload.get("valuation_date") or "")
                != payload.end_asset_date.isoformat()
            ):
                continue
            existing_manifest = str(
                existing.payload.get("history_manifest_sha256") or ""
            )
            existing_value = str(existing.payload.get("value_eur") or "")
            if existing_manifest != payload.history_manifest_sha256:
                continue
            if (
                existing_value == str(connector.candidate_end_asset_value_eur)
                and existing.evidence_ref == evidence_ref
            ):
                return CoinbaseValuationDecisionResult(
                    decision_id=existing.decision_id,
                    already_recorded=True,
                    valuation_date=payload.end_asset_date,
                    value_eur=connector.candidate_end_asset_value_eur,
                    evidence_ref=evidence_ref,
                    history_manifest_sha256=payload.history_manifest_sha256,
                    origin_report=self.report(end_asset_date=payload.end_asset_date),
                )
            raise ValueError(
                "Fuer diese Coinbase-Historie ist bereits ein abweichender Wert freigegeben."
            )
        if (
            not connector.valuation_review_ready
            or connector.history_manifest_sha256 != payload.history_manifest_sha256
            or connector.candidate_end_asset_value_eur is None
        ):
            raise ValueError(
                "Coinbase-Historie, Stichtagspreise oder Mengen sind nicht eindeutig reviewbereit."
            )
        decision = self.store.add_review_decision(
            ReviewDecisionCreate(
                decision_type="divorce_external_asset_valuation",
                scope=scope,
                title="Coinbase-Stichtagswert aus vollstaendiger Historie geprueft",
                rationale=payload.rationale
                or (
                    "Der Nutzer hat bestaetigt, dass der offizielle Coinbase-Export die "
                    "vollstaendige Account-Historie ab Kontoeroeffnung enthaelt. Der Wert "
                    "wurde aus Ledger-Mengen und belegten Stichtagspreisen berechnet."
                ),
                evidence_ref=evidence_ref,
                actor=payload.actor,
                source="api:/api/v1/divorce/coinbase/valuation-decisions",
                affected_ids=[payload.history_manifest_sha256],
                payload={
                    "provider": "coinbase",
                    "valuation_date": payload.end_asset_date.isoformat(),
                    "value_eur": str(connector.candidate_end_asset_value_eur),
                    "history_manifest_sha256": payload.history_manifest_sha256,
                    "history_events_count": connector.history_events_count,
                    "history_from": connector.history_from.isoformat()
                    if connector.history_from
                    else None,
                    "history_to": connector.history_to.isoformat()
                    if connector.history_to
                    else None,
                    "import_effect": "review_decision_only",
                },
            )
        )
        return CoinbaseValuationDecisionResult(
            decision_id=decision.decision_id,
            valuation_date=payload.end_asset_date,
            value_eur=connector.candidate_end_asset_value_eur,
            evidence_ref=evidence_ref,
            history_manifest_sha256=payload.history_manifest_sha256,
            origin_report=self.report(end_asset_date=payload.end_asset_date),
        )

    def inheritance_documents_csv(self) -> str:
        return self.inheritance_documents_csv_for_connector(
            self.inheritance_documents()
        )

    @staticmethod
    def inheritance_documents_csv_for_connector(
        connector: InheritanceDocumentConnectorStatus,
    ) -> str:
        output = io.StringIO()
        fieldnames = [
            "document_sha256",
            "media_type",
            "size_bytes",
            "source_kind",
            "review_status",
            "evidence_ref",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for item in connector.documents:
            writer.writerow(item.model_dump(mode="json"))
        return output.getvalue()

    def store_inheritance_document(
        self,
        *,
        filename: str,
        content: bytes,
    ) -> InheritanceDocumentUploadResult:
        suffix, _media_type = InheritanceDocumentService.validate_upload(
            filename, content
        )
        document_sha256 = self._sha256(content)
        root = self.inheritance_document_root
        root.mkdir(parents=True, exist_ok=True)
        target = root / f"document-{document_sha256[:24]}{suffix}"
        already_present = (
            target.is_file() and self._file_sha256(target) == document_sha256
        )
        if target.exists() and not already_present:
            raise ValueError(
                "Hashbasierter Zielname ist bereits mit anderem Inhalt belegt."
            )
        if not already_present:
            temporary = root / f".{target.name}.{uuid4().hex}.tmp"
            try:
                temporary.write_bytes(content)
                temporary.replace(target)
            finally:
                if temporary.exists():
                    temporary.unlink()
        return InheritanceDocumentUploadResult(
            document_sha256=document_sha256,
            size_bytes=len(content),
            already_present=already_present,
            connector=self.inheritance_documents(),
        )

    def accept_inheritance_document(
        self,
        payload: InheritanceDocumentDecisionRequest,
    ) -> InheritanceDocumentDecisionResult:
        connector = InheritanceDocumentService().scan(
            self.inheritance_document_root,
            configured_path=self.inheritance_document_path,
        )
        candidate = next(
            (
                item
                for item in connector.documents
                if item.document_sha256 == payload.document_sha256
            ),
            None,
        )
        if candidate is None:
            raise ValueError(
                "Der angegebene Erbnachweis ist nicht im Dokumentroot vorhanden."
            )
        scope = "divorce:formal-inheritance-evidence"
        for existing in self.store.list_review_decisions():
            if existing.decision_type != "divorce_formal_inheritance_evidence":
                continue
            existing_sha256 = str(existing.payload.get("document_sha256") or "")
            if existing_sha256 == candidate.document_sha256 and existing.evidence_ref:
                return InheritanceDocumentDecisionResult(
                    decision_id=existing.decision_id,
                    already_recorded=True,
                    document_sha256=candidate.document_sha256,
                    evidence_ref=existing.evidence_ref,
                    origin_report=self.report(),
                )
            raise ValueError(
                "Ein anderer formaler Erbnachweis ist bereits freigegeben. "
                "Die vorhandene Review Decision muss fachlich geprueft werden."
            )
        decision = self.store.add_review_decision(
            ReviewDecisionCreate(
                decision_type="divorce_formal_inheritance_evidence",
                scope=scope,
                title="Formaler Erbnachweis geprueft",
                rationale=payload.rationale
                or (
                    "Der Nutzer hat das Originaldokument als Erbschein, Testament/Erbvertrag "
                    "oder Nachlassabrechnung geprueft. API und Dossier speichern nur die "
                    "SHA-256-Belegbindung."
                ),
                evidence_ref=candidate.evidence_ref,
                actor=payload.actor,
                source="api:/api/v1/divorce/inheritance-documents/review-decisions",
                affected_ids=[candidate.document_sha256],
                payload={
                    "document_sha256": candidate.document_sha256,
                    "evidence_kind": "formal_inheritance_document",
                    "import_effect": "review_decision_only",
                },
            )
        )
        return InheritanceDocumentDecisionResult(
            decision_id=decision.decision_id,
            document_sha256=candidate.document_sha256,
            evidence_ref=candidate.evidence_ref,
            origin_report=self.report(),
        )

    def store_trade_republic_document(
        self,
        *,
        filename: str,
        content: bytes,
        end_asset_date: date = DEFAULT_END_ASSET_DATE,
    ) -> TradeRepublicDocumentUploadResult:
        suffix = Path(filename or "").suffix.lower()
        if suffix not in TradeRepublicDocumentService.SUPPORTED_SUFFIXES:
            raise ValueError(
                "Erlaubt sind ausschliesslich PDF-, CSV- und ZIP-Dokumente."
            )
        if not content:
            raise ValueError("Das Dokument ist leer.")
        if len(content) > TradeRepublicDocumentService.MAX_FILE_BYTES:
            raise ValueError("Das Dokument ueberschreitet das lokale Dateilimit.")
        document_sha256 = self._sha256(content)
        root = self.trade_republic_document_root
        root.mkdir(parents=True, exist_ok=True)
        target = root / f"document-{document_sha256[:24]}{suffix}"
        already_present = (
            target.is_file() and self._file_sha256(target) == document_sha256
        )
        if target.exists() and not already_present:
            raise ValueError(
                "Hashbasierter Zielname ist bereits mit anderem Inhalt belegt."
            )
        if not already_present:
            temporary = root / f".{target.name}.{uuid4().hex}.tmp"
            try:
                temporary.write_bytes(content)
                temporary.replace(target)
            finally:
                if temporary.exists():
                    temporary.unlink()
        return TradeRepublicDocumentUploadResult(
            document_sha256=document_sha256,
            size_bytes=len(content),
            already_present=already_present,
            connector=self.trade_republic_documents(end_asset_date=end_asset_date),
        )

    def accept_trade_republic_valuation(
        self,
        payload: TradeRepublicValuationDecisionRequest,
    ) -> TradeRepublicValuationDecisionResult:
        connector = TradeRepublicDocumentService().scan(
            self.trade_republic_document_root,
            end_asset_date=payload.end_asset_date,
        )
        candidate = next(
            (
                item
                for item in connector.documents
                if item.document_sha256 == payload.document_sha256
                and item.end_asset_date_match_source == "content"
                and item.valuation_status == "exact_date_candidate"
                and item.total_value_eur is not None
            ),
            None,
        )
        if candidate is None:
            raise ValueError(
                "Der Beleg liefert keinen eindeutigen, inhaltlich exakt datierten Trade-Republic-Stichtagswert."
            )
        scope = f"divorce:external-asset-valuation:trade_republic:{payload.end_asset_date.isoformat()}"
        for existing in self.store.list_review_decisions():
            if existing.decision_type != "divorce_external_asset_valuation":
                continue
            if str(existing.payload.get("provider") or "") != "trade_republic":
                continue
            if (
                str(existing.payload.get("valuation_date") or "")
                != payload.end_asset_date.isoformat()
            ):
                continue
            existing_sha256 = str(existing.payload.get("source_document_sha256") or "")
            existing_value = self._parse_eur_amount(
                str(existing.payload.get("value_eur") or "")
            )
            if (
                existing_sha256 == candidate.document_sha256
                and existing_value == candidate.total_value_eur
            ):
                return TradeRepublicValuationDecisionResult(
                    decision_id=existing.decision_id,
                    already_recorded=True,
                    valuation_date=payload.end_asset_date,
                    value_eur=candidate.total_value_eur,
                    evidence_ref=existing.evidence_ref or candidate.evidence_ref,
                    source_document_sha256=candidate.document_sha256,
                    origin_report=self.report(end_asset_date=payload.end_asset_date),
                )
            raise ValueError(
                "Fuer Trade Republic ist an diesem Stichtag bereits ein anderer Wert freigegeben. "
                "Die vorhandene Review Decision muss fachlich geprueft werden."
            )
        decision = self.store.add_review_decision(
            ReviewDecisionCreate(
                decision_type="divorce_external_asset_valuation",
                scope=scope,
                title=f"Trade-Republic-Stichtagswert {payload.end_asset_date.strftime('%d.%m.%Y')}",
                rationale=payload.rationale
                or (
                    "Explizite Nutzerfreigabe eines lokal extrahierten, inhaltlich exakt "
                    "datierten offiziellen Depotbelegs. Keine Aenderung an Ledger, FIFO, "
                    "Preisen oder Steuerzeilen."
                ),
                evidence_ref=candidate.evidence_ref,
                actor=payload.actor,
                source="api:/api/v1/divorce/trade-republic/valuation-decisions",
                affected_ids=[candidate.document_sha256],
                payload={
                    "provider": "trade_republic",
                    "valuation_date": payload.end_asset_date.isoformat(),
                    "value_eur": str(candidate.total_value_eur),
                    "cash_value_eur": (
                        str(candidate.cash_value_eur)
                        if candidate.cash_value_eur is not None
                        else None
                    ),
                    "securities_value_eur": (
                        str(candidate.securities_value_eur)
                        if candidate.securities_value_eur is not None
                        else None
                    ),
                    "source_document_sha256": candidate.document_sha256,
                    "document_manifest_sha256": connector.document_manifest_sha256,
                    "extraction_method": "official_document_exact_date_review",
                    "import_effect": "review_decision_only",
                },
            )
        )
        return TradeRepublicValuationDecisionResult(
            decision_id=decision.decision_id,
            valuation_date=payload.end_asset_date,
            value_eur=candidate.total_value_eur,
            evidence_ref=candidate.evidence_ref,
            source_document_sha256=candidate.document_sha256,
            origin_report=self.report(end_asset_date=payload.end_asset_date),
        )

    @staticmethod
    def csv_for_report(report: DivorceInheritanceOriginReport) -> str:
        output = io.StringIO()
        fieldnames = [
            "provider",
            "booking_date",
            "amount_eur",
            "evidence_source",
            "transaction_reference_sha256",
            "capital_origin",
            "capital_origin_evidence_status",
            "portfolio_coverage_status",
            "end_asset_valuation_status",
            "note",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for item in report.investment_flows:
            writer.writerow(
                {
                    "provider": item.provider,
                    "booking_date": item.booking_date.isoformat(),
                    "amount_eur": str(item.amount_eur),
                    "evidence_source": item.evidence_source,
                    "transaction_reference_sha256": item.transaction_reference_sha256,
                    "capital_origin": item.capital_origin,
                    "capital_origin_evidence_status": item.capital_origin_evidence_status,
                    "portfolio_coverage_status": item.portfolio_coverage_status,
                    "end_asset_valuation_status": item.end_asset_valuation_status,
                    "note": item.note,
                }
            )
        return output.getvalue()

    def _load_bank_data(
        self,
    ) -> tuple[list[_BankEntry], list[_BankBalance], list[Path], str | None, list[str]]:
        if self.bank_camt_dir is None or not self.bank_camt_dir.is_dir():
            return [], [], [], None, []
        files = sorted(self.bank_camt_dir.glob("*.xml"))
        manifest = [
            {
                "size_bytes": path.stat().st_size,
                "sha256": self._file_sha256(path),
            }
            for path in files
        ]
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
        entries: list[_BankEntry] = []
        balances: list[_BankBalance] = []
        errors: list[str] = []
        seen_entries: set[str] = set()
        seen_balances: set[tuple[date, str, Decimal]] = set()
        for path, file_meta in zip(files, manifest, strict=True):
            try:
                root = ET.parse(path).getroot()
            except (ET.ParseError, OSError):
                errors.append(f"bank_camt_parse_error:sha256:{file_meta['sha256']}")
                continue
            for element in self._elements(root, "Ntry"):
                entry = self._bank_entry(element, str(file_meta["sha256"]))
                if entry is None or entry.reference_sha256 in seen_entries:
                    continue
                seen_entries.add(entry.reference_sha256)
                entries.append(entry)
            for element in self._elements(root, "Bal"):
                balance = self._bank_balance(element)
                if balance is None:
                    continue
                key = (
                    balance.balance_date,
                    balance.balance_type,
                    balance.balance_eur,
                )
                if key in seen_balances:
                    continue
                seen_balances.add(key)
                balances.append(balance)
        entries.sort(key=lambda item: (item.booking_date, item.reference_sha256))
        balances.sort(
            key=lambda item: (item.balance_date, item.balance_type, item.balance_eur)
        )
        return entries, balances, files, manifest_sha256, errors

    def _sparkasse_statement_connector(
        self,
        entries: list[_BankEntry],
    ) -> SparkasseStatementConnectorStatus:
        investments = [
            SparkasseCamtInvestmentEvidence(
                booking_date=item.booking_date,
                provider=item.provider,
                amount_eur=item.amount_eur,
                transaction_reference_sha256=item.reference_sha256,
            )
            for item in entries
            if item.direction == "DBIT" and item.provider is not None
        ]
        return SparkasseStatementDocumentService().scan(
            self.sparkasse_statement_root,
            camt_investments=investments,
        )

    def _bank_entry(
        self,
        element: ET.Element,
        source_file_sha256: str,
    ) -> _BankEntry | None:
        amount_element = next(self._direct_children(element, "Amt"), None)
        direction = self._first_text(element, "CdtDbtInd")
        booking_element = next(self._elements(element, "BookgDt"), None)
        booking_text = (
            self._first_text(booking_element, "Dt")
            if booking_element is not None
            else None
        )
        if (
            amount_element is None
            or str(amount_element.attrib.get("Ccy") or "").upper() != "EUR"
            or direction not in {"CRDT", "DBIT"}
            or not booking_text
        ):
            return None
        try:
            amount = Decimal(str(amount_element.text or ""))
            booking_date = date.fromisoformat(booking_text)
        except (InvalidOperation, ValueError):
            return None
        flattened = " ".join(
            str(item.text or "").strip()
            for item in element.iter()
            if str(item.text or "").strip()
        )
        normalized = flattened.casefold()
        provider = self._provider(normalized) if direction == "DBIT" else None
        is_inheritance_credit = direction == "CRDT" and "nachlass" in normalized
        if amount <= 0 or (direction == "DBIT" and provider is None):
            return None
        source_reference = self._first_text(element, "AcctSvcrRef") or self._first_text(
            element, "NtryRef"
        )
        reference_material = "|".join(
            (
                source_reference
                or self._sha256(ET.tostring(element, encoding="utf-8")),
                booking_date.isoformat(),
                str(amount),
                direction,
                provider
                or ("inheritance_credit" if is_inheritance_credit else "bank_credit"),
            )
        )
        return _BankEntry(
            booking_date=booking_date,
            amount_eur=amount,
            direction=direction,
            provider=provider,
            is_inheritance_credit=is_inheritance_credit,
            reference_sha256=self._sha256(reference_material.encode("utf-8")),
            source_file_sha256=source_file_sha256,
        )

    def _bank_balance(self, element: ET.Element) -> _BankBalance | None:
        amount_element = next(self._direct_children(element, "Amt"), None)
        direction = self._first_text(element, "CdtDbtInd")
        balance_type = self._first_text(element, "Cd") or "unknown"
        date_container = next(self._direct_children(element, "Dt"), None)
        date_text = (
            self._first_text(date_container, "Dt")
            if date_container is not None
            else None
        )
        if (
            amount_element is None
            or str(amount_element.attrib.get("Ccy") or "").upper() != "EUR"
            or direction not in {"CRDT", "DBIT"}
            or not date_text
        ):
            return None
        try:
            amount = Decimal(str(amount_element.text or ""))
            balance_date = date.fromisoformat(date_text)
        except (InvalidOperation, ValueError):
            return None
        if direction == "DBIT":
            amount = -amount
        return _BankBalance(
            balance_date=balance_date,
            balance_eur=amount,
            balance_type=balance_type,
        )

    @staticmethod
    def _provider(normalized: str) -> str | None:
        if "trade republic" in normalized:
            return "trade_republic"
        if "moonpay" in normalized:
            return "moonpay"
        if "coinbase" in normalized:
            return "coinbase"
        if "binance" in normalized or "bifinity" in normalized:
            return "binance"
        return None

    def _platform_only_binance(
        self,
        bank_entries: list[_BankEntry],
        *,
        separation_date: date,
        end_asset_date: date,
    ) -> list[tuple[date, Decimal, str]]:
        report = PortfolioService(self.store).fiat_deposit_report(
            cutoff=datetime.combine(
                separation_date, datetime.min.time(), tzinfo=timezone.utc
            ),
            source="binance",
        )
        bank_candidates = [item for item in bank_entries if item.provider == "binance"]
        available = set(range(len(bank_candidates)))
        platform_only: list[tuple[date, Decimal, str]] = []
        berlin = ZoneInfo("Europe/Berlin")
        for row in report.rows:
            event_time = row.time_utc
            if event_time.tzinfo is None:
                event_time = event_time.replace(tzinfo=timezone.utc)
            event_date = event_time.astimezone(berlin).date()
            if not separation_date < event_date <= end_asset_date:
                continue
            gross_amount = self._parse_eur_amount(row.deposit_amount_original)
            if gross_amount is None:
                gross_amount = row.receive_amount_eur
            matches = sorted(
                (
                    (
                        abs((bank_candidates[index].booking_date - event_date).days),
                        index,
                    )
                    for index in available
                    if bank_candidates[index].amount_eur == gross_amount
                    and abs((bank_candidates[index].booking_date - event_date).days)
                    <= 14
                ),
                key=lambda item: (item[0], item[1]),
            )
            if matches:
                available.remove(matches[0][1])
                continue
            reference = (
                row.transaction_id
                or row.raw_object_id
                or (f"{event_time.isoformat()}|{gross_amount}")
            )
            platform_only.append(
                (
                    event_date,
                    gross_amount,
                    self._sha256(str(reference).encode("utf-8")),
                )
            )
        return platform_only

    def _investment_flows(
        self,
        bank_entries: list[_BankEntry],
        platform_only_binance: list[tuple[date, Decimal, str]],
        decisions: dict[str, tuple[str, str | None]],
    ) -> list[DivorceInheritanceInvestmentFlow]:
        result: list[DivorceInheritanceInvestmentFlow] = []
        for item in bank_entries:
            if item.provider is None:
                continue
            result.append(
                self._flow(
                    provider=item.provider,
                    booking_date=item.booking_date,
                    amount_eur=item.amount_eur,
                    evidence_source="bank_camt",
                    reference_sha256=item.reference_sha256,
                    decisions=decisions,
                )
            )
        for booking_date, amount_eur, reference_sha256 in platform_only_binance:
            result.append(
                self._flow(
                    provider="binance",
                    booking_date=booking_date,
                    amount_eur=amount_eur,
                    evidence_source="platform_ledger",
                    reference_sha256=reference_sha256,
                    decisions=decisions,
                )
            )
        result.sort(
            key=lambda item: (item.booking_date, item.provider, item.evidence_source)
        )
        return result

    def _flow(
        self,
        *,
        provider: str,
        booking_date: date,
        amount_eur: Decimal,
        evidence_source: str,
        reference_sha256: str,
        decisions: dict[str, tuple[str, str | None]],
    ) -> DivorceInheritanceInvestmentFlow:
        flow_id = self.PROVIDER_FLOW_IDS[provider]
        documented = flow_id in decisions or "post_separation_investments" in decisions
        tracked = provider in {"binance", "moonpay"}
        return DivorceInheritanceInvestmentFlow(
            flow_id=flow_id,
            provider=provider,
            booking_date=booking_date,
            amount_eur=amount_eur,
            evidence_source=evidence_source,
            transaction_reference_sha256=reference_sha256,
            capital_origin="inheritance" if documented else "claimed_inheritance",
            capital_origin_evidence_status=(
                "documented" if documented else "user_declared"
            ),
            portfolio_coverage_status=(
                "platform_only"
                if evidence_source == "platform_ledger"
                else "tracked"
                if tracked
                else "not_connected"
            ),
            end_asset_valuation_status=(
                "covered_by_crypto_ledger" if tracked else "missing_source_documents"
            ),
            note=(
                "Plattformbeleg ohne passenden Sparkassenabgang im vorhandenen Export."
                if evidence_source == "platform_ledger"
                else "Datensparsam gehashter Primaerbeleg aus Sparkassen-CAMT."
            ),
        )

    def _provider_summaries(
        self,
        flows: list[DivorceInheritanceInvestmentFlow],
        decisions: dict[str, tuple[str, str | None]],
        end_asset_date: date,
        *,
        coinbase_connector: CoinbaseConnectorStatus,
    ) -> list[DivorceInheritanceProviderSummary]:
        grouped: defaultdict[str, list[DivorceInheritanceInvestmentFlow]] = defaultdict(
            list
        )
        for item in flows:
            grouped[item.provider].append(item)
        result: list[DivorceInheritanceProviderSummary] = []
        for provider in ("binance", "moonpay", "coinbase", "trade_republic"):
            rows = grouped.get(provider, [])
            bank_rows = [item for item in rows if item.evidence_source == "bank_camt"]
            platform_rows = [
                item for item in rows if item.evidence_source == "platform_ledger"
            ]
            amount = sum((item.amount_eur for item in rows), Decimal("0"))
            flow_id = self.PROVIDER_FLOW_IDS[provider]
            documented = (
                flow_id in decisions or "post_separation_investments" in decisions
            )
            valuation = (
                _ExternalValuation(
                    value_eur=coinbase_connector.accepted_end_asset_value_eur,
                    evidence_ref=coinbase_connector.accepted_evidence_ref,
                )
                if provider == "coinbase"
                and coinbase_connector.history_status == "reviewed"
                and coinbase_connector.accepted_end_asset_value_eur is not None
                and coinbase_connector.accepted_evidence_ref
                else self._external_valuation(provider, end_asset_date)
                if provider != "coinbase"
                else None
            )
            tracked = provider in {"binance", "moonpay"}
            end_status = "covered" if tracked or valuation is not None else "missing"
            if amount == 0 and not tracked:
                end_status = "covered"
            evidence_ref = (
                decisions.get(
                    flow_id, decisions.get("post_separation_investments", ("", None))
                )[1]
                or "/api/v1/divorce/inheritance-origin"
            )
            result.append(
                DivorceInheritanceProviderSummary(
                    provider=provider,
                    label=self.PROVIDER_LABELS[provider],
                    bank_transactions_count=len(bank_rows),
                    bank_outflow_eur=sum(
                        (item.amount_eur for item in bank_rows), Decimal("0")
                    ),
                    platform_only_transactions_count=len(platform_rows),
                    platform_only_outflow_eur=sum(
                        (item.amount_eur for item in platform_rows), Decimal("0")
                    ),
                    identified_investment_eur=amount,
                    capital_origin=(
                        "inheritance" if documented else "claimed_inheritance"
                    ),
                    capital_origin_evidence_status=(
                        "documented" if documented else "user_declared"
                    ),
                    portfolio_coverage_status=(
                        "tracked"
                        if tracked and not platform_rows
                        else "partial"
                        if tracked
                        else "not_connected"
                    ),
                    end_asset_valuation_status=end_status,
                    end_asset_value_eur=(valuation.value_eur if valuation else None),
                    end_asset_evidence_ref=(
                        valuation.evidence_ref if valuation else None
                    ),
                    evidence_ref=evidence_ref,
                    finding=self._provider_finding(
                        provider,
                        amount,
                        platform_rows,
                        valuation,
                    ),
                )
            )
        return result

    @staticmethod
    def _provider_finding(
        provider: str,
        amount: Decimal,
        platform_rows: list[DivorceInheritanceInvestmentFlow],
        valuation: _ExternalValuation | None,
    ) -> str:
        if amount == 0:
            return "Keine Investition im vorhandenen Zeitraum erkannt."
        if provider in {"trade_republic", "coinbase"} and valuation is None:
            return (
                "Kapitalabfluss belegt; Depot-/Kontobestand am Endvermoegensstichtag "
                "ist noch nicht importiert."
            )
        if platform_rows:
            return (
                "Krypto-Ledger erfasst; mindestens ein Plattformzufluss hat im "
                "vorhandenen Sparkassenzeitraum keinen Bankmatch."
            )
        return "Kapitalabfluss und erfasste Vermoegensquelle sind zugeordnet."

    def _capital_origin_decisions(self) -> dict[str, tuple[str, str | None]]:
        result: dict[str, tuple[str, str | None]] = {}
        for decision in self.store.list_review_decisions():
            if decision.decision_type != "divorce_capital_origin":
                continue
            flow_id = str(decision.payload.get("flow_id") or "")
            capital_origin = str(decision.payload.get("capital_origin") or "")
            if flow_id and capital_origin == "inheritance" and flow_id not in result:
                result[flow_id] = (capital_origin, decision.evidence_ref)
        return result

    def _external_valuation(
        self,
        provider: str,
        end_asset_date: date,
    ) -> _ExternalValuation | None:
        for decision in self.store.list_review_decisions():
            if decision.decision_type != "divorce_external_asset_valuation":
                continue
            if str(decision.payload.get("provider") or "") != provider:
                continue
            if (
                str(decision.payload.get("valuation_date") or "")
                != end_asset_date.isoformat()
            ):
                continue
            try:
                value = Decimal(str(decision.payload.get("value_eur")))
            except (InvalidOperation, TypeError):
                continue
            if decision.evidence_ref:
                return _ExternalValuation(
                    value_eur=value, evidence_ref=decision.evidence_ref
                )
        return None

    def _inheritance_bank_credit_decisions(self) -> dict[str, ReviewDecision]:
        result: dict[str, ReviewDecision] = {}
        for decision in self.store.list_review_decisions():
            if decision.decision_type != "divorce_inheritance_bank_credit":
                continue
            reference = str(decision.payload.get("transaction_reference_sha256") or "")
            credit_kind = str(decision.payload.get("credit_kind") or "")
            if (
                len(reference) == 64
                and credit_kind in {"estate_asset_realization", "estate_refund"}
                and reference not in result
            ):
                result[reference] = decision
        return result

    def _document_inheritance_credits(
        self,
        *,
        end_asset_date: date,
    ) -> list[DivorceInheritanceCreditEvidence]:
        known_documents = {
            item.document_sha256: item
            for item in self.inheritance_documents().documents
        }
        result: list[DivorceInheritanceCreditEvidence] = []
        seen_references: set[str] = set()
        for decision in self.store.list_review_decisions():
            if decision.decision_type != "divorce_inheritance_document_credit":
                continue
            document_sha256 = str(decision.payload.get("document_sha256") or "")
            document = known_documents.get(document_sha256)
            if document is None:
                continue
            try:
                document_date = date.fromisoformat(
                    str(decision.payload.get("document_date") or "")
                )
                amount_eur = Decimal(str(decision.payload.get("amount_eur")))
            except (InvalidOperation, TypeError, ValueError):
                continue
            credit_kind = str(decision.payload.get("credit_kind") or "")
            reference = str(decision.payload.get("transaction_reference_sha256") or "")
            if (
                document_date > end_asset_date
                or amount_eur <= 0
                or credit_kind not in {"estate_asset_realization", "estate_refund"}
                or len(reference) != 64
                or reference in seen_references
            ):
                continue
            seen_references.add(reference)
            result.append(
                DivorceInheritanceCreditEvidence(
                    booking_date=document_date,
                    amount_eur=amount_eur,
                    evidence_status="review",
                    evidence_source="supporting_document",
                    date_basis="document_date",
                    credit_kind=credit_kind,
                    classification_source="review_decision",
                    transaction_reference_sha256=reference,
                    source_file_sha256=document_sha256,
                    evidence_ref=document.evidence_ref,
                    review_decision_id=decision.decision_id,
                    note=(
                        "Nettobetrag aus einem geprueften Nachlassdokument; das Datum ist "
                        "das Dokumentdatum und kein behaupteter CAMT-Buchungstag."
                    ),
                )
            )
        return result

    def _credit_evidence(
        self,
        item: _BankEntry,
        decision: ReviewDecision | None,
    ) -> DivorceInheritanceCreditEvidence:
        automatic = item.is_inheritance_credit
        credit_kind = (
            "estate_account_transfer"
            if automatic
            else str(decision.payload.get("credit_kind") or "")
            if decision is not None
            else "estate_asset_realization"
        )
        return DivorceInheritanceCreditEvidence(
            booking_date=item.booking_date,
            amount_eur=item.amount_eur,
            evidence_status="bank_primary_evidence" if automatic else "review",
            evidence_source="bank_camt",
            date_basis="bank_booking_date",
            credit_kind=credit_kind,
            classification_source="camt_marker" if automatic else "review_decision",
            transaction_reference_sha256=item.reference_sha256,
            source_file_sha256=item.source_file_sha256,
            evidence_ref=self._bank_credit_evidence_ref(item),
            supporting_evidence_ref=(
                decision.evidence_ref if decision is not None else None
            ),
            review_decision_id=(decision.decision_id if decision is not None else None),
            note=(
                "CAMT-Gutschrift mit Nachlassmarker; Gegenpartei und Kontodaten werden "
                "im Report nicht offengelegt."
                if automatic
                else "CAMT-Gutschrift wurde per hashgebundener Review Decision als "
                "weiterer Erbmittelzufluss klassifiziert."
            ),
        )

    @staticmethod
    def _bank_credit_evidence_ref(item: _BankEntry) -> str:
        return f"bank-camt-entry:sha256:{item.reference_sha256}"

    @staticmethod
    def _primary_credit_evidence(
        credits: list[DivorceInheritanceCreditEvidence],
    ) -> DivorceInheritanceCreditEvidence | None:
        if not credits:
            return None
        account_transfers = [
            item for item in credits if item.credit_kind == "estate_account_transfer"
        ]
        candidates = account_transfers or credits
        return min(
            candidates,
            key=lambda item: (item.booking_date, item.transaction_reference_sha256),
        )

    @staticmethod
    def _first_bank_inheritance_credit_date(
        credits: list[DivorceInheritanceCreditEvidence],
    ) -> date | None:
        bank_dates = [
            item.booking_date for item in credits if item.evidence_source == "bank_camt"
        ]
        return min(bank_dates, default=None)

    def _trade_republic_connector(
        self,
        end_asset_date: date,
    ) -> TradeRepublicConnectorStatus:
        valuation = self._external_valuation("trade_republic", end_asset_date)
        return TradeRepublicDocumentService().scan(
            self.trade_republic_document_root,
            end_asset_date=end_asset_date,
            accepted_value_eur=valuation.value_eur if valuation else None,
            accepted_evidence_ref=valuation.evidence_ref if valuation else None,
        )

    def _coinbase_connector(
        self,
        end_asset_date: date,
        *,
        valuation_portfolio: PortfolioAsOfSnapshot | None = None,
    ) -> CoinbaseConnectorStatus:
        api_key = resolve_secret_value(self.store, "secret.cex.coinbase.api_key")
        api_secret = resolve_secret_value(self.store, "secret.cex.coinbase.api_secret")
        with self.store.connect() as con:
            history_rows = con.execute(
                """
                select
                    b.file_hash,
                    count(distinct b.batch_id) as batches_count,
                    count(e.event_id) as events_count,
                    min(e.event_time) as history_from,
                    max(e.event_time) as history_to
                from raw_import_batches b
                left join raw_objects r on r.batch_id = b.batch_id
                left join canonical_events e on e.raw_object_id = r.raw_object_id
                where lower(b.source) = 'coinbase'
                group by b.file_hash
                order by b.file_hash
                """
            ).fetchall()
            history_event_rows = con.execute(
                """
                select
                    b.file_hash,
                    e.event_id,
                    e.source_ref,
                    e.event_time,
                    e.event_type,
                    e.asset,
                    e.quantity,
                    e.quote_asset,
                    e.quote_quantity,
                    e.fee_asset,
                    e.fee_quantity,
                    e.tx_id,
                    e.wallet,
                    e.account,
                    e.confidence
                from raw_import_batches b
                join raw_objects r on r.batch_id = b.batch_id
                join canonical_events e on e.raw_object_id = r.raw_object_id
                where lower(b.source) = 'coinbase'
                order by b.file_hash, e.event_time, e.event_id
                """
            ).fetchall()
            live_row = con.execute(
                """
                with latest as (
                    select max(fetched_at) as fetched_at
                    from portfolio_live_balance_snapshots
                    where connector_id = 'coinbase'
                )
                select latest.fetched_at, count(distinct p.asset)
                from latest
                left join portfolio_live_balance_snapshots p
                  on p.connector_id = 'coinbase'
                 and p.fetched_at = latest.fetched_at
                group by latest.fetched_at
                """
            ).fetchone()
        batches_count = sum(int(row[1] or 0) for row in history_rows)
        events_count = sum(int(row[2] or 0) for row in history_rows)
        history_from_values = [row[3] for row in history_rows if row[3] is not None]
        history_to_values = [row[4] for row in history_rows if row[4] is not None]
        history_from = min(history_from_values, default=None)
        history_to = max(history_to_values, default=None)
        manifest_payload = {
            "batches": [
                {
                    "file_hash": str(row[0] or ""),
                    "batches_count": int(row[1] or 0),
                    "events_count": int(row[2] or 0),
                    "history_from": row[3].isoformat() if row[3] is not None else None,
                    "history_to": row[4].isoformat() if row[4] is not None else None,
                }
                for row in history_rows
            ],
            "events": [
                {
                    "file_hash": str(row[0] or ""),
                    "event_id": str(row[1] or ""),
                    "source_ref": str(row[2]) if row[2] is not None else None,
                    "event_time": row[3].isoformat(),
                    "event_type": str(row[4]),
                    "asset": str(row[5]),
                    "quantity": str(row[6]),
                    "quote_asset": str(row[7]) if row[7] is not None else None,
                    "quote_quantity": str(row[8]) if row[8] is not None else None,
                    "fee_asset": str(row[9]) if row[9] is not None else None,
                    "fee_quantity": str(row[10]) if row[10] is not None else None,
                    "tx_id": str(row[11]) if row[11] is not None else None,
                    "wallet": str(row[12]) if row[12] is not None else None,
                    "account": str(row[13]) if row[13] is not None else None,
                    "confidence": str(row[14]),
                }
                for row in history_event_rows
            ],
        }
        history_manifest_sha256 = (
            self._sha256(
                json.dumps(
                    manifest_payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("utf-8")
            )
            if history_rows
            else None
        )

        positions = []
        if events_count > 0:
            snapshot = valuation_portfolio or PortfolioService(
                self.store
            ).as_of_snapshot(
                datetime.combine(
                    end_asset_date,
                    time.max,
                    tzinfo=ZoneInfo("Europe/Berlin"),
                ).astimezone(timezone.utc)
            )
            positions = [
                item
                for item in snapshot.positions
                if "coinbase" in str(item.account or "").strip().lower()
            ]
        assets = [
            CoinbaseValuationAssetEvidence(
                asset=item.asset,
                quantity=item.quantity,
                value_eur=item.value_eur,
                price_source=item.price_source,
                priced_at=item.priced_at,
            )
            for item in positions
        ]
        missing_price_assets = sorted(
            {item.asset for item in positions if item.value_eur is None}
        )
        negative_quantity_assets = sorted(
            {item.asset for item in positions if item.quantity < 0}
        )
        candidate_value = (
            sum((item.value_eur or Decimal("0") for item in positions), Decimal("0"))
            if events_count > 0
            and not missing_price_assets
            and not negative_quantity_assets
            else None
        )

        accepted_value: Decimal | None = None
        accepted_evidence_ref: str | None = None
        for decision in self.store.list_review_decisions():
            if decision.decision_type != "divorce_external_asset_valuation":
                continue
            if str(decision.payload.get("provider") or "") != "coinbase":
                continue
            if (
                str(decision.payload.get("valuation_date") or "")
                != end_asset_date.isoformat()
            ):
                continue
            if (
                str(decision.payload.get("history_manifest_sha256") or "")
                != history_manifest_sha256
            ):
                continue
            try:
                decision_value = Decimal(str(decision.payload.get("value_eur")))
            except (InvalidOperation, TypeError):
                continue
            if decision_value != candidate_value or not decision.evidence_ref:
                continue
            accepted_value = decision_value
            accepted_evidence_ref = decision.evidence_ref
            break
        history_status = (
            "reviewed"
            if accepted_value is not None
            else "imported_pending_review"
            if events_count > 0
            else "missing"
        )
        review_ready = (
            history_status == "imported_pending_review"
            and candidate_value is not None
            and history_manifest_sha256 is not None
        )
        note = (
            "Die vollstaendige Coinbase-Historie und der daraus berechnete Stichtagswert wurden per Review Decision gebunden."
            if history_status == "reviewed"
            else "Coinbase-Historie ist importiert. Vor der Freigabe muessen Vollstaendigkeit ab Kontoeroeffnung, Mengen und Stichtagspreise geprueft werden."
            if history_status == "imported_pending_review"
            else "Coinbase ist als eigene Quelle registriert. Fuer den historischen Stichtagswert fehlt noch die vollstaendige Transaction History."
        )
        return CoinbaseConnectorStatus(
            official_accounts_api_url=self.OFFICIAL_COINBASE_ACCOUNTS_API,
            official_transactions_api_url=self.OFFICIAL_COINBASE_TRANSACTIONS_API,
            official_statements_help_url=self.OFFICIAL_COINBASE_STATEMENTS_HELP,
            credential_status="configured" if api_key and api_secret else "missing",
            latest_live_snapshot_at=(live_row[0] if live_row else None),
            latest_live_assets_count=int(live_row[1] or 0) if live_row else 0,
            history_batches_count=batches_count,
            history_events_count=events_count,
            history_from=history_from,
            history_to=history_to,
            history_manifest_sha256=history_manifest_sha256,
            history_status=history_status,
            valuation_review_ready=review_ready,
            candidate_end_asset_value_eur=candidate_value,
            accepted_end_asset_value_eur=accepted_value,
            accepted_evidence_ref=accepted_evidence_ref,
            missing_price_assets=missing_price_assets,
            negative_quantity_assets=negative_quantity_assets,
            assets=assets,
            note=note,
        )

    def _formal_inheritance_connector(self) -> InheritanceDocumentConnectorStatus:
        reviewed_document_sha256: str | None = None
        reviewed_evidence_ref: str | None = None
        for decision in self.store.list_review_decisions():
            if decision.decision_type != "divorce_formal_inheritance_evidence":
                continue
            candidate_sha256 = str(decision.payload.get("document_sha256") or "")
            if (
                re.fullmatch(r"[0-9a-f]{64}", candidate_sha256)
                and decision.evidence_ref
            ):
                reviewed_document_sha256 = candidate_sha256
                reviewed_evidence_ref = decision.evidence_ref
                break
        return InheritanceDocumentService().scan(
            self.inheritance_document_root,
            configured_path=self.inheritance_document_path,
            reviewed_document_sha256=reviewed_document_sha256,
            reviewed_evidence_ref=reviewed_evidence_ref,
        )

    @staticmethod
    def _opening_balance(balances: list[_BankBalance]) -> Decimal | None:
        opening = [item for item in balances if item.balance_type == "OPBD"]
        if opening:
            return min(opening, key=lambda item: item.balance_date).balance_eur
        closing = [item for item in balances if item.balance_type == "CLBD"]
        return (
            min(closing, key=lambda item: item.balance_date).balance_eur
            if closing
            else None
        )

    @staticmethod
    def _closing_balance(
        balances: list[_BankBalance],
        end_asset_date: date,
    ) -> Decimal | None:
        candidates = [
            item
            for item in balances
            if item.balance_type == "CLBD" and item.balance_date <= end_asset_date
        ]
        return (
            max(candidates, key=lambda item: item.balance_date).balance_eur
            if candidates
            else None
        )

    @staticmethod
    def _minimum_balance_after_credit(
        balances: list[_BankBalance],
        credit_date: date | None,
        end_asset_date: date,
    ) -> Decimal | None:
        if credit_date is None:
            return None
        candidates = [
            item.balance_eur
            for item in balances
            if item.balance_type == "CLBD"
            and credit_date <= item.balance_date <= end_asset_date
        ]
        return min(candidates) if candidates else None

    @staticmethod
    def _findings(
        *,
        bank_statement_status: str,
        statement_from: date | None,
        inheritance_credits: list[DivorceInheritanceCreditEvidence],
        headroom: Decimal | None,
        formal_document_status: str,
        user_declaration_status: str,
        missing_external_valuations: list[str],
        flows: list[DivorceInheritanceInvestmentFlow],
        parse_errors: list[str],
    ) -> list[str]:
        findings: list[str] = []
        if bank_statement_status != "complete":
            findings.append(
                "Der Sparkassenexport beginnt erst am "
                f"{statement_from.strftime('%d.%m.%Y') if statement_from else 'unbekannten Datum'}; "
                "der Zeitraum ab 13.06.2025 ist damit nicht vollstaendig bankseitig belegt."
            )
        if not inheritance_credits:
            findings.append(
                "Es ist noch kein eindeutiger Erbmittelzufluss mit Bank- oder "
                "Dokumentbeleg klassifiziert."
            )
        if headroom is not None and headroom < 0:
            findings.append(
                "Die identifizierten Investitionen uebersteigen die erkannte Nachlassgutschrift."
            )
        if formal_document_status != "documented":
            findings.append(
                "Formaler Erbnachweis ist noch nicht per SHA-256 referenziert."
            )
        if user_declaration_status != "recorded":
            findings.append(
                "Die Erbgeld-Zuordnung ist noch nicht fuer alle erkannten Anbieter als Review Decision gespeichert."
            )
        if missing_external_valuations:
            labels = ", ".join(
                DivorceInheritanceOriginService.PROVIDER_LABELS[item]
                for item in missing_external_valuations
            )
            findings.append(f"Endvermoegenswert zum 24.07.2026 fehlt fuer: {labels}.")
        credit_dates = [item.booking_date for item in inheritance_credits]
        if credit_dates and any(
            item.booking_date < min(credit_dates) for item in flows
        ):
            findings.append(
                "Mindestens ein erkannter Investmentabfluss liegt vor der Nachlassgutschrift und braucht einen separaten Herkunftsbeleg."
            )
        findings.extend(parse_errors)
        if not findings:
            findings.append(
                "Mittelherkunft und externe Stichtagswerte sind vollstaendig belegt."
            )
        return findings

    @staticmethod
    def _next_actions(
        *,
        bank_statement_status: str,
        separation_date: date,
        statement_from: date | None,
        formal_document_status: str,
        user_declaration_status: str,
        missing_external_valuations: list[str],
        trade_republic_connector: TradeRepublicConnectorStatus,
        coinbase_connector: CoinbaseConnectorStatus,
    ) -> list[str]:
        actions: list[str] = []
        if bank_statement_status != "complete":
            if statement_from is not None and statement_from > separation_date:
                missing_to = statement_from - timedelta(days=1)
                actions.append(
                    "Sparkassen-Kontoauszug fuer "
                    f"{separation_date.strftime('%d.%m.%Y')} bis "
                    f"{missing_to.strftime('%d.%m.%Y')} nachreichen."
                )
            else:
                actions.append(
                    "Sparkassen-Kontoauszug ab dem Trennungsstichtag nachreichen."
                )
        if formal_document_status != "documented":
            actions.append(
                "Erbschein, Testament/Erbvertrag oder Nachlassabrechnung als formalen Erbnachweis referenzieren."
            )
        if user_declaration_status != "recorded":
            actions.append(
                "Erbgeld-Zuordnung je Anbieter ueber Review Decisions dokumentieren."
            )
        if "trade_republic" in missing_external_valuations:
            if trade_republic_connector.valuation_review_ready:
                actions.append(
                    "Extrahierten Trade-Republic-Stichtagswert gegen den Originalbeleg pruefen und explizit freigeben."
                )
            else:
                actions.append(
                    "Trade-Republic-Kontoauszuege, Einzelabrechnungen und Depot-/Cash-Auszug zum 24.07.2026 importieren."
                )
        if "coinbase" in missing_external_valuations:
            if coinbase_connector.valuation_review_ready:
                actions.append(
                    "Coinbase-Historie ab Kontoeroeffnung gegen den Originalexport pruefen und den berechneten Stichtagswert freigeben."
                )
            elif coinbase_connector.history_events_count > 0:
                actions.append(
                    "Coinbase-Mengen- und Preisblocker im Historienstatus beheben."
                )
            else:
                actions.append(
                    "Vollstaendige Coinbase-Transaction-History seit Kontoeroeffnung importieren."
                )
        if trade_republic_connector.document_files_count == 0:
            actions.append(
                f"Offizielle Trade-Republic-Dokumente unter {trade_republic_connector.document_root} ablegen."
            )
        return actions

    def _discover_bank_camt_dir(self) -> Path | None:
        if not self.DEFAULT_BANK_CAMT_ROOT.is_dir():
            return None
        candidates = sorted(
            path
            for path in self.DEFAULT_BANK_CAMT_ROOT.glob("*-camt52v8Booked")
            if path.is_dir()
        )
        return candidates[-1] if candidates else None

    @staticmethod
    def _bank_statement_coverage(
        intervals: list[tuple[date, date]],
        *,
        required_from: date,
        required_to: date,
    ) -> tuple[str, date | None, date | None]:
        valid = sorted(
            (start, end)
            for start, end in intervals
            if start <= end
        )
        if not valid:
            return "missing", None, None
        merged: list[tuple[date, date]] = []
        for start, end in valid:
            if merged and start <= merged[-1][1] + timedelta(days=1):
                previous_start, previous_end = merged[-1]
                merged[-1] = (previous_start, max(previous_end, end))
            else:
                merged.append((start, end))
        complete = any(
            start <= required_from and end >= required_to
            for start, end in merged
        )
        return (
            "complete" if complete else "partial",
            min(start for start, _end in valid),
            max(end for _start, end in valid),
        )

    def _discover_sparkasse_statement_dir(self) -> Path:
        root = self.DEFAULT_SPARKASSE_STATEMENT_DISCOVERY_ROOT
        if root.is_dir():
            candidates = {
                path
                for pattern in (
                    "S_*_Postfach_-_Sammeldownload",
                    "Sparkasse/*Sammeldownload*",
                )
                for path in root.glob(pattern)
                if path.is_dir()
                and SparkasseStatementDocumentService.statement_paths(path)
            }
            if candidates:
                return max(
                    candidates,
                    key=lambda path: (
                        len(SparkasseStatementDocumentService.statement_paths(path)),
                        str(path),
                    ),
                )
        return self.DEFAULT_BANK_CAMT_ROOT / "statements-managed"

    @staticmethod
    def _parse_eur_amount(value: str | None) -> Decimal | None:
        if not value:
            return None
        text = re.sub(r"[^0-9,.-]", "", str(value)).strip()
        if not text:
            return None
        if "," in text:
            text = text.replace(".", "").replace(",", ".")
        try:
            return Decimal(text)
        except InvalidOperation:
            return None

    @staticmethod
    def _elements(root: ET.Element, local_name: str):
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] == local_name:
                yield element

    @staticmethod
    def _direct_children(root: ET.Element, local_name: str):
        for element in root:
            if element.tag.rsplit("}", 1)[-1] == local_name:
                yield element

    @classmethod
    def _first_text(cls, root: ET.Element, local_name: str) -> str | None:
        for element in cls._elements(root, local_name):
            value = str(element.text or "").strip()
            if value:
                return value
        return None

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
