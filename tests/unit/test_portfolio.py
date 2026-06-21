from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.portfolio import PortfolioLiveBalanceSnapshot
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


def _build_balance(store: DuckDbStore) -> None:
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="pionex.csv",
        content=(
            "time,coin,change,type,account\n"
            "2021-04-28T10:00:00Z,USDT,100,deposit,pionex-main\n"
            "2021-04-29T10:00:00Z,BTC,0.5,deposit,pionex-main\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()


def test_portfolio_snapshot_uses_balance_times_latest_price(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _build_balance(store)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.90"),
            priced_at=datetime(2021, 4, 29, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="BTC",
            price_eur=Decimal("50000"),
            priced_at=datetime(2021, 4, 29, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    snapshot = PortfolioService(store).snapshot()

    assert snapshot.total_value_eur == Decimal("25090.000000000000000000000000000000000000")
    assert snapshot.missing_price_assets == []
    assert [(item.asset, item.value_eur) for item in snapshot.asset_summary] == [
        ("BTC", Decimal("25000.000000000000000000000000000000000000")),
        ("USDT", Decimal("90.000000000000000000000000000000000000")),
    ]
    assert snapshot.account_summary[0].account == "pionex-main"
    assert snapshot.account_summary[0].value_eur == snapshot.total_value_eur


def test_portfolio_token_risk_report_filters_spam_review_and_min_value(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="solana_rpc",
        filename="solana.csv",
        content=(
            "time,asset,amount,type,account\n"
            "2026-01-01T10:00:00Z,CBDC,5,deposit,wallet-main\n"
            "2026-01-01T10:00:00Z,JUP,2,deposit,wallet-main\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    for asset, price in [("CBDC", "2"), ("JUP", "3")]:
        store.add_price_point(
            PricePointCreate(
                asset=asset,
                price_eur=Decimal(price),
                priced_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                source="manual-test",
            )
        )
    now = datetime.now(timezone.utc)
    with store.connect() as con:
        con.execute(
            """
            insert into jupiter_token_metadata_cache (
                mint, symbol, name, decimals, icon, token_program, is_verified,
                organic_score, organic_score_label, holder_count, liquidity_usd,
                usd_price, market_cap_usd, risk_status, source,
                discovered_sources_json, refreshed_at, jupiter_updated_at
            ) values
                ('fakeMint1111111111111111111111111111111111', 'CBDC', 'Central Bank Digital Currency', 6, null, null, false,
                 1, 'low', 1, 0, 0, 0, 'spam_review', 'jupiter_tokens_v2', '["v1_solscan:wallet-main"]', ?, null),
                ('JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN', 'JUP', 'Jupiter', 6, null, null, true,
                 98, 'high', 100, 1000, 1, 1000, 'verified', 'jupiter_tokens_v2', '[]', ?, null)
            """,
            [now, now],
        )

    report = PortfolioService(store).token_risk_report(risk_status="spam_review", min_value_eur=Decimal("1"))

    assert report.rows_count == 1
    assert report.spam_review_count == 1
    assert report.verified_count == 1
    assert report.rows[0].asset == "CBDC"
    assert report.rows[0].token_risk_status == "spam_review"
    assert report.rows[0].value_eur == Decimal("10.000000000000000000000000000000000000")
    assert report.rows[0].discovered_sources == ["v1_solscan:wallet-main"]
    assert len(report.rows[0].positions) == 1
    assert report.rows[0].positions[0].account == "wallet-main"
    assert report.rows[0].positions[0].quantity == Decimal("5.000000000000000000")


def test_portfolio_token_risk_report_api_rejects_unknown_filter(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))

    response = client.get("/api/v1/portfolio/token-risk?risk_status=danger")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["errors"][0]["code"] == "portfolio_token_risk_failed"


def test_portfolio_valuation_audit_compares_latest_with_previous_price(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _build_balance(store)
    store.add_price_point(
        PricePointCreate(
            asset="BTC",
            price_eur=Decimal("40000"),
            priced_at=datetime(2021, 4, 28, tzinfo=timezone.utc),
            source="previous-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="BTC",
            price_eur=Decimal("50000"),
            priced_at=datetime(2021, 4, 29, tzinfo=timezone.utc),
            source="current-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.90"),
            priced_at=datetime(2021, 4, 29, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    report = PortfolioService(store).valuation_audit()
    btc = next(row for row in report.rows if row.asset == "BTC")

    assert report.total_value_eur == Decimal("25090.000000000000000000000000000000000000")
    assert btc.current_price_eur == Decimal("50000.000000000000000000")
    assert btc.previous_price_eur == Decimal("40000.000000000000000000")
    assert btc.previous_value_eur == Decimal("20000.000000000000000000000000000000000000")
    assert btc.value_delta_eur == Decimal("5000.000000000000000000000000000000000000")
    assert btc.price_delta_pct == Decimal("25.00")


def test_portfolio_snapshot_excludes_fairspot_transfer_counterparty(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="helium-fairspot-counterparty.csv",
        content=(
            "time,asset,amount,type,account\n"
            f"2021-07-08T18:30:00Z,HNT,99.75,deposit,{PortfolioService.FAIRSPOT_STAKING_WALLET}\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("2"),
            priced_at=datetime(2021, 7, 9, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    snapshot = PortfolioService(store).snapshot()

    assert snapshot.total_value_eur == Decimal("0")
    assert snapshot.positions == []
    assert snapshot.account_summary == []
    assert snapshot.excluded_account_summary == []


def test_portfolio_snapshot_excludes_helium_service_counterparty(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    service_wallet = "138bCXPVfSq7yyTfoDUrVwztPmUr4WGyA7TED9Y41djmF7rjA8y"
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="helium-service-counterparty.csv",
        content=(
            "time,asset,amount,type,account\n"
            f"2022-02-22T06:33:00Z,HNT,450,deposit,{service_wallet}\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("2"),
            priced_at=datetime(2022, 2, 23, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    snapshot = PortfolioService(store).snapshot()

    assert snapshot.total_value_eur == Decimal("0")
    assert snapshot.positions == []
    assert snapshot.account_summary == []


def test_portfolio_as_of_uses_ledger_cutoff_and_historical_price(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="as-of.csv",
        content=(
            "time,coin,change,type,account\n"
            "2021-12-31T10:00:00Z,USDT,100,deposit,pionex-main\n"
            "2021-12-31T12:00:00Z,BTC,0.1,deposit,pionex-main\n"
            "2022-01-01T00:00:01Z,BTC,0.2,deposit,pionex-main\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("1"),
            priced_at=datetime(2021, 12, 31, tzinfo=timezone.utc),
            source="manual-usdt",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="BTC",
            price_eur=Decimal("40000"),
            priced_at=datetime(2021, 12, 31, 23, 0, tzinfo=timezone.utc),
            source="manual-2021",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="BTC",
            price_eur=Decimal("50000"),
            priced_at=datetime(2022, 1, 1, tzinfo=timezone.utc),
            source="manual-2022",
        )
    )

    snapshot = PortfolioService(store).as_of_snapshot("2021-12-31")

    assert snapshot.as_of == datetime(2021, 12, 31, 23, 59, 59, 999999, tzinfo=timezone.utc)
    assert snapshot.total_value_eur == Decimal("4100.000000000000000000000000000000000000")
    assert snapshot.missing_price_assets == []
    assert snapshot.transfer_context_note is not None
    assert "Transfer-/Bridge" in snapshot.transfer_context_note
    assert [(item.asset, item.quantity) for item in snapshot.asset_summary] == [
        ("BTC", Decimal("0.100000000000000000")),
        ("USDT", Decimal("100.000000000000000000")),
    ]
    btc_position = next(position for position in snapshot.positions if position.asset == "BTC")
    assert btc_position.price_eur == Decimal("40000.000000000000000000")
    assert btc_position.price_source == "manual-2021"


def test_portfolio_as_of_reports_missing_historical_prices(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _build_balance(store)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("1"),
            priced_at=datetime(2021, 4, 29, tzinfo=timezone.utc),
            source="manual-usdt",
        )
    )

    snapshot = PortfolioService(store).as_of_snapshot("2021-04-29")

    assert snapshot.total_value_eur == Decimal("100.000000000000000000")
    assert snapshot.missing_price_assets == ["BTC"]


def test_portfolio_as_of_api(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _build_balance(store)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("1"),
            priced_at=datetime(2021, 4, 29, tzinfo=timezone.utc),
            source="manual-usdt",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="BTC",
            price_eur=Decimal("50000"),
            priced_at=datetime(2021, 4, 29, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    response = TestClient(create_app(store)).get("/api/v1/portfolio/as-of?as_of=2021-04-29")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["as_of"] == "2021-04-29T23:59:59.999999Z"
    assert Decimal(data["total_value_eur"]) == Decimal("25100")
    assert data["missing_price_assets"] == []


def test_portfolio_snapshot_reports_missing_prices(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _build_balance(store)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.90"),
            priced_at=datetime(2021, 4, 29, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    snapshot = PortfolioService(store).snapshot()

    assert snapshot.total_value_eur == Decimal("90.000000000000000000000000000000000000")
    assert snapshot.missing_price_assets == ["BTC"]


def test_portfolio_snapshot_ignores_zero_quantity_positions_for_missing_prices(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="flat.csv",
        content=(
            "time,asset,amount,type,account\n"
            "2021-01-01T00:00:00Z,BTC,1,deposit,test\n"
            "2021-01-02T00:00:00Z,BTC,-1,withdrawal,test\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()

    snapshot = PortfolioService(store).snapshot()

    assert snapshot.positions == []
    assert snapshot.missing_price_assets == []


def test_portfolio_snapshot_values_eur_without_price_ledger(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="eur.csv",
        content="time,asset,amount,type,account\n2021-01-01T00:00:00Z,EUR,98.1,deposit,Spot\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()

    snapshot = PortfolioService(store).snapshot()

    assert snapshot.missing_price_assets == []
    assert snapshot.total_value_eur == Decimal("98.100000000000000000")


def test_portfolio_snapshot_always_values_eur_at_one_even_with_price_ledger(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="eur.csv",
        content="time,asset,amount,type,account\n2025-07-01T00:00:00Z,EUR,100,deposit,Spot\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="EUR",
            price_eur=Decimal("0.90"),
            priced_at=datetime(2025, 7, 1, tzinfo=timezone.utc),
            source="bad-derived-eur-test",
        )
    )

    snapshot = PortfolioService(store).snapshot()
    virtual = snapshot.separation_virtual_wallet

    assert snapshot.total_value_eur == Decimal("100.000000000000000000")
    assert snapshot.positions[0].price_source == "fiat:EUR"
    assert virtual is not None
    assert virtual.total_value_eur == Decimal("0")
    assert virtual.positions == []


def test_portfolio_snapshot_excludes_binance_source_account_from_current_total(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="mixed-binance.csv",
        content=(
            "time,asset,amount,type,account\n"
            "2025-01-01T00:00:00Z,EUR,9000,deposit,binance\n"
            "2025-01-01T00:00:00Z,EUR,7000,deposit,Spot\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()

    snapshot = PortfolioService(store).snapshot()

    assert snapshot.total_value_eur == Decimal("7000.000000000000000000")
    assert snapshot.excluded_value_eur == Decimal("9000.000000000000000000")
    assert snapshot.account_summary[0].account == "Spot"
    assert snapshot.excluded_account_summary[0].account == "binance"


def test_portfolio_snapshot_excludes_uppercase_binance_bridge_account(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="helium-binance-bridge.csv",
        content=(
            "time,asset,amount,type,account\n"
            "2021-07-27T20:00:00Z,HNT,124.54,transfer,Binance\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("1"),
            priced_at=datetime(2021, 7, 27, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    snapshot = PortfolioService(store).snapshot()
    overview = PortfolioService(store).source_overview()

    assert snapshot.total_value_eur == Decimal("0")
    assert snapshot.excluded_value_eur == Decimal("124.540000000000000000")
    assert snapshot.excluded_account_summary[0].account == "Binance"
    assert all(group.source_group != "Binance" for group in overview.groups)


def test_portfolio_snapshot_adds_virtual_separation_wallet_for_eur_token_buys_only(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="separation.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity,account\n"
            "2025-06-12T23:59:00Z,BTC,10,deposit,wallet-a\n"
            "2025-06-13T09:00:00Z,BTC,-2,transfer,,,wallet-a\n"
            "2025-06-13T09:01:00Z,BTC,2,transfer,,,wallet-b\n"
            "2025-07-01T00:00:00Z,BTC,3,deposit,,,wallet-b\n"
            "2025-07-01T01:00:00Z,BTC,0.5,buy,EUR,25000,wallet-b\n"
            "2025-07-01T02:00:00Z,USDT,100,buy,EUR,90,wallet-b\n"
            "2025-07-01T03:00:00Z,ETH,1,reward,,,wallet-b\n"
            "2025-07-01T04:00:00Z,SOL,2,staking,,,wallet-b\n"
            "2025-07-02T00:00:00Z,ETH,-2,withdrawal,,,wallet-b\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    TaxService(store).rebuild_fifo()
    store.add_price_point(
        PricePointCreate(
            asset="BTC",
            price_eur=Decimal("50000"),
            priced_at=datetime(2025, 7, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.90"),
            priced_at=datetime(2025, 7, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    snapshot = PortfolioService(store).snapshot()
    virtual = snapshot.separation_virtual_wallet

    assert virtual is not None
    assert virtual.cutoff_date == "2025-06-13"
    positions = {position.asset: position for position in virtual.positions}
    assert set(positions) == {"BTC", "USDT"}
    assert positions["BTC"].quantity == Decimal("0.500000000000000000")
    assert positions["USDT"].quantity == Decimal("100.000000000000000000")
    assert virtual.total_value_eur == Decimal("25090.000000000000000000000000000000000000")
    assert virtual.missing_price_assets == []
    assert "Staking, Rewards, Mining" in virtual.methodology


def test_portfolio_separation_report_exposes_trend_and_investment_locations(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="separation-report.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity,account\n"
            "2025-06-12T23:59:00Z,SOL,10,deposit,,,old-wallet\n"
            "2025-06-14T10:00:00Z,SOL,2,buy,EUR,40,new-wallet\n"
            "2025-06-15T10:00:00Z,SOL,3,buy,EUR,90,new-wallet\n"
            "2025-06-15T10:30:00Z,SOL,4,reward,,,new-wallet\n"
            "2025-06-15T11:00:00Z,EUR,100,deposit,,,bank\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    TaxService(store).rebuild_fifo()
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("20"),
            priced_at=datetime(2025, 6, 14, tzinfo=timezone.utc),
            source="manual-day-1",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("30"),
            priced_at=datetime(2025, 6, 15, tzinfo=timezone.utc),
            source="manual-day-2",
        )
    )

    report = PortfolioService(store).separation_report()

    assert report.virtual_wallet.total_value_eur == Decimal("150.000000000000000000")
    assert [(point.date, point.total_value_eur) for point in report.trend] == [
        ("2025-06-13", Decimal("0")),
        ("2025-06-14", Decimal("40.000000000000000000000000000000000000")),
        ("2025-06-15", Decimal("150.000000000000000000")),
    ]
    locations = {(item.account, item.asset): item for item in report.investment_locations}
    assert locations[("new-wallet", "SOL")].quantity == Decimal("5.000000000000000000")
    assert ("bank", "EUR") not in locations


def test_portfolio_separation_report_api(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="separation-report.csv",
        content="time,asset,amount,type,account\n2025-06-14T10:00:00Z,EUR,100,deposit,bank\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    from fastapi.testclient import TestClient
    from steuerreport_v2.api.app import create_app

    response = TestClient(create_app(store)).get("/api/v1/portfolio/separation-report")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["cutoff_date"] == "2025-06-13"
    assert data["virtual_wallet"]["positions"] == []
    assert data["virtual_wallet"]["total_value_eur"] == "0"
    assert data["trend"][-1]["total_value_eur"] == "0"
    assert data["investment_locations"] == []


def test_portfolio_fiat_deposit_report_lists_external_binance_deposits_only(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Fiat-Deposit-History.xlsx",
        )
    )
    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=(
                '{"Time":"25-10-12 08:13:53","Deposit Amount":"200.00 EUR",'
                '"Receive Amount":"196 EUR","Method":"Apple Pay",'
                '"Status":"Successful","Transaction ID":"tx-fiat-1"}'
            ),
        ),
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="binance",
            source_ref="tx-fiat-1",
            event_time=datetime(2025, 10, 12, 8, 13, 53, tzinfo=timezone.utc),
            event_type="transfer",
            asset="EUR",
            quantity=Decimal("196"),
            tx_id="tx-fiat-1",
            account="binance",
            raw_object_id=raw.raw_object_id,
        )
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="binance",
            event_time=datetime(2025, 10, 12, 8, 13, 54, tzinfo=timezone.utc),
            event_type="transfer",
            asset="EUR",
            quantity=Decimal("196"),
            account="Spot",
        )
    )

    report = PortfolioService(store).fiat_deposit_report()

    assert report.rows_count == 1
    assert report.total_deposit_amount_eur == Decimal("200.00")
    assert report.total_receive_amount_eur == Decimal("196.000000000000000000")
    assert report.total_fee_or_difference_eur == Decimal("4.000000000000000000")
    assert report.rows[0].transaction_id == "tx-fiat-1"
    assert report.rows[0].method == "Apple Pay"
    assert report.rows[0].source_file == "Binance-Fiat-Deposit-History.xlsx"


def test_portfolio_fiat_deposit_report_api(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    from fastapi.testclient import TestClient
    from steuerreport_v2.api.app import create_app

    response = TestClient(create_app(store)).get("/api/v1/portfolio/fiat-deposits/binance")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["cutoff_date"] == "2025-06-13"
    assert data["target_source"] == "binance"
    assert data["rows"] == []


def test_portfolio_fiat_deposit_csv_export(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(source="binance", filename="Binance-Fiat-Deposit-History.xlsx")
    )
    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=7,
            payload_json=(
                '{"Deposit Amount":"500.00 EUR","Method":"SEPA",'
                '"Status":"Successful","Transaction ID":"tx-fiat-2"}'
            ),
        ),
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="binance",
            source_ref="tx-fiat-2",
            event_time=datetime(2026, 2, 2, 15, 26, 25, tzinfo=timezone.utc),
            event_type="transfer",
            asset="EUR",
            quantity=Decimal("500"),
            tx_id="tx-fiat-2",
            account="binance",
            raw_object_id=raw.raw_object_id,
        )
    )
    from fastapi.testclient import TestClient
    from steuerreport_v2.api.app import create_app

    response = TestClient(create_app(store)).get("/api/v1/export/binance-fiat-deposits.csv")

    assert response.status_code == 200
    assert "binance-fiat-deposits.csv" in response.headers["content-disposition"]
    assert "Zeit_UTC,Brutto_Zahlungsbeleg,Binance_Gutschrift_EUR" in response.text
    assert "2026-02-02T15:26:25+00:00,500.00 EUR,500.000000000000000000" in response.text
    assert "tx-fiat-2" in response.text


def test_portfolio_separation_report_lists_unrealized_lots_with_price_quality(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="separation-lots.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity,account\n"
            "2025-06-14T10:00:00Z,SOL,2,buy,EUR,100,spot\n"
            "2025-06-15T10:00:00Z,SOL,-0.5,sell,EUR,40,spot\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    TaxService(store).rebuild_fifo()
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("80"),
            priced_at=datetime(2025, 6, 20, tzinfo=timezone.utc),
            source="coingecko:coins-history",
        )
    )

    lots = PortfolioService(store).separation_unrealized_lots(
        valuation_at=datetime(2025, 6, 20, tzinfo=timezone.utc)
    )

    assert len(lots) == 1
    assert lots[0].asset == "SOL"
    assert lots[0].quantity_remaining == Decimal("1.500000000000000000")
    assert lots[0].cost_basis_eur == Decimal("75.000000000000000000000000000000000000")
    assert lots[0].current_value_eur == Decimal("120.000000000000000000")
    assert lots[0].unrealized_gain_loss_eur == Decimal(
        "45.000000000000000000000000000000000000"
    )
    assert lots[0].price_status == "ok"
    assert lots[0].price_source == "coingecko:coins-history"


def test_portfolio_snapshot_merges_unique_truncated_wallet_alias(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = "1362Z4gXFbBuUp22PtwNhdNc3iR6Tjc7ty5S8CPjSwVH6F7BsHV"
    short_wallet = "133iWieuw...xU6WUW8v"
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="wallets.csv",
        content=(
                "time,asset,amount,type,account\n"
                f"2024-01-01T00:00:00Z,BTC,10,deposit,{wallet}\n"
                f"2024-01-02T00:00:00Z,BTC,2,deposit,{short_wallet} \n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
                asset="BTC",
            price_eur=Decimal("7.5"),
            priced_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    snapshot = PortfolioService(store).snapshot()

    assert len(snapshot.positions) == 1
    assert snapshot.positions[0].account == wallet
    assert snapshot.positions[0].quantity == Decimal("12.000000000000000000")
    assert snapshot.total_value_eur == Decimal("90.000000000000000000000000000000000000")
    assert [alias.alias for alias in snapshot.resolved_account_aliases] == [short_wallet]
    assert snapshot.unresolved_truncated_accounts == []


def test_portfolio_snapshot_reports_unresolved_truncated_wallet_alias(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    short_wallet = "138bCXPVf...mF7rjA8y"
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="wallets.csv",
        content=(
                "time,asset,amount,type,account\n"
                f"2024-01-01T00:00:00Z,BTC,10,deposit,{short_wallet}\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()

    snapshot = PortfolioService(store).snapshot()

    assert snapshot.unresolved_truncated_accounts == [short_wallet]


def test_portfolio_snapshot_uses_full_wallet_from_raw_transfer_payload_for_alias(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = "138bCXPVfSq7yyTfoDUrVwztPmUr4WGyA7TED9Y41djmF7rjA8y"
    short_wallet = "138bCXPVf...mF7rjA8y"
    raw_batch = store.create_import_batch(
        ImportBatchCreate(source="binance", filename="withdrawals.csv")
    )
    store.add_raw_object(
        raw_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=(
                '{"Address":"'
                + wallet
                + '","Amount":"10","Coin":"BTC","TXID":"not-an-account"}'
            ),
        ),
    )
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="wallets.csv",
        content=(
            "time,asset,amount,type,account\n"
            f"2024-01-01T00:00:00Z,BTC,10,deposit,{short_wallet}\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()

    snapshot = PortfolioService(store).snapshot()

    assert snapshot.positions[0].account == wallet
    assert [alias.alias for alias in snapshot.resolved_account_aliases] == [short_wallet]
    assert snapshot.unresolved_truncated_accounts == []


def test_portfolio_reconciliation_flags_expected_zero_cex_and_missing_jup_wallet(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(PortfolioService, "_v1_cex_live_balance_snapshots", lambda _self, _connector_id, _fetched_at: [])
    monkeypatch.setattr(
        PortfolioService,
        "_v1_cex_live_balances",
        lambda _self, connector_id: {
            "bitget": {"USDT": Decimal("0.000000006884"), "BTC": Decimal("0.000000304")},
            "pionex": {"USDT": Decimal("0.8958683252194125"), "JUP": Decimal("0.093774016835")},
        }.get(connector_id, {}),
    )
    def solscan_balances(_self, wallet):
        if wallet == PortfolioService.KNOWN_JUP_WALLET:
            return {"SOL": Decimal("3.346886523"), "JUP": Decimal("4530.26599")}
        return {"SOL": Decimal("0.236270174"), "HNT": Decimal("71.687274")}

    monkeypatch.setattr(
        PortfolioService,
        "_solscan_wallet_balances",
        solscan_balances,
    )
    monkeypatch.setattr(PortfolioService, "_v1_solana_wallet_balances", lambda _self, _wallet: {})
    monkeypatch.setattr(
        PortfolioService,
        "_v1_solana_wallet_balances",
        lambda _self, _wallet: {"SOL": Decimal("3.346886523"), "JUP": Decimal("4530.26599")},
    )
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="reconciliation.csv",
        content=(
            "time,asset,amount,type,account\n"
            "2024-12-12T00:00:00Z,USDT,1000,deposit,bitget\n"
            "2024-11-22T00:00:00Z,USDT,100,deposit,pionex\n"
            "2024-12-31T00:00:00Z,SOL,2,deposit,G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.9"),
            priced_at=datetime(2024, 12, 31, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("100"),
            priced_at=datetime(2024, 12, 31, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    report = PortfolioService(store).reconciliation_report()

    blockers = {(row.source_group, row.asset): row for row in report.rows if row.severity == "blocker"}
    assert blockers[("Bitget", "USDT")].status == "mismatch_live_anchor"
    assert blockers[("Bitget", "USDT")].external_quantity == Decimal("0.000000006884")
    assert blockers[("Bitget", "USDT")].delta_value_eur == Decimal("-899.999999993804400000000000000000000000")
    assert blockers[("Pionex", "USDT")].status == "mismatch_live_anchor"
    assert blockers[("Jup Wallet GmHY...3yu", "JUP")].status == "missing_wallet_history_live_balance_found"
    assert blockers[("Jup Wallet GmHY...3yu", "SOL")].external_quantity == Decimal("3.346886523")
    assert report.expected_zero_ledger_value_eur == Decimal("990.000000000000000000000000000000000000")
    assert PortfolioService.KNOWN_JUP_WALLET in report.missing_wallets


def test_portfolio_reconciliation_api(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(PortfolioService, "V1_CONNECTOR_BASE_URL", "")

    response = TestClient(create_app(store)).get("/api/v1/portfolio/reconciliation")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["missing_wallets"] == [PortfolioService.KNOWN_JUP_WALLET]
    assert data["rows"][0]["status"] == "missing_live_wallet_import"


def test_portfolio_reconciliation_expected_zero_small_delta_is_warning(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(PortfolioService, "V1_CONNECTOR_BASE_URL", "")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="bitget-small-residual.csv",
        content="time,asset,amount,type,account\n2024-12-12T00:00:00Z,USDT,7.9,deposit,bitget\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.9"),
            priced_at=datetime(2024, 12, 31, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    report = PortfolioService(store).reconciliation_report()

    bitget = next(row for row in report.rows if row.source_group == "Bitget" and row.asset == "USDT")
    assert bitget.status == "mismatch_expected_live_zero"
    assert bitget.severity == "warning"


def test_portfolio_reconciliation_documents_bitget_usdt_live_zero_residual(
    tmp_path,
    monkeypatch,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(
        PortfolioService,
        "_v1_cex_live_balance_snapshots",
        lambda _self, _connector_id, _fetched_at: [],
    )
    monkeypatch.setattr(
        PortfolioService,
        "_v1_cex_live_balances",
        lambda _self, connector_id: (
            {"USDT": Decimal("0.000000006884")} if connector_id == "bitget" else {}
        ),
    )
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="bitget-usdt-live-zero-residual.csv",
        content=(
            "time,asset,amount,type,account\n"
            "2024-12-12T09:28:15Z,USDT,7.945994569,deposit,bitget\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.8587904019434827"),
            priced_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    report = PortfolioService(store).reconciliation_report()

    bitget = next(row for row in report.rows if row.source_group == "Bitget" and row.asset == "USDT")
    assert bitget.status == "complete_export_strategy_reference_live_zero"
    assert bitget.severity == "info"
    assert bitget.external_quantity == Decimal("0.000000006884")
    assert "2024-12-20 19:34:28 UTC+8" in bitget.next_action
    assert "347_BITGET_USDT_STRATEGY_RESIDUAL_WARNING" in bitget.evidence


def test_portfolio_reconciliation_expected_zero_reconciles_live_match_and_dust(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(PortfolioService, "_v1_cex_live_balance_snapshots", lambda _self, _connector_id, _fetched_at: [])
    monkeypatch.setattr(
        PortfolioService,
        "_v1_cex_live_balances",
        lambda _self, connector_id: {
            "bitget": {"BTC": Decimal("0.000000304"), "HNT": Decimal("0.00062275")},
        }.get(connector_id, {}),
    )
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="bitget-dust.csv",
        content=(
            "time,asset,amount,type,account\n"
            "2024-12-12T00:00:00Z,BTC,0.000000304,deposit,bitget\n"
            "2024-12-12T00:00:00Z,HNT,0.000991,deposit,bitget\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    priced_at = datetime(2024, 12, 31, tzinfo=timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="BTC",
            price_eur=Decimal("65000"),
            priced_at=priced_at,
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("0.62"),
            priced_at=priced_at,
            source="manual-test",
        )
    )

    report = PortfolioService(store).reconciliation_report()
    rows = {(row.source_group, row.asset): row for row in report.rows}

    assert rows[("Bitget", "BTC")].status == "live_anchor_reconciled"
    assert rows[("Bitget", "BTC")].severity == "info"
    assert rows[("Bitget", "HNT")].status == "live_anchor_reconciled"
    assert rows[("Bitget", "HNT")].severity == "info"


def test_portfolio_reconciliation_refresh_persists_live_snapshots(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(PortfolioService, "_v1_cex_live_balance_snapshots", lambda _self, _connector_id, _fetched_at: [])
    monkeypatch.setattr(
        PortfolioService,
        "_v1_cex_live_balances",
        lambda _self, connector_id: {
            "binance": {"EUR": Decimal("10")},
            "bitget": {"USDT": Decimal("0.000000006884")},
            "pionex": {"USDT": Decimal("0.8958683252194125")},
        }.get(connector_id, {}),
    )
    def solscan_balances(_self, wallet):
        if wallet == PortfolioService.KNOWN_JUP_WALLET:
            return {"SOL": Decimal("3.346886523"), "JUP": Decimal("4530.26599")}
        return {"SOL": Decimal("0.236270174"), "HNT": Decimal("71.687274")}

    monkeypatch.setattr(
        PortfolioService,
        "_solscan_wallet_balances",
        solscan_balances,
    )
    monkeypatch.setattr(PortfolioService, "_v1_solana_wallet_balances", lambda _self, _wallet: {})

    response = TestClient(create_app(store)).post("/api/v1/portfolio/reconciliation/refresh")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["connectors"] == ["binance", "bitget", "pionex", "jup_wallet", "solana_wallet"]
    assert data["imported_snapshots"] == 7
    assert {row["connector_id"]: row["status"] for row in data["connector_results"]} == {
        "binance": "refreshed",
        "bitget": "refreshed",
        "pionex": "refreshed",
        "jup_wallet": "refreshed",
        "solana_wallet": "refreshed",
    }
    assert {row["connector_id"] for row in data["snapshots"]} == {"binance", "bitget", "pionex", "jup_wallet", "solana_wallet"}
    with store.connect() as con:
        rows = con.execute(
            """
            select connector_id, asset, quantity
            from portfolio_live_balance_snapshots
            order by connector_id, asset
            """
        ).fetchall()
    assert rows == [
        ("binance", "EUR", Decimal("10.000000000000000000")),
        ("bitget", "USDT", Decimal("6.884000000000000000E-9")),
        ("jup_wallet", "JUP", Decimal("4530.265990000000000000")),
        ("jup_wallet", "SOL", Decimal("3.346886523000000000")),
        ("pionex", "USDT", Decimal("0.895868325219412500")),
        ("solana_wallet", "HNT", Decimal("71.687274000000000000")),
        ("solana_wallet", "SOL", Decimal("0.236270174000000000")),
    ]


def test_portfolio_reconciliation_refresh_keeps_cex_product_metadata(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    def cex_snapshots(_self, connector_id, fetched_at):
        if connector_id != "binance":
            return []
        return [
            PortfolioLiveBalanceSnapshot(
                snapshot_id=f"{connector_id}:JUP:simple_earn_flexible:JUP001:{fetched_at.isoformat()}:0",
                connector_id=connector_id,
                asset="JUP",
                quantity=Decimal("16625.6"),
                source="test",
                fetched_at=fetched_at,
                account_type="simple_earn_flexible",
                product_id="JUP001",
                event_type="balance_snapshot",
            ),
            PortfolioLiveBalanceSnapshot(
                snapshot_id=f"{connector_id}:SOL:spot:{fetched_at.isoformat()}:0",
                connector_id=connector_id,
                asset="SOL",
                quantity=Decimal("1.4"),
                source="test",
                fetched_at=fetched_at,
                account_type="spot",
                event_type="balance_snapshot",
            ),
        ]

    monkeypatch.setattr(PortfolioService, "_v1_cex_live_balance_snapshots", cex_snapshots)
    monkeypatch.setattr(PortfolioService, "_v1_solana_wallet_balances", lambda _self, _wallet: {})
    monkeypatch.setattr(PortfolioService, "_solscan_wallet_balances", lambda _self, _wallet: {})

    result = PortfolioService(store).refresh_reconciliation_snapshots(connectors=["binance"])

    assert result.imported_snapshots == 2
    with store.connect() as con:
        rows = con.execute(
            """
            select asset, quantity, account_type, product_id, event_type
            from portfolio_live_balance_snapshots
            order by asset
            """
        ).fetchall()
    assert rows == [
        ("JUP", Decimal("16625.600000000000000000"), "simple_earn_flexible", "JUP001", "balance_snapshot"),
        ("SOL", Decimal("1.400000000000000000"), "spot", None, "balance_snapshot"),
    ]
    assert PortfolioService(store)._stored_live_balance_snapshots("binance") == {
        "JUP": Decimal("16625.600000000000000000"),
        "SOL": Decimal("1.400000000000000000"),
    }


def test_portfolio_snapshot_does_not_use_stale_cex_live_anchor(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="binance.csv",
        content=(
            "time,asset,amount,type,account\n"
            "2026-01-01T00:00:00Z,JUP,1,deposit,Spot\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("0.20"),
            priced_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="binance:JUP:stale",
                connector_id="binance",
                asset="JUP",
                quantity=Decimal("100"),
                source="v1_connector:binance",
                fetched_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                account_type="simple_earn_flexible",
                product_id="JUP001",
            )
        ]
    )

    snapshot = PortfolioService(store).snapshot()

    assert snapshot.total_value_eur == Decimal("0.200000000000000000")
    assert [(item.account, item.asset, item.quantity) for item in snapshot.positions] == [
        ("Spot", "JUP", Decimal("1.000000000000000000"))
    ]


def test_portfolio_reconciliation_refresh_warns_when_connectors_return_no_snapshots(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(PortfolioService, "_v1_cex_live_balance_snapshots", lambda _self, _connector_id, _fetched_at: [])
    monkeypatch.setattr(PortfolioService, "_v1_cex_live_balances", lambda _self, _connector_id: {})
    monkeypatch.setattr(PortfolioService, "_v1_solana_wallet_balances", lambda _self, _wallet: {})
    monkeypatch.setattr(PortfolioService, "_v1_solana_wallet_balances", lambda _self, _wallet: {})
    monkeypatch.setattr(PortfolioService, "_solscan_wallet_balances", lambda _self, _wallet: {})
    monkeypatch.setattr(PortfolioService, "_solscan_api_key", lambda _self: "test-key")

    response = TestClient(create_app(store)).post("/api/v1/portfolio/reconciliation/refresh")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "warning"
    data = payload["data"]
    assert data["imported_snapshots"] == 0
    assert {row["status"] for row in data["connector_results"]} == {"empty_response"}
    assert any(warning["code"] == "no_live_snapshots_imported" for warning in payload["warnings"])


def test_portfolio_reconciliation_refresh_uses_v1_solana_wallet_fallback_without_solscan_key(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(PortfolioService, "_solscan_api_key", lambda _self: "")
    monkeypatch.setattr(
        PortfolioService,
        "_v1_solana_wallet_balances",
        lambda _self, wallet: {"SOL": Decimal("2.5")} if wallet == PortfolioService.PRIMARY_SOLANA_WALLET else {},
    )
    monkeypatch.setattr(PortfolioService, "_solscan_wallet_balances", lambda _self, _wallet: {})

    result = PortfolioService(store).refresh_reconciliation_snapshots(connectors=["solana_wallet"])

    solana = result.connector_results[0]
    assert solana.connector_id == "solana_wallet"
    assert solana.status == "refreshed"
    assert result.snapshots[0].asset == "SOL"
    assert result.snapshots[0].quantity == Decimal("2.5")


def test_portfolio_snapshot_uses_live_jup_wallet_anchor_but_reconciliation_keeps_ledger_delta(
    tmp_path,
    monkeypatch,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = PortfolioService.KNOWN_JUP_WALLET
    monkeypatch.setattr(PortfolioService, "_v1_cex_live_balances", lambda _self, _connector_id: {})
    monkeypatch.setattr(PortfolioService, "_v1_solana_wallet_balances", lambda _self, _wallet: {})
    monkeypatch.setattr(
        PortfolioService,
        "_solscan_wallet_balances",
        lambda _self, _wallet: {"SOL": Decimal("3"), "JUP": Decimal("4500")},
    )
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="jup-wallet-ledger.csv",
        content=(
            "time,asset,amount,type,account\n"
            f"2026-05-16T00:00:00Z,SOL,15,deposit,{wallet}\n"
            f"2026-05-16T00:00:00Z,JUP,2000,deposit,{wallet}\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("100"),
            priced_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("1"),
            priced_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    service = PortfolioService(store)
    service.refresh_reconciliation_snapshots(connectors=["jup_wallet"])

    snapshot = PortfolioService(store).snapshot()
    snapshot_quantities = {
        (position.account, position.asset): position.quantity for position in snapshot.positions
    }
    assert snapshot_quantities[(wallet, "SOL")] == Decimal("3.000000000000000000")
    assert snapshot_quantities[(wallet, "JUP")] == Decimal("4500.000000000000000000")
    assert snapshot.total_value_eur == Decimal("4800.000000000000000000000000000000000000")

    report = PortfolioService(store).reconciliation_report()
    rows = {
        row.asset: row
        for row in report.rows
        if row.source_group == "Jup Wallet GmHY...3yu"
    }
    assert rows["SOL"].ledger_quantity == Decimal("15.000000000000000000")
    assert rows["SOL"].external_quantity == Decimal("3.000000000000000000")
    assert rows["SOL"].status == "wallet_history_partially_imported"
    assert rows["JUP"].ledger_quantity == Decimal("2000.000000000000000000")
    assert rows["JUP"].external_quantity == Decimal("4500.000000000000000000")


def test_portfolio_snapshot_uses_expected_zero_live_anchor_but_reconciliation_keeps_ledger_delta(
    tmp_path,
    monkeypatch,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(PortfolioService, "_v1_cex_live_balances", lambda _self, _connector_id: {})
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="bitget-current-live.csv",
        content="time,asset,amount,type,account\n2024-12-12T00:00:00Z,USDT,7.9,deposit,bitget\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    priced_at = datetime(2026, 5, 16, tzinfo=timezone.utc)
    live_at = datetime.now(timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.9"),
            priced_at=priced_at,
            source="manual-test",
        )
    )
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="bitget:USDT:test",
                connector_id="bitget",
                asset="USDT",
                quantity=Decimal("0.000000006884"),
                source="v1_connector:bitget",
                fetched_at=live_at,
            )
        ]
    )

    snapshot = PortfolioService(store).snapshot()
    report = PortfolioService(store).reconciliation_report()
    bitget = next(row for row in report.rows if row.source_group == "Bitget" and row.asset == "USDT")

    assert snapshot.total_value_eur == Decimal("0.000000006195600000000000000000000000")
    assert snapshot.account_summary[0].account == "bitget"
    assert snapshot.account_summary[0].value_eur == snapshot.total_value_eur
    assert bitget.ledger_quantity == Decimal("7.900000000000000000")
    assert bitget.external_quantity == Decimal("0.000000006884")
    assert bitget.status == "complete_export_strategy_reference_live_zero"
    assert bitget.severity == "info"


def test_portfolio_snapshot_uses_primary_solana_live_anchor(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(PortfolioService, "_v1_cex_live_balances", lambda _self, _connector_id: {})
    wallet = PortfolioService.PRIMARY_SOLANA_WALLET
    batch = CsvRawImporter(store).import_text(
        source="solana_rpc",
        filename="solana-ledger.csv",
        content=(
            "time,asset,amount,type,account\n"
            f"2024-01-01T00:00:00Z,SOL,10,deposit,{wallet}\n"
            f"2024-01-01T00:00:00Z,HNT,1000,deposit,{wallet}\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    priced_at = datetime(2026, 5, 16, tzinfo=timezone.utc)
    live_at = datetime.now(timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("100"),
            priced_at=priced_at,
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("2"),
            priced_at=priced_at,
            source="manual-test",
        )
    )
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="solana_wallet:SOL:test",
                connector_id="solana_wallet",
                asset="SOL",
                quantity=Decimal("0.25"),
                source="solscan_pro:/account/portfolio",
                fetched_at=live_at,
            ),
            PortfolioLiveBalanceSnapshot(
                snapshot_id="solana_wallet:HNT:test",
                connector_id="solana_wallet",
                asset="HNT",
                quantity=Decimal("50"),
                source="solscan_pro:/account/portfolio",
                fetched_at=live_at,
            ),
            PortfolioLiveBalanceSnapshot(
                snapshot_id="solana_wallet:SPAM:test",
                connector_id="solana_wallet",
                asset="SPAM",
                quantity=Decimal("1000000000"),
                source="solscan_pro:/account/portfolio",
                fetched_at=live_at,
            ),
        ]
    )

    snapshot = PortfolioService(store).snapshot()
    quantities = {(position.account, position.asset): position.quantity for position in snapshot.positions}

    assert quantities[(wallet, "SOL")] == Decimal("0.250000000000000000")
    assert quantities[(wallet, "HNT")] == Decimal("50.000000000000000000")
    assert (wallet, "SPAM") not in quantities
    assert snapshot.total_value_eur == Decimal("125.000000000000000000000000000000000000")


def test_portfolio_snapshot_uses_binance_live_product_anchor_without_changing_reconciliation(
    tmp_path,
    monkeypatch,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(PortfolioService, "_v1_cex_live_balances", lambda _self, _connector_id: {})
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="binance-ledger.csv",
        content=(
            "time,asset,amount,type,account\n"
            "2024-01-01T00:00:00Z,EUR,10000,deposit,Spot\n"
            "2024-01-01T00:00:00Z,JUP,100,deposit,binance\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    priced_at = datetime(2026, 5, 16, tzinfo=timezone.utc)
    live_at = datetime.now(timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="EUR",
            price_eur=Decimal("1"),
            priced_at=priced_at,
            source="fiat:EUR",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("0.2"),
            priced_at=priced_at,
            source="manual-test",
        )
    )
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="binance:EUR:spot:test",
                connector_id="binance",
                asset="EUR",
                quantity=Decimal("0.5"),
                source="v1_connector:binance",
                fetched_at=live_at,
                account_type="spot",
                event_type="balance_snapshot",
            ),
            PortfolioLiveBalanceSnapshot(
                snapshot_id="binance:JUP:simple_earn_flexible:JUP001:test",
                connector_id="binance",
                asset="JUP",
                quantity=Decimal("25"),
                source="v1_connector:binance",
                fetched_at=live_at,
                account_type="simple_earn_flexible",
                product_id="JUP001",
                event_type="balance_snapshot",
            ),
            PortfolioLiveBalanceSnapshot(
                snapshot_id="binance:LDJUP:spot:test",
                connector_id="binance",
                asset="LDJUP",
                quantity=Decimal("25"),
                source="v1_connector:binance",
                fetched_at=live_at,
                account_type="spot",
                event_type="balance_snapshot",
            ),
        ]
    )

    snapshot = PortfolioService(store).snapshot()
    report = PortfolioService(store).reconciliation_report()

    assert snapshot.total_value_eur == Decimal("5.500000000000000000")
    assert {(position.account, position.asset): position.quantity for position in snapshot.positions} == {
        ("Binance Earn Flexible JUP001", "JUP"): Decimal("25.000000000000000000"),
        ("Binance Spot", "EUR"): Decimal("0.500000000000000000"),
    }
    assert snapshot.missing_price_assets == []
    binance = next(row for row in report.rows if row.source_group == "Binance")
    assert binance.ledger_value_eur == Decimal("10000.000000000000000000")
    assert binance.status == "ledger_current_needs_live_anchor"


def test_portfolio_jup_wallet_history_imports_v1_solana_rows(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = PortfolioService.KNOWN_JUP_WALLET
    monkeypatch.setattr(
        PortfolioService,
        "_v1_solana_wallet_history",
        lambda _self, **_kwargs: {
            "signature_count": 1,
            "first_signature": "sig-1",
            "last_signature": "sig-1",
            "rows": [
                {
                    "timestamp_utc": "2026-05-25T10:00:00Z",
                    "asset": "JUP",
                    "symbol": "JUP",
                    "quantity": "10",
                    "event_type": "token_transfer",
                    "side": "in",
                    "tx_id": "sig-1",
                    "wallet_address": wallet,
                }
            ],
            "warnings": [],
        },
    )

    response = TestClient(create_app(store)).post(
        "/api/v1/portfolio/jup-wallet/import-history",
        json={"max_signatures": 1, "max_transactions": 1},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["wallet_address"] == wallet
    assert data["source"] == "solana_rpc"
    assert data["fetched_rows"] == 1
    assert data["signature_count"] == 1
    assert data["normalized_events"] == 1
    with store.connect() as con:
        balance = con.execute(
            "select sum(delta_quantity) from balance_ledger where account = ? and asset = 'JUP'",
            [wallet],
        ).fetchone()[0]
    assert balance == Decimal("10.000000000000000000")


def test_price_points_are_listed_newest_first(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    older = store.add_price_point(
        PricePointCreate(
            asset="usdt",
            price_eur=Decimal("0.89"),
            priced_at=datetime(2021, 4, 28, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    newer = store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.90"),
            priced_at=datetime(2021, 4, 29, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    prices = store.list_price_points()

    assert [price.price_id for price in prices] == [newer.price_id, older.price_id]
    assert older.asset == "USDT"


def test_latest_price_points_are_listed_once_per_asset(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.89"),
            priced_at=datetime(2021, 4, 28, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    latest_usdt = store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.90"),
            priced_at=datetime(2021, 4, 29, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    latest_btc = store.add_price_point(
        PricePointCreate(
            asset="BTC",
            price_eur=Decimal("50000"),
            priced_at=datetime(2021, 4, 29, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    prices = store.list_latest_price_points()

    assert [price.price_id for price in prices] == [latest_btc.price_id, latest_usdt.price_id]


def test_price_point_at_or_before_uses_historical_effective_price(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    older = store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.89"),
            priced_at=datetime(2021, 4, 28, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.95"),
            priced_at=datetime(2021, 4, 30, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    price = store.price_point_at_or_before(
        "usdt",
        datetime(2021, 4, 29, tzinfo=timezone.utc),
    )

    assert price is not None
    assert price.price_id == older.price_id
    assert store.price_point_at_or_before(
        "USDT",
        datetime(2021, 4, 27, tzinfo=timezone.utc),
    ) is None


def test_delete_price_point_removes_only_requested_entry(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    old_price = store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.89"),
            priced_at=datetime(2021, 4, 28, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    kept_price = store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.90"),
            priced_at=datetime(2021, 4, 29, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    assert store.delete_price_point(old_price.price_id) is True
    assert store.delete_price_point("missing") is False

    prices = store.list_price_points()
    assert [price.price_id for price in prices] == [kept_price.price_id]
