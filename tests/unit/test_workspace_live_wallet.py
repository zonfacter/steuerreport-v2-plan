from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json

from fastapi.testclient import TestClient
import pytest

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.connectors import PublicWalletAddressRequest
from steuerreport_v2.contracts.portfolio import PortfolioLiveBalanceSnapshot, PortfolioReconciliationRefreshConnectorResult
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.connectors import ConnectorService
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.workspace import WorkspaceService, source_ref


def fingerprint(store):
    with store.connect() as con:
        tables = con.execute("select table_name from information_schema.tables where table_schema='main' order by table_name").fetchall()
        values = [(name, con.execute('select * from "' + name + '" order by all').fetchall()) for (name,) in tables]
    return hashlib.sha256(json.dumps(values, default=str).encode()).hexdigest()


@pytest.fixture
def live_wallet(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    secondary = PortfolioService.KNOWN_JUP_WALLET
    monkeypatch.setattr(PortfolioService, "KNOWN_JUP_WALLET", "")
    monkeypatch.setattr(PortfolioService, "_live_solana_wallet_balances", lambda *_args: pytest.fail("Read views must not fetch providers"))
    portfolio = PortfolioService(store)
    at = datetime.now(timezone.utc) - timedelta(minutes=1)
    snapshots = [PortfolioLiveBalanceSnapshot(snapshot_id=f"synthetic-{index}", connector_id="solana_wallet", asset=asset,
        quantity=Decimal("1.234567890123456789"), source="synthetic-rpc", fetched_at=at)
        for index, asset in enumerate(["SOL", *[f"TOKEN{index:02}" for index in range(17)]])]
    portfolio._replace_live_balance_snapshots(snapshots)
    ref = source_ref("wallet:" + portfolio.PRIMARY_SOLANA_WALLET)
    return store, TestClient(create_app(store)), portfolio, ref, at, secondary


def test_unpriced_rpc_positions_are_visible_without_history_and_reads_are_immutable(live_wallet):
    store, client, _portfolio, ref, at, _secondary = live_wallet
    before = fingerprint(store)
    sources = client.get("/api/v1/workspace/sources").json()["data"]
    assert sources["events_count"] == 0 and len(sources["sources"]) == 1
    source = sources["sources"][0]
    assert source["ref"] == ref and source["live_assets_count"] == 18
    assert source["live_unpriced_assets_count"] == 18 and source["live_value_eur"] is None
    assert source["freshness"] == "fresh" and source["value_basis"] == "stored_live_snapshot"
    assert source["value_eur"] is None and source["ownership_status"] == "not_assessed"
    detail = client.get(f"/api/v1/workspace/sources/{ref}").json()["data"]
    assert detail["valuation"] is None
    assert len(detail["live_balance"]["assets"]) == 18 and detail["live_balance"]["value_eur"] is None
    assert detail["live_balance"]["assets"][0]["quantity"] == "1.234567890123456789"
    assert datetime.fromisoformat(detail["live_balance"]["fetched_at"].replace("Z", "+00:00")) == at
    assert detail["live_balance"]["sources"] == ["synthetic-rpc"]
    status = client.get("/api/v1/workspace/status?year=2025").json()["data"]
    assert not status["preview_available"] and not status["final_available"]
    assert status["next_section"] == "import"
    assert fingerprint(store) == before


def test_partial_prices_do_not_turn_a_partial_sum_into_total_wallet_value(live_wallet):
    store, _client, _portfolio, ref, at, _secondary = live_wallet
    store.add_price_point(PricePointCreate(asset="SOL", price_eur=Decimal("10"), priced_at=at, source="synthetic"))
    detail = WorkspaceService(store).source(ref)
    assert detail.live_balance.unpriced_assets_count == 17 and detail.live_balance.value_eur is None
    sol = next(row for row in detail.live_balance.assets if row.asset == "SOL")
    assert sol.value_eur == Decimal("12.345678901234567890") and sol.price_source == "synthetic"
    assert detail.source.live_value_eur is None


def test_fully_priced_positions_use_existing_prices_without_creating_tax_history(live_wallet):
    store, client, portfolio, ref, at, _secondary = live_wallet
    for asset in ["SOL", *[f"TOKEN{index:02}" for index in range(17)]]:
        store.add_price_point(PricePointCreate(asset=asset, price_eur=Decimal("10"), priced_at=at, source="synthetic"))
    detail = WorkspaceService(store).source(ref)
    assert detail.live_balance.unpriced_assets_count == 0
    assert detail.live_balance.value_eur == Decimal("1.234567890123456789") * 10 * 18
    assert detail.source.events_count == 0
    assert len([row for row in WorkspaceService(store).sources().sources if row.wallet_address == portfolio.PRIMARY_SOLANA_WALLET]) == 1
    assert not client.get("/api/v1/workspace/status?year=2025").json()["data"]["final_available"]


def test_confirmed_empty_run_supersedes_old_positions_but_keeps_original_rows(live_wallet):
    store, _client, portfolio, ref, _at, _secondary = live_wallet
    portfolio._record_live_connector_runs(fetched_at=datetime.now(timezone.utc),
        results=[PortfolioReconciliationRefreshConnectorResult(connector_id="solana_wallet", status="empty_response", snapshots=0, message="Synthetic empty")], snapshots=[])
    detail = WorkspaceService(store).source(ref)
    assert detail.live_balance.status == "confirmed_empty" and detail.live_balance.assets == []
    assert detail.live_balance.value_eur == 0 and detail.source.live_assets_count == 0
    with store.connect() as con:
        assert con.execute("select count(*) from portfolio_live_balance_snapshots").fetchone()[0] == 18


def test_failed_retry_keeps_previous_positions_and_exposes_attempt_separately(live_wallet):
    store, _client, portfolio, ref, at, _secondary = live_wallet
    portfolio._record_live_connector_runs(fetched_at=datetime.now(timezone.utc),
        results=[PortfolioReconciliationRefreshConnectorResult(connector_id="solana_wallet", status="connector_error", snapshots=0, message="Synthetic failure")], snapshots=[])
    detail = WorkspaceService(store).source(ref)
    assert detail.source.last_attempt.status == "connector_error"
    assert len(detail.live_balance.assets) == 18 and detail.live_balance.fetched_at == at


def test_other_observation_wallet_does_not_inherit_profile_wallet_snapshots(live_wallet):
    store, _client, _portfolio, ref, _at, secondary = live_wallet
    ConnectorService(store).save_public_wallet(PublicWalletAddressRequest(wallet_address=secondary, display_label="Other synthetic wallet"))
    other = WorkspaceService(store).source(source_ref("wallet:" + secondary))
    assert other.live_balance is None and other.source.live_assets_count is None
    assert not other.source.can_sync
    assert len(WorkspaceService(store).source(ref).live_balance.assets) == 18
