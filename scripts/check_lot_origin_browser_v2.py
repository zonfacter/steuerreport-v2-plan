"""Lesender Herkunftsablauf mit echten API-Antworten und synthetischer Datenbank."""
from contextlib import ExitStack
from datetime import datetime, timezone
from decimal import Decimal
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import argparse
import json
import os
from pathlib import Path
import tempfile
from threading import Thread
from urllib.parse import urlparse

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser-executable")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    with ExitStack() as stack:
        state = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="sr-origin-browser-")))
        for key in list(os.environ):
            if key.startswith("STEUERREPORT_"):
                del os.environ[key]
        os.environ.update(STEUERREPORT_STATE_DIR=str(state), STEUERREPORT_PRIVATE_PROFILE="",
            STEUERREPORT_PRIVATE_CONFIG_DIR=str(state / "configs"), STEUERREPORT_V2_DB=str(state / "test.duckdb"),
            STEUERREPORT_USERTRANSFER_ROOT=str(state / "imports"))
        from fastapi.testclient import TestClient
        from steuerreport_v2.api.app import create_app
        from steuerreport_v2.contracts.events import CanonicalEventCreate
        from steuerreport_v2.contracts.tax import TaxLot, TaxLine
        from steuerreport_v2.db.duckdb_store import DuckDbStore
        from steuerreport_v2.domain.tax import TaxService
        from check_review_backend_browser_v2 import fingerprint
        from ux_workspace_fixtures import WorkspaceFixture
        store = DuckDbStore(state / "test.duckdb")
        acquired = datetime(2024, 1, 1, tzinfo=timezone.utc)
        carried = datetime(2024, 2, 1, tzinfo=timezone.utc)
        disposed = datetime(2024, 3, 1, tzinfo=timezone.utc)
        reward, transfer, sale = store.add_canonical_events([
            CanonicalEventCreate(source="helium", event_time=acquired, event_type="reward", asset="HNT", quantity=Decimal("100")),
            CanonicalEventCreate(source="helium", event_time=carried, event_type="transfer", asset="JUP", quantity=Decimal("1")),
            CanonicalEventCreate(source="synthetic", event_time=disposed, event_type="trade", asset="JUP", quantity=Decimal("-0.4"), quote_asset="EUR", quote_quantity=Decimal("60")),
        ])
        # Gespeicherte synthetische Rechenergebnisse, keine fachliche Freigabe/Umstellung.
        lots = [
            TaxLot(lot_id="synthetic-root", asset="HNT", acquired_at=acquired, quantity_total=Decimal("100"), quantity_remaining=Decimal("0"), cost_basis_eur_total=Decimal("90"), source_event_id=reward.event_id),
            TaxLot(lot_id="synthetic-carry", asset="JUP", acquired_at=acquired, quantity_total=Decimal("1"), quantity_remaining=Decimal("0.6"), cost_basis_eur_total=Decimal("90"), source_event_id=transfer.event_id, origin_lot_id="synthetic-root"),
            TaxLot(lot_id="synthetic-orphan", asset="HNT", acquired_at=acquired, quantity_total=Decimal("1"), quantity_remaining=Decimal("0.5"), cost_basis_eur_total=Decimal("2"), source_event_id=reward.event_id, origin_lot_id="missing-synthetic-root"),
        ]
        lines = [
            TaxLine(tax_line_id="synthetic-line", asset="JUP", acquired_at=acquired, disposed_at=disposed, quantity=Decimal("0.4"), acquisition_cost_eur=Decimal("36"), disposal_proceeds_eur=Decimal("60"), gain_loss_eur=Decimal("24"), holding_days=60, source_event_id=sale.event_id, lot_id="synthetic-carry", acquisition_source_event_id=transfer.event_id, origin_lot_id="synthetic-root"),
            TaxLine(tax_line_id="synthetic-broken", asset="HNT", acquired_at=acquired, disposed_at=disposed, quantity=Decimal("0.5"), acquisition_cost_eur=Decimal("1"), disposal_proceeds_eur=Decimal("2"), gain_loss_eur=Decimal("1"), holding_days=60, source_event_id=sale.event_id, lot_id="synthetic-orphan", origin_lot_id="missing-synthetic-root"),
        ]
        TaxService(store)._replace_tax_tables(lots, lines, [])
        client = stack.enter_context(TestClient(create_app(store)))
        before = fingerprint(store)
        endpoint = "/api/v1/tax-years/business-reward-inventory-review"
        report = client.get(endpoint).json()["data"]
        assert report["potential_business_tax_lines_count"] == 1 and report["unresolved_tax_lines_count"] == 1
        assert report["strict_ready"] is False
        fixture = WorkspaceFixture()
        fixture.fresh = False
        class Handler(SimpleHTTPRequestHandler):
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(root / "frontend/dist")))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        stack.callback(server.server_close)
        stack.callback(thread.join)
        stack.callback(server.shutdown)
        origin = f"http://127.0.0.1:{server.server_port}"
        calls, errors, shots = [], [], []
        with sync_playwright() as playwright:
            browser = stack.enter_context(playwright.chromium.launch(headless=True, executable_path=args.browser_executable))
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, reduced_motion="reduce")
            page.on("pageerror", lambda error: errors.append(str(error)))
            def bridge(route):
                request = route.request
                parsed = urlparse(request.url)
                if parsed.netloc != urlparse(origin).netloc:
                    raise AssertionError("No external browser requests permitted")
                if not parsed.path.startswith("/api/"):
                    return route.continue_()
                assert request.method == "GET", "No browser write permitted"
                calls.append(parsed.path)
                if parsed.path == endpoint:
                    response = client.get(endpoint)
                    return route.fulfill(status=response.status_code, content_type="application/json", body=response.content)
                if parsed.path == "/api/v1/tax-years":
                    return fixture.send(route, [{"year": 2024, "state": "review_required", "issues": []}])
                if parsed.path == "/api/v1/tax/bmf-combined-fifo-staging/latest":
                    return fixture.send(route, {"status": "ready_for_professional_review", "strict_ready": False,
                        "origin_trace_policy": "legacy_direct_origin_v1", "years": [2024], "year_rows": [], "top_events": [], "top_assets": [], "sphere_rows": []})
                try:
                    if fixture.handle(route):
                        return
                except ValueError:
                    pass
                fixture.send(route, {})
            page.route("**/*", bridge)
            expect.set_options(timeout=30000)
            page.goto(origin + "/#tax?tab=details&year=2024", wait_until="networkidle")
            panel = page.locator(".panel").filter(has=page.get_by_text("Ursprungssphaere der Verwertungen 2024", exact=True))
            expect(panel).to_have_count(1)
            expect(panel.get_by_text("Ursprungslot fortgeführt", exact=True)).to_be_visible()
            expect(panel.get_by_text("Herkunftskette offen", exact=True)).to_be_visible()
            expect(panel.get_by_role("columnheader", name="gewinn_verlust_eur", exact=True)).to_be_visible()
            for width in (390, 768, 1280, 1440):
                page.set_viewport_size({"width": width, "height": 1000})
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
                panel.scroll_into_view_if_needed()
                panel.screenshot(path=str(args.output / f"lineage-{width}.png"))
                opener = panel.get_by_role("button", name="Ursprungslot anzeigen", exact=True).last
                opener.click()
                dialog = page.get_by_role("dialog", name="Ursprung der Verwertung", exact=True)
                expect(dialog).to_be_visible()
                expect(dialog.get_by_text("synthetic-root", exact=True)).to_be_visible()
                expect(dialog.get_by_text("36,00 EUR", exact=True)).to_be_visible()
                expect(dialog.get_by_text("24,00 EUR", exact=True)).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
                dialog.screenshot(path=str(args.output / f"lineage-detail-{width}.png"))
                dialog.get_by_role("button", name="Details schließen", exact=True).click()
                expect(opener).to_be_focused()
                shots.append(width)
            page.goto(origin + "/#tax?tab=expert&year=2024", wait_until="networkidle")
            expect(page.get_by_text("Herkunftsvorschau veraltet", exact=True)).to_be_visible()
            assert fingerprint(store) == before
            assert not errors, errors
        result = {"passed": True, "viewports": shots, "actual_business_api": True, "unrelated_api": "synthetic fixtures",
            "database_unchanged": True, "browser_writes": 0, "external_requests": 0, "errors": errors,
            "checks": ["carried_root_visible", "unresolved_visible", "gain_column_not_hidden", "detail_basis_36_gain_24", "focus_return", "old_policy_stale"], "api_reads": len(calls)}
        (args.output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))


if __name__ == "__main__":
    main()
