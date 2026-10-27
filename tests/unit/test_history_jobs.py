from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
import json
import os
from uuid import uuid4

from fastapi.testclient import TestClient
from nacl.signing import SigningKey
from pydantic import SecretStr
import pytest

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.admin import AdminSettingWrite
from steuerreport_v2.contracts.connectors import PublicWalletAddressRequest
from steuerreport_v2.contracts.connections import ConnectionCreate
from steuerreport_v2.contracts.history import HistoryApprove, HistoryResume, HistoryStart
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.connectors import ConnectorService
from steuerreport_v2.domain.connections import ConnectionService
from steuerreport_v2.domain.history_cex import CexHistoryCollector
from steuerreport_v2.domain.history import HistoryService
from steuerreport_v2.domain.history_storage import HistoryStorage
from steuerreport_v2.domain.history_types import HistoryFetchError, HistoryOptions, HistoryPage, HistoryRecord
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.source_registry import SourceRegistryService
from steuerreport_v2.domain.secret_vault import KEY_FILE_ENV
from steuerreport_v2.domain.workspace import source_ref


def base58(value):
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number, result = int.from_bytes(value, "big"), ""
    while number:
        number, digit = divmod(number, 58)
        result = alphabet[digit] + result
    return "1" * (len(value) - len(value.lstrip(b"\0"))) + result


@pytest.fixture
def setup(tmp_path, monkeypatch):
    profile = tmp_path / "profile.json"
    profile.write_text("{}")
    registry = tmp_path / "registry.json"
    registry.write_text('{"registry_version":"test","entries":[],"ledger_adjustments":[],"transfer_evidence":[]}')
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", str(profile))
    monkeypatch.setattr(PortfolioService, "PRIMARY_SOLANA_WALLET", "")
    monkeypatch.setattr(PortfolioService, "KNOWN_JUP_WALLET", "")
    monkeypatch.setattr(PortfolioService, "SOURCE_REGISTRY_CONFIG_PATH", registry)
    monkeypatch.setattr(SourceRegistryService, "DEFAULT_CONFIG_PATH", registry)
    monkeypatch.setattr(HistoryService, "_launch", lambda *_args: None)
    store = DuckDbStore(tmp_path / "test.duckdb")
    address = base58(SigningKey(bytes(range(32))).verify_key.encode())
    ConnectorService(store).save_public_wallet(PublicWalletAddressRequest(wallet_address=address, display_label="Synthetic history wallet"))
    ref = source_ref("wallet:" + address)
    service = HistoryService(store)
    return store, service, ref, address


def request(**kwargs):
    return HistoryStart(request_id=uuid4(), confirm_external_request=True, start="2025-01-01", end="2025-01-02", **kwargs)


def records(wallet, identity="synthetic-signature-a", amount="10", context="initial"):
    return [HistoryRecord(identity=identity, source="solana_rpc", raw={"transaction": {"synthetic": identity, "amount": amount}, "discovery": context}, rows=[
        {"timestamp_utc": "2025-01-01T12:00:00Z", "event_type": "token_transfer", "asset": "TESTTOKEN", "quantity": amount,
         "side": "in", "tx_id": identity, "wallet_address": wallet, "history_mapper_version": "2"},
        {"timestamp_utc": "2025-01-01T12:00:00Z", "event_type": "network_fee", "asset": "SOL", "quantity": "0.000005",
         "side": "out", "tx_id": identity, "wallet_address": wallet, "history_mapper_version": "2"},
    ])]


class Collector:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def fetch_page(self, cursor, check):
        check()
        self.calls.append(deepcopy(cursor))
        index = cursor.get("page", 0)
        page = self.pages[index]
        if isinstance(page, Exception):
            raise page
        return HistoryPage(deepcopy(page), {"page": index + 1}, index + 1 == len(self.pages), requests=1,
                           notes=("Synthetic provider coverage is limited.",))


def collect(monkeypatch, service, ref, pages):
    collector = Collector(pages)
    monkeypatch.setattr(HistoryService, "_collector", lambda *_args: collector)
    job = service.start(ref, request())
    service._run(str(job.id))
    return service.get(ref, str(job.id)), collector


def approve(job):
    return HistoryApprove(preview_sha256=job.preview_sha256, actor="Synthetic reviewer",
                          confirm_import=True, confirm_recalculation=True)


def financial_state(store):
    with store.connect() as con:
        return {table: con.execute(f"select * from {table} order by all").fetchall() for table in (
            "raw_import_batches", "raw_objects", "canonical_events", "balance_ledger", "tax_lines", "review_decisions",
            "price_ledger",
        )}


def test_fetch_preview_approval_are_separate_and_repeat_import_is_idempotent(setup, monkeypatch):
    store, service, ref, wallet = setup
    before = financial_state(store)
    job, collector = collect(monkeypatch, service, ref, [records(wallet)])
    assert job.status == "ready", service.storage.load(str(job.id)).get("error_code")
    assert job.records_fetched == job.new_records == 1 and job.imported_events == 0
    assert job.preview_sha256 and not job.complete_history_proven
    assert financial_state(store) == before
    result = service.approve(ref, str(job.id), approve(job))
    assert result.status == "succeeded" and result.imported_events == 2
    events = store.list_canonical_events()
    assert len(events) == 2 and {event.event_type for event in events} == {"transfer", "fee"}
    assert {event.account for event in events} == {wallet}
    assert collector.calls == [{}]
    snapshot = financial_state(store)
    assert service.approve(ref, str(job.id), approve(job)).status == "succeeded"
    assert financial_state(store) == snapshot
    assert len(store.list_review_decisions()) == 1


def test_source_get_reload_and_duplicate_start_do_not_fetch_or_mutate_finances(setup):
    store, service, ref, _wallet = setup
    before = financial_state(store)
    service.view(ref)
    assert not service.storage.jobs() and financial_state(store) == before
    payload = request()
    first = service.start(ref, payload)
    repeated = service.start(ref, payload)
    assert repeated.id == first.id
    assert len(service.storage.jobs()) == 1
    assert financial_state(store) == before
    with pytest.raises(HistoryFetchError, match="source_job_exists"):
        service.start(ref, request())


def test_page_error_preserves_checkpoint_and_new_service_can_resume(setup, monkeypatch):
    store, service, ref, wallet = setup
    collector = Collector([records(wallet), HistoryFetchError("solana_transaction_missing")])
    monkeypatch.setattr(HistoryService, "_collector", lambda *_args: collector)
    job = service.start(ref, request())
    service._run(str(job.id))
    paused = service.get(ref, str(job.id))
    assert paused.status == "paused" and paused.records_fetched == 1
    assert service.storage.load(str(job.id))["_cursor"] == {"page": 1}
    assert not store.list_canonical_events()
    collector.pages[1] = records(wallet, identity="synthetic-signature-b", amount="20")
    fresh = HistoryService(DuckDbStore(store.path))
    fresh.control(ref, str(job.id), "resume", HistoryResume(confirm_external_request=True))
    fresh._run(str(job.id))
    assert fresh.get(ref, str(job.id)).status == "ready"
    assert collector.calls[-1] == {"page": 1}
    assert not store.list_canonical_events()


def test_different_source_cannot_read_control_approve_or_audit_job(setup):
    _store, service, ref, _wallet = setup
    job = service.start(ref, request())
    other = source_ref("wallet:other-synthetic")
    for action in (lambda: service.get(other, str(job.id)), lambda: service.control(other, str(job.id), "cancel"), lambda: service.audit(other, str(job.id))):
        with pytest.raises(HistoryFetchError, match="not_found"):
            action()


def test_stale_preview_or_modified_original_cannot_apply(setup, monkeypatch):
    store, service, ref, wallet = setup
    job, _ = collect(monkeypatch, service, ref, [records(wallet)])
    assert job.status == "ready"
    store.add_price_point(PricePointCreate(asset="SOL", price_eur="100", source="synthetic", priced_at=datetime(2025, 1, 1, tzinfo=timezone.utc)))
    before = financial_state(store)
    with pytest.raises(HistoryFetchError, match="preview_stale"):
        service.approve(ref, str(job.id), approve(job))
    assert financial_state(store) == before


def test_raw_evidence_tampering_is_detected_before_import(setup, monkeypatch):
    store, service, ref, wallet = setup
    job, _ = collect(monkeypatch, service, ref, [records(wallet)])
    assert job.status == "ready"
    record_hash = next(iter(service.storage.load(str(job.id))["_records"].values()))
    path = service.storage.directory(str(job.id)) / "records" / (record_hash + ".json")
    path.write_text("{}")
    with pytest.raises(HistoryFetchError, match="evidence_changed"):
        service.approve(ref, str(job.id), approve(job))
    assert not store.list_canonical_events()


def test_record_directory_symlink_cannot_redirect_evidence_writes_or_reads(setup):
    store, service, ref, wallet = setup
    job = service.start(ref, request())
    outside = store.path.parent / "unrelated-private-directory"
    outside.mkdir()
    (service.storage.directory(str(job.id)) / "records").symlink_to(outside, target_is_directory=True)
    for action in (
        lambda: service.storage.write_record(str(job.id), records(wallet)[0]),
        lambda: service.storage.records(service.storage.load(str(job.id))),
    ):
        with pytest.raises(HistoryFetchError, match="history_storage_invalid"):
            action()
    assert list(outside.iterdir()) == []


def test_cex_trade_preview_applies_derived_prices_without_changing_original_prices(setup, monkeypatch):
    from steuerreport_v2.domain.history_preview import _summary

    store, service, _ref, _wallet = setup
    vault = store.path.parent / "synthetic-vault.key"
    vault.write_bytes(bytes(range(32)))
    vault.chmod(0o600)
    monkeypatch.setenv(KEY_FILE_ENV, str(vault))
    connection = ConnectionService(store).create(ConnectionCreate(
        provider="binance", label="Synthetic trade account", account="Synthetic spot",
        api_key=SecretStr("synthetic-trade-key"), api_secret=SecretStr("synthetic-trade-secret"),
    ))
    ref = source_ref("connection:" + str(connection.id))
    first = datetime(2025, 1, 1, 12, tzinfo=timezone.utc)
    second = datetime(2025, 1, 2, 12, tzinfo=timezone.utc)
    for asset, price, source in (("ETH", "3000", "synthetic-original"), ("OLD", "5", "derived:event_quote")):
        store.add_price_point(PricePointCreate(asset=asset, price_eur=price, source=source, priced_at=first))
    before = financial_state(store)
    adapter = CexHistoryCollector(store, service._target(ref), HistoryOptions(first, second, ("BTCEUR",)))
    entries = [adapter._record("/api/v3/myTrades", [identity], {"synthetic": identity}, [
        adapter._row(timestamp, "BTC", Decimal("1"), side, "EUR", Decimal(amount), "EUR", Decimal("0")),
    ]) for identity, timestamp, side, amount in (("buy", first, "buy", "20000"), ("sell", second, "sell", "25000"))]
    collector = Collector([entries])
    monkeypatch.setattr(HistoryService, "_collector", lambda *_args: collector)
    job = service.start(ref, request(symbols=["BTCEUR"]))
    service._run(str(job.id))
    ready = service.get(ref, str(job.id))
    assert ready.status == "ready", ready.error_code
    assert [(row["asset"], Decimal(row["quantity"])) for row in ready.sample_rows] == [
        ("BTC", Decimal("1")), ("BTC", Decimal("-1")),
    ]
    assert financial_state(store) == before
    service.approve(ref, str(job.id), approve(ready))
    with store.connect() as con:
        prices = con.execute("select asset, price_eur from price_ledger where source='derived:event_quote' order by priced_at").fetchall()
        originals = con.execute("select * from price_ledger where source='synthetic-original' order by all").fetchall()
        expected_originals = [row for row in before["price_ledger"] if "synthetic-original" in row]
        assert originals == expected_originals
        assert prices == [("BTC", Decimal("20000")), ("BTC", Decimal("25000"))]
        applied = _summary(con)
        assert Decimal(applied["tax"]["2025"]["gain_loss_eur"]) == Decimal("5000")
        assert applied == ready.after_summary
    PipelineService(store).rebuild_ledgers()
    with store.connect() as con:
        assert _summary(con) == applied


def test_repeated_new_job_skips_existing_financial_records_despite_new_discovery_metadata(setup, monkeypatch):
    store, service, ref, wallet = setup
    first, _ = collect(monkeypatch, service, ref, [records(wallet)])
    assert first.status == "ready"
    service.approve(ref, str(first.id), approve(first))
    before = financial_state(store)
    second, _ = collect(monkeypatch, service, ref, [records(wallet, context="changed current token balance")])
    assert second.status == "ready", service.storage.load(str(second.id)).get("error_code")
    assert second.new_records == 0 and second.duplicate_records == 1
    service.approve(ref, str(second.id), approve(second))
    after = financial_state(store)
    assert after["canonical_events"] == before["canonical_events"]
    assert after["balance_ledger"] == before["balance_ledger"]
    assert after["tax_lines"] == before["tax_lines"]
    assert after["raw_objects"] == before["raw_objects"]


def test_zero_effect_transactions_remain_raw_evidence_without_invented_events(setup, monkeypatch):
    store, service, ref, wallet = setup
    evidence = replace(records(wallet)[0], rows=[])
    job, _ = collect(monkeypatch, service, ref, [[evidence]])
    assert job.status == "ready"
    service.approve(ref, str(job.id), approve(job))
    assert not store.list_canonical_events()
    with store.connect() as con:
        assert con.execute("select count(*) from raw_objects").fetchone()[0] == 1
    assert store.unmapped_raw_object_counts() == {}


def test_api_requires_explicit_consents_and_blocks_demo_mutations(setup):
    store, _service, ref, _wallet = setup
    app = create_app(store)
    client = TestClient(app)
    path = f"/api/v1/workspace/sources/{ref}/history"
    assert client.get(path).status_code == 200
    for value in (False, "true", 1, None):
        response = client.post(path + "/jobs", json={"request_id": str(uuid4()), "confirm_external_request": value})
        assert response.status_code == 422
        assert "input" not in response.text
    app.state.ux_sandbox = True
    assert client.post(path + "/jobs", json=request().model_dump(mode="json")).status_code == 403
    assert not HistoryStorage(store).jobs()


def test_job_and_audit_responses_never_include_credential_store_or_internal_paths(setup):
    store, service, ref, _wallet = setup
    store.upsert_admin_setting(AdminSettingWrite(key="secret.unrelated.synthetic", value_json='"SYNTHETIC_PRIVATE_VALUE_NOT_FOR_RESPONSE"'))
    job = service.start(ref, request())
    encoded = json.dumps(service.view(ref).model_dump(mode="json")) + json.dumps(service.audit(ref, str(job.id)))
    assert "SYNTHETIC_PRIVATE_VALUE_NOT_FOR_RESPONSE" not in encoded
    assert '"_binding"' not in encoded and '"_records"' not in encoded
    assert str(store.path.parent) not in encoded


@pytest.mark.parametrize("action", ["pause", "cancel"])
def test_control_between_pages_keeps_checkpoint_and_stops_further_requests(setup, monkeypatch, action):
    store, service, ref, wallet = setup
    collector = Collector([records(wallet), records(wallet, identity="second")])
    original = collector.fetch_page
    job_id = None

    def fetch(cursor, check):
        if cursor:
            service.control(ref, job_id, action)
            # Force the next check to observe the durable request immediately.
            check.__self__.checked_at = 0
        return original(cursor, check)

    collector.fetch_page = fetch
    monkeypatch.setattr(HistoryService, "_collector", lambda *_args: collector)
    job = service.start(ref, request())
    job_id = str(job.id)
    service._run(job_id)
    stopped = service.get(ref, job_id)
    assert stopped.status == ("paused" if action == "pause" else "cancelled")
    assert stopped.records_fetched == 1 and collector.calls == [{}]
    assert service.storage.load(job_id)["_cursor"] == {"page": 1}
    assert not store.list_canonical_events()


def test_restart_is_reported_as_paused_without_automatic_external_restart(setup, monkeypatch):
    _store, service, ref, _wallet = setup
    job = service.start(ref, request())
    saved = service.storage.load(str(job.id))
    saved["_pid"] = os.getpid()
    saved["_until"] = "2000-01-01T00:00:00+00:00"
    service.storage.save(saved)
    launches = []
    monkeypatch.setattr(HistoryService, "_launch", lambda _self, identity: launches.append(identity))
    restarted = HistoryService(service.store)
    assert restarted.get(ref, str(job.id)).status == "paused"
    assert restarted.view(ref).jobs[0].error_code == "history_worker_stopped"
    assert launches == []
    assert restarted.storage.load(str(job.id))["status"] == "queued"


def test_request_time_slice_continues_same_job_without_resetting_checkpoint(setup, monkeypatch):
    _store, service, ref, wallet = setup
    collector = Collector([records(wallet), HistoryFetchError("history_run_deadline")])
    monkeypatch.setattr(HistoryService, "_collector", lambda *_args: collector)
    job = service.start(ref, request())
    launches = []
    monkeypatch.setattr(HistoryService, "_launch", lambda _self, identity: launches.append(identity))
    service._run(str(job.id))
    assert launches == [str(job.id)]
    queued = service.storage.load(str(job.id))
    assert queued["status"] == "queued" and queued["_cursor"] == {"page": 1}
    collector.pages[1] = records(wallet, identity="second")
    service._run(str(job.id))
    assert service.get(ref, str(job.id)).status == "ready"
    assert len(service.storage.jobs()) == 1


def test_failure_inside_approval_rolls_back_raw_events_and_decision(setup, monkeypatch):
    import steuerreport_v2.domain.history_preview as preview_module

    store, service, ref, wallet = setup
    job, _collector = collect(monkeypatch, service, ref, [records(wallet)])
    before = financial_state(store)
    original = preview_module._summary

    def fail_after_writes(con):
        original(con)
        raise RuntimeError("synthetic transaction failure")

    monkeypatch.setattr(preview_module, "_summary", fail_after_writes)
    with pytest.raises(RuntimeError, match="synthetic transaction failure"):
        service.approve(ref, str(job.id), approve(job))
    assert financial_state(store) == before
    assert service.get(ref, str(job.id)).status == "ready"
    monkeypatch.setattr(preview_module, "_summary", original)
    assert service.approve(ref, str(job.id), approve(job)).status == "succeeded"


def test_modified_financial_record_is_blocked_not_overwritten(setup, monkeypatch):
    store, service, ref, wallet = setup
    first, _ = collect(monkeypatch, service, ref, [records(wallet)])
    service.approve(ref, str(first.id), approve(first))
    before = financial_state(store)
    second, _ = collect(monkeypatch, service, ref, [records(wallet, amount="11")])
    assert second.status == "failed"
    assert second.error_code == "history_existing_evidence_conflict"
    assert financial_state(store) == before
