from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_methodology import TaxMethodologyService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer


def _import_trade_csv(store: DuckDbStore, content: str) -> None:
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="trades.csv",
        content=content,
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    TaxService(store).rebuild_fifo()


def test_tax_methodology_report_marks_clean_year_as_bmf_ready_with_evidence_overlay(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _import_trade_csv(
        store,
        (
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2024-01-01T00:00:00Z,BTC,1,buy,EUR,10000\n"
            "2024-06-01T00:00:00Z,BTC,-0.5,sell,EUR,8000\n"
        ),
    )

    report = TaxMethodologyService(store).report(2024)

    assert report.status == "ok"
    assert report.bmf_ready is True
    assert report.policy.fifo_scope == "global_asset_with_wallet_fifo_evidence_overlay_v1"
    assert report.tax_lines_count == 1
    assert report.traceability_score == Decimal("100")
    assert [gap.code for gap in report.gaps] == [
        "wallet_fifo_evidence_overlay_ok",
        "asset_fifo_quote_attribution_documented",
    ]
    assert all(gap.blocks_bmf_ready is False for gap in report.gaps)
    assert any(metric.key == "asset_fifo_correction_candidates" for metric in report.metrics)


def test_tax_methodology_report_blocks_unmatched_disposals(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _import_trade_csv(
        store,
        (
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2024-06-01T00:00:00Z,HNT,-2,sell,EUR,10\n"
        ),
    )

    report = TaxMethodologyService(store).report(2024)

    assert report.status == "blocked"
    assert report.bmf_ready is False
    assert any(gap.code == "unmatched_disposals" for gap in report.gaps)
    assert any(gap.code == "wallet_fifo_preview_unmatched" for gap in report.gaps)
    assert any(gap.blocks_bmf_ready for gap in report.gaps)


def test_tax_methodology_documents_small_exchange_sequencing_gap_without_blocker(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2022, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("1"),
                quote_asset="EUR",
                quote_quantity=Decimal("20"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2022, 9, 9, 4, 16, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("1"),
                quote_asset="EUR",
                quote_quantity=Decimal("5"),
                account="pionex",
            ),
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2022, 9, 9, 4, 17, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("-1.03"),
                quote_asset="EUR",
                quote_quantity=Decimal("6"),
                account="pionex",
            ),
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2022, 9, 9, 4, 18, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("0.1"),
                quote_asset="EUR",
                quote_quantity=Decimal("0.5"),
                account="pionex",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    report = TaxMethodologyService(store).report(2022)

    assert report.status == "review"
    assert not any(gap.code == "wallet_fifo_preview_unmatched" for gap in report.gaps)
    sequencing_gap = next(gap for gap in report.gaps if gap.code == "wallet_fifo_exchange_sequencing_documented")
    assert sequencing_gap.count == 1
    assert sequencing_gap.blocks_bmf_ready is False


def test_tax_methodology_bmf_action_plan_lists_blockers(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _import_trade_csv(
        store,
        (
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2024-06-01T00:00:00Z,HNT,-2,sell,EUR,10\n"
        ),
    )

    plan = TaxMethodologyService(store).bmf_action_plan()

    assert 2024 in plan.blocked_years
    assert plan.blocking_items_count >= 1
    assert any(item.code == "wallet_fifo_preview_unmatched" for item in plan.items)
    assert any(item.category == "wallet_fifo" for item in plan.items)


def test_tax_methodology_blocks_unresolved_wallet_fifo_inbound_provenance(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="JUP",
                quantity=Decimal("10"),
                account="Spot",
                tx_id="external-inbound",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="USDT",
                quantity=Decimal("20"),
                quote_asset="JUP",
                quote_quantity=Decimal("10"),
                account="Spot",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    report = TaxMethodologyService(store).report(2024)

    assert report.status == "blocked"
    assert report.bmf_ready is False
    gap = next(gap for gap in report.gaps if gap.code == "wallet_fifo_unresolved_inbound_provenance")
    assert gap.count == 1
    assert gap.blocks_bmf_ready is True


def test_tax_methodology_report_blocks_asset_fifo_recalculation_candidates(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _import_trade_csv(
        store,
        (
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2024-01-01T00:00:00Z,BTC,1,buy,EUR,10000\n"
            "2024-06-01T00:00:00Z,BTC,-0.5,sell,EUR,8000\n"
        ),
    )
    service = TaxMethodologyService(store)
    service.tax_years.asset_fifo_correction_review = lambda *args, **kwargs: SimpleNamespace(
        possible_recalculation_assets_count=1,
        attribution_review_assets_count=0,
    )

    report = service.report(2024)

    assert report.status == "blocked"
    assert report.bmf_ready is False
    assert any(gap.code == "asset_fifo_possible_recalculation" for gap in report.gaps)
    assert any(gap.blocks_bmf_ready for gap in report.gaps)


def test_tax_methodology_report_blocks_external_solana_inflow_review(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
                event_type="income",
                asset="JUP",
                quantity=Decimal("10"),
                account="wallet-1",
                tx_id="airdrop-1",
            )
        ]
    )

    report = TaxMethodologyService(store).report(2024)

    assert report.status == "blocked"
    assert any(gap.code == "external_inflows_need_evidence" for gap in report.gaps)


def test_tax_reward_bmf_recheck_matches_income_guide_and_flags_review_context(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2025, 1, 31, tzinfo=timezone.utc),
                event_type="mining",
                asset="IOT",
                quantity=Decimal("100"),
                account="helium-wallet",
            ),
            CanonicalEventCreate(
                source="binance_simple_earn_api",
                event_time=datetime(2025, 2, 1, tzinfo=timezone.utc),
                event_type="reward",
                asset="JUP",
                quantity=Decimal("10"),
                account="Binance Earn Flexible JUP001",
            ),
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset="IOT",
            price_eur=Decimal("0.01"),
            priced_at=datetime(2025, 1, 31, tzinfo=timezone.utc),
            source="unit",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("0.5"),
            priced_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
            source="unit",
        )
    )
    TaxService(store).rebuild_fifo()

    report = TaxMethodologyService(store).reward_bmf_recheck()
    year = next(item for item in report.years if item.year == 2025)

    assert report.years_with_rewards_count == 1
    assert year.reward_income_eur == Decimal("1.000000000000000000")
    assert year.income_guide_reward_eur == year.reward_income_eur
    assert year.reward_events_count == 1
    assert year.reward_income_candidate_count == 1
    assert year.exchange_or_wrapper_review_count == 1
    assert year.consistency_status == "review"
    assert "exchange_earn_or_wrapper_review_present" in year.flags


def test_tax_methodology_api_endpoints(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    _import_trade_csv(
        store,
        (
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2024-01-01T00:00:00Z,SOL,1,buy,EUR,50\n"
            "2024-02-01T00:00:00Z,SOL,-1,sell,EUR,75\n"
        ),
    )
    client = TestClient(create_app(store))

    summary = client.get("/api/v1/tax-methodology/summary")
    summary_year = client.get("/api/v1/tax-methodology/summary?year=2024")
    reward_recheck = client.get("/api/v1/tax-years/reward-bmf-recheck")
    action_plan = client.get("/api/v1/tax-methodology/bmf-action-plan?year=2024")
    detail = client.get("/api/v1/tax-years/2024/methodology")
    status = client.get("/api/v1/tax-years/2024/compliance-status")

    assert summary.status_code == 200
    assert summary_year.status_code == 200
    assert reward_recheck.status_code == 200
    assert action_plan.status_code == 200
    assert detail.status_code == 200
    assert status.status_code == 200
    assert 2024 in summary.json()["data"]["available_years"]
    assert summary_year.json()["data"]["available_years"] == [2024]
    assert 2024 in reward_recheck.json()["data"]["available_years"]
    assert action_plan.json()["data"]["available_years"] == [2024]
    assert detail.json()["data"]["policy"]["method_version"] == "bmf_readiness_v2"
    assert status.json()["data"]["methodology_endpoint"] == "/api/v1/tax-years/2024/methodology"
