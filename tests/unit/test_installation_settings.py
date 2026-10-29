import json
import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
import pytest

from steuerreport_v2.contracts.installation import InstallationSettingsWrite, PrivateConfigWrite
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.installation import FIELD_KEYS, InstallationSettingsError, InstallationSettingsService
from steuerreport_v2.private_settings import _read_profile


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", str(tmp_path / "private/profile.json"))
    monkeypatch.setenv("STEUERREPORT_PRIVATE_CONFIG_DIR", str(tmp_path / "private/configs"))
    (tmp_path / "private").mkdir()
    (tmp_path / "private/profile.json").write_text("{}\n")
    _read_profile.cache_clear()
    yield InstallationSettingsService(DuckDbStore(tmp_path / "ledger.duckdb"))
    _read_profile.cache_clear()


def test_fresh_installation_has_no_accounts_or_secrets(service):
    state = service.read()
    assert state.profile_writable
    assert not state.restart_required
    assert not any(field.value for field in state.fields)
    assert not any(state.providers.values())


def test_profile_write_roundtrip_atomic_permissions_and_restart(service):
    before = service.read()
    state = service.write(InstallationSettingsWrite(revision=before.revision, values={"primary_solana_wallet": "fixture-wallet", "import_root": "/tmp/test-imports"}))
    assert state.restart_required
    assert service.path.stat().st_mode & 0o777 == 0o600
    assert json.loads(service.path.read_text())["primary_solana_wallet"] == "fixture-wallet"
    assert list(service.path.parent.iterdir()) == [service.path]
    with pytest.raises(InstallationSettingsError, match="revision_conflict"):
        service.write(InstallationSettingsWrite(revision=before.revision, values={"primary_solana_wallet": "stale"}))
    environment = dict(os.environ)
    result = subprocess.run([sys.executable, "-c", "from steuerreport_v2.private_settings import private_value; assert private_value('primary_solana_wallet') == 'fixture-wallet'; from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService as S; assert S.PRIMARY_SOLANA_WALLET == 'fixture-wallet'; from steuerreport_v2.paths import configured_import_path; assert str(configured_import_path('solscan_export_file', 'solscan/export.csv')) == '/tmp/test-imports/solscan/export.csv'"], env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_profile_rejects_unknown_keys_and_does_not_clobber_hidden_keys(service):
    service.path.write_text('{"future_field":"keep"}')
    before = service.read()
    with pytest.raises(InstallationSettingsError, match="unknown_profile_field"):
        service.write(InstallationSettingsWrite(revision=before.revision, values={"secret": "value"}))
    service.write(InstallationSettingsWrite(revision=before.revision, values={"primary_solana_wallet": ""}))
    assert json.loads(service.path.read_text())["future_field"] == "keep"


def test_environment_managed_field_cannot_be_silently_overridden(service, monkeypatch):
    monkeypatch.setenv("STEUERREPORT_PRIMARY_SOLANA_WALLET", "environment-fixture")
    state = service.read()
    field = next(field for field in state.fields if field.key == "primary_solana_wallet")
    assert not field.editable
    assert field.source == "environment"
    with pytest.raises(InstallationSettingsError, match="managed_by_environment"):
        service.write(InstallationSettingsWrite(revision=state.revision, values={field.key: "ignored"}))


@pytest.mark.parametrize("value", ["https://user:pass@example.invalid", "https://example.invalid/?api-key=fixture", "file:///private", "https://example.invalid/#token"])
def test_service_urls_cannot_smuggle_credentials(service, value):
    with pytest.raises(InstallationSettingsError, match="profile_url_invalid"):
        service.write(InstallationSettingsWrite(revision=service.read().revision, values={"v1_connector_base_url": value}))


def test_symlink_profile_is_never_overwritten(service, tmp_path):
    target = tmp_path / "original.json"
    target.write_text("{}")
    service.path.unlink()
    service.path.symlink_to(target)
    assert not service.read().profile_writable
    with pytest.raises(InstallationSettingsError, match="location_not_writable"):
        service.write(InstallationSettingsWrite(revision=service.read().revision, values={}))
    assert target.read_text() == "{}"


def test_config_editor_is_external_revision_bound_and_does_not_run_pipeline(service):
    before = service.read_config("source_registry.json")
    value = json.loads(before.content)
    value["registry_version"] = "fixture-registry"
    result = service.write_config(before.filename, PrivateConfigWrite(revision=before.revision, content=json.dumps(value)))
    assert result.revision != before.revision
    assert service.read().restart_required
    assert (service.config_dir / before.filename).stat().st_mode & 0o777 == 0o600
    assert service.store.list_canonical_events() == []
    with pytest.raises(InstallationSettingsError, match="revision_conflict"):
        service.write_config(before.filename, PrivateConfigWrite(revision=before.revision, content=json.dumps(value)))
    with pytest.raises(InstallationSettingsError, match="not_supported"):
        service.read_config("../profile.json")
    with pytest.raises(InstallationSettingsError, match="schema_invalid"):
        service.write_config(before.filename, PrivateConfigWrite(revision=result.revision, content='{"entries":"wrong"}'))


def test_solana_ownership_config_is_typed_and_preserves_existing_metadata(service):
    document = service.read_config("solana_v1_ownership_scope.json")
    assert document.configuration_status == "unconfigured"
    content = json.dumps(
        {
            "outside_owned_wallet_scope_txids": ["synthetic-tx-1"],
            "audit_metadata": {"review_ref": "synthetic-review-1"},
        }
    )
    saved = service.write_config(
        document.filename,
        PrivateConfigWrite(revision=document.revision, content=content),
    )
    assert saved.content == content
    assert saved.configuration_status == "configured"

    for invalid in [
        {"outside_owned_wallet_scope_txids": "synthetic-tx-1"},
        {"outside_owned_wallet_scope_txids": None},
        {"outside_owned_wallet_scope_txids": [None]},
        {"outside_owned_wallet_scope_txids": [1]},
        {"outside_owned_wallet_scope_txids": [""]},
        {"outside_owned_wallet_scope_txids": [" padded "]},
    ]:
        with pytest.raises(InstallationSettingsError, match="config_json_or_schema_invalid"):
            service.write_config(
                document.filename,
                PrivateConfigWrite(
                    revision=saved.revision,
                    content=json.dumps(invalid),
                ),
            )
        assert service.read_config(document.filename).content == content

    empty = service.write_config(
        document.filename,
        PrivateConfigWrite(
            revision=saved.revision,
            content='{"outside_owned_wallet_scope_txids": []}',
        ),
    )
    assert empty.configuration_status == "configured_empty"


def test_solana_ownership_config_api_rejects_invalid_values_without_writing(service):
    from steuerreport_v2.api.app import create_app

    client = TestClient(create_app(service.store))
    document = client.get(
        "/api/v1/admin/installation/configs/solana_v1_ownership_scope.json"
    ).json()["data"]
    assert document["configuration_status"] == "unconfigured"
    response = client.put(
        "/api/v1/admin/installation/configs/solana_v1_ownership_scope.json",
        json={
            "revision": document["revision"],
            "content": '{"outside_owned_wallet_scope_txids":"synthetic-tx"}',
        },
    )

    assert response.status_code == 400
    assert "config_json_or_schema_invalid" in response.text
    assert service.read_config("solana_v1_ownership_scope.json").content == document["content"]


def test_invalid_existing_ownership_config_does_not_break_installation_settings(service):
    path = service.config_dir / "solana_v1_ownership_scope.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"outside_owned_wallet_scope_txids":null}', encoding="utf-8")

    restarted_service = InstallationSettingsService(service.store)
    assert restarted_service.read().revision
    with pytest.raises(InstallationSettingsError, match="config_json_or_schema_invalid"):
        restarted_service.read_config(path.name)

    from steuerreport_v2.api.app import create_app

    client = TestClient(create_app(service.store))
    assert client.get("/api/v1/admin/installation").status_code == 200
    response = client.get(f"/api/v1/admin/installation/configs/{path.name}")
    assert response.status_code == 400
    assert "config_json_or_schema_invalid" in response.text


def test_provider_secret_requires_encryption_and_is_never_returned(service, tmp_path, monkeypatch):
    monkeypatch.delenv("STEUERREPORT_V2_SECRET_VAULT_KEY_FILE", raising=False)
    with pytest.raises(InstallationSettingsError, match="encrypted_secret_vault_required"):
        service.save_provider("solscan", "fixture-api-token")
    key = tmp_path / "vault.key"
    key.write_bytes(os.urandom(32))
    monkeypatch.setenv("STEUERREPORT_V2_SECRET_VAULT_KEY_FILE", str(key))
    service.save_provider("solscan", "fixture-api-token")
    assert service.read().providers["solscan"]
    assert "fixture-api-token" not in service.read().model_dump_json()
    assert "fixture-api-token" not in service.store.list_admin_settings()[0].value_json
    service.delete_provider("solscan")
    assert not service.read().providers["solscan"]


def test_profile_field_catalog_covers_every_used_private_value():
    import ast

    used = set()
    for path in (Path(__file__).resolve().parents[2] / "src/steuerreport_v2").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"private_value", "private_alias", "configured_import_path"} and node.args and isinstance(node.args[0], ast.Constant):
                used.add(node.args[0].value)
    assert not used - FIELD_KEYS


def test_settings_endpoints_do_not_return_secrets(service, monkeypatch, tmp_path):
    from steuerreport_v2.api.app import create_app

    key = tmp_path / "key"
    key.write_bytes(os.urandom(32))
    monkeypatch.setenv("STEUERREPORT_V2_SECRET_VAULT_KEY_FILE", str(key))
    client = TestClient(create_app(service.store))
    state = client.get("/api/v1/admin/installation").json()["data"]
    assert client.put("/api/v1/admin/installation", json={"revision": state["revision"], "values": {"primary_solana_wallet": "api-fixture"}}).status_code == 200
    result = client.put("/api/v1/admin/installation/providers/solscan", json={"api_key": "fixture-only-token"})
    assert result.status_code == 200
    assert "fixture-only-token" not in result.text
    assert "fixture-only-token" not in client.get("/api/v1/admin/installation").text
    assert client.delete("/api/v1/admin/installation/providers/unknown").status_code == 400
    assert client.get("/api/v1/admin/installation", headers={"Origin": "https://untrusted.invalid"}).status_code == 403
    assert client.get("/api/v1/admin/installation", headers={"Host": "untrusted.invalid"}).status_code == 400


def test_container_state_initialization_never_replaces_profile_or_key(tmp_path, monkeypatch):
    from steuerreport_v2.container_entrypoint import initialize_state

    monkeypatch.setenv("STEUERREPORT_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", str(tmp_path / "profile.json"))
    monkeypatch.setenv("STEUERREPORT_V2_SECRET_VAULT_KEY_FILE", str(tmp_path / "keys/vault.key"))
    monkeypatch.setenv("STEUERREPORT_V2_DB", str(tmp_path / "state.duckdb"))
    monkeypatch.setenv("STEUERREPORT_USERTRANSFER_ROOT", str(tmp_path / "imports"))
    monkeypatch.setenv("STEUERREPORT_V2_REQUIRE_ENCRYPTED_SECRETS", "false")
    previous_umask = os.umask(0o077)
    try:
        initialize_state()
        key = (tmp_path / "keys/vault.key").read_bytes()
        assert len(key) == 32
        (tmp_path / "profile.json").write_text('{"primary_solana_wallet":"fixture-only"}')
        initialize_state()
        assert (tmp_path / "keys/vault.key").read_bytes() == key
        assert json.loads((tmp_path / "profile.json").read_text())["primary_solana_wallet"] == "fixture-only"
    finally:
        os.umask(previous_umask)
