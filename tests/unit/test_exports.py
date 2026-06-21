from datetime import datetime, timezone
from decimal import Decimal

from steuerreport_v2.contracts.admin import AdminSettingWrite
from steuerreport_v2.contracts.exports import PdfExportRequest
from steuerreport_v2.contracts.parity import V1ReferenceMetricCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.exports import ExportService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


def _clean_store(tmp_path):
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


def test_pdf_export_splits_at_100_pages(tmp_path):
    store = _clean_store(tmp_path)

    result = ExportService(store).create_pdf_packages(
        PdfExportRequest(label="test", estimated_pages=230)
    )

    assert result.blocked is False
    assert [package.page_count for package in result.packages] == [100, 100, 30]
    assert all(package.page_count <= 100 for package in result.packages)
    assert [package.file_index for package in result.packages] == [1, 2, 3]


def test_pdf_export_blocks_when_review_gate_blocks(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="pionex.csv",
        content="time,coin,change,type\n2021-04-28T10:00:00Z,BTC,1,deposit\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()

    result = ExportService(store).create_pdf_packages(
        PdfExportRequest(label="blocked", estimated_pages=1)
    )

    assert result.blocked is True
    assert result.packages[0].status == "blocked"
    assert result.packages[0].page_count == 0


def test_export_packages_are_listed(tmp_path):
    store = _clean_store(tmp_path)
    service = ExportService(store)
    service.create_pdf_packages(PdfExportRequest(label="test", estimated_pages=101))

    packages = service.list_packages()

    assert len(packages) == 2
    assert {package.label for package in packages} == {"test"}


def test_export_package_pdf_can_be_rendered(tmp_path):
    store = _clean_store(tmp_path)
    service = ExportService(store)
    result = service.create_pdf_packages(PdfExportRequest(label="test", estimated_pages=1))

    rendered = service.render_pdf_package(result.packages[0].package_id)

    assert rendered is not None
    package, content = rendered
    assert package.package_id == result.packages[0].package_id
    assert content.startswith(b"%PDF-1.4")
    assert b"Steuerreport V2 Exportpaket" in content
    assert b"Export-Freigabe" in content
    assert b"Review aktuell offen: 0" in content
    assert b"Review historisch offen: 0" in content
    assert b"Review blockierend: 0" in content
    assert b"V1/V2 Parity releasebereit: ja" in content
    assert b"V1/V2 Parity blockierend: 0" in content
    assert b"FIFO Steuerzeilen: 0" in content
    assert b"Derivate Zeilen: 0" in content
    assert b"direkte ERiC-Uebertragung nein" in content


def test_export_package_can_be_deleted(tmp_path):
    store = _clean_store(tmp_path)
    service = ExportService(store)
    package = service.create_pdf_packages(
        PdfExportRequest(label="test", estimated_pages=1)
    ).packages[0]

    assert service.delete_package(package.package_id) is True
    assert service.delete_package("missing") is False
    assert service.get_package(package.package_id) is None


def test_blocked_export_package_is_not_rendered(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="pionex.csv",
        content="time,coin,change,type\n2021-04-28T10:00:00Z,BTC,1,deposit\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    service = ExportService(store)
    result = service.create_pdf_packages(PdfExportRequest(label="blocked", estimated_pages=1))

    assert service.render_pdf_package(result.packages[0].package_id) is None


def test_export_readiness_reports_gate_and_tax_state(tmp_path):
    store = _clean_store(tmp_path)

    readiness = ExportService(store).readiness()

    assert readiness.allow_export is True
    assert readiness.review_issues_open == 0
    assert readiness.parity_release_ready is True
    assert readiness.parity_blocking_groups == 0
    assert readiness.parity_blocking_difference_eur == "0"
    assert readiness.tax_lines_count == 0
    assert readiness.derivative_lines_count == 0
    assert readiness.derivative_realized_pnl_eur == "0"
    assert readiness.derivative_missing_price_count == 0
    assert readiness.unmatched_disposals == 0
    assert readiness.max_pdf_pages_per_file == 100


def test_export_readiness_separates_historical_review_issues(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.upsert_admin_setting(
        AdminSettingWrite(
            key="runtime.review.closed_tax_years",
            value_json="[2020, 2021, 2022]",
        )
    )
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="bnb.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2021-04-27T00:00:00Z,BNB,2.235,transfer,,\n"
            "2021-04-28T07:53:14Z,BNB,-2.47,sell,EUR,1136.09\n"
            "2021-04-29T00:00:00Z,BNB,0.235,transfer,,\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="BNB",
            price_eur=Decimal("460"),
            priced_at=datetime(2021, 4, 28, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    TaxService(store).rebuild_fifo()

    readiness = ExportService(store).readiness()

    assert readiness.allow_export is True
    assert readiness.review_issues_open == 0
    assert readiness.review_issues_current_open == 0
    assert readiness.review_issues_historical_open == 1
    assert readiness.review_issues_open_total == 1
    assert readiness.review_blocking_issues_open == 0
    assert readiness.unmatched_disposals == 1


def test_export_readiness_blocks_unresolved_v1_v2_parity_group(tmp_path):
    store = _clean_store(tmp_path)
    store.add_v1_reference_metric(
        V1ReferenceMetricCreate(
            scope="year:2021:asset:USDT",
            metric="gain_loss_eur",
            unit="EUR",
            value=Decimal("12.34"),
            year=2021,
            asset="USDT",
            source="test",
            note="parity must block export until reviewed",
        )
    )

    service = ExportService(store)
    readiness = service.readiness()
    result = service.create_pdf_packages(PdfExportRequest(label="blocked", estimated_pages=1))

    assert readiness.allow_export is False
    assert readiness.review_blocking_issues_open == 0
    assert readiness.parity_release_ready is False
    assert readiness.parity_unresolved_groups == 1
    assert readiness.parity_blocking_groups == 1
    assert result.blocked is True
    assert result.packages[0].block_reason == "parity_release_blocked"
