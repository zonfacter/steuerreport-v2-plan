from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.admin import AdminSettingWrite
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.contracts.portfolio import PortfolioLiveBalanceSnapshot
from steuerreport_v2.contracts.review import ReviewDecisionCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.solscan_preflight import (
    DEFAULT_BLOCKPIT_SOLANA_FILE,
    DEFAULT_RPC_EVIDENCE_ARTIFACT,
    DEFAULT_SOLSCAN_FILE,
)
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


LOCAL_IOT_EVIDENCE_AVAILABLE = all(
    Path(path).is_file()
    for path in (
        DEFAULT_BLOCKPIT_SOLANA_FILE,
        DEFAULT_RPC_EVIDENCE_ARTIFACT,
        DEFAULT_SOLSCAN_FILE,
    )
)


def _build_balance(store: DuckDbStore, content: str) -> None:
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="pionex.csv",
        content=content,
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()


def test_review_gate_blocks_missing_price(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _build_balance(
        store,
        "time,coin,change,type\n2021-04-28T10:00:00Z,BTC,0.5,deposit\n",
    )

    gate = ReviewService(store).gate()

    assert gate.allow_export is False
    assert gate.issues_high_open == 1
    assert gate.issues_medium_open == 0
    assert gate.issues_low_open == 0
    assert gate.blocking_issues_open == 1
    assert gate.issues[0].code == "missing_price"


def test_review_gate_blocks_missing_historical_event_price(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="manual-test",
            source_ref="iot-buy",
            event_time=datetime(2024, 4, 1, tzinfo=timezone.utc),
            event_type="trade",
            asset="SOL",
            quantity=Decimal("1"),
            quote_asset="IOT",
            quote_quantity=Decimal("100"),
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("120"),
            priced_at=datetime(2024, 4, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    gate = ReviewService(store).gate()

    assert gate.allow_export is False
    issue_codes = {issue.code for issue in gate.issues}
    assert "missing_event_price" in issue_codes
    issue = next(issue for issue in gate.issues if issue.code == "missing_event_price")
    assert "IOT" in issue.message
    assert "2024" in issue.message


def test_price_coverage_api_groups_missing_prices_by_asset_year_and_source(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="manual-test",
            source_ref="iot-buy-1",
            event_time=datetime(2024, 4, 1, tzinfo=timezone.utc),
            event_type="trade",
            asset="SOL",
            quantity=Decimal("1"),
            quote_asset="IOT",
            quote_quantity=Decimal("100"),
        )
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="manual-test",
            source_ref="iot-buy-2",
            event_time=datetime(2024, 4, 2, tzinfo=timezone.utc),
            event_type="trade",
            asset="SOL",
            quantity=Decimal("2"),
            quote_asset="IOT",
            quote_quantity=Decimal("50"),
        )
    )
    client = TestClient(create_app(store))

    response = client.get("/api/v1/prices/coverage")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["missing_count"] == 1
    assert data["missing_assets"] == ["IOT"]
    assert data["missing"][0]["asset"] == "IOT"
    assert data["missing"][0]["scope"] == (
        "price_gap:asset:IOT:year:2024:source:manual-test:event_type:trade:role:quote_asset"
    )
    assert data["missing"][0]["decision_status"] == "unreviewed"
    assert data["missing"][0]["year"] == 2024
    assert data["missing"][0]["event_count"] == 2
    assert data["missing"][0]["gross_quantity"] == "150.000000000000000000"


def test_price_requirements_api_groups_missing_prices_by_asset_date(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="manual-test",
            source_ref="iot-buy-1",
            event_time=datetime(2024, 4, 1, 8, tzinfo=timezone.utc),
            event_type="trade",
            asset="SOL",
            quantity=Decimal("1"),
            quote_asset="IOT",
            quote_quantity=Decimal("100"),
        )
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="manual-test",
            source_ref="iot-buy-2",
            event_time=datetime(2024, 4, 1, 12, tzinfo=timezone.utc),
            event_type="trade",
            asset="SOL",
            quantity=Decimal("2"),
            quote_asset="IOT",
            quote_quantity=Decimal("50"),
        )
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="manual-test",
            source_ref="iot-buy-3",
            event_time=datetime(2024, 4, 2, tzinfo=timezone.utc),
            event_type="trade",
            asset="SOL",
            quantity=Decimal("3"),
            quote_asset="IOT",
            quote_quantity=Decimal("25"),
        )
    )
    client = TestClient(create_app(store))

    response = client.get("/api/v1/prices/requirements")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["requirements_count"] == 2
    assert data["missing_assets"] == ["IOT"]
    assert data["requirements"][0]["price_date"] == "2024-04-01"
    assert data["requirements"][0]["event_count"] == 2
    assert data["requirements"][0]["gross_quantity"] == "150.000000000000000000"
    assert data["requirements"][1]["price_date"] == "2024-04-02"
    assert data["requirements"][1]["event_count"] == 1


def test_price_gap_decision_marks_coverage_group_without_unblocking_gate(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="manual-test",
            event_time=datetime(2024, 4, 1, tzinfo=timezone.utc),
            event_type="trade",
            asset="SOL",
            quantity=Decimal("1"),
            quote_asset="IOT",
            quote_quantity=Decimal("100"),
        )
    )
    client = TestClient(create_app(store))
    scope = "price_gap:asset:IOT:year:2024:source:manual-test:event_type:trade:role:quote_asset"

    response = client.post(
        "/api/v1/prices/coverage/decisions",
        json={
            "scope": scope,
            "decision_status": "manual_price_required",
            "title": "IOT Preis manuell belegen",
            "rationale": "Keine belastbare automatische Preisquelle vorhanden.",
            "evidence_ref": "docs/test.md",
        },
    )
    coverage = client.get("/api/v1/prices/coverage").json()["data"]
    gate = client.get("/api/v1/review/gates").json()["data"]

    assert response.status_code == 200
    assert response.json()["data"]["decision_status"] == "manual_price_required"
    assert coverage["missing"][0]["decision_status"] == "manual_price_required"
    assert coverage["missing"][0]["decision_id"] == response.json()["data"]["decision_id"]
    assert gate["allow_export"] is False
    assert {issue["code"] for issue in gate["issues"]} == {"missing_event_price"}


def test_review_gate_blocks_negative_balance(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _build_balance(
        store,
        "time,coin,change,type\n2021-04-28T10:00:00Z,USDT,-10,withdrawal\n",
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.90"),
            priced_at=datetime(2021, 4, 28, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    gate = ReviewService(store).gate()

    assert gate.allow_export is False
    assert {issue.code for issue in gate.issues} == {"negative_balance"}


def test_review_gate_blocks_unresolved_truncated_accounts(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _build_balance(
        store,
        "time,coin,change,type,account\n"
        "2024-01-01T00:00:00Z,HNT,10,deposit,138bCXPVf...mF7rjA8y\n",
    )
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("7.5"),
            priced_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    gate = ReviewService(store).gate()

    assert gate.allow_export is False
    assert {issue.code for issue in gate.issues} == {"unresolved_truncated_account"}


def test_review_gate_allows_clean_portfolio(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _build_balance(
        store,
        "time,coin,change,type\n2021-04-28T10:00:00Z,USDT,10,deposit\n",
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.90"),
            priced_at=datetime(2021, 4, 28, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    gate = ReviewService(store).gate()

    assert gate.allow_export is True
    assert gate.issues_open == 0
    assert gate.blocking_issues_open == 0


def test_review_gate_blocks_unmatched_tax_disposals(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="trades.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2021-01-01T00:00:00Z,ETH,-1,sell,EUR,1000\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="ETH",
            price_eur=Decimal("1000"),
            priced_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    TaxService(store).rebuild_fifo()

    gate = ReviewService(store).gate()
    unmatched = TaxService(store).list_unmatched_disposals()

    assert gate.allow_export is False
    assert "unmatched_tax_disposal" in {issue.code for issue in gate.issues}
    assert len(unmatched) == 1
    assert unmatched[0].asset == "ETH"
    assert unmatched[0].quantity == Decimal("1.000000000000000000")
    assert unmatched[0].matched_quantity == Decimal("0E-18")
    assert unmatched[0].missing_quantity == Decimal("1.000000000000000000")
    assert unmatched[0].source == "binance"
    issue = next(issue for issue in gate.issues if issue.code == "unmatched_tax_disposal")
    assert "ETH" in issue.message
    assert "fehlend 1.000000000000000000" in issue.message


def test_review_tasks_prioritize_fifo_unmatched_disposals(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="trades.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2021-01-01T00:00:00Z,ETH,-1,sell,EUR,1000\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="ETH",
            price_eur=Decimal("1000"),
            priced_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    TaxService(store).rebuild_fifo()

    summary = ReviewService(store).tasks()

    assert summary.open_tasks >= 1
    assert summary.blocking_tasks >= 1
    assert summary.fifo_relevant_tasks >= 1
    task = next(item for item in summary.tasks if item.decision_status == "unmatched_tax_disposal")
    assert task.priority == "high"
    assert task.category == "fifo"
    assert task.blocks_export is True
    assert task.action_path == "/api/v1/tax/unmatched-disposals"
    assert "FIFO" in task.title


def test_review_tasks_api_includes_price_gap_work_items(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="manual-test",
            source_ref="iot-buy",
            event_time=datetime(2024, 4, 1, tzinfo=timezone.utc),
            event_type="trade",
            asset="SOL",
            quantity=Decimal("1"),
            quote_asset="IOT",
            quote_quantity=Decimal("100"),
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("120"),
            priced_at=datetime(2024, 4, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    client = TestClient(create_app(store))

    response = client.get("/api/v1/review/tasks")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["open_tasks"] >= 1
    assert data["blocking_tasks"] >= 1
    assert data["high_priority_tasks"] >= 1
    assert any(
        task["category"] == "price" and task["asset"] == "IOT"
        for task in data["tasks"]
    )


def test_review_gate_keeps_closed_year_unmatched_visible_without_blocking_export(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.upsert_admin_setting(
        AdminSettingWrite(
            key="runtime.review.closed_tax_years",
            value_json="[2020, 2021, 2022]",
        )
    )
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="trades.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2021-04-27T00:00:00Z,BNB,2.235,transfer,,\n"
            "2021-04-28T07:53:14Z,BNB,-2.47,sell,EUR,1136.09\n"
            "2021-04-29T00:00:00Z,BNB,0.235,transfer,,\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="BNB",
            price_eur=Decimal("460"),
            priced_at=datetime(2021, 4, 28, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    TaxService(store).rebuild_fifo()

    gate = ReviewService(store).gate()

    assert gate.allow_export is True
    assert gate.issues_open == 0
    assert gate.issues_open_total == 1
    assert gate.issues_historical_open == 1
    assert gate.blocking_issues_open == 0
    issue = gate.issues[0]
    assert issue.code == "unmatched_tax_disposal"
    assert issue.tax_year == 2021
    assert issue.is_current_scope is False
    assert issue.blocks_export is False


def test_review_gate_blocks_unmapped_raw_objects(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="broken.csv",
        content="time,asset,note\n2021-01-01T00:00:00Z,BTC,no amount\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)

    gate = ReviewService(store).gate()

    assert gate.allow_export is False
    assert "unmapped_raw_objects" in {issue.code for issue in gate.issues}


def test_review_gate_allows_bitget_withdrawal_evidence_only_raw_objects(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="bitget",
        filename="bitget-withdrawal-api.csv",
        content=(
            "record_type,type,asset,coin,amount,quantity,fee,cTime,uTime,time,account,address,toAddress,chain,network,tx_id,txId,source_ref,status\n"
            "bitget_withdrawal_evidence,withdraw,SOL,SOL,7.0760475,7.0760475,-0.006,1749973423929,1749973546005,2025-06-15T07:45:46+00:00,bitget,EnbD7,EnbD7,SOL,SOL,sig,sig,order-1,success\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)

    gate = ReviewService(store).gate()

    assert "unmapped_raw_objects" not in {issue.code for issue in gate.issues}


def test_review_gate_blocks_zero_cost_tax_lots_after_closed_position(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="hnt.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2021-01-01T00:00:00Z,HNT,10,mining,,\n"
            "2021-06-01T00:00:00Z,HNT,-10,sell,EUR,50\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    TaxService(store).rebuild_fifo()

    gate = ReviewService(store).gate()

    assert gate.allow_export is False
    assert "zero_cost_tax_lots" in {issue.code for issue in gate.issues}


def test_review_gate_does_not_block_unused_zero_cost_lots(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="hnt.csv",
        content="time,asset,amount,type\n2021-01-01T00:00:00Z,HNT,10,mining\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("2"),
            priced_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    TaxService(store).rebuild_fifo()

    gate = ReviewService(store).gate()

    assert "zero_cost_tax_lots" not in {issue.code for issue in gate.issues}


def test_review_gate_blocks_zero_proceeds_tax_lines(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="mxc.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2021-01-01T00:00:00Z,MXC,100,buy,EUR,10\n"
            "2021-06-01T00:00:00Z,MXC,-40,sell,USDT,8\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    TaxService(store).rebuild_fifo()

    gate = ReviewService(store).gate()

    assert gate.allow_export is False
    assert "zero_proceeds_tax_lines" in {issue.code for issue in gate.issues}


def test_review_decisions_are_stored_without_changing_gates(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _build_balance(
        store,
        "time,coin,change,type\n2024-01-01T00:00:00Z,SOL,-1,withdrawal\n",
    )
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("80"),
            priced_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    gate_before = ReviewService(store).gate()
    assert gate_before.allow_export is False
    decision = store.add_review_decision(
        ReviewDecisionCreate(
            decision_type="opening_balance_candidate",
            scope="account:Solana:asset:SOL",
            title="Solana SOL Opening-Balance Kandidat",
            rationale="Staging zeigt, dass 1 SOL Startbestand den negativen Bestand behebt.",
            evidence_ref="docs/228_SOLANA_PRIORITY_STAGING_2026-05-19.md",
            payload={"asset": "SOL", "amount": "1"},
        )
    )

    decisions = store.list_review_decisions()
    gate_after = ReviewService(store).gate()

    assert decisions[0].decision_id == decision.decision_id
    assert decisions[0].payload == {"asset": "SOL", "amount": "1"}
    assert gate_after.allow_export is False
    assert gate_after.issues_open == gate_before.issues_open


def test_review_decisions_api_roundtrip(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/review/decisions",
        json={
            "decision_type": "opening_balance_candidate",
            "scope": "account:Solana:asset:SOL",
            "title": "SOL Startbestand",
            "rationale": "Belegter Staging-Kandidat, noch nicht live wirksam.",
            "evidence_ref": "docs/228_SOLANA_PRIORITY_STAGING_2026-05-19.md",
            "actor": "codex",
            "source": "unit-test",
            "affected_ids": ["event-a"],
            "payload": {"amount": "0.004176713", "asset": "SOL"},
        },
    )

    assert response.status_code == 200
    created = response.json()["data"]
    assert created["decision_id"]
    assert created["payload"]["amount"] == "0.004176713"

    list_response = client.get("/api/v1/review/decisions")

    assert list_response.status_code == 200
    decisions = list_response.json()["data"]
    assert len(decisions) == 1
    assert decisions[0]["decision_id"] == created["decision_id"]
    assert decisions[0]["actor"] == "codex"
    assert decisions[0]["source"] == "unit-test"
    assert decisions[0]["affected_ids"] == ["event-a"]


@pytest.mark.skipif(
    not LOCAL_IOT_EVIDENCE_AVAILABLE,
    reason="requires private Solscan, Blockpit, and RPC evidence files",
)
def test_review_decision_suggestions_include_verified_iot_evidence(tmp_path):
    client = TestClient(create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb")))

    response = client.get("/api/v1/review/decision-suggestions")

    assert response.status_code == 200
    suggestions = response.json()["data"]
    scopes = {item["scope"] for item in suggestions}
    assert "blockpit_solana:opening_balance:asset:IOT" in scopes
    assert "solscan_iot:blockpit_missing_signatures" in scopes
    iot = next(
        item
        for item in suggestions
        if item["scope"] == "blockpit_solana:opening_balance:asset:IOT"
    )
    assert iot["decision_type"] == "evidence_acceptance"
    assert iot["confidence"] == "high"
    assert iot["auto_persist"] is False
    assert iot["payload"]["import_effect"] == "none"
    solscan = next(
        item
        for item in suggestions
        if item["scope"] == "solscan_iot:blockpit_missing_signatures"
    )
    assert solscan["evidence_ref"] == "/api/v1/import/solscan/evidence-trace"
    assert "solscan_evidence_trace:IOT" in solscan["affected_ids"]
    assert solscan["payload"]["evidence_trace_endpoint"] == "/api/v1/import/solscan/evidence-trace"
    assert solscan["payload"]["evidence_trace_status"] == "rpc_verified"
    assert solscan["payload"]["import_effect"] == "none"


def test_review_decision_suggestions_include_spam_token_documentation(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="solana_rpc",
        filename="solana.csv",
        content=(
            "time,asset,amount,type,account\n"
            "2026-01-01T10:00:00Z,CBDC,5,deposit,wallet-main\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="CBDC",
            price_eur=Decimal("2"),
            priced_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    now = datetime.now(timezone.utc)
    with store.connect() as con:
        con.execute(
            """
            insert into jupiter_token_metadata_cache (
                mint, symbol, name, decimals, icon, token_program, is_verified,
                organic_score, organic_score_label, holder_count, liquidity_usd,
                usd_price, market_cap_usd, risk_status, source,
                discovered_sources_json, refreshed_at, jupiter_updated_at
            ) values (
                'fakeMint1111111111111111111111111111111111', 'CBDC',
                'Central Bank Digital Currency', 6, null, null, false,
                1, 'low', 1, 0, 0, 0, 'spam_review', 'jupiter_tokens_v2',
                '["v1_solscan:wallet-main"]', ?, null
            )
            """,
            [now],
        )

    suggestions = ReviewService(store).decision_suggestions()
    suggestion = next(
        item
        for item in suggestions
        if item.scope.startswith("token_risk:spam_review:asset:CBDC:mint:")
    )

    assert suggestion.decision_type == "token_risk_documentation"
    assert suggestion.confidence == "medium"
    assert suggestion.evidence_ref == "/api/v1/portfolio/token-risk?risk_status=spam_review&min_value_eur=1"
    assert suggestion.payload["import_effect"] == "none"
    assert suggestion.payload["ledger_effect"] == "none"
    assert suggestion.payload["fifo_effect"] == "none"
    assert suggestion.payload["tax_line_effect"] == "none"
    assert suggestion.payload["accounts"] == ["wallet-main"]
    assert "account:wallet-main" in suggestion.affected_ids

    tasks = ReviewService(store).tasks().tasks
    task = next(item for item in tasks if item.scope == suggestion.scope)

    assert task.category == "evidence"
    assert task.blocks_export is False
    assert task.asset == "CBDC"
    assert task.token_risk_status == "spam_review"
    assert task.action_path == (
        f"/api/v1/review/decision-suggestions/{suggestion.suggestion_id}/accept"
    )


@pytest.mark.skipif(
    not LOCAL_IOT_EVIDENCE_AVAILABLE,
    reason="requires private Solscan, Blockpit, and RPC evidence files",
)
def test_review_tasks_link_solscan_evidence_trace(tmp_path):
    client = TestClient(create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb")))

    response = client.get("/api/v1/review/tasks")

    assert response.status_code == 200
    tasks = response.json()["data"]["tasks"]
    task = next(
        item
        for item in tasks
        if item["scope"] == "solscan_iot:blockpit_missing_signatures"
    )
    assert task["category"] == "evidence"
    assert task["action_path"] == "/api/v1/review/decision-suggestions/solscan_iot_missing_signatures_rpc_verified/accept"
    assert "/api/v1/import/solscan/evidence-trace" in task["evidence_refs"]
    assert "solscan_evidence_trace:IOT" in task["evidence_refs"]
    assert task["decision_status"] == "suggestion:high"


def test_review_evidence_traces_report_missing_and_legacy_decisions(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    service = ReviewService(store)

    missing = service.evidence_traces()
    assert missing.traces_count == 1
    assert missing.missing_decision_count == 1
    assert missing.traces[0].status == "missing_decision"
    assert missing.traces[0].canonical_evidence_ref == "/api/v1/import/solscan/evidence-trace"
    assert missing.traces[0].import_effect == "none"
    assert missing.traces[0].target_changed is False

    store.add_review_decision(
        ReviewDecisionCreate(
            decision_type="evidence_acceptance",
            scope="solscan_iot:blockpit_missing_signatures",
            title="legacy",
            rationale="legacy evidence",
            evidence_ref="var/staging_audits/legacy-rpc.json",
        )
    )

    legacy = service.evidence_traces()
    assert legacy.legacy_ref_count == 1
    assert legacy.canonical_count == 0
    assert legacy.traces[0].status == "legacy_ref"
    assert legacy.traces[0].stored_evidence_ref == "var/staging_audits/legacy-rpc.json"


def test_review_evidence_traces_api(tmp_path):
    client = TestClient(create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb")))

    response = client.get("/api/v1/review/evidence-traces")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["traces_count"] == 1
    assert data["traces"][0]["scope"] == "solscan_iot:blockpit_missing_signatures"
    assert data["traces"][0]["canonical_evidence_ref"] == "/api/v1/import/solscan/evidence-trace"


def test_review_evidence_trace_canonicalize_dry_run_and_execute(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    decision = store.add_review_decision(
        ReviewDecisionCreate(
            decision_type="evidence_acceptance",
            scope="solscan_iot:blockpit_missing_signatures",
            title="legacy",
            rationale="legacy evidence",
            evidence_ref="var/staging_audits/legacy-rpc.json",
            payload={"import_effect": "none"},
        )
    )
    service = ReviewService(store)

    dry_run = service.canonicalize_evidence_traces(execute=False)

    assert dry_run.dry_run is True
    assert dry_run.target_changed is False
    assert dry_run.candidates_count == 1
    assert dry_run.updated_count == 0
    assert store.list_review_decisions()[0].evidence_ref == "var/staging_audits/legacy-rpc.json"

    executed = service.canonicalize_evidence_traces(execute=True)

    assert executed.dry_run is False
    assert executed.target_changed is True
    assert executed.candidates_count == 1
    assert executed.updated_count == 1
    assert executed.updated_decision_ids == [decision.decision_id]
    updated = store.list_review_decisions()[0]
    assert updated.evidence_ref == "/api/v1/import/solscan/evidence-trace"
    assert updated.payload["previous_evidence_ref"] == "var/staging_audits/legacy-rpc.json"
    assert updated.payload["canonical_evidence_ref"] == "/api/v1/import/solscan/evidence-trace"
    assert updated.payload["import_effect"] == "none"
    assert updated.updated_at is not None


def test_review_evidence_trace_canonicalize_api_dry_run(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_review_decision(
        ReviewDecisionCreate(
            decision_type="evidence_acceptance",
            scope="solscan_iot:blockpit_missing_signatures",
            title="legacy",
            rationale="legacy evidence",
            evidence_ref="var/staging_audits/legacy-rpc.json",
        )
    )
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/review/evidence-traces/canonicalize",
        json={"execute": False},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["dry_run"] is True
    assert data["candidates_count"] == 1
    assert data["updated_count"] == 0
    assert store.list_review_decisions()[0].evidence_ref == "var/staging_audits/legacy-rpc.json"


@pytest.mark.skipif(
    not LOCAL_IOT_EVIDENCE_AVAILABLE,
    reason="requires private Solscan, Blockpit, and RPC evidence files",
)
def test_review_decision_suggestion_acceptance_is_idempotent(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))
    suggestion_id = "blockpit_solana_iot_opening_wallet_monthly_coverage"

    response = client.post(f"/api/v1/review/decision-suggestions/{suggestion_id}/accept")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    decision = response.json()["data"]
    assert decision["scope"] == "blockpit_solana:opening_balance:asset:IOT"
    assert decision["payload"]["suggestion_id"] == suggestion_id
    assert decision["payload"]["import_effect"] == "none"

    duplicate = client.post(f"/api/v1/review/decision-suggestions/{suggestion_id}/accept")

    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "warning"
    assert duplicate.json()["data"]["decision_id"] == decision["decision_id"]
    assert len(store.list_review_decisions()) == 1


def test_review_decision_suggestion_acceptance_rejects_unknown_id(tmp_path):
    client = TestClient(create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb")))

    response = client.post("/api/v1/review/decision-suggestions/does-not-exist/accept")

    assert response.status_code == 200
    assert response.json()["status"] == "error"
    assert response.json()["errors"][0]["code"] == "review_suggestion_not_found"


def test_review_tasks_include_price_quality_bucket_work(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.92"),
            priced_at=datetime(2022, 1, 1, tzinfo=timezone.utc),
            source="derived:event_quote",
            confidence=Decimal("0.85"),
        )
    )
    with store.connect() as con:
        con.execute(
            """
            insert into tax_lines (
                tax_line_id, asset, disposed_at, quantity,
                acquisition_cost_eur, disposal_proceeds_eur, gain_loss_eur,
                holding_days, source_event_id, lot_id, created_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                "tax-usdt-2022",
                "USDT",
                datetime(2022, 2, 1, tzinfo=timezone.utc),
                Decimal("1"),
                Decimal("1"),
                Decimal("1"),
                Decimal("0"),
                1,
                "event-1",
                "lot-1",
                datetime(2026, 1, 1, tzinfo=timezone.utc),
            ],
        )
    store.add_review_decision(
        ReviewDecisionCreate(
            decision_type="price_quality",
            scope="price_quality:asset:USDT:year:2022:source:derived:event_quote",
            title="USDT FX pruefen",
            rationale="Stablecoin braucht FX-Evidenz.",
            source="unit-test",
            payload={"decision_status": "manual_review_required", "import_effect": "none"},
        )
    )

    tasks = ReviewService(store).tasks()

    price_quality_tasks = [
        task for task in tasks.tasks if task.source == "price_quality_manual_review"
    ]
    assert len(price_quality_tasks) == 1
    assert price_quality_tasks[0].scope == "price_quality_bucket:stablecoin_fx_review"
    assert price_quality_tasks[0].action_path == "/api/v1/prices/quality/stablecoin-fx-review"
    assert price_quality_tasks[0].blocks_export is False
    assert price_quality_tasks[0].decision_status == "stablecoin_fx_review"


def test_review_tasks_include_source_reconciliation_warnings(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="binance-ledger.csv",
        content="time,asset,amount,type,account\n2026-05-29T00:00:00Z,JUP,1,deposit,Spot\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    priced_at = datetime(2026, 5, 30, tzinfo=timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("0.2"),
            priced_at=priced_at,
            source="manual-test",
        )
    )
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="binance:JUP:earn",
                connector_id="binance",
                asset="JUP",
                quantity=Decimal("40"),
                source="v1_connector:binance",
                fetched_at=priced_at,
                account_type="simple_earn_flexible",
                product_id="JUP001",
            )
        ]
    )

    tasks = ReviewService(store).tasks()

    source_tasks = [task for task in tasks.tasks if task.source == "source_reconciliation"]
    assert len(source_tasks) == 1
    assert source_tasks[0].scope == "source_reconciliation:binance"
    assert source_tasks[0].action_path == "/api/v1/sources/binance/reconciliation"
    assert source_tasks[0].blocks_export is False
    assert source_tasks[0].category == "reconciliation"


def test_review_tasks_skip_documented_bitget_dust(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="bitget",
        filename="bitget-ledger.csv",
        content="time,asset,amount,type,account\n2024-12-12T00:00:00Z,USDT,7.945994569,deposit,bitget\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    priced_at = datetime(2026, 5, 30, tzinfo=timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.8587904019434827"),
            priced_at=priced_at,
            source="manual-test",
        )
    )
    PortfolioService(store)._replace_live_balance_snapshots(
        [
            PortfolioLiveBalanceSnapshot(
                snapshot_id="bitget:USDT:test",
                connector_id="bitget",
                asset="USDT",
                quantity=Decimal("0.000000006884"),
                source="v1_connector:bitget",
                fetched_at=priced_at,
            )
        ]
    )

    tasks = ReviewService(store).tasks()

    assert not [
        task
        for task in tasks.tasks
        if task.source == "source_reconciliation" and task.source_group == "Bitget"
    ]
