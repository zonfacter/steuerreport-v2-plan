"""Unabhaengige Offline-Counterprobes zu Issue #4, ausschliesslich Testdaten.

Reviewbasis: 6228467ce0a1746a4d7e7abe42306bb68f170118 gegen v0.2.0rc35.
Quellen: src/steuerreport_v2/importers/mexc_native.py, domain/review.py,
db/duckdb_store.py, contracts/mexc_import.py und api/app.py.
Originalrepros/SHA-Nachweise: /tmp/steuerreport-mexc-review-handoff-20261028.md.
SHA256 der Reviewbasis, nicht als Hash des spaeteren Backends ausgeben:
mexc_native.py: 14eaaa7a2250349a5ad637aa5d0c56365684f6b1dcc1f143fdee5255fb465314
domain/review.py: 6540cbf55be4787944e421f85ccc3647cbdc4326af224b703ad31017505ee222
db/duckdb_store.py: 65d1e030f0cde3d0a5ef4cb050ad3905eb83a857ea319d33679a50e75521f7d1

Entscheidungstokens sind ausschliesslich Serverausgaben. Kein Nachbau des
produktiven Hashalgorithmus; negative Stale-Tests behalten ihren alten Token.
Der importierte case-Harness sperrt fremde DBs, IP-Netzwerk und DNS.
"""

from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re

from fastapi.testclient import TestClient
import pytest

from test_mexc_native_reference import (
    LEDGER_ACCOUNT,
    _funding,
    _import,
    _options,
    _positions,
    _preview,
    _raw,
    _request,
    _snapshot_row,
    _spot,
    _state,
    _xlsx,
    case as case,
)
from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.ai_changes import (
    AiChangeApply,
    AiChangeDraft,
    AiChangePreview,
    AiDataQuery,
)
from steuerreport_v2.domain.ai_changes import AiChangeService
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


def _row_preview(preview, number=2):
    row = next(row for row in preview.mexc.rows if row.row_number == number)
    value = row.model_dump(mode="json")
    assert re.fullmatch(r"[0-9a-f]{64}", value.get("input_digest", "")), value
    assert isinstance(value.get("decision_stale"), bool), value
    return value


def _decision(action, target=None, reason="Synthetische Originalbelege einzeln geprueft."):
    decision = {"action": action, "reason": reason}
    if target is not None:
        decision["target_raw_object_id"] = target
    return decision


def _bound_decision(preview, action, target=None, *, number=2, reason=None):
    """Nur explizit aufgerufen; insbesondere kein Refresh in Importhelfern."""
    row = _row_preview(preview, number)
    assert row["decision_stale"] is False
    decision = _decision(action, target)
    if reason is not None:
        decision["reason"] = reason
    return {**decision, "input_digest": row["input_digest"]}


def _with_decision(options, decision, number=2):
    return {**deepcopy(options), "decisions": {str(number): deepcopy(decision)}}


def _reject_without_writes(case, content, options):
    before = _state(case)
    originals = _archive_state(case)
    with pytest.raises(ValueError):
        case[1].import_base64(**_request(content, options))
    assert _state(case) == before
    assert _archive_state(case) == originals


def _archive_state(case):
    archive = case[0].path.parent / "mexc_originals"
    if not archive.exists():
        return None
    assert not archive.is_symlink()
    return sorted((path.name, path.is_symlink(),
                   hashlib.sha256(path.read_bytes()).hexdigest()
                   if path.is_file() and not path.is_symlink() else None)
                  for path in archive.iterdir())


def _mexc_blocker(gate, *fragments):
    issues = [issue for issue in gate.issues if issue.blocks_export
              and issue.code.startswith("mexc_")
              and any(fragment in issue.code for fragment in fragments)]
    assert not gate.allow_export and issues, gate.model_dump(mode="json")
    return issues


def _identified_file(identifier="TX-123", revision="first", **changes):
    row = _spot(**{"Transaction ID": identifier, **changes})
    return _xlsx([row], revision=revision, extra_headers=("Transaction ID",))


def _archive_file(case, content):
    return case[0].path.parent / "mexc_originals" / (
        hashlib.sha256(content).hexdigest() + ".original"
    )


def _damage_archive(case, content, tmp_path, mode):
    original = _archive_file(case, content)
    assert original.is_file() and not original.is_symlink()
    assert original.read_bytes() == content
    if mode == "tampered":
        original.write_bytes(b"SYNTHETIC TAMPERING")
    else:
        original.unlink()
        if mode == "symlink":
            target = tmp_path / "synthetic-symlink-target"
            target.write_bytes(content)
            original.symlink_to(target)


def _approved_root_correction(case, patch):
    service = AiChangeService(case[0])
    rows = service.context(AiDataQuery(kind="event", year=2031)).rows
    assert len(rows) == 1
    row = rows[0]
    draft = AiChangeDraft(
        summary="Synthetischer unabhaengiger Root-Korrekturtest",
        changes=[{
            "kind": "event", "target_id": row.target_id,
            "before_sha256": row.revision, "patch": patch,
            "reason": "Synthetischer Review der Originalquelle und Menge.",
            "evidence_ref": "synthetic:review-receipt",
        }],
    )
    proposal = service.create(draft)
    preview = service.preview(proposal.change_set_id, AiChangePreview(selected_indices=[0]))
    result = service.apply(proposal.change_set_id, AiChangeApply(
        preview_sha256=preview.preview["preview_sha256"], actor="Synthetic Reviewer",
        rationale="Synthetische Root-Korrektur separat und ausdruecklich bestaetigt.",
        confirm=True, evidence_checked=True,
    ))
    assert result.status == "applied"
    return result


def _linked_evidence(case, *, asset="DEMOCOIN"):
    batch, events = _import(case, _xlsx([_spot(Crypto=asset)]), _options())
    root = _raw(case, batch)[0]
    content = _xlsx([_funding(Crypto=asset)], "funding_other")
    options = _options("funding_other")
    preview = _preview(case, content, options)
    decision = _bound_decision(preview, "link_existing", root.raw_object_id)
    linked, linked_events = _import(case, content, _with_decision(options, decision))
    assert linked_events == [] and len(_raw(case, linked)) == 1
    assert len(case[0].list_canonical_events()) == 1
    return batch, root, events, linked


def test_same_provider_id_separate_must_not_double_book(case):
    _import(case, _identified_file(), _options())
    content = _identified_file(revision="second")
    preview = _preview(case, content, _options())
    decision = _bound_decision(preview, "separate")
    options = _with_decision(_options(), decision)
    assert not _preview(case, content, options).can_import
    _reject_without_writes(case, content, options)
    assert len(case[0].list_canonical_events()) == 1
    assert _positions(case) == {(LEDGER_ACCOUNT, "DEMOCOIN"): Decimal("2.5")}


def test_distinct_provider_ids_remain_two_legitimate_bookings(case):
    _import(case, _identified_file("TX-A"), _options())
    content = _identified_file("TX-B")
    assert _preview(case, content, _options()).can_import
    _import(case, content, _options())
    assert len(case[0].list_canonical_events()) == 2
    assert _positions(case) == {(LEDGER_ACCOUNT, "DEMOCOIN"): Decimal("5")}


def test_provider_id_on_linked_evidence_must_detect_conflict(case):
    batch, _ = _import(case, _xlsx([_spot()]), _options())
    root = _raw(case, batch)[0]
    content = _identified_file()
    preview = _preview(case, content, _options())
    decision = _bound_decision(preview, "link_existing", root.raw_object_id)
    linked, events = _import(case, content, _with_decision(_options(), decision))
    assert events == []
    metadata = json.loads(json.loads(_raw(case, linked)[0].payload_json)["_mexc"])
    assert metadata["provider_id"] == "TX-123" and metadata["role"] == "linked"
    conflicting = _identified_file(revision="changed-amount", Quantity="9")
    assert not _preview(case, conflicting, _options()).can_import
    _reject_without_writes(case, conflicting, _options())
    assert _positions(case) == {(LEDGER_ACCOUNT, "DEMOCOIN"): Decimal("2.5")}


def test_valid_separate_decision_uses_preview_token_without_false_positive(case):
    _import(case, _xlsx([_spot()]), _options())
    content = _xlsx([_spot()], revision="separate-original")
    initial = _preview(case, content, _options())
    decision = _bound_decision(initial, "separate")
    options = _with_decision(_options(), decision)
    current = _preview(case, content, options)
    assert current.can_import and _row_preview(current)["decision_stale"] is False
    _import(case, content, options)
    assert _positions(case) == {(LEDGER_ACCOUNT, "DEMOCOIN"): Decimal("5")}


def test_decision_token_binds_physical_row_even_for_identical_rows(case):
    _import(case, _xlsx([_spot()]), _options())
    content = _xlsx([_spot(), _spot()], revision="two-physical-rows")
    initial = _preview(case, content, _options())
    first = _bound_decision(initial, "separate", number=2)
    second = _bound_decision(initial, "separate", number=3)
    assert first["input_digest"] != second["input_digest"]
    options = {**_options(), "decisions": {"2": deepcopy(first), "3": deepcopy(first)}}
    stale = _preview(case, content, options)
    assert _row_preview(stale, 2)["decision_stale"] is False
    assert _row_preview(stale, 3)["decision_stale"] is True
    assert not stale.can_import
    _reject_without_writes(case, content, options)


@pytest.mark.parametrize("change", ["file-bytes", "row-content", "account", "export-kind"])
def test_separate_decision_must_bind_reviewed_file_context_and_row(case, change):
    _import(case, _xlsx([_spot(Crypto="COINA"), _spot(Crypto="COINB")]), _options())
    reviewed = _xlsx([_spot(Crypto="COINA")], revision="reviewed")
    initial = _preview(case, reviewed, _options())
    old_decision = _bound_decision(initial, "separate", reason="Nur COINA als eigenstaendig geprueft.")
    saved = deepcopy(old_decision)
    options = _with_decision(_options(), old_decision)
    assert _preview(case, reviewed, options).can_import
    replacement = reviewed
    if change == "file-bytes":
        replacement = _xlsx([_spot(Crypto="COINA")], revision="replacement")
    elif change == "row-content":
        replacement = _xlsx([_spot(Crypto="COINB")], revision="replacement")
    elif change == "account":
        options["account"] = "synthetic-other-account"
    else:
        options["export_kind"] = "futures_statement"
    before = _state(case)
    stale = _preview(case, replacement, options)
    assert not stale.can_import
    assert old_decision == saved and options["decisions"]["2"] == saved
    _reject_without_writes(case, replacement, options)
    assert _state(case) == before
    assert _row_preview(stale)["input_digest"] != old_decision["input_digest"]
    assert _row_preview(stale)["decision_stale"] is True


@pytest.mark.parametrize("change", ["candidate-added", "canonical-quantity"])
def test_decision_token_must_bind_candidate_facts_without_autorefresh(case, change):
    _import(case, _xlsx([_spot(Crypto="EUR")]), _options())
    pending = _xlsx([_spot(Crypto="EUR")], revision="pending")
    initial = _preview(case, pending, _options())
    old_decision = _bound_decision(initial, "separate")
    saved = deepcopy(old_decision)
    if change == "candidate-added":
        extra = _xlsx([_spot(Crypto="EUR")], revision="another-root")
        extra_preview = _preview(case, extra, _options())
        extra_decision = _bound_decision(extra_preview, "separate")
        _import(case, extra, _with_decision(_options(), extra_decision))
    else:
        _approved_root_correction(case, {"event_type": "transfer", "quantity": "9"})
    options = _with_decision(_options(), old_decision)
    stale = _preview(case, pending, options)
    assert _row_preview(stale)["input_digest"] != saved["input_digest"]
    assert _row_preview(stale)["decision_stale"] is True
    assert not stale.can_import and old_decision == saved
    _reject_without_writes(case, pending, options)


def test_decision_without_input_digest_cannot_authorize_import(case):
    _import(case, _xlsx([_spot()]), _options())
    content = _xlsx([_spot()], revision="no-token")
    options = _with_decision(_options(), _decision("separate"))
    _reject_without_writes(case, content, options)


def test_event_identity_stays_stable_across_recalculation(case):
    batch, events = _import(case, _xlsx([_spot()]), _options())
    again = RawNormalizer(case[0]).normalize_batch(batch.batch_id)
    assert [event.event_id for event in events] == [event.event_id for event in again]


@pytest.mark.parametrize("mode", ["dict", "bad-json"])
def test_bad_metadata_never_falls_back_to_generic(case, mode):
    batch, _ = _import(case, _xlsx([_spot()]), _options())
    raw = _raw(case, batch)[0]
    payload = json.loads(raw.payload_json)
    payload["_mexc"] = json.loads(payload["_mexc"]) if mode == "dict" else "broken"
    with case[0].connect() as con:
        con.execute("update raw_objects set payload_json=? where raw_object_id=?",
                    [json.dumps(payload), raw.raw_object_id])
    assert RawNormalizer(case[0]).normalize_batch(batch.batch_id) == []
    gate = ReviewService(case[0]).gate()
    assert not gate.allow_export
    assert any(issue.code == "unmapped_raw_objects" for issue in gate.issues)


@pytest.mark.parametrize("mode", ["missing", "tampered", "symlink"])
def test_original_download_rejects_damaged_archive(case, tmp_path, mode):
    content = _xlsx([_spot()])
    batch, _ = _import(case, content, _options())
    _damage_archive(case, content, tmp_path, mode)
    with TestClient(create_app(case[0])) as client:
        response = client.get(f"/api/v1/import/batches/{batch.batch_id}/original")
        assert response.status_code == 409


def test_snapshot_only_full_pipeline_must_expose_dedicated_reconciliation_blocker(case):
    row = _snapshot_row()
    assert row["Total"] == "2.5"
    batch, events = _import(case, _xlsx([row], "asset_snapshot"), _options("asset_snapshot"))
    result = PipelineService(case[0]).rebuild_all()
    gate = ReviewService(case[0]).gate()
    assert events == [] and case[0].list_canonical_events() == []
    assert _positions(case) == {} and len(_raw(case, batch)) == 1
    assert case[0].unmapped_raw_object_counts() == {}
    with case[0].connect() as con:
        assert con.execute("select count(*) from tax_lots").fetchone()[0] == 0
    _mexc_blocker(gate, "snapshot")
    assert result.allow_export is False


@pytest.mark.parametrize("mode", ["missing", "tampered", "symlink"])
def test_snapshot_missing_original_requires_integrity_not_only_snapshot_blocker(case, tmp_path, mode):
    content = _xlsx([_snapshot_row()], "asset_snapshot")
    _import(case, content, _options("asset_snapshot"))
    baseline = ReviewService(case[0]).gate()
    _mexc_blocker(baseline, "snapshot")
    assert not any("integrity" in issue.code for issue in baseline.issues)
    _damage_archive(case, content, tmp_path, mode)
    PipelineService(case[0]).rebuild_all()
    _mexc_blocker(ReviewService(case[0]).gate(), "integrity")


@pytest.mark.parametrize("shape", ["string", "object"])
def test_forged_snapshot_role_must_not_hide_unmapped_row(case, shape):
    batch, _ = _import(case, _xlsx([_spot()]), _options())
    raw = _raw(case, batch)[0]
    payload = json.loads(raw.payload_json)
    metadata = json.loads(payload["_mexc"])
    metadata["role"] = "snapshot"
    payload["_mexc"] = json.dumps(metadata) if shape == "string" else metadata
    with case[0].connect() as con:
        con.execute("update raw_objects set payload_json=? where raw_object_id=?",
                    [json.dumps(payload), raw.raw_object_id])
    assert RawNormalizer(case[0]).normalize_batch(batch.batch_id) == []
    BalanceLedgerBuilder(case[0]).rebuild()
    assert _positions(case) == {}
    _mexc_blocker(ReviewService(case[0]).gate(), "mexc_native_binding_invalid")


def test_corrected_type_only_same_values_is_not_a_link_conflict(case):
    batch, root, original_events, linked = _linked_evidence(case, asset="EUR")
    _approved_root_correction(case, {"event_type": "transfer"})
    result = PipelineService(case[0]).rebuild_all()
    again = case[0].list_canonical_events()
    assert len(again) == 1 and again[0].event_id == original_events[0].event_id
    assert again[0].event_type == "transfer" and again[0].quantity == Decimal("2.5")
    assert again[0].raw_object_id == root.raw_object_id
    assert len(_raw(case, batch)) == len(_raw(case, linked)) == 1
    gate = ReviewService(case[0]).gate()
    assert result.allow_export and gate.allow_export, gate.model_dump(mode="json")


def test_existing_link_must_be_rechecked_after_root_quantity_correction(case):
    _linked_evidence(case, asset="EUR")
    _approved_root_correction(case, {"event_type": "transfer", "quantity": "9"})
    result = PipelineService(case[0]).rebuild_all()
    events = case[0].list_canonical_events()
    assert len(events) == 1 and events[0].quantity == Decimal("9")
    issues = _mexc_blocker(ReviewService(case[0]).gate(), "link")
    assert any(issue.code == "mexc_link_target_conflict" for issue in issues)
    assert result.allow_export is False


def test_new_link_after_quantity_correction_requires_current_reconciliation(case):
    batch, _ = _import(case, _xlsx([_spot(Crypto="EUR")]), _options())
    root = _raw(case, batch)[0]
    _approved_root_correction(case, {"event_type": "transfer", "quantity": "9"})
    content = _xlsx([_funding(Crypto="EUR")], "funding_other")
    options = _options("funding_other")
    initial = _preview(case, content, options)
    decision = _bound_decision(initial, "link_existing", root.raw_object_id)
    linked, events = _import(case, content, _with_decision(options, decision))
    assert events == [] and len(_raw(case, linked)) == 1
    result = PipelineService(case[0]).rebuild_all()
    effective = case[0].list_canonical_events()
    assert len(effective) == 1 and effective[0].quantity == Decimal("9")
    _mexc_blocker(ReviewService(case[0]).gate(), "mexc_link_target_conflict")
    assert result.allow_export is False


@pytest.mark.parametrize("mode", ["missing", "tampered", "symlink"])
def test_classified_root_lost_original_must_block_export(case, tmp_path, mode):
    content = _xlsx([_spot(Crypto="EUR")])
    batch, _ = _import(case, content, _options())
    _approved_root_correction(case, {"event_type": "transfer"})
    healthy = ReviewService(case[0]).gate()
    assert healthy.allow_export, healthy.model_dump(mode="json")
    _damage_archive(case, content, tmp_path, mode)
    result = PipelineService(case[0]).rebuild_all()
    _mexc_blocker(ReviewService(case[0]).gate(), "integrity")
    assert result.allow_export is False
    with TestClient(create_app(case[0])) as client:
        assert client.get(f"/api/v1/import/batches/{batch.batch_id}/original").status_code == 409


@pytest.mark.parametrize("scenario", ["same-id-separate", "linked-id-conflict", "stale-separate"])
def test_api_does_not_accept_unbound_or_conflicting_identity(case, scenario):
    with TestClient(create_app(case[0])) as client:
        def request(content, options):
            return {**_request(content, options), "import_mode": "file"}

        def preview(content, options):
            response = client.post("/api/v1/import/assistant/preview", json=request(content, options))
            assert response.status_code == 200
            body = response.json()
            assert body["status"] in {"ok", "warning"} and isinstance(body["data"], dict), body
            return body["data"]

        def token(content, options):
            row = preview(content, options)["preview"]["mexc"]["rows"][0]
            assert re.fullmatch(r"[0-9a-f]{64}", row["input_digest"])
            assert row["decision_stale"] is False
            return row["input_digest"]

        def execute(content, options):
            response = client.post("/api/v1/import/assistant/execute", json=request(content, options))
            assert response.status_code == 200
            return response.json()

        if scenario == "same-id-separate":
            assert execute(_identified_file(), _options())["status"] == "ok"
            content = _identified_file(revision="different-export")
            decision = {**_decision("separate"), "input_digest": token(content, _options())}
            options = _with_decision(_options(), decision)
        elif scenario == "linked-id-conflict":
            first = execute(_xlsx([_spot()]), _options())
            assert first["status"] == "ok"
            root = case[0].list_raw_objects(first["data"]["batch"]["batch_id"])[0]
            evidence = _identified_file()
            decision = {**_decision("link_existing", root.raw_object_id),
                        "input_digest": token(evidence, _options())}
            assert execute(evidence, _with_decision(_options(), decision))["status"] == "ok"
            content = _identified_file(revision="conflict", Quantity="9")
            options = _options()
        else:
            roots = _xlsx([_spot(Crypto="COINA"), _spot(Crypto="COINB")])
            assert execute(roots, _options())["status"] == "ok"
            reviewed = _xlsx([_spot(Crypto="COINA")], revision="reviewed")
            old_token = token(reviewed, _options())
            decision = {**_decision("separate", reason="Nur COINA als eigenstaendig geprueft."),
                        "input_digest": old_token}
            options = _with_decision(_options(), decision)
            assert preview(reviewed, options)["can_execute"]
            content = _xlsx([_spot(Crypto="COINB")], revision="replacement")
            stale = preview(content, options)
            assert not stale["can_execute"]
            assert stale["preview"]["mexc"]["rows"][0]["decision_stale"] is True
            assert options["decisions"]["2"]["input_digest"] == old_token
        before = _state(case)
        originals = _archive_state(case)
        assert execute(content, options)["status"] == "error"
        assert _state(case) == before
        assert _archive_state(case) == originals


def test_fixture_helpers_are_from_same_acceptance_directory():
    """Kein versehentlicher Import einer zweiten Acceptance-Datei aus /tmp."""
    import test_mexc_native_reference
    assert Path(test_mexc_native_reference.__file__).parent == Path(__file__).parent


@pytest.mark.parametrize("shape", ["string", "object"])
def test_existing_index_rejects_invalid_metadata_instead_of_trusting_native_label(case, shape):
    batch, _ = _import(case, _xlsx([_spot()]), _options())
    raw = _raw(case, batch)[0]
    payload = json.loads(raw.payload_json)
    metadata = json.loads(payload["_mexc"])
    metadata["role"] = "snapshot"
    payload["_mexc"] = json.dumps(metadata) if shape == "string" else metadata
    with case[0].connect() as con:
        con.execute("update raw_objects set payload_json=? where raw_object_id=?",
                    [json.dumps(payload), raw.raw_object_id])
    unrelated = _xlsx([_spot(Crypto="UNRELATED")], revision="invalid-existing-binding")
    before = _state(case)
    preview = _preview(case, unrelated, _options())
    assert preview.can_import is False
    assert ("Vorhandene MEXC-Altbelege haben keine native Konto-/Exportartbindung; "
            "zuerst gesondert pruefen.") in preview.mexc.blocking_reasons
    _reject_without_writes(case, unrelated, _options())
    assert _state(case) == before
    _mexc_blocker(ReviewService(case[0]).gate(), "mexc_native_binding_invalid")


@pytest.mark.parametrize("field", ["decision_evidence", "decision_input_digest"])
def test_saved_decision_evidence_and_digest_must_survive_rebuild_consistently(case, field):
    _import(case, _xlsx([_spot()]), _options())
    content = _xlsx([_spot()], revision="decision-metadata-tampering")
    initial = _preview(case, content, _options())
    decision = _bound_decision(initial, "separate")
    batch, events = _import(case, content, _with_decision(_options(), decision))
    assert len(events) == 1
    raw = _raw(case, batch)[0]
    payload = json.loads(raw.payload_json)
    metadata = json.loads(payload["_mexc"])
    assert metadata["decision_input_digest"] == decision["input_digest"]
    assert isinstance(metadata["decision_evidence"], list) and metadata["decision_evidence"]
    PipelineService(case[0]).rebuild_all()
    assert len(case[0].list_canonical_events()) == 2
    assert not any(issue.code == "mexc_native_binding_invalid"
                   for issue in ReviewService(case[0]).gate().issues)
    if field == "decision_input_digest":
        token = metadata[field]
        metadata[field] = ("0" if token[0] != "0" else "1") + token[1:]
    else:
        metadata[field] = []
    payload["_mexc"] = json.dumps(metadata)
    with case[0].connect() as con:
        con.execute("update raw_objects set payload_json=? where raw_object_id=?",
                    [json.dumps(payload), raw.raw_object_id])
    PipelineService(case[0]).rebuild_all()
    _mexc_blocker(ReviewService(case[0]).gate(), "mexc_native_binding_invalid")


@pytest.mark.parametrize("change", ["same-inode", "replace-inode"])
def test_warmed_original_hash_cache_detects_same_size_and_restored_mtime_tampering(case, tmp_path, change):
    content = _xlsx([_spot(Crypto="EUR")])
    _import(case, content, _options())
    _approved_root_correction(case, {"event_type": "transfer"})
    assert ReviewService(case[0]).gate().allow_export
    original = _archive_file(case, content)
    before = original.stat()
    corrupted = content[:-1] + bytes([content[-1] ^ 1])
    if change == "same-inode":
        original.write_bytes(corrupted)
        os.utime(original, ns=(before.st_atime_ns, before.st_mtime_ns))
    else:
        replacement = tmp_path / "synthetic-replacement"
        replacement.write_bytes(corrupted)
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        replacement.replace(original)
    after = original.stat()
    assert after.st_size == before.st_size and after.st_mtime_ns == before.st_mtime_ns
    if change == "same-inode":
        assert after.st_ino == before.st_ino and after.st_ctime_ns != before.st_ctime_ns
    else:
        assert after.st_ino != before.st_ino
    _mexc_blocker(ReviewService(case[0]).gate(), "mexc_original_integrity_failed")
