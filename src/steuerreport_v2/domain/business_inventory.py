from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from steuerreport_v2.contracts.business_inventory import (
    BusinessRewardInventoryReviewReport,
    BusinessRewardInventoryReviewRow,
    BusinessRewardOriginStatus,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_time import reporting_year_sql


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

        placeholders = ", ".join("?" for _ in asset_keys)
        disposal_year = reporting_year_sql("line.disposed_at")
        with self.store.connect() as con:
            records = con.execute(
                f"""
                select
                    {disposal_year} as disposal_year,
                    upper(line.asset) as asset,
                    nullif(lower(trim(origin.source)), '') as origin_source,
                    nullif(lower(trim(origin.event_type)), '') as origin_event_type,
                    nullif(trim(coalesce(origin.account, origin.wallet)), '') as origin_account,
                    count(distinct origin.event_id)::integer as origin_events_count,
                    count(*)::integer as tax_lines_count,
                    coalesce(sum(line.quantity), 0) as quantity_disposed,
                    coalesce(sum(line.acquisition_cost_eur), 0) as acquisition_cost_eur,
                    coalesce(sum(line.disposal_proceeds_eur), 0) as disposal_proceeds_eur,
                    coalesce(sum(line.gain_loss_eur), 0) as gain_loss_eur,
                    min(line.disposed_at) as first_disposal_at,
                    max(line.disposed_at) as last_disposal_at,
                    min(origin.event_id) as sample_origin_event_id,
                    min(line.source_event_id) as sample_disposal_event_id
                from tax_lines line
                left join tax_lots lot on lot.lot_id = line.lot_id
                left join canonical_events origin
                  on origin.event_id = coalesce(
                    nullif(line.acquisition_source_event_id, ''),
                    lot.source_event_id
                  )
                where upper(line.asset) in ({placeholders})
                group by
                    disposal_year,
                    upper(line.asset),
                    origin_source,
                    origin_event_type,
                    origin_account
                order by disposal_year, asset, origin_source, origin_event_type, origin_account
                """,
                list(asset_keys),
            ).fetchall()

        rows = [self._row(record) for record in records]
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
            generated_at=datetime.now(timezone.utc).isoformat(),
            assets=list(asset_keys),
            affected_years=affected_years,
            strict_ready=strict_ready,
            total_tax_lines_count=sum(row.tax_lines_count for row in rows),
            potential_business_tax_lines_count=sum(
                row.tax_lines_count for row in potential_rows
            ),
            unresolved_tax_lines_count=sum(row.tax_lines_count for row in unresolved_rows),
            potential_business_acquisition_cost_eur=sum(
                (row.acquisition_cost_eur for row in potential_rows), Decimal("0")
            ),
            potential_business_proceeds_eur=sum(
                (row.disposal_proceeds_eur for row in potential_rows), Decimal("0")
            ),
            potential_business_gain_loss_eur=sum(
                (row.gain_loss_eur for row in potential_rows), Decimal("0")
            ),
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
                "Read-only Ursprungslot-Audit fuer HNT, IOT und MOBILE. Jede bestehende "
                "Tax-Line wird ueber tax_lots.source_event_id beziehungsweise den expliziten "
                "acquisition_source_event_id mit dem Anschaffungsereignis verbunden. Mining- "
                "und belegte On-Chain-Reward-Urspruenge werden konservativ als potenzielles "
                "Betriebsvermoegen markiert. Income-, Transfer-, CEX-Staking- und fehlende "
                "Urspruenge bleiben im Review. Der Audit aendert weder Events noch Lots, "
                "Tax-Lines, Preise oder Erklaerungswerte."
            ),
        )

    def _row(self, record: tuple[object, ...]) -> BusinessRewardInventoryReviewRow:
        source = self._optional_text(record[2])
        event_type = self._optional_text(record[3])
        classification, reason = self.classify_origin(source, event_type)
        blocks = classification != "non_reward_origin"
        return BusinessRewardInventoryReviewRow(
            disposal_year=int(record[0]),
            asset=str(record[1]),
            origin_source=source,
            origin_event_type=event_type,
            origin_account=self._optional_text(record[4]),
            origin_events_count=int(record[5] or 0),
            tax_lines_count=int(record[6] or 0),
            quantity_disposed=Decimal(str(record[7] or "0")),
            acquisition_cost_eur=Decimal(str(record[8] or "0")),
            disposal_proceeds_eur=Decimal(str(record[9] or "0")),
            gain_loss_eur=Decimal(str(record[10] or "0")),
            first_disposal_at=self._iso(record[11]),
            last_disposal_at=self._iso(record[12]),
            sample_origin_event_id=self._optional_text(record[13]),
            sample_disposal_event_id=self._optional_text(record[14]),
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
        return (
            "non_reward_origin",
            "Der direkte Ursprung ist kein Reward-/Mining-/Staking-Ereignis.",
        )

    def _empty_report(
        self,
        assets: tuple[str, ...],
    ) -> BusinessRewardInventoryReviewReport:
        return BusinessRewardInventoryReviewReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            assets=list(assets),
            strict_ready=True,
            findings=["Keine Assets fuer den Ursprungslot-Audit ausgewaehlt."],
            methodology="Read-only Ursprungslot-Audit; keine Auswahl, keine Datenveraenderung.",
        )

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
