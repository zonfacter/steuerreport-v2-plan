from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path

from steuerreport_v2.contracts.pionex_reconciliation import (
    PionexHntReconciliationDecisionLayer,
    PionexHntReconciliationReport,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore


class PionexHntReconciliationService:
    DEFAULT_CONFIG_PATH = Path(
        "/workspace/steuerreport-v2-plan/configs/pionex_hnt_reconciliation.json"
    )
    DEFAULT_SOURCE_DIR = Path("/workspace/steuerreport/usertransfer/pionex")
    EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

    def __init__(
        self,
        store: DuckDbStore,
        *,
        config_path: Path | None = None,
        source_dir: Path | None = None,
    ) -> None:
        self.store = store
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self.source_dir = source_dir or self.DEFAULT_SOURCE_DIR

    def report(self) -> PionexHntReconciliationReport:
        methodology = (
            "SHA-gebundene Pionex-HNT-Reconciliation. Ausgefuehrte Teilfills "
            "bleiben auch bei spaeterem Orderstatus CANCELED steuerlich erhalten. "
            "Die nicht mehr aus der Pionex-API beschaffbare Mindestmenge wird "
            "unmittelbar vor dem ersten Fehlbestand als dokumentierter, "
            "konservativer 0-EUR-Anschaffungslot gefuehrt. Damit wird weder ein "
            "externer Deposit noch ein Reward behauptet. Der fehlende originale "
            "Anschaffungsbeleg bleibt ausdruecklich als BMF-Caveat sichtbar."
        )
        try:
            config = json.loads(self.config_path.read_text(encoding="utf-8"))
            if int(config.get("schema_version") or 0) != 1:
                raise ValueError("invalid_schema_version")
            source_config = config["source_files"]
            raw_config = source_config["raw_trading_details"]
            summary_config = source_config["trading_summary"]
            canceled_config = config["executed_canceled_partials"]
            probe_config = config["historical_api_probe"]
            adjustment_config = config["adjustment"]
            adjusted_balance_config = config["adjusted_balance"]
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return self._error_report(
                methodology=methodology,
                error=f"config_read_failed:{exc}",
            )

        errors: list[str] = []
        raw_path = self.source_dir / str(raw_config["filename"])
        summary_path = self.source_dir / str(summary_config["filename"])
        probe_path = self.config_path.parent / str(probe_config["filename"])
        adjustment_path = self.config_path.parent / str(adjustment_config["filename"])
        raw_sha = self._file_sha256(raw_path, errors, "raw_export")
        summary_sha = self._file_sha256(summary_path, errors, "summary_export")
        probe_sha = self._file_sha256(probe_path, errors, "api_probe")
        adjustment_sha = self._file_sha256(
            adjustment_path, errors, "adjustment_csv"
        )
        raw_rows = self._csv_rows(raw_path, errors, "raw_export")
        summary_rows = self._csv_rows(summary_path, errors, "summary_export")
        raw_aggregate = self._trade_aggregate(raw_rows, errors, "raw_export")
        summary_aggregate = self._trade_aggregate(
            summary_rows, errors, "summary_export"
        )
        account = str(config.get("account") or "pionex")
        asset = str(config.get("asset") or "HNT").upper()
        canceled_rows = [
            row
            for row in raw_rows
            if str(row.get("state") or "").strip().upper() == "CANCELED"
            and self._decimal(row.get("executed_qty")) != 0
        ]
        canceled_buy_quantity = sum(
            (
                self._decimal(row.get("executed_qty"))
                for row in canceled_rows
                if str(row.get("symbol") or "").upper().startswith(f"{asset}_")
                and str(row.get("side") or "").upper() == "BUY"
            ),
            Decimal("0"),
        )
        canceled_sell_quantity = sum(
            (
                self._decimal(row.get("executed_qty"))
                for row in canceled_rows
                if str(row.get("symbol") or "").upper().startswith(f"{asset}_")
                and str(row.get("side") or "").upper() == "SELL"
            ),
            Decimal("0"),
        )
        canceled_base_fee = sum(
            (
                self._decimal(row.get("fee"))
                for row in canceled_rows
                if str(row.get("fee_coin") or "").upper() == asset
            ),
            Decimal("0"),
        )
        canceled_net = (
            canceled_buy_quantity - canceled_base_fee - canceled_sell_quantity
        )
        probe_payload = self._json_payload(probe_path, errors, "api_probe")
        historical_api_rows = int(probe_payload.get("rows_count") or 0)
        deficit_event_time = self._datetime(config.get("deficit_event_time"))
        adjustment_event_time = self._datetime(adjustment_config.get("event_time"))
        adjustment_quantity = self._decimal(adjustment_config.get("quantity"))
        adjustment_cost_basis = self._decimal(
            adjustment_config.get("cost_basis_eur_total")
        )
        expected_balance_min = self._decimal(
            adjusted_balance_config.get("minimum_quantity")
        )
        expected_balance_final = self._decimal(
            adjusted_balance_config.get("final_quantity")
        )

        imported_raw_objects, imported_canceled_events = self._database_import_counts(
            filename=str(raw_config["filename"]),
            file_hash=f"sha256:{raw_config['sha256']}",
        )
        adjustment_events = self._adjustment_event_ids(
            account=account,
            asset=asset,
            adjustment=adjustment_config,
        )
        adjustment_event_id = (
            adjustment_events[0] if len(adjustment_events) == 1 else None
        )
        balance_min, balance_final = self._balance_state(account=account, asset=asset)
        (
            zero_cost_lot_ids,
            zero_cost_consumed,
            zero_cost_proceeds,
            zero_cost_gain,
            zero_cost_remaining,
        ) = self._zero_cost_lot_state(adjustment_event_id)

        source_files_integrity_valid = bool(
            raw_sha == str(raw_config["sha256"])
            and summary_sha == str(summary_config["sha256"])
            and probe_sha == str(probe_config["sha256"])
            and adjustment_sha == str(adjustment_config["sha256"])
        )
        source_exports_reconcile = bool(
            len(raw_rows) == int(raw_config["rows"])
            and len(summary_rows) == int(summary_config["rows"])
            and len(raw_aggregate) == int(source_config["aggregate_groups"])
            and raw_aggregate == summary_aggregate
        )
        executed_canceled_partials_complete = bool(
            len(canceled_rows) == int(canceled_config["count"])
            and canceled_buy_quantity
            == self._decimal(canceled_config["buy_quantity"])
            and canceled_sell_quantity
            == self._decimal(canceled_config["sell_quantity"])
            and canceled_base_fee
            == self._decimal(canceled_config["base_fee_quantity"])
            and canceled_net == self._decimal(canceled_config["net_quantity"])
        )
        historical_api_exhausted = bool(
            probe_payload.get("status") == "success"
            and probe_payload.get("history_available") is False
            and historical_api_rows == int(probe_config["expected_rows"])
            and probe_payload.get("contains_credentials") is False
        )
        database_primary_import_complete = bool(
            imported_raw_objects == int(raw_config["rows"])
            and imported_canceled_events == int(canceled_config["count"])
        )
        adjustment_event_bound = bool(len(adjustment_events) == 1)
        balance_reconciles = bool(
            balance_min == expected_balance_min
            and balance_final == expected_balance_final
        )
        zero_cost_tax_lot_bound = bool(
            adjustment_event_id
            and len(zero_cost_lot_ids) == 1
            and zero_cost_consumed == adjustment_quantity
            and zero_cost_remaining == 0
        )
        tax_treatment_explicit = bool(
            adjustment_config.get("tax_treatment")
            == "conservative_zero_cost_basis_missing_primary_acquisition_evidence"
            and adjustment_config.get("classification")
            == "documented_minimum_inventory_reconciliation"
            and adjustment_config.get("asserts_external_deposit") is False
            and adjustment_config.get("asserts_reward") is False
            and adjustment_cost_basis == 0
            and str(adjustment_config.get("quote_asset") or "").upper() == "EUR"
            and self._decimal(adjustment_config.get("quote_quantity")) == 0
        )
        decision = PionexHntReconciliationDecisionLayer(
            config_enabled=config.get("enabled") is True,
            source_files_integrity_valid=source_files_integrity_valid,
            source_exports_reconcile=source_exports_reconcile,
            executed_canceled_partials_complete=executed_canceled_partials_complete,
            historical_api_exhausted=historical_api_exhausted,
            database_primary_import_complete=database_primary_import_complete,
            adjustment_event_bound=adjustment_event_bound,
            balance_reconciles=balance_reconciles,
            zero_cost_tax_lot_bound=zero_cost_tax_lot_bound,
            tax_treatment_explicit=tax_treatment_explicit,
        )
        preflight_ready = all(
            (
                decision.config_enabled,
                decision.source_files_integrity_valid,
                decision.source_exports_reconcile,
                decision.executed_canceled_partials_complete,
                decision.historical_api_exhausted,
                decision.tax_treatment_explicit,
            )
        )
        reconciliation_ready = preflight_ready and all(
            (
                decision.database_primary_import_complete,
                decision.adjustment_event_bound,
                decision.balance_reconciles,
                decision.zero_cost_tax_lot_bound,
            )
        )
        status = (
            "conservative_reconciliation_ready"
            if reconciliation_ready
            else "ready_to_apply"
            if preflight_ready
            else "review_required"
        )
        return PionexHntReconciliationReport(
            generated_at=datetime.now(timezone.utc),
            status=status,
            preflight_ready=preflight_ready,
            reconciliation_ready=reconciliation_ready,
            wallet_fifo_ready=reconciliation_ready,
            strict_ready=False,
            missing_primary_acquisition_evidence=True,
            config_path=str(self.config_path),
            source_dir=str(self.source_dir),
            api_probe_path=str(probe_path),
            raw_export_sha256=raw_sha,
            summary_export_sha256=summary_sha,
            api_probe_sha256=probe_sha,
            raw_export_rows=len(raw_rows),
            summary_export_rows=len(summary_rows),
            aggregate_groups=len(raw_aggregate),
            canceled_partial_fills_count=len(canceled_rows),
            canceled_buy_quantity=canceled_buy_quantity,
            canceled_sell_quantity=canceled_sell_quantity,
            canceled_base_fee_quantity=canceled_base_fee,
            canceled_net_quantity=canceled_net,
            imported_raw_objects=imported_raw_objects,
            imported_canceled_events=imported_canceled_events,
            account=account,
            asset=asset,
            deficit_event_time=deficit_event_time,
            adjustment_event_time=adjustment_event_time,
            adjustment_quantity=adjustment_quantity,
            adjustment_cost_basis_eur=adjustment_cost_basis,
            adjustment_event_id=adjustment_event_id,
            balance_min_quantity=balance_min,
            balance_final_quantity=balance_final,
            expected_balance_min_quantity=expected_balance_min,
            expected_balance_final_quantity=expected_balance_final,
            zero_cost_lot_ids=zero_cost_lot_ids,
            zero_cost_lot_consumed_quantity=zero_cost_consumed,
            zero_cost_lot_proceeds_eur=zero_cost_proceeds,
            zero_cost_lot_gain_loss_eur=zero_cost_gain,
            historical_api_rows=historical_api_rows,
            decision_layer=decision,
            evidence_refs=[str(value) for value in config.get("evidence_refs", [])],
            errors=errors,
            methodology=methodology,
        )

    def approved_zero_cost_event_ids(self) -> set[str]:
        report = self.report()
        if not report.reconciliation_ready or report.adjustment_event_id is None:
            return set()
        return {report.adjustment_event_id}

    def _database_import_counts(self, *, filename: str, file_hash: str) -> tuple[int, int]:
        with self.store.connect() as con:
            row = con.execute(
                """
                select count(r.raw_object_id)
                from raw_import_batches b
                left join raw_objects r using(batch_id)
                where lower(b.source) = 'pionex'
                  and b.filename = ?
                  and b.file_hash = ?
                """,
                [filename, file_hash],
            ).fetchone()
            canceled = con.execute(
                """
                select count(*)
                from canonical_events e
                join raw_objects r using(raw_object_id)
                join raw_import_batches b using(batch_id)
                where lower(e.source) = 'pionex'
                  and b.filename = ?
                  and upper(json_extract_string(r.payload_json, '$.state')) = 'CANCELED'
                  and abs(e.quantity) > 0
                """,
                [filename],
            ).fetchone()
        return int(row[0] if row else 0), int(canceled[0] if canceled else 0)

    def _balance_state(
        self, *, account: str, asset: str
    ) -> tuple[Decimal | None, Decimal | None]:
        with self.store.connect() as con:
            row = con.execute(
                """
                select min(balance_quantity),
                       max_by(balance_quantity, (event_time, ledger_id))
                from balance_ledger
                where lower(account) = lower(?) and upper(asset) = upper(?)
                """,
                [account, asset],
            ).fetchone()
        if row is None or row[0] is None:
            return None, None
        return Decimal(str(row[0])), Decimal(str(row[1]))

    def _adjustment_event_ids(
        self,
        *,
        account: str,
        asset: str,
        adjustment: dict[str, object],
    ) -> list[str]:
        event_time = self._datetime(adjustment["event_time"]).replace(tzinfo=None)
        with self.store.connect() as con:
            rows = con.execute(
                """
                select event_id
                from canonical_events
                where lower(source) = lower(?)
                  and event_type = 'transfer'
                  and upper(asset) = upper(?)
                  and quantity = ?
                  and lower(coalesce(account, '')) = lower(?)
                  and event_time = ?
                  and upper(coalesce(quote_asset, '')) = upper(?)
                  and quote_quantity = ?
                  and coalesce(tx_id, '') = ?
                order by event_id
                """,
                [
                    str(adjustment["source"]),
                    asset,
                    self._decimal(adjustment["quantity"]),
                    account,
                    event_time,
                    str(adjustment["quote_asset"]),
                    self._decimal(adjustment["quote_quantity"]),
                    str(adjustment["tx_id"]),
                ],
            ).fetchall()
        return [str(row[0]) for row in rows]

    def _zero_cost_lot_state(
        self, event_id: str | None
    ) -> tuple[list[str], Decimal, Decimal, Decimal, Decimal]:
        if event_id is None:
            return [], Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")
        with self.store.connect() as con:
            rows = con.execute(
                """
                select lot.lot_id,
                       lot.quantity_remaining,
                       coalesce(sum(line.quantity), 0),
                       coalesce(sum(line.disposal_proceeds_eur), 0),
                       coalesce(sum(line.gain_loss_eur), 0)
                from tax_lots lot
                left join tax_lines line on line.lot_id = lot.lot_id
                where lot.source_event_id = ?
                  and lot.cost_basis_eur_total = 0
                group by lot.lot_id, lot.quantity_remaining
                order by lot.lot_id
                """,
                [event_id],
            ).fetchall()
        return (
            [str(row[0]) for row in rows],
            sum((Decimal(str(row[2])) for row in rows), Decimal("0")),
            sum((Decimal(str(row[3])) for row in rows), Decimal("0")),
            sum((Decimal(str(row[4])) for row in rows), Decimal("0")),
            sum((Decimal(str(row[1])) for row in rows), Decimal("0")),
        )

    @staticmethod
    def _trade_aggregate(
        rows: list[dict[str, str]], errors: list[str], label: str
    ) -> dict[tuple[str, str, str], tuple[Decimal, Decimal, Decimal]]:
        totals: defaultdict[tuple[str, str, str], list[Decimal]] = defaultdict(
            lambda: [Decimal("0"), Decimal("0"), Decimal("0")]
        )
        required = {"tax_id", "symbol", "side", "executed_qty", "amount", "fee"}
        for row in rows:
            if not required <= set(row):
                errors.append(f"{label}_columns_missing")
                return {}
            key = (
                str(row.get("tax_id") or ""),
                str(row.get("symbol") or "").upper(),
                str(row.get("side") or "").upper(),
            )
            totals[key][0] += PionexHntReconciliationService._decimal(
                row.get("executed_qty")
            )
            totals[key][1] += PionexHntReconciliationService._decimal(
                row.get("amount")
            )
            totals[key][2] += PionexHntReconciliationService._decimal(row.get("fee"))
        return {key: tuple(values) for key, values in totals.items()}

    @staticmethod
    def _csv_rows(
        path: Path, errors: list[str], label: str
    ) -> list[dict[str, str]]:
        try:
            with path.open(newline="", encoding="utf-8-sig") as handle:
                return [dict(row) for row in csv.DictReader(handle)]
        except (OSError, csv.Error) as exc:
            errors.append(f"{label}_read_failed:{exc}")
            return []

    @staticmethod
    def _json_payload(path: Path, errors: list[str], label: str) -> dict[str, object]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{label}_read_failed:{exc}")
            return {}
        if not isinstance(payload, dict):
            errors.append(f"{label}_not_object")
            return {}
        return payload

    @staticmethod
    def _file_sha256(path: Path, errors: list[str], label: str) -> str:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError as exc:
            errors.append(f"{label}_hash_failed:{exc}")
            return ""

    @staticmethod
    def _decimal(value: object) -> Decimal:
        if value in (None, ""):
            return Decimal("0")
        try:
            return Decimal(str(value).replace(",", "."))
        except InvalidOperation:
            return Decimal("0")

    @staticmethod
    def _datetime(value: object) -> datetime:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _error_report(
        self, *, methodology: str, error: str
    ) -> PionexHntReconciliationReport:
        return PionexHntReconciliationReport(
            generated_at=datetime.now(timezone.utc),
            status="not_available",
            config_path=str(self.config_path),
            source_dir=str(self.source_dir),
            api_probe_path="",
            account="pionex",
            asset="HNT",
            deficit_event_time=self.EPOCH,
            adjustment_event_time=self.EPOCH,
            adjustment_quantity=Decimal("0"),
            adjustment_cost_basis_eur=Decimal("0"),
            expected_balance_min_quantity=Decimal("0"),
            expected_balance_final_quantity=Decimal("0"),
            decision_layer=PionexHntReconciliationDecisionLayer(),
            errors=[error],
            methodology=methodology,
        )
