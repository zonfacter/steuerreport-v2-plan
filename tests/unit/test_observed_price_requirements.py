from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json

import duckdb
import pytest

from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.historical_prices import HistoricalPriceQuery
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.observed_price_requirements import SOL_MINT, observed_requirements


# Synthetische, nur syntaktisch plausible Adressen, keine privaten Fixtures.
MINT_A = "Ab" + "1" * 30
MINT_B = "Cd" + "2" * 30
UNKNOWN = "SOLANA_" + "A" * 64
DAY = "2024-06-02"


@pytest.fixture
def store(tmp_path):
    result = DuckDbStore(tmp_path / "synthetic.duckdb")
    with result.connect():
        pass
    return result


def event(store, asset="HNT", *, at=DAY + "T12:00:00+00:00", mint=None,
          payload=None, source="solana_rpc", kind="transfer", quantity="1", **kwargs):
    if mint is not None:
        payload = {"mint": mint, **(payload or {})}
    raw_id = None
    if payload is not None:
        batch = store.create_import_batch(ImportBatchCreate(source=source))
        raw_id = store.add_raw_object(
            batch.batch_id, RawObjectCreate(payload_json=json.dumps(payload))
        ).raw_object_id
    return store.add_canonical_event(CanonicalEventCreate(
        asset=asset, quantity=Decimal(quantity), event_type=kind, source=source,
        event_time=datetime.fromisoformat(at), raw_object_id=raw_id, **kwargs,
    ))


def price(store, *, asset="HNT", at=DAY + "T00:00:00+00:00", value="3.25", source="manual:test"):
    return store.add_price_point(PricePointCreate(
        asset=asset, price_eur=Decimal(value), priced_at=datetime.fromisoformat(at), source=source,
    ))


def plan(store, *, mappings=None, risks=None, **kwargs):
    return observed_requirements(store, HistoricalPriceQuery(**kwargs), mappings or {}, risks or {})


def metadata(store, mint, symbol, risk):
    with store.connect() as con:
        con.execute("""
            insert into jupiter_token_metadata_cache
                (mint, symbol, risk_status, source, discovered_sources_json, refreshed_at)
            values (?, ?, ?, 'synthetic', '[]', '2024-06-01')
        """, [mint, symbol, risk])


def test_transfers_hnt_iot_and_native_sol_are_observed(store):
    event(store, mint=MINT_A, fee_asset="SOL", fee_quantity=Decimal("-0.001"))
    event(store, asset="IOT", mint=MINT_B, quantity="-2")
    rows = {row["asset"]: row for row in plan(store)}
    assert set(rows) == {"HNT", "IOT", "SOL"}
    for asset, mint in (("HNT", MINT_A), ("IOT", MINT_B), ("SOL", SOL_MINT)):
        assert rows[asset]["provider_id"] == "solana:" + mint
        assert rows[asset]["mint"] == mint
        assert rows[asset]["status"] == "planned"
        assert rows[asset]["event_types"] == ["transfer"]
        assert rows[asset]["event_count"] == 1


def test_all_roles_count_each_event_once_without_netting_quantities(store):
    event(store, mint=MINT_A, quote_asset="HNT", quote_quantity=Decimal("2"),
          fee_asset="HNT", fee_quantity=Decimal("0.01"))
    event(store, mint=MINT_A, quantity="-1", kind="unknown")
    row, = plan(store)
    assert row["event_count"] == 2
    assert row["event_types"] == ["transfer", "unknown"]
    assert row["years"] == [2024]
    assert row["event_year_counts"] == {"2024": 2}


def test_raw_mint_is_only_asset_role_and_never_quote_or_fee_identity(store):
    event(store, mint=MINT_A, quote_asset="IOT", quote_quantity=Decimal("2"),
          fee_asset="FEE", fee_quantity=Decimal("0.01"))
    rows = {row["asset"]: row for row in plan(store)}
    assert rows["HNT"]["mint"] == MINT_A
    for asset in ("IOT", "FEE"):
        assert rows[asset]["mint"] is None
        assert rows[asset]["mints"] == []
        assert rows[asset]["reason"] == "solana_mint_missing"


def test_unknown_hash_can_only_use_exact_original_mint(store):
    event(store, asset=UNKNOWN, mint=MINT_A)
    row, = plan(store)
    assert row["provider_id"] == "solana:" + MINT_A
    assert row["status"] == "planned"
    row, = plan(store, provider="coingecko", mappings={UNKNOWN: {"coingecko_id": "guessed-symbol"}})
    assert row["status"] == "blocked"
    assert row["provider_id"] is None


def test_uppercase_address_alias_alone_does_not_prove_coingecko_mint_binding(store):
    event(store, asset=UNKNOWN, mint=MINT_A)
    row, = plan(store, provider="coingecko", mappings={
        MINT_A.upper(): {"coingecko_id": "ambiguous-address-alias"},
    })
    assert row["status"] == "blocked" and row["provider_id"] is None
    row, = plan(store, provider="coingecko", mappings={
        MINT_A: {"coingecko_id": "exact-address-binding"},
    })
    assert row["status"] == "planned" and row["provider_id"] == "exact-address-binding"


def test_exact_cased_address_mapping_precedes_normalized_address_alias(store):
    event(store, asset=UNKNOWN, mint=MINT_A)
    row, = plan(store, provider="coingecko", mappings={
        "solana:" + MINT_A: {"coingecko_id": "exact-address-binding"},
        MINT_A.upper(): {"coingecko_id": "ambiguous-address-alias"},
    })
    assert row["status"] == "planned" and row["provider_id"] == "exact-address-binding"


@pytest.mark.parametrize("source", ["solana_rpc", "manual"])
def test_unknown_without_original_mint_cannot_be_rescued_by_configuration(store, source):
    event(store, asset=UNKNOWN, source=source)
    row, = plan(store, mappings={UNKNOWN: {"defillama_id": "solana:" + MINT_A}})
    assert row["reason"] == "solana_mint_missing"


@pytest.mark.parametrize("mint", ["short", "A" * 31, "A" * 45, "0" * 32, "O" * 32,
                                   "I" * 32, "l" * 32, " " + MINT_A, MINT_A + " ",
                                   11111111111111111111111111111111, [MINT_A], ""])
def test_original_mint_must_be_a_plausible_base58_string(store, mint):
    event(store, asset=UNKNOWN, payload={"mint": mint})
    row, = plan(store)
    assert row["reason"] == "solana_mint_invalid"


@pytest.mark.parametrize("mint", ["A" * 32, "B" * 44])
def test_plausible_mint_length_boundaries(store, mint):
    event(store, asset=UNKNOWN, mint=mint)
    row, = plan(store)
    assert row["status"] == "planned"
    assert row["provider_id"] == "solana:" + mint


@pytest.mark.parametrize("provider", ["defillama", "coingecko"])
def test_mismatched_mapping_blocks_both_providers_even_with_a_price(store, provider):
    event(store, mint=MINT_A)
    price(store)
    row, = plan(store, provider=provider, mappings={"HNT": {
        "coingecko_id": "helium", "defillama_id": "solana:" + MINT_A.upper(),
    }})
    assert row["status"] == "blocked"
    assert row["reason"] == "price_mapping_mint_mismatch"
    assert row["price_eur"] is None


@pytest.mark.parametrize("address_key", [MINT_A, MINT_A.upper()])
@pytest.mark.parametrize("provider", ["defillama", "coingecko"])
def test_exact_address_mapping_wins_over_symbol_mapping(store, address_key, provider):
    event(store, mint=MINT_A)
    mappings = {
        "HNT": {"coingecko_id": "wrong-alias", "defillama_id": "solana:" + MINT_B},
        address_key: {"coingecko_id": "exact-test-token", "defillama_id": "solana:" + MINT_A},
    }
    row, = plan(store, mappings=mappings, provider=provider)
    assert row["status"] == "planned"
    assert row["provider_id"] == ("exact-test-token" if provider == "coingecko" else "solana:" + MINT_A)


def test_same_symbol_different_mints_in_other_year_blocks_global_identity(store):
    event(store, mint=MINT_A)
    event(store, mint=MINT_B, at="2025-02-03T12:00:00+00:00")
    row, = plan(store, year=2024)
    assert row["status"] == "blocked"
    assert row["reason"] == "asset_mint_conflict"
    assert row["mints"] == [MINT_A, MINT_B]
    assert row["event_count"] == 1
    assert row["years"] == [2024]


def test_distinct_case_variants_of_a_mint_are_not_collapsed(store):
    event(store, mint=MINT_A)
    event(store, mint=MINT_A.upper(), at="2023-01-02T12:00:00+00:00")
    row, = plan(store, year=2024)
    assert row["reason"] == "asset_mint_conflict"


@pytest.mark.parametrize("source", ["binance", "manual"])
@pytest.mark.parametrize("provider", ["defillama", "coingecko"])
def test_known_cex_manual_assets_without_mint_use_explicit_mapping(store, source, provider):
    event(store, asset="BTC", source=source)
    row, = plan(store, provider=provider, mappings={"BTC": {"coingecko_id": "bitcoin"}})
    assert row["status"] == "planned"
    assert row["provider_id"] == ("bitcoin" if provider == "coingecko" else "coingecko:bitcoin")


def test_known_solana_asset_without_raw_mint_is_blocked_despite_mapping(store):
    event(store)
    row, = plan(store, mappings={"HNT": {"defillama_id": "solana:" + MINT_A}})
    assert row["reason"] == "solana_mint_missing"


def test_nested_mint_is_not_original_top_level_identity(store):
    event(store, asset=UNKNOWN, payload={"raw_transaction": {"mint": MINT_A}})
    row, = plan(store)
    assert row["reason"] == "solana_mint_missing"


def test_native_sol_rejects_conflicting_original_identity(store):
    event(store, asset="SOL", mint=MINT_A)
    row, = plan(store)
    assert row["reason"] == "solana_mint_identity_mismatch"


def test_same_day_positive_price_at_first_event_is_visible_coverage(store):
    event(store, mint=MINT_A)
    point = price(store, at=DAY + "T12:00:00+00:00")
    row, = plan(store)
    assert row["status"] == "covered" and row["reason"] is None
    assert Decimal(row["price_eur"]) == point.price_eur
    assert row["priced_at"] == DAY + "T12:00:00+00:00"
    assert row["source"] == "manual:test"


@pytest.mark.parametrize("at,value", [("2023-06-02T00:00:00+00:00", "100"),
    ("2024-06-01T23:59:59+00:00", "100"), (DAY + "T12:00:01+00:00", "100"),
    (DAY + "T00:00:00+00:00", "0"), (DAY + "T00:00:00+00:00", "-1")])
def test_old_later_and_nonpositive_prices_do_not_cover(store, at, value):
    event(store, mint=MINT_A)
    price(store, at=at, value=value)
    row, = plan(store)
    assert row["status"] == "planned"
    assert row["price_eur"] is None and row["priced_at"] is None and row["source"] is None


def test_same_day_primary_is_preferred_over_later_derived_quote(store):
    event(store, mint=MINT_A)
    price(store)
    price(store, at=DAY + "T10:00:00+00:00", value="4", source="derived:event_quote")
    row, = plan(store)
    assert row["source"] == "manual:test"
    assert Decimal(row["price_eur"]) == Decimal("3.25")


def test_nonpositive_quote_does_not_hide_earlier_valid_same_day_coverage(store):
    event(store, mint=MINT_A)
    price(store)
    price(store, at=DAY + "T11:00:00+00:00", value="0")
    row, = plan(store)
    assert row["status"] == "covered" and Decimal(row["price_eur"]) == Decimal("3.25")


def test_coverage_needs_no_fetch_mapping_for_non_solana_asset(store):
    event(store, asset="BTC", source="manual")
    price(store, asset="BTC")
    row, = plan(store)
    assert row["status"] == "covered" and row["provider_id"] is None


def test_year_boundary_uses_berlin_but_keeps_global_first_event_on_utc_day(store):
    event(store, mint=MINT_A, at="2023-12-31T22:30:00+00:00")
    event(store, mint=MINT_A, at="2023-12-31T23:30:00+00:00", kind="reward")
    price(store, at="2023-12-31T23:00:00+00:00")
    row, = plan(store, year=2024)
    assert row["price_date"] == "2023-12-31"
    assert row["first_event_at"] == "2023-12-31T22:30:00+00:00"
    assert row["years"] == [2024] and row["event_count"] == 1
    assert row["event_types"] == ["reward"]
    assert row["event_year_counts"] == {"2024": 1}
    assert row["status"] == "planned"
    row, = plan(store)
    assert row["years"] == [2023, 2024] and row["event_count"] == 2
    assert row["event_year_counts"] == {"2023": 1, "2024": 1}


def test_helium_mining_period_start_preserves_existing_source_year(store):
    event(store, source="helium", kind="mining", at="2023-12-31T23:59:59+00:00",
          payload={"Period Start (UTC)": "2023-12-01"})
    event(store, source="helium", kind="mining", at="2023-12-31T23:59:59+00:00")
    older, = plan(store, year=2023)
    newer, = plan(store, year=2024)
    assert older["event_year_counts"] == {"2023": 1}
    assert newer["event_year_counts"] == {"2024": 1}
    row, = plan(store)
    assert row["years"] == [2023, 2024]
    assert row["event_count"] == 2


def test_zero_and_null_roles_are_not_observations_or_mint_conflicts(store):
    event(store, mint=MINT_A)
    event(store, mint=MINT_B, quantity="0", quote_asset="ZERO", quote_quantity=Decimal("0"),
          fee_asset="NULL_FEE", fee_quantity=None)
    event(store, asset="NULL_QUOTE", quantity="0", quote_asset="BTC", quote_quantity=None)
    row, = plan(store)
    assert row["asset"] == "HNT" and row["event_count"] == 1
    assert row["mints"] == [MINT_A] and row["status"] == "planned"


def test_eur_is_fixed_reference_and_never_fetchable(store):
    event(store, asset="EUR", source="manual")
    price(store, asset="EUR", value="100")
    row, = plan(store, mappings={"EUR": {"coingecko_id": "not-eur"}})
    assert row["status"] == "covered" and row["provider_id"] is None
    assert row["price_eur"] == "1" and row["source"] == "fiat:EUR"
    assert row["priced_at"] == row["first_event_at"]


@pytest.mark.parametrize("key", ["HNT", MINT_A, MINT_A.upper()])
def test_supplied_spam_risk_blocks_even_when_price_exists(store, key):
    event(store, mint=MINT_A)
    price(store)
    row, = plan(store, risks={key: "spam_review"})
    assert row["status"] == "blocked" and row["reason"] == "token_risk_spam_review"


@pytest.mark.parametrize("symbol", [None, "DIFFERENT", "HNT"])
def test_exact_mint_metadata_spam_blocks_even_with_positive_symbol_review(store, symbol):
    event(store, asset=UNKNOWN, mint=MINT_A)
    metadata(store, MINT_A, symbol, "spam_review")
    metadata(store, MINT_B, UNKNOWN, "verified")
    row, = plan(store, risks={UNKNOWN: "verified"})
    assert row["reason"] == "token_risk_spam_review"


def test_metadata_symbol_aggregation_is_conservative_across_mints(store):
    event(store, mint=MINT_A)
    metadata(store, MINT_A, "HNT", "verified")
    metadata(store, MINT_B, "hnt", "spam_review")
    row, = plan(store, risks={"HNT": "verified"})
    assert row["reason"] == "token_risk_spam_review"


def test_metadata_mint_comparison_is_case_sensitive(store):
    event(store, asset=UNKNOWN, mint=MINT_A)
    metadata(store, MINT_A.upper(), None, "spam_review")
    row, = plan(store)
    assert row["status"] == "planned"


def test_asset_filter_and_missing_year(store):
    event(store, mint=MINT_A)
    event(store, asset="IOT", mint=MINT_B)
    row, = plan(store, assets=["iot"])
    assert row["asset"] == "IOT"
    assert plan(store, year=2022) == []


def test_empty_inventory(store):
    assert plan(store) == []


def test_today_is_not_fetchable_without_coverage(store):
    today = datetime.now(timezone.utc).date().isoformat()
    event(store, mint=MINT_A, at=today + "T00:00:00+00:00")
    row, = plan(store)
    assert row["reason"] == "future_date"


def test_function_is_read_only_and_does_not_modify_input_mappings(store):
    event(store, mint=MINT_A)
    mappings = {"HNT": {"coingecko_id": "synthetic-token", "defillama_id": "solana:" + MINT_A}}
    risks = {"HNT": "review"}
    before_inputs = deepcopy((mappings, risks))
    before_db = hashlib.sha256(store.path.read_bytes()).hexdigest()

    class ReadOnlyStore:
        @contextmanager
        def connect(self):
            with duckdb.connect(str(store.path), read_only=True) as con:
                yield con

    rows = observed_requirements(ReadOnlyStore(), HistoricalPriceQuery(), mappings, risks)
    assert rows[0]["status"] == "planned"
    assert hashlib.sha256(store.path.read_bytes()).hexdigest() == before_db
    assert (mappings, risks) == before_inputs
