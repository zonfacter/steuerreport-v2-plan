"""Synthetische reine Belegpruefung; keine DB, Provider oder echten Reviews."""
from datetime import UTC, datetime, timedelta
from decimal import Decimal, localcontext
import hashlib
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from pydantic import ValidationError

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
    POLICY_ID,
    POLICY_VERSION,
    assess_price_evidence,
    price_evidence_binding,
)


def _hash(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def case():
    price, method = b"Synthetic BTC EUR quote: 100 at 2025-06-13T00:30Z", b"Synthetic observed quote method v1"
    identity = PriceEvidenceIdentity(asset="BTC", network="bitcoin", contract="native", decimals=8)
    observed = datetime(2025, 6, 13, 0, 30, tzinfo=UTC)
    return {
        "point": PricePoint(price_id=str(UUID(int=1)), asset="BTC", price_eur=Decimal("100"),
                            priced_at=observed, source="synthetic:untrusted-label", confidence=Decimal("0.95")),
        "identity": identity,
        "valuation_at": observed + timedelta(minutes=30),
        "observation": PriceEvidenceObservation(
            identity=identity, quote_currency="EUR", value=Decimal("100"), kind="observed_quote",
            observed_at=observed, published_at=observed, captured_at=observed + timedelta(days=1),
            evidence_sha256=_hash(price), locator="page 1, row BTC", source="Synthetic original",
        ),
        "method": PriceEvidenceMethod(
            method_id="synthetic-observed", version=1, kind="observed_quote", timezone="UTC",
            availability_rule="available_at_cutoff", evidence_sha256=_hash(method),
        ),
        "originals": {_hash(price): price, _hash(method): method},
    }


def _binding(case):
    return price_evidence_binding(**{key: value for key, value in case.items() if key != "originals"})


def _approval(case, **changes):
    data = dict(decision_id="synthetic-review-1", binding_sha256=_binding(case), actor="Synthetic reviewer",
                rationale="Synthetic original checked; limited to this valuation.",
                approved_at=datetime(2025, 6, 15, tzinfo=UTC),
                acknowledge_original_verified=True, acknowledge_scope_limited=True)
    data.update(changes)
    return PriceEvidenceApproval(**data)


def _assess(case, approval=True):
    return assess_price_evidence(**case, approval=_approval(case) if approval is True else approval)


def _change(case, key, **changes):
    data = case[key].model_dump(mode="python")
    data.update(changes)
    case[key] = type(case[key]).model_validate(data)


def _daily(case, date="2025-06-13", zone="Europe/Berlin", statistic="daily_mean", daily_time=None):
    local = ZoneInfo(zone)
    start = datetime.fromisoformat(date).replace(tzinfo=local)
    end = start + timedelta(days=1)
    case["valuation_at"] = (start + timedelta(hours=12)).astimezone(UTC)
    _change(case, "point", priced_at=start)
    _change(case, "observation", kind="daily_reference", observed_at=None, period_start=start,
            period_end=end, published_at=end + timedelta(hours=2), captured_at=end + timedelta(days=1))
    _change(case, "method", kind="daily_reference", daily_statistic=statistic, daily_time=daily_time,
            timezone=zone, availability_rule="retrospective_daily_reference")


def _usd(case, base="USD", rate="0.8", value="125"):
    original = b"Synthetic independent USD/EUR reference"
    sha = _hash(original)
    case["originals"][sha] = original
    _change(case, "observation", quote_currency="USD", value=Decimal(value), fx=PriceEvidenceFx(
        base=base, quote="EUR" if base == "USD" else "USD", rate=Decimal(rate),
        reference_at=case["point"].priced_at, published_at=case["point"].priced_at,
        captured_at=case["observation"].captured_at, evidence_sha256=sha, locator="row USD/EUR",
        source="Synthetic independent FX original",
    ))
    _change(case, "method", fx_max_age_days=0)


def test_direct_eur_requires_explicit_human_approval(case):
    result = _assess(case)
    assert result.strict_eligible
    assert result.status == "human_approved"
    assert result.evidence_origin == "operator_confirmed"
    assert result.original_integrity_verified
    assert result.policy_id == POLICY_ID and result.policy_version == POLICY_VERSION
    assert result.reason_codes == []
    assert result.decision_id == "synthetic-review-1"
    missing = _assess(case, None)
    assert not missing.strict_eligible
    assert missing.status == "not_approved"
    assert missing.evidence_origin == "unverified"
    assert missing.reason_codes == ["approval_missing"]


@pytest.mark.parametrize("key,changes", [
    ("point", {"price_id": str(UUID(int=2))}),
    ("point", {"price_eur": Decimal("101")}),
    ("point", {"source": "a different full source"}),
    ("point", {"confidence": Decimal("0.8")}),
    ("point", {"priced_at": datetime(2025, 6, 13, 0, 31, tzinfo=UTC)}),
    ("identity", {"network": "another-network"}),
    ("identity", {"contract": "another-contract"}),
    ("identity", {"decimals": 9}),
    ("method", {"version": 2}),
    ("method", {"method_id": "different-method"}),
    ("method", {"timezone": "Europe/Berlin"}),
    ("observation", {"locator": "another row"}),
    ("observation", {"source": "another original source"}),
    ("observation", {"value": Decimal("101")}),
    ("observation", {"published_at": datetime(2025, 6, 13, 0, 31, tzinfo=UTC)}),
    ("observation", {"captured_at": datetime(2025, 6, 14, 0, 31, tzinfo=UTC)}),
])
def test_bound_input_changes_reject_old_approval(case, key, changes):
    approval = _approval(case)
    _change(case, key, **changes)
    result = _assess(case, approval)
    assert not result.strict_eligible
    assert "approval_binding_mismatch" in result.reason_codes


def test_valuation_change_is_bound(case):
    approval = _approval(case)
    case["valuation_at"] += timedelta(seconds=1)
    assert "approval_binding_mismatch" in _assess(case, approval).reason_codes


@pytest.mark.parametrize("change,reason", [
    ({"binding_sha256": "0" * 64}, "approval_binding_mismatch"),
    ({"updated_at": datetime(2025, 6, 15, tzinfo=UTC)}, "approval_updated"),
    ({"acknowledge_original_verified": False}, "approval_acknowledgement_missing"),
    ({"acknowledge_scope_limited": False}, "approval_acknowledgement_missing"),
    ({"approved_at": datetime(2025, 6, 13, tzinfo=UTC)}, "approval_before_capture"),
])
def test_approval_limits(case, change, reason):
    result = _assess(case, _approval(case, **change))
    assert not result.strict_eligible and reason in result.reason_codes


def test_binding_normalizes_numbers_and_timezones_without_rounding(case):
    expected = _binding(case)
    _change(case, "point", price_eur="100.0000", confidence="0.9500",
            priced_at=case["point"].priced_at.astimezone(ZoneInfo("Europe/Berlin")))
    _change(case, "observation", value="1E+2")
    case["valuation_at"] = case["valuation_at"].astimezone(ZoneInfo("America/New_York"))
    assert _binding(case) == expected
    with localcontext() as ctx:
        ctx.prec = 2
        assert _binding(case) == expected
    _change(case, "point", confidence=Decimal("0.950000000000000000000000001"))
    assert _binding(case) != expected


@pytest.mark.parametrize("field", ["published_at", "observed_at"])
def test_future_price_reference_or_publication_blocks_even_if_approved(case, field):
    _change(case, "observation", **{field: case["valuation_at"] + timedelta(seconds=1)})
    assert not _assess(case).strict_eligible


def test_capture_is_not_publication(case):
    assert _assess(case).strict_eligible  # Retrieval after cutoff is permitted.
    _change(case, "observation", captured_at=case["observation"].published_at - timedelta(seconds=1))
    assert "price_capture_before_publication" in _assess(case).reason_codes


@pytest.mark.parametrize("seconds", [-1, 0])
def test_observed_publication_cannot_precede_observation(case, seconds):
    _change(case, "observation", published_at=case["observation"].observed_at + timedelta(seconds=seconds))
    result = _assess(case)
    assert result.strict_eligible == (seconds == 0)
    if seconds < 0:
        assert "price_publication_before_observation" in result.reason_codes


@pytest.mark.parametrize("statistic", ["daily_mean", "daily_close"])
@pytest.mark.parametrize("seconds", [-1, 0])
def test_daily_publication_cannot_precede_period_completion(case, statistic, seconds):
    _daily(case, statistic=statistic)
    _change(case, "observation", published_at=case["observation"].period_end + timedelta(seconds=seconds))
    result = _assess(case)
    assert result.strict_eligible == (seconds == 0)
    if seconds < 0:
        assert "price_publication_before_period_end" in result.reason_codes


@pytest.mark.parametrize("date", ["2025-03-30", "2025-10-26", "2025-06-13"])
@pytest.mark.parametrize("seconds", [-1, 0])
def test_daily_fixed_publication_cannot_precede_local_fix(case, date, seconds):
    _daily(case, date=date, statistic="daily_fixed_time", daily_time="12:00:00")
    fixed = datetime.fromisoformat(date + "T12:00:00").replace(tzinfo=ZoneInfo("Europe/Berlin"))
    _change(case, "observation", published_at=fixed.astimezone(UTC) + timedelta(seconds=seconds))
    result = _assess(case, _approval(case, approved_at=datetime(2026, 1, 1, tzinfo=UTC)))
    assert result.strict_eligible == (seconds == 0)
    if seconds < 0:
        assert "price_publication_before_daily_fixed_time" in result.reason_codes


@pytest.mark.parametrize("base,rate", [("USD", "0.8"), ("EUR", "1.25")])
@pytest.mark.parametrize("seconds", [-1, 0])
def test_fx_publication_cannot_precede_reference(case, base, rate, seconds):
    _usd(case, base=base, rate=rate)
    fx = case["observation"].fx
    _change(case, "observation", fx=fx.model_copy(update={
        "published_at": fx.reference_at + timedelta(seconds=seconds),
    }))
    result = _assess(case)
    assert result.strict_eligible == (seconds == 0)
    if seconds < 0:
        assert "fx_publication_before_reference" in result.reason_codes


@pytest.mark.parametrize("date", ["2025-03-30", "2025-10-26", "2025-06-13"])
@pytest.mark.parametrize("statistic,daily_time", [
    ("daily_mean", None), ("daily_close", None), ("daily_fixed_time", "12:00:00"),
])
def test_documented_daily_references_including_dst(case, date, statistic, daily_time):
    _daily(case, date=date, statistic=statistic, daily_time=daily_time)
    approval = _approval(case, approved_at=datetime(2026, 1, 1, tzinfo=UTC))
    result = _assess(case, approval)
    assert result.strict_eligible
    assert case["observation"].observed_at is None
    assert case["observation"].published_at > case["valuation_at"]
    hours = (case["observation"].period_end - case["observation"].period_start).total_seconds() / 3600
    assert hours == {"2025-03-30": 23, "2025-10-26": 25}.get(date, 24)
    _change(case, "method", availability_rule="available_at_cutoff")
    negative = _assess(case, _approval(case, approved_at=datetime(2026, 1, 1, tzinfo=UTC)))
    assert not negative.strict_eligible
    assert "price_reference_after_cutoff" in negative.reason_codes


@pytest.mark.parametrize("mutation", ["period", "anchor", "valuation", "observed", "statistic", "time"])
def test_daily_shape_and_containment(case, mutation):
    _daily(case)
    obs = case["observation"]
    if mutation == "period":
        _change(case, "observation", period_end=obs.period_end + timedelta(hours=1))
    elif mutation == "anchor":
        _change(case, "point", priced_at=obs.period_end)
    elif mutation == "valuation":
        case["valuation_at"] = obs.period_end
    elif mutation == "observed":
        _change(case, "observation", observed_at=obs.period_start)
    elif mutation == "statistic":
        _change(case, "method", daily_statistic=None)
    else:
        _change(case, "method", daily_time="12:00:00")
    assert not _assess(case).strict_eligible


@pytest.mark.parametrize("date", ["2025-03-30", "2025-10-26"])
def test_nonexistent_or_ambiguous_fixed_daily_time_rejected(case, date):
    _daily(case, date=date, statistic="daily_fixed_time", daily_time="02:30:00")
    result = _assess(case, _approval(case, approved_at=datetime(2026, 1, 1, tzinfo=UTC)))
    assert not result.strict_eligible
    assert any(reason in result.reason_codes for reason in ["daily_time_nonexistent", "daily_time_ambiguous"])


@pytest.mark.parametrize("base,rate", [("USD", "0.8"), ("EUR", "1.25")])
def test_usd_fx_both_directions(case, base, rate):
    _usd(case, base=base, rate=rate)
    assert _assess(case).strict_eligible


@pytest.mark.parametrize("problem,reason", [
    ("missing", "fx_evidence_required"), ("age_missing", "fx_max_age_required"),
    ("too_old", "fx_reference_age_invalid"), ("future_day", "fx_reference_age_invalid"),
    ("late_publication", "fx_publication_after_cutoff"), ("capture", "fx_capture_before_publication"),
    ("zero", "fx_rate_invalid"), ("negative", "fx_rate_invalid"),
    ("wrong_value", "fx_converted_value_mismatch"), ("overflow", "fx_conversion_unrepresentable"),
])
def test_fx_no_fallback(case, problem, reason):
    _usd(case)
    fx = case["observation"].fx
    if problem == "missing":
        _change(case, "observation", fx=None)
    elif problem == "age_missing":
        _change(case, "method", fx_max_age_days=None)
    else:
        changes = {
            "too_old": {"reference_at": fx.reference_at - timedelta(days=1)},
            "future_day": {"reference_at": fx.reference_at + timedelta(days=1)},
            "late_publication": {"published_at": case["valuation_at"] + timedelta(seconds=1)},
            "capture": {"captured_at": fx.published_at - timedelta(seconds=1)},
            "zero": {"rate": Decimal("0")}, "negative": {"rate": Decimal("-1")},
            "wrong_value": {"rate": Decimal("0.9")}, "overflow": {"rate": Decimal("1e999")},
        }[problem]
        _change(case, "observation", fx=fx.model_copy(update=changes))
    result = _assess(case)
    assert not result.strict_eligible and reason in result.reason_codes


def test_fx_age_explicit_and_inclusive(case):
    _usd(case)
    fx = case["observation"].fx
    _change(case, "observation", fx=fx.model_copy(update={"reference_at": fx.reference_at - timedelta(days=7)}))
    _change(case, "method", fx_max_age_days=7)
    assert _assess(case).strict_eligible


def test_usd_quantization_is_explicit_half_even_and_context_independent(case):
    _usd(case, rate="0.800000000000000000004", value="125")
    with localcontext() as ctx:
        ctx.prec = 2
        assert _assess(case).strict_eligible
    _change(case, "point", price_eur=Decimal("100.000000000000000001"))
    assert not _assess(case).strict_eligible


def test_fx_quantization_does_not_lose_a_long_tail_above_the_halfway_tie(case):
    _usd(case, rate="1.0000000000000000005" + "0" * 150 + "1", value="1")
    _change(case, "point", price_eur=Decimal("1.000000000000000001"))
    assert _assess(case).strict_eligible


@pytest.mark.parametrize("value", ["0", "-1", "1e20", "1e-19"])
def test_nonpositive_or_unrepresentable_direct_eur(case, value):
    _change(case, "point", price_eur=Decimal(value))
    _change(case, "observation", value=Decimal(value))
    assert not _assess(case).strict_eligible


@pytest.mark.parametrize("value", [True, False, 1.25, "NaN", "Infinity", "-Infinity"])
def test_decimal_contract_rejects_bool_float_nonfinite(case, value):
    with pytest.raises(ValidationError):
        _change(case, "observation", value=value)
    with pytest.raises(ValidationError):
        _change(case, "point", price_eur=value) if not isinstance(value, (bool, float)) else price_evidence_binding(
            point=case["point"].model_copy(update={"price_eur": value}), identity=case["identity"],
            valuation_at=case["valuation_at"], observation=case["observation"], method=case["method"])


@pytest.mark.parametrize("model,field,value", [
    ("method", "version", True), ("method", "version", 1.0), ("method", "version", "1"),
    ("method", "fx_max_age_days", True), ("method", "fx_max_age_days", 8),
    ("identity", "decimals", True), ("identity", "decimals", 8.0),
    ("method", "timezone", "Unknown/NotAZone"),
    ("method", "daily_time", "12:00:00+00:00"),
    ("observation", "published_at", datetime(2025, 6, 13)),
    ("observation", "published_at", "2025-06-13T00:00:00"),
    ("observation", "evidence_sha256", "G" * 64), ("observation", "locator", " "),
])
def test_strict_contract_fields(case, model, field, value):
    with pytest.raises(ValidationError):
        _change(case, model, **{field: value})


@pytest.mark.parametrize("field", ["valuation_at", "point"])
def test_function_rejects_naive_legacy_times(case, field):
    if field == "valuation_at":
        case[field] = case[field].replace(tzinfo=None)
    else:
        _change(case, field, priced_at=case[field].priced_at.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        _binding(case)


@pytest.mark.parametrize("field", ["acknowledge_original_verified", "acknowledge_scope_limited"])
@pytest.mark.parametrize("value", [1, "true", None])
def test_acknowledgements_are_real_booleans(case, field, value):
    with pytest.raises(ValidationError):
        _approval(case, **{field: value})


@pytest.mark.parametrize("field", ["acknowledge_original_verified", "acknowledge_scope_limited"])
def test_acknowledgements_must_be_explicit(case, field):
    data = _approval(case).model_dump(mode="python")
    del data[field]
    with pytest.raises(ValidationError) as error:
        PriceEvidenceApproval.model_validate(data)
    assert any(item["loc"] == (field,) and item["type"] == "missing" for item in error.value.errors())


def test_import_decision_cannot_be_used_as_admission(case):
    with pytest.raises(ValidationError):
        _approval(case, decision_type="historical_price_import")


@pytest.mark.parametrize("model", ["identity", "observation", "method"])
def test_extra_fields_forbidden(case, model):
    with pytest.raises(ValidationError):
        _change(case, model, arbitrary_secret="not allowed")


def test_missing_changed_and_extra_originals(case):
    sha = case["observation"].evidence_sha256
    original = case["originals"].pop(sha)
    result = _assess(case)
    assert not result.original_integrity_verified and "original_missing" in result.reason_codes
    case["originals"][sha] = original + b" changed"
    assert "original_integrity_mismatch" in _assess(case).reason_codes
    case["originals"][sha] = original
    extra = b"unneeded but integrity checked"
    case["originals"][_hash(extra)] = extra
    assert _assess(case).strict_eligible
    case["originals"][_hash(extra)] = b"changed unneeded bytes"
    assert not _assess(case).strict_eligible


@pytest.mark.parametrize("originals", [
    {"0" * 64: "not bytes"}, {"0" * 64: bytearray(b"not immutable bytes")},
    {"invalid key": b"x"}, {"0" * 64: b"x" * (2 * 1024 * 1024 + 1)},
    {str(i) * 64: b"x" * (2 * 1024 * 1024) for i in range(4)},
])
def test_all_originals_bounded_and_strict(case, originals):
    case["originals"] = originals
    with pytest.raises(ValidationError):
        _assess(case)


def test_empty_original_never_integrity_verified(case):
    case["originals"][_hash(b"")] = b""
    assert not _assess(case).original_integrity_verified


def test_original_size_limits_are_inclusive(case):
    for marker in (b"a", b"b"):
        data = marker * (2 * 1024 * 1024)
        case["originals"][_hash(data)] = data
    assert _assess(case).strict_eligible


def test_pure_function_uses_no_file_network_or_database_calls(case, monkeypatch):
    import builtins
    from pathlib import Path
    import socket

    def forbidden(*args, **kwargs):
        pytest.fail("Admission attempted external I/O")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(Path, "open", forbidden)
        patch.setattr(Path, "read_bytes", forbidden)
        patch.setattr(socket, "socket", forbidden)
        assert _assess(case).strict_eligible


def test_outputs_contain_no_original_bytes_or_transcribed_text(case):
    output = _assess(case).model_dump_json()
    for content in case["originals"].values():
        assert content.decode() not in output
    assert "Synthetic reviewer" not in output
    assert "page 1, row BTC" not in output
    assert PriceEvidenceAdmission.model_validate_json(output).strict_eligible


def test_model_construct_does_not_bypass_nested_validation(case):
    case["observation"] = PriceEvidenceObservation.model_construct(
        **{**case["observation"].model_dump(), "value": float("nan")})
    with pytest.raises(ValidationError):
        _assess(case)


def test_inputs_not_mutated(case):
    before = repr(case)
    _assess(case)
    assert repr(case) == before


@pytest.mark.parametrize("value", ["1", "2"])
def test_base_eur_cannot_be_redefined_by_non_eur_evidence_admission(case, value):
    identity = PriceEvidenceIdentity(asset="EUR", network="fiat", contract="iso4217:EUR", decimals=2)
    original = ("Synthetic EUR/EUR original: " + value).encode()
    sha = _hash(original)
    case["originals"] = {sha: original, case["method"].evidence_sha256: case["originals"][case["method"].evidence_sha256]}
    case["identity"] = identity
    _change(case, "point", asset="EUR", price_eur=Decimal(value))
    _change(case, "observation", identity=identity, value=Decimal(value), evidence_sha256=sha)
    result = _assess(case)
    assert not result.strict_eligible
    assert "eur_identity_uses_legacy_policy" in result.reason_codes


def test_stored_price_fingerprint_is_semantic_and_not_a_method_admission(case):
    from steuerreport_v2.domain.price_evidence import price_point_fingerprint

    point = case["point"]
    original = price_point_fingerprint(point)
    equivalent = point.model_copy(update={"price_eur": Decimal("100.000000000000000000"),
        "confidence": Decimal("0.95000000"),
        "priced_at": point.priced_at.astimezone(timezone := ZoneInfo("Europe/Berlin"))})
    assert equivalent.priced_at.tzinfo == timezone
    assert price_point_fingerprint(equivalent) == original
    assert price_point_fingerprint(point.model_copy(update={"price_id": str(UUID(int=2))})) != original
    assert price_point_fingerprint(point.model_copy(update={"source": "synthetic:other"})) != original
    with pytest.raises(ValidationError):
        price_point_fingerprint(point.model_copy(update={"priced_at": point.priced_at.replace(tzinfo=None)}))
