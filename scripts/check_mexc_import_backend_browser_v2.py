"""MEXC-Wizard mit echtem isoliertem Importbackend; keine Produktions-/Providerzugriffe.

Nur die uebrigen Workspace-Anzeigen sind synthetische Antworten. Alle Import-,
Normalisierungs-, Ledger-, Originaldownload- und Trace-Aufrufe laufen gegen
create_app mit einer temporaeren DuckDB. Keine laufende Instanz wird verwendet.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import socket
import shutil
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import patch
from urllib.parse import urlparse

from openpyxl import Workbook
from playwright.sync_api import expect, sync_playwright

from ux_workspace_fixtures import WorkspaceFixture


def workbook(headers, values):
    book = Workbook()
    book.active.title = "Sheet1"
    book.active.append(headers)
    book.active.append(values)
    out = BytesIO()
    book.save(out)
    return out.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-executable")
    parser.add_argument("--output", type=Path, default=Path("artifacts/mexc-backend-browser"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    code = Path(__file__).resolve().parents[1]
    original_connect, original_dns = socket.socket.connect, socket.getaddrinfo

    def local_connect(sock, address):
        if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1", "localhost"}:
            raise AssertionError("MEXC-Abnahme: externer Netzwerkzugriff gesperrt")
        return original_connect(sock, address)

    def local_dns(host, *a, **kw):
        if host not in {"127.0.0.1", "::1", "localhost", b"127.0.0.1", b"localhost"}:
            raise AssertionError("MEXC-Abnahme: externe DNS-Aufloesung gesperrt")
        return original_dns(host, *a, **kw)

    with ExitStack() as stack:
        tmp = Path(stack.enter_context(TemporaryDirectory(prefix="sr-mexc-backend-browser-")))
        clean_env = {k: v for k, v in os.environ.items() if not k.startswith("STEUERREPORT_")}
        clean_env.update({
            "STEUERREPORT_V2_ROOT": str(tmp / "software"), "STEUERREPORT_STATE_DIR": str(tmp / "state"),
            "STEUERREPORT_PRIVATE_PROFILE": "", "STEUERREPORT_PRIVATE_CONFIG_DIR": str(tmp / "configs"),
            "STEUERREPORT_V2_DB": str(tmp / "synthetic.duckdb"), "STEUERREPORT_USERTRANSFER_ROOT": str(tmp / "imports"),
        })
        stack.enter_context(patch.dict(os.environ, clean_env, clear=True))
        public_configs = tmp / "software/configs"
        public_configs.mkdir(parents=True)
        for target, source in {"crypto_price_sources.example.json": "crypto_price_sources.json",
                               "source_registry.example.json": "source_registry.example.json"}.items():
            shutil.copyfile(code / "configs" / source, public_configs / target)
        from fastapi.testclient import TestClient
        from steuerreport_v2.api.app import create_app
        from steuerreport_v2.db.duckdb_store import DuckDbStore
        from steuerreport_v2.ledger.balance import BalanceLedgerBuilder
        from steuerreport_v2.domain.review import ReviewService

        store = DuckDbStore(tmp / "synthetic.duckdb")
        client = stack.enter_context(TestClient(create_app(store)))
        stack.enter_context(patch.object(socket.socket, "connect", local_connect))
        stack.enter_context(patch.object(socket, "getaddrinfo", local_dns))

        class QuietHandler(SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                path = urlparse(self.path).path
                if path.startswith("/api/v1/import/batches/") and path.endswith(("/original", "/trace.json")):
                    calls.append({"method": "GET", "path": path})
                    response = client.get(self.path)
                    self.send_response(response.status_code)
                    for key, value in response.headers.items():
                        if key.lower() in {"content-type", "content-disposition"}:
                            self.send_header(key, value)
                    self.send_header("Content-Length", str(len(response.content)))
                    self.end_headers()
                    self.wfile.write(response.content)
                elif path.startswith("/api/"):
                    self.send_error(451, "API nur ueber den isolierten ASGI-Testclient")
                else:
                    super().do_GET()

        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(code / "frontend/dist")))
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        stack.callback(server.server_close)
        stack.callback(worker.join)
        stack.callback(server.shutdown)
        origin = f"http://127.0.0.1:{server.server_port}"
        playwright = stack.enter_context(sync_playwright())
        browser = stack.enter_context(playwright.chromium.launch(headless=True, executable_path=args.browser_executable))
        context = stack.enter_context(browser.new_context(viewport={"width": 1440, "height": 1000}, service_workers="block", accept_downloads=True))
        fixture, errors, calls, unmodelled = WorkspaceFixture(), [], [], []

        def handle(route):
            req, url = route.request, urlparse(route.request.url)
            if url.netloc != urlparse(origin).netloc:
                raise AssertionError("Browser-Fremdverkehr gesperrt")
            if url.path.startswith("/api/v1/import/"):
                calls.append({"method": req.method, "path": url.path})
                if req.method == "GET" and url.path.startswith("/api/v1/import/batches/") and url.path.endswith(("/original", "/trace.json")):
                    route.continue_()
                    return
                response = client.request(req.method, url.path, json=req.post_data_json if req.post_data else None)
                headers = {k: v for k, v in response.headers.items() if k.lower() in {"content-type", "content-disposition"}}
                route.fulfill(status=response.status_code, headers=headers, body=response.content)
            elif url.path.startswith("/api/"):
                if req.method not in {"GET", "HEAD"} and url.path not in {"/api/v1/activity/query", "/api/v1/workspace/review/query"}:
                    raise AssertionError("Fachfremder Schreibaufruf gesperrt")
                if url.path == "/api/v1/health" and req.method == "GET":
                    response = client.get(url.path)
                    route.fulfill(status=response.status_code, content_type="application/json", body=response.content)
                elif not fixture.handle(route):
                    unmodelled.append(url.path)
                    route.fulfill(status=503, content_type="application/json", body=json.dumps({
                        "status": "error", "errors": [{"code": "isolated_workspace_not_modelled"}], "data": None}))
            else:
                route.continue_()

        context.route("**/*", handle)
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))
        expect.set_options(timeout=60000)
        page.goto(origin + "/#import", wait_until="domcontentloaded")
        panel = page.get_by_role("region", name="Dateiimport", exact=True)
        expect(panel.get_by_label("Importquelle", exact=True)).to_be_visible()
        panel.get_by_label("Importquelle", exact=True).select_option("mexc")
        panel.get_by_label("MEXC-Konto", exact=True).fill("synthetic-spot")
        spot = workbook(["UID", "Creation Time(UTC+01:00)", "Crypto", "Transaction Type", "Direction", "Quantity"],
                        ["SYNTHETIC-ACCOUNT", "2031-07-09 12:00:00", "DEMOCOIN", "Airdrop", "Inflow", "2.5"])

        def upload(name, content, kind):
            panel.get_by_label("Importdateien auswaehlen", exact=True).set_input_files({"name": name,
                "mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "buffer": content})
            panel.get_by_label(f"MEXC-Exportart fuer {name}", exact=True).select_option(kind)

        def execute():
            panel.get_by_role("checkbox", name="Gepruefte Dateien freigeben", exact=False).check()
            panel.get_by_role("button", name="1 Datei(en) importieren", exact=True).click()
            expect(panel.get_by_role("link", name="Originaldatei", exact=True)).to_be_visible()

        upload("spot.xlsx", spot, "spot_statement")
        panel.get_by_role("button", name="Dateien pruefen", exact=True).click()
        expect(panel.get_by_role("button", name="1 Datei(en) importieren", exact=True)).to_be_visible()
        assert store.list_import_batches() == []
        execute()
        assert len(store.list_canonical_events()) == 1
        root = store.list_raw_objects(limit=None)[0].raw_object_id
        with page.expect_download() as event:
            panel.get_by_role("link", name="Originaldatei", exact=True).click()
        downloaded = event.value
        assert Path(downloaded.path()).read_bytes() == spot
        panel.get_by_role("button", name="Neuer Import", exact=True).click()
        funding = workbook(["UID", "Time", "Crypto", "Type", "Quantity", "Status", "Remark"],
                           ["SYNTHETIC-ACCOUNT", "2031-07-09 12:00:00", "DEMOCOIN", "Airdrop", "2.5", None, None])
        upload("funding.xlsx", funding, "funding_other")
        panel.get_by_role("button", name="Dateien pruefen", exact=True).click()
        expect(panel.get_by_text("Zeitbasis fuer Time fehlt", exact=False).first).to_be_visible()
        assert len(store.list_import_batches()) == 1
        panel.get_by_label("MEXC-Zeitbasis fuer funding.xlsx", exact=True).select_option("UTC+01:00")
        panel.get_by_role("button", name="Dateien pruefen", exact=True).click()
        review = panel.get_by_role("region", name="MEXC-Pruefung fuer funding.xlsx", exact=True)
        expect(review.get_by_text("moeglicher Doppelbeleg", exact=False).first).to_be_visible()
        review.locator("summary").click()
        review.get_by_label("Belegzuordnung Zeile 2 fuer funding.xlsx", exact=True).select_option("raw:" + root)
        review.get_by_label("Begruendung Zeile 2 fuer funding.xlsx", exact=True).fill("Synthetisches Belegpaar anhand beider Originale geprueft.")
        panel.get_by_role("button", name="Dateien pruefen", exact=True).click()
        expect(panel.get_by_role("button", name="1 Datei(en) importieren", exact=True)).to_be_visible()
        execute()
        assert len(store.list_import_batches()) == 2 and len(store.list_canonical_events()) == 1
        assert str(BalanceLedgerBuilder(store).positions()[0].quantity) == "2.500000000000000000"
        assert not ReviewService(store).gate().allow_export
        with page.expect_download() as event:
            panel.get_by_role("link", name="Belegspur (JSON)", exact=True).click()
        trace = json.loads(Path(event.value.path()).read_text())
        assert len(trace["mexc_evidence"]) == 2
        for width in (1440, 390):
            page.set_viewport_size({"width": width, "height": 1000})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 1")
            page.screenshot(path=str(args.output / f"mexc-real-import-{width}.png"), full_page=True, animations="disabled")
        assert not errors, errors
        result = {"passed": True, "synthetic_only": True, "real_import_backend": True,
            "workspace_displays_mocked": True, "no_external_requests": True,
            "raw_rows": 2, "canonical_events": 1, "quantity": "2.5",
            "review_blocks_export": True, "original_download_exact": True,
            "trace_originals": 2, "viewports": [1440, 390], "calls": calls}
        result["unmodelled_workspace_reads"] = sorted(set(unmodelled))
        (args.output / "verification.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))


if __name__ == "__main__":
    main()
