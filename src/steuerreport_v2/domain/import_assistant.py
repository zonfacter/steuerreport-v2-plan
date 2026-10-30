from __future__ import annotations

from datetime import datetime
from uuid import UUID

from steuerreport_v2.contracts.imports import (
    ImportAssistantExecuteResult,
    ImportAssistantExecutionPlan,
    ImportAssistantLinkedPreflight,
    ImportAssistantPipelineSnapshot,
    ImportAssistantPreview,
    ImportAssistantPriceNeed,
    ImportAssistantRequest,
    ImportAssistantTaxImpact,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.connections import ConnectionError, ConnectionService
from steuerreport_v2.domain.import_context import bitget_import_context
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.file_raw_importer import FileRawImporter


def validate_import_connection_binding(
    store: DuckDbStore,
    *,
    source: str,
    import_mode: str,
    connection_id: str | UUID | None,
) -> str | None:
    if connection_id is None:
        return None
    provider = source.strip().lower()
    if import_mode != "file":
        raise ValueError("connection_binding_file_mode_required")
    if provider not in {"binance", "bitget"}:
        raise ValueError("connection_binding_provider_unsupported")
    try:
        return ConnectionService(store).validate_import_binding(connection_id, provider)
    except ConnectionError as exc:
        raise ValueError(exc.code) from None


def binance_file_requires_connection(source: str, matched_columns: dict[str, str | None]) -> bool:
    return source.strip().lower() == "binance" and matched_columns.get("account") is None


class ImportAssistantService:
    SUPPORTED_API_SOURCES = {"binance", "bitget", "pionex", "solana_wallet", "jup_wallet"}

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def preview(self, request: ImportAssistantRequest) -> ImportAssistantPreview:
        warnings: list[str] = []
        current_state = self._current_state()
        import_context: dict[str, str] = {}
        context_error: str | None = None
        context_missing: list[str] = []
        if request.source.strip().lower() == "bitget":
            try:
                import_context = bitget_import_context(
                    export_timezone=request.export_timezone,
                    product_scope=request.bitget_product_scope,
                    margin_pair=request.bitget_margin_pair,
                    allow_legacy_defaults=False,
                )
            except ValueError as exc:
                context_error = {
                    "import_timezone_invalid": "Die Exportzeitzone ist ungueltig.",
                    "bitget_export_timezone_required": "Eine Exportzeitzone muss ausdruecklich ausgewaehlt werden.",
                    "bitget_product_scope_required": "Ein Bitget-Produktscope muss ausdruecklich ausgewaehlt werden.",
                    "bitget_margin_pair_required": "Bei Isolated Margin ist ein Handelspaar erforderlich.",
                    "bitget_margin_pair_not_applicable": "Ein Margin-Paar ist nur bei Isolated Margin zulaessig.",
                }.get(str(exc), "Der Bitget-Importkontext ist ungueltig.")
            if not request.export_timezone or not request.export_timezone.strip():
                context_missing.append("Exportzeitzone")
            if request.bitget_product_scope is None:
                context_missing.append("Produktscope")
            if request.connection_id is None:
                context_missing.append("Bitget-Verbindung")
            if context_error:
                context_missing.append("gueltige Zeitzone oder Margin-Paar")
        connection_id = validate_import_connection_binding(
            self.store,
            source=request.source,
            import_mode=request.import_mode,
            connection_id=request.connection_id,
        )
        if request.import_mode != "file":
            linked_preflights = self._linked_preflights(request)
            return ImportAssistantPreview(
                source=request.source,
                import_mode=request.import_mode,
                can_execute=False,
                import_context=import_context,
                blocked_reason=(
                    "Dieser Assistent fuehrt diese Importart nicht direkt aus. "
                    "Nutze zuerst die verlinkten Preflight-Endpunkte; ein spaeterer "
                    "Execute muss ueber den spezialisierten, belegbaren Pfad laufen."
                ),
                tax_impact=ImportAssistantTaxImpact(),
                current_state=current_state,
                estimated_state=current_state,
                execution_plan=self._execution_plan(can_execute=False, filename=request.filename),
                linked_preflights=linked_preflights,
                steps=["Quelle", "Importart", "Vorschau", "Preisbedarf", "Steuerwirkung"],
                warnings=[
                    f"Importart {request.import_mode} ist im Assistenten Preview-only.",
                    *(
                        []
                        if linked_preflights
                        else [f"Fuer Quelle {request.source} ist noch kein spezialisierter Preflight verknuepft."]
                    ),
                ],
            )

        preview = self._file_preview(request, import_context)
        warnings.extend(preview.blocking_reasons)
        if preview.mexc:
            warnings.extend(preview.mexc.warnings)
            warnings.extend(preview.mexc.blocking_reasons)
        assets, years = self._detect_assets_and_years(preview.sample_rows)
        if preview.mexc:
            from steuerreport_v2.domain.tax_time import reporting_tax_year
            assets = sorted({row.asset for row in preview.mexc.rows if row.asset})
            years = sorted({reporting_tax_year(datetime.fromisoformat(row.event_time))
                            for row in preview.mexc.rows if row.event_time})
        price_needs = self._price_needs(assets, years)
        timezone_unavailable = (
            request.source.strip().lower() == "bitget"
            and (context_error is not None or not request.export_timezone or not request.export_timezone.strip())
        )
        estimated_normalizable_rows = (
            None if timezone_unavailable
            else (preview.mexc.bookable_rows if preview.mexc else preview.row_count)
            if preview.can_import else 0
        )
        expected_issues = []
        if preview.missing_required_groups:
            expected_issues.append("missing_required_columns")
        if preview.duplicate_batch_id:
            expected_issues.append("duplicate_import_batch")
        missing_price_assets = [item.asset for item in price_needs if not item.latest_price_available]
        if missing_price_assets:
            expected_issues.append("missing_current_price_reference")
        if preview.duplicate_batch_id:
            warnings.append(f"Dublette erkannt: {preview.duplicate_batch_id}")
            if (
                request.source.strip().lower() == "bitget"
                and preview.duplicate_batch_import_context != import_context
            ):
                warnings.append(
                    "Der vorhandene Batch wurde mit anderem oder unbekanntem Importkontext angelegt. Er wird nicht als Import mit der aktuellen Auswahl wiederverwendet."
                )
        if preview.missing_required_groups:
            warnings.append(
                "Fehlende Pflichtfelder: " + ", ".join(preview.missing_required_groups)
            )
        binding_required = binance_file_requires_connection(
            request.source, preview.matched_columns,
        )
        if binding_required and connection_id is None:
            warnings.append(
                "Diese Binance-Datei hat keine Konto-/Wallet-Spalte. Vor dem Import muss "
                "eine konkrete Binance-Verbindung ausgewaehlt werden."
            )
        if request.source.strip().lower() == "bitget":
            if request.export_timezone and request.export_timezone.strip() and not context_error:
                warnings.append(
                    "Zeitstempel mit eigenem UTC-Offset behalten diesen Offset; die ausgewaehlte Exportzeitzone gilt nur fuer Zeitwerte ohne Offset."
                )
            else:
                warnings.append(
                    "Der Importkontext ist unvollstaendig oder ungueltig. Lokale Zeitwerte werden in dieser Vorschau nicht interpretiert; es wird kein UTC+08-Fallback verwendet und der Import bleibt gesperrt."
                )
            if request.bitget_product_scope:
                warnings.append(
                    "Produktscope anhand des Originalexports pruefen: Eine falsche Auswahl kann produktspezifische Plausibilitaetspruefungen umgehen. Der Scope ist kein Eigentums- oder Unterkontonachweis."
                )
            if context_error:
                warnings.append(context_error)
            if context_missing:
                warnings.append("Vor dem Import erforderlich: " + ", ".join(context_missing) + ".")
        mexc_blocked = bool(
            preview.mexc
            and (preview.mexc.blocking_reasons or preview.mexc.disposition in {"empty", "unsupported"})
        )
        can_execute = (
            preview.can_import
            and preview.duplicate_batch_id is None
            and not (binding_required and connection_id is None)
            and not context_missing
            and not preview.blocking_reasons
            and not mexc_blocked
        )
        return ImportAssistantPreview(
            source=request.source,
            import_mode=request.import_mode,
            import_context=import_context,
            can_execute=can_execute,
            blocked_reason=(
                "Fuer eine Binance-Datei ohne Konto-/Wallet-Spalte ist eine ausdrueckliche "
                "Bindung an eine bestehende Binance-Verbindung erforderlich."
                if binding_required and connection_id is None
                else "Bitget-Import benoetigt eine bestehende Verbindung, Exportzeitzone und Produktscope."
                if request.source.strip().lower() == "bitget" and context_missing
                else "; ".join(preview.blocking_reasons)
                if preview.blocking_reasons
                else "; ".join(preview.mexc.blocking_reasons)
                if preview.mexc and preview.mexc.blocking_reasons
                else self._blocked_reason(preview)
            ),
            preview=preview,
            price_needs=price_needs,
            tax_impact=ImportAssistantTaxImpact(
                estimated_new_rows=preview.row_count,
                estimated_normalizable_rows=estimated_normalizable_rows,
                detected_assets=assets,
                detected_years=years,
                duplicate_batch_id=preview.duplicate_batch_id,
                expected_review_issue_codes=expected_issues,
            ),
            current_state=current_state,
            estimated_state=self._estimated_state(
                current_state,
                raw_rows=preview.row_count,
                can_execute=can_execute,
            ),
            execution_plan=self._execution_plan(can_execute=can_execute, filename=request.filename),
            linked_preflights=self._linked_preflights(request),
            steps=[
                "Quelle",
                "Importart",
                "Vorschau",
                "Preisbedarf",
                "Steuerwirkung",
                "Ausfuehren",
            ],
            warnings=warnings,
        )

    def execute(self, request: ImportAssistantRequest) -> ImportAssistantExecuteResult:
        preview = self.preview(request)
        if not preview.can_execute:
            raise ValueError(preview.blocked_reason or "Import-Assistent ist blockiert.")
        connection_id = str(request.connection_id) if request.connection_id else None
        if request.content_base64:
            batch = FileRawImporter(CsvRawImporter(self.store)).import_base64(
                source=request.source,
                filename=request.filename or "import.xlsx",
                content_base64=request.content_base64,
                sheet_name=request.sheet_name,
                connection_id=str(connection_id) if connection_id else None,
                mexc=request.mexc,
                import_context=preview.import_context,
            )
        else:
            batch = CsvRawImporter(self.store).import_text(
                source=request.source,
                filename=request.filename or "import.csv",
                content=request.content or "",
                connection_id=str(connection_id) if connection_id else None,
                mexc=request.mexc,
                import_context=preview.import_context,
            )
        run = PipelineService(self.store).rebuild_after_import(batch.batch_id)
        return ImportAssistantExecuteResult(preview=preview, batch=batch, run=run)

    def _file_preview(self, request: ImportAssistantRequest, import_context: dict[str, str]):
        connection_id = str(request.connection_id) if request.connection_id else None
        if request.content_base64:
            return FileRawImporter(CsvRawImporter(self.store)).preview_base64(
                source=request.source,
                filename=request.filename or "import.xlsx",
                content_base64=request.content_base64,
                sheet_name=request.sheet_name,
                connection_id=connection_id,
                mexc=request.mexc,
                import_context=import_context,
                allow_legacy_bitget_context=False,
            )
        return CsvRawImporter(self.store).preview_text(
            source=request.source,
            filename=request.filename or "import.csv",
            content=request.content or "",
                connection_id=connection_id,
            mexc=request.mexc,
            import_context=import_context,
            allow_legacy_bitget_context=False,
        )

    def _price_needs(self, assets: list[str], years: list[int]) -> list[ImportAssistantPriceNeed]:
        latest = self.store.latest_price_points()
        fiat_assets = {"EUR"}
        return [
            ImportAssistantPriceNeed(
                asset=asset,
                years=years,
                latest_price_available=asset.upper() in fiat_assets or asset.upper() in latest,
            )
            for asset in assets
        ]

    def _detect_assets_and_years(self, rows: list[dict[str, str | None]]) -> tuple[list[str], list[int]]:
        assets: set[str] = set()
        years: set[int] = set()
        for row in rows:
            normalized = {key.lower().strip(): value for key, value in row.items()}
            for key in ("asset", "coin", "currency", "base asset", "crypto"):
                value = normalized.get(key)
                if value:
                    assets.add(value.strip().upper())
            for key in ("quote_asset", "quote asset", "fee_asset", "fee asset"):
                value = normalized.get(key)
                if value:
                    assets.add(value.strip().upper())
            for value in normalized.values():
                if not value:
                    continue
                parsed = self._parse_year(value)
                if parsed is not None:
                    years.add(parsed)
        return sorted(assets), sorted(years)

    def _parse_year(self, value: str) -> int | None:
        text = value.strip()
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).year
        except ValueError:
            pass
        for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(text, fmt).year
            except ValueError:
                continue
        if len(text) >= 4 and text[:4].isdigit():
            year = int(text[:4])
            if 2000 <= year <= 2100:
                return year
        return None

    def _linked_preflights(self, request: ImportAssistantRequest) -> list[ImportAssistantLinkedPreflight]:
        source = request.source.strip().lower()
        if request.import_mode == "api":
            if source == "binance":
                return [
                    ImportAssistantLinkedPreflight(
                        label="Binance Earn Liveprodukt-Preflight",
                        endpoint="/api/v1/sources/binance/earn-history-preflight",
                        external_requests=False,
                        purpose=(
                            "Ermittelt aus gespeicherten Live-Snapshot-Ankern, "
                            "welche Binance-Earn-Produkte Historie brauchen."
                        ),
                        next_step=(
                            "Danach Binance Earn History API Preview mit kleinem "
                            "Zeitfenster starten."
                        ),
                    ),
                    ImportAssistantLinkedPreflight(
                        label="Binance Earn History API Preview",
                        endpoint="/api/v1/sources/binance/earn-history-api-preview?since=2025-01-01&max_pages=2&max_records=500",
                        external_requests=True,
                        purpose=(
                            "Signierter read-only USER_DATA-Abruf fuer Subscription-, "
                            "Redemption- und Reward-Historie."
                        ),
                        next_step=(
                            "Harvest lokal speichern, pruefen und erst danach ueber "
                            "/api/v1/sources/binance/earn-history-harvest/import importieren."
                        ),
                    ),
                    ImportAssistantLinkedPreflight(
                        label="Binance Harvest Import Preview",
                        endpoint="/api/v1/sources/binance/earn-history-harvest/import",
                        method="POST",
                        writes_database=False,
                        purpose=(
                            "Prueft eine lokal gespeicherte Binance-History-Ernte "
                            "mit execute=false auf neue importierbare Records."
                        ),
                        next_step="Bei sauberer Preview denselben Endpoint bewusst mit execute=true ausfuehren.",
                    ),
                ]
            return [
                ImportAssistantLinkedPreflight(
                    label=f"{request.source} API-Importpfad",
                    endpoint="/api/v1/import/assistant/preview",
                    purpose="Noch kein spezialisierter API-Preflight fuer diese Quelle registriert.",
                    next_step="Quelle zuerst ueber Quellen-Cockpit/Reconciliation klaeren.",
                )
            ]
        if request.import_mode == "onchain":
            if source in {"solana", "solana_wallet", "jup_wallet", "solscan", "helium"}:
                return [
                    ImportAssistantLinkedPreflight(
                        label="Solscan Token Coverage Preflight",
                        endpoint="/api/v1/import/solscan/token-preflight",
                        external_requests=False,
                        purpose=(
                            "Vergleicht vorhandene Solscan-/Blockpit-Dateien und "
                            "zeigt fehlende Signaturen, ohne zu importieren."
                        ),
                        next_step="Fehlende Signaturen optional per RPC-Probe belegen.",
                    ),
                    ImportAssistantLinkedPreflight(
                        label="Solana RPC Signature Probe",
                        endpoint="/api/v1/import/solscan/rpc-probe",
                        method="POST",
                        external_requests=True,
                        purpose=(
                            "Verifiziert konkrete Signaturen read-only gegen RPC "
                            "und schreibt keine V2-Steuerdaten."
                        ),
                        next_step="Verifizierte Evidence als Beleg nutzen; Realimport bleibt separater kuratierter Pfad.",
                    ),
                    ImportAssistantLinkedPreflight(
                        label="Solana Evidence Trace",
                        endpoint="/api/v1/import/solscan/evidence-trace",
                        external_requests=False,
                        purpose=(
                            "Buendelt Solscan-Coverage, Blockpit-Referenz und "
                            "RPC-Artefakt als read-only Belegspur."
                        ),
                        next_step=(
                            "Trace im Report-/Review-Kontext verwenden; kein "
                            "Portfolio- oder Steuerdatenimport."
                        ),
                    ),
                ]
            return [
                ImportAssistantLinkedPreflight(
                    label=f"{request.source} Onchain-Preflight",
                    endpoint="/api/v1/import/parser-preflight",
                    purpose="Noch kein spezialisierter Onchain-Preflight fuer diese Quelle registriert.",
                    next_step="Parser-Preflight ausfuehren und Datei-/Parserbedarf klaeren.",
                )
            ]
        if request.import_mode == "v1_cache":
            return [
                ImportAssistantLinkedPreflight(
                    label="V1 FX Cache Preis-Preview",
                    endpoint="/api/v1/prices/import/v1-fx-cache/preview",
                    method="POST",
                    purpose="Prueft belegbare historische V1-Preise ohne Persistenz.",
                    next_step="Nur nach positiver Preview V1-FX-Cache-Import ausfuehren.",
                )
            ]
        return []

    def _blocked_reason(self, preview: object) -> str | None:
        if not preview.can_import:
            return "Preview ist nicht importfaehig."
        if preview.duplicate_batch_id:
            return f"Datei wurde bereits importiert: {preview.duplicate_batch_id}"
        return None

    def _current_state(self) -> ImportAssistantPipelineSnapshot:
        counts = self.store.table_counts(
            [
                "raw_import_batches",
                "raw_objects",
                "canonical_events",
                "balance_ledger",
                "tax_lines",
                "derivative_lines",
            ]
        )
        gate = ReviewService(self.store).gate()
        return ImportAssistantPipelineSnapshot(
            import_batches=counts["raw_import_batches"],
            raw_objects=counts["raw_objects"],
            canonical_events=counts["canonical_events"],
            balance_entries=counts["balance_ledger"],
            tax_lines=counts["tax_lines"],
            derivative_lines=counts["derivative_lines"],
            review_issues_open=gate.issues_open,
            allow_export=gate.allow_export,
        )

    def _estimated_state(
        self,
        current: ImportAssistantPipelineSnapshot,
        *,
        raw_rows: int,
        can_execute: bool,
    ) -> ImportAssistantPipelineSnapshot:
        if not can_execute:
            return current.model_copy()
        tax_summary = TaxService(self.store).latest_summary()
        return ImportAssistantPipelineSnapshot(
            import_batches=current.import_batches + 1,
            raw_objects=current.raw_objects + raw_rows,
            canonical_events=current.canonical_events,
            balance_entries=current.balance_entries,
            tax_lines=tax_summary.tax_lines_count if tax_summary is not None else current.tax_lines,
            derivative_lines=current.derivative_lines,
            review_issues_open=current.review_issues_open,
            allow_export=current.allow_export,
        )

    @staticmethod
    def _execution_plan(
        *,
        can_execute: bool,
        filename: str | None,
    ) -> ImportAssistantExecutionPlan:
        affected = [
            "raw_import_batches",
            "raw_objects",
            "canonical_events",
            "balance_ledger",
            "flow_ledger",
            "tax_lots",
            "tax_lines",
            "tax_unmatched_disposals",
            "derivative_lines",
            "review_gate_readonly",
        ]
        return ImportAssistantExecutionPlan(
            writes_database=can_execute,
            requires_confirmation=True,
            will_create_batch=can_execute,
            will_normalize_batch=can_execute,
            will_rebuild_pipeline=can_execute,
            affected_tables=affected if can_execute else [],
            trace_url_template="/api/v1/import/batches/{batch_id}/trace.json" if can_execute else None,
            note=(
                "Execute schreibt erst nach bestaetigter Preview: Raw-Batch anlegen, "
                "Batch normalisieren, Pipeline rebuild ausfuehren und danach Trace-JSON "
                "fuer den konkreten Batch bereitstellen."
                if can_execute
                else (
                    "Preview schreibt keine Daten. Execute bleibt blockiert, bis "
                    "Pflichtfelder, Dubletten und Importfaehigkeit geklaert sind."
                )
            ),
        )
