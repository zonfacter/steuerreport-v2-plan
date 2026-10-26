import json
import os
import subprocess
import sys

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.private_settings import private_state_root


def test_settings_get_is_readonly_and_configuration_survives_application_restart(tmp_path):
    store = DuckDbStore(tmp_path / "api.duckdb")
    client = TestClient(create_app(store))
    config = client.get("/api/v1/admin/request-limits").json()["data"]
    assert config["default_profile"]["requests_per_second"] == 1
    assert client.get("/api/v1/admin/request-limits/status").json()["data"]["groups"] == []
    assert not (private_state_root() / "request_limits").exists()
    assert client.get("/api/v1/admin/provider-references").json()["data"]["automatic_plan_detection"] is False
    config["default_profile"].update(requests_per_second=2, requests_per_minute=60, burst=2)
    config["endpoint_costs"] = {"binance": {"account": 20}}
    response = client.put("/api/v1/admin/request-limits", json={"config": config, "expected_revision": 0})
    assert response.status_code == 200
    restart = TestClient(create_app(DuckDbStore(store.path)))
    loaded = restart.get("/api/v1/admin/request-limits").json()["data"]
    assert loaded["revision"] == 1 and loaded["default_profile"]["requests_per_minute"] == 60
    assert loaded["endpoint_costs"] == {"binance": {"account": 20}}
    assert client.put("/api/v1/admin/request-limits", json={"config": config, "expected_revision": 0}).status_code == 409
    assert store.list_canonical_events() == [] and store.list_admin_settings() == []


def test_invalid_limits_and_admin_credentials_never_echo_request_inputs(tmp_path):
    client = TestClient(create_app(DuckDbStore(tmp_path / "invalid.duckdb")))
    config = client.get("/api/v1/admin/request-limits").json()["data"]
    config["default_profile"]["requests_per_second"] = -1
    config["provider_groups"] = {"binance": ["SECRET-MUST-NOT-ECHO"]}
    response = client.put("/api/v1/admin/request-limits", json={"config": config, "expected_revision": 0})
    assert response.status_code == 422 and "SECRET-MUST-NOT-ECHO" not in response.text
    response = client.post("/api/v1/admin/cex-credentials", json={"connector_id": [], "api_key": "PRIVATE-INPUT-NOT-ERROR", "api_secret": []})
    assert response.status_code == 422 and "PRIVATE-INPUT-NOT-ERROR" not in response.text


def test_demo_blocks_configuration_and_corrupt_coordinator_is_not_empty_success(tmp_path):
    app = create_app(DuckDbStore(tmp_path / "demo.duckdb"))
    app.state.ux_sandbox = True
    client = TestClient(app)
    config = client.get("/api/v1/admin/request-limits").json()["data"]
    assert client.put("/api/v1/admin/request-limits", json={"config": config, "expected_revision": 0}).status_code == 403
    assert client.get("/api/v1/admin/installation").json()["data"]["demo_mode"] is True
    app.state.ux_sandbox = False
    assert client.put("/api/v1/admin/request-limits", json={"config": config, "expected_revision": 0}).status_code == 200
    path = private_state_root() / "request_limits/coordinator.json"
    path.write_text('{"corrupt":"PRIVATE-CONTENT-NOT-ERROR"}')
    response = client.get("/api/v1/admin/request-limits/status")
    assert response.status_code == 503 and "PRIVATE-CONTENT-NOT-ERROR" not in response.text


def test_installation_permission_checks_and_provider_restart_persistence(tmp_path, monkeypatch):
    from steuerreport_v2.domain.installation import InstallationSettingsService
    from steuerreport_v2.private_settings import _read_profile
    root = tmp_path / "private"
    root.mkdir()
    profile = root / "profile.json"
    profile.write_text("{}")
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", str(profile))
    monkeypatch.setenv("STEUERREPORT_PRIVATE_CONFIG_DIR", str(root / "configs"))
    _read_profile.cache_clear()
    key = root / "key"
    key.write_bytes(os.urandom(32))
    key.chmod(0o600)
    monkeypatch.setenv("STEUERREPORT_V2_SECRET_VAULT_KEY_FILE", str(key))
    store = DuckDbStore(tmp_path / "persistent.duckdb")
    service = InstallationSettingsService(store)
    service.save_provider("helius", "synthetic-provider-secret")
    fresh = InstallationSettingsService(DuckDbStore(store.path))
    assert fresh.read().providers["helius"] is True
    assert "synthetic-provider-secret" not in fresh.read().model_dump_json()
    profile.chmod(0o400)
    try:
        assert fresh.read().profile_writable is False
        assert fresh.read().profile_issue == "profile_permission_denied"
        assert any(check["code"] == "encrypted_vault" and check["status"] == "ready" for check in fresh.read().storage_checks)
    finally:
        profile.chmod(0o600)
    root.chmod(0o500)
    try:
        assert fresh.read().profile_issue == "profile_parent_permission_denied"
    finally:
        root.chmod(0o700)
        _read_profile.cache_clear()
    assert json.loads(profile.read_text()) == {}


def test_connections_and_encrypted_credentials_survive_a_fresh_python_process(tmp_path, monkeypatch):
    key = tmp_path / "persist-key"
    key.write_bytes(os.urandom(32))
    key.chmod(0o600)
    monkeypatch.setenv("STEUERREPORT_V2_SECRET_VAULT_KEY_FILE", str(key))
    store = DuckDbStore(tmp_path / "restart.duckdb")
    client = TestClient(create_app(store))
    identifiers = []
    for number in (1, 2):
        response = client.post("/api/v1/admin/connections", json={"provider": "binance", "label": f"Synthetic {number}", "account": f"account-{number}", "api_key": f"synthetic-key-{number}", "api_secret": f"synthetic-secret-{number}"})
        assert response.status_code == 201
        identifiers.append(response.json()["data"]["id"])
    code = """
import sys
from steuerreport_v2.domain.connections import ConnectionService
from steuerreport_v2.db.duckdb_store import DuckDbStore
service = ConnectionService(DuckDbStore(sys.argv[1]))
assert len(service.list().connections) == 2
for number, identifier in enumerate(sys.argv[2:], 1):
    assert service.credentials(identifier, 'binance')[:2] == (f'synthetic-key-{number}', f'synthetic-secret-{number}')
    assert next(item for item in service.list().connections if str(item.id) == identifier).credentials.encrypted
"""
    result = subprocess.run([sys.executable, "-c", code, str(store.path), *identifiers], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, "Fresh process could not read encrypted persisted connections"
    assert not result.stdout and not result.stderr
