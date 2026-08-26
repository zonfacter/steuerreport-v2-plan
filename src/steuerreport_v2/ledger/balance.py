from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pandas as pd

from steuerreport_v2.contracts.ledger import BalanceLedgerEntry, BalancePosition
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.account_aliases import (
    build_account_alias_map_for_store,
    canonical_account_label,
)

MIN_DECIMAL_DUST = Decimal("0.000000000001")
STABLE_BALANCE_DUST = Decimal("0.00001")
STABLE_BALANCE_DUST_ASSETS = {"EUR", "USD", "USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD"}


class BalanceLedgerBuilder:
    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def rebuild(self) -> list[BalanceLedgerEntry]:
        events = self.store.list_canonical_events()
        account_aliases = build_account_alias_map_for_store(self.store)
        bitget_quote_mirrors = {
            (
                event.event_time.replace(tzinfo=timezone.utc)
                if event.event_time.tzinfo is None
                else event.event_time.astimezone(timezone.utc),
                event.asset.upper(),
                event.quantity,
            )
            for event in events
            if event.source == "bitget-tax-api-evidence"
            and str(event.account or event.wallet or "").strip().lower() == "bitget"
        }
        balances: defaultdict[tuple[str, str], Decimal] = defaultdict(lambda: Decimal("0"))
        entries: list[BalanceLedgerEntry] = []

        for event in events:
            account = canonical_account_label(event.account, account_aliases)
            movements: list[tuple[str, Decimal]] = [(event.asset, event.quantity)]
            if (
                event.event_type == "trade"
                and event.quote_asset is not None
                and event.quote_quantity is not None
            ):
                quote_delta = abs(event.quote_quantity)
                if event.quantity > 0:
                    quote_delta = -quote_delta
                quote_time = (
                    event.event_time.replace(tzinfo=timezone.utc)
                    if event.event_time.tzinfo is None
                    else event.event_time.astimezone(timezone.utc)
                )
                mirrored = bool(
                    event.source == "blockpit"
                    and str(event.account or event.wallet or "").strip().lower()
                    == "bitget"
                    and any(
                        abs((mirror_time - quote_time).total_seconds()) <= 10
                        and mirror_asset == event.quote_asset.upper()
                        and mirror_quantity == quote_delta
                        for mirror_time, mirror_asset, mirror_quantity in bitget_quote_mirrors
                    )
                )
                if not mirrored:
                    movements.append((event.quote_asset, quote_delta))
            if (
                event.event_type != "derivative"
                and event.fee_asset is not None
                and event.fee_quantity is not None
            ):
                movements.append((event.fee_asset, -abs(event.fee_quantity)))

            for asset, delta_quantity in movements:
                key = (account, asset)
                balances[key] += delta_quantity
                balances[key] = self._zero_balance_dust(asset, balances[key])
                entries.append(
                    BalanceLedgerEntry(
                        ledger_id=str(uuid4()),
                        event_id=event.event_id,
                        event_time=event.event_time,
                        account=account,
                        asset=asset,
                        delta_quantity=delta_quantity,
                        balance_quantity=balances[key],
                    )
                )

        self._replace_entries(entries)
        return entries

    def positions(self) -> list[BalancePosition]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select account, asset, sum(delta_quantity) as quantity
                from balance_ledger
                group by account, asset
                order by account, asset
                """
            ).fetchall()
        return [
            BalancePosition(account=row[0], asset=row[1], quantity=row[2])
            for row in rows
        ]

    def _zero_balance_dust(self, asset: str, quantity: Decimal) -> Decimal:
        if abs(quantity) <= MIN_DECIMAL_DUST:
            return Decimal("0")
        if asset.upper() in STABLE_BALANCE_DUST_ASSETS and abs(quantity) <= STABLE_BALANCE_DUST:
            return Decimal("0")
        return quantity

    def _replace_entries(self, entries: list[BalanceLedgerEntry]) -> None:
        created_at = datetime.now(timezone.utc)
        with self.store.connect() as con:
            con.execute("delete from balance_ledger")
            if not entries:
                return
            frame = pd.DataFrame(
                [
                    (
                        entry.ledger_id,
                        entry.event_id,
                        entry.event_time,
                        entry.account,
                        entry.asset,
                        str(entry.delta_quantity),
                        str(entry.balance_quantity),
                        created_at,
                    )
                    for entry in entries
                ],
                columns=[
                    "ledger_id",
                    "event_id",
                    "event_time",
                    "account",
                    "asset",
                    "delta_quantity",
                    "balance_quantity",
                    "created_at",
                ],
            )
            con.register("balance_entries_to_insert", frame)
            con.execute(
                """
                insert into balance_ledger (
                    ledger_id, event_id, event_time, account, asset,
                    delta_quantity, balance_quantity, created_at
                )
                select
                    ledger_id, event_id, event_time, account, asset,
                    cast(delta_quantity as decimal(38, 18)),
                    cast(balance_quantity as decimal(38, 18)),
                    created_at
                from balance_entries_to_insert
                """
            )
            con.unregister("balance_entries_to_insert")
