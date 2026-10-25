import base64
from decimal import Decimal
from io import BytesIO

import pandas as pd

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.file_raw_importer import FileRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer


def _xlsx_base64(rows: list[dict[str, object]]) -> str:
    buffer = BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _multi_sheet_xlsx_base64(sheets: dict[str, list[dict[str, object]]]) -> str:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer) as writer:
        for sheet_name, rows in sheets.items():
            pd.DataFrame(rows).to_excel(writer, sheet_name=sheet_name, index=False)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _single_column_xlsx_base64(lines: list[str]) -> str:
    buffer = BytesIO()
    pd.DataFrame(lines).to_excel(buffer, index=False, header=False)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def test_excel_preview_maps_columns_without_persisting(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    importer = FileRawImporter(CsvRawImporter(store))

    preview = importer.preview_base64(
        source="helium",
        filename="helium.xlsx",
        content_base64=_xlsx_base64(
            [
                {
                    "timestamp": "2021-06-01T00:00:00Z",
                    "token": "HNT",
                    "amount": 1.25,
                    "type": "Reward",
                }
            ]
        ),
    )

    assert preview.can_import is True
    assert preview.file_format == "xlsx"
    assert preview.sheet_name == "Sheet1"
    assert preview.sheet_names == ["Sheet1"]
    assert preview.row_count == 1
    assert preview.matched_columns["time"] == "timestamp"
    assert preview.matched_columns["asset"] == "token"
    assert preview.matched_columns["quantity"] == "amount"
    assert store.list_import_batches() == []


def test_csv_preview_prefers_semicolon_header_over_decimal_commas(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    importer = FileRawImporter(CsvRawImporter(store))
    content = (
        "block;date;type;transaction_hash;hnt_amount;hnt_fee;mobile_amount;usd_oracle_price;usd_amount;usd_fee;payer;payee\n"
        "101;12.05.2021 09:13;rewards_v1;hash-1;0,00711018;0;0;18,8;0,13;0;payer-1;payee-1\n"
    )

    preview = importer.preview_base64(
        source="helium",
        filename="helium-raw.csv",
        content_base64=base64.b64encode(content.encode("utf-8")).decode("ascii"),
    )

    assert preview.can_import is True
    assert preview.columns[:4] == ["block", "date", "type", "transaction_hash"]
    assert preview.matched_columns["quantity"] == "hnt_amount"
    assert preview.missing_required_groups == []


def test_csv_preview_detects_bitget_header_below_title_row(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    importer = FileRawImporter(CsvRawImporter(store))
    content = (
        "Deposit-Withdrawal History,,,,,,,,,,,,,,,\n"
        "Order no.,UID,Transaction hash(txid),Coin,Network,Quantity,Amount in USDT,Withdrawal fee,Withdrawal fee in USDT,Type,Sub category,From address,To address,Status,Timestamp UTC+8 (Submission),Timestamp UTC+8 (Completion)\n"
        "'1149662704676515840,operator-reference,tx-1,USDT,SOL,55,55,0,0,Deposit,chain,-,to,Successful,2024-03-07 23:54:29,2024-03-07 23:54:40\n"
    )

    preview = importer.preview_base64(
        source="bitget",
        filename="Deposit-Withdrawal History.csv",
        content_base64=base64.b64encode(content.encode("utf-8")).decode("ascii"),
    )

    assert preview.can_import is True
    assert preview.columns[:4] == ["Order no.", "UID", "Transaction hash(txid)", "Coin"]
    assert preview.row_count == 1
    assert preview.matched_columns["time"] == "Timestamp UTC+8 (Completion)"
    assert preview.matched_columns["quantity"] == "Quantity"


def test_solana_rpc_normalizer_preserves_swap_and_transfer_direction(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_rows(
        source="solana_rpc",
        filename="v1-solana-rpc.json",
        file_hash="test-solana-rpc",
        rows=[
            {
                "timestamp_utc": "2024-03-11T08:53:42+00:00",
                "event_type": "swap_out_aggregated",
                "asset": "SOL",
                "quantity": "4.683251153",
                "side": "out",
                "tx_id": "tx-swap",
                "wallet_address": "wallet-1",
                "fee": "0.000105",
                "fee_asset": "SOL",
            },
            {
                "timestamp_utc": "2024-03-11T08:53:42+00:00",
                "event_type": "swap_in_aggregated",
                "asset": "ZEUS",
                "quantity": "13582.984397",
                "side": "in",
                "tx_id": "tx-swap",
                "wallet_address": "wallet-1",
            },
            {
                "timestamp_utc": "2024-03-12T17:25:45+00:00",
                "event_type": "sol_transfer",
                "asset": "SOL",
                "quantity": "57.910526716",
                "side": "out",
                "tx_id": "tx-transfer",
                "wallet_address": "wallet-1",
            },
        ],
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    by_asset = {event.asset: event for event in events if event.tx_id == "tx-swap"}
    by_tx = {event.tx_id: event for event in events if event.tx_id == "tx-transfer"}
    assert by_asset["SOL"].event_type == "unknown"
    assert by_asset["SOL"].quantity == Decimal("0")
    assert by_asset["SOL"].quote_asset is None
    assert by_asset["SOL"].quote_quantity is None
    assert by_asset["SOL"].fee_asset == "SOL"
    assert by_asset["SOL"].fee_quantity == Decimal("0.000105")
    assert by_asset["ZEUS"].event_type == "trade"
    assert by_asset["ZEUS"].quantity == Decimal("13582.984397")
    assert by_asset["ZEUS"].quote_asset == "SOL"
    assert by_asset["ZEUS"].quote_quantity == Decimal("4.683251153")
    assert by_tx["tx-transfer"].event_type == "transfer"
    assert by_tx["tx-transfer"].quantity == Decimal("-57.910526716")
    assert by_tx["tx-transfer"].account == "wallet-1"


def test_solana_rpc_positive_token_transfer_creates_income_lot(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_rows(
        source="solana_rpc",
        filename="v1-solana-rpc.json",
        file_hash="test-solana-rpc-token-transfer",
        rows=[
            {
                "timestamp_utc": "2024-04-28T14:00:00+00:00",
                "event_type": "token_transfer",
                "asset": "MANEKI",
                "quantity": "7445.66318",
                "side": "in",
                "tx_id": "tx-token-in",
                "wallet_address": "wallet-1",
            },
            {
                "timestamp_utc": "2024-11-17T14:00:00+00:00",
                "event_type": "token_transfer",
                "asset": "MANEKI",
                "quantity": "5945.66318",
                "side": "out",
                "tx_id": "tx-token-out",
                "wallet_address": "wallet-1",
            },
        ],
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    by_tx = {event.tx_id: event for event in events}
    assert by_tx["tx-token-in"].event_type == "income"
    assert by_tx["tx-token-in"].quantity == Decimal("7445.66318")
    assert by_tx["tx-token-out"].event_type == "transfer"
    assert by_tx["tx-token-out"].quantity == Decimal("-5945.66318")


def test_solana_rpc_token_transfer_pair_with_same_tx_creates_trade(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_rows(
        source="solana_rpc",
        filename="v1-solana-rpc.json",
        file_hash="test-solana-rpc-transfer-pair",
        rows=[
            {
                "timestamp_utc": "2024-11-21T05:07:51+00:00",
                "event_type": "token_transfer",
                "asset": "USDC",
                "quantity": "11289.078251",
                "side": "out",
                "tx_id": "tx-usdc-sol-swap",
                "wallet_address": "wallet-1",
            },
            {
                "timestamp_utc": "2024-11-21T05:07:51+00:00",
                "event_type": "sol_transfer",
                "asset": "SOL",
                "quantity": "46.502478086",
                "side": "in",
                "tx_id": "tx-usdc-sol-swap",
                "wallet_address": "wallet-1",
            },
        ],
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    sol = next(event for event in events if event.asset == "SOL")
    usdc = next(event for event in events if event.asset == "USDC")
    assert sol.event_type == "trade"
    assert sol.quantity == Decimal("46.502478086")
    assert sol.quote_asset == "USDC"
    assert sol.quote_quantity == Decimal("11289.078251")
    assert usdc.event_type == "unknown"
    assert usdc.quantity == Decimal("0")


def test_solana_rpc_new_claim_token_transfer_is_not_merged_to_trade(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_rows(
        source="solana_rpc",
        filename="jup-claim-2024.json",
        file_hash="test-solana-rpc-jup-new-claim",
        rows=[
            {
                "timestamp_utc": "2024-04-28T19:09:21+00:00",
                "event_type": "token_transfer",
                "asset": "JUP",
                "quantity": "1200",
                "side": "in",
                "tx_id": "tx-jup-new-claim",
                "wallet_address": "wallet-1",
                "defi_label": "lp",
                "logMessages": [
                    "Program log: Instruction: NewClaim",
                    "Program log: Created new claim with locked 0 and 1200000000 unlocked",
                ],
            },
            {
                "timestamp_utc": "2024-04-28T19:09:21+00:00",
                "event_type": "sol_transfer",
                "asset": "SOL",
                "quantity": "0.001622447",
                "side": "out",
                "tx_id": "tx-jup-new-claim",
                "wallet_address": "wallet-1",
            },
        ],
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    jup = next(event for event in events if event.asset == "JUP")
    sol = next(event for event in events if event.asset == "SOL")
    assert jup.event_type == "income"
    assert jup.quantity == Decimal("1200")
    assert jup.quote_asset is None
    assert jup.quote_quantity is None
    assert sol.event_type == "transfer"
    assert sol.quantity == Decimal("-0.001622447")


def test_solana_rpc_helium_staking_token_transfer_is_reward_not_trade(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_rows(
        source="solana_rpc",
        filename="helium-staking-claim-2024.json",
        file_hash="test-solana-rpc-helium-staking-reward",
        rows=[
            {
                "timestamp_utc": "2024-01-18T01:28:25+00:00",
                "event_type": "token_transfer",
                "asset": "IOT",
                "quantity": "164.879512",
                "side": "in",
                "tx_id": "tx-iot-staking-reward",
                "wallet_address": "wallet-1",
                "defi_label": "staking",
            },
            {
                "timestamp_utc": "2024-01-18T01:28:25+00:00",
                "event_type": "sol_transfer",
                "asset": "SOL",
                "quantity": "0.000005001",
                "side": "out",
                "tx_id": "tx-iot-staking-reward",
                "wallet_address": "wallet-1",
                "defi_label": "staking",
                "fee": "0.000005001",
                "fee_asset": "SOL",
            },
        ],
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    iot = next(event for event in events if event.asset == "IOT")
    sol = next(event for event in events if event.asset == "SOL")
    assert iot.event_type == "reward"
    assert iot.quantity == Decimal("164.879512")
    assert iot.quote_asset is None
    assert iot.quote_quantity is None
    assert sol.event_type == "transfer"
    assert sol.quantity == Decimal("-0.000005001")


def test_solana_rpc_swap_with_sol_dust_uses_stable_quote(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_rows(
        source="solana_rpc",
        filename="solscan-jup-mixed.json",
        file_hash="test-solana-rpc-mixed-dust",
        rows=[
            {
                "timestamp_utc": "2026-03-12T19:51:48+00:00",
                "event_type": "token_transfer",
                "asset": "HNT",
                "quantity": "86.67080219",
                "side": "in",
                "tx_id": "tx-hnt-usdc-with-sol-dust",
                "wallet_address": "wallet-1",
            },
            {
                "timestamp_utc": "2026-03-12T19:51:48+00:00",
                "event_type": "token_transfer",
                "asset": "USDC",
                "quantity": "100",
                "side": "out",
                "tx_id": "tx-hnt-usdc-with-sol-dust",
                "wallet_address": "wallet-1",
            },
            {
                "timestamp_utc": "2026-03-12T19:51:48+00:00",
                "event_type": "sol_transfer",
                "asset": "SOL",
                "quantity": "0.00203928",
                "side": "out",
                "tx_id": "tx-hnt-usdc-with-sol-dust",
                "wallet_address": "wallet-1",
            },
        ],
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    hnt = next(event for event in events if event.asset == "HNT")
    usdc = next(event for event in events if event.asset == "USDC")
    sol = next(event for event in events if event.asset == "SOL")
    assert hnt.event_type == "trade"
    assert hnt.quantity == Decimal("86.67080219")
    assert hnt.quote_asset == "USDC"
    assert hnt.quote_quantity == Decimal("100")
    assert usdc.event_type == "unknown"
    assert usdc.quantity == Decimal("0")
    assert sol.event_type == "unknown"
    assert sol.quantity == Decimal("0")


def test_solana_rpc_swap_into_unconfigured_asset_keeps_known_asset_disposal(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_rows(
        source="solana_rpc",
        filename="v1-solana-rpc.json",
        file_hash="test-solana-rpc-unconfigured-swap",
        rows=[
            {
                "timestamp_utc": "2023-05-08T04:52:01+00:00",
                "event_type": "swap_out_aggregated",
                "asset": "HNT",
                "quantity": "74",
                "side": "out",
                "tx_id": "tx-nft-buy",
                "wallet_address": "wallet-1",
            },
            {
                "timestamp_utc": "2023-05-08T04:52:01+00:00",
                "event_type": "swap_in_aggregated",
                "asset": "DSA1VHV1GOSIM1DV5K9H7S8HCJQZEFLSG6A4WNKQGJDU",
                "quantity": "1",
                "side": "in",
                "tx_id": "tx-nft-buy",
                "wallet_address": "wallet-1",
            },
        ],
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    trade = next(event for event in events if event.event_type == "trade")
    technical = next(event for event in events if event.event_type == "unknown")
    assert trade.asset == "HNT"
    assert trade.quantity == Decimal("-74")
    assert trade.quote_asset is None
    assert trade.quote_quantity is None
    assert technical.asset == "HNT"
    assert technical.quantity == Decimal("0")


def test_solana_rpc_swap_out_of_unconfigured_asset_keeps_known_asset_income(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_rows(
        source="solana_rpc",
        filename="v1-solana-rpc.json",
        file_hash="test-solana-rpc-unconfigured-sale",
        rows=[
            {
                "timestamp_utc": "2024-04-25T10:47:12+00:00",
                "event_type": "swap_out_aggregated",
                "asset": "DVOPSYDUOU8QQWRK4K1HIPN6WTKGK2PW1CFX8KUVVR4K",
                "quantity": "1",
                "side": "out",
                "tx_id": "tx-nft-sell",
                "wallet_address": "wallet-1",
            },
            {
                "timestamp_utc": "2024-04-25T10:47:12+00:00",
                "event_type": "swap_in_aggregated",
                "asset": "HNT",
                "quantity": "800",
                "side": "in",
                "tx_id": "tx-nft-sell",
                "wallet_address": "wallet-1",
            },
        ],
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    income = next(event for event in events if event.event_type == "income")
    technical = next(event for event in events if event.event_type == "unknown")
    assert income.asset == "HNT"
    assert income.quantity == Decimal("800")
    assert income.quote_asset is None
    assert income.quote_quantity is None
    assert technical.asset == "DVOPSYDUOU8QQWRK4K1HIPN6WTKGK2PW1CFX8KUVVR4K"
    assert technical.quantity == Decimal("0")


def test_csv_preview_does_not_treat_jup_market_data_row_as_header(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    importer = FileRawImporter(CsvRawImporter(store))
    content = (
        "Created at, Transaction ID, Asset, Position, Position change, Order type, "
        "Deposit / Withdraw ($), Execution price ($), Trade size ($), Profit / Loss ($), "
        "Trade fee ($), Liquidation fee ($), Mint, Collateral, Collateral mint\n"
        "Fri Dec 06 2024 16:27:25 GMT+0000 (Coordinated Universal Time),"
        " 4bfeLE8kETYdJgaoHh6JKPxyEoJNZa6AN1z1Adj22gVCW7yvpwFFMx6KBJeHrchpqkXquTQuAi8ThrbwUZBV6Pjv,"
        " BTC, Long, Decrease, Market, 84.28, 98929.26, 5646.52, -26.21, 4.29, , BTC, BTC, BTC\n"
    )

    preview = importer.preview_base64(
        source="manual-csv",
        filename="6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP.csv",
        content_base64=base64.b64encode(content.encode("utf-8")).decode("ascii"),
    )

    assert preview.columns[:6] == [
        "Created at",
        "Transaction ID",
        "Asset",
        "Position",
        "Position change",
        "Order type",
    ]
    assert preview.row_count == 1
    assert preview.sample_rows[0]["Order type"] == "Market"


def test_excel_preview_reads_embedded_csv_sheet(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    importer = FileRawImporter(CsvRawImporter(store))

    preview = importer.preview_base64(
        source="helium",
        filename="heliumtracker.xlsx",
        content_base64=_single_column_xlsx_base64(
            [
                "Hotspot Name,Date,Mining Rewards HNT,Mining Rewards IOT,Mining Rewards MOBILE,Commissions HNT,Commissions IOT,Commissions MOBILE,HNT (USD),HNT (EUR)",
                "hotspot-1,2022-02-01,0.05843385,0.0,0.0,0.0,0.0,0.0,28.02,25.68",
            ]
        ),
    )

    assert preview.can_import is True
    assert preview.columns[:4] == [
        "Hotspot Name",
        "Date",
        "Mining Rewards HNT",
        "Mining Rewards IOT",
    ]


def test_excel_preview_detects_binance_header_below_cover_rows(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    importer = FileRawImporter(CsvRawImporter(store))
    content = _multi_sheet_xlsx_base64(
        {
            "Sheet0": [
                {"": None, "A": None, "B": "www.binance.com"},
                {"": None, "A": None, "B": "Deposit History"},
                {"": "Time", "A": "Coin", "B": "Network", "C": "Amount", "D": "Status"},
                {"": "21-12-13 15:19:15", "A": "HNT", "B": "HNT", "C": "11", "D": "Completed"},
            ]
        }
    )

    preview = importer.preview_base64(
        source="binance",
        filename="binance.xlsx",
        content_base64=content,
        sheet_name="Sheet0",
    )

    assert preview.can_import is True
    assert preview.columns[:4] == ["Time", "Coin", "Network", "Amount"]


def test_excel_import_persists_rows_for_normalization(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    importer = FileRawImporter(CsvRawImporter(store))

    batch = importer.import_base64(
        source="helium",
        filename="helium.xlsx",
        content_base64=_xlsx_base64(
            [
                {
                    "timestamp": "2021-06-01T00:00:00Z",
                    "token": "HNT",
                    "amount": 1.25,
                    "type": "Reward",
                    "wallet": "wallet-1",
                }
            ]
        ),
    )
    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert batch.raw_object_count == 1
    assert len(events) == 1
    assert events[0].event_type == "mining"
    assert events[0].asset == "HNT"


def test_excel_preview_can_select_non_first_sheet(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    importer = FileRawImporter(CsvRawImporter(store))
    content = _multi_sheet_xlsx_base64(
        {
            "Info": [{"note": "not transactions"}],
            "Rewards": [
                {
                    "timestamp": "2021-06-01T00:00:00Z",
                    "token": "HNT",
                    "amount": 1.25,
                    "type": "Reward",
                }
            ],
        }
    )

    first = importer.preview_base64(
        source="helium",
        filename="helium.xlsx",
        content_base64=content,
    )
    selected = importer.preview_base64(
        source="helium",
        filename="helium.xlsx",
        content_base64=content,
        sheet_name="Rewards",
    )

    assert first.sheet_names == ["Info", "Rewards"]
    assert first.sheet_name == "Info"
    assert first.can_import is False
    assert selected.sheet_name == "Rewards"
    assert selected.can_import is True
    assert selected.matched_columns["quantity"] == "amount"


def test_excel_preview_auto_selects_later_detected_binance_raw_sheet(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    importer = FileRawImporter(CsvRawImporter(store))
    content = _multi_sheet_xlsx_base64(
        {
            "Pivot": [
                {"Zeilenbeschriftungen": "Buy", "Summe von Change": 10},
            ],
            "part-00000": [
                {
                    "User_ID": "75432044",
                    "UTC_Time": "2021-02-06 21:23:58",
                    "Account": "Spot",
                    "Operation": "Buy",
                    "Coin": "BTC",
                    "Change": "0.002872",
                    "Remark": None,
                }
            ],
        }
    )

    preview = importer.preview_base64(
        source="binance",
        filename="binance-raw.xlsx",
        content_base64=content,
    )

    assert preview.can_import is True
    assert preview.sheet_name == "part-00000"
    assert preview.columns[:6] == ["User_ID", "UTC_Time", "Account", "Operation", "Coin", "Change"]


def test_excel_import_uses_selected_sheet(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    importer = FileRawImporter(CsvRawImporter(store))
    content = _multi_sheet_xlsx_base64(
        {
            "Info": [{"note": "not transactions"}],
            "Rewards": [
                {
                    "timestamp": "2021-06-01T00:00:00Z",
                    "token": "HNT",
                    "amount": 2.5,
                    "type": "Reward",
                }
            ],
        }
    )

    batch = importer.import_base64(
        source="helium",
        filename="helium.xlsx",
        content_base64=content,
        sheet_name="Rewards",
    )
    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert batch.raw_object_count == 1
    assert len(events) == 1
    assert str(events[0].quantity) == "2.5"


def test_excel_duplicate_detection_is_scoped_to_sheet(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    importer = FileRawImporter(CsvRawImporter(store))
    content = _multi_sheet_xlsx_base64(
        {
            "RewardsA": [
                {
                    "timestamp": "2021-06-01T00:00:00Z",
                    "token": "HNT",
                    "amount": 1,
                    "type": "Reward",
                }
            ],
            "RewardsB": [
                {
                    "timestamp": "2021-06-02T00:00:00Z",
                    "token": "HNT",
                    "amount": 2,
                    "type": "Reward",
                }
            ],
        }
    )

    first = importer.import_base64(
        source="helium",
        filename="helium.xlsx",
        content_base64=content,
        sheet_name="RewardsA",
    )
    duplicate = importer.import_base64(
        source="helium",
        filename="helium.xlsx",
        content_base64=content,
        sheet_name="RewardsA",
    )
    other_sheet = importer.import_base64(
        source="helium",
        filename="helium.xlsx",
        content_base64=content,
        sheet_name="RewardsB",
    )
    preview = importer.preview_base64(
        source="helium",
        filename="helium.xlsx",
        content_base64=content,
        sheet_name="RewardsA",
    )

    assert duplicate.batch_id == first.batch_id
    assert other_sheet.batch_id != first.batch_id
    assert len(store.list_import_batches()) == 2
    assert preview.duplicate_batch_id == first.batch_id
