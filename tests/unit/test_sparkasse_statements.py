from datetime import date
from decimal import Decimal

from steuerreport_v2.domain.sparkasse_statements import (
    SparkasseCamtInvestmentEvidence,
    SparkasseStatementDocumentService,
)


def test_sparkasse_statement_extracts_balances_and_matches_camt_without_new_flow():
    text = """Kontoauszug 5 / 2025
1. November 2025
Konto-Nr. 100199266, DE12 3456 7890 1234 5678 90 Max Mustermann
Kontostand am 30.09.2025, Auszug Nr.    4            22.169,40
13.10.2025 Ueberw. Drittdienste
Bifinity UAB DATUM 12.10.2025, 08.18 UHR
-500,00
Kontostand am 31.10.2025 um 20:04 Uhr            21.355,58
"""
    camt_reference = "b" * 64

    document = SparkasseStatementDocumentService()._parse_text(
        text,
        page_texts=[text],
        document_sha256="a" * 64,
        size_bytes=1024,
        evidence_ref=f"sparkasse-statement:sha256:{'a' * 64}",
        camt_investments=[
            SparkasseCamtInvestmentEvidence(
                booking_date=date(2025, 10, 13),
                provider="binance",
                amount_eur=Decimal("500.00"),
                transaction_reference_sha256=camt_reference,
            )
        ],
    )

    assert document.extraction_status == "parsed"
    assert document.account_last4 == "9266"
    assert document.account_fingerprint_sha256 is not None
    assert document.opening_balance_eur == Decimal("22169.40")
    assert document.closing_balance_eur == Decimal("21355.58")
    assert document.period_from == date(2025, 10, 1)
    assert document.period_to == date(2025, 10, 31)
    assert document.crypto_debits_count == 1
    assert document.crypto_debits_eur == Decimal("500.00")
    debit = document.crypto_debits[0]
    assert debit.provider == "binance"
    assert debit.camt_match_status == "exact"
    assert debit.camt_transaction_reference_sha256 == camt_reference
    assert debit.calculation_effect == "corroboration_only_no_duplicate_flow"


def test_sparkasse_statement_connector_csv_contains_only_masked_account_identity(
    tmp_path,
):
    report = SparkasseStatementDocumentService().scan(
        tmp_path / "missing",
        camt_investments=[],
    )

    content = SparkasseStatementDocumentService().csv(report)

    assert report.status == "missing"
    assert report.crypto_debits_eur == Decimal("0")
    assert content.startswith("document_sha256,account_last4,ownership_scope")
    assert "Konto-Nr." not in content
