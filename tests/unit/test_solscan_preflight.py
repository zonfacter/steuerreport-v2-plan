from __future__ import annotations

from decimal import Decimal

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.solscan import (
    SolanaRpcProbeRequest,
    SolscanBlockpitMissingSignature,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.solscan_preflight import SolscanPreflightService


def test_solscan_preflight_compares_iot_signatures_with_blockpit(tmp_path):
    solscan = tmp_path / "export-solscan.csv"
    blockpit = tmp_path / "blockpit.csv"
    wallet = "wallet-1"
    token = "iot-token"
    solscan.write_text(
        "Signature,Time,Action,From,To,Amount,Decimals,TokenAddress\n"
        "sig-in,1704067200,TRANSFER,external,wallet-1,100000000,6,iot-token\n"
        "sig-out,1704153600,TRANSFER,wallet-1,external,40000000,6,iot-token\n",
        encoding="utf-8",
    )
    blockpit.write_text(
        "Date (UTC);Integration Name;Label;Outgoing Asset;Outgoing Amount;"
        "Incoming Asset;Incoming Amount;Fee Asset (optional);Fee Amount (optional);"
        "Trx. ID (optional)\n"
        "01.01.2024 00:00:00;Solana;Deposit;;;IOT;100;; ;sig-in\n"
        "02.01.2024 00:00:00;Solana;Withdrawal;IOT;40;;;;;sig-out\n"
        "03.01.2024 00:00:00;Solana;Withdrawal;IOT;5;;;;;missing-in-solscan\n",
        encoding="utf-8",
    )

    report = SolscanPreflightService().inspect_token(
        file_path=str(solscan),
        blockpit_file_path=str(blockpit),
        wallet=wallet,
        asset="IOT",
        token_address=token,
        max_year=2024,
    )

    assert report.target_changed is False
    assert report.file_coverage.first_event_at == "2024-01-01T00:00:00"
    assert report.file_coverage.last_event_at == "2024-01-02T00:00:00"
    assert report.file_coverage.first_token_event_at == "2024-01-01T00:00:00"
    assert report.file_coverage.last_token_event_at == "2024-01-02T00:00:00"
    assert report.solscan.net_quantity == Decimal("60")
    assert report.blockpit.net_quantity == Decimal("55")
    assert report.matched_signatures == 2
    assert report.blockpit_missing_signatures == 1
    assert report.solscan_extra_signatures == 0
    assert report.matched_quantity_delta == Decimal("0")
    assert report.missing_summary[0].period == "2024-01"
    assert report.missing_summary[0].label == "Withdrawal"
    assert report.missing_summary[0].signatures == 1
    assert report.missing_summary[0].net_quantity == Decimal("-5")
    assert report.missing_blockpit_signatures[0].signature == "missing-in-solscan"
    assert report.missing_blockpit_signatures[0].quantity == Decimal("-5")


def test_solscan_preflight_surfaces_verified_rpc_evidence(tmp_path):
    solscan = tmp_path / "export-solscan.csv"
    blockpit = tmp_path / "blockpit.csv"
    evidence = tmp_path / "rpc-evidence.json"
    solscan.write_text(
        "Signature,Time,Action,From,To,Amount,Decimals,TokenAddress\n",
        encoding="utf-8",
    )
    blockpit.write_text(
        "Date (UTC);Integration Name;Label;Outgoing Asset;Outgoing Amount;"
        "Incoming Asset;Incoming Amount;Fee Asset (optional);Fee Amount (optional);"
        "Trx. ID (optional)\n"
        "03.01.2024 00:00:00;Solana;Withdrawal;IOT;5;;;;;missing-in-solscan\n",
        encoding="utf-8",
    )
    evidence.write_text(
        "{"
        '"jobs_total": 1,'
        '"verified": 1,'
        '"failed": 0,'
        '"rate_limited": 0,'
        '"expected_quantity_sum": "-5",'
        '"wallet_delta_quantity_sum": "-5",'
        '"quantity_delta_sum": "0"'
        "}",
        encoding="utf-8",
    )

    report = SolscanPreflightService().inspect_token(
        file_path=str(solscan),
        blockpit_file_path=str(blockpit),
        wallet="wallet",
        asset="IOT",
        token_address="iot-token",
        max_year=2024,
        rpc_evidence_path=str(evidence),
    )

    assert report.rpc_evidence.status == "verified"
    assert report.rpc_evidence.signatures_total == 1
    assert report.rpc_evidence.verified == 1
    assert report.rpc_evidence.quantity_delta_sum == Decimal("0")


def test_solscan_preflight_api_returns_report(tmp_path):
    solscan = tmp_path / "export-solscan.csv"
    blockpit = tmp_path / "blockpit.csv"
    solscan.write_text(
        "Signature,Time,Action,From,To,Amount,Decimals,TokenAddress\n"
        "sig-in,1704067200,TRANSFER,external,wallet,1000000,6,iot-token\n",
        encoding="utf-8",
    )
    blockpit.write_text(
        "Date (UTC);Integration Name;Label;Outgoing Asset;Outgoing Amount;"
        "Incoming Asset;Incoming Amount;Fee Asset (optional);Fee Amount (optional);"
        "Trx. ID (optional)\n"
        "01.01.2024 00:00:00;Solana;Deposit;;;IOT;1;;;sig-in\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb")))

    response = client.get(
        "/api/v1/import/solscan/token-preflight",
        params={
            "file_path": str(solscan),
            "blockpit_file_path": str(blockpit),
            "wallet": "wallet",
            "asset": "IOT",
            "token_address": "iot-token",
            "max_year": 2024,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["matched_signatures"] == 1
    assert data["target_changed"] is False


def test_solscan_evidence_trace_bundles_rpc_artifact_without_import_effect(tmp_path):
    solscan = tmp_path / "export-solscan.csv"
    blockpit = tmp_path / "blockpit.csv"
    evidence = tmp_path / "rpc-evidence.json"
    solscan.write_text(
        "Signature,Time,Action,From,To,Amount,Decimals,TokenAddress\n",
        encoding="utf-8",
    )
    blockpit.write_text(
        "Date (UTC);Integration Name;Label;Outgoing Asset;Outgoing Amount;"
        "Incoming Asset;Incoming Amount;Fee Asset (optional);Fee Amount (optional);"
        "Trx. ID (optional)\n"
        "03.01.2024 00:00:00;Solana;Withdrawal;IOT;5;;;;;missing-in-solscan\n",
        encoding="utf-8",
    )
    evidence.write_text(
        "{"
        '"jobs_total": 1,'
        '"verified": 1,'
        '"failed": 0,'
        '"rate_limited": 0,'
        '"expected_quantity_sum": "-5",'
        '"wallet_delta_quantity_sum": "-5",'
        '"quantity_delta_sum": "0"'
        "}",
        encoding="utf-8",
    )

    report = SolscanPreflightService().evidence_trace(
        file_path=str(solscan),
        blockpit_file_path=str(blockpit),
        wallet="wallet",
        asset="IOT",
        token_address="iot-token",
        max_year=2024,
        rpc_evidence_path=str(evidence),
    )

    assert report.status == "rpc_verified"
    assert report.import_effect == "none"
    assert report.target_changed is False
    assert report.missing_signatures == 1
    assert report.verified_signatures == 1
    assert report.quantity_delta_sum == Decimal("0")
    assert report.review_scope == "solscan_iot:blockpit_missing_signatures"
    assert report.review_suggestion_id == "solscan_iot_missing_signatures_rpc_verified"
    assert str(evidence) in report.evidence_refs
    assert {step.step_id: step.import_effect for step in report.trace_steps}["rpc_artifact"] == "none"


def test_solscan_evidence_trace_api_returns_read_only_report(tmp_path):
    solscan = tmp_path / "export-solscan.csv"
    blockpit = tmp_path / "blockpit.csv"
    solscan.write_text(
        "Signature,Time,Action,From,To,Amount,Decimals,TokenAddress\n",
        encoding="utf-8",
    )
    blockpit.write_text(
        "Date (UTC);Integration Name;Label;Outgoing Asset;Outgoing Amount;"
        "Incoming Asset;Incoming Amount;Fee Asset (optional);Fee Amount (optional);"
        "Trx. ID (optional)\n",
        encoding="utf-8",
    )
    client = TestClient(create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb")))

    response = client.get(
        "/api/v1/import/solscan/evidence-trace",
        params={
            "file_path": str(solscan),
            "blockpit_file_path": str(blockpit),
            "wallet": "wallet",
            "asset": "IOT",
            "token_address": "iot-token",
            "max_year": 2024,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "covered"
    assert data["import_effect"] == "none"
    assert data["target_changed"] is False


def test_helium_reward_evidence_api_returns_read_only_artifact(tmp_path):
    evidence = tmp_path / "helium-reward-evidence.json"
    evidence.write_text(
        "{"
        '"summary":{"reward_rows":1,"reward_totals":{"HNT":"3.48812900"}},'
        '"rows":[{"signature":"sig-1","asset":"HNT","quantity":"3.48812900","classification":"helium_reward"}],'
        '"target_changed":false,'
        '"import_effect":"none",'
        '"methodology":"read-only test artifact"'
        "}",
        encoding="utf-8",
    )
    client = TestClient(create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb")))

    response = client.get(
        "/api/v1/import/solscan/helium-reward-evidence",
        params={"artifact_path": str(evidence)},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "verified"
    assert data["target_changed"] is False
    assert data["import_effect"] == "none"
    assert data["summary"]["reward_totals"]["HNT"] == "3.48812900"
    assert data["rows"][0]["classification"] == "helium_reward"


def test_solana_rpc_probe_verifies_wallet_token_delta():
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "result": {
                    "slot": 123,
                    "blockTime": 1705541305,
                    "meta": {
                        "err": None,
                        "preTokenBalances": [
                            {
                                "owner": "wallet",
                                "mint": "iot-token",
                                "uiTokenAmount": {
                                    "amount": "100000000",
                                    "decimals": 6,
                                },
                            }
                        ],
                        "postTokenBalances": [
                            {
                                "owner": "wallet",
                                "mint": "iot-token",
                                "uiTokenAmount": {
                                    "amount": "164879512",
                                    "decimals": 6,
                                },
                            }
                        ],
                    },
                }
            }

    class FakeClient:
        def post(self, rpc_url, json):
            assert rpc_url == "https://rpc.example"
            assert json["method"] == "getTransaction"
            return FakeResponse()

    job = SolscanPreflightService()._probe_signature_rpc(
        client=FakeClient(),
        rpc_url="https://rpc.example",
        signature="sig",
        wallet="wallet",
        token_address="iot-token",
        expected=SolscanBlockpitMissingSignature(
            signature="sig",
            event_time="2024-01-01T00:00:00",
            label="Deposit",
            quantity=Decimal("64.879512"),
        ),
    )

    assert job.status == "verified"
    assert job.wallet_delta_quantity == Decimal("64.879512")
    assert job.quantity_delta == Decimal("0")
    assert job.block_time == "2024-01-18T01:28:25"


def test_solana_rpc_probe_request_accepts_delay_seconds():
    request = SolanaRpcProbeRequest(delay_seconds=Decimal("0.25"))

    assert request.delay_seconds == Decimal("0.25")
