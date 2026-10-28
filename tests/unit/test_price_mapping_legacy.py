from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from steuerreport_v2.api.historical_prices import build_historical_prices_router
from steuerreport_v2.contracts.admin import AdminSettingWrite
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.historical_prices import HistoricalPriceQuery, PriceMapping
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.external_price_backfill import ExternalPriceBackfillService
from steuerreport_v2.domain.historical_prices import HistoricalPriceService
from steuerreport_v2.paths import resolve_project_path


MINT = "Ab" + "1" * 30
OTHER_MINT = "Cd" + "2" * 30
STORED = {"stored_mapping": True}
BASE = "/api/v1/prices/historical"


@pytest.mark.parametrize("asset", [MINT.upper(), MINT, "LEGACY_TOKEN"])
@pytest.mark.parametrize("missing", [{}, {"solana_mint": None}])
def test_stored_defillama_binding_uses_original_id_not_normalized_asset(asset, missing):
    payload = {"asset": asset, "defillama_id": "solana:" + MINT, **missing}
    mapping = PriceMapping.model_validate_json(json.dumps(payload), context=STORED)
    assert mapping.asset == asset.upper()
    assert mapping.solana_mint == MINT
    assert mapping.defillama_id == "solana:" + MINT
    assert PriceMapping.model_validate_json(mapping.model_dump_json(), context=STORED) == mapping


@pytest.mark.parametrize("asset", [MINT.upper(), MINT])
@pytest.mark.parametrize("missing", [{}, {"solana_mint": None}])
def test_stored_coingecko_only_never_infers_original_mint_from_asset(asset, missing):
    mapping = PriceMapping.model_validate_json(json.dumps({
        "asset": asset, "coingecko_id": "legacy-token", **missing,
    }), context=STORED)
    assert mapping.solana_mint is None
    assert PriceMapping.model_validate_json(mapping.model_dump_json(), context=STORED) == mapping


@pytest.mark.parametrize("mint", ["A" * 32, "B" * 44])
def test_stored_defillama_mint_length_boundaries(mint):
    mapping = PriceMapping.model_validate_json(json.dumps({
        "asset": "TOKEN", "defillama_id": "solana:" + mint,
    }), context=STORED)
    assert mapping.solana_mint == mint


@pytest.mark.parametrize("identifier", [
    "solana:short", "solana:" + "A" * 31, "solana:" + "A" * 45,
    *["solana:" + char * 32 for char in "0OIl"],
    "ethereum:" + MINT, "SOLANA:" + MINT, "coingecko:legacy-token",
])
def test_stored_mapping_does_not_infer_from_invalid_or_non_solana_id(identifier):
    mapping = PriceMapping.model_validate_json(json.dumps({
        "asset": MINT.upper(), "defillama_id": identifier,
    }), context=STORED)
    assert mapping.solana_mint is None
    assert mapping.defillama_id == identifier


@pytest.mark.parametrize("context", [None, STORED])
def test_explicit_mint_is_never_overwritten_even_when_it_conflicts(context):
    mapping = PriceMapping.model_validate_json(json.dumps({
        "asset": MINT, "defillama_id": "solana:" + MINT, "solana_mint": OTHER_MINT,
    }), context=context)
    assert mapping.solana_mint == OTHER_MINT
    assert PriceMapping.model_validate_json(mapping.model_dump_json(), context=STORED) == mapping


@pytest.mark.parametrize("context", [None, STORED])
@pytest.mark.parametrize("mint", ["", "short", "0" * 32, "A" * 45])
def test_invalid_explicit_mint_is_rejected_not_replaced(context, mint):
    with pytest.raises(ValidationError):
        PriceMapping.model_validate_json(json.dumps({
            "asset": MINT, "defillama_id": "solana:" + MINT, "solana_mint": mint,
        }), context=context)


@pytest.fixture
def setup(tmp_path):
    store = DuckDbStore(tmp_path / "mapping.duckdb")
    batch = store.create_import_batch(ImportBatchCreate(source="solana_rpc"))
    raw = store.add_raw_object(batch.batch_id, RawObjectCreate(payload_json=json.dumps({"mint": MINT})))
    store.add_canonical_event(CanonicalEventCreate(
        source="solana_rpc", asset=MINT.upper(), quantity=Decimal("1"),
        event_time=datetime(2024, 6, 2, 12, tzinfo=timezone.utc),
        event_type="transfer", raw_object_id=raw.raw_object_id,
    ))
    app = FastAPI()
    app.include_router(build_historical_prices_router(store, lambda: None))
    return store, TestClient(app)


def snapshot(store):
    with store.connect() as con:
        return {
            table: con.execute(f"select * from {table}").fetchall()
            for table in ("admin_settings", "canonical_events", "raw_objects", "price_ledger")
        }


@pytest.mark.parametrize("provider", ["defillama", "coingecko"])
@pytest.mark.parametrize("binding", ["defillama", "coingecko_only", "explicit_conflict"])
def test_legacy_reload_in_both_services_is_read_only_and_keeps_identity_guards(setup, monkeypatch, provider, binding):
    store, client = setup
    payload = {"asset": MINT.upper(), "coingecko_id": "legacy-token"}
    if binding != "coingecko_only":
        payload["defillama_id"] = "solana:" + MINT
    if binding == "explicit_conflict":
        payload["solana_mint"] = OTHER_MINT
    stored_json = json.dumps(payload)
    store.write_admin_settings_batch([
        AdminSettingWrite(key="price.mapping." + MINT.upper(), value_json=stored_json),
    ], [])
    before = snapshot(store)
    contexts = []
    validate_json = PriceMapping.model_validate_json

    def recorded_validation(cls, value, **kwargs):
        contexts.append(kwargs.get("context"))
        return validate_json(value, **kwargs)

    monkeypatch.setattr(PriceMapping, "model_validate_json", classmethod(recorded_validation))
    config = resolve_project_path("configs/crypto_price_sources.json")
    config_sha = hashlib.sha256(config.read_bytes()).hexdigest()
    reloaded_store = DuckDbStore(store.path)
    service = HistoricalPriceService(reloaded_store)
    mapping = service.mappings()[MINT.upper()]
    expected_mint = OTHER_MINT if binding == "explicit_conflict" else MINT if binding == "defillama" else None
    assert mapping["solana_mint"] == expected_mint
    loaded = ExternalPriceBackfillService(reloaded_store)._load_assets(str(config))[-1]
    assert loaded.symbol == MINT.upper()
    assert loaded.defillama_id == payload.get("defillama_id")
    assert loaded.coingecko_id == payload["coingecko_id"]
    response = client.get(BASE + "/mappings")
    assert response.status_code == 200
    assert response.json()["data"][MINT.upper()] == mapping
    row, = service.plan(HistoricalPriceQuery(scope="all_observed", provider=provider))["rows"]
    if binding == "explicit_conflict":
        assert row["status"] == "blocked" and row["reason"] == "price_mapping_mint_mismatch"
    elif binding == "coingecko_only" and provider == "coingecko":
        assert row["status"] == "blocked" and row["provider_id"] is None
    else:
        assert row["status"] == "planned" and row["reason"] is None
        assert row["provider_id"] == ("legacy-token" if provider == "coingecko" else "solana:" + MINT)
    assert snapshot(store) == before
    assert len(contexts) >= 4 and all(context == STORED for context in contexts)
    assert hashlib.sha256(config.read_bytes()).hexdigest() == config_sha
    assert not store.list_review_decisions() and not service.root.exists()


@pytest.mark.parametrize("explicit", [False, True])
def test_new_api_mapping_preserves_raw_or_explicit_mint_after_save_reload(setup, explicit):
    store, client = setup
    payload = {"asset": MINT.upper() if explicit else MINT, "coingecko_id": "new-token"}
    if explicit:
        payload["solana_mint"] = MINT
    response = client.put(BASE + "/mappings", json=payload)
    assert response.status_code == 200
    saved = response.json()["data"]
    assert saved["asset"] == MINT.upper() and saved["solana_mint"] == MINT
    assert PriceMapping.model_validate_json(json.dumps(saved), context=STORED).solana_mint == MINT
    service = HistoricalPriceService(DuckDbStore(store.path))
    assert service.mappings()[MINT.upper()] == {**saved, "origin": "operator"}
    assert client.put(BASE + "/mappings", json=saved).json()["data"] == saved
    row, = service.plan(HistoricalPriceQuery(scope="all_observed", provider="coingecko"))["rows"]
    assert row["status"] == "planned" and row["provider_id"] == "new-token"
    assert not store.list_price_points() and not store.list_review_decisions()


@pytest.mark.parametrize("provider", ["defillama", "coingecko"])
def test_legacy_defillama_binding_does_not_bypass_spam_guard(setup, provider):
    store, _ = setup
    store.write_admin_settings_batch([AdminSettingWrite(
        key="price.mapping." + MINT.upper(), value_json=json.dumps({
            "asset": MINT.upper(), "defillama_id": "solana:" + MINT, "coingecko_id": "legacy-token",
        }),
    )], [])
    with store.connect() as con:
        con.execute("""insert into jupiter_token_metadata_cache
            (mint, symbol, risk_status, source, discovered_sources_json, refreshed_at)
            values (?, null, 'spam_review', 'synthetic', '[]', '2024-06-01')""", [MINT])
    before = snapshot(store)
    row, = HistoricalPriceService(DuckDbStore(store.path)).plan(
        HistoricalPriceQuery(scope="all_observed", provider=provider),
    )["rows"]
    assert row["status"] == "blocked" and row["reason"] == "token_risk_spam_review"
    assert snapshot(store) == before
