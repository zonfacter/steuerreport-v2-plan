"""Echter Historien-Importpfad im Browser mit wegwerfbaren synthetischen Wallets.

Vorher frontend bauen. Beispiel aus dem Projektverzeichnis:
PYTHONPATH=src:/tmp/steuerreport-browser-tools:/tmp/steuerreport-connector-tools-20261026 \
PYTHONPYCACHEPREFIX=/tmp/steuerreport-limits-pycache \
python3 scripts/check_history_backend_browser_v2.py --browser-executable \
  /root/.cache/ms-playwright/chromium-1187/chrome-linux/chrome
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
import os
from pathlib import Path
import socket
import tempfile
from threading import Thread, enumerate as threads
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from uuid import UUID


WIDTHS = (390, 768, 1280, 1440)
LABEL_A, LABEL_B = "Browser Historie Wallet A", "Browser Historie Wallet B"
ACTOR = "Synthetische Browserpruefung"


def base58(content):
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    number, result = int.from_bytes(content, "big"), ""
    while number:
        number, remainder = divmod(number, 58)
        result = alphabet[remainder] + result
    return "1" * (len(content) - len(content.lstrip(b"\0"))) + result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-executable")
    parser.add_argument("--output", type=Path, default=Path("artifacts/source-history-backend-browser"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    assert (root / "frontend/dist/index.html").is_file(), "Frontend zuerst bauen"
    result = {
        "passed": False, "synthetic_only": True, "actual_fastapi_bridge": True,
        "mocked_boundary": "HistoryService._collector", "viewports": list(WIDTHS),
        "calls": [], "collector_calls": [], "javascript_errors": [], "bridge_errors": [],
        "external_requests": [], "screenshots": [], "cleanup": {},
    }
    state = None
    try:
        with ExitStack() as stack:
            state = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="steuerreport-history-browser-")))
            retained = {name: value for name, value in os.environ.items() if name in {
                "PATH", "HOME", "LANG", "PYTHONPATH", "PYTHONPYCACHEPREFIX", "LD_LIBRARY_PATH",
            }}
            stack.enter_context(patch.dict(os.environ, retained, clear=True))
            os.environ.update(
                STEUERREPORT_V2_ROOT=str(root), STEUERREPORT_STATE_DIR=str(state),
                STEUERREPORT_PRIVATE_PROFILE=str(state / "profile.json"),
                STEUERREPORT_V2_DB=str(state / "synthetic.duckdb"),
                STEUERREPORT_PRIVATE_CONFIG_DIR=str(state / "configs"),
                STEUERREPORT_USERTRANSFER_ROOT=str(state / "imports"),
            )
            (state / "profile.json").write_text("{}\n", encoding="utf-8")
            original_connect = socket.socket.connect
            original_connect_ex = socket.socket.connect_ex

            def local_only(sock, address):
                if sock.family in {socket.AF_INET, socket.AF_INET6}:
                    try:
                        allowed = ipaddress.ip_address(address[0]).is_loopback
                    except ValueError:
                        allowed = address[0] == "localhost"
                    if not allowed:
                        result["external_requests"].append({"transport": "python_socket", "host": str(address[0])})
                        raise AssertionError("Externe Sockets sind gesperrt")

            def connect(sock, address):
                local_only(sock, address)
                return original_connect(sock, address)

            def connect_ex(sock, address):
                local_only(sock, address)
                return original_connect_ex(sock, address)

            stack.enter_context(patch.object(socket.socket, "connect", connect))
            stack.enter_context(patch.object(socket.socket, "connect_ex", connect_ex))

            # Keine Anwendungsimporte vor privater Umgebungs- und Netzinitialisierung.
            from fastapi.testclient import TestClient
            from nacl.signing import SigningKey
            from playwright.sync_api import expect, sync_playwright
            from steuerreport_v2.container_entrypoint import initialize_state

            initialize_state()
            from steuerreport_v2.api.app import create_app
            from steuerreport_v2.contracts.connectors import PublicWalletAddressRequest
            from steuerreport_v2.db.duckdb_store import DuckDbStore
            from steuerreport_v2.domain.connectors import ConnectorService
            from steuerreport_v2.domain.history import HistoryService
            from steuerreport_v2.domain.history_types import HistoryPage, HistoryRecord
            from steuerreport_v2.domain.portfolio import PortfolioService
            from steuerreport_v2.domain.workspace import source_ref

            expect.set_options(timeout=60000)
            store = DuckDbStore(state / "synthetic.duckdb")
            wallets = [base58(SigningKey.generate().verify_key.encode()) for _ in range(2)]
            wallet_a, wallet_b = wallets
            assert wallet_a != wallet_b
            ref_a, ref_b = [source_ref("wallet:" + wallet) for wallet in wallets]
            connectors = ConnectorService(store)
            for wallet, label in zip(wallets, (LABEL_A, LABEL_B)):
                connectors.save_public_wallet(PublicWalletAddressRequest(wallet_address=wallet, display_label=label))
            connections_before = [row.model_dump(mode="json") for row in connectors.connections()]
            signature = base58(os.urandom(64))
            tx = {
                "blockTime": 1735732800, "slot": 1,
                "transaction": {"signatures": [signature], "message": {"accountKeys": [
                    {"pubkey": wallet_a}, {"pubkey": base58(os.urandom(32))},
                ]}},
                "meta": {
                    "err": None, "fee": 5000,
                    "preBalances": [2_000_000_000, 2_000_000_000],
                    "postBalances": [2_999_995_000, 1_000_000_000],
                    "preTokenBalances": [], "postTokenBalances": [],
                },
            }
            rows = PortfolioService(store)._solana_transaction_rows(wallet_a, signature, tx)
            assert len(rows) == 2 and {row["event_type"] for row in rows} == {"sol_transfer", "network_fee"}
            record = HistoryRecord(
                "solana:" + signature, "solana_rpc", rows,
                {"transaction": tx, "wallet_address": wallet_a, "source_ref": ref_a,
                 "scan_address": wallet_a, "signature_info": {"signature": signature, "err": None}},
            )

            class FixtureCollector:
                def fetch_page(self, cursor, check):
                    check()
                    assert cursor == {}, "Nur ein synthetischer Seitenabruf erwartet"
                    result["collector_calls"].append({"source_ref": ref_a, "wallet_address": wallet_a, "cursor": deepcopy(cursor)})
                    return HistoryPage(
                        [deepcopy(record)], {"synthetic_page": 1}, True, requests=1,
                        notes=("Synthetische Browserpruefung; keine vollstaendige historische Abdeckung bewiesen.",),
                        complete_history_proven=False,
                        extra={"progress": {"phase": "fetch", "references_discovered": 1,
                                            "signatures_discovered": 1, "signatures_total": 1,
                                            "signatures_completed": 1, "addresses_completed": 1,
                                            "addresses_total": 1, "inventory_complete": True}},
                    )

            def fixture_collector(service, target, options):
                assert service.store.path == store.path
                assert target.source_ref == ref_a and target.wallet_address == target.account == wallet_a
                assert target.provider == "solana" and not options.symbols and options.public_rpc_only
                assert options.rpc_provider == "public" and UUID(options.inventory_job_id).version == 4
                assert options.start <= datetime.fromtimestamp(tx["blockTime"], timezone.utc) <= options.end
                return FixtureCollector()

            stack.enter_context(patch.object(HistoryService, "_collector", fixture_collector))
            client = stack.enter_context(TestClient(create_app(store)))

            def stop_history_workers():
                service = HistoryService(store)
                for job in service.storage.jobs():
                    if job["status"] in {"queued", "running"}:
                        service.control(job["source_ref"], job["id"], "cancel")
                pending = [thread for thread in threads() if thread.name.startswith("source-history-")]
                for thread in pending:
                    thread.join(timeout=30)
                result["cleanup"]["history_workers_stopped"] = not any(thread.is_alive() for thread in pending)
                assert result["cleanup"]["history_workers_stopped"], "Historienworker nicht beendet"

            stack.callback(stop_history_workers)

            def api(path, payload=None):
                response = client.get(path) if payload is None else client.post(path, json=payload)
                assert response.status_code == 200, (path, response.status_code, response.text)
                body = response.json()
                assert body["status"] == "ok", body
                return body["data"]

            def financial_counts():
                with store.connect() as con:
                    return {table: con.execute(f"select count(*) from {table}").fetchone()[0] for table in (
                        "raw_import_batches", "raw_objects", "canonical_events", "balance_ledger", "tax_lines", "review_decisions",
                    )}

            initial_counts = financial_counts()
            assert all(value == 0 for value in initial_counts.values()), initial_counts
            assert api(f"/api/v1/workspace/sources/{ref_b}/history")["jobs"] == []
            capability = api(f"/api/v1/workspace/sources/{ref_a}/history")["capability"]
            free = next(option for option in capability["rpc_options"] if option["id"] == "public")
            assert free["ready"] and free["configured"] and free["pinned"] and not free["tariff_verified"]
            assert free["kind"] == "public" and free["provider_id"] == "solana_rpc"

            class QuietHandler(SimpleHTTPRequestHandler):
                def log_message(self, *args):
                    pass

            server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(root / "frontend/dist")))
            worker = Thread(target=server.serve_forever, daemon=True, name="history-browser-static")

            def stop_server():
                server.shutdown()
                server.server_close()
                worker.join(timeout=10)
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                    probe.settimeout(1)
                    released = probe.connect_ex(("127.0.0.1", server.server_port)) != 0
                result["cleanup"].update(server_stopped=not worker.is_alive(), server_socket_closed=server.socket.fileno() == -1,
                                         server_port_released=released)
                assert all(result["cleanup"][key] for key in ("server_stopped", "server_socket_closed", "server_port_released"))

            worker.start()
            stack.callback(stop_server)
            base = f"http://127.0.0.1:{server.server_port}"
            origin = urlparse(base).netloc
            playwright = stack.enter_context(sync_playwright())
            browser = stack.enter_context(playwright.chromium.launch(headless=True, executable_path=args.browser_executable))
            context = stack.enter_context(browser.new_context(viewport={"width": 1440, "height": 1000}, service_workers="block"))
            job_ids = []
            history_base = f"/api/v1/workspace/sources/{ref_a}/history"

            def bridge(route):
                request = route.request
                parsed = urlparse(request.url)
                if parsed.netloc != origin or parsed.scheme != "http":
                    result["external_requests"].append({"transport": "browser", "host": parsed.hostname})
                    route.abort()
                    return
                if not parsed.path.startswith("/api/"):
                    route.continue_()
                    return
                try:
                    allowed_post = parsed.path in {"/api/v1/activity/query", "/api/v1/workspace/review/query", history_base + "/jobs"}
                    allowed_post = allowed_post or any(parsed.path == history_base + "/jobs/" + job_id + "/import" for job_id in job_ids)
                    assert request.method == "GET" or request.method == "POST" and allowed_post, (request.method, parsed.path)
                    if request.method == "POST" and parsed.path == history_base + "/jobs":
                        body = request.post_data_json
                        assert set(body) == {"request_id", "confirm_external_request", "start", "end", "symbols",
                                             "public_rpc_only", "rpc_provider", "max_records"}
                        assert UUID(body["request_id"]).version == 4 and body["confirm_external_request"] is True
                        assert body["rpc_provider"] == "public" and body["public_rpc_only"] is True
                        assert body["symbols"] == [] and body["max_records"] == 100000
                        assert body["start"] == "2025-01-01" and body["end"] == "2025-01-02"
                    response = client.request(request.method, parsed.path + ("?" + parsed.query if parsed.query else ""),
                                              content=request.post_data, headers={"Content-Type": "application/json"})
                    result["calls"].append({"method": request.method, "path": parsed.path, "http": response.status_code,
                                            **({"payload": request.post_data_json} if request.method == "POST" else {})})
                    if response.status_code >= 400:
                        result["bridge_errors"].append(f"{parsed.path}: HTTP {response.status_code}: {response.text}")
                    if request.method == "POST" and parsed.path == history_base + "/jobs" and response.status_code == 202:
                        data = response.json()["data"]
                        assert data["source_ref"] == ref_a
                        job_ids.append(data["id"])
                    route.fulfill(status=response.status_code, content_type="application/json", body=response.content)
                except Exception as exc:
                    result["bridge_errors"].append(f"{type(exc).__name__}: {exc}")
                    route.fulfill(status=500, content_type="application/json", body='{"status":"error","errors":[]}')

            context.route("**/*", bridge)
            page = context.new_page()
            page.set_default_timeout(60000)
            page.on("pageerror", lambda error: result["javascript_errors"].append(str(error)))

            def screenshots(phase, anchor):
                for width in WIDTHS:
                    page.set_viewport_size({"width": width, "height": 1000})
                    page.wait_for_function("innerWidth > 820 || getComputedStyle(document.querySelector('.sidebar')).visibility === 'hidden'")
                    anchor.scroll_into_view_if_needed()
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (phase, width)
                    panel = page.get_by_role("dialog").bounding_box()
                    assert panel and panel["x"] >= -1 and panel["x"] + panel["width"] <= width + 1, (phase, width, panel)
                    name = f"synthetic-history-{phase}-{width}.png"
                    page.screenshot(path=str(args.output / name), animations="disabled")
                    result["screenshots"].append(name)

            def assert_counts(area, values):
                for label, value in values.items():
                    counter = area.locator(".hiCounts > div").filter(has=page.get_by_text(label, exact=True))
                    expect(counter.locator("dd")).to_have_text(str(value))

            try:
                page.goto(base + "/#sources")
                row_a = page.locator(".wsSourceRow").filter(has=page.get_by_role("button", name=LABEL_A, exact=True))
                expect(row_a).to_be_visible()
                row_a.get_by_role("button", name="Transaktionen abrufen", exact=True).click()
                panel = page.get_by_role("dialog", name=LABEL_A, exact=True)
                expect(panel).to_be_visible()
                result["phase"] = "selected_source"
                screenshots("selected-source", panel.get_by_role("heading").first)
                expect(panel.get_by_role("tab", name="Automatischer Import", exact=True)).to_have_attribute(
                    "aria-selected", "true", timeout=5000,
                )
                area = panel.get_by_role("region", name="Automatischer Import: " + LABEL_A, exact=True)
                expect(area.locator(".hiContext code")).to_have_text(ref_a)
                expect(area.get_by_label("Handelspaare (kommagetrennt)")).to_have_count(0)
                area.get_by_label("Von", exact=True).fill("2025-01-01")
                area.get_by_label("Bis", exact=True).fill("2025-01-02")
                free_radio = area.get_by_role("radio", name="\u00d6ffentlicher RPC (Free)", exact=True)
                expect(free_radio).not_to_be_checked()
                expect(area.get_by_role("radio", name="Eigener Anbieter (Free/Premium)", exact=True)).not_to_be_checked()
                start = area.get_by_role("button", name="Vorschau abrufen", exact=True)
                expect(start).to_be_disabled()
                assert not result["collector_calls"] and not job_ids
                before_calls = len(result["calls"])
                free_radio.check()
                page.evaluate("async () => { await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))); }")
                expect(free_radio).to_be_checked()
                expect(start).to_be_disabled()
                assert len(result["calls"]) == before_calls, "Die Free-Wahl darf keinen Request ausloesen"
                assert not result["collector_calls"] and not job_ids
                area.get_by_label(f"Ich best\u00e4tige den externen Anbieterabruf f\u00fcr {LABEL_A} im gew\u00e4hlten Zeitraum.", exact=True).check()
                start.click()
                job_area = area.get_by_role("region", name="Ausgew\u00e4hlter Historienauftrag", exact=True)
                expect(job_area.get_by_role("status").first).to_contain_text("Vorschau bereit")
                assert len(job_ids) == 1
                job_id = job_ids[0]
                ready = api(history_base + "/jobs/" + job_id)
                assert ready["status"] == "ready" and ready["source_ref"] == ref_a and ready["imported_events"] == 0, ready
                assert ready["new_records"] == 1 and len(ready["sample_rows"]) == 2 and not ready["complete_history_proven"]
                assert ready["transport"]["id"] == "public" and ready["transport"]["pinned"] is True
                assert ready["progress"]["inventory_complete"] is True
                assert ready["progress"]["signatures_total"] == ready["progress"]["signatures_completed"] == 1
                expect(job_area.locator(".hiTransport")).to_contain_text(ready["transport"]["label"])
                assert financial_counts() == initial_counts, "Vorschau hat produktive Finanzdaten veraendert"
                assert not store.list_canonical_events()
                result["phase"] = "preview_ready_live_canonical_empty"
                print("Echte Vorschau bereit; produktive kanonische Ereignisse weiterhin leer.", flush=True)
                expect(job_area.get_by_role("region", name="Beispielzeilen der Importvorschau").locator("tbody tr")).to_have_count(2)
                expect(job_area.get_by_label("SHA-256 der Vorschau")).to_have_text(ready["preview_sha256"])
                assert_counts(area, {"Datens\u00e4tze": 1, "Seiten": 1, "Anfragen gespeicherter Seiten": 1, "Neu": 1, "Duplikate": 0, "Importierte Ereignisse": 0})
                screenshots("ready", job_area.get_by_role("heading").first)

                approve = area.get_by_role("button", name="Importieren und neu berechnen", exact=True)
                expect(approve).to_be_disabled()
                area.get_by_label("Freigebende Person (Importprotokoll)", exact=True).fill(ACTOR)
                expect(approve).to_be_disabled()
                area.get_by_label(f"Ich best\u00e4tige den Import dieser Vorschau f\u00fcr {LABEL_A}.", exact=True).check()
                expect(approve).to_be_disabled()
                assert not store.list_canonical_events()
                area.get_by_label("Ich best\u00e4tige die Neuberechnung der betroffenen Bestands- und Steuerauswertungen.", exact=True).check()
                expect(approve).to_be_enabled()
                screenshots("approval", approve)
                assert not store.list_canonical_events(), "Checkboxen allein duerfen keinen Import ausloesen"
                assert not any(call["path"].endswith("/import") for call in result["calls"])
                with page.expect_response(lambda response: urlparse(response.url).path == history_base + "/jobs/" + job_id + "/import") as approval_response:
                    approve.click()
                applied_response = approval_response.value
                assert applied_response.status == 200, applied_response.text()
                expect(job_area.get_by_role("status").first).to_contain_text("Import abgeschlossen")
                expect(job_area.get_by_text("2 Ereignisse importiert.", exact=False)).to_be_visible()
                expect(job_area.get_by_text("Freigegeben von: " + ACTOR + ".", exact=False)).to_be_visible()
                assert_counts(area, {"Datens\u00e4tze": 1, "Seiten": 1, "Anfragen gespeicherter Seiten": 1, "Neu": 1, "Duplikate": 0, "Importierte Ereignisse": 2})
                expect(area.locator(".hiContext code")).to_have_text(ref_a)
                screenshots("imported", job_area.get_by_role("heading").first)

                events = store.list_canonical_events()
                actual = {(event.source, event.account, event.event_type, event.asset, event.quantity, event.tx_id) for event in events}
                expected = {("solana_rpc", wallet_a, "transfer", "SOL", Decimal("1"), signature),
                            ("solana_rpc", wallet_a, "fee", "SOL", Decimal("-0.000005"), signature)}
                assert len(events) == 2 and actual == expected, actual
                assert all(event.event_time.replace(tzinfo=timezone.utc) == datetime(2025, 1, 1, 12, tzinfo=timezone.utc) for event in events)
                assert all(event.account != wallet_b for event in events)
                result["phase"] = "imported_exactly_transfer_and_fee_on_a"
                print("Explizite Freigabe importiert genau Transfer und Gebuehr auf Wallet A.", flush=True)
                assert [row.model_dump(mode="json") for row in connectors.connections()] == connections_before
                completed = api(history_base + "/jobs/" + job_id)
                assert completed["status"] == "succeeded" and completed["imported_events"] == 2
                assert completed["approval"]["actor"] == ACTOR
                assert api(f"/api/v1/workspace/sources/{ref_b}/history")["jobs"] == []
                sources = api("/api/v1/workspace/sources")["sources"]
                source_a = next(source for source in sources if source["ref"] == ref_a)
                source_b = next(source for source in sources if source["ref"] == ref_b)
                assert source_a["events_count"] == 2 and source_b["events_count"] == 0
                assert source_a["review_tasks_count"] > 0
                audit = api(history_base + "/jobs/" + job_id + "/audit.json")
                assert audit["source_binding"]["wallet_address"] == wallet_a and audit["tax_source_activated"] is False

                panel.get_by_role("tab", name="Hinweise / Abgleich", exact=True).click()
                task_title = "Solana-Bewegung fachlich einordnen"
                task = panel.get_by_role("region", name="Zugeordnete Review-Aufgaben").locator(".wsTaskRow").filter(has_text=task_title)
                expect(task).to_have_count(1)
                task.get_by_role("button", name="Review-Aufgabe \u00f6ffnen", exact=True).click()
                task_panel = page.get_by_role("dialog", name=task_title, exact=True)
                expect(task_panel.get_by_role("button", name="Betroffene Quelle \u00f6ffnen", exact=True)).to_be_enabled()
                query = parse_qs(urlparse(page.url).fragment.partition("?")[2])
                task_id = query["detail"][0]
                task_data = api("/api/v1/workspace/review/query", {"task_id": task_id})["items"]
                assert len(task_data) == 1 and task_data[0]["source_ref"] == ref_a
                task_panel.get_by_role("button", name="Betroffene Quelle \u00f6ffnen", exact=True).click()
                expect(page.get_by_role("dialog", name=LABEL_A, exact=True)).to_be_visible()
                query = parse_qs(urlparse(page.url).fragment.partition("?")[2])
                assert query["detail"] == [ref_a] and query["task"] == [task_id]
                screenshots("source-task", page.get_by_role("dialog").get_by_role("region", name="Zugeordnete Review-Aufgaben"))

                page.get_by_role("dialog").get_by_role("button", name="Details schlie\u00dfen", exact=True).click()
                row_a = page.locator(".wsSourceRow").filter(has=page.get_by_role("button", name=LABEL_A, exact=True))
                row_b = page.locator(".wsSourceRow").filter(has=page.get_by_role("button", name=LABEL_B, exact=True))
                expect(row_a.locator(".wsSourceIdentity small").first).to_contain_text("2 Ereignisse")
                expect(row_b.locator(".wsSourceIdentity small").first).to_contain_text("0 Ereignisse")
                row_b.get_by_role("button", name="Transaktionen abrufen", exact=True).click()
                other = page.get_by_role("region", name="Automatischer Import: " + LABEL_B, exact=True)
                expect(other.locator(".hiContext code")).to_have_text(ref_b)
                expect(other.get_by_text("F\u00fcr diese Quelle ist noch kein Historienauftrag gespeichert.", exact=True)).to_be_visible()
                expect(other.get_by_role("region", name="Ausgew\u00e4hlter Historienauftrag")).to_have_count(0)
                assert len(result["collector_calls"]) == 1 and result["collector_calls"][0]["source_ref"] == ref_a
                mutations = [call for call in result["calls"] if call["method"] == "POST" and "/history/" in call["path"]]
                assert [call["path"] for call in mutations] == [history_base + "/jobs", history_base + "/jobs/" + job_id + "/import"]
                assert mutations[1]["payload"] == {"preview_sha256": ready["preview_sha256"], "actor": ACTOR,
                                                   "confirm_import": True, "confirm_recalculation": True}
                assert not result["external_requests"] and not result["javascript_errors"] and not result["bridge_errors"], result
                result.update(
                    passed=True, source_a=ref_a, source_b=ref_b, job_id=job_id, task_id=task_id,
                    ready_before_approval=ready, completed=completed,
                    financial_counts_before=initial_counts, financial_counts_after=financial_counts(),
                    canonical_events=[event.model_dump(mode="json") for event in events],
                    wallet_b_untouched=True, source_task_roundtrip=True, explicit_actor_and_two_consents=True,
                )
            except Exception:
                page.screenshot(path=str(args.output / "failure.png"), animations="disabled")
                (args.output / "failure-dom.html").write_text(page.content(), encoding="utf-8")
                raise
    except Exception as exc:
        result.update(passed=False, failure=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        result["cleanup"]["disposable_state_removed"] = state is not None and not state.exists()
        (args.output / "verification.json").write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        print(json.dumps({key: value for key, value in result.items() if key not in {
            "calls", "canonical_events", "ready_before_approval", "completed",
        }}, ensure_ascii=True))


if __name__ == "__main__":
    main()
