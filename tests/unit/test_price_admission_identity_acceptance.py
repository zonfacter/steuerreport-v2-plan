"""Supplement requested after the 92-case freeze; never edits that reference."""
import base64
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import socket
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from steuerreport_v2.api.historical_prices import build_historical_prices_router
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain import historical_prices as history


BASE = "/api/v1/prices/historical"
MINT = "Ab" + "1" * 30
PRICE = b"Synthetic price original with separately reviewed transcription."
METHOD = b"Synthetic limited observed-quote method original."


def data(response):
    assert response.status_code == 200, response.text
    return response.json()["data"]


@pytest.mark.parametrize("change", ["matching", "wrong_contract", "wrong_network"])
def test_human_attestation_must_respect_original_raw_mint(tmp_path, monkeypatch, change):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("STEUERREPORT_PRIVATE_PROFILE", str(root / "tests/fixture_profile.json"))
    monkeypatch.setenv("STEUERREPORT_STATE_DIR", str(tmp_path / "runtime"))
    monkeypatch.delenv("STEUERREPORT_PRIVATE_CONFIG_DIR", raising=False)

    def no_network(*args, **kwargs):
        pytest.fail("Supplement must not use providers or network")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    monkeypatch.setattr(history, "managed_client", no_network)
    monkeypatch.setattr(history.HistoricalPriceService, "mappings", lambda self: {
        "TOKEN000": {"asset": "TOKEN000", "coingecko_id": "synthetic-token", "defillama_id": None},
    })
    store = DuckDbStore(tmp_path / "original-mint.duckdb")
    batch = store.create_import_batch(ImportBatchCreate(source="synthetic-solana", filename="synthetic.json"))
    raw, = store.add_raw_objects(batch.batch_id, [RawObjectCreate(
        payload_json=json.dumps({"mint": MINT, "network": "solana", "decimals": 6}),
    )])
    store.add_canonical_events([CanonicalEventCreate(
        source="synthetic-solana", source_ref="original-mint-row", raw_object_id=raw.raw_object_id,
        asset="TOKEN000", quantity=Decimal("1"), event_type="transfer", account="Synthetic account",
        event_time=datetime(2025, 6, 13, 1, tzinfo=timezone.utc),
    )])
    app = FastAPI()
    app.include_router(build_historical_prices_router(store, lambda: None))
    with TestClient(app) as client:
        query = {"scope": "all_observed", "assets": ["TOKEN000"], "max_requests": 1}
        plan = data(client.post(BASE + "/plan", json=query))
        assert plan["rows"][0]["asset_identity"]["network"] == "solana"
        assert plan["rows"][0]["asset_identity"]["contract_address"] == MINT
        preview = data(client.post(BASE + "/manual-previews", json={
            "request_id": str(uuid4()), "query": query, "plan_sha256": plan["plan_sha256"],
            "asset": "TOKEN000", "price_date": "2025-06-13", "price_value": "125.50",
            "price_currency": "EUR", "priced_at": "2025-06-13T00:30:00Z",
            "price_evidence": {
                "filename": "price.bin", "media_type": "application/octet-stream",
                "source_name": "Synthetic original", "source_observed_at": "2025-06-14T10:00:00Z",
                "content_base64": base64.b64encode(PRICE).decode(),
            },
        }))
        assert preview["rows"][0]["asset_identity"]["contract_address"] == MINT
        data(client.post(BASE + f"/previews/{preview['id']}/apply", json={
            "preview_sha256": preview["preview_sha256"], "actor": "Synthetic importer",
            "confirm_prices": True, "confirm_recalculation": True,
        }))
        binding, = preview["price_bindings"]
        point_root = BASE + f"/previews/{preview['id']}/prices/{binding['price_id']}"
        identity = {"asset": "TOKEN000", "network": "solana", "contract": MINT, "decimals": 6}
        if change == "wrong_contract":
            identity["contract"] = "Cd" + "2" * 30
        elif change == "wrong_network":
            identity["network"] = "ethereum"
        with store.connect() as con:
            before = {table: con.execute(f"select * from {table} order by all").fetchall()
                      for table in ("price_ledger", "review_decisions", "raw_objects", "canonical_events")}
        response = client.post(point_root + "/admission-previews", json={
            "request_id": str(uuid4()), "preview_sha256": preview["preview_sha256"],
            "price_fingerprint": binding["price_fingerprint"], "valuation_at": "2025-06-13T01:00:00Z",
            "identity": identity,
            "observation": {
                "identity": identity, "quote_currency": "EUR", "value": "125.50", "kind": "observed_quote",
                "observed_at": "2025-06-13T00:30:00Z", "published_at": "2025-06-13T00:31:00Z",
                "evidence_sha256": hashlib.sha256(PRICE).hexdigest(),
                "locator": "synthetic document, line 1", "source": "Synthetic original",
            },
            "method": {
                "method_id": "synthetic-original-mint-method", "version": 1, "kind": "observed_quote",
                "timezone": "UTC", "availability_rule": "available_at_cutoff",
                "evidence_sha256": hashlib.sha256(METHOD).hexdigest(),
            },
            "method_original": {"filename": "method.txt", "media_type": "text/plain",
                                "content_base64": base64.b64encode(METHOD).decode()},
            "actor": "Synthetic reviewer", "rationale": "Respect original mint; only human limited admission.",
        })
        if change == "matching":
            report = data(response)
            assert report["can_apply"] is True and report["status"] == "prepared"
            assert re.fullmatch(r"[a-f0-9]{64}", report["validation_policy_sha256"])
            assert report["assessment"]["strict_eligible"] is False
        elif response.status_code == 200:
            report = data(response)
            assert report["can_apply"] is False and report["assessment"]["strict_eligible"] is False
            assert report["status"] in {"blocked", "rejected"}
        else:
            assert response.status_code in {409, 422}, response.text
        with store.connect() as con:
            after = {table: con.execute(f"select * from {table} order by all").fetchall() for table in before}
        assert after == before
