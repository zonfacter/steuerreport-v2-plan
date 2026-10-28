"""Freigrenzen-Arithmetik, keine persoenliche Steuerfestsetzung oder Freigabe."""
from decimal import Decimal, localcontext

from steuerreport_v2.contracts.private_disposal_threshold import (
    PrivateDisposalThresholdAssessment, PrivateDisposalThresholdRequest,
)


def assess_private_disposal_threshold(year: int, crypto_gain: Decimal,
                                      request: PrivateDisposalThresholdRequest) -> PrivateDisposalThresholdAssessment:
    threshold = Decimal("600" if year <= 2023 else "1000") if 2009 <= year <= 2026 else None
    complete = request.confirm_other_private_disposals_complete and request.other_private_gain_loss_eur is not None
    with localcontext() as arithmetic:
        arithmetic.prec = 60
        total = crypto_gain + request.other_private_gain_loss_eur if complete else None
    reached = total >= threshold if total is not None and threshold is not None else None
    return PrivateDisposalThresholdAssessment(year=year, threshold_eur=threshold,
        calculated_crypto_gain_loss_eur=crypto_gain, other_private_gain_loss_eur=request.other_private_gain_loss_eur,
        total_private_gain_loss_eur=total, threshold_reached=reached,
        status="unsupported_year" if threshold is None else "context_required" if reached is None else "threshold_reached" if reached else "below_threshold",
        methodology="Nur Vergleich der angegebenen privaten Jahresgewinne mit der Freigrenze, kein Freibetragsabzug und keine Einkommensteuerberechnung. Andere private Veraeusserungsgeschaefte bleiben unbekannt, bis Betrag und Vollstaendigkeit ausdruecklich angegeben sind. Daten-, Kostenbasis-, Verlustverrechnungs- und Methodengates bleiben unveraendert; keine Jahresfreigabe.",
        source_refs=["https://www.gesetze-im-internet.de/estg/__23.html",
                     "https://amtliche-handbuecher.bundesfinanzministerium.de/esth/2025/B-Anhaenge/Anhang-04/anhang-4.html"])
