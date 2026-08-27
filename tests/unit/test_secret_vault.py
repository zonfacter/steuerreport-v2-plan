from __future__ import annotations

import json
import os

import pytest

from steuerreport_v2.contracts.admin import AdminSettingWrite
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.secret_vault import (
    is_encrypted_envelope,
    migrate_secret_vault,
    secret_vault_status,
)
from steuerreport_v2.domain.connectors import ConnectorService
from steuerreport_v2.domain.secrets import resolve_secret_value, upsert_secret


def _configure_vault(tmp_path, monkeypatch, *, key: bytes | None = None):
    key_path = tmp_path / "secret-vault.key"
    key_path.write_bytes(key or os.urandom(32))
    monkeypatch.setenv("STEUERREPORT_V2_SECRET_VAULT_KEY_FILE", str(key_path))
    return key_path


def test_secret_write_uses_aes_gcm_envelope_and_resolves_value(tmp_path, monkeypatch):
    _configure_vault(tmp_path, monkeypatch)
    store = DuckDbStore(tmp_path / "db.duckdb")

    upsert_secret(store, "secret.cex.binance.api_key", "private-api-key")

    setting = store.list_admin_settings()[0]
    assert is_encrypted_envelope(setting.value_json)
    assert "private-api-key" not in setting.value_json
    assert resolve_secret_value(store, setting.key) == "private-api-key"
    status = secret_vault_status(store)
    assert status.status == "encrypted"
    assert status.encrypted_secrets == 1
    assert status.plaintext_secrets == 0
    assert status.unreadable_secrets == 0


def test_secret_envelope_is_bound_to_vault_key(tmp_path, monkeypatch):
    key_path = _configure_vault(tmp_path, monkeypatch)
    store = DuckDbStore(tmp_path / "db.duckdb")
    upsert_secret(store, "secret.jupiter.api_key", "jupiter-secret")

    key_path.write_bytes(os.urandom(32))

    with pytest.raises(ValueError, match="secret_envelope_unreadable"):
        resolve_secret_value(store, "secret.jupiter.api_key")
    assert secret_vault_status(store).status == "error"
    catalog = ConnectorService(store).catalog()
    assert catalog.security.vault.status == "error"
    assert next(
        item for item in catalog.connectors if item.connector_id == "jupiter"
    ).connection_status == "not_configured"


def test_secret_vault_migrates_legacy_plaintext_transactionally(tmp_path, monkeypatch):
    _configure_vault(tmp_path, monkeypatch)
    store = DuckDbStore(tmp_path / "db.duckdb")
    store.upsert_admin_setting(
        AdminSettingWrite(
            key="secret.cex.bitget.api_secret",
            value_json=json.dumps("legacy-secret"),
        )
    )
    store.upsert_admin_setting(
        AdminSettingWrite(key="ui.theme", value_json=json.dumps("light"))
    )

    preview = migrate_secret_vault(store, apply=False)
    assert preview.status == "blocked"
    assert preview.plaintext_remaining == 1

    result = migrate_secret_vault(store, apply=True)

    assert result.status == "encrypted"
    assert result.encrypted_now == 1
    assert result.plaintext_remaining == 0
    stored = {item.key: item.value_json for item in store.list_admin_settings()}
    assert is_encrypted_envelope(stored["secret.cex.bitget.api_secret"])
    assert "legacy-secret" not in stored["secret.cex.bitget.api_secret"]
    assert json.loads(stored["ui.theme"]) == "light"
    assert resolve_secret_value(store, "secret.cex.bitget.api_secret") == "legacy-secret"


def test_required_encryption_rejects_secret_write_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("STEUERREPORT_V2_SECRET_VAULT_KEY_FILE", raising=False)
    monkeypatch.setenv("STEUERREPORT_V2_REQUIRE_ENCRYPTED_SECRETS", "true")
    store = DuckDbStore(tmp_path / "db.duckdb")

    with pytest.raises(RuntimeError, match="secret_vault_key_required"):
        upsert_secret(store, "secret.cex.pionex.api_key", "key")


def test_malformed_secret_setting_blocks_vault_migration(tmp_path, monkeypatch):
    _configure_vault(tmp_path, monkeypatch)
    store = DuckDbStore(tmp_path / "db.duckdb")
    store.upsert_admin_setting(
        AdminSettingWrite(
            key="secret.cex.binance.api_key",
            value_json='{"unexpected":"object"}',
        )
    )

    status = secret_vault_status(store)
    migration = migrate_secret_vault(store, apply=True)

    assert status.status == "error"
    assert status.unreadable_secrets == 1
    assert migration.status == "blocked"
    assert migration.unreadable_secrets == 1


def test_default_mode_keeps_clean_clone_legacy_compatibility(tmp_path, monkeypatch):
    monkeypatch.delenv("STEUERREPORT_V2_SECRET_VAULT_KEY_FILE", raising=False)
    monkeypatch.delenv("STEUERREPORT_V2_REQUIRE_ENCRYPTED_SECRETS", raising=False)
    store = DuckDbStore(tmp_path / "db.duckdb")

    upsert_secret(store, "secret.cex.pionex.api_key", "key")

    setting = store.list_admin_settings()[0]
    assert json.loads(setting.value_json) == "key"
    assert secret_vault_status(store).status == "not_configured"
