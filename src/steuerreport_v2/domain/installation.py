"""Manage operator configuration outside the distributable software tree."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
from threading import RLock
from urllib.parse import urlsplit

from steuerreport_v2.contracts.installation import InstallationField, InstallationSettings, InstallationSettingsWrite, PrivateConfigDocument, PrivateConfigWrite
from steuerreport_v2.contracts.source_registry import SourceRegistryConfig
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.secret_vault import load_vault_key
from steuerreport_v2.domain.secrets import resolve_secret_value, upsert_secret
from steuerreport_v2.paths import PROJECT_ROOT
from steuerreport_v2.private_settings import private_profile_path, private_state_root, private_value


# Keys retain compatibility with profiles from the first privacy-clean release.
FIELDS = (
    ("primary_solana_wallet", "Solana-Hauptwallet", "Wallets", "account"),
    ("secondary_solana_wallet", "Weitere Solana-/Jupiter-Wallet", "Wallets", "account"),
    ("legacy_helium_wallet", "Helium Legacy Wallet", "Wallets", "account"),
    ("legacy_staking_wallet", "Legacy Staking Wallet", "Wallets", "account"),
    ("staking_route_wallet", "Staking-Transferroute", "Wallets", "account"),
    ("helium_mobile_position_receipt", "Helium MOBILE Position Receipt", "Wallets", "account"),
    ("helium_iot_position_receipt", "Helium IOT Position Receipt", "Wallets", "account"),
    ("configured_identifier_04", "Bitget-Einzahlungsadresse 1", "Gegenparteien", "account"),
    ("configured_identifier_79", "Bitget-Einzahlungsadresse 2", "Gegenparteien", "account"),
    ("configured_identifier_100", "Binance-Einzahlungsadresse", "Gegenparteien", "account"),
    ("configured_identifier_95", "CEX-Hauptwallet (Belegabgleich)", "Gegenparteien", "account"),
    ("configured_identifier_97", "Bitget-Gegenpartei", "Gegenparteien", "account"),
    ("configured_identifier_80", "MoonPay-Senderwallet", "Gegenparteien", "account"),
    ("import_root", "Importverzeichnis", "Dateien", "path"),
    ("blockpit_reference_file", "Blockpit-Referenzdatei", "Dateien", "path"),
    ("solscan_export_file", "Solscan-Exportdatei", "Dateien", "path"),
    ("wallet_monthly_file", "Wallet-Monatsdatei", "Dateien", "path"),
    ("jup_perps_file", "Jupiter-Perpetuals-Datei", "Dateien", "path"),
    ("bitget_support_root", "Bitget-Supportexport-Verzeichnis", "Dateien", "path"),
    ("moonpay_history_file", "MoonPay-Handelsdatei", "Dateien", "path"),
    ("bank_camt_root", "Bank-CAMT-Verzeichnis", "Dateien", "path"),
    ("bank_statement_root", "Bankauszugsverzeichnis", "Dateien", "path"),
    ("trade_republic_root", "Trade-Republic-Belege", "Dateien", "path"),
    ("inheritance_root", "Herkunftsbelege", "Dateien", "path"),
    ("v1_fx_db_file", "Optionale V1-Preisdatenbank", "Dateien", "path"),
    ("v1_connector_base_url", "Optionale V1-API", "Dienste", "url"),
    ("local_llm_base", "Lokaler LLM-Endpunkt", "Dienste", "url"),
    ("local_llm_model", "Lokales LLM-Modell", "Dienste", "text"),
    ("solana_rpc_url", "Solana-RPC-Endpunkt (ohne API-Key)", "Dienste", "url"),
    ("expected_zero_sources", "Quellen mit erwartetem Nullbestand (kommagetrennt)", "Abgleich", "text"),
)
FIELD_KEYS = {row[0] for row in FIELDS}
PROVIDERS = {"solscan": "secret.solscan.api_key", "alchemy": "secret.alchemy.api_key", "jupiter": "secret.jupiter.api_key", "helius": "secret.helius.api_key"}
CONFIG_FILES = {
    "source_registry.json", "solana_v1_ownership_scope.json",
    "solana_service_swap_tax_mappings.json", "pionex_hnt_reconciliation.json",
    "fairspot_hnt_staking_reconciliation.json", "solana_staking_position_reconciliations.json",
}
_WRITE_LOCK = RLock()


class InstallationSettingsError(ValueError):
    pass


class InstallationSettingsService:
    def __init__(self, store: DuckDbStore):
        self.store = store
        self.path = private_profile_path()
        self.active = {key: private_value(key) for key in FIELD_KEYS}
        self.config_dir = Path(os.environ.get("STEUERREPORT_PRIVATE_CONFIG_DIR", private_state_root() / "configs")).expanduser()
        self.active_configs = {name: self.read_config(name).revision for name in CONFIG_FILES}

    def _read(self) -> tuple[dict[str, str], str]:
        if self.path is None or not self.path.exists():
            content = b"{}"
        else:
            try:
                content = self.path.read_bytes()
            except OSError:
                raise InstallationSettingsError("profile_unreadable") from None
        try:
            data = json.loads(content)
        except (ValueError, UnicodeDecodeError):
            raise InstallationSettingsError("profile_invalid") from None
        if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
            raise InstallationSettingsError("profile_invalid")
        return data, hashlib.sha256(content).hexdigest()

    def _writable(self) -> bool:
        if self.path is None or self.path.is_symlink():
            return False
        # No UI action may create a profile inside the software checkout.
        return not self.path.resolve().is_relative_to(PROJECT_ROOT.resolve())

    def read(self) -> InstallationSettings:
        profile, revision = self._read()
        fields = []
        for key, label, group, kind in FIELDS:
            env = "STEUERREPORT_" + key.upper()
            source = "environment" if env in os.environ else "profile" if profile.get(key) else "empty"
            value = os.environ[env] if env in os.environ else profile.get(key, "")
            fields.append(InstallationField(key=key, label=label, group=group, kind=kind, value=value, source=source, editable=source != "environment"))
        providers = {}
        for provider, key in PROVIDERS.items():
            try:
                providers[provider] = bool(resolve_secret_value(self.store, key))
            except (RuntimeError, ValueError):
                providers[provider] = False
        return InstallationSettings(
            fields=fields, revision=revision,
            restart_required=(any(field.value != self.active[field.key] for field in fields)
                              or any(self.read_config(name).revision != revision for name, revision in self.active_configs.items())),
            profile_writable=self._writable(), encrypted_secrets_available=load_vault_key() is not None,
            providers=providers,
        )

    def write(self, payload: InstallationSettingsWrite) -> InstallationSettings:
        if not self._writable():
            raise InstallationSettingsError("profile_location_not_writable")
        if set(payload.values) - FIELD_KEYS:
            raise InstallationSettingsError("unknown_profile_field")
        kinds = {row[0]: row[3] for row in FIELDS}
        values = {}
        for key, raw in payload.values.items():
            if "STEUERREPORT_" + key.upper() in os.environ:
                raise InstallationSettingsError("profile_field_managed_by_environment")
            value = raw.strip()
            if len(value) > 2048 or any(ord(c) < 32 for c in value):
                raise InstallationSettingsError("profile_field_invalid")
            if kinds[key] == "url" and value:
                url = urlsplit(value)
                if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
                    raise InstallationSettingsError("profile_url_invalid_or_contains_credentials")
            values[key] = value
        with _WRITE_LOCK:
            profile, revision = self._read()
            if payload.revision != revision:
                raise InstallationSettingsError("profile_revision_conflict")
            profile.update(values)
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as handle:
                    temporary = Path(handle.name)
                    os.chmod(temporary, 0o600)
                    json.dump(profile, handle, sort_keys=True, indent=2)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            except OSError:
                raise InstallationSettingsError("profile_write_failed") from None
            finally:
                if temporary and temporary.exists():
                    temporary.unlink()
        return self.read()

    def save_provider(self, provider: str, value: str) -> None:
        if provider not in PROVIDERS:
            raise InstallationSettingsError("provider_not_supported")
        if load_vault_key() is None:
            raise InstallationSettingsError("encrypted_secret_vault_required")
        if not value.strip():
            raise InstallationSettingsError("api_key_required")
        upsert_secret(self.store, PROVIDERS[provider], value)

    def delete_provider(self, provider: str) -> None:
        if provider not in PROVIDERS:
            raise InstallationSettingsError("provider_not_supported")
        self.store.delete_admin_setting(PROVIDERS[provider])

    def _config_path(self, filename: str) -> Path:
        if filename not in CONFIG_FILES:
            raise InstallationSettingsError("config_file_not_supported")
        path = self.config_dir / filename
        if path.is_symlink() or path.resolve().is_relative_to(PROJECT_ROOT.resolve()):
            raise InstallationSettingsError("config_location_not_writable")
        return path

    def read_config(self, filename: str) -> PrivateConfigDocument:
        path = self._config_path(filename)
        try:
            if path.exists():
                content = path.read_text(encoding="utf-8")
            elif filename == "source_registry.json":
                content = '{"registry_version":"unconfigured","entries":[],"ledger_adjustments":[],"transfer_evidence":[]}\n'
            else:
                content = "{}\n"
        except (OSError, UnicodeDecodeError):
            raise InstallationSettingsError("config_unreadable") from None
        return PrivateConfigDocument(filename=filename, content=content, revision=hashlib.sha256(content.encode()).hexdigest())

    def write_config(self, filename: str, payload: PrivateConfigWrite) -> PrivateConfigDocument:
        path = self._config_path(filename)
        try:
            value = json.loads(payload.content)
            if not isinstance(value, dict):
                raise ValueError()
            if filename == "source_registry.json":
                SourceRegistryConfig.model_validate(value)
        except (ValueError, TypeError):
            raise InstallationSettingsError("config_json_or_schema_invalid") from None
        with _WRITE_LOCK:
            if self.read_config(filename).revision != payload.revision:
                raise InstallationSettingsError("config_revision_conflict")
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as handle:
                    temporary = Path(handle.name)
                    os.chmod(temporary, 0o600)
                    handle.write(payload.content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, path)
            except OSError:
                raise InstallationSettingsError("config_write_failed") from None
            finally:
                if temporary and temporary.exists():
                    temporary.unlink()
        return self.read_config(filename)
