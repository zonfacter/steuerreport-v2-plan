from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

import httpx

from steuerreport_v2.contracts.prices import (
    AsOfPriceGateBackfillJob,
    AsOfPriceGateBackfillRequest,
    AsOfPriceGateBackfillResult,
    AsOfPriceGateCandidate,
    AsOfPriceGateReport,
    AsOfTokenValuationDecisionRequest,
    AsOfTokenValuationDecisionResult,
    PricePointCreate,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.divorce import DivorceEqualizationService
from steuerreport_v2.domain.external_price_backfill import ExternalPriceBackfillService
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.stichtag_token_valuation import (
    StichtagTokenValuationService,
)


class AsOfPriceGateService:
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
    DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT / "var/price_gate_runs"

    def __init__(
        self, store: DuckDbStore, *, artifact_root: Path | None = None
    ) -> None:
        self.store = store
        self.artifact_root = artifact_root or self._default_artifact_root()

    def report(
        self,
        *,
        as_of: datetime | None = None,
        as_of_date: date | None = None,
        materiality_threshold_eur: Decimal = Decimal("1"),
        config_path: str = "/workspace/steuerreport-v2-plan/configs/crypto_price_sources.json",
    ) -> AsOfPriceGateReport:
        valuation_at = self._resolve_as_of(as_of=as_of, as_of_date=as_of_date)
        if materiality_threshold_eur < 0:
            raise ValueError("Die Materialitaetsschwelle darf nicht negativ sein.")
        if valuation_at > datetime.now(timezone.utc):
            raise ValueError("Der Preisstichtag darf nicht in der Zukunft liegen.")
        portfolio = PortfolioService(self.store).as_of_snapshot(valuation_at)
        divorce_service = DivorceEqualizationService(self.store)
        gate = divorce_service._valuation_gate(
            portfolio.positions,
            divorce_service._naive(valuation_at),
            materiality_threshold_eur,
        )
        valuation_date = divorce_service._local_date(valuation_at)
        provider_sources = self._provider_sources(config_path)
        positions_by_asset: defaultdict[str, list[object]] = defaultdict(list)
        for position in portfolio.positions:
            value = abs(position.value_eur or Decimal("0"))
            if position.price_eur is None or value >= materiality_threshold_eur:
                positions_by_asset[str(position.asset).upper()].append(position)
        candidates: list[AsOfPriceGateCandidate] = []
        for asset, positions in sorted(positions_by_asset.items()):
            priced = [
                position for position in positions if position.priced_at is not None
            ]
            latest = (
                max(priced, key=lambda position: position.priced_at) if priced else None
            )
            priced_at = latest.priced_at if latest is not None else None
            price_source = latest.price_source if latest is not None else None
            price_eur = latest.price_eur if latest is not None else None
            age_days, price_status = divorce_service._price_status(
                priced_at=priced_at,
                price_source=price_source,
                valuation_at=divorce_service._naive(valuation_at),
            )
            value_eur = sum(
                (position.value_eur or Decimal("0") for position in positions),
                Decimal("0"),
            )
            quantity = sum((position.quantity for position in positions), Decimal("0"))
            coingecko_id, defillama_id = provider_sources.get(asset, (None, None))
            provider_id = defillama_id or coingecko_id
            token_assessment = divorce_service.token_valuation_service.assessment(
                asset,
                valuation_date,
            )
            token_review_status = (
                "accepted"
                if token_assessment.accepted_decision is not None
                else "pending"
                if token_assessment.review_required
                else "not_required"
            )
            if price_status != "same_day" and provider_id:
                status = "fetchable"
                reason = (
                    "Historischer Provider und USD/EUR-Tageskurs koennen den "
                    "Stichtagspreis belegen."
                )
                if token_review_status == "pending":
                    reason += " Danach bleibt eine stichtagsbezogene Tokenpruefung erforderlich."
            elif price_status != "same_day":
                status = "not_configured"
                reason = "Kein historischer Provider-Identifier konfiguriert."
            elif token_review_status == "pending":
                status = "review_only"
                reason = (
                    "Same-Day-Preis vorhanden; der exakte Token-Mint muss fuer "
                    "diesen Stichtag beleggebunden angenommen werden."
                )
            else:
                status = "satisfied"
                reason = (
                    "Materielle Position besitzt einen Preis am Stichtag."
                    if token_review_status == "not_required"
                    else "Same-Day-Preis und stichtagsbezogene Tokenentscheidung sind belegt."
                )
            candidates.append(
                AsOfPriceGateCandidate(
                    asset=asset,
                    accounts=sorted({str(position.account) for position in positions}),
                    quantity=quantity,
                    value_eur=value_eur,
                    current_price_eur=price_eur,
                    current_priced_at=self._as_utc(priced_at) if priced_at else None,
                    current_price_source=price_source,
                    current_price_age_days=age_days,
                    current_price_status=price_status,
                    provider_id=provider_id,
                    token_mint=token_assessment.mint,
                    token_verified=token_assessment.token_verified,
                    token_risk_status=token_assessment.risk_status,
                    token_review_status=token_review_status,
                    token_review_decision_id=(
                        token_assessment.accepted_decision.decision_id
                        if token_assessment.accepted_decision is not None
                        else None
                    ),
                    token_review_evidence_ref=(
                        token_assessment.accepted_decision.evidence_ref
                        if token_assessment.accepted_decision is not None
                        else None
                    ),
                    status=status,
                    reason=reason,
                )
            )
        candidates.sort(
            key=lambda item: (
                {
                    "fetchable": 0,
                    "not_configured": 1,
                    "review_only": 2,
                    "satisfied": 3,
                }.get(item.status, 4),
                -abs(item.value_eur),
                item.asset,
            )
        )
        return AsOfPriceGateReport(
            generated_at=datetime.now(timezone.utc),
            as_of=valuation_at,
            materiality_threshold_eur=materiality_threshold_eur,
            strict_ready=gate.strict_ready,
            status=gate.status,
            gate=gate,
            material_assets_count=len(candidates),
            requirements_count=sum(item.status != "satisfied" for item in candidates),
            fetchable_count=sum(item.status == "fetchable" for item in candidates),
            review_only_count=sum(item.status == "review_only" for item in candidates),
            not_configured_count=sum(
                item.status == "not_configured" for item in candidates
            ),
            candidates=candidates,
            methodology=(
                "Read-only Stichtagspreis-Gate aus historischen Portfolio-Positionen. Materielle Assets "
                "benoetigen einen Preis am selben UTC-Kalendertag. Vortags-, veraltete oder aus Event-"
                "Quotes abgeleitete Preise werden nicht still akzeptiert. Tokenrisiken werden mintgenau "
                "aus dem Jupiter-Metadatenbeleg bestimmt und benoetigen pro Stichtag eine explizite "
                "Bewertungsentscheidung. Fetchable bedeutet nur, dass Provider-ID und FX-Pfad "
                "konfiguriert sind."
            ),
        )

    def accept_token_valuation(
        self,
        request: AsOfTokenValuationDecisionRequest,
    ) -> AsOfTokenValuationDecisionResult:
        gate_before = self.report(
            as_of_date=request.as_of_date,
            materiality_threshold_eur=request.materiality_threshold_eur,
        )
        asset = str(request.asset or "").strip().lstrip("$").upper()
        candidate = next(
            (item for item in gate_before.candidates if item.asset == asset),
            None,
        )
        if candidate is None:
            raise ValueError("material_token_candidate_not_found")
        if candidate.token_review_status == "not_required":
            raise ValueError("token_review_not_required")
        if candidate.current_price_status != "same_day":
            raise ValueError("documented_same_day_price_required_before_token_review")
        if candidate.current_price_eur is None or candidate.current_price_eur <= 0:
            raise ValueError("documented_positive_same_day_price_required")
        evidence_ref = (
            f"/api/v1/prices/as-of-gate?as_of_date={request.as_of_date.isoformat()}"
            f"&materiality_threshold_eur={request.materiality_threshold_eur}"
        )
        decision, already_recorded = StichtagTokenValuationService(
            self.store
        ).accept_same_day_valuation(
            asset=asset,
            as_of_date=request.as_of_date,
            price_eur=candidate.current_price_eur,
            price_source=candidate.current_price_source or "",
            evidence_ref=evidence_ref,
            rationale=request.rationale,
            actor=request.actor,
        )
        return AsOfTokenValuationDecisionResult(
            already_recorded=already_recorded,
            decision=decision,
            gate_after=self.report(
                as_of_date=request.as_of_date,
                materiality_threshold_eur=request.materiality_threshold_eur,
            ),
        )

    def token_valuation_decisions_csv(
        self,
        *,
        separation_date: date | None = None,
        end_asset_date: date | None = None,
    ) -> str:
        dates = {
            separation_date or DivorceEqualizationService.DEFAULT_SEPARATION_DATE,
            end_asset_date or DivorceEqualizationService.DEFAULT_END_ASSET_DATE,
        }
        return StichtagTokenValuationService(self.store).decisions_csv(dates)

    def backfill(
        self, request: AsOfPriceGateBackfillRequest
    ) -> AsOfPriceGateBackfillResult:
        generated_at = datetime.now(timezone.utc)
        valuation_at = self._resolve_as_of(
            as_of=request.as_of,
            as_of_date=request.as_of_date,
        )
        gate_before = self.report(
            as_of=valuation_at,
            materiality_threshold_eur=request.materiality_threshold_eur,
            config_path=request.config_path,
        )
        requested_assets = {
            asset.strip().upper() for asset in request.assets if asset.strip()
        }
        candidates = [
            item
            for item in gate_before.candidates
            if item.status == "fetchable"
            and (not requested_assets or item.asset in requested_assets)
        ][: request.max_requests]
        jobs: list[AsOfPriceGateBackfillJob] = []
        prices: list[PricePointCreate] = []
        failed = 0
        skipped = 0
        provider = (
            request.provider
            if request.provider in {"auto", "defillama"}
            else "defillama"
        )
        backfill_service = ExternalPriceBackfillService(self.store)
        provider_sources = self._provider_sources(request.config_path)
        price_date = valuation_at.date()
        usd_eur = backfill_service._usd_eur_rate(
            request.v1_fx_db_path, price_date.isoformat()
        )
        if usd_eur <= 0:
            raise ValueError(
                f"Kein belegter USD/EUR-Kurs fuer {price_date.isoformat()} vorhanden."
            )
        with httpx.Client(
            timeout=request.timeout_seconds,
            headers={"user-agent": "steuerreport-v2/0.1"},
        ) as client:
            for candidate in candidates:
                coingecko_id, defillama_id = provider_sources.get(
                    candidate.asset, (None, None)
                )
                if request.dry_run:
                    jobs.append(
                        AsOfPriceGateBackfillJob(
                            asset=candidate.asset,
                            price_date=price_date,
                            provider_id=candidate.provider_id,
                            status="planned",
                            usd_eur=usd_eur,
                            source="defillama_coingecko_history:usd_eur:v1_fx_cache:as_of_gate",
                        )
                    )
                    continue
                try:
                    price_usd, source = backfill_service._fetch_price_usd(
                        client=client,
                        coingecko_id=coingecko_id,
                        defillama_id=defillama_id,
                        date_str=price_date.isoformat(),
                        provider=provider,
                    )
                except httpx.HTTPError as exc:
                    price_usd = Decimal("0")
                    source = ""
                    reason = f"provider_error:{type(exc).__name__}"
                else:
                    reason = None
                if price_usd <= 0:
                    failed += 1
                    jobs.append(
                        AsOfPriceGateBackfillJob(
                            asset=candidate.asset,
                            price_date=price_date,
                            provider_id=candidate.provider_id,
                            status="failed",
                            reason=reason or "asset_usd_missing",
                        )
                    )
                    continue
                price_eur = price_usd * usd_eur
                source_label = (
                    f"{source}:usd_eur:v1_fx_cache:as_of_gate:{price_date.isoformat()}"
                )
                prices.append(
                    PricePointCreate(
                        asset=candidate.asset,
                        price_eur=price_eur,
                        priced_at=datetime.combine(
                            price_date, datetime.min.time(), tzinfo=timezone.utc
                        ),
                        source=source_label,
                        confidence=request.confidence,
                    )
                )
                jobs.append(
                    AsOfPriceGateBackfillJob(
                        asset=candidate.asset,
                        price_date=price_date,
                        provider_id=candidate.provider_id,
                        status="imported",
                        price_usd=price_usd,
                        usd_eur=usd_eur,
                        price_eur=price_eur,
                        source=source_label,
                    )
                )
        if prices:
            self.store.add_price_points(prices)
        if request.dry_run:
            gate_after = gate_before
        else:
            gate_after = self.report(
                as_of=valuation_at,
                materiality_threshold_eur=request.materiality_threshold_eur,
                config_path=request.config_path,
            )
        run_kind = "preview" if request.dry_run else "apply"
        artifact_path = self.artifact_root / (
            f"as_of_price_gate_{run_kind}_{generated_at.strftime('%Y%m%dT%H%M%S%fZ')}.json"
        )
        result = AsOfPriceGateBackfillResult(
            generated_at=generated_at,
            dry_run=request.dry_run,
            attempted=len(candidates),
            imported_prices=len(prices),
            skipped=skipped,
            failed=failed,
            gate_before=gate_before,
            gate_after=gate_after,
            jobs=jobs,
            artifact_path=self._display_path(artifact_path),
            methodology=(
                "Historischer Preisbackfill nur fuer materielle, fetchable Stichtagspositionen. "
                "DefiLlama liefert den historischen USD-Preis anhand der konfigurierten CoinGecko- oder Chain-ID; "
                "der vorhandene V1-FX-Cache liefert den belegten USD/EUR-Tageskurs. Apply schreibt nur "
                "neue Price-Ledger-Punkte und baut weder Ledger noch Steuer-FIFO automatisch neu."
            ),
        )
        self._atomic_write(
            artifact_path,
            json.dumps(
                result.model_dump(mode="json"), indent=2, ensure_ascii=False
            ).encode("utf-8"),
        )
        self._atomic_write(
            self.artifact_root / "latest_as_of_price_gate_run.json",
            json.dumps(
                result.model_dump(mode="json"), indent=2, ensure_ascii=False
            ).encode("utf-8"),
        )
        return result

    @staticmethod
    def _resolve_as_of(
        *,
        as_of: datetime | None,
        as_of_date: date | None,
    ) -> datetime:
        if as_of_date is not None:
            resolved = DivorceEqualizationService.local_day_end_utc(as_of_date)
            if as_of is not None and AsOfPriceGateService._as_utc(as_of) != resolved:
                raise ValueError(
                    "Preisstichtag: as_of und as_of_date widersprechen sich."
                )
            return resolved
        if as_of is None:
            raise ValueError("Preisstichtag as_of oder as_of_date ist erforderlich.")
        return AsOfPriceGateService._as_utc(as_of)

    @staticmethod
    def _provider_sources(
        config_path: str,
    ) -> dict[str, tuple[str | None, str | None]]:
        payload = json.loads(Path(config_path).read_text(encoding="utf-8"))
        return {
            str(item.get("symbol") or "").upper(): (
                str(item.get("coingecko_id") or "").strip() or None,
                str(item.get("defillama_id") or "").strip() or None,
            )
            for item in payload.get("assets") or []
            if isinstance(item, dict)
            and item.get("symbol")
            and (item.get("coingecko_id") or item.get("defillama_id"))
        }

    def _default_artifact_root(self) -> Path:
        if self.store.path.resolve() == self.DEFAULT_DB.resolve():
            return self.DEFAULT_ARTIFACT_ROOT
        return self.store.path.parent / "var/price_gate_runs"

    def _display_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.PROJECT_ROOT.resolve()))
        except ValueError:
            return str(path.resolve())

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
