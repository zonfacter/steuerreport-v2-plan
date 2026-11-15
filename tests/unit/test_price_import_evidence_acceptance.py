"""Unabhaengige synthetische Importreader-Abnahme, ohne API oder Provider.

Manifestmutationen werden nur mit ausdruecklicher synthetischer Neubindung
als intern konsistente Angriffe behandelt. Keine echte Reviewentscheidung.
"""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
from types import SimpleNamespace
from uuid import UUID

import duckdb
import pytest
from pydantic import ValidationError

from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.historical_prices import (
    HistoricalPriceApply, HistoricalPriceQuery, ManualHistoricalPricePreviewRequest,
)
from steuerreport_v2.contracts.price_import_evidence import PreparedPriceBinding
from steuerreport_v2.contracts.prices import PricePoint, PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain import historical_prices as history_module
from steuerreport_v2.domain import price_import_evidence as reader_module
from steuerreport_v2.domain.historical_prices import HistoricalPriceError, HistoricalPriceService
from steuerreport_v2.domain.price_evidence import price_point_fingerprint
from steuerreport_v2.domain.price_import_evidence import PriceImportEvidenceService


AT = datetime(2024, 6, 2, 12, tzinfo=timezone.utc)
PREVIEW_ID = str(UUID("875096ef-8f53-46ac-9a4a-952190887639"))
ORIGINAL = b"Synthetic original: TOKEN000 EUR125.50 at 2024-06-02T11:30Z"


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def _canonical(document):
    return json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _forbidden(*args, **kwargs):
    pytest.fail("Acceptance probe attempted a provider/network access")


@contextmanager
def _offline():
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(socket.socket, "connect", _forbidden)
        patch.setattr(socket, "create_connection", _forbidden)
        patch.setattr(history_module, "managed_client", _forbidden)
        patch.setattr(history_module, "outbound_scope", _forbidden)
        yield


@pytest.fixture(autouse=True)
def offline():
    with _offline():
        yield


@pytest.fixture(scope="module")
def applied_template(tmp_path_factory):
    root = tmp_path_factory.mktemp("synthetic-import-reader-template")
    with _offline():
        store = DuckDbStore(root / "synthetic.duckdb")
        store.add_canonical_events([CanonicalEventCreate(
            source="synthetic-acceptance", source_ref="disposable-transfer", event_time=AT,
            event_type="transfer", asset="TOKEN000", quantity=Decimal("1"), account="synthetic-account",
        )])
        history = HistoricalPriceService(store)
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(history, "mappings", lambda: {
                "TOKEN000": {"asset": "TOKEN000", "coingecko_id": "synthetic-token", "defillama_id": None},
            })
            query = HistoricalPriceQuery(scope="all_observed", assets=["TOKEN000"], max_requests=1)
            plan = history.plan(query)
            request = ManualHistoricalPricePreviewRequest.model_validate({
                "request_id": PREVIEW_ID, "query": query, "plan_sha256": plan["plan_sha256"],
                "asset": "TOKEN000", "price_date": "2024-06-02", "price_value": "125.50",
                "price_currency": "EUR", "priced_at": "2024-06-02T11:30:00Z",
                "price_evidence": {
                    "filename": "synthetic-original.bin", "media_type": "application/octet-stream",
                    "source_name": "Synthetic original", "source_reference": "synthetic page 1",
                    "source_observed_at": AT, "content_base64": base64.b64encode(ORIGINAL).decode(),
                },
            })
            preview = history.manual_preview(request)
        binding, = preview["price_bindings"]
        assert preview["status"] == "ready" and preview["price_bindings_version"] == 1
        with pytest.raises(HistoricalPriceError, match="^historical_price_not_applied$"):
            PriceImportEvidenceService(store).read(PREVIEW_ID, binding["price_id"])
        history.apply(PREVIEW_ID, HistoricalPriceApply(
            preview_sha256=preview["preview_sha256"], actor="Synthetic acceptance only",
            confirm_prices=True, confirm_recalculation=True,
        ))
        # The originalreader must not depend on or load the prepared database.
        (history.root / PREVIEW_ID / "calculation.prepared").unlink()
        with store.connect() as con:
            con.execute("checkpoint")
    return root


@pytest.fixture
def case(applied_template, tmp_path):
    root = tmp_path / "isolated-case"
    shutil.copytree(applied_template, root)
    store = DuckDbStore(root / "synthetic.duckdb")
    with store.connect():
        pass
    history = HistoricalPriceService(store)
    directory = history.root / PREVIEW_ID
    preview = json.loads((directory / "preview.json").read_bytes())
    binding, = preview["price_bindings"]
    yield SimpleNamespace(root=root, store=store, history=history, reader=PriceImportEvidenceService(store),
                          directory=directory, preview=preview, binding=binding,
                          price_id=binding["price_id"], sha=_sha(ORIGINAL))
    shutil.rmtree(root)


def _write_json(path, document):
    if path.exists():
        path.chmod(0o600)
    path.write_text(_canonical(document), encoding="utf-8")


def _synthetic_rebind(case, change):
    """Only test data: explicitly bind a new manifest and synthetic decision."""
    document = deepcopy(case.preview)
    change(document)
    document.pop("preview_sha256", None)
    document["preview_sha256"] = _sha(_canonical(document).encode())
    _write_json(case.directory / "preview.json", document)
    with case.store.connect() as con:
        raw, = con.execute("select payload_json from review_decisions where id=?",
                           ["historical-price:" + PREVIEW_ID]).fetchone()
        decision = json.loads(raw)
        decision["payload"] = {"preview_sha256": document["preview_sha256"]}
        con.execute("update review_decisions set payload_json=? where id=?",
                    [_canonical(decision), decision["decision_id"]])
    case.preview = document
    return document


def _state(case):
    with case.store.read_initialized_snapshot() as snapshot, snapshot.connect() as con:
        tables = [row[0] for row in con.execute(
            "select table_name from information_schema.tables where table_schema='main' order by table_name",
        ).fetchall()]
        data = {table: con.execute('select * from "' + table.replace('"', '""') + '" order by all').fetchall()
                for table in tables}
        schema = con.execute("select * from information_schema.columns order by table_name, ordinal_position").fetchall()
    files = {}
    for path in case.root.rglob("*"):
        if path.is_symlink():
            files[str(path.relative_to(case.root))] = ("symlink", os.readlink(path))
        elif path.is_file():
            files[str(path.relative_to(case.root))] = ("file", _sha(path.read_bytes()))
    return schema, data, files


def _read(case):
    return case.reader.read(PREVIEW_ID, case.price_id)


def _reject(case, *codes):
    before = _state(case)
    with pytest.raises(HistoricalPriceError) as error:
        _read(case)
    assert str(error.value) in codes
    assert _state(case) == before


def _attach(case, contents):
    hashes = []
    for content in contents:
        sha = _sha(content)
        path = case.history.root / "evidence" / (sha + ".body")
        if path.exists():
            path.chmod(0o600)
        path.write_bytes(content)
        hashes.append(sha)

    def change(document):
        document["rows"][0]["evidence_sha256"] = hashes
        document["evidence"] = [{"sha256": sha, "filename": "synthetic.bin"} for sha in hashes]

    _synthetic_rebind(case, change)
    return hashes


def test_real_manual_preview_apply_reader_and_download_are_read_only(case, monkeypatch):
    before = _state(case)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "read_bytes", _forbidden)
        patch.setattr(Path, "mkdir", _forbidden)
        patch.setattr(case.store, "ensure_schema", _forbidden)
        patch.setattr(history_module.PipelineService, "rebuild_ledgers", _forbidden)
        report = _read(case)
        body, filename = case.reader.download(PREVIEW_ID, case.price_id, case.sha)
    assert _state(case) == before
    assert report.status == "verified_import_binding" and report.integrity_scope == "selected_price_only"
    assert report.strict_eligible is False and report.admission_status == "not_reviewed"
    assert report.observed_at is report.price_published_at is report.fx_published_at is None
    assert report.price_fingerprint == case.binding["price_fingerprint"]
    assert report.price_eur == Decimal("125.50")
    assert report.stored_reference_at == datetime(2024, 6, 2, 11, 30, tzinfo=timezone.utc)
    assert body == ORIGINAL and filename == "synthetic-original.bin"
    ref, = report.originals
    assert ref.sha256 == case.sha and ref.byte_length == len(ORIGINAL)
    assert ref.download_url == (
        f"/api/v1/prices/historical/previews/{PREVIEW_ID}/prices/{case.price_id}/evidence/{case.sha}"
    )


def test_missing_prepared_database_is_not_an_originalreader_dependency(case):
    assert not (case.directory / "calculation.prepared").exists()
    assert _read(case).price_id == UUID(case.price_id)


def test_originalreader_never_opens_a_huge_prepared_database(case, monkeypatch):
    path = case.directory / "calculation.prepared"
    with path.open("wb") as stream:
        stream.truncate(64 * 1024 * 1024)
    original_open = os.open

    def bounded_open(path, flags, *args, **kwargs):
        assert "calculation.prepared" not in os.fsdecode(path)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(reader_module.os, "open", bounded_open)
    assert _read(case).status == "verified_import_binding"


def test_no_apply_decision_is_not_imported_even_if_receipt_claims_success(case):
    with case.store.connect() as con:
        con.execute("delete from review_decisions where id=?", ["historical-price:" + PREVIEW_ID])
    _reject(case, "historical_price_not_applied")


@pytest.mark.parametrize("field,value", [
    ("decision_id", "synthetic-wrong-id"), ("decision_type", "token_review"),
    ("scope", "wrong-scope"), ("evidence_ref", "api:/wrong-preview"),
    ("payload", {"preview_sha256": "0" * 64}), ("payload", {"preview_sha256": "0" * 64, "extra": True}),
    ("updated_at", "2025-01-01T00:00:00Z"), ("created_at", "2000-01-01T00:00:00Z"),
])
def test_decision_must_match_the_exact_original_import(case, field, value):
    with case.store.connect() as con:
        row = con.execute("select id,payload_json from review_decisions").fetchone()
        document = json.loads(row[1])
        document[field] = value
        con.execute("update review_decisions set payload_json=? where id=?", [_canonical(document), row[0]])
    _reject(case, "historical_price_apply_decision_invalid")


@pytest.mark.parametrize("part", ["preview", "plan", "receipt"])
@pytest.mark.parametrize("damage", ["missing", "invalid_json", "duplicate_key", "nonfinite", "nonobject"])
def test_malformed_or_missing_manifests_fail_closed(case, part, damage):
    filename = {"preview": "preview.json", "plan": "plan.json", "receipt": "applied.json"}[part]
    path = case.directory / filename
    if damage == "missing":
        path.unlink()
        if part == "receipt":
            assert _read(case).status == "verified_import_binding"
            return
        _reject(case, "historical_price_not_found")
        return
    path.chmod(0o600)
    path.write_bytes({"invalid_json": b"{", "duplicate_key": b'{"x":1,"x":2}',
                      "nonfinite": b'{"x":NaN}', "nonobject": b"[]"}[damage])
    _reject(case, "historical_price_evidence_changed")


@pytest.mark.parametrize("part", ["preview", "plan", "receipt"])
def test_byte_changes_without_synthetic_rebinding_are_rejected(case, part):
    path = case.directory / {"preview": "preview.json", "plan": "plan.json", "receipt": "applied.json"}[part]
    document = json.loads(path.read_bytes())
    if part == "receipt":
        document["decision_id"] = "not-the-applied-decision"
    else:
        document["unbound_test_change"] = True
    _write_json(path, document)
    _reject(case, "historical_price_evidence_changed")


@pytest.mark.parametrize("mutation,code", [
    ("legacy", "historical_price_binding_missing"), ("version_bool", "historical_price_binding_missing"),
    ("missing_binding", "historical_price_binding_invalid"), ("duplicate", "historical_price_binding_invalid"),
    ("wrong_fingerprint", "historical_price_binding_invalid"), ("wrong_id", "historical_price_binding_invalid"),
    ("wrong_asset", "historical_price_binding_invalid"), ("wrong_value", "historical_price_binding_invalid"),
    ("naive_binding_time", "historical_price_binding_invalid"), ("count_bool", "historical_price_binding_invalid"),
])
def test_bound_price_identity_has_no_symbol_or_value_fallback(case, mutation, code):
    def change(document):
        binding = document["price_bindings"][0]
        if mutation == "legacy":
            document.pop("price_bindings_version")
        elif mutation == "version_bool":
            document["price_bindings_version"] = True
        elif mutation == "missing_binding":
            document.pop("price_bindings")
        elif mutation == "duplicate":
            document["price_bindings"].append(deepcopy(binding))
            document["prices"].append(deepcopy(document["prices"][0]))
            document["prices_count"] = 2
        elif mutation == "count_bool":
            document["prices_count"] = True
        else:
            field, value = {
                "wrong_fingerprint": ("price_fingerprint", "0" * 64),
                "wrong_id": ("price_id", str(UUID(int=45))), "wrong_asset": ("asset", "OTHER"),
                "wrong_value": ("price_eur", "999"),
                "naive_binding_time": ("stored_reference_at", "2024-06-02T11:30:00"),
            }[mutation]
            binding[field] = value

    _synthetic_rebind(case, change)
    _reject(case, code)


@pytest.mark.parametrize("field,value", [
    ("asset", "OTHER"), ("price_eur", "999"), ("source", "synthetic-other-source"),
    ("confidence", "0.5"), ("priced_at", "2024-06-02T11:31:00"),
])
def test_live_price_change_cannot_reuse_an_archived_fingerprint(case, field, value):
    with case.store.connect() as con:
        con.execute(f"update price_ledger set {field}=? where price_id=?", [value, case.price_id])
    _reject(case, "historical_price_binding_invalid")


def test_deleted_live_price_is_not_recreated(case):
    with case.store.connect() as con:
        con.execute("delete from price_ledger where price_id=?", [case.price_id])
    _reject(case, "historical_price_point_not_found")


def test_another_real_id_with_identical_values_is_not_an_evidence_alias(case):
    original = case.preview["prices"][0]
    other = case.store.add_price_point(PricePointCreate.model_validate(original))
    with pytest.raises(HistoricalPriceError, match="^historical_price_binding_invalid$"):
        case.reader.read(PREVIEW_ID, other.price_id)


@pytest.mark.parametrize("mutation,code", [
    ("missing_row", "historical_price_binding_ambiguous"), ("duplicate_row", "historical_price_binding_ambiguous"),
    ("missing_refs", "historical_price_binding_invalid"), ("unknown_ref", "historical_price_binding_invalid"),
    ("path_ref", "historical_price_binding_invalid"), ("uppercase_ref", "historical_price_binding_invalid"),
    ("nonstring_ref", "historical_price_binding_invalid"), ("missing_metadata", "historical_price_binding_invalid"),
])
def test_only_unique_selected_row_originals_are_eligible(case, mutation, code):
    def change(document):
        row = document["rows"][0]
        if mutation == "missing_row":
            document["rows"] = []
        elif mutation == "duplicate_row":
            document["rows"].append(deepcopy(row))
        elif mutation == "missing_metadata":
            document["evidence"] = []
        else:
            row["evidence_sha256"] = {
                "missing_refs": [], "unknown_ref": ["0" * 64], "path_ref": ["../../outside"],
                "uppercase_ref": [case.sha.upper()], "nonstring_ref": [{"sha": case.sha}],
            }[mutation]

    _synthetic_rebind(case, change)
    _reject(case, code)


def test_other_previews_original_cannot_be_downloaded_for_this_price(case):
    foreign = b"synthetic unrelated original"
    sha = _sha(foreign)
    (case.history.root / "evidence" / (sha + ".body")).write_bytes(foreign)
    _synthetic_rebind(case, lambda doc: doc["evidence"].append({"sha256": sha}))
    report = _read(case)
    assert [ref.sha256 for ref in report.originals] == [case.sha]
    with pytest.raises(HistoricalPriceError, match="^historical_price_not_found$"):
        case.reader.original(PREVIEW_ID, case.price_id, sha)


@pytest.mark.parametrize("damage", ["missing", "changed", "empty"])
def test_original_bytes_must_still_exist_and_match_their_hash(case, damage):
    path = case.history.root / "evidence" / (case.sha + ".body")
    path.chmod(0o600)
    if damage == "missing":
        path.unlink()
        _reject(case, "historical_price_not_found")
    else:
        path.write_bytes(b"changed" if damage == "changed" else b"")
        _reject(case, "historical_price_evidence_changed")


@pytest.mark.parametrize("target", ["root", "preview_directory", "preview", "plan", "receipt", "evidence_directory", "original"])
def test_no_symlink_component_can_supply_evidence(case, tmp_path, target):
    path = {
        "root": case.history.root, "preview_directory": case.directory,
        "preview": case.directory / "preview.json", "plan": case.directory / "plan.json",
        "receipt": case.directory / "applied.json", "evidence_directory": case.history.root / "evidence",
        "original": case.history.root / "evidence" / (case.sha + ".body"),
    }[target]
    outside = tmp_path / ("synthetic-symlink-target-" + target)
    path.rename(outside)
    path.symlink_to(outside, target_is_directory=outside.is_dir())
    _reject(case, "historical_price_evidence_changed")


@pytest.mark.parametrize("name", [
    None, 42, True, [], {}, ["nested"], {"nested": "filename"}, "", ".", "..", "../private.bin",
    "subdir/file.bin", "subdir\\file.bin", "evil\r\nheader.bin", "nul\x00.bin", "x" * 181,
])
def test_malformed_filename_metadata_is_omitted_without_losing_verified_bytes(case, name):
    _synthetic_rebind(case, lambda doc: doc["evidence"][0].update(filename=name))
    report = _read(case)
    ref, = report.originals
    assert ref.filename is None
    body, filename = case.reader.download(PREVIEW_ID, case.price_id, case.sha)
    assert body == ORIGINAL and filename == f"price-original-{case.sha}.body"


def test_differing_filename_claims_are_not_arbitrarily_selected(case):
    def change(document):
        document["evidence"].append({**document["evidence"][0], "filename": "different.bin"})

    _synthetic_rebind(case, change)
    assert _read(case).originals[0].filename is None


def test_private_metadata_cannot_become_report_fields_or_query_parameters(case):
    marker = "synthetic-private-sentinel"

    def change(document):
        document["evidence"][0].update(url="https://invalid.test/" + marker, params={"key": marker},
                                        source_reference=marker, source_observed_at="2099-01-01T00:00:00Z")

    _synthetic_rebind(case, change)
    serialized = _read(case).model_dump_json()
    assert marker not in serialized and str(case.root) not in serialized
    assert "2099-01-01" not in serialized and ORIGINAL.decode() not in serialized
    assert "?" not in _read(case).originals[0].download_url


@pytest.mark.parametrize("which", ["preview", "original"])
def test_fifo_is_rejected_without_a_potentially_blocking_open(case, monkeypatch, which):
    path = case.directory / "preview.json" if which == "preview" else case.history.root / "evidence" / (case.sha + ".body")
    path.unlink()
    os.mkfifo(path)
    original_open = os.open
    checked = []

    def guarded_open(name, flags, *args, **kwargs):
        if os.fsdecode(name) == path.name:
            checked.append(name)
            # This assertion fires before the real syscall on pre-fix code.
            assert flags & os.O_NONBLOCK, "FIFO file open must be nonblocking before fstat"
        return original_open(name, flags, *args, **kwargs)

    monkeypatch.setattr(reader_module.os, "open", guarded_open)
    with pytest.raises(HistoricalPriceError, match="^historical_price_evidence_changed$"):
        _read(case)
    assert checked


@pytest.mark.parametrize("part", ["preview", "original", "receipt"])
def test_each_file_limit_is_checked_before_loading_oversized_data(case, part):
    path, limit = {
        "preview": (case.directory / "preview.json", case.reader.MAX_PREVIEW_BYTES),
        "original": (case.history.root / "evidence" / (case.sha + ".body"), case.reader.MAX_ORIGINAL_BYTES),
        "receipt": (case.directory / "applied.json", 4096),
    }[part]
    path.chmod(0o600)
    with path.open("wb") as stream:
        stream.truncate(limit + 1)
    with pytest.raises(HistoricalPriceError, match="^historical_price_reader_limit_exceeded$"):
        _read(case)


@pytest.mark.parametrize("extra", [0, 1])
def test_total_original_limit_is_inclusive_and_enforced(case, extra):
    contents = [bytes([marker]) * (2 * 1024 * 1024) for marker in (65, 66, 67)]
    if extra:
        contents.append(b"x")
    _attach(case, contents)
    if extra:
        with pytest.raises(HistoricalPriceError, match="^historical_price_reader_limit_exceeded$"):
            _read(case)
    else:
        report = _read(case)
        assert sum(ref.byte_length for ref in report.originals) == 6 * 1024 * 1024


@pytest.mark.parametrize("count", [1001])
def test_original_reference_count_is_bounded_before_any_file_load(case, count):
    _synthetic_rebind(case, lambda doc: doc["rows"][0].update(evidence_sha256=[case.sha] * count))
    _reject(case, "historical_price_binding_invalid")


def test_uninitialized_store_is_refused_without_creation_or_schema_repair(tmp_path, monkeypatch):
    path = tmp_path / "uninitialized.duckdb"
    store = DuckDbStore(path)
    monkeypatch.setattr(store, "ensure_schema", _forbidden)
    monkeypatch.setattr(store, "connect", _forbidden)
    with pytest.raises(HistoricalPriceError, match="^historical_price_store_not_initialized$"):
        PriceImportEvidenceService(store).read(PREVIEW_ID, str(UUID(int=1)))
    assert not path.exists() and not (tmp_path / "historical_prices").exists()
    assert store._schema_ready is False


def test_one_readonly_snapshot_covers_decision_and_price_queries(case, monkeypatch):
    contexts = []
    original = case.store.read_initialized_snapshot
    # A rejected write aborts DuckDB's transaction; close that disposable
    # transaction before observing the reader's separate, healthy snapshot.
    with original() as snapshot, snapshot.connect() as con:
        with pytest.raises(duckdb.Error):
            con.execute("delete from price_ledger")

    @contextmanager
    def observed_snapshot():
        with original() as snapshot:
            contexts.append(snapshot)
            yield snapshot

    monkeypatch.setattr(case.store, "read_initialized_snapshot", observed_snapshot)
    assert _read(case).status == "verified_import_binding"
    assert len(contexts) == 1


def test_semantic_fingerprint_requires_aware_time_but_db_utc_is_normalized_by_reader(case):
    with case.store.connect() as con:
        row = con.execute("select asset,price_eur,priced_at,source,confidence from price_ledger where price_id=?",
                          [case.price_id]).fetchone()
    assert row[2].tzinfo is None
    point = PricePoint(price_id=case.price_id, asset=row[0], price_eur=row[1], priced_at=row[2], source=row[3], confidence=row[4])
    with pytest.raises(ValidationError):
        price_point_fingerprint(point)
    point.priced_at = point.priced_at.replace(tzinfo=timezone.utc)
    assert price_point_fingerprint(point) == case.binding["price_fingerprint"]
    assert _read(case).stored_reference_at == point.priced_at


@pytest.mark.parametrize("mismatched_original_row", [False, True])
def test_same_persisted_value_does_not_make_distinct_original_inputs_equal(case, mismatched_original_row):
    first, second = "125.5000000000000000001", "125.5000000000000000002"
    with case.store.connect() as con:
        stored_first, stored_second = con.execute(
            "select cast(? as decimal(38,18)), cast(? as decimal(38,18))", [first, second],
        ).fetchone()
    assert stored_first == stored_second == Decimal("125.5")
    assert Decimal(first) != Decimal(second)
    binding = deepcopy(case.preview["price_bindings"])

    def change(document):
        document["prices"][0]["price_eur"] = first
        document["rows"][0]["price_eur"] = second if mismatched_original_row else first

    _synthetic_rebind(case, change)
    assert case.preview["price_bindings"] == binding
    if mismatched_original_row:
        _reject(case, "historical_price_binding_ambiguous", "historical_price_binding_invalid")
    else:
        report = _read(case)
        assert report.price_eur == stored_first
        assert report.price_fingerprint == binding[0]["price_fingerprint"]


def test_preparation_fingerprints_the_actual_quantized_clone_rows(case):
    directory = case.root / "synthetic-precision-prepare"
    directory.mkdir()
    point = PricePointCreate(asset="TOKEN000", price_eur=Decimal("1.1234567891234567899"),
                             priced_at=AT, source="synthetic-precision-source", confidence=Decimal("0.987654321"))
    preview = {"database_revision": case.history._revision()}
    case.history._prepare(directory, preview, [point])
    binding, = preview["price_bindings"]
    with duckdb.connect(str(directory / "calculation.prepared"), read_only=True) as con:
        row = con.execute("select price_id,asset,price_eur,priced_at,source,confidence from price_ledger where price_id=?",
                          [binding["price_id"]]).fetchone()
    assert row[2] == Decimal("1.123456789123456790") and row[5] == Decimal("0.98765432")
    assert row[2] != point.price_eur and row[5] != point.confidence
    actual = PricePoint(price_id=row[0], asset=row[1], price_eur=row[2], priced_at=row[3].replace(tzinfo=timezone.utc),
                        source=row[4], confidence=row[5])
    assert binding["price_fingerprint"] == price_point_fingerprint(actual)
    assert PreparedPriceBinding.model_validate(binding).price_eur == actual.price_eur
