from __future__ import annotations

from collections import defaultdict

from steuerreport_v2.private_settings import private_alias

from datetime import datetime, timezone
from decimal import Decimal
from hashlib import sha1
import json
from types import SimpleNamespace

from steuerreport_v2.contracts.review import (
    ReviewDecisionSuggestion,
    ReviewEvidenceTraceCanonicalizeResult,
    ReviewEvidenceTraceItem,
    ReviewEvidenceTraceReport,
    ReviewGate,
    ReviewIssue,
    ReviewTask,
    ReviewTaskSummary,
)
from steuerreport_v2.contracts.valuation import PriceCoverageReport
from steuerreport_v2.contracts.ledger import BalancePosition
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.account_aliases import (
    build_account_alias_map_for_store,
    unresolved_truncated_account_labels,
)
from steuerreport_v2.domain.derivatives import DerivativesManager
from steuerreport_v2.domain.derivative_cash import (
    BITGET_DERIVATIVE_ACTIONS, BITGET_NEUTRAL_ACTIONS, bitget_financial_row,
    derivative_cash, derivative_raw_rows,
)
from steuerreport_v2.domain.jupiter import JupiterTokenService
from steuerreport_v2.domain.pionex_reconciliation import (
    PionexHntReconciliationService,
)
from steuerreport_v2.domain.price_lookup import fiat_price_point
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_time import reporting_tax_year
from steuerreport_v2.domain.valuation import PriceCoverageService, PriceQualityService
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


class ReviewService:
    STATIC_DECISION_SUGGESTION_SCOPES = {
        "blockpit_solana:opening_balance:asset:IOT",
        "solscan_iot:blockpit_missing_signatures",
    }

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store
        self._jupiter_metadata_cache = None

    def gate(self, price_coverage: PriceCoverageReport | None = None) -> ReviewGate:
        issues: list[ReviewIssue] = []
        from steuerreport_v2.domain.asset_identity import AssetIdentityIndex
        from steuerreport_v2.domain.historical_prices import HistoricalPriceService
        identity_problems = AssetIdentityIndex(self.store).problems_for_mappings(
            HistoricalPriceService(self.store).mappings())
        for asset, reason in sorted(identity_problems.items()):
            issues.append(ReviewIssue(code=reason, severity="high", scope=f"asset_identity:{asset}",
                blocks_export=True, message=f"Tokenidentitaet fuer {asset} nicht eindeutig oder Mengeneinheit widerspruechlich ({reason}). Originale Chain-/Contract-/Dezimalstellen pruefen; keine Freigabe aufgrund des Symbols."))
        from steuerreport_v2.domain.token_conversion import TokenConversionService
        conversion_report = TokenConversionService(self.store).report()
        for item in conversion_report["issues"]:
            issues.append(ReviewIssue(code=item["reason"], severity="high",
                scope=f"token_conversion:{item['event_id'] or 'config'}", blocks_export=True,
                message="Migration/Wrapping ohne aktuelle eindeutige Beleg-, Mengen- oder Methodenbindung. Keine automatische 1:1-Paritaet oder neutrale Fortschreibung."))
        from steuerreport_v2.db.ai_corrections import conflicts
        with self.store.connect() as con:
            derivative_calculated = con.execute("select count(*) from derivative_run_summaries").fetchone()[0] > 0
            for kind, target_id, code in conflicts(con):
                issues.append(ReviewIssue(code=code, severity="high", scope=f"correction:{kind}:{target_id}",
                                          message="Freigegebene Datenkorrektur stimmt nicht mit dem aktuellen Datenstand ueberein.", blocks_export=True))
        positions = BalanceLedgerBuilder(self.store).positions()

        from steuerreport_v2.domain.lot_origin import LotOriginIndex
        origin_events = self.store.list_canonical_events()
        derivative_rows = derivative_raw_rows(self.store)
        stored_cash = defaultdict(dict)
        stored_derivatives = defaultdict(dict)
        with self.store.connect() as con:
            for event_id, asset, amount in con.execute("""select l.event_id,l.asset,sum(l.delta_quantity)
                from balance_ledger l join canonical_events e on e.event_id=l.event_id
                where e.event_type='derivative' group by 1,2""").fetchall():
                stored_cash[event_id][asset.upper()] = amount
            for event_id, asset, amount in con.execute(
                "select event_id,asset,sum(quantity) from derivative_lines group by 1,2").fetchall():
                stored_derivatives[event_id][asset.upper()] = amount
        for event in origin_events:
            row = derivative_rows.get(event.event_id, {})
            action = str(row.get("type") or row.get("action") or row.get("action (english)") or "").strip().lower()
            neutral = action in BITGET_NEUTRAL_ACTIONS and bitget_financial_row(row)
            normalization_required = event.source.lower() == "bitget" and (
                (action in BITGET_DERIVATIVE_ACTIONS or neutral) and event.event_type != "derivative"
                or neutral and event.quantity != 0
            )
            if normalization_required:
                issues.append(ReviewIssue(code="derivative_normalization_required", severity="high",
                    scope=f"event:{event.event_id}", tax_year=reporting_tax_year(event.event_time), blocks_export=True,
                    message="Die gespeicherte Bitget-Einordnung entspricht nicht dem belegten Funding-/Futures-Schema oder enthaelt eine Sicherheitenumbuchung als Geldfluss. Rohimport in einer neuen Vorschau normalisieren und pruefen; kein automatisches Umschreiben alter Daten."))
            if event.event_type != "derivative":
                continue
            cash = derivative_cash(event, row)
            if cash.review_reason:
                raw_mismatch = cash.review_reason.startswith("principal_")
                issues.append(ReviewIssue(code="derivative_normalization_required" if raw_mismatch else "derivative_fee_semantics_required", severity="high",
                    scope=f"event:{event.event_id}", tax_year=reporting_tax_year(event.event_time), blocks_export=True,
                    message=(f"Die gespeicherte Derivate-Menge stimmt nicht mit der ausdruecklichen Brutto-/Nettospalte ueberein ({cash.review_reason}). Rohimport in einer neuen Vorschau normalisieren und pruefen."
                             if raw_mismatch else f"Derivategebuehren sind nicht abschliessend belegt ({cash.review_reason}). Brutto-/Nettokonvention, Gebuehrenwaehrung und gegebenenfalls eigener Token-Lotverbrauch pruefen; keine pauschale Kostenfreigabe.")))
            expected = {}
            for asset, amount in cash.legs:
                key = asset.upper()
                expected[key] = expected.get(key, Decimal("0")) + amount
            if (not derivative_calculated and any(expected.values())) or any(
                calculated and any(stored.get(key, Decimal("0")) != expected.get(key, Decimal("0"))
                                   for key in expected.keys() | stored.keys())
                for stored, calculated in ((stored_cash.get(event.event_id, {}), bool(stored_cash)),
                    (stored_derivatives.get(event.event_id, {}), derivative_calculated))
            ):
                issues.append(ReviewIssue(code="derivative_cash_recalculation_required", severity="high",
                    scope=f"event:{event.event_id}", tax_year=reporting_tax_year(event.event_time), blocks_export=True,
                    message="Gespeicherte Derivate-/Ledger-Geldbeine weichen von der belegten Gebuehrenkonvention ab. Einen neuen gebundenen Berechnungslauf pruefen; alte Berichte und Abgabestaende bleiben unveraendert."))
        origin_index = LotOriginIndex(TaxService(self.store).list_tax_lots(), origin_events)
        with self.store.connect() as con:
            origin_lines = con.execute("""select tax_line_id,source_event_id,lot_id,asset,acquired_at,
                disposed_at,pool_id,origin_lot_id,acquisition_source_event_id from tax_lines
                order by disposed_at,tax_line_id""").fetchall()
        for values in origin_lines:
            line = SimpleNamespace(**dict(zip(("tax_line_id", "source_event_id", "lot_id", "asset",
                "acquired_at", "disposed_at", "pool_id", "origin_lot_id", "acquisition_source_event_id"), values)))
            trace = origin_index.resolve(line)
            if trace.status == "unresolved":
                issues.append(ReviewIssue(code="lot_origin_unresolved", severity="high",
                    scope=f"event:{line.source_event_id}:lot:{line.lot_id}", blocks_export=True,
                    tax_year=reporting_tax_year(line.disposed_at),
                    message=f"Die gespeicherte Anschaffungsherkunft fuer {line.asset} ist nicht vollstaendig oder widerspruchsfrei verknuepft ({trace.reason}). Originale Ereignis- und Lotverweise pruefen; keine automatische private Einordnung."))

        with self.store.connect() as con:
            zero_basis = con.execute("""
                select lot.lot_id, lot.asset, lot.source_event_id, min(line.disposed_at)
                from tax_lots lot left join tax_lines line on line.lot_id=lot.lot_id
                where lot.quantity_total > 0 and lot.cost_basis_eur_total=0
                group by lot.lot_id, lot.asset, lot.source_event_id
                order by lot.lot_id
            """).fetchall()
        for lot_id, asset, event_id, disposed_at in zero_basis:
            issues.append(ReviewIssue(code="unproven_zero_cost_basis", severity="high",
                scope=f"lot:{lot_id}:event:{event_id}", blocks_export=True,
                tax_year=reporting_tax_year(disposed_at) if disposed_at else None,
                message=f"Fuer {asset} ist eine Nullkostenbasis gespeichert. Anschaffung, Herkunft und ein gegebenenfalls begruendeter Nullansatz sind gesondert zu belegen; keine automatische Anerkennung."))

        fee_service = TaxService(self.store)
        with self.store.connect() as con:
            fee_marker = con.execute("select value_json from admin_settings where key='tax.fee_accounting_binding'").fetchone()
            fee_line_quantities = {(event_id, asset.upper()): quantity for event_id, asset, quantity in con.execute(
                "select source_event_id,asset,sum(quantity) from tax_lines group by 1,2").fetchall()}
            carried_quantities = dict(con.execute("select source_event_id,sum(quantity_total) from tax_lots group by 1").fetchall())
        has_current_fee_run = fee_marker is not None and fee_marker[0] == json.dumps(fee_service.fee_input_binding())
        for conversion in conversion_report["ready"]:
            if (not has_current_fee_run
                    or carried_quantities.get(conversion.target.event_id) != conversion.target.quantity):
                issues.append(ReviewIssue(code="token_conversion_recalculation_required", severity="high",
                    scope=f"token_conversion:{conversion.mapping.mapping_id}", blocks_export=True,
                    message="Belegbindung ist vorhanden, aber gespeicherte Konvertierungslots sind nicht durch einen aktuellen Berechnungslauf nachgewiesen. Keine automatische Uebernahme oder Jahresfreigabe."))
        for event in self.store.list_canonical_events():
            fee = fee_service.trade_fee_accounting(event)
            if fee is None:
                continue
            expected_quantity = fee.quantity
            if fee.separate_disposal:
                if event.quantity < 0 and event.asset.upper() == fee.asset:
                    expected_quantity += abs(event.quantity)
                elif event.quantity > 0 and str(event.quote_asset or "").upper() == fee.asset:
                    expected_quantity += abs(event.quote_quantity or Decimal("0"))
            if (not has_current_fee_run or fee.separate_disposal
                    and fee_line_quantities.get((event.event_id, fee.asset), Decimal("0")) != expected_quantity):
                issues.append(ReviewIssue(code="fee_accounting_recalculation_required", severity="high",
                    scope=f"event:{event.event_id}", blocks_export=True, tax_year=reporting_tax_year(event.event_time),
                    message="Gespeicherter Gebuehrenverbrauch ist nicht durch einen aktuellen gebundenen Berechnungslauf belegt. Vorschau neu berechnen und pruefen; ein vorhandener Kurs allein reicht nicht."))
            if fee.allocation == "review_required":
                issues.append(ReviewIssue(code="swap_fee_allocation_review_required", severity="high",
                    scope=f"event:{event.event_id}", blocks_export=True, tax_year=reporting_tax_year(event.event_time),
                    message="Gebuehrenmenge ist beruecksichtigt; die Kostenrolle beim Token-Tausch ist noch nicht belegt. Erwerbs- und Verwertungskosten getrennt pruefen."))
            if fee.separate_disposal and fee.value_eur is None:
                issues.append(ReviewIssue(code="fee_token_valuation_missing", severity="high",
                    scope=f"event:{event.event_id}", blocks_export=True, tax_year=reporting_tax_year(event.event_time),
                    message="Gebuehren-Token wurde mengenmaessig verbraucht, sein historischer EUR-Wert fehlt. Ein vorlaeufiger Nullerloes ist kein belegter Nullwert."))
            if fee.allocation == "disposal_cost" and fee_service._disposal_value_eur(event) < 0:
                issues.append(ReviewIssue(code="negative_net_disposal_proceeds", severity="high",
                    scope=f"event:{event.event_id}", blocks_export=True, tax_year=reporting_tax_year(event.event_time),
                    message="Verkaufskosten uebersteigen den Erloes. Nettoerloes und Gebuehrenbeleg fachlich pruefen."))

        with self.store.connect() as con:
            pending_history = con.execute(
                """
                select e.event_id, e.account, e.asset, e.event_time
                from canonical_events e
                join raw_objects r on r.raw_object_id = e.raw_object_id
                where e.source = 'solana_rpc' and e.event_type = 'transfer'
                  and json_extract_string(r.payload_json, '$.history_mapper_version') = '2'
                order by e.event_time, e.event_id
                """
            ).fetchall()
        for event_id, account, asset, event_time in pending_history:
            issues.append(ReviewIssue(
                code="solana_history_classification_required",
                severity="high",
                message=(
                    "RPC-Bestandsbewegung ist belegt, aber noch nicht fachlich als "
                    "Transfer, Handel oder Reward eingeordnet. Originaltransaktion "
                    "und Gegenkonto pruefen; keine automatische steuerliche Einordnung."
                ),
                scope=f"event:{event_id}",
                blocks_export=True,
                tax_year=reporting_tax_year(event_time),
            ))

        with self.store.connect() as con:
            pending_api_evidence = con.execute(
                """
                select e.event_id from canonical_events e
                join raw_objects r on r.raw_object_id=e.raw_object_id
                where e.event_type='unknown'
                  and json_extract_string(r.payload_json, '$.history_classification_required')='1'
                """
            ).fetchall()
        for (event_id,) in pending_api_evidence:
            issues.append(ReviewIssue(
                code="api_history_classification_required", severity="high", scope="event:" + event_id,
                message="API-Beleg vorhanden, Betrag/Gebuehrenwirkung noch nicht eindeutig gebucht. Originalbeleg pruefen und fachlich zuordnen.",
                blocks_export=True,
            ))

        from steuerreport_v2.importers.mexc_native import review_issues as mexc_review_issues
        issues.extend(mexc_review_issues(self.store))

        for batch_id, count in self.store.unmapped_raw_object_counts().items():
            issues.append(
                ReviewIssue(
                    code="unmapped_raw_objects",
                    severity="high",
                    message=(
                        f"{count} Rohzeile(n) im Import-Batch konnten nicht "
                        "zu Canonical Events normalisiert werden."
                    ),
                    scope=f"import_batch:{batch_id}",
                    blocks_export=True,
                )
            )

        for asset in self._missing_position_price_assets(positions):
            issues.append(
                ReviewIssue(
                    code="missing_price",
                    severity="high",
                    message=f"Fuer {asset} fehlt ein EUR-Preis im Price-Ledger.",
                    scope=f"asset:{asset}",
                    blocks_export=True,
                )
            )

        for account in self._unresolved_truncated_position_accounts(positions):
            issues.append(
                ReviewIssue(
                    code="unresolved_truncated_account",
                    severity="high",
                    message=(
                        "Gekuerzter Account kann keiner eindeutigen vollen "
                        f"Wallet zugeordnet werden: {account}."
                    ),
                    scope=f"account_alias:{account}",
                    blocks_export=True,
                )
            )

        if price_coverage is None:
            price_coverage = PriceCoverageService(self.store).report()
        for item in price_coverage.missing:
            issues.append(
                ReviewIssue(
                    code="missing_event_price",
                    severity="high",
                    message=(
                        f"{item.event_count} steuerrelevante Event(s) fuer "
                        f"{item.asset} im Jahr {item.year} haben keine "
                        "historische EUR-Bewertung."
                    ),
                    scope=(
                        f"price_coverage:asset:{item.asset}:year:{item.year}:"
                        f"source:{item.source}:event_type:{item.event_type}:role:{item.role}"
                    ),
                    blocks_export=True,
                )
            )

        for position in positions:
            if position.quantity < 0:
                issues.append(
                    ReviewIssue(
                        code="negative_balance",
                        severity="high",
                        message=(
                            f"Negativer Bestand fuer {position.asset} "
                            f"auf {position.account}."
                        ),
                        scope=f"account:{position.account}:asset:{position.asset}",
                        blocks_export=True,
                    )
                )

        tax_summary = TaxService(self.store).latest_summary()
        if tax_summary is not None and tax_summary.unmatched_disposals > 0:
            unmatched = TaxService(self.store).list_unmatched_disposals()
            years = sorted({reporting_tax_year(item.event_time) for item in unmatched})
            tax_year = years[0] if len(years) == 1 else None
            closed_years = self._closed_tax_years()
            is_current_scope = not years or any(year not in closed_years for year in years)
            detail = ""
            if unmatched:
                first = unmatched[0]
                detail = (
                    f" Erstes Ereignis: {first.asset} "
                    f"{first.quantity} am {first.event_time.isoformat()} "
                    f"auf {first.account or '-'}; fehlend {first.missing_quantity}."
                )
            issues.append(
                ReviewIssue(
                    code="unmatched_tax_disposal",
                    severity="high",
                    message=(
                        f"{tax_summary.unmatched_disposals} Verkauf/Abgang "
                        "konnte keinem FIFO-Lot zugeordnet werden."
                        f"{detail}"
                    ),
                    scope=f"tax:fifo:year:{tax_year}" if tax_year is not None else "tax:fifo",
                    blocks_export=is_current_scope,
                    tax_year=tax_year,
                    is_current_scope=is_current_scope,
                )
            )

        zero_cost_lots = self._zero_cost_tax_lots()
        if zero_cost_lots:
            issues.append(
                ReviewIssue(
                    code="zero_cost_tax_lots",
                    severity="high",
                    message=(
                        f"{zero_cost_lots} FIFO-Lot(s) haben 0 EUR "
                        "Anschaffungskosten. Bewertung oder Quellwert fehlt."
                    ),
                    scope="tax:fifo",
                    blocks_export=True,
                )
            )

        zero_proceeds_lines = self._zero_proceeds_tax_lines()
        if zero_proceeds_lines:
            issues.append(
                ReviewIssue(
                    code="zero_proceeds_tax_lines",
                    severity="high",
                    message=(
                        f"{zero_proceeds_lines} Steuerzeile(n) haben 0 EUR "
                        "Verkaufserloes. Quote- oder Asset-Bewertung fehlt."
                    ),
                    scope="tax:fifo",
                    blocks_export=True,
                )
            )

        derivative_summary = DerivativesManager(self.store).latest_summary()
        if derivative_summary is not None and derivative_summary.missing_price_count > 0:
            issues.append(
                ReviewIssue(
                    code="derivative_missing_prices",
                    severity="high",
                    message=(
                        f"{derivative_summary.missing_price_count} Derivate-Zeile(n) "
                        "haben keine EUR-Bewertung."
                    ),
                    scope="tax:derivatives",
                    blocks_export=True,
                )
            )

        current_issues = [issue for issue in issues if issue.is_current_scope]
        high_count = sum(1 for issue in current_issues if issue.severity == "high")
        medium_count = sum(1 for issue in current_issues if issue.severity == "medium")
        low_count = sum(1 for issue in current_issues if issue.severity == "low")
        blocking_count = sum(1 for issue in issues if issue.blocks_export)
        return ReviewGate(
            allow_export=blocking_count == 0,
            issues_open=len(current_issues),
            issues_open_total=len(issues),
            issues_current_open=len(current_issues),
            issues_historical_open=len(issues) - len(current_issues),
            issues_high_open=high_count,
            issues_medium_open=medium_count,
            issues_low_open=low_count,
            blocking_issues_open=blocking_count,
            issues=issues,
        )

    def decision_suggestions(
        self,
        *,
        include_static: bool = True,
        include_token_risk: bool = True,
    ) -> list[ReviewDecisionSuggestion]:
        from steuerreport_v2.domain.blockpit_solana_preflight import (
            BlockpitSolanaPreflightService,
        )
        from steuerreport_v2.domain.solscan_preflight import SolscanPreflightService
        from steuerreport_v2.domain.wallet_monthly_preflight import (
            WalletMonthlyPreflightService,
        )

        suggestions: list[ReviewDecisionSuggestion] = []
        if include_static:
            blockpit = BlockpitSolanaPreflightService(self.store).inspect()
            wallet_monthly = WalletMonthlyPreflightService().inspect()
            solscan_trace = SolscanPreflightService().evidence_trace()
            solscan = solscan_trace.preflight

            iot_incident = next(
                (
                    incident
                    for incident in blockpit.combined_readiness.incidents
                    if incident.asset.upper() == "IOT"
                ),
                None,
            )
            if iot_incident is not None and wallet_monthly.covers_required_quantity:
                wallet_candidate = next(
                    (
                        candidate
                        for candidate in iot_incident.evidence_candidates
                        if candidate.source == "wallet_monthly"
                    ),
                    None,
                )
                suggestions.append(
                    ReviewDecisionSuggestion(
                        suggestion_id="blockpit_solana_iot_opening_wallet_monthly_coverage",
                        decision_type="evidence_acceptance",
                        scope="blockpit_solana:opening_balance:asset:IOT",
                        title="IOT-Startbestand durch Wallet-Monatsdaten belegt",
                        rationale=(
                            "Der chronologische Blockpit/Solana-Preflight benoetigt "
                            f"{iot_incident.required_quantity} IOT Startbestand. "
                            "Die Wallet-Monatsdatei weist bis zum ersten Defizit "
                            f"{wallet_monthly.quantity_until_cutoff} IOT aus und "
                            "deckt den benoetigten Bestand mengenmaessig."
                        ),
                        evidence_ref=wallet_candidate.source_ref if wallet_candidate else wallet_monthly.file_path,
                        actor="codex",
                        source="api:/api/v1/review/decision-suggestions",
                        affected_ids=[
                            "blockpit_solana_preflight:combined_readiness:IOT",
                            "wallet_monthly_preflight:IOT",
                        ],
                        payload={
                            "asset": "IOT",
                            "required_quantity": str(iot_incident.required_quantity),
                            "covered_quantity": str(wallet_monthly.quantity_until_cutoff),
                            "coverage_ratio": str(wallet_monthly.coverage_ratio),
                            "first_deficit_at": iot_incident.first_deficit_at,
                            "candidate_score": (
                                wallet_candidate.score if wallet_candidate else None
                            ),
                            "import_effect": "none",
                        },
                        confidence="high",
                    )
                )

            rpc = solscan.rpc_evidence
            if (
                solscan.blockpit_missing_signatures > 0
                and rpc.status == "verified"
                and rpc.quantity_delta_sum == 0
            ):
                suggestions.append(
                    ReviewDecisionSuggestion(
                        suggestion_id="solscan_iot_missing_signatures_rpc_verified",
                        decision_type="evidence_acceptance",
                        scope="solscan_iot:blockpit_missing_signatures",
                        title="Fehlende Solscan-IOT-Signaturen per RPC verifiziert",
                        rationale=(
                            f"{solscan.blockpit_missing_signatures} Blockpit-IOT-"
                            "Signaturen fehlen in der Solscan-CSV, wurden aber per "
                            "Solana-RPC mit identischem Wallet-Delta bestaetigt."
                        ),
                        evidence_ref="/api/v1/import/solscan/evidence-trace",
                        actor="codex",
                        source="api:/api/v1/review/decision-suggestions",
                        affected_ids=[
                            "solscan_token_preflight:IOT",
                            "solscan_rpc_probe:IOT",
                            "solscan_evidence_trace:IOT",
                            *([rpc.artifact_path] if rpc.artifact_path else []),
                        ],
                        payload={
                            "asset": "IOT",
                            "missing_signatures": solscan.blockpit_missing_signatures,
                            "verified": rpc.verified,
                            "signatures_total": rpc.signatures_total,
                            "quantity_delta_sum": str(rpc.quantity_delta_sum),
                            "expected_quantity_sum": str(rpc.expected_quantity_sum),
                            "wallet_delta_quantity_sum": str(rpc.wallet_delta_quantity_sum),
                            "evidence_trace_endpoint": "/api/v1/import/solscan/evidence-trace",
                            "evidence_trace_status": solscan_trace.status,
                            "review_scope": solscan_trace.review_scope,
                            "import_effect": "none",
                        },
                        confidence="high",
                    )
                )
        if include_token_risk:
            suggestions.extend(self._token_risk_documentation_suggestions())
        return suggestions

    def tasks(self, limit: int | None = 80, include_reconciliation: bool = False) -> ReviewTaskSummary:
        from steuerreport_v2.domain.portfolio import PortfolioService

        coverage = PriceCoverageService(self.store).report()
        gate = self.gate(price_coverage=coverage)
        decided_scopes = {
            decision.scope
            for decision in self.store.list_review_decisions()
        }
        suggestions = self.decision_suggestions(
            include_static=not self.STATIC_DECISION_SUGGESTION_SCOPES <= decided_scopes,
            include_token_risk=True,
        )
        price_quality_manual = PriceQualityService(self.store).manual_review_report(limit=10_000)

        tasks: list[ReviewTask] = []
        for issue in gate.issues:
            tasks.append(self._task_from_issue(issue))

        for suggestion in suggestions:
            if suggestion.scope in decided_scopes:
                continue
            tasks.append(self._task_from_suggestion(suggestion))

        for gap in coverage.missing:
            if gap.decision_status != "unreviewed":
                continue
            tasks.append(
                ReviewTask(
                    task_id=self._task_id("price-gap", gap.scope),
                    priority="high",
                    category="price",
                    title=f"{gap.asset} Preisbeleg fuer {gap.year} klaeren",
                    detail=(
                        f"{gap.event_count} steuerrelevante Event(s), Rolle {gap.role}, "
                        f"Quelle {gap.source}. Ohne EUR-Preis bleibt FIFO/Steuerbewertung blockiert."
                    ),
                    source="price_coverage",
                    scope=gap.scope,
                    action_label="Preisbedarf pruefen",
                    action_path="/api/v1/prices/requirements",
                    blocks_export=True,
                    tax_year=gap.year,
                    asset=gap.asset,
                    source_group=gap.source,
                    count=gap.event_count,
                    evidence_refs=gap.sample_event_ids[:5],
                    decision_status=gap.decision_status,
                )
            )

        tasks.extend(self._price_quality_bucket_tasks(price_quality_manual.groups))
        tasks.extend(self._source_reconciliation_tasks())

        if include_reconciliation:
            reconciliation = PortfolioService(self.store).reconciliation_report()
            for row in reconciliation.rows:
                if row.severity not in {"blocker", "warning"}:
                    continue
                tasks.append(
                    ReviewTask(
                        task_id=self._task_id(
                            "reconciliation",
                            row.source_group,
                            row.asset or "",
                            row.status,
                        ),
                        priority="high" if row.severity == "blocker" else "medium",
                        category="reconciliation",
                        title=f"{row.source_group} Live-vs-Ledger klaeren",
                        detail=f"{row.evidence} Naechster Schritt: {row.next_action}",
                        source="portfolio_reconciliation",
                        scope=f"reconciliation:{row.source_group}:{row.asset or 'all'}",
                        action_label="Quellenabgleich pruefen",
                        action_path="/api/v1/portfolio/reconciliation",
                        blocks_export=row.severity == "blocker",
                        asset=row.asset,
                        source_group=row.source_group,
                        value_eur=self._abs_decimal(row.delta_value_eur),
                        evidence_refs=[row.evidence],
                        decision_status=row.status,
                    )
                )

        tasks = self._deduplicate_tasks(tasks)
        self._enrich_tasks_with_token_metadata(tasks)
        tasks.sort(key=self._task_sort_key)
        if limit is not None:
            tasks = tasks[: max(1, limit)]

        return ReviewTaskSummary(
            generated_at=datetime.now(timezone.utc),
            open_tasks=len(tasks),
            blocking_tasks=sum(1 for task in tasks if task.blocks_export),
            high_priority_tasks=sum(1 for task in tasks if task.priority == "high"),
            medium_priority_tasks=sum(1 for task in tasks if task.priority == "medium"),
            low_priority_tasks=sum(1 for task in tasks if task.priority == "low"),
            fifo_relevant_tasks=sum(1 for task in tasks if task.category in {"fifo", "tax", "reconciliation"}),
            evidence_tasks=sum(1 for task in tasks if task.category in {"evidence", "price"}),
            tasks=tasks,
            methodology=(
                "Lesende Review-Aufgaben aus Review-Gate, Preisdeckung, "
                "Preisqualitaets-Buckets, Entscheidungsvorschlaegen und "
                "optional Portfolio-Reconciliation. "
                "Aufgaben schreiben keine Steuerdaten; sie priorisieren Belege "
                "fuer FIFO-, Preis- und Live/Ledger-Klaerung."
            ),
        )

    def evidence_traces(self) -> ReviewEvidenceTraceReport:
        from steuerreport_v2.domain.solscan_preflight import SolscanPreflightService

        canonical_ref = "/api/v1/import/solscan/evidence-trace"
        scope = "solscan_iot:blockpit_missing_signatures"
        solscan_trace = SolscanPreflightService().evidence_trace()
        decision = next(
            (
                item
                for item in self.store.list_review_decisions()
                if item.scope == scope
            ),
            None,
        )
        if decision is None:
            decision_status = "missing_decision"
        elif decision.evidence_ref == canonical_ref:
            decision_status = "canonical"
        else:
            decision_status = "legacy_ref"
        trace = ReviewEvidenceTraceItem(
            trace_id="solscan_iot_missing_signatures",
            scope=scope,
            title="Solscan/IOT RPC Evidence Trace",
            status=decision_status,
            canonical_evidence_ref=canonical_ref,
            stored_evidence_ref=decision.evidence_ref if decision else None,
            decision_id=decision.decision_id if decision else None,
            decision_status=decision_status,
            evidence_trace_status=solscan_trace.status,
            import_effect=solscan_trace.import_effect,
            target_changed=solscan_trace.target_changed,
            action_path=canonical_ref,
            note=(
                "Read-only Abgleich: zeigt, ob die Review-Entscheidung fuer "
                "fehlende Solscan-IOT-Signaturen bereits auf den kanonischen "
                "Evidence-Trace zeigt. Es werden keine Entscheidungen geaendert."
            ),
        )
        traces = [trace]
        return ReviewEvidenceTraceReport(
            generated_at=datetime.now(timezone.utc),
            traces_count=len(traces),
            canonical_count=sum(1 for item in traces if item.status == "canonical"),
            legacy_ref_count=sum(1 for item in traces if item.status == "legacy_ref"),
            missing_decision_count=sum(1 for item in traces if item.status == "missing_decision"),
            traces=traces,
            methodology=(
                "Read-only Review-Evidence-Trace-Report. Er verknuepft bestehende "
                "Review-Entscheidungen mit kanonischen Beleg-Endpunkten und "
                "schreibt keine Review-Entscheidungen, Imports, FIFO-Lots oder Tax-Lines."
            ),
        )

    def canonicalize_evidence_traces(
        self,
        *,
        execute: bool = False,
    ) -> ReviewEvidenceTraceCanonicalizeResult:
        report = self.evidence_traces()
        candidates = [
            trace
            for trace in report.traces
            if trace.status == "legacy_ref" and trace.decision_id
        ]
        updated_ids: list[str] = []
        if execute:
            decisions = {
                decision.decision_id: decision
                for decision in self.store.list_review_decisions()
            }
            for trace in candidates:
                decision = decisions.get(str(trace.decision_id))
                if decision is None:
                    continue
                payload = dict(decision.payload)
                if decision.evidence_ref != trace.canonical_evidence_ref:
                    payload.setdefault("previous_evidence_ref", decision.evidence_ref)
                payload["canonical_evidence_ref"] = trace.canonical_evidence_ref
                payload["canonicalized_by"] = "api:/api/v1/review/evidence-traces/canonicalize"
                payload["import_effect"] = "none"
                updated = decision.model_copy(
                    update={
                        "evidence_ref": trace.canonical_evidence_ref,
                        "payload": payload,
                    }
                )
                self.store.update_review_decision(updated)
                updated_ids.append(updated.decision_id)
        return ReviewEvidenceTraceCanonicalizeResult(
            execute=execute,
            dry_run=not execute,
            target_changed=bool(updated_ids),
            candidates_count=len(candidates),
            updated_count=len(updated_ids),
            skipped_count=len(candidates) - len(updated_ids),
            updated_decision_ids=updated_ids,
            candidates=candidates,
            methodology=(
                "Kanonisiert ausschliesslich Review-Decision evidence_ref-Werte "
                "von bekannten Legacy-Artefakten auf kanonische read-only "
                "Evidence-Trace-Endpunkte. execute=false prueft nur; execute=true "
                "aendert keine Steuerdaten, Imports, FIFO-Lots, Tax-Lines oder "
                "Portfolio-Bestaende."
            ),
        )

    def _missing_position_price_assets(self, positions: list[BalancePosition]) -> list[str]:
        prices = self.store.latest_price_points()
        missing: set[str] = set()
        for position in positions:
            asset = str(position.asset)
            if position.quantity == 0:
                continue
            if fiat_price_point(asset) is not None:
                continue
            if asset not in prices:
                missing.add(asset)
        return sorted(missing)

    def _unresolved_truncated_position_accounts(
        self,
        positions: list[BalancePosition],
    ) -> list[str]:
        accounts = [str(position.account) for position in positions]
        if not any("..." in account for account in accounts):
            return []
        aliases = build_account_alias_map_for_store(self.store, accounts)
        return unresolved_truncated_account_labels(accounts, aliases)

    def _zero_cost_tax_lots(self) -> int:
        approved_event_ids = sorted(
            PionexHntReconciliationService(self.store).approved_zero_cost_event_ids()
        )
        exclusion = ""
        params: list[str] = []
        if approved_event_ids:
            exclusion = (
                "and lot.source_event_id not in ("
                + ", ".join("?" for _event_id in approved_event_ids)
                + ")"
            )
            params.extend(approved_event_ids)
        with self.store.connect() as con:
            row = con.execute(
                f"""
                select count(distinct lot.lot_id)
                from tax_lots lot
                join tax_lines line on line.lot_id = lot.lot_id
                where lot.cost_basis_eur_total = 0
                {exclusion}
                """,
                params,
            ).fetchone()
        return int(row[0] if row is not None else 0)

    def _zero_proceeds_tax_lines(self) -> int:
        with self.store.connect() as con:
            row = con.execute(
                """
                select count(*)
                from tax_lines
                where disposal_proceeds_eur = 0
                """
            ).fetchone()
        return int(row[0] if row is not None else 0)

    def _closed_tax_years(self) -> set[int]:
        settings = {
            setting.key: setting.value_json
            for setting in self.store.list_admin_settings()
        }
        raw = settings.get("runtime.review.closed_tax_years", "[]")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return set()
        if not isinstance(value, list):
            return set()
        years: set[int] = set()
        for item in value:
            try:
                years.add(int(item))
            except (TypeError, ValueError):
                continue
        return years

    def _task_from_issue(self, issue: ReviewIssue) -> ReviewTask:
        category = self._issue_category(issue)
        return ReviewTask(
            task_id=self._task_id("issue", issue.code, issue.scope),
            priority=issue.severity,
            category=category,
            title=self._issue_title(issue),
            detail=issue.message,
            source="review_gate",
            scope=issue.scope,
            action_label=self._issue_action_label(issue),
            action_path=self._issue_action_path(issue),
            blocks_export=issue.blocks_export,
            tax_year=issue.tax_year,
            asset=self._scope_part(issue.scope, "asset"),
            source_group="mexc" if issue.code.startswith("mexc_") else self._scope_part(issue.scope, "source"),
            count=1,
            evidence_refs=[issue.scope],
            decision_status=issue.code,
        )

    def _task_from_suggestion(self, suggestion: ReviewDecisionSuggestion) -> ReviewTask:
        category = "evidence"
        if "fifo" in suggestion.scope.lower() or "opening_balance" in suggestion.scope.lower():
            category = "fifo"
        return ReviewTask(
            task_id=self._task_id("suggestion", suggestion.suggestion_id),
            priority="high" if suggestion.confidence == "high" else "medium",
            category=category,
            title=suggestion.title,
            detail=suggestion.rationale,
            source="review_decision_suggestion",
            scope=suggestion.scope,
            action_label="Vorschlag uebernehmen",
            action_path=f"/api/v1/review/decision-suggestions/{suggestion.suggestion_id}/accept",
            blocks_export=False,
            asset=self._scope_part(suggestion.scope, "asset"),
            count=len(suggestion.affected_ids) or None,
            evidence_refs=[ref for ref in [suggestion.evidence_ref, *suggestion.affected_ids] if ref],
            decision_status=f"suggestion:{suggestion.confidence}",
        )

    def _token_risk_documentation_suggestions(self) -> list[ReviewDecisionSuggestion]:
        from steuerreport_v2.domain.portfolio import PortfolioService

        try:
            report = PortfolioService(self.store).token_risk_report(
                risk_status="spam_review",
                min_value_eur=Decimal("1"),
            )
        except Exception:
            return []

        suggestions: list[ReviewDecisionSuggestion] = []
        for row in report.rows:
            mint_or_asset = row.token_mint or row.asset
            digest = sha1(f"{row.asset}:{mint_or_asset}".encode("utf-8")).hexdigest()[:12]
            scope = f"token_risk:spam_review:asset:{row.asset}:mint:{mint_or_asset}"
            accounts = sorted({position.account for position in row.positions if position.account})
            affected_ids = [
                f"asset:{row.asset}",
                f"token_mint:{mint_or_asset}",
                *[f"account:{account}" for account in accounts],
                *[f"source:{source}" for source in row.discovered_sources],
            ]
            suggestions.append(
                ReviewDecisionSuggestion(
                    suggestion_id=f"token_risk_spam_review_{digest}",
                    decision_type="token_risk_documentation",
                    scope=scope,
                    title=f"Spam/Dust-Token dokumentieren: {row.asset}",
                    rationale=(
                        f"{row.asset} ist im Jupiter-Metadaten-Cache als spam_review "
                        f"markiert und steht mit {row.quantity} Einheiten bzw. "
                        f"{row.value_eur} EUR im aktuellen Portfolio. Diese Entscheidung "
                        "dokumentiert nur die Einordnung fuer Historie/Finanzamt; "
                        "Importe, Preise, Ledger, FIFO und Steuerzeilen werden nicht veraendert."
                    ),
                    evidence_ref="/api/v1/portfolio/token-risk?risk_status=spam_review&min_value_eur=1",
                    actor="codex",
                    source="api:/api/v1/review/decision-suggestions",
                    affected_ids=affected_ids,
                    payload={
                        "asset": row.asset,
                        "token_symbol": row.token_symbol,
                        "token_name": row.token_name,
                        "token_mint": row.token_mint,
                        "token_verified": row.token_verified,
                        "token_risk_status": row.token_risk_status,
                        "quantity": str(row.quantity),
                        "value_eur": str(row.value_eur),
                        "position_count": row.position_count,
                        "accounts": accounts,
                        "discovered_sources": row.discovered_sources,
                        "price_status": row.price_status,
                        "priced_at_latest": row.priced_at_latest.isoformat()
                        if row.priced_at_latest
                        else None,
                        "documentation_effect": "classification_only",
                        "import_effect": "none",
                        "ledger_effect": "none",
                        "fifo_effect": "none",
                        "tax_line_effect": "none",
                    },
                    confidence="medium",
                )
            )
        return suggestions

    def _price_quality_bucket_tasks(self, groups: list[object]) -> list[ReviewTask]:
        bucket_meta = {
            "stablecoin_fx_review": (
                "Stablecoin-FX-Preisgruppen pruefen",
                "/api/v1/prices/quality/stablecoin-fx-review",
                "Stablecoin-FX pruefen",
            ),
            "solscan_signature_review": (
                "Solscan-Signatur-Preisgruppen pruefen",
                "/api/v1/prices/quality/solscan-signature-review",
                "Solscan-Signaturen pruefen",
            ),
            "binance_normalizer_review": (
                "Binance-Normalizer-Preisgruppen pruefen",
                "/api/v1/prices/quality/binance-normalizer-review",
                "Binance-Normalizer pruefen",
            ),
            "event_quote_evidence_review": (
                "Event-Quote-Evidenzgruppen pruefen",
                "/api/v1/prices/quality/event-quote-evidence-review",
                "Event-Quote-Evidenz pruefen",
            ),
        }
        grouped: dict[str, dict[str, object]] = {}
        for group in groups:
            bucket = str(getattr(group, "review_bucket", ""))
            if bucket not in bucket_meta:
                continue
            item = grouped.setdefault(
                bucket,
                {
                    "count": 0,
                    "tax_lines_count": 0,
                    "tax_relevant_count": 0,
                    "assets": set(),
                    "evidence_refs": [],
                },
            )
            item["count"] = int(item["count"]) + 1
            tax_lines_count = int(getattr(group, "tax_lines_count", 0) or 0)
            item["tax_lines_count"] = int(item["tax_lines_count"]) + tax_lines_count
            if tax_lines_count > 0:
                item["tax_relevant_count"] = int(item["tax_relevant_count"]) + 1
            assets = item["assets"]
            if isinstance(assets, set):
                assets.add(str(getattr(group, "asset", "")))
            evidence_refs = item["evidence_refs"]
            evidence_ref = getattr(group, "evidence_ref", None)
            if isinstance(evidence_refs, list) and evidence_ref:
                evidence_refs.append(str(evidence_ref))

        tasks: list[ReviewTask] = []
        for bucket, item in grouped.items():
            title, action_path, action_label = bucket_meta[bucket]
            tax_lines_count = int(item["tax_lines_count"])
            count = int(item["count"])
            tax_relevant_count = int(item["tax_relevant_count"])
            assets = sorted(asset for asset in item["assets"] if asset) if isinstance(item["assets"], set) else []
            evidence_refs = item["evidence_refs"] if isinstance(item["evidence_refs"], list) else []
            tasks.append(
                ReviewTask(
                    task_id=self._task_id("price-quality-bucket", bucket),
                    priority="high" if tax_lines_count >= 1000 else "medium",
                    category="price",
                    title=title,
                    detail=(
                        f"{count} Gruppe(n), davon {tax_relevant_count} steuerrelevant "
                        f"mit {tax_lines_count} Tax-Line(s). Assets: "
                        f"{', '.join(assets[:8]) or '-'}."
                    ),
                    source="price_quality_manual_review",
                    scope=f"price_quality_bucket:{bucket}",
                    action_label=action_label,
                    action_path=action_path,
                    blocks_export=False,
                    count=count,
                    evidence_refs=evidence_refs[:5],
                    decision_status=bucket,
                )
            )
        return tasks

    def _enrich_tasks_with_token_metadata(self, tasks: list[ReviewTask]) -> None:
        for task in tasks:
            if not task.asset:
                continue
            metadata = self._token_metadata_for_asset(task.asset)
            if metadata is None:
                continue
            task.token_name = metadata.name
            task.token_symbol = metadata.symbol
            task.token_mint = metadata.mint
            task.token_verified = metadata.is_verified
            task.token_risk_status = metadata.risk_status

    def _token_metadata_for_asset(self, asset: str) -> object | None:
        if self._jupiter_metadata_cache is None:
            self._jupiter_metadata_cache = JupiterTokenService(self.store).cached_metadata_by_asset()
        return self._jupiter_metadata_cache.get(str(asset)) or self._jupiter_metadata_cache.get(str(asset).upper())

    def _source_reconciliation_tasks(self) -> list[ReviewTask]:
        from steuerreport_v2.domain.portfolio import PortfolioService
        from steuerreport_v2.domain.sources import SourceService

        portfolio_service = PortfolioService(self.store)
        overview = portfolio_service.source_overview()
        prices = portfolio_service._latest_prices()
        connector_by_source = {
            "Binance": "binance",
            "Bitget": "bitget",
            "Pionex": "pionex",
            ('Jup Wallet ' + private_alias('secondary_solana_wallet', 4, 3, '...')): "jup_wallet",
            ('Solana Wallet ' + private_alias('primary_solana_wallet', 6, 4, '...')): "solana_wallet",
        }
        tasks: list[ReviewTask] = []
        for group in overview.groups:
            connector_id = connector_by_source.get(group.source_group)
            if connector_id is None:
                continue
            live_value, live_anchor_source = self._stored_live_value(connector_id, prices)
            if live_value is None:
                continue
            delta_value = live_value - group.value_eur
            if self._is_bitget_documented_dust(group.source_group, live_value, delta_value):
                continue
            display_warning = self._source_display_warning(group.source_group, live_value, delta_value)
            if not display_warning:
                continue
            source_id = SourceService.source_id(group.source_group)
            abs_delta = abs(delta_value)
            priority = "high" if abs_delta >= Decimal("100") else "medium"
            tasks.append(
                ReviewTask(
                    task_id=self._task_id("source-reconciliation", source_id, group.current_status),
                    priority=priority,
                    category="reconciliation",
                    title=f"{group.source_group} Live-vs-Ledger klaeren",
                    detail=(
                        f"{display_warning} Ledger {group.value_eur} EUR, "
                        f"API-Live {live_value} EUR, Delta {delta_value} EUR."
                    ),
                    source="source_reconciliation",
                    scope=f"source_reconciliation:{source_id}",
                    action_label="Asset-Drilldown pruefen",
                    action_path=f"/api/v1/sources/{source_id}/reconciliation",
                    blocks_export=False,
                    source_group=group.source_group,
                    count=group.assets,
                    value_eur=abs_delta,
                    evidence_refs=[live_anchor_source] if live_anchor_source else [],
                    decision_status=group.current_status,
                )
            )
        return tasks

    def _stored_live_value(
        self,
        connector_id: str,
        prices: dict[str, object],
    ) -> tuple[Decimal | None, str | None]:
        from steuerreport_v2.domain.portfolio import PortfolioService

        with self.store.connect() as con:
            rows = con.execute(
                """
                select asset, sum(quantity), string_agg(distinct source, ', ' order by source)
                from portfolio_live_balance_snapshots
                where connector_id = ?
                  and fetched_at = (
                    select max(fetched_at)
                    from portfolio_live_balance_snapshots
                    where connector_id = ?
                  )
                group by asset
                order by asset
                """,
                [connector_id, connector_id],
            ).fetchall()
        if not rows:
            return None, None
        total = Decimal("0")
        sources: set[str] = set()
        for asset, quantity, source in rows:
            symbol = str(asset).upper()
            if symbol in PortfolioService.NON_VALUED_LIVE_RECEIPT_ASSETS:
                continue
            if source:
                sources.update(part.strip() for part in str(source).split(",") if part.strip())
            price = fiat_price_point(symbol) or prices.get(symbol)
            if price is None:
                continue
            total += (quantity or Decimal("0")) * price.price_eur
        return total, ", ".join(sorted(sources)) or None

    @staticmethod
    def _source_display_warning(
        source_group: str,
        live_value: Decimal,
        delta_value: Decimal,
    ) -> str | None:
        if source_group == "Binance":
            return (
                "Livewert aus gespeicherten Binance-API-Snapshots inkl. "
                "Spot/Earn/Product; Ledger-Delta bleibt separat zu klaeren."
            )
        if abs(delta_value) >= Decimal("5"):
            return "API-Livewert und steuerlicher Ledger weichen wesentlich ab."
        return None

    @staticmethod
    def _is_bitget_documented_dust(
        source_group: str,
        live_value: Decimal,
        delta_value: Decimal,
    ) -> bool:
        return source_group == "Bitget" and abs(live_value) < Decimal("1") and abs(delta_value) < Decimal("10")

    @staticmethod
    def _issue_category(issue: ReviewIssue) -> str:
        if issue.code == "mexc_snapshot_reconciliation_required":
            return "reconciliation"
        if issue.code.startswith("mexc_") and issue.code != "mexc_classification_required":
            return "import"
        if issue.code in {"missing_price", "missing_event_price"}:
            return "price"
        if issue.code == "unmapped_raw_objects":
            return "import"
        if issue.code == "unresolved_truncated_account":
            return "wallet"
        if issue.code in {"unmatched_tax_disposal", "zero_cost_tax_lots", "zero_proceeds_tax_lines"}:
            return "fifo"
        if issue.code == "derivative_missing_prices":
            return "tax"
        if issue.code == "negative_balance":
            return "reconciliation"
        return "tax"

    @staticmethod
    def _issue_title(issue: ReviewIssue) -> str:
        titles = {
            "unmapped_raw_objects": "Nicht normalisierte Rohzeilen klaeren",
            "missing_price": "Aktuellen Asset-Preis ergaenzen",
            "missing_event_price": "Historischen Event-Preis belegen",
            "unresolved_truncated_account": "Gekuerzte Wallet-Adresse aufloesen",
            "negative_balance": "Negativen Ledger-Bestand klaeren",
            "unmatched_tax_disposal": "FIFO-Abgang ohne Lot klaeren",
            "zero_cost_tax_lots": "FIFO-Lots mit 0 EUR Kosten pruefen",
            "zero_proceeds_tax_lines": "Steuerzeilen mit 0 EUR Erloes pruefen",
            "derivative_missing_prices": "Derivate-Preisbewertung ergaenzen",
            "derivative_fee_semantics_required": "Derivategebuehren und Nettokonvention pruefen",
            "derivative_cash_recalculation_required": "Derivateberechnung aktualisieren",
            "derivative_normalization_required": "Bitget-Funding und Sicherheitenzuordnung pruefen",
            "solana_history_classification_required": "Solana-Bewegung fachlich einordnen",
            "api_history_classification_required": "API-Beleg fachlich einordnen",
            "mexc_classification_required": "MEXC-Bewegung fachlich einordnen",
            "mexc_link_target_missing": "Fehlenden MEXC-Originalbeleg klaeren",
            "mexc_link_target_conflict": "MEXC-Beleg und korrigierte Buchung abgleichen",
            "mexc_original_integrity_failed": "MEXC-Originalintegritaet wiederherstellen",
            "mexc_native_binding_invalid": "MEXC-Belegbindung pruefen",
            "mexc_snapshot_reconciliation_required": "MEXC-Bestand und Historie abgleichen",
        }
        return titles.get(issue.code, issue.code.replace("_", " ").title())

    @staticmethod
    def _issue_action_label(issue: ReviewIssue) -> str:
        if issue.code in {"missing_price", "missing_event_price", "derivative_missing_prices"}:
            return "Preise pruefen"
        if issue.code == "unmapped_raw_objects":
            return "Import pruefen"
        if issue.code in {"unmatched_tax_disposal", "zero_cost_tax_lots", "zero_proceeds_tax_lines"}:
            return "FIFO pruefen"
        if issue.code in {"negative_balance", "unresolved_truncated_account"}:
            return "Ledger/Wallet pruefen"
        return "Review pruefen"

    @staticmethod
    def _issue_action_path(issue: ReviewIssue) -> str:
        if issue.code in {"missing_price", "missing_event_price", "derivative_missing_prices"}:
            return "/api/v1/prices/requirements"
        if issue.code == "unmapped_raw_objects":
            return "/api/v1/raw/objects"
        if issue.code in {"unmatched_tax_disposal", "zero_cost_tax_lots", "zero_proceeds_tax_lines"}:
            return "/api/v1/tax/unmatched-disposals"
        if issue.code in {"negative_balance", "unresolved_truncated_account"}:
            return "/api/v1/portfolio/reconciliation"
        return "/api/v1/review/gates"

    @staticmethod
    def _scope_part(scope: str, key: str) -> str | None:
        marker = f"{key}:"
        if marker not in scope:
            return None
        tail = scope.split(marker, 1)[1]
        value = tail.split(":", 1)[0].strip()
        return value or None

    @staticmethod
    def _abs_decimal(value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        return abs(value)

    @staticmethod
    def _task_id(*parts: str) -> str:
        raw = ":".join(parts)
        return "review_task_" + sha1(raw.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _deduplicate_tasks(tasks: list[ReviewTask]) -> list[ReviewTask]:
        seen: set[str] = set()
        result: list[ReviewTask] = []
        for task in tasks:
            if task.task_id in seen:
                continue
            seen.add(task.task_id)
            result.append(task)
        return result

    @staticmethod
    def _task_sort_key(task: ReviewTask) -> tuple[int, int, str]:
        priority = {"high": 0, "medium": 1, "low": 2}.get(task.priority, 3)
        blocking = 0 if task.blocks_export else 1
        return priority, blocking, task.title
