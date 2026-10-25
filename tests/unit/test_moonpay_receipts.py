from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal
import json

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.moonpay_receipts import MoonpayReceiptService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService
from steuerreport_v2.domain.tax_years import TaxYearService


def _fixture(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = "GmHYjZGkcHBZ3WyGZ9eUGDZMfHvJTLtTKXu6dnSc63yu"
    sender = MoonpayReceiptService.MOONPAY_SOLANA_SENDER
    sol_tx = "s" * 88
    usdc_tx = "u" * 88
    sol_event, usdc_event = store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2026, 1, 1, 12, 0, 10, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("2.5"),
                tx_id=sol_tx,
                account=wallet,
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2026, 2, 1, 12, 0, 9, tzinfo=timezone.utc),
                event_type="income",
                asset="USDC",
                quantity=Decimal("250"),
                tx_id=usdc_tx,
                account=wallet,
            ),
        ]
    )
    trade_path = tmp_path / "MoonPay_trade-history.csv"
    with trade_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "id", "operation", "baseCurrency", "baseCurrencyAmount",
                "createdAt", "quoteCurrency", "quoteCurrencyAmount", "feeAmount",
                "extraFeeAmount", "networkFeeAmount", "status",
            ]
        )
        writer.writerow(
            ["trade-sol", "buy", "eur", "210.50", "2026-01-01T12:00:00Z", "sol", "2.5", "5", "0", "0.5", "completed"]
        )
        writer.writerow(
            ["trade-usdc", "buy", "eur", "225.25", "2026-02-01T12:00:00Z", "usdc_sol", "250", "4", "0", "0.25", "completed"]
        )
    audit_path = tmp_path / "alchemy.json"
    audit_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "tx_id": sol_tx,
                        "assets": "SOL",
                        "accounts": [wallet],
                        "signers": [sender],
                        "onchain_confirmed": True,
                    },
                    {
                        "tx_id": usdc_tx,
                        "assets": "USDC",
                        "accounts": [wallet],
                        "signers": [sender],
                        "onchain_confirmed": True,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    provenance_dir = tmp_path / "provenance"
    provenance_dir.mkdir()
    manifest_path = tmp_path / "manifest.json"
    monkeypatch.setattr(MoonpayReceiptService, "DEFAULT_TRADE_HISTORY_PATH", trade_path)
    monkeypatch.setattr(MoonpayReceiptService, "DEFAULT_ALCHEMY_AUDIT_PATH", audit_path)
    monkeypatch.setattr(MoonpayReceiptService, "DEFAULT_PROVENANCE_DIR", provenance_dir)
    monkeypatch.setattr(MoonpayReceiptService, "DEFAULT_MANIFEST_PATH", manifest_path)
    return store, trade_path, sol_event, usdc_event


def test_moonpay_trade_history_binds_sol_and_usdc_with_exact_eur_basis(
    tmp_path, monkeypatch
):
    store, trade_path, sol_event, usdc_event = _fixture(tmp_path, monkeypatch)

    report = MoonpayReceiptService(store).report()

    assert report.status == "ready"
    assert report.strict_ready is True
    assert report.trade_history_rows_count == 2
    assert report.matched_trade_rows_count == 2
    assert report.unmatched_trade_rows_count == 0
    assert report.total_base_payment_amount_eur == Decimal("435.75")
    assert report.total_receipt_cost_basis_eur == Decimal("445.50")
    assert report.total_fee_components_eur == Decimal("9.75")
    by_event = {item.event_id: item for item in report.items}
    assert by_event[sol_event.event_id].cost_basis_eur == Decimal("216.00")
    assert by_event[usdc_event.event_id].cost_basis_eur == Decimal("229.50")
    assert all(item.strict_ready for item in report.items)
    assert all(all(item.decision_layer.model_dump().values()) for item in report.items)
    assert report.trade_history_sha256 is not None
    assert report.trade_history_size_bytes == trade_path.stat().st_size


def test_moonpay_exact_basis_is_used_by_global_and_wallet_fifo(tmp_path, monkeypatch):
    store, _trade_path, sol_event, usdc_event = _fixture(tmp_path, monkeypatch)

    TaxService(store).rebuild_fifo()
    lots = {lot.source_event_id: lot for lot in TaxService(store).list_tax_lots()}

    assert lots[sol_event.event_id].cost_basis_eur_total == Decimal("216.00")
    assert lots[usdc_event.event_id].cost_basis_eur_total == Decimal("229.50")
    income = TaxYearService(store).income_report(2026)
    external = TaxYearService(store).external_inflow_report(2026)
    assert all(item.asset != "USDC" for item in income.assets)
    assert external.inflows_count == 0
    preview = WalletFifoPreviewService(store).preview(year=2026)
    traces = [
        trace
        for trace in preview.transfer_traces
        if trace.status == "resolved_by_moonpay_trade_history_exact_cost_basis"
    ]
    assert len(traces) == 2
    assert sum((trace.carried_cost_basis_eur for trace in traces), Decimal("0")) == Decimal("445.50")
    assert preview.unmatched_count == 0


def test_moonpay_api_reports_and_downloads_original_csv(tmp_path, monkeypatch):
    store, trade_path, _sol_event, _usdc_event = _fixture(tmp_path, monkeypatch)
    client = TestClient(create_app(store))

    response = client.get("/api/v1/tax/moonpay-receipts")
    download = client.get("/api/v1/tax/moonpay-receipts/trade-history.csv")

    assert response.status_code == 200
    assert response.json()["data"]["strict_ready"] is True
    assert download.status_code == 200
    assert download.content == trade_path.read_bytes()
    assert download.headers["x-content-sha256"] == response.json()["data"]["trade_history_sha256"]


def test_moonpay_sparkasse_camt_matches_gross_debits_without_other_bank_rows(
    tmp_path,
    monkeypatch,
):
    store, _trade_path, _sol_event, _usdc_event = _fixture(tmp_path, monkeypatch)
    camt_dir = tmp_path / "sparkasse-camt"
    camt_dir.mkdir()
    entries = [
        ("216.00", "2026-01-02", "bank-ref-sol", "2026-01-01T12:00", "MOONPAY"),
        ("229.50", "2026-02-02", "bank-ref-usdc", "2026-02-01T12:00", "MoonPay"),
        ("99.00", "2026-02-02", "private-unrelated", "2026-02-01T13:00", "OTHER SHOP"),
    ]
    body = "".join(
        (
            "<Ntry>"
            f"<Amt Ccy=\"EUR\">{amount}</Amt>"
            "<CdtDbtInd>DBIT</CdtDbtInd>"
            f"<BookgDt><Dt>{booking_date}</Dt></BookgDt>"
            f"<AcctSvcrRef>{reference}</AcctSvcrRef>"
            "<NtryDtls><TxDtls><RltdPties><Cdtr><Pty>"
            f"<Nm>{merchant}</Nm>"
            "</Pty></Cdtr></RltdPties><RmtInf>"
            f"<Ustrd>{merchant_time} APPLE PAY</Ustrd>"
            "</RmtInf></TxDtls></NtryDtls>"
            "</Ntry>"
        )
        for amount, booking_date, reference, merchant_time, merchant in entries
    )
    (camt_dir / "2026.02.02.xml").write_text(
        (
            '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.052.001.08">'
            f"<BkToCstmrAcctRpt><Rpt>{body}</Rpt></BkToCstmrAcctRpt>"
            "</Document>"
        ),
        encoding="utf-8",
    )

    report = MoonpayReceiptService(store, bank_camt_dir=camt_dir).report()

    assert report.strict_ready is True
    assert report.bank_camt_exists is True
    assert report.bank_camt_files_count == 1
    assert report.bank_debits_count == 2
    assert report.bank_debits_matched_count == 2
    assert report.bank_debits_unmatched_count == 0
    assert report.total_base_payment_amount_eur == Decimal("435.75")
    assert report.total_bank_debits_eur == Decimal("445.50")
    assert report.bank_camt_semantic_sha256
    assert all(item.decision_layer.bank_debit_bound for item in report.items)
    assert all(item.decision_layer.gross_payment_reconciled for item in report.items)
    assert all(item.bank_reference for item in report.items)
def test_candidate_events_without_configured_receivers(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "unconfigured.duckdb")
    monkeypatch.setattr(MoonpayReceiptService, "KNOWN_RECEIVER_WALLETS", frozenset())
    assert MoonpayReceiptService(store)._candidate_events() == ([], [])


def test_candidate_events_with_a_single_configured_receiver(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "single-receiver.duckdb")
    monkeypatch.setattr(MoonpayReceiptService, "KNOWN_RECEIVER_WALLETS", frozenset({"fixture-receiver"}))
    assert MoonpayReceiptService(store)._candidate_events() == ([], [])


