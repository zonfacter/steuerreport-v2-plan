from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse

import httpx

from steuerreport_v2.contracts.binance_earn_import import BinanceEarnHarvestImportPreview
from steuerreport_v2.contracts.bitget import (
    BitgetWithdrawalPreview,
    BitgetWithdrawalRecord,
    BitgetWithdrawalRequest,
)
from steuerreport_v2.contracts.bitget_import import BitgetWithdrawalApiImportResult
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.secrets import resolve_secret_value
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter


class BitgetWalletHistoryService:
    BASE_URL = "https://api.bitget.com"
    WITHDRAWAL_ENDPOINT = "/api/v2/spot/wallet/withdrawal-records"
    PAGE_SIZE = 100
    WINDOW_DAYS = 29

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def withdrawal_history_api_preview(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        assets: list[str] | None = None,
        max_records: int = 5000,
    ) -> BitgetWithdrawalPreview:
        since_at = since or datetime(2025, 6, 14, tzinfo=timezone.utc)
        until_at = until or datetime(2025, 6, 16, 23, 59, 59, tzinfo=timezone.utc)
        selected_assets = sorted({asset.strip().upper() for asset in (assets or []) if asset.strip()}) or ["JUP", "SOL"]
        api_key, api_secret, passphrase = self._credentials()
        if not api_key or not api_secret or not passphrase:
            return BitgetWithdrawalPreview(
                generated_at=datetime.now(timezone.utc),
                credential_status="missing",
                since=since_at,
                until=until_at,
                assets=selected_assets,
                methodology=(
                    "Read-only Bitget Withdrawal-List API Preview. Credentials "
                    "fehlen; es wurden keine Bitget-Aufrufe ausgefuehrt."
                ),
            )

        requests: list[BitgetWithdrawalRequest] = []
        records: list[BitgetWithdrawalRecord] = []
        for asset in selected_assets:
            for window_start, window_end in self._time_windows(since_at, until_at):
                if len(records) >= max_records:
                    break
                page_no = 1
                id_less_than = ""
                while len(records) < max_records:
                    params = {
                        "coin": asset,
                        "startTime": self._millis(window_start),
                        "endTime": self._millis(window_end),
                        "limit": self.PAGE_SIZE,
                    }
                    if id_less_than:
                        params["idLessThan"] = id_less_than
                    try:
                        payload = self._signed_get(api_key, api_secret, passphrase, self.WITHDRAWAL_ENDPOINT, params)
                        rows = payload.get("data") if isinstance(payload, dict) else []
                        if not isinstance(rows, list):
                            rows = []
                        for row in rows:
                            if isinstance(row, dict):
                                records.append(BitgetWithdrawalRecord(endpoint=self.WITHDRAWAL_ENDPOINT, asset=asset, payload=dict(row)))
                                if len(records) >= max_records:
                                    break
                        requests.append(
                            BitgetWithdrawalRequest(
                                endpoint=self.WITHDRAWAL_ENDPOINT,
                                asset=asset,
                                window_start=window_start,
                                window_end=window_end,
                                page_no=page_no,
                                records=len(rows),
                                status="ok",
                            )
                        )
                    except Exception as exc:
                        requests.append(
                            BitgetWithdrawalRequest(
                                endpoint=self.WITHDRAWAL_ENDPOINT,
                                asset=asset,
                                window_start=window_start,
                                window_end=window_end,
                                page_no=page_no,
                                records=0,
                                status="error",
                                error=str(exc)[:240],
                            )
                        )
                        break
                    if len(rows) < self.PAGE_SIZE:
                        break
                    id_less_than = self._pagination_id(rows[-1])
                    if not id_less_than:
                        break
                    page_no += 1
                if len(records) >= max_records:
                    break

        return BitgetWithdrawalPreview(
            generated_at=datetime.now(timezone.utc),
            credential_status="configured",
            since=since_at,
            until=until_at,
            assets=selected_assets,
            requests=requests,
            records=records,
            records_returned=len(records),
            methodology=(
                "Read-only Bitget Withdrawal Records API Preview ueber "
                "/api/v2/spot/wallet/withdrawal-records. Liefert Betrag, Status, "
                "Zieladresse, Chain, TXID und Zeitstempel, wenn Bitget diese Daten "
                "bereitstellt. Der Preview-Endpunkt schreibt keine Daten."
            ),
        )

    def import_withdrawal_api_history(
        self,
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        assets: list[str] | None = None,
        max_records: int = 5000,
        execute: bool = False,
    ) -> BitgetWithdrawalApiImportResult:
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
        )
        if not execute or not import_preview.can_execute:
            return BitgetWithdrawalApiImportResult(api_preview=api_preview, import_preview=import_preview)
        file_hash = self._rows_hash(rows)
        batch = CsvRawImporter(self.store).import_rows(
            source="bitget",
            filename=import_preview.harvest_path,
            file_hash=file_hash,
            rows=rows,
        )
        run = PipelineService(self.store).rebuild_after_import(batch.batch_id)
        return BitgetWithdrawalApiImportResult(api_preview=api_preview, import_preview=import_preview, batch=batch, run=run)

    def _prepared_rows_from_withdrawal_api_preview(
        self,
        api_preview: BitgetWithdrawalPreview,
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
            warnings.append(f"{duplicate_count} doppelte Bitget-Withdrawal-API-Records uebersprungen.")
        full_hash = self._rows_hash(rows)
        duplicate = self.store.get_import_batch_by_file_hash("bitget", full_hash)
        existing_refs = self._existing_source_refs_for_source("bitget")
        existing_tx_ids = self._existing_tx_ids_for_source("bitget")
        prepared = [
            row
            for row in rows
            if str(row.get("source_ref") or "") not in existing_refs
            and str(row.get("tx_id") or "").strip() not in existing_tx_ids
        ]
        skipped_existing = len(rows) - len(prepared)
        if skipped_existing:
            warnings.append(f"{skipped_existing} bereits importierte Bitget-Withdrawal-Belege uebersprungen.")
        return rows, prepared, warnings, duplicate

    def _import_preview_from_rows(
        self,
        *,
        harvest_path: str,
        all_rows: list[dict[str, object]],
        rows: list[dict[str, object]],
        warnings: list[str],
        duplicate: object | None,
    ) -> BinanceEarnHarvestImportPreview:
        record_types = Counter(str(row.get("type") or row.get("record_type") or "") for row in all_rows)
        assets = sorted({str(row.get("coin") or row.get("asset") or "").upper() for row in all_rows if row.get("coin") or row.get("asset")})
        blocked_reason = None
        if not all_rows:
            blocked_reason = "Bitget Withdrawal API lieferte keine importierbaren Beleg-Records."
        elif not rows:
            blocked_reason = "Bitget Withdrawal API lieferte keine neuen Beleg-Records."
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

    def _row_from_withdrawal_record(self, payload: dict[str, object]) -> dict[str, object]:
        amount = self._decimal_from_payload(payload.get("size") or payload.get("amount"))
        fee = self._decimal_from_payload(payload.get("fee"))
        asset = str(payload.get("coin") or "").upper()
        tx_id = str(payload.get("tradeId") or payload.get("txId") or payload.get("txid") or payload.get("tx_id") or "")
        source_ref = str(payload.get("orderId") or payload.get("id") or tx_id)
        c_time = str(payload.get("cTime") or payload.get("ctime") or "")
        u_time = str(payload.get("uTime") or payload.get("utime") or "")
        address = str(payload.get("toAddress") or payload.get("address") or "")
        chain = str(payload.get("chain") or payload.get("network") or "")
        return {
            "record_type": "bitget_withdrawal_evidence",
            "type": str(payload.get("type") or "withdraw"),
            "asset": asset,
            "coin": asset,
            "size": str(amount),
            "amount": str(amount),
            "quantity": str(amount),
            "fee": str(fee),
            "withdrawal fee": str(fee),
            "cTime": c_time,
            "uTime": u_time,
            "time": self._millis_to_iso(u_time or c_time),
            "account": "bitget",
            "address": address,
            "toAddress": address,
            "chain": chain,
            "network": chain,
            "tx_id": tx_id,
            "txId": tx_id,
            "tradeId": tx_id,
            "source_ref": source_ref,
            "orderId": str(payload.get("orderId") or ""),
            "dest": str(payload.get("dest") or ""),
            "status": str(payload.get("status") or ""),
            "clientOid": str(payload.get("clientOid") or ""),
        }

    @staticmethod
    def _pagination_id(row: object) -> str:
        if not isinstance(row, dict):
            return ""
        return str(row.get("orderId") or row.get("id") or "").strip()

    @staticmethod
    def _withdrawal_api_history_label(api_preview: BitgetWithdrawalPreview) -> str:
        since = api_preview.since.astimezone(timezone.utc).strftime("%Y%m%d")
        until = api_preview.until.astimezone(timezone.utc).strftime("%Y%m%d")
        assets = "-".join(api_preview.assets) if api_preview.assets else "all"
        return f"bitget-withdrawal-api-{since}-{until}-{assets}.csv"

    def _signed_get(
        self,
        api_key: str,
        api_secret: str,
        passphrase: str,
        endpoint: str,
        params: dict[str, object],
    ) -> dict[str, object]:
        query = urllib.parse.urlencode(params)
        request_path = f"{endpoint}?{query}" if query else endpoint
        timestamp = str(int(time.time() * 1000))
        prehash = f"{timestamp}GET{request_path}"
        signature = base64.b64encode(
            hmac.new(api_secret.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).digest()
        ).decode("utf-8")
        headers = {
            "ACCESS-KEY": api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-PASSPHRASE": passphrase,
            "ACCESS-TIMESTAMP": timestamp,
            "locale": "en-US",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=30) as client:
            response = client.get(f"{self.BASE_URL}{request_path}", headers=headers)
            if response.status_code >= 400:
                raise RuntimeError(self._bitget_error_message(response))
            payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("bitget_unexpected_payload")
        code = str(payload.get("code") or "")
        if code and code != "00000":
            raise RuntimeError(f"bitget_api_error:{code}:{payload.get('msg') or payload.get('message')}")
        return payload

    def _credentials(self) -> tuple[str, str, str]:
        api_key = self._secret_value("secret.cex.bitget.api_key") or os.environ.get("BITGET_API_KEY", "")
        api_secret = self._secret_value("secret.cex.bitget.api_secret") or os.environ.get("BITGET_API_SECRET", "")
        passphrase = self._secret_value("secret.cex.bitget.passphrase") or os.environ.get("BITGET_PASSPHRASE", "")
        return str(api_key).strip(), str(api_secret).strip(), str(passphrase).strip()

    def _secret_value(self, key: str) -> str:
        return resolve_secret_value(self.store, key)

    def _time_windows(self, since: datetime, until: datetime) -> list[tuple[datetime, datetime]]:
        windows: list[tuple[datetime, datetime]] = []
        start = since.astimezone(timezone.utc)
        end = until.astimezone(timezone.utc)
        current = start
        while current <= end:
            window_end = min(current + timedelta(days=self.WINDOW_DAYS), end)
            windows.append((current, window_end))
            current = window_end + timedelta(milliseconds=1)
        return windows

    @staticmethod
    def _millis(value: datetime) -> int:
        return int(value.astimezone(timezone.utc).timestamp() * 1000)

    @staticmethod
    def _millis_to_iso(value: object) -> str:
        try:
            millis = int(str(value))
        except Exception:
            return ""
        return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).isoformat()

    @staticmethod
    def _decimal_from_payload(value: object) -> Decimal:
        if value in (None, ""):
            return Decimal("0")
        try:
            return Decimal(str(value).strip().replace(",", "."))
        except (InvalidOperation, ValueError):
            return Decimal("0")

    @staticmethod
    def _rows_hash(rows: list[dict[str, object]]) -> str:
        return "sha256:" + hashlib.sha256(
            json.dumps(rows, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

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

    @staticmethod
    def _bitget_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except json.JSONDecodeError:
            payload = {}
        if isinstance(payload, dict):
            code = payload.get("code")
            message = payload.get("msg") or payload.get("message")
            if code is not None or message is not None:
                return f"bitget_http_{response.status_code}: code={code} msg={message}"
        return f"bitget_http_{response.status_code}"
