from datetime import datetime, timezone
from decimal import Decimal
import json

import httpx
import pytest

from steuerreport_v2.contracts.admin import AdminSettingWrite
from steuerreport_v2.contracts.portfolio import PortfolioLiveBalanceSnapshot
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain import portfolio
from steuerreport_v2.domain.external_http import managed_client
from steuerreport_v2.domain.portfolio import PortfolioService


@pytest.fixture
def rpc_setup(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    service = PortfolioService(store)
    monkeypatch.setattr(service, "V1_CONNECTOR_BASE_URL", "")
    monkeypatch.setattr(service, "_v1_solana_wallet_balances", lambda _wallet: {})
    monkeypatch.setattr(service, "_solscan_api_key", lambda: "")
    return store, service


def install_rpc(monkeypatch, responder):
    requests = []

    def handle(request):
        requests.append(request)
        return responder(request, json.loads(request.content))

    monkeypatch.setattr(portfolio, "managed_client", lambda **kwargs: managed_client(transport=httpx.MockTransport(handle), **kwargs))
    return requests


@pytest.mark.parametrize("provider", [None, "alchemy", "helius"])
def test_solana_refresh_uses_rpc_without_mandatory_alchemy_key(rpc_setup, monkeypatch, provider):
    store, service = rpc_setup
    if provider:
        store.upsert_admin_setting(AdminSettingWrite(key=f"secret.{provider}.api_key", value_json='"configured"'))

    def respond(request, payload):
        assert payload["params"][0] == service.PRIMARY_SOLANA_WALLET
        value = 1250000000 if payload["method"] == "getBalance" else []
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": value}})

    requests = install_rpc(monkeypatch, respond)
    result = service.refresh_reconciliation_snapshots(connectors=["solana_wallet"])
    assert result.connector_results[0].status == "refreshed"
    assert [(row.asset, row.quantity) for row in result.snapshots] == [("SOL", Decimal("1.25"))]
    assert len(requests) == 3
    expected_host = {None: "api.mainnet.solana.com", "alchemy": "solana-mainnet.g.alchemy.com", "helius": "mainnet.helius-rpc.com"}[provider]
    assert all(request.url.host == expected_host for request in requests)
    with store.connect() as con:
        for name in ("canonical_events", "balance_ledger", "tax_lots", "tax_lines"):
            assert con.execute(f"select count(*) from {name}").fetchone()[0] == 0


def test_solana_complete_empty_rpc_is_confirmed_without_fallback(rpc_setup, monkeypatch):
    store, service = rpc_setup

    def respond(_request, payload):
        value = 0 if payload["method"] == "getBalance" else []
        return httpx.Response(200, json={"result": {"value": value}})

    requests = install_rpc(monkeypatch, respond)
    monkeypatch.setattr(service, "_solscan_wallet_balances", lambda _wallet: pytest.fail("Empty RPC must not trigger a paid fallback"))
    result = service.refresh_reconciliation_snapshots(connectors=["solana_wallet"])
    assert result.connector_results[0].status == "empty_response"
    assert len(requests) == 3 and result.snapshots == []
    assert PortfolioService(store)._latest_live_connector_anchor("solana_wallet")[0] == "empty_response"


@pytest.mark.parametrize("native,tokens", [(None, []), (True, []), (-1, []), (0, None), (0, [None]), (0, [{}]),
    (0, [{"account": {"data": {"parsed": {"info": {"mint": "synthetic", "tokenAmount": {"uiAmountString": "NaN"}}}}}}])])
def test_solana_incomplete_rpc_never_confirms_zero_or_replaces_previous_snapshot(rpc_setup, monkeypatch, native, tokens):
    store, service = rpc_setup
    old = datetime(2025, 1, 1, tzinfo=timezone.utc)
    service._replace_live_balance_snapshots([PortfolioLiveBalanceSnapshot(snapshot_id="previous", connector_id="solana_wallet", asset="SOL",
        quantity=Decimal("2"), source="synthetic", fetched_at=old)])
    requests = install_rpc(monkeypatch, lambda _request, payload: httpx.Response(200, json={"result": {
        "value": native if payload["method"] == "getBalance" else tokens}}))
    result = service.refresh_reconciliation_snapshots(connectors=["solana_wallet"])
    assert requests and result.connector_results[0].status == "connector_error"
    assert result.snapshots == [] and result.connector_results[0].previous_snapshot_at.replace(tzinfo=timezone.utc) == old
    assert service._stored_live_balance_snapshots("solana_wallet") == {"SOL": Decimal("2")}
    assert service._latest_live_connector_anchor("solana_wallet")[0] == "refreshed"


@pytest.mark.parametrize("http_status,payload", [(403, {}), (200, {"error": {"code": -32001, "message": "sensitive-value"}}), (200, {})])
def test_solana_rpc_errors_do_not_expose_secrets_or_urls(rpc_setup, monkeypatch, http_status, payload):
    _store, service = rpc_setup
    monkeypatch.setattr(service, "_solana_rpc_urls", lambda: ["https://rpc.invalid/private-sensitive-value?api-key=sensitive-value"])
    install_rpc(monkeypatch, lambda _request, _payload: httpx.Response(http_status, json=payload))
    result = service.refresh_reconciliation_snapshots(connectors=["solana_wallet"])
    assert result.connector_results[0].status == "connector_error"
    message = result.connector_results[0].message
    assert "sensitive-value" not in message and "api-key" not in message
    assert "RPC-Abruf fehlgeschlagen" in message
    if http_status == 403:
        assert "HTTP 403" in message


def test_solana_without_wallet_does_not_start_any_external_request(rpc_setup, monkeypatch):
    _store, service = rpc_setup
    monkeypatch.setattr(service, "PRIMARY_SOLANA_WALLET", "")
    monkeypatch.setattr(service, "_live_solana_wallet_balances", lambda _wallet: pytest.fail("No wallet configured"))
    result = service.refresh_reconciliation_snapshots(connectors=["solana_wallet"])
    assert result.connector_results[0].status == "missing_configuration"
    assert "Profilwallet" in result.connector_results[0].message
