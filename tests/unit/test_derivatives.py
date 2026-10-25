from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.derivatives import DerivativesManager
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.review import ReviewService


def test_derivatives_manager_values_derivative_cash_events(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    event_time = datetime(2024, 1, 2, 12, tzinfo=timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.90"),
            priced_at=event_time,
            source="manual-test",
        )
    )
    event = store.add_canonical_event(
        CanonicalEventCreate(
            source="bitget",
            source_ref="futures-row-1",
            event_time=event_time,
            event_type="derivative",
            asset="USDT",
            quantity=Decimal("-10"),
            account="bitget-futures",
        )
    )

    result = DerivativesManager(store).rebuild()

    assert result.summary.derivative_lines_count == 1
    assert result.summary.realized_pnl_eur == Decimal("-9.000000000000000000")
    assert result.summary.missing_price_count == 0
    assert result.lines[0].event_id == event.event_id
    assert result.lines[0].price_source == "manual-test"
    assert result.lines[0].value_eur == Decimal("-9.000000000000000000")
    assert DerivativesManager(store).list_lines()[0].value_eur == Decimal(
        "-9.000000000000000000"
    )


def test_derivatives_manager_marks_missing_prices_and_review_blocks(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="bitget",
            source_ref="futures-row-2",
            event_time=datetime(2024, 1, 2, 12, tzinfo=timezone.utc),
            event_type="derivative",
            asset="USD_UNKNOWN",
            quantity=Decimal("5"),
        )
    )

    result = DerivativesManager(store).rebuild()

    assert result.summary.derivative_lines_count == 1
    assert result.summary.realized_pnl_eur == Decimal("0")
    assert result.summary.missing_price_count == 1
    assert result.lines[0].price_source is None
    gate = ReviewService(store).gate()
    assert gate.allow_export is False
    assert "derivative_missing_prices" in {issue.code for issue in gate.issues}


def test_derivatives_manager_resolves_unique_truncated_wallet_alias(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = "133iWieuwSsyRYopuykZFnxs5qJJW1AiRgXqH43S9rJxU6WUW8v"
    short_wallet = "133iWieuw...xU6WUW8v"
    event_time = datetime(2024, 1, 2, 12, tzinfo=timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.90"),
            priced_at=event_time,
            source="manual-test",
        )
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="bitget",
            source_ref="futures-row-short",
            event_time=event_time,
            event_type="derivative",
            asset="USDT",
            quantity=Decimal("2"),
            account=short_wallet,
        )
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="manual-csv",
            source_ref="wallet-ref",
            event_time=event_time,
            event_type="transfer",
            asset="HNT",
            quantity=Decimal("0"),
            account=wallet,
        )
    )

    result = DerivativesManager(store).rebuild()

    assert result.lines[0].account == wallet


def test_pipeline_and_api_expose_derivative_lines(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    event_time = datetime(2024, 1, 2, 12, tzinfo=timezone.utc)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.91"),
            priced_at=event_time,
            source="manual-test",
        )
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="bitget",
            source_ref="futures-row-3",
            event_time=event_time,
            event_type="derivative",
            asset="USDT",
            quantity=Decimal("2.5"),
        )
    )
    client = TestClient(create_app(store))

    pipeline = PipelineService(store).rebuild_all()
    lines_response = client.get("/api/v1/derivatives/lines")
    summary_response = client.get("/api/v1/derivatives/summary")
    readiness_response = client.get("/api/v1/export/readiness")
    csv_response = client.get("/api/v1/export/derivative-lines.csv")

    assert pipeline.derivative_lines == 1
    assert lines_response.status_code == 200
    assert lines_response.json()["data"][0]["value_eur"] == "2.275000000000000000"
    assert summary_response.json()["data"]["derivative_lines_count"] == 1
    readiness = readiness_response.json()["data"]
    assert readiness["derivative_lines_count"] == 1
    assert readiness["derivative_realized_pnl_eur"] == "2.275000000000000000"
    assert csv_response.status_code == 200
    assert "Ergebnis_EUR" in csv_response.text
    assert "bitget" in csv_response.text
