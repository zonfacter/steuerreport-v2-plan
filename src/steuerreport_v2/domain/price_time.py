"""Reine Legacy-Zeitdiagnose: Label und Ledgerzeit sind kein Originalbeleg.

Die positive Nicht-EUR-Belegpipeline ist ausdruecklich nicht implementiert.
Diese Policy aendert weder Preiswahl, Preiszeilen noch steuerliche Formeln.
"""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from steuerreport_v2.contracts.price_time import PriceTimeAssessment


POLICY_ID = "stichtag-temporal-evidence"
POLICY_VERSION = 1
_HISTORY_LABELS = frozenset({
    "coingecko_history", "defillama_coingecko_history", "defillama_token_history",
})


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("price_time_requires_datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _label_kind(source: str | None) -> str:
    if source is None:
        return "unknown"
    if not isinstance(source, str):
        raise TypeError("price_time_source_must_be_string")
    label = source.strip().lower()
    if label.startswith("derived:"):
        return "derived_reference_candidate"
    parts = label.split(":")
    if parts[0] in _HISTORY_LABELS or any(part in {"day", "daily", "daily_reference"} for part in parts):
        return "daily_reference_candidate"
    return "unknown"


def assess_price_time(*, asset: str, price_source: str | None, priced_at: datetime | None,
                      price_eur: Decimal | None, valuation_at: datetime) -> PriceTimeAssessment:
    """Bewerte nur den gegebenen Legacy-Verweis; keine Suche nach neuen Belegen.

    Naive Ledger- und Bewertungszeiten folgen der bisherigen UTC-Konvention.
    Echte EUR-Identitaet ist zeitlos; auch ein synthetischer Epochenanker wird
    deshalb nicht als gespeichertes Kursereignis oder als Beobachtung ausgegeben.
    """
    if not isinstance(asset, str):
        raise TypeError("price_time_asset_must_be_string")
    if price_eur is not None and not isinstance(price_eur, Decimal):
        raise TypeError("price_time_price_must_be_decimal")
    cutoff = _utc(valuation_at)
    reference = _utc(priced_at) if priced_at is not None else None
    reference_kind = _label_kind(price_source)
    if asset == "EUR" and price_source == "fiat:EUR" and price_eur is not None and price_eur.is_finite() and price_eur == 1:
        return PriceTimeAssessment(
            policy_id=POLICY_ID, policy_version=POLICY_VERSION, asset=asset,
            status="fixed_eur_identity", strict_eligible=True, reference_kind="fixed_identity",
            reason_codes=["fixed_eur_identity"],
            explanation=("Echte EUR-Identitaet: ein EUR entspricht einem EUR. Dies ist zeitlos, "
                         "kein beobachtetes Kursereignis; ein Ledger- oder Epochenanker wird nicht als solches ausgegeben."),
        )

    reasons = []
    if priced_at is not None and (priced_at.tzinfo is None or priced_at.utcoffset() is None):
        reasons.append("naive_reference_assumed_utc")
    if valuation_at.tzinfo is None or valuation_at.utcoffset() is None:
        reasons.append("naive_valuation_assumed_utc")
    if price_source == "fiat:EUR":
        reasons.append("fiat_eur_identity_mismatch")

    if price_eur is None:
        status = "missing"
        reasons.append("price_missing")
        explanation = "Kein Preiswert vorhanden; daraus folgt kein Zeit-, Bestands- oder Bewertungsnachweis."
    elif not price_eur.is_finite():
        status = "non_positive"
        reasons.append("price_not_finite")
        explanation = "Der Preiswert ist nicht endlich und daher kein verwendbarer positiver Referenzwert."
    elif price_eur <= 0:
        status = "non_positive"
        reasons.append("price_non_positive")
        explanation = "Der Preiswert ist nicht positiv und daher kein verwendbarer positiver Referenzwert."
    elif reference is None:
        status = "missing"
        reasons.append("stored_reference_time_missing")
        explanation = "Zum vorhandenen Preiswert fehlt die gespeicherte Referenzzeit; der Zeitbeleg bleibt unbekannt."
    elif reference > cutoff:
        status = "future_reference"
        reasons.append("stored_reference_after_valuation")
        explanation = ("Die gespeicherte Referenzzeit liegt nach dem Bewertungszeitpunkt. "
                       "Sie ist kein rechtzeitig belegter Preis- oder Veroeffentlichungszeitpunkt.")
    else:
        status = "unverified_time"
        reasons.append("price_time_evidence_missing")
        if reference_kind == "derived_reference_candidate":
            reasons.append("derived_reference_label_only")
        elif reference_kind == "daily_reference_candidate":
            reasons.append("daily_reference_label_only")
        else:
            reasons.append("source_label_unverified")
        explanation = ("Preis und gespeicherte Referenzzeit sind nur eine vorlaeufige Legacy-Referenz. "
                       "Label, gleiches UTC-Datum oder genaue Uhrzeit belegen weder Beobachtung noch "
                       "Preis-/FX-Veroeffentlichung oder eine freigegebene Bewertungsmethode.")

    return PriceTimeAssessment(
        policy_id=POLICY_ID, policy_version=POLICY_VERSION, asset=asset, status=status,
        strict_eligible=False, reference_kind=reference_kind, stored_reference_at=reference,
        reason_codes=reasons, explanation=explanation,
    )
