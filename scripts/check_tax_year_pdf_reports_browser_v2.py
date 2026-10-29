#!/usr/bin/env python3
"""Synthetic browser proof for archived per-year PDF previews."""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

from ux_workspace_fixtures import WorkspaceFixture


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "frontend/dist"
ARTIFACT_ID = "pdf-preview-synthetic-001"


def envelope(data: object) -> dict[str, object]:
    return {"status": "ok", "data": data, "errors": [], "warnings": []}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--browser-executable", type=Path)
    args = parser.parse_args()
    if not (DIST / "index.html").is_file():
        raise SystemExit("Frontend-Build fehlt; zuerst frontend npm run build ausfuehren.")

    fixture = WorkspaceFixture()
    artifact = {
        "manifest_endpoint": f"/api/v1/tax-years/2025/reports/pdf/{ARTIFACT_ID}/manifest.json",
        "manifest": {
            "artifact_id": ARTIFACT_ID,
            "year": 2025,
            "created_at": "2026-10-29T12:00:00Z",
            "report_status": "preview",
            "final_filing_allowed": False,
            "calculation_run_id": "run-synthetic-2025",
            "input_binding_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
            "summary": {
                "taxable_private_disposals_eur": "10.12",
                "taxable_disposal_proceeds_eur": "100.00",
                "acquisition_cost_eur": "89.88",
                "rewards_mining_staking_income_eur": "2.34",
                "derivative_pnl_eur": "0.00",
                "tax_free_private_disposals_eur": "0.00",
                "tax_free_lines_count": 0,
            },
            "tax_line_count": 2,
            "reward_asset_row_count": 1,
            "reward_missing_value_count": 0,
            "derivative_line_count": 0,
            "derivative_missing_price_count": 0,
            "unmatched_disposals": 0,
            "missing_price_groups": 0,
            "technical_status": {"status": "technical_only", "technical_export_allowed": True},
            "files": [{
                "file_index": 1,
                "filename": "steuerjahr-2025-vorschau-1.pdf",
                "page_count": 2,
                "size_bytes": 2048,
                "sha256": "c" * 64,
                "download_endpoint": f"/api/v1/tax-years/2025/reports/pdf/{ARTIFACT_ID}/files/1",
            }],
        },
    }
    artifacts: list[dict[str, object]] = []
    requests: list[tuple[str, str]] = []
    external: list[str] = []
    errors: list[str] = []

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(DIST)))
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    origin = f"http://127.0.0.1:{server.server_port}"

    def route_api(route) -> None:
        request = route.request
        parts = urlsplit(request.url)
        if parts.hostname not in {"127.0.0.1", "localhost"}:
            external.append(request.url)
            route.abort()
            return
        if not parts.path.startswith("/api/"):
            route.continue_()
            return
        requests.append((request.method, parts.path))
        if parts.path == "/api/v1/export/readiness":
            data = {"technical_export_allowed": True, "final_filing_allowed": False, "filing_status": "technical_only"}
            return route.fulfill(content_type="application/json", body=json.dumps(envelope(data)))
        if parts.path == "/api/v1/tax-years/2025/reports/pdf" and request.method == "GET":
            data = {"year": 2025, "generated_at": "2026-10-29T12:00:00Z", "artifacts": artifacts}
            return route.fulfill(content_type="application/json", body=json.dumps(envelope(data)))
        if parts.path == "/api/v1/tax-years/2025/reports/pdf" and request.method == "POST":
            artifacts.insert(0, artifact)
            return route.fulfill(content_type="application/json", body=json.dumps(envelope(artifact)))
        if parts.path == artifact["manifest_endpoint"]:
            return route.fulfill(content_type="application/json", body=json.dumps(artifact["manifest"]))
        if parts.path == artifact["manifest"]["files"][0]["download_endpoint"]:
            return route.fulfill(status=200, content_type="application/pdf", body=b"%PDF-1.4\nsynthetic preview\n%%EOF")
        if fixture.handle(route):
            return
        route.fulfill(content_type="application/json", body=json.dumps(envelope({})))

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, executable_path=args.browser_executable)
            try:
                context = browser.new_context(viewport={"width": 1280, "height": 900}, accept_downloads=True)
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.route("**/*", route_api)
                page.goto(f"{origin}/#export?year=2025", wait_until="networkidle")
                expect(page.get_by_role("heading", name="Vorschau · keine finale Jahresfreigabe · 2025")).to_be_visible()
                expect(page.get_by_text("Jahres-PDF-Vorschau erzeugen", exact=True)).to_be_enabled()
                expect(page.get_by_text("Für 2025 sind noch keine Jahres-PDFs archiviert.")).to_be_visible()
                page.get_by_role("button", name="Jahres-PDF-Vorschau erzeugen").click()
                expect(page.get_by_role("status").filter(has_text="nicht final")).to_be_visible()
                expect(page.get_by_text("Private Veräußerungen, Gewinn/Verlust: 10,12 EUR", exact=False)).to_be_visible()
                expect(page.get_by_text("Veräußerungserlöse (kein EUR-Auszahlungsbetrag): 100,00 EUR", exact=False)).to_be_visible()
                expect(page.get_by_text("Technischer Export möglich; keine Abgabefreigabe", exact=True)).to_be_visible()
                expect(page.get_by_text("Lauf run-synthetic-2025", exact=True)).to_be_visible()
                with page.expect_download() as pdf_download:
                    page.get_by_role("link", name="PDF 1 · 2 Seiten · 2 KB").click()
                assert pdf_download.value.suggested_filename == "steuerjahr-2025-vorschau-1.pdf"
                with page.expect_download() as manifest_download:
                    page.get_by_role("link", name="Manifest JSON").click()
                assert manifest_download.value.suggested_filename.endswith("manifest.json")
                assert sum(method == "POST" and path.endswith("/reports/pdf") for method, path in requests) == 1
                assert not external, external
                assert not errors, errors
                desktop = Path("/tmp/steuerreport-issue-integration-pdf-preview.png")
                page.screenshot(path=str(desktop), full_page=True)
                page.set_viewport_size({"width": 390, "height": 844})
                expect(page.get_by_role("button", name="Jahres-PDF-Vorschau erzeugen")).to_be_visible()
                dimensions = page.evaluate("({inner: innerWidth, scroll: document.documentElement.scrollWidth})")
                assert dimensions["scroll"] <= dimensions["inner"], dimensions
                mobile = Path("/tmp/steuerreport-issue-integration-pdf-preview-mobile.png")
                page.screenshot(path=str(mobile), full_page=True)
                print(json.dumps({"result": "passed", "route": "#export?year=2025", "desktop": "1280x900", "mobile": {"viewport": "390x844", **dimensions}, "pdf_posts": 1, "external_requests": 0, "screenshots": [str(desktop), str(mobile)]}))
                context.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
