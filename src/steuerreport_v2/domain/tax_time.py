from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
from zoneinfo import ZoneInfo

from steuerreport_v2.contracts.tax_methodology import (
    TaxTimeBoundaryEvent,
    TaxTimePrecisionAudit,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore


UTC = timezone.utc
REPORTING_TIMEZONE_NAME = "Europe/Berlin"
REPORTING_TIMEZONE = ZoneInfo(REPORTING_TIMEZONE_NAME)
POLICY_VERSION = "de_calendar_year_v1"
REPORTING_POLICY_APPLIED = True


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def reporting_time(value: datetime) -> datetime:
    return as_utc(value).astimezone(REPORTING_TIMEZONE)


def reporting_tax_year(value: datetime) -> int:
    return reporting_time(value).year


def reporting_year_utc_bounds(year: int) -> tuple[datetime, datetime]:
    start = datetime(year, 1, 1, tzinfo=REPORTING_TIMEZONE).astimezone(UTC)
    end = datetime(year + 1, 1, 1, tzinfo=REPORTING_TIMEZONE).astimezone(UTC)
    return start, end


def reporting_year_sql(column: str) -> str:
    return (
        "date_part('year', timezone('Europe/Berlin', "
        f"timezone('UTC', {column})))::integer"
    )


def event_reporting_year_sql(event_alias: str, raw_alias: str) -> str:
    local_year = reporting_year_sql(f"{event_alias}.event_time")
    return (
        "case "
        f"when lower({event_alias}.source) = 'helium' "
        f"and lower({event_alias}.event_type) = 'mining' "
        f"and json_extract_string({raw_alias}.payload_json, '$.\"Period Start (UTC)\"') is not null "
        f"then date_part('year', {event_alias}.event_time)::integer "
        f"else {local_year} end"
    )


def source_period_year(payload: dict[str, object]) -> int | None:
    value = str(payload.get("Period Start (UTC)") or "").strip()
    if not value:
        return None
    for pattern in ("%d.%m.%y", "%d.%m.%Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime(value, pattern).year
        except ValueError:
            continue
    return None


def event_reporting_tax_year(
    event_time: datetime,
    *,
    source: str,
    event_type: str,
    payload: dict[str, object] | None = None,
) -> int:
    raw = payload or {}
    period_year = source_period_year(raw)
    if source.lower() == "helium" and event_type.lower() == "mining" and period_year is not None:
        return period_year
    return reporting_tax_year(event_time)


def source_period_event_years(store: DuckDbStore) -> dict[str, int]:
    with store.connect() as con:
        rows = con.execute(
            """
            select event.event_id, date_part('year', event.event_time)::integer
            from canonical_events event
            join raw_objects raw on raw.raw_object_id = event.raw_object_id
            where lower(event.source) = 'helium'
              and lower(event.event_type) = 'mining'
              and json_extract_string(
                  raw.payload_json,
                  '$."Period Start (UTC)"'
              ) is not null
            """
        ).fetchall()
    return {str(event_id): int(year) for event_id, year in rows}


class TaxTimePolicyService:
    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def audit(self, *, limit: int = 200) -> TaxTimePrecisionAudit:
        generated_at = datetime.now(UTC)
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    event.event_id,
                    event.event_time,
                    event.source,
                    event.event_type,
                    event.asset,
                    event.quantity,
                    event.tx_id,
                    event.source_ref,
                    event.raw_object_id,
                    batch.filename,
                    raw.payload_json
                from canonical_events event
                left join raw_objects raw on raw.raw_object_id = event.raw_object_id
                left join raw_import_batches batch on batch.batch_id = raw.batch_id
                where year(event.event_time) != year(
                    timezone('Europe/Berlin', timezone('UTC', event.event_time))
                )
                order by event.event_time, event.event_id
                """
            ).fetchall()
            tax_line_rows = con.execute(
                """
                select source_event_id, count(*), coalesce(sum(gain_loss_eur), 0)
                from tax_lines
                where year(disposed_at) != year(
                    timezone('Europe/Berlin', timezone('UTC', disposed_at))
                )
                group by source_event_id
                """
            ).fetchall()
            income_rows = con.execute(
                """
                select lot.source_event_id, coalesce(sum(lot.cost_basis_eur_total), 0)
                from tax_lots lot
                join canonical_events event on event.event_id = lot.source_event_id
                where event.event_type in ('income', 'reward', 'staking', 'mining')
                group by lot.source_event_id
                """
            ).fetchall()
        tax_line_impact = {
            str(event_id): (int(count), Decimal(str(gain or "0")))
            for event_id, count, gain in tax_line_rows
        }
        income_impact = {
            str(event_id): Decimal(str(value or "0"))
            for event_id, value in income_rows
        }

        events: list[TaxTimeBoundaryEvent] = []
        for row in rows:
            payload = self._payload(row[10])
            period_year = source_period_year(payload)
            local_time = reporting_time(row[1])
            preserve_period = (
                str(row[2]).lower() == "helium"
                and str(row[3]).lower() == "mining"
                and period_year is not None
            )
            reporting_year = period_year if preserve_period else local_time.year
            line_count, line_gain = tax_line_impact.get(str(row[0]), (0, Decimal("0")))
            events.append(
                TaxTimeBoundaryEvent(
                    event_id=str(row[0]),
                    event_time_utc=as_utc(row[1]),
                    event_time_europe_berlin=local_time,
                    utc_year=row[1].year,
                    reporting_year=reporting_year,
                    classification=(
                        "source_period_aggregate_preserved"
                        if preserve_period
                        else "local_calendar_shift_required"
                    ),
                    source_period_year=period_year,
                    source=str(row[2]),
                    event_type=str(row[3]),
                    asset=str(row[4]),
                    quantity=Decimal(str(row[5])),
                    tx_id=str(row[6]) if row[6] is not None else None,
                    source_ref=str(row[7]) if row[7] is not None else None,
                    raw_object_id=str(row[8]) if row[8] is not None else None,
                    raw_filename=str(row[9]) if row[9] is not None else None,
                    tax_lines_count=line_count,
                    tax_lines_gain_loss_eur=line_gain,
                    income_cost_basis_eur=income_impact.get(str(row[0]), Decimal("0")),
                )
            )

        shifts = [
            event
            for event in events
            if event.classification == "local_calendar_shift_required"
        ]
        period_aggregates = [
            event
            for event in events
            if event.classification == "source_period_aggregate_preserved"
        ]
        tax_line_count = sum(event.tax_lines_count for event in shifts)
        tax_gain = sum((event.tax_lines_gain_loss_eur for event in shifts), Decimal("0"))
        income_events = [event for event in shifts if event.income_cost_basis_eur != 0]
        income_value = sum((event.income_cost_basis_eur for event in income_events), Decimal("0"))
        status = "satisfied" if REPORTING_POLICY_APPLIED else ("blocked" if shifts else "satisfied")
        return TaxTimePrecisionAudit(
            generated_at=generated_at,
            policy_version=POLICY_VERSION,
            status=status,
            reporting_policy_applied=REPORTING_POLICY_APPLIED,
            rounding_policy=(
                "Backend und Datenbank behalten Decimal-Genauigkeit; EUR wird erst in der UI "
                "auf zwei Nachkommastellen formatiert."
            ),
            boundary_events_count=len(events),
            source_period_aggregate_events_count=len(period_aggregates),
            reporting_year_shift_events_count=len(shifts),
            reporting_year_shift_tax_lines_count=tax_line_count,
            reporting_year_shift_tax_gain_loss_eur=tax_gain,
            reporting_year_shift_income_events_count=len(income_events),
            reporting_year_shift_income_cost_basis_eur=income_value,
            affected_utc_years=sorted({event.utc_year for event in shifts}),
            affected_reporting_years=sorted({event.reporting_year for event in shifts}),
            events=events[: max(1, min(limit, 1000))],
            findings=(
                [
                    f"{len(shifts)} echte Ereignisse werden dem deutschen Kalenderjahr zugeordnet.",
                    f"{len(period_aggregates)} Helium-Periodenaggregate behalten ihr belegtes Quelljahr.",
                    f"Betroffen sind {tax_line_count} Steuerzeilen mit zusammen {tax_gain} EUR G/V.",
                    f"Betroffen sind {len(income_events)} Einkommensereignisse mit {income_value} EUR Anschaffungswert.",
                ]
                if shifts
                else ["Keine UTC-/Europe-Berlin-Jahresgrenze mit Berichtsabweichung vorhanden."]
            ),
            next_actions=(
                []
                if REPORTING_POLICY_APPLIED
                else [
                    "Jahresfilter fuer Tax-Lines, Rewards und Derivate auf Europe/Berlin umstellen.",
                    "Helium-Monatsaggregate anhand Period Start (UTC) im Quelljahr belassen.",
                    "Alle Steuerjahre im Staging vergleichen und erst danach produktiv freigeben.",
                ]
            ),
            methodology=(
                "Read-only Audit. Naive Datenbank-Timestamps werden als UTC interpretiert und mit "
                "IANA Europe/Berlin inklusive CET/CEST konvertiert. Helium-Monatsaggregate mit "
                "Period Start (UTC) verwenden das belegte Quelljahr statt des synthetischen "
                "Monatsendzeitpunkts. Der Audit schreibt keine Events, Tax-Lots oder Tax-Lines."
            ),
        )

    @staticmethod
    def _payload(value: object) -> dict[str, object]:
        try:
            parsed = json.loads(str(value or "{}"))
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
