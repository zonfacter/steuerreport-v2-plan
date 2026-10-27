"""Isolierte Browserpruefung des Quellen-Historienimports, nur synthetische Daten.

PYTHONPATH=/tmp/steuerreport-browser-tools python3 scripts/check_history_import_browser_v2.py \
    --base-url http://127.0.0.1:5176
Ohne --base-url wird frontend/dist wie beim UX-Smoke lokal bereitgestellt.
Kein Backend, keine echten Anbieter, keine Produktionsbrowser oder Zugangsdaten.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, suppress
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import re
from threading import Thread
import time
from urllib.parse import unquote, urlparse
from uuid import UUID

from playwright.sync_api import expect, sync_playwright

from ux_workspace_fixtures import OTHER, SOURCE, WorkspaceFixture


LABELS = {SOURCE: "Synthetische Boerse A", OTHER: "Synthetische Wallet B"}
JOB_IDS = {
    SOURCE: "11111111-1111-4111-8111-111111111111",
    OTHER: "22222222-2222-4222-8222-222222222222",
}
OLD_JOB = "33333333-3333-4333-8333-333333333333"
STAMP = "2026-10-27T10:00:00Z"
NOTE = "Synthetischer Anbieter: begrenzte Abdeckung, keine Vollstaendigkeitsgarantie."
EXACT_QUANTITY = "0.123456789012345678"
PREFIX = "/api/v1/workspace/sources/"


def history_path(ref):
    return f"{PREFIX}{ref}/history"


class HistoryFixture(WorkspaceFixture):
    """Reine Antwortmaschine; kein HTTP-Client und keine Backend-Imports."""

    def __init__(self):
        super().__init__()
        self.capabilities = {
            ref: dict(source_ref=ref, label=LABELS[ref], provider="binance" if ref == SOURCE else "solana",
                      supported=True, ready=True, blocked_reason=None, requires_symbols=ref == SOURCE,
                      coverage_notes=[NOTE], default_start="2020-01-01")
            for ref in LABELS
        }
        self.jobs = {ref: [] for ref in LABELS}
        self.api_calls = []
        self.unexpected = []
        self.violations = []
        self.hold_views = set()
        self.pending_views = []
        self.pending_starts = []
        self.hold_start = False
        self.view_errors = {}
        self.job_errors = {}
        self.foreign_view_job = False
        self.sequence = 0

    def sources(self):
        template = super().sources()[0]
        return [{**template, "ref": ref, "label": LABELS[ref], "events_count": 0, "imports_count": 0,
                 "review_tasks_count": 0, "blocking_review_tasks_count": 0, "issues_count": 0,
                 "last_success_at": None, "last_attempt": None, "value_eur": None,
                 "source_type": "exchange" if ref == SOURCE else "solana_wallet",
                 "connector_id": "binance" if ref == SOURCE else "solana_rpc", "can_sync": True,
                 "freshness": "missing", "warning": None} for ref in LABELS]

    @staticmethod
    def reply(route, data=None, status=200, code=None):
        route.fulfill(status=status, content_type="application/json", body=json.dumps({
            "trace_id": "44444444-4444-4444-8444-444444444444", "status": "error" if code else "ok",
            "data": data, "errors": [{"code": code, "message": "<html>SYNTHETIC_SERVER_DETAIL</html>", "field": None}] if code else [],
            "warnings": [],
        }))

    def job(self, ref=SOURCE, status="running", job_id=None, **changes):
        value = dict(id=job_id or JOB_IDS[ref], source_ref=ref, label=LABELS[ref],
                     provider=self.capabilities[ref]["provider"], status=status, phase="Synthetischer Abrufabschnitt",
                     created_at=STAMP, updated_at=STAMP, start="2020-01-01", end="2026-10-27",
                     records_fetched=12, pages_fetched=3, new_records=8, duplicate_records=4,
                     imported_events=0, requests=5, max_records=100000,
                     preview_sha256="a" * 64 if status == "ready" else None,
                     sample_rows=[dict(timestamp_utc="2025-01-02T03:04:05Z", event_type="trade", asset="BTC",
                                       quantity=EXACT_QUANTITY, quote_asset="USDT", quote_quantity="-10.000000000000000001", side="in")],
                     before_summary={"events_count": 0}, after_summary={"events_count": 8}, review_issues_open=1,
                     error_code=None, coverage_notes=[NOTE], complete_history_proven=False,
                     can_resume=status in {"paused", "failed"}, approval=None)
        value.update(changes)
        UUID(value["id"])
        self.jobs[ref].append(value)
        return value

    def update(self, job, **changes):
        self.sequence += 1
        job.update(changes, updated_at=(datetime(2026, 10, 27, 10, tzinfo=timezone.utc)
                                       + timedelta(seconds=self.sequence)).isoformat())
        return job

    def view(self, ref):
        jobs = deepcopy(self.jobs[ref])
        if self.foreign_view_job and ref == SOURCE:
            jobs += deepcopy(self.jobs[OTHER])
        return {"capability": deepcopy(self.capabilities[ref]), "jobs": jobs}

    def posts(self, suffix=None):
        return [call for call in self.api_calls if call["method"] == "POST" and "/history/jobs" in call["path"]
                and (suffix is None or call["path"].endswith(suffix))]

    def release_views(self):
        self.hold_views.clear()
        pending, self.pending_views = self.pending_views, []
        for route, ref in pending:
            self.reply(route, self.view(ref))

    def release_start(self, code=None):
        assert len(self.pending_starts) == 1, self.pending_starts
        route, ref, body = self.pending_starts.pop()
        if code:
            self.reply(route, status=503, code=code)
        else:
            self.accept_start(route, ref, body)

    def accept_start(self, route, ref, body):
        assert UUID(body["request_id"]).version == 4
        assert body["confirm_external_request"] is True
        assert set(body) == {"request_id", "confirm_external_request", "start", "end", "symbols", "public_rpc_only", "max_records"}
        assert body["max_records"] == 100000 and body["public_rpc_only"] is True
        assert body["symbols"] == (["BTCUSDT", "ETHUSDT"] if self.capabilities[ref]["requires_symbols"] else [])
        value = self.job(ref, "queued", start=body["start"], end=body["end"], records_fetched=0, pages_fetched=0,
                         requests=0, new_records=0, duplicate_records=0, sample_rows=[])
        self.reply(route, value, 202)

    def handle(self, route):
        request = route.request
        path = unquote(urlparse(request.url).path)
        body = request.post_data_json if request.post_data else None
        self.api_calls.append({"method": request.method, "path": path, "body": body})
        try:
            match = re.fullmatch(re.escape(PREFIX) + r"(s_[a-f0-9]{20})/history(?:/jobs(?:/([a-f0-9-]{36})(?:/(pause|resume|cancel|import))?)?)?", path)
            if match:
                ref, job_id, action = match.groups()
                assert ref in LABELS, "Unbekannte synthetische Quelle"
                if request.method == "GET" and path == history_path(ref):
                    if ref in self.hold_views:
                        self.pending_views.append((route, ref))
                    elif ref in self.view_errors:
                        self.reply(route, status=503, code=self.view_errors[ref])
                    else:
                        self.reply(route, self.view(ref))
                elif request.method == "POST" and path == history_path(ref) + "/jobs":
                    if self.hold_start:
                        self.pending_starts.append((route, ref, body))
                    else:
                        self.accept_start(route, ref, body)
                else:
                    value = next((item for item in self.jobs[ref] if item["id"] == job_id), None)
                    assert value is not None, "Job und URL-Quelle stimmen nicht ueberein"
                    if request.method == "GET" and not action:
                        if ref in self.job_errors:
                            self.reply(route, status=503, code=self.job_errors[ref])
                        else:
                            self.reply(route, value)
                    else:
                        assert request.method == "POST" and action
                        if action in {"pause", "cancel"}:
                            assert body == {}
                            self.update(value, status="paused" if action == "pause" else "cancelled",
                                        phase="Synthetisch angehalten", can_resume=action == "pause")
                        elif action == "resume":
                            assert body["confirm_external_request"] is True and set(body) <= {"confirm_external_request", "max_records"}
                            self.update(value, status="running", can_resume=False, max_records=body.get("max_records", value["max_records"]))
                        elif action == "import":
                            assert body == dict(preview_sha256=value["preview_sha256"], actor="Synthetische Freigabe",
                                                confirm_import=True, confirm_recalculation=True)
                            self.update(value, status="succeeded", imported_events=8, approval=deepcopy(body))
                        self.reply(route, value)
                return True
            if request.method == "POST" and path in {"/api/v1/activity/query", "/api/v1/workspace/review/query"}:
                return super().handle(route)
            if request.method != "GET":
                self.unexpected.append({"method": request.method, "path": path})
                self.reply(route, status=500, code="synthetic_unexpected_write")
                return True
            if path == "/api/v1/workspace/sources":
                self.reply(route, dict(generated_at=STAMP, sources=self.sources(), events_count=0, methodology="Synthetisch"))
                return True
            if path in {PREFIX + ref for ref in LABELS}:
                source = next(item for item in self.sources() if item["ref"] == path.rsplit("/", 1)[1])
                self.reply(route, dict(source=source, valuation=None, live_balance=None, evidence={"synthetic": True}, review_tasks=[]))
                return True
            if path == "/api/v1/health":
                self.reply(route, {"app_version": "synthetic-browser", "status": "ok"})
                return True
            # Die vorhandene Workspace-Fixture deckt Umgebung und Dateiimport ab.
            if super().handle(route):
                return True
            self.unexpected.append({"method": request.method, "path": path})
            self.reply(route, status=500, code="synthetic_unexpected_api")
        except Exception as exc:
            self.violations.append(f"{request.method} {path}: {type(exc).__name__}: {exc}")
            self.reply(route, status=500, code="synthetic_fixture_contract_violation")
        return True


def frames(page):
    page.evaluate("async () => { await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))); }")


def workflow(page):
    return page.locator(".hiWorkflow")


def open_source(page, base, ref=SOURCE, entry="card"):
    page.goto(base + "/#sources", wait_until="domcontentloaded")
    expect(page.get_by_role("heading", name="Quellen & Wallets", exact=True)).to_be_visible()
    row = page.locator(".wsSourceRow").filter(has=page.get_by_role("button", name=LABELS[ref], exact=True))
    expect(row).to_be_visible()
    if entry == "overview":
        row.get_by_role("button", name=LABELS[ref], exact=True).click()
        page.get_by_role("dialog").get_by_role("button", name="Transaktionen abrufen", exact=True).click()
    else:
        row.get_by_role("button", name="Transaktionen abrufen", exact=True).click()
    panel = page.get_by_role("dialog")
    expect(panel.get_by_role("heading", name=LABELS[ref], exact=True)).to_be_visible()
    expect(panel.get_by_role("tab", name="Automatischer Import", exact=True)).to_have_attribute("aria-selected", "true")
    expect(workflow(page)).to_be_visible()
    expect(workflow(page).locator(".hiContext")).to_contain_text(ref)
    return workflow(page)


def start_fields(area, ref=SOURCE):
    expect(area.get_by_label("Von", exact=True)).to_have_value("2020-01-01")
    if ref == SOURCE:
        area.get_by_label("Handelspaare (kommagetrennt)").fill(" btcusdt, ETHUSDT, BTCUSDT ")
    return area.get_by_role("button", name="Vorschau abrufen", exact=True)


def confirm_external(area):
    area.get_by_role("checkbox", name=re.compile("Ich bestätige den externen Anbieterabruf")).check()


def public_rpc_checkbox(area):
    return area.get_by_role("checkbox", name=re.compile(r"Nur .*RPC", re.IGNORECASE))


def confirm_import(area):
    area.get_by_role("checkbox", name=re.compile("Ich bestätige den Import dieser Vorschau")).check()
    area.get_by_role("checkbox", name=re.compile("Ich bestätige die Neuberechnung")).check()


def count_value(area, name):
    return area.locator(".hiCounts").get_by_text(name, exact=True).locator("..").locator("dd")


class Run:
    def __init__(self, browser, base, output):
        self.browser, self.base, self.output = browser, base, output
        self.results, self.screenshots, self.calls = {}, [], []
        self.external, self.errors, self.unexpected, self.violations = [], [], [], []
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.started = time.monotonic()

    def screenshot(self, page, name):
        filename = "synthetic-" + name + ".png"
        page.screenshot(path=str(self.output / filename), animations="disabled")
        self.screenshots.append({"file": filename, "synthetic_only": True, "viewport": page.viewport_size})

    def scenario(self, name, check):
        print(f"{name}: gestartet", flush=True)
        started = time.monotonic()
        fixture = HistoryFixture()
        context = self.browser.new_context(viewport={"width": 1440, "height": 1000}, service_workers="block")
        context.set_default_timeout(7000)
        context.set_default_navigation_timeout(15000)
        external, errors = [], []
        origin = urlparse(self.base)

        def guard(route):
            parsed = urlparse(route.request.url)
            if (parsed.scheme, parsed.netloc) != (origin.scheme, origin.netloc):
                external.append(route.request.url)
                route.abort("blockedbyclient")
            elif parsed.path == "/api" or parsed.path.startswith("/api/"):
                fixture.handle(route)
            elif route.request.method != "GET":
                fixture.unexpected.append({"method": route.request.method, "path": parsed.path})
                route.abort("blockedbyclient")
            else:
                route.continue_()

        context.route("**/*", guard)

        def websocket(socket):
            if urlparse(socket.url).netloc != origin.netloc:
                external.append(socket.url)
                socket.close()
            else:
                socket.connect_to_server()

        context.route_web_socket("**", websocket)
        context.add_init_script("""
          window.__historyRefreshes = 0;
          addEventListener('steuerreport:refresh', () => window.__historyRefreshes++);
          Object.defineProperty(crypto, 'randomUUID', {configurable: true, value: undefined});
        """)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        result = {"status": "bestanden", "synthetic_only": True}
        try:
            check(page, fixture)
            frames(page)
            assert not external, external
            assert not errors, errors
            assert not fixture.unexpected, fixture.unexpected
            assert not fixture.violations, fixture.violations
            result["evidence"] = check.__doc__
        except Exception as exc:
            result.update(status="fehlgeschlagen", error=f"{type(exc).__name__}: {exc}")
            with suppress(Exception):
                self.screenshot(page, name + "-failure")
        finally:
            self.calls.extend({"scenario": name, **call} for call in fixture.api_calls)
            self.external.extend(external)
            self.errors.extend(errors)
            self.unexpected.extend(fixture.unexpected)
            self.violations.extend(fixture.violations)
            # Die Netzsperre bleibt bis zum Schliessen aktiv, auch fuer letzte Poll-Timer.
            context.close()
            result["duration_seconds"] = round(time.monotonic() - started, 3)
            self.results[name] = result
            print(f"{name}: {result['status']}" + (f" {result['error']}" if "error" in result else ""), flush=True)

    def checks(self):
        def loading(page, fixture):
            """Quellenkarte mit 0 Ereignissen oeffnet Import; gehaltenes GET zeigt weder Leerstand noch Erfolg."""
            fixture.hold_views.add(SOURCE)
            area = open_source(page, self.base)
            expect(area.get_by_text("Historienabruf: Ladevorgang läuft.", exact=False)).to_be_visible()
            expect(area.get_by_text("Für diese Quelle ist noch kein Historienauftrag gespeichert.", exact=True)).to_have_count(0)
            expect(area.get_by_role("button", name="Vorschau abrufen", exact=True)).to_have_count(0)
            assert not fixture.posts()
            assert page.evaluate("window.__historyRefreshes") == 0
            self.screenshot(page, "loading-1440")
            fixture.release_views()
            expect(area.get_by_text("Für diese Quelle ist noch kein Historienauftrag gespeichert.", exact=True)).to_be_visible()
            self.screenshot(page, "selected-source-1440")

        def overview_and_file(page, fixture):
            """Uebersichtsbutton fuehrt zum selben Quellentab; Dateiimport bleibt sekundarer Link ohne Schreibzugriff."""
            area = open_source(page, self.base, entry="overview")
            expect(area.get_by_role("button", name="Vorschau abrufen", exact=True)).to_be_disabled()
            link = area.get_by_role("link", name="Dateien importieren", exact=True)
            expect(link).to_have_attribute("href", "#import")
            assert "wsPrimary" not in (link.get_attribute("class") or "")
            link.click()
            expect(page.get_by_role("heading", name="Daten importieren", exact=True)).to_be_visible()
            expect(page.get_by_role("dialog")).to_have_count(0)
            expect(page.get_by_role("combobox", name="Importquelle", exact=True)).to_be_visible()
            assert not fixture.posts()

        def consent_uuid(page, fixture):
            """Explizite Einwilligung, Doppelklickschutz, stabile UUID nach Fehler und neue UUID nach geaenderten Eingaben."""
            fixture.hold_start = True
            area = open_source(page, self.base)
            button = start_fields(area)
            expect(button).to_be_disabled()
            assert page.evaluate("typeof crypto.randomUUID") == "undefined"
            confirm_external(area)
            expect(button).to_be_enabled()
            button.evaluate("button => { button.click(); button.click(); }")
            expect(button).to_be_disabled()
            frames(page)
            assert len(fixture.posts("/jobs")) == 1
            first = fixture.posts("/jobs")[0]["body"]
            assert UUID(first["request_id"]).version == 4
            fixture.release_start("history_job_capacity")
            expect(area.get_by_role("alert")).to_contain_text("Abrufplätze")
            expect(button).to_be_disabled()
            confirm_external(area)
            expect(button).to_be_enabled()
            button.click()
            expect(button).to_be_disabled()
            frames(page)
            second = fixture.posts("/jobs")[-1]["body"]
            assert second == first
            fixture.release_start("history_job_capacity")
            expect(area.get_by_role("alert")).to_contain_text("Abrufplätze")
            area.get_by_label("Von", exact=True).fill("2021-01-01")
            expect(button).to_be_disabled()
            confirm_external(area)
            expect(button).to_be_enabled()
            button.click()
            expect(button).to_be_disabled()
            frames(page)
            third = fixture.posts("/jobs")[-1]["body"]
            assert third["request_id"] != first["request_id"] and third["start"] == "2021-01-01"
            fixture.release_start()
            expect(area.locator(".hiJob .wsBadge")).to_have_text("Wartet auf Abruf")
            assert len(fixture.posts("/jobs")) == 3
            assert page.evaluate("window.__historyRefreshes") == 0

        def solana_start(page, fixture):
            """Solana startet nur mit Einwilligung, ohne Asset-/Adressfilter und standardmaessig mit public_rpc_only=true."""
            area = open_source(page, self.base, OTHER)
            button = start_fields(area, OTHER)
            expect(button).to_be_disabled()
            expect(area.get_by_label("Bis", exact=True)).to_have_value(page.evaluate("new Date().toISOString().slice(0, 10)"))
            expect(area.get_by_label("Handelspaare (kommagetrennt)")).to_have_count(0)
            expect(area.locator('input[type="password"]')).to_have_count(0)
            public_only = public_rpc_checkbox(area)
            expect(public_only).to_be_checked()
            confirm_external(area)
            button.click()
            expect(area.locator(".hiJob .wsBadge")).to_have_text("Wartet auf Abruf")
            payload = fixture.posts("/jobs")[-1]["body"]
            assert payload["symbols"] == [] and payload["public_rpc_only"] is True
            assert not any(call["path"].startswith(history_path(SOURCE)) for call in fixture.api_calls)

        def progress_controls(page, fixture):
            """Echte Zaehler und Phase ohne Prozent; Polling, Fokus, Pause/Fortsetzen/Abbruch und gespeicherter Stand bei GET-Fehler."""
            job = fixture.job()
            area = open_source(page, self.base)
            expect(count_value(area, "Datensätze")).to_have_text("12")
            expect(count_value(area, "Anfragen gespeicherter Seiten")).to_have_text("5")
            expect(area.get_by_text("Anfragen gespeicherter Seiten", exact=True)).to_have_attribute("title", re.compile("keine vollständige Anbieterabrechnung"))
            page.clock.install()
            start_fields(area)
            confirm_external(area)
            expect(area.get_by_role("button", name="Vorschau abrufen", exact=True)).to_be_disabled()
            date = area.get_by_label("Von", exact=True)
            date.focus()
            fixture.update(job, records_fetched=27, pages_fetched=4, phase="Synthetischer Folgeabschnitt")
            page.clock.run_for(2100)
            expect(count_value(area, "Datensätze")).to_have_text("27")
            expect(area).to_contain_text("Synthetischer Folgeabschnitt")
            expect(date).to_be_focused()
            assert not re.search(r"\d+(?:[.,]\d+)?\s*%", area.inner_text())
            assert not re.search(r"(?:5|fünf)[ -]*(?:Minuten|min\b)", area.inner_text(), re.IGNORECASE)
            expect(area.get_by_role("progressbar")).to_have_count(0)
            self.screenshot(page, "running-1440")
            fixture.job_errors[SOURCE] = "solana_rpc_failed"
            area.get_by_role("button", name="Status aktualisieren", exact=True).click()
            expect(area.get_by_role("alert")).to_contain_text("Solana-RPC-Anbieter")
            expect(count_value(area, "Datensätze")).to_have_text("27")
            fixture.job_errors.clear()
            area.get_by_role("button", name="Pausieren", exact=True).click()
            expect(area.locator(".hiJob .wsBadge")).to_have_text("Pausiert")
            expect(area.get_by_role("button", name="Vorschau abrufen", exact=True)).to_be_disabled()
            resume = area.get_by_role("button", name="Abruf fortsetzen", exact=True)
            expect(resume).to_be_disabled()
            area.get_by_label("Datensatzlimit beim Fortsetzen").fill("150000")
            area.get_by_role("checkbox", name=re.compile("Ich bestätige weitere externe Anbieteranfragen")).check()
            resume.click()
            expect(area.locator(".hiJob .wsBadge")).to_have_text("Abruf läuft")
            assert fixture.posts("/resume")[-1]["body"] == {"confirm_external_request": True, "max_records": 150000}
            area.get_by_role("button", name="Auftrag abbrechen", exact=True).click()
            expect(area.locator(".hiJob .wsBadge")).to_have_text("Abgebrochen")
            confirm_external(area)
            expect(area.get_by_role("button", name="Vorschau abrufen", exact=True)).to_be_enabled()
            assert fixture.posts("/pause")[-1]["body"] == fixture.posts("/cancel")[-1]["body"] == {}
            assert page.evaluate("window.__historyRefreshes") == 0

        def non_resumable(page, fixture):
            """Ein nicht fortsetzbarer Fehler zeigt die konkrete Beleggrenze, aber keine wirkungslose Resume-Aktion."""
            fixture.job(status="failed", can_resume=False, error_code="history_existing_evidence_conflict")
            area = open_source(page, self.base)
            expect(area.get_by_role("alert")).to_contain_text("Originalbelege widersprechen")
            expect(area.get_by_role("button", name="Abruf fortsetzen", exact=True)).to_have_count(0)
            assert not fixture.posts()

        def ready_approval(page, fixture):
            """Exakte Mengen, Actor und zwei Freigaben; neuer Hash setzt Freigaben zurueck, Apply sendet nur aktuellen Hash und refresht."""
            job = fixture.job(status="ready")
            area = open_source(page, self.base)
            expect(area.locator(".hiExact").first).to_have_text(EXACT_QUANTITY)
            expect(area.get_by_text("Verfügbare Anbieterhistorie, Vollständigkeit nicht bestätigt", exact=True)).to_be_visible()
            expect(area.get_by_role("list", name="Historienabdeckung").last).to_contain_text(NOTE)
            approve = area.get_by_role("button", name="Importieren und neu berechnen", exact=True)
            expect(approve).to_be_disabled()
            confirm_import(area)
            expect(approve).to_be_disabled()
            area.get_by_label("Freigebende Person (Importprotokoll)").fill("Synthetische Freigabe")
            expect(area.get_by_role("checkbox", name=re.compile("Ich bestätige den Import dieser Vorschau"))).not_to_be_checked()
            area.get_by_role("checkbox", name=re.compile("Ich bestätige den Import dieser Vorschau")).check()
            expect(approve).to_be_disabled()
            area.get_by_role("checkbox", name=re.compile("Ich bestätige die Neuberechnung")).check()
            expect(approve).to_be_enabled()
            start_fields(area)
            confirm_external(area)
            expect(area.get_by_role("button", name="Vorschau abrufen", exact=True)).to_be_disabled()
            assert not fixture.posts() and page.evaluate("window.__historyRefreshes") == 0
            fixture.update(job, preview_sha256="b" * 64)
            area.get_by_role("button", name="Status aktualisieren", exact=True).click()
            expect(area.get_by_label("SHA-256 der Vorschau")).to_have_text("b" * 64)
            expect(approve).to_be_disabled()
            expect(area.get_by_role("checkbox", name=re.compile("Ich bestätige den Import dieser Vorschau"))).not_to_be_checked()
            expect(area.get_by_role("checkbox", name=re.compile("Ich bestätige die Neuberechnung"))).not_to_be_checked()
            expect(area.get_by_label("Freigebende Person (Importprotokoll)")).to_have_value("Synthetische Freigabe")
            assert "Synthetische Freigabe" not in page.evaluate("JSON.stringify(localStorage)")
            confirm_import(area)
            expect(approve).to_be_enabled()
            self.screenshot(page, "ready-1440")
            before = len([call for call in fixture.api_calls if call["path"] == "/api/v1/workspace/sources"])
            approve.click()
            expect(area.locator(".hiJob .wsBadge")).to_have_text("Import abgeschlossen")
            expect(area.get_by_role("status").filter(has_text="8 Ereignisse importiert")).to_be_visible()
            page.wait_for_function("window.__historyRefreshes === 1")
            frames(page)
            assert len([call for call in fixture.api_calls if call["path"] == "/api/v1/workspace/sources"]) > before
            assert len(fixture.posts("/import")) == 1
            self.screenshot(page, "done-1440")

        def prior_jobs(page, fixture):
            """Gespeicherte Auftraege: aktiven neuesten waehlen, aelteren auswaehlen, fremde Quellen aus Liste entfernen."""
            fixture.job(status="failed", job_id=OLD_JOB, created_at="2026-10-25T10:00:00Z")
            fixture.job(status="ready")
            fixture.job(OTHER, status="ready")
            fixture.foreign_view_job = True
            area = open_source(page, self.base)
            select = area.get_by_label("Gespeicherte Aufträge")
            expect(select).to_have_value(JOB_IDS[SOURCE])
            expect(select.locator("option")).to_have_count(2)
            select.select_option(OLD_JOB)
            expect(area.locator(".hiJob .wsBadge")).to_have_text("Fehlgeschlagen")
            expect(area).not_to_contain_text(JOB_IDS[OTHER])
            assert not fixture.posts()

        def source_races(page, fixture):
            """Zwei Quellen, verspaetete View-/Poll-Antworten trotz ignoriertem Abort: keine Fremddaten, Polling endet bei Wechsel."""
            job_a = fixture.job(phase="A-RACE-ONLY", records_fetched=888)
            fixture.job(OTHER, status="ready", phase="B-ONLY", records_fetched=23)
            page.goto(self.base + "/#sources", wait_until="domcontentloaded")
            expect(page.locator(".wsSourceRow")).to_have_count(2)
            page.evaluate("""path => {
              const original = window.fetch;
              window.__delayedReleases = []; window.__delayedAborts = 0;
              window.__holdHistoryPath = path;
              window.fetch = (input, init = {}) => {
                if (window.__holdHistoryPath && String(input).endsWith(window.__holdHistoryPath)) {
                  init.signal?.addEventListener('abort', () => window.__delayedAborts++);
                  const {signal, ...rest} = init;
                  return original(input, rest).then(response => new Promise(resolve => {
                    window.__delayedReleases.push(() => resolve(response));
                  }));
                }
                return original(input, init);
              };
            }""", history_path(SOURCE))
            row_a = page.locator(".wsSourceRow").filter(has=page.get_by_role("button", name=LABELS[SOURCE], exact=True))
            row_a.get_by_role("button", name="Transaktionen abrufen", exact=True).click()
            expect(page.get_by_role("tab", name="Automatischer Import", exact=True)).to_have_attribute("aria-selected", "true")
            page.wait_for_function("window.__delayedReleases.length > 0")
            page.get_by_role("dialog").get_by_role("button", name="Details schließen", exact=True).click()
            row_b = page.locator(".wsSourceRow").filter(has=page.get_by_role("button", name=LABELS[OTHER], exact=True))
            row_b.get_by_role("button", name="Transaktionen abrufen", exact=True).click()
            area = workflow(page)
            expect(area.locator(".hiContext")).to_contain_text(OTHER)
            expect(count_value(area, "Datensätze")).to_have_text("23")
            page.evaluate("() => { window.__holdHistoryPath = ''; window.__delayedReleases.splice(0).forEach(release => release()); }")
            frames(page)
            expect(area).not_to_contain_text("A-RACE-ONLY")
            expect(area).not_to_contain_text(JOB_IDS[SOURCE])
            assert page.evaluate("window.__delayedAborts") > 0
            expect(area.get_by_label("Handelspaare (kommagetrennt)")).to_have_count(0)
            expect(public_rpc_checkbox(area)).to_be_checked()
            page.get_by_role("dialog").get_by_role("button", name="Details schließen", exact=True).click()
            row_a.get_by_role("button", name="Transaktionen abrufen", exact=True).click()
            expect(count_value(workflow(page), "Datensätze")).to_have_text(str(job_a["records_fetched"]))
            page.clock.install()
            page.evaluate("path => { window.__holdHistoryPath = path; }", history_path(SOURCE) + "/jobs/" + JOB_IDS[SOURCE])
            page.clock.run_for(2100)
            page.wait_for_function("window.__delayedReleases.length > 0")
            page.get_by_role("dialog").get_by_role("button", name="Details schließen", exact=True).click()
            row_b.get_by_role("button", name="Transaktionen abrufen", exact=True).click()
            expect(count_value(workflow(page), "Datensätze")).to_have_text("23")
            page.evaluate("() => { window.__holdHistoryPath = ''; window.__delayedReleases.splice(0).forEach(release => release()); }")
            frames(page)
            before = len([call for call in fixture.api_calls if call["path"] == history_path(SOURCE) + "/jobs/" + JOB_IDS[SOURCE]])
            page.clock.run_for(4500)
            frames(page)
            assert len([call for call in fixture.api_calls if call["path"] == history_path(SOURCE) + "/jobs/" + JOB_IDS[SOURCE]]) == before
            expect(workflow(page)).not_to_contain_text("A-RACE-ONLY")
            assert not fixture.posts()

        def unsupported_setup(page, fixture):
            """Nicht unterstuetzter Anbieter und fehlende Verbindung sind lesbar; keine Credentials- oder Adressfelder im Import."""
            fixture.capabilities[OTHER].update(supported=False, ready=False, blocked_reason="history_provider_not_supported")
            area = open_source(page, self.base, OTHER)
            expect(area).to_contain_text("Automatischer Import nicht verfügbar")
            expect(area).to_contain_text("Für diesen Anbieter ist kein automatischer Historienabruf verfügbar")
            expect(area.get_by_role("link", name="Dateien importieren", exact=True)).to_be_visible()
            expect(area.get_by_role("button", name="Vorschau abrufen", exact=True)).to_have_count(0)
            fixture.capabilities[SOURCE].update(ready=False, blocked_reason="history_connection_required")
            area = open_source(page, self.base)
            expect(area).to_contain_text("Einrichtung erforderlich")
            expect(area).to_contain_text("API-Verbindung")
            expect(area.get_by_role("link", name="Einrichtung öffnen", exact=True)).to_be_visible()
            expect(area.locator("input")).to_have_count(0)
            assert not fixture.posts()
            self.screenshot(page, "setup-1440")

        def mapped_errors(page, fixture):
            """ApiReadError.code bleibt im View sichtbar; unbekannte Solana-Codes bekommen sicheren lesbaren Fallback statt Server-HTML."""
            fixture.view_errors[SOURCE] = "history_connection_required"
            area = open_source(page, self.base)
            expect(area.get_by_role("alert")).to_contain_text("API-Verbindung")
            for code, text in [("history_select_individual_connection", "einzelne eingerichtete Kontoverbindung"),
                               ("history_preview_stale", "Vorschau ist veraltet"),
                               ("history_source_job_exists", "offener Auftrag"),
                               ("history_worker_stopped", "Serverneustart"),
                               ("history_existing_evidence_conflict", "Originalbelege widersprechen"),
                               ("solana_synthetic_unknown_rpc_error", "RPC-Verfügbarkeit")]:
                fixture.view_errors[SOURCE] = code
                area.get_by_role("button", name="Status aktualisieren", exact=True).click()
                expect(area.get_by_role("alert")).to_contain_text(text)
                expect(area.get_by_role("alert")).not_to_contain_text(code)
                expect(area).not_to_contain_text("SYNTHETIC_SERVER_DETAIL")
            assert not fixture.posts()
            self.screenshot(page, "mapped-error-1440")

        def responsive_keyboard(page, fixture):
            """390/768/1280/1440: begrenzter Tabellen-Scroll, kein Seiten-/Paneloverflow, Tastaturumlauf, Tabs und stabiler Formularfokus."""
            fixture.job(status="ready")
            area = open_source(page, self.base)
            expect(area.get_by_label("Freigebende Person (Importprotokoll)")).to_be_visible()
            for width in (390, 768, 1280, 1440):
                page.set_viewport_size({"width": width, "height": 1000})
                frames(page)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Seitenoverflow: {width}"
                panel = page.get_by_role("dialog")
                assert panel.locator(".wsPanelBody").evaluate("el => el.scrollWidth <= el.clientWidth + 1"), f"Paneloverflow: {width}"
                outside = area.evaluate("""root => {
                  const bounds = root.closest('[role=dialog]').getBoundingClientRect();
                  return [...root.querySelectorAll('button, input, select, a')].filter(el => {
                    const r = el.getBoundingClientRect();
                    return r.width && r.height && !el.closest('.wsTableScroll') && (r.left < bounds.left - 1 || r.right > bounds.right + 1);
                  }).map(el => el.outerHTML.slice(0, 180));
                }""")
                assert not outside, (width, outside)
                area.locator(".hiContext").scroll_into_view_if_needed()
                self.screenshot(page, f"start-{width}")
                area.locator(".hiApproval").scroll_into_view_if_needed()
                self.screenshot(page, f"approval-{width}")
                close = panel.get_by_role("button", name="Details schließen", exact=True)
                close.focus()
                page.keyboard.press("Shift+Tab")
                assert page.evaluate("document.activeElement.closest('[role=dialog]') !== null")
                page.keyboard.press("Tab")
                expect(close).to_be_focused()
                for _ in range(12):
                    page.keyboard.press("Tab")
                    assert page.evaluate("document.activeElement.closest('[role=dialog]') !== null")
                tab = panel.get_by_role("tab", name="Automatischer Import", exact=True)
                tab.focus()
                page.keyboard.press("ArrowLeft")
                expect(panel.get_by_role("tab", name="Transaktionen", exact=True)).to_have_attribute("aria-selected", "true")
                page.keyboard.press("ArrowRight")
                expect(tab).to_be_focused()
                expect(tab).to_have_attribute("aria-selected", "true")
                actor = workflow(page).get_by_label("Freigebende Person (Importprotokoll)")
                actor.fill("Synthetische Freigabe")
                actor.focus()
                page.evaluate("window.dispatchEvent(new Event('steuerreport:refresh'))")
                expect(workflow(page).locator(".wsResource")).to_have_count(0)
                expect(actor).to_be_focused()
                expect(actor).to_have_value("Synthetische Freigabe")
            page.keyboard.press("Escape")
            expect(page.get_by_role("dialog")).to_have_count(0)
            expect(page.locator(".wsSourceRow").filter(has=page.get_by_role("button", name=LABELS[SOURCE], exact=True)).get_by_role("button", name="Transaktionen abrufen", exact=True)).to_be_focused()
            assert not fixture.posts()

        return {"loading": loading, "overview-file": overview_and_file, "consent-uuid": consent_uuid, "solana-start": solana_start,
                "progress-controls": progress_controls, "ready-approval": ready_approval, "prior-jobs": prior_jobs,
                "non-resumable": non_resumable,
                "source-races": source_races, "unsupported-setup": unsupported_setup, "mapped-errors": mapped_errors,
                "responsive-keyboard": responsive_keyboard}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help="Nur Loopback-Frontend; ohne Angabe isolierter Server fuer frontend/dist.")
    parser.add_argument("--browser-executable")
    parser.add_argument("--output", type=Path, default=Path("artifacts/source-history-browser"))
    parser.add_argument("--scenario", action="append", help="Optional einzelne Szenarionamen wiederholen.")
    args = parser.parse_args()
    if args.base_url:
        parsed = urlparse(args.base_url)
        try:
            loopback = parsed.hostname == "localhost" or ipaddress.ip_address(parsed.hostname or "").is_loopback
        except ValueError:
            loopback = False
        if not loopback or parsed.scheme != "http" or parsed.path not in {"", "/"} or parsed.query or parsed.fragment or parsed.username or parsed.password:
            parser.error("Nur eine lokale HTTP-Frontend-URL ohne Zugangsdaten, Pfad oder Query ist erlaubt.")
        args.base_url = args.base_url.rstrip("/")
    args.output.mkdir(parents=True, exist_ok=True)
    expect.set_options(timeout=7000)
    with ExitStack() as stack:
        if not args.base_url:
            root = Path(__file__).resolve().parents[1] / "frontend/dist"
            if not (root / "index.html").is_file():
                parser.error("Zuerst npm run build im Frontend ausfuehren oder --base-url angeben.")

            class QuietHandler(SimpleHTTPRequestHandler):
                def log_message(self, *args):
                    pass

            server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(root)))
            worker = Thread(target=server.serve_forever, daemon=True)
            worker.start()
            stack.callback(server.server_close)
            stack.callback(worker.join)
            stack.callback(server.shutdown)
            args.base_url = f"http://127.0.0.1:{server.server_port}"
        playwright = stack.enter_context(sync_playwright())
        browser = stack.enter_context(playwright.chromium.launch(headless=True, executable_path=args.browser_executable))
        run = Run(browser, args.base_url, args.output)
        checks = run.checks()
        if args.scenario and set(args.scenario) - checks.keys():
            parser.error("Unbekannte Szenarien: " + ", ".join(sorted(set(args.scenario) - checks.keys())))
        for name, check in checks.items():
            if not args.scenario or name in args.scenario:
                run.scenario(name, check)
        result = {"synthetic_only": True, "actual_frontend_routes": True, "all_api_intercepted": True,
                  "started_at": run.started_at, "duration_seconds": round(time.monotonic() - run.started, 3),
                  "actual_backend_tested": False, "base_url": args.base_url, "browser_executable": args.browser_executable,
                  "complete_suite": not args.scenario, "implemented_scenarios": list(checks),
                  "passed": all(item["status"] == "bestanden" for item in run.results.values()),
                  "scenarios": run.results, "screenshots": run.screenshots, "calls": run.calls,
                  "external_requests": run.external, "javascript_errors": run.errors,
                  "unexpected_api": run.unexpected, "fixture_contract_violations": run.violations,
                  "limitations": ["Nur synthetische UI-Vertraege; keine Backend-, Anbieter-, Persistenz- oder Steuerpruefung.",
                                  "Chromium mit Desktop-Tastatur und responsiven Viewports, kein echter Touch-/Screenreader-Test.",
                                  "Pollingzeit wird kontrolliert mit der Playwright-Uhr vorgerueckt; kein 240-Sekunden-Worker-Dauertest."]}
        (args.output / "verification.json").write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        print(json.dumps({"passed": result["passed"], "scenarios": {name: item["status"] for name, item in run.results.items()},
                          "verification": str(args.output / "verification.json")}), flush=True)
        if not result["passed"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
