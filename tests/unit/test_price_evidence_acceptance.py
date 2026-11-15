"""Independent synthetic references for the positive #46 admission contract.

No provider facts or legal approval are inferred. Missing contract modules cause
one collection error, not a set of alleged behavioral counterexamples.
"""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import hashlib
import re

from pydantic import ValidationError
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


def at(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


PRICE_BYTES = b"Synthetic price document; its transcription requires human review."
METHOD_BYTES = b"Synthetic method document; no legal or automatic admission is claimed."
FX_BYTES = b"Synthetic FX document; its transcription requires human review."
PRICE_SHA = hashlib.sha256(PRICE_BYTES).hexdigest()
METHOD_SHA = hashlib.sha256(METHOD_BYTES).hexdigest()
FX_SHA = hashlib.sha256(FX_BYTES).hexdigest()
UNSET = object()


@pytest.fixture
def case():
    identity = PriceEvidenceIdentity(
        asset="TOKEN", network="ethereum", contract="0x" + "12" * 20,
        decimals=18,
    )
    return {
        "point": PricePoint(
            price_id="synthetic-point-46", asset="TOKEN",
            price_eur=Decimal("125.50"), priced_at=at("2025-06-13T01:00:00Z"),
            source="synthetic-evidence", confidence=Decimal("0.95"),
        ),
        "identity": identity,
        "valuation_at": at("2025-06-13T01:00:00Z"),
        "observation": PriceEvidenceObservation(
            identity=identity, quote_currency="EUR", value=Decimal("125.50"),
            kind="observed_quote", observed_at=at("2025-06-13T01:00:00Z"),
            published_at=at("2025-06-13T01:00:00Z"),
            captured_at=at("2025-06-14T10:00:00Z"),
            evidence_sha256=PRICE_SHA, locator="synthetic document, line 1",
            source="Synthetic exchange",
        ),
        "method": PriceEvidenceMethod(
            method_id="synthetic-observed-quote", version=1,
            kind="observed_quote", timezone="UTC",
            availability_rule="available_at_cutoff", evidence_sha256=METHOD_SHA,
        ),
        "originals": {PRICE_SHA: PRICE_BYTES, METHOD_SHA: METHOD_BYTES},
    }


def binding(case):
    return price_evidence_binding(**{k: v for k, v in case.items() if k != "originals"})


def approval(case, **changes):
    values = {
        "decision_id": "synthetic-admission-46",
        "decision_type": "stichtag_price_time_admission",
        "binding_sha256": binding(case), "actor": "Synthetic reviewer",
        "rationale": "Original and limited temporal admission explicitly reviewed.",
        "approved_at": at("2025-11-03T12:00:00Z"),
        "acknowledge_original_verified": True,
        "acknowledge_scope_limited": True,
    }
    return PriceEvidenceApproval.model_validate({**values, **changes})


def assess(case, decision=UNSET):
    return assess_price_evidence(
        **case, approval=approval(case) if decision is UNSET else decision,
    )


def changed(case, part, **values):
    result = deepcopy(case)
    model = result[part]
    result[part] = type(model).model_validate({**model.model_dump(), **values})
    return result


def admitted(result):
    assert isinstance(result, PriceEvidenceAdmission)
    assert result.status == "human_approved"
    assert result.strict_eligible is True
    assert result.original_integrity_verified is True
    assert result.evidence_origin == "operator_confirmed"
    assert result.decision_id == "synthetic-admission-46"
    assert re.fullmatch(r"[a-f0-9]{64}", result.binding_sha256)
    return result


def blocked(result):
    assert isinstance(result, PriceEvidenceAdmission)
    assert result.strict_eligible is False
    assert result.status != "human_approved"
    assert result.evidence_origin == "unverified"
    assert result.reason_codes


def usd_case(case, *, inverse=False, raw_value="100", stored="90"):
    # The expected stored value is a literal reference, never a product formula.
    result = changed(case, "point", price_eur=Decimal(stored))
    fx = PriceEvidenceFx(
        base="EUR" if inverse else "USD", quote="USD" if inverse else "EUR",
        rate=Decimal("1.111111111111111111111111111") if inverse else Decimal("0.9"),
        reference_at=at("2025-06-13T00:00:00Z"),
        published_at=at("2025-06-13T00:30:00Z"),
        captured_at=at("2025-06-14T10:00:00Z"), evidence_sha256=FX_SHA,
        locator="synthetic FX document, line 1", source="Synthetic FX source",
    )
    result = changed(result, "observation", quote_currency="USD", value=Decimal(raw_value), fx=fx)
    result = changed(result, "method", fx_max_age_days=0)
    result["originals"][FX_SHA] = FX_BYTES
    return result


def daily_case(case, *, start, end, valuation, anchor, statistic="daily_close"):
    result = changed(case, "point", priced_at=at(anchor))
    result["valuation_at"] = at(valuation)
    result = changed(
        result, "observation", kind="daily_reference", observed_at=None,
        period_start=at(start), period_end=at(end),
        published_at=at("2025-11-01T10:00:00Z"),
        captured_at=at("2025-11-02T10:00:00Z"),
    )
    return changed(
        result, "method", kind="daily_reference", daily_statistic=statistic,
        daily_time="12:00:00" if statistic == "daily_fixed_time" else None,
        timezone="Europe/Berlin", availability_rule="retrospective_daily_reference",
    )


def test_direct_eur_requires_exact_bound_human_approval_without_fx(case):
    result = admitted(assess(case))
    assert result.binding_sha256 == binding(case)
    assert case["observation"].fx is None
    assert case["observation"].identity.asset == "TOKEN"
    missing = assess(case, None)
    blocked(missing)
    assert missing.status == "not_approved"


@pytest.mark.parametrize("inverse", [False, True], ids=["100-times-0.9", "100-divided-by-10-over-9"])
def test_usd_both_quotations_admit_the_same_90_eur(case, inverse):
    admitted(assess(usd_case(case, inverse=inverse)))


def test_usd_storage_quantization_uses_18_places_not_display_rounding(case):
    admitted(assess(usd_case(case, raw_value="100.0000000000000000004", stored="90")))
    different = usd_case(case, raw_value="100.0000000000000000004", stored="90.000000000000000001")
    blocked(assess(different))


def test_direct_eur_has_exact_value_agreement_not_fx_rounding_tolerance(case):
    result = changed(case, "observation", value=Decimal("125.5000000000000000001"))
    blocked(assess(result))


@pytest.mark.parametrize("part", ["price", "fx"])
def test_publication_one_microsecond_after_cutoff_is_not_available(case, part):
    result = usd_case(case) if part == "fx" else deepcopy(case)
    late = at("2025-06-13T01:00:00.000001Z")
    if part == "price":
        result = changed(result, "observation", published_at=late)
    else:
        fx = result["observation"].fx
        fx = PriceEvidenceFx.model_validate({**fx.model_dump(), "published_at": late})
        result = changed(result, "observation", fx=fx)
    blocked(assess(result))


def test_late_capture_does_not_replace_a_missing_publication(case):
    # Missing required publication is either structurally rejected or ineligible.
    try:
        result = changed(case, "observation", published_at=None)
    except ValidationError:
        return
    blocked(assess(result))


@pytest.mark.parametrize("part", ["price", "fx"])
def test_capture_cannot_precede_publication(case, part):
    result = usd_case(case) if part == "fx" else deepcopy(case)
    early = at("2025-06-12T23:59:59Z")
    try:
        if part == "price":
            result = changed(result, "observation", captured_at=early)
        else:
            fx = result["observation"].fx
            fx = PriceEvidenceFx.model_validate({**fx.model_dump(), "captured_at": early})
            result = changed(result, "observation", fx=fx)
    except ValidationError:
        return
    blocked(assess(result))


def test_later_human_approval_is_allowed_but_not_before_capture(case):
    admitted(assess(case, approval(case, approved_at=at("2025-06-15T12:00:00Z"))))
    blocked(assess(case, approval(case, approved_at=at("2025-06-14T09:59:59Z"))))


@pytest.mark.parametrize("statistic", ["daily_mean", "daily_close", "daily_fixed_time"])
def test_retrospective_daily_methods_are_positive_without_fabricated_observation(case, statistic):
    result = daily_case(
        case, start="2025-06-12T22:00:00Z", end="2025-06-13T22:00:00Z",
        valuation="2025-06-13T01:00:00Z", anchor="2025-06-12T22:00:00Z",
        statistic=statistic,
    )
    admitted(assess(result))
    assert result["observation"].kind == "daily_reference"
    assert result["observation"].observed_at is None
    assert result["observation"].published_at > result["valuation_at"]
    blocked(assess(result, None))


@pytest.mark.parametrize(
    "start,end,valuation", [
        ("2025-03-29T23:00:00Z", "2025-03-30T22:00:00Z", "2025-03-30T01:00:00Z"),
        ("2025-10-25T22:00:00Z", "2025-10-26T23:00:00Z", "2025-10-26T01:00:00Z"),
    ], ids=["spring-23-hours", "autumn-25-hours"],
)
def test_local_daily_period_handles_real_dst_day_lengths(case, start, end, valuation):
    result = daily_case(case, start=start, end=end, valuation=valuation, anchor=start)
    admitted(assess(result, approval(result, approved_at=at("2025-11-03T10:00:00Z"))))


@pytest.mark.parametrize("which", ["period_24h_on_spring_day", "valuation_at_next_day", "anchor_at_next_day"])
def test_daily_period_is_local_calendar_day_with_exclusive_end(case, which):
    result = daily_case(
        case, start="2025-03-29T23:00:00Z", end="2025-03-30T22:00:00Z",
        valuation="2025-03-30T01:00:00Z", anchor="2025-03-29T23:00:00Z",
    )
    if which == "period_24h_on_spring_day":
        try:
            result = changed(result, "observation", period_end=at("2025-03-30T23:00:00Z"))
        except ValidationError:
            return
    elif which == "valuation_at_next_day":
        result["valuation_at"] = at("2025-03-30T22:00:00Z")
    else:
        result = changed(result, "point", priced_at=at("2025-03-30T22:00:00Z"))
    blocked(assess(result, approval(result, approved_at=at("2025-11-03T10:00:00Z"))))


def test_daily_method_cannot_use_retroactive_publication_in_available_mode(case):
    result = daily_case(
        case, start="2025-06-12T22:00:00Z", end="2025-06-13T22:00:00Z",
        valuation="2025-06-13T01:00:00Z", anchor="2025-06-12T22:00:00Z",
    )
    result = changed(result, "method", availability_rule="available_at_cutoff")
    blocked(assess(result, approval(result, approved_at=at("2025-11-03T10:00:00Z"))))


@pytest.mark.parametrize("sha", [PRICE_SHA, METHOD_SHA, FX_SHA], ids=["price", "method", "fx"])
@pytest.mark.parametrize("tampered", [False, True], ids=["missing", "changed-bytes"])
def test_all_required_originals_are_checked_against_their_hashes(case, sha, tampered):
    result = usd_case(case)
    decision = approval(result)
    if tampered:
        result["originals"][sha] += b" changed"
    else:
        del result["originals"][sha]
    answer = assess(result, decision)
    blocked(answer)
    assert answer.original_integrity_verified is False


def test_rehashed_replacement_original_does_not_inherit_old_approval(case):
    decision = approval(case)
    replacement = b"A different synthetic original."
    sha = hashlib.sha256(replacement).hexdigest()
    result = changed(case, "observation", evidence_sha256=sha)
    result["originals"] = {sha: replacement, METHOD_SHA: METHOD_BYTES}
    blocked(assess(result, decision))


@pytest.mark.parametrize("part,field,value", [
    ("point", "price_id", "another-price-id"),
    ("point", "price_eur", Decimal("125.51")),
    ("point", "priced_at", at("2025-06-13T00:59:59Z")),
    ("point", "source", "another-source"),
    ("point", "confidence", Decimal("0.96")),
    ("identity", "network", "another-network"),
    ("identity", "contract", "0x" + "34" * 20),
    ("identity", "decimals", 6),
    ("observation", "value", Decimal("125.51")),
    ("observation", "locator", "another document, line 2"),
    ("observation", "source", "another original source"),
    ("observation", "published_at", at("2025-06-13T01:00:00.000001Z")),
    ("observation", "captured_at", at("2025-06-14T10:00:01Z")),
    ("method", "method_id", "another-method"),
    ("method", "version", 2),
    ("method", "timezone", "Europe/Berlin"),
    ("method", "evidence_sha256", "0" * 64),
])
def test_exact_input_changes_never_reuse_an_old_binding(case, part, field, value):
    decision = approval(case)
    result = changed(case, part, **{field: value})
    assert binding(result) != decision.binding_sha256
    blocked(assess(result, decision))


def test_valuation_instant_is_part_of_binding_even_with_same_price(case):
    decision = approval(case)
    result = deepcopy(case)
    result["valuation_at"] = at("2025-06-13T01:00:00.000001Z")
    assert binding(result) != decision.binding_sha256
    blocked(assess(result, decision))


@pytest.mark.parametrize("field,value", [
    ("asset", "OTHER"), ("network", "another-network"),
    ("contract", "0x" + "34" * 20), ("decimals", 6),
])
def test_matching_ticker_alone_is_not_identity_even_with_rebound_approval(case, field, value):
    identity = PriceEvidenceIdentity.model_validate({**case["identity"].model_dump(), field: value})
    result = changed(case, "observation", identity=identity)
    blocked(assess(result))


@pytest.mark.parametrize("which", ["value", "observed_time"])
def test_rebound_approval_cannot_cure_observed_price_mismatch(case, which):
    result = changed(case, "observation", **(
        {"value": Decimal("125.51")} if which == "value"
        else {"observed_at": at("2025-06-13T00:59:59Z")}
    ))
    blocked(assess(result))


def test_updated_decision_is_not_an_unchanged_approval(case):
    decision = approval(case, updated_at=at("2025-11-03T12:00:01Z"))
    blocked(assess(case, decision))


@pytest.mark.parametrize("field", ["acknowledge_original_verified", "acknowledge_scope_limited"])
def test_denied_acknowledgement_cannot_admit(case, field):
    try:
        decision = approval(case, **{field: False})
    except ValidationError:
        return
    blocked(assess(case, decision))


@pytest.mark.parametrize("decision_type", ["historical_price_import", "token_valuation", "wallet_fifo_method_acceptance"])
def test_other_review_decision_types_do_not_admit_price_time(case, decision_type):
    try:
        decision = approval(case, decision_type=decision_type)
    except ValidationError:
        return
    blocked(assess(case, decision))


def test_numerically_equal_decimals_and_equal_utc_instants_have_identical_binding(case):
    result = changed(case, "point", price_eur=Decimal("125.5000"), confidence=Decimal("0.95000"),
                     priced_at=at("2025-06-13T03:00:00+02:00"))
    result["valuation_at"] = at("2025-06-12T20:00:00-05:00")
    result = changed(result, "observation", value=Decimal("1.2550E+2"),
                     observed_at=at("2025-06-13T03:00:00+02:00"),
                     published_at=at("2025-06-13T03:00:00+02:00"),
                     captured_at=at("2025-06-14T12:00:00+02:00"))
    assert binding(result) == binding(case)
    admitted(assess(result, approval(case)))


def test_fx_decimal_spellings_and_offsets_have_identical_binding(case):
    original = usd_case(case)
    fx = original["observation"].fx
    equivalent = PriceEvidenceFx.model_validate({
        **fx.model_dump(), "rate": Decimal("9.000E-1"),
        "reference_at": at("2025-06-13T02:00:00+02:00"),
        "published_at": at("2025-06-13T02:30:00+02:00"),
        "captured_at": at("2025-06-14T12:00:00+02:00"),
    })
    result = changed(original, "observation", value=Decimal("1.00E+2"), fx=equivalent)
    assert binding(original) == binding(result)
    admitted(assess(result, approval(original)))


@pytest.mark.parametrize("field,value", [
    ("rate", Decimal("0.91")), ("base", "EUR"),
    ("reference_at", at("2025-06-12T00:00:00Z")),
    ("published_at", at("2025-06-13T00:30:01Z")),
    ("captured_at", at("2025-06-14T10:00:01Z")),
    ("locator", "another FX line"), ("source", "another FX source"),
])
def test_fx_fields_are_bound_not_just_the_eur_conversion(case, field, value):
    original = usd_case(case)
    fx = original["observation"].fx
    try:
        fx = PriceEvidenceFx.model_validate({**fx.model_dump(), field: value})
    except ValidationError:
        assert field == "base"  # Same-currency pairs are malformed, not an admission.
        return
    result = changed(original, "observation", fx=fx)
    assert binding(result) != binding(original)
    blocked(assess(result, approval(original)))


def test_fx_age_policy_is_explicit_and_bound(case):
    result = usd_case(case)
    decision = approval(result)
    result = changed(result, "method", fx_max_age_days=1)
    assert binding(result) != decision.binding_sha256
    blocked(assess(result, decision))
    admitted(assess(result))


def test_usd_missing_explicit_fx_age_rule_cannot_admit(case):
    result = usd_case(case)
    try:
        result = changed(result, "method", fx_max_age_days=None)
    except ValidationError:
        return
    blocked(assess(result))


@pytest.mark.parametrize("field", ["locator", "source"])
def test_unknown_provenance_cannot_become_a_reviewed_original(case, field):
    try:
        result = changed(case, "observation", **{field: ""})
    except ValidationError:
        return
    blocked(assess(result))


def test_wrong_point_asset_cannot_be_cured_by_rebinding(case):
    result = changed(case, "point", asset="OTHER")
    blocked(assess(result))


@pytest.mark.parametrize("days", [None, 0, 1])
def test_missing_or_out_of_policy_fx_never_uses_parity(case, days):
    result = usd_case(case)
    if days is None:
        result = changed(result, "observation", fx=None)
    else:
        fx = result["observation"].fx
        fx = PriceEvidenceFx.model_validate({
            **fx.model_dump(),
            "reference_at": at("2025-06-12T00:00:00Z") if days == 1 else at("2025-06-13T01:00:01Z"),
        })
        result = changed(result, "observation", fx=fx)
    blocked(assess(result))


@pytest.mark.parametrize("part,field", [("observation", "value"), ("fx", "rate"), ("method", "version")])
@pytest.mark.parametrize("value", [True, False, 1.0, float("nan"), float("inf")])
def test_float_and_bool_are_rejected_before_new_model_coercion(case, part, field, value):
    result = usd_case(case)
    model = result["observation"].fx if part == "fx" else result[part]
    with pytest.raises(ValidationError):
        type(model).model_validate({**model.model_dump(), field: value})


@pytest.mark.parametrize("part,field", [("observation", "value"), ("fx", "rate")])
@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_nonfinite_decimal_is_rejected_by_model(case, part, field, value):
    model = usd_case(case)["observation"]
    if part == "fx":
        model = model.fx
    with pytest.raises(ValidationError):
        type(model).model_validate({**model.model_dump(), field: value})


@pytest.mark.parametrize("field", ["acknowledge_original_verified", "acknowledge_scope_limited"])
@pytest.mark.parametrize("value", [1, 0, "true", "false"])
def test_acknowledgements_require_real_booleans(case, field, value):
    with pytest.raises(ValidationError):
        approval(case, **{field: value})


@pytest.mark.parametrize("part,field", [
    ("point", "priced_at"), ("observation", "observed_at"),
    ("observation", "published_at"), ("observation", "captured_at"),
    ("fx", "reference_at"), ("fx", "published_at"), ("fx", "captured_at"),
    ("approval", "approved_at"),
])
def test_naive_datetimes_are_rejected_not_normalized_as_utc(case, part, field):
    result = usd_case(case)
    naive = datetime(2025, 6, 13, 1)
    with pytest.raises(ValidationError):
        if part == "approval":
            assess(result, approval(result, **{field: naive}))
        elif part == "point":
            result = changed(result, part, **{field: naive})
            binding(result)
        elif part == "fx":
            fx = result["observation"].fx
            fx = PriceEvidenceFx.model_validate({**fx.model_dump(), field: naive})
            assess(changed(result, "observation", fx=fx))
        else:
            assess(changed(result, part, **{field: naive}))


def test_naive_valuation_is_rejected_by_pure_entrypoints(case):
    result = deepcopy(case)
    result["valuation_at"] = datetime(2025, 6, 13, 1)
    with pytest.raises(ValidationError):
        binding(result)
    with pytest.raises(ValidationError):
        assess(result, approval(case))


@pytest.mark.parametrize("field", ["period_start", "period_end"])
def test_daily_period_endpoints_require_explicit_timezone(case, field):
    result = daily_case(
        case, start="2025-06-12T22:00:00Z", end="2025-06-13T22:00:00Z",
        valuation="2025-06-13T01:00:00Z", anchor="2025-06-12T22:00:00Z",
    )
    with pytest.raises(ValidationError):
        result = changed(result, "observation", **{field: datetime(2025, 6, 13)})
        binding(result)


@pytest.mark.parametrize("part", ["identity", "observation", "method", "fx", "approval", "admission"])
def test_all_new_models_reject_unknown_fields(case, part):
    model = (usd_case(case)["observation"].fx if part == "fx"
             else approval(case) if part == "approval"
             else admitted(assess(case)) if part == "admission" else case[part])
    with pytest.raises(ValidationError):
        type(model).model_validate({**model.model_dump(), "unapproved_extra": "synthetic"})


@pytest.mark.parametrize("bad", ["zero", "negative", "too_large", "below_storage_precision"])
def test_usd_values_must_be_positive_and_storage_representable(case, bad):
    stored, raw = {
        "zero": ("0", "0"), "negative": ("-90", "-100"),
        "too_large": ("100000000000000000000", "111111111111111111111.111111111"),
        "below_storage_precision": ("0", "0.00000000000000000001"),
    }[bad]
    try:
        result = usd_case(case, stored=stored, raw_value=raw)
    except ValidationError:
        return
    blocked(assess(result))


@pytest.mark.parametrize("extra_kind", ["changed_hash", "too_large", "aggregate_too_large"])
def test_unused_originals_cannot_evade_integrity_or_size_validation(case, extra_kind):
    result = deepcopy(case)
    if extra_kind == "changed_hash":
        result["originals"]["0" * 64] = b"unbound extra bytes"
    elif extra_kind == "too_large":
        raw = b"x" * (2 * 1024 * 1024 + 1)
        result["originals"][hashlib.sha256(raw).hexdigest()] = raw
    else:
        for char in (b"a", b"b", b"c"):
            raw = char * (2 * 1024 * 1024)
            result["originals"][hashlib.sha256(raw).hexdigest()] = raw
    try:
        answer = assess(result)
    except (ValidationError, ValueError):
        return
    blocked(answer)


def test_negative_admission_never_exposes_private_original_contents(case):
    result = deepcopy(case)
    marker = b"SYNTHETIC-PRIVATE-DOCUMENT-NOT-FOR-ERRORS"
    sha = hashlib.sha256(marker).hexdigest()
    result = changed(result, "observation", evidence_sha256=sha)
    result["originals"] = {sha: marker + b"tampered", METHOD_SHA: METHOD_BYTES}
    answer = assess(result)
    blocked(answer)
    assert marker.decode() not in answer.model_dump_json()


def test_admission_and_binding_are_deterministic_input_preserving_and_effect_free(case, monkeypatch):
    import builtins
    import io
    import os
    from pathlib import Path
    import socket
    import subprocess

    import duckdb

    decision = approval(case)
    expected_binding = binding(case)
    before = deepcopy(case)
    before_decision = decision.model_dump()

    def forbidden(*args, **kwargs):
        pytest.fail("Pure admission attempted filesystem, network, database or process access")

    with monkeypatch.context() as guard:
        for owner, names in (
            (builtins, ("open",)), (io, ("open",)),
            (Path, ("open", "read_bytes", "read_text", "write_bytes", "write_text", "mkdir", "stat", "iterdir")),
            (os, ("open", "stat", "listdir", "scandir", "system", "urandom")),
            (socket, ("socket", "create_connection", "getaddrinfo")),
            (subprocess, ("Popen", "run")), (duckdb, ("connect",)),
        ):
            for name in names:
                guard.setattr(owner, name, forbidden)
        assert binding(case) == expected_binding
        first = assess(case, decision)
        second = assess(case, decision)
        assert first.model_dump() == second.model_dump()
    admitted(first)
    assert case == before
    assert decision.model_dump() == before_decision
    output = first.model_dump_json()
    for raw in (PRICE_BYTES, METHOD_BYTES):
        assert raw.decode() not in output
    assert "Original and limited temporal admission explicitly reviewed." not in output
