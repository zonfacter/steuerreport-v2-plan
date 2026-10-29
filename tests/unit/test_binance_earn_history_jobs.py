from datetime import datetime, timezone
from decimal import Decimal
import json
from collections import Counter
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
from pydantic import SecretStr
import pytest

from steuerreport_v2.contracts.admin import AdminSettingWrite
from steuerreport_v2.contracts.connections import ConnectionCreate, ConnectionSnapshots
from steuerreport_v2.contracts.history import HistoryApprove, HistoryStart
from steuerreport_v2.contracts.portfolio import PortfolioLiveBalanceSnapshot
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.connections import ConnectionService, SNAPSHOT_PREFIX
from steuerreport_v2.domain.history import HistoryService
from steuerreport_v2.domain.history_storage import HistoryStorage
from steuerreport_v2.domain.history_types import HistoryPage
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.secret_vault import KEY_FILE_ENV
from steuerreport_v2.domain.source_registry import SourceRegistryService
from steuerreport_v2.domain.workspace import source_ref


@pytest.fixture
def earn_job(tmp_path, monkeypatch):
    profile = tmp_path / "profile.json"
    profile.write_text("{}", encoding="ascii")
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps({
        "registry_version": "earn-history-test", "entries": [],
        "ledger_adjustments": [], "transfer_evidence": [],
    }), encoding="ascii")
    vault = tmp_path / "vault.key"
    vault.write_bytes(bytes(range(32)))
    vault.chmod(0o600)
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", str(profile))
    monkeypatch.setenv("STEUERREPORT_PRIVATE_CONFIG_DIR", str(tmp_path / "configs"))
    monkeypatch.setenv(KEY_FILE_ENV, str(vault))
    monkeypatch.setattr(PortfolioService, "PRIMARY_SOLANA_WALLET", "")
    monkeypatch.setattr(PortfolioService, "KNOWN_JUP_WALLET", "")
    monkeypatch.setattr(PortfolioService, "SOURCE_REGISTRY_CONFIG_PATH", registry)
    monkeypatch.setattr(SourceRegistryService, "DEFAULT_CONFIG_PATH", registry)
    monkeypatch.setattr(HistoryService, "_launch", lambda *_args: None)
    store = DuckDbStore(tmp_path / "history.duckdb")
    connection_service = ConnectionService(store)
    connection = connection_service.create(ConnectionCreate(
        provider="binance", label="Synthetic A", account="A",
        budget_group="budget:synthetic-binance-a",
        api_key=SecretStr("fake-api-key-a"), api_secret=SecretStr("fake-api-secret-a"),
    ))
    fetched_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
    snapshot = ConnectionSnapshots(
        connection_id=connection.id,
        fetched_at=fetched_at,
        snapshots=[
            PortfolioLiveBalanceSnapshot(
                snapshot_id="synthetic-flex", connector_id="binance", asset="JUP",
                quantity=Decimal("10"), source="synthetic", fetched_at=fetched_at,
                account_type="simple_earn_flexible", product_id="JUP001",
            ),
            PortfolioLiveBalanceSnapshot(
                snapshot_id="synthetic-locked", connector_id="binance", asset="SOL",
                quantity=Decimal("1"), source="synthetic", fetched_at=fetched_at,
                account_type="simple_earn_locked", product_id="SOL001",
                position_id="locked-position-a",
            ),
        ],
    )
    store.write_admin_settings_batch([
        AdminSettingWrite(key=f"{SNAPSHOT_PREFIX}{connection.id}", value_json=snapshot.model_dump_json()),
    ], [])
    ref = source_ref("connection:" + str(connection.id))
    return store, HistoryService(store), connection, ref


def test_selected_connection_earn_history_uses_fake_http_and_stored_apply_evidence(earn_job, monkeypatch):
    store, service, connection, ref = earn_job
    requests = []
    timestamp = 1735689600000

    def handler(request):
        query = parse_qs(request.url.query.decode("ascii"))
        endpoint = request.url.path
        page = int(query.get("current", ["1"])[0])
        requests.append((endpoint, page, query.get("asset", [None])[0],
                         query.get("productId", [None])[0], query.get("type", [None])[0],
                         query.get("positionId", [None])[0]))
        if endpoint.endswith("flexible/history/subscriptionRecord"):
            if page == 1:
                rows = [{
                    "asset": "JUP", "amount": "0.1", "productId": "JUP001",
                    "purchaseId": f"purchase-{index}", "positionId": "flex-position-a",
                    "time": timestamp, "status": "SUCCESS",
                } for index in range(100)]
                return httpx.Response(200, json={"rows": rows, "total": 101})
            return httpx.Response(200, json={"rows": [{
                "asset": "JUP", "amount": "0.1", "productId": "JUP001",
                "purchaseId": "purchase-100", "positionId": "flex-position-a",
                "time": timestamp, "status": "SUCCESS",
            }], "total": 101})
        if endpoint.endswith("flexible/history/redemptionRecord"):
            rows = [{"asset": "JUP", "amount": "0.05", "productId": "JUP001",
                     "redeemId": "flex-redeem-a", "time": timestamp, "status": "SUCCESS"}]
        elif endpoint.endswith("flexible/history/rewardsRecord"):
            reward_type = query.get("type", [""])[0]
            rows = [{"asset": "JUP", "rewards": "0.001", "productId": "JUP001",
                     "id": f"flex-reward-{reward_type}", "time": timestamp, "type": reward_type}]
        elif endpoint.endswith("locked/history/subscriptionRecord"):
            rows = [{"asset": "SOL", "amount": "0.5", "productId": "SOL001",
                     "positionId": "locked-position-a", "purchaseId": "locked-buy-a",
                     "time": timestamp, "status": "SUCCESS"}]
        elif endpoint.endswith("locked/history/redemptionRecord"):
            rows = [{"asset": "SOL", "amount": "0.25", "productId": "SOL001",
                     "positionId": "locked-position-a", "redeemId": "locked-redeem-a",
                     "time": timestamp, "status": "SUCCESS"}]
        elif endpoint.endswith("locked/history/rewardsRecord"):
            rows = [{"asset": "SOL", "rewards": "0.002", "productId": "SOL001",
                     "positionId": "locked-position-a", "id": "locked-reward-a",
                     "time": timestamp}]
        else:
            pytest.fail(f"Unexpected fake provider endpoint: {endpoint}")
        return httpx.Response(200, json={"rows": rows, "total": len(rows)})

    import steuerreport_v2.domain.binance_earn as earn_module
    from steuerreport_v2.domain.history_cex import CexHistoryCollector

    real_managed_client = earn_module.managed_client
    monkeypatch.setattr(earn_module, "managed_client", lambda **kwargs: real_managed_client(
        transport=httpx.MockTransport(handler), **kwargs,
    ))
    monkeypatch.setattr(CexHistoryCollector, "fetch_page", lambda _self, _cursor, check: (
        check() or HistoryPage([], {"spot_done": True}, True)
    ))

    request = HistoryStart(
        request_id=uuid4(), confirm_external_request=True,
        start="2025-01-01", end="2025-01-01", symbols=["BTCEUR"],
        include_binance_earn=True, max_records=1000,
    )
    job = service.start(ref, request)
    assert job.includes_binance_earn is True
    assert job.provider_request_limit == 10000
    service._run(str(job.id))
    ready = service.get(ref, str(job.id))
    assert ready.status == "ready", service.storage.load(str(job.id)).get("error_code")
    assert ready.complete_history_proven is False
    stored = HistoryStorage(store).records(service.storage.load(str(job.id)))
    assert ready.records_fetched == 108, {
        "record_types": Counter(record.raw["record_type"] for record in stored),
        "subscription_pages": [(path, page, asset, product, reward_type)
                               for path, page, asset, product, reward_type, _ in requests
                               if path.endswith("flexible/history/subscriptionRecord")],
        "request_count": len(requests),
    }
    assert ready.provider_requests_reserved == len(requests) == 9
    assert any("Aufbewahrungsabdeckung" in note for note in ready.coverage_notes)
    assert sum(1 for path, page, *_rest in requests
               if path.endswith("flexible/history/subscriptionRecord") and page == 1) == 1
    assert [(page, position) for path, page, _, _, _, position in requests
            if path.endswith("flexible/history/subscriptionRecord")] == [(1, None), (2, None)]
    assert all(position == "locked-position-a" for path, _page, _, _, _, position in requests
               if "/locked/history/" in path and not path.endswith("subscriptionRecord"))

    stored_records = HistoryStorage(store).records(service.storage.load(str(job.id)))
    earn_records = [record for record in stored_records if record.source == "binance_simple_earn_api"]
    assert len(earn_records) == 108
    assert any(record.raw["payload"].get("purchaseId") == "purchase-100" for record in earn_records)
    assert all(row["account"] == f"connection:{connection.id}"
               for record in earn_records for row in record.rows)

    monkeypatch.setattr(earn_module, "managed_client", lambda **_kwargs: pytest.fail("apply must not refetch"))
    approved = service.approve(ref, str(job.id), HistoryApprove(
        preview_sha256=ready.preview_sha256, actor="Synthetic reviewer",
        confirm_import=True, confirm_recalculation=True,
    ))
    assert approved.status == "succeeded"
    assert approved.imported_events > 0
    with store.connect() as con:
        batches = con.execute(
            "select source, connection_id from raw_import_batches where source='binance_simple_earn_api'",
        ).fetchall()
        assert batches == [("binance_simple_earn_api", str(connection.id))]
        assert con.execute(
            """select count(*) from canonical_events e
               join raw_objects r using(raw_object_id)
               join raw_import_batches b using(batch_id)
               where e.source='binance_simple_earn_api' and b.connection_id=?""",
            [str(connection.id)],
        ).fetchone()[0] == approved.imported_events


def test_earn_import_identity_is_scoped_to_selected_account(earn_job):
    store, _service, connection, _ref = earn_job
    from steuerreport_v2.domain.history_types import HistoryRecord, HistoryTarget
    from steuerreport_v2.importers.source_history_importer import scope_identity

    record = HistoryRecord(
        identity="binance-earn:locked_rewards:provider-id-7",
        source="binance_simple_earn_api", rows=[], raw={"payload": {"id": "provider-id-7"}},
    )
    target_a = HistoryTarget("ref-a", "A", "binance", f"connection:{connection.id}", connection_id=str(connection.id))
    target_b = HistoryTarget("ref-b", "B", "binance", "connection:other", connection_id=str(uuid4()))
    assert scope_identity(target_a, record) != scope_identity(target_b, record)
