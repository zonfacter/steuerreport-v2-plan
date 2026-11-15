"""One native failed-scope cache probe; original red references stay unchanged."""
from uuid import uuid4

import pytest

from test_price_admission_readonly_review import AT, native as native

from steuerreport_v2.contracts.price_admissions import PriceAdmissionApply, PriceAdmissionRevoke
from steuerreport_v2.domain.price_admissions import PriceAdmissionError


def test_failed_scope_is_validated_once_for_two_main_records(native, monkeypatch):
    env = native
    other_request = env.request.model_copy(update={"request_id": uuid4()})
    other = env.service.prepare(env.preview["id"], env.binding["price_id"], other_request)
    env.service.revoke(env.preview["id"], env.binding["price_id"], env.request.request_id,
                       PriceAdmissionRevoke(draft_sha256=env.approved.draft_sha256, actor="Synthetic only",
                                            rationale="Synthetic transition", acknowledge_revocation=True))
    env.service.apply(env.preview["id"], env.binding["price_id"], other_request.request_id,
                      PriceAdmissionApply(draft_sha256=other.draft_sha256,
                                          acknowledge_original_verified=True, acknowledge_scope_limited=True))
    intact = env.service.state_fingerprint(AT)
    assert intact is not None
    # Synthetic evidence loss, not an attempt to rewrite/rebind any manifest.
    draft = env.service.reader.history.root / "admissions" / str(other_request.request_id) / "draft.json"
    draft.unlink()
    actual = env.service._scope_docs
    calls = 0

    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return actual(*args, **kwargs)

    monkeypatch.setattr(env.service, "_scope_docs", counted)
    broken = env.service.state_fingerprint(AT)
    assert broken is not None and broken != intact
    assert calls == 1
    assert not draft.exists()
    with pytest.raises(PriceAdmissionError):
        env.service.read_admission(env.preview["id"], env.binding["price_id"], AT)
    assert not draft.exists()
