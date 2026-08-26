from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.blockpit_solana_preflight import BlockpitSolanaPreflightService
from steuerreport_v2.domain.external_price_backfill import ExternalPriceBackfillService


def test_blockpit_solana_preflight_returns_empty_report_for_missing_file(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    report = BlockpitSolanaPreflightService(store).inspect(
        file_path=str(tmp_path / "missing-blockpit.csv"),
    )

    assert report.filtered_rows == 0
    assert report.classes == []
    assert report.combined_readiness.required_opening_balance == {}
    assert report.target_changed is False


def test_blockpit_solana_preflight_reports_missing_prices_and_opening_balance(tmp_path):
    csv_path = tmp_path / "blockpit.csv"
    csv_path.write_text(
        "Date (UTC);Integration Name;Label;Outgoing Asset;Outgoing Amount;"
        "Incoming Asset;Incoming Amount;Fee Asset (optional);Fee Amount (optional)\n"
        "01.01.2024 00:00:00;Solana;Trade;USDC;100;JUP;10;SOL;0.01\n"
        "02.01.2024 00:00:00;Solana;Withdrawal;SOL;5;;;;\n",
        encoding="utf-8",
    )
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="binance",
            event_time=datetime(2023, 12, 31, 23, 30, tzinfo=timezone.utc),
            event_type="transfer",
            asset="SOL",
            quantity=Decimal("-5.01"),
            tx_id="sol-transfer-out",
            account="Spot",
        )
    )
    config = tmp_path / "prices.json"
    config.write_text(
        '{"assets":[{"symbol":"JUP","coingecko_id":"jupiter-exchange-solana","store_keys":["JUP"],"aliases":["JUP"]}]}',
        encoding="utf-8",
    )

    report = BlockpitSolanaPreflightService(store).inspect(
        file_path=str(csv_path),
        integration="Solana",
        max_year=2024,
        account="Solana",
        price_config_path=str(config),
    )

    assert report.target_changed is False
    assert report.filtered_rows == 2
    assert report.class_counts == {"trade_buy_from_stable": 1, "withdrawal_sol": 1}
    trade = {item.row_class: item for item in report.classes}["trade_buy_from_stable"]
    assert trade.status == "blocked"
    assert trade.missing_latest_price_assets == ["JUP"]
    assert report.price_source_status[0].asset == "JUP"
    assert report.price_source_status[0].configured is True
    assert report.price_source_status[0].provider_id == "jupiter-exchange-solana"
    assert len(report.historical_price_requirements) == 1
    assert report.historical_price_requirements[0].asset == "JUP"
    assert report.historical_price_requirements[0].price_date.isoformat() == "2024-01-01"
    assert report.historical_price_requirements[0].row_class == "trade_buy_from_stable"
    assert report.historical_price_requirements[0].status == "configured"
    assert trade.required_opening_balance == {
        "SOL": Decimal("0.01"),
        "USDC": Decimal("100"),
    }
    withdrawal = {item.row_class: item for item in report.classes}["withdrawal_sol"]
    assert withdrawal.required_opening_balance == {"SOL": Decimal("5")}
    assert report.combined_readiness.status == "blocked"
    assert report.combined_readiness.required_opening_balance == {
        "SOL": Decimal("5.01"),
        "USDC": Decimal("100"),
    }
    assert report.combined_readiness.gross_positive_movements == {
        "JUP": Decimal("10"),
    }
    assert report.combined_readiness.gross_negative_movements == {
        "SOL": Decimal("5.01"),
        "USDC": Decimal("100"),
    }
    assert [item.asset for item in report.combined_readiness.incidents] == ["SOL", "USDC"]
    sol_incident = {
        item.asset: item for item in report.combined_readiness.incidents
    }["SOL"]
    assert sol_incident.evidence_candidates[0].source == "binance"
    assert sol_incident.evidence_candidates[0].quantity == Decimal("-5.01")
    assert "Menge exakt gleich" in sol_incident.evidence_candidates[0].reasons


def test_blockpit_solana_preflight_accepts_existing_price_and_balance(tmp_path):
    csv_path = tmp_path / "blockpit.csv"
    csv_path.write_text(
        "Date (UTC);Integration Name;Label;Outgoing Asset;Outgoing Amount;"
        "Incoming Asset;Incoming Amount;Fee Asset (optional);Fee Amount (optional)\n"
        "01.01.2024 00:00:00;Solana;Deposit;;;JUP;10;;\n",
        encoding="utf-8",
    )
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_price_point(
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("1.20"),
            priced_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            source="test",
        )
    )

    report = BlockpitSolanaPreflightService(store).inspect(
        file_path=str(csv_path),
        integration="Solana",
        max_year=2024,
        account="Solana",
    )

    assert report.importable_classes == ["deposit_plain"]
    assert report.blocked_classes == []
    assert report.classes[0].status == "importable"
    assert report.combined_readiness.status == "importable"
    assert report.combined_readiness.required_opening_balance == {}
    assert report.historical_price_requirements == []


def test_blockpit_solana_preflight_marks_unconfigured_missing_price_source(tmp_path):
    csv_path = tmp_path / "blockpit.csv"
    csv_path.write_text(
        "Date (UTC);Integration Name;Label;Outgoing Asset;Outgoing Amount;"
        "Incoming Asset;Incoming Amount;Fee Asset (optional);Fee Amount (optional)\n"
        "01.01.2024 00:00:00;Solana;Deposit;;;MANEKI;10;;\n",
        encoding="utf-8",
    )
    config = tmp_path / "empty-prices.json"
    config.write_text('{"assets":[]}', encoding="utf-8")
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    report = BlockpitSolanaPreflightService(store).inspect(
        file_path=str(csv_path),
        integration="Solana",
        max_year=2024,
        account="Solana",
        price_config_path=str(config),
    )

    assert report.price_source_status[0].asset == "MANEKI"
    assert report.price_source_status[0].configured is False
    assert report.price_source_status[0].status == "not_configured"
    assert report.historical_price_requirements[0].asset == "MANEKI"
    assert report.historical_price_requirements[0].status == "not_configured"


def test_blockpit_solana_preflight_links_wallet_monthly_iot_evidence(tmp_path):
    csv_path = tmp_path / "blockpit.csv"
    csv_path.write_text(
        "Date (UTC);Integration Name;Label;Outgoing Asset;Outgoing Amount;"
        "Incoming Asset;Incoming Amount;Fee Asset (optional);Fee Amount (optional)\n"
        "23.02.2024 21:01:15;Solana;Withdrawal;IOT;50;;;;\n",
        encoding="utf-8",
    )
    wallet_monthly = tmp_path / "wallet-month.csv"
    wallet_monthly.write_text(
        "Gateway Address,Name,Tag,Period Start (UTC),IOT Tokens,IOT Token,"
        "MOBILE Tokens,MOBILE Token,IOT (Ours),IOT (Other Party),"
        "MOBILE (Ours),MOBILE (Other Party)\n"
        "gateway-1,Hotspot,My Hotspots,01.01.24,60,IOT,,,,,,\n",
        encoding="utf-8",
    )
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    report = BlockpitSolanaPreflightService(store).inspect(
        file_path=str(csv_path),
        integration="Solana",
        max_year=2024,
        account="Solana",
        wallet_monthly_file_path=str(wallet_monthly),
    )

    incident = report.combined_readiness.incidents[0]
    assert incident.asset == "IOT"
    assert incident.required_quantity == Decimal("50")
    assert incident.evidence_candidates[0].source == "wallet_monthly"
    assert incident.evidence_candidates[0].quantity == Decimal("60")
    assert "Monatssummen decken den erforderlichen Startbestand" in (
        incident.evidence_candidates[0].reasons
    )


def test_blockpit_solana_preflight_api_returns_report(tmp_path):
    csv_path = tmp_path / "blockpit.csv"
    csv_path.write_text(
        "Date (UTC);Integration Name;Label;Outgoing Asset;Outgoing Amount;"
        "Incoming Asset;Incoming Amount;Fee Asset (optional);Fee Amount (optional)\n"
        "01.01.2024 00:00:00;Solana;Withdrawal;USDT;7;;;;\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb")))

    response = client.get(
        "/api/v1/import/blockpit-solana/preflight",
        params={"file_path": str(csv_path), "integration": "Solana", "max_year": 2024},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["target_changed"] is False
    assert data["filtered_rows"] == 1
    assert data["classes"][0]["row_class"] == "withdrawal_stable"
    assert data["classes"][0]["required_opening_balance"] == {"USDT": "7"}
    assert data["combined_readiness"]["required_opening_balance"] == {"USDT": "7"}


def test_blockpit_solana_price_probe_checks_provider_without_persisting_prices(tmp_path, monkeypatch):
    csv_path = tmp_path / "blockpit.csv"
    csv_path.write_text(
        "Date (UTC);Integration Name;Label;Outgoing Asset;Outgoing Amount;"
        "Incoming Asset;Incoming Amount;Fee Asset (optional);Fee Amount (optional)\n"
        "01.01.2024 00:00:00;Solana;Deposit;;;JUP;10;;\n",
        encoding="utf-8",
    )
    config = tmp_path / "prices.json"
    config.write_text(
        '{"assets":[{"symbol":"JUP","coingecko_id":"jupiter-exchange-solana","store_keys":["JUP"],"aliases":["JUP"]}]}',
        encoding="utf-8",
    )
    v1_db = tmp_path / "v1.db"
    import sqlite3

    with sqlite3.connect(v1_db) as con:
        con.execute(
            """
            create table fx_cache (
                rate_date text,
                base_ccy text,
                quote_ccy text,
                rate text,
                source text,
                source_rate_date text,
                updated_at_utc text
            )
            """
        )
        con.execute(
            "insert into fx_cache values (?, ?, ?, ?, ?, ?, ?)",
            ("2024-01-01", "USD", "EUR", "0.90", "ecb", "2024-01-01", "now"),
        )

    def fake_fetch(self, *, client, coingecko_id, date_str, provider):
        assert coingecko_id == "jupiter-exchange-solana"
        assert date_str == "2024-01-01"
        return Decimal("2.5"), "test_provider"

    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_price_usd", fake_fetch)
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    result = BlockpitSolanaPreflightService(store).probe_historical_prices(
        file_path=str(csv_path),
        integration="Solana",
        max_year=2024,
        price_config_path=str(config),
        v1_fx_db_path=str(v1_db),
        max_requests=5,
    )

    assert result.target_changed is False
    assert result.requirements_count == 1
    assert result.attempted == 1
    assert result.available == 1
    assert result.failed == 0
    assert result.dry_run is True
    assert result.imported_prices == 0
    assert result.jobs[0].status == "available"
    assert result.jobs[0].price_eur == Decimal("2.250")
    assert store.list_price_points() == []


def test_blockpit_solana_price_probe_can_import_available_prices_when_enabled(tmp_path, monkeypatch):
    csv_path = tmp_path / "blockpit.csv"
    csv_path.write_text(
        "Date (UTC);Integration Name;Label;Outgoing Asset;Outgoing Amount;"
        "Incoming Asset;Incoming Amount;Fee Asset (optional);Fee Amount (optional)\n"
        "01.01.2024 00:00:00;Solana;Deposit;;;JUP;10;;\n",
        encoding="utf-8",
    )
    config = tmp_path / "prices.json"
    config.write_text(
        '{"assets":[{"symbol":"JUP","coingecko_id":"jupiter-exchange-solana","store_keys":["JUP"],"aliases":["JUP"]}]}',
        encoding="utf-8",
    )
    v1_db = tmp_path / "v1.db"
    import sqlite3

    with sqlite3.connect(v1_db) as con:
        con.execute(
            """
            create table fx_cache (
                rate_date text,
                base_ccy text,
                quote_ccy text,
                rate text,
                source text,
                source_rate_date text,
                updated_at_utc text
            )
            """
        )
        con.execute(
            "insert into fx_cache values (?, ?, ?, ?, ?, ?, ?)",
            ("2024-01-01", "USD", "EUR", "0.90", "ecb", "2024-01-01", "now"),
        )

    def fake_fetch(self, *, client, coingecko_id, date_str, provider):
        return Decimal("2.5"), "test_provider"

    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_price_usd", fake_fetch)
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    result = BlockpitSolanaPreflightService(store).probe_historical_prices(
        file_path=str(csv_path),
        integration="Solana",
        max_year=2024,
        price_config_path=str(config),
        v1_fx_db_path=str(v1_db),
        max_requests=5,
        dry_run=False,
    )

    assert result.dry_run is False
    assert result.target_changed is True
    assert result.imported_prices == 1
    assert result.pipeline is not None
    prices = store.list_price_points()
    assert len(prices) == 1
    assert prices[0].asset == "JUP"
    assert prices[0].price_eur == Decimal("2.250000000000000000")
