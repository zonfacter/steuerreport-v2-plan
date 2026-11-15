"""Synthetische Gate-/Run-Bruecke mit unabhaengigen Resolver-Sollzustaenden.

Die Admission-Implementierung entsteht getrennt beim Koordinator und wird bis
zur Integration lesend eingebunden. Resolver-Doubles sind explizit; native
Proben verwenden den echten Dienst. Keine Formeln dienen als Erwartungsoracle.
"""
# ruff: noqa: E402 -- install the test-only source overlay before product imports
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import base64
import hashlib
import importlib.abc
import importlib.util
import json
from pathlib import Path
import socket
import sys
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

import steuerreport_v2 as _package


# With coordinator PYTHONPATH, overlay only this agent's seven bridge files.
# After integration both roots are equal and the normal importer is untouched.
_agent_src = Path(__file__).resolve().parents[2] / "src"
if _agent_src != Path(_package.__file__).resolve().parents[1]:
    _bridge_paths = {
        "steuerreport_v2." + name.replace("/", "."): _agent_src / "steuerreport_v2" / (name + ".py")
        for name in ("contracts/portfolio", "contracts/divorce", "contracts/prices", "domain/portfolio",
                     "domain/divorce", "domain/as_of_price_gate", "domain/valuation_runs")
    }

    class _BridgeFinder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path, target=None):
            source = _bridge_paths.get(fullname)
            return importlib.util.spec_from_file_location(fullname, source) if source is not None else None

    sys.meta_path.insert(0, _BridgeFinder())

from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.historical_prices import (
    HistoricalPriceApply, HistoricalPriceQuery, ManualHistoricalPricePreviewRequest,
)
from steuerreport_v2.contracts.portfolio import PortfolioPosition
from steuerreport_v2.contracts.price_admissions import (
    PriceAdmissionApply, PriceAdmissionDraftRequest, PriceAdmissionReport, PriceAdmissionRevoke,
)
from steuerreport_v2.contracts.price_evidence import (
    PriceEvidenceAdmission, PriceEvidenceFx, PriceEvidenceIdentity, PriceEvidenceMethod, PriceEvidenceObservation,
)
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.contracts.review import ReviewDecision
from steuerreport_v2.contracts.valuation_runs import DivorceValuationRunReport, DivorceValuationRunRequest
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain import as_of_price_gate as asof_module
from steuerreport_v2.domain import divorce as divorce_module
from steuerreport_v2.domain import valuation_runs as runs_module
from steuerreport_v2.domain.as_of_price_gate import AsOfPriceGateService
from steuerreport_v2.domain.divorce import DivorceEqualizationService
from steuerreport_v2.domain.historical_prices import HistoricalPriceService
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.price_admissions import PriceAdmissionError, PriceAdmissionService
from steuerreport_v2.domain.valuation_runs import DivorceValuationRunService
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


AT = datetime(2025, 6, 13, 1, tzinfo=timezone.utc)
LATER = AT + timedelta(days=1)
REFERENCE = AT - timedelta(minutes=30)
STATE = "a" * 64
CHANGED = "b" * 64


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class ResolverError(RuntimeError):
    code = "synthetic_admission_unavailable"
    http_status = 503


class ResolverOracle:
    def __init__(self):
        self.answers = {}
        self.expected = {}
        self.states = {}
        self.calls = []
        self.state_calls = []
        self.error = None
        self.state_error = None
        self.state_sequence = []

    def assess_selected(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        key = (str(kwargs["price_id"]), _utc(kwargs["valuation_at"]))
        if key in self.expected:
            assert kwargs == self.expected[key]
        return self.answers.get(key)

    def state_fingerprint(self, valuation_at):
        self.state_calls.append(_utc(valuation_at))
        if self.state_error is not None:
            raise self.state_error
        if self.state_sequence:
            return self.state_sequence.pop(0)
        return self.states.get(_utc(valuation_at))


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    oracle = ResolverOracle()
    for module in (asof_module, divorce_module, runs_module):
        monkeypatch.setattr(module, "PriceAdmissionService", lambda store: oracle)
    monkeypatch.setattr(AsOfPriceGateService, "_provider_sources", staticmethod(lambda path: {}))

    def forbidden(*args, **kwargs):
        pytest.fail("Gate reading attempted network/provider/pipeline activity")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(asof_module, "managed_client", forbidden)
    for key in ("STEUERREPORT_SPARKASSE_CAMT_DIR", "STEUERREPORT_SPARKASSE_STATEMENT_DIR",
                "STEUERREPORT_TRADE_REPUBLIC_DOCUMENT_ROOT", "STEUERREPORT_INHERITANCE_DOCUMENT_ROOT"):
        monkeypatch.setenv(key, str(tmp_path / "empty-documents"))
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    store.add_canonical_event(CanonicalEventCreate(
        source="synthetic-gate", source_ref="position", event_time=AT - timedelta(days=1),
        event_type="transfer", account="synthetic-wallet", asset="BTC", quantity=Decimal("2"),
    ))
    point = store.add_price_point(PricePointCreate(
        asset="BTC", price_eur=Decimal("100"), priced_at=REFERENCE, source="synthetic:original",
    ))
    BalanceLedgerBuilder(store).rebuild()
    position = PortfolioService(store).as_of_snapshot(AT).positions[0]
    return SimpleNamespace(store=store, oracle=oracle, point=point, position=position, root=tmp_path)


def _approval(position, *, at=AT, status="human_approved"):
    identity = PriceEvidenceIdentity(asset=position.asset, network="bitcoin", contract="native", decimals=8)
    observation = PriceEvidenceObservation(
        identity=identity, quote_currency="EUR", value=position.price_eur, kind="observed_quote",
        observed_at=_utc(position.priced_at), published_at=_utc(position.priced_at), captured_at=LATER,
        evidence_sha256="1" * 64, locator="synthetic page 1", source="synthetic original",
    )
    method = PriceEvidenceMethod(method_id="synthetic-observed", version=1, kind="observed_quote",
                                 timezone="UTC", availability_rule="available_at_cutoff", evidence_sha256="2" * 64)
    positive = status == "human_approved"
    decision = ReviewDecision(
        decision_id="price-time-admission:synthetic", decision_type="stichtag_price_time_admission",
        scope="synthetic-only", title="Synthetic decision", actor="Synthetic test actor",
        rationale="Synthetic limited admission, no actual approval.", created_at=LATER,
    ) if positive else None
    assessment = PriceEvidenceAdmission(
        status="human_approved" if positive else "not_approved", strict_eligible=positive,
        binding_sha256="3" * 64, decision_id=decision.decision_id if decision else None,
        reason_codes=[] if positive else ["approval_missing"], original_integrity_verified=True,
        evidence_origin="operator_confirmed" if positive else "unverified",
    )
    original = {"sha256": "1" * 64, "byte_length": 17, "download_url": "/synthetic-original"}
    return PriceAdmissionReport(
        status=status, request_id=UUID(int=1), preview_id=UUID(int=2), price_id=position.price_id,
        draft_sha256="4" * 64, price_fingerprint="5" * 64, validation_policy_sha256="7" * 64,
        created_at=LATER, valuation_at=at,
        identity=identity, observation=observation, method=method, actor="Synthetic test actor",
        rationale="Synthetic limited admission.", assessment=assessment,
        can_apply=status == "prepared", decision=decision,
        method_original={**original, "sha256": "2" * 64}, originals=[original],
    )


def _allow(sandbox, *, at=AT, report=None):
    report = report or _approval(sandbox.position, at=at)
    key = (sandbox.point.price_id, at)
    sandbox.oracle.answers[key] = report
    sandbox.oracle.states[at] = STATE
    sandbox.oracle.expected[key] = {
        "price_id": sandbox.point.price_id, "valuation_at": at, "asset": "BTC",
        "price_eur": Decimal("100"), "price_source": "synthetic:original", "priced_at": REFERENCE,
    }
    return report


def _gate(sandbox, positions=None, at=AT):
    return DivorceEqualizationService(sandbox.store)._valuation_gate(
        [sandbox.position] if positions is None else positions, at, Decimal("1"),
    )


def _financial_rows(store):
    with store.connect() as con:
        return {table: con.execute(f"select * from {table} order by all").fetchall()
                for table in ("canonical_events", "price_ledger", "balance_ledger", "flow_ledger",
                              "tax_lots", "tax_lines", "review_decisions")}


def test_snapshot_adds_only_the_actual_chosen_price_id(sandbox):
    snapshot = PortfolioService(sandbox.store).as_of_snapshot(AT)
    assert snapshot.positions[0].price_id == sandbox.point.price_id
    assert snapshot.total_value_eur == Decimal("200")
    sandbox.store.add_canonical_event(CanonicalEventCreate(
        source="synthetic-gate", source_ref="missing", event_time=AT - timedelta(days=1),
        event_type="transfer", account="synthetic-wallet", asset="MISSING", quantity=Decimal("1"),
    ))
    BalanceLedgerBuilder(sandbox.store).rebuild()
    positions = {row.asset: row for row in PortfolioService(sandbox.store).as_of_snapshot(AT).positions}
    assert positions["MISSING"].price_id is None


def test_no_admission_keeps_legacy_unverified_and_policy_one(sandbox):
    gate = _gate(sandbox)
    assert not gate.strict_ready and gate.unverified_price_time_count == 1
    assert gate.accepted_price_time_count == 0 and gate.price_admission_state_sha256 is None
    assert gate.price_time_policy_id == "stichtag-temporal-evidence" and gate.price_time_policy_version == 1


def test_bound_human_admission_is_additive_and_financially_read_only(sandbox):
    report = _allow(sandbox)
    before = _financial_rows(sandbox.store)
    gate = _gate(sandbox)
    result = AsOfPriceGateService(sandbox.store).report(as_of=AT)
    candidate, = result.candidates
    assert gate.strict_ready and result.strict_ready
    assert gate.accepted_price_time_count == result.gate.accepted_price_time_count == 1
    assert gate.price_admission_state_sha256 == STATE
    assert candidate.price_admission == report
    assert candidate.price_admission.assessment.evidence_origin == "operator_confirmed"
    assert candidate.price_time.status == "unverified_time" and not candidate.price_time.strict_eligible
    assert candidate.price_time.policy_version == gate.price_time_policy_version == 1
    assert candidate.status == "satisfied" and result.requirements_count == result.time_review_count == 0
    assert result.gate.unverified_price_time_count == 0
    assert _financial_rows(sandbox.store) == before


@pytest.mark.parametrize("kind", ["usd_per_eur", "eur_per_usd", "daily_mean", "daily_fixed_time", "daily_close"])
def test_documented_method_facts_are_separate_from_legacy_diagnosis(sandbox, kind):
    report = _approval(sandbox.position)
    if kind in {"usd_per_eur", "eur_per_usd"}:
        fx = PriceEvidenceFx(
            base="EUR" if kind == "usd_per_eur" else "USD",
            quote="USD" if kind == "usd_per_eur" else "EUR",
            rate=Decimal("1.25") if kind == "usd_per_eur" else Decimal("0.8"),
            reference_at=REFERENCE, published_at=REFERENCE, captured_at=LATER,
            evidence_sha256="6" * 64, locator="synthetic FX row", source="synthetic FX original",
        )
        observation = report.observation.model_copy(update={"quote_currency": "USD", "value": Decimal("125"), "fx": fx})
        report = report.model_copy(update={"observation": observation})
    else:
        start = AT.replace(hour=0, minute=0)
        observation = report.observation.model_copy(update={
            "kind": "daily_reference", "observed_at": None, "period_start": start,
            "period_end": start + timedelta(days=1), "published_at": start + timedelta(days=1),
        })
        data = report.method.model_dump()
        data.update(kind="daily_reference", daily_statistic=kind, daily_time="00:30:00" if kind == "daily_fixed_time" else None,
                    availability_rule="retrospective_daily_reference")
        report = report.model_copy(update={"observation": observation, "method": PriceEvidenceMethod.model_validate(data)})
    _allow(sandbox, report=report)
    result = AsOfPriceGateService(sandbox.store).report(as_of=AT)
    candidate, = result.candidates
    assert result.strict_ready and result.gate.accepted_price_time_count == 1
    assert candidate.price_admission.observation == report.observation
    assert candidate.price_admission.method == report.method
    assert candidate.price_time.observed_at is candidate.price_time.period_start is None
    assert candidate.price_time.price_published_at is candidate.price_time.fx_published_at is None
    assert candidate.price_time.policy_version == 1 and not candidate.price_time.strict_eligible


@pytest.mark.parametrize("status", ["prepared", "blocked", "revoked", "rejected"])
def test_nonpositive_admission_status_never_opens_a_gate(sandbox, status):
    report = _approval(sandbox.position, status=status)
    _allow(sandbox, report=report)
    gate = _gate(sandbox)
    result = AsOfPriceGateService(sandbox.store).report(as_of=AT)
    assert not gate.strict_ready and not result.strict_ready
    assert gate.accepted_price_time_count == 0 and gate.unverified_price_time_count == 1
    assert result.candidates[0].price_admission == report
    assert result.candidates[0].status == "time_review"


@pytest.mark.parametrize("changed", ["id", "cutoff"])
def test_resolver_report_must_match_id_and_exact_cutoff(sandbox, changed):
    report = _approval(sandbox.position)
    report = report.model_copy(update={"price_id": uuid4()} if changed == "id" else {
        "valuation_at": AT + timedelta(microseconds=1),
    })
    _allow(sandbox, report=report)
    assert not _gate(sandbox).strict_ready
    assert not AsOfPriceGateService(sandbox.store).report(as_of=AT).strict_ready


def test_same_price_at_another_cutoff_has_no_implicit_admission(sandbox):
    _allow(sandbox)
    gate = _gate(sandbox, at=AT + timedelta(microseconds=1))
    assert not gate.strict_ready and gate.accepted_price_time_count == 0


def test_price_id_is_never_guessed_from_a_matching_value_or_label(sandbox):
    _allow(sandbox)
    position = sandbox.position.model_copy(update={"price_id": None})
    gate = _gate(sandbox, [position])
    assert not gate.strict_ready and gate.accepted_price_time_count == 0
    assert sandbox.oracle.calls == []


def test_admission_never_changes_the_existing_price_selection(sandbox):
    _allow(sandbox)
    newer = sandbox.store.add_price_point(PricePointCreate(
        asset="BTC", price_eur=Decimal("101"), priced_at=AT - timedelta(seconds=1), source="synthetic:newer",
    ))
    snapshot = PortfolioService(sandbox.store).as_of_snapshot(AT)
    assert snapshot.positions[0].price_id == newer.price_id
    result = AsOfPriceGateService(sandbox.store).report(as_of=AT)
    assert not result.strict_ready
    assert result.candidates[0].current_price_eur == Decimal("101")
    assert result.candidates[0].price_admission is None


@pytest.mark.parametrize("kind", ["prior_day", "stale", "derived", "future", "nonpositive"])
def test_admission_cannot_replace_price_selection_guards(sandbox, kind):
    changes = {
        "prior_day": {"priced_at": AT - timedelta(days=1)},
        "stale": {"priced_at": AT - timedelta(days=3)},
        "derived": {"price_source": "derived:event_quote"},
        "future": {"priced_at": AT + timedelta(seconds=1)},
        "nonpositive": {"price_eur": Decimal("0")},
    }[kind]
    position = sandbox.position.model_copy(update=changes)
    report = _approval(position) if kind != "nonpositive" else _approval(sandbox.position)
    _allow(sandbox, report=report)
    sandbox.oracle.expected.clear()
    assert not _gate(sandbox, [position]).strict_ready


def test_price_admission_does_not_replace_independent_token_risk_review(sandbox, monkeypatch):
    _allow(sandbox)
    service = DivorceEqualizationService(sandbox.store)
    monkeypatch.setattr(service.token_valuation_service, "assessment", lambda *args: SimpleNamespace(
        review_required=True, accepted_decision=None,
    ))
    gate = service._valuation_gate([sandbox.position], AT, Decimal("1"))
    assert not gate.strict_ready
    assert gate.accepted_price_time_count == 1 and gate.review_asset_count == 1
    assert gate.unverified_price_time_count == 0


def test_counts_are_positions_not_asset_count(sandbox):
    _allow(sandbox)
    other = sandbox.position.model_copy(update={"account": "synthetic-second-wallet"})
    gate = _gate(sandbox, [sandbox.position, other])
    assert gate.strict_ready and gate.accepted_price_time_count == 2
    assert gate.same_day_price_count == gate.material_positions_count == 2


def test_true_eur_identity_does_not_need_a_price_admission(sandbox):
    position = PortfolioPosition(account="synthetic", asset="EUR", quantity=Decimal("10"),
                                 price_id="synthetic:EUR:EUR", price_eur=Decimal("1"), value_eur=Decimal("10"),
                                 price_source="fiat:EUR", priced_at=datetime(1970, 1, 1, tzinfo=timezone.utc))
    assert _gate(sandbox, [position]).strict_ready
    assert sandbox.oracle.calls == []


@pytest.mark.parametrize("surface", ["gate", "asof"])
@pytest.mark.parametrize("failure", ["assess", "state"])
def test_resolver_errors_are_not_absence_or_positive_results(sandbox, surface, failure):
    _allow(sandbox)
    if failure == "assess":
        sandbox.oracle.error = ResolverError("synthetic_admission_unavailable")
    else:
        sandbox.oracle.state_error = ResolverError("synthetic_admission_unavailable")
    with pytest.raises(ResolverError):
        _gate(sandbox) if surface == "gate" else AsOfPriceGateService(sandbox.store).report(as_of=AT)


def test_state_change_during_gate_evaluation_is_not_a_positive_snapshot(sandbox):
    _allow(sandbox)
    sandbox.oracle.state_sequence = [STATE, CHANGED]
    with pytest.raises(RuntimeError, match="^price_admission_state_changed$") as error:
        _gate(sandbox)
    assert isinstance(error.value, PriceAdmissionError)
    assert error.value.code == "price_admission_state_changed" and error.value.http_status == 409
    sandbox.oracle.state_sequence = [STATE, STATE, CHANGED]
    with pytest.raises(PriceAdmissionError, match="^price_admission_state_changed$") as error:
        AsOfPriceGateService(sandbox.store).report(as_of=AT)
    assert error.value.code == "price_admission_state_changed" and error.value.http_status == 409


def test_positive_resolver_without_any_state_record_is_rejected(sandbox):
    _allow(sandbox)
    sandbox.oracle.states.clear()
    with pytest.raises(RuntimeError, match="^price_admission_state_changed$") as error:
        _gate(sandbox)
    assert isinstance(error.value, PriceAdmissionError)
    assert error.value.code == "price_admission_state_changed" and error.value.http_status == 409


def _archive(sandbox, *, admission=False):
    if admission:
        _allow(sandbox)
        sandbox.oracle.states[LATER] = CHANGED
    summary = DivorceEqualizationService(sandbox.store).summary(cutoff_at=AT, valuation_at=LATER)
    if admission:
        assert summary.cutoff_price_gate.price_admission_state_sha256 == STATE
        assert summary.valuation_price_gate.price_admission_state_sha256 == CHANGED
    root = sandbox.root / "run-archives"
    run_id = "valuation-synthetic-price-admissions"
    path = root / run_id / "valuation_run.json"
    latest = root / "latest_valuation_gate.json"
    report = DivorceValuationRunReport(
        run_id=run_id, generated_at=LATER, status="blocked", strict_ready=False,
        cutoff_at=AT, valuation_at=LATER, materiality_threshold_eur=Decimal("1"),
        material_delta_threshold_eur=Decimal("0.01"), cutoff_price_gate=summary.cutoff_price_gate,
        valuation_price_gate=summary.valuation_price_gate, semantic_sha256="c" * 64,
        artifact_path=str(path), latest_artifact_path=str(latest), summary=summary,
        methodology="Synthetic archive, no actual admission or overall release.",
    )
    document = report.model_dump(mode="json")
    if not admission:
        for container in (document, document["summary"]):
            for key in ("cutoff_price_gate", "valuation_price_gate"):
                container[key].pop("price_admission_state_sha256")
                container[key].pop("accepted_price_time_count")
        report = DivorceValuationRunReport.model_validate(document)
    path.parent.mkdir(parents=True)
    content = json.dumps(document, sort_keys=True).encode()
    path.write_bytes(content)
    latest.write_bytes(content)
    service = DivorceValuationRunService(sandbox.store, artifact_root=root,
                                        wallet_fifo_artifact_root=sandbox.root / "unused-fifo")
    return report, service, path, latest, content


def test_legacy_matching_v1_run_without_admissions_remains_current_and_unchanged(sandbox):
    report, service, path, latest, content = _archive(sandbox)
    assert service.has_current_price_time_policy(report)
    assert service.has_current_price_time_policy(report, store=sandbox.store)
    assert service.latest() is not None and service.get(report.run_id) is not None
    assert path.read_bytes() == latest.read_bytes() == content


def test_new_run_has_four_independent_cutoff_markers_and_requires_store_for_freshness(sandbox):
    report, service, path, latest, content = _archive(sandbox, admission=True)
    assert report.cutoff_price_gate.price_admission_state_sha256 == report.summary.cutoff_price_gate.price_admission_state_sha256 == STATE
    assert report.valuation_price_gate.price_admission_state_sha256 == report.summary.valuation_price_gate.price_admission_state_sha256 == CHANGED
    assert not service.has_current_price_time_policy(report)
    assert service.has_current_price_time_policy(report, store=sandbox.store)
    assert service.latest() is not None
    assert path.read_bytes() == latest.read_bytes() == content


@pytest.mark.parametrize("change", ["revoked", "new_decision", "lost_original", "changed_price", "lost_record", "corrupt_record"])
@pytest.mark.parametrize("cutoff", [AT, LATER])
def test_live_admission_changes_make_current_run_stale_but_never_rewrite_archive(sandbox, change, cutoff):
    report, service, path, latest, content = _archive(sandbox, admission=True)
    if change in {"lost_original", "corrupt_record"}:
        sandbox.oracle.state_error = ResolverError("synthetic_admission_unavailable")
    elif change == "lost_record":
        sandbox.oracle.states.pop(cutoff)
    else:
        sandbox.oracle.states[cutoff] = "f" * 64
    assert not service.has_current_price_time_policy(report, store=sandbox.store)
    assert service.latest() is None
    assert service.latest(require_current_policy=False) is not None
    assert service.get(report.run_id) is not None
    assert path.read_bytes() == latest.read_bytes() == content


@pytest.mark.parametrize("nested,key", [(False, "cutoff_price_gate"), (False, "valuation_price_gate"),
                                         (True, "cutoff_price_gate"), (True, "valuation_price_gate")])
def test_each_archived_gate_copy_participates_in_freshness(sandbox, nested, key):
    report, service, *_ = _archive(sandbox, admission=True)
    target = report.summary if nested else report
    # Replace, do not mutate a possibly shared original model instance.
    setattr(target, key, getattr(target, key).model_copy(update={"price_admission_state_sha256": "e" * 64}))
    assert not service.has_current_price_time_policy(report, store=sandbox.store)


def test_admission_addition_invalidates_an_old_markerless_run(sandbox):
    report, service, *_ = _archive(sandbox)
    sandbox.oracle.states[AT] = STATE
    assert not service.has_current_price_time_policy(report, store=sandbox.store)
    assert service.latest() is None


def test_positive_accepted_count_requires_nonempty_state(sandbox):
    report, service, *_ = _archive(sandbox)
    for target in (report, report.summary):
        target.cutoff_price_gate = target.cutoff_price_gate.model_copy(update={"accepted_price_time_count": 1})
    assert not service.has_current_price_time_policy(report)
    assert not service.has_current_price_time_policy(report, store=sandbox.store)


def test_actual_run_serializes_both_cutoffs_into_every_gate_copy(sandbox):
    _allow(sandbox)
    sandbox.oracle.states[LATER] = CHANGED
    service = DivorceValuationRunService(sandbox.store, artifact_root=sandbox.root / "actual-runs",
                                        wallet_fifo_artifact_root=sandbox.root / "actual-fifo")
    before = _financial_rows(sandbox.store)
    report = service.run(DivorceValuationRunRequest(cutoff_at=AT, valuation_at=LATER))
    assert report.cutoff_price_gate.price_admission_state_sha256 == report.summary.cutoff_price_gate.price_admission_state_sha256 == STATE
    assert report.valuation_price_gate.price_admission_state_sha256 == report.summary.valuation_price_gate.price_admission_state_sha256 == CHANGED
    assert report.cutoff_price_gate.price_time_policy_version == report.valuation_price_gate.price_time_policy_version == 1
    assert report.cutoff_price_gate.accepted_price_time_count == 1
    assert not report.strict_ready  # The other independent source/FIFO/legal gates remain unapproved.
    assert _financial_rows(sandbox.store) == before
    path = service.artifact_root / report.run_id / "valuation_run.json"
    gates = json.loads((path.parent / "price_gates.json").read_bytes())
    assert gates["cutoff"]["price_admission_state_sha256"] == STATE
    assert gates["valuation"]["price_admission_state_sha256"] == CHANGED


@pytest.fixture
def native_admission(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Native synthetic admission must not call providers or network")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    for key in ("STEUERREPORT_SPARKASSE_CAMT_DIR", "STEUERREPORT_SPARKASSE_STATEMENT_DIR",
                "STEUERREPORT_TRADE_REPUBLIC_DOCUMENT_ROOT", "STEUERREPORT_INHERITANCE_DOCUMENT_ROOT"):
        monkeypatch.setenv(key, str(tmp_path / "empty-documents"))
    store = DuckDbStore(tmp_path / "native-synthetic.duckdb")
    store.add_canonical_event(CanonicalEventCreate(
        source="synthetic-native", source_ref="position", event_time=AT - timedelta(minutes=15),
        event_type="transfer", account="synthetic-wallet", asset="BTC", quantity=Decimal("2"),
    ))
    history = HistoricalPriceService(store)
    monkeypatch.setattr(history, "mappings", lambda: {
        "BTC": {"asset": "BTC", "coingecko_id": "synthetic-bitcoin", "defillama_id": None},
    })
    original = b"Synthetic BTC original: EUR100 at 2025-06-13T00:30Z"
    sha = hashlib.sha256(original).hexdigest()
    query = HistoricalPriceQuery(scope="all_observed", assets=["BTC"])
    planned = history.plan(query)
    preview = history.manual_preview(ManualHistoricalPricePreviewRequest.model_validate({
        "request_id": str(uuid4()), "query": query, "plan_sha256": planned["plan_sha256"],
        "asset": "BTC", "price_date": AT.date(), "price_value": "100", "price_currency": "EUR",
        "priced_at": REFERENCE, "price_evidence": {
            "filename": "synthetic-price.txt", "media_type": "text/plain", "source_name": "Synthetic original",
            "source_reference": "synthetic row 1", "source_observed_at": AT,
            "content_base64": base64.b64encode(original).decode(),
        },
    }))
    history.apply(preview["id"], HistoricalPriceApply(
        preview_sha256=preview["preview_sha256"], actor="Synthetic test only",
        confirm_prices=True, confirm_recalculation=True,
    ))
    binding, = preview["price_bindings"]
    method_bytes = b"Synthetic observed EUR quote, available at cutoff; no overall release."
    method_sha = hashlib.sha256(method_bytes).hexdigest()
    identity = PriceEvidenceIdentity(asset="BTC", network="bitcoin", contract="native", decimals=8)
    request = PriceAdmissionDraftRequest.model_validate({
        "request_id": str(uuid4()), "preview_sha256": preview["preview_sha256"],
        "price_fingerprint": binding["price_fingerprint"], "valuation_at": AT, "identity": identity,
        "observation": {"identity": identity, "quote_currency": "EUR", "value": "100", "kind": "observed_quote",
                        "observed_at": REFERENCE, "published_at": REFERENCE, "evidence_sha256": sha,
                        "locator": "synthetic row 1", "source": "Synthetic original"},
        "method": {"method_id": "synthetic-observed-available", "version": 1, "kind": "observed_quote",
                   "timezone": "UTC", "availability_rule": "available_at_cutoff", "evidence_sha256": method_sha},
        "method_original": {"filename": "synthetic-method.txt", "media_type": "text/plain",
                            "content_base64": base64.b64encode(method_bytes).decode()},
        "actor": "Synthetic test only", "rationale": "Synthetic limited method confirmation, not a real review.",
    })
    service = PriceAdmissionService(store)
    prepared = service.prepare(preview["id"], binding["price_id"], request)
    assert prepared.status == "prepared" and prepared.can_apply and not prepared.assessment.strict_eligible
    assert not AsOfPriceGateService(store).report(as_of=AT).strict_ready
    approved = service.apply(preview["id"], binding["price_id"], request.request_id, PriceAdmissionApply(
        draft_sha256=prepared.draft_sha256, acknowledge_original_verified=True, acknowledge_scope_limited=True,
    ))
    assert approved.status == "human_approved" and approved.assessment.strict_eligible
    return SimpleNamespace(store=store, service=service, history=history, approved=approved,
                           root=tmp_path, sha=sha, method_sha=method_sha, preview=preview)


def test_native_import_admission_and_gate_remain_separate_from_legacy_and_other_run_gates(native_admission):
    fixture = native_admission
    before = _financial_rows(fixture.store)
    result = AsOfPriceGateService(fixture.store).report(as_of=AT)
    candidate, = result.candidates
    assert result.strict_ready and result.gate.accepted_price_time_count == 1
    assert result.gate.unverified_price_time_count == 0
    assert candidate.price_time.status == "unverified_time" and not candidate.price_time.strict_eligible
    assert candidate.price_time.policy_version == 1
    assert candidate.price_admission.status == "human_approved"
    assert candidate.price_admission.assessment.evidence_origin == "operator_confirmed"
    assert candidate.price_admission.price_id == fixture.approved.price_id
    assert candidate.price_admission.valuation_at == AT
    assert _financial_rows(fixture.store) == before


@pytest.mark.parametrize("change", ["method", "original", "price", "revoke", "delete_record"])
def test_native_evidence_changes_or_revocation_invalidate_runs_without_rewriting_archives(native_admission, change):
    fixture = native_admission
    service = DivorceValuationRunService(fixture.store, artifact_root=fixture.root / "native-runs",
                                        wallet_fifo_artifact_root=fixture.root / "native-fifo")
    report = service.run(DivorceValuationRunRequest(cutoff_at=AT, valuation_at=LATER))
    assert report.cutoff_price_gate.accepted_price_time_count == report.summary.cutoff_price_gate.accepted_price_time_count == 1
    assert report.cutoff_price_gate.price_admission_state_sha256 is not None
    assert service.has_current_price_time_policy(report, store=fixture.store)
    path = service.artifact_root / report.run_id / "valuation_run.json"
    latest = service.artifact_root / "latest_valuation_gate.json"
    content, latest_content = path.read_bytes(), latest.read_bytes()
    if change in {"method", "original"}:
        path_to_change = (fixture.history.root / "admissions" / "originals" / (fixture.method_sha + ".body")
                          if change == "method" else fixture.history.root / "evidence" / (fixture.sha + ".body"))
        path_to_change.chmod(0o600)
        path_to_change.write_bytes(b"changed synthetic original")
    elif change == "price":
        with fixture.store.connect() as con:
            con.execute("update price_ledger set price_eur=101 where price_id=?", [str(fixture.approved.price_id)])
    elif change == "revoke":
        revoked = fixture.service.revoke(
            fixture.approved.preview_id, fixture.approved.price_id, fixture.approved.request_id,
            PriceAdmissionRevoke(draft_sha256=fixture.approved.draft_sha256, actor="Synthetic test only",
                                 rationale="Synthetic revocation", acknowledge_revocation=True),
        )
        assert revoked.status == "revoked" and not revoked.assessment.strict_eligible
    else:
        with fixture.store.connect() as con:
            con.execute("delete from review_decisions where id=?", [fixture.approved.decision.decision_id])
    assert not service.has_current_price_time_policy(report, store=fixture.store)
    assert service.latest() is None and service.get(report.run_id) is not None
    assert path.read_bytes() == content and latest.read_bytes() == latest_content
    if change == "price":
        with pytest.raises(PriceAdmissionError):
            AsOfPriceGateService(fixture.store).report(as_of=AT)
    else:
        assert not AsOfPriceGateService(fixture.store).report(as_of=AT).strict_ready
