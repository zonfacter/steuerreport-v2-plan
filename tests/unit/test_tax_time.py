from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_time import (
    TaxTimePolicyService,
    event_reporting_tax_year,
    reporting_tax_year,
    reporting_time,
    reporting_year_sql,
    reporting_year_utc_bounds,
)


def test_reporting_tax_year_uses_europe_berlin_calendar_boundary():
    value = datetime(2021, 12, 31, 23, 30, tzinfo=timezone.utc)

    assert reporting_tax_year(value) == 2022
    assert reporting_time(value).isoformat() == "2022-01-01T00:30:00+01:00"


def test_reporting_timezone_handles_cet_and_cest_transitions():
    before_spring_jump = reporting_time(datetime(2025, 3, 30, 0, 30, tzinfo=timezone.utc))
    after_spring_jump = reporting_time(datetime(2025, 3, 30, 1, 30, tzinfo=timezone.utc))
    first_autumn_0230 = reporting_time(datetime(2025, 10, 26, 0, 30, tzinfo=timezone.utc))
    second_autumn_0230 = reporting_time(datetime(2025, 10, 26, 1, 30, tzinfo=timezone.utc))

    assert before_spring_jump.isoformat() == "2025-03-30T01:30:00+01:00"
    assert after_spring_jump.isoformat() == "2025-03-30T03:30:00+02:00"
    assert first_autumn_0230.isoformat() == "2025-10-26T02:30:00+02:00"
    assert second_autumn_0230.isoformat() == "2025-10-26T02:30:00+01:00"
    assert first_autumn_0230.fold == 0
    assert second_autumn_0230.fold == 1


def test_reporting_year_bounds_are_local_midnight_expressed_in_utc():
    start, end = reporting_year_utc_bounds(2025)

    assert start == datetime(2024, 12, 31, 23, tzinfo=timezone.utc)
    assert end == datetime(2025, 12, 31, 23, tzinfo=timezone.utc)
    assert "Europe/Berlin" in reporting_year_sql("disposed_at")


def test_source_period_aggregate_preserves_documented_period_year():
    event_time = datetime(2023, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

    assert reporting_tax_year(event_time) == 2024
    assert event_reporting_tax_year(
        event_time,
        source="helium",
        event_type="mining",
        payload={"Period Start (UTC)": "01.12.23"},
    ) == 2023


def test_time_precision_audit_separates_real_shift_from_source_period_aggregate(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(source="evidence", filename="timezone-boundary.csv", file_hash="time-boundary")
    )
    raw = store.add_raw_objects(
        batch.batch_id,
        [
            RawObjectCreate(row_number=1, payload_json='{"date(UTC+0)":"2021-12-31 23:38:35"}'),
            RawObjectCreate(row_number=2, payload_json='{"Period Start (UTC)":"01.12.23"}'),
        ],
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2021, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("1"),
                quote_asset="EUR",
                quote_quantity=Decimal("10"),
                account="pionex",
            ),
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2021, 12, 31, 23, 38, 35, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("-1"),
                quote_asset="EUR",
                quote_quantity=Decimal("12"),
                account="pionex",
                raw_object_id=raw[0].raw_object_id,
            ),
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2023, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
                event_type="mining",
                asset="IOT",
                quantity=Decimal("100"),
                account="wallet",
                raw_object_id=raw[1].raw_object_id,
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    report = TaxTimePolicyService(store).audit()

    assert report.status == "satisfied"
    assert report.reporting_policy_applied is True
    assert report.boundary_events_count == 2
    assert report.reporting_year_shift_events_count == 1
    assert report.source_period_aggregate_events_count == 1
    assert report.reporting_year_shift_tax_lines_count == 1
    assert report.reporting_year_shift_tax_gain_loss_eur == Decimal("2")
    by_class = {event.classification: event for event in report.events}
    assert by_class["local_calendar_shift_required"].reporting_year == 2022
    assert by_class["source_period_aggregate_preserved"].reporting_year == 2023


def test_time_precision_audit_api(tmp_path):
    response = TestClient(create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb"))).get(
        "/api/v1/tax-methodology/time-precision-audit"
    )

    assert response.status_code == 200
    assert response.json()["data"]["policy_version"] == "de_calendar_year_v1"
    assert response.json()["data"]["reporting_policy_applied"] is True
