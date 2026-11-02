"""Browser smoke against the disposable read-only UX sandbox; no real provider requests."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


WARNING = "FX-Tagesreferenz: Originalbeleg und Veröffentlichung nicht geprüft."


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    parsed = urlparse(args.url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        parser.error("Only a local synthetic sandbox is allowed")
    args.output.mkdir(parents=True, exist_ok=True)
    calls = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            scenarios = (("desktop", 1280, False), ("mobile", 390, False),
                         ("desktop-refresh-error", 1280, True), ("mobile-refresh-error", 390, True))
            for name, width, refresh_error in scenarios:
                page = browser.new_page(viewport={"width": width, "height": 844})
                submitted = [False]

                def intercept(route):
                    url = urlparse(route.request.url)
                    if url.hostname not in {"127.0.0.1", "localhost"}:
                        route.abort()
                    elif url.path == "/api/v1/prices/as-of-gate/backfill":
                        assert route.request.method == "POST"
                        assert route.request.post_data_json["dry_run"] is True
                        calls.append(name)
                        submitted[0] = True
                        route.fulfill(status=200, content_type="application/json", body=json.dumps({
                            "status": "warning", "errors": [],
                            "warnings": [{"code": "usd_eur_daily_reference_unverified", "message": WARNING}],
                            "data": {"attempted": 1, "imported_prices": 0, "failed": 0},
                        }))
                    elif refresh_error and submitted[0] and url.path == "/api/v1/prices/as-of-gate":
                        route.fulfill(status=503, content_type="application/json", body='{"detail":"synthetic refresh failure"}')
                    else:
                        route.continue_()

                page.route("**/*", intercept)
                sandbox = page.request.get(args.url.rstrip("/") + "/api/v1/health")
                assert sandbox.headers.get("x-steuerreport-ux-sandbox") == "synthetic-read-only"
                response = page.goto(args.url.rstrip("/") + "/#zugewinn", wait_until="domcontentloaded")
                assert response is not None
                button = page.get_by_role("button", name="Backfill pruefen")
                expect(button).to_be_enabled(timeout=120_000)
                button.click()
                expect(page.get_by_text(WARNING, exact=False)).to_be_visible(timeout=120_000)
                if refresh_error:
                    expect(page.get_by_text("Ergebnis erhalten, aber Aktualisierung fehlgeschlagen", exact=False)).to_be_visible()
                page.screenshot(path=str(args.output / f"as-of-fx-warning-{name}-{width}.png"), full_page=True)
                page.close()
            assert calls == ["desktop", "mobile", "desktop-refresh-error", "mobile-refresh-error"]
        finally:
            browser.close()
    print("synthetic_as_of_fx_warning_browser: desktop/mobile and refresh failure passed")


if __name__ == "__main__":
    main()
