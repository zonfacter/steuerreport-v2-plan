"""Synthetic browser proof for the manual, exact-target correction workflow."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from threading import Thread
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright

from ux_workspace_fixtures import WorkspaceFixture


ROOT = Path(__file__).resolve().parents[1]
TARGET = "evt-000"
TASK = "review-demo"
SOURCE = "s_" + "a" * 20
ACCOUNT = "a_" + "b" * 20
OLD_ID = "fixture-change-old"
NEW_ID = "fixture-change-new"
OLD_REVISION = "a" * 64
CURRENT_REVISION = "b" * 64


def envelope(route, data, status=200, detail=None):
    body = {"status": "ok" if status == 200 else "error", "data": data, "errors": [], "warnings": []}
    if detail:
        body["detail"] = detail
    route.fulfill(status=status, content_type="application/json", body=json.dumps(body))


def main(browser_executable: str | None = None) -> None:
    dist = ROOT / "frontend/dist"
    if not (dist / "index.html").is_file():
        raise SystemExit("Frontend fehlt. Erst frontend: npm ci --ignore-scripts && npm run build ausfuehren.")

    workspace = WorkspaceFixture()
    fixture_event = {**workspace.events[0], "source_ref": SOURCE, "account": "synthetic-account"}
    old_row = {"kind": "event", "target_id": TARGET, "revision": OLD_REVISION,
               "values": {**fixture_event, "quantity": "1", "quote_quantity": "150", "event_type": "trade"},
               "provenance": {"source": "synthetic", "filename": "synthetic.csv", "row_number": 2,
                              "file_sha256": "c" * 64, "raw_payload_sha256": "d" * 64}}
    current_row = {"kind": "event", "target_id": TARGET, "revision": CURRENT_REVISION,
                   "values": {**fixture_event, "quantity": "1", "quote_quantity": "175", "event_type": "reward"},
                   "provenance": old_row["provenance"]}
    old_set = None
    child_set = None
    target_reads = 0
    rebase_body = None
    api_calls: list[tuple[str, str, object]] = []
    external_requests: list[str] = []
    page_errors: list[str] = []

    def target_context(route):
        nonlocal target_reads
        body = route.request.post_data_json
        requested = body.get("targets", [])
        assert requested == [{"kind": "event", "target_id": TARGET}], requested
        target_reads += 1
        row = old_row if target_reads == 1 else current_row
        envelope(route, {"context_sha256": "e" * 64, "rows": [row], "missing_targets": []})

    def route_all(route):
        nonlocal old_set, child_set, rebase_body
        parsed = urlparse(route.request.url)
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            external_requests.append(route.request.url)
            route.abort()
            return
        if not parsed.path.startswith("/api/"):
            route.continue_()
            return
        method = route.request.method
        body = route.request.post_data_json if method == "POST" and route.request.post_data else {}
        api_calls.append((method, parsed.path, body))
        if workspace.handle(route):
            return
        if parsed.path == "/api/v1/ai/changes" and method == "GET":
            envelope(route, [item for item in (child_set, old_set) if item])
        elif parsed.path == "/api/v1/ai/changes" and method == "POST":
            draft = body
            old_set = {"change_set_id": OLD_ID, "status": "proposed", "draft": draft,
                       "before": [old_row], "origin": "manual", "model": None,
                       "created_at": "2026-10-29T10:00:00Z", "preview": None,
                       "approval": None, "parent_id": None, "generation": None}
            envelope(route, old_set)
        elif parsed.path == "/api/v1/ai/data-context/targets":
            target_context(route)
        elif parsed.path == f"/api/v1/ai/changes/{OLD_ID}/preview":
            envelope(route, {}, 409, "ai_change_stale")
        elif parsed.path == f"/api/v1/ai/changes/{OLD_ID}/rebase":
            rebase_body = body
            assert body.get("reviewed") is True
            assert body.get("targets") == [{"kind": "event", "target_id": TARGET, "current_sha256": CURRENT_REVISION}]
            revised_draft = json.loads(json.dumps(old_set["draft"]))
            revised_draft["changes"][0]["before_sha256"] = CURRENT_REVISION
            child_set = {"change_set_id": NEW_ID, "status": "proposed", "draft": revised_draft,
                         "before": [current_row], "origin": "human_rebase", "model": None,
                         "created_at": "2026-10-29T10:01:00Z", "preview": None,
                         "approval": None, "parent_id": OLD_ID, "generation": None}
            envelope(route, child_set)
        elif parsed.path == f"/api/v1/ai/changes/{OLD_ID}":
            envelope(route, old_set)
        elif parsed.path == f"/api/v1/ai/changes/{NEW_ID}":
            envelope(route, child_set)
        else:
            envelope(route, {})

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *_args):
            pass

    with ExitStack() as stack:
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(dist)))
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        stack.callback(server.server_close)
        stack.callback(worker.join)
        stack.callback(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        playwright = stack.enter_context(sync_playwright())
        browser = playwright.chromium.launch(headless=True, executable_path=browser_executable)
        stack.callback(browser.close)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        stack.callback(context.close)
        context.route("**/*", route_all)
        page = context.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))

        page.goto(f"{base}/#review?year=2025&detail={TASK}", wait_until="networkidle")
        review_panel = page.get_by_role("dialog")
        expect(review_panel.get_by_role("heading", name="Originalbeleg prüfen", exact=True)).to_be_visible()
        review_panel.get_by_role("button", name="Manuelle Korrektur vorbereiten", exact=True).click()
        expect(page).to_have_url(re.compile(r".*/#ai\?.*"))
        assert "year=2025" in page.url and "task=" + TASK in page.url
        assert "source=" + SOURCE in page.url and "account=" + ACCOUNT in page.url
        assert "evidence_id=raw-000" in page.url
        expect(page.get_by_text(TARGET, exact=True)).to_be_visible()
        expect(page.get_by_text("Review-Aufgabe", exact=True)).to_be_visible()
        expect(page.get_by_text("raw-000", exact=True)).to_have_count(2)
        expect(page.get_by_text("Manueller Modus: Keine Modellanfrage", exact=False)).to_be_visible()
        expect(page.get_by_role("button", name="Manuell vorbereiten", exact=True)).to_be_enabled()

        page.get_by_role("button", name="Manuell vorbereiten", exact=True).click()
        patch_value = page.get_by_role("textbox", name="Position 1 event_type")
        patch_value.fill("mining")
        page.get_by_role("textbox", name="Position 1 Begruendung").fill("Der synthetische Beleg weist den Mining-Zugang aus.")
        page.get_by_role("textbox", name="Position 1 Belegstelle").fill("raw:raw-000")
        page.get_by_role("button", name="Neue Vorschlagsrevision speichern", exact=True).click()
        expect(page.get_by_text(OLD_ID, exact=False)).to_be_visible()
        page.get_by_role("button", name="Vorschau berechnen", exact=True).click()
        expect(page.get_by_role("heading", name="Veralteter Korrekturstand", exact=True)).to_be_visible()
        expect(page.get_by_text("trade", exact=True)).to_be_visible()
        expect(page.get_by_text("reward", exact=True)).to_be_visible()
        expect(page.get_by_text("mining", exact=True)).to_be_visible()
        rebase_button = page.get_by_role("button", name="Neue verknüpfte Entwurfsrevision anlegen", exact=True)
        expect(rebase_button).to_be_disabled()
        page.get_by_role("checkbox", name="Ich habe alten Wert, aktuellen Wert, Vorschlag und Belegbezug für jedes Ziel geprüft.").check()
        rebase_button.click()
        expect(page.get_by_text(NEW_ID, exact=False)).to_be_visible()
        expect(page.get_by_text("Vorschau, Belegprüfung und menschliche Freigabe sind erneut erforderlich.", exact=False)).to_be_visible()
        assert old_set["draft"]["changes"][0]["before_sha256"] == OLD_REVISION
        assert old_set["preview"] is None and old_set["approval"] is None
        assert child_set["parent_id"] == OLD_ID and child_set["draft"]["changes"][0]["before_sha256"] == CURRENT_REVISION
        assert child_set["preview"] is None and child_set["approval"] is None
        assert rebase_body and rebase_body["reviewed"] is True
        page.get_by_role("button", name="Zur Review-Aufgabe zurück", exact=True).click()
        expect(page).to_have_url(re.compile(r".*/#review\?.*"))
        expect(page.get_by_role("dialog").get_by_role("heading", name="Originalbeleg prüfen", exact=True)).to_be_visible()

        page.goto(f"{base}/#flows?tab=transactions&detail={TARGET}&year=2025&source={SOURCE}&account={ACCOUNT}&task={TASK}", wait_until="networkidle")
        expect(page.get_by_role("heading", name="Transaktionsdetails", exact=True)).to_be_visible()
        page.get_by_role("button", name="Manuelle Korrektur vorbereiten", exact=True).click()
        expect(page).to_have_url(re.compile(r".*/#ai\?.*"))
        expect(page.get_by_text(TARGET, exact=True)).to_be_visible()
        expect(page.get_by_text("raw-000", exact=True)).to_have_count(2)
        assert "target=evt-000" in page.url and "task=review-demo" in page.url
        assert "source=" + SOURCE in page.url and "account=" + ACCOUNT in page.url and "evidence_id=raw-000" in page.url
        page.get_by_role("button", name="Zum Ereignis zurück", exact=True).click()
        expect(page).to_have_url(re.compile(r".*/#flows\?.*"))
        expect(page.get_by_role("heading", name="Transaktionsdetails", exact=True)).to_be_visible()

        forbidden = [(method, path) for method, path, _body in api_calls if path in {
            "/api/v1/ai/provider", "/api/v1/ai/agents", "/api/v1/ai/provider/models",
            "/api/v1/ai/provider/test", "/api/v1/ai/changes/generate"
        } or path.endswith("/execute") or path.startswith("/api/v1/ai/agents/")]
        task_writes = [(method, path) for method, path, _body in api_calls
                       if path.startswith("/api/v1/ai/tasks") and method != "GET"]
        assert not forbidden, f"Manueller Modus hat Provider-, Agenten- oder Modellrouten aufgerufen: {forbidden}"
        assert not task_writes, f"Manueller Modus hat KI-Aufgaben geschrieben oder ausgefuehrt: {task_writes}"
        assert not external_requests, f"Unerwartete externe Requests: {external_requests}"
        assert not page_errors, f"Browserfehler: {page_errors}"
    print("issue17_browser=passed; synthetic=only; provider/agent/model/generation-calls=0; task-writes=0; external-requests=0")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-executable", help="Optional path to an existing Chromium executable.")
    main(parser.parse_args().browser_executable)
