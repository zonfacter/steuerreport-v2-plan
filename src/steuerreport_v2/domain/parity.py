from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from decimal import Decimal
from pathlib import Path

from steuerreport_v2.contracts.parity import (
    HntFifoProvenanceEvent,
    HntFifoProvenanceLot,
    HntFifoProvenanceReport,
    HntFifoProvenanceTaxLine,
    HntFifoProvenanceTimelineStep,
    HntWalletBridgeReport,
    HntWalletBridgeRow,
    ParityDecisionStatus,
    ParityStatus,
    V1ParityGroupDetail,
    V1ParityGroupMetricDetail,
    V1ParityDiagnostics,
    V1ParityIssueGroup,
    V1ParityReleaseReadiness,
    V1ParityRow,
    V1ParitySummary,
    V1ParityTaxEventSample,
    V1ParityTaxSourceSummary,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.flows import FlowService
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_time import reporting_tax_year, reporting_year_sql

MetricKey = tuple[str, str, str, int | None, str | None, str | None]
DEFAULT_PRICE_CONFIG = Path("/workspace/steuerreport-v2-plan/configs/crypto_price_sources.json")
HNT_CURRENT_PORTFOLIO_ACCOUNTS = {
    PortfolioService.KNOWN_JUP_WALLET,
    PortfolioService.PRIMARY_SOLANA_WALLET,
}
HNT_TRANSFER_COUNTERPARTY_ACCOUNTS = {
    "binance",
    "Binance",
    "helium",
    PortfolioService.MAIN_HELIUM_LEGACY_WALLET,
    PortfolioService.FAIRSPOT_STAKING_WALLET,
}


class V1ParityService:
    def __init__(self, store: DuckDbStore) -> None:
        self.store = store
        self._asset_aliases = self._load_asset_aliases(DEFAULT_PRICE_CONFIG)

    def compare(self) -> V1ParitySummary:
        v2_values = self._v2_metrics()
        rows: list[V1ParityRow] = []
        for reference in self.store.list_v1_reference_metrics():
            key = self._key(
                scope=reference.scope,
                metric=reference.metric,
                unit=reference.unit,
                year=reference.year,
                asset=reference.asset,
                source=reference.source,
            )
            v2_value = v2_values.get(key)
            if v2_value is None and reference.source is not None:
                v2_value = v2_values.get(
                    self._key(
                        scope=reference.scope,
                        metric=reference.metric,
                        unit=reference.unit,
                        year=reference.year,
                        asset=reference.asset,
                        source=None,
                    )
                )
            if v2_value is None and reference.value == 0:
                v2_value = Decimal("0")
            difference = None if v2_value is None else v2_value - reference.value
            absolute_difference = None if difference is None else abs(difference)
            if v2_value is None:
                status = "missing_v2"
            elif difference == 0:
                status = "match"
            else:
                status = "diff"
            rows.append(
                V1ParityRow(
                    reference=reference,
                    v2_value=v2_value,
                    difference=difference,
                    absolute_difference=absolute_difference,
                    status=status,
                )
            )

        return V1ParitySummary(
            rows=rows,
            compared=len(rows),
            matches=sum(1 for row in rows if row.status == "match"),
            differences=sum(1 for row in rows if row.status == "diff"),
            missing_v2=sum(1 for row in rows if row.status == "missing_v2"),
            max_absolute_difference=max(
                (row.absolute_difference for row in rows if row.absolute_difference is not None),
                default=Decimal("0"),
            ),
        )

    def diagnostics(self) -> V1ParityDiagnostics:
        summary = self.compare()
        decisions = self._parity_decisions_by_scope()
        grouped: dict[tuple[int | None, str | None, str], list[V1ParityRow]] = defaultdict(list)
        for row in summary.rows:
            if row.status == "match":
                continue
            grouped[
                (
                    row.reference.year,
                    row.reference.asset,
                    row.status,
                )
            ].append(row)

        groups = [
            self._issue_group(
                year=year,
                asset=asset,
                status=status,
                rows=rows,
                decisions=decisions,
            )
            for (year, asset, status), rows in grouped.items()
        ]
        groups.sort(
            key=lambda group: (
                group.absolute_difference_eur,
                group.max_absolute_difference,
                Decimal(group.issue_count),
            ),
            reverse=True,
        )
        return V1ParityDiagnostics(
            compared=summary.compared,
            matches=summary.matches,
            differences=summary.differences,
            missing_v2=summary.missing_v2,
            groups=groups,
        )

    def release_readiness(self) -> V1ParityReleaseReadiness:
        diagnostics = self.diagnostics()
        blocking_statuses = {"unreviewed", "needs_manual_evidence", "v2_missing_data"}
        accepted_statuses = {"v1_known_wrong", "v2_corrected", "accepted_difference"}
        blocking_groups = [
            group
            for group in diagnostics.groups
            if group.decision_status in blocking_statuses
        ]
        return V1ParityReleaseReadiness(
            release_ready=len(blocking_groups) == 0,
            compared=diagnostics.compared,
            matches=diagnostics.matches,
            differences=diagnostics.differences,
            missing_v2=diagnostics.missing_v2,
            groups_total=len(diagnostics.groups),
            unresolved_groups=sum(
                1 for group in diagnostics.groups if group.decision_status == "unreviewed"
            ),
            blocking_groups=len(blocking_groups),
            accepted_groups=sum(
                1 for group in diagnostics.groups if group.decision_status in accepted_statuses
            ),
            max_absolute_difference=max(
                (group.max_absolute_difference for group in diagnostics.groups),
                default=Decimal("0"),
            ),
            blocking_difference_eur=sum(
                (group.absolute_difference_eur for group in blocking_groups),
                Decimal("0"),
            ),
            blocking_groups_top=blocking_groups[:20],
        )

    def group_detail(self, scope: str) -> V1ParityGroupDetail:
        year, asset, status = self._parse_issue_scope(scope)
        decisions = self._parity_decisions_by_scope()
        rows = self._compare_group_rows(year=year, asset=asset, status=status)
        group = None
        if status is not None:
            group = self._issue_group(
                year=year,
                asset=asset,
                status=status,
                rows=rows,
                decisions=decisions,
            )
        metrics = [
            V1ParityGroupMetricDetail(
                metric=row.reference.metric,
                unit=row.reference.unit,
                v1_value=row.reference.value,
                v2_value=row.v2_value,
                difference=row.difference,
                absolute_difference=row.absolute_difference,
            )
            for row in rows
        ]
        tax_source_summaries: list[V1ParityTaxSourceSummary] = []
        tax_event_samples: list[V1ParityTaxEventSample] = []
        if year is not None and asset is not None:
            tax_source_summaries = self._tax_source_summaries(year, asset)
            tax_event_samples = self._tax_event_samples(year, asset)
        return V1ParityGroupDetail(
            scope=scope,
            year=year,
            asset=asset,
            status=status,
            decision_status=group.decision_status if group is not None else "unreviewed",
            metrics=metrics,
            tax_source_summaries=tax_source_summaries,
            tax_event_samples=tax_event_samples,
        )

    def _compare_group_rows(
        self,
        year: int | None,
        asset: str | None,
        status: ParityStatus | None,
    ) -> list[V1ParityRow]:
        if year is None or asset is None or status is None:
            return [
                row
                for row in self.compare().rows
                if row.reference.year == year
                and row.reference.asset == asset
                and row.status == status
            ]

        references = [
            reference
            for reference in self.store.list_v1_reference_metrics()
            if reference.year == year and reference.asset == asset.upper()
        ]
        tax_values = self._v2_tax_metrics_for_group(year, asset)
        rows: list[V1ParityRow] = []
        for reference in references:
            v2_value = tax_values.get(
                (
                    reference.scope,
                    reference.metric,
                    self._canonical_unit(reference.unit),
                )
            )
            if v2_value is None:
                v2_value = self._v2_metrics().get(
                    self._key(
                        scope=reference.scope,
                        metric=reference.metric,
                        unit=reference.unit,
                        year=reference.year,
                    asset=self._canonical_asset(reference.asset),
                        source=reference.source,
                    )
                )
            if v2_value is None and reference.source is not None:
                v2_value = tax_values.get(
                    (
                        reference.scope,
                        reference.metric,
                        self._canonical_unit(reference.unit),
                    )
                )
            if v2_value is None and reference.value == 0:
                v2_value = Decimal("0")
            difference = None if v2_value is None else v2_value - reference.value
            absolute_difference = None if difference is None else abs(difference)
            row_status: ParityStatus
            if v2_value is None:
                row_status = "missing_v2"
            elif difference == 0:
                row_status = "match"
            else:
                row_status = "diff"
            if row_status != status:
                continue
            rows.append(
                V1ParityRow(
                    reference=reference,
                    v2_value=v2_value,
                    difference=difference,
                    absolute_difference=absolute_difference,
                    status=row_status,
                )
            )
        return rows

    def _v2_tax_metrics_for_group(
        self,
        year: int,
        asset: str,
    ) -> dict[tuple[str, str, str], Decimal]:
        canonical_asset = self._canonical_asset(asset)
        with self.store.connect() as con:
            row = con.execute(
                f"""
                select
                    coalesce(sum(quantity), 0) as quantity_disposed,
                    coalesce(sum(acquisition_cost_eur), 0) as acquisition_cost_eur,
                    coalesce(sum(disposal_proceeds_eur), 0) as disposal_proceeds_eur,
                    coalesce(sum(gain_loss_eur), 0) as gain_loss_eur
                from tax_lines
                where asset = ?
                  and {reporting_year_sql('disposed_at')} = ?
                """,
                [canonical_asset, year],
            ).fetchone()
        if row is None:
            return {}
        return {
            ("tax", "quantity_disposed", canonical_asset): row[0],
            ("tax", "acquisition_cost_eur", "EUR"): row[1],
            ("tax", "disposal_proceeds_eur", "EUR"): row[2],
            ("tax", "gain_loss_eur", "EUR"): row[3],
        }

    def hnt_wallet_bridge(self, year: int) -> HntWalletBridgeReport:
        rows = self._hnt_wallet_bridge_rows(year)
        v1_quantity = self._v1_quantity_disposed(year, "HNT")
        v2_quantity = self._v2_quantity_disposed(year, "HNT")

        def qty(source: str | None = None, event_type: str | None = None, direction: str | None = None) -> Decimal:
            return sum(
                (
                    row.quantity
                    for row in rows
                    if (source is None or row.source == source)
                    and (event_type is None or row.event_type == event_type)
                    and (direction is None or row.direction == direction)
                ),
                Decimal("0"),
            )

        pionex_buys = qty("pionex", "trade", "in")
        pionex_sells = abs(qty("pionex", "trade", "out"))
        wallet_mining_in = qty("helium", "mining", "in")
        wallet_transfer_in = qty("helium", "transfer", "in")
        wallet_fees_out = abs(qty("helium", "fee", "out"))
        binance_in = sum(
            (row.quantity for row in rows if row.source == "binance" and row.direction == "in"),
            Decimal("0"),
        )
        binance_out = abs(
            sum(
                (row.quantity for row in rows if row.source == "binance" and row.direction == "out"),
                Decimal("0"),
            )
        )
        interpretation = (
            "Der HNT-Wallet-Export belegt Mining- und Transferbewegungen. "
            "Die grosse 2022-Abweichung entsteht jedoch aus Pionex-internen "
            "HNT_USDT-Spot-Trades: Pionex zeigt sowohl hohe HNT-Kaeufe als "
            "auch hohe HNT-Verkaeufe. Damit ist der naechste Pruefschritt kein "
            "Wallet-Import, sondern die steuerliche Klassifizierung dieser "
            "Pionex-Detailfills gegen die V1/WISO-Referenz."
        )
        return HntWalletBridgeReport(
            year=year,
            v1_quantity_disposed=v1_quantity,
            v2_quantity_disposed=v2_quantity,
            quantity_difference=(
                None if v1_quantity is None else v2_quantity - v1_quantity
            ),
            pionex_buys=pionex_buys,
            pionex_sells=pionex_sells,
            pionex_net=pionex_buys - pionex_sells,
            wallet_mining_in=wallet_mining_in,
            wallet_transfer_in=wallet_transfer_in,
            wallet_fees_out=wallet_fees_out,
            binance_in=binance_in,
            binance_out=binance_out,
            rows=rows,
            interpretation=interpretation,
        )

    def hnt_fifo_provenance(
        self,
        limit: int = 200,
        source: str | None = None,
        account: str | None = None,
        from_at: datetime | None = None,
        to_at: datetime | None = None,
    ) -> HntFifoProvenanceReport:
        event_limit = max(1, min(limit, 1000))
        events = self._hnt_fifo_provenance_events(
            event_limit,
            source=source,
            account=account,
            from_at=from_at,
            to_at=to_at,
        )
        open_lots = self._hnt_open_fifo_lots(source=source, account=account, from_at=from_at, to_at=to_at)
        disposal_lines = self._hnt_disposal_tax_lines(source=source, account=account, from_at=from_at, to_at=to_at)
        counts = self._hnt_fifo_provenance_counts(source=source, account=account, from_at=from_at, to_at=to_at)
        return HntFifoProvenanceReport(
            generated_at=datetime.now(timezone.utc),
            event_limit=event_limit,
            filter_source=source,
            filter_account=account,
            filter_from=from_at,
            filter_to=to_at,
            current_portfolio_accounts=sorted(HNT_CURRENT_PORTFOLIO_ACCOUNTS),
            transfer_counterparty_accounts=sorted(HNT_TRANSFER_COUNTERPARTY_ACCOUNTS),
            current_portfolio_events=counts["current_portfolio_events"],
            transfer_counterparty_events=counts["transfer_counterparty_events"],
            fifo_relevant_events=counts["fifo_relevant_events"],
            open_lots=counts["open_lots"],
            disposals=counts["disposals"],
            timeline=self._hnt_fifo_timeline(events),
            events=events,
            open_fifo_lots=open_lots,
            disposal_tax_lines=disposal_lines,
            methodology=(
                "Read-only HNT-Herkunftsansicht aus Canonical Events, FIFO-Lots "
                "und Tax-Lines. Transfer-Gegenparteien wie Helium Legacy, Fairspot "
                "und Binance bleiben als Belegkette sichtbar, werden aber nicht als "
                "aktuelle Portfolio-Wallets gewertet. Der Report erzeugt keine "
                "Imports, keine Review-Entscheidungen und keinen FIFO-Rebuild."
            ),
        )

    def _issue_group(
        self,
        year: int | None,
        asset: str | None,
        status: str,
        rows: list[V1ParityRow],
        decisions: dict[str, tuple[ParityDecisionStatus, str, str]],
    ) -> V1ParityIssueGroup:
        eur_rows = [row for row in rows if row.reference.unit.upper() == "EUR"]
        scope = self.issue_scope(year=year, asset=asset, status=status)
        decision = decisions.get(scope)
        return V1ParityIssueGroup(
            scope=scope,
            year=year,
            asset=asset,
            status=status,  # type: ignore[arg-type]
            decision_status=decision[0] if decision is not None else "unreviewed",
            decision_id=decision[1] if decision is not None else None,
            decision_title=decision[2] if decision is not None else None,
            issue_count=len(rows),
            metrics=sorted({row.reference.metric for row in rows}),
            v1_total_eur=sum((row.reference.value for row in eur_rows), Decimal("0")),
            v2_total_eur=sum(
                (row.v2_value for row in eur_rows if row.v2_value is not None),
                Decimal("0"),
            ),
            absolute_difference_eur=sum(
                (
                    row.absolute_difference
                    for row in eur_rows
                    if row.absolute_difference is not None
                ),
                Decimal("0"),
            ),
            max_absolute_difference=max(
                (row.absolute_difference for row in rows if row.absolute_difference is not None),
                default=Decimal("0"),
            ),
        )

    def issue_scope(self, year: int | None, asset: str | None, status: str) -> str:
        year_part = str(year) if year is not None else "all"
        asset_part = asset.upper() if asset is not None else "all"
        return f"parity:year:{year_part}:asset:{asset_part}:status:{status}"

    def _parse_issue_scope(self, scope: str) -> tuple[int | None, str | None, ParityStatus | None]:
        parts = scope.split(":")
        if (
            len(parts) != 7
            or parts[0] != "parity"
            or parts[1] != "year"
            or parts[3] != "asset"
            or parts[5] != "status"
        ):
            return None, None, None
        year = None if parts[2] == "all" else int(parts[2])
        asset = None if parts[4] == "all" else parts[4].upper()
        status = parts[6] if parts[6] in {"match", "diff", "missing_v2"} else None
        return year, asset, status  # type: ignore[return-value]

    def _hnt_wallet_bridge_rows(self, year: int) -> list[HntWalletBridgeRow]:
        with self.store.connect() as con:
            rows = con.execute(
                f"""
                select
                    source,
                    account,
                    event_type,
                    case when quantity < 0 then 'out' else 'in' end as direction,
                    count(*) as event_count,
                    sum(quantity) as quantity,
                    min(event_time) as first_event_at,
                    max(event_time) as last_event_at
                from canonical_events
                where asset = 'HNT'
                  and {reporting_year_sql('event_time')} = ?
                group by 1, 2, 3, 4
                order by source, account, event_type, direction
                """,
                [year],
            ).fetchall()
        return [
            HntWalletBridgeRow(
                source=row[0],
                account=row[1],
                event_type=row[2],
                direction=row[3],
                event_count=row[4],
                quantity=row[5],
                first_event_at=row[6],
                last_event_at=row[7],
            )
            for row in rows
        ]

    def _hnt_fifo_provenance_events(
        self,
        limit: int,
        *,
        source: str | None = None,
        account: str | None = None,
        from_at: datetime | None = None,
        to_at: datetime | None = None,
    ) -> list[HntFifoProvenanceEvent]:
        clauses = ["e.asset = 'HNT'"]
        params: list[object] = []
        if source:
            clauses.append("lower(e.source) = ?")
            params.append(source.strip().lower())
        if from_at is not None:
            clauses.append("e.event_time >= ?")
            params.append(from_at.replace(tzinfo=None))
        if to_at is not None:
            clauses.append("e.event_time <= ?")
            params.append(to_at.replace(tzinfo=None))
        where_clause = " and ".join(clauses)
        with self.store.connect() as con:
            rows = con.execute(
                f"""
                select
                    e.event_id,
                    e.event_time,
                    e.source,
                    e.event_type,
                    e.quantity,
                    e.account,
                    e.tx_id,
                    e.source_ref,
                    b.filename,
                    r.payload_json
                from canonical_events e
                left join raw_objects r on r.raw_object_id = e.raw_object_id
                left join raw_import_batches b on b.batch_id = r.batch_id
                where {where_clause}
                order by e.event_time, e.event_id
                """,
                params,
            ).fetchall()
        result: list[HntFifoProvenanceEvent] = []
        for row in rows:
            payload = self._parse_raw_payload(row[9])
            event_account = row[5]
            counterparty = self._counterparty_from_payload(payload, event_account)
            event_type = str(row[3])
            quantity = row[4] or Decimal("0")
            fifo_relevant = self._is_hnt_fifo_relevant_event(event_type, quantity)
            if account and not self._hnt_event_matches_account(account, event_account, counterparty):
                continue
            result.append(
                HntFifoProvenanceEvent(
                    event_id=row[0],
                    event_time=row[1],
                    source=row[2],
                    event_type=event_type,
                    direction="out" if quantity < 0 else "in",
                    quantity=quantity,
                    account=event_account,
                    counterparty_account=counterparty,
                    tx_id=row[6],
                    source_ref=row[7],
                    filename=row[8],
                    current_portfolio_account=self._is_hnt_current_portfolio_account(event_account),
                    fifo_relevant=fifo_relevant,
                    note=self._hnt_provenance_note(event_type, quantity, event_account, counterparty, fifo_relevant),
                )
            )
            if len(result) >= limit:
                break
        return result

    def _hnt_fifo_provenance_counts(
        self,
        *,
        source: str | None = None,
        account: str | None = None,
        from_at: datetime | None = None,
        to_at: datetime | None = None,
    ) -> dict[str, int]:
        current_accounts = {account.lower() for account in HNT_CURRENT_PORTFOLIO_ACCOUNTS}
        counterparty_accounts = {account.lower() for account in HNT_TRANSFER_COUNTERPARTY_ACCOUNTS}
        clauses = ["e.asset = 'HNT'"]
        params: list[object] = []
        if source:
            clauses.append("lower(e.source) = ?")
            params.append(source.strip().lower())
        if from_at is not None:
            clauses.append("e.event_time >= ?")
            params.append(from_at.replace(tzinfo=None))
        if to_at is not None:
            clauses.append("e.event_time <= ?")
            params.append(to_at.replace(tzinfo=None))
        where_clause = " and ".join(clauses)
        with self.store.connect() as con:
            rows = con.execute(
                f"""
                select e.event_type, e.quantity, e.account, r.payload_json
                from canonical_events e
                left join raw_objects r on r.raw_object_id = e.raw_object_id
                where {where_clause}
                """,
                params,
            ).fetchall()
            lot_rows = con.execute(
                """
                select lot.acquired_at, e.source, e.account, e.source_ref, e.tx_id
                from tax_lots lot
                left join canonical_events e on e.event_id = lot.source_event_id
                where lot.asset = 'HNT'
                  and lot.quantity_remaining > 0
                """
            ).fetchall()
            disposal_rows = con.execute(
                """
                select l.disposed_at, e.source, e.account, e.source_ref, e.tx_id
                from tax_lines l
                left join canonical_events e on e.event_id = l.source_event_id
                where l.asset = 'HNT'
                """
            ).fetchall()
        current_events = 0
        counterparty_events = 0
        fifo_events = 0
        for event_type, quantity, event_account, payload_json in rows:
            payload = self._parse_raw_payload(payload_json)
            counterparty = self._counterparty_from_payload(payload, event_account)
            if account and not self._hnt_event_matches_account(account, event_account, counterparty):
                continue
            account_key = str(event_account or "").strip().lower()
            counterparty_key = str(counterparty or "").strip().lower()
            amount = quantity or Decimal("0")
            if account_key in current_accounts:
                current_events += 1
            if account_key in counterparty_accounts or counterparty_key in counterparty_accounts:
                counterparty_events += 1
            if self._is_hnt_fifo_relevant_event(str(event_type), amount):
                fifo_events += 1
        return {
            "current_portfolio_events": current_events,
            "transfer_counterparty_events": counterparty_events,
            "fifo_relevant_events": fifo_events,
            "open_lots": sum(1 for row in lot_rows if self._hnt_record_matches_filters(row, source, account, from_at, to_at)),
            "disposals": sum(1 for row in disposal_rows if self._hnt_record_matches_filters(row, source, account, from_at, to_at)),
        }

    def _hnt_open_fifo_lots(
        self,
        *,
        source: str | None = None,
        account: str | None = None,
        from_at: datetime | None = None,
        to_at: datetime | None = None,
    ) -> list[HntFifoProvenanceLot]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    lot.lot_id,
                    lot.acquired_at,
                    lot.quantity_total,
                    lot.quantity_remaining,
                    lot.cost_basis_eur_total,
                    lot.source_event_id,
                    e.source,
                    e.source_ref,
                    e.account,
                    e.tx_id
                from tax_lots lot
                left join canonical_events e on e.event_id = lot.source_event_id
                where lot.asset = 'HNT'
                  and lot.quantity_remaining > 0
                order by lot.acquired_at, lot.lot_id
                limit 250
                """
            ).fetchall()
        result = []
        for row in rows:
            if not self._hnt_record_matches_filters(
                (row[1], row[6], row[8], row[7], row[9]),
                source,
                account,
                from_at,
                to_at,
            ):
                continue
            result.append(HntFifoProvenanceLot(
                lot_id=row[0],
                acquired_at=row[1],
                quantity_total=row[2],
                quantity_remaining=row[3],
                cost_basis_eur_total=row[4],
                source_event_id=row[5],
                source=row[6],
                source_ref=row[7],
                account=row[8],
                tx_id=row[9],
            ))
        return result

    def _hnt_disposal_tax_lines(
        self,
        *,
        source: str | None = None,
        account: str | None = None,
        from_at: datetime | None = None,
        to_at: datetime | None = None,
    ) -> list[HntFifoProvenanceTaxLine]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    l.tax_line_id,
                    l.lot_id,
                    lot.acquired_at,
                    l.disposed_at,
                    l.quantity,
                    l.acquisition_cost_eur,
                    l.disposal_proceeds_eur,
                    l.gain_loss_eur,
                    l.holding_days,
                    l.source_event_id,
                    e.source,
                    e.account,
                    e.source_ref,
                    e.tx_id
                from tax_lines l
                join tax_lots lot on lot.lot_id = l.lot_id
                left join canonical_events e on e.event_id = l.source_event_id
                where l.asset = 'HNT'
                order by l.disposed_at desc, l.tax_line_id
                limit 250
                """
            ).fetchall()
        result = []
        for row in rows:
            if not self._hnt_record_matches_filters(
                (row[3], row[10], row[11], row[12], row[13]),
                source,
                account,
                from_at,
                to_at,
            ):
                continue
            result.append(HntFifoProvenanceTaxLine(
                tax_line_id=row[0],
                lot_id=row[1],
                acquired_at=row[2],
                disposed_at=row[3],
                quantity=row[4],
                acquisition_cost_eur=row[5],
                disposal_proceeds_eur=row[6],
                gain_loss_eur=row[7],
                holding_days=row[8],
                source_event_id=row[9],
                disposal_source=row[10],
                disposal_account=row[11],
                source_ref=row[12],
                tx_id=row[13],
            ))
        return result

    def _hnt_fifo_timeline(
        self,
        events: list[HntFifoProvenanceEvent],
    ) -> list[HntFifoProvenanceTimelineStep]:
        buckets = [
            (
                "Helium Legacy",
                "legacy_source",
                lambda event: self._is_hnt_transfer_counterparty_account(event.account)
                and str(event.account or "").lower() not in {"binance", "helium"},
                "Historische Helium-/Fairspot-Kontexte. Belegkette, kein aktueller Portfolio-Ort.",
            ),
            (
                "Binance Bridge/CEX",
                "cex_bridge",
                lambda event: str(event.source).lower() == "binance"
                or str(event.account or "").lower() in {"binance", "binance spot"},
                "CEX-Bruecke und Handelsort; Live-Bestand wird separat ueber Binance API abgeglichen.",
            ),
            (
                "Solana/Jup Wallets",
                "current_wallet",
                lambda event: event.current_portfolio_account,
                "Aktuelle Nutzer-Wallets; voller Account bleibt im JSON sichtbar.",
            ),
            (
                "Sonstige HNT-Kontexte",
                "other",
                lambda event: True,
                "Weitere HNT-Ereignisse fuer Audit und FIFO-Kontext.",
            ),
        ]
        assigned: set[str] = set()
        steps: list[HntFifoProvenanceTimelineStep] = []
        for label, role, predicate, note in buckets:
            selected = [
                event
                for event in events
                if event.event_id not in assigned and predicate(event)
            ]
            if not selected:
                continue
            assigned.update(event.event_id for event in selected)
            quantity_in = sum((event.quantity for event in selected if event.quantity > 0), Decimal("0"))
            quantity_out = abs(sum((event.quantity for event in selected if event.quantity < 0), Decimal("0")))
            steps.append(
                HntFifoProvenanceTimelineStep(
                    label=label,
                    role=role,
                    account=None,
                    event_count=len(selected),
                    quantity_in=quantity_in,
                    quantity_out=quantity_out,
                    net_quantity=quantity_in - quantity_out,
                    first_event_at=min(event.event_time for event in selected),
                    last_event_at=max(event.event_time for event in selected),
                    note=note,
                )
            )
        return steps

    def _parse_raw_payload(self, payload_json: str | None) -> dict[str, object]:
        if not payload_json:
            return {}
        try:
            raw = json.loads(payload_json)
        except json.JSONDecodeError:
            return {"raw": payload_json}
        return raw if isinstance(raw, dict) else {"raw": raw}

    def _counterparty_from_payload(
        self,
        payload: dict[str, object],
        account: str | None,
    ) -> str | None:
        payer = self._payload_value(payload, "payer", "from", "from_address", "sender")
        payee = self._payload_value(payload, "payee", "to", "to_address", "receiver", "recipient")
        if account is None:
            return payee or payer
        if payer and payer != account:
            return payer
        if payee and payee != account:
            return payee
        return None

    def _payload_value(self, payload: dict[str, object], *keys: str) -> str | None:
        lowered = {str(key).lower(): value for key, value in payload.items()}
        for key in keys:
            value = lowered.get(key.lower())
            if value is not None and str(value).strip():
                return str(value).strip()
        return None

    def _hnt_event_matches_account(
        self,
        wanted_account: str,
        event_account: str | None,
        counterparty_account: str | None,
    ) -> bool:
        needle = wanted_account.strip().lower()
        return needle in {
            str(event_account or "").strip().lower(),
            str(counterparty_account or "").strip().lower(),
        }

    def _hnt_record_matches_filters(
        self,
        row: tuple[object, object, object, object, object],
        source: str | None,
        account: str | None,
        from_at: datetime | None,
        to_at: datetime | None,
    ) -> bool:
        event_time, event_source, event_account, source_ref, tx_id = row
        if source and str(event_source or "").strip().lower() != source.strip().lower():
            return False
        if account:
            needle = account.strip().lower()
            if needle not in {
                str(event_account or "").strip().lower(),
                str(source_ref or "").strip().lower(),
                str(tx_id or "").strip().lower(),
            }:
                return False
        if from_at is not None and event_time is not None and event_time < from_at.replace(tzinfo=None):
            return False
        if to_at is not None and event_time is not None and event_time > to_at.replace(tzinfo=None):
            return False
        return True

    def _is_hnt_current_portfolio_account(self, account: str | None) -> bool:
        return bool(account and account in HNT_CURRENT_PORTFOLIO_ACCOUNTS)

    def _is_hnt_transfer_counterparty_account(self, account: str | None) -> bool:
        return bool(account and account.strip().lower() in {item.lower() for item in HNT_TRANSFER_COUNTERPARTY_ACCOUNTS})

    def _is_hnt_fifo_relevant_event(self, event_type: str, quantity: Decimal) -> bool:
        if event_type in {"mining", "reward", "income", "staking"} and quantity > 0:
            return True
        return event_type == "trade"

    def _hnt_provenance_note(
        self,
        event_type: str,
        quantity: Decimal,
        account: str | None,
        counterparty: str | None,
        fifo_relevant: bool,
    ) -> str:
        if self._is_hnt_current_portfolio_account(account):
            return "Aktuelle Nutzer-Wallet; fuer Portfolio und Live-Abgleich relevant."
        if self._is_hnt_transfer_counterparty_account(account) or self._is_hnt_transfer_counterparty_account(counterparty):
            return "Transfer-/Bridge-Gegenpartei; fuer Belegkette sichtbar, aber kein aktueller Portfolio-Ort."
        if fifo_relevant:
            return "FIFO-relevantes Erwerbs- oder Veraeusserungsereignis."
        if event_type == "transfer":
            return "Transferereignis; dient der Nachverfolgung, erzeugt allein keinen FIFO-Lot."
        return "HNT-Ereignis fuer Audit- und Herkunftskontext."

    def _v1_quantity_disposed(self, year: int, asset: str) -> Decimal | None:
        values = [
            reference.value
            for reference in self.store.list_v1_reference_metrics()
            if reference.scope == "tax"
            and reference.metric == "quantity_disposed"
            and reference.year == year
            and reference.asset == asset.upper()
        ]
        if not values:
            return None
        return sum(values, Decimal("0"))

    def _v2_quantity_disposed(self, year: int, asset: str) -> Decimal:
        return sum(
            (
                line.quantity
                for line in TaxService(self.store).list_tax_lines()
                if line.asset == asset.upper() and reporting_tax_year(line.disposed_at) == year
            ),
            Decimal("0"),
        )

    def _tax_source_summaries(self, year: int, asset: str) -> list[V1ParityTaxSourceSummary]:
        canonical_asset = self._canonical_asset(asset)
        with self.store.connect() as con:
            rows = con.execute(
                f"""
                select
                    e.source,
                    e.account,
                    b.filename,
                    count(*) as tax_lines,
                    count(distinct e.event_id) as event_count,
                    sum(l.quantity) as quantity,
                    sum(l.disposal_proceeds_eur) as disposal_proceeds_eur,
                    sum(l.acquisition_cost_eur) as acquisition_cost_eur,
                    sum(l.gain_loss_eur) as gain_loss_eur,
                    min(l.disposed_at) as first_disposed_at,
                    max(l.disposed_at) as last_disposed_at
                from tax_lines l
                join canonical_events e on e.event_id = l.source_event_id
                left join raw_objects r on r.raw_object_id = e.raw_object_id
                left join raw_import_batches b on b.batch_id = r.batch_id
                where l.asset = ?
                  and {reporting_year_sql('l.disposed_at')} = ?
                group by 1, 2, 3
                order by quantity desc
                limit 50
                """,
                [canonical_asset, year],
            ).fetchall()
        return [
            V1ParityTaxSourceSummary(
                source=row[0],
                account=row[1],
                filename=row[2],
                tax_lines=row[3],
                event_count=row[4],
                quantity=row[5],
                disposal_proceeds_eur=row[6],
                acquisition_cost_eur=row[7],
                gain_loss_eur=row[8],
                first_disposed_at=row[9],
                last_disposed_at=row[10],
            )
            for row in rows
        ]

    def _tax_event_samples(self, year: int, asset: str) -> list[V1ParityTaxEventSample]:
        canonical_asset = self._canonical_asset(asset)
        with self.store.connect() as con:
            rows = con.execute(
                f"""
                select
                    e.event_time,
                    e.source,
                    e.account,
                    e.source_ref,
                    b.filename,
                    e.raw_object_id,
                    e.quantity,
                    e.quote_asset,
                    e.quote_quantity,
                    sum(l.disposal_proceeds_eur) as disposal_proceeds_eur,
                    sum(l.acquisition_cost_eur) as acquisition_cost_eur,
                    sum(l.gain_loss_eur) as gain_loss_eur,
                    r.payload_json
                from tax_lines l
                join canonical_events e on e.event_id = l.source_event_id
                left join raw_objects r on r.raw_object_id = e.raw_object_id
                left join raw_import_batches b on b.batch_id = r.batch_id
                where l.asset = ?
                  and {reporting_year_sql('l.disposed_at')} = ?
                group by
                    e.event_time, e.source, e.account, e.source_ref, b.filename,
                    e.raw_object_id, e.quantity, e.quote_asset, e.quote_quantity,
                    r.payload_json
                order by abs(e.quantity) desc, e.event_time
                limit 25
                """,
                [canonical_asset, year],
            ).fetchall()
        result: list[V1ParityTaxEventSample] = []
        for row in rows:
            payload: dict[str, object] = {}
            if row[12]:
                try:
                    raw = json.loads(row[12])
                    if isinstance(raw, dict):
                        payload = raw
                except json.JSONDecodeError:
                    payload = {"raw": row[12]}
            result.append(
                V1ParityTaxEventSample(
                    event_time=row[0],
                    source=row[1],
                    account=row[2],
                    source_ref=row[3],
                    filename=row[4],
                    raw_object_id=row[5],
                    quantity=row[6],
                    quote_asset=row[7],
                    quote_quantity=row[8],
                    disposal_proceeds_eur=row[9],
                    acquisition_cost_eur=row[10],
                    gain_loss_eur=row[11],
                    payload=payload,
                )
            )
        return result

    def _parity_decisions_by_scope(self) -> dict[str, tuple[ParityDecisionStatus, str, str]]:
        result: dict[str, tuple[ParityDecisionStatus, str, str]] = {}
        for decision in reversed(self.store.list_review_decisions()):
            if decision.decision_type != "parity_finding":
                continue
            raw_status = decision.payload.get("decision_status")
            if not isinstance(raw_status, str):
                continue
            if raw_status not in {
                "v1_known_wrong",
                "v2_missing_data",
                "v2_corrected",
                "needs_manual_evidence",
                "accepted_difference",
            }:
                continue
            result[decision.scope] = (
                raw_status,  # type: ignore[assignment]
                decision.decision_id,
                decision.title,
            )
        return result

    def _v2_metrics(self) -> dict[MetricKey, Decimal]:
        metrics: defaultdict[MetricKey, Decimal] = defaultdict(lambda: Decimal("0"))
        reference_scopes = {
            reference.scope.strip().lower()
            for reference in self.store.list_v1_reference_metrics()
        }
        if "portfolio" in reference_scopes:
            self._add_portfolio_metrics(metrics)
        if "tax" in reference_scopes:
            self._add_tax_metrics(metrics)
        if "flow" in reference_scopes:
            self._add_flow_metrics(metrics)
        return dict(metrics)

    def _add_portfolio_metrics(self, metrics: defaultdict[MetricKey, Decimal]) -> None:
        snapshot = PortfolioService(self.store).snapshot()
        metrics[self._key("portfolio", "total_value_eur", "EUR", None, None, None)] += (
            snapshot.total_value_eur
        )
        for position in snapshot.positions:
            metrics[
                self._key(
                    "portfolio",
                    "quantity",
                    position.asset,
                    None,
                    position.asset,
                    position.account,
                )
            ] += position.quantity
            if position.value_eur is not None:
                metrics[
                    self._key(
                        "portfolio",
                        "value_eur",
                        "EUR",
                        None,
                        position.asset,
                        position.account,
                    )
                ] += position.value_eur

    def _add_tax_metrics(self, metrics: defaultdict[MetricKey, Decimal]) -> None:
        with self.store.connect() as con:
            rows = con.execute(
                f"""
                select
                    {reporting_year_sql('disposed_at')} as tax_year,
                    asset,
                    coalesce(sum(quantity), 0) as quantity_disposed,
                    coalesce(sum(acquisition_cost_eur), 0) as acquisition_cost_eur,
                    coalesce(sum(disposal_proceeds_eur), 0) as disposal_proceeds_eur,
                    coalesce(sum(gain_loss_eur), 0) as gain_loss_eur
                from tax_lines
                group by 1, 2
                """
            ).fetchall()
        for row in rows:
            year = row[0]
            asset = row[1]
            canonical_asset = self._canonical_asset(asset)
            metrics[self._key("tax", "quantity_disposed", canonical_asset, year, canonical_asset, None)] += row[2]
            metrics[self._key("tax", "acquisition_cost_eur", "EUR", year, canonical_asset, None)] += (
                row[3]
            )
            metrics[self._key("tax", "disposal_proceeds_eur", "EUR", year, canonical_asset, None)] += (
                row[4]
            )
            metrics[self._key("tax", "gain_loss_eur", "EUR", year, canonical_asset, None)] += (
                row[5]
            )

    def _add_flow_metrics(self, metrics: defaultdict[MetricKey, Decimal]) -> None:
        FlowService(self.store).rebuild()
        for edge in FlowService(self.store).summary().edges:
            source = f"{edge.source_node}->{edge.target_node}"
            metrics[
                self._key("flow", "net_value_eur", "EUR", None, None, source)
            ] += edge.value_eur
        for year in FlowService(self.store).summary().available_years:
            for edge in FlowService(self.store).summary(year=year).edges:
                source = f"{edge.source_node}->{edge.target_node}"
                metrics[
                    self._key("flow", "net_value_eur", "EUR", year, None, source)
                ] += edge.value_eur

    def _key(
        self,
        scope: str,
        metric: str,
        unit: str,
        year: int | None,
        asset: str | None,
        source: str | None,
    ) -> MetricKey:
        return (
            scope.strip().lower(),
            metric.strip().lower(),
            self._canonical_unit(unit),
            year,
            self._canonical_asset(asset) if asset else None,
            source.strip() if source else None,
        )

    def _canonical_asset(self, value: str | None) -> str | None:
        if value is None:
            return None
        upper = value.strip().upper()
        if upper == "HNT2":
            return "HNT"
        if upper == "BTTOLD":
            return "BTTC"
        return self._asset_aliases.get(upper, upper)

    def _canonical_unit(self, value: str) -> str:
        upper = value.strip().upper()
        if upper == "EUR":
            return "EUR"
        return self._canonical_asset(upper) or upper

    def _load_asset_aliases(self, config_path: Path) -> dict[str, str]:
        if not config_path.exists():
            return {}
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        result: dict[str, str] = {}
        for item in payload.get("assets", []):
            symbol = str(item.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            for value in [symbol, *item.get("aliases", []), *item.get("store_keys", [])]:
                alias = str(value or "").strip().upper()
                if alias:
                    result[alias] = symbol
        return result
