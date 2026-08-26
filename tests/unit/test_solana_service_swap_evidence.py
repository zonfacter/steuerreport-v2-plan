from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.service_swap_tax_mapping import (
    ServiceSwapTaxMappingService,
)
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService
from steuerreport_v2.domain.tax_years import TaxYearService


SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "audit_solana_service_swap_route_evidence_v2.py"
)
SPEC = importlib.util.spec_from_file_location(
    "audit_solana_service_swap_route_evidence_v2",
    SCRIPT_PATH,
)
assert SPEC is not None and SPEC.loader is not None
SCRIPT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCRIPT)


WALLET = WalletFifoPreviewService.PRIMARY_SOLANA_WALLET
ROUTE_WALLET = "ServiceRouteWallet111111111111111111111111111"
DEPOSIT_ADDRESS = "Ftf2dgeRpBrPFmbd4wQWWqSjCmRjGes1GzNXtxKETeLW"
IOT_MINT = "iotEVVZLEywoTn1QdwNPddxPWszn3zFhEot3MfL9fns"
EVENT_TIME = datetime(2024, 1, 12, 5, 2, 48, tzinfo=timezone.utc)


def _token_balance(owner: str, quantity: str) -> dict[str, object]:
    return {
        "owner": owner,
        "mint": IOT_MINT,
        "uiTokenAmount": {"uiAmountString": quantity},
    }


def _source_transaction() -> dict[str, object]:
    return {
        "blockTime": int(EVENT_TIME.timestamp()),
        "transaction": {
            "message": {
                "accountKeys": [
                    {"pubkey": WALLET, "signer": True},
                    {"pubkey": ROUTE_WALLET, "signer": False},
                ],
                "instructions": [],
            }
        },
        "meta": {
            "err": None,
            "fee": 5_000,
            "preBalances": [100_000_000, 0],
            "postBalances": [99_995_000, 0],
            "preTokenBalances": [_token_balance(WALLET, "75000")],
            "postTokenBalances": [_token_balance(ROUTE_WALLET, "75000")],
            "innerInstructions": [],
        },
    }


def _funding_transaction() -> dict[str, object]:
    return {
        "blockTime": int(EVENT_TIME.replace(minute=5, second=18).timestamp()),
        "transaction": {
            "message": {
                "accountKeys": [
                    {"pubkey": WALLET, "signer": True},
                    {"pubkey": ROUTE_WALLET, "signer": False},
                ],
                "instructions": [
                    {
                        "program": "system",
                        "parsed": {
                            "type": "transfer",
                            "info": {
                                "source": WALLET,
                                "destination": ROUTE_WALLET,
                                "lamports": 50_000_000,
                            },
                        },
                    }
                ],
            }
        },
        "meta": {
            "err": None,
            "fee": 5_000,
            "preBalances": [100_000_000, 0],
            "postBalances": [49_995_000, 50_000_000],
            "preTokenBalances": [],
            "postTokenBalances": [],
            "innerInstructions": [],
        },
    }


def _swap_transaction() -> dict[str, object]:
    return {
        "blockTime": int(EVENT_TIME.replace(minute=5, second=56).timestamp()),
        "transaction": {
            "message": {
                "accountKeys": [
                    {"pubkey": ROUTE_WALLET, "signer": True},
                    {"pubkey": SCRIPT.JUPITER_V6_PROGRAM, "signer": False},
                ],
                "instructions": [{"programId": SCRIPT.JUPITER_V6_PROGRAM}],
            }
        },
        "meta": {
            "err": None,
            "fee": 10_000,
            "preBalances": [50_000_000, 0],
            "postBalances": [1_525_369_140, 0],
            "preTokenBalances": [_token_balance(ROUTE_WALLET, "75000")],
            "postTokenBalances": [],
            "innerInstructions": [],
        },
    }


def _deposit_transaction() -> dict[str, object]:
    return {
        "blockTime": int(EVENT_TIME.replace(minute=7, second=43).timestamp()),
        "transaction": {
            "message": {
                "accountKeys": [
                    {"pubkey": ROUTE_WALLET, "signer": True},
                    {"pubkey": DEPOSIT_ADDRESS, "signer": False},
                ],
                "instructions": [
                    {
                        "program": "system",
                        "parsed": {
                            "type": "transfer",
                            "info": {
                                "source": ROUTE_WALLET,
                                "destination": DEPOSIT_ADDRESS,
                                "lamports": 1_400_000_000,
                            },
                        },
                    }
                ],
            }
        },
        "meta": {
            "err": None,
            "fee": 5_000,
            "preBalances": [1_525_369_140, 0],
            "postBalances": [125_364_140, 1_400_000_000],
            "preTokenBalances": [],
            "postTokenBalances": [],
            "innerInstructions": [],
        },
    }


def _events(store: DuckDbStore):
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="binance",
            filename="Binance-Deposit-History-UTC.xlsx",
            file_hash="service-swap-route",
        )
    )
    raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {"Address": DEPOSIT_ADDRESS, "Status": "Completed"}
            ),
        ),
    )
    mirror_raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=2,
            payload_json=json.dumps(
                {
                    "Account": "Spot",
                    "Change": "1.4",
                    "Coin": "SOL",
                    "Operation": "Deposit",
                    "Time": "24-01-12 07:09:42",
                }
            ),
        ),
    )
    return store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=EVENT_TIME,
                event_type="transfer",
                asset="IOT",
                quantity=Decimal("-75000"),
                fee_asset="SOL",
                fee_quantity=Decimal("0.000005"),
                tx_id="source-transaction",
                account=WALLET,
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=EVENT_TIME.replace(minute=5, second=18),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("-0.050005"),
                fee_asset="SOL",
                fee_quantity=Decimal("0.000005"),
                tx_id="funding-transaction",
                account=WALLET,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=EVENT_TIME.replace(minute=9, second=33),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("1.4"),
                tx_id="deposit-transaction",
                account="binance",
                raw_object_id=raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=EVENT_TIME.replace(minute=9, second=42),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("1.4"),
                account="Spot",
                raw_object_id=mirror_raw.raw_object_id,
            ),
        ]
    )


def _record(events) -> dict[str, object]:
    return SCRIPT.analyze_route(
        source_event=events[0],
        funding_event=events[1],
        deposit_event=events[2],
        deposit_raw_payload={"Address": DEPOSIT_ADDRESS, "Status": "Completed"},
        wallet=WALLET,
        route_wallet=ROUTE_WALLET,
        swap_tx_id="swap-transaction",
        source_transaction=_source_transaction(),
        funding_transaction=_funding_transaction(),
        swap_transaction=_swap_transaction(),
        deposit_transaction=_deposit_transaction(),
    )


def _write_artifact(path: Path, record: dict[str, object]) -> str:
    records = [record]
    semantic_sha256 = hashlib.sha256(
        json.dumps(
            records,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "generated_at": EVENT_TIME.isoformat(),
                "year": 2024,
                "wallet": WALLET,
                "route_wallet": ROUTE_WALLET,
                "provider": "unit",
                "records_count": 1,
                "verified_count": 1,
                "review_count": 0,
                "failed_count": 0,
                "semantic_sha256": semantic_sha256,
                "records": records,
                "rpc_errors": [],
            }
        ),
        encoding="utf-8",
    )
    return semantic_sha256


def _write_mapping_config(
    path: Path,
    *,
    record: dict[str, object],
    semantic_sha256: str,
    mirror_event_id: str,
) -> None:
    direct_cost = Decimal(str(record["direct_wallet_cost_quantity"]))
    source_cost = Decimal(str(record["source_native_outflow_lamports"])) / Decimal(
        "1000000000"
    )
    funding_cost = Decimal(
        str(record["funding_native_outflow_lamports"])
    ) / Decimal("1000000000")
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "mappings": [
                    {
                        "mapping_id": "unit-service-swap",
                        "enabled": True,
                        "year": 2024,
                        "evidence_semantic_sha256": semantic_sha256,
                        "source_event_id": record["source_event_id"],
                        "funding_event_id": record["funding_event_id"],
                        "deposit_event_id": record["deposit_event_id"],
                        "deposit_mirror_event_ids": [mirror_event_id],
                        "swap_tx_id": record["swap_tx_id"],
                        "swap_event_time": record["swap_event_time"],
                        "source_asset": "IOT",
                        "source_quantity": "75000",
                        "acquired_asset": "SOL",
                        "acquired_quantity": "1.4",
                        "source_direct_cost_quantity": str(source_cost),
                        "funding_direct_cost_quantity": str(funding_cost),
                        "direct_cost_asset": "SOL",
                        "direct_cost_quantity": str(direct_cost),
                        "output_withheld_quantity": record[
                            "output_withheld_quantity"
                        ],
                        "source_pool_id": f"solana_rpc:{WALLET}",
                        "deposit_evidence_pool_id": "binance:binance",
                        "target_pool_id": "binance:Spot",
                        "valuation_method": (
                            "received_asset_market_value_at_swap_time"
                        ),
                        "direct_cost_treatment": (
                            "deduct_from_source_disposal_and_realize_cost_asset_disposal"
                        ),
                        "tax_treatment": "taxable_crypto_to_crypto_swap",
                        "bmf_reference": "BMF 06.03.2025 Rn. 54, 58, 59 und 60",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_service_swap_analysis_requires_all_exact_route_legs(tmp_path):
    events = _events(DuckDbStore(tmp_path / "analysis.duckdb"))
    record = _record(events)
    wrong_deposit = _deposit_transaction()
    wrong_deposit["transaction"]["message"]["instructions"][0]["parsed"]["info"][
        "lamports"
    ] = 1_399_999_999
    rejected = SCRIPT.analyze_route(
        source_event=events[0],
        funding_event=events[1],
        deposit_event=events[2],
        deposit_raw_payload={"Address": DEPOSIT_ADDRESS, "Status": "Completed"},
        wallet=WALLET,
        route_wallet=ROUTE_WALLET,
        swap_tx_id="swap-transaction",
        source_transaction=_source_transaction(),
        funding_transaction=_funding_transaction(),
        swap_transaction=_swap_transaction(),
        deposit_transaction=wrong_deposit,
    )

    assert record["classification"] == "service_mediated_jupiter_swap_evidence_ready"
    assert all(record["decision_layer"].values())
    assert record["swap_input_quantity"] == "75000"
    assert record["swap_output_quantity"] == "1.47537914"
    assert record["deposit_quantity"] == "1.4"
    assert record["direct_wallet_cost_quantity"] == "0.05001"
    assert record["output_withheld_quantity"] == "0.07537914"
    assert record["route_balance_after_deposit_quantity"] == "0.12536414"
    assert record["swap_event_time"] == "2024-01-12T05:05:56+00:00"
    assert record["deposit_onchain_event_time"] == "2024-01-12T05:07:43+00:00"
    assert rejected["classification"] == "review_required"
    assert rejected["decision_layer"]["route_to_cex_deposit_exact"] is False


def test_service_swap_artifact_is_integrity_and_database_bound(
    tmp_path,
    monkeypatch,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    events = _events(store)
    evidence_dir = tmp_path / "service-swap-evidence"
    artifact_path = evidence_dir / "latest_2024_service_swap_evidence.json"
    record = _record(events)
    _write_artifact(artifact_path, record)
    service = WalletFifoPreviewService(
        store,
        service_swap_evidence_dir=evidence_dir,
    )

    report = service.solana_service_swap_evidence_latest(2024)
    assert report.status == "evidence_ready_tax_mapping_review_required"
    assert report.evidence_ready is True
    assert report.tax_mapping_ready is False
    assert report.artifact_integrity_valid is True
    assert report.database_binding_valid is True
    assert report.verified_count == 1
    closure = service.provenance_closure_report(2024)
    route_item = next(
        item
        for item in closure.items
        if item.closure_status
        == "documented_service_mediated_jupiter_swap_tax_mapping_review"
    )
    assert route_item.requires_review is True
    assert route_item.category == "service_mediated_jupiter_swap"
    monkeypatch.setattr(
        WalletFifoPreviewService,
        "DEFAULT_SOLANA_SERVICE_SWAP_EVIDENCE_DIR",
        evidence_dir,
    )
    appendix = TaxYearService(store).bmf_closure_appendix(2024)
    appendix_item = next(
        item
        for item in appendix.items
        if item.closure_status
        == "documented_service_mediated_jupiter_swap_tax_mapping_review"
    )
    assert appendix_item.manual_evidence_required is True
    assert appendix_item.conservative_treatment_available is False

    response = TestClient(create_app(store)).get(
        "/api/v1/tax-years/2024/wallet-fifo-solana-service-swap-evidence"
    )
    assert response.status_code == 200
    assert response.json()["data"]["evidence_ready"] is True

    mismatched = dict(record)
    mismatched["deposit_tx_id"] = "different-deposit-transaction"
    _write_artifact(artifact_path, mismatched)
    rejected = service.solana_service_swap_evidence_latest(2024)
    assert rejected.artifact_integrity_valid is True
    assert rejected.database_binding_valid is False
    assert rejected.evidence_ready is False
    assert rejected.status == "review_required"


def test_approved_service_swap_mapping_updates_global_and_wallet_fifo(
    tmp_path,
    monkeypatch,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2023, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="IOT",
                quantity=Decimal("100000"),
                quote_asset="EUR",
                quote_quantity=Decimal("100"),
                account=WALLET,
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2023, 1, 2, tzinfo=timezone.utc),
                event_type="trade",
                asset="SOL",
                quantity=Decimal("2"),
                quote_asset="EUR",
                quote_quantity=Decimal("100"),
                account=WALLET,
            ),
        ]
    )
    events = _events(store)
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("100"),
            priced_at=datetime(2024, 1, 12, tzinfo=timezone.utc),
            source="unit-service-swap-price",
        )
    )
    evidence_dir = tmp_path / "service-swap-evidence"
    artifact_path = evidence_dir / "latest_2024_service_swap_evidence.json"
    record = _record(events)
    semantic_sha256 = _write_artifact(artifact_path, record)
    mapping_path = tmp_path / "service-swap-tax-mappings.json"
    _write_mapping_config(
        mapping_path,
        record=record,
        semantic_sha256=semantic_sha256,
        mirror_event_id=events[3].event_id,
    )

    mapping_report = ServiceSwapTaxMappingService(
        store,
        config_path=mapping_path,
        evidence_dir=evidence_dir,
    ).report()
    assert mapping_report.strict_ready is True
    assert mapping_report.ready_count == 1
    assert all(mapping_report.records[0].decision_layer.model_dump().values())

    result = TaxService(
        store,
        service_swap_tax_mapping_config_path=mapping_path,
        service_swap_evidence_dir=evidence_dir,
    ).rebuild_fifo()
    assert result.unmatched_disposals == 0
    route_source_id = events[0].event_id
    route_funding_id = events[1].event_id
    route_deposit_id = events[2].event_id
    iot_lines = [
        line
        for line in result.tax_lines
        if line.asset == "IOT" and line.source_event_id == route_source_id
    ]
    cost_lines = [
        line
        for line in result.tax_lines
        if line.asset == "SOL"
        and line.source_event_id in {route_source_id, route_funding_id}
    ]
    assert sum((line.quantity for line in iot_lines), Decimal("0")) == Decimal(
        "75000"
    )
    assert sum(
        (line.disposal_proceeds_eur for line in iot_lines), Decimal("0")
    ) == Decimal("134.999")
    assert sum((line.gain_loss_eur for line in iot_lines), Decimal("0")) == Decimal(
        "59.999"
    )
    assert sum((line.quantity for line in cost_lines), Decimal("0")) == Decimal(
        "0.05001"
    )
    assert sum(
        (line.disposal_proceeds_eur for line in cost_lines), Decimal("0")
    ) == Decimal("5.001")
    output_lot = next(
        lot for lot in result.lots if lot.source_event_id == route_deposit_id
    )
    assert output_lot.asset == "SOL"
    assert output_lot.quantity_total == Decimal("1.4")
    assert output_lot.cost_basis_eur_total == Decimal("140")
    assert output_lot.acquired_at == datetime(2024, 1, 12, 5, 5, 56)

    wallet_service = WalletFifoPreviewService(
        store,
        service_swap_evidence_dir=evidence_dir,
        service_swap_tax_mapping_config_path=mapping_path,
    )
    preview = wallet_service.preview(year=2024)
    assert preview.unmatched_count == 0
    assert preview.unresolved_inbound_provenance_count == 0
    assert any(
        trace.status == "service_swap_tax_mapping_applied"
        and trace.quantity == Decimal("1.4")
        and trace.target_pool_id == "binance:Spot"
        for trace in preview.transfer_traces
    )
    evidence_report = wallet_service.solana_service_swap_evidence_latest(2024)
    assert evidence_report.status == "evidence_and_tax_mapping_ready"
    assert evidence_report.tax_mapping_ready is True
    closure_item = next(
        item
        for item in wallet_service.provenance_closure_report(2024).items
        if item.category == "service_mediated_jupiter_swap"
    )
    assert (
        closure_item.closure_status
        == "documented_service_mediated_jupiter_swap_tax_mapping_ready"
    )
    assert closure_item.requires_review is False

    monkeypatch.setattr(
        ServiceSwapTaxMappingService,
        "DEFAULT_CONFIG_PATH",
        mapping_path,
    )
    monkeypatch.setattr(
        ServiceSwapTaxMappingService,
        "DEFAULT_EVIDENCE_DIR",
        evidence_dir,
    )
    monkeypatch.setattr(
        WalletFifoPreviewService,
        "DEFAULT_SOLANA_SERVICE_SWAP_EVIDENCE_DIR",
        evidence_dir,
    )
    appendix_item = next(
        item
        for item in TaxYearService(store).bmf_closure_appendix(2024).items
        if item.closure_status
        == "documented_service_mediated_jupiter_swap_tax_mapping_ready"
    )
    assert appendix_item.manual_evidence_required is False
    assert appendix_item.conservative_treatment_available is True
    response = TestClient(create_app(store)).get(
        "/api/v1/tax/service-swap-mappings"
    )
    assert response.status_code == 200
    assert response.json()["data"]["strict_ready"] is True
    evidence_response = TestClient(create_app(store)).get(
        "/api/v1/tax-years/2024/wallet-fifo-solana-service-swap-evidence"
    )
    assert evidence_response.status_code == 200
    assert evidence_response.json()["data"]["tax_mapping_ready"] is True


def test_service_swap_mapping_rejects_unbound_evidence_sha(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    events = _events(store)
    evidence_dir = tmp_path / "service-swap-evidence"
    record = _record(events)
    semantic_sha256 = _write_artifact(
        evidence_dir / "latest_2024_service_swap_evidence.json",
        record,
    )
    mapping_path = tmp_path / "service-swap-tax-mappings.json"
    _write_mapping_config(
        mapping_path,
        record=record,
        semantic_sha256="0" * len(semantic_sha256),
        mirror_event_id=events[3].event_id,
    )

    report = ServiceSwapTaxMappingService(
        store,
        config_path=mapping_path,
        evidence_dir=evidence_dir,
    ).report()

    assert report.strict_ready is False
    assert report.ready_count == 0
    assert report.records[0].decision_layer.evidence_sha_matches is False
