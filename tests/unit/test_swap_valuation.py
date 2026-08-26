from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.swap_valuation import CryptoSwapValuationReviewService
from steuerreport_v2.domain.swap_valuation_parallel import (
    CryptoSwapFifoParallelPreviewService,
)
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer


def _trade(
    *,
    at: datetime,
    asset: str,
    quantity: str,
    quote_asset: str,
    quote_quantity: str,
) -> CanonicalEventCreate:
    return CanonicalEventCreate(
        source="manual-csv",
        event_time=at,
        event_type="trade",
        asset=asset,
        quantity=Decimal(quantity),
        quote_asset=quote_asset,
        quote_quantity=Decimal(quote_quantity),
        account="Spot",
    )


def _price(store: DuckDbStore, asset: str, price: str, at: datetime) -> None:
    store.add_price_point(
        PricePointCreate(
            asset=asset,
            price_eur=Decimal(price),
            priced_at=at,
            source=f"unit:{asset}",
        )
    )


def test_crypto_swap_valuation_review_compares_received_primary_without_writes(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    at = datetime(2024, 2, 1, tzinfo=timezone.utc)
    store.add_canonical_events(
        [
            _trade(
                at=at,
                asset="JUP",
                quantity="100",
                quote_asset="SOL",
                quote_quantity="2",
            ),
            _trade(
                at=at,
                asset="USDT",
                quantity="250",
                quote_asset="SOL",
                quote_quantity="2",
            ),
            _trade(
                at=at,
                asset="NO_RECEIVED_PRICE",
                quantity="10",
                quote_asset="SOL",
                quote_quantity="1",
            ),
            _trade(
                at=at,
                asset="NO_PRICE_A",
                quantity="10",
                quote_asset="NO_PRICE_B",
                quote_quantity="1",
            ),
        ]
    )
    _price(store, "SOL", "120", at)
    _price(store, "JUP", "3", at)
    _price(store, "USDT", "0.96", at)

    report = CryptoSwapValuationReviewService(store).review(limit=20)

    by_asset = {row.received_asset: row for row in report.rows}
    assert report.strict_ready is False
    assert report.candidates_count == 4
    assert report.material_delta_count == 1
    assert report.aligned_count == 1
    assert report.received_price_fallback_review_count == 1
    assert report.missing_both_prices_count == 1
    assert by_asset["JUP"].current_value_eur == Decimal("240")
    assert by_asset["JUP"].bmf_preview_value_eur == Decimal("300")
    assert by_asset["JUP"].value_delta_eur == Decimal("60")
    assert by_asset["JUP"].status == "material_delta"
    assert by_asset["USDT"].status == "aligned_received_primary"
    assert by_asset["NO_RECEIVED_PRICE"].status == "received_price_fallback_review"
    assert by_asset["NO_PRICE_A"].status == "missing_both_prices"
    assert len(store.list_canonical_events()) == 4
    with store.connect() as con:
        assert con.execute("select count(*) from tax_lines").fetchone()[0] == 0

    filtered = CryptoSwapValuationReviewService(store).review(year=2023)
    assert filtered.year == 2023
    assert filtered.candidates_count == 0


def test_crypto_swap_valuation_review_api_endpoint(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    store.add_canonical_events(
        [
            _trade(
                at=at,
                asset="JUP",
                quantity="100",
                quote_asset="SOL",
                quote_quantity="2",
            )
        ]
    )
    _price(store, "SOL", "100", at)
    _price(store, "JUP", "3", at)

    response = TestClient(create_app(store)).get(
        "/api/v1/tax/crypto-swap-valuation-review?limit=10"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["candidates_count"] == 1
    assert data["material_delta_count"] == 1
    assert Decimal(data["rows"][0]["value_delta_eur"]) == Decimal("100")


def test_crypto_swap_fifo_parallel_preview_moves_gain_between_years_read_only(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="swap-parallel.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2024-01-01T00:00:00Z,SOL,10,buy,EUR,1000\n"
            "2024-02-01T00:00:00Z,JUP,100,buy,SOL,2\n"
            "2025-01-01T00:00:00Z,JUP,-100,sell,EUR,400\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    at = datetime(2024, 2, 1, tzinfo=timezone.utc)
    _price(store, "SOL", "120", at)
    _price(store, "JUP", "3", at)

    report = CryptoSwapFifoParallelPreviewService(store).preview(limit=20)

    by_year = {row.year: row for row in report.years}
    assert report.read_only is True
    assert report.status == "delta"
    assert report.current_tax_lines_count == 2
    assert report.preview_tax_lines_count == 2
    assert report.current_gain_loss_eur == Decimal("200")
    assert report.preview_gain_loss_eur == Decimal("200")
    assert report.gain_loss_delta_eur == Decimal("0")
    assert report.absolute_year_gain_loss_delta_eur == Decimal("120")
    assert by_year[2024].gain_loss_delta_eur == Decimal("60")
    assert by_year[2025].gain_loss_delta_eur == Decimal("-60")
    assert report.top_assets[0].asset in {"JUP", "SOL"}
    with store.connect() as con:
        assert con.execute("select count(*) from tax_lots").fetchone()[0] == 0
        assert con.execute("select count(*) from tax_lines").fetchone()[0] == 0
        assert con.execute("select count(*) from tax_run_summaries").fetchone()[0] == 0

    year_report = CryptoSwapFifoParallelPreviewService(store).preview(year=2024)
    assert year_report.year == 2024
    assert year_report.gain_loss_delta_eur == Decimal("60")
    assert year_report.affected_years == [2024]


def test_crypto_swap_fifo_parallel_artifact_and_api_are_explicit(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="swap-parallel-api.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2024-01-01T00:00:00Z,SOL,10,buy,EUR,1000\n"
            "2024-02-01T00:00:00Z,JUP,100,buy,SOL,2\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    at = datetime(2024, 2, 1, tzinfo=timezone.utc)
    _price(store, "SOL", "120", at)
    _price(store, "JUP", "3", at)
    artifact_root = tmp_path / "artifacts"
    service = CryptoSwapFifoParallelPreviewService(
        store,
        artifact_root=artifact_root,
    )

    assert service.latest() is None
    report = service.run(limit=10)

    assert report.status == "delta"
    assert service.latest() is not None
    assert (artifact_root / "latest.json").exists()
    assert len(list(artifact_root.glob("swap_valuation_parallel_*.json"))) == 1

    default_artifact_root = tmp_path / "var/swap_valuation_parallel"
    default_artifact_root.mkdir(parents=True)
    (default_artifact_root / "latest.json").write_bytes(
        (artifact_root / "latest.json").read_bytes()
    )
    client = TestClient(create_app(store))
    latest_response = client.get(
        "/api/v1/tax/crypto-swap-fifo-parallel-preview/latest"
    )
    assert latest_response.status_code == 200
    assert latest_response.json()["data"]["read_only"] is True

    run_response = client.post(
        "/api/v1/tax/crypto-swap-fifo-parallel-preview/run",
        json={"limit": 5},
    )
    assert run_response.status_code == 200
    assert run_response.json()["data"]["status"] == "delta"
