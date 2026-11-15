"""Isolierte synthetische Browserpruefung des echten Vergleichspanels."""
import json
from pathlib import Path
import subprocess
import tempfile

from playwright.sync_api import expect, sync_playwright


def report(state):
    compared = state in {"supporting", "cent"}
    delta = "0.001" if state == "cent" else "10"
    return {
        "year": 2025, "generated_at": "2026-01-01T00:00:00Z",
        "baseline": {"snapshot_id": "synthetic", "revision": 1, "state": "submitted",
                     "package_generated_at": "2026-01-01T00:00:00Z", "package_sha256": "a" * 64,
                     "integrity_status": "verified", "files_count": 1, "package_download_endpoint": "/synthetic.zip"},
        "status": "unchanged", "headline": "Synthetischer Vergleich", "next_action": "Detailabgleich bleibt offen.",
        "comparison_scope": {"aggregate_status": "different" if compared else "not_compared"} if state != "legacy" else None,
        "exact_change_detected": compared, "declaration_change_detected": state == "cent",
        "amendment_review_required": state == "cent", "integrity_blocked": False,
        "comparison_html_endpoint": "/synthetic.html", "legal_notice": "Synthetische Testdaten", "methodology": "Test",
        "deltas": [{"key": "test", "label": "Synthetischer Nachweiswert", "category": "supporting",
                    "filed_value_eur": "1.004" if state == "cent" else "20", "current_value_eur": "1.005" if state == "cent" else "30",
                    "delta_eur": delta, "rounded_amount_delta_eur": "0.01" if state == "cent" else "10",
                    "changed_at_cent_precision": True, "requires_review": state == "cent"}],
    }


def main():
    root = Path(__file__).resolve().parents[1]
    harness = '''import React from "react"; import {createRoot} from "react-dom/client";
import {TaxFilingSnapshotPanel} from "./src/main";
createRoot(document.getElementById("test-mount")).render(<TaxFilingSnapshotPanel year={2025} initialReport={(window as any).fixture} onDownload={()=>{throw new Error("unexpected action")}}/>);'''
    code = f'''import {{build}} from "esbuild";
const result=await build({{stdin:{{contents:{json.dumps(harness)},resolveDir:process.cwd(),loader:"tsx"}},bundle:true,write:false,format:"iife",loader:{{".css":"empty"}},define:{{"import.meta.env.VITE_API_BASE":'""'}}}});process.stdout.write(result.outputFiles[0].text);'''
    bundle = subprocess.check_output(["node", "--input-type=module", "-e", code], cwd=root / "frontend", text=True)
    styles = (root / "frontend/src/styles.css").read_text() + (root / "frontend/src/workspace/workspace.css").read_text()
    output = Path(tempfile.mkdtemp(prefix="steuerreport-filing-comparison-browser-"))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for width in (390, 768, 1280, 1440):
            for state in ("legacy", "unavailable", "supporting", "cent"):
                page = browser.new_page(viewport={"width": width, "height": 1000})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                def route(request):
                    assert request.request.url == "http://synthetic.invalid/", request.request.url
                    request.fulfill(content_type="text/html", body=f'<html lang="de"><meta name="viewport" content="width=device-width,initial-scale=1"><style>{styles}</style><div id="test-mount"></div><script>window.fixture={json.dumps(report(state))};</script><script>{bundle}</script></html>')
                page.route("**/*", route)
                page.goto("http://synthetic.invalid/")
                panel = page.locator(".filingSnapshotPanel")
                expect(panel).to_be_visible()
                if state in {"legacy", "unavailable"}:
                    expect(panel.get_by_text("Vergleich offen", exact=True)).to_be_visible()
                    expect(panel.get_by_text("Synthetischer Nachweiswert", exact=True)).to_have_count(0)
                    assert "Nicht verglichen" in panel.inner_text()
                    assert "ok" not in panel.get_attribute("class").split()
                elif state == "supporting":
                    expect(panel.get_by_text("keine Cent-Abweichung der deklarationsrelevanten Beträge", exact=True)).to_be_visible()
                    expect(panel.get_by_text("Synthetischer Nachweiswert", exact=True)).to_be_visible()
                else:
                    expect(panel.get_by_text("0,01 EUR", exact=True)).to_be_visible()
                    expect(panel.get_by_text("1,01 EUR", exact=True)).to_be_visible()
                    assert panel.locator('[title^="Exaktes Delta:"]').get_attribute("title").startswith("Exaktes Delta: 0.001")
                    panel.locator(".filingSnapshotDeltaTable").evaluate("table => table.scrollLeft = table.scrollWidth")
                    expect(panel.get_by_text("0,01 EUR", exact=True)).to_be_in_viewport()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                assert errors == [], errors
                page.screenshot(path=str(output / f"{state}-{width}.png"), full_page=True)
                page.close()
        browser.close()
    print(json.dumps({"passed": True, "synthetic": True, "viewports": [390, 768, 1280, 1440], "external_requests": 0, "screenshots": str(output)}))


if __name__ == "__main__":
    main()
