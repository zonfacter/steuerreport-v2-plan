"""Zusaetzliche Koordinatorproben fuer persistente Phasenwahrheit."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore


@pytest.mark.parametrize("kind", ["current_portfolio", "historical"])
@pytest.mark.parametrize("bad_kind", [None, "SYNTHETIC_SECRET_KIND"])
def test_wrong_journal_kind_is_unknown_not_not_found(tmp_path, caplog, kind, bad_kind):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    request_id = str(uuid4())
    identity = {"request_id": request_id}
    if kind == "historical":
        identity["operation_kind"] = kind
    key = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    reserve = store.reserve_current_price_backfill if kind == "current_portfolio" else store.reserve_historical_price_backfill
    assert reserve(key)
    with store.connect() as con:
        con.execute("update current_price_backfill_requests set operation_kind=?", [bad_kind])
        before = con.execute("select * from current_price_backfill_requests").fetchall()
    endpoint = "current-portfolio" if kind == "current_portfolio" else "external"
    response = TestClient(create_app(store)).post(
        f"/api/v1/prices/backfill/{endpoint}/status", json={"request_id": request_id},
    )
    assert response.status_code == 500 and response.json()["data"]["status"] == "unknown"
    assert "SYNTHETIC_SECRET_KIND" not in response.text + caplog.text
    with store.connect() as con:
        assert con.execute("select * from current_price_backfill_requests").fetchall() == before
    assert not store.list_price_points()


@pytest.mark.parametrize("kind", ["current_portfolio", "historical"])
@pytest.mark.parametrize("forgery", ["missing_pipeline", "completed_unknown_effects", "failed_completed_effects"])
def test_final_journal_rejects_contradictory_pipeline_evidence(tmp_path, kind, forgery):
    store = DuckDbStore(tmp_path / "synthetic.duckdb")
    key = "a" * 64
    reserve = store.reserve_current_price_backfill if kind == "current_portfolio" else store.reserve_historical_price_backfill
    assert reserve(key)
    now = datetime.now(timezone.utc)
    prices = store.prepare_price_backfill(key, kind, [PricePointCreate(
        asset="SYNTHETIC", price_eur=Decimal("2"), priced_at=now, source="synthetic",
    )])
    store.mark_price_backfill_pipeline_started(key, kind)
    pipeline = {"normalized_events": 0, "balance_entries": 0, "flow_entries": 0,
                "tax_lines": 0, "review_issues_open": 0, "allow_export": False}
    result = {"operation_kind": kind, "configured_assets": ["SYNTHETIC"], "asset_filter": [],
              "planned_jobs": 1, "attempted": 1, "imported_prices": 1, "skipped": 0, "failed": 0,
              "dry_run": False, "jobs": [], "pipeline": pipeline, "stored_price_ids": [prices[0].price_id],
              "pipeline_status": "completed", "pipeline_effects": "completed", "result_journal_status": "recorded"}
    if kind == "current_portfolio":
        result.update(portfolio_assets_count=1, priced_at=now.isoformat())
    else:
        result["requirements_count"] = 1
    if forgery == "missing_pipeline":
        result["pipeline"] = None
    elif forgery == "completed_unknown_effects":
        result["pipeline_effects"] = "unknown_or_partial"
    else:
        result.update(pipeline_status="failed", pipeline_effects="completed", pipeline=None)
    before = store.price_backfill_operation_record(key, kind)
    record = store.record_current_price_backfill if kind == "current_portfolio" else store.record_historical_price_backfill
    with pytest.raises(Exception):
        record(key, json.dumps(result))
    assert store.price_backfill_operation_record(key, kind) == before
    assert [price.price_id for price in store.list_price_points()] == [prices[0].price_id]
