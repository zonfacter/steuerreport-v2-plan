from datetime import datetime, timezone
from decimal import Decimal
from io import BytesIO
import json
from zipfile import ZipFile

from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.divorce import DivorceEqualizationService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


def test_divorce_equalization_summary_splits_pre_cutoff_and_direct_eur_invest(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc),
                event_type="transfer",
                asset="EUR",
                quantity=Decimal("100"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 1, 0, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("1"),
                quote_asset="EUR",
                quote_quantity=Decimal("100"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 7, 1, 0, 0, tzinfo=timezone.utc),
                event_type="transfer",
                asset="EUR",
                quantity=Decimal("50"),
                account="binance",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 7, 1, 0, 0, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="EUR",
                quantity=Decimal("50"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 7, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="ETH",
                quantity=Decimal("2"),
                quote_asset="EUR",
                quote_quantity=Decimal("50"),
                account="Spot",
            ),
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset="BTC",
            price_eur=Decimal("100"),
            priced_at=datetime(2025, 6, 13, tzinfo=timezone.utc),
            source="test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="BTC",
            price_eur=Decimal("120"),
            priced_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
            source="test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="ETH",
            price_eur=Decimal("20"),
            priced_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
            source="test",
        )
    )
    TaxService(store).rebuild_fifo()
    BalanceLedgerBuilder(store).rebuild()

    report = DivorceEqualizationService(store).summary()

    assert report.cutoff_portfolio_value_eur == Decimal("100.000000000000000000")
    assert report.valuation_portfolio_value_eur == Decimal("160.000000000000000000")
    assert report.gross_portfolio_change_eur == Decimal("60.000000000000000000")
    assert report.gross_portfolio_change_without_review_assets_eur == Decimal("60.000000000000000000")
    assert report.valuation_review_value_eur == Decimal("0")
    assert report.valuation_dust_value_eur == Decimal("0")
    assert report.valuation_value_without_review_assets_eur == Decimal("160.000000000000000000")
    assert report.adjusted_gain_loss_without_review_assets_eur == Decimal("10.000000000000000000")
    assert "2025-03-06" in report.bmf_tax_boundary.bmf_reference_url
    assert report.bmf_tax_boundary.tax_methodology_summary_endpoint == "/api/v1/tax-methodology/summary"
    assert "/api/v1/tax-years/{year}/methodology" == report.bmf_tax_boundary.tax_year_methodology_endpoint_template
    assert any("familienrechtliche" in note for note in report.bmf_tax_boundary.boundary_notes)
    assert isinstance(report.live_reconciliation, list)
    assert len(report.accounts) == 1
    assert report.accounts[0].account == "Spot"
    assert report.accounts[0].cutoff_value_eur == Decimal("100.000000000000000000")
    assert report.accounts[0].valuation_value_eur == Decimal("160.000000000000000000")
    assert report.accounts[0].gross_change_eur == Decimal("60.000000000000000000")
    assert report.accounts[0].asset_labels_cutoff == ["BTC"]
    assert report.accounts[0].asset_labels_valuation == ["BTC", "ETH"]
    assert report.marital_pre_cutoff.open_cost_basis_eur == Decimal("100.000000000000000000")
    assert report.marital_pre_cutoff.open_value_eur == Decimal("120.000000000000000000")
    assert report.marital_pre_cutoff.total_gain_loss_eur == Decimal("20.000000000000000000")
    assert report.post_cutoff_direct_eur_invest.open_cost_basis_eur == Decimal("50.000000000000000000")
    assert report.post_cutoff_direct_eur_invest.open_value_eur == Decimal("40.000000000000000000")
    assert report.post_cutoff_direct_eur_invest.total_gain_loss_eur == Decimal("-10.000000000000000000")
    assert report.post_cutoff_all_lots.total_gain_loss_eur == Decimal("-10.000000000000000000")


def test_divorce_equalization_summary_counts_sold_pre_cutoff_lot_after_cutoff(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc),
                event_type="transfer",
                asset="EUR",
                quantity=Decimal("100"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 1, 0, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("1"),
                quote_asset="EUR",
                quote_quantity=Decimal("100"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 7, 1, tzinfo=timezone.utc),
                event_type="trade",
                asset="BTC",
                quantity=Decimal("-1"),
                quote_asset="EUR",
                quote_quantity=Decimal("150"),
                account="Spot",
            ),
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset="BTC",
            price_eur=Decimal("100"),
            priced_at=datetime(2025, 6, 13, tzinfo=timezone.utc),
            source="test",
        )
    )
    TaxService(store).rebuild_fifo()
    BalanceLedgerBuilder(store).rebuild()

    report = DivorceEqualizationService(store).summary()

    assert report.cutoff_portfolio_value_eur == Decimal("100.000000000000000000")
    assert report.marital_pre_cutoff.open_lots_count == 0
    assert report.marital_pre_cutoff.sold_lines_count == 1
    assert report.marital_pre_cutoff.sold_cost_basis_eur == Decimal("100.000000000000000000")
    assert report.marital_pre_cutoff.sold_proceeds_eur == Decimal("150.000000000000000000")
    assert report.marital_pre_cutoff.realized_gain_loss_eur == Decimal("50.000000000000000000")
    assert report.marital_pre_cutoff.total_gain_loss_eur == Decimal("50.000000000000000000")


def test_divorce_equalization_summary_marks_low_confidence_wallet_tokens(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = "G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY"
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana",
                event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="CBDC",
                quantity=Decimal("1000"),
                account=wallet,
            ),
            CanonicalEventCreate(
                source="solana",
                event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("2"),
                account=wallet,
            ),
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset="CBDC",
            price_eur=Decimal("0.05"),
            priced_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
            source="test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("10"),
            priced_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
            source="test",
        )
    )
    TaxService(store).rebuild_fifo()
    BalanceLedgerBuilder(store).rebuild()

    report = DivorceEqualizationService(store).summary()
    account = next(row for row in report.accounts if row.account == wallet)

    assert account.classification == "solana_main_wallet"
    assert account.valuation_value_eur == Decimal("70.000000000000000000")
    assert account.valuation_review_value_eur == Decimal("50.000000000000000000")
    assert account.valuation_value_without_review_assets_eur == Decimal("20.000000000000000000")
    assert report.valuation_review_value_eur == Decimal("50.000000000000000000")
    assert report.valuation_dust_value_eur == Decimal("0")
    assert report.valuation_value_without_review_assets_eur == Decimal("20.000000000000000000")
    assert report.gross_portfolio_change_without_review_assets_eur == Decimal("20.000000000000000000")
    assert report.adjusted_gain_loss_without_review_assets_eur == Decimal("20.000000000000000000")
    assert account.valuation_assets[0].asset == "CBDC"
    assert account.valuation_assets[0].valuation_flag == "review_low_confidence_token"

    csv_text = DivorceEqualizationService(store).valuation_tokens_csv()
    assert "account,classification,valuation_basis,asset,quantity,value_eur,valuation_flag" in csv_text
    assert f"{wallet},solana_main_wallet,current_live_anchored_snapshot,CBDC" in csv_text
    assert "review_low_confidence_token" in csv_text

    accounts_csv = DivorceEqualizationService(store).accounts_csv()
    assert "account,classification,valuation_basis,cutoff_value_eur,valuation_value_eur" in accounts_csv
    assert f"{wallet},solana_main_wallet,current_live_anchored_snapshot,0,70.000000000000000000" in accounts_csv
    assert "50.000000000000000000" in accounts_csv
    live_csv = DivorceEqualizationService(store).live_reconciliation_csv()
    assert "source_group,source_type,asset,ledger_quantity,ledger_value_eur" in live_csv

    package_bytes = DivorceEqualizationService(store).evidence_package_zip()
    with ZipFile(BytesIO(package_bytes)) as package:
        names = set(package.namelist())
        assert "00_Manifest/divorce-equalization-summary.json" in names
        assert "00_Manifest/methodik-und-bmf-abgrenzung.json" in names
        assert "01_Konten/divorce-equalization-accounts.csv" in names
        assert "02_Token/divorce-equalization-valuation-tokens.csv" in names
        assert "03_Live_Abgleich/live-reconciliation.json" in names
        assert "03_Live_Abgleich/live-reconciliation.csv" in names
        methodology = json.loads(package.read("00_Manifest/methodik-und-bmf-abgrenzung.json").decode("utf-8"))
        assert methodology["read_only"] is True
        assert methodology["bmf_tax_boundary"]["tax_methodology_summary_endpoint"] == "/api/v1/tax-methodology/summary"
