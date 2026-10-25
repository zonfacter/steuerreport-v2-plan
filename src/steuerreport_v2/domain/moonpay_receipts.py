from __future__ import annotations

from steuerreport_v2.paths import PROJECT_ROOT as SOFTWARE_ROOT

from steuerreport_v2.private_settings import private_value
from steuerreport_v2.paths import configured_import_path

import base64
import binascii
import csv
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
from threading import RLock
import xml.etree.ElementTree as ET

from steuerreport_v2.contracts.events import CanonicalEvent
from steuerreport_v2.contracts.moonpay_receipts import (
    MoonpayReceiptDecisionLayer,
    MoonpayReceiptItem,
    MoonpayReceiptReport,
    MoonpayReceiptUpsertRequest,
    MoonpayReceiptUpsertResult,
    MoonpayTradeHistoryRow,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup


@dataclass(frozen=True)
class _MoonpayTrade:
    trade_id: str
    operation: str
    status: str
    payment_currency: str
    payment_amount: Decimal
    paid_at: datetime
    quote_currency: str
    received_quantity: Decimal
    service_fee_eur: Decimal
    extra_fee_eur: Decimal
    network_fee_eur: Decimal

    @property
    def asset(self) -> str | None:
        return {"sol": "SOL", "usdc_sol": "USDC"}.get(self.quote_currency.lower())

    @property
    def fee_components_eur(self) -> Decimal:
        return self.service_fee_eur + self.extra_fee_eur + self.network_fee_eur

    @property
    def gross_payment_amount_eur(self) -> Decimal:
        return self.payment_amount + self.fee_components_eur


@dataclass(frozen=True)
class _SparkasseDebit:
    amount_eur: Decimal
    booking_date: date
    merchant_time: datetime | None
    reference: str
    source_file: str


class MoonpayReceiptService:
    PROJECT_ROOT = SOFTWARE_ROOT
    DEFAULT_DB_PATH = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
    DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT / "var/moonpay_receipts"
    DEFAULT_MANIFEST_PATH = DEFAULT_ARTIFACT_ROOT / "manifest.json"
    DEFAULT_TRADE_HISTORY_PATH = configured_import_path("moonpay_history_file", "MoonPay_trade-history.csv")
    DEFAULT_BANK_CAMT_ROOT = configured_import_path("bank_camt_root", "bank/camt")
    DEFAULT_PROVENANCE_DIR = PROJECT_ROOT / "var/solana_provenance_batches"
    DEFAULT_ALCHEMY_AUDIT_PATH = (
        PROJECT_ROOT / "var/solana_tx_alchemy_audits/latest_all_tx_alchemy_audit.json"
    )
    MOONPAY_SOLANA_SENDER = private_value('configured_identifier_80', '')
    KNOWN_RECEIVER_WALLETS = frozenset(
        value for value in {
            private_value('secondary_solana_wallet', ''),
            private_value('primary_solana_wallet', ''),
        } if value
    )
    QUANTITY_TOLERANCE = Decimal("0.000000001")
    MAX_TRADE_MATCH_TIME_DELTA_SECONDS = 5 * 60
    MAX_BANK_MATCH_TIME_DELTA_SECONDS = 6 * 60 * 60
    MAX_DOCUMENT_BYTES = 15 * 1024 * 1024
    MAX_PAYMENT_TIME_DELTA_SECONDS = 14 * 24 * 60 * 60
    REQUIRED_TRADE_HISTORY_COLUMNS = frozenset(
        {
            "id",
            "operation",
            "baseCurrency",
            "baseCurrencyAmount",
            "createdAt",
            "quoteCurrency",
            "quoteCurrencyAmount",
            "feeAmount",
            "extraFeeAmount",
            "networkFeeAmount",
            "status",
        }
    )
    MEDIA_EXTENSIONS = {
        "application/pdf": ".pdf",
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "text/csv": ".csv",
        "text/plain": ".txt",
    }
    _write_lock = RLock()

    def __init__(
        self,
        store: DuckDbStore,
        *,
        manifest_path: Path | None = None,
        trade_history_path: Path | None = None,
        provenance_dir: Path | None = None,
        alchemy_audit_path: Path | None = None,
        bank_camt_dir: Path | None = None,
    ) -> None:
        self.store = store
        self.manifest_path = manifest_path or self.DEFAULT_MANIFEST_PATH
        configured_trade_history = os.getenv(
            "STEUERREPORT_MOONPAY_TRADE_HISTORY_PATH"
        )
        self.trade_history_path = trade_history_path or (
            Path(configured_trade_history)
            if configured_trade_history
            else self.DEFAULT_TRADE_HISTORY_PATH
        )
        self.artifact_root = self.manifest_path.parent
        self.files_root = self.artifact_root / "files"
        self.provenance_dir = provenance_dir or self.DEFAULT_PROVENANCE_DIR
        self.alchemy_audit_path = alchemy_audit_path or self.DEFAULT_ALCHEMY_AUDIT_PATH
        configured_bank_camt_dir = os.getenv("STEUERREPORT_SPARKASSE_CAMT_DIR")
        use_instance_default = self.store.path.resolve() == self.DEFAULT_DB_PATH.resolve()
        self.bank_camt_dir = bank_camt_dir or (
            Path(configured_bank_camt_dir)
            if configured_bank_camt_dir
            else self._discover_bank_camt_dir()
            if use_instance_default
            else None
        )
        self.price_lookup = HistoricalPriceLookup(store)

    def _discover_bank_camt_dir(self) -> Path | None:
        if not self.DEFAULT_BANK_CAMT_ROOT.is_dir():
            return None
        candidates = sorted(
            path
            for path in self.DEFAULT_BANK_CAMT_ROOT.glob("*-camt52v8Booked")
            if path.is_dir()
        )
        return candidates[-1] if candidates else None

    def report(self, *, as_of: datetime | None = None) -> MoonpayReceiptReport:
        methodology = (
            "Read-only MoonPay-Anschaffungsnachweis. Der originale Trade-History-"
            "Export wird per SHA-256 gebunden und nach EUR-Zahlbetrag, Asset, exakter "
            "Menge sowie engem UTC-Zeitfenster eindeutig den vorhandenen Solana-"
            "Events zugeordnet. Sender und Empfaenger werden aus lokal archivierter "
            "Alchemy-/RPC-Provenance bestaetigt. Die Anschaffungskosten sind "
            "baseCurrencyAmount plus feeAmount, extraFeeAmount und networkFeeAmount. "
            "Ein optionaler Sparkassen-CAMT-Primaerbeleg wird read-only gehasht und "
            "nach Bruttobetrag sowie Haendlerzeit eindeutig gematcht. Kontonummern und "
            "sonstige Bankumsaetze werden nicht ausgegeben oder importiert. Der Report "
            "schreibt weder Canonical Events noch Tax-Lots, Tax-Lines, Ledger- oder "
            "Reviewdaten."
        )
        normalized_as_of = self._as_utc(as_of) if as_of is not None else None
        candidates, candidate_errors = self._candidate_events()
        trades, trade_errors = self._load_trade_history()
        bank_debits, bank_errors, bank_semantic_sha256, bank_files_count = (
            self._load_sparkasse_debits()
        )
        if normalized_as_of is not None:
            candidates = [
                item
                for item in candidates
                if self._as_utc(item[0].event_time) <= normalized_as_of
            ]
            trades = [trade for trade in trades if trade.paid_at <= normalized_as_of]
            bank_debits = [
                debit
                for debit in bank_debits
                if debit.booking_date <= normalized_as_of.date()
            ]

        manifest, manifest_errors = self._load_manifest()
        receipts = manifest.get("receipts")
        receipt_entries = receipts if isinstance(receipts, dict) else {}
        matches, match_errors = self._match_trades(candidates, trades)
        matched_trade_ids = {trade.trade_id for trade in matches.values()}
        bank_required = self.bank_camt_dir is not None and self.bank_camt_dir.is_dir()
        bank_matches, bank_match_errors = (
            self._match_bank_debits(trades, bank_debits)
            if bank_required
            else ({}, [])
        )

        items: list[MoonpayReceiptItem] = []
        for event, provenance in candidates:
            trade = matches.get(event.event_id)
            entry = receipt_entries.get(str(event.tx_id))
            items.append(
                self._item(
                    event=event,
                    provenance=provenance,
                    trade=trade,
                    bank_debit=(bank_matches.get(trade.trade_id) if trade else None),
                    bank_required=bank_required,
                    bank_evidence_sha256=bank_semantic_sha256,
                    entry=entry if trade is None and isinstance(entry, dict) else None,
                )
            )

        trade_rows = [
            MoonpayTradeHistoryRow(
                trade_id=trade.trade_id,
                operation=trade.operation,
                status=trade.status,
                paid_at=trade.paid_at,
                payment_currency=trade.payment_currency.upper(),
                payment_amount=trade.payment_amount,
                gross_payment_amount=trade.gross_payment_amount_eur,
                quote_currency=trade.quote_currency,
                asset=trade.asset,
                received_quantity=trade.received_quantity,
                service_fee_eur=trade.service_fee_eur,
                extra_fee_eur=trade.extra_fee_eur,
                network_fee_eur=trade.network_fee_eur,
                matched=trade.trade_id in matched_trade_ids,
                matched_tx_id=next(
                    (
                        str(event.tx_id)
                        for event, _provenance in candidates
                        if matches.get(event.event_id) == trade
                    ),
                    None,
                ),
                bank_debit_matched=trade.trade_id in bank_matches,
                bank_debit_amount_eur=(
                    bank_matches[trade.trade_id].amount_eur
                    if trade.trade_id in bank_matches
                    else None
                ),
                bank_booking_date=(
                    bank_matches[trade.trade_id].booking_date.isoformat()
                    if trade.trade_id in bank_matches
                    else None
                ),
                match_error=(
                    None
                    if trade.trade_id in matched_trade_ids
                    and (not bank_required or trade.trade_id in bank_matches)
                    else "bank_debit_match_missing"
                    if trade.trade_id in matched_trade_ids and bank_required
                    else "onchain_match_missing"
                    if self._is_supported_completed_buy(trade)
                    else "unsupported_or_incomplete_trade"
                ),
            )
            for trade in trades
        ]
        ready_count = sum(item.strict_ready for item in items)
        missing_count = sum(item.status == "receipt_required" for item in items)
        invalid_count = sum(item.status == "receipt_invalid" for item in items)
        supported_buys = [trade for trade in trades if self._is_supported_completed_buy(trade)]
        unmatched_supported = [
            trade for trade in supported_buys if trade.trade_id not in matched_trade_ids
        ]
        all_errors = (
            candidate_errors
            + trade_errors
            + bank_errors
            + manifest_errors
            + match_errors
            + bank_match_errors
        )
        strict_ready = bool(
            items
            and ready_count == len(items)
            and len(matched_trade_ids) == len(supported_buys)
            and not unmatched_supported
            and (not bank_required or len(bank_matches) == len(supported_buys))
            and not all_errors
        )
        status = (
            "ready"
            if strict_ready
            else "review_required"
            if invalid_count or all_errors or unmatched_supported
            else "evidence_required"
        )
        semantic_payload = {
            "sender_address": self.MOONPAY_SOLANA_SENDER,
            "as_of": normalized_as_of.isoformat() if normalized_as_of else None,
            "trade_history_sha256": self._file_sha256(self.trade_history_path),
            "bank_camt_semantic_sha256": bank_semantic_sha256,
            "items": [
                item.model_dump(mode="json", exclude={"document_download_url"})
                for item in items
            ],
            "trade_rows": [item.model_dump(mode="json") for item in trade_rows],
            "errors": all_errors,
        }
        semantic_sha256 = hashlib.sha256(
            json.dumps(
                semantic_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        trade_history_exists = self.trade_history_path.is_file()
        trade_history_size = (
            self.trade_history_path.stat().st_size if trade_history_exists else 0
        )
        return MoonpayReceiptReport(
            generated_at=datetime.now(timezone.utc),
            status=status,
            strict_ready=strict_ready,
            sender_address=self.MOONPAY_SOLANA_SENDER,
            manifest_path=self._display_path(self.manifest_path),
            trade_history_path=self._display_path(self.trade_history_path),
            trade_history_exists=trade_history_exists,
            trade_history_sha256=self._file_sha256(self.trade_history_path),
            trade_history_size_bytes=trade_history_size,
            trade_history_rows_count=len(trades),
            completed_buy_rows_count=len(supported_buys),
            matched_trade_rows_count=len(matched_trade_ids),
            unmatched_trade_rows_count=len(unmatched_supported),
            invalid_trade_rows_count=len(trade_errors),
            candidates_count=len(items),
            ready_count=ready_count,
            missing_count=missing_count,
            invalid_count=invalid_count,
            total_received_quantity=sum(
                (item.received_quantity for item in items), Decimal("0")
            ),
            total_provisional_market_value_eur=sum(
                (item.provisional_market_value_eur for item in items), Decimal("0")
            ),
            total_base_payment_amount_eur=sum(
                (trade.payment_amount for trade in supported_buys), Decimal("0")
            ),
            total_receipt_cost_basis_eur=sum(
                (
                    item.cost_basis_eur
                    for item in items
                    if item.cost_basis_eur is not None and item.strict_ready
                ),
                Decimal("0"),
            ),
            total_fee_components_eur=sum(
                (trade.fee_components_eur for trade in supported_buys), Decimal("0")
            ),
            total_bank_debits_eur=sum(
                (debit.amount_eur for debit in bank_matches.values()),
                Decimal("0"),
            ),
            bank_camt_path=(
                "external:Sparkasse/camt52v8Booked"
                if self.bank_camt_dir is not None
                else None
            ),
            bank_camt_exists=bank_required,
            bank_camt_files_count=bank_files_count,
            bank_camt_semantic_sha256=bank_semantic_sha256,
            bank_debits_count=len(bank_debits),
            bank_debits_matched_count=len(bank_matches),
            bank_debits_unmatched_count=max(len(bank_debits) - len(bank_matches), 0),
            items=items,
            trade_rows=trade_rows,
            semantic_sha256=semantic_sha256,
            methodology=methodology,
        )

    def upsert(self, request: MoonpayReceiptUpsertRequest) -> MoonpayReceiptUpsertResult:
        candidates = {item.tx_id: item for item in self.report().items}
        candidate = candidates.get(request.tx_id)
        if candidate is None:
            raise ValueError("moonpay_onchain_transaction_not_found")
        if abs(request.received_quantity - candidate.received_quantity) > self.QUANTITY_TOLERANCE:
            raise ValueError("moonpay_receipt_quantity_mismatch")
        if request.fee_eur > request.payment_amount_eur:
            raise ValueError("moonpay_receipt_fee_exceeds_payment")
        paid_at = self._as_utc(request.paid_at)
        event_time = self._as_utc(candidate.event_time)
        if abs((paid_at - event_time).total_seconds()) > self.MAX_PAYMENT_TIME_DELTA_SECONDS:
            raise ValueError("moonpay_receipt_payment_time_outside_14_days")
        content = self._decode_document(request.content_base64)
        self._validate_document(content, request.media_type, request.filename)
        document_sha256 = hashlib.sha256(content).hexdigest()
        extension = self.MEDIA_EXTENSIONS[request.media_type]
        stored_filename = f"{request.tx_id[:16]}_{document_sha256[:20]}{extension}"
        document_path = self.files_root / stored_filename
        entry = {
            "tx_id": request.tx_id,
            "event_id": candidate.event_id,
            "event_time": event_time.isoformat(),
            "sender_address": candidate.sender_address,
            "receiver_wallet": candidate.receiver_wallet,
            "asset": candidate.asset,
            "received_quantity": str(request.received_quantity),
            "payment_amount_eur": str(request.payment_amount_eur),
            "fee_eur": str(request.fee_eur),
            "payment_currency": request.payment_currency,
            "payment_method": request.payment_method.strip(),
            "paid_at": paid_at.isoformat(),
            "original_filename": Path(request.filename).name,
            "document_filename": stored_filename,
            "document_media_type": request.media_type,
            "document_sha256": document_sha256,
            "document_size_bytes": len(content),
            "note": request.note,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._write_lock:
            self.files_root.mkdir(parents=True, exist_ok=True)
            self._atomic_write(document_path, content)
            manifest, _errors = self._load_manifest()
            receipts = manifest.get("receipts")
            if not isinstance(receipts, dict):
                receipts = {}
            receipts[request.tx_id] = entry
            self._atomic_write(
                self.manifest_path,
                json.dumps(
                    {
                        "schema_version": 1,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                        "receipts": receipts,
                    },
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
            )
        item = next(row for row in self.report().items if row.tx_id == request.tx_id)
        if not item.strict_ready:
            raise RuntimeError("moonpay_receipt_postcheck_failed:" + ",".join(item.errors))
        return MoonpayReceiptUpsertResult(
            item=item,
            manifest_path=self._display_path(self.manifest_path),
            message=(
                "Primaerbeleg SHA-256-gesichert und der On-chain-Anschaffung "
                "zugeordnet. Steuer- und Wallet-FIFO muessen bewusst neu berechnet "
                "werden, bevor die Kostenbasis produktiv wirkt."
            ),
        )

    def ready_cost_basis_by_tx(
        self, *, as_of: datetime | None = None
    ) -> dict[str, MoonpayReceiptItem]:
        return {
            item.tx_id: item
            for item in self.report(as_of=as_of).items
            if item.strict_ready and item.cost_basis_eur is not None
        }

    def ready_cost_basis_by_event(
        self, *, as_of: datetime | None = None
    ) -> dict[str, MoonpayReceiptItem]:
        return {
            item.event_id: item
            for item in self.report(as_of=as_of).items
            if item.strict_ready and item.cost_basis_eur is not None
        }

    def evidence_fingerprint(self) -> dict[str, object]:
        _debits, _errors, bank_semantic_sha256, bank_files_count = (
            self._load_sparkasse_debits()
        )
        return {
            "trade_history_path": self._display_path(self.trade_history_path),
            "trade_history_sha256": self._file_sha256(self.trade_history_path),
            "alchemy_audit_sha256": self._file_sha256(self.alchemy_audit_path),
            "manifest_sha256": self._file_sha256(self.manifest_path),
            "bank_camt_path": (
                "external:Sparkasse/camt52v8Booked"
                if self.bank_camt_dir is not None
                else None
            ),
            "bank_camt_semantic_sha256": bank_semantic_sha256,
            "bank_camt_files_count": bank_files_count,
        }

    def document_path(self, tx_id: str) -> Path | None:
        item = next((row for row in self.report().items if row.tx_id == tx_id), None)
        if item is None or not item.strict_ready:
            return None
        if item.evidence_source == "trade_history_csv":
            return self.trade_history_path if self.trade_history_path.is_file() else None
        if not item.document_filename:
            return None
        path = (self.files_root / item.document_filename).resolve()
        if path.parent != self.files_root.resolve() or not path.is_file():
            return None
        if hashlib.sha256(path.read_bytes()).hexdigest() != item.document_sha256:
            return None
        return path

    def _candidate_events(
        self,
    ) -> tuple[list[tuple[CanonicalEvent, dict[str, object]]], list[str]]:
        receiver_wallets = sorted(self.KNOWN_RECEIVER_WALLETS)
        if not receiver_wallets:
            return [], []
        receiver_placeholders = ", ".join("?" for _ in receiver_wallets)
        classifications: dict[str, dict[str, object]] = {}
        errors: list[str] = []
        with self.store.connect() as con:
            candidate_rows = con.execute(
                f"""
                select distinct tx_id
                from canonical_events
                where lower(source) = 'solana_rpc'
                  and upper(asset) in ('SOL', 'USDC')
                  and quantity > 0
                  and tx_id is not null
                  and coalesce(account, wallet, '') in ({receiver_placeholders})
                """,
                receiver_wallets,
            ).fetchall()
        candidate_signatures = {str(row[0]) for row in candidate_rows if row[0]}
        if not candidate_signatures:
            return [], []
        audit, audit_errors = self._load_json(self.alchemy_audit_path, "alchemy_audit")
        errors.extend(audit_errors)
        rows = audit.get("rows") if isinstance(audit, dict) else None
        if isinstance(rows, list):
            for value in rows:
                if not isinstance(value, dict):
                    continue
                signature = str(value.get("tx_id") or "")
                signers = {str(item) for item in value.get("signers") or []}
                accounts = {str(item) for item in value.get("accounts") or []}
                if (
                    signature
                    and signature in candidate_signatures
                    and self.MOONPAY_SOLANA_SENDER in signers
                    and bool(value.get("onchain_confirmed"))
                    and accounts.intersection(self.KNOWN_RECEIVER_WALLETS)
                    and {item.upper() for item in str(value.get("assets") or "").split(",")}
                    .intersection({"SOL", "USDC"})
                ):
                    classifications[signature] = {
                        **value,
                        "sender_owner": self.MOONPAY_SOLANA_SENDER,
                        "receiver_owner": next(iter(accounts.intersection(self.KNOWN_RECEIVER_WALLETS))),
                        "evidence_source": self._display_path(self.alchemy_audit_path),
                    }

        fallback, fallback_errors = self._sol_provenance_classifications()
        for signature, value in fallback.items():
            if signature in candidate_signatures:
                classifications.setdefault(signature, value)
        if not classifications:
            errors.extend(fallback_errors)
        if not classifications:
            return [], errors
        signatures = sorted(classifications)
        placeholders = ",".join("?" for _ in signatures)
        with self.store.connect() as con:
            rows = con.execute(
                f"""
                select event_id, source, source_ref, event_time, event_type,
                       asset, quantity, quote_asset, quote_quantity,
                       fee_asset, fee_quantity, tx_id, wallet, account,
                       confidence, raw_object_id
                from canonical_events
                where tx_id in ({placeholders})
                  and lower(source) = 'solana_rpc'
                  and upper(asset) in ('SOL', 'USDC')
                  and quantity > 0
                order by event_time, event_id
                """,
                signatures,
            ).fetchall()
        result: list[tuple[CanonicalEvent, dict[str, object]]] = []
        seen_tx: set[str] = set()
        for row in rows:
            event = CanonicalEvent(
                event_id=row[0], source=row[1], source_ref=row[2], event_time=row[3],
                event_type=row[4], asset=row[5], quantity=row[6], quote_asset=row[7],
                quote_quantity=row[8], fee_asset=row[9], fee_quantity=row[10],
                tx_id=row[11], wallet=row[12], account=row[13], confidence=row[14],
                raw_object_id=row[15],
            )
            tx_id = str(event.tx_id or "")
            provenance = classifications[tx_id]
            receiver = str(event.account or event.wallet or "")
            if receiver != str(provenance.get("receiver_owner") or ""):
                errors.append(f"provenance_database_receiver_mismatch:{tx_id}")
                continue
            if tx_id in seen_tx:
                errors.append(f"duplicate_positive_onchain_event:{tx_id}")
                continue
            seen_tx.add(tx_id)
            result.append((event, provenance))
        missing = set(signatures) - seen_tx
        errors.extend(f"canonical_event_missing:{signature}" for signature in sorted(missing))
        return result, errors

    def _sol_provenance_classifications(
        self,
    ) -> tuple[dict[str, dict[str, object]], list[str]]:
        result: dict[str, dict[str, object]] = {}
        errors: list[str] = []
        try:
            paths = sorted(self.provenance_dir.glob("latest_*_SOL_provenance_classification.json"))
        except OSError as exc:
            return {}, [f"provenance_directory_read_failed:{exc}"]
        for path in paths:
            payload, path_errors = self._load_json(path, "provenance")
            errors.extend(path_errors)
            values = payload.get("classifications") if isinstance(payload, dict) else None
            if not isinstance(values, list) or int(payload.get("failed_count") or 0):
                continue
            for value in values:
                if not isinstance(value, dict):
                    continue
                signature = str(value.get("signature") or "")
                if (
                    signature
                    and str(value.get("sender_owner") or "") == self.MOONPAY_SOLANA_SENDER
                    and str(value.get("receiver_owner") or "") in self.KNOWN_RECEIVER_WALLETS
                ):
                    result[signature] = {
                        **value,
                        "evidence_source": self._display_path(path),
                    }
        return result, errors

    def _load_trade_history(self) -> tuple[list[_MoonpayTrade], list[str]]:
        if not self.trade_history_path.is_file():
            return [], ["trade_history_missing"]
        try:
            with self.trade_history_path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                fields = set(reader.fieldnames or [])
                if not self.REQUIRED_TRADE_HISTORY_COLUMNS.issubset(fields):
                    missing = sorted(self.REQUIRED_TRADE_HISTORY_COLUMNS - fields)
                    return [], ["trade_history_columns_missing:" + ",".join(missing)]
                raw_rows = list(reader)
        except (OSError, UnicodeDecodeError, csv.Error) as exc:
            return [], [f"trade_history_read_failed:{exc}"]
        trades: list[_MoonpayTrade] = []
        errors: list[str] = []
        seen_ids: set[str] = set()
        for index, row in enumerate(raw_rows, start=2):
            try:
                trade = _MoonpayTrade(
                    trade_id=str(row.get("id") or "").strip(),
                    operation=str(row.get("operation") or "").strip().lower(),
                    status=str(row.get("status") or "").strip().lower(),
                    payment_currency=str(row.get("baseCurrency") or "").strip().lower(),
                    payment_amount=self._required_decimal(row.get("baseCurrencyAmount")),
                    paid_at=self._required_datetime(row.get("createdAt")),
                    quote_currency=str(row.get("quoteCurrency") or "").strip().lower(),
                    received_quantity=self._required_decimal(row.get("quoteCurrencyAmount")),
                    service_fee_eur=self._required_decimal(row.get("feeAmount")),
                    extra_fee_eur=self._required_decimal(row.get("extraFeeAmount")),
                    network_fee_eur=self._required_decimal(row.get("networkFeeAmount")),
                )
            except (ValueError, InvalidOperation) as exc:
                errors.append(f"trade_history_row_invalid:{index}:{exc}")
                continue
            if not trade.trade_id:
                errors.append(f"trade_history_row_invalid:{index}:missing_id")
                continue
            if trade.trade_id in seen_ids:
                errors.append(f"trade_history_duplicate_id:{trade.trade_id}")
                continue
            seen_ids.add(trade.trade_id)
            trades.append(trade)
        return trades, errors

    def _match_trades(
        self,
        candidates: list[tuple[CanonicalEvent, dict[str, object]]],
        trades: list[_MoonpayTrade],
    ) -> tuple[dict[str, _MoonpayTrade], list[str]]:
        available = {
            trade.trade_id: trade
            for trade in trades
            if self._is_supported_completed_buy(trade)
        }
        matches: dict[str, _MoonpayTrade] = {}
        errors: list[str] = []
        for event, _provenance in sorted(candidates, key=lambda item: item[0].event_time):
            ranked = sorted(
                (
                    (abs((trade.paid_at - self._as_utc(event.event_time)).total_seconds()), trade)
                    for trade in available.values()
                    if trade.asset == event.asset.upper()
                    and abs(trade.received_quantity - event.quantity) <= self.QUANTITY_TOLERANCE
                ),
                key=lambda item: (item[0], item[1].trade_id),
            )
            if not ranked or ranked[0][0] > self.MAX_TRADE_MATCH_TIME_DELTA_SECONDS:
                continue
            if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
                errors.append(f"ambiguous_trade_match:{event.tx_id}")
                continue
            trade = ranked[0][1]
            matches[event.event_id] = trade
            available.pop(trade.trade_id, None)
        return matches, errors

    def _load_sparkasse_debits(
        self,
    ) -> tuple[list[_SparkasseDebit], list[str], str | None, int]:
        if self.bank_camt_dir is None or not self.bank_camt_dir.is_dir():
            return [], [], None, 0
        files = sorted(self.bank_camt_dir.glob("*.xml"))
        if not files:
            return [], ["sparkasse_camt_xml_missing"], None, 0
        file_manifest = [
            {
                "name": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": self._file_sha256(path),
            }
            for path in files
        ]
        semantic_sha256 = hashlib.sha256(
            json.dumps(
                file_manifest,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        debits: list[_SparkasseDebit] = []
        errors: list[str] = []
        seen_references: set[str] = set()
        for path in files:
            try:
                root = ET.parse(path).getroot()
            except (ET.ParseError, OSError):
                errors.append(f"sparkasse_camt_parse_error:{path.name}")
                continue
            for entry in self._elements(root, "Ntry"):
                values = " ".join(
                    str(element.text or "") for element in entry.iter()
                )
                if "moonpay" not in values.lower():
                    continue
                debit = self._sparkasse_debit(entry, path.name)
                if debit is None:
                    errors.append(f"sparkasse_moonpay_entry_invalid:{path.name}")
                    continue
                if debit.reference in seen_references:
                    continue
                seen_references.add(debit.reference)
                debits.append(debit)
        debits.sort(
            key=lambda item: (
                item.merchant_time or datetime.combine(item.booking_date, datetime.min.time()),
                item.reference,
            )
        )
        return debits, errors, semantic_sha256, len(files)

    def _sparkasse_debit(
        self,
        entry: ET.Element,
        source_file: str,
    ) -> _SparkasseDebit | None:
        direction = self._first_text(entry, "CdtDbtInd")
        amount_element = next(self._elements(entry, "Amt"), None)
        booking_element = next(self._elements(entry, "BookgDt"), None)
        booking_text = (
            self._first_text(booking_element, "Dt")
            if booking_element is not None
            else None
        )
        reference = self._first_text(entry, "AcctSvcrRef")
        if (
            direction != "DBIT"
            or amount_element is None
            or str(amount_element.attrib.get("Ccy") or "").upper() != "EUR"
            or not booking_text
            or not reference
        ):
            return None
        try:
            amount = Decimal(str(amount_element.text or ""))
            booking_date = date.fromisoformat(booking_text)
        except (InvalidOperation, ValueError):
            return None
        merchant_time = None
        remittance = " ".join(
            value
            for element in self._elements(entry, "Ustrd")
            if (value := str(element.text or "").strip())
        )
        match = re.search(r"(20\d\d-\d\d-\d\dT\d\d:\d\d)", remittance)
        if match:
            try:
                merchant_time = datetime.fromisoformat(match.group(1))
            except ValueError:
                merchant_time = None
        return _SparkasseDebit(
            amount_eur=amount,
            booking_date=booking_date,
            merchant_time=merchant_time,
            reference=reference,
            source_file=source_file,
        )

    def _match_bank_debits(
        self,
        trades: list[_MoonpayTrade],
        debits: list[_SparkasseDebit],
    ) -> tuple[dict[str, _SparkasseDebit], list[str]]:
        available = {debit.reference: debit for debit in debits}
        matches: dict[str, _SparkasseDebit] = {}
        errors: list[str] = []
        for trade in sorted(trades, key=lambda item: item.paid_at):
            if not self._is_supported_completed_buy(trade):
                continue
            paid_at = self._as_utc(trade.paid_at).replace(tzinfo=None)
            ranked: list[tuple[float, _SparkasseDebit]] = []
            for debit in available.values():
                if abs(debit.amount_eur - trade.gross_payment_amount_eur) > Decimal("0.01"):
                    continue
                if debit.merchant_time is not None:
                    delta_seconds = abs(
                        (debit.merchant_time - paid_at).total_seconds()
                    )
                    if delta_seconds > self.MAX_BANK_MATCH_TIME_DELTA_SECONDS:
                        continue
                else:
                    day_delta = abs((debit.booking_date - paid_at.date()).days)
                    if day_delta > 7:
                        continue
                    delta_seconds = float(day_delta * 24 * 60 * 60)
                ranked.append((delta_seconds, debit))
            ranked.sort(key=lambda item: (item[0], item[1].reference))
            if not ranked:
                errors.append(f"bank_debit_match_missing:{trade.trade_id}")
                continue
            if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
                errors.append(f"bank_debit_match_ambiguous:{trade.trade_id}")
                continue
            debit = ranked[0][1]
            matches[trade.trade_id] = debit
            available.pop(debit.reference, None)
        for reference in sorted(available):
            reference_digest = hashlib.sha256(reference.encode("utf-8")).hexdigest()[:12]
            errors.append(f"bank_debit_without_trade:{reference_digest}")
        return matches, errors

    @staticmethod
    def _elements(root: ET.Element, local_name: str):
        return (
            element
            for element in root.iter()
            if element.tag.rsplit("}", 1)[-1] == local_name
        )

    @classmethod
    def _first_text(cls, root: ET.Element, local_name: str) -> str | None:
        element = next(cls._elements(root, local_name), None)
        value = str(element.text or "").strip() if element is not None else ""
        return value or None

    def _item(
        self,
        *,
        event: CanonicalEvent,
        provenance: dict[str, object],
        trade: _MoonpayTrade | None,
        bank_debit: _SparkasseDebit | None,
        bank_required: bool,
        bank_evidence_sha256: str | None,
        entry: dict[str, object] | None,
    ) -> MoonpayReceiptItem:
        provisional_value = self._market_value(event)
        base_decision = {
            "onchain_event_bound": True,
            "provenance_sender_bound": str(provenance.get("sender_owner") or "") == self.MOONPAY_SOLANA_SENDER,
            "receiver_wallet_bound": str(provenance.get("receiver_owner") or "") == str(event.account or event.wallet or ""),
            "received_quantity_bound": True,
        }
        if trade is not None:
            event_time = self._as_utc(event.event_time)
            time_delta = int((event_time - trade.paid_at).total_seconds())
            fee_valid = (
                trade.service_fee_eur >= 0
                and trade.extra_fee_eur >= 0
                and trade.network_fee_eur >= 0
                and trade.fee_components_eur <= trade.gross_payment_amount_eur
            )
            bank_reconciled = (
                bank_debit is not None
                and abs(bank_debit.amount_eur - trade.gross_payment_amount_eur)
                <= Decimal("0.01")
            )
            decisions = MoonpayReceiptDecisionLayer(
                **base_decision,
                payment_currency_eur=trade.payment_currency == "eur",
                payment_amount_valid=trade.payment_amount > 0,
                payment_fee_valid=fee_valid,
                payment_time_plausible=abs(time_delta) <= self.MAX_TRADE_MATCH_TIME_DELTA_SECONDS,
                document_integrity_valid=self._file_sha256(self.trade_history_path) is not None,
                trade_history_row_bound=True,
                completed_buy_bound=trade.operation == "buy" and trade.status == "completed",
                fee_components_within_payment_amount=fee_valid,
                bank_debit_bound=bank_reconciled if bank_required else True,
                gross_payment_reconciled=bank_reconciled if bank_required else True,
            )
            errors = self._decision_errors(decisions)
            strict_ready = not errors
            return MoonpayReceiptItem(
                tx_id=str(event.tx_id), event_id=event.event_id, event_time=event_time,
                sender_address=self.MOONPAY_SOLANA_SENDER,
                receiver_wallet=str(event.account or event.wallet or ""), asset=event.asset.upper(),
                received_quantity=event.quantity, provisional_market_value_eur=provisional_value,
                status="ready" if strict_ready else "receipt_invalid", strict_ready=strict_ready,
                cost_basis_eur=trade.gross_payment_amount_eur if strict_ready else None,
                payment_amount_eur=trade.payment_amount,
                gross_payment_amount_eur=trade.gross_payment_amount_eur,
                fee_eur=trade.fee_components_eur,
                service_fee_eur=trade.service_fee_eur, extra_fee_eur=trade.extra_fee_eur,
                network_fee_eur=trade.network_fee_eur, payment_method="MoonPay",
                paid_at=trade.paid_at, receipt_received_quantity=trade.received_quantity,
                moonpay_trade_id=trade.trade_id, moonpay_operation=trade.operation,
                moonpay_status=trade.status, moonpay_quote_currency=trade.quote_currency,
                payment_to_chain_seconds=time_delta, evidence_source="trade_history_csv",
                bank_debit_amount_eur=bank_debit.amount_eur if bank_debit else None,
                bank_booking_date=(
                    bank_debit.booking_date.isoformat() if bank_debit else None
                ),
                bank_reference=(
                    hashlib.sha256(bank_debit.reference.encode("utf-8")).hexdigest()[:16]
                    if bank_debit
                    else None
                ),
                bank_evidence_sha256=bank_evidence_sha256,
                document_filename=self.trade_history_path.name, document_media_type="text/csv",
                document_sha256=self._file_sha256(self.trade_history_path),
                document_size_bytes=self.trade_history_path.stat().st_size,
                document_download_url="/api/v1/tax/moonpay-receipts/trade-history.csv",
                decision_layer=decisions, errors=errors,
            )
        if entry is not None:
            return self._individual_receipt_item(event, provenance, entry, provisional_value)
        return MoonpayReceiptItem(
            tx_id=str(event.tx_id), event_id=event.event_id,
            event_time=self._as_utc(event.event_time), sender_address=self.MOONPAY_SOLANA_SENDER,
            receiver_wallet=str(event.account or event.wallet or ""), asset=event.asset.upper(),
            received_quantity=event.quantity, provisional_market_value_eur=provisional_value,
            decision_layer=MoonpayReceiptDecisionLayer(**base_decision),
        )

    def _individual_receipt_item(
        self,
        event: CanonicalEvent,
        provenance: dict[str, object],
        entry: dict[str, object],
        provisional_value: Decimal,
    ) -> MoonpayReceiptItem:
        payment_amount = self._optional_decimal(entry.get("payment_amount_eur"))
        fee = self._optional_decimal(entry.get("fee_eur"))
        receipt_quantity = self._optional_decimal(entry.get("received_quantity"))
        paid_at = self._optional_datetime(entry.get("paid_at"))
        event_time = self._as_utc(event.event_time)
        document_filename = str(entry.get("document_filename") or "") or None
        document_sha256 = str(entry.get("document_sha256") or "") or None
        document_size = int(entry.get("document_size_bytes") or 0)
        decisions = MoonpayReceiptDecisionLayer(
            onchain_event_bound=str(entry.get("event_id") or "") == event.event_id,
            provenance_sender_bound=(
                str(entry.get("sender_address") or "") == self.MOONPAY_SOLANA_SENDER
                and str(provenance.get("sender_owner") or "") == self.MOONPAY_SOLANA_SENDER
            ),
            receiver_wallet_bound=(
                str(entry.get("receiver_wallet") or "") == str(event.account or event.wallet or "")
                and str(provenance.get("receiver_owner") or "") == str(event.account or event.wallet or "")
            ),
            received_quantity_bound=receipt_quantity is not None and abs(receipt_quantity - event.quantity) <= self.QUANTITY_TOLERANCE,
            payment_currency_eur=str(entry.get("payment_currency") or "") == "EUR",
            payment_amount_valid=payment_amount is not None and payment_amount > 0,
            payment_fee_valid=fee is not None and fee >= 0 and payment_amount is not None and fee <= payment_amount,
            payment_time_plausible=paid_at is not None and abs((paid_at - event_time).total_seconds()) <= self.MAX_PAYMENT_TIME_DELTA_SECONDS,
            document_integrity_valid=self._document_valid(filename=document_filename, sha256=document_sha256, size_bytes=document_size),
            trade_history_row_bound=True,
            completed_buy_bound=True,
            fee_components_within_payment_amount=True,
            bank_debit_bound=True,
            gross_payment_reconciled=True,
        )
        errors = self._decision_errors(decisions)
        strict_ready = not errors
        return MoonpayReceiptItem(
            tx_id=str(event.tx_id), event_id=event.event_id, event_time=event_time,
            sender_address=self.MOONPAY_SOLANA_SENDER,
            receiver_wallet=str(event.account or event.wallet or ""), asset=event.asset.upper(),
            received_quantity=event.quantity, provisional_market_value_eur=provisional_value,
            status="ready" if strict_ready else "receipt_invalid", strict_ready=strict_ready,
            cost_basis_eur=payment_amount if strict_ready else None,
            payment_amount_eur=payment_amount,
            gross_payment_amount_eur=payment_amount,
            fee_eur=fee,
            payment_method=str(entry.get("payment_method") or "") or None,
            paid_at=paid_at, receipt_received_quantity=receipt_quantity,
            evidence_source="individual_receipt", document_filename=document_filename,
            document_media_type=str(entry.get("document_media_type") or "") or None,
            document_sha256=document_sha256, document_size_bytes=document_size,
            document_download_url=f"/api/v1/tax/moonpay-receipts/{event.tx_id}/document" if strict_ready else None,
            decision_layer=decisions, errors=errors,
        )

    @staticmethod
    def _decision_errors(decisions: MoonpayReceiptDecisionLayer) -> list[str]:
        labels = {
            "onchain_event_bound": "event_binding_invalid",
            "provenance_sender_bound": "sender_binding_invalid",
            "receiver_wallet_bound": "receiver_binding_invalid",
            "received_quantity_bound": "receipt_quantity_invalid",
            "payment_currency_eur": "payment_currency_not_eur",
            "payment_amount_valid": "payment_amount_invalid",
            "payment_fee_valid": "payment_fee_invalid",
            "payment_time_plausible": "payment_time_implausible",
            "document_integrity_valid": "document_integrity_invalid",
            "trade_history_row_bound": "trade_history_row_not_bound",
            "completed_buy_bound": "completed_buy_not_bound",
            "fee_components_within_payment_amount": "fee_components_invalid",
            "bank_debit_bound": "bank_debit_not_bound",
            "gross_payment_reconciled": "gross_payment_not_reconciled",
        }
        return [labels[key] for key, valid in decisions.model_dump().items() if not valid]

    @staticmethod
    def _is_supported_completed_buy(trade: _MoonpayTrade) -> bool:
        return (
            trade.operation == "buy"
            and trade.status == "completed"
            and trade.payment_currency == "eur"
            and trade.asset in {"SOL", "USDC"}
            and trade.payment_amount > 0
            and trade.received_quantity > 0
        )

    def _market_value(self, event: CanonicalEvent) -> Decimal:
        point = self.price_lookup.at_or_before(event.asset, event.event_time)
        return event.quantity * point.price_eur if point is not None else Decimal("0")

    def _load_manifest(self) -> tuple[dict[str, object], list[str]]:
        if not self.manifest_path.exists():
            return {"schema_version": 1, "receipts": {}}, []
        payload, errors = self._load_json(self.manifest_path, "manifest")
        if errors or not isinstance(payload, dict) or int(payload.get("schema_version") or 0) != 1:
            return {"schema_version": 1, "receipts": {}}, errors or ["manifest_schema_invalid"]
        return payload, []

    @staticmethod
    def _load_json(path: Path, label: str) -> tuple[dict[str, object], list[str]]:
        if not path.is_file():
            return {}, [f"{label}_missing"]
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {}, [f"{label}_read_failed:{exc}"]
        return payload if isinstance(payload, dict) else {}, ([] if isinstance(payload, dict) else [f"{label}_invalid"])

    def _document_valid(self, *, filename: str | None, sha256: str | None, size_bytes: int) -> bool:
        if not filename or not sha256 or size_bytes <= 0:
            return False
        path = (self.files_root / filename).resolve()
        if path.parent != self.files_root.resolve() or not path.is_file():
            return False
        try:
            content = path.read_bytes()
        except OSError:
            return False
        return len(content) == size_bytes and hashlib.sha256(content).hexdigest() == sha256

    def _decode_document(self, value: str) -> bytes:
        try:
            content = base64.b64decode(value, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("moonpay_receipt_base64_invalid") from exc
        if not content:
            raise ValueError("moonpay_receipt_document_empty")
        if len(content) > self.MAX_DOCUMENT_BYTES:
            raise ValueError("moonpay_receipt_document_too_large")
        return content

    def _validate_document(self, content: bytes, media_type: str, filename: str) -> None:
        if Path(filename).name != filename or filename in {".", ".."}:
            raise ValueError("moonpay_receipt_filename_invalid")
        suffix = Path(filename).suffix.lower()
        expected = self.MEDIA_EXTENSIONS[media_type]
        allowed_suffixes = {expected, ".jpeg"} if media_type == "image/jpeg" else {expected}
        if suffix not in allowed_suffixes:
            raise ValueError("moonpay_receipt_filename_media_type_mismatch")
        valid_signature = (
            media_type == "application/pdf" and content.startswith(b"%PDF-")
            or media_type == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n")
            or media_type == "image/jpeg" and content.startswith(b"\xff\xd8\xff")
        )
        if media_type in {"text/csv", "text/plain"}:
            try:
                content.decode("utf-8")
                valid_signature = b"\x00" not in content
            except UnicodeDecodeError:
                valid_signature = False
        if not valid_signature:
            raise ValueError("moonpay_receipt_document_signature_invalid")

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)

    def _display_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.PROJECT_ROOT.resolve()))
        except ValueError:
            return str(path.resolve())

    @staticmethod
    def _file_sha256(path: Path) -> str | None:
        if not path.is_file():
            return None
        hasher = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    hasher.update(chunk)
        except OSError:
            return None
        return hasher.hexdigest()

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @classmethod
    def _required_datetime(cls, value: object) -> datetime:
        if not value:
            raise ValueError("missing_datetime")
        try:
            return cls._as_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
        except ValueError as exc:
            raise ValueError("invalid_datetime") from exc

    @classmethod
    def _optional_datetime(cls, value: object) -> datetime | None:
        try:
            return cls._required_datetime(value)
        except ValueError:
            return None

    @staticmethod
    def _required_decimal(value: object) -> Decimal:
        if value is None or str(value).strip() == "":
            raise ValueError("missing_decimal")
        result = Decimal(str(value))
        if not result.is_finite():
            raise ValueError("non_finite_decimal")
        return result

    @staticmethod
    def _optional_decimal(value: object) -> Decimal | None:
        try:
            return MoonpayReceiptService._required_decimal(value)
        except (ValueError, InvalidOperation):
            return None
