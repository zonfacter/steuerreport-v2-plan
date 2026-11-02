from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.imports import ImportAssistantRequest
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.import_assistant import ImportAssistantService


def test_import_assistant_preview_detects_assets_years_and_price_needs(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_price_point(
        PricePointCreate(
            asset="BTC",
            price_eur=Decimal("50000"),
            priced_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    preview = ImportAssistantService(store).preview(
        ImportAssistantRequest(
            source="binance",
            filename="assistant.csv",
            content=(
                "time,asset,amount,type,quote_asset,quote_quantity,account\n"
                "2026-01-01T00:00:00Z,BTC,0.1,buy,EUR,5000,Spot\n"
            ),
        )
    )

    assert preview.can_execute is True
    assert preview.tax_impact.estimated_new_rows == 1
    assert preview.tax_impact.estimated_normalizable_rows == 1
    assert preview.tax_impact.detected_assets == ["BTC", "EUR"]
    assert preview.tax_impact.detected_years == [2026]
    assert {item.asset: item.latest_price_available for item in preview.price_needs} == {
        "BTC": True,
        "EUR": True,
    }
    assert preview.current_state is not None
    assert preview.estimated_state is not None
    assert preview.current_state.raw_objects == 0
    assert preview.estimated_state.raw_objects == 1
    assert preview.estimated_state.import_batches == preview.current_state.import_batches + 1
    assert preview.execution_plan is not None
    assert preview.execution_plan.writes_database is True
    assert preview.execution_plan.will_rebuild_pipeline is True
    assert preview.execution_plan.trace_url_template == "/api/v1/import/batches/{batch_id}/trace.json"


def test_import_assistant_preview_reports_blocked_execution_plan_without_writes(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    preview = ImportAssistantService(store).preview(
        ImportAssistantRequest(
            source="binance",
            import_mode="api",
            filename="api",
        )
    )

    assert preview.can_execute is False
    assert preview.current_state is not None
    assert preview.estimated_state == preview.current_state
    assert preview.execution_plan is not None
    assert preview.execution_plan.writes_database is False
    assert preview.execution_plan.affected_tables == []
    assert [item.endpoint for item in preview.linked_preflights] == [
        "/api/v1/sources/binance/earn-history-preflight",
        "/api/v1/sources/binance/earn-history-api-preview?since=2025-01-01&max_pages=2&max_records=500",
        "/api/v1/sources/binance/earn-history-harvest/import",
    ]
    assert preview.linked_preflights[1].external_requests is True


def test_import_assistant_onchain_preview_links_solana_preflights(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    preview = ImportAssistantService(store).preview(
        ImportAssistantRequest(
            source="solana_wallet",
            import_mode="onchain",
        )
    )

    assert preview.can_execute is False
    assert [item.endpoint for item in preview.linked_preflights] == [
        "/api/v1/import/solscan/token-preflight",
        "/api/v1/import/solscan/rpc-probe",
        "/api/v1/import/solscan/evidence-trace",
    ]
    assert preview.linked_preflights[0].writes_database is False
    assert preview.linked_preflights[1].external_requests is True
    assert preview.linked_preflights[2].writes_database is False


def test_import_assistant_v1_cache_is_unverified_and_direct_import_blocked(tmp_path):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    preview = ImportAssistantService(store).preview(ImportAssistantRequest(source="v1", import_mode="v1_cache"))
    assert preview.can_execute is False and "gesperrt" in preview.blocked_reason
    assert preview.execution_plan.writes_database is False
    link, = preview.linked_preflights
    assert link.endpoint == "/api/v1/prices/import/v1-fx-cache/preview"
    assert link.writes_database is True and link.external_requests is False
    assert "unverbindliche" in link.purpose and "kaltem Store" in link.purpose
    assert "gesperrt" in link.next_step and "manuell belegen" in link.next_step


def test_import_assistant_execute_imports_and_runs_pipeline(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_price_point(
        PricePointCreate(
            asset="BTC",
            price_eur=Decimal("50000"),
            priced_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    result = ImportAssistantService(store).execute(
        ImportAssistantRequest(
            source="binance",
            filename="assistant.csv",
            content=(
                "time,asset,amount,type,quote_asset,quote_quantity,account\n"
                "2026-01-01T00:00:00Z,BTC,0.1,deposit,,,Spot\n"
            ),
        )
    )

    assert result.batch.raw_object_count == 1
    assert result.run.imported_rows == 1
    assert result.run.pipeline.balance_entries >= 1


def test_import_assistant_api_routes(tmp_path):
    client = TestClient(create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb")))

    response = client.post(
        "/api/v1/import/assistant/preview",
        json={
            "source": "binance",
            "filename": "assistant.csv",
            "content": (
                "time,asset,amount,type,account\n"
                "2026-01-01T00:00:00Z,BTC,0.1,deposit,Spot\n"
            ),
        },
    )

    assert response.status_code == 200
    assert response.json()["data"]["source"] == "binance"
