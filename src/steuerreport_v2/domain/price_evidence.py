"""Reine Zulassungspruefung; der Aufrufer muss die gespeicherte Reviewbindung liefern.

Originalhashes belegen Integritaet, nicht den Inhalt einer Transkription. Ein
Erfolg bezeichnet ausschliesslich die explizit menschlich bestaetigte Zuordnung.
USD/FX wird explizit auf DECIMAL(38,18) mit ROUND_HALF_EVEN quantisiert.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime, time, timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, DivisionByZero, InvalidOperation, Overflow, localcontext
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, RootModel, field_validator, model_validator

from steuerreport_v2.contracts.price_evidence import (
    EvidenceDatetime,
    EvidenceDecimal,
    EvidenceHash,
    PriceEvidenceAdmission,
    PriceEvidenceApproval,
    PriceEvidenceIdentity,
    PriceEvidenceMethod,
    PriceEvidenceObservation,
)
from steuerreport_v2.contracts.prices import PricePoint


POLICY_ID = "stichtag-price-evidence-admission"
POLICY_VERSION = 1
_QUANTUM = Decimal("0.000000000000000001")
_LIMIT = Decimal("1e20")


class _Point(PricePoint):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    price_eur: EvidenceDecimal
    confidence: EvidenceDecimal
    priced_at: EvidenceDatetime

    @field_validator("asset", "source", "price_id", mode="before")
    @classmethod
    def required_text(cls, value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("evidence_point_text_invalid")
        return value


class _Inputs(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    point: _Point
    identity: PriceEvidenceIdentity
    valuation_at: EvidenceDatetime
    observation: PriceEvidenceObservation
    method: PriceEvidenceMethod


class _Originals(RootModel[dict[EvidenceHash, bytes]]):
    model_config = ConfigDict(hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def bounded_bytes(cls, value):
        if not isinstance(value, Mapping):
            raise ValueError("evidence_originals_mapping_required")
        total = 0
        for content in value.values():
            if type(content) is not bytes:
                raise ValueError("evidence_original_bytes_required")
            if len(content) > 2 * 1024 * 1024:
                raise ValueError("evidence_original_size_exceeded")
            total += len(content)
        if total > 6 * 1024 * 1024:
            raise ValueError("evidence_original_total_exceeded")
        return dict(value)


def _document(value):
    if isinstance(value, BaseModel):
        return _document(value.model_dump(mode="python", warnings=False))
    if isinstance(value, dict):
        return {key: _document(item) for key, item in value.items()}
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="microseconds")
    if isinstance(value, time):
        return value.isoformat(timespec="microseconds")
    if isinstance(value, Decimal):
        # Decimal.normalize() would round under the caller's decimal context.
        if value == 0:
            return "0"
        digits = value.as_tuple()
        coefficient = list(digits.digits)
        exponent = digits.exponent
        while coefficient[-1] == 0:
            coefficient.pop()
            exponent += 1
        return ("-" if digits.sign else "") + "".join(map(str, coefficient)) + "e" + str(exponent)
    return value


def _inputs(*, point, identity, valuation_at, observation, method):
    # Revalidate also mutable legacy PricePoint instances and model_construct inputs.
    return _Inputs.model_validate({
        "point": _dump(point),
        "identity": _dump(identity), "valuation_at": valuation_at,
        "observation": _dump(observation), "method": _dump(method),
    })


def _dump(value):
    return value.model_dump(mode="python", warnings=False) if isinstance(value, BaseModel) else value


def _binding(inputs):
    payload = {"policy_id": POLICY_ID, "policy_version": POLICY_VERSION, "inputs": _document(inputs)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def price_evidence_binding(*, point: PricePoint, identity: PriceEvidenceIdentity,
                           valuation_at: datetime, observation: PriceEvidenceObservation,
                           method: PriceEvidenceMethod) -> str:
    """Kanonische Bindung aller Inputs, ohne eine Zustimmung zu erzeugen."""
    return _binding(_inputs(point=point, identity=identity, valuation_at=valuation_at,
                            observation=observation, method=method))


def price_point_fingerprint(point: PricePoint) -> str:
    """Bind the stored price identity; this is not an observation or admission."""
    normalized = _Point.model_validate(_dump(point))
    payload = {"policy_id": "historical-price-point", "policy_version": 1,
               "point": _document(normalized)}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _stored_value(value):
    if value <= 0 or value >= _LIMIT:
        return False
    try:
        with localcontext(_arithmetic_context(80)):
            return value.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN) == value
    except InvalidOperation:
        return False


def _arithmetic_context(precision):
    return Context(prec=precision, rounding=ROUND_HALF_EVEN, Emin=-999999, Emax=999999,
                   capitals=1, clamp=0, flags=[], traps=[InvalidOperation, DivisionByZero, Overflow])


def _local_day_start(day, zone):
    # Fold 0/1 cover repeated midnight and the two sides of a midnight gap.
    midnight = datetime.combine(day, time(), zone)
    candidates = [midnight.replace(fold=fold).astimezone(UTC) for fold in (0, 1)]
    return min((value for value in candidates if value.astimezone(zone).date() >= day), default=None)


def _daily_reasons(inputs):
    obs, method = inputs.observation, inputs.method
    reasons = []
    if obs.observed_at is not None or obs.period_start is None or obs.period_end is None:
        return ["daily_period_required"]
    zone = ZoneInfo(method.timezone)
    start = obs.period_start.astimezone(zone)
    try:
        next_date = start.date() + timedelta(days=1)
    except OverflowError:
        return ["daily_period_not_one_local_day"]
    expected_start = _local_day_start(start.date(), zone)
    expected_end = _local_day_start(next_date, zone)
    if obs.period_start != expected_start or obs.period_end != expected_end:
        reasons.append("daily_period_not_one_local_day")
    if not (obs.period_start <= inputs.valuation_at < obs.period_end
            and obs.period_start <= inputs.point.priced_at < obs.period_end):
        reasons.append("daily_reference_outside_period")
    if method.daily_statistic is None:
        reasons.append("daily_statistic_required")
    if method.daily_statistic in {"daily_mean", "daily_close"} and obs.published_at < obs.period_end:
        reasons.append("price_publication_before_period_end")
    if (method.daily_statistic == "daily_fixed_time") != (method.daily_time is not None):
        reasons.append("daily_time_mismatch")
    if method.daily_time is not None:
        fixed = datetime.combine(start.date(), method.daily_time, zone)
        # A nonexistent local wall time cannot document a real fixed-time quote.
        if fixed.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != fixed.replace(tzinfo=None):
            reasons.append("daily_time_nonexistent")
        if fixed.replace(fold=0).utcoffset() != fixed.replace(fold=1).utcoffset():
            reasons.append("daily_time_ambiguous")
        if method.daily_statistic == "daily_fixed_time" and obs.published_at < fixed.astimezone(UTC):
            reasons.append("price_publication_before_daily_fixed_time")
    return reasons


def _reasons(inputs):
    point, identity, obs, method = inputs.point, inputs.identity, inputs.observation, inputs.method
    reasons = []
    if point.asset == "EUR" or identity.asset == "EUR" or obs.identity.asset == "EUR":
        reasons.append("eur_identity_uses_legacy_policy")
    if identity != obs.identity or point.asset != identity.asset:
        reasons.append("asset_identity_mismatch")
    if not _stored_value(point.price_eur) or obs.value <= 0:
        reasons.append("price_value_invalid")
    if not 0 <= point.confidence <= 1:
        reasons.append("price_confidence_invalid")
    if obs.kind != method.kind:
        reasons.append("reference_kind_mismatch")
    if obs.kind == "observed_quote":
        if obs.observed_at is None or obs.period_start is not None or obs.period_end is not None:
            reasons.append("observed_quote_time_invalid")
        elif point.priced_at != obs.observed_at:
            reasons.append("observed_quote_time_mismatch")
        if obs.observed_at is not None and obs.published_at < obs.observed_at:
            reasons.append("price_publication_before_observation")
        if method.daily_statistic is not None or method.daily_time is not None:
            reasons.append("observed_quote_has_daily_method")
        if method.availability_rule != "available_at_cutoff":
            reasons.append("retrospective_requires_daily_reference")
    else:
        reasons.extend(_daily_reasons(inputs))
    if obs.captured_at < obs.published_at:
        reasons.append("price_capture_before_publication")
    if method.availability_rule == "available_at_cutoff":
        reference = obs.observed_at if obs.kind == "observed_quote" else obs.period_end
        if reference is not None and reference > inputs.valuation_at:
            reasons.append("price_reference_after_cutoff")
        if point.priced_at > inputs.valuation_at:
            reasons.append("stored_reference_after_cutoff")
        if obs.published_at > inputs.valuation_at:
            reasons.append("price_publication_after_cutoff")
    if obs.quote_currency == "EUR":
        if obs.fx is not None:
            reasons.append("direct_eur_has_fx")
        if not _stored_value(obs.value) or obs.value != point.price_eur:
            reasons.append("price_value_mismatch")
    elif obs.fx is None:
        reasons.append("fx_evidence_required")
    else:
        fx = obs.fx
        if method.fx_max_age_days is None:
            reasons.append("fx_max_age_required")
        else:
            zone = ZoneInfo(method.timezone)
            reference = obs.observed_at if obs.kind == "observed_quote" else obs.period_start
            if reference is not None:
                age = (reference.astimezone(zone).date() - fx.reference_at.astimezone(zone).date()).days
                if not 0 <= age <= method.fx_max_age_days:
                    reasons.append("fx_reference_age_invalid")
        if fx.captured_at < fx.published_at:
            reasons.append("fx_capture_before_publication")
        if fx.published_at < fx.reference_at:
            reasons.append("fx_publication_before_reference")
        if method.availability_rule == "available_at_cutoff":
            if fx.reference_at > inputs.valuation_at:
                reasons.append("fx_reference_after_cutoff")
            if fx.published_at > inputs.valuation_at:
                reasons.append("fx_publication_after_cutoff")
        if fx.rate <= 0:
            reasons.append("fx_rate_invalid")
        else:
            try:
                precision = max(80, len(obs.value.as_tuple().digits) + len(fx.rate.as_tuple().digits) + 80)
                with localcontext(_arithmetic_context(precision)):
                    converted = obs.value * fx.rate if fx.base == "USD" else obs.value / fx.rate
                    if not 0 < converted < _LIMIT:
                        raise InvalidOperation
                    converted = converted.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN)
                if converted <= 0 or converted != point.price_eur:
                    reasons.append("fx_converted_value_mismatch")
            except (ArithmeticError, ValueError):
                reasons.append("fx_conversion_unrepresentable")
    return reasons


def assess_price_evidence(*, point: PricePoint, identity: PriceEvidenceIdentity,
                          valuation_at: datetime, observation: PriceEvidenceObservation,
                          method: PriceEvidenceMethod, approval: PriceEvidenceApproval | None,
                          originals: Mapping[str, bytes]) -> PriceEvidenceAdmission:
    """Pruefe ausschliesslich gelieferte Daten; keine Suche oder automatische Freigabe."""
    inputs = _inputs(point=point, identity=identity, valuation_at=valuation_at,
                     observation=observation, method=method)
    binding = _binding(inputs)
    originals = _Originals.model_validate(originals).root
    approval = PriceEvidenceApproval.model_validate(_dump(approval)) if approval is not None else None
    obs = inputs.observation
    required = {obs.evidence_sha256, inputs.method.evidence_sha256}
    if obs.fx is not None:
        required.add(obs.fx.evidence_sha256)
    reasons = []
    if not required.issubset(originals):
        reasons.append("original_missing")
    if any(not data or hashlib.sha256(data).hexdigest() != sha for sha, data in originals.items()):
        reasons.append("original_integrity_mismatch")
    integrity = not reasons
    reasons.extend(_reasons(inputs))
    if approval is None:
        reasons.append("approval_missing")
    else:
        if approval.binding_sha256 != binding:
            reasons.append("approval_binding_mismatch")
        if approval.updated_at is not None:
            reasons.append("approval_updated")
        if not approval.acknowledge_original_verified or not approval.acknowledge_scope_limited:
            reasons.append("approval_acknowledgement_missing")
        captured = [obs.captured_at] + ([obs.fx.captured_at] if obs.fx is not None else [])
        if approval.approved_at < max(captured):
            reasons.append("approval_before_capture")
    positive = not reasons
    return PriceEvidenceAdmission(
        policy_id=POLICY_ID, policy_version=POLICY_VERSION,
        status="human_approved" if positive else ("not_approved" if approval is None else "rejected"),
        strict_eligible=positive, binding_sha256=binding,
        decision_id=approval.decision_id if approval is not None else None,
        reason_codes=list(dict.fromkeys(reasons)), original_integrity_verified=integrity,
        evidence_origin="operator_confirmed" if positive else "unverified",
    )
