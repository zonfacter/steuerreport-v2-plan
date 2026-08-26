from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


LegalAuthority = Literal[
    "bundesfinanzministerium",
    "bundesfinanzhof",
    "bundestag",
    "gesetze_im_internet",
]
LegalSourceKind = Literal["law_section", "administrative_guidance", "court_decision", "legislation"]
LegalMonitorMode = Literal["sitemap", "bfh_search", "rss"]
LegalCheckStatus = Literal["ok", "changed", "error"]
LegalFreshnessStatus = Literal["fresh", "review_required", "error", "stale", "missing"]


class LegalResearchSource(BaseModel):
    source_id: str
    title: str
    authority: LegalAuthority
    kind: LegalSourceKind
    url: str
    reviewed_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    required: bool = True
    relevance_tags: list[str] = Field(default_factory=list)
    note: str | None = None


class LegalResearchMonitor(BaseModel):
    monitor_id: str
    title: str
    authority: LegalAuthority
    mode: LegalMonitorMode
    url: str
    keywords: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    reviewed_urls: list[str] = Field(default_factory=list)
    reviewed_url_last_modified: dict[str, str] = Field(default_factory=dict)
    ignored_urls: list[str] = Field(default_factory=list)
    required: bool = True
    max_results: int = 25


class LegalResearchConfig(BaseModel):
    registry_version: str
    freshness_hours: int = 36
    sources: list[LegalResearchSource] = Field(default_factory=list)
    monitors: list[LegalResearchMonitor] = Field(default_factory=list)


class LegalSourceCheck(BaseModel):
    source_id: str
    title: str
    authority: LegalAuthority
    kind: LegalSourceKind
    url: str
    required: bool
    checked_at: datetime
    status: LegalCheckStatus
    http_status: int | None = None
    content_sha256: str | None = None
    previous_sha256: str | None = None
    changed: bool = False
    content_bytes: int = 0
    error: str | None = None


class LegalDiscoveryHit(BaseModel):
    monitor_id: str
    authority: LegalAuthority
    title: str
    url: str
    published_at: datetime | None = None
    source_updated_at: datetime | None = None
    matched_terms: list[str] = Field(default_factory=list)
    review_status: Literal["reviewed", "review_required"]


class LegalMonitorCheck(BaseModel):
    monitor_id: str
    title: str
    authority: LegalAuthority
    mode: LegalMonitorMode
    url: str
    required: bool
    checked_at: datetime
    status: Literal["ok", "error"]
    http_status: int | None = None
    hits_count: int = 0
    review_required_count: int = 0
    error: str | None = None


class LegalResearchFreshnessReport(BaseModel):
    generated_at: datetime
    fresh_until: datetime
    registry_version: str
    status: LegalFreshnessStatus
    is_fresh: bool
    official_sources_reachable: bool
    source_checks: list[LegalSourceCheck] = Field(default_factory=list)
    monitor_checks: list[LegalMonitorCheck] = Field(default_factory=list)
    discovery_hits: list[LegalDiscoveryHit] = Field(default_factory=list)
    changed_source_ids: list[str] = Field(default_factory=list)
    failed_check_ids: list[str] = Field(default_factory=list)
    review_required_urls: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    artifact_path: str
    config_path: str
    methodology: str
