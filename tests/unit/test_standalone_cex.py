from decimal import Decimal
import os

from fastapi.testclient import TestClient
import pytest

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.portfolio import PortfolioLiveBalanceSnapshot
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.admin import AdminService
from steuerreport_v2.domain.cex_balances import CexBalanceService
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.secret_vault import is_encrypted_envelope


def no_legacy(*args, **kwargs):
    raise AssertionError("Standalone operation must not contact V1")


def test_unconfigured_legacy_preflight_is_inactive_and_has_no_side_effects(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "standalone.duckdb")
    monkeypatch.setattr(AdminService, "V1_ADMIN_BASE_URL", "")
    monkeypatch.setattr("steuerreport_v2.domain.admin.httpx.post", no_legacy)
    before = store.list_admin_settings()
    client = TestClient(create_app(store))
    response = client.get("/api/v1/admin/cex-credentials/v1-takeover")
    assert response.status_code == 200
    report = response.json()["data"]
    assert report["items"] == [] and report["transferable"] == report["blocked"] == 0
    response = client.post("/api/v1/admin/cex-credentials/v1-takeover", json={})
    assert response.json()["status"] == "error"
    assert response.json()["errors"][0]["message"] == "v1_migration_not_configured"
    assert store.list_admin_settings() == before


@pytest.mark.parametrize("connector", ["binance", "bitget", "pionex", "coinbase"])
def test_missing_credentials_do_not_fall_back_to_v1_or_create_zero_balance(tmp_path, monkeypatch, connector):
    store = DuckDbStore(tmp_path / "standalone.duckdb")
    monkeypatch.setattr(PortfolioService, "V1_CONNECTOR_BASE_URL", "")
    monkeypatch.setattr(PortfolioService, "_v1_cex_live_balance_snapshots", no_legacy)
    monkeypatch.setattr(PortfolioService, "_v1_cex_live_balances", no_legacy)
    monkeypatch.setattr(CexBalanceService, "fetch", no_legacy)
    result = PortfolioService(store).refresh_reconciliation_snapshots(connectors=[connector])
    assert result.imported_snapshots == 0
    assert result.connector_results[0].status == "missing_configuration"
    assert "V2-Administration" in result.connector_results[0].message
    assert "V1" not in result.connector_results[0].message
    assert PortfolioService(store)._latest_live_connector_anchor(connector) == (None, None)


@pytest.mark.parametrize("connector", ["binance", "bitget", "pionex", "coinbase"])
def test_credentials_save_encrypted_and_native_refresh_works_without_v1(tmp_path, monkeypatch, connector):
    store = DuckDbStore(tmp_path / "standalone.duckdb")
    keyfile = tmp_path / "vault.key"
    keyfile.write_bytes(os.urandom(32))
    monkeypatch.setenv("STEUERREPORT_V2_SECRET_VAULT_KEY_FILE", str(keyfile))
    monkeypatch.setenv("STEUERREPORT_V2_REQUIRE_ENCRYPTED_SECRETS", "true")
    monkeypatch.setattr(AdminService, "V1_ADMIN_BASE_URL", "")
    monkeypatch.setattr(PortfolioService, "V1_CONNECTOR_BASE_URL", "")
    monkeypatch.setattr(PortfolioService, "_v1_cex_live_balance_snapshots", no_legacy)
    monkeypatch.setattr(PortfolioService, "_v1_cex_live_balances", no_legacy)
    client = TestClient(create_app(store))
    payload = {"connector_id": connector, "api_key": "api-key", "api_secret": "api-secret", "passphrase": "passphrase" if connector == "bitget" else ""}
    response = client.post("/api/v1/admin/cex-credentials", json=payload)
    assert response.json()["data"]["credential_status"] == "configured"
    assert "api-secret" not in response.text
    secrets = [row for row in store.list_admin_settings() if row.key.startswith("secret.cex.")]
    assert len(secrets) == (3 if connector == "bitget" else 2)
    assert all(is_encrypted_envelope(row.value_json) for row in secrets)

    def fetch(service, connector_id, fetched_at):
        assert connector_id == connector
        credentials = service._credentials(connector_id)
        assert credentials[0:2] == ("api-key", "api-secret")
        return [PortfolioLiveBalanceSnapshot(
            snapshot_id="standalone:" + connector, connector_id=connector,
            asset="EUR", quantity=Decimal("1"), source=connector + "_api_v2", fetched_at=fetched_at,
        )]

    monkeypatch.setattr(CexBalanceService, "fetch", fetch)
    result = PortfolioService(store).refresh_reconciliation_snapshots(connectors=[connector])
    assert result.imported_snapshots == 1
    assert result.connector_results[0].status == "refreshed"
    assert result.snapshots[0].source == connector + "_api_v2"
