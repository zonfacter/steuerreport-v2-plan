from __future__ import annotations

from datetime import datetime, timezone
import json

import httpx

from steuerreport_v2.contracts.admin import (
    AdminSetting,
    AdminSettingWrite,
    AdminStatus,
    ApiKeyWrite,
    ApiKeyWriteResult,
    CexCredentialWrite,
    CexCredentialWriteResult,
    V1CexCredentialTakeoverItem,
    V1CexCredentialTakeoverReport,
    V1CexCredentialTakeoverResult,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.secrets import (
    is_secret_key,
    redact_setting,
    secret_value_from_json,
    upsert_secret,
)
from steuerreport_v2.domain.sources import SourceService
from steuerreport_v2.private_settings import private_value


class AdminService:
    V1_ADMIN_BASE_URL = private_value("v1_connector_base_url")
    CEX_CONNECTORS = {"binance", "bitget", "pionex", "coinbase"}

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def upsert_setting(self, setting: AdminSettingWrite) -> AdminSetting:
        parsed_value = json.loads(setting.value_json)
        if is_secret_key(setting.key):
            if not isinstance(parsed_value, str):
                raise ValueError("secret_setting_must_be_json_string")
            value = secret_value_from_json(setting.value_json)
            return redact_setting(upsert_secret(self.store, setting.key, value))
        return redact_setting(self.store.upsert_admin_setting(setting))

    def list_settings(self) -> list[AdminSetting]:
        return [redact_setting(setting) for setting in self.store.list_admin_settings()]

    def delete_setting(self, key: str) -> bool:
        return self.store.delete_admin_setting(key)

    def status(self) -> AdminStatus:
        settings = {setting.key: setting.value_json for setting in self.list_settings()}
        return AdminStatus(
            database=self.store.health(),
            settings_count=len(settings),
            local_ai_enabled=json.loads(settings.get("ai.local.enabled", "true")),
            external_ai_enabled=json.loads(settings.get("ai.external.enabled", "false")),
        )

    def save_cex_credentials(self, payload: CexCredentialWrite) -> CexCredentialWriteResult:
        connector_id = payload.connector_id.strip().lower()
        if connector_id not in self.CEX_CONNECTORS:
            raise ValueError("unsupported_cex_connector")
        api_key = payload.api_key.strip()
        api_secret = payload.api_secret.strip()
        passphrase = (payload.passphrase or "").strip()
        if not api_key or not api_secret:
            raise ValueError("api_key_and_api_secret_required")
        settings = [
            (f"secret.cex.{connector_id}.api_key", api_key),
            (f"secret.cex.{connector_id}.api_secret", api_secret),
        ]
        if connector_id == "bitget" or passphrase:
            settings.append((f"secret.cex.{connector_id}.passphrase", passphrase))
        written_keys: list[str] = []
        for setting_key, value in settings:
            self._write_v2_secret_setting(setting_key, value)
            written_keys.append(setting_key)
        diagnostic = next(
            item
            for item in SourceService(self.store).connector_diagnostics().diagnostics
            if item.connector_id == connector_id
        )
        return CexCredentialWriteResult(
            connector_id=connector_id,
            status="ok" if diagnostic.credential_status == "configured" else "warning",
            written_keys=written_keys,
            diagnostic_status=diagnostic.status,
            credential_status=diagnostic.credential_status,
            credential_issue=diagnostic.credential_issue,
            message=(
                "CEX-Credentials wurden im V2-Secret-Store gespeichert."
                if diagnostic.credential_status == "configured"
                else "CEX-Credentials wurden geschrieben, sind aber in der anschliessenden Diagnose noch nicht nutzbar."
            ),
        )

    def save_jupiter_api_key(self, payload: ApiKeyWrite) -> ApiKeyWriteResult:
        api_key = payload.api_key.strip()
        if not api_key:
            raise ValueError("api_key_required")
        setting_key = "secret.jupiter.api_key"
        self._write_v2_secret_setting(setting_key, api_key)
        return ApiKeyWriteResult(
            provider="jupiter",
            status="ok",
            written_keys=[setting_key],
            message="Jupiter API-Key wurde im V2-Secret-Store gespeichert.",
        )

    def _write_v2_secret_setting(self, setting_key: str, value: str) -> None:
        upsert_secret(self.store, setting_key, value)

    def v1_cex_credential_takeover_report(self) -> V1CexCredentialTakeoverReport:
        items = [self._v1_cex_takeover_item(connector_id) for connector_id in sorted(self.CEX_CONNECTORS)]
        return V1CexCredentialTakeoverReport(
            generated_at=datetime.now(timezone.utc),
            items=items,
            transferable=sum(1 for item in items if item.can_take_over),
            blocked=sum(1 for item in items if not item.can_take_over),
            methodology=(
                "Read-only V1-CEX-Credential-Takeover-Preflight. V1 wird ueber "
                "/api/v1/admin/cex-credentials/load gefragt; Secret-Werte werden "
                "nicht ausgegeben. Eine Uebernahme ist nur moeglich, wenn V1 API "
                "Key und Secret tatsaechlich entschluesselt liefern kann."
            ),
        )

    def import_v1_cex_credentials(
        self,
        connectors: list[str] | None = None,
    ) -> V1CexCredentialTakeoverResult:
        requested = sorted({item.strip().lower() for item in (connectors or sorted(self.CEX_CONNECTORS)) if item.strip()})
        unsupported = [item for item in requested if item not in self.CEX_CONNECTORS]
        if unsupported:
            raise ValueError(f"unsupported_cex_connector:{','.join(unsupported)}")
        imported: list[CexCredentialWriteResult] = []
        skipped: list[V1CexCredentialTakeoverItem] = []
        for connector_id in requested:
            item, creds = self._v1_cex_takeover_item_with_credentials(connector_id)
            if not item.can_take_over:
                skipped.append(item)
                continue
            imported.append(
                self.save_cex_credentials(
                    CexCredentialWrite(
                        connector_id=connector_id,
                        api_key=creds["api_key"],
                        api_secret=creds["api_secret"],
                        passphrase=creds.get("passphrase") or "",
                    )
                )
            )
        return V1CexCredentialTakeoverResult(
            generated_at=datetime.now(timezone.utc),
            imported=imported,
            skipped=skipped,
            methodology=(
                "Importiert nur V1-CEX-Credentials, die V1 selbst entschluesselt "
                "bereitstellt. Nicht entschluesselbare vorhandene Secret-Zeilen "
                "werden nicht geraten, nicht exportiert und nicht ueberschrieben."
            ),
        )

    def _v1_cex_takeover_item(self, connector_id: str) -> V1CexCredentialTakeoverItem:
        item, _creds = self._v1_cex_takeover_item_with_credentials(connector_id)
        return item

    def _v1_cex_takeover_item_with_credentials(
        self,
        connector_id: str,
    ) -> tuple[V1CexCredentialTakeoverItem, dict[str, str]]:
        diagnostic = next(
            (
                item
                for item in SourceService(self.store).connector_diagnostics().diagnostics
                if item.connector_id == connector_id
            ),
            None,
        )
        creds: dict[str, str] = {}
        try:
            response = httpx.post(
                f"{self.V1_ADMIN_BASE_URL.rstrip('/')}/api/v1/admin/cex-credentials/load",
                json={"connector_id": connector_id},
                timeout=10,
            )
            response.raise_for_status()
            body = response.json()
        except Exception as exc:
            return (
                V1CexCredentialTakeoverItem(
                    connector_id=connector_id,
                    status="v1_load_failed",
                    can_take_over=False,
                    has_api_key=False,
                    has_api_secret=False,
                    keys_present=diagnostic.credential_keys_present if diagnostic is not None else 0,
                    keys_required=diagnostic.credential_keys_required if diagnostic is not None else 0,
                    credential_issue=f"{type(exc).__name__}",
                    next_action="V1-Admin-Service pruefen oder Credentials neu hinterlegen.",
                ),
                creds,
            )
        if str(body.get("status")) != "success":
            return (
                V1CexCredentialTakeoverItem(
                    connector_id=connector_id,
                    status="v1_load_error",
                    can_take_over=False,
                    has_api_key=False,
                    has_api_secret=False,
                    keys_present=diagnostic.credential_keys_present if diagnostic is not None else 0,
                    keys_required=diagnostic.credential_keys_required if diagnostic is not None else 0,
                    credential_issue="v1_admin_status_error",
                    next_action="V1-Admin-Load-Fehler pruefen oder Credentials neu hinterlegen.",
                ),
                creds,
            )
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        creds = {
            "api_key": str(data.get("api_key") or ""),
            "api_secret": str(data.get("api_secret") or ""),
            "passphrase": str(data.get("passphrase") or ""),
        }
        has_api_key = bool(creds["api_key"])
        has_api_secret = bool(creds["api_secret"])
        has_passphrase = bool(creds["passphrase"])
        needs_passphrase = connector_id == "bitget"
        can_take_over = has_api_key and has_api_secret and (has_passphrase or not needs_passphrase)
        status = "transferable" if can_take_over else "not_decryptable"
        issue = None if can_take_over else "v1_returned_empty_credentials"
        if diagnostic is not None and diagnostic.credential_status == "missing":
            status = "missing_in_v1"
            issue = diagnostic.credential_issue
        return (
            V1CexCredentialTakeoverItem(
                connector_id=connector_id,
                status=status,
                can_take_over=can_take_over,
                has_api_key=has_api_key,
                has_api_secret=has_api_secret,
                has_passphrase=has_passphrase,
                keys_present=diagnostic.credential_keys_present if diagnostic is not None else 0,
                keys_required=diagnostic.credential_keys_required if diagnostic is not None else 0,
                credential_issue=issue,
                next_action=(
                    "V1-Credentials koennen uebernommen und mit aktuellem Secret-Key neu gespeichert werden."
                    if can_take_over
                    else "Alter Master-Key erforderlich oder Credentials im Admin-Bereich neu eintragen."
                ),
            ),
            creds,
        )
