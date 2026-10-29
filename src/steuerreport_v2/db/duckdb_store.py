from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import duckdb
import pandas as pd

from steuerreport_v2.contracts.admin import AdminSetting, AdminSettingWrite
from steuerreport_v2.contracts.ai import AiTask, AiTaskCreate, AiTaskStatus
from steuerreport_v2.contracts.events import CanonicalEvent, CanonicalEventCreate
from steuerreport_v2.contracts.imports import (
    ImportBatch,
    ImportBatchCreate,
    RawObject,
    RawObjectCreate,
)
from steuerreport_v2.contracts.parity import V1ReferenceMetric, V1ReferenceMetricCreate
from steuerreport_v2.contracts.prices import PricePoint, PricePointCreate
from steuerreport_v2.contracts.review import ReviewDecision, ReviewDecisionCreate
from steuerreport_v2.paths import PROJECT_ROOT

SCHEMA_VERSION = 2


class _LockedDuckDbConnection:
    def __init__(
        self,
        connection: duckdb.DuckDBPyConnection,
        lock: threading.RLock,
    ) -> None:
        self._connection = connection
        self._lock = lock
        self._closed = False

    def __enter__(self) -> "_LockedDuckDbConnection":
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def __getattr__(self, name: str) -> object:
        return getattr(self._connection, name)

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._connection.close()
        finally:
            self._closed = True
            self._lock.release()


class DuckDbStore:
    def __init__(self, path: str | Path | None = None) -> None:
        configured_path = path or os.environ.get(
            "STEUERREPORT_V2_DB",
            PROJECT_ROOT / "data/steuerreport_v2.duckdb",
        )
        self.path = Path(configured_path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._schema_lock = threading.Lock()
        self._connection_lock = threading.RLock()
        self._schema_ready = False

    def connect(self) -> _LockedDuckDbConnection:
        self._connection_lock.acquire()
        try:
            con = duckdb.connect(str(self.path))
            if not self._schema_ready:
                with self._schema_lock:
                    if not self._schema_ready:
                        self.ensure_schema(con)
                        self._schema_ready = True
            return _LockedDuckDbConnection(con, self._connection_lock)
        except Exception:
            self._connection_lock.release()
            raise

    @contextmanager
    def exclusive_access(self):
        self._connection_lock.acquire()
        try:
            yield
        finally:
            self._connection_lock.release()

    def ensure_schema(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("""create table if not exists ai_change_sets (
            change_set_id varchar primary key, status varchar not null,
            data_json varchar not null, created_at timestamp not null
        )""")
        con.execute("""create table if not exists ai_change_generations (
            request_id varchar primary key, request_sha256 varchar not null,
            status varchar not null, result_id varchar, error_code varchar,
            created_at timestamp not null
        )""")
        con.execute("""create table if not exists ai_correction_overrides (
            kind varchar not null, target_id varchar not null,
            original_json varchar not null, corrected_json varchar not null,
            change_set_id varchar not null, primary key (kind, target_id)
        )""")
        self._drop_table_if_missing_columns(
            con,
            "tax_lots",
            {
                "lot_id",
                "asset",
                "acquired_at",
                "quantity_total",
                "quantity_remaining",
                "cost_basis_eur_total",
                "source_event_id",
            },
        )
        self._drop_table_if_missing_columns(
            con,
            "tax_lines",
            {
                "tax_line_id",
                "asset",
                "disposed_at",
                "quantity",
                "acquisition_cost_eur",
                "disposal_proceeds_eur",
                "gain_loss_eur",
                "holding_days",
                "source_event_id",
                "lot_id",
            },
        )
        self._drop_table_if_missing_columns(
            con,
            "admin_settings",
            {"key", "value_json", "updated_at"},
        )
        self._drop_table_if_missing_columns(
            con,
            "ai_tasks",
            {
                "task_id",
                "task_type",
                "prompt",
                "status",
                "allow_external",
            },
        )
        self._drop_table_if_missing_columns(
            con,
            "tax_run_summaries",
            {"run_id", "tax_lines_count", "unmatched_disposals", "created_at"},
        )
        self._drop_table_if_missing_columns(
            con,
            "tax_unmatched_disposals",
            {
                "unmatched_id",
                "source_event_id",
                "source",
                "event_time",
                "asset",
                "quantity",
                "matched_quantity",
                "missing_quantity",
                "available_before",
            },
        )
        self._drop_table_if_missing_columns(
            con,
            "derivative_lines",
            {
                "derivative_line_id",
                "event_id",
                "source",
                "event_time",
                "asset",
                "quantity",
                "price_eur",
                "value_eur",
            },
        )
        self._drop_table_if_missing_columns(
            con,
            "derivative_run_summaries",
            {
                "run_id",
                "derivative_lines_count",
                "realized_pnl_eur",
                "missing_price_count",
                "created_at",
            },
        )
        con.execute(
            """
            create table if not exists schema_meta (
                key varchar primary key,
                value varchar not null
            )
            """
        )
        schema_row = con.execute(
            "select value from schema_meta where key = 'schema_version'"
        ).fetchone()
        schema_version = int(schema_row[0]) if schema_row is not None else 0
        if schema_version > SCHEMA_VERSION:
            raise RuntimeError("database_schema_newer_than_application")
        con.execute(
            """
            create table if not exists raw_import_batches (
                batch_id varchar primary key,
                source varchar not null,
                filename varchar,
                file_hash varchar,
                status varchar not null,
                created_at timestamp not null,
                connection_id varchar
            )
            """
        )
        if schema_version < 2:
            # Version 2 records only new explicit bindings. Existing imports stay NULL.
            con.execute(
                "alter table raw_import_batches add column if not exists connection_id varchar"
            )
        con.execute(
            """
            create table if not exists raw_objects (
                raw_object_id varchar primary key,
                batch_id varchar not null,
                row_number integer,
                payload_json varchar not null,
                created_at timestamp not null
            )
            """
        )
        con.execute(
            """
            create table if not exists canonical_events (
                event_id varchar primary key,
                source varchar not null,
                source_ref varchar,
                event_time timestamp not null,
                event_type varchar not null,
                asset varchar not null,
                quantity decimal(38, 18) not null,
                quote_asset varchar,
                quote_quantity decimal(38, 18),
                fee_asset varchar,
                fee_quantity decimal(38, 18),
                tx_id varchar,
                wallet varchar,
                account varchar,
                confidence decimal(18, 8) not null,
                raw_object_id varchar
            )
            """
        )
        con.execute(
            """
            create table if not exists balance_ledger (
                ledger_id varchar primary key,
                event_id varchar not null,
                event_time timestamp not null,
                account varchar not null,
                asset varchar not null,
                delta_quantity decimal(38, 18) not null,
                balance_quantity decimal(38, 18) not null,
                created_at timestamp not null
            )
            """
        )
        con.execute(
            """
            create table if not exists price_ledger (
                price_id varchar primary key,
                asset varchar not null,
                price_eur decimal(38, 18) not null,
                priced_at timestamp not null,
                source varchar not null,
                confidence decimal(18, 8) not null,
                created_at timestamp not null
            )
            """
        )
        con.execute(
            """
            create table if not exists flow_ledger (
                flow_id varchar primary key,
                event_id varchar not null,
                event_time timestamp not null,
                source_node varchar not null,
                target_node varchar not null,
                asset varchar not null,
                quantity decimal(38, 18) not null,
                value_eur decimal(38, 18),
                price_source varchar,
                created_at timestamp not null
            )
            """
        )
        con.execute(
            """
            create table if not exists export_packages (
                package_id varchar primary key,
                kind varchar not null,
                label varchar not null,
                file_index integer not null,
                page_count integer not null,
                status varchar not null,
                block_reason varchar,
                created_at timestamp not null
            )
            """
        )
        con.execute(
            """
            create table if not exists tax_year_report_pdf_artifacts (
                artifact_id varchar primary key,
                year integer not null,
                created_at timestamp not null,
                calculation_run_id varchar not null,
                input_binding_sha256 varchar not null,
                manifest_sha256 varchar not null,
                archive_relative_path varchar not null,
                manifest_json varchar not null
            )
            """
        )
        con.execute(
            """
            create table if not exists tax_lots (
                lot_id varchar primary key,
                asset varchar not null,
                acquired_at timestamp not null,
                quantity_total decimal(38, 18) not null,
                quantity_remaining decimal(38, 18) not null,
                cost_basis_eur_total decimal(38, 18) not null,
                source_event_id varchar not null,
                created_at timestamp not null
            )
            """
        )
        con.execute(
            """
            create table if not exists tax_lines (
                tax_line_id varchar primary key,
                asset varchar not null,
                disposed_at timestamp not null,
                quantity decimal(38, 18) not null,
                acquisition_cost_eur decimal(38, 18) not null,
                disposal_proceeds_eur decimal(38, 18) not null,
                gain_loss_eur decimal(38, 18) not null,
                holding_days integer not null,
                source_event_id varchar not null,
                lot_id varchar not null,
                created_at timestamp not null
            )
            """
        )
        con.execute(
            """
            create table if not exists tax_run_summaries (
                run_id varchar primary key,
                tax_lines_count integer not null,
                unmatched_disposals integer not null,
                created_at timestamp not null
            )
            """
        )
        con.execute(
            """
            create table if not exists tax_unmatched_disposals (
                unmatched_id varchar primary key,
                source_event_id varchar not null,
                source varchar not null,
                source_ref varchar,
                raw_object_id varchar,
                event_time timestamp not null,
                event_type varchar not null,
                account varchar,
                asset varchar not null,
                quantity decimal(38, 18) not null,
                matched_quantity decimal(38, 18) not null,
                missing_quantity decimal(38, 18) not null,
                available_before decimal(38, 18) not null,
                proceeds_total_eur decimal(38, 18) not null,
                created_at timestamp not null
            )
            """
        )
        for column_name, column_type in (
            ("pool_id", "varchar"),
            ("origin_lot_id", "varchar"),
            ("fifo_method", "varchar"),
        ):
            con.execute(
                f"alter table tax_lots add column if not exists {column_name} {column_type}"
            )
        for column_name, column_type in (
            ("pool_id", "varchar"),
            ("acquired_at", "timestamp"),
            ("acquisition_source_event_id", "varchar"),
            ("origin_lot_id", "varchar"),
            ("fifo_method", "varchar"),
        ):
            con.execute(
                f"alter table tax_lines add column if not exists {column_name} {column_type}"
            )
        for column_name, column_type in (
            ("fifo_method", "varchar"),
            ("input_fingerprint_digest", "varchar"),
        ):
            con.execute(
                f"alter table tax_run_summaries add column if not exists {column_name} {column_type}"
            )
        con.execute(
            """
            create table if not exists derivative_lines (
                derivative_line_id varchar primary key,
                event_id varchar not null,
                source varchar not null,
                source_ref varchar,
                event_time timestamp not null,
                account varchar,
                asset varchar not null,
                quantity decimal(38, 18) not null,
                price_eur decimal(38, 18) not null,
                value_eur decimal(38, 18) not null,
                price_source varchar,
                created_at timestamp not null
            )
            """
        )
        con.execute(
            """
            create table if not exists derivative_run_summaries (
                run_id varchar primary key,
                derivative_lines_count integer not null,
                realized_pnl_eur decimal(38, 18) not null,
                missing_price_count integer not null,
                created_at timestamp not null
            )
            """
        )
        con.execute(
            """
            create table if not exists admin_settings (
                key varchar primary key,
                value_json varchar not null,
                updated_at timestamp not null
            )
            """
        )
        con.execute(
            """
            create table if not exists connector_connections (
                connection_id varchar primary key,
                connector_id varchar not null,
                external_identifier varchar not null,
                display_label varchar not null,
                source_id varchar,
                status varchar not null,
                metadata_json varchar not null,
                created_at timestamp not null,
                verified_at timestamp,
                revoked_at timestamp,
                last_sync_at timestamp,
                unique (connector_id, external_identifier)
            )
            """
        )
        con.execute(
            """
            create table if not exists wallet_ownership_challenges (
                challenge_id varchar primary key,
                connector_id varchar not null,
                wallet_address varchar not null,
                wallet_provider varchar not null,
                display_label varchar not null,
                message varchar not null,
                nonce_hash varchar not null,
                issued_at timestamp not null,
                expires_at timestamp not null,
                status varchar not null,
                verified_at timestamp,
                signature varchar
            )
            """
        )
        con.execute(
            """
            create table if not exists mobile_connector_pairings (
                pairing_id varchar primary key,
                code_hash varchar not null,
                device_name varchar not null,
                platform varchar not null,
                scopes_json varchar not null,
                session_ttl_hours integer not null,
                issued_at timestamp not null,
                expires_at timestamp not null,
                status varchar not null,
                attempt_count integer not null,
                exchanged_at timestamp,
                session_id varchar
            )
            """
        )
        con.execute(
            """
            create table if not exists mobile_connector_sessions (
                session_id varchar primary key,
                token_hash varchar unique not null,
                device_name varchar not null,
                platform varchar not null,
                scopes_json varchar not null,
                created_at timestamp not null,
                expires_at timestamp not null,
                last_used_at timestamp,
                revoked_at timestamp
            )
            """
        )
        con.execute(
            """
            create table if not exists mobile_document_inbox (
                document_id varchar primary key,
                document_sha256 varchar unique not null,
                original_filename varchar not null,
                storage_filename varchar not null,
                media_type varchar not null,
                size_bytes bigint not null,
                document_kind varchar not null,
                source_hint varchar,
                note varchar,
                captured_at timestamp,
                first_uploaded_at timestamp not null,
                last_uploaded_at timestamp not null,
                upload_count integer not null,
                first_uploaded_by_session_id varchar,
                last_uploaded_by_session_id varchar,
                review_status varchar not null
            )
            """
        )
        con.execute(
            """
            create table if not exists tax_filing_snapshots (
                snapshot_id varchar primary key,
                year integer not null,
                revision integer not null,
                state varchar not null,
                filing_kind varchar not null,
                source_kind varchar not null,
                source_snapshot_id varchar,
                package_filename varchar not null,
                archive_relative_path varchar not null,
                package_sha256 varchar not null,
                package_size_bytes bigint not null,
                manifest_sha256 varchar not null,
                runtime_fingerprint_sha256 varchar not null,
                package_generated_at timestamp not null,
                summary_json varchar not null,
                manifest_json varchar not null,
                metadata_json varchar not null,
                taxable_private_disposals_eur decimal(38, 18) not null,
                taxable_disposal_proceeds_eur decimal(38, 18) not null,
                acquisition_cost_eur decimal(38, 18) not null,
                rewards_mining_staking_income_eur decimal(38, 18) not null,
                derivative_pnl_eur decimal(38, 18) not null,
                tax_free_private_disposals_eur decimal(38, 18) not null,
                tax_free_lines_count integer not null,
                export_ready boolean not null,
                note varchar,
                created_at timestamp not null,
                submitted_at timestamp,
                unique (year, revision)
            )
            """
        )
        con.execute(
            """
            create table if not exists tax_filing_snapshot_files (
                snapshot_id varchar not null,
                path varchar not null,
                size_bytes bigint not null,
                sha256 varchar not null,
                source_endpoint varchar,
                primary key (snapshot_id, path)
            )
            """
        )
        con.execute(
            """
            create table if not exists tax_filing_snapshot_events (
                event_id varchar primary key,
                snapshot_id varchar not null,
                event_type varchar not null,
                payload_json varchar not null,
                created_at timestamp not null
            )
            """
        )
        con.execute(
            """
            create table if not exists ai_tasks (
                task_id varchar primary key,
                task_type varchar not null,
                prompt varchar not null,
                status varchar not null,
                result_json varchar,
                allow_external boolean not null,
                created_at timestamp not null,
                updated_at timestamp not null
            )
            """
        )
        con.execute(
            """
            create table if not exists v1_reference_metrics (
                reference_id varchar primary key,
                scope varchar not null,
                metric varchar not null,
                unit varchar not null,
                value decimal(38, 18) not null,
                year integer,
                asset varchar,
                source varchar,
                note varchar,
                created_at timestamp not null
            )
            """
        )
        con.execute(
            """
            create table if not exists portfolio_live_balance_snapshots (
                snapshot_id varchar primary key,
                connector_id varchar not null,
                asset varchar not null,
                quantity decimal(38, 18) not null,
                source varchar not null,
                fetched_at timestamp not null,
                account_type varchar,
                product_id varchar,
                position_id varchar,
                event_type varchar
            )
            """
        )
        con.execute(
            """
            create table if not exists portfolio_live_connector_runs (
                run_id varchar primary key,
                connector_id varchar not null,
                fetched_at timestamp not null,
                status varchar not null,
                snapshots_count bigint not null,
                source varchar,
                message varchar
            )
            """
        )
        con.execute(
            """
            create table if not exists jupiter_token_metadata_cache (
                mint varchar primary key,
                symbol varchar,
                name varchar,
                decimals integer,
                icon varchar,
                token_program varchar,
                is_verified boolean,
                organic_score decimal(38, 18),
                organic_score_label varchar,
                holder_count integer,
                liquidity_usd decimal(38, 18),
                usd_price decimal(38, 18),
                market_cap_usd decimal(38, 18),
                risk_status varchar not null,
                source varchar not null,
                discovered_sources_json varchar not null,
                refreshed_at timestamp not null,
                jupiter_updated_at timestamp
            )
            """
        )
        for column_name in ("account_type", "product_id", "position_id", "event_type"):
            con.execute(
                f"alter table portfolio_live_balance_snapshots add column if not exists {column_name} varchar"
            )
        for table_name in (
            "event_links",
            "transfer_chains",
            "review_issues",
            "review_decisions",
        ):
            con.execute(
                f"""
                create table if not exists {table_name} (
                    id varchar primary key,
                    payload_json varchar not null,
                    created_at timestamp not null,
                    updated_at timestamp
                )
                """
            )
        con.execute(
            "insert or replace into schema_meta values ('schema_version', ?)",
            [str(SCHEMA_VERSION)],
        )

    def _drop_table_if_missing_columns(
        self,
        con: duckdb.DuckDBPyConnection,
        table_name: str,
        required_columns: set[str],
    ) -> None:
        table_exists = con.execute(
            """
            select count(*)
            from information_schema.tables
            where table_name = ?
            """,
            [table_name],
        ).fetchone()[0]
        if table_exists == 0:
            return
        rows = con.execute(f"pragma table_info('{table_name}')").fetchall()
        columns = {row[1] for row in rows}
        if not required_columns.issubset(columns):
            con.execute(f"drop table {table_name}")

    def health(self) -> dict[str, str | int | bool]:
        with self.connect() as con:
            version = con.execute(
                "select value from schema_meta where key = 'schema_version'"
            ).fetchone()[0]
        return {
            "database_type": "duckdb",
            "path": str(self.path),
            "exists": self.path.exists(),
            "schema_version": int(version),
        }

    def create_import_batch(self, payload: ImportBatchCreate) -> ImportBatch:
        batch_id = str(uuid4())
        created_at = datetime.now(timezone.utc)
        with self.connect() as con:
            con.execute(
                """
                insert into raw_import_batches
                    (batch_id, source, filename, file_hash, status, created_at, connection_id)
                values (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    batch_id,
                    payload.source,
                    payload.filename,
                    payload.file_hash,
                    "created",
                    created_at,
                    str(payload.connection_id) if payload.connection_id else None,
                ],
            )
        batch = self.get_import_batch(batch_id)
        if batch is None:
            raise RuntimeError("created import batch could not be read back")
        return batch

    def create_import_batch_with_raw(self, payload: ImportBatchCreate, payloads: list[RawObjectCreate]) -> ImportBatch:
        """Persist a fully validated native file in one transaction."""
        batch_id, created_at = str(uuid4()), datetime.now(timezone.utc)
        rows = [(str(uuid4()), batch_id, p.row_number, p.payload_json, created_at) for p in payloads]
        with self.connect() as con:
            con.execute("begin transaction")
            try:
                con.execute("""insert into raw_import_batches
                    (batch_id,source,filename,file_hash,status,created_at) values (?,?,?,?,?,?)""",
                    [batch_id, payload.source, payload.filename, payload.file_hash, "loaded", created_at])
                if rows:
                    frame = pd.DataFrame(rows, columns=["raw_object_id", "batch_id", "row_number", "payload_json", "created_at"])
                    con.register("native_raw_rows", frame)
                    try:
                        con.execute("""insert into raw_objects (raw_object_id,batch_id,row_number,payload_json,created_at)
                            select raw_object_id,batch_id,row_number,payload_json,created_at from native_raw_rows""")
                    finally:
                        con.unregister("native_raw_rows")
                con.execute("commit")
            except Exception:
                con.execute("rollback")
                raise
        return self.get_import_batch(batch_id)

    def get_import_batch(self, batch_id: str) -> ImportBatch | None:
        with self.connect() as con:
            row = con.execute(
                """
                select
                    b.batch_id,
                    b.source,
                    b.filename,
                    b.file_hash,
                    b.connection_id,
                    b.status,
                    b.created_at,
                    count(o.raw_object_id) as raw_object_count
                from raw_import_batches b
                left join raw_objects o on o.batch_id = b.batch_id
                where b.batch_id = ?
                group by
                    b.batch_id, b.source, b.filename, b.file_hash,
                    b.connection_id, b.status, b.created_at
                """,
                [batch_id],
            ).fetchone()
        if row is None:
            return None
        return ImportBatch(
            batch_id=row[0],
            source=row[1],
            filename=row[2],
            file_hash=row[3],
            connection_id=row[4],
            status=row[5],
            created_at=row[6],
            raw_object_count=row[7],
        )

    def get_import_batch_by_file_hash(
        self,
        source: str,
        file_hash: str,
        connection_id: str | None = None,
    ) -> ImportBatch | None:
        with self.connect() as con:
            if connection_id is None:
                row = con.execute(
                    """
                    select batch_id
                    from raw_import_batches
                    where source = ? and file_hash = ?
                    order by created_at
                    limit 1
                    """,
                    [source, file_hash],
                ).fetchone()
            else:
                row = con.execute(
                    """
                    select batch_id
                    from raw_import_batches
                    where source = ? and file_hash = ?
                      and (connection_id = ? or connection_id is null)
                    order by case when connection_id = ? then 0 else 1 end, created_at
                    limit 1
                    """,
                    [source, file_hash, connection_id, connection_id],
                ).fetchone()
        if row is None:
            return None
        return self.get_import_batch(row[0])

    def list_import_batches(self) -> list[ImportBatch]:
        with self.connect() as con:
            rows = con.execute(
                """
                select
                    b.batch_id,
                    b.source,
                    b.filename,
                    b.file_hash,
                    b.connection_id,
                    b.status,
                    b.created_at,
                    count(o.raw_object_id) as raw_object_count
                from raw_import_batches b
                left join raw_objects o on o.batch_id = b.batch_id
                group by
                    b.batch_id, b.source, b.filename, b.file_hash,
                    b.connection_id, b.status, b.created_at
                order by b.created_at desc
                """
            ).fetchall()
        return [
            ImportBatch(
                batch_id=row[0],
                source=row[1],
                filename=row[2],
                file_hash=row[3],
                connection_id=row[4],
                status=row[5],
                created_at=row[6],
                raw_object_count=row[7],
            )
            for row in rows
        ]

    def upsert_admin_setting(self, setting: AdminSettingWrite) -> AdminSetting:
        updated_at = datetime.now(timezone.utc)
        with self.connect() as con:
            con.execute(
                """
                insert or replace into admin_settings (key, value_json, updated_at)
                values (?, ?, ?)
                """,
                [setting.key, setting.value_json, updated_at],
            )
        return AdminSetting(
            key=setting.key,
            value_json=setting.value_json,
            updated_at=updated_at,
        )

    def list_admin_settings(self) -> list[AdminSetting]:
        with self.connect() as con:
            rows = con.execute(
                """
                select key, value_json, updated_at
                from admin_settings
                order by key
                """
            ).fetchall()
        return [
            AdminSetting(key=row[0], value_json=row[1], updated_at=row[2])
            for row in rows
        ]

    def delete_admin_setting(self, key: str) -> bool:
        with self.connect() as con:
            existing = con.execute(
                "select 1 from admin_settings where key = ?",
                [key],
            ).fetchone()
            if existing is None:
                return False
            con.execute("delete from admin_settings where key = ?", [key])
        return True

    def create_ai_task(
        self,
        payload: AiTaskCreate,
        status: AiTaskStatus,
        result_json: str | None,
    ) -> AiTask:
        task_id = str(uuid4())
        created_at = datetime.now(timezone.utc)
        with self.connect() as con:
            con.execute(
                """
                insert into ai_tasks (
                    task_id, task_type, prompt, status, result_json,
                    allow_external, created_at, updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    task_id,
                    payload.task_type,
                    payload.prompt,
                    status,
                    result_json,
                    payload.allow_external,
                    created_at,
                    created_at,
                ],
            )
        return AiTask(
            task_id=task_id,
            task_type=payload.task_type,
            prompt=payload.prompt,
            status=status,
            result_json=result_json,
            allow_external=payload.allow_external,
            created_at=created_at,
            updated_at=created_at,
        )

    def write_admin_settings_batch(self, settings: list[AdminSettingWrite], delete_keys: list[str]) -> None:
        with self.connect() as con:
            con.execute("begin transaction")
            try:
                for key in delete_keys:
                    con.execute("delete from admin_settings where key = ?", [key])
                for item in settings:
                    con.execute(
                        "insert into admin_settings (key, value_json, updated_at) values (?, ?, ?) "
                        "on conflict (key) do update set value_json = excluded.value_json, updated_at = excluded.updated_at",
                        [item.key, item.value_json, datetime.now(timezone.utc)],
                    )
                con.execute("commit")
            except Exception:
                con.execute("rollback")
                raise

    def get_ai_task(self, task_id: str) -> AiTask | None:
        return next((item for item in self.list_ai_tasks() if item.task_id == task_id), None)

    def claim_ai_task(self, task_id: str) -> bool:
        with self.connect() as con:
            return con.execute(
                "update ai_tasks set status = 'running', updated_at = ? "
                "where task_id = ? and status = 'queued' returning task_id",
                [datetime.now(timezone.utc), task_id],
            ).fetchone() is not None

    def finish_ai_task(self, task_id: str, *, status: AiTaskStatus, result_json: str) -> None:
        with self.connect() as con:
            con.execute(
                "update ai_tasks set status = ?, result_json = ?, updated_at = ? "
                "where task_id = ? and status = 'running'",
                [status, result_json, datetime.now(timezone.utc), task_id],
            )

    def list_ai_tasks(self) -> list[AiTask]:
        with self.connect() as con:
            rows = con.execute(
                """
                select
                    task_id, task_type, prompt, status, result_json,
                    allow_external, created_at, updated_at
                from ai_tasks
                order by created_at desc
                """
            ).fetchall()
        return [
            AiTask(
                task_id=row[0],
                task_type=row[1],
                prompt=row[2],
                status=row[3],
                result_json=row[4],
                allow_external=row[5],
                created_at=row[6],
                updated_at=row[7],
            )
            for row in rows
        ]

    def delete_ai_task(self, task_id: str) -> bool:
        with self.connect() as con:
            existing = con.execute(
                "select 1 from ai_tasks where task_id = ?",
                [task_id],
            ).fetchone()
            if existing is None:
                return False
            con.execute("delete from ai_tasks where task_id = ?", [task_id])
        return True

    def table_counts(self, table_names: list[str]) -> dict[str, int]:
        allowed = {
            "raw_import_batches",
            "raw_objects",
            "canonical_events",
            "balance_ledger",
            "flow_ledger",
            "export_packages",
            "tax_lines",
            "tax_run_summaries",
            "derivative_lines",
            "derivative_run_summaries",
        }
        counts: dict[str, int] = {}
        with self.connect() as con:
            for table_name in table_names:
                if table_name not in allowed:
                    raise ValueError(f"unsupported table count: {table_name}")
                counts[table_name] = con.execute(
                    f"select count(*) from {table_name}"
                ).fetchone()[0]
        return counts

    def delete_import_batches_by_source(self, source: str) -> int:
        deleted = 0
        with self.connect() as con:
            batch_ids = [
                row[0]
                for row in con.execute(
                    "select batch_id from raw_import_batches where source = ?",
                    [source],
                ).fetchall()
            ]
        for batch_id in batch_ids:
            if self.delete_import_batch(batch_id):
                deleted += 1
        return deleted

    def delete_import_batch(self, batch_id: str) -> bool:
        with self.connect() as con:
            existing = con.execute(
                "select 1 from raw_import_batches where batch_id = ?",
                [batch_id],
            ).fetchone()
            if existing is None:
                return False
            protected = con.execute("""select 1 from ai_correction_overrides o
                join canonical_events e on o.kind='event' and o.target_id=e.event_id
                join raw_objects r on r.raw_object_id=e.raw_object_id
                where r.batch_id=? and o.original_json <> o.corrected_json limit 1""", [batch_id]).fetchone()
            if protected:
                from steuerreport_v2.db.ai_corrections import CorrectionConflict
                raise CorrectionConflict("ai_correction_target_protected")
            con.execute(
                """
                delete from balance_ledger
                where event_id in (
                    select event_id
                    from canonical_events
                    where raw_object_id in (
                        select raw_object_id from raw_objects where batch_id = ?
                    )
                )
                """,
                [batch_id],
            )
            con.execute(
                """
                delete from flow_ledger
                where event_id in (
                    select event_id
                    from canonical_events
                    where raw_object_id in (
                        select raw_object_id from raw_objects where batch_id = ?
                    )
                )
                """,
                [batch_id],
            )
            con.execute(
                """
                delete from canonical_events
                where raw_object_id in (
                    select raw_object_id from raw_objects where batch_id = ?
                )
                """,
                [batch_id],
            )
            con.execute("delete from raw_objects where batch_id = ?", [batch_id])
            con.execute("delete from raw_import_batches where batch_id = ?", [batch_id])
        return True

    def delete_price_points_by_source(self, source: str) -> int:
        with self.connect() as con:
            protected = con.execute("""select 1 from ai_correction_overrides o join price_ledger p
                on o.kind='price' and o.target_id=p.price_id where p.source=?
                and o.original_json <> o.corrected_json limit 1""", [source]).fetchone()
            if protected:
                from steuerreport_v2.db.ai_corrections import CorrectionConflict
                raise CorrectionConflict("ai_correction_target_protected")
            count = con.execute(
                "select count(*) from price_ledger where source = ?",
                [source],
            ).fetchone()[0]
            con.execute("delete from price_ledger where source = ?", [source])
        return count

    def delete_price_point(self, price_id: str) -> bool:
        with self.connect() as con:
            if con.execute("select 1 from ai_correction_overrides where kind='price' and target_id=? and original_json <> corrected_json", [price_id]).fetchone():
                from steuerreport_v2.db.ai_corrections import CorrectionConflict
                raise CorrectionConflict("ai_correction_target_protected")
            existing = con.execute(
                "select 1 from price_ledger where price_id = ?",
                [price_id],
            ).fetchone()
            if existing is None:
                return False
            con.execute("delete from price_ledger where price_id = ?", [price_id])
        return True

    def add_price_point(self, payload: PricePointCreate) -> PricePoint:
        return self.add_price_points([payload])[0]

    def add_price_points(self, payloads: list[PricePointCreate]) -> list[PricePoint]:
        if not payloads:
            return []
        created_at = datetime.now(timezone.utc)
        rows = [
            (
                str(uuid4()),
                payload.asset.upper(),
                str(payload.price_eur),
                payload.priced_at,
                payload.source,
                str(payload.confidence),
                created_at,
            )
            for payload in payloads
        ]
        with self.connect() as con:
            frame = pd.DataFrame(
                rows,
                columns=[
                    "price_id",
                    "asset",
                    "price_eur",
                    "priced_at",
                    "source",
                    "confidence",
                    "created_at",
                ],
            )
            con.register("price_points_to_insert", frame)
            con.execute(
                """
                insert into price_ledger (
                    price_id, asset, price_eur, priced_at, source,
                    confidence, created_at
                )
                select
                    price_id,
                    asset,
                    cast(price_eur as decimal(38, 18)),
                    priced_at,
                    source,
                    cast(confidence as decimal(18, 8)),
                    created_at
                from price_points_to_insert
                """
            )
            con.unregister("price_points_to_insert")
        return [
            PricePoint(
                price_id=row[0],
                asset=row[1],
                price_eur=Decimal(row[2]),
                priced_at=row[3],
                source=row[4],
                confidence=Decimal(row[5]),
            )
            for row in rows
        ]

    def add_v1_reference_metric(
        self,
        payload: V1ReferenceMetricCreate,
    ) -> V1ReferenceMetric:
        reference_id = str(uuid4())
        created_at = datetime.now(timezone.utc)
        asset = payload.asset.upper() if payload.asset is not None else None
        with self.connect() as con:
            con.execute(
                """
                insert into v1_reference_metrics (
                    reference_id, scope, metric, unit, value, year, asset,
                    source, note, created_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    reference_id,
                    payload.scope,
                    payload.metric,
                    payload.unit,
                    payload.value,
                    payload.year,
                    asset,
                    payload.source,
                    payload.note,
                    created_at,
                ],
            )
        return V1ReferenceMetric(
            reference_id=reference_id,
            scope=payload.scope,
            metric=payload.metric,
            unit=payload.unit,
            value=payload.value,
            year=payload.year,
            asset=asset,
            source=payload.source,
            note=payload.note,
            created_at=created_at,
        )

    def list_v1_reference_metrics(self) -> list[V1ReferenceMetric]:
        with self.connect() as con:
            rows = con.execute(
                """
                select
                    reference_id, scope, metric, unit, value, year, asset,
                    source, note, created_at
                from v1_reference_metrics
                order by scope, metric, year nulls last, asset nulls last, source nulls last
                """
            ).fetchall()
        return [
            V1ReferenceMetric(
                reference_id=row[0],
                scope=row[1],
                metric=row[2],
                unit=row[3],
                value=row[4],
                year=row[5],
                asset=row[6],
                source=row[7],
                note=row[8],
                created_at=row[9],
            )
            for row in rows
        ]

    def delete_v1_reference_metric(self, reference_id: str) -> bool:
        with self.connect() as con:
            existing = con.execute(
                "select 1 from v1_reference_metrics where reference_id = ?",
                [reference_id],
            ).fetchone()
            if existing is None:
                return False
            con.execute(
                "delete from v1_reference_metrics where reference_id = ?",
                [reference_id],
            )
        return True

    def delete_v1_reference_metrics_by_source(self, source: str) -> int:
        with self.connect() as con:
            count = con.execute(
                "select count(*) from v1_reference_metrics where source = ?",
                [source],
            ).fetchone()[0]
            con.execute(
                "delete from v1_reference_metrics where source = ?",
                [source],
            )
        return int(count)

    def add_review_decision(self, payload: ReviewDecisionCreate) -> ReviewDecision:
        decision_id = str(uuid4())
        created_at = datetime.now(timezone.utc)
        decision = ReviewDecision(
            decision_id=decision_id,
            decision_type=payload.decision_type,
            scope=payload.scope,
            title=payload.title,
            rationale=payload.rationale,
            evidence_ref=payload.evidence_ref,
            actor=payload.actor,
            source=payload.source,
            affected_ids=payload.affected_ids,
            payload=payload.payload,
            created_at=created_at,
            updated_at=None,
        )
        with self.connect() as con:
            con.execute(
                """
                insert into review_decisions (id, payload_json, created_at, updated_at)
                values (?, ?, ?, ?)
                """,
                [
                    decision_id,
                    decision.model_dump_json(),
                    created_at,
                    None,
                ],
            )
        return decision

    def list_review_decisions(self) -> list[ReviewDecision]:
        with self.connect() as con:
            rows = con.execute(
                """
                select payload_json, created_at, updated_at
                from review_decisions
                order by created_at desc, id desc
                """
            ).fetchall()
        decisions: list[ReviewDecision] = []
        for payload_json, created_at, updated_at in rows:
            decision = ReviewDecision.model_validate_json(payload_json)
            if decision.created_at != created_at or decision.updated_at != updated_at:
                decision = decision.model_copy(
                    update={
                        "created_at": created_at,
                        "updated_at": updated_at,
                    }
                )
            decisions.append(decision)
        return decisions

    def update_review_decision(self, decision: ReviewDecision) -> ReviewDecision:
        updated_at = datetime.now(timezone.utc)
        updated = decision.model_copy(update={"updated_at": updated_at})
        with self.connect() as con:
            con.execute(
                """
                update review_decisions
                set payload_json = ?, updated_at = ?
                where id = ?
                """,
                [
                    updated.model_dump_json(),
                    updated_at,
                    updated.decision_id,
                ],
            )
        return updated

    def latest_price_points(self) -> dict[str, PricePoint]:
        with self.connect() as con:
            rows = con.execute(
                """
                select p.price_id, p.asset, p.price_eur, p.priced_at, p.source, p.confidence
                from price_ledger p
                join (
                    select asset, max(priced_at) as priced_at
                    from price_ledger
                    group by asset
                ) latest
                on latest.asset = p.asset and latest.priced_at = p.priced_at
                qualify row_number() over (
                    partition by p.asset order by p.price_id desc
                ) = 1
                """
            ).fetchall()
        return {
            row[1]: PricePoint(
                price_id=row[0],
                asset=row[1],
                price_eur=row[2],
                priced_at=row[3],
                source=row[4],
                confidence=row[5],
            )
            for row in rows
        }

    def price_point_at_or_before(self, asset: str, priced_at: datetime) -> PricePoint | None:
        with self.connect() as con:
            row = con.execute(
                """
                select price_id, asset, price_eur, priced_at, source, confidence
                from price_ledger
                where asset = ? and priced_at <= ?
                order by priced_at desc, created_at desc, price_id desc
                limit 1
                """,
                [asset.upper(), priced_at],
            ).fetchone()
        if row is None:
            return None
        return PricePoint(
            price_id=row[0],
            asset=row[1],
            price_eur=row[2],
            priced_at=row[3],
            source=row[4],
            confidence=row[5],
        )

    def list_latest_price_points(self) -> list[PricePoint]:
        prices = self.latest_price_points()
        return [prices[asset] for asset in sorted(prices)]

    def list_price_points(self, limit: int | None = 500) -> list[PricePoint]:
        with self.connect() as con:
            rows = con.execute(
                """
                select price_id, asset, price_eur, priced_at, source, confidence
                from price_ledger
                order by priced_at desc, created_at desc, price_id desc
                """ + (" limit ?" if limit is not None else ""),
                [limit] if limit is not None else [],
            ).fetchall()
        return [
            PricePoint(
                price_id=row[0],
                asset=row[1],
                price_eur=row[2],
                priced_at=row[3],
                source=row[4],
                confidence=row[5],
            )
            for row in rows
        ]

    def add_raw_object(self, batch_id: str, payload: RawObjectCreate) -> RawObject:
        return self.add_raw_objects(batch_id, [payload])[0]

    def add_raw_objects(
        self,
        batch_id: str,
        payloads: list[RawObjectCreate],
    ) -> list[RawObject]:
        if not payloads:
            return []
        created_at = datetime.now(timezone.utc)
        rows = [
            (
                str(uuid4()),
                batch_id,
                payload.row_number,
                payload.payload_json,
                created_at,
            )
            for payload in payloads
        ]
        with self.connect() as con:
            existing = con.execute(
                "select 1 from raw_import_batches where batch_id = ?",
                [batch_id],
            ).fetchone()
            if existing is None:
                raise ValueError(f"unknown import batch: {batch_id}")
            frame = pd.DataFrame(
                rows,
                columns=["raw_object_id", "batch_id", "row_number", "payload_json", "created_at"],
            )
            con.register("raw_objects_to_insert", frame)
            con.execute(
                """
                insert into raw_objects
                    (raw_object_id, batch_id, row_number, payload_json, created_at)
                select raw_object_id, batch_id, row_number, payload_json, created_at
                from raw_objects_to_insert
                """
            )
            con.unregister("raw_objects_to_insert")
            con.execute(
                """
                update raw_import_batches
                set status = 'loaded'
                where batch_id = ? and status = 'created'
                """,
                [batch_id],
            )
        return [
            RawObject(
                raw_object_id=row[0],
                batch_id=row[1],
                row_number=row[2],
                payload_json=row[3],
                created_at=row[4],
            )
            for row in rows
        ]

    def list_raw_objects(
        self,
        batch_id: str | None = None,
        limit: int | None = 500,
    ) -> list[RawObject]:
        where_clause = ""
        params: list[str | int] = []
        if batch_id is not None:
            where_clause = "where batch_id = ?"
            params.append(batch_id)
        limit_clause = ""
        if limit is not None:
            limit_clause = "limit ?"
            params.append(limit)
        with self.connect() as con:
            rows = con.execute(
                f"""
                select raw_object_id, batch_id, row_number, payload_json, created_at
                from raw_objects
                {where_clause}
                order by row_number nulls last, created_at
                {limit_clause}
                """,
                params,
            ).fetchall()
        return [
            RawObject(
                raw_object_id=row[0],
                batch_id=row[1],
                row_number=row[2],
                payload_json=row[3],
                created_at=row[4],
            )
            for row in rows
        ]

    def delete_canonical_events_for_batch(self, batch_id: str) -> None:
        with self.connect() as con:
            con.execute(
                """
                delete from canonical_events
                where raw_object_id in (
                    select raw_object_id from raw_objects where batch_id = ?
                )
                """,
                [batch_id],
            )

    def add_canonical_event(self, payload: CanonicalEventCreate) -> CanonicalEvent:
        return self.add_canonical_events([payload])[0]

    def add_canonical_events(
        self,
        payloads: list[CanonicalEventCreate],
    ) -> list[CanonicalEvent]:
        if not payloads:
            return []
        identity_occurrences: dict[str, int] = {}
        rows = []
        for payload in payloads:
            event_id = str(uuid4())
            if payload.raw_object_id:
                identity = self._canonical_event_identity(payload)
                occurrence = identity_occurrences.get(identity, 0)
                identity_occurrences[identity] = occurrence + 1
                event_id = str(
                    uuid5(
                        NAMESPACE_URL,
                        f"steuerreport-v2:canonical-event:v1:{identity}:{occurrence}",
                    )
                )
            rows.append(
                (
                event_id,
                payload.source,
                payload.source_ref,
                payload.event_time,
                payload.event_type,
                payload.asset,
                str(payload.quantity),
                payload.quote_asset,
                str(payload.quote_quantity) if payload.quote_quantity is not None else None,
                payload.fee_asset,
                str(payload.fee_quantity) if payload.fee_quantity is not None else None,
                payload.tx_id,
                payload.wallet,
                payload.account,
                str(payload.confidence),
                payload.raw_object_id,
                )
            )
        with self.connect() as con:
            frame = pd.DataFrame(
                rows,
                columns=[
                    "event_id",
                    "source",
                    "source_ref",
                    "event_time",
                    "event_type",
                    "asset",
                    "quantity",
                    "quote_asset",
                    "quote_quantity",
                    "fee_asset",
                    "fee_quantity",
                    "tx_id",
                    "wallet",
                    "account",
                    "confidence",
                    "raw_object_id",
                ],
            )
            con.register("canonical_events_to_insert", frame)
            con.execute(
                """
                insert into canonical_events (
                    event_id, source, source_ref, event_time, event_type,
                    asset, quantity, quote_asset, quote_quantity,
                    fee_asset, fee_quantity, tx_id, wallet, account,
                    confidence, raw_object_id
                )
                select
                    event_id, source, source_ref, event_time, event_type,
                    asset,
                    cast(quantity as decimal(38, 18)),
                    quote_asset,
                    cast(quote_quantity as decimal(38, 18)),
                    fee_asset,
                    cast(fee_quantity as decimal(38, 18)),
                    tx_id, wallet, account,
                    cast(confidence as decimal(18, 8)),
                    raw_object_id
                from canonical_events_to_insert
                """
            )
            con.unregister("canonical_events_to_insert")
            from steuerreport_v2.db.ai_corrections import replay
            corrected_records = replay(con, event_ids=[row[0] for row in rows])
        return [
            CanonicalEvent.model_validate(corrected_records[row[0]]) if row[0] in corrected_records else CanonicalEvent(
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
            for row in rows
        ]

    @staticmethod
    def _canonical_event_identity(payload: CanonicalEventCreate) -> str:
        event_time = payload.event_time
        if event_time.tzinfo is not None:
            event_time = event_time.astimezone(timezone.utc)
        values = {
            "raw_object_id": payload.raw_object_id,
            "source": payload.source,
            "source_ref": payload.source_ref,
            "event_time": event_time.isoformat(),
            "event_type": payload.event_type,
            "asset": payload.asset,
            "quantity": str(payload.quantity),
            "quote_asset": payload.quote_asset,
            "quote_quantity": (
                str(payload.quote_quantity)
                if payload.quote_quantity is not None
                else None
            ),
            "fee_asset": payload.fee_asset,
            "fee_quantity": (
                str(payload.fee_quantity) if payload.fee_quantity is not None else None
            ),
            "tx_id": payload.tx_id,
            "wallet": payload.wallet,
            "account": payload.account,
        }
        return json.dumps(
            values,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

    def list_canonical_events(self, batch_id: str | None = None) -> list[CanonicalEvent]:
        where_clause = ""
        params: list[str] = []
        if batch_id is not None:
            where_clause = """
            where e.raw_object_id in (
                select raw_object_id from raw_objects where batch_id = ?
            )
            """
            params.append(batch_id)
        with self.connect() as con:
            rows = con.execute(
                f"""
                select
                    e.event_id, e.source, e.source_ref, e.event_time, e.event_type,
                    e.asset, e.quantity, e.quote_asset, e.quote_quantity,
                    e.fee_asset, e.fee_quantity, e.tx_id, e.wallet, e.account,
                    e.confidence, e.raw_object_id
                from canonical_events e
                left join raw_objects r on r.raw_object_id = e.raw_object_id
                {where_clause}
                order by
                    e.event_time,
                    case when r.row_number is null then 1 else 0 end,
                    r.row_number,
                    e.source,
                    coalesce(e.account, ''),
                    coalesce(e.wallet, ''),
                    coalesce(e.tx_id, ''),
                    coalesce(e.source_ref, ''),
                    e.event_type,
                    e.asset,
                    coalesce(e.quote_asset, ''),
                    e.quantity,
                    coalesce(e.quote_quantity, 0),
                    e.event_id
                """,
                params,
            ).fetchall()
        return [
            CanonicalEvent(
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
            for row in rows
        ]

    def unmapped_raw_object_counts(self) -> dict[str, int]:
        with self.connect() as con:
            rows = con.execute(
                """
                select r.batch_id, count(*) as unmapped_count
                from raw_objects r
                join raw_import_batches b on b.batch_id = r.batch_id
                left join canonical_events e on e.raw_object_id = r.raw_object_id
                where e.event_id is null
                  and (b.source = 'mexc' or lower(r.payload_json) not like '%bitget_withdrawal_evidence%')
                  and (b.source = 'mexc' or coalesce(json_extract_string(r.payload_json, '$.history_evidence_only'), '') <> '1')
                  and not (b.source = 'mexc' and coalesce(json_extract_string(
                    try_cast(json_extract_string(r.payload_json, '$._mexc') as json), '$.role'), '') in ('snapshot', 'linked'))
                group by r.batch_id
                order by r.batch_id
                """
            ).fetchall()
        return {row[0]: row[1] for row in rows}
