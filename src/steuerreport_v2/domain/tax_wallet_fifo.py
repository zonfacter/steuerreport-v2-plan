from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from dataclasses import dataclass
import ast
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

import httpx

from steuerreport_v2.contracts.events import CanonicalEvent
from steuerreport_v2.contracts.tax import TaxLine, TaxLot
from steuerreport_v2.contracts.tax_wallet_fifo import (
    LegacyHeliumOverviewReport,
    LegacyHeliumTransferEvidence,
    LegacyHeliumWalletSummary,
    WalletFifoGapCandidateEvent,
    WalletFifoCexDepositTransferEvidence,
    WalletFifoCexDepositTransferEvidenceReport,
    WalletFifoCexExchangeOutflowAnchorFeasibilityItem,
    WalletFifoCexExchangeOutflowAnchorFeasibilityReport,
    WalletFifoCexExchangeOutflowCandidate,
    WalletFifoCexExchangeOutflowEvidenceReport,
    WalletFifoCexExchangeOutflowEvidenceRow,
    WalletFifoCexSenderOwnershipDecision,
    WalletFifoCexSenderOwnershipSummaryReport,
    WalletFifoGapDiagnosis,
    WalletFifoGapDiagnosisReport,
    WalletFifoExchangeEvidenceGap,
    WalletFifoExchangeEvidenceGapReport,
    WalletFifoOriginRawEvidence,
    WalletFifoOriginTrace,
    WalletFifoOriginTraceReport,
    WalletFifoOpeningBalanceEvidence,
    WalletFifoOpeningBalanceEvidenceReport,
    WalletFifoProvenanceOutflowSummary,
    WalletFifoProvenanceEvent,
    WalletFifoProvenanceEventReport,
    WalletFifoProvenancePriorityGroup,
    WalletFifoProvenancePriorityReport,
    WalletFifoProvenancePrioritySample,
    WalletFifoYearProvenanceClosureItem,
    WalletFifoYearProvenanceClosureReport,
    WalletFifoRawProvenanceBreakdownGroup,
    WalletFifoRawProvenanceBreakdownReport,
    WalletFifoProvenanceStatusBreakdown,
    WalletFifoSolanaProvenanceBatchLatest,
    WalletFifoSolanaProvenanceClassification,
    WalletFifoSolanaProvenanceClassificationReport,
    WalletFifoSolanaRawBmfEvidenceDrilldownEvent,
    WalletFifoSolanaRawBmfEvidenceDrilldownReport,
    WalletFifoSolanaRawBmfEvidenceSignerGroup,
    WalletFifoSolanaRawBmfEvidenceGroup,
    WalletFifoSolanaRawBmfEvidenceSummaryReport,
    WalletFifoSolanaRawProvenancePriority,
    WalletFifoSolanaRawProvenancePriorityReport,
    WalletFifoSolanaRawProvenanceSenderSummary,
    WalletFifoSolanaRawProvenanceSenderSummaryReport,
    WalletFifoSolanaSenderCluster,
    WalletFifoSolanaSenderClusterOutflowReport,
    WalletFifoSolanaSenderClusterOutflowSample,
    WalletFifoSolanaSenderClusterReport,
    WalletFifoSolanaSenderClusterSample,
    WalletFifoSolanaNearbyOutflowCandidate,
    WalletFifoSolanaOriginTrace,
    WalletFifoSolanaOriginTraceReport,
    WalletFifoSolanaTokenDelta,
    WalletFifoWithdrawalCandidate,
    WalletFifoWithdrawalGapReport,
    WalletFifoWithdrawalGapTrace,
    WalletFifoPreviewLine,
    WalletFifoPreviewLot,
    WalletFifoPreviewReport,
    WalletFifoPreviewUnmatched,
    WalletFifoTransferTrace,
    WalletFifoYearDelta,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax import FIAT_TAX_EXCLUDED_ASSETS, LOT_ACQUISITION_EVENT_TYPES, TaxService


@dataclass(frozen=True)
class _ExternalTransferAnchor:
    deposit_event_id: str
    target_event_id: str
    target_event_time: datetime
    source_pool_id: str
    target_pool_id: str
    asset: str
    quantity: Decimal
    tx_id: str
    source_account: str
    target_account: str
    fee_quantity: Decimal = Decimal("0")


@dataclass(frozen=True)
class _SolanaRawRouteDetails:
    wallet_is_signer: bool = False
    signers: tuple[str, ...] = ()
    program_ids: tuple[str, ...] = ()
    primary_program: str | None = None


class WalletFifoPreviewService:
    METHOD_VERSION = "wallet_asset_preview_v17"
    DEFAULT_SOLANA_RPC_URL = "https://api.mainnet-beta.solana.com"
    DEFAULT_SOLANA_PROVENANCE_BATCH_DIR = Path("/workspace/steuerreport-v2-plan/var/solana_provenance_batches")
    MAIN_HELIUM_LEGACY_WALLET = "1362Z4gXFbBuUp22PtwNhdNc3iR6Tjc7ty5S8CPjSwVH6F7BsHV"
    FAIRSPOT_STAKING_WALLET = "13xfSeV2UcVgUiTKmd9V1Htunc6N7wsAgkGRHtquN9hpCbA78Yp"
    PRIMARY_SOLANA_WALLET = "G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY"
    MOONPAY_APPLE_PAY_SOLANA_SENDER = "Dw8phQHJuLhCMzUUNWTNkHcui847dMdoADdg8XDxsVtE"
    FAIRSPOT_EVIDENCE_URL = (
        "https://www.fairspot.host/hnt-export-mining-tax"
        "?account=13xfSeV2UcVgUiTKmd9V1Htunc6N7wsAgkGRHtquN9hpCbA78Yp"
    )
    _SOLANA_ORIGIN_TRACE_CACHE: dict[tuple[str, str, str, str, str], WalletFifoSolanaOriginTrace] = {}
    _PREVIEW_CACHE_TTL_SECONDS = 300
    _PREVIEW_CACHE: dict[tuple[str, str, tuple[object, ...]], tuple[float, WalletFifoPreviewReport]] = {}
    _PROVENANCE_CLOSURE_CACHE: dict[tuple[str, int, int], tuple[float, WalletFifoYearProvenanceClosureReport]] = {}
    _PREVIEW_DISK_CACHE_DIRNAME = ".steuerreport_v2_cache/wallet_fifo_preview"
    DEFAULT_CEX_SENDER_OWNERSHIP_DIR = Path("/workspace/steuerreport-v2-plan/var/cex_deposit_sender_ownership")
    KNOWN_OWN_SOLANA_WALLETS = {
        "4dCdKKXm1aHzMLFHFz7Cyn6CA14RK7WdYKeAGrHx4fod",
        "G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY",
    }
    KNOWN_SOLANA_EXCHANGE_INFRASTRUCTURE = {
        "3wUnjrkdLcXARm51UmsPNAn43bh5zAB7MDv28C2MHNfr": "Bitget Exchange",
    }
    SOLANA_MINT_SYMBOLS = {
        "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN".upper(): "JUP",
        "SO11111111111111111111111111111111111111112": "SOL",
        "EPJFWDD5AUFQSSQE2QEZXABK12CGMXBTSBS8G4WYGKZ".upper(): "USDC",
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB".upper(): "USDT",
    }

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store
        self.tax_service = TaxService(store)

    def preview(self, year: int | None = None) -> WalletFifoPreviewReport:
        cache_key = self._preview_cache_key(year)
        cached = self._PREVIEW_CACHE.get(cache_key)
        now = time.monotonic()
        if cached is not None and now - cached[0] <= self._PREVIEW_CACHE_TTL_SECONDS:
            return cached[1].model_copy(deep=True)
        disk_cached = self._read_preview_disk_cache(cache_key)
        if disk_cached is not None:
            self._PREVIEW_CACHE[cache_key] = (now, disk_cached.model_copy(deep=True))
            return disk_cached.model_copy(deep=True)
        report = self._build_preview(year)
        self._PREVIEW_CACHE[cache_key] = (now, report.model_copy(deep=True))
        self._write_preview_disk_cache(cache_key, report)
        return report

    def legacy_helium_overview(self, *, limit: int = 200) -> LegacyHeliumOverviewReport:
        wallets = [
            self._legacy_wallet_summary(
                address=self.MAIN_HELIUM_LEGACY_WALLET,
                label="Helium Main Legacy Wallet",
                role="main_legacy_wallet",
                note=(
                    "Historische HNT-Main-Wallet fuer Mining/Rewards und Transfers. "
                    "Sie wird nicht als aktuelle Portfolio-Wallet bewertet; ihre "
                    "Events bleiben als FIFO- und Steuerhistorie erhalten."
                ),
            ),
            self._legacy_wallet_summary(
                address=self.FAIRSPOT_STAKING_WALLET,
                label="Fairspot/Staking Gegenpartei",
                role="staking_counterparty",
                note=(
                    "Bekannte Staking-/Service-Gegenpartei. Transfers zu/von dieser "
                    "Adresse werden als Transfer-Provenance fuer FIFO gefuehrt, aber "
                    "nicht als eigene aktuelle Portfolio-Wallet."
                ),
                evidence_url=self.FAIRSPOT_EVIDENCE_URL,
            ),
            LegacyHeliumWalletSummary(
                address=self.PRIMARY_SOLANA_WALLET,
                label="Solana Main Wallet 6K9n7y...qEwP",
                role="migration_target",
                included_in_portfolio=False,
                note=(
                    "Migrationsziel fuer die Helium->Solana-Historie. Aktuelle "
                    "Portfolio-Bewertung erfolgt ueber die Solana-/Live-Pfade; diese "
                    "Legacy-Uebersicht schreibt keine Portfolio-Werte."
                ),
            ),
        ]
        fairspot_transfers = self._fairspot_transfer_evidence(limit=limit)
        return LegacyHeliumOverviewReport(
            generated_at=datetime.now(timezone.utc),
            main_legacy_wallet=self.MAIN_HELIUM_LEGACY_WALLET,
            fairspot_staking_wallet=self.FAIRSPOT_STAKING_WALLET,
            solana_migration_wallet=self.PRIMARY_SOLANA_WALLET,
            wallets=wallets,
            fairspot_transfers=fairspot_transfers,
            fairspot_transfers_count=len(fairspot_transfers),
            included_in_portfolio_count=sum(1 for wallet in wallets if wallet.included_in_portfolio),
            total_canonical_events_count=sum(wallet.canonical_events_count for wallet in wallets),
            total_net_hnt_quantity=sum((wallet.net_hnt_quantity for wallet in wallets), Decimal("0")),
            methodology=(
                "Read-only Legacy-HNT/Fairspot-Provenance. Die Main-Legacy-Wallet "
                "wird aus Canonical Events zusammengefasst; Fairspot wird aus "
                "Raw-Evidence als Transfer-Gegenpartei sichtbar gemacht. Keine "
                "dieser Legacy-/Gegenpartei-Zeilen erzeugt einen aktuellen "
                "Portfolio-Wert. Fuer FIFO bleibt die Historie ueber Canonical "
                "Events, Raw-Object-Belege und Wallet-FIFO-Drilldowns pruefbar."
            ),
        )

    def _preview_cache_key(self, year: int | None) -> tuple[str, str, tuple[object, ...]]:
        with self.store.connect() as con:
            canonical = con.execute(
                """
                select
                    count(*)::integer,
                    coalesce(max(event_time), timestamp '1970-01-01'),
                    coalesce(max(event_id), '')
                from canonical_events
                """
            ).fetchone()
            tax_lines = con.execute(
                """
                select
                    count(*)::integer,
                    coalesce(max(disposed_at), timestamp '1970-01-01'),
                    coalesce(max(tax_line_id), '')
                from tax_lines
                """
            ).fetchone()
            cex_exchange_outflow_decisions = con.execute(
                """
                select
                    count(*)::integer,
                    coalesce(max(created_at), timestamp '1970-01-01'),
                    coalesce(max(id), '')
                from review_decisions
                where payload_json like '%"decision_type":"cex_exchange_outflow"%'
                """
            ).fetchone()
            raw_objects = con.execute(
                """
                select
                    count(*)::integer,
                    coalesce(max(row_number), 0),
                    coalesce(max(raw_object_id), '')
                from raw_objects
                """
            ).fetchone()
        return (
            str(self.store.path.resolve()),
            str(year) if year is not None else "all",
            (self.METHOD_VERSION,)
            + tuple(canonical or ())
            + tuple(tax_lines or ())
            + tuple(cex_exchange_outflow_decisions or ())
            + tuple(raw_objects or ()),
        )

    def _preview_disk_cache_path(self, cache_key: tuple[str, str, tuple[object, ...]]) -> Path:
        digest = hashlib.sha256(repr(cache_key).encode("utf-8")).hexdigest()
        return self.store.path.parent / self._PREVIEW_DISK_CACHE_DIRNAME / f"{digest}.json"

    def _legacy_wallet_summary(
        self,
        *,
        address: str,
        label: str,
        role: str,
        note: str,
        evidence_url: str | None = None,
    ) -> LegacyHeliumWalletSummary:
        with self.store.connect() as con:
            row = con.execute(
                """
                select
                    count(*)::integer as events_count,
                    sum(case when event_type = 'mining' then 1 else 0 end)::integer as mining_count,
                    sum(case when event_type = 'transfer' then 1 else 0 end)::integer as transfer_count,
                    sum(case when event_type = 'fee' then 1 else 0 end)::integer as fee_count,
                    coalesce(sum(case when upper(asset) = 'HNT' then quantity else 0 end), 0) as net_hnt,
                    min(event_time) as first_event_at,
                    max(event_time) as last_event_at
                from canonical_events
                where (account = ? or wallet = ?)
                  and upper(asset) = 'HNT'
                """,
                [address, address],
            ).fetchone()
        return LegacyHeliumWalletSummary(
            address=address,
            label=label,
            role=role,  # type: ignore[arg-type]
            included_in_portfolio=False,
            current_portfolio_value_eur=Decimal("0"),
            canonical_events_count=int(row[0] or 0),
            mining_events_count=int(row[1] or 0),
            transfer_events_count=int(row[2] or 0),
            fee_events_count=int(row[3] or 0),
            net_hnt_quantity=row[4] or Decimal("0"),
            first_event_at=row[5],
            last_event_at=row[6],
            note=note,
            evidence_url=evidence_url,
        )

    def _fairspot_transfer_evidence(self, *, limit: int) -> list[LegacyHeliumTransferEvidence]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    r.raw_object_id,
                    b.source,
                    b.filename,
                    r.row_number,
                    r.payload_json
                from raw_objects r
                join raw_import_batches b on b.batch_id = r.batch_id
                where r.payload_json like ?
                  and r.payload_json like ?
                order by b.created_at, r.row_number
                limit ?
                """,
                [
                    f"%{self.FAIRSPOT_STAKING_WALLET}%",
                    f"%{self.MAIN_HELIUM_LEGACY_WALLET}%",
                    max(1, min(limit, 1000)),
                ],
            ).fetchall()
        transfers: list[LegacyHeliumTransferEvidence] = []
        for raw_object_id, source, filename, row_number, payload_json in rows:
            payload = self._parse_payload(payload_json)
            payer = self._payload_str(payload, "payer")
            payee = self._payload_str(payload, "payee")
            direction = "other_legacy_transfer"
            if payer == self.MAIN_HELIUM_LEGACY_WALLET and payee == self.FAIRSPOT_STAKING_WALLET:
                direction = "main_to_fairspot"
            elif payer == self.FAIRSPOT_STAKING_WALLET and payee == self.MAIN_HELIUM_LEGACY_WALLET:
                direction = "fairspot_to_main"
            quantity = self._payload_decimal_any_locale(
                payload,
                ("hnt_amount", "amount", "Mining Rewards HNT", "mining rewards hnt"),
            )
            transfers.append(
                LegacyHeliumTransferEvidence(
                    raw_object_id=str(raw_object_id),
                    source=str(source),
                    filename=str(filename) if filename is not None else None,
                    row_number=int(row_number) if row_number is not None else None,
                    event_time=self._payload_str(payload, "date") or self._payload_str(payload, "time"),
                    tx_id=(
                        self._payload_str(payload, "transaction_hash")
                        or self._payload_str(payload, "txid")
                        or self._payload_str(payload, "hash")
                    ),
                    quantity=quantity or Decimal("0"),
                    payer=payer,
                    payee=payee,
                    direction=direction,  # type: ignore[arg-type]
                    evidence_ref=(
                        f"raw_object:{raw_object_id}"
                        if row_number is None
                        else f"raw_object:{raw_object_id}:row:{row_number}"
                    ),
                )
            )
        return transfers

    @classmethod
    def _payload_decimal_any_locale(
        cls,
        payload: dict[str, object],
        keys: tuple[str, ...],
    ) -> Decimal | None:
        for key in keys:
            value = payload.get(key)
            if value is None:
                continue
            text = str(value).strip().replace(".", "").replace(",", ".") if "," in str(value) else str(value).strip()
            try:
                return Decimal(text)
            except Exception:
                continue
        return None

    def _read_preview_disk_cache(
        self,
        cache_key: tuple[str, str, tuple[object, ...]],
    ) -> WalletFifoPreviewReport | None:
        path = self._preview_disk_cache_path(cache_key)
        try:
            if not path.exists():
                return None
            report = WalletFifoPreviewReport.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        if report.method_version != self.METHOD_VERSION:
            return None
        return report

    def _write_preview_disk_cache(
        self,
        cache_key: tuple[str, str, tuple[object, ...]],
        report: WalletFifoPreviewReport,
    ) -> None:
        path = self._preview_disk_cache_path(cache_key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = path.with_suffix(f".{uuid4().hex}.tmp")
            tmp_path.write_text(report.model_dump_json(), encoding="utf-8")
            tmp_path.replace(path)
        except Exception:
            return

    def _build_preview(self, year: int | None = None) -> WalletFifoPreviewReport:
        events = self.store.list_canonical_events()
        grouped_transfer_ids = self._grouped_transfer_ids(events)
        external_transfer_anchors = self._external_transfer_anchors(events)
        external_transfer_anchors_by_target_event = {
            anchor.target_event_id: anchor
            for anchor in external_transfer_anchors.values()
            if not anchor.target_event_id.startswith("external:")
        }
        lots_by_pool_asset: defaultdict[tuple[str, str], deque[WalletFifoPreviewLot]] = defaultdict(deque)
        all_lots: list[WalletFifoPreviewLot] = []
        tax_lines: list[WalletFifoPreviewLine] = []
        unmatched: list[WalletFifoPreviewUnmatched] = []
        transfers: list[WalletFifoTransferTrace] = []

        processed_transfer_event_ids: set[str] = set()
        events_by_tx = self._events_by_tx(events)
        positive_events_by_asset: defaultdict[str, list[CanonicalEvent]] = defaultdict(list)
        for candidate in events:
            if candidate.quantity > 0 and candidate.asset.upper() not in FIAT_TAX_EXCLUDED_ASSETS:
                positive_events_by_asset[candidate.asset.upper()].append(candidate)
        for event in events:
            if event.asset.upper() in FIAT_TAX_EXCLUDED_ASSETS:
                continue
            if event.event_id in processed_transfer_event_ids:
                continue
            target_anchor = external_transfer_anchors_by_target_event.get(event.event_id)
            if target_anchor is not None:
                moved, fee_lines, missing = self._process_external_transfer_anchor(
                    anchor=target_anchor,
                    anchor_event=event,
                    lots_by_pool_asset=lots_by_pool_asset,
                )
                transfers.extend(moved)
                tax_lines.extend(fee_lines)
                unmatched.extend(missing)
                processed_transfer_event_ids.add(event.event_id)
                processed_transfer_event_ids.add(target_anchor.deposit_event_id)
                processed_transfer_event_ids.add(target_anchor.target_event_id)
                continue
            external_anchor = external_transfer_anchors.get(event.event_id)
            if external_anchor is not None:
                moved, fee_lines, missing = self._process_external_transfer_anchor(
                    anchor=external_anchor,
                    anchor_event=event,
                    lots_by_pool_asset=lots_by_pool_asset,
                )
                transfers.extend(moved)
                tax_lines.extend(fee_lines)
                unmatched.extend(missing)
                processed_transfer_event_ids.add(event.event_id)
                processed_transfer_event_ids.add(external_anchor.target_event_id)
                continue
            if event.event_type == "transfer" and event.tx_id in grouped_transfer_ids:
                tx_events = events_by_tx.get(str(event.tx_id), [])
                moved, missing = self._process_transfer_group(tx_events, lots_by_pool_asset)
                transfers.extend(moved)
                unmatched.extend(missing)
                processed_transfer_event_ids.update(item.event_id for item in tx_events if item.event_type == "transfer")
                all_lots.extend(lot for trace in moved for lot in self._new_lots_for_trace(trace, lots_by_pool_asset))
                continue
            if event.event_type == "transfer" and event.quantity > 0:
                moved, missing = self._process_inferred_cross_pool_transfer_target(
                    target_event=event,
                    candidate_events=positive_events_by_asset[event.asset.upper()],
                    lots_by_pool_asset=lots_by_pool_asset,
                )
                if moved or missing:
                    transfers.extend(moved)
                    unmatched.extend(missing)
                    processed_transfer_event_ids.add(event.event_id)
                    continue
                lot, trace = self._process_unresolved_inbound_transfer(
                    event=event,
                    lots_by_pool_asset=lots_by_pool_asset,
                )
                all_lots.append(lot)
                transfers.append(trace)
                processed_transfer_event_ids.add(event.event_id)
                continue
            created_lots, created_lines, missing = self._process_non_transfer_event(event, lots_by_pool_asset)
            all_lots.extend(created_lots)
            tax_lines.extend(created_lines)
            unmatched.extend(missing)

        global_lines = self.tax_service.list_tax_lines()
        report_lines = tax_lines if year is None else [line for line in tax_lines if line.disposed_at.year == year]
        global_report_lines = global_lines if year is None else [line for line in global_lines if line.disposed_at.year == year]
        year_deltas = self._year_deltas(global_lines, tax_lines)
        if year is not None:
            year_deltas = [delta for delta in year_deltas if delta.year == year]
        global_gain = sum((line.gain_loss_eur for line in global_report_lines), Decimal("0"))
        wallet_gain = sum((line.gain_loss_eur for line in report_lines), Decimal("0"))
        filtered_unmatched = unmatched if year is None else [item for item in unmatched if item.event_time.year == year]
        filtered_transfers = transfers if year is None else [item for item in transfers if item.event_time.year == year]
        filtered_transfers = self._mark_cex_exchange_outflow_resolved_traces(
            filtered_transfers,
            year=year,
        )
        filtered_transfers = self._mark_exchange_internal_context_resolved_traces(
            filtered_transfers,
            events=events,
        )
        return WalletFifoPreviewReport(
            generated_at=datetime.now(timezone.utc),
            method_version=self.METHOD_VERSION,
            status="blocked" if filtered_unmatched else "preview",
            pools_count=len({pool for pool, _asset in lots_by_pool_asset.keys()}),
            lots_count=sum(len(lots) for lots in lots_by_pool_asset.values()),
            tax_lines_count=len(report_lines),
            unmatched_count=len(filtered_unmatched),
            transfer_traces_count=len(filtered_transfers),
            unresolved_inbound_provenance_count=sum(
                1 for trace in filtered_transfers if trace.status == "unresolved_inbound_provenance"
            ),
            global_gain_loss_eur=global_gain,
            wallet_gain_loss_eur=wallet_gain,
            delta_gain_loss_eur=wallet_gain - global_gain,
            year_deltas=year_deltas,
            unmatched=filtered_unmatched[:200],
            transfer_traces=filtered_transfers[:1000],
            sample_lines=report_lines[:200],
            methodology=(
                "Read-only Preview einer wallet-/depotbezogenen FIFO-Logik. "
                "Pools werden aus account, wallet oder source gebildet. Transfers "
                "mit gleicher tx_id, gleichem Asset und Gegenbuchung fuehren Lots "
                "mit Anschaffungsdatum und Cost Basis in den Ziel-Pool fort. "
                "Die bestehenden tax_lots/tax_lines werden nicht veraendert."
            ),
        )

    def _mark_cex_exchange_outflow_resolved_traces(
        self,
        traces: list[WalletFifoTransferTrace],
        *,
        year: int | None,
    ) -> list[WalletFifoTransferTrace]:
        exchange_outflow_txids = self._reviewed_cex_exchange_outflow_deposit_txids(year=year)
        sender_ownership_txids = self._reviewed_cex_sender_ownership_deposit_txids(year=year)
        if not exchange_outflow_txids and not sender_ownership_txids:
            return traces
        resolved: list[WalletFifoTransferTrace] = []
        for trace in traces:
            if (
                trace.status == "unresolved_inbound_provenance"
                and trace.tx_id
                and trace.tx_id in exchange_outflow_txids
            ):
                resolved.append(
                    trace.model_copy(
                        update={
                            "status": "resolved_by_cex_exchange_outflow_anchor",
                            "source_pool_id": "cex_exchange_outflow_anchor",
                        }
                    )
                )
            elif (
                trace.status == "unresolved_inbound_provenance"
                and trace.tx_id
                and trace.tx_id in sender_ownership_txids
            ):
                resolved.append(
                    trace.model_copy(
                        update={
                            "status": "resolved_by_cex_sender_ownership_anchor",
                            "source_pool_id": "cex_sender_ownership_anchor",
                        }
                    )
                )
            else:
                resolved.append(trace)
        return resolved

    def _mark_exchange_internal_context_resolved_traces(
        self,
        traces: list[WalletFifoTransferTrace],
        *,
        events: list[CanonicalEvent],
    ) -> list[WalletFifoTransferTrace]:
        unresolved = [trace for trace in traces if trace.status == "unresolved_inbound_provenance"]
        if not unresolved:
            return traces
        events_by_id = {event.event_id: event for event in events}
        outflow_rows_by_asset = self._negative_outflow_rows_by_asset()
        withdrawal_evidence_by_asset_event_id: dict[str, dict[str, WalletFifoOriginRawEvidence | None]] = {}
        raw_evidence_by_id: dict[str, WalletFifoOriginRawEvidence | None] = {}
        resolved: list[WalletFifoTransferTrace] = []
        for trace in traces:
            if trace.status != "unresolved_inbound_provenance":
                resolved.append(trace)
                continue
            event = events_by_id.get(trace.target_event_id)
            if event is None:
                resolved.append(trace)
                continue
            raw_evidence = None
            if event.raw_object_id:
                if event.raw_object_id not in raw_evidence_by_id:
                    raw_evidence_by_id[event.raw_object_id] = self._raw_evidence(event.raw_object_id)
                raw_evidence = raw_evidence_by_id.get(event.raw_object_id)
            if self._is_exchange_internal_inbound_context(event=event, raw_evidence=raw_evidence):
                resolved.append(
                    trace.model_copy(
                        update={
                            "status": "resolved_by_exchange_internal_context",
                            "source_pool_id": "exchange_internal_context",
                        }
                    )
                )
                continue
            if self._is_solana_tiny_raw_credit(event=event, raw_evidence=raw_evidence):
                resolved.append(
                    trace.model_copy(
                        update={
                            "status": "resolved_by_solana_tiny_raw_credit",
                            "source_pool_id": "solana_tiny_raw_credit",
                        }
                    )
                )
                continue
            if self._is_solana_helium_reward_claim_context(event=event, raw_evidence=raw_evidence):
                resolved.append(
                    trace.model_copy(
                        update={
                            "status": "resolved_by_solana_helium_reward_context",
                            "source_pool_id": "helium_solana_reward_context",
                        }
                    )
                )
                continue
            asset = trace.asset.upper()
            if asset not in withdrawal_evidence_by_asset_event_id:
                withdrawal_evidence_by_asset_event_id[asset] = {}
            local_cex_deposit_candidate = self._bitget_cex_deposit_local_onchain_match_candidate(
                event=event,
                trace=trace,
                rows=outflow_rows_by_asset.get(asset, []),
                withdrawal_evidence_by_event_id=withdrawal_evidence_by_asset_event_id[asset],
            )
            if local_cex_deposit_candidate:
                resolved.append(
                    trace.model_copy(
                        update={
                            "status": "resolved_by_cex_deposit_local_onchain_match",
                            "source_pool_id": (
                                f"{local_cex_deposit_candidate.source}:"
                                f"{local_cex_deposit_candidate.account or 'unknown'}"
                            ),
                        }
                    )
                )
                continue
            internal_context_candidate = self._best_provenance_internal_context_candidate(
                event=event,
                trace=trace,
                rows=outflow_rows_by_asset.get(asset, []),
                withdrawal_evidence_by_event_id=withdrawal_evidence_by_asset_event_id[asset],
            )
            if internal_context_candidate:
                resolved.append(
                    trace.model_copy(
                        update={
                            "status": "resolved_by_exchange_internal_context",
                            "source_pool_id": "exchange_internal_context",
                        }
                    )
                )
            else:
                resolved.append(trace)
        return resolved

    def _reviewed_cex_exchange_outflow_deposit_txids(self, *, year: int | None) -> set[str]:
        txids: set[str] = set()
        for decision in self.store.list_review_decisions():
            if decision.decision_type != "cex_exchange_outflow":
                continue
            payload = decision.payload
            if payload.get("decision_status") != "transfer_neutral_fifo_carry_forward_reviewed":
                continue
            if year is not None and str(payload.get("year") or "") != str(year):
                continue
            deposit_txid = str(payload.get("deposit_txid") or "")
            if deposit_txid:
                txids.add(deposit_txid)
        return txids

    def _reviewed_cex_sender_ownership_deposit_txids(self, *, year: int | None) -> set[str]:
        txids: set[str] = set()
        for decision in self.store.list_review_decisions():
            if decision.decision_type != "cex_sender_ownership":
                continue
            payload = decision.payload
            if payload.get("decision_status") != "tax_neutral_transfer_reviewed":
                continue
            if year is not None and str(payload.get("year") or "") != str(year):
                continue
            txid = str(payload.get("txid") or "")
            if txid:
                txids.add(txid)
        return txids

    def _external_transfer_anchors(self, events: list[CanonicalEvent]) -> dict[str, _ExternalTransferAnchor]:
        anchors: dict[str, _ExternalTransferAnchor] = {}
        live_rpc_enabled = os.getenv("STEUERREPORT_WALLET_FIFO_ENABLE_LIVE_RPC", "").lower() in {"1", "true", "yes"}
        deposit_events = [
            event
            for event in events
            if event.source == "binance"
            and event.event_type == "transfer"
            and event.quantity > 0
            and event.tx_id
            and event.asset.upper() in {"JUP"}
        ]
        withdrawal_events = [
            event
            for event in events
            if event.source == "binance"
            and event.event_type == "transfer"
            and event.quantity < 0
            and event.asset.upper() in {"JUP", "SOL"}
        ]
        if not deposit_events and not withdrawal_events:
            return anchors
        if live_rpc_enabled:
            with httpx.Client(timeout=20) as client:
                for event in deposit_events:
                    deposit_address = self._deposit_address_for_tx(str(event.tx_id))
                    if not deposit_address:
                        continue
                    try:
                        trace = self._cached_solana_origin_trace(
                            client=client,
                            rpc_url=self.DEFAULT_SOLANA_RPC_URL,
                            signature=str(event.tx_id),
                            asset=event.asset,
                            expected_amount=event.quantity,
                            deposit_address=deposit_address,
                        )
                    except Exception:
                        continue
                    if trace.status != "own_wallet_transfer_candidate" or not trace.sender_owner:
                        continue
                    source_pool = f"solana_rpc:{trace.sender_owner}"
                    target_event = self._external_anchor_target_event(event, events)
                    anchors[event.event_id] = _ExternalTransferAnchor(
                        deposit_event_id=event.event_id,
                        target_event_id=target_event.event_id,
                        target_event_time=target_event.event_time,
                        source_pool_id=source_pool,
                        target_pool_id=self._pool_id(target_event),
                        asset=event.asset.upper(),
                        quantity=event.quantity,
                        tx_id=str(event.tx_id),
                        source_account=trace.sender_owner,
                        target_account=target_event.account or target_event.wallet or target_event.source,
                    )
        for event in withdrawal_events:
            evidence = self._matching_withdrawal_history(event)
            if evidence is None:
                continue
            payload = evidence.payload
            target_address = (
                self._payload_str(payload, "address")
                or self._payload_str(payload, "Address")
                or self._payload_str(payload, "To Address")
            )
            if target_address not in self.KNOWN_OWN_SOLANA_WALLETS:
                continue
            tx_id = (
                self._payload_str(payload, "tx_id")
                or self._payload_str(payload, "txId")
                or self._payload_str(payload, "TXID")
                or str(event.tx_id or "")
            )
            amount = self._payload_decimal_any(payload, ("amount", "Amount"))
            fee = self._payload_decimal_any(payload, ("transaction_fee", "transactionFee", "Transaction Fee"))
            gross = self._payload_decimal_any(payload, ("gross_amount", "Gross Amount"))
            fee_quantity = fee or Decimal("0")
            transfer_quantity = amount or ((gross or abs(event.quantity)) - fee_quantity)
            if transfer_quantity <= 0 or not tx_id:
                continue
            target_time = self._parse_binance_time(
                self._payload_str(payload, "complete_time")
                or self._payload_str(payload, "Complete Time")
                or self._payload_str(payload, "apply_time")
                or self._payload_str(payload, "Apply Time")
            ) or event.event_time
            target_event = self._external_withdrawal_anchor_target_event(
                events=events,
                asset=event.asset.upper(),
                tx_id=tx_id,
                target_address=target_address,
                quantity=transfer_quantity,
            )
            anchors[event.event_id] = _ExternalTransferAnchor(
                deposit_event_id=event.event_id,
                target_event_id=target_event.event_id if target_event else f"external:{tx_id}:target",
                target_event_time=target_event.event_time if target_event else target_time,
                source_pool_id=self._pool_id(event),
                target_pool_id=self._pool_id(target_event) if target_event else f"solana_rpc:{target_address}",
                asset=event.asset.upper(),
                quantity=transfer_quantity,
                fee_quantity=fee_quantity,
                tx_id=tx_id,
                source_account=event.account or event.wallet or event.source,
                target_account=target_address,
            )
        return anchors

    def _cached_solana_origin_trace(
        self,
        *,
        client: httpx.Client,
        rpc_url: str,
        signature: str,
        asset: str,
        expected_amount: Decimal | None,
        deposit_address: str | None,
    ) -> WalletFifoSolanaOriginTrace:
        cache_key = (
            rpc_url,
            signature,
            asset.upper(),
            str(expected_amount or ""),
            deposit_address or "",
        )
        cached = self._SOLANA_ORIGIN_TRACE_CACHE.get(cache_key)
        if cached is not None:
            return cached
        trace = self._fetch_solana_origin_trace(
            client=client,
            rpc_url=rpc_url,
            signature=signature,
            asset=asset,
            expected_amount=expected_amount,
            deposit_address=deposit_address,
        )
        if trace.status in {"own_wallet_transfer_candidate", "external_or_unknown_origin", "not_found"}:
            self._SOLANA_ORIGIN_TRACE_CACHE[cache_key] = trace
        return trace

    def _external_anchor_target_event(self, deposit_event: CanonicalEvent, events: list[CanonicalEvent]) -> CanonicalEvent:
        window_end = deposit_event.event_time + timedelta(minutes=10)
        candidates = [
            event
            for event in events
            if event.source == deposit_event.source
            and event.event_type == "transfer"
            and event.asset.upper() == deposit_event.asset.upper()
            and event.quantity == deposit_event.quantity
            and not event.tx_id
            and deposit_event.event_time <= event.event_time <= window_end
        ]
        candidates.sort(key=lambda event: (event.account != "Spot", event.event_time, event.event_id))
        return candidates[0] if candidates else deposit_event

    def _external_withdrawal_anchor_target_event(
        self,
        *,
        events: list[CanonicalEvent],
        asset: str,
        tx_id: str,
        target_address: str,
        quantity: Decimal,
    ) -> CanonicalEvent | None:
        candidates = [
            event
            for event in events
            if event.event_type == "transfer"
            and event.quantity > 0
            and event.asset.upper() == asset.upper()
            and str(event.tx_id or "") == tx_id
            and self._pool_id(event) == f"solana_rpc:{target_address}"
            and abs(event.quantity - quantity) <= self._transfer_match_tolerance(asset)
        ]
        candidates.sort(key=lambda event: (abs(event.quantity - quantity), event.event_time, event.event_id))
        return candidates[0] if candidates else None

    def _process_external_transfer_anchor(
        self,
        *,
        anchor: _ExternalTransferAnchor,
        anchor_event: CanonicalEvent,
        lots_by_pool_asset: defaultdict[tuple[str, str], deque[WalletFifoPreviewLot]],
    ) -> tuple[list[WalletFifoTransferTrace], list[WalletFifoPreviewLine], list[WalletFifoPreviewUnmatched]]:
        source_lots = lots_by_pool_asset[(anchor.source_pool_id, anchor.asset)]
        target_lots = lots_by_pool_asset[(anchor.target_pool_id, anchor.asset)]
        source_event_time = anchor_event.event_time
        source_name = anchor.source_pool_id.split(":", 1)[0]
        target_name = anchor.target_pool_id.split(":", 1)[0]
        moved_lots, missing = self._move_lots(
            source_event=CanonicalEvent(
                event_id=f"external:{anchor.tx_id}:source",
                source=source_name,
                event_time=source_event_time,
                event_type="transfer",
                asset=anchor.asset,
                quantity=-anchor.quantity,
                tx_id=anchor.tx_id,
                account=anchor.source_account,
                confidence=Decimal("1"),
            ),
            target_event=CanonicalEvent(
                event_id=anchor.target_event_id,
                source=target_name,
                event_time=anchor.target_event_time,
                event_type="transfer",
                asset=anchor.asset,
                quantity=anchor.quantity,
                tx_id=anchor.tx_id,
                account=anchor.target_account,
                confidence=Decimal("1"),
            ),
            asset=anchor.asset,
            quantity=anchor.quantity,
            source_lots=source_lots,
            target_lots=target_lots,
        )
        fee_lines: list[WalletFifoPreviewLine] = []
        if anchor.fee_quantity > 0:
            lines, fee_missing = self._consume(
                event=CanonicalEvent(
                    event_id=f"external:{anchor.tx_id}:fee",
                    source=source_name,
                    event_time=source_event_time,
                    event_type="fee",
                    asset=anchor.asset,
                    quantity=-anchor.fee_quantity,
                    tx_id=anchor.tx_id,
                    account=anchor.source_account,
                    confidence=Decimal("1"),
                ),
                pool_id=anchor.source_pool_id,
                asset=anchor.asset,
                quantity=anchor.fee_quantity,
                proceeds_total=Decimal("0"),
                lots=source_lots,
                reason="withdrawal_fee_without_wallet_lot",
            )
            fee_lines.extend(lines)
            missing.extend(fee_missing)
        return [
            WalletFifoTransferTrace(
                tx_id=anchor.tx_id,
                asset=anchor.asset,
                event_time=anchor.target_event_time,
                source_pool_id=anchor.source_pool_id,
                target_pool_id=anchor.target_pool_id,
                quantity=anchor.quantity,
                fee_quantity=anchor.fee_quantity if anchor.fee_quantity > 0 else None,
                lots_moved=len(moved_lots),
                carried_cost_basis_eur=sum((lot.cost_basis_eur_total for lot in moved_lots), Decimal("0")),
                status="ok" if not missing else "partial",
                source_event_id=f"external:{anchor.tx_id}:source",
                target_event_id=anchor.target_event_id,
            )
        ], fee_lines, missing

    def _deposit_address_for_tx(self, tx_id: str) -> str | None:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select r.payload_json
                from raw_objects r
                left join raw_import_batches b on b.batch_id = r.batch_id
                where (lower(b.filename) like '%deposit%' or lower(b.source) like '%deposit%')
                  and r.payload_json like ?
                """,
                [f"%{tx_id}%"],
            ).fetchall()
        for (payload_json,) in rows:
            payload = self._parse_payload(payload_json)
            address = self._payload_str(payload, "Address")
            if address:
                return address
        return None

    def gap_diagnosis(self, year: int, *, limit: int = 80) -> WalletFifoGapDiagnosisReport:
        preview = self.preview(year=year)
        events = self.store.list_canonical_events()
        events_by_id = {event.event_id: event for event in events}
        diagnoses = [
            self._diagnose_gap(gap, events, events_by_id)
            for gap in preview.unmatched[:limit]
        ]
        likely_causes: dict[str, int] = {}
        for item in diagnoses:
            likely_causes[item.likely_cause] = likely_causes.get(item.likely_cause, 0) + 1
        return WalletFifoGapDiagnosisReport(
            generated_at=datetime.now(timezone.utc),
            year=year,
            gaps_count=preview.unmatched_count,
            affected_assets=sorted({item.asset for item in diagnoses}),
            affected_pools=sorted({item.pool_id for item in diagnoses}),
            likely_causes=likely_causes,
            diagnoses=diagnoses,
            methodology=(
                "Read-only Diagnose fuer Wallet-FIFO-Pool-Luecken. Je Gap "
                "werden zeitnahe positive Transfers/Trades/Rewards im gleichen "
                "Pool und moegliche Quellpool-Events gesucht. Die Diagnose "
                "schreibt keine Ersatzlots und trifft keine Review-Entscheidung."
            ),
        )

    def origin_trace(
        self,
        year: int,
        *,
        asset: str | None = None,
        pool_id: str | None = None,
        limit: int = 20,
    ) -> WalletFifoOriginTraceReport:
        diagnosis = self.gap_diagnosis(year=year, limit=limit)
        preview = self.preview(year=year)
        events = self.store.list_canonical_events()
        events_by_id = {event.event_id: event for event in events}
        traces: list[WalletFifoOriginTrace] = []
        for gap in diagnosis.diagnoses:
            if asset and gap.asset.upper() != asset.upper():
                continue
            if pool_id and gap.pool_id != pool_id:
                continue
            candidate = self._primary_origin_candidate(gap)
            tx_history = self._raw_evidence(candidate.raw_object_id) if candidate and candidate.raw_object_id else None
            deposit_history = self._matching_deposit_history(candidate) if candidate else None
            deposit_payload = deposit_history.payload if deposit_history else {}
            traces.append(
                WalletFifoOriginTrace(
                    trace_id=gap.gap_id,
                    year=year,
                    asset=gap.asset,
                    pool_id=gap.pool_id,
                    missing_quantity=gap.missing_quantity,
                    gap_event_id=gap.disposal_event_id,
                    gap_event_time=gap.event_time,
                    likely_cause=gap.likely_cause,
                    candidate_event=candidate,
                    transaction_history_evidence=tx_history,
                    deposit_history_evidence=deposit_history,
                    onchain_tx_id=self._payload_str(deposit_payload, "TXID") or (candidate.tx_id if candidate else None),
                    deposit_address=self._payload_str(deposit_payload, "Address"),
                    network=self._payload_str(deposit_payload, "Network"),
                    recommended_action=self._origin_recommended_action(gap, deposit_history),
                )
            )
        remaining = max(0, limit - len(traces))
        unresolved_traces = [
            trace
            for trace in preview.transfer_traces
            if trace.status == "unresolved_inbound_provenance"
        ][:remaining]
        for transfer in unresolved_traces:
            event = events_by_id.get(transfer.target_event_id)
            if event is None:
                continue
            if asset and transfer.asset.upper() != asset.upper():
                continue
            if pool_id and transfer.target_pool_id != pool_id:
                continue
            candidate = WalletFifoGapCandidateEvent(
                event_id=event.event_id,
                event_time=event.event_time,
                event_type=event.event_type,
                source=event.source,
                account=event.account,
                pool_id=self._pool_id(event),
                asset=event.asset.upper(),
                quantity=event.quantity,
                quote_asset=event.quote_asset,
                quote_quantity=event.quote_quantity,
                tx_id=event.tx_id,
                source_ref=event.source_ref,
                raw_object_id=event.raw_object_id,
                relation="provisional_same_pool_inbound",
                seconds_before_gap=0,
            )
            tx_history = self._raw_evidence(event.raw_object_id) if event.raw_object_id else None
            deposit_history = self._matching_deposit_history(candidate)
            deposit_payload = deposit_history.payload if deposit_history else {}
            traces.append(
                WalletFifoOriginTrace(
                    trace_id=f"unresolved:{event.event_id}",
                    year=year,
                    asset=transfer.asset,
                    pool_id=transfer.target_pool_id,
                    missing_quantity=transfer.quantity,
                    gap_event_id=event.event_id,
                    gap_event_time=event.event_time,
                    likely_cause="unresolved_inbound_transfer_or_opening_balance",
                    candidate_event=candidate,
                    transaction_history_evidence=tx_history,
                    deposit_history_evidence=deposit_history,
                    onchain_tx_id=self._payload_str(deposit_payload, "TXID") or event.tx_id,
                    deposit_address=self._payload_str(deposit_payload, "Address"),
                    network=self._payload_str(deposit_payload, "Network"),
                    recommended_action=(
                        "Provisorischer Inbound-Lot: Herkunft mit Withdrawal-/Deposit-/"
                        "Onchain-Beleg verknuepfen oder als Anfangsbestand dokumentieren."
                    ),
                )
            )
        return WalletFifoOriginTraceReport(
            generated_at=datetime.now(timezone.utc),
            year=year,
            traces_count=len(traces),
            traces=traces,
            methodology=(
                "Read-only Herkunftsspur fuer Wallet-FIFO-Gaps. Verknuepft "
                "Gap-Diagnose sowie provisorische Inbound-Lots mit Binance "
                "Transaction-History-Rohzeile und, wenn vorhanden, separater "
                "Binance Deposit-History inklusive Netzwerk, Adresse und TXID. "
                "Es werden keine produktiven Lots erzeugt."
            ),
        )

    def cex_deposit_transfer_evidence(
        self,
        year: int,
        *,
        cex: str = "binance",
        network: str | None = "SOL",
        limit: int = 100,
    ) -> WalletFifoCexDepositTransferEvidenceReport:
        normalized_cex = cex.lower()
        normalized_network = network.upper() if network else None
        events = self.store.list_canonical_events()
        preview = self.preview(year=year)
        transfer_traces_by_tx = {
            trace.tx_id: trace
            for trace in preview.transfer_traces
            if trace.tx_id
        }
        reviewed_transfer_txids = (
            self._reviewed_cex_sender_ownership_deposit_txids(year=year)
            | self._reviewed_cex_exchange_outflow_deposit_txids(year=year)
        )
        cex_events = [
            event
            for event in events
            if event.source.lower() == normalized_cex
            and event.event_type == "transfer"
            and event.quantity > 0
            and event.event_time.year == year
        ]
        deposit_rows = [
            evidence
            for evidence in self._deposit_history_candidates()
            if self._cex_deposit_row_matches(evidence, normalized_cex, normalized_network, year)
        ]
        deposits: list[WalletFifoCexDepositTransferEvidence] = []
        used_event_ids: set[str] = set()
        for evidence in deposit_rows:
            payload = evidence.payload
            asset = str(payload.get("Coin") or payload.get("coin") or "").upper()
            amount = self._payload_decimal_any(payload, ("Amount", "amount"))
            if not asset or amount is None:
                continue
            tx_id = self._payload_str(payload, "TXID") or self._payload_str(payload, "txId")
            deposit_time = self._parse_binance_time(
                self._payload_str(payload, "Time")
                or self._payload_str(payload, "Insert Time")
                or self._payload_str(payload, "Apply Time")
            )
            match = self._matching_cex_deposit_event(
                deposit_evidence=evidence,
                cex_events=cex_events,
                used_event_ids=used_event_ids,
            )
            if match:
                used_event_ids.add(match.event_id)
            trace = transfer_traces_by_tx.get(tx_id or "")
            deposits.append(
                self._cex_deposit_evidence_item(
                    year=year,
                    cex=normalized_cex,
                    asset=asset,
                    network=self._payload_str(payload, "Network") or normalized_network,
                    deposit_time=deposit_time,
                    credited_quantity=match.quantity if match else amount,
                    onchain_quantity=amount,
                    tx_id=tx_id,
                    deposit_address=self._payload_str(payload, "Address"),
                    deposit_evidence=evidence,
                    cex_event=match,
                    transfer_trace=trace,
                    reviewed_transfer_txids=reviewed_transfer_txids,
                )
            )

        for event in cex_events:
            if normalized_network is not None or event.event_id in used_event_ids:
                continue
            if event.tx_id:
                trace = transfer_traces_by_tx.get(str(event.tx_id))
                deposits.append(
                    self._cex_deposit_evidence_item(
                        year=year,
                        cex=normalized_cex,
                        asset=event.asset.upper(),
                        network=normalized_network,
                        deposit_time=None,
                        credited_quantity=event.quantity,
                        onchain_quantity=None,
                        tx_id=str(event.tx_id),
                        deposit_address=None,
                        deposit_evidence=None,
                        cex_event=event,
                        transfer_trace=trace,
                        reviewed_transfer_txids=reviewed_transfer_txids,
                    )
                )
        deposits.sort(
            key=lambda item: (
                item.evidence_status != "transfer_neutral_fifo_carried",
                -(abs(item.carried_cost_basis_eur)),
                item.cex_credit_time or item.onchain_time or datetime.min.replace(tzinfo=timezone.utc),
                item.asset,
            )
        )
        total_by_asset: dict[str, Decimal] = defaultdict(Decimal)
        for item in deposits:
            total_by_asset[item.asset] += item.credited_quantity
        shown = deposits[: max(1, min(limit, 500))]
        return WalletFifoCexDepositTransferEvidenceReport(
            generated_at=datetime.now(timezone.utc),
            year=year,
            cex=normalized_cex,
            network=normalized_network,
            deposits_count=len(deposits),
            transfer_neutral_count=sum(1 for item in deposits if item.holding_period_continues),
            evidence_ready_count=sum(1 for item in deposits if item.evidence_status in {"transfer_neutral_fifo_carried", "cex_onchain_evidence_ready"}),
            missing_evidence_count=sum(1 for item in deposits if item.missing_evidence),
            total_credited_quantity_by_asset=dict(total_by_asset),
            total_carried_cost_basis_eur=sum((item.carried_cost_basis_eur for item in deposits), Decimal("0")),
            deposits=shown,
            methodology=(
                "Read-only CEX-Deposit-Transfer-Evidence-Ledger. Verknuepft Binance "
                "Deposit-History, Binance-Gutschrift-Event und vorhandene Wallet-FIFO-"
                "Transfertraces. Der technische Sweep zur Binance Hot-/Main-Wallet wird "
                "nur als Exchange-Infrastruktur dokumentiert und nicht als steuerlicher "
                "Nutzertransfer gewertet. Es werden keine Canonical Events, Lots, "
                "Tax-Lines, Preise, Imports oder Review-Entscheidungen veraendert."
            ),
        )

    def cex_sender_ownership_latest(
        self,
        year: int,
        *,
        cex: str = "binance",
        network: str | None = "SOL",
        limit: int = 100,
        artifact_dir: Path | None = None,
    ) -> WalletFifoCexSenderOwnershipSummaryReport:
        normalized_cex = cex.lower()
        normalized_network = network.upper() if network else None
        artifact = self._latest_cex_sender_ownership_artifact(
            evidence_dirs=(
                [artifact_dir]
                if artifact_dir is not None
                else [
                    self.store.path.parent / "var/cex_deposit_sender_ownership",
                    self.store.path.parent.parent / "var/cex_deposit_sender_ownership",
                    Path.cwd() / "var/cex_deposit_sender_ownership",
                    self.DEFAULT_CEX_SENDER_OWNERSHIP_DIR,
                ]
            ),
            year=year,
            cex=normalized_cex,
            network=normalized_network,
        )
        if artifact is None:
            return WalletFifoCexSenderOwnershipSummaryReport(
                generated_at=datetime.now(timezone.utc),
                year=year,
                cex=normalized_cex,
                network=normalized_network,
                artifact_exists=False,
                methodology=(
                    "Read-only Latest-View fuer CEX Deposit Sender Ownership. "
                    "Es wurde noch kein Resolver-Artifact gefunden; die API fuehrt "
                    "keine externen Onchain-Provider-Aufrufe aus und veraendert "
                    "keine Steuer-, FIFO- oder Importdaten."
                ),
            )

        payload = json.loads(artifact.read_text(encoding="utf-8"))
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        raw_results = payload.get("results") if isinstance(payload.get("results"), list) else []
        decisions: list[WalletFifoCexSenderOwnershipDecision] = []
        for row in raw_results[: max(1, min(limit, 500))]:
            if not isinstance(row, dict):
                continue
            decision_layer = row.get("decision_layer") if isinstance(row.get("decision_layer"), dict) else {}
            onchain_sender = row.get("onchain_sender")
            sender_label = self.KNOWN_SOLANA_EXCHANGE_INFRASTRUCTURE.get(str(onchain_sender or ""))
            sender_classification = "exchange_infrastructure" if sender_label else None
            review_note = str(row.get("review_note") or "")
            if sender_label and row.get("final_tax_status") == "UNVERIFIED_THIRD_PARTY":
                review_note = (
                    f"Onchain-Sender ist als {sender_label} gelabelt. "
                    "Fuer steuerneutralen CEX-zu-CEX-Transfer wird der "
                    "passende Bitget Withdrawal-/Account-Ledger-Beleg benoetigt."
                )
            decisions.append(
                WalletFifoCexSenderOwnershipDecision(
                    txid=str(row.get("txid") or ""),
                    timestamp_utc=row.get("timestamp_utc"),
                    asset=str(row.get("asset") or "").upper(),
                    amount=Decimal(str(row.get("amount") or "0")),
                    provider_status=str(row.get("provider_status") or "unknown"),
                    onchain_sender=onchain_sender,
                    onchain_sender_label=sender_label,
                    sender_classification=sender_classification,
                    primary_signer=row.get("primary_signer"),
                    deposit_address=row.get("deposit_address"),
                    cex_account=row.get("cex_account"),
                    fifo_transfer_status=row.get("fifo_transfer_status"),
                    carried_cost_basis_eur=Decimal(str(row.get("carried_cost_basis_eur") or "0")),
                    program_ids=[str(program) for program in row.get("program_ids", []) if program],
                    decision_layer={
                        str(key): bool(value)
                        for key, value in decision_layer.items()
                    },
                    final_tax_status=str(row.get("final_tax_status") or "PENDING_REVIEW"),
                    review_note=review_note,
                )
            )
        status_counts = {
            str(key): int(value)
            for key, value in (summary.get("status_counts") or {}).items()
        }
        return WalletFifoCexSenderOwnershipSummaryReport(
            generated_at=datetime.now(timezone.utc),
            year=int(payload.get("year") or year),
            cex=str(payload.get("cex") or normalized_cex),
            network=str(payload.get("network") or normalized_network) if (payload.get("network") or normalized_network) else None,
            artifact_path=str(artifact),
            artifact_exists=True,
            transactions_count=int(summary.get("transactions") or len(raw_results)),
            status_counts=status_counts,
            tax_neutral_candidates=int(summary.get("tax_neutral_candidates") or 0),
            complex_route_review=int(summary.get("complex_route_review") or 0),
            unverified_third_party=int(summary.get("unverified_third_party") or 0),
            pending_review=int(summary.get("pending_review") or 0),
            decisions=decisions,
            methodology=str(
                payload.get("methodology")
                or (
                    "Read-only Latest-View fuer CEX Deposit Sender Ownership. "
                    "Zeigt das letzte lokal erzeugte Resolver-Artifact und markiert "
                    "eigene Sender nur als Review-Kandidaten, bis die Entscheidung "
                    "bewusst in FIFO/Tax uebernommen wird."
                )
            ),
        )

    @staticmethod
    def _latest_cex_sender_ownership_artifact(
        *,
        evidence_dirs: list[Path],
        year: int,
        cex: str,
        network: str | None,
    ) -> Path | None:
        network_slug = WalletFifoPreviewService._cex_sender_ownership_network_slug(network)
        pattern = f"*_{year}_{cex}_{network_slug}_sender_ownership.json"
        seen_dirs: set[Path] = set()
        matches: list[Path] = []
        for evidence_dir in evidence_dirs:
            resolved_dir = evidence_dir.resolve()
            if resolved_dir in seen_dirs or not resolved_dir.exists():
                continue
            seen_dirs.add(resolved_dir)
            matches = sorted(resolved_dir.glob(pattern), key=lambda path: path.name, reverse=True)
            if matches:
                return matches[0]
        return None

    @staticmethod
    def _cex_sender_ownership_network_slug(network: str | None) -> str:
        if not network:
            return "all"
        normalized = network.lower()
        return {"sol": "solana"}.get(normalized, normalized)

    def cex_exchange_outflow_evidence(
        self,
        year: int,
        *,
        source_exchange: str = "bitget",
        target_cex: str = "binance",
        network: str | None = "SOL",
        window_hours: int = 72,
        limit: int = 100,
    ) -> WalletFifoCexExchangeOutflowEvidenceReport:
        source_exchange_normalized = source_exchange.lower()
        target_cex_normalized = target_cex.lower()
        ownership = self.cex_sender_ownership_latest(
            year=year,
            cex=target_cex_normalized,
            network=network,
            limit=500,
        )
        exchange_deposits = [
            item
            for item in ownership.decisions
            if item.sender_classification == "exchange_infrastructure"
            and item.onchain_sender_label
            and source_exchange_normalized in item.onchain_sender_label.lower()
        ]
        events = [
            event
            for event in self.store.list_canonical_events()
            if source_exchange_normalized in event.source.lower()
            and event.event_type == "transfer"
            and event.quantity < 0
            and event.event_time.year in {year, year - 1, year + 1}
        ]
        raw_evidence = self._cex_exchange_outflow_raw_evidence(source_exchange_normalized, year=year)
        rows: list[WalletFifoCexExchangeOutflowEvidenceRow] = []
        for deposit in exchange_deposits[: max(1, min(limit, 500))]:
            candidates = self._cex_exchange_outflow_candidates_for_deposit(
                deposit=deposit,
                events=events,
                raw_evidence=raw_evidence,
                source_exchange=source_exchange_normalized,
                window_hours=window_hours,
            )
            best = candidates[0] if candidates else None
            status = self._cex_exchange_outflow_row_status(best)
            rows.append(
                WalletFifoCexExchangeOutflowEvidenceRow(
                    deposit_txid=deposit.txid,
                    deposit_time=deposit.timestamp_utc,
                    target_cex=target_cex_normalized,
                    source_exchange=source_exchange_normalized,
                    source_sender=deposit.onchain_sender,
                    source_sender_label=deposit.onchain_sender_label,
                    deposit_address=deposit.deposit_address,
                    asset=deposit.asset,
                    amount=deposit.amount,
                    status=status,
                    candidates_count=len(candidates),
                    best_candidate=best,
                    candidates=candidates[:10],
                    recommended_action=self._cex_exchange_outflow_row_action(status, source_exchange_normalized),
                )
            )
        return WalletFifoCexExchangeOutflowEvidenceReport(
            generated_at=datetime.now(timezone.utc),
            year=year,
            source_exchange=source_exchange_normalized,
            target_cex=target_cex_normalized,
            network=network,
            window_hours=window_hours,
            rows_count=len(rows),
            ready_count=sum(1 for row in rows if row.status in {"exchange_outflow_txid_match_ready", "exchange_outflow_address_txid_ready"}),
            missing_count=sum(1 for row in rows if row.status in {"missing_exchange_outflow_event", "exchange_outflow_ledger_candidate_missing_tx_address"}),
            rows=rows,
            methodology=(
                "Read-only CEX-zu-CEX-Outflow-Evidence. Verknuepft Solana "
                "Deposit-Sender-Ownership mit lokalen Exchange-Abgaengen aus "
                "Canonical Events und optionaler Raw Withdrawal Evidence. Ein "
                "Exchange-Infrastruktur-Label wie Bitget beweist nur die "
                "Absender-Infrastruktur; fuer steuerneutrale FIFO-Fortfuehrung "
                "braucht es den passenden Withdrawal-/Account-Ledger-Beleg des "
                "eigenen Exchange-Kontos. Es werden keine FIFO-, Ledger-, Tax- "
                "oder Importdaten veraendert."
            ),
        )

    def _cex_exchange_outflow_candidates_for_deposit(
        self,
        *,
        deposit: WalletFifoCexSenderOwnershipDecision,
        events: list[CanonicalEvent],
        raw_evidence: list[WalletFifoOriginRawEvidence],
        source_exchange: str,
        window_hours: int,
    ) -> list[WalletFifoCexExchangeOutflowCandidate]:
        if deposit.timestamp_utc is None:
            return []
        deposit_time = self._as_utc(deposit.timestamp_utc)
        start = deposit_time - timedelta(hours=window_hours)
        end = deposit_time + timedelta(hours=window_hours)
        tolerance = self._transfer_match_tolerance(deposit.asset)
        candidates: list[WalletFifoCexExchangeOutflowCandidate] = []
        for event in events:
            if event.asset.upper() != deposit.asset.upper():
                continue
            event_time = self._as_utc(event.event_time)
            if event_time < start or event_time > end:
                continue
            amount_delta = abs(abs(event.quantity) - deposit.amount)
            if amount_delta > tolerance:
                continue
            evidence = self._raw_evidence(event.raw_object_id) if event.raw_object_id else None
            payload = evidence.payload if evidence else {}
            withdrawal_tx_id = (
                self._payload_str(payload, "tx_id")
                or self._payload_str(payload, "txId")
                or self._payload_str(payload, "TXID")
                or self._payload_str(payload, "TxID")
                or self._payload_str(payload, "Transaction hash(txid)")
                or self._payload_str(payload, "Transaction Hash")
                or event.tx_id
            )
            withdrawal_address = (
                self._payload_str(payload, "address")
                or self._payload_str(payload, "Address")
                or self._payload_str(payload, "toAddress")
                or self._payload_str(payload, "ToAddress")
                or self._payload_str(payload, "To Address")
                or self._payload_str(payload, "To address")
                or self._payload_str(payload, "Destination")
            )
            withdrawal_network = (
                self._payload_str(payload, "network")
                or self._payload_str(payload, "Network")
                or self._payload_str(payload, "chain")
                or self._payload_str(payload, "Chain")
            )
            withdrawal_amount = self._payload_decimal_any(payload, ("amount", "Amount", "Quantity"))
            withdrawal_fee = self._payload_decimal_any(payload, ("transaction_fee", "transactionFee", "Transaction Fee", "Withdrawal fee", "withdrawal fee"))
            evidence_status = self._cex_exchange_outflow_candidate_status(
                deposit_txid=deposit.txid,
                withdrawal_tx_id=withdrawal_tx_id,
                withdrawal_address=withdrawal_address,
                raw_evidence_exists=evidence is not None,
                source_exchange=source_exchange,
            )
            candidates.append(
                WalletFifoCexExchangeOutflowCandidate(
                    event_id=event.event_id,
                    event_time=event.event_time,
                    source=event.source,
                    account=event.account,
                    asset=event.asset.upper(),
                    quantity=abs(event.quantity),
                    seconds_delta=int(abs((event_time - deposit_time).total_seconds())),
                    amount_delta=amount_delta,
                    tx_id=event.tx_id,
                    raw_object_id=event.raw_object_id,
                    withdrawal_tx_id=withdrawal_tx_id,
                    withdrawal_address=withdrawal_address,
                    withdrawal_network=withdrawal_network,
                    withdrawal_amount=withdrawal_amount,
                    withdrawal_fee=withdrawal_fee,
                    evidence_status=evidence_status,
                    recommended_action=self._cex_exchange_outflow_candidate_action(evidence_status, source_exchange),
                )
            )
        for evidence in raw_evidence:
            payload = evidence.payload
            asset = (
                self._payload_str(payload, "asset")
                or self._payload_str(payload, "coin")
                or self._payload_str(payload, "Coin")
            )
            if not asset or asset.upper() != deposit.asset.upper():
                continue
            event_time = self._parse_exchange_evidence_time(payload)
            if event_time is None or event_time < start or event_time > end:
                continue
            withdrawal_amount = self._payload_decimal_any(payload, ("size", "amount", "Amount", "Quantity"))
            withdrawal_fee = self._payload_decimal_any(
                payload,
                ("fee", "transaction_fee", "transactionFee", "Transaction Fee", "Withdrawal fee", "withdrawal fee"),
            )
            matched_quantity = self._net_withdrawal_amount(withdrawal_amount, withdrawal_fee)
            if matched_quantity is None:
                continue
            amount_delta = abs(matched_quantity - deposit.amount)
            if amount_delta > tolerance:
                continue
            withdrawal_tx_id = (
                self._payload_str(payload, "tradeId")
                or self._payload_str(payload, "tx_id")
                or self._payload_str(payload, "txId")
                or self._payload_str(payload, "TXID")
                or self._payload_str(payload, "TxID")
                or self._payload_str(payload, "Transaction hash(txid)")
                or self._payload_str(payload, "Transaction Hash")
            )
            withdrawal_address = (
                self._payload_str(payload, "toAddress")
                or self._payload_str(payload, "address")
                or self._payload_str(payload, "Address")
                or self._payload_str(payload, "ToAddress")
                or self._payload_str(payload, "To Address")
                or self._payload_str(payload, "To address")
                or self._payload_str(payload, "Destination")
            )
            withdrawal_network = (
                self._payload_str(payload, "network")
                or self._payload_str(payload, "Network")
                or self._payload_str(payload, "chain")
                or self._payload_str(payload, "Chain")
            )
            evidence_status = self._cex_exchange_outflow_candidate_status(
                deposit_txid=deposit.txid,
                withdrawal_tx_id=withdrawal_tx_id,
                withdrawal_address=withdrawal_address,
                raw_evidence_exists=True,
                source_exchange=source_exchange,
            )
            candidates.append(
                WalletFifoCexExchangeOutflowCandidate(
                    event_id=f"raw:{evidence.raw_object_id}",
                    event_time=event_time,
                    source=evidence.source or source_exchange,
                    account=str(payload.get("account") or source_exchange),
                    asset=asset.upper(),
                    quantity=matched_quantity,
                    seconds_delta=int(abs((event_time - deposit_time).total_seconds())),
                    amount_delta=amount_delta,
                    tx_id=withdrawal_tx_id,
                    raw_object_id=evidence.raw_object_id,
                    withdrawal_tx_id=withdrawal_tx_id,
                    withdrawal_address=withdrawal_address,
                    withdrawal_network=withdrawal_network,
                    withdrawal_amount=withdrawal_amount,
                    withdrawal_fee=withdrawal_fee,
                    evidence_status=evidence_status,
                    recommended_action=self._cex_exchange_outflow_candidate_action(evidence_status, source_exchange),
                )
            )
        candidates.sort(
            key=lambda item: (
                item.evidence_status not in {"exchange_outflow_txid_match_ready", "exchange_outflow_address_txid_ready"},
                item.amount_delta,
                item.seconds_delta,
                item.event_id,
            )
        )
        return candidates

    def _cex_exchange_outflow_raw_evidence(
        self,
        source_exchange: str,
        *,
        year: int,
    ) -> list[WalletFifoOriginRawEvidence]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select r.raw_object_id, r.batch_id, b.source, b.filename, r.row_number, r.payload_json
                from raw_objects r
                left join raw_import_batches b on b.batch_id = r.batch_id
                where lower(coalesce(b.source, '')) like ?
                  and lower(r.payload_json) like '%bitget_withdrawal_evidence%'
                """,
                [f"%{source_exchange.lower()}%"],
            ).fetchall()
        result: list[WalletFifoOriginRawEvidence] = []
        for row in rows:
            evidence = self._evidence_from_row(row)
            event_time = self._parse_exchange_evidence_time(evidence.payload)
            if event_time is None or event_time.year not in {year, year - 1, year + 1}:
                continue
            result.append(evidence)
        return result

    @classmethod
    def _parse_exchange_evidence_time(cls, payload: dict[str, object]) -> datetime | None:
        millis = (
            cls._payload_str(payload, "uTime")
            or cls._payload_str(payload, "utime")
            or cls._payload_str(payload, "cTime")
            or cls._payload_str(payload, "ctime")
        )
        if millis:
            try:
                return datetime.fromtimestamp(int(millis) / 1000, tz=timezone.utc)
            except Exception:
                pass
        return cls._parse_binance_time(
            cls._payload_str(payload, "time")
            or cls._payload_str(payload, "Time")
            or cls._payload_str(payload, "complete_time")
            or cls._payload_str(payload, "Complete Time")
        )

    @staticmethod
    def _net_withdrawal_amount(amount: Decimal | None, fee: Decimal | None) -> Decimal | None:
        if amount is None:
            return None
        if fee is not None and fee < 0:
            return amount + fee
        return amount

    @staticmethod
    def _cex_exchange_outflow_candidate_status(
        *,
        deposit_txid: str,
        withdrawal_tx_id: str | None,
        withdrawal_address: str | None,
        raw_evidence_exists: bool,
        source_exchange: str,
    ) -> str:
        if withdrawal_tx_id and withdrawal_tx_id == deposit_txid:
            return "exchange_outflow_txid_match_ready"
        if withdrawal_tx_id and withdrawal_address:
            return "exchange_outflow_address_txid_ready"
        if withdrawal_tx_id:
            return "exchange_outflow_txid_without_address"
        if raw_evidence_exists:
            return "exchange_outflow_raw_missing_txid_address"
        return f"{source_exchange}_canonical_outflow_without_raw_withdrawal_evidence"

    @staticmethod
    def _cex_exchange_outflow_candidate_action(status: str, source_exchange: str) -> str:
        if status in {"exchange_outflow_txid_match_ready", "exchange_outflow_address_txid_ready"}:
            return "Withdrawal-Beleg pruefen; danach steuerneutralen CEX-zu-CEX-Transfer als Review-Decision dokumentieren."
        if status == "exchange_outflow_txid_without_address":
            return "TXID passt als starker Beleg; Zieladresse aus Exchange-Withdrawal-History/API nachziehen."
        if status == "exchange_outflow_raw_missing_txid_address":
            return "Raw Exchange-Abgang vorhanden; TXID/Zieladresse aus Withdrawal-History/API ergaenzen."
        return f"{source_exchange.title()} Withdrawal-History/API oder CSV-Export fuer diesen Zeitraum importieren."

    @staticmethod
    def _cex_exchange_outflow_row_status(best: WalletFifoCexExchangeOutflowCandidate | None) -> str:
        if best is None:
            return "missing_exchange_outflow_event"
        if best.evidence_status in {"exchange_outflow_txid_match_ready", "exchange_outflow_address_txid_ready"}:
            return best.evidence_status
        return "exchange_outflow_ledger_candidate_missing_tx_address"

    @staticmethod
    def _cex_exchange_outflow_row_action(status: str, source_exchange: str) -> str:
        if status in {"exchange_outflow_txid_match_ready", "exchange_outflow_address_txid_ready"}:
            return "Belegkette ist als Review-Kandidat bereit; steuerneutrale FIFO-Fortfuehrung fachlich pruefen."
        if status == "exchange_outflow_ledger_candidate_missing_tx_address":
            return "Zeit-/betragsnaher Exchange-Abgang gefunden; TXID und Zieladresse aus Withdrawal-History/API ergaenzen."
        return f"{source_exchange.title()} Withdrawal-History/API fuer diesen Zeitraum fehlt oder ist noch nicht importiert."

    def cex_exchange_outflow_anchor_feasibility(
        self,
        year: int,
        *,
        source_exchange: str = "bitget",
        target_cex: str = "binance",
        network: str | None = "SOL",
        window_hours: int = 72,
        limit: int = 200,
    ) -> WalletFifoCexExchangeOutflowAnchorFeasibilityReport:
        source_exchange_normalized = source_exchange.lower()
        target_cex_normalized = target_cex.lower()
        normalized_network = network or "all"
        evidence = self.cex_exchange_outflow_evidence(
            year,
            source_exchange=source_exchange_normalized,
            target_cex=target_cex_normalized,
            network=network,
            window_hours=window_hours,
            limit=max(limit, 1),
        )
        evidence_by_tx = {row.deposit_txid: row for row in evidence.rows}
        preview = self.preview(year=year)
        traces_by_tx = {trace.tx_id: trace for trace in preview.transfer_traces if trace.tx_id}
        items: list[WalletFifoCexExchangeOutflowAnchorFeasibilityItem] = []
        for decision in self.store.list_review_decisions():
            if decision.decision_type != "cex_exchange_outflow":
                continue
            payload = decision.payload
            if str(payload.get("year") or "") != str(year):
                continue
            if str(payload.get("source_exchange") or "").lower() != source_exchange_normalized:
                continue
            if str(payload.get("target_cex") or "").lower() != target_cex_normalized:
                continue
            if str(payload.get("network") or normalized_network) != normalized_network:
                continue
            deposit_txid = str(payload.get("deposit_txid") or "")
            if not deposit_txid:
                continue
            row = evidence_by_tx.get(deposit_txid)
            trace = traces_by_tx.get(deposit_txid)
            item = self._cex_exchange_outflow_anchor_feasibility_item(
                year=year,
                source_exchange=source_exchange_normalized,
                target_cex=target_cex_normalized,
                network=network,
                decision_id=decision.decision_id,
                decision_status=str(payload.get("decision_status") or ""),
                payload=payload,
                row=row,
                trace=trace,
            )
            items.append(item)
        items.sort(key=lambda item: (item.anchor_ready, item.asset, item.deposit_txid))
        limited_items = items[: max(1, min(limit, 500))]
        return WalletFifoCexExchangeOutflowAnchorFeasibilityReport(
            generated_at=datetime.now(timezone.utc),
            year=year,
            source_exchange=source_exchange_normalized,
            target_cex=target_cex_normalized,
            network=network,
            decisions_count=len(items),
            evidence_ready_count=sum(1 for item in items if item.evidence_status in {"exchange_outflow_txid_match_ready", "exchange_outflow_address_txid_ready"}),
            anchor_ready_count=sum(1 for item in items if item.anchor_ready),
            anchor_missing_count=sum(1 for item in items if not item.anchor_ready),
            items=limited_items,
            methodology=(
                "Read-only FIFO-Anker-Vorpruefung fuer gespeicherte "
                "cex_exchange_outflow Review-Decisions. Der Report verknuepft "
                "Review-Decision, Bitget-Withdrawal-Raw-Evidence, Binance-Onchain-"
                "Deposit und vorhandene Wallet-FIFO-Transfertraces. Er schreibt "
                "keine Canonical Events, keine Lots, keine Tax-Lines und keine "
                "Review-Decisions."
            ),
        )

    def _cex_exchange_outflow_anchor_feasibility_item(
        self,
        *,
        year: int,
        source_exchange: str,
        target_cex: str,
        network: str | None,
        decision_id: str,
        decision_status: str,
        payload: dict[str, object],
        row: WalletFifoCexExchangeOutflowEvidenceRow | None,
        trace: WalletFifoTransferTrace | None,
    ) -> WalletFifoCexExchangeOutflowAnchorFeasibilityItem:
        ready_statuses = {"exchange_outflow_txid_match_ready", "exchange_outflow_address_txid_ready"}
        evidence_status = row.status if row is not None else str(payload.get("evidence_status") or "")
        missing: list[str] = []
        if decision_status != "transfer_neutral_fifo_carry_forward_reviewed":
            missing.append("review_decision_not_transfer_neutral")
        if evidence_status not in ready_statuses:
            missing.append("exchange_outflow_evidence_not_ready")
        if trace is None:
            missing.append("wallet_fifo_transfer_trace_missing")
        elif trace.status not in {
            "ok",
            "partial",
            "inferred_cross_pool",
            "inferred_cross_pool_partial",
            "resolved_by_cex_exchange_outflow_anchor",
        }:
            missing.append(f"wallet_fifo_trace_status_{trace.status}")
        anchor_ready = not missing
        if anchor_ready:
            anchor_status = "existing_fifo_anchor_ready"
            recommended_action = "Bestehender Wallet-FIFO-Transfertrace kann als Ankerbeleg genutzt werden; keine automatische Datenmutation erforderlich."
        elif row is not None and evidence_status in ready_statuses and decision_status == "transfer_neutral_fifo_carry_forward_reviewed":
            anchor_status = "evidence_ready_decision_present_fifo_anchor_missing"
            recommended_action = (
                "Beleg und Review-Decision sind vorhanden. Fuer produktive FIFO-Fortfuehrung "
                "fehlt noch ein expliziter, stichtagsgenauer Anchor-/Bridge-Schreibpfad oder "
                "ein vorhandener Wallet-FIFO-Transfertrace."
            )
        else:
            anchor_status = "blocked_missing_evidence_or_decision"
            recommended_action = "Fehlende Review-Decision oder Exchange-Outflow-Evidence nachziehen, bevor ein FIFO-Anker geplant wird."
        best = row.best_candidate if row and row.best_candidate else None
        return WalletFifoCexExchangeOutflowAnchorFeasibilityItem(
            decision_id=decision_id,
            deposit_txid=str(payload.get("deposit_txid") or (row.deposit_txid if row else "")),
            year=year,
            source_exchange=source_exchange,
            target_cex=target_cex,
            network=network,
            asset=str(payload.get("asset") or (row.asset if row else "")).upper(),
            amount=Decimal(str(payload.get("deposit_amount") or (row.amount if row else "0"))),
            decision_status=decision_status,
            evidence_status=evidence_status or None,
            anchor_status=anchor_status,
            anchor_ready=anchor_ready,
            existing_fifo_trace_status=trace.status if trace else None,
            existing_fifo_source_pool_id=trace.source_pool_id if trace else None,
            existing_fifo_target_pool_id=trace.target_pool_id if trace else None,
            exchange_outflow_raw_object_id=str(payload.get("exchange_outflow_raw_object_id") or (best.raw_object_id if best else "") or "") or None,
            exchange_outflow_tx_id=str(payload.get("exchange_outflow_tx_id") or (best.withdrawal_tx_id if best else "") or "") or None,
            exchange_outflow_fee=self._decimal_from_object(payload.get("exchange_outflow_fee")) or (best.withdrawal_fee if best else None),
            amount_delta=self._decimal_from_object(payload.get("amount_delta")) or (best.amount_delta if best else None),
            time_delta_seconds=int(payload.get("time_delta_seconds")) if payload.get("time_delta_seconds") not in (None, "") else (best.seconds_delta if best else None),
            missing_requirements=missing,
            recommended_action=recommended_action,
        )

    @staticmethod
    def _decimal_from_object(value: object) -> Decimal | None:
        if value in (None, ""):
            return None
        try:
            return Decimal(str(value))
        except Exception:
            return None

    def _cex_deposit_row_matches(
        self,
        evidence: WalletFifoOriginRawEvidence,
        cex: str,
        network: str | None,
        year: int,
    ) -> bool:
        source_text = f"{evidence.source or ''} {evidence.filename or ''}".lower()
        if cex not in source_text:
            return False
        payload = evidence.payload
        if str(payload.get("TXID") or payload.get("txId") or "") == "":
            return False
        if network and str(payload.get("Network") or "").upper() != network:
            return False
        deposit_time = self._parse_binance_time(
            self._payload_str(payload, "Time")
            or self._payload_str(payload, "Insert Time")
            or self._payload_str(payload, "Apply Time")
        )
        return bool(deposit_time and deposit_time.year == year)

    def _matching_cex_deposit_event(
        self,
        *,
        deposit_evidence: WalletFifoOriginRawEvidence,
        cex_events: list[CanonicalEvent],
        used_event_ids: set[str],
    ) -> CanonicalEvent | None:
        payload = deposit_evidence.payload
        asset = str(payload.get("Coin") or "").upper()
        amount = self._payload_decimal_any(payload, ("Amount", "amount"))
        deposit_time = self._parse_binance_time(
            self._payload_str(payload, "Time")
            or self._payload_str(payload, "Insert Time")
            or self._payload_str(payload, "Apply Time")
        )
        tx_id = self._payload_str(payload, "TXID") or self._payload_str(payload, "txId")
        if not asset or amount is None:
            return None
        candidates = [
            event
            for event in cex_events
            if event.event_id not in used_event_ids
            and event.asset.upper() == asset
            and abs(event.quantity - amount) <= self._transfer_match_tolerance(asset)
        ]
        if tx_id:
            tx_candidates = [event for event in candidates if str(event.tx_id or "") == tx_id]
            if tx_candidates:
                candidates = tx_candidates
        if deposit_time:
            candidates.sort(key=lambda event: (abs((self._as_utc(event.event_time) - deposit_time).total_seconds()), event.event_id))
        else:
            candidates.sort(key=lambda event: event.event_id)
        return candidates[0] if candidates else None

    def _cex_deposit_evidence_item(
        self,
        *,
        year: int,
        cex: str,
        asset: str,
        network: str | None,
        deposit_time: datetime | None,
        credited_quantity: Decimal,
        onchain_quantity: Decimal | None,
        tx_id: str | None,
        deposit_address: str | None,
        deposit_evidence: WalletFifoOriginRawEvidence | None,
        cex_event: CanonicalEvent | None,
        transfer_trace: WalletFifoTransferTrace | None,
        reviewed_transfer_txids: set[str] | None = None,
    ) -> WalletFifoCexDepositTransferEvidence:
        missing: list[str] = []
        if not tx_id:
            missing.append("onchain_tx_id")
        if not deposit_address:
            missing.append("deposit_address")
        if cex_event is None:
            missing.append("cex_credit_event")
        if transfer_trace is None:
            missing.append("fifo_transfer_trace")
        transfer_neutral_full_statuses = {
            "ok",
            "resolved_by_cex_exchange_outflow_anchor",
            "resolved_by_cex_sender_ownership_anchor",
        }
        transfer_neutral_partial_statuses = {"partial"}
        reviewed_transfer_txids = reviewed_transfer_txids or set()
        holding_period_continues = bool(
            transfer_trace
            and transfer_trace.status in transfer_neutral_full_statuses | transfer_neutral_partial_statuses
        ) or bool(tx_id and tx_id in reviewed_transfer_txids)
        if holding_period_continues:
            evidence_status = (
                "transfer_neutral_fifo_carried"
                if (transfer_trace and transfer_trace.status in transfer_neutral_full_statuses)
                or (tx_id and tx_id in reviewed_transfer_txids)
                else "transfer_neutral_fifo_partial"
            )
        elif tx_id and deposit_address and cex_event is not None:
            evidence_status = "cex_onchain_evidence_ready"
        else:
            evidence_status = "missing_cex_transfer_evidence"
        quantity_delta = (credited_quantity - onchain_quantity) if onchain_quantity is not None else None
        return WalletFifoCexDepositTransferEvidence(
            evidence_id=f"{cex}:{year}:{tx_id or (cex_event.event_id if cex_event else deposit_evidence.raw_object_id if deposit_evidence else 'unknown')}",
            year=year,
            cex=cex,
            asset=asset.upper(),
            network=network,
            onchain_time=deposit_time,
            cex_credit_time=cex_event.event_time if cex_event else None,
            credited_quantity=credited_quantity,
            onchain_quantity=onchain_quantity,
            quantity_delta=quantity_delta,
            deposit_address=deposit_address,
            cex_main_wallet="DWf2k9851Uxny6fvj3jq5bY6W5xaHmjxfBVobMPSHVvM" if cex == "binance" and network == "SOL" else None,
            tx_id=tx_id,
            deposit_raw_object_id=deposit_evidence.raw_object_id if deposit_evidence else None,
            deposit_row_number=deposit_evidence.row_number if deposit_evidence else None,
            cex_event_id=cex_event.event_id if cex_event else None,
            cex_account=cex_event.account if cex_event else None,
            fifo_transfer_status=transfer_trace.status if transfer_trace else "missing",
            fifo_source_pool_id=transfer_trace.source_pool_id if transfer_trace else None,
            fifo_target_pool_id=transfer_trace.target_pool_id if transfer_trace else None,
            fifo_lots_moved=transfer_trace.lots_moved if transfer_trace else 0,
            carried_cost_basis_eur=transfer_trace.carried_cost_basis_eur if transfer_trace else Decimal("0"),
            tax_label="Transfer / Uebertrag" if holding_period_continues else "Deposit-Beleg pruefen",
            holding_period_continues=holding_period_continues,
            evidence_status=evidence_status,
            missing_evidence=missing,
            recommended_action=self._cex_deposit_evidence_action(evidence_status, missing),
        )

    @staticmethod
    def _cex_deposit_evidence_action(evidence_status: str, missing: list[str]) -> str:
        if evidence_status == "transfer_neutral_fifo_carried":
            return "Als steuerneutralen Depotwechsel dokumentieren; Anschaffungsdaten/Haltefrist wurden im Wallet-FIFO-Preview fortgefuehrt."
        if evidence_status == "transfer_neutral_fifo_partial":
            return "Transferanker vorhanden, aber FIFO nur teilweise gedeckt; fehlende Quell-Lots/Herkunft klaeren."
        if evidence_status == "cex_onchain_evidence_ready":
            return "Onchain- und CEX-Beleg vorhanden; Quellwallet als eigene Wallet/Deposit-Transferanker pruefen."
        return f"Fehlende Belege ergaenzen: {', '.join(missing) or 'unbekannt'}."

    def provenance_priorities(self, year: int, *, limit: int = 50) -> WalletFifoProvenancePriorityReport:
        preview = self.preview(year=year)
        events = {event.event_id: event for event in self.store.list_canonical_events()}
        unresolved_preview_traces = [
            trace for trace in preview.transfer_traces if trace.status == "unresolved_inbound_provenance"
        ]
        raw_evidence_by_id = self._raw_evidence_map(
            [
                events[trace.target_event_id].raw_object_id
                for trace in unresolved_preview_traces
                if trace.target_event_id in events and events[trace.target_event_id].raw_object_id
            ]
        )
        deposit_history_rows = self._deposit_history_candidates()
        local_outflow_rows_by_asset: dict[str, list[tuple[object, ...]]] = {}
        withdrawal_evidence_by_asset_event_id: dict[str, dict[str, WalletFifoOriginRawEvidence | None]] = {}
        all_local_outflow_rows_by_asset = self._negative_outflow_rows_by_asset()
        grouped: dict[tuple[str, str, str, str | None], dict[str, object]] = {}
        status_breakdown_items: dict[str, dict[str, object]] = {}
        for trace in unresolved_preview_traces:
            event = events.get(trace.target_event_id)
            if event is None:
                continue
            asset = trace.asset.upper()
            if asset not in local_outflow_rows_by_asset:
                local_outflow_rows_by_asset[asset] = all_local_outflow_rows_by_asset.get(asset, [])
            local_outflow_rows = local_outflow_rows_by_asset[asset]
            if asset not in withdrawal_evidence_by_asset_event_id:
                withdrawal_evidence_by_asset_event_id[asset] = {}
            withdrawal_evidence_by_event_id = withdrawal_evidence_by_asset_event_id[asset]
            best_outflow_candidate = self._best_provenance_outflow_candidate(
                event=event,
                trace=trace,
                rows=local_outflow_rows,
                withdrawal_evidence_by_event_id=withdrawal_evidence_by_event_id,
            )
            key = (trace.asset.upper(), trace.target_pool_id, event.source, event.account)
            item = grouped.setdefault(
                key,
                {
                    "events": [],
                    "quantity_total": Decimal("0"),
                    "cost_basis_total": Decimal("0"),
                    "raw_evidence_count": 0,
                    "deposit_evidence_count": 0,
                    "onchain_tx_id_count": 0,
                    "missing_tx_id_count": 0,
                    "local_outflow_candidate_count": 0,
                    "exchange_outflow_candidate_count": 0,
                    "exchange_internal_context_count": 0,
                    "withdrawal_evidence_ready_count": 0,
                    "event_status_counts": defaultdict(int),
                    "best_outflow_candidate": None,
                    "samples": [],
                },
            )
            candidate = WalletFifoGapCandidateEvent(
                event_id=event.event_id,
                event_time=event.event_time,
                event_type=event.event_type,
                source=event.source,
                account=event.account,
                pool_id=self._pool_id(event),
                asset=event.asset.upper(),
                quantity=event.quantity,
                quote_asset=event.quote_asset,
                quote_quantity=event.quote_quantity,
                tx_id=event.tx_id,
                source_ref=event.source_ref,
                raw_object_id=event.raw_object_id,
                relation="provisional_same_pool_inbound",
                seconds_before_gap=0,
            )
            raw_evidence = raw_evidence_by_id.get(event.raw_object_id or "")
            deposit_evidence = self._matching_deposit_history_from_rows(candidate, deposit_history_rows)
            deposit_payload = deposit_evidence.payload if deposit_evidence else {}
            onchain_tx_id = self._payload_str(deposit_payload, "TXID") or event.tx_id
            deposit_address = self._payload_str(deposit_payload, "Address")
            network = self._payload_str(deposit_payload, "Network")
            event_status, event_action = self._provenance_status_and_action(
                event=event,
                raw_evidence=raw_evidence,
                best_outflow_candidate=best_outflow_candidate,
                deposit_evidence_ready=bool(deposit_evidence and onchain_tx_id),
                raw_evidence_ready=raw_evidence is not None,
            )
            event_status_counts: defaultdict[str, int] = item["event_status_counts"]  # type: ignore[assignment]
            event_status_counts[event_status] += 1
            item["events"].append(event)  # type: ignore[union-attr]
            item["quantity_total"] = item["quantity_total"] + trace.quantity  # type: ignore[operator]
            item["cost_basis_total"] = item["cost_basis_total"] + trace.carried_cost_basis_eur  # type: ignore[operator]
            item["raw_evidence_count"] = item["raw_evidence_count"] + (1 if raw_evidence else 0)  # type: ignore[operator]
            item["deposit_evidence_count"] = item["deposit_evidence_count"] + (1 if deposit_evidence else 0)  # type: ignore[operator]
            item["onchain_tx_id_count"] = item["onchain_tx_id_count"] + (1 if onchain_tx_id else 0)  # type: ignore[operator]
            item["missing_tx_id_count"] = item["missing_tx_id_count"] + (0 if onchain_tx_id else 1)  # type: ignore[operator]
            if best_outflow_candidate is not None:
                item["local_outflow_candidate_count"] = item["local_outflow_candidate_count"] + 1  # type: ignore[operator]
                if best_outflow_candidate.evidence_category == "exchange_outflow_candidate":
                    item["exchange_outflow_candidate_count"] = item["exchange_outflow_candidate_count"] + 1  # type: ignore[operator]
                    if self._is_exchange_internal_context_status(best_outflow_candidate.exchange_evidence_status):
                        item["exchange_internal_context_count"] = item["exchange_internal_context_count"] + 1  # type: ignore[operator]
                if best_outflow_candidate.withdrawal_evidence_status == "withdrawal_address_txid_ready":
                    item["withdrawal_evidence_ready_count"] = item["withdrawal_evidence_ready_count"] + 1  # type: ignore[operator]
                current_best = item["best_outflow_candidate"]
                if current_best is None or self._provenance_outflow_rank(best_outflow_candidate) < self._provenance_outflow_rank(current_best):  # type: ignore[arg-type]
                    item["best_outflow_candidate"] = best_outflow_candidate
            self._add_provenance_status_breakdown_item(
                items=status_breakdown_items,
                status=event_status,
                action=event_action,
                event=event,
                trace=trace,
                best_outflow_candidate=best_outflow_candidate,
            )
            samples = item["samples"]  # type: ignore[assignment]
            if len(samples) < 5:
                samples.append(
                    WalletFifoProvenancePrioritySample(
                        event_id=event.event_id,
                        event_time=event.event_time,
                        tx_id=event.tx_id,
                        quantity=trace.quantity,
                        raw_object_id=event.raw_object_id,
                        has_raw_evidence=raw_evidence is not None,
                        has_deposit_evidence=deposit_evidence is not None,
                        onchain_tx_id=onchain_tx_id,
                        deposit_address=deposit_address,
                        network=network,
                    )
                )
        groups: list[WalletFifoProvenancePriorityGroup] = []
        for (asset, pool_id, source, account), item in grouped.items():
            group_events: list[CanonicalEvent] = item["events"]  # type: ignore[assignment]
            group_events.sort(key=lambda event: event.event_time)
            events_count = len(group_events)
            deposit_count = int(item["deposit_evidence_count"])
            raw_count = int(item["raw_evidence_count"])
            tx_count = int(item["onchain_tx_id_count"])
            withdrawal_ready_count = int(item["withdrawal_evidence_ready_count"])
            exchange_outflow_count = int(item["exchange_outflow_candidate_count"])
            exchange_internal_context_count = int(item["exchange_internal_context_count"])
            local_outflow_count = int(item["local_outflow_candidate_count"])
            status, action = self._provenance_group_status_and_action(
                events_count=events_count,
                deposit_count=deposit_count,
                tx_count=tx_count,
                raw_count=raw_count,
                local_outflow_count=local_outflow_count,
                exchange_outflow_count=exchange_outflow_count,
                exchange_internal_context_count=exchange_internal_context_count,
                withdrawal_ready_count=withdrawal_ready_count,
            )
            priority_score = Decimal(events_count) * Decimal("100") + abs(item["cost_basis_total"])  # type: ignore[arg-type]
            groups.append(
                WalletFifoProvenancePriorityGroup(
                    year=year,
                    asset=asset,
                    pool_id=pool_id,
                    source=source,
                    account=account,
                    events_count=events_count,
                    quantity_total=item["quantity_total"],  # type: ignore[arg-type]
                    carried_cost_basis_eur_total=item["cost_basis_total"],  # type: ignore[arg-type]
                    first_event_at=group_events[0].event_time if group_events else None,
                    last_event_at=group_events[-1].event_time if group_events else None,
                    raw_evidence_count=raw_count,
                    deposit_evidence_count=deposit_count,
                    onchain_tx_id_count=tx_count,
                    missing_tx_id_count=int(item["missing_tx_id_count"]),
                    local_outflow_candidate_count=local_outflow_count,
                    exchange_outflow_candidate_count=exchange_outflow_count,
                    exchange_internal_context_count=exchange_internal_context_count,
                    withdrawal_evidence_ready_count=withdrawal_ready_count,
                    evidence_status=status,
                    event_status_counts=dict(item["event_status_counts"]),  # type: ignore[arg-type]
                    priority_score=priority_score,
                    origin_trace_endpoint=(
                        f"/api/v1/tax-years/{year}/wallet-fifo-origin-trace"
                        f"?asset={asset}&pool_id={pool_id}"
                    ),
                    recommended_action=action,
                    best_outflow_candidate=item["best_outflow_candidate"],  # type: ignore[arg-type]
                    samples=item["samples"],  # type: ignore[arg-type]
                )
            )
        groups.sort(
            key=lambda group: (
                self._provenance_status_order(group.evidence_status),
                -group.events_count,
                -abs(group.carried_cost_basis_eur_total),
                group.asset,
                group.pool_id,
            )
        )
        return WalletFifoProvenancePriorityReport(
            generated_at=datetime.now(timezone.utc),
            year=year,
            unresolved_inbound_provenance_count=preview.unresolved_inbound_provenance_count,
            groups_count=len(groups),
            groups=groups[: max(1, min(limit, 500))],
            status_breakdown=self._build_provenance_status_breakdown(status_breakdown_items),
            methodology=(
                "Read-only Priorisierung offener provisorischer Wallet-FIFO-Zufluesse. "
                "Gruppiert unresolved_inbound_provenance-Traces nach Jahr, Asset, Pool, Quelle "
                "und Account und bewertet vorhandene Raw-/Deposit-/TXID-Evidence. Es werden "
                "keine produktiven Lots, Tax-Lines oder Transferanker geschrieben."
            ),
        )

    def provenance_closure_report(self, year: int, *, limit: int = 50) -> WalletFifoYearProvenanceClosureReport:
        normalized_limit = max(1, min(limit, 500))
        cache_key = (str(self.store.path), year, normalized_limit)
        now = time.monotonic()
        cached = self._PROVENANCE_CLOSURE_CACHE.get(cache_key)
        if cached is not None and now - cached[0] <= self._PREVIEW_CACHE_TTL_SECONDS:
            return cached[1].model_copy(deep=True)
        priority_report = self.provenance_priorities(year=year, limit=500)
        solana_batch = self.solana_provenance_batch_latest(year=year, asset="SOL")
        cex_sender = self.cex_sender_ownership_latest(year=year, cex="binance", network="SOL")
        cex_status_by_asset = {
            decision.asset.upper(): decision.final_tax_status
            for decision in cex_sender.decisions
            if decision.asset
        }
        items: list[WalletFifoYearProvenanceClosureItem] = []
        canonical_events = self.store.list_canonical_events()
        raw_evidence_by_id = self._raw_evidence_map(
            [
                event.raw_object_id
                for event in canonical_events
                if event.raw_object_id and event.event_time.year == year
            ]
        )
        deposit_history_rows = self._deposit_history_candidates()
        deposit_history_index = self._deposit_history_index(deposit_history_rows)
        legacy_cex_deposit_count = 0
        legacy_cex_deposit_mirror_count = 0
        fairspot_staking_return_count = 0
        legacy_counterparty_mirror_count = 0
        legacy_hnt_external_payment_count = 0
        token_redenomination_count = 0
        manual_cex_deposit_count = 0
        exchange_deposit_history_count = 0
        for group in priority_report.groups:
            category = "unresolved_provenance"
            closure_status = "review_required"
            requires_review = True
            tax_hint = "Herkunft offen; nicht automatisch als steuerneutralen Transfer behandeln."
            evidence_refs = [group.origin_trace_endpoint]
            action = group.recommended_action
            if group.source.startswith("opening-balance"):
                category = "opening_balance"
                closure_status = "documented_non_live_opening_balance"
                requires_review = False
                tax_hint = "Belegter Anfangsbestand; kein Live-Zufluss und kein Eigenwallet-Transfer."
                evidence_refs.append(
                    f"/api/v1/tax-years/{year}/wallet-fifo-opening-balance-evidence"
                    f"?asset={group.asset}&pool_id={group.pool_id}"
                )
                action = "Als Anfangsbestand in der Steuerbeilage ausweisen; nicht als Live-Transfer eskalieren."
            elif self._provenance_group_documents_fiat_purchase(
                year=year,
                group=group,
                canonical_events=canonical_events,
                raw_evidence_by_id=raw_evidence_by_id,
            ):
                category = "fiat_purchase"
                closure_status = "documented_fiat_purchase"
                requires_review = False
                tax_hint = "Belegte Anschaffung gegen Fiat; kein Wallet-/Depot-Transfer und keine steuerneutrale Umbuchung."
                action = "Als EUR-Anschaffung im Jahresbeleg ausweisen; nicht als offene Transfer-Herkunft eskalieren."
            else:
                documented_legacy_count = self._provenance_group_legacy_hnt_cex_deposit_count(
                    year=year,
                    group=group,
                    canonical_events=canonical_events,
                    raw_evidence_by_id=raw_evidence_by_id,
                    deposit_history_rows=deposit_history_rows,
                    deposit_history_index=deposit_history_index,
                )
                legacy_cex_deposit_count += documented_legacy_count
                documented_mirror_count = 0
                if documented_legacy_count and documented_legacy_count == group.events_count:
                    category = "legacy_hnt_cex_deposit"
                    closure_status = "documented_legacy_hnt_cex_deposit"
                    requires_review = False
                    tax_hint = (
                        "Heliumtracker-Abgang zur Boerse und Binance-Deposit-History "
                        "mit TXID/Adresse belegen den CEX-Deposit."
                    )
                    action = "Als dokumentierten Legacy-HNT-Transfer zur Boerse im Jahresbeleg ausweisen."
                elif documented_legacy_count:
                    tax_hint = (
                        f"{documented_legacy_count} von {group.events_count} Ereignissen sind "
                        "durch Heliumtracker plus Binance-Deposit-History belegt; Rest bleibt Review."
                    )
                    action = (
                        f"{documented_legacy_count} belegte Legacy-HNT-CEX-Deposits dokumentieren; "
                        "fehlende Deposit-History/TXIDs fuer Restereignisse nachziehen."
                    )
                else:
                    documented_mirror_count = self._provenance_group_legacy_hnt_cex_deposit_mirror_count(
                        year=year,
                        group=group,
                        canonical_events=canonical_events,
                        raw_evidence_by_id=raw_evidence_by_id,
                    )
                    legacy_cex_deposit_mirror_count += documented_mirror_count
                    if documented_mirror_count and documented_mirror_count == group.events_count:
                        category = "legacy_hnt_cex_deposit_mirror"
                        closure_status = "documented_legacy_hnt_cex_deposit_mirror"
                        requires_review = False
                        tax_hint = (
                            "Binance-Deposit-History-Spiegel ist mit Heliumtracker-Abgang "
                            "zur Boerse verbunden; keine zweite Anschaffung behaupten."
                        )
                        action = "Als Spiegelbeleg des Legacy-HNT-CEX-Deposits im Jahresbeleg ausweisen."
                    elif documented_mirror_count:
                        tax_hint = (
                            f"{documented_mirror_count} von {group.events_count} Binance-Deposit-"
                            "Spiegelereignissen sind mit Heliumtracker-Abgaengen belegt; Rest bleibt Review."
                        )
                        action = (
                            f"{documented_mirror_count} belegte Binance-HNT-Deposit-Spiegel dokumentieren; "
                            "fehlende Heliumtracker-Gegenbelege fuer Restereignisse nachziehen."
                        )
                    else:
                        documented_fairspot_count = self._provenance_group_fairspot_staking_return_count(
                            year=year,
                            group=group,
                            canonical_events=canonical_events,
                            raw_evidence_by_id=raw_evidence_by_id,
                        )
                        fairspot_staking_return_count += documented_fairspot_count
                        documented_external_payment_count = (
                            self._provenance_group_legacy_hnt_external_payment_count(
                                year=year,
                                group=group,
                                canonical_events=canonical_events,
                                raw_evidence_by_id=raw_evidence_by_id,
                            )
                        )
                        legacy_hnt_external_payment_count += documented_external_payment_count
                        if documented_fairspot_count and documented_fairspot_count == group.events_count:
                            category = "fairspot_staking_return"
                            closure_status = "documented_fairspot_staking_return"
                            requires_review = False
                            tax_hint = (
                                "Fairspot/Staking-Ruecktransfer zur Main-Legacy-Wallet ist "
                                "durch Helium-Raw-Evidence belegt."
                            )
                            action = "Als steuerneutralen Staking-/Service-Ruecktransfer mit FIFO-Fortfuehrung dokumentieren."
                        elif (
                            documented_external_payment_count
                            and documented_external_payment_count == group.events_count
                        ):
                            category = "legacy_hnt_external_payment"
                            closure_status = "documented_legacy_hnt_payment_provenance"
                            requires_review = False
                            tax_hint = (
                                "Legacy-HNT-Zufluss ist durch Helium-Payment-Raw-Evidence "
                                "mit Payer, Payee, TX-Hash, Zeitstempel, Menge und Oracle-Wert belegt; "
                                "keine Eigenwallet-Transferannahme."
                            )
                            action = (
                                "Konservativ als externe Legacy-HNT-Zahlung im Jahresbeleg ausweisen; "
                                "nur bei spaeterem Sender-Ownership-Nachweis als Transfer/FIFO-Fortfuehrung behandeln."
                            )
                        elif (
                            documented_external_payment_count
                            and documented_fairspot_count + documented_external_payment_count == group.events_count
                        ):
                            category = "legacy_hnt_mixed_payment_provenance"
                            closure_status = "documented_legacy_hnt_payment_provenance"
                            requires_review = False
                            tax_hint = (
                                f"{documented_fairspot_count} Ereignis(se) sind als Fairspot/Staking-"
                                f"Ruecktransfer und {documented_external_payment_count} Ereignis(se) "
                                "als externe Legacy-HNT-Zahlung mit Helium-Raw-Evidence belegt."
                            )
                            action = (
                                "Fairspot-Anteil als steuerneutralen Ruecktransfer dokumentieren; "
                                "externen Payment-Anteil konservativ offenlegen und nicht als "
                                "Eigenwallet-Transfer behandeln."
                            )
                        elif documented_fairspot_count:
                            tax_hint = (
                                f"{documented_fairspot_count} von {group.events_count} Ereignissen sind "
                                "als Fairspot/Staking-Ruecktransfer belegt; Rest bleibt Review."
                            )
                            action = (
                                f"{documented_fairspot_count} belegte Fairspot/Staking-Ruecktransfers dokumentieren; "
                                "fehlende Sender-Ownership fuer Restereignisse nachziehen."
                            )
                        else:
                            documented_counterparty_mirror_count = (
                                self._provenance_group_legacy_counterparty_mirror_count(
                                    year=year,
                                    group=group,
                                    canonical_events=canonical_events,
                                    raw_evidence_by_id=raw_evidence_by_id,
                                )
                            )
                            legacy_counterparty_mirror_count += documented_counterparty_mirror_count
                            if documented_counterparty_mirror_count and documented_counterparty_mirror_count == group.events_count:
                                category = "legacy_counterparty_mirror"
                                closure_status = "documented_legacy_counterparty_mirror"
                                requires_review = False
                                tax_hint = (
                                    "Legacy-HNT-Zielpool ist als Gegenpartei-Spiegel eines "
                                    "Main-Legacy-Outflows mit TX-Hash belegt; nicht als eigene "
                                    "aktuelle Wallet fortfuehren."
                                )
                                action = "Als Gegenpartei-/Service-Spiegel des Main-Legacy-Outflows dokumentieren."
                            elif documented_counterparty_mirror_count:
                                tax_hint = (
                                    f"{documented_counterparty_mirror_count} von {group.events_count} Ereignissen "
                                    "sind als Gegenpartei-Spiegel eines Main-Legacy-Outflows belegt; Rest bleibt Review."
                                )
                                action = (
                                    f"{documented_counterparty_mirror_count} belegte Legacy-Gegenpartei-Spiegel "
                                    "dokumentieren; Restereignisse fachlich pruefen."
                                )
                            else:
                                documented_redenomination_count = (
                                    self._provenance_group_binance_btt_bttc_redenomination_count(
                                        year=year,
                                        group=group,
                                        canonical_events=canonical_events,
                                        raw_evidence_by_id=raw_evidence_by_id,
                                    )
                                )
                                token_redenomination_count += documented_redenomination_count
                                if (
                                    documented_redenomination_count
                                    and documented_redenomination_count == group.events_count
                                ):
                                    category = "token_redenomination"
                                    closure_status = "documented_binance_btt_bttc_redenomination"
                                    requires_review = False
                                    tax_hint = (
                                        "Binance-Transaction-History belegt BTT-Abgang und BTTC-Zugang "
                                        "am selben Tag im Faktor 1:1000; keine neue externe Herkunft."
                                    )
                                    action = (
                                        "Als BTT/BTTC-Redenomination im Jahresbeleg ausweisen; "
                                        "keine steuerneutrale Eigenwallet-Umbuchung und keinen Reward behaupten."
                                    )
                                elif documented_redenomination_count:
                                    tax_hint = (
                                        f"{documented_redenomination_count} von {group.events_count} Ereignissen "
                                        "sind als Binance-BTT/BTTC-Redenomination belegt; Rest bleibt Review."
                                    )
                                    action = (
                                        f"{documented_redenomination_count} Redenomination-Belege dokumentieren; "
                                        "fehlende Gegenzeilen fuer Restereignisse nachziehen."
                                    )
                                if category != "unresolved_provenance":
                                    pass
                                else:
                                    documented_manual_cex_deposit_count = (
                                        self._provenance_group_manual_cex_deposit_history_count(
                                            year=year,
                                            group=group,
                                            canonical_events=canonical_events,
                                            raw_evidence_by_id=raw_evidence_by_id,
                                            deposit_history_rows=deposit_history_rows,
                                            deposit_history_index=deposit_history_index,
                                        )
                                    )
                                    manual_cex_deposit_count += documented_manual_cex_deposit_count
                                    if (
                                        documented_manual_cex_deposit_count
                                        and documented_manual_cex_deposit_count == group.events_count
                                    ):
                                        category = "manual_cex_deposit_history"
                                        closure_status = "documented_manual_cex_deposit_history"
                                        requires_review = False
                                        tax_hint = (
                                            "Manueller Deposit-Lot ist mit Binance Deposit-History "
                                            "inklusive Adresse, Netzwerk, TXID, Zeitstempel und Menge belegt; "
                                            "Sender-Ownership wird nicht automatisch behauptet."
                                        )
                                        action = (
                                            "Als dokumentierten CEX-Deposit/externen Zufluss im Jahresbeleg "
                                            "ausweisen; nur bei spaeterem Sendernachweis als Eigenwallet-Transfer behandeln."
                                        )
                                    elif documented_manual_cex_deposit_count:
                                        tax_hint = (
                                            f"{documented_manual_cex_deposit_count} von {group.events_count} manuellen "
                                            "Deposit-Lots sind mit Binance Deposit-History belegt; Rest bleibt Review."
                                        )
                                        action = (
                                            f"{documented_manual_cex_deposit_count} manuelle CEX-Deposit-Belege "
                                            "dokumentieren; fehlende Deposit-History fuer Restereignisse nachziehen."
                                        )
                                if category != "unresolved_provenance":
                                    pass
                                else:
                                    documented_exchange_deposit_count = (
                                        self._provenance_group_exchange_deposit_history_count(
                                            year=year,
                                            group=group,
                                            canonical_events=canonical_events,
                                            raw_evidence_by_id=raw_evidence_by_id,
                                        )
                                    )
                                    exchange_deposit_history_count += documented_exchange_deposit_count
                                    if (
                                        documented_exchange_deposit_count
                                        and documented_exchange_deposit_count == group.events_count
                                    ):
                                        category = "exchange_deposit_history"
                                        closure_status = "documented_exchange_deposit_history"
                                        requires_review = False
                                        tax_hint = (
                                            "Exchange-Deposit-History belegt Zeitstempel, Asset, Menge, Netzwerk "
                                            "und TXID; Sender-Ownership wird daraus nicht automatisch behauptet."
                                        )
                                        action = (
                                            "Als dokumentierten Exchange-Deposit/externen Zufluss im Jahresbeleg "
                                            "ausweisen; nur bei spaeterem Sendernachweis als Eigenwallet-Transfer "
                                            "mit FIFO-Fortfuehrung behandeln."
                                        )
                                    elif documented_exchange_deposit_count:
                                        tax_hint = (
                                            f"{documented_exchange_deposit_count} von {group.events_count} Ereignissen "
                                            "sind durch Exchange-Deposit-History mit TXID/Netzwerk belegt; Rest bleibt Review."
                                        )
                                        action = (
                                            f"{documented_exchange_deposit_count} belegte Exchange-Deposits dokumentieren; "
                                            "fehlende Deposit-History/TXIDs fuer Restereignisse nachziehen."
                                        )
            if category == "unresolved_provenance" and group.source.lower() == "binance" and group.asset.upper() == "SOL":
                category = "cex_deposit_sender_ownership"
                cex_status = cex_status_by_asset.get(group.asset.upper())
                if cex_status == "TAX_NEUTRAL_TRANSFER_PENDING_REVIEW":
                    closure_status = "tax_neutral_candidate_review_required"
                    tax_hint = "Potentieller steuerneutraler CEX-Deposit; erst nach Review FIFO fortschreiben."
                else:
                    closure_status = "unverified_cex_deposit_sender"
                    tax_hint = "Deposit-/CEX-Beleg vorhanden, aber Onchain-Sender nicht als eigene Wallet belegt."
                evidence_refs.append(
                    f"/api/v1/tax-years/{year}/cex-sender-ownership-latest?cex=binance&network=SOL"
                )
                action = "Sender-Ownership belegen oder konservativ offen lassen; nicht automatisch steuerneutral schließen."
            elif category == "unresolved_provenance" and group.source.lower() == "solana_rpc" and group.asset.upper() == "SOL":
                category = "solana_external_or_unknown_origin"
                if self._solana_batch_documents_moonpay_apple_pay_onramp(
                    solana_batch=solana_batch,
                    group=group,
                ):
                    category = "fiat_onramp_purchase"
                    closure_status = "documented_moonpay_apple_pay_onramp"
                    requires_review = False
                    tax_hint = (
                        "Alchemy/RPC-Batch belegt Zufluss von der bekannten MoonPay-/Apple-Pay-"
                        "Onramp-Adresse; als Fiat-Anschaffung dokumentieren, keine FIFO-Fortfuehrung "
                        "aus einer Vorwallet behaupten."
                    )
                    action = (
                        "MoonPay-/Apple-Pay-Zahlungsbelege als Anschaffungsnachweis beilegen; "
                        "nicht als steuerneutralen Eigenwallet-Transfer behandeln."
                    )
                elif solana_batch.exists and solana_batch.failed_count == 0 and solana_batch.own_transfer_candidates_count == 0:
                    closure_status = "external_or_unknown_origin_documented"
                    tax_hint = "Alchemy/RPC-Batch fand keine eigene Senderwallet; Herkunft bleibt extern/unklar."
                    action = "Programm-/Service-/Exchange-Kontext belegen; nicht automatisch als Eigenwallet-Transfer behandeln."
                elif solana_batch.own_transfer_candidates_count > 0:
                    closure_status = "tax_neutral_candidate_review_required"
                    tax_hint = "Batch enthält Eigenwallet-Kandidaten; Review vor FIFO-Fortschreibung erforderlich."
                else:
                    closure_status = "solana_batch_incomplete"
                    tax_hint = "Solana-Batch nicht vollständig; TXIDs erneut klassifizieren."
                evidence_refs.extend(
                    [
                        f"/api/v1/tax-years/{year}/wallet-fifo-solana-provenance-batch-latest?asset=SOL",
                        f"/api/v1/tax-years/{year}/wallet-fifo-solana-raw-bmf-evidence-summary?asset=SOL",
                        f"/api/v1/tax-years/{year}/wallet-fifo-solana-raw-provenance-senders?asset=SOL",
                    ]
                )
            elif (
                category == "unresolved_provenance"
                and self._provenance_group_solana_helium_reward_context_count(
                    year=year,
                    group=group,
                    canonical_events=canonical_events,
                    raw_evidence_by_id=raw_evidence_by_id,
                )
                == group.events_count
            ):
                category = "solana_helium_reward_context"
                closure_status = "documented_solana_helium_reward_context"
                requires_review = False
                tax_hint = (
                    "Solana-Raw-Evidence belegt Helium/HNT-IOT-MOBILE Claim-/Staking-Reward-Kontext "
                    "auf eigener Wallet; kein ungeklärter CEX-/Fremdtransfer."
                )
                action = (
                    "Als dokumentierten Helium/Solana-Reward-Kontext im Jahresbeleg ausweisen; "
                    "Reward-/Income-Behandlung bleibt in den Steuerjahreswerten separat nachvollziehbar."
                )
                evidence_refs.append(
                    f"/api/v1/tax-years/{year}/wallet-fifo-provenance-events"
                    f"?asset={group.asset}&pool_id={group.pool_id}"
                )
            items.append(
                WalletFifoYearProvenanceClosureItem(
                    category=category,
                    closure_status=closure_status,
                    asset=group.asset,
                    pool_id=group.pool_id,
                    source=group.source,
                    account=group.account,
                    events_count=group.events_count,
                    quantity_total=group.quantity_total,
                    carried_cost_basis_eur_total=group.carried_cost_basis_eur_total,
                    evidence_status=group.evidence_status,
                    requires_review=requires_review,
                    tax_treatment_hint=tax_hint,
                    evidence_refs=evidence_refs,
                    recommended_action=action,
                )
            )
        shown = items[:normalized_limit]
        report = WalletFifoYearProvenanceClosureReport(
            generated_at=datetime.now(timezone.utc),
            year=year,
            unresolved_inbound_provenance_count=priority_report.unresolved_inbound_provenance_count,
            groups_count=priority_report.groups_count,
            documented_non_live_count=sum(1 for item in items if item.closure_status == "documented_non_live_opening_balance"),
            documented_fiat_purchase_count=sum(1 for item in items if item.closure_status == "documented_fiat_purchase"),
            documented_legacy_cex_deposit_count=legacy_cex_deposit_count,
            documented_legacy_cex_deposit_mirror_count=legacy_cex_deposit_mirror_count,
            documented_fairspot_staking_return_count=fairspot_staking_return_count,
            documented_legacy_counterparty_mirror_count=legacy_counterparty_mirror_count,
            documented_legacy_hnt_external_payment_count=legacy_hnt_external_payment_count,
            documented_token_redenomination_count=token_redenomination_count,
            documented_manual_cex_deposit_count=manual_cex_deposit_count,
            documented_exchange_deposit_history_count=exchange_deposit_history_count,
            external_or_unknown_count=sum(1 for item in items if item.closure_status == "external_or_unknown_origin_documented"),
            unverified_cex_count=sum(1 for item in items if item.closure_status == "unverified_cex_deposit_sender"),
            tax_neutral_candidate_count=sum(1 for item in items if item.closure_status == "tax_neutral_candidate_review_required"),
            review_required_count=sum(1 for item in items if item.requires_review),
            items=shown,
            methodology=(
                "Read-only Jahresabschluss der offenen Wallet-FIFO-Provenance. "
                "Kombiniert Provenance-Prioritaeten, Opening-Balance-Evidence, "
                "Solana-Provenance-Batch und CEX-Sender-Ownership-Artefakte. "
                "Der Report klassifiziert nur den Nachweisstatus und schreibt keine "
                "Canonical Events, Lots, Tax-Lines, Preise, Imports, Transferanker "
                "oder Review-Entscheidungen."
            ),
        )
        self._PROVENANCE_CLOSURE_CACHE[cache_key] = (now, report.model_copy(deep=True))
        return report

    def _provenance_group_documents_fiat_purchase(
        self,
        *,
        year: int,
        group: WalletFifoProvenancePriorityGroup,
        canonical_events: list[object],
        raw_evidence_by_id: dict[str, WalletFifoOriginRawEvidence | None],
    ) -> bool:
        if group.source.lower() != "binance":
            return False
        group_events = [
            event
            for event in canonical_events
            if event.event_time.year == year
            and event.source.lower() == "binance"
            and event.asset.upper() == group.asset.upper()
            and self._pool_id(event) == group.pool_id
            and event.quantity > 0
            and event.quote_asset is not None
            and event.quote_asset.upper() in {"EUR", "USD"}
        ]
        if len(group_events) != group.events_count:
            return False
        quantity_total = sum((event.quantity for event in group_events), Decimal("0"))
        if quantity_total != group.quantity_total:
            return False
        for event in group_events:
            evidence = raw_evidence_by_id.get(event.raw_object_id or "")
            if evidence is None or evidence.source.lower() != "binance":
                return False
            filename = evidence.filename.lower()
            payload = evidence.payload
            if "fiat-buy" not in filename and not (
                "Spend Amount" in payload and "Receive Amount" in payload and "Transaction ID" in payload
            ):
                return False
        return True

    def _provenance_group_solana_helium_reward_context_count(
        self,
        *,
        year: int,
        group: WalletFifoProvenancePriorityGroup,
        canonical_events: list[object],
        raw_evidence_by_id: dict[str, WalletFifoOriginRawEvidence | None],
    ) -> int:
        if group.source.lower() != "solana_rpc" or group.asset.upper() not in {"HNT", "IOT", "MOBILE"}:
            return 0
        group_events = [
            event
            for event in canonical_events
            if event.event_time.year == year
            and event.source.lower() == "solana_rpc"
            and event.asset.upper() == group.asset.upper()
            and self._pool_id(event) == group.pool_id
            and event.quantity > 0
        ]
        if not group_events:
            return 0
        documented = 0
        for event in group_events:
            raw_evidence = raw_evidence_by_id.get(event.raw_object_id or "")
            if self._is_solana_helium_reward_claim_context(event=event, raw_evidence=raw_evidence):
                documented += 1
        return documented

    def _solana_batch_documents_moonpay_apple_pay_onramp(
        self,
        *,
        solana_batch: WalletFifoSolanaProvenanceBatchLatest,
        group: WalletFifoProvenancePriorityGroup,
    ) -> bool:
        if (
            group.source.lower() != "solana_rpc"
            or group.asset.upper() != "SOL"
            or not solana_batch.exists
            or solana_batch.failed_count != 0
            or solana_batch.own_transfer_candidates_count != 0
            or solana_batch.classified_count < group.events_count
        ):
            return False
        try:
            payload = json.loads(Path(solana_batch.artifact_path).read_text(encoding="utf-8"))
        except Exception:
            return False
        classifications = payload.get("classifications")
        if not isinstance(classifications, list) or len(classifications) < group.events_count:
            return False
        sender = self.MOONPAY_APPLE_PAY_SOLANA_SENDER
        matching = [
            item
            for item in classifications
            if isinstance(item, dict)
            and str(item.get("asset") or "").upper() == "SOL"
            and str(item.get("status") or "") == "external_or_unknown_origin"
            and str(item.get("sender_owner") or "") == sender
        ]
        if len(matching) < group.events_count:
            return False
        matched_amount_total = sum(
            (
                Decimal(str(item.get("matched_amount") or item.get("expected_amount") or "0"))
                for item in matching
            ),
            Decimal("0"),
        )
        tolerance = self._transfer_match_tolerance("SOL") * Decimal(str(max(1, group.events_count)))
        return abs(matched_amount_total - group.quantity_total) <= tolerance

    def _provenance_group_legacy_hnt_cex_deposit_count(
        self,
        *,
        year: int,
        group: WalletFifoProvenancePriorityGroup,
        canonical_events: list[object],
        raw_evidence_by_id: dict[str, WalletFifoOriginRawEvidence | None],
        deposit_history_rows: list[WalletFifoOriginRawEvidence],
        deposit_history_index: dict[tuple[str, Decimal], list[WalletFifoOriginRawEvidence]],
    ) -> int:
        if group.asset.upper() != "HNT" or group.source.lower() != "helium":
            return 0
        group_events = [
            event
            for event in canonical_events
            if event.event_time.year == year
            and event.source.lower() == group.source.lower()
            and event.asset.upper() == "HNT"
            and self._pool_id(event) == group.pool_id
            and event.quantity > 0
        ]
        if not group_events:
            return 0
        documented = 0
        for event in group_events:
            raw_evidence = raw_evidence_by_id.get(event.raw_object_id or "")
            payload = raw_evidence.payload if raw_evidence is not None else {}
            receiver = str(payload.get("Receiver") or event.account or "").strip().lower()
            sender = str(payload.get("Sender") or "").strip()
            if "binance" not in receiver:
                continue
            if sender and not self._is_legacy_helium_wallet_like(sender):
                continue
            candidate = WalletFifoGapCandidateEvent(
                event_id=event.event_id,
                event_time=event.event_time,
                event_type=event.event_type,
                source=event.source,
                account=event.account,
                pool_id=self._pool_id(event),
                asset=event.asset.upper(),
                quantity=event.quantity,
                quote_asset=event.quote_asset,
                quote_quantity=event.quote_quantity,
                tx_id=event.tx_id,
                source_ref=event.source_ref,
                raw_object_id=event.raw_object_id,
                relation="provisional_same_pool_inbound",
                seconds_before_gap=0,
            )
            deposit = self._matching_deposit_history_from_rows(
                candidate,
                deposit_history_rows,
                deposit_history_index=deposit_history_index,
                amount_tolerance=Decimal("0.01"),
            )
            if deposit is None:
                continue
            deposit_payload = deposit.payload
            if not self._payload_str(deposit_payload, "TXID") or not self._payload_str(deposit_payload, "Address"):
                continue
            documented += 1
        return min(documented, group.events_count)

    def _provenance_group_legacy_hnt_external_payment_count(
        self,
        *,
        year: int,
        group: WalletFifoProvenancePriorityGroup,
        canonical_events: list[object],
        raw_evidence_by_id: dict[str, WalletFifoOriginRawEvidence | None],
    ) -> int:
        if group.asset.upper() != "HNT" or group.source.lower() != "helium":
            return 0
        group_events = [
            event
            for event in canonical_events
            if event.event_time.year == year
            and event.source.lower() == group.source.lower()
            and event.asset.upper() == "HNT"
            and self._pool_id(event) == group.pool_id
            and event.quantity > 0
        ]
        documented = 0
        for event in group_events:
            evidence = raw_evidence_by_id.get(event.raw_object_id or "")
            payload = evidence.payload if evidence is not None else {}
            tx_type = str(payload.get("type") or payload.get("Type") or "").strip().lower()
            if not tx_type.startswith("payment_"):
                continue
            payer = str(payload.get("payer") or payload.get("Payer") or payload.get("Sender") or "").replace("\u00a0", "").strip()
            payee = str(payload.get("payee") or payload.get("Payee") or payload.get("Receiver") or event.account or "").replace("\u00a0", "").strip()
            if not payer or not payee:
                continue
            if payer in {self.MAIN_HELIUM_LEGACY_WALLET, self.FAIRSPOT_STAKING_WALLET}:
                continue
            if payee != str(event.account or "").replace("\u00a0", "").strip():
                continue
            if not self._payload_str(payload, "transaction_hash") and not self._payload_str(payload, "TXID"):
                continue
            documented += 1
        return min(documented, group.events_count)

    def _provenance_group_exchange_deposit_history_count(
        self,
        *,
        year: int,
        group: WalletFifoProvenancePriorityGroup,
        canonical_events: list[object],
        raw_evidence_by_id: dict[str, WalletFifoOriginRawEvidence | None],
    ) -> int:
        if group.source.lower() not in {"pionex"}:
            return 0
        group_events = [
            event
            for event in canonical_events
            if event.event_time.year == year
            and event.source.lower() == group.source.lower()
            and event.asset.upper() == group.asset.upper()
            and self._pool_id(event) == group.pool_id
            and event.quantity > 0
        ]
        if not group_events:
            return 0
        documented = 0
        for event in group_events:
            evidence = raw_evidence_by_id.get(event.raw_object_id or "")
            if evidence is None:
                continue
            payload = evidence.payload
            if not self._payload_is_exchange_deposit_history(payload):
                continue
            payload_asset = (
                self._payload_str(payload, "coin")
                or self._payload_str(payload, "Coin")
                or self._payload_str(payload, "asset")
                or self._payload_str(payload, "Asset")
                or ""
            ).upper()
            if payload_asset and payload_asset != group.asset.upper():
                continue
            payload_amount = self._payload_decimal(payload, "amount")
            if payload_amount is None:
                payload_amount = self._payload_decimal(payload, "Amount")
            if payload_amount is not None and abs(payload_amount - event.quantity) > Decimal("0.00000001"):
                continue
            documented += 1
        return min(documented, group.events_count)

    def _provenance_group_manual_cex_deposit_history_count(
        self,
        *,
        year: int,
        group: WalletFifoProvenancePriorityGroup,
        canonical_events: list[object],
        raw_evidence_by_id: dict[str, WalletFifoOriginRawEvidence | None],
        deposit_history_rows: list[WalletFifoOriginRawEvidence],
        deposit_history_index: dict[tuple[str, Decimal], list[WalletFifoOriginRawEvidence]],
    ) -> int:
        if group.source.lower() != "manual-csv":
            return 0
        group_events = [
            event
            for event in canonical_events
            if event.event_time.year == year
            and event.source.lower() == group.source.lower()
            and event.asset.upper() == group.asset.upper()
            and self._pool_id(event) == group.pool_id
            and event.quantity > 0
        ]
        documented = 0
        for event in group_events:
            evidence = raw_evidence_by_id.get(event.raw_object_id or "")
            payload = evidence.payload if evidence is not None else {}
            if str(payload.get("type") or "").strip().lower() not in {"deposit", "opening deposit"}:
                continue
            candidate = WalletFifoGapCandidateEvent(
                event_id=event.event_id,
                event_time=event.event_time,
                event_type=event.event_type,
                source=event.source,
                account=event.account,
                pool_id=self._pool_id(event),
                asset=event.asset.upper(),
                quantity=event.quantity,
                quote_asset=event.quote_asset,
                quote_quantity=event.quote_quantity,
                tx_id=str(payload.get("source_ref") or event.tx_id or ""),
                source_ref=event.source_ref,
                raw_object_id=event.raw_object_id,
                relation="provisional_same_pool_inbound",
                seconds_before_gap=0,
            )
            deposit = self._matching_deposit_history_from_rows(
                candidate,
                deposit_history_rows,
                deposit_history_index=deposit_history_index,
            )
            if deposit is None:
                continue
            deposit_payload = deposit.payload
            if not self._payload_str(deposit_payload, "TXID") or not self._payload_str(deposit_payload, "Address"):
                continue
            documented += 1
        return min(documented, group.events_count)

    def _payload_is_exchange_deposit_history(self, payload: dict[str, object]) -> bool:
        tx_type = (
            self._payload_str(payload, "tx_type")
            or self._payload_str(payload, "Tx Type")
            or self._payload_str(payload, "type")
            or self._payload_str(payload, "Type")
            or ""
        ).lower()
        if tx_type and "deposit" not in tx_type:
            return False
        txid = self._payload_str(payload, "txid") or self._payload_str(payload, "TXID") or self._payload_str(payload, "TxID")
        network = self._payload_str(payload, "network") or self._payload_str(payload, "Network")
        timestamp = (
            self._payload_str(payload, "date(UTC+0)")
            or self._payload_str(payload, "date")
            or self._payload_str(payload, "Date")
            or self._payload_str(payload, "time")
            or self._payload_str(payload, "Time")
        )
        return bool(txid and network and timestamp)

    def _provenance_group_binance_btt_bttc_redenomination_count(
        self,
        *,
        year: int,
        group: WalletFifoProvenancePriorityGroup,
        canonical_events: list[object],
        raw_evidence_by_id: dict[str, WalletFifoOriginRawEvidence | None],
    ) -> int:
        if group.source.lower() != "binance" or group.asset.upper() != "BTTC":
            return 0
        group_events = [
            event
            for event in canonical_events
            if event.event_time.year == year
            and event.source.lower() == "binance"
            and event.asset.upper() == "BTTC"
            and self._pool_id(event) == group.pool_id
            and event.quantity > 0
        ]
        outflows = [
            event
            for event in canonical_events
            if event.event_time.year == year
            and event.source.lower() == "binance"
            and event.asset.upper() == "BTTC"
            and self._pool_id(event) == group.pool_id
            and event.quantity < 0
        ]
        documented = 0
        for event in group_events:
            evidence = raw_evidence_by_id.get(event.raw_object_id or "")
            payload = evidence.payload if evidence is not None else {}
            if self._payload_str(payload, "Operation") != "Airdrop Assets":
                continue
            if (self._payload_str(payload, "Coin") or "").upper() != "BTTC":
                continue
            if self._matching_btt_bttc_redenomination_outflow(
                target_event=event,
                outflows=outflows,
                raw_evidence_by_id=raw_evidence_by_id,
            ):
                documented += 1
        return min(documented, group.events_count)

    def _matching_btt_bttc_redenomination_outflow(
        self,
        *,
        target_event: CanonicalEvent,
        outflows: list[CanonicalEvent],
        raw_evidence_by_id: dict[str, WalletFifoOriginRawEvidence | None],
    ) -> CanonicalEvent | None:
        for outflow in outflows:
            if outflow.event_time.date() != target_event.event_time.date():
                continue
            if outflow.event_time >= target_event.event_time:
                continue
            if abs((abs(outflow.quantity) * Decimal("1000")) - target_event.quantity) > Decimal("0.00000001"):
                continue
            evidence = raw_evidence_by_id.get(outflow.raw_object_id or "")
            payload = evidence.payload if evidence is not None else {}
            if self._payload_str(payload, "Operation") != "Token Swap - Redenomination/Rebranding":
                continue
            if (self._payload_str(payload, "Coin") or "").upper() != "BTT":
                continue
            return outflow
        return None

    def _provenance_group_legacy_hnt_cex_deposit_mirror_count(
        self,
        *,
        year: int,
        group: WalletFifoProvenancePriorityGroup,
        canonical_events: list[object],
        raw_evidence_by_id: dict[str, WalletFifoOriginRawEvidence | None],
    ) -> int:
        if group.asset.upper() != "HNT" or group.source.lower() != "binance":
            return 0
        group_events = [
            event
            for event in canonical_events
            if event.event_time.year == year
            and event.source.lower() == group.source.lower()
            and event.asset.upper() == "HNT"
            and self._pool_id(event) == group.pool_id
            and event.quantity > 0
        ]
        if not group_events:
            return 0
        helium_events = [
            event
            for event in canonical_events
            if event.event_time.year == year
            and event.source.lower() == "helium"
            and event.asset.upper() == "HNT"
            and event.quantity > 0
        ]
        documented = 0
        for event in group_events:
            deposit_evidence = raw_evidence_by_id.get(event.raw_object_id or "")
            deposit_payload = deposit_evidence.payload if deposit_evidence is not None else {}
            if not self._payload_str(deposit_payload, "TXID") or not self._payload_str(deposit_payload, "Address"):
                continue
            if self._matching_legacy_hnt_binance_outflow(
                event=event,
                helium_events=helium_events,
                raw_evidence_by_id=raw_evidence_by_id,
            ):
                documented += 1
        return min(documented, group.events_count)

    def _matching_legacy_hnt_binance_outflow(
        self,
        *,
        event: CanonicalEvent,
        helium_events: list[CanonicalEvent],
        raw_evidence_by_id: dict[str, WalletFifoOriginRawEvidence | None],
    ) -> CanonicalEvent | None:
        amount_tolerance = Decimal("0.01")
        for helium_event in helium_events:
            if abs(abs(helium_event.quantity) - abs(event.quantity)) > amount_tolerance:
                continue
            if helium_event.event_time.date() != event.event_time.date():
                continue
            evidence = raw_evidence_by_id.get(helium_event.raw_object_id or "")
            payload = evidence.payload if evidence is not None else {}
            receiver = str(payload.get("Receiver") or helium_event.account or "").strip().lower()
            sender = str(payload.get("Sender") or "").strip()
            if "binance" not in receiver:
                continue
            if sender and not self._is_legacy_helium_wallet_like(sender):
                continue
            return helium_event
        return None

    def _provenance_group_fairspot_staking_return_count(
        self,
        *,
        year: int,
        group: WalletFifoProvenancePriorityGroup,
        canonical_events: list[object],
        raw_evidence_by_id: dict[str, WalletFifoOriginRawEvidence | None],
    ) -> int:
        if group.asset.upper() != "HNT" or group.source.lower() != "helium":
            return 0
        group_events = [
            event
            for event in canonical_events
            if event.event_time.year == year
            and event.source.lower() == group.source.lower()
            and event.asset.upper() == "HNT"
            and self._pool_id(event) == group.pool_id
            and event.quantity > 0
        ]
        documented = 0
        for event in group_events:
            evidence = raw_evidence_by_id.get(event.raw_object_id or "")
            payload = evidence.payload if evidence is not None else {}
            payer = str(payload.get("payer") or payload.get("Payer") or payload.get("Sender") or "").replace("\u00a0", "").strip()
            payee = str(payload.get("payee") or payload.get("Payee") or payload.get("Receiver") or event.account or "").replace("\u00a0", "").strip()
            if payer != self.FAIRSPOT_STAKING_WALLET:
                continue
            if payee != self.MAIN_HELIUM_LEGACY_WALLET:
                continue
            if not self._payload_str(payload, "transaction_hash") and not self._payload_str(payload, "TXID"):
                continue
            documented += 1
        return min(documented, group.events_count)

    def _provenance_group_legacy_counterparty_mirror_count(
        self,
        *,
        year: int,
        group: WalletFifoProvenancePriorityGroup,
        canonical_events: list[object],
        raw_evidence_by_id: dict[str, WalletFifoOriginRawEvidence | None],
    ) -> int:
        if group.asset.upper() != "HNT" or group.source.lower() != "helium":
            return 0
        if group.pool_id == f"helium:{self.MAIN_HELIUM_LEGACY_WALLET}":
            return 0
        group_events = [
            event
            for event in canonical_events
            if event.event_time.year == year
            and event.source.lower() == group.source.lower()
            and event.asset.upper() == "HNT"
            and self._pool_id(event) == group.pool_id
            and event.quantity > 0
        ]
        main_outflows = [
            event
            for event in canonical_events
            if event.event_time.year == year
            and event.source.lower() == "helium"
            and event.asset.upper() == "HNT"
            and event.account == self.MAIN_HELIUM_LEGACY_WALLET
            and event.quantity < 0
        ]
        documented = 0
        for event in group_events:
            if self._matching_legacy_main_outflow(
                target_event=event,
                main_outflows=main_outflows,
                raw_evidence_by_id=raw_evidence_by_id,
            ):
                documented += 1
        return min(documented, group.events_count)

    def _matching_legacy_main_outflow(
        self,
        *,
        target_event: CanonicalEvent,
        main_outflows: list[CanonicalEvent],
        raw_evidence_by_id: dict[str, WalletFifoOriginRawEvidence | None],
    ) -> CanonicalEvent | None:
        amount_tolerance = Decimal("0.01")
        target_account = str(target_event.account or "").replace("\u00a0", "").strip()
        if not target_account:
            return None
        for outflow in main_outflows:
            if outflow.event_time.date() != target_event.event_time.date():
                continue
            if abs(abs(outflow.quantity) - abs(target_event.quantity)) > amount_tolerance:
                continue
            evidence = raw_evidence_by_id.get(outflow.raw_object_id or "")
            payload = evidence.payload if evidence is not None else {}
            payer = str(payload.get("payer") or payload.get("Payer") or payload.get("Sender") or "").replace("\u00a0", "").strip()
            payee = str(payload.get("payee") or payload.get("Payee") or payload.get("Receiver") or "").replace("\u00a0", "").strip()
            if payer != self.MAIN_HELIUM_LEGACY_WALLET:
                continue
            if not self._legacy_account_matches(target_account, payee):
                continue
            if not self._payload_str(payload, "transaction_hash") and not self._payload_str(payload, "TXID"):
                continue
            return outflow
        return None

    def _legacy_account_matches(self, short_or_full: str, full: str) -> bool:
        candidate = short_or_full.replace("\u00a0", "").strip()
        target = full.replace("\u00a0", "").strip()
        if not candidate or not target:
            return False
        if candidate == target:
            return True
        if "..." not in candidate:
            return False
        prefix, suffix = candidate.split("...", 1)
        return bool(prefix) and bool(suffix) and target.startswith(prefix) and target.endswith(suffix)

    def _is_legacy_helium_wallet_like(self, value: str) -> bool:
        normalized = value.replace("\u00a0", "").strip()
        if not normalized:
            return False
        if "..." in normalized:
            return True
        return len(normalized) >= 30 and normalized[0] == "1"

    def provenance_events(
        self,
        year: int,
        *,
        asset: str | None = None,
        pool_id: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> WalletFifoProvenanceEventReport:
        preview = self.preview(year=year)
        canonical_events = {event.event_id: event for event in self.store.list_canonical_events()}
        unresolved_traces = [
            trace
            for trace in preview.transfer_traces
            if trace.status == "unresolved_inbound_provenance"
            and (asset is None or trace.asset.upper() == asset.upper())
            and (pool_id is None or trace.target_pool_id == pool_id)
        ]
        raw_evidence_by_id = self._raw_evidence_map(
            [
                canonical_events[trace.target_event_id].raw_object_id
                for trace in unresolved_traces
                if trace.target_event_id in canonical_events and canonical_events[trace.target_event_id].raw_object_id
            ]
        )
        deposit_history_rows = self._deposit_history_candidates()
        local_outflow_rows_by_asset: dict[str, list[tuple[object, ...]]] = {}
        withdrawal_evidence_by_asset_event_id: dict[str, dict[str, WalletFifoOriginRawEvidence | None]] = {}
        all_local_outflow_rows_by_asset = self._negative_outflow_rows_by_asset()
        events: list[WalletFifoProvenanceEvent] = []
        normalized_offset = max(0, offset)
        normalized_limit = max(1, min(limit, 1000))
        for trace in unresolved_traces[normalized_offset : normalized_offset + normalized_limit]:
            event = canonical_events.get(trace.target_event_id)
            if event is None:
                continue
            candidate = WalletFifoGapCandidateEvent(
                event_id=event.event_id,
                event_time=event.event_time,
                event_type=event.event_type,
                source=event.source,
                account=event.account,
                pool_id=self._pool_id(event),
                asset=event.asset.upper(),
                quantity=event.quantity,
                quote_asset=event.quote_asset,
                quote_quantity=event.quote_quantity,
                tx_id=event.tx_id,
                source_ref=event.source_ref,
                raw_object_id=event.raw_object_id,
                relation="provisional_same_pool_inbound",
                seconds_before_gap=0,
            )
            raw_evidence = raw_evidence_by_id.get(event.raw_object_id or "")
            deposit_evidence = self._matching_deposit_history_from_rows(candidate, deposit_history_rows)
            deposit_payload = deposit_evidence.payload if deposit_evidence else {}
            onchain_tx_id = self._payload_str(deposit_payload, "TXID") or event.tx_id
            deposit_address = self._payload_str(deposit_payload, "Address")
            network = self._payload_str(deposit_payload, "Network")
            asset_key = trace.asset.upper()
            if asset_key not in local_outflow_rows_by_asset:
                local_outflow_rows_by_asset[asset_key] = all_local_outflow_rows_by_asset.get(asset_key, [])
            local_outflow_rows = local_outflow_rows_by_asset[asset_key]
            if asset_key not in withdrawal_evidence_by_asset_event_id:
                withdrawal_evidence_by_asset_event_id[asset_key] = {}
            withdrawal_evidence_by_event_id = withdrawal_evidence_by_asset_event_id[asset_key]
            best_outflow_candidate = self._best_provenance_outflow_candidate(
                event=event,
                trace=trace,
                rows=local_outflow_rows,
                withdrawal_evidence_by_event_id=withdrawal_evidence_by_event_id,
            )
            status, action = self._provenance_status_and_action(
                event=event,
                raw_evidence=raw_evidence,
                best_outflow_candidate=best_outflow_candidate,
                deposit_evidence_ready=bool(deposit_evidence and onchain_tx_id),
                raw_evidence_ready=raw_evidence is not None,
            )
            events.append(
                WalletFifoProvenanceEvent(
                    event_id=event.event_id,
                    event_time=event.event_time,
                    source=event.source,
                    account=event.account,
                    asset=trace.asset,
                    pool_id=trace.target_pool_id,
                    quantity=trace.quantity,
                    carried_cost_basis_eur=trace.carried_cost_basis_eur,
                    tx_id=event.tx_id,
                    raw_object_id=event.raw_object_id,
                    has_raw_evidence=raw_evidence is not None,
                    has_deposit_evidence=deposit_evidence is not None,
                    onchain_tx_id=onchain_tx_id,
                    deposit_address=deposit_address,
                    network=network,
                    best_outflow_candidate=best_outflow_candidate,
                    evidence_status=status,
                    recommended_action=action,
                )
            )
        return WalletFifoProvenanceEventReport(
            generated_at=datetime.now(timezone.utc),
            year=year,
            asset=asset.upper() if asset else None,
            pool_id=pool_id,
            offset=normalized_offset,
            limit=normalized_limit,
            events_count=len(unresolved_traces),
            events=events,
            methodology=(
                "Read-only Einzelereignisse offener Wallet-FIFO-Zufluss-Herkunft. "
                "Filtert unresolved_inbound_provenance nach Jahr, optional Asset und Pool, "
                "und zeigt vorhandene Raw-/Deposit-/TXID-Evidence. Es werden keine "
                "Transferanker oder Steuerdaten geschrieben."
            ),
        )

    def exchange_evidence_gaps(
        self,
        year: int,
        *,
        asset: str | None = None,
        pool_id: str | None = None,
        limit: int = 50,
    ) -> WalletFifoExchangeEvidenceGapReport:
        event_report = self.provenance_events(
            year,
            asset=asset,
            pool_id=pool_id,
            limit=1000,
        )
        canonical_events = {event.event_id: event for event in self.store.list_canonical_events()}
        gaps: list[WalletFifoExchangeEvidenceGap] = []
        for event in event_report.events:
            if event.evidence_status != "exchange_outflow_candidate" or event.best_outflow_candidate is None:
                continue
            inbound_raw = self._raw_evidence(event.raw_object_id) if event.raw_object_id else None
            outflow_raw = (
                self._raw_evidence(event.best_outflow_candidate.raw_object_id)
                if event.best_outflow_candidate.raw_object_id
                else None
            )
            inbound_event = canonical_events.get(event.event_id)
            if inbound_event is None:
                continue
            missing_fields = self._exchange_evidence_missing_fields(event.best_outflow_candidate)
            source_label = event.best_outflow_candidate.source.lower()
            expected_source = (
                "Binance Withdrawal History/API"
                if source_label == "binance"
                else "Bitget Deposit-Withdrawal History/API"
                if source_label == "bitget"
                else f"{event.best_outflow_candidate.source} Withdrawal-/Deposit-History"
            )
            gaps.append(
                WalletFifoExchangeEvidenceGap(
                    gap_id=f"{event.event_id}:{event.best_outflow_candidate.event_id or 'outflow'}",
                    year=year,
                    asset=event.asset,
                    pool_id=event.pool_id,
                    inbound_event_id=event.event_id,
                    inbound_event_time=event.event_time,
                    inbound_source=event.source,
                    inbound_account=event.account,
                    inbound_quantity=event.quantity,
                    inbound_tx_id=event.tx_id,
                    inbound_raw_evidence=inbound_raw,
                    outflow_candidate=event.best_outflow_candidate,
                    outflow_raw_evidence=outflow_raw,
                    missing_fields=missing_fields,
                    evidence_status="exchange_evidence_missing_fields",
                    expected_evidence_source=expected_source,
                    recommended_action=(
                        f"{expected_source} fuer Asset {event.asset} und Zeitpunkt "
                        f"{event.best_outflow_candidate.event_time.isoformat()} beschaffen/importieren. "
                        f"Fehlende Felder: {', '.join(missing_fields) or 'keine'}."
                    ),
                )
            )
        gaps.sort(
            key=lambda gap: (
                gap.outflow_candidate.source,
                gap.asset,
                gap.inbound_event_time,
                abs(gap.inbound_quantity),
            )
        )
        return WalletFifoExchangeEvidenceGapReport(
            generated_at=datetime.now(timezone.utc),
            year=year,
            gaps_count=len(gaps),
            gaps=gaps[: max(1, min(limit, 500))],
            methodology=(
                "Read-only Liste der offenen Exchange-Evidence-Gaps aus der Wallet-FIFO-Provenance. "
                "Enthaelt nur Events mit Detailstatus exchange_outflow_candidate. Interne Bitget-Kontexte, "
                "lokale Onchain-Kandidaten und Raw-only Faelle werden nicht aufgenommen."
            ),
        )

    def raw_provenance_breakdown(
        self,
        year: int,
        *,
        asset: str | None = None,
        pool_id: str | None = None,
        limit: int = 50,
    ) -> WalletFifoRawProvenanceBreakdownReport:
        event_report = self.provenance_events(
            year,
            asset=asset,
            pool_id=pool_id,
            limit=1000,
        )
        breakdown_events = [
            event
            for event in event_report.events
            if event.evidence_status in {"raw_transaction_evidence_only", "solana_tiny_raw_credit"}
        ]
        raw_evidence_by_id = self._raw_evidence_map([event.raw_object_id for event in breakdown_events])
        grouped: dict[tuple[str, str, str, str, str | None, str | None, str | None, str], dict[str, object]] = {}
        for event in breakdown_events:
            evidence = raw_evidence_by_id.get(event.raw_object_id or "")
            raw_source = evidence.source if evidence else None
            raw_filename = evidence.filename if evidence else None
            raw_pattern = self._raw_provenance_pattern(
                event=event,
                evidence=evidence,
            )
            key = (
                raw_pattern,
                event.asset.upper(),
                event.pool_id,
                event.source,
                event.account,
                raw_source,
                raw_filename,
                self._raw_provenance_action_key(evidence.payload if evidence else {}),
            )
            item = grouped.setdefault(
                key,
                {
                    "events": [],
                    "quantity_total": Decimal("0"),
                    "cost_basis_total": Decimal("0"),
                    "tx_id_count": 0,
                    "tiny_quantity_count": 0,
                    "sample_event_ids": [],
                    "sample_tx_ids": [],
                },
            )
            group_events: list[WalletFifoProvenanceEvent] = item["events"]  # type: ignore[assignment]
            group_events.append(event)
            item["quantity_total"] = item["quantity_total"] + event.quantity  # type: ignore[operator]
            item["cost_basis_total"] = item["cost_basis_total"] + event.carried_cost_basis_eur  # type: ignore[operator]
            if event.tx_id:
                item["tx_id_count"] = int(item["tx_id_count"]) + 1
                sample_tx_ids: list[str] = item["sample_tx_ids"]  # type: ignore[assignment]
                if len(sample_tx_ids) < 5:
                    sample_tx_ids.append(event.tx_id)
            if abs(event.quantity) <= Decimal("0.00001"):
                item["tiny_quantity_count"] = int(item["tiny_quantity_count"]) + 1
            sample_event_ids: list[str] = item["sample_event_ids"]  # type: ignore[assignment]
            if len(sample_event_ids) < 5:
                sample_event_ids.append(event.event_id)

        groups: list[WalletFifoRawProvenanceBreakdownGroup] = []
        for (raw_pattern, group_asset, group_pool_id, source, account, raw_source, raw_filename, _action_key), item in grouped.items():
            group_events: list[WalletFifoProvenanceEvent] = item["events"]  # type: ignore[assignment]
            group_events.sort(key=lambda event: event.event_time)
            groups.append(
                WalletFifoRawProvenanceBreakdownGroup(
                    year=year,
                    evidence_status=group_events[0].evidence_status if group_events else "raw_transaction_evidence_only",
                    raw_pattern=raw_pattern,
                    asset=group_asset,
                    pool_id=group_pool_id,
                    source=source,
                    account=account,
                    raw_source=raw_source,
                    raw_filename=raw_filename,
                    events_count=len(group_events),
                    quantity_total=item["quantity_total"],  # type: ignore[arg-type]
                    carried_cost_basis_eur_total=item["cost_basis_total"],  # type: ignore[arg-type]
                    first_event_at=group_events[0].event_time if group_events else None,
                    last_event_at=group_events[-1].event_time if group_events else None,
                    tx_id_count=int(item["tx_id_count"]),
                    tiny_quantity_count=int(item["tiny_quantity_count"]),
                    sample_event_ids=item["sample_event_ids"],  # type: ignore[arg-type]
                    sample_tx_ids=item["sample_tx_ids"],  # type: ignore[arg-type]
                    recommended_action=self._raw_provenance_recommended_action(raw_pattern),
                )
            )
        groups.sort(
            key=lambda group: (
                -group.events_count,
                -abs(group.carried_cost_basis_eur_total),
                group.raw_pattern,
                group.asset,
                group.pool_id,
            )
        )
        return WalletFifoRawProvenanceBreakdownReport(
            generated_at=datetime.now(timezone.utc),
            year=year,
            groups_count=len(groups),
            raw_transaction_evidence_only_count=sum(
                1 for event in breakdown_events if event.evidence_status == "raw_transaction_evidence_only"
            ),
            solana_tiny_raw_credit_count=sum(
                1 for event in breakdown_events if event.evidence_status == "solana_tiny_raw_credit"
            ),
            groups=groups[: max(1, min(limit, 500))],
            methodology=(
                "Read-only Breakdown der Wallet-FIFO-Provenance-Events mit Status "
                "raw_transaction_evidence_only oder solana_tiny_raw_credit. Gruppiert "
                "nach Asset, Pool, Quelle, Raw-Quelle/Datei und Payload-Muster. Es "
                "werden keine Imports, Lots, Tax-Lines oder Transferanker geschrieben."
            ),
        )

    def opening_balance_evidence(
        self,
        year: int,
        *,
        asset: str | None = None,
        pool_id: str | None = None,
        limit: int = 50,
    ) -> WalletFifoOpeningBalanceEvidenceReport:
        event_report = self.provenance_events(
            year,
            asset=asset,
            pool_id=pool_id,
            limit=1000,
        )
        candidate_events = [
            event
            for event in event_report.events
            if event.has_raw_evidence and (event.source or "").startswith("opening-balance")
        ]
        raw_evidence_by_id = self._raw_evidence_map([event.raw_object_id for event in candidate_events])
        rows: list[WalletFifoOpeningBalanceEvidence] = []
        quantity_by_asset: dict[str, Decimal] = defaultdict(Decimal)
        total_cost_basis = Decimal("0")
        for event in candidate_events:
            evidence = raw_evidence_by_id.get(event.raw_object_id or "")
            quantity_by_asset[event.asset.upper()] += event.quantity
            total_cost_basis += event.carried_cost_basis_eur
            rows.append(
                WalletFifoOpeningBalanceEvidence(
                    event_id=event.event_id,
                    event_time=event.event_time,
                    source=event.source,
                    account=event.account,
                    asset=event.asset.upper(),
                    pool_id=event.pool_id,
                    quantity=event.quantity,
                    carried_cost_basis_eur=event.carried_cost_basis_eur,
                    raw_object_id=event.raw_object_id,
                    raw_source=evidence.source if evidence else None,
                    raw_filename=evidence.filename if evidence else None,
                    raw_row_number=evidence.row_number if evidence else None,
                    raw_payload=evidence.payload if evidence else {},
                    provenance_status=event.evidence_status,
                    recommended_action=(
                        "Anfangsbestand als belegten Startbestand dokumentieren. "
                        "Nicht als Live-Zufluss oder Eigenwallet-Transfer werten; "
                        "bei Steuerreport-Beilage Stichtag, Menge, Konto, Kostenbasis und CSV-Rohzeile ausweisen."
                    ),
                )
            )
        rows.sort(key=lambda row: (row.event_time, row.asset, row.pool_id))
        return WalletFifoOpeningBalanceEvidenceReport(
            generated_at=datetime.now(timezone.utc),
            year=year,
            asset=asset.upper() if asset else None,
            pool_id=pool_id,
            rows_count=len(rows),
            total_quantity_by_asset=dict(quantity_by_asset),
            total_cost_basis_eur=total_cost_basis,
            rows=rows[: max(1, min(limit, 500))],
            methodology=(
                "Read-only Opening-Balance-Evidence-Report fuer offene Wallet-FIFO-Provenance. "
                "Der Report filtert vorhandene Opening-Balance-Rohbelege aus den unresolved "
                "Inbound-Provenance-Spuren, zeigt Menge, Kostenbasis und CSV-Rohzeile und schreibt "
                "keine Imports, Lots, Tax-Lines, Transferanker oder Review-Entscheidungen."
            ),
        )

    @staticmethod
    def _raw_provenance_pattern(
        *,
        event: WalletFifoProvenanceEvent,
        evidence: WalletFifoOriginRawEvidence | None,
    ) -> str:
        payload = evidence.payload if evidence else {}
        raw_source = (evidence.source if evidence else event.source).strip().lower() if (evidence and evidence.source) else event.source.strip().lower()
        action = WalletFifoPreviewService._raw_provenance_action_key(payload)
        if raw_source == "solana_rpc":
            if event.asset.upper() == "SOL" and abs(event.quantity) <= Decimal("0.00001"):
                return "solana_rpc_tiny_sol_credit"
            return "solana_rpc_onchain_raw_tx"
        if raw_source == "bitget":
            if "STRATEGY" in action:
                return "bitget_strategy_raw_context"
            if action:
                return "bitget_raw_context"
        if raw_source.startswith("opening-balance"):
            return "opening_balance_adjustment"
        return "raw_transaction_evidence"

    @staticmethod
    def _raw_provenance_action_key(payload: dict[str, object]) -> str:
        return str(
            payload.get("Action")
            or payload.get("action")
            or payload.get("Action (English)")
            or payload.get("action (english)")
            or payload.get("Type")
            or payload.get("type")
            or ""
        ).strip().upper()

    @staticmethod
    def _raw_provenance_recommended_action(raw_pattern: str) -> str:
        if raw_pattern == "solana_rpc_tiny_sol_credit":
            return "Solana-Mikrozufluesse buendeln; bei steuerlicher Irrelevanz als Dust-/Rent-/Programmkontext dokumentieren."
        if raw_pattern == "solana_rpc_onchain_raw_tx":
            return "Solana-TX per Provenance-Batch/Solscan klassifizieren: Eigenwallet, DEX/Service, externer Zufluss oder Anfangsbestand."
        if raw_pattern == "bitget_strategy_raw_context":
            return "Bitget-Strategy-Kontext gegen Gegenbuchung pruefen; nicht als externe Wallet-Herkunft eskalieren, wenn interne Strategy-Bewegung belegt ist."
        if raw_pattern == "bitget_raw_context":
            return "Bitget-Rohaktion fachlich zuordnen und bei Bedarf Import-/Normalizer-Regel ergaenzen."
        if raw_pattern == "opening_balance_adjustment":
            return "Anfangsbestand mit Stichtag, Quelle und Beleg dokumentieren; nicht als Live-Zufluss interpretieren."
        return "Raw-Beleg fachlich klassifizieren und passende Provenance-Regel ergaenzen."

    @staticmethod
    def _exchange_evidence_missing_fields(candidate: WalletFifoProvenanceOutflowSummary) -> list[str]:
        missing: list[str] = []
        if not candidate.withdrawal_tx_id:
            missing.append("withdrawal_tx_id")
        if not candidate.withdrawal_address:
            missing.append("withdrawal_address")
        if not candidate.withdrawal_network:
            missing.append("withdrawal_network")
        return missing

    def _best_provenance_outflow_candidate(
        self,
        *,
        event: CanonicalEvent,
        trace: WalletFifoTransferTrace,
        rows: list[tuple[object, ...]],
        withdrawal_evidence_by_event_id: dict[str, WalletFifoOriginRawEvidence | None],
    ) -> WalletFifoProvenanceOutflowSummary | None:
        summaries = self._provenance_outflow_summaries(
            event=event,
            trace=trace,
            rows=rows,
            withdrawal_evidence_by_event_id=withdrawal_evidence_by_event_id,
        )
        if not summaries:
            return None
        summaries.sort(key=self._provenance_outflow_rank)
        return summaries[0]

    def _bitget_cex_deposit_local_onchain_match_candidate(
        self,
        *,
        event: CanonicalEvent,
        trace: WalletFifoTransferTrace,
        rows: list[tuple[object, ...]],
        withdrawal_evidence_by_event_id: dict[str, WalletFifoOriginRawEvidence | None],
    ) -> WalletFifoProvenanceOutflowSummary | None:
        if not self._is_bitget_recharge_deposit_event(event):
            return None
        inbound_raw_evidence = self._raw_evidence(event.raw_object_id) if event.raw_object_id else None
        if not self._is_bitget_recharge_deposit_payload(inbound_raw_evidence):
            return None
        candidates = [
            summary
            for summary in self._provenance_outflow_summaries(
                event=event,
                trace=trace,
                rows=rows,
                withdrawal_evidence_by_event_id=withdrawal_evidence_by_event_id,
            )
            if summary.evidence_category == "same_wallet_onchain_flow_candidate"
            and summary.source == "solana_rpc"
            and summary.raw_object_id
            and summary.amount_delta <= self._transfer_match_tolerance(trace.asset)
            and summary.seconds_delta <= 10 * 60
        ]
        for candidate in sorted(candidates, key=lambda item: (item.amount_delta, item.seconds_delta, item.event_time)):
            raw_evidence = self._raw_evidence(candidate.raw_object_id) if candidate.raw_object_id else None
            if self._is_matching_known_wallet_spl_outflow(
                raw_evidence=raw_evidence,
                asset=trace.asset.upper(),
                amount=trace.quantity,
            ):
                return candidate
        return None

    def _best_provenance_internal_context_candidate(
        self,
        *,
        event: CanonicalEvent,
        trace: WalletFifoTransferTrace,
        rows: list[tuple[object, ...]],
        withdrawal_evidence_by_event_id: dict[str, WalletFifoOriginRawEvidence | None],
    ) -> WalletFifoProvenanceOutflowSummary | None:
        summaries = [
            summary
            for summary in self._provenance_outflow_summaries(
                event=event,
                trace=trace,
                rows=rows,
                withdrawal_evidence_by_event_id=withdrawal_evidence_by_event_id,
            )
            if self._is_exchange_internal_context_status(summary.exchange_evidence_status)
        ]
        if not summaries:
            return None
        summaries.sort(key=lambda candidate: (candidate.amount_delta, candidate.seconds_delta, candidate.event_time))
        return summaries[0]

    def _provenance_outflow_summaries(
        self,
        *,
        event: CanonicalEvent,
        trace: WalletFifoTransferTrace,
        rows: list[tuple[object, ...]],
        withdrawal_evidence_by_event_id: dict[str, WalletFifoOriginRawEvidence | None],
    ) -> list[WalletFifoProvenanceOutflowSummary]:
        candidates = self._nearby_solana_outflow_candidates_from_rows(
            rows=rows,
            asset=trace.asset.upper(),
            inbound_time=self._as_utc(event.event_time),
            inbound_amount=trace.quantity,
            window_hours=48,
            amount_tolerance_percent=Decimal("1"),
            withdrawal_evidence_by_event_id=withdrawal_evidence_by_event_id,
        )
        if not candidates:
            return []
        return [
            WalletFifoProvenanceOutflowSummary(
                event_id=candidate.event_id,
                source=candidate.source,
                account=candidate.account,
                event_time=candidate.event_time,
                asset=candidate.asset.upper(),
                quantity=candidate.quantity,
                tx_id=candidate.tx_id,
                seconds_delta=candidate.seconds_delta,
                amount_delta=candidate.amount_delta,
                evidence_category=candidate.evidence_category,
                exchange_evidence_status=candidate.exchange_evidence_status,
                withdrawal_evidence_status=candidate.withdrawal_evidence_status,
                withdrawal_tx_id=candidate.withdrawal_tx_id,
                withdrawal_address=candidate.withdrawal_address,
                withdrawal_network=candidate.withdrawal_network,
                withdrawal_amount=candidate.withdrawal_amount,
                withdrawal_fee=candidate.withdrawal_fee,
                raw_object_id=candidate.raw_object_id,
                recommended_action=candidate.recommended_action,
            )
            for candidate in candidates
        ]

    @staticmethod
    def _provenance_outflow_rank(candidate: WalletFifoProvenanceOutflowSummary) -> tuple[int, Decimal, int]:
        if candidate.withdrawal_evidence_status == "withdrawal_address_txid_ready":
            evidence_rank = 0
        elif candidate.exchange_evidence_status in {
            "transaction_history_without_address_txid",
            "withdrawal_transaction_without_address_txid",
            "withdrawal_address_or_txid_in_raw_payload",
        }:
            evidence_rank = 1
        elif candidate.evidence_category == "same_wallet_onchain_flow_candidate":
            evidence_rank = 2
        elif candidate.evidence_category == "exchange_outflow_candidate":
            evidence_rank = 3 if WalletFifoPreviewService._is_exchange_internal_context_status(candidate.exchange_evidence_status) else 1
        else:
            evidence_rank = 4
        return (evidence_rank, candidate.amount_delta, candidate.seconds_delta)

    @staticmethod
    def _provenance_status_order(status: str) -> int:
        return {
            "withdrawal_evidence_ready": 0,
            "cex_deposit_local_onchain_match": 1,
            "exchange_outflow_candidate": 1,
            "deposit_evidence_ready": 2,
            "fiat_onramp_purchase": 2,
            "local_outflow_candidate": 3,
            "exchange_internal_context": 4,
            "solana_tiny_raw_credit": 5,
            "solana_helium_reward_context": 6,
            "raw_transaction_evidence_only": 7,
            "missing_source_evidence": 8,
        }.get(status, 99)

    def _provenance_status_and_action(
        self,
        *,
        event: CanonicalEvent,
        raw_evidence: WalletFifoOriginRawEvidence | None,
        best_outflow_candidate: WalletFifoProvenanceOutflowSummary | None,
        deposit_evidence_ready: bool,
        raw_evidence_ready: bool,
    ) -> tuple[str, str]:
        if best_outflow_candidate and best_outflow_candidate.withdrawal_evidence_status == "withdrawal_address_txid_ready":
            return (
                "withdrawal_evidence_ready",
                "Withdrawal-API/History belegt lokalen Abgang mit Adresse/TXID; als Transferanker-Kandidat im Review pruefen.",
            )
        if (
            self._is_bitget_recharge_deposit_event(event)
            and self._is_bitget_recharge_deposit_payload(raw_evidence)
            and best_outflow_candidate
        ):
            if (
                best_outflow_candidate.evidence_category == "same_wallet_onchain_flow_candidate"
                and best_outflow_candidate.raw_object_id
                and best_outflow_candidate.seconds_delta <= 10 * 60
                and best_outflow_candidate.amount_delta <= self._transfer_match_tolerance(event.asset)
                and self._is_matching_known_wallet_spl_outflow(
                    raw_evidence=self._raw_evidence(best_outflow_candidate.raw_object_id),
                    asset=event.asset.upper(),
                    amount=event.quantity,
                )
            ):
                return (
                    "cex_deposit_local_onchain_match",
                    "Bitget-Deposit-Ledger und eigener Solana-Onchain-Abgang passen nach Betrag, Zeit, Sender und SPL-Transfer; als steuerneutralen Depotwechsel-Beleg dokumentieren.",
                )
        if best_outflow_candidate and self._is_exchange_internal_context_status(best_outflow_candidate.exchange_evidence_status):
            return (
                "exchange_internal_context",
                "Exchange-Gegenbewegung ist interner Earn-/Fund-/Strategy-/Trading-Kontext; nicht als Blockchain-Withdrawal werten.",
            )
        if best_outflow_candidate and best_outflow_candidate.evidence_category == "exchange_outflow_candidate":
            return (
                "exchange_outflow_candidate",
                "Zeit-/betragsnaher Exchange-Abgang gefunden; Withdrawal-History/API-Beleg mit Adresse und TXID vervollstaendigen.",
            )
        if best_outflow_candidate:
            return (
                "local_outflow_candidate",
                "Zeit-/betragsnaher lokaler Abgang gefunden; Onchain-/Service-Kontext fachlich pruefen.",
            )
        if deposit_evidence_ready:
            return (
                "deposit_evidence_ready",
                "Onchain-Gegenwallet pruefen und bei eigener Umbuchung Transferanker-Kandidat bilden.",
            )
        if raw_evidence_ready and self._is_solana_tiny_raw_credit(event=event, raw_evidence=raw_evidence):
            return (
                "solana_tiny_raw_credit",
                "Winziger SOL-Raw-Zufluss; als Dust-/Rent-/Programmkontext buendeln und nicht mit wertrelevanten Herkunftsluecken vermischen.",
            )
        if raw_evidence_ready and self._is_solana_helium_reward_claim_context(event=event, raw_evidence=raw_evidence):
            return (
                "solana_helium_reward_context",
                "Solana-Raw-Evidence belegt Helium/HNT-IOT-MOBILE Claim-/Staking-Reward-Kontext auf eigener Wallet; nicht als ungeklärten CEX-/Fremdtransfer behandeln.",
            )
        if raw_evidence_ready:
            return (
                "raw_transaction_evidence_only",
                "Passende Deposit-/Withdrawal-History mit Adresse und TXID verknuepfen.",
            )
        return (
            "missing_source_evidence",
            "Quellimport/API-Beleg beschaffen oder Anfangsbestand dokumentieren.",
        )

    @staticmethod
    def _is_solana_tiny_raw_credit(
        *,
        event: CanonicalEvent | WalletFifoProvenanceEvent,
        raw_evidence: WalletFifoOriginRawEvidence | None,
    ) -> bool:
        raw_source = (raw_evidence.source if raw_evidence else event.source) or ""
        return (
            raw_source.strip().lower() == "solana_rpc"
            and event.source.strip().lower() == "solana_rpc"
            and event.asset.upper() == "SOL"
            and event.quantity > 0
            and abs(event.quantity) <= Decimal("0.00001")
        )

    @staticmethod
    def _is_solana_helium_reward_claim_context(
        *,
        event: CanonicalEvent | WalletFifoProvenanceEvent,
        raw_evidence: WalletFifoOriginRawEvidence | None,
    ) -> bool:
        raw_source = (raw_evidence.source if raw_evidence else event.source) or ""
        if (
            raw_source.strip().lower() != "solana_rpc"
            or event.source.strip().lower() != "solana_rpc"
            or event.asset.upper() not in {"HNT", "IOT", "MOBILE"}
            or event.quantity <= 0
        ):
            return False
        payload = raw_evidence.payload if raw_evidence else {}
        defi_label = str(payload.get("defi_label") or payload.get("defiLabel") or "").strip().lower()
        payload_text = json.dumps(payload, ensure_ascii=False, default=str).lower()
        helium_reward_instructions = (
            "claimrewardsv0",
            "setcurrentrewardswrapperv1",
            "setcurrentrewardsv0",
            "distributecompressionrewardsv0",
        )
        return defi_label in {"claim", "staking"} or any(
            instruction in payload_text for instruction in helium_reward_instructions
        )

    def _provenance_group_status_and_action(
        self,
        *,
        events_count: int,
        deposit_count: int,
        tx_count: int,
        raw_count: int,
        local_outflow_count: int,
        exchange_outflow_count: int,
        exchange_internal_context_count: int,
        withdrawal_ready_count: int,
    ) -> tuple[str, str]:
        if withdrawal_ready_count:
            return (
                "withdrawal_evidence_ready",
                "Withdrawal-API/History belegt lokalen Abgang mit Adresse/TXID; als Transferanker-Kandidat im Review pruefen.",
            )
        if exchange_internal_context_count and exchange_internal_context_count == exchange_outflow_count:
            return (
                "exchange_internal_context",
                "Zeit-/betragsnahe Exchange-Gegenbewegung ist interner Earn-/Fund-/Strategy-/Trading-Kontext; nicht als Blockchain-Withdrawal werten.",
            )
        if exchange_outflow_count:
            return (
                "exchange_outflow_candidate",
                "Zeit-/betragsnaher Exchange-Abgang gefunden; Withdrawal-History/API-Beleg mit Adresse und TXID vervollstaendigen.",
            )
        if local_outflow_count:
            return (
                "local_outflow_candidate",
                "Zeit-/betragsnaher lokaler Abgang gefunden; Onchain-/Service-Kontext fachlich pruefen.",
            )
        if deposit_count == events_count and tx_count == events_count:
            return (
                "deposit_evidence_ready",
                "Deposit-/TXID-Evidence vorhanden; Onchain-Gegenwallet pruefen und Transferanker fachlich ableiten.",
            )
        if raw_count:
            return (
                "raw_transaction_evidence_only",
                "Raw-Transaction-Evidence vorhanden; passende Deposit-/Withdrawal-History mit Adresse und TXID verknuepfen.",
            )
        return (
            "missing_source_evidence",
            "Quellimport/API-Beleg fuer diesen Zufluss beschaffen oder als Anfangsbestand dokumentieren.",
        )

    def _add_provenance_status_breakdown_item(
        self,
        *,
        items: dict[str, dict[str, object]],
        status: str,
        action: str,
        event: CanonicalEvent,
        trace: WalletFifoTransferTrace,
        best_outflow_candidate: WalletFifoProvenanceOutflowSummary | None,
    ) -> None:
        item = items.setdefault(
            status,
            {
                "evidence_status": status,
                "events_count": 0,
                "quantity_total": Decimal("0"),
                "carried_cost_basis_eur_total": Decimal("0"),
                "local_outflow_candidate_count": 0,
                "exchange_outflow_candidate_count": 0,
                "exchange_internal_context_count": 0,
                "withdrawal_evidence_ready_count": 0,
                "first_event_at": None,
                "last_event_at": None,
                "recommended_action": action,
                "best_outflow_candidate": None,
            },
        )
        item["events_count"] = int(item["events_count"]) + 1
        item["quantity_total"] = item["quantity_total"] + trace.quantity  # type: ignore[operator]
        item["carried_cost_basis_eur_total"] = item["carried_cost_basis_eur_total"] + trace.carried_cost_basis_eur  # type: ignore[operator]
        first = item["first_event_at"]
        last = item["last_event_at"]
        item["first_event_at"] = event.event_time if first is None or event.event_time < first else first
        item["last_event_at"] = event.event_time if last is None or event.event_time > last else last
        if best_outflow_candidate:
            item["local_outflow_candidate_count"] = int(item["local_outflow_candidate_count"]) + 1
            if best_outflow_candidate.evidence_category == "exchange_outflow_candidate":
                item["exchange_outflow_candidate_count"] = int(item["exchange_outflow_candidate_count"]) + 1
            if self._is_exchange_internal_context_status(best_outflow_candidate.exchange_evidence_status):
                item["exchange_internal_context_count"] = int(item["exchange_internal_context_count"]) + 1
            if best_outflow_candidate.withdrawal_evidence_status == "withdrawal_address_txid_ready":
                item["withdrawal_evidence_ready_count"] = int(item["withdrawal_evidence_ready_count"]) + 1
            current_best = item["best_outflow_candidate"]
            if current_best is None or self._provenance_outflow_rank(best_outflow_candidate) < self._provenance_outflow_rank(current_best):  # type: ignore[arg-type]
                item["best_outflow_candidate"] = best_outflow_candidate

    def _build_provenance_status_breakdown(
        self,
        items: dict[str, dict[str, object]],
    ) -> list[WalletFifoProvenanceStatusBreakdown]:
        breakdown = [
            WalletFifoProvenanceStatusBreakdown(
                evidence_status=str(item["evidence_status"]),
                events_count=int(item["events_count"]),
                quantity_total=item["quantity_total"],  # type: ignore[arg-type]
                carried_cost_basis_eur_total=item["carried_cost_basis_eur_total"],  # type: ignore[arg-type]
                local_outflow_candidate_count=int(item["local_outflow_candidate_count"]),
                exchange_outflow_candidate_count=int(item["exchange_outflow_candidate_count"]),
                exchange_internal_context_count=int(item["exchange_internal_context_count"]),
                withdrawal_evidence_ready_count=int(item["withdrawal_evidence_ready_count"]),
                first_event_at=item["first_event_at"],  # type: ignore[arg-type]
                last_event_at=item["last_event_at"],  # type: ignore[arg-type]
                recommended_action=str(item["recommended_action"]),
                best_outflow_candidate=item["best_outflow_candidate"],  # type: ignore[arg-type]
            )
            for item in items.values()
        ]
        breakdown.sort(
            key=lambda item: (
                self._provenance_status_order(item.evidence_status),
                -item.events_count,
                -abs(item.carried_cost_basis_eur_total),
            )
        )
        return breakdown

    def solana_origin_trace(
        self,
        year: int,
        *,
        asset: str = "JUP",
        pool_id: str = "binance:Spot",
        rpc_url: str = DEFAULT_SOLANA_RPC_URL,
        limit: int = 5,
        timeout_seconds: int = 20,
    ) -> WalletFifoSolanaOriginTraceReport:
        origin = self.origin_trace(year=year, asset=asset, pool_id=pool_id, limit=limit)
        traces: list[WalletFifoSolanaOriginTrace] = []
        with httpx.Client(timeout=max(3, min(timeout_seconds, 60))) as client:
            for trace in origin.traces[:limit]:
                if not trace.onchain_tx_id:
                    traces.append(
                        WalletFifoSolanaOriginTrace(
                            signature="",
                            status="missing_txid",
                            asset=trace.asset,
                            expected_amount=trace.candidate_event.quantity if trace.candidate_event else None,
                            deposit_address=trace.deposit_address,
                            known_wallets=sorted(self.KNOWN_OWN_SOLANA_WALLETS),
                            recommended_action="Keine TXID vorhanden; Binance Deposit-History pruefen.",
                            reason="origin_trace_without_txid",
                        )
                    )
                    continue
                traces.append(
                    self._fetch_solana_origin_trace(
                        client=client,
                        rpc_url=rpc_url,
                        signature=trace.onchain_tx_id,
                        asset=trace.asset,
                        expected_amount=trace.candidate_event.quantity if trace.candidate_event else None,
                        deposit_address=trace.deposit_address,
                    )
                )
        return WalletFifoSolanaOriginTraceReport(
            generated_at=datetime.now(timezone.utc),
            year=year,
            traces_count=len(traces),
            traces=traces,
            methodology=(
                "Read-only Solana-Origin-Trace fuer Binance-Deposit-TXIDs. "
                "Ruft getTransaction per Solana RPC ab, wertet Token-Balance-"
                "Deltas aus und klassifiziert Sender/Empfaenger gegen bekannte "
                "eigene Wallets. Es werden keine Imports, Lots oder Review-"
                "Entscheidungen geschrieben."
            ),
        )

    def solana_provenance_classification(
        self,
        year: int,
        *,
        asset: str = "SOL",
        pool_id: str | None = None,
        offset: int = 0,
        limit: int = 5,
        provider: str = "rpc_public",
        rpc_url: str = DEFAULT_SOLANA_RPC_URL,
        timeout_seconds: int = 20,
    ) -> WalletFifoSolanaProvenanceClassificationReport:
        event_report = self.provenance_events(
            year,
            asset=asset,
            pool_id=pool_id,
            offset=offset,
            limit=max(1, min(limit, 25)),
        )
        classifications: list[WalletFifoSolanaProvenanceClassification] = []
        normalized_provider = provider.strip().lower()
        if normalized_provider == "rpc_public":
            normalized_provider = "rpc"
        solscan_key = self._solscan_api_key() if normalized_provider == "solscan" else ""
        with httpx.Client(timeout=max(3, min(timeout_seconds, 60))) as client:
            for event in event_report.events:
                signature = event.onchain_tx_id or event.tx_id
                if not signature:
                    classifications.append(
                        self._solana_provenance_classification_error(
                            event=event,
                            signature="",
                            status="missing_txid",
                            reason="provenance_event_without_txid",
                        )
                    )
                    continue
                if normalized_provider == "solscan":
                    if not solscan_key:
                        classifications.append(
                            self._solana_provenance_classification_error(
                                event=event,
                                signature=signature,
                                status="failed",
                                reason="solscan_api_key_missing",
                                evidence_source="solscan",
                            )
                        )
                        continue
                    classifications.append(
                        self._fetch_solscan_provenance_classification(
                            client=client,
                            api_key=solscan_key,
                            event=event,
                        )
                    )
                else:
                    classifications.append(
                        self._fetch_solana_provenance_classification(
                            client=client,
                            rpc_url=rpc_url,
                            event=event,
                        )
                    )
        return WalletFifoSolanaProvenanceClassificationReport(
            generated_at=datetime.now(timezone.utc),
            year=year,
            asset=asset.upper(),
            pool_id=pool_id,
            offset=event_report.offset,
            limit=event_report.limit,
            requested_events_count=event_report.events_count,
            classified_count=len(classifications),
            own_transfer_candidates_count=sum(1 for item in classifications if item.status == "own_wallet_transfer_candidate"),
            external_or_unknown_count=sum(1 for item in classifications if item.status == "external_or_unknown_origin"),
            failed_count=sum(1 for item in classifications if item.status in {"failed", "not_found", "rate_limited", "missing_txid"}),
            classifications=classifications,
            methodology=(
                "Read-only Solana-Signaturklassifizierung fuer offene Wallet-FIFO-Zufluss-Herkunft. "
                "Standard ist provider=rpc_public ueber die freie Solana Public RPC; provider=solscan "
                "nutzt Solscan Pro transaction/actions, wenn der API-Level das erlaubt. RPC nutzt native pre/postBalances "
                "fuer SOL und Token-Balances fuer SPL-Token. "
                "Bekannte eigene Wallets werden nur markiert; es werden keine Transferanker, Imports "
                "oder Steuerdaten geschrieben."
            ),
        )

    def solana_provenance_batch_latest(
        self,
        year: int,
        *,
        asset: str = "SOL",
        output_dir: Path | None = None,
    ) -> WalletFifoSolanaProvenanceBatchLatest:
        artifact_path = (output_dir or self.DEFAULT_SOLANA_PROVENANCE_BATCH_DIR) / (
            f"latest_{year}_{asset.upper()}_provenance_classification.json"
        )
        methodology = (
            "Read-only Status des letzten Solana-Provenance-Batch-Artefakts. "
            "Der Batch klassifiziert bekannte TXIDs fuer offene Wallet-FIFO-Zufluesse "
            "und schreibt keine Imports, Transferanker, Tax-Lines oder Lots."
        )
        if not artifact_path.exists():
            return WalletFifoSolanaProvenanceBatchLatest(
                year=year,
                asset=asset.upper(),
                artifact_path=str(artifact_path),
                exists=False,
                methodology=methodology,
            )
        try:
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return WalletFifoSolanaProvenanceBatchLatest(
                year=year,
                asset=asset.upper(),
                artifact_path=str(artifact_path),
                exists=True,
                last_batch_status="read_failed",
                methodology=f"{methodology} Letztes Artefakt konnte nicht gelesen werden: {exc}",
            )
        total_events = int(payload.get("total_events") or 0)
        classified_count = int(payload.get("classified_count") or 0)
        batches = payload.get("batches") or []
        last_batch = batches[-1] if batches else {}
        progress_percent = Decimal("0")
        if total_events > 0:
            progress_percent = (Decimal(classified_count) / Decimal(total_events) * Decimal("100")).quantize(Decimal("0.01"))
        generated_at = None
        if payload.get("generated_at"):
            try:
                generated_at = datetime.fromisoformat(str(payload["generated_at"]))
            except ValueError:
                generated_at = None
        return WalletFifoSolanaProvenanceBatchLatest(
            generated_at=generated_at,
            year=int(payload.get("year") or year),
            asset=str(payload.get("asset") or asset).upper(),
            pool_id=payload.get("pool_id"),
            provider=payload.get("provider"),
            run_id=payload.get("run_id"),
            artifact_path=str(artifact_path),
            exists=True,
            total_events=total_events,
            classified_count=classified_count,
            remaining_count=max(0, total_events - classified_count),
            progress_percent=progress_percent,
            own_transfer_candidates_count=int(payload.get("own_transfer_candidates_count") or 0),
            external_or_unknown_count=int(payload.get("external_or_unknown_count") or 0),
            failed_count=int(payload.get("failed_count") or 0),
            batches_count=len(batches),
            last_batch_offset=last_batch.get("offset") if isinstance(last_batch.get("offset"), int) else None,
            last_batch_failed_count=(
                last_batch.get("failed_count") if isinstance(last_batch.get("failed_count"), int) else None
            ),
            last_batch_status=last_batch.get("status") if isinstance(last_batch.get("status"), str) else None,
            methodology=methodology,
        )

    def solana_raw_provenance_priorities(
        self,
        year: int,
        *,
        asset: str = "SOL",
        pool_id: str | None = None,
        limit: int = 50,
        output_dir: Path | None = None,
    ) -> WalletFifoSolanaRawProvenancePriorityReport:
        normalized_asset = asset.upper()
        event_report = self.provenance_events(
            year,
            asset=normalized_asset,
            pool_id=pool_id,
            limit=1000,
        )
        events = [
            event
            for event in event_report.events
            if event.evidence_status in {"raw_transaction_evidence_only", "solana_tiny_raw_credit"}
        ]
        artifact_path = (output_dir or self.DEFAULT_SOLANA_PROVENANCE_BATCH_DIR) / (
            f"latest_{year}_{normalized_asset}_provenance_classification.json"
        )
        classifications = self._solana_batch_classifications_by_event_id(artifact_path)
        raw_evidence_by_id = self._raw_evidence_map([event.raw_object_id for event in events])
        rows: list[WalletFifoSolanaRawProvenancePriority] = []
        for event in events:
            classification = classifications.get(event.event_id, {})
            raw_evidence = raw_evidence_by_id.get(event.raw_object_id or "")
            route_details = self._solana_raw_route_details(raw_evidence, event.account or "")
            origin_hint, evidence_needed = self._solana_raw_origin_hint(raw_evidence, route_details)
            route_classification = self._solana_raw_route_classification(origin_hint, route_details)
            evidence_priority = self._solana_raw_bmf_evidence_priority(
                route_classification=route_classification,
                evidence_status=event.evidence_status,
                carried_cost_basis_eur=event.carried_cost_basis_eur,
            )
            signature = str(classification.get("signature") or event.tx_id or "") or None
            classification_status = str(classification.get("status") or "") or None
            row = WalletFifoSolanaRawProvenancePriority(
                event_id=event.event_id,
                event_time=event.event_time,
                evidence_status=event.evidence_status,
                asset=event.asset.upper(),
                pool_id=event.pool_id,
                quantity=event.quantity,
                carried_cost_basis_eur=event.carried_cost_basis_eur,
                signature=signature,
                classification_status=classification_status,
                evidence_source=str(classification.get("evidence_source") or "") or None,
                sender_owner=str(classification.get("sender_owner") or "") or None,
                receiver_owner=str(classification.get("receiver_owner") or "") or None,
                matched_amount=self._decimal_from_json_value(classification.get("matched_amount")),
                wallet_delta_quantity=self._decimal_from_json_value(classification.get("wallet_delta_quantity")),
                origin_hint=origin_hint,
                evidence_needed=evidence_needed,
                wallet_is_signer=route_details.wallet_is_signer,
                signers=list(route_details.signers),
                program_ids=list(route_details.program_ids),
                primary_program=route_details.primary_program,
                route_classification=route_classification,
                bmf_evidence_priority=evidence_priority,
                evidence_checklist=self._solana_raw_evidence_checklist(route_classification, route_details),
                sender_is_known_own_wallet=bool(classification.get("sender_is_known_own_wallet")),
                receiver_is_known_own_wallet=bool(classification.get("receiver_is_known_own_wallet")),
                block_time=str(classification.get("block_time") or "") or None,
                classification_reason=str(classification.get("reason") or "") or None,
                recommended_action=self._solana_raw_provenance_priority_action(
                    event_status=event.evidence_status,
                    classification_status=classification_status,
                    sender_owner=str(classification.get("sender_owner") or "") or None,
                    receiver_owner=str(classification.get("receiver_owner") or "") or None,
                ),
            )
            rows.append(row)
        rows.sort(
            key=lambda row: (
                row.evidence_status == "solana_tiny_raw_credit",
                -abs(row.carried_cost_basis_eur),
                -abs(row.quantity),
                row.event_time,
            )
        )
        return WalletFifoSolanaRawProvenancePriorityReport(
            generated_at=datetime.now(timezone.utc),
            year=year,
            asset=normalized_asset,
            pool_id=pool_id,
            artifact_path=str(artifact_path),
            artifact_exists=artifact_path.exists(),
            events_count=len(events),
            priorities_count=min(len(rows), max(1, min(limit, 500))),
            raw_transaction_evidence_only_count=sum(1 for event in events if event.evidence_status == "raw_transaction_evidence_only"),
            solana_tiny_raw_credit_count=sum(1 for event in events if event.evidence_status == "solana_tiny_raw_credit"),
            total_quantity=sum((event.quantity for event in events), Decimal("0")),
            total_cost_basis_eur=sum((event.carried_cost_basis_eur for event in events), Decimal("0")),
            priorities=rows[: max(1, min(limit, 500))],
            methodology=(
                "Read-only Priorisierung der SOL-Raw-Provenance. Verknuepft offene "
                "raw_transaction_evidence_only/solana_tiny_raw_credit-Events mit dem "
                "letzten lokalen Solana-Provenance-Batch-Artefakt und sortiert nach "
                "Cost Basis. Es werden keine RPC-/Solscan-Live-Abfragen, Imports, Lots "
                "oder Steuerdaten geschrieben."
            ),
        )

    def solana_raw_provenance_sender_summary(
        self,
        year: int,
        *,
        asset: str = "SOL",
        pool_id: str | None = None,
        limit: int = 50,
    ) -> WalletFifoSolanaRawProvenanceSenderSummaryReport:
        priorities = self.solana_raw_provenance_priorities(
            year,
            asset=asset,
            pool_id=pool_id,
            limit=500,
        )
        grouped: dict[tuple[str, str | None, str | None], dict[str, object]] = {}
        for row in priorities.priorities:
            sender = row.sender_owner or "unknown_sender"
            key = (sender, row.receiver_owner, row.classification_status)
            item = grouped.setdefault(
                key,
                {
                    "rows": [],
                    "events_count": 0,
                    "raw_count": 0,
                    "tiny_count": 0,
                    "quantity_total": Decimal("0"),
                    "cost_total": Decimal("0"),
                    "sample_signatures": [],
                    "wallet_signed_events_count": 0,
                    "sample_signers": [],
                    "sample_program_ids": [],
                    "program_cost_by_id": defaultdict(Decimal),
                    "route_cost_by_classification": defaultdict(Decimal),
                    "priority_cost_by_level": defaultdict(Decimal),
                    "checklist_items": [],
                    "origin_cost_by_hint": defaultdict(Decimal),
                    "evidence_needed_by_hint": {},
                    "top": None,
                },
            )
            rows: list[WalletFifoSolanaRawProvenancePriority] = item["rows"]  # type: ignore[assignment]
            rows.append(row)
            item["events_count"] = int(item["events_count"]) + 1
            if row.evidence_status == "raw_transaction_evidence_only":
                item["raw_count"] = int(item["raw_count"]) + 1
            if row.evidence_status == "solana_tiny_raw_credit":
                item["tiny_count"] = int(item["tiny_count"]) + 1
            item["quantity_total"] = item["quantity_total"] + row.quantity  # type: ignore[operator]
            item["cost_total"] = item["cost_total"] + row.carried_cost_basis_eur  # type: ignore[operator]
            sample_signatures: list[str] = item["sample_signatures"]  # type: ignore[assignment]
            if row.signature and len(sample_signatures) < 5:
                sample_signatures.append(row.signature)
            if row.wallet_is_signer:
                item["wallet_signed_events_count"] = int(item["wallet_signed_events_count"]) + 1
            sample_signers: list[str] = item["sample_signers"]  # type: ignore[assignment]
            for signer in row.signers:
                if signer not in sample_signers and len(sample_signers) < 5:
                    sample_signers.append(signer)
            sample_program_ids: list[str] = item["sample_program_ids"]  # type: ignore[assignment]
            for program_id in row.program_ids:
                if program_id not in sample_program_ids and len(sample_program_ids) < 6:
                    sample_program_ids.append(program_id)
            if row.primary_program:
                program_cost_by_id: defaultdict[str, Decimal] = item["program_cost_by_id"]  # type: ignore[assignment]
                program_cost_by_id[row.primary_program] += abs(row.carried_cost_basis_eur)
            route_key = row.route_classification or "unknown_route"
            route_cost_by_classification: defaultdict[str, Decimal] = item["route_cost_by_classification"]  # type: ignore[assignment]
            route_cost_by_classification[route_key] += abs(row.carried_cost_basis_eur)
            priority_cost_by_level: defaultdict[str, Decimal] = item["priority_cost_by_level"]  # type: ignore[assignment]
            priority_cost_by_level[row.bmf_evidence_priority] += abs(row.carried_cost_basis_eur)
            checklist_items: list[str] = item["checklist_items"]  # type: ignore[assignment]
            for checklist_item in row.evidence_checklist:
                if checklist_item not in checklist_items and len(checklist_items) < 8:
                    checklist_items.append(checklist_item)
            origin_hint = row.origin_hint or "unknown"
            origin_cost_by_hint: defaultdict[str, Decimal] = item["origin_cost_by_hint"]  # type: ignore[assignment]
            origin_cost_by_hint[origin_hint] += abs(row.carried_cost_basis_eur)
            evidence_needed_by_hint: dict[str, str] = item["evidence_needed_by_hint"]  # type: ignore[assignment]
            if row.evidence_needed and origin_hint not in evidence_needed_by_hint:
                evidence_needed_by_hint[origin_hint] = row.evidence_needed
            top = item["top"]
            if top is None or abs(row.carried_cost_basis_eur) > abs(top.carried_cost_basis_eur):  # type: ignore[union-attr]
                item["top"] = row

        summaries: list[WalletFifoSolanaRawProvenanceSenderSummary] = []
        for (sender, receiver, classification_status), item in grouped.items():
            rows: list[WalletFifoSolanaRawProvenancePriority] = item["rows"]  # type: ignore[assignment]
            rows.sort(key=lambda row: row.event_time)
            top: WalletFifoSolanaRawProvenancePriority | None = item["top"]  # type: ignore[assignment]
            origin_cost_by_hint: defaultdict[str, Decimal] = item["origin_cost_by_hint"]  # type: ignore[assignment]
            origin_hint = max(origin_cost_by_hint, key=lambda key: origin_cost_by_hint[key]) if origin_cost_by_hint else None
            evidence_needed_by_hint: dict[str, str] = item["evidence_needed_by_hint"]  # type: ignore[assignment]
            program_cost_by_id: defaultdict[str, Decimal] = item["program_cost_by_id"]  # type: ignore[assignment]
            primary_program = (
                max(program_cost_by_id, key=lambda key: program_cost_by_id[key]) if program_cost_by_id else None
            )
            route_cost_by_classification: defaultdict[str, Decimal] = item["route_cost_by_classification"]  # type: ignore[assignment]
            route_classification = (
                max(route_cost_by_classification, key=lambda key: route_cost_by_classification[key])
                if route_cost_by_classification
                else None
            )
            priority_cost_by_level: defaultdict[str, Decimal] = item["priority_cost_by_level"]  # type: ignore[assignment]
            priority_order = {"high": 3, "medium": 2, "low": 1}
            bmf_evidence_priority = (
                max(priority_cost_by_level, key=lambda key: (priority_order.get(key, 0), priority_cost_by_level[key]))
                if priority_cost_by_level
                else "medium"
            )
            summaries.append(
                WalletFifoSolanaRawProvenanceSenderSummary(
                    sender_owner=sender,
                    receiver_owner=receiver,
                    classification_status=classification_status,
                    events_count=int(item["events_count"]),
                    raw_transaction_evidence_only_count=int(item["raw_count"]),
                    solana_tiny_raw_credit_count=int(item["tiny_count"]),
                    quantity_total=item["quantity_total"],  # type: ignore[arg-type]
                    carried_cost_basis_eur_total=item["cost_total"],  # type: ignore[arg-type]
                    first_event_at=rows[0].event_time if rows else None,
                    last_event_at=rows[-1].event_time if rows else None,
                    top_signature=top.signature if top else None,
                    top_quantity=top.quantity if top else None,
                    top_cost_basis_eur=top.carried_cost_basis_eur if top else None,
                    origin_hint=origin_hint,
                    evidence_needed=evidence_needed_by_hint.get(origin_hint or ""),
                    sample_signatures=item["sample_signatures"],  # type: ignore[arg-type]
                    wallet_signed_events_count=int(item["wallet_signed_events_count"]),
                    sample_signers=item["sample_signers"],  # type: ignore[arg-type]
                    sample_program_ids=item["sample_program_ids"],  # type: ignore[arg-type]
                    primary_program=primary_program,
                    route_classification=route_classification,
                    bmf_evidence_priority=bmf_evidence_priority,
                    evidence_checklist=item["checklist_items"],  # type: ignore[arg-type]
                    recommended_action=self._solana_sender_summary_action(
                        sender=sender,
                        receiver=receiver,
                        classification_status=classification_status,
                        raw_count=int(item["raw_count"]),
                        tiny_count=int(item["tiny_count"]),
                    ),
                )
            )
        summaries.sort(
            key=lambda item: (
                -abs(item.carried_cost_basis_eur_total),
                -abs(item.quantity_total),
                item.sender_owner,
            )
        )
        return WalletFifoSolanaRawProvenanceSenderSummaryReport(
            generated_at=datetime.now(timezone.utc),
            year=year,
            asset=asset.upper(),
            pool_id=pool_id,
            senders_count=len(summaries),
            events_count=priorities.events_count,
            raw_transaction_evidence_only_count=priorities.raw_transaction_evidence_only_count,
            solana_tiny_raw_credit_count=priorities.solana_tiny_raw_credit_count,
            total_quantity=priorities.total_quantity,
            total_cost_basis_eur=priorities.total_cost_basis_eur,
            senders=summaries[: max(1, min(limit, 500))],
            methodology=(
                "Read-only Sender-Zusammenfassung der Solana-Raw-Provenance-Prioritaeten. "
                "Gruppiert das lokale Batch-Ergebnis nach Sender, Empfaenger und Status, "
                "sortiert nach Cost Basis und schreibt keine Imports, Transferanker, Lots "
                "oder Steuerdaten."
            ),
        )

    def solana_raw_bmf_evidence_summary(
        self,
        year: int,
        *,
        asset: str = "SOL",
        pool_id: str | None = None,
        limit: int = 50,
    ) -> WalletFifoSolanaRawBmfEvidenceSummaryReport:
        priorities = self.solana_raw_provenance_priorities(
            year,
            asset=asset,
            pool_id=pool_id,
            limit=500,
        )
        grouped: dict[tuple[str, str], dict[str, object]] = {}
        for row in priorities.priorities:
            route = row.route_classification or "unknown_route"
            priority = row.bmf_evidence_priority or "medium"
            key = (route, priority)
            item = grouped.setdefault(
                key,
                {
                    "events_count": 0,
                    "raw_count": 0,
                    "tiny_count": 0,
                    "quantity_total": Decimal("0"),
                    "cost_total": Decimal("0"),
                    "wallet_signed_events_count": 0,
                    "senders": set(),
                    "primary_programs": [],
                    "sample_senders": [],
                    "sample_signatures": [],
                    "checklist_items": [],
                },
            )
            item["events_count"] = int(item["events_count"]) + 1
            if row.evidence_status == "raw_transaction_evidence_only":
                item["raw_count"] = int(item["raw_count"]) + 1
            if row.evidence_status == "solana_tiny_raw_credit":
                item["tiny_count"] = int(item["tiny_count"]) + 1
            item["quantity_total"] = item["quantity_total"] + row.quantity  # type: ignore[operator]
            item["cost_total"] = item["cost_total"] + row.carried_cost_basis_eur  # type: ignore[operator]
            if row.wallet_is_signer:
                item["wallet_signed_events_count"] = int(item["wallet_signed_events_count"]) + 1
            senders: set[str] = item["senders"]  # type: ignore[assignment]
            if row.sender_owner:
                senders.add(row.sender_owner)
            sample_senders: list[str] = item["sample_senders"]  # type: ignore[assignment]
            if row.sender_owner and row.sender_owner not in sample_senders and len(sample_senders) < 6:
                sample_senders.append(row.sender_owner)
            primary_programs: list[str] = item["primary_programs"]  # type: ignore[assignment]
            if row.primary_program and row.primary_program not in primary_programs and len(primary_programs) < 6:
                primary_programs.append(row.primary_program)
            sample_signatures: list[str] = item["sample_signatures"]  # type: ignore[assignment]
            if row.signature and row.signature not in sample_signatures and len(sample_signatures) < 6:
                sample_signatures.append(row.signature)
            checklist_items: list[str] = item["checklist_items"]  # type: ignore[assignment]
            for checklist_item in row.evidence_checklist:
                if checklist_item not in checklist_items and len(checklist_items) < 10:
                    checklist_items.append(checklist_item)

        groups: list[WalletFifoSolanaRawBmfEvidenceGroup] = []
        for (route, priority), item in grouped.items():
            groups.append(
                WalletFifoSolanaRawBmfEvidenceGroup(
                    route_classification=route,
                    bmf_evidence_priority=priority,
                    events_count=int(item["events_count"]),
                    senders_count=len(item["senders"]),  # type: ignore[arg-type]
                    raw_transaction_evidence_only_count=int(item["raw_count"]),
                    solana_tiny_raw_credit_count=int(item["tiny_count"]),
                    quantity_total=item["quantity_total"],  # type: ignore[arg-type]
                    carried_cost_basis_eur_total=item["cost_total"],  # type: ignore[arg-type]
                    wallet_signed_events_count=int(item["wallet_signed_events_count"]),
                    primary_programs=item["primary_programs"],  # type: ignore[arg-type]
                    sample_senders=item["sample_senders"],  # type: ignore[arg-type]
                    sample_signatures=item["sample_signatures"],  # type: ignore[arg-type]
                    evidence_checklist=item["checklist_items"],  # type: ignore[arg-type]
                    recommended_action=self._solana_raw_bmf_group_action(route, priority),
                )
            )
        priority_order = {"high": 3, "medium": 2, "low": 1}
        groups.sort(
            key=lambda group: (
                -priority_order.get(group.bmf_evidence_priority, 0),
                -abs(group.carried_cost_basis_eur_total),
                group.route_classification,
            )
        )
        high_priority_groups = [group for group in groups if group.bmf_evidence_priority == "high"]
        return WalletFifoSolanaRawBmfEvidenceSummaryReport(
            generated_at=datetime.now(timezone.utc),
            year=year,
            asset=asset.upper(),
            pool_id=pool_id,
            groups_count=len(groups),
            high_priority_events_count=sum(group.events_count for group in high_priority_groups),
            high_priority_cost_basis_eur=sum(
                (group.carried_cost_basis_eur_total for group in high_priority_groups),
                Decimal("0"),
            ),
            total_quantity=priorities.total_quantity,
            total_cost_basis_eur=priorities.total_cost_basis_eur,
            groups=groups[: max(1, min(limit, 100))],
            methodology=(
                "Read-only BMF-Beleguebersicht aus Solana-Raw-Provenance-Prioritaeten. "
                "Aggregiert Route und Prioritaet aus lokalen Raw-Belegen, Signern und "
                "Programmen. Es werden keine Canonical Events, Lots, Tax-Lines, Preise, "
                "Imports oder Review-Entscheidungen veraendert."
            ),
        )

    @staticmethod
    def _solana_raw_bmf_group_action(route_classification: str, bmf_evidence_priority: str) -> str:
        prefix = "Hohe Prioritaet: " if bmf_evidence_priority == "high" else ""
        if route_classification == "program_service_route":
            return (
                f"{prefix}Programm-/Service-Route mit externem Signer belegen; "
                "gegen Boersen-, Perp-, Service- oder Swap-Historie abgleichen und nicht automatisch als externen Zufluss werten."
            )
        if route_classification == "wallet_signed_route":
            return f"{prefix}Wallet-signierte Route als eigenen Swap/Trade mit Input-/Output-Asset und EUR-Wert belegen."
        if route_classification == "native_transfer_route":
            return f"{prefix}Native SOL-Transfers gegen Eigenwallet, Boerse oder Service-Auszahlung belegen."
        return f"{prefix}Unbekannte Route manuell anhand Signatur, Sender und moeglichem Anfangsbestand klaeren."

    def solana_raw_bmf_evidence_drilldown(
        self,
        year: int,
        *,
        asset: str = "SOL",
        pool_id: str | None = None,
        route_classification: str | None = "program_service_route",
        bmf_evidence_priority: str | None = "high",
        limit: int = 50,
    ) -> WalletFifoSolanaRawBmfEvidenceDrilldownReport:
        priorities = self.solana_raw_provenance_priorities(
            year,
            asset=asset,
            pool_id=pool_id,
            limit=500,
        )
        rows = priorities.priorities
        if route_classification:
            rows = [row for row in rows if row.route_classification == route_classification]
        if bmf_evidence_priority:
            rows = [row for row in rows if row.bmf_evidence_priority == bmf_evidence_priority]
        rows.sort(key=lambda row: (-abs(row.carried_cost_basis_eur), row.event_time, row.event_id))

        events: list[WalletFifoSolanaRawBmfEvidenceDrilldownEvent] = []
        grouped: dict[tuple[str, str | None, str, str], dict[str, object]] = {}
        for row in rows[: max(1, min(limit, 200))]:
            primary_signer = row.signers[0] if row.signers else "unknown_signer"
            decision_suggestion, decision_reason = self._solana_raw_bmf_decision_suggestion(row)
            events.append(
                WalletFifoSolanaRawBmfEvidenceDrilldownEvent(
                    event_id=row.event_id,
                    event_time=row.event_time,
                    asset=row.asset,
                    pool_id=row.pool_id,
                    quantity=row.quantity,
                    carried_cost_basis_eur=row.carried_cost_basis_eur,
                    signature=row.signature,
                    sender_owner=row.sender_owner,
                    receiver_owner=row.receiver_owner,
                    wallet_is_signer=row.wallet_is_signer,
                    signers=row.signers,
                    primary_signer=primary_signer,
                    primary_program=row.primary_program,
                    program_ids=row.program_ids,
                    route_classification=row.route_classification or "unknown_route",
                    bmf_evidence_priority=row.bmf_evidence_priority,
                    evidence_needed=row.evidence_needed,
                    evidence_checklist=row.evidence_checklist,
                    decision_suggestion=decision_suggestion,
                    decision_reason=decision_reason,
                )
            )
            key = (
                primary_signer,
                row.primary_program,
                row.route_classification or "unknown_route",
                row.bmf_evidence_priority,
            )
            item = grouped.setdefault(
                key,
                {
                    "events_count": 0,
                    "quantity_total": Decimal("0"),
                    "cost_total": Decimal("0"),
                    "first_event_at": None,
                    "last_event_at": None,
                    "sample_senders": [],
                    "sample_signatures": [],
                    "checklist_items": [],
                    "decision_suggestion": decision_suggestion,
                },
            )
            item["events_count"] = int(item["events_count"]) + 1
            item["quantity_total"] = item["quantity_total"] + row.quantity  # type: ignore[operator]
            item["cost_total"] = item["cost_total"] + row.carried_cost_basis_eur  # type: ignore[operator]
            first_event_at = item["first_event_at"]
            last_event_at = item["last_event_at"]
            if first_event_at is None or row.event_time < first_event_at:  # type: ignore[operator]
                item["first_event_at"] = row.event_time
            if last_event_at is None or row.event_time > last_event_at:  # type: ignore[operator]
                item["last_event_at"] = row.event_time
            sample_senders: list[str] = item["sample_senders"]  # type: ignore[assignment]
            if row.sender_owner and row.sender_owner not in sample_senders and len(sample_senders) < 5:
                sample_senders.append(row.sender_owner)
            sample_signatures: list[str] = item["sample_signatures"]  # type: ignore[assignment]
            if row.signature and row.signature not in sample_signatures and len(sample_signatures) < 5:
                sample_signatures.append(row.signature)
            checklist_items: list[str] = item["checklist_items"]  # type: ignore[assignment]
            for checklist_item in row.evidence_checklist:
                if checklist_item not in checklist_items and len(checklist_items) < 10:
                    checklist_items.append(checklist_item)

        signer_groups: list[WalletFifoSolanaRawBmfEvidenceSignerGroup] = []
        for (primary_signer, primary_program, route, priority), item in grouped.items():
            signer_groups.append(
                WalletFifoSolanaRawBmfEvidenceSignerGroup(
                    primary_signer=primary_signer,
                    primary_program=primary_program,
                    route_classification=route,
                    bmf_evidence_priority=priority,
                    events_count=int(item["events_count"]),
                    quantity_total=item["quantity_total"],  # type: ignore[arg-type]
                    carried_cost_basis_eur_total=item["cost_total"],  # type: ignore[arg-type]
                    first_event_at=item["first_event_at"],  # type: ignore[arg-type]
                    last_event_at=item["last_event_at"],  # type: ignore[arg-type]
                    sample_senders=item["sample_senders"],  # type: ignore[arg-type]
                    sample_signatures=item["sample_signatures"],  # type: ignore[arg-type]
                    decision_suggestion=str(item["decision_suggestion"]),
                    evidence_checklist=item["checklist_items"],  # type: ignore[arg-type]
                )
            )
        signer_groups.sort(
            key=lambda group: (
                -abs(group.carried_cost_basis_eur_total),
                group.primary_signer,
                group.primary_program or "",
            )
        )
        return WalletFifoSolanaRawBmfEvidenceDrilldownReport(
            generated_at=datetime.now(timezone.utc),
            year=year,
            asset=asset.upper(),
            pool_id=pool_id,
            route_filter=route_classification,
            priority_filter=bmf_evidence_priority,
            events_count=len(events),
            groups_count=len(signer_groups),
            total_quantity=sum((event.quantity for event in events), Decimal("0")),
            total_cost_basis_eur=sum((event.carried_cost_basis_eur for event in events), Decimal("0")),
            signer_groups=signer_groups,
            events=events,
            methodology=(
                "Read-only Drilldown fuer Solana-BMF-Belege. Filtert bestehende "
                "Raw-Provenance-Prioritaeten nach Route/Prioritaet, gruppiert nach "
                "Signer und Programm und erzeugt nur Entscheidungsvorschlaege. Keine "
                "Canonical Events, Lots, Tax-Lines, Preise, Imports oder Review-Entscheidungen werden veraendert."
            ),
        )

    @staticmethod
    def _solana_raw_bmf_decision_suggestion(
        row: WalletFifoSolanaRawProvenancePriority,
    ) -> tuple[str, str]:
        if row.route_classification == "program_service_route" and not row.wallet_is_signer:
            return (
                "service_program_route_not_income",
                "Programm-/Service-Kontext mit externem Signer; erst Service-, Perp-, Swap- oder Boersenbeleg zuordnen, nicht automatisch als Einkommen oder externen Zufluss behandeln.",
            )
        if row.route_classification == "wallet_signed_route":
            return (
                "own_trade_needs_swap_legs",
                "Main-Wallet hat signiert; Input-/Output-Legs und EUR-Wert zum Zeitpunkt als eigener Swap/Trade belegen.",
            )
        if row.route_classification == "native_transfer_route":
            return (
                "exchange_or_wallet_transfer_candidate",
                "Nativer Transfer; Sender/Empfaenger gegen Eigenwallet, Deposit-Adresse oder Exchange-Log matchen.",
            )
        return (
            "external_inflow_needs_evidence",
            "Route unbekannt; Signatur, Sender und moeglichen Anfangsbestand fachlich belegen.",
        )

    @staticmethod
    def _solana_sender_summary_action(
        *,
        sender: str,
        receiver: str | None,
        classification_status: str | None,
        raw_count: int,
        tiny_count: int,
    ) -> str:
        if raw_count == 0 and tiny_count:
            return "Nur Tiny-SOL/Dust von diesem Sender; gebuendelt dokumentieren."
        if classification_status == "external_or_unknown_origin":
            return (
                f"Sender {sender} -> {receiver or '-'} als externe/unklare Herkunft klaeren: "
                "Boerse/Service-Auszahlung, DEX-/Programmfluss, Anfangsbestand oder echter externer Zufluss."
            )
        if classification_status == "own_wallet_transfer_candidate":
            return "Als Eigenwallet-Transferanker-Kandidat fachlich pruefen."
        return "Sender-Gruppe mit Signaturbelegen pruefen und Herkunftskategorie setzen."

    @staticmethod
    def _solana_raw_origin_hint(
        raw_evidence: WalletFifoOriginRawEvidence | None,
        route_details: _SolanaRawRouteDetails | None = None,
    ) -> tuple[str, str]:
        payload = raw_evidence.payload if raw_evidence else {}
        defi_label = str(payload.get("defi_label") or "").strip().lower()
        event_type = str(payload.get("event_type") or "").strip().lower()
        raw_row = str(payload.get("raw_row") or "")
        if "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4" in raw_row or defi_label == "swap":
            if route_details and not route_details.wallet_is_signer:
                return (
                    "solana_jupiter_or_swap_route",
                    "Swap-/Route-Kontext vorhanden, aber Main-Wallet ist nicht Signer; Route-/Service-/Programmkontext belegen, bevor der Vorgang als eigener Wallet-Trade behandelt wird.",
                )
            return (
                "solana_jupiter_or_swap_route",
                "Swap-/Route-Beleg mit Input- und Output-Asset pruefen; bei Wallet-signiertem Swap als Tausch/Trade-Herkunft statt externem Zufluss dokumentieren.",
            )
        if "PERPHjGBqRHArX4DySjwM6UJHiR3sWAatqfdBS2qQJu" in raw_row or "perp" in raw_row.lower():
            if route_details and not route_details.wallet_is_signer:
                return (
                    "solana_perp_or_dex_program_context",
                    "Perp-/DEX-Programmkontext vorhanden, aber Main-Wallet ist nicht Signer; Funding/CloseAccount/Service-Kontext belegen und von echter externer Einzahlung trennen.",
                )
            return (
                "solana_perp_or_dex_program_context",
                "Perp-/DEX-Programmkontext pruefen; Funding/CloseAccount/Programmfluss von echter externer Einzahlung trennen.",
            )
        if event_type == "sol_transfer":
            return (
                "solana_native_transfer",
                "Native SOL-Transfer gegen bekannte Quelle, Boerse oder Eigenwallet belegen.",
            )
        return (
            "external_or_unknown_sender",
            "Senderadresse fachlich identifizieren und mit Import-/Börsen-/Service-Beleg verknuepfen.",
        )

    @staticmethod
    def _solana_raw_route_classification(
        origin_hint: str | None,
        route_details: _SolanaRawRouteDetails,
    ) -> str:
        if route_details.wallet_is_signer:
            return "wallet_signed_route"
        if origin_hint in {"solana_jupiter_or_swap_route", "solana_perp_or_dex_program_context"}:
            return "program_service_route"
        if origin_hint == "solana_native_transfer":
            return "native_transfer_route"
        return "unknown_route"

    @staticmethod
    def _solana_raw_bmf_evidence_priority(
        *,
        route_classification: str,
        evidence_status: str,
        carried_cost_basis_eur: Decimal,
    ) -> str:
        if evidence_status == "solana_tiny_raw_credit":
            return "low"
        if abs(carried_cost_basis_eur) >= Decimal("1000"):
            return "high"
        if route_classification in {"program_service_route", "unknown_route"}:
            return "medium"
        return "low"

    @staticmethod
    def _solana_raw_evidence_checklist(
        route_classification: str,
        route_details: _SolanaRawRouteDetails,
    ) -> list[str]:
        if route_classification == "wallet_signed_route":
            return [
                "Input-/Output-Asset aus Signatur belegen",
                "EUR-Wert zum Ausfuehrungszeitpunkt pruefen",
                "Als eigenen Swap/Trade gegen FIFO-Lot verknuepfen",
            ]
        if route_classification == "program_service_route":
            checklist = [
                "Externen Signer/Service identifizieren",
                "Programmroute dokumentieren",
                "Nicht automatisch als eigenen Wallet-Trade werten",
                "Gegen Boersen-/Service-/Perp-Historie abgleichen",
            ]
            if route_details.primary_program:
                checklist.append(f"Programm {route_details.primary_program} als Beleganker nutzen")
            return checklist
        if route_classification == "native_transfer_route":
            return [
                "Senderadresse identifizieren",
                "Eigenwallet, Boerse oder Service-Beleg zuordnen",
                "Transferanker statt externem Zufluss pruefen",
            ]
        return [
            "Sender und Signatur manuell pruefen",
            "Quelle/Anfangsbestand/externer Zufluss fachlich entscheiden",
            "Beleg im Jahrespaket dokumentieren",
        ]

    @classmethod
    def _solana_raw_route_details(
        cls,
        raw_evidence: WalletFifoOriginRawEvidence | None,
        wallet_address: str,
    ) -> _SolanaRawRouteDetails:
        payload = raw_evidence.payload if raw_evidence else {}
        raw_row = payload.get("raw_row")
        parsed = cls._parse_solana_raw_row(raw_row)
        if not parsed:
            raw_program = str(payload.get("programId") or payload.get("program_id") or "").strip()
            raw_programs = (raw_program,) if raw_program else ()
            return _SolanaRawRouteDetails(program_ids=raw_programs, primary_program=cls._primary_solana_program(raw_programs))

        message = parsed.get("transaction", {}).get("message", {}) if isinstance(parsed.get("transaction"), dict) else {}
        signers: list[str] = []
        account_keys = message.get("accountKeys") if isinstance(message, dict) else None
        if isinstance(account_keys, list):
            for key in account_keys:
                if isinstance(key, dict) and key.get("signer") is True and key.get("pubkey"):
                    signers.append(str(key["pubkey"]))
                elif isinstance(key, str):
                    continue

        program_ids: list[str] = []
        if isinstance(message, dict):
            cls._collect_solana_program_ids(message.get("instructions"), program_ids)
        meta = parsed.get("meta")
        if isinstance(meta, dict):
            inner = meta.get("innerInstructions")
            if isinstance(inner, list):
                for group in inner:
                    if isinstance(group, dict):
                        cls._collect_solana_program_ids(group.get("instructions"), program_ids)

        deduped_signers = tuple(dict.fromkeys(signers))
        deduped_programs = tuple(dict.fromkeys(program_ids))
        return _SolanaRawRouteDetails(
            wallet_is_signer=bool(wallet_address and wallet_address in deduped_signers),
            signers=deduped_signers,
            program_ids=deduped_programs,
            primary_program=cls._primary_solana_program(deduped_programs),
        )

    @staticmethod
    def _parse_solana_raw_row(raw_row: object) -> dict[str, object]:
        if isinstance(raw_row, dict):
            return raw_row
        if not isinstance(raw_row, str):
            return {}
        text = raw_row.strip()
        if not text:
            return {}
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(text)
            except Exception:
                continue
            if isinstance(parsed, dict):
                return parsed
        return {}

    @staticmethod
    def _collect_solana_program_ids(instructions: object, target: list[str]) -> None:
        if not isinstance(instructions, list):
            return
        for instruction in instructions:
            if not isinstance(instruction, dict):
                continue
            program_id = instruction.get("programId") or instruction.get("program_id")
            if program_id:
                target.append(str(program_id))

    @staticmethod
    def _primary_solana_program(program_ids: tuple[str, ...]) -> str | None:
        preferred = (
            "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
            "PERPHjGBqRHArX4DySjwM6UJHiR3sWAatqfdBS2qQJu",
        )
        for program_id in preferred:
            if program_id in program_ids:
                return program_id
        ignored = {
            "ComputeBudget111111111111111111111111111111",
            "11111111111111111111111111111111",
            "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
            "ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL",
        }
        for program_id in program_ids:
            if program_id not in ignored:
                return program_id
        return program_ids[0] if program_ids else None

    @staticmethod
    def _solana_batch_classifications_by_event_id(artifact_path: Path) -> dict[str, dict[str, object]]:
        try:
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        classifications = payload.get("classifications")
        if not isinstance(classifications, list):
            return {}
        result: dict[str, dict[str, object]] = {}
        for item in classifications:
            if isinstance(item, dict) and item.get("event_id"):
                result[str(item["event_id"])] = item
        return result

    @staticmethod
    def _decimal_from_json_value(value: object) -> Decimal | None:
        if value is None or value == "":
            return None
        try:
            return Decimal(str(value))
        except Exception:
            return None

    @staticmethod
    def _solana_raw_provenance_priority_action(
        *,
        event_status: str,
        classification_status: str | None,
        sender_owner: str | None,
        receiver_owner: str | None,
    ) -> str:
        if event_status == "solana_tiny_raw_credit":
            return "Tiny-SOL als Dust/Rent/Programmkontext dokumentieren; nur bei Auffaelligkeit einzeln pruefen."
        if classification_status == "own_wallet_transfer_candidate":
            return "Batch erkennt bekannte eigene Wallets; als Transferanker-Kandidat fachlich pruefen."
        if classification_status == "external_or_unknown_origin":
            return (
                "Batch erkennt externen/unklaren Sender "
                f"{sender_owner or '-'} -> {receiver_owner or '-'}; Herkunft belegen oder als externen Zufluss/Anfangsbestand klaeren."
            )
        if classification_status:
            return f"Batch-Status {classification_status}; Signaturbeleg gezielt erneut pruefen."
        return "Keine Batch-Klassifizierung gefunden; Signatur gezielt per Solscan/RPC pruefen."

    def solana_sender_clusters(
        self,
        year: int,
        *,
        asset: str = "SOL",
        limit: int = 50,
        output_dir: Path | None = None,
    ) -> WalletFifoSolanaSenderClusterReport:
        artifact_path = (output_dir or self.DEFAULT_SOLANA_PROVENANCE_BATCH_DIR) / (
            f"latest_{year}_{asset.upper()}_provenance_classification.json"
        )
        methodology = (
            "Read-only Sender-Clustering aus dem letzten Solana-Provenance-Batch-Artefakt. "
            "Gruppiert klassifizierte TXIDs nach Senderadresse, summiert Mengen und markiert "
            "nur bekannte eigene Sender/Empfaenger als Transferkandidaten. Es werden keine "
            "Transferanker, Imports, Lots oder Tax-Lines geschrieben."
        )
        if not artifact_path.exists():
            return WalletFifoSolanaSenderClusterReport(
                generated_at=datetime.now(timezone.utc),
                year=year,
                asset=asset.upper(),
                artifact_path=str(artifact_path),
                artifact_exists=False,
                methodology=methodology,
            )
        try:
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return WalletFifoSolanaSenderClusterReport(
                generated_at=datetime.now(timezone.utc),
                year=year,
                asset=asset.upper(),
                artifact_path=str(artifact_path),
                artifact_exists=True,
                methodology=f"{methodology} Letztes Artefakt konnte nicht gelesen werden: {exc}",
            )
        groups: dict[str, dict[str, object]] = {}
        failed_statuses = {"failed", "not_found", "rate_limited", "missing_txid"}
        classifications = payload.get("classifications") if isinstance(payload.get("classifications"), list) else []
        for item in classifications:
            if not isinstance(item, dict):
                continue
            sender = str(item.get("sender_owner") or "unknown_sender")
            group = groups.setdefault(
                sender,
                {
                    "sender_owner": sender,
                    "receiver_owner": item.get("receiver_owner"),
                    "events_count": 0,
                    "expected_amount_total": Decimal("0"),
                    "matched_amount_total": Decimal("0"),
                    "first_block_time": None,
                    "last_block_time": None,
                    "own_wallet_sender": False,
                    "own_wallet_receiver": False,
                    "own_events": 0,
                    "failed_events": 0,
                    "samples": [],
                    "signatures": [],
                },
            )
            group["events_count"] = int(group["events_count"]) + 1
            expected = self._decimal_from_any(item.get("expected_amount"))
            matched = self._decimal_from_any(item.get("matched_amount"))
            group["expected_amount_total"] = group["expected_amount_total"] + expected  # type: ignore[operator]
            group["matched_amount_total"] = group["matched_amount_total"] + matched  # type: ignore[operator]
            block_time = str(item.get("block_time") or "") or None
            if block_time:
                first = group.get("first_block_time")
                last = group.get("last_block_time")
                group["first_block_time"] = block_time if not first or block_time < str(first) else first
                group["last_block_time"] = block_time if not last or block_time > str(last) else last
            if bool(item.get("sender_is_known_own_wallet")):
                group["own_wallet_sender"] = True
            if bool(item.get("receiver_is_known_own_wallet")):
                group["own_wallet_receiver"] = True
            if item.get("status") == "own_wallet_transfer_candidate":
                group["own_events"] = int(group["own_events"]) + 1
            if item.get("status") in failed_statuses:
                group["failed_events"] = int(group["failed_events"]) + 1
            samples = group["samples"]
            if isinstance(samples, list) and len(samples) < 5:
                samples.append(
                    WalletFifoSolanaSenderClusterSample(
                        event_id=str(item.get("event_id") or ""),
                        signature=str(item.get("signature") or ""),
                        block_time=block_time,
                        expected_amount=expected,
                        matched_amount=matched if item.get("matched_amount") is not None else None,
                        reason=str(item.get("reason")) if item.get("reason") else None,
                    )
                )
            signatures = group["signatures"]
            if isinstance(signatures, list) and item.get("signature"):
                signatures.append(str(item["signature"]))
        clusters: list[WalletFifoSolanaSenderCluster] = []
        for group in groups.values():
            events_count = int(group["events_count"])
            own_sender = bool(group["own_wallet_sender"])
            own_receiver = bool(group["own_wallet_receiver"])
            failed_events = int(group["failed_events"])
            own_events = int(group["own_events"])
            if failed_events:
                status = "needs_retry_or_manual_evidence"
                action = "TXID-Beleg erneut abrufen oder manuell dokumentieren; keine FIFO-Transferannahme."
            elif own_sender and own_receiver and own_events == events_count:
                status = "own_wallet_transfer_candidate"
                action = "Als belegte Eigenumbuchung in Review-Liste aufnehmen; erst danach Transferanker schreiben."
            elif own_receiver and not own_sender:
                status = "external_or_unknown_sender"
                action = "Sender gegen Exchange-Auszahlungsadressen, historische eigene Wallets und Service-/Programm-Adressen abgleichen."
            else:
                status = "manual_review_required"
                action = "Sender/Empfaenger fachlich pruefen; keine automatische FIFO-Umbuchung."
            clusters.append(
                WalletFifoSolanaSenderCluster(
                    sender_owner=str(group["sender_owner"]),
                    receiver_owner=str(group["receiver_owner"]) if group.get("receiver_owner") else None,
                    status=status,
                    events_count=events_count,
                    expected_amount_total=group["expected_amount_total"],  # type: ignore[arg-type]
                    matched_amount_total=group["matched_amount_total"],  # type: ignore[arg-type]
                    first_block_time=str(group["first_block_time"]) if group.get("first_block_time") else None,
                    last_block_time=str(group["last_block_time"]) if group.get("last_block_time") else None,
                    own_wallet_sender=own_sender,
                    own_wallet_receiver=own_receiver,
                    recommended_action=action,
                    samples=group["samples"] if isinstance(group["samples"], list) else [],
                )
            )
        clusters.sort(
            key=lambda item: (
                item.status != "own_wallet_transfer_candidate",
                -abs(item.matched_amount_total),
                -item.events_count,
                item.sender_owner,
            )
        )
        total_clusters_count = len(clusters)
        normalized_limit = max(1, min(int(limit), 500))
        clusters = clusters[:normalized_limit]
        self._attach_solana_sender_cluster_local_evidence(clusters, groups)
        return WalletFifoSolanaSenderClusterReport(
            generated_at=datetime.now(timezone.utc),
            year=int(payload.get("year") or year),
            asset=str(payload.get("asset") or asset).upper(),
            artifact_path=str(artifact_path),
            artifact_exists=True,
            run_id=payload.get("run_id"),
            total_events=int(payload.get("total_events") or len(classifications)),
            clusters_count=total_clusters_count,
            own_transfer_candidate_events=sum(1 for item in classifications if isinstance(item, dict) and item.get("status") == "own_wallet_transfer_candidate"),
            external_or_unknown_events=sum(1 for item in classifications if isinstance(item, dict) and item.get("status") == "external_or_unknown_origin"),
            failed_events=sum(1 for item in classifications if isinstance(item, dict) and item.get("status") in failed_statuses),
            clusters=clusters,
            methodology=methodology,
        )

    @staticmethod
    def _decimal_from_any(value: object) -> Decimal:
        if value is None:
            return Decimal("0")
        try:
            return Decimal(str(value))
        except Exception:
            return Decimal("0")

    def _attach_solana_sender_cluster_local_evidence(
        self,
        clusters: list[WalletFifoSolanaSenderCluster],
        groups: dict[str, dict[str, object]],
    ) -> None:
        if not clusters:
            return
        try:
            with self.store.connect() as con:
                for cluster in clusters:
                    sender_hits = con.execute(
                        "select count(*) from raw_objects where payload_json like ?",
                        [f"%{cluster.sender_owner}%"],
                    ).fetchone()[0]
                    signatures = groups.get(cluster.sender_owner, {}).get("signatures", [])
                    signature_evidence_count = 0
                    canonical_signature_count = 0
                    if isinstance(signatures, list):
                        for signature in signatures:
                            signature_evidence_count += int(
                                con.execute(
                                    "select count(*) from raw_objects where payload_json like ?",
                                    [f"%{signature}%"],
                                ).fetchone()[0]
                            )
                            canonical_signature_count += int(
                                con.execute(
                                    "select count(*) from canonical_events where tx_id = ?",
                                    [signature],
                                ).fetchone()[0]
                            )
                    cluster.local_raw_sender_hits = int(sender_hits)
                    cluster.local_signature_evidence_count = signature_evidence_count
                    cluster.local_canonical_signature_count = canonical_signature_count
        except Exception:
            return

    def solana_sender_cluster_outflows(
        self,
        year: int,
        *,
        asset: str = "SOL",
        sender_owner: str | None = None,
        limit: int = 25,
        window_hours: int = 48,
        amount_tolerance_percent: Decimal = Decimal("1"),
        output_dir: Path | None = None,
    ) -> WalletFifoSolanaSenderClusterOutflowReport:
        artifact_path = (output_dir or self.DEFAULT_SOLANA_PROVENANCE_BATCH_DIR) / (
            f"latest_{year}_{asset.upper()}_provenance_classification.json"
        )
        methodology = (
            "Read-only Abgleich offener Solana-Inbounds gegen zeit-/betragsnahe lokale SOL-Abgaenge. "
            "Das ist nur Review-Evidence fuer Onchain-/DEX-/Service-Fluesse; es schreibt keine "
            "Transferanker und beweist ohne Sender-/Exchange-Beleg keine Eigenumbuchung."
        )
        if not artifact_path.exists():
            return WalletFifoSolanaSenderClusterOutflowReport(
                generated_at=datetime.now(timezone.utc),
                year=year,
                asset=asset.upper(),
                artifact_path=str(artifact_path),
                artifact_exists=False,
                sender_owner=sender_owner,
                methodology=methodology,
            )
        try:
            payload = json.loads(artifact_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return WalletFifoSolanaSenderClusterOutflowReport(
                generated_at=datetime.now(timezone.utc),
                year=year,
                asset=asset.upper(),
                artifact_path=str(artifact_path),
                artifact_exists=True,
                sender_owner=sender_owner,
                methodology=f"{methodology} Letztes Artefakt konnte nicht gelesen werden: {exc}",
            )
        classifications = [
            item
            for item in (payload.get("classifications") if isinstance(payload.get("classifications"), list) else [])
            if isinstance(item, dict)
            and str(item.get("asset") or asset).upper() == asset.upper()
            and (sender_owner is None or item.get("sender_owner") == sender_owner)
        ]
        classifications.sort(
            key=lambda item: (
                -abs(self._decimal_from_any(item.get("matched_amount"))),
                str(item.get("block_time") or ""),
            )
        )
        checked = 0
        candidates_total = 0
        samples: list[WalletFifoSolanaSenderClusterOutflowSample] = []
        normalized_limit = max(1, min(int(limit), 200))
        normalized_window_hours = max(1, min(int(window_hours), 24 * 30))
        tolerance_percent = max(Decimal("0"), amount_tolerance_percent)
        local_outflow_rows = self._solana_negative_outflow_rows(asset.upper())
        withdrawal_evidence_by_event_id: dict[str, WalletFifoOriginRawEvidence | None] = {}
        for item in classifications[:normalized_limit]:
            block_time = str(item.get("block_time") or "")
            inbound_time = self._parse_iso_datetime(block_time)
            if inbound_time is None:
                continue
            checked += 1
            inbound_amount = self._decimal_from_any(item.get("matched_amount") or item.get("expected_amount"))
            candidates = self._nearby_solana_outflow_candidates_from_rows(
                rows=local_outflow_rows,
                asset=asset.upper(),
                inbound_time=inbound_time,
                inbound_amount=inbound_amount,
                window_hours=normalized_window_hours,
                amount_tolerance_percent=tolerance_percent,
                withdrawal_evidence_by_event_id=withdrawal_evidence_by_event_id,
            )
            candidates_total += len(candidates)
            if candidates:
                samples.append(
                    WalletFifoSolanaSenderClusterOutflowSample(
                        inbound_event_id=str(item.get("event_id") or ""),
                        inbound_signature=str(item.get("signature") or ""),
                        inbound_block_time=block_time or None,
                        inbound_sender_owner=str(item.get("sender_owner") or "unknown_sender"),
                        inbound_receiver_owner=str(item.get("receiver_owner")) if item.get("receiver_owner") else None,
                        inbound_amount=inbound_amount,
                        candidates=candidates,
                    )
                )
        return WalletFifoSolanaSenderClusterOutflowReport(
            generated_at=datetime.now(timezone.utc),
            year=int(payload.get("year") or year),
            asset=str(payload.get("asset") or asset).upper(),
            artifact_path=str(artifact_path),
            artifact_exists=True,
            sender_owner=sender_owner,
            checked_events_count=checked,
            events_with_candidates_count=len(samples),
            candidates_count=candidates_total,
            window_hours=normalized_window_hours,
            amount_tolerance_percent=tolerance_percent,
            samples=samples,
            methodology=methodology,
        )

    def _solana_negative_outflow_rows(self, asset: str) -> list[tuple[object, ...]]:
        try:
            with self.store.connect() as con:
                return con.execute(
                    """
                    select
                        c.event_id,
                        c.source,
                        c.account,
                        c.event_time,
                        c.event_type,
                        c.asset,
                        c.quantity,
                        c.tx_id,
                        c.source_ref,
                        c.raw_object_id,
                        b.source as raw_source,
                        b.filename as raw_filename,
                        r.row_number as raw_row_number,
                        r.payload_json as raw_payload_json
                    from canonical_events c
                    left join raw_objects r on r.raw_object_id = c.raw_object_id
                    left join raw_import_batches b on b.batch_id = r.batch_id
                    where upper(c.asset) = ?
                      and c.quantity < 0
                    order by c.event_time
                    """,
                    [asset.upper()],
                ).fetchall()
        except Exception:
            return []

    def _negative_outflow_rows_by_asset(self) -> dict[str, list[tuple[object, ...]]]:
        grouped: dict[str, list[tuple[object, ...]]] = defaultdict(list)
        try:
            with self.store.connect() as con:
                rows = con.execute(
                    """
                    select
                        c.event_id,
                        c.source,
                        c.account,
                        c.event_time,
                        c.event_type,
                        c.asset,
                        c.quantity,
                        c.tx_id,
                        c.source_ref,
                        c.raw_object_id,
                        b.source as raw_source,
                        b.filename as raw_filename,
                        r.row_number as raw_row_number,
                        r.payload_json as raw_payload_json
                    from canonical_events c
                    left join raw_objects r on r.raw_object_id = c.raw_object_id
                    left join raw_import_batches b on b.batch_id = r.batch_id
                    where c.quantity < 0
                    order by c.event_time
                    """
                ).fetchall()
        except Exception:
            return {}
        for row in rows:
            grouped[str(row[5]).upper()].append(row)
        return dict(grouped)

    def _nearby_solana_outflow_candidates_from_rows(
        self,
        *,
        rows: list[tuple[object, ...]],
        asset: str,
        inbound_time: datetime,
        inbound_amount: Decimal,
        window_hours: int,
        amount_tolerance_percent: Decimal,
        withdrawal_evidence_by_event_id: dict[str, WalletFifoOriginRawEvidence | None] | None = None,
    ) -> list[WalletFifoSolanaNearbyOutflowCandidate]:
        if inbound_amount <= 0:
            return []
        tolerance = max(Decimal("0.000001"), inbound_amount * amount_tolerance_percent / Decimal("100"))
        start = (inbound_time - timedelta(hours=window_hours)).replace(tzinfo=None)
        end = (inbound_time + timedelta(hours=window_hours)).replace(tzinfo=None)
        naive_inbound = inbound_time.replace(tzinfo=None)
        sortable_candidates: list[tuple[Decimal, int, datetime, WalletFifoSolanaNearbyOutflowCandidate]] = []
        for row in rows:
            event_time = row[3]
            quantity = row[6]
            if str(row[5]).upper() != asset.upper() or not isinstance(event_time, datetime):
                continue
            if event_time < start:
                continue
            if event_time > end:
                break
            amount_delta = abs(abs(quantity) - inbound_amount)
            if amount_delta > tolerance:
                continue
            seconds_delta = int(abs((event_time - naive_inbound).total_seconds())) if isinstance(event_time, datetime) else 0
            source = str(row[1])
            account = str(row[2]) if row[2] else None
            raw_payload = row[13]
            withdrawal_evidence = None
            if self._solana_outflow_evidence_category(source=source, account=account) == "exchange_outflow_candidate":
                event_id = str(row[0])
                if withdrawal_evidence_by_event_id is not None:
                    if event_id not in withdrawal_evidence_by_event_id:
                        withdrawal_evidence_by_event_id[event_id] = self._matching_withdrawal_history(
                            self._canonical_event_from_outflow_row(row)
                        )
                    withdrawal_evidence = withdrawal_evidence_by_event_id.get(event_id)
                else:
                    withdrawal_evidence = self._matching_withdrawal_history(
                        self._canonical_event_from_outflow_row(row)
                    )
            withdrawal_payload = withdrawal_evidence.payload if withdrawal_evidence else {}
            withdrawal_tx_id = (
                self._payload_str(withdrawal_payload, "tx_id")
                or self._payload_str(withdrawal_payload, "txId")
                or self._payload_str(withdrawal_payload, "TXID")
                or self._payload_str(withdrawal_payload, "TxID")
                or self._payload_str(withdrawal_payload, "Transaction hash(txid)")
                or self._payload_str(withdrawal_payload, "Transaction Hash")
            )
            withdrawal_address = (
                self._payload_str(withdrawal_payload, "address")
                or self._payload_str(withdrawal_payload, "Address")
                or self._payload_str(withdrawal_payload, "To Address")
                or self._payload_str(withdrawal_payload, "To address")
                or self._payload_str(withdrawal_payload, "Destination")
            )
            withdrawal_network = self._payload_str(withdrawal_payload, "network") or self._payload_str(withdrawal_payload, "Network")
            withdrawal_amount = self._payload_decimal_any(withdrawal_payload, ("amount", "Amount", "Quantity"))
            withdrawal_fee = self._payload_decimal_any(
                withdrawal_payload,
                ("transaction_fee", "transactionFee", "Transaction Fee", "Withdrawal fee", "withdrawal fee"),
            )
            withdrawal_status = None
            if withdrawal_evidence:
                withdrawal_status = (
                    "withdrawal_address_txid_ready"
                    if withdrawal_tx_id and withdrawal_address
                    else "withdrawal_evidence_missing_address_or_txid"
                )
            candidate = WalletFifoSolanaNearbyOutflowCandidate(
                    event_id=str(row[0]) if row[0] else None,
                    source=source,
                    account=account,
                    event_time=event_time,
                    event_type=str(row[4]),
                    asset=str(row[5]),
                    quantity=quantity,
                    tx_id=str(row[7]) if row[7] else None,
                    source_ref=str(row[8]) if row[8] else None,
                    seconds_delta=seconds_delta,
                    amount_delta=amount_delta,
                    evidence_category=self._solana_outflow_evidence_category(source=source, account=account),
                    exchange_evidence_status=self._exchange_outflow_evidence_status(
                        source=source,
                        account=account,
                        tx_id=str(row[7]) if row[7] else None,
                        raw_payload=raw_payload,
                    ),
                    raw_object_id=str(row[9]) if row[9] else None,
                    raw_source=str(row[10]) if row[10] else None,
                    raw_filename=str(row[11]) if row[11] else None,
                    raw_row_number=int(row[12]) if isinstance(row[12], int) else None,
                    withdrawal_evidence_status=withdrawal_status,
                    withdrawal_raw_object_id=withdrawal_evidence.raw_object_id if withdrawal_evidence else None,
                    withdrawal_tx_id=withdrawal_tx_id,
                    withdrawal_address=withdrawal_address,
                    withdrawal_network=withdrawal_network,
                    withdrawal_amount=withdrawal_amount,
                    withdrawal_fee=withdrawal_fee,
                    recommended_action=self._solana_outflow_evidence_action(
                        source=source,
                        account=account,
                        tx_id=str(row[7]) if row[7] else None,
                        raw_payload=raw_payload,
                        withdrawal_tx_id=withdrawal_tx_id,
                        withdrawal_address=withdrawal_address,
                    ),
                )
            sortable_candidates.append((amount_delta, seconds_delta, event_time, candidate))
        sortable_candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        return [item[3] for item in sortable_candidates[:5]]

    def _withdrawal_evidence_by_outflow_event_id(
        self,
        rows: list[tuple[object, ...]],
    ) -> dict[str, WalletFifoOriginRawEvidence | None]:
        evidence_by_id: dict[str, WalletFifoOriginRawEvidence | None] = {}
        for row in rows:
            event_id = str(row[0])
            if event_id in evidence_by_id:
                continue
            source = str(row[1])
            account = str(row[2]) if row[2] else None
            if self._solana_outflow_evidence_category(source=source, account=account) != "exchange_outflow_candidate":
                continue
            evidence_by_id[event_id] = self._matching_withdrawal_history(
                self._canonical_event_from_outflow_row(row)
            )
        return evidence_by_id

    @staticmethod
    def _canonical_event_from_outflow_row(row: tuple[object, ...]) -> CanonicalEvent:
        event_time = row[3]
        if isinstance(event_time, datetime) and event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=timezone.utc)
        return CanonicalEvent(
            event_id=str(row[0]),
            source=str(row[1]),
            source_ref=str(row[8]) if row[8] else None,
            event_time=event_time if isinstance(event_time, datetime) else datetime.now(timezone.utc),
            event_type=str(row[4]),
            asset=str(row[5]),
            quantity=row[6],
            tx_id=str(row[7]) if row[7] else None,
            account=str(row[2]) if row[2] else None,
            confidence=Decimal("1"),
            raw_object_id=str(row[9]) if row[9] else None,
        )

    @staticmethod
    def _solana_outflow_evidence_category(*, source: str, account: str | None) -> str:
        source_lower = source.strip().lower()
        account_lower = (account or "").strip().lower()
        if source_lower in {"binance", "bitget", "pionex"} or account_lower in {"spot", "funding", "bitget", "pionex"} or "binance" in account_lower:
            return "exchange_outflow_candidate"
        if source_lower == "solana_rpc":
            return "same_wallet_onchain_flow_candidate"
        return "local_outflow_candidate"

    @staticmethod
    def _exchange_outflow_evidence_status(
        *,
        source: str,
        account: str | None,
        tx_id: str | None,
        raw_payload: object,
    ) -> str | None:
        category = WalletFifoPreviewService._solana_outflow_evidence_category(source=source, account=account)
        if category != "exchange_outflow_candidate":
            return None
        payload_obj = WalletFifoPreviewService._parse_payload(str(raw_payload) if raw_payload else None)
        binance_status = WalletFifoPreviewService._binance_outflow_evidence_status(payload_obj)
        if binance_status is not None:
            return binance_status
        bitget_status = WalletFifoPreviewService._bitget_outflow_evidence_status(payload_obj)
        if bitget_status is not None:
            return bitget_status
        payload = str(raw_payload or "")
        has_address = any(token in payload for token in ("Address", "address", "To Address", "Destination", "TXID", "txId", "Transaction ID"))
        if tx_id and has_address:
            return "withdrawal_address_txid_ready"
        if has_address:
            return "withdrawal_address_or_txid_in_raw_payload"
        return "transaction_history_without_address_txid"

    @staticmethod
    def _binance_outflow_evidence_status(payload: dict[str, object]) -> str | None:
        if not payload:
            return None
        operation = str(payload.get("Operation") or payload.get("operation") or "").strip().lower()
        remark = str(payload.get("Remark") or payload.get("remark") or "").strip().lower()
        record_type = str(payload.get("record_type") or payload.get("Record Type") or payload.get("type") or "").strip().lower()
        account_type = str(payload.get("account_type") or payload.get("Account Type") or "").strip().lower()
        source_ref = str(payload.get("source_ref") or payload.get("Source Ref") or "").strip().lower()
        if not operation and not remark and not record_type and not account_type and not source_ref:
            return None
        if "transfer between" in operation and "account" in operation:
            return "binance_internal_account_transfer"
        if "simple earn" in operation or "binance earn" in remark:
            if "subscription" in operation or "redemption" in operation:
                return "binance_internal_earn_transfer"
        if "simple_earn" in account_type or source_ref.startswith("flexible_"):
            if "subscription" in record_type or "redemption" in record_type or "flexible_" in source_ref:
                return "binance_internal_earn_transfer"
        return None

    @staticmethod
    def _bitget_outflow_evidence_status(payload: dict[str, object]) -> str | None:
        if not payload:
            return None
        action = str(
            payload.get("Action")
            or payload.get("action")
            or payload.get("Action (English)")
            or payload.get("action (english)")
            or ""
        ).strip().upper()
        record_type = str(payload.get("Type") or payload.get("type") or "").strip().upper()
        if not action and not record_type:
            return None
        if action in {"WITHDRAW", "WITHDRAW_FROZEN"} or record_type == "WITHDRAWAL":
            return "withdrawal_transaction_without_address_txid"
        if "ORDER_DEALT" in action or record_type == "TRADING":
            return "bitget_trading_or_order_freeze_not_withdrawal"
        if "STRATEGY" in action:
            return "bitget_strategy_internal_transfer"
        if action in {"TRANSFER_OUT", "TRANSFER_IN"} or record_type == "FUND TRANSFER":
            return "bitget_internal_fund_transfer"
        return None

    @staticmethod
    def _is_exchange_internal_context_status(status: str | None) -> bool:
        return status in {
            "binance_internal_earn_transfer",
            "binance_internal_account_transfer",
            "bitget_internal_fund_transfer",
            "bitget_strategy_internal_transfer",
            "bitget_trading_or_order_freeze_not_withdrawal",
        }

    @staticmethod
    def _is_exchange_internal_inbound_context(
        *,
        event: CanonicalEvent,
        raw_evidence: WalletFifoOriginRawEvidence | None,
    ) -> bool:
        payload = raw_evidence.payload if raw_evidence else {}
        source = event.source.strip().lower()
        operation = str(payload.get("Operation") or payload.get("operation") or "").strip().lower()
        remark = str(payload.get("Remark") or payload.get("remark") or "").strip().lower()
        if source == "binance":
            if "index-auto-investment" in operation and "redeem positions" in operation:
                return True
            if "staking redemption" in operation:
                return True
            if "simple earn" in operation or "binance earn" in remark:
                if "redemption" in operation:
                    return True
            return False
        if source == "bitget":
            action = str(
                payload.get("Action")
                or payload.get("action")
                or payload.get("Action (English)")
                or payload.get("action (english)")
                or ""
            ).strip().upper()
            record_type = str(payload.get("Type") or payload.get("type") or "").strip().upper()
            if "STRATEGY_TRANSFER" in action:
                return True
            if action in {"TRANSFER_IN", "TRANSFER_OUT"}:
                return True
            if record_type == "FUND TRANSFER":
                return True
            if action in {"TRANS_FROM_EXCHANGE", "TRANS_FROM_STRATEGY", "TRANS_FROM_MANUAL_STRATEGY"}:
                return True
        return False

    @staticmethod
    def _is_bitget_recharge_deposit_event(event: CanonicalEvent) -> bool:
        if event.source.strip().lower() != "bitget" or event.quantity <= 0:
            return False
        return True

    def _is_bitget_recharge_deposit_payload(self, raw_evidence: WalletFifoOriginRawEvidence | None) -> bool:
        payload = raw_evidence.payload if raw_evidence else {}
        action = str(payload.get("Action") or payload.get("action") or "").strip().upper()
        record_type = str(payload.get("Type") or payload.get("type") or "").strip().upper()
        return action == "RECHARGE" and record_type == "DEPOSIT"

    def _is_matching_known_wallet_spl_outflow(
        self,
        *,
        raw_evidence: WalletFifoOriginRawEvidence | None,
        asset: str,
        amount: Decimal,
    ) -> bool:
        payload = raw_evidence.payload if raw_evidence else {}
        parsed = self._parse_solana_raw_row(payload.get("raw_row"))
        if not parsed:
            return False
        message = parsed.get("transaction", {}).get("message", {}) if isinstance(parsed.get("transaction"), dict) else {}
        account_keys = message.get("accountKeys") if isinstance(message, dict) else []
        signers = {
            str(key.get("pubkey"))
            for key in account_keys
            if isinstance(key, dict) and key.get("signer") is True and key.get("pubkey")
        }
        if not signers.intersection(self.KNOWN_OWN_SOLANA_WALLETS):
            return False
        meta = parsed.get("meta") if isinstance(parsed.get("meta"), dict) else {}
        deltas = self._token_deltas_by_owner(
            pre=meta.get("preTokenBalances") if isinstance(meta.get("preTokenBalances"), list) else [],
            post=meta.get("postTokenBalances") if isinstance(meta.get("postTokenBalances"), list) else [],
        )
        asset_deltas = [item for item in deltas if item.asset.upper() == asset.upper()]
        sender = self._largest_owner(asset_deltas, negative=True)
        receiver = self._largest_owner(asset_deltas, negative=False)
        if sender is None or receiver is None:
            return False
        amount_matches = abs(abs(sender.delta_quantity) - amount) <= self._transfer_match_tolerance(asset)
        receiver_matches = abs(receiver.delta_quantity - amount) <= self._transfer_match_tolerance(asset)
        return (
            amount_matches
            and receiver_matches
            and bool(sender.owner in self.KNOWN_OWN_SOLANA_WALLETS)
            and bool(receiver.owner)
            and receiver.owner not in self.KNOWN_OWN_SOLANA_WALLETS
        )

    @staticmethod
    def _solana_outflow_evidence_action(
        *,
        source: str,
        account: str | None,
        tx_id: str | None = None,
        raw_payload: object = None,
        withdrawal_tx_id: str | None = None,
        withdrawal_address: str | None = None,
    ) -> str:
        category = WalletFifoPreviewService._solana_outflow_evidence_category(source=source, account=account)
        if category == "exchange_outflow_candidate":
            if withdrawal_tx_id and withdrawal_address:
                return "Withdrawal-History/API belegt Adresse und TXID; als Transferanker-Kandidat im Review pruefen."
            status = WalletFifoPreviewService._exchange_outflow_evidence_status(
                source=source,
                account=account,
                tx_id=tx_id,
                raw_payload=raw_payload,
            )
            if status == "transaction_history_without_address_txid":
                return "Transaction-History belegt Withdraw-Betrag; Withdrawal-History/API-Beleg mit Adresse und TXID fehlt."
            if status == "binance_internal_earn_transfer":
                return "Binance-Rohzeile ist interner Simple-Earn-Transfer; nicht als Blockchain-Withdrawal werten."
            if status == "binance_internal_account_transfer":
                return "Binance-Rohzeile ist interner Konto-/Futures-Transfer; nicht als Blockchain-Withdrawal werten."
            if status in {"bitget_internal_fund_transfer", "bitget_strategy_internal_transfer", "bitget_trading_or_order_freeze_not_withdrawal"}:
                return "Bitget-Rohzeile ist interner Fund-/Strategy-/Trading-Kontext; nicht als Blockchain-Withdrawal werten."
            if status == "withdrawal_transaction_without_address_txid":
                return "Bitget-Withdrawal-Zeile erkannt; Deposit-Withdrawal-History/API-Beleg mit Adresse und TXID verknuepfen."
            return "Exchange-Withdrawal-Beleg mit Adresse/TXID beschaffen; erst danach als Transferanker-Kandidat reviewen."
        if category == "same_wallet_onchain_flow_candidate":
            return "Onchain-Kontext pruefen: kann DEX-/Service-/Programmfluss sein, kein automatischer Eigenwallet-Transfer."
        return "Lokalen Abgang fachlich pruefen und Belegquelle zuordnen."

    @staticmethod
    def _parse_iso_datetime(value: str) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _fetch_solscan_provenance_classification(
        self,
        *,
        client: httpx.Client,
        api_key: str,
        event: WalletFifoProvenanceEvent,
    ) -> WalletFifoSolanaProvenanceClassification:
        signature = str(event.onchain_tx_id or event.tx_id or "")
        try:
            response = client.get(
                "https://pro-api.solscan.io/v2.0/transaction/actions",
                params={"tx": signature},
                headers={"token": api_key, "accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            return self._solana_provenance_classification_error(
                event=event,
                signature=signature,
                status="failed",
                reason=str(exc),
                evidence_source="solscan",
            )
        if response.status_code == 429:
            return self._solana_provenance_classification_error(event=event, signature=signature, status="rate_limited", reason="solscan_http_429", evidence_source="solscan")
        if response.status_code >= 400:
            return self._solana_provenance_classification_error(event=event, signature=signature, status="failed", reason=f"solscan_http_{response.status_code}", evidence_source="solscan")
        payload = response.json()
        if isinstance(payload, dict) and payload.get("success") is False:
            return self._solana_provenance_classification_error(event=event, signature=signature, status="failed", reason=str(payload.get("errors") or "solscan_success_false"), evidence_source="solscan")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            return self._solana_provenance_classification_error(event=event, signature=signature, status="not_found", reason="solscan_data_missing", evidence_source="solscan")
        return self._classify_solscan_actions(event=event, signature=signature, data=data)

    def _classify_solscan_actions(
        self,
        *,
        event: WalletFifoProvenanceEvent,
        signature: str,
        data: dict[str, object],
    ) -> WalletFifoSolanaProvenanceClassification:
        transfers = self._flatten_solscan_transfers(data)
        best: tuple[Decimal, dict[str, object], Decimal] | None = None
        for transfer in transfers:
            asset = self._solscan_transfer_asset(transfer)
            if asset and asset.upper() != event.asset.upper():
                continue
            amount = self._solscan_transfer_amount(transfer)
            if amount is None:
                continue
            from_owner = self._solscan_transfer_owner(transfer, ("from", "src", "source", "sender", "from_address", "source_owner"))
            to_owner = self._solscan_transfer_owner(transfer, ("to", "dst", "destination", "receiver", "to_address", "destination_owner"))
            if event.account and to_owner != event.account:
                continue
            delta = abs(amount - event.quantity)
            if best is None or delta < best[0]:
                best = (delta, transfer, amount)
        if best is None:
            return self._solana_provenance_classification_error(
                event=event,
                signature=signature,
                status="external_or_unknown_origin",
                reason="solscan_matching_transfer_missing",
                evidence_source="solscan",
            )
        delta, transfer, amount = best
        sender_owner = self._solscan_transfer_owner(transfer, ("from", "src", "source", "sender", "from_address", "source_owner"))
        receiver_owner = self._solscan_transfer_owner(transfer, ("to", "dst", "destination", "receiver", "to_address", "destination_owner"))
        sender_known = bool(sender_owner in self.KNOWN_OWN_SOLANA_WALLETS)
        receiver_known = bool(receiver_owner in self.KNOWN_OWN_SOLANA_WALLETS)
        amount_matches = delta <= Decimal("0.000001")
        status = "own_wallet_transfer_candidate" if sender_known and receiver_known and amount_matches else "external_or_unknown_origin"
        return WalletFifoSolanaProvenanceClassification(
            event_id=event.event_id,
            signature=signature,
            evidence_source="solscan",
            status=status,
            asset=event.asset.upper(),
            expected_amount=event.quantity,
            matched_amount=amount,
            wallet_delta_quantity=amount if receiver_owner == event.account else None,
            sender_owner=sender_owner,
            receiver_owner=receiver_owner,
            sender_is_known_own_wallet=sender_known,
            receiver_is_known_own_wallet=receiver_known,
            block_time=self._solscan_block_time(data),
            slot=int(data["block_id"]) if isinstance(data.get("block_id"), int) else None,
            reason=None if amount_matches else f"amount_delta:{delta}",
            recommended_action=(
                "Solscan markiert Sender und Empfaenger als bekannte eigene Wallets; Transferanker-Kandidat pruefen."
                if status == "own_wallet_transfer_candidate"
                else "Solscan-Transfer gefunden, aber Sender/Empfaenger/Betrag nicht vollstaendig als eigene Umbuchung belegt."
            ),
        )

    def _flatten_solscan_transfers(self, data: dict[str, object]) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []

        def walk(value: object) -> None:
            if isinstance(value, list):
                for item in value:
                    walk(item)
                return
            if not isinstance(value, dict):
                return
            keys = {str(key).lower() for key in value.keys()}
            if keys & {"from", "src", "source", "sender", "from_address"} and keys & {"to", "dst", "destination", "receiver", "to_address"}:
                result.append(value)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    walk(child)

        for key in ("transfers", "activities", "summaries"):
            walk(data.get(key))
        return result

    def _solscan_transfer_asset(self, transfer: dict[str, object]) -> str | None:
        symbol = (
            self._payload_str(transfer, "token_symbol")
            or self._payload_str(transfer, "symbol")
            or self._payload_str(transfer, "asset")
        )
        if symbol:
            return "SOL" if symbol.upper() in {"SOL", "WSOL"} else symbol.upper()
        token = (
            self._payload_str(transfer, "token")
            or self._payload_str(transfer, "token_address")
            or self._payload_str(transfer, "mint")
        )
        if token in {"So11111111111111111111111111111111111111111", "So11111111111111111111111111111111111111112"}:
            return "SOL"
        return token

    def _solscan_transfer_amount(self, transfer: dict[str, object]) -> Decimal | None:
        amount = self._payload_decimal_any(transfer, ("amount", "value", "token_amount", "change_amount"))
        if amount is None:
            return None
        decimals_raw = transfer.get("token_decimals") or transfer.get("decimals")
        try:
            decimals = int(str(decimals_raw)) if decimals_raw is not None else None
        except Exception:
            decimals = None
        if decimals is not None and abs(amount) >= Decimal("1000000"):
            return abs(amount) / (Decimal(10) ** decimals)
        return abs(amount)

    @staticmethod
    def _solscan_transfer_owner(transfer: dict[str, object], keys: tuple[str, ...]) -> str | None:
        for key in keys:
            value = transfer.get(key)
            if isinstance(value, dict):
                nested = value.get("address") or value.get("account") or value.get("owner")
                if nested:
                    return str(nested)
            if value:
                return str(value)
        return None

    @staticmethod
    def _solscan_block_time(data: dict[str, object]) -> str | None:
        if isinstance(data.get("time"), str):
            return str(data.get("time"))
        if isinstance(data.get("block_time"), int):
            return datetime.fromtimestamp(int(data["block_time"]), tz=timezone.utc).isoformat()
        return None

    def _solscan_api_key(self) -> str:
        try:
            settings = {setting.key: setting.value_json for setting in self.store.list_admin_settings()}
            raw = settings.get("secret.solscan.api_key")
            if raw:
                value = json.loads(raw)
                if value:
                    return str(value).strip()
        except Exception:
            pass
        for env_key in ("SOLSCAN_API_KEY", "SOLSCAN_PRO_API_KEY"):
            value = os.getenv(env_key)
            if value:
                return value.strip()
        try:
            if "/workspace/steuerreport/src" not in sys.path:
                sys.path.append("/workspace/steuerreport/src")
            from tax_engine.admin import resolve_secret_value  # type: ignore

            return str(resolve_secret_value("secret.solscan.api_key") or "").strip()
        except Exception:
            return ""

    def _alchemy_api_key(self) -> str:
        try:
            settings = {setting.key: setting.value_json for setting in self.store.list_admin_settings()}
            raw = settings.get("secret.alchemy.api_key")
            if raw:
                value = json.loads(raw)
                if value:
                    return str(value).strip()
        except Exception:
            pass
        for env_key in ("ALCHEMY_API_KEY", "ALCHEMY_SOLANA_API_KEY"):
            value = os.getenv(env_key)
            if value:
                return value.strip()
        try:
            if "/workspace/steuerreport/src" not in sys.path:
                sys.path.append("/workspace/steuerreport/src")
            from tax_engine.admin import resolve_secret_value  # type: ignore

            return str(resolve_secret_value("secret.alchemy.api_key") or "").strip()
        except Exception:
            return ""

    def _fetch_solana_provenance_classification(
        self,
        *,
        client: httpx.Client,
        rpc_url: str,
        event: WalletFifoProvenanceEvent,
    ) -> WalletFifoSolanaProvenanceClassification:
        signature = str(event.onchain_tx_id or event.tx_id or "")
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [
                signature,
                {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0},
            ],
        }
        try:
            response = client.post(rpc_url, json=payload)
        except httpx.HTTPError as exc:
            return self._solana_provenance_classification_error(event=event, signature=signature, status="failed", reason=str(exc))
        if response.status_code == 429:
            return self._solana_provenance_classification_error(event=event, signature=signature, status="rate_limited", reason="rpc_http_429")
        if response.status_code >= 400:
            return self._solana_provenance_classification_error(event=event, signature=signature, status="failed", reason=f"rpc_http_{response.status_code}")
        data = response.json()
        if data.get("error"):
            return self._solana_provenance_classification_error(event=event, signature=signature, status="failed", reason=str(data["error"]))
        result = data.get("result")
        if not isinstance(result, dict):
            return self._solana_provenance_classification_error(event=event, signature=signature, status="not_found", reason="rpc_result_null")
        meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
        if meta.get("err") is not None:
            return self._solana_provenance_classification_error(
                event=event,
                signature=signature,
                status="failed",
                reason=f"transaction_err:{meta.get('err')}",
            )
        if event.asset.upper() == "SOL":
            return self._classify_native_sol_transaction(event=event, signature=signature, result=result)
        return self._classify_spl_transaction(event=event, signature=signature, result=result)

    def _classify_native_sol_transaction(
        self,
        *,
        event: WalletFifoProvenanceEvent,
        signature: str,
        result: dict[str, object],
    ) -> WalletFifoSolanaProvenanceClassification:
        deltas = self._native_sol_deltas(result)
        receiver = self._largest_native_delta(deltas, positive=True)
        sender = self._largest_native_delta(deltas, positive=False)
        receiver_owner = receiver[0] if receiver else None
        sender_owner = sender[0] if sender else None
        wallet_delta = deltas.get(event.account or "")
        if wallet_delta is not None and wallet_delta > 0:
            receiver_owner = event.account
            matched_amount = wallet_delta
        else:
            matched_amount = receiver[1] if receiver else None
        receiver_known = bool(receiver_owner in self.KNOWN_OWN_SOLANA_WALLETS)
        sender_known = bool(sender_owner in self.KNOWN_OWN_SOLANA_WALLETS)
        amount_matches = matched_amount is not None and abs(matched_amount - event.quantity) <= Decimal("0.000001")
        status = "own_wallet_transfer_candidate" if receiver_known and sender_known and amount_matches else "external_or_unknown_origin"
        return WalletFifoSolanaProvenanceClassification(
            event_id=event.event_id,
            signature=signature,
            status=status,
            asset=event.asset.upper(),
            expected_amount=event.quantity,
            matched_amount=matched_amount,
            wallet_delta_quantity=wallet_delta,
            sender_owner=sender_owner,
            receiver_owner=receiver_owner,
            sender_is_known_own_wallet=sender_known,
            receiver_is_known_own_wallet=receiver_known,
            block_time=self._block_time(result.get("blockTime")),
            slot=result.get("slot") if isinstance(result.get("slot"), int) else None,
            recommended_action=(
                "Sender und Empfaenger sind bekannte eigene Wallets; als belegten Transferanker-Kandidaten pruefen."
                if status == "own_wallet_transfer_candidate"
                else "Sender/Empfaenger oder Betrag passen nicht vollstaendig zu bekannten eigenen Wallets; Herkunft fachlich pruefen."
            ),
        )

    def _classify_spl_transaction(
        self,
        *,
        event: WalletFifoProvenanceEvent,
        signature: str,
        result: dict[str, object],
    ) -> WalletFifoSolanaProvenanceClassification:
        meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
        deltas = self._token_deltas_by_owner(
            pre=meta.get("preTokenBalances") if isinstance(meta.get("preTokenBalances"), list) else [],
            post=meta.get("postTokenBalances") if isinstance(meta.get("postTokenBalances"), list) else [],
        )
        asset_deltas = [item for item in deltas if item.asset.upper() == event.asset.upper()]
        sender = self._largest_owner(asset_deltas, negative=True)
        receiver = self._largest_owner(asset_deltas, negative=False)
        matched_amount = receiver.delta_quantity if receiver else None
        sender_owner = sender.owner if sender else None
        receiver_owner = receiver.owner if receiver else None
        sender_known = bool(sender_owner in self.KNOWN_OWN_SOLANA_WALLETS)
        receiver_known = bool(receiver_owner in self.KNOWN_OWN_SOLANA_WALLETS)
        amount_matches = matched_amount is not None and abs(matched_amount - event.quantity) <= Decimal("0.000001")
        status = "own_wallet_transfer_candidate" if sender_known and receiver_known and amount_matches else "external_or_unknown_origin"
        return WalletFifoSolanaProvenanceClassification(
            event_id=event.event_id,
            signature=signature,
            status=status,
            asset=event.asset.upper(),
            expected_amount=event.quantity,
            matched_amount=matched_amount,
            wallet_delta_quantity=matched_amount if receiver_owner == event.account else None,
            sender_owner=sender_owner,
            receiver_owner=receiver_owner,
            sender_is_known_own_wallet=sender_known,
            receiver_is_known_own_wallet=receiver_known,
            block_time=self._block_time(result.get("blockTime")),
            slot=result.get("slot") if isinstance(result.get("slot"), int) else None,
            recommended_action=(
                "Bekannte eigene SPL-Umbuchung; Transferanker-Kandidat pruefen."
                if status == "own_wallet_transfer_candidate"
                else "SPL-Sender/Empfaenger nicht vollstaendig als eigene Wallets erkannt; Herkunft pruefen."
            ),
        )

    def _solana_provenance_classification_error(
        self,
        *,
        event: WalletFifoProvenanceEvent,
        signature: str,
        status: str,
        reason: str,
        evidence_source: str = "rpc",
    ) -> WalletFifoSolanaProvenanceClassification:
        return WalletFifoSolanaProvenanceClassification(
            event_id=event.event_id,
            signature=signature,
            evidence_source=evidence_source,
            status=status,
            asset=event.asset.upper(),
            expected_amount=event.quantity,
            reason=reason,
            recommended_action="Signaturbeleg erneut abrufen oder manuell ueber Solscan/RPC pruefen.",
        )

    def _native_sol_deltas(self, result: dict[str, object]) -> dict[str, Decimal]:
        transaction = result.get("transaction") if isinstance(result.get("transaction"), dict) else {}
        message = transaction.get("message") if isinstance(transaction.get("message"), dict) else {}
        account_keys = message.get("accountKeys") if isinstance(message.get("accountKeys"), list) else []
        meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
        pre_balances = meta.get("preBalances") if isinstance(meta.get("preBalances"), list) else []
        post_balances = meta.get("postBalances") if isinstance(meta.get("postBalances"), list) else []
        deltas: dict[str, Decimal] = {}
        for index, account in enumerate(account_keys):
            if index >= len(pre_balances) or index >= len(post_balances):
                continue
            owner = self._account_key_pubkey(account)
            if not owner:
                continue
            try:
                quantity = (Decimal(str(post_balances[index])) - Decimal(str(pre_balances[index]))) / Decimal("1000000000")
            except Exception:
                continue
            if quantity:
                deltas[owner] = deltas.get(owner, Decimal("0")) + quantity
        return deltas

    @staticmethod
    def _account_key_pubkey(account: object) -> str | None:
        if isinstance(account, str):
            return account
        if isinstance(account, dict) and account.get("pubkey"):
            return str(account.get("pubkey"))
        return None

    @staticmethod
    def _largest_native_delta(
        deltas: dict[str, Decimal],
        *,
        positive: bool,
    ) -> tuple[str, Decimal] | None:
        candidates = [(owner, quantity) for owner, quantity in deltas.items() if quantity > 0] if positive else [
            (owner, quantity) for owner, quantity in deltas.items() if quantity < 0
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: abs(item[1]))

    def withdrawal_gap_trace(self, year: int, *, limit: int = 20) -> WalletFifoWithdrawalGapReport:
        diagnosis = self.gap_diagnosis(year=year, limit=limit)
        events = self.store.list_canonical_events()
        traces: list[WalletFifoWithdrawalGapTrace] = []
        for gap in diagnosis.diagnoses:
            candidates = self._withdrawal_candidates_for_gap(gap, events)
            if not candidates:
                continue
            traces.append(
                WalletFifoWithdrawalGapTrace(
                    gap_id=gap.gap_id,
                    year=year,
                    asset=gap.asset,
                    pool_id=gap.pool_id,
                    missing_quantity=gap.missing_quantity,
                    gap_event_time=gap.event_time,
                    candidates=candidates,
                    recommended_action=(
                        "Withdrawal-History/API-Beleg mit Adresse und TXID importieren. "
                        "Erst danach darf ein lot-erhaltender Transferanker in den Zielpool gebildet werden."
                    ),
                )
            )
        return WalletFifoWithdrawalGapReport(
            generated_at=datetime.now(timezone.utc),
            year=year,
            traces_count=len(traces),
            traces=traces,
            methodology=(
                "Read-only Diagnose fuer offene Wallet-FIFO-Gaps, die durch Exchange-Withdrawals "
                "erklaert werden koennten. Transaction-History-Zeilen werden mit vorhandener "
                "Withdrawal-History nach Coin, Betrag und Zeitfenster abgeglichen. Ohne Adresse/TXID "
                "wird kein Transferanker erzeugt."
            ),
        )

    def _withdrawal_candidates_for_gap(
        self,
        gap: WalletFifoGapDiagnosis,
        events: list[CanonicalEvent],
    ) -> list[WalletFifoWithdrawalCandidate]:
        window_start = gap.event_time - timedelta(days=180)
        result: list[WalletFifoWithdrawalCandidate] = []
        gap_time = self._as_utc(gap.event_time)
        window_start = self._as_utc(window_start)
        for event in events:
            if event.event_type != "transfer" or event.source != "binance" or event.quantity >= 0:
                continue
            if event.asset.upper() != gap.asset.upper():
                continue
            event_time = self._as_utc(event.event_time)
            if not (window_start <= event_time <= gap_time):
                continue
            evidence = self._raw_evidence(event.raw_object_id) if event.raw_object_id else None
            if evidence and self._payload_str(evidence.payload, "Operation") != "Withdraw":
                continue
            withdrawal_evidence = self._matching_withdrawal_history(event)
            payload = withdrawal_evidence.payload if withdrawal_evidence else {}
            tx_id = (
                self._payload_str(payload, "TXID")
                or self._payload_str(payload, "TxID")
                or self._payload_str(payload, "txId")
                or self._payload_str(payload, "tx_id")
                or self._payload_str(payload, "Transaction hash(txid)")
                or self._payload_str(payload, "Transaction Hash")
                or event.tx_id
            )
            address = (
                self._payload_str(payload, "Address")
                or self._payload_str(payload, "To address")
                or self._payload_str(payload, "To Address")
                or self._payload_str(payload, "address")
            )
            network = self._payload_str(payload, "Network") or self._payload_str(payload, "network")
            status = "ready_for_transfer_anchor" if tx_id and address else "withdrawal_history_missing"
            result.append(
                WalletFifoWithdrawalCandidate(
                    event_id=event.event_id,
                    event_time=event.event_time,
                    source=event.source,
                    account=event.account,
                    pool_id=self._pool_id(event),
                    asset=event.asset.upper(),
                    quantity=abs(event.quantity),
                    raw_object_id=event.raw_object_id,
                    transaction_history_evidence=evidence,
                    withdrawal_history_evidence=withdrawal_evidence,
                    onchain_tx_id=tx_id,
                    to_address=address,
                    network=network,
                    evidence_status=status,
                    recommended_action=(
                        "Adresse/TXID vorhanden; Onchain-Ziel pruefen und Transferanker bilden."
                        if status == "ready_for_transfer_anchor"
                        else "Binance Withdrawal-History/API fuer diesen Zeitraum importieren; Transaction-History allein reicht nicht."
                    ),
                )
            )
        result.sort(
            key=lambda item: (
                item.evidence_status != "ready_for_transfer_anchor",
                abs(item.quantity - gap.missing_quantity),
                abs((gap_time - self._as_utc(item.event_time)).total_seconds()),
            )
        )
        return result[:10]

    def _fetch_solana_origin_trace(
        self,
        *,
        client: httpx.Client,
        rpc_url: str,
        signature: str,
        asset: str,
        expected_amount: Decimal | None,
        deposit_address: str | None,
    ) -> WalletFifoSolanaOriginTrace:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTransaction",
            "params": [
                signature,
                {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0},
            ],
        }
        try:
            response = client.post(rpc_url, json=payload)
        except httpx.HTTPError as exc:
            return self._solana_origin_error(signature, asset, expected_amount, deposit_address, "failed", str(exc))
        if response.status_code == 429:
            return self._solana_origin_error(signature, asset, expected_amount, deposit_address, "rate_limited", "rpc_http_429")
        if response.status_code >= 400:
            return self._solana_origin_error(signature, asset, expected_amount, deposit_address, "failed", f"rpc_http_{response.status_code}")
        data = response.json()
        if data.get("error"):
            return self._solana_origin_error(signature, asset, expected_amount, deposit_address, "failed", str(data["error"]))
        result = data.get("result")
        if not isinstance(result, dict):
            return self._solana_origin_error(signature, asset, expected_amount, deposit_address, "not_found", "rpc_result_null")
        meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
        if meta.get("err") is not None:
            return self._solana_origin_error(signature, asset, expected_amount, deposit_address, "failed", f"transaction_err:{meta.get('err')}")
        deltas = self._token_deltas_by_owner(
            pre=meta.get("preTokenBalances") if isinstance(meta.get("preTokenBalances"), list) else [],
            post=meta.get("postTokenBalances") if isinstance(meta.get("postTokenBalances"), list) else [],
        )
        asset_deltas = [item for item in deltas if item.asset.upper() == asset.upper()]
        sender = self._largest_owner(asset_deltas, negative=True)
        receiver = self._largest_owner(asset_deltas, negative=False)
        matched_amount = receiver.post_quantity - receiver.pre_quantity if receiver else None
        sender_owner = sender.owner if sender else None
        receiver_owner = receiver.owner if receiver else None
        sender_is_known = bool(sender_owner in self.KNOWN_OWN_SOLANA_WALLETS)
        receiver_is_deposit = bool(deposit_address and receiver_owner == deposit_address)
        status = "own_wallet_transfer_candidate" if sender_is_known and receiver_is_deposit else "external_or_unknown_origin"
        recommended = (
            "Sender ist bekannte eigene Wallet; Transferpaar bilden und Ursprungslots in Binance Spot fortschreiben."
            if status == "own_wallet_transfer_candidate"
            else "Sender ist nicht als eigene Wallet erkannt; Zufluss steuerlich klassifizieren oder Wallet-Liste erweitern."
        )
        return WalletFifoSolanaOriginTrace(
            signature=signature,
            status=status,
            block_time=self._block_time(result.get("blockTime")),
            slot=result.get("slot"),
            asset=asset.upper(),
            expected_amount=expected_amount,
            deposit_address=deposit_address,
            sender_owner=sender_owner,
            receiver_owner=receiver_owner,
            sender_is_known_own_wallet=sender_is_known,
            receiver_is_deposit_address=receiver_is_deposit,
            matched_amount=matched_amount,
            token_deltas=asset_deltas,
            known_wallets=sorted(self.KNOWN_OWN_SOLANA_WALLETS),
            recommended_action=recommended,
        )

    def _solana_origin_error(
        self,
        signature: str,
        asset: str,
        expected_amount: Decimal | None,
        deposit_address: str | None,
        status: str,
        reason: str,
    ) -> WalletFifoSolanaOriginTrace:
        return WalletFifoSolanaOriginTrace(
            signature=signature,
            status=status,
            asset=asset.upper(),
            expected_amount=expected_amount,
            deposit_address=deposit_address,
            known_wallets=sorted(self.KNOWN_OWN_SOLANA_WALLETS),
            recommended_action="RPC-Beleg erneut abrufen oder Solscan-Detail manuell pruefen.",
            reason=reason,
        )

    def _token_deltas_by_owner(self, *, pre: list[object], post: list[object]) -> list[WalletFifoSolanaTokenDelta]:
        pre_map = self._token_balance_map(pre)
        post_map = self._token_balance_map(post)
        result: list[WalletFifoSolanaTokenDelta] = []
        for key in sorted(set(pre_map) | set(post_map)):
            owner, mint = key
            pre_qty = pre_map.get(key, Decimal("0"))
            post_qty = post_map.get(key, Decimal("0"))
            delta = post_qty - pre_qty
            if not delta:
                continue
            result.append(
                WalletFifoSolanaTokenDelta(
                    owner=owner or None,
                    mint=mint,
                    asset=self.SOLANA_MINT_SYMBOLS.get(mint.upper(), mint[:6] + "..." + mint[-4:]),
                    pre_quantity=pre_qty,
                    post_quantity=post_qty,
                    delta_quantity=delta,
                )
            )
        return result

    def _token_balance_map(self, balances: list[object]) -> dict[tuple[str, str], Decimal]:
        result: dict[tuple[str, str], Decimal] = {}
        for item in balances:
            if not isinstance(item, dict):
                continue
            owner = str(item.get("owner") or "")
            mint = str(item.get("mint") or "")
            amount = item.get("uiTokenAmount") if isinstance(item.get("uiTokenAmount"), dict) else {}
            quantity = self._raw_token_amount(amount)
            if mint:
                result[(owner, mint)] = result.get((owner, mint), Decimal("0")) + quantity
        return result

    @staticmethod
    def _raw_token_amount(amount: dict[str, object]) -> Decimal:
        if amount.get("uiAmountString") is not None:
            return Decimal(str(amount.get("uiAmountString")))
        raw = Decimal(str(amount.get("amount") or "0"))
        decimals = int(amount.get("decimals") or 0)
        return raw / (Decimal(10) ** decimals)

    @staticmethod
    def _largest_owner(
        deltas: list[WalletFifoSolanaTokenDelta],
        *,
        negative: bool,
    ) -> WalletFifoSolanaTokenDelta | None:
        candidates = [item for item in deltas if item.delta_quantity < 0] if negative else [item for item in deltas if item.delta_quantity > 0]
        if not candidates:
            return None
        return max(candidates, key=lambda item: abs(item.delta_quantity))

    @staticmethod
    def _block_time(value: int | None) -> str | None:
        if value is None:
            return None
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()

    def _diagnose_gap(
        self,
        gap: WalletFifoPreviewUnmatched,
        events: list[CanonicalEvent],
        events_by_id: dict[str, CanonicalEvent],
    ) -> WalletFifoGapDiagnosis:
        disposal_event = events_by_id.get(gap.source_event_id)
        window_start = gap.event_time - timedelta(days=14)
        same_pool_candidates: list[WalletFifoGapCandidateEvent] = []
        other_pool_candidates: list[WalletFifoGapCandidateEvent] = []
        same_tx_candidates: list[WalletFifoGapCandidateEvent] = []
        for event in events:
            if event.asset.upper() != gap.asset.upper() and str(event.quote_asset or "").upper() != gap.asset.upper():
                continue
            relation = None
            if event.event_id == gap.source_event_id:
                relation = "gap_event"
            elif event.tx_id and disposal_event and event.tx_id == disposal_event.tx_id:
                relation = "same_tx"
            elif window_start <= event.event_time <= gap.event_time:
                event_pool = self._pool_id(event)
                if event_pool == gap.pool_id and self._positive_asset_quantity(event, gap.asset) > 0:
                    relation = "same_pool_prior_positive"
                elif self._positive_asset_quantity(event, gap.asset) > 0:
                    relation = "other_pool_prior_positive"
            if relation is None:
                continue
            candidate = self._candidate_from_event(event, gap, relation)
            if relation == "same_pool_prior_positive":
                same_pool_candidates.append(candidate)
            elif relation == "other_pool_prior_positive":
                other_pool_candidates.append(candidate)
            elif relation == "same_tx":
                same_tx_candidates.append(candidate)
        same_pool_candidates.sort(key=lambda item: (item.event_time, item.event_id), reverse=True)
        other_pool_candidates.sort(key=lambda item: (item.event_time, item.event_id), reverse=True)
        candidate_events = same_tx_candidates[:10] + same_pool_candidates[:10] + other_pool_candidates[:10]
        likely_cause = "missing_pool_lot"
        recommended_action = "Quellimport oder Anfangsbestand fuer den Pool pruefen."
        if same_pool_candidates:
            likely_cause = "unresolved_inbound_transfer_or_opening_balance"
            recommended_action = (
                "Positiven Zufluss im gleichen Pool zur Herkunft zurueckverfolgen; "
                "bei eigenem Transfer muss das Ursprungslot in diesen Pool "
                "fortgeschrieben werden."
            )
        elif other_pool_candidates:
            likely_cause = "possible_cross_pool_transfer_missing_link"
            recommended_action = (
                "Zeitnahen Zufluss in anderem Pool auf interne Umbuchung pruefen "
                "und Transferpaar/Bridge-Beleg herstellen."
            )
        elif disposal_event and str(disposal_event.quote_asset or "").upper() == gap.asset.upper():
            likely_cause = "quote_asset_disposal_without_pool_lot"
            recommended_action = (
                "Trade verbraucht Quote-Asset aus Pool. Herkunft des Quote-Assets "
                "vor dem Trade klaeren."
            )
        return WalletFifoGapDiagnosis(
            gap_id=f"{gap.pool_id}:{gap.asset}:{gap.source_event_id}",
            event_time=gap.event_time,
            pool_id=gap.pool_id,
            asset=gap.asset,
            missing_quantity=gap.missing_quantity,
            disposal_event_id=gap.source_event_id,
            disposal_event_type=gap.event_type,
            reason=gap.reason,
            likely_cause=likely_cause,
            recommended_action=recommended_action,
            candidate_events=candidate_events,
        )

    def _candidate_from_event(
        self,
        event: CanonicalEvent,
        gap: WalletFifoPreviewUnmatched,
        relation: str,
    ) -> WalletFifoGapCandidateEvent:
        seconds_before = None
        if event.event_time <= gap.event_time:
            seconds_before = int((gap.event_time - event.event_time).total_seconds())
        return WalletFifoGapCandidateEvent(
            event_id=event.event_id,
            event_time=event.event_time,
            event_type=event.event_type,
            source=event.source,
            account=event.account,
            pool_id=self._pool_id(event),
            asset=event.asset.upper(),
            quantity=event.quantity,
            quote_asset=event.quote_asset,
            quote_quantity=event.quote_quantity,
            tx_id=event.tx_id,
            source_ref=event.source_ref,
            raw_object_id=event.raw_object_id,
            relation=relation,
            seconds_before_gap=seconds_before,
        )

    @staticmethod
    def _primary_origin_candidate(gap: WalletFifoGapDiagnosis) -> WalletFifoGapCandidateEvent | None:
        priority = {
            "same_pool_prior_positive": 0,
            "other_pool_prior_positive": 1,
            "same_tx": 2,
        }
        candidates = [item for item in gap.candidate_events if item.relation != "gap_event"]
        candidates.sort(key=lambda item: (priority.get(item.relation, 9), item.seconds_before_gap if item.seconds_before_gap is not None else 10**12))
        return candidates[0] if candidates else None

    def _raw_evidence(self, raw_object_id: str) -> WalletFifoOriginRawEvidence | None:
        return self._raw_evidence_map([raw_object_id]).get(raw_object_id)

    def _raw_evidence_map(self, raw_object_ids: list[str | None]) -> dict[str, WalletFifoOriginRawEvidence]:
        ids = sorted({str(raw_id) for raw_id in raw_object_ids if raw_id})
        if not ids:
            return {}
        placeholders = ", ".join(["?"] * len(ids))
        with self.store.connect() as con:
            rows = con.execute(
                f"""
                select r.raw_object_id, r.batch_id, b.source, b.filename, r.row_number, r.payload_json
                from raw_objects r
                left join raw_import_batches b on b.batch_id = r.batch_id
                where r.raw_object_id in ({placeholders})
                """,
                ids,
            ).fetchall()
        return {row[0]: self._evidence_from_row(row) for row in rows}

    def _matching_deposit_history(self, candidate: WalletFifoGapCandidateEvent) -> WalletFifoOriginRawEvidence | None:
        return self._matching_deposit_history_from_rows(candidate, self._deposit_history_candidates())

    def _deposit_history_candidates(self) -> list[WalletFifoOriginRawEvidence]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select r.raw_object_id, r.batch_id, b.source, b.filename, r.row_number, r.payload_json
                from raw_objects r
                left join raw_import_batches b on b.batch_id = r.batch_id
                where lower(b.filename) like '%deposit%'
                   or lower(b.source) like '%deposit%'
                   or lower(r.payload_json) like '%"txid"%'
                """
            ).fetchall()
        return [self._evidence_from_row(row) for row in rows]

    def _deposit_history_index(
        self,
        rows: list[WalletFifoOriginRawEvidence],
    ) -> dict[tuple[str, Decimal], list[WalletFifoOriginRawEvidence]]:
        index: dict[tuple[str, Decimal], list[WalletFifoOriginRawEvidence]] = defaultdict(list)
        for evidence in rows:
            payload = evidence.payload
            asset = str(payload.get("Coin", "")).upper()
            amount = self._payload_decimal(payload, "Amount")
            if asset and amount is not None:
                index[(asset, amount)].append(evidence)
        return index

    def _matching_deposit_history_from_rows(
        self,
        candidate: WalletFifoGapCandidateEvent,
        rows: list[WalletFifoOriginRawEvidence],
        *,
        deposit_history_index: dict[tuple[str, Decimal], list[WalletFifoOriginRawEvidence]] | None = None,
        amount_tolerance: Decimal = Decimal("0.00000001"),
    ) -> WalletFifoOriginRawEvidence | None:
        best: tuple[int, WalletFifoOriginRawEvidence] | None = None
        exact_tolerance = Decimal("0.00000001")
        candidate_amount = abs(candidate.quantity)
        indexed_rows = (
            deposit_history_index.get((candidate.asset.upper(), candidate_amount), [])
            if deposit_history_index is not None
            else []
        )
        candidate_rows = indexed_rows or rows
        for evidence in candidate_rows:
            payload = evidence.payload
            if str(payload.get("Coin", "")).upper() != candidate.asset.upper():
                continue
            amount = self._payload_decimal(payload, "Amount")
            if amount is None:
                continue
            amount_delta = abs(amount - candidate_amount)
            if amount_delta > amount_tolerance:
                continue
            payload_time = str(payload.get("Time", ""))
            if amount_delta > exact_tolerance and candidate.event_time.strftime("%y-%m-%d") not in payload_time:
                continue
            score = 10
            if candidate.event_time.strftime("%y-%m-%d") in payload_time:
                score -= 5
            if amount_delta > exact_tolerance:
                score += 1
            if candidate.tx_id and str(payload.get("TXID", "")) == candidate.tx_id:
                score -= 10
            if best is None or score < best[0]:
                best = (score, evidence)
        return best[1] if best else None

    def _matching_withdrawal_history(self, event: CanonicalEvent) -> WalletFifoOriginRawEvidence | None:
        expected_amount = abs(event.quantity)
        with self.store.connect() as con:
            rows = con.execute(
                """
                select r.raw_object_id, r.batch_id, b.source, b.filename, r.row_number, r.payload_json
                from raw_objects r
                left join raw_import_batches b on b.batch_id = r.batch_id
                where (lower(b.filename) like '%withdraw%' or lower(b.source) like '%withdraw%')
                  and upper(r.payload_json) like ?
                """,
                [f"%{event.asset.upper()}%"],
            ).fetchall()
        best: tuple[float, WalletFifoOriginRawEvidence] | None = None
        for row in rows:
            evidence = self._evidence_from_row(row)
            if not self._withdrawal_amount_matches(evidence.payload, expected_amount):
                continue
            parsed_time = self._parse_binance_time(
                self._payload_str(evidence.payload, "Time")
                or self._payload_str(evidence.payload, "Timestamp UTC+8 (Completion)")
                or self._payload_str(evidence.payload, "Apply Time")
                or self._payload_str(evidence.payload, "apply_time")
                or self._payload_str(evidence.payload, "Complete Time")
                or self._payload_str(evidence.payload, "complete_time")
            )
            delta = abs(((parsed_time or event.event_time).timestamp()) - event.event_time.timestamp())
            if best is None or delta < best[0]:
                best = (delta, evidence)
        return best[1] if best else None

    def _withdrawal_amount_matches(
        self,
        payload: dict[str, object],
        expected_amount: Decimal,
    ) -> bool:
        amount = self._payload_decimal_any(
            payload,
            ("Amount", "amount", "withdraw_amount", "Withdraw Amount", "Quantity"),
        )
        gross = self._payload_decimal_any(payload, ("gross_amount", "Gross Amount"))
        fee = self._payload_decimal_any(
            payload,
            ("transactionFee", "transaction_fee", "Transaction Fee", "Withdrawal fee", "withdrawal fee"),
        )
        candidates = [value for value in (amount, gross) if value is not None]
        if amount is not None and fee is not None:
            candidates.append(amount + fee)
        return any(abs(candidate - expected_amount) <= Decimal("0.00000001") for candidate in candidates)

    def _evidence_from_row(self, row: object) -> WalletFifoOriginRawEvidence:
        return WalletFifoOriginRawEvidence(
            raw_object_id=row[0],
            batch_id=row[1],
            source=row[2],
            filename=row[3],
            row_number=row[4],
            payload=self._parse_payload(row[5]),
        )

    @staticmethod
    def _parse_binance_time(value: str | None) -> datetime | None:
        if not value:
            return None
        text = value.strip()
        for fmt in ("%y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
            try:
                parsed = datetime.strptime(text, fmt)
                return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
            except ValueError:
                continue
        return None

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @staticmethod
    def _origin_recommended_action(
        gap: WalletFifoGapDiagnosis,
        deposit_history: WalletFifoOriginRawEvidence | None,
    ) -> str:
        if deposit_history:
            return (
                "Deposit-History mit Adresse/TXID gegen Solscan pruefen. Wenn "
                "die Quelladresse eine eigene Wallet ist, als eigenen Transfer "
                "lot-erhaltend verknuepfen; sonst steuerliche Zuflussart klaeren."
            )
        return gap.recommended_action

    @staticmethod
    def _parse_payload(value: str | None) -> dict[str, str | int | float | None]:
        if not value:
            return {}
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _payload_decimal(payload: dict[str, object], key: str) -> Decimal | None:
        value = payload.get(key)
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except Exception:
            return None

    @classmethod
    def _payload_decimal_any(
        cls,
        payload: dict[str, object],
        keys: tuple[str, ...],
    ) -> Decimal | None:
        for key in keys:
            value = cls._payload_decimal(payload, key)
            if value is not None:
                return value
        return None

    @staticmethod
    def _payload_str(payload: dict[str, object], key: str) -> str | None:
        value = payload.get(key)
        if value in (None, ""):
            return None
        return str(value)

    @staticmethod
    def _positive_asset_quantity(event: CanonicalEvent, asset: str) -> Decimal:
        normalized = asset.upper()
        if event.asset.upper() == normalized and event.quantity > 0:
            return event.quantity
        return Decimal("0")

    def _process_non_transfer_event(
        self,
        event: CanonicalEvent,
        lots_by_pool_asset: defaultdict[tuple[str, str], deque[WalletFifoPreviewLot]],
    ) -> tuple[list[WalletFifoPreviewLot], list[WalletFifoPreviewLine], list[WalletFifoPreviewUnmatched]]:
        pool_id = self._pool_id(event)
        asset = event.asset.upper()
        created_lots: list[WalletFifoPreviewLot] = []
        created_lines: list[WalletFifoPreviewLine] = []
        unmatched: list[WalletFifoPreviewUnmatched] = []
        if not self._is_tax_relevant_event(event):
            return created_lots, created_lines, unmatched
        event_value_eur = self.tax_service._eur_value(event)
        if event.event_type == "trade" and event.quantity > 0:
            lot = self._lot_from_event(event, pool_id, event_value_eur)
            lots_by_pool_asset[(pool_id, asset)].append(lot)
            created_lots.append(lot)
            if self._is_taxable_quote_disposal(event):
                quote_asset = str(event.quote_asset).upper()
                lines, missing = self._consume(
                    event=event,
                    pool_id=pool_id,
                    asset=quote_asset,
                    quantity=abs(event.quote_quantity or Decimal("0")),
                    proceeds_total=event_value_eur,
                    lots=lots_by_pool_asset[(pool_id, quote_asset)],
                    reason="trade_quote_disposal_without_wallet_lot",
                )
                created_lines.extend(lines)
                unmatched.extend(missing)
            return created_lots, created_lines, unmatched
        if event.event_type == "trade" and event.quantity < 0:
            lines, missing = self._consume(
                event=event,
                pool_id=pool_id,
                asset=asset,
                quantity=abs(event.quantity),
                proceeds_total=event_value_eur,
                lots=lots_by_pool_asset[(pool_id, asset)],
                reason="trade_disposal_without_wallet_lot",
            )
            created_lines.extend(lines)
            unmatched.extend(missing)
            if self._is_taxable_quote_acquisition(event):
                lot = self._lot_from_values(
                    pool_id=pool_id,
                    asset=str(event.quote_asset).upper(),
                    acquired_at=event.event_time,
                    quantity=abs(event.quote_quantity or Decimal("0")),
                    cost_basis_eur_total=event_value_eur,
                    source_event_id=event.event_id,
                )
                lots_by_pool_asset[(pool_id, lot.asset)].append(lot)
                created_lots.append(lot)
            return created_lots, created_lines, unmatched
        if event.quantity > 0 and event.event_type in LOT_ACQUISITION_EVENT_TYPES:
            lot = self._lot_from_event(event, pool_id, event_value_eur)
            lots_by_pool_asset[(pool_id, asset)].append(lot)
            created_lots.append(lot)
        return created_lots, created_lines, unmatched

    def _process_transfer_group(
        self,
        events: list[CanonicalEvent],
        lots_by_pool_asset: defaultdict[tuple[str, str], deque[WalletFifoPreviewLot]],
    ) -> tuple[list[WalletFifoTransferTrace], list[WalletFifoPreviewUnmatched]]:
        traces: list[WalletFifoTransferTrace] = []
        unmatched: list[WalletFifoPreviewUnmatched] = []
        by_asset: defaultdict[str, list[CanonicalEvent]] = defaultdict(list)
        for event in events:
            if event.event_type == "transfer" and event.asset.upper() not in FIAT_TAX_EXCLUDED_ASSETS:
                by_asset[event.asset.upper()].append(event)
        for asset, asset_events in by_asset.items():
            outgoing = [event for event in asset_events if event.quantity < 0]
            incoming = [event for event in asset_events if event.quantity > 0]
            if not outgoing or not incoming:
                continue
            source_event = outgoing[0]
            target_event = incoming[0]
            quantity = min(abs(source_event.quantity), target_event.quantity)
            source_pool = self._pool_id(source_event)
            target_pool = self._pool_id(target_event)
            moved_lots, missing = self._move_lots(
                source_event=source_event,
                target_event=target_event,
                asset=asset,
                quantity=quantity,
                source_lots=lots_by_pool_asset[(source_pool, asset)],
                target_lots=lots_by_pool_asset[(target_pool, asset)],
            )
            unmatched.extend(missing)
            traces.append(
                WalletFifoTransferTrace(
                    tx_id=str(source_event.tx_id),
                    asset=asset,
                    event_time=max(source_event.event_time, target_event.event_time),
                    source_pool_id=source_pool,
                    target_pool_id=target_pool,
                    quantity=quantity,
                    lots_moved=len(moved_lots),
                    carried_cost_basis_eur=sum((lot.cost_basis_eur_total for lot in moved_lots), Decimal("0")),
                    status="ok" if not missing else "partial",
                    source_event_id=source_event.event_id,
                    target_event_id=target_event.event_id,
                )
            )
        return traces, unmatched

    def _process_inferred_cross_pool_transfer_target(
        self,
        *,
        target_event: CanonicalEvent,
        candidate_events: list[CanonicalEvent],
        lots_by_pool_asset: defaultdict[tuple[str, str], deque[WalletFifoPreviewLot]],
    ) -> tuple[list[WalletFifoTransferTrace], list[WalletFifoPreviewUnmatched]]:
        asset = target_event.asset.upper()
        target_quantity = target_event.quantity
        if target_quantity <= 0 or asset in FIAT_TAX_EXCLUDED_ASSETS:
            return [], []
        target_pool = self._pool_id(target_event)
        source_event = self._inferred_cross_pool_source_event(
            target_event=target_event,
            candidate_events=candidate_events,
            lots_by_pool_asset=lots_by_pool_asset,
        )
        if source_event is None:
            return [], []
        source_pool = self._pool_id(source_event)
        moved_lots, missing = self._move_lots(
            source_event=CanonicalEvent(
                event_id=f"inferred:{source_event.event_id}:source",
                source=source_event.source,
                event_time=source_event.event_time,
                event_type="transfer",
                asset=asset,
                quantity=-target_quantity,
                tx_id=target_event.tx_id or source_event.tx_id,
                account=source_event.account,
                wallet=source_event.wallet,
                source_ref=source_event.source_ref,
                raw_object_id=source_event.raw_object_id,
                confidence=Decimal("1"),
            ),
            target_event=target_event,
            asset=asset,
            quantity=target_quantity,
            source_lots=lots_by_pool_asset[(source_pool, asset)],
            target_lots=lots_by_pool_asset[(target_pool, asset)],
        )
        return [
            WalletFifoTransferTrace(
                tx_id=str(target_event.tx_id or source_event.tx_id or f"inferred:{source_event.event_id}:{target_event.event_id}"),
                asset=asset,
                event_time=target_event.event_time,
                source_pool_id=source_pool,
                target_pool_id=target_pool,
                quantity=target_quantity,
                lots_moved=len(moved_lots),
                carried_cost_basis_eur=sum((lot.cost_basis_eur_total for lot in moved_lots), Decimal("0")),
                status="inferred_cross_pool" if not missing else "inferred_cross_pool_partial",
                source_event_id=source_event.event_id,
                target_event_id=target_event.event_id,
            )
        ], missing

    def _inferred_cross_pool_source_event(
        self,
        *,
        target_event: CanonicalEvent,
        candidate_events: list[CanonicalEvent],
        lots_by_pool_asset: defaultdict[tuple[str, str], deque[WalletFifoPreviewLot]],
    ) -> CanonicalEvent | None:
        asset = target_event.asset.upper()
        target_pool = self._pool_id(target_event)
        target_time = self._as_utc(target_event.event_time)
        window_start = target_time - timedelta(days=180)
        candidates: list[tuple[int, int, CanonicalEvent]] = []
        for event in candidate_events:
            if event.event_id == target_event.event_id:
                continue
            if event.asset.upper() != asset or event.quantity <= 0:
                continue
            event_time = self._as_utc(event.event_time)
            if not (window_start <= event_time <= target_time):
                continue
            source_pool = self._pool_id(event)
            if source_pool == target_pool:
                continue
            amount_delta = abs(event.quantity - target_event.quantity)
            if amount_delta > self._transfer_match_tolerance(asset):
                continue
            available = sum((lot.quantity_remaining for lot in lots_by_pool_asset[(source_pool, asset)]), Decimal("0"))
            if available < target_event.quantity:
                continue
            same_source_penalty = 0 if event.source == target_event.source else 50
            tx_penalty = 0 if event.tx_id and target_event.tx_id and event.tx_id == target_event.tx_id else 10
            seconds = int((target_time - event_time).total_seconds())
            candidates.append((same_source_penalty + tx_penalty, seconds, event))
        if not candidates:
            return None
        candidates.sort(key=lambda item: (item[0], item[1], item[2].event_id))
        return candidates[0][2]

    @staticmethod
    def _transfer_match_tolerance(asset: str) -> Decimal:
        if asset.upper() in {"BTC", "WBTC"}:
            return Decimal("0.00000001")
        return Decimal("0.000001")

    def _process_unresolved_inbound_transfer(
        self,
        *,
        event: CanonicalEvent,
        lots_by_pool_asset: defaultdict[tuple[str, str], deque[WalletFifoPreviewLot]],
    ) -> tuple[WalletFifoPreviewLot, WalletFifoTransferTrace]:
        asset = event.asset.upper()
        pool_id = self._pool_id(event)
        event_value_eur = self.tax_service._eur_value(event)
        lot = self._lot_from_values(
            pool_id=pool_id,
            asset=asset,
            acquired_at=event.event_time,
            quantity=event.quantity,
            cost_basis_eur_total=event_value_eur,
            source_event_id=event.event_id,
        )
        lots_by_pool_asset[(pool_id, asset)].append(lot)
        trace = WalletFifoTransferTrace(
            tx_id=str(event.tx_id or f"unresolved:{event.event_id}"),
            asset=asset,
            event_time=event.event_time,
            source_pool_id="unresolved_inbound_provenance",
            target_pool_id=pool_id,
            quantity=event.quantity,
            lots_moved=1,
            carried_cost_basis_eur=event_value_eur,
            status="unresolved_inbound_provenance",
            source_event_id=f"unresolved:{event.event_id}:source",
            target_event_id=event.event_id,
        )
        return lot, trace

    def _move_lots(
        self,
        *,
        source_event: CanonicalEvent,
        target_event: CanonicalEvent,
        asset: str,
        quantity: Decimal,
        source_lots: deque[WalletFifoPreviewLot],
        target_lots: deque[WalletFifoPreviewLot],
    ) -> tuple[list[WalletFifoPreviewLot], list[WalletFifoPreviewUnmatched]]:
        quantity_to_move = quantity
        moved: list[WalletFifoPreviewLot] = []
        unmatched: list[WalletFifoPreviewUnmatched] = []
        available_before = sum((lot.quantity_remaining for lot in source_lots), Decimal("0"))
        while quantity_to_move > 0:
            if not source_lots:
                unmatched.append(
                    WalletFifoPreviewUnmatched(
                        source_event_id=source_event.event_id,
                        event_time=source_event.event_time,
                        event_type=source_event.event_type,
                        pool_id=self._pool_id(source_event),
                        asset=asset,
                        quantity=quantity,
                        matched_quantity=quantity - quantity_to_move,
                        missing_quantity=quantity_to_move,
                        reason=f"transfer_source_pool_missing_lot_available_{available_before}",
                    )
                )
                break
            source_lot = source_lots[0]
            used_quantity = min(quantity_to_move, source_lot.quantity_remaining)
            ratio = used_quantity / source_lot.quantity_total if source_lot.quantity_total else Decimal("0")
            carried_basis = source_lot.cost_basis_eur_total * ratio
            source_lot.quantity_remaining -= used_quantity
            target_lot = self._lot_from_values(
                pool_id=self._pool_id(target_event),
                asset=asset,
                acquired_at=source_lot.acquired_at,
                quantity=used_quantity,
                cost_basis_eur_total=carried_basis,
                source_event_id=source_lot.source_event_id,
                origin_lot_id=source_lot.origin_lot_id or source_lot.lot_id,
            )
            target_lots.append(target_lot)
            moved.append(target_lot)
            quantity_to_move -= used_quantity
            if source_lot.quantity_remaining == 0:
                source_lots.popleft()
        return moved, unmatched

    def _consume(
        self,
        *,
        event: CanonicalEvent,
        pool_id: str,
        asset: str,
        quantity: Decimal,
        proceeds_total: Decimal,
        lots: deque[WalletFifoPreviewLot],
        reason: str,
    ) -> tuple[list[WalletFifoPreviewLine], list[WalletFifoPreviewUnmatched]]:
        quantity_to_sell = quantity
        created: list[WalletFifoPreviewLine] = []
        unmatched: list[WalletFifoPreviewUnmatched] = []
        available_before = sum((lot.quantity_remaining for lot in lots), Decimal("0"))
        while quantity_to_sell > 0:
            if not lots:
                unmatched.append(
                    WalletFifoPreviewUnmatched(
                        source_event_id=event.event_id,
                        event_time=event.event_time,
                        event_type=event.event_type,
                        pool_id=pool_id,
                        asset=asset,
                        quantity=quantity,
                        matched_quantity=quantity - quantity_to_sell,
                        missing_quantity=quantity_to_sell,
                        reason=f"{reason}_available_{available_before}",
                    )
                )
                break
            lot = lots[0]
            used_quantity = min(quantity_to_sell, lot.quantity_remaining)
            lot_ratio = used_quantity / lot.quantity_total if lot.quantity_total else Decimal("0")
            acquisition_cost = lot.cost_basis_eur_total * lot_ratio
            proceeds = proceeds_total * (used_quantity / quantity) if quantity else Decimal("0")
            remaining = lot.quantity_remaining - used_quantity
            lot.quantity_remaining = remaining
            created.append(
                WalletFifoPreviewLine(
                    tax_line_id=str(uuid4()),
                    pool_id=pool_id,
                    asset=asset,
                    acquired_at=lot.acquired_at,
                    disposed_at=event.event_time,
                    quantity=used_quantity,
                    acquisition_cost_eur=acquisition_cost,
                    disposal_proceeds_eur=proceeds,
                    gain_loss_eur=proceeds - acquisition_cost,
                    holding_days=(event.event_time.date() - lot.acquired_at.date()).days,
                    source_event_id=event.event_id,
                    lot_id=lot.lot_id,
                )
            )
            quantity_to_sell -= used_quantity
            if lot.quantity_remaining == 0:
                lots.popleft()
        return created, unmatched

    def _year_deltas(
        self,
        global_lines: list[TaxLine],
        wallet_lines: list[WalletFifoPreviewLine],
    ) -> list[WalletFifoYearDelta]:
        global_totals: defaultdict[tuple[int, str], tuple[Decimal, int]] = defaultdict(lambda: (Decimal("0"), 0))
        wallet_totals: defaultdict[tuple[int, str, str], tuple[Decimal, int]] = defaultdict(lambda: (Decimal("0"), 0))
        for line in global_lines:
            key = (line.disposed_at.year, line.asset.upper())
            total, count = global_totals[key]
            global_totals[key] = (total + line.gain_loss_eur, count + 1)
        for line in wallet_lines:
            key = (line.disposed_at.year, line.asset.upper(), line.pool_id)
            total, count = wallet_totals[key]
            wallet_totals[key] = (total + line.gain_loss_eur, count + 1)
        years_assets = {(year, asset) for year, asset in global_totals}
        years_assets.update((year, asset) for year, asset, _pool in wallet_totals)
        deltas: list[WalletFifoYearDelta] = []
        for year, asset in sorted(years_assets):
            global_gain, global_count = global_totals[(year, asset)]
            pool_items = [(pool, values) for (item_year, item_asset, pool), values in wallet_totals.items() if item_year == year and item_asset == asset]
            if not pool_items:
                deltas.append(
                    WalletFifoYearDelta(
                        year=year,
                        asset=asset,
                        global_gain_loss_eur=global_gain,
                        wallet_gain_loss_eur=Decimal("0"),
                        delta_eur=-global_gain,
                        global_tax_lines_count=global_count,
                    )
                )
                continue
            wallet_asset_gain = sum((values[0] for _pool, values in pool_items), Decimal("0"))
            wallet_asset_count = sum((values[1] for _pool, values in pool_items), 0)
            deltas.append(
                WalletFifoYearDelta(
                    year=year,
                    asset=asset,
                    global_gain_loss_eur=global_gain,
                    wallet_gain_loss_eur=wallet_asset_gain,
                    delta_eur=wallet_asset_gain - global_gain,
                    global_tax_lines_count=global_count,
                    wallet_tax_lines_count=wallet_asset_count,
                )
            )
        return deltas

    def _lot_from_event(self, event: CanonicalEvent, pool_id: str, cost_basis: Decimal) -> WalletFifoPreviewLot:
        return self._lot_from_values(
            pool_id=pool_id,
            asset=event.asset.upper(),
            acquired_at=event.event_time,
            quantity=event.quantity,
            cost_basis_eur_total=cost_basis,
            source_event_id=event.event_id,
        )

    def _lot_from_values(
        self,
        *,
        pool_id: str,
        asset: str,
        acquired_at: datetime,
        quantity: Decimal,
        cost_basis_eur_total: Decimal,
        source_event_id: str,
        origin_lot_id: str | None = None,
    ) -> WalletFifoPreviewLot:
        return WalletFifoPreviewLot(
            lot_id=str(uuid4()),
            pool_id=pool_id,
            asset=asset.upper(),
            acquired_at=acquired_at,
            quantity_total=quantity,
            quantity_remaining=quantity,
            cost_basis_eur_total=cost_basis_eur_total,
            source_event_id=source_event_id,
            origin_lot_id=origin_lot_id,
        )

    def _grouped_transfer_ids(self, events: list[CanonicalEvent]) -> set[str]:
        result: set[str] = set()
        by_tx = self._events_by_tx(events)
        for tx_id, tx_events in by_tx.items():
            transfer_events = [event for event in tx_events if event.event_type == "transfer"]
            assets = {event.asset.upper() for event in transfer_events}
            for asset in assets:
                asset_events = [event for event in transfer_events if event.asset.upper() == asset]
                if any(event.quantity < 0 for event in asset_events) and any(event.quantity > 0 for event in asset_events):
                    result.add(tx_id)
        return result

    @staticmethod
    def _events_by_tx(events: list[CanonicalEvent]) -> dict[str, list[CanonicalEvent]]:
        grouped: defaultdict[str, list[CanonicalEvent]] = defaultdict(list)
        for event in events:
            if event.tx_id:
                grouped[str(event.tx_id)].append(event)
        return dict(grouped)

    @staticmethod
    def _pool_id(event: CanonicalEvent) -> str:
        value = event.account or event.wallet or event.source
        return f"{event.source}:{value}".replace(" ", "_")

    @staticmethod
    def _is_tax_relevant_event(event: CanonicalEvent) -> bool:
        if event.event_type in LOT_ACQUISITION_EVENT_TYPES:
            return True
        return event.quantity > 0 and event.quote_asset is not None and event.quote_quantity is not None

    @staticmethod
    def _is_taxable_quote_disposal(event: CanonicalEvent) -> bool:
        return (
            event.quote_asset is not None
            and event.quote_quantity is not None
            and event.quote_asset.upper() not in FIAT_TAX_EXCLUDED_ASSETS
            and event.quote_quantity != 0
        )

    @staticmethod
    def _is_taxable_quote_acquisition(event: CanonicalEvent) -> bool:
        return (
            event.quote_asset is not None
            and event.quote_quantity is not None
            and event.quote_asset.upper() not in FIAT_TAX_EXCLUDED_ASSETS
            and event.quote_quantity != 0
        )

    @staticmethod
    def _new_lots_for_trace(
        trace: WalletFifoTransferTrace,
        lots_by_pool_asset: defaultdict[tuple[str, str], deque[WalletFifoPreviewLot]],
    ) -> list[WalletFifoPreviewLot]:
        return [
            lot
            for lot in lots_by_pool_asset[(trace.target_pool_id, trace.asset)]
            if lot.origin_lot_id is not None
        ]
