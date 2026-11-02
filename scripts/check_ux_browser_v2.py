"""Reproduzierbarer UX-Smoke-Test mit ausschliesslich synthetischen API-Antworten.

Voraussetzungen: Frontend-Server und Playwright mit Chromium.
Beispiel: python scripts/check_ux_browser_v2.py --base-url http://localhost:5174
Kein Request an /api wird an einen echten Dienst weitergegeben.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright
from check_workspace_browser_v2 import check_workspace
from check_admin_browser_v2 import check_admin
from ux_workspace_fixtures import WorkspaceFixture


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", help="Ohne Angabe wird frontend/dist lokal auf einem freien Port bereitgestellt.")
    parser.add_argument("--browser-executable")
    parser.add_argument("--workspace-only", action="store_true", help="Nur die neuen A01-A23-Browserabläufe prüfen.")
    parser.add_argument("--output", type=Path, default=Path("artifacts/ux-browser"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    api_requests: list[tuple[str, str]] = []
    errors: list[str] = []
    workspace = WorkspaceFixture()
    config = {"provider": "openrouter", "base_url": "https://openrouter.ai/api/v1",
              "model": "example/test:free", "max_tokens": 1024, "probe_max_tokens": 32,
              "timeout_seconds": 60, "token_parameter": "max_tokens", "thinking": "server_default"}
    provider = {"config": config, "revision": "test-revision", "local_enabled": True,
                "external_enabled": True, "api_key_present": True, "api_key_readable": True,
                "encrypted_secrets_available": True, "configured": True, "source": "test"}
    roles = ["coordinator", "import_sources", "crypto_forensics", "wallet_fifo", "tax_rewards", "valuation", "documentation"]
    agents = {"revision": "test-agents", "knowledge": {"version": "test"}, "knowledge_sha256": "a" * 64,
              "profiles": [{"agent_id": role, "name": role, "instructions": "Nur synthetische Testdaten pruefen.",
                            "enabled": True, "models": {"local": "", "openrouter": "", "cloud": ""}} for role in roles]}

    def mock(route):
        if workspace.handle(route):
            return
        path = urlparse(route.request.url).path
        method = route.request.method
        api_requests.append((method, path))
        data: object = {}
        if path == "/api/v1/health":
            data = {"app_version": "test", "status": "ok"}
        elif path == "/api/v1/cockpit/summary":
            data = {"portfolio_value_eur": "1000.00", "export_allowed": False, "export_status": "blocked",
                    "tasks": [], "top_assets": [], "top_sources": [], "open_tasks": 0,
                    "portfolio_performance": {"live_value_eur": "1000.00", "calculated_value_eur": "990.00"}}
        elif path == "/api/v1/product/readiness":
            data = {"overall_status": "blocked", "next_action": "Synthetische Belegluecke pruefen."}
        elif path == "/api/v1/import/profiles":
            data = [{"source": "manual-csv", "label": "Manuelle CSV"}]
        elif path in {"/api/v1/import/batches", "/api/v1/ai/tasks", "/api/v1/ai/changes", "/api/v1/admin/settings"}:
            data = []
        elif path == "/api/v1/ai/provider":
            data = provider
        elif path == "/api/v1/ai/agents":
            data = agents
        elif path == "/api/v1/ai/data-context":
            data = {"total": 0, "rows": [], "context_sha256": "b" * 64}
        elif path == "/api/v1/import/assistant/preview":
            data = {"can_execute": True, "warnings": [], "preview": {
                "row_count": 1, "columns": ["time", "asset", "amount", "type", "account"],
                "sample_rows": [{"time": "2025-02-01T10:00:00Z", "asset": "EUR", "amount": "10", "type": "deposit", "account": "test-account"}],
                "sheet_names": [], "file_sha256": "sha256:" + "c" * 64,
                "missing_required_groups": [], "profile_label": "Manuelle CSV"}}
        elif path == "/api/v1/admin/installation":
            data = {"fields": [], "revision": "test", "restart_required": False,
                    "profile_writable": True, "encrypted_secrets_available": True, "providers": {}}
        elif path.startswith("/api/v1/admin/installation/configs/"):
            data = {"filename": path.rsplit("/", 1)[-1], "content": "{}", "revision": "test"}
        elif path.endswith("/metadata-cache"):
            data = {}
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"status": "ok", "data": data, "errors": [], "warnings": []}))

    with ExitStack() as stack:
        if not args.base_url:
            root = Path(__file__).resolve().parents[1] / "frontend/dist"
            if not (root / "index.html").is_file():
                parser.error("Zuerst im Frontend npm run build ausfuehren.")

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
        browser = playwright.chromium.launch(headless=True, executable_path=args.browser_executable)
        if args.workspace_only:
            check_workspace(browser, args.base_url, args.output)
            browser.close()
            return
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        # Every API is intercepted, including accidental model calls or writes.
        context.route("**/api/**", mock)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.base_url + "/#help", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Hilfe & Anleitungen", exact=True)).to_be_visible()
        assert not api_requests, "Direkter Hilfeeinstieg darf keine API benoetigen."
        expect(page.get_by_role("button", name="Expertenwerkzeuge anzeigen", exact=True)).to_have_count(0)
        search = page.get_by_role("searchbox", name="Hilfe durchsuchen")
        search.fill("Anschaffung")
        expect(page.get_by_text("Keine passenden Hilfethemen.", exact=False)).to_have_count(0)
        search.fill("Pr\u00fcfung")
        expect(page.get_by_text("Keine passenden Hilfethemen.", exact=False)).to_have_count(0)
        search.fill("Free-Modelle")
        expect(page.get_by_text("Keine passenden Hilfethemen.", exact=False)).to_have_count(0)
        page.get_by_role("button", name="Filter zuruecksetzen").click()
        search.fill("krzz-kein-treffer")
        expect(page.get_by_text("Keine passenden Hilfethemen.", exact=False)).to_be_visible()
        page.get_by_role("button", name="Filter zuruecksetzen").click()
        page.get_by_role("combobox", name="Hilfebereich").select_option("import")
        expect(page.get_by_text("Die Dateiendung allein reicht nicht.", exact=False)).to_be_visible()
        page.get_by_role("link", name="Bereich oeffnen", exact=True).click()
        expect(page.get_by_role("heading", name="Daten importieren", exact=True)).to_be_visible()
        expect(page.get_by_text("Zuerst die Quelle fuer deine Dateien waehlen.", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Dateien pruefen", exact=True)).to_be_disabled()

        tip = page.get_by_role("button", name="Hilfe: Importquelle und Dateiformat", exact=True)
        tip.focus()
        expect(page.get_by_role("tooltip")).to_be_visible()
        assert tip.get_attribute("aria-describedby") == page.get_by_role("tooltip").get_attribute("id")
        page.keyboard.press("Escape")
        expect(page.get_by_role("tooltip")).to_have_count(0)
        tip.hover()
        expect(page.get_by_role("tooltip")).to_be_visible()
        page.get_by_role("tooltip").hover()
        page.wait_for_timeout(220)
        expect(page.get_by_role("tooltip")).to_be_visible()
        page.keyboard.press("Escape")

        page.get_by_role("combobox", name="Importquelle", exact=True).select_option("manual-csv")
        expect(page.get_by_text("Dateien auswaehlen oder hierher ziehen.", exact=True)).to_be_visible()
        page.get_by_label("Importdateien auswaehlen", exact=True).set_input_files({
            "name": "synthetischer-import.csv", "mimeType": "text/csv",
            "buffer": b"time,asset,amount,type,account\n2025-02-01T10:00:00Z,EUR,10,deposit,test-account\n"})
        expect(page.get_by_text("Dateien pruefen und danach die Vorschau kontrollieren.", exact=True)).to_be_visible()
        page.get_by_role("button", name="Dateien pruefen", exact=True).click()
        expect(page.get_by_text("Vorschau und Warnungen pruefen, dann die geprueften Dateien freigeben.", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="1 Datei(en) importieren", exact=True)).to_be_disabled()
        for width in (1440, 390, 320):
            page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 844})
            if width < 821:
                expect(page.locator(".sidebar")).not_to_be_in_viewport()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Import overflow: {width}"
            page.screenshot(path=str(args.output / f"import-{width}.png"))

        page.set_viewport_size({"width": 1440, "height": 1000})
        with page.expect_popup() as opened:
            page.get_by_role("link", name="Hilfe zum Bereich", exact=True).click()
        help_tab = opened.value
        help_tab.on("pageerror", lambda error: errors.append(str(error)))
        expect(help_tab.get_by_role("combobox", name="Hilfebereich")).to_have_value("import")
        expect(page.get_by_role("combobox", name="Importquelle", exact=True)).to_have_value("manual-csv")
        expect(page.get_by_text("synthetischer-import.csv", exact=True)).to_be_visible()
        help_tab.close()
        page.goto(args.base_url + "/#help", wait_until="networkidle")
        for width in (1440, 390, 320):
            page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 844})
            if width < 821:
                expect(page.locator(".sidebar")).not_to_be_in_viewport()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Help overflow: {width}"
            page.screenshot(path=str(args.output / f"help-{width}.png"))
        for link in page.locator(".helpDocuments a").all():
            href = link.get_attribute("href")
            response = page.request.get(args.base_url + href)
            assert response.status == 200, href
            if href.endswith(".pdf"):
                assert response.body().startswith(b"%PDF-"), href

        page.set_viewport_size({"width": 1440, "height": 1000})
        page.goto(args.base_url + "/#dashboard", wait_until="networkidle")
        page.get_by_role("button", name="Hilfe: Gespeicherte Live-Anker", exact=True).focus()
        expect(page.get_by_role("tooltip")).to_have_count(1)
        expect(page.get_by_role("tooltip")).to_contain_text("kein bestätigtes Gesamtvermögen")
        page.keyboard.press("Escape")
        for width in (1440, 390, 320):
            page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 844})
            if width < 821:
                expect(page.locator(".sidebar")).not_to_be_in_viewport()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Dashboard overflow: {width}"
            page.screenshot(path=str(args.output / f"dashboard-{width}.png"))

        page.set_viewport_size({"width": 1440, "height": 1000})
        page.goto(args.base_url + "/#ai", wait_until="networkidle")
        expect(page.get_by_label("KI-Aufgabentext", exact=True)).to_be_visible()
        expect(page.get_by_label("KI-Anbieter", exact=True)).to_be_hidden()
        expect(page.get_by_text("Aufgabentext eingeben.", exact=True)).to_be_visible()
        page.get_by_label("KI-Aufgabentext", exact=True).fill("Pruefe diesen synthetischen Text.")
        expect(page.get_by_text("Vor dem Senden die Cloud-Freigabe bestaetigen.", exact=True)).to_be_visible()
        expect(page.get_by_role("button", name="Aufgabe ausfuehren", exact=True)).to_be_disabled()
        page.get_by_role("tab", name="Datenkorrekturen", exact=True).click()
        expect(page.get_by_label("Korrektur-Datenart", exact=True)).to_be_visible()
        for width in (1440, 390, 320):
            page.set_viewport_size({"width": width, "height": 1000 if width == 1440 else 844})
            if width < 821:
                expect(page.locator(".sidebar")).not_to_be_in_viewport()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"AI overflow: {width}"
            tip = page.get_by_role("button", name="Hilfe: Korrektur und Freigabe", exact=True)
            tip.click()
            tooltip = page.get_by_role("tooltip")
            expect(tooltip).to_be_visible()
            box = tooltip.bounding_box()
            assert box and box["x"] >= 0 and box["x"] + box["width"] <= width
            page.screenshot(path=str(args.output / f"ai-tooltip-{width}.png"))
            page.keyboard.press("Escape")
        # Genuine touch events, not just a smaller desktop viewport.
        touch = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        touch.route("**/api/**", mock)
        mobile = touch.new_page()
        mobile.on("pageerror", lambda error: errors.append(str(error)))
        mobile.goto(args.base_url + "/#import", wait_until="networkidle")
        mobile.get_by_role("button", name="Hilfe: Daten importieren", exact=True).tap()
        expect(mobile.get_by_role("tooltip")).to_be_visible()
        mobile.get_by_role("button", name="Hilfe: Daten importieren", exact=True).tap()
        expect(mobile.get_by_role("tooltip")).to_have_count(0)
        mobile.get_by_role("button", name="Navigation öffnen", exact=True).tap()
        mobile.get_by_role("button", name="Hilfe & Anleitungen", exact=True).tap()
        expect(mobile.get_by_role("heading", name="Hilfe & Anleitungen", exact=True)).to_be_visible()
        expect(mobile.get_by_role("button", name="Navigation öffnen", exact=True)).to_have_attribute("aria-expanded", "false")
        # Setup must be visible for a new installation, but diagnostics stay optional.
        provider["configured"] = False
        provider["config"] = {**config, "model": ""}
        provider["external_enabled"] = False
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.goto(args.base_url + "/#ai", wait_until="networkidle")
        page.reload(wait_until="networkidle")
        expect(page.get_by_label("KI-Anbieter", exact=True)).to_be_visible()
        expect(page.get_by_text("Aktivierte Verbindung und Modell zuerst speichern.", exact=True)).to_be_visible()
        page.goto(args.base_url + "/#admin", wait_until="networkidle")
        expect(page.get_by_text("Technische Diagnose und erweiterte Einstellungen", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="Installation", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="Eigene Verbindungen", exact=True)).to_be_visible()
        expect(page.get_by_text("CEX-Credentials speichern", exact=True)).not_to_be_visible()
        technical = page.locator("details.advancedSettings").filter(has=page.get_by_text("Technische Diagnose und erweiterte Einstellungen", exact=True))
        assert technical.get_attribute("open") is None
        page.get_by_text("Technische Diagnose und erweiterte Einstellungen", exact=True).click()
        assert technical.get_attribute("open") is not None
        assert not errors, errors
        writes = [entry for entry in api_requests if entry[0] != "GET"]
        assert writes == [("POST", "/api/v1/import/assistant/preview")], writes
        result = {"all_api_responses_synthetic": True, "real_api_calls": 0, "real_model_calls": 0,
                  "help_without_api": True, "search_and_context_links": True, "document_links_verified": True,
                  "context_help_preserves_unsaved_workspace": True,
                  "keyboard_hover_and_touch_tooltips": True, "guided_import_preview_no_execution": True,
                  "ai_setup_collapsed_when_configured": True, "cloud_task_requires_explicit_consent": True,
                  "desktop_mobile_320_390_1440_no_overflow": True, "javascript_errors": errors}
        (args.output / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
        acceptance = check_workspace(browser, args.base_url, args.output)
        print(json.dumps({"workspace_scenarios": len(acceptance["scenarios"]), "external_requests": acceptance["external_requests"]}))
        check_admin(browser, args.base_url, args.output / "admin")
        browser.close()


if __name__ == "__main__":
    main()
