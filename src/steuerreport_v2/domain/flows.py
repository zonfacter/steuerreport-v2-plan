from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pandas as pd

from steuerreport_v2.contracts.flows import FlowEntry, NetFlowEdge, NetFlowSummary
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.account_aliases import (
    build_account_alias_map_for_store,
    canonical_account_label,
)
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup
from steuerreport_v2.domain.tax_time import reporting_tax_year, source_period_event_years

FLOW_EVENT_TYPES = {"transfer", "income", "reward", "staking", "mining"}


class FlowService:
    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def rebuild(self) -> list[FlowEntry]:
        entries: list[FlowEntry] = []
        price_lookup = HistoricalPriceLookup(self.store)
        events = self.store.list_canonical_events()
        account_aliases = build_account_alias_map_for_store(self.store)

        for event in events:
            if event.event_type not in FLOW_EVENT_TYPES:
                continue

            account = canonical_account_label(event.account, account_aliases)
            quantity_abs = abs(event.quantity)
            if event.quantity >= 0:
                source_node = "external"
                target_node = account
            else:
                source_node = account
                target_node = "external"

            value_eur = None
            price_source = None
            if event.quote_asset == "EUR" and event.quote_quantity is not None:
                value_eur = abs(event.quote_quantity)
                price_source = "event_quote"
            else:
                price = price_lookup.at_or_before(event.asset, event.event_time)
                if price is not None:
                    value_eur = quantity_abs * price.price_eur
                    price_source = price.source

            entries.append(
                FlowEntry(
                    flow_id=str(uuid4()),
                    event_id=event.event_id,
                    event_time=event.event_time,
                    source_node=source_node,
                    target_node=target_node,
                    asset=event.asset,
                    quantity=quantity_abs,
                    value_eur=value_eur,
                    price_source=price_source,
                )
            )

        self._replace_entries(entries)
        return entries

    def summary(self, year: int | None = None) -> NetFlowSummary:
        entries = self._list_entries()
        period_years = source_period_event_years(self.store)

        def entry_year(entry: FlowEntry) -> int:
            return period_years.get(
                entry.event_id,
                reporting_tax_year(entry.event_time),
            )

        available_years = sorted({entry_year(entry) for entry in entries})
        if year is not None:
            entries = [entry for entry in entries if entry_year(entry) == year]
        net_edges: defaultdict[tuple[str, str], dict[str, Decimal | int | str]] = defaultdict(
            lambda: {
                "signed_value_eur": Decimal("0"),
                "event_count": 0,
                "positive_source": "",
                "positive_target": "",
            }
        )
        missing: set[str] = set()

        for entry in entries:
            if entry.value_eur is None:
                missing.add(entry.asset)
                continue
            source = entry.source_node
            target = entry.target_node
            if source <= target:
                key = (source, target)
                direction = Decimal("1")
                positive_source = source
                positive_target = target
            else:
                key = (target, source)
                direction = Decimal("-1")
                positive_source = target
                positive_target = source
            net_edges[key]["signed_value_eur"] = net_edges[key]["signed_value_eur"] + (entry.value_eur * direction)
            net_edges[key]["event_count"] = int(net_edges[key]["event_count"]) + 1
            net_edges[key]["positive_source"] = positive_source
            net_edges[key]["positive_target"] = positive_target

        edge_models: list[NetFlowEdge] = []
        for _, data in sorted(net_edges.items()):
            signed_value = data["signed_value_eur"]
            if not isinstance(signed_value, Decimal) or signed_value == 0:
                continue
            positive_source = str(data["positive_source"])
            positive_target = str(data["positive_target"])
            if signed_value > 0:
                source_node = positive_source
                target_node = positive_target
                value_eur = signed_value
            else:
                source_node = positive_target
                target_node = positive_source
                value_eur = abs(signed_value)
            edge_models.append(
                NetFlowEdge(
                    source_node=source_node,
                    target_node=target_node,
                    value_eur=value_eur,
                    event_count=int(data["event_count"]),
                )
            )
        return NetFlowSummary(
            year=year,
            available_years=available_years,
            total_visible_value_eur=sum(
                (edge.value_eur for edge in edge_models),
                Decimal("0"),
            ),
            edges=edge_models,
            missing_price_assets=sorted(missing),
        )

    def _replace_entries(self, entries: list[FlowEntry]) -> None:
        created_at = datetime.now(timezone.utc)
        with self.store.connect() as con:
            con.execute("delete from flow_ledger")
            if not entries:
                return
            frame = pd.DataFrame(
                [
                    (
                        entry.flow_id,
                        entry.event_id,
                        entry.event_time,
                        entry.source_node,
                        entry.target_node,
                        entry.asset,
                        str(entry.quantity),
                        str(entry.value_eur) if entry.value_eur is not None else None,
                        entry.price_source,
                        created_at,
                    )
                    for entry in entries
                ],
                columns=[
                    "flow_id",
                    "event_id",
                    "event_time",
                    "source_node",
                    "target_node",
                    "asset",
                    "quantity",
                    "value_eur",
                    "price_source",
                    "created_at",
                ],
            )
            con.register("flow_entries_to_insert", frame)
            con.execute(
                """
                insert into flow_ledger (
                    flow_id, event_id, event_time, source_node, target_node,
                    asset, quantity, value_eur, price_source, created_at
                )
                select
                    flow_id, event_id, event_time, source_node, target_node,
                    asset,
                    cast(quantity as decimal(38, 18)),
                    cast(value_eur as decimal(38, 18)),
                    price_source, created_at
                from flow_entries_to_insert
                """
            )
            con.unregister("flow_entries_to_insert")

    def _list_entries(self) -> list[FlowEntry]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    flow_id, event_id, event_time, source_node, target_node,
                    asset, quantity, value_eur, price_source
                from flow_ledger
                order by event_time, flow_id
                """
            ).fetchall()
        return [
            FlowEntry(
                flow_id=row[0],
                event_id=row[1],
                event_time=row[2],
                source_node=row[3],
                target_node=row[4],
                asset=row[5],
                quantity=row[6],
                value_eur=row[7],
                price_source=row[8],
            )
            for row in rows
        ]
