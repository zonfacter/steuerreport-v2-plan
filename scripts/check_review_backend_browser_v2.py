"""F1-F3 against the actual backend and a disposable 45-event synthetic database.

No productive API is used. Browser requests are bridged to FastAPI TestClient;
only the explicit funding step writes to this script's temporary test database.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
from threading import Thread
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

expect.set_options(timeout=15000)


def fingerprint(store):
    with store.connect() as con:
        names = con.execute("select table_name from information_schema.tables where table_schema='main' order by table_name").fetchall()
        values = [(name, con.execute('select * from "' + name + '" order by all').fetchall()) for (name,) in names]
    return hashlib.sha256(json.dumps(values, default=str).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-executable")
    parser.add_argument("--output", type=Path, default=Path("artifacts/ux-review-fixes"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    with ExitStack() as stack:
        state = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="steuerreport-review-browser-")))
        for key in list(os.environ):
            if key.startswith("STEUERREPORT_"):
                del os.environ[key]
        os.environ.update(STEUERREPORT_V2_ROOT=str(root), STEUERREPORT_STATE_DIR=str(state),
                          STEUERREPORT_V2_DB=str(state / "synthetic.duckdb"), STEUERREPORT_PRIVATE_PROFILE="",
                          STEUERREPORT_PRIVATE_CONFIG_DIR=str(state / "configs"), STEUERREPORT_USERTRANSFER_ROOT=str(state / "imports"))
        from fastapi.testclient import TestClient
        from run_ux_sandbox_v2 import create_readonly_preview, seed_synthetic_store
        from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
        from steuerreport_v2.importers.raw_normalizer import RawNormalizer
        from steuerreport_v2.ledger.balance import BalanceLedgerBuilder
        store = seed_synthetic_store(state / "synthetic.duckdb")
        client = stack.enter_context(TestClient(create_readonly_preview(store)))
        tasks = client.post("/api/v1/workspace/review/query", json={}).json()["data"]["items"]
        task = next(item for item in tasks if item["task"]["decision_status"] == "negative_balance")
        assert task["source_ref"] and task["account_ref"] and task["account"] == "synthetic-account"
        before = fingerprint(store)
        originals = [(row.batch_id, row.file_hash) for row in store.list_import_batches()]
        source_ref = task["source_ref"]

        class QuietHandler(SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(root / "frontend/dist")))
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        stack.callback(server.server_close)
        stack.callback(worker.join)
        stack.callback(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        playwright = stack.enter_context(sync_playwright())
        browser = stack.enter_context(playwright.chromium.launch(headless=True, executable_path=args.browser_executable))
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        calls, errors, screenshots = [], [], []
        def bridge(route):
            request = route.request
            parsed = urlparse(request.url)
            path = parsed.path + ("?" + parsed.query if parsed.query else "")
            allowed = request.method == "GET" or (request.method == "POST" and parsed.path in {"/api/v1/activity/query", "/api/v1/workspace/review/query"})
            assert allowed, "Unexpected browser write: " + parsed.path
            calls.append({"method": request.method, "path": parsed.path})
            response = client.request(request.method, path, content=request.post_data, headers={"Content-Type": "application/json"})
            assert response.status_code == 200, (path, response.text[:200])
            route.fulfill(status=response.status_code, content_type="application/json", body=response.content)
        context.route("**/api/**", bridge)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        def go(route, title):
            page.goto(base + "/" + route, wait_until="networkidle")
            expect(page.get_by_role("heading", name=title, exact=True)).to_be_visible()
        def shot(name):
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), name
            expect(page.locator(".wsResource")).to_have_count(0)
            page.screenshot(path=str(args.output / (name + ".png")), full_page=page.get_by_role("dialog").count() == 0, animations="disabled")
            screenshots.append({"file": name + ".png", "viewport": page.viewport_size, "route": page.url.split("#", 1)[-1], "data": "synthetic", "backend": "actual FastAPI"})

        go("#sources", "Quellen & Wallets")
        expect(page.get_by_role("note", name="Synthetische Testumgebung")).to_be_visible()
        expect(page.locator(".wsSourceRow")).to_have_count(1)
        expect(page.locator(".wsSourceRow")).to_contain_text("1 Review-Aufgabe")
        expect(page.locator(".wsSourceRow")).to_contain_text("1 blockierend")
        page.get_by_role("combobox", name="Quellenstatus").select_option("reconciliation")
        expect(page.locator(".wsSourceRow")).to_have_count(1)
        shot("F1-sources-1440")
        page.get_by_role("button", name="synthetic-account", exact=True).click()
        panel = page.get_by_role("dialog")
        panel.get_by_role("tab", name="Hinweise / Abgleich", exact=True).click()
        expect(panel.get_by_text(task["task"]["title"], exact=True)).to_be_visible()
        expect(panel.get_by_role("heading", name="1 Review-Aufgabe", exact=True)).to_be_visible()
        shot("F1-source-issues-1440")
        page.set_viewport_size({"width": 390, "height": 844})
        shot("F1-source-issues-390")
        page.keyboard.press("Escape")
        page.set_viewport_size({"width": 1440, "height": 1000})

        go("#review?category=reconciliation&status=high&size=10", "Hinweise prüfen")
        page.get_by_role("button", name=task["task"]["title"], exact=True).click()
        review_url = page.url
        expect(page.get_by_role("dialog")).to_contain_text("Konto synthetic-account · Asset EUR")
        page.get_by_role("button", name="Bestehenden Prüfablauf öffnen", exact=True).click()
        expect(page.get_by_role("tab", name="Ledger", exact=True)).to_have_attribute("aria-selected", "true")
        expect(page.locator(".wsActivityTable tbody tr")).to_have_count(22)
        assert "account=" + task["account_ref"] in page.url and "asset=EUR" in page.url
        assert "synthetic-account" not in page.url
        expect(page.locator(".wsActivityTable tbody")).to_contain_text("synthetic-account")
        assert "gespeichertes Vorzeichen" not in page.locator(".wsActivityTable").inner_text()
        shot("F2-context-ledger-1440")
        page.set_viewport_size({"width": 390, "height": 844})
        shot("F2-context-ledger-390")
        page.get_by_role("button", name="Zur Review-Aufgabe zurück", exact=True).click()
        expect(page.get_by_role("dialog")).to_be_visible()
        assert page.url == review_url
        page.get_by_role("button", name="Betroffene Quelle öffnen", exact=True).click()
        expect(page.get_by_role("dialog").get_by_role("tab", name="Hinweise / Abgleich", exact=True)).to_have_attribute("aria-selected", "true")
        page.get_by_role("dialog").get_by_role("button", name="EUR Ledger prüfen", exact=True).click()
        expect(page.get_by_role("tab", name="Ledger", exact=True)).to_have_attribute("aria-selected", "true")
        page.get_by_role("button", name="Zur Review-Aufgabe zurück", exact=True).click()
        expect(page.get_by_role("dialog")).to_be_visible()
        assert page.url == review_url
        page.keyboard.press("Escape")

        page.set_viewport_size({"width": 1440, "height": 1000})
        go("#dashboard", "Übersicht")
        eur = page.locator("table tbody tr").filter(has=page.get_by_role("button", name="EUR", exact=True))
        expect(eur.get_by_text("EUR-Referenzwert", exact=True)).to_be_visible()
        assert "1970" not in eur.inner_text() and "fiat:EUR" not in eur.inner_text()
        expect(page.locator("table tbody tr").filter(has=page.get_by_role("button", name="SOL", exact=True)).get_by_text("Bewertungsquelle in Details", exact=True)).to_be_visible()
        shot("F3-dashboard-1440")
        page.set_viewport_size({"width": 390, "height": 844})
        shot("F3-dashboard-390")
        assert fingerprint(store) == before, "Browser reads changed the test database"

        go("#sources?status=reconciliation", "Quellen & Wallets")
        expect(page.locator(".wsSourceRow")).to_have_count(1)

        # Actual correction in disposable data, never a decision acceptance or live call.
        funding = CsvRawImporter(store).import_text(source="manual-csv", filename="synthetic-funding.csv", content="time,asset,amount,type,account\n2024-12-31T10:00:00Z,EUR,1000,deposit,synthetic-account\n")
        RawNormalizer(store).normalize_batch(funding.batch_id)
        BalanceLedgerBuilder(store).rebuild()
        after_correction = fingerprint(store)
        assert all(store.get_import_batch(batch_id).file_hash == digest for batch_id, digest in originals)
        assert store.list_review_decisions() == []
        page.set_viewport_size({"width": 1440, "height": 1000})
        page.get_by_role("button", name="Ansicht aktualisieren", exact=True).click()
        expect(page.get_by_text("Keine passenden Quellen", exact=True)).to_be_visible()
        page.get_by_role("button", name="Filter zurücksetzen", exact=True).click()
        expect(page.locator(".wsSourceRow")).to_contain_text("0 Review-Aufgaben")
        page.get_by_role("button", name="synthetic-account", exact=True).click()
        panel = page.get_by_role("dialog")
        panel.get_by_role("tab", name="Hinweise / Abgleich", exact=True).click()
        expect(panel.get_by_role("heading", name="0 Review-Aufgaben", exact=True)).to_be_visible()
        expect(panel.get_by_text(task["task"]["title"], exact=True)).to_have_count(0)
        shot("F1-after-funding-1440")
        page.keyboard.press("Escape")
        go("#review", "Hinweise prüfen")
        expect(page.locator(".wsResource")).to_have_count(0)
        expect(page.get_by_text(task["task"]["title"], exact=True)).to_have_count(0)
        assert fingerprint(store) == after_correction
        assert client.post("/api/v1/pipeline/rebuild").status_code == 403
        assert not errors, errors
        result = {"F1": "bestanden", "F2": "bestanden", "F3": "bestanden", "browser_api_calls_readonly": calls,
                  "browser_reads_preserve_database": True, "actual_backend": True, "actual_disposable_funding_import": True,
                  "review_decisions_written": 0, "original_hashes_preserved": True, "source_ref": source_ref,
                  "javascript_errors": errors, "screenshots": screenshots, "financial_release": False}
        (args.output / "review-verification.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({key: value for key, value in result.items() if key not in {"browser_api_calls_readonly", "screenshots"}}, ensure_ascii=False), flush=True)
        context.unroute_all(behavior="ignoreErrors")
        context.close()


if __name__ == "__main__":
    main()
