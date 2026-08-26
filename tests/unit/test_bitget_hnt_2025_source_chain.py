from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "import_bitget_hnt_2025_fifo_source_chain_v2.py"
)
SPEC = importlib.util.spec_from_file_location(
    "import_bitget_hnt_2025_fifo_source_chain_v2",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
SCRIPT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SCRIPT
SPEC.loader.exec_module(SCRIPT)

FULL_IMPORT_SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "import_bitget_2025_blockpit_account_history_v2.py"
)
FULL_IMPORT_SPEC = importlib.util.spec_from_file_location(
    "import_bitget_2025_blockpit_account_history_v2",
    FULL_IMPORT_SCRIPT_PATH,
)
assert FULL_IMPORT_SPEC is not None and FULL_IMPORT_SPEC.loader is not None
FULL_IMPORT_SCRIPT = importlib.util.module_from_spec(FULL_IMPORT_SPEC)
sys.modules[FULL_IMPORT_SPEC.name] = FULL_IMPORT_SCRIPT
FULL_IMPORT_SPEC.loader.exec_module(FULL_IMPORT_SCRIPT)


def _v1_evidence_db(path: Path) -> Path:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        create table source_files (
            source_file_id text primary key,
            source_name text not null,
            source_hash text not null,
            row_count integer not null,
            created_at_utc text not null
        );
        create table raw_events (
            unique_event_id text primary key,
            source_file_id text not null,
            row_index integer not null,
            payload_json text not null,
            created_at_utc text not null
        );
        """
    )
    connection.execute(
        "insert into source_files values (?, ?, ?, ?, ?)",
        ("blockpit", SCRIPT.BLOCKPIT_SOURCE, "blockpit", len(SCRIPT.SOURCE_CHAIN), "now"),
    )
    connection.execute(
        "insert into source_files values (?, ?, ?, ?, ?)",
        (
            "bitget-api",
            "bitget_api_tax_unit",
            "bitget-api",
            sum(len(spec.api_ids) for spec in SCRIPT.SOURCE_CHAIN),
            "now",
        ),
    )
    api_row_index = 0
    for row_index, source_row in enumerate(SCRIPT.SOURCE_CHAIN):
        blockpit_row = {
            "Integration Name": "Bitget",
            "Date (UTC)": source_row.blockpit_date,
            "Incoming Amount": source_row.incoming_amount,
            "Incoming Asset": source_row.incoming_asset,
            "Outgoing Amount": source_row.outgoing_amount,
            "Outgoing Asset": source_row.outgoing_asset,
            "Fee Amount (optional)": source_row.blockpit_fee,
            "Fee Asset (optional)": source_row.blockpit_fee_asset,
        }
        connection.execute(
            "insert into raw_events values (?, ?, ?, ?, ?)",
            (
                f"blockpit-{row_index}",
                "blockpit",
                row_index,
                json.dumps({"raw_row": blockpit_row}),
                "now",
            ),
        )
        for api_id in source_row.api_ids:
            connection.execute(
                "insert into raw_events values (?, ?, ?, ?, ?)",
                (
                    f"api-{api_id}",
                    "bitget-api",
                    api_row_index,
                    json.dumps(
                        {
                            "asset": "HNT",
                            "raw_row": {
                                "id": api_id,
                                "coin": "HNT",
                                "balance": source_row.balance_after,
                            },
                        }
                    ),
                    "now",
                ),
            )
            api_row_index += 1
    connection.commit()
    connection.close()
    return path


def test_bitget_hnt_source_chain_validates_v1_evidence_and_normalizes(tmp_path):
    v1_db = _v1_evidence_db(tmp_path / "v1.sqlite")
    rows = SCRIPT.prepared_rows(v1_db)

    assert len(rows) == 8
    assert rows[0]["amount"] == "989.722"
    assert rows[0]["quote_quantity"] == "3640.9995719999997"
    assert rows[3]["amount"] == "859.9208492"
    assert rows[3]["withdrawal fee"] == "0.5174198"
    assert rows[3]["address"] == SCRIPT.MAIN_WALLET
    assert rows[3]["tx_id"] == SCRIPT.BITGET_WITHDRAWAL_ONCHAIN_TX

    store = DuckDbStore(tmp_path / "v2.duckdb")
    batch = CsvRawImporter(store).import_rows(
        source="bitget",
        filename=SCRIPT.FILENAME,
        file_hash="unit-bitget-hnt-source-chain",
        rows=rows,
    )
    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 8
    buy = next(event for event in events if event.source_ref == rows[0]["source_ref"])
    withdrawal = next(
        event for event in events if event.source_ref == rows[3]["source_ref"]
    )
    deposit = next(
        event for event in events if event.source_ref == rows[4]["source_ref"]
    )
    assert buy.event_type == "trade"
    assert buy.quantity == Decimal("989.722")
    assert buy.quote_asset == "USDT"
    assert buy.quote_quantity == Decimal("3640.9995719999997")
    assert buy.fee_asset == "HNT"
    assert buy.fee_quantity == Decimal("0.989722")
    assert withdrawal.event_type == "transfer"
    assert withdrawal.quantity == Decimal("-859.9208492")
    assert withdrawal.fee_quantity == Decimal("0.5174198")
    assert withdrawal.tx_id == SCRIPT.BITGET_WITHDRAWAL_ONCHAIN_TX
    assert deposit.event_type == "transfer"
    assert deposit.quantity == Decimal("16.16462275")
    assert deposit.tx_id == SCRIPT.BITGET_DEPOSIT_ONCHAIN_TX


def test_wallet_fifo_carries_bitget_hnt_lots_to_earlier_onchain_credit(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = WalletFifoPreviewService.PRIMARY_SOLANA_WALLET
    tx_id = SCRIPT.BITGET_WITHDRAWAL_ONCHAIN_TX
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="bitget",
            filename="bitget-hnt-withdrawal-evidence.csv",
            file_hash="bitget-hnt-withdrawal-anchor",
        )
    )
    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "time": "2025-03-09T19:00:22+00:00",
                    "asset": "HNT",
                    "amount": "859.9208492",
                    "type": "withdrawal",
                    "withdrawal fee": "0.5174198",
                    "address": wallet,
                    "network": "SOL",
                    "tx_id": tx_id,
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="blockpit",
                event_time=datetime(2025, 1, 29, 5, 58, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("860.438269"),
                quote_asset="EUR",
                quote_quantity=Decimal("3000"),
                account="Bitget",
                tx_id="buy-hnt",
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2025, 3, 9, 18, 59, 51, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("859.9208492"),
                account=wallet,
                tx_id=tx_id,
            ),
            CanonicalEventCreate(
                source="blockpit",
                event_time=datetime(2025, 3, 9, 19, 0, 22, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("-859.9208492"),
                fee_asset="HNT",
                fee_quantity=Decimal("0.5174198"),
                account="Bitget",
                tx_id=tx_id,
                raw_object_id=raw.raw_object_id,
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    service = WalletFifoPreviewService(store)
    state = service.replay()
    preview = service.preview(year=2025)

    assert preview.unresolved_inbound_provenance_count == 0
    assert preview.unmatched_count == 0
    transfer = next(trace for trace in preview.transfer_traces if trace.tx_id == tx_id)
    assert transfer.status == "ok"
    assert transfer.source_pool_id == "bitget:bitget"
    assert transfer.target_pool_id == f"solana_rpc:{wallet}"
    assert transfer.quantity == Decimal("859.9208492")
    assert transfer.fee_quantity == Decimal("0.5174198")
    assert transfer.carried_cost_basis_eur > 0
    assert sum(
        lot.quantity_remaining
        for lot in state.open_lots
        if lot.pool_id == "bitget:bitget" and lot.asset == "HNT"
    ) == 0
    assert sum(
        lot.quantity_remaining
        for lot in state.open_lots
        if lot.pool_id == f"solana_rpc:{wallet}" and lot.asset == "HNT"
    ) == Decimal("859.9208492")


def test_balance_ledger_uses_explicit_bitget_eur_event_as_blockpit_quote_mirror(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="bitget-tax-api-evidence",
                event_time=datetime(
                    2025,
                    3,
                    9,
                    19,
                    0,
                    30,
                    468000,
                    tzinfo=timezone.utc,
                ),
                event_type="trade",
                asset="EUR",
                quantity=Decimal("-9.99993348"),
                account="bitget",
            ),
            CanonicalEventCreate(
                source="blockpit",
                event_time=datetime(
                    2025,
                    3,
                    9,
                    19,
                    0,
                    30,
                    tzinfo=timezone.utc,
                ),
                event_type="trade",
                asset="XRP",
                quantity=Decimal("5.0823"),
                quote_asset="EUR",
                quote_quantity=Decimal("9.99993348"),
                fee_asset="XRP",
                fee_quantity=Decimal("0.0050823"),
                account="Bitget",
            ),
        ]
    )

    BalanceLedgerBuilder(store).rebuild()
    positions = {
        (position.account.lower(), position.asset): position.quantity
        for position in BalanceLedgerBuilder(store).positions()
    }

    assert positions[("bitget", "EUR")] == Decimal("-9.99993348")
    assert positions[("bitget", "XRP")] == Decimal("5.0772177")


def test_blockpit_bitget_sell_uses_outgoing_crypto_quantity(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_rows(
        source="blockpit",
        filename="bitget-blockpit.csv",
        file_hash="bitget-sell-quantity",
        rows=[
            {
                "Integration Name": "bitget",
                "Date (UTC)": "30.01.2025 05:36:02",
                "Label": "Trade",
                "Incoming Amount": "599.999634",
                "Incoming Asset": "USDT",
                "Outgoing Amount": "140.283",
                "Outgoing Asset": "HNT",
                "Fee Amount (optional)": "0.599999634",
                "Fee Asset (optional)": "USDT",
            }
        ],
    )

    event = RawNormalizer(store).normalize_batch(batch.batch_id)[0]

    assert event.event_type == "trade"
    assert event.account == "bitget"
    assert event.asset == "HNT"
    assert event.quantity == Decimal("-140.283")
    assert event.quote_asset == "USDT"
    assert event.quote_quantity == Decimal("599.999634")


def test_blockpit_bitget_internal_movements_are_mapped_as_zero_evidence(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_rows(
        source="blockpit",
        filename="bitget-internal-blockpit.csv",
        file_hash="bitget-internal-evidence",
        rows=[
            {
                "Integration Name": "bitget",
                "Date (UTC)": "23.02.2025 14:52:35",
                "Label": "Auto-Balancing Out",
                "Outgoing Amount": "21.410532",
                "Outgoing Asset": "HNT",
            },
            {
                "Integration Name": "bitget",
                "Date (UTC)": "11.07.2025 20:07:05",
                "Label": "Non-Taxable In",
                "Incoming Amount": "27.40478646",
                "Incoming Asset": "USDT",
                "Comment (optional)": "Borrow (Margin)",
            },
        ],
    )

    events, report = RawNormalizer(store).normalize_batch_with_report(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()

    assert report.created_events == 2
    assert report.skipped_raw_objects == 0
    assert store.unmapped_raw_object_counts() == {}
    assert all(event.event_type == "unknown" for event in events)
    assert all(event.quantity == 0 for event in events)
    assert all(position.quantity == 0 for position in BalanceLedgerBuilder(store).positions())


def test_full_import_pairs_fiat_conversion_and_unmerged_trade_legs(tmp_path):
    rows = [
        {
            "Integration Name": "Bitget",
            "Date (UTC)": "23.04.2025 07:18:39",
            "Label": "Withdrawal",
            "Outgoing Amount": "1000.14",
            "Outgoing Asset": "EUR",
            "Comment (optional)": "Fiat/Crypto Conversion",
            "Trx. ID (optional)": "conversion-out",
        },
        {
            "Integration Name": "Bitget",
            "Date (UTC)": "23.04.2025 07:18:44",
            "Label": "Deposit",
            "Incoming Amount": "1127.2308",
            "Incoming Asset": "USDT",
            "Comment (optional)": "Fiat/Crypto Conversion",
            "Trx. ID (optional)": "conversion-in",
        },
        {
            "Integration Name": "Bitget",
            "Date (UTC)": "11.07.2025 20:08:09",
            "Label": "Withdrawal",
            "Outgoing Amount": "27.40478646",
            "Outgoing Asset": "USDT",
            "Comment (optional)": "Unmerged Trade (deal_out)",
            "Trx. ID (optional)": "deal-out",
        },
        {
            "Integration Name": "Bitget",
            "Date (UTC)": "11.07.2025 20:08:09",
            "Label": "Deposit",
            "Incoming Amount": "9.6438",
            "Incoming Asset": "XRP",
            "Fee Amount (optional)": "0.0096438",
            "Fee Asset (optional)": "USDT",
            "Comment (optional)": "Unmerged Trade (deal_in)",
            "Trx. ID (optional)": "deal-in",
        },
    ]
    paired = FULL_IMPORT_SCRIPT._pair_bitget_account_rows(
        rows,
        expected_fiat_conversion_pairs=1,
        expected_unmerged_trade_pairs=1,
    )

    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_rows(
        source="blockpit",
        filename="paired-bitget.csv",
        file_hash="paired-bitget",
        rows=paired,
    )
    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 4
    assert sum(event.quantity for event in events if event.event_type == "unknown") == 0
    trades = sorted(
        (event for event in events if event.event_type == "trade"),
        key=lambda event: event.event_time,
    )
    assert len(trades) == 2
    assert trades[0].asset == "USDT"
    assert trades[0].quantity == Decimal("1127.2308")
    assert trades[0].quote_asset == "EUR"
    assert trades[0].quote_quantity == Decimal("1000.14")
    assert trades[1].asset == "XRP"
    assert trades[1].quantity == Decimal("9.6438")
    assert trades[1].quote_asset == "USDT"
    assert trades[1].quote_quantity == Decimal("27.40478646")


def test_balance_ledger_matches_fiat_conversion_quote_with_five_second_evidence(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="bitget-tax-api-evidence",
                event_time=datetime(2025, 4, 23, 7, 18, 39, tzinfo=timezone.utc),
                event_type="transfer",
                asset="EUR",
                quantity=Decimal("-1000.14"),
                account="bitget",
            ),
            CanonicalEventCreate(
                source="blockpit",
                event_time=datetime(2025, 4, 23, 7, 18, 44, tzinfo=timezone.utc),
                event_type="trade",
                asset="USDT",
                quantity=Decimal("1127.2308"),
                quote_asset="EUR",
                quote_quantity=Decimal("1000.14"),
                account="bitget",
            ),
        ]
    )

    BalanceLedgerBuilder(store).rebuild()
    positions = {
        (position.account, position.asset): position.quantity
        for position in BalanceLedgerBuilder(store).positions()
    }

    assert positions[("bitget", "EUR")] == Decimal("-1000.14")
    assert positions[("bitget", "USDT")] == Decimal("1127.2308")


def test_wallet_fifo_carries_binance_usdt_to_owned_bitget_deposit_address(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    tx_id = "0xafe24daadbd2adbae1636acfffa8f45e4b8c740013509c9394c9ce0efaec6260"
    address = "0x6b007cb6d125f4aaa77b3154c6e4a8316e84bffc"
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance_withdrawal_api",
            filename="binance-withdrawal-api.csv",
            file_hash="binance-to-bitget-usdt",
        )
    )
    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "complete_time": "2025-01-29T05:56:41+00:00",
                    "coin": "USDT",
                    "amount": "5009.09824537",
                    "transaction_fee": "0",
                    "address": address,
                    "network": "BSC",
                    "tx_id": tx_id,
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="USDT",
                quantity=Decimal("5009.09824537"),
                quote_asset="EUR",
                quote_quantity=Decimal("4800"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="blockpit",
                event_time=datetime(
                    2025,
                    1,
                    29,
                    5,
                    56,
                    22,
                    tzinfo=timezone.utc,
                ),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("5009.09824537"),
                account="Bitget",
                tx_id=tx_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(
                    2025,
                    1,
                    29,
                    5,
                    56,
                    41,
                    tzinfo=timezone.utc,
                ),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("-5009.09824537"),
                account="Spot",
                raw_object_id=raw.raw_object_id,
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    preview = WalletFifoPreviewService(store).preview(year=2025)

    assert preview.unresolved_inbound_provenance_count == 0
    assert preview.unmatched_count == 0
    transfer = next(trace for trace in preview.transfer_traces if trace.tx_id == tx_id)
    assert transfer.status == "ok"
    assert transfer.source_pool_id == "binance:Spot"
    assert transfer.target_pool_id == "bitget:bitget"
    assert transfer.quantity == Decimal("5009.09824537")


def test_withdrawal_evidence_never_cross_matches_bitget_to_binance(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    tx_id = "bitget-sol-withdrawal-tx"
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="bitget",
            filename="bitget-withdrawal-api.csv",
            file_hash="provider-bound-withdrawal",
        )
    )
    store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "time": "2025-06-15T07:45:46.005000+00:00",
                    "asset": "SOL",
                    "amount": "7.0700475",
                    "address": "Ftf2dgeRpBrPFmbd4wQWWqSjCmRjGes1GzNXtxKETeLW",
                    "tx_id": tx_id,
                }
            ),
        ),
    )
    bitget_event, binance_event = store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="blockpit",
                event_time=datetime(2025, 6, 15, 7, 45, 46, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("-7.0700475"),
                account="bitget",
                tx_id=tx_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 7, 11, 8, 48, 17, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("-7.0700475"),
                account="Coin-M Futures",
            ),
        ]
    )
    service = WalletFifoPreviewService(store)

    assert service._matching_withdrawal_history(bitget_event) is not None
    assert service._matching_withdrawal_history(binance_event) is None


def test_wallet_fifo_preserves_deterministic_store_order_for_equal_timestamps(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    event_time = datetime(2025, 1, 1, tzinfo=timezone.utc)
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="blockpit",
                event_time=event_time,
                event_type="trade",
                asset="HNT",
                quantity=Decimal("1"),
                quote_asset="EUR",
                quote_quantity=Decimal("1"),
                account="bitget",
            ),
            CanonicalEventCreate(
                source="blockpit",
                event_time=event_time,
                event_type="trade",
                asset="HNT",
                quantity=Decimal("2"),
                quote_asset="EUR",
                quote_quantity=Decimal("20"),
                account="bitget",
            ),
        ]
    )
    with store.connect() as con:
        con.execute("update canonical_events set event_id = 'z-first' where quantity = 1")
        con.execute("update canonical_events set event_id = 'a-second' where quantity = 2")
    events = store.list_canonical_events()

    adjusted = WalletFifoPreviewService(store)._events_with_source_timezone_utc(events)

    assert [event.event_id for event in events] == ["z-first", "a-second"]
    assert [event.event_id for event in adjusted] == ["z-first", "a-second"]
