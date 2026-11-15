"""Isolierter Browsernachweis der lesenden Portfolio-Auftragsauskunft."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    harness = '''import React from "react";
import {createRoot} from "react-dom/client";
import {CurrentPriceRequestStatus,rememberCurrentPriceRequest} from "./src/workspace/CurrentPriceRequestStatus";
(window as any).rememberPriceRequest=rememberCurrentPriceRequest;
createRoot(document.getElementById("root")).render(<CurrentPriceRequestStatus/>);'''
    code = f'''import {{build}} from "esbuild";
const result=await build({{stdin:{{contents:{json.dumps(harness)},resolveDir:process.cwd(),loader:"tsx"}},bundle:true,write:false,format:"iife",define:{{"import.meta.env.VITE_API_BASE":'""'}}}});
process.stdout.write(result.outputFiles[0].text);'''
    bundle = subprocess.check_output(["node", "--input-type=module", "-e", code], cwd=root / "frontend", text=True)
    styles = (root / "frontend/src/styles.css").read_text() + (root / "frontend/src/workspace/workspace.css").read_text()
    output = args.output or Path(tempfile.mkdtemp(prefix="steuerreport-price-status-browser-"))
    output.mkdir(parents=True, exist_ok=True)
    calls = []
    state = ["recorded"]
    request_id = "11111111-1111-4111-8111-111111111111"
    def route(request):
        path = request.request.url
        if path == "http://synthetic.invalid/":
            request.fulfill(content_type="text/html", body=f'<html lang="de"><meta name="viewport" content="width=device-width,initial-scale=1"><style>{styles}</style><main id="root"></main><script>{bundle}</script></html>')
        elif path.endswith("/api/v1/prices/backfill/current-portfolio/status"):
            calls.append(request.request.post_data_json)
            if state[0] == "error":
                request.fulfill(status=500, body='{"status":"error"}')
            else:
                request.fulfill(content_type="application/json", body=json.dumps({"status": "warning", "warnings": [{"message": "Ein Preisabruf ist fehlgeschlagen."}] if state[0] == "recorded" else [], "data": {
                    "status": state[0], "explanation": "Gespeicherte Antwort" if state[0] == "recorded" else "Ausgang unbekannt oder noch in Arbeit",
                    "result": {"pipeline_status": "completed", "imported_prices": 2, "failed": 1, "skipped": 3, "stored_price_ids": []} if state[0] == "recorded" else None,
                }}))
        else:
            raise AssertionError(f"Unexpected request: {path}")
    with sync_playwright() as browser:
        chromium = browser.chromium.launch()
        for width in (390, 1440):
            page = chromium.new_page(viewport={"width": width, "height": 900})
            page.route("**/*", route)
            page.goto("http://synthetic.invalid/")
            field = page.get_by_label("Auftragskennung", exact=True)
            expect(field).to_be_visible()
            assert len(calls) == 0
            button = page.get_by_role("button", name="Auftragsstatus lesen")
            expect(button).to_be_disabled()
            page.evaluate("id => window.rememberPriceRequest(id)", request_id)
            expect(field).to_have_value(request_id)
            page.reload()
            expect(field).to_have_value(request_id)
            assert calls == []
            for value in ("recorded", "unknown_or_running", "not_found", "error"):
                state[0] = value
                button.click()
                if value == "recorded":
                    expect(page.get_by_text("Fehlgeschlagen: 1", exact=False)).to_be_visible()
                    expect(page.get_by_text("Ein Preisabruf ist fehlgeschlagen.", exact=True)).to_be_visible()
                elif value == "error":
                    expect(page.get_by_text("Auftragsstatus nicht sicher lesbar", exact=False)).to_be_visible()
                else:
                    expect(page.get_by_text("Ausgang unbekannt oder noch in Arbeit", exact=True)).to_be_visible()
                    expect(page.get_by_text("Damals gespeichert:", exact=False)).to_have_count(0)
                expect(button).to_be_enabled()
                page.screenshot(path=str(output / f"status-{value}-{width}.png"))
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert all(item == {"request_id": request_id} for item in calls)
            calls.clear()
            page.close()
        chromium.close()
    print(json.dumps({"synthetic": True, "viewports": [390, 1440], "screenshots": str(output), "external_requests": 0}))


if __name__ == "__main__":
    main()
