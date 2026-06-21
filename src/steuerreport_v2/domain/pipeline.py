from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from steuerreport_v2.contracts.pipeline import (
    DemoSeedResult,
    ImportDeleteResult,
    ImportRunResult,
    PipelineResult,
)
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.derived_prices import DerivedPriceService
from steuerreport_v2.domain.derivatives import DerivativesManager
from steuerreport_v2.domain.flows import FlowService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


class PipelineService:
    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def rebuild_all(self) -> PipelineResult:
        normalized_events = 0
        for batch in self.store.list_import_batches():
            normalized_events += len(RawNormalizer(self.store).normalize_batch(batch.batch_id))
        return self._rebuild_ledgers(normalized_events)

    def rebuild_after_import(self, batch_id: str) -> ImportRunResult:
        batch = self.store.get_import_batch(batch_id)
        if batch is None:
            raise ValueError(f"unknown import batch: {batch_id}")
        _, report = RawNormalizer(self.store).normalize_batch_with_report(batch_id)
        pipeline = self._rebuild_ledgers(report.created_events)
        return ImportRunResult(
            batch_id=batch_id,
            imported_rows=batch.raw_object_count,
            normalized_events=report.created_events,
            skipped_raw_objects=report.skipped_raw_objects,
            pipeline=pipeline,
        )

    def delete_import_and_rebuild(self, batch_id: str) -> ImportDeleteResult:
        deleted = self.store.delete_import_batch(batch_id)
        pipeline = self.rebuild_all()
        return ImportDeleteResult(
            batch_id=batch_id,
            deleted=deleted,
            pipeline=pipeline,
        )

    def _rebuild_ledgers(self, normalized_events: int) -> PipelineResult:
        DerivedPriceService(self.store).rebuild_from_event_quotes()
        balance_entries = len(BalanceLedgerBuilder(self.store).rebuild())
        flow_entries = len(FlowService(self.store).rebuild())
        tax_result = TaxService(self.store).rebuild_fifo()
        derivative_result = DerivativesManager(self.store).rebuild()
        gate = ReviewService(self.store).gate()
        return PipelineResult(
            normalized_events=normalized_events,
            balance_entries=balance_entries,
            flow_entries=flow_entries,
            tax_lines=len(tax_result.tax_lines),
            derivative_lines=len(derivative_result.lines),
            review_issues_open=gate.issues_open,
            allow_export=gate.allow_export,
        )

    def seed_demo(self) -> DemoSeedResult:
        self.store.delete_import_batches_by_source("demo")
        self.store.delete_price_points_by_source("demo")
        content = (
            "time,asset,amount,type,quote_asset,quote_quantity,account\n"
            "2020-12-31T23:59:00Z,EUR,10000,deposit,,,pionex-demo\n"
            "2021-01-01T00:00:00Z,BTC,1,buy,EUR,10000,pionex-demo\n"
            "2021-04-28T10:00:00Z,USDT,1000,deposit,EUR,900,pionex-demo\n"
            "2021-06-01T00:00:00Z,BTC,-0.4,sell,EUR,6000,pionex-demo\n"
            "2021-07-01T00:00:00Z,USDT,-250,withdrawal,EUR,225,pionex-demo\n"
        )
        batch = CsvRawImporter(self.store).import_text(
            source="demo",
            filename="demo.csv",
            content=content,
        )
        priced_at = datetime(2021, 7, 1, tzinfo=timezone.utc)
        self.store.add_price_point(
            PricePointCreate(
                asset="BTC",
                price_eur=Decimal("30000"),
                priced_at=priced_at,
                source="demo",
            )
        )
        self.store.add_price_point(
            PricePointCreate(
                asset="USDT",
                price_eur=Decimal("0.90"),
                priced_at=priced_at,
                source="demo",
            )
        )
        pipeline = self.rebuild_all()
        return DemoSeedResult(
            batch_id=batch.batch_id,
            imported_rows=batch.raw_object_count,
            pipeline=pipeline,
        )
