from fastapi.testclient import TestClient
import pytest

from steuerreport_v2.api.app import create_app
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.import_coverage import ImportCoverageService
from steuerreport_v2.domain.import_policy import ImportPolicyService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.paths import USERTRANSFER_ROOT


def test_import_coverage_detects_pionex_and_binance_files(tmp_path):
    root = tmp_path / "incoming"
    pionex_dir = root / "pionex"
    binance_dir = root / "Binance"
    pionex_dir.mkdir(parents=True)
    binance_dir.mkdir()
    (pionex_dir / "trading.csv").write_text(
        '"date(UTC+0)","executed_qty","amount","side","symbol"\n'
        '"2021-12-25 16:25:25","2.7","105","BUY","HNT_USDT"\n',
        encoding="utf-8",
    )
    (binance_dir / "trades.csv").write_text(
        "Date(UTC),Market,Type,Amount,Total\n"
        "2021-05-15 23:59:49,ETHEUR,BUY,0.01374,41.220\n",
        encoding="utf-8",
    )

    summary = ImportCoverageService(DuckDbStore(tmp_path / "db.duckdb")).scan(str(root))

    assert summary.files_scanned == 2
    assert summary.files_total == 2
    assert summary.scan_truncated is False
    assert summary.importable == 2
    assert {row.source for row in summary.rows} == {"pionex", "binance"}


def test_import_coverage_endpoint(tmp_path):
    root = tmp_path / "incoming"
    root.mkdir()
    (root / "broken.csv").write_text("note\nx\n", encoding="utf-8")
    client = TestClient(create_app(DuckDbStore(tmp_path / "db.duckdb")))

    response = client.get(f"/api/v1/import/coverage?root_path={root}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["files_scanned"] == 1
    assert data["files_total"] == 1
    assert data["blocked"] == 1
    assert data["rows"][0]["can_import"] is False


def test_import_coverage_respects_time_budget(tmp_path):
    root = tmp_path / "incoming"
    root.mkdir()
    for index in range(5):
        (root / f"file-{index}.csv").write_text(
            "time,asset,amount,type\n2021-01-01T00:00:00Z,BTC,1,deposit\n",
            encoding="utf-8",
        )

    summary = ImportCoverageService(DuckDbStore(tmp_path / "db.duckdb")).scan(
        str(root),
        limit=5,
        max_seconds=0,
    )

    assert summary.files_total == 5
    assert summary.files_scanned == 1
    assert summary.scan_truncated is True


@pytest.mark.skipif(
    not USERTRANSFER_ROOT.is_dir(),
    reason="requires the private local usertransfer evidence tree",
)
def test_import_policy_classifies_known_usertransfer_tree():
    summary = ImportPolicyService().audit(str(USERTRANSFER_ROOT))

    assert summary.files_total >= 150
    assert summary.unclassified == 0
    assert summary.curated_primary == 12
    assert summary.staging_required == 2
    assert summary.parser_needed >= 4
    assert summary.reference_only >= 140


def test_import_policy_endpoint(tmp_path):
    root = tmp_path / "incoming"
    active = root / "Binance" / "export 2021"
    active.mkdir(parents=True)
    (active / "Binance-Deposit-History-202605061836(UTC+2)_db80f010.xlsx").write_text(
        "placeholder",
        encoding="utf-8",
    )
    (root / "wiso").mkdir()
    (root / "wiso" / "WISO Steuer CSV 2021 - ref.csv").write_text("placeholder", encoding="utf-8")
    client = TestClient(create_app(DuckDbStore(tmp_path / "db.duckdb")))

    response = client.get(f"/api/v1/import/policy/audit?root_path={root}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["files_total"] == 2
    assert data["unclassified"] == 0
    assert data["curated_primary"] == 1
    assert data["reference_only"] == 1


def test_import_policy_classifies_moonpay_trade_history_as_evidence(tmp_path):
    root = tmp_path / "incoming"
    root.mkdir()
    trade_history = root / "MoonPay_trade-history.csv"
    trade_history.write_text("Transaction ID,Status\ntrade-1,Completed\n", encoding="utf-8")

    summary = ImportPolicyService().audit(str(root))

    assert summary.unclassified == 0
    assert summary.reference_only == 1
    assert summary.decisions[0].action == "evidence_only"
    assert summary.decisions[0].can_be_realimport is False


def test_import_policy_classifies_sparkasse_camt_aggregate_as_evidence(tmp_path):
    root = tmp_path / "incoming"
    bank_dir = root / "Sparkasse"
    bank_dir.mkdir(parents=True)
    bank_export = bank_dir / "20260821-account-umsatz-camt52v8.CSV"
    bank_export.write_text("Auftragskonto;Betrag\nredacted;-250,00\n", encoding="utf-8")

    summary = ImportPolicyService().audit(str(root))

    assert summary.unclassified == 0
    assert summary.reference_only == 1
    assert summary.decisions[0].action == "evidence_only"
    assert summary.decisions[0].can_be_realimport is False


def test_import_policy_marks_files_already_loaded(tmp_path):
    root = tmp_path / "incoming"
    active = root / "Binance" / "export 2021"
    active.mkdir(parents=True)
    filename = "Binance-Deposit-History-202605061836(UTC+2)_db80f010.xlsx"
    (active / filename).write_text("placeholder", encoding="utf-8")
    store = DuckDbStore(tmp_path / "db.duckdb")
    CsvRawImporter(store).import_text(
        source="binance",
        filename=filename,
        content="time,asset,amount,type\n2021-01-01T00:00:00Z,BTC,1,deposit\n",
    )

    summary = ImportPolicyService(store).audit(str(root))

    assert summary.imported_files == 1
    assert summary.unused_curated_primary == 0
    assert summary.decisions[0].imported is True
    assert summary.decisions[0].imported_sources == ["binance"]
