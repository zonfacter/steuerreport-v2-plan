from __future__ import annotations

from datetime import date, datetime, time, timezone
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx

from steuerreport_v2.contracts.divorce_service_routes import (
    DivorceServiceRouteAcceptedDecision,
    DivorceServiceRouteDecisionLayer,
    DivorceServiceRouteDecisionRequest,
    DivorceServiceRouteDecisionResult,
    DivorceServiceRouteEvidenceBundle,
    DivorceServiceRouteEvidenceFile,
    DivorceServiceRouteEvidenceRefreshRequest,
    DivorceServiceRouteEvidenceReport,
    DivorceServiceRouteLifecycleRow,
)
from steuerreport_v2.contracts.events import CanonicalEvent
from steuerreport_v2.contracts.review import ReviewDecision, ReviewDecisionCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup
from steuerreport_v2.domain.source_registry import SourceRegistryService


class DivorceServiceRouteEvidenceService:
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT / "var/divorce_service_route_evidence"
    DEFAULT_RPC_URL = "https://api.mainnet-beta.solana.com"
    JUPITER_PERPS_PROGRAM_ID = "PERPHjGBqRHArX4DySjwM6UJHiR3sWAatqfdBS2qQJu"
    OPENING_INSTRUCTION = "InstantIncreasePosition"
    LIQUIDATION_INSTRUCTION = "LiquidateFullPosition4"
    DECISION_TYPE = "divorce_service_route"
    DECISION_STATUS = "internal_service_position_loss_confirmed"
    SOL_LAMPORTS = Decimal("1000000000")
    LOG_SCALE = Decimal("1000000")

    def __init__(
        self,
        store: DuckDbStore,
        *,
        artifact_root: Path | None = None,
        registry_path: Path | None = None,
        rpc_url: str = DEFAULT_RPC_URL,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.store = store
        self.artifact_root = artifact_root or self.DEFAULT_ARTIFACT_ROOT
        self.registry_path = registry_path
        self.rpc_url = rpc_url
        self.transport = transport

    def refresh(
        self,
        request: DivorceServiceRouteEvidenceRefreshRequest,
    ) -> DivorceServiceRouteEvidenceReport:
        generated_at = datetime.now(timezone.utc)
        errors: list[str] = []
        event = self._canonical_event(request.tx_id)
        wallet = (event.account or event.wallet or "").strip() if event else ""
        wallet_source_id = self._owned_wallet_source_id(
            wallet, event.event_time if event else None
        )
        end_at = self._day_end_utc(request.end_asset_date)
        run_dir = self.artifact_root / (
            f"route-{generated_at.strftime('%Y%m%dT%H%M%S%fZ')}-"
            f"{request.tx_id[:12]}-{uuid4().hex[:8]}"
        )
        run_dir.mkdir(parents=True, exist_ok=False)
        evidence_files: list[DivorceServiceRouteEvidenceFile] = []
        opening_payload: dict[str, Any] = {}
        signatures_payload: dict[str, Any] = {}
        liquidation_payload: dict[str, Any] = {}
        lifecycle: list[DivorceServiceRouteLifecycleRow] = []

        if event is None:
            errors.append("canonical_negative_sol_event_not_found")
        if event is not None and not wallet:
            errors.append("canonical_wallet_missing")
        if wallet and wallet_source_id is None:
            errors.append("wallet_not_owned_in_source_registry")

        try:
            with httpx.Client(
                timeout=request.timeout_seconds,
                transport=self.transport,
                headers={"user-agent": "steuerreport-v2/0.1"},
            ) as client:
                opening_payload = self._rpc(
                    client,
                    "getTransaction",
                    [
                        request.tx_id,
                        {
                            "encoding": "jsonParsed",
                            "maxSupportedTransactionVersion": 0,
                        },
                    ],
                )
                evidence_files.append(
                    self._write_rpc_evidence(
                        run_dir,
                        "opening_get_transaction",
                        opening_payload,
                    )
                )
                opening = self._parse_opening(opening_payload, wallet)
                position_account = str(opening.get("position_account") or "")
                if not position_account:
                    errors.append("jupiter_perps_position_account_not_found")
                    signatures = []
                else:
                    signatures_payload = self._rpc(
                        client,
                        "getSignaturesForAddress",
                        [position_account, {"limit": 1000}],
                    )
                    evidence_files.append(
                        self._write_rpc_evidence(
                            run_dir,
                            "position_signatures",
                            signatures_payload,
                        )
                    )
                    signatures = signatures_payload.get("result") or []
                liquidation: dict[str, Any] = {}
                for row in sorted(
                    [item for item in signatures if isinstance(item, dict)],
                    key=lambda item: int(item.get("blockTime") or 0),
                ):
                    signature = str(row.get("signature") or "")
                    block_time = self._block_time(row.get("blockTime"))
                    successful = row.get("err") is None
                    if signature == request.tx_id:
                        lifecycle.append(
                            DivorceServiceRouteLifecycleRow(
                                tx_id=signature,
                                block_time=block_time,
                                slot=self._int(row.get("slot")),
                                successful=successful,
                                instruction=self.OPENING_INSTRUCTION,
                                note="Eigene Wallet erhoeht die Jupiter-Perps-Position.",
                            )
                        )
                        continue
                    if not successful:
                        lifecycle.append(
                            DivorceServiceRouteLifecycleRow(
                                tx_id=signature,
                                block_time=block_time,
                                slot=self._int(row.get("slot")),
                                successful=False,
                                note="Fehlgeschlagene Transaktion; keine Zustandsaenderung.",
                            )
                        )
                        continue
                    if block_time is not None and block_time > end_at:
                        lifecycle.append(
                            DivorceServiceRouteLifecycleRow(
                                tx_id=signature,
                                block_time=block_time,
                                slot=self._int(row.get("slot")),
                                successful=True,
                                note="Erfolgreiche Aktivitaet nach dem angeforderten Endstichtag.",
                            )
                        )
                        continue
                    transaction_payload = self._rpc(
                        client,
                        "getTransaction",
                        [
                            signature,
                            {
                                "encoding": "jsonParsed",
                                "maxSupportedTransactionVersion": 0,
                            },
                        ],
                    )
                    parsed = self._parse_liquidation(
                        transaction_payload,
                        position_account,
                    )
                    instruction = str(parsed.get("instruction") or "") or None
                    lifecycle.append(
                        DivorceServiceRouteLifecycleRow(
                            tx_id=signature,
                            block_time=parsed.get("block_time"),
                            slot=parsed.get("slot"),
                            successful=bool(parsed.get("successful")),
                            instruction=instruction,
                            note=(
                                "Jupiter-Perps-Position wurde vollstaendig liquidiert."
                                if instruction == self.LIQUIDATION_INSTRUCTION
                                else "Erfolgreiche Positionsaktivitaet ohne belegte Vollliquidation."
                            ),
                        )
                    )
                    if instruction == self.LIQUIDATION_INSTRUCTION:
                        liquidation = parsed
                        liquidation_payload = transaction_payload
                if liquidation_payload:
                    evidence_files.append(
                        self._write_rpc_evidence(
                            run_dir,
                            "liquidation_get_transaction",
                            liquidation_payload,
                        )
                    )
        except (httpx.HTTPError, ValueError) as exc:
            errors.append(f"solana_rpc_failed:{exc}")
            opening = self._empty_opening()
            liquidation = {}
            signatures = []

        if "opening" not in locals():
            opening = self._empty_opening()
        if "liquidation" not in locals():
            liquidation = {}
        if "signatures" not in locals():
            signatures = []

        event_lamports = (
            int(abs(event.quantity) * self.SOL_LAMPORTS) if event is not None else None
        )
        opening_block_time = opening.get("block_time")
        wallet_debit = self._int(opening.get("wallet_debit_lamports"))
        collateral_lamports = self._int(opening.get("collateral_lamports"))
        position_rent = self._int(opening.get("position_account_rent_lamports"))
        wrapped_rent_return = self._int(
            opening.get("wrapped_account_rent_return_lamports")
        )
        opening_fee_lamports = self._int(opening.get("fee_lamports"))
        components_reconcile = bool(
            None
            not in {
                wallet_debit,
                collateral_lamports,
                position_rent,
                wrapped_rent_return,
                opening_fee_lamports,
            }
            and wallet_debit
            == collateral_lamports
            + position_rent
            + opening_fee_lamports
            - wrapped_rent_return
        )
        liquidation_block_time = liquidation.get("block_time")
        successful_before_end = [
            item
            for item in lifecycle
            if item.successful
            and item.block_time is not None
            and item.block_time <= end_at
        ]
        successful_after_liquidation = [
            item
            for item in successful_before_end
            if liquidation_block_time is not None
            and item.block_time > liquidation_block_time
        ]
        residual_lamports = self._int(liquidation.get("position_account_post_lamports"))
        residual_quantity = (
            Decimal(residual_lamports) / self.SOL_LAMPORTS
            if residual_lamports is not None
            else None
        )
        price_point = HistoricalPriceLookup(self.store).at_or_before("SOL", end_at)
        residual_value = (
            residual_quantity * price_point.price_eur
            if residual_quantity is not None and price_point is not None
            else None
        )
        collateral_quantity = self._quantity(collateral_lamports)
        collateral_added_usd = self._scaled_log(opening.get("collateral_added_usd_raw"))
        opening_price_usd = self._scaled_log(opening.get("current_price_raw"))
        decision_layer = DivorceServiceRouteDecisionLayer(
            canonical_event_bound=event is not None,
            owned_wallet_registry_bound=wallet_source_id is not None,
            opening_transaction_successful=bool(opening.get("successful")),
            opening_time_matches_event=bool(
                event is not None
                and opening_block_time is not None
                and int(self._as_utc(event.event_time).timestamp())
                == int(opening_block_time.timestamp())
            ),
            owned_wallet_signed_opening=bool(opening.get("wallet_signed")),
            wallet_debit_matches_event=bool(
                event_lamports is not None and wallet_debit == event_lamports
            ),
            wallet_debit_reconciles_components=components_reconcile,
            jupiter_perps_program_bound=bool(opening.get("program_bound")),
            instant_increase_position_bound=bool(opening.get("opening_log_bound")),
            wsol_collateral_transfer_bound=bool(
                collateral_lamports is not None
                and collateral_lamports > 0
                and collateral_lamports == opening.get("system_transfer_lamports")
            ),
            position_account_bound=bool(opening.get("position_account_bound")),
            collateral_log_bound=bool(
                collateral_quantity is not None
                and collateral_added_usd is not None
                and opening_price_usd is not None
                and abs(collateral_added_usd - collateral_quantity * opening_price_usd)
                <= Decimal("0.00001")
            ),
            full_liquidation_before_end_date=bool(
                liquidation.get("successful")
                and liquidation.get("instruction") == self.LIQUIDATION_INSTRUCTION
                and liquidation_block_time is not None
                and liquidation_block_time <= end_at
            ),
            liquidation_position_account_bound=bool(
                liquidation.get("position_account_bound")
            ),
            no_successful_activity_after_liquidation=bool(
                liquidation_block_time is not None
                and not successful_after_liquidation
                and len(signatures) < 1000
            ),
            residual_account_rent_same_day_priced=bool(
                price_point is not None
                and self._as_utc(price_point.priced_at).date() == end_at.date()
            ),
            residual_account_rent_below_materiality=bool(
                residual_value is not None
                and residual_value < request.materiality_threshold_eur
            ),
        )
        strict_ready = all(decision_layer.model_dump().values()) and not errors
        if strict_ready:
            findings = [
                (
                    f"{self._quantity(collateral_lamports)} SOL wurden als Jupiter-Perps-"
                    "Collateral in ein programmverwaltetes Positionskonto uebertragen."
                ),
                (
                    "Die Position wurde vor dem Endstichtag vollstaendig liquidiert; "
                    "danach besteht bis zum Stichtag keine erfolgreiche Positionsaktivitaet."
                ),
                (
                    f"Das verbleibende Programmkonto-Rent von {residual_quantity} SOL "
                    f"ist mit {residual_value} EUR unter der Materialitaetsschwelle."
                ),
                (
                    "Die Entscheidung wirkt ausschliesslich im familienrechtlichen "
                    "Vermoegensfluss. Steuer-, Import-, Ledger- und FIFO-Daten bleiben unveraendert."
                ),
            ]
        else:
            failed_flags = [
                key
                for key, value in decision_layer.model_dump().items()
                if value is not True
            ]
            findings = [
                "Service-Route noch nicht freigabefaehig: " + ", ".join(failed_flags)
            ]
        report_values = {
            "generated_at": generated_at,
            "status": "ready_for_review"
            if strict_ready
            else "failed"
            if errors
            else "review_required",
            "strict_ready": strict_ready,
            "end_asset_date": request.end_asset_date,
            "materiality_threshold_eur": request.materiality_threshold_eur,
            "tx_id": request.tx_id,
            "canonical_event_id": event.event_id if event else None,
            "canonical_event_time": self._as_utc(event.event_time) if event else None,
            "canonical_asset": event.asset if event else None,
            "canonical_quantity": abs(event.quantity) if event else None,
            "wallet": wallet or None,
            "wallet_source_id": wallet_source_id,
            "opening_slot": self._int(opening.get("slot")),
            "opening_block_time": opening_block_time,
            "opening_fee_lamports": opening_fee_lamports,
            "wallet_debit_lamports": wallet_debit,
            "collateral_lamports": collateral_lamports,
            "position_account_rent_lamports": position_rent,
            "wrapped_account_rent_return_lamports": wrapped_rent_return,
            "position_account": opening.get("position_account"),
            "collateral_quantity": collateral_quantity,
            "collateral_added_usd": collateral_added_usd,
            "opening_fee_usd": self._scaled_log(opening.get("collected_fee_raw")),
            "opening_price_usd": opening_price_usd,
            "lifecycle_signatures_count": len(signatures),
            "successful_lifecycle_count": sum(item.successful for item in lifecycle),
            "failed_lifecycle_count": sum(not item.successful for item in lifecycle),
            "liquidation_tx_id": liquidation.get("tx_id"),
            "liquidation_slot": self._int(liquidation.get("slot")),
            "liquidation_block_time": liquidation_block_time,
            "liquidation_instruction": liquidation.get("instruction"),
            "liquidation_exit_price_usd": self._scaled_log(
                liquidation.get("exit_price_raw")
            ),
            "liquidation_fee_usd": self._scaled_log(
                liquidation.get("collected_fee_raw")
            ),
            "liquidation_net_loss_usd": self._scaled_log(
                liquidation.get("net_loss_raw")
            ),
            "residual_position_account_lamports": residual_lamports,
            "residual_position_account_quantity": residual_quantity,
            "residual_position_account_price_eur": (
                price_point.price_eur if price_point is not None else None
            ),
            "residual_position_account_priced_at": (
                self._as_utc(price_point.priced_at) if price_point is not None else None
            ),
            "residual_position_account_price_source": (
                price_point.source if price_point is not None else None
            ),
            "residual_position_account_value_eur": residual_value,
            "decision_layer": decision_layer,
            "lifecycle": lifecycle,
            "evidence_files": evidence_files,
            "artifact_path": self._display_path(run_dir / "service_route_report.json"),
            "semantic_sha256": "",
            "errors": errors,
            "findings": findings,
            "methodology": (
                "TXID- und SHA-gebundener Solana-RPC-Nachweis fuer einen im "
                "Zugewinnreport offenen Jupiter-Perps-Abfluss. Freigabe erfordert "
                "Eigenwallet-Signer, exakte Lamport-Reconciliation, WSOL-Collateral, "
                "programmverwaltetes Positionskonto, InstantIncreasePosition sowie "
                "eine erfolgreiche LiquidateFullPosition4-Transaktion vor dem "
                "Endstichtag ohne spaetere erfolgreiche Positionsaktivitaet. Die "
                "Klassifikation betrifft nur den familienrechtlichen Vermoegensfluss."
            ),
        }
        preliminary = DivorceServiceRouteEvidenceReport(**report_values)
        report = preliminary.model_copy(
            update={"semantic_sha256": self._semantic_digest(preliminary)}
        )
        content = json.dumps(
            report.model_dump(mode="json"), indent=2, ensure_ascii=False
        ).encode("utf-8")
        self._atomic_write(run_dir / "service_route_report.json", content)
        self._atomic_write(self._latest_path(request.tx_id), content)
        return report

    def latest(self, tx_id: str) -> DivorceServiceRouteEvidenceReport | None:
        try:
            report = DivorceServiceRouteEvidenceReport.model_validate_json(
                self._latest_path(tx_id).read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None
        return (
            report if self._semantic_digest(report) == report.semantic_sha256 else None
        )

    def accept(
        self,
        request: DivorceServiceRouteDecisionRequest,
    ) -> DivorceServiceRouteDecisionResult:
        evidence = self.latest(request.tx_id)
        if evidence is None:
            raise ValueError("service_route_evidence_missing")
        if evidence.semantic_sha256 != request.semantic_sha256:
            raise ValueError("service_route_evidence_sha256_mismatch")
        if not evidence.strict_ready:
            raise ValueError("service_route_evidence_not_ready")
        existing = self.accepted_decisions({request.tx_id}).get(request.tx_id)
        if (
            existing is not None
            and existing[1].semantic_sha256 == request.semantic_sha256
        ):
            return DivorceServiceRouteDecisionResult(
                already_recorded=True,
                decision=existing[0],
                evidence=existing[1],
            )
        evidence_ref = f"{evidence.artifact_path}#sha256={evidence.semantic_sha256}"
        decision = self.store.add_review_decision(
            ReviewDecisionCreate(
                decision_type=self.DECISION_TYPE,
                scope=(
                    f"divorce_service_route:txid:{request.tx_id}:"
                    f"semantic:{evidence.semantic_sha256}"
                ),
                title="Jupiter-Perps-Serviceposition im Vermoegensfluss belegen",
                rationale=(
                    str(request.rationale or "").strip()
                    or (
                        "Die eigene Wallet hat 0,2 SOL als Jupiter-Perps-Collateral "
                        "eingezahlt. Die Position wurde vor dem Endstichtag vollstaendig "
                        "liquidiert; es liegt keine externe Auszahlung und kein offener "
                        "Positionswert am Stichtag vor."
                    )
                ),
                evidence_ref=evidence_ref,
                actor=str(request.actor or "user").strip() or "user",
                source="api:/api/v1/divorce/service-route-evidence/decisions",
                affected_ids=[
                    value
                    for value in (
                        evidence.canonical_event_id,
                        evidence.tx_id,
                        evidence.position_account,
                        evidence.liquidation_tx_id,
                    )
                    if value
                ],
                payload={
                    "decision_status": self.DECISION_STATUS,
                    "classification_effect": "divorce_capital_flow_only",
                    "txid": evidence.tx_id,
                    "event_id": evidence.canonical_event_id,
                    "wallet": evidence.wallet,
                    "position_account": evidence.position_account,
                    "liquidation_txid": evidence.liquidation_tx_id,
                    "end_asset_date": evidence.end_asset_date.isoformat(),
                    "collateral_quantity": str(evidence.collateral_quantity),
                    "liquidation_net_loss_usd": str(evidence.liquidation_net_loss_usd),
                    "residual_position_account_value_eur": str(
                        evidence.residual_position_account_value_eur
                    ),
                    "evidence_artifact_path": evidence.artifact_path,
                    "evidence_semantic_sha256": evidence.semantic_sha256,
                    "import_effect": "none",
                    "ledger_effect": "none",
                    "fifo_effect": "none",
                    "tax_classification_effect": "none",
                },
            )
        )
        return DivorceServiceRouteDecisionResult(
            decision=decision,
            evidence=evidence,
        )

    def accepted_decisions(
        self,
        tx_ids: set[str] | None = None,
    ) -> dict[str, tuple[ReviewDecision, DivorceServiceRouteEvidenceReport]]:
        result: dict[str, tuple[ReviewDecision, DivorceServiceRouteEvidenceReport]] = {}
        for decision in self.store.list_review_decisions():
            if decision.decision_type != self.DECISION_TYPE:
                continue
            if decision.payload.get("decision_status") != self.DECISION_STATUS:
                continue
            tx_id = str(decision.payload.get("txid") or "")
            if not tx_id or (tx_ids is not None and tx_id not in tx_ids):
                continue
            if tx_id in result:
                continue
            report = self._report_from_decision(decision)
            if report is not None:
                result[tx_id] = (decision, report)
        return result

    def accepted_reports(
        self,
        tx_ids: set[str] | None = None,
    ) -> list[DivorceServiceRouteEvidenceReport]:
        return [item[1] for item in self.accepted_decisions(tx_ids).values()]

    def accepted_evidence_bundle(
        self,
        tx_ids: set[str] | None = None,
    ) -> DivorceServiceRouteEvidenceBundle:
        accepted = self.accepted_decisions(tx_ids)
        ordered = [accepted[tx_id] for tx_id in sorted(accepted)]
        return DivorceServiceRouteEvidenceBundle(
            generated_at=datetime.now(timezone.utc),
            reports_count=len(ordered),
            reports=[report for _, report in ordered],
            accepted_decisions_count=len(ordered),
            accepted_decisions=[
                DivorceServiceRouteAcceptedDecision(
                    tx_id=report.tx_id,
                    evidence_semantic_sha256=report.semantic_sha256,
                    decision=decision,
                )
                for decision, report in ordered
            ],
        )

    def evidence_path(self, tx_id: str, filename: str) -> Path | None:
        report = self.latest(tx_id)
        if report is None:
            return None
        allowed = {Path(item.path).name: item for item in report.evidence_files}
        item = allowed.get(filename)
        if item is None:
            return None
        path = (self.PROJECT_ROOT / item.path).resolve()
        try:
            path.relative_to(self.artifact_root.resolve())
        except ValueError:
            return None
        if not path.is_file() or self._sha256(path.read_bytes()) != item.sha256:
            return None
        return path

    def _report_from_decision(
        self,
        decision: ReviewDecision,
    ) -> DivorceServiceRouteEvidenceReport | None:
        raw_path = str(decision.payload.get("evidence_artifact_path") or "")
        expected_sha = str(decision.payload.get("evidence_semantic_sha256") or "")
        if not raw_path or not expected_sha:
            return None
        path = (self.PROJECT_ROOT / raw_path).resolve()
        try:
            path.relative_to(self.artifact_root.resolve())
        except ValueError:
            return None
        try:
            report = DivorceServiceRouteEvidenceReport.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None
        if (
            not report.strict_ready
            or report.semantic_sha256 != expected_sha
            or self._semantic_digest(report) != expected_sha
        ):
            return None
        return report

    def _canonical_event(self, tx_id: str) -> CanonicalEvent | None:
        with self.store.connect() as con:
            row = con.execute(
                """
                select event_id, source, source_ref, event_time, event_type,
                       asset, quantity, quote_asset, quote_quantity, fee_asset,
                       fee_quantity, tx_id, wallet, account, confidence,
                       raw_object_id
                from canonical_events
                where tx_id = ? and source = 'solana_rpc' and event_type = 'transfer'
                  and upper(asset) = 'SOL' and quantity < 0
                order by event_time, event_id
                limit 1
                """,
                [tx_id],
            ).fetchone()
        if row is None:
            return None
        return CanonicalEvent(
            event_id=row[0],
            source=row[1],
            source_ref=row[2],
            event_time=row[3],
            event_type=row[4],
            asset=row[5],
            quantity=row[6],
            quote_asset=row[7],
            quote_quantity=row[8],
            fee_asset=row[9],
            fee_quantity=row[10],
            tx_id=row[11],
            wallet=row[12],
            account=row[13],
            confidence=row[14],
            raw_object_id=row[15],
        )

    def _owned_wallet_source_id(
        self,
        wallet: str,
        event_time: datetime | None,
    ) -> str | None:
        if not wallet or event_time is None:
            return None
        try:
            config = SourceRegistryService(
                self.store,
                config_path=self.registry_path,
            ).config()
        except (OSError, ValueError):
            return None
        event_at = self._as_utc(event_time)
        for entry in config.entries:
            if entry.ownership != "owned":
                continue
            if not any(
                item.kind == "account" and item.value == wallet
                for item in entry.identifiers
            ):
                continue
            if event_at < self._as_utc(entry.valid_from):
                continue
            if entry.valid_to is not None and event_at > self._as_utc(entry.valid_to):
                continue
            return entry.source_id
        return None

    def _rpc(
        self,
        client: httpx.Client,
        method: str,
        params: list[object],
    ) -> dict[str, Any]:
        response = client.post(
            self.rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )
        if response.status_code == 429:
            raise ValueError("rpc_http_429")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("rpc_payload_not_object")
        if payload.get("error"):
            raise ValueError(f"rpc_error:{payload['error']}")
        if payload.get("result") is None:
            raise ValueError(f"rpc_result_null:{method}")
        return payload

    def _parse_opening(self, payload: dict[str, Any], wallet: str) -> dict[str, Any]:
        result = (
            payload.get("result") if isinstance(payload.get("result"), dict) else {}
        )
        meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
        transaction = (
            result.get("transaction")
            if isinstance(result.get("transaction"), dict)
            else {}
        )
        message = (
            transaction.get("message")
            if isinstance(transaction.get("message"), dict)
            else {}
        )
        keys = self._account_keys(message)
        instructions = [
            item for item in message.get("instructions") or [] if isinstance(item, dict)
        ]
        inner = [
            item
            for group in meta.get("innerInstructions") or []
            if isinstance(group, dict)
            for item in group.get("instructions") or []
            if isinstance(item, dict)
        ]
        logs = [str(item) for item in meta.get("logMessages") or []]
        wallet_index = next(
            (index for index, item in enumerate(keys) if item["pubkey"] == wallet),
            None,
        )
        pre_balances = meta.get("preBalances") or []
        post_balances = meta.get("postBalances") or []
        wallet_debit = None
        if (
            wallet_index is not None
            and wallet_index < len(pre_balances)
            and wallet_index < len(post_balances)
        ):
            wallet_debit = int(pre_balances[wallet_index]) - int(
                post_balances[wallet_index]
            )
        system_transfer = next(
            (
                item
                for item in instructions
                if item.get("program") == "system"
                and self._parsed_type(item) == "transfer"
                and self._parsed_info(item).get("source") == wallet
            ),
            {},
        )
        wrapped_account = str(
            self._parsed_info(system_transfer).get("destination") or ""
        )
        system_lamports = self._int(self._parsed_info(system_transfer).get("lamports"))
        position_create = next(
            (
                item
                for item in inner
                if self._parsed_type(item) == "createAccount"
                and self._parsed_info(item).get("source") == wallet
                and self._parsed_info(item).get("owner")
                == self.JUPITER_PERPS_PROGRAM_ID
            ),
            {},
        )
        position_account = str(
            self._parsed_info(position_create).get("newAccount") or ""
        )
        position_rent = self._int(self._parsed_info(position_create).get("lamports"))
        collateral_transfer = next(
            (
                item
                for item in inner
                if self._parsed_type(item) == "transfer"
                and self._parsed_info(item).get("source") == wrapped_account
            ),
            {},
        )
        collateral_lamports = self._int(
            self._parsed_info(collateral_transfer).get("amount")
        )
        perps_instruction = next(
            (
                item
                for item in instructions
                if item.get("programId") == self.JUPITER_PERPS_PROGRAM_ID
            ),
            {},
        )
        close_instruction = next(
            (
                item
                for item in instructions
                if self._parsed_type(item) == "closeAccount"
                and self._parsed_info(item).get("account") == wrapped_account
                and self._parsed_info(item).get("destination") == wallet
            ),
            {},
        )
        wrapped_rent_return = None
        wrapped_index = next(
            (
                index
                for index, item in enumerate(keys)
                if item["pubkey"] == wrapped_account
            ),
            None,
        )
        if (
            close_instruction
            and wrapped_index is not None
            and wrapped_index < len(pre_balances)
            and wrapped_index < len(post_balances)
        ):
            wrapped_rent_return = int(pre_balances[wrapped_index]) - int(
                post_balances[wrapped_index]
            )
        return {
            "successful": meta.get("err") is None,
            "slot": result.get("slot"),
            "block_time": self._block_time(result.get("blockTime")),
            "fee_lamports": meta.get("fee"),
            "wallet_signed": any(
                item["pubkey"] == wallet and item["signer"] for item in keys
            ),
            "wallet_debit_lamports": wallet_debit,
            "system_transfer_lamports": system_lamports,
            "collateral_lamports": collateral_lamports,
            "position_account": position_account or None,
            "position_account_rent_lamports": position_rent,
            "wrapped_account_rent_return_lamports": wrapped_rent_return,
            "program_bound": bool(perps_instruction),
            "opening_log_bound": self._has_log_instruction(
                logs, self.OPENING_INSTRUCTION
            ),
            "position_account_bound": bool(
                position_account
                and position_account in (perps_instruction.get("accounts") or [])
            ),
            "collateral_added_usd_raw": self._log_integer(
                logs, "Collateral added in USD"
            ),
            "collected_fee_raw": self._log_integer(logs, "Collected fee"),
            "current_price_raw": self._log_integer(logs, "Current price"),
        }

    def _parse_liquidation(
        self,
        payload: dict[str, Any],
        position_account: str,
    ) -> dict[str, Any]:
        result = (
            payload.get("result") if isinstance(payload.get("result"), dict) else {}
        )
        meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
        transaction = (
            result.get("transaction")
            if isinstance(result.get("transaction"), dict)
            else {}
        )
        message = (
            transaction.get("message")
            if isinstance(transaction.get("message"), dict)
            else {}
        )
        keys = self._account_keys(message)
        logs = [str(item) for item in meta.get("logMessages") or []]
        position_index = next(
            (
                index
                for index, item in enumerate(keys)
                if item["pubkey"] == position_account
            ),
            None,
        )
        post_balances = meta.get("postBalances") or []
        residual_lamports = (
            int(post_balances[position_index])
            if position_index is not None and position_index < len(post_balances)
            else None
        )
        instruction = (
            self.LIQUIDATION_INSTRUCTION
            if self._has_log_instruction(logs, self.LIQUIDATION_INSTRUCTION)
            else None
        )
        signatures = transaction.get("signatures") or []
        return {
            "tx_id": str(signatures[0]) if signatures else None,
            "successful": meta.get("err") is None,
            "slot": result.get("slot"),
            "block_time": self._block_time(result.get("blockTime")),
            "instruction": instruction,
            "position_account_bound": bool(
                position_index is not None
                and any(
                    item.get("programId") == self.JUPITER_PERPS_PROGRAM_ID
                    for item in message.get("instructions") or []
                    if isinstance(item, dict)
                )
            ),
            "position_account_post_lamports": residual_lamports,
            "exit_price_raw": self._log_integer(logs, "Exit price"),
            "collected_fee_raw": self._log_integer(logs, "Collected fee"),
            "net_loss_raw": self._log_integer(logs, "Net loss"),
        }

    def _write_rpc_evidence(
        self,
        run_dir: Path,
        kind: str,
        payload: dict[str, Any],
    ) -> DivorceServiceRouteEvidenceFile:
        raw = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        content = gzip.compress(raw, mtime=0)
        path = run_dir / f"{kind}.json.gz"
        self._atomic_write(path, content)
        return DivorceServiceRouteEvidenceFile(
            kind=kind,
            path=self._display_path(path),
            size_bytes=len(content),
            sha256=self._sha256(content),
        )

    def _semantic_digest(self, report: DivorceServiceRouteEvidenceReport) -> str:
        payload = report.model_dump(
            mode="json",
            exclude={
                "generated_at",
                "status",
                "artifact_path",
                "semantic_sha256",
                "findings",
                "methodology",
                "evidence_files",
            },
        )
        payload["evidence_sha256"] = {
            item.kind: item.sha256 for item in report.evidence_files
        }
        return self._sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        )

    def _latest_path(self, tx_id: str) -> Path:
        safe_tx_id = re.sub(r"[^1-9A-HJ-NP-Za-km-z]", "", tx_id)
        if safe_tx_id != tx_id or not 64 <= len(tx_id) <= 128:
            raise ValueError("invalid_solana_tx_id")
        return self.artifact_root / f"latest_{tx_id}_service_route_report.json"

    @staticmethod
    def _account_keys(message: dict[str, Any]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for item in message.get("accountKeys") or []:
            if isinstance(item, dict):
                result.append(
                    {
                        "pubkey": str(item.get("pubkey") or ""),
                        "signer": bool(item.get("signer")),
                    }
                )
            else:
                result.append({"pubkey": str(item), "signer": False})
        return result

    @staticmethod
    def _parsed_info(instruction: dict[str, Any]) -> dict[str, Any]:
        parsed = instruction.get("parsed")
        if not isinstance(parsed, dict):
            return {}
        info = parsed.get("info")
        return info if isinstance(info, dict) else {}

    @staticmethod
    def _parsed_type(instruction: dict[str, Any]) -> str:
        parsed = instruction.get("parsed")
        return str(parsed.get("type") or "") if isinstance(parsed, dict) else ""

    @staticmethod
    def _has_log_instruction(logs: list[str], instruction: str) -> bool:
        return f"Program log: Instruction: {instruction}" in logs

    @staticmethod
    def _log_integer(logs: list[str], label: str) -> int | None:
        pattern = re.compile(rf"^Program log: {re.escape(label)}: (\d+)$")
        for line in logs:
            match = pattern.match(line)
            if match:
                return int(match.group(1))
        return None

    @classmethod
    def _scaled_log(cls, value: object) -> Decimal | None:
        parsed = cls._int(value)
        return Decimal(parsed) / cls.LOG_SCALE if parsed is not None else None

    @classmethod
    def _quantity(cls, lamports: int | None) -> Decimal | None:
        return Decimal(lamports) / cls.SOL_LAMPORTS if lamports is not None else None

    @staticmethod
    def _int(value: object) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _block_time(value: object) -> datetime | None:
        parsed = DivorceServiceRouteEvidenceService._int(value)
        return (
            datetime.fromtimestamp(parsed, tz=timezone.utc)
            if parsed is not None
            else None
        )

    @staticmethod
    def _day_end_utc(value: date) -> datetime:
        return datetime.combine(
            value,
            time.max,
            tzinfo=ZoneInfo("Europe/Berlin"),
        ).astimezone(timezone.utc)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return (
            value.replace(tzinfo=timezone.utc)
            if value.tzinfo is None
            else value.astimezone(timezone.utc)
        )

    @staticmethod
    def _empty_opening() -> dict[str, Any]:
        return {}

    @staticmethod
    def _sha256(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @classmethod
    def _display_path(cls, path: Path) -> str:
        try:
            return str(path.relative_to(cls.PROJECT_ROOT))
        except ValueError:
            return str(path)

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)
