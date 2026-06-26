from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from typing import Any

from steuerreport_v2.contracts.events import CanonicalEvent
from steuerreport_v2.contracts.review import ReviewDecisionCreate
from steuerreport_v2.contracts.valuation import (
    MissingPriceCoverageItem,
    PriceGapDecisionStatus,
    PriceCoverageReport,
    PriceQualityGroup,
    PriceQualityGroupDetail,
    PriceQualityBinanceNormalizerItem,
    PriceQualityBinanceNormalizerReport,
    PriceQualityClosureCandidate,
    PriceQualityClosureCandidateReport,
    PriceQualityClosureClass,
    PriceQualityDecisionStatus,
    PriceQualityEventQuoteEvidenceItem,
    PriceQualityEventQuoteEvidenceReport,
    PriceQualityLatestAsset,
    PriceQualityManualReviewItem,
    PriceQualityManualReviewReport,
    PriceQualityPriceSample,
    PriceQualityReport,
    PriceQualitySourceSummary,
    PriceQualityStablecoinFxItem,
    PriceQualityStablecoinFxReport,
    PriceQualityStablecoinFxReplacementDay,
    PriceQualityStablecoinFxReplacementGroup,
    PriceQualityStablecoinFxReplacementImpactReport,
    PriceQualityStablecoinFxReplacementImpactRow,
    PriceQualityStablecoinFxReplacementReport,
    PriceQualityStablecoinFxAnchorPreviewDecisionCreate,
    PriceQualityStablecoinFxAnchorPreviewGroup,
    PriceQualityStablecoinFxAnchorPreviewLatest,
    PriceQualityStablecoinFxTaxImpactDecisionCreate,
    PriceQualityStablecoinFxTaxImpactDecisionOption,
    PriceQualityStablecoinFxTaxImpactDecisionResult,
    PriceQualityStablecoinFxTaxImpactLatestReport,
    PriceQualitySolscanSignatureItem,
    PriceQualitySolscanSignatureReport,
    PriceQualityTaxSample,
    PriceRequirementItem,
    PriceRequirementReport,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup, fiat_price_point

TAX_VALUE_EVENT_TYPES = {"trade", "income", "reward", "staking", "mining", "fee"}
STABLECOIN_FX_ASSETS = {"USDT", "USDC", "BUSD", "EUR"}


@dataclass
class _MissingAccumulator:
    asset: str
    year: int
    source: str
    event_type: str
    role: str
    event_count: int = 0
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None
    gross_quantity: Decimal = Decimal("0")
    sample_event_ids: list[str] | None = None

    def add(self, event: CanonicalEvent, quantity: Decimal) -> None:
        self.event_count += 1
        self.first_event_at = (
            event.event_time
            if self.first_event_at is None
            else min(self.first_event_at, event.event_time)
        )
        self.last_event_at = (
            event.event_time
            if self.last_event_at is None
            else max(self.last_event_at, event.event_time)
        )
        self.gross_quantity += abs(quantity)
        if self.sample_event_ids is None:
            self.sample_event_ids = []
        if len(self.sample_event_ids) < 5:
            self.sample_event_ids.append(event.event_id)

    def to_contract(
        self,
        decision: tuple[PriceGapDecisionStatus, str, str] | None = None,
    ) -> MissingPriceCoverageItem:
        if self.first_event_at is None or self.last_event_at is None:
            raise RuntimeError("missing coverage accumulator has no events")
        scope = PriceCoverageService.issue_scope(
            asset=self.asset,
            year=self.year,
            source=self.source,
            event_type=self.event_type,
            role=self.role,
        )
        return MissingPriceCoverageItem(
            scope=scope,
            asset=self.asset,
            year=self.year,
            source=self.source,
            event_type=self.event_type,
            role=self.role,
            decision_status=decision[0] if decision is not None else "unreviewed",
            decision_id=decision[1] if decision is not None else None,
            decision_title=decision[2] if decision is not None else None,
            event_count=self.event_count,
            first_event_at=self.first_event_at,
            last_event_at=self.last_event_at,
            gross_quantity=self.gross_quantity,
            sample_event_ids=self.sample_event_ids or [],
        )


@dataclass
class _RequirementAccumulator:
    asset: str
    source: str
    event_type: str
    role: str
    price_date: date
    event_count: int = 0
    first_event_at: datetime | None = None
    last_event_at: datetime | None = None
    gross_quantity: Decimal = Decimal("0")
    sample_event_ids: list[str] | None = None

    def add(self, event: CanonicalEvent, quantity: Decimal) -> None:
        self.event_count += 1
        self.first_event_at = (
            event.event_time
            if self.first_event_at is None
            else min(self.first_event_at, event.event_time)
        )
        self.last_event_at = (
            event.event_time
            if self.last_event_at is None
            else max(self.last_event_at, event.event_time)
        )
        self.gross_quantity += abs(quantity)
        if self.sample_event_ids is None:
            self.sample_event_ids = []
        if len(self.sample_event_ids) < 5:
            self.sample_event_ids.append(event.event_id)

    def to_contract(self) -> PriceRequirementItem:
        if self.first_event_at is None or self.last_event_at is None:
            raise RuntimeError("price requirement accumulator has no events")
        return PriceRequirementItem(
            asset=self.asset,
            price_date=self.price_date,
            year=self.first_event_at.year,
            source=self.source,
            event_type=self.event_type,
            role=self.role,
            event_count=self.event_count,
            first_event_at=self.first_event_at,
            last_event_at=self.last_event_at,
            gross_quantity=self.gross_quantity,
            sample_event_ids=self.sample_event_ids or [],
        )


class PriceCoverageService:
    def __init__(self, store: DuckDbStore) -> None:
        self.store = store
        self.lookup = HistoricalPriceLookup(store)

    def report(self) -> PriceCoverageReport:
        decisions = self._price_gap_decisions_by_scope()
        items = sorted(
            (
                item.to_contract(
                    decisions.get(
                        self.issue_scope(
                            asset=item.asset,
                            year=item.year,
                            source=item.source,
                            event_type=item.event_type,
                            role=item.role,
                        )
                    )
                )
                for item in self._missing_accumulators().values()
            ),
            key=lambda item: (item.year, item.asset, item.source, item.event_type, item.role),
        )
        return PriceCoverageReport(
            missing_count=len(items),
            missing_assets=sorted({item.asset for item in items}),
            missing=items,
        )

    def requirements(self) -> PriceRequirementReport:
        items = sorted(
            (item.to_contract() for item in self._requirement_accumulators().values()),
            key=lambda item: (item.price_date, item.asset, item.source, item.event_type, item.role),
        )
        return PriceRequirementReport(
            requirements_count=len(items),
            missing_assets=sorted({item.asset for item in items}),
            requirements=items,
        )

    def _required_price_checks(
        self,
        event: CanonicalEvent,
    ) -> list[tuple[str, Decimal, str]]:
        checks: list[tuple[str, Decimal, str]] = []
        if event.event_type not in TAX_VALUE_EVENT_TYPES:
            return checks
        if event.quote_asset is not None and event.quote_quantity is not None:
            checks.append((event.quote_asset, event.quote_quantity, "quote_asset"))
        elif event.quantity != 0:
            checks.append((event.asset, event.quantity, "asset"))
        if event.fee_asset is not None and event.fee_quantity not in (None, Decimal("0")):
            checks.append((event.fee_asset, event.fee_quantity or Decimal("0"), "fee_asset"))
        return checks

    def _missing_accumulators(
        self,
    ) -> dict[tuple[str, int, str, str, str], _MissingAccumulator]:
        result: dict[tuple[str, int, str, str, str], _MissingAccumulator] = {}
        with self.store.connect() as con:
            rows = con.execute(
                self._missing_price_query(
                    """
                    req.asset,
                    date_part('year', req.event_time)::integer as year,
                    req.source,
                    req.event_type,
                    req.role,
                    count(*) as event_count,
                    min(req.event_time) as first_event_at,
                    max(req.event_time) as last_event_at,
                    sum(abs(req.quantity)) as gross_quantity,
                    list(req.event_id order by req.event_time, req.event_id) as sample_event_ids
                    """,
                    """
                    req.asset,
                    date_part('year', req.event_time),
                    req.source,
                    req.event_type,
                    req.role
                    """,
                    """
                    year,
                    req.asset,
                    req.source,
                    req.event_type,
                    req.role
                    """,
                )
            ).fetchall()

        for row in rows:
            key = (row[0], row[1], row[2], row[3], row[4])
            accumulator = _MissingAccumulator(
                asset=row[0],
                year=row[1],
                source=row[2],
                event_type=row[3],
                role=row[4],
                event_count=row[5],
                first_event_at=row[6],
                last_event_at=row[7],
                gross_quantity=row[8],
                sample_event_ids=list(row[9] or [])[:5],
            )
            result[key] = accumulator
        return result

    def _requirement_accumulators(
        self,
    ) -> dict[tuple[str, date, str, str, str], _RequirementAccumulator]:
        result: dict[tuple[str, date, str, str, str], _RequirementAccumulator] = {}
        with self.store.connect() as con:
            rows = con.execute(
                self._missing_price_query(
                    """
                    req.asset,
                    cast(req.event_time as date) as price_date,
                    req.source,
                    req.event_type,
                    req.role,
                    count(*) as event_count,
                    min(req.event_time) as first_event_at,
                    max(req.event_time) as last_event_at,
                    sum(abs(req.quantity)) as gross_quantity,
                    list(req.event_id order by req.event_time, req.event_id) as sample_event_ids
                    """,
                    """
                    req.asset,
                    cast(req.event_time as date),
                    req.source,
                    req.event_type,
                    req.role
                    """,
                    """
                    price_date,
                    req.asset,
                    req.source,
                    req.event_type,
                    req.role
                    """,
                )
            ).fetchall()

        for row in rows:
            key = (row[0], row[1], row[2], row[3], row[4])
            accumulator = _RequirementAccumulator(
                asset=row[0],
                price_date=row[1],
                source=row[2],
                event_type=row[3],
                role=row[4],
                event_count=row[5],
                first_event_at=row[6],
                last_event_at=row[7],
                gross_quantity=row[8],
                sample_event_ids=list(row[9] or [])[:5],
            )
            result[key] = accumulator
        return result

    def _missing_price_query(
        self,
        select_clause: str,
        group_by_clause: str,
        order_by_clause: str,
    ) -> str:
        return f"""
            with required_prices as (
                select
                    event_id,
                    source,
                    event_time,
                    event_type,
                    upper(quote_asset) as asset,
                    quote_quantity as quantity,
                    'quote_asset' as role
                from canonical_events
                where event_type in {self._tax_value_event_types_sql()}
                  and quote_asset is not null
                  and quote_quantity is not null
                  and upper(quote_asset) <> 'EUR'
                union all
                select
                    event_id,
                    source,
                    event_time,
                    event_type,
                    upper(asset) as asset,
                    quantity,
                    'asset' as role
                from canonical_events
                where event_type in {self._tax_value_event_types_sql()}
                  and (quote_asset is null or quote_quantity is null)
                  and quantity <> 0
                  and upper(asset) <> 'EUR'
                union all
                select
                    event_id,
                    source,
                    event_time,
                    event_type,
                    upper(fee_asset) as asset,
                    fee_quantity as quantity,
                    'fee_asset' as role
                from canonical_events
                where event_type in {self._tax_value_event_types_sql()}
                  and fee_asset is not null
                  and fee_quantity is not null
                  and fee_quantity <> 0
                  and upper(fee_asset) <> 'EUR'
            )
            select {select_clause}
            from required_prices req
            where not exists (
                select 1
                from price_ledger price
                where price.asset = req.asset
                  and price.price_eur > 0
                  and price.priced_at <= req.event_time
                  and (
                    (
                      req.source = 'solana_rpc'
                      and cast(price.priced_at as date) = cast(req.event_time as date)
                      and lower(price.source) not like 'derived:%'
                    )
                    or req.source <> 'solana_rpc'
                  )
            )
            group by {group_by_clause}
            order by {order_by_clause}
            """

    @staticmethod
    def _tax_value_event_types_sql() -> str:
        values = ", ".join(f"'{item}'" for item in sorted(TAX_VALUE_EVENT_TYPES))
        return f"({values})"

    def _has_acceptable_price(self, asset: str, event: CanonicalEvent) -> bool:
        if event.source == "solana_rpc":
            price = self.lookup.at_or_before(
                asset,
                event.event_time,
                allow_derived=False,
            )
            return price is not None and price.priced_at.date() == event.event_time.date()
        return self.lookup.at_or_before(asset, event.event_time) is not None

    @staticmethod
    def issue_scope(
        *,
        asset: str,
        year: int,
        source: str,
        event_type: str,
        role: str,
    ) -> str:
        return (
            f"price_gap:asset:{asset.upper()}:year:{year}:source:{source}:"
            f"event_type:{event_type}:role:{role}"
        )

    def _price_gap_decisions_by_scope(self) -> dict[str, tuple[PriceGapDecisionStatus, str, str]]:
        result: dict[str, tuple[PriceGapDecisionStatus, str, str]] = {}
        valid_statuses = {
            "price_source_needed",
            "manual_price_required",
            "parser_data_needed",
            "not_tax_relevant",
            "price_added",
        }
        for decision in reversed(self.store.list_review_decisions()):
            if decision.decision_type != "price_gap":
                continue
            raw_status = decision.payload.get("decision_status")
            if not isinstance(raw_status, str) or raw_status not in valid_statuses:
                continue
            result[decision.scope] = (
                raw_status,  # type: ignore[assignment]
                decision.decision_id,
                decision.title,
            )
        return result


class PriceQualityService:
    TAX_IMPACT_ARTIFACT_DIR = Path("var/stablecoin_fx_replacement_tax_impact")
    ANCHOR_PREVIEW_ARTIFACT_DIR = Path("var/stablecoin_fx_anchor_preview")

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def report(self, limit: int = 120) -> PriceQualityReport:
        decisions = self._price_quality_decisions_by_scope()
        groups = self._apply_decisions(self._groups(limit=max(1, limit)), decisions)
        source_summaries = self._source_summaries()
        latest_assets = self._latest_assets()
        totals = self._totals()
        issue_group_counts = self._issue_group_counts()
        return PriceQualityReport(
            generated_at=datetime.now(timezone.utc),
            price_points_count=totals["price_points_count"],
            assets_count=totals["assets_count"],
            sources_count=totals["sources_count"],
            low_confidence_count=totals["low_confidence_count"],
            proxy_count=totals["proxy_count"],
            zero_or_negative_count=totals["zero_or_negative_count"],
            tax_relevant_issue_groups=issue_group_counts["tax_relevant_issue_groups"],
            issue_groups_count=issue_group_counts["issue_groups_count"],
            high_risk_groups=issue_group_counts["high_risk_groups"],
            medium_risk_groups=issue_group_counts["medium_risk_groups"],
            low_risk_groups=issue_group_counts["low_risk_groups"],
            groups=groups,
            source_summaries=source_summaries,
            latest_assets=latest_assets,
            methodology=(
                "Read-only Aggregation aus price_ledger und tax_lines. High "
                "bedeutet: Low-Confidence/Proxy/ungueltige Preiszeile beruehrt "
                "ein Asset/Jahr mit Tax-Lines. Medium bedeutet: Qualitaetswarnung "
                "ohne Tax-Line-Bezug in dieser Gruppierung. Diese Sicht schreibt "
                "keine Preise und akzeptiert keine Preisquelle automatisch."
            ),
        )

    def group_detail(
        self,
        *,
        asset: str,
        year: int,
        source: str,
        limit: int = 25,
    ) -> PriceQualityGroupDetail:
        normalized_asset = asset.upper()
        normalized_limit = max(1, min(limit, 200))
        group = self._single_group(asset=normalized_asset, year=year, source=source)
        decisions = self._price_quality_decisions_by_scope()
        if group is not None:
            group = self._apply_decisions([group], decisions)[0]
        price_samples = self._price_samples(
            asset=normalized_asset,
            year=year,
            source=source,
            limit=normalized_limit,
        )
        tax_samples = self._tax_line_samples(
            asset=normalized_asset,
            year=year,
            limit=normalized_limit,
        )
        return PriceQualityGroupDetail(
            asset=normalized_asset,
            year=year,
            source=source,
            group=group,
            price_samples=price_samples,
            tax_line_samples=tax_samples,
            event_sources=self._count_dict(sample.event_source for sample in price_samples),
            quote_assets=self._count_dict(sample.quote_asset for sample in price_samples),
            methodology=(
                "Read-only Drilldown fuer eine Preisqualitaetsgruppe. "
                "Price-Samples werden anhand Asset, Jahr, Quelle und identischem "
                "Event-Zeitpunkt mit Canonical Events verknuepft; Tax-Line-Samples "
                "zeigen die steuerliche Nutzung des Asset/Jahrs."
            ),
        )

    def manual_review_report(self, limit: int = 120) -> PriceQualityManualReviewReport:
        decisions = self._price_quality_decisions_by_scope()
        groups = self._apply_decisions(self._groups(limit=10_000), decisions)
        manual_groups = [
            group
            for group in groups
            if group.decision_status == "manual_review_required"
        ]
        manual_groups.sort(
            key=lambda group: (
                -group.tax_lines_count,
                -group.price_count,
                group.asset,
                group.year,
                group.source,
            )
        )
        sample_contexts = self._manual_review_sample_contexts(manual_groups[: max(1, limit)])
        items: list[PriceQualityManualReviewItem] = []
        for rank, group in enumerate(manual_groups[: max(1, limit)], start=1):
            samples = sample_contexts.get(group.scope, [])
            items.append(
                PriceQualityManualReviewItem(
                    scope=group.scope,
                    asset=group.asset,
                    year=group.year,
                    source=group.source,
                    priority_rank=rank,
                    review_bucket=self._manual_review_bucket(group, samples),
                    evidence_ref=(
                        "/api/v1/prices/quality/group"
                        f"?asset={group.asset}&year={group.year}&source={group.source}"
                    ),
                    decision_id=group.decision_id,
                    decision_title=group.decision_title,
                    price_count=group.price_count,
                    tax_lines_count=group.tax_lines_count,
                    tax_quantity=group.tax_quantity,
                    status=group.status,
                    risk_level=group.risk_level,
                    event_sources=self._count_dict(sample.event_source for sample in samples),
                    quote_assets=self._count_dict(sample.quote_asset for sample in samples),
                    sample_event_refs=[
                        ref
                        for ref in (sample.source_ref for sample in samples)
                        if ref
                    ][:5],
                    reason=self._manual_review_reason(samples),
                    next_action=self._manual_review_next_action(group, samples),
                )
            )
        return PriceQualityManualReviewReport(
            generated_at=datetime.now(timezone.utc),
            manual_groups_count=len(manual_groups),
            tax_relevant_groups_count=sum(1 for group in manual_groups if group.tax_lines_count > 0),
            total_tax_lines_count=sum(group.tax_lines_count for group in manual_groups),
            groups=items,
            methodology=(
                "Priorisierte Arbeitsliste aus PriceQuality-Gruppen mit "
                "decision_status=manual_review_required. Sortierung nach "
                "Tax-Line-Anzahl, Preiszeilen und Asset/Jahr. Sample-Kontext "
                "wird gebuendelt gelesen. Die Liste ist read-only und erzeugt "
                "keine Preis-, Import- oder FIFO-Aenderung."
            ),
        )

    def stablecoin_fx_review(self, limit: int = 120) -> PriceQualityStablecoinFxReport:
        manual = self.manual_review_report(limit=10_000)
        groups = [
            group
            for group in manual.groups
            if group.review_bucket == "stablecoin_fx_review"
        ]
        groups.sort(
            key=lambda group: (
                -group.tax_lines_count,
                group.asset,
                group.year,
                group.source,
            )
        )
        items = [
            PriceQualityStablecoinFxItem(
                scope=group.scope,
                asset=group.asset,
                year=group.year,
                source=group.source,
                price_count=group.price_count,
                tax_lines_count=group.tax_lines_count,
                tax_quantity=group.tax_quantity,
                decision_id=group.decision_id,
                decision_title=group.decision_title,
                expected_price_basis=self._stablecoin_expected_price_basis(group.asset),
                recommended_action=self._stablecoin_recommended_action(group.asset, group.tax_lines_count),
                evidence_ref=group.evidence_ref,
                event_sources=group.event_sources,
                quote_assets=group.quote_assets,
                sample_event_refs=group.sample_event_refs,
                reason=group.reason,
            )
            for group in groups[: max(1, limit)]
        ]
        return PriceQualityStablecoinFxReport(
            generated_at=datetime.now(timezone.utc),
            groups_count=len(groups),
            tax_relevant_groups_count=sum(1 for group in groups if group.tax_lines_count > 0),
            total_tax_lines_count=sum(group.tax_lines_count for group in groups),
            assets=sorted({group.asset for group in groups}),
            groups=items,
            methodology=(
                "Read-only Arbeitsliste fuer Stablecoin-/Fiat-Preisgruppen. "
                "USDT/USDC/BUSD sollen gegen USD/EUR-FX bzw. belastbare "
                "Marktpreise geprueft werden; EUR wird als Fiat-Basis mit "
                "EUR=1 betrachtet. Der Endpunkt schreibt keine Preiszeilen "
                "und aendert keine FIFO- oder Steuerdaten."
            ),
        )

    def stablecoin_fx_replacement_preview(
        self,
        limit: int = 120,
        days_per_group: int = 20,
    ) -> PriceQualityStablecoinFxReplacementReport:
        manual = self.manual_review_report(limit=10_000)
        groups = [
            group
            for group in manual.groups
            if group.review_bucket == "stablecoin_fx_review"
            and group.asset in {"USDT", "USDC", "BUSD"}
            and group.source == "derived:event_quote"
        ]
        groups.sort(
            key=lambda group: (
                -group.tax_lines_count,
                group.asset,
                group.year,
                group.source,
            )
        )

        items: list[PriceQualityStablecoinFxReplacementGroup] = []
        all_days: list[PriceQualityStablecoinFxReplacementDay] = []
        for group in groups[: max(1, limit)]:
            days = self._stablecoin_fx_replacement_days(
                group,
                limit=max(1, days_per_group),
            )
            all_days.extend(days)
            days_needing_replacement = sum(
                1 for day in days if day.replacement_status == "replacement_needed"
            )
            fx_backed_days = sum(
                1 for day in days if day.replacement_status == "fx_backed_available"
            )
            market_days = sum(
                1 for day in days if day.replacement_status == "market_price_available"
            )
            items.append(
                PriceQualityStablecoinFxReplacementGroup(
                    scope=group.scope,
                    asset=group.asset,
                    year=group.year,
                    source=group.source,
                    tax_lines_count=group.tax_lines_count,
                    tax_quantity=group.tax_quantity,
                    days_count=len(days),
                    days_needing_replacement=days_needing_replacement,
                    fx_backed_days_count=fx_backed_days,
                    market_price_days_count=market_days,
                    days=days,
                    recommended_action=self._stablecoin_fx_replacement_group_action(
                        days_needing_replacement=days_needing_replacement,
                        fx_backed_days=fx_backed_days,
                        market_days=market_days,
                    ),
                )
            )

        return PriceQualityStablecoinFxReplacementReport(
            generated_at=datetime.now(timezone.utc),
            groups_count=len(groups),
            tax_relevant_groups_count=sum(1 for group in groups if group.tax_lines_count > 0),
            days_count=sum(group.days_count for group in items),
            days_needing_replacement=sum(group.days_needing_replacement for group in items),
            fx_backed_days_count=sum(group.fx_backed_days_count for group in items),
            market_price_days_count=sum(group.market_price_days_count for group in items),
            total_tax_lines_count=sum(group.tax_lines_count for group in groups),
            assets=sorted({group.asset for group in groups}),
            groups=items,
            methodology=(
                "Read-only Stablecoin-FX-Replacement-Preview fuer USDT/USDC/BUSD "
                "PriceQuality-Gruppen mit derived:event_quote. Die Matrix zeigt pro "
                "Asset/Jahr/Tag, ob eine gleichdatierte FX-/ECB-/USD_EUR-Quelle oder "
                "sonstige Marktpreisquelle existiert. Sie schreibt keine Preise, "
                "keine Review-Decisions und aendert keine FIFO-/Steuerdaten."
            ),
        )

    def stablecoin_fx_replacement_impact(
        self,
        *,
        asset: str,
        year: int,
        source: str = "derived:event_quote",
        limit: int = 200,
    ) -> PriceQualityStablecoinFxReplacementImpactReport:
        normalized_asset = asset.upper()
        with self.store.connect() as con:
            tax_row = con.execute(
                """
                select count(*)::integer, coalesce(sum(abs(quantity)), 0)
                from tax_lines
                where upper(asset) = ?
                  and date_part('year', disposed_at)::integer = ?
                """,
                [normalized_asset, year],
            ).fetchone()
            rows = con.execute(
                """
                with alternatives as (
                    select
                        price_id,
                        upper(asset) as asset,
                        price_eur,
                        priced_at,
                        source,
                        case
                          when lower(source) like '%usd_eur%'
                            or lower(source) like '%fx%'
                            or lower(source) like '%ecb%'
                          then 1 else 0
                        end as is_fx_backed,
                        case
                          when lower(source) like '%coingecko%'
                            or lower(source) like '%market%'
                            or lower(source) like '%manual%'
                          then 1 else 0
                        end as is_market
                    from price_ledger
                    where upper(asset) = ?
                      and date_part('year', priced_at)::integer = ?
                      and source <> ?
                      and price_eur > 0
                ),
                selected_alternative as (
                    select *
                    from (
                        select
                            asset,
                            cast(priced_at as date) as price_date,
                            price_id,
                            price_eur,
                            source,
                            priced_at,
                            row_number() over (
                                partition by asset, cast(priced_at as date)
                                order by is_fx_backed desc, is_market desc, priced_at desc, source, price_id
                            ) as rn
                        from alternatives
                    )
                    where rn = 1
                ),
                refs as (
                    select
                        upper(asset) as asset,
                        cast(event_time as date) as price_date,
                        list(source_ref order by event_time, event_id) as source_refs
                    from canonical_events
                    where upper(asset) = ?
                      and date_part('year', event_time)::integer = ?
                      and source_ref is not null
                    group by upper(asset), cast(event_time as date)
                )
                select
                    p.price_id,
                    upper(p.asset) as asset,
                    date_part('year', p.priced_at)::integer as year,
                    p.priced_at,
                    p.price_eur,
                    p.source,
                    s.price_eur as replacement_price_eur,
                    s.source as replacement_source,
                    s.priced_at as replacement_priced_at,
                    coalesce(r.source_refs, []) as source_refs
                from price_ledger p
                left join selected_alternative s
                  on s.asset = upper(p.asset)
                 and s.price_date = cast(p.priced_at as date)
                left join refs r
                  on r.asset = upper(p.asset)
                 and r.price_date = cast(p.priced_at as date)
                where upper(p.asset) = ?
                  and date_part('year', p.priced_at)::integer = ?
                  and p.source = ?
                order by
                    case when s.price_id is null then 0 else 1 end,
                    p.priced_at,
                    p.price_id
                limit ?
                """,
                [
                    normalized_asset,
                    year,
                    source,
                    normalized_asset,
                    year,
                    normalized_asset,
                    year,
                    source,
                    max(1, limit),
                ],
            ).fetchall()

        impact_rows: list[PriceQualityStablecoinFxReplacementImpactRow] = []
        deltas: list[Decimal] = []
        for row in rows:
            derived_price = row[4]
            replacement_price = row[6]
            abs_delta_eur: Decimal | None = None
            abs_delta_pct: Decimal | None = None
            if replacement_price is not None:
                abs_delta_eur = abs(derived_price - replacement_price)
                if replacement_price > 0:
                    abs_delta_pct = abs_delta_eur / replacement_price * Decimal("100")
                    deltas.append(abs_delta_pct)
            status = "ready" if replacement_price is not None else "missing_replacement"
            impact_rows.append(
                PriceQualityStablecoinFxReplacementImpactRow(
                    price_id=row[0],
                    asset=row[1],
                    year=row[2],
                    priced_at=row[3],
                    derived_price_eur=derived_price,
                    derived_source=row[5],
                    replacement_status=status,
                    replacement_price_eur=replacement_price,
                    replacement_source=row[7],
                    replacement_priced_at=row[8],
                    abs_delta_eur=abs_delta_eur,
                    abs_delta_pct=abs_delta_pct,
                    sample_event_refs=list(row[9] or [])[:5],
                    recommended_action=self._stablecoin_fx_replacement_impact_action(status),
                )
            )

        missing = sum(1 for row in impact_rows if row.replacement_status == "missing_replacement")
        return PriceQualityStablecoinFxReplacementImpactReport(
            generated_at=datetime.now(timezone.utc),
            asset=normalized_asset,
            year=year,
            source=source,
            derived_price_rows=len(impact_rows),
            replacement_ready_rows=len(impact_rows) - missing,
            missing_replacement_rows=missing,
            all_replacement_ready=bool(impact_rows) and missing == 0,
            tax_lines_count=int(tax_row[0] or 0),
            tax_quantity=tax_row[1] or Decimal("0"),
            max_abs_delta_pct=max(deltas) if deltas else None,
            avg_abs_delta_pct=(sum(deltas, Decimal("0")) / Decimal(len(deltas))) if deltas else None,
            rows=impact_rows,
            methodology=(
                "Read-only Impact-Vorschau fuer Stablecoin-FX-Replacement. "
                "Pro Derived-Preiszeile wird der beste gleichdatierte Ersatzpreis "
                "aus vorhandenen Preiszeilen ausgewaehlt, bevorzugt FX-/USD_EUR-/ECB-"
                "Quellen. Der Endpunkt schreibt keine Preise und baut FIFO nicht neu."
            ),
        )

    def stablecoin_fx_tax_impact_latest(
        self,
        *,
        asset: str = "USDT",
        year: int = 2024,
        source: str = "derived:event_quote",
    ) -> PriceQualityStablecoinFxTaxImpactLatestReport:
        normalized_asset = asset.upper()
        scope = self.stablecoin_fx_tax_impact_scope(
            asset=normalized_asset,
            year=year,
            source=source,
        )
        path = self._stablecoin_fx_tax_impact_artifact_path(
            asset=normalized_asset,
            year=year,
        )
        payload: dict[str, object] | None = None
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))

        decisions = [
            decision
            for decision in self.store.list_review_decisions()
            if decision.decision_type == "stablecoin_fx_replacement_tax_impact"
            and decision.scope == scope
        ]
        decisions.sort(key=lambda item: item.created_at, reverse=True)
        latest_decision = decisions[0] if decisions else None
        conclusion = str(payload.get("conclusion")) if payload else None
        replacement_plan = payload.get("replacement_plan") if payload else {}
        baseline = payload.get("baseline") if payload else {}
        patched = payload.get("patched") if payload else {}
        delta = payload.get("delta") if payload else {}
        return PriceQualityStablecoinFxTaxImpactLatestReport(
            generated_at=datetime.now(timezone.utc),
            asset=normalized_asset,
            year=year,
            source=source,
            artifact_path=str(path) if path.exists() else None,
            artifact_found=path.exists(),
            artifact_generated_at=self._parse_optional_datetime(payload.get("generated_at") if payload else None),
            conclusion=conclusion,
            replacement_rows_count=int(self._mapping_value(replacement_plan, "rows_count") or 0),
            replacement_ready_rows=int(self._mapping_value(replacement_plan, "ready_rows") or 0),
            replacement_missing_rows=int(self._mapping_value(replacement_plan, "missing_rows") or 0),
            applied_rows=int(self._mapping_value(replacement_plan, "applied_rows") or 0),
            baseline_taxable_gain_loss_eur=self._optional_decimal(
                self._mapping_value(baseline, "taxable_gain_loss_eur")
            ),
            patched_taxable_gain_loss_eur=self._optional_decimal(
                self._mapping_value(patched, "taxable_gain_loss_eur")
            ),
            taxable_gain_loss_delta_eur=self._optional_decimal(
                self._mapping_value(delta, "taxable_gain_loss_eur")
            ),
            baseline_stablecoin_gain_loss_eur=self._optional_decimal(
                self._mapping_value(baseline, "stablecoin_gain_loss_eur")
            ),
            patched_stablecoin_gain_loss_eur=self._optional_decimal(
                self._mapping_value(patched, "stablecoin_gain_loss_eur")
            ),
            stablecoin_gain_loss_delta_eur=self._optional_decimal(
                self._mapping_value(delta, "stablecoin_gain_loss_eur")
            ),
            unmatched_disposals_delta=self._optional_int(
                self._mapping_value(delta, "unmatched_disposals")
            ),
            existing_decisions_count=len(decisions),
            latest_decision_id=latest_decision.decision_id if latest_decision else None,
            latest_decision_action=(
                latest_decision.payload.get("action")  # type: ignore[assignment]
                if latest_decision and latest_decision.payload.get("action") in {"apply_replacement", "document_delta_only", "keep_existing"}
                else None
            ),
            latest_decision_title=latest_decision.title if latest_decision else None,
            decision_scope=scope,
            decision_options=self._stablecoin_fx_tax_impact_decision_options(conclusion),
            recommended_next_action=self._stablecoin_fx_tax_impact_next_action(
                artifact_found=path.exists(),
                conclusion=conclusion,
                decisions_count=len(decisions),
            ),
            methodology=(
                "Read-only Statusflaeche fuer Stablecoin-FX-Tax-Impact-Artefakte. "
                "Der Report liest nur das letzte Skriptartefakt und vorhandene "
                "Review-Decisions. Er schreibt keine Preise, keine FIFO-Lots und "
                "keine Tax-Lines."
            ),
        )

    def add_stablecoin_fx_tax_impact_decision(
        self,
        payload: PriceQualityStablecoinFxTaxImpactDecisionCreate,
    ) -> PriceQualityStablecoinFxTaxImpactDecisionResult:
        normalized_asset = payload.asset.upper()
        latest = self.stablecoin_fx_tax_impact_latest(
            asset=normalized_asset,
            year=payload.year,
            source=payload.source,
        )
        if not latest.artifact_found:
            raise ValueError("stablecoin_fx_tax_impact_artifact_missing")
        scope = latest.decision_scope
        evidence_ref = payload.evidence_ref or latest.artifact_path
        decision = self.store.add_review_decision(
            ReviewDecisionCreate(
                decision_type="stablecoin_fx_replacement_tax_impact",
                scope=scope,
                title=self._stablecoin_fx_tax_impact_decision_title(
                    asset=normalized_asset,
                    year=payload.year,
                    action=payload.action,
                ),
                rationale=payload.rationale,
                evidence_ref=evidence_ref,
                actor="user",
                source="api:/api/v1/prices/quality/stablecoin-fx-tax-impact-decisions",
                payload={
                    "action": payload.action,
                    "asset": normalized_asset,
                    "year": payload.year,
                    "price_source": payload.source,
                    "artifact_path": latest.artifact_path,
                    "conclusion": latest.conclusion,
                    "taxable_gain_loss_delta_eur": (
                        str(latest.taxable_gain_loss_delta_eur)
                        if latest.taxable_gain_loss_delta_eur is not None
                        else None
                    ),
                    "stablecoin_gain_loss_delta_eur": (
                        str(latest.stablecoin_gain_loss_delta_eur)
                        if latest.stablecoin_gain_loss_delta_eur is not None
                        else None
                    ),
                    "import_effect": "none",
                    "ledger_effect": "none",
                    "fifo_effect": "none",
                    "tax_lines_effect": "none",
                    "price_write_effect": "none",
                },
            )
        )
        return PriceQualityStablecoinFxTaxImpactDecisionResult(
            decision_id=decision.decision_id,
            scope=scope,
            action=payload.action,
            writes_prices=False,
            writes_fifo=False,
            writes_tax_lines=False,
        )

    def stablecoin_fx_anchor_preview_latest(
        self,
        *,
        include_rows: bool = False,
    ) -> PriceQualityStablecoinFxAnchorPreviewLatest:
        path = self.ANCHOR_PREVIEW_ARTIFACT_DIR / "latest_stablecoin_fx_anchor_preview.json"
        payload: dict[str, object] | None = None
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))

        summary = payload.get("summary") if payload else {}
        tax_impact_summary = payload.get("tax_impact_summary") if payload else {}
        if (
            (not isinstance(tax_impact_summary, dict) or not tax_impact_summary)
            and payload
            and isinstance(payload.get("tax_impact"), list)
        ):
            tax_impact_summary = self._stablecoin_fx_anchor_tax_impact_summary(payload["tax_impact"])
        raw_groups = self._mapping_value(summary, "groups") or []
        decisions = self._stablecoin_fx_tax_impact_decisions_by_scope()
        groups: list[PriceQualityStablecoinFxAnchorPreviewGroup] = []
        if isinstance(raw_groups, list):
            for item in raw_groups:
                if not isinstance(item, dict):
                    continue
                asset = str(item.get("asset", "")).upper()
                year = int(item.get("year") or 0)
                scope = self.stablecoin_fx_tax_impact_scope(
                    asset=asset,
                    year=year,
                    source="derived:event_quote",
                )
                group_decisions = decisions.get(scope, [])
                latest = group_decisions[0] if group_decisions else None
                missing_days = int(item.get("missing_days") or 0)
                ready_days = int(item.get("ready_days") or 0)
                if missing_days:
                    status = "incomplete"
                    next_action = "Fehlende USD/EUR-FX-Tage beschaffen, bevor eine Review-Decision moeglich ist."
                elif latest:
                    status = "review_documented"
                    next_action = "Review-Decision ist dokumentiert; Apply-Pfad nur separat und kontrolliert ausfuehren."
                elif ready_days:
                    status = "ready_for_review"
                    next_action = "Tax-Impact pruefen und Review-Decision je Asset/Jahr dokumentieren."
                else:
                    status = "empty"
                    next_action = "Keine offenen Stablecoin-FX-Anker fuer diese Gruppe."
                action = latest.payload.get("action") if latest else None
                groups.append(
                    PriceQualityStablecoinFxAnchorPreviewGroup(
                        asset=asset,
                        year=year,
                        required_days=int(item.get("required_days") or 0),
                        ready_days=ready_days,
                        missing_days=missing_days,
                        tax_lines_count=int(item.get("tax_lines_count") or 0),
                        existing_decisions_count=len(group_decisions),
                        latest_decision_id=latest.decision_id if latest else None,
                        latest_decision_action=(
                            action  # type: ignore[arg-type]
                            if action in {"apply_replacement", "document_delta_only", "keep_existing"}
                            else None
                        ),
                        status=status,  # type: ignore[arg-type]
                        recommended_next_action=next_action,
                    )
                )

        anchors = payload.get("anchors") if payload and include_rows else []
        tax_impact = payload.get("tax_impact") if payload and include_rows else []
        return PriceQualityStablecoinFxAnchorPreviewLatest(
            generated_at=datetime.now(timezone.utc),
            artifact_found=path.exists(),
            artifact_path=str(path) if path.exists() else None,
            artifact_generated_at=self._parse_optional_datetime(payload.get("generated_at") if payload else None),
            required_days=int(self._mapping_value(summary, "required_days") or 0),
            ready_days=int(self._mapping_value(summary, "ready_days") or 0),
            missing_days=int(self._mapping_value(summary, "missing_days") or 0),
            groups_count=len(groups),
            groups_requiring_review=sum(1 for group in groups if group.status == "ready_for_review"),
            taxable_gain_loss_delta_eur=self._optional_decimal(
                self._mapping_value(tax_impact_summary, "taxable_gain_loss_delta_eur")
            ),
            groups=groups,
            anchors=anchors if isinstance(anchors, list) else [],
            tax_impact=tax_impact if isinstance(tax_impact, list) else [],
            methodology=(
                "Read-only Statusflaeche fuer das Stablecoin-FX-Anchor-Preview-Artefakt. "
                "Der Endpunkt liest nur JSON und Review-Decisions. Er schreibt keine Preise, "
                "keine FIFO-Lots und keine Tax-Lines."
            ),
        )

    def add_stablecoin_fx_anchor_preview_decision(
        self,
        payload: PriceQualityStablecoinFxAnchorPreviewDecisionCreate,
    ) -> PriceQualityStablecoinFxTaxImpactDecisionResult:
        if payload.action == "apply_replacement":
            raise ValueError("stablecoin_fx_anchor_preview_apply_not_supported")
        path = self.ANCHOR_PREVIEW_ARTIFACT_DIR / "latest_stablecoin_fx_anchor_preview.json"
        if not path.exists():
            raise ValueError("stablecoin_fx_anchor_preview_artifact_missing")
        artifact = json.loads(path.read_text(encoding="utf-8"))
        normalized_asset = payload.asset.upper()
        impact = self._stablecoin_fx_anchor_impact_for_group(
            artifact.get("tax_impact"),
            asset=normalized_asset,
            year=payload.year,
            source=payload.source,
        )
        if impact is None:
            raise ValueError("stablecoin_fx_anchor_preview_group_missing")
        scope = self.stablecoin_fx_tax_impact_scope(
            asset=normalized_asset,
            year=payload.year,
            source=payload.source,
        )
        delta = impact.get("delta") if isinstance(impact.get("delta"), dict) else {}
        decision = self.store.add_review_decision(
            ReviewDecisionCreate(
                decision_type="stablecoin_fx_replacement_tax_impact",
                scope=scope,
                title=self._stablecoin_fx_anchor_decision_title(
                    asset=normalized_asset,
                    year=payload.year,
                    action=payload.action,
                ),
                rationale=payload.rationale,
                evidence_ref=payload.evidence_ref or str(path),
                actor="user",
                source="api:/api/v1/prices/quality/stablecoin-fx-anchor-preview-decisions",
                payload={
                    "action": payload.action,
                    "asset": normalized_asset,
                    "year": payload.year,
                    "price_source": payload.source,
                    "artifact_path": str(path),
                    "conclusion": impact.get("conclusion"),
                    "taxable_gain_loss_delta_eur": (
                        str(delta.get("taxable_gain_loss_eur"))
                        if isinstance(delta, dict) and delta.get("taxable_gain_loss_eur") is not None
                        else None
                    ),
                    "stablecoin_gain_loss_delta_eur": (
                        str(delta.get("stablecoin_gain_loss_eur"))
                        if isinstance(delta, dict) and delta.get("stablecoin_gain_loss_eur") is not None
                        else None
                    ),
                    "anchor_days": impact.get("anchor_days"),
                    "applied_replacements_in_preview": impact.get("applied_replacements"),
                    "import_effect": "none",
                    "ledger_effect": "none",
                    "fifo_effect": "none",
                    "tax_lines_effect": "none",
                    "price_write_effect": "none",
                },
            )
        )
        return PriceQualityStablecoinFxTaxImpactDecisionResult(
            decision_id=decision.decision_id,
            scope=scope,
            action=payload.action,
            writes_prices=False,
            writes_fifo=False,
            writes_tax_lines=False,
        )

    def solscan_signature_review(self, limit: int = 120) -> PriceQualitySolscanSignatureReport:
        manual = self.manual_review_report(limit=10_000)
        groups = [
            group
            for group in manual.groups
            if group.review_bucket == "solscan_signature_review"
        ]
        groups.sort(
            key=lambda group: (
                -group.tax_lines_count,
                -group.price_count,
                group.asset,
                group.year,
                group.source,
            )
        )
        items: list[PriceQualitySolscanSignatureItem] = []
        for group in groups[: max(1, limit)]:
            signature_refs, non_signature_refs = self._split_signature_refs(group.sample_event_refs)
            items.append(
                PriceQualitySolscanSignatureItem(
                    scope=group.scope,
                    asset=group.asset,
                    year=group.year,
                    source=group.source,
                    price_count=group.price_count,
                    tax_lines_count=group.tax_lines_count,
                    tax_quantity=group.tax_quantity,
                    decision_id=group.decision_id,
                    decision_title=group.decision_title,
                    signature_count=len(signature_refs),
                    non_signature_ref_count=len(non_signature_refs),
                    signature_refs=signature_refs[:5],
                    non_signature_refs=non_signature_refs[:5],
                    event_sources=group.event_sources,
                    quote_assets=group.quote_assets,
                    reason=group.reason,
                    recommended_action=self._solscan_recommended_action(group, signature_refs),
                    evidence_ref=group.evidence_ref,
                )
            )
        return PriceQualitySolscanSignatureReport(
            generated_at=datetime.now(timezone.utc),
            groups_count=len(groups),
            tax_relevant_groups_count=sum(1 for group in groups if group.tax_lines_count > 0),
            total_tax_lines_count=sum(group.tax_lines_count for group in groups),
            total_signature_refs=sum(
                len(self._split_signature_refs(group.sample_event_refs)[0])
                for group in groups
            ),
            assets=sorted({group.asset for group in groups}),
            groups=items,
            methodology=(
                "Read-only Arbeitsliste fuer Solana-RPC/Solscan-Preisgruppen. "
                "Der Endpunkt trennt echte Onchain-Signatur-Refs von CEX-/CSV-"
                "Refs und priorisiert steuerrelevante Gruppen. Er schreibt "
                "keine Preiszeilen und aendert keine FIFO- oder Steuerdaten."
            ),
        )

    def binance_normalizer_review(self, limit: int = 120) -> PriceQualityBinanceNormalizerReport:
        manual = self.manual_review_report(limit=10_000)
        groups = [
            group
            for group in manual.groups
            if group.review_bucket == "binance_normalizer_review"
        ]
        groups.sort(
            key=lambda group: (
                -group.tax_lines_count,
                -group.price_count,
                group.asset,
                group.year,
                group.source,
            )
        )
        items = [
            PriceQualityBinanceNormalizerItem(
                scope=group.scope,
                asset=group.asset,
                year=group.year,
                source=group.source,
                price_count=group.price_count,
                tax_lines_count=group.tax_lines_count,
                tax_quantity=group.tax_quantity,
                decision_id=group.decision_id,
                decision_title=group.decision_title,
                has_missing_quote_fields="fehlende quote_asset-Felder" in group.reason,
                has_unknown_events="unknown Events" in group.reason,
                has_zero_quantity_samples="Zero-Quantity-Samples" in group.reason,
                sample_ref_count=len(group.sample_event_refs),
                missing_sample_refs=not group.sample_event_refs,
                sample_event_refs=group.sample_event_refs[:5],
                event_sources=group.event_sources,
                quote_assets=group.quote_assets,
                reason=group.reason,
                recommended_action=self._binance_normalizer_recommended_action(group),
                evidence_ref=group.evidence_ref,
            )
            for group in groups[: max(1, limit)]
        ]
        return PriceQualityBinanceNormalizerReport(
            generated_at=datetime.now(timezone.utc),
            groups_count=len(groups),
            tax_relevant_groups_count=sum(1 for group in groups if group.tax_lines_count > 0),
            total_tax_lines_count=sum(group.tax_lines_count for group in groups),
            missing_quote_groups_count=sum(
                1 for group in groups if "fehlende quote_asset-Felder" in group.reason
            ),
            unknown_or_zero_groups_count=sum(
                1
                for group in groups
                if "unknown Events" in group.reason or "Zero-Quantity-Samples" in group.reason
            ),
            missing_sample_ref_groups_count=sum(1 for group in groups if not group.sample_event_refs),
            assets=sorted({group.asset for group in groups}),
            groups=items,
            methodology=(
                "Read-only Arbeitsliste fuer Binance-Preisgruppen mit "
                "fehlenden Quote-Feldern, unknown Events oder Zero-Quantity-"
                "Samples. Der Endpunkt markiert Raw-/Normalizer-Risiken, "
                "schreibt keine Preiszeilen und aendert keine FIFO- oder "
                "Steuerdaten."
            ),
        )

    def event_quote_evidence_review(self, limit: int = 120) -> PriceQualityEventQuoteEvidenceReport:
        manual = self.manual_review_report(limit=10_000)
        groups = [
            group
            for group in manual.groups
            if group.review_bucket == "event_quote_evidence_review"
        ]
        groups.sort(
            key=lambda group: (
                -group.tax_lines_count,
                -group.price_count,
                group.asset,
                group.year,
                group.source,
            )
        )
        items = [
            PriceQualityEventQuoteEvidenceItem(
                scope=group.scope,
                asset=group.asset,
                year=group.year,
                source=group.source,
                price_count=group.price_count,
                tax_lines_count=group.tax_lines_count,
                tax_quantity=group.tax_quantity,
                decision_id=group.decision_id,
                decision_title=group.decision_title,
                evidence_class=self._event_quote_evidence_class(group),
                stable_quote_evidence=self._has_stable_quote_evidence(group),
                sample_ref_count=len(group.sample_event_refs),
                missing_sample_refs=not group.sample_event_refs,
                sample_event_refs=group.sample_event_refs[:5],
                event_sources=group.event_sources,
                quote_assets=group.quote_assets,
                reason=group.reason,
                recommended_action=self._event_quote_recommended_action(group),
                evidence_ref=group.evidence_ref,
            )
            for group in groups[: max(1, limit)]
        ]
        return PriceQualityEventQuoteEvidenceReport(
            generated_at=datetime.now(timezone.utc),
            groups_count=len(groups),
            tax_relevant_groups_count=sum(1 for group in groups if group.tax_lines_count > 0),
            total_tax_lines_count=sum(group.tax_lines_count for group in groups),
            stable_quote_groups_count=sum(1 for group in groups if self._has_stable_quote_evidence(group)),
            missing_sample_ref_groups_count=sum(1 for group in groups if not group.sample_event_refs),
            assets=sorted({group.asset for group in groups}),
            groups=items,
            methodology=(
                "Read-only Arbeitsliste fuer verbleibende Event-Quote-"
                "Evidenzgruppen. Der Endpunkt klassifiziert Restgruppen nach "
                "Quote-Evidenz und Source-Typ, schreibt keine Preiszeilen und "
                "aendert keine FIFO- oder Steuerdaten."
            ),
        )

    def closure_candidates(self, limit: int = 120) -> PriceQualityClosureCandidateReport:
        manual = self.manual_review_report(limit=10_000)
        groups = sorted(
            manual.groups,
            key=lambda group: (
                not self._closure_candidate_can_auto_close(group)[2],
                -group.tax_lines_count,
                group.review_bucket,
                group.asset,
                group.year,
                group.source,
            ),
        )
        items: list[PriceQualityClosureCandidate] = []
        for group in groups[: max(1, limit)]:
            closure_class, decision_status, can_auto_close, recommended_action = (
                self._closure_candidate_can_auto_close(group)
            )
            items.append(
                PriceQualityClosureCandidate(
                    scope=group.scope,
                    asset=group.asset,
                    year=group.year,
                    source=group.source,
                    review_bucket=group.review_bucket,
                    closure_class=closure_class,
                    recommended_decision_status=decision_status,
                    can_auto_close_with_evidence=can_auto_close,
                    price_count=group.price_count,
                    tax_lines_count=group.tax_lines_count,
                    tax_quantity=group.tax_quantity,
                    event_sources=group.event_sources,
                    quote_assets=group.quote_assets,
                    sample_event_refs=group.sample_event_refs,
                    reason=group.reason,
                    evidence_ref=group.evidence_ref,
                    recommended_action=recommended_action,
                )
            )
        all_classified = [self._closure_candidate_can_auto_close(group) for group in manual.groups]
        return PriceQualityClosureCandidateReport(
            generated_at=datetime.now(timezone.utc),
            groups_count=len(manual.groups),
            tax_relevant_groups_count=sum(1 for group in manual.groups if group.tax_lines_count > 0),
            auto_close_candidates_count=sum(1 for item in all_classified if item[2]),
            stablecoin_fx_replacement_candidates_count=sum(
                1 for item in all_classified if item[0] == "stablecoin_fx_replacement_candidate"
            ),
            external_price_required_candidates_count=sum(
                1 for item in all_classified if item[0] == "external_price_required_candidate"
            ),
            manual_review_required_count=sum(
                1 for item in all_classified if item[0] == "manual_review_required"
            ),
            total_tax_lines_count=sum(group.tax_lines_count for group in manual.groups),
            groups=items,
            methodology=(
                "Read-only Closure-Kandidatenliste fuer PriceQuality-Manual-Gruppen. "
                "Sie schreibt keine Review-Decisions und aendert keine Preis-, FIFO- "
                "oder Steuerdaten. Auto-Close-Kandidaten sind nur Gruppen mit klarer "
                "stabiler Event-Quote-Evidenz; Stablecoin-FX-Gruppen werden als "
                "FX-Replacement-Kandidaten markiert, nicht als akzeptierte Event-Quote."
            ),
        )

    def _stablecoin_fx_replacement_days(
        self,
        group: PriceQualityManualReviewItem,
        *,
        limit: int,
    ) -> list[PriceQualityStablecoinFxReplacementDay]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                with derived_days as (
                    select
                        upper(asset) as asset,
                        date_part('year', priced_at)::integer as year,
                        cast(priced_at as date) as price_date,
                        source,
                        count(*)::integer as derived_price_count,
                        min(price_eur) as min_derived_price_eur,
                        max(price_eur) as max_derived_price_eur
                    from price_ledger
                    where upper(asset) = ?
                      and date_part('year', priced_at)::integer = ?
                      and source = ?
                    group by upper(asset), date_part('year', priced_at), cast(priced_at as date), source
                ),
                alternatives as (
                    select
                        upper(asset) as asset,
                        cast(priced_at as date) as price_date,
                        source,
                        price_eur,
                        priced_at,
                        case
                          when lower(source) like '%usd_eur%'
                            or lower(source) like '%fx%'
                            or lower(source) like '%ecb%'
                          then 1 else 0
                        end as is_fx_backed,
                        case
                          when lower(source) like '%coingecko%'
                            or lower(source) like '%market%'
                            or lower(source) like '%manual%'
                          then 1 else 0
                        end as is_market
                    from price_ledger
                    where upper(asset) = ?
                      and date_part('year', priced_at)::integer = ?
                      and source <> ?
                      and price_eur > 0
                ),
                alternative_summary as (
                    select
                        asset,
                        price_date,
                        count(*)::integer as same_day_alternative_count,
                        sum(is_fx_backed)::integer as fx_backed_alternative_count,
                        sum(is_market)::integer as market_alternative_count
                    from alternatives
                    group by asset, price_date
                ),
                selected_alternative as (
                    select *
                    from (
                        select
                            asset,
                            price_date,
                            price_eur,
                            source,
                            priced_at,
                            row_number() over (
                                partition by asset, price_date
                                order by is_fx_backed desc, is_market desc, priced_at desc, source
                            ) as rn
                        from alternatives
                    )
                    where rn = 1
                ),
                tax_by_year as (
                    select
                        upper(asset) as asset,
                        date_part('year', disposed_at)::integer as year,
                        count(*)::integer as tax_lines_count,
                        sum(abs(quantity)) as tax_quantity
                    from tax_lines
                    where upper(asset) = ?
                      and date_part('year', disposed_at)::integer = ?
                    group by upper(asset), date_part('year', disposed_at)
                ),
                refs as (
                    select
                        upper(asset) as asset,
                        cast(event_time as date) as price_date,
                        list(source_ref order by event_time, event_id) as source_refs
                    from canonical_events
                    where upper(asset) = ?
                      and date_part('year', event_time)::integer = ?
                      and source_ref is not null
                    group by upper(asset), cast(event_time as date)
                )
                select
                    d.asset,
                    d.year,
                    d.price_date,
                    d.source,
                    d.derived_price_count,
                    d.min_derived_price_eur,
                    d.max_derived_price_eur,
                    coalesce(a.same_day_alternative_count, 0) as same_day_alternative_count,
                    coalesce(a.fx_backed_alternative_count, 0) as fx_backed_alternative_count,
                    coalesce(a.market_alternative_count, 0) as market_alternative_count,
                    s.price_eur as selected_price_eur,
                    s.source as selected_source,
                    s.priced_at as selected_priced_at,
                    coalesce(t.tax_lines_count, 0) as tax_lines_count,
                    coalesce(t.tax_quantity, 0) as tax_quantity,
                    coalesce(r.source_refs, []) as source_refs
                from derived_days d
                left join alternative_summary a
                  on a.asset = d.asset and a.price_date = d.price_date
                left join selected_alternative s
                  on s.asset = d.asset and s.price_date = d.price_date
                left join tax_by_year t
                  on t.asset = d.asset and t.year = d.year
                left join refs r
                  on r.asset = d.asset and r.price_date = d.price_date
                order by
                    case when coalesce(a.fx_backed_alternative_count, 0) > 0 then 2
                         when coalesce(a.same_day_alternative_count, 0) > 0 then 1
                         else 0
                    end,
                    d.price_date,
                    d.asset
                limit ?
                """,
                [
                    group.asset,
                    group.year,
                    group.source,
                    group.asset,
                    group.year,
                    group.source,
                    group.asset,
                    group.year,
                    group.asset,
                    group.year,
                    limit,
                ],
            ).fetchall()

        days: list[PriceQualityStablecoinFxReplacementDay] = []
        for row in rows:
            replacement_status = self._stablecoin_fx_replacement_status(
                fx_backed_count=int(row[8] or 0),
                market_count=int(row[9] or 0),
                alternative_count=int(row[7] or 0),
            )
            days.append(
                PriceQualityStablecoinFxReplacementDay(
                    asset=row[0],
                    year=row[1],
                    price_date=row[2],
                    source=row[3],
                    derived_price_count=row[4],
                    min_derived_price_eur=row[5],
                    max_derived_price_eur=row[6],
                    replacement_status=replacement_status,
                    same_day_alternative_count=row[7],
                    fx_backed_alternative_count=row[8],
                    market_alternative_count=row[9],
                    selected_alternative_price_eur=row[10],
                    selected_alternative_source=row[11],
                    selected_alternative_priced_at=row[12],
                    tax_lines_count=row[13],
                    tax_quantity=row[14],
                    sample_event_refs=list(row[15] or [])[:5],
                    recommended_action=self._stablecoin_fx_replacement_day_action(replacement_status),
                )
            )
        return days

    def _manual_review_sample_contexts(
        self,
        groups: list[PriceQualityGroup],
        per_group_limit: int = 12,
    ) -> dict[str, list[PriceQualityPriceSample]]:
        if not groups:
            return {}
        assets = sorted({group.asset for group in groups})
        years = sorted({group.year for group in groups})
        sources = sorted({group.source for group in groups})
        wanted = {
            (group.asset, group.year, group.source): group.scope
            for group in groups
        }
        result: dict[str, list[PriceQualityPriceSample]] = {
            group.scope: [] for group in groups
        }
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    p.asset,
                    p.price_eur,
                    p.priced_at,
                    p.source,
                    p.confidence,
                    e.event_id,
                    e.source as event_source,
                    e.event_type,
                    e.asset as event_asset,
                    e.quantity as event_quantity,
                    e.quote_asset,
                    e.quote_quantity,
                    e.source_ref,
                    e.raw_object_id
                from price_ledger p
                left join canonical_events e
                  on upper(e.asset) = upper(p.asset)
                 and e.event_time = p.priced_at
                where upper(p.asset) in (select unnest(?))
                  and date_part('year', p.priced_at)::integer in (select unnest(?))
                  and p.source in (select unnest(?))
                order by upper(p.asset), date_part('year', p.priced_at)::integer, p.source,
                         p.priced_at, p.price_id, e.event_id
                """,
                [assets, years, sources],
            ).fetchall()
        for row in rows:
            key = (str(row[0]).upper(), int(row[2].year), str(row[3]))
            scope = wanted.get(key)
            if scope is None or len(result[scope]) >= per_group_limit:
                continue
            result[scope].append(
                PriceQualityPriceSample(
                    asset=row[0],
                    price_eur=row[1],
                    priced_at=row[2],
                    source=row[3],
                    confidence=row[4],
                    event_id=row[5],
                    event_source=row[6],
                    event_type=row[7],
                    event_asset=row[8],
                    event_quantity=row[9],
                    quote_asset=row[10],
                    quote_quantity=row[11],
                    source_ref=row[12],
                    raw_object_id=row[13],
                )
            )
        return result

    def _groups(self, limit: int) -> list[PriceQualityGroup]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                with price_groups as (
                    select
                        upper(asset) as asset,
                        date_part('year', priced_at)::integer as year,
                        source,
                        count(*)::integer as price_count,
                        sum(case when confidence < 1.0 then 1 else 0 end)::integer as low_confidence_count,
                        sum(case when lower(source) like '%proxy%' or lower(source) like '%derived%' then 1 else 0 end)::integer as proxy_count,
                        sum(case when price_eur <= 0 then 1 else 0 end)::integer as zero_or_negative_count,
                        min(confidence) as min_confidence,
                        avg(confidence) as avg_confidence,
                        min(priced_at) as first_priced_at,
                        max(priced_at) as last_priced_at
                    from price_ledger
                    group by upper(asset), date_part('year', priced_at), source
                ),
                tax_by_asset_year as (
                    select
                        upper(asset) as asset,
                        date_part('year', disposed_at)::integer as year,
                        count(*)::integer as tax_lines_count,
                        sum(abs(quantity)) as tax_quantity
                    from tax_lines
                    group by upper(asset), date_part('year', disposed_at)
                )
                select
                    p.asset,
                    p.year,
                    p.source,
                    p.price_count,
                    p.low_confidence_count,
                    p.proxy_count,
                    p.zero_or_negative_count,
                    p.min_confidence,
                    p.avg_confidence,
                    p.first_priced_at,
                    p.last_priced_at,
                    coalesce(t.tax_lines_count, 0) as tax_lines_count,
                    coalesce(t.tax_quantity, 0) as tax_quantity
                from price_groups p
                left join tax_by_asset_year t
                  on t.asset = p.asset and t.year = p.year
                where p.low_confidence_count > 0
                   or p.proxy_count > 0
                   or p.zero_or_negative_count > 0
                order by
                    case
                      when coalesce(t.tax_lines_count, 0) > 0 then 0
                      when p.zero_or_negative_count > 0 then 1
                      else 2
                    end,
                    p.price_count desc,
                    p.asset,
                    p.year,
                    p.source
                limit ?
                """,
                [limit],
            ).fetchall()
        return [self._group_from_row(row) for row in rows]

    def _single_group(self, *, asset: str, year: int, source: str) -> PriceQualityGroup | None:
        with self.store.connect() as con:
            row = con.execute(
                """
                with price_groups as (
                    select
                        upper(asset) as asset,
                        date_part('year', priced_at)::integer as year,
                        source,
                        count(*)::integer as price_count,
                        sum(case when confidence < 1.0 then 1 else 0 end)::integer as low_confidence_count,
                        sum(case when lower(source) like '%proxy%' or lower(source) like '%derived%' then 1 else 0 end)::integer as proxy_count,
                        sum(case when price_eur <= 0 then 1 else 0 end)::integer as zero_or_negative_count,
                        min(confidence) as min_confidence,
                        avg(confidence) as avg_confidence,
                        min(priced_at) as first_priced_at,
                        max(priced_at) as last_priced_at
                    from price_ledger
                    where upper(asset) = ? and date_part('year', priced_at) = ? and source = ?
                    group by upper(asset), date_part('year', priced_at), source
                ),
                tax_by_asset_year as (
                    select
                        upper(asset) as asset,
                        date_part('year', disposed_at)::integer as year,
                        count(*)::integer as tax_lines_count,
                        sum(abs(quantity)) as tax_quantity
                    from tax_lines
                    where upper(asset) = ? and date_part('year', disposed_at) = ?
                    group by upper(asset), date_part('year', disposed_at)
                )
                select
                    p.asset,
                    p.year,
                    p.source,
                    p.price_count,
                    p.low_confidence_count,
                    p.proxy_count,
                    p.zero_or_negative_count,
                    p.min_confidence,
                    p.avg_confidence,
                    p.first_priced_at,
                    p.last_priced_at,
                    coalesce(t.tax_lines_count, 0) as tax_lines_count,
                    coalesce(t.tax_quantity, 0) as tax_quantity
                from price_groups p
                left join tax_by_asset_year t
                  on t.asset = p.asset and t.year = p.year
                """,
                [asset, year, source, asset, year],
            ).fetchone()
        return self._group_from_row(row) if row is not None else None

    def _price_samples(
        self,
        *,
        asset: str,
        year: int,
        source: str,
        limit: int,
    ) -> list[PriceQualityPriceSample]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    p.asset,
                    p.price_eur,
                    p.priced_at,
                    p.source,
                    p.confidence,
                    e.event_id,
                    e.source as event_source,
                    e.event_type,
                    e.asset as event_asset,
                    e.quantity as event_quantity,
                    e.quote_asset,
                    e.quote_quantity,
                    e.source_ref,
                    e.raw_object_id
                from price_ledger p
                left join canonical_events e
                  on upper(e.asset) = upper(p.asset)
                 and e.event_time = p.priced_at
                where upper(p.asset) = ?
                  and date_part('year', p.priced_at) = ?
                  and p.source = ?
                order by p.priced_at, p.price_id, e.event_id
                limit ?
                """,
                [asset, year, source, limit],
            ).fetchall()
        return [
            PriceQualityPriceSample(
                asset=row[0],
                price_eur=row[1],
                priced_at=row[2],
                source=row[3],
                confidence=row[4],
                event_id=row[5],
                event_source=row[6],
                event_type=row[7],
                event_asset=row[8],
                event_quantity=row[9],
                quote_asset=row[10],
                quote_quantity=row[11],
                source_ref=row[12],
                raw_object_id=row[13],
            )
            for row in rows
        ]

    def _tax_line_samples(self, *, asset: str, year: int, limit: int) -> list[PriceQualityTaxSample]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    tax_line_id,
                    asset,
                    disposed_at,
                    quantity,
                    acquisition_cost_eur,
                    disposal_proceeds_eur,
                    gain_loss_eur,
                    holding_days,
                    source_event_id,
                    lot_id
                from tax_lines
                where upper(asset) = ? and date_part('year', disposed_at) = ?
                order by disposed_at, tax_line_id
                limit ?
                """,
                [asset, year, limit],
            ).fetchall()
        return [
            PriceQualityTaxSample(
                tax_line_id=row[0],
                asset=row[1],
                disposed_at=row[2],
                quantity=row[3],
                acquisition_cost_eur=row[4],
                disposal_proceeds_eur=row[5],
                gain_loss_eur=row[6],
                holding_days=row[7],
                source_event_id=row[8],
                lot_id=row[9],
            )
            for row in rows
        ]

    def _source_summaries(self) -> list[PriceQualitySourceSummary]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                with price_source as (
                    select
                        source,
                        count(*)::integer as price_count,
                        count(distinct upper(asset))::integer as assets_count,
                        count(distinct date_part('year', priced_at))::integer as years_count,
                        sum(case when confidence < 1.0 then 1 else 0 end)::integer as low_confidence_count,
                        sum(case when lower(source) like '%proxy%' or lower(source) like '%derived%' then 1 else 0 end)::integer as proxy_count
                    from price_ledger
                    group by source
                ),
                tax_assets as (
                    select distinct upper(asset) as asset from tax_lines
                ),
                source_tax as (
                    select p.source, count(*)::integer as tax_lines_count
                    from price_ledger p
                    join tax_assets t on t.asset = upper(p.asset)
                    group by p.source
                )
                select
                    p.source,
                    p.price_count,
                    p.assets_count,
                    p.years_count,
                    p.low_confidence_count,
                    p.proxy_count,
                    coalesce(t.tax_lines_count, 0) as tax_lines_count
                from price_source p
                left join source_tax t on t.source = p.source
                where p.low_confidence_count > 0 or p.proxy_count > 0
                order by p.price_count desc, p.source
                limit 80
                """
            ).fetchall()
        return [
            PriceQualitySourceSummary(
                source=row[0],
                price_count=row[1],
                assets_count=row[2],
                years_count=row[3],
                low_confidence_count=row[4],
                proxy_count=row[5],
                tax_lines_count=row[6],
                risk_level=self._risk_level(
                    low_confidence_count=row[4],
                    proxy_count=row[5],
                    zero_or_negative_count=0,
                    tax_lines_count=row[6],
                ),
            )
            for row in rows
        ]

    def _latest_assets(self) -> list[PriceQualityLatestAsset]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select asset, price_eur, priced_at, source, confidence
                from (
                    select
                        upper(asset) as asset,
                        price_eur,
                        priced_at,
                        source,
                        confidence,
                        row_number() over (
                            partition by upper(asset)
                            order by priced_at desc, created_at desc, price_id desc
                        ) as rn
                    from price_ledger
                )
                where rn = 1
                order by
                    case
                      when confidence < 1.0 or lower(source) like '%proxy%' or lower(source) like '%derived%' or price_eur <= 0 then 0
                      else 1
                    end,
                    asset
                limit 80
                """
            ).fetchall()
        latest: list[PriceQualityLatestAsset] = []
        for row in rows:
            low = 1 if row[4] < Decimal("1.0") else 0
            proxy = 1 if self._is_proxy_source(row[3]) else 0
            invalid = 1 if row[1] <= 0 else 0
            status = self._status(low, proxy, invalid)
            latest.append(
                PriceQualityLatestAsset(
                    asset=row[0],
                    price_eur=row[1],
                    priced_at=row[2],
                    source=row[3],
                    confidence=row[4],
                    status=status,
                    risk_level=self._risk_level(
                        low_confidence_count=low,
                        proxy_count=proxy,
                        zero_or_negative_count=invalid,
                        tax_lines_count=0,
                    ),
                )
            )
        return latest

    def _totals(self) -> dict[str, int]:
        with self.store.connect() as con:
            row = con.execute(
                """
                select
                    count(*)::integer as price_points_count,
                    count(distinct upper(asset))::integer as assets_count,
                    count(distinct source)::integer as sources_count,
                    sum(case when confidence < 1.0 then 1 else 0 end)::integer as low_confidence_count,
                    sum(case when lower(source) like '%proxy%' or lower(source) like '%derived%' then 1 else 0 end)::integer as proxy_count,
                    sum(case when price_eur <= 0 then 1 else 0 end)::integer as zero_or_negative_count
                from price_ledger
                """
            ).fetchone()
        return {
            "price_points_count": int(row[0] or 0),
            "assets_count": int(row[1] or 0),
            "sources_count": int(row[2] or 0),
            "low_confidence_count": int(row[3] or 0),
            "proxy_count": int(row[4] or 0),
            "zero_or_negative_count": int(row[5] or 0),
        }

    def _issue_group_counts(self) -> dict[str, int]:
        with self.store.connect() as con:
            row = con.execute(
                """
                with price_groups as (
                    select
                        upper(asset) as asset,
                        date_part('year', priced_at)::integer as year,
                        source,
                        sum(case when confidence < 1.0 then 1 else 0 end)::integer as low_confidence_count,
                        sum(case when lower(source) like '%proxy%' or lower(source) like '%derived%' then 1 else 0 end)::integer as proxy_count,
                        sum(case when price_eur <= 0 then 1 else 0 end)::integer as zero_or_negative_count
                    from price_ledger
                    group by upper(asset), date_part('year', priced_at), source
                ),
                tax_by_asset_year as (
                    select
                        upper(asset) as asset,
                        date_part('year', disposed_at)::integer as year,
                        count(*)::integer as tax_lines_count
                    from tax_lines
                    group by upper(asset), date_part('year', disposed_at)
                ),
                issue_groups as (
                    select
                        p.low_confidence_count,
                        p.proxy_count,
                        p.zero_or_negative_count,
                        coalesce(t.tax_lines_count, 0) as tax_lines_count
                    from price_groups p
                    left join tax_by_asset_year t
                      on t.asset = p.asset and t.year = p.year
                    where p.low_confidence_count > 0
                       or p.proxy_count > 0
                       or p.zero_or_negative_count > 0
                )
                select
                    count(*)::integer as issue_groups_count,
                    sum(case when tax_lines_count > 0 then 1 else 0 end)::integer as tax_relevant_issue_groups,
                    sum(case when zero_or_negative_count > 0 or tax_lines_count > 0 then 1 else 0 end)::integer as high_risk_groups,
                    sum(case when zero_or_negative_count = 0 and tax_lines_count = 0 then 1 else 0 end)::integer as medium_risk_groups,
                    0::integer as low_risk_groups
                from issue_groups
                """
            ).fetchone()
        return {
            "issue_groups_count": int(row[0] or 0),
            "tax_relevant_issue_groups": int(row[1] or 0),
            "high_risk_groups": int(row[2] or 0),
            "medium_risk_groups": int(row[3] or 0),
            "low_risk_groups": int(row[4] or 0),
        }

    def _group_from_row(self, row: tuple) -> PriceQualityGroup:
        status = self._status(row[4], row[5], row[6])
        risk_level = self._risk_level(
            low_confidence_count=row[4],
            proxy_count=row[5],
            zero_or_negative_count=row[6],
            tax_lines_count=row[11],
        )
        return PriceQualityGroup(
            asset=row[0],
            year=row[1],
            source=row[2],
            status=status,
            risk_level=risk_level,
            price_count=row[3],
            low_confidence_count=row[4],
            proxy_count=row[5],
            zero_or_negative_count=row[6],
            min_confidence=row[7],
            avg_confidence=row[8],
            first_priced_at=row[9],
            last_priced_at=row[10],
            tax_lines_count=row[11],
            tax_quantity=row[12],
            evidence=(
                f"{row[3]} Preiszeile(n), {row[4]} low-confidence, "
                f"{row[5]} proxy/derived, {row[11]} Tax-Line(s) im Asset/Jahr."
            ),
            next_action=self._next_action(status=status, tax_lines_count=row[11]),
            scope=self.issue_scope(asset=row[0], year=row[1], source=row[2]),
        )

    @staticmethod
    def _status(low_confidence_count: int, proxy_count: int, zero_or_negative_count: int) -> str:
        parts: list[str] = []
        if zero_or_negative_count:
            parts.append("invalid_price")
        if low_confidence_count:
            parts.append("low_confidence")
        if proxy_count:
            parts.append("proxy_or_derived")
        return "+".join(parts) if parts else "ok"

    @staticmethod
    def _risk_level(
        *,
        low_confidence_count: int,
        proxy_count: int,
        zero_or_negative_count: int,
        tax_lines_count: int,
    ) -> str:
        has_issue = low_confidence_count > 0 or proxy_count > 0 or zero_or_negative_count > 0
        if zero_or_negative_count > 0 or (has_issue and tax_lines_count > 0):
            return "high"
        if has_issue:
            return "medium"
        return "low"

    @staticmethod
    def _next_action(*, status: str, tax_lines_count: int) -> str:
        if status == "ok":
            return "Keine Aktion erforderlich."
        if tax_lines_count > 0:
            return "Steuerrelevante Preisgruppe pruefen und ggf. belastbare Quelle oder Review-Entscheidung hinterlegen."
        return "Als nicht steuerrelevante Preisqualitaetswarnung beobachten oder bei Bedarf durch externe Quelle ersetzen."

    @staticmethod
    def _is_proxy_source(source: str) -> bool:
        normalized = source.lower()
        return "proxy" in normalized or "derived" in normalized

    @staticmethod
    def _manual_review_reason(samples: list[PriceQualityPriceSample]) -> str:
        event_types = {sample.event_type for sample in samples if sample.event_type}
        event_sources = {sample.event_source for sample in samples if sample.event_source}
        quote_assets = {sample.quote_asset for sample in samples if sample.quote_asset}
        has_zero = any(
            str(sample.event_quantity) in {"0E-18", "0", "0.000000000000000000"}
            for sample in samples
        )
        has_missing_quote = any(
            sample.event_type == "trade" and not sample.quote_asset
            for sample in samples
        )
        reasons: list[str] = []
        if "unknown" in event_types:
            reasons.append("unknown Events")
        if has_zero:
            reasons.append("Zero-Quantity-Samples")
        if has_missing_quote:
            reasons.append("fehlende quote_asset-Felder")
        if len(quote_assets) > 1:
            reasons.append("gemischte Quote-Assets: " + ", ".join(sorted(quote_assets)))
        if len(event_sources) > 1:
            reasons.append("gemischte Quellen: " + ", ".join(sorted(event_sources)))
        if not reasons:
            reasons.append("keine eindeutige direkte stabile Quote-Evidenz")
        return "; ".join(reasons)

    @staticmethod
    def _manual_review_next_action(
        group: PriceQualityGroup,
        samples: list[PriceQualityPriceSample],
    ) -> str:
        quote_assets = {sample.quote_asset for sample in samples if sample.quote_asset}
        event_sources = {sample.event_source for sample in samples if sample.event_source}
        if group.asset in {"USDT", "USDC", "BUSD", "EUR"}:
            return "Stablecoin-/Fiat-FX-Behandlung pruefen und ggf. EUR/FX-Preisquelle statt Event-Quote verwenden."
        if "binance" in event_sources:
            return "Binance Raw-/Normalizer-Kette fuer fehlende Quotes oder unknown/Zero-Quantity-Samples pruefen."
        if "solana_rpc" in event_sources:
            return "Solana-RPC Trade-Samples gegen Solscan/Signaturdetails und Quote-Token-Mengen pruefen."
        if len(quote_assets) > 1 or len(event_sources) > 1:
            return "Quellen-/Quote-Mix auf einzelne belegbare Untergruppen trennen oder externe Preisquelle nutzen."
        return "Drilldown-Samples pruefen und entweder Event-Quote akzeptieren oder externe Preisquelle hinterlegen."

    @staticmethod
    def _manual_review_bucket(
        group: PriceQualityGroup,
        samples: list[PriceQualityPriceSample],
    ) -> str:
        quote_assets = {sample.quote_asset for sample in samples if sample.quote_asset}
        event_sources = {sample.event_source for sample in samples if sample.event_source}
        event_types = {sample.event_type for sample in samples if sample.event_type}
        has_zero = any(
            str(sample.event_quantity) in {"0E-18", "0", "0.000000000000000000"}
            for sample in samples
        )
        has_missing_quote = any(
            sample.event_type == "trade" and not sample.quote_asset
            for sample in samples
        )
        if group.asset in STABLECOIN_FX_ASSETS:
            return "stablecoin_fx_review"
        if "solana_rpc" in event_sources:
            return "solscan_signature_review"
        if "binance" in event_sources and (has_missing_quote or has_zero or "unknown" in event_types):
            return "binance_normalizer_review"
        if len(quote_assets) > 1 or len(event_sources) > 1:
            return "mixed_quote_source_review"
        return "event_quote_evidence_review"

    @staticmethod
    def _stablecoin_expected_price_basis(asset: str) -> str:
        if asset == "EUR":
            return "fiat:EUR=1"
        return "USD/EUR-FX oder belegter EUR-Stablecoin-Marktpreis"

    @staticmethod
    def _stablecoin_recommended_action(asset: str, tax_lines_count: int) -> str:
        if asset == "EUR":
            return "EUR-Preiszeilen als Fiat-Identitaet pruefen; steuerrelevante Derived-Quotes nicht als Marktpreis akzeptieren."
        if tax_lines_count > 0:
            return "Historische USD/EUR-FX-Evidenz beschaffen und Derived Event-Quote gegen FX-basierte EUR-Bewertung pruefen."
        return "Keine steuerliche Prioritaet; Derived Event-Quote als Diagnose sichtbar lassen oder spaeter bereinigen."

    @staticmethod
    def _split_signature_refs(refs: list[str]) -> tuple[list[str], list[str]]:
        signatures: list[str] = []
        other: list[str] = []
        seen_signatures: set[str] = set()
        seen_other: set[str] = set()
        for ref in refs:
            normalized = ref.strip().strip("'")
            if not normalized:
                continue
            is_signature = (
                len(normalized) >= 40
                and normalized.replace("_", "").replace("-", "").isalnum()
                and not normalized.startswith("s_")
            )
            if is_signature:
                if normalized not in seen_signatures:
                    signatures.append(normalized)
                    seen_signatures.add(normalized)
            elif normalized not in seen_other:
                other.append(normalized)
                seen_other.add(normalized)
        return signatures, other

    @staticmethod
    def _solscan_recommended_action(
        group: PriceQualityManualReviewItem,
        signature_refs: list[str],
    ) -> str:
        stable_quotes = {"USDT", "USDC", "EUR", "BUSD"}
        quote_assets = set(group.quote_assets)
        if not signature_refs:
            return "Keine eindeutige Onchain-Signatur im Sample; Raw-/Source-Ref-Mapping pruefen und Gruppe nicht automatisch akzeptieren."
        if quote_assets & stable_quotes and len(quote_assets - stable_quotes) == 0:
            return "Signaturen gegen Solscan-Details pruefen; stabile Quote-Assets koennen nach Belegabgleich als Event-Quote-Evidenz dienen."
        if group.tax_lines_count > 0:
            return "Signaturen gegen Solscan-Details pruefen und Quote-Token/Mengen je Swap belegen; bei gemischten Quotes externe Preisquelle bevorzugen."
        return "Nicht steuerpriorisiert; Signaturen fuer spaetere Plausibilitaet sichern."

    @staticmethod
    def _binance_normalizer_recommended_action(group: PriceQualityManualReviewItem) -> str:
        if "fehlende quote_asset-Felder" in group.reason:
            return "Binance Raw-Zeilen und Normalizer-Mapping fuer Pair/Quote-Felder pruefen; Derived-Quote nicht automatisch akzeptieren."
        if "unknown Events" in group.reason or "Zero-Quantity-Samples" in group.reason:
            return "Binance Event-Typ-/Mengen-Normalisierung pruefen; Zero-Quantity-Samples aus Preisableitung ausschliessen oder belegen."
        if group.tax_lines_count > 0:
            return "Binance Drilldown gegen Raw-Import und externe Preisquelle pruefen."
        return "Nicht steuerpriorisiert; Normalizer-Signal dokumentiert lassen."

    @staticmethod
    def _has_stable_quote_evidence(group: PriceQualityManualReviewItem) -> bool:
        stable_quotes = {"USDT", "USDC", "EUR", "BUSD"}
        quote_assets = set(group.quote_assets)
        return bool(quote_assets) and quote_assets <= stable_quotes

    @classmethod
    def _event_quote_evidence_class(cls, group: PriceQualityManualReviewItem) -> str:
        if group.source.startswith("derived:blockpit_solana_quote"):
            return "blockpit_solana_derived_quote"
        if cls._has_stable_quote_evidence(group):
            return "stable_quote_sample"
        if group.quote_assets:
            return "non_stable_quote_sample"
        return "missing_quote_sample"

    @classmethod
    def _event_quote_recommended_action(cls, group: PriceQualityManualReviewItem) -> str:
        evidence_class = cls._event_quote_evidence_class(group)
        if evidence_class == "blockpit_solana_derived_quote":
            return "Blockpit-Solana-Quote-Ableitung gegen Originalexport und externe Preisquelle pruefen."
        if evidence_class == "stable_quote_sample":
            return "Drilldown-Sample mit stabiler Quote pruefen; bei plausibler Menge kann Event-Quote fachlich akzeptiert werden."
        if evidence_class == "non_stable_quote_sample":
            return "Nicht-stabile Quote gegen externe historische Preisquelle pruefen; Event-Quote nicht automatisch akzeptieren."
        return "Keine Quote-/Ref-Evidenz im Sample; externe Preisquelle oder Raw-Drilldown benoetigt."

    @classmethod
    def _closure_candidate_can_auto_close(
        cls,
        group: PriceQualityManualReviewItem,
    ) -> tuple[PriceQualityClosureClass, PriceQualityDecisionStatus, bool, str]:
        if group.review_bucket == "stablecoin_fx_review":
            if group.asset == "EUR" and group.tax_lines_count == 0:
                return (
                    "accepted_event_quote_candidate",
                    "accepted_event_quote",
                    True,
                    "EUR-Fiat-Identitaet als nicht steuerrelevante Preisqualitaetsgruppe dokumentieren.",
                )
            return (
                "stablecoin_fx_replacement_candidate",
                "external_price_required",
                False,
                "Stablecoin-Event-Quote nicht akzeptieren; historische USD/EUR-FX-Preisanker oder FX-Belege verwenden.",
            )
        if group.review_bucket == "event_quote_evidence_review":
            if cls._has_stable_quote_evidence(group) and group.sample_event_refs:
                return (
                    "accepted_event_quote_candidate",
                    "accepted_event_quote",
                    True,
                    "Stabile Quote-Samples und Source-Refs vorhanden; Event-Quote kann nach Belegablage akzeptiert werden.",
                )
            if cls._event_quote_evidence_class(group) == "blockpit_solana_derived_quote":
                return (
                    "external_price_required_candidate",
                    "external_price_required",
                    False,
                    "Blockpit-Solana-Quote-Ableitung gegen Originalexport oder externe Tagespreise absichern.",
                )
        if group.review_bucket == "solscan_signature_review":
            signature_refs, _other = cls._split_signature_refs(group.sample_event_refs)
            if signature_refs and cls._has_stable_quote_evidence(group):
                return (
                    "accepted_event_quote_candidate",
                    "accepted_event_quote",
                    True,
                    "Onchain-Signaturen und stabile Quote vorhanden; nach Solscan-Belegablage als Event-Quote akzeptierbar.",
                )
        if group.review_bucket in {"binance_normalizer_review", "mixed_quote_source_review"}:
            return (
                "manual_review_required",
                "manual_review_required",
                False,
                "Normalizer-/Quote-Mix bleibt manuell zu pruefen; keine automatische Closure.",
            )
        return (
            "manual_review_required",
            "manual_review_required",
            False,
            "Manuelle Detailpruefung oder externe Preisquelle erforderlich.",
        )

    @staticmethod
    def _stablecoin_fx_replacement_status(
        *,
        fx_backed_count: int,
        market_count: int,
        alternative_count: int,
    ) -> str:
        if fx_backed_count > 0:
            return "fx_backed_available"
        if market_count > 0 or alternative_count > 0:
            return "market_price_available"
        return "replacement_needed"

    @staticmethod
    def _stablecoin_fx_replacement_day_action(status: str) -> str:
        if status == "fx_backed_available":
            return "Gleichdatierte FX-/USD_EUR-/ECB-Quelle vorhanden; Replacement fachlich pruefbar."
        if status == "market_price_available":
            return "Gleichdatierte Marktpreisquelle vorhanden; fuer Finanzamt FX-/Preisbeleg archivieren."
        return "Kein gleichdatierter Ersatzpreis vorhanden; USD/EUR-FX- oder belastbaren Stablecoin-EUR-Preisanker beschaffen."

    @staticmethod
    def _stablecoin_fx_replacement_group_action(
        *,
        days_needing_replacement: int,
        fx_backed_days: int,
        market_days: int,
    ) -> str:
        if days_needing_replacement == 0 and fx_backed_days > 0:
            return "Alle angezeigten Tage haben FX-Ersatz; nach Belegpruefung koennen Derived-Event-Quotes ersetzt werden."
        if days_needing_replacement == 0 and market_days > 0:
            return "Alle angezeigten Tage haben Marktpreis-Ersatz; FX-Beleglage fuer Stablecoin sauber dokumentieren."
        return "Offene Tage benoetigen Stablecoin-FX-Replacement; vor Review-Closure keine automatische Akzeptanz der Event-Quotes."

    @staticmethod
    def _stablecoin_fx_replacement_impact_action(status: str) -> str:
        if status == "ready":
            return "Replacement-Kandidat vorhanden; Delta pruefen und danach kontrolliert anwenden oder als Review-Evidenz dokumentieren."
        return "Kein gleichdatierter Replacement-Preis vorhanden; vor Anwendung Tages-FX-/Stablecoin-EUR-Preisanker beschaffen."

    @classmethod
    def stablecoin_fx_tax_impact_scope(cls, *, asset: str, year: int, source: str) -> str:
        return f"stablecoin_fx_replacement:asset:{asset.upper()}:year:{year}:source:{source}"

    def _stablecoin_fx_tax_impact_decisions_by_scope(self) -> dict[str, list[Any]]:
        result: dict[str, list[Any]] = defaultdict(list)
        for decision in self.store.list_review_decisions():
            if decision.decision_type != "stablecoin_fx_replacement_tax_impact":
                continue
            result[decision.scope].append(decision)
        for decisions in result.values():
            decisions.sort(key=lambda item: item.created_at, reverse=True)
        return result

    @staticmethod
    def _stablecoin_fx_anchor_tax_impact_summary(rows: object) -> dict[str, object]:
        if not isinstance(rows, list):
            return {}
        total = Decimal("0")
        requiring_review = 0
        quality_only = 0
        incomplete = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            conclusion = row.get("conclusion")
            if conclusion == "replacement_changes_tax_result_review_required":
                requiring_review += 1
            elif conclusion == "no_tax_delta_replacement_is_quality_closure_only":
                quality_only += 1
            elif conclusion == "replacement_not_complete":
                incomplete += 1
            delta = row.get("delta")
            if isinstance(delta, dict):
                value = delta.get("taxable_gain_loss_eur")
                if value is not None:
                    total += Decimal(str(value))
        return {
            "groups_count": len(rows),
            "groups_requiring_review": requiring_review,
            "groups_complete_quality_only": quality_only,
            "groups_incomplete": incomplete,
            "taxable_gain_loss_delta_eur": str(total),
        }

    @staticmethod
    def _stablecoin_fx_anchor_impact_for_group(
        rows: object,
        *,
        asset: str,
        year: int,
        source: str,
    ) -> dict[str, object] | None:
        if not isinstance(rows, list):
            return None
        for row in rows:
            if not isinstance(row, dict):
                continue
            if (
                str(row.get("asset", "")).upper() == asset.upper()
                and int(row.get("year") or 0) == year
                and str(row.get("source") or "derived:event_quote") == source
            ):
                return row
        return None

    @staticmethod
    def _stablecoin_fx_anchor_decision_title(
        *,
        asset: str,
        year: int,
        action: str,
    ) -> str:
        if action == "document_delta_only":
            return f"{asset} {year} Stablecoin-FX-Anker nur dokumentiert"
        if action == "keep_existing":
            return f"{asset} {year} Stablecoin-FX-Anker verworfen"
        return f"{asset} {year} Stablecoin-FX-Anker Review-Decision"

    @classmethod
    def _stablecoin_fx_tax_impact_artifact_path(cls, *, asset: str, year: int) -> Path:
        return cls.TAX_IMPACT_ARTIFACT_DIR / f"latest_{asset.upper()}_{year}_tax_impact.json"

    @staticmethod
    def _mapping_value(value: object, key: str) -> object | None:
        if isinstance(value, dict):
            return value.get(key)
        return None

    @staticmethod
    def _optional_decimal(value: object | None) -> Decimal | None:
        if value is None:
            return None
        return Decimal(str(value))

    @staticmethod
    def _optional_int(value: object | None) -> int | None:
        if value is None:
            return None
        return int(value)

    @staticmethod
    def _parse_optional_datetime(value: object | None) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _stablecoin_fx_tax_impact_decision_options(
        conclusion: str | None,
    ) -> list[PriceQualityStablecoinFxTaxImpactDecisionOption]:
        tax_delta = conclusion == "replacement_changes_tax_result_review_required"
        return [
            PriceQualityStablecoinFxTaxImpactDecisionOption(
                action="document_delta_only",
                label="Delta dokumentieren, keine Daten aendern",
                recommended=tax_delta,
                rationale=(
                    "Geeignet, wenn die Abweichung fuer die aktuelle Abgabe nur "
                    "dokumentiert werden soll und keine Preis-/FIFO-Neuberechnung "
                    "in der Live-Datenbank erfolgen soll."
                ),
            ),
            PriceQualityStablecoinFxTaxImpactDecisionOption(
                action="keep_existing",
                label="Bestehende Bewertung beibehalten",
                recommended=not tax_delta,
                rationale=(
                    "Geeignet, wenn der Impact nicht materiell ist oder die "
                    "bestehende Berechnung als konservativer Nachweis beibehalten "
                    "werden soll."
                ),
            ),
            PriceQualityStablecoinFxTaxImpactDecisionOption(
                action="apply_replacement",
                label="Replacement separat anwenden",
                writes_prices=True,
                writes_fifo=True,
                recommended=False,
                rationale=(
                    "Nur nach gesonderter fachlicher Freigabe nutzen. Diese Option "
                    "ist hier nur dokumentiert; dieser Endpunkt schreibt keine Preise "
                    "und baut FIFO nicht neu."
                ),
            ),
        ]

    @staticmethod
    def _stablecoin_fx_tax_impact_next_action(
        *,
        artifact_found: bool,
        conclusion: str | None,
        decisions_count: int,
    ) -> str:
        if not artifact_found:
            return "Tax-Impact-Skript ausfuehren, bevor eine Review-Entscheidung dokumentiert wird."
        if decisions_count:
            return "Review-Entscheidung ist dokumentiert; Jahrespaket kann den Beleg referenzieren."
        if conclusion == "replacement_changes_tax_result_review_required":
            return "Steuerdelta vorhanden; document_delta_only, keep_existing oder separaten Apply-Pfad fachlich entscheiden."
        if conclusion == "no_tax_delta_replacement_is_quality_closure_only":
            return "Kein Steuerdelta; PriceQuality-Closure kann als Belegentscheidung vorbereitet werden."
        return "Impact-Artefakt pruefen und fachliche Entscheidung dokumentieren."

    @staticmethod
    def _stablecoin_fx_tax_impact_decision_title(
        *,
        asset: str,
        year: int,
        action: str,
    ) -> str:
        labels = {
            "document_delta_only": "Delta dokumentiert",
            "keep_existing": "Bestehende Bewertung beibehalten",
            "apply_replacement": "Replacement fachlich freigegeben",
        }
        return f"{asset.upper()} {year} Stablecoin-FX Tax Impact: {labels.get(action, action)}"

    @staticmethod
    def _count_dict(values: object) -> dict[str, int]:
        result: dict[str, int] = {}
        for value in values:
            if value is None:
                continue
            key = str(value)
            result[key] = result.get(key, 0) + 1
        return dict(sorted(result.items()))

    @staticmethod
    def issue_scope(*, asset: str, year: int, source: str) -> str:
        return f"price_quality:asset:{asset.upper()}:year:{year}:source:{source}"

    def _apply_decisions(
        self,
        groups: list[PriceQualityGroup],
        decisions: dict[str, tuple[PriceQualityDecisionStatus, str, str]],
    ) -> list[PriceQualityGroup]:
        result: list[PriceQualityGroup] = []
        for group in groups:
            decision = decisions.get(group.scope)
            if decision is None:
                result.append(group)
                continue
            result.append(
                group.model_copy(
                    update={
                        "decision_status": decision[0],
                        "decision_id": decision[1],
                        "decision_title": decision[2],
                        "next_action": self._next_action_after_decision(decision[0]),
                    }
                )
            )
        return result

    def _price_quality_decisions_by_scope(
        self,
    ) -> dict[str, tuple[PriceQualityDecisionStatus, str, str]]:
        result: dict[str, tuple[PriceQualityDecisionStatus, str, str]] = {}
        valid_statuses = {
            "accepted_event_quote",
            "external_price_required",
            "manual_review_required",
        }
        for decision in reversed(self.store.list_review_decisions()):
            if decision.decision_type != "price_quality":
                continue
            raw_status = decision.payload.get("decision_status")
            if not isinstance(raw_status, str) or raw_status not in valid_statuses:
                continue
            result[decision.scope] = (
                raw_status,  # type: ignore[assignment]
                decision.decision_id,
                decision.title,
            )
        return result

    @staticmethod
    def _next_action_after_decision(status: PriceQualityDecisionStatus) -> str:
        if status == "accepted_event_quote":
            return "Event-Quote-Bewertung fachlich akzeptiert; keine Preiszeile automatisch geaendert."
        if status == "external_price_required":
            return "Externe historische Marktpreise beschaffen und gegen Event-Quote pruefen."
        if status == "manual_review_required":
            return "Manuelle Detailpruefung mit Belegen erforderlich."
        return "Preisqualitaetsgruppe pruefen."
