import json
from hashlib import sha256
from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile

from steuerreport_v2.contracts.exports import PdfExportRequest
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.contracts.review import ReviewDecisionCreate
from steuerreport_v2.contracts.valuation import PriceCoverageReport
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.exports import ExportService
from steuerreport_v2.domain.reports import ReportCenterService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


def _store_with_priced_deposit(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="pionex.csv",
        content="time,coin,change,type\n2021-04-28T10:00:00Z,USDT,10,deposit\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.90"),
            priced_at=datetime(2021, 4, 28, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    return store


def _call_get_route(app, path: str):
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == path
        and "GET" in getattr(route, "methods", set())
    )
    return route.endpoint()


def test_report_center_collects_existing_export_surfaces(tmp_path):
    store = _store_with_priced_deposit(tmp_path)

    center = ReportCenterService(store).center()

    assert center.export_allowed is True
    assert center.export_status == "freigegeben"
    assert center.max_pdf_pages_per_file == 100
    assert {action.action_id for action in center.actions} >= {
        "create-pdf",
        "create-audit-json",
        "create-elster-prep",
    }
    assert {artifact.artifact_id for artifact in center.csv_exports} >= {
        "review-decisions",
        "price-gaps",
        "parity-diagnostics",
        "hnt-provenance-timeline",
        "hnt-provenance-events",
        "hnt-fairspot-timeline",
        "hnt-fairspot-events",
        "tax-lines",
        "tax-income-guide",
        "tax-external-inflows",
    }
    assert any(artifact.artifact_id == "tax-payment-overview" for artifact in center.artifacts)
    evidence = next(artifact for artifact in center.artifacts if artifact.artifact_id == "evidence-package")
    assert evidence.status == "available"
    assert evidence.endpoint == "/api/v1/export/evidence-package.zip"
    fairspot_timeline = next(
        artifact
        for artifact in center.csv_exports
        if artifact.artifact_id == "hnt-fairspot-timeline"
    )
    assert "account=13xfSeV2UcVgUiTKmd9V1Htunc6N7wsAgkGRHtquN9hpCbA78Yp" in str(fairspot_timeline.endpoint)
    assert center.years
    year_2021 = next(year for year in center.years if year.year == 2021)
    assert year_2021.filing_endpoint == "/api/v1/tax-years/2021/filing-summary"
    assert year_2021.evidence_endpoint == "/api/v1/tax-years/2021/evidence"
    assert year_2021.evidence_package_endpoint == "/api/v1/export/tax-years/2021/evidence-package.zip"
    assert year_2021.wallet_fifo_endpoint == "/api/v1/tax-years/2021/wallet-fifo-delta"
    assert year_2021.wallet_fifo_gaps_endpoint == "/api/v1/tax-years/2021/wallet-fifo-gaps?limit=80"
    assert year_2021.filing_status == "empty"
    assert year_2021.filing_status_label == "Keine V2-Eingabewerte"
    assert "/api/v1/export/tax-payment-overview.json" in year_2021.required_evidence_refs
    assert "/api/v1/export/evidence-package.zip" in year_2021.required_evidence_refs
    assert year_2021.required_evidence_count == len(year_2021.required_evidence_refs)
    assert year_2021.expected_package_files_count >= 5
    assert "2021:" in year_2021.filing_summary


def test_report_center_year_cards_surface_cex_fifo_anchor_decisions(tmp_path):
    store = _store_with_priced_deposit(tmp_path)
    store.add_review_decision(
        ReviewDecisionCreate(
            decision_type="cex_exchange_outflow",
            scope="cex_exchange_outflow:year:2025:source:bitget:target:binance:network:SOL:deposit_tx:tx-1",
            title="CEX-zu-CEX-Transfer steuerneutral dokumentiert",
            rationale="Bitget Withdrawal und Binance Deposit sind gematcht.",
            evidence_ref="/api/v1/tax-years/2025/cex-exchange-outflow-evidence?source_exchange=bitget&target_cex=binance&network=SOL",
            actor="codex",
            source="unit-test",
            payload={
                "decision_status": "transfer_neutral_fifo_carry_forward_reviewed",
                "year": 2025,
                "source_exchange": "bitget",
                "target_cex": "binance",
                "network": "SOL",
                "deposit_txid": "tx-1",
                "asset": "SOL",
            },
        )
    )

    center = ReportCenterService(store).center()
    year_2025 = next(year for year in center.years if year.year == 2025)

    assert year_2025.cex_fifo_anchor_status == "documented"
    assert year_2025.cex_fifo_anchor_decisions_count == 1
    assert year_2025.cex_fifo_anchor_status_label == "1 CEX-FIFO-Anker dokumentiert"
    assert year_2025.cex_fifo_anchor_endpoint == (
        "/api/v1/tax-years/2025/cex-exchange-outflow-anchor-feasibility"
        "?source_exchange=bitget&target_cex=binance&network=SOL"
    )
    assert year_2025.cex_fifo_anchor_endpoint in year_2025.required_evidence_refs
    assert "CEX-FIFO-Anker" in year_2025.required_evidence_labels


def test_report_center_evidence_health_reports_missing_decision(tmp_path):
    store = _store_with_priced_deposit(tmp_path)

    center = ReportCenterService(store).center()

    assert center.evidence_health is not None
    assert center.evidence_health.status == "missing_decision"
    assert center.evidence_health.missing_decision_count == 1
    assert center.evidence_health.action_path == "/api/v1/review/evidence-traces"


def test_report_center_evidence_health_reports_complete_when_canonical(tmp_path):
    store = _store_with_priced_deposit(tmp_path)
    store.add_review_decision(
        ReviewDecisionCreate(
            decision_type="evidence_acceptance",
            scope="solscan_iot:blockpit_missing_signatures",
            title="canonical",
            rationale="canonical evidence",
            evidence_ref="/api/v1/import/solscan/evidence-trace",
            payload={"import_effect": "none"},
        )
    )

    center = ReportCenterService(store).center()

    assert center.evidence_health is not None
    assert center.evidence_health.status == "complete"
    assert center.evidence_health.canonical_count == 1
    assert center.evidence_health.legacy_ref_count == 0


def test_export_readiness_reuses_supplied_price_coverage(tmp_path, monkeypatch):
    import steuerreport_v2.domain.review as review_module

    class FailingPriceCoverageService:
        def __init__(self, store):
            self.store = store

        def report(self):
            raise AssertionError("price coverage should be supplied by caller")

    store = _store_with_priced_deposit(tmp_path)
    coverage = PriceCoverageReport(
        missing_count=0,
        missing_assets=[],
        missing=[],
    )
    monkeypatch.setattr(review_module, "PriceCoverageService", FailingPriceCoverageService)

    readiness = ExportService(store).readiness(price_coverage=coverage)

    assert readiness.allow_export is True
    assert readiness.review_issues_open == 0


def test_evidence_manifest_collects_required_finanzamt_files(tmp_path):
    store = _store_with_priced_deposit(tmp_path)

    manifest = ReportCenterService(store).evidence_manifest()
    files_by_id = {file.file_id: file for file in manifest.files}

    assert {
        "audit-json",
        "review-decisions",
        "parity-diagnostics",
        "hnt-fairspot-timeline",
        "hnt-fairspot-events",
        "solscan-evidence-trace",
        "helium-solana-reward-rpc-evidence",
        "tax-lines",
        "tax-payment-overview",
    } <= set(files_by_id)
    assert files_by_id["hnt-fairspot-timeline"].required is True
    assert files_by_id["hnt-fairspot-timeline"].group == "hnt"
    assert files_by_id["tax-lines"].group_label == "Steuerliche CSVs"
    assert files_by_id["tax-payment-overview"].required is True
    assert files_by_id["tax-payment-overview"].kind == "json"
    assert files_by_id["parity-diagnostics"].group == "prices_parity"
    assert files_by_id["solscan-evidence-trace"].required is True
    assert files_by_id["solscan-evidence-trace"].group == "solana_fifo"
    assert files_by_id["helium-solana-reward-rpc-evidence"].required is True
    assert files_by_id["helium-solana-reward-rpc-evidence"].group == "solana_fifo"
    assert files_by_id["elster-prep"].required is False
    assert files_by_id["elster-prep"].group == "structure"
    assert "keine Exporte" in manifest.methodology


def test_evidence_manifest_does_not_build_full_report_center(tmp_path, monkeypatch):
    store = _store_with_priced_deposit(tmp_path)

    def fail_center(self):
        raise AssertionError("manifest should use static export metadata")

    monkeypatch.setattr(ReportCenterService, "center", fail_center)

    manifest = ReportCenterService(store).evidence_manifest()

    assert {file.file_id for file in manifest.files} >= {
        "audit-json",
        "tax-lines",
        "tax-income-guide",
        "tax-external-inflows",
        "tax-solana-stablecoin-swap-evidence",
        "tax-solana-stablecoin-swap-fifo-lines",
        "tax-helium-swap-context",
        "tax-helium-swap-evidence-review",
        "tax-helium-swap-alchemy-audit",
        "solana-tx-alchemy-audit",
        "solana-failed-tx-tax-impact",
        "tax-payment-overview",
        "solscan-evidence-trace",
        "helium-solana-reward-rpc-evidence",
    }


def test_evidence_package_index_maps_manifest_files_to_zip_paths(tmp_path):
    store = _store_with_priced_deposit(tmp_path)

    package_index = ReportCenterService(store).evidence_package_index()
    paths_by_id = {file.file_id: file.path for file in package_index.files}

    assert package_index.label == "steuerreport-v2-evidence-package-index"
    assert package_index.files_count == 27
    assert paths_by_id["evidence-manifest"] == "00_Manifest/evidence-manifest.json"
    assert paths_by_id["token-risk-documentation"] == "03_Review_Entscheidungen/token-risk-documentation.csv"
    assert paths_by_id["tax-payment-overview"] == "02_Steuerliche_CSVs/tax-payment-overview.json"
    assert paths_by_id["tax-lines"] == "02_Steuerliche_CSVs/tax-lines.csv"
    assert paths_by_id["tax-income-guide"] == "02_Steuerliche_CSVs/tax-income-guide.csv"
    assert paths_by_id["tax-external-inflows"] == "02_Steuerliche_CSVs/tax-external-inflows.csv"
    assert paths_by_id["tax-solana-stablecoin-swap-evidence"] == "06_Solana_FIFO_Belege/tax-solana-stablecoin-swap-evidence.csv"
    assert paths_by_id["tax-solana-stablecoin-swap-fifo-lines"] == "06_Solana_FIFO_Belege/tax-solana-stablecoin-swap-fifo-lines.csv"
    assert paths_by_id["tax-helium-swap-context"] == "06_Solana_FIFO_Belege/tax-helium-swap-context.csv"
    assert paths_by_id["tax-helium-swap-evidence-review"] == "06_Solana_FIFO_Belege/tax-helium-swap-evidence-review.csv"
    assert paths_by_id["tax-helium-swap-alchemy-audit"] == "06_Solana_FIFO_Belege/tax-helium-swap-alchemy-audit.json"
    assert paths_by_id["solana-tx-alchemy-audit"] == "06_Solana_FIFO_Belege/solana-tx-alchemy-audit.json"
    assert paths_by_id["solana-failed-tx-tax-impact"] == "06_Solana_FIFO_Belege/solana-failed-tx-tax-impact.json"
    assert paths_by_id["hnt-fairspot-events"] == "05_HNT_Fairspot/hnt-fairspot-events.csv"
    assert paths_by_id["solscan-evidence-trace"] == "06_Solana_FIFO_Belege/solscan-evidence-trace.json"
    assert paths_by_id["helium-solana-reward-rpc-evidence"] == "06_Solana_FIFO_Belege/helium-solana-reward-rpc-evidence.json"
    assert any(group.folder == "05_HNT_Fairspot" and group.required_count == 2 for group in package_index.groups)
    assert any(group.folder == "06_Solana_FIFO_Belege" and group.required_count == 2 for group in package_index.groups)
    assert "schreibt aber keine Steuerdaten" in package_index.methodology


def test_evidence_manifest_and_index_include_cex_fifo_anchor_year_files(tmp_path):
    store = _store_with_priced_deposit(tmp_path)
    store.add_review_decision(
        ReviewDecisionCreate(
            decision_type="cex_exchange_outflow",
            scope="cex_exchange_outflow:year:2025:source:bitget:target:binance:network:SOL:deposit_tx:tx-1",
            title="CEX-zu-CEX-Transfer steuerneutral dokumentiert",
            rationale="Unit-Test CEX Anchor.",
            evidence_ref="/api/v1/tax-years/2025/cex-exchange-outflow-evidence?source_exchange=bitget&target_cex=binance&network=SOL",
            actor="codex",
            source="unit-test",
            payload={
                "decision_status": "transfer_neutral_fifo_carry_forward_reviewed",
                "year": 2025,
                "source_exchange": "bitget",
                "target_cex": "binance",
                "network": "SOL",
                "deposit_txid": "tx-1",
                "asset": "SOL",
            },
        )
    )

    manifest = ReportCenterService(store).evidence_manifest()
    package_index = ReportCenterService(store).evidence_package_index()
    files_by_id = {file.file_id: file for file in manifest.files}
    paths_by_id = {file.file_id: file.path for file in package_index.files}

    assert files_by_id["tax-year-2025-cex-exchange-outflow-evidence"].required is True
    assert files_by_id["tax-year-2025-cex-exchange-outflow-evidence"].group == "solana_fifo"
    assert files_by_id["tax-year-2025-cex-exchange-outflow-anchor-feasibility"].required is True
    assert files_by_id["tax-year-2025-cex-exchange-outflow-anchor-feasibility"].endpoint == (
        "/api/v1/tax-years/2025/cex-exchange-outflow-anchor-feasibility"
        "?source_exchange=bitget&target_cex=binance&network=SOL"
    )
    assert paths_by_id["tax-year-2025-cex-exchange-outflow-evidence"] == (
        "06_Solana_FIFO_Belege/tax-year-2025-cex-exchange-outflow-evidence.json"
    )
    assert paths_by_id["tax-year-2025-cex-exchange-outflow-anchor-feasibility"] == (
        "06_Solana_FIFO_Belege/tax-year-2025-cex-exchange-outflow-anchor-feasibility.json"
    )
    assert any(group.folder == "06_Solana_FIFO_Belege" and group.required_count == 4 for group in package_index.groups)


def test_report_center_shows_created_pdf_package(tmp_path):
    store = _store_with_priced_deposit(tmp_path)
    ExportService(store).create_pdf_packages(
        PdfExportRequest(label="test", estimated_pages=1)
    )

    center = ReportCenterService(store).center()
    pdf = next(artifact for artifact in center.artifacts if artifact.artifact_id == "pdf-package")

    assert center.packages_count == 1
    assert center.created_pdf_packages_count == 1
    assert pdf.status == "ready"
    assert pdf.package_id is not None


def test_report_center_blocks_pdf_when_export_gate_blocks(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="pionex.csv",
        content="time,coin,change,type\n2021-04-28T10:00:00Z,BTC,1,deposit\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()

    center = ReportCenterService(store).center()
    pdf_action = next(action for action in center.actions if action.action_id == "create-pdf")

    assert center.export_allowed is False
    assert pdf_action.enabled is False
    assert any(warning.code == "export_gate_blocked" for warning in center.quality_warnings)


def test_report_center_warns_about_quality_risks(tmp_path):
    store = _store_with_priced_deposit(tmp_path)
    store.add_price_point(
        PricePointCreate(
            asset="BTC",
            price_eur=Decimal("60000"),
            priced_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            source="proxy-derived-test",
            confidence=Decimal("0.80"),
        )
    )
    store.add_review_decision(
        ReviewDecisionCreate(
            decision_type="price_gap",
            scope="price_gap:test",
            title="Manuelle Entscheidung ohne Beleg",
            rationale="Nur fuer Report-Center-Test.",
        )
    )

    center = ReportCenterService(store).center()
    codes = {warning.code for warning in center.quality_warnings}

    assert "low_confidence_prices" in codes
    assert "proxy_prices" in codes
    assert "manual_decisions_without_evidence" in codes


def test_report_center_warns_about_external_solana_inflows(tmp_path):
    from steuerreport_v2.contracts.events import CanonicalEventCreate

    store = _store_with_priced_deposit(tmp_path)
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                event_type="income",
                asset="JUP",
                quantity=Decimal("10"),
                account="wallet-1",
                tx_id="airdrop-1",
            )
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("1"),
            priced_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    center = ReportCenterService(store).center()
    warning = next(
        item for item in center.quality_warnings
        if item.code == "external_solana_inflows_need_evidence"
    )

    assert warning.blocks_export is False
    assert warning.count == 1
    assert warning.action_path == "/api/v1/export/tax-external-inflows.csv"


def test_report_center_routes_are_registered():
    from steuerreport_v2.api.app import create_app

    app = create_app()

    assert any(
        getattr(route, "path", None) == "/api/v1/reports/center"
        for route in app.routes
    )
    assert any(
        getattr(route, "path", None) == "/api/v1/export/evidence-manifest.json"
        for route in app.routes
    )
    assert any(
        getattr(route, "path", None) == "/api/v1/export/evidence-package-index.json"
        for route in app.routes
    )
    assert any(
        getattr(route, "path", None) == "/api/v1/export/evidence-package.zip"
        for route in app.routes
    )
    assert any(
        getattr(route, "path", None) == "/api/v1/export/tax-years/{year}/evidence-package.zip"
        for route in app.routes
    )
    assert any(
        getattr(route, "path", None) == "/api/v1/export/tax-payment-overview.json"
        for route in app.routes
    )


def test_evidence_manifest_download_endpoint(tmp_path):
    from steuerreport_v2.api.app import create_app

    store = _store_with_priced_deposit(tmp_path)
    response = _call_get_route(create_app(store), "/api/v1/export/evidence-manifest.json")

    assert response.status_code == 200
    assert "filename=evidence-manifest.json" in response.headers["content-disposition"]
    payload = json.loads(response.body.decode("utf-8"))
    file_ids = {file["file_id"] for file in payload["files"]}
    assert "audit-json" in file_ids
    assert "tax-payment-overview" in file_ids
    assert "hnt-fairspot-events" in file_ids
    hnt_file = next(file for file in payload["files"] if file["file_id"] == "hnt-fairspot-events")
    assert hnt_file["group"] == "hnt"
    assert hnt_file["group_label"] == "HNT und Fairspot"


def test_evidence_package_index_download_endpoint(tmp_path):
    from steuerreport_v2.api.app import create_app

    store = _store_with_priced_deposit(tmp_path)
    response = _call_get_route(create_app(store), "/api/v1/export/evidence-package-index.json")

    assert response.status_code == 200
    assert "filename=evidence-package-index.json" in response.headers["content-disposition"]
    payload = json.loads(response.body.decode("utf-8"))
    assert payload["files_count"] == 27
    assert any(file["path"] == "03_Review_Entscheidungen/token-risk-documentation.csv" for file in payload["files"])
    assert any(file["path"] == "02_Steuerliche_CSVs/tax-payment-overview.json" for file in payload["files"])
    assert any(file["path"] == "05_HNT_Fairspot/hnt-fairspot-events.csv" for file in payload["files"])
    assert any(file["path"] == "06_Solana_FIFO_Belege/tax-solana-stablecoin-swap-evidence.csv" for file in payload["files"])
    assert any(file["path"] == "06_Solana_FIFO_Belege/tax-solana-stablecoin-swap-fifo-lines.csv" for file in payload["files"])
    assert any(file["path"] == "06_Solana_FIFO_Belege/tax-helium-swap-context.csv" for file in payload["files"])
    assert any(file["path"] == "06_Solana_FIFO_Belege/tax-helium-swap-evidence-review.csv" for file in payload["files"])
    assert any(file["path"] == "06_Solana_FIFO_Belege/tax-helium-swap-alchemy-audit.json" for file in payload["files"])
    assert any(file["path"] == "06_Solana_FIFO_Belege/solana-tx-alchemy-audit.json" for file in payload["files"])
    assert any(file["path"] == "06_Solana_FIFO_Belege/solana-failed-tx-tax-impact.json" for file in payload["files"])
    assert any(file["path"] == "06_Solana_FIFO_Belege/solscan-evidence-trace.json" for file in payload["files"])
    assert any(file["path"] == "06_Solana_FIFO_Belege/helium-solana-reward-rpc-evidence.json" for file in payload["files"])
    assert any(group["folder"] == "02_Steuerliche_CSVs" for group in payload["groups"])
    assert any(group["folder"] == "06_Solana_FIFO_Belege" for group in payload["groups"])


def test_tax_payment_overview_json_download_endpoint(tmp_path):
    from steuerreport_v2.api.app import create_app

    store = _store_with_priced_deposit(tmp_path)
    response = _call_get_route(create_app(store), "/api/v1/export/tax-payment-overview.json")

    assert response.status_code == 200
    assert "filename=tax-payment-overview.json" in response.headers["content-disposition"]
    payload = json.loads(response.body.decode("utf-8"))
    assert "ascii_table" in payload
    assert "rows" in payload
    assert any(row["checklist"] for row in payload["rows"])


def test_tax_income_and_external_inflow_csv_downloads(tmp_path):
    from steuerreport_v2.api.app import create_app
    from steuerreport_v2.contracts.events import CanonicalEventCreate

    store = _store_with_priced_deposit(tmp_path)
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                event_type="income",
                asset="JUP",
                quantity=Decimal("10"),
                account="wallet-1",
                tx_id="airdrop-1",
            )
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("1"),
            priced_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    app = create_app(store)

    income = _call_get_route(app, "/api/v1/export/tax-income-guide.csv")
    inflows = _call_get_route(app, "/api/v1/export/tax-external-inflows.csv")
    income_text = income.body.decode("utf-8")
    inflows_text = inflows.body.decode("utf-8")

    assert income.status_code == 200
    assert "filename=tax-income-guide.csv" in income.headers["content-disposition"]
    assert "Klassifizierung" in income_text
    assert "JUP" in income_text
    assert inflows.status_code == 200
    assert "filename=tax-external-inflows.csv" in inflows.headers["content-disposition"]
    assert "unmatched_external_inflow" in inflows_text


def test_tax_income_csv_export_can_filter_single_year(tmp_path):
    from steuerreport_v2.api.app import create_app
    from steuerreport_v2.contracts.events import CanonicalEventCreate

    store = _store_with_priced_deposit(tmp_path)
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                event_type="income",
                asset="JUP",
                quantity=Decimal("10"),
                account="wallet-1",
                tx_id="airdrop-1",
            )
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("1"),
            priced_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    route = next(
        route
        for route in create_app(store).routes
        if getattr(route, "path", None) == "/api/v1/export/tax-income-guide.csv"
        and "GET" in getattr(route, "methods", set())
    )

    response = route.endpoint(year=2024)
    text = response.body.decode("utf-8")

    assert response.status_code == 200
    assert "filename=tax-income-guide-2024.csv" in response.headers["content-disposition"]
    assert "2024,JUP" in text
    assert "2021,USDT" not in text


def test_evidence_package_download_endpoint_contains_required_files(tmp_path):
    from steuerreport_v2.api.app import create_app

    store = _store_with_priced_deposit(tmp_path)
    response = _call_get_route(create_app(store), "/api/v1/export/evidence-package.zip")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "filename=steuerreport-v2-evidence-" in response.headers["content-disposition"]
    with ZipFile(BytesIO(response.body)) as package:
        names = set(package.namelist())
        assert {
            "README.txt",
            "00_Manifest/evidence-manifest.json",
            "00_Manifest/package-index.json",
            "01_Struktur_Audit/audit.json",
            "01_Struktur_Audit/elster-prep.json",
            "02_Steuerliche_CSVs/tax-payment-overview.json",
            "02_Steuerliche_CSVs/binance-fiat-deposits.csv",
            "02_Steuerliche_CSVs/tax-lines.csv",
            "02_Steuerliche_CSVs/derivative-lines.csv",
            "02_Steuerliche_CSVs/tax-income-guide.csv",
            "02_Steuerliche_CSVs/tax-external-inflows.csv",
            "03_Review_Entscheidungen/review-decisions.csv",
            "03_Review_Entscheidungen/token-risk-documentation.csv",
            "04_Preise_Paritaet/parity-diagnostics.csv",
            "05_HNT_Fairspot/hnt-fairspot-timeline.csv",
            "05_HNT_Fairspot/hnt-fairspot-events.csv",
            "06_Solana_FIFO_Belege/tax-solana-stablecoin-swap-evidence.csv",
            "06_Solana_FIFO_Belege/tax-solana-stablecoin-swap-fifo-lines.csv",
            "06_Solana_FIFO_Belege/tax-helium-swap-context.csv",
            "06_Solana_FIFO_Belege/tax-helium-swap-evidence-review.csv",
            "06_Solana_FIFO_Belege/tax-helium-swap-alchemy-audit.json",
            "06_Solana_FIFO_Belege/solana-tx-alchemy-audit.json",
            "06_Solana_FIFO_Belege/solana-failed-tx-tax-impact.json",
            "06_Solana_FIFO_Belege/solscan-evidence-trace.json",
            "06_Solana_FIFO_Belege/helium-solana-reward-rpc-evidence.json",
        } <= names
        assert len(names) == 29
        package_index = json.loads(package.read("00_Manifest/package-index.json").decode("utf-8"))
        assert package_index["label"] == "steuerreport-v2-evidence-package-index"
        assert package_index["files_count"] == 27
        indexed_files = {file["path"]: file for file in package_index["files"]}
        indexed_paths = set(indexed_files)
        assert "02_Steuerliche_CSVs/tax-payment-overview.json" in indexed_paths
        assert "05_HNT_Fairspot/hnt-fairspot-events.csv" in indexed_paths
        assert "06_Solana_FIFO_Belege/tax-solana-stablecoin-swap-evidence.csv" in indexed_paths
        assert "06_Solana_FIFO_Belege/tax-solana-stablecoin-swap-fifo-lines.csv" in indexed_paths
        assert "06_Solana_FIFO_Belege/tax-helium-swap-context.csv" in indexed_paths
        assert "06_Solana_FIFO_Belege/tax-helium-swap-evidence-review.csv" in indexed_paths
        assert "06_Solana_FIFO_Belege/tax-helium-swap-alchemy-audit.json" in indexed_paths
        assert "06_Solana_FIFO_Belege/solana-tx-alchemy-audit.json" in indexed_paths
        assert "06_Solana_FIFO_Belege/solana-failed-tx-tax-impact.json" in indexed_paths
        assert "06_Solana_FIFO_Belege/solscan-evidence-trace.json" in indexed_paths
        assert "06_Solana_FIFO_Belege/helium-solana-reward-rpc-evidence.json" in indexed_paths
        payment_overview = json.loads(package.read("02_Steuerliche_CSVs/tax-payment-overview.json").decode("utf-8"))
        assert "ascii_table" in payment_overview
        assert payment_overview["rows"]
        hnt_events_content = package.read("05_HNT_Fairspot/hnt-fairspot-events.csv")
        assert indexed_files["05_HNT_Fairspot/hnt-fairspot-events.csv"]["size_bytes"] == len(hnt_events_content)
        assert indexed_files["05_HNT_Fairspot/hnt-fairspot-events.csv"]["sha256"] == sha256(hnt_events_content).hexdigest()
        assert len(indexed_files["05_HNT_Fairspot/hnt-fairspot-events.csv"]["sha256"]) == 64
        solscan_trace = json.loads(package.read("06_Solana_FIFO_Belege/solscan-evidence-trace.json").decode("utf-8"))
        assert solscan_trace["import_effect"] == "none"
        assert solscan_trace["target_changed"] is False
        reward_evidence = json.loads(package.read("06_Solana_FIFO_Belege/helium-solana-reward-rpc-evidence.json").decode("utf-8"))
        assert reward_evidence["import_effect"] == "none"
        assert reward_evidence["target_changed"] is False
        assert reward_evidence["summary"]["reward_totals"]["HNT"] == "3.48812900"
        assert any(group["folder"] == "05_HNT_Fairspot" for group in package_index["groups"])
        assert any(group["folder"] == "06_Solana_FIFO_Belege" for group in package_index["groups"])
        readme = package.read("README.txt").decode("utf-8")
        assert "schreibt keine Steuerdaten" in readme
        assert "05_HNT_Fairspot" in readme
        assert "06_Solana_FIFO_Belege" in readme


def test_tax_year_evidence_package_download_endpoint_contains_year_files(tmp_path):
    from steuerreport_v2.api.app import create_app

    store = _store_with_priced_deposit(tmp_path)
    app = create_app(store)
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/export/tax-years/{year}/evidence-package.zip"
    )
    response = route.endpoint(2021)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "filename=steuerreport-v2-tax-year-2021-evidence.zip" in response.headers["content-disposition"]
    with ZipFile(BytesIO(response.body)) as package:
        names = set(package.namelist())
        assert {
            "README.txt",
            "00_Manifest/year-evidence-manifest.json",
            "02_Steuerliche_CSVs/tax-year-2021-filing-summary.json",
            "02_Steuerliche_CSVs/tax-year-2021-filing-checklist.csv",
            "02_Steuerliche_CSVs/tax-year-2021-evidence.json",
            "02_Steuerliche_CSVs/tax-payment-overview.json",
            "03_Review_Entscheidungen/tax-year-2021-review-decisions.json",
            "06_Solana_FIFO_Belege/tax-year-2021-wallet-fifo-delta.json",
            "06_Solana_FIFO_Belege/tax-year-2021-wallet-fifo-gaps.json",
            "06_Solana_FIFO_Belege/tax-year-2021-wallet-fifo-withdrawal-gaps.json",
            "06_Solana_FIFO_Belege/tax-year-2021-cex-exchange-outflow-evidence.json",
            "06_Solana_FIFO_Belege/tax-year-2021-cex-exchange-outflow-anchor-feasibility.json",
        } <= names
        manifest = json.loads(package.read("00_Manifest/year-evidence-manifest.json").decode("utf-8"))
        assert manifest["year"] == 2021
        assert manifest["label"] == "steuerreport-v2-tax-year-2021-evidence-package"
        assert manifest["files"]
        manifest_paths = {file["path"] for file in manifest["files"]}
        assert "06_Solana_FIFO_Belege/tax-year-2021-wallet-fifo-delta.json" in manifest_paths
        assert "06_Solana_FIFO_Belege/tax-year-2021-wallet-fifo-gaps.json" in manifest_paths
        assert "06_Solana_FIFO_Belege/tax-year-2021-wallet-fifo-withdrawal-gaps.json" in manifest_paths
        assert "06_Solana_FIFO_Belege/tax-year-2021-cex-exchange-outflow-evidence.json" in manifest_paths
        assert "06_Solana_FIFO_Belege/tax-year-2021-cex-exchange-outflow-anchor-feasibility.json" in manifest_paths
        assert "03_Review_Entscheidungen/tax-year-2021-review-decisions.json" in manifest_paths
        assert "02_Steuerliche_CSVs/tax-year-2021-filing-checklist.csv" in manifest_paths
        wallet_fifo = json.loads(package.read("06_Solana_FIFO_Belege/tax-year-2021-wallet-fifo-delta.json").decode("utf-8"))
        assert wallet_fifo["method_version"] == "wallet_asset_preview_v14"
        filing_summary = json.loads(package.read("02_Steuerliche_CSVs/tax-year-2021-filing-summary.json").decode("utf-8"))
        filing_checklist = package.read("02_Steuerliche_CSVs/tax-year-2021-filing-checklist.csv").decode("utf-8")
        evidence = json.loads(package.read("02_Steuerliche_CSVs/tax-year-2021-evidence.json").decode("utf-8"))
        review_decisions = json.loads(package.read("03_Review_Entscheidungen/tax-year-2021-review-decisions.json").decode("utf-8"))
        cex_evidence = json.loads(package.read("06_Solana_FIFO_Belege/tax-year-2021-cex-exchange-outflow-evidence.json").decode("utf-8"))
        cex_anchor = json.loads(package.read("06_Solana_FIFO_Belege/tax-year-2021-cex-exchange-outflow-anchor-feasibility.json").decode("utf-8"))
        assert filing_summary["year"] == 2021
        assert "Category,Label,Amount_EUR,Action" in filing_checklist
        assert evidence["year"] == 2021
        assert review_decisions["year"] == 2021
        assert review_decisions["decisions_count"] == 0
        assert cex_evidence["year"] == 2021
        assert cex_anchor["year"] == 2021
        readme = package.read("README.txt").decode("utf-8")
        assert "schreibt keine Steuerdaten" in readme
        assert "Wallet-FIFO" in readme


def test_tax_year_evidence_package_uses_year_filtered_csv_names(tmp_path):
    from steuerreport_v2.api.app import create_app

    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="year-package-tax-lines.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2021-01-01T00:00:00Z,HNT,10,buy,EUR,100\n"
            "2021-06-01T00:00:00Z,HNT,-10,sell,EUR,40\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    from steuerreport_v2.domain.tax import TaxService

    TaxService(store).rebuild_fifo()
    app = create_app(store)
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/export/tax-years/{year}/evidence-package.zip"
    )
    response = route.endpoint(2021)

    with ZipFile(BytesIO(response.body)) as package:
        names = set(package.namelist())
        assert "02_Steuerliche_CSVs/tax-year-2021-tax-lines.csv" in names
        assert "02_Steuerliche_CSVs/tax-lines.csv" not in names
        manifest = json.loads(package.read("00_Manifest/year-evidence-manifest.json").decode("utf-8"))
        paths = {file["path"] for file in manifest["files"]}
        assert "02_Steuerliche_CSVs/tax-year-2021-tax-lines.csv" in paths


def test_tax_year_evidence_package_contains_filtered_review_decisions(tmp_path):
    from steuerreport_v2.api.app import create_app

    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_review_decision(
        ReviewDecisionCreate(
            decision_type="parity_finding",
            scope="parity:year:2021:asset:HNT:status:diff",
            title="HNT Jahresentscheidung",
            rationale="Belegentscheidung fuer 2021.",
            evidence_ref="/api/v1/export/review-decisions.csv",
            actor="codex",
            source="unit-test",
            payload={
                "decision_status": "accepted_difference",
                "import_effect": "none",
                "ledger_effect": "none",
                "fifo_effect": "none",
                "tax_line_effect": "none",
            },
        )
    )
    store.add_review_decision(
        ReviewDecisionCreate(
            decision_type="token_risk_documentation",
            scope="token_risk:spam_review:asset:CBDC:mint:fake",
            title="Globale Token-Entscheidung",
            rationale="Ohne Jahresbezug.",
            actor="codex",
            source="unit-test",
            payload={"asset": "CBDC"},
        )
    )
    app = create_app(store)
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/export/tax-years/{year}/evidence-package.zip"
    )

    response = route.endpoint(2021)

    with ZipFile(BytesIO(response.body)) as package:
        decisions = json.loads(
            package.read("03_Review_Entscheidungen/tax-year-2021-review-decisions.json").decode("utf-8")
        )
        manifest = json.loads(package.read("00_Manifest/year-evidence-manifest.json").decode("utf-8"))

    assert decisions["decisions_count"] == 1
    assert decisions["decisions"][0]["title"] == "HNT Jahresentscheidung"
    assert decisions["decisions"][0]["effect_summary"] == "Import: none | Ledger: none | FIFO: none | Tax-Lines: none"
    assert all(item["title"] != "Globale Token-Entscheidung" for item in decisions["decisions"])
    assert any(
        file["path"] == "03_Review_Entscheidungen/tax-year-2021-review-decisions.json"
        and file["source_endpoint"] == "/api/v1/export/review-decisions.csv"
        for file in manifest["files"]
    )
