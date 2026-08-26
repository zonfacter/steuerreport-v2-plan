from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.wallet_monthly_preflight import WalletMonthlyPreflightService


def test_wallet_monthly_preflight_returns_empty_report_for_missing_file(tmp_path):
    report = WalletMonthlyPreflightService().inspect(
        file_path=str(tmp_path / "missing-wallet-month.csv"),
    )

    assert report.rows == 0
    assert report.monthly_totals == []
    assert report.covers_required_quantity is False
    assert report.target_changed is False


def test_wallet_monthly_preflight_covers_required_iot_quantity(tmp_path):
    source = tmp_path / "wallet-month.csv"
    source.write_text(
        "Gateway Address,Name,Tag,Period Start (UTC),IOT Tokens,IOT Token,"
        "MOBILE Tokens,MOBILE Token,IOT (Ours),IOT (Other Party),"
        "MOBILE (Ours),MOBILE (Other Party)\n"
        "gateway-1,Hotspot,My Hotspots,01.01.24,200,IOT,,,,,,\n"
        "gateway-2,Hotspot,My Hotspots,01.02.24,150,IOT,,,,,,\n"
        "gateway-2,Hotspot,My Hotspots,01.03.24,25,IOT,,,,,,\n",
        encoding="utf-8",
    )

    report = WalletMonthlyPreflightService().inspect(
        file_path=str(source),
        wallet="wallet",
        asset="IOT",
        cutoff_at="2024-02-23T21:01:15",
        required_quantity=Decimal("339"),
    )

    assert report.rows == 3
    assert report.gateways == 2
    assert report.quantity_until_cutoff == Decimal("350")
    assert report.covers_required_quantity is True
    assert report.coverage_ratio > Decimal("1")
    assert [item.quantity for item in report.monthly_totals] == [
        Decimal("200"),
        Decimal("150"),
        Decimal("25"),
    ]


def test_wallet_monthly_preflight_api_returns_report(tmp_path):
    source = tmp_path / "wallet-month.csv"
    source.write_text(
        "Gateway Address,Name,Tag,Period Start (UTC),IOT Tokens,IOT Token,"
        "MOBILE Tokens,MOBILE Token,IOT (Ours),IOT (Other Party),"
        "MOBILE (Ours),MOBILE (Other Party)\n"
        "gateway-1,Hotspot,My Hotspots,01.01.24,10,IOT,,,,,,\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb")))

    response = client.get(
        "/api/v1/import/wallet-monthly/preflight",
        params={
            "file_path": str(source),
            "wallet": "wallet",
            "asset": "IOT",
            "cutoff_at": "2024-02-23T21:01:15",
            "required_quantity": "10",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["covers_required_quantity"] is True
    assert data["quantity_until_cutoff"] == "10"
