from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json

from fastapi.testclient import TestClient
import httpx

from steuerreport_v2.api.app import create_app
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.legal_research import LegalResearchService


NOW = datetime(2026, 8, 24, 6, 45, tzinfo=timezone.utc)
LAW_URL = "https://www.gesetze-im-internet.de/estg/__23.html"
SITEMAP_URL = "https://www.bundesfinanzministerium.de/sitemap.xml"
BMF_URL = (
    "https://www.bundesfinanzministerium.de/Content/DE/Downloads/BMF_Schreiben/"
    "Steuerarten/Einkommensteuer/2025-03-06-einzelfragen-kryptowerte.html"
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _config(
    path,
    *,
    reviewed_urls=None,
    monitors=None,
    freshness_hours=36,
    reviewed_sha256=None,
):
    payload = {
        "registry_version": "test-v1",
        "freshness_hours": freshness_hours,
        "sources": [
            {
                "source_id": "estg-23",
                "title": "EStG 23",
                "authority": "gesetze_im_internet",
                "kind": "law_section",
                "url": LAW_URL,
                "reviewed_sha256": reviewed_sha256 or _digest("law"),
                "required": True,
            }
        ],
        "monitors": monitors
        or [
            {
                "monitor_id": "bmf-sitemap",
                "title": "BMF Sitemap",
                "authority": "bundesfinanzministerium",
                "mode": "sitemap",
                "url": SITEMAP_URL,
                "keywords": ["kryptowerte"],
                "reviewed_urls": reviewed_urls or [BMF_URL],
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _sitemap(*urls):
    nodes = "".join(f"<url><loc>{url}</loc></url>" for url in urls)
    return f'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{nodes}</urlset>'


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_legal_research_run_is_fresh_with_reachable_unchanged_reviewed_sources(tmp_path):
    def handler(request):
        if str(request.url) == LAW_URL:
            return httpx.Response(200, text="<html><body>Paragraph 23 current</body></html>")
        if str(request.url) == SITEMAP_URL:
            return httpx.Response(200, text=_sitemap(BMF_URL), headers={"content-type": "application/xml"})
        raise AssertionError(str(request.url))

    with _client(handler) as client:
        service = LegalResearchService(
            config_path=_config(
                tmp_path / "legal.json",
                reviewed_sha256=_digest("Paragraph 23 current"),
            ),
            artifact_root=tmp_path / "runs",
            client=client,
            now=lambda: NOW,
        )
        report = service.run()

    assert report.status == "fresh"
    assert report.is_fresh is True
    assert report.official_sources_reachable is True
    assert report.discovery_hits[0].review_status == "reviewed"
    assert report.source_checks[0].content_sha256
    assert service.latest() == report
    assert (tmp_path / "runs/latest_legal_research_freshness.json").is_file()


def test_legal_research_detects_changed_primary_source_against_previous_run(tmp_path):
    state = {"content": "first"}

    def handler(request):
        if str(request.url) == LAW_URL:
            return httpx.Response(200, text=f"<html><body>{state['content']}</body></html>")
        if str(request.url) == SITEMAP_URL:
            return httpx.Response(200, text=_sitemap(BMF_URL))
        raise AssertionError(str(request.url))

    with _client(handler) as client:
        service = LegalResearchService(
            config_path=_config(
                tmp_path / "legal.json", reviewed_sha256=_digest("first")
            ),
            artifact_root=tmp_path / "runs",
            client=client,
            now=lambda: NOW,
        )
        first = service.run()
        state["content"] = "second"
        second = service.run()
        third = service.run()

    assert first.status == "fresh"
    assert second.status == "review_required"
    assert second.is_fresh is False
    assert second.changed_source_ids == ["estg-23"]
    assert second.source_checks[0].previous_sha256 == first.source_checks[0].content_sha256
    assert third.status == "review_required"
    assert third.changed_source_ids == ["estg-23"]
    assert third.source_checks[0].previous_sha256 == first.source_checks[0].content_sha256


def test_legal_research_keeps_unknown_official_discovery_fail_closed(tmp_path):
    new_url = "https://www.bundesfinanzministerium.de/Content/DE/2026-08-24-neue-kryptowerte-regel.html"

    def handler(request):
        if str(request.url) == LAW_URL:
            return httpx.Response(200, text="law")
        if str(request.url) == SITEMAP_URL:
            return httpx.Response(200, text=_sitemap(BMF_URL, new_url))
        raise AssertionError(str(request.url))

    with _client(handler) as client:
        report = LegalResearchService(
            config_path=_config(tmp_path / "legal.json"),
            artifact_root=tmp_path / "runs",
            client=client,
            now=lambda: NOW,
        ).run()

    assert report.status == "review_required"
    assert report.review_required_urls == [new_url]
    assert next(hit for hit in report.discovery_hits if hit.url == new_url).review_status == "review_required"


def test_legal_research_reopens_review_when_official_sitemap_lastmod_changes(tmp_path):
    config_path = _config(tmp_path / "legal.json")
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["monitors"][0]["reviewed_url_last_modified"] = {BMF_URL: "2025-03-07"}
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    sitemap = (
        '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        f"<url><loc>{BMF_URL}</loc><lastmod>2026-08-24</lastmod></url></urlset>"
    )

    def handler(request):
        if str(request.url) == LAW_URL:
            return httpx.Response(200, text="law")
        return httpx.Response(200, text=sitemap)

    with _client(handler) as client:
        report = LegalResearchService(
            config_path=config_path,
            artifact_root=tmp_path / "runs",
            client=client,
            now=lambda: NOW,
        ).run()

    assert report.status == "review_required"
    assert report.review_required_urls == [BMF_URL]
    assert report.discovery_hits[0].source_updated_at == datetime(
        2026, 8, 24, tzinfo=timezone.utc
    )


def test_legal_research_required_source_failure_has_priority_over_new_hits(tmp_path):
    new_url = "https://www.bundesfinanzministerium.de/Content/DE/2026-08-24-neue-kryptowerte-regel.html"

    def handler(request):
        if str(request.url) == LAW_URL:
            return httpx.Response(503, text="unavailable")
        if str(request.url) == SITEMAP_URL:
            return httpx.Response(200, text=_sitemap(new_url))
        raise AssertionError(str(request.url))

    with _client(handler) as client:
        report = LegalResearchService(
            config_path=_config(tmp_path / "legal.json"),
            artifact_root=tmp_path / "runs",
            client=client,
            now=lambda: NOW,
        ).run()

    assert report.status == "error"
    assert report.is_fresh is False
    assert report.official_sources_reachable is False
    assert report.failed_check_ids == ["estg-23"]
    assert report.review_required_urls == [new_url]


def test_legal_research_parses_bfh_results_and_rss_with_review_registry(tmp_path):
    bfh_url = "https://www.bundesfinanzhof.de/de/entscheidungen/entscheidungen-online/"
    decision_url = "https://www.bundesfinanzhof.de/de/entscheidung/entscheidungen-online/detail/STRE202650119/"
    rss_url = "https://www.bundestag.de/static/appdata/includes/rss/finanzen.rss"
    legislation_url = "https://www.bundestag.de/presse/hib/kurzmeldungen-1234567"
    monitors = [
        {
            "monitor_id": "bfh",
            "title": "BFH",
            "authority": "bundesfinanzhof",
            "mode": "bfh_search",
            "url": bfh_url,
            "queries": ["private Veräußerungsgeschäfte"],
        },
        {
            "monitor_id": "bundestag",
            "title": "Bundestag",
            "authority": "bundestag",
            "mode": "rss",
            "url": rss_url,
            "keywords": ["Kryptowerte"],
            "reviewed_urls": [legislation_url],
        },
    ]

    def handler(request):
        if str(request.url) == LAW_URL:
            return httpx.Response(200, text="law")
        if request.url.host == "www.bundesfinanzhof.de":
            return httpx.Response(
                200,
                text=f'<a href="{decision_url}">Fristberechnung bei privaten Veräußerungsgeschäften</a>',
            )
        if str(request.url) == rss_url:
            return httpx.Response(
                200,
                text=(
                    "<rss><channel><item><title>Kryptowerte im Finanzausschuss</title>"
                    f"<link>{legislation_url}</link><pubDate>Mon, 24 Aug 2026 06:00:00 GMT</pubDate>"
                    "</item></channel></rss>"
                ),
            )
        raise AssertionError(str(request.url))

    with _client(handler) as client:
        report = LegalResearchService(
            config_path=_config(tmp_path / "legal.json", monitors=monitors),
            artifact_root=tmp_path / "runs",
            client=client,
            now=lambda: NOW,
        ).run()

    assert report.status == "review_required"
    hits = {hit.url: hit for hit in report.discovery_hits}
    assert hits[decision_url].review_status == "review_required"
    assert hits[legislation_url].review_status == "reviewed"
    assert hits[legislation_url].published_at == datetime(2026, 8, 24, 6, 0, tzinfo=timezone.utc)


def test_legal_research_latest_becomes_stale_without_mutating_artifact(tmp_path):
    def handler(request):
        if str(request.url) == LAW_URL:
            return httpx.Response(200, text="law")
        return httpx.Response(200, text=_sitemap(BMF_URL))

    current = {"now": NOW}
    with _client(handler) as client:
        service = LegalResearchService(
            config_path=_config(tmp_path / "legal.json", freshness_hours=1),
            artifact_root=tmp_path / "runs",
            client=client,
            now=lambda: current["now"],
        )
        report = service.run()
        current["now"] = NOW + timedelta(hours=2)
        stale = service.latest()

    assert report.status == "fresh"
    assert stale is not None
    assert stale.status == "stale"
    assert stale.is_fresh is False
    persisted = json.loads((tmp_path / "runs/latest_legal_research_freshness.json").read_text())
    assert persisted["status"] == "fresh"


def test_bundestag_press_footer_date_does_not_change_content_fingerprint():
    def response(day: str) -> httpx.Response:
        return httpx.Response(
            200,
            request=httpx.Request(
                "GET",
                "https://www.bundestag.de/presse/hib/kurzmeldungen-1179034",
            ),
            headers={"content-type": "text/html"},
            text=(
                "<html><body><main>Gesetzentwurf im Ausschuss gescheitert.</main>"
                f"<footer>Stand: {day}</footer></body></html>"
            ),
        )

    first = LegalResearchService._normalized_content(response("25.08.2026"))
    second = LegalResearchService._normalized_content(response("26.08.2026"))

    assert first == second
    assert first == b"Gesetzentwurf im Ausschuss gescheitert."


def test_legal_research_api_exposes_registry_and_latest_without_network_call(tmp_path, monkeypatch):
    def handler(request):
        if str(request.url) == LAW_URL:
            return httpx.Response(200, text="law")
        return httpx.Response(200, text=_sitemap(BMF_URL))

    config_path = _config(tmp_path / "legal.json")
    artifact_root = tmp_path / "runs"
    api_now = datetime.now(timezone.utc)
    with _client(handler) as client:
        LegalResearchService(
            config_path=config_path,
            artifact_root=artifact_root,
            client=client,
            now=lambda: api_now,
        ).run()
    monkeypatch.setattr(LegalResearchService, "DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.setattr(LegalResearchService, "DEFAULT_ARTIFACT_ROOT", artifact_root)
    client = TestClient(create_app(DuckDbStore(tmp_path / "db.duckdb")))

    sources = client.get("/api/v1/tax-methodology/legal-research/sources")
    freshness = client.get("/api/v1/tax-methodology/legal-research/freshness")

    assert sources.status_code == 200
    assert sources.json()["data"]["registry_version"] == "test-v1"
    assert freshness.status_code == 200
    assert freshness.json()["data"]["status"] == "fresh"
