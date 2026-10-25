from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.transfers import TransferCandidateService


def test_transfer_candidates_score_txid_time_and_accounts(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    out_time = datetime(2024, 1, 1, 12, tzinfo=timezone.utc)
    store.add_canonical_event(
        CanonicalEventCreate(
            source="binance",
            source_ref="withdraw-1",
            event_time=out_time,
            event_type="transfer",
            asset="SOL",
            quantity=Decimal("-10"),
            tx_id="tx-1",
            account="Binance",
        )
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="solana",
            source_ref="deposit-1",
            event_time=out_time + timedelta(minutes=20),
            event_type="transfer",
            asset="SOL",
            quantity=Decimal("10"),
            tx_id="tx-1",
            account="Solana Wallet",
        )
    )

    report = TransferCandidateService(store).candidates(asset="SOL")

    assert report.candidates_count == 1
    candidate = report.candidates[0]
    assert candidate.status == "strong_candidate"
    assert candidate.score >= 85
    assert "TX-ID stimmt ueberein" in candidate.reasons
    assert "Zeitreihenfolge plausibel" in candidate.reasons
    assert candidate.warnings == []


def test_transfer_candidates_warn_for_reverse_time_and_mismatching_txid(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    out_time = datetime(2024, 1, 1, 12, tzinfo=timezone.utc)
    store.add_canonical_event(
        CanonicalEventCreate(
            source="exchange-a",
            event_time=out_time,
            event_type="transfer",
            asset="HNT",
            quantity=Decimal("-5"),
            tx_id="tx-out",
            account="A",
        )
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="exchange-b",
            event_time=out_time - timedelta(minutes=5),
            event_type="transfer",
            asset="HNT",
            quantity=Decimal("5"),
            tx_id="tx-in",
            account="B",
        )
    )

    report = TransferCandidateService(store).candidates()

    assert report.candidates_count == 1
    candidate = report.candidates[0]
    assert candidate.status != "strong_candidate"
    assert "Eingang liegt vor Ausgang" in candidate.warnings
    assert "TX-IDs unterscheiden sich" in candidate.warnings


def test_transfer_candidates_resolve_unique_truncated_wallet_alias(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = "133iWieuwSsyRYopuykZFnxs5qJJW1AiRgXqH43S9rJxU6WUW8v"
    short_wallet = "133iWieuw...xU6WUW8v"
    event_time = datetime(2024, 1, 1, 12, tzinfo=timezone.utc)
    store.add_canonical_event(
        CanonicalEventCreate(
            source="helium",
            event_time=event_time,
            event_type="transfer",
            asset="HNT",
            quantity=Decimal("-2"),
            account=short_wallet,
        )
    )
    store.add_canonical_event(
        CanonicalEventCreate(
            source="helium",
            event_time=event_time + timedelta(minutes=5),
            event_type="transfer",
            asset="HNT",
            quantity=Decimal("2"),
            account=wallet,
        )
    )

    report = TransferCandidateService(store).candidates()

    assert report.candidates_count == 1
    assert report.candidates[0].out_account == wallet
    assert report.candidates[0].in_account == wallet
    assert "Gleiches Konto auf beiden Seiten" in report.candidates[0].warnings


def test_transfer_candidates_api_filters_asset(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    event_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for asset in ("SOL", "USDT"):
        store.add_canonical_event(
            CanonicalEventCreate(
                source="a",
                event_time=event_time,
                event_type="transfer",
                asset=asset,
                quantity=Decimal("-1"),
                account="A",
            )
        )
        store.add_canonical_event(
            CanonicalEventCreate(
                source="b",
                event_time=event_time + timedelta(minutes=1),
                event_type="transfer",
                asset=asset,
                quantity=Decimal("1"),
                account="B",
            )
        )
    client = TestClient(create_app(store))

    response = client.get("/api/v1/transfers/candidates", params={"asset": "SOL"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["assets"] == ["SOL"]
    assert data["candidates_count"] == 1
    assert data["candidates"][0]["asset"] == "SOL"
