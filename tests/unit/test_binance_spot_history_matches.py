from dataclasses import asdict
import base64
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Event
from uuid import uuid4

import pytest
from pydantic import SecretStr

from steuerreport_v2.contracts.connections import ConnectionCreate
from steuerreport_v2.contracts.history import (
    BinanceSpotMatchDecisionCreate,
    BinanceSpotMatchPreviewRequest,
    BinanceSpotMatchRevocation,
    HistoryApprove,
)
from steuerreport_v2.contracts.imports import ImportAssistantRequest
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.binance_spot_matches import BinanceSpotHistoryMatchService
from steuerreport_v2.domain.connections import ConnectionService
from steuerreport_v2.domain.history_preview import HistoryPreview
from steuerreport_v2.domain.history_storage import HistoryStorage
from steuerreport_v2.domain.history_types import HistoryFetchError, HistoryRecord, HistoryTarget
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.secret_vault import KEY_FILE_ENV
from steuerreport_v2.importers.binance_spot_lock import BINANCE_SPOT_IMPORT_LOCK
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.source_history_importer import import_records


HEADER = "Trade ID,Symbol,UTC Time,Coin,Change,Operation,quote_asset,quote_quantity,fee_asset,fee_quantity\n"


def csv_text(*, trade_id="42", quantity="0.1", fee="0.001", include_id=True):
    cols = [trade_id, "BTCUSDT", "2025-01-01T12:00:00Z", "BTC", quantity,
            "buy", "USDT", "1000", "BNB", fee]
    if not include_id:
        cols[0] = ""
    return HEADER + ",".join(cols) + "\n"


def environment(tmp_path, monkeypatch, count=1):
    vault_key = tmp_path / "synthetic-vault.key"
    vault_key.write_bytes(bytes(range(32)))
    vault_key.chmod(0o600)
    monkeypatch.setenv(KEY_FILE_ENV, str(vault_key))
    store = DuckDbStore(tmp_path / "matches.duckdb")
    connections = [ConnectionService(store).create(ConnectionCreate(
        provider="binance", label=f"Synthetic Binance {i}", account=f"account-{i}",
        api_key=SecretStr(f"key-{i}"), api_secret=SecretStr(f"secret-{i}"),
    )) for i in range(count)]
    targets = [HistoryTarget(
        source_ref=f"binance-source-{i}", label=f"Synthetic Binance {i}", provider="binance",
        account="connection:" + str(connection.id), connection_id=str(connection.id),
    ) for i, connection in enumerate(connections)]
    return store, connections, targets


def api_record(target, *, trade_id="42", quantity="0.1", fee="0.001"):
    identity = "cex:" + json.dumps([
        "binance", target.account, "/api/v3/myTrades", "BTCUSDT", str(trade_id),
    ], ensure_ascii=True, separators=(",", ":"))
    row = {
        "utc time": "2025-01-01T12:00:00+00:00", "coin": "BTC", "change": quantity,
        "operation": "buy", "account": target.account, "quote_asset": "USDT",
        "quote_quantity": "1000", "fee_asset": "BNB", "fee_quantity": fee, "id": identity,
    }
    raw = {"endpoint": "/api/v3/myTrades", "payload": {
        "id": int(trade_id), "symbol": "BTCUSDT", "time": 1735732800000,
        "isBuyer": True, "qty": quantity, "quoteQty": "1000", "commission": fee,
        "commissionAsset": "BNB",
    }}
    return HistoryRecord(identity=identity, source="binance", rows=[row], raw=raw)


def save_job(store, target, record, status="ready"):
    storage = HistoryStorage(store)
    job_id = str(uuid4())
    record_file_hash = storage.write_record(job_id, record)
    job = {
        "id": job_id, "source_ref": target.source_ref, "provider": "binance", "status": status,
        "_target": asdict(target), "_options": {
            "start": "2025-01-01T00:00:00+00:00", "end": "2025-01-02T00:00:00+00:00",
        },
        "_records": {record_file_hash: record_file_hash},
    }
    storage.save(job)
    return job


def bind(store, target, content):
    batch = CsvRawImporter(store).import_text(
        source="binance", filename="synthetic_utc.csv", content=content,
        connection_id=target.connection_id,
    )
    PipelineService(store).rebuild_after_import(batch.batch_id)
    return batch


def create_match(service, ref, job, target, source, *, row_number=1, content=None, batch_id=None):
    preview_request = BinanceSpotMatchPreviewRequest(
        batch_id=batch_id, filename=None if batch_id else "synthetic_utc.csv",
        content=content if not batch_id else None,
    )
    preview = service.preview(ref, job["id"], preview_request)
    candidate = next(item for item in preview.candidates if item.csv_row_number == row_number)
    assert candidate.status == "matchable"
    return service.decide(ref, job["id"], BinanceSpotMatchDecisionCreate(
        batch_id=batch_id, filename=None if batch_id else "synthetic_utc.csv",
        content=content if not batch_id else None,
        preview_sha256=preview.preview_sha256, csv_row_number=row_number,
        api_record_identity=candidate.api_record_identity, actor="Synthetic reviewer",
        rationale="Die Originalbelege und der identische Spot-Fill wurden geprueft.",
        confirm_match=True,
    )), preview


def test_csv_first_explicit_match_skips_api_event_and_keeps_both_references(tmp_path, monkeypatch):
    store, _connections, (target,) = environment(tmp_path, monkeypatch)
    content = csv_text()
    batch = bind(store, target, content)
    before_event_ids = [event.event_id for event in store.list_canonical_events()]
    record = api_record(target)
    job = save_job(store, target, record)
    service = BinanceSpotHistoryMatchService(store)
    decision, preview = create_match(service, target.source_ref, job, target, "", batch_id=batch.batch_id)
    assert preview.candidates[0].status == "matchable"
    facts = preview.candidates[0]
    assert facts.csv_financial_facts.quantity == "0.1"
    assert facts.api_financial_facts.quantity == "0.1"
    assert facts.csv_financial_facts.quote_asset == "USDT"
    assert facts.api_financial_facts.fee_asset == "BNB"
    assert len(store.list_review_decisions()) == 1

    live_job = HistoryStorage(store).load(job["id"])
    prepared = HistoryPreview(store).prepare(live_job, target)
    assert prepared["new_records"] == 0
    assert prepared["duplicate_records"] == 1
    assert prepared["imported_events"] == 0
    live_job.update(status="ready", _preview=prepared)
    HistoryPreview(store).apply(live_job, HistoryApprove(
        preview_sha256=prepared["preview_sha256"], actor="Synthetic reviewer",
        confirm_import=True, confirm_recalculation=True,
    ))
    assert [event.event_id for event in store.list_canonical_events()] == before_event_ids
    saved = next(row for row in store.list_review_decisions() if row.decision_id == decision.decision_id)
    assert saved.updated_at is None
    assert saved.payload["csv_raw_object_id"]
    assert saved.payload["api_record_identity"] == record.identity


def test_match_decision_cannot_race_binance_history_preview_snapshot(tmp_path, monkeypatch):
    store, _connections, (target,) = environment(tmp_path, monkeypatch)
    content = csv_text()
    batch = CsvRawImporter(store).import_text(
        source="binance", filename="synthetic_utc.csv", content=content,
        connection_id=target.connection_id,
    )
    record = api_record(target)
    job = save_job(store, target, record)
    service = BinanceSpotHistoryMatchService(store)
    preview = service.preview(target.source_ref, job["id"], BinanceSpotMatchPreviewRequest(batch_id=batch.batch_id))
    candidate = preview.candidates[0]
    request = BinanceSpotMatchDecisionCreate(
        batch_id=batch.batch_id, preview_sha256=preview.preview_sha256,
        csv_row_number=candidate.csv_row_number, api_record_identity=candidate.api_record_identity,
        actor="Synthetic reviewer", rationale="Entscheidung waehrend Vorbereitung darf nicht eingemischt werden.",
        confirm_match=True,
    )

    filtered = Event()
    continue_prepare = Event()
    original_filter = BinanceSpotHistoryMatchService.history_records_for_import

    def pause_after_filter(match_service, current_job, current_target, records):
        result = original_filter(match_service, current_job, current_target, records)
        filtered.set()
        if not continue_prepare.wait(10):
            raise TimeoutError("test did not release preview preparation")
        return result

    monkeypatch.setattr(BinanceSpotHistoryMatchService, "history_records_for_import", pause_after_filter)

    with ThreadPoolExecutor(max_workers=2) as executor:
        prepare_future = executor.submit(HistoryPreview(store).prepare, job, target)
        assert filtered.wait(5)
        try:
            assert not BINANCE_SPOT_IMPORT_LOCK.acquire(blocking=False)
            decide_future = executor.submit(service.decide, target.source_ref, job["id"], request)
        finally:
            continue_prepare.set()
        prepared = prepare_future.result(timeout=20)
        decision = decide_future.result(timeout=20)

    assert decision.decision_type == "binance_spot_csv_api_match"
    live_job = {**job, "status": "ready", "_preview": prepared}
    with pytest.raises(HistoryFetchError, match="history_preview_stale"):
        HistoryPreview(store).apply(live_job, HistoryApprove(
            preview_sha256=prepared["preview_sha256"], actor="Synthetic reviewer",
            confirm_import=True, confirm_recalculation=True,
        ))


def test_api_first_explicit_match_imports_csv_as_evidence_only(tmp_path, monkeypatch):
    store, _connections, (target,) = environment(tmp_path, monkeypatch)
    record = api_record(target)
    job = save_job(store, target, record, status="succeeded")
    api_batches = import_records(store, target, [record], job["id"])
    PipelineService(store).rebuild_after_import(api_batches[0].batch_id)
    before = list(store.list_canonical_events())
    content = csv_text()
    service = BinanceSpotHistoryMatchService(store)
    decision, preview = create_match(service, target.source_ref, job, target, "", content=content)
    assert preview.candidates[0].status == "matchable"

    import_request = ImportAssistantRequest(
        source="binance", filename="synthetic_utc.csv", content=content,
        connection_id=target.connection_id,
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        concurrent_results = list(executor.map(
            lambda _index: service.import_csv_if_needed(import_request), range(2),
        ))
    completed = [result for result in concurrent_results if result is not None]
    assert len(completed) == 1
    result = completed[0]
    assert result is not None
    assert len(store.list_canonical_events()) == len(before) == 1
    assert result.run.pipeline.normalized_events == 0
    assert result.batch.file_hash == preview.file_sha256
    with store.connect() as con:
        raw = json.loads(con.execute(
            "select payload_json from raw_objects where batch_id=?", [result.batch.batch_id],
        ).fetchone()[0])
        assert raw["Trade ID"] == "42"
        assert raw["history_evidence_only"] == "1"
        assert raw["history_scope_identity"] == decision.payload["history_scope_identity"]
        assert con.execute("select count(*) from canonical_events where raw_object_id in (select raw_object_id from raw_objects where batch_id=?)",
                           [result.batch.batch_id]).fetchone()[0] == 0
    with pytest.raises(HistoryFetchError, match="history_match_revoke_after_import"):
        service.revoke(target.source_ref, decision.decision_id, BinanceSpotMatchRevocation(
            actor="Synthetic reviewer", rationale="Revocation after application must be blocked.",
        ))


def test_match_after_both_api_and_csv_imports_is_rejected(tmp_path, monkeypatch):
    store, _connections, (target,) = environment(tmp_path, monkeypatch)
    content = csv_text()
    batch = bind(store, target, content)
    record = api_record(target)
    job = save_job(store, target, record, status="succeeded")
    api_batches = import_records(store, target, [record], job["id"])
    PipelineService(store).rebuild_after_import(api_batches[0].batch_id)
    preview = BinanceSpotHistoryMatchService(store).preview(
        target.source_ref, job["id"], BinanceSpotMatchPreviewRequest(batch_id=batch.batch_id),
    )
    candidate = preview.candidates[0]
    with pytest.raises(HistoryFetchError, match="history_match_both_sources_already_imported"):
        BinanceSpotHistoryMatchService(store).decide(target.source_ref, job["id"], BinanceSpotMatchDecisionCreate(
            batch_id=batch.batch_id, preview_sha256=preview.preview_sha256,
            csv_row_number=candidate.csv_row_number, api_record_identity=candidate.api_record_identity,
            actor="Synthetic reviewer", rationale="Beide Seiten wurden bereits importiert.", confirm_match=True,
        ))
    assert not store.list_review_decisions()


@pytest.mark.parametrize(("quantity", "fee"), [("0.2", "0.001"), ("0.1", "0.002")])
def test_changed_amount_or_fee_is_conflict_not_match(tmp_path, monkeypatch, quantity, fee):
    store, _connections, (target,) = environment(tmp_path, monkeypatch)
    job = save_job(store, target, api_record(target))
    preview = BinanceSpotHistoryMatchService(store).preview(
        target.source_ref, job["id"], BinanceSpotMatchPreviewRequest(
            filename="synthetic_utc.csv", content=csv_text(quantity=quantity, fee=fee),
        ),
    )
    assert preview.candidates[0].status == "financial_digest_conflict"
    candidate = preview.candidates[0]
    with pytest.raises(HistoryFetchError, match="history_match_not_exact"):
        BinanceSpotHistoryMatchService(store).decide(target.source_ref, job["id"], BinanceSpotMatchDecisionCreate(
            filename="synthetic_utc.csv", content=csv_text(quantity=quantity, fee=fee),
            preview_sha256=preview.preview_sha256, csv_row_number=1,
            api_record_identity=candidate.api_record_identity, actor="Synthetic reviewer",
            rationale="Digestabweichung bleibt ohne Matchentscheidung.", confirm_match=True,
        ))
    assert not store.list_review_decisions()


def test_missing_stable_id_never_matches(tmp_path, monkeypatch):
    store, _connections, (target,) = environment(tmp_path, monkeypatch)
    record = api_record(target)
    job = save_job(store, target, record, status="succeeded")
    service = BinanceSpotHistoryMatchService(store)
    missing_id_content = csv_text(include_id=False)
    preview = service.preview(target.source_ref, job["id"], BinanceSpotMatchPreviewRequest(
        filename="synthetic_utc.csv", content=missing_id_content,
    ))
    assert preview.candidates[0].status == "missing_stable_id"
    assert preview.candidates[0].api_record_identity is None
    api_batches = import_records(store, target, [record], job["id"])
    PipelineService(store).rebuild_after_import(api_batches[0].batch_id)
    with pytest.raises(ValueError, match="Tradezeile ohne eindeutige Trade-ID/Symbol"):
        service.import_csv_if_needed(ImportAssistantRequest(
            source="binance", filename="synthetic_utc.csv", content=missing_id_content,
            connection_id=target.connection_id,
        ))


def test_duplicate_csv_provider_id_is_ambiguous(tmp_path, monkeypatch):
    store, _connections, (target,) = environment(tmp_path, monkeypatch)
    job = save_job(store, target, api_record(target))
    content = csv_text() + csv_text().splitlines()[1] + "\n"

    preview = BinanceSpotHistoryMatchService(store).preview(target.source_ref, job["id"], BinanceSpotMatchPreviewRequest(
        filename="synthetic_utc.csv", content=content,
    ))
    assert [candidate.status for candidate in preview.candidates] == ["csv_id_ambiguous", "csv_id_ambiguous"]


def test_same_provider_record_id_isolated_by_connection(tmp_path, monkeypatch):
    store, _connections, targets = environment(tmp_path, monkeypatch, count=2)
    target_a, target_b = targets
    record_a = api_record(target_a)
    job_a = save_job(store, target_a, record_a, status="succeeded")
    api_batches_a = import_records(store, target_a, [record_a], job_a["id"])
    PipelineService(store).rebuild_after_import(api_batches_a[0].batch_id)
    job_b = save_job(store, target_b, api_record(target_b), status="succeeded")
    content = csv_text()
    service = BinanceSpotHistoryMatchService(store)
    decision, _ = create_match(service, target_a.source_ref, job_a, target_a, "", content=content)
    assert decision.payload["connection_id"] == target_a.connection_id

    api_rows_b = import_records(store, target_b, [api_record(target_b)], job_b["id"])
    PipelineService(store).rebuild_after_import(api_rows_b[0].batch_id)
    with pytest.raises(ValueError, match="ausdrueckliche CSV/API-Abgleichentscheidung"):
        service.import_csv_if_needed(ImportAssistantRequest(
            source="binance", filename="synthetic_utc.csv", content=content,
            connection_id=target_b.connection_id,
        ))
    # Both connection-scoped API imports remain distinct; the blocked CSV must
    # not add a third event to either account.
    assert len(store.list_canonical_events()) == 2


def test_duplicate_provider_id_in_same_connection_is_ambiguous(tmp_path, monkeypatch):
    store, _connections, (target,) = environment(tmp_path, monkeypatch)
    first = api_record(target)
    second = api_record(target, fee="0.002")
    job = save_job(store, target, first)
    storage = HistoryStorage(store)
    second_hash = storage.write_record(job["id"], second)
    job["_records"][second_hash] = second_hash
    storage.save(job)

    preview = BinanceSpotHistoryMatchService(store).preview(target.source_ref, job["id"], BinanceSpotMatchPreviewRequest(
        filename="synthetic_utc.csv", content=csv_text(),
    ))
    assert preview.candidates[0].status == "api_id_ambiguous"
    assert preview.candidates[0].api_record_identity is None


def test_stale_preview_and_append_only_revocation_block_reimport(tmp_path, monkeypatch):
    store, _connections, (target,) = environment(tmp_path, monkeypatch)
    record = api_record(target)
    job = save_job(store, target, record, status="succeeded")
    api_batches = import_records(store, target, [record], job["id"])
    PipelineService(store).rebuild_after_import(api_batches[0].batch_id)
    service = BinanceSpotHistoryMatchService(store)
    original_content = csv_text()
    old_preview = service.preview(target.source_ref, job["id"], BinanceSpotMatchPreviewRequest(
        filename="synthetic_utc.csv", content=original_content,
    ))
    candidate = old_preview.candidates[0]
    with pytest.raises(HistoryFetchError, match="history_match_preview_stale"):
        service.decide(target.source_ref, job["id"], BinanceSpotMatchDecisionCreate(
            filename="synthetic_utc.csv", content=csv_text(fee="0.002"),
            preview_sha256=old_preview.preview_sha256, csv_row_number=1,
            api_record_identity=candidate.api_record_identity, actor="Synthetic reviewer",
            rationale="Pruefung nach veraendertem Vorschauinhalt.", confirm_match=True,
        ))
    assert not store.list_review_decisions()

    decision, _ = create_match(service, target.source_ref, job, target, "", content=original_content)
    active_preview = service.preview(target.source_ref, job["id"], BinanceSpotMatchPreviewRequest(
        filename="synthetic_utc.csv", content=original_content,
    ))
    assert active_preview.candidates[0].decision_state == "active"
    assert active_preview.candidates[0].decision_id == decision.decision_id
    assert active_preview.candidates[0].status == "already_decided"
    revoke = service.revoke(target.source_ref, decision.decision_id, BinanceSpotMatchRevocation(
        actor="Synthetic reviewer", rationale="Zuordnung wird zur erneuten Pruefung widerrufen.",
    ))
    assert revoke.decision_type == "binance_spot_csv_api_match_revocation"
    assert len(store.list_review_decisions()) == 2
    original = next(row for row in store.list_review_decisions() if row.decision_id == decision.decision_id)
    assert original.updated_at is None
    revoked_preview = service.preview(target.source_ref, job["id"], BinanceSpotMatchPreviewRequest(
        filename="synthetic_utc.csv", content=original_content,
    ))
    assert revoked_preview.candidates[0].decision_state == "revoked"
    assert revoked_preview.candidates[0].status == "match_revoked"
    with pytest.raises(HistoryFetchError, match="history_match_revoked_review_required"):
        service.history_records_for_import(HistoryStorage(store).load(job["id"]), target, [record])
    with pytest.raises(ValueError, match="wurde widerrufen"):
        service.import_csv_if_needed(ImportAssistantRequest(
            source="binance", filename="synthetic_utc.csv", content=original_content,
            connection_id=target.connection_id,
        ))
    with pytest.raises(HistoryFetchError, match="history_match_decision_not_found"):
        service.revoke("different-source", decision.decision_id, BinanceSpotMatchRevocation(
            actor="Synthetic reviewer", rationale="Falscher Quellenkontext wird abgewiesen.",
        ))


def test_uploaded_csv_auto_binds_existing_batch_and_keeps_importer_row_number(tmp_path, monkeypatch):
    store, _connections, (target,) = environment(tmp_path, monkeypatch)
    row = csv_text().splitlines()[1]
    content = HEADER + ",,,,,,,,,\n" + row + "\n"
    batch = bind(store, target, content)
    job = save_job(store, target, api_record(target))
    service = BinanceSpotHistoryMatchService(store)

    preview = service.preview(target.source_ref, job["id"], BinanceSpotMatchPreviewRequest(
        filename="synthetic_utc.csv", content=content,
    ))
    assert preview.source_batch_id == batch.batch_id
    assert preview.candidates[0].csv_row_number == 2
    decision, _ = create_match(
        service, target.source_ref, job, target, "", row_number=2, content=content,
    )
    assert decision.payload["source_batch_id"] == batch.batch_id
    assert decision.payload["csv_raw_object_id"]


def test_uploaded_match_before_api_evidence_is_persisted_is_rejected(tmp_path, monkeypatch):
    store, _connections, (target,) = environment(tmp_path, monkeypatch)
    job = save_job(store, target, api_record(target), status="ready")
    service = BinanceSpotHistoryMatchService(store)
    content = csv_text()
    preview = service.preview(target.source_ref, job["id"], BinanceSpotMatchPreviewRequest(
        filename="synthetic_utc.csv", content=content,
    ))
    candidate = preview.candidates[0]

    with pytest.raises(HistoryFetchError, match="history_match_api_evidence_not_persisted"):
        service.decide(target.source_ref, job["id"], BinanceSpotMatchDecisionCreate(
            filename="synthetic_utc.csv", content=content,
            preview_sha256=preview.preview_sha256, csv_row_number=1,
            api_record_identity=candidate.api_record_identity, actor="Synthetic reviewer",
            rationale="Ohne persistierten API-Beleg wird keine Zuordnung gespeichert.",
            confirm_match=True,
        ))
    assert not store.list_review_decisions()


def test_concurrent_decision_submits_create_only_one_match(tmp_path, monkeypatch):
    store, _connections, (target,) = environment(tmp_path, monkeypatch)
    record = api_record(target)
    job = save_job(store, target, record, status="succeeded")
    api_batches = import_records(store, target, [record], job["id"])
    PipelineService(store).rebuild_after_import(api_batches[0].batch_id)
    service = BinanceSpotHistoryMatchService(store)
    content = csv_text()
    preview = service.preview(target.source_ref, job["id"], BinanceSpotMatchPreviewRequest(
        filename="synthetic_utc.csv", content=content,
    ))
    candidate = preview.candidates[0]
    request = BinanceSpotMatchDecisionCreate(
        filename="synthetic_utc.csv", content=content,
        preview_sha256=preview.preview_sha256, csv_row_number=1,
        api_record_identity=candidate.api_record_identity, actor="Synthetic reviewer",
        rationale="Parallel doppelte Freigabe wird serialisiert und nur einmal gespeichert.",
        confirm_match=True,
    )

    def decide_once():
        try:
            return service.decide(target.source_ref, job["id"], request)
        except HistoryFetchError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: decide_once(), range(2)))
    assert sum(not isinstance(item, str) for item in results) == 1
    assert "history_match_already_decided" in results
    assert len([item for item in store.list_review_decisions() if item.decision_type == "binance_spot_csv_api_match"]) == 1


def test_unreviewed_csv_overlap_with_incomplete_financial_shape_is_blocked(tmp_path, monkeypatch):
    store, _connections, (target,) = environment(tmp_path, monkeypatch)
    record = api_record(target)
    job = save_job(store, target, record, status="succeeded")
    api_batches = import_records(store, target, [record], job["id"])
    PipelineService(store).rebuild_after_import(api_batches[0].batch_id)
    content = (
        "Trade ID,Symbol,UTC Time,Coin,Change,Operation,fee_asset,fee_quantity\n"
        "42,BTCUSDT,2025-01-01T12:00:00Z,BTC,0.1,buy,BNB,0.001\n"
    )

    with pytest.raises(ValueError, match="fehlender Gegenmenge"):
        BinanceSpotHistoryMatchService(store).import_csv_if_needed(ImportAssistantRequest(
            source="binance", filename="incomplete.csv", content=content,
            connection_id=target.connection_id,
        ))
    assert len(store.list_canonical_events()) == 1


def test_low_level_binance_csv_import_blocks_after_spot_api_history(tmp_path, monkeypatch):
    store, _connections, (target,) = environment(tmp_path, monkeypatch)
    record = api_record(target)
    job = save_job(store, target, record, status="succeeded")
    api_batches = import_records(store, target, [record], job["id"])
    PipelineService(store).rebuild_after_import(api_batches[0].batch_id)

    with pytest.raises(ValueError, match="binance_spot_history_requires_guided_import"):
        CsvRawImporter(store).import_text(
            source="binance", filename="another-export.csv", content=csv_text(trade_id="43"),
            connection_id=target.connection_id,
        )
    assert len(store.list_canonical_events()) == 1


def test_api_csv_endpoint_payload_is_supported_base64_without_changing_file_hash(tmp_path, monkeypatch):
    store, _connections, (target,) = environment(tmp_path, monkeypatch)
    job = save_job(store, target, api_record(target), status="succeeded")
    content = csv_text()
    encoded = base64.b64encode(content.encode()).decode()
    service = BinanceSpotHistoryMatchService(store)
    preview = service.preview(target.source_ref, job["id"], BinanceSpotMatchPreviewRequest(
        filename="synthetic_utc.csv", content_base64=encoded,
    ))
    assert preview.file_sha256 == CsvRawImporter(store).hash_text(content)

