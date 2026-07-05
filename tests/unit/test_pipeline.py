import sqlite3
from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.exports import PdfExportRequest
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.external_price_backfill import ExternalPriceBackfillService
from steuerreport_v2.domain.exports import ExportService
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


def test_demo_seed_builds_visible_pipeline(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    result = PipelineService(store).seed_demo()

    assert result.imported_rows == 5
    assert result.pipeline.balance_entries == 7
    assert result.pipeline.flow_entries == 3
    assert result.pipeline.tax_lines == 1
    assert result.pipeline.derivative_lines == 0
    assert result.pipeline.allow_export is True


def test_demo_seed_replaces_previous_demo_data(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    service = PipelineService(store)

    service.seed_demo()
    second = service.seed_demo()
    counts = store.table_counts(["raw_import_batches", "raw_objects", "canonical_events"])

    assert second.imported_rows == 5
    assert counts["raw_import_batches"] == 1
    assert counts["raw_objects"] == 5
    assert counts["canonical_events"] == 5


def test_net_flows_endpoint_filters_by_year(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    PipelineService(store).seed_demo()
    client = TestClient(create_app(store))

    response = client.get("/api/v1/flows/net?year=2021")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["year"] == 2021
    assert data["available_years"] == [2020, 2021]
    assert len(data["edges"]) == 1
    assert data["edges"][0]["source_node"] == "external"
    assert data["edges"][0]["target_node"] == "pionex-demo"


def test_export_package_pdf_download_endpoint(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    PipelineService(store).seed_demo()
    package = ExportService(store).create_pdf_packages(
        PdfExportRequest(label="test", estimated_pages=1)
    ).packages[0]
    client = TestClient(create_app(store))

    response = client.get(f"/api/v1/export/packages/{package.package_id}/download.pdf")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF-1.4")


def test_tax_lots_endpoint_lists_fifo_lots(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    PipelineService(store).seed_demo()
    client = TestClient(create_app(store))

    response = client.get("/api/v1/tax/lots")

    assert response.status_code == 200
    lots = response.json()["data"]
    assert len(lots) == 2
    by_asset = {lot["asset"]: lot for lot in lots}
    assert by_asset["BTC"]["quantity_remaining"] == "0.600000000000000000"
    assert by_asset["USDT"]["quantity_remaining"] == "1000.000000000000000000"


def test_export_package_delete_endpoint(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    PipelineService(store).seed_demo()
    package = ExportService(store).create_pdf_packages(
        PdfExportRequest(label="test", estimated_pages=1)
    ).packages[0]
    client = TestClient(create_app(store))

    response = client.delete(f"/api/v1/export/packages/{package.package_id}")

    assert response.status_code == 200
    assert response.json()["data"] == {"package_id": package.package_id, "deleted": True}
    assert ExportService(store).get_package(package.package_id) is None


def test_export_package_delete_endpoint_warns_for_missing_package(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))

    response = client.delete("/api/v1/export/packages/missing")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "warning"
    assert body["data"] == {"package_id": "missing", "deleted": False}
    assert body["warnings"][0]["code"] == "export_package_not_found"


def test_pipeline_rebuild_is_idempotent_for_canonical_events(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    service = PipelineService(store)
    service.seed_demo()

    first = service.rebuild_all()
    second = service.rebuild_all()

    assert second.normalized_events == first.normalized_events
    assert second.balance_entries == first.balance_entries


def test_pipeline_suppresses_solana_rpc_duplicate_reward_income_from_overlapping_sources(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    importer = CsvRawImporter(store)
    base_row = {
        "timestamp_utc": "2026-05-07T14:53:43+00:00",
        "event_type": "token_transfer",
        "asset": "HNT",
        "quantity": "0.40107403",
        "side": "in",
        "tx_id": "same-hnt-reward-tx",
        "wallet_address": "wallet-1",
    }
    importer.import_rows(
        source="solana_rpc",
        filename="wbr-wallet-solscan-safe.json",
        file_hash="solscan-discovery",
        rows=[
            {
                **base_row,
                "defi_label": "transfer",
                "source": "solscan_wallet_discovery",
            }
        ],
    )
    importer.import_rows(
        source="solana_rpc",
        filename="helium-reward-evidence.json",
        file_hash="helium-reward-evidence",
        rows=[
            {
                **base_row,
                "source": "helium_solana_reward_rpc_evidence",
                "logMessages": ["Program log: Instruction: SetCurrentRewardsWrapperV1"],
            }
        ],
    )

    PipelineService(store).rebuild_all()

    with store.connect() as con:
        rows = con.execute(
            """
            select event_type, asset, quantity, tx_id
            from canonical_events
            where tx_id = 'same-hnt-reward-tx'
            order by event_type
            """
        ).fetchall()

    assert rows == [
        ("reward", "HNT", Decimal("0.401074030000000000"), "same-hnt-reward-tx"),
        ("unknown", "HNT", Decimal("0E-18"), "same-hnt-reward-tx"),
    ]


def test_pipeline_carries_forward_solana_helium_claim_when_legacy_mining_matches(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    importer = CsvRawImporter(store)
    importer.import_rows(
        source="helium",
        filename="legacy-iot-mining.csv",
        file_hash="legacy-iot-mining",
        rows=[
            {
                "time": "2024-01-31T23:59:59Z",
                "asset": "IOT",
                "amount": "1000",
                "type": "mining",
                "quote_asset": "EUR",
                "quote_quantity": "10",
                "account": "legacy-wallet",
            }
        ],
    )
    importer.import_rows(
        source="solana_rpc",
        filename="solana-iot-claim.json",
        file_hash="solana-iot-claim",
        rows=[
            {
                "timestamp_utc": "2024-02-01T00:00:00+00:00",
                "event_type": "token_transfer",
                "asset": "IOT",
                "quantity": "980",
                "side": "in",
                "tx_id": "claim-iot-on-solana",
                "wallet_address": "wallet-1",
                "defi_label": "staking",
            }
        ],
    )

    PipelineService(store).rebuild_all()

    with store.connect() as con:
        events = con.execute(
            """
            select source, event_type, asset, quantity, tx_id
            from canonical_events
            order by source, event_time
            """
        ).fetchall()
        lots = con.execute(
            """
            select e.source, e.event_type, l.asset, l.quantity_total, l.cost_basis_eur_total
            from tax_lots l
            join canonical_events e on e.event_id = l.source_event_id
            order by e.source
            """
        ).fetchall()

    assert events == [
        ("helium", "mining", "IOT", Decimal("1000.000000000000000000"), None),
        ("solana_rpc", "transfer", "IOT", Decimal("980.000000000000000000"), "claim-iot-on-solana"),
    ]
    assert lots == [
        (
            "helium",
            "mining",
            "IOT",
            Decimal("1000.000000000000000000"),
            Decimal("10.000000000000000000"),
        )
    ]


def test_pipeline_keeps_solana_helium_reward_without_legacy_match_taxable(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    CsvRawImporter(store).import_rows(
        source="solana_rpc",
        filename="solana-hnt-reward.json",
        file_hash="solana-hnt-reward-no-legacy",
        rows=[
            {
                "timestamp_utc": "2026-05-07T14:53:43+00:00",
                "event_type": "token_transfer",
                "asset": "HNT",
                "quantity": "3.5",
                "side": "in",
                "tx_id": "real-hnt-reward",
                "wallet_address": "wallet-1",
                "logMessages": ["Program log: Instruction: SetCurrentRewardsWrapperV1"],
            }
        ],
    )

    PipelineService(store).rebuild_all()

    with store.connect() as con:
        event = con.execute(
            "select event_type, asset, quantity from canonical_events where tx_id = 'real-hnt-reward'"
        ).fetchone()
        lots = con.execute("select asset, quantity_total from tax_lots").fetchall()

    assert event == ("reward", "HNT", Decimal("3.500000000000000000"))
    assert lots == [("HNT", Decimal("3.500000000000000000"))]


def test_rebuild_after_import_runs_full_pipeline(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="import.csv",
            content=(
                "time,asset,amount,type,quote_asset,quote_quantity,account\n"
                "2020-12-31T23:59:00Z,EUR,10000,deposit,,,test\n"
                "2021-01-01T00:00:00Z,BTC,1,buy,EUR,10000,test\n"
                "2021-06-01T00:00:00Z,BTC,-0.5,sell,EUR,8000,test\n"
            ),
    )
    store.add_price_point(
        PricePointCreate(
            asset="BTC",
            price_eur=Decimal("16000"),
            priced_at=datetime(2021, 6, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    result = PipelineService(store).rebuild_after_import(batch.batch_id)

    assert result.imported_rows == 3
    assert result.normalized_events == 3
    assert result.skipped_raw_objects == 0
    assert result.pipeline.balance_entries == 5
    assert result.pipeline.flow_entries == 1
    assert result.pipeline.tax_lines == 1
    assert result.pipeline.allow_export is True


def test_delete_import_and_rebuild_removes_batch_effects(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="import.csv",
        content="time,asset,amount,type,quote_asset,quote_quantity,account\n"
        "2021-01-01T00:00:00Z,USDT,10,deposit,EUR,9,test\n",
    )
    service = PipelineService(store)
    service.rebuild_after_import(batch.batch_id)

    result = service.delete_import_and_rebuild(batch.batch_id)

    assert result.deleted is True
    assert result.pipeline.normalized_events == 0
    assert result.pipeline.balance_entries == 0
    assert result.pipeline.flow_entries == 0
    assert store.list_import_batches() == []


def test_delete_import_endpoint_rebuilds_pipeline(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="import.csv",
        content="time,asset,amount,type,quote_asset,quote_quantity,account\n"
        "2021-01-01T00:00:00Z,USDT,10,deposit,EUR,9,test\n",
    )
    PipelineService(store).rebuild_after_import(batch.batch_id)
    client = TestClient(create_app(store))

    response = client.delete(f"/api/v1/import/batches/{batch.batch_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["data"]["deleted"] is True
    assert body["data"]["pipeline"]["balance_entries"] == 0


def test_raw_and_canonical_trace_endpoints_expose_import_state(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    PipelineService(store).seed_demo()
    client = TestClient(create_app(store))

    raw_response = client.get("/api/v1/raw/objects")
    canonical_response = client.get("/api/v1/events/canonical")

    assert raw_response.status_code == 200
    assert canonical_response.status_code == 200
    raw_objects = raw_response.json()["data"]
    canonical_events = canonical_response.json()["data"]
    assert len(raw_objects) == 5
    assert len(canonical_events) == 5
    assert raw_objects[0]["batch_id"]
    assert canonical_events[0]["raw_object_id"]


def test_import_batch_trace_json_download_contains_raw_and_canonical(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    result = PipelineService(store).seed_demo()
    client = TestClient(create_app(store))

    response = client.get(f"/api/v1/import/batches/{result.batch_id}/trace.json")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert payload["batch"]["batch_id"] == result.batch_id
    assert len(payload["raw_objects"]) == 5
    assert len(payload["canonical_events"]) == 5


def test_tax_lines_csv_uses_acquisition_date_not_lot_id(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    PipelineService(store).seed_demo()
    client = TestClient(create_app(store))

    response = client.get("/api/v1/export/tax-lines.csv")

    assert response.status_code == 200
    assert "Datum_Kauf,Datum_Verkauf,Asset" in response.text
    assert "Steuerpflichtig,Steuerliche_Behandlung" in response.text
    assert "2021-01-01T00:00:00" in response.text
    assert "BTC" in response.text


def test_import_profiles_endpoint_lists_known_sources(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))

    response = client.get("/api/v1/import/profiles")

    assert response.status_code == 200
    sources = {profile["source"] for profile in response.json()["data"]}
    assert {"binance", "helium", "manual-csv", "pionex"}.issubset(sources)


def test_get_import_batch_endpoint_returns_metadata(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="deposit.csv",
        content="time,asset,amount,type\n2021-01-01T00:00:00Z,BTC,1,deposit\n",
    )
    client = TestClient(create_app(store))

    response = client.get(f"/api/v1/import/batches/{batch.batch_id}")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["batch_id"] == batch.batch_id
    assert data["raw_object_count"] == 1


def test_get_import_batch_endpoint_reports_missing_batch(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))

    response = client.get("/api/v1/import/batches/missing")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["data"] is None
    assert body["errors"][0]["code"] == "import_batch_not_found"


def test_prices_endpoint_lists_price_points(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.90"),
            priced_at=datetime(2021, 4, 29, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    client = TestClient(create_app(store))

    response = client.get("/api/v1/prices")

    assert response.status_code == 200
    prices = response.json()["data"]
    assert len(prices) == 1
    assert prices[0]["asset"] == "USDT"


def test_add_price_endpoint_rebuilds_pipeline(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="deposit.csv",
        content="time,asset,amount,type,account\n2021-04-28T10:00:00Z,USDT,100,deposit,pionex\n",
    )
    PipelineService(store).rebuild_after_import(batch.batch_id)
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/prices",
        json={
            "asset": "usdt",
            "price_eur": "0.90",
            "priced_at": "2021-04-29T00:00:00Z",
            "source": "manual-test",
            "confidence": "1.0",
        },
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["price"]["asset"] == "USDT"
    assert body["pipeline"]["review_issues_open"] == 0


def test_price_csv_preview_reports_invalid_rows(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/prices/import/csv/preview",
        json={
            "content": "asset,price_eur,priced_at\nMOBILE,not-a-price,2021-05-15\n",
            "default_source": "unit-test",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "warning"
    assert body["data"]["can_import"] is False
    assert body["data"]["invalid_rows"] == 1
    assert "price_eur_invalid_decimal" in body["data"]["rows"][0]["errors"]


def test_price_csv_import_rebuilds_pipeline(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="deposit.csv",
        content="time,asset,amount,type,account\n2021-05-15T10:00:00Z,MOBILE,100,deposit,wallet\n",
    )
    PipelineService(store).rebuild_after_import(batch.batch_id)
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/prices/import/csv",
        json={
            "content": "asset,price_eur,priced_at,source\nMOBILE,0.001,2021-05-15,unit-test\n",
            "default_source": "unit-test",
        },
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["imported_prices"] == 1
    assert body["pipeline"]["review_issues_open"] == 0
    prices = store.list_price_points()
    assert prices[0].asset == "MOBILE"
    assert prices[0].source == "unit-test"


def test_v1_fx_cache_import_converts_usd_prices_to_eur(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="manual-test",
            source_ref="mobile-reward",
            event_time=datetime(2024, 1, 1, 12, tzinfo=timezone.utc),
            event_type="reward",
            asset="MOBILE",
            quantity=Decimal("100"),
        )
    )
    BalanceLedgerBuilder(store).rebuild()
    v1_db = tmp_path / "v1.db"
    with sqlite3.connect(v1_db) as con:
        con.execute(
            """
            create table fx_cache (
                rate_date text,
                base_ccy text,
                quote_ccy text,
                rate text,
                source text,
                source_rate_date text,
                updated_at_utc text,
                primary key(rate_date, base_ccy, quote_ccy)
            )
            """
        )
        con.execute(
            "insert into fx_cache values (?, ?, ?, ?, ?, ?, ?)",
            ("2024-01-01", "MOBILE", "USD", "0.002", "coingecko_history", "2024-01-01", "now"),
        )
        con.execute(
            "insert into fx_cache values (?, ?, ?, ?, ?, ?, ?)",
            ("2023-12-29", "USD", "EUR", "0.91", "ecb", "2023-12-29", "now"),
        )
    client = TestClient(create_app(store))

    preview_response = client.post(
        "/api/v1/prices/import/v1-fx-cache/preview",
        json={"db_path": str(v1_db), "confidence": "1.0"},
    )
    import_response = client.post(
        "/api/v1/prices/import/v1-fx-cache",
        json={"db_path": str(v1_db), "confidence": "1.0"},
    )

    assert preview_response.status_code == 200
    assert preview_response.json()["data"]["importable_count"] == 1
    assert import_response.status_code == 200
    body = import_response.json()["data"]
    assert body["imported_prices"] == 1
    assert body["pipeline"]["review_issues_open"] == 0
    price = store.list_price_points()[0]
    assert price.asset == "MOBILE"
    assert price.price_eur == Decimal("0.001820000000000000")
    assert price.source == "v1_fx_cache:coingecko_history:usd_eur:ecb"


def test_external_price_backfill_dry_run_plans_configured_requirements(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="manual-test",
            source_ref="mobile-reward",
            event_time=datetime(2024, 1, 1, 12, tzinfo=timezone.utc),
            event_type="reward",
            asset="MOBILE",
            quantity=Decimal("100"),
        )
    )
    config = tmp_path / "prices.json"
    config.write_text(
        '{"assets":[{"symbol":"MOBILE","coingecko_id":"helium-mobile","store_keys":["MOBILE"],"aliases":["MOBILE"]}]}',
        encoding="utf-8",
    )
    v1_db = tmp_path / "v1.db"
    with sqlite3.connect(v1_db) as con:
        con.execute(
            """
            create table fx_cache (
                rate_date text,
                base_ccy text,
                quote_ccy text,
                rate text,
                source text,
                source_rate_date text,
                updated_at_utc text,
                primary key(rate_date, base_ccy, quote_ccy)
            )
            """
        )
        con.execute(
            "insert into fx_cache values (?, ?, ?, ?, ?, ?, ?)",
            ("2024-01-01", "USD", "EUR", "0.91", "ecb", "2024-01-01", "now"),
        )
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/prices/backfill/external",
        json={
            "config_path": str(config),
            "v1_fx_db_path": str(v1_db),
            "provider": "auto",
            "max_requests": 5,
            "dry_run": True,
        },
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["dry_run"] is True
    assert body["requirements_count"] == 1
    assert body["attempted"] == 1
    assert body["imported_prices"] == 0
    assert body["jobs"][0]["status"] == "planned"
    assert body["jobs"][0]["provider_id"] == "helium-mobile"


def test_external_price_backfill_asset_filter_limits_attempts(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="manual-test",
            source_ref="mobile-reward",
            event_time=datetime(2024, 1, 1, 12, tzinfo=timezone.utc),
            event_type="reward",
            asset="MOBILE",
            quantity=Decimal("100"),
        )
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="manual-test",
            source_ref="bttc-reward",
            event_time=datetime(2024, 1, 2, 12, tzinfo=timezone.utc),
            event_type="reward",
            asset="BTTC",
            quantity=Decimal("100"),
        )
    )
    config = tmp_path / "prices.json"
    config.write_text(
        """
        {
          "assets": [
            {"symbol":"MOBILE","coingecko_id":"helium-mobile","store_keys":["MOBILE"],"aliases":["MOBILE"]},
            {"symbol":"BTTC","coingecko_id":"bittorrent","store_keys":["BTTC"],"aliases":["BTTC"]}
          ]
        }
        """,
        encoding="utf-8",
    )
    v1_db = tmp_path / "v1.db"
    with sqlite3.connect(v1_db) as con:
        con.execute(
            """
            create table fx_cache (
                rate_date text,
                base_ccy text,
                quote_ccy text,
                rate text,
                source text,
                source_rate_date text,
                updated_at_utc text,
                primary key(rate_date, base_ccy, quote_ccy)
            )
            """
        )
        con.execute(
            "insert into fx_cache values (?, ?, ?, ?, ?, ?, ?)",
            ("2024-01-01", "USD", "EUR", "0.91", "ecb", "2024-01-01", "now"),
        )
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/prices/backfill/external",
        json={
            "config_path": str(config),
            "v1_fx_db_path": str(v1_db),
            "provider": "auto",
            "assets": ["bttc"],
            "max_requests": 5,
            "dry_run": True,
        },
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["requirements_count"] == 2
    assert body["asset_filter"] == ["BTTC"]
    assert body["attempted"] == 1
    assert [job["asset"] for job in body["jobs"]] == ["BTTC"]


def test_external_price_backfill_uses_first_available_following_price(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="manual-test",
            source_ref="iot-launch-claim",
            event_time=datetime(2023, 4, 20, 12, tzinfo=timezone.utc),
            event_type="reward",
            asset="IOT",
            quantity=Decimal("100"),
        )
    )
    config = tmp_path / "prices.json"
    config.write_text(
        '{"assets":[{"symbol":"IOT","coingecko_id":"helium-iot","store_keys":["IOT"],"aliases":["IOT"]}]}',
        encoding="utf-8",
    )
    v1_db = tmp_path / "v1.db"
    with sqlite3.connect(v1_db) as con:
        con.execute(
            """
            create table fx_cache (
                rate_date text,
                base_ccy text,
                quote_ccy text,
                rate text,
                source text,
                source_rate_date text,
                updated_at_utc text,
                primary key(rate_date, base_ccy, quote_ccy)
            )
            """
        )
        con.execute(
            "insert into fx_cache values (?, ?, ?, ?, ?, ?, ?)",
            ("2023-04-20", "USD", "EUR", "0.90", "ecb", "2023-04-20", "now"),
        )
        con.execute(
            "insert into fx_cache values (?, ?, ?, ?, ?, ?, ?)",
            ("2023-04-23", "USD", "EUR", "0.92", "ecb", "2023-04-23", "now"),
        )

    def fake_fetch(self, *, client, coingecko_id, date_str, provider):
        if date_str == "2023-04-23":
            return Decimal("0.50"), "defillama_coingecko_history"
        return Decimal("0"), ""

    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_price_usd", fake_fetch)
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/prices/backfill/external",
        json={
            "config_path": str(config),
            "v1_fx_db_path": str(v1_db),
            "provider": "auto",
            "max_requests": 5,
            "dry_run": False,
        },
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["imported_prices"] == 1
    assert Decimal(body["jobs"][0]["price_eur"]) == Decimal("0.46")
    price = store.latest_price_points()["IOT"]
    assert price.price_eur == Decimal("0.460000000000000000")
    assert price.priced_at.date().isoformat() == "2023-04-20"
    assert (
        price.source
        == "defillama_coingecko_history:first_available_after:2023-04-23:usd_eur:v1_fx_cache:2023-04-23"
    )


def test_current_portfolio_price_backfill_imports_live_price(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="manual-test",
            source_ref="hnt-balance",
            event_time=datetime(2026, 5, 24, 12, tzinfo=timezone.utc),
            event_type="transfer",
            asset="HNT",
            quantity=Decimal("10"),
            account="wallet",
        )
    )
    BalanceLedgerBuilder(store).rebuild()
    config = tmp_path / "prices.json"
    config.write_text(
        '{"assets":[{"symbol":"HNT","coingecko_id":"helium","store_keys":["HNT"],"aliases":["HNT"]}]}',
        encoding="utf-8",
    )

    def fake_fetch(self, client, coingecko_ids):
        assert coingecko_ids == ["helium"]
        return {"helium": Decimal("3.21")}

    monkeypatch.setattr(
        ExternalPriceBackfillService,
        "_fetch_coingecko_simple_prices_eur",
        fake_fetch,
    )
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/prices/backfill/current-portfolio",
        json={
            "config_path": str(config),
            "assets": ["HNT"],
            "max_requests": 5,
            "dry_run": False,
        },
    )

    assert response.status_code == 200
    body = response.json()["data"]
    assert body["imported_prices"] == 1
    assert body["jobs"][0]["status"] == "imported"
    assert body["jobs"][0]["price_eur"] == "3.21"
    latest = store.latest_price_points()["HNT"]
    assert latest.price_eur == Decimal("3.210000000000000000")
    assert latest.source == "coingecko:simple-price:eur"


def test_latest_prices_endpoint_lists_effective_prices(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.89"),
            priced_at=datetime(2021, 4, 28, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.90"),
            priced_at=datetime(2021, 4, 29, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    client = TestClient(create_app(store))

    response = client.get("/api/v1/prices/latest")

    assert response.status_code == 200
    prices = response.json()["data"]
    assert len(prices) == 1
    assert prices[0]["asset"] == "USDT"
    assert prices[0]["price_eur"] == "0.900000000000000000"


def test_export_readiness_endpoint_reports_status(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))

    response = client.get("/api/v1/export/readiness")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["allow_export"] is True
    assert data["max_pdf_pages_per_file"] == 100


def test_delete_price_endpoint_removes_price_and_rebuilds(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    price = store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.90"),
            priced_at=datetime(2021, 4, 29, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    client = TestClient(create_app(store))

    response = client.delete(f"/api/v1/prices/{price.price_id}")

    assert response.status_code == 200
    assert response.json()["data"] == {"price_id": price.price_id, "deleted": True}
    assert store.list_price_points() == []


def test_delete_price_endpoint_warns_for_missing_price(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))

    response = client.delete("/api/v1/prices/missing")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "warning"
    assert body["data"] == {"price_id": "missing", "deleted": False}
    assert body["warnings"][0]["code"] == "price_not_found"


def test_normalize_endpoint_reports_skipped_rows_as_warning(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="broken.csv",
        content="time,asset,note\n2021-01-01T00:00:00Z,BTC,no amount\n",
    )
    client = TestClient(create_app(store))

    response = client.post(f"/api/v1/import/batches/{batch.batch_id}/normalize")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "warning"
    assert body["data"]["skipped_raw_objects"] == 1
    assert body["warnings"][0]["code"] == "raw_objects_skipped"


def test_import_run_endpoint_reports_full_pipeline_and_warnings(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="mixed.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity,account\n"
            "2021-01-01T00:00:00Z,USDT,10,deposit,EUR,9,test\n"
            "2021-01-02T00:00:00Z,BTC,,deposit,EUR,100,test\n"
        ),
    )
    client = TestClient(create_app(store))

    response = client.post(f"/api/v1/import/batches/{batch.batch_id}/run")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "warning"
    assert body["data"]["imported_rows"] == 2
    assert body["data"]["normalized_events"] == 1
    assert body["data"]["skipped_raw_objects"] == 1
    assert body["data"]["pipeline"]["balance_entries"] == 1
    assert body["warnings"][0]["code"] == "raw_objects_skipped"


def test_csv_preview_endpoint_warns_without_persisting(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/import/csv/preview",
        json={
            "source": "pionex",
            "filename": "broken.csv",
            "content": "time,asset,note\n2021-01-01T00:00:00Z,BTC,no amount\n",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "warning"
    assert body["data"]["can_import"] is False
    assert body["data"]["missing_required_groups"] == ["quantity"]
    assert body["warnings"][0]["code"] == "missing_required_columns"
    assert store.list_import_batches() == []


def test_csv_raw_import_endpoint_blocks_invalid_preview(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/import/csv/raw",
        json={
            "source": "pionex",
            "filename": "broken.csv",
            "content": "time,asset,note\n2021-01-01T00:00:00Z,BTC,no amount\n",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["data"] is None
    assert body["errors"][0]["code"] == "missing_required_columns"
    assert store.list_import_batches() == []


def test_csv_raw_import_endpoint_warns_for_duplicate(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))
    payload = {
        "source": "pionex",
        "filename": "pionex.csv",
        "content": "time,asset,amount,type\n2021-01-01T00:00:00Z,BTC,1,deposit\n",
    }
    first = client.post("/api/v1/import/csv/raw", json=payload)

    duplicate = client.post("/api/v1/import/csv/raw", json=payload)

    assert first.status_code == 200
    assert duplicate.status_code == 200
    body = duplicate.json()
    assert body["status"] == "warning"
    assert body["data"]["batch_id"] == first.json()["data"]["batch_id"]
    assert body["warnings"][0]["code"] == "duplicate_import"
