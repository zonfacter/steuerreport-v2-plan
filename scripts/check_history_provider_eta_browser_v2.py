"""Isolierter Browsernachweis fuer Anbieterwahl und Historien-Restzeit.

Erst nach dem von Main koordinierten Frontend-Build ausfuehren. Kein Build,
kein Server, kein Livebackend: Playwright liefert frontend/dist selbst aus und
beantwortet jede API-Anfrage mit modellvalidierten synthetischen Daten.

PYTHONPATH=src:/tmp/steuerreport-browser-tools python3 \
    scripts/check_history_provider_eta_browser_v2.py --browser-executable \
    /root/.cache/ms-playwright/chromium-1187/chrome-linux/chrome

--browser-executable ist optional; Standard ist der Playwright-Browser.
Alle Nachweise enthalten ausschliesslich synthetische Daten.
"""
from __future__ import annotations

import argparse
from contextlib import suppress
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import mimetypes
from pathlib import Path
import re
import sys
import time
from urllib.parse import unquote, urlparse
from uuid import UUID

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from playwright.sync_api import expect, sync_playwright  # noqa: E402
from steuerreport_v2.contracts.history import (  # noqa: E402
    HistoryJob, HistoryProgress, HistoryResume, HistoryRpcOption, HistoryStart, HistoryView,
)
from check_history_import_browser_v2 import (  # noqa: E402
    HistoryFixture, JOB_IDS, LABELS, OTHER, SOURCE, STAMP,
    confirm_external, count_value, frames, history_path, open_source, workflow,
)

PUBLIC = "\u00d6ffentlicher RPC (Free)"
CONFIGURED = "Eigener Anbieter (Free/Premium)"
SERVICE = "Eingerichteter Dienst"
ORIGIN = "http://127.0.0.1:9"
WIDTHS = (390, 768, 1280, 1440)
SYNTHETIC_SECRET = "SYNTHETIC_NOT_A_REAL_KEY"
SYNTHETIC_RPC_URL = "https://rpc.synthetic.invalid/?api-key=" + SYNTHETIC_SECRET


def option(provider, *, ready=True):
    """Lokale Testbudgets, keine Aussagen ueber Anbieter-Tarife oder Quoten."""
    return HistoryRpcOption(
        id=provider, label={"public": PUBLIC, "helius": "Helius", "alchemy": "Alchemy",
                            "custom": "Eigener RPC", "legacy": "Bisheriger Anbieter"}[provider],
        kind="public" if provider == "public" else "legacy" if provider == "legacy" else "configured",
        provider_id="solana_rpc" if provider == "public" else provider,
        configured=ready, ready=ready,
        blocked_reason=None if ready else "history_rpc_not_configured",
        limits={"available": True, "config_revision": 17, "requests_per_second": 8,
                "requests_per_10_seconds": 15, "requests_per_minute": 30, "max_concurrency": 1,
                "effective_max_requests_per_second": 0.5,
                "budget_groups": ["ip:global", "provider:solana_rpc"],
                "bottlenecks": ["ip:global"], "blocking_reasons": [],
                "waiting_requests": 0, "in_flight": 0},
    ).model_dump(mode="json")


def progress(phase="discovery", **changes):
    value = dict(phase=phase, references_discovered=32, signatures_discovered=20,
                 signatures_total=None, signatures_completed=0,
                 addresses_completed=1, addresses_total=3, inventory_complete=False,
                 estimate_status="unknown_total", updated_at=STAMP)
    value.update(changes)
    return HistoryProgress.model_validate(value).model_dump(mode="json")


def fetching(**changes):
    value = dict(inventory_complete=True, signatures_discovered=100,
                 signatures_total=100, signatures_completed=20, fetch_elapsed_seconds=40,
                 observed_details_per_second=0.5, estimated_fetch_remaining_seconds=160,
                 estimate_status="estimated")
    value.update(changes)
    return progress("fetch", **value)


class ProviderFixture(HistoryFixture):
    def __init__(self):
        super().__init__()
        for ref in LABELS:
            self.capabilities[ref].update(provider="solana", requires_symbols=False,
                rpc_options=[option(provider) for provider in ("public", "helius", "alchemy", "custom")])

    def sources(self):
        return [{**row, "source_type": "solana_wallet", "connector_id": "solana_rpc"}
                for row in super().sources()]

    @staticmethod
    def reply(route, data=None, status=200, code=None):
        if code:
            route.fulfill(status=status, json={"trace_id": "44444444-4444-4444-8444-444444444444",
                "status": "error", "data": None, "errors": [{"code": code,
                "message": "<html>" + SYNTHETIC_RPC_URL + "</html>", "field": None}], "warnings": []})
            return
        if not code and isinstance(data, dict):
            if "capability" in data:
                HistoryView.model_validate(data)
            elif "source_ref" in data and "id" in data:
                HistoryJob.model_validate(data)
        HistoryFixture.reply(route, data, status, code)

    def job(self, ref=SOURCE, status="running", job_id=None, **changes):
        changes.setdefault("transport", option("helius"))
        changes.setdefault("progress", progress())
        return super().job(ref, status, job_id, **changes)

    def accept_start(self, route, ref, body):
        parsed = HistoryStart.model_validate(body)
        assert UUID(body["request_id"]).version == 4
        assert set(body) == {"request_id", "confirm_external_request", "start", "end", "symbols",
                             "rpc_provider", "public_rpc_only", "max_records"}, body
        assert parsed.rpc_provider in {"public", "helius", "alchemy", "custom"}, body
        assert body["public_rpc_only"] is (body["rpc_provider"] == "public"), body
        assert parsed.symbols == [] and parsed.max_records == 100000, body
        selected = next(item for item in self.capabilities[ref].get("rpc_options", [])
                        if item["id"] == parsed.rpc_provider)
        assert selected["ready"], "Nicht eingerichteter Anbieter wurde gestartet"
        value = self.job(ref, "queued", transport=deepcopy(selected), start=body["start"], end=body["end"],
                         records_fetched=0, pages_fetched=0, requests=0, new_records=0,
                         duplicate_records=0, sample_rows=[], progress=progress())
        self.reply(route, value, 202)

    def handle(self, route):
        request = route.request
        path = unquote(urlparse(request.url).path)
        if request.method == "POST" and path.endswith("/resume"):
            HistoryResume.model_validate(request.post_data_json)
        return super().handle(route)


def mode(area, provider):
    area.get_by_role("radio", name=PUBLIC if provider == "public" else CONFIGURED, exact=True).check()
    if provider != "public":
        area.get_by_role("combobox", name=SERVICE, exact=True).select_option(provider)


def start_button(area):
    return area.get_by_role("button", name="Vorschau abrufen", exact=True)


def refresh(area):
    area.get_by_role("button", name="Status aktualisieren", exact=True).click()
    frames(area.page)


def no_estimate(area, *, unknown_total=False):
    estimate = area.locator(".hiEstimate")
    text = (estimate if estimate.count() else area.locator(".hiProgress")).inner_text()
    assert not re.search(r"(?:Restzeit|verbleibend)[^\n]*\b0\s*(?:s|Sek|Min)", text, re.I), text
    assert not re.search(r"(?:ca\.|ungef\u00e4hr)\s*\d", text), text
    if unknown_total:
        assert not re.search(r"\d+(?:[.,]\d+)?\s*%", area.locator(".hiProgress").inner_text())
        expect(area.get_by_role("progressbar")).to_have_count(0)


def layout(area, width):
    page = area.page
    frames(page)
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1"), f"Seitenoverflow {width}"
    panel = page.get_by_role("dialog")
    assert panel.locator(".wsPanelBody").evaluate("el => el.scrollWidth <= el.clientWidth + 1"), f"Paneloverflow {width}"
    problems = area.evaluate("""root => {
      const bounds = root.closest('[role=dialog]').getBoundingClientRect();
      return [...root.querySelectorAll('button,input,select,a,dt,dd,p,th,td,label')].flatMap(el => {
        const box = el.getBoundingClientRect();
        if (!box.width || !box.height || el.closest('.wsTableScroll')) return [];
        const bad = box.left < bounds.left - 1 || box.right > bounds.right + 1 ||
          (el.scrollWidth > el.clientWidth + 1 && getComputedStyle(el).overflowX === 'visible');
        return bad ? [el.outerHTML.slice(0, 200)] : [];
      });
    }""")
    assert not problems, (width, problems)
    # Tabellen duerfen lokal scrollen, Text darf aber keine Nachbarzellen uebermalen.
    collisions = area.locator("td,th").evaluate_all("""cells => cells.flatMap(cell => {
      const range = document.createRange(); range.selectNodeContents(cell);
      const box = cell.getBoundingClientRect();
      return [...range.getClientRects()].some(r => r.left < box.left - 1 || r.right > box.right + 1)
        ? [cell.textContent] : [];
    })""")
    assert not collisions, (width, collisions)


class Run:
    def __init__(self, browser, base, output, assets):
        self.browser, self.base, self.output = browser, base, output
        self.assets = assets
        self.results, self.calls, self.screenshots = {}, [], []
        self.blocked, self.errors, self.violations = [], [], []

    def shot(self, page, name, focus=None):
        if focus is not None:
            focus.scroll_into_view_if_needed()
            frames(page)
        path = self.output / ("synthetic-" + name + ".png")
        page.screenshot(path=str(path), animations="disabled")
        self.screenshots.append({"file": path.name, "synthetic_only": True, "viewport": page.viewport_size})

    def scenario(self, name, check):
        print(name + ": gestartet", flush=True)
        fixture = ProviderFixture()
        context = self.browser.new_context(viewport={"width": 1440, "height": 1000}, service_workers="block")
        context.set_default_timeout(7000)
        context.set_default_navigation_timeout(15000)
        blocked, errors = [], []
        origin = urlparse(self.base)
        dist = (ROOT / "frontend/dist").resolve()

        def guard(route):
            request = route.request
            parsed = urlparse(request.url)
            try:
                if (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc):
                    blocked.append({"kind": "http", "method": request.method, "url": request.url})
                    route.abort("blockedbyclient")
                elif parsed.path.startswith("/api/"):
                    fixture.handle(route)
                elif request.method == "GET" and (parsed.path == "/" or parsed.path.startswith("/assets/")
                                                  or parsed.path in {"/favicon.ico", "/favicon.svg"}):
                    path = (dist / ("index.html" if parsed.path == "/" else unquote(parsed.path).lstrip("/"))).resolve()
                    assert path.is_relative_to(dist), "Buildasset ausserhalb dist"
                    key = str(path.relative_to(dist))
                    assert key in self.assets, "Unbekanntes Buildasset: " + parsed.path
                    route.fulfill(body=self.assets[key], content_type=mimetypes.guess_type(path)[0] or "application/octet-stream")
                else:
                    fixture.unexpected.append({"method": request.method, "path": parsed.path})
                    route.abort("blockedbyclient")
            except Exception as error:
                fixture.violations.append(str(error))
                with suppress(Exception):
                    route.abort("blockedbyclient")

        def socket(route):
            blocked.append({"kind": "websocket", "url": route.url})
            # Kein connect_to_server: Der Socket bleibt ein netzloser Playwright-Stub.
            # close() im Handshake-Callback blockiert aeltere Chromium-Versionen.
            route.on_message(lambda _message: None)

        context.route("**/*", guard)
        context.route_web_socket("**/*", socket)
        context.add_init_script("""
          window.__historyRefreshes = 0;
          addEventListener('steuerreport:refresh', () => window.__historyRefreshes++);
        """)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        started = time.monotonic()
        result = {"passed": False, "synthetic_only": True, "evidence": check.__doc__}
        try:
            metadata = check(page, fixture) or {}
            frames(page)
            assert not errors, errors
            assert not fixture.unexpected, fixture.unexpected
            assert not fixture.violations, fixture.violations
            assert len(blocked) == metadata.get("expected_blocked_requests", 0), blocked
            result.update(metadata)
            result["passed"] = True
        except Exception as error:
            result["error"] = f"{type(error).__name__}: {error}"
            with suppress(Exception):
                self.shot(page, name + "-failure")
        finally:
            self.calls.extend({"scenario": name, **call} for call in fixture.api_calls)
            self.blocked.extend(blocked)
            self.errors.extend(errors)
            self.violations.extend(fixture.violations + fixture.unexpected)
            result["duration_seconds"] = round(time.monotonic() - started, 3)
            self.results[name] = result
            (self.output / "attempt-progress.json").write_text(json.dumps({
                "synthetic_only": True, "complete_suite": False, "scenarios": self.results,
                "screenshots": self.screenshots, "calls": self.calls,
                "blocked_requests": self.blocked, "javascript_errors": self.errors,
                "fixture_violations": self.violations,
            }, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
            context.close()
            print(name + ": " + ("bestanden" if result["passed"] else result["error"]), flush=True)

    def checks(self):
        def provider_start(provider):
            def check(page, fixture):
                """Explizite Anbieterwahl und Consent binden den Startbody; zwei Klicks erzeugen nur einen Auftrag."""
                fixture.hold_start = True
                area = open_source(page, self.base)
                expect(area.get_by_role("radio", name=PUBLIC, exact=True)).not_to_be_checked()
                expect(area.get_by_role("radio", name=CONFIGURED, exact=True)).not_to_be_checked()
                confirm_external(area)
                expect(start_button(area)).to_be_disabled()
                for selected in ("public", "helius", "alchemy", "custom", provider):
                    mode(area, selected)
                    frames(page)
                    assert not fixture.posts(), "Formularwechsel hat Anbieterabruf gestartet"
                area.get_by_label("Von", exact=True).fill("2021-02-03")
                area.get_by_label("Bis", exact=True).fill("2025-04-05")
                expect(area.locator('input[type="password"],input[type="url"]')).to_have_count(0)
                expect(area.get_by_role("checkbox", name=re.compile("Ich best\u00e4tige den externen Anbieterabruf"))).not_to_be_checked()
                confirm_external(area)
                button = start_button(area)
                expect(button).to_be_enabled()
                with page.expect_request(lambda request: request.method == "POST" and request.url.endswith("/history/jobs")):
                    button.evaluate("button => { button.click(); button.click(); }")
                expect(button).to_be_disabled()
                frames(page)
                assert len(fixture.posts()) == 1, fixture.posts()
                body = fixture.posts()[0]["body"]
                assert body["rpc_provider"] == provider and body["public_rpc_only"] is (provider == "public"), body
                assert body["start"] == "2021-02-03" and body["end"] == "2025-04-05", body
                assert body["confirm_external_request"] is True and body["symbols"] == []
                assert fixture.posts()[0]["path"] == history_path(SOURCE) + "/jobs"
                assert fixture.pending_starts[0][1] == SOURCE
                fixture.release_start()
                expect(area.locator(".hiJob .wsBadge")).to_have_text("Wartet auf Abruf")
                expect(area.locator(".hiTransport")).to_contain_text(option(provider)["label"])
                assert len(fixture.jobs[SOURCE]) == 1
                assert page.evaluate("window.__historyRefreshes") == 0
                self.shot(page, "start-" + provider + "-1440", area.locator(".hiTransport"))
            return check

        def missing_credentials(page, fixture):
            """Nicht eingerichtete Anbieter erklaeren die Einrichtung ohne Schluessel-/URL-Eingabe oder stillen Fallback."""
            fixture.capabilities[SOURCE]["rpc_options"] = [option("public"), option("helius", ready=False),
                                                          option("alchemy", ready=False), option("custom", ready=False)]
            area = open_source(page, self.base)
            area.get_by_role("radio", name=CONFIGURED, exact=True).check()
            select = area.get_by_role("combobox", name=SERVICE, exact=True)
            expect(select).to_be_visible()
            # Nicht eingerichtete Optionen duerfen deaktiviert oder als blockierte Auswahl lesbar sein.
            for provider in ("helius", "alchemy", "custom"):
                item = select.locator(f'option[value="{provider}"]')
                expect(item).to_have_count(1)
                if item.is_disabled():
                    continue
                select.select_option(provider)
                expect(start_button(area)).to_be_disabled()
            expect(area.get_by_role("link", name=re.compile("Einrichtung"))).to_be_visible()
            expect(area).to_contain_text(re.compile("nicht eingerichtet|Zugangsdaten|Einrichtung", re.I))
            expect(area.locator('input[type="password"],input[type="url"]')).to_have_count(0)
            confirm_external(area)
            expect(start_button(area)).to_be_disabled()
            assert not fixture.posts()
            self.shot(page, "missing-credentials-1440")

        def safe_start_error(page, fixture):
            """Providerfehler zeigt Einrichtungshinweis ohne Server-URL/Key; kein Fallback, neuer Provider erfordert neuen bestaetigten Start."""
            fixture.hold_start = True
            area = open_source(page, self.base)
            mode(area, "helius")
            confirm_external(area)
            start_button(area).click()
            expect(start_button(area)).to_be_disabled()
            frames(page)
            first = fixture.posts("/jobs")[0]["body"]
            fixture.release_start("history_rpc_not_configured")
            expect(area.get_by_role("alert")).to_contain_text("Einrichtung")
            expect(area).not_to_contain_text(SYNTHETIC_SECRET)
            expect(area).not_to_contain_text(SYNTHETIC_RPC_URL)
            assert len(fixture.posts()) == 1 and not fixture.jobs[SOURCE]
            mode(area, "alchemy")
            expect(start_button(area)).to_be_disabled()
            confirm_external(area)
            start_button(area).click()
            expect(start_button(area)).to_be_disabled()
            frames(page)
            second = fixture.posts("/jobs")[-1]["body"]
            assert second["rpc_provider"] == "alchemy" and second["request_id"] != first["request_id"]
            fixture.release_start()
            expect(area.locator(".hiTransport")).to_contain_text("Alchemy")
            assert len(fixture.posts()) == 2 and len(fixture.jobs[SOURCE]) == 1
            self.shot(page, "safe-start-error-1440", area.locator(".hiTransport"))

        def progress_states(page, fixture):
            """Unbekanntes Total, Aufwaermen, gemessene ETA, Pause/Fehler und Vorschauvorbereitung werden getrennt dargestellt."""
            job = fixture.job(progress=progress())
            area = open_source(page, self.base)
            no_estimate(area, unknown_total=True)
            expect(area.locator(".hiProgress")).to_contain_text(re.compile("Signatur|Transaktionsliste", re.I))
            self.shot(page, "discovery-1440", area.locator(".hiProgress"))
            warm = progress("fetch", signatures_discovered=100, signatures_total=100, signatures_completed=0,
                            inventory_complete=True, estimate_status="warming_up")
            fixture.update(job, progress=warm)
            refresh(area)
            expect(area.locator(".hiProgress")).to_contain_text(re.compile("100"))
            no_estimate(area)
            fixture.update(job, progress=fetching())
            refresh(area)
            estimate = area.locator(".hiProgress")
            expect(area.locator(".hiEstimate")).to_have_text("Restzeit Abruf: ca. 3 Minuten")
            expect(estimate).to_contain_text("20")
            expect(estimate).to_contain_text("100")
            expect(estimate).to_contain_text("Messstand:")
            self.shot(page, "estimated-1440", area.locator(".hiEstimate"))
            fixture.job_errors[SOURCE] = "solana_rpc_failed"
            refresh(area)
            expect(area.get_by_role("alert")).to_contain_text("Solana-RPC-Anbieter")
            no_estimate(area)
            expect(count_value(area, "Datens\u00e4tze")).to_have_text("12")
            fixture.job_errors.clear()
            refresh(area)
            expect(area.locator(".hiEstimate")).to_have_text("Restzeit Abruf: ca. 3 Minuten")
            # Selbst widerspruechlich alte ETA-Metadaten duerfen bei Pause/Fehler nicht als Restzeit erscheinen.
            for status, phase in (("paused", "paused"), ("failed", "error")):
                stale = fetching()
                stale["phase"] = phase
                fixture.update(job, status=status, progress=stale, error_code="solana_rpc_failed", can_resume=True)
                refresh(area)
                expect(area.locator(".hiJob .wsBadge")).to_have_text("Pausiert" if status == "paused" else "Fehlgeschlagen")
                no_estimate(area)
                self.shot(page, phase + "-1440", area.locator(".hiEstimate"))
            done = progress("preparing", inventory_complete=True, signatures_discovered=100,
                            signatures_total=100, signatures_completed=100, fetch_elapsed_seconds=200,
                            estimated_fetch_remaining_seconds=0, estimate_status="fetch_complete")
            fixture.update(job, status="running", progress=done, phase="Vorschau wird vorbereitet", error_code=None)
            refresh(area)
            expect(area.locator(".hiProgress")).to_contain_text(re.compile("Vorschau|Vorbereit", re.I))
            expect(area.locator(".hiJob .wsBadge")).not_to_have_text("Import abgeschlossen")
            expect(area.get_by_role("button", name="Importieren und neu berechnen", exact=True)).to_have_count(0)
            assert not re.search(r"Gesamt[^\n]*\b0\s*(?:s|Sek|Min)", area.inner_text(), re.I)
            assert page.evaluate("window.__historyRefreshes") == 0
            assert not fixture.posts()
            self.shot(page, "preparing-not-complete-1440", area.locator(".hiProgress"))

        def provider_wait(page, fixture):
            """Providerpause mit bekannter Wartezeit ist sichtbar; niedriges gemeinsames Budget bleibt wirksam."""
            transport = option("helius")
            transport["limits"].update(blocking_reasons=["provider_pause"], wait_seconds=37,
                                       retry_at="2026-10-27T10:00:37Z", waiting_requests=1)
            job = fixture.job(status="paused", transport=transport, can_resume=True, error_code="rate_limited",
                        progress=progress("paused", signatures_total=100, inventory_complete=True,
                                          signatures_completed=20, estimate_status="paused"))
            page.clock.install(time=datetime(2026, 10, 27, 10, tzinfo=timezone.utc))
            area = open_source(page, self.base)
            no_estimate(area)
            expect(area.locator(".hiTransport")).to_contain_text("Helius")
            expect(area.locator(".hiTransport")).to_contain_text(re.compile("37|10:00:37"))
            expect(area.locator(".hiTransport")).to_contain_text(re.compile("0[,.]5"))
            expect(area.locator(".hiTransport")).to_contain_text("ip:global")
            assert not fixture.posts()
            self.shot(page, "provider-wait-1440", area.locator(".hiTransport"))
            unknown_wait = deepcopy(transport)
            unknown_wait["limits"].update(wait_seconds=None, retry_at=None)
            fixture.update(job, transport=unknown_wait)
            refresh(area)
            expect(area.locator(".hiTransport")).to_contain_text("Wartezeit unbekannt.")
            no_estimate(area)

        def pinned_resume(page, fixture):
            """Formularwechsel aendert weder Auftrag noch Resume-Anbieter; Fortsetzen uebermittelt keine RPC-Auswahl."""
            job = fixture.job(status="paused", transport=option("helius"), can_resume=True,
                              progress=progress("paused", estimate_status="paused"))
            area = open_source(page, self.base)
            for provider in ("public", "alchemy", "custom"):
                mode(area, provider)
                expect(area.locator(".hiTransport")).to_contain_text("Helius")
                frames(page)
                assert not fixture.posts()
            confirm_external(area)
            expect(start_button(area)).to_be_disabled()
            area.get_by_role("checkbox", name=re.compile("Ich best\u00e4tige weitere externe Anbieteranfragen")).check()
            resume = area.get_by_role("button", name="Abruf fortsetzen", exact=True)
            resume.evaluate("button => { button.click(); button.click(); }")
            expect(area.locator(".hiJob .wsBadge")).to_have_text("Abruf l\u00e4uft")
            assert len(fixture.posts("/resume")) == 1
            assert set(fixture.posts("/resume")[0]["body"]) <= {"confirm_external_request", "max_records"}
            assert job["transport"]["id"] == "helius"
            expect(area.locator(".hiTransport")).to_contain_text("Helius")
            self.shot(page, "pinned-resume-1440", area.locator(".hiTransport"))

        def legacy(page, fixture):
            """Alte Antworten ohne rpc_options/transport/progress bleiben lesbar und erfinden weder Anbieter noch ETA."""
            fixture.capabilities[SOURCE].pop("rpc_options")
            job = fixture.job(status="paused", can_resume=True)
            job.pop("transport")
            job.pop("progress")
            area = open_source(page, self.base)
            expect(count_value(area, "Datens\u00e4tze")).to_have_text("12")
            expect(area.locator(".hiTransport")).to_contain_text(re.compile("unbekannt|nicht gespeichert|nicht hinterlegt|nicht verf\u00fcgbar", re.I))
            no_estimate(area, unknown_total=True)
            assert not fixture.posts()
            self.shot(page, "legacy-1440", area.locator(".hiProgress"))

        def cex_unknown(page, fixture):
            """CEX ohne RPC-Progress bekommt keine Solana-Auswahl und keine erfundene Restzeit oder Prozentanzeige."""
            fixture.capabilities[SOURCE].update(provider="binance", requires_symbols=True)
            fixture.capabilities[SOURCE].pop("rpc_options")
            fixture.job(provider="binance", transport=None, progress=None)
            area = open_source(page, self.base)
            expect(area.get_by_label("Handelspaare (kommagetrennt)")).to_be_visible()
            expect(area.get_by_role("radio")).to_have_count(0)
            expect(area.locator(".hiProgress")).to_have_count(0)
            expect(area.get_by_role("progressbar")).to_have_count(0)
            assert not re.search(r"\d+(?:[.,]\d+)?\s*%", area.inner_text())
            assert not re.search(r"Restzeit[^\n]*\b\d+\s*(?:s|Sek|Min)", area.inner_text(), re.I)
            assert not fixture.posts()
            self.shot(page, "cex-unknown-1440")

        def network_guard(page, fixture):
            """Kontrollierte Nichtlokal-HTTP-/API-/WebSocket-Versuche werden vor jedem Netzzugriff abgefangen."""
            open_source(page, self.base)
            for url in ("https://rpc.synthetic.invalid/", "https://api.synthetic.invalid/api/v1/workspace/sources"):
                result = page.evaluate("url => fetch(url).then(() => 'UNEXPECTED').catch(() => 'blocked')", url)
                assert result == "blocked", result
            page.evaluate("""() => {
              const socket = new WebSocket('wss://rpc.synthetic.invalid/');
              socket.onerror = () => {};
              window.__guardSocket = socket;
            }""")
            page.wait_for_function("window.__guardSocket.readyState === WebSocket.OPEN", timeout=7000)
            page.evaluate("window.__guardSocket.close()")
            assert not fixture.posts()
            return {"expected_blocked_requests": 3, "egress_guard_self_test": True,
                    "websocket_stub_never_connected_to_server": True}

        def stale_progress(page, fixture):
            """Ein alter Detailpoll kann einen neueren gespeicherten Fortschritt derselben Quelle nicht zuruecksetzen."""
            job = fixture.job(progress=fetching(), records_fetched=20)
            area = open_source(page, self.base)
            expect(count_value(area, "Datens\u00e4tze")).to_have_text("20")
            page.clock.install()
            path = history_path(SOURCE) + "/jobs/" + JOB_IDS[SOURCE]
            page.evaluate("""path => {
              const original = window.fetch;
              window.__oldPoll = []; window.__holdOldPoll = true;
              window.fetch = (input, init = {}) => {
                if (!window.__holdOldPoll || !String(input).endsWith(path)) return original(input, init);
                const {signal, ...rest} = init;
                return original(input, rest).then(response => new Promise(resolve => {
                  window.__oldPoll.push(() => resolve(response));
                }));
              };
            }""", path)
            page.clock.run_for(2100)
            page.wait_for_function("window.__oldPoll.length > 0")
            fixture.update(job, records_fetched=45,
                           progress=fetching(signatures_completed=45, estimated_fetch_remaining_seconds=110))
            page.evaluate("window.__holdOldPoll = false")
            refresh(area)
            expect(count_value(area, "Datens\u00e4tze")).to_have_text("45")
            page.evaluate("window.__oldPoll.splice(0).forEach(release => release())")
            frames(page)
            expect(count_value(area, "Datens\u00e4tze")).to_have_text("45")
            expect(area.locator(".hiProgress")).to_contain_text("45 / 100")
            expect(area.locator(".hiEstimate")).to_have_text("Restzeit Abruf: ca. 2 Minuten")
            assert not fixture.posts()
            self.shot(page, "stale-progress-1440", area.locator(".hiEstimate"))

        def working_capacity(page, fixture):
            """Normale Parallelitaetsbelegung und kurze Ratecap-Wartezeit unterdruecken keine gemessene ETA; echte Anbieterpause schon."""
            transport = option("helius")
            transport["limits"].update(blocking_reasons=["concurrency"], in_flight=1,
                                       waiting_requests=0, wait_seconds=None)
            job = fixture.job(progress=fetching(), transport=transport)
            area = open_source(page, self.base)
            for reason, wait, waiting in (("concurrency", None, 0), ("rolling_second", 0.2, 1),
                                           ("burst", 0.2, 1)):
                current = deepcopy(transport)
                current["limits"].update(blocking_reasons=[reason], wait_seconds=wait, waiting_requests=waiting)
                fixture.update(job, transport=current)
                refresh(area)
                expect(area.locator(".hiEstimate")).to_have_text("Restzeit Abruf: ca. 3 Minuten")
                expect(area.locator(".hiEstimate")).not_to_contain_text("ausgesetzt")
                self.shot(page, "working-" + reason + "-1440", area.locator(".hiEstimate"))
            paused = deepcopy(transport)
            paused["limits"].update(blocking_reasons=["provider_pause"], wait_seconds=37,
                                      waiting_requests=1, retry_at="2026-10-27T10:00:37Z")
            fixture.update(job, transport=paused)
            refresh(area)
            no_estimate(area)
            expect(area.locator(".hiEstimate")).to_contain_text(re.compile("Wartet|ausgesetzt", re.I))
            assert not fixture.posts()
            self.shot(page, "working-provider-pause-1440", area.locator(".hiEstimate"))

        def responsive(page, fixture):
            """390/768/1280/1440: kein Seiten-/Panel-/Textoverflow; benannte native Auswahl, Fokus und Vorschautabelle."""
            fixture.job(status="ready", transport=option("helius"),
                        progress=progress("complete", inventory_complete=True, signatures_total=100,
                                          signatures_completed=100, signatures_discovered=100,
                                          estimate_status="fetch_complete"))
            area = open_source(page, self.base)
            for width in WIDTHS:
                page.set_viewport_size({"width": width, "height": 1000})
                mode(area, "helius")
                select = area.get_by_role("combobox", name=SERVICE, exact=True)
                select.focus()
                page.keyboard.press("ArrowDown")
                page.keyboard.press("Enter")
                expect(select).to_be_focused()
                assert select.evaluate("el => getComputedStyle(el).outlineStyle !== 'none' && parseFloat(getComputedStyle(el).outlineWidth) >= 2"), "Tastaturfokus ist nicht sichtbar"
                before = select.input_value()
                refresh(area)
                select.focus()
                page.evaluate("window.dispatchEvent(new Event('steuerreport:refresh'))")
                frames(page)
                expect(select).to_be_focused()
                expect(select).to_have_value(before)
                layout(area, width)
                area.locator(".hiContext").scroll_into_view_if_needed()
                self.shot(page, f"provider-{width}")
                area.locator(".hiJob").scroll_into_view_if_needed()
                self.shot(page, f"job-{width}")
                area.locator(".wsTableScroll").scroll_into_view_if_needed()
                self.shot(page, f"table-{width}")
                panel = page.get_by_role("dialog")
                close = panel.get_by_role("button", name="Details schlie\u00dfen", exact=True)
                close.focus()
                page.keyboard.press("Shift+Tab")
                assert page.evaluate("!!document.activeElement.closest('[role=dialog]')")
                page.keyboard.press("Tab")
                expect(close).to_be_focused()
            assert not fixture.posts()

        def source_race(page, fixture):
            """Verspaetete View-/Poll-Antworten trotz ignoriertem Abort ueberschreiben keinen anderen Quellenauftrag."""
            fixture.job(phase="A-RACE-ONLY", transport=option("helius"), progress=fetching())
            fixture.job(OTHER, status="ready", phase="B-ONLY", transport=option("alchemy"), records_fetched=23)
            page.goto(self.base + "/#sources", wait_until="domcontentloaded")
            expect(page.locator(".wsSourceRow")).to_have_count(2)
            page.evaluate("""path => {
              const original = window.fetch;
              window.__releases = []; window.__aborts = 0; window.__hold = path;
              window.fetch = (input, init = {}) => {
                if (!window.__hold || !String(input).endsWith(window.__hold)) return original(input, init);
                init.signal?.addEventListener('abort', () => window.__aborts++);
                const {signal, ...rest} = init;
                return original(input, rest).then(response => new Promise(resolve => {
                  window.__releases.push(() => resolve(response));
                }));
              };
            }""", history_path(SOURCE))

            def enter(ref):
                row = page.locator(".wsSourceRow").filter(has=page.get_by_role("button", name=LABELS[ref], exact=True))
                row.get_by_role("button", name="Transaktionen abrufen", exact=True).click()

            def close():
                page.get_by_role("dialog").get_by_role("button", name="Details schlie\u00dfen", exact=True).click()

            def release():
                page.evaluate("() => { window.__hold = ''; window.__releases.splice(0).forEach(fn => fn()); }")
                frames(page)

            enter(SOURCE)
            page.wait_for_function("window.__releases.length > 0")
            close()
            enter(OTHER)
            expect(count_value(workflow(page), "Datens\u00e4tze")).to_have_text("23")
            release()
            expect(workflow(page).locator(".hiTransport")).to_contain_text("Alchemy")
            expect(workflow(page)).not_to_contain_text("A-RACE-ONLY")
            close()
            enter(SOURCE)
            expect(workflow(page).locator(".hiTransport")).to_contain_text("Helius")
            page.clock.install()
            poll_path = history_path(SOURCE) + "/jobs/" + JOB_IDS[SOURCE]
            page.evaluate("path => window.__hold = path", poll_path)
            page.clock.run_for(2100)
            page.wait_for_function("window.__releases.length > 0")
            close()
            enter(OTHER)
            expect(workflow(page).locator(".hiTransport")).to_contain_text("Alchemy")
            release()
            before = len([call for call in fixture.api_calls if call["path"] == poll_path])
            page.clock.run_for(4500)
            frames(page)
            assert len([call for call in fixture.api_calls if call["path"] == poll_path]) == before
            expect(workflow(page)).not_to_contain_text(JOB_IDS[SOURCE])
            assert page.evaluate("window.__aborts") >= 2
            assert not fixture.posts()
            self.shot(page, "source-race-1440")

        return {**{"start-" + provider: provider_start(provider) for provider in ("public", "helius", "alchemy", "custom")},
                "missing-credentials": missing_credentials, "safe-start-error": safe_start_error,
                "progress-states": progress_states,
                "provider-wait": provider_wait, "pinned-resume": pinned_resume, "legacy": legacy,
                "cex-unknown": cex_unknown,
                "responsive-keyboard": responsive, "source-race": source_race,
                "stale-progress": stale_progress, "network-guard": network_guard,
                "working-capacity": working_capacity}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-executable", help="Optionaler Chromium-Pfad; sonst Playwright-Standard.")
    parser.add_argument("--base-url", default=ORIGIN, help="Synthetischer Loopback-Origin; kein Serverzugriff.")
    parser.add_argument("--output", type=Path, default=Path("/tmp/steuerreport-rc26-history-provider-browser-20261027"))
    parser.add_argument("--scenario", action="append", help="Optional einzelne Szenarien.")
    args = parser.parse_args()
    parsed = urlparse(args.base_url)
    try:
        local = parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname or "").is_loopback
    except ValueError:
        local = False
    if not local or parsed.scheme != "http" or parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username or parsed.password:
        parser.error("Nur lokaler HTTP-Origin ohne Pfad, Query oder Zugangsdaten erlaubt.")
    dist = ROOT / "frontend/dist"
    if not (dist / "index.html").is_file():
        parser.error("Main muss erst das Frontend bauen. Dieses Skript baut und startet keine Server.")
    args.output.mkdir(parents=True, exist_ok=True)
    assets = {str(path.relative_to(dist)): path.read_bytes() for path in sorted(dist.rglob("*")) if path.is_file()}
    started = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    expect.set_options(timeout=7000)
    with sync_playwright() as playwright:
        with playwright.chromium.launch(headless=True, executable_path=args.browser_executable) as browser:
            run = Run(browser, args.base_url.rstrip("/"), args.output, assets)
            checks = run.checks()
            if args.scenario and set(args.scenario) - checks.keys():
                parser.error("Unbekannte Szenarien: " + ", ".join(sorted(set(args.scenario) - checks.keys())))
            for name, check in checks.items():
                if not args.scenario or name in args.scenario:
                    run.scenario(name, check)
    report = dict(synthetic_only=True, actual_frontend=True, actual_backend_tested=False,
                  response_models_validated=True, external_network_blocked=True,
                  no_server_started=True, no_live_wallets_or_credentials=True,
                  passed=all(result["passed"] for result in run.results.values()),
                  started_at=started_at, duration_seconds=round(time.monotonic() - started, 3),
                  complete_suite=not args.scenario, scenarios=run.results, calls=run.calls,
                  screenshots=run.screenshots, blocked_requests=run.blocked,
                  javascript_errors=run.errors, fixture_violations=run.violations,
                  browser_executable=args.browser_executable, viewports=list(WIDTHS),
                  frontend_snapshot_sha256={name: hashlib.sha256(data).hexdigest() for name, data in assets.items()},
                  limitations=["Kontrollierte API-Antworten; keine Backend-, RPC-, Persistenz- oder Steuerpruefung.",
                               "Lokale Testbudgets sind keine Herstellerquoten; kein verifizierter Free-/Premium-Tarif.",
                               "Chromium mit Tastatur; kein echter Screenreader- oder Touchgeraetetest.",
                               "Restzeit-Pruefung belegt UI-Darstellung, nicht die Genauigkeit einer realen Laufzeitprognose."])
    target = args.output / "verification.json"
    target.write_text(json.dumps(report, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "verification": str(target)}), flush=True)
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
