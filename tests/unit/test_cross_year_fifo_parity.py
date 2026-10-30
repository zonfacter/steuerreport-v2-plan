from decimal import Decimal

from steuerreport_v2.contracts.parity import V1ReferenceMetricCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.parity import V1ParityService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_years import TaxYearService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer


def test_synthetic_cross_year_fifo_keeps_prior_year_basis_and_matches_reference(
    tmp_path,
):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    content = (
        "time,asset,amount,type,quote_asset,quote_quantity,account\n"
        "2024-12-15T12:00:00Z,SYNTH,10,buy,EUR,100,Spot\n"
        "2025-06-15T12:00:00Z,SYNTH,-4,sell,EUR,80,Spot\n"
    )
    importer = CsvRawImporter(store)
    batch = importer.import_text(
        source="binance", filename="cross-year-synthetic.csv", content=content
    )
    duplicate = importer.import_text(
        source="binance", filename="same-content-different-name.csv", content=content
    )

    assert duplicate.batch_id == batch.batch_id
    assert len(store.list_import_batches()) == 1
    assert batch.raw_object_count == 2
    RawNormalizer(store).normalize_batch(batch.batch_id)

    # Independent arithmetic: EUR 100 / 10 units = EUR 10 per unit;
    # selling 4 for EUR 80 uses EUR 40 basis and realizes EUR 40 gain.
    # The 6 remaining units retain EUR 60 of the original EUR 100 basis.
    reference_metrics = [
        ("quantity_disposed", "SYNTH", Decimal("4")),
        ("acquisition_cost_eur", "EUR", Decimal("40")),
        ("disposal_proceeds_eur", "EUR", Decimal("80")),
        ("gain_loss_eur", "EUR", Decimal("40")),
    ]
    for metric, unit, value in reference_metrics:
        store.add_v1_reference_metric(
            V1ReferenceMetricCreate(
                scope="tax",
                metric=metric,
                unit=unit,
                value=value,
                year=2025,
                asset="SYNTH",
                source="synthetic-independent-arithmetic",
            )
        )

    tax = TaxService(store)
    rebuilt = tax.rebuild_fifo()
    assert rebuilt.unmatched_disposals == 0

    canonical = store.list_canonical_events()
    assert len(canonical) == 2
    assert {event.event_time.date().isoformat() for event in canonical} == {
        "2024-12-15",
        "2025-06-15",
    }

    years = TaxYearService(store)
    year_2024 = years.detail(2024)
    year_2025 = years.detail(2025)
    assert year_2024.tax_lines_count == 0
    assert year_2024.realized_gain_loss_eur == Decimal("0")
    assert year_2025.tax_lines_count == 1
    assert year_2025.acquisition_cost_eur == Decimal("40")
    assert year_2025.taxable_disposal_proceeds_eur == Decimal("80")
    assert year_2025.realized_gain_loss_eur == Decimal("40")

    tax_lines = tax.list_tax_lines()
    lots = tax.list_tax_lots()
    assert len(tax_lines) == 1
    assert len(lots) == 1
    tax_line = tax_lines[0]
    lot = lots[0]
    assert tax_line.asset == lot.asset == "SYNTH"
    assert tax_line.lot_id == lot.lot_id
    assert tax_line.quantity == Decimal("4")
    assert tax_line.acquisition_cost_eur == Decimal("40")
    assert tax_line.disposal_proceeds_eur == Decimal("80")
    assert tax_line.gain_loss_eur == Decimal("40")
    assert lot.acquired_at.isoformat().startswith("2024-12-15T12:00:00")
    assert lot.quantity_total == Decimal("10")
    assert lot.quantity_remaining == Decimal("6")
    assert lot.cost_basis_eur_total == Decimal("100")
    assert lot.quantity_remaining * lot.cost_basis_eur_total / lot.quantity_total == Decimal(
        "60"
    )

    drilldown = years.asset_fifo_drilldown(2025, asset="SYNTH")
    assert drilldown.lines_count == 1
    fifo_line = drilldown.lines[0]
    assert fifo_line.acquired_at.startswith("2024-12-15T12:00:00")
    assert fifo_line.disposed_at.startswith("2025-06-15T12:00:00")
    assert fifo_line.acquisition_raw is not None
    assert fifo_line.acquisition_raw.source == "binance"
    assert fifo_line.acquisition_raw.batch_id == batch.batch_id
    assert fifo_line.acquisition_raw.filename == "cross-year-synthetic.csv"
    assert fifo_line.acquisition_raw.row_number == 1
    assert fifo_line.disposal_raw is not None
    assert fifo_line.disposal_raw.source == "binance"
    assert fifo_line.disposal_raw.batch_id == batch.batch_id
    assert fifo_line.disposal_raw.row_number == 2
    assert fifo_line.acquisition_event is not None
    assert fifo_line.disposal_event is not None
    assert fifo_line.acquisition_event.raw_object_id == fifo_line.acquisition_raw.raw_object_id
    assert fifo_line.disposal_event.raw_object_id == fifo_line.disposal_raw.raw_object_id

    comparison = V1ParityService(store).compare()
    assert comparison.compared == 4
    assert comparison.matches == 4
    assert comparison.differences == 0
    assert comparison.missing_v2 == 0
    assert all(
        row.status == "match" and row.difference == Decimal("0")
        for row in comparison.rows
    )

    def semantic_snapshot():
        year_values = tuple(
            (
                year,
                detail.tax_lines_count,
                detail.realized_gain_loss_eur,
                detail.taxable_disposal_proceeds_eur,
                detail.acquisition_cost_eur,
            )
            for year in (2024, 2025)
            for detail in (years.detail(year),)
        )
        line_values = tuple(
            sorted(
                (
                    line.asset,
                    line.quantity,
                    line.acquisition_cost_eur,
                    line.disposal_proceeds_eur,
                    line.gain_loss_eur,
                    line.holding_days,
                )
                for line in tax.list_tax_lines()
            )
        )
        lot_values = tuple(
            sorted(
                (
                    lot.asset,
                    lot.quantity_total,
                    lot.quantity_remaining,
                    lot.cost_basis_eur_total,
                )
                for lot in tax.list_tax_lots()
            )
        )
        parity = V1ParityService(store).compare()
        parity_deltas = tuple(
            sorted(
                (
                    row.reference.metric,
                    row.reference.unit,
                    row.reference.year,
                    row.reference.asset,
                    row.status,
                    row.v2_value,
                    row.difference,
                )
                for row in parity.rows
            )
        )
        return year_values, line_values, lot_values, parity_deltas

    first_run_semantics = semantic_snapshot()
    second_run = tax.rebuild_fifo()
    assert second_run.unmatched_disposals == 0
    assert semantic_snapshot() == first_run_semantics
