from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import io
import json
from zipfile import ZipFile

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.bitget_strategy_reconstruction import (
    BitgetStrategyReferencePriceBackfillRequest,
)
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.contracts.wallet_fifo_runs import WalletFifoParallelRunRequest
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.bitget_strategy_fifo import BitgetStrategyFifoGapService
from steuerreport_v2.domain.bitget_strategy_reconstruction import (
    BitgetStrategyBasisReconstructionService,
)
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.wallet_fifo_acceptance import (
    WalletFifoMethodAcceptanceService,
)
from steuerreport_v2.domain.wallet_fifo_runs import WalletFifoParallelRunService


def _write_bitget_support_package(tmp_path):
    root = tmp_path / "bitget-support"
    root.mkdir()
    files = {
        "Deposit-Withdrawal History.csv": (
            "Deposit-Withdrawal History,,\n"
            "Order no.,UID\n"
        ),
        "Spot Financial Record.csv": (
            "Spot Financial Record,,\n"
            "Order no.,UID,Coin,Action,Creation timestamp (+8 UTC)\n"
        ),
        "Spot Trading History.csv": (
            "Spot Trading History,,\n"
            "id,UID,Trading pair,Coin,Action,Executed price,Quantity,"
            "Transacted amount,Timestamp UTC+8 (Created)\n"
            "trade-1,operator-reference,HNTUSDT,HNT,buy,5,1,5,2024-01-15 08:00:00\n"
        ),
        "Futures Financial Record.csv": (
            "Futures Financial Record,,\n"
            "UID,Coin,Action (English),Timestamp UTC+8 (Order)\n"
        ),
        "Futures Trading History.csv": (
            "Futures Trading History,,\n"
            "Order Number,UID,Action,Trading Pair,Timestamp UTC+8 (Order)\n"
        ),
        "Strategy.csv": (
            "Strategy,,,,\n"
            "UID,Strategy ID,Futures/Spot,Strategy type,Status,Trading pair,"
            "Investment amount,Total gains,Strategy identifier,"
            "Timestamp(creation) - (UTC+8),Timestamp(termination) - (UTC+8),"
            "Fee(base asset),Fee(quote asset),Status upon termination,"
            "Reason of termination,Voucher used,Arbitrage\n"
            "operator-reference,strategy-1,Spot,Spot grid (positive),Inactive,HNTUSDT,"
            "30,2,identifier,2024-01-01 08:00:00,2024-02-01 08:00:00,"
            "0.1,0,Manual operation,Manual termination,0,0\n"
        ),
    }
    for filename, content in files.items():
        (root / filename).write_text(content, encoding="utf-8")
    return root


def _bitget_strategy_store(tmp_path):
    _write_bitget_support_package(tmp_path)
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="bitget",
            filename="Spot Financial Record.csv",
            file_hash="sha256:bitget-primary",
        )
    )
    raw_buy = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "Order no.": "buy-1",
                    "Action": "ORDER_DEALT_IN",
                    "Coin": "HNT",
                    "Quantity": "4",
                }
            ),
        ),
    )
    raw_settlement = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=2,
            payload_json=json.dumps(
                {
                    "Order no.": "settlement-1",
                    "Action": "STRATEGY_TRANSFER_IN",
                    "Coin": "HNT",
                    "Quantity": "6",
                    "Amount (USDT)": "42",
                    "Type": "Fund transfer",
                }
            ),
        ),
    )
    raw_later_buy = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=3,
            payload_json=json.dumps(
                {
                    "Order no.": "buy-2",
                    "Action": "ORDER_DEALT_IN",
                    "Coin": "HNT",
                    "Quantity": "1",
                }
            ),
        ),
    )
    raw_sale = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=4,
            payload_json=json.dumps(
                {
                    "Order no.": "sale-1",
                    "Action": "ORDER_DEALT_FROZEN_OUT",
                    "Coin": "HNT",
                    "Quantity": "-10.999",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="bitget",
                source_ref="buy-1",
                event_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("4"),
                quote_asset="USDT",
                quote_quantity=Decimal("-20"),
                account="bitget",
                raw_object_id=raw_buy.raw_object_id,
            ),
            CanonicalEventCreate(
                source="bitget",
                source_ref="settlement-1",
                event_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("6"),
                tx_id="settlement-1",
                account="bitget",
                raw_object_id=raw_settlement.raw_object_id,
            ),
            CanonicalEventCreate(
                source="bitget",
                source_ref="buy-2",
                event_time=datetime(2024, 2, 2, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("1"),
                quote_asset="USDT",
                quote_quantity=Decimal("-5"),
                account="bitget",
                raw_object_id=raw_later_buy.raw_object_id,
            ),
            CanonicalEventCreate(
                source="bitget",
                source_ref="sale-1",
                event_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("-10.999"),
                quote_asset="USDT",
                quote_quantity=Decimal("60"),
                account="bitget",
                raw_object_id=raw_sale.raw_object_id,
            ),
        ]
    )
    TaxService(store).rebuild_fifo()
    return store


def test_bitget_strategy_gap_reconciles_quantity_but_keeps_basis_blocked(
    tmp_path,
    monkeypatch,
):
    store = _bitget_strategy_store(tmp_path)
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="pionex",
                source_ref="independent-hnt-lot",
                event_time=datetime(2023, 12, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("10"),
                quote_asset="EUR",
                quote_quantity=Decimal("-10"),
                account="pionex",
            )
        ]
    )
    TaxService(store).rebuild_fifo()
    blockpit = tmp_path / "blockpit.csv"
    blockpit.write_text(
        "Date (UTC);Integration Name;Label;Outgoing Asset;Outgoing Amount;"
        "Incoming Asset;Incoming Amount;Fee Asset (optional);Fee Amount (optional);"
        "Comment (optional);Trx. ID (optional);Source Type;Source Name\n"
        "01.02.2024 00:00:00;Bitget;Mining;;;HNT;6;;;Automatic deposit;"
        "settlement-1;API;Bitget\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        BitgetStrategyFifoGapService,
        "DEFAULT_BLOCKPIT_REFERENCE_PATH",
        blockpit,
    )
    artifact_root = tmp_path / "var/wallet_fifo_runs"
    before = {}
    with store.connect() as con:
        for table in ("canonical_events", "tax_lots", "tax_lines"):
            before[table] = con.execute(f"select count(*) from {table}").fetchone()[0]

    run = WalletFifoParallelRunService(
        store,
        artifact_root=artifact_root,
    ).run(
        WalletFifoParallelRunRequest(
            years=[2024],
            as_of=datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
        )
    )
    report = BitgetStrategyFifoGapService(
        store,
        artifact_root=artifact_root,
        blockpit_reference_path=blockpit,
    ).report(run_id=run.run_id)

    assert report is not None
    assert run.bitget_strategy_gap_status == "quantity_reconciled_basis_pending"
    assert run.bitget_strategy_gap_quantity_reconciled is True
    assert run.bitget_strategy_gap_groups_count == 1
    assert run.bitget_strategy_gap_linked_disposals_count == 1
    assert run.bitget_strategy_gap_unallocated_disposals_count == 0
    assert run.report_schema_version == (
        "wallet_fifo_run_v2_provider_basis_classification"
    )
    assert run.unmatched_count == 3
    assert run.provider_basis_gap_count == 1
    assert run.unexplained_unmatched_count == 2
    assert run.year_results[0].provider_basis_gap_count == 1
    assert run.year_results[0].unexplained_unmatched_count == 2
    acceptance = WalletFifoMethodAcceptanceService(store).readiness(
        run_id=run.run_id
    )
    checks = {check.key: check for check in acceptance.checks}
    assert acceptance.provider_basis_gap_count == 1
    assert acceptance.unexplained_unmatched_count == 2
    assert acceptance.provider_basis_resolution_required is True
    assert acceptance.provider_basis_event_set_gap_groups_count == 0
    assert acceptance.provider_basis_quantity_gap_groups_count == 1
    assert acceptance.unexplained_method_gap_groups_count == 0
    assert checks["provider_basis_complete"].passed is False
    assert checks["no_unexplained_unmatched_disposals"].passed is False
    assert any("Provider nicht exportierte Bot-Fill-Kostenbasis" in item for item in run.findings)
    assert any("keine weiteren Nutzerexporte" in item for item in run.next_actions)
    assert report.status == "quantity_reconciled_basis_pending"
    assert report.strict_ready is False
    assert report.quantity_reconciled is True
    assert report.original_acquisition_basis_complete is False
    assert report.unmatched_disposals_count == 1
    assert report.out_of_scope_bitget_unmatched_disposals_count == 2
    assert report.linked_unmatched_disposals_count == 1
    assert report.unallocated_unmatched_disposals_count == 0
    assert report.asset_totals[0].asset == "HNT"
    assert report.asset_totals[0].strategy_quantity_without_cost_basis == Decimal("6")
    assert report.asset_totals[0].allocated_missing_quantity == Decimal("5.999")
    assert report.asset_totals[0].residual_quantity == Decimal("0.001")
    group = report.groups[0]
    assert group.quantity_equation == (
        "6.000000000000000000 = 5.999000000000000000 + "
        "0.001000000000000000 HNT"
    )
    assert group.acquisition_time_status == "missing_original_bot_fills"
    assert group.acquisition_cost_status == "missing_original_bot_fill_cost_basis"
    assert group.blockpit_reference.label == "Mining"
    assert group.blockpit_reference.classification_conflict is True
    assert group.blockpit_reference.reward_classification_effect == "none"
    assert group.reward_classification_effect == "none"
    assert report.blockpit_classification_conflict_count == 1
    assert report.support_package.package_complete is True
    assert report.support_package.available_files_count == 6
    assert report.support_package.additional_user_export_required is False
    assert report.support_package.provider_export_field_gap is True
    assert report.support_package.relevant_strategy_matches_count == 1
    assert report.support_package.strategy_linked_fill_rows_count == 0
    assert group.basis_gap_responsibility == "provider_export_field_gap"
    assert group.support_strategy_match is not None
    assert group.support_strategy_match.strategy_id == "strategy-1"
    assert group.support_strategy_match.exact_settlement_match is True
    assert report.api_history_boundary.retention_days == 90
    assert report.api_history_boundary.older_data_retrieval == (
        "support_package_already_supplied_provider_fill_fields_absent"
    )
    assert any("Keine weiteren Bitget-Dateien" in item for item in report.next_actions)
    assert any(
        item.kind == "bitget_strategy_fifo_gap_report" for item in run.evidence_files
    )
    assert any(
        item.kind == "bitget_strategy_fifo_gap_disposals"
        for item in run.evidence_files
    )

    with store.connect() as con:
        for table, count in before.items():
            assert con.execute(f"select count(*) from {table}").fetchone()[0] == count


def test_bitget_strategy_gap_api_and_csv_use_versioned_run(tmp_path, monkeypatch):
    store = _bitget_strategy_store(tmp_path)
    blockpit = tmp_path / "blockpit.csv"
    blockpit.write_text(
        "Date (UTC);Integration Name;Label;Outgoing Asset;Outgoing Amount;"
        "Incoming Asset;Incoming Amount;Fee Asset (optional);Fee Amount (optional);"
        "Comment (optional);Trx. ID (optional);Source Type;Source Name\n"
        "01.02.2024 00:00:00;Bitget;Deposit;;;HNT;6;;;Automatic deposit;"
        "settlement-1;API;Bitget\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        BitgetStrategyFifoGapService,
        "DEFAULT_BLOCKPIT_REFERENCE_PATH",
        blockpit,
    )
    artifact_root = tmp_path / "var/wallet_fifo_runs"
    run = WalletFifoParallelRunService(store, artifact_root=artifact_root).run(
        WalletFifoParallelRunRequest(
            years=[2024],
            as_of=datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
        )
    )
    client = TestClient(create_app(store))

    response = client.get(
        "/api/v1/tax/wallet-fifo/bitget-strategy-gaps",
        params={"run_id": run.run_id},
    )
    csv_response = client.get(
        "/api/v1/tax/wallet-fifo/bitget-strategy-gaps.csv",
        params={"run_id": run.run_id},
    )
    package_response = client.get(
        "/api/v1/tax/wallet-fifo/bitget-support-package.zip",
        params={"run_id": run.run_id},
    )

    assert response.status_code == 200
    assert response.json()["data"]["run_id"] == run.run_id
    assert response.json()["data"]["linked_unmatched_disposals_count"] == 1
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert "settlement_group_id,source_event_id,event_time" in csv_response.text
    assert "sale-1" in csv_response.text
    assert package_response.status_code == 200
    assert package_response.headers["content-type"] == "application/zip"
    with ZipFile(io.BytesIO(package_response.content)) as package:
        names = set(package.namelist())
        assert "bitget_support_manifest.json" in names
        assert "bitget_support/Strategy.csv" in names
        manifest = json.loads(package.read("bitget_support_manifest.json"))
        assert manifest["package_complete"] is True
        assert manifest["additional_user_export_required"] is False
    invalid_run = client.get(
        "/api/v1/tax/wallet-fifo/bitget-strategy-gaps",
        params={"run_id": "wallet-fifo-valid/../../outside"},
    )
    assert invalid_run.status_code == 404


def test_bitget_strategy_reconstruction_is_versioned_read_only_sensitivity(
    tmp_path,
    monkeypatch,
):
    store = _bitget_strategy_store(tmp_path)
    support_root = tmp_path / "bitget-support"
    monkeypatch.setattr(
        BitgetStrategyFifoGapService,
        "DEFAULT_SUPPORT_PACKAGE_ROOT",
        support_root,
    )
    for priced_at in (
        datetime(2024, 1, 1, tzinfo=timezone.utc),
        datetime(2024, 2, 1, tzinfo=timezone.utc),
        datetime(2024, 3, 1, tzinfo=timezone.utc),
    ):
        store.add_price_point(
            PricePointCreate(
                asset="USDT",
                price_eur=Decimal("0.9"),
                priced_at=priced_at,
                source="ecb:test-usd-eur",
                confidence=Decimal("1"),
            )
        )
    artifact_root = tmp_path / "var/wallet_fifo_runs"
    before = {}
    with store.connect() as con:
        for table in ("canonical_events", "tax_lots", "tax_lines", "price_ledger"):
            before[table] = con.execute(f"select count(*) from {table}").fetchone()[0]

    run = WalletFifoParallelRunService(
        store,
        artifact_root=artifact_root,
    ).run(
        WalletFifoParallelRunRequest(
            years=[2024],
            as_of=datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
        )
    )
    service = BitgetStrategyBasisReconstructionService(
        store,
        artifact_root=artifact_root,
    )
    report = service.report(run_id=run.run_id)

    assert report is not None
    assert report.status == "ready_for_professional_review"
    assert report.strict_ready is False
    assert report.productive_tax_effect == "none"
    assert report.groups_count == 1
    assert report.linked_disposals_count == 1
    assert report.price_evidence_complete_groups_count == 1
    assert report.definitely_within_one_year_disposals_count == 1
    assert report.documented_cost_basis_floor_total_eur == Decimal("0")
    assert report.documented_cost_basis_ceiling_total_eur is None
    group = report.groups[0]
    row = group.linked_disposals[0]
    assert group.strategy_id == "strategy-1"
    assert group.acquisition_window_start == datetime(
        2024, 1, 1, tzinfo=timezone.utc
    )
    assert group.acquisition_window_end == datetime(
        2024, 2, 1, tzinfo=timezone.utc
    )
    assert row.holding_period_certainty == "definitely_within_one_year"
    assert row.minimum_holding_days == Decimal("29")
    assert row.maximum_holding_days == Decimal("60")
    expected_proceeds = Decimal("60") * Decimal("5.999") / Decimal("10.999") * Decimal("0.9")
    expected_proxy_basis = Decimal("42") * Decimal("5.999") / Decimal("6") * Decimal("0.9")
    assert row.attributable_disposal_proceeds_eur == expected_proceeds
    assert row.zero_basis_gain_sensitivity_eur == expected_proceeds
    assert row.settlement_value_proxy_basis_eur == expected_proxy_basis
    assert row.settlement_value_proxy_gain_sensitivity_eur == (
        expected_proceeds - expected_proxy_basis
    )
    assert row.tax_basis_status == "provider_fill_basis_missing"
    assert group.tax_basis_use == "sensitivity_only_not_fifo_cost_basis"
    assert run.bitget_strategy_reconstruction_status == (
        "ready_for_professional_review"
    )
    assert any(
        item.kind == "bitget_strategy_basis_reconstruction"
        for item in run.evidence_files
    )
    assert any(
        item.kind == "bitget_strategy_basis_reconstruction_csv"
        for item in run.evidence_files
    )

    client = TestClient(create_app(store))
    response = client.get(
        "/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction",
        params={"run_id": run.run_id},
    )
    csv_response = client.get(
        "/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction.csv",
        params={"run_id": run.run_id},
    )
    html_response = client.get(
        "/api/v1/tax/wallet-fifo/bitget-strategy-review.html",
        params={"run_id": run.run_id},
    )
    package_response = client.get(
        "/api/v1/tax/wallet-fifo/bitget-strategy-review-package.zip",
        params={"run_id": run.run_id},
    )
    assert response.status_code == 200
    assert response.json()["data"]["productive_tax_effect"] == "none"
    assert csv_response.status_code == 200
    assert "zero_basis_gain_sensitivity_eur" in csv_response.text
    assert "provider_fill_basis_missing" in csv_response.text
    assert html_response.status_code == 200
    assert html_response.headers["content-type"].startswith("text/html")
    assert "Bitget Strategy-FIFO Fachakte" in html_response.text
    assert "Fachpruefung erforderlich" in html_response.text
    assert "Keine produktive Steuerwirkung" in html_response.text
    assert run.run_id in html_response.text
    assert package_response.status_code == 200
    assert package_response.headers["content-type"] == "application/zip"
    with ZipFile(io.BytesIO(package_response.content)) as package:
        names = set(package.namelist())
        assert names == {
            "Bitget_Strategy_FIFO_Fachakte.html",
            "evidence/bitget_support_package.zip",
            "machine/bitget_strategy_disposals.csv",
            "machine/bitget_strategy_gap_report.json",
            "machine/bitget_strategy_reconstruction.json",
            "manifest.json",
        }
        manifest = json.loads(package.read("manifest.json"))
        assert manifest["package_version"] == (
            "bitget_strategy_professional_review_v1"
        )
        assert manifest["run_id"] == run.run_id
        assert manifest["productive_tax_effect"] == "none"
        for item in manifest["files"]:
            content = package.read(item["path"])
            assert len(content) == item["size_bytes"]
            assert hashlib.sha256(content).hexdigest() == item["sha256"]
        with ZipFile(
            io.BytesIO(package.read("evidence/bitget_support_package.zip"))
        ) as support_package:
            assert "bitget_support_manifest.json" in support_package.namelist()

    with store.connect() as con:
        for table, count in before.items():
            assert con.execute(f"select count(*) from {table}").fetchone()[0] == count


def test_bitget_strategy_basis_decision_is_hash_bound_and_staging_only(tmp_path):
    store = _bitget_strategy_store(tmp_path)
    for priced_at in (
        datetime(2024, 1, 1, tzinfo=timezone.utc),
        datetime(2024, 2, 1, tzinfo=timezone.utc),
        datetime(2024, 3, 1, tzinfo=timezone.utc),
    ):
        store.add_price_point(
            PricePointCreate(
                asset="USDT",
                price_eur=Decimal("0.9"),
                priced_at=priced_at,
                source="ecb:test-usd-eur",
                confidence=Decimal("1"),
            )
        )
    artifact_root = tmp_path / "var/wallet_fifo_runs"
    run_request = WalletFifoParallelRunRequest(
        years=[2024],
        as_of=datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
    )
    run_service = WalletFifoParallelRunService(
        store,
        artifact_root=artifact_root,
    )
    run = run_service.run(run_request)
    reconstruction = BitgetStrategyBasisReconstructionService(
        store,
        artifact_root=artifact_root,
    ).report(run_id=run.run_id)
    assert reconstruction is not None

    with store.connect() as con:
        productive_before = {
            table: con.execute(f"select count(*) from {table}").fetchone()[0]
            for table in ("canonical_events", "tax_lots", "tax_lines", "price_ledger")
        }

    client = TestClient(create_app(store))
    readiness = client.get(
        "/api/v1/tax/wallet-fifo/bitget-strategy-basis-decision",
        params={"run_id": run.run_id},
    )
    payload = {
        "decision": "approve_settlement_value_proxy_estimate_for_staging",
        "rationale": (
            "Die vollstaendige Providerakte wurde geprueft; der Settlement-Proxy "
            "wird ausschliesslich als offengelegte Staging-Schaetzung verwendet."
        ),
        "actor": "unit-test",
        "acknowledge_provider_fill_data_missing": True,
        "acknowledge_estimate_not_observed_transaction": True,
        "acknowledge_consistent_application": True,
        "acknowledge_no_automatic_tax_effect": True,
        "acknowledge_professional_review_before_filing": True,
    }
    accepted = client.post(
        f"/api/v1/tax/wallet-fifo/bitget-strategy-basis-decision/{run.run_id}",
        json=payload,
    )
    repeated = client.post(
        f"/api/v1/tax/wallet-fifo/bitget-strategy-basis-decision/{run.run_id}",
        json=payload,
    )
    html_response = client.get(
        "/api/v1/tax/wallet-fifo/bitget-strategy-review.html",
        params={"run_id": run.run_id},
    )

    assert readiness.status_code == 200
    readiness_data = readiness.json()["data"]
    assert readiness_data["status"] == "ready_for_professional_decision"
    assert readiness_data["decision_ready"] is True
    assert readiness_data["decision_status"] == "pending"
    assert readiness_data["input_fingerprint_current"] is True
    assert accepted.status_code == 200
    accepted_data = accepted.json()["data"]
    assert accepted_data["created"] is True
    report = accepted_data["report"]
    assert report["status"] == "decision_recorded"
    assert report["decision_status"] == payload["decision"]
    assert report["selected_method"] == "settlement_value_proxy_estimate"
    assert report["selected_estimated_cost_basis_total_eur"] == str(
        reconstruction.settlement_value_proxy_basis_total_eur
    )
    assert report["selected_estimated_gain_loss_total_eur"] == str(
        reconstruction.settlement_value_proxy_gain_sensitivity_total_eur
    )
    assert report["estimate_selected_for_staging"] is True
    assert report["productive_tax_effect"] == "none"
    assert report["strict_ready"] is False
    assert repeated.status_code == 200
    assert repeated.json()["data"]["created"] is False
    assert repeated.json()["data"]["decision_id"] == accepted_data["decision_id"]
    assert html_response.status_code == 200
    assert "Settlement-Proxy nur fuer Staging ausgewaehlt" in html_response.text
    assert "Keine produktive Steuerwirkung" in html_response.text
    assert run_service.input_fingerprint(run.as_of).digest == (
        run.input_fingerprint.digest
    )
    reusable = run_service.find_reusable_run(run_request)
    assert reusable is not None
    assert reusable.run_id == run.run_id
    with store.connect() as con:
        for table, count in productive_before.items():
            assert con.execute(f"select count(*) from {table}").fetchone()[0] == count
        assert con.execute(
            """
            select count(*) from review_decisions
            where json_extract_string(payload_json, '$.decision_type') = ?
            """,
            ["bitget_strategy_basis_method_decision"],
        ).fetchone()[0] == 1
    stored_decision = next(
        item
        for item in store.list_review_decisions()
        if item.decision_type == "bitget_strategy_basis_method_decision"
    )
    assert stored_decision.payload["years"] == [2024]
    assert stored_decision.payload["fifo_effect"] == (
        "staging_only_no_productive_change"
    )
    assert stored_decision.payload["tax_line_effect"] == "none"


def test_bitget_strategy_reference_price_backfill_is_additive_and_tax_neutral(
    tmp_path,
    monkeypatch,
):
    store = _bitget_strategy_store(tmp_path)
    artifact_root = tmp_path / "var/wallet_fifo_runs"
    backfill_root = tmp_path / "var/bitget-backfill"
    run_service = WalletFifoParallelRunService(store, artifact_root=artifact_root)
    source_run = run_service.run(
        WalletFifoParallelRunRequest(
            years=[2024],
            as_of=datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
        )
    )
    service = BitgetStrategyBasisReconstructionService(
        store,
        artifact_root=artifact_root,
        backfill_artifact_root=backfill_root,
    )

    def fake_fetch_fx(_client, requested_date):
        return {
            "rate": Decimal("0.9"),
            "rate_date": requested_date,
            "request_url": f"https://example.test/fx/{requested_date.isoformat()}",
            "response_sha256": "a" * 64,
            "payload": [{"date": requested_date.isoformat(), "rate": 0.9}],
        }

    monkeypatch.setattr(service, "_fetch_fx", fake_fetch_fx)
    with store.connect() as con:
        tax_before = {
            table: con.execute(f"select count(*) from {table}").fetchone()[0]
            for table in ("tax_lots", "tax_lines")
        }
        prices_before = con.execute("select count(*) from price_ledger").fetchone()[0]

    dry_run = service.backfill_reference_prices(
        BitgetStrategyReferencePriceBackfillRequest(
            execute=False,
            run_id=source_run.run_id,
        )
    )
    assert dry_run.status == "planned"
    assert dry_run.requested_dates_count == 3
    assert dry_run.planned_count == 3
    assert dry_run.imported_count == 0
    assert dry_run.read_only is True
    with store.connect() as con:
        assert con.execute("select count(*) from price_ledger").fetchone()[0] == prices_before

    applied = service.backfill_reference_prices(
        BitgetStrategyReferencePriceBackfillRequest(
            execute=True,
            run_id=source_run.run_id,
        )
    )
    assert applied.status == "applied"
    assert applied.imported_count == 3
    assert applied.failed_count == 0
    assert applied.read_only is False
    assert applied.productive_tax_tables_unchanged is True
    assert applied.evidence_artifact_sha256
    assert service.latest_backfill() == applied
    with store.connect() as con:
        assert con.execute("select count(*) from price_ledger").fetchone()[0] == (
            prices_before + 3
        )
        for table, count in tax_before.items():
            assert con.execute(f"select count(*) from {table}").fetchone()[0] == count

    rebound_run = run_service.run(
        WalletFifoParallelRunRequest(
            years=[2024],
            as_of=datetime(2024, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
        )
    )
    rebound = service.report(run_id=rebound_run.run_id)
    assert rebound is not None
    assert rebound.status == "ready_for_professional_review"
    assert rebound.price_evidence_complete_groups_count == 1
