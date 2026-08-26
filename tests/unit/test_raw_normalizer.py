from datetime import datetime, timezone
from decimal import Decimal
import json

from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer


def test_normalize_batch_creates_canonical_events(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="pionex.csv",
        content="time,coin,change,type\n2021-04-28T10:00:00Z,USDT,100,deposit\n",
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].source == "pionex"
    assert events[0].event_type == "transfer"
    assert events[0].asset == "USDT"
    assert events[0].quantity == Decimal("100")
    assert events[0].raw_object_id is not None


def test_normalize_batch_skips_incomplete_rows(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="unknown",
        filename="broken.csv",
        content="time,asset,note\n2021-01-01T00:00:00Z,BTC,no amount\n",
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert events == []
    assert store.list_canonical_events(batch.batch_id) == []


def test_normalize_batch_report_counts_skipped_rows(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="mixed.csv",
        content=(
            "time,asset,amount,type,note\n"
            "2021-01-01T00:00:00Z,BTC,1,deposit,ok\n"
            "2021-01-02T00:00:00Z,ETH,,deposit,missing amount\n"
        ),
    )

    events, report = RawNormalizer(store).normalize_batch_with_report(batch.batch_id)

    assert len(events) == 1
    assert report.raw_objects == 2
    assert report.created_events == 1
    assert report.skipped_raw_objects == 1
    assert store.unmapped_raw_object_counts()[batch.batch_id] == 1


def test_binance_profile_maps_utc_time_operation_and_change(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="binance.csv",
        content=(
            "UTC Time,Operation,Coin,Change,Remark\n"
            "2021-04-28 10:00:00,Buy,BTC,+0.5,order-1\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "trade"
    assert events[0].asset == "BTC"
    assert events[0].quantity == Decimal("+0.5")
    assert events[0].account == "binance"


def test_binance_filename_timezone_is_converted_to_utc(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="Binance-Transaction-History-202605061835(UTC+2)_test.csv",
        content=(
            "Time,Account,Operation,Coin,Change,Remark\n"
            "21-12-25 18:22:42,Spot,Withdraw,USDT,-201,Withdraw fee is included\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert events[0].event_time == datetime(2021, 12, 25, 16, 22, 42, tzinfo=timezone.utc)


def test_binance_timezone_column_is_converted_to_utc(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="binance.csv",
        content=(
            "Date(UTC+2),Account,Operation,Coin,Change\n"
            "2022-01-19 14:52:45,Spot,Withdraw,USDT,-1246.38419\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert events[0].event_time == datetime(2022, 1, 19, 12, 52, 45, tzinfo=timezone.utc)


def test_binance_withdrawal_api_normalizes_as_zero_quantity_evidence(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_rows(
        source="binance_withdrawal_api",
        filename="binance-withdrawal-api.json",
        file_hash="withdrawal-api",
        rows=[
            {
                "record_type": "capital_withdrawal_evidence",
                "asset": "JUP",
                "amount": "5530.555703",
                "transaction_fee": "1.72",
                "gross_amount": "5532.275703",
                "complete_time": "2025-03-23 13:49:42",
                "address": "G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY",
                "network": "SOL",
                "tx_id": "withdraw-tx",
                "source_ref": "withdraw-id",
            }
        ],
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].source == "binance_withdrawal_api"
    assert events[0].event_type == "unknown"
    assert events[0].asset == "JUP"
    assert events[0].quantity == Decimal("0")
    assert events[0].tx_id == "withdraw-tx"
    assert events[0].source_ref == "withdraw-id"
    assert events[0].account == "Binance Withdrawal Evidence"


def test_binance_scaled_legacy_export_prefers_decimal_remark(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="scaled-binance.csv",
        content=(
            "User_ID,UTC_Time,Account,Operation,Coin,Change,Remark\n"
            "75432044,2021-02-06 21:18:00,Spot,Deposit,EUR,9810000000,98.1\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "transfer"
    assert events[0].asset == "EUR"
    assert events[0].quantity == Decimal("98.1")


def test_helium_profile_treats_reward_as_mining(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="fairspot.csv",
        content=(
            "timestamp,token,amount,type,transaction hash,wallet\n"
            "2021-06-01T00:00:00Z,HNT,1.25,Reward,abc123,wallet-1\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "mining"
    assert events[0].asset == "HNT"
    assert events[0].quantity == Decimal("1.25")
    assert events[0].tx_id == "abc123"
    assert events[0].account == "wallet-1"


def test_helium_cointracking_export_maps_buy_amount_and_hnt2_alias(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="fairspot-cointracking.csv",
        content=(
            "type,buyAmount,buyCurrency,date,txId,buyValueUSD\n"
            "Mining,0.28617728,HNT2,2025-01-04T08:32:56+00:00,tx-101,71.04\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "mining"
    assert events[0].asset == "HNT"
    assert events[0].quantity == Decimal("0.28617728")
    assert events[0].tx_id == "tx-101"


def test_helium_raw_export_derives_hnt_quantity_and_transaction_hash(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    main_wallet = RawNormalizer.HELIUM_MAIN_LEGACY_WALLET
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="helium-raw.csv",
        content=(
            "block;date;type;transaction_hash;hnt_amount;hnt_fee;mobile_amount;usd_oracle_price;usd_amount;usd_fee;payer;payee\n"
            "101;12.05.2021 09:13;rewards_v1;hash-1;0,00711018;0;0;18,8;0,13;0;;\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "mining"
    assert events[0].asset == "HNT"
    assert events[0].quantity == Decimal("0.00711018")
    assert events[0].tx_id == "hash-1"
    assert events[0].account == main_wallet


def test_helium_documented_staking_return_is_split_into_principal_and_reward(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    main_wallet = RawNormalizer.HELIUM_MAIN_LEGACY_WALLET
    tx_id = "staking-return-tx"
    content = (
        "block;date;type;transaction_hash;hnt_amount;hnt_fee;mobile_amount;"
        "usd_oracle_price;usd_amount;usd_fee;payer;payee\n"
        f"1684084;31.12.2022 21:57;payment_v2;{tx_id};73,9345895;0;0;"
        f"1,52;112,38;0;staking-wallet;{main_wallet}\n"
    )
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="helium-main.csv",
        content=content,
    )
    config_path = tmp_path / "fairspot-staking.json"
    config_path.write_text(
        json.dumps(
            {
                "review_status": "approved_evidence_overlay",
                "main_wallet": main_wallet,
                "primary_source": {"file_hash": batch.file_hash},
                "return_splits": [
                    {
                        "tx_id": tx_id,
                        "received_quantity": "73.9345895",
                        "principal_quantity": "56.2836845",
                        "reward_quantity": "17.650905",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    normalizer = RawNormalizer(
        store,
        fairspot_staking_config_path=config_path,
    )

    first = normalizer.normalize_batch(batch.batch_id)
    second = normalizer.normalize_batch(batch.batch_id)

    assert len(first) == 2
    assert {event.event_type for event in first} == {"transfer", "reward"}
    principal = next(event for event in first if event.event_type == "transfer")
    reward = next(event for event in first if event.event_type == "reward")
    assert principal.quantity == Decimal("56.2836845")
    assert reward.quantity == Decimal("17.650905")
    assert principal.quantity + reward.quantity == Decimal("73.9345895")
    assert principal.tx_id == reward.tx_id == tx_id
    assert {event.event_id for event in first} == {event.event_id for event in second}


def test_helium_raw_export_derives_legacy_scientific_hnt_before_mobile_column(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="helium-raw.csv",
        content=(
            "block;date;type;transaction_hash;hnt_amount;hnt_fee;mobile_amount;usd_oracle_price;usd_amount;usd_fee;payer;payee\n"
            "845277;26.07.2021 23:37;rewards_v1;hash-legacy;8,7e.7;0;11,507715;0;;0;payer-1;payee-1\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "mining"
    assert events[0].asset == "HNT"
    assert events[0].quantity == Decimal("8.7E-7")
    assert events[0].tx_id == "hash-legacy"


def test_helium_raw_export_derives_mobile_when_hnt_is_zero(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="helium-raw.csv",
        content=(
            "block;date;type;transaction_hash;hnt_amount;mobile_amount;payee\n"
            "102;12.05.2023 09:13;rewards_v1;hash-2;0;1234,5;wallet-1\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "mining"
    assert events[0].asset == "MOBILE"
    assert events[0].quantity == Decimal("1234.5")


def test_solana_rpc_helium_reward_instruction_maps_incoming_hnt_to_reward(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_rows(
        source="solana_rpc",
        filename="solana-hnt-reward.json",
        file_hash="solana-hnt-reward",
        rows=[
            {
                "timestamp_utc": "2026-06-19T21:40:23+00:00",
                "event_type": "token_transfer",
                "asset": "HNT",
                "quantity": "3.488129",
                "side": "in",
                "tx_id": "reward-tx",
                "wallet_address": "G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY",
                "logMessages": [
                    "Program log: Instruction: SetCurrentRewardsWrapperV1",
                    "Program log: Instruction: SetCurrentRewardsV0",
                    "Program log: Instruction: DistributeCompressionRewardsV0",
                ],
            },
            {
                "timestamp_utc": "2026-06-19T21:41:00+00:00",
                "event_type": "token_transfer",
                "asset": "HNT",
                "quantity": "1",
                "side": "in",
                "tx_id": "normal-transfer-tx",
                "wallet_address": "G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY",
                "logMessages": ["Program log: Instruction: TransferChecked"],
            },
        ],
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    by_tx = {event.tx_id: event for event in events}
    assert by_tx["reward-tx"].event_type == "reward"
    assert by_tx["reward-tx"].quantity == Decimal("3.488129")
    assert by_tx["normal-transfer-tx"].event_type == "income"


def test_solana_documented_staking_return_is_split_into_principal_and_reward(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = RawNormalizer.HELIUM_MAIN_LEGACY_WALLET
    tx_id = "solana-staking-return"
    file_hash = "sha256:solana-staking-return"
    batch = CsvRawImporter(store).import_rows(
        source="solana_rpc",
        filename="solana-staking.json",
        file_hash=file_hash,
        rows=[
            {
                "timestamp_utc": "2026-01-02T04:18:08Z",
                "event_type": "transfer",
                "asset": "SHARK",
                "quantity": "963.536668",
                "side": "in",
                "tx_id": tx_id,
                "wallet_address": wallet,
                "movement_classification": "defi_position_transfer",
                "classification_reason": "position_withdraw_instruction",
            }
        ],
    )
    config_path = tmp_path / "solana-staking.json"
    config_path.write_text(
        json.dumps(
            {
                "review_status": "approved_evidence_overlay",
                "positions": [
                    {
                        "wallet": wallet,
                        "asset": "SHARK",
                        "position_return": {
                            "tx_id": tx_id,
                            "source_file_hash": file_hash,
                            "received_quantity": "963.536668",
                            "principal_quantity": "677.465346",
                            "reward_quantity": "286.071322",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    normalizer = RawNormalizer(
        store,
        solana_staking_config_path=config_path,
    )

    first = normalizer.normalize_batch(batch.batch_id)
    second = normalizer.normalize_batch(batch.batch_id)

    principal = next(event for event in first if event.event_type == "transfer")
    reward = next(event for event in first if event.event_type == "reward")
    assert principal.quantity == Decimal("677.465346")
    assert reward.quantity == Decimal("286.071322")
    assert principal.quantity + reward.quantity == Decimal("963.536668")
    assert {event.event_id for event in first} == {event.event_id for event in second}


def test_solana_rpc_spacex_xstock_mint_alias_keeps_swap_as_trade(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    tx_id = "spacex-xstock-swap"
    batch = CsvRawImporter(store).import_rows(
        source="solana_rpc",
        filename="jup-wallet-spcxx.json",
        file_hash="jup-wallet-spcxx",
        rows=[
            {
                "timestamp_utc": "2026-06-12T16:26:50+00:00",
                "event_type": "sol_transfer",
                "asset": "SOL",
                "quantity": "3.002167496",
                "side": "out",
                "tx_id": tx_id,
                "wallet_address": "wallet",
            },
            {
                "timestamp_utc": "2026-06-12T16:26:50+00:00",
                "event_type": "token_transfer",
                "asset": "XS3OZW...QPH8",
                "quantity": "1.18234846",
                "side": "in",
                "tx_id": tx_id,
                "wallet_address": "wallet",
            },
        ],
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    trade = next(event for event in events if event.event_type == "trade")
    assert trade.asset == "SPCXX"
    assert trade.quantity == Decimal("1.18234846")
    assert trade.quote_asset == "SOL"
    assert trade.quote_quantity == Decimal("3.002167496")
    assert not any(event.event_type == "income" for event in events)


def test_solana_rpc_helium_vsr_position_receipt_keeps_principal_transfer_tax_neutral(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    receipt = "5MFEM7LYTSGP2X3TVJXHXLENXSLRW6DQR3PSPJXVUETF"
    tx_id = "helium-vsr-position-deposit"
    rows = [
        {
            "timestamp_utc": "2023-08-01T06:43:43+00:00",
            "event_type": "swap_out_aggregated",
            "asset": "MOBILE",
            "quantity": "64729.546356",
            "side": "out",
            "fee_asset": "SOL",
            "fee": "0.00001",
            "tx_id": tx_id,
            "wallet_address": "wallet",
        },
        {
            "timestamp_utc": "2023-08-01T06:43:43+00:00",
            "event_type": "swap_in_aggregated",
            "asset": receipt,
            "quantity": "1",
            "side": "in",
            "tx_id": tx_id,
            "wallet_address": "wallet",
        },
    ]
    batch = CsvRawImporter(store).import_rows(
        source="solana_rpc",
        filename="helium-vsr-position.json",
        file_hash="helium-vsr-position",
        rows=rows,
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    principal = next(event for event in events if event.asset == "MOBILE")
    receipt_event = next(event for event in events if event.asset == receipt)
    assert principal.event_type == "transfer"
    assert principal.quantity == Decimal("-64729.546356")
    assert principal.fee_asset == "SOL"
    assert principal.fee_quantity == Decimal("0.00001")
    assert receipt_event.event_type == "unknown"
    assert receipt_event.quantity == 0


def _solana_raw_transaction(wallet, *, payer, native_delta_lamports, fee_lamports=5000):
    start = 1_000_000_000
    return {
        "transaction": {
            "message": {
                "accountKeys": [
                    {"pubkey": payer, "signer": True},
                    *([] if payer == wallet else [{"pubkey": wallet, "signer": False}]),
                ]
            }
        },
        "meta": {
            "err": None,
            "fee": fee_lamports,
            "preBalances": [start, start],
            "postBalances": [start - (fee_lamports if payer != wallet else -native_delta_lamports), start + native_delta_lamports],
            "preTokenBalances": [],
            "postTokenBalances": [],
        },
    }


def test_solana_rpc_native_reconciliation_charges_only_actual_fee_payer(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = "wallet"
    batch = CsvRawImporter(store).import_rows(
        source="solana_rpc",
        filename="third-party-paid.json",
        file_hash="third-party-paid",
        rows=[
            {
                "timestamp_utc": "2025-01-01T00:00:00Z",
                "event_type": "token_transfer",
                "asset": "HNT",
                "quantity": "1",
                "side": "in",
                "fee_asset": "SOL",
                "fee": "0.000005",
                "tx_id": "third-party-paid",
                "wallet_address": wallet,
                "raw_row": _solana_raw_transaction(
                    wallet,
                    payer="third-party",
                    native_delta_lamports=0,
                ),
            }
        ],
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].fee_asset is None
    assert events[0].fee_quantity is None


def test_solana_rpc_native_reconciliation_adds_exact_non_fee_lamport_effect(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = "wallet"
    raw_transaction = {
        "transaction": {"message": {"accountKeys": [{"pubkey": wallet, "signer": True}]}},
        "meta": {
            "err": None,
            "fee": 5000,
            "preBalances": [1_000_000_000],
            "postBalances": [999_985_000],
            "preTokenBalances": [],
            "postTokenBalances": [],
        },
    }
    batch = CsvRawImporter(store).import_rows(
        source="solana_rpc",
        filename="wallet-paid.json",
        file_hash="wallet-paid",
        rows=[
            {
                "timestamp_utc": "2025-01-01T00:00:00Z",
                "event_type": "token_transfer",
                "asset": "HNT",
                "quantity": "1",
                "side": "in",
                "fee_asset": "SOL",
                "fee": "0.000005",
                "tx_id": "wallet-paid",
                "wallet_address": wallet,
                "raw_row": raw_transaction,
            }
        ],
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)
    effect = sum(
        (RawNormalizer._canonical_event_asset_effect(event, "SOL") for event in events),
        Decimal("0"),
    )

    assert effect == Decimal("-0.000015")
    assert sum(event.fee_asset == "SOL" for event in events) == 1
    correction = next(event for event in events if event.asset == "SOL")
    assert correction.event_type == "transfer"
    assert correction.quantity == Decimal("-0.000010")


def test_solana_rpc_native_reconciliation_does_not_guess_unowned_token_account(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = "wallet"
    batch = CsvRawImporter(store).import_rows(
        source="solana_rpc",
        filename="unowned.json",
        file_hash="unowned",
        rows=[
            {
                "timestamp_utc": "2025-01-01T00:00:00Z",
                "event_type": "solana_tx",
                "asset": "SOL",
                "quantity": "0",
                "fee_asset": "SOL",
                "fee": "0.000005",
                "tx_id": "unowned",
                "wallet_address": wallet,
                "raw_row": {
                    "transaction": {
                        "message": {"accountKeys": [{"pubkey": "other", "signer": True}]}
                    },
                    "meta": {
                        "fee": 5000,
                        "preBalances": [1_000_000_000],
                        "postBalances": [999_995_000],
                        "preTokenBalances": [],
                        "postTokenBalances": [],
                    },
                },
            }
        ],
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "unknown"
    assert events[0].quantity == 0
    assert events[0].fee_asset == "SOL"
    assert events[0].fee_quantity == Decimal("0.000005")
    assert events[0].account == wallet


def test_solana_rpc_native_reconciliation_neutralizes_verified_outside_scope_txid(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = "wallet"
    row = {
        "timestamp_utc": "2025-01-01T00:00:00Z",
        "event_type": "solana_tx",
        "asset": "SOL",
        "quantity": "0",
        "fee_asset": "SOL",
        "fee": "0.000005",
        "tx_id": "verified-unowned",
        "wallet_address": wallet,
    }
    batch = CsvRawImporter(store).import_rows(
        source="solana_rpc",
        filename="verified-unowned.json",
        file_hash="verified-unowned",
        rows=[row],
    )
    normalizer = RawNormalizer(store)
    normalizer._solana_unowned_txids = {"verified-unowned"}

    events = normalizer.normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].quantity == 0
    assert events[0].fee_asset is None
    assert events[0].account == "solana_rpc_unowned_evidence"


def test_helium_raw_assert_location_uses_hnt_fee_not_mobile_oracle_column(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    main_wallet = RawNormalizer.HELIUM_MAIN_LEGACY_WALLET
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="helium-raw.csv",
        content=(
            "block;date;type;transaction_hash;hnt_amount;hnt_fee;mobile_amount;usd_oracle_price;usd_amount;usd_fee;payer;payee\n"
            "845276;15.05.2021 11:14;assert_location_v2;hash-3;0;0,036691127;14,99;0;0,55;0;;\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "fee"
    assert events[0].asset == "HNT"
    assert events[0].quantity == Decimal("-0.036691127")
    assert events[0].tx_id == "hash-3"
    assert events[0].account == main_wallet


def test_heliumtracker_advanced_report_derives_iot_reward(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="heliumtracker-report-advanced-2024-1.csv",
        content=(
            "Hotspot Name,Date,Mining Rewards HNT,Mining Rewards IOT,Mining Rewards MOBILE,Commissions HNT,Commissions IOT,Commissions MOBILE,HNT (EUR),IOT (EUR),MOBILE (EUR)\n"
            "hotspot-1,2024-01-05,0,42.125,0,0,0,0,6.10,0.001,0.0002\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "mining"
    assert events[0].asset == "IOT"
    assert events[0].quantity == Decimal("42.125")
    assert events[0].account == "hotspot-1"


def test_helium_wallet_month_derives_iot_reward_without_ours_other_party_double_count(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="Wallet.G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY-month.csv",
        content=(
            "Gateway Address,Name,Tag,Period Start (UTC),IOT Tokens,IOT Token,"
            "MOBILE Tokens,MOBILE Token,IOT (Ours),IOT (Other Party),"
            "MOBILE (Ours),MOBILE (Other Party)\n"
            "112Afmysw7zZa2pxUmoe31vpVQLPhhzvQNkfjw2YEUnpMprSgGwN,"
            "Short Caramel Shetland,My Hotspots,01.04.23,3421.905036,IOT,"
            ",,100,100,,\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "mining"
    assert events[0].asset == "IOT"
    assert events[0].quantity == Decimal("3421.905036")
    assert events[0].account == "112Afmysw7zZa2pxUmoe31vpVQLPhhzvQNkfjw2YEUnpMprSgGwN"
    assert events[0].source_ref == "112Afmysw7zZa2pxUmoe31vpVQLPhhzvQNkfjw2YEUnpMprSgGwN"
    assert events[0].event_time.year == 2023
    assert events[0].event_time.month == 4
    assert events[0].event_time.day == 30


def test_helium_wallet_month_skips_zero_iot_and_mobile_rows(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="Wallet.G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY-month.csv",
        content=(
            "Gateway Address,Period Start (UTC),IOT Tokens,IOT Token,MOBILE Tokens,MOBILE Token\n"
            "gateway-1,01.04.23,0,IOT,,\n"
        ),
    )

    events, report = RawNormalizer(store).normalize_batch_with_report(batch.batch_id)

    assert events == []
    assert report.raw_objects == 0


def test_heliumtracker_transfer_sheet_derives_hnt_transfer(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="heliumtracker-2021.csv",
        content=(
            "Sender,Receiver,Memo,Amount,Time\n"
            "13TFnZyGD,133rkwoKC,,453.53,2022-10-14 at 09:41PM\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "transfer"
    assert events[0].asset == "HNT"
    assert events[0].quantity == Decimal("453.53")
    assert events[0].account == "133rkwoKC"


def test_helium_payment_v2_fairspot_roundtrip_stays_transfer_on_main_wallet(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    main_wallet = RawNormalizer.HELIUM_MAIN_LEGACY_WALLET
    fairspot_wallet = RawNormalizer.HELIUM_FAIRSPOT_STAKING_WALLET
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="helium-fairspot-payment-v2.csv",
        content=(
            "block;time;type;txid;amount;hnt_fee;eur_value;payer;payee\n"
            f"894246;23.06.2021 20:26;payment_v2;Kk7ZTefj1fQOZ-1rPwt4aIOXpTmckgt8JA28IJ6XF_8;100;0,031305903;11,18;{main_wallet};{fairspot_wallet}\n"
            f"911879;08.07.2021 18:30;payment_v2;tLOGE2C0v-CGYSJfvKU6KvI7oQq4OALrz3rh6SbC8Qs;99,75;0,031305903;12,20;{fairspot_wallet};{main_wallet}\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert [event.event_type for event in events] == ["transfer", "transfer"]
    assert [event.account for event in events] == [main_wallet, main_wallet]
    assert [event.quantity for event in events] == [Decimal("-100"), Decimal("99.75")]
    assert all(event.asset == "HNT" for event in events)


def test_helium_payment_v2_inbound_to_main_wallet_is_positive_on_main_wallet(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    main_wallet = RawNormalizer.HELIUM_MAIN_LEGACY_WALLET
    service_wallet = "133bkeRPNK4BFhGfcf3uzmARbBfACprQ1TjWFMaxoHQoBqc5kfQ"
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="helium-inbound-payment-v2.csv",
        content=(
            "block;time;type;txid;amount;hnt_fee;eur_value;payer;payee\n"
            f"900001;24.06.2021 04:41;payment_v2;QGHeiessdO0yjf2y7Xi7aWQ1gilyQg.tyzhlzHmc08s;100;0,01;10;{service_wallet};{main_wallet}\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "transfer"
    assert events[0].account == main_wallet
    assert events[0].quantity == Decimal("100")


def test_pionex_pair_symbol_derives_asset_quote_and_sell_sign(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="pionex.csv",
        content=(
            "Time,Symbol,Side,Filled Amount,Filled Total,Order ID\n"
            "2021-04-28 10:00:00,MXC_USDT,SELL,125,84.50,order-442\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "trade"
    assert events[0].asset == "MXC"
    assert events[0].quantity == Decimal("-125")
    assert events[0].quote_asset == "USDT"
    assert events[0].quote_quantity == Decimal("84.50")
    assert events[0].source_ref == "order-442"
    assert events[0].account == "pionex"


def test_pionex_raw_trading_details_buy_uses_executed_qty_as_base_amount(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="raw-trading-details.csv",
        content=(
            "date(UTC+0),symbol,side,executed_qty,amount,fee,fee_coin,tax_id\n"
            "2023-03-10 09:10:58,BTC_USDT,BUY,0.00024703000000000000,4.92168365170000000000,0.00000012,BTC,s_0\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "trade"
    assert events[0].asset == "BTC"
    assert events[0].quantity == Decimal("0.00024703000000000000")
    assert events[0].quote_asset == "USDT"
    assert events[0].quote_quantity == Decimal("4.92168365170000000000")
    assert events[0].fee_asset == "BTC"
    assert events[0].fee_quantity == Decimal("0.00000012")
    assert events[0].source_ref == "s_0"


def test_pionex_raw_trading_details_sell_uses_executed_qty_as_negative_base_amount(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="raw-trading-details.csv",
        content=(
            "date(UTC+0),symbol,side,executed_qty,amount,fee,fee_coin,tax_id\n"
            "2023-03-10 09:15:58,BTC_USDT,SELL,0.00024600000000000000,4.90000000000000000000,0.0049,USDT,s_1\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "trade"
    assert events[0].asset == "BTC"
    assert events[0].quantity == Decimal("-0.00024600000000000000")
    assert events[0].quote_asset == "USDT"
    assert events[0].quote_quantity == Decimal("4.90000000000000000000")
    assert events[0].fee_asset == "USDT"
    assert events[0].fee_quantity == Decimal("0.0049")
    assert events[0].source_ref == "s_1"


def test_pionex_raw_trading_details_keeps_executed_canceled_orders(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="raw-trading-details.csv",
        content=(
            "date(UTC+0),symbol,side,executed_qty,amount,fee,fee_coin,state,tax_id\n"
            "2022-09-10 15:58:52,HNT_USDT,SELL,0.394,2.286776,0.001143,USDT,CANCELED,s_16\n"
            "2022-09-10 15:59:00,HNT_USDT,SELL,0,0,0,USDT,CANCELED,s-empty\n"
            "2022-09-10 15:59:52,HNT_USDT,SELL,0.394,2.286776,0.001143,USDT,FILLED,s_17\n"
        ),
    )

    events, report = RawNormalizer(store).normalize_batch_with_report(batch.batch_id)

    assert len(events) == 2
    assert report.raw_objects == 2
    assert report.created_events == 2
    assert report.skipped_raw_objects == 0
    by_source_ref = {event.source_ref: event for event in events}
    assert set(by_source_ref) == {"s_16", "s_17"}
    assert by_source_ref["s_16"].quantity == Decimal("-0.394")
    assert by_source_ref["s_16"].quote_quantity == Decimal("2.286776")


def test_pionex_cointracker_buy_side_maps_received_asset_and_sent_quote(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="for-cointracker.csv",
        content=(
            "Date,Received Quantity,Received Currency,Sent Quantity,Sent Currency,Fee Amount,Fee Currency,Tag\n"
            "12/25/2021 16:25:25,2.787,HNT,105.042721,USDT,0.00139350,HNT,\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "trade"
    assert events[0].asset == "HNT"
    assert events[0].quantity == Decimal("2.787")
    assert events[0].quote_asset == "USDT"
    assert events[0].quote_quantity == Decimal("105.042721")
    assert events[0].fee_asset == "HNT"
    assert events[0].fee_quantity == Decimal("0.00139350")


def test_pionex_cointracker_sell_side_maps_sent_crypto_as_negative(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="for-cointracker.csv",
        content=(
            "Date,Received Quantity,Received Currency,Sent Quantity,Sent Currency,Fee Amount,Fee Currency,Tag\n"
            "12/25/2021 16:35:01,8.658,USDT,0.222,HNT,0.00432900,USDT,\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "trade"
    assert events[0].asset == "HNT"
    assert events[0].quantity == Decimal("-0.222")
    assert events[0].quote_asset == "USDT"
    assert events[0].quote_quantity == Decimal("8.658")


def test_pionex_cointracking_export_maps_tx_id_and_exchange_account(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="for-cointracking.csv",
        content=(
            "Type,Buy Amount,Buy Currency,Sell Amount,Sell Currency,Fee,Fee Currency,Exchange,Trade-Group,Comment,Date,Tx-ID\n"
            "Trade,2.787,HNT,105.042721,USDT,0.00139350,HNT,Pionex,,,12/25/2021 16:25:25,s_1\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "trade"
    assert events[0].asset == "HNT"
    assert events[0].tx_id == "s_1"
    assert events[0].source_ref == "s_1"
    assert events[0].account == "Pionex"


def test_pionex_support_transfer_list_maps_usdt_direction(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="pionex_usdt_known_transfers.csv",
        content=(
            "timestamp_utc,direction,amount_usdt,from_address,to_address,tx_id\n"
            "2022-01-19T12:55:51+00:00,out,1245.38419,from-1,to-1,tx-1245\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "transfer"
    assert events[0].asset == "USDT"
    assert events[0].quantity == Decimal("-1245.38419")
    assert events[0].tx_id == "tx-1245"


def test_binance_market_without_separator_derives_asset_and_quote(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="binance.csv",
        content=(
            "Date(UTC),Market,Type,Amount,Total\n"
            "2021-05-15 23:59:49,ETHEUR,BUY,0.01374,41.220\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].asset == "ETH"
    assert events[0].quote_asset == "EUR"
    assert events[0].quote_quantity == Decimal("41.220")


def test_binance_fiat_buy_splits_receive_and_spend_amounts(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="fiat-buy.csv",
        content=(
            "Time,Method,Spend Amount,Receive Amount,Fee,Price,Status,Transaction ID\n"
            "21-04-19 17:16:48,Credit Card,1000.00 EUR,1169.434027 USDT,20.00 EUR,0.83801222 USDT/EUR,Successful,tx-1\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "transfer"
    assert events[0].asset == "USDT"
    assert events[0].quantity == Decimal("1169.434027")
    assert events[0].quote_asset == "EUR"
    assert events[0].quote_quantity == Decimal("1000.00")


def test_binance_failed_fiat_buy_is_audit_only_zero_event(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="fiat-buy.csv",
        content=(
            "Time,Method,Spend Amount,Receive Amount,Fee,Price,Status,Transaction ID\n"
            "21-04-19 17:14:53,Credit Card,1000.00 EUR,1170.074512 USDT,20.00 EUR,0.8375535 USDT/EUR,Failed,tx-failed\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].asset == "USDT"
    assert events[0].event_type == "unknown"
    assert events[0].quantity == Decimal("0")
    assert events[0].quote_asset is None
    assert events[0].quote_quantity is None


def test_binance_transaction_card_buy_keeps_spot_transfer_without_tax_lot(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="Binance-Transaction-History.xlsx",
        content=(
            "Time,Account,Operation,Coin,Change,Remark\n"
            "23-03-17 09:51:28,Spot,Buy Crypto With Card,BUSD,519.83907139,Ref - N01333135634309321728031744\n"
            "23-03-17 09:51:28,Spot,Buy Crypto With Card,EUR,-490.5,Ref - N01333135634309321728031744\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 2
    assert {event.asset for event in events} == {"BUSD", "EUR"}
    busd = next(event for event in events if event.asset == "BUSD")
    eur = next(event for event in events if event.asset == "EUR")
    assert busd.event_type == "transfer"
    assert busd.quantity == Decimal("519.83907139")
    assert busd.quote_asset is None
    assert busd.quote_quantity is None
    assert eur.event_type == "unknown"
    assert eur.quantity == Decimal("0")
    assert eur.quote_asset is None
    assert eur.quote_quantity is None


def test_binance_fiat_ocbs_add_fiat_and_fees_is_zero_mirror(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="Binance-Transaction-History.xlsx",
        content=(
            "Time,Account,Operation,Coin,Change\n"
            "23-03-17 09:51:27,Spot,Fiat OCBS - Add Fiat and Fees,EUR,490.5\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "unknown"
    assert events[0].asset == "EUR"
    assert events[0].quantity == Decimal("0")
    assert events[0].quote_asset is None
    assert events[0].quote_quantity is None
    assert events[0].fee_asset is None
    assert events[0].fee_quantity is None


def test_binance_transaction_spend_is_merged_into_token_buy_quote(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="Binance-Transaction-History.xlsx",
        content=(
            "Time,Account,Operation,Coin,Change\n"
            "25-10-13 14:45:07,Spot,Transaction Spend,EUR,-171.62761\n"
            "25-10-13 14:45:07,Spot,Transaction Buy,ADA,126.5\n"
            "25-10-13 14:45:07,Spot,Transaction Fee,ADA,-0.264385\n"
            "25-10-13 14:45:07,Spot,Transaction Buy,ADA,278.3\n"
            "25-10-13 14:45:07,Spot,Transaction Spend,EUR,-78.01255\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    nonzero_events = [event for event in events if event.quantity != 0]
    assert [(event.event_type, event.asset, event.quantity) for event in nonzero_events] == [
        ("trade", "ADA", Decimal("126.417379687500000000")),
        ("trade", "ADA", Decimal("278.118235312500000000")),
    ]
    assert [event.asset for event in events if event.quantity == 0] == ["EUR", "ADA", "EUR"]
    buy_events = [event for event in events if event.event_type == "trade"]
    assert all(event.quote_asset == "EUR" for event in buy_events)
    assert sum((event.quote_quantity for event in buy_events), Decimal("0")) == Decimal("249.64016")
    assert buy_events[0].quote_quantity == Decimal("249.64016") * (
        Decimal("126.417379687500000000") / Decimal("404.535615000000000000")
    )


def test_binance_transaction_sold_positive_asset_is_treated_as_eur_quote_buy(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="Binance-Transaction-History.xlsx",
        content=(
            "Time,Account,Operation,Coin,Change\n"
            "25-11-04 22:57:07,Spot,Transaction Sold,EUR,-196.5\n"
            "25-11-04 22:57:07,Spot,Transaction Sold,USDC,225.56235\n"
            "25-11-04 22:57:07,Spot,Transaction Fee,BNB,-0.00017546\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    usdc = next(event for event in events if event.asset == "USDC")
    assert usdc.event_type == "trade"
    assert usdc.quantity == Decimal("225.56235")
    assert usdc.quote_asset == "EUR"
    assert usdc.quote_quantity == Decimal("196.5")
    assert all(not (event.asset == "EUR" and event.quantity < 0) for event in events)
    assert [event.event_type for event in events if event.asset == "EUR"] == ["unknown"]


def test_binance_transaction_spend_crypto_quote_creates_taxable_quote_trade(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="Binance-Transaction-History.xlsx",
        content=(
            "Time,Account,Operation,Coin,Change\n"
            "23-03-17 09:53:36,Spot,Transaction Spend,BUSD,-48.33066\n"
            "23-03-17 09:53:36,Spot,Transaction Buy,HNT,29.01\n"
            "23-03-17 10:25:50,Spot,Transaction Sold,HNT,-304.49\n"
            "23-03-17 10:25:50,Spot,Transaction Sold,HNT,-9.42\n"
            "23-03-17 10:25:50,Spot,Transaction Revenue,BUSD,482.00767\n"
            "23-03-17 10:25:50,Spot,Transaction Revenue,BUSD,14.91186\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    hnt_buy = next(event for event in events if event.asset == "HNT" and event.quantity > 0)
    assert hnt_buy.event_type == "trade"
    assert hnt_buy.quote_asset == "BUSD"
    assert hnt_buy.quote_quantity == Decimal("48.33066")

    busd_revenue = [event for event in events if event.asset == "BUSD" and event.quantity > 0]
    assert [event.event_type for event in busd_revenue] == ["trade", "trade"]
    assert all(event.quote_asset == "HNT" for event in busd_revenue)
    assert sum((event.quote_quantity for event in busd_revenue), Decimal("0")) == Decimal("313.91")

    assert all(
        event.event_type == "unknown" and event.quantity == 0
        for event in events
        if (event.asset == "BUSD" and event.quote_asset is None)
        or (event.asset == "HNT" and event.quantity == 0)
    )


def test_binance_small_assets_exchange_bnb_allocates_dust_quote(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    priced_at = datetime(2021, 4, 28, 7, 14, 15, tzinfo=timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="COTI",
            price_eur=Decimal("0.4"),
            priced_at=priced_at,
            source="unit",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="WRX",
            price_eur=Decimal("4"),
            priced_at=priced_at,
            source="unit",
        )
    )
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="Binance-Transaction-History.xlsx",
        content=(
            "Time,Account,Operation,Coin,Change\n"
            "21-04-28 07:14:15,Spot,Small Assets Exchange BNB,COTI,-100\n"
            "21-04-28 07:14:15,Spot,Small Assets Exchange BNB,BNB,0.072727272727272727\n"
            "21-04-28 07:14:15,Spot,Small Assets Exchange BNB,WRX,-1\n"
            "21-04-28 07:14:15,Spot,Small Assets Exchange BNB,BNB,0.007272727272727273\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    coti = next(event for event in events if event.asset == "COTI")
    wrx = next(event for event in events if event.asset == "WRX")
    assert coti.event_type == "trade"
    assert coti.quote_asset == "BNB"
    assert coti.quote_quantity == Decimal("0.08") * (Decimal("40") / Decimal("44"))
    assert wrx.event_type == "trade"
    assert wrx.quote_asset == "BNB"
    assert wrx.quote_quantity == Decimal("0.08") * (Decimal("4") / Decimal("44"))
    assert all(
        event.event_type == "unknown" and event.quantity == 0
        for event in events
        if event.asset == "BNB"
    )


def test_binance_small_assets_exchange_ignores_derived_price_feedback(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    priced_at = datetime(2021, 4, 28, 7, 14, 15, tzinfo=timezone.utc)
    for asset, price in (("COTI", "0.4"), ("WRX", "400")):
        store.add_price_point(
            PricePointCreate(
                asset=asset,
                price_eur=Decimal(price),
                priced_at=priced_at,
                source="derived:event_quote",
            )
        )
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="Binance-Transaction-History.xlsx",
        content=(
            "Time,Account,Operation,Coin,Change\n"
            "21-04-28 07:14:15,Spot,Small Assets Exchange BNB,COTI,-100\n"
            "21-04-28 07:14:15,Spot,Small Assets Exchange BNB,BNB,0.08\n"
            "21-04-28 07:14:15,Spot,Small Assets Exchange BNB,WRX,-1\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    coti = next(event for event in events if event.asset == "COTI")
    wrx = next(event for event in events if event.asset == "WRX")
    assert coti.quote_quantity == Decimal("0.08") * (Decimal("100") / Decimal("101"))
    assert wrx.quote_quantity == Decimal("0.08") * (Decimal("1") / Decimal("101"))


def test_binance_transaction_related_pair_creates_quote_trade(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="transaction-history.csv",
        content=(
            "Time,Account,Operation,Coin,Change,Remark\n"
            "21-02-06 23:18:15,Spot,Transaction Related,EUR,-98.1,2ae01da3bd9f4522a103b8c54f0eb1c6\n"
            "21-02-06 23:18:15,Spot,Transaction Related,BNB,1.625,2ae01da3bd9f4522a103b8c54f0eb1c6\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert [(event.asset, event.event_type, event.quantity) for event in events] == [
        ("EUR", "unknown", Decimal("0E-18")),
        ("BNB", "trade", Decimal("1.625000000000000000")),
    ]
    assert events[1].quote_asset == "EUR"
    assert events[1].quote_quantity == Decimal("98.100000000000000000")


def test_binance_same_asset_fee_reduces_trade_quantity(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="transaction-history.csv",
        content=(
            "Time,Account,Operation,Coin,Change\n"
            "21-02-23 12:54:43,Spot,Fee,HNT,-0.0176\n"
            "21-02-23 12:54:43,Spot,Buy,HNT,17.6\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert [(event.asset, event.event_type, event.quantity) for event in events] == [
        ("HNT", "unknown", Decimal("0E-18")),
        ("HNT", "trade", Decimal("17.582400000000000000")),
    ]


def test_binance_transaction_revenue_fee_reduces_revenue_quantity(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="transaction-history.csv",
        content=(
            "Time,Account,Operation,Coin,Change\n"
            "23-03-17 10:25:50,Spot,Transaction Sold,HNT,-304.49\n"
            "23-03-17 10:25:50,Spot,Transaction Sold,HNT,-9.42\n"
            "23-03-17 10:25:50,Spot,Transaction Revenue,BUSD,482.00767\n"
            "23-03-17 10:25:50,Spot,Transaction Fee,BUSD,-0.48200767\n"
            "23-03-17 10:25:50,Spot,Transaction Revenue,BUSD,14.91186\n"
            "23-03-17 10:25:50,Spot,Transaction Fee,BUSD,-0.01491186\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    busd_trades = [event for event in events if event.asset == "BUSD" and event.event_type == "trade"]
    assert [event.quantity for event in busd_trades] == [
        Decimal("481.525662330000000000"),
        Decimal("14.896948140000000000"),
    ]
    assert sum((event.quote_quantity for event in busd_trades), Decimal("0")) == Decimal("313.91")
    assert all(
        event.event_type == "unknown" and event.quantity == 0
        for event in events
        if event.asset in {"BUSD", "HNT"} and event.event_type == "unknown"
    )


def test_binance_airdrop_assets_create_reward_except_bttc_redenomination(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="transaction-history.csv",
        content=(
            "Time,Account,Operation,Coin,Change\n"
            "22-09-19 14:08:11,Spot,Airdrop Assets,ETHW,0.00000468\n"
            "22-01-24 18:47:31,Spot,Airdrop Assets,BTTC,4194464\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    ethw = next(event for event in events if event.asset == "ETHW")
    bttc = next(event for event in events if event.asset == "BTTC")
    assert ethw.event_type == "reward"
    assert ethw.quantity == Decimal("0.00000468")
    assert bttc.event_type == "transfer"
    assert bttc.quantity == Decimal("4194464")


def test_binance_token_redenomination_and_asset_recovery_are_transfers(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="transaction-history.csv",
        content=(
            "Time,Account,Operation,Coin,Change\n"
            "22-01-24 12:18:36,Spot,Token Swap - Redenomination/Rebranding,BTT,-4194.464\n"
            "24-04-26 11:25:58,Spot,Asset Recovery,HNT,-0.00371718\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    btt = next(event for event in events if event.asset == "BTTC")
    hnt = next(event for event in events if event.asset == "HNT")
    assert btt.event_type == "transfer"
    assert btt.quantity == Decimal("-4194.464")
    assert hnt.event_type == "transfer"
    assert hnt.quantity == Decimal("-0.00371718")


def test_binance_crypto_box_is_reward_but_auto_invest_and_index_redeem_are_transfers(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="transaction-history.csv",
        content=(
            "Time,Account,Operation,Coin,Change,Remark\n"
            "25-02-18 22:40:01,Funding,Crypto Box,BONK,222.76,Binance Pay\n"
            "25-01-28 14:22:24,Spot,Auto-Invest Transaction,EUR,-50,\n"
            "25-11-27 08:26:17,Spot,Index-auto-investment - Redeem Positions,SOL,0.16379017,\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    bonk = next(event for event in events if event.asset == "BONK")
    eur = next(event for event in events if event.asset == "EUR")
    sol = next(event for event in events if event.asset == "SOL")
    assert bonk.event_type == "reward"
    assert bonk.quantity == Decimal("222.76")
    assert eur.event_type == "transfer"
    assert eur.quantity == Decimal("-50")
    assert sol.event_type == "transfer"
    assert sol.quantity == Decimal("0.16379017")


def test_binance_sol_staking_purchase_is_bnsol_trade_not_staking_reward(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="transaction-history.csv",
        content=(
            "Time,Account,Operation,Coin,Change,Remark\n"
            "25-02-28 06:55:47,Spot,SOL Staking - Purchase,BNSOL,22.32304223,\n"
            "25-02-28 06:55:47,Spot,SOL Staking - Purchase,SOL,-23.189761,\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    bnsol = next(event for event in events if event.asset == "BNSOL")
    sol = next(event for event in events if event.asset == "SOL")
    assert bnsol.event_type == "trade"
    assert bnsol.quantity == Decimal("22.32304223")
    assert bnsol.quote_asset == "SOL"
    assert bnsol.quote_quantity == Decimal("23.189761")
    assert sol.event_type == "unknown"
    assert sol.quantity == Decimal("0")


def test_binance_simple_earn_flexible_moves_are_internal_transfers(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="transaction-history.csv",
        content=(
            "Time,Account,Operation,Coin,Change,Remark\n"
            "25-03-09 21:01:51,Spot,Simple Earn Flexible Subscription,BNSOL,-22.32304223,Binance Earn\n"
            "25-03-23 15:44:22,Spot,Simple Earn Flexible Redemption,BNSOL,22.32305193,Binance Earn\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert [(event.asset, event.event_type, event.quantity) for event in events] == [
        ("BNSOL", "transfer", Decimal("-22.32304223")),
        ("BNSOL", "transfer", Decimal("22.32304223")),
        ("BNSOL", "income", Decimal("0.00000970")),
    ]


def test_binance_staking_purchase_and_redemption_are_principal_transfers(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="transaction-history.csv",
        content=(
            "Time,Account,Operation,Coin,Change,Remark\n"
            "25-01-01 08:00:00,Spot,Staking Purchase,HNT,-100,\n"
            "25-01-31 08:00:00,Spot,Staking Redemption,HNT,100,\n"
            "25-02-01 08:00:00,Spot,Staking Rewards,HNT,0.5,\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert [(event.asset, event.event_type, event.quantity) for event in events] == [
        ("HNT", "transfer", Decimal("-100")),
        ("HNT", "transfer", Decimal("100")),
        ("HNT", "staking", Decimal("0.5")),
    ]


def test_bitget_spot_trading_history_derives_quote_and_utc_time(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="bitget",
        filename="Spot Trading History.csv",
        content=(
            "Trading pair,Coin,Action,Quantity,Transacted amount,Fee deducted in,Fee,Timestamp UTC+8 (Created),id\n"
            "BTCUSDT,BTC,Sell,0.000542,34.72029236,USDT,0,2024-04-14 13:04:47,'1163269941592801282\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "trade"
    assert events[0].event_time.isoformat() == "2024-04-14T05:04:47+00:00"
    assert events[0].asset == "BTC"
    assert events[0].quantity == Decimal("-0.000542")
    assert events[0].quote_asset == "USDT"
    assert events[0].quote_quantity == Decimal("34.72029236")
    assert events[0].fee_asset == "USDT"
    assert events[0].fee_quantity == Decimal("0")


def test_binance_simple_earn_api_maps_subscription_redemption_and_reward(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    rows = [
        {
            "record_type": "flexible_subscription",
            "asset": "JUP",
            "amount": "10",
            "time_iso": "2025-01-01T00:00:00Z",
            "account_type": "simple_earn_flexible",
            "product_id": "JUP001",
            "purchase_id": "sub-1",
            "source_ref": "flexible_subscription:JUP001:sub-1",
        },
        {
            "record_type": "flexible_redemption",
            "asset": "JUP",
            "amount": "4",
            "time_iso": "2025-01-02T00:00:00Z",
            "account_type": "simple_earn_flexible",
            "product_id": "JUP001",
            "redeem_id": "red-1",
            "source_ref": "flexible_redemption:JUP001:red-1",
        },
        {
            "record_type": "flexible_rewards_realtime",
            "asset": "JUP",
            "rewards": "0.5",
            "time_iso": "2025-01-03T00:00:00Z",
            "account_type": "simple_earn_flexible",
            "product_id": "JUP001",
            "source_ref": "flexible_rewards_realtime:JUP001:2025-01-03",
        },
    ]
    batch = CsvRawImporter(store).import_rows(
        source="binance_simple_earn_api",
        filename="simple-earn.json",
        file_hash="sha256:simple-earn-test",
        rows=rows,
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert [(event.event_type, event.account, event.quantity) for event in events] == [
        ("transfer", "Binance Earn Flexible JUP001", Decimal("10")),
        ("transfer", "Binance Earn Flexible JUP001", Decimal("-4")),
        ("reward", "Binance Earn Flexible JUP001", Decimal("0.5")),
        ("transfer", "Spot", Decimal("-10")),
        ("transfer", "Spot", Decimal("4")),
    ]
    assert events[0].source_ref == "flexible_subscription:JUP001:sub-1"
    assert events[3].source_ref == "flexible_subscription:JUP001:sub-1:spot_mirror"
    assert events[4].source_ref == "flexible_redemption:JUP001:red-1:spot_mirror"


def test_binance_simple_earn_api_uses_existing_split_spot_counterpart(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    transaction_batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="transaction-history.csv",
        content=(
            "Time,Account,Operation,Coin,Change,Remark\n"
            "25-01-01 00:00:00,Spot,Simple Earn Flexible Subscription,JUP,-3.5,Binance Earn\n"
            "25-01-02 00:00:00,Spot,Simple Earn Flexible Redemption,JUP,4,Binance Earn\n"
        ),
    )
    RawNormalizer(store).normalize_batch(transaction_batch.batch_id)
    api_batch = CsvRawImporter(store).import_rows(
        source="binance_simple_earn_api",
        filename="simple-earn.json",
        file_hash="sha256:simple-earn-existing-counterpart-test",
        rows=[
            {
                "record_type": "flexible_redemption",
                "asset": "JUP",
                "amount": "4",
                "time_iso": "2025-01-02T00:00:00Z",
                "account_type": "simple_earn_flexible",
                "product_id": "JUP001",
                "redeem_id": "red-existing",
                "source_ref": "flexible_redemption:JUP001:red-existing",
            }
        ],
    )

    events = RawNormalizer(store).normalize_batch(api_batch.batch_id)

    assert [(event.event_type, event.account, event.quantity) for event in events] == [
        ("transfer", "Binance Earn Flexible JUP001", Decimal("-4")),
    ]


def test_binance_simple_earn_api_uses_delayed_exact_spot_counterpart(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    transaction_batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="transaction-history.csv",
        content=(
            "Time,Account,Operation,Coin,Change,Remark\n"
            "24-04-04 00:38:38,Spot,Simple Earn Locked Redemption,SOL,1.3832922,Binance Earn\n"
        ),
    )
    RawNormalizer(store).normalize_batch(transaction_batch.batch_id)
    api_batch = CsvRawImporter(store).import_rows(
        source="binance_simple_earn_api",
        filename="simple-earn.json",
        file_hash="sha256:simple-earn-delayed-counterpart-test",
        rows=[
            {
                "record_type": "locked_redemption",
                "asset": "SOL",
                "amount": "1.3832922",
                "time_iso": "2024-04-02T16:56:17Z",
                "account_type": "simple_earn_locked",
                "product_id": "Sol*120",
                "redeem_id": "red-delayed",
                "source_ref": "locked_redemption:SOL:Sol*120:red-delayed",
            }
        ],
    )

    events = RawNormalizer(store).normalize_batch(api_batch.batch_id)

    assert [(event.event_type, event.account, event.quantity) for event in events] == [
        ("transfer", "Binance Earn Locked Sol*120", Decimal("-1.3832922")),
    ]


def test_binance_simple_earn_api_does_not_fill_partial_spot_counterpart(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    transaction_batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="transaction-history.csv",
        content=(
            "Time,Account,Operation,Coin,Change,Remark\n"
            "25-01-02 00:00:00,Spot,Simple Earn Flexible Redemption,JUP,3,Binance Earn\n"
        ),
    )
    RawNormalizer(store).normalize_batch(transaction_batch.batch_id)
    api_batch = CsvRawImporter(store).import_rows(
        source="binance_simple_earn_api",
        filename="simple-earn.json",
        file_hash="sha256:simple-earn-partial-counterpart-test",
        rows=[
            {
                "record_type": "flexible_redemption",
                "asset": "JUP",
                "amount": "4",
                "time_iso": "2025-01-02T00:00:00Z",
                "account_type": "simple_earn_flexible",
                "product_id": "JUP001",
                "redeem_id": "red-partial",
                "source_ref": "flexible_redemption:JUP001:red-partial",
            }
        ],
    )

    events = RawNormalizer(store).normalize_batch(api_batch.batch_id)

    assert [(event.account, event.quantity) for event in events] == [
        ("Binance Earn Flexible JUP001", Decimal("-4")),
    ]


def test_binance_simple_earn_api_does_not_fill_delayed_partial_spot_counterpart(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    transaction_batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="transaction-history.csv",
        content=(
            "Time,Account,Operation,Coin,Change,Remark\n"
            "25-01-03 00:00:00,Spot,Simple Earn Flexible Redemption,JUP,3,Binance Earn\n"
        ),
    )
    RawNormalizer(store).normalize_batch(transaction_batch.batch_id)
    api_batch = CsvRawImporter(store).import_rows(
        source="binance_simple_earn_api",
        filename="simple-earn.json",
        file_hash="sha256:simple-earn-delayed-partial-counterpart-test",
        rows=[
            {
                "record_type": "flexible_redemption",
                "asset": "JUP",
                "amount": "4",
                "time_iso": "2025-01-02T00:00:00Z",
                "account_type": "simple_earn_flexible",
                "product_id": "JUP001",
                "redeem_id": "red-delayed-partial",
                "source_ref": "flexible_redemption:JUP001:red-delayed-partial",
            }
        ],
    )

    events = RawNormalizer(store).normalize_batch(api_batch.batch_id)

    assert [(event.account, event.quantity) for event in events] == [
        ("Binance Earn Flexible JUP001", Decimal("-4")),
    ]


def test_binance_simple_earn_api_does_not_match_delayed_regular_trade(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    transaction_batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="transaction-history.csv",
        content=(
            "Time,Account,Operation,Coin,Change,Remark\n"
            "25-01-03 00:00:00,Spot,Transaction Buy,JUP,4,\n"
        ),
    )
    RawNormalizer(store).normalize_batch(transaction_batch.batch_id)
    api_batch = CsvRawImporter(store).import_rows(
        source="binance_simple_earn_api",
        filename="simple-earn.json",
        file_hash="sha256:simple-earn-delayed-trade-test",
        rows=[
            {
                "record_type": "flexible_redemption",
                "asset": "JUP",
                "amount": "4",
                "time_iso": "2025-01-02T00:00:00Z",
                "account_type": "simple_earn_flexible",
                "product_id": "JUP001",
                "redeem_id": "red-unmatched",
                "source_ref": "flexible_redemption:JUP001:red-unmatched",
            }
        ],
    )

    events = RawNormalizer(store).normalize_batch(api_batch.batch_id)

    assert [(event.account, event.quantity) for event in events] == [
        ("Binance Earn Flexible JUP001", Decimal("-4")),
        ("Spot", Decimal("4")),
    ]


def test_binance_simple_earn_locked_auto_subscription_is_non_balance_renewal(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_rows(
        source="binance_simple_earn_api",
        filename="simple-earn.json",
        file_hash="sha256:locked-auto-renewal-test",
        rows=[
            {
                "record_type": "locked_subscription",
                "asset": "SOL",
                "amount": "9.84095708",
                "time_iso": "2026-05-26T00:36:41Z",
                "account_type": "simple_earn_locked",
                "product_id": "Sol*120",
                "position_id": "344393820",
                "purchase_id": "347914202",
                "type": "AUTO",
                "source_ref": "locked_subscription:SOL:Sol*120:344393820:347914202",
            }
        ],
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "transfer"
    assert events[0].asset == "SOL"
    assert events[0].account == "Binance Earn Locked Sol*120"
    assert events[0].quantity == Decimal("0")
    assert events[0].source_ref == "locked_subscription:SOL:Sol*120:344393820:347914202"


def test_bitget_deposit_withdrawal_history_maps_deposit(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="bitget",
        filename="Deposit-Withdrawal History.csv",
        content=(
            "Order no.,UID,Transaction hash(txid),Coin,Network,Quantity,Amount in USDT,Withdrawal fee,Type,Timestamp UTC+8 (Completion)\n"
            "'1149662704676515840,operator-reference,tx-1,USDT,SOL,55,55,0,Deposit,2024-03-07 23:54:40\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "transfer"
    assert events[0].event_time.isoformat() == "2024-03-07T15:54:40+00:00"
    assert events[0].asset == "USDT"
    assert events[0].quantity == Decimal("55")
    assert events[0].quote_asset is None
    assert events[0].quote_quantity == Decimal("55")
    assert events[0].tx_id == "tx-1"


def test_bitget_withdrawal_api_fields_stay_raw_evidence_only(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="bitget",
        filename="bitget-withdrawal-api-20250615-20250616-JUP-SOL.json",
        content=(
            "record_type,type,asset,coin,amount,quantity,fee,cTime,uTime,time,account,address,toAddress,chain,network,tx_id,txId,source_ref,status\n"
            "bitget_withdrawal_evidence,withdraw,JUP,JUP,4680.175116,4680.175116,0.1,1749972612000,1749972612000,2025-06-15T07:30:12+00:00,bitget,EnbD7,EnbD7,SOL,SOL,bitget-withdraw-tx,bitget-withdraw-tx,bitget-order-1,success\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert events == []


def test_pionex_dust_collector_creates_negative_trade_with_swap_value(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="dust-collector.csv",
        content=(
            "date(UTC+0),coin,amount,price,swap_value\n"
            "2024-03-12 04:44:43,SHIB,0.007625,0.00003307,0.0000002521351125\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "trade"
    assert events[0].asset == "SHIB"
    assert events[0].quantity == Decimal("-0.007625")
    assert events[0].quote_asset == "USDT"
    assert events[0].quote_quantity == Decimal("0.0000002521351125")


def test_bitget_usdc_transfer_amount_usdt_sets_quote_asset(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="bitget",
        filename="Spot Financial Record.csv",
        content=(
            "Coin,Type,Action,Quantity,Amount (USDT),Creation timestamp (+8 UTC)\n"
            "USDC,Deposit,RECHARGE,500,500,2024-12-01 21:12:52\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].asset == "USDC"
    assert events[0].quote_asset == "USDT"
    assert events[0].quote_quantity == Decimal("500")


def test_bitget_spot_financial_record_skips_usdt_trade_shadow_rows(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="bitget",
        filename="Spot Financial Record.csv",
        content=(
            "Coin,Type,Action,Quantity,Amount (USDT),Fee (Coin quantity),Creation timestamp (+8 UTC),"
            "Balance before action (USDT),Balance after action (USDT),Order no.\n"
            "HNT,Trading,ORDER_DEALT_IN,4.993,45.1337242,-0.004993,2024-03-07 23:55:54,0,45.08859048,'base\n"
            "USDT,Trading,ORDER_DEALT_FROZEN_OUT,-45.6265333,-45.6265333,0,2024-03-07 23:55:54,9.3579884,0,'quote\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 2
    hnt = next(event for event in events if event.asset == "HNT")
    usdt_shadow = next(event for event in events if event.asset == "USDT")
    assert hnt.quantity == Decimal("4.993")
    assert hnt.quote_asset == "USDT"
    assert hnt.quote_quantity == Decimal("45.1337242")
    assert usdt_shadow.event_type == "unknown"
    assert usdt_shadow.quantity == Decimal("0")
    assert usdt_shadow.quote_asset is None
    assert usdt_shadow.fee_asset is None


def test_bitget_futures_financial_record_keeps_cash_settlement(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="bitget",
        filename="Futures Financial Record.csv",
        content=(
            "Coin,Trading Pair,Action (English),Surplus/deduction (after fee),Fee,Timestamp UTC+8 (Order)\n"
            "USDT,BTCUSDT_UMCBL,open_long,-1.70002224,-1.70002224,2024-12-06 02:34:05\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "derivative"
    assert events[0].event_time.isoformat() == "2024-12-05T18:34:05+00:00"
    assert events[0].asset == "USDT"
    assert events[0].quantity == Decimal("-1.70002224")


def test_blockpit_trade_uses_incoming_and_outgoing_legs(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="blockpit",
        filename="blockpit.csv",
        content=(
            "Date (UTC);Integration Name;Label;Outgoing Asset;Outgoing Amount;"
            "Incoming Asset;Incoming Amount;Fee Asset (optional);Fee Amount (optional);"
            "Comment (optional);Trx. ID (optional);Source Type;Source Name\n"
            "06.12.2024 12:09:15;Solana;Trade;USDC;100;SOL;0.5;SOL;0.001;;tx-1;Chain;Solana\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "trade"
    assert events[0].event_time.isoformat() == "2024-12-06T12:09:15+00:00"
    assert events[0].asset == "SOL"
    assert events[0].quantity == Decimal("0.5")
    assert events[0].quote_asset == "USDC"
    assert events[0].quote_quantity == Decimal("100")
    assert events[0].fee_asset == "SOL"
    assert events[0].fee_quantity == Decimal("0.001")
    assert events[0].tx_id == "tx-1"
    assert events[0].account == "Solana"


def test_blockpit_derivative_loss_keeps_negative_cashflow(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="blockpit",
        filename="blockpit.csv",
        content=(
            "Date (UTC);Integration Name;Label;Outgoing Asset;Outgoing Amount;"
            "Incoming Asset;Incoming Amount;Fee Asset (optional);Fee Amount (optional);"
            "Comment (optional);Trx. ID (optional);Source Type;Source Name\n"
            "06.12.2024 12:09:15;Bitget;Derivative Loss;USDT;73.67;;;;;tx-2;API;Bitget\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "derivative"
    assert events[0].asset == "USDT"
    assert events[0].quantity == Decimal("-73.67")


def test_blockpit_interest_creates_reward_event(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="blockpit",
        filename="blockpit.csv",
        content=(
            "Date (UTC);Integration Name;Label;Outgoing Asset;Outgoing Amount;"
            "Incoming Asset;Incoming Amount;Fee Asset (optional);Fee Amount (optional);"
            "Comment (optional);Trx. ID (optional);Source Type;Source Name\n"
            "02.05.2026 23:59:59;Binance;Interest;;;JUP;0.2512438;;;;reward-1;API;Binance\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "reward"
    assert events[0].asset == "JUP"
    assert events[0].quantity == Decimal("0.2512438")
    assert events[0].quote_asset is None
    assert events[0].quote_quantity is None


def test_blockpit_transfer_does_not_self_quote_incoming_asset(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="blockpit",
        filename="blockpit.csv",
        content=(
            "Date (UTC);Integration Name;Label;Outgoing Asset;Outgoing Amount;"
            "Incoming Asset;Incoming Amount;Fee Asset (optional);Fee Amount (optional);"
            "Comment (optional);Trx. ID (optional);Source Type;Source Name\n"
            "12.01.2024 05:00:21;Solana;Deposit;;;IOT;5624.359439;SOL;0.00001;;tx-3;Chain;Solana\n"
        ),
    )

    events = RawNormalizer(store).normalize_batch(batch.batch_id)

    assert len(events) == 1
    assert events[0].event_type == "transfer"
    assert events[0].asset == "IOT"
    assert events[0].quantity == Decimal("5624.359439")
    assert events[0].quote_asset is None
    assert events[0].quote_quantity is None
    assert events[0].fee_asset == "SOL"
    assert events[0].fee_quantity == Decimal("0.00001")
