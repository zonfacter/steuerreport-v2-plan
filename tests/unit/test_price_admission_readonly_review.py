"""Disposable native review proofs; current coordinator src, no source overlay."""
import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.historical_prices import (
    HistoricalPriceApply, HistoricalPriceQuery, ManualHistoricalPricePreviewRequest,
)
from steuerreport_v2.contracts.price_admissions import (
    PriceAdmissionApply, PriceAdmissionDraftRequest, PriceAdmissionRevoke,
)
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.contracts.valuation_runs import DivorceValuationRunReport
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain import price_admissions as admissions_module
from steuerreport_v2.domain.as_of_price_gate import AsOfPriceGateService
from steuerreport_v2.domain.divorce import DivorceEqualizationService
from steuerreport_v2.domain.historical_prices import HistoricalPriceService
from steuerreport_v2.domain.price_admissions import PriceAdmissionError, PriceAdmissionService
from steuerreport_v2.domain.valuation_runs import DivorceValuationRunService


AT = datetime(2025, 6, 13, 1, tzinfo=timezone.utc)


@pytest.fixture
def native(tmp_path, monkeypatch):
    assert Path(admissions_module.__file__).resolve().is_relative_to(
        Path(__file__).resolve().parents[2] / "src")
    store = DuckDbStore(tmp_path / "review-only-synthetic.duckdb")
    store.add_canonical_event(CanonicalEventCreate(
        source="synthetic-review", source_ref="position", event_time=AT - timedelta(minutes=15),
        event_type="transfer", asset="TOKEN000", quantity="2", account="synthetic-wallet",
    ))
    history = HistoricalPriceService(store)
    monkeypatch.setattr(history, "mappings", lambda: {
        "TOKEN000": {"asset": "TOKEN000", "coingecko_id": "synthetic-token", "defillama_id": None},
    })
    original, method = b"Synthetic quote EUR100", b"Synthetic method; limited observed EUR quote."
    query = HistoricalPriceQuery(scope="all_observed", assets=["TOKEN000"])
    plan = history.plan(query)
    preview = history.manual_preview(ManualHistoricalPricePreviewRequest.model_validate({
        "request_id": str(uuid4()), "query": query, "plan_sha256": plan["plan_sha256"],
        "asset": "TOKEN000", "price_date": AT.date(), "price_value": "100", "price_currency": "EUR",
        "priced_at": AT - timedelta(minutes=30), "price_evidence": {
            "filename": "synthetic-original.txt", "media_type": "text/plain", "source_name": "Synthetic",
            "source_observed_at": AT, "content_base64": base64.b64encode(original).decode(),
        },
    }))
    history.apply(preview["id"], HistoricalPriceApply(
        preview_sha256=preview["preview_sha256"], actor="Synthetic only",
        confirm_prices=True, confirm_recalculation=True,
    ))
    binding, = preview["price_bindings"]
    identity = {"asset": "TOKEN000", "network": "synthetic", "contract": "native", "decimals": 8}
    request = PriceAdmissionDraftRequest.model_validate({
        "request_id": str(uuid4()), "preview_sha256": preview["preview_sha256"],
        "price_fingerprint": binding["price_fingerprint"], "valuation_at": AT, "identity": identity,
        "observation": {"identity": identity, "quote_currency": "EUR", "value": "100", "kind": "observed_quote",
                        "observed_at": AT - timedelta(minutes=30), "published_at": AT - timedelta(minutes=30),
                        "evidence_sha256": hashlib.sha256(original).hexdigest(), "locator": "row 1", "source": "Synthetic"},
        "method": {"method_id": "synthetic", "version": 1, "kind": "observed_quote", "timezone": "UTC",
                   "availability_rule": "available_at_cutoff", "evidence_sha256": hashlib.sha256(method).hexdigest()},
        "method_original": {"filename": "synthetic-method.txt", "media_type": "text/plain",
                            "content_base64": base64.b64encode(method).decode()},
        "actor": "Synthetic only", "rationale": "Disposable review proof, not an actual approval.",
    })
    service = PriceAdmissionService(store)
    prepared = service.prepare(preview["id"], binding["price_id"], request)
    apply = PriceAdmissionApply(draft_sha256=prepared.draft_sha256,
                               acknowledge_original_verified=True, acknowledge_scope_limited=True)
    approved = service.apply(preview["id"], binding["price_id"], request.request_id, apply)
    assert approved.assessment.strict_eligible
    return SimpleNamespace(store=store, service=service, preview=preview, binding=binding,
                           request=request, approved=approved, apply=apply, root=tmp_path)


@pytest.mark.parametrize("operation", ["get", "repeated_apply"])
def test_scope_conflict_must_not_produce_an_individual_positive_receipt(native, operation):
    env = native
    other_request = env.request.model_copy(update={"request_id": uuid4()})
    other = env.service.prepare(env.preview["id"], env.binding["price_id"], other_request)
    env.service.revoke(env.preview["id"], env.binding["price_id"], env.request.request_id,
                       PriceAdmissionRevoke(draft_sha256=env.approved.draft_sha256, actor="Synthetic only",
                                            rationale="Synthetic transition", acknowledge_revocation=True))
    env.service.apply(env.preview["id"], env.binding["price_id"], other_request.request_id,
                      PriceAdmissionApply(draft_sha256=other.draft_sha256,
                                          acknowledge_original_verified=True, acknowledge_scope_limited=True))
    # Explicit synthetic DB-corruption fixture: lose only the first revocation.
    # Both main decisions were legitimately emitted by the native service.
    with env.store.connect() as con:
        con.execute("delete from review_decisions where id=?", ["price-time-revocation:" + str(env.request.request_id)])
    with pytest.raises(PriceAdmissionError, match="^price_admission_ambiguous$"):
        env.service.read_admission(env.preview["id"], env.binding["price_id"], AT)
    try:
        result = (env.service.get(env.preview["id"], env.binding["price_id"], env.request.request_id)
                  if operation == "get" else env.service.apply(
                      env.preview["id"], env.binding["price_id"], env.request.request_id, env.apply))
    except PriceAdmissionError:
        return
    assert not result.assessment.strict_eligible, f"{operation}: positive receipt despite two active decisions"


def test_preferred_new_price_makes_the_previous_run_price_gate_stale(native):
    env = native
    later = AT + timedelta(minutes=1)
    summary = DivorceEqualizationService(env.store).summary(cutoff_at=AT, valuation_at=later)
    assert summary.cutoff_price_gate.strict_ready
    root = env.root / "synthetic-run"
    run_id = "valuation-synthetic-review"
    path = root / run_id / "valuation_run.json"
    latest = root / "latest_valuation_gate.json"
    report = DivorceValuationRunReport(
        run_id=run_id, generated_at=AT, status="blocked", strict_ready=False,
        cutoff_at=AT, valuation_at=later, materiality_threshold_eur="1", material_delta_threshold_eur="0.01",
        cutoff_price_gate=deepcopy(summary.cutoff_price_gate), valuation_price_gate=deepcopy(summary.valuation_price_gate),
        semantic_sha256="c" * 64, artifact_path=str(path), latest_artifact_path=str(latest),
        summary=summary, methodology="Synthetic archive with actually assessed price gates.",
    )
    path.parent.mkdir(parents=True)
    raw = report.model_dump_json().encode()
    path.write_bytes(raw)
    latest.write_bytes(raw)
    service = DivorceValuationRunService(env.store, artifact_root=root)
    assert service.has_current_price_time_policy(report, store=env.store)
    previous_state = env.service.state_fingerprint(AT)
    other = env.store.add_price_point(PricePointCreate(
        asset="TOKEN000", price_eur="101", priced_at=AT - timedelta(seconds=1), source="synthetic-new-selected",
    ))
    current = AsOfPriceGateService(env.store).report(as_of=AT)
    assert not current.strict_ready
    assert current.candidates[0].current_price_eur == 101
    assert current.candidates[0].price_admission is None
    assert other.price_id != env.binding["price_id"]
    assert env.service.state_fingerprint(AT) == previous_state
    assert path.read_bytes() == latest.read_bytes() == raw
    assert not service.has_current_price_time_policy(report, store=env.store), "archived admitted price is no longer the selected price"
