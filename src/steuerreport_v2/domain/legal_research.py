from __future__ import annotations

from steuerreport_v2.paths import PROJECT_ROOT as SOFTWARE_ROOT

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from typing import Callable
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx

from steuerreport_v2.contracts.legal_research import (
    LegalDiscoveryHit,
    LegalMonitorCheck,
    LegalResearchConfig,
    LegalResearchFreshnessReport,
    LegalResearchMonitor,
    LegalSourceCheck,
)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)


class _BfhResultParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self._anchor: tuple[str, list[str]] | None = None
        self.results: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href:
            self._anchor = (href, [])

    def handle_data(self, data: str) -> None:
        if self._anchor is not None:
            self._anchor[1].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._anchor is None:
            return
        href, parts = self._anchor
        if "/entscheidung/entscheidungen-online/detail/" in href:
            title = " ".join("".join(parts).split())
            if title:
                self.results.append((urljoin(self.base_url, href), title))
        self._anchor = None


class LegalResearchService:
    PROJECT_ROOT = SOFTWARE_ROOT
    DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs/legal_research_sources.json"
    DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT / "var/legal_research_freshness"
    ALLOWED_HOSTS = {
        "www.bundesfinanzministerium.de",
        "bundesfinanzministerium.de",
        "www.bundesfinanzhof.de",
        "bundesfinanzhof.de",
        "www.bundestag.de",
        "bundestag.de",
        "dserver.bundestag.de",
        "www.gesetze-im-internet.de",
        "gesetze-im-internet.de",
    }
    USER_AGENT = "Steuerreport-V2-Legal-Freshness-Monitor/1.0"

    def __init__(
        self,
        *,
        config_path: Path | None = None,
        artifact_root: Path | None = None,
        client: httpx.Client | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self.artifact_root = artifact_root or self.DEFAULT_ARTIFACT_ROOT
        self.client = client
        self._now = now or (lambda: datetime.now(timezone.utc))

    def config(self) -> LegalResearchConfig:
        config = LegalResearchConfig.model_validate_json(
            self.config_path.read_text(encoding="utf-8")
        )
        self._validate_config(config)
        return config

    def run(self) -> LegalResearchFreshnessReport:
        config = self.config()
        if self.client is not None:
            return self._run(config, self.client)
        with httpx.Client(
            timeout=httpx.Timeout(45.0, connect=15.0),
            follow_redirects=True,
            headers={"User-Agent": self.USER_AGENT, "Accept": "*/*"},
        ) as client:
            return self._run(config, client)

    def latest(self) -> LegalResearchFreshnessReport | None:
        report = self._load_latest()
        if report is None:
            return None
        now = self._as_utc(self._now())
        if now <= report.fresh_until:
            return report
        findings = list(report.findings)
        stale_finding = (
            f"Rechtsquellen-Pruefung ist seit {report.fresh_until.isoformat()} abgelaufen."
        )
        if stale_finding not in findings:
            findings.append(stale_finding)
        return report.model_copy(
            update={
                "status": "stale",
                "is_fresh": False,
                "findings": findings,
                "next_actions": [
                    "Rechtsquellen-Monitor erneut ausfuehren, bevor aktuelle Rechtsaussagen verwendet werden."
                ],
            }
        )

    def _run(
        self,
        config: LegalResearchConfig,
        client: httpx.Client,
    ) -> LegalResearchFreshnessReport:
        generated_at = self._as_utc(self._now())
        source_checks = [
            self._check_source(source, source.reviewed_sha256, client, generated_at)
            for source in config.sources
        ]
        monitor_checks: list[LegalMonitorCheck] = []
        discovery_hits: list[LegalDiscoveryHit] = []
        for monitor in config.monitors:
            check, hits = self._check_monitor(monitor, client, generated_at)
            monitor_checks.append(check)
            discovery_hits.extend(hits)
        discovery_hits = self._deduplicate_hits(discovery_hits)

        failed_check_ids = [
            check.source_id
            for check in source_checks
            if check.required and check.status == "error"
        ] + [
            check.monitor_id
            for check in monitor_checks
            if check.required and check.status == "error"
        ]
        changed_source_ids = [
            check.source_id for check in source_checks if check.changed
        ]
        review_required_urls = sorted(
            {hit.url for hit in discovery_hits if hit.review_status == "review_required"}
        )
        official_sources_reachable = not failed_check_ids
        if failed_check_ids:
            status = "error"
        elif changed_source_ids or review_required_urls:
            status = "review_required"
        else:
            status = "fresh"
        is_fresh = status == "fresh"
        fresh_until = generated_at + timedelta(hours=config.freshness_hours)
        artifact_path = self.artifact_root / "latest_legal_research_freshness.json"
        report = LegalResearchFreshnessReport(
            generated_at=generated_at,
            fresh_until=fresh_until,
            registry_version=config.registry_version,
            status=status,
            is_fresh=is_fresh,
            official_sources_reachable=official_sources_reachable,
            source_checks=source_checks,
            monitor_checks=monitor_checks,
            discovery_hits=discovery_hits,
            changed_source_ids=changed_source_ids,
            failed_check_ids=failed_check_ids,
            review_required_urls=review_required_urls,
            findings=self._findings(
                failed_check_ids=failed_check_ids,
                changed_source_ids=changed_source_ids,
                review_required_urls=review_required_urls,
            ),
            next_actions=self._next_actions(
                failed_check_ids=failed_check_ids,
                changed_source_ids=changed_source_ids,
                review_required_urls=review_required_urls,
            ),
            artifact_path=self._display_path(artifact_path),
            config_path=self._display_path(self.config_path),
            methodology=(
                "Fail-closed Aktualitaetskontrolle gegen versionierte offizielle Quellen. "
                "Konsolidierte Gesetzestexte und bekannte Primaerdokumente werden inhaltlich "
                "normalisiert und per SHA-256 mit einer explizit fachlich geprueften "
                "Registry-Baseline verglichen. Ein Lauf darf diese Baseline niemals selbst "
                "fortschreiben. Offizielle "
                "Sitemaps, BFH-Suchergebnisse und Bundestags-RSS-Feeds werden nach neuen "
                "relevanten Fundstellen durchsucht. Ein Quellenfehler, eine Inhaltsaenderung "
                "oder eine noch nicht in der Registry gepruefte Fundstelle verhindert den "
                "Status fresh. Der Monitor veraendert niemals Steuerregeln, Ledger, FIFO-Lots "
                "oder Steuerwerte automatisch; Rechtsaenderungen werden erst nach dokumentierter "
                "fachlicher Pruefung in die deterministische Methodik uebernommen."
            ),
        )
        content = json.dumps(
            report.model_dump(mode="json"), indent=2, ensure_ascii=False
        ).encode("utf-8")
        self._atomic_write(artifact_path, content)
        versioned_path = self.artifact_root / (
            "legal_research_freshness_"
            f"{generated_at.strftime('%Y%m%dT%H%M%S%fZ')}.json"
        )
        self._atomic_write(versioned_path, content)
        return report

    def _check_source(
        self,
        source,
        previous_sha256: str | None,
        client: httpx.Client,
        checked_at: datetime,
    ) -> LegalSourceCheck:
        try:
            response = client.get(source.url)
            response.raise_for_status()
            self._assert_official_url(str(response.url))
            content = self._normalized_content(response)
            digest = hashlib.sha256(content).hexdigest()
            changed = previous_sha256 is not None and previous_sha256 != digest
            return LegalSourceCheck(
                source_id=source.source_id,
                title=source.title,
                authority=source.authority,
                kind=source.kind,
                url=source.url,
                required=source.required,
                checked_at=checked_at,
                status="changed" if changed else "ok",
                http_status=response.status_code,
                content_sha256=digest,
                previous_sha256=previous_sha256,
                changed=changed,
                content_bytes=len(content),
            )
        except (httpx.HTTPError, ValueError) as exc:
            return LegalSourceCheck(
                source_id=source.source_id,
                title=source.title,
                authority=source.authority,
                kind=source.kind,
                url=source.url,
                required=source.required,
                checked_at=checked_at,
                status="error",
                previous_sha256=previous_sha256,
                error=self._error_text(exc),
            )

    def _check_monitor(
        self,
        monitor: LegalResearchMonitor,
        client: httpx.Client,
        checked_at: datetime,
    ) -> tuple[LegalMonitorCheck, list[LegalDiscoveryHit]]:
        try:
            if monitor.mode == "sitemap":
                response = client.get(monitor.url)
                response.raise_for_status()
                self._assert_official_url(str(response.url))
                hits = self._sitemap_hits(monitor, response.content)
                http_status = response.status_code
            elif monitor.mode == "bfh_search":
                hits, http_status = self._bfh_hits(monitor, client)
            elif monitor.mode == "rss":
                response = client.get(monitor.url)
                response.raise_for_status()
                self._assert_official_url(str(response.url))
                hits = self._rss_hits(monitor, response.content)
                http_status = response.status_code
            else:
                raise ValueError(f"Nicht unterstuetzter Monitor-Modus: {monitor.mode}")
            hits = hits[: monitor.max_results]
            review_required_count = sum(
                hit.review_status == "review_required" for hit in hits
            )
            return (
                LegalMonitorCheck(
                    monitor_id=monitor.monitor_id,
                    title=monitor.title,
                    authority=monitor.authority,
                    mode=monitor.mode,
                    url=monitor.url,
                    required=monitor.required,
                    checked_at=checked_at,
                    status="ok",
                    http_status=http_status,
                    hits_count=len(hits),
                    review_required_count=review_required_count,
                ),
                hits,
            )
        except (httpx.HTTPError, ElementTree.ParseError, ValueError) as exc:
            return (
                LegalMonitorCheck(
                    monitor_id=monitor.monitor_id,
                    title=monitor.title,
                    authority=monitor.authority,
                    mode=monitor.mode,
                    url=monitor.url,
                    required=monitor.required,
                    checked_at=checked_at,
                    status="error",
                    error=self._error_text(exc),
                ),
                [],
            )

    def _sitemap_hits(
        self, monitor: LegalResearchMonitor, content: bytes
    ) -> list[LegalDiscoveryHit]:
        root = ElementTree.fromstring(content)
        hits: list[LegalDiscoveryHit] = []
        for element in root.iter():
            if self._local_name(element.tag) != "url":
                continue
            values = {
                self._local_name(child.tag): (child.text or "").strip()
                for child in element
            }
            url = self._canonical_url(values.get("loc", ""))
            matched = self._matched_terms(url, monitor.keywords)
            if not matched or url in monitor.ignored_urls:
                continue
            source_updated_at = self._parse_date(values.get("lastmod"))
            hits.append(
                self._hit(
                    monitor,
                    title=self._title_from_url(url),
                    url=url,
                    matched_terms=matched,
                    published_at=self._date_from_text(url),
                    source_updated_at=source_updated_at,
                )
            )
        return sorted(hits, key=lambda item: (item.published_at or datetime.min.replace(tzinfo=timezone.utc), item.url), reverse=True)

    def _bfh_hits(
        self, monitor: LegalResearchMonitor, client: httpx.Client
    ) -> tuple[list[LegalDiscoveryHit], int]:
        hits: list[LegalDiscoveryHit] = []
        status = 200
        for query in monitor.queries:
            response = client.get(
                monitor.url,
                params={
                    "tx_solr[action]": "results",
                    "tx_solr[controller]": "Search",
                    "tx_solr[q]": query,
                    "tx_solr[searchTerms][sorting]": "publishingDateDesc",
                },
            )
            response.raise_for_status()
            self._assert_official_url(str(response.url))
            status = response.status_code
            parser = _BfhResultParser(monitor.url)
            parser.feed(response.text)
            for url, title in parser.results:
                url = self._canonical_url(url)
                if url in monitor.ignored_urls:
                    continue
                hits.append(
                    self._hit(
                        monitor,
                        title=title,
                        url=url,
                        matched_terms=[query],
                    )
                )
        return self._deduplicate_hits(hits), status

    def _rss_hits(
        self, monitor: LegalResearchMonitor, content: bytes
    ) -> list[LegalDiscoveryHit]:
        root = ElementTree.fromstring(content)
        hits: list[LegalDiscoveryHit] = []
        for item in root.iter():
            if self._local_name(item.tag) not in {"item", "entry"}:
                continue
            values: dict[str, str] = {}
            atom_link: str | None = None
            for child in item:
                name = self._local_name(child.tag)
                if name == "link" and child.attrib.get("href"):
                    atom_link = child.attrib["href"]
                elif child.text:
                    values[name] = child.text.strip()
            url = self._canonical_url(values.get("link") or atom_link or "")
            title = " ".join(values.get("title", "").split())
            haystack = " ".join(
                [title, values.get("description", ""), values.get("summary", ""), url]
            )
            matched = self._matched_terms(haystack, monitor.keywords)
            if not url or not matched or url in monitor.ignored_urls:
                continue
            published = (
                values.get("pubDate")
                or values.get("published")
                or values.get("updated")
                or values.get("date")
            )
            hits.append(
                self._hit(
                    monitor,
                    title=title or self._title_from_url(url),
                    url=url,
                    matched_terms=matched,
                    published_at=self._parse_date(published),
                )
            )
        return sorted(hits, key=lambda item: (item.published_at or datetime.min.replace(tzinfo=timezone.utc), item.url), reverse=True)

    def _hit(
        self,
        monitor: LegalResearchMonitor,
        *,
        title: str,
        url: str,
        matched_terms: list[str],
        published_at: datetime | None = None,
        source_updated_at: datetime | None = None,
    ) -> LegalDiscoveryHit:
        reviewed = url in monitor.reviewed_urls
        reviewed_last_modified = monitor.reviewed_url_last_modified.get(url)
        if reviewed and reviewed_last_modified is not None:
            reviewed = (
                source_updated_at is not None
                and source_updated_at.date().isoformat() == reviewed_last_modified
            )
        return LegalDiscoveryHit(
            monitor_id=monitor.monitor_id,
            authority=monitor.authority,
            title=title,
            url=url,
            published_at=published_at,
            source_updated_at=source_updated_at,
            matched_terms=matched_terms,
            review_status="reviewed" if reviewed else "review_required",
        )

    @staticmethod
    def _deduplicate_hits(hits: list[LegalDiscoveryHit]) -> list[LegalDiscoveryHit]:
        by_url: dict[str, LegalDiscoveryHit] = {}
        for hit in hits:
            existing = by_url.get(hit.url)
            if existing is None:
                by_url[hit.url] = hit
                continue
            existing.matched_terms = sorted(
                set(existing.matched_terms) | set(hit.matched_terms)
            )
            if hit.review_status == "review_required":
                existing.review_status = "review_required"
        return sorted(
            by_url.values(),
            key=lambda item: (
                item.review_status == "review_required",
                item.published_at or datetime.min.replace(tzinfo=timezone.utc),
                item.url,
            ),
            reverse=True,
        )

    def _validate_config(self, config: LegalResearchConfig) -> None:
        if config.freshness_hours < 1 or config.freshness_hours > 168:
            raise ValueError("freshness_hours muss zwischen 1 und 168 liegen")
        ids = [source.source_id for source in config.sources] + [
            monitor.monitor_id for monitor in config.monitors
        ]
        if len(ids) != len(set(ids)):
            raise ValueError("Source- und Monitor-IDs muessen eindeutig sein")
        if not config.sources or not config.monitors:
            raise ValueError("Mindestens eine Direktquelle und ein Monitor sind erforderlich")
        for source in config.sources:
            self._assert_official_url(source.url)
        for monitor in config.monitors:
            self._assert_official_url(monitor.url)
            if monitor.mode == "bfh_search" and not monitor.queries:
                raise ValueError(f"{monitor.monitor_id}: BFH-Suche braucht queries")
            if monitor.mode in {"sitemap", "rss"} and not monitor.keywords:
                raise ValueError(f"{monitor.monitor_id}: Monitor braucht keywords")
            for url in monitor.reviewed_urls + monitor.ignored_urls:
                self._assert_official_url(url)
            for url, last_modified in monitor.reviewed_url_last_modified.items():
                self._assert_official_url(url)
                if url not in monitor.reviewed_urls:
                    raise ValueError(
                        f"{monitor.monitor_id}: lastmod ohne reviewed URL: {url}"
                    )
                if not re.fullmatch(r"20\d{2}-\d{2}-\d{2}", last_modified):
                    raise ValueError(
                        f"{monitor.monitor_id}: ungueltiges reviewed lastmod: {last_modified}"
                    )

    def _assert_official_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname not in self.ALLOWED_HOSTS:
            raise ValueError(f"Nicht freigegebene offizielle Quelle: {parsed.hostname or url}")

    @staticmethod
    def _normalized_content(response: httpx.Response) -> bytes:
        content_type = response.headers.get("content-type", "").casefold()
        if "html" not in content_type and not response.text.lstrip().startswith("<"):
            return response.content
        parser = _VisibleTextParser()
        parser.feed(response.text)
        normalized = " ".join(" ".join(parser.parts).split())
        parsed_url = urlparse(str(response.url))
        if (
            parsed_url.hostname in {"bundestag.de", "www.bundestag.de"}
            and parsed_url.path.startswith("/presse/hib/kurzmeldungen-")
        ):
            normalized = re.sub(
                r"\s+Stand:\s+\d{2}\.\d{2}\.\d{4}\s*$",
                "",
                normalized,
            )
        return normalized.encode("utf-8")

    @staticmethod
    def _matched_terms(value: str, terms: list[str]) -> list[str]:
        folded = value.casefold()
        return sorted({term for term in terms if term.casefold() in folded})

    @staticmethod
    def _canonical_url(url: str) -> str:
        return unescape(url.strip()).split("#", 1)[0]

    @staticmethod
    def _title_from_url(url: str) -> str:
        slug = urlparse(url).path.rstrip("/").rsplit("/", 1)[-1]
        slug = re.sub(r"\.(html|pdf|xml)$", "", slug, flags=re.IGNORECASE)
        return " ".join(part for part in slug.replace("_", "-").split("-") if part)

    @staticmethod
    def _date_from_text(value: str) -> datetime | None:
        match = re.search(r"(?<!\d)(20\d{2})-(\d{2})-(\d{2})(?!\d)", value)
        if not match:
            return None
        try:
            return datetime(
                int(match.group(1)), int(match.group(2)), int(match.group(3)), tzinfo=timezone.utc
            )
        except ValueError:
            return None

    @classmethod
    def _parse_date(cls, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return cls._as_utc(parsedate_to_datetime(value))
        except (TypeError, ValueError):
            try:
                return cls._as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
            except ValueError:
                return cls._date_from_text(value)

    @staticmethod
    def _local_name(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _error_text(exc: Exception) -> str:
        return " ".join(str(exc).split())[:500] or exc.__class__.__name__

    def _load_latest(self) -> LegalResearchFreshnessReport | None:
        path = self.artifact_root / "latest_legal_research_freshness.json"
        try:
            return LegalResearchFreshnessReport.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None

    @staticmethod
    def _findings(
        *,
        failed_check_ids: list[str],
        changed_source_ids: list[str],
        review_required_urls: list[str],
    ) -> list[str]:
        findings = []
        if failed_check_ids:
            findings.append(
                f"{len(failed_check_ids)} erforderliche offizielle Quellenpruefung(en) fehlgeschlagen."
            )
        if changed_source_ids:
            findings.append(
                f"{len(changed_source_ids)} bekannte Primaerquelle(n) haben sich inhaltlich geaendert."
            )
        if review_required_urls:
            findings.append(
                f"{len(review_required_urls)} offizielle neue Fundstelle(n) erfordern fachliche Pruefung."
            )
        if not findings:
            findings.append("Alle erforderlichen offiziellen Quellen wurden erfolgreich und ohne offenen Neufund geprueft.")
        return findings

    @staticmethod
    def _next_actions(
        *,
        failed_check_ids: list[str],
        changed_source_ids: list[str],
        review_required_urls: list[str],
    ) -> list[str]:
        actions = []
        if failed_check_ids:
            actions.append(
                "Netzwerk- oder Quellenfehler beheben und den Monitor erneut ausfuehren."
            )
        if changed_source_ids or review_required_urls:
            actions.append(
                "Fundstellen im Original fachlich pruefen und Auswirkung, Gueltigkeitszeitraum sowie Testfall dokumentieren."
            )
            actions.append(
                "Erst nach Review die Registry aktualisieren und gegebenenfalls Steuerregeln versioniert anpassen."
            )
        return actions

    def _display_path(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.PROJECT_ROOT.resolve()))
        except ValueError:
            return str(path)

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_bytes(content)
        temporary.replace(path)
