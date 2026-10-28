from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json

import pytest

from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.historical_prices import HistoricalPriceQuery, PriceMapping
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.contracts.token_conversion import TokenConversionConfig
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.asset_identity import AssetIdentityIndex, identity_from_payload
from steuerreport_v2.domain.historical_prices import HistoricalPriceService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.token_conversion import TokenConversionService, event_binding


def event(store, ref, asset, quantity, payload, *, day=2, kind="transfer", quote=None, quote_quantity=None):
    batch = store.create_import_batch(ImportBatchCreate(source="synthetic"))
    raw = store.add_raw_object(batch.batch_id, RawObjectCreate(payload_json=json.dumps(payload, sort_keys=True)))
    value = store.add_canonical_event(CanonicalEventCreate(source="synthetic", source_ref=ref,
        account="isolated", raw_object_id=raw.raw_object_id, event_type=kind, asset=asset,
        quantity=Decimal(quantity), event_time=datetime(2025, 1, day, 12, tzinfo=timezone.utc),
        quote_asset=quote, quote_quantity=Decimal(quote_quantity) if quote_quantity else None))
    return value, raw


def conversion_fixture(tmp_path, monkeypatch):
    config = tmp_path / "configs"
    monkeypatch.setenv("STEUERREPORT_PRIVATE_CONFIG_DIR", str(config))
    config.mkdir()
    evidence = b"Synthetic primary evidence: OLD to NEW at 100 to 1, same economic asset."
    (config / "conversion-evidence.txt").write_bytes(evidence)
    store = DuckDbStore(tmp_path / "identity.duckdb")
    event(store, "buy", "OLD", "100", {}, day=1, kind="trade", quote="EUR", quote_quantity="200")
    source, raw_source = event(store, "out", "OLD", "-100", {"conversion_kind": "redenomination"})
    target, raw_target = event(store, "in", "NEW", "1", {"conversion_kind": "redenomination"})
    mapping = dict(mapping_id="synthetic-100-to-1", enabled=True, kind="redenomination",
        source_event_id=source.event_id, target_event_id=target.event_id,
        source_event_sha256=event_binding(source), target_event_sha256=event_binding(target),
        source_raw_sha256=hashlib.sha256(raw_source.payload_json.encode()).hexdigest(),
        target_raw_sha256=hashlib.sha256(raw_target.payload_json.encode()).hexdigest(),
        ratio_numerator="1", ratio_denominator="100", tax_treatment="carry_original_basis_and_date",
        actor="Synthetic reviewer", rationale="Synthetic evidence explicitly establishes the 100 to 1 conversion.",
        evidence_ref="conversion-evidence.txt", evidence_sha256=hashlib.sha256(evidence).hexdigest(),
        acknowledge_same_economic_asset=True,
        acknowledge_no_automatic_tax_approval=True)
    path = config / "token_conversion_mappings.json"
    return store, path, mapping


def test_g18_bound_contract_is_used_without_symbol_guess(tmp_path):
    store = DuckDbStore(tmp_path / "identity.duckdb")
    contract = "0x" + "aB" * 20
    event(store, "reward", "SAME", "1.25", {"network": "eth", "contract_address": contract,
        "decimals": 6, "amount_raw": "1250000"}, kind="reward")
    plan = HistoricalPriceService(store).plan(HistoricalPriceQuery(year=2025, scope="all_observed"))
    row = plan["rows"][0]
    assert row["provider_id"] == "ethereum:" + contract.lower()
    assert row["asset_identity"]["decimals"] == 6
    assert row["status"] == "planned"


def test_g18_chain_collision_blocks_plan_and_gate_even_with_existing_price(tmp_path):
    store = DuckDbStore(tmp_path / "identity.duckdb")
    for chain in ("ethereum", "polygon"):
        event(store, chain, "SAME", "1", {"network": chain, "contract_address": "0x" + "a" * 40}, kind="reward")
    store.add_price_point(PricePointCreate(asset="SAME", price_eur=Decimal("10"),
        priced_at=datetime(2025, 1, 2, 0, tzinfo=timezone.utc), source="synthetic:legacy"))
    assert AssetIdentityIndex(store).problems == {"SAME": "asset_identity_conflict"}
    row = HistoricalPriceService(store).plan(HistoricalPriceQuery(scope="all_observed"))["rows"][0]
    assert row["status"] == "blocked" and row["price_eur"] is None
    assert any(i.code == "asset_identity_conflict" and i.blocks_export for i in ReviewService(store).gate().issues)


@pytest.mark.parametrize("decimals,raw", [(5, "1250000"), (None, "1250000"), (True, None), (6.0, None)])
def test_g18_invalid_units_never_become_a_price_identity(decimals, raw):
    with pytest.raises(ValueError):
        identity_from_payload(dict(network="ethereum", contract_address="0x" + "a" * 40,
            decimals=decimals, amount_raw=raw), role="asset", source="synthetic", quantity=Decimal("1.25"))


def test_g18_solana_case_preserved_and_mapping_roundtrips():
    mint = "So11111111111111111111111111111111111111112"
    identity = identity_from_payload({"mint": mint}, role="asset", source="solana_rpc", quantity=Decimal("1"))
    assert identity.contract == mint
    mapping = PriceMapping(asset="SAME", network="eth", contract_address="0x" + "aB" * 20, decimals=6)
    assert PriceMapping.model_validate_json(mapping.model_dump_json()) == mapping
    assert mapping.network == "ethereum"


def test_g19_no_automatic_neutral_conversion(tmp_path, monkeypatch):
    store, path, mapping = conversion_fixture(tmp_path, monkeypatch)
    report = TokenConversionService(store).report()
    assert not report["ready"] and len(report["issues"]) == 2
    assert any(i.code == "conversion_evidence_mapping_required" for i in ReviewService(store).gate().issues)


def test_g19_ratio_preserves_basis_date_and_quantity(tmp_path, monkeypatch):
    store, path, mapping = conversion_fixture(tmp_path, monkeypatch)
    path.write_text(json.dumps({"schema_version": 1, "mappings": [mapping]}))
    assert not TokenConversionService(store).report()["issues"]
    result = WalletFifoPreviewService(store).replay()
    lots = [lot for lot in result.open_lots if lot.asset == "NEW"]
    assert len(lots) == 1
    assert lots[0].quantity_remaining == Decimal("1")
    assert lots[0].cost_basis_eur_total == Decimal("200")
    assert lots[0].acquired_at.day == 1
    global_result = TaxService(store).preview_global_fifo()
    converted = [lot for lot in global_result.lots if lot.asset == "NEW"]
    assert len(converted) == 1 and not global_result.unmatched
    assert converted[0].quantity_remaining == Decimal("1")
    assert converted[0].cost_basis_eur_total == Decimal("200")
    assert converted[0].acquired_at.day == 1


def test_g19_changed_primary_evidence_invalidates_run_binding(tmp_path, monkeypatch):
    from steuerreport_v2.domain.token_conversion import config_binding
    from steuerreport_v2.domain.ai_changes import _fingerprint
    store, path, mapping = conversion_fixture(tmp_path, monkeypatch)
    path.write_text(json.dumps({"schema_version": 1, "mappings": [mapping]}))
    before = config_binding()
    with store.connect() as con:
        preview_before = _fingerprint(con)
    path.with_name("conversion-evidence.txt").write_text("Changed primary evidence")
    assert config_binding() != before
    with store.connect() as con:
        assert _fingerprint(con) != preview_before
    assert not TokenConversionService(store).report()["ready"]


@pytest.mark.parametrize("change,reason", [
    ({"ratio_numerator": "2"}, "conversion_quantity_ratio_mismatch"),
    ({"source_event_sha256": "0" * 64}, "conversion_event_binding_stale"),
    ({"source_raw_sha256": "0" * 64}, "conversion_raw_binding_stale"),
    ({"enabled": False}, "conversion_not_enabled"),
    ({"evidence_sha256": "0" * 64}, "conversion_evidence_missing_or_changed"),
])
def test_g19_stale_or_unproven_conversion_stays_blocked(tmp_path, monkeypatch, change, reason):
    store, path, mapping = conversion_fixture(tmp_path, monkeypatch)
    path.write_text(json.dumps({"schema_version": 1, "mappings": [{**mapping, **change}]}))
    report = TokenConversionService(store).report()
    assert not report["ready"]
    assert report["issues"][0]["reason"] == reason


@pytest.mark.parametrize("value", [False, "true", 1])
def test_g19_explicit_human_acknowledgment_cannot_be_coerced(tmp_path, monkeypatch, value):
    _, _, mapping = conversion_fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError):
        TokenConversionConfig.model_validate({"schema_version": 1, "mappings": [{**mapping, "acknowledge_same_economic_asset": value}]})
