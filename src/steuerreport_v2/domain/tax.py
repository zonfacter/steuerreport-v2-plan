from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pandas as pd

from steuerreport_v2.contracts.events import CanonicalEvent
from steuerreport_v2.contracts.service_swap_tax_mapping import (
    ServiceSwapTaxMappingRecord,
)
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
from steuerreport_v2.domain.binance_earn_fifo import (
    locked_redemption_clawback_reward_event_ids,
)
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup
from steuerreport_v2.domain.fifo_methods import (
    GLOBAL_ASSET_FIFO_SCOPE,
    WALLET_DEPOT_FIFO_SCOPE,
    active_fifo_scope,
)
from steuerreport_v2.domain.moonpay_receipts import MoonpayReceiptService
from steuerreport_v2.domain.tax_time import private_disposal_tax_free_at, reporting_time
from steuerreport_v2.domain.service_swap_tax_mapping import (
    ServiceSwapTaxMappingService,
)

LOT_ACQUISITION_EVENT_TYPES = {"trade", "income", "reward", "staking", "mining"}
FIAT_TAX_EXCLUDED_ASSETS = {"EUR"}
STABLE_VALUE_ANCHOR_ASSETS = {
    "EUR",
    "USD",
    "USDT",
    "USDC",
    "BUSD",
    "FDUSD",
    "TUSD",
    "DAI",
    "EURC",
    "EURS",
}


@dataclass(frozen=True)
class _ServiceSwapOperation:
    event_time: datetime
    sequence: int
    kind: str
    mapping: ServiceSwapTaxMappingRecord
    event: CanonicalEvent
    quantity: Decimal = Decimal("0")


class TaxService:
    def __init__(
        self,
        store: DuckDbStore,
        *,
        service_swap_tax_mapping_config_path: Path | None = None,
        service_swap_evidence_dir: Path | None = None,
    ) -> None:
        self.store = store
        self.price_lookup = HistoricalPriceLookup(store)
        self.service_swap_tax_mapping = ServiceSwapTaxMappingService(
            store,
            config_path=service_swap_tax_mapping_config_path,
            evidence_dir=service_swap_evidence_dir,
        )

    def rebuild_fifo(self) -> TaxRunResult:
        if active_fifo_scope(self.store) == WALLET_DEPOT_FIFO_SCOPE:
            return self._rebuild_wallet_fifo()
        return self._rebuild_global_fifo()

    def crypto_to_crypto_valuation_events(self) -> list[CanonicalEvent]:
        """Return economic positive swap events after service-route normalization."""
        events = self.store.list_canonical_events()
        return [
            operation
            for operation in self._rebuild_operations(events)
            if isinstance(operation, CanonicalEvent)
            and operation.event_type == "trade"
            and operation.quantity > 0
            and operation.quote_asset is not None
            and operation.quote_asset.upper() not in FIAT_TAX_EXCLUDED_ASSETS
            and operation.quote_quantity is not None
            and operation.quote_quantity != 0
        ]

    def _rebuild_global_fifo(self) -> TaxRunResult:
        result = self.preview_global_fifo()
        self._replace_tax_tables(result.lots, result.tax_lines, result.unmatched)
        return result

    def preview_global_fifo(
        self,
        *,
        received_asset_first: bool = False,
    ) -> TaxRunResult:
        """Calculate global FIFO in memory without replacing productive tax tables."""
        lots_by_asset: defaultdict[str, deque[TaxLot]] = defaultdict(deque)
        all_lots: list[TaxLot] = []
        tax_lines: list[TaxLine] = []
        unmatched: list[TaxUnmatchedDisposal] = []
        moonpay_cost_basis_by_event = (
            MoonpayReceiptService(self.store).ready_cost_basis_by_event()
        )

        events = self.store.list_canonical_events()
        clawback_reward_event_ids = locked_redemption_clawback_reward_event_ids(
            self.store, events
        )
        for operation in self._rebuild_operations(events):
            if isinstance(operation, _ServiceSwapOperation):
                created_lots, created_lines, missing = (
                    self._process_service_swap_operation(
                        operation=operation,
                        lots_by_asset=lots_by_asset,
                    )
                )
                all_lots.extend(created_lots)
                tax_lines.extend(created_lines)
                unmatched.extend(missing)
                continue
            event = operation
            if event.asset in FIAT_TAX_EXCLUDED_ASSETS:
                continue
            moonpay_evidence = moonpay_cost_basis_by_event.get(event.event_id)
            if moonpay_evidence is not None:
                lot = self._lot_from_values(
                    asset=event.asset,
                    acquired_at=event.event_time,
                    quantity=event.quantity,
                    cost_basis_eur_total=moonpay_evidence.cost_basis_eur
                    or Decimal("0"),
                    source_event_id=event.event_id,
                )
                lots_by_asset[event.asset].append(lot)
                all_lots.append(lot)
                continue
            if self._is_binance_locked_redemption_loss(event):
                missing = self._consume_fifo_without_tax_line(
                    event=event,
                    lots=lots_by_asset[event.asset],
                    reward_event_ids=clawback_reward_event_ids.get(
                        event.event_id, frozenset()
                    ),
                )
                unmatched.extend(missing)
                continue
            if not self._is_tax_relevant_event(event):
                continue
            event_value_eur = self._eur_value(event)
            if event.event_type == "trade" and event.quantity > 0:
                event_value_eur = self._eur_value(
                    event,
                    prefer_received_asset=self._use_received_asset_value_for_quote_disposal(
                        event,
                        received_asset_first=received_asset_first,
                    ),
                )
                lot = self._lot_from_buy(event, value_eur=event_value_eur)
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
                    quote_asset = str(event.quote_asset)
                    lot = self._lot_from_values(
                        asset=quote_asset,
                        acquired_at=event.event_time,
                        quantity=self._net_acquired_quantity(
                            event=event,
                            acquired_asset=quote_asset,
                            gross_quantity=abs(event.quote_quantity or Decimal("0")),
                        ),
                        cost_basis_eur_total=self._disposal_value_eur(event),
                        source_event_id=event.event_id,
                    )
                    lots_by_asset[lot.asset].append(lot)
                    all_lots.append(lot)
                continue
            if event.quantity > 0:
                lot = self._lot_from_buy(event)
                lots_by_asset[event.asset].append(lot)
                all_lots.append(lot)

        return TaxRunResult(
            lots=all_lots,
            tax_lines=tax_lines,
            unmatched_disposals=len(unmatched),
            unmatched=unmatched,
        )

    def _rebuild_wallet_fifo(self) -> TaxRunResult:
        from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService
        from steuerreport_v2.domain.wallet_fifo_persistence import wallet_fifo_tax_rows
        from steuerreport_v2.domain.wallet_fifo_runs import WalletFifoParallelRunService

        as_of = datetime.now(timezone.utc)
        fingerprint = WalletFifoParallelRunService(self.store).input_fingerprint(as_of)
        state = WalletFifoPreviewService(self.store).replay(as_of=as_of)
        if state.unmatched:
            raise ValueError(
                "Wallet-/Depot-FIFO-Rebuild abgebrochen: "
                f"{len(state.unmatched)} unmatched Abgaenge muessen zuerst geprueft werden."
            )
        lots, tax_lines = wallet_fifo_tax_rows(state)
        self._replace_tax_tables(
            lots,
            tax_lines,
            [],
            fifo_method=WALLET_DEPOT_FIFO_SCOPE,
            input_fingerprint_digest=fingerprint.digest,
        )
        return TaxRunResult(
            lots=lots,
            tax_lines=tax_lines,
            unmatched_disposals=0,
            unmatched=[],
        )

    def _rebuild_operations(
        self,
        events: list[CanonicalEvent],
    ) -> list[CanonicalEvent | _ServiceSwapOperation]:
        mappings = self.service_swap_tax_mapping.ready_mappings(events=events)
        events_by_id = {event.event_id: event for event in events}
        mapped_event_ids = {
            event_id
            for mapping in mappings
            for event_id in (
                mapping.source_event_id,
                mapping.funding_event_id,
                mapping.deposit_event_id,
                *mapping.deposit_mirror_event_ids,
            )
        }
        operations: list[
            tuple[datetime, int, int, CanonicalEvent | _ServiceSwapOperation]
        ] = [
            (self._normalize_datetime(event.event_time), 0, index, event)
            for index, event in enumerate(events)
            if event.event_id not in mapped_event_ids
        ]
        next_sequence = len(events)
        for mapping in mappings:
            source_event = events_by_id[mapping.source_event_id]
            funding_event = events_by_id[mapping.funding_event_id]
            for offset, operation in enumerate(
                (
                    _ServiceSwapOperation(
                        event_time=self._database_datetime(
                            mapping.source_event_time
                        ),
                        sequence=next_sequence,
                        kind="direct_cost",
                        mapping=mapping,
                        event=source_event,
                        quantity=mapping.source_direct_cost_quantity,
                    ),
                    _ServiceSwapOperation(
                        event_time=self._database_datetime(
                            mapping.funding_event_time
                        ),
                        sequence=next_sequence + 1,
                        kind="direct_cost",
                        mapping=mapping,
                        event=funding_event,
                        quantity=mapping.funding_direct_cost_quantity,
                    ),
                    _ServiceSwapOperation(
                        event_time=self._database_datetime(mapping.swap_event_time),
                        sequence=next_sequence + 2,
                        kind="swap",
                        mapping=mapping,
                        event=source_event,
                    ),
                )
            ):
                operations.append(
                    (
                        self._normalize_datetime(operation.event_time),
                        1,
                        next_sequence + offset,
                        operation,
                    )
                )
            next_sequence += 3
        operations.sort(key=lambda item: (item[0], item[1], item[2]))
        return [operation for _time, _priority, _sequence, operation in operations]

    def _process_service_swap_operation(
        self,
        *,
        operation: _ServiceSwapOperation,
        lots_by_asset: defaultdict[str, deque[TaxLot]],
    ) -> tuple[list[TaxLot], list[TaxLine], list[TaxUnmatchedDisposal]]:
        mapping = operation.mapping
        if operation.kind == "direct_cost":
            if operation.quantity <= 0:
                return [], [], []
            cost_value = self._required_asset_value_eur(
                mapping.direct_cost_asset,
                operation.quantity,
                operation.event_time,
                mapping_id=mapping.mapping_id,
            )
            fee_event = operation.event.model_copy(
                update={
                    "event_time": operation.event_time,
                    "event_type": "trade",
                    "asset": mapping.direct_cost_asset,
                    "quantity": -operation.quantity,
                    "quote_asset": "EUR",
                    "quote_quantity": cost_value,
                    "fee_asset": None,
                    "fee_quantity": None,
                }
            )
            lines, missing = self._consume_fifo_asset(
                asset=mapping.direct_cost_asset,
                quantity=operation.quantity,
                disposed_at=operation.event_time,
                proceeds_total=cost_value,
                event=fee_event,
                lots=lots_by_asset[mapping.direct_cost_asset],
            )
            return [], lines, missing
        if operation.kind != "swap":
            raise ValueError(f"unsupported_service_swap_operation:{operation.kind}")
        output_value = self._required_asset_value_eur(
            mapping.acquired_asset,
            mapping.acquired_quantity,
            operation.event_time,
            mapping_id=mapping.mapping_id,
        )
        direct_cost_value = sum(
            (
                self._required_asset_value_eur(
                    mapping.direct_cost_asset,
                    quantity,
                    event_time,
                    mapping_id=mapping.mapping_id,
                )
                for quantity, event_time in (
                    (
                        mapping.source_direct_cost_quantity,
                        mapping.source_event_time,
                    ),
                    (
                        mapping.funding_direct_cost_quantity,
                        mapping.funding_event_time,
                    ),
                )
            ),
            Decimal("0"),
        )
        swap_event = operation.event.model_copy(
            update={
                "event_time": operation.event_time,
                "event_type": "trade",
                "asset": mapping.source_asset,
                "quantity": -mapping.source_quantity,
                "quote_asset": mapping.acquired_asset,
                "quote_quantity": mapping.acquired_quantity,
                "fee_asset": None,
                "fee_quantity": None,
                "tx_id": mapping.swap_tx_id,
            }
        )
        lines, missing = self._consume_fifo_asset(
            asset=mapping.source_asset,
            quantity=mapping.source_quantity,
            disposed_at=operation.event_time,
            proceeds_total=max(output_value - direct_cost_value, Decimal("0")),
            event=swap_event,
            lots=lots_by_asset[mapping.source_asset],
        )
        lot = self._lot_from_values(
            asset=mapping.acquired_asset,
            acquired_at=operation.event_time,
            quantity=mapping.acquired_quantity,
            cost_basis_eur_total=output_value,
            source_event_id=mapping.deposit_event_id,
        )
        lots_by_asset[mapping.acquired_asset].append(lot)
        return [lot], lines, missing

    def _required_asset_value_eur(
        self,
        asset: str,
        quantity: Decimal,
        at: datetime,
        *,
        mapping_id: str,
    ) -> Decimal:
        value = self._asset_value_eur(asset, quantity, at)
        if value is None:
            raise RuntimeError(
                f"service_swap_tax_mapping_price_missing:{mapping_id}:{asset}:{at.isoformat()}"
            )
        return value

    def latest_summary(self) -> TaxRunSummary | None:
        with self.store.connect() as con:
            row = con.execute(
                """
                select run_id, tax_lines_count, unmatched_disposals, created_at,
                       coalesce(fifo_method, ?), input_fingerprint_digest
                from tax_run_summaries
                order by created_at desc
                limit 1
                """,
                [GLOBAL_ASSET_FIFO_SCOPE],
            ).fetchone()
        if row is None:
            return None
        return TaxRunSummary(
            run_id=row[0],
            tax_lines_count=row[1],
            unmatched_disposals=row[2],
            created_at=row[3],
            fifo_method=row[4],
            input_fingerprint_digest=row[5],
        )

    def list_tax_lines(self) -> list[TaxLine]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    l.tax_line_id, l.asset, coalesce(l.acquired_at, lot.acquired_at),
                    l.disposed_at, l.quantity,
                    acquisition_cost_eur, disposal_proceeds_eur, gain_loss_eur,
                    holding_days, l.source_event_id, l.lot_id, l.pool_id,
                    l.acquisition_source_event_id, l.origin_lot_id,
                    coalesce(l.fifo_method, ?)
                from tax_lines l
                join tax_lots lot on lot.lot_id = l.lot_id
                order by l.disposed_at, l.tax_line_id
                """,
                [GLOBAL_ASSET_FIFO_SCOPE],
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
                pool_id=row[11],
                acquisition_source_event_id=row[12],
                origin_lot_id=row[13],
                fifo_method=row[14],
            )
            for row in rows
        ]

    def list_tax_lots(self) -> list[TaxLot]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    lot_id, asset, acquired_at, quantity_total,
                    quantity_remaining, cost_basis_eur_total, source_event_id,
                    pool_id, origin_lot_id, coalesce(fifo_method, ?)
                from tax_lots
                order by acquired_at, lot_id
                """,
                [GLOBAL_ASSET_FIFO_SCOPE],
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
                pool_id=row[7],
                origin_lot_id=row[8],
                fifo_method=row[9],
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
            days_until = max(
                (reporting_time(tax_free_at).date() - reporting_time(as_of).date()).days,
                0,
            )
            context = event_context.get(lot.source_event_id, {})
            lots.append(
                TaxHoldingPeriodLot(
                    lot_id=lot.lot_id,
                    asset=lot.asset,
                    acquired_at=lot.acquired_at,
                    tax_free_at=tax_free_at,
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
                "sichtbaren Portfolio-Mengen. Modellierte private Jahresfrist in "
                "Europe/Berlin: Jahrestag noch innerhalb, Folgetag ausserhalb; "
                "keine Entscheidung ueber Privat-/Betriebsvermoegen. Lots unter "
                "min_value_eur werden als Dust ausgeblendet."
            ),
        )

    def _lot_from_buy(self, event: CanonicalEvent, *, value_eur: Decimal | None = None) -> TaxLot:
        cost_basis = value_eur if value_eur is not None else self._eur_value(event)
        return self._lot_from_values(
            asset=event.asset,
            acquired_at=event.event_time,
            quantity=self._net_acquired_quantity(
                event=event,
                acquired_asset=event.asset,
                gross_quantity=event.quantity,
            ),
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

    @classmethod
    def _database_datetime(cls, value: datetime) -> datetime:
        return cls._normalize_datetime(value).replace(tzinfo=None)

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
        return private_disposal_tax_free_at(acquired_at)

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

    @staticmethod
    def _is_binance_locked_redemption_loss(event: CanonicalEvent) -> bool:
        return (
            event.source.strip().lower() == "binance_simple_earn_api"
            and event.event_type == "fee"
            and event.quantity < 0
            and str(event.source_ref or "").startswith(
                "locked_redemption_loss:"
            )
        )

    def _consume_fifo_without_tax_line(
        self,
        *,
        event: CanonicalEvent,
        lots: deque[TaxLot],
        reward_event_ids: frozenset[str],
    ) -> list[TaxUnmatchedDisposal]:
        quantity = abs(event.quantity)
        quantity_remaining = quantity
        eligible_lots = [
            lot for lot in lots if lot.source_event_id in reward_event_ids
        ]
        available_before = sum(
            (lot.quantity_remaining for lot in eligible_lots), Decimal("0")
        )
        for lot in eligible_lots:
            if quantity_remaining <= 0:
                break
            used_quantity = min(quantity_remaining, lot.quantity_remaining)
            lot.quantity_remaining -= used_quantity
            quantity_remaining -= used_quantity
            if lot.quantity_remaining == 0:
                lots.remove(lot)
        if quantity_remaining == 0:
            return []
        return [
            TaxUnmatchedDisposal(
                unmatched_id=str(uuid4()),
                source_event_id=event.event_id,
                source=event.source,
                source_ref=event.source_ref,
                raw_object_id=event.raw_object_id,
                event_time=event.event_time,
                event_type=event.event_type,
                account=event.account,
                asset=event.asset,
                quantity=quantity,
                matched_quantity=quantity - quantity_remaining,
                missing_quantity=quantity_remaining,
                available_before=available_before,
                proceeds_total_eur=Decimal("0"),
            )
        ]

    def _consume_fifo(
        self,
        event: CanonicalEvent,
        lots: deque[TaxLot],
    ) -> tuple[list[TaxLine], list[TaxUnmatchedDisposal]]:
        return self._consume_fifo_asset(
            asset=event.asset,
            quantity=abs(event.quantity),
            disposed_at=event.event_time,
            proceeds_total=self._disposal_value_eur(event),
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

    def _use_received_asset_value_for_quote_disposal(
        self,
        event: CanonicalEvent,
        *,
        received_asset_first: bool = False,
    ) -> bool:
        if event.quote_asset is None or event.quote_quantity is None:
            return False
        return (
            event.quantity > 0
            and event.quote_asset not in FIAT_TAX_EXCLUDED_ASSETS
            and (
                received_asset_first
                or event.asset.upper() in STABLE_VALUE_ANCHOR_ASSETS
            )
        )

    def _available_quantity(self, lots: deque[TaxLot]) -> Decimal:
        return sum((lot.quantity_remaining for lot in lots), Decimal("0"))

    def _eur_value(self, event: CanonicalEvent, *, prefer_received_asset: bool = False) -> Decimal:
        if prefer_received_asset and event.quantity > 0:
            received_value = self._asset_value_eur(event.asset, abs(event.quantity), event.event_time)
            if received_value is not None:
                return received_value
        if event.quote_quantity is not None and event.quote_asset is not None:
            if event.quote_asset == "EUR":
                return abs(event.quote_quantity)
            quote_value = self._asset_value_eur(
                event.quote_asset,
                abs(event.quote_quantity),
                event.event_time,
            )
            if quote_value is None:
                return Decimal("0")
            return quote_value
        value = self._asset_value_eur(event.asset, abs(event.quantity), event.event_time)
        if value is None:
            return Decimal("0")
        return value

    def _disposal_value_eur(self, event: CanonicalEvent) -> Decimal:
        value = self._eur_value(event)
        if (
            event.event_type == "trade"
            and event.quantity < 0
            and event.quote_asset
            and event.fee_asset
            and event.fee_quantity
            and event.quote_asset.upper() == event.fee_asset.upper()
        ):
            fee_value = self._asset_value_eur(
                event.fee_asset,
                abs(event.fee_quantity),
                event.event_time,
            )
            if fee_value is not None:
                return max(value - fee_value, Decimal("0"))
        return value

    @staticmethod
    def _net_acquired_quantity(
        *,
        event: CanonicalEvent,
        acquired_asset: str,
        gross_quantity: Decimal,
    ) -> Decimal:
        if (
            gross_quantity > 0
            and event.fee_asset
            and event.fee_quantity
            and event.fee_asset.upper() == acquired_asset.upper()
        ):
            return max(gross_quantity - abs(event.fee_quantity), Decimal("0"))
        return gross_quantity

    def _asset_value_eur(self, asset: str, quantity: Decimal, at: datetime) -> Decimal | None:
        if asset == "EUR":
            return quantity
        price = self.price_lookup.at_or_before(asset, at)
        if price is None:
            return None
        return quantity * price.price_eur

    def _replace_tax_tables(
        self,
        lots: list[TaxLot],
        tax_lines: list[TaxLine],
        unmatched_disposals: list[TaxUnmatchedDisposal],
        *,
        fifo_method: str = GLOBAL_ASSET_FIFO_SCOPE,
        input_fingerprint_digest: str | None = None,
    ) -> None:
        created_at = datetime.now(timezone.utc)
        with self.store.connect() as con:
            con.execute("begin transaction")
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
                            lot.pool_id,
                            lot.origin_lot_id,
                            lot.fifo_method,
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
                        "pool_id",
                        "origin_lot_id",
                        "fifo_method",
                        "created_at",
                    ],
                )
                con.register("tax_lots_to_insert", lot_frame)
                con.execute(
                    """
                    insert into tax_lots (
                        lot_id, asset, acquired_at, quantity_total,
                        quantity_remaining, cost_basis_eur_total,
                        source_event_id, pool_id, origin_lot_id,
                        fifo_method, created_at
                    )
                    select
                        lot_id, asset, acquired_at,
                        cast(quantity_total as decimal(38, 18)),
                        cast(quantity_remaining as decimal(38, 18)),
                        cast(cost_basis_eur_total as decimal(38, 18)),
                        source_event_id, pool_id, origin_lot_id,
                        fifo_method, created_at
                    from tax_lots_to_insert
                    """
                )
                con.unregister("tax_lots_to_insert")
            con.execute(
                """
                insert into tax_run_summaries (
                    run_id, tax_lines_count, unmatched_disposals, created_at,
                    fifo_method, input_fingerprint_digest
                )
                values (?, ?, ?, ?, ?, ?)
                """,
                [
                    str(uuid4()),
                    len(tax_lines),
                    len(unmatched_disposals),
                    created_at,
                    fifo_method,
                    input_fingerprint_digest,
                ],
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
                            line.pool_id,
                            line.acquired_at,
                            line.acquisition_source_event_id,
                            line.origin_lot_id,
                            line.fifo_method,
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
                        "pool_id",
                        "acquired_at",
                        "acquisition_source_event_id",
                        "origin_lot_id",
                        "fifo_method",
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
                        lot_id, pool_id, acquired_at,
                        acquisition_source_event_id, origin_lot_id,
                        fifo_method, created_at
                    )
                    select
                        tax_line_id, asset, disposed_at,
                        cast(quantity as decimal(38, 18)),
                        cast(acquisition_cost_eur as decimal(38, 18)),
                        cast(disposal_proceeds_eur as decimal(38, 18)),
                        cast(gain_loss_eur as decimal(38, 18)),
                        holding_days, source_event_id, lot_id, pool_id,
                        acquired_at, acquisition_source_event_id, origin_lot_id,
                        fifo_method, created_at
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
            counts = con.execute(
                """
                select
                    (select count(*) from tax_lots),
                    (select count(*) from tax_lines),
                    (select count(*) from tax_unmatched_disposals),
                    (select count(*) from tax_run_summaries),
                    (
                        select count(*)
                        from tax_lines line
                        left join tax_lots lot on lot.lot_id = line.lot_id
                        where lot.lot_id is null
                    ),
                    (select count(*) from tax_lots where coalesce(fifo_method, '') <> ?),
                    (select count(*) from tax_lines where coalesce(fifo_method, '') <> ?)
                """,
                [fifo_method, fifo_method],
            ).fetchone()
            expected = (
                len(lots),
                len(tax_lines),
                len(unmatched_disposals),
                1,
                0,
                0,
                0,
            )
            if tuple(int(value) for value in counts) != expected:
                raise ValueError(
                    "Atomarer Tax-Tabellentausch hat die internen "
                    f"Integritaetschecks nicht bestanden: {counts} != {expected}."
                )
            con.execute("commit")
