from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup


def test_lookup_prefers_primary_same_day_price_over_later_derived_quote(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    primary = store.add_price_point(
        PricePointCreate(
            asset="IOT",
            price_eur=Decimal("0.0012"),
            priced_at=datetime(2024, 10, 6, 0, 0),
            source="defillama_coingecko_history:usd_eur:v1_fx_cache",
            confidence=Decimal("1"),
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="IOT",
            price_eur=Decimal("0.0000004"),
            priced_at=datetime(2024, 10, 6, 5, 47),
            source="derived:event_quote",
            confidence=Decimal("0.85"),
        )
    )

    price = HistoricalPriceLookup(store).at_or_before(
        "IOT",
        datetime(2024, 10, 6, 6, 0),
    )

    assert price is not None
    assert price.price_id == primary.price_id


def test_lookup_can_require_non_derived_primary_price(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("240972.922372"),
            priced_at=datetime(2023, 4, 25, 4, 17),
            source="derived:event_quote",
            confidence=Decimal("0.80"),
        )
    )

    lookup = HistoricalPriceLookup(store)

    assert lookup.at_or_before(
        "SOL",
        datetime(2023, 4, 25, 5, 0),
    ) is not None
    assert (
        lookup.at_or_before(
            "SOL",
            datetime(2023, 4, 25, 5, 0),
            allow_derived=False,
        )
        is None
    )


def test_explain_preserves_selected_point_and_missing_provenance(tmp_path):
    store = DuckDbStore(tmp_path / "prices.duckdb")
    event_time = datetime(2025, 7, 1, 12, tzinfo=timezone.utc)
    fixtures = [
        (event_time - timedelta(days=1642), "1", "fixture:old", "different_utc_day"),
        (event_time + timedelta(seconds=1), "2", "fixture:future", "future"),
        (event_time, "0", "fixture:zero", "non_positive"),
        (event_time, "-1", "fixture:negative", "non_positive"),
        (event_time, "3", "  DeRiVeD:event_quote", "derived_disallowed"),
        (event_time - timedelta(hours=1), "7", "fixture:primary", None),
    ]
    reasons = {}
    for at, price, source, reason in fixtures:
        point = store.add_price_point(PricePointCreate(
            asset="HNT", price_eur=Decimal(price), priced_at=at, source=source))
        reasons[point.price_id] = reason
    lookup = HistoricalPriceLookup(store)
    decision = lookup.explain("hnt", event_time, allow_derived=False)

    assert decision.policy_id == "historical_same_utc_day_not_after_event"
    assert decision.policy_version == 1
    assert decision.asset == "HNT"
    assert decision.event_time == event_time
    assert decision.status == "selected"
    assert decision.rejection_reason is None
    assert decision.selected_price == lookup.at_or_before("HNT", event_time, allow_derived=False)
    assert decision.selected_price.source == "fixture:primary"
    assert decision.selected_price.price_eur == Decimal("7")
    assert decision.candidate_count == 6
    assert not decision.candidates_truncated
    assert {item.price.price_id: item.rejection_reason for item in decision.candidates} == reasons
    assert sum(item.selected for item in decision.candidates) == 1
    assert all(item.provenance_status == "not_linked" for item in decision.candidates)
    assert decision.model_dump(mode="json")["selected_price"]["source"] == "fixture:primary"


@pytest.mark.parametrize("candidate_limit,expected_count", [(0, 0), (1, 1), (50, 50), (5000, 55)])
def test_explain_limits_do_not_change_selection(tmp_path, candidate_limit, expected_count):
    store = DuckDbStore(tmp_path / "prices.duckdb")
    at = datetime(2025, 7, 1, 12)
    store.add_price_points([PricePointCreate(
        asset="HNT", priced_at=at - timedelta(seconds=i),
        price_eur=Decimal("7"), source=f"fixture:{i}",
    ) for i in range(55)])
    lookup = HistoricalPriceLookup(store)
    decision = lookup.explain("HNT", at, candidate_limit=candidate_limit)
    assert decision.selected_price == lookup.at_or_before("HNT", at)
    assert len(decision.candidates) == expected_count
    assert decision.candidate_count == 55
    assert decision.candidates_truncated is (expected_count < 55)
    if expected_count:
        assert decision.candidates[0].selected


def test_explain_missing_and_fiat_do_not_invent_fx_evidence(tmp_path):
    lookup = HistoricalPriceLookup(DuckDbStore(tmp_path / "prices.duckdb"))
    at = datetime(2025, 7, 1, 12)
    missing = lookup.explain("USD", at)
    assert missing.status == "missing"
    assert missing.rejection_reason == "no_candidates"
    assert missing.selected_price is None
    assert missing.candidates == []
    eur = lookup.explain("eur", at)
    assert eur.status == "fiat"
    assert eur.selected_price.price_eur == Decimal("1")
    assert eur.selected_price.priced_at == at.replace(tzinfo=timezone.utc)
    assert eur.candidates[0].provenance_status == "synthetic_fiat_identity"


@pytest.mark.parametrize("event_time,price_time,accepted", [
    ("2025-07-02T00:30:00+02:00", "2025-07-01T22:00:00+00:00", True),
    ("2025-07-02T00:30:00+02:00", "2025-07-02T00:00:00+02:00", True),
    ("2025-07-02T00:30:00+02:00", "2025-07-01T21:00:00-02:00", False),
    ("2025-07-02T00:00:00+00:00", "2025-07-01T23:59:59+00:00", False),
    ("2024-03-01T00:00:00+00:00", "2024-02-29T23:59:59+00:00", False),
])
def test_lookup_uses_utc_date_not_local_calendar_date(tmp_path, event_time, price_time, accepted):
    store = DuckDbStore(tmp_path / "prices.duckdb")
    store.add_price_point(PricePointCreate(
        asset="HNT", price_eur=Decimal("7"), source="fixture",
        priced_at=datetime.fromisoformat(price_time)))
    lookup = HistoricalPriceLookup(store)
    at = datetime.fromisoformat(event_time)
    assert (lookup.at_or_before("HNT", at) is not None) is accepted
    decision = lookup.explain("HNT", at)
    assert decision.status == ("selected" if accepted else "missing")
    if not accepted:
        assert decision.rejection_reason == "no_eligible_candidate"
        assert decision.candidates[0].rejection_reason in {"future", "different_utc_day"}


def test_previous_day_primary_does_not_override_same_day_derived_price(tmp_path):
    store = DuckDbStore(tmp_path / "prices.duckdb")
    at = datetime(2025, 7, 1, 12)
    store.add_price_point(PricePointCreate(
        asset="HNT", price_eur=Decimal("99"), priced_at=at - timedelta(days=1), source="primary"))
    derived = store.add_price_point(PricePointCreate(
        asset="HNT", price_eur=Decimal("7"), priced_at=at, source="derived:event_quote"))
    lookup = HistoricalPriceLookup(store)
    assert lookup.at_or_before("HNT", at).price_id == derived.price_id
    assert lookup.at_or_before("HNT", at, allow_derived=False) is None


def test_explain_hard_cap_keeps_full_candidate_count_and_selected_price(tmp_path):
    store = DuckDbStore(tmp_path / "prices.duckdb")
    at = datetime(2025, 7, 1, 12)
    store.add_price_points([PricePointCreate(
        asset="HNT", priced_at=at - timedelta(seconds=i),
        price_eur=Decimal("7"), source=f"fixture:{i}",
    ) for i in range(1005)])
    lookup = HistoricalPriceLookup(store)
    decision = lookup.explain("HNT", at, candidate_limit=5000)
    assert len(decision.candidates) == 1000
    assert decision.candidate_count == 1005
    assert decision.candidates_truncated
    assert decision.selected_price == lookup.at_or_before("HNT", at)
    assert decision.candidates[0].selected


def test_source_name_alone_never_establishes_synthetic_fiat_identity(tmp_path):
    store = DuckDbStore(tmp_path / "prices.duckdb")
    at = datetime(2025, 7, 1, 12)
    point = store.add_price_point(PricePointCreate(
        asset="HNT", priced_at=at, price_eur=Decimal("7"), source="fiat:EUR"))
    decision = HistoricalPriceLookup(store).explain("HNT", at)
    assert decision.status == "selected"
    assert decision.selected_price.price_id == point.price_id
    assert decision.candidates[0].provenance_status == "not_linked"
