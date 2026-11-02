import logging
from contextlib import nullcontext
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.pipeline import PipelineResult
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.external_price_backfill import ExternalPriceBackfillService
from steuerreport_v2.domain.historical_fx import FxReference
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.valuation import PriceCoverageService


def test_pipeline_exception_does_not_disclose_canary_in_api_or_log(tmp_path, monkeypatch, caplog):
    store = DuckDbStore(tmp_path / "isolated.duckdb")
    store.add_canonical_event(CanonicalEventCreate(
        source="synthetic", source_ref="reward", event_time=datetime(2024, 1, 1, 12, tzinfo=timezone.utc),
        event_type="reward", asset="SYNTH", quantity=Decimal("1"),
    ))
    config = tmp_path / "assets.json"
    config.write_text('{"assets":[{"symbol":"SYNTH","coingecko_id":"synthetic","aliases":["SYNTH"]}]}')
    monkeypatch.setattr("steuerreport_v2.domain.external_price_backfill.managed_client", lambda **kwargs: nullcontext(object()))
    monkeypatch.setattr(ExternalPriceBackfillService, "_usd_eur_reference", lambda self, *args: FxReference(
        Decimal("1"), date(2024, 1, 1), "USD", "EUR", Decimal("1"), "synthetic",
    ))
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_price_usd", lambda self, **kwargs: (Decimal("2"), "synthetic"))
    canary = "SYNTHETIC_SECRET_CANARY_49"
    def fail(self):
        raise RuntimeError(f"/private/synthetic-receipt-123 token={canary}")
    monkeypatch.setattr(PipelineService, "rebuild_all", fail)
    caplog.set_level(logging.ERROR, logger="steuerreport_v2.domain.external_price_backfill")

    response = TestClient(create_app(store)).post(
        "/api/v1/prices/backfill/external",
        json={"config_path": str(config), "v1_fx_db_path": str(tmp_path / "unused"), "dry_run": False},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "warning"
    result = response.json()["data"]
    assert result["pipeline_status"] == "failed"
    assert result["pipeline_effects"] == "unknown_or_partial"
    with store.connect() as con:
        assert con.execute("select price_id from price_ledger").fetchone()[0] == result["stored_price_ids"][0]
    assert canary not in response.text
    assert "/private/synthetic-receipt-123" not in response.text
    records = [r for r in caplog.records if r.name == "steuerreport_v2.domain.external_price_backfill"]
    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert records[0].exc_info is None
    assert records[0].exc_text is None
    assert records[0].stack_info is None
    assert records[0].getMessage() == "Historical price backfill pipeline failed after price storage"
    assert canary not in caplog.text
    assert "/private/synthetic-receipt-123" not in caplog.text
    assert "Traceback" not in caplog.text


def test_partial_pipeline_and_repeat_are_observable_not_idempotent(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "isolated.duckdb")
    store.add_canonical_event(CanonicalEventCreate(
        source="synthetic", source_ref="reward", event_time=datetime(2024, 1, 1, 12, tzinfo=timezone.utc),
        event_type="reward", asset="SYNTH", quantity=Decimal("2"),
    ))
    old = store.add_price_point(PricePointCreate(
        asset="OLD", price_eur=Decimal("3"), priced_at=datetime(2023, 1, 1, tzinfo=timezone.utc),
        source="synthetic-existing",
    ))
    config = tmp_path / "assets.json"
    config.write_text('{"assets":[{"symbol":"SYNTH","coingecko_id":"synthetic","aliases":["SYNTH"]}]}')
    requirements = PriceCoverageService(store).requirements()
    # Freeze the same plan to model overlapping requests or a stale retry.
    monkeypatch.setattr(PriceCoverageService, "requirements", lambda self: requirements)
    monkeypatch.setattr("steuerreport_v2.domain.external_price_backfill.managed_client", lambda **kwargs: nullcontext(object()))
    monkeypatch.setattr(ExternalPriceBackfillService, "_usd_eur_reference", lambda self, *args: FxReference(
        Decimal("0.9"), date(2024, 1, 1), "USD", "EUR", Decimal("0.9"), "synthetic",
    ))
    calls = []
    def fetch(self, **kwargs):
        calls.append(kwargs["date_str"])
        return Decimal("2"), "synthetic-provider"
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_price_usd", fetch)
    def partial_failure(self):
        with self.store.connect() as con:
            con.execute("create table if not exists synthetic_pipeline_effect (value integer)")
            con.execute("insert into synthetic_pipeline_effect values (1)")
        raise RuntimeError("synthetic pipeline failure")
    monkeypatch.setattr(PipelineService, "rebuild_all", partial_failure)
    with store.connect() as con:
        before = con.execute("select price_id, asset, price_eur, source from price_ledger order by price_id").fetchall()
        events_before = con.execute("select count(*) from canonical_events").fetchone()[0]
    client = TestClient(create_app(store))
    payload = {"config_path": str(config), "v1_fx_db_path": str(tmp_path / "unused"), "dry_run": False}

    first = client.post("/api/v1/prices/backfill/external", json=payload)
    assert first.status_code == 200
    body = first.json()
    assert body["status"] == "warning"
    assert body["warnings"][0]["code"] == "price_backfill_pipeline_failed"
    result = body["data"]
    assert result["pipeline_status"] == "failed"
    assert result["pipeline_effects"] == "unknown_or_partial"
    assert result["pipeline"] is None
    assert result["imported_prices"] == 1
    assert len(result["stored_price_ids"]) == 1
    with store.connect() as con:
        after = con.execute("select price_id, asset, price_eur, source from price_ledger order by price_id").fetchall()
        assert [row for row in after if row[0] == old.price_id] == before
        assert {row[0] for row in after} - {row[0] for row in before} == set(result["stored_price_ids"])
        assert con.execute("select count(*) from canonical_events").fetchone()[0] == events_before
        assert con.execute("select count(*) from synthetic_pipeline_effect").fetchone()[0] == 1

    second = client.post("/api/v1/prices/backfill/external", json=payload).json()["data"]
    assert second["pipeline_status"] == "failed"
    assert set(second["stored_price_ids"]).isdisjoint(result["stored_price_ids"])
    with store.connect() as con:
        assert con.execute("select count(*) from price_ledger where asset='SYNTH'").fetchone()[0] == 2
        assert con.execute("select count(*) from synthetic_pipeline_effect").fetchone()[0] == 2
    assert calls == ["2024-01-01", "2024-01-01"]


def test_pipeline_completed_and_no_work_contract(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "isolated.duckdb")
    store.add_canonical_event(CanonicalEventCreate(
        source="synthetic", source_ref="reward", event_time=datetime(2024, 1, 1, 12, tzinfo=timezone.utc),
        event_type="reward", asset="SYNTH", quantity=Decimal("1"),
    ))
    config = tmp_path / "assets.json"
    config.write_text('{"assets":[{"symbol":"SYNTH","coingecko_id":"synthetic","aliases":["SYNTH"]}]}')
    monkeypatch.setattr("steuerreport_v2.domain.external_price_backfill.managed_client", lambda **kwargs: nullcontext(object()))
    monkeypatch.setattr(ExternalPriceBackfillService, "_usd_eur_reference", lambda self, *args: FxReference(
        Decimal("1"), date(2024, 1, 1), "USD", "EUR", Decimal("1"), "synthetic",
    ))
    calls = []
    def fetch(self, **kwargs):
        calls.append(kwargs["date_str"])
        return Decimal("2"), "synthetic"
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_price_usd", fetch)
    monkeypatch.setattr(PipelineService, "rebuild_all", lambda self: PipelineResult(
        normalized_events=0, balance_entries=0, flow_entries=0, tax_lines=0, review_issues_open=0, allow_export=False,
    ))
    client = TestClient(create_app(store))
    payload = {"config_path": str(config), "v1_fx_db_path": str(tmp_path / "unused")}
    preview = client.post("/api/v1/prices/backfill/external", json={**payload, "dry_run": True}).json()["data"]
    assert preview["pipeline_status"] == preview["pipeline_effects"] == "not_started"
    assert preview["stored_price_ids"] == []
    result = client.post("/api/v1/prices/backfill/external", json={**payload, "dry_run": False}).json()
    assert result["status"] == "ok"
    assert result["data"]["pipeline_status"] == result["data"]["pipeline_effects"] == "completed"
    with store.connect() as con:
        assert con.execute("select price_id from price_ledger").fetchone()[0] == result["data"]["stored_price_ids"][0]
    repeated = client.post("/api/v1/prices/backfill/external", json={**payload, "dry_run": False}).json()["data"]
    assert repeated["stored_price_ids"] == []
    assert repeated["pipeline_status"] == "not_started"
    assert calls == ["2024-01-01"]


@pytest.mark.parametrize("insert_before_failure", [False, True], ids=["before-insert", "after-insert"])
def test_store_exception_has_unknown_state_without_canary(tmp_path, monkeypatch, caplog, insert_before_failure):
    store = DuckDbStore(tmp_path / "isolated.duckdb")
    store.add_canonical_event(CanonicalEventCreate(
        source="synthetic", source_ref="reward", event_time=datetime(2024, 1, 1, 12, tzinfo=timezone.utc),
        event_type="reward", asset="SYNTH", quantity=Decimal("1"),
    ))
    config = tmp_path / "assets.json"
    config.write_text('{"assets":[{"symbol":"SYNTH","coingecko_id":"synthetic","aliases":["SYNTH"]}]}')
    monkeypatch.setattr("steuerreport_v2.domain.external_price_backfill.managed_client", lambda **kwargs: nullcontext(object()))
    monkeypatch.setattr(ExternalPriceBackfillService, "_usd_eur_reference", lambda self, *args: FxReference(
        Decimal("1"), date(2024, 1, 1), "USD", "EUR", Decimal("1"), "synthetic",
    ))
    monkeypatch.setattr(ExternalPriceBackfillService, "_fetch_price_usd", lambda self, **kwargs: (Decimal("2"), "synthetic"))
    original_add = store.add_price_points
    requirements = PriceCoverageService(store).requirements()
    monkeypatch.setattr(PriceCoverageService, "requirements", lambda self: requirements)
    canary = "SYNTHETIC_STORAGE_SECRET_CANARY_49"
    def fail_store(prices):
        if insert_before_failure:
            original_add(prices)
        raise RuntimeError(f"/private/synthetic-receipt-456 token={canary}")
    monkeypatch.setattr(store, "add_price_points", fail_store)
    monkeypatch.setattr(PipelineService, "rebuild_all", lambda self: (_ for _ in ()).throw(AssertionError("unexpected pipeline")))
    caplog.set_level(logging.ERROR)
    with store.connect() as con:
        assert con.execute("select count(*) from price_ledger").fetchone()[0] == 0
    response = TestClient(create_app(store)).post(
        "/api/v1/prices/backfill/external",
        json={"config_path": str(config), "v1_fx_db_path": str(tmp_path / "unused"), "dry_run": False},
    )
    assert response.status_code == 500
    body = response.json()
    assert body["status"] == "error"
    assert body["errors"][0]["code"] == "price_backfill_storage_unknown"
    assert body["data"] == {"storage_status": "unknown", "pipeline_status": "not_started"}
    assert canary not in response.text and "/private/synthetic-receipt-456" not in response.text
    assert canary not in caplog.text and "/private/synthetic-receipt-456" not in caplog.text
    assert "Traceback" not in caplog.text
    records = [r for r in caplog.records if r.name == "steuerreport_v2.domain.external_price_backfill"]
    assert len(records) == 1
    assert records[0].getMessage() == "Historical price backfill storage failed; storage state unknown"
    assert records[0].exc_info is None and records[0].exc_text is None and records[0].stack_info is None
    with store.connect() as con:
        assert con.execute("select count(*) from price_ledger").fetchone()[0] == int(insert_before_failure)
    from steuerreport_v2.domain.external_price_backfill import HistoricalBackfillStorageUnknown
    with pytest.raises(HistoricalBackfillStorageUnknown) as raised:
        ExternalPriceBackfillService(store).run(
            config_path=str(config), v1_fx_db_path=str(tmp_path / "unused"), provider="auto",
            assets_filter=[], max_requests=1, timeout_seconds=3, confidence=Decimal("1"), dry_run=False,
        )
    assert raised.value.__context__ is None
    assert raised.value.__cause__ is None
    assert canary not in str(raised.value)
