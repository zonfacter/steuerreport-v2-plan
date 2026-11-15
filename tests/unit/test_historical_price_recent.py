"""Isolierte synthetische Archive und DuckDBs fuer die lesende Recent-Liste."""
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
from uuid import UUID

import duckdb
import pytest
from pydantic import ValidationError

from steuerreport_v2.contracts.historical_prices import HistoricalPricePreviewListItem
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain import historical_prices as module
from steuerreport_v2.domain.historical_prices import HistoricalPriceError, HistoricalPriceService, digest
from steuerreport_v2.importers.source_history_importer import canonical_json


METADATA = (
    "created_at", "prices_count", "applied", "preview_sha256", "pending_count", "open_count",
    "parent_preview_id", "collection_complete", "manual",
)
AT = "2025-06-13T01:00:00+00:00"


@pytest.fixture
def service(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    with store.connect():
        pass

    def forbidden(*args, **kwargs):
        pytest.fail("Recent must not invoke a provider, pipeline or mutation")

    monkeypatch.setattr(module, "managed_client", forbidden)
    monkeypatch.setattr(module.PipelineService, "rebuild_ledgers", forbidden)
    monkeypatch.setattr(module.ConnectionService, "_mutation", forbidden)
    return HistoricalPriceService(store)


def _preview(service, number=1, **changes):
    document = {
        "id": str(UUID(int=number)), "created_at": AT, "prices_count": 0, "status": "no_prices",
        "query": {"scope": "tax_required"}, "evidence": [], "prices": [], "rows": [],
    }
    document.update(changes)
    return _write(service, document, directory_id=str(UUID(int=number)))


def _write(service, document, *, directory_id=None):
    document = {key: value for key, value in document.items() if key != "preview_sha256"}
    document["preview_sha256"] = digest(document)
    directory = service.root / (directory_id or document["id"])
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "preview.json").write_text(canonical_json(document), encoding="utf-8")
    return document


def _placeholder(item, request_id, code=None):
    assert item["id"] == request_id
    assert item["status"] == item["integrity_status"] == "unavailable"
    assert all(item[field] is None for field in METADATA)
    assert item["error_code"] in {
        "historical_price_evidence_changed", "historical_price_apply_decision_invalid",
        "historical_price_preview_unavailable",
    }
    if code is not None:
        assert item["error_code"] == code
    HistoricalPricePreviewListItem.model_validate(item)


def test_deeply_nested_archive_is_a_row_failure_not_a_database_failure(service):
    healthy = _preview(service, 1)
    broken_id = str(UUID(int=2))
    folder = service.root / broken_id
    folder.mkdir()
    (folder / "preview.json").write_text("[" * 3000 + "0" + "]" * 3000)
    rows = service.recent()
    assert len(rows) == 2
    _placeholder(next(row for row in rows if row["id"] == broken_id), broken_id)
    assert next(row for row in rows if row["id"] == healthy["id"])["integrity_status"] == "verified"


def test_fifo_preview_is_rejected_before_document_read(service, monkeypatch):
    request_id = str(UUID(int=3))
    folder = service.root / request_id
    folder.mkdir(parents=True)
    os.mkfifo(folder / "preview.json")
    monkeypatch.setattr(service, "_json", lambda *_: pytest.fail("FIFO must never be opened"))
    row, = service.recent()
    _placeholder(row, request_id)


def _files(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _decision(service, preview, **changes):
    request_id = preview["id"]
    decision_id = "historical-price:" + request_id
    document = {
        "decision_id": decision_id, "decision_type": "historical_price_import",
        "scope": "historical_prices:" + request_id, "title": "Synthetic import decision",
        "actor": "synthetic-reviewer", "rationale": "Synthetic test; no actual approval.",
        "evidence_ref": "api:/api/v1/prices/historical/previews/" + request_id,
        "payload": {"preview_sha256": preview["preview_sha256"]}, "created_at": AT,
    }
    document.update(changes)
    with service.store.connect() as con:
        con.execute("insert into review_decisions values (?, ?, ?, ?)", [
            decision_id, json.dumps(document), datetime.fromisoformat(AT), None,
        ])


def test_missing_or_empty_root_is_empty_without_creating_an_archive(service):
    assert not service.root.exists()
    assert service.recent() == []
    assert not service.root.exists()
    service.root.mkdir()
    assert service.recent() == []


def test_valid_zero_and_corrupt_side_by_side_without_mutating_files_or_db(service):
    good = _preview(service)
    bad = _preview(service, 2)
    path = service.root / bad["id"] / "preview.json"
    path.write_bytes(b"{private synthetic invalid json")
    before = _files(service.store.path.parent)
    items = {item["id"]: item for item in service.recent()}
    verified = items[good["id"]]
    assert verified["prices_count"] == 0 and type(verified["prices_count"]) is int
    assert verified["created_at"] == AT
    assert verified["applied"] is False
    assert verified["integrity_status"] == "verified" and verified["error_code"] is None
    _placeholder(items[bad["id"]], bad["id"])
    assert _files(service.store.path.parent) == before


def test_all_corrupt_is_not_an_empty_list(service):
    for number in range(1, 4):
        doc = _preview(service, number)
        (service.root / doc["id"] / "preview.json").write_bytes(b"broken")
    items = service.recent()
    assert len(items) == 3
    for item in items:
        _placeholder(item, item["id"])


@pytest.mark.parametrize("damage", [
    "missing_preview", "missing_original", "changed_original", "invalid_utf8", "array", "scalar",
    "wrong_digest", "wrong_id", "query_shape", "evidence_shape", "missing_field", "nan",
    "symlink_directory", "symlink_preview", "symlink_original", "uuid_file",
])
def test_document_damage_remains_visible_and_sanitized(service, tmp_path, damage):
    original = b"Synthetic original that must never appear in a list"
    sha = hashlib.sha256(original).hexdigest()
    evidence = service.root / "evidence" / (sha + ".body")
    evidence.parent.mkdir(parents=True)
    evidence.write_bytes(original)
    doc = _preview(service, evidence=[{"sha256": sha}])
    directory = service.root / doc["id"]
    path = directory / "preview.json"
    if damage == "missing_preview":
        path.unlink()
    elif damage == "missing_original":
        evidence.unlink()
    elif damage == "changed_original":
        evidence.write_bytes(b"changed")
    elif damage in {"invalid_utf8", "array", "scalar", "nan"}:
        path.write_bytes({"invalid_utf8": b"\xff", "array": b"[]", "scalar": b"null",
                          "nan": b'{"private":NaN}'}[damage])
    elif damage == "wrong_digest":
        doc["prices_count"] = 99
        path.write_text(json.dumps(doc))
    elif damage == "wrong_id":
        _write(service, {**doc, "id": str(UUID(int=9))}, directory_id=doc["id"])
    elif damage in {"query_shape", "evidence_shape", "missing_field"}:
        key = {"query_shape": "query", "evidence_shape": "evidence", "missing_field": "created_at"}[damage]
        doc[key] = [] if damage == "query_shape" else "private:wrong-shape"
        if damage == "missing_field":
            del doc[key]
        _write(service, doc)
    elif damage == "symlink_directory":
        path.unlink()
        directory.rmdir()
        directory.symlink_to(tmp_path, target_is_directory=True)
    elif damage == "symlink_preview":
        path.unlink()
        path.symlink_to(evidence)
    elif damage == "symlink_original":
        evidence.unlink()
        evidence.symlink_to(service.store.path)
    else:
        path.unlink()
        directory.rmdir()
        directory.write_bytes(b"not a preview directory")
    items = service.recent()
    assert len(items) == 1
    _placeholder(items[0], doc["id"])
    serialized = json.dumps(items)
    assert "Synthetic original" not in serialized
    assert "private" not in serialized
    assert str(tmp_path) not in serialized


@pytest.mark.parametrize("changes", [
    {"payload": {"preview_sha256": "0" * 64}}, {"scope": "wrong"},
    {"decision_type": "token_review"}, {"updated_at": AT},
])
def test_forged_apply_binding_is_an_unavailable_row(service, changes):
    doc = _preview(service)
    _decision(service, doc, **changes)
    before = _files(service.store.path.parent)
    item, = service.recent()
    _placeholder(item, doc["id"], "historical_price_apply_decision_invalid")
    assert _files(service.store.path.parent) == before


def test_valid_apply_binding_is_preserved_and_not_a_method_admission(service):
    doc = _preview(service)
    _decision(service, doc)
    item, = service.recent()
    assert item["applied"] is True
    assert item["integrity_status"] == "verified"
    assert set(item) == set(HistoricalPricePreviewListItem.model_fields)


def test_read_retry_recovers_only_after_fixture_is_restored(service):
    doc = _preview(service)
    path = service.root / doc["id"] / "preview.json"
    expected = path.read_bytes()
    path.write_bytes(b"{")
    _placeholder(service.recent()[0], doc["id"])
    assert path.read_bytes() == b"{"
    path.write_bytes(expected)
    item, = service.recent()
    assert item["integrity_status"] == "verified"
    assert path.read_bytes() == expected


@pytest.mark.parametrize("root_kind", ["file", "symlink", "dangling_symlink"])
def test_invalid_root_is_a_service_error(service, tmp_path, root_kind):
    if root_kind == "file":
        service.root.write_bytes(b"not a directory")
    else:
        target = tmp_path if root_kind == "symlink" else tmp_path / "absent"
        service.root.symlink_to(target, target_is_directory=True)
    with pytest.raises(HistoricalPriceError, match="^historical_price_storage_invalid$"):
        service.recent()


def test_root_enumeration_permission_error_is_not_an_empty_list(service, monkeypatch):
    service.root.mkdir()

    def inaccessible(*args, **kwargs):
        raise PermissionError("synthetic root unavailable")

    monkeypatch.setattr(module.os, "scandir", inaccessible)
    with pytest.raises(PermissionError):
        service.recent()


@pytest.mark.parametrize("error", [
    duckdb.IOException, duckdb.ConnectionException, ValueError, RuntimeError, TypeError, AttributeError, KeyError, OSError,
])
def test_database_failure_is_never_a_document_placeholder(service, monkeypatch, error):
    _preview(service)

    @contextmanager
    def unavailable():
        raise error("synthetic database unavailable")
        yield  # pragma: no cover

    monkeypatch.setattr(service.store, "read_snapshot", unavailable)
    with pytest.raises(error, match="synthetic database unavailable"):
        service.recent()


def test_real_synthetic_database_failure_is_a_service_error(service):
    _preview(service)
    service.store.path.write_bytes(b"synthetic invalid DuckDB file")
    with pytest.raises(duckdb.Error):
        service.recent()


@pytest.mark.parametrize("plan", [[], {"not_finite": float("nan")}])
def test_corrupt_collection_plan_is_a_document_error(service, plan):
    doc = _preview(service, query={"scope": "all_observed"}, plan_sha256="0" * 64)
    (service.root / doc["id"] / "plan.json").write_text(json.dumps(plan))
    _placeholder(service.recent()[0], doc["id"])


def test_original_hash_cannot_be_a_path_locator(service):
    doc = _preview(service, evidence=[{"sha256": "../../synthetic-private-file"}])
    _placeholder(service.recent()[0], doc["id"])


def test_archive_read_oserror_is_per_document(service, monkeypatch):
    doc = _preview(service)
    expected_path = service.root / doc["id"] / "preview.json"
    read_bytes = Path.read_bytes

    def unreadable(path):
        if path == expected_path:
            raise PermissionError(13, "synthetic file unavailable", str(path))
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", unreadable)
    _placeholder(service.recent()[0], doc["id"])


def test_archive_read_oserror_after_preflight_is_still_per_document(service, monkeypatch):
    doc = _preview(service)
    expected_path = service.root / doc["id"] / "preview.json"
    read_bytes = Path.read_bytes
    calls = 0

    def unreadable(path):
        nonlocal calls
        if path == expected_path:
            calls += 1
            if calls == 2:
                raise PermissionError(13, "synthetic file unavailable", str(path))
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", unreadable)
    _placeholder(service.recent()[0], doc["id"])
    assert calls == 2


def test_per_file_stat_error_does_not_hide_other_entries(service, monkeypatch):
    good = _preview(service)
    bad = _preview(service, 2)
    lstat = Path.lstat

    def inaccessible(path):
        if path == service.root / bad["id"] / "preview.json":
            raise PermissionError("synthetic metadata unavailable")
        return lstat(path)

    monkeypatch.setattr(Path, "lstat", inaccessible)
    items = {item["id"]: item for item in service.recent()}
    assert items[good["id"]]["integrity_status"] == "verified"
    _placeholder(items[bad["id"]], bad["id"])


def test_database_oserror_with_filename_is_a_service_error(service, monkeypatch):
    _preview(service)

    @contextmanager
    def unavailable():
        raise PermissionError(13, "synthetic database unavailable", str(service.store.path))
        yield  # pragma: no cover

    monkeypatch.setattr(service.store, "read_snapshot", unavailable)
    with pytest.raises(PermissionError):
        service.recent()


def test_noncanonical_directory_names_are_never_returned(service):
    _preview(service)
    for name in ["not-a-uuid", "ABCDEFAB-CDEF-ABCD-EFAB-CDEFABCDEFAB", "{" + str(UUID(int=2)) + "}"]:
        directory = service.root / name
        directory.mkdir()
        (directory / "preview.json").write_bytes(b"private")
    items = service.recent()
    assert len(items) == 1 and items[0]["id"] == str(UUID(int=1))


def test_limit_and_metadata_sorting_do_not_fabricate_a_document_date(service):
    for number in range(1, 23):
        doc = _preview(service, number)
        path = service.root / doc["id"] / "preview.json"
        os.utime(path, ns=(number * 10**9, number * 10**9))
    items = service.recent()
    assert [row["id"] for row in items] == [str(UUID(int=number)) for number in range(22, 2, -1)]
    assert all(row["created_at"] == AT for row in items)


def _valid_item(**changes):
    return {"id": str(UUID(int=1)), "created_at": AT, "prices_count": 0, "status": "no_prices",
            "applied": False, "preview_sha256": "a" * 64, "integrity_status": "verified", **changes}


@pytest.mark.parametrize("field,value", [
    ("prices_count", True), ("prices_count", "0"), ("prices_count", 0.0), ("prices_count", -1),
    ("pending_count", True), ("open_count", "0"), ("applied", 0), ("manual", "true"),
    ("collection_complete", 1), ("created_at", "2025-06-13"),
    ("id", str(UUID(int=1)).replace("-", "")), ("parent_preview_id", "private/path"),
    ("preview_sha256", "private/path"), ("error_code", "private error message"),
    ("status", "private error message"), ("private_field", "not allowed"),
])
def test_model_rejects_coercions_untrusted_fields_and_bad_metadata(field, value):
    with pytest.raises(ValidationError):
        HistoricalPricePreviewListItem.model_validate(_valid_item(**{field: value}))


@pytest.mark.parametrize("field", METADATA)
def test_unavailable_model_cannot_retain_any_unverified_metadata(field):
    value = _valid_item(pending_count=0, open_count=0, parent_preview_id=str(UUID(int=2)),
                        collection_complete=False, manual=False)[field]
    with pytest.raises(ValidationError):
        HistoricalPricePreviewListItem.model_validate({
            "id": str(UUID(int=1)), "status": "unavailable", "integrity_status": "unavailable",
            "error_code": "historical_price_preview_unavailable", field: value,
        })


@pytest.mark.parametrize("changes", [
    {"integrity_status": "unavailable"}, {"status": "unavailable"},
    {"error_code": "historical_price_evidence_changed"}, {"created_at": None},
    {"prices_count": None}, {"applied": None}, {"preview_sha256": None},
])
def test_verified_model_requires_consistent_success(changes):
    with pytest.raises(ValidationError):
        HistoricalPricePreviewListItem.model_validate(_valid_item(**changes))


@pytest.mark.parametrize("changes", [
    {"prices_count": True}, {"manual": 1},
    {"created_at": "private/path"}, {"pending_count": -1},
])
def test_wrongly_typed_but_hash_consistent_metadata_is_unavailable(service, changes):
    doc = _preview(service, **changes)
    _placeholder(service.recent()[0], doc["id"])


def test_applied_comes_from_validated_database_decision_not_archived_claim(service):
    _preview(service, applied=True)
    item, = service.recent()
    assert item["integrity_status"] == "verified"
    assert item["applied"] is False
