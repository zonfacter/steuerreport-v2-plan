from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import io
import json
from types import SimpleNamespace
from zipfile import ZipFile

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.moonpay_receipts import MoonpayReceiptReport
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.contracts.valuation_runs import DivorceValuationRunRequest
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.valuation_runs import DivorceValuationRunService
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


def _store(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                source_ref="eur-deposit",
                event_time=datetime(2024, 12, 31, tzinfo=timezone.utc),
                event_type="transfer",
                asset="EUR",
                quantity=Decimal("100"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                source_ref="btc-buy",
                event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("1"),
                quote_asset="EUR",
                quote_quantity=Decimal("100"),
                account="Spot",
            ),
        ]
    )
    for priced_at, price in (
        (datetime(2025, 6, 13, 12, tzinfo=timezone.utc), Decimal("110")),
        (datetime(2026, 7, 24, 12, tzinfo=timezone.utc), Decimal("130")),
    ):
        store.add_price_point(
            PricePointCreate(
                asset="BTC",
                price_eur=price,
                priced_at=priced_at,
                source="test",
            )
        )
    TaxService(store).rebuild_fifo()
    BalanceLedgerBuilder(store).rebuild()
    return store


def test_divorce_valuation_run_versions_two_exact_fifo_checkpoints_and_evidence(
    tmp_path,
    monkeypatch,
):
    store = _store(tmp_path)
    trade_history = tmp_path / "MoonPay_trade-history.csv"
    trade_history.write_text("id,status\ntrade-1,completed\n", encoding="utf-8")
    trade_history_content = trade_history.read_bytes()
    trade_history_sha256 = hashlib.sha256(trade_history_content).hexdigest()

    class MoonpayReceiptStub:
        def __init__(self, _store):
            self.trade_history_path = trade_history

        def report(self, *, as_of):
            assert as_of == datetime(
                2026, 7, 24, 21, 59, 59, 999999, tzinfo=timezone.utc
            )
            return MoonpayReceiptReport(
                generated_at=datetime(2026, 8, 21, tzinfo=timezone.utc),
                status="ready",
                strict_ready=True,
                sender_address="moonpay-sender",
                manifest_path="manifest.json",
                trade_history_path=str(trade_history),
                trade_history_exists=True,
                trade_history_sha256=trade_history_sha256,
                trade_history_size_bytes=len(trade_history_content),
                candidates_count=1,
                ready_count=1,
                semantic_sha256="m" * 64,
                methodology="test evidence",
            )

    monkeypatch.setattr(
        "steuerreport_v2.domain.valuation_runs.MoonpayReceiptService",
        MoonpayReceiptStub,
    )
    service = DivorceValuationRunService(store)

    report = service.run(DivorceValuationRunRequest())

    assert report.status == "blocked"
    assert report.strict_ready is False
    assert report.summary.stichtage.end_asset_date.isoformat() == "2026-07-24"
    assert report.summary.stichtage.court_evidence_status == "pending_document"
    assert any("Gerichts-/Zustellungsbeleg" in item for item in report.next_actions)
    assert report.cutoff_value_eur == Decimal("110.000000000000000000")
    assert report.valuation_value_eur == Decimal("130.000000000000000000")
    assert report.cutoff_price_gate.strict_ready is True
    assert report.valuation_price_gate.strict_ready is True
    assert report.source_registry_status == "blocked"
    assert report.source_registry_strict_ready is False
    assert report.source_provider_coverage_gap_count >= 0
    assert report.source_user_evidence_gap_count >= 0
    assert report.source_quantity_blocker_count >= 0
    assert report.source_registry_semantic_sha256
    assert [item.label for item in report.fifo_checkpoints] == ["cutoff", "valuation"]
    assert all(not item.reused_existing_run for item in report.fifo_checkpoints)
    assert all(
        item.unmatched_classification_complete for item in report.fifo_checkpoints
    )
    assert all(item.provider_basis_gap_count == 0 for item in report.fifo_checkpoints)
    assert all(
        item.unexplained_unmatched_count == 0 for item in report.fifo_checkpoints
    )
    assert all(
        item.method_gap_classification_complete for item in report.fifo_checkpoints
    )
    assert all(
        item.unexplained_method_gap_groups_count == 0
        for item in report.fifo_checkpoints
    )
    assert report.fifo_checkpoints[0].as_of == report.cutoff_at
    assert report.fifo_checkpoints[1].as_of == report.valuation_at
    assert all(
        item.report_url.endswith(item.run_id) for item in report.fifo_checkpoints
    )
    assert service.latest() == report
    assert service.get(report.run_id) == report

    dossier = next(
        item for item in report.evidence_files if item.kind == "evidence_package"
    )
    dossier_path = service.evidence_path(report.run_id, "stichtag-zugewinn-dossier.zip")
    assert dossier.download_url is not None
    assert dossier_path is not None
    with ZipFile(dossier_path) as package:
        names = set(package.namelist())
        assert "equalization_summary.json" in names
        assert "accounts.csv" in names
        assert "valuation_tokens.csv" in names
        assert "price_gates.json" in names
        assert "stichtag_token_valuation_decisions.csv" in names
        assert "capital_flow_reconciliation.json" in names
        assert "capital_flow_reconciliation.csv" in names
        assert "service_route_evidence.json" in names
        service_routes = json.loads(package.read("service_route_evidence.json"))
        assert service_routes["reports_count"] == 0
        assert service_routes["accepted_decisions_count"] == 0
        assert service_routes["accepted_decisions"] == []
        assert "inheritance_origin.json" in names
        assert "inheritance_origin.csv" in names
        assert "inheritance_credit_evidence.csv" in names
        assert "trade_republic_document_evidence.csv" in names
        assert "formal_inheritance_document_evidence.csv" in names
        assert "coinbase_history_valuation_evidence.csv" in names
        assert "fifo_checkpoints.json" in names
        assert "bitget_strategy_fifo_gaps_cutoff.json" in names
        assert "bitget_strategy_fifo_gaps_valuation.json" in names
        assert "bitget_strategy_basis_reconstruction_cutoff.json" in names
        assert "bitget_strategy_basis_reconstruction_cutoff.csv" in names
        assert "bitget_strategy_basis_reconstruction_valuation.json" in names
        assert "bitget_strategy_basis_reconstruction_valuation.csv" in names
        assert "bitget_support_package_manifest.json" in names
        assert "bitget_support_package.zip" in names
        bitget_support_manifest = json.loads(
            package.read("bitget_support_package_manifest.json")
        )
        assert bitget_support_manifest["status"] == "support_package_unavailable"
        with ZipFile(io.BytesIO(package.read("bitget_support_package.zip"))) as support:
            assert support.namelist() == ["bitget_support_manifest.json"]
        assert "source_manifest.json" in names
        assert "source_registry.json" in names
        assert "solana_staking_position_reconciliation.json" in names
        assert "moonpay_receipt_reconciliation.json" in names
        assert package.read("moonpay_trade_history.csv") == trade_history_content
        moonpay = json.loads(package.read("moonpay_receipt_reconciliation.json"))
        assert moonpay["trade_history_sha256"] == trade_history_sha256
        manifest = json.loads(package.read("manifest.json"))
        assert manifest["read_only"] is True
        assert len(manifest["wallet_fifo_runs"]) == 2

    repeated = service.run(DivorceValuationRunRequest())

    assert repeated.run_id != report.run_id
    assert [item.run_id for item in repeated.fifo_checkpoints] == [
        item.run_id for item in report.fifo_checkpoints
    ]
    assert all(item.reused_existing_run for item in repeated.fifo_checkpoints)
    assert service.latest() == repeated


def test_divorce_valuation_next_actions_separate_provider_and_user_gaps():
    summary = SimpleNamespace(
        cutoff_price_gate=SimpleNamespace(strict_ready=True),
        valuation_price_gate=SimpleNamespace(strict_ready=True),
        capital_flow_gate=SimpleNamespace(
            provisional_contributions_eur=Decimal("0"),
            capital_origin_pending_count=0,
            material_review_outflows_count=0,
        ),
        inheritance_origin_gate=SimpleNamespace(next_actions=[]),
        stichtage=SimpleNamespace(court_evidence_status="documented"),
    )
    checkpoint = SimpleNamespace(
        provider_basis_gap_count=10,
        unexplained_unmatched_count=0,
        unresolved_inbound_provenance_count=0,
        event_set_mismatch_years=[],
        acquisition_cost_evidence_review_count=0,
        method_gap_classification_complete=True,
        provider_basis_event_set_gap_groups_count=2,
        provider_basis_quantity_gap_groups_count=3,
        unexplained_method_gap_groups_count=0,
        strict_ready=False,
    )
    source_registry = SimpleNamespace(
        provider_coverage_gap_entries_count=2,
        user_evidence_gap_entries_count=1,
        quantity_blocker_entries_count=0,
        next_actions=[
            "Pionex Account: API-Key/Secret fuer diese Quelle im V2 Secret Store erneuern."
        ],
    )

    actions = DivorceValuationRunService._next_actions(
        summary, [checkpoint], source_registry
    )

    assert any("2 dokumentierte Provider-Abdeckungsgrenze" in item for item in actions)
    assert any("Fuer 1 Quelle" in item for item in actions)
    assert any("Quellenregistry: Pionex Account: API-Key/Secret" in item for item in actions)
    assert any("Providergebundene FIFO-Kostenbasisluecken" in item for item in actions)
    assert not any("Wirklich ungeklaerte FIFO-Herkunft" in item for item in actions)


def test_divorce_valuation_run_api_and_wallet_fifo_run_lookup(tmp_path):
    store = _store(tmp_path)
    client = TestClient(create_app(store))

    response = client.post("/api/v1/divorce/valuation-runs", json={})

    assert response.status_code == 200
    report = response.json()["data"]
    run_id = report["run_id"]
    latest = client.get("/api/v1/divorce/valuation-runs/latest")
    assert latest.status_code == 200
    assert latest.json()["data"]["run_id"] == run_id
    by_id = client.get(f"/api/v1/divorce/valuation-runs/{run_id}")
    assert by_id.status_code == 200
    assert by_id.json()["data"]["semantic_sha256"] == report["semantic_sha256"]

    fifo_run_id = report["fifo_checkpoints"][0]["run_id"]
    fifo = client.get(f"/api/v1/tax/wallet-fifo-runs/{fifo_run_id}")
    assert fifo.status_code == 200
    assert fifo.json()["data"]["run_id"] == fifo_run_id

    evidence = client.get(
        f"/api/v1/divorce/valuation-runs/{run_id}/evidence/price_gates.json"
    )
    assert evidence.status_code == 200
    assert evidence.headers["content-type"].startswith("application/json")

    capital_flows = client.get("/api/v1/divorce/equalization-summary/capital-flows.csv")
    assert capital_flows.status_code == 200
    assert capital_flows.headers["content-type"].startswith("text/csv")
    assert capital_flows.text.startswith("row_type,flow_id,event_id,event_time")
