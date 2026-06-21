from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.parser_preflight import ParserPreflightService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter


def test_parser_preflight_inspects_parser_needed_files_without_import(tmp_path):
    root = tmp_path / "usertransfer"
    jup_dir = root / "jup"
    jup_dir.mkdir(parents=True)
    (jup_dir / "G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY.csv").write_text(
        "timestamp,market,side,size,pnl\n"
        "2024-01-01T00:00:00Z,SOL-PERP,long,1,-12.5\n",
        encoding="utf-8",
    )
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    report = ParserPreflightService(CsvRawImporter(store)).inspect(
        root_path=str(root),
        limit=10,
    )

    assert report.parser_needed == 1
    assert report.inspected == 1
    item = report.files[0]
    assert item.parser_kind == "jup_perps"
    assert item.can_realimport is False
    assert item.row_count == 1
    assert item.columns == ["timestamp", "market", "side", "size", "pnl"]
    assert item.sample_rows[0]["market"] == "SOL-PERP"
    assert item.warnings == []


def test_parser_preflight_api_is_registered_and_returns_report(tmp_path):
    root = tmp_path / "usertransfer"
    wallet_file = root / "Wallet.G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY-month.csv"
    wallet_file.parent.mkdir(parents=True)
    wallet_file.write_text(
        "Date,Asset,Amount\n2024-01-01,SOL,1\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb")))

    response = client.get(
        "/api/v1/import/parser-preflight",
        params={"root_path": str(root)},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["parser_needed"] == 1
    assert data["files"][0]["parser_kind"] == "wallet_month"


def test_parser_preflight_wallet_month_recognizes_helium_columns_but_keeps_realimport_blocked(tmp_path):
    root = tmp_path / "usertransfer"
    wallet_file = root / "Wallet.G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY-month.csv"
    wallet_file.parent.mkdir(parents=True)
    wallet_file.write_text(
        "Gateway Address,Name,Tag,Period Start (UTC),IOT Tokens,IOT Token,MOBILE Tokens,MOBILE Token\n"
        "gateway-1,Hotspot,My Hotspots,01.04.23,42.5,IOT,,\n",
        encoding="utf-8",
    )
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    report = ParserPreflightService(CsvRawImporter(store)).inspect(
        root_path=str(root),
        limit=10,
    )

    item = report.files[0]
    assert item.parser_kind == "wallet_month"
    assert item.row_count == 1
    assert item.columns[:4] == ["Gateway Address", "Name", "Tag", "Period Start (UTC)"]
    assert item.can_realimport is False
    assert item.warnings == []


def test_parser_preflight_redacts_metadata_sample_rows(tmp_path):
    root = tmp_path / "usertransfer"
    c2c_file = root / "Binance/export 2021/Binance-C2C-Order-History-test.xlsx"
    c2c_file.parent.mkdir(parents=True)
    import pandas as pd

    frame = pd.DataFrame(
        [
            ["A", "B", "C", "D", "E", "F"],
            ["Name", "Person Eins", "Email", "person@example.test", "Address", "Street 1"],
            ["User ID", "123456", None, None, None, None],
        ]
    )
    frame.to_excel(c2c_file, index=False, header=False)
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    report = ParserPreflightService(CsvRawImporter(store)).inspect(
        root_path=str(root),
        limit=10,
    )

    sample_text = str(report.files[0].sample_rows)
    assert "person@example.test" not in sample_text
    assert "Person Eins" not in sample_text
    assert "123456" not in sample_text
    assert "Street 1" not in sample_text
    assert "[redacted]" in sample_text
