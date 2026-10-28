"""Synthetische Reports-UX-Abnahme, keine fiskalische Backend-Freigabe."""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
import json
from pathlib import Path
from threading import Thread
from urllib.parse import parse_qs, urlparse
import zipfile

from playwright.sync_api import Error as PlaywrightError, expect, sync_playwright

from ux_workspace_fixtures import WorkspaceFixture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--browser-executable")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(root / "frontend/dist")))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    fixture = WorkspaceFixture()
    state = {"binding": "current", "final": False, "mode": "ready"}
    held, calls, errors, external, screenshots = [], [], [], [], []

    def respond(route):
        request = route.request
        parsed = urlparse(request.url)
        if parsed.netloc != urlparse(origin).netloc:
            external.append(request.url)
            route.abort()
        elif parsed.path.startswith("/api/"):
            calls.append((request.method, parsed.path))
            if parsed.path == "/api/v1/workspace/status":
                if state["mode"] == "loading":
                    held.append(route)
                    return
                if state["mode"] == "error":
                    fixture.send(route, {}, 503)
                    return
                year = int(parse_qs(parsed.query).get("year", [2025])[0])
                data = fixture.status(year)
                data["readiness"].update(snapshot_binding_status=state["binding"],
                                         can_file_without_review=state["final"], ready_years=[year])
                if state["binding"] == "legacy":
                    del data["readiness"]["snapshot_binding_status"]
                # Contradictory final=true for old/unbound states must not leak through.
                data.update(final_available=state["final"], summary="Synthetischer Pruefstand")
                fixture.send(route, data)
            elif parsed.path.startswith("/api/v1/tax-years/") and parsed.path.count("/") == 4 and state["mode"].startswith("annual_"):
                if state["mode"] == "annual_loading":
                    held.append(route)
                else:
                    fixture.send(route, {}, 503)
            elif parsed.path == "/api/v1/export/readiness":
                fixture.send(route, {"allow_export": True, "technical_export_allowed": True,
                                     "final_filing_allowed": False, "filing_status": "technical_only"})
            elif parsed.path.endswith("evidence-package.zip"):
                body = io.BytesIO()
                with zipfile.ZipFile(body, "w") as archive:
                    archive.writestr("manifest.json", json.dumps({"synthetic": True, "filing_status": "preview"}))
                    archive.writestr("README.md", "SYNTHETISCHE VORSCHAU - keine fiskalische Freigabe")
                route.fulfill(body=body.getvalue(), content_type="application/zip")
            elif parsed.path.endswith("filing-checklist.csv"):
                route.fulfill(body="year,status\n2024,synthetic_preview\n", content_type="text/csv")
            elif not fixture.handle(route):
                fixture.send(route, {})
        else:
            route.continue_()

    def screenshot(page, name):
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), name
        assert page.evaluate("""() => [...document.querySelectorAll('.wsPage button, .wsDetailPanel button')]
          .filter(e => e.offsetWidth).every(e => e.scrollWidth <= e.clientWidth + 1)"""), name
        page.screenshot(path=str(args.output / f"{name}.png"), full_page=True, animations="disabled")
        screenshots.append(name + ".png")

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=args.browser_executable)
            for width in (390, 768, 1280, 1440):
                context = browser.new_context(viewport={"width": width, "height": 1000}, service_workers="block", accept_downloads=True)
                context.route("**/*", respond)
                for kind in ("tax", "export"):
                    for scenario in ("loading", "error", "annual_loading", "annual_error", "missing", "legacy", "unbound", "stale", "current", "final"):
                        state.update(mode=scenario if scenario in {"loading", "error", "annual_loading", "annual_error"} else "ready",
                                     binding="current" if scenario in {"final", "annual_loading", "annual_error"} else scenario,
                                     final=scenario not in {"loading", "error", "current"})
                        page = context.new_page()
                        page.on("pageerror", lambda error: errors.append(str(error)))
                        page.goto(origin + f"/#{kind}?year=2024", wait_until="domcontentloaded")
                        region = page.get_by_role("region", name="Paketstatus und Datenbindung", exact=True)
                        expect(region).to_be_visible()
                        if scenario == "final":
                            expect(region).to_contain_text("Jahresfreigabe bestätigt")
                        else:
                            expect(region).to_contain_text("Vorschau · keine finale Jahresfreigabe")
                            expect(page.get_by_text("Vorhandene Freigaben erfüllt", exact=True)).to_have_count(0)
                        expected = {"loading": "Prüfstand wird geladen", "error": "Prüfstand nicht verfügbar",
                                    "annual_loading": "Jahresauswertung wird geladen", "annual_error": "Jahresauswertung nicht verfügbar",
                                    "legacy": "Eingangsbindung nicht bestätigt",
                                    "missing": "Methoden-Prüfstand fehlt", "unbound": "Methoden-Prüfstand ohne Eingangsbindung",
                                    "stale": "Eingangsbindung veraltet", "current": "Eingangsbindung aktuell", "final": "Eingangsbindung aktuell"}
                        expect(region).to_contain_text(expected[scenario])
                        if kind == "export":
                            expect(page.get_by_role("link", name="Vorschau öffnen", exact=True)).to_have_attribute(
                                "href", origin + "/api/v1/tax-years/2024/filing-summary.html")
                            button = page.get_by_role("button", name="Paket erstellen / laden" if scenario == "final" else "Vorschaupaket erstellen / laden", exact=True)
                            if scenario in {"loading", "error"}:
                                expect(button).to_be_disabled()
                            else:
                                expect(button).to_be_enabled()
                            expect(page.get_by_text("Technischer PDF-Export möglich; keine finale Jahresfreigabe", exact=True)).to_be_visible()
                        screenshot(page, f"{kind}-{scenario}-{width}")
                        if kind == "export" and scenario == "current":
                            button.click()
                            dialog = page.get_by_role("dialog", name="Vorschau-Belegpaket", exact=True)
                            expect(dialog).to_contain_text("Steuerjahr 2024")
                            expect(dialog).to_contain_text("Ein Download erteilt keine finale Jahresfreigabe")
                            screenshot(page, f"export-preview-dialog-{width}")
                            with page.expect_download() as downloaded:
                                dialog.get_by_role("button", name="Bestätigen und herunterladen", exact=True).click()
                            with zipfile.ZipFile(downloaded.value.path()) as archive:
                                assert json.loads(archive.read("manifest.json"))["filing_status"] == "preview"
                            assert ("GET", "/api/v1/export/tax-years/2024/evidence-package.zip") in calls
                            dialog.get_by_role("button", name="Schließen", exact=True).click()
                            page.get_by_role("button", name="Checkliste laden", exact=True).click()
                            checklist = page.get_by_role("dialog", name="Jahrescheckliste", exact=True)
                            with page.expect_download():
                                checklist.get_by_role("button", name="Bestätigen und herunterladen", exact=True).click()
                            assert ("GET", "/api/v1/export/tax-years/2024/filing-checklist.csv") in calls
                            checklist.get_by_role("button", name="Schließen", exact=True).click()
                        if kind == "tax" and scenario == "current":
                            page.get_by_role("button", name="Berichte und Umfang prüfen", exact=True).click()
                            expect(page).to_have_url(origin + "/#export?year=2024")
                        if scenario == "final":
                            state["mode"] = "loading"
                            page.evaluate("window.dispatchEvent(new Event('steuerreport:refresh'))")
                            expect(region).to_contain_text("Prüfstand wird geladen")
                            expect(page.get_by_text("Vorhandene Freigaben erfüllt", exact=True)).to_have_count(0)
                            screenshot(page, f"{kind}-refresh-{width}")
                            page.evaluate(f"location.hash = '#{kind}?year=2025'")
                            expect(region).to_contain_text("2025")
                            expect(region).to_contain_text("Vorschau · keine finale Jahresfreigabe")
                            screenshot(page, f"{kind}-year-change-{width}")
                        for route in held:
                            try:
                                route.abort()
                            except PlaywrightError:
                                pass  # Already cancelled by a year change / AbortSignal.
                        held.clear()
                        page.close()
                context.close()
            browser.close()
        assert not errors, errors
        assert not external, external
        assert all(method == "GET" for method, _ in calls), calls
        report = {"status": "passed", "evidence_type": "synthetic_controlled_api_not_fiscal_acceptance",
                  "widths": [390, 768, 1280, 1440], "screenshots": screenshots,
                  "api_calls": len(calls), "external_requests": external, "page_errors": errors}
        (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
