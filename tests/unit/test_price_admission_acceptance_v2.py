"""Independent synthetic admission references; no product implementation oracle.

Missing new contract modules are one collection error, not arithmetic bugs.
Fixtures use the real existing manual import/apply workflow, never providers.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import duckdb
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from steuerreport_v2.api.historical_prices import build_historical_prices_router
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.price_admissions import (
    PriceAdmissionApply,
    PriceAdmissionDraftRequest,
    PriceAdmissionReport,
    PriceAdmissionRevoke,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain import historical_prices as historical
from steuerreport_v2.domain.historical_prices import HistoricalPriceService


BASE = "/api/v1/prices/historical"
VALUATION = "2025-06-13T01:00:00.123456Z"
QUOTE_TIME = "2025-06-13T00:30:00Z"
PRICE_BYTES = b"Synthetic price original; reviewed facts are a separate human transcription."
FX_BYTES = b"Synthetic FX original; reviewed facts are a separate human transcription."
METHOD_BYTES = b"Synthetic method description; no legal or automatic tax approval."
PRICE_SHA = hashlib.sha256(PRICE_BYTES).hexdigest()
FX_SHA = hashlib.sha256(FX_BYTES).hexdigest()
METHOD_SHA = hashlib.sha256(METHOD_BYTES).hexdigest()
PRIVATE = "SYNTHETIC-PRIVATE-NOT-FOR-ERRORS"
ABSENT = object()
BAD_ACKS = (False, 0, 1, "true", None, ABSENT)


def _at(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _data(response, status=200):
    assert response.status_code == status, response.text
    result = response.json()
    assert result["status"] != "error", response.text
    return result["data"]


def _report(response):
    result = _data(response)
    PriceAdmissionReport.model_validate(result)
    return result


def _rejected(response, env, statuses=(409, 422)):
    assert response.status_code in statuses, response.text
    assert response.json()["data"] is None
    assert PRIVATE not in response.text and str(env.store.path.parent) not in response.text


@pytest.fixture
def env(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "synthetic-admission.duckdb")
    with store.connect():
        pass
    effects = []
    cache_notifications = []

    def forbidden(*args, **kwargs):
        effects.append("external_call")
        raise AssertionError("Admission reference attempted provider access")

    monkeypatch.setattr(historical, "managed_client", forbidden)
    monkeypatch.setattr(HistoricalPriceService, "mappings", lambda self: {
        "TOKEN000": {"asset": "TOKEN000", "coingecko_id": "synthetic-token", "defillama_id": None},
    })
    # A lazy import of the full app must not create or touch its default DB.
    monkeypatch.setenv("STEUERREPORT_V2_DB", str(store.path))
    store.add_canonical_events([CanonicalEventCreate(
        source="synthetic", source_ref="synthetic-admission-deposit",
        asset="TOKEN000", quantity=Decimal("1"), event_time=_at("2025-06-13T01:00:00Z"),
        event_type="transfer", account="Synthetic account",
    )])
    app = FastAPI()
    app.include_router(build_historical_prices_router(store, lambda: cache_notifications.append("invalidate")))
    with TestClient(app) as client:
        yield SimpleNamespace(store=store, app=app, client=client, effects=effects,
                              root=store.path.parent / "historical_prices",
                              forbid_rebuild=lambda: monkeypatch.setattr(historical.PipelineService, "rebuild_ledgers", forbidden))
    assert "external_call" not in effects


def _attachment(body, source, filename):
    return {
        "filename": filename, "media_type": "application/octet-stream",
        "source_name": source, "source_reference": "synthetic document, line 1",
        "source_observed_at": "2025-06-14T10:00:00Z",
        "content_base64": base64.b64encode(body).decode("ascii"),
    }


def _imported(env, kind="eur", *, apply=True):
    query = {"scope": "all_observed", "assets": ["TOKEN000"], "max_requests": 1}
    planned = _data(env.client.post(BASE + "/plan", json=query))
    inverse = kind == "inverse"
    request = {
        "request_id": str(uuid4()), "query": query, "plan_sha256": planned["plan_sha256"],
        "asset": "TOKEN000", "price_date": "2025-06-13", "priced_at": QUOTE_TIME,
        "price_currency": "EUR" if kind == "eur" else "USD",
        "price_value": "125.50" if kind == "eur" else "100",
        "price_unit": "currency_per_asset",
        "price_evidence": _attachment(PRICE_BYTES, "Synthetic price source", "price.bin"),
    }
    if kind != "eur":
        request.update(
            fx_evidence=_attachment(FX_BYTES, "Synthetic FX source", "fx.bin"),
            fx_observations=[{
                "date": "2025-06-13", "base": "EUR" if inverse else "USD",
                "quote": "USD" if inverse else "EUR",
                "rate": "1.111111111111111111111111111" if inverse else "0.9",
                "source": "Synthetic FX source",
            }],
        )
    preview = _data(env.client.post(BASE + "/manual-previews", json=request))
    assert preview["status"] == "ready" and preview["prices_count"] == 1
    assert Decimal(preview["prices"][0]["price_eur"]) == Decimal("125.50" if kind == "eur" else "90")
    binding, = preview["price_bindings"]
    path = BASE + f"/previews/{preview['id']}/prices/{binding['price_id']}"
    if apply:
        _data(env.client.post(BASE + f"/previews/{preview['id']}/apply", json={
            "preview_sha256": preview["preview_sha256"], "actor": "Synthetic importer",
            "confirm_prices": True, "confirm_recalculation": True,
        }))
        evidence = _data(env.client.get(path + "/evidence"))
        assert evidence["price_fingerprint"] == binding["price_fingerprint"]
        assert Decimal(evidence["price_eur"]) == Decimal("125.50" if kind == "eur" else "90")
    env.forbid_rebuild()
    return SimpleNamespace(preview=preview, binding=binding, path=path, kind=kind)


def _payload(case=None, *, kind="eur"):
    identity = {"asset": "TOKEN000", "network": "ethereum", "contract": "0x" + "12" * 20, "decimals": 18}
    observation = {
        "identity": deepcopy(identity), "quote_currency": "EUR" if kind == "eur" else "USD",
        "value": "125.50" if kind == "eur" else "100", "kind": "observed_quote",
        "observed_at": QUOTE_TIME, "published_at": "2025-06-13T00:31:00Z",
        "evidence_sha256": PRICE_SHA, "locator": "synthetic price document, line 1",
        "source": "Synthetic price source",
    }
    method = {
        "method_id": "synthetic-observed-method", "version": 1, "kind": "observed_quote",
        "timezone": "UTC", "availability_rule": "available_at_cutoff", "evidence_sha256": METHOD_SHA,
    }
    if kind != "eur":
        inverse = kind == "inverse"
        observation["fx"] = {
            "base": "EUR" if inverse else "USD", "quote": "USD" if inverse else "EUR",
            "rate": "1.111111111111111111111111111" if inverse else "0.9",
            "reference_at": "2025-06-13T00:00:00Z", "published_at": "2025-06-13T00:10:00Z",
            "evidence_sha256": FX_SHA, "locator": "synthetic FX document, line 1", "source": "Synthetic FX source",
        }
        method["fx_max_age_days"] = 0
    return {
        "request_id": str(uuid4()),
        "preview_sha256": case.preview["preview_sha256"] if case else "a" * 64,
        "price_fingerprint": case.binding["price_fingerprint"] if case else "b" * 64,
        "valuation_at": VALUATION, "identity": identity, "observation": observation, "method": method,
        "method_original": {"filename": "method.txt", "media_type": "text/plain",
                            "content_base64": base64.b64encode(METHOD_BYTES).decode("ascii")},
        "actor": "Synthetic reviewer", "rationale": "Originals and limited temporal method explicitly reviewed.",
    }


def _draft(env, case, payload=None):
    return _report(env.client.post(case.path + "/admission-previews", json=payload or _payload(case, kind=case.kind)))


def _draft_url(case, draft):
    return case.path + "/admission-previews/" + draft["request_id"]


def _apply(env, case, draft, **changes):
    return env.client.post(_draft_url(case, draft) + "/apply", json={
        "draft_sha256": draft["draft_sha256"],
        "acknowledge_original_verified": True, "acknowledge_scope_limited": True, **changes,
    })


def _status(env, case, valuation=VALUATION):
    return _report(env.client.get(case.path + "/admissions", params={"valuation_at": valuation}))


def _revoke(env, case, draft, **changes):
    return env.client.post(case.path + "/admissions/" + draft["request_id"] + "/revoke", json={
        "draft_sha256": draft["draft_sha256"], "actor": "Synthetic second reviewer",
        "rationale": "Synthetic explicit revocation; retain the original decision unchanged.",
        "acknowledge_revocation": True, **changes,
    })


def _financial(env):
    with env.store.connect() as con:
        names = [row[0] for row in con.execute(
            "select table_name from information_schema.tables where table_schema='main' order by table_name"
        ).fetchall() if row[0] != "review_decisions"]
        return {name: con.execute('select * from "' + name.replace('"', '""') + '" order by all').fetchall()
                for name in names}


def _reviews(env):
    with env.store.connect() as con:
        return con.execute("select * from review_decisions order by id").fetchall()


def _artifacts(env):
    return {str(path.relative_to(env.root)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in env.root.rglob("*") if path.is_file() and not path.is_symlink()
            and path.name != "calculation.prepared"}


def _not_positive(report):
    assert report["status"] != "human_approved"
    assert report["assessment"]["strict_eligible"] is False


def _blocked_or_error(response, env):
    if response.status_code == 200:
        report = _report(response)
        _not_positive(report)
        assert report["can_apply"] is False
        assert report["assessment"]["reason_codes"]
    else:
        _rejected(response, env)


@pytest.mark.parametrize("kind", ["eur", "usd", "inverse"])
def test_real_import_draft_and_apply_admit_fixed_reference_values_only_as_review_data(env, kind):
    case = _imported(env, kind)
    financial, reviews = _financial(env), _reviews(env)
    callbacks = list(env.effects)
    before = datetime.now(timezone.utc)
    draft = _draft(env, case)
    after = datetime.now(timezone.utc)
    assert draft["status"] == "prepared" and draft["can_apply"] is True
    assert draft["assessment"]["status"] == "not_approved"
    assert draft["assessment"]["reason_codes"] == ["approval_missing"]
    assert draft["assessment"]["strict_eligible"] is False
    assert draft["decision"] is draft["revocation"] is None
    assert draft["preview_id"] == case.preview["id"] and draft["price_id"] == case.binding["price_id"]
    assert _at(draft["valuation_at"]) == _at(VALUATION)
    assert before <= _at(draft["created_at"]) <= after
    assert before <= _at(draft["observation"]["captured_at"]) <= after
    if kind != "eur":
        assert before <= _at(draft["observation"]["fx"]["captured_at"]) <= after
    else:
        assert draft["observation"]["fx"] is None
    assert _reviews(env) == reviews and _financial(env) == financial
    files = _artifacts(env)
    assert _report(env.client.get(_draft_url(case, draft))) == draft
    download = env.client.get(_draft_url(case, draft) + "/method-original")
    assert download.status_code == 200 and download.content == METHOD_BYTES
    assert _artifacts(env) == files and _reviews(env) == reviews
    apply_before = datetime.now(timezone.utc)
    admitted = _report(_apply(env, case, draft))
    apply_after = datetime.now(timezone.utc)
    assert admitted["status"] == admitted["assessment"]["status"] == "human_approved"
    assert admitted["assessment"]["strict_eligible"] is True and admitted["can_apply"] is False
    decision = admitted["decision"]
    assert decision["decision_id"] == "price-time-admission:" + draft["request_id"]
    assert decision["decision_type"] == "stichtag_price_time_admission"
    assert decision["actor"] == draft["actor"] and decision["rationale"] == draft["rationale"]
    assert decision["updated_at"] is None
    assert apply_before <= _at(decision["created_at"]) <= apply_after
    scope = "price_time_admission:" + case.binding["price_id"] + ":"
    assert decision["scope"].startswith(scope)
    assert _at(decision["scope"][len(scope):]) == _at(VALUATION)
    assert len(_reviews(env)) == len(reviews) + 1
    assert _financial(env) == financial and env.effects == callbacks


@pytest.mark.parametrize("part", ["observation", "fx"])
def test_client_captured_at_is_forbidden_not_a_historical_availability_claim(part):
    payload = _payload(kind="usd")
    target = payload["observation"] if part == "observation" else payload["observation"]["fx"]
    target["captured_at"] = "2025-06-13T00:00:00Z"
    with pytest.raises(ValidationError):
        PriceAdmissionDraftRequest.model_validate(payload)


@pytest.mark.parametrize("field", ["preview_sha256", "price_fingerprint", "actor", "rationale", "request_id"])
def test_request_requires_import_hashes_actor_rationale_and_own_uuid(field):
    payload = _payload()
    del payload[field]
    with pytest.raises(ValidationError):
        PriceAdmissionDraftRequest.model_validate(payload)


@pytest.mark.parametrize("field,value", [
    ("value", True), ("value", 1.25), ("value", "NaN"), ("value", "Infinity"),
    ("observed_at", "2025-06-13T00:30:00"), ("published_at", "2025-06-13T00:31:00"),
])
def test_observation_input_does_not_coerce_unsafe_numbers_or_naive_times(field, value):
    payload = _payload()
    payload["observation"][field] = value
    with pytest.raises(ValidationError):
        PriceAdmissionDraftRequest.model_validate(payload)


@pytest.mark.parametrize("which", ["valuation_naive", "method_version_bool", "method_version_float", "client_assessment", "alternate_price"])
def test_typed_request_cannot_supply_result_or_replace_selected_price(which):
    payload = _payload()
    if which == "valuation_naive":
        payload["valuation_at"] = "2025-06-13T01:00:00"
    elif which.startswith("method_version"):
        payload["method"]["version"] = True if which.endswith("bool") else 1.0
    else:
        payload["assessment" if which == "client_assessment" else "price_eur"] = "125.50"
    with pytest.raises(ValidationError):
        PriceAdmissionDraftRequest.model_validate(payload)


@pytest.mark.parametrize("field", ["acknowledge_original_verified", "acknowledge_scope_limited"])
@pytest.mark.parametrize("value", BAD_ACKS, ids=["false", "zero", "one", "string", "null", "missing"])
def test_apply_requires_two_explicit_real_true_booleans(field, value):
    request = {"draft_sha256": "a" * 64, "acknowledge_original_verified": True, "acknowledge_scope_limited": True}
    if value is ABSENT:
        del request[field]
    else:
        request[field] = value
    with pytest.raises(ValidationError):
        PriceAdmissionApply.model_validate(request)


@pytest.mark.parametrize("value", BAD_ACKS, ids=["false", "zero", "one", "string", "null", "missing"])
def test_revoke_requires_explicit_real_true_and_retains_actor_and_rationale(value):
    request = {"draft_sha256": "a" * 64, "actor": "Synthetic reviewer", "rationale": "Synthetic revocation",
               "acknowledge_revocation": True}
    if value is ABSENT:
        del request["acknowledge_revocation"]
    else:
        request["acknowledge_revocation"] = value
    with pytest.raises(ValidationError):
        PriceAdmissionRevoke.model_validate(request)


@pytest.mark.parametrize("original", ["empty", "invalid_base64", "too_large", "path_filename"])
def test_method_upload_rejects_invalid_or_oversized_originals(original):
    request = _payload()
    if original == "empty":
        request["method_original"]["content_base64"] = ""
    elif original == "invalid_base64":
        request["method_original"]["content_base64"] = "!!!!"
    elif original == "too_large":
        request["method_original"]["content_base64"] = base64.b64encode(b"x" * (2 * 1024 * 1024 + 1)).decode()
    else:
        request["method_original"]["filename"] = "../" + PRIVATE
    with pytest.raises(ValidationError):
        PriceAdmissionDraftRequest.model_validate(request)


@pytest.mark.parametrize("which", ["float_value", "captured_at", "fx_captured_at", "naive_valuation", "blank_actor", "extra_price_id"])
def test_real_draft_route_enforces_input_contract_without_review_writes(env, which):
    kind = "usd" if which == "fx_captured_at" else "eur"
    case = _imported(env, kind)
    payload = _payload(case, kind=kind)
    if which == "float_value":
        payload["observation"]["value"] = 125.5
    elif which == "captured_at":
        payload["observation"]["captured_at"] = "2025-06-13T00:00:00Z"
    elif which == "fx_captured_at":
        payload["observation"]["fx"]["captured_at"] = "2025-06-13T00:00:00Z"
    elif which == "naive_valuation":
        payload["valuation_at"] = "2025-06-13T01:00:00"
    elif which == "blank_actor":
        payload["actor"] = " "
    else:
        payload["price_id"] = str(uuid4())
    before = _reviews(env), _financial(env)
    _rejected(env.client.post(case.path + "/admission-previews", json=payload), env, (422,))
    assert (_reviews(env), _financial(env)) == before


@pytest.mark.parametrize("field", ["acknowledge_original_verified", "acknowledge_scope_limited"])
def test_real_apply_route_rejects_false_acknowledgement(env, field):
    case = _imported(env)
    draft = _draft(env, case)
    before = _reviews(env), _financial(env)
    _rejected(_apply(env, case, draft, **{field: False}), env, (422,))
    assert (_reviews(env), _financial(env)) == before


@pytest.mark.parametrize("which", ["preview_hash", "point_fingerprint", "method_hash", "unbound_original"])
def test_known_but_mismatching_bindings_never_offer_apply(env, which):
    case = _imported(env)
    payload = _payload(case)
    target, field = {
        "preview_hash": (payload, "preview_sha256"), "point_fingerprint": (payload, "price_fingerprint"),
        "method_hash": (payload["method"], "evidence_sha256"),
        "unbound_original": (payload["observation"], "evidence_sha256"),
    }[which]
    target[field] = "0" * 64
    reviews, financial = _reviews(env), _financial(env)
    _blocked_or_error(env.client.post(case.path + "/admission-previews", json=payload), env)
    assert _reviews(env) == reviews and _financial(env) == financial


@pytest.mark.parametrize("which", ["value", "identity", "quote_time", "publication", "retrospective_quote"])
def test_human_claim_does_not_override_pure_value_identity_or_time_rules(env, which):
    case = _imported(env)
    payload = _payload(case)
    if which == "value":
        payload["observation"]["value"] = "125.51"
    elif which == "identity":
        payload["observation"]["identity"]["contract"] = "0x" + "34" * 20
    elif which == "quote_time":
        payload["observation"]["observed_at"] = "2025-06-13T00:29:59Z"
    elif which == "publication":
        payload["observation"]["published_at"] = "2025-06-13T01:00:00.123457Z"
    else:
        payload["method"]["availability_rule"] = "retrospective_daily_reference"
    reviews = _reviews(env)
    _blocked_or_error(env.client.post(case.path + "/admission-previews", json=payload), env)
    assert _reviews(env) == reviews


@pytest.mark.parametrize("statistic", ["daily_mean", "daily_fixed_time", "daily_close"])
def test_explicit_retrospective_daily_method_stays_named_daily_and_can_be_confirmed(env, statistic):
    case = _imported(env)
    payload = _payload(case)
    payload["observation"].update(kind="daily_reference", observed_at=None,
        period_start="2025-06-12T22:00:00Z", period_end="2025-06-13T22:00:00Z",
        published_at="2025-06-14T00:00:00Z")
    payload["method"].update(kind="daily_reference", daily_statistic=statistic, timezone="Europe/Berlin",
        availability_rule="retrospective_daily_reference")
    if statistic == "daily_fixed_time":
        payload["method"]["daily_time"] = "12:00:00"
    draft = _draft(env, case, payload)
    assert draft["can_apply"] is True
    admitted = _report(_apply(env, case, draft))
    assert admitted["status"] == "human_approved"
    assert admitted["observation"]["kind"] == "daily_reference" and admitted["observation"]["observed_at"] is None
    assert admitted["method"]["daily_statistic"] == statistic
    assert _at(admitted["observation"]["published_at"]) > _at(VALUATION)


def test_admission_requires_actual_import_apply_not_only_prepared_clone(env):
    case = _imported(env, apply=False)
    reviews = _reviews(env)
    _rejected(env.client.post(case.path + "/admission-previews", json=_payload(case)), env, (409,))
    assert _reviews(env) == reviews


def test_same_request_id_is_idempotent_but_changed_request_is_a_conflict(env):
    case = _imported(env)
    payload = _payload(case)
    first = _draft(env, case, payload)
    before = _artifacts(env)
    second = _draft(env, case, payload)
    assert first == second
    assert _artifacts(env) == before
    changed = deepcopy(payload)
    changed["rationale"] += " Changed."
    _rejected(env.client.post(case.path + "/admission-previews", json=changed), env, (409,))
    assert _report(env.client.get(_draft_url(case, first))) == first


@pytest.mark.parametrize("resource", ["price", "preview", "draft"])
def test_other_well_formed_uuid_cannot_reuse_a_draft(env, resource):
    case = _imported(env)
    draft = _draft(env, case)
    path = _draft_url(case, draft)
    wrong = str(uuid4())
    target = {"price": case.binding["price_id"], "preview": case.preview["id"], "draft": draft["request_id"]}[resource]
    response = env.client.get(path.replace(target, wrong))
    _rejected(response, env, (404, 409))


def test_apply_retries_do_not_append_a_second_review_or_recalculate(env):
    case = _imported(env)
    draft = _draft(env, case)
    first = _report(_apply(env, case, draft))
    before = _reviews(env), _financial(env), _artifacts(env), list(env.effects)
    assert _report(_apply(env, case, draft)) == first
    assert _status(env, case)["decision"] == first["decision"]
    assert (_reviews(env), _financial(env), _artifacts(env), env.effects) == before


def test_wrong_draft_hash_cannot_apply_or_revoke(env):
    case = _imported(env)
    draft = _draft(env, case)
    reviews = _reviews(env)
    _rejected(_apply(env, case, draft, draft_sha256="0" * 64), env, (409,))
    assert _reviews(env) == reviews
    admitted = _report(_apply(env, case, draft))
    reviews = _reviews(env)
    _rejected(_revoke(env, case, draft, draft_sha256="0" * 64), env, (409,))
    assert _reviews(env) == reviews and _status(env, case)["decision"] == admitted["decision"]


def test_revoke_is_append_only_and_old_apply_cannot_reactivate(env):
    case = _imported(env)
    draft = _draft(env, case)
    approved = _report(_apply(env, case, draft))
    old_rows, files, financial = _reviews(env), _artifacts(env), _financial(env)
    revoked = _report(_revoke(env, case, draft))
    assert revoked["status"] == "revoked" and revoked["can_apply"] is False
    assert revoked["assessment"]["strict_eligible"] is False
    assert revoked["decision"] == approved["decision"]
    assert revoked["revocation"]["decision_type"] == "stichtag_price_time_admission_revocation"
    assert revoked["revocation"]["actor"] == "Synthetic second reviewer"
    rows = _reviews(env)
    assert len(rows) == len(old_rows) + 1 and all(row in rows for row in old_rows)
    assert _financial(env) == financial
    assert all(_artifacts(env).get(name) == checksum for name, checksum in files.items())
    assert _status(env, case)["status"] == "revoked"
    _rejected(_apply(env, case, draft), env, (409,))
    assert _reviews(env) == rows


@pytest.mark.parametrize("which", ["price_original", "method_original", "price_missing", "method_missing", "import_preview",
                                   "import_decision", "draft", "price_value", "review_time", "review_payload"])
def test_post_approval_changes_invalidate_read_status_without_repair(env, which):
    case = _imported(env)
    draft = _draft(env, case)
    admitted = _report(_apply(env, case, draft))
    if which in {"price_original", "price_missing"}:
        path = env.root / "evidence" / (PRICE_SHA + ".body")
        if which == "price_missing":
            path.unlink()
        else:
            path.chmod(0o600)
            path.write_bytes(PRICE_BYTES + b" changed")
    elif which in {"method_original", "method_missing"}:
        paths = [path for path in env.root.rglob("*") if path.is_file() and not path.is_symlink()
                 and path.name != "calculation.prepared" and path.read_bytes() == METHOD_BYTES]
        assert paths, "Method original must be stored, not only transcribed metadata"
        for path in paths:
            if which == "method_missing":
                path.unlink()
            else:
                path.chmod(0o600)
                path.write_bytes(METHOD_BYTES + b" changed")
    elif which in {"draft", "import_preview"}:
        path = (env.root / "admissions" / draft["request_id"] / "draft.json" if which == "draft"
                else env.root / case.preview["id"] / "preview.json")
        path.chmod(0o600)
        path.write_bytes(b"invalid draft " + PRIVATE.encode())
    else:
        with env.store.connect() as con:
            if which == "price_value":
                con.execute("update price_ledger set price_eur=126 where price_id=?", [case.binding["price_id"]])
            elif which == "review_time":
                con.execute("update review_decisions set created_at=created_at + interval 1 second where id=?",
                            [admitted["decision"]["decision_id"]])
            elif which == "import_decision":
                con.execute("update review_decisions set payload_json='{}' where id=?", ["historical-price:" + case.preview["id"]])
            else:
                con.execute("update review_decisions set payload_json='{}' where id=?", [admitted["decision"]["decision_id"]])
    before = _reviews(env), _financial(env), _artifacts(env)
    response = env.client.get(case.path + "/admissions", params={"valuation_at": VALUATION})
    if which in {"price_missing", "method_missing"} and response.status_code == 404:
        _rejected(response, env, (404,))
    else:
        _blocked_or_error(response, env)
    assert (_reviews(env), _financial(env), _artifacts(env)) == before


def test_exact_valuation_microsecond_is_not_a_scope_wildcard(env):
    case = _imported(env)
    draft = _draft(env, case)
    _report(_apply(env, case, draft))
    exact = _status(env, case)
    assert exact["status"] == "human_approved"
    response = env.client.get(case.path + "/admissions", params={"valuation_at": "2025-06-13T01:00:00.123457Z"})
    if response.status_code == 404:
        _rejected(response, env, (404,))
    else:
        other = _data(response)
        if other is not None:
            PriceAdmissionReport.model_validate(other)
            _not_positive(other)
            assert other["decision"] is None
            assert _at(other["valuation_at"]) == _at("2025-06-13T01:00:00.123457Z")


def test_multiple_active_decisions_do_not_use_latest_wins(env):
    case = _imported(env)
    first = _draft(env, case)
    one = _report(_apply(env, case, first))
    second = _draft(env, case)
    response = _apply(env, case, second)
    if response.status_code == 409:
        # Preventing the conflicting append is also safe; first remains current.
        assert _status(env, case)["decision"] == one["decision"]
    else:
        _report(response)
        report = _status(env, case)
        _not_positive(report)
        assert report["can_apply"] is False


def test_simultaneous_identical_apply_is_reserved_and_has_one_review_effect(env):
    case = _imported(env)
    draft = _draft(env, case)
    count = len(_reviews(env))
    financial = _financial(env)
    barrier = Barrier(2)

    def apply_once():
        barrier.wait(timeout=10)
        return _apply(env, case, draft)

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: apply_once(), range(2)))
    assert all(response.status_code in {200, 409} for response in responses)
    assert any(response.status_code == 200 for response in responses)
    repeated = _report(_apply(env, case, draft))
    assert repeated["status"] == "human_approved"
    assert len(_reviews(env)) == count + 1 and _financial(env) == financial


@pytest.mark.parametrize("phase", ["before_insert", "after_commit"])
def test_storage_fault_never_duplicates_or_loses_acknowledged_review_on_retry(env, monkeypatch, phase):
    case = _imported(env)
    draft = _draft(env, case)
    original = env.store.connect
    fired = []

    class Connection:
        def __init__(self):
            self.connection = original()
            self.review_inserted = False
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return self.connection.__exit__(*args)
        def __getattr__(self, name):
            return getattr(self.connection, name)
        def execute(self, sql, *args, **kwargs):
            normalized = " ".join(sql.lower().split()).rstrip(";")
            insert = normalized.startswith("insert") and "review_decisions" in normalized
            commit = normalized in {"commit", "commit transaction"}
            if not fired and phase == "before_insert" and insert:
                fired.append(True)
                raise duckdb.IOException("synthetic review storage failure")
            result = self.connection.execute(sql, *args, **kwargs)
            self.review_inserted = self.review_inserted or insert
            if not fired and phase == "after_commit" and commit and self.review_inserted:
                fired.append(True)
                raise duckdb.IOException("synthetic commit acknowledgement failure")
            return result
        def commit(self):
            result = self.connection.commit()
            if not fired and phase == "after_commit" and self.review_inserted:
                fired.append(True)
                raise duckdb.IOException("synthetic commit acknowledgement failure")
            return result

    before = _reviews(env)
    with monkeypatch.context() as patch:
        patch.setattr(env.store, "connect", Connection)
        response = _apply(env, case, draft)
        assert response.status_code in {200, 503}, response.text
        if response.status_code == 200:
            if phase == "before_insert":
                failed = _report(response)
                _not_positive(failed)
                assert failed["can_apply"] is False
            else:
                assert _report(response)["status"] == "human_approved"
    assert fired, "Fault must hit the specified SQL boundary, not silently pass"
    rows = _reviews(env)
    assert len(rows) == len(before) + (phase == "after_commit")
    assert all(row in rows for row in before)
    answer = _report(_apply(env, case, draft))
    assert answer["status"] == "human_approved" and len(_reviews(env)) == len(before) + 1


@pytest.mark.parametrize("operation", ["draft", "apply", "revoke"])
def test_sandbox_blocks_every_admission_mutation(env, operation):
    case = _imported(env)
    draft = _draft(env, case)
    if operation == "revoke":
        _report(_apply(env, case, draft))
    before = _reviews(env), _financial(env), _artifacts(env)
    env.app.state.ux_sandbox = True
    if operation == "draft":
        response = env.client.post(case.path + "/admission-previews", json=_payload(case))
    elif operation == "apply":
        response = _apply(env, case, draft)
    else:
        response = _revoke(env, case, draft)
    _rejected(response, env, (403,))
    assert (_reviews(env), _financial(env), _artifacts(env)) == before
    assert env.client.get(_draft_url(case, draft)).status_code == 200


@pytest.mark.parametrize("decision_type", ["stichtag_price_time_admission", "stichtag_price_time_admission_revocation"])
def test_generic_review_post_cannot_forge_reserved_decision_types(env, decision_type):
    from steuerreport_v2.api.app import create_app

    before = _reviews(env), _financial(env)
    with TestClient(create_app(env.store)) as client:
        response = client.post("/api/v1/review/decisions", json={
            "decision_type": decision_type, "scope": "synthetic-unbound", "title": "Synthetic forgery",
            "actor": "Synthetic user", "rationale": "No dedicated validation and no bound originals.",
            "payload": {},
        })
    _rejected(response, env, (403, 409, 422))
    assert (_reviews(env), _financial(env)) == before


def test_native_gate_consumes_only_selected_price_and_exact_valuation(env):
    from steuerreport_v2.api.app import create_app

    case = _imported(env)
    draft = _draft(env, case)
    _report(_apply(env, case, draft))
    before = _reviews(env), _financial(env), _artifacts(env)
    with TestClient(create_app(env.store)) as client:
        current = _data(client.get("/api/v1/prices/as-of-gate", params={"as_of": VALUATION}))
        other = _data(client.get("/api/v1/prices/as-of-gate", params={"as_of": "2025-06-13T01:00:00.123457Z"}))
    candidate = next(row for row in current["candidates"] if row["asset"] == "TOKEN000")
    assert candidate["price_admission"]["price_id"] == case.binding["price_id"]
    assert candidate["price_admission"]["status"] == "human_approved"
    assert candidate["price_time"]["strict_eligible"] is False  # Legacy diagnosis is not rewritten.
    other_candidate = next(row for row in other["candidates"] if row["asset"] == "TOKEN000")
    admission = other_candidate.get("price_admission")
    assert admission is None or admission["assessment"]["strict_eligible"] is False
    assert other["strict_ready"] is False
    assert (_reviews(env), _financial(env), _artifacts(env)) == before
