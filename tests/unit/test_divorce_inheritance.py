from datetime import datetime, timezone
from decimal import Decimal
import hashlib
from zipfile import ZipFile

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.contracts.review import ReviewDecisionCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.divorce_inheritance import (
    DivorceInheritanceOriginService,
)
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


def _entry(reference, booking_date, amount, direction, text):
    return f"""
    <Ntry>
      <NtryRef>{reference}</NtryRef>
      <Amt Ccy="EUR">{amount}</Amt>
      <CdtDbtInd>{direction}</CdtDbtInd>
      <BookgDt><Dt>{booking_date}</Dt></BookgDt>
      <NtryDtls><TxDtls><Refs><AcctSvcrRef>{reference}</AcctSvcrRef></Refs>
      <RmtInf><Ustrd>{text}</Ustrd></RmtInf></TxDtls></NtryDtls>
    </Ntry>
    """


def _balance(balance_type, balance_date, amount):
    return f"""
    <Bal>
      <Tp><CdOrPrtry><Cd>{balance_type}</Cd></CdOrPrtry></Tp>
      <Amt Ccy="EUR">{amount}</Amt><CdtDbtInd>CRDT</CdtDbtInd>
      <Dt><Dt>{balance_date}</Dt></Dt>
    </Bal>
    """


def _write_camt(path):
    content = """<?xml version="1.0" encoding="UTF-8"?>
    <Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.052.001.08">
      <BkToCstmrAcctRpt><Rpt>
    """
    content += _balance("OPBD", "2025-08-22", "2001.81")
    content += _entry("inheritance", "2025-09-03", "18743.53", "CRDT", "Nachlass")
    content += _entry("tr-1", "2025-09-04", "100.00", "DBIT", "Trade Republic")
    content += _entry("binance-1", "2025-09-05", "200.00", "DBIT", "Bifinity Binance")
    content += _entry("coinbase-1", "2025-09-06", "50.00", "DBIT", "Coinbase")
    content += _entry("moonpay-1", "2025-09-07", "300.00", "DBIT", "MoonPay")
    content += _balance("CLBD", "2026-07-24", "1940.01")
    content += "</Rpt></BkToCstmrAcctRpt></Document>"
    path.write_text(content, encoding="utf-8")


def test_coinbase_connector_without_history_skips_portfolio_replay(
    tmp_path,
    monkeypatch,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(
        PortfolioService,
        "as_of_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("portfolio replay must not run without Coinbase history")
        ),
    )

    connector = DivorceInheritanceOriginService(store).coinbase_connector()

    assert connector.history_status == "missing"
    assert connector.history_events_count == 0
    assert connector.assets == []


def _add_origin_decision(store, flow_id):
    store.add_review_decision(
        ReviewDecisionCreate(
            decision_type="divorce_capital_origin",
            scope=f"divorce:capital-origin:{flow_id}",
            title="Investition aus Erbgeld",
            rationale="Nutzerangabe mit referenzierter Bankspur.",
            evidence_ref="/api/v1/divorce/inheritance-origin",
            actor="user",
            source="unit-test",
            affected_ids=[flow_id],
            payload={"flow_id": flow_id, "capital_origin": "inheritance"},
        )
    )


def _trade_republic_snapshot_csv(total="3357,92", cash="157,92", securities="3200,00"):
    return (
        "valuation_date;cash_eur;securities_value_eur;total_value_eur\n"
        f"2026-07-24;{cash};{securities};{total}\n"
    ).encode("utf-8")


def _inheritance_evidence_pdf():
    return b"%PDF-1.4\nformal-inheritance-evidence\n%%EOF\n"


def _early_camt_bytes():
    content = """<?xml version="1.0" encoding="UTF-8"?>
    <Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.052.001.08">
      <BkToCstmrAcctRpt><Rpt>
    """
    content += _balance("OPBD", "2025-06-13", "2500.00")
    content += _balance("CLBD", "2025-08-21", "2100.00")
    content += "</Rpt></BkToCstmrAcctRpt></Document>"
    return content.encode("utf-8")


def test_inheritance_report_matches_bank_and_platform_without_double_counting(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                source_ref="matched-200",
                event_time=datetime(2025, 9, 5, 10, tzinfo=timezone.utc),
                event_type="transfer",
                asset="EUR",
                quantity=Decimal("200"),
                account="binance",
            ),
            CanonicalEventCreate(
                source="binance",
                source_ref="platform-only-500",
                event_time=datetime(2026, 2, 2, 10, tzinfo=timezone.utc),
                event_type="transfer",
                asset="EUR",
                quantity=Decimal("500"),
                account="binance",
            ),
        ]
    )
    camt_dir = tmp_path / "camt"
    camt_dir.mkdir()
    _write_camt(camt_dir / "statement.xml")
    trade_republic_dir = tmp_path / "TradeRepublic"
    trade_republic_dir.mkdir()
    (trade_republic_dir / "Depotauszug-20260724.pdf").write_bytes(b"test-pdf")
    inheritance_document = tmp_path / "inheritance.pdf"
    inheritance_document.write_bytes(b"formal-inheritance-evidence")

    service = DivorceInheritanceOriginService(
        store,
        bank_camt_dir=camt_dir,
        trade_republic_document_root=trade_republic_dir,
        inheritance_document_path=inheritance_document,
    )
    report = service.report()

    assert report.bank_statement_status == "partial"
    assert report.opening_balance_eur == Decimal("2001.81")
    assert report.end_asset_closing_balance_eur == Decimal("1940.01")
    assert report.inheritance_credit_eur == Decimal("18743.53")
    assert report.formal_inheritance_document_status == "documented"
    assert report.bank_identified_investment_eur == Decimal("650.00")
    assert report.platform_only_investment_eur == Decimal("500")
    assert report.total_identified_investment_eur == Decimal("1150.00")
    assert report.declared_inheritance_headroom_eur == Decimal("17593.53")
    assert report.crypto_tracked_investment_eur == Decimal("1000.00")
    assert report.external_asset_investment_eur == Decimal("150.00")
    assert report.external_asset_end_value_eur is None
    assert report.trade_republic_connector.direct_retail_api_available is False
    assert (
        report.trade_republic_connector.end_asset_statement_status
        == "candidate_present"
    )
    assert report.strict_ready is False
    assert all(
        len(item.transaction_reference_sha256) == 64 for item in report.investment_flows
    )
    assert "Trade Republic" not in str(report.inheritance_credit.model_dump())

    csv_text = service.csv()
    assert csv_text.startswith("provider,booking_date,amount_eur")
    assert "trade_republic,2025-09-04,100.00" in csv_text
    assert "Bifinity" not in csv_text


def test_inheritance_decisions_document_origin_but_not_missing_external_values(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    camt_dir = tmp_path / "camt"
    camt_dir.mkdir()
    _write_camt(camt_dir / "statement.xml")
    for flow_id in (
        "binance_fiat_deposits",
        "moonpay_apple_pay_onramp",
        "coinbase_bank_transfers",
        "trade_republic_bank_transfers",
    ):
        _add_origin_decision(store, flow_id)

    report = DivorceInheritanceOriginService(store, bank_camt_dir=camt_dir).report()

    assert report.user_declaration_status == "recorded"
    assert all(
        item.capital_origin == "inheritance"
        for item in report.provider_summaries
        if item.identified_investment_eur > 0
    )
    assert report.strict_ready is False
    assert any("Endvermoegenswert" in item for item in report.findings)


def test_inheritance_origin_api_has_json_and_csv(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    camt_dir = tmp_path / "camt"
    camt_dir.mkdir()
    _write_camt(camt_dir / "statement.xml")
    monkeypatch.setenv("STEUERREPORT_SPARKASSE_CAMT_DIR", str(camt_dir))
    client = TestClient(create_app(store))

    response = client.get("/api/v1/divorce/inheritance-origin")
    csv_response = client.get("/api/v1/divorce/inheritance-origin.csv")
    statement_response = client.get("/api/v1/divorce/sparkasse-statements")
    statement_csv_response = client.get(
        "/api/v1/divorce/sparkasse-statements.csv"
    )

    assert response.status_code == 200
    assert response.json()["data"]["inheritance_credit_eur"] == "18743.53"
    assert response.json()["data"]["sparkasse_statement_connector"]["status"] == (
        "missing"
    )
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")
    assert statement_response.status_code == 200
    assert statement_response.json()["data"]["status"] == "missing"
    assert statement_csv_response.status_code == 200
    assert statement_csv_response.headers["content-type"].startswith("text/csv")


def test_multiple_inheritance_credits_are_hash_bound_and_aggregated(
    tmp_path, monkeypatch
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    camt_dir = tmp_path / "camt"
    camt_dir.mkdir()
    content = """<?xml version="1.0" encoding="UTF-8"?>
    <Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.052.001.08">
      <BkToCstmrAcctRpt><Rpt>
    """
    content += _balance("OPBD", "2025-06-13", "2001.81")
    content += _entry("inheritance", "2025-09-03", "18743.53", "CRDT", "Nachlass")
    content += _entry("salary", "2026-06-26", "3200.00", "CRDT", "Gehalt")
    content += _entry(
        "estate-asset", "2026-07-03", "1051.01", "CRDT", "Mitgliedsanteil"
    )
    content += _balance("CLBD", "2026-07-24", "1940.01")
    content += "</Rpt></BkToCstmrAcctRpt></Document>"
    (camt_dir / "statement.xml").write_text(content, encoding="utf-8")
    document_root = tmp_path / "Inheritance"
    monkeypatch.setenv("STEUERREPORT_SPARKASSE_CAMT_DIR", str(camt_dir))
    monkeypatch.setenv("STEUERREPORT_INHERITANCE_DOCUMENT_ROOT", str(document_root))
    client = TestClient(create_app(store))

    supporting_pdf = b"%PDF-1.4\nestate-asset-support\n%%EOF\n"
    refund_pdf = b"%PDF-1.4\nestate-refund-net-amount\n%%EOF\n"
    supporting_upload = client.post(
        "/api/v1/divorce/inheritance-documents",
        files={"file": ("support.pdf", supporting_pdf, "application/pdf")},
    ).json()["data"]
    refund_upload = client.post(
        "/api/v1/divorce/inheritance-documents",
        files={"file": ("refund.pdf", refund_pdf, "application/pdf")},
    ).json()["data"]
    candidates = client.get("/api/v1/divorce/inheritance-credit-candidates").json()[
        "data"
    ]
    estate_candidate = next(
        item for item in candidates["candidates"] if item["amount_eur"] == "1051.01"
    )
    salary_candidate = next(
        item for item in candidates["candidates"] if item["amount_eur"] == "3200.00"
    )

    bank_decision_payload = {
        "transaction_reference_sha256": estate_candidate[
            "transaction_reference_sha256"
        ],
        "credit_kind": "estate_asset_realization",
        "supporting_evidence_ref": (
            f"inheritance-document:sha256:{supporting_upload['document_sha256']}"
        ),
    }
    bank_decision = client.post(
        "/api/v1/divorce/inheritance-credit-decisions",
        json=bank_decision_payload,
    )
    repeated_bank_decision = client.post(
        "/api/v1/divorce/inheritance-credit-decisions",
        json=bank_decision_payload,
    )
    document_decision_payload = {
        "document_sha256": refund_upload["document_sha256"],
        "document_date": "2025-05-14",
        "amount_eur": "1095.09",
        "credit_kind": "estate_refund",
    }
    document_decision = client.post(
        "/api/v1/divorce/inheritance-document-credit-decisions",
        json=document_decision_payload,
    )
    repeated_document_decision = client.post(
        "/api/v1/divorce/inheritance-document-credit-decisions",
        json=document_decision_payload,
    )
    report = client.get("/api/v1/divorce/inheritance-origin").json()["data"]
    evidence_csv = client.get("/api/v1/divorce/inheritance-credits.csv")

    assert salary_candidate["review_status"] == "unclassified"
    assert bank_decision.json()["status"] == "ok"
    assert repeated_bank_decision.json()["status"] == "warning"
    assert document_decision.json()["status"] == "ok"
    assert repeated_document_decision.json()["status"] == "warning"
    assert report["inheritance_credit_count"] == 3
    assert report["inheritance_credit_eur"] == "20889.63"
    assert report["inheritance_credit"]["amount_eur"] == "18743.53"
    assert [item["amount_eur"] for item in report["inheritance_credits"]] == [
        "1095.09",
        "18743.53",
        "1051.01",
    ]
    assert "3200.00" not in [
        item["amount_eur"] for item in report["inheritance_credits"]
    ]
    assert evidence_csv.status_code == 200
    assert "1095.09" in evidence_csv.text
    assert "1051.01" in evidence_csv.text
    assert "support.pdf" not in evidence_csv.text


def test_trade_republic_exact_csv_is_review_candidate_not_automatic_valuation(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    trade_republic_dir = tmp_path / "TradeRepublic"
    trade_republic_dir.mkdir()
    content = _trade_republic_snapshot_csv()
    (trade_republic_dir / "depot-export.csv").write_bytes(content)

    service = DivorceInheritanceOriginService(
        store,
        bank_camt_dir=None,
        trade_republic_document_root=trade_republic_dir,
    )
    connector = service.trade_republic_documents()

    assert connector.document_parse_status == "parsed"
    assert connector.end_asset_statement_status == "exact_date_candidate"
    assert connector.valuation_review_status == "ready"
    assert connector.valuation_review_ready is True
    assert connector.exact_date_documents_count == 1
    assert connector.candidate_end_asset_value_eur == Decimal("3357.92")
    assert connector.candidate_cash_value_eur == Decimal("157.92")
    assert connector.candidate_securities_value_eur == Decimal("3200.00")
    assert connector.accepted_end_asset_value_eur is None
    assert connector.candidate_document_sha256 == hashlib.sha256(content).hexdigest()
    assert all(
        "depot-export.csv" not in str(item.model_dump()) for item in connector.documents
    )

    csv_text = service.trade_republic_documents_csv()
    assert "3357.92" in csv_text
    assert "depot-export.csv" not in csv_text


def test_trade_republic_zip_member_is_parsed_without_exposing_member_name(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    trade_republic_dir = tmp_path / "TradeRepublic"
    trade_republic_dir.mkdir()
    archive_path = trade_republic_dir / "documents.zip"
    with ZipFile(archive_path, mode="w") as archive:
        archive.writestr(
            "private/name-and-account-20260724.csv", _trade_republic_snapshot_csv()
        )

    connector = DivorceInheritanceOriginService(
        store,
        bank_camt_dir=None,
        trade_republic_document_root=trade_republic_dir,
    ).trade_republic_documents()

    assert connector.document_files_count == 1
    assert connector.parsed_documents_count == 1
    assert connector.documents[0].source_kind == "zip_member"
    assert (
        connector.documents[0].container_sha256
        == hashlib.sha256(archive_path.read_bytes()).hexdigest()
    )
    assert "name-and-account" not in connector.model_dump_json()


def test_trade_republic_filename_only_candidate_cannot_be_accepted(
    tmp_path, monkeypatch
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    trade_republic_dir = tmp_path / "TradeRepublic"
    trade_republic_dir.mkdir()
    (trade_republic_dir / "Depotauszug-20260724.pdf").write_bytes(b"not-a-pdf")
    monkeypatch.setenv(
        "STEUERREPORT_TRADE_REPUBLIC_DOCUMENT_ROOT", str(trade_republic_dir)
    )
    client = TestClient(create_app(store))
    document_sha256 = hashlib.sha256(b"not-a-pdf").hexdigest()

    response = client.post(
        "/api/v1/divorce/trade-republic/valuation-decisions",
        json={
            "end_asset_date": "2026-07-24",
            "document_sha256": document_sha256,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert store.list_review_decisions() == []


def test_trade_republic_exact_valuation_decision_is_idempotent_and_updates_report(
    tmp_path,
    monkeypatch,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    camt_dir = tmp_path / "camt"
    camt_dir.mkdir()
    _write_camt(camt_dir / "statement.xml")
    trade_republic_dir = tmp_path / "TradeRepublic"
    trade_republic_dir.mkdir()
    content = _trade_republic_snapshot_csv()
    (trade_republic_dir / "snapshot.csv").write_bytes(content)
    monkeypatch.setenv("STEUERREPORT_SPARKASSE_CAMT_DIR", str(camt_dir))
    monkeypatch.setenv(
        "STEUERREPORT_TRADE_REPUBLIC_DOCUMENT_ROOT", str(trade_republic_dir)
    )
    client = TestClient(create_app(store))
    document_sha256 = hashlib.sha256(content).hexdigest()
    payload = {
        "end_asset_date": "2026-07-24",
        "document_sha256": document_sha256,
    }

    preview = client.get("/api/v1/divorce/trade-republic/documents")
    accepted = client.post(
        "/api/v1/divorce/trade-republic/valuation-decisions", json=payload
    )
    repeated = client.post(
        "/api/v1/divorce/trade-republic/valuation-decisions", json=payload
    )
    csv_response = client.get("/api/v1/divorce/trade-republic/documents.csv")

    assert preview.status_code == 200
    assert preview.json()["data"]["valuation_review_ready"] is True
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "ok"
    assert accepted.json()["data"]["value_eur"] == "3357.92"
    assert (
        accepted.json()["data"]["origin_report"]["trade_republic_connector"][
            "end_asset_statement_status"
        ]
        == "reviewed"
    )
    trade_republic = next(
        item
        for item in accepted.json()["data"]["origin_report"]["provider_summaries"]
        if item["provider"] == "trade_republic"
    )
    assert trade_republic["end_asset_valuation_status"] == "covered"
    assert trade_republic["end_asset_value_eur"] == "3357.92"
    assert repeated.json()["status"] == "warning"
    assert repeated.json()["data"]["already_recorded"] is True
    assert (
        len(
            [
                item
                for item in store.list_review_decisions()
                if item.decision_type == "divorce_external_asset_valuation"
            ]
        )
        == 1
    )
    assert csv_response.status_code == 200
    assert csv_response.headers["content-type"].startswith("text/csv")


def test_trade_republic_document_upload_is_hash_deduplicated(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    trade_republic_dir = tmp_path / "TradeRepublic"
    monkeypatch.setenv(
        "STEUERREPORT_TRADE_REPUBLIC_DOCUMENT_ROOT", str(trade_republic_dir)
    )
    client = TestClient(create_app(store))
    content = _trade_republic_snapshot_csv()

    uploaded = client.post(
        "/api/v1/divorce/trade-republic/documents",
        data={"end_asset_date": "2026-07-24"},
        files={"file": ("private-depot-name.csv", content, "text/csv")},
    )
    repeated = client.post(
        "/api/v1/divorce/trade-republic/documents",
        data={"end_asset_date": "2026-07-24"},
        files={"file": ("renamed.csv", content, "text/csv")},
    )

    assert uploaded.status_code == 200
    assert uploaded.json()["status"] == "ok"
    assert uploaded.json()["data"]["connector"]["valuation_review_ready"] is True
    assert repeated.json()["status"] == "warning"
    assert repeated.json()["data"]["already_present"] is True
    stored = list(trade_republic_dir.glob("*"))
    assert len(stored) == 1
    assert stored[0].name.startswith("document-")
    assert "private-depot-name" not in stored[0].name


def test_inheritance_document_upload_is_candidate_until_explicit_review(
    tmp_path,
    monkeypatch,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    document_root = tmp_path / "Inheritance"
    monkeypatch.setenv("STEUERREPORT_INHERITANCE_DOCUMENT_ROOT", str(document_root))
    client = TestClient(create_app(store))
    content = _inheritance_evidence_pdf()
    document_sha256 = hashlib.sha256(content).hexdigest()

    uploaded = client.post(
        "/api/v1/divorce/inheritance-documents",
        files={"file": ("private-erbschein-name.pdf", content, "application/pdf")},
    )
    preview = client.get("/api/v1/divorce/inheritance-origin")
    accepted = client.post(
        "/api/v1/divorce/inheritance-documents/review-decisions",
        json={"document_sha256": document_sha256},
    )
    repeated = client.post(
        "/api/v1/divorce/inheritance-documents/review-decisions",
        json={"document_sha256": document_sha256},
    )
    csv_response = client.get("/api/v1/divorce/inheritance-documents.csv")

    assert uploaded.status_code == 200
    assert uploaded.json()["status"] == "ok"
    assert uploaded.json()["data"]["connector"]["status"] == "candidate_present"
    assert preview.json()["data"]["formal_inheritance_document_status"] == "missing"
    assert accepted.json()["status"] == "ok"
    assert (
        accepted.json()["data"]["origin_report"]["formal_inheritance_document_status"]
        == "documented"
    )
    assert (
        accepted.json()["data"]["origin_report"]["formal_inheritance_connector"][
            "accepted_document_sha256"
        ]
        == document_sha256
    )
    assert repeated.json()["status"] == "warning"
    assert repeated.json()["data"]["already_recorded"] is True
    assert csv_response.status_code == 200
    assert document_sha256 in csv_response.text
    assert "private-erbschein-name" not in csv_response.text
    assert (
        len(
            [
                item
                for item in store.list_review_decisions()
                if item.decision_type == "divorce_formal_inheritance_evidence"
            ]
        )
        == 1
    )
    stored = list(document_root.glob("*"))
    assert len(stored) == 1
    assert stored[0].name.startswith("document-")
    assert "private-erbschein-name" not in stored[0].name


def test_inheritance_document_upload_rejects_extension_signature_mismatch(
    tmp_path,
    monkeypatch,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    document_root = tmp_path / "Inheritance"
    monkeypatch.setenv("STEUERREPORT_INHERITANCE_DOCUMENT_ROOT", str(document_root))
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/divorce/inheritance-documents",
        files={"file": ("inheritance.pdf", b"not-a-pdf", "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert response.json()["errors"][0]["code"] == "inheritance_document_rejected"
    assert not document_root.exists()
    assert store.list_review_decisions() == []


def test_sparkasse_camt_zip_upload_closes_statement_gap_and_is_hash_deduplicated(
    tmp_path,
    monkeypatch,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    camt_dir = tmp_path / "Sparkasse"
    camt_dir.mkdir()
    _write_camt(camt_dir / "statement.xml")
    archive_path = tmp_path / "sparkasse-private-export.zip"
    with ZipFile(archive_path, mode="w") as archive:
        archive.writestr("private/100199266-20250613.xml", _early_camt_bytes())
    monkeypatch.setenv("STEUERREPORT_SPARKASSE_CAMT_DIR", str(camt_dir))
    client = TestClient(create_app(store))
    archive_content = archive_path.read_bytes()

    uploaded = client.post(
        "/api/v1/divorce/sparkasse-camt",
        data={"separation_date": "2025-06-13", "end_asset_date": "2026-07-24"},
        files={
            "file": ("sparkasse-private-export.zip", archive_content, "application/zip")
        },
    )
    repeated = client.post(
        "/api/v1/divorce/sparkasse-camt",
        data={"separation_date": "2025-06-13", "end_asset_date": "2026-07-24"},
        files={"file": ("renamed.zip", archive_content, "application/zip")},
    )

    assert uploaded.status_code == 200
    assert uploaded.json()["status"] == "ok"
    assert uploaded.json()["data"]["uploaded_files"] == 1
    report = uploaded.json()["data"]["origin_report"]
    assert report["bank_statement_status"] == "complete"
    assert report["bank_statement_from"] == "2025-06-13"
    assert report["bank_statement_to"] == "2026-07-24"
    assert report["bank_files_count"] == 2
    assert "100199266" not in uploaded.text
    assert "sparkasse-private-export" not in uploaded.text
    assert repeated.json()["status"] == "warning"
    assert repeated.json()["data"]["already_present_files"] == 1
    stored = [path for path in camt_dir.glob("*.xml") if path.name != "statement.xml"]
    assert len(stored) == 1
    assert stored[0].name.startswith("camt-")


def test_sparkasse_camt_upload_rejects_non_camt_xml(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    camt_dir = tmp_path / "Sparkasse"
    monkeypatch.setenv("STEUERREPORT_SPARKASSE_CAMT_DIR", str(camt_dir))
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/divorce/sparkasse-camt",
        files={
            "file": ("account.xml", b"<root><value>1</value></root>", "application/xml")
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert response.json()["errors"][0]["code"] == "sparkasse_camt_rejected"
    assert not camt_dir.exists()


def test_coinbase_history_valuation_is_computed_reviewed_and_invalidated_by_new_import(
    tmp_path,
    monkeypatch,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    camt_dir = tmp_path / "camt"
    camt_dir.mkdir()
    _write_camt(camt_dir / "statement.xml")
    monkeypatch.setenv("STEUERREPORT_SPARKASSE_CAMT_DIR", str(camt_dir))
    content = (
        "Timestamp,Transaction Type,Asset,Quantity Transacted,Spot Price Currency,Subtotal,Fees and/or Spread,Transaction ID\n"
        "2025-09-06T09:00:00Z,Deposit,EUR,21,EUR,,,deposit-1\n"
        "2025-09-06T10:00:00Z,Buy,SOL,1,EUR,20.00,1.00,buy-1\n"
    )
    batch = CsvRawImporter(store).import_text(
        source="coinbase",
        filename="coinbase-history.csv",
        content=content,
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("100"),
            priced_at=datetime(2026, 7, 24, 12, tzinfo=timezone.utc),
            source="unit-test-stichtag",
        )
    )
    client = TestClient(create_app(store))

    preview = client.get("/api/v1/divorce/coinbase/connector?end_asset_date=2026-07-24")
    connector = preview.json()["data"]
    accepted = client.post(
        "/api/v1/divorce/coinbase/valuation-decisions",
        json={
            "end_asset_date": "2026-07-24",
            "history_manifest_sha256": connector["history_manifest_sha256"],
        },
    )
    repeated = client.post(
        "/api/v1/divorce/coinbase/valuation-decisions",
        json={
            "end_asset_date": "2026-07-24",
            "history_manifest_sha256": connector["history_manifest_sha256"],
        },
    )
    csv_response = client.get(
        "/api/v1/divorce/coinbase/connector.csv?end_asset_date=2026-07-24"
    )

    assert preview.status_code == 200
    assert connector["history_events_count"] == 2
    assert connector["history_status"] == "imported_pending_review"
    assert connector["valuation_review_ready"] is True
    assert Decimal(connector["candidate_end_asset_value_eur"]) == Decimal("100")
    assert connector["negative_quantity_assets"] == []
    assert accepted.json()["status"] == "ok"
    assert Decimal(accepted.json()["data"]["value_eur"]) == Decimal("100")
    coinbase = next(
        item
        for item in accepted.json()["data"]["origin_report"]["provider_summaries"]
        if item["provider"] == "coinbase"
    )
    assert coinbase["end_asset_valuation_status"] == "covered"
    assert repeated.json()["status"] == "warning"
    assert csv_response.status_code == 200
    assert connector["history_manifest_sha256"] in csv_response.text
    assert "coinbase-history.csv" not in csv_response.text

    with store.connect() as con:
        con.execute(
            "update canonical_events set source_ref = 'buy-1-reparsed' where tx_id = 'buy-1'"
        )
    renormalized = DivorceInheritanceOriginService(
        store,
        bank_camt_dir=camt_dir,
    ).report()

    assert (
        renormalized.coinbase_connector.history_manifest_sha256
        != connector["history_manifest_sha256"]
    )
    assert renormalized.coinbase_connector.candidate_end_asset_value_eur == Decimal(
        "100"
    )
    assert renormalized.coinbase_connector.history_status == "imported_pending_review"
    assert renormalized.coinbase_connector.accepted_end_asset_value_eur is None

    added_batch = CsvRawImporter(store).import_text(
        source="coinbase",
        filename="coinbase-later-export.csv",
        content=(
            "Timestamp,Transaction Type,Asset,Quantity Transacted,Spot Price Currency,Subtotal,Fees and/or Spread,Transaction ID\n"
            "2026-01-01T10:00:00Z,Receive,SOL,0.5,EUR,,,receive-2\n"
        ),
    )
    RawNormalizer(store).normalize_batch(added_batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()

    changed = DivorceInheritanceOriginService(store, bank_camt_dir=camt_dir).report()

    assert changed.coinbase_connector.history_status == "imported_pending_review"
    assert changed.coinbase_connector.accepted_end_asset_value_eur is None
    assert changed.coinbase_connector.candidate_end_asset_value_eur == Decimal("150")
    changed_coinbase = next(
        item for item in changed.provider_summaries if item.provider == "coinbase"
    )
    assert changed_coinbase.end_asset_valuation_status == "missing"
