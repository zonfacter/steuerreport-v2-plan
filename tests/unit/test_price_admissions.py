"""Echte isolierte Import-/Bestaetigungsroute, keine produktiven Entscheidungen."""
import base64
from copy import deepcopy
import hashlib
from uuid import uuid4

import pytest

from test_historical_price_workflow import (
    BASE, data, prepared_original, source_snapshot, workflow as workflow,
)
from steuerreport_v2.domain.price_admissions import PriceAdmissionService


METHOD = b"Synthetic method: observed quote, EUR per token; available at cutoff."


def admission_request(preview, binding):
    identity = {"asset": "TOKEN000", "network": "synthetic", "contract": "synthetic-token", "decimals": 8}
    return {
        "request_id": str(uuid4()), "preview_sha256": preview["preview_sha256"],
        "price_fingerprint": binding["price_fingerprint"], "valuation_at": "2024-06-02T13:00:00Z",
        "identity": identity,
        "observation": {"identity": identity, "quote_currency": "EUR", "value": "125.50",
            "kind": "observed_quote", "observed_at": binding["stored_reference_at"],
            "published_at": "2024-06-02T11:31:00Z", "evidence_sha256": preview["evidence"][0]["sha256"],
            "locator": "Synthetic source page 1", "source": "Synthetic original"},
        "method": {"method_id": "synthetic-observed-eur", "version": 1, "kind": "observed_quote",
            "timezone": "UTC", "availability_rule": "available_at_cutoff",
            "evidence_sha256": hashlib.sha256(METHOD).hexdigest()},
        "method_original": {"filename": "method.txt", "media_type": "text/plain",
                            "content_base64": base64.b64encode(METHOD).decode()},
        "actor": "Synthetic reviewer", "rationale": "Synthetic fixture only; no actual approval.",
    }


def context(workflow):
    preview, binding, _ = prepared_original(workflow)
    path = BASE + f"/previews/{preview['id']}/prices/{binding['price_id']}"
    return preview, binding, path, admission_request(preview, binding)


def prepare(workflow):
    preview, binding, path, request = context(workflow)
    report = data(workflow.client.post(path + "/admission-previews", json=request))
    return preview, binding, path, request, report


def apply_body(report):
    return {"draft_sha256": report["draft_sha256"], "acknowledge_original_verified": True,
            "acknowledge_scope_limited": True}


def test_human_price_confirmation_is_explicit_append_only_and_revocable(workflow):
    preview, binding, path, request = context(workflow)
    sources = source_snapshot(workflow)
    prices = workflow.store.list_price_points()
    decisions = workflow.store.list_review_decisions()
    report = data(workflow.client.post(path + "/admission-previews", json=request))
    assert report["status"] == "prepared" and report["can_apply"] is True, report
    assert report["assessment"]["strict_eligible"] is False
    assert report["assessment"]["reason_codes"] == ["approval_missing"]
    assert report["observation"]["captured_at"] != report["observation"]["published_at"]
    assert workflow.store.list_review_decisions() == decisions
    draft_path = path + "/admission-previews/" + report["request_id"]
    method_url = report["method_original"]["download_url"]
    assert workflow.client.get(method_url).content == METHOD
    assert data(workflow.client.get(draft_path)) == report
    assert data(workflow.client.post(path + "/admission-previews", json=request)) == report
    assert data(workflow.client.get(path + "/admissions", params={"valuation_at": request["valuation_at"]})) is None
    approved = data(workflow.client.post(draft_path + "/apply", json=apply_body(report)))
    assert approved["status"] == "human_approved" and approved["assessment"]["strict_eligible"] is True, approved
    assert approved["assessment"]["evidence_origin"] == "operator_confirmed"
    assert len(workflow.store.list_review_decisions()) == len(decisions) + 1
    assert data(workflow.client.post(draft_path + "/apply", json=apply_body(report))) == approved
    assert data(workflow.client.get(path + "/admissions", params={"valuation_at": request["valuation_at"]})) == approved
    fingerprint = PriceAdmissionService(workflow.store).state_fingerprint(request_datetime(request))
    assert fingerprint is not None
    original_decision = deepcopy(approved["decision"])
    revoke = {"draft_sha256": report["draft_sha256"], "actor": "Synthetic reviewer",
              "rationale": "Synthetic withdrawal", "acknowledge_revocation": True}
    revoked = data(workflow.client.post(path + "/admissions/" + request["request_id"] + "/revoke", json=revoke))
    assert revoked["status"] == "revoked" and revoked["assessment"]["strict_eligible"] is False
    assert revoked["decision"] == original_decision and revoked["revocation"] is not None
    assert PriceAdmissionService(workflow.store).state_fingerprint(request_datetime(request)) != fingerprint
    assert data(workflow.client.post(path + "/admissions/" + request["request_id"] + "/revoke", json=revoke)) == revoked
    assert workflow.client.post(draft_path + "/apply", json=apply_body(report)).status_code == 409
    assert workflow.store.list_price_points() == prices and source_snapshot(workflow) == sources
    assert not workflow.calls


def request_datetime(request):
    from datetime import datetime
    return datetime.fromisoformat(request["valuation_at"].replace("Z", "+00:00"))


@pytest.mark.parametrize("field", ["acknowledge_original_verified", "acknowledge_scope_limited"])
@pytest.mark.parametrize("invalid", [None, False, 0, 1, "true", []])
def test_confirmation_acknowledgements_are_never_inferred(workflow, field, invalid):
    _, _, path, request, report = prepare(workflow)
    before = workflow.store.list_review_decisions()
    body = apply_body(report)
    if invalid is None:
        body.pop(field)
    else:
        body[field] = invalid
    result = workflow.client.post(path + "/admission-previews/" + request["request_id"] + "/apply", json=body)
    assert result.status_code == 422, result.text
    assert workflow.store.list_review_decisions() == before


def test_original_change_disables_prepared_confirmation_without_repair(workflow):
    preview, _, path, request, report = prepare(workflow)
    original = workflow.service.root / "evidence" / (preview["evidence"][0]["sha256"] + ".body")
    original.chmod(0o600)
    original.write_bytes(b"synthetic replacement")
    before = workflow.store.list_review_decisions()
    draft_path = path + "/admission-previews/" + request["request_id"]
    invalid = data(workflow.client.get(draft_path))
    assert invalid["can_apply"] is False and invalid["assessment"]["strict_eligible"] is False
    assert workflow.client.post(draft_path + "/apply", json=apply_body(report)).status_code == 409
    assert workflow.store.list_review_decisions() == before and original.read_bytes() == b"synthetic replacement"
