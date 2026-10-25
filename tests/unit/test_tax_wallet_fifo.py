from datetime import datetime, timezone
from decimal import Decimal
import argparse
import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient
import httpx

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.admin import AdminSettingWrite
from steuerreport_v2.contracts.events import CanonicalEvent, CanonicalEventCreate
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.contracts.review import ReviewDecisionCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_methodology import TaxMethodologyService
from steuerreport_v2.domain.tax_wallet_fifo import (
    WalletFifoPreviewService,
    _SolanaProgramEscrowAnchor,
)
from steuerreport_v2.contracts.tax_wallet_fifo import (
    WalletFifoGapDiagnosis,
    WalletFifoProvenanceEvent,
    WalletFifoSolanaOriginTrace,
)


def test_wallet_fifo_loads_alchemy_api_key_from_admin_secret(tmp_path, monkeypatch):
    monkeypatch.delenv("ALCHEMY_API_KEY", raising=False)
    monkeypatch.delenv("ALCHEMY_SOLANA_API_KEY", raising=False)
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.upsert_admin_setting(
        AdminSettingWrite(key="secret.alchemy.api_key", value_json='"alchemy-secret"')
    )

    assert WalletFifoPreviewService(store)._alchemy_api_key() == "alchemy-secret"


def test_wallet_fifo_solana_delta_maps_case_sensitive_cwif_mint(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    service = WalletFifoPreviewService(store)
    mint = "7atgF8KQo4wJrD5ATGX7t1V2zVvykPJbFfNeVf1icFv1"

    rows = service._token_deltas_by_owner(
        pre=[],
        post=[
            {
                "owner": "wallet",
                "mint": mint,
                "uiTokenAmount": {"uiAmountString": "11310642.83"},
            }
        ],
    )

    assert len(rows) == 1
    assert rows[0].mint == mint
    assert rows[0].asset == "CWIF"
    assert rows[0].delta_quantity == Decimal("11310642.83")


def test_wallet_fifo_solana_program_escrow_precedes_same_tx_fee_mirror(
    tmp_path, monkeypatch
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    service = WalletFifoPreviewService(store)
    wallet = service.PRIMARY_SOLANA_WALLET
    opened_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    source_at = datetime(2024, 2, 1, tzinfo=timezone.utc)
    target_at = datetime(2024, 2, 2, tzinfo=timezone.utc)
    opening = CanonicalEvent(
        event_id="opening",
        source="solana_rpc",
        event_time=opened_at,
        event_type="income",
        asset="SOL",
        quantity=Decimal("1"),
        account=wallet,
        confidence=Decimal("1"),
    )
    fee_mirror = CanonicalEvent(
        event_id="fee-mirror",
        source="solana_rpc",
        event_time=source_at,
        event_type="transfer",
        asset="SOL",
        quantity=Decimal("0.0000103"),
        tx_id="source-tx",
        account=wallet,
        confidence=Decimal("1"),
    )
    source = CanonicalEvent(
        event_id="escrow-source",
        source="solana_rpc",
        event_time=source_at,
        event_type="transfer",
        asset="SOL",
        quantity=Decimal("-0.00513286"),
        fee_asset="SOL",
        fee_quantity=Decimal("0.0000103"),
        tx_id="source-tx",
        account=wallet,
        confidence=Decimal("1"),
    )
    target = CanonicalEvent(
        event_id="escrow-target",
        source="solana_rpc",
        event_time=target_at,
        event_type="transfer",
        asset="SOL",
        quantity=Decimal("0.005117545"),
        tx_id="target-tx",
        account=wallet,
        confidence=Decimal("1"),
    )
    events = [opening, fee_mirror, source, target]
    anchor = _SolanaProgramEscrowAnchor(
        source_event_id=source.event_id,
        target_event_id=target.event_id,
        source_pool_id=service._pool_id(source),
        escrow_pool_id=f"solana_program_escrow:{source.event_id}",
        target_pool_id=service._pool_id(target),
        asset="SOL",
        gross_quantity=abs(source.quantity),
        return_quantity=target.quantity,
        fee_quantity=abs(source.quantity) - target.quantity,
    )
    monkeypatch.setattr(
        service, "_events_with_source_timezone_utc", lambda _events: events
    )
    monkeypatch.setattr(
        service,
        "_solana_program_escrow_anchors",
        lambda _events: {source.event_id: anchor},
    )

    state = service.replay()

    assert state.unmatched == []
    assert [trace.status for trace in state.transfer_traces] == [
        "solana_program_escrow_outbound",
        "solana_program_escrow_return",
    ]
    assert sum(
        lot.quantity_remaining
        for lot in state.open_lots
        if lot.pool_id == service._pool_id(source) and lot.asset == "SOL"
    ) == Decimal("0.999984685")


def test_wallet_fifo_excludes_evidence_net_zero_fee_reclassification(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = WalletFifoPreviewService.PRIMARY_SOLANA_WALLET
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2026, 6, 12, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("0.000030776"),
                fee_asset="SOL",
                fee_quantity=Decimal("0.000030776"),
                tx_id="fee-reclassification",
                account=wallet,
            )
        ]
    )

    state = WalletFifoPreviewService(store).replay()

    assert state.unmatched == []
    assert state.open_lots == []
    assert len(state.transfer_traces) == 1
    assert (
        state.transfer_traces[0].status
        == "solana_evidence_net_zero_fee_reclassification"
    )
    assert state.transfer_traces[0].carried_cost_basis_eur == 0


def test_wallet_fifo_marks_evidence_bound_spl_dust_nonblocking(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = WalletFifoPreviewService.PRIMARY_SOLANA_WALLET
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="solana_rpc",
            filename="solana-token-account-evidence.json",
            file_hash="unit:token-dust",
        )
    )
    raw = store.add_raw_objects(
        batch.batch_id,
        [
            RawObjectCreate(
                row_number=1,
                payload_json=json.dumps(
                    {
                        "movement_classification": "direct_token_transfer",
                        "evidence_artifact": "var/solana_token_account_coverage/unit.json",
                        "classification_reason": "checked_token_transfer",
                    }
                ),
            )
        ],
    )[0]
    store.add_price_point(
        PricePointCreate(
            asset="USDC",
            price_eur=Decimal("1"),
            priced_at=datetime(2024, 11, 28, tzinfo=timezone.utc),
            source="unit",
        )
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 11, 28, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDC",
                quantity=Decimal("0.000001"),
                tx_id="spl-dust",
                account=wallet,
                raw_object_id=raw.raw_object_id,
            )
        ]
    )

    state = WalletFifoPreviewService(store).replay()

    assert state.unmatched == []
    assert len(state.open_lots) == 1
    assert len(state.transfer_traces) == 1
    assert state.transfer_traces[0].status == "resolved_by_documented_solana_token_dust"


def test_wallet_fifo_carries_binance_withdrawal_into_legacy_helium_wallet(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    service = WalletFifoPreviewService(store)
    legacy_wallet = service.MAIN_HELIUM_LEGACY_WALLET
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="evidence",
            filename="wallet-fifo-legacy-binance-evidence.json",
            file_hash="unit:legacy-binance-withdrawal",
        )
    )
    raw = store.add_raw_objects(
        batch.batch_id,
        [
            RawObjectCreate(
                row_number=1,
                payload_json=json.dumps(
                    {
                        "Account": "Spot",
                        "Change": "-96.529374",
                        "Coin": "HNT",
                        "Operation": "Withdraw",
                        "Time": "21-06-22 11:02:02",
                    }
                ),
            ),
            RawObjectCreate(
                row_number=2,
                payload_json=json.dumps(
                    {
                        "date": "22.06.2021 08:58",
                        "hnt_amount": "96,479374",
                        "payee": legacy_wallet,
                        "payer": "BinanceLegacyPayer",
                        "transaction_hash": "legacy-onchain-tx",
                        "type": "payment_v1",
                    }
                ),
            ),
        ],
    )
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("10"),
            priced_at=datetime(2021, 6, 22, tzinfo=timezone.utc),
            source="unit",
        )
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2021, 6, 1, tzinfo=timezone.utc),
                event_type="income",
                asset="HNT",
                quantity=Decimal("100"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2021, 6, 22, 8, 58, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("96.479374"),
                tx_id="legacy-onchain-tx",
                account=legacy_wallet,
                raw_object_id=raw[1].raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2021, 6, 22, 9, 2, 2, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("-96.529374"),
                account="Spot",
                raw_object_id=raw[0].raw_object_id,
            ),
        ]
    )
    source_evidence = service._raw_evidence(raw[0].raw_object_id)
    assert source_evidence is not None
    source_evidence.filename = "Binance-Transaction-History(UTC+2).xlsx"
    original_raw_evidence_map = service._raw_evidence_map

    def evidence_map(raw_ids):
        result = original_raw_evidence_map(raw_ids)
        if raw[0].raw_object_id in result:
            result[raw[0].raw_object_id] = source_evidence
        return result

    service._raw_evidence_map = evidence_map

    state = service.replay()

    assert state.unmatched == []
    bridge = next(
        trace for trace in state.transfer_traces if trace.tx_id == "legacy-onchain-tx"
    )
    assert bridge.status == "cross_cex_transfer_evidence_partial"
    assert bridge.quantity == Decimal("96.479374")
    assert bridge.fee_quantity == Decimal("0.05")
    assert bridge.source_pool_id == "binance:Spot"
    assert bridge.target_pool_id == f"helium:{legacy_wallet}"


def test_wallet_fifo_preserves_exact_defi_position_principal_lot(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = WalletFifoPreviewService.PRIMARY_SOLANA_WALLET
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="solana_rpc",
            filename="solana-token-account-evidence.json",
            file_hash="unit:defi-position-principal",
        )
    )
    raw = store.add_raw_objects(
        batch.batch_id,
        [
            RawObjectCreate(row_number=1, payload_json=json.dumps({"side": "out"})),
            RawObjectCreate(
                row_number=2,
                payload_json=json.dumps(
                    {
                        "movement_classification": "defi_position_transfer",
                        "classification_reason": "position_withdraw_instruction",
                        "instruction_labels": "Burn|ClosePositionV0|WithdrawV0|transfer",
                        "evidence_artifact": "var/solana_token_account_coverage/unit.json",
                    }
                ),
            ),
        ],
    )
    store.add_price_point(
        PricePointCreate(
            asset="IOT",
            price_eur=Decimal("0.001"),
            priced_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
            source="unit",
        )
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2023, 1, 1, tzinfo=timezone.utc),
                event_type="income",
                asset="IOT",
                quantity=Decimal("34687.714944"),
                account=wallet,
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2023, 5, 14, tzinfo=timezone.utc),
                event_type="transfer",
                asset="IOT",
                quantity=Decimal("-34687.714944"),
                tx_id="position-lock",
                account=wallet,
                raw_object_id=raw[0].raw_object_id,
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2025, 12, 20, tzinfo=timezone.utc),
                event_type="transfer",
                asset="IOT",
                quantity=Decimal("34687.714944"),
                tx_id="position-return",
                account=wallet,
                raw_object_id=raw[1].raw_object_id,
            ),
        ]
    )

    state = WalletFifoPreviewService(store).replay()

    assert state.unmatched == []
    assert len(state.open_lots) == 1
    assert state.open_lots[0].quantity_remaining == Decimal("34687.714944")
    assert state.open_lots[0].acquired_at == datetime(2023, 1, 1, tzinfo=timezone.utc)
    principal = next(
        trace
        for trace in state.transfer_traces
        if trace.status == "solana_defi_position_principal_return"
    )
    assert principal.quantity == Decimal("34687.714944")
    assert principal.lots_moved == 1
    assert principal.carried_cost_basis_eur == Decimal("34.687714944")


def test_wallet_fifo_preserves_aggregated_hnt_position_principal_lot(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = WalletFifoPreviewService.PRIMARY_SOLANA_WALLET
    position_mint = "DvoPSyDUou8qQWRK4K1hipN6wtkGk2PW1CfX8kUVvR4K"
    hnt_mint = "hntyVP6YFm1Hg25TN9WGLqM12b8TQmcknKrdu1oxWux"
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="solana_rpc",
            filename="solana-position-roundtrip.json",
            file_hash="unit:aggregated-hnt-position-principal",
        )
    )
    raw = store.add_raw_objects(
        batch.batch_id,
        [
            RawObjectCreate(
                row_number=1,
                payload_json=json.dumps(
                    {
                        "event_type": "swap_in_aggregated",
                        "raw_row": str(
                            {
                                "jupiter_aggregated": True,
                                "from_asset": hnt_mint,
                                "from_quantity": "800",
                                "to_asset": position_mint,
                                "to_quantity": "1",
                            }
                        ),
                    }
                ),
            ),
            RawObjectCreate(
                row_number=2,
                payload_json=json.dumps(
                    {
                        "event_type": "swap_in_aggregated",
                        "raw_row": str(
                            {
                                "jupiter_aggregated": True,
                                "from_asset": position_mint,
                                "from_quantity": "1",
                                "to_asset": hnt_mint,
                                "to_quantity": "800",
                            }
                        ),
                    }
                ),
            ),
        ],
    )
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("2"),
            priced_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
            source="unit",
        )
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2023, 1, 1, tzinfo=timezone.utc),
                event_type="income",
                asset="HNT",
                quantity=Decimal("800"),
                account=wallet,
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2023, 8, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("-800"),
                tx_id="hnt-position-lock",
                account=wallet,
                raw_object_id=raw[0].raw_object_id,
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 4, 25, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("800"),
                tx_id="hnt-position-return",
                account=wallet,
                raw_object_id=raw[1].raw_object_id,
            ),
        ]
    )

    state = WalletFifoPreviewService(store).replay()

    assert state.unmatched == []
    assert len(state.open_lots) == 1
    assert state.open_lots[0].quantity_remaining == Decimal("800")
    assert state.open_lots[0].acquired_at == datetime(2023, 1, 1, tzinfo=timezone.utc)
    principal = next(
        trace
        for trace in state.transfer_traces
        if trace.status == "solana_defi_position_principal_return"
    )
    assert principal.source_event_id is not None
    assert principal.target_event_id is not None
    assert principal.quantity == Decimal("800")
    assert principal.carried_cost_basis_eur == Decimal("1600")


def test_wallet_fifo_carries_linked_bitget_hot_wallet_withdrawal(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = WalletFifoPreviewService.PRIMARY_SOLANA_WALLET
    tx_id = "bitget-solana-withdrawal"
    artifact = tmp_path / "token-account-audit.json"
    artifact.write_text(
        json.dumps(
            {
                "targets": [
                    {
                        "asset": "USDT",
                        "transactions": [
                            {
                                "signature": tx_id,
                                "signers": [
                                    "CySAjqmKLQCT729gypchz3zbYSSNh85rXx8Tk9e7PC7P"
                                ],
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="evidence",
            filename="bitget-solana-withdrawal-evidence.json",
            file_hash="unit:bitget-solana-withdrawal",
        )
    )
    raw = store.add_raw_objects(
        batch.batch_id,
        [
            RawObjectCreate(
                row_number=1,
                payload_json=json.dumps(
                    {
                        "Action": "WITHDRAW",
                        "Coin": "USDT",
                        "Quantity": "-1988.008261",
                    }
                ),
            ),
            RawObjectCreate(
                row_number=2,
                payload_json=json.dumps(
                    {
                        "movement_classification": "direct_token_transfer",
                        "classification_reason": "checked_token_transfer",
                        "evidence_artifact": str(artifact),
                    }
                ),
            ),
        ],
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.95"),
            priced_at=datetime(2024, 12, 1, tzinfo=timezone.utc),
            source="unit",
        )
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="bitget",
                event_time=datetime(2024, 12, 1, 12, tzinfo=timezone.utc),
                event_type="income",
                asset="USDT",
                quantity=Decimal("2000"),
                account="bitget",
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 12, 1, 13, 32, 32, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("1988.008260"),
                tx_id=tx_id,
                account=wallet,
                raw_object_id=raw[1].raw_object_id,
            ),
            CanonicalEventCreate(
                source="bitget",
                event_time=datetime(2024, 12, 1, 13, 33, 12, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("-1988.008261"),
                fee_asset="USDT",
                fee_quantity=Decimal("-1.5"),
                account="bitget",
                raw_object_id=raw[0].raw_object_id,
            ),
        ]
    )

    state = WalletFifoPreviewService(store).replay()

    assert state.unmatched == []
    bridge = next(trace for trace in state.transfer_traces if trace.tx_id == tx_id)
    assert bridge.status == "cross_cex_transfer_evidence_partial"
    assert bridge.source_pool_id == "bitget:bitget"
    assert bridge.target_pool_id == f"solana_rpc:{wallet}"
    assert bridge.quantity == Decimal("1988.008260")
    assert bridge.fee_quantity == Decimal("1.500001")


def test_solana_provenance_batch_alchemy_alias_redacts_secret(tmp_path, monkeypatch):
    script_path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "run_wallet_fifo_solana_provenance_batch_20260620.py"
    )
    spec = importlib.util.spec_from_file_location(
        "solana_provenance_batch_script", script_path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.upsert_admin_setting(
        AdminSettingWrite(key="secret.alchemy.api_key", value_json='"alchemy-secret"')
    )
    service = WalletFifoPreviewService(store)

    resolved = module._resolve_rpc_url(service, "alchemy")
    assert resolved == "https://solana-mainnet.g.alchemy.com/v2/alchemy-secret"

    payload = module._build_result(
        run_id="run-test",
        args=argparse.Namespace(
            year=2024, asset="SOL", pool_id="pool", provider="rpc", rpc_url="alchemy"
        ),
        db_path=tmp_path / "steuerreport_v2.duckdb",
        rpc_url=resolved,
        batch_size=1,
        max_events=1,
        total_events=0,
        classifications_by_event={},
        batches=[],
    )
    assert payload["rpc_url"] == "alchemy_admin_secret"
    assert "alchemy-secret" not in json.dumps(payload)


def test_legacy_helium_overview_keeps_fairspot_as_fifo_evidence_not_portfolio(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    main = WalletFifoPreviewService.MAIN_HELIUM_LEGACY_WALLET
    fairspot = WalletFifoPreviewService.FAIRSPOT_STAKING_WALLET
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="helium",
            filename="helium-fairspot-payment-v2.csv",
            file_hash="unit:fairspot",
        )
    )
    store.add_raw_objects(
        batch.batch_id,
        [
            RawObjectCreate(
                row_number=1,
                payload_json=(
                    '{"date":"23.06.2021 20:26","type":"payment_v2",'
                    '"transaction_hash":"Kk7ZTefj1fQOZ-1rPwt4aIOXpTmckgt8JA28IJ6XF_8",'
                    '"hnt_amount":"100","payer":"'
                    + main
                    + '","payee":"'
                    + fairspot
                    + '"}'
                ),
            ),
            RawObjectCreate(
                row_number=2,
                payload_json=(
                    '{"date":"08.07.2021 18:30","type":"payment_v2",'
                    '"transaction_hash":"tLOGE2C0v-CGYSJfvKU6KvI7oQq4OALrz3rh6SbC8Qs",'
                    '"hnt_amount":"99,75","payer":"'
                    + fairspot
                    + '","payee":"'
                    + main
                    + '"}'
                ),
            ),
        ],
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2021, 6, 23, 20, 26, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("-100"),
                account=main,
                tx_id="Kk7ZTefj1fQOZ-1rPwt4aIOXpTmckgt8JA28IJ6XF_8",
                raw_object_id="raw-main-to-fairspot",
            ),
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2021, 7, 8, 18, 30, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("99.75"),
                account=main,
                tx_id="tLOGE2C0v-CGYSJfvKU6KvI7oQq4OALrz3rh6SbC8Qs",
                raw_object_id="raw-fairspot-to-main",
            ),
        ]
    )

    report = WalletFifoPreviewService(store).legacy_helium_overview()
    client = TestClient(create_app(store))
    response = client.get("/api/v1/tax/legacy-helium-overview")

    main_wallet = next(
        item for item in report.wallets if item.role == "main_legacy_wallet"
    )
    fairspot_wallet = next(
        item for item in report.wallets if item.role == "staking_counterparty"
    )
    assert main_wallet.included_in_portfolio is False
    assert fairspot_wallet.included_in_portfolio is False
    assert main_wallet.transfer_events_count == 2
    assert main_wallet.net_hnt_quantity == Decimal("-0.250000000000000000")
    assert report.fairspot_transfers_count == 2
    assert [item.direction for item in report.fairspot_transfers] == [
        "main_to_fairspot",
        "fairspot_to_main",
    ]
    assert report.fairspot_transfers[1].quantity == Decimal("99.75")
    assert report.included_in_portfolio_count == 0
    assert response.status_code == 200
    assert response.json()["data"]["included_in_portfolio_count"] == 0


def test_wallet_fifo_preview_carries_lot_through_own_transfer(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="SOL",
                quantity=Decimal("10"),
                quote_asset="EUR",
                quote_quantity=Decimal("100"),
                account="spot",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("-4"),
                account="spot",
                tx_id="own-transfer-1",
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 2, 1, 0, 5, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("4"),
                account="wallet-main",
                tx_id="own-transfer-1",
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="SOL",
                quantity=Decimal("-4"),
                quote_asset="EUR",
                quote_quantity=Decimal("80"),
                account="wallet-main",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    report = WalletFifoPreviewService(store).preview(year=2024)

    assert report.status == "preview"
    assert report.transfer_traces_count == 1
    assert report.tax_lines_count == 1
    assert report.unmatched_count == 0
    line = report.sample_lines[0]
    assert line.pool_id == "solana_rpc:wallet-main"
    assert line.acquisition_cost_eur == Decimal(
        "40.000000000000000000000000000000000000"
    )
    assert line.disposal_proceeds_eur == Decimal("80.000000000000000000")
    assert line.gain_loss_eur == Decimal("40.000000000000000000000000000000000000")


def test_wallet_fifo_preview_infers_internal_cross_pool_transfer_target(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("10"),
                quote_asset="EUR",
                quote_quantity=Decimal("20"),
                account="Funding",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("10"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("-10"),
                quote_asset="EUR",
                quote_quantity=Decimal("50"),
                account="Spot",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    report = WalletFifoPreviewService(store).preview(year=2024)

    assert report.status == "preview"
    assert report.unmatched_count == 0
    assert report.transfer_traces_count == 1
    trace = report.transfer_traces[0]
    assert trace.status == "inferred_cross_pool"
    assert trace.source_pool_id == "binance:Funding"
    assert trace.target_pool_id == "binance:Spot"
    assert trace.quantity == Decimal("10.000000000000000000")
    assert report.tax_lines_count == 1
    assert report.sample_lines[0].gain_loss_eur == Decimal(
        "30.000000000000000000000000000000000000"
    )


def test_wallet_fifo_preview_anchors_binance_withdrawal_net_to_solana_and_consumes_fee(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    withdrawal_batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance_withdrawal_api",
            filename="binance-withdrawal-api-20250323-20250324-JUP.json",
            file_hash="withdrawal-api",
        )
    )
    store.add_raw_object(
        withdrawal_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=(
                '{"asset":"JUP","amount":"5530.555703","transaction_fee":"1.72",'
                '"gross_amount":"5532.275703","address":"6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",'
                '"network":"SOL","tx_id":"withdraw-tx","complete_time":"2025-03-23 13:49:42"}'
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="JUP",
                quantity=Decimal("6000"),
                quote_asset="EUR",
                quote_quantity=Decimal("600"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 3, 23, 15, 49, 42, tzinfo=timezone.utc),
                event_type="transfer",
                asset="JUP",
                quantity=Decimal("-5532.275703"),
                account="Spot",
            ),
        ]
    )

    report = WalletFifoPreviewService(store).preview(year=2025)

    assert report.unmatched_count == 0
    assert report.transfer_traces_count == 1
    trace = report.transfer_traces[0]
    assert trace.source_pool_id == "binance:Spot"
    assert (
        trace.target_pool_id == "solana_rpc:6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"
    )
    assert trace.quantity == Decimal("5530.555703")
    assert trace.fee_quantity == Decimal("1.72")
    assert report.tax_lines_count == 1
    assert report.sample_lines[0].source_event_id == "external:withdraw-tx:fee"
    assert report.sample_lines[0].quantity == Decimal("1.72")


def test_wallet_fifo_preview_anchors_binance_sol_withdrawal_net_to_solana_and_consumes_fee(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    withdrawal_batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance_withdrawal_api",
            filename="binance-withdrawal-api-20241124-SOL.json",
            file_hash="withdrawal-api-sol",
        )
    )
    store.add_raw_object(
        withdrawal_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=(
                '{"asset":"SOL","amount":"1.12889582","transaction_fee":"0.008",'
                '"gross_amount":"1.13689582","address":"6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",'
                '"network":"SOL","tx_id":"withdraw-sol-tx","complete_time":"2024-11-24 07:24:42"}'
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2024, 11, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="SOL",
                quantity=Decimal("2"),
                quote_asset="EUR",
                quote_quantity=Decimal("200"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2024, 11, 24, 9, 24, 42, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("-1.13689582"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 11, 24, 7, 19, 30, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("1.12889582"),
                account="6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
                tx_id="withdraw-sol-tx",
            ),
        ]
    )

    report = WalletFifoPreviewService(store).preview(year=2024)

    assert report.unmatched_count == 0
    assert report.transfer_traces_count == 1
    assert report.unresolved_inbound_provenance_count == 0
    trace = report.transfer_traces[0]
    assert trace.source_pool_id == "binance:Spot"
    assert (
        trace.target_pool_id == "solana_rpc:6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"
    )
    assert trace.quantity == Decimal("1.12889582")
    assert trace.fee_quantity == Decimal("0.008")
    assert trace.status == "ok"
    assert not trace.target_event_id.startswith("external:")
    assert report.tax_lines_count == 1
    assert report.sample_lines[0].source_event_id == "external:withdraw-sol-tx:fee"
    assert report.sample_lines[0].quantity == Decimal("0.008")


def test_wallet_fifo_preview_carries_binance_withdrawal_api_evidence_without_balance_event(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    withdrawal_batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance_withdrawal_api",
            filename="binance-withdrawal-api-20260727-JUP.json",
            file_hash="withdrawal-api-evidence-only",
        )
    )
    withdrawal_raw = store.add_raw_object(
        withdrawal_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=(
                '{"asset":"JUP","amount":"5530.555703","transaction_fee":"1.72",'
                '"gross_amount":"5532.275703","address":"6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",'
                '"network":"SOL","tx_id":"withdraw-api-tx","operation":"Withdraw",'
                '"complete_time":"2026-07-27 21:30:50"}'
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2026, 7, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="JUP",
                quantity=Decimal("6000"),
                quote_asset="EUR",
                quote_quantity=Decimal("600"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2026, 7, 27, 21, 28, 52, tzinfo=timezone.utc),
                event_type="transfer",
                asset="JUP",
                quantity=Decimal("5530.555703"),
                account="6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
                tx_id="withdraw-api-tx",
            ),
            CanonicalEventCreate(
                source="binance_withdrawal_api",
                event_time=datetime(2026, 7, 27, 21, 30, 50, tzinfo=timezone.utc),
                event_type="unknown",
                asset="JUP",
                quantity=Decimal("0"),
                account="Binance Withdrawal Evidence",
                tx_id="withdraw-api-tx",
                raw_object_id=withdrawal_raw.raw_object_id,
            ),
        ]
    )

    report = WalletFifoPreviewService(store).preview(year=2026)

    assert report.unmatched_count == 0
    assert report.unresolved_inbound_provenance_count == 0
    assert report.transfer_traces_count == 1
    trace = report.transfer_traces[0]
    assert trace.status == "ok"
    assert trace.source_pool_id == "binance:Spot"
    assert trace.target_pool_id == (
        "solana_rpc:6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"
    )
    assert trace.quantity == Decimal("5530.555703")
    assert trace.fee_quantity == Decimal("1.72")
    assert trace.carry_mode == "binance_withdrawal_api_lot_carry"
    assert trace.evidence_status == "binance_withdrawal_api_txid_address_match"
    assert trace.evidence_raw_object_id == withdrawal_raw.raw_object_id
    assert trace.evidence_batch_id == withdrawal_batch.batch_id
    assert trace.evidence_filename == "binance-withdrawal-api-20260727-JUP.json"
    assert trace.evidence_row_number == 1
    assert trace.evidence_operation == "Withdraw"
    assert report.tax_lines_count == 1
    assert report.sample_lines[0].source_event_id == "external:withdraw-api-tx:fee"
    assert report.sample_lines[0].quantity == Decimal("1.72")


def test_wallet_fifo_preview_blocks_sale_from_pool_without_lot(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("10"),
                quote_asset="EUR",
                quote_quantity=Decimal("20"),
                account="spot",
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("-3"),
                quote_asset="EUR",
                quote_quantity=Decimal("12"),
                account="wallet-main",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    report = WalletFifoPreviewService(store).preview(year=2024)

    assert report.status == "blocked"
    assert report.unmatched_count == 1
    assert report.unmatched[0].pool_id == "solana_rpc:wallet-main"
    assert report.unmatched[0].reason.startswith("trade_disposal_without_wallet_lot")
    assert report.global_gain_loss_eur == Decimal(
        "6.000000000000000000000000000000000000"
    )
    assert report.wallet_gain_loss_eur == Decimal("0")
    assert report.delta_gain_loss_eur == Decimal(
        "-6.000000000000000000000000000000000000"
    )


def test_wallet_fifo_preview_uses_net_acquired_quantity_and_net_quote_proceeds_for_fees(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2022, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("10"),
                quote_asset="EUR",
                quote_quantity=Decimal("20"),
                fee_asset="HNT",
                fee_quantity=Decimal("0.1"),
                account="pionex",
            ),
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2022, 2, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("-9.9"),
                quote_asset="EUR",
                quote_quantity=Decimal("30"),
                fee_asset="EUR",
                fee_quantity=Decimal("0.3"),
                account="pionex",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    report = WalletFifoPreviewService(store).preview(year=2022)

    assert report.unmatched_count == 0
    assert report.tax_lines_count == 1
    assert report.sample_lines[0].quantity == Decimal("9.9")
    assert report.sample_lines[0].acquisition_cost_eur == Decimal("20")
    assert report.sample_lines[0].disposal_proceeds_eur == Decimal("29.7")
    assert report.sample_lines[0].gain_loss_eur == Decimal("9.7")


def test_wallet_fifo_preview_exposes_opening_gap_after_same_asset_acquisition_fees(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2022, 4, 12, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("74.32236512"),
                quote_asset="EUR",
                quote_quantity=Decimal("100"),
                fee_asset="HNT",
                fee_quantity=Decimal("0.13513319"),
                account="pionex",
            ),
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2022, 9, 9, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("-74.356"),
                quote_asset="EUR",
                quote_quantity=Decimal("357.434788"),
                fee_asset="EUR",
                fee_quantity=Decimal("0.17871739"),
                account="pionex",
            ),
        ]
    )

    report = WalletFifoPreviewService(store).preview(year=2022)

    assert report.unmatched_count == 1
    assert report.unmatched[0].matched_quantity == Decimal("74.18723193")
    assert report.unmatched[0].missing_quantity == Decimal("0.16876807")


def test_wallet_fifo_preview_api(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("1"),
                quote_asset="EUR",
                quote_quantity=Decimal("10000"),
                account="spot",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 2, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("-1"),
                quote_asset="EUR",
                quote_quantity=Decimal("12000"),
                account="spot",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()
    client = TestClient(create_app(store))

    all_years = client.get("/api/v1/tax/wallet-fifo-preview")
    before_disposal = client.get(
        "/api/v1/tax/wallet-fifo-preview",
        params={"year": 2025, "as_of": "2025-01-15T00:00:00Z"},
    )
    year = client.get("/api/v1/tax-years/2025/wallet-fifo-delta")

    assert all_years.status_code == 200
    assert before_disposal.status_code == 200
    assert before_disposal.json()["data"]["tax_lines_count"] == 0
    assert before_disposal.json()["data"]["input_events_count"] == 1
    assert year.status_code == 200
    assert year.json()["data"]["tax_lines_count"] == 1
    assert year.json()["data"]["year_deltas"][0]["year"] == 2025


def test_wallet_fifo_preview_uses_persistent_cache_after_process_cache_clear(
    tmp_path, monkeypatch
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("1"),
                quote_asset="EUR",
                quote_quantity=Decimal("10000"),
                account="spot",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 2, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("-1"),
                quote_asset="EUR",
                quote_quantity=Decimal("12000"),
                account="spot",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()
    service = WalletFifoPreviewService(store)

    first = service.preview(year=2025)
    cache_key = service._preview_cache_key(2025)
    cache_path = service._preview_disk_cache_path(cache_key)
    assert first.tax_lines_count == 1
    assert cache_path.exists()

    WalletFifoPreviewService._PREVIEW_CACHE.clear()

    def fail_build(*_args, **_kwargs):
        raise AssertionError("preview should be read from persistent cache")

    monkeypatch.setattr(WalletFifoPreviewService, "_build_preview", fail_build)
    second = WalletFifoPreviewService(store).preview(year=2025)

    assert second.tax_lines_count == first.tax_lines_count
    assert second.global_gain_loss_eur == first.global_gain_loss_eur


def test_wallet_fifo_preview_cache_is_invalidated_by_price_import(
    tmp_path, monkeypatch
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("1"),
                quote_asset="EUR",
                quote_quantity=Decimal("10000"),
                account="spot",
            )
        ]
    )
    TaxService(store).rebuild_fifo()
    service = WalletFifoPreviewService(store)
    first = service.preview(year=2025)
    old_cache_key = service._preview_cache_key(2025)

    store.add_price_point(
        PricePointCreate(
            asset="BTC",
            price_eur=Decimal("11000"),
            priced_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
            source="test",
        )
    )
    new_cache_key = service._preview_cache_key(2025)
    assert new_cache_key != old_cache_key

    WalletFifoPreviewService._PREVIEW_CACHE.clear()
    rebuilt = False

    def record_build(*_args, **_kwargs):
        nonlocal rebuilt
        rebuilt = True
        return first.model_copy(deep=True)

    monkeypatch.setattr(WalletFifoPreviewService, "_build_preview", record_build)
    WalletFifoPreviewService(store).preview(year=2025)

    assert rebuilt is True


def test_wallet_fifo_gap_diagnosis_finds_prior_same_pool_inbound(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 20, 0, 39, 31, tzinfo=timezone.utc),
                event_type="transfer",
                asset="JUP",
                quantity=Decimal("8427.293653"),
                account="Spot",
                tx_id="inbound-jup",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 20, 0, 39, 56, tzinfo=timezone.utc),
                event_type="trade",
                asset="USDT",
                quantity=Decimal("249.584133318392421418"),
                quote_asset="JUP",
                quote_quantity=Decimal("254.859911993559057132"),
                account="Spot",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    service = WalletFifoPreviewService(store)
    preview = service.preview(year=2025)
    report = service.gap_diagnosis(2025)

    assert preview.unmatched_count == 0
    assert preview.unresolved_inbound_provenance_count == 1
    assert preview.transfer_traces[0].status == "unresolved_inbound_provenance"
    assert report.gaps_count == 0


def test_wallet_fifo_gap_diagnosis_api(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 20, 0, 39, 56, tzinfo=timezone.utc),
                event_type="trade",
                asset="USDT",
                quantity=Decimal("1"),
                quote_asset="JUP",
                quote_quantity=Decimal("2"),
                account="Spot",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()
    response = TestClient(create_app(store)).get(
        "/api/v1/tax-years/2025/wallet-fifo-gaps"
    )

    assert response.status_code == 200
    assert response.json()["data"]["gaps_count"] == 1


def test_wallet_fifo_origin_trace_links_transaction_and_deposit_history(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    transaction_batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Transaction-History.xlsx",
            file_hash="tx-history",
        )
    )
    transaction_raw = store.add_raw_object(
        transaction_batch.batch_id,
        RawObjectCreate(
            row_number=7965,
            payload_json=(
                '{"Account":"Spot","Change":"8427.293653","Coin":"JUP",'
                '"Operation":"Deposit","Remark":null,"Time":"25-01-20 00:39:31"}'
            ),
        ),
    )
    deposit_batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Deposit-History.xlsx",
            file_hash="deposit-history",
        )
    )
    store.add_raw_object(
        deposit_batch.batch_id,
        RawObjectCreate(
            row_number=4,
            payload_json=(
                '{"Address":"Ftf2dgeRpBrPFmbd4wQWWqSjCmRjGes1GzNXtxKETeLW",'
                '"Amount":"8427.293653","Coin":"JUP","Network":"SOL",'
                '"Status":"Completed","TXID":"solana-tx","Time":"25-01-20 00:39:17"}'
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 20, 0, 39, 31, tzinfo=timezone.utc),
                event_type="transfer",
                asset="JUP",
                quantity=Decimal("8427.293653"),
                account="Spot",
                raw_object_id=transaction_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 20, 0, 39, 56, tzinfo=timezone.utc),
                event_type="trade",
                asset="USDT",
                quantity=Decimal("249.584133318392421418"),
                quote_asset="JUP",
                quote_quantity=Decimal("254.859911993559057132"),
                account="Spot",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    preview = WalletFifoPreviewService(store).preview(year=2025)
    report = WalletFifoPreviewService(store).origin_trace(
        2025, asset="JUP", pool_id="binance:Spot"
    )

    assert preview.unresolved_inbound_provenance_count == 1
    assert report.traces_count == 1
    trace = report.traces[0]
    assert trace.likely_cause == "unresolved_inbound_transfer_or_opening_balance"
    assert trace.candidate_event is not None
    assert trace.candidate_event.relation == "provisional_same_pool_inbound"
    assert trace.transaction_history_evidence is not None
    assert trace.transaction_history_evidence.row_number == 7965
    assert trace.deposit_history_evidence is not None
    assert trace.deposit_history_evidence.row_number == 4
    assert trace.onchain_tx_id == "solana-tx"
    assert trace.deposit_address == "Ftf2dgeRpBrPFmbd4wQWWqSjCmRjGes1GzNXtxKETeLW"
    assert trace.network == "SOL"


def test_wallet_fifo_provenance_priorities_group_unresolved_inbounds(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    transaction_batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Transaction-History.xlsx",
            file_hash="tx-history-priority",
        )
    )
    transaction_raw = store.add_raw_object(
        transaction_batch.batch_id,
        RawObjectCreate(
            row_number=7965,
            payload_json=(
                '{"Account":"Spot","Change":"8427.293653","Coin":"JUP",'
                '"Operation":"Deposit","Remark":null,"Time":"25-01-20 00:39:31"}'
            ),
        ),
    )
    deposit_batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Deposit-History.xlsx",
            file_hash="deposit-history-priority",
        )
    )
    store.add_raw_object(
        deposit_batch.batch_id,
        RawObjectCreate(
            row_number=4,
            payload_json=(
                '{"Address":"Ftf2dgeRpBrPFmbd4wQWWqSjCmRjGes1GzNXtxKETeLW",'
                '"Amount":"8427.293653","Coin":"JUP","Network":"SOL",'
                '"Status":"Completed","TXID":"solana-tx","Time":"25-01-20 00:39:17"}'
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 20, 0, 39, 31, tzinfo=timezone.utc),
                event_type="transfer",
                asset="JUP",
                quantity=Decimal("8427.293653"),
                account="Spot",
                tx_id="solana-tx",
                raw_object_id=transaction_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 20, 0, 39, 56, tzinfo=timezone.utc),
                event_type="trade",
                asset="USDT",
                quantity=Decimal("249.584133318392421418"),
                quote_asset="JUP",
                quote_quantity=Decimal("254.859911993559057132"),
                account="Spot",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    report = WalletFifoPreviewService(store).provenance_priorities(2025)

    assert report.unresolved_inbound_provenance_count == 1
    assert report.groups_count == 1
    group = report.groups[0]
    assert group.asset == "JUP"
    assert group.pool_id == "binance:Spot"
    assert group.events_count == 1
    assert group.raw_evidence_count == 1
    assert group.deposit_evidence_count == 1
    assert group.onchain_tx_id_count == 1
    assert group.evidence_status == "deposit_evidence_ready"
    assert (
        group.samples[0].deposit_address
        == "Ftf2dgeRpBrPFmbd4wQWWqSjCmRjGes1GzNXtxKETeLW"
    )


def test_wallet_fifo_provenance_closure_summarizes_unverified_cex_and_opening_balance(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    deposit_batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Deposit-History.xlsx",
            file_hash="closure-deposit",
        )
    )
    deposit_raw = store.add_raw_object(
        deposit_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "Address": "Ftf2dgeRpBrPFmbd4wQWWqSjCmRjGes1GzNXtxKETeLW",
                    "Amount": "1.4",
                    "Coin": "SOL",
                    "Network": "SOL",
                    "Status": "Completed",
                    "TXID": "closure-sol-tx",
                    "Time": "24-01-12 07:09:33",
                }
            ),
        ),
    )
    opening_batch = store.create_import_batch(
        ImportBatchCreate(
            source="opening-balance-scope-test",
            filename="opening-balance-adjustments.csv",
            file_hash="closure-opening",
        )
    )
    opening_raw = store.add_raw_object(
        opening_batch.batch_id,
        RawObjectCreate(
            row_number=2,
            payload_json=json.dumps(
                {
                    "time": "2024-02-15T07:28:31",
                    "asset": "USDT",
                    "amount": "1988.008263",
                    "type": "opening transfer",
                    "account": "wallet",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2024, 1, 12, 7, 9, 33, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("1.4"),
                account="binance",
                tx_id="closure-sol-tx",
                raw_object_id=deposit_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2024, 1, 12, 7, 10, tzinfo=timezone.utc),
                event_type="trade",
                asset="USDT",
                quantity=Decimal("100"),
                quote_asset="SOL",
                quote_quantity=Decimal("1.4"),
                account="binance",
            ),
            CanonicalEventCreate(
                source="opening-balance-scope-test",
                event_time=datetime(2024, 2, 15, 7, 28, 31, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("1988.008263"),
                account="wallet",
                raw_object_id=opening_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="manual-csv",
                event_time=datetime(2024, 12, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="EUR",
                quantity=Decimal("1000"),
                quote_asset="USDT",
                quote_quantity=Decimal("1988.008263"),
                account="wallet",
            ),
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("90"),
            priced_at=datetime(2024, 1, 12, tzinfo=timezone.utc),
            source="unit",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.93"),
            priced_at=datetime(2024, 2, 15, tzinfo=timezone.utc),
            source="unit",
        )
    )
    TaxService(store).rebuild_fifo()

    report = WalletFifoPreviewService(store).provenance_closure_report(2024)
    response = TestClient(create_app(store)).get(
        "/api/v1/tax-years/2024/wallet-fifo-provenance-closure"
    )

    statuses = {item.category: item.closure_status for item in report.items}
    assert statuses["cex_deposit_sender_ownership"] == "unverified_cex_deposit_sender"
    assert statuses["opening_balance"] == "documented_non_live_opening_balance"
    assert report.documented_non_live_count == 1
    assert report.unverified_cex_count == 1
    assert report.review_required_count == 1
    assert response.status_code == 200
    assert response.json()["data"]["documented_non_live_count"] == 1


def test_wallet_fifo_provenance_closure_documents_binance_fiat_purchase(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Fiat-Buy-History.xlsx",
            file_hash="fiat-buy",
        )
    )
    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=3,
            payload_json=json.dumps(
                {
                    "Fee": "20.00 EUR",
                    "Method": "Credit Card",
                    "Price": "0.83801222 USDT/EUR",
                    "Receive Amount": "1169.434027 USDT",
                    "Spend Amount": "1000.00 EUR",
                    "Status": "Successful",
                    "Time": "21-04-19 17:16:48",
                    "Transaction ID": "fiat-buy-tx",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2021, 4, 19, 17, 16, 48, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("1169.434027"),
                quote_asset="EUR",
                quote_quantity=Decimal("1000"),
                account="binance",
                tx_id="fiat-buy-tx",
                raw_object_id=raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2021, 4, 20, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("10"),
                quote_asset="USDT",
                quote_quantity=Decimal("100"),
                account="binance",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    report = WalletFifoPreviewService(store).provenance_closure_report(2021)
    item = report.items[0]

    assert item.category == "fiat_purchase"
    assert item.closure_status == "documented_fiat_purchase"
    assert item.requires_review is False
    assert report.documented_fiat_purchase_count == 1
    assert report.review_required_count == 0


def test_wallet_fifo_provenance_closure_documents_moonpay_apple_pay_onramp(
    tmp_path, monkeypatch
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = "GmHYjZGkcHBZ3WyGZ9eUGDZMfHvJTLtTKXu6dnSc63yu"
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="solana_rpc",
            filename="jup_wallet_solscan_balance_change_2026-05-27.json",
            file_hash="moonpay-apple-pay-sol",
        )
    )
    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "source": "solana_rpc",
                    "signature": "moonpay-sol-tx",
                    "event_type": "sol_transfer",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2026, 1, 1, 14, 49, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("1.972"),
                account=wallet,
                tx_id="moonpay-sol-tx",
                raw_object_id=raw.raw_object_id,
            ),
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("80"),
            priced_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            source="unit",
        )
    )
    artifact_dir = tmp_path / "solana_batches"
    artifact_dir.mkdir()
    artifact = artifact_dir / "latest_2026_SOL_provenance_classification.json"
    artifact.write_text(
        json.dumps(
            {
                "run_id": "run-moonpay",
                "generated_at": "2026-07-05T11:30:00+00:00",
                "year": 2026,
                "asset": "SOL",
                "pool_id": f"solana_rpc:{wallet}",
                "provider": "rpc",
                "total_events": 1,
                "classified_count": 1,
                "own_transfer_candidates_count": 0,
                "external_or_unknown_count": 1,
                "failed_count": 0,
                "classifications": [
                    {
                        "event_id": "event-1",
                        "signature": "moonpay-sol-tx",
                        "status": "external_or_unknown_origin",
                        "asset": "SOL",
                        "expected_amount": "1.972",
                        "matched_amount": "1.972",
                        "sender_owner": WalletFifoPreviewService.MOONPAY_APPLE_PAY_SOLANA_SENDER,
                        "receiver_owner": wallet,
                        "sender_is_known_own_wallet": False,
                        "receiver_is_known_own_wallet": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        WalletFifoPreviewService, "DEFAULT_SOLANA_PROVENANCE_BATCH_DIR", artifact_dir
    )
    TaxService(store).rebuild_fifo()

    report = WalletFifoPreviewService(store).provenance_closure_report(2026)

    assert report.review_required_count == 0
    assert report.items[0].category == "fiat_onramp_purchase"
    assert report.items[0].closure_status == "documented_moonpay_apple_pay_onramp"
    assert "keine FIFO-Fortfuehrung" in report.items[0].tax_treatment_hint


def test_wallet_fifo_provenance_closure_counts_partial_legacy_hnt_cex_deposit(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    helium_batch = store.create_import_batch(
        ImportBatchCreate(
            source="helium",
            filename="Heliumtracker 2021.xlsx",
            file_hash="legacy-hnt-cex",
        )
    )
    helium_raw_1 = store.add_raw_object(
        helium_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "Amount": "10",
                    "Receiver": "Binance",
                    "Sender": "133iWieuw...xU6WUW8v\u00a0",
                    "Time": "2021-09-05 at 03:14PM",
                }
            ),
        ),
    )
    helium_raw_2 = store.add_raw_object(
        helium_batch.batch_id,
        RawObjectCreate(
            row_number=2,
            payload_json=json.dumps(
                {
                    "Amount": "20",
                    "Receiver": "Binance",
                    "Sender": "133iWieuw...xU6WUW8v\u00a0",
                    "Time": "2021-09-06 at 03:14PM",
                }
            ),
        ),
    )
    deposit_batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Deposit-History.xlsx",
            file_hash="legacy-hnt-deposit",
        )
    )
    store.add_raw_object(
        deposit_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "Address": "138bCXPVfSq7yyTfoDUrVwztPmUr4WGyA7TED9Y41djmF7rjA8y",
                    "Amount": "10.004",
                    "Coin": "HNT",
                    "Network": "HNT",
                    "Status": "Completed",
                    "TXID": "legacy-hnt-deposit-tx",
                    "Time": "21-09-05 15:17:15",
                }
            ),
        ),
    )
    store.add_raw_object(
        deposit_batch.batch_id,
        RawObjectCreate(
            row_number=2,
            payload_json=json.dumps(
                {
                    "Address": "138bCXPVfSq7yyTfoDUrVwztPmUr4WGyA7TED9Y41djmF7rjA8y",
                    "Amount": "20.004",
                    "Coin": "HNT",
                    "Network": "HNT",
                    "Status": "Completed",
                    "TXID": "wrong-day-rounded-hnt-deposit-tx",
                    "Time": "21-09-05 18:00:00",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2021, 9, 5, 15, 14, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("10"),
                account="Binance",
                raw_object_id=helium_raw_1.raw_object_id,
            ),
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2021, 9, 6, 15, 14, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("20"),
                account="Binance",
                raw_object_id=helium_raw_2.raw_object_id,
            ),
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2021, 9, 7, tzinfo=timezone.utc),
                event_type="trade",
                asset="USDT",
                quantity=Decimal("90"),
                quote_asset="HNT",
                quote_quantity=Decimal("30"),
                account="Binance",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    report = WalletFifoPreviewService(store).provenance_closure_report(2021)

    assert report.documented_legacy_cex_deposit_count == 1
    item = report.items[0]
    assert item.closure_status == "review_required"
    assert item.requires_review is True
    assert "1 von 2" in item.tax_treatment_hint


def test_wallet_fifo_provenance_closure_documents_legacy_hnt_cex_deposit_mirror(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    helium_batch = store.create_import_batch(
        ImportBatchCreate(
            source="helium",
            filename="Heliumtracker 2021.xlsx",
            file_hash="legacy-hnt-mirror",
        )
    )
    helium_raw = store.add_raw_object(
        helium_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "Amount": "10",
                    "Receiver": "Binance",
                    "Sender": "133iWieuw...xU6WUW8v\u00a0",
                    "Time": "2021-09-05 at 03:14PM",
                }
            ),
        ),
    )
    deposit_batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Deposit-History.xlsx",
            file_hash="legacy-hnt-mirror-deposit",
        )
    )
    deposit_raw = store.add_raw_object(
        deposit_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "Address": "138bCXPVfSq7yyTfoDUrVwztPmUr4WGyA7TED9Y41djmF7rjA8y",
                    "Amount": "10.004",
                    "Coin": "HNT",
                    "Network": "HNT",
                    "Status": "Completed",
                    "TXID": "legacy-hnt-deposit-mirror-tx",
                    "Time": "21-09-05 15:17:15",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2021, 9, 5, 15, 14, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("10"),
                account="Binance",
                raw_object_id=helium_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2021, 9, 5, 15, 17, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("10.004"),
                account="binance",
                tx_id="legacy-hnt-deposit-mirror-tx",
                raw_object_id=deposit_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2021, 9, 6, tzinfo=timezone.utc),
                event_type="trade",
                asset="USDT",
                quantity=Decimal("90"),
                quote_asset="HNT",
                quote_quantity=Decimal("10.004"),
                account="binance",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    report = WalletFifoPreviewService(store).provenance_closure_report(2021)
    by_pool = {item.pool_id: item for item in report.items}

    assert report.documented_legacy_cex_deposit_count == 1
    assert report.documented_legacy_cex_deposit_mirror_count == 1
    assert (
        by_pool["helium:Binance"].closure_status == "documented_legacy_hnt_cex_deposit"
    )
    assert (
        by_pool["binance:binance"].closure_status
        == "documented_legacy_hnt_cex_deposit_mirror"
    )
    assert by_pool["binance:binance"].requires_review is False


def test_wallet_fifo_provenance_closure_counts_fairspot_staking_return(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    main_wallet = WalletFifoPreviewService.MAIN_HELIUM_LEGACY_WALLET
    fairspot = WalletFifoPreviewService.FAIRSPOT_STAKING_WALLET
    helium_batch = store.create_import_batch(
        ImportBatchCreate(
            source="helium",
            filename="helium-main-legacy.csv",
            file_hash="fairspot-return",
        )
    )
    fairspot_raw = store.add_raw_object(
        helium_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "date": "08.07.2021 18:30",
                    "hnt_amount": "99,75",
                    "payee": main_wallet,
                    "payer": fairspot,
                    "transaction_hash": "fairspot-return-tx",
                    "type": "payment_v2",
                }
            ),
        ),
    )
    unknown_raw = store.add_raw_object(
        helium_batch.batch_id,
        RawObjectCreate(
            row_number=2,
            payload_json=json.dumps(
                {
                    "date": "22.06.2021 08:58",
                    "hnt_amount": "96,479374",
                    "payee": main_wallet,
                    "payer": "14YeKFGXE23yAdACj6hu5NWEcYzzKxptYbm5jHgzw9A1P1UQfMv",
                    "transaction_hash": "unknown-legacy-inflow-tx",
                    "type": "payment_v1",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2021, 7, 8, 18, 30, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("99.75"),
                account=main_wallet,
                tx_id="fairspot-return-tx",
                raw_object_id=fairspot_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2021, 6, 22, 8, 58, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("96.479374"),
                account=main_wallet,
                tx_id="unknown-legacy-inflow-tx",
                raw_object_id=unknown_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2021, 7, 9, tzinfo=timezone.utc),
                event_type="trade",
                asset="USDT",
                quantity=Decimal("900"),
                quote_asset="HNT",
                quote_quantity=Decimal("196.229374"),
                account=main_wallet,
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    report = WalletFifoPreviewService(store).provenance_closure_report(2021)
    item = report.items[0]

    assert report.documented_fairspot_staking_return_count == 1
    assert report.documented_legacy_hnt_external_payment_count == 1
    assert item.pool_id == f"helium:{main_wallet}"
    assert item.closure_status == "documented_legacy_hnt_payment_provenance"
    assert item.requires_review is False
    assert "externe Legacy-HNT-Zahlung" in item.tax_treatment_hint


def test_wallet_fifo_provenance_closure_documents_legacy_counterparty_mirror(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    main_wallet = WalletFifoPreviewService.MAIN_HELIUM_LEGACY_WALLET
    service_wallet = "13xfSeV2UcVgUiTKmd9V1Htunc6N7wsAgkGRHtquN9hpCbA78Yp"
    short_service_wallet = "13xfSeV2U...pCbA78Yp\u00a0"
    helium_batch = store.create_import_batch(
        ImportBatchCreate(
            source="helium",
            filename="helium-main-service.csv",
            file_hash="legacy-counterparty-mirror",
        )
    )
    outflow_raw = store.add_raw_object(
        helium_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "date": "14.08.2021 17:15",
                    "hnt_amount": "100",
                    "payee": service_wallet,
                    "payer": main_wallet,
                    "transaction_hash": "main-to-service-tx",
                    "type": "payment_v2",
                }
            ),
        ),
    )
    mirror_raw = store.add_raw_object(
        helium_batch.batch_id,
        RawObjectCreate(
            row_number=2,
            payload_json=json.dumps(
                {
                    "Amount": "100",
                    "Receiver": short_service_wallet,
                    "Sender": "133iWieuw...xU6WUW8v\u00a0",
                    "Time": "2021-08-14 at 07:15PM",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2021, 8, 14, 17, 15, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("-100"),
                account=main_wallet,
                tx_id="main-to-service-tx",
                raw_object_id=outflow_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2021, 8, 14, 19, 15, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("100"),
                account=short_service_wallet,
                raw_object_id=mirror_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2021, 8, 15, tzinfo=timezone.utc),
                event_type="trade",
                asset="USDT",
                quantity=Decimal("900"),
                quote_asset="HNT",
                quote_quantity=Decimal("100"),
                account=short_service_wallet,
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    report = WalletFifoPreviewService(store).provenance_closure_report(2021)
    item = report.items[0]

    assert report.documented_legacy_counterparty_mirror_count == 1
    assert item.pool_id == f"helium:{short_service_wallet}"
    assert item.closure_status == "documented_legacy_counterparty_mirror"
    assert item.requires_review is False


def test_wallet_fifo_provenance_closure_documents_exchange_deposit_history(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="pionex",
            filename="deposit-withdraw.csv",
            file_hash="pionex-usdt-deposit",
        )
    )
    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "amount": "200.00000000",
                    "coin": "USDT",
                    "date(UTC+0)": "2021-12-25 16:23:04",
                    "fee": "0",
                    "network": "TRC20",
                    "tx_type": "DEPOSIT",
                    "txid": "b742f811bf6372301484d585166ebb0f334996185285c8fc91ced3830c724182",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2021, 12, 25, 16, 23, 4, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("200"),
                account="pionex",
                tx_id="b742f811bf6372301484d585166ebb0f334996185285c8fc91ced3830c724182",
                raw_object_id=raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2021, 12, 26, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("0.004"),
                quote_asset="USDT",
                quote_quantity=Decimal("200"),
                account="pionex",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    report = WalletFifoPreviewService(store).provenance_closure_report(2021)
    item = report.items[0]

    assert report.documented_exchange_deposit_history_count == 1
    assert item.pool_id == "pionex:pionex"
    assert item.closure_status == "documented_exchange_deposit_history"
    assert item.requires_review is False
    assert "Sender-Ownership" in item.tax_treatment_hint


def test_wallet_fifo_provenance_closure_documents_binance_btt_bttc_redenomination(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="transaction-history.csv",
            file_hash="btt-bttc-redenomination",
        )
    )
    outflow_raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "Account": "Spot",
                    "Change": "-4194.464",
                    "Coin": "BTT",
                    "Operation": "Token Swap - Redenomination/Rebranding",
                    "Time": "22-01-24 12:18:36",
                }
            ),
        ),
    )
    inflow_raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=2,
            payload_json=json.dumps(
                {
                    "Account": "Spot",
                    "Change": "4194464",
                    "Coin": "BTTC",
                    "Operation": "Airdrop Assets",
                    "Time": "22-01-24 18:47:31",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2021, 12, 31, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTTC",
                quantity=Decimal("4194.464"),
                quote_asset="USDT",
                quote_quantity=Decimal("25"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2022, 1, 24, 12, 18, 36, tzinfo=timezone.utc),
                event_type="transfer",
                asset="BTTC",
                quantity=Decimal("-4194.464"),
                account="Spot",
                raw_object_id=outflow_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2022, 1, 24, 18, 47, 31, tzinfo=timezone.utc),
                event_type="transfer",
                asset="BTTC",
                quantity=Decimal("4194464"),
                account="Spot",
                raw_object_id=inflow_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2022, 1, 25, tzinfo=timezone.utc),
                event_type="trade",
                asset="USDT",
                quantity=Decimal("100"),
                quote_asset="BTTC",
                quote_quantity=Decimal("4194464"),
                account="Spot",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    report = WalletFifoPreviewService(store).provenance_closure_report(2022)
    item = report.items[0]

    assert report.documented_token_redenomination_count == 1
    assert item.pool_id == "binance:Spot"
    assert item.closure_status == "documented_binance_btt_bttc_redenomination"
    assert item.requires_review is False
    assert "1:1000" in item.tax_treatment_hint


def test_wallet_fifo_provenance_closure_documents_manual_cex_deposit_history(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    manual_batch = store.create_import_batch(
        ImportBatchCreate(
            source="manual-csv",
            filename="btc-opening.csv",
            file_hash="manual-btc-deposit",
        )
    )
    manual_raw = store.add_raw_object(
        manual_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "account": "binance",
                    "amount": "0.01036997",
                    "asset": "BTC",
                    "quote_asset": "EUR",
                    "quote_quantity": "254.942392828916",
                    "source_ref": "btc-chain-tx",
                    "time": "2023-06-09T20:30:41Z",
                    "tx_id": "manual-opening:binance-btc-deposit-2023-06-09",
                    "type": "deposit",
                }
            ),
        ),
    )
    deposit_batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Deposit-History.xlsx",
            file_hash="btc-deposit-history",
        )
    )
    deposit_raw = store.add_raw_object(
        deposit_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "Address": "1KsYCTB1KgzLUz752NkEj9tnXUguaxaWox",
                    "Amount": "0.01036997",
                    "Coin": "BTC",
                    "Network": "BTC",
                    "Status": "Completed",
                    "TXID": "btc-chain-tx",
                    "Time": "23-06-09 20:30:41",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                source_ref="btc-chain-tx",
                event_time=datetime(2023, 6, 9, 20, 30, 41, tzinfo=timezone.utc),
                event_type="transfer",
                asset="BTC",
                quantity=Decimal("0.01036997"),
                account="binance",
                tx_id="btc-chain-tx",
                raw_object_id=deposit_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="manual-csv",
                event_time=datetime(2023, 6, 9, 20, 30, 41, tzinfo=timezone.utc),
                event_type="transfer",
                asset="BTC",
                quantity=Decimal("0.01036997"),
                quote_asset="EUR",
                quote_quantity=Decimal("254.942392828916"),
                account="binance",
                tx_id="manual-opening:binance-btc-deposit-2023-06-09",
                raw_object_id=manual_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="manual-csv",
                event_time=datetime(2023, 6, 10, tzinfo=timezone.utc),
                event_type="trade",
                asset="USDT",
                quantity=Decimal("300"),
                quote_asset="BTC",
                quote_quantity=Decimal("0.01036997"),
                account="binance",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    report = WalletFifoPreviewService(store).provenance_closure_report(2023)
    item = report.items[0]

    assert report.documented_manual_cex_deposit_count == 1
    assert item.pool_id == "binance:binance"
    assert item.evidence_status == "documented_manual_cex_deposit_history"
    assert item.closure_status == "documented_manual_cex_deposit_history"
    assert item.requires_review is False
    assert "Sender-Ownership" in item.tax_treatment_hint
    backlog = TaxMethodologyService(store).bmf_closure_backlog(year=2023)
    assert not any(
        item.blocker_type == "review_required"
        and item.asset == "BTC"
        and item.quantity_total == Decimal("0.01036997")
        for year in backlog.years
        for item in year.items
    )


def test_wallet_fifo_marks_reviewed_cex_exchange_outflow_anchor_as_resolved(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    txid = "cex-reviewed-deposit-tx"
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 6, 15, 9, 32, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="JUP",
                quantity=Decimal("4680.175116"),
                account="binance",
                tx_id=txid,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 6, 16, 9, 32, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="USDT",
                quantity=Decimal("100"),
                quote_asset="JUP",
                quote_quantity=Decimal("100"),
                account="binance",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()
    store.add_review_decision(
        ReviewDecisionCreate(
            decision_type="cex_exchange_outflow",
            scope=f"cex_exchange_outflow:year:2025:source:bitget:target:binance:network:SOL:deposit_tx:{txid}",
            title="CEX-zu-CEX-Transfer steuerneutral dokumentiert",
            rationale="Bitget Withdrawal und Binance Deposit sind gematcht.",
            evidence_ref="/api/v1/tax-years/2025/cex-exchange-outflow-evidence?source_exchange=bitget&target_cex=binance&network=SOL",
            actor="codex",
            source="unit-test",
            payload={
                "decision_status": "transfer_neutral_fifo_carry_forward_reviewed",
                "year": 2025,
                "source_exchange": "bitget",
                "target_cex": "binance",
                "network": "SOL",
                "deposit_txid": txid,
                "asset": "JUP",
            },
        )
    )

    service = WalletFifoPreviewService(store)
    preview = service.preview(year=2025)
    priorities = service.provenance_priorities(2025)
    origin = service.origin_trace(2025, asset="JUP", pool_id="binance:binance")

    assert preview.unresolved_inbound_provenance_count == 0
    assert (
        preview.transfer_traces[0].status == "resolved_by_cex_exchange_outflow_anchor"
    )
    assert preview.transfer_traces[0].source_pool_id == "cex_exchange_outflow_anchor"
    assert priorities.unresolved_inbound_provenance_count == 0
    assert priorities.groups_count == 0
    assert origin.traces_count == 0


def test_wallet_fifo_marks_reviewed_cex_sender_ownership_anchor_as_resolved(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    txid = "own-wallet-binance-deposit-tx"
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 20, 0, 39, 17, tzinfo=timezone.utc),
                event_type="transfer",
                asset="JUP",
                quantity=Decimal("8427.293653"),
                account="binance",
                tx_id=txid,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 21, 0, 39, 17, tzinfo=timezone.utc),
                event_type="trade",
                asset="USDT",
                quantity=Decimal("100"),
                quote_asset="JUP",
                quote_quantity=Decimal("100"),
                account="binance",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()
    store.add_review_decision(
        ReviewDecisionCreate(
            decision_type="cex_sender_ownership",
            scope=f"cex_sender_ownership:year:2025:cex:binance:network:SOL:tx:{txid}",
            title="CEX Deposit als steuerneutralen Transfer dokumentiert",
            rationale="Onchain-Sender ist eigene Solana-Wallet; Binance Deposit-Adresse ist belegt.",
            evidence_ref="/api/v1/tax-years/2025/cex-sender-ownership-latest?cex=binance&network=SOL",
            actor="codex",
            source="unit-test",
            payload={
                "decision_status": "tax_neutral_transfer_reviewed",
                "year": 2025,
                "cex": "binance",
                "network": "SOL",
                "txid": txid,
                "asset": "JUP",
                "onchain_sender": WalletFifoPreviewService.PRIMARY_SOLANA_WALLET,
                "deposit_address": "binance-deposit-address",
            },
        )
    )

    service = WalletFifoPreviewService(store)
    preview = service.preview(year=2025)
    priorities = service.provenance_priorities(2025)
    origin = service.origin_trace(2025, asset="JUP", pool_id="binance:binance")

    assert preview.unresolved_inbound_provenance_count == 0
    assert (
        preview.transfer_traces[0].status == "resolved_by_cex_sender_ownership_anchor"
    )
    assert preview.transfer_traces[0].source_pool_id == "cex_sender_ownership_anchor"
    assert priorities.unresolved_inbound_provenance_count == 0
    assert priorities.groups_count == 0
    assert origin.traces_count == 0


def test_wallet_fifo_provenance_priorities_api(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("200"),
                account="pionex",
            ),
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2025, 1, 2, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("0.001"),
                quote_asset="USDT",
                quote_quantity=Decimal("100"),
                account="pionex",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    response = TestClient(create_app(store)).get(
        "/api/v1/tax-years/2025/wallet-fifo-provenance-priorities"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["unresolved_inbound_provenance_count"] == 1
    assert data["groups"][0]["evidence_status"] == "missing_source_evidence"


def test_wallet_fifo_provenance_priorities_surface_withdrawal_outflow_evidence(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    withdrawal_batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance_withdrawal_api",
            filename="binance-withdrawal-api-USDT.json",
            file_hash="withdrawal-api-usdt-priority",
        )
    )
    withdrawal_raw = store.add_raw_object(
        withdrawal_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=(
                '{"asset":"USDT","amount":"100","transaction_fee":"1",'
                '"address":"6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",'
                '"network":"SOL","tx_id":"withdraw-usdt-tx","complete_time":"2025-02-01 12:00:00"}'
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 2, 1, 12, 0, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("-100"),
                account="Spot",
                raw_object_id=withdrawal_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2025, 2, 1, 12, 5, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("100"),
                account="6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
                tx_id="withdraw-usdt-tx",
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2025, 2, 2, tzinfo=timezone.utc),
                event_type="trade",
                asset="SOL",
                quantity=Decimal("1"),
                quote_asset="USDT",
                quote_quantity=Decimal("50"),
                account="6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    service = WalletFifoPreviewService(store)
    priority_report = service.provenance_priorities(2025)
    event_report = service.provenance_events(
        2025,
        asset="USDT",
        pool_id="solana_rpc:6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
    )

    group = priority_report.groups[0]
    assert group.evidence_status == "withdrawal_evidence_ready"
    assert group.local_outflow_candidate_count == 1
    assert group.exchange_outflow_candidate_count == 1
    assert group.withdrawal_evidence_ready_count == 1
    assert group.best_outflow_candidate is not None
    assert group.best_outflow_candidate.withdrawal_tx_id == "withdraw-usdt-tx"
    assert (
        group.best_outflow_candidate.withdrawal_address
        == "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"
    )
    event = event_report.events[0]
    assert event.evidence_status == "withdrawal_evidence_ready"
    assert event.best_outflow_candidate is not None
    assert event.best_outflow_candidate.withdrawal_network == "SOL"


def test_wallet_fifo_provenance_marks_bitget_internal_fund_transfer_not_withdrawal(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="bitget",
            filename="Spot Financial Record.csv",
            file_hash="bitget-internal-fund-transfer",
        )
    )
    raw_out = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=77,
            payload_json=(
                '{"Action":"TRANSFER_OUT","Type":"Fund transfer","Coin":"USDT",'
                '"Quantity":"-426.1090937","Order no.":"1248632144040288260",'
                '"Creation timestamp (+8 UTC)":"2024-12-06 02:23:42"}'
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="bitget",
                event_time=datetime(2024, 12, 5, 18, 23, 42, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("-426.1090937"),
                account="bitget",
                tx_id="1248632144040288260",
                raw_object_id=raw_out.raw_object_id,
            ),
            CanonicalEventCreate(
                source="bitget",
                event_time=datetime(2024, 12, 5, 18, 23, 42, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("426.1090937"),
                account="bitget",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    service = WalletFifoPreviewService(store)
    preview = service.preview(year=2024)
    report = service.provenance_priorities(2024)
    events = service.provenance_events(2024, asset="USDT", pool_id="bitget:bitget")

    assert preview.unresolved_inbound_provenance_count == 0
    assert preview.transfer_traces[0].status == "exchange_internal_principal_carry_basis_pending"
    assert preview.transfer_traces[0].source_pool_id == "bitget:bitget"
    assert preview.transfer_traces[0].evidence_status == "bitget_internal_fund_transfer"
    assert report.groups_count == 0
    assert events.events_count == 0


def test_wallet_fifo_provenance_marks_bitget_action_english_strategy_transfer_internal(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="bitget",
            filename="Futures Financial Record.csv",
            file_hash="bitget-action-english-strategy-transfer",
        )
    )
    raw_in = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=14,
            payload_json=json.dumps(
                {
                    "Action (English)": "trans_from_strategy",
                    "Coin": "USDT",
                    "Surplus/deduction (after fee)": "225.8188395",
                    "Timestamp UTC+8 (Order)": "2024-12-10 12:56:25",
                }
            ),
        ),
    )
    raw_out = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=15,
            payload_json=json.dumps(
                {
                    "Action (English)": "trans_to_strategy",
                    "Coin": "USDT",
                    "Surplus/deduction (after fee)": "-225.8188395",
                    "Timestamp UTC+8 (Order)": "2024-12-10 13:00:37",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="bitget",
                event_time=datetime(2024, 12, 10, 4, 56, 25, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("225.8188395"),
                account="bitget",
                raw_object_id=raw_in.raw_object_id,
            ),
            CanonicalEventCreate(
                source="bitget",
                event_time=datetime(2024, 12, 10, 5, 0, 37, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("-225.8188395"),
                account="bitget",
                raw_object_id=raw_out.raw_object_id,
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    service = WalletFifoPreviewService(store)
    preview = service.preview(year=2024)
    events = service.provenance_events(2024, asset="USDT", pool_id="bitget:bitget")
    gaps = service.exchange_evidence_gaps(2024, asset="USDT")

    assert preview.unresolved_inbound_provenance_count == 0
    assert preview.transfer_traces[0].status == "exchange_internal_principal_carry_basis_pending"
    assert preview.transfer_traces[0].source_pool_id == "bitget:bitget"
    assert preview.transfer_traces[0].evidence_status == "bitget_strategy_internal_transfer"
    assert events.events_count == 0
    assert gaps.gaps_count == 0


def test_wallet_fifo_provenance_marks_binance_simple_earn_subscription_internal(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    spot_batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Transaction-History.xlsx",
            file_hash="binance-simple-earn-subscription",
        )
    )
    raw_spot = store.add_raw_object(
        spot_batch.batch_id,
        RawObjectCreate(
            row_number=7960,
            payload_json=json.dumps(
                {
                    "Account": "Spot",
                    "Change": "-262.5153",
                    "Coin": "JUP",
                    "Operation": "Simple Earn Flexible Subscription",
                    "Remark": "Binance Earn",
                    "Time": "24-10-18 10:26:44",
                }
            ),
        ),
    )
    earn_batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance_simple_earn_api",
            filename="var/binance_simple_earn_history/20260531T095848Z",
            file_hash="binance-simple-earn-api",
        )
    )
    raw_earn = store.add_raw_object(
        earn_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "account_type": "simple_earn_flexible",
                    "amount": "262.5153",
                    "asset": "JUP",
                    "product_id": "JUP001",
                    "purchase_id": "7080981276",
                    "record_type": "flexible_subscription",
                    "source_ref": "flexible_subscription:JUP:JUP001:7080981276",
                    "status": "SUCCESS",
                    "time_iso": "2024-10-18T08:26:44+00:00",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2024, 10, 18, 10, 26, 44, tzinfo=timezone.utc),
                event_type="transfer",
                asset="JUP",
                quantity=Decimal("-262.5153"),
                account="Spot",
                raw_object_id=raw_spot.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance_simple_earn_api",
                event_time=datetime(2024, 10, 18, 8, 26, 44, tzinfo=timezone.utc),
                event_type="transfer",
                asset="JUP",
                quantity=Decimal("262.5153"),
                account="Binance Earn Flexible JUP001",
                tx_id="7080981276",
                source_ref="flexible_subscription:JUP:JUP001:7080981276",
                raw_object_id=raw_earn.raw_object_id,
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    service = WalletFifoPreviewService(store)
    preview = service.preview(year=2024)
    report = service.provenance_priorities(2024)
    events = service.provenance_events(
        2024,
        asset="JUP",
        pool_id="binance:Spot",
    )
    gaps = service.exchange_evidence_gaps(2024, asset="JUP")

    assert preview.unresolved_inbound_provenance_count == 0
    assert preview.transfer_traces[0].status == "exchange_internal_principal_carry_basis_pending"
    assert preview.transfer_traces[0].source_pool_id == "binance:Spot"
    assert preview.transfer_traces[0].evidence_status == "binance_internal_earn_transfer"
    assert report.groups_count == 0
    assert events.events_count == 0
    assert gaps.gaps_count == 0


def test_wallet_fifo_provenance_marks_binance_simple_earn_api_context_internal(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance_simple_earn_api",
            filename="var/binance_simple_earn_history/20260531T095848Z",
            file_hash="binance-simple-earn-api-roundtrip",
        )
    )
    raw_inbound = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "account_type": "simple_earn_flexible",
                    "amount": "7987.06455508",
                    "asset": "JUP",
                    "product_id": "JUP001",
                    "purchase_id": "7659945881",
                    "record_type": "flexible_subscription",
                    "source_ref": "flexible_subscription:JUP:JUP001:7659945881",
                    "status": "SUCCESS",
                    "time_iso": "2025-01-24T18:30:26+00:00",
                }
            ),
        ),
    )
    raw_outbound = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=2,
            payload_json=json.dumps(
                {
                    "account_type": "simple_earn_flexible",
                    "amount": "7987.17351339",
                    "asset": "JUP",
                    "product_id": "JUP001",
                    "redeem_id": "502519687",
                    "record_type": "flexible_redemption",
                    "source_ref": "flexible_redemption:JUP:JUP001:502519687",
                    "status": "SUCCESS",
                    "time_iso": "2025-01-24T23:46:40+00:00",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance_simple_earn_api",
                event_time=datetime(2025, 1, 24, 18, 30, 26, tzinfo=timezone.utc),
                event_type="transfer",
                asset="JUP",
                quantity=Decimal("7987.06455508"),
                account="Binance Earn Flexible JUP001",
                tx_id="7659945881",
                raw_object_id=raw_inbound.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance_simple_earn_api",
                event_time=datetime(2025, 1, 24, 23, 46, 40, tzinfo=timezone.utc),
                event_type="transfer",
                asset="JUP",
                quantity=Decimal("-7987.17351339"),
                account="Binance Earn Flexible JUP001",
                tx_id="502519687",
                raw_object_id=raw_outbound.raw_object_id,
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    service = WalletFifoPreviewService(store)
    preview = service.preview(year=2025)
    report = service.provenance_priorities(2025)
    events = service.provenance_events(
        2025,
        asset="JUP",
        pool_id="binance:Spot",
    )
    gaps = service.exchange_evidence_gaps(2025, asset="JUP")

    assert preview.unresolved_inbound_provenance_count == 0
    assert preview.transfer_traces[0].status == "exchange_internal_principal_carry_basis_pending"
    assert report.groups_count == 0
    assert events.events_count == 0
    assert gaps.gaps_count == 0


def test_wallet_fifo_provenance_marks_binance_transaction_history_earn_redemption_internal(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Transaction-History.xlsx",
            file_hash="binance-bnsol-earn-roundtrip",
        )
    )
    raw_purchase = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "Account": "Spot",
                    "Change": "22.32304223",
                    "Coin": "BNSOL",
                    "Operation": "SOL Staking - Purchase",
                    "Remark": None,
                    "Time": "25-02-28 06:55:47",
                }
            ),
        ),
    )
    raw_subscription = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=2,
            payload_json=json.dumps(
                {
                    "Account": "Spot",
                    "Change": "-22.32304223",
                    "Coin": "BNSOL",
                    "Operation": "Simple Earn Flexible Subscription",
                    "Remark": "Binance Earn",
                    "Time": "25-03-09 21:01:51",
                }
            ),
        ),
    )
    raw_redemption = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=3,
            payload_json=json.dumps(
                {
                    "Account": "Spot",
                    "Change": "22.32305193",
                    "Coin": "BNSOL",
                    "Operation": "Simple Earn Flexible Redemption",
                    "Remark": "Binance Earn",
                    "Time": "25-03-23 15:44:22",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 2, 28, 6, 55, 47, tzinfo=timezone.utc),
                event_type="trade",
                asset="BNSOL",
                quantity=Decimal("22.32304223"),
                quote_asset="SOL",
                quote_quantity=Decimal("23.189761"),
                account="Spot",
                raw_object_id=raw_purchase.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 3, 9, 21, 1, 51, tzinfo=timezone.utc),
                event_type="transfer",
                asset="BNSOL",
                quantity=Decimal("-22.32304223"),
                account="Spot",
                raw_object_id=raw_subscription.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 3, 23, 15, 44, 22, tzinfo=timezone.utc),
                event_type="transfer",
                asset="BNSOL",
                quantity=Decimal("22.32304223"),
                account="Spot",
                raw_object_id=raw_redemption.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 3, 23, 15, 44, 22, tzinfo=timezone.utc),
                event_type="income",
                asset="BNSOL",
                quantity=Decimal("0.00000970"),
                account="Spot",
                raw_object_id=raw_redemption.raw_object_id,
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    service = WalletFifoPreviewService(store)
    preview = service.preview(year=2025)
    report = service.provenance_priorities(2025)
    events = service.provenance_events(2025, asset="BNSOL", pool_id="binance:Spot")
    gaps = service.exchange_evidence_gaps(2025, asset="BNSOL")

    assert preview.unresolved_inbound_provenance_count == 0
    assert preview.transfer_traces[-1].status == "exchange_internal_principal_carry_in_place"
    assert preview.transfer_traces[-1].basis_missing_quantity == 0
    assert report.groups_count == 0
    assert events.events_count == 0
    assert gaps.gaps_count == 0


def test_wallet_fifo_internal_earn_carry_preserves_original_lot_and_reward_lot(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Transaction-History.xlsx",
            file_hash="binance-earn-fifo-carry-roundtrip",
        )
    )
    raw_subscription = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "Account": "Spot",
                    "Change": "-10",
                    "Coin": "JUP",
                    "Operation": "Simple Earn Flexible Subscription",
                    "Remark": "Binance Earn",
                    "Time": "25-01-02 00:00:00",
                }
            ),
        ),
    )
    raw_redemption = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=2,
            payload_json=json.dumps(
                {
                    "Account": "Spot",
                    "Change": "10",
                    "Coin": "JUP",
                    "Operation": "Simple Earn Flexible Redemption",
                    "Remark": "Binance Earn",
                    "Time": "25-01-03 00:00:00",
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
                asset="JUP",
                quantity=Decimal("10"),
                quote_asset="EUR",
                quote_quantity=Decimal("100"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 2, tzinfo=timezone.utc),
                event_type="transfer",
                asset="JUP",
                quantity=Decimal("-10"),
                account="Spot",
                raw_object_id=raw_subscription.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 3, tzinfo=timezone.utc),
                event_type="transfer",
                asset="JUP",
                quantity=Decimal("10"),
                account="Spot",
                raw_object_id=raw_redemption.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance_simple_earn_api",
                event_time=datetime(2025, 1, 3, 1, tzinfo=timezone.utc),
                event_type="reward",
                asset="JUP",
                quantity=Decimal("1"),
                quote_asset="EUR",
                quote_quantity=Decimal("2"),
                account="Binance Earn Flexible JUP001",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 4, tzinfo=timezone.utc),
                event_type="trade",
                asset="JUP",
                quantity=Decimal("-11"),
                quote_asset="EUR",
                quote_quantity=Decimal("220"),
                account="Spot",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    service = WalletFifoPreviewService(store)
    preview = service.preview(year=2025)
    carry = service.internal_transfer_carry_report(year=2025)

    assert preview.unmatched_count == 0
    assert preview.internal_transfer_carry_count == 2
    assert preview.internal_transfer_carry_fully_covered_count == 2
    assert preview.internal_transfer_carry_basis_pending_count == 0
    assert carry.status == "ready"
    assert carry.events_count == 2
    assert carry.carried_cost_basis_eur == Decimal("200")
    assert len(preview.sample_lines) == 2
    assert [line.acquired_at.day for line in preview.sample_lines] == [1, 3]
    assert sum(
        (line.acquisition_cost_eur for line in preview.sample_lines), Decimal("0")
    ) == Decimal("102")
    assert preview.wallet_gain_loss_eur == Decimal("118")


def test_wallet_fifo_internal_transfer_carry_api(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    response = TestClient(create_app(store)).get(
        "/api/v1/tax/wallet-fifo-internal-transfer-carry?year=2025"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["year"] == 2025
    assert data["status"] == "ready"
    assert data["events_count"] == 0
    assert data["method_version"] == WalletFifoPreviewService.METHOD_VERSION


def test_wallet_fifo_provenance_marks_binance_staking_redemption_internal(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Transaction-History.xlsx",
            file_hash="binance-hnt-staking-redemption",
        )
    )
    raw_redemption = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "Account": "Spot",
                    "Change": "42.66970598",
                    "Coin": "HNT",
                    "Operation": "Staking Redemption",
                    "Remark": None,
                    "Time": "22-02-24 02:36:41",
                    "User ID": "75432044",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2022, 2, 24, 2, 36, 41, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("42.66970598"),
                account="Spot",
                raw_object_id=raw_redemption.raw_object_id,
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    service = WalletFifoPreviewService(store)
    preview = service.preview(year=2022)
    report = service.provenance_priorities(2022)
    events = service.provenance_events(2022, asset="HNT", pool_id="binance:Spot")
    gaps = service.exchange_evidence_gaps(2022, asset="HNT")

    assert preview.unresolved_inbound_provenance_count == 0
    assert preview.transfer_traces[0].status == "exchange_internal_principal_carry_basis_pending"
    assert preview.transfer_traces[0].source_pool_id == "binance:Spot"
    assert report.groups_count == 0
    assert events.events_count == 0
    assert gaps.gaps_count == 0


def test_wallet_fifo_provenance_marks_binance_spot_futures_transfer_internal(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Transaction-History.xlsx",
            file_hash="binance-spot-futures-transfer",
        )
    )
    raw_spot = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "Account": "Spot",
                    "Change": "-5009.09824537",
                    "Coin": "USDT",
                    "Operation": "Transfer Between Spot Account and UM Futures Account",
                    "Remark": None,
                    "Time": "25-01-29 07:42:25",
                }
            ),
        ),
    )
    raw_futures = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=2,
            payload_json=json.dumps(
                {
                    "Account": "USD-M Futures",
                    "Change": "5009.09824537",
                    "Coin": "USDT",
                    "Operation": "Transfer Between Spot Account and UM Futures Account",
                    "Remark": None,
                    "Time": "25-01-29 07:42:25",
                }
            ),
        ),
    )
    raw_later_withdraw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=3,
            payload_json=json.dumps(
                {
                    "Account": "Spot",
                    "Change": "-5009.09824537",
                    "Coin": "USDT",
                    "Operation": "Withdraw",
                    "Remark": "Withdraw fee is included",
                    "Time": "25-01-29 07:56:41",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 28, 7, 42, 25, tzinfo=timezone.utc),
                event_type="trade",
                asset="USDT",
                quantity=Decimal("5009.09824537"),
                quote_asset="EUR",
                quote_quantity=Decimal("4750"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 29, 7, 42, 25, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("-5009.09824537"),
                account="Spot",
                raw_object_id=raw_spot.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 29, 7, 42, 25, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("5009.09824537"),
                account="USD-M Futures",
                raw_object_id=raw_futures.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 29, 7, 56, 41, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("-5009.09824537"),
                account="Spot",
                raw_object_id=raw_later_withdraw.raw_object_id,
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    service = WalletFifoPreviewService(store)
    preview = service.preview(year=2025)
    report = service.provenance_priorities(2025)
    events = service.provenance_events(
        2025, asset="USDT", pool_id="binance:USD-M_Futures"
    )
    gaps = service.exchange_evidence_gaps(2025, asset="USDT")

    assert preview.unresolved_inbound_provenance_count == 0
    assert preview.transfer_traces[0].status == "exchange_internal_cross_pool_lot_carry"
    assert preview.transfer_traces[0].source_pool_id == "binance:Spot"
    assert preview.transfer_traces[0].target_pool_id == "binance:USD-M_Futures"
    assert preview.transfer_traces[0].basis_missing_quantity == 0
    assert report.groups_count == 0
    assert events.events_count == 0
    assert gaps.gaps_count == 0


def test_wallet_fifo_provenance_marks_binance_auto_invest_redeem_inbound_internal(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Transaction-History.xlsx",
            file_hash="binance-auto-invest-redeem",
        )
    )
    raw_redeem = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "Account": "Spot",
                    "Change": "49.54531081",
                    "Coin": "ADA",
                    "Operation": "Index-auto-investment - Redeem Positions",
                    "Remark": None,
                    "Time": "25-11-27 08:26:17",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 11, 27, 8, 26, 17, tzinfo=timezone.utc),
                event_type="transfer",
                asset="ADA",
                quantity=Decimal("49.54531081"),
                account="Spot",
                raw_object_id=raw_redeem.raw_object_id,
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    service = WalletFifoPreviewService(store)
    preview = service.preview(year=2025)
    report = service.provenance_priorities(2025)
    events = service.provenance_events(2025, asset="ADA", pool_id="binance:Spot")
    raw_breakdown = service.raw_provenance_breakdown(2025)

    assert preview.unresolved_inbound_provenance_count == 0
    assert preview.transfer_traces[0].status == "exchange_internal_principal_carry_basis_pending"
    assert preview.transfer_traces[0].source_pool_id == "binance:Spot"
    assert preview.transfer_traces[0].evidence_status == "binance_internal_auto_invest_redemption"
    assert report.groups_count == 0
    assert events.events_count == 0
    assert raw_breakdown.groups_count == 0


def test_wallet_fifo_provenance_marks_bitget_strategy_inbound_internal(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="bitget",
            filename="Spot Financial Record.csv",
            file_hash="bitget-strategy-inbound",
        )
    )
    raw_inbound = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "Action": "STRATEGY_TRANSFER_IN",
                    "Coin": "HNT",
                    "Creation timestamp (+8 UTC)": "2024-04-17 13:19:02",
                    "Quantity": "33.422544",
                    "Type": "Fund transfer",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="bitget",
                event_time=datetime(2024, 4, 17, 5, 19, 2, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("33.422544"),
                account="bitget",
                raw_object_id=raw_inbound.raw_object_id,
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    service = WalletFifoPreviewService(store)
    preview = service.preview(year=2024)
    report = service.provenance_priorities(2024)
    raw_breakdown = service.raw_provenance_breakdown(2024)

    assert preview.unresolved_inbound_provenance_count == 0
    assert preview.transfer_traces[0].status == "exchange_internal_principal_carry_basis_pending"
    assert preview.transfer_traces[0].source_pool_id == "bitget:bitget"
    assert report.groups_count == 0
    assert raw_breakdown.groups_count == 0


def test_wallet_fifo_provenance_keeps_bitget_recharge_open(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="bitget",
            filename="Spot Financial Record.csv",
            file_hash="bitget-recharge-inbound",
        )
    )
    raw_inbound = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "Action": "RECHARGE",
                    "Coin": "USDT",
                    "Creation timestamp (+8 UTC)": "2024-03-07 23:54:40",
                    "Quantity": "55",
                    "Type": "Deposit",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="bitget",
                event_time=datetime(2024, 3, 7, 15, 54, 40, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("55"),
                account="bitget",
                raw_object_id=raw_inbound.raw_object_id,
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    service = WalletFifoPreviewService(store)
    preview = service.preview(year=2024)
    report = service.provenance_priorities(2024)
    raw_breakdown = service.raw_provenance_breakdown(2024)

    assert preview.unresolved_inbound_provenance_count == 1
    assert preview.transfer_traces[0].status == "unresolved_inbound_provenance"
    assert report.groups_count == 1
    assert raw_breakdown.groups_count == 1


def test_wallet_fifo_provenance_resolves_bitget_recharge_with_known_solana_outflow(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    bitget_batch = store.create_import_batch(
        ImportBatchCreate(
            source="bitget",
            filename="Spot Financial Record.csv",
            file_hash="bitget-recharge-with-solana-outflow",
        )
    )
    solana_batch = store.create_import_batch(
        ImportBatchCreate(
            source="solana_rpc",
            filename="solana-readonly.sqlite",
            file_hash="bitget-recharge-solana-outflow",
        )
    )
    raw_inbound = store.add_raw_object(
        bitget_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "Action": "RECHARGE",
                    "Coin": "USDT",
                    "Creation timestamp (+8 UTC)": "2024-03-07 23:54:40",
                    "Order no.": "'1149662750789283849",
                    "Quantity": "55",
                    "Type": "Deposit",
                    "UID": "operator-reference",
                }
            ),
        ),
    )
    raw_outflow = store.add_raw_object(
        solana_batch.batch_id,
        RawObjectCreate(
            row_number=2,
            payload_json=json.dumps(
                {
                    "asset": "ES9VMFRZACERMJFRF4H2FYD4KCONKY11MCCE8BENWNYB",
                    "event_type": "token_transfer",
                    "quantity": "55.000000",
                    "raw_row": str(
                        {
                            "meta": {
                                "preTokenBalances": [
                                    {
                                        "owner": "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
                                        "mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
                                        "uiTokenAmount": {
                                            "uiAmountString": "57.012482",
                                            "decimals": 6,
                                        },
                                    },
                                    {
                                        "owner": "4txxDLNGsGF1HyaW957fdhpnGbPxeuyEhA2V6x284kTN",
                                        "mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
                                        "uiTokenAmount": {
                                            "uiAmountString": "0",
                                            "decimals": 6,
                                        },
                                    },
                                ],
                                "postTokenBalances": [
                                    {
                                        "owner": "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
                                        "mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
                                        "uiTokenAmount": {
                                            "uiAmountString": "2.012482",
                                            "decimals": 6,
                                        },
                                    },
                                    {
                                        "owner": "4txxDLNGsGF1HyaW957fdhpnGbPxeuyEhA2V6x284kTN",
                                        "mint": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
                                        "uiTokenAmount": {
                                            "uiAmountString": "55",
                                            "decimals": 6,
                                        },
                                    },
                                ],
                            },
                            "transaction": {
                                "message": {
                                    "accountKeys": [
                                        {
                                            "pubkey": "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
                                            "signer": True,
                                            "writable": True,
                                        },
                                        {
                                            "pubkey": "4txxDLNGsGF1HyaW957fdhpnGbPxeuyEhA2V6x284kTN",
                                            "signer": False,
                                            "writable": True,
                                        },
                                    ]
                                }
                            },
                        }
                    ),
                    "side": "out",
                    "source": "solana_rpc",
                    "timestamp_utc": "2024-03-07T15:54:07+00:00",
                    "tx_id": "35dJxyr62S6DmwTXZs8qzQ19qew4h4XTD9wbRy87ucg4JqxYtXCgX1k6189P8X2mQ8LmKnh6w41CNYVgU2HbPJfW",
                    "wallet_address": "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 3, 7, 15, 54, 7, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("-55"),
                account="6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
                tx_id="35dJxyr62S6DmwTXZs8qzQ19qew4h4XTD9wbRy87ucg4JqxYtXCgX1k6189P8X2mQ8LmKnh6w41CNYVgU2HbPJfW",
                raw_object_id=raw_outflow.raw_object_id,
            ),
            CanonicalEventCreate(
                source="bitget",
                event_time=datetime(2024, 3, 7, 15, 54, 40, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("55"),
                account="bitget",
                tx_id="'1149662750789283849",
                raw_object_id=raw_inbound.raw_object_id,
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    service = WalletFifoPreviewService(store)
    preview = service.preview(year=2024)
    report = service.provenance_priorities(2024)
    raw_breakdown = service.raw_provenance_breakdown(2024)

    assert preview.unresolved_inbound_provenance_count == 0
    assert (
        preview.transfer_traces[0].status
        == "resolved_by_cex_deposit_local_onchain_match"
    )
    assert (
        preview.transfer_traces[0].source_pool_id
        == "solana_rpc:6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"
    )
    assert report.groups_count == 0
    assert raw_breakdown.groups_count == 0


def test_wallet_fifo_provenance_priorities_expose_status_breakdown_for_mixed_groups(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="bitget",
            filename="Spot Financial Record.csv",
            file_hash="bitget-mixed-breakdown",
        )
    )
    raw_withdrawish = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=(
                '{"Action":"WITHDRAW","Type":"Withdrawal","Coin":"USDT",'
                '"Quantity":"-100","Creation timestamp (+8 UTC)":"2024-12-10 13:00:00"}'
            ),
        ),
    )
    raw_internal = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=2,
            payload_json=(
                '{"Action":"TRANSFER_OUT","Type":"Fund transfer","Coin":"USDT",'
                '"Quantity":"-50","Creation timestamp (+8 UTC)":"2024-12-11 13:00:00"}'
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="bitget",
                event_time=datetime(2024, 12, 10, 5, 0, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("-100"),
                account="bitget",
                raw_object_id=raw_withdrawish.raw_object_id,
            ),
            CanonicalEventCreate(
                source="bitget",
                event_time=datetime(2024, 12, 10, 5, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("100"),
                account="bitget",
            ),
            CanonicalEventCreate(
                source="bitget",
                event_time=datetime(2024, 12, 11, 5, 0, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("-50"),
                account="bitget",
                raw_object_id=raw_internal.raw_object_id,
            ),
            CanonicalEventCreate(
                source="bitget",
                event_time=datetime(2024, 12, 11, 5, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("50"),
                account="bitget",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    report = WalletFifoPreviewService(store).provenance_priorities(2024)
    breakdown = {item.evidence_status: item for item in report.status_breakdown}

    assert report.groups[0].evidence_status == "exchange_outflow_candidate"
    assert report.groups[0].event_status_counts == {"exchange_outflow_candidate": 1}
    assert breakdown["exchange_outflow_candidate"].events_count == 1
    assert "exchange_internal_context" not in breakdown


def test_wallet_fifo_exchange_evidence_gaps_report_and_api(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="bitget",
            filename="Spot Financial Record.csv",
            file_hash="bitget-exchange-evidence-gap",
        )
    )
    raw_out = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=5,
            payload_json=(
                '{"Action":"WITHDRAW","Type":"Withdrawal","Coin":"USDT",'
                '"Quantity":"-225.8188395","Creation timestamp (+8 UTC)":"2024-12-10 13:00:37"}'
            ),
        ),
    )
    raw_in = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=6,
            payload_json=(
                '{"Action":"RECHARGE","Type":"Deposit","Coin":"USDT",'
                '"Quantity":"225.8188395","Creation timestamp (+8 UTC)":"2024-12-10 12:56:25"}'
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="bitget",
                event_time=datetime(2024, 12, 9, 0, 0, tzinfo=timezone.utc),
                event_type="transfer",
                asset="BTC",
                quantity=Decimal("1"),
                account="bitget",
            ),
            CanonicalEventCreate(
                source="bitget",
                event_time=datetime(2024, 12, 10, 5, 0, 37, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("-225.8188395"),
                account="bitget",
                raw_object_id=raw_out.raw_object_id,
            ),
            CanonicalEventCreate(
                source="bitget",
                event_time=datetime(2024, 12, 10, 4, 56, 25, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("225.8188395"),
                account="bitget",
                raw_object_id=raw_in.raw_object_id,
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    report = WalletFifoPreviewService(store).exchange_evidence_gaps(2024, limit=1)
    response = TestClient(create_app(store)).get(
        "/api/v1/tax-years/2024/wallet-fifo-exchange-evidence-gaps?limit=1"
    )

    assert report.gaps_count == 1
    gap = report.gaps[0]
    assert gap.asset == "USDT"
    assert gap.expected_evidence_source == "Bitget Deposit-Withdrawal History/API"
    assert gap.missing_fields == [
        "withdrawal_tx_id",
        "withdrawal_address",
        "withdrawal_network",
    ]
    assert gap.inbound_raw_evidence is not None
    assert gap.outflow_raw_evidence is not None
    assert response.status_code == 200
    assert response.json()["data"]["gaps_count"] == 1


def test_wallet_fifo_raw_provenance_breakdown_groups_raw_only_patterns_and_api(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    sol_batch = store.create_import_batch(
        ImportBatchCreate(
            source="solana_rpc",
            filename="solana-readonly.sqlite",
            file_hash="raw-breakdown-solana",
        )
    )
    sol_raw = store.add_raw_object(
        sol_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {"source": "solana_rpc", "signature": "solana-raw-tx"}
            ),
        ),
    )
    bitget_batch = store.create_import_batch(
        ImportBatchCreate(
            source="bitget",
            filename="Spot Financial Record.csv",
            file_hash="raw-breakdown-bitget",
        )
    )
    bitget_raw = store.add_raw_object(
        bitget_batch.batch_id,
        RawObjectCreate(
            row_number=2,
            payload_json=json.dumps(
                {
                    "Action": "RECHARGE",
                    "Coin": "USDT",
                    "Quantity": "42",
                    "Type": "Deposit",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("0.005"),
                account="6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
                tx_id="solana-raw-tx",
                raw_object_id=sol_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="bitget",
                event_time=datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("42"),
                account="bitget",
                raw_object_id=bitget_raw.raw_object_id,
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    report = WalletFifoPreviewService(store).raw_provenance_breakdown(2024)
    events = WalletFifoPreviewService(store).provenance_events(
        2024,
        asset="SOL",
        pool_id="solana_rpc:6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
    )
    response = TestClient(create_app(store)).get(
        "/api/v1/tax-years/2024/wallet-fifo-raw-provenance-breakdown?limit=10"
    )

    patterns = {group.raw_pattern: group for group in report.groups}
    assert events.events[0].evidence_status == "raw_transaction_evidence_only"
    assert patterns["solana_rpc_onchain_raw_tx"].events_count == 1
    assert (
        patterns["solana_rpc_onchain_raw_tx"].evidence_status
        == "raw_transaction_evidence_only"
    )
    assert patterns["bitget_raw_context"].events_count == 1
    assert response.status_code == 200
    assert response.json()["data"]["raw_transaction_evidence_only_count"] == 2
    assert response.json()["data"]["solana_tiny_raw_credit_count"] == 0


def test_wallet_fifo_opening_balance_evidence_reports_csv_row_and_api(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    account = "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="opening-balance-scope-test",
            filename="opening-balance-adjustments.csv",
            file_hash="opening-balance-evidence",
        )
    )
    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=7,
            payload_json=json.dumps(
                {
                    "time": "2024-02-15T07:28:31Z",
                    "asset": "USDT",
                    "amount": "1988.008263",
                    "type": "opening transfer",
                    "account": account,
                    "note": "Opening balance required before first negative balance",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="opening-balance-scope-test",
                event_time=datetime(2024, 2, 15, 7, 28, 31, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("1988.008263"),
                account=account,
                raw_object_id=raw.raw_object_id,
            )
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.93177"),
            priced_at=datetime(2024, 2, 15, tzinfo=timezone.utc),
            source="unit",
        )
    )
    TaxService(store).rebuild_fifo()

    report = WalletFifoPreviewService(store).opening_balance_evidence(
        2024, asset="USDT"
    )
    response = TestClient(create_app(store)).get(
        "/api/v1/tax-years/2024/wallet-fifo-opening-balance-evidence?asset=USDT"
    )

    assert report.rows_count == 1
    row = report.rows[0]
    assert row.asset == "USDT"
    assert row.account == account
    assert row.raw_filename == "opening-balance-adjustments.csv"
    assert row.raw_row_number == 7
    assert row.raw_payload["amount"] == "1988.008263"
    assert row.tax_classification == "opening_balance_evidence"
    assert row.live_balance_effect == "none"
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["rows_count"] == 1
    assert data["total_quantity_by_asset"]["USDT"] == "1988.008263000000000000"


def test_wallet_fifo_provenance_resolves_solana_tiny_raw_credit(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="solana_rpc",
            filename="solana-readonly.sqlite",
            file_hash="tiny-sol-resolved",
        )
    )
    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {"source": "solana_rpc", "signature": "tiny-sol-tx"}
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("0.000005"),
                account="6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
                tx_id="tiny-sol-tx",
                raw_object_id=raw.raw_object_id,
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    service = WalletFifoPreviewService(store)
    preview = service.preview(year=2024)
    report = service.provenance_priorities(2024)
    raw_breakdown = service.raw_provenance_breakdown(2024)

    assert preview.unresolved_inbound_provenance_count == 0
    assert preview.transfer_traces[0].status == "resolved_by_solana_tiny_raw_credit"
    assert preview.transfer_traces[0].source_pool_id == "solana_tiny_raw_credit"
    assert report.groups_count == 0
    assert raw_breakdown.groups_count == 0


def test_wallet_fifo_provenance_resolves_solana_helium_reward_claim_context(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="solana_rpc",
            filename="solana-readonly.sqlite",
            file_hash="helium-iot-claim-resolved",
        )
    )
    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "source": "solana_rpc",
                    "signature": "iot-claim-tx",
                    "defi_label": "claim",
                    "event_type": "token_transfer",
                    "raw_row": str(
                        {
                            "logMessages": [
                                "Program log: Instruction: SetCurrentRewardsWrapperV1",
                                "Program log: Instruction: SetCurrentRewardsV0",
                                "Program log: Instruction: DistributeCompressionRewardsV0",
                            ]
                        }
                    ),
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 4, 28, 12, 0, tzinfo=timezone.utc),
                event_type="transfer",
                asset="IOT",
                quantity=Decimal("898221.114046"),
                account="6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
                tx_id="iot-claim-tx",
                raw_object_id=raw.raw_object_id,
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    service = WalletFifoPreviewService(store)
    preview = service.preview(year=2024)
    report = service.provenance_priorities(2024)
    raw_breakdown = service.raw_provenance_breakdown(2024)

    assert preview.unresolved_inbound_provenance_count == 0
    assert (
        preview.transfer_traces[0].status == "resolved_by_solana_helium_reward_context"
    )
    assert preview.transfer_traces[0].source_pool_id == "helium_solana_reward_context"
    assert report.groups_count == 0
    assert raw_breakdown.groups_count == 0


def test_wallet_fifo_provenance_resolves_solana_helium_staking_reward_context(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="solana_rpc",
            filename="solana-readonly.sqlite",
            file_hash="helium-iot-staking-resolved",
        )
    )
    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "source": "solana_rpc",
                    "signature": "iot-staking-tx",
                    "defi_label": "staking",
                    "event_type": "token_transfer",
                    "raw_row": str(
                        {
                            "transaction": {
                                "message": {
                                    "accountKeys": [
                                        {
                                            "pubkey": "circAbx64bbsscPbQzZAUvuXpHqrCe6fLMzc2uKXz9g"
                                        }
                                    ]
                                }
                            },
                            "meta": {
                                "logMessages": [
                                    "Program circAbx64bbsscPbQzZAUvuXpHqrCe6fLMzc2uKXz9g invoke"
                                ]
                            },
                        }
                    ),
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 1, 18, 1, 28, 25, tzinfo=timezone.utc),
                event_type="transfer",
                asset="IOT",
                quantity=Decimal("164.879512"),
                account="6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
                tx_id="iot-staking-tx",
                raw_object_id=raw.raw_object_id,
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    service = WalletFifoPreviewService(store)
    preview = service.preview(year=2024)
    report = service.provenance_priorities(2024)
    raw_breakdown = service.raw_provenance_breakdown(2024)

    assert preview.unresolved_inbound_provenance_count == 0
    assert (
        preview.transfer_traces[0].status == "resolved_by_solana_helium_reward_context"
    )
    assert preview.transfer_traces[0].source_pool_id == "helium_solana_reward_context"
    assert report.groups_count == 0
    assert raw_breakdown.groups_count == 0


def test_wallet_fifo_solana_raw_provenance_priorities_join_latest_batch_artifact(
    tmp_path, monkeypatch
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="solana_rpc",
            filename="solana-readonly.sqlite",
            file_hash="solana-raw-priority",
        )
    )
    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "source": "solana_rpc",
                    "signature": "sig-priority",
                    "defi_label": "swap",
                    "event_type": "sol_transfer",
                    "raw_row": str(
                        {
                            "transaction": {
                                "message": {
                                    "accountKeys": [
                                        {
                                            "pubkey": "ExternalSigner111111111111111111111111111",
                                            "signer": True,
                                        },
                                        {
                                            "pubkey": "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
                                            "signer": False,
                                        },
                                    ],
                                    "instructions": [
                                        {
                                            "programId": "ComputeBudget111111111111111111111111111111"
                                        },
                                        {
                                            "programId": "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
                                        },
                                    ],
                                }
                            },
                            "meta": {
                                "innerInstructions": [
                                    {
                                        "instructions": [
                                            {
                                                "programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
                                            }
                                        ]
                                    }
                                ]
                            },
                        }
                    ),
                }
            ),
        ),
    )
    event = store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 11, 22, 19, 34, 42, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("15.261428266"),
                account="6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
                tx_id="sig-priority",
                raw_object_id=raw.raw_object_id,
            )
        ]
    )[0]
    TaxService(store).rebuild_fifo()
    artifact_dir = tmp_path / "solana_batches"
    artifact_dir.mkdir()
    (artifact_dir / "latest_2024_SOL_provenance_classification.json").write_text(
        json.dumps(
            {
                "classifications": [
                    {
                        "event_id": event.event_id,
                        "signature": "sig-priority",
                        "status": "external_or_unknown_origin",
                        "evidence_source": "rpc",
                        "asset": "SOL",
                        "expected_amount": "15.261428266",
                        "matched_amount": "15.261428266",
                        "wallet_delta_quantity": "15.261428266",
                        "sender_owner": "ExternalSender111111111111111111111111111",
                        "receiver_owner": "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
                        "sender_is_known_own_wallet": False,
                        "receiver_is_known_own_wallet": True,
                        "block_time": "2024-11-22T19:34:42+00:00",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        WalletFifoPreviewService, "DEFAULT_SOLANA_PROVENANCE_BATCH_DIR", artifact_dir
    )

    report = WalletFifoPreviewService(store).solana_raw_provenance_priorities(
        2024, limit=5
    )
    response = TestClient(create_app(store)).get(
        "/api/v1/tax-years/2024/wallet-fifo-solana-raw-provenance-priorities?limit=5"
    )

    assert report.raw_transaction_evidence_only_count == 1
    assert report.priorities[0].classification_status == "external_or_unknown_origin"
    assert (
        report.priorities[0].sender_owner == "ExternalSender111111111111111111111111111"
    )
    assert report.priorities[0].origin_hint == "solana_jupiter_or_swap_route"
    assert report.priorities[0].wallet_is_signer is False
    assert report.priorities[0].signers == ["ExternalSigner111111111111111111111111111"]
    assert (
        report.priorities[0].primary_program
        == "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
    )
    assert report.priorities[0].route_classification == "program_service_route"
    assert report.priorities[0].bmf_evidence_priority == "medium"
    assert (
        "Nicht automatisch als eigenen Wallet-Trade werten"
        in report.priorities[0].evidence_checklist
    )
    assert "Main-Wallet ist nicht Signer" in str(report.priorities[0].evidence_needed)
    assert response.status_code == 200
    assert (
        response.json()["data"]["priorities"][0]["classification_status"]
        == "external_or_unknown_origin"
    )
    assert response.json()["data"]["priorities"][0]["wallet_is_signer"] is False
    assert (
        response.json()["data"]["priorities"][0]["route_classification"]
        == "program_service_route"
    )

    summary = WalletFifoPreviewService(store).solana_raw_provenance_sender_summary(
        2024, limit=5
    )
    summary_response = TestClient(create_app(store)).get(
        "/api/v1/tax-years/2024/wallet-fifo-solana-raw-provenance-senders?limit=5"
    )

    assert summary.senders_count == 1
    assert (
        summary.senders[0].sender_owner == "ExternalSender111111111111111111111111111"
    )
    assert summary.senders[0].origin_hint == "solana_jupiter_or_swap_route"
    assert summary.senders[0].raw_transaction_evidence_only_count == 1
    assert summary.senders[0].quantity_total == Decimal("15.261428266")
    assert summary.senders[0].wallet_signed_events_count == 0
    assert summary.senders[0].sample_signers == [
        "ExternalSigner111111111111111111111111111"
    ]
    assert (
        summary.senders[0].primary_program
        == "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
    )
    assert summary.senders[0].route_classification == "program_service_route"
    assert summary.senders[0].bmf_evidence_priority == "medium"
    assert "Programmroute dokumentieren" in summary.senders[0].evidence_checklist
    assert summary_response.status_code == 200
    assert (
        summary_response.json()["data"]["senders"][0]["sender_owner"]
        == "ExternalSender111111111111111111111111111"
    )
    assert (
        summary_response.json()["data"]["senders"][0]["wallet_signed_events_count"] == 0
    )
    assert (
        summary_response.json()["data"]["senders"][0]["bmf_evidence_priority"]
        == "medium"
    )

    bmf_summary = WalletFifoPreviewService(store).solana_raw_bmf_evidence_summary(
        2024, limit=5
    )
    bmf_response = TestClient(create_app(store)).get(
        "/api/v1/tax-years/2024/wallet-fifo-solana-raw-bmf-evidence-summary?limit=5"
    )

    assert bmf_summary.groups_count == 1
    assert bmf_summary.groups[0].route_classification == "program_service_route"
    assert bmf_summary.groups[0].bmf_evidence_priority == "medium"
    assert bmf_summary.groups[0].events_count == 1
    assert bmf_summary.groups[0].senders_count == 1
    assert bmf_summary.groups[0].wallet_signed_events_count == 0
    assert bmf_summary.groups[0].primary_programs == [
        "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
    ]
    assert (
        "Nicht automatisch als eigenen Wallet-Trade werten"
        in bmf_summary.groups[0].evidence_checklist
    )
    assert bmf_response.status_code == 200
    assert (
        bmf_response.json()["data"]["groups"][0]["route_classification"]
        == "program_service_route"
    )

    drilldown = WalletFifoPreviewService(store).solana_raw_bmf_evidence_drilldown(
        2024,
        route_classification="program_service_route",
        bmf_evidence_priority="medium",
        limit=5,
    )
    drilldown_response = TestClient(create_app(store)).get(
        "/api/v1/tax-years/2024/wallet-fifo-solana-raw-bmf-evidence-drilldown"
        "?route_classification=program_service_route&bmf_evidence_priority=medium&limit=5"
    )

    assert drilldown.events_count == 1
    assert drilldown.groups_count == 1
    assert (
        drilldown.events[0].primary_signer
        == "ExternalSigner111111111111111111111111111"
    )
    assert drilldown.events[0].decision_suggestion == "service_program_route_not_income"
    assert (
        drilldown.signer_groups[0].primary_program
        == "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
    )
    assert (
        drilldown.signer_groups[0].decision_suggestion
        == "service_program_route_not_income"
    )
    assert drilldown_response.status_code == 200
    assert (
        drilldown_response.json()["data"]["events"][0]["decision_suggestion"]
        == "service_program_route_not_income"
    )


def test_wallet_fifo_provenance_recognizes_bitget_withdrawal_history_fields(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    spot_batch = store.create_import_batch(
        ImportBatchCreate(
            source="bitget",
            filename="Spot Financial Record.csv",
            file_hash="bitget-withdraw-spot",
        )
    )
    raw_spot = store.add_raw_object(
        spot_batch.batch_id,
        RawObjectCreate(
            row_number=70,
            payload_json=(
                '{"Action":"WITHDRAW","Type":"Withdrawal","Coin":"USDT",'
                '"Quantity":"-100","Fee (Coin quantity)":"-1",'
                '"Order no.":"1247109485523623953",'
                '"Creation timestamp (+8 UTC)":"2024-12-01 21:33:12"}'
            ),
        ),
    )
    withdrawal_batch = store.create_import_batch(
        ImportBatchCreate(
            source="bitget",
            filename="Deposit-Withdrawal History.csv",
            file_hash="bitget-withdraw-history",
        )
    )
    store.add_raw_object(
        withdrawal_batch.batch_id,
        RawObjectCreate(
            row_number=3,
            payload_json=(
                '{"Order no.":"1247109485523623953","Transaction hash(txid)":"bitget-chain-tx",'
                '"Coin":"USDT","Network":"SOL","Quantity":"100","Withdrawal fee":"1",'
                '"Type":"Withdrawal","To address":"6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",'
                '"Timestamp UTC+8 (Completion)":"2024-12-01 21:33:12"}'
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="bitget",
                event_time=datetime(2024, 12, 1, 13, 33, 12, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("-100"),
                account="bitget",
                tx_id="1247109485523623953",
                raw_object_id=raw_spot.raw_object_id,
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 12, 1, 13, 34, 12, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("100"),
                account="6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
                tx_id="bitget-chain-tx",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    report = WalletFifoPreviewService(store).provenance_priorities(2024)
    group = report.groups[0]

    assert group.evidence_status == "withdrawal_evidence_ready"
    assert group.withdrawal_evidence_ready_count == 1
    assert group.best_outflow_candidate is not None
    assert group.best_outflow_candidate.withdrawal_tx_id == "bitget-chain-tx"
    assert (
        group.best_outflow_candidate.withdrawal_address
        == "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"
    )
    assert group.best_outflow_candidate.withdrawal_amount == Decimal("100")
    assert group.best_outflow_candidate.withdrawal_fee == Decimal("1")


def test_wallet_fifo_provenance_events_filter_by_asset_and_pool(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("200"),
                account="pionex",
                tx_id="usdt-in",
            ),
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2025, 1, 2, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("0.001"),
                quote_asset="USDT",
                quote_quantity=Decimal("100"),
                account="pionex",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 3, tzinfo=timezone.utc),
                event_type="transfer",
                asset="JUP",
                quantity=Decimal("10"),
                account="Spot",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    report = WalletFifoPreviewService(store).provenance_events(
        2025,
        asset="USDT",
        pool_id="pionex:pionex",
    )

    assert report.events_count == 1
    assert len(report.events) == 1
    assert report.events[0].asset == "USDT"
    assert report.events[0].pool_id == "pionex:pionex"
    assert report.events[0].evidence_status == "missing_source_evidence"


def test_wallet_fifo_provenance_events_support_offset(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("100"),
                account="pionex",
                tx_id="first",
            ),
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2025, 1, 2, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("200"),
                account="pionex",
                tx_id="second",
            ),
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2025, 1, 3, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("0.001"),
                quote_asset="USDT",
                quote_quantity=Decimal("50"),
                account="pionex",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    report = WalletFifoPreviewService(store).provenance_events(
        2025,
        asset="USDT",
        pool_id="pionex:pionex",
        offset=1,
        limit=1,
    )

    assert report.offset == 1
    assert report.limit == 1
    assert report.events_count == 2
    assert len(report.events) == 1
    assert report.events[0].tx_id == "second"


def test_wallet_fifo_provenance_events_api(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("200"),
                account="pionex",
            ),
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2025, 1, 2, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("0.001"),
                quote_asset="USDT",
                quote_quantity=Decimal("100"),
                account="pionex",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    response = TestClient(create_app(store)).get(
        "/api/v1/tax-years/2025/wallet-fifo-provenance-events?asset=USDT&pool_id=pionex%3Apionex"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["events_count"] == 1
    assert data["events"][0]["asset"] == "USDT"


def test_wallet_fifo_origin_trace_api(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 20, 0, 39, 56, tzinfo=timezone.utc),
                event_type="trade",
                asset="USDT",
                quantity=Decimal("1"),
                quote_asset="JUP",
                quote_quantity=Decimal("2"),
                account="Spot",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()
    response = TestClient(create_app(store)).get(
        "/api/v1/tax-years/2025/wallet-fifo-origin-trace?asset=JUP"
    )

    assert response.status_code == 200
    assert response.json()["data"]["traces_count"] == 1


def test_wallet_fifo_solana_origin_trace_marks_known_sender(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    service = WalletFifoPreviewService(store)
    payload = {
        "jsonrpc": "2.0",
        "result": {
            "slot": 123,
            "blockTime": 1737333557,
            "meta": {
                "err": None,
                "preTokenBalances": [
                    {
                        "owner": "GmHYjZGkcHBZ3WyGZ9eUGDZMfHvJTLtTKXu6dnSc63yu",
                        "mint": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
                        "uiTokenAmount": {
                            "uiAmountString": "9000",
                            "decimals": 6,
                            "amount": "9000000000",
                        },
                    },
                    {
                        "owner": "Ftf2dgeRpBrPFmbd4wQWWqSjCmRjGes1GzNXtxKETeLW",
                        "mint": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
                        "uiTokenAmount": {
                            "uiAmountString": "0",
                            "decimals": 6,
                            "amount": "0",
                        },
                    },
                ],
                "postTokenBalances": [
                    {
                        "owner": "GmHYjZGkcHBZ3WyGZ9eUGDZMfHvJTLtTKXu6dnSc63yu",
                        "mint": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
                        "uiTokenAmount": {
                            "uiAmountString": "572.706347",
                            "decimals": 6,
                            "amount": "572706347",
                        },
                    },
                    {
                        "owner": "Ftf2dgeRpBrPFmbd4wQWWqSjCmRjGes1GzNXtxKETeLW",
                        "mint": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
                        "uiTokenAmount": {
                            "uiAmountString": "8427.293653",
                            "decimals": 6,
                            "amount": "8427293653",
                        },
                    },
                ],
            },
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        trace = service._fetch_solana_origin_trace(
            client=client,
            rpc_url="https://rpc.test",
            signature="sig",
            asset="JUP",
            expected_amount=Decimal("8427.293653"),
            deposit_address="Ftf2dgeRpBrPFmbd4wQWWqSjCmRjGes1GzNXtxKETeLW",
        )

    assert trace.status == "own_wallet_transfer_candidate"
    assert trace.sender_owner == "GmHYjZGkcHBZ3WyGZ9eUGDZMfHvJTLtTKXu6dnSc63yu"
    assert trace.receiver_owner == "Ftf2dgeRpBrPFmbd4wQWWqSjCmRjGes1GzNXtxKETeLW"
    assert trace.sender_is_known_own_wallet is True
    assert trace.receiver_is_deposit_address is True
    assert trace.matched_amount == Decimal("8427.293653")


def test_wallet_fifo_solana_origin_trace_marks_unknown_sender(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    service = WalletFifoPreviewService(store)
    payload = {
        "jsonrpc": "2.0",
        "result": {
            "slot": 123,
            "blockTime": 1737333557,
            "meta": {
                "err": None,
                "preTokenBalances": [
                    {
                        "owner": "unknown-wallet",
                        "mint": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
                        "uiTokenAmount": {"uiAmountString": "9000"},
                    }
                ],
                "postTokenBalances": [
                    {
                        "owner": "unknown-wallet",
                        "mint": "JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN",
                        "uiTokenAmount": {"uiAmountString": "572.706347"},
                    }
                ],
            },
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        trace = service._fetch_solana_origin_trace(
            client=client,
            rpc_url="https://rpc.test",
            signature="sig",
            asset="JUP",
            expected_amount=Decimal("8427.293653"),
            deposit_address="deposit-wallet",
        )

    assert trace.status == "external_or_unknown_origin"
    assert trace.sender_owner == "unknown-wallet"
    assert trace.sender_is_known_own_wallet is False


def test_wallet_fifo_preview_carries_external_solana_deposit_to_binance_pool(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("STEUERREPORT_WALLET_FIFO_ENABLE_LIVE_RPC", "1")
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    deposit_batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Deposit-History.xlsx",
            file_hash="deposit-history",
        )
    )
    store.add_raw_object(
        deposit_batch.batch_id,
        RawObjectCreate(
            row_number=4,
            payload_json=(
                '{"Address":"binance-deposit-address","Amount":"4","Coin":"JUP",'
                '"Network":"SOL","Status":"Completed","TXID":"solana-transfer-tx",'
                '"Time":"25-01-20 00:39:17"}'
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="JUP",
                quantity=Decimal("4"),
                quote_asset="EUR",
                quote_quantity=Decimal("40"),
                account="6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 20, 0, 39, 17, tzinfo=timezone.utc),
                event_type="transfer",
                asset="JUP",
                quantity=Decimal("4"),
                account="binance",
                tx_id="solana-transfer-tx",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 20, 0, 39, 31, tzinfo=timezone.utc),
                event_type="transfer",
                asset="JUP",
                quantity=Decimal("4"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 20, 0, 39, 56, tzinfo=timezone.utc),
                event_type="trade",
                asset="USDT",
                quantity=Decimal("80"),
                quote_asset="JUP",
                quote_quantity=Decimal("4"),
                account="Spot",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    def fake_fetch(
        self, *, client, rpc_url, signature, asset, expected_amount, deposit_address
    ):
        return WalletFifoSolanaOriginTrace(
            signature=signature,
            status="own_wallet_transfer_candidate",
            asset=asset,
            expected_amount=expected_amount,
            deposit_address=deposit_address,
            sender_owner="6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
            receiver_owner="binance-deposit-address",
            sender_is_known_own_wallet=True,
            receiver_is_deposit_address=True,
            matched_amount=expected_amount,
            known_wallets=["6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"],
            recommended_action="test",
        )

    monkeypatch.setattr(
        WalletFifoPreviewService, "_fetch_solana_origin_trace", fake_fetch
    )

    report = WalletFifoPreviewService(store).preview(year=2025)

    assert report.unmatched_count == 0
    assert report.transfer_traces_count == 1
    assert (
        report.transfer_traces[0].source_pool_id
        == "solana_rpc:6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"
    )
    assert report.transfer_traces[0].target_pool_id == "binance:Spot"
    assert (
        report.transfer_traces[0].target_event_id
        != report.transfer_traces[0].source_event_id
    )
    assert report.tax_lines_count == 1
    assert report.sample_lines[0].pool_id == "binance:Spot"
    assert report.sample_lines[0].acquisition_cost_eur == Decimal(
        "40.000000000000000000000000000000000000"
    )

    evidence = WalletFifoPreviewService(store).cex_deposit_transfer_evidence(
        2025, cex="binance", network="SOL"
    )
    response = TestClient(create_app(store)).get(
        "/api/v1/tax-years/2025/cex-deposit-transfer-evidence?cex=binance&network=SOL"
    )

    assert evidence.deposits_count == 1
    assert evidence.transfer_neutral_count == 1
    assert evidence.deposits[0].tx_id == "solana-transfer-tx"
    assert evidence.deposits[0].deposit_address == "binance-deposit-address"
    assert evidence.deposits[0].cex_account == "binance"
    assert (
        evidence.deposits[0].fifo_source_pool_id
        == "solana_rpc:6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"
    )
    assert evidence.deposits[0].fifo_target_pool_id == "binance:Spot"
    assert evidence.deposits[0].tax_label == "Transfer / Uebertrag"
    assert evidence.deposits[0].holding_period_continues is True
    assert evidence.deposits[0].evidence_status == "transfer_neutral_fifo_carried"
    assert response.status_code == 200
    assert response.json()["data"]["deposits"][0]["holding_period_continues"] is True


def test_cex_sender_ownership_latest_reads_latest_artifact(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    evidence_dir = tmp_path / "var/cex_deposit_sender_ownership"
    evidence_dir.mkdir(parents=True)
    artifact = (
        evidence_dir / "20260621T064725Z_2025_binance_solana_sender_ownership.json"
    )
    artifact.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-21T06:47:25+00:00",
                "year": 2025,
                "cex": "binance",
                "network": "SOL",
                "summary": {
                    "transactions": 2,
                    "status_counts": {
                        "TAX_NEUTRAL_TRANSFER_PENDING_REVIEW": 1,
                        "UNVERIFIED_THIRD_PARTY": 1,
                    },
                    "tax_neutral_candidates": 1,
                    "complex_route_review": 0,
                    "unverified_third_party": 1,
                    "pending_review": 0,
                },
                "results": [
                    {
                        "txid": "own-tx",
                        "timestamp_utc": "2025-01-19T22:37:40+00:00",
                        "asset": "JUP",
                        "amount": "8427.293653",
                        "provider_status": "alchemy",
                        "onchain_sender": "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
                        "primary_signer": "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
                        "deposit_address": "binance-deposit-address",
                        "cex_account": "binance",
                        "fifo_transfer_status": "inferred_cross_pool",
                        "carried_cost_basis_eur": "7930.4626281621104158",
                        "program_ids": ["11111111111111111111111111111111"],
                        "decision_layer": {
                            "binance_deposit_address_owned": True,
                            "sender_is_own_wallet": True,
                            "service_program_route_not_income": False,
                            "exchange_deposit_transfer_neutral": True,
                        },
                        "final_tax_status": "TAX_NEUTRAL_TRANSFER_PENDING_REVIEW",
                        "review_note": "Own sender/deposit match found.",
                    },
                    {
                        "txid": "third-party-tx",
                        "timestamp_utc": "2025-03-23T15:55:52+00:00",
                        "asset": "SOL",
                        "amount": "7.0700475",
                        "provider_status": "alchemy",
                        "onchain_sender": "CySAjqmKLQCT729gypchz3zbYSSNh85rXx8Tk9e7PC7P",
                        "primary_signer": "CySAjqmKLQCT729gypchz3zbYSSNh85rXx8Tk9e7PC7P",
                        "deposit_address": "binance-deposit-address",
                        "cex_account": "binance",
                        "fifo_transfer_status": "missing",
                        "carried_cost_basis_eur": "0",
                        "program_ids": ["11111111111111111111111111111111"],
                        "decision_layer": {
                            "binance_deposit_address_owned": True,
                            "sender_is_own_wallet": False,
                            "service_program_route_not_income": False,
                            "exchange_deposit_transfer_neutral": False,
                        },
                        "final_tax_status": "UNVERIFIED_THIRD_PARTY",
                        "review_note": "Sender is not in owned wallet registry.",
                    },
                ],
                "methodology": "test artifact",
            }
        ),
        encoding="utf-8",
    )

    report = WalletFifoPreviewService(store).cex_sender_ownership_latest(
        2025, cex="binance", network="SOL"
    )
    response = TestClient(create_app(store)).get(
        "/api/v1/tax-years/2025/cex-sender-ownership-latest?cex=binance&network=SOL"
    )

    assert report.artifact_exists is True
    assert report.artifact_path == str(artifact)
    assert report.transactions_count == 2
    assert report.tax_neutral_candidates == 1
    assert report.unverified_third_party == 1
    assert report.decisions[0].decision_layer["sender_is_own_wallet"] is True
    assert (
        report.decisions[1].onchain_sender
        == "CySAjqmKLQCT729gypchz3zbYSSNh85rXx8Tk9e7PC7P"
    )
    assert report.decisions[1].onchain_sender_label == "Bitget Exchange"
    assert report.decisions[1].sender_classification == "exchange_infrastructure"
    assert response.status_code == 200
    assert response.json()["data"]["status_counts"]["UNVERIFIED_THIRD_PARTY"] == 1

    client = TestClient(create_app(store))
    accepted = client.post(
        "/api/v1/tax-years/2025/cex-sender-ownership-decisions?cex=binance&network=SOL",
        json={
            "txid": "own-tx",
            "decision_status": "tax_neutral_transfer_reviewed",
        },
    )
    rejected = client.post(
        "/api/v1/tax-years/2025/cex-sender-ownership-decisions?cex=binance&network=SOL",
        json={
            "txid": "third-party-tx",
            "decision_status": "tax_neutral_transfer_reviewed",
        },
    )
    exchange_evidence_required = client.post(
        "/api/v1/tax-years/2025/cex-sender-ownership-decisions?cex=binance&network=SOL",
        json={
            "txid": "third-party-tx",
            "decision_status": "exchange_outflow_evidence_required",
        },
    )
    duplicate_exchange_evidence_required = client.post(
        "/api/v1/tax-years/2025/cex-sender-ownership-decisions?cex=binance&network=SOL",
        json={
            "txid": "third-party-tx",
            "decision_status": "exchange_outflow_evidence_required",
        },
    )

    assert accepted.status_code == 200
    assert accepted.json()["data"]["decision_status"] == "tax_neutral_transfer_reviewed"
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "error"
    assert (
        rejected.json()["errors"][0]["code"]
        == "cex_sender_ownership_not_tax_neutral_candidate"
    )
    assert exchange_evidence_required.status_code == 200
    assert (
        exchange_evidence_required.json()["data"]["decision_status"]
        == "exchange_outflow_evidence_required"
    )
    assert duplicate_exchange_evidence_required.status_code == 200
    assert duplicate_exchange_evidence_required.json()["status"] == "warning"
    assert (
        duplicate_exchange_evidence_required.json()["warnings"][0]["code"]
        == "cex_sender_ownership_decision_already_exists"
    )
    decisions = store.list_review_decisions()
    assert [decision.decision_type for decision in decisions].count(
        "cex_sender_ownership"
    ) == 2
    bitget_decision = next(
        decision
        for decision in decisions
        if decision.payload.get("decision_status")
        == "exchange_outflow_evidence_required"
    )
    assert bitget_decision.payload["onchain_sender_label"] == "Bitget Exchange"

    outflow_missing = WalletFifoPreviewService(store).cex_exchange_outflow_evidence(
        2025,
        source_exchange="bitget",
        target_cex="binance",
        network="SOL",
    )
    assert outflow_missing.rows_count == 1
    assert outflow_missing.rows[0].status == "missing_exchange_outflow_event"
    not_ready_decision = client.post(
        "/api/v1/tax-years/2025/cex-exchange-outflow-decisions?source_exchange=bitget&target_cex=binance&network=SOL",
        json={
            "deposit_txid": "third-party-tx",
            "decision_status": "transfer_neutral_fifo_carry_forward_reviewed",
        },
    )
    assert not_ready_decision.status_code == 200
    assert not_ready_decision.json()["status"] == "error"
    assert (
        not_ready_decision.json()["errors"][0]["code"]
        == "cex_exchange_outflow_not_ready"
    )

    withdrawal_batch = store.create_import_batch(
        ImportBatchCreate(
            source="bitget",
            filename="bitget-withdrawal-api-20250323-SOL.csv",
            file_hash="unit:bitget-withdrawal-api",
        )
    )
    withdrawal_raw = store.add_raw_objects(
        withdrawal_batch.batch_id,
        [
            RawObjectCreate(
                row_number=1,
                payload_json=json.dumps(
                    {
                        "record_type": "bitget_withdrawal_evidence",
                        "asset": "SOL",
                        "coin": "SOL",
                        "amount": "7.0760475",
                        "size": "7.0760475",
                        "fee": "-0.006",
                        "tradeId": "third-party-tx",
                        "tx_id": "third-party-tx",
                        "toAddress": "binance-deposit-address",
                        "chain": "SOL",
                        "network": "SOL",
                        "account": "bitget",
                        "uTime": "1742745360000",
                        "status": "success",
                    }
                ),
            )
        ],
    )[0]
    outflow_ready = WalletFifoPreviewService(store).cex_exchange_outflow_evidence(
        2025,
        source_exchange="bitget",
        target_cex="binance",
        network="SOL",
    )
    response_outflow = client.get(
        "/api/v1/tax-years/2025/cex-exchange-outflow-evidence?source_exchange=bitget&target_cex=binance&network=SOL"
    )
    assert outflow_ready.rows_count == 1
    assert outflow_ready.ready_count == 1
    assert outflow_ready.rows[0].status == "exchange_outflow_txid_match_ready"
    assert outflow_ready.rows[0].best_candidate is not None
    assert (
        outflow_ready.rows[0].best_candidate.event_id
        == f"raw:{withdrawal_raw.raw_object_id}"
    )
    assert outflow_ready.rows[0].best_candidate.quantity == Decimal("7.0700475")
    assert outflow_ready.rows[0].best_candidate.withdrawal_tx_id == "third-party-tx"
    assert response_outflow.status_code == 200
    assert response_outflow.json()["data"]["ready_count"] == 1
    accepted_outflow_decision = client.post(
        "/api/v1/tax-years/2025/cex-exchange-outflow-decisions?source_exchange=bitget&target_cex=binance&network=SOL",
        json={
            "deposit_txid": "third-party-tx",
            "decision_status": "transfer_neutral_fifo_carry_forward_reviewed",
        },
    )
    duplicate_outflow_decision = client.post(
        "/api/v1/tax-years/2025/cex-exchange-outflow-decisions?source_exchange=bitget&target_cex=binance&network=SOL",
        json={
            "deposit_txid": "third-party-tx",
            "decision_status": "transfer_neutral_fifo_carry_forward_reviewed",
        },
    )
    assert accepted_outflow_decision.status_code == 200
    assert (
        accepted_outflow_decision.json()["data"]["decision_status"]
        == "transfer_neutral_fifo_carry_forward_reviewed"
    )
    assert duplicate_outflow_decision.status_code == 200
    assert duplicate_outflow_decision.json()["status"] == "warning"
    assert (
        duplicate_outflow_decision.json()["warnings"][0]["code"]
        == "cex_exchange_outflow_decision_already_exists"
    )
    outflow_decision = next(
        decision
        for decision in store.list_review_decisions()
        if decision.decision_type == "cex_exchange_outflow"
    )
    assert (
        outflow_decision.payload["exchange_outflow_raw_object_id"]
        == withdrawal_raw.raw_object_id
    )
    assert outflow_decision.payload["exchange_outflow_amount"] == "7.0700475"
    assert outflow_decision.payload["exchange_outflow_gross_amount"] == "7.0760475"
    assert outflow_decision.payload["exchange_outflow_fee"] == "-0.006"
    assert (
        outflow_decision.payload["fifo_effect"]
        == "carry_forward_documented_pending_fifo_anchor"
    )
    assert outflow_decision.payload["tax_line_effect"] == "none"
    anchor_feasibility = WalletFifoPreviewService(
        store
    ).cex_exchange_outflow_anchor_feasibility(
        2025,
        source_exchange="bitget",
        target_cex="binance",
        network="SOL",
    )
    response_anchor_feasibility = client.get(
        "/api/v1/tax-years/2025/cex-exchange-outflow-anchor-feasibility?source_exchange=bitget&target_cex=binance&network=SOL"
    )
    assert anchor_feasibility.decisions_count == 1
    assert anchor_feasibility.evidence_ready_count == 1
    assert anchor_feasibility.anchor_ready_count == 0
    assert anchor_feasibility.anchor_missing_count == 1
    assert (
        anchor_feasibility.items[0].anchor_status
        == "evidence_ready_decision_present_fifo_anchor_missing"
    )
    assert anchor_feasibility.items[0].missing_requirements == [
        "wallet_fifo_transfer_trace_missing"
    ]
    assert anchor_feasibility.items[0].exchange_outflow_fee == Decimal("-0.006")
    assert response_anchor_feasibility.status_code == 200
    assert (
        response_anchor_feasibility.json()["data"]["items"][0]["anchor_ready"] is False
    )


def test_wallet_fifo_withdrawal_gap_trace_flags_missing_withdrawal_history(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Transaction-History.xlsx",
            file_hash="transaction-history-withdrawal",
        )
    )
    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=12,
            payload_json=(
                '{"Account":"Spot","Change":"-5532.275703","Coin":"JUP",'
                '"Operation":"Withdraw","Remark":"Withdraw fee is included",'
                '"Time":"25-03-23 15:49:42"}'
            ),
        ),
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="binance",
            event_time=datetime(2025, 3, 23, 15, 49, 42, tzinfo=timezone.utc),
            event_type="transfer",
            asset="JUP",
            quantity=Decimal("-5532.275703"),
            account="Spot",
            raw_object_id=raw.raw_object_id,
        )
    )
    gap = WalletFifoGapDiagnosis(
        gap_id="solana_rpc:wallet:JUP:gap",
        event_time=datetime(2025, 6, 12, 10, 51, 5, tzinfo=timezone.utc),
        pool_id="solana_rpc:wallet",
        asset="JUP",
        missing_quantity=Decimal("3772.154256"),
        disposal_event_id="gap-event",
        disposal_event_type="transfer",
        reason="transfer_source_pool_missing_lot_available_6295.733027",
        likely_cause="possible_cross_pool_transfer_missing_link",
        recommended_action="test",
    )

    candidates = WalletFifoPreviewService(store)._withdrawal_candidates_for_gap(
        gap,
        store.list_canonical_events(),
    )

    assert len(candidates) == 1
    assert candidates[0].quantity == Decimal("5532.275703000000000000")
    assert candidates[0].evidence_status == "withdrawal_history_missing"
    assert candidates[0].transaction_history_evidence is not None
    assert candidates[0].withdrawal_history_evidence is None


def test_wallet_fifo_withdrawal_gap_trace_matches_binance_api_amount_plus_fee(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    transaction_batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Transaction-History.xlsx",
            file_hash="transaction-history-withdrawal",
        )
    )
    transaction_raw = store.add_raw_object(
        transaction_batch.batch_id,
        RawObjectCreate(
            row_number=12,
            payload_json=(
                '{"Account":"Spot","Change":"-5532.275703","Coin":"JUP",'
                '"Operation":"Withdraw","Remark":"Withdraw fee is included",'
                '"Time":"25-03-23 15:49:42"}'
            ),
        ),
    )
    withdrawal_batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance_withdrawal_api",
            filename="binance-withdrawal-api-20250323-20250324-JUP.json",
            file_hash="withdrawal-api",
        )
    )
    store.add_raw_object(
        withdrawal_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=(
                '{"asset":"JUP","amount":"5530.555703","transaction_fee":"1.72",'
                '"gross_amount":"5532.275703","address":"6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",'
                '"network":"SOL","tx_id":"withdraw-tx","complete_time":"2025-03-23 13:49:42"}'
            ),
        ),
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="binance",
            event_time=datetime(2025, 3, 23, 15, 49, 42, tzinfo=timezone.utc),
            event_type="transfer",
            asset="JUP",
            quantity=Decimal("-5532.275703"),
            account="Spot",
            raw_object_id=transaction_raw.raw_object_id,
        )
    )
    gap = WalletFifoGapDiagnosis(
        gap_id="solana_rpc:wallet:JUP:gap",
        event_time=datetime(2025, 6, 12, 10, 51, 5, tzinfo=timezone.utc),
        pool_id="solana_rpc:wallet",
        asset="JUP",
        missing_quantity=Decimal("3772.154256"),
        disposal_event_id="gap-event",
        disposal_event_type="transfer",
        reason="transfer_source_pool_missing_lot_available_6295.733027",
        likely_cause="possible_cross_pool_transfer_missing_link",
        recommended_action="test",
    )

    candidates = WalletFifoPreviewService(store)._withdrawal_candidates_for_gap(
        gap,
        store.list_canonical_events(),
    )

    assert len(candidates) == 1
    assert candidates[0].evidence_status == "ready_for_transfer_anchor"
    assert candidates[0].withdrawal_history_evidence is not None
    assert candidates[0].onchain_tx_id == "withdraw-tx"
    assert candidates[0].to_address == "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"


def test_wallet_fifo_solana_provenance_classifies_native_sol_own_transfer(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    service = WalletFifoPreviewService(store)
    source_wallet = "GmHYjZGkcHBZ3WyGZ9eUGDZMfHvJTLtTKXu6dnSc63yu"
    target_wallet = "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"
    event = WalletFifoProvenanceEvent(
        event_id="event-1",
        event_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
        source="solana_rpc",
        account=target_wallet,
        asset="SOL",
        pool_id=f"solana_rpc:{target_wallet}",
        quantity=Decimal("0.005"),
        tx_id="sig",
        onchain_tx_id="sig",
        evidence_status="raw_transaction_evidence_only",
        recommended_action="test",
    )
    payload = {
        "blockTime": 1700000000,
        "slot": 123,
        "transaction": {
            "message": {
                "accountKeys": [
                    {"pubkey": source_wallet},
                    {"pubkey": target_wallet},
                    {"pubkey": "fee-account"},
                ]
            }
        },
        "meta": {
            "err": None,
            "preBalances": [1000000000, 100000000, 10],
            "postBalances": [994990000, 105000000, 10],
        },
    }

    result = service._classify_native_sol_transaction(
        event=event, signature="sig", result=payload
    )

    assert result.status == "own_wallet_transfer_candidate"
    assert result.sender_owner == source_wallet
    assert result.receiver_owner == target_wallet
    assert result.sender_is_known_own_wallet is True
    assert result.receiver_is_known_own_wallet is True
    assert result.matched_amount == Decimal("0.005")
    assert result.wallet_delta_quantity == Decimal("0.005")


def test_wallet_fifo_solana_provenance_classifies_solscan_actions(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    service = WalletFifoPreviewService(store)
    source_wallet = "GmHYjZGkcHBZ3WyGZ9eUGDZMfHvJTLtTKXu6dnSc63yu"
    target_wallet = "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"
    event = WalletFifoProvenanceEvent(
        event_id="event-1",
        event_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
        source="solana_rpc",
        account=target_wallet,
        asset="SOL",
        pool_id=f"solana_rpc:{target_wallet}",
        quantity=Decimal("0.005"),
        tx_id="sig",
        onchain_tx_id="sig",
        evidence_status="raw_transaction_evidence_only",
        recommended_action="test",
    )
    data = {
        "tx_hash": "sig",
        "block_id": 123,
        "block_time": 1700000000,
        "transfers": [
            {
                "from": source_wallet,
                "to": target_wallet,
                "token_symbol": "SOL",
                "amount": "5000000",
                "token_decimals": 9,
            }
        ],
    }

    result = service._classify_solscan_actions(event=event, signature="sig", data=data)

    assert result.status == "own_wallet_transfer_candidate"
    assert result.evidence_source == "solscan"
    assert result.sender_owner == source_wallet
    assert result.receiver_owner == target_wallet
    assert result.matched_amount == Decimal("0.005")


def test_wallet_fifo_solana_provenance_classification_api_with_mocked_rpc(
    tmp_path, monkeypatch
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("0.005"),
                account=wallet,
                tx_id="sig",
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 2, 2, tzinfo=timezone.utc),
                event_type="fee",
                asset="SOL",
                quantity=Decimal("-0.001"),
                account=wallet,
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    def fake_fetch(self, *, client, rpc_url, event):
        return self._solana_provenance_classification_error(
            event=event,
            signature=event.onchain_tx_id or event.tx_id or "",
            status="external_or_unknown_origin",
            reason="mocked",
        )

    monkeypatch.setattr(
        WalletFifoPreviewService, "_fetch_solana_provenance_classification", fake_fetch
    )

    response = TestClient(create_app(store)).get(
        f"/api/v1/tax-years/2024/wallet-fifo-solana-provenance-classification?asset=SOL&pool_id=solana_rpc%3A{wallet}&limit=1&provider=rpc"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["requested_events_count"] == 1
    assert data["classified_count"] == 1
    assert data["external_or_unknown_count"] == 1


def test_wallet_fifo_solana_provenance_batch_latest_reads_artifact(
    tmp_path, monkeypatch
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    artifact_dir = tmp_path / "batches"
    artifact_dir.mkdir()
    artifact = artifact_dir / "latest_2024_SOL_provenance_classification.json"
    artifact.write_text(
        json.dumps(
            {
                "run_id": "run-test",
                "generated_at": "2026-06-20T19:40:00+00:00",
                "year": 2024,
                "asset": "SOL",
                "pool_id": "solana_rpc:test",
                "provider": "rpc_public",
                "total_events": 10,
                "classified_count": 4,
                "own_transfer_candidates_count": 1,
                "external_or_unknown_count": 3,
                "failed_count": 0,
                "batches": [
                    {"offset": 0, "failed_count": 0, "status": "skipped_resume_cache"}
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        WalletFifoPreviewService, "DEFAULT_SOLANA_PROVENANCE_BATCH_DIR", artifact_dir
    )

    report = WalletFifoPreviewService(store).solana_provenance_batch_latest(2024)
    assert report.exists is True
    assert report.classified_count == 4
    assert report.remaining_count == 6
    assert report.progress_percent == Decimal("40.00")
    assert report.own_transfer_candidates_count == 1

    response = TestClient(create_app(store)).get(
        "/api/v1/tax-years/2024/wallet-fifo-solana-provenance-batch-latest?asset=SOL"
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["exists"] is True
    assert data["run_id"] == "run-test"
    assert data["progress_percent"] == "40.00"


def test_wallet_fifo_solana_sender_clusters_group_batch_artifact(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    artifact_dir = tmp_path / "batches"
    artifact_dir.mkdir()
    own_sender = "GmHYjZGkcHBZ3WyGZ9eUGDZMfHvJTLtTKXu6dnSc63yu"
    own_receiver = "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"
    external_sender = "ExternalSender111111111111111111111111111111"
    artifact = artifact_dir / "latest_2024_SOL_provenance_classification.json"
    artifact.write_text(
        json.dumps(
            {
                "run_id": "run-test",
                "year": 2024,
                "asset": "SOL",
                "total_events": 3,
                "classifications": [
                    {
                        "event_id": "event-1",
                        "signature": "sig-1",
                        "status": "external_or_unknown_origin",
                        "asset": "SOL",
                        "expected_amount": "0.1",
                        "matched_amount": "0.1",
                        "sender_owner": external_sender,
                        "receiver_owner": own_receiver,
                        "sender_is_known_own_wallet": False,
                        "receiver_is_known_own_wallet": True,
                        "block_time": "2024-01-01T00:00:00+00:00",
                    },
                    {
                        "event_id": "event-2",
                        "signature": "sig-2",
                        "status": "external_or_unknown_origin",
                        "asset": "SOL",
                        "expected_amount": "0.2",
                        "matched_amount": "0.2",
                        "sender_owner": external_sender,
                        "receiver_owner": own_receiver,
                        "sender_is_known_own_wallet": False,
                        "receiver_is_known_own_wallet": True,
                        "block_time": "2024-01-02T00:00:00+00:00",
                    },
                    {
                        "event_id": "event-3",
                        "signature": "sig-3",
                        "status": "own_wallet_transfer_candidate",
                        "asset": "SOL",
                        "expected_amount": "0.3",
                        "matched_amount": "0.3",
                        "sender_owner": own_sender,
                        "receiver_owner": own_receiver,
                        "sender_is_known_own_wallet": True,
                        "receiver_is_known_own_wallet": True,
                        "block_time": "2024-01-03T00:00:00+00:00",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        WalletFifoPreviewService, "DEFAULT_SOLANA_PROVENANCE_BATCH_DIR", artifact_dir
    )
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="solana_rpc",
            filename="unit-solana.json",
            file_hash="unit:sender-cluster",
        )
    )
    store.add_raw_objects(
        batch.batch_id,
        [
            RawObjectCreate(
                row_number=1,
                payload_json=json.dumps(
                    {"sender": external_sender, "signature": "sig-1"}
                ),
            )
        ],
    )

    response = TestClient(create_app(store)).get(
        "/api/v1/tax-years/2024/wallet-fifo-solana-sender-clusters?asset=SOL&limit=10"
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["clusters_count"] == 2
    assert data["own_transfer_candidate_events"] == 1
    assert data["external_or_unknown_events"] == 2
    own_cluster = next(
        item for item in data["clusters"] if item["sender_owner"] == own_sender
    )
    external_cluster = next(
        item for item in data["clusters"] if item["sender_owner"] == external_sender
    )
    assert own_cluster["status"] == "own_wallet_transfer_candidate"
    assert external_cluster["status"] == "external_or_unknown_sender"
    assert external_cluster["events_count"] == 2
    assert external_cluster["matched_amount_total"] == "0.3"
    assert external_cluster["local_raw_sender_hits"] == 1
    assert external_cluster["local_signature_evidence_count"] == 1


def test_wallet_fifo_solana_sender_cluster_outflows_find_nearby_local_outflow(
    tmp_path, monkeypatch
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    artifact_dir = tmp_path / "batches"
    artifact_dir.mkdir()
    sender = "ExternalSender111111111111111111111111111111"
    receiver = "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"
    (artifact_dir / "latest_2024_SOL_provenance_classification.json").write_text(
        json.dumps(
            {
                "run_id": "run-test",
                "year": 2024,
                "asset": "SOL",
                "total_events": 1,
                "classifications": [
                    {
                        "event_id": "event-in",
                        "signature": "sig-in",
                        "status": "external_or_unknown_origin",
                        "asset": "SOL",
                        "expected_amount": "1.000000000",
                        "matched_amount": "1.000000000",
                        "sender_owner": sender,
                        "receiver_owner": receiver,
                        "sender_is_known_own_wallet": False,
                        "receiver_is_known_own_wallet": True,
                        "block_time": "2024-01-01T10:00:00+00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        WalletFifoPreviewService, "DEFAULT_SOLANA_PROVENANCE_BATCH_DIR", artifact_dir
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 1, 1, 10, 15, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("-1.005"),
                account=receiver,
                tx_id="sig-out",
            )
        ]
    )

    response = TestClient(create_app(store)).get(
        f"/api/v1/tax-years/2024/wallet-fifo-solana-sender-cluster-outflows?asset=SOL&sender_owner={sender}&limit=5&window_hours=1&amount_tolerance_percent=1"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["checked_events_count"] == 1
    assert data["events_with_candidates_count"] == 1
    assert data["candidates_count"] == 1
    assert data["samples"][0]["inbound_signature"] == "sig-in"
    assert data["samples"][0]["candidates"][0]["tx_id"] == "sig-out"
    assert (
        data["samples"][0]["candidates"][0]["evidence_category"]
        == "same_wallet_onchain_flow_candidate"
    )


def test_wallet_fifo_solana_sender_cluster_outflows_marks_binance_history_missing_txid(
    tmp_path, monkeypatch
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    artifact_dir = tmp_path / "batches"
    artifact_dir.mkdir()
    sender = "ExchangeHotWallet111111111111111111111111111"
    receiver = "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"
    (artifact_dir / "latest_2024_SOL_provenance_classification.json").write_text(
        json.dumps(
            {
                "run_id": "run-test",
                "year": 2024,
                "asset": "SOL",
                "total_events": 1,
                "classifications": [
                    {
                        "event_id": "event-in",
                        "signature": "sig-in",
                        "status": "external_or_unknown_origin",
                        "asset": "SOL",
                        "expected_amount": "1.12889582",
                        "matched_amount": "1.12889582",
                        "sender_owner": sender,
                        "receiver_owner": receiver,
                        "sender_is_known_own_wallet": False,
                        "receiver_is_known_own_wallet": True,
                        "block_time": "2024-11-24T07:19:30+00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        WalletFifoPreviewService, "DEFAULT_SOLANA_PROVENANCE_BATCH_DIR", artifact_dir
    )
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Transaction-History.xlsx",
            file_hash="unit:binance",
        )
    )
    raw = store.add_raw_objects(
        batch.batch_id,
        [
            RawObjectCreate(
                row_number=7964,
                payload_json=json.dumps(
                    {
                        "Account": "Spot",
                        "Change": "-1.13689582",
                        "Coin": "SOL",
                        "Operation": "Withdraw",
                        "Remark": "Withdraw fee is included",
                        "Time": "24-11-24 09:24:42",
                    }
                ),
            )
        ],
    )[0]
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2024, 11, 24, 9, 24, 42, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("-1.13689582"),
                account="Spot",
                raw_object_id=raw.raw_object_id,
            )
        ]
    )
    withdrawal_batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance_withdrawal_api",
            filename="binance-withdrawal-api.json",
            file_hash="unit:withdraw-api",
        )
    )
    withdrawal_raw = store.add_raw_objects(
        withdrawal_batch.batch_id,
        [
            RawObjectCreate(
                row_number=1,
                payload_json=json.dumps(
                    {
                        "asset": "SOL",
                        "amount": "1.12889582",
                        "transaction_fee": "0.008",
                        "gross_amount": "1.13689582",
                        "address": receiver,
                        "network": "SOL",
                        "tx_id": "sig-in",
                        "complete_time": "2024-11-24 07:24:42",
                    }
                ),
            )
        ],
    )[0]

    response = TestClient(create_app(store)).get(
        f"/api/v1/tax-years/2024/wallet-fifo-solana-sender-cluster-outflows?asset=SOL&sender_owner={sender}&limit=5&window_hours=48&amount_tolerance_percent=1"
    )

    assert response.status_code == 200
    candidate = response.json()["data"]["samples"][0]["candidates"][0]
    assert candidate["evidence_category"] == "exchange_outflow_candidate"
    assert (
        candidate["exchange_evidence_status"]
        == "transaction_history_without_address_txid"
    )
    assert candidate["raw_filename"] == "Binance-Transaction-History.xlsx"
    assert candidate["withdrawal_evidence_status"] == "withdrawal_address_txid_ready"
    assert candidate["withdrawal_raw_object_id"] == withdrawal_raw.raw_object_id
    assert candidate["withdrawal_tx_id"] == "sig-in"
    assert candidate["withdrawal_address"] == receiver
    assert candidate["withdrawal_fee"] == "0.008"
    assert "Transferanker-Kandidat" in candidate["recommended_action"]
