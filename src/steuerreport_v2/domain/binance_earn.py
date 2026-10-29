from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import os
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
import urllib.parse

import httpx
from steuerreport_v2.domain.external_http import managed_client, request_signer

from steuerreport_v2.contracts.binance_earn import (
    BinanceAssetDividendPreview,
    BinanceAssetDividendRecord,
    BinanceAssetDividendRequest,
    BinanceCapitalWithdrawalPreview,
    BinanceCapitalWithdrawalRecord,
    BinanceCapitalWithdrawalRequest,
    BinanceEarnHistoryApiPreview,
    BinanceEarnHistoryApiRecord,
    BinanceEarnHistoryApiRequest,
)
from steuerreport_v2.contracts.binance_earn_import import (
    BinanceAssetDividendApiImportResult,
    BinanceCapitalWithdrawalApiImportResult,
    BinanceEarnApiImportResult,
    BinanceEarnHarvestImportPreview,
    BinanceEarnHarvestImportResult,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.secrets import resolve_secret_value
from steuerreport_v2.domain.sources import SourceService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter


class BinanceEarnHistoryService:
    BASE_URL = "https://api.binance.com"
    SIZE = 100
    WINDOW_DAYS = 29
    DIVIDEND_WINDOW_DAYS = 179
    DIVIDEND_LIMIT = 500

    def __init__(self, store: DuckDbStore, *, connection_id: str | None = None) -> None:
        self.store = store
        self.connection_id = str(connection_id).strip() if connection_id is not None else None

    def history_products_for_connection(self) -> list[dict[str, str | None]]:
        """Return Earn product anchors only from the selected account's evidence."""
        if self.connection_id is None:
            raise RuntimeError("binance_earn_connection_required")
        from steuerreport_v2.domain.connections import ConnectionService

        connections = ConnectionService(self.store)
        connections.validate_import_binding(self.connection_id, "binance")
        snapshots = connections.snapshots(self.connection_id).snapshots
        products: set[tuple[str, str, str | None, str | None]] = set()
        for snapshot in snapshots:
            account_type = str(snapshot.account_type or "")
            asset = str(snapshot.asset or "").strip().upper()
            if account_type not in {"simple_earn_flexible", "simple_earn_locked"} or not asset:
                continue
            products.add((asset, account_type, snapshot.product_id or None, snapshot.position_id or None))

        account = f"connection:{self.connection_id}"
        with self.store.connect() as con:
            rows = con.execute(
                """
                select distinct
                    upper(json_extract_string(raw.payload_json, '$.asset')) as asset,
                    json_extract_string(raw.payload_json, '$.account_type') as account_type,
                    nullif(json_extract_string(raw.payload_json, '$.product_id'), '') as product_id,
                    nullif(json_extract_string(raw.payload_json, '$.position_id'), '') as position_id
                from raw_objects raw
                join raw_import_batches batch using(batch_id)
                where lower(batch.source) = 'binance_simple_earn_api'
                  and batch.connection_id = ?
                  and json_extract_string(raw.payload_json, '$.account') = ?
                  and json_extract_string(raw.payload_json, '$.account_type')
                      in ('simple_earn_flexible', 'simple_earn_locked')
                  and coalesce(json_extract_string(raw.payload_json, '$.asset'), '') <> ''
                """,
                [self.connection_id, account],
            ).fetchall()
        for asset, account_type, product_id, position_id in rows:
            products.add((str(asset).upper(), str(account_type), product_id, position_id))
        return [
            {"asset": asset, "account_type": account_type,
             "product_id": product_id, "position_id": position_id}
            for asset, account_type, product_id, position_id in sorted(
                products, key=lambda item: (item[0], item[1], item[2] or "", item[3] or ""),
            )
        ]

    def api_preview(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        assets: list[str] | None = None,
        max_pages: int = 20,
        max_records: int = 5000,
    ) -> BinanceEarnHistoryApiPreview:
        since_at = since or datetime(2021, 1, 1, tzinfo=timezone.utc)
        until_at = until or datetime.now(timezone.utc)
        selected_assets = sorted({asset.strip().upper() for asset in (assets or []) if asset.strip()})
        api_key, secret_key = self._credentials()
        products = SourceService(self.store).binance_earn_history_preflight().products
        if selected_assets:
            products = [product for product in products if product.asset.upper() in selected_assets]
        elif products:
            selected_assets = sorted({product.asset.upper() for product in products})

        requests: list[BinanceEarnHistoryApiRequest] = []
        records: list[BinanceEarnHistoryApiRecord] = []
        if not api_key or not secret_key:
            return BinanceEarnHistoryApiPreview(
                generated_at=datetime.now(timezone.utc),
                credential_status="missing",
                since=since_at,
                until=until_at,
                assets=selected_assets,
                requests=[],
                records=[],
                records_returned=0,
                records_available_hint=0,
                truncated=False,
                methodology=(
                    "Read-only Binance Simple-Earn-History API Preview. "
                    "Credentials fehlen; es wurden keine Binance-Aufrufe ausgefuehrt."
                ),
            )

        for product in products:
            for spec in self._endpoint_specs(product.account_type):
                if len(records) >= max_records:
                    break
                for position_id in self._position_ids_for_spec(spec, product, records):
                    for window_start, window_end in self._time_windows(since_at, until_at):
                        params: dict[str, object] = {
                            "asset": product.asset,
                            "startTime": self._millis(window_start),
                            "endTime": self._millis(window_end),
                            "size": self.SIZE,
                        }
                        if spec["scope"] == "flexible" and product.product_id:
                            params["productId"] = product.product_id
                        if spec.get("use_position_id") == "true" and position_id:
                            params["positionId"] = position_id
                        if spec.get("reward_type"):
                            params["type"] = spec["reward_type"]
                        request, rows = self._fetch_pages(
                            api_key=api_key,
                            secret_key=secret_key,
                            endpoint=str(spec["endpoint"]),
                            record_type=str(spec["record_type"]),
                            asset=product.asset,
                            product_id=product.product_id,
                            position_id=position_id,
                            window_start=window_start,
                            window_end=window_end,
                            params=params,
                            max_pages=max_pages,
                            remaining=max_records - len(records),
                        )
                        requests.append(request)
                        records.extend(rows)
                        if len(records) >= max_records:
                            break
                    if len(records) >= max_records:
                        break

        available_hint = sum(item.records for item in requests)
        return BinanceEarnHistoryApiPreview(
            generated_at=datetime.now(timezone.utc),
            credential_status="configured",
            since=since_at,
            until=until_at,
            assets=selected_assets,
            requests=requests,
            records=records,
            records_returned=len(records),
            records_available_hint=available_hint,
            truncated=any(item.total is not None and item.records < item.total for item in requests)
            or len(records) >= max_records,
            methodology=(
                "Read-only Binance Simple-Earn-History API Preview ueber signierte "
                "USER_DATA-Endpunkte. Es werden Subscription-, Redemption- und "
                "Reward-Historien fuer aktuelle Live-Earn-Produkte abgefragt. "
                "Der Endpunkt schreibt keine Raw Objects, Canonical Events, FIFO-Lots "
                "oder Ledgerbuchungen."
            ),
        )

    def withdrawal_history_api_preview(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        assets: list[str] | None = None,
        max_records: int = 1000,
    ) -> BinanceCapitalWithdrawalPreview:
        since_at = since or datetime(2025, 1, 1, tzinfo=timezone.utc)
        until_at = until or datetime.now(timezone.utc)
        selected_assets = sorted({asset.strip().upper() for asset in (assets or []) if asset.strip()}) or ["JUP"]
        api_key, secret_key = self._credentials()
        if not api_key or not secret_key:
            return BinanceCapitalWithdrawalPreview(
                generated_at=datetime.now(timezone.utc),
                credential_status="missing",
                since=since_at,
                until=until_at,
                assets=selected_assets,
                methodology=(
                    "Read-only Binance Capital Withdraw-History API Preview. "
                    "Credentials fehlen; es wurden keine Binance-Aufrufe ausgefuehrt."
                ),
            )
        endpoint = "/sapi/v1/capital/withdraw/history"
        requests: list[BinanceCapitalWithdrawalRequest] = []
        records: list[BinanceCapitalWithdrawalRecord] = []
        for asset in selected_assets:
            for window_start, window_end in self._time_windows(since_at, until_at):
                if len(records) >= max_records:
                    break
                params = {
                    "coin": asset,
                    "startTime": self._millis(window_start),
                    "endTime": self._millis(window_end),
                    "recvWindow": 5000,
                }
                try:
                    payload = self._signed_get_any(api_key, secret_key, endpoint, params)
                    rows = payload if isinstance(payload, list) else payload.get("rows", []) if isinstance(payload, dict) else []
                    if not isinstance(rows, list):
                        rows = []
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        records.append(BinanceCapitalWithdrawalRecord(endpoint=endpoint, asset=asset, payload=dict(row)))
                        if len(records) >= max_records:
                            break
                    requests.append(
                        BinanceCapitalWithdrawalRequest(
                            endpoint=endpoint,
                            asset=asset,
                            window_start=window_start,
                            window_end=window_end,
                            records=len(rows),
                            status="ok",
                        )
                    )
                except Exception as exc:
                    requests.append(
                        BinanceCapitalWithdrawalRequest(
                            endpoint=endpoint,
                            asset=asset,
                            window_start=window_start,
                            window_end=window_end,
                            records=0,
                            status="error",
                            error=str(exc)[:240],
                        )
                    )
        return BinanceCapitalWithdrawalPreview(
            generated_at=datetime.now(timezone.utc),
            credential_status="configured",
            since=since_at,
            until=until_at,
            assets=selected_assets,
            requests=requests,
            records=records,
            records_returned=len(records),
            methodology=(
                "Read-only Binance Capital Withdraw-History API Preview ueber "
                "/sapi/v1/capital/withdraw/history. Liefert Adresse, Netzwerk und TXID, "
                "wenn Binance diese Daten bereitstellt. Der Endpunkt schreibt keine Daten."
            ),
        )

    def asset_dividend_history_api_preview(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        assets: list[str] | None = None,
        max_records: int = 5000,
    ) -> BinanceAssetDividendPreview:
        since_at = since or datetime(2021, 1, 1, tzinfo=timezone.utc)
        until_at = until or datetime.now(timezone.utc)
        selected_assets = sorted(
            {asset.strip().upper() for asset in (assets or ["SOL"]) if asset.strip()}
        )
        api_key, secret_key = self._credentials()
        if not api_key or not secret_key:
            return BinanceAssetDividendPreview(
                generated_at=datetime.now(timezone.utc),
                credential_status="missing",
                since=since_at,
                until=until_at,
                assets=selected_assets,
                methodology=(
                    "Read-only Binance Asset-Dividend-Preview. Credentials fehlen; "
                    "es wurden keine Binance-Aufrufe ausgefuehrt."
                ),
            )

        endpoint = "/sapi/v1/asset/assetDividend"
        requests: list[BinanceAssetDividendRequest] = []
        records: list[BinanceAssetDividendRecord] = []
        seen_refs: set[str] = set()
        truncated = False
        for asset in selected_assets:
            for window_start, window_end in self._dividend_time_windows(
                since_at, until_at
            ):
                if len(records) >= max_records:
                    truncated = True
                    break
                request, window_records, window_truncated = (
                    self._fetch_asset_dividend_window(
                        api_key=api_key,
                        secret_key=secret_key,
                        endpoint=endpoint,
                        asset=asset,
                        window_start=window_start,
                        window_end=window_end,
                        remaining=max_records - len(records),
                    )
                )
                requests.extend(request)
                truncated = truncated or window_truncated
                for record in window_records:
                    provider_ref = self._asset_dividend_provider_ref(record.payload)
                    if provider_ref in seen_refs:
                        continue
                    seen_refs.add(provider_ref)
                    records.append(record)
                    if len(records) >= max_records:
                        truncated = True
                        break

        return BinanceAssetDividendPreview(
            generated_at=datetime.now(timezone.utc),
            credential_status="configured",
            since=since_at,
            until=until_at,
            assets=selected_assets,
            requests=requests,
            records=records,
            records_returned=len(records),
            records_available_hint=sum(
                request.total if request.total is not None else request.records
                for request in requests
                if request.status != "split"
            ),
            truncated=truncated,
            methodology=(
                "Read-only Binance USER_DATA-Abfrage ueber "
                "/sapi/v1/asset/assetDividend. Zeitraeume werden wegen der "
                "offiziellen 180-Tage-Grenze in hoechstens 179 Tage zerlegt; "
                "uebervolle 500er-Antworten werden rekursiv geteilt. Es werden "
                "keine Raw Objects, Canonical Events, FIFO-Lots oder "
                "Ledgerbuchungen geschrieben."
            ),
        )

    def preview_harvest_import(self, harvest_path: str) -> BinanceEarnHarvestImportPreview:
        all_rows, rows, warnings, duplicate = self._prepared_rows_from_harvest(harvest_path)
        record_types = Counter(str(row.get("record_type") or "") for row in all_rows)
        assets = sorted({str(row.get("asset") or "").upper() for row in all_rows if row.get("asset")})
        blocked_reason = None
        if not all_rows:
            blocked_reason = "Harvest enthaelt keine importierbaren Simple-Earn-Records."
        elif not rows:
            blocked_reason = "Harvest enthaelt keine neuen Simple-Earn-Records."
        elif duplicate is not None:
            blocked_reason = f"Harvest wurde bereits importiert: {duplicate.batch_id}"
        return BinanceEarnHarvestImportPreview(
            harvest_path=harvest_path,
            can_execute=blocked_reason is None,
            blocked_reason=blocked_reason,
            records_total=len(all_rows),
            rows_prepared=len(rows),
            assets=assets,
            record_types={key: int(value) for key, value in sorted(record_types.items())},
            duplicate_batch_id=duplicate.batch_id if duplicate is not None else None,
            warnings=warnings,
        )

    def import_harvest(
        self,
        harvest_path: str,
        execute: bool = False,
    ) -> BinanceEarnHarvestImportResult:
        if execute and self.connection_id is not None:
            raise RuntimeError("binance_earn_connection_import_requires_history_job")
        preview = self.preview_harvest_import(harvest_path)
        if not execute or not preview.can_execute:
            return BinanceEarnHarvestImportResult(preview=preview)
        _all_rows, rows, _warnings, _duplicate = self._prepared_rows_from_harvest(harvest_path)
        file_hash = self._harvest_hash(rows)
        batch = CsvRawImporter(self.store).import_rows(
            source="binance_simple_earn_api",
            filename=str(harvest_path),
            file_hash=file_hash,
            rows=rows,
        )
        run = PipelineService(self.store).rebuild_after_import(batch.batch_id)
        return BinanceEarnHarvestImportResult(preview=preview, batch=batch, run=run)

    def import_api_history(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        assets: list[str] | None = None,
        max_pages: int = 200,
        max_records: int = 50000,
        execute: bool = False,
    ) -> BinanceEarnApiImportResult:
        if execute and self.connection_id is not None:
            raise RuntimeError("binance_earn_connection_import_requires_history_job")
        api_preview = self.api_preview(
            since=since,
            until=until,
            assets=assets,
            max_pages=max_pages,
            max_records=max_records,
        )
        all_rows, rows, warnings, duplicate = self._prepared_rows_from_api_preview(api_preview)
        import_preview = self._import_preview_from_rows(
            harvest_path=self._api_history_label(api_preview),
            all_rows=all_rows,
            rows=rows,
            warnings=warnings,
            duplicate=duplicate,
            empty_reason="Binance API lieferte keine importierbaren Simple-Earn-Records.",
            no_new_reason="Binance API lieferte keine neuen Simple-Earn-Records.",
        )
        if not execute or not import_preview.can_execute:
            return BinanceEarnApiImportResult(
                api_preview=api_preview,
                import_preview=import_preview,
            )
        file_hash = self._harvest_hash(rows)
        batch = CsvRawImporter(self.store).import_rows(
            source="binance_simple_earn_api",
            filename=import_preview.harvest_path,
            file_hash=file_hash,
            rows=rows,
        )
        run = PipelineService(self.store).rebuild_after_import(batch.batch_id)
        return BinanceEarnApiImportResult(
            api_preview=api_preview,
            import_preview=import_preview,
            batch=batch,
            run=run,
        )

    def import_withdrawal_api_history(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        assets: list[str] | None = None,
        max_records: int = 5000,
        execute: bool = False,
    ) -> BinanceCapitalWithdrawalApiImportResult:
        if execute and self.connection_id is not None:
            raise RuntimeError("binance_withdrawal_connection_import_requires_history_job")
        api_preview = self.withdrawal_history_api_preview(
            since=since,
            until=until,
            assets=assets,
            max_records=max_records,
        )
        all_rows, rows, warnings, duplicate = self._prepared_rows_from_withdrawal_api_preview(api_preview)
        import_preview = self._import_preview_from_rows(
            harvest_path=self._withdrawal_api_history_label(api_preview),
            all_rows=all_rows,
            rows=rows,
            warnings=warnings,
            duplicate=duplicate,
            empty_reason="Binance Withdrawal API lieferte keine importierbaren Beleg-Records.",
            no_new_reason="Binance Withdrawal API lieferte keine neuen Beleg-Records.",
        )
        if not execute or not import_preview.can_execute:
            return BinanceCapitalWithdrawalApiImportResult(
                api_preview=api_preview,
                import_preview=import_preview,
            )
        file_hash = self._harvest_hash(rows)
        batch = CsvRawImporter(self.store).import_rows(
            source="binance_withdrawal_api",
            filename=import_preview.harvest_path,
            file_hash=file_hash,
            rows=rows,
        )
        run = PipelineService(self.store).rebuild_after_import(batch.batch_id)
        return BinanceCapitalWithdrawalApiImportResult(
            api_preview=api_preview,
            import_preview=import_preview,
            batch=batch,
            run=run,
        )

    def import_asset_dividend_api_history(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        assets: list[str] | None = None,
        max_records: int = 5000,
        execute: bool = False,
    ) -> BinanceAssetDividendApiImportResult:
        if execute and self.connection_id is not None:
            raise RuntimeError("binance_dividend_connection_import_requires_history_job")
        api_preview = self.asset_dividend_history_api_preview(
            since=since,
            until=until,
            assets=assets,
            max_records=max_records,
        )
        all_rows, rows, warnings, duplicate = (
            self._prepared_rows_from_asset_dividend_preview(api_preview)
        )
        import_preview = self._import_preview_from_rows(
            harvest_path=self._asset_dividend_api_history_label(api_preview),
            all_rows=all_rows,
            rows=rows,
            warnings=warnings,
            duplicate=duplicate,
            empty_reason="Binance Asset Dividend API lieferte keine importierbaren Records.",
            no_new_reason="Binance Asset Dividend API lieferte keine neuen Records.",
        )
        if not execute or not import_preview.can_execute:
            return BinanceAssetDividendApiImportResult(
                api_preview=api_preview,
                import_preview=import_preview,
            )
        file_hash = self._harvest_hash(rows)
        batch = CsvRawImporter(self.store).import_rows(
            source="binance_asset_dividend_api",
            filename=import_preview.harvest_path,
            file_hash=file_hash,
            rows=rows,
        )
        run = PipelineService(self.store).rebuild_after_import(batch.batch_id)
        return BinanceAssetDividendApiImportResult(
            api_preview=api_preview,
            import_preview=import_preview,
            batch=batch,
            run=run,
        )

    def _prepared_rows_from_harvest(
        self,
        harvest_path: str,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]], list[str], object | None]:
        rows, warnings = self._rows_from_harvest(harvest_path)
        return self._prepared_rows(rows, warnings)

    def _prepared_rows_from_api_preview(
        self,
        api_preview: BinanceEarnHistoryApiPreview,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]], list[str], object | None]:
        rows: list[dict[str, object]] = []
        seen: set[str] = set()
        for record in api_preview.records:
            for row in self._rows_from_earn_record(record.model_dump(mode="json")):
                key = str(row.get("source_ref") or "")
                if key in seen:
                    continue
                seen.add(key)
                rows.append(row)
        warnings = []
        expanded_count = sum(
            len(self._rows_from_earn_record(record.model_dump(mode="json")))
            for record in api_preview.records
        )
        duplicate_count = expanded_count - len(rows)
        if duplicate_count:
            warnings.append(f"{duplicate_count} doppelte API-Records uebersprungen.")
        return self._prepared_rows(rows, warnings)

    def _prepared_rows_from_withdrawal_api_preview(
        self,
        api_preview: BinanceCapitalWithdrawalPreview,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]], list[str], object | None]:
        rows: list[dict[str, object]] = []
        seen: set[str] = set()
        for record in api_preview.records:
            row = self._row_from_withdrawal_record(record.payload)
            key = str(row.get("source_ref") or row.get("tx_id") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append(row)
        warnings: list[str] = []
        duplicate_count = len(api_preview.records) - len(rows)
        if duplicate_count:
            warnings.append(f"{duplicate_count} doppelte Withdrawal-API-Records uebersprungen.")
        full_hash = self._harvest_hash(rows)
        duplicate = self.store.get_import_batch_by_file_hash("binance_withdrawal_api", full_hash)
        existing_refs = self._existing_source_refs_for_source("binance_withdrawal_api")
        existing_tx_ids = self._existing_tx_ids_for_source("binance_withdrawal_api")
        prepared = [
            row
            for row in rows
            if str(row.get("source_ref") or "") not in existing_refs
            and str(row.get("tx_id") or "").strip() not in existing_tx_ids
        ]
        skipped_existing = len(rows) - len(prepared)
        if skipped_existing:
            warnings.append(f"{skipped_existing} bereits importierte Withdrawal-API-Belege uebersprungen.")
        return rows, prepared, warnings, duplicate

    def _prepared_rows_from_asset_dividend_preview(
        self,
        api_preview: BinanceAssetDividendPreview,
    ) -> tuple[list[dict[str, object]], list[dict[str, object]], list[str], object | None]:
        rows: list[dict[str, object]] = []
        seen: set[str] = set()
        for record in api_preview.records:
            row = self._row_from_asset_dividend_record(record.payload)
            key = str(row.get("source_ref") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append(row)
        warnings: list[str] = []
        duplicate_count = len(api_preview.records) - len(rows)
        if duplicate_count:
            warnings.append(
                f"{duplicate_count} doppelte Asset-Dividend-API-Records uebersprungen."
            )
        full_hash = self._harvest_hash(rows)
        duplicate = self.store.get_import_batch_by_file_hash(
            "binance_asset_dividend_api", full_hash
        )
        existing_refs = self._existing_source_refs_for_source(
            "binance_asset_dividend_api"
        )
        locked_reward_counter = self._existing_locked_reward_semantic_counter()
        prepared: list[dict[str, object]] = []
        skipped_existing = 0
        skipped_semantic = 0
        for row in rows:
            if str(row.get("source_ref") or "") in existing_refs:
                skipped_existing += 1
                continue
            semantic_key = self._locked_reward_semantic_key(row)
            if semantic_key is not None and locked_reward_counter[semantic_key] > 0:
                locked_reward_counter[semantic_key] -= 1
                skipped_semantic += 1
                continue
            prepared.append(row)
        if skipped_existing:
            warnings.append(
                f"{skipped_existing} bereits importierte Asset-Dividend-Belege uebersprungen."
            )
        if skipped_semantic:
            warnings.append(
                f"{skipped_semantic} bereits durch Binance-Ledger oder Simple-Earn-API "
                "belegte Locked-Rewards semantisch uebersprungen."
            )
        return rows, prepared, warnings, duplicate

    def _prepared_rows(
        self,
        rows: list[dict[str, object]],
        warnings: list[str],
    ) -> tuple[list[dict[str, object]], list[dict[str, object]], list[str], object | None]:
        full_hash = self._harvest_hash(rows)
        duplicate = self.store.get_import_batch_by_file_hash("binance_simple_earn_api", full_hash)
        existing_refs = self._existing_source_refs()
        existing_tx_ids = self._existing_tx_ids()
        locked_reward_counter = self._existing_locked_reward_semantic_counter()
        prepared: list[dict[str, object]] = []
        semantic_skipped = 0
        for row in rows:
            if str(row.get("source_ref") or "") in existing_refs:
                continue
            row_tx_id = self._row_tx_id(row)
            if (
                str(row.get("record_type") or "") != "locked_redemption_loss"
                and row_tx_id
                and row_tx_id in existing_tx_ids
            ):
                continue
            semantic_key = self._locked_reward_semantic_key(row)
            if semantic_key is not None and locked_reward_counter[semantic_key] > 0:
                locked_reward_counter[semantic_key] -= 1
                semantic_skipped += 1
                continue
            prepared.append(row)
        skipped_existing = len(rows) - len(prepared)
        if skipped_existing:
            warnings.append(f"{skipped_existing} bereits importierte Simple-Earn-Records uebersprungen.")
        if semantic_skipped:
            warnings.append(
                f"{semantic_skipped} bereits im Binance-Ledger belegte Locked-Rewards "
                "semantisch erkannt."
            )
        return rows, prepared, warnings, duplicate

    def _import_preview_from_rows(
        self,
        *,
        harvest_path: str,
        all_rows: list[dict[str, object]],
        rows: list[dict[str, object]],
        warnings: list[str],
        duplicate: object | None,
        empty_reason: str,
        no_new_reason: str,
    ) -> BinanceEarnHarvestImportPreview:
        record_types = Counter(str(row.get("record_type") or "") for row in all_rows)
        assets = sorted({str(row.get("asset") or "").upper() for row in all_rows if row.get("asset")})
        blocked_reason = None
        if not all_rows:
            blocked_reason = empty_reason
        elif not rows:
            blocked_reason = no_new_reason
        elif duplicate is not None:
            blocked_reason = f"Harvest wurde bereits importiert: {duplicate.batch_id}"
        return BinanceEarnHarvestImportPreview(
            harvest_path=harvest_path,
            can_execute=blocked_reason is None,
            blocked_reason=blocked_reason,
            records_total=len(all_rows),
            rows_prepared=len(rows),
            assets=assets,
            record_types={key: int(value) for key, value in sorted(record_types.items())},
            duplicate_batch_id=duplicate.batch_id if duplicate is not None else None,
            warnings=warnings,
        )

    def _rows_from_harvest(self, harvest_path: str) -> tuple[list[dict[str, object]], list[str]]:
        path = Path(harvest_path)
        if path.is_dir():
            path = path / "binance_simple_earn_history_preview.json"
        warnings: list[str] = []
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = payload.get("records") if isinstance(payload, dict) else []
        if not isinstance(records, list):
            return [], ["Harvest JSON enthaelt keine Records-Liste."]
        rows: list[dict[str, object]] = []
        seen: set[str] = set()
        expanded_count = 0
        for record in records:
            if not isinstance(record, dict):
                continue
            expanded_rows = self._rows_from_earn_record(record)
            expanded_count += len(expanded_rows)
            for row in expanded_rows:
                key = str(row.get("source_ref") or "")
                if key in seen:
                    continue
                seen.add(key)
                rows.append(row)
        if len(rows) != expanded_count:
            warnings.append(
                f"{expanded_count - len(rows)} doppelte Harvest-Records uebersprungen."
            )
        return rows, warnings

    def _existing_source_refs(self) -> set[str]:
        return self._existing_source_refs_for_source("binance_simple_earn_api")

    def _existing_source_refs_for_source(self, source: str) -> set[str]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select distinct source_ref
                from canonical_events
                where source = ?
                  and source_ref is not null
                """,
                [source],
            ).fetchall()
        return {str(row[0]) for row in rows if row[0]}

    def _existing_tx_ids(self) -> set[str]:
        return self._existing_tx_ids_for_source("binance_simple_earn_api")

    def _existing_tx_ids_for_source(self, source: str) -> set[str]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select distinct tx_id
                from canonical_events
                where source = ?
                  and tx_id is not null
                """,
                [source],
            ).fetchall()
        return {str(row[0]) for row in rows if row[0]}

    def _row_tx_id(self, row: dict[str, object]) -> str:
        return str(row.get("purchase_id") or row.get("redeem_id") or "").strip()

    def _api_history_label(self, api_preview: BinanceEarnHistoryApiPreview) -> str:
        since = api_preview.since.astimezone(timezone.utc).strftime("%Y%m%d")
        until = api_preview.until.astimezone(timezone.utc).strftime("%Y%m%d")
        assets = "-".join(api_preview.assets) if api_preview.assets else "all"
        return f"binance-simple-earn-api-{since}-{until}-{assets}.json"

    def _withdrawal_api_history_label(self, api_preview: BinanceCapitalWithdrawalPreview) -> str:
        since = api_preview.since.astimezone(timezone.utc).strftime("%Y%m%d")
        until = api_preview.until.astimezone(timezone.utc).strftime("%Y%m%d")
        assets = "-".join(api_preview.assets) if api_preview.assets else "all"
        return f"binance-withdrawal-api-{since}-{until}-{assets}.json"

    def _asset_dividend_api_history_label(
        self, api_preview: BinanceAssetDividendPreview
    ) -> str:
        since = api_preview.since.astimezone(timezone.utc).strftime("%Y%m%d")
        until = api_preview.until.astimezone(timezone.utc).strftime("%Y%m%d")
        assets = "-".join(api_preview.assets) if api_preview.assets else "all"
        return f"binance-asset-dividend-api-{since}-{until}-{assets}.json"

    def _row_from_withdrawal_record(self, payload: dict[str, object]) -> dict[str, object]:
        amount = self._decimal_from_payload(payload.get("amount"))
        fee = self._decimal_from_payload(
            payload.get("transactionFee")
            or payload.get("transaction_fee")
            or payload.get("fee")
            or "0"
        )
        gross = amount + fee
        asset = str(payload.get("coin") or payload.get("asset") or "").upper()
        tx_id = str(payload.get("txId") or payload.get("txid") or payload.get("tx_id") or "")
        source_ref = str(payload.get("id") or tx_id)
        complete_time = str(payload.get("completeTime") or payload.get("complete_time") or "")
        apply_time = str(payload.get("applyTime") or payload.get("apply_time") or "")
        return {
            "record_type": "capital_withdrawal_evidence",
            "operation": "Withdraw",
            "asset": asset,
            "coin": asset,
            "amount": str(amount),
            "transaction_fee": str(fee),
            "gross_amount": str(gross),
            "complete_time": complete_time or apply_time,
            "apply_time": apply_time or complete_time,
            "account": "Binance Withdrawal Evidence",
            "address": str(payload.get("address") or ""),
            "network": str(payload.get("network") or ""),
            "tx_id": tx_id,
            "source_ref": source_ref,
            "status": str(payload.get("status") or ""),
        }

    def _row_from_asset_dividend_record(
        self, payload: dict[str, object]
    ) -> dict[str, object]:
        asset = str(payload.get("asset") or "").upper()
        dividend_id = str(payload.get("id") or "")
        transaction_id = str(payload.get("tranId") or payload.get("tran_id") or "")
        source_ref = self._asset_dividend_provider_ref(payload)
        timestamp = payload.get("divTime") or payload.get("div_time")
        return {
            "record_type": "asset_dividend",
            "asset": asset,
            "amount": str(payload.get("amount") or "0"),
            "direction": str(payload.get("direction") or "1"),
            "div_time": str(timestamp or ""),
            "time_iso": self._millis_to_iso(timestamp),
            "en_info": str(payload.get("enInfo") or payload.get("en_info") or ""),
            "dividend_id": dividend_id,
            "tran_id": transaction_id,
            "source_ref": source_ref,
            "account": "Spot",
            "provider_evidence": "binance_asset_dividend_user_data",
        }

    @staticmethod
    def _decimal_from_payload(value: object) -> Decimal:
        if value in (None, ""):
            return Decimal("0")
        try:
            return Decimal(str(value).strip().replace(",", "."))
        except (InvalidOperation, ValueError):
            return Decimal("0")

    def _rows_from_earn_record(
        self, record: dict[str, object]
    ) -> list[dict[str, object]]:
        base = self._row_from_harvest_record(record)
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        if not isinstance(payload, dict):
            return [base]
        record_type = str(record.get("record_type") or "")
        loss_amount = self._decimal_from_payload(payload.get("lossAmount"))
        if record_type != "locked_redemption" or loss_amount <= 0:
            return [base]
        asset = str(payload.get("rewardAsset") or base.get("asset") or "").upper()
        position_id = str(payload.get("positionId") or base.get("position_id") or "")
        redeem_id = str(payload.get("redeemId") or base.get("redeem_id") or "")
        loss_row = {
            **base,
            "record_type": "locked_redemption_loss",
            "asset": asset,
            "amount": str(loss_amount),
            "rewards": "",
            "position_id": position_id,
            "redeem_id": redeem_id,
            "source_ref": ":".join(
                part
                for part in (
                    "locked_redemption_loss",
                    asset,
                    position_id,
                    redeem_id,
                )
                if part
            ),
            "loss_amount": str(loss_amount),
            "provider_adjustment_kind": "early_redemption_reward_clawback",
            "provider_evidence": "binance_simple_earn_redemption_record",
        }
        return [base, loss_row]

    def _row_from_harvest_record(self, record: dict[str, object]) -> dict[str, object]:
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        if not isinstance(payload, dict):
            payload = {}
        record_type = str(record.get("record_type") or "")
        asset = str(record.get("asset") or payload.get("asset") or "").upper()
        product_id = str(payload.get("productId") or record.get("product_id") or "")
        position_id = str(payload.get("positionId") or record.get("position_id") or "")
        timestamp = payload.get("time")
        time_iso = self._millis_to_iso(timestamp)
        amount = payload.get("amount") or payload.get("rewards") or payload.get("principal") or "0"
        source_ref = ":".join(
            part
            for part in (
                record_type,
                asset,
                product_id,
                position_id,
                str(payload.get("purchaseId") or payload.get("redeemId") or timestamp or ""),
            )
            if part
        )
        account_type = (
            "simple_earn_locked"
            if "locked" in record_type
            else "simple_earn_flexible"
        )
        return {
            "record_type": record_type,
            "asset": asset,
            "amount": amount if "reward" not in record_type else "",
            "rewards": amount if "reward" in record_type else "",
            "time": str(timestamp or ""),
            "time_iso": time_iso,
            "account_type": account_type,
            "product_id": product_id,
            "position_id": position_id,
            "purchase_id": str(payload.get("purchaseId") or ""),
            "redeem_id": str(payload.get("redeemId") or ""),
            "status": str(payload.get("status") or ""),
            "type": str(payload.get("type") or ""),
            "loss_amount": str(payload.get("lossAmount") or ""),
            "original_amount": str(payload.get("originalAmount") or ""),
            "reward_amount": str(payload.get("rewardAmt") or ""),
            "reward_asset": str(payload.get("rewardAsset") or ""),
            "deliver_date": str(payload.get("deliverDate") or ""),
            "is_complete": str(payload.get("isComplete") or ""),
            "source_ref": source_ref,
        }

    @staticmethod
    def _asset_dividend_provider_ref(payload: dict[str, object]) -> str:
        provider_id = str(payload.get("id") or "").strip()
        transaction_id = str(payload.get("tranId") or payload.get("tran_id") or "").strip()
        timestamp = str(payload.get("divTime") or payload.get("div_time") or "").strip()
        asset = str(payload.get("asset") or "").upper()
        amount = str(payload.get("amount") or "")
        identifier = provider_id or transaction_id or f"{timestamp}:{asset}:{amount}"
        return f"asset_dividend:{identifier}"

    def _millis_to_iso(self, value: object) -> str:
        try:
            millis = int(str(value))
        except Exception:
            return ""
        return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).isoformat()

    def _harvest_hash(self, rows: list[dict[str, object]]) -> str:
        return "sha256:" + hashlib.sha256(
            json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def _existing_locked_reward_semantic_counter(
        self,
    ) -> Counter[tuple[str, str, Decimal]]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select e.event_time, upper(e.asset), e.quantity, lower(e.source),
                       r.payload_json
                from canonical_events e
                left join raw_objects r on r.raw_object_id = e.raw_object_id
                where lower(e.source) in (
                    'binance',
                    'binance_simple_earn_api',
                    'binance_asset_dividend_api'
                )
                  and e.quantity > 0
                  and e.event_type in ('reward', 'staking', 'income')
                """
            ).fetchall()
        result: Counter[tuple[str, str, Decimal]] = Counter()
        for event_time, asset, quantity, source, payload_json in rows:
            try:
                payload = json.loads(payload_json or "{}")
            except (json.JSONDecodeError, TypeError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            record_type = str(
                payload.get("record_type") or payload.get("record type") or ""
            ).lower()
            operation = str(payload.get("Operation") or payload.get("operation") or "").lower()
            en_info = str(payload.get("en_info") or payload.get("enInfo") or "").lower()
            is_locked_reward = (
                (source == "binance" and "simple earn locked rewards" in operation)
                or (
                    source == "binance_simple_earn_api"
                    and record_type == "locked_rewards"
                )
                or (
                    source == "binance_asset_dividend_api"
                    and "locked" in en_info
                )
            )
            if not is_locked_reward:
                continue
            normalized_time = (
                event_time.replace(tzinfo=timezone.utc)
                if event_time.tzinfo is None
                else event_time.astimezone(timezone.utc)
            )
            result[(str(asset).upper(), normalized_time.date().isoformat(), abs(quantity))] += 1
        return result

    def _locked_reward_semantic_key(
        self, row: dict[str, object]
    ) -> tuple[str, str, Decimal] | None:
        record_type = str(row.get("record_type") or "").lower()
        en_info = str(row.get("en_info") or "").lower()
        if record_type != "locked_rewards" and "locked" not in en_info:
            return None
        amount = self._decimal_from_payload(row.get("rewards") or row.get("amount"))
        if amount <= 0:
            return None
        time_text = str(
            row.get("time_iso") or row.get("time") or row.get("div_time") or ""
        ).strip()
        try:
            if time_text.isdigit():
                event_time = datetime.fromtimestamp(
                    int(time_text) / 1000, tz=timezone.utc
                )
            else:
                event_time = datetime.fromisoformat(time_text.replace("Z", "+00:00"))
                if event_time.tzinfo is None:
                    event_time = event_time.replace(tzinfo=timezone.utc)
                else:
                    event_time = event_time.astimezone(timezone.utc)
        except (ValueError, OverflowError):
            return None
        return (
            str(row.get("asset") or "").upper(),
            event_time.date().isoformat(),
            abs(amount),
        )

    def _fetch_asset_dividend_window(
        self,
        *,
        api_key: str,
        secret_key: str,
        endpoint: str,
        asset: str,
        window_start: datetime,
        window_end: datetime,
        remaining: int,
    ) -> tuple[
        list[BinanceAssetDividendRequest],
        list[BinanceAssetDividendRecord],
        bool,
    ]:
        params: dict[str, object] = {
            "asset": asset,
            "startTime": self._millis(window_start),
            "endTime": self._millis(window_end),
            "limit": self.DIVIDEND_LIMIT,
            "recvWindow": 5000,
        }
        try:
            payload = self._signed_get_with_retries(
                api_key, secret_key, endpoint, params
            )
            raw_rows = payload.get("rows") if isinstance(payload, dict) else []
            if not isinstance(raw_rows, list):
                raw_rows = []
            total = int(payload.get("total") or len(raw_rows))
            request = BinanceAssetDividendRequest(
                endpoint=endpoint,
                asset=asset,
                window_start=window_start,
                window_end=window_end,
                records=len(raw_rows),
                total=total,
                status="ok",
            )
            if total > len(raw_rows) and window_end - window_start > timedelta(days=1):
                midpoint = window_start + (window_end - window_start) / 2
                request = request.model_copy(update={"status": "split"})
                left_requests, left_records, left_truncated = (
                    self._fetch_asset_dividend_window(
                        api_key=api_key,
                        secret_key=secret_key,
                        endpoint=endpoint,
                        asset=asset,
                        window_start=window_start,
                        window_end=midpoint,
                        remaining=remaining,
                    )
                )
                right_remaining = max(remaining - len(left_records), 0)
                if right_remaining == 0:
                    return [request, *left_requests], left_records, True
                right_requests, right_records, right_truncated = (
                    self._fetch_asset_dividend_window(
                        api_key=api_key,
                        secret_key=secret_key,
                        endpoint=endpoint,
                        asset=asset,
                        window_start=midpoint + timedelta(milliseconds=1),
                        window_end=window_end,
                        remaining=right_remaining,
                    )
                )
                return (
                    [request, *left_requests, *right_requests],
                    [*left_records, *right_records],
                    left_truncated or right_truncated,
                )
            records = [
                BinanceAssetDividendRecord(
                    endpoint=endpoint,
                    asset=asset,
                    payload=dict(row),
                )
                for row in raw_rows[:remaining]
                if isinstance(row, dict)
            ]
            return [request], records, total > len(records)
        except Exception as exc:
            return (
                [
                    BinanceAssetDividendRequest(
                        endpoint=endpoint,
                        asset=asset,
                        window_start=window_start,
                        window_end=window_end,
                        status="error",
                        error=str(exc)[:240],
                    )
                ],
                [],
                False,
            )

    def _position_ids_for_spec(
        self,
        spec: dict[str, str],
        product: object,
        records: list[BinanceEarnHistoryApiRecord],
    ) -> list[str]:
        if spec.get("use_position_id") != "true":
            return [""]
        position_ids: list[str] = []
        current = str(getattr(product, "position_id", "") or "").strip()
        if current:
            position_ids.append(current)
        if spec.get("discover_position_ids") == "true":
            asset = str(getattr(product, "asset", "") or "").upper()
            product_id = str(getattr(product, "product_id", "") or "")
            for record in records:
                if str(record.asset or "").upper() != asset:
                    continue
                if product_id and str(record.product_id or "") != product_id:
                    continue
                payload = record.payload if isinstance(record.payload, dict) else {}
                discovered = str(
                    payload.get("positionId")
                    or record.position_id
                    or ""
                ).strip()
                if discovered:
                    position_ids.append(discovered)
        deduped: list[str] = []
        for position_id in position_ids:
            if position_id not in deduped:
                deduped.append(position_id)
        return deduped or [""]

    def _fetch_pages(
        self,
        *,
        api_key: str,
        secret_key: str,
        endpoint: str,
        record_type: str,
        asset: str,
        product_id: str | None,
        position_id: str | None,
        window_start: datetime,
        window_end: datetime,
        params: dict[str, object],
        max_pages: int,
        remaining: int,
    ) -> tuple[BinanceEarnHistoryApiRequest, list[BinanceEarnHistoryApiRecord]]:
        records: list[BinanceEarnHistoryApiRecord] = []
        total = None
        pages_requested = 0
        try:
            for page in range(1, max(max_pages, 0) + 1):
                if len(records) >= remaining:
                    break
                page_params = {**params, "current": page}
                payload = self._signed_get_with_retries(api_key, secret_key, endpoint, page_params)
                pages_requested += 1
                rows = payload.get("rows") if isinstance(payload, dict) else None
                if isinstance(payload, dict) and payload.get("total") is not None:
                    total = int(payload.get("total") or 0)
                if not isinstance(rows, list) or not rows:
                    break
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    records.append(
                        BinanceEarnHistoryApiRecord(
                            endpoint=endpoint,
                            asset=asset,
                            product_id=product_id,
                            position_id=position_id,
                            record_type=record_type,
                            payload=dict(row),
                        )
                    )
                    if len(records) >= remaining:
                        break
                if total is not None and len(records) >= total:
                    break
                if len(rows) < self.SIZE:
                    break
            status = "ok"
            error = None
        except Exception as exc:
            status = "error"
            error = str(exc)[:240]
        return (
            BinanceEarnHistoryApiRequest(
                endpoint=endpoint,
                record_type=record_type,
                asset=asset,
                product_id=product_id,
                position_id=position_id,
                window_start=window_start,
                window_end=window_end,
                pages_requested=pages_requested,
                records=len(records),
                total=total,
                status=status,
                error=error,
            ),
            records,
        )

    def _signed_get(
        self,
        api_key: str,
        secret_key: str,
        endpoint: str,
        params: dict[str, object],
    ) -> dict[str, Any]:
        payload = self._signed_get_any(api_key, secret_key, endpoint, params)
        if not isinstance(payload, dict):
            raise RuntimeError("binance_unexpected_payload")
        return payload

    def _signed_get_any(
        self,
        api_key: str,
        secret_key: str,
        endpoint: str,
        params: dict[str, object],
    ) -> object:
        def sign(request: httpx.Request) -> None:
            query = urllib.parse.urlencode({**params, "timestamp": self._millis(datetime.now(timezone.utc))})
            signature = hmac.new(secret_key.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
            request.url = httpx.URL(f"{self.BASE_URL}{endpoint}?{query}&signature={signature}")
        with request_signer(sign), managed_client(timeout=30) as client:
            response = client.get(f"{self.BASE_URL}{endpoint}", headers={"X-MBX-APIKEY": api_key})
            if response.status_code >= 400:
                raise RuntimeError(self._binance_error_message(response))
            return response.json()

    def _signed_get_with_retries(
        self,
        api_key: str,
        secret_key: str,
        endpoint: str,
        params: dict[str, object],
    ) -> dict[str, Any]:
        # Retry-Zahl und Wartezeiten gehoeren ausschliesslich dem gemeinsamen Transport.
        return self._signed_get(api_key, secret_key, endpoint, params)

    def _binance_error_message(self, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            code = payload.get("code")
            if str(code).lstrip("-").isdigit():
                return f"binance_http_{response.status_code}: code={code}"
        return f"binance_http_{response.status_code}"

    def _credentials(self) -> tuple[str, str]:
        if self.connection_id is not None:
            from steuerreport_v2.domain.connections import ConnectionService

            api_key, secret_key, _passphrase = ConnectionService(self.store).credentials(
                self.connection_id, "binance"
            )
            return api_key, secret_key
        api_key = (
            self._secret_value("secret.cex.binance.api_key")
            or self._secret_value("secret.binance.api_key")
            or os.environ.get("BINANCE_API_KEY", "")
        )
        secret_key = (
            self._secret_value("secret.cex.binance.api_secret")
            or self._secret_value("secret.binance.secret_key")
            or os.environ.get("BINANCE_SECRET_KEY", "")
        )
        if not secret_key:
            secret_key = self._secret_value("secret.binance.api_secret") or os.environ.get("BINANCE_API_SECRET", "")
        return str(api_key).strip(), str(secret_key).strip()

    def _secret_value(self, key: str) -> str:
        return resolve_secret_value(self.store, key)

    def _endpoint_specs(self, account_type: str) -> list[dict[str, str]]:
        if account_type == "simple_earn_locked":
            return [
                {
                    "scope": "locked",
                    "record_type": "locked_subscription",
                    "endpoint": "/sapi/v1/simple-earn/locked/history/subscriptionRecord",
                },
                {
                    "scope": "locked",
                    "record_type": "locked_redemption",
                    "endpoint": "/sapi/v1/simple-earn/locked/history/redemptionRecord",
                    "use_position_id": "true",
                    "discover_position_ids": "true",
                },
                {
                    "scope": "locked",
                    "record_type": "locked_rewards",
                    "endpoint": "/sapi/v1/simple-earn/locked/history/rewardsRecord",
                    "use_position_id": "true",
                    "discover_position_ids": "true",
                },
            ]
        return [
            {
                "scope": "flexible",
                "record_type": "flexible_subscription",
                "endpoint": "/sapi/v1/simple-earn/flexible/history/subscriptionRecord",
            },
            {
                "scope": "flexible",
                "record_type": "flexible_redemption",
                "endpoint": "/sapi/v1/simple-earn/flexible/history/redemptionRecord",
            },
            {
                "scope": "flexible",
                "record_type": "flexible_rewards_realtime",
                "endpoint": "/sapi/v1/simple-earn/flexible/history/rewardsRecord",
                "reward_type": "REALTIME",
            },
            {
                "scope": "flexible",
                "record_type": "flexible_rewards_bonus",
                "endpoint": "/sapi/v1/simple-earn/flexible/history/rewardsRecord",
                "reward_type": "BONUS",
            },
            {
                "scope": "flexible",
                "record_type": "flexible_rewards_rewards",
                "endpoint": "/sapi/v1/simple-earn/flexible/history/rewardsRecord",
                "reward_type": "REWARDS",
            },
        ]

    def _millis(self, value: datetime) -> int:
        normalized = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return int(normalized.timestamp() * 1000)

    def _time_windows(self, since: datetime, until: datetime) -> list[tuple[datetime, datetime]]:
        start = since if since.tzinfo is not None else since.replace(tzinfo=timezone.utc)
        end = until if until.tzinfo is not None else until.replace(tzinfo=timezone.utc)
        if end < start:
            return []
        windows: list[tuple[datetime, datetime]] = []
        current = start
        while current <= end:
            window_end = min(current + timedelta(days=self.WINDOW_DAYS), end)
            windows.append((current, window_end))
            current = window_end + timedelta(milliseconds=1)
        return windows

    def _dividend_time_windows(
        self, since: datetime, until: datetime
    ) -> list[tuple[datetime, datetime]]:
        start = since if since.tzinfo is not None else since.replace(tzinfo=timezone.utc)
        end = until if until.tzinfo is not None else until.replace(tzinfo=timezone.utc)
        if end < start:
            return []
        windows: list[tuple[datetime, datetime]] = []
        current = start
        while current <= end:
            window_end = min(
                current + timedelta(days=self.DIVIDEND_WINDOW_DAYS), end
            )
            windows.append((current, window_end))
            current = window_end + timedelta(milliseconds=1)
        return windows
