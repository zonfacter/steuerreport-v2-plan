"""Browserabnahme mit echtem Preisrouter und disponiblen Daten; kein Live-Netz."""
import argparse
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import csv
import io
import os
from pathlib import Path
import re
import tempfile
import zipfile
from threading import Thread
from unittest.mock import patch
from urllib.parse import urlparse


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser-executable")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="historical-prices-browser-") as temporary, ExitStack() as stack:
        state = Path(temporary)
        stack.enter_context(patch.dict(os.environ))
        for key in list(os.environ):
            if key.startswith("STEUERREPORT_"):
                del os.environ[key]
        os.environ.update(STEUERREPORT_STATE_DIR=str(state), STEUERREPORT_PRIVATE_PROFILE=str(state / "profile.json"),
                          STEUERREPORT_PRIVATE_CONFIG_DIR=str(state / "configs"), STEUERREPORT_V2_DB=str(state / "test.duckdb"))
        (state / "profile.json").write_text("{}\n")
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import httpx
        from playwright.sync_api import expect, sync_playwright
        from steuerreport_v2.api.historical_prices import build_historical_prices_router
        from steuerreport_v2.contracts.events import CanonicalEventCreate
        from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
        from steuerreport_v2.contracts.request_limits import RequestLimitProfile, RequestLimitsConfig
        from steuerreport_v2.db.duckdb_store import DuckDbStore
        from steuerreport_v2.domain import historical_prices as module
        from steuerreport_v2.domain.external_http import managed_client
        from steuerreport_v2.domain.historical_prices import HistoricalPriceService
        from steuerreport_v2.domain.request_limits import RequestLimiter
        from ux_workspace_fixtures import WorkspaceFixture
        store = DuckDbStore(state / "test.duckdb")
        for index in range(26):
            store.add_canonical_event(CanonicalEventCreate(source="solana_rpc", source_ref=f"synthetic-sol-{index}",
                event_time=datetime(2024, 1, 2, 12, tzinfo=timezone.utc) + timedelta(days=index), event_type="transfer", asset="SOL", quantity=Decimal("2")))
        batch = store.create_import_batch(ImportBatchCreate(source="solana_rpc", filename="synthetic-mint.json"))
        raw = store.add_raw_object(batch.batch_id, RawObjectCreate(payload_json=json.dumps({"mint": "Ab" + "1" * 30})))
        store.add_canonical_event(CanonicalEventCreate(source="solana_rpc", source_ref="synthetic-token",
            raw_object_id=raw.raw_object_id, event_time=datetime(2025, 1, 5, 12, tzinfo=timezone.utc),
            event_type="transfer", asset="SYNTHETIC_TOKEN", quantity=Decimal("2")))
        store.add_canonical_event(CanonicalEventCreate(source="solana_rpc", source_ref="synthetic-unknown",
            event_time=datetime(2025, 1, 5, 12, tzinfo=timezone.utc), event_type="transfer", asset="SYNTHETIC_UNKNOWN", quantity=Decimal("2")))
        store.add_canonical_event(CanonicalEventCreate(source="manual", source_ref="synthetic-eur",
            event_time=datetime(2023, 6, 2, 12, tzinfo=timezone.utc), event_type="transfer", asset="EUR", quantity=Decimal("100")))
        limiter = RequestLimiter(state_root=state)
        limiter.write_config(RequestLimitsConfig(default_profile=RequestLimitProfile(requests_per_second=100, requests_per_minute=6000, burst=100)), expected_revision=0)
        provider_calls = []
        def provider(request):
            provider_calls.append({"host": request.url.host, "path": request.url.path})
            if request.url.host == "api.frankfurter.dev":
                first, last = date.fromisoformat(request.url.params["from"]), date.fromisoformat(request.url.params["to"])
                return httpx.Response(200, json=[{"base": "USD", "quote": "EUR", "date": (first + timedelta(days=offset)).isoformat(), "rate": "0.92"}
                    for offset in range((last - first).days + 1) if (first + timedelta(days=offset)).weekday() < 5])
            assert request.url.host == "coins.llama.fi", "Unerwarteter Mock-Provider"
            assert request.url.path == "/batchHistorical"
            coins = json.loads(request.url.params["coins"])
            return httpx.Response(200, json={"coins": {identifier: {"prices": [{"timestamp": timestamp, "price": "150", "confidence": "0.99"} for timestamp in timestamps]} for identifier, timestamps in coins.items()}})
        stack.enter_context(patch.object(module, "managed_client", lambda **kw: managed_client(transport=httpx.MockTransport(provider), limiter=limiter, **kw)))
        app = FastAPI()
        app.include_router(build_historical_prices_router(store, lambda: None))
        client = stack.enter_context(TestClient(app))
        fixture = WorkspaceFixture()
        fixture.fresh = True
        service = HistoricalPriceService(store)
        before = service._revision()
        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self):
                # Chromium-Downloads koennen die Browser-Route umgehen. Nur den
                # lesenden Preisrouter auch am lokalen Testserver bereitstellen.
                path = urlparse(self.path).path
                if path.startswith("/api/v1/prices/historical/"):
                    response = client.get(path)
                    self.send_response(response.status_code)
                    for key in ("content-type", "content-disposition"):
                        if key in response.headers:
                            self.send_header(key, response.headers[key])
                    self.send_header("Content-Length", str(len(response.content)))
                    self.end_headers()
                    self.wfile.write(response.content)
                    return
                super().do_GET()
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(root / "frontend/dist")))
        Thread(target=server.serve_forever, daemon=True).start()
        stack.callback(server.server_close)
        stack.callback(server.shutdown)
        origin = "http://127.0.0.1:" + str(server.server_port)
        calls, errors, external, held = [], [], [], []
        hold_plan = [True]
        def respond(route):
            request = route.request
            parsed = urlparse(request.url)
            if parsed.netloc != urlparse(origin).netloc:
                external.append(parsed.hostname)
                route.abort()
            elif parsed.path.startswith("/api/v1/prices/historical"):
                calls.append({"method": request.method, "path": parsed.path})
                if parsed.path.endswith("/plan") and hold_plan[0]:
                    held.append(route)
                    return
                response = client.request(request.method, parsed.path, content=request.post_data, headers={"Content-Type": "application/json"})
                route.fulfill(status=response.status_code, body=response.content, content_type="application/json")
            elif parsed.path.startswith("/api/"):
                if not fixture.handle(route):
                    fixture.send(route, {})
            else:
                route.continue_()
        expect.set_options(timeout=60000)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, executable_path=args.browser_executable)
            context = browser.new_context(viewport={"width": 1440, "height": 1000}, service_workers="block", reduced_motion="reduce")
            context.route("**/*", respond)
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(origin + "/#portfolio?tab=prices&year=all", wait_until="domcontentloaded")
            region = page.get_by_role("region", name="EUR-Preise ermitteln", exact=True)
            expect(region).to_be_visible()
            expect(region.get_by_role("combobox", name="Preisumfang", exact=True)).to_have_value("all_observed")
            region.get_by_label("Maximale HTTP-Anfragen", exact=True).fill("2")
            expect(region.get_by_role("button", name="Kurse abrufen und Vorschau berechnen", exact=True)).to_have_count(0)
            region.get_by_role("button", name="Preisbedarf planen", exact=True).click()
            expect(region.get_by_role("status")).to_contain_text("Preisbedarf planen läuft")
            assert not provider_calls
            hold_plan[0] = False
            for route in held:
                respond(route)
            expect(region.get_by_text("28 fehlende Asset-Tagespreise", exact=False)).to_be_visible()
            expect(region.get_by_text("In der importierten Datenbasis sind nur", exact=False)).to_be_visible()
            region.get_by_role("button", name="Nächste Planseite", exact=True).click()
            expect(region.get_by_label("Planseiten")).to_contain_text("26–29 von 29")
            assert not provider_calls, "Planpagination darf keine Providerabfrage starten"
            expect(region.get_by_role("button", name="Kurse abrufen und Vorschau berechnen", exact=True)).to_be_disabled()
            assert service._revision() == before
            for width in (390, 768, 1280, 1440):
                page.set_viewport_size({"width": width, "height": 1000})
                if width <= 820:
                    expect(page.locator("#main-navigation")).to_be_hidden()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
                page.evaluate("window.scrollTo(0, 0)")
                page.screenshot(path=str(args.output / f"plan-{width}.png"), full_page=True)
            region.get_by_role("checkbox", name="Externe Preis- und", exact=False).check()
            region.get_by_role("button", name="Kurse abrufen und Vorschau berechnen", exact=True).click()
            expect(region.get_by_role("heading", name="Gespeicherte Preisvorschau")).to_be_visible()
            expect(region.get_by_text("25 belegte EUR-Preise", exact=False)).to_be_visible()
            assert len(provider_calls) == 2
            assert service._revision() == before
            apply = region.get_by_role("button", name="Preise und Neuberechnung übernehmen", exact=True)
            expect(apply).to_be_disabled()
            expect(region.get_by_text("2 noch nicht abgerufen", exact=False)).to_be_visible()
            expect(region.get_by_role("button", name="Nächsten Preisabschnitt abrufen", exact=True)).to_be_disabled()
            region.get_by_role("checkbox", name="Für diesen weiteren Abschnitt", exact=False).check()
            region.get_by_role("button", name="Nächsten Preisabschnitt abrufen", exact=True).click()
            expect(region.get_by_text("27 belegte EUR-Preise", exact=False)).to_be_visible()
            expect(region.get_by_text("0 noch nicht abgerufen", exact=False)).to_be_visible()
            assert len(provider_calls) == 4 and service._revision() == before
            for width in (390, 768, 1280, 1440):
                page.set_viewport_size({"width": width, "height": 1000})
                if width <= 820:
                    expect(page.locator("#main-navigation")).to_be_hidden()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
                page.evaluate("window.scrollTo(0, 0)")
                page.screenshot(path=str(args.output / f"preview-{width}.png"), full_page=True)
            with page.expect_download() as downloaded:
                region.get_by_role("link", name="Jahres-CSV und Belege als ZIP", exact=True).click()
            archive_bytes = Path(downloaded.value.path()).read_bytes()
            with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
                assert archive.testzip() is None
                assert len(json.loads(archive.read("report.json"))["preview"]["rows"]) == 29
                assert sum(len(list(csv.DictReader(io.StringIO(archive.read(f"{year}/preise.csv").decode())))) for year in (2023, 2024, 2025)) == 29
            (args.output / "synthetic-year-report.zip").write_bytes(archive_bytes)
            assert service._revision() == before and len(provider_calls) == 4
            page.reload(wait_until="domcontentloaded")
            expect(region.get_by_role("button", name="Abrufstatus prüfen", exact=True)).to_be_visible()
            region.get_by_role("button", name="Abrufstatus prüfen", exact=True).click()
            expect(region.get_by_text("27 belegte EUR-Preise", exact=False)).to_be_visible()
            region.get_by_label("Freigebende Person", exact=True).fill("Synthetische Browserpruefung")
            region.get_by_role("checkbox", name="Die ausgewiesenen EUR-Preise", exact=False).check()
            expect(apply).to_be_disabled()
            region.get_by_role("checkbox", name="Die gezeigte Neuberechnung", exact=False).check()
            apply.click()
            expect(region.get_by_role("heading", name="Preisübernahme abgeschlossen")).to_be_visible()
            assert any(price.price_eur == Decimal("138") for price in store.list_price_points())
            assert len(provider_calls) == 4
            page.reload(wait_until="domcontentloaded")
            expect(region.get_by_role("combobox", name="Jahr", exact=True)).to_have_value("all")
            region.locator("summary").filter(has_text="Gespeicherte Preisvorschauen").click()
            region.get_by_role("button", name="übernommen", exact=False).click()
            expect(region.get_by_role("heading", name="Preisübernahme abgeschlossen")).to_be_visible()
            region.locator("summary").filter(has_text="Preisquellen zuordnen").click()
            original_mint = "Ab" + "1" * 30
            region.get_by_label("Asset-Kennung", exact=True).fill(original_mint)
            region.get_by_label("CoinGecko-ID", exact=True).fill("synthetic-token")
            region.get_by_role("button", name="Preiszuordnung speichern", exact=True).click()
            expect(region.get_by_text("Preiszuordnung gespeichert.", exact=False)).to_be_visible()
            mapping = service.mappings()[original_mint.upper()]
            assert mapping["solana_mint"] == original_mint
            assert mapping["coingecko_id"] == "synthetic-token"
            assert len(provider_calls) == 4, "Eine Preiszuordnung darf keine Anbieteranfrage starten"
            region.get_by_role("combobox", name="Jahr", exact=True).select_option("2024")
            expect(page).to_have_url(re.compile(r"[?&]year=2024(?:&|$)"))
            page.reload(wait_until="domcontentloaded")
            expect(region.get_by_role("combobox", name="Jahr", exact=True)).to_have_value("2024")
            page.wait_for_load_state("networkidle")
            assert not external and not errors, (external, errors)
            context.close()
            browser.close()
        report = {"passed": True, "actual_price_router": True, "provider_boundary": "httpx.MockTransport", "real_external_requests": 0,
                  "mock_provider_calls": len(provider_calls), "canonical_events_unchanged": len(store.list_canonical_events()) == 29,
                  "viewports": [390, 768, 1280, 1440], "screenshots": 8,
                  "checks": ["loading_not_empty", "all_observed_transfers_and_fee_independent", "planning_and_pagination_read_only", "collection_not_limited_to_visible_page", "three_years", "fixed_eur_coverage", "original_mint_binding", "explicit_external_consent", "preview_isolated", "limited_section_and_cumulative_continue", "two_approvals_required", "complete_year_zip", "reload_status_no_refetch", "atomic_apply", "reload_year_and_saved_preview", "mapping_ui_roundtrip_preserves_original_mint", "year_url_roundtrip"], "browser_errors": errors}
        (args.output / "result.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))


if __name__ == "__main__":
    main()
