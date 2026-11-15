"""Small native coordinator fix checks; the original red file stays unchanged."""
from copy import deepcopy
from datetime import timedelta

from test_price_admission_readonly_review import AT, native as native

from steuerreport_v2.contracts.price_admissions import PriceAdmissionApply, PriceAdmissionRevoke
from steuerreport_v2.contracts.valuation_runs import DivorceValuationRunReport
from steuerreport_v2.domain.divorce import DivorceEqualizationService
from steuerreport_v2.domain.valuation_runs import DivorceValuationRunService

from uuid import uuid4


def test_fingerprint_reads_records_once_with_two_main_records_and_a_revocation(native, monkeypatch):
    env = native
    other_request = env.request.model_copy(update={"request_id": uuid4()})
    other = env.service.prepare(env.preview["id"], env.binding["price_id"], other_request)
    env.service.revoke(env.preview["id"], env.binding["price_id"], env.request.request_id,
                       PriceAdmissionRevoke(draft_sha256=env.approved.draft_sha256, actor="Synthetic only",
                                            rationale="Synthetic transition", acknowledge_revocation=True))
    env.service.apply(env.preview["id"], env.binding["price_id"], other_request.request_id,
                      PriceAdmissionApply(draft_sha256=other.draft_sha256,
                                          acknowledge_original_verified=True, acknowledge_scope_limited=True))
    actual = env.service._records
    calls = 0

    def counted(con):
        nonlocal calls
        calls += 1
        records = actual(con)
        assert len(records) == 3
        return records

    monkeypatch.setattr(env.service, "_records", counted)
    assert env.service.state_fingerprint(AT) is not None
    assert calls == 1


def test_freshness_validates_nested_gate_fields_not_just_their_markers(native):
    env = native
    later = AT + timedelta(minutes=1)
    summary = DivorceEqualizationService(env.store).summary(cutoff_at=AT, valuation_at=later)
    report = DivorceValuationRunReport(
        run_id="valuation-synthetic-nested-review", generated_at=AT, status="blocked", strict_ready=False,
        cutoff_at=AT, valuation_at=later, materiality_threshold_eur="1", material_delta_threshold_eur="0.01",
        cutoff_price_gate=deepcopy(summary.cutoff_price_gate), valuation_price_gate=deepcopy(summary.valuation_price_gate),
        semantic_sha256="c" * 64, artifact_path="synthetic.json", latest_artifact_path="synthetic-latest.json",
        summary=summary, methodology="Synthetic independent gate-copy consistency check.",
    )
    assert not report.valuation_price_gate.strict_ready
    assert DivorceValuationRunService.has_current_price_time_policy(report, store=env.store)
    report.summary.valuation_price_gate = report.summary.valuation_price_gate.model_copy(update={
        "strict_ready": True, "status": "strict_ready", "unverified_price_time_count": 0,
    })
    assert not DivorceValuationRunService.has_current_price_time_policy(report, store=env.store)
