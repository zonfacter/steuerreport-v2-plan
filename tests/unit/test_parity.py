from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.parity import V1ReferenceMetricCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.parity import V1ParityService
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.importers.wiso_reference_importer import WisoReferenceImporter
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


WISO_SAMPLE = """Identifier:Capital_Gains,Method:FIFO,Tax_Year:2021,Base_Currency:EUR,Par22Nr3:0.00
Amount,Currency,Date Acquired,Date Sold,Short / Long,Buy / Input at,Sell / Output at,Proceeds,Cost Basis,Gain / Loss
1,BTC,01.01.2021,02.01.2021,Short,Binance,Binance,100,40,60
0.5,BTC,01.01.2021,03.01.2021,Short,Binance,Binance,80,20,60
10,HNT,01.01.2021,03.01.2021,Short,Helium,Binance,30,10,20
"""


def test_v1_reference_metrics_are_persisted_and_listed(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    created = store.add_v1_reference_metric(
        V1ReferenceMetricCreate(
            scope="tax",
            metric="gain_loss_eur",
            unit="EUR",
            value=Decimal("2000"),
            year=2021,
            asset="btc",
            note="V1 export",
        )
    )

    references = store.list_v1_reference_metrics()

    assert len(references) == 1
    assert references[0].reference_id == created.reference_id
    assert references[0].value == Decimal("2000.000000000000000000")
    assert references[0].asset == "BTC"


def test_v1_parity_compare_reports_match_and_difference(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    PipelineService(store).seed_demo()
    store.add_v1_reference_metric(
        V1ReferenceMetricCreate(
            scope="tax",
            metric="gain_loss_eur",
            unit="EUR",
            value=Decimal("2000"),
            year=2021,
            asset="BTC",
        )
    )
    store.add_v1_reference_metric(
        V1ReferenceMetricCreate(
            scope="tax",
            metric="disposal_proceeds_eur",
            unit="EUR",
            value=Decimal("999"),
            year=2021,
            asset="BTC",
        )
    )

    summary = V1ParityService(store).compare()

    assert summary.compared == 2
    assert summary.matches == 1
    assert summary.differences == 1
    assert summary.missing_v2 == 0
    assert {row.status for row in summary.rows} == {"match", "diff"}


def test_v1_parity_diagnostics_groups_open_issues(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    PipelineService(store).seed_demo()
    store.add_v1_reference_metric(
        V1ReferenceMetricCreate(
            scope="tax",
            metric="gain_loss_eur",
            unit="EUR",
            value=Decimal("1000"),
            year=2021,
            asset="BTC",
        )
    )
    store.add_v1_reference_metric(
        V1ReferenceMetricCreate(
            scope="tax",
            metric="disposal_proceeds_eur",
            unit="EUR",
            value=Decimal("999"),
            year=2021,
            asset="BTC",
        )
    )
    store.add_v1_reference_metric(
        V1ReferenceMetricCreate(
            scope="tax",
            metric="gain_loss_eur",
            unit="EUR",
            value=Decimal("1"),
            year=2024,
            asset="JUP",
        )
    )

    diagnostics = V1ParityService(store).diagnostics()

    assert diagnostics.compared == 3
    assert diagnostics.differences == 2
    assert diagnostics.missing_v2 == 1
    btc_group = [
        group
        for group in diagnostics.groups
        if group.year == 2021 and group.asset == "BTC" and group.status == "diff"
    ][0]
    assert btc_group.issue_count == 2
    assert btc_group.scope == "parity:year:2021:asset:BTC:status:diff"
    assert btc_group.decision_status == "unreviewed"
    assert btc_group.metrics == ["disposal_proceeds_eur", "gain_loss_eur"]
    assert btc_group.absolute_difference_eur > Decimal("0")


def test_v1_parity_release_readiness_blocks_unreviewed_groups(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    PipelineService(store).seed_demo()
    store.add_v1_reference_metric(
        V1ReferenceMetricCreate(
            scope="tax",
            metric="gain_loss_eur",
            unit="EUR",
            value=Decimal("1000"),
            year=2021,
            asset="BTC",
        )
    )

    readiness = V1ParityService(store).release_readiness()

    assert readiness.release_ready is False
    assert readiness.blocking_groups == 1
    assert readiness.unresolved_groups == 1
    assert readiness.accepted_groups == 0
    assert readiness.blocking_difference_eur > Decimal("0")
    assert readiness.blocking_groups_top[0].scope == "parity:year:2021:asset:BTC:status:diff"


def test_v1_parity_group_detail_exposes_tax_sources_and_samples(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="raw-trading-details.csv",
        content=(
            "date(UTC+0),symbol,side,executed_qty,amount,fee,fee_coin,state,tax_id\n"
            "2022-01-01 00:00:00,HNT_USDT,BUY,10,100,0.05,USDT,FILLED,b_1\n"
            "2022-01-02 00:00:00,HNT_USDT,SELL,4,60,0.03,USDT,FILLED,s_1\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.90"),
            priced_at=datetime(2022, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    TaxService(store).rebuild_fifo()
    store.add_v1_reference_metric(
        V1ReferenceMetricCreate(
            scope="tax",
            metric="quantity_disposed",
            unit="HNT",
            value=Decimal("1"),
            year=2022,
            asset="HNT",
        )
    )

    detail = V1ParityService(store).group_detail("parity:year:2022:asset:HNT:status:diff")

    assert detail.asset == "HNT"
    assert detail.year == 2022
    assert detail.metrics[0].metric == "quantity_disposed"
    assert detail.tax_source_summaries[0].source == "pionex"
    assert detail.tax_source_summaries[0].filename == "raw-trading-details.csv"
    assert detail.tax_source_summaries[0].quantity == Decimal("4.000000000000000000")
    assert detail.tax_event_samples[0].source_ref == "s_1"
    assert detail.tax_event_samples[0].payload["symbol"] == "HNT_USDT"


def test_hnt_wallet_bridge_shows_pionex_internal_trade_churn(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="raw-trading-details.csv",
        content=(
            "date(UTC+0),symbol,side,executed_qty,amount,fee,fee_coin,state,tax_id\n"
            "2022-01-01 00:00:00,HNT_USDT,BUY,10,100,0.05,USDT,FILLED,b_1\n"
            "2022-01-02 00:00:00,HNT_USDT,SELL,4,60,0.03,USDT,FILLED,s_1\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.90"),
            priced_at=datetime(2022, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    TaxService(store).rebuild_fifo()
    store.add_v1_reference_metric(
        V1ReferenceMetricCreate(
            scope="tax",
            metric="quantity_disposed",
            unit="HNT",
            value=Decimal("1"),
            year=2022,
            asset="HNT",
        )
    )

    report = V1ParityService(store).hnt_wallet_bridge(2022)

    assert report.v1_quantity_disposed == Decimal("1.000000000000000000")
    assert report.v2_quantity_disposed == Decimal("4.000000000000000000")
    assert report.quantity_difference == Decimal("3.000000000000000000")
    assert report.pionex_buys == Decimal("10.000000000000000000")
    assert report.pionex_sells == Decimal("4.000000000000000000")
    assert report.pionex_net == Decimal("6.000000000000000000")
    assert "Pionex-internen" in report.interpretation


def test_hnt_fifo_provenance_keeps_transfer_counterparties_separate_from_current_wallets(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    main_wallet = PortfolioService.MAIN_HELIUM_LEGACY_WALLET
    fairspot_wallet = PortfolioService.FAIRSPOT_STAKING_WALLET
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="helium-fairspot.csv",
        content=(
            "time,asset,amount,type,txid,payer,payee\n"
            f"2021-06-23T20:26:18Z,HNT,100,payment_v2,tx-fairspot,{main_wallet},{fairspot_wallet}\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="helium",
                source_ref="mine-1",
                event_time=datetime(2021, 1, 1, tzinfo=timezone.utc),
                event_type="mining",
                asset="HNT",
                quantity=Decimal("10"),
                account=main_wallet,
            ),
            CanonicalEventCreate(
                source="binance",
                source_ref="sell-1",
                event_time=datetime(2021, 7, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("-3"),
                quote_asset="EUR",
                quote_quantity=Decimal("30"),
                account="Binance Spot",
                tx_id="sell-tx",
            ),
            CanonicalEventCreate(
                source="solscan",
                source_ref="live-wallet-1",
                event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("2"),
                account=PortfolioService.PRIMARY_SOLANA_WALLET,
                tx_id="solana-tx",
            ),
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("2"),
            priced_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    TaxService(store).rebuild_fifo()

    report = V1ParityService(store).hnt_fifo_provenance(limit=20)
    fairspot_report = V1ParityService(store).hnt_fifo_provenance(
        limit=20,
        account=fairspot_wallet,
    )

    assert report.asset == "HNT"
    assert report.timeline
    assert report.open_lots == 1
    assert report.disposals == 1
    assert report.fifo_relevant_events == 2
    fairspot_event = next(event for event in report.events if event.tx_id == "tx-fairspot")
    assert fairspot_event.event_type == "transfer"
    assert fairspot_event.counterparty_account == fairspot_wallet
    assert fairspot_event.current_portfolio_account is False
    assert "Gegenpartei" in fairspot_event.note
    solana_event = next(event for event in report.events if event.tx_id == "solana-tx")
    assert solana_event.current_portfolio_account is True
    assert report.disposal_tax_lines[0].disposal_source == "binance"
    assert fairspot_report.filter_account == fairspot_wallet
    assert fairspot_report.transfer_counterparty_events == 1
    assert [event.tx_id for event in fairspot_report.events] == ["tx-fairspot"]


def test_v1_parity_compare_uses_reference_source_as_metadata(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    PipelineService(store).seed_demo()
    store.add_v1_reference_metric(
        V1ReferenceMetricCreate(
            scope="tax",
            metric="gain_loss_eur",
            unit="EUR",
            value=Decimal("2000"),
            year=2021,
            asset="BTC",
            source="wiso:2021-export.csv",
        )
    )

    summary = V1ParityService(store).compare()

    assert summary.compared == 1
    assert summary.matches == 1
    assert summary.missing_v2 == 0


def test_v1_parity_compare_reports_missing_v2_metric(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_v1_reference_metric(
        V1ReferenceMetricCreate(
            scope="tax",
            metric="gain_loss_eur",
            unit="EUR",
            value=Decimal("1"),
            year=2020,
            asset="DOGE",
        )
    )

    summary = V1ParityService(store).compare()

    assert summary.compared == 1
    assert summary.missing_v2 == 1
    assert summary.rows[0].status == "missing_v2"


def test_v1_parity_compare_treats_missing_zero_reference_as_match(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_v1_reference_metric(
        V1ReferenceMetricCreate(
            scope="tax",
            metric="acquisition_cost_eur",
            unit="EUR",
            value=Decimal("0"),
            year=2021,
            asset="BTTOLD",
            source="wiso:2021-export.csv",
        )
    )

    summary = V1ParityService(store).compare()

    assert summary.matches == 1
    assert summary.missing_v2 == 0
    assert summary.rows[0].v2_value == Decimal("0")


def test_v1_parity_api_endpoints(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))

    create_response = client.post(
        "/api/v1/parity/v1/references",
        json={
            "scope": "portfolio",
            "metric": "total_value_eur",
            "unit": "EUR",
            "value": "0",
        },
    )
    list_response = client.get("/api/v1/parity/v1/references")
    compare_response = client.get("/api/v1/parity/compare")
    diagnostics_response = client.get("/api/v1/parity/diagnostics")
    release_response = client.get("/api/v1/parity/release-readiness")
    detail_response = client.get(
        "/api/v1/parity/group-detail",
        params={"scope": "parity:year:all:asset:all:status:diff"},
    )
    bridge_response = client.get("/api/v1/parity/hnt-wallet-bridge?year=2022")
    provenance_response = client.get("/api/v1/parity/hnt-fifo-provenance?limit=25&source=helium")
    reference_id = create_response.json()["data"]["reference_id"]
    delete_response = client.delete(f"/api/v1/parity/v1/references/{reference_id}")

    assert create_response.status_code == 200
    assert list_response.status_code == 200
    assert compare_response.status_code == 200
    assert diagnostics_response.status_code == 200
    assert release_response.status_code == 200
    assert detail_response.status_code == 200
    assert bridge_response.status_code == 200
    assert provenance_response.status_code == 200
    assert provenance_response.json()["data"]["filter_source"] == "helium"
    assert compare_response.json()["data"]["matches"] == 1
    assert diagnostics_response.json()["data"]["groups"] == []
    assert release_response.json()["data"]["release_ready"] is True
    assert delete_response.json()["data"]["deleted"] is True


def test_v1_parity_decision_marks_diagnostic_group(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    PipelineService(store).seed_demo()
    store.add_v1_reference_metric(
        V1ReferenceMetricCreate(
            scope="tax",
            metric="gain_loss_eur",
            unit="EUR",
            value=Decimal("1000"),
            year=2021,
            asset="BTC",
        )
    )
    client = TestClient(create_app(store))
    scope = "parity:year:2021:asset:BTC:status:diff"

    response = client.post(
        "/api/v1/parity/decisions",
        json={
            "scope": scope,
            "decision_status": "accepted_difference",
            "title": "V1/V2 Differenz akzeptiert",
            "rationale": "V1 enthielt gerundete Referenzwerte; V2 ist anhand Rohdaten nachvollziehbar.",
            "evidence_ref": "docs/test.md",
        },
    )
    diagnostics = client.get("/api/v1/parity/diagnostics").json()["data"]

    assert response.status_code == 200
    assert response.json()["data"]["decision_status"] == "accepted_difference"
    group = diagnostics["groups"][0]
    assert group["scope"] == scope
    assert group["decision_status"] == "accepted_difference"
    assert group["decision_id"] == response.json()["data"]["decision_id"]


def test_wiso_reference_importer_aggregates_tax_metrics(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    result = WisoReferenceImporter(store).import_text(WISO_SAMPLE, label="wiso-2021")
    references = store.list_v1_reference_metrics()

    assert result.tax_year == 2021
    assert result.rows_read == 3
    assert result.references_created == 8
    assert result.assets == ["BTC", "HNT"]
    gain_btc = [
        item
        for item in references
        if item.asset == "BTC" and item.metric == "gain_loss_eur"
    ][0]
    assert gain_btc.value == Decimal("120.000000000000000000")
    assert gain_btc.source == "wiso-2021"


def test_wiso_reference_importer_replaces_same_label(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    importer = WisoReferenceImporter(store)

    first = importer.import_text(WISO_SAMPLE, label="wiso-repeat")
    second = importer.import_text(WISO_SAMPLE, label="wiso-repeat")

    assert first.references_created == 8
    assert second.references_created == 8
    assert len(store.list_v1_reference_metrics()) == 8


def test_wiso_reference_import_endpoint_accepts_content(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/parity/v1/import/wiso",
        json={"content": WISO_SAMPLE, "label": "wiso-api"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["data"]["references_created"] == 8
    assert len(store.list_v1_reference_metrics()) == 8


def test_parity_diagnostics_csv_export_contains_group_rows(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    PipelineService(store).seed_demo()
    store.add_v1_reference_metric(
        V1ReferenceMetricCreate(
            scope="tax",
            metric="gain_loss_eur",
            unit="EUR",
            value=Decimal("1000"),
            year=2021,
            asset="BTC",
        )
    )
    client = TestClient(create_app(store))

    response = client.get("/api/v1/export/parity-diagnostics.csv")

    assert response.status_code == 200
    assert "parity-diagnostics.csv" in response.headers["content-disposition"]
    assert "scope,decision_status" in response.text
    assert "parity:year:2021:asset:BTC:status:diff" in response.text


def test_hnt_provenance_csv_exports_are_filterable(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    main_wallet = PortfolioService.MAIN_HELIUM_LEGACY_WALLET
    fairspot_wallet = PortfolioService.FAIRSPOT_STAKING_WALLET
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="helium-fairspot.csv",
        content=(
            "time,asset,amount,type,txid,payer,payee\n"
            f"2021-06-23T20:26:18Z,HNT,100,payment_v2,tx-fairspot,{main_wallet},{fairspot_wallet}\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    client = TestClient(create_app(store))

    timeline = client.get(
        "/api/v1/export/hnt-provenance-timeline.csv",
        params={"account": fairspot_wallet},
    )
    events = client.get(
        "/api/v1/export/hnt-provenance-events.csv",
        params={"account": fairspot_wallet},
    )

    assert timeline.status_code == 200
    assert "hnt-provenance-timeline.csv" in timeline.headers["content-disposition"]
    assert "Helium Legacy" in timeline.text
    assert fairspot_wallet in timeline.text
    assert events.status_code == 200
    assert "hnt-provenance-events.csv" in events.headers["content-disposition"]
    assert "tx-fairspot" in events.text
    assert "Transfer-/Bridge-Gegenpartei" in events.text
