from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

import httpx

from steuerreport_v2.contracts.bmf_event_evidence import (
    BmfFifoEventEvidenceRunRequest,
)
from steuerreport_v2.contracts.bmf_event_price_remediation import (
    BmfEventPriceRemediationJob,
    BmfEventPriceRemediationReport,
    BmfEventPriceRemediationRunRequest,
)
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.bmf_event_evidence import BmfFifoEventEvidenceService
from steuerreport_v2.paths import resolve_project_path
from steuerreport_v2.domain.tax import STABLE_VALUE_ANCHOR_ASSETS


@dataclass
class _Requirement:
    asset: str
    price_date: date
    roles: set[str] = field(default_factory=set)
    event_ids: set[str] = field(default_factory=set)
    qualities: set[str] = field(default_factory=set)
    sources: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class _FxResult:
    rate: Decimal
    rate_date: date
    request_url: str
    response_sha256: str
    payload: object


@dataclass(frozen=True)
class _CryptoResult:
    price_usd: Decimal
    provider_id: str
    provider_timestamp: datetime
    confidence: Decimal
    request_url: str
    response_sha256: str
    payload: object


class BmfEventPriceRemediationService:
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
    DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT / "var/bmf_event_price_remediation"
    FRANKFURTER_URL = "https://api.frankfurter.dev/v2/rates"
    DEFILLAMA_URL = "https://coins.llama.fi/prices/historical"
    SOURCE_PREFIX = "bmf_event_price_anchor:v1"

    def __init__(
        self,
        store: DuckDbStore,
        *,
        artifact_root: Path | None = None,
        event_evidence_service: BmfFifoEventEvidenceService | None = None,
    ) -> None:
        self.store = store
        self.artifact_root = artifact_root or self._default_artifact_root()
        self.event_evidence_service = (
            event_evidence_service or BmfFifoEventEvidenceService(store)
        )
        self.staging_service = self.event_evidence_service.staging_service

    def run(
        self,
        request: BmfEventPriceRemediationRunRequest,
    ) -> BmfEventPriceRemediationReport:
        evidence_before = self.event_evidence_service.latest()
        if evidence_before is None:
            raise ValueError(
                "Zuerst muss die BMF-FIFO-Eventbelegpruefung ausgefuehrt werden."
            )
        if evidence_before.event_issues_truncated:
            raise ValueError(
                "Eventbeleg-Artefakt ist gekuerzt; zuerst mit hoeherem issue_limit neu erzeugen."
            )
        generated_at = datetime.now(timezone.utc)
        productive_before = self.staging_service._productive_tax_sha256()
        price_count_before = self._price_points_count()
        requirements = self._requirements(
            evidence_before,
            include_roles=set(request.include_roles),
        )
        requirement_items = sorted(
            requirements.values(),
            key=lambda item: (item.price_date, item.asset),
        )
        config = self._price_config(resolve_project_path(request.config_path))
        token_risk_statuses = self._token_risk_statuses()
        jobs: list[BmfEventPriceRemediationJob] = []
        pending_points: list[tuple[int, PricePointCreate]] = []
        evidence_payloads: list[dict[str, object]] = []
        fx_cache: dict[date, _FxResult | None] = {}
        provider_requests = 0
        fx_requests = 0

        timeout = max(3, min(request.timeout_seconds, 60))
        with httpx.Client(
            timeout=timeout,
            headers={"user-agent": "steuerreport-v2/0.1"},
        ) as client:
            for index, requirement in enumerate(requirement_items):
                if index >= request.max_jobs:
                    jobs.append(
                        self._base_job(
                            requirement,
                            status="request_limit",
                            reason="max_jobs erreicht",
                        )
                    )
                    continue
                token_risk_status = token_risk_statuses.get(requirement.asset)
                if token_risk_status == "spam_review":
                    jobs.append(
                        self._base_job(
                            requirement,
                            status="token_risk_blocked",
                            reason=(
                                "Token ist als spam_review markiert; ein Preisimport "
                                "darf die fachliche Token-Identitaetspruefung nicht umgehen"
                            ),
                            token_risk_status=token_risk_status,
                        )
                    )
                    continue
                if requirement.price_date not in fx_cache:
                    fx_cache[requirement.price_date] = self._fetch_fx(
                        client,
                        requirement.price_date,
                    )
                    fx_requests += 1
                    fx_item = fx_cache[requirement.price_date]
                    if fx_item is not None:
                        evidence_payloads.append(
                            {
                                "kind": "usd_eur_fx",
                                "price_date": requirement.price_date.isoformat(),
                                "request_url": fx_item.request_url,
                                "response_sha256": fx_item.response_sha256,
                                "payload": fx_item.payload,
                            }
                        )
                fx = fx_cache[requirement.price_date]
                if fx is None:
                    jobs.append(
                        self._base_job(
                            requirement,
                            status="fx_failed",
                            reason="ECB-USD/EUR-Referenzkurs nicht abrufbar",
                        )
                    )
                    continue

                crypto: _CryptoResult | None = None
                asset_config = config.get(requirement.asset)
                stable = requirement.asset in STABLE_VALUE_ANCHOR_ASSETS
                if stable:
                    price_usd = Decimal("1")
                    provider_id = "USD-parity"
                    provider_confidence = Decimal("1")
                    price_confidence = Decimal("1")
                    provider_timestamp = datetime.combine(
                        requirement.price_date,
                        time.min,
                        tzinfo=timezone.utc,
                    )
                    provider_request_url = None
                    provider_response_sha256 = None
                else:
                    if asset_config is None:
                        jobs.append(
                            self._base_job(
                                requirement,
                                status="not_configured",
                                reason="Asset besitzt keine historische Provider-ID",
                            )
                        )
                        continue
                    crypto, requests_used = self._fetch_crypto(
                        client,
                        requirement.price_date,
                        asset_config,
                    )
                    provider_requests += requests_used
                    if crypto is None:
                        jobs.append(
                            self._base_job(
                                requirement,
                                status="provider_failed",
                                reason="DefiLlama lieferte keinen positiven historischen Preis",
                                fx=fx,
                            )
                        )
                        continue
                    evidence_payloads.append(
                        {
                            "kind": "crypto_usd_price",
                            "asset": requirement.asset,
                            "price_date": requirement.price_date.isoformat(),
                            "provider_id": crypto.provider_id,
                            "request_url": crypto.request_url,
                            "response_sha256": crypto.response_sha256,
                            "payload": crypto.payload,
                        }
                    )
                    price_usd = crypto.price_usd
                    provider_id = crypto.provider_id
                    provider_confidence = crypto.confidence
                    price_confidence = max(
                        Decimal("0.9"),
                        min(Decimal("0.99"), crypto.confidence),
                    )
                    provider_timestamp = crypto.provider_timestamp
                    provider_request_url = crypto.request_url
                    provider_response_sha256 = crypto.response_sha256

                price_eur = price_usd * fx.rate
                source = self._source_label(
                    stable=stable,
                    provider_id=provider_id,
                    provider_timestamp=provider_timestamp,
                    fx_rate_date=fx.rate_date,
                )
                if self._price_point_exists(
                    requirement.asset,
                    requirement.price_date,
                    source,
                ):
                    jobs.append(
                        self._job(
                            requirement,
                            status="already_ready",
                            reason="Identischer V2-Preisanker ist bereits vorhanden",
                            fx=fx,
                            crypto=crypto,
                            provider_id=provider_id,
                            provider_timestamp=provider_timestamp,
                            provider_confidence=provider_confidence,
                            price_usd=price_usd,
                            price_eur=price_eur,
                            source=source,
                            price_confidence=price_confidence,
                        )
                    )
                    continue
                job = self._job(
                    requirement,
                    status="planned",
                    reason=(
                        "Additiver V2-Preisanker wird nach execute=true importiert"
                        if not request.execute
                        else "Provider- und ECB-Beleg erfolgreich abgerufen"
                    ),
                    fx=fx,
                    crypto=crypto,
                    provider_id=provider_id,
                    provider_timestamp=provider_timestamp,
                    provider_confidence=provider_confidence,
                    price_usd=price_usd,
                    price_eur=price_eur,
                    source=source,
                    price_confidence=price_confidence,
                    provider_request_url=provider_request_url,
                    provider_response_sha256=provider_response_sha256,
                )
                jobs.append(job)
                if request.execute:
                    pending_points.append(
                        (
                            len(jobs) - 1,
                            PricePointCreate(
                                asset=requirement.asset,
                                price_eur=price_eur,
                                priced_at=datetime.combine(
                                    requirement.price_date,
                                    time.min,
                                    tzinfo=timezone.utc,
                                ),
                                source=source,
                                confidence=price_confidence,
                            ),
                        )
                    )

        if pending_points:
            imported = self.store.add_price_points(
                [point for _index, point in pending_points]
            )
            for (job_index, _point), price in zip(pending_points, imported, strict=True):
                jobs[job_index] = jobs[job_index].model_copy(
                    update={
                        "status": "imported",
                        "reason": "Preisanker additiv in V2 price_ledger importiert",
                        "price_id": price.price_id,
                    }
                )

        productive_after = self.staging_service._productive_tax_sha256()
        productive_unchanged = productive_before == productive_after
        if not productive_unchanged:
            raise RuntimeError(
                "Preisremediation hat produktive Tax-Tabellen veraendert."
            )
        evidence_after = None
        if request.execute:
            evidence_after = self.event_evidence_service.run(
                BmfFifoEventEvidenceRunRequest(limit=5000, issue_limit=5000)
            )

        fingerprint = self._requirements_fingerprint(
            evidence_before.run_id,
            requirement_items,
        )
        run_id = (
            f"bmf-event-price-remediation-"
            f"{generated_at.strftime('%Y%m%dT%H%M%S%fZ')}-{fingerprint[:12]}"
        )
        artifact_path = self.artifact_root / f"{run_id}.json"
        latest_path = self.artifact_root / "latest.json"
        evidence_path = self.artifact_root / f"{run_id}-provider-evidence.json"
        evidence_content = json.dumps(
            {
                "run_id": run_id,
                "generated_at": generated_at.isoformat(),
                "responses": evidence_payloads,
            },
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        evidence_sha256 = hashlib.sha256(evidence_content).hexdigest()
        self._atomic_write(evidence_path, evidence_content)

        failed_count = sum(
            1
            for job in jobs
            if job.status
            in {"not_configured", "fx_failed", "provider_failed"}
        )
        imported_count = sum(1 for job in jobs if job.status == "imported")
        planned_count = sum(1 for job in jobs if job.status == "planned")
        token_risk_blocked_count = sum(
            1 for job in jobs if job.status == "token_risk_blocked"
        )
        request_limit_count = sum(
            1 for job in jobs if job.status == "request_limit"
        )
        status = self._status(
            execute=request.execute,
            planned_count=planned_count,
            imported_count=imported_count,
            failed_count=failed_count,
            token_risk_blocked_count=token_risk_blocked_count,
            request_limit_count=request_limit_count,
        )
        report = BmfEventPriceRemediationReport(
            run_id=run_id,
            generated_at=generated_at,
            status=status,
            execute=request.execute,
            read_only=not request.execute,
            event_evidence_run_id_before=evidence_before.run_id,
            event_evidence_run_id_after=(
                evidence_after.run_id if evidence_after else None
            ),
            productive_tax_component_sha256_before=productive_before,
            productive_tax_component_sha256_after=productive_after,
            productive_tax_tables_unchanged=productive_unchanged,
            price_points_count_before=price_count_before,
            price_points_count_after=self._price_points_count(),
            requirements_count=len(requirement_items),
            jobs_returned=len(jobs),
            planned_count=planned_count,
            imported_count=imported_count,
            already_ready_count=sum(
                1 for job in jobs if job.status == "already_ready"
            ),
            failed_count=failed_count,
            token_risk_blocked_count=token_risk_blocked_count,
            request_limit_count=request_limit_count,
            provider_requests_count=provider_requests,
            fx_requests_count=fx_requests,
            unique_assets=sorted({item.asset for item in requirement_items}),
            unique_dates_count=len({item.price_date for item in requirement_items}),
            before_review_events_count=evidence_before.review_events_count,
            before_derived_price_review_count=(
                evidence_before.derived_price_review_count
            ),
            before_stale_price_review_count=evidence_before.stale_price_review_count,
            after_review_events_count=(
                evidence_after.review_events_count if evidence_after else None
            ),
            after_derived_price_review_count=(
                evidence_after.derived_price_review_count if evidence_after else None
            ),
            after_stale_price_review_count=(
                evidence_after.stale_price_review_count if evidence_after else None
            ),
            jobs=jobs,
            artifact_path=self._display_path(artifact_path),
            latest_artifact_path=self._display_path(latest_path),
            evidence_artifact_path=self._display_path(evidence_path),
            evidence_artifact_sha256=evidence_sha256,
            findings=self._findings(
                requirements=len(requirement_items),
                imported=imported_count,
                planned=planned_count,
                failed=failed_count,
                token_risk_blocked=token_risk_blocked_count,
                request_limit=request_limit_count,
                evidence_after=evidence_after,
            ),
            next_actions=self._next_actions(
                execute=request.execute,
                failed=failed_count,
                token_risk_blocked=token_risk_blocked_count,
                request_limit=request_limit_count,
            ),
            methodology=(
                "Gezielte V2-Preisremediation nur fuer abgeleitete, veraltete oder "
                "fehlende received-/given-Preisrollen der aktuellen BMF-FIFO-"
                "Eventbeleg-Worklist. USD-Paritaets-Stablecoins verwenden den taeglichen "
                "USD/EUR-ECB-Referenzkurs aus Frankfurter v2. Andere Assets verwenden "
                "einen DefiLlama-Historienpreis um 00:00 UTC und denselben ECB-Kurs. "
                "Providerantworten werden mit URL, Payload und SHA-256 archiviert. "
                "Assets mit Jupiter-Risikostatus spam_review werden vor dem Abruf "
                "blockiert; ein Preisanker ersetzt keine Token-Identitaetspruefung. "
                "execute=false schreibt nur Artefakte; execute=true fuegt deduplizierte "
                "Preisanker additiv ein. Tax-Lots und Tax-Lines werden nicht neu gebaut "
                "und muessen vor/nach dem Lauf denselben Hash besitzen."
            ),
        )
        report_content = json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        self._atomic_write(artifact_path, report_content)
        self._atomic_write(latest_path, report_content)
        return report

    def latest(self) -> BmfEventPriceRemediationReport | None:
        try:
            return BmfEventPriceRemediationReport.model_validate_json(
                (self.artifact_root / "latest.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None

    @staticmethod
    def _requirements(evidence: object, *, include_roles: set[str]) -> dict[tuple[str, date], _Requirement]:
        result: dict[tuple[str, date], _Requirement] = {}
        for event in getattr(evidence, "event_issues"):
            if event.event_time is None:
                continue
            for role, price in (
                ("received", event.received_price),
                ("given", event.given_price),
            ):
                if role not in include_roles or price is None:
                    continue
                low_confidence_issue = (
                    f"{role}_price_low_confidence" in event.issue_codes
                )
                if price.quality == "independent_current" and not low_confidence_issue:
                    continue
                key = (price.asset.upper(), event.event_time.date())
                requirement = result.setdefault(
                    key,
                    _Requirement(asset=key[0], price_date=key[1]),
                )
                requirement.roles.add(role)
                requirement.event_ids.add(event.event_id)
                requirement.qualities.add(price.quality)
                if price.source:
                    requirement.sources.add(price.source)
        return result

    @staticmethod
    def _price_config(path: Path) -> dict[str, dict[str, str | None]]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        result: dict[str, dict[str, str | None]] = {}
        for item in payload.get("assets", []):
            if not isinstance(item, dict) or not item.get("symbol"):
                continue
            result[str(item["symbol"]).upper()] = {
                "defillama_id": str(item.get("defillama_id") or "") or None,
                "coingecko_id": str(item.get("coingecko_id") or "") or None,
            }
        return result

    def _token_risk_statuses(self) -> dict[str, str]:
        priority = {
            "spam_review": 4,
            "review": 3,
            "unverified_plausible": 2,
            "verified": 1,
        }
        with self.store.connect() as con:
            rows = con.execute(
                """
                select upper(coalesce(symbol, mint)), risk_status
                from jupiter_token_metadata_cache
                where coalesce(symbol, mint) is not null
                """
            ).fetchall()
        result: dict[str, str] = {}
        for asset, status in rows:
            key = str(asset).upper()
            candidate = str(status or "review")
            current = result.get(key)
            if current is None or priority.get(candidate, 3) > priority.get(current, 3):
                result[key] = candidate
        return result

    def _fetch_fx(self, client: httpx.Client, price_date: date) -> _FxResult | None:
        response = client.get(
            self.FRANKFURTER_URL,
            params={
                "date": price_date.isoformat(),
                "base": "USD",
                "quotes": "EUR",
                "providers": "ECB",
            },
        )
        if response.status_code >= 400:
            return None
        payload = response.json()
        if not isinstance(payload, list) or not payload:
            return None
        row = payload[0]
        if not isinstance(row, dict):
            return None
        rate = self._decimal(row.get("rate"))
        if rate <= 0 or not row.get("date"):
            return None
        return _FxResult(
            rate=rate,
            rate_date=date.fromisoformat(str(row["date"])),
            request_url=str(response.request.url),
            response_sha256=self._sha256_bytes(response.content),
            payload=payload,
        )

    def _fetch_crypto(
        self,
        client: httpx.Client,
        price_date: date,
        config: dict[str, str | None],
    ) -> tuple[_CryptoResult | None, int]:
        timestamp = int(
            datetime.combine(price_date, time.min, tzinfo=UTC).timestamp()
        )
        provider_ids = [
            item
            for item in (
                config.get("defillama_id"),
                f"coingecko:{config['coingecko_id']}"
                if config.get("coingecko_id")
                else None,
            )
            if item
        ]
        requests_used = 0
        for provider_id in dict.fromkeys(provider_ids):
            response = client.get(
                f"{self.DEFILLAMA_URL}/{timestamp}/{quote(str(provider_id), safe=':')}"
            )
            requests_used += 1
            if response.status_code >= 400:
                continue
            payload = response.json()
            coins = payload.get("coins") if isinstance(payload, dict) else None
            row = coins.get(provider_id) if isinstance(coins, dict) else None
            if not isinstance(row, dict):
                continue
            price_usd = self._decimal(row.get("price"))
            provider_ts = int(row.get("timestamp") or 0)
            if price_usd <= 0 or provider_ts <= 0:
                continue
            return (
                _CryptoResult(
                    price_usd=price_usd,
                    provider_id=str(provider_id),
                    provider_timestamp=datetime.fromtimestamp(
                        provider_ts,
                        tz=timezone.utc,
                    ),
                    confidence=self._decimal(row.get("confidence") or "0.95"),
                    request_url=str(response.request.url),
                    response_sha256=self._sha256_bytes(response.content),
                    payload=payload,
                ),
                requests_used,
            )
        return None, requests_used

    def _base_job(
        self,
        requirement: _Requirement,
        *,
        status: str,
        reason: str,
        fx: _FxResult | None = None,
        token_risk_status: str | None = None,
    ) -> BmfEventPriceRemediationJob:
        event_ids = sorted(requirement.event_ids)
        return BmfEventPriceRemediationJob(
            asset=requirement.asset,
            price_date=requirement.price_date,
            roles=sorted(requirement.roles),  # type: ignore[arg-type]
            affected_event_ids=event_ids[:50],
            affected_event_ids_truncated=len(event_ids) > 50,
            previous_qualities=sorted(requirement.qualities),
            previous_sources=sorted(requirement.sources),
            token_risk_status=token_risk_status,
            fx_request_url=fx.request_url if fx else None,
            fx_response_sha256=fx.response_sha256 if fx else None,
            fx_rate_date=fx.rate_date if fx else None,
            usd_eur=fx.rate if fx else None,
            status=status,  # type: ignore[arg-type]
            reason=reason,
        )

    def _job(
        self,
        requirement: _Requirement,
        *,
        status: str,
        reason: str,
        fx: _FxResult,
        crypto: _CryptoResult | None,
        provider_id: str,
        provider_timestamp: datetime,
        provider_confidence: Decimal,
        price_usd: Decimal,
        price_eur: Decimal,
        source: str,
        price_confidence: Decimal,
        provider_request_url: str | None = None,
        provider_response_sha256: str | None = None,
    ) -> BmfEventPriceRemediationJob:
        job = self._base_job(
            requirement,
            status=status,
            reason=reason,
            fx=fx,
        )
        return job.model_copy(
            update={
                "provider_id": provider_id,
                "provider_request_url": (
                    provider_request_url
                    or (crypto.request_url if crypto else None)
                ),
                "provider_response_sha256": (
                    provider_response_sha256
                    or (crypto.response_sha256 if crypto else None)
                ),
                "provider_timestamp": provider_timestamp,
                "provider_confidence": provider_confidence,
                "price_usd": price_usd,
                "price_eur": price_eur,
                "price_source": source,
                "price_confidence": price_confidence,
            }
        )

    @classmethod
    def _source_label(
        cls,
        *,
        stable: bool,
        provider_id: str,
        provider_timestamp: datetime,
        fx_rate_date: date,
    ) -> str:
        provider = (
            "stablecoin_usd_parity"
            if stable
            else f"defillama:{provider_id}:provider_ts:{int(provider_timestamp.timestamp())}"
        )
        return (
            f"{cls.SOURCE_PREFIX}:{provider}:usd_eur:"
            f"frankfurter_v2_ecb:rate_date:{fx_rate_date.isoformat()}"
        )

    def _price_point_exists(self, asset: str, price_date: date, source: str) -> bool:
        with self.store.connect() as con:
            row = con.execute(
                """
                select 1 from price_ledger
                where upper(asset) = ?
                  and cast(priced_at as date) = ?
                  and source = ?
                limit 1
                """,
                [asset.upper(), price_date, source],
            ).fetchone()
        return row is not None

    def _price_points_count(self) -> int:
        with self.store.connect() as con:
            return int(con.execute("select count(*) from price_ledger").fetchone()[0])

    @staticmethod
    def _status(
        *,
        execute: bool,
        planned_count: int,
        imported_count: int,
        failed_count: int,
        token_risk_blocked_count: int,
        request_limit_count: int,
    ) -> str:
        incomplete = bool(
            failed_count or token_risk_blocked_count or request_limit_count
        )
        if not execute:
            if incomplete and not planned_count:
                return "blocked"
            return "partial" if incomplete else "planned"
        if incomplete and not imported_count:
            return "blocked"
        return "partial" if incomplete else "applied"

    @staticmethod
    def _findings(
        *,
        requirements: int,
        imported: int,
        planned: int,
        failed: int,
        token_risk_blocked: int,
        request_limit: int,
        evidence_after: object | None,
    ) -> list[str]:
        findings = [
            f"{requirements} eindeutige Asset-/Tagesanker stammen aus der aktuellen Eventbeleg-Worklist.",
            f"{planned} Anker sind geplant, {imported} wurden importiert, {failed} Provider-/FX-Abrufe sind fehlgeschlagen.",
        ]
        if request_limit:
            findings.append(
                f"{request_limit} Anforderungen wurden wegen max_jobs nicht abgerufen."
            )
        if token_risk_blocked:
            findings.append(
                f"{token_risk_blocked} Anforderungen wurden wegen spam_review nicht als Preisanker freigegeben."
            )
        if evidence_after is not None:
            findings.append(
                f"Eventreview danach: {getattr(evidence_after, 'review_events_count')} Events; "
                f"{getattr(evidence_after, 'derived_price_review_count')} abgeleitete und "
                f"{getattr(evidence_after, 'stale_price_review_count')} veraltete erhaltene Preise."
            )
        return findings

    @staticmethod
    def _next_actions(
        *,
        execute: bool,
        failed: int,
        token_risk_blocked: int,
        request_limit: int,
    ) -> list[str]:
        actions: list[str] = []
        if not execute:
            actions.append(
                "Dry-run-Artefakt pruefen und denselben Lauf mit execute=true additiv anwenden."
            )
        if failed:
            actions.append(
                "Fehlgeschlagene Provider-IDs oder ECB-Tage einzeln mit einer unabhaengigen Quelle belegen."
            )
        if token_risk_blocked:
            actions.append(
                "Token-Identitaet und steuerliche Relevanz der spam_review-Assets fachlich dokumentieren; erst danach separat freigeben."
            )
        if request_limit:
            actions.append("max_jobs erhoehen und Restanforderungen erneut pruefen.")
        if execute:
            actions.append(
                "Vier-Wege-FIFO-Staging neu berechnen, weil sich dessen Preis-Input-Fingerprint geaendert hat."
            )
            actions.append(
                "Anschliessend Eventbeleg-Report erneut an den neuen Staging-Run binden."
            )
        return actions

    @staticmethod
    def _requirements_fingerprint(
        evidence_run_id: str,
        requirements: list[_Requirement],
    ) -> str:
        payload = [
            {
                "asset": item.asset,
                "date": item.price_date.isoformat(),
                "roles": sorted(item.roles),
                "events": sorted(item.event_ids),
            }
            for item in requirements
        ]
        return hashlib.sha256(
            (evidence_run_id + json.dumps(payload, sort_keys=True)).encode("utf-8")
        ).hexdigest()

    def _default_artifact_root(self) -> Path:
        if self.store.path.resolve() == self.DEFAULT_DB.resolve():
            return self.DEFAULT_ARTIFACT_ROOT
        return self.store.path.parent / "var/bmf_event_price_remediation"

    @classmethod
    def _display_path(cls, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(cls.PROJECT_ROOT.resolve()))
        except ValueError:
            return str(path.resolve())

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)

    @staticmethod
    def _decimal(value: object) -> Decimal:
        try:
            return Decimal(str(value))
        except Exception:
            return Decimal("0")

    @staticmethod
    def _sha256_bytes(value: bytes) -> str:
        return hashlib.sha256(value).hexdigest()
