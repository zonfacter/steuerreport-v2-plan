import json
from io import BytesIO
from zipfile import ZipFile
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.admin import AdminSettingWrite
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.contracts.review import ReviewDecisionCreate
from steuerreport_v2.contracts.tax_years import TaxYearAssetFifoPlausibilityRow
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_years import TaxYearService
from steuerreport_v2.domain.valuation import PriceQualityService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer


def test_tax_year_summary_aggregates_fifo_gain_loss(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="trades.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2021-01-01T00:00:00Z,BTC,1,buy,EUR,10000\n"
            "2021-06-01T00:00:00Z,BTC,-0.4,sell,EUR,6000\n"
            "2021-07-01T00:00:00Z,HNT,10,mining,EUR,20\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    TaxService(store).rebuild_fifo()

    summary = TaxYearService(store).summary()
    year = next(item for item in summary.years if item.year == 2021)

    assert year.state == "finished"
    assert year.realized_gain_loss_eur == Decimal("2000.000000000000000000000000000000000000")
    assert year.rewards_income_eur == Decimal("20.000000000000000000")
    assert year.rewards_events_count == 1
    assert year.top_assets[0].asset == "BTC"


def test_tax_year_assigns_utc_year_end_disposal_to_german_calendar_year(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2021, 1, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("1"),
                quote_asset="EUR",
                quote_quantity=Decimal("10"),
                account="pionex",
            ),
            CanonicalEventCreate(
                source="pionex",
                event_time=datetime(2021, 12, 31, 23, 30, tzinfo=timezone.utc),
                event_type="trade",
                asset="HNT",
                quantity=Decimal("-1"),
                quote_asset="EUR",
                quote_quantity=Decimal("12"),
                account="pionex",
            ),
        ]
    )
    TaxService(store).rebuild_fifo()

    service = TaxYearService(store)

    assert service.detail(2021).tax_lines_count == 0
    assert service.detail(2022).tax_lines_count == 1
    assert service.detail(2022).realized_gain_loss_eur == Decimal("2")


def test_tax_year_assigns_actual_utc_year_end_reward_to_german_calendar_year(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2021, 12, 31, 23, 30, tzinfo=timezone.utc),
                event_type="mining",
                asset="HNT",
                quantity=Decimal("1"),
                quote_asset="EUR",
                quote_quantity=Decimal("10"),
                account="legacy-wallet",
            )
        ]
    )
    TaxService(store).rebuild_fifo()

    service = TaxYearService(store)

    assert service.detail(2021).rewards_events_count == 0
    assert service.detail(2022).rewards_events_count == 1
    assert service.detail(2022).rewards_income_eur == Decimal("10")


def test_tax_year_preserves_helium_source_period_aggregate_year(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="helium",
            filename="helium-period-aggregate.csv",
            file_hash="helium-period-aggregate",
        )
    )
    raw = store.add_raw_objects(
        batch.batch_id,
        [RawObjectCreate(row_number=1, payload_json='{"Period Start (UTC)":"01.12.23"}')],
    )[0]
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2023, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
                event_type="mining",
                asset="IOT",
                quantity=Decimal("100"),
                quote_asset="EUR",
                quote_quantity=Decimal("4"),
                account="legacy-wallet",
                raw_object_id=raw.raw_object_id,
            )
        ]
    )
    TaxService(store).rebuild_fifo()

    service = TaxYearService(store)

    assert service.detail(2023).rewards_events_count == 1
    assert service.detail(2023).rewards_income_eur == Decimal("4")
    assert service.detail(2024).rewards_events_count == 0


def test_tax_year_summary_separates_tax_free_holding_period_lines(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="holding-period.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2021-01-01T00:00:00Z,SOL,1,buy,EUR,10\n"
            "2022-02-01T00:00:00Z,SOL,-1,sell,EUR,100\n"
            "2022-03-01T00:00:00Z,HNT,10,buy,EUR,20\n"
            "2022-04-01T00:00:00Z,HNT,-10,sell,EUR,50\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    TaxService(store).rebuild_fifo()

    year = TaxYearService(store).detail(2022)
    guide = TaxYearService(store).declaration_guide(2022)

    assert year.realized_gain_loss_eur == Decimal("30.000000000000000000000000000000000000")
    assert year.taxable_disposal_proceeds_eur == Decimal("50.000000000000000000")
    assert year.acquisition_cost_eur == Decimal("20.000000000000000000000000000000000000")
    assert year.tax_lines_count == 1
    assert year.tax_free_gain_loss_eur == Decimal("90.000000000000000000000000000000000000")
    assert year.tax_free_disposal_proceeds_eur == Decimal("100.000000000000000000")
    assert year.tax_free_acquisition_cost_eur == Decimal("10.000000000000000000000000000000000000")
    assert year.tax_free_lines_count == 1
    assert [item.asset for item in year.asset_breakdown] == ["HNT"]
    assert guide.tax_free_gain_loss_eur == year.tax_free_gain_loss_eur
    assert any(entry.section == "Steuerfreie Veraeusserungen nach Haltefrist" for entry in guide.entries)


def test_income_guide_values_rewards_with_historical_asset_price(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="mining.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2024-01-01T00:00:00Z,HNT,10,mining,,\n"
            "2024-01-02T00:00:00Z,IOT,100,rewards,,\n"
            "2024-01-03T00:00:00Z,MOBILE,200,reward,EUR,3\n"
            "2024-01-04T00:00:00Z,USDT,5,income,EUR,5\n"
            "2024-01-05T00:00:00Z,SOL,-1,income,EUR,100\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("2"),
            priced_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    TaxService(store).rebuild_fifo()

    year = TaxYearService(store).detail(2024)
    report = TaxYearService(store).income_report(2024)

    assert year.rewards_income_eur == Decimal("23.000000000000000000")
    assert year.rewards_events_count == 3
    assert report.total_income_eur == Decimal("28.000000000000000000")
    assert report.reward_income_eur == Decimal("23.000000000000000000")
    assert report.generic_income_eur == Decimal("5.000000000000000000")
    assert report.declaration_income_eur == report.reward_income_eur
    assert report.review_only_income_eur == report.generic_income_eur
    assert report.taxable_reward_events_count == 3
    assert report.review_only_events_count == 1
    assert report.valued_events_count == 3
    assert report.missing_value_count == 1
    assert report.ignored_non_positive_count == 1
    assert report.missing_assets == ["IOT"]
    assert [item.asset for item in report.assets[:3]] == ["HNT", "USDT", "MOBILE"]
    assert report.classification_counts == {
        "generic_income_review": 1,
        "non_positive_ignored": 1,
        "reward_income_candidate": 3,
    }
    assert any(item.classification == "reward_income_candidate" for item in report.assets)


def test_reward_trading_separation_splits_helium_rewards_from_fifo_trading(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="reward-trading.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2024-01-01T00:00:00Z,HNT,10,mining,EUR,20\n"
            "2024-06-01T00:00:00Z,HNT,-5,sell,EUR,15\n"
            "2024-07-01T00:00:00Z,IOT,100,reward,EUR,4\n"
            "2025-08-01T00:00:00Z,IOT,-100,sell,EUR,1\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    TaxService(store).rebuild_fifo()

    report = TaxYearService(store).reward_trading_separation(years=[2024, 2025])
    hnt = next(row for row in report.rows if row.year == 2024 and row.asset == "HNT")
    iot_2024 = next(row for row in report.rows if row.year == 2024 and row.asset == "IOT")
    iot_2025 = next(row for row in report.rows if row.year == 2025 and row.asset == "IOT")

    assert hnt.reward_income_eur == Decimal("20.000000000000000000")
    assert hnt.trade_taxable_gain_loss_eur == Decimal("5.000000000000000000000000000000000000")
    assert hnt.trade_taxable_lines_count == 1
    assert hnt.trade_tax_free_lines_count == 0
    assert iot_2024.reward_income_eur == Decimal("4.000000000000000000")
    assert iot_2025.reward_income_eur == Decimal("0")
    assert iot_2025.trade_tax_free_gain_loss_eur == Decimal("-3.000000000000000000000000000000000000")
    assert iot_2025.trade_tax_free_lines_count == 1
    assert "Reward/Mining ist der Einnahmevorgang" in hnt.tax_note
    assert "Betriebsvermoegen" in hnt.tax_note
    assert "aktuell aktive FIFO-Berechnung" in report.methodology
    assert "Handel steuerpfl." in report.ascii_table


def test_income_guide_uses_solana_transaction_context_for_income_review(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDC",
                quantity=Decimal("-100"),
                tx_id="tx-swap",
                account="wallet-1",
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
                event_type="income",
                asset="NFTX",
                quantity=Decimal("1"),
                tx_id="tx-swap",
                account="wallet-1",
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
                event_type="income",
                asset="AIR",
                quantity=Decimal("5"),
                tx_id="tx-airdrop",
                account="wallet-1",
            ),
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset="NFTX",
            price_eur=Decimal("7"),
            priced_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="AIR",
            price_eur=Decimal("2"),
            priced_at=datetime(2024, 3, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    report = TaxYearService(store).income_report(2024)

    assert report.classification_counts["solana_swap_or_transfer_with_outgoing_review"] == 1
    assert report.classification_counts["solana_external_inflow_or_airdrop_review"] == 1


def test_tax_year_rewards_exclude_exchange_earn_and_wrapper_candidates(tmp_path):
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
                source="binance",
                event_time=datetime(2025, 1, 20, tzinfo=timezone.utc),
                event_type="staking",
                asset="BNSOL",
                quantity=Decimal("2"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance_simple_earn_api",
                event_time=datetime(2025, 1, 21, tzinfo=timezone.utc),
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
            asset="BNSOL",
            price_eur=Decimal("100"),
            priced_at=datetime(2025, 1, 20, tzinfo=timezone.utc),
            source="unit",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("0.5"),
            priced_at=datetime(2025, 1, 21, tzinfo=timezone.utc),
            source="unit",
        )
    )
    TaxService(store).rebuild_fifo()

    year = TaxYearService(store).detail(2025)
    report = TaxYearService(store).income_report(2025)

    assert year.rewards_income_eur == Decimal("1.000000000000000000")
    assert year.rewards_events_count == 1
    assert report.reward_income_eur == Decimal("1.000000000000000000")
    assert report.generic_income_eur == Decimal("205.000000000000000000")
    assert report.declaration_income_eur == Decimal("1.000000000000000000")
    assert report.review_only_income_eur == Decimal("205.000000000000000000")
    assert report.taxable_reward_events_count == 1
    assert report.review_only_events_count == 2
    assert report.classification_counts["reward_income_candidate"] == 1
    assert report.classification_counts["exchange_earn_or_wrapper_review"] == 2


def test_tax_year_rewards_include_solana_helium_instruction_rewards(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_rows(
        source="solana_rpc",
        filename="solana-hnt-reward-2026-06-19.json",
        file_hash="solana-hnt-reward-2026-06-19",
        rows=[
            {
                "timestamp_utc": "2026-06-19T21:40:23+00:00",
                "event_type": "token_transfer",
                "asset": "HNT",
                "quantity": "3.488129",
                "side": "in",
                "tx_id": "reward-tx",
                "wallet_address": "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP",
                "logMessages": [
                    "Program log: Instruction: SetCurrentRewardsWrapperV1",
                    "Program log: Instruction: SetCurrentRewardsV0",
                    "Program log: Instruction: DistributeCompressionRewardsV0",
                ],
            }
        ],
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("3"),
            priced_at=datetime(2026, 6, 19, 21, 40, 23, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    TaxService(store).rebuild_fifo()

    year = TaxYearService(store).detail(2026)
    report = TaxYearService(store).income_report(2026)

    assert year.rewards_income_eur == Decimal("10.464387000000000000")
    assert year.rewards_events_count == 1
    assert report.reward_income_eur == Decimal("10.464387000000000000")
    assert report.classification_counts["reward_income_candidate"] == 1


def test_external_inflow_report_matches_prior_outgoing_transfer(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2024, 2, 1, 10, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDC",
                quantity=Decimal("-100"),
                account="Spot",
                tx_id="withdraw-1",
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 2, 1, 12, tzinfo=timezone.utc),
                event_type="income",
                asset="USDC",
                quantity=Decimal("100"),
                account="wallet-1",
                tx_id="sol-in-1",
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 3, 1, tzinfo=timezone.utc),
                event_type="income",
                asset="JUP",
                quantity=Decimal("10"),
                account="wallet-1",
                tx_id="airdrop-1",
            ),
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDC",
            price_eur=Decimal("0.92"),
            priced_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("1"),
            priced_at=datetime(2024, 3, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    report = TaxYearService(store).external_inflow_report(2024)

    assert report.inflows_count == 2
    assert report.matched_count == 1
    assert report.unmatched_count == 1
    matched = next(row for row in report.rows if row.asset == "USDC")
    assert matched.status == "matched_transfer_candidate"
    assert matched.matched_source == "binance"
    unmatched = next(row for row in report.rows if row.asset == "JUP")
    assert unmatched.status == "unmatched_external_inflow"


def test_external_inflow_report_excludes_multi_event_solana_program_income(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 3, 12, 17, 26, 37, tzinfo=timezone.utc),
                event_type="income",
                asset="USDT",
                quantity=Decimal("8291.780901"),
                account="wallet-1",
                tx_id="swap-like-tx",
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 3, 12, 17, 26, 37, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("0.00397416"),
                account="wallet-1",
                tx_id="swap-like-tx",
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2024, 3, 13, tzinfo=timezone.utc),
                event_type="trade",
                asset="USDT",
                quantity=Decimal("-1000"),
                quote_asset="USDT",
                quote_quantity=Decimal("960"),
                account="wallet-1",
                tx_id="dispose-usdt",
            ),
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.92"),
            priced_at=datetime(2024, 3, 12, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    store.add_price_point(PricePointCreate(asset="USDT", price_eur=Decimal("0.92"),
        priced_at=datetime(2024, 3, 13, tzinfo=timezone.utc), source="manual-test"))

    income = TaxYearService(store).income_report(2024)
    external = TaxYearService(store).external_inflow_report(2024)

    assert income.classification_counts["solana_program_or_swap_income_review"] == 1
    assert "solana_external_inflow_or_airdrop_review" not in income.classification_counts
    assert external.inflows_count == 0
    assert external.total_value_eur == Decimal("0")
    review = TaxYearService(store).solana_program_income_review(2024)
    assert review.events_count == 1
    assert review.total_value_eur == Decimal("7628.438428920000000000")
    assert review.years[0].year == 2024
    assert review.assets[0].asset == "USDT"
    assert review.rows[0].review_reason == "same_tx_has_additional_positive_program_context"
    assert review.rows[0].tx_total_count == 2
    TaxService(store).rebuild_fifo()
    stablecoin = TaxYearService(store).stablecoin_fifo_review(2024)
    assert stablecoin.tax_line_count == 1
    assert stablecoin.gain_loss_eur == Decimal("-36.800000000000000000")
    assert stablecoin.assets[0].asset == "USDT"
    assert stablecoin.sources[0].disposal_source == "solana_rpc"
    assert stablecoin.rows[0].acquisition_classification == "solana_program_or_swap_income_review"
    assert stablecoin.rows[0].review_reason == "stablecoin_lot_from_solana_program_context"


def test_income_report_excludes_duplicate_solana_income_when_reward_tx_is_verified(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2026, 5, 7, 14, 53, 43, tzinfo=timezone.utc),
                event_type="income",
                asset="HNT",
                quantity=Decimal("1.70084235"),
                account="wallet-1",
                tx_id="reward-tx-1",
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2026, 5, 7, 14, 53, 43, tzinfo=timezone.utc),
                event_type="reward",
                asset="HNT",
                quantity=Decimal("1.70084235"),
                account="wallet-1",
                tx_id="reward-tx-1",
            ),
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("0.80"),
            priced_at=datetime(2026, 5, 7, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    income = TaxYearService(store).income_report(2026)
    external = TaxYearService(store).external_inflow_report(2026)

    assert income.reward_income_eur == Decimal("1.36067388000000000000")
    assert income.generic_income_eur == Decimal("0")
    assert income.classification_counts == {"reward_income_candidate": 1}
    assert external.inflows_count == 0


def test_declaration_guide_flags_external_solana_inflows(tmp_path):
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
    store.add_price_point(
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("1"),
            priced_at=datetime(2024, 3, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )

    guide = TaxYearService(store).declaration_guide(2024)

    assert any(entry.section == "Pruefbereich externe Solana-Zufluesse" for entry in guide.entries)
    assert any("Externe Solana-Zufluesse pruefen" in caveat for caveat in guide.caveats)
    assert "/api/v1/export/tax-external-inflows.csv" in guide.evidence_exports


def test_tax_year_drivers_split_taxable_and_tax_free_lines(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="drivers.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2021-01-01T00:00:00Z,SOL,1,buy,EUR,10\n"
            "2022-02-01T00:00:00Z,SOL,-1,sell,EUR,100\n"
            "2022-03-01T00:00:00Z,HNT,10,buy,EUR,20\n"
            "2022-04-01T00:00:00Z,HNT,-10,sell,EUR,50\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    TaxService(store).rebuild_fifo()

    report = TaxYearService(store).driver_report(2022)

    assert report.taxable_gain_loss_eur == Decimal("30.000000000000000000000000000000000000")
    assert report.tax_free_gain_loss_eur == Decimal("90.000000000000000000000000000000000000")
    assert report.top_taxable_assets[0].asset == "HNT"
    assert report.top_tax_free_assets[0].asset == "SOL"
    assert report.top_taxable_lines[0].taxable is True
    assert report.top_tax_free_lines[0].taxable is False


def test_gain_loss_reality_check_separates_realized_from_unrealized_losses(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="reality-check.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2024-01-01T00:00:00Z,JUP,10,buy,EUR,10\n"
            "2024-02-01T00:00:00Z,JUP,-5,sell,EUR,20\n"
            "2025-01-01T00:00:00Z,JUP,10,buy,EUR,100\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("2"),
            priced_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    TaxService(store).rebuild_fifo()

    report = TaxYearService(store).gain_loss_reality_check(2024)
    jup = next(row for row in report.rows if row.asset == "JUP")

    assert report.taxable_gain_loss_eur == Decimal("15.000000000000000000000000000000000000")
    assert jup.realized_taxable_gain_loss_eur == Decimal("15.000000000000000000000000000000000000")
    assert jup.open_current_value_eur == Decimal("30.00000000000000000000000000")
    assert jup.open_cost_basis_eur == Decimal("105.000000000000000000000000000000000000")
    assert jup.open_unrealized_gain_loss_eur == Decimal("-75.00000000000000000000000000000000000000")
    assert jup.potential_loss_not_realized_eur == jup.open_unrealized_gain_loss_eur
    assert "nicht automatisch" in jup.note
    assert "Handels-/Swap-Volumen" in report.plain_language_summary


def test_gain_evidence_review_flags_missing_raw_and_non_eur_quote(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="gain-evidence.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2024-01-01T00:00:00Z,JUP,10,buy,USDT,10\n"
            "2024-02-01T00:00:00Z,JUP,-10,sell,USDT,30\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("1"),
            priced_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("1"),
            priced_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    TaxService(store).rebuild_fifo()

    report = TaxYearService(store).gain_evidence_review(2024)
    line = report.lines[0]

    assert line.asset == "JUP"
    assert line.risk_level == "review"
    assert "non_eur_quote_or_stablecoin_valuation" in line.review_reasons
    assert line.acquisition_raw_evidence == "present"
    assert line.disposal_raw_evidence == "present"
    assert line.acquisition_price_source == "manual-test"
    assert line.disposal_price_source == "manual-test"
    assert line.acquisition_expected_cost_eur == Decimal("10.000000000000000000")
    assert line.disposal_expected_proceeds_eur == Decimal("30.000000000000000000")
    assert line.acquisition_cost_delta_eur == Decimal("0E-18")
    assert line.disposal_proceeds_delta_eur == Decimal("0E-18")
    assert line.delta_classification == "no_material_delta"
    assert line.absolute_price_delta_eur == Decimal("0E-18")
    assert line.open_price_delta_eur == Decimal("0")
    assert report.price_delta_lines_count == 0
    assert report.event_level_reconciled_lines_count == 1
    assert report.material_price_delta_eur == Decimal("0E-18")
    assert report.open_price_delta_eur == Decimal("0")
    assert report.delta_groups == []
    assert "disp_quote=USDT" in line.valuation_path
    assert "Risiko" in report.ascii_table


def test_gain_evidence_review_groups_stablecoin_price_delta(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="gain-evidence-delta.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2024-01-01T00:00:00Z,JUP,10,buy,USDT,10\n"
            "2024-02-01T00:00:00Z,JUP,-10,sell,USDT,30\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.80"),
            priced_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("1"),
            priced_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    TaxService(store).rebuild_fifo()
    with store.connect() as con:
        con.execute("update tax_lines set acquisition_cost_eur = 10 where asset = 'JUP'")

    report = TaxYearService(store).gain_evidence_review(2024)
    line = report.lines[0]

    assert line.delta_classification == "stablecoin_fx_or_market_delta"
    assert line.absolute_price_delta_eur == Decimal("2.000000000000000000")
    assert line.open_price_delta_eur == Decimal("2.000000000000000000")
    assert line.event_level_reconciled is True
    assert line.acquisition_event_level_reconciled is False
    assert line.max_price_delta_pct == Decimal("25.00")
    assert "USD/EUR" in line.delta_explanation
    assert report.price_delta_lines_count == 1
    assert report.event_level_reconciled_lines_count == 1
    assert report.acquisition_event_level_reconciled_lines_count == 0
    assert report.material_price_delta_eur == Decimal("2.000000000000000000")
    assert report.open_price_delta_eur == Decimal("2.000000000000000000")
    assert len(report.delta_groups) == 1
    group = report.delta_groups[0]
    assert group.classification == "stablecoin_fx_or_market_delta"
    assert group.lines_count == 1
    assert group.quote_assets == ["USDT"]
    assert group.absolute_delta_eur == Decimal("2.000000000000000000")
    assert group.open_delta_eur == Decimal("2.000000000000000000")


def test_gain_evidence_price_delta_drilldown_uses_proportional_quote_for_split_lines(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="gain-evidence-split-delta.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2024-01-01T00:00:00Z,JUP,5,buy,USDT,5\n"
            "2024-01-02T00:00:00Z,JUP,5,buy,USDT,10\n"
            "2024-02-01T00:00:00Z,JUP,-10,sell,USDT,30\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("1"),
            priced_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("1"),
            priced_at=datetime(2024, 1, 2, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("1"),
            priced_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    TaxService(store).rebuild_fifo()

    report = TaxYearService(store).gain_evidence_price_delta_drilldown(2024)
    gain_report = TaxYearService(store).gain_evidence_review(2024)

    assert report.lines_count == 0
    assert report.split_line_review_count == 0
    assert report.root_cause_counts == {}
    assert report.absolute_delta_eur == Decimal("0")
    assert report.event_level_reconciled_count == 0
    assert report.event_level_review_count == 0
    assert report.event_level_unchecked_count == 0
    assert gain_report.event_level_reconciled_lines_count == 2
    assert gain_report.acquisition_event_level_reconciled_lines_count == 2
    assert gain_report.material_price_delta_eur == Decimal("0E-18")
    assert gain_report.open_price_delta_eur == Decimal("0")
    assert all(line.event_level_reconciled for line in gain_report.lines)
    assert all(line.acquisition_event_level_reconciled for line in gain_report.lines)
    assert all(line.open_price_delta_eur == Decimal("0") for line in gain_report.lines)
    assert all(line.absolute_price_delta_eur == Decimal("0E-18") for line in gain_report.lines)

    event_report = TaxYearService(store).gain_evidence_event_delta_review(2024)
    assert event_report.events_count == 1
    assert event_report.event_level_ok_count == 1
    assert event_report.event_level_review_count == 0
    assert event_report.split_line_absolute_delta_eur == Decimal("0")
    event = event_report.lines[0]
    assert event.tax_line_count == 2
    assert event.actual_proceeds_eur == Decimal("30.000000000000000000")
    assert event.expected_proceeds_eur == Decimal("30.000000000000000000")
    assert event.event_delta_eur == Decimal("0E-18")
    assert event.split_line_count == 0
    assert event.status == "event_level_ok"
    assert "aggregiert plausibel" in event.explanation

    acquisition_event_report = TaxYearService(store).gain_evidence_acquisition_event_delta_review(2024)
    assert acquisition_event_report.events_count == 2
    assert acquisition_event_report.event_level_ok_count == 2
    assert acquisition_event_report.event_level_review_count == 0
    assert acquisition_event_report.event_delta_eur == Decimal("0E-18")
    assert all(line.status == "event_level_ok" for line in acquisition_event_report.lines)


def test_gain_evidence_event_delta_uses_received_stablecoin_for_positive_trade(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="gain-evidence-stablecoin-received.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2025-01-01T00:00:00Z,TRUMP,140,buy,EUR,100\n"
            "2025-01-20T06:49:58Z,USDT,8363.628,buy,TRUMP,140\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.96937"),
            priced_at=datetime(2025, 1, 20, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="TRUMP",
            price_eur=Decimal("41.4405675"),
            priced_at=datetime(2025, 1, 20, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    TaxService(store).rebuild_fifo()

    report = TaxYearService(store).gain_evidence_event_delta_review(2025)

    assert report.events_count == 1
    event = report.lines[0]
    assert event.price_asset == "USDT"
    assert event.event_total_proceeds_eur == Decimal("8107.450074360000000000")
    assert event.actual_proceeds_eur == Decimal("8107.450074360000000000")
    assert event.event_delta_eur == Decimal("0E-18")
    assert event.status == "event_level_ok"


def test_loss_realization_planner_marks_usable_and_expired_loss_windows(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    now = datetime.now(timezone.utc).replace(microsecond=0)
    fresh = (now.replace(tzinfo=timezone.utc) - timedelta(days=30)).isoformat().replace("+00:00", "Z")
    expired = (now.replace(tzinfo=timezone.utc) - timedelta(days=500)).isoformat().replace("+00:00", "Z")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="loss-planner.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            f"{fresh},JUP,10,buy,EUR,100\n"
            f"{expired},SOL,2,buy,EUR,200\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="JUP",
            price_eur=Decimal("5"),
            priced_at=now,
            source="manual-test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("50"),
            priced_at=now,
            source="manual-test",
        )
    )
    TaxService(store).rebuild_fifo()

    report = TaxYearService(store).loss_realization_planner(min_loss_eur=Decimal("1"), min_value_eur=Decimal("1"))
    jup = next(row for row in report.rows if row.asset == "JUP")
    sol = next(row for row in report.rows if row.asset == "SOL")

    assert jup.status == "tax_relevant_loss_if_sold_now"
    assert jup.unrealized_gain_loss_eur == Decimal("-50.000000000000000000000000000000000000")
    assert sol.status == "loss_window_expired"
    assert sol.unrealized_gain_loss_eur == Decimal("-100.000000000000000000000000000000000000")
    assert report.tax_relevant_lots_count == 1
    assert report.expired_loss_lots_count == 1
    assert "FIFO-Lot" in jup.evidence_note
    assert "tax_relevant_loss_if_sold_now" in report.ascii_table


def test_tax_year_asset_fifo_drilldown_links_tax_line_to_raw_evidence(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="trump-fifo.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2025-01-20T07:12:26Z,TRUMP,10,buy,EUR,100\n"
            "2025-01-20T08:49:58Z,TRUMP,-10,sell,EUR,540\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    TaxService(store).rebuild_fifo()

    report = TaxYearService(store).asset_fifo_drilldown(2025, asset="trump")

    assert report.asset == "TRUMP"
    assert report.lines_count == 1
    assert report.taxable_gain_loss_eur == Decimal("440.000000000000000000000000000000000000")
    line = report.lines[0]
    assert line.taxable is True
    assert line.acquisition_event is not None
    assert line.acquisition_event.asset == "TRUMP"
    assert line.disposal_event is not None
    assert line.disposal_event.asset == "TRUMP"
    assert line.acquisition_raw is not None
    assert line.acquisition_raw.filename == "trump-fifo.csv"
    assert line.disposal_raw is not None
    assert line.disposal_raw.filename == "trump-fifo.csv"
    assert "TRUMP" in line.acquisition_raw.payload_json


def test_tax_year_asset_fifo_plausibility_surfaces_quote_leg_effects(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="quote-leg-plausibility.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2025-01-01T00:00:00Z,USDT,100,buy,EUR,100\n"
            "2025-01-02T00:00:00Z,TRUMP,10,buy,USDT,100\n"
            "2025-01-03T00:00:00Z,USDT,150,buy,EUR,150\n"
            "2025-01-04T00:00:00Z,TRUMP,-10,sell,USDT,150\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    TaxService(store).rebuild_fifo()

    report = TaxYearService(store).asset_fifo_plausibility(
        2025,
        min_abs_gain_eur=Decimal("10"),
    )
    by_asset = {row.asset: row for row in report.rows}

    assert "TRUMP" in by_asset
    assert by_asset["TRUMP"].linked_tax_lines_count >= 1
    assert "material_linked_quote_gain_or_loss" in by_asset["TRUMP"].reasons
    assert by_asset["TRUMP"].drilldown_endpoint == "/api/v1/tax-years/2025/asset-fifo-drilldown?asset=TRUMP"
    assert report.high_risk_assets_count + report.review_assets_count >= 1


def test_tax_year_asset_fifo_correction_review_classifies_quote_attribution(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="quote-correction-review.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2025-01-01T00:00:00Z,USDT,100,buy,EUR,100\n"
            "2025-01-02T00:00:00Z,TRUMP,10,buy,USDT,100\n"
            "2025-01-03T00:00:00Z,USDT,150,buy,EUR,150\n"
            "2025-01-04T00:00:00Z,TRUMP,-10,sell,USDT,150\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    TaxService(store).rebuild_fifo()

    report = TaxYearService(store).asset_fifo_correction_review(
        2025,
        min_abs_gain_eur=Decimal("10"),
    )
    by_asset = {row.asset: row for row in report.rows}

    assert by_asset["TRUMP"].recommended_action == "verify_quote_leg_attribution"
    assert by_asset["TRUMP"].tax_sum_impact == "already_in_existing_tax_lines"
    assert by_asset["TRUMP"].related_raw_evidence_count > 0
    assert by_asset["TRUMP"].related_missing_raw_evidence_count == 0
    assert report.attribution_review_assets_count >= 1


def test_tax_year_asset_fifo_correction_review_keeps_historical_cost_basis_trace(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="historical-cost-basis.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2024-01-01T00:00:00Z,BTC,0.01,buy,EUR,100\n"
            "2024-02-01T00:00:00Z,BTC,-0.01,sell,USDT,150\n"
            "2025-01-01T00:00:00Z,TRUMP,10,buy,USDT,150\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("1.20"),
            priced_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
            source="unit",
        )
    )
    TaxService(store).rebuild_fifo()

    report = TaxYearService(store).asset_fifo_correction_review(
        2025,
        min_abs_gain_eur=Decimal("10"),
    )
    by_asset = {row.asset: row for row in report.rows}

    assert by_asset["BTC"].recommended_action == "keep_tax_sum_review_presentation"
    assert by_asset["BTC"].tax_sum_impact == "already_in_existing_tax_lines"
    assert "historische Kostenbasis" in by_asset["BTC"].conclusion


def test_tax_year_asset_fifo_correction_review_ignores_sub_threshold_quote_only_dust():
    row = TaxYearAssetFifoPlausibilityRow(
        year=2023,
        asset="BNB",
        risk_level="high",
        linked_tax_lines_count=92,
        linked_gain_loss_eur=Decimal("0.196277990140708774"),
        total_related_gain_loss_eur=Decimal("0.196277990140708774"),
        reasons=["asset_only_seen_in_related_quote_or_counter_events", "many_related_quote_or_counter_lines"],
        drilldown_endpoint="/api/v1/tax-years/2023/asset-fifo-drilldown?asset=BNB",
    )

    action, tax_impact, conclusion, next_step = TaxYearService._asset_fifo_correction_decision(
        row,
        role_counts={
            "direct_tax_asset": 0,
            "disposal_asset": 0,
            "disposal_quote_asset": 92,
            "acquisition_asset": 0,
            "acquisition_quote_asset": 0,
        },
        related_missing_raw_evidence_count=0,
        min_abs_gain_eur=Decimal("100"),
    )

    assert action == "no_action"
    assert tax_impact == "none_expected"
    assert "Kein materielles Korrektursignal" in conclusion
    assert next_step == "Keine Aktion noetig."


def test_tax_year_turnover_audit_separates_gross_volume_from_taxable_gain(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="turnover.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2022-01-01T00:00:00Z,HNT,10,buy,EUR,10\n"
            "2024-01-10T00:00:00Z,HNT,-10,sell,EUR,1000\n"
            "2024-01-01T00:00:00Z,USDC,10000,buy,EUR,10000\n"
            "2024-01-02T00:00:00Z,USDC,-10000,sell,EUR,10000\n"
            "2024-02-01T00:00:00Z,SOL,10,buy,EUR,100\n"
            "2024-03-01T00:00:00Z,SOL,-10,sell,EUR,200\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    TaxService(store).rebuild_fifo()

    report = TaxYearService(store).turnover_audit(2024)
    by_asset = {item.asset: item for item in report.top_assets_by_proceeds}

    assert report.gross_disposal_proceeds_eur == Decimal("11200.000000000000000000000000000000000000")
    assert report.taxable_gain_loss_eur == Decimal("100.000000000000000000000000000000000000")
    assert report.tax_free_gain_loss_eur == Decimal("990.000000000000000000000000000000000000")
    assert report.stablecoin_gross_disposal_proceeds_eur == Decimal("10000.000000000000000000000000000000000000")
    assert report.stablecoin_gain_loss_eur == Decimal("0E-36")
    assert by_asset["USDC"].stablecoin_like is True
    assert by_asset["USDC"].gross_disposal_proceeds_eur == Decimal(
        "10000.000000000000000000000000000000000000"
    )
    assert "kein eingesetztes oder ausgezahltes EUR-Kapital" in report.plain_language_summary
    assert any(item.source == "binance" and item.asset == "USDC" for item in report.top_sources_by_proceeds)


def test_tax_year_turnover_audit_summary_flags_material_stablecoin_results(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="turnover-summary.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2021-01-01T00:00:00Z,USDT,1000,buy,EUR,500\n"
            "2021-02-01T00:00:00Z,USDT,-1000,sell,EUR,1000\n"
            "2022-01-01T00:00:00Z,USDC,1000,buy,EUR,1000\n"
            "2022-02-01T00:00:00Z,USDC,-1000,sell,EUR,1000\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    TaxService(store).rebuild_fifo()

    summary = TaxYearService(store).turnover_audit_summary()
    by_year = {row.year: row for row in summary.years}

    assert by_year[2021].risk_level == "high"
    assert "material_stablecoin_fifo_gain_or_loss" in by_year[2021].reasons
    assert by_year[2021].stablecoin_gain_ratio_pct == Decimal("50.000")
    assert by_year[2021].audit_endpoint == "/api/v1/tax-years/2021/turnover-audit"
    assert by_year[2022].risk_level == "review"
    assert by_year[2022].reasons == ["stablecoin_turnover_present"]
    assert summary.high_risk_years_count >= 1


def test_stablecoin_quote_leg_review_matches_expected_tax_lines(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="stable-quote.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2024-01-01T00:00:00Z,USDC,1000,buy,EUR,920\n"
            "2024-02-01T00:00:00Z,SOL,5,buy,USDC,500\n"
            "2024-03-01T00:00:00Z,SOL,-1,sell,USDC,120\n"
            "2024-04-01T00:00:00Z,USDT,50,buy,USDC,46\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="USDC",
            price_eur=Decimal("0.92"),
            priced_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
            source="unit",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDC",
            price_eur=Decimal("0.91"),
            priced_at=datetime(2024, 3, 1, tzinfo=timezone.utc),
            source="unit",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDC",
            price_eur=Decimal("0.90"),
            priced_at=datetime(2024, 4, 1, tzinfo=timezone.utc),
            source="unit",
        )
    )
    TaxService(store).rebuild_fifo()

    report = TaxYearService(store).stablecoin_quote_leg_review(2024)

    assert report.events_count == 3
    assert report.expected_tax_line_events_count == 2
    assert report.missing_expected_tax_line_events_count == 0
    assert report.stable_to_stable_events_count == 1
    rows_by_effect = {row.expected_tax_effect: row for row in report.rows}
    assert rows_by_effect["stable_quote_disposal"].stable_tax_lines_count == 1
    assert rows_by_effect["stable_quote_lot_acquisition"].expected_tax_line is False
    assert rows_by_effect["stable_to_stable_quote_leg_review"].review_reason == "stable_to_stable_quote_leg_review"
    assert all(row.batch_filename == "stable-quote.csv" for row in report.rows)


def test_solana_stablecoin_swap_context_classifies_rpc_quote_leg(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    opening = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="/tmp/private/opening.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2024-01-01T00:00:00Z,USDC,1000,buy,EUR,920\n"
        ),
    )
    RawNormalizer(store).normalize_batch(opening.batch_id)
    batch = CsvRawImporter(store).import_rows(
        source="solana_rpc",
        filename="/tmp/private/solana-swap.json",
        file_hash="solana-swap",
        rows=[
            {
                "timestamp_utc": "2024-02-01T00:00:00+00:00",
                "event_type": "token_transfer",
                "asset": "USDC",
                "quantity": "100",
                "side": "out",
                "tx_id": "swap-tx-1",
                "wallet_address": "wallet-1",
            },
            {
                "timestamp_utc": "2024-02-01T00:00:00+00:00",
                "event_type": "token_transfer",
                "asset": "HNT",
                "quantity": "50",
                "side": "in",
                "tx_id": "swap-tx-1",
                "wallet_address": "wallet-1",
            },
        ],
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="USDC",
            price_eur=Decimal("0.92"),
            priced_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
            source="unit",
        )
    )
    TaxService(store).rebuild_fifo()

    report = TaxYearService(store).solana_stablecoin_swap_context_review(2024)

    assert report.events_count == 1
    assert report.missing_raw_evidence_count == 0
    assert report.rows[0].classification == "solana_swap_stablecoin_quote_disposal"
    assert report.rows[0].confidence == "high"
    assert report.rows[0].raw_evidence_count == 2
    assert report.rows[0].tx_assets == "HNT, USDC"
    assert report.rows[0].stable_tax_lines_count == 1
    assert report.rows[0].jupiter_quote_status == "verified"

    fx = TaxYearService(store).solana_stablecoin_fx_review(2024)
    assert fx.events_count == 1
    assert fx.missing_price_count == 0
    assert fx.market_price_count == 1
    assert fx.rows[0].stable_asset == "USDC"
    assert fx.rows[0].selected_price_eur == Decimal("0.920000000000000000")
    assert fx.rows[0].implied_stable_price_eur == Decimal("0.920000000000000000")
    assert fx.rows[0].review_reason == "stablecoin_fx_price_basis_ok"

    evidence = TaxYearService(store).evidence_report(2024)
    evidence_by_id = {item.evidence_id: item for item in evidence.items}
    assert evidence_by_id["tax-solana-stablecoin-swap-evidence"].record_count == 1
    assert evidence_by_id["tax-solana-stablecoin-swap-fifo-lines"].record_count == 1

    app = create_app(store)
    swap_csv_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/export/tax-solana-stablecoin-swap-evidence.csv"
    )
    swap_csv = swap_csv_route.endpoint(year=2024)
    swap_csv_text = swap_csv.body.decode("utf-8")
    assert "filename=tax-year-2024-solana-stablecoin-swap-evidence.csv" in swap_csv.headers["content-disposition"]
    assert "swap-tx-1" in swap_csv_text
    assert "solana_swap_stablecoin_quote_disposal" in swap_csv_text
    assert "stablecoin_fx_price_basis_ok" in swap_csv_text
    assert "/tmp/private" not in swap_csv_text
    assert "solana-swap.json" in swap_csv_text
    assert "steuerreport_ai_readonly.tmp.sqlite" not in swap_csv_text

    fifo_csv_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/export/tax-solana-stablecoin-swap-fifo-lines.csv"
    )
    fifo_csv = fifo_csv_route.endpoint(year=2024)
    fifo_csv_text = fifo_csv.body.decode("utf-8")
    assert "filename=tax-year-2024-solana-stablecoin-swap-fifo-lines.csv" in fifo_csv.headers["content-disposition"]
    assert "Tax_Line_ID" in fifo_csv_text
    assert "swap-tx-1" in fifo_csv_text
    assert "raw_import_row_available" in fifo_csv_text
    assert "/tmp/private" not in fifo_csv_text
    assert "opening.csv" in fifo_csv_text
    assert "solana-swap.json" in fifo_csv_text
    assert "steuerreport_ai_readonly.tmp.sqlite" not in fifo_csv_text

    year_package_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/export/tax-years/{year}/evidence-package.zip"
    )
    package_response = year_package_route.endpoint(2024)
    with ZipFile(BytesIO(package_response.body)) as package:
        names = set(package.namelist())
        assert "06_Solana_FIFO_Belege/tax-year-2024-solana-stablecoin-swap-evidence.csv" in names
        assert "06_Solana_FIFO_Belege/tax-year-2024-solana-stablecoin-swap-fifo-lines.csv" in names
        manifest = json.loads(package.read("00_Manifest/year-evidence-manifest.json").decode("utf-8"))
    manifest_paths = {file["path"] for file in manifest["files"]}
    assert "06_Solana_FIFO_Belege/tax-year-2024-solana-stablecoin-swap-evidence.csv" in manifest_paths
    assert "06_Solana_FIFO_Belege/tax-year-2024-solana-stablecoin-swap-fifo-lines.csv" in manifest_paths


def test_helium_swap_context_separates_solana_swap_from_rewards(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    opening = CsvRawImporter(store).import_text(
        source="manual-csv",
        filename="opening.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2024-01-01T00:00:00Z,USDC,100,buy,EUR,92\n"
        ),
    )
    RawNormalizer(store).normalize_batch(opening.batch_id)
    batch = CsvRawImporter(store).import_rows(
        source="solana_rpc",
        filename="solana-hnt-swap.json",
        file_hash="solana-hnt-swap",
        rows=[
            {
                "timestamp_utc": "2024-02-01T00:00:00+00:00",
                "event_type": "token_transfer",
                "asset": "USDC",
                "quantity": "100",
                "side": "out",
                "tx_id": "hnt-swap-tx",
                "wallet_address": "wallet-1",
            },
            {
                "timestamp_utc": "2024-02-01T00:00:00+00:00",
                "event_type": "token_transfer",
                "asset": "HNT",
                "quantity": "25",
                "side": "in",
                "tx_id": "hnt-swap-tx",
                "wallet_address": "wallet-1",
            },
        ],
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("2"),
            priced_at=datetime(2024, 2, 1, tzinfo=timezone.utc),
            source="unit",
        )
    )
    TaxService(store).rebuild_fifo()

    income = TaxYearService(store).income_report(2024)
    report = TaxYearService(store).helium_swap_context_review(2024)

    assert income.reward_income_eur == Decimal("0")
    assert report.events_count == 1
    assert report.total_context_value_eur == Decimal("50.00000000000000000000000000")
    assert report.total_reward_income_eur == Decimal("0")
    assert report.rows[0].asset == "HNT"
    assert report.rows[0].classification == "helium_swap_trading_context"
    assert report.rows[0].tax_treatment == "trading_fifo_not_reward"
    assert report.rows[0].review_reason == "helium_asset_normalized_as_solana_trade"
    assert report.rows[0].fifo_drilldown_endpoint == "/api/v1/tax-years/2024/asset-fifo-drilldown?asset=HNT"
    assert report.assets[0].asset == "HNT"
    assert report.assets[0].swap_context_events_count == 1
    assert report.assets[0].swap_context_quantity == Decimal("25.000000000000000000")

    evidence_review = TaxYearService(store).helium_swap_evidence_review(2024)
    assert evidence_review.tx_count == 1
    assert evidence_review.raw_evidence_ready_count == 1
    assert evidence_review.raw_evidence_missing_count == 0
    assert evidence_review.total_context_value_eur == Decimal("50.00000000000000000000000000")
    assert evidence_review.rows[0].tx_id == "hnt-swap-tx"
    assert evidence_review.rows[0].assets == "HNT, USDC"
    assert evidence_review.rows[0].raw_evidence_count == 2
    assert evidence_review.rows[0].raw_filenames == ["solana-hnt-swap.json"]
    assert evidence_review.rows[0].evidence_status == "raw_evidence_ready"
    assert evidence_review.rows[0].tax_treatment == "trading_fifo_not_reward"
    assert evidence_review.rows[0].fifo_drilldown_endpoint == "/api/v1/tax-years/2024/asset-fifo-drilldown?asset=HNT"

    evidence = TaxYearService(store).evidence_report(2024)
    evidence_by_id = {item.evidence_id: item for item in evidence.items}
    assert evidence_by_id["tax-helium-swap-context"].record_count == 1
    assert evidence_by_id["tax-helium-swap-context"].amount_eur == Decimal("0")
    assert evidence_by_id["tax-helium-swap-evidence-review"].record_count == 1
    assert evidence_by_id["tax-helium-swap-evidence-review"].status == "available"
    assert evidence_by_id["tax-helium-swap-alchemy-audit"].endpoint == "/api/v1/export/tax-helium-swap-alchemy-audit.json"
    assert evidence_by_id["tax-helium-swap-alchemy-audit"].required is True

    app = create_app(store)
    api_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/helium-swap-context"
    )
    api_response = api_route.endpoint(2024)
    assert api_response.data.events_count == 1
    assert api_response.data.rows[0].tax_treatment == "trading_fifo_not_reward"

    evidence_api_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/helium-swap-evidence-review"
    )
    evidence_api_response = evidence_api_route.endpoint(2024)
    assert evidence_api_response.data.tx_count == 1
    assert evidence_api_response.data.rows[0].evidence_status == "raw_evidence_ready"

    alchemy_api_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/helium-swap-alchemy-audit"
    )
    alchemy_api_response = alchemy_api_route.endpoint(2024)
    assert "tx_count" in alchemy_api_response.data
    assert "rows" in alchemy_api_response.data

    csv_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/export/tax-helium-swap-context.csv"
    )
    csv_response = csv_route.endpoint(year=2024)
    csv_text = csv_response.body.decode("utf-8")
    assert "filename=tax-year-2024-helium-swap-context.csv" in csv_response.headers["content-disposition"]
    assert "TX_ID" in csv_text
    assert "hnt-swap-tx" in csv_text
    assert "trading_fifo_not_reward" in csv_text
    assert "helium_asset_normalized_as_solana_trade" in csv_text

    evidence_csv_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/export/tax-helium-swap-evidence-review.csv"
    )
    evidence_csv_response = evidence_csv_route.endpoint(year=2024)
    evidence_csv_text = evidence_csv_response.body.decode("utf-8")
    assert "filename=tax-year-2024-helium-swap-evidence-review.csv" in evidence_csv_response.headers["content-disposition"]
    assert "Raw_Belege" in evidence_csv_text
    assert "hnt-swap-tx" in evidence_csv_text
    assert "raw_evidence_ready" in evidence_csv_text
    assert "solana-hnt-swap.json" in evidence_csv_text

    alchemy_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/export/tax-helium-swap-alchemy-audit.json"
    )
    alchemy_response = alchemy_route.endpoint()
    alchemy_payload = json.loads(alchemy_response.body.decode("utf-8"))
    assert "filename=tax-helium-swap-alchemy-audit.json" in alchemy_response.headers["content-disposition"]
    assert "methodology" in alchemy_payload
    assert str(alchemy_payload.get("rpc_url", "")).find("secret") == -1

    year_package_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/export/tax-years/{year}/evidence-package.zip"
    )
    package_response = year_package_route.endpoint(2024)
    with ZipFile(BytesIO(package_response.body)) as package:
        names = set(package.namelist())
        assert "06_Solana_FIFO_Belege/tax-year-2024-helium-swap-context.csv" in names
        assert "06_Solana_FIFO_Belege/tax-year-2024-helium-swap-evidence-review.csv" in names
        assert "06_Solana_FIFO_Belege/tax-year-2024-helium-swap-alchemy-audit.json" in names
        manifest = json.loads(package.read("00_Manifest/year-evidence-manifest.json").decode("utf-8"))
    manifest_paths = {file["path"] for file in manifest["files"]}
    assert "06_Solana_FIFO_Belege/tax-year-2024-helium-swap-context.csv" in manifest_paths
    assert "06_Solana_FIFO_Belege/tax-year-2024-helium-swap-evidence-review.csv" in manifest_paths
    assert "06_Solana_FIFO_Belege/tax-year-2024-helium-swap-alchemy-audit.json" in manifest_paths


def test_tax_declaration_guide_highlights_losses_and_hnt(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="hnt-loss.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2021-01-01T00:00:00Z,HNT,10,buy,EUR,100\n"
            "2021-06-01T00:00:00Z,HNT,-10,sell,EUR,40\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    TaxService(store).rebuild_fifo()

    guide = TaxYearService(store).declaration_guide(2021)

    assert guide.export_ready is True
    assert guide.realized_gain_loss_eur == Decimal("-60.000000000000000000000000000000000000")
    assert guide.hnt_gain_loss_eur == guide.realized_gain_loss_eur
    assert guide.loss_assets[0].asset == "HNT"
    assert any(entry.section == "HNT Schwerpunkt" and entry.sign == "loss" for entry in guide.entries)
    assert "/api/v1/export/evidence-package.zip" in guide.evidence_exports


def test_tax_payment_overview_summarizes_where_to_enter_values(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="payment-overview.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2020-01-01T00:00:00Z,SOL,1,buy,EUR,10\n"
            "2021-06-01T00:00:00Z,SOL,-1,sell,EUR,30\n"
            "2021-01-01T00:00:00Z,HNT,10,buy,EUR,100\n"
            "2021-06-01T00:00:00Z,HNT,-10,sell,EUR,40\n"
            "2021-07-01T00:00:00Z,HNT,5,mining,EUR,15\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    TaxService(store).rebuild_fifo()

    report = TaxYearService(store).payment_overview()
    row = next(item for item in report.rows if item.year == 2021)

    assert row.private_disposals_gain_loss_eur == Decimal("-60.000000000000000000000000000000000000")
    assert row.rewards_mining_staking_income_eur == Decimal("15.000000000000000000")
    assert row.declaration_bucket == "Anlage SO + Sonstige Einkuenfte/EUR"
    assert "Private Veraeusserungsgeschaefte" in row.where_to_enter
    assert "Verlust belegbar erfassen" in row.what_to_do
    assert "2021 | SO G/V -60.00 EUR | Rewards 15.00 EUR" in row.display_line
    assert row.tax_free_private_disposals_eur == Decimal("20.000000000000000000000000000000000000")
    assert {item.category for item in row.checklist} == {"eintragen", "beleg"}
    assert any(item.label == "Einzutragende Rewards / Mining / Staking" for item in row.checklist)
    assert any(item.label == "Steuerfrei nach Haltefrist" for item in row.checklist)
    assert any(item.target == "Anlage SO: Gewinn/Verlust aus Kryptowerten" for item in row.checklist)


def test_tax_year_filing_summary_explains_entry_targets(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="filing-summary.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2020-01-01T00:00:00Z,SOL,1,buy,EUR,10\n"
            "2021-06-01T00:00:00Z,SOL,-1,sell,EUR,30\n"
            "2021-01-01T00:00:00Z,HNT,10,buy,EUR,100\n"
            "2021-06-01T00:00:00Z,HNT,-10,sell,EUR,40\n"
            "2021-07-01T00:00:00Z,HNT,5,mining,EUR,15\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    TaxService(store).rebuild_fifo()
    store.add_review_decision(
        ReviewDecisionCreate(
            decision_type="price_gap_resolution",
            scope="price_gap:asset:HNT:year:2021:source:helium",
            title="HNT Preisbeleg 2021 akzeptiert",
            rationale="Manueller Preisbeleg fuer 2021 liegt vor.",
            evidence_ref="/api/v1/export/review-decisions.csv",
            actor="codex",
            source="unit-test",
            payload={
                "year": 2021,
                "asset": "HNT",
                "import_effect": "none",
                "ledger_effect": "none",
                "fifo_effect": "none",
                "tax_line_effect": "none",
            },
        )
    )
    store.add_review_decision(
        ReviewDecisionCreate(
            decision_type="token_risk_documentation",
            scope="token_risk:spam_review:asset:CBDC:mint:fake",
            title="Nicht jahresbezogen",
            rationale="Darf nicht in 2021 Filing Summary landen.",
            actor="codex",
            source="unit-test",
            payload={"asset": "CBDC"},
        )
    )

    report = TaxYearService(store).filing_summary(2021)
    by_topic = {line.topic: line for line in report.lines}

    assert report.export_ready is True
    assert "privater Verlust -60.00 EUR" in report.plain_language_summary
    assert report.taxable_private_disposals_eur == Decimal("-60.000000000000000000000000000000000000")
    assert report.rewards_mining_staking_income_eur == Decimal("15.000000000000000000")
    assert report.tax_free_private_disposals_eur == Decimal("20.000000000000000000000000000000000000")
    assert by_topic["private_disposal"].declaration_target.startswith("Anlage SO")
    assert by_topic["private_disposal"].tax_treatment == "steuerpflichtiger Verlust"
    assert by_topic["income"].evidence_ref == "/api/v1/export/tax-income-guide.csv"
    assert by_topic["tax_free"].declaration_target.startswith("Nicht in den steuerpflichtigen")
    assert by_topic["evidence"].evidence_ref == "/api/v1/export/evidence-package.zip"
    checklist_by_label = {item.label: item for item in report.checklist}
    assert checklist_by_label["Privates Veraeusserungsergebnis"].category == "eintragen"
    assert checklist_by_label["Einzutragende Rewards / Mining / Staking"].category == "eintragen"
    assert checklist_by_label["Veraeusserungen ausserhalb der privaten Jahresfrist"].category == "archivieren"
    assert checklist_by_label["Belegpaket"].category == "archivieren"
    assert "Jahr" in report.checklist_ascii
    assert "eintragen" in report.checklist_ascii
    assert len(report.review_decisions) == 1
    assert report.review_decisions[0].title == "HNT Preisbeleg 2021 akzeptiert"
    assert report.review_decisions[0].effect_summary == "Import: none | Ledger: none | FIFO: none | Tax-Lines: none"
    assert any(line.label == "Review-Entscheidungen mit Jahresbezug" for line in report.lines)
    assert "Einzutragende Rewards / Mining / Staking" in report.ascii_table


def test_tax_year_filing_matrix_summarizes_year_actions(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="filing-matrix.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2020-01-01T00:00:00Z,SOL,1,buy,EUR,10\n"
            "2021-06-01T00:00:00Z,SOL,-1,sell,EUR,30\n"
            "2021-07-01T00:00:00Z,HNT,5,mining,EUR,15\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    TaxService(store).rebuild_fifo()

    matrix = TaxYearService(store).filing_matrix(years=[2021])
    row = matrix.rows[0]

    assert row.year == 2021
    assert row.action_status == "review"
    assert row.taxable_private_disposals_eur == Decimal("0")
    assert row.tax_free_private_disposals_eur == Decimal("20.000000000000000000000000000000000000")
    assert row.rewards_mining_staking_income_eur == Decimal("15.000000000000000000")
    assert row.checklist_counts["eintragen"] == 1
    assert row.checklist_counts["archivieren"] == 3
    assert row.filing_checklist_csv_endpoint == "/api/v1/export/tax-years/2021/filing-checklist.csv"
    assert row.evidence_package_endpoint == "/api/v1/export/tax-years/2021/evidence-package.zip"
    assert matrix.ready_years == []
    assert matrix.review_years == [2021]
    assert matrix.blocked_years == []
    assert "Naechster Schritt" in matrix.ascii_table
    assert "SO 0.00 EUR" in row.display_line


def test_tax_year_filing_matrix_marks_conservative_snapshot_ready(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    snapshot_dir = tmp_path / "var" / "bmf_filing_readiness"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "latest_bmf_filing_readiness_2021_2025.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-22T00:00:00+00:00",
                "years": [
                    {
                        "year": 2024,
                        "filing_status": "conservative_appendix",
                        "status_label": "Konservativ belegbar mit Beilage",
                        "bmf_ready": False,
                        "can_file_with_conservative_appendix": True,
                        "blocking_gap_codes": [],
                        "review_gap_codes": ["external_or_unknown_origin_documented"],
                        "appendix_status": "review",
                        "appendix_items_count": 3,
                        "appendix_manual_evidence_required_count": 0,
                        "taxable_private_disposals_eur": "18490.21",
                        "rewards_mining_staking_income_eur": "1097.06",
                        "derivative_pnl_eur": "0",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    matrix = TaxYearService(store).filing_matrix()
    row = matrix.rows[0]

    assert row.year == 2024
    assert row.action_status == "conservative_ready"
    assert row.export_ready is True
    assert row.warnings_count == 1
    assert row.checklist_counts.get("pruefen", 0) == 0
    assert row.checklist_counts["beilegen"] == 1
    assert row.bmf_closure_appendix_manual_evidence_required_count == 0
    assert matrix.ready_years == []
    assert matrix.conservative_ready_years == [2024]
    assert matrix.review_years == []
    assert matrix.blocked_years == []
    assert "Konservativ belegbar" in row.next_action
    assert "conservative_ready" in matrix.ascii_table


def test_tax_year_filing_closure_overview_combines_final_actions(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    snapshot_dir = tmp_path / "var" / "bmf_filing_readiness"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "latest_bmf_filing_readiness_2021_2025.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-23T00:00:00+00:00",
                "years": [
                    {
                        "year": 2024,
                        "filing_status": "conservative_appendix",
                        "status_label": "Konservativ belegbar",
                        "bmf_ready": False,
                        "can_file_with_conservative_appendix": True,
                        "blocking_gap_codes": [],
                        "review_gap_codes": ["asset_fifo_quote_attribution_documented"],
                        "appendix_status": "ready",
                        "appendix_items_count": 2,
                        "appendix_manual_evidence_required_count": 0,
                        "taxable_private_disposals_eur": "18490.21",
                        "rewards_mining_staking_income_eur": "1097.06",
                        "derivative_pnl_eur": "-71.91",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    overview = TaxYearService(store).filing_closure_overview(years=[2024])
    row = overview.rows[0]

    assert row.year == 2024
    assert row.filing_status == "conservative_ready"
    assert row.private_disposals_gain_loss_eur == Decimal("18490.21")
    assert row.rewards_mining_staking_income_eur == Decimal("1097.06")
    assert row.derivative_pnl_eur == Decimal("-71.91")
    assert row.beilegen_count == 1
    assert row.pruefen_count == 1
    assert row.evidence_package_endpoint == "/api/v1/export/tax-years/2024/evidence-package.zip"
    assert overview.conservative_ready_years == [2024]
    assert overview.review_years == []
    assert overview.blocked_years == []
    assert overview.amendment_review_years == [2024]
    assert "18490.21 EUR" in overview.ascii_table


def test_tax_year_correction_map_guides_prior_year_review(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="correction-map.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2021-01-01T00:00:00Z,HNT,10,buy,EUR,100\n"
            "2021-06-01T00:00:00Z,HNT,-10,sell,EUR,40\n"
            "2021-07-01T00:00:00Z,HNT,5,mining,EUR,15\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    TaxService(store).rebuild_fifo()

    report = TaxYearService(store).year_correction_map(2021)
    by_label = {line.label: line for line in report.lines}

    assert report.amendment_review_recommended is True
    assert report.taxable_private_disposals_eur == Decimal("-60.000000000000000000000000000000000000")
    assert report.rewards_mining_staking_income_eur == Decimal("15.000000000000000000")
    assert by_label["Privates Veraeusserungsergebnis"].action_category == "korrigieren_pruefen"
    assert by_label["Einzutragende Rewards / Mining / Staking"].action_category == "korrigieren_pruefen"
    assert by_label["Belegpaket"].action_category == "archivieren"
    assert "Korrektur" in report.amendment_reason
    assert "2021 | korrigieren_pruefen | Privates Veraeusserungsergebnis" in report.ascii_table

    overview = TaxYearService(store).correction_map(years=[2021, 2022])
    assert overview.amendment_review_years == [2021]
    assert 2022 in overview.archive_only_years
    assert "Jahr | Status | Korrektur pruefen" in overview.ascii_table

    response = TestClient(create_app(store)).get("/api/v1/tax-years/2021/correction-map")
    assert response.status_code == 200
    assert response.json()["data"]["amendment_review_recommended"] is True

    all_response = TestClient(create_app(store)).get("/api/v1/tax-years/correction-map")
    assert all_response.status_code == 200
    assert "years" in all_response.json()["data"]

    csv_response = TestClient(create_app(store)).get("/api/v1/export/tax-years/2021/correction-map.csv")
    assert csv_response.status_code == 200
    assert "filename=tax-year-2021-correction-map.csv" in csv_response.headers["content-disposition"]
    assert "Action_Category,Topic,Label,Amount_EUR" in csv_response.text
    assert "korrigieren_pruefen,private_disposal,Privates Veraeusserungsergebnis,-60.00" in csv_response.text

    all_csv_response = TestClient(create_app(store)).get("/api/v1/export/tax-years/correction-map.csv")
    assert all_csv_response.status_code == 200
    assert "filename=tax-years-correction-map.csv" in all_csv_response.headers["content-disposition"]
    assert "Amendment_Review_Recommended" in all_csv_response.text


def test_tax_year_correction_map_uses_local_readiness_snapshot_for_single_year(tmp_path):
    snapshot_dir = tmp_path / "var" / "bmf_filing_readiness"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "latest_bmf_filing_readiness_2021_2025.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-22T00:00:00Z",
                "years": [
                    {
                        "year": 2024,
                        "filing_status": "conservative_appendix",
                        "status_label": "Konservativ belegbar",
                        "bmf_ready": False,
                        "can_file_with_conservative_appendix": True,
                        "appendix_status": "ready",
                        "appendix_items_count": 2,
                        "appendix_manual_evidence_required_count": 0,
                        "taxable_private_disposals_eur": "18490.205",
                        "rewards_mining_staking_income_eur": "1097.06",
                        "derivative_pnl_eur": "0",
                        "blocking_gap_codes": [],
                        "review_gap_codes": ["wallet_fifo_delta_present"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    report = TaxYearService(store).year_correction_map(2024)

    assert report.filing_status == "Konservativ belegbar"
    assert report.taxable_private_disposals_eur == Decimal("18490.205")
    assert report.rewards_mining_staking_income_eur == Decimal("1097.06")
    assert report.amendment_review_recommended is True
    assert [line.topic for line in report.lines[:2]] == ["private_disposal", "income"]
    assert report.lines[-1].evidence_ref == "/api/v1/export/tax-years/2024/evidence-package.zip"
    assert "Snapshot" in report.methodology


def test_tax_year_correction_map_ignores_stale_snapshot_when_live_summary_differs(tmp_path):
    snapshot_dir = tmp_path / "var" / "bmf_filing_readiness"
    snapshot_dir.mkdir(parents=True)
    (snapshot_dir / "latest_bmf_filing_readiness_2021_2025.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-22T00:00:00Z",
                "years": [
                    {
                        "year": 2025,
                        "filing_status": "conservative_appendix",
                        "status_label": "Konservativ belegbar",
                        "taxable_private_disposals_eur": "-923.64",
                        "rewards_mining_staking_income_eur": "45.44",
                        "derivative_pnl_eur": "0",
                        "blocking_gap_codes": [],
                        "review_gap_codes": ["wallet_fifo_delta_present"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="stale-correction-map.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2025-01-01T00:00:00Z,HNT,10,buy,EUR,100\n"
            "2025-06-01T00:00:00Z,HNT,-10,sell,EUR,40\n"
            "2025-07-01T00:00:00Z,HNT,5,mining,EUR,15\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    TaxService(store).rebuild_fifo()

    report = TaxYearService(store).year_correction_map(2025)
    overview = TaxYearService(store).correction_map()
    filing = TaxYearService(store).filing_matrix()

    assert report.taxable_private_disposals_eur == Decimal("-60.000000000000000000000000000000000000")
    assert report.rewards_mining_staking_income_eur == Decimal("15.000000000000000000")
    assert "Snapshot" in report.methodology
    row = next(item for item in overview.years if item.year == 2025)
    assert row.taxable_private_disposals_eur == report.taxable_private_disposals_eur
    filing_row = next(item for item in filing.rows if item.year == 2025)
    assert filing_row.taxable_private_disposals_eur == report.taxable_private_disposals_eur


def test_tax_year_filing_summary_surfaces_cex_fifo_anchor_status(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="filing-cex-anchor.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2025-01-01T00:00:00Z,SOL,1,buy,EUR,100\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    TaxService(store).rebuild_fifo()

    class FakeAnchorFeasibility:
        decisions_count = 2
        evidence_ready_count = 2
        anchor_ready_count = 2
        anchor_missing_count = 0

    def fake_anchor_feasibility(self, year, *, source_exchange, target_cex, network):
        assert year == 2025
        assert source_exchange == "bitget"
        assert target_cex == "binance"
        assert network == "SOL"
        return FakeAnchorFeasibility()

    monkeypatch.setattr(
        "steuerreport_v2.domain.tax_wallet_fifo.WalletFifoPreviewService.cex_exchange_outflow_anchor_feasibility",
        fake_anchor_feasibility,
    )

    report = TaxYearService(store).filing_summary(2025)
    anchor_line = next(line for line in report.lines if line.label == "CEX-FIFO-Anker Bitget -> Binance")

    assert anchor_line.topic == "evidence"
    assert anchor_line.amount_eur is None
    assert anchor_line.tax_treatment == "steuerneutraler Depotwechsel mit FIFO-Fortschreibung"
    assert "2 von 2" in anchor_line.note
    assert "CEX-FIFO-Anker Bitget -> Binance" in report.ascii_table


def test_tax_year_evidence_report_maps_year_to_export_artifacts(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="helium",
        filename="evidence-map.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2021-01-01T00:00:00Z,HNT,10,buy,EUR,100\n"
            "2021-06-01T00:00:00Z,HNT,-10,sell,EUR,40\n"
            "2021-07-01T00:00:00Z,HNT,5,mining,EUR,15\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    TaxService(store).rebuild_fifo()

    report = TaxYearService(store).evidence_report(2021)
    items = {item.evidence_id: item for item in report.items}

    assert report.export_ready is True
    assert items["tax-lines"].endpoint == "/api/v1/export/tax-lines.csv"
    assert items["tax-lines"].record_count == 1
    assert items["tax-lines"].amount_eur == Decimal("-60.000000000000000000000000000000000000")
    assert items["tax-income-guide"].category == "eintragen"
    assert items["tax-income-guide"].record_count == 1
    assert items["tax-payment-overview"].file_format == "json"
    assert items["review-decisions"].endpoint == "/api/v1/export/review-decisions.csv"
    assert items["review-decisions"].record_count == 0
    assert items["review-decisions"].status == "empty"
    assert items["evidence-package"].file_format == "zip"


def test_tax_year_bmf_closure_appendix_documents_conservative_provenance(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    deposit_batch = store.create_import_batch(
        ImportBatchCreate(source="binance", filename="Binance-Deposit-History.xlsx", file_hash="bmf-appendix-deposit")
    )
    deposit_raw = store.add_raw_object(
        deposit_batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {
                    "Address": "Ftf2dgeRpBrPFmbd4wQWWqSjCmRjGes1GzNXtxKETeLW",
                    "Amount": "1.4",
                    "Coin": "SOL",
                    "Network": "SOL",
                    "Status": "Completed",
                    "TXID": "bmf-appendix-sol-tx",
                    "Time": "24-01-12 07:09:33",
                }
            ),
        ),
    )
    opening_batch = store.create_import_batch(
        ImportBatchCreate(
            source="opening-balance-scope-test",
            filename="opening-balance-adjustments.csv",
            file_hash="bmf-appendix-opening",
        )
    )
    opening_raw = store.add_raw_object(
        opening_batch.batch_id,
        RawObjectCreate(
            row_number=2,
            payload_json=json.dumps(
                {
                    "time": "2024-02-15T07:28:31",
                    "asset": "USDT",
                    "amount": "1988.008263",
                    "type": "opening transfer",
                    "account": "wallet",
                }
            ),
        ),
    )
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2024, 1, 12, 7, 9, 33, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("1.4"),
                account="binance",
                tx_id="bmf-appendix-sol-tx",
                raw_object_id=deposit_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2024, 1, 12, 7, 10, tzinfo=timezone.utc),
                event_type="trade",
                asset="USDT",
                quantity=Decimal("100"),
                quote_asset="SOL",
                quote_quantity=Decimal("1.4"),
                account="binance",
            ),
            CanonicalEventCreate(
                source="opening-balance-scope-test",
                event_time=datetime(2024, 2, 15, 7, 28, 31, tzinfo=timezone.utc),
                event_type="transfer",
                asset="USDT",
                quantity=Decimal("1988.008263"),
                account="wallet",
                raw_object_id=opening_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="manual-csv",
                event_time=datetime(2024, 12, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="EUR",
                quantity=Decimal("1000"),
                quote_asset="USDT",
                quote_quantity=Decimal("1988.008263"),
                account="wallet",
            ),
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("90"),
            priced_at=datetime(2024, 1, 12, tzinfo=timezone.utc),
            source="unit",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.93"),
            priced_at=datetime(2024, 2, 15, tzinfo=timezone.utc),
            source="unit",
        )
    )
    TaxService(store).rebuild_fifo()

    appendix = TaxYearService(store).bmf_closure_appendix(2024)
    response = TestClient(create_app(store)).get("/api/v1/tax-years/2024/bmf-closure-appendix")
    items = {item.category: item for item in appendix.items}

    assert appendix.status == "ready"
    assert appendix.items_count == 2
    assert appendix.manual_evidence_required_count == 0
    assert appendix.conservative_items_count == 2
    assert appendix.can_file_with_conservative_appendix is True
    assert items["cex_deposit_sender_ownership"].closure_status == "unverified_cex_deposit_sender"
    assert "nicht als Eigenwallet-Transfer" in items["cex_deposit_sender_ownership"].recommended_tax_treatment
    assert items["cex_deposit_sender_ownership"].manual_evidence_required is False
    assert items["opening_balance"].manual_evidence_required is False
    assert response.status_code == 200
    assert response.json()["data"]["items_count"] == 2

    filing_summary = TaxYearService(store).filing_summary(2024)
    appendix_line = next(line for line in filing_summary.lines if line.topic == "appendix")

    assert filing_summary.bmf_closure_appendix_status == "ready"
    assert filing_summary.bmf_closure_appendix_items_count == 2
    assert filing_summary.bmf_closure_appendix_manual_evidence_required_count == 0
    assert filing_summary.can_file_with_conservative_appendix is True
    assert appendix_line.label == "BMF-Abschlussbeilage Herkunft"
    assert appendix_line.tax_treatment == "konservativ belegbar"
    assert appendix_line.declaration_target.startswith("Nicht als Betrag eintragen")
    assert appendix_line.evidence_ref == "/api/v1/tax-years/2024/bmf-closure-appendix"
    assert "2 Herkunftsposition" in appendix_line.note
    assert "BMF-Abschlussbeilage Herkunft" in filing_summary.ascii_table
    appendix_checklist = next(item for item in filing_summary.checklist if item.source_topic == "appendix")
    assert appendix_checklist.category == "beilegen"
    assert appendix_checklist.evidence_ref == "/api/v1/tax-years/2024/bmf-closure-appendix"
    assert "keinen zusaetzlichen Betrag eintragen" in appendix_checklist.action
    assert "BMF-Abschlussbeilage Herkunft" in filing_summary.checklist_ascii

    checklist_response = TestClient(create_app(store)).get("/api/v1/export/tax-years/2024/filing-checklist.csv")
    assert checklist_response.status_code == 200
    assert "filename=tax-year-2024-filing-checklist.csv" in checklist_response.headers["content-disposition"]
    checklist_csv = checklist_response.text
    assert "Category,Label,Amount_EUR,Action" in checklist_csv
    assert "beilegen,BMF-Abschlussbeilage Herkunft" in checklist_csv

    package_response = TestClient(create_app(store)).get("/api/v1/export/tax-years/2024/evidence-package.zip")
    assert package_response.status_code == 200
    with ZipFile(BytesIO(package_response.content)) as package:
        names = set(package.namelist())
        assert "02_Steuerliche_CSVs/tax-year-2024-bmf-closure-appendix.json" in names
        assert "02_Steuerliche_CSVs/tax-year-2024-filing-checklist.csv" in names
        assert "02_Steuerliche_CSVs/tax-year-2024-correction-map.json" in names
        assert "02_Steuerliche_CSVs/tax-year-2024-correction-map.csv" in names
        assert "01_Transaktionen/tax-year-2024-canonical-events.csv" in names
        assert "01_Transaktionen/tax-year-2024-unknown-event-review.csv" in names
        assert "01_Transaktionen/tax-year-2024-reward-mining-staking-events.csv" in names
        packaged_checklist_csv = package.read("02_Steuerliche_CSVs/tax-year-2024-filing-checklist.csv").decode("utf-8")
        assert "beilegen,BMF-Abschlussbeilage Herkunft" in packaged_checklist_csv
        canonical_events_csv = package.read("01_Transaktionen/tax-year-2024-canonical-events.csv").decode("utf-8")
        assert "Event_ID,Zeitpunkt_UTC,Quelle" in canonical_events_csv
        assert "Export_Klassifizierung,Steuerwirkung_Hinweis" in canonical_events_csv
        assert "manual-csv" in canonical_events_csv
        unknown_review_csv = package.read("01_Transaktionen/tax-year-2024-unknown-event-review.csv").decode("utf-8")
        assert "Export_Klassifizierung,Steuerwirkung_Hinweis" in unknown_review_csv
        reward_events_csv = package.read(
            "01_Transaktionen/tax-year-2024-reward-mining-staking-events.csv"
        ).decode("utf-8")
        assert "Steuerlicher_Hinweis" in reward_events_csv
        correction_map = json.loads(package.read("02_Steuerliche_CSVs/tax-year-2024-correction-map.json").decode("utf-8"))
        assert correction_map["year"] == 2024
        correction_map_csv = package.read("02_Steuerliche_CSVs/tax-year-2024-correction-map.csv").decode("utf-8")
        assert "Action_Category,Topic,Label,Amount_EUR" in correction_map_csv
        manifest = json.loads(package.read("00_Manifest/year-evidence-manifest.json").decode("utf-8"))
    assert "/api/v1/tax-years/2024/bmf-closure-appendix" in manifest["required_refs"]
    assert "/api/v1/tax-years/2024/correction-map" in manifest["required_refs"]
    assert "/api/v1/export/tax-years/2024/correction-map.csv" in manifest["required_refs"]
    assert "/api/v1/export/tax-years/2024/filing-checklist.csv" in manifest["required_refs"]


def test_tax_year_evidence_report_counts_year_review_decisions(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_review_decision(
        ReviewDecisionCreate(
            decision_type="parity_finding",
            scope="parity:year:2024:asset:SOL:status:diff",
            title="SOL Differenz akzeptiert",
            rationale="Belegter V2-Korrekturpfad.",
            evidence_ref="docs/test.md",
            actor="codex",
            source="unit-test",
            payload={"decision_status": "accepted_difference"},
        )
    )

    report = TaxYearService(store).evidence_report(2024)
    items = {item.evidence_id: item for item in report.items}

    assert items["review-decisions"].record_count == 1
    assert items["review-decisions"].status == "available"
    assert items["review-decisions"].required is True


def test_tax_year_evidence_report_surfaces_stablecoin_fx_tax_impact(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "impact"
    artifact_dir.mkdir()
    (artifact_dir / "latest_USDT_2024_tax_impact.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-06-26T20:55:53+00:00",
                "replacement_plan": {
                    "rows_count": 6,
                    "ready_rows": 6,
                    "missing_rows": 0,
                    "applied_rows": 6,
                },
                "baseline": {
                    "taxable_gain_loss_eur": "17187.535700018292083739",
                    "stablecoin_gain_loss_eur": "448.568882903768959597",
                },
                "patched": {
                    "taxable_gain_loss_eur": "17164.365258034450328223",
                    "stablecoin_gain_loss_eur": "420.843483359799231191",
                },
                "delta": {
                    "taxable_gain_loss_eur": "-23.170441983841755516",
                    "stablecoin_gain_loss_eur": "-27.725399543969728406",
                    "unmatched_disposals": 0,
                },
                "conclusion": "replacement_changes_tax_result_review_required",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(PriceQualityService, "TAX_IMPACT_ARTIFACT_DIR", artifact_dir)
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    report = TaxYearService(store).evidence_report(2024)
    items = {item.evidence_id: item for item in report.items}

    item = items["stablecoin-fx-tax-impact"]
    assert item.category == "pruefen"
    assert item.status == "review"
    assert item.required is True
    assert item.record_count == 6
    assert item.amount_eur == Decimal("-23.170441983841755516")
    assert item.endpoint == "/api/v1/prices/quality/stablecoin-fx-tax-impact-latest?asset=USDT&year=2024"


def test_tax_year_evidence_report_surfaces_cex_exchange_outflow_evidence(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    evidence_dir = tmp_path / "var/cex_deposit_sender_ownership"
    evidence_dir.mkdir(parents=True)
    artifact = evidence_dir / "20260621T064725Z_2025_binance_solana_sender_ownership.json"
    artifact.write_text(
        json.dumps(
            {
                "generated_at": "2026-06-21T06:47:25+00:00",
                "year": 2025,
                "cex": "binance",
                "network": "SOL",
                "summary": {
                    "transactions": 1,
                    "status_counts": {"UNVERIFIED_THIRD_PARTY": 1},
                    "tax_neutral_candidates": 0,
                    "unverified_third_party": 1,
                },
                "results": [
                    {
                        "txid": "bitget-deposit-tx",
                        "timestamp_utc": "2025-06-15T07:45:46+00:00",
                        "asset": "SOL",
                        "amount": "7.0700475",
                        "provider_status": "alchemy",
                        "onchain_sender": "CySAjqmKLQCT729gypchz3zbYSSNh85rXx8Tk9e7PC7P",
                        "deposit_address": "binance-deposit-address",
                        "cex_account": "binance",
                        "fifo_transfer_status": "missing",
                        "decision_layer": {
                            "binance_deposit_address_owned": True,
                            "sender_is_own_wallet": False,
                            "exchange_deposit_transfer_neutral": False,
                        },
                        "final_tax_status": "UNVERIFIED_THIRD_PARTY",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    batch = store.create_import_batch(
        ImportBatchCreate(source="bitget", filename="bitget-withdrawal-api.csv", file_hash="unit:bitget-cex-evidence")
    )
    store.add_raw_objects(
        batch.batch_id,
        [
            RawObjectCreate(
                row_number=1,
                payload_json=json.dumps(
                    {
                        "record_type": "bitget_withdrawal_evidence",
                        "asset": "SOL",
                        "amount": "7.0760475",
                        "size": "7.0760475",
                        "fee": "-0.006",
                        "tradeId": "bitget-deposit-tx",
                        "tx_id": "bitget-deposit-tx",
                        "toAddress": "binance-deposit-address",
                        "chain": "SOL",
                        "network": "SOL",
                        "account": "bitget",
                        "uTime": "1749973546000",
                        "status": "success",
                    }
                ),
            )
        ],
    )
    store.add_review_decision(
        ReviewDecisionCreate(
            decision_type="cex_exchange_outflow",
            scope="cex_exchange_outflow:year:2025:source:bitget:target:binance:network:SOL:deposit_tx:bitget-deposit-tx",
            title="CEX-zu-CEX-Transfer steuerneutral dokumentiert",
            rationale="Unit-Test Decision.",
            evidence_ref="/api/v1/tax-years/2025/cex-exchange-outflow-evidence?source_exchange=bitget&target_cex=binance&network=SOL",
            actor="codex",
            source="unit-test",
            payload={
                "decision_status": "transfer_neutral_fifo_carry_forward_reviewed",
                "year": 2025,
                "source_exchange": "bitget",
                "target_cex": "binance",
                "network": "SOL",
                "deposit_txid": "bitget-deposit-tx",
                "asset": "SOL",
                "deposit_amount": "7.0700475",
                "exchange_outflow_raw_object_id": "raw-1",
                "exchange_outflow_tx_id": "bitget-deposit-tx",
                "exchange_outflow_amount": "7.0700475",
                "exchange_outflow_fee": "-0.006",
                "amount_delta": "0",
                "fifo_effect": "carry_forward_documented_pending_fifo_anchor",
                "tax_line_effect": "none",
            },
        )
    )

    report = TaxYearService(store).evidence_report(2025)
    items = {item.evidence_id: item for item in report.items}
    item = items["cex-exchange-outflow-evidence"]
    anchor_item = items["cex-exchange-outflow-anchor-feasibility"]

    assert item.category == "beleg"
    assert item.record_count == 1
    assert item.status == "available"
    assert item.required is True
    assert anchor_item.category == "pruefen"
    assert anchor_item.record_count == 1
    assert anchor_item.status == "review"
    assert anchor_item.required is True


def test_tax_year_closed_year_marks_unmatched_historical(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.upsert_admin_setting(
        AdminSettingWrite(
            key="runtime.review.closed_tax_years",
            value_json="[2021]",
        )
    )
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="trades.csv",
        content="time,asset,amount,type,quote_asset,quote_quantity\n2021-01-01T00:00:00Z,ETH,-1,sell,EUR,1000\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    store.add_price_point(
        PricePointCreate(
            asset="ETH",
            price_eur=Decimal("1000"),
            priced_at=datetime(2021, 1, 1, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    TaxService(store).rebuild_fifo()

    year = TaxYearService(store).detail(2021)

    assert year.state == "historical_open"
    assert year.is_closed_historical_year is True
    assert year.export_blocked is False
    assert year.unmatched_disposals == 1
    assert year.issues[0].blocks_export is False


def test_tax_year_api_routes_are_registered(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    app = create_app(store)
    summary_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/summary"
    )
    detail_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}"
    )
    guide_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/declaration-guide"
    )
    guide_html_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/declaration-guide.html"
    )
    filing_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/filing-summary"
    )
    filing_html_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/filing-summary.html"
    )
    correction_map_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/correction-map"
    )
    income_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/income-guide"
    )
    drivers_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/drivers"
    )
    gain_loss_reality_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/gain-loss-reality-check"
    )
    gain_evidence_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/gain-evidence-review"
    )
    asset_fifo_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/asset-fifo-drilldown"
    )
    asset_fifo_plausibility_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/asset-fifo-plausibility"
    )
    asset_fifo_correction_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/asset-fifo-correction-review"
    )
    turnover_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/turnover-audit"
    )
    evidence_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/evidence"
    )
    evidence_html_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/evidence.html"
    )
    external_inflows_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/external-inflows"
    )
    payment_overview_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/payment-overview"
    )
    filing_matrix_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/filing-matrix"
    )
    filing_closure_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/filing-closure-overview"
    )
    reward_trading_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/reward-trading-separation"
    )
    loss_realization_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax/loss-realization-planner"
    )
    correction_map_summary_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/correction-map"
    )
    turnover_summary_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/turnover-audit-summary"
    )
    solana_program_summary_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/solana-program-income-review"
    )
    solana_program_year_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/solana-program-income-review"
    )
    stablecoin_fifo_summary_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/stablecoin-fifo-review"
    )
    stablecoin_fifo_year_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/stablecoin-fifo-review"
    )
    stablecoin_quote_leg_summary_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/stablecoin-quote-leg-review"
    )
    stablecoin_quote_leg_year_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/stablecoin-quote-leg-review"
    )
    solana_stablecoin_swap_summary_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/solana-stablecoin-swap-context"
    )
    solana_stablecoin_swap_year_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/solana-stablecoin-swap-context"
    )
    solana_stablecoin_fx_summary_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/solana-stablecoin-fx-review"
    )
    solana_stablecoin_fx_year_route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/v1/tax-years/{year}/solana-stablecoin-fx-review"
    )

    assert summary_route.endpoint().status == "ok"
    assert detail_route.endpoint(2021).status == "ok"
    assert guide_route.endpoint(2021).status == "ok"
    guide_html_response = guide_html_route.endpoint(2021)
    assert guide_html_response.media_type == "text/html; charset=utf-8"
    assert "Steuerjahr 2021" in guide_html_response.body.decode("utf-8")
    assert filing_route.endpoint(2021).status == "ok"
    filing_html_response = filing_html_route.endpoint(2021)
    assert filing_html_response.media_type == "text/html; charset=utf-8"
    assert "Steuerjahr 2021" in filing_html_response.body.decode("utf-8")
    assert "Finanzamt-Checkliste" in filing_html_response.body.decode("utf-8")
    assert correction_map_route.endpoint(2021).status == "ok"
    assert income_route.endpoint(2021).status == "ok"
    assert drivers_route.endpoint(2021).status == "ok"
    assert gain_loss_reality_route.endpoint(2021).status == "ok"
    assert gain_evidence_route.endpoint(2021).status == "ok"
    assert asset_fifo_route.endpoint(2021, "BTC").status == "ok"
    assert asset_fifo_plausibility_route.endpoint(2021).status == "ok"
    assert asset_fifo_correction_route.endpoint(2021).status == "ok"
    assert turnover_route.endpoint(2021).status == "ok"
    assert evidence_route.endpoint(2021).status == "ok"
    evidence_html_response = evidence_html_route.endpoint(2021)
    assert evidence_html_response.media_type == "text/html; charset=utf-8"
    assert "Steuerjahr 2021" in evidence_html_response.body.decode("utf-8")
    assert "Belege und Nachweise" in evidence_html_response.body.decode("utf-8")
    assert external_inflows_route.endpoint(2021).status == "ok"
    assert payment_overview_route.endpoint().status == "ok"
    assert filing_matrix_route.endpoint().status == "ok"
    assert filing_closure_route.endpoint().status == "ok"
    assert reward_trading_route.endpoint().status == "ok"
    assert loss_realization_route.endpoint().status == "ok"
    assert correction_map_summary_route.endpoint().status == "ok"
    assert turnover_summary_route.endpoint().status == "ok"
    assert solana_program_summary_route.endpoint().status == "ok"
    assert solana_program_year_route.endpoint(2021).status == "ok"
    assert stablecoin_fifo_summary_route.endpoint().status == "ok"
    assert stablecoin_fifo_year_route.endpoint(2021).status == "ok"
    assert stablecoin_quote_leg_summary_route.endpoint().status == "ok"
    assert stablecoin_quote_leg_year_route.endpoint(2021).status == "ok"
    assert solana_stablecoin_swap_summary_route.endpoint().status == "ok"
    assert solana_stablecoin_swap_year_route.endpoint(2021).status == "ok"
    assert solana_stablecoin_fx_summary_route.endpoint().status == "ok"
    assert solana_stablecoin_fx_year_route.endpoint(2021).status == "ok"


def test_tax_year_declaration_guide_returns_html_for_browser_accept(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))

    html_response = client.get(
        "/api/v1/tax-years/2021/declaration-guide",
        headers={"Accept": "text/html,application/xhtml+xml"},
    )
    assert html_response.status_code == 200
    assert html_response.headers["content-type"] == "text/html; charset=utf-8"
    assert "Steuerjahr 2021" in html_response.text
    assert "Finanzamt-Checkliste" in html_response.text

    json_response = client.get(
        "/api/v1/tax-years/2021/declaration-guide",
        headers={"Accept": "application/json"},
    )
    assert json_response.status_code == 200
    assert json_response.headers["content-type"].startswith("application/json")
    assert json_response.json()["status"] == "ok"


def test_tax_year_evidence_returns_html_for_browser_accept(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))

    html_response = client.get(
        "/api/v1/tax-years/2021/evidence",
        headers={"Accept": "text/html,application/xhtml+xml"},
    )
    assert html_response.status_code == 200
    assert html_response.headers["content-type"] == "text/html; charset=utf-8"
    assert "Steuerjahr 2021" in html_response.text
    assert "Belege und Nachweise" in html_response.text

    json_response = client.get(
        "/api/v1/tax-years/2021/evidence",
        headers={"Accept": "application/json"},
    )
    assert json_response.status_code == 200
    assert json_response.headers["content-type"].startswith("application/json")
    assert json_response.json()["status"] == "ok"
