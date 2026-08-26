from datetime import datetime, timezone
from decimal import Decimal

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.contracts.portfolio import PortfolioLiveBalanceSnapshot
from steuerreport_v2.contracts.review import ReviewDecisionCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.cockpit import CockpitService
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


def _build_portfolio(store: DuckDbStore) -> None:
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="cockpit.csv",
        content=(
            "time,asset,amount,type,account\n"
            "2026-01-01T00:00:00Z,BTC,0.1,deposit,Spot\n"
            "2026-01-01T00:00:00Z,USDT,100,deposit,Spot\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    priced_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="BTC",
            price_eur=Decimal("50000"),
            priced_at=priced_at,
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.9"),
            priced_at=priced_at,
            source="manual-test",
        )
    )


def test_cockpit_summary_aggregates_portfolio_review_and_sources(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _build_portfolio(store)

    summary = CockpitService(store).summary()

    assert summary.portfolio_value_eur == Decimal("5090.000000000000000000000000000000000000")
    assert summary.export_allowed is True
    assert summary.export_status == "frei"
    assert summary.top_assets[0].asset == "BTC"
    assert summary.top_assets[0].share_pct == Decimal("98.23")
    assert summary.top_assets[0].value_basis == "current_ledger"
    assert summary.top_sources[0].source_group == "Binance"
    assert summary.top_sources[0].ledger_value_eur == summary.top_sources[0].value_eur
    assert summary.portfolio_performance.display_value_eur == summary.portfolio_value_eur
    assert summary.portfolio_performance.calculated_value_eur == summary.portfolio_value_eur
    assert summary.portfolio_performance.display_value_basis == "calculated_ledger"
    assert summary.price_coverage.missing_assets == []
    assert summary.price_coverage.coverage_pct == Decimal("100.00")
    assert summary.live_reconciliation.stored_live_connectors == 0
    assert summary.evidence_health.status == "missing_decision"
    assert [action.target for action in summary.quick_actions] == [
        "import",
        "portfolio",
        "export",
        "review",
        "review",
    ]
    assert [action.label for action in summary.quick_actions] == [
        "Import starten",
        "Preise aktualisieren",
        "Report-Center oeffnen",
        "Belegstatus pruefen",
        "Review-Issues bearbeiten",
    ]


def test_cockpit_summary_reports_portfolio_performance_from_fifo_lots_and_eur_trades(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _build_portfolio(store)
    with store.connect() as con:
        con.execute(
            """
            insert into tax_lots (
                lot_id, asset, acquired_at, quantity_total, quantity_remaining,
                cost_basis_eur_total, source_event_id, created_at
            )
            values
                ('lot-btc', 'BTC', ?, 1, 0.1, 40000, 'event-btc', ?),
                ('lot-usdt', 'USDT', ?, 1000, 100, 900, 'event-usdt', ?)
            """,
            [
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 1, 2, tzinfo=timezone.utc),
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 1, 2, tzinfo=timezone.utc),
            ],
        )
        con.execute(
            """
            insert into canonical_events (
                event_id, source, source_ref, event_time, event_type, asset,
                quantity, quote_asset, quote_quantity, fee_asset, fee_quantity,
                tx_id, wallet, account, confidence, raw_object_id
            )
            values
                ('trade-buy', 'binance', 'buy', ?, 'trade', 'BTC', 0.1, 'EUR', 4500, null, null, null, null, 'Spot', 1, null),
                ('trade-sell', 'binance', 'sell', ?, 'trade', 'ETH', -1, 'EUR', 500, null, null, null, null, 'Spot', 1, null)
            """,
            [
                datetime(2026, 1, 1, tzinfo=timezone.utc),
                datetime(2026, 1, 3, tzinfo=timezone.utc),
            ],
        )

    summary = CockpitService(store).summary()
    assets = {asset.asset: asset for asset in summary.top_assets}

    assert summary.portfolio_performance.open_cost_basis_eur == Decimal("4090.000000000000000000")
    assert summary.portfolio_performance.unrealized_return_eur == Decimal("1000.000000000000000000000000000000000000")
    assert summary.portfolio_performance.unrealized_return_pct == Decimal("24.45")
    assert summary.portfolio_performance.net_fiat_invested_eur == Decimal("4000.000000000000000000")
    assert summary.portfolio_performance.cost_basis_status == "available"
    assert assets["BTC"].open_cost_basis_eur == Decimal("4000.000000000000000000")
    assert assets["BTC"].unrealized_return_eur == Decimal("1000.000000000000000000000000000000000000")
    assert assets["BTC"].unrealized_return_pct == Decimal("25.00")
    assert assets["BTC"].performance_status == "gain"
    assert assets["USDT"].open_cost_basis_eur == Decimal("90.000000000000000000")
    assert assets["USDT"].unrealized_return_eur == Decimal("0E-36")
    assert assets["USDT"].performance_status == "flat"


def test_cockpit_evidence_health_complete_after_canonical_review_decision(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _build_portfolio(store)
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

    summary = CockpitService(store).summary()

    assert summary.evidence_health.status == "complete"
    assert summary.evidence_health.canonical_count == 1
    assert summary.evidence_health.legacy_ref_count == 0


def test_cockpit_summary_uses_live_assets_without_legacy_wallets(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="mixed",
        filename="cockpit-live.csv",
        content=(
            "time,asset,amount,type,account\n"
            f"2022-01-01T00:00:00Z,HNT,100,deposit,{PortfolioService.MAIN_HELIUM_LEGACY_WALLET}\n"
            "2026-01-01T00:00:00Z,USDT,1000,deposit,bitget\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    priced_at = datetime(2026, 1, 3, tzinfo=timezone.utc)
    live_at = datetime.now(timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("2"),
            priced_at=priced_at,
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("1"),
            priced_at=priced_at,
            source="manual-test",
        )
    )
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="solana_wallet:HNT:test",
                connector_id="solana_wallet",
                asset="HNT",
                quantity=Decimal("2"),
                source="solscan_pro:/account/portfolio",
                fetched_at=live_at,
            ),
            PortfolioLiveBalanceSnapshot(
                snapshot_id="bitget:USDT:test",
                connector_id="bitget",
                asset="USDT",
                quantity=Decimal("0.01"),
                source="v1_connector:bitget",
                fetched_at=live_at,
            ),
        ]
    )

    summary = CockpitService(store).summary()
    assets = {asset.asset: asset for asset in summary.top_assets}

    assert summary.portfolio_value_eur == Decimal("4.01")
    assert assets["HNT"].quantity == Decimal("2")
    assert assets["HNT"].value_basis == "live_api"
    assert assets["USDT"].quantity == Decimal("0.01")
    assert all(asset.quantity != Decimal("100") for asset in summary.top_assets)


def test_cockpit_live_status_uses_reconciled_jup_wallet(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    priced_at = datetime(2026, 1, 3, tzinfo=timezone.utc)
    batch = CsvRawImporter(store).import_text(
        source="solana_rpc",
        filename="jup-history.json",
        content=(
            "time,asset,amount,type,account\n"
            f"2026-01-01T00:00:00Z,JUP,12.5,deposit,{PortfolioService.KNOWN_JUP_WALLET}\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("0.5"),
            priced_at=priced_at,
            source="manual-test",
        )
    )
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="jup_wallet:JUP:test",
                connector_id="jup_wallet",
                asset="JUP",
                quantity=Decimal("12.5"),
                source="solscan_pro:/account/portfolio",
                fetched_at=priced_at,
            )
        ]
    )

    summary = CockpitService(store).summary()

    assert summary.live_reconciliation.status == "ok"
    assert summary.live_reconciliation.missing_wallets == []
    assert summary.live_reconciliation.blocker_count == 0
    assert summary.live_reconciliation.warning_count == 0


def test_cockpit_sources_use_live_value_status_and_ignore_receipt_tokens(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = PortfolioService.KNOWN_JUP_WALLET
    priced_at = datetime(2026, 5, 30, tzinfo=timezone.utc)
    live_at = datetime.now(timezone.utc)
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="cockpit-live-sources.csv",
        content=(
            "time,asset,amount,type,account\n"
            "2026-05-29T00:00:00Z,JUP,1,deposit,Spot\n"
            f"2026-05-29T00:00:00Z,JUP,5,deposit,{wallet}\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
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
                snapshot_id="binance:JUP:test",
                connector_id="binance",
                asset="JUP",
                quantity=Decimal("10"),
                source="v1_connector:binance",
                fetched_at=live_at,
                account_type="simple_earn_flexible",
                product_id="JUP001",
            ),
            PortfolioLiveBalanceSnapshot(
                snapshot_id="binance:LDJUP:test",
                connector_id="binance",
                asset="LDJUP",
                quantity=Decimal("99"),
                source="v1_connector:binance",
                fetched_at=live_at,
                account_type="spot",
            ),
            PortfolioLiveBalanceSnapshot(
                snapshot_id="jup_wallet:JUP:test",
                connector_id="jup_wallet",
                asset="JUP",
                quantity=Decimal("5"),
                source="solscan_pro:/account/portfolio",
                fetched_at=live_at,
            ),
        ]
    )

    summary = CockpitService(store).summary()
    sources = {source.source_group: source for source in summary.top_sources}

    assert sources["Binance"].value_eur == Decimal("2.0")
    assert sources["Binance"].ledger_value_eur == Decimal("0.200000000000000000")
    assert sources["Binance"].live_value_eur == Decimal("2.0")
    assert sources["Binance"].live_anchor_source == "v1_connector:binance"
    assert sources["Binance"].display_warning is not None
    assert summary.live_reconciliation.status == "warning"
    assert summary.live_reconciliation.warning_count == 1
    assert sources["Jup Wallet GmHY...3yu"].current_status == "live_anchor_reconciled"
    assert "LDJUP" not in {asset.asset for asset in summary.top_assets}


def test_cockpit_summary_reports_review_and_price_tasks(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="missing-price.csv",
        content="time,asset,amount,type,account\n2026-01-01T00:00:00Z,BTC,1,deposit,pionex-main\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()

    summary = CockpitService(store).summary()

    assert summary.export_allowed is False
    assert summary.export_status == "blockiert"
    assert summary.price_coverage.missing_assets == ["BTC"]
    assert summary.open_tasks >= 2
    assert {task.target for task in summary.tasks} >= {"review", "portfolio"}


def test_cockpit_excludes_stale_expected_zero_ledger_from_current_total(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="pionex-ledger.csv",
        content=(
            "time,asset,amount,type,account\n"
            "2026-01-01T00:00:00Z,USDT,4,deposit,pionex\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("1"),
            priced_at=datetime.now(timezone.utc),
            source="manual-test",
        )
    )
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="pionex:USDT:stale",
                connector_id="pionex",
                asset="USDT",
                quantity=Decimal("2"),
                source="pionex_api_v2",
                fetched_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            )
        ]
    )

    summary = CockpitService(store).summary()
    pionex = next(
        source for source in summary.top_sources if source.source_group == "Pionex"
    )

    assert summary.portfolio_value_eur == Decimal("0")
    assert sum((source.value_eur for source in summary.top_sources), Decimal("0")) == Decimal("0")
    assert pionex.value_eur == Decimal("0")
    assert pionex.ledger_value_eur == Decimal("4.000000000000000000000000000")
    assert pionex.live_value_eur is None
    assert pionex.last_live_at == datetime(2026, 1, 2)
    assert pionex.value_basis == "expected_zero_policy_no_current_live"
    assert pionex.current_status == "expected_zero_live_unavailable"
    assert pionex.display_warning is not None


def test_cockpit_ignores_unpriced_live_token_identifiers_for_price_task(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    live_at = datetime.now(timezone.utc)
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="solana_wallet:2DWZNY:test",
                connector_id="solana_wallet",
                asset="2DWZNY...NRQC",
                quantity=Decimal("1000000"),
                source="solscan_pro:/account/portfolio",
                fetched_at=live_at,
            )
        ]
    )

    summary = CockpitService(store).summary()

    assert summary.price_coverage.missing_assets == []
    assert summary.price_coverage.coverage_pct == Decimal("100.00")
    assert not any(task.title == "Preisdeckung vervollstaendigen" for task in summary.tasks)


def test_cockpit_summary_api_contract(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _build_portfolio(store)
    app = create_app(store)
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/cockpit/summary"
    )

    response = route.endpoint()

    assert response.status == "ok"
    assert response.data is not None
    assert response.data.portfolio_value_eur == Decimal("5090.000000000000000000000000000000000000")
    assert response.data.price_coverage.coverage_pct == Decimal("100.00")
    assert response.data.top_sources[0].source_group == "Binance"
