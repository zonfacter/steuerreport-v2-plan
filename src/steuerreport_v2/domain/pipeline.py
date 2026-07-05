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
        self._suppress_solana_rpc_duplicate_reward_income_events()
        self._carry_forward_solana_rpc_legacy_helium_claim_rewards()
        return self._rebuild_ledgers(normalized_events)

    def rebuild_after_import(self, batch_id: str) -> ImportRunResult:
        batch = self.store.get_import_batch(batch_id)
        if batch is None:
            raise ValueError(f"unknown import batch: {batch_id}")
        _, report = RawNormalizer(self.store).normalize_batch_with_report(batch_id)
        self._suppress_solana_rpc_duplicate_reward_income_events()
        self._carry_forward_solana_rpc_legacy_helium_claim_rewards()
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

    def _suppress_solana_rpc_duplicate_reward_income_events(self) -> int:
        with self.store.connect() as con:
            suppressed = con.execute(
                """
                with duplicate_income as (
                    select income.event_id
                    from canonical_events income
                    join canonical_events reward
                      on reward.source = income.source
                     and reward.tx_id = income.tx_id
                     and reward.event_time = income.event_time
                     and reward.asset = income.asset
                     and reward.quantity = income.quantity
                     and coalesce(reward.account, '') = coalesce(income.account, '')
                     and reward.event_type = 'reward'
                    where income.source = 'solana_rpc'
                      and income.event_type = 'income'
                      and income.asset in ('HNT', 'IOT', 'MOBILE')
                      and income.tx_id is not null
                )
                update canonical_events
                   set event_type = 'unknown',
                       quantity = 0,
                       quote_asset = null,
                       quote_quantity = null,
                       fee_asset = null,
                       fee_quantity = null,
                       confidence = 0.70
                 where event_id in (select event_id from duplicate_income)
                returning event_id
                """
            ).fetchall()
        return len(suppressed)

    def _carry_forward_solana_rpc_legacy_helium_claim_rewards(self) -> int:
        with self.store.connect() as con:
            carried = con.execute(
                """
                with legacy as (
                    select
                        extract(year from event_time)::integer as tax_year,
                        asset,
                        sum(quantity) as legacy_quantity
                    from canonical_events
                    where source = 'helium'
                      and event_type = 'mining'
                      and asset in ('HNT', 'IOT', 'MOBILE')
                      and quantity > 0
                    group by 1, 2
                ),
                solana as (
                    select
                        extract(year from event_time)::integer as tax_year,
                        asset,
                        sum(quantity) as solana_quantity
                    from canonical_events
                    where source = 'solana_rpc'
                      and event_type = 'reward'
                      and asset in ('HNT', 'IOT', 'MOBILE')
                      and quantity > 0
                    group by 1, 2
                ),
                matched as (
                    select solana.tax_year, solana.asset
                    from solana
                    join legacy
                      on legacy.tax_year = solana.tax_year
                     and legacy.asset = solana.asset
                    where solana.tax_year = 2024
                      and legacy.legacy_quantity > 0
                      and solana.solana_quantity > 0
                      and abs(solana.solana_quantity - legacy.legacy_quantity)
                          / greatest(legacy.legacy_quantity, solana.solana_quantity)
                          <= 0.10
                )
                update canonical_events event
                   set event_type = 'transfer',
                       quote_asset = null,
                       quote_quantity = null,
                       confidence = 0.85
                  from matched
                 where event.source = 'solana_rpc'
                   and event.event_type = 'reward'
                   and event.asset = matched.asset
                   and extract(year from event.event_time)::integer = matched.tax_year
                returning event.event_id
                """
            ).fetchall()
        return len(carried)

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
