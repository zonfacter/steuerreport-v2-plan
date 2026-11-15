"""Independent #46 review references: local calendar days and Decimal contexts.

No imports from other test modules and no implementation-derived value oracle.
The original 131-case acceptance file remains unchanged.
"""
from datetime import datetime
from decimal import (
    Clamped,
    Context,
    Decimal,
    Inexact,
    Overflow,
    ROUND_HALF_EVEN,
    Rounded,
    Subnormal,
    Underflow,
    getcontext,
    localcontext,
)
import hashlib
from zoneinfo import ZoneInfo

import pytest

from steuerreport_v2.contracts.price_evidence import (
    PriceEvidenceAdmission,
    PriceEvidenceApproval,
    PriceEvidenceFx,
    PriceEvidenceIdentity,
    PriceEvidenceMethod,
    PriceEvidenceObservation,
)
from steuerreport_v2.contracts.prices import PricePoint
from steuerreport_v2.domain.price_evidence import (
    assess_price_evidence,
    price_evidence_binding,
)


def _at(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


PRICE_BYTES = b"Synthetic price original; transcription explicitly reviewed."
METHOD_BYTES = b"Synthetic method original; limited human admission only."
FX_BYTES = b"Synthetic FX original; transcription explicitly reviewed."
PRICE_SHA = hashlib.sha256(PRICE_BYTES).hexdigest()
METHOD_SHA = hashlib.sha256(METHOD_BYTES).hexdigest()
FX_SHA = hashlib.sha256(FX_BYTES).hexdigest()
PROFILES = (
    "normal",
    "inexact_trap",
    "rounded_trap",
    "inexact_and_rounded_traps",
    "narrow_exponents",
    "narrow_exponents_with_traps",
)


def _case(*, stored, valuation, observation, method, originals=None):
    identity = PriceEvidenceIdentity(
        asset="TOKEN", network="ethereum", contract="0x" + "12" * 20,
        decimals=18,
    )
    return {
        "point": PricePoint(
            price_id="synthetic-review-point-46", asset="TOKEN",
            price_eur=Decimal(stored), priced_at=_at(valuation),
            source="synthetic-review-evidence", confidence=Decimal("0.95"),
        ),
        "identity": identity,
        "valuation_at": _at(valuation),
        "observation": PriceEvidenceObservation(
            identity=identity, evidence_sha256=PRICE_SHA,
            locator="synthetic document, line 1", source="Synthetic source",
            **observation,
        ),
        "method": PriceEvidenceMethod(
            method_id="synthetic-review-method", version=1,
            evidence_sha256=METHOD_SHA, **method,
        ),
        "originals": {PRICE_SHA: PRICE_BYTES, METHOD_SHA: METHOD_BYTES, **(originals or {})},
    }


def _binding(case):
    return price_evidence_binding(**{key: value for key, value in case.items() if key != "originals"})


def _approval(case):
    return PriceEvidenceApproval(
        decision_id="synthetic-review-admission-46",
        decision_type="stichtag_price_time_admission",
        binding_sha256=_binding(case), actor="Synthetic reviewer",
        rationale="Originals reviewed; admission limited to the exact supplied valuation.",
        approved_at=_at("2025-11-04T12:00:00Z"),
        acknowledge_original_verified=True, acknowledge_scope_limited=True,
    )


def _positive(answer):
    assert isinstance(answer, PriceEvidenceAdmission)
    assert answer.status == "human_approved"
    assert answer.strict_eligible is True
    assert answer.original_integrity_verified is True
    assert answer.evidence_origin == "operator_confirmed"
    assert answer.decision_id == "synthetic-review-admission-46"
    assert answer.reason_codes == []


@pytest.mark.parametrize(
    "zone,start,end,valuation,published,captured,local_start,seconds,eligible",
    [
        (
            "America/Havana", "2025-11-02T04:00:00Z", "2025-11-03T05:00:00Z",
            "2025-11-02T12:00:00Z", "2025-11-03T06:00:00Z", "2025-11-03T07:00:00Z",
            "2025-11-02T00:00:00-04:00", 90000, True,
        ),
        (
            "America/Havana", "2025-11-02T05:00:00Z", "2025-11-03T05:00:00Z",
            "2025-11-02T12:00:00Z", "2025-11-03T06:00:00Z", "2025-11-03T07:00:00Z",
            "2025-11-02T00:00:00-05:00", 86400, False,
        ),
        (
            "America/Sao_Paulo", "2018-11-04T03:00:00Z", "2018-11-05T02:00:00Z",
            "2018-11-04T12:00:00Z", "2018-11-05T03:00:00Z", "2018-11-05T04:00:00Z",
            "2018-11-04T01:00:00-02:00", 82800, True,
        ),
    ],
    ids=["havana-complete-25h", "havana-second-midnight-truncated", "sao-paulo-first-valid-time-01h"],
)
def test_calendar_day_uses_first_valid_instant_not_arbitrary_wall_midnight(
    zone, start, end, valuation, published, captured, local_start, seconds, eligible,
):
    # UTC endpoints and expected local starts are fixed references, not a copied algorithm.
    assert _at(start).astimezone(ZoneInfo(zone)).isoformat() == local_start
    assert (_at(end) - _at(start)).total_seconds() == seconds
    case = _case(
        stored="125.50", valuation=valuation,
        observation={
            "quote_currency": "EUR", "value": Decimal("125.50"), "kind": "daily_reference",
            "period_start": _at(start), "period_end": _at(end),
            "published_at": _at(published), "captured_at": _at(captured),
        },
        method={
            "kind": "daily_reference", "daily_statistic": "daily_close",
            "timezone": zone, "availability_rule": "retrospective_daily_reference",
        },
    )
    point = case["point"].model_dump()
    case["point"] = PricePoint.model_validate({**point, "priced_at": _at(start)})
    decision = _approval(case)
    assert case["observation"].observed_at is None
    assert case["observation"].published_at > case["valuation_at"]
    answer = assess_price_evidence(**case, approval=decision)
    assert answer.binding_sha256 == decision.binding_sha256
    if eligible:
        _positive(answer)
    else:
        assert answer.strict_eligible is False
        assert answer.status == "rejected"
        assert answer.evidence_origin == "unverified"
        assert answer.original_integrity_verified is True
        assert answer.reason_codes


def _context_state(context):
    return (
        context.prec, context.rounding, context.Emax, context.Emin,
        context.capitals, context.clamp, dict(context.traps), dict(context.flags),
    )


def _caller_context(profile):
    narrow = profile.startswith("narrow_exponents")
    context = Context(
        prec=28, rounding=ROUND_HALF_EVEN,
        Emin=0 if narrow else -999999, Emax=0 if narrow else 999999,
    )
    if profile in {"inexact_trap", "inexact_and_rounded_traps", "narrow_exponents_with_traps"}:
        context.traps[Inexact] = True
    if profile in {"rounded_trap", "inexact_and_rounded_traps", "narrow_exponents_with_traps"}:
        context.traps[Rounded] = True
    if profile == "narrow_exponents_with_traps":
        for signal in (Subnormal, Underflow, Overflow, Clamped):
            context.traps[signal] = True
    context.clear_flags()
    # Existing caller flags must survive too; the function may not clear them.
    context.flags[Rounded] = True
    return context


def _assert_context_independent(case, profile):
    decision = _approval(case)
    expected_binding = decision.binding_sha256
    outside = getcontext()
    outside_before = _context_state(outside)
    inputs_before = {key: value.model_dump() if hasattr(value, "model_dump") else value.copy()
                     if isinstance(value, dict) else value for key, value in case.items()}
    decision_before = decision.model_dump()
    supplied_context = _caller_context(profile)
    supplied_before = _context_state(supplied_context)
    with localcontext(supplied_context) as caller:
        before = _context_state(caller)
        actual_binding = _binding(case)
        assert _context_state(caller) == before
        answer = assess_price_evidence(**case, approval=decision)
        assert _context_state(caller) == before
    assert getcontext() is outside
    assert _context_state(outside) == outside_before
    assert _context_state(supplied_context) == supplied_before
    assert actual_binding == expected_binding
    _positive(answer)
    assert answer.binding_sha256 == expected_binding
    assert decision.model_dump() == decision_before
    after = {key: value.model_dump() if hasattr(value, "model_dump") else value.copy()
             if isinstance(value, dict) else value for key, value in case.items()}
    assert after == inputs_before


@pytest.mark.parametrize("profile", PROFILES)
def test_one_usd_divided_by_three_eur_usd_remains_positive_in_all_contexts(profile):
    moment = "2025-06-13T01:00:00Z"
    fx = PriceEvidenceFx(
        base="EUR", quote="USD", rate=Decimal("3"), reference_at=_at(moment),
        published_at=_at(moment), captured_at=_at("2025-06-14T10:00:00Z"),
        evidence_sha256=FX_SHA, locator="synthetic FX document, line 1", source="Synthetic FX source",
    )
    case = _case(
        stored="0.333333333333333333", valuation=moment,
        observation={
            "quote_currency": "USD", "value": Decimal("1"), "kind": "observed_quote",
            "observed_at": _at(moment), "published_at": _at(moment),
            "captured_at": _at("2025-06-14T10:00:00Z"), "fx": fx,
        },
        method={
            "kind": "observed_quote", "timezone": "UTC",
            "availability_rule": "available_at_cutoff", "fx_max_age_days": 0,
        }, originals={FX_SHA: FX_BYTES},
    )
    assert case["point"].price_eur == Decimal("0.333333333333333333")
    _assert_context_independent(case, profile)


@pytest.mark.parametrize("profile", PROFILES)
def test_smallest_stored_eur_quantum_remains_positive_in_all_contexts(profile):
    moment = "2025-06-13T01:00:00Z"
    case = _case(
        stored="0.000000000000000001", valuation=moment,
        observation={
            "quote_currency": "EUR", "value": Decimal("0.000000000000000001"),
            "kind": "observed_quote", "observed_at": _at(moment),
            "published_at": _at(moment), "captured_at": _at("2025-06-14T10:00:00Z"),
        },
        method={
            "kind": "observed_quote", "timezone": "UTC", "availability_rule": "available_at_cutoff",
        },
    )
    assert case["point"].price_eur == Decimal("0.000000000000000001")
    assert case["observation"].fx is None
    _assert_context_independent(case, profile)
