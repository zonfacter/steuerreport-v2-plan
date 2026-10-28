from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, localcontext
from collections import defaultdict
from types import SimpleNamespace

from steuerreport_v2.contracts.events import CanonicalEvent

from steuerreport_v2.contracts.business_inventory import (
    BusinessRewardInventoryReviewReport,
    BusinessRewardInventoryReviewRow,
    BusinessRewardOriginStatus,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_time import reporting_tax_year
from steuerreport_v2.domain.lot_origin import POLICY_ID, LotOriginIndex, LotOriginTrace


class BusinessRewardInventoryReviewService:
    DEFAULT_ASSETS = ("HNT", "IOT", "MOBILE")
    ONCHAIN_REWARD_SOURCES = {
        "alchemy",
        "helium",
        "solana_rpc",
        "solscan",
    }
    UNRESOLVED_STATUSES = {
        "origin_classification_review",
        "separate_income_review",
        "missing_origin",
    }

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def review(
        self,
        *,
        assets: tuple[str, ...] = DEFAULT_ASSETS,
    ) -> BusinessRewardInventoryReviewReport:
        asset_keys = tuple(sorted({asset.strip().upper() for asset in assets if asset.strip()}))
        if not asset_keys:
            return self._empty_report(asset_keys)

        with self.store.connect() as con:
            def records(table: str, order: str) -> list[SimpleNamespace]:
                cursor = con.execute(f"select * from {table} order by {order}")
                columns = [column[0] for column in cursor.description]
                return [SimpleNamespace(**dict(zip(columns, row))) for row in cursor.fetchall()]

            lots = records("tax_lots", "lot_id")
            lines = records("tax_lines", "tax_line_id")
        events = self.store.list_canonical_events()
        origin_index = LotOriginIndex(lots, events)
        events_by_id = {event.event_id: event for event in events}
        groups = defaultdict(list)
        for line in lines:
            trace = origin_index.resolve(line)
            if line.asset.upper() not in asset_keys and trace.origin_asset not in asset_keys:
                continue
            origin = events_by_id.get(trace.origin_event_id)
            source = self._optional_text(origin.source.lower()) if origin else None
            event_type = self._optional_text(origin.event_type.lower()) if origin else None
            account = self._optional_text(origin.account or origin.wallet) if origin else None
            key = (reporting_tax_year(line.disposed_at), line.asset.upper(), source,
                   event_type, account, trace.status, trace.reason)
            groups[key].append((line, trace, origin))

        with localcontext() as context:
            context.prec = 80
            rows = [self._row(records) for _, records in sorted(
                groups.items(), key=lambda item: tuple("" if value is None else value for value in item[0]))]
        potential_rows = [
            row for row in rows if row.classification == "potential_business_inventory"
        ]
        unresolved_rows = [row for row in rows if row.classification in self.UNRESOLVED_STATUSES]
        blocked_rows = [row for row in rows if row.blocks_private_fifo_classification]
        affected_years = sorted({row.disposal_year for row in blocked_rows})
        strict_ready = not blocked_rows

        findings: list[str] = []
        if potential_rows:
            findings.append(
                f"{sum(row.tax_lines_count for row in potential_rows)} Veraeusserungszeilen "
                "verwenden Lots aus HNT/IOT/MOBILE-Mining oder On-Chain-Rewards. Ohne "
                "dokumentierte Entnahme duerfen sie nicht automatisch als private "
                "Veraeusserungen behandelt werden."
            )
        if unresolved_rows:
            findings.append(
                f"{sum(row.tax_lines_count for row in unresolved_rows)} Veraeusserungszeilen "
                "haben einen noch nicht eindeutig als Reward, Transferfortfuehrung oder "
                "separate Einkunftsart klassifizierten Ursprung."
            )
        if strict_ready:
            findings.append(
                "Keine HNT/IOT/MOBILE-Verauesserungszeile mit offenem Reward- oder "
                "Ursprungssphaeren-Konflikt gefunden."
            )

        return BusinessRewardInventoryReviewReport(
            origin_trace_policy=POLICY_ID,
            generated_at=datetime.now(timezone.utc).isoformat(),
            assets=list(asset_keys),
            affected_years=affected_years,
            strict_ready=strict_ready,
            total_tax_lines_count=sum(row.tax_lines_count for row in rows),
            potential_business_tax_lines_count=sum(
                row.tax_lines_count for row in potential_rows
            ),
            unresolved_tax_lines_count=sum(row.tax_lines_count for row in unresolved_rows),
            potential_business_acquisition_cost_eur=self._sum_amount(potential_rows, "acquisition_cost_eur"),
            potential_business_proceeds_eur=self._sum_amount(potential_rows, "disposal_proceeds_eur"),
            potential_business_gain_loss_eur=self._sum_amount(potential_rows, "gain_loss_eur"),
            rows=rows,
            findings=findings,
            next_actions=(
                [
                    "Reward-Ursprungsereignisse mit Primaerbelegen als betrieblicher oder privater Zugang klassifizieren.",
                    "Dokumentierte Entnahmen mit Zeitpunkt und Teilwert erfassen, bevor eine private Haltefrist beginnt.",
                    "Erst danach betroffene Zeilen in einem versionierten Parallel-Lauf neu berechnen und fachlich freigeben.",
                ]
                if blocked_rows
                else []
            ),
            methodology=(
                "Read-only Ursprungslot-Audit mit explizitem Assetfilter auf Verkauf oder bestaetigten Ursprung. "
                "Jede Tax-Line wird ueber eindeutige Lot-/Event-IDs und origin_lot_id bis zum "
                "Ursprung verfolgt. Fehlende oder widerspruechliche Ketten bleiben im Review. Mining- "
                "und als On-Chain-Rewards erfasste Urspruenge werden konservativ als potenzielles "
                "Betriebsvermoegen markiert. Income-, Transfer-, CEX-Staking- und fehlende "
                "Urspruenge bleiben im Review. Der Audit aendert weder Events noch Lots, "
                "Tax-Lines, Preise oder Erklaerungswerte. Eine ID-Kette belegt weder die Echtheit "
                "der Quelle noch die Angemessenheit einer positiven Kostenbasis."
            ),
        )

    def _row(self, records: list[tuple[SimpleNamespace, LotOriginTrace, CanonicalEvent | None]]) -> BusinessRewardInventoryReviewRow:
        line, trace, origin = min(records, key=lambda item: (
            item[2].event_id if item[2] else "", item[0].tax_line_id))
        source = self._optional_text(origin.source.lower()) if origin else None
        event_type = self._optional_text(origin.event_type.lower()) if origin else None
        classification, reason = self.classify_origin(source, event_type)
        blocks = classification != "non_reward_origin"
        return BusinessRewardInventoryReviewRow(
            disposal_year=reporting_tax_year(line.disposed_at),
            asset=line.asset.upper(),
            origin_source=source,
            origin_event_type=event_type,
            origin_account=self._optional_text(origin.account or origin.wallet) if origin else None,
            origin_events_count=len({item[2].event_id for item in records if item[2] is not None}),
            tax_lines_count=len(records),
            quantity_disposed=sum((item[0].quantity for item in records), Decimal("0")),
            acquisition_cost_eur=sum((item[0].acquisition_cost_eur for item in records), Decimal("0")),
            disposal_proceeds_eur=sum((item[0].disposal_proceeds_eur for item in records), Decimal("0")),
            gain_loss_eur=sum((item[0].gain_loss_eur for item in records), Decimal("0")),
            first_disposal_at=self._iso(min(item[0].disposed_at for item in records)),
            last_disposal_at=self._iso(max(item[0].disposed_at for item in records)),
            sample_origin_event_id=origin.event_id if origin else None,
            sample_disposal_event_id=line.source_event_id,
            lineage_status=trace.status,
            lineage_reason=trace.reason,
            sample_lot_path=list(trace.lot_ids),
            sample_direct_event_id=trace.direct_event_id,
            classification=classification,
            blocks_private_fifo_classification=blocks,
            reason=reason,
        )

    @staticmethod
    def classify_origin(
        source: str | None,
        event_type: str | None,
    ) -> tuple[BusinessRewardOriginStatus, str]:
        if source is None or event_type is None:
            return (
                "missing_origin",
                "Das Anschaffungslot ist nicht vollstaendig mit einem Canonical Event verknuepft.",
            )
        if event_type == "mining" or (
            event_type == "reward"
            and source in BusinessRewardInventoryReviewService.ONCHAIN_REWARD_SOURCES
        ):
            return (
                "potential_business_inventory",
                "Mining-/Netzwerk-Reward-Ursprung: betriebliche Zugehoerigkeit bis zu einer belegten Entnahme pruefen.",
            )
        if event_type in {"staking", "reward"}:
            return (
                "separate_income_review",
                "Staking-/CEX-Reward ist separat einzuordnen und nicht automatisch Helium-Betriebsvermoegen.",
            )
        if event_type in {"income", "transfer"}:
            return (
                "origin_classification_review",
                "Income oder Transfer kann Reward, Migration, Airdrop oder FIFO-Fortfuehrung sein; Primaerbeleg fehlt in dieser Ableitung.",
            )
        if event_type == "trade":
            return (
                "non_reward_origin",
                "Der direkte Ursprung ist ein Handel; keine automatische steuerliche Sphaerenfreigabe.",
            )
        return (
            "origin_classification_review",
            "Der Ursprungstyp ist nicht als Anschaffung klassifiziert; keine automatische Privatzuordnung.",
        )

    def _empty_report(
        self,
        assets: tuple[str, ...],
    ) -> BusinessRewardInventoryReviewReport:
        return BusinessRewardInventoryReviewReport(
            origin_trace_policy=POLICY_ID,
            generated_at=datetime.now(timezone.utc).isoformat(),
            assets=list(assets),
            strict_ready=True,
            findings=["Keine Assets fuer den Ursprungslot-Audit ausgewaehlt."],
            methodology="Read-only Ursprungslot-Audit; keine Auswahl, keine Datenveraenderung.",
        )

    @staticmethod
    def _sum_amount(rows: list[BusinessRewardInventoryReviewRow], field: str) -> Decimal:
        with localcontext() as context:
            context.prec = 80
            return sum((getattr(row, field) for row in rows), Decimal("0"))

    @staticmethod
    def _optional_text(value: object) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _iso(value: object) -> str | None:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).isoformat()
        return None
