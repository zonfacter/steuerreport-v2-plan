from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from steuerreport_v2.contracts.prices import PricePoint
from steuerreport_v2.contracts.swap_valuation import (
    CryptoSwapValuationDeltaRow,
    CryptoSwapValuationReviewReport,
    CryptoSwapValuationStatus,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup
from steuerreport_v2.domain.tax import STABLE_VALUE_ANCHOR_ASSETS, TaxService
from steuerreport_v2.domain.tax_time import reporting_tax_year


class CryptoSwapValuationReviewService:
    MATERIAL_DELTA_EUR = Decimal("0.01")

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def review(
        self,
        *,
        limit: int = 200,
        year: int | None = None,
    ) -> CryptoSwapValuationReviewReport:
        lookup = HistoricalPriceLookup(self.store)
        candidates = TaxService(self.store).crypto_to_crypto_valuation_events()
        if year is not None:
            candidates = [
                event
                for event in candidates
                if reporting_tax_year(self._as_utc(event.event_time)) == year
            ]
        rows = [self._row(event, lookup) for event in candidates]
        blocked_rows = [row for row in rows if row.blocks_bmf_valuation]
        material_rows = [row for row in rows if row.status == "material_delta"]
        policy_rows = [
            row
            for row in rows
            if row.status in {"material_delta", "policy_mismatch_no_material_delta"}
        ]
        fallback_rows = [
            row for row in rows if row.status == "received_price_fallback_review"
        ]
        missing_rows = [row for row in rows if row.status == "missing_both_prices"]
        aligned_rows = [row for row in rows if row.status == "aligned_received_primary"]
        rows.sort(key=self._sort_key)
        selected = rows[: max(1, min(limit, 5000))]

        findings: list[str] = []
        if policy_rows:
            findings.append(
                f"{len(policy_rows)} Krypto-zu-Krypto-Erwerbe verwenden in der aktiven V2-Regel "
                "noch nicht den erhaltenen Token als primaere Bewertungsbasis."
            )
        if material_rows:
            findings.append(
                f"{len(material_rows)} Transaktionen haben dadurch ein direktes Wertdelta von "
                "mindestens 0,01 EUR. Das Delta ist noch keine endgueltige Jahressteuerdifferenz."
            )
        if fallback_rows:
            findings.append(
                f"Bei {len(fallback_rows)} Transaktionen fehlt intern ein Preis des erhaltenen "
                "Tokens. Der Preis des hingegebenen Tokens ist erst nach dokumentierter "
                "Nicht-Ermittelbarkeit ein belastbarer BMF-Fallback."
            )
        if missing_rows:
            findings.append(
                f"{len(missing_rows)} Transaktionen besitzen weder fuer den erhaltenen noch den "
                "hingegebenen Token einen Preis im aktuellen Ledger."
            )
        if not blocked_rows:
            findings.append(
                "Alle Krypto-zu-Krypto-Kandidaten verwenden bereits eine belegte erhaltene "
                "Bewertungsbasis."
            )

        return CryptoSwapValuationReviewReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            year=year,
            strict_ready=not blocked_rows,
            candidates_count=len(rows),
            aligned_count=len(aligned_rows),
            policy_mismatch_count=len(policy_rows),
            material_delta_count=len(material_rows),
            received_price_fallback_review_count=len(fallback_rows),
            missing_both_prices_count=len(missing_rows),
            current_value_eur=sum((row.current_value_eur for row in rows), Decimal("0")),
            bmf_preview_value_eur=sum(
                (row.bmf_preview_value_eur for row in rows), Decimal("0")
            ),
            signed_value_delta_eur=sum((row.value_delta_eur for row in rows), Decimal("0")),
            absolute_value_delta_eur=sum(
                (abs(row.value_delta_eur) for row in rows), Decimal("0")
            ),
            affected_years=sorted({row.reporting_year for row in blocked_rows}),
            rows_returned=len(selected),
            rows=selected,
            findings=findings,
            next_actions=(
                [
                    "Erhaltenen Tokenpreis und Quelle fuer Materialdeltas und Fallback-Gruppen belegen.",
                    "Jahres-, Asset- und Quellen-Deltas in einem isolierten Tax-Parallel-Lauf berechnen.",
                    "Preisrangfolge erst nach fachlicher Abnahme gemeinsam mit Wallet-FIFO und Steuersphaere aktivieren.",
                ]
                if blocked_rows
                else []
            ),
            current_policy=(
                "Bei positiven Krypto-zu-Krypto-Trades nutzt V2 den erhaltenen Token nur fuer "
                "Stable-Value-Anker; sonst wird der hingegebene Quote-Token bewertet."
            ),
            bmf_preview_policy=(
                "BMF Rn. 58: Marktwert des erhaltenen Tokens im Tauschzeitpunkt zuerst; nur bei "
                "belegter Nicht-Ermittelbarkeit Marktwert des hingegebenen Tokens als Fallback."
            ),
            methodology=(
                "Read-only Delta-Audit auf denselben positiven Trade-Events, die der aktive "
                "TaxService nach Service-Swap-Normalisierung verarbeitet. Preiswahl erfolgt mit "
                "dem unveraenderten HistoricalPriceLookup. Das Wertdelta wirkt gleichzeitig auf "
                "den unmittelbaren Veraeusserungserloes des hingegebenen Tokens und die "
                "Anschaffungskosten des erhaltenen Lots, ist aber ohne FIFO-Parallelrechnung "
                "keine endgueltige Gewinn-, Verlust- oder Steuerdifferenz. Keine Daten werden geschrieben."
            ),
        )

    def _row(
        self,
        event: object,
        lookup: HistoricalPriceLookup,
    ) -> CryptoSwapValuationDeltaRow:
        received_asset = str(getattr(event, "asset")).upper()
        given_asset = str(getattr(event, "quote_asset")).upper()
        received_quantity = abs(Decimal(str(getattr(event, "quantity"))))
        given_quantity = abs(Decimal(str(getattr(event, "quote_quantity"))))
        event_time = self._as_utc(getattr(event, "event_time"))
        received_price = lookup.at_or_before(received_asset, event_time)
        given_price = lookup.at_or_before(given_asset, event_time)
        received_value = self._value(received_price, received_quantity)
        given_value = self._value(given_price, given_quantity)

        if received_asset in STABLE_VALUE_ANCHOR_ASSETS and received_value is not None:
            current_value = received_value
            current_basis = "received_stable_anchor"
        elif given_value is not None:
            current_value = given_value
            current_basis = "given_quote_asset"
        else:
            current_value = Decimal("0")
            current_basis = "missing_current_price"

        if received_value is not None:
            preview_value = received_value
            preview_basis = "received_asset_market_value"
        elif given_value is not None:
            preview_value = given_value
            preview_basis = "given_asset_fallback_review"
        else:
            preview_value = Decimal("0")
            preview_basis = "missing_both_prices"

        delta = preview_value - current_value
        status, reason = self._status(
            received_asset=received_asset,
            received_price=received_price,
            given_price=given_price,
            delta=delta,
        )
        return CryptoSwapValuationDeltaRow(
            event_id=str(getattr(event, "event_id")),
            reporting_year=reporting_tax_year(event_time),
            event_time=event_time.isoformat(),
            source=str(getattr(event, "source")),
            source_ref=self._optional_text(getattr(event, "source_ref", None)),
            account=self._optional_text(getattr(event, "account", None)),
            tx_id=self._optional_text(getattr(event, "tx_id", None)),
            received_asset=received_asset,
            received_quantity=received_quantity,
            given_asset=given_asset,
            given_quantity=given_quantity,
            current_basis=current_basis,
            bmf_preview_basis=preview_basis,
            current_value_eur=current_value,
            bmf_preview_value_eur=preview_value,
            value_delta_eur=delta,
            received_price_eur=received_price.price_eur if received_price else None,
            received_price_source=received_price.source if received_price else None,
            received_priced_at=self._price_time(received_price),
            received_price_confidence=received_price.confidence if received_price else None,
            given_price_eur=given_price.price_eur if given_price else None,
            given_price_source=given_price.source if given_price else None,
            given_priced_at=self._price_time(given_price),
            given_price_confidence=given_price.confidence if given_price else None,
            status=status,
            blocks_bmf_valuation=status != "aligned_received_primary",
            reason=reason,
        )

    def _status(
        self,
        *,
        received_asset: str,
        received_price: PricePoint | None,
        given_price: PricePoint | None,
        delta: Decimal,
    ) -> tuple[CryptoSwapValuationStatus, str]:
        if received_price is None and given_price is None:
            return (
                "missing_both_prices",
                "Keine der beiden Bewertungsseiten ist im Preisledger verfuegbar.",
            )
        if received_price is None:
            return (
                "received_price_fallback_review",
                "Erhaltener Tokenpreis fehlt; Quote-Token ist nur bei belegter Nicht-Ermittelbarkeit Fallback.",
            )
        if received_asset in STABLE_VALUE_ANCHOR_ASSETS:
            return (
                "aligned_received_primary",
                "Die aktive Regel verwendet bereits den erhaltenen Stable-Value-Anker.",
            )
        if abs(delta) >= self.MATERIAL_DELTA_EUR:
            return (
                "material_delta",
                "Erhaltener und hingegebener Token ergeben nach aktueller Preisquelle ein materielles Wertdelta.",
            )
        return (
            "policy_mismatch_no_material_delta",
            "Die Werte sind innerhalb eines Cents gleich, die aktive Quellenrangfolge bleibt aber abweichend.",
        )

    @staticmethod
    def _value(price: PricePoint | None, quantity: Decimal) -> Decimal | None:
        return None if price is None else price.price_eur * quantity

    @staticmethod
    def _as_utc(value: object) -> datetime:
        if not isinstance(value, datetime):
            raise TypeError("event_time must be datetime")
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _price_time(price: PricePoint | None) -> str | None:
        if price is None:
            return None
        value = price.priced_at
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()

    @staticmethod
    def _optional_text(value: object) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _sort_key(row: CryptoSwapValuationDeltaRow) -> tuple[int, Decimal, int, str]:
        priority = {
            "material_delta": 0,
            "missing_both_prices": 1,
            "received_price_fallback_review": 2,
            "policy_mismatch_no_material_delta": 3,
            "aligned_received_primary": 4,
        }[row.status]
        return (priority, -abs(row.value_delta_eur), row.reporting_year, row.event_id)
