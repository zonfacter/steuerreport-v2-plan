from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json

from fastapi.testclient import TestClient
import pytest

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.ai import AiProviderWrite
from steuerreport_v2.contracts.ai_changes import (
    AiChangeApply, AiChangeDraft, AiChangeGenerate, AiChangePreview, AiDataQuery,
)
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.db.ai_corrections import CorrectionConflict, digest
from steuerreport_v2.domain.ai_changes import AiChangeError, AiChangeService
from steuerreport_v2.domain.ai_provider import AiProviderService
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer


@pytest.fixture
def setup(tmp_path):
    store = DuckDbStore(tmp_path / "changes.duckdb")
    for day, amount, quote in ((1, "1", "100"), (2, "-1", "150")):
        store.add_canonical_event(CanonicalEventCreate(
            source="fixture", event_time=datetime(2025, 1, day, tzinfo=timezone.utc),
            event_type="trade", asset="BTC", quantity=Decimal(amount), quote_asset="EUR",
            quote_quantity=Decimal(quote), account="fixture-account",
        ))
    PipelineService(store).rebuild_ledgers()
    return store, AiChangeService(store)


def make_draft(service, *, patch=None, kind="event"):
    context = service.context(AiDataQuery(kind=kind))
    row = context.rows[-1]
    return AiChangeDraft(summary="Beleggestuetzte Korrektur der Fixture-Zeile", changes=[{
        "kind": kind, "target_id": row.target_id, "before_sha256": row.revision,
        "patch": patch or {"quote_quantity": "160"},
        "reason": "Der gepruefte Originalbeleg weist diesen Wert aus.", "evidence_ref": "fixture:receipt-002",
    }])


def prepare(service, draft=None):
    item = service.create(draft or make_draft(service))
    return service.preview(item.change_set_id, AiChangePreview(selected_indices=[0]))


def approval(item):
    return AiChangeApply(preview_sha256=item.preview["preview_sha256"], actor="Fixture Reviewer",
                         rationale="Originalbeleg und berechnete Auswirkungen selbst geprueft.",
                         confirm=True, evidence_checked=True)


def tax_gain(store):
    with store.connect() as con:
        return con.execute("select sum(gain_loss_eur) from tax_lines").fetchone()[0]


def test_preview_isolated_apply_updates_database_and_ledgers_atomically(setup):
    store, service = setup
    before_bytes = hashlib.sha256(store.path.read_bytes()).hexdigest()
    item = prepare(service)
    assert item.status == "previewed"
    assert item.preview["before_summary"]["tax"]["2025"]["gain_loss_eur"] == "50.000000000000000000"
    assert item.preview["after_summary"]["tax"]["2025"]["gain_loss_eur"] == "60.000000000000000000"
    assert item.preview["tax_line_deltas"]
    assert tax_gain(store) == 50
    applied = service.apply(item.change_set_id, approval(item))
    assert applied.status == "applied" and tax_gain(store) == 60
    assert store.list_canonical_events()[-1].quote_quantity == 160
    assert applied.approval["identity_verified"] is False
    assert applied.approval["audit_sha256"]
    assert hashlib.sha256(store.path.read_bytes()).hexdigest() != before_bytes
    assert service.apply(item.change_set_id, approval(item)) == applied
    assert not list(service._root().glob("*/preview.duckdb"))


def test_reversal_is_new_proposal_and_requires_its_own_preview_and_approval(setup):
    store, service = setup
    original = prepare(service)
    service.apply(original.change_set_id, approval(original))
    reversal = service.revert(original.change_set_id, "Der zusaetzliche Abgleich bestaetigt den alten Belegwert.")
    assert reversal.parent_id == original.change_set_id and reversal.status == "proposed"
    assert tax_gain(store) == 60
    reversal = service.preview(reversal.change_set_id, AiChangePreview(selected_indices=[0]))
    service.apply(reversal.change_set_id, approval(reversal))
    assert tax_gain(store) == 50
    assert service.get(original.change_set_id).status == "applied"
    PipelineService(store).rebuild_all()
    assert tax_gain(store) == 50


@pytest.mark.parametrize("patch", [
    {"source": "override"}, {"event_id": "other"}, {"raw_object_id": None},
    {"quantity": "NaN"}, {"quantity": "Infinity"}, {"quantity": "0.0000000000000000001"},
    {"quantity": "100000000000000000000"}, {"event_type": "execute_sql"},
    {"asset": "BTC'; drop table raw_objects;--"}, {"event_time": "2025-01-04T12:00:00"},
    {"account": "pri\nvate"}, {"quote_asset": None},
])
def test_invalid_or_unapproved_fields_never_change_financial_data(setup, patch):
    store, service = setup
    with pytest.raises(AiChangeError):
        service.create(make_draft(service, patch=patch))
    assert tax_gain(store) == 50
    assert len(store.list_canonical_events()) == 2


def test_whole_database_revision_blocks_changed_price_or_method(setup):
    store, service = setup
    item = prepare(service)
    store.add_price_point(PricePointCreate(asset="ETH", price_eur=Decimal("1000"),
                                        priced_at=datetime(2025, 1, 1), source="fixture"))
    with pytest.raises(AiChangeError, match="ai_change_stale"):
        service.apply(item.change_set_id, approval(item))
    assert tax_gain(store) == 50


def test_prepared_database_tampering_is_rejected(setup):
    store, service = setup
    item = prepare(service)
    path = next(service._root().glob("*/preview.duckdb"))
    with path.open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(AiChangeError, match="ai_change_prepared_mismatch"):
        service.apply(item.change_set_id, approval(item))
    assert tax_gain(store) == 50


def test_apply_failure_rolls_back_all_tables_and_proposal_state(setup, monkeypatch):
    store, service = setup
    item = prepare(service)
    monkeypatch.setattr("steuerreport_v2.domain.ai_changes.DERIVED_TABLES", ("price_ledger", "no_such_fixture_table"))
    with pytest.raises(Exception):
        service.apply(item.change_set_id, approval(item))
    assert tax_gain(store) == 50
    assert store.list_canonical_events()[-1].quote_quantity == 150
    assert service.get(item.change_set_id).status == "previewed"
    with store.connect() as con:
        assert con.execute("select count(*) from ai_correction_overrides").fetchone()[0] == 0


def test_simultaneous_apply_is_idempotent(setup):
    store, service = setup
    item = prepare(service)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.apply(item.change_set_id, approval(item)), range(2)))
    assert results[0] == results[1]
    assert tax_gain(store) == 60


def test_context_is_filtered_and_contains_hashes_not_raw_payload_or_settings(setup):
    store, service = setup
    batch = CsvRawImporter(store).import_text(source="manual-csv", filename="fixture-evidence.csv",
        content="time,asset,amount,type,account\n2025-03-02T10:00:00Z,ETH,1,reward,fixture-wallet\n")
    RawNormalizer(store).normalize_batch(batch.batch_id)
    context = service.context(AiDataQuery(asset="ETH"))
    assert context.total == 1 and len(context.rows) == 1
    row = context.rows[0]
    assert row.provenance["filename"] == "fixture-evidence.csv"
    assert row.provenance["file_sha256"] == batch.file_hash
    assert row.provenance["raw_payload_sha256"]
    assert "payload_json" not in context.model_dump_json()
    assert "admin_settings" not in context.model_dump_json()


def test_reimport_preserves_approved_event_correction_and_raw_objects(setup):
    store, service = setup
    batch = CsvRawImporter(store).import_text(source="manual-csv", filename="fixture-evidence.csv",
        content="time,asset,amount,type,account\n2025-03-02T10:00:00Z,ETH,1,reward,fixture-wallet\n")
    RawNormalizer(store).normalize_batch(batch.batch_id)
    raw_before = [item.model_dump_json() for item in store.list_raw_objects(batch.batch_id)]
    row = service.context(AiDataQuery(asset="ETH")).rows[0]
    draft = AiChangeDraft(summary="Korrigierte Quellenklassifikation", changes=[{
        "kind": "event", "target_id": row.target_id, "before_sha256": row.revision,
        "patch": {"event_type": "mining"}, "reason": "Dokumentierter Mining-Zufluss statt allgemeinem Reward.", "evidence_ref": "fixture:receipt",
    }])
    item = prepare(service, draft)
    service.apply(item.change_set_id, approval(item))
    PipelineService(store).rebuild_all()
    assert next(event for event in store.list_canonical_events() if event.event_id == row.target_id).event_type == "mining"
    assert [item.model_dump_json() for item in store.list_raw_objects(batch.batch_id)] == raw_before


def test_existing_non_derived_price_can_be_updated(setup):
    store, service = setup
    point = store.add_price_point(PricePointCreate(asset="ETH", price_eur=Decimal("1000"),
        priced_at=datetime(2025, 1, 1), source="fixture-evidence"))
    item = prepare(service, make_draft(service, kind="price", patch={"price_eur": "1100"}))
    service.apply(item.change_set_id, approval(item))
    with store.connect() as con:
        assert con.execute("select price_eur from price_ledger where price_id=?", [point.price_id]).fetchone()[0] == 1100


def test_model_sends_only_selected_rows_and_does_not_apply(setup, monkeypatch):
    store, service = setup
    provider = AiProviderService(store)
    provider.save(AiProviderWrite(revision=provider.status().revision, base_url="http://127.0.0.1:18901/v1", model="fixture-model"))
    context = service.context(AiDataQuery())
    draft = make_draft(service)
    selected = context.rows[-1]
    calls = []

    def complete(_self, prompt, **kwargs):
        calls.append(json.loads(prompt))
        assert len(calls[-1]["rows"]) == 1 and calls[-1]["rows"][0]["target_id"] == selected.target_id
        assert context.rows[0].target_id not in prompt
        assert "system_prompt" in kwargs
        return {"answer": draft.model_dump_json(), "truncated": False, "resolved_model": "fixture-model"}

    monkeypatch.setattr(AiProviderService, "complete", complete)
    item = service.generate(AiChangeGenerate(query=AiDataQuery(), selected_ids=[selected.target_id],
        context_sha256=context.context_sha256, instruction="Korrigiere den Erloes entsprechend meinem geprueften Beleg auf 160 EUR.",
        provider_revision=provider.status().revision))
    assert len(calls) == 1 and item.origin == "model" and item.status == "proposed"
    assert tax_gain(store) == 50


def test_api_requires_explicit_confirmation_and_keeps_errors_private(setup):
    store, service = setup
    item = prepare(service)
    client = TestClient(create_app(store))
    path = "/api/v1/ai/changes/" + item.change_set_id
    response = client.post(path + "/apply", json={**approval(item).model_dump(), "confirm": False})
    assert response.status_code == 422 and response.json() == {"detail": "ai_request_invalid"}
    assert tax_gain(store) == 50
    response = client.post(path + "/apply", json=approval(item).model_dump())
    assert response.status_code == 200
    audit = client.get(path + "/audit.json")
    assert audit.status_code == 200 and audit.json()["approval"]["audit_sha256"]
    assert "preview_directory" not in audit.text
    assert client.get("/api/v1/ai/changes/missing").status_code == 404


def test_generate_replay_does_not_send_a_second_model_request(setup, monkeypatch):
    store, service = setup
    provider = AiProviderService(store)
    draft = make_draft(service)
    called = []

    def generate(_request):
        called.append(True)
        return service.create(draft)

    monkeypatch.setattr(service, "_generate", generate)
    context = service.context(AiDataQuery())
    request = AiChangeGenerate(query=AiDataQuery(), selected_ids=[context.rows[-1].target_id],
        context_sha256=context.context_sha256, instruction="Geprueften Fixture-Beleg uebernehmen.", provider_revision=provider.status().revision)
    first = service.generate(request)
    assert service.generate(request) == first and len(called) == 1
    assert tax_gain(store) == 50


def test_selected_subset_only_is_applied_and_human_edits_create_new_revision(setup):
    store, service = setup
    draft = make_draft(service)
    row = service.context(AiDataQuery()).rows[0]
    draft.changes.append(draft.changes[0].model_copy(update={"target_id": row.target_id, "before_sha256": row.revision, "patch": {"account": "fixture-other"}}))
    original = service.create(draft)
    revised = service.revise(original.change_set_id, draft)
    assert revised.parent_id == original.change_set_id and service.get(original.change_set_id).draft == original.draft
    prepared = service.preview(revised.change_set_id, AiChangePreview(selected_indices=[0]))
    service.apply(prepared.change_set_id, approval(prepared))
    assert tax_gain(store) == 60
    assert store.list_canonical_events()[0].account == "fixture-account"


def test_export_gate_blocks_conflicting_approved_correction_and_audit_hash_is_recomputable(setup):
    store, service = setup
    item = prepare(service)
    applied = service.apply(item.change_set_id, approval(item))
    audit = applied.model_dump(mode="json")
    claimed = audit["approval"].pop("audit_sha256")
    assert digest(audit) == claimed
    with store.connect() as con:
        con.execute("update canonical_events set quote_quantity=999 where event_id=?", [item.draft.changes[0].target_id])
    gate = ReviewService(store).gate()
    assert not gate.allow_export and any(issue.code == "ai_correction_replay_conflict" for issue in gate.issues)
    with pytest.raises(AiChangeError, match="ai_change_stale"):
        service.revert(item.change_set_id, "Ruecknahme darf keine spaetere Korrektur ueberschreiben.")


def test_corrected_price_cannot_be_deleted_until_reversed(setup):
    store, service = setup
    point = store.add_price_point(PricePointCreate(asset="ETH", price_eur=Decimal("1000"), priced_at=datetime(2025, 1, 1), source="fixture-evidence"))
    item = prepare(service, make_draft(service, kind="price", patch={"price_eur": "1100"}))
    service.apply(item.change_set_id, approval(item))
    with pytest.raises(CorrectionConflict, match="ai_correction_target_protected"):
        store.delete_price_point(point.price_id)
    with pytest.raises(CorrectionConflict, match="ai_correction_target_protected"):
        store.delete_price_points_by_source("fixture-evidence")
    reversal = service.revert(item.change_set_id, "Belegpruefung erfordert Ruecknahme und neuen Quellimport.")
    reversal = service.preview(reversal.change_set_id, AiChangePreview(selected_indices=[0]))
    service.apply(reversal.change_set_id, approval(reversal))
    assert store.delete_price_point(point.price_id)
    PipelineService(store).rebuild_ledgers()


def test_holding_period_change_is_visible_even_if_total_gain_is_unchanged(setup):
    store, service = setup
    row = service.context(AiDataQuery()).rows[0]
    draft = make_draft(service)
    draft.changes[0].target_id = row.target_id
    draft.changes[0].before_sha256 = row.revision
    draft.changes[0].patch = {"event_time": "2023-01-01T00:00:00Z"}
    item = prepare(service, draft)
    assert item.preview["before_summary"]["tax"] == item.preview["after_summary"]["tax"]
    assert item.preview["tax_line_deltas"]


def test_correction_is_linked_in_review_and_year_audit(setup):
    store, service = setup
    item = prepare(service)
    assert not any(row.decision_type == "approved_data_correction" for row in store.list_review_decisions())
    service.apply(item.change_set_id, approval(item))
    decisions = [row for row in store.list_review_decisions() if row.decision_type == "approved_data_correction"]
    assert len(decisions) == 1
    assert decisions[0].evidence_ref.endswith(item.change_set_id + "/audit.json")
    assert [item.change_set_id for item in service.year_audits(2025)] == [item.change_set_id]
    assert not service.year_audits(2024)
