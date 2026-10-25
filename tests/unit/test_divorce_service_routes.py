from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.divorce_service_routes import (
    DivorceServiceRouteDecisionRequest,
    DivorceServiceRouteEvidenceRefreshRequest,
)
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.divorce_service_routes import (
    DivorceServiceRouteEvidenceService,
)
from steuerreport_v2.domain.divorce_capital_flows import DivorceCapitalFlowService
from steuerreport_v2.domain.tax import TaxService


OPEN_TX = "VoD5cPnG87Z32TkiSWwn99KdnfZcyabeNCGrTy3Zk21onoGqcbX4nRujbDKZKHAx12GF3dxrVaPKM1X17d9EWTz"
CLOSE_TX = "57Cr2PXABViecRonjhYEvJpYqFn5C58WAzy6XTPCCd99c3iNxUCbVNdi8L3fY4Rgk63RkPtiuRaPPT9CgPUXseKc"
FAILED_TX = "5BHFpY7jiGD9fu313fR7gKbQ96MmiwUaB2L7fSt1ncrK31Pf2zML8WLFByd4npqchSoD3EVynVmNRtn8DKk8ESLF"
WALLET = "GmHYjZGkcHBZ3WyGZ9eUGDZMfHvJTLtTKXu6dnSc63yu"
WRAPPED = "79VRvygpbWYWPP4q3vT5kHktgxdnL6myBsDdYLa9LKcu"
POSITION = "7141SmgRfdhVSBR7u7Un9jCf7ESKnqe4FukMJPPgAm7f"
PERPS = "PERPHjGBqRHArX4DySjwM6UJHiR3sWAatqfdBS2qQJu"


def _store(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime.fromtimestamp(1769027359, tz=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("-0.2003719"),
                account=WALLET,
                tx_id=OPEN_TX,
            )
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("100"),
            priced_at=datetime(2026, 1, 21, tzinfo=timezone.utc),
            source="event-day-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("100"),
            priced_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
            source="same-day-test",
        )
    )
    registry_path = tmp_path / "source_registry.json"
    registry_path.write_text(
        json.dumps(
            {
                "registry_version": "test",
                "entries": [
                    {
                        "source_id": "jup-inheritance-wallet",
                        "label": "JUP Erbgeld-Wallet",
                        "source_type": "wallet",
                        "ownership": "owned",
                        "role": "portfolio_inheritance",
                        "portfolio_policy": "include",
                        "fifo_policy": "owned_pool",
                        "valid_from": "2026-01-01T00:00:00Z",
                        "coverage_status": "complete",
                        "identifiers": [{"kind": "account", "value": WALLET}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return store, registry_path


def _opening_payload():
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "slot": 395042495,
            "blockTime": 1769027359,
            "meta": {
                "err": None,
                "fee": 16940,
                "preBalances": [234872162, 2039280, 0, 1],
                "postBalances": [34500262, 0, 2394240, 1],
                "logMessages": [
                    f"Program {PERPS} invoke [1]",
                    "Program log: Instruction: InstantIncreasePosition",
                    "Program log: Current price: 130177083",
                    "Program log: Collected fee: 90806",
                    "Program log: Collateral added in USD: 26035416",
                    "Program log: Update existing position",
                    f"Program {PERPS} success",
                ],
                "innerInstructions": [
                    {
                        "index": 2,
                        "instructions": [
                            {
                                "program": "system",
                                "programId": "11111111111111111111111111111111",
                                "parsed": {
                                    "type": "createAccount",
                                    "info": {
                                        "lamports": 2394240,
                                        "newAccount": POSITION,
                                        "owner": PERPS,
                                        "source": WALLET,
                                    },
                                },
                            },
                            {
                                "program": "spl-token",
                                "programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
                                "parsed": {
                                    "type": "transfer",
                                    "info": {
                                        "amount": "200000000",
                                        "authority": WALLET,
                                        "destination": "perps-custody",
                                        "source": WRAPPED,
                                    },
                                },
                            },
                        ],
                    }
                ],
            },
            "transaction": {
                "signatures": [OPEN_TX],
                "message": {
                    "accountKeys": [
                        {"pubkey": WALLET, "signer": True, "writable": True},
                        {"pubkey": WRAPPED, "signer": False, "writable": True},
                        {"pubkey": POSITION, "signer": False, "writable": True},
                        {"pubkey": PERPS, "signer": False, "writable": False},
                    ],
                    "instructions": [
                        {
                            "program": "system",
                            "programId": "11111111111111111111111111111111",
                            "parsed": {
                                "type": "transfer",
                                "info": {
                                    "destination": WRAPPED,
                                    "lamports": 200000000,
                                    "source": WALLET,
                                },
                            },
                        },
                        {
                            "accounts": [WALLET, WRAPPED, POSITION, PERPS],
                            "programId": PERPS,
                        },
                        {
                            "program": "spl-token",
                            "parsed": {
                                "type": "closeAccount",
                                "info": {
                                    "account": WRAPPED,
                                    "destination": WALLET,
                                    "owner": WALLET,
                                },
                            },
                        },
                    ],
                },
            },
        },
    }


def _signatures_payload(include_liquidation=True):
    rows = [
        {
            "signature": OPEN_TX,
            "blockTime": 1769027359,
            "slot": 395042495,
            "err": None,
        },
        {
            "signature": FAILED_TX,
            "blockTime": 1769879410,
            "slot": 397172474,
            "err": {"InstructionError": [4, {"Custom": 6009}]},
        },
    ]
    if include_liquidation:
        rows.append(
            {
                "signature": CLOSE_TX,
                "blockTime": 1769879409,
                "slot": 397172472,
                "err": None,
            }
        )
    return {"jsonrpc": "2.0", "id": 1, "result": rows}


def _liquidation_payload():
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "slot": 397172472,
            "blockTime": 1769879409,
            "meta": {
                "err": None,
                "fee": 120171,
                "preBalances": [64597760384, 2394240, 1],
                "postBalances": [64597640213, 2394240, 1],
                "logMessages": [
                    f"Program {PERPS} invoke [1]",
                    "Program log: Instruction: LiquidateFullPosition4",
                    "Program log: Exit price: 104988945",
                    "Program log: Collected fee: 596285",
                    "Program log: Net loss: 25099979",
                    f"Program {PERPS} success",
                ],
            },
            "transaction": {
                "signatures": [CLOSE_TX],
                "message": {
                    "accountKeys": [
                        {"pubkey": "keeper", "signer": True, "writable": True},
                        {"pubkey": POSITION, "signer": False, "writable": True},
                        {"pubkey": PERPS, "signer": False, "writable": False},
                    ],
                    "instructions": [{"accounts": [POSITION], "programId": PERPS}],
                },
            },
        },
    }


def _transport(include_liquidation=True):
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        method = payload["method"]
        if method == "getSignaturesForAddress":
            return httpx.Response(
                200,
                json=_signatures_payload(include_liquidation=include_liquidation),
            )
        signature = payload["params"][0]
        if signature == OPEN_TX:
            return httpx.Response(200, json=_opening_payload())
        if signature == CLOSE_TX:
            return httpx.Response(200, json=_liquidation_payload())
        raise AssertionError(f"unexpected rpc request: {payload}")

    return httpx.MockTransport(handler)


def test_service_route_evidence_binds_full_liquidation_and_is_idempotent(tmp_path):
    store, registry_path = _store(tmp_path)
    service = DivorceServiceRouteEvidenceService(
        store,
        artifact_root=tmp_path / "service-route-evidence",
        registry_path=registry_path,
        transport=_transport(),
    )

    report = service.refresh(DivorceServiceRouteEvidenceRefreshRequest(tx_id=OPEN_TX))

    assert report.status == "ready_for_review"
    assert report.strict_ready is True
    assert all(report.decision_layer.model_dump().values())
    assert report.wallet_source_id == "jup-inheritance-wallet"
    assert report.wallet_debit_lamports == 200371900
    assert report.collateral_quantity == Decimal("0.2")
    assert report.collateral_added_usd == Decimal("26.035416")
    assert report.position_account == POSITION
    assert report.liquidation_tx_id == CLOSE_TX
    assert report.liquidation_instruction == "LiquidateFullPosition4"
    assert report.liquidation_net_loss_usd == Decimal("25.099979")
    assert report.residual_position_account_quantity == Decimal("0.00239424")
    assert report.residual_position_account_price_eur == Decimal("100")
    assert report.decision_layer.residual_account_rent_same_day_priced is True
    assert report.residual_position_account_value_eur == Decimal("0.23942400")
    assert len(report.evidence_files) == 3
    assert all(Path(item.path).is_file() for item in report.evidence_files)

    request = DivorceServiceRouteDecisionRequest(
        tx_id=OPEN_TX,
        semantic_sha256=report.semantic_sha256,
        actor="test",
    )
    result = service.accept(request)
    repeated = service.accept(request)

    assert result.already_recorded is False
    assert repeated.already_recorded is True
    assert repeated.decision.decision_id == result.decision.decision_id
    assert result.decision.payload["decision_status"] == (
        "internal_service_position_loss_confirmed"
    )
    assert result.decision.payload["fifo_effect"] == "none"
    assert result.decision.payload["tax_classification_effect"] == "none"
    assert OPEN_TX in service.accepted_decisions({OPEN_TX})
    bundle = service.accepted_evidence_bundle({OPEN_TX})
    assert bundle.reports_count == 1
    assert bundle.accepted_decisions_count == 1
    assert bundle.reports[0].semantic_sha256 == report.semantic_sha256
    assert bundle.accepted_decisions[0].tx_id == OPEN_TX
    assert bundle.accepted_decisions[0].evidence_semantic_sha256 == (
        report.semantic_sha256
    )
    assert bundle.accepted_decisions[0].decision.decision_id == (
        result.decision.decision_id
    )
    assert bundle.accepted_decisions[0].decision.evidence_ref == (
        result.decision.evidence_ref
    )
    assert TaxService(store).list_tax_lines() == []

    gate = DivorceCapitalFlowService(
        store,
        service_route_evidence_service=service,
    ).report(
        cutoff_at=datetime(2025, 6, 13, 21, 59, 59, tzinfo=timezone.utc),
        valuation_at=datetime(2026, 7, 24, 21, 59, 59, tzinfo=timezone.utc),
        opening_value_eur=Decimal("100"),
        closing_value_eur=Decimal("80"),
        binance_contributions_eur=Decimal("0"),
        confirmed_onramp_contributions_eur=Decimal("0"),
        provisional_onramp_contributions_eur=Decimal("0"),
        materiality_threshold_eur=Decimal("1"),
    )

    assert gate.strict_ready is True
    assert gate.material_review_outflows_count == 0
    assert gate.confirmed_service_position_loss_count == 1
    assert gate.internal_service_position_loss_value_eur == Decimal(
        "20.037190000000000000"
    )
    assert gate.flow_adjusted_change_eur == Decimal("-20")
    assert gate.outflows[0].classification == "internal_service_position_loss"
    assert gate.outflows[0].affects_flow_adjusted_change is False


def test_service_route_evidence_stays_in_review_without_full_liquidation(tmp_path):
    store, registry_path = _store(tmp_path)
    service = DivorceServiceRouteEvidenceService(
        store,
        artifact_root=tmp_path / "service-route-evidence",
        registry_path=registry_path,
        transport=_transport(include_liquidation=False),
    )

    report = service.refresh(DivorceServiceRouteEvidenceRefreshRequest(tx_id=OPEN_TX))

    assert report.status == "review_required"
    assert report.strict_ready is False
    assert report.decision_layer.full_liquidation_before_end_date is False
    assert report.decision_layer.no_successful_activity_after_liquidation is False
    try:
        service.accept(
            DivorceServiceRouteDecisionRequest(
                tx_id=OPEN_TX,
                semantic_sha256=report.semantic_sha256,
            )
        )
    except ValueError as exc:
        assert str(exc) == "service_route_evidence_not_ready"
    else:
        raise AssertionError("unready service-route evidence must not be accepted")


def test_service_route_evidence_api_exposes_refresh_latest_and_decision(
    tmp_path,
    monkeypatch,
):
    store, registry_path = _store(tmp_path)
    service = DivorceServiceRouteEvidenceService(
        store,
        artifact_root=tmp_path / "service-route-evidence",
        registry_path=registry_path,
        transport=_transport(),
    )
    report = service.refresh(DivorceServiceRouteEvidenceRefreshRequest(tx_id=OPEN_TX))
    result = service.accept(
        DivorceServiceRouteDecisionRequest(
            tx_id=OPEN_TX,
            semantic_sha256=report.semantic_sha256,
        )
    )
    monkeypatch.setattr(
        DivorceServiceRouteEvidenceService,
        "refresh",
        lambda self, request: report,
    )
    monkeypatch.setattr(
        DivorceServiceRouteEvidenceService,
        "latest",
        lambda self, tx_id: report if tx_id == OPEN_TX else None,
    )
    monkeypatch.setattr(
        DivorceServiceRouteEvidenceService,
        "accept",
        lambda self, request: result,
    )
    client = TestClient(create_app(tmp_path / "api.duckdb"))

    refreshed = client.post(
        "/api/v1/divorce/service-route-evidence/refresh",
        json={"tx_id": OPEN_TX, "end_asset_date": "2026-07-24"},
    )
    latest = client.get(f"/api/v1/divorce/service-route-evidence/{OPEN_TX}")
    accepted = client.post(
        "/api/v1/divorce/service-route-evidence/decisions",
        json={"tx_id": OPEN_TX, "semantic_sha256": report.semantic_sha256},
    )

    assert refreshed.status_code == 200
    assert refreshed.json()["data"]["strict_ready"] is True
    assert latest.status_code == 200
    assert latest.json()["data"]["position_account"] == POSITION
    assert accepted.status_code == 200
    assert accepted.json()["data"]["decision"]["payload"]["fifo_effect"] == "none"
