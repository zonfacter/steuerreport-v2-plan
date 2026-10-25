from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.contracts.portfolio import PortfolioLiveBalanceSnapshot
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.sources import SourceService
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


def _seed_sources(store: DuckDbStore) -> None:
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="binance.csv",
        content=(
            "time,asset,amount,type,account\n"
            "2026-01-01T00:00:00Z,BTC,0.1,deposit,Spot\n"
            "2026-01-01T00:00:00Z,USDT,100,deposit,Funding\n"
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


def test_coinbase_transaction_history_profile_preserves_trade_fee_and_transfer_direction(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="coinbase",
        filename="coinbase-transaction-history.csv",
        content=(
            "Timestamp,Transaction Type,Asset,Quantity Transacted,Spot Price Currency,Subtotal,Fees and/or Spread,Transaction ID\n"
            "2025-09-06T10:00:00Z,Buy,SOL,1,EUR,20.00,1.00,buy-1\n"
            "2025-09-07T10:00:00Z,Sell,SOL,0.4,EUR,10.00,0.50,sell-1\n"
            "2025-09-08T10:00:00Z,Send,SOL,0.1,EUR,,,send-1\n"
            "2025-09-09T10:00:00Z,Receive,SOL,0.2,EUR,,,receive-1\n"
            "2025-09-10T10:00:00Z,Learning Reward,SOL,0.01,EUR,0.20,0,reward-1\n"
        ),
    )

    result = RawNormalizer(store).normalize_batch(batch.batch_id)
    events = store.list_canonical_events()

    assert len(result) == 5
    assert [event.event_type for event in events] == [
        "trade",
        "trade",
        "transfer",
        "transfer",
        "reward",
    ]
    assert [event.quantity for event in events] == [
        Decimal("1"),
        Decimal("-0.4"),
        Decimal("-0.1"),
        Decimal("0.2"),
        Decimal("0.01"),
    ]
    assert events[0].quote_asset == "EUR"
    assert events[0].quote_quantity == Decimal("20.00")
    assert events[0].fee_asset == "EUR"
    assert events[0].fee_quantity == Decimal("1.00")
    assert all(event.account == "coinbase" for event in events)


def test_sources_overview_groups_readable_sources(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _seed_sources(store)

    overview = SourceService(store).overview()

    assert overview.total_value_eur == Decimal("5090.000000000000000000000000000000000000")
    assert overview.sources[0].source_id == "binance"
    assert overview.sources[0].label == "Binance"
    assert overview.sources[0].account_count == 2
    assert overview.sources[0].asset_count == 2
    assert overview.sources[0].top_assets[0].asset == "BTC"
    assert overview.health is not None
    assert overview.health.status == "blocked"
    assert overview.health.sources_count == 2
    assert overview.health.live_connected_sources == 0
    assert overview.health.ledger_only_sources == 2
    assert overview.health.missing_live_sources == 2
    assert overview.health.total_open_reconciliation_issues == 1
    assert {issue.issue for issue in overview.health.issues} >= {
        "missing_live_anchor",
        "reconciliation_issue",
    }
    assert overview.sources[0].live_age_days is None
    assert overview.sources[0].live_freshness == "missing"


def test_source_detail_keeps_full_accounts_and_recent_events(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _seed_sources(store)

    detail = SourceService(store).detail("binance")

    assert detail is not None
    assert detail.full_accounts == ["Spot", "Funding"]
    assert len(detail.assets) == 2
    assert {event.asset for event in detail.recent_events} == {"BTC", "USDT"}
    assert detail.reconciliation.status == "ledger_current_needs_live_anchor"


def test_helium_main_legacy_wallet_is_grouped_as_solana_migration(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="helium-migration.csv",
        content=(
            "time,asset,amount,type,account\n"
            f"2022-01-01T00:00:00Z,HNT,100,deposit,{PortfolioService.MAIN_HELIUM_LEGACY_WALLET}\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("2"),
            priced_at=datetime(2022, 1, 2, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    overview = SourceService(store).overview()
    labels = {source.label for source in overview.sources}

    assert "Helium Main Legacy Wallet" not in labels
    assert "Solana Wallet 6K9n7y...qEwP" not in labels
    assert all(
        PortfolioService.MAIN_HELIUM_LEGACY_WALLET not in account.account
        for source in overview.sources
        for account in source.accounts
    )


def test_helium_legacy_service_wallets_are_not_dashboard_sources(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    legacy_service_wallet = "13xfSeV2UcVgUiTKmd9V1Htunc6N7wsAgkGRHtquN9hpCbA78Yp"
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="helium-service.csv",
        content=(
            "time,asset,amount,type,account\n"
            f"2022-01-01T00:00:00Z,HNT,100,deposit,{legacy_service_wallet}\n"
            "2022-01-02T00:00:00Z,HNT,50,deposit,helium\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("2"),
            priced_at=datetime(2022, 1, 3, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    overview = SourceService(store).overview()
    labels = {source.label for source in overview.sources}

    assert not any("Legacy" in label or "Helium" in label for label in labels)
    assert "Solana Wallet 6K9n7y...qEwP" not in labels
    assert all(
        legacy_service_wallet not in account.account and account.account != "helium"
        for source in overview.sources
        for account in source.accounts
    )


def test_known_fairspot_staking_wallet_stays_transfer_counterparty_not_source(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="helium-fairspot-staking.csv",
        content=(
            "time,asset,amount,type,txid,payer,payee\n"
            f"2021-06-23T20:26:18Z,HNT,100,payment_v2,Kk7ZTefj1fQOZ-1rPwt4aIOXpTmckgt8JA28IJ6XF_8,{PortfolioService.MAIN_HELIUM_LEGACY_WALLET},{PortfolioService.FAIRSPOT_STAKING_WALLET}\n"
            f"2021-07-08T18:30:00Z,HNT,99.75,payment_v2,tLOGE2C0v-CGYSJfvKU6KvI7oQq4OALrz3rh6SbC8Qs,{PortfolioService.FAIRSPOT_STAKING_WALLET},{PortfolioService.MAIN_HELIUM_LEGACY_WALLET}\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("2"),
            priced_at=datetime(2021, 6, 23, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    overview = SourceService(store).overview()
    labels = {item.label for item in overview.sources}

    assert "Fairspot Staking 133m...RuN" not in labels
    assert "Fairspot Staking Transfer Counterparty" not in labels
    assert all(
        PortfolioService.FAIRSPOT_STAKING_WALLET not in account.account
        for source in overview.sources
        for account in source.accounts
    )


def test_solana_wallet_source_uses_live_snapshot_not_helium_legacy_ledger(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="mixed-solana.csv",
        content=(
            "time,asset,amount,type,account\n"
            f"2022-01-01T00:00:00Z,HNT,100,deposit,{PortfolioService.MAIN_HELIUM_LEGACY_WALLET}\n"
            f"2026-01-01T00:00:00Z,HNT,999,deposit,{PortfolioService.PRIMARY_SOLANA_WALLET}\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("2"),
            priced_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    fetched_at = datetime(2026, 1, 3, tzinfo=timezone.utc)
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="solana_wallet:HNT:test",
                connector_id="solana_wallet",
                asset="HNT",
                quantity=Decimal("71.687274"),
                source="solscan_pro:/account/portfolio",
                fetched_at=fetched_at,
            ),
            PortfolioLiveBalanceSnapshot(
                snapshot_id="solana_wallet:SPAM:test",
                connector_id="solana_wallet",
                asset="SPAM",
                quantity=Decimal("1000000000"),
                source="solscan_pro:/account/portfolio",
                fetched_at=fetched_at,
            ),
        ]
    )

    overview = SourceService(store).overview()
    labels = {source.label for source in overview.sources}
    solana = next(source for source in overview.sources if source.label == "Solana Wallet 6K9n7y...qEwP")
    detail = SourceService(store).detail("solana-wallet-6k9n7y-qewp")

    assert "Helium Main Legacy Wallet" not in labels
    assert solana.value_eur == Decimal("143.374548000000000000000000000000000000")
    assert [asset.asset for asset in solana.top_assets] == ["HNT"]
    assert solana.accounts[0].account == PortfolioService.PRIMARY_SOLANA_WALLET
    assert solana.accounts[0].value_eur == solana.value_eur
    assert detail is not None
    assert detail.live_value_eur == solana.value_eur
    assert detail.full_accounts == [PortfolioService.PRIMARY_SOLANA_WALLET]


def test_source_overview_uses_live_value_and_keeps_ledger_delta(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="bitget",
        filename="bitget-ledger.csv",
        content=(
            "time,asset,amount,type,account\n"
            "2026-01-01T00:00:00Z,USDT,1000,deposit,bitget\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    priced_at = datetime(2026, 1, 3, tzinfo=timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("1"),
            priced_at=priced_at,
            source="manual-test",
        )
    )
    live_at = datetime.now(timezone.utc)
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="bitget:USDT:test",
                connector_id="bitget",
                asset="USDT",
                quantity=Decimal("0.02"),
                source="v1_connector:bitget",
                fetched_at=live_at,
            )
        ]
    )

    overview = SourceService(store).overview()
    bitget = next(source for source in overview.sources if source.label == "Bitget")
    detail = SourceService(store).detail("bitget")

    assert overview.total_value_eur == Decimal("0.02")
    assert bitget.value_basis == "live_api"
    assert bitget.value_eur == Decimal("0.02")
    assert bitget.ledger_value_eur == Decimal("1000.000000000000000000000000000000000000")
    assert bitget.delta_value_eur == Decimal("-999.9800000000000000000000000")
    assert bitget.live_anchor_source == "v1_connector:bitget"
    assert bitget.display_warning is not None
    assert bitget.last_evidence_files == ["bitget-ledger.csv"]
    assert bitget.top_assets[0].value_basis == "live_api"
    assert bitget.top_assets[0].priced_at_latest == priced_at.replace(tzinfo=None)
    assert detail is not None
    assert detail.reconciliation.severity == "blocker"
    assert detail.reconciliation.live_anchor_source == "v1_connector:bitget"
    assert detail.display_warning is not None
    assert detail.assets[0].quantity == Decimal("0.02")
    assert detail.assets[0].value_basis == "live_api"


def test_source_overview_does_not_present_stale_expected_zero_as_live_value(
    tmp_path,
):
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
    stale_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="pionex:USDT:stale",
                connector_id="pionex",
                asset="USDT",
                quantity=Decimal("2"),
                source="pionex_api_v2",
                fetched_at=stale_at,
            )
        ]
    )

    overview = SourceService(store).overview()
    pionex = next(source for source in overview.sources if source.label == "Pionex")

    assert overview.total_value_eur == Decimal("0")
    assert pionex.value_eur == Decimal("0")
    assert pionex.value_basis == "expected_zero_policy_no_current_live"
    assert pionex.ledger_value_eur == Decimal("4.000000000000000000000000000")
    assert pionex.live_value_eur is None
    assert pionex.delta_value_eur is None
    assert pionex.last_live_at == stale_at.replace(tzinfo=None)
    assert pionex.live_freshness == "stale"
    assert pionex.current_status == "expected_zero_live_unavailable"
    assert pionex.display_warning is not None
    assert pionex.top_assets == []


def test_source_breakdown_empty_response_supersedes_old_snapshot(tmp_path):
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
    old_snapshot_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="pionex:USDT:old",
                connector_id="pionex",
                asset="USDT",
                quantity=Decimal("2"),
                source="pionex_api_v2",
                fetched_at=old_snapshot_at,
            )
        ]
    )
    empty_at = datetime.now(timezone.utc)
    with store.connect() as con:
        con.execute(
            """
            insert into portfolio_live_connector_runs (
                run_id, connector_id, fetched_at, status, snapshots_count,
                source, message
            )
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                "pionex-empty-test",
                "pionex",
                empty_at,
                "empty_response",
                0,
                "pionex_api_v2",
                "Connector returned no balances.",
            ],
        )

    breakdown = SourceService(store).reconciliation_breakdown("pionex")

    assert breakdown is not None
    assert breakdown.live_value_eur == Decimal("0")
    assert breakdown.last_live_at == empty_at.replace(tzinfo=None)
    assert breakdown.live_anchor_source == "pionex_api_v2:empty_response"
    assert breakdown.live_components == []
    assert breakdown.rows[0].asset == "USDT"
    assert breakdown.rows[0].live_quantity == Decimal("0")
    assert breakdown.rows[0].delta_quantity == Decimal("-4.000000000000000000")
    assert breakdown.rows[0].status == "dust_delta"


def test_source_reconciliation_breakdown_shows_expected_zero_asset_delta(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="bitget",
        filename="bitget-ledger.csv",
        content="time,asset,amount,type,account\n2026-01-01T00:00:00Z,USDT,1000,deposit,bitget\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    priced_at = datetime(2026, 1, 3, tzinfo=timezone.utc)
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
                snapshot_id="bitget:USDT:test",
                connector_id="bitget",
                asset="USDT",
                quantity=Decimal("0.02"),
                source="v1_connector:bitget",
                fetched_at=priced_at,
            )
        ]
    )

    breakdown = SourceService(store).reconciliation_breakdown("bitget")

    assert breakdown is not None
    assert breakdown.label == "Bitget"
    assert breakdown.severity == "blocker"
    assert breakdown.live_anchor_source == "v1_connector:bitget"
    assert breakdown.rows[0].asset == "USDT"
    assert breakdown.rows[0].ledger_quantity == Decimal("1000.000000000000000000")
    assert breakdown.rows[0].live_quantity == Decimal("0.020000000000000000")
    assert breakdown.rows[0].delta_value_eur == Decimal("-999.9800000000000000000000000")
    assert breakdown.rows[0].status == "expected_zero_delta"


def test_source_reconciliation_breakdown_shows_binance_product_components(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="binance-ledger.csv",
        content="time,asset,amount,type,account\n2026-05-29T00:00:00Z,JUP,1,deposit,Spot\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    priced_at = datetime(2026, 5, 30, tzinfo=timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("0.2"),
            priced_at=priced_at,
            source="manual-test",
        )
    )
    live_at = datetime.now(timezone.utc)
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="binance:JUP:earn",
                connector_id="binance",
                asset="JUP",
                quantity=Decimal("40"),
                source="v1_connector:binance",
                fetched_at=live_at,
                account_type="simple_earn_flexible",
                product_id="JUP001",
            ),
            PortfolioLiveBalanceSnapshot(
                snapshot_id="binance:JUP:spot",
                connector_id="binance",
                asset="JUP",
                quantity=Decimal("2"),
                source="v1_connector:binance",
                fetched_at=live_at,
                account_type="spot",
            ),
        ]
    )

    breakdown = SourceService(store).reconciliation_breakdown("binance")

    assert breakdown is not None
    assert breakdown.severity == "warning"
    assert breakdown.display_warning is not None
    assert breakdown.rows[0].asset == "JUP"
    assert breakdown.rows[0].ledger_quantity == Decimal("1.000000000000000000")
    assert breakdown.rows[0].live_quantity == Decimal("42.000000000000000000")
    assert breakdown.rows[0].live_components == 2
    assert breakdown.rows[0].live_account_types == ["simple_earn_flexible", "spot"]
    assert breakdown.rows[0].live_products == ["JUP001"]
    assert breakdown.rows[0].status == "material_live_ledger_delta"
    components = sorted(breakdown.live_components, key=lambda item: str(item.account_type))
    assert [(item.account_type, item.product_id, item.quantity) for item in components] == [
        ("simple_earn_flexible", "JUP001", Decimal("40.000000000000000000")),
        ("spot", None, Decimal("2.000000000000000000")),
    ]
    assert components[0].value_eur == Decimal("8.000000000000000000000000000")


def test_binance_uncredited_earn_accrual_is_visible_but_not_a_fifo_ledger_delta(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                source_ref="sol-ledger",
                event_time=datetime(2026, 7, 17, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("10"),
                account="Spot",
            )
        ]
    )
    BalanceLedgerBuilder(store).rebuild()
    priced_at = datetime.now(timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("70"),
            priced_at=priced_at,
            source="manual-test",
        )
    )
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="binance:SOL:locked",
                connector_id="binance",
                asset="SOL",
                quantity=Decimal("10"),
                source="binance_api",
                fetched_at=priced_at,
                account_type="simple_earn_locked",
                product_id="Sol*120",
                event_type="balance_snapshot",
            ),
            PortfolioLiveBalanceSnapshot(
                snapshot_id="binance:SOL:accrual",
                connector_id="binance",
                asset="SOL",
                quantity=Decimal("0.1"),
                source="binance_api",
                fetched_at=priced_at,
                account_type="simple_earn_locked",
                product_id="Sol*120",
                event_type="earn_accrued_reward_snapshot",
            ),
        ]
    )

    breakdown = SourceService(store).reconciliation_breakdown("binance")
    evidence = SourceService(store).binance_reconciliation_evidence(assets=["SOL"])

    assert breakdown is not None
    assert breakdown.live_value_eur == Decimal("707.0000000000000000000000000")
    assert breakdown.live_nonledger_accrual_value_eur == Decimal("7.0000000000000000000")
    assert breakdown.reconciliation_live_value_eur == Decimal("700.0000000000000000000000000")
    assert breakdown.raw_delta_value_eur == Decimal("7.0000000000000000000000000")
    assert breakdown.delta_value_eur == Decimal("0E-25")
    row = breakdown.rows[0]
    assert row.live_quantity == Decimal("10.100000000000000000")
    assert row.live_nonledger_accrual_quantity == Decimal("0.100000000000000000")
    assert row.reconciliation_live_quantity == Decimal("10.000000000000000000")
    assert row.raw_delta_quantity == Decimal("0.100000000000000000")
    assert row.delta_quantity == Decimal("0E-18")
    assert row.status == "quantity_reconciled"
    assert evidence is not None
    assert evidence.live_nonledger_accrual_value_eur == Decimal("7.0000000000000000000")
    assert evidence.asset_reports[0].live_nonledger_accrual_quantity == Decimal(
        "0.100000000000000000"
    )
    assert evidence.asset_reports[0].delta_quantity == Decimal("0E-18")


def test_source_reconciliation_breakdown_api(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _seed_sources(store)

    response = TestClient(create_app(store)).get("/api/v1/sources/binance/reconciliation")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source_id"] == "binance"
    assert data["rows"][0]["asset"] == "BTC"


def test_binance_reconciliation_evidence_report_highlights_product_gaps(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                source_ref="jup-trade",
                event_time=datetime(2025, 2, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="JUP",
                quantity=Decimal("10"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                source_ref="jup-unknown",
                event_time=datetime(2025, 2, 2, tzinfo=timezone.utc),
                event_type="unknown",
                asset="JUP",
                quantity=Decimal("0"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                source_ref="sol-reward",
                event_time=datetime(2025, 3, 1, tzinfo=timezone.utc),
                event_type="reward",
                asset="SOL",
                quantity=Decimal("0.5"),
                account="Spot",
            ),
        ]
    )
    BalanceLedgerBuilder(store).rebuild()
    priced_at = datetime(2026, 5, 30, tzinfo=timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("0.2"),
            priced_at=priced_at,
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("70"),
            priced_at=priced_at,
            source="manual-test",
        )
    )
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="binance:JUP:earn",
                connector_id="binance",
                asset="JUP",
                quantity=Decimal("40"),
                source="v1_connector:binance",
                fetched_at=priced_at,
                account_type="simple_earn_flexible",
                product_id="JUP001",
            ),
            PortfolioLiveBalanceSnapshot(
                snapshot_id="binance:SOL:locked",
                connector_id="binance",
                asset="SOL",
                quantity=Decimal("2"),
                source="v1_connector:binance",
                fetched_at=priced_at,
                account_type="simple_earn_locked",
                product_id="Sol*120",
            ),
        ]
    )

    report = SourceService(store).binance_reconciliation_evidence()

    assert report is not None
    assert report.assets == ["EUR", "JUP", "SOL"]
    jup = next(item for item in report.asset_reports if item.asset == "JUP")
    assert jup.suspected_gap == "missing_earn_flexible_history_or_product_mapping"
    assert jup.unknown_event_count == 1
    assert jup.live_components[0].account_type == "simple_earn_flexible"
    assert {summary.event_type for summary in jup.event_summaries} == {"trade", "unknown"}
    sol = next(item for item in report.asset_reports if item.asset == "SOL")
    assert sol.suspected_gap == "missing_locked_earn_history_or_product_mapping"
    requirements = {(item.asset, item.requirement): item for item in report.history_requirements}
    assert requirements[("JUP", "flexible_earn_subscription_redemption_reward_history")].current_status == "missing"
    assert requirements[("SOL", "locked_earn_subscription_redemption_reward_history")].current_status == "missing"


def test_binance_reconciliation_evidence_api(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _seed_sources(store)

    response = TestClient(create_app(store)).get(
        "/api/v1/sources/binance/reconciliation/evidence?since=2025-01-01&assets=BTC"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source_id"] == "binance"
    assert data["assets"] == ["BTC"]
    assert data["asset_reports"][0]["asset"] == "BTC"


def test_binance_reconciliation_evidence_marks_fiat_history_partial_when_imports_exist(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="Binance-Fiat-Deposit-History.xlsx",
        content="time,asset,amount,type,account\n2025-01-01T00:00:00Z,EUR,100,deposit,Spot\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                source_ref="eur-shadow",
                event_time=datetime(2025, 2, 1, tzinfo=timezone.utc),
                event_type="unknown",
                asset="EUR",
                quantity=Decimal("0"),
                account="Spot",
            )
        ]
    )

    report = SourceService(store).binance_reconciliation_evidence(assets=["EUR"])

    assert report is not None
    requirement = report.history_requirements[0]
    assert requirement.requirement == "fiat_deposit_withdraw_buy_spend_history"
    assert requirement.current_status == "partial"
    assert requirement.evidence_refs == ["Binance-Fiat-Deposit-History.xlsx"]


def test_binance_reconciliation_evidence_recognizes_simple_earn_api_import(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance_simple_earn_api",
        filename="var/binance_simple_earn_history/20260531T095848Z",
        content=(
            "time_iso,asset,amount,record_type,account_type,product_id,source_ref\n"
            "2025-01-01T00:00:00Z,JUP,40,flexible_subscription,"
            "simple_earn_flexible,JUP001,sub-1\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    priced_at = datetime(2026, 5, 30, tzinfo=timezone.utc)
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
                snapshot_id="binance:JUP:earn",
                connector_id="binance",
                asset="JUP",
                quantity=Decimal("40"),
                source="v1_connector:binance",
                fetched_at=priced_at,
                account_type="simple_earn_flexible",
                product_id="JUP001",
            )
        ]
    )

    report = SourceService(store).binance_reconciliation_evidence(assets=["JUP"])

    requirement = report.history_requirements[0]
    assert requirement.requirement == "flexible_earn_subscription_redemption_reward_history"
    assert requirement.current_status == "covered"
    assert requirement.evidence_refs == ["var/binance_simple_earn_history/20260531T095848Z"]


def test_binance_earn_history_preflight_lists_missing_live_products(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    priced_at = datetime(2026, 5, 30, tzinfo=timezone.utc)
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
                snapshot_id="binance:JUP:earn",
                connector_id="binance",
                asset="JUP",
                quantity=Decimal("40"),
                source="v1_connector:binance",
                fetched_at=priced_at,
                account_type="simple_earn_flexible",
                product_id="JUP001",
            ),
            PortfolioLiveBalanceSnapshot(
                snapshot_id="binance:SOL:spot",
                connector_id="binance",
                asset="SOL",
                quantity=Decimal("1"),
                source="v1_connector:binance",
                fetched_at=priced_at,
                account_type="spot",
            ),
        ]
    )

    report = SourceService(store).binance_earn_history_preflight()

    assert report.status == "missing_history"
    assert report.missing_products == 1
    assert len(report.products) == 1
    product = report.products[0]
    assert product.asset == "JUP"
    assert product.account_type == "simple_earn_flexible"
    assert product.product_id == "JUP001"
    assert product.live_quantity == Decimal("40.000000000000000000")
    assert product.live_value_eur == Decimal("8.000000000000000000000000000")
    assert product.import_status == "missing"
    assert product.required_movements == ["subscription", "redemption", "reward"]
    assert product.api_probe_payload["connector_id"] == "binance"


def test_binance_earn_history_preflight_api(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    response = TestClient(create_app(store)).get("/api/v1/sources/binance/earn-history-preflight")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source_id"] == "binance"
    assert data["status"] == "no_live_earn_products"


def test_source_reconciliation_filters_decimal_dust_ledger_rows(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                source_ref="dust-1",
                event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("0.000000000000000003"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                source_ref="eur-1",
                event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="EUR",
                quantity=Decimal("1"),
                account="Spot",
            ),
        ]
    )
    BalanceLedgerBuilder(store).rebuild()

    breakdown = SourceService(store).reconciliation_breakdown("binance")

    assert breakdown is not None
    assert [row.asset for row in breakdown.rows] == ["EUR"]


def test_binance_reconciliation_marks_small_product_delta_as_reconciled_with_dust(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    priced_at = datetime(2026, 5, 30, tzinfo=timezone.utc)
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="binance-ledger.csv",
        content=(
            "time,asset,amount,type,account\n"
            "2026-05-29T00:00:00Z,SOL,10,deposit,Spot\n"
            "2026-05-29T00:00:00Z,BONK,200,deposit,Funding\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("70"),
            priced_at=priced_at,
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="BONK",
            price_eur=Decimal("0.000005"),
            priced_at=priced_at,
            source="manual-test",
        )
    )
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="binance:SOL:locked",
                connector_id="binance",
                asset="SOL",
                quantity=Decimal("10.01"),
                source="v1_connector:binance",
                fetched_at=datetime.now(timezone.utc),
                account_type="simple_earn_locked",
                product_id="Sol*120",
            )
        ]
    )

    overview_source = next(source for source in SourceService(store).overview().sources if source.label == "Binance")
    detail = SourceService(store).detail("binance")
    breakdown = SourceService(store).reconciliation_breakdown("binance")

    assert overview_source.open_reconciliation_issues == 0
    assert detail is not None
    assert detail.reconciliation.status == "reconciled_with_dust"
    assert detail.reconciliation.severity == "ok"
    assert breakdown is not None
    assert breakdown.status == "reconciled_with_dust"
    assert breakdown.severity == "info"
    rows = {row.asset: row for row in breakdown.rows}
    assert overview_source.current_status == "reconciled_with_dust"
    assert rows["SOL"].status == "dust_delta"
    assert rows["BONK"].status == "ledger_only_dust"


def test_source_overview_documents_bitget_complete_export_dust_delta(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="bitget",
        filename="bitget-ledger.csv",
        content=(
            "time,asset,amount,type,account\n"
            "2024-12-12T09:28:15Z,USDT,7.945994569,deposit,bitget\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    priced_at = datetime(2026, 5, 30, tzinfo=timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.8587904019434827"),
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
                fetched_at=datetime.now(timezone.utc),
            )
        ]
    )

    bitget = next(source for source in SourceService(store).overview().sources if source.label == "Bitget")
    detail = SourceService(store).detail("bitget")

    assert bitget.open_reconciliation_issues == 0
    assert bitget.current_status == "complete_export_strategy_reference_live_zero"
    assert detail is not None
    assert detail.reconciliation.status == "complete_export_strategy_reference_live_zero"
    assert detail.reconciliation.severity == "info"
    breakdown = SourceService(store).reconciliation_breakdown("bitget")
    assert breakdown is not None
    assert breakdown.severity == "info"
    assert breakdown.rows[0].status == "complete_export_strategy_reference_live_zero"
    assert breakdown.rows[0].severity == "info"


def test_source_overview_ignores_non_valued_live_receipt_tokens(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="binance-ledger.csv",
        content="time,asset,amount,type,account\n2026-05-29T00:00:00Z,JUP,1,deposit,Spot\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    priced_at = datetime(2026, 5, 30, tzinfo=timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("0.2"),
            priced_at=priced_at,
            source="manual-test",
        )
    )
    live_at = datetime.now(timezone.utc)
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
        ]
    )

    binance = next(source for source in SourceService(store).overview().sources if source.label == "Binance")

    assert binance.value_eur == Decimal("2.0")
    assert binance.open_price_issues == 0
    assert [asset.asset for asset in binance.top_assets] == ["JUP"]


def test_jup_source_overview_marks_reconciled_live_anchor(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = PortfolioService.KNOWN_JUP_WALLET
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="jup.csv",
        content=(
            "time,asset,amount,type,account\n"
            f"2026-01-01T00:00:00Z,JUP,10,deposit,{wallet}\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    fetched_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("1"),
            priced_at=fetched_at,
            source="manual-test",
        )
    )
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="jup_wallet:JUP:test",
                connector_id="jup_wallet",
                asset="JUP",
                quantity=Decimal("10"),
                source="solscan_pro:/account/portfolio",
                fetched_at=fetched_at,
            )
        ]
    )

    overview = SourceService(store).overview()
    jup = next(source for source in overview.sources if source.label == "Jup Wallet GmHY...3yu")

    assert jup.current_status == "live_anchor_reconciled"
    assert jup.open_reconciliation_issues == 0
    assert jup.delta_value_eur == Decimal("0E-36")
    assert jup.live_age_days is not None
    assert jup.live_age_days > SourceService.LIVE_STALE_AFTER_DAYS
    assert jup.live_freshness == "stale"
    assert any(
        issue.source_id == jup.source_id and issue.issue == "stale_live_snapshot"
        for issue in overview.health.issues
    )


def test_jup_source_overview_marks_fresh_live_anchor(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = PortfolioService.KNOWN_JUP_WALLET
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="jup-fresh.csv",
        content=(
            "time,asset,amount,type,account\n"
            f"2026-06-12T00:00:00Z,JUP,10,deposit,{wallet}\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    fetched_at = datetime.now(timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("1"),
            priced_at=fetched_at,
            source="manual-test",
        )
    )
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="jup_wallet:JUP:fresh",
                connector_id="jup_wallet",
                asset="JUP",
                quantity=Decimal("10"),
                source="solscan_pro:/account/portfolio",
                fetched_at=fetched_at,
            )
        ]
    )

    overview = SourceService(store).overview()
    jup = next(source for source in overview.sources if source.label == "Jup Wallet GmHY...3yu")

    assert jup.live_age_days == 0
    assert jup.live_freshness == "fresh"


def test_source_api_routes_are_registered(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _seed_sources(store)
    app = create_app(store)
    overview_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/sources/overview"
    )
    detail_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/sources/{source_id}"
    )

    overview_response = overview_route.endpoint()
    detail_response = detail_route.endpoint("binance")

    assert overview_response.status == "ok"
    assert overview_response.data.sources[0].source_id == "binance"
    assert detail_response.status == "ok"
    assert detail_response.data.label == "Binance"


def test_connector_diagnostics_marks_missing_cex_credentials(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _seed_sources(store)

    monkeypatch.setattr(
        SourceService,
        "_cex_credential_diagnostic",
        lambda self, connector_id: {
            "status": "missing",
            "issue": "secret_rows_missing",
            "keys_present": 0,
            "keys_required": 2,
            "updated_at_latest": None,
        },
    )

    report = SourceService(store).connector_diagnostics()
    binance = next(item for item in report.diagnostics if item.connector_id == "binance")

    assert report.missing_credentials >= 1
    assert binance.status == "missing_credentials"
    assert binance.credential_status == "missing"
    assert binance.credential_issue == "secret_rows_missing"
    assert binance.last_snapshot_at is None
    assert "Secret" in report.methodology


def test_connector_diagnostics_distinguishes_decrypt_failed_credentials(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _seed_sources(store)
    updated_at = datetime(2026, 5, 6, tzinfo=timezone.utc)

    monkeypatch.setattr(
        SourceService,
        "_cex_credential_diagnostic",
        lambda self, connector_id: {
            "status": "decrypt_failed",
            "issue": "secret_rows_present_but_empty_after_decrypt",
            "keys_present": 2,
            "keys_required": 2,
            "updated_at_latest": updated_at,
        },
    )

    report = SourceService(store).connector_diagnostics()
    binance = next(item for item in report.diagnostics if item.connector_id == "binance")

    assert report.missing_credentials >= 1
    assert binance.status == "credential_decrypt_failed"
    assert binance.credential_status == "decrypt_failed"
    assert binance.credential_keys_present == 2
    assert binance.credential_keys_required == 2
    assert binance.credential_updated_at_latest == updated_at
    assert "Master-Key" in binance.next_action


def test_connector_diagnostics_reports_fresh_wallet_snapshot(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _seed_sources(store)
    fetched_at = datetime.now(timezone.utc)
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="solana_wallet:SOL:fresh",
                connector_id="solana_wallet",
                asset="SOL",
                quantity=Decimal("2"),
                source="solscan_pro:/account/portfolio",
                fetched_at=fetched_at,
            )
        ]
    )
    monkeypatch.setattr(
        SourceService,
        "_cex_credential_diagnostic",
        lambda self, connector_id: {
            "status": "missing",
            "issue": "secret_rows_missing",
            "keys_present": 0,
            "keys_required": 2,
            "updated_at_latest": None,
        },
    )

    report = SourceService(store).connector_diagnostics()
    solana = next(item for item in report.diagnostics if item.connector_id == "solana_wallet")

    assert solana.status == "fresh"
    assert solana.credential_status == "not_required"
    assert solana.last_snapshot_age_days == 0
    assert solana.last_snapshot_assets == 1


def test_connector_diagnostics_keeps_latest_api_failure_visible(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _seed_sources(store)
    stale_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    attempted_at = datetime.now(timezone.utc)
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="pionex:USDT:stale-before-error",
                connector_id="pionex",
                asset="USDT",
                quantity=Decimal("1"),
                source="pionex_api_v2",
                fetched_at=stale_at,
            )
        ]
    )
    with store.connect() as con:
        con.execute(
            """
            insert into portfolio_live_connector_runs (
                run_id, connector_id, fetched_at, status, snapshots_count,
                source, message
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                "pionex-expired-key-test",
                "pionex",
                attempted_at,
                "connector_error",
                0,
                "pionex_api_v2",
                "V2-pionex-Liveabruf fehlgeschlagen: APIKEY_EXPIRED",
            ],
        )
    monkeypatch.setattr(
        SourceService,
        "_cex_credential_diagnostic",
        lambda self, connector_id: {
            "status": "configured",
            "issue": None,
            "keys_present": 2,
            "keys_required": 2,
            "updated_at_latest": attempted_at,
        },
    )

    report = SourceService(store).connector_diagnostics()
    pionex = next(
        item for item in report.diagnostics if item.connector_id == "pionex"
    )

    assert report.failed_latest_attempts == 1
    assert pionex.status == "connector_error"
    assert pionex.last_attempt is not None
    assert pionex.last_attempt.status == "connector_error"
    assert pionex.last_attempt.snapshots_count == 0
    assert "APIKEY_EXPIRED" in pionex.message
    assert "API-Key/Secret" in pionex.next_action
    assert pionex.last_snapshot_at == stale_at.replace(tzinfo=None)


def test_connector_diagnostics_api_route_is_registered(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _seed_sources(store)
    monkeypatch.setattr(
        SourceService,
        "_cex_credential_diagnostic",
        lambda self, connector_id: {
            "status": "missing",
            "issue": "secret_rows_missing",
            "keys_present": 0,
            "keys_required": 2,
            "updated_at_latest": None,
        },
    )
    app = create_app(store)
    route = next(
        item
        for item in app.routes
        if getattr(item, "path", None) == "/api/v1/sources/connector-diagnostics"
    )

    response = route.endpoint()

    assert response.status == "ok"
    assert response.data.missing_credentials >= 1
    assert any(item.connector_id == "binance" for item in response.data.diagnostics)
