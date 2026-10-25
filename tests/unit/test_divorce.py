from datetime import date, datetime, timezone
from decimal import Decimal
from io import BytesIO
import json
from types import SimpleNamespace
from zipfile import ZipFile

from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.divorce import DivorceEqualizationService
from steuerreport_v2.domain.divorce_capital_flows import DivorceCapitalFlowService
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


def test_divorce_equalization_reuses_end_asset_portfolio_for_coinbase(
    tmp_path,
    monkeypatch,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    original = PortfolioService.as_of_snapshot
    calls = []

    def counted(service, as_of):
        calls.append(as_of)
        return original(service, as_of)

    monkeypatch.setattr(PortfolioService, "as_of_snapshot", counted)

    DivorceEqualizationService(store).summary()

    assert len(calls) == 2


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
            priced_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
            source="test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="ETH",
            price_eur=Decimal("20"),
            priced_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
            source="test",
        )
    )
    TaxService(store).rebuild_fifo()
    BalanceLedgerBuilder(store).rebuild()

    report = DivorceEqualizationService(store).summary()

    assert report.stichtage.separation_date == date(2025, 6, 13)
    assert report.stichtage.end_asset_date == date(2026, 7, 24)
    assert report.stichtage.timezone == "Europe/Berlin"
    assert report.stichtage.court_evidence_status == "pending_document"
    assert report.cutoff_at == datetime(
        2025, 6, 13, 21, 59, 59, 999999, tzinfo=timezone.utc
    )
    assert report.valuation_at == datetime(
        2026, 7, 24, 21, 59, 59, 999999, tzinfo=timezone.utc
    )
    assert report.cutoff_portfolio_value_eur == Decimal("100.000000000000000000")
    assert report.valuation_portfolio_value_eur == Decimal("160.000000000000000000")
    assert report.gross_portfolio_change_eur == Decimal("60.000000000000000000")
    assert report.gross_portfolio_change_without_review_assets_eur == Decimal(
        "60.000000000000000000"
    )
    assert report.valuation_review_value_eur == Decimal("0")
    assert report.valuation_dust_value_eur == Decimal("0")
    assert report.valuation_value_without_review_assets_eur == Decimal(
        "160.000000000000000000"
    )
    assert report.adjusted_gain_loss_without_review_assets_eur == Decimal(
        "10.000000000000000000"
    )
    assert report.capital_flow_gate.flow_adjusted_change_eur == Decimal(
        "10.000000000000000000"
    )
    assert report.capital_flow_gate.confirmed_contributions_eur == Decimal(
        "50.000000000000000000"
    )
    assert report.capital_flow_gate.capital_origin_pending_count == 1
    assert report.capital_flow_gate.status == "review"
    assert "2025-03-06" in report.bmf_tax_boundary.bmf_reference_url
    assert (
        report.bmf_tax_boundary.tax_methodology_summary_endpoint
        == "/api/v1/tax-methodology/summary"
    )
    assert (
        "/api/v1/tax-years/{year}/methodology"
        == report.bmf_tax_boundary.tax_year_methodology_endpoint_template
    )
    assert any(
        "familienrechtliche" in note for note in report.bmf_tax_boundary.boundary_notes
    )
    assert isinstance(report.live_reconciliation, list)
    assert len(report.accounts) == 1
    assert report.accounts[0].account == "Binance"
    assert report.accounts[0].source_accounts == ["Spot"]
    assert report.accounts[0].classification == "exchange_binance"
    assert report.accounts[0].valuation_basis == "historical_ledger_as_of"
    assert report.accounts[0].cutoff_value_eur == Decimal("100.000000000000000000")
    assert report.accounts[0].valuation_value_eur == Decimal("160.000000000000000000")
    assert report.accounts[0].gross_change_eur == Decimal("60.000000000000000000")
    assert report.accounts[0].external_invest_since_cutoff_eur == Decimal(
        "50.000000000000000000"
    )
    assert report.accounts[0].adjusted_gain_loss_eur == Decimal("10.000000000000000000")
    assert report.accounts[0].asset_labels_cutoff == ["BTC"]
    assert report.accounts[0].asset_labels_valuation == ["BTC", "ETH"]
    assert report.marital_pre_cutoff.open_cost_basis_eur == Decimal(
        "100.000000000000000000"
    )
    assert report.marital_pre_cutoff.open_value_eur == Decimal("120.000000000000000000")
    assert report.marital_pre_cutoff.total_gain_loss_eur == Decimal(
        "20.000000000000000000"
    )
    assert report.post_cutoff_direct_eur_invest.open_cost_basis_eur == Decimal(
        "50.000000000000000000"
    )
    assert report.post_cutoff_direct_eur_invest.open_value_eur == Decimal(
        "40.000000000000000000"
    )
    assert report.post_cutoff_direct_eur_invest.total_gain_loss_eur == Decimal(
        "-10.000000000000000000"
    )
    assert report.post_cutoff_all_lots.total_gain_loss_eur == Decimal(
        "-10.000000000000000000"
    )
    assert report.cutoff_price_gate.strict_ready is True
    assert report.valuation_price_gate.strict_ready is True

    capital_flows_csv = DivorceEqualizationService(store).capital_flows_csv()
    assert capital_flows_csv.startswith("row_type,flow_id,event_id,event_time")
    assert "contribution,binance_fiat_deposits" in capital_flows_csv


def test_divorce_capital_flow_gate_separates_internal_transfer_and_material_review(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("2"),
                account="wallet-a",
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2025, 7, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("-1"),
                account="wallet-a",
                tx_id="internal-transfer",
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2025, 7, 1, 0, 0, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("1"),
                account="wallet-b",
                tx_id="internal-transfer",
            ),
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2025, 7, 2, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("-0.2"),
                account="wallet-b",
                tx_id="unresolved-outflow",
            ),
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("10"),
            priced_at=datetime(2025, 6, 13, tzinfo=timezone.utc),
            source="test",
        )
    )

    gate = DivorceCapitalFlowService(store).report(
        cutoff_at=datetime(2025, 6, 13, 21, 59, 59, tzinfo=timezone.utc),
        valuation_at=datetime(2026, 7, 24, 21, 59, 59, tzinfo=timezone.utc),
        opening_value_eur=Decimal("20"),
        closing_value_eur=Decimal("18"),
        binance_contributions_eur=Decimal("0"),
        confirmed_onramp_contributions_eur=Decimal("0"),
        provisional_onramp_contributions_eur=Decimal("0"),
        materiality_threshold_eur=Decimal("1"),
    )

    assert gate.status == "blocked"
    assert gate.strict_ready is False
    assert gate.outflows_count == 2
    assert gate.internal_outflows_count == 1
    assert gate.material_review_outflows_count == 1
    assert gate.internal_transfer_value_eur == Decimal("10.000000000000000000")
    assert gate.review_outflow_value_eur == Decimal("2.000000000000000000")
    assert gate.flow_adjusted_change_eur == Decimal("-2")
    assert gate.flow_adjusted_change_if_all_review_outflows_are_external_eur == Decimal(
        "0E-18"
    )
    assert [row.classification for row in gate.outflows] == [
        "internal_transfer_confirmed",
        "external_distribution_review",
    ]


def test_divorce_capital_flow_gate_does_not_treat_missing_price_as_zero(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana_rpc",
                event_time=datetime(2025, 7, 2, tzinfo=timezone.utc),
                event_type="transfer",
                asset="UNKNOWN",
                quantity=Decimal("-5"),
                account="wallet",
                tx_id="unpriced-outflow",
            ),
        ]
    )

    gate = DivorceCapitalFlowService(store).report(
        cutoff_at=datetime(2025, 6, 13, 21, 59, 59, tzinfo=timezone.utc),
        valuation_at=datetime(2026, 7, 24, 21, 59, 59, tzinfo=timezone.utc),
        opening_value_eur=Decimal("10"),
        closing_value_eur=Decimal("10"),
        binance_contributions_eur=Decimal("0"),
        confirmed_onramp_contributions_eur=Decimal("0"),
        provisional_onramp_contributions_eur=Decimal("0"),
        materiality_threshold_eur=Decimal("1"),
    )

    assert gate.outflows[0].value_eur is None
    assert gate.outflows[0].material is True
    assert gate.unpriced_review_outflows_count == 1
    assert gate.flow_adjusted_change_if_all_review_outflows_are_external_eur is None
    assert any("keinen EUR-Wert" in finding for finding in gate.findings)


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
    assert report.marital_pre_cutoff.sold_cost_basis_eur == Decimal(
        "100.000000000000000000"
    )
    assert report.marital_pre_cutoff.sold_proceeds_eur == Decimal(
        "150.000000000000000000"
    )
    assert report.marital_pre_cutoff.realized_gain_loss_eur == Decimal(
        "50.000000000000000000"
    )
    assert report.marital_pre_cutoff.total_gain_loss_eur == Decimal(
        "50.000000000000000000"
    )


def test_divorce_equalization_uses_receipted_moonpay_cost_and_only_estimates_unmatched(
    tmp_path,
    monkeypatch,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    class MoonpayReceiptStub:
        def __init__(self, _store):
            pass

        def report(self, *, as_of):
            assert as_of == datetime(
                2026, 7, 24, 21, 59, 59, 999999, tzinfo=timezone.utc
            )
            return SimpleNamespace(
                items=[
                    SimpleNamespace(
                        event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
                        strict_ready=True,
                        cost_basis_eur=Decimal("250"),
                        provisional_market_value_eur=Decimal("240"),
                    ),
                    SimpleNamespace(
                        event_time=datetime(2026, 2, 1, tzinfo=timezone.utc),
                        strict_ready=False,
                        cost_basis_eur=None,
                        provisional_market_value_eur=Decimal("100"),
                    ),
                ]
            )

    monkeypatch.setattr(
        "steuerreport_v2.domain.divorce.MoonpayReceiptService",
        MoonpayReceiptStub,
    )

    report = DivorceEqualizationService(store).summary()

    assert report.confirmed_onramp_invest_since_cutoff_eur == Decimal("250")
    assert report.provisional_onramp_invest_since_cutoff_eur == Decimal("100")
    assert report.confirmed_external_invest_since_cutoff_eur == Decimal("250")
    assert report.net_external_invest_since_cutoff_eur == Decimal("350")
    assert report.capital_flow_gate.confirmed_contributions_eur == Decimal("250")
    assert report.capital_flow_gate.provisional_contributions_eur == Decimal("100")
    assert report.capital_flow_gate.flow_adjusted_change_eur == Decimal("-350")
    moonpay_rows = [
        row
        for row in report.capital_flow_gate.contributions
        if row.flow_id.startswith("moonpay_apple_pay_onramp")
    ]
    assert moonpay_rows
    assert all(
        row.evidence_ref == "/api/v1/tax/moonpay-receipts" for row in moonpay_rows
    )


def test_divorce_equalization_summary_marks_low_confidence_wallet_tokens(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    wallet = "6K9n7yyZHxgQ9ycSak29WtVitZy1ZNTF3Jms9CErqEwP"
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
    with store.connect() as con:
        con.execute(
            """
            insert into jupiter_token_metadata_cache (
                mint, symbol, name, decimals, icon, token_program, is_verified,
                organic_score, organic_score_label, holder_count, liquidity_usd,
                usd_price, market_cap_usd, risk_status, source,
                discovered_sources_json, refreshed_at, jupiter_updated_at
            ) values (
                '2KFZCkfxj1Us8YRQZa5vktSxy3GPzFZvVhWj91n8Fv2J',
                'CBDC', 'Central Bank Digital Currency', 2, null, null, false,
                0, 'low', 10, 1000, 0.1, 1000, 'spam_review',
                'jupiter_tokens_v2', '[]', ?, null
            )
            """,
            [datetime.now(timezone.utc)],
        )
    store.add_price_point(
        PricePointCreate(
            asset="CBDC",
            price_eur=Decimal("0.05"),
            priced_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
            source="test",
        )
    )
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("10"),
            priced_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
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
    assert account.valuation_value_without_review_assets_eur == Decimal(
        "20.000000000000000000"
    )
    assert report.valuation_review_value_eur == Decimal("50.000000000000000000")
    assert report.valuation_dust_value_eur == Decimal("0")
    assert report.valuation_value_without_review_assets_eur == Decimal(
        "20.000000000000000000"
    )
    assert report.gross_portfolio_change_without_review_assets_eur == Decimal(
        "20.000000000000000000"
    )
    assert report.adjusted_gain_loss_without_review_assets_eur == Decimal(
        "20.000000000000000000"
    )
    assert account.valuation_assets[0].asset == "CBDC"
    assert account.valuation_assets[0].valuation_flag == "review_low_confidence_token"

    csv_text = DivorceEqualizationService(store).valuation_tokens_csv()
    assert (
        "snapshot,snapshot_at,account,source_accounts,classification,valuation_basis"
        in csv_text
    )
    assert (
        f"valuation,2026-07-24T21:59:59.999999+00:00,{wallet},{wallet},solana_main_wallet,historical_ledger_as_of,CBDC"
        in csv_text
    )
    assert "price_age_days,price_status" in csv_text
    assert "review_low_confidence_token" in csv_text

    accounts_csv = DivorceEqualizationService(store).accounts_csv()
    assert (
        "account,source_accounts,classification,valuation_basis,cutoff_value_eur,valuation_value_eur"
        in accounts_csv
    )
    assert (
        f"{wallet},{wallet},solana_main_wallet,historical_ledger_as_of,0,70.000000000000000000"
        in accounts_csv
    )
    assert "50.000000000000000000" in accounts_csv
    live_csv = DivorceEqualizationService(store).live_reconciliation_csv()
    assert "source_group,source_type,asset,ledger_quantity,ledger_value_eur" in live_csv

    package_bytes = DivorceEqualizationService(store).evidence_package_zip()
    with ZipFile(BytesIO(package_bytes)) as package:
        names = set(package.namelist())
        assert "02_Token/stichtag-token-valuation-decisions.csv" in names
        assert "00_Manifest/divorce-equalization-summary.json" in names
        assert "00_Manifest/methodik-und-bmf-abgrenzung.json" in names
        assert "01_Konten/divorce-equalization-accounts.csv" in names
        assert "02_Token/divorce-equalization-valuation-tokens.csv" in names
        assert "02_Token/valuation-price-gates.json" in names
        assert "03_Live_Abgleich/live-reconciliation.json" in names
        assert "03_Live_Abgleich/live-reconciliation.csv" in names
        assert "04_Vermoegensfluss/capital-flow-reconciliation.json" in names
        assert "04_Vermoegensfluss/capital-flow-reconciliation.csv" in names
        assert "04_Vermoegensfluss/service-route-evidence.json" in names
        assert "04_Vermoegensfluss/inheritance-origin.json" in names
        assert "04_Vermoegensfluss/inheritance-origin.csv" in names
        assert "04_Vermoegensfluss/inheritance-credit-evidence.csv" in names
        assert "04_Vermoegensfluss/trade-republic-document-evidence.csv" in names
        assert "04_Vermoegensfluss/formal-inheritance-document-evidence.csv" in names
        assert "04_Vermoegensfluss/coinbase-history-valuation-evidence.csv" in names
        methodology = json.loads(
            package.read("00_Manifest/methodik-und-bmf-abgrenzung.json").decode("utf-8")
        )
        assert methodology["read_only"] is True
        assert (
            methodology["bmf_tax_boundary"]["tax_methodology_summary_endpoint"]
            == "/api/v1/tax-methodology/summary"
        )


def test_divorce_equalization_respects_explicit_valuation_end_and_stable_exchange_accounts(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 1, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="BTC",
                quantity=Decimal("1"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2025, 2, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="ETH",
                quantity=Decimal("2"),
                account="Funding",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2026, 6, 15, 12, tzinfo=timezone.utc),
                event_type="transfer",
                asset="EUR",
                quantity=Decimal("25"),
                account="binance",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2026, 6, 16, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("10"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2026, 6, 16, tzinfo=timezone.utc),
                event_type="transfer",
                asset="EUR",
                quantity=Decimal("100"),
                account="binance",
            ),
        ]
    )
    for asset, price in (("BTC", "100"), ("ETH", "10"), ("SOL", "5")):
        store.add_price_point(
            PricePointCreate(
                asset=asset,
                price_eur=Decimal(price),
                priced_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
                source="test",
            )
        )
    TaxService(store).rebuild_fifo()
    BalanceLedgerBuilder(store).rebuild()

    report = DivorceEqualizationService(store).summary(
        cutoff_at=datetime(2025, 6, 13, 23, 59, 59, tzinfo=timezone.utc),
        valuation_at=datetime(2026, 6, 15, 23, 59, 59, tzinfo=timezone.utc),
    )

    assert report.valuation_portfolio_value_eur == Decimal("120.000000000000000000")
    assert report.fiat_deposits_since_cutoff_eur == Decimal("25.000000000000000000")
    assert len(report.accounts) == 1
    assert report.accounts[0].account == "Binance"
    assert report.accounts[0].source_accounts == ["Funding", "Spot"]
    assert "SOL" not in report.accounts[0].asset_labels_valuation


def test_divorce_local_date_uses_berlin_end_of_day_in_utc(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2026, 7, 24, 20, tzinfo=timezone.utc),
                event_type="transfer",
                asset="BTC",
                quantity=Decimal("1"),
                account="Spot",
            ),
            CanonicalEventCreate(
                source="binance",
                event_time=datetime(2026, 7, 24, 22, 30, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("2"),
                account="Spot",
            ),
        ]
    )
    for asset, price in (("BTC", "100"), ("SOL", "10")):
        store.add_price_point(
            PricePointCreate(
                asset=asset,
                price_eur=Decimal(price),
                priced_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
                source="test",
            )
        )
    TaxService(store).rebuild_fifo()
    BalanceLedgerBuilder(store).rebuild()

    report = DivorceEqualizationService(store).summary()

    assert report.valuation_at == datetime(
        2026, 7, 24, 21, 59, 59, 999999, tzinfo=timezone.utc
    )
    assert report.valuation_portfolio_value_eur == Decimal("100.000000000000000000")
    assert report.accounts[0].asset_labels_valuation == ["BTC"]


def test_divorce_valuation_gate_blocks_stale_and_missing_material_prices(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="solana",
                event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="SOL",
                quantity=Decimal("2"),
                account="wallet",
            ),
            CanonicalEventCreate(
                source="solana",
                event_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="UNKNOWN",
                quantity=Decimal("1"),
                account="wallet",
            ),
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset="SOL",
            price_eur=Decimal("10"),
            priced_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
            source="test",
        )
    )
    TaxService(store).rebuild_fifo()
    BalanceLedgerBuilder(store).rebuild()

    report = DivorceEqualizationService(store).summary()

    assert report.valuation_price_gate.strict_ready is False
    assert report.valuation_price_gate.stale_price_count == 1
    assert report.valuation_price_gate.missing_price_count == 1
    assert report.valuation_price_gate.affected_assets == ["SOL", "UNKNOWN"]
