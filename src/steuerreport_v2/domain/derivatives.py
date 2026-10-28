from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pandas as pd

from steuerreport_v2.contracts.derivatives import (
    DerivativeLine,
    DerivativeRunResult,
    DerivativeRunSummary,
)
from steuerreport_v2.contracts.events import CanonicalEvent
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.account_aliases import (
    build_account_alias_map_for_store,
    canonical_account_label,
)
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup
from steuerreport_v2.domain.derivative_cash import derivative_cash, derivative_raw_rows


class DerivativesManager:
    def __init__(self, store: DuckDbStore) -> None:
        self.store = store
        self.price_lookup = HistoricalPriceLookup(store)

    def rebuild(self) -> DerivativeRunResult:
        lines: list[DerivativeLine] = []
        missing_price_count = 0
        account_aliases = build_account_alias_map_for_store(self.store)
        raw_rows = derivative_raw_rows(self.store)

        for event in self.store.list_canonical_events():
            if event.event_type != "derivative":
                continue
            for asset, quantity in derivative_cash(event, raw_rows.get(event.event_id)).legs:
                if quantity == 0:
                    continue
                line = self._line_from_event(event.model_copy(update={"asset": asset, "quantity": quantity}), account_aliases)
                if line.price_source is None:
                    missing_price_count += 1
                lines.append(line)

        summary = self._replace_derivative_tables(lines, missing_price_count)
        return DerivativeRunResult(lines=lines, summary=summary)

    def latest_summary(self) -> DerivativeRunSummary | None:
        with self.store.connect() as con:
            row = con.execute(
                """
                select
                    run_id, derivative_lines_count, realized_pnl_eur,
                    missing_price_count, created_at
                from derivative_run_summaries
                order by created_at desc
                limit 1
                """
            ).fetchone()
        if row is None:
            return None
        return DerivativeRunSummary(
            run_id=row[0],
            derivative_lines_count=row[1],
            realized_pnl_eur=row[2],
            missing_price_count=row[3],
            created_at=row[4],
        )

    def list_lines(self) -> list[DerivativeLine]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    derivative_line_id, event_id, source, source_ref,
                    event_time, account, asset, quantity, price_eur,
                    value_eur, price_source
                from derivative_lines
                order by event_time, derivative_line_id
                """
            ).fetchall()
        return [
            DerivativeLine(
                derivative_line_id=row[0],
                event_id=row[1],
                source=row[2],
                source_ref=row[3],
                event_time=row[4],
                account=row[5],
                asset=row[6],
                quantity=row[7],
                price_eur=row[8],
                value_eur=row[9],
                price_source=row[10],
            )
            for row in rows
        ]

    def _line_from_event(self, event: CanonicalEvent, account_aliases: dict[str, str]) -> DerivativeLine:
        price = self.price_lookup.at_or_before(event.asset, event.event_time)
        price_eur = price.price_eur if price is not None else Decimal("0")
        return DerivativeLine(
            derivative_line_id=str(uuid4()),
            event_id=event.event_id,
            source=event.source,
            source_ref=event.source_ref,
            event_time=event.event_time,
            account=canonical_account_label(event.account, account_aliases),
            asset=event.asset,
            quantity=event.quantity,
            price_eur=price_eur,
            value_eur=event.quantity * price_eur,
            price_source=price.source if price is not None else None,
        )

    def _replace_derivative_tables(
        self,
        lines: list[DerivativeLine],
        missing_price_count: int,
    ) -> DerivativeRunSummary:
        created_at = datetime.now(timezone.utc)
        realized_pnl_eur = sum((line.value_eur for line in lines), Decimal("0"))
        summary = DerivativeRunSummary(
            run_id=str(uuid4()),
            derivative_lines_count=len(lines),
            realized_pnl_eur=realized_pnl_eur,
            missing_price_count=missing_price_count,
            created_at=created_at,
        )
        with self.store.connect() as con:
            con.execute("delete from derivative_lines")
            con.execute("delete from derivative_run_summaries")
            con.execute(
                """
                insert into derivative_run_summaries (
                    run_id, derivative_lines_count, realized_pnl_eur,
                    missing_price_count, created_at
                )
                values (?, ?, ?, ?, ?)
                """,
                [
                    summary.run_id,
                    summary.derivative_lines_count,
                    str(summary.realized_pnl_eur),
                    summary.missing_price_count,
                    summary.created_at,
                ],
            )
            if not lines:
                return summary
            frame = pd.DataFrame(
                [
                    (
                        line.derivative_line_id,
                        line.event_id,
                        line.source,
                        line.source_ref,
                        line.event_time,
                        line.account,
                        line.asset,
                        str(line.quantity),
                        str(line.price_eur),
                        str(line.value_eur),
                        line.price_source,
                        created_at,
                    )
                    for line in lines
                ],
                columns=[
                    "derivative_line_id",
                    "event_id",
                    "source",
                    "source_ref",
                    "event_time",
                    "account",
                    "asset",
                    "quantity",
                    "price_eur",
                    "value_eur",
                    "price_source",
                    "created_at",
                ],
            )
            con.register("derivative_lines_to_insert", frame)
            con.execute(
                """
                insert into derivative_lines (
                    derivative_line_id, event_id, source, source_ref,
                    event_time, account, asset, quantity, price_eur,
                    value_eur, price_source, created_at
                )
                select
                    derivative_line_id, event_id, source, source_ref,
                    event_time, account, asset,
                    cast(quantity as decimal(38, 18)),
                    cast(price_eur as decimal(38, 18)),
                    cast(value_eur as decimal(38, 18)),
                    price_source, created_at
                from derivative_lines_to_insert
                """
            )
            con.unregister("derivative_lines_to_insert")
        return summary
