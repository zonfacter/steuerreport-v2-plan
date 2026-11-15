"""Independent synthetic #63 recent-preview references through the real router."""
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import duckdb
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from steuerreport_v2.api.historical_prices import build_historical_prices_router
from steuerreport_v2.contracts import historical_prices as contracts
from steuerreport_v2.contracts.historical_prices import HistoricalPriceQuery
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.contracts.review import ReviewDecision, ReviewDecisionCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain import historical_prices as module
from steuerreport_v2.domain.historical_prices import HistoricalPriceService
from steuerreport_v2.importers.source_history_importer import canonical_json


URL = "/api/v1/prices/historical/previews"
AT = datetime(2025, 6, 13, 12, tzinfo=timezone.utc)
UNKNOWN_FIELDS = (
    "created_at", "prices_count", "applied", "preview_sha256", "pending_count",
    "open_count", "parent_preview_id", "collection_complete", "manual",
)
SAFE_CODES = {
    "historical_price_evidence_changed", "historical_price_apply_decision_invalid",
    "historical_price_preview_unavailable",
}
PRIVATE = "SYNTHETIC-PRIVATE-MUST-NOT-LEAK"
SNAPSHOT_TABLES = ("price_ledger", "review_decisions", "raw_objects", "canonical_events")


def _uuid(number):
    return str(UUID(int=number))


def _hash(document):
    return hashlib.sha256(canonical_json(document).encode()).hexdigest()


@pytest.fixture
def env(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "disposable.duckdb")
    point = store.add_price_point(PricePointCreate(
        asset="TOKEN", price_eur=Decimal("125.50"), priced_at=AT, source="synthetic-recent",
    ))
    store.add_review_decision(ReviewDecisionCreate(
        decision_type="synthetic_reference", scope="synthetic-only", title="Existing review",
        rationale="Synthetic unrelated row must remain unchanged.",
    ))
    effects = []

    def forbidden(*args, **kwargs):
        effects.append("unexpected_provider_or_mutation")
        raise AssertionError("GET attempted provider or mutation")

    monkeypatch.setattr(module, "managed_client", forbidden)
    for name in ("fetch", "manual_preview", "continue_preview", "apply", "_write"):
        monkeypatch.setattr(HistoricalPriceService, name, forbidden)
    service = HistoricalPriceService(store)
    app = FastAPI()
    app.include_router(build_historical_prices_router(store, forbidden))
    with TestClient(app) as client:
        yield SimpleNamespace(
            store=store, root=service.root, service=service, client=client,
            point=point, tmp=tmp_path, effects=effects,
        )
    assert effects == []


def _preview(env, number=1, *, count=1, applied=False):
    request_id = _uuid(number)
    directory = env.root / request_id
    directory.mkdir(parents=True, exist_ok=True)
    original = canonical_json({"synthetic": True, "asset": "TOKEN", "value_eur": "125.50"}).encode()
    sha = hashlib.sha256(original).hexdigest()
    evidence = env.root / "evidence" / (sha + ".body")
    evidence.parent.mkdir(exist_ok=True)
    evidence.write_bytes(original)
    document = {
        "id": request_id, "created_at": AT.isoformat(),
        "query": HistoricalPriceQuery().model_dump(mode="json"),
        "prices_count": count, "prices": [env.point.model_dump(mode="json")] if count else [],
        "status": "ready", "pending_count": 0, "open_count": 0,
        "parent_preview_id": None, "collection_complete": True, "manual": False,
        "evidence": [{"sha256": sha, "kind": "synthetic_original"}],
        "writes_financial_data": False,
    }
    document["preview_sha256"] = _hash(document)
    path = directory / "preview.json"
    path.write_text(canonical_json(document), encoding="ascii")
    os.utime(path, (1000 + number, 1000 + number))
    result = SimpleNamespace(id=request_id, path=path, evidence=evidence, document=document)
    if applied:
        _decision(env, result)
    return result


def _rewrite(preview, **changes):
    document = {**preview.document, **changes}
    document.pop("preview_sha256", None)
    document["preview_sha256"] = _hash(document)
    preview.document = document
    preview.path.write_text(canonical_json(document), encoding="ascii")


def _decision(env, preview, *, changes=None, raw=None, db_updated=None):
    decision_id = "historical-price:" + preview.id
    fields = {
        "decision_id": decision_id, "decision_type": "historical_price_import",
        "scope": "historical_prices:" + preview.id, "title": "Synthetic import acknowledgement",
        "rationale": "Synthetic stored approval; never a new apply action.", "actor": "Synthetic user",
        "evidence_ref": "api:" + URL + "/" + preview.id,
        "payload": {"preview_sha256": preview.document["preview_sha256"]}, "created_at": AT,
    }
    fields.update(changes or {})
    payload = raw if raw is not None else ReviewDecision(**fields).model_dump_json()
    with env.store.connect() as con:
        con.execute("insert into review_decisions values (?, ?, ?, ?)", [decision_id, payload, AT, db_updated])


def _list(env):
    response = env.client.get(URL)
    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body["data"], list)
    return body


def _verified(row, preview, *, applied=False):
    assert row["id"] == preview.id
    assert row["integrity_status"] == "verified"
    assert row["error_code"] is None
    assert row["status"] == "ready"
    assert row["prices_count"] == preview.document["prices_count"]
    assert type(row["prices_count"]) is int
    assert row["applied"] is applied
    assert datetime.fromisoformat(row["created_at"].replace("Z", "+00:00")) == AT
    assert row["preview_sha256"] == preview.document["preview_sha256"]


def _unavailable(row, request_id, *, code=None):
    assert row["id"] == request_id
    assert row["status"] == row["integrity_status"] == "unavailable"
    assert row["error_code"] in SAFE_CODES
    if code is not None:
        assert row["error_code"] == code
    for key in UNKNOWN_FIELDS:
        assert key in row and row[key] is None, (key, row)


def _warned(body):
    assert body["status"] == "warning"
    assert any(row["code"] == "historical_price_recent_partial" for row in body["warnings"])


def _no_leaks(response, env):
    assert PRIVATE not in response.text
    assert str(env.tmp) not in response.text
    assert "Traceback" not in response.text


def _snapshot(env):
    with env.store.connect() as con:
        tables = {table: con.execute(f"select * from {table} order by all").fetchall()
                  for table in SNAPSHOT_TABLES}
    files = {}
    if env.root.is_dir() and not env.root.is_symlink():
        for path in env.root.rglob("*"):
            if path.is_file() and not path.is_symlink():
                files[str(path.relative_to(env.root))] = path.read_bytes()
    return tables, files


def test_empty_missing_root_is_loaded_empty_not_an_error(env):
    assert not env.root.exists()
    body = _list(env)
    assert body["data"] == []
    assert body["status"] == "ok" and body["warnings"] == []
    assert not env.root.exists()


@pytest.mark.parametrize("applied", [False, True])
def test_valid_bound_preview_retains_fields_and_real_import_state(env, applied):
    preview = _preview(env, applied=applied)
    body = _list(env)
    assert len(body["data"]) == 1
    _verified(body["data"][0], preview, applied=applied)
    assert body["status"] == "ok" and body["warnings"] == []


@pytest.mark.parametrize("damage", ["json", "hash", "missing_original", "changed_original", "missing_preview"])
def test_mixed_valid_and_bad_preview_remain_two_visible_rows(env, damage):
    good = _preview(env, 1)
    bad = _preview(env, 2)
    if damage == "json":
        bad.path.write_bytes(("invalid-json " + PRIVATE).encode())
    elif damage == "hash":
        bad.path.write_text(canonical_json({**bad.document, "prices_count": 99}), encoding="ascii")
    elif damage == "missing_original":
        # Give the bad row its own original so the good row stays independently valid.
        raw = b"synthetic second original"
        sha = hashlib.sha256(raw).hexdigest()
        _rewrite(bad, evidence=[{"sha256": sha, "kind": "synthetic_original"}])
    elif damage == "changed_original":
        raw = b"synthetic second original"
        sha = hashlib.sha256(raw).hexdigest()
        _rewrite(bad, evidence=[{"sha256": sha, "kind": "synthetic_original"}])
        (env.root / "evidence" / (sha + ".body")).write_bytes(raw + b" changed")
    else:
        bad.path.unlink()
    response = env.client.get(URL)
    assert response.status_code == 200, response.text
    _no_leaks(response, env)
    body = response.json()
    assert {row["id"] for row in body["data"]} == {good.id, bad.id}
    rows = {row["id"]: row for row in body["data"]}
    _verified(rows[good.id], good)
    _unavailable(rows[bad.id], bad.id)
    _warned(body)


def test_all_bad_are_unavailable_not_empty_and_unknown_is_not_zero_or_false(env):
    first, second = _preview(env, 1), _preview(env, 2)
    first.evidence.unlink()
    body = _list(env)
    assert len(body["data"]) == 2
    for row in body["data"]:
        _unavailable(row, row["id"], code="historical_price_evidence_changed")
    assert {row["id"] for row in body["data"]} == {first.id, second.id}
    _warned(body)


def test_valid_zero_count_and_bad_unknown_count_are_distinct(env):
    zero, bad = _preview(env, 1, count=0), _preview(env, 2)
    bad.path.write_bytes(b"{")
    body = _list(env)
    rows = {row["id"]: row for row in body["data"]}
    assert set(rows) == {zero.id, bad.id}
    assert rows[zero.id]["prices_count"] == 0 and rows[zero.id]["applied"] is False
    assert rows[bad.id]["prices_count"] is None and rows[bad.id]["applied"] is None
    _verified(rows[zero.id], zero)
    _unavailable(rows[bad.id], bad.id)


@pytest.mark.parametrize("forgery", ["type", "scope", "hash", "evidence_ref", "updated", "malformed"])
def test_wrong_import_decision_does_not_silently_drop_row_or_claim_unapplied(env, forgery):
    preview = _preview(env)
    changes = {
        "type": {"decision_type": "stichtag_price_time_admission"},
        "scope": {"scope": "unrelated:" + PRIVATE},
        "hash": {"payload": {"preview_sha256": "0" * 64}},
        "evidence_ref": {"evidence_ref": "private:" + PRIVATE},
        "updated": {"updated_at": AT}, "malformed": {},
    }[forgery]
    _decision(env, preview, changes=changes, raw="invalid:" + PRIVATE if forgery == "malformed" else None)
    response = env.client.get(URL)
    assert response.status_code == 200, response.text
    _no_leaks(response, env)
    body = response.json()
    assert len(body["data"]) == 1
    _unavailable(body["data"][0], preview.id, code="historical_price_apply_decision_invalid")
    _warned(body)


@pytest.mark.parametrize("document_id", [_uuid(999), PRIVATE])
def test_preview_document_id_cannot_relabel_a_different_directory(env, document_id):
    preview = _preview(env)
    _rewrite(preview, id=document_id)
    body = _list(env)
    assert PRIVATE not in canonical_json(body)
    assert len(body["data"]) == 1
    _unavailable(body["data"][0], preview.id)


@pytest.mark.parametrize("operation", ["read_bytes", "stat"])
def test_per_file_oserror_keeps_other_rows_visible_and_has_no_private_error_text(env, monkeypatch, operation):
    good, bad = _preview(env, 1), _preview(env, 2)
    original = getattr(Path, operation)

    def denied(path, *args, **kwargs):
        if path == bad.path:
            raise PermissionError(PRIVATE + " " + str(bad.path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, operation, denied)
    response = env.client.get(URL)
    assert response.status_code == 200, response.text
    _no_leaks(response, env)
    body = response.json()
    assert {row["id"] for row in body["data"]} == {good.id, bad.id}
    rows = {row["id"]: row for row in body["data"]}
    _verified(rows[good.id], good)
    _unavailable(rows[bad.id], bad.id, code="historical_price_preview_unavailable")
    _warned(body)


@pytest.mark.parametrize("kind", ["file", "symlink", "dangling_symlink", "unreadable"])
def test_broken_root_is_a_service_error_not_a_loaded_empty_list(env, monkeypatch, kind):
    if kind == "file":
        env.root.write_text(PRIVATE)
    elif kind in {"symlink", "dangling_symlink"}:
        target = env.tmp / (PRIVATE + "-outside")
        if kind == "symlink":
            target.mkdir()
        env.root.symlink_to(target, target_is_directory=True)
    else:
        env.root.mkdir()
        original = os.scandir

        def denied(path):
            if path == env.root or path == str(env.root):
                raise PermissionError(PRIVATE + " " + str(env.root))
            return original(path)

        monkeypatch.setattr(os, "scandir", denied)
    response = env.client.get(URL)
    assert response.status_code in {409, 503}, response.text
    assert response.json()["status"] == "error" and response.json()["data"] is None
    _no_leaks(response, env)


@pytest.mark.parametrize("failure", ["database", "external_service_boundary"])
def test_global_outage_is_not_an_empty_or_unavailable_document_list(env, monkeypatch, failure):
    _preview(env)
    if failure == "database":
        @contextmanager
        def unavailable(*args, **kwargs):
            raise duckdb.IOException(PRIVATE + " " + str(env.store.path))
            yield  # pragma: no cover

        monkeypatch.setattr(env.store, "read_snapshot", unavailable)
    else:
        def unavailable(*args, **kwargs):
            raise RuntimeError(PRIVATE + " external service boundary")

        monkeypatch.setattr(HistoricalPriceService, "recent", unavailable)
    response = env.client.get(URL)
    assert response.status_code == 503, response.text
    body = response.json()
    assert body["status"] == "error" and body["data"] is None
    assert body["errors"][0]["code"] == "historical_price_service_unavailable"
    _no_leaks(response, env)


@pytest.mark.parametrize("alias", ["hex", "upper", "braces", "untrusted_name"])
def test_only_canonical_uuid_directories_are_listed_once(env, alias):
    preview = _preview(env, int("abcdef", 16))
    name = {"hex": preview.id.replace("-", ""), "upper": preview.id.upper(),
            "braces": "{" + preview.id + "}", "untrusted_name": PRIVATE}[alias]
    directory = env.root / name
    directory.mkdir()
    path = directory / "preview.json"
    path.write_bytes(preview.path.read_bytes())
    response = env.client.get(URL)
    assert response.status_code == 200, response.text
    _no_leaks(response, env)
    assert [row["id"] for row in response.json()["data"]] == [preview.id]


def test_canonical_symlink_directory_never_reads_its_external_target(env, monkeypatch):
    preview = _preview(env)
    outside = env.tmp / (PRIVATE + "-target")
    outside.mkdir()
    target = outside / "preview.json"
    target.write_text(PRIVATE)
    link_id = _uuid(2)
    (env.root / link_id).symlink_to(outside, target_is_directory=True)
    original = Path.read_bytes
    reads = []

    def guarded(path):
        if path == target or path == env.root / link_id / "preview.json":
            reads.append(str(path))
            raise AssertionError("External symlink target must never be read")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    response = env.client.get(URL)
    assert response.status_code == 200, response.text
    assert reads == []
    _no_leaks(response, env)
    rows = {row["id"]: row for row in response.json()["data"]}
    assert preview.id in rows and set(rows) <= {preview.id, link_id}
    if link_id in rows:
        _unavailable(rows[link_id], link_id)


def test_limit_applies_to_last_twenty_candidates_not_twenty_successes(env):
    previews = [_preview(env, number) for number in range(1, 26)]
    for number, preview in enumerate(previews, 1):
        if number >= 6:
            preview.path.write_bytes(b"{")
        os.utime(preview.path, (1000 + number, 1000 + number))
    body = _list(env)
    expected = [_uuid(number) for number in range(25, 5, -1)]
    assert [row["id"] for row in body["data"]] == expected
    assert len(body["data"]) == 20
    for row in body["data"]:
        _unavailable(row, row["id"])
    _warned(body)


def test_corruption_outside_last_twenty_does_not_create_a_global_partial_warning(env):
    previews = [_preview(env, number) for number in range(1, 26)]
    for number, preview in enumerate(previews, 1):
        if number <= 5:
            preview.path.write_bytes(b"{")
        os.utime(preview.path, (1000 + number, 1000 + number))
    body = _list(env)
    assert [row["id"] for row in body["data"]] == [_uuid(number) for number in range(25, 5, -1)]
    assert body["status"] == "ok" and body["warnings"] == []
    assert len(body["data"]) == 20


@pytest.mark.parametrize("broken", [False, True])
def test_repeated_get_preserves_original_review_and_price_rows_without_repairs(env, broken):
    preview = _preview(env, applied=True)
    if broken:
        preview.path.write_bytes(b"{broken:" + PRIVATE.encode())
    before = _snapshot(env)
    first, second = env.client.get(URL), env.client.get(URL)
    assert first.status_code == second.status_code == 200
    assert _snapshot(env) == before
    assert env.effects == []
    assert first.json()["data"] == second.json()["data"]


def test_repaired_original_can_be_rechecked_by_get_without_apply_or_provider(env):
    preview = _preview(env)
    original = preview.evidence.read_bytes()
    preview.evidence.write_bytes(original + b" tampered")
    bad = _list(env)
    assert len(bad["data"]) == 1
    _unavailable(bad["data"][0], preview.id, code="historical_price_evidence_changed")
    preview.evidence.write_bytes(original)
    before = _snapshot(env)
    good = _list(env)
    assert len(good["data"]) == 1
    _verified(good["data"][0], preview)
    assert good["status"] == "ok" and good["warnings"] == []
    assert _snapshot(env) == before and env.effects == []


def test_domain_recent_remains_list_of_dicts_for_existing_callers(env):
    preview = _preview(env)
    rows = env.service.recent()
    assert isinstance(rows, list) and len(rows) == 1
    assert type(rows[0]) is dict and rows[0]["id"] == preview.id


def test_real_router_adds_partial_warning_even_for_clients_ignoring_row_markers(env, monkeypatch):
    row = {"id": _uuid(1), "status": "unavailable", "integrity_status": "unavailable",
           "error_code": "historical_price_preview_unavailable", **{key: None for key in UNKNOWN_FIELDS}}
    monkeypatch.setattr(HistoricalPriceService, "recent", lambda self: [row])
    body = _list(env)
    assert body["data"] == [row]
    _warned(body)


def test_typed_list_contract_is_present_strict_and_null_consistent():
    model = getattr(contracts, "HistoricalPricePreviewListItem", None)
    assert model is not None, "Missing additive contract HistoricalPricePreviewListItem"
    bad = {"id": _uuid(1), "status": "unavailable", "integrity_status": "unavailable",
           "error_code": "historical_price_preview_unavailable", **{key: None for key in UNKNOWN_FIELDS}}
    assert model.model_validate(bad).model_dump(mode="json") == bad
    good = {**bad, "status": "ready", "integrity_status": "verified", "error_code": None,
            "created_at": AT.isoformat(), "prices_count": 0, "applied": False, "preview_sha256": "a" * 64,
            "pending_count": 0, "open_count": 0, "collection_complete": True, "manual": False}
    assert model.model_validate(good).prices_count == 0
    invalid = [
        {**bad, "prices_count": 0}, {**bad, "applied": False},
        {**good, "error_code": "historical_price_preview_unavailable"},
        {**good, "prices_count": True}, {**good, "prices_count": "0"},
        {**good, "pending_count": -1}, {**good, "open_count": 0.0},
        {**good, "applied": 0}, {**good, "manual": "false"},
        {**bad, "error_code": PRIVATE}, {**good, "extra_private": PRIVATE},
    ]
    for payload in invalid:
        with pytest.raises(ValidationError):
            model.model_validate(payload)
