from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
import json
from pathlib import Path

from steuerreport_v2.contracts.divorce import (
    DivorceCapitalContributionRow,
    DivorceCapitalFlowGate,
    DivorceCapitalOutflowRow,
)
from steuerreport_v2.contracts.events import CanonicalEvent
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.divorce_service_routes import (
    DivorceServiceRouteEvidenceService,
)
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup


class DivorceCapitalFlowService:
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    ALCHEMY_AUDIT_PATH = (
        PROJECT_ROOT / "var/solana_tx_alchemy_audits/latest_all_tx_alchemy_audit.json"
    )
    TAX_NEUTRAL_STATUSES = {
        "tax_neutral_transfer_reviewed",
        "transfer_neutral_fifo_carry_forward_reviewed",
        "transfer_neutral_fifo_carried",
    }
    EXTERNAL_DISTRIBUTION_STATUSES = {
        "external_distribution_confirmed",
        "external_withdrawal_confirmed",
    }
    SERVICE_PROGRAM_IDS = {
        "PERPHjGBqRHArX4DySjwM6UJHiR3sWAatqfdBS2qQJu",
        "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
        "JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB",
    }
    INTERNAL_OPERATION_MARKERS = (
        "simple earn",
        "staking purchase",
        "staking redemption",
        "sol staking",
        "auto-invest",
        "redeem positions",
    )

    def __init__(
        self,
        store: DuckDbStore,
        *,
        service_route_evidence_service: DivorceServiceRouteEvidenceService
        | None = None,
    ) -> None:
        self.store = store
        self.service_route_evidence_service = (
            service_route_evidence_service or DivorceServiceRouteEvidenceService(store)
        )

    def report(
        self,
        *,
        cutoff_at: datetime,
        valuation_at: datetime,
        opening_value_eur: Decimal,
        closing_value_eur: Decimal,
        binance_contributions_eur: Decimal,
        confirmed_onramp_contributions_eur: Decimal,
        provisional_onramp_contributions_eur: Decimal,
        materiality_threshold_eur: Decimal,
    ) -> DivorceCapitalFlowGate:
        cutoff = self._naive(cutoff_at)
        valuation = self._naive(valuation_at)
        events = [
            event
            for event in self.store.list_canonical_events()
            if cutoff < self._naive(event.event_time) <= valuation
        ]
        transfers_in = defaultdict(list)
        events_by_tx: defaultdict[str, list[CanonicalEvent]] = defaultdict(list)
        for event in events:
            if event.event_type == "transfer" and event.quantity > 0:
                transfers_in[event.asset.upper()].append(event)
            if event.tx_id:
                events_by_tx[event.tx_id].append(event)

        negative_transfers = [
            event
            for event in events
            if event.event_type == "transfer" and event.quantity < 0
        ]
        raw_payloads = self._raw_payloads(negative_transfers)
        (
            tax_neutral_ids,
            external_distribution_ids,
            internal_service_loss_ids,
            decision_evidence,
        ) = self._decision_evidence(
            {event.tx_id for event in negative_transfers if event.tx_id}
        )
        alchemy_rows = self._alchemy_rows(
            {event.tx_id for event in negative_transfers if event.tx_id}
        )
        price_lookup = HistoricalPriceLookup(self.store)
        outflows = [
            self._classify_outflow(
                event=event,
                incoming=transfers_in[event.asset.upper()],
                tx_events=events_by_tx.get(event.tx_id or "", []),
                raw_payload=raw_payloads.get(event.raw_object_id or "", {}),
                tax_neutral_ids=tax_neutral_ids,
                external_distribution_ids=external_distribution_ids,
                internal_service_loss_ids=internal_service_loss_ids,
                decision_evidence=decision_evidence,
                alchemy_row=alchemy_rows.get(event.tx_id or "", {}),
                price_lookup=price_lookup,
                materiality_threshold_eur=materiality_threshold_eur,
            )
            for event in negative_transfers
        ]
        contributions = self._contributions(
            binance_contributions_eur=binance_contributions_eur,
            confirmed_onramp_contributions_eur=confirmed_onramp_contributions_eur,
            provisional_onramp_contributions_eur=provisional_onramp_contributions_eur,
        )
        origin_pending = sum(
            1
            for row in contributions
            if row.amount_eur != 0
            and row.capital_origin_evidence_status != "documented"
        )
        confirmed_distributions = self._sum_values(
            row
            for row in outflows
            if row.classification == "external_distribution_confirmed"
        )
        review_outflows = [
            row
            for row in outflows
            if row.classification
            in {
                "trade_or_service_route",
                "operational_adjustment_review",
                "external_distribution_review",
            }
            and row.material
        ]
        review_value = self._sum_values(review_outflows)
        unpriced_review = sum(1 for row in review_outflows if row.value_eur is None)
        confirmed_contributions = (
            binance_contributions_eur + confirmed_onramp_contributions_eur
        )
        total_contributions = (
            confirmed_contributions + provisional_onramp_contributions_eur
        )
        flow_adjusted = (
            closing_value_eur
            + confirmed_distributions
            - opening_value_eur
            - total_contributions
        )
        strict_ready = not any(
            (
                provisional_onramp_contributions_eur,
                origin_pending,
                len(review_outflows),
                unpriced_review,
            )
        )
        findings = self._findings(
            provisional_contributions_eur=provisional_onramp_contributions_eur,
            origin_pending=origin_pending,
            review_outflows=review_outflows,
            unpriced_review=unpriced_review,
            confirmed_distributions=confirmed_distributions,
        )
        return DivorceCapitalFlowGate(
            cutoff_at=cutoff_at,
            valuation_at=valuation_at,
            materiality_threshold_eur=materiality_threshold_eur,
            opening_value_eur=opening_value_eur,
            closing_value_eur=closing_value_eur,
            confirmed_contributions_eur=confirmed_contributions,
            provisional_contributions_eur=provisional_onramp_contributions_eur,
            total_contributions_eur=total_contributions,
            confirmed_external_distributions_eur=confirmed_distributions,
            review_outflow_value_eur=review_value,
            internal_transfer_value_eur=self._sum_values(
                row
                for row in outflows
                if row.classification
                in {
                    "internal_transfer_confirmed",
                    "internal_product_transfer",
                    "internal_service_position_loss",
                }
            ),
            internal_service_position_loss_value_eur=self._sum_values(
                row
                for row in outflows
                if row.classification == "internal_service_position_loss"
            ),
            technical_fee_value_eur=self._sum_values(
                row for row in outflows if row.classification == "technical_fee"
            ),
            operational_adjustment_value_eur=self._sum_values(
                row
                for row in outflows
                if row.classification == "operational_adjustment_review"
            ),
            flow_adjusted_change_eur=flow_adjusted,
            flow_adjusted_change_if_all_review_outflows_are_external_eur=(
                None if unpriced_review else flow_adjusted + review_value
            ),
            outflows_count=len(outflows),
            internal_outflows_count=sum(
                1
                for row in outflows
                if row.classification
                in {
                    "internal_transfer_confirmed",
                    "internal_product_transfer",
                    "internal_service_position_loss",
                }
            ),
            confirmed_service_position_loss_count=sum(
                1
                for row in outflows
                if row.classification == "internal_service_position_loss"
            ),
            confirmed_external_distributions_count=sum(
                1
                for row in outflows
                if row.classification == "external_distribution_confirmed"
            ),
            material_review_outflows_count=len(review_outflows),
            unpriced_review_outflows_count=unpriced_review,
            capital_origin_pending_count=origin_pending,
            strict_ready=strict_ready,
            status="strict_ready"
            if strict_ready
            else "blocked"
            if review_outflows or unpriced_review
            else "review",
            contributions=contributions,
            outflows=outflows,
            findings=findings,
            methodology=(
                "Read-only Vermoegensfluss-Reconciliation. Negative Transferereignisse werden "
                "nicht pauschal als Entnahmen behandelt. TXID-/Mengenmatches, dokumentierte "
                "Eigenwallet-Transfers, CEX-Produktbewegungen und technische Gebuehren werden "
                "getrennt. Nur explizit belegte externe Auszahlungen werden dem Endwert fuer die "
                "Flussrechnung hinzugerechnet. Ungeklaerte Service-Routen und operative "
                "Korrekturen bleiben im Review. Eine belegte, vor dem Endstichtag vollstaendig "
                "liquidierte Serviceposition bleibt als Portfolioverlust sichtbar und wird nicht "
                "als externe Auszahlung hinzugerechnet. Diese Einordnung aendert keine steuerliche "
                "Klassifikation, Imports, Ledgerdaten oder FIFO-Lots."
            ),
        )

    def _classify_outflow(
        self,
        *,
        event: CanonicalEvent,
        incoming: list[CanonicalEvent],
        tx_events: list[CanonicalEvent],
        raw_payload: dict[str, object],
        tax_neutral_ids: set[str],
        external_distribution_ids: set[str],
        internal_service_loss_ids: set[str],
        decision_evidence: dict[str, str],
        alchemy_row: dict[str, object],
        price_lookup: HistoricalPriceLookup,
        materiality_threshold_eur: Decimal,
    ) -> DivorceCapitalOutflowRow:
        identifiers = {event.event_id, event.tx_id or "", event.raw_object_id or ""}
        value_eur = self._event_value(price_lookup, event)
        material = value_eur is None or abs(value_eur) >= materiality_threshold_eur
        operation = self._operation(raw_payload)
        evidence_ref = self._decision_ref(identifiers, decision_evidence)
        classification = "external_distribution_review"
        evidence_status = "review"
        note = "Negativer Transfer ohne vollstaendig belegte Zielverwendung."

        if identifiers & external_distribution_ids:
            classification = "external_distribution_confirmed"
            evidence_status = "confirmed"
            note = "Externe Auszahlung wurde durch eine Review-Entscheidung bestaetigt."
        elif identifiers & internal_service_loss_ids:
            classification = "internal_service_position_loss"
            evidence_status = "confirmed"
            note = (
                "Jupiter-Perps-Collateral wurde in eine interne Serviceposition "
                "uebertragen und vor dem Endstichtag vollstaendig liquidiert. Der "
                "Verlust bleibt in der Portfolioveraenderung; es liegt keine externe "
                "Auszahlung vor."
            )
        elif identifiers & tax_neutral_ids or self._has_exact_internal_match(
            event, incoming
        ):
            classification = "internal_transfer_confirmed"
            evidence_status = "confirmed"
            note = "Interner Transfer ist durch TXID/Mengenmatch oder Review-Entscheidung belegt."
        elif str(event.source_ref or "").startswith(
            "binance-auto-invest-redemption-offset:"
        ):
            classification = "internal_product_transfer"
            evidence_status = "confirmed"
            note = "Technischer Binance-Auto-Invest-Produktgegenposten."
        elif any(marker in operation for marker in self.INTERNAL_OPERATION_MARKERS):
            classification = "internal_product_transfer"
            evidence_status = "confirmed"
            note = f"Interne Produktbewegung laut Rohoperation: {operation or 'unbekannt'}."
        elif operation == "deposit" and self._has_nearby_deposit_offset(
            event, incoming
        ):
            classification = "internal_product_transfer"
            evidence_status = "confirmed"
            note = "Binance-Deposit wurde zwischen Hauptkonto und Spot gespiegelt."
        elif operation == "asset recovery":
            classification = "operational_adjustment_review"
            evidence_status = "review" if material else "immaterial"
            note = "Binance Asset Recovery ist keine belegte Auszahlung; Gegenwert/Korrekturbeleg pruefen."
        elif event.source == "solana_rpc":
            classification, evidence_status, note, evidence_ref = (
                self._solana_classification(
                    event=event,
                    tx_events=tx_events,
                    raw_payload=raw_payload,
                    alchemy_row=alchemy_row,
                    material=material,
                )
            )
        elif event.source.endswith("_withdrawal_api") or "withdraw" in operation:
            classification = "external_distribution_review"
            evidence_status = "review" if material else "immaterial"
            note = "Withdrawal-Beleg vorhanden; Zielkonto/Eigentum und Verbleib fuer Zugewinn pruefen."
        elif not material:
            classification = "operational_adjustment_review"
            evidence_status = "immaterial"
            note = "Operativer Transfer unterhalb der Materialitaetsschwelle."

        if evidence_ref is None:
            evidence_ref = event.raw_object_id or event.tx_id
        return DivorceCapitalOutflowRow(
            event_id=event.event_id,
            event_time=event.event_time,
            source=event.source,
            account=event.account,
            asset=event.asset,
            quantity=abs(event.quantity),
            value_eur=value_eur,
            classification=classification,
            evidence_status=evidence_status,
            material=material,
            affects_flow_adjusted_change=classification
            == "external_distribution_confirmed",
            tx_id=event.tx_id,
            raw_object_id=event.raw_object_id,
            evidence_ref=evidence_ref,
            note=note,
        )

    def _solana_classification(
        self,
        *,
        event: CanonicalEvent,
        tx_events: list[CanonicalEvent],
        raw_payload: dict[str, object],
        alchemy_row: dict[str, object],
        material: bool,
    ) -> tuple[str, str, str, str | None]:
        fee_quantity = self._decimal(raw_payload.get("fee_quantity"))
        if fee_quantity is not None and abs(event.quantity) <= abs(fee_quantity):
            return (
                "technical_fee",
                "confirmed",
                "On-chain SOL-Abgang entspricht der separat belegten Netzwerkgebuehr.",
                event.raw_object_id,
            )
        if any(
            item.event_type in {"trade", "reward", "income", "staking", "mining"}
            for item in tx_events
        ):
            return (
                "trade_or_service_route",
                "review" if material else "immaterial",
                "SOL-Nebenabgang gehoert zu einer belegten Trade-/Reward-/Service-Transaktion.",
                event.tx_id,
            )
        program_ids = {str(item) for item in alchemy_row.get("program_ids") or []}
        if program_ids & self.SERVICE_PROGRAM_IDS:
            return (
                "trade_or_service_route",
                "review" if material else "immaterial",
                "Alchemy belegt eine Jupiter-/Perps-Service-Route; wirtschaftlicher Positionsverbleib pruefen.",
                f"{self._display_path(self.ALCHEMY_AUDIT_PATH)}#{event.tx_id}",
            )
        if not material:
            return (
                "technical_fee",
                "immaterial",
                "On-chain SOL-Differenz unterhalb der Materialitaetsschwelle.",
                event.raw_object_id,
            )
        return (
            "external_distribution_review",
            "review",
            "Materieller On-chain-Abgang; Empfaenger und wirtschaftlicher Verbleib muessen belegt werden.",
            event.tx_id,
        )

    def _contributions(
        self,
        *,
        binance_contributions_eur: Decimal,
        confirmed_onramp_contributions_eur: Decimal,
        provisional_onramp_contributions_eur: Decimal,
    ) -> list[DivorceCapitalContributionRow]:
        origin_decisions = self._capital_origin_decisions()
        rows = [
            DivorceCapitalContributionRow(
                flow_id="binance_fiat_deposits",
                label="Binance EUR-Einzahlungen und direkte Fiat-Kaeufe",
                amount_eur=binance_contributions_eur,
                transaction_evidence_status="confirmed",
                capital_origin="unclassified",
                evidence_ref="/api/v1/divorce/inheritance-origin",
                note=(
                    "Plattform-Ledger und datensparsame Bankspur werden ohne Doppelzaehlung "
                    "vereinigt; Herkunft als Erbe, eheliches oder sonstiges Vermoegen separat belegen."
                ),
            ),
            DivorceCapitalContributionRow(
                flow_id="moonpay_apple_pay_onramp",
                label="MoonPay-/Apple-Pay-Onramps mit Trade-History-Beleg",
                amount_eur=confirmed_onramp_contributions_eur,
                transaction_evidence_status="confirmed",
                capital_origin="claimed_inheritance",
                evidence_ref="/api/v1/tax/moonpay-receipts",
                note="Bankabgang, Gebuehren und On-chain Eingang sind belegt; die Erbgeld-Kontokette bleibt separat nachzuweisen.",
            ),
            DivorceCapitalContributionRow(
                flow_id="moonpay_apple_pay_onramp_provisional",
                label="MoonPay-/Apple-Pay-Onramps ohne vollstaendigen Trade-History-Beleg",
                amount_eur=provisional_onramp_contributions_eur,
                transaction_evidence_status="provisional",
                capital_origin="claimed_inheritance",
                evidence_ref="/api/v1/tax/moonpay-receipts",
                note="Vorlaeufiger historischer Marktwert; Zahlungsbetrag, Gebuehren und Erbgeld-Kontokette sind noch zuzuordnen.",
            ),
        ]
        result: list[DivorceCapitalContributionRow] = []
        for row in rows:
            decision = origin_decisions.get(row.flow_id)
            if decision is None and row.flow_id.startswith("moonpay_apple_pay_onramp"):
                decision = origin_decisions.get("moonpay_apple_pay_onramp")
            if decision is None:
                result.append(row)
                continue
            origin, evidence_ref = decision
            result.append(
                row.model_copy(
                    update={
                        "capital_origin": origin,
                        "capital_origin_evidence_status": "documented",
                        "evidence_ref": evidence_ref or row.evidence_ref,
                    }
                )
            )
        return result

    def _decision_evidence(
        self,
        tx_ids: set[str],
    ) -> tuple[set[str], set[str], set[str], dict[str, str]]:
        tax_neutral: set[str] = set()
        external: set[str] = set()
        internal_service_loss: set[str] = set()
        evidence: dict[str, str] = {}
        for decision in self.store.list_review_decisions():
            status = str(decision.payload.get("decision_status") or "")
            identifiers = {str(item) for item in decision.affected_ids if str(item)}
            for key in (
                "txid",
                "deposit_txid",
                "withdrawal_tx_id",
                "event_id",
                "raw_object_id",
            ):
                value = decision.payload.get(key)
                if value:
                    identifiers.add(str(value))
            if status in self.TAX_NEUTRAL_STATUSES:
                tax_neutral.update(identifiers)
            if status in self.EXTERNAL_DISTRIBUTION_STATUSES:
                external.update(identifiers)
            if decision.evidence_ref:
                for identifier in identifiers:
                    evidence[identifier] = decision.evidence_ref
        accepted = self.service_route_evidence_service.accepted_decisions(tx_ids)
        for tx_id, (decision, report) in accepted.items():
            identifiers = {
                tx_id,
                report.canonical_event_id or "",
                *[str(item) for item in decision.affected_ids],
            }
            internal_service_loss.update(item for item in identifiers if item)
            if decision.evidence_ref:
                for identifier in identifiers:
                    if identifier:
                        evidence[identifier] = decision.evidence_ref
        return tax_neutral, external, internal_service_loss, evidence

    def _capital_origin_decisions(self) -> dict[str, tuple[str, str | None]]:
        allowed = {"inheritance", "marital_funds", "other_separate_property"}
        result: dict[str, tuple[str, str | None]] = {}
        for decision in self.store.list_review_decisions():
            if decision.decision_type != "divorce_capital_origin":
                continue
            flow_id = str(decision.payload.get("flow_id") or "")
            origin = str(decision.payload.get("capital_origin") or "")
            if flow_id and origin in allowed and flow_id not in result:
                result[flow_id] = (origin, decision.evidence_ref)
        return result

    def _raw_payloads(
        self, events: list[CanonicalEvent]
    ) -> dict[str, dict[str, object]]:
        ids = sorted({event.raw_object_id for event in events if event.raw_object_id})
        if not ids:
            return {}
        placeholders = ",".join("?" for _ in ids)
        with self.store.connect() as con:
            rows = con.execute(
                f"select raw_object_id, payload_json from raw_objects where raw_object_id in ({placeholders})",
                ids,
            ).fetchall()
        result: dict[str, dict[str, object]] = {}
        for raw_object_id, payload_json in rows:
            try:
                payload = json.loads(payload_json)
            except (TypeError, ValueError):
                payload = {}
            result[str(raw_object_id)] = payload if isinstance(payload, dict) else {}
        return result

    def _alchemy_rows(self, tx_ids: set[str | None]) -> dict[str, dict[str, object]]:
        wanted = {str(item) for item in tx_ids if item}
        if not wanted:
            return {}
        try:
            payload = json.loads(self.ALCHEMY_AUDIT_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {
            str(row.get("tx_id")): row
            for row in payload.get("rows") or []
            if isinstance(row, dict) and str(row.get("tx_id") or "") in wanted
        }

    @staticmethod
    def _has_exact_internal_match(
        event: CanonicalEvent, incoming: list[CanonicalEvent]
    ) -> bool:
        amount = abs(event.quantity)
        for candidate in incoming:
            tolerance = max(amount, abs(candidate.quantity)) * Decimal("0.000001")
            if abs(abs(candidate.quantity) - amount) > max(
                tolerance, Decimal("0.00000001")
            ):
                continue
            delta_seconds = abs(
                (candidate.event_time - event.event_time).total_seconds()
            )
            same_tx = bool(
                event.tx_id and candidate.tx_id and event.tx_id == candidate.tx_id
            )
            same_ref = bool(
                event.source_ref
                and candidate.source_ref
                and (
                    event.source_ref == candidate.source_ref
                    or event.source_ref.replace(":spot_mirror", "")
                    == candidate.source_ref.replace(":spot_mirror", "")
                )
            )
            same_time_internal = (
                delta_seconds <= 2
                and event.source == candidate.source
                and (event.account or "") != (candidate.account or "")
            )
            if (
                (same_tx and delta_seconds <= 6 * 60 * 60)
                or same_ref
                or same_time_internal
            ):
                return True
        return False

    @staticmethod
    def _has_nearby_deposit_offset(
        event: CanonicalEvent, incoming: list[CanonicalEvent]
    ) -> bool:
        return any(
            abs(abs(candidate.quantity) - abs(event.quantity)) <= Decimal("0.00000001")
            and abs((candidate.event_time - event.event_time).total_seconds()) <= 120
            for candidate in incoming
        )

    @staticmethod
    def _operation(payload: dict[str, object]) -> str:
        for key in ("Operation", "operation", "Label", "label", "record_type"):
            value = str(payload.get(key) or "").strip().lower()
            if value:
                return value
        return ""

    @staticmethod
    def _event_value(
        price_lookup: HistoricalPriceLookup,
        event: CanonicalEvent,
    ) -> Decimal | None:
        if event.asset.upper() == "EUR":
            return abs(event.quantity)
        point = price_lookup.at_or_before(event.asset, event.event_time)
        if point is None:
            return None
        return abs(event.quantity) * point.price_eur

    @staticmethod
    def _sum_values(rows: object) -> Decimal:
        return sum(
            (row.value_eur for row in rows if row.value_eur is not None),
            Decimal("0"),
        )

    @staticmethod
    def _decimal(value: object) -> Decimal | None:
        try:
            return Decimal(str(value)) if value not in (None, "") else None
        except (ArithmeticError, ValueError):
            return None

    @staticmethod
    def _decision_ref(identifiers: set[str], evidence: dict[str, str]) -> str | None:
        for identifier in identifiers:
            if identifier and identifier in evidence:
                return evidence[identifier]
        return None

    @staticmethod
    def _findings(
        *,
        provisional_contributions_eur: Decimal,
        origin_pending: int,
        review_outflows: list[DivorceCapitalOutflowRow],
        unpriced_review: int,
        confirmed_distributions: Decimal,
    ) -> list[str]:
        findings: list[str] = []
        if provisional_contributions_eur:
            findings.append(
                f"{provisional_contributions_eur} EUR Onramp-Zufluesse sind noch vorlaeufig bewertet."
            )
        if origin_pending:
            findings.append(
                f"Fuer {origin_pending} Kapitalzuflussgruppe(n) fehlt der Herkunftsnachweis Erbe/ehelich/sonstig."
            )
        if review_outflows:
            findings.append(
                f"{len(review_outflows)} materielle Abfluss-/Service-Ereignisse benoetigen einen Verbleibsnachweis."
            )
        if unpriced_review:
            findings.append(
                f"{unpriced_review} materielle Review-Abfluesse besitzen keinen EUR-Wert."
            )
        if confirmed_distributions:
            findings.append(
                f"{confirmed_distributions} EUR bestaetigte externe Auszahlungen wurden der Flussrechnung hinzugerechnet."
            )
        if not findings:
            findings.append(
                "Kapitalherkunft und alle materiellen Abfluesse sind belegt."
            )
        return findings

    @classmethod
    def _display_path(cls, path: Path) -> str:
        try:
            return str(path.relative_to(cls.PROJECT_ROOT))
        except ValueError:
            return str(path)

    @staticmethod
    def _naive(value: datetime) -> datetime:
        return value.replace(tzinfo=None) if value.tzinfo is not None else value
