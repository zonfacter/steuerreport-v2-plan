"""Synthetische, rein funktionale Zeitbelegproben ohne Datenbank oder Provider."""
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
import json
from pathlib import Path
import socket
import subprocess

import pytest
from pydantic import ValidationError

from steuerreport_v2.contracts.price_time import PriceTimeAssessment
from steuerreport_v2.domain.price_time import POLICY_ID, POLICY_VERSION, assess_price_time


CUTOFF = datetime(2026, 11, 15, 1, tzinfo=UTC)
ANCHOR = datetime(2026, 11, 15, tzinfo=UTC)
EVIDENCE_FIELDS = (
    "observed_at", "period_start", "period_end", "price_published_at", "fx_published_at",
    "valuation_method_id", "valuation_method_version", "price_evidence_ref", "fx_evidence_ref",
)


def assess(**overrides):
    arguments = dict(asset="SYNTHETIC", price_source="unknown-source", priced_at=ANCHOR,
                     price_eur=Decimal("1"), valuation_at=CUTOFF)
    arguments.update(overrides)
    return assess_price_time(**arguments)


def assert_unknown_evidence(result):
    payload = result.model_dump(mode="json")
    for field in EVIDENCE_FIELDS:
        assert field in payload and payload[field] is None
    assert json.loads(result.model_dump_json())["observed_at"] is None
    assert result.policy_id == POLICY_ID == "stichtag-temporal-evidence"
    assert result.policy_version == POLICY_VERSION == 1


@pytest.mark.parametrize("source,kind", [
    (None, "unknown"), ("", "unknown"), ("unfamiliar-vendor", "unknown"),
    ("observed:intraday:verified", "unknown"), ("manual:historical-evidence:v1:abc", "unknown"),
    ("coingecko_history", "daily_reference_candidate"),
    ("coingecko_history:usd_eur:v1_fx_cache:2026-11-14", "daily_reference_candidate"),
    ("defillama_token_history:usd_eur:v1_fx_cache:2026-11-01", "daily_reference_candidate"),
    ("defillama_coingecko_history:usd_eur:as_of_gate", "daily_reference_candidate"),
    ("historical:v2:vendor:token:day:2026-11-15:evidence:abc", "daily_reference_candidate"),
    ("vendor:daily", "daily_reference_candidate"),
    ("derived:event_quote", "derived_reference_candidate"),
    ("  DeRiVeD:event_quote:daily  ", "derived_reference_candidate"),
    ("derived:blockpit_solana_quote:intraday", "derived_reference_candidate"),
])
def test_label_is_only_a_hint_never_provenance(source, kind):
    result = assess(price_source=source)
    assert result.status == "unverified_time" and not result.strict_eligible
    assert result.reference_kind == kind and result.stored_reference_at == ANCHOR
    assert "price_time_evidence_missing" in result.reason_codes
    assert_unknown_evidence(result)


@pytest.mark.parametrize("at", [ANCHOR, CUTOFF, CUTOFF - timedelta(microseconds=1),
                                ANCHOR - timedelta(days=10), ANCHOR.replace(tzinfo=None)])
@pytest.mark.parametrize("source", ["coingecko_history", "arbitrary-exact-intraday", "derived:event_quote"])
def test_same_day_exact_time_prior_day_and_small_reference_never_grant_strict(at, source):
    result = assess(priced_at=at, price_source=source, price_eur=Decimal("0.000000000000000001"))
    assert result.status == "unverified_time" and result.strict_eligible is False
    assert_unknown_evidence(result)


@pytest.mark.parametrize("value", [Decimal("0"), Decimal("-0"), Decimal("-1"),
                                  Decimal("NaN"), Decimal("sNaN"), Decimal("Infinity"), Decimal("-Infinity")])
def test_nonpositive_and_nonfinite_are_distinct_from_missing_and_do_not_compare_nan(value):
    with localcontext() as arithmetic:
        arithmetic.traps[InvalidOperation] = True
        result = assess(price_eur=value)
    assert result.status == "non_positive" and not result.strict_eligible
    assert ("price_not_finite" if not value.is_finite() else "price_non_positive") in result.reason_codes
    assert_unknown_evidence(result)


@pytest.mark.parametrize("overrides,reason", [
    ({"price_eur": None}, "price_missing"),
    ({"priced_at": None}, "stored_reference_time_missing"),
    ({"price_eur": None, "priced_at": None}, "price_missing"),
])
def test_missing_value_or_reference_is_not_final_evidence(overrides, reason):
    result = assess(**overrides)
    assert result.status == "missing" and result.strict_eligible is False
    assert reason in result.reason_codes
    assert_unknown_evidence(result)


@pytest.mark.parametrize("at,cutoff,status", [
    (CUTOFF + timedelta(microseconds=1), CUTOFF, "future_reference"),
    (CUTOFF.replace(tzinfo=None) + timedelta(seconds=1), CUTOFF, "future_reference"),
    (CUTOFF, CUTOFF.replace(tzinfo=None), "unverified_time"),
    (datetime(2026, 11, 15, 2, tzinfo=timezone(timedelta(hours=2))), CUTOFF, "unverified_time"),
    (datetime(2026, 11, 14, 23, tzinfo=timezone(timedelta(hours=-3))), CUTOFF, "future_reference"),
])
def test_future_comparison_is_exact_and_utc_not_calendar_date(at, cutoff, status):
    result = assess(priced_at=at, valuation_at=cutoff)
    assert result.status == status and not result.strict_eligible
    expected = at.replace(tzinfo=UTC) if at.tzinfo is None else at.astimezone(UTC)
    assert result.stored_reference_at == expected
    assert result.stored_reference_at.tzinfo == UTC
    assert_unknown_evidence(result)


def test_naive_convention_is_explicit_not_an_observed_timestamp():
    result = assess(priced_at=ANCHOR.replace(tzinfo=None), valuation_at=CUTOFF.replace(tzinfo=None))
    assert {"naive_reference_assumed_utc", "naive_valuation_assumed_utc"} <= set(result.reason_codes)
    assert result.stored_reference_at == ANCHOR and result.observed_at is None


@pytest.mark.parametrize("at", [None, datetime(1970, 1, 1, tzinfo=UTC), ANCHOR,
                                CUTOFF + timedelta(days=1), ANCHOR.replace(tzinfo=None)])
@pytest.mark.parametrize("value", [Decimal("1"), Decimal("1.0000000000000000000000000")])
def test_exact_eur_identity_is_timeless_not_a_quote_event(at, value):
    result = assess(asset="EUR", price_source="fiat:EUR", price_eur=value, priced_at=at)
    assert result.status == "fixed_eur_identity" and result.strict_eligible is True
    assert result.reference_kind == "fixed_identity" and result.stored_reference_at is None
    assert_unknown_evidence(result)


@pytest.mark.parametrize("asset,source,value", [
    ("USDT", "fiat:EUR", Decimal("1")), ("USD", "fiat:EUR", Decimal("1")),
    ("USDC", "fiat:EUR", Decimal("1")), ("SYNTHETIC", "fiat:EUR", Decimal("1")),
    ("EUR", "market:EUR", Decimal("1")), ("EUR", "FIAT:EUR", Decimal("1")),
    ("EUR", "fiat:eur", Decimal("1")), ("EUR", "fiat:EUR ", Decimal("1")),
    ("EUR", "fiat:EUR:verified", Decimal("1")), ("eur", "fiat:EUR", Decimal("1")),
    (" EUR ", "fiat:EUR", Decimal("1")), ("EUR", "fiat:EUR", Decimal("1.00000000000000000001")),
    ("EUR", "fiat:EUR", Decimal("0.99999999999999999999")),
    ("EUR", "fiat:EUR", Decimal("NaN")), ("EUR", "fiat:EUR", Decimal("sNaN")),
    ("EUR", "fiat:EUR", None), ("EUR", "fiat:EUR", Decimal("0")),
])
def test_eur_label_and_stablecoin_abuse_cannot_become_identity(asset, source, value):
    result = assess(asset=asset, price_source=source, price_eur=value)
    assert result.status != "fixed_eur_identity" and result.strict_eligible is False
    assert result.reference_kind != "fixed_identity"
    assert_unknown_evidence(result)


def test_decimal_context_never_rounds_a_non_identity_into_identity():
    with localcontext() as arithmetic:
        arithmetic.prec = 2
        result = assess(asset="EUR", price_source="fiat:EUR", price_eur=Decimal("1.00000000000000000001"))
    assert result.status == "unverified_time" and not result.strict_eligible


@pytest.mark.parametrize("value", [1, True, 1.0, "1"])
def test_non_decimal_input_is_not_coerced_to_eur_proof(value):
    with pytest.raises(TypeError, match="price_time_price_must_be_decimal"):
        assess(asset="EUR", price_source="fiat:EUR", price_eur=value)


@pytest.mark.parametrize("field,value", [("asset", None), ("price_source", 1),
                                         ("priced_at", "2026-11-15T00:00:00Z"), ("valuation_at", None)])
def test_invalid_typed_inputs_are_rejected_without_echo(field, value):
    with pytest.raises(TypeError):
        assess(**{field: value})


@pytest.mark.parametrize("field", EVIDENCE_FIELDS)
def test_model_cannot_manufacture_legacy_observation_or_method_proof(field):
    payload = assess().model_dump()
    payload[field] = 1 if field == "valuation_method_version" else "synthetic-ref" if field.endswith("_ref") or field == "valuation_method_id" else ANCHOR
    with pytest.raises(ValidationError):
        PriceTimeAssessment.model_validate(payload)


def test_model_version_eligibility_and_identity_are_bound():
    payload = assess().model_dump()
    for changed in ({"strict_eligible": True}, {"strict_eligible": "yes"}, {"reference_kind": "fixed_identity"},
                    {"policy_version": True}, {"policy_version": 2}, {"confidence": "1"}):
        with pytest.raises(ValidationError):
            PriceTimeAssessment.model_validate({**payload, **changed})


def test_no_io_network_database_or_writer_needed(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Pure time assessment must not perform IO")
    with monkeypatch.context() as guard:
        guard.setattr(Path, "open", forbidden)
        guard.setattr(socket.socket, "connect", forbidden)
        guard.setattr(subprocess, "Popen", forbidden)
        result = assess(price_source="/private/synthetic-source?token=DO-NOT-ECHO")
    assert result.status == "unverified_time"
    assert "/private/" not in result.model_dump_json() and "DO-NOT-ECHO" not in result.model_dump_json()


def test_inputs_are_unchanged_and_repeated_calls_are_deterministic():
    inputs = dict(asset="SYNTHETIC", price_source="derived:event_quote", price_eur=Decimal("2.50"),
                  priced_at=ANCHOR, valuation_at=CUTOFF)
    before = dict(inputs)
    first = assess_price_time(**inputs)
    assert inputs == before and assess_price_time(**inputs) == first
    with pytest.raises(ValidationError):
        first.strict_eligible = True
