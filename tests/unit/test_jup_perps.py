from __future__ import annotations

import sqlite3
from decimal import Decimal

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.jup_perps import JupPerpsPreviewService


def _write_fx_db(path) -> None:
    with sqlite3.connect(path) as con:
        con.execute(
            "create table fx_cache (rate_date text, base_ccy text, quote_ccy text, rate text)"
        )
        con.execute(
            "insert into fx_cache values ('2024-12-06', 'USD', 'EUR', '0.92')"
        )


def test_jup_perps_preview_separates_realized_pnl_fees_and_collateral_flow(tmp_path):
    csv_path = tmp_path / "jup.csv"
    csv_path.write_text(
        "Created at, Transaction ID, Asset, Position, Position change, Order type, "
        "Deposit / Withdraw ($), Execution price ($), Trade size ($), Profit / Loss ($), "
        "Trade fee ($), Liquidation fee ($), Mint, Collateral, Collateral mint\n"
        "Fri Dec 06 2024 16:27:25 GMT+0000 (Coordinated Universal Time),tx-1,"
        "BTC,Long,Decrease,Market,84.28,98929.26,5646.52,-26.21,4.29,,BTC,BTC,BTC\n"
        "Fri Dec 06 2024 14:55:29 GMT+0000 (Coordinated Universal Time),tx-2,"
        "BTC,Long,Increase,Market,-118.74,99390.72,5646.52,,3.95,,BTC,BTC,BTC\n",
        encoding="utf-8",
    )
    fx_path = tmp_path / "fx.sqlite"
    _write_fx_db(fx_path)

    preview = JupPerpsPreviewService().preview(
        file_path=str(csv_path),
        v1_fx_db_path=str(fx_path),
    )

    assert preview.row_count == 2
    assert preview.assets == ["BTC"]
    assert preview.increases == 1
    assert preview.decreases == 1
    assert preview.collateral_flow_usd == Decimal("-34.46")
    assert preview.realized_pnl_usd == Decimal("-26.21")
    assert preview.trade_fee_usd == Decimal("8.24")
    assert preview.liquidation_fee_usd == Decimal("0")
    assert preview.net_result_usd == Decimal("-34.45")
    assert preview.net_result_eur == Decimal("-31.6940")
    assert preview.missing_fx_count == 0
    assert preview.asset_summaries[0].net_result_usd == Decimal("-34.45")


def test_jup_perps_preview_api(tmp_path):
    csv_path = tmp_path / "jup.csv"
    csv_path.write_text(
        "Created at, Transaction ID, Asset, Position, Position change, Order type, "
        "Deposit / Withdraw ($), Execution price ($), Trade size ($), Profit / Loss ($), "
        "Trade fee ($), Liquidation fee ($), Mint, Collateral, Collateral mint\n"
        "Fri Dec 06 2024 16:27:25 GMT+0000 (Coordinated Universal Time),tx-1,"
        "SOL,Short,Decrease,Market,333.28,235.30,22223.37,-103.90,15.63,,SOL,USDC,USDC\n",
        encoding="utf-8",
    )
    fx_path = tmp_path / "fx.sqlite"
    _write_fx_db(fx_path)
    client = TestClient(create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb")))

    response = client.get(
        "/api/v1/import/jup-perps/preview",
        params={"file_path": str(csv_path), "v1_fx_db_path": str(fx_path)},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["row_count"] == 1
    assert data["assets"] == ["SOL"]
    assert data["net_result_usd"] == "-119.53"
