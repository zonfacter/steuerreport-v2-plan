"""Synthetischer Browsernachweis fuer Einrichtung > Abrufsteuerung.

Echter FastAPI-Router und persistenter Datei-Koordinator in /tmp, keine Live-DB.
Andere Ansichten erhalten kontrollierte Fixtures. Unbekannte API-Aufrufe und
externes Netzwerk werden blockiert. Alle Nachweise bleiben im Tempverzeichnis.
Vor dem Browserlauf muss Main das aktuelle Frontend gebaut haben.
"""
from __future__ import annotations

import argparse
import copy
from contextlib import ExitStack, contextmanager
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from threading import Thread
from unittest.mock import patch
from urllib.parse import urlparse

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
LIMITS = "/api/v1/admin/request-limits"
PRESETS = LIMITS + "/presets"
APPLY = PRESETS + "/solana_public_free"
SUMMARY = "Solana Public RPC - Free"
CONFIRM = "Ich m\u00f6chte das Startprofil ausdr\u00fccklich"
RELOAD = "Gespeicherte Limits und lokale Auslastung neu lesen"
TEN_SECONDS = "Requests pro 10 Sekunden"
ENDPOINTS = ("rpc_gettransaction", "rpc_getsignaturesforaddress", "rpc_gettokenaccountsbyowner")


def require(condition, detail):
    if not condition:
        raise AssertionError(detail)


class Clock:
    def __init__(self):
        self.now = 1793102400.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


@contextmanager
def isolated_backend(state: Path):
    """Nur den echten Limits-Router laden, niemals create_app oder Live-Daten."""
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ))
        for key in list(os.environ):
            if key.startswith("STEUERREPORT_"):
                del os.environ[key]
        os.environ.update(STEUERREPORT_V2_ROOT=str(ROOT), STEUERREPORT_STATE_DIR=str(state),
                          STEUERREPORT_PRIVATE_PROFILE=str(state / "unused-profile.json"),
                          STEUERREPORT_PRIVATE_CONFIG_DIR=str(state / "configs"),
                          STEUERREPORT_USERTRANSFER_ROOT=str(state / "imports"),
                          STEUERREPORT_V2_DB=str(state / "unused.duckdb"))
        # TestClient uses an in-process ASGI transport; no TCP is necessary.
        def no_network(*_args, **_kwargs):
            raise AssertionError("Backend-Netzwerk ist im Browsernachweis gesperrt")
        stack.enter_context(patch.object(socket.socket, "connect", no_network))
        stack.enter_context(patch.object(socket.socket, "connect_ex", no_network))
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from steuerreport_v2.api import request_limits as api
        from steuerreport_v2.contracts.request_limits import RequestLimitProfile, RequestLimitsConfig
        from steuerreport_v2.domain.request_limits import RequestLimiter

        clock = Clock()
        limiter = RequestLimiter(state_root=state, clock=clock, monotonic=clock, sleep=clock.advance)
        stack.enter_context(patch.object(api, "private_state_root", lambda: state))
        stack.enter_context(patch.object(api, "RequestLimiter", lambda: limiter))
        app = FastAPI()
        app.include_router(api.build_request_limits_router())
        client = stack.enter_context(TestClient(app))
        # Fremde Gruppen/Felder sind absichtliche Erhaltungskontrollen.
        profile = RequestLimitProfile(requests_per_second=2, requests_per_minute=60,
                                      requests_per_10_seconds=None, max_retries=3, jitter_ratio=0.15)
        small = profile.model_copy(update={"requests_per_second": 5, "requests_per_minute": 2})
        config = RequestLimitsConfig(default_profile=profile,
            group_profiles={"provider:binance": small, "budget:synthetic": profile},
            provider_groups={"binance": ["budget:synthetic"]},
            endpoint_profiles={"binance": {"account": small}},
            endpoint_costs={"binance": {"account": 7}},
            provider_ceilings={"binance": {
                "requests_per_second": 9, "requests_per_minute": 90,
                "source_url": "https://docs.example.org/synthetic-limits",
                "checked_date": "2026-10-27", "scope": "provider", "plan": "Synthetic",
            }})
        response = client.put(LIMITS, json={"config": config.model_dump(mode="json"), "expected_revision": 0})
        require(response.status_code == 200, response.text)
        # Echte lokale Startbuchungen ohne HTTP-Aufruf erzeugen Minutenwartezeit.
        for _ in range(2):
            with limiter.acquire("binance", endpoint="account") as lease:
                lease.start()
            clock.advance(2.0)
        yield Backend(client, app, limiter, state)


class Backend:
    def __init__(self, client, app, limiter, state):
        self.client, self.app, self.limiter, self.state = client, app, limiter, state

    def config(self):
        response = self.client.get(LIMITS)
        require(response.status_code == 200, response.text)
        return response.json()["data"]

    def document(self):
        return json.loads((self.state / "request_limits/coordinator.json").read_text())

    def unchanged_starts(self, before):
        after = self.document()
        for name, bucket in before["buckets"].items():
            require(after["buckets"][name]["starts"] == bucket["starts"], "Startbuchungen verloren: " + name)
        for key in ("active", "waiters", "observations"):
            require(after[key] == before[key], "Koordinatorzustand veraendert: " + key)


def contract_checks(backend):
    before = backend.document()
    revision = backend.config()["revision"]
    preview = backend.client.get(PRESETS)
    require(preview.status_code == 200, preview.text)
    preset = preview.json()["data"]["presets"][0]
    require(preset["id"] == "solana_public_free", preset)
    require(preset["current_revision"] == revision and not preset["conflicts"], preset)
    for body in ({"expected_revision": revision}, {"expected_revision": revision, "confirmation": False}):
        response = backend.client.post(APPLY, json=body)
        require(response.status_code == 422, response.text)
    response = backend.client.post(APPLY, json={"expected_revision": revision - 1, "confirmation": True})
    require(response.status_code == 409, response.text)
    backend.app.state.ux_sandbox = True
    response = backend.client.post(APPLY, json={"expected_revision": revision, "confirmation": True})
    require(response.status_code == 403 and response.json()["detail"] == "connection_demo_read_only", response.text)
    backend.app.state.ux_sandbox = False
    require(backend.document() == before, "Abgewiesene API-Requests haben Zustand veraendert")
    status = backend.client.get(LIMITS + "/status").json()["data"]
    require(any("rolling_minute" in row["blocking_reasons"] for row in status["groups"]), status)
    return {"missing_or_false_confirmation": 422, "stale_revision": 409, "demo": 403,
            "rejected_requests_preserve_entire_document": True, "actual_rolling_minute": True}


class Bridge:
    def __init__(self, context, base, backend, mode):
        from ux_workspace_fixtures import WorkspaceFixture
        self.backend, self.mode, self.origin = backend, mode, urlparse(base).netloc
        self.fixture = WorkspaceFixture()
        self.calls, self.writes, self.blocked, self.errors, self.pending = [], [], [], [], []
        self.hold = set()
        self.fail = set()
        self.empty = set()
        context.route("**/*", self.dispatch)
        context.route_web_socket("**/*", self.block_socket)

    def block_socket(self, route):
        self.blocked.append("websocket:" + route.url)
        route.close()

    def dispatch(self, route):
        request = route.request
        url = urlparse(request.url)
        try:
            if url.path.startswith("/api/"):
                require(url.path.startswith("/api/v1/"), "Unbekannte API-Version")
                call = {"method": request.method, "path": url.path,
                        "body": request.post_data_json if request.post_data else None}
                self.calls.append(call)
                if request.method != "GET":
                    self.writes.append(call)
                require(request.method == "GET" or (request.method, url.path) in {
                    ("PUT", LIMITS), ("POST", APPLY)}, "Unerwartete API-Aktion: " + str(call))
                if url.path in self.hold:
                    self.pending.append(route)
                else:
                    self.respond(route)
            elif url.netloc == self.origin and request.method == "GET" and (
                    url.path == "/" or url.path.startswith("/assets/") or url.path in {"/favicon.ico", "/favicon.svg"}):
                route.continue_()
            else:
                self.blocked.append(request.method + " " + request.url)
                route.abort("blockedbyclient")
        except Exception as error:
            self.errors.append(str(error))
            print("BLOCKED:", error, flush=True)
            route.abort("blockedbyclient")

    def respond(self, route):
        request = route.request
        path = urlparse(request.url).path
        if path in self.fail:
            self.calls_entry_response(request, 503)
            route.fulfill(status=503, json={"detail": "request_limits_unavailable"})
            return
        if path == PRESETS and path in self.empty:
            self.send(route, {"presets": [], "current_revision": self.backend.config()["revision"]})
            return
        if path in {LIMITS, LIMITS + "/status", LIMITS + "/endpoints", PRESETS, APPLY,
                    "/api/v1/admin/provider-references"}:
            response = self.backend.client.request(request.method, path, content=request.post_data,
                                                   headers={"Content-Type": "application/json"})
            self.calls_entry_response(request, response.status_code)
            if self.mode == "legacy" and path == LIMITS and request.method == "GET":
                data = response.json()["data"]
                profiles = [data["default_profile"], *data["group_profiles"].values(),
                    *(profile for group in data["endpoint_profiles"].values() for profile in group.values()),
                    *data["provider_ceilings"].values()]
                for profile in profiles:
                    profile.pop("requests_per_10_seconds", None)
                self.send(route, data)
                return
            route.fulfill(status=response.status_code, content_type="application/json", body=response.content)
            return
        require(request.method == "GET", "Nur Limits-Writes sind zulaessig")
        if path == "/api/v1/workspace/environment":
            data = {"synthetic_preview": self.mode == "demo", "read_only": self.mode in {"demo", "read-only"}}
        elif path == "/api/v1/admin/installation":
            data = {"fields": [], "revision": "synthetic", "restart_required": False,
                    "profile_writable": False, "encrypted_secrets_available": False, "providers": {}}
        elif path in {"/api/v1/admin/settings", "/api/v1/ai/tasks", "/api/v1/ai/changes"}:
            data = []
        elif path == "/api/v1/health":
            data = {"status": "ok", "app_version": "synthetic"}
        elif path == "/api/v1/product/readiness":
            data = {"overall_status": "blocked", "next_action": "Synthetischer Teststand."}
        elif path == "/api/v1/ai/provider":
            data = {"config": {"provider": "local", "base_url": "http://127.0.0.1:1", "model": "synthetic",
                "max_tokens": 512, "probe_max_tokens": 32, "timeout_seconds": 30,
                "token_parameter": "max_tokens", "thinking": "server_default"}, "revision": "synthetic",
                "local_enabled": False, "external_enabled": False, "api_key_present": False,
                "api_key_readable": False, "encrypted_secrets_available": False, "configured": False, "source": "test"}
        elif path == "/api/v1/ai/agents":
            data = {"revision": "synthetic", "knowledge": {"version": "synthetic"},
                    "knowledge_sha256": "a" * 64, "profiles": []}
        elif path in {"/api/v1/admin/status", "/api/v1/sources/connector-diagnostics",
                      "/api/v1/sources/jupiter/tokens/metadata-cache"}:
            data = {}
        elif self.fixture.handle(route):
            return
        else:
            raise AssertionError("Unbekannter API-Request: " + path)
        self.send(route, data)

    def calls_entry_response(self, request, status):
        for call in reversed(self.calls):
            if call["method"] == request.method and call["path"] == urlparse(request.url).path and "status" not in call:
                call["status"] = status
                break

    @staticmethod
    def send(route, data):
        route.fulfill(json={"status": "ok", "data": data, "errors": [], "warnings": []})

    def release(self, path):
        self.hold.discard(path)
        held = [route for route in self.pending if urlparse(route.request.url).path == path]
        self.pending = [route for route in self.pending if route not in held]
        require(held, "Kein kontrolliert wartender Request: " + path)
        for route in held:
            self.respond(route)


def show(locator):
    locator.evaluate("""element => {
        element.scrollIntoView({block:'start'});
        const header = document.querySelector('.topbar');
        const offset = header && getComputedStyle(header).position === 'sticky'
            ? header.getBoundingClientRect().height : 0;
        window.scrollBy(0, -offset - 16);
    }""")


def shot(page, limits, output, name, anchor, screenshots):
    show(anchor)
    page.wait_for_function("""() => {
        const nav = document.querySelector('.sidebar');
        return innerWidth > 820 || !nav || (!nav.classList.contains('open') &&
            nav.getBoundingClientRect().right <= 0 && getComputedStyle(nav).visibility === 'hidden');
    }""")
    require(page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Seitenoverflow: " + name)
    bad = limits.evaluate("""section => [...section.querySelectorAll('button,input,select,summary,[role=alert]')]
        .filter(el => el.checkVisibility()).map(el => ({name:el.getAttribute('aria-label') || el.textContent,
            left:el.getBoundingClientRect().left,right:el.getBoundingClientRect().right}))
        .filter(r => r.left < -1 || r.right > innerWidth + 1)""")
    require(not bad, {"screenshot": name, "overflow_controls": bad})
    overlap = limits.evaluate("""section => [...section.querySelectorAll('th,td')]
        .filter(cell => cell.checkVisibility() && getComputedStyle(cell).overflowX === 'visible')
        .map(cell => { const range = document.createRange(); range.selectNodeContents(cell);
            const text = range.getBoundingClientRect(), bounds = cell.getBoundingClientRect();
            return {text:cell.textContent, left:text.left, right:text.right,
                cellLeft:bounds.left, cellRight:bounds.right}; })
        .filter(r => r.left < r.cellLeft - 1 || r.right > r.cellRight + 1)""")
    require(not overlap, {"screenshot": name, "overlapping_table_text": overlap})
    page.screenshot(path=str(output / (name + ".png")), animations="disabled")
    screenshots.append({"file": name + ".png", "viewport": page.viewport_size, "synthetic": True})


def preserved_config(before, after, *, groups=(), endpoints=(), default_changed=False):
    expected = copy.deepcopy(before)
    expected["revision"] = after["revision"]
    if default_changed:
        expected["default_profile"] = after["default_profile"]
    for group in groups:
        expected["group_profiles"][group] = after["group_profiles"][group]
    for provider, endpoint in endpoints:
        expected.setdefault("endpoint_profiles", {}).setdefault(provider, {})[endpoint] = after["endpoint_profiles"][provider][endpoint]
    require(expected == after, {"error": "Nicht betroffene Konfigurationsfelder veraendert", "expected": expected, "actual": after})
    require(after["scheduler_enabled"] is False, "Scheduler ungewollt aktiviert")


@contextmanager
def failure_evidence(page, bridge, output, mode):
    try:
        yield
    except Exception as error:
        evidence = {"case": mode, "passed": False, "error": str(error),
                    "api_calls": bridge.calls, "blocked": bridge.blocked,
                    "javascript_errors": bridge.errors, "synthetic_only": True}
        try:
            page.screenshot(path=str(output / (mode + "-failure.png")), animations="disabled", timeout=5000)
        except Exception as screenshot_error:
            evidence["screenshot_error"] = str(screenshot_error)
        (output / (mode + "-failure.json")).write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        raise
    finally:
        # Gehaltene Requests bei Testabbruch beenden, ohne sie auszufuehren.
        for route in bridge.pending:
            route.abort("blockedbyclient")
        bridge.pending.clear()


def run_case(browser, base, output, mode, state):
    from playwright.sync_api import expect
    import re
    with ExitStack() as stack:
        backend = stack.enter_context(isolated_backend(state))
        context = stack.enter_context(browser.new_context(viewport={"width": 1440, "height": 1000},
                                                          service_workers="block"))
        bridge = Bridge(context, base, backend, mode)
        page = context.new_page()
        stack.enter_context(failure_evidence(page, bridge, output, mode))
        page.on("pageerror", lambda error: bridge.errors.append(str(error)))
        dialogs = []
        page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
        screenshots = []
        before = backend.config()
        document = backend.document()
        contract = contract_checks(backend) if mode == "writable" else None
        if mode == "writable":
            bridge.hold.add(PRESETS)
        elif mode == "preset-empty":
            bridge.empty.add(PRESETS)
        elif mode in {"preset-error", "config-error", "status-error", "environment-error", "endpoint-error"}:
            bridge.fail.add({"preset-error": PRESETS, "config-error": LIMITS,
                "status-error": LIMITS + "/status", "environment-error": "/api/v1/workspace/environment",
                "endpoint-error": LIMITS + "/endpoints"}[mode])
        elif mode == "preset-conflict":
            changed = copy.deepcopy(before)
            changed["group_profiles"]["ip:global"] = copy.deepcopy(changed["default_profile"])
            response = backend.client.put(LIMITS, json={"config": changed, "expected_revision": before["revision"]})
            require(response.status_code == 200, response.text)
            before, document = backend.config(), backend.document()
        page.goto(base + "/#admin", wait_until="domcontentloaded")
        limits = page.get_by_role("region", name="Abrufsteuerung", exact=True)
        expect(limits.get_by_role("heading", name="Abrufsteuerung", exact=True)).to_be_visible()
        if mode == "config-error":
            expect(limits.get_by_role("alert").filter(has_text="Limitprofile konnten nicht gelesen werden")).to_be_visible()
            expect(limits.get_by_role("button", name="Solana-Startprofil anwenden", exact=True)).to_have_count(0)
        else:
            summary = limits.locator("summary").filter(has_text=re.compile("^" + re.escape(SUMMARY) + "$"))
            summary.click()
            apply = limits.get_by_role("button", name="Solana-Startprofil anwenden", exact=True)
            confirm = limits.get_by_role("checkbox", name=re.compile("^" + CONFIRM))
            editor = limits.get_by_text("Lokales Betreiberprofil bearbeiten", exact=True).first
            selector = limits.get_by_label("Limitprofil", exact=True)
            if mode == "writable":
                expect(limits.get_by_role("status").filter(has_text="Serverseitige Preset-Vorschau wird geladen")).to_be_visible()
                expect(apply).to_have_count(0)
                require(not bridge.writes, bridge.writes)
                shot(page, limits, output, "loading-1440", summary, screenshots)
                bridge.release(PRESETS)
                expect(confirm).to_be_enabled()
                expect(apply).to_be_disabled()
                require(not bridge.writes and backend.document() == document, "Preset wurde automatisch angewendet")
                confirm.check()
                expect(apply).to_be_enabled()
                confirm.uncheck()
                expect(apply).to_be_disabled()
                require(not bridge.writes, "Bestaetigung allein hat POST ausgeloest")
                for width in (390, 768, 1280, 1440):
                    page.set_viewport_size({"width": width, "height": 1000})
                    shot(page, limits, output, f"preset-{width}", summary, screenshots)
                confirm.check()
                bridge.hold.add(APPLY)
                # Zwei echte click()-Aktivierungen im selben Browser-Task.
                with page.expect_request(lambda request: request.method == "POST" and urlparse(request.url).path == APPLY):
                    apply.evaluate("button => { button.click(); button.click(); }")
                expect(apply).to_be_disabled()
                require(len(bridge.writes) == 1, {"double_click_writes": bridge.writes})
                require(bridge.writes[0]["body"] == {"expected_revision": before["revision"], "confirmation": True}, bridge.writes)
                require(backend.document() == document, "Verzoegerter POST hat vor Freigabe geschrieben")
                bridge.release(APPLY)
                expect(limits.get_by_role("status").filter(has_text="Solana-Startprofil serverseitig gespeichert")).to_be_visible()
                after = backend.config()
                require(after["revision"] == before["revision"] + 1, after)
                preserved_config(before, after, groups=("ip:global", "provider:solana_rpc"),
                                 endpoints=tuple(("solana_rpc", endpoint) for endpoint in ENDPOINTS))
                for group in ("ip:global", "provider:solana_rpc"):
                    profile = after["group_profiles"][group]
                    require([profile[k] for k in ("requests_per_second", "requests_per_10_seconds", "requests_per_minute", "burst", "max_concurrency")] == [3, 30, 180, 1, 1], profile)
                for endpoint in ENDPOINTS:
                    profile = after["endpoint_profiles"]["solana_rpc"][endpoint]
                    require([profile[k] for k in ("requests_per_second", "requests_per_10_seconds", "requests_per_minute", "burst", "max_concurrency")] == [4, 40, 240, 1, 1], profile)
                backend.unchanged_starts(document)
                expect(confirm).not_to_be_checked()
                editor.click()
                selector.select_option("provider:solana_rpc")
                field = limits.get_by_label(TEN_SECONDS, exact=True)
                expect(field).to_have_value("30")
                field.fill("29")
                save = limits.get_by_role("button", name="Limitprofil speichern", exact=True)
                bridge.hold.add(LIMITS)
                with page.expect_request(lambda request: request.method == "PUT" and urlparse(request.url).path == LIMITS):
                    save.evaluate("button => { button.click(); button.click(); }")
                expect(save).to_be_disabled()
                require(len(bridge.writes) == 2 and bridge.writes[-1]["method"] == "PUT", bridge.writes)
                require(backend.config() == after, "Verzoegerter PUT hat vor Freigabe geschrieben")
                bridge.release(LIMITS)
                expect(limits.get_by_role("status").filter(has_text="Lokales Limitprofil gespeichert")).to_be_visible()
                saved = backend.config()
                preserved_config(after, saved, groups=("provider:solana_rpc",))
                expected_profile = {**after["group_profiles"]["provider:solana_rpc"], "requests_per_10_seconds": 29}
                require(saved["group_profiles"]["provider:solana_rpc"] == expected_profile, saved)
                limits.get_by_role("button", name=RELOAD, exact=True).click()
                expect(field).to_have_value("29")
                # Ein neues Methodenprofil speichern; nicht nur Mock-In-Memory-State pruefen.
                selector.select_option("new-endpoint")
                limits.get_by_role("combobox", name="Anbieter des Endpunktprofils", exact=True).select_option("solana_rpc")
                limits.get_by_role("combobox", name="Endpunkt des Limitprofils", exact=True).select_option("rpc_getbalance")
                field.fill("17")
                limits.get_by_role("button", name="Limitprofil speichern", exact=True).click()
                expect(selector).to_have_value("endpoint-profile:solana_rpc:rpc_getbalance")
                final = backend.config()
                preserved_config(saved, final, endpoints=(("solana_rpc", "rpc_getbalance"),))
                expected_profile = {**saved["group_profiles"]["provider:solana_rpc"], "requests_per_10_seconds": 17}
                require(final["endpoint_profiles"]["solana_rpc"]["rpc_getbalance"] == expected_profile, final)
                # Ganze Seite neu laden und persistierten Stand mit frischer Limiterinstanz pruefen.
                page.reload(wait_until="domcontentloaded")
                expect(limits.get_by_label("Limitprofil", exact=True)).to_be_enabled()
                limits.get_by_text("Lokales Betreiberprofil bearbeiten", exact=True).first.click()
                selector.select_option("endpoint-profile:solana_rpc:rpc_getbalance")
                expect(field).to_have_value("17")
                for width in (390, 768, 1280, 1440):
                    page.set_viewport_size({"width": width, "height": 1000})
                    shot(page, limits, output, f"endpoint-editor-{width}", field.locator(".."), screenshots)
                    budgets = limits.get_by_role("region", name="Lokale Budgetauslastung", exact=True)
                    expect(budgets.get_by_text("Minutenbudget", exact=False).first).to_be_visible()
                    require("rolling_minute" not in budgets.inner_text(), "Technischer Budgetcode in Benutzertext")
                    expect(budgets.get_by_role("columnheader", name="Starts: 1 s / 10 s / 60 s", exact=True)).to_be_visible()
                    shot(page, limits, output, f"budget-{width}", budgets, screenshots)
                from steuerreport_v2.domain.request_limits import RequestLimiter
                fresh = RequestLimiter(state_root=state).read_config().model_dump(mode="json")
                require(fresh == final, "Persistenzpruefung mit frischer Serviceinstanz fehlgeschlagen")
                backend.unchanged_starts(document)
                require(len(bridge.writes) == 3, bridge.writes)
            elif mode == "rpc-provider-profiles":
                # Testwerte, keine Herstellerempfehlung oder automatische Tarifverifikation.
                for provider, second, minute in (("alchemy", "500", "30000"), ("helius", "50", "3000")):
                    selector.select_option("provider:" + provider)
                    expect(limits.get_by_role("status").filter(has_text="noch kein eigenes Profil gespeichert")).to_be_visible()
                    expect(limits.get_by_label("Neue Budgetgruppen-ID", exact=True)).to_have_count(0)
                    require(backend.config() == before, "Anbieterwahl hat bereits gespeichert")
                    if provider == "alchemy":
                        expect(limits.get_by_text("Alchemy: Einheit des Tarifs prüfen.", exact=True)).to_be_visible()
                        expect(limits).to_contain_text("500 CU/s")
                    else:
                        expect(limits).to_contain_text("DAS-/Enhanced-API-Limits")
                    limits.get_by_label("Requests pro Sekunde", exact=True).fill(second)
                    limits.get_by_label("Requests pro Minute", exact=True).fill(minute)
                    limits.get_by_role("button", name="Limitprofil speichern", exact=True).click()
                    expect(limits.get_by_role("status").filter(has_text="Lokales Limitprofil gespeichert")).to_be_visible()
                    saved = backend.config()
                    preserved_config(before, saved, groups=("provider:" + provider,))
                    require(saved["group_profiles"]["provider:" + provider]["requests_per_second"] == int(second), saved)
                    before = saved
                page.reload(wait_until="domcontentloaded")
                expect(selector).to_be_enabled()
                selector.select_option("provider:alchemy")
                expect(limits.get_by_role("columnheader", name="Wirksames Gruppenlimit", exact=True)).to_be_visible()
                if not limits.get_by_label("Requests pro Sekunde", exact=True).is_visible():
                    editor.click()
                expect(limits.get_by_label("Requests pro Sekunde", exact=True)).to_have_value("500")
                # Das separat geerbte gemeinsame IP-Budget bleibt absichtlich strenger.
                expect(limits).to_contain_text("2 Requests/s")
                for width in (390, 768, 1280, 1440):
                    page.set_viewport_size({"width": width, "height": 1000})
                    shot(page, limits, output, f"alchemy-profile-{width}", selector, screenshots)
                limits.get_by_role("button", name="Gemeinsames IP-Limit bearbeiten", exact=True).click()
                expect(selector).to_have_value("ip:global")
                expect(limits.get_by_label("Requests pro Sekunde", exact=True)).to_have_value("2")
                limits.get_by_role("button", name="Limitprofil speichern", exact=True).click()
                expect(limits.get_by_role("status").filter(has_text="Lokales Limitprofil gespeichert")).to_be_visible()
                final = backend.config()
                preserved_config(before, final, groups=("ip:global",))
                from steuerreport_v2.domain.request_limits import RequestLimiter
                fresh = RequestLimiter(state_root=state)
                require(fresh.read_config().model_dump(mode="json") == final, "Anbieterprofile nicht persistent")
                require(fresh.profile("alchemy").requests_per_second == 2, "Gemeinsames IP-Limit wird umgangen")
                require(fresh.profile("helius").requests_per_second == 2, "Helius umgeht gemeinsames IP-Limit")
                backend.unchanged_starts(document)
                require(len(bridge.writes) == 3, bridge.writes)
                document = backend.document()
            elif mode == "legacy":
                expect(confirm).to_be_enabled()
                editor.click()
                field = limits.get_by_label(TEN_SECONDS, exact=True)
                expect(field).to_have_value("")
                limits.get_by_label("Requests pro Sekunde", exact=True).fill("3")
                limits.get_by_role("button", name="Limitprofil speichern", exact=True).click()
                expect(limits.get_by_role("status").filter(has_text="Lokales Limitprofil gespeichert")).to_be_visible()
                after = backend.config()
                require(after["default_profile"]["requests_per_10_seconds"] is None, after)
                preserved_config(before, after, default_changed=True)
                require(after["default_profile"] == {**before["default_profile"], "requests_per_second": 3}, after)
                limits.get_by_role("button", name=RELOAD, exact=True).click()
                expect(field).to_have_value("")
                require(len(bridge.writes) == 1, bridge.writes)
                backend.unchanged_starts(document)
                document = backend.document()
            elif mode == "editor409":
                expect(confirm).to_be_enabled()
                editor.click()
                field = limits.get_by_label(TEN_SECONDS, exact=True)
                field.fill("19")
                response = backend.client.put(LIMITS, json={"config": before, "expected_revision": before["revision"]})
                require(response.status_code == 200, response.text)
                document = backend.document()
                limits.get_by_role("button", name="Limitprofil speichern", exact=True).click()
                expect(limits.get_by_role("alert").filter(has_text="haben sich ge\u00e4ndert")).to_be_visible()
                expect(field).to_have_value("19")
                require(len(bridge.writes) == 1 and bridge.writes[0].get("status") == 409, bridge.writes)
            elif mode == "stale-ceiling":
                limits.get_by_text("Herstellergrenzen aus eigenem Tarif deklarieren", exact=True).click()
                limits.get_by_role("button", name="Deklaration bearbeiten", exact=True).click()
                ceiling = limits.get_by_label("Tarifgrenze Requests pro Sekunde", exact=True)
                confirmation = limits.get_by_role("checkbox", name=re.compile("^Ich habe diese Angaben aus meinem Tarif"))
                save = limits.get_by_role("button", name="Tarifdeklaration speichern", exact=True)
                reset = limits.get_by_role("button", name="Tarifentwurf verwerfen und aktuellen Stand laden", exact=True)
                for trigger, width in (("local", 390), ("global", 1440)):
                    ceiling.fill("8")
                    confirmation.check()
                    expect(save).to_be_enabled()
                    current = backend.config()
                    current["provider_ceilings"]["binance"]["requests_per_second"] = 1
                    response = backend.client.put(LIMITS, json={"config": current, "expected_revision": current["revision"]})
                    require(response.status_code == 200, response.text)
                    concurrent = backend.config()
                    document = backend.document()
                    if trigger == "local":
                        limits.get_by_role("button", name=RELOAD, exact=True).click()
                    else:
                        # Der echte globale Button sendet steuerreport:refresh.
                        page.get_by_role("button", name="Ansicht aktualisieren", exact=True).click()
                    expect(limits.locator("caption").filter(has_text=f"Revision {concurrent['revision']}.")).to_be_visible()
                    expect(confirmation).not_to_be_checked()
                    expect(confirmation).to_be_disabled()
                    expect(ceiling).to_have_value("8")
                    expect(save).to_be_disabled()
                    expect(limits.get_by_role("alert").filter(has_text="seit Beginn dieses Tarifentwurfs")).to_be_visible()
                    # Auch submit ohne Button darf den veralteten Entwurf nicht schreiben.
                    save.evaluate("button => button.form.dispatchEvent(new Event('submit', {bubbles:true,cancelable:true}))")
                    require(not bridge.writes and backend.document() == document, "Veralteter Tarifentwurf hat geschrieben")
                    page.set_viewport_size({"width": width, "height": 1000})
                    shot(page, limits, output, f"stale-ceiling-{trigger}-{width}", ceiling.locator(".."), screenshots)
                    reset.click()
                    expect(ceiling).to_have_value("1")
                    expect(confirmation).not_to_be_checked()
                    expect(confirmation).to_be_enabled()
                    expect(save).to_be_disabled()
                # Erst bewusstes Neuladen plus neue Bestaetigung erlaubt Speichern.
                confirmation.check()
                expect(save).to_be_enabled()
                save.click()
                expect(limits.get_by_role("status").filter(has_text="Tarifgrenze als Betreiberdeklaration gespeichert")).to_be_visible()
                after = backend.config()
                preserved_config(concurrent, after)
                require(len(bridge.writes) == 1 and bridge.writes[0]["body"]["expected_revision"] == concurrent["revision"], bridge.writes)
                require(after["provider_ceilings"]["binance"]["requests_per_second"] == 1, after)
                expect(confirmation).not_to_be_checked()
                document = backend.document()
            elif mode in {"demo", "read-only", "environment-error"}:
                expect(confirm).to_be_disabled()
                expect(apply).to_be_disabled()
                editor.click()
                expect(limits.get_by_label(TEN_SECONDS, exact=True)).to_be_disabled()
                expect(limits.get_by_role("button", name="Limitprofil speichern", exact=True)).to_be_disabled()
                message = {"demo": "Demo-/Testmodus mit synthetischen Daten.",
                           "read-only": "Diese Installation ist schreibgesch\u00fctzt.",
                           "environment-error": "Der Betriebsmodus konnte nicht gepr\u00fcft werden."}[mode]
                expect(limits.get_by_text(message, exact=False)).to_be_visible()
                selector.select_option("provider:alchemy")
                expect(limits.get_by_label("Requests pro Sekunde", exact=True)).to_be_disabled()
                expect(limits.get_by_role("button", name="Limitprofil speichern", exact=True)).to_be_disabled()
                require(not bridge.writes, bridge.writes)
            elif mode in {"preset-empty", "preset-error"}:
                expect(apply).to_have_count(0)
                message = "Der Server bietet dieses Startprofil nicht an." if mode == "preset-empty" else "Die Preset-Vorschau ist nicht verf\u00fcgbar."
                expect(limits.get_by_text(message, exact=False)).to_be_visible()
                if mode == "preset-error":
                    bridge.fail.clear()
                    limits.get_by_role("button", name="Vorschau neu laden", exact=True).click()
                    expect(confirm).to_be_enabled()
                    expect(apply).to_be_disabled()
            elif mode == "status-error":
                expect(limits.get_by_role("alert").filter(has_text="Der Abrufkoordinator konnte nicht gelesen werden")).to_be_visible()
                bridge.fail.clear()
                limits.get_by_role("button", name="Status erneut lesen", exact=True).click()
                expect(limits.get_by_text("Minutenbudget", exact=False).first).to_be_visible()
            elif mode == "endpoint-error":
                selector.select_option("new-endpoint")
                expect(limits.get_by_role("combobox", name="Endpunkt des Limitprofils", exact=True)).to_be_disabled()
                expect(limits.get_by_role("button", name="Limitprofil speichern", exact=True)).to_be_disabled()
            elif mode == "preset-conflict":
                expect(limits.get_by_role("alert").filter(has_text="Abweichende vorhandene Profile")).to_contain_text("ip:global")
                expect(confirm).to_be_disabled()
                expect(apply).to_be_disabled()
                response = backend.client.post(APPLY, json={"expected_revision": before["revision"], "confirmation": True})
                require(response.status_code == 409, response.text)
            elif mode in {"conflict409", "post-error", "demo-error"}:
                expect(confirm).to_be_enabled()
                confirm.check()
                if mode == "conflict409":
                    response = backend.client.put(LIMITS, json={"config": before, "expected_revision": before["revision"]})
                    require(response.status_code == 200, response.text)
                    document = backend.document()
                elif mode == "post-error":
                    bridge.fail.add(APPLY)
                else:
                    backend.app.state.ux_sandbox = True
                apply.click()
                expected = {"conflict409": "haben sich ge\u00e4ndert", "post-error": "es wurde kein Erfolg best\u00e4tigt",
                            "demo-error": "Demo-/Testumgebung sperrt"}[mode]
                expect(limits.get_by_role("alert").filter(has_text=expected)).to_be_visible()
                expect(confirm).not_to_be_checked()
                expect(apply).to_be_disabled()
                require(len(bridge.writes) == 1, bridge.writes)
            else:
                raise AssertionError("Unbekannter Prueffall: " + mode)
        if mode != "writable":
            require(backend.document() == document, "Fehler-/Lesefall hat Zustand veraendert: " + mode)
            if mode not in {"conflict409", "post-error", "demo-error", "editor409", "legacy", "stale-ceiling", "rpc-provider-profiles"}:
                require(not bridge.writes, bridge.writes)
            shot(page, limits, output, mode + "-1440", limits, screenshots)
        require(not dialogs, {"unexpected_dialogs": dialogs})
        require(not bridge.blocked and not bridge.errors and not bridge.pending,
                {"blocked": bridge.blocked, "errors": bridge.errors, "pending": len(bridge.pending)})
        require(all(call["path"] in {LIMITS, APPLY} for call in bridge.writes), "Externe Aktion gestartet")
        return {"case": mode, "passed": True, "actual_limits_backend": True, "contract": contract,
                "api_calls": bridge.calls, "writes": bridge.writes, "screenshots": screenshots,
                "blocked": bridge.blocked, "javascript_errors": bridge.errors}


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-executable", help="Optional; sonst Playwright-Standardbrowser verwenden.")
    parser.add_argument("--output", type=Path, help="Neues Nachweisverzeichnis unter System-Temp oder RUNNER_TEMP.")
    parser.add_argument("--self-test", action="store_true", help="Nur echten API-Vertrag ohne Browser pruefen.")
    args = parser.parse_args()
    output = args.output.resolve() if args.output else Path(tempfile.mkdtemp(prefix="steuerreport-solana-browser-"))
    temporary_roots = {Path(tempfile.gettempdir()).resolve()}
    if os.environ.get("RUNNER_TEMP"):
        temporary_roots.add(Path(os.environ["RUNNER_TEMP"]).resolve())
    disposable = any(root != Path(root.anchor) and output != root and output.is_relative_to(root)
                     for root in temporary_roots)
    if not disposable or output.is_relative_to(ROOT):
        parser.error("Nachweise duerfen nur ausserhalb des Repos im Tempverzeichnis geschrieben werden.")
    output.mkdir(parents=True, exist_ok=True)
    result_path = output / "result.json"
    if result_path.exists():
        parser.error("Vorhandene Nachweise nicht ueberschreiben; ein neues --output waehlen.")
    result = {"scope": "Echtes Frontend + echter isolierter Limits-Router/Dateikoordinator; andere APIs synthetisch.",
              "synthetic_only": True, "live_state_accessed": False, "external_provider_requests": 0,
              "financial_release": False, "results": [], "passed": False}
    try:
        with ExitStack() as stack:
            state = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="steuerreport-solana-state-")))
            if args.self_test:
                with isolated_backend(state) as backend:
                    result["contract"] = contract_checks(backend)
                result["self_test_only"] = True
            else:
                dist = ROOT / "frontend/dist"
                index = dist / "index.html"
                require(index.is_file(), "Main muss zuerst das Frontend bauen.")
                newest = max(path.stat().st_mtime for path in (ROOT / "frontend/src").rglob("*") if path.is_file())
                require(index.stat().st_mtime >= newest, "Frontend-Build ist aelter als der Quellstand; Main muss neu bauen.")
                result["frontend_sha256"] = {str(path.relative_to(dist)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(dist.rglob("*")) if path.is_file() and path.suffix in {".html", ".js", ".css"}}
                server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(dist)))
                worker = Thread(target=server.serve_forever, daemon=True)
                worker.start()
                stack.callback(server.server_close)
                stack.callback(worker.join)
                stack.callback(server.shutdown)
                from playwright.sync_api import expect, sync_playwright
                expect.set_options(timeout=15000)
                playwright = stack.enter_context(sync_playwright())
                browser = stack.enter_context(playwright.chromium.launch(headless=True, executable_path=args.browser_executable))
                base = f"http://127.0.0.1:{server.server_port}"
                for mode in ("writable", "rpc-provider-profiles", "legacy", "stale-ceiling", "preset-empty", "preset-error", "config-error", "status-error",
                             "endpoint-error", "environment-error", "read-only", "demo", "preset-conflict",
                             "conflict409", "editor409", "post-error", "demo-error"):
                    print("CHECK", mode, flush=True)
                    try:
                        result["results"].append(run_case(browser, base, output, mode, state / mode))
                    except Exception as error:
                        result["results"].append({"case": mode, "passed": False, "error": str(error)})
                        print("FAIL", mode, str(error), flush=True)
                failures = [case["case"] for case in result["results"] if not case["passed"]]
                require(not failures, {"failed_cases": failures})
            result["passed"] = True
    except Exception as error:
        result["error"] = str(error)
        raise
    finally:
        result["screenshots_count"] = len(list(output.glob("*.png")))
        result_path.write_text(json.dumps(result, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"passed": result["passed"], "cases": len(result["results"]),
                          "screenshots": result["screenshots_count"], "result": str(result_path)}), flush=True)


if __name__ == "__main__":
    main()
