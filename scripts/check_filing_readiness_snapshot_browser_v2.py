#!/usr/bin/env python3
"""Synthetic browser check for the explicit filing-readiness snapshot action.

Build the frontend first. This test serves only the generated static bundle and
intercepts every API request; it never starts the application or contacts a provider.
"""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIST = ROOT / "frontend/dist"
INPUT_HASH = "a" * 64


def api_response(data: object, *, status: str = "ok") -> dict[str, object]:
    return {"status": status, "data": data, "errors": [], "warnings": []}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser-executable", type=Path)
    args = parser.parse_args()
    if not (FRONTEND_DIST / "index.html").is_file():
        raise SystemExit("Frontend-Build fehlt; zuerst frontend npm run build ausfuehren.")

    request_log: list[tuple[str, str, dict[str, object] | None]] = []
    mode = {"value": "completed"}
    snapshot_created = {"value": False}

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(QuietHandler, directory=str(FRONTEND_DIST))
    )
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"

    def route_api(route) -> None:
        request = route.request
        parts = urlsplit(request.url)
        payload = None
        if request.method == "POST":
            try:
                payload = request.post_data_json
            except Exception:
                payload = None
        request_log.append((request.method, parts.path, payload))

        if request.method == "GET" and parts.path == "/api/v1/workspace/status":
            data = {
                "generated_at": "2026-10-29T12:00:00Z",
                "year": 2025,
                "events_count": 1,
                "imports_count": 1,
                "balance_entries": 1,
                "owned_sources_count": 1,
                "calculation_stale": False,
                "review": {"allow_export": False, "issues_open": 1, "blocking_issues_open": 1, "issues": []},
                "readiness": {
                    "snapshot_binding_status": "missing",
                    "can_file_without_review": False,
                    "ready_years": [],
                    "checks": [],
                    "methodology": "Synthetische Browserprobe",
                },
                "preview_available": True,
                "final_available": False,
                "summary": "Synthetische Vorschau; keine finale Freigabe",
                "next_section": "tax",
                "next_action": "Pruefpunkte klaeren",
                "dimensions": {
                    "data": "Synthetische Daten",
                    "calculation": "Berechnet",
                    "methodology": "Pruefstand fehlt",
                    "review": "Offen",
                    "year": "Nicht freigegeben",
                    "export": "Nur Vorschau",
                },
            }
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(api_response(data)))

        if request.method == "GET" and parts.path == "/api/v1/tax-years/2025":
            data = {
                "year": 2025,
                "state": "preview",
                "realized_gain_loss_eur": "0",
                "tax_free_gain_loss_eur": "0",
                "rewards_income_eur": "0",
                "derivative_pnl_eur": "0",
                "taxable_disposal_proceeds_eur": "0",
                "acquisition_cost_eur": "0",
                "tax_lines_count": 0,
                "issues": [],
                "methodology": "Synthetische Browserprobe",
            }
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(api_response(data)))

        if request.method == "GET" and parts.path == "/api/v1/tax-methodology/bmf-filing-readiness-snapshot":
            if snapshot_created["value"]:
                data = {
                    "status": "available",
                    "binding_status": "current",
                    "generated_at": "2026-10-29T12:01:00Z",
                    "note": "Synthetischer Snapshot mit aktueller Eingangsbindung.",
                }
            else:
                data = {
                    "status": "missing",
                    "binding_status": "missing",
                    "generated_at": "2026-10-29T12:00:00Z",
                    "note": "Noch kein gebundener Methoden-Pruefstand vorhanden.",
                }
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(api_response(data)))

        if request.method == "GET" and parts.path == "/api/v1/tax-methodology/bmf-filing-readiness":
            data = {
                "input_binding_sha256": INPUT_HASH,
                "latest_tax_run_id": "synthetic-run-2025",
                "available_years": [2025],
                "ready_years": [],
                "conservative_appendix_years": [],
                "review_years": [2025],
                "blocked_years": [],
                "empty_years": [],
            }
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(api_response(data)))

        if request.method == "POST" and parts.path == "/api/v1/tax-methodology/bmf-filing-readiness-snapshot":
            if mode["value"] == "conflict":
                body = {
                    "status": "warning",
                    "data": None,
                    "errors": [{"code": "filing_readiness_inputs_changed", "message": "Synthetic conflict"}],
                    "warnings": [],
                }
                return route.fulfill(status=409, content_type="application/json", body=json.dumps(body))
            snapshot_created["value"] = True
            report = {
                "input_binding_sha256": INPUT_HASH,
                "latest_tax_run_id": "synthetic-run-2025",
                "available_years": [2025],
                "ready_years": [],
                "conservative_appendix_years": [],
                "review_years": [2025],
                "blocked_years": [],
                "empty_years": [],
            }
            data = {
                "operation_id": "synthetic-operation-1",
                "scope": "years_2021_2025",
                "status": "completed",
                "binding_status": "current",
                "started_at": "2026-10-29T12:00:10Z",
                "completed_at": "2026-10-29T12:00:11Z",
                "report": report,
                "final_approval_granted": False,
                "tax_data_changed": False,
                "external_provider_calls_made": False,
            }
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(api_response(data)))

        return route.fulfill(
            status=404,
            content_type="application/json",
            body=json.dumps({"status": "error", "data": None, "errors": [{"code": "synthetic_unavailable", "message": "Nicht Teil dieser Browserprobe"}], "warnings": []}),
        )

    try:
        with sync_playwright() as playwright:
            launch_options: dict[str, object] = {"headless": True}
            if args.browser_executable:
                launch_options["executable_path"] = str(args.browser_executable)
            browser = playwright.chromium.launch(**launch_options)
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()
            page.route("**/api/v1/**", route_api)
            page.goto(f"{origin}/#tax", wait_until="domcontentloaded")
            button = page.get_by_role("button", name="Prüfstand 2021–2025 erzeugen / erneuern")
            expect(button).to_be_visible(timeout=15000)
            assert not [entry for entry in request_log if entry[0] == "POST"]

            button.click()
            try:
                expect(
                    page.locator("[role=status]").filter(has_text="Prüfstand erstellt")
                ).to_be_visible(timeout=15000)
            except Exception:
                print(json.dumps({
                    "browser_status": page.locator("[role=status]").all_text_contents(),
                    "api_requests": request_log,
                }, ensure_ascii=False))
                raise
            posts = [entry for entry in request_log if entry[0] == "POST"]
            assert len(posts) == 1
            assert posts[0][2] == {
                "scope": "years_2021_2025",
                "expected_input_binding_sha256": INPUT_HASH,
                "expected_latest_tax_run_id": "synthetic-run-2025",
            }
            assert "Keine finale Freigabe" in page.locator("[role=status]").all_text_contents()[-1]

            mode["value"] = "conflict"
            page.reload(wait_until="domcontentloaded")
            conflict_button = page.get_by_role("button", name="Prüfstand 2021–2025 erzeugen / erneuern")
            expect(conflict_button).to_be_visible(timeout=15000)
            conflict_button.click()
            expect(page.get_by_role("alert")).to_contain_text("Eingaben haben sich seit dem gelesenen Prüfstand geändert", timeout=15000)
            assert len([entry for entry in request_log if entry[0] == "POST"]) == 2

            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=3)

    print(json.dumps({"status": "passed", "scenarios": ["page-open-is-read-only", "explicit-refresh", "stale-input-error"], "api_post_count": 2}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
