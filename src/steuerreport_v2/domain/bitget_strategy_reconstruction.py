from __future__ import annotations

import csv
from datetime import date, datetime, time, timezone
from decimal import Decimal
import hashlib
import html
import io
import json
from pathlib import Path
from typing import Any
import zipfile

import httpx

from steuerreport_v2.contracts.bitget_strategy_basis_decisions import (
    BitgetStrategyBasisDecisionReport,
)
from steuerreport_v2.contracts.bitget_strategy_fifo import (
    BitgetStrategyFifoGapReport,
    BitgetStrategySettlementGap,
)
from steuerreport_v2.contracts.bitget_strategy_reconstruction import (
    BitgetStrategyBasisReconstructionGroup,
    BitgetStrategyBasisReconstructionReport,
    BitgetStrategyDisposalReconstruction,
    BitgetStrategyReferencePrice,
    BitgetStrategyReferencePriceBackfillJob,
    BitgetStrategyReferencePriceBackfillRequest,
    BitgetStrategyReferencePriceBackfillResult,
)
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup


class BitgetStrategyBasisReconstructionService:
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
    DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT / "var/wallet_fifo_runs"
    DEFAULT_BACKFILL_ARTIFACT_ROOT = (
        PROJECT_ROOT / "var/bitget_strategy_price_backfill"
    )
    FRANKFURTER_URL = "https://api.frankfurter.dev/v2/rates"
    PRICE_SOURCE_PREFIX = "bitget_strategy_basis_anchor:v1"
    ONE_YEAR_DAYS = Decimal("365")
    MAX_READY_PRICE_AGE_HOURS = Decimal("24")

    def __init__(
        self,
        store: DuckDbStore,
        *,
        artifact_root: Path | None = None,
        backfill_artifact_root: Path | None = None,
    ) -> None:
        self.store = store
        self.artifact_root = artifact_root or (
            self.DEFAULT_ARTIFACT_ROOT
            if self.store.path.resolve() == self.DEFAULT_DB.resolve()
            else self.store.path.parent / "var/wallet_fifo_runs"
        )
        self.backfill_artifact_root = backfill_artifact_root or (
            self.DEFAULT_BACKFILL_ARTIFACT_ROOT
            if self.store.path.resolve() == self.DEFAULT_DB.resolve()
            else self.store.path.parent / "var/bitget_strategy_price_backfill"
        )

    def build(
        self,
        gap_report: BitgetStrategyFifoGapReport,
    ) -> BitgetStrategyBasisReconstructionReport:
        lookup = HistoricalPriceLookup(self.store)
        groups = [self._group(group, lookup) for group in gap_report.groups]
        disposal_rows = [row for group in groups for row in group.linked_disposals]
        blocked_groups = [
            group
            for group in groups
            if group.basis_reconstruction_status != "ready_for_professional_review"
        ]
        if not groups and gap_report.status == "no_gap":
            status = "no_gap"
        elif blocked_groups:
            status = "blocked_missing_inputs"
        else:
            status = "ready_for_professional_review"

        proceeds_total = self._sum_optional(
            row.attributable_disposal_proceeds_eur for row in disposal_rows
        )
        proxy_basis_total = self._sum_optional(
            row.settlement_value_proxy_basis_eur for row in disposal_rows
        )
        zero_basis_gain_total = self._sum_optional(
            row.zero_basis_gain_sensitivity_eur for row in disposal_rows
        )
        proxy_gain_total = self._sum_optional(
            row.settlement_value_proxy_gain_sensitivity_eur for row in disposal_rows
        )
        semantic_payload = {
            "as_of": self._utc(gap_report.as_of).isoformat(),
            "source_input": gap_report.source_run_input_fingerprint_digest,
            "source_gap": gap_report.semantic_sha256,
            "status": status,
            "groups": [group.model_dump(mode="json") for group in groups],
        }
        semantic_sha256 = hashlib.sha256(
            json.dumps(
                semantic_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()

        return BitgetStrategyBasisReconstructionReport(
            run_id=gap_report.run_id,
            generated_at=self._utc(gap_report.generated_at),
            as_of=self._utc(gap_report.as_of),
            source_run_input_fingerprint_digest=(
                gap_report.source_run_input_fingerprint_digest
            ),
            source_gap_semantic_sha256=gap_report.semantic_sha256,
            status=status,
            strict_ready=status == "no_gap",
            provider_export_field_gap=gap_report.support_package.provider_export_field_gap,
            support_package_complete=gap_report.support_package.package_complete,
            groups_count=len(groups),
            linked_disposals_count=len(disposal_rows),
            quantity_reconciled_groups_count=sum(
                group.quantity_reconciled for group in groups
            ),
            price_evidence_complete_groups_count=sum(
                group.price_evidence_complete for group in groups
            ),
            definitely_within_one_year_disposals_count=sum(
                row.holding_period_certainty == "definitely_within_one_year"
                for row in disposal_rows
            ),
            definitely_over_one_year_disposals_count=sum(
                row.holding_period_certainty == "definitely_over_one_year"
                for row in disposal_rows
            ),
            uncertain_holding_period_disposals_count=sum(
                row.holding_period_certainty
                in {"crosses_one_year_boundary", "invalid_time_order"}
                for row in disposal_rows
            ),
            attributable_disposal_proceeds_total_eur=proceeds_total,
            documented_cost_basis_floor_total_eur=Decimal("0"),
            documented_cost_basis_ceiling_total_eur=None,
            settlement_value_proxy_basis_total_eur=proxy_basis_total,
            zero_basis_gain_sensitivity_total_eur=zero_basis_gain_total,
            settlement_value_proxy_gain_sensitivity_total_eur=proxy_gain_total,
            groups=groups,
            findings=self._findings(
                gap_report=gap_report,
                groups=groups,
                disposal_rows=disposal_rows,
                proceeds_total=proceeds_total,
                proxy_basis_total=proxy_basis_total,
            ),
            next_actions=self._next_actions(status),
            evidence_refs=[
                f"/api/v1/tax/wallet-fifo/bitget-strategy-gaps?run_id={gap_report.run_id}",
                f"/api/v1/tax/wallet-fifo/bitget-support-package.zip?run_id={gap_report.run_id}",
                *gap_report.evidence_refs,
            ],
            semantic_sha256=semantic_sha256,
            methodology=(
                "Read-only Rekonstruktions- und Sensitivitaetsakte fuer die im vollstaendigen "
                "Bitget-Supportpaket nicht enthaltenen strategiegebundenen Bot-Fills. Das "
                "beobachtete Strategy-Zeitfenster begrenzt den moeglichen Erwerbszeitraum. "
                "Quote-Erloese werden anteilig auf die mengenmaessig zugeordneten Strategy-"
                "Abgaenge verteilt und mit dem historischen EUR-Preis der Quote bewertet. "
                "Die dokumentierte Kostenbasis-Untergrenze null zeigt ausschliesslich eine "
                "konservative Gewinnsensitivitaet. Der anteilige Settlement-Zeitwert ist ein "
                "Plausibilitaetsvergleich und keine behauptete Anschaffungskostenbasis. Eine "
                "belastbare Obergrenze wird bewusst nicht erfunden. Canonical Events, Lots, "
                "Tax-Lines, Ledger und Preise bleiben unveraendert."
            ),
        )

    def report(
        self,
        *,
        run_id: str | None = None,
    ) -> BitgetStrategyBasisReconstructionReport | None:
        payload = self._run_payload(run_id)
        if payload is None:
            return None
        evidence = next(
            (
                item
                for item in payload.get("evidence_files", [])
                if isinstance(item, dict)
                and item.get("kind") == "bitget_strategy_basis_reconstruction"
            ),
            None,
        )
        if evidence is None:
            return None
        path = self._resolve_path(str(evidence.get("path") or ""))
        try:
            content = path.read_bytes()
            if hashlib.sha256(content).hexdigest() != str(evidence.get("sha256") or ""):
                return None
            return BitgetStrategyBasisReconstructionReport.model_validate_json(content)
        except (OSError, ValueError):
            return None

    def backfill_reference_prices(
        self,
        request: BitgetStrategyReferencePriceBackfillRequest,
    ) -> BitgetStrategyReferencePriceBackfillResult:
        report = self.report(run_id=request.run_id)
        if report is None:
            raise ValueError(
                "Gebundene Bitget-Rekonstruktionsakte fehlt; zuerst Wallet-FIFO-Lauf erzeugen."
            )
        generated_at = datetime.now(timezone.utc)
        requested_dates = self._reference_price_dates(report)
        productive_before = self._productive_tax_component_sha256()
        jobs: list[BitgetStrategyReferencePriceBackfillJob] = []
        points: list[PricePointCreate] = []
        evidence_payloads: list[dict[str, object]] = []
        timeout = max(3, min(request.timeout_seconds, 60))
        with httpx.Client(
            timeout=timeout,
            headers={"user-agent": "steuerreport-v2/0.1"},
        ) as client:
            for requested_date in requested_dates:
                fx = self._fetch_fx(client, requested_date)
                if fx is None:
                    jobs.append(
                        BitgetStrategyReferencePriceBackfillJob(
                            requested_date=requested_date,
                            status="fetch_failed",
                            reason="Offizieller ECB-USD/EUR-Referenzkurs nicht abrufbar.",
                        )
                    )
                    continue
                source = self._reference_price_source(
                    requested_date=requested_date,
                    rate_date=fx["rate_date"],
                    response_sha256=str(fx["response_sha256"]),
                )
                evidence_payloads.append(
                    {
                        "asset": "USDT",
                        "requested_date": requested_date.isoformat(),
                        "provider_rate_date": fx["rate_date"].isoformat(),
                        "request_url": fx["request_url"],
                        "response_sha256": fx["response_sha256"],
                        "payload": fx["payload"],
                    }
                )
                if self._price_point_exists(requested_date, source):
                    jobs.append(
                        BitgetStrategyReferencePriceBackfillJob(
                            requested_date=requested_date,
                            provider_rate_date=fx["rate_date"],
                            usd_eur=fx["rate"],
                            status="already_ready",
                            request_url=str(fx["request_url"]),
                            response_sha256=str(fx["response_sha256"]),
                            price_source=source,
                            reason="Identischer hashgebundener Preisanker ist vorhanden.",
                        )
                    )
                    continue
                status = "imported" if request.execute else "planned"
                jobs.append(
                    BitgetStrategyReferencePriceBackfillJob(
                        requested_date=requested_date,
                        provider_rate_date=fx["rate_date"],
                        usd_eur=fx["rate"],
                        status=status,
                        request_url=str(fx["request_url"]),
                        response_sha256=str(fx["response_sha256"]),
                        price_source=source,
                        reason=(
                            "Additiver USDT/EUR-Preisanker importiert."
                            if request.execute
                            else "Additiver USDT/EUR-Preisanker im Dry-Run geplant."
                        ),
                    )
                )
                if request.execute:
                    points.append(
                        PricePointCreate(
                            asset="USDT",
                            price_eur=fx["rate"],
                            priced_at=datetime.combine(
                                requested_date,
                                time.min,
                                tzinfo=timezone.utc,
                            ),
                            source=source,
                            confidence=Decimal("1"),
                        )
                    )
        if points:
            self.store.add_price_points(points)
        productive_after = self._productive_tax_component_sha256()
        productive_unchanged = productive_before == productive_after
        failed_count = sum(job.status == "fetch_failed" for job in jobs)
        imported_count = sum(job.status == "imported" for job in jobs)
        planned_count = sum(job.status == "planned" for job in jobs)
        already_ready_count = sum(job.status == "already_ready" for job in jobs)
        if not productive_unchanged:
            status = "blocked"
        elif failed_count and (imported_count or planned_count or already_ready_count):
            status = "partial"
        elif failed_count:
            status = "blocked"
        else:
            status = "applied" if request.execute else "planned"

        artifact_id = (
            f"bitget-strategy-price-{generated_at.strftime('%Y%m%dT%H%M%S%fZ')}-"
            f"{report.semantic_sha256[:12]}"
        )
        evidence_path = self.backfill_artifact_root / f"{artifact_id}.evidence.json"
        evidence_content = json.dumps(
            {
                "generated_at": generated_at.isoformat(),
                "source_run_id": report.run_id,
                "execute": request.execute,
                "provider": "Frankfurter v2 / ECB",
                "responses": evidence_payloads,
            },
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8")
        self._atomic_write(evidence_path, evidence_content)
        evidence_sha256 = hashlib.sha256(evidence_content).hexdigest()
        semantic_payload = {
            "source_run_id": report.run_id,
            "execute": request.execute,
            "status": status,
            "productive_before": productive_before,
            "productive_after": productive_after,
            "jobs": [job.model_dump(mode="json") for job in jobs],
            "evidence_sha256": evidence_sha256,
        }
        semantic_sha256 = hashlib.sha256(
            json.dumps(
                semantic_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        artifact_path = self.backfill_artifact_root / f"{artifact_id}.json"
        latest_path = self.backfill_artifact_root / "latest.json"
        result = BitgetStrategyReferencePriceBackfillResult(
            generated_at=generated_at,
            source_run_id=report.run_id,
            execute=request.execute,
            status=status,
            read_only=not request.execute,
            requested_dates_count=len(requested_dates),
            planned_count=planned_count,
            imported_count=imported_count,
            already_ready_count=already_ready_count,
            failed_count=failed_count,
            productive_tax_component_sha256_before=productive_before,
            productive_tax_component_sha256_after=productive_after,
            productive_tax_tables_unchanged=productive_unchanged,
            jobs=jobs,
            artifact_path=self._display_path(artifact_path),
            semantic_sha256=semantic_sha256,
            evidence_artifact_path=self._display_path(evidence_path),
            evidence_artifact_sha256=evidence_sha256,
            findings=[
                (
                    f"{len(requested_dates)} konkrete USDT/EUR-Referenztage aus "
                    "der gebundenen Bitget-Rekonstruktionsakte geprueft."
                ),
                (
                    f"{imported_count} Preisanker importiert; {planned_count} geplant; "
                    f"{failed_count} fehlgeschlagen."
                ),
                (
                    "Produktive Tax-Lots und Tax-Lines blieben unveraendert."
                    if productive_unchanged
                    else "Produktiver Tax-Komponenten-Hash hat sich unerwartet geaendert."
                ),
            ],
            next_actions=(
                [
                    "Wallet-FIFO-Parallel-Run nach dem additiven Preisimport neu erzeugen.",
                    "Bitget-Rekonstruktionsakte erneut gegen Same-Day-Preisstatus pruefen.",
                ]
                if request.execute and imported_count
                else ["Dry-Run pruefen und erst danach execute=true aufrufen."]
                if not request.execute and planned_count
                else []
            ),
            methodology=(
                "Eng begrenzter additiver Backfill fuer USDT/EUR-Tage, die in einer "
                "versionierten Bitget-Strategy-Rekonstruktionsakte als abgeleitet, "
                "veraltet oder fehlend markiert sind. Der USD/EUR-Referenzkurs wird "
                "direkt vom Frankfurter-v2-Endpoint mit Provider ECB bezogen. URL, "
                "Payload und Response-SHA-256 werden archiviert. Der Lauf schreibt "
                "nur neue PricePoint-Zeilen und startet keinen Steuer- oder FIFO-Rebuild."
            ),
        )
        content = json.dumps(
            result.model_dump(mode="json"), indent=2, ensure_ascii=False
        ).encode("utf-8")
        self._atomic_write(artifact_path, content)
        self._atomic_write(latest_path, content)
        return result

    def latest_backfill(self) -> BitgetStrategyReferencePriceBackfillResult | None:
        path = self.backfill_artifact_root / "latest.json"
        try:
            return BitgetStrategyReferencePriceBackfillResult.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None

    @staticmethod
    def csv_bytes(report: BitgetStrategyBasisReconstructionReport) -> bytes:
        fieldnames = [
            "settlement_group_id",
            "strategy_id",
            "asset",
            "acquisition_window_start",
            "acquisition_window_end",
            "source_event_id",
            "disposal_at",
            "allocated_strategy_quantity",
            "minimum_holding_days",
            "maximum_holding_days",
            "holding_period_certainty",
            "attributable_disposal_quote_asset",
            "attributable_disposal_quote_quantity",
            "attributable_disposal_proceeds_eur",
            "documented_cost_basis_floor_eur",
            "documented_cost_basis_ceiling_eur",
            "zero_basis_gain_sensitivity_eur",
            "settlement_value_proxy_basis_eur",
            "settlement_value_proxy_gain_sensitivity_eur",
            "tax_basis_status",
            "productive_tax_effect",
        ]
        buffer = io.StringIO(newline="")
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for group in report.groups:
            for row in group.linked_disposals:
                writer.writerow(
                    {
                        "settlement_group_id": group.settlement_group_id,
                        "strategy_id": group.strategy_id,
                        "asset": row.asset,
                        "acquisition_window_start": row.acquisition_window_start.isoformat(),
                        "acquisition_window_end": row.acquisition_window_end.isoformat(),
                        "source_event_id": row.source_event_id,
                        "disposal_at": row.event_time.isoformat(),
                        "allocated_strategy_quantity": row.allocated_strategy_quantity,
                        "minimum_holding_days": row.minimum_holding_days,
                        "maximum_holding_days": row.maximum_holding_days,
                        "holding_period_certainty": row.holding_period_certainty,
                        "attributable_disposal_quote_asset": (
                            row.attributable_disposal_quote_asset
                        ),
                        "attributable_disposal_quote_quantity": (
                            row.attributable_disposal_quote_quantity
                        ),
                        "attributable_disposal_proceeds_eur": (
                            row.attributable_disposal_proceeds_eur
                        ),
                        "documented_cost_basis_floor_eur": (
                            row.documented_cost_basis_floor_eur
                        ),
                        "documented_cost_basis_ceiling_eur": (
                            row.documented_cost_basis_ceiling_eur
                        ),
                        "zero_basis_gain_sensitivity_eur": (
                            row.zero_basis_gain_sensitivity_eur
                        ),
                        "settlement_value_proxy_basis_eur": (
                            row.settlement_value_proxy_basis_eur
                        ),
                        "settlement_value_proxy_gain_sensitivity_eur": (
                            row.settlement_value_proxy_gain_sensitivity_eur
                        ),
                        "tax_basis_status": row.tax_basis_status,
                        "productive_tax_effect": row.productive_tax_effect,
                    }
                )
        return buffer.getvalue().encode("utf-8")

    @classmethod
    def professional_review_html(
        cls,
        report: BitgetStrategyBasisReconstructionReport,
        gap_report: BitgetStrategyFifoGapReport,
        decision_report: BitgetStrategyBasisDecisionReport | None = None,
    ) -> str:
        status_label = (
            "Keine offene Provider-Luecke"
            if report.status == "no_gap"
            else "Fachpruefung erforderlich"
            if report.status == "ready_for_professional_review"
            else "Eingaben unvollstaendig"
        )
        group_sections = "\n".join(
            cls._professional_review_group_html(group)
            for group in report.groups
        ) or "<p>Keine Bitget-Strategy-Kostenbasisluecke vorhanden.</p>"
        support_rows = "\n".join(
            f"""
            <tr>
              <td>{html.escape(item.filename)}</td>
              <td>{item.records_count}</td>
              <td><code>{html.escape(item.file_sha256)}</code></td>
              <td>{'ja' if item.contains_individual_executions else 'nein'}</td>
              <td>{'ja' if item.contains_strategy_link_field else 'nein'}</td>
            </tr>
            """
            for item in gap_report.support_package.files
        )
        official_urls = gap_report.api_history_boundary.official_documentation_urls
        classic_history_url = (
            official_urls[0]
            if official_urls
            else "https://www.bitget.com/api-doc/classic/spot/trade/Get-History-Orders"
        )
        uta_history_url = (
            official_urls[1]
            if len(official_urls) > 1
            else "https://www.bitget.com/api-doc/uta/trade/Get-Order-History"
        )
        decision_label = {
            "pending": "Noch keine Basismethode ausgewaehlt",
            "retain_provider_gap_pending_professional_review": (
                "Provider-Luecke bleibt bis zur Fachpruefung offen"
            ),
            "approve_zero_basis_estimate_for_staging": (
                "Nullbasis-Schaetzung nur fuer Staging ausgewaehlt"
            ),
            "approve_settlement_value_proxy_estimate_for_staging": (
                "Settlement-Proxy nur fuer Staging ausgewaehlt"
            ),
            "rejected_requires_rework": "Rekonstruktion zur Ueberarbeitung abgelehnt",
        }.get(
            decision_report.decision_status if decision_report is not None else "pending",
            "Noch keine Basismethode ausgewaehlt",
        )
        decision_meta = (
            f"<p class=\"meta\"><strong>Entscheidung:</strong> "
            f"{html.escape(decision_report.decision_status)}<br />"
            f"<strong>Methode:</strong> {html.escape(decision_report.selected_method)}<br />"
            f"<strong>Bearbeiter:</strong> {html.escape(decision_report.decision_actor or '-')}<br />"
            f"<strong>Begruendung:</strong> {html.escape(decision_report.decision_rationale or '-')}</p>"
            if decision_report is not None
            else ""
        )
        return f"""<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Bitget Strategy-FIFO Fachakte</title>
    <style>
      :root {{ color: #18211c; background: #f4f6f3; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }}
      * {{ box-sizing: border-box; }}
      body {{ margin: 0; }}
      header {{ background: #17251d; color: #fff; padding: 28px max(24px, calc((100vw - 1180px) / 2)); }}
      header p {{ color: #d7e1da; max-width: 850px; }}
      main {{ display: grid; gap: 24px; margin: 0 auto; max-width: 1180px; padding: 28px 24px 48px; }}
      section {{ border-bottom: 1px solid #d7ddd8; padding-bottom: 24px; }}
      h1, h2, h3 {{ letter-spacing: 0; margin: 0 0 10px; }}
      h1 {{ font-size: 32px; }}
      h2 {{ font-size: 21px; }}
      h3 {{ font-size: 16px; }}
      p, li {{ line-height: 1.5; }}
      .status {{ align-items: center; display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }}
      .pill {{ background: #fff3d5; border: 1px solid #c79521; border-radius: 999px; color: #5a3b00; font-size: 13px; font-weight: 750; padding: 5px 9px; }}
      .pill.neutral {{ background: #e8f1eb; border-color: #8ca394; color: #1c4b32; }}
      .metrics {{ display: grid; gap: 12px; grid-template-columns: repeat(4, minmax(0, 1fr)); }}
      .metric {{ border-left: 3px solid #46715a; padding: 4px 12px; }}
      .metric span {{ color: #5e6a62; display: block; font-size: 12px; }}
      .metric strong {{ display: block; font-size: 20px; margin-top: 4px; }}
      .notice {{ background: #fff8e8; border: 1px solid #dfc782; border-radius: 6px; padding: 14px; }}
      .ok {{ background: #edf6ef; border-color: #aac5b0; }}
      .group {{ margin-top: 22px; }}
      .group-head {{ align-items: baseline; display: flex; flex-wrap: wrap; gap: 8px 16px; }}
      .table-wrap {{ overflow-x: auto; }}
      table {{ border-collapse: collapse; min-width: 980px; width: 100%; }}
      th, td {{ border-bottom: 1px solid #e2e6e3; font-size: 12px; padding: 9px 8px; text-align: left; vertical-align: top; }}
      th {{ color: #59645c; font-weight: 750; text-transform: uppercase; }}
      td.number {{ font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }}
      code {{ overflow-wrap: anywhere; }}
      a.button, button {{ background: #2f5b45; border: 0; border-radius: 6px; color: #fff; cursor: pointer; display: inline-flex; font: inherit; font-weight: 700; padding: 9px 12px; text-decoration: none; }}
      .actions {{ display: flex; flex-wrap: wrap; gap: 8px; }}
      .meta {{ color: #59645c; font-size: 12px; overflow-wrap: anywhere; }}
      @media (max-width: 800px) {{ .metrics {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} h1 {{ font-size: 26px; }} }}
      @media print {{ body {{ background: #fff; }} header {{ background: #fff; color: #000; padding: 0 0 18px; }} header p {{ color: #333; }} main {{ max-width: none; padding: 0; }} .actions {{ display: none; }} section {{ break-inside: avoid; }} .group {{ break-inside: avoid; }} }}
    </style>
  </head>
  <body>
    <header>
      <h1>Bitget Strategy-FIFO Fachakte</h1>
      <p>Hashgebundene Pruefakte fuer mengenmaessig geklaerte Strategy-Settlements, deren originale Bot-Fill-Anschaffungskosten im vollstaendigen Anbieterexport fehlen.</p>
      <div class="status">
        <span class="pill">{html.escape(status_label)}</span>
        <span class="pill neutral">Keine produktive Steuerwirkung</span>
      </div>
    </header>
    <main>
      <div class="actions">
        <button type="button" onclick="window.print()">Drucken / als PDF speichern</button>
        <a class="button" href="/api/v1/tax/wallet-fifo/bitget-strategy-review-package.zip?run_id={html.escape(report.run_id, quote=True)}">Komplettes Pruefpaket</a>
        <a class="button" href="/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction?run_id={html.escape(report.run_id, quote=True)}">Maschinenlesbare Akte</a>
        <a class="button" href="/api/v1/tax/wallet-fifo/bitget-strategy-basis-decision?run_id={html.escape(report.run_id, quote=True)}">Methodenstatus</a>
      </div>
      <section>
        <h2>Ergebnis</h2>
        <div class="metrics">
          <div class="metric"><span>Settlement-Ketten</span><strong>{report.groups_count}</strong></div>
          <div class="metric"><span>Zugeordnete Abgaenge</span><strong>{report.linked_disposals_count}</strong></div>
          <div class="metric"><span>Belegte Verkaufserloese</span><strong>{cls._display_eur(report.attributable_disposal_proceeds_total_eur)}</strong></div>
          <div class="metric"><span>Ungeklaerte Mengenabgaenge</span><strong>{gap_report.unallocated_unmatched_disposals_count}</strong></div>
        </div>
        <p class="notice ok"><strong>Belegt:</strong> Menge, Strategy, Erwerbszeitfenster, Settlement, spaetere Abgaenge, Verkaufserloese, Haltedauerband und Originaldatei-Hashes sind nachvollziehbar.</p>
        <p class="notice"><strong>Nicht belegt:</strong> Die einzelnen Bot-Kaeufe mit exaktem Anschaffungszeitpunkt und exakten Anschaffungskosten. Nullbasis ({cls._display_eur(report.zero_basis_gain_sensitivity_total_eur)} Gewinnsensitivitaet) und anteiliger Settlement-Wert ({cls._display_eur(report.settlement_value_proxy_basis_total_eur)}) sind nur Vergleichswerte und keine freigegebene FIFO-Basis.</p>
      </section>
      <section>
        <h2>Fachlich notwendige Entscheidung</h2>
        <p class="notice"><strong>{html.escape(decision_label)}</strong></p>
        {decision_meta}
        <ol>
          <li>Das vollstaendige Bitget-Supportpaket und diese Rekonstruktionsakte gemeinsam pruefen.</li>
          <li>Nur eine fachlich begruendete Methode fuer die fehlende Bot-Fill-Basis freigeben; keine Werte stillschweigend schaetzen.</li>
          <li>Entscheidung mit Run-ID, semantischem Hash, Bearbeiter, Datum und Begruendung dokumentieren.</li>
          <li>Erst danach eine kontrollierte Wallet-FIFO-Migration ausfuehren und Jahresergebnisse erneut validieren.</li>
        </ol>
      </section>
      <section>
        <h2>Strategy-Ketten und Abgaenge</h2>
        {group_sections}
      </section>
      <section>
        <h2>Vollstaendiges Anbieterpaket</h2>
        <p>Vorhanden: {gap_report.support_package.available_files_count}/{gap_report.support_package.expected_files_count} Dateien. Strategy-verknuepfte Einzelfills: {gap_report.support_package.strategy_linked_fill_rows_count}.</p>
        <div class="table-wrap"><table>
          <thead><tr><th>Datei</th><th>Zeilen</th><th>SHA-256</th><th>Einzelausfuehrungen</th><th>Strategy-Linkfeld</th></tr></thead>
          <tbody>{support_rows}</tbody>
        </table></div>
      </section>
      <section>
        <h2>Bindung und Methodik</h2>
        <p class="meta"><strong>Run-ID:</strong> {html.escape(report.run_id)}<br /><strong>Input-Fingerprint:</strong> {html.escape(report.source_run_input_fingerprint_digest)}<br /><strong>Gap-Hash:</strong> {html.escape(report.source_gap_semantic_sha256)}<br /><strong>Rekonstruktions-Hash:</strong> {html.escape(report.semantic_sha256)}<br /><strong>Stichtag:</strong> {html.escape(report.as_of.isoformat())}</p>
        <p>{html.escape(report.methodology)}</p>
        <p class="meta">Offizielle Bitget-History-Dokumentation: <a href="{html.escape(classic_history_url, quote=True)}">Classic Spot</a> und <a href="{html.escape(uta_history_url, quote=True)}">UTA</a>. Die dokumentierte API-Historiengrenze ersetzt keine Originalbelege.</p>
      </section>
    </main>
  </body>
</html>"""

    @classmethod
    def professional_review_package_bytes(
        cls,
        report: BitgetStrategyBasisReconstructionReport,
        gap_report: BitgetStrategyFifoGapReport,
        *,
        support_package_zip: bytes,
    ) -> bytes:
        html_content = cls.professional_review_html(report, gap_report).encode("utf-8")
        files = {
            "Bitget_Strategy_FIFO_Fachakte.html": html_content,
            "machine/bitget_strategy_reconstruction.json": json.dumps(
                report.model_dump(mode="json"), indent=2, ensure_ascii=False
            ).encode("utf-8"),
            "machine/bitget_strategy_gap_report.json": json.dumps(
                gap_report.model_dump(mode="json"), indent=2, ensure_ascii=False
            ).encode("utf-8"),
            "machine/bitget_strategy_disposals.csv": cls.csv_bytes(report),
            "evidence/bitget_support_package.zip": support_package_zip,
        }
        manifest = {
            "package_version": "bitget_strategy_professional_review_v1",
            "run_id": report.run_id,
            "as_of": report.as_of.isoformat(),
            "source_input_fingerprint": report.source_run_input_fingerprint_digest,
            "gap_semantic_sha256": report.source_gap_semantic_sha256,
            "reconstruction_semantic_sha256": report.semantic_sha256,
            "productive_tax_effect": report.productive_tax_effect,
            "files": [
                {
                    "path": path,
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
                for path, content in sorted(files.items())
            ],
        }
        files["manifest.json"] = json.dumps(
            manifest, indent=2, ensure_ascii=False
        ).encode("utf-8")
        buffer = io.BytesIO()
        with zipfile.ZipFile(
            buffer,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for path, content in sorted(files.items()):
                info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                archive.writestr(info, content)
        return buffer.getvalue()

    @classmethod
    def _professional_review_group_html(
        cls,
        group: BitgetStrategyBasisReconstructionGroup,
    ) -> str:
        rows = "\n".join(
            f"""
            <tr>
              <td>{html.escape(row.event_time.isoformat())}</td>
              <td><code title="{html.escape(row.source_event_id, quote=True)}">{html.escape(cls._short_id(row.source_event_id))}</code></td>
              <td class="number">{html.escape(cls._display_decimal(row.allocated_strategy_quantity))} {html.escape(row.asset)}</td>
              <td class="number">{cls._display_eur(row.attributable_disposal_proceeds_eur)}</td>
              <td>{html.escape(row.holding_period_certainty)}</td>
              <td>{html.escape(row.tax_basis_status)}</td>
            </tr>
            """
            for row in group.linked_disposals
        )
        return f"""
        <div class="group">
          <div class="group-head">
            <h3>{html.escape(group.asset)} / {html.escape(group.strategy_type)}</h3>
            <span class="meta">Strategy {html.escape(group.strategy_id)}</span>
          </div>
          <p class="meta">Erwerbsfenster: {html.escape(group.acquisition_window_start.isoformat())} bis {html.escape(group.acquisition_window_end.isoformat())} | Settlement: {html.escape(group.settlement_at.isoformat())} | Mengengleichung: {html.escape(cls._display_decimal(group.strategy_quantity_without_cost_basis))} = {html.escape(cls._display_decimal(group.allocated_missing_quantity))} + {html.escape(cls._display_decimal(group.residual_quantity))} {html.escape(group.asset)}</p>
          <div class="table-wrap"><table>
            <thead><tr><th>Abgang UTC</th><th>Event</th><th>Menge</th><th>Erloes EUR</th><th>Haltedauer</th><th>Kostenbasis</th></tr></thead>
            <tbody>{rows}</tbody>
          </table></div>
        </div>
        """

    @staticmethod
    def _display_decimal(value: Decimal) -> str:
        return f"{value:f}"

    @classmethod
    def _display_eur(cls, value: Decimal | None) -> str:
        if value is None:
            return "-"
        normalized = value.quantize(Decimal("0.01"))
        raw = f"{normalized:,.2f}"
        return f"{raw.replace(',', 'X').replace('.', ',').replace('X', '.')} EUR"

    @staticmethod
    def _short_id(value: str) -> str:
        return value if len(value) <= 18 else f"{value[:9]}...{value[-6:]}"

    def _group(
        self,
        gap: BitgetStrategySettlementGap,
        lookup: HistoricalPriceLookup,
    ) -> BitgetStrategyBasisReconstructionGroup:
        strategy = gap.support_strategy_match
        if strategy is None:
            missing_price = self._missing_price("USDT", gap.settlement_at)
            return BitgetStrategyBasisReconstructionGroup(
                settlement_group_id=gap.settlement_group_id,
                year=gap.year,
                asset=gap.asset,
                strategy_id="missing",
                strategy_type="missing",
                acquisition_window_start=gap.settlement_at,
                acquisition_window_end=gap.settlement_at,
                settlement_at=gap.settlement_at,
                settlement_quantity=gap.settlement_quantity,
                supported_principal_carried_quantity=(
                    gap.supported_principal_carried_quantity
                ),
                strategy_quantity_without_cost_basis=(
                    gap.strategy_quantity_without_cost_basis
                ),
                allocated_missing_quantity=gap.allocated_missing_quantity,
                residual_quantity=gap.residual_quantity,
                quantity_reconciled=gap.quantity_reconciled,
                strategy_investment_reference_usdt=Decimal("0"),
                strategy_reported_gain_reference_usdt=Decimal("0"),
                investment_reference_price=missing_price,
                gain_reference_price=missing_price,
                settlement_reference_price=missing_price,
                basis_reconstruction_status="blocked_missing_strategy_match",
                evidence_refs=gap.evidence_refs,
                findings=["Strategy.csv-Zuordnung fehlt; Zeitfenster ist nicht belegbar."],
            )

        investment_price = self._price("USDT", strategy.created_at, lookup)
        gain_price = self._price("USDT", strategy.terminated_at, lookup)
        settlement_price = self._price("USDT", gap.settlement_at, lookup)
        settlement_value_eur = self._converted_value(
            gap.settlement_reference_value_usdt,
            settlement_price,
        )
        investment_value_eur = self._converted_value(
            strategy.investment_amount,
            investment_price,
        )
        gain_value_eur = self._converted_value(
            strategy.total_gains,
            gain_price,
        )
        linked = [
            self._disposal(
                gap=gap,
                event=row,
                acquisition_start=strategy.created_at,
                acquisition_end=strategy.terminated_at,
                settlement_value_eur=settlement_value_eur,
                lookup=lookup,
            )
            for row in gap.linked_disposals
        ]
        prices = [
            investment_price,
            gain_price,
            settlement_price,
            *[
                row.disposal_quote_price
                for row in linked
                if row.disposal_quote_price is not None
            ],
        ]
        price_complete = all(price.status == "ready" for price in prices)
        status = (
            "ready_for_professional_review"
            if gap.quantity_reconciled and price_complete
            else "blocked_missing_reference_price"
        )
        proceeds = self._sum_optional(
            row.attributable_disposal_proceeds_eur for row in linked
        )
        proxy_basis = self._sum_optional(
            row.settlement_value_proxy_basis_eur for row in linked
        )
        zero_gain = self._sum_optional(
            row.zero_basis_gain_sensitivity_eur for row in linked
        )
        proxy_gain = self._sum_optional(
            row.settlement_value_proxy_gain_sensitivity_eur for row in linked
        )
        findings = [
            (
                f"Erwerbszeitpunkt liegt nur im belegten Strategy-Fenster "
                f"{strategy.created_at.isoformat()} bis {strategy.terminated_at.isoformat()}."
            ),
            (
                "Dokumentierte Kostenbasis-Untergrenze ist 0 EUR; eine belastbare "
                "Obergrenze fehlt wegen der nicht exportierten Bot-Einzelfills."
            ),
            (
                "Der anteilige Settlement-Zeitwert ist ausschliesslich ein "
                "Sensitivitaetswert und darf nicht als produktive FIFO-Basis verwendet werden."
            ),
        ]
        if not price_complete:
            findings.append(
                "Mindestens ein EUR-Referenzpreis ist abgeleitet, veraltet oder fehlt."
            )
        return BitgetStrategyBasisReconstructionGroup(
            settlement_group_id=gap.settlement_group_id,
            year=gap.year,
            asset=gap.asset,
            strategy_id=strategy.strategy_id,
            strategy_type=strategy.strategy_type,
            acquisition_window_start=self._utc(strategy.created_at),
            acquisition_window_end=self._utc(strategy.terminated_at),
            settlement_at=self._utc(gap.settlement_at),
            settlement_quantity=gap.settlement_quantity,
            supported_principal_carried_quantity=gap.supported_principal_carried_quantity,
            strategy_quantity_without_cost_basis=gap.strategy_quantity_without_cost_basis,
            allocated_missing_quantity=gap.allocated_missing_quantity,
            residual_quantity=gap.residual_quantity,
            quantity_reconciled=gap.quantity_reconciled,
            strategy_investment_reference_usdt=strategy.investment_amount,
            strategy_reported_gain_reference_usdt=strategy.total_gains,
            settlement_reference_value_usdt=gap.settlement_reference_value_usdt,
            strategy_investment_reference_eur=investment_value_eur,
            strategy_reported_gain_reference_eur=gain_value_eur,
            settlement_reference_value_eur=settlement_value_eur,
            allocated_settlement_value_proxy_eur=proxy_basis,
            attributable_disposal_proceeds_eur=proceeds,
            zero_basis_gain_sensitivity_eur=zero_gain,
            settlement_value_proxy_gain_sensitivity_eur=proxy_gain,
            investment_reference_price=investment_price,
            gain_reference_price=gain_price,
            settlement_reference_price=settlement_price,
            linked_disposals=linked,
            price_evidence_complete=price_complete,
            basis_reconstruction_status=status,
            evidence_refs=gap.evidence_refs,
            findings=findings,
        )

    def _disposal(
        self,
        *,
        gap: BitgetStrategySettlementGap,
        event: Any,
        acquisition_start: datetime,
        acquisition_end: datetime,
        settlement_value_eur: Decimal | None,
        lookup: HistoricalPriceLookup,
    ) -> BitgetStrategyDisposalReconstruction:
        event_at = self._utc(event.event_time)
        acquisition_start = self._utc(acquisition_start)
        acquisition_end = self._utc(acquisition_end)
        minimum_days = self._days(event_at - acquisition_end)
        maximum_days = self._days(event_at - acquisition_start)
        holding_status = self._holding_status(minimum_days, maximum_days)
        quote_asset = event.quote_asset.upper() if event.quote_asset else None
        quote_quantity = None
        quote_price = None
        proceeds_eur = None
        if quote_asset and event.quote_quantity is not None and event.disposal_quantity:
            allocation_ratio = event.allocated_strategy_gap_quantity / event.disposal_quantity
            quote_quantity = abs(event.quote_quantity) * allocation_ratio
            quote_price = self._price(quote_asset, event_at, lookup)
            proceeds_eur = self._converted_value(quote_quantity, quote_price)
        proxy_basis = None
        if settlement_value_eur is not None and gap.settlement_quantity:
            proxy_basis = (
                settlement_value_eur
                * event.allocated_strategy_gap_quantity
                / gap.settlement_quantity
            )
        return BitgetStrategyDisposalReconstruction(
            settlement_group_id=gap.settlement_group_id,
            source_event_id=event.source_event_id,
            event_time=event_at,
            asset=event.asset,
            acquisition_window_start=acquisition_start,
            acquisition_window_end=acquisition_end,
            minimum_holding_days=minimum_days,
            maximum_holding_days=maximum_days,
            holding_period_certainty=holding_status,
            disposal_quantity=event.disposal_quantity,
            allocated_strategy_quantity=event.allocated_strategy_gap_quantity,
            attributable_disposal_quote_asset=quote_asset,
            attributable_disposal_quote_quantity=quote_quantity,
            disposal_quote_price=quote_price,
            attributable_disposal_proceeds_eur=proceeds_eur,
            zero_basis_gain_sensitivity_eur=proceeds_eur,
            settlement_value_proxy_basis_eur=proxy_basis,
            settlement_value_proxy_gain_sensitivity_eur=(
                proceeds_eur - proxy_basis
                if proceeds_eur is not None and proxy_basis is not None
                else None
            ),
            evidence_refs=[
                *gap.evidence_refs,
                *(
                    [f"{event.source_filename}:{event.source_row_number}"]
                    if event.source_filename and event.source_row_number is not None
                    else []
                ),
            ],
        )

    def _price(
        self,
        asset: str,
        requested_at: datetime,
        lookup: HistoricalPriceLookup,
    ) -> BitgetStrategyReferencePrice:
        requested_at = self._utc(requested_at)
        point = lookup.at_or_before(asset, requested_at)
        if point is None:
            return self._missing_price(asset, requested_at)
        priced_at = self._utc(point.priced_at)
        age_hours = self._hours(requested_at - priced_at)
        independent = not HistoricalPriceLookup.is_derived_source(point.source)
        same_day = priced_at.date() == requested_at.date()
        if not independent:
            status = "derived_review"
        elif age_hours > self.MAX_READY_PRICE_AGE_HOURS:
            status = "stale_review"
        else:
            status = "ready"
        return BitgetStrategyReferencePrice(
            asset=asset.upper(),
            requested_at=requested_at,
            price_eur=point.price_eur,
            priced_at=priced_at,
            source=point.source,
            confidence=point.confidence,
            age_hours=age_hours,
            same_day=same_day,
            independent=independent,
            status=status,
        )

    @staticmethod
    def _missing_price(asset: str, requested_at: datetime) -> BitgetStrategyReferencePrice:
        return BitgetStrategyReferencePrice(
            asset=asset.upper(),
            requested_at=BitgetStrategyBasisReconstructionService._utc(requested_at),
            status="missing",
        )

    @staticmethod
    def _converted_value(
        amount: Decimal | None,
        price: BitgetStrategyReferencePrice,
    ) -> Decimal | None:
        if amount is None or price.price_eur is None:
            return None
        return amount * price.price_eur

    @classmethod
    def _holding_status(
        cls,
        minimum_days: Decimal,
        maximum_days: Decimal,
    ) -> str:
        if minimum_days < 0 or maximum_days < 0:
            return "invalid_time_order"
        if maximum_days <= cls.ONE_YEAR_DAYS:
            return "definitely_within_one_year"
        if minimum_days > cls.ONE_YEAR_DAYS:
            return "definitely_over_one_year"
        return "crosses_one_year_boundary"

    @staticmethod
    def _findings(
        *,
        gap_report: BitgetStrategyFifoGapReport,
        groups: list[BitgetStrategyBasisReconstructionGroup],
        disposal_rows: list[BitgetStrategyDisposalReconstruction],
        proceeds_total: Decimal,
        proxy_basis_total: Decimal,
    ) -> list[str]:
        if not groups:
            return ["Keine Bitget-Strategy-FIFO-Basisluecke im gebundenen Lauf."]
        return [
            (
                f"{len(disposal_rows)} Abgaenge sind {len(groups)} belegten Strategy-"
                "Settlements mengenmaessig zugeordnet."
            ),
            (
                f"Auf die offene Strategy-Menge entfallen {proceeds_total} EUR belegte "
                "Verkaufserloese."
            ),
            (
                "Bei dokumentierter Nullbasis ergibt sich derselbe Betrag nur als "
                "konservative Gewinnsensitivitaet, nicht als freigegebener Steuerwert."
            ),
            (
                f"Der anteilige Settlement-Zeitwert von {proxy_basis_total} EUR ist "
                "Plausibilitaetsreferenz, keine Anschaffungskostenbasis."
            ),
            (
                "Das vollstaendige Anbieterpaket enthaelt keine strategiegebundenen "
                "Einzelfills; deshalb bleibt die belastbare Kostenbasis-Obergrenze leer."
            ),
            (
                f"Provider-Feldluecke bestaetigt: "
                f"{gap_report.support_package.provider_export_field_gap}."
            ),
        ]

    @staticmethod
    def _next_actions(status: str) -> list[str]:
        if status == "no_gap":
            return []
        actions = [
            "Rekonstruktionsakte zusammen mit dem vollstaendigen Bitget-Supportpaket fachlich pruefen.",
            "Zwischen konservativer Nullbasis und einem fachlich begruendeten Rekonstruktionsansatz entscheiden.",
            "Erst eine explizite, run- und hashgebundene Entscheidung darf die Wallet-FIFO-Migration beeinflussen.",
        ]
        if status == "blocked_missing_inputs":
            actions.insert(
                0,
                "Fehlende Strategy-Zuordnung oder historische EUR-Referenzpreise schliessen.",
            )
        return actions

    @staticmethod
    def _reference_price_dates(
        report: BitgetStrategyBasisReconstructionReport,
    ) -> list[date]:
        result: set[date] = set()
        for group in report.groups:
            prices = [
                group.investment_reference_price,
                group.gain_reference_price,
                group.settlement_reference_price,
                *[
                    row.disposal_quote_price
                    for row in group.linked_disposals
                    if row.disposal_quote_price is not None
                ],
            ]
            for price in prices:
                if price.asset == "USDT" and price.status != "ready":
                    result.add(price.requested_at.date())
        return sorted(result)

    def _fetch_fx(
        self,
        client: httpx.Client,
        requested_date: date,
    ) -> dict[str, Any] | None:
        try:
            response = client.get(
                self.FRANKFURTER_URL,
                params={
                    "date": requested_date.isoformat(),
                    "base": "USD",
                    "quotes": "EUR",
                    "providers": "ECB",
                },
            )
            if response.status_code >= 400:
                return None
            payload = response.json()
        except (httpx.HTTPError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(payload, list) or not payload:
            return None
        row = payload[0]
        if not isinstance(row, dict) or not row.get("date"):
            return None
        rate = self._decimal(row.get("rate"))
        if rate <= 0:
            return None
        return {
            "rate": rate,
            "rate_date": date.fromisoformat(str(row["date"])),
            "request_url": str(response.request.url),
            "response_sha256": hashlib.sha256(response.content).hexdigest(),
            "payload": payload,
        }

    def _price_point_exists(self, requested_date: date, source: str) -> bool:
        with self.store.connect() as con:
            row = con.execute(
                """
                select count(*)::integer
                from price_ledger
                where upper(asset) = 'USDT'
                  and cast(priced_at as date) = ?
                  and source = ?
                """,
                [requested_date, source],
            ).fetchone()
        return bool(row and row[0])

    def _productive_tax_component_sha256(self) -> str:
        digest = hashlib.sha256()
        queries = (
            """
            select lot_id, asset, acquired_at, quantity_total,
                   quantity_remaining, cost_basis_eur_total, source_event_id
            from tax_lots order by all
            """,
            """
            select tax_line_id, lot_id, asset, acquired_at, disposed_at,
                   quantity, acquisition_cost_eur, disposal_proceeds_eur,
                   gain_loss_eur, holding_days, source_event_id,
                   acquisition_source_event_id
            from tax_lines order by all
            """,
        )
        with self.store.connect() as con:
            for query in queries:
                cursor = con.execute(query)
                while rows := cursor.fetchmany(2000):
                    for row in rows:
                        digest.update(
                            json.dumps(
                                [self._json_value(value) for value in row],
                                ensure_ascii=True,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        )
                        digest.update(b"\n")
        return digest.hexdigest()

    @classmethod
    def _reference_price_source(
        cls,
        *,
        requested_date: date,
        rate_date: date,
        response_sha256: str,
    ) -> str:
        return (
            f"{cls.PRICE_SOURCE_PREFIX}:stablecoin_usd_parity:"
            f"usd_eur:frankfurter_v2_ecb:requested_date:{requested_date.isoformat()}:"
            f"rate_date:{rate_date.isoformat()}:response_sha256:{response_sha256}"
        )

    def _run_payload(self, run_id: str | None) -> dict[str, Any] | None:
        if run_id is not None:
            if not run_id.startswith("wallet-fifo-") or Path(run_id).name != run_id:
                return None
        path = (
            self.artifact_root / run_id / "wallet_fifo_parallel_run.json"
            if run_id
            else self.artifact_root / "latest_wallet_fifo_run.json"
        )
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def _resolve_path(self, raw_path: str) -> Path:
        path = Path(raw_path)
        return path if path.is_absolute() else self.PROJECT_ROOT / path

    @classmethod
    def _display_path(cls, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(cls.PROJECT_ROOT.resolve()))
        except ValueError:
            return str(path.resolve())

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)

    @staticmethod
    def _decimal(value: object) -> Decimal:
        try:
            return Decimal(str(value))
        except (ValueError, TypeError):
            return Decimal("0")

    @staticmethod
    def _json_value(value: object) -> object:
        if isinstance(value, (datetime, date, Decimal)):
            return str(value)
        if isinstance(value, bytes):
            return value.hex()
        return value

    @staticmethod
    def _sum_optional(values: Any) -> Decimal:
        return sum((value for value in values if value is not None), Decimal("0"))

    @staticmethod
    def _days(delta: Any) -> Decimal:
        return Decimal(str(delta.total_seconds())) / Decimal("86400")

    @staticmethod
    def _hours(delta: Any) -> Decimal:
        return max(Decimal(str(delta.total_seconds())) / Decimal("3600"), Decimal("0"))

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
