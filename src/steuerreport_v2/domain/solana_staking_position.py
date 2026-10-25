from __future__ import annotations

from steuerreport_v2.private_settings import private_config_path

import csv
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
from uuid import UUID

from steuerreport_v2.contracts.solana_staking_position import (
    SolanaStakingPositionDecisionLayer,
    SolanaStakingPositionReconciliationReport,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService
from steuerreport_v2.domain.valuation import PriceCoverageService


class SolanaStakingPositionReconciliationService:
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    DEFAULT_CONFIG_PATH = (
        private_config_path('solana_staking_position_reconciliations.json')
    )
    DEFAULT_LATEST_WALLET_FIFO_PATH = (
        PROJECT_ROOT / "var/wallet_fifo_runs/latest_wallet_fifo_run.json"
    )

    def __init__(
        self,
        store: DuckDbStore,
        *,
        config_path: Path | None = None,
        latest_wallet_fifo_path: Path | None = None,
        program_settlement_evidence_dir: Path | None = None,
    ) -> None:
        self.store = store
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self.latest_wallet_fifo_path = (
            latest_wallet_fifo_path or self.DEFAULT_LATEST_WALLET_FIFO_PATH
        )
        self.program_settlement_evidence_dir = program_settlement_evidence_dir

    def report(self) -> SolanaStakingPositionReconciliationReport:
        methodology = (
            "SHA-, Event- und Program-gebundener Nachweis einer Solana-Staking-"
            "Position. Der urspruengliche Principal wird mit Anschaffungsdatum "
            "und Kostenbasis fortgefuehrt. Nur die Ruecklauf-Mehrmenge wird als "
            "Reward zum tagesgenauen EUR-Preis erfasst. Ein gleichzeitiger "
            "nativer SOL-Zufluss gilt nur bei exakter Lamport-Reconciliation als "
            "Rueckzahlung der Programmkonto-Miete."
        )
        errors: list[str] = []
        try:
            config = json.loads(self.config_path.read_text(encoding="utf-8"))
            position = config["positions"][0]
            outbound_config = position["principal_outbound"]
            return_config = position["position_return"]
            native_config = position["native_settlement"]
        except (KeyError, IndexError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return self._error_report(methodology, f"config_read_failed:{exc}")
        wallet = str(position["wallet"])
        asset = str(position["asset"]).upper()
        principal = self._decimal(return_config["principal_quantity"])
        received = self._decimal(return_config["received_quantity"])
        expected_reward = self._decimal(return_config["reward_quantity"])
        outbound = self._event(str(outbound_config["event_id"]))
        return_events = self._events_by_tx(
            str(return_config["tx_id"]),
            asset=asset,
            wallet=wallet,
        )
        principal_events = [event for event in return_events if event[2] == "transfer"]
        reward_events = [event for event in return_events if event[2] == "reward"]
        principal_event = principal_events[0] if len(principal_events) == 1 else None
        reward_event = reward_events[0] if len(reward_events) == 1 else None
        reward_event_id = str(reward_event[0]) if reward_event else None
        reward_lot_ids, reward_lot_quantity, reward_income = self._reward_lots(
            reward_event_id
        )
        (
            wallet_run_id,
            fifo_lots_moved,
            fifo_cost_basis,
            fifo_ready,
        ) = self._wallet_fifo_state(
            tx_id=str(return_config["tx_id"]),
            asset=asset,
            source_event_id=str(outbound_config["event_id"]),
            target_event_id=str(principal_event[0]) if principal_event else "",
            quantity=principal,
            errors=errors,
        )
        settlement_report = WalletFifoPreviewService(
            self.store,
            program_settlement_evidence_dir=self.program_settlement_evidence_dir,
        ).solana_program_settlement_evidence_latest(int(position.get("year") or 2026))
        settlement_record = next(
            (
                record
                for record in settlement_report.records
                if record.event_id == str(native_config["event_id"])
            ),
            None,
        )
        outbound_event_bound = bool(
            outbound
            and str(outbound[0]) == str(outbound_config["event_id"])
            and str(outbound[2]) == "transfer"
            and str(outbound[3]).upper() == asset
            and self._decimal(outbound[4]) == -self._decimal(outbound_config["quantity"])
            and str(outbound[5]) == str(outbound_config["tx_id"])
            and str(outbound[7]) == str(outbound_config["source_file_hash"])
        )
        return_event_bound = bool(
            principal_event
            and self._decimal(principal_event[4]) == principal
            and str(principal_event[5]) == str(return_config["tx_id"])
            and str(principal_event[7]) == str(return_config["source_file_hash"])
        )
        reward_split_bound = bool(
            reward_event
            and self._decimal(reward_event[4]) == expected_reward
            and str(reward_event[5]) == str(return_config["tx_id"])
            and str(reward_event[7]) == str(return_config["source_file_hash"])
        )
        raw_text = " ".join(
            str(event[6] or "") for event in [outbound, principal_event] if event
        )
        program_route_bound = str(position["program_id"]) in raw_text
        quantity_equation = bool(
            self._decimal(outbound_config["quantity"]) == principal
            and principal + expected_reward == received
        )
        canonical_balance_preserved = bool(
            principal_event
            and reward_event
            and self._decimal(principal_event[4]) + self._decimal(reward_event[4])
            == received
        )
        deterministic_ids = bool(
            outbound
            and principal_event
            and reward_event
            and all(
                self._is_uuid5(event[0])
                for event in (outbound, principal_event, reward_event)
            )
        )
        reward_price_ready = not any(
            item.asset.upper() == asset
            and item.year == int(position.get("year") or 2026)
            and item.event_type == "reward"
            for item in PriceCoverageService(self.store).report().missing
        )
        reward_lot_bound = bool(
            reward_event_id
            and len(reward_lot_ids) == 1
            and reward_lot_quantity == expected_reward
            and reward_income > 0
            and reward_price_ready
        )
        native_settlement_bound = bool(
            settlement_report.strict_ready
            and settlement_report.semantic_sha256
            == str(native_config["evidence_semantic_sha256"])
            and settlement_record is not None
            and settlement_record.quantity == self._decimal(native_config["quantity"])
            and settlement_record.exact_lamport_reconciliation
        )
        decision = SolanaStakingPositionDecisionLayer(
            config_approved=config.get("review_status") == "approved_evidence_overlay",
            outbound_event_bound=outbound_event_bound,
            return_event_bound=return_event_bound,
            reward_split_bound=reward_split_bound,
            program_route_bound=program_route_bound,
            quantity_equation_reconciles=quantity_equation,
            canonical_balance_effect_preserved=canonical_balance_preserved,
            deterministic_event_ids_bound=deterministic_ids,
            wallet_fifo_principal_carry_complete=fifo_ready,
            reward_tax_lot_and_price_bound=reward_lot_bound,
            native_rent_settlement_bound=native_settlement_bound,
        )
        strict_ready = all(decision.model_dump().values()) and not errors
        semantic_sha = hashlib.sha256(
            json.dumps(
                {
                    "decision_layer": decision.model_dump(mode="json"),
                    "outbound_event_id": outbound_config["event_id"],
                    "principal_return_event_id": principal_event[0]
                    if principal_event
                    else None,
                    "reward_event_id": reward_event_id,
                    "principal_quantity": str(principal),
                    "reward_quantity": str(expected_reward),
                    "reward_income_eur": str(reward_income),
                    "wallet_fifo_run_id": wallet_run_id,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return SolanaStakingPositionReconciliationReport(
            generated_at=datetime.now(timezone.utc),
            status="ready" if strict_ready else "review_required",
            strict_ready=strict_ready,
            reconciliation_id=str(position["reconciliation_id"]),
            year=int(position.get("year") or 2026),
            wallet=wallet,
            program_id=str(position["program_id"]),
            asset=asset,
            mint=str(position["mint"]),
            outbound_event_id=str(outbound[0]) if outbound else None,
            principal_return_event_id=str(principal_event[0])
            if principal_event
            else None,
            reward_event_id=reward_event_id,
            native_settlement_event_id=str(native_config["event_id"]),
            principal_quantity=principal,
            received_quantity=received,
            reward_quantity=expected_reward,
            reward_income_eur=reward_income,
            reward_lot_ids=reward_lot_ids,
            wallet_fifo_run_id=wallet_run_id,
            wallet_fifo_lots_moved=fifo_lots_moved,
            wallet_fifo_carried_cost_basis_eur=fifo_cost_basis,
            native_settlement_quantity=self._decimal(native_config["quantity"]),
            decision_layer=decision,
            evidence_refs=[str(value) for value in position.get("evidence_refs", [])],
            errors=errors,
            semantic_sha256=semantic_sha,
            methodology=methodology,
        )

    def _event(self, event_id: str) -> tuple[object, ...] | None:
        with self.store.connect() as con:
            return con.execute(
                """
                select e.event_id, e.event_time, e.event_type, e.asset, e.quantity,
                       e.tx_id, r.payload_json, b.file_hash
                from canonical_events e
                join raw_objects r using(raw_object_id)
                join raw_import_batches b using(batch_id)
                where e.event_id = ?
                """,
                [event_id],
            ).fetchone()

    def _events_by_tx(
        self,
        tx_id: str,
        *,
        asset: str,
        wallet: str,
    ) -> list[tuple[object, ...]]:
        with self.store.connect() as con:
            return con.execute(
                """
                select e.event_id, e.event_time, e.event_type, e.asset, e.quantity,
                       e.tx_id, r.payload_json, b.file_hash
                from canonical_events e
                join raw_objects r using(raw_object_id)
                join raw_import_batches b using(batch_id)
                where e.tx_id = ? and upper(e.asset) = ? and e.account = ?
                order by e.event_type, e.event_id
                """,
                [tx_id, asset, wallet],
            ).fetchall()

    def _reward_lots(self, event_id: str | None) -> tuple[list[str], Decimal, Decimal]:
        if event_id is None:
            return [], Decimal("0"), Decimal("0")
        with self.store.connect() as con:
            rows = con.execute(
                """
                select lot_id, quantity_total, cost_basis_eur_total
                from tax_lots where source_event_id = ? order by lot_id
                """,
                [event_id],
            ).fetchall()
        return (
            [str(row[0]) for row in rows],
            sum((self._decimal(row[1]) for row in rows), Decimal("0")),
            sum((self._decimal(row[2]) for row in rows), Decimal("0")),
        )

    def _wallet_fifo_state(
        self,
        *,
        tx_id: str,
        asset: str,
        source_event_id: str,
        target_event_id: str,
        quantity: Decimal,
        errors: list[str],
    ) -> tuple[str | None, int, Decimal, bool]:
        try:
            run = json.loads(self.latest_wallet_fifo_path.read_text(encoding="utf-8"))
            meta = next(
                item
                for item in run.get("evidence_files", [])
                if item.get("kind") == "wallet_fifo_transfer_traces"
            )
            trace_path = Path(str(meta["path"]))
            if not trace_path.is_absolute():
                trace_path = self.PROJECT_ROOT / trace_path
            if hashlib.sha256(trace_path.read_bytes()).hexdigest() != str(meta["sha256"]):
                errors.append("wallet_fifo_trace_sha256_mismatch")
            with gzip.open(trace_path, "rt", encoding="utf-8", newline="") as handle:
                traces = list(csv.DictReader(handle))
        except (OSError, ValueError, StopIteration, TypeError, json.JSONDecodeError) as exc:
            errors.append(f"wallet_fifo_load_failed:{exc}")
            return None, 0, Decimal("0"), False
        candidates = [
            row
            for row in traces
            if row.get("tx_id") == tx_id
            and str(row.get("asset") or "").upper() == asset
            and row.get("status") == "solana_defi_position_principal_return"
            and row.get("source_event_id") == source_event_id
            and row.get("target_event_id") == target_event_id
            and self._decimal(row.get("quantity")) == quantity
        ]
        if len(candidates) != 1:
            return str(run.get("run_id") or "") or None, 0, Decimal("0"), False
        trace = candidates[0]
        lots_moved = int(trace.get("lots_moved") or 0)
        cost_basis = self._decimal(trace.get("carried_cost_basis_eur"))
        return (
            str(run.get("run_id") or "") or None,
            lots_moved,
            cost_basis,
            lots_moved > 0 and cost_basis > 0,
        )

    @staticmethod
    def _decimal(value: object) -> Decimal:
        return Decimal(str(value or "0"))

    @staticmethod
    def _is_uuid5(value: object) -> bool:
        try:
            return UUID(str(value)).version == 5
        except ValueError:
            return False

    def _error_report(
        self,
        methodology: str,
        error: str,
    ) -> SolanaStakingPositionReconciliationReport:
        return SolanaStakingPositionReconciliationReport(
            generated_at=datetime.now(timezone.utc),
            status="not_available",
            reconciliation_id="",
            year=2026,
            wallet="",
            program_id="",
            asset="",
            mint="",
            decision_layer=SolanaStakingPositionDecisionLayer(),
            errors=[error],
            semantic_sha256=hashlib.sha256(b"{}").hexdigest(),
            methodology=methodology,
        )
