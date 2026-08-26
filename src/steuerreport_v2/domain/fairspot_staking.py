from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import gzip
import hashlib
import json
from pathlib import Path
from uuid import UUID

from steuerreport_v2.contracts.fairspot_staking import (
    FairspotStakingDecisionLayer,
    FairspotStakingReconciliationReport,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore


class FairspotStakingReconciliationService:
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs/fairspot_hnt_staking_reconciliation.json"
    DEFAULT_INDEPENDENT_SOURCE_PATH = (
        PROJECT_ROOT
        / "var/fairspot_staking_reconciliation/latest_fairspot_staking_source.csv"
    )
    DEFAULT_LATEST_WALLET_FIFO_PATH = (
        PROJECT_ROOT / "var/wallet_fifo_runs/latest_wallet_fifo_run.json"
    )
    QUANTITY_TOLERANCE = Decimal("0.0000001")

    def __init__(
        self,
        store: DuckDbStore,
        *,
        config_path: Path | None = None,
        independent_source_path: Path | None = None,
        latest_wallet_fifo_path: Path | None = None,
    ) -> None:
        self.store = store
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self.independent_source_path = (
            independent_source_path or self.DEFAULT_INDEPENDENT_SOURCE_PATH
        )
        self.latest_wallet_fifo_path = (
            latest_wallet_fifo_path or self.DEFAULT_LATEST_WALLET_FIFO_PATH
        )

    def report(self) -> FairspotStakingReconciliationReport:
        methodology = (
            "SHA-gebundener Fairspot-/Helium-Staking-Abgleich. Sieben belegte "
            "Main-Wallet-Ausgaenge werden gegen zwei Ruecklaeufe abgegrenzt. "
            "Der Principal bleibt ein steuerneutraler eigener Transferpfad mit "
            "fortgefuehrten FIFO-Lots; ausschliesslich die belegte Mehrmenge "
            "wird als HNT-Reward zum Zuflusszeitpunkt und dessen EUR-Wert "
            "normalisiert. Die historische Staking-Adresse bleibt aus dem "
            "aktuellen Portfolio ausgeschlossen."
        )
        errors: list[str] = []
        try:
            config = json.loads(self.config_path.read_text(encoding="utf-8"))
            primary = config["primary_source"]
            independent = config["independent_source"]
            outbound_tx_ids = {str(value) for value in config["principal_outbound_tx_ids"]}
            return_tx_ids = {str(value) for value in config["principal_return_tx_ids"]}
            main_wallet = str(config["main_wallet"])
            staking_wallet = str(config["staking_wallet"])
            expected_outbound = self._decimal(config["principal_outbound_quantity"])
            expected_principal_return = self._decimal(config["principal_return_quantity"])
            expected_received = self._decimal(config["total_received_quantity"])
            expected_reward = self._decimal(config["reward_quantity"])
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return self._error_report(methodology, f"config_read_failed:{exc}")

        independent_sha = self._sha256(self.independent_source_path, errors)
        independent_rows = self._csv_rows(self.independent_source_path, errors)
        independent_outbound_rows = [
            row
            for row in independent_rows
            if self._clean(row.get("payer")) == main_wallet
            and self._clean(row.get("payee")) == staking_wallet
        ]
        independent_return_rows = [
            row
            for row in independent_rows
            if self._clean(row.get("payer")) == staking_wallet
            and self._clean(row.get("payee")) == main_wallet
        ]
        independent_outbound = sum(
            (self._decimal(row.get("hnt_amount")) for row in independent_outbound_rows),
            Decimal("0"),
        )
        independent_received = sum(
            (self._decimal(row.get("hnt_amount")) for row in independent_return_rows),
            Decimal("0"),
        )
        events, primary_hashes = self._canonical_events(
            primary_file_hash=str(primary["file_hash"]),
            main_wallet=main_wallet,
            outbound_tx_ids=outbound_tx_ids,
            return_tx_ids=return_tx_ids,
        )
        outbound_events = [
            event
            for event in events
            if event[2] == "transfer"
            and event[4] < 0
            and event[6] in outbound_tx_ids
        ]
        return_events = [
            event
            for event in events
            if event[2] == "transfer"
            and event[4] > 0
            and event[6] in return_tx_ids
        ]
        reward_events = [
            event
            for event in events
            if event[2] == "reward"
            and event[4] > 0
            and event[6] in return_tx_ids
        ]
        principal_outbound = sum((abs(event[4]) for event in outbound_events), Decimal("0"))
        principal_return = sum((event[4] for event in return_events), Decimal("0"))
        reward_quantity = sum((event[4] for event in reward_events), Decimal("0"))
        total_received = principal_return + reward_quantity
        reward_event_id = reward_events[0][0] if len(reward_events) == 1 else None
        reward_lot_ids, reward_lot_quantity, reward_income = self._reward_lots(
            reward_event_id
        )
        wallet_run_id, fifo_outbound, fifo_return, fifo_ready = self._wallet_fifo_state(
            staking_wallet=staking_wallet,
            expected_outbound=expected_outbound,
            expected_principal_return=expected_principal_return,
            errors=errors,
        )
        primary_hash = next(iter(primary_hashes), "") if len(primary_hashes) == 1 else ""
        config_approved = config.get("review_status") == "approved_evidence_overlay"
        primary_source_hash_bound = primary_hash == str(primary["file_hash"])
        independent_source_hash_bound = independent_sha == str(independent["sha256"])
        independent_routes_complete = bool(
            len(independent_outbound_rows) == len(outbound_tx_ids)
            and len(independent_return_rows) == len(return_tx_ids)
            and self._close(independent_outbound, expected_outbound)
            and self._close(independent_received, expected_received)
        )
        quantity_equation_reconciles = bool(
            expected_outbound == expected_principal_return
            and expected_principal_return + expected_reward == expected_received
            and self._close(
                independent_received - independent_outbound,
                expected_reward,
            )
        )
        canonical_split_bound = bool(
            len(outbound_events) == len(outbound_tx_ids)
            and len(return_events) == len(return_tx_ids)
            and len(reward_events) == 1
            and principal_outbound == expected_outbound
            and principal_return == expected_principal_return
            and reward_quantity == expected_reward
        )
        canonical_balance_preserved = bool(
            total_received == expected_received
            and total_received - principal_outbound == expected_reward
        )
        deterministic_ids = bool(events) and all(self._is_uuid5(event[0]) for event in events)
        reward_tax_lot_bound = bool(
            reward_event_id
            and len(reward_lot_ids) == 1
            and reward_lot_quantity == expected_reward
            and reward_income > 0
        )
        decision = FairspotStakingDecisionLayer(
            config_approved=config_approved,
            primary_source_hash_bound=primary_source_hash_bound,
            independent_source_hash_bound=independent_source_hash_bound,
            independent_routes_complete=independent_routes_complete,
            quantity_equation_reconciles=quantity_equation_reconciles,
            canonical_principal_reward_split_bound=canonical_split_bound,
            canonical_balance_effect_preserved=canonical_balance_preserved,
            deterministic_event_ids_bound=deterministic_ids,
            wallet_fifo_principal_carry_complete=fifo_ready,
            reward_tax_lot_bound=reward_tax_lot_bound,
        )
        strict_ready = all(decision.model_dump().values()) and not errors
        semantic_sha = self._semantic_sha(
            decision=decision,
            principal_outbound=principal_outbound,
            principal_return=principal_return,
            reward_quantity=reward_quantity,
            reward_income=reward_income,
            reward_event_id=reward_event_id,
            wallet_run_id=wallet_run_id,
        )
        return FairspotStakingReconciliationReport(
            generated_at=datetime.now(timezone.utc),
            status="ready" if strict_ready else "review_required",
            strict_ready=strict_ready,
            config_path=str(self.config_path),
            independent_source_path=str(self.independent_source_path),
            primary_source_sha256=primary_hash,
            independent_source_sha256=independent_sha,
            main_wallet=main_wallet,
            staking_wallet=staking_wallet,
            outbound_events_count=len(outbound_events),
            return_events_count=len(return_events),
            reward_events_count=len(reward_events),
            principal_outbound_quantity=principal_outbound,
            principal_return_quantity=principal_return,
            total_received_quantity=total_received,
            reward_quantity=reward_quantity,
            independent_principal_outbound_quantity=independent_outbound,
            independent_total_received_quantity=independent_received,
            reward_income_eur=reward_income,
            reward_event_id=reward_event_id,
            reward_lot_ids=reward_lot_ids,
            source_run_id=wallet_run_id,
            decision_layer=decision,
            evidence_refs=[str(value) for value in config.get("evidence_refs", [])],
            errors=errors,
            semantic_sha256=semantic_sha,
            methodology=methodology,
        )

    def _canonical_events(
        self,
        *,
        primary_file_hash: str,
        main_wallet: str,
        outbound_tx_ids: set[str],
        return_tx_ids: set[str],
    ) -> tuple[list[tuple[object, ...]], set[str]]:
        tx_ids = sorted(outbound_tx_ids | return_tx_ids)
        if not tx_ids:
            return [], set()
        placeholders = ",".join("?" for _ in tx_ids)
        with self.store.connect() as con:
            rows = con.execute(
                f"""
                select e.event_id, e.event_time, e.event_type, e.asset,
                       e.quantity, e.account, e.tx_id, b.file_hash
                from canonical_events e
                join raw_objects r using(raw_object_id)
                join raw_import_batches b using(batch_id)
                where b.file_hash = ?
                  and e.account = ?
                  and upper(e.asset) = 'HNT'
                  and e.tx_id in ({placeholders})
                order by e.event_time, e.event_type, e.event_id
                """,
                [primary_file_hash, main_wallet, *tx_ids],
            ).fetchall()
        return rows, {str(row[7]) for row in rows}

    def _reward_lots(self, event_id: str | None) -> tuple[list[str], Decimal, Decimal]:
        if event_id is None:
            return [], Decimal("0"), Decimal("0")
        with self.store.connect() as con:
            rows = con.execute(
                """
                select lot_id, quantity_total, cost_basis_eur_total
                from tax_lots
                where source_event_id = ? and upper(asset) = 'HNT'
                order by lot_id
                """,
                [event_id],
            ).fetchall()
        return (
            [str(row[0]) for row in rows],
            sum((Decimal(str(row[1])) for row in rows), Decimal("0")),
            sum((Decimal(str(row[2])) for row in rows), Decimal("0")),
        )

    def _wallet_fifo_state(
        self,
        *,
        staking_wallet: str,
        expected_outbound: Decimal,
        expected_principal_return: Decimal,
        errors: list[str],
    ) -> tuple[str | None, Decimal, Decimal, bool]:
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
            return None, Decimal("0"), Decimal("0"), False
        pool_fragment = f"helium_counterparty:{staking_wallet}"
        outbound = [
            row
            for row in traces
            if row.get("target_pool_id") == pool_fragment
            and row.get("status") == "known_staking_counterparty_outbound"
        ]
        returns = [
            row
            for row in traces
            if row.get("source_pool_id") == pool_fragment
            and row.get("status") == "known_staking_counterparty_return"
        ]
        outbound_quantity = sum(
            (self._decimal(row.get("quantity")) for row in outbound), Decimal("0")
        )
        return_quantity = sum(
            (self._decimal(row.get("quantity")) for row in returns), Decimal("0")
        )
        ready = bool(
            outbound_quantity == expected_outbound
            and return_quantity == expected_principal_return
            and outbound
            and returns
            and all(int(row.get("lots_moved") or 0) > 0 for row in outbound + returns)
        )
        return str(run.get("run_id") or "") or None, outbound_quantity, return_quantity, ready

    @staticmethod
    def _csv_rows(path: Path, errors: list[str]) -> list[dict[str, str]]:
        try:
            with path.open("r", encoding="utf-8", newline="") as handle:
                return list(csv.DictReader(handle))
        except OSError as exc:
            errors.append(f"independent_source_read_failed:{exc}")
            return []

    @staticmethod
    def _sha256(path: Path, errors: list[str]) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            errors.append(f"independent_source_hash_failed:{exc}")
            return ""

    @staticmethod
    def _decimal(value: object) -> Decimal:
        try:
            return Decimal(str(value or "0").strip().replace(",", "."))
        except InvalidOperation:
            return Decimal("0")

    @staticmethod
    def _clean(value: object) -> str:
        return str(value or "").replace("\u00a0", "").strip()

    def _close(self, actual: Decimal, expected: Decimal) -> bool:
        return abs(actual - expected) <= self.QUANTITY_TOLERANCE

    @staticmethod
    def _is_uuid5(value: object) -> bool:
        try:
            return UUID(str(value)).version == 5
        except ValueError:
            return False

    @staticmethod
    def _semantic_sha(
        *,
        decision: FairspotStakingDecisionLayer,
        principal_outbound: Decimal,
        principal_return: Decimal,
        reward_quantity: Decimal,
        reward_income: Decimal,
        reward_event_id: str | None,
        wallet_run_id: str | None,
    ) -> str:
        payload = {
            "decision_layer": decision.model_dump(mode="json"),
            "principal_outbound": str(principal_outbound),
            "principal_return": str(principal_return),
            "reward_quantity": str(reward_quantity),
            "reward_income": str(reward_income),
            "reward_event_id": reward_event_id,
            "wallet_run_id": wallet_run_id,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def _error_report(
        self,
        methodology: str,
        error: str,
    ) -> FairspotStakingReconciliationReport:
        return FairspotStakingReconciliationReport(
            generated_at=datetime.now(timezone.utc),
            status="not_available",
            config_path=str(self.config_path),
            independent_source_path=str(self.independent_source_path),
            main_wallet="",
            staking_wallet="",
            decision_layer=FairspotStakingDecisionLayer(),
            errors=[error],
            semantic_sha256=hashlib.sha256(b"{}").hexdigest(),
            methodology=methodology,
        )
