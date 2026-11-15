"""Begrenzte Snapshot-Lesearbeit ohne langlebigen Belegcache."""
from uuid import uuid4

from test_price_admission_readonly_review import AT, native as native
from steuerreport_v2.contracts.price_admissions import PriceAdmissionApply, PriceAdmissionRevoke


def test_fingerprint_loads_reserved_records_once_even_with_retired_scope_history(native, monkeypatch):
    service = native.service
    other = native.request.model_copy(update={"request_id": uuid4()})
    draft = service.prepare(native.preview["id"], native.binding["price_id"], other)
    service.revoke(native.preview["id"], native.binding["price_id"], native.request.request_id,
        PriceAdmissionRevoke(draft_sha256=native.approved.draft_sha256, actor="Synthetic only",
            rationale="Synthetic retired history", acknowledge_revocation=True))
    service.apply(native.preview["id"], native.binding["price_id"], other.request_id,
        PriceAdmissionApply(draft_sha256=draft.draft_sha256,
            acknowledge_original_verified=True, acknowledge_scope_limited=True))
    reads = []
    original = service._records

    def counted(con):
        reads.append(con)
        return original(con)

    monkeypatch.setattr(service, "_records", counted)
    first = service.state_fingerprint(AT)
    assert len(reads) == 1
    second = service.state_fingerprint(AT)
    assert len(reads) == 2  # New request, new snapshot; no stale cross-request cache.
    assert first == second and first is not None
