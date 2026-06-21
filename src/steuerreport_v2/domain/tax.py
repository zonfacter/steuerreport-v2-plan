from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pandas as pd

from steuerreport_v2.contracts.events import CanonicalEvent
from steuerreport_v2.contracts.tax import (
    TaxLine,
    TaxHoldingPeriodBucket,
    TaxHoldingPeriodLot,
    TaxHoldingPeriodReport,
    TaxLot,
    TaxRunResult,
    TaxRunSummary,
    TaxUnmatchedDisposal,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup

LOT_ACQUISITION_EVENT_TYPES = {"trade", "income", "reward", "staking", "mining"}
FIAT_TAX_EXCLUDED_ASSETS = {"EUR"}


class TaxService:
    def __init__(self, store: DuckDbStore) -> None:
        self.store = store
        self.price_lookup = HistoricalPriceLookup(store)

    def rebuild_fifo(self) -> TaxRunResult:
        lots_by_asset: defaultdict[str, deque[TaxLot]] = defaultdict(deque)
        all_lots: list[TaxLot] = []
        tax_lines: list[TaxLine] = []
        unmatched: list[TaxUnmatchedDisposal] = []

        for event in self.store.list_canonical_events():
            if event.asset in FIAT_TAX_EXCLUDED_ASSETS:
                continue
            if not self._is_tax_relevant_event(event):
                continue
            event_value_eur = self._eur_value(event)
            if event.event_type == "trade" and event.quantity > 0:
                lot = self._lot_from_buy(event)
                lots_by_asset[event.asset].append(lot)
                all_lots.append(lot)
                if (
                    self._is_taxable_quote_disposal(event)
                    and str(event.quote_asset) in lots_by_asset
                ):
                    created, missing = self._consume_fifo_asset(
                        asset=str(event.quote_asset),
                        quantity=abs(event.quote_quantity or Decimal("0")),
                        disposed_at=event.event_time,
                        proceeds_total=event_value_eur,
                        event=event,
                        lots=lots_by_asset[str(event.quote_asset)],
                    )
                    tax_lines.extend(created)
                    unmatched.extend(missing)
                continue
            if event.event_type == "trade" and event.quantity < 0:
                created, missing = self._consume_fifo(event, lots_by_asset[event.asset])
                tax_lines.extend(created)
                unmatched.extend(missing)
                if self._is_taxable_quote_acquisition(event):
                    lot = self._lot_from_values(
                        asset=str(event.quote_asset),
                        acquired_at=event.event_time,
                        quantity=abs(event.quote_quantity or Decimal("0")),
                        cost_basis_eur_total=event_value_eur,
                        source_event_id=event.event_id,
                    )
                    lots_by_asset[lot.asset].append(lot)
                    all_lots.append(lot)
                continue
            if event.quantity > 0:
                lot = self._lot_from_buy(event)
                lots_by_asset[event.asset].append(lot)
                all_lots.append(lot)

        self._replace_tax_tables(all_lots, tax_lines, unmatched)
        return TaxRunResult(
            lots=all_lots,
            tax_lines=tax_lines,
            unmatched_disposals=len(unmatched),
            unmatched=unmatched,
        )

    def latest_summary(self) -> TaxRunSummary | None:
        with self.store.connect() as con:
            row = con.execute(
                """
                select run_id, tax_lines_count, unmatched_disposals, created_at
                from tax_run_summaries
                order by created_at desc
                limit 1
                """
            ).fetchone()
        if row is None:
            return None
        return TaxRunSummary(
            run_id=row[0],
            tax_lines_count=row[1],
            unmatched_disposals=row[2],
            created_at=row[3],
        )

    def list_tax_lines(self) -> list[TaxLine]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    l.tax_line_id, l.asset, lot.acquired_at, l.disposed_at, l.quantity,
                    acquisition_cost_eur, disposal_proceeds_eur, gain_loss_eur,
                    holding_days, l.source_event_id, l.lot_id
                from tax_lines l
                join tax_lots lot on lot.lot_id = l.lot_id
                order by l.disposed_at, l.tax_line_id
                """
            ).fetchall()
        return [
            TaxLine(
                tax_line_id=row[0],
                asset=row[1],
                acquired_at=row[2],
                disposed_at=row[3],
                quantity=row[4],
                acquisition_cost_eur=row[5],
                disposal_proceeds_eur=row[6],
                gain_loss_eur=row[7],
                holding_days=row[8],
                source_event_id=row[9],
                lot_id=row[10],
            )
            for row in rows
        ]

    def list_tax_lots(self) -> list[TaxLot]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    lot_id, asset, acquired_at, quantity_total,
                    quantity_remaining, cost_basis_eur_total, source_event_id
                from tax_lots
                order by acquired_at, lot_id
                """
            ).fetchall()
        return [
            TaxLot(
                lot_id=row[0],
                asset=row[1],
                acquired_at=row[2],
                quantity_total=row[3],
                quantity_remaining=row[4],
                cost_basis_eur_total=row[5],
                source_event_id=row[6],
            )
            for row in rows
        ]

    def list_unmatched_disposals(self) -> list[TaxUnmatchedDisposal]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    unmatched_id, source_event_id, source, source_ref,
                    raw_object_id, event_time, event_type, account, asset,
                    quantity, matched_quantity, missing_quantity,
                    available_before, proceeds_total_eur
                from tax_unmatched_disposals
                order by event_time, unmatched_id
                """
            ).fetchall()
        return [
            TaxUnmatchedDisposal(
                unmatched_id=row[0],
                source_event_id=row[1],
                source=row[2],
                source_ref=row[3],
                raw_object_id=row[4],
                event_time=row[5],
                event_type=row[6],
                account=row[7],
                asset=row[8],
                quantity=row[9],
                matched_quantity=row[10],
                missing_quantity=row[11],
                available_before=row[12],
                proceeds_total_eur=row[13],
            )
            for row in rows
        ]

    def holding_period_report(
        self,
        *,
        min_value_eur: Decimal = Decimal("1"),
        as_of: datetime | None = None,
    ) -> TaxHoldingPeriodReport:
        as_of = self._normalize_datetime(as_of or datetime.now(timezone.utc))
        latest_prices = {
            point.asset.upper(): point
            for point in self.store.list_latest_price_points()
            if point.price_eur > 0
        }
        event_context = self._lot_event_context()
        current_quantities = self._current_portfolio_quantities()
        use_current_quantity_cap = bool(current_quantities)
        lots: list[TaxHoldingPeriodLot] = []
        hidden_dust = 0
        missing_price_assets: set[str] = set()

        for lot in self.list_tax_lots():
            if lot.quantity_remaining <= 0:
                continue
            asset_key = lot.asset.upper()
            sellable_quantity = lot.quantity_remaining
            if use_current_quantity_cap:
                available_current = current_quantities.get(asset_key, Decimal("0"))
                if available_current <= 0:
                    continue
                sellable_quantity = min(lot.quantity_remaining, available_current)
                current_quantities[asset_key] = available_current - sellable_quantity
            price = latest_prices.get(lot.asset.upper())
            if price is None:
                missing_price_assets.add(lot.asset.upper())
                continue
            current_value = sellable_quantity * price.price_eur
            if current_value < min_value_eur:
                hidden_dust += 1
                continue
            cost_basis_remaining = self._remaining_cost_basis(lot, sellable_quantity)
            tax_free_at = self._tax_free_at(lot.acquired_at)
            days_until = max((tax_free_at.date() - as_of.date()).days, 0)
            context = event_context.get(lot.source_event_id, {})
            lots.append(
                TaxHoldingPeriodLot(
                    lot_id=lot.lot_id,
                    asset=lot.asset,
                    acquired_at=lot.acquired_at,
                    tax_free_at=datetime.combine(tax_free_at.date(), time.min, tzinfo=timezone.utc),
                    days_until_tax_free=days_until,
                    bucket=self._holding_bucket(days_until),
                    quantity_remaining=sellable_quantity,
                    cost_basis_eur_remaining=cost_basis_remaining,
                    current_price_eur=price.price_eur,
                    current_value_eur=current_value,
                    unrealized_gain_loss_eur=current_value - cost_basis_remaining,
                    price_source=price.source,
                    priced_at=price.priced_at,
                    source_event_id=lot.source_event_id,
                    source=context.get("source"),
                    account=context.get("account"),
                )
            )

        lots.sort(key=lambda item: (item.days_until_tax_free, item.tax_free_at, item.asset, item.lot_id))
        buckets = self._holding_buckets(lots)
        value_by_bucket = {bucket.bucket: bucket.value_eur for bucket in buckets}
        return TaxHoldingPeriodReport(
            generated_at=datetime.now(timezone.utc),
            as_of=as_of,
            min_value_eur=min_value_eur,
            visible_lots_count=len(lots),
            hidden_dust_lots_count=hidden_dust,
            missing_price_assets=sorted(missing_price_assets),
            tax_free_now_value_eur=value_by_bucket.get("tax_free_now", Decimal("0")),
            next_7_days_value_eur=value_by_bucket.get("next_7_days", Decimal("0")),
            next_30_days_value_eur=value_by_bucket.get("next_30_days", Decimal("0")),
            next_7_months_value_eur=value_by_bucket.get("next_7_months", Decimal("0")),
            next_year_value_eur=value_by_bucket.get("next_year", Decimal("0")),
            buckets=buckets,
            lots=lots,
            methodology=(
                "Read-only Haltefristansicht aus offenen FIFO-Lots und aktuellen "
                "sichtbaren Portfolio-Mengen. Steuerfrei-Datum konservativ: Tag "
                "nach dem einjaehrigen Anschaffungsjubilauem. Lots unter "
                "min_value_eur werden als Dust ausgeblendet."
            ),
        )

    def _lot_from_buy(self, event: CanonicalEvent) -> TaxLot:
        cost_basis = self._eur_value(event)
        return self._lot_from_values(
            asset=event.asset,
            acquired_at=event.event_time,
            quantity=event.quantity,
            cost_basis_eur_total=cost_basis,
            source_event_id=event.event_id,
        )

    def _lot_from_values(
        self,
        asset: str,
        acquired_at: datetime,
        quantity: Decimal,
        cost_basis_eur_total: Decimal,
        source_event_id: str,
    ) -> TaxLot:
        return TaxLot(
            lot_id=str(uuid4()),
            asset=asset,
            acquired_at=acquired_at,
            quantity_total=quantity,
            quantity_remaining=quantity,
            cost_basis_eur_total=cost_basis_eur_total,
            source_event_id=source_event_id,
        )

    def _lot_event_context(self) -> dict[str, dict[str, str | None]]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select event_id, source, account
                from canonical_events
                """
            ).fetchall()
        return {
            row[0]: {"source": row[1], "account": row[2]}
            for row in rows
        }

    @staticmethod
    def _normalize_datetime(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _remaining_cost_basis(lot: TaxLot, quantity: Decimal | None = None) -> Decimal:
        if lot.quantity_total == 0:
            return Decimal("0")
        basis_quantity = quantity if quantity is not None else lot.quantity_remaining
        return lot.cost_basis_eur_total * (basis_quantity / lot.quantity_total)

    def _current_portfolio_quantities(self) -> dict[str, Decimal]:
        from steuerreport_v2.domain.portfolio import PortfolioService

        try:
            snapshot = PortfolioService(self.store).snapshot()
        except Exception:
            return {}
        quantities: dict[str, Decimal] = defaultdict(Decimal)
        for position in snapshot.positions:
            if position.quantity > 0:
                quantities[position.asset.upper()] += position.quantity
        return dict(quantities)

    @staticmethod
    def _tax_free_at(acquired_at: datetime) -> datetime:
        normalized = acquired_at if acquired_at.tzinfo is not None else acquired_at.replace(tzinfo=timezone.utc)
        normalized = normalized.astimezone(timezone.utc)
        acquired_date = normalized.date()
        try:
            anniversary = acquired_date.replace(year=acquired_date.year + 1)
        except ValueError:
            anniversary = acquired_date.replace(year=acquired_date.year + 1, day=28)
        return datetime.combine(anniversary + timedelta(days=1), time.min, tzinfo=timezone.utc)

    @staticmethod
    def _holding_bucket(days_until: int) -> str:
        if days_until <= 0:
            return "tax_free_now"
        if days_until <= 7:
            return "next_7_days"
        if days_until <= 30:
            return "next_30_days"
        if days_until <= 213:
            return "next_7_months"
        if days_until <= 365:
            return "next_year"
        return "later"

    @staticmethod
    def _holding_bucket_label(bucket: str) -> str:
        labels = {
            "tax_free_now": "Jetzt steuerfrei",
            "next_7_days": "Naechste 7 Tage",
            "next_30_days": "Naechste 30 Tage",
            "next_7_months": "Naechste 7 Monate",
            "next_year": "Naechstes Jahr",
            "later": "Spaeter",
        }
        return labels.get(bucket, bucket)

    def _holding_buckets(self, lots: list[TaxHoldingPeriodLot]) -> list[TaxHoldingPeriodBucket]:
        result = []
        for bucket in ["tax_free_now", "next_7_days", "next_30_days", "next_7_months", "next_year", "later"]:
            bucket_lots = [lot for lot in lots if lot.bucket == bucket]
            if not bucket_lots:
                continue
            result.append(
                TaxHoldingPeriodBucket(
                    bucket=bucket,
                    label=self._holding_bucket_label(bucket),
                    lots_count=len(bucket_lots),
                    value_eur=sum((lot.current_value_eur for lot in bucket_lots), Decimal("0")),
                    assets=sorted({lot.asset for lot in bucket_lots}),
                )
            )
        return result

    def _is_tax_relevant_event(self, event: CanonicalEvent) -> bool:
        if event.event_type in LOT_ACQUISITION_EVENT_TYPES:
            return True
        return (
            event.quantity > 0
            and event.quote_asset is not None
            and event.quote_quantity is not None
        )

    def _consume_fifo(
        self,
        event: CanonicalEvent,
        lots: deque[TaxLot],
    ) -> tuple[list[TaxLine], list[TaxUnmatchedDisposal]]:
        return self._consume_fifo_asset(
            asset=event.asset,
            quantity=abs(event.quantity),
            disposed_at=event.event_time,
            proceeds_total=self._eur_value(event),
            event=event,
            lots=lots,
        )

    def _consume_fifo_asset(
        self,
        asset: str,
        quantity: Decimal,
        disposed_at: datetime,
        proceeds_total: Decimal,
        event: CanonicalEvent,
        lots: deque[TaxLot],
    ) -> tuple[list[TaxLine], list[TaxUnmatchedDisposal]]:
        quantity_to_sell = quantity
        available_before = self._available_quantity(lots)
        created: list[TaxLine] = []
        unmatched: list[TaxUnmatchedDisposal] = []

        while quantity_to_sell > 0:
            if not lots:
                if self._is_ignored_dust_disposal(asset, quantity_to_sell, proceeds_total):
                    break
                matched_quantity = quantity - quantity_to_sell
                unmatched.append(
                    TaxUnmatchedDisposal(
                        unmatched_id=str(uuid4()),
                        source_event_id=event.event_id,
                        source=event.source,
                        source_ref=event.source_ref,
                        raw_object_id=event.raw_object_id,
                        event_time=disposed_at,
                        event_type=event.event_type,
                        account=event.account,
                        asset=asset,
                        quantity=quantity,
                        matched_quantity=matched_quantity,
                        missing_quantity=quantity_to_sell,
                        available_before=available_before,
                        proceeds_total_eur=proceeds_total,
                    )
                )
                break

            lot = lots[0]
            used_quantity = min(quantity_to_sell, lot.quantity_remaining)
            lot_ratio = used_quantity / lot.quantity_total
            acquisition_cost = lot.cost_basis_eur_total * lot_ratio
            proceeds = proceeds_total * (used_quantity / quantity)
            holding_days = (disposed_at.date() - lot.acquired_at.date()).days
            remaining = lot.quantity_remaining - used_quantity
            lot.quantity_remaining = remaining

            created.append(
                TaxLine(
                    tax_line_id=str(uuid4()),
                    asset=asset,
                    acquired_at=lot.acquired_at,
                    disposed_at=disposed_at,
                    quantity=used_quantity,
                    acquisition_cost_eur=acquisition_cost,
                    disposal_proceeds_eur=proceeds,
                    gain_loss_eur=proceeds - acquisition_cost,
                    holding_days=holding_days,
                    source_event_id=event.event_id,
                    lot_id=lot.lot_id,
                )
            )

            quantity_to_sell -= used_quantity
            if lot.quantity_remaining == 0:
                lots.popleft()

        return created, unmatched

    def _is_ignored_dust_disposal(
        self,
        asset: str,
        missing_quantity: Decimal,
        proceeds_total: Decimal,
    ) -> bool:
        return (
            asset.upper() == "SOL"
            and missing_quantity <= Decimal("0.00001")
            and abs(proceeds_total) <= Decimal("0.01")
        )

    def _is_taxable_quote_disposal(self, event: CanonicalEvent) -> bool:
        if event.quote_asset is None or event.quote_quantity is None:
            return False
        return (
            event.quote_asset not in FIAT_TAX_EXCLUDED_ASSETS
            and event.quote_quantity != 0
        )

    def _is_taxable_quote_acquisition(self, event: CanonicalEvent) -> bool:
        if event.quote_asset is None or event.quote_quantity is None:
            return False
        return (
            event.quote_asset not in FIAT_TAX_EXCLUDED_ASSETS
            and event.quote_quantity != 0
        )

    def _available_quantity(self, lots: deque[TaxLot]) -> Decimal:
        return sum((lot.quantity_remaining for lot in lots), Decimal("0"))

    def _eur_value(self, event: CanonicalEvent) -> Decimal:
        if event.quote_quantity is not None and event.quote_asset is not None:
            if event.quote_asset == "EUR":
                return abs(event.quote_quantity)
            quote_price = self.price_lookup.at_or_before(
                event.quote_asset,
                event.event_time,
            )
            if quote_price is None:
                return Decimal("0")
            return abs(event.quote_quantity) * quote_price.price_eur
        price = self.price_lookup.at_or_before(event.asset, event.event_time)
        if price is None:
            return Decimal("0")
        return abs(event.quantity) * price.price_eur

    def _replace_tax_tables(
        self,
        lots: list[TaxLot],
        tax_lines: list[TaxLine],
        unmatched_disposals: list[TaxUnmatchedDisposal],
    ) -> None:
        created_at = datetime.now(timezone.utc)
        with self.store.connect() as con:
            con.execute("delete from tax_lots")
            con.execute("delete from tax_lines")
            con.execute("delete from tax_run_summaries")
            con.execute("delete from tax_unmatched_disposals")
            if lots:
                lot_frame = pd.DataFrame(
                    [
                        (
                            lot.lot_id,
                            lot.asset,
                            lot.acquired_at,
                            str(lot.quantity_total),
                            str(lot.quantity_remaining),
                            str(lot.cost_basis_eur_total),
                            lot.source_event_id,
                            created_at,
                        )
                        for lot in lots
                    ],
                    columns=[
                        "lot_id",
                        "asset",
                        "acquired_at",
                        "quantity_total",
                        "quantity_remaining",
                        "cost_basis_eur_total",
                        "source_event_id",
                        "created_at",
                    ],
                )
                con.register("tax_lots_to_insert", lot_frame)
                con.execute(
                    """
                    insert into tax_lots (
                        lot_id, asset, acquired_at, quantity_total,
                        quantity_remaining, cost_basis_eur_total,
                        source_event_id, created_at
                    )
                    select
                        lot_id, asset, acquired_at,
                        cast(quantity_total as decimal(38, 18)),
                        cast(quantity_remaining as decimal(38, 18)),
                        cast(cost_basis_eur_total as decimal(38, 18)),
                        source_event_id, created_at
                    from tax_lots_to_insert
                    """
                )
                con.unregister("tax_lots_to_insert")
            con.execute(
                """
                insert into tax_run_summaries (
                    run_id, tax_lines_count, unmatched_disposals, created_at
                )
                values (?, ?, ?, ?)
                """,
                [str(uuid4()), len(tax_lines), len(unmatched_disposals), created_at],
            )
            if tax_lines:
                line_frame = pd.DataFrame(
                    [
                        (
                            line.tax_line_id,
                            line.asset,
                            line.disposed_at,
                            str(line.quantity),
                            str(line.acquisition_cost_eur),
                            str(line.disposal_proceeds_eur),
                            str(line.gain_loss_eur),
                            line.holding_days,
                            line.source_event_id,
                            line.lot_id,
                            created_at,
                        )
                        for line in tax_lines
                    ],
                    columns=[
                        "tax_line_id",
                        "asset",
                        "disposed_at",
                        "quantity",
                        "acquisition_cost_eur",
                        "disposal_proceeds_eur",
                        "gain_loss_eur",
                        "holding_days",
                        "source_event_id",
                        "lot_id",
                        "created_at",
                    ],
                )
                con.register("tax_lines_to_insert", line_frame)
                con.execute(
                    """
                    insert into tax_lines (
                        tax_line_id, asset, disposed_at, quantity,
                        acquisition_cost_eur, disposal_proceeds_eur,
                        gain_loss_eur, holding_days, source_event_id,
                        lot_id, created_at
                    )
                    select
                        tax_line_id, asset, disposed_at,
                        cast(quantity as decimal(38, 18)),
                        cast(acquisition_cost_eur as decimal(38, 18)),
                        cast(disposal_proceeds_eur as decimal(38, 18)),
                        cast(gain_loss_eur as decimal(38, 18)),
                        holding_days, source_event_id, lot_id, created_at
                    from tax_lines_to_insert
                    """
                )
                con.unregister("tax_lines_to_insert")
            if unmatched_disposals:
                unmatched_frame = pd.DataFrame(
                    [
                        (
                            item.unmatched_id,
                            item.source_event_id,
                            item.source,
                            item.source_ref,
                            item.raw_object_id,
                            item.event_time,
                            item.event_type,
                            item.account,
                            item.asset,
                            str(item.quantity),
                            str(item.matched_quantity),
                            str(item.missing_quantity),
                            str(item.available_before),
                            str(item.proceeds_total_eur),
                            created_at,
                        )
                        for item in unmatched_disposals
                    ],
                    columns=[
                        "unmatched_id",
                        "source_event_id",
                        "source",
                        "source_ref",
                        "raw_object_id",
                        "event_time",
                        "event_type",
                        "account",
                        "asset",
                        "quantity",
                        "matched_quantity",
                        "missing_quantity",
                        "available_before",
                        "proceeds_total_eur",
                        "created_at",
                    ],
                )
                con.register("tax_unmatched_to_insert", unmatched_frame)
                con.execute(
                    """
                    insert into tax_unmatched_disposals (
                        unmatched_id, source_event_id, source, source_ref,
                        raw_object_id, event_time, event_type, account, asset,
                        quantity, matched_quantity, missing_quantity,
                        available_before, proceeds_total_eur, created_at
                    )
                    select
                        unmatched_id, source_event_id, source, source_ref,
                        raw_object_id, event_time, event_type, account, asset,
                        cast(quantity as decimal(38, 18)),
                        cast(matched_quantity as decimal(38, 18)),
                        cast(missing_quantity as decimal(38, 18)),
                        cast(available_before as decimal(38, 18)),
                        cast(proceeds_total_eur as decimal(38, 18)),
                        created_at
                    from tax_unmatched_to_insert
                    """
                )
                con.unregister("tax_unmatched_to_insert")
