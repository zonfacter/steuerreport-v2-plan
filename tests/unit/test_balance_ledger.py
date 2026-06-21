from decimal import Decimal

from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


def test_balance_ledger_sums_canonical_events_by_account_and_asset(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="pionex.csv",
        content=(
            "time,coin,change,type,account\n"
            "2021-04-28T10:00:00Z,USDT,100,deposit,pionex-main\n"
            "2021-04-29T10:00:00Z,USDT,-30,withdrawal,pionex-main\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)

    entries = BalanceLedgerBuilder(store).rebuild()
    positions = BalanceLedgerBuilder(store).positions()

    assert [entry.balance_quantity for entry in entries] == [
        Decimal("100.000000000000000000"),
        Decimal("70.000000000000000000"),
    ]
    assert positions[0].account == "pionex-main"
    assert positions[0].asset == "USDT"
    assert positions[0].quantity == Decimal("70.000000000000000000")


def test_balance_ledger_books_trade_quote_and_fee_movements(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="raw-trading-details.csv",
        content=(
            "date(UTC+0),symbol,side,executed_qty,amount,fee,fee_coin,account\n"
            "2023-03-10 09:10:58,BTC_USDT,BUY,0.25,5000,0.001,BTC,pionex-main\n"
            "2023-03-11 09:10:58,BTC_USDT,SELL,0.10,2100,1.05,USDT,pionex-main\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)

    BalanceLedgerBuilder(store).rebuild()
    positions = {
        position.asset: position.quantity
        for position in BalanceLedgerBuilder(store).positions()
        if position.account == "pionex-main"
    }

    assert positions["BTC"] == Decimal("0.149000000000000000")
    assert positions["USDT"] == Decimal("-2901.050000000000000000")


def test_balance_ledger_does_not_double_book_derivative_fee_in_after_fee_cashflow(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(source="bitget", filename="Futures Financial Record.csv")
    )
    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json='{"Action (English)":"open_long","Surplus/deduction (after fee)":"-1.7","Fee":"-1.7"}',
        ),
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="bitget",
            event_time="2024-12-05T18:34:05Z",
            event_type="derivative",
            asset="USDT",
            quantity=Decimal("-1.70002224"),
            fee_asset="USDT",
            fee_quantity=Decimal("-1.70002224"),
            account="bitget",
            raw_object_id=raw.raw_object_id,
        )
    )

    entries = BalanceLedgerBuilder(store).rebuild()

    assert [(entry.asset, entry.delta_quantity, entry.balance_quantity) for entry in entries] == [
        ("USDT", Decimal("-1.700022240000000000"), Decimal("-1.700022240000000000"))
    ]


def test_balance_ledger_keeps_raw_row_order_for_same_timestamp(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(source="binance", filename="transaction-history.xlsx")
    )
    row_buy = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(row_number=10, payload_json='{"Operation":"Buy"}'),
    )
    row_fee = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(row_number=11, payload_json='{"Operation":"Fee"}'),
    )
    event_time = "2021-02-17T20:13:26Z"
    store.add_canonical_event(
        CanonicalEventCreate(
            source="binance",
            event_time=event_time,
            event_type="fee",
            asset="USDT",
            quantity=Decimal("-0.12542968"),
            account="Spot",
            raw_object_id=row_fee.raw_object_id,
        )
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="binance",
            event_time=event_time,
            event_type="trade",
            asset="USDT",
            quantity=Decimal("125.4296806"),
            account="Spot",
            raw_object_id=row_buy.raw_object_id,
        )
    )

    entries = BalanceLedgerBuilder(store).rebuild()

    assert [entry.delta_quantity for entry in entries] == [
        Decimal("125.429680600000000000"),
        Decimal("-0.125429680000000000"),
    ]
    assert [entry.balance_quantity for entry in entries] == [
        Decimal("125.429680600000000000"),
        Decimal("125.304250920000000000"),
    ]


def test_balance_ledger_zeroes_min_decimal_dust_balance(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(source="binance", filename="transaction-history.xlsx")
    )
    raw_in = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(row_number=1, payload_json='{"Operation":"Simple Earn Redemption"}'),
    )
    raw_out = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(row_number=2, payload_json='{"Operation":"Transaction Sold"}'),
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="binance",
            event_time="2024-03-09T03:38:43Z",
            event_type="income",
            asset="BTTC",
            quantity=Decimal("43511899.999999999999999999"),
            account="Spot",
            raw_object_id=raw_in.raw_object_id,
        )
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="binance",
            event_time="2024-03-09T12:56:02Z",
            event_type="trade",
            asset="USDT",
            quantity=Decimal("77.451182"),
            quote_asset="BTTC",
            quote_quantity=Decimal("43511900"),
            account="Spot",
            raw_object_id=raw_out.raw_object_id,
        )
    )

    entries = BalanceLedgerBuilder(store).rebuild()

    assert entries[-1].asset == "BTTC"
    assert entries[-1].delta_quantity == Decimal("-43511900.000000000000000000")
    assert entries[-1].balance_quantity == Decimal("0")


def test_balance_ledger_zeroes_stablecoin_sub_cent_dust_balance(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(source="solana_rpc", filename="solana-rpc.csv")
    )
    raw_in = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(row_number=1, payload_json='{"event_type":"swap_in_aggregated"}'),
    )
    raw_out = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(row_number=2, payload_json='{"event_type":"swap_in_aggregated"}'),
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="solana_rpc",
            event_time="2024-12-01T13:34:26Z",
            event_type="transfer",
            asset="USDC",
            quantity=Decimal("148.066733"),
            account="wallet-1",
            raw_object_id=raw_in.raw_object_id,
        )
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="solana_rpc",
            event_time="2024-12-01T13:35:14Z",
            event_type="trade",
            asset="USDT",
            quantity=Decimal("146.699985"),
            quote_asset="USDC",
            quote_quantity=Decimal("148.066735"),
            account="wallet-1",
            raw_object_id=raw_out.raw_object_id,
        )
    )

    entries = BalanceLedgerBuilder(store).rebuild()

    usdc_entries = [entry for entry in entries if entry.asset == "USDC"]
    assert usdc_entries[-1].delta_quantity == Decimal("-148.066735000000000000")
    assert usdc_entries[-1].balance_quantity == Decimal("0")


def test_balance_ledger_merges_unique_truncated_wallet_account_alias(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = "1362Z4gXFbBuUp22PtwNhdNc3iR6Tjc7ty5S8CPjSwVH6F7BsHV"
    short_wallet = "133iWieuw...xU6WUW8v"
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="wallets.csv",
        content=(
            "time,asset,amount,type,account\n"
            f"2024-01-01T00:00:00Z,HNT,10,deposit,{wallet}\n"
            f"2024-01-02T00:00:00Z,HNT,2,deposit,{short_wallet} \n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)

    BalanceLedgerBuilder(store).rebuild()
    positions = BalanceLedgerBuilder(store).positions()

    assert len(positions) == 1
    assert positions[0].account == wallet
    assert positions[0].asset == "HNT"
    assert positions[0].quantity == Decimal("12.000000000000000000")


def test_balance_ledger_uses_full_wallet_from_raw_transfer_payload_for_alias(tmp_path):
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
                + '","Amount":"10","Coin":"HNT","TXID":"not-an-account"}'
            ),
        ),
    )
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="wallets.csv",
        content=(
            "time,asset,amount,type,account\n"
            f"2024-01-01T00:00:00Z,HNT,10,deposit,{short_wallet}\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)

    BalanceLedgerBuilder(store).rebuild()
    positions = BalanceLedgerBuilder(store).positions()

    assert positions[0].account == wallet
    assert positions[0].quantity == Decimal("10.000000000000000000")
