"""Echte main.tsx mit synthetischen Archivantworten, ohne Server oder echte API.

CI nutzt standardmaessig den Script-Checkout; --source-root prueft einen anderen
Checkout ausschliesslich lesend. ZIP-Buttons werden nur fokussiert, nie geklickt.
"""
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright


WIDTHS = (390, 768, 1280, 1440)
STATES = ("archived", "mixed_policy", "current_blocked", "no_run")
ORIGIN = "http://synthetic.invalid"
LATEST = "/api/v1/divorce/valuation-runs/latest"
ZIP = "/api/v1/divorce/valuation-runs/valuation-synthetic-archive/evidence/stichtag-zugewinn-dossier.zip"
STAMP = "2026-11-15T10:00:00Z"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def payloads(state):
    archived = state in {"archived", "mixed_policy"}
    gate = {"strict_ready": archived, "same_day_price_count": 1, "prior_day_price_count": 0,
            "stale_price_count": 0, "missing_price_count": 0, "accepted_review_asset_count": 0,
            "unverified_price_time_count": 0 if archived else 1, "affected_assets": ["SYNTHETIC"],
            "findings": ["Synthetischer Zeitbeleg offen."] if not archived else []}
    if not archived:
        gate.update(price_time_policy_id="stichtag-temporal-evidence", price_time_policy_version=1)
    report = {"generated_at": STAMP, "stichtage": {"separation_date": "2025-06-13", "end_asset_date": "2026-07-24",
              "timezone": "Europe/Berlin", "court_evidence_status": "pending_document",
              "court_evidence_note": "Synthetischer Nachweis, keine echten Finanzdaten."},
              "cutoff_price_gate": deepcopy(gate), "valuation_price_gate": deepcopy(gate),
              "accounts": [], "live_reconciliation": [], "cash_flows": [], "caveats": [],
              "marital_pre_cutoff": {}, "post_cutoff_direct_eur_invest": {}, "post_cutoff_all_lots": {},
              "inheritance_origin_gate": {}, "capital_flow_gate": {}, "bmf_tax_boundary": {},
              "legal_note": "Ausschliesslich synthetische Browserfixture.", "methodology": "synthetic"}
    for key in ("cutoff_portfolio_value_eur", "valuation_portfolio_value_eur", "valuation_review_value_eur",
                "valuation_dust_value_eur", "valuation_value_without_review_assets_eur", "gross_portfolio_change_eur",
                "gross_portfolio_change_without_review_assets_eur", "net_external_invest_since_cutoff_eur",
                "adjusted_gain_loss_excluding_new_invest_eur", "adjusted_gain_loss_without_review_assets_eur"):
        report[key] = "0"
    run = None if state == "no_run" else {
        "run_id": "valuation-synthetic-archive", "generated_at": STAMP, "status": "strict_ready" if archived else "blocked",
        "strict_ready": archived, "cutoff_price_gate": deepcopy(gate), "valuation_price_gate": deepcopy(gate),
        "cutoff_at": "2025-06-13T00:00:00Z", "valuation_at": "2026-07-24T00:00:00Z",
        "cutoff_value_eur": "0", "valuation_value_eur": "0", "gross_change_eur": "0", "external_invest_eur": "0",
        "adjusted_gain_loss_eur": "0", "fifo_checkpoints": [], "findings": [], "next_actions": [],
        "source_registry_status": "synthetic", "source_registry_strict_ready": False, "source_accounts": [],
        "semantic_sha256": "a" * 64, "methodology": "synthetic",
        "evidence_files": [{"kind": "evidence_package", "download_url": ZIP, "filename": "synthetic-archive.zip"}],
        "summary": deepcopy(report),
    }
    if state == "mixed_policy":
        for key in ("cutoff_price_gate", "valuation_price_gate"):
            run[key].update(price_time_policy_id="stichtag-temporal-evidence", price_time_policy_version=1)
    as_of = {"generated_at": STAMP, "gate": gate, "candidates": [], "material_assets_count": 1,
             "fetchable_count": 0, "not_configured_count": 0, "time_review_count": 0 if archived else 1,
             "methodology": "Synthetische Referenz ohne automatischen Abruf."}
    return report, run, as_of


def bundle_app(source, modules):
    # Wie check_ux_browser_v2: echte App, WorkspaceFixture; kein React-Mock.
    options = {"entryPoints": ["src/main.tsx"], "absWorkingDir": str(source / "frontend"), "nodePaths": [str(modules)],
               "bundle": True, "write": False, "format": "iife", "outdir": "/virtual", "jsx": "automatic",
               "define": {"import.meta.env.VITE_API_BASE": json.dumps(ORIGIN)}}
    code = f'''import {{build}} from {json.dumps((modules / "esbuild/lib/main.js").as_uri())};
const r=await build({json.dumps(options)});
process.stdout.write(JSON.stringify(Object.fromEntries(r.outputFiles.map(f=>[f.path.endsWith(".css")?"css":"js",f.text]))));'''
    return json.loads(subprocess.check_output(["node", "--input-type=module", "-e", code], text=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--source-root", type=Path, default=root)
    parser.add_argument("--node-modules", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--browser-executable")
    args = parser.parse_args()
    source = args.source_root.resolve()
    modules = (args.node_modules or source / "frontend/node_modules").resolve()
    output = (args.output or Path(tempfile.mkdtemp(prefix="steuerreport-time-archive-"))).resolve()
    if not (output.is_relative_to(Path("/tmp")) or output.is_relative_to(root / "var")):
        parser.error("Ausgabe nur unter /tmp oder Script-Checkout/var")
    output.mkdir(parents=True, exist_ok=True)
    main_path = source / "frontend/src/main.tsx"
    main_sha = sha(main_path)
    sys.dont_write_bytecode = True
    helper = source / "scripts/ux_workspace_fixtures.py"
    spec = importlib.util.spec_from_file_location("archive_workspace_fixtures", helper)
    fixture_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture_module)
    assets = bundle_app(source, modules)
    html = '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/app.css"></head><body><div id="root"></div><script src="/app.js"></script></body></html>'
    completed, requests, blocked, errors, downloads = [], [], [], [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.browser_executable)
        for width in WIDTHS:
            for state in STATES:
                fixture = fixture_module.WorkspaceFixture()
                fixture.fresh = True
                report, run, as_of = payloads(state)
                before = len(requests)
                context = browser.new_context(viewport={"width": width, "height": 1000}, device_scale_factor=1,
                                              service_workers="block", reduced_motion="reduce")
                page = context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("download", lambda download: downloads.append(download.suggested_filename))

                def route(route):
                    request = route.request
                    url = urlsplit(request.url)
                    if url.scheme != "http" or url.netloc != "synthetic.invalid" or request.method != "GET":
                        blocked.append({"method": request.method, "url": request.url})
                        route.abort()
                    elif url.path == "/":
                        route.fulfill(content_type="text/html", body=html)
                    elif url.path in {"/app.js", "/app.css"}:
                        route.fulfill(content_type="text/css" if url.path.endswith("css") else "text/javascript",
                                      body=assets["css" if url.path.endswith("css") else "js"])
                    elif url.path.startswith("/api/"):
                        requests.append({"method": request.method, "path": url.path, "query": parse_qs(url.query)})
                        if url.path == LATEST:
                            fixture.send(route, run)
                        elif url.path == "/api/v1/divorce/equalization-summary":
                            fixture.send(route, report)
                        elif url.path == "/api/v1/prices/as-of-gate":
                            fixture.send(route, as_of)
                        elif url.path == "/api/v1/health":
                            fixture.send(route, {"app_version": "synthetic-test", "status": "ok"})
                        elif not fixture.handle(route):
                            blocked.append({"method": request.method, "url": request.url})
                            route.abort()
                    else:
                        blocked.append({"method": request.method, "url": request.url})
                        route.abort()

                page.route("**/*", route)
                page.goto(ORIGIN + "/#zugewinn", wait_until="networkidle")
                assert page.evaluate("document.compatMode") == "CSS1Compat"
                panel = page.locator(".valuationControlPanel")
                expect(panel.get_by_text("Stichtagsdossier festlegen", exact=True)).to_be_visible()
                status = panel.locator(".statusPill")
                expect(status).to_have_text({"archived": "Zeitbelegprüfung veraltet", "mixed_policy": "Zeitbelegprüfung veraltet", "current_blocked": "blocked", "no_run": "noch kein Lauf"}[state])
                assert "ok" not in (status.get_attribute("class") or "").split()
                gate_band = page.locator("section.valuationGateBand").filter(has=page.get_by_role("heading", name="Preis- und FIFO-Gates", exact=True))
                gate_items = gate_band.locator(".valuationGateGrid > .valuationGateItem")
                expect(gate_items).to_have_count(3)
                counters = []
                for index in range(2):
                    gate = gate_items.nth(index)
                    expect(gate.locator(".panelToolbar .statusPill")).to_have_text("offen")
                    expect(gate.locator(".statusPill.ok")).to_have_count(0)
                    metric = gate.locator(".metric").filter(has=page.get_by_text("Zeitbeleg offen", exact=True))
                    counters.append(metric.locator("strong").inner_text())
                    if state == "current_blocked":
                        expect(metric.locator("strong")).to_have_text("1")
                    elif state in {"archived", "mixed_policy"}:
                        expect(metric.locator("strong")).to_have_text("Nicht geprüft")
                expect(gate_band.locator(".valuationGateHeader .statusPill.ok")).to_have_count(0)
                button = panel.get_by_role("button", name="Letztes Dossier", exact=True)
                if state in {"archived", "mixed_policy"}:
                    warning = panel.get_by_role("status")
                    expect(warning).to_contain_text("ohne aktuelle Zeitbelegprüfung")
                    expect(warning).to_contain_text("nicht als aktuelle Freigabe")
                    expect(warning).to_contain_text("nur ausdrücklich erstellt")
                    expect(page.get_by_text("Archivierter Prüfstand ohne aktuelle Zeitbelegprüfung", exact=False)).to_have_count(2)
                    expect(button).to_be_enabled()
                    button.scroll_into_view_if_needed()
                    button.focus()
                    expect(button).to_be_focused()
                    expect(button).to_be_in_viewport()
                    expect(warning).to_be_in_viewport()
                    if state == "archived":
                        page.screenshot(path=str(output / f"archive-{width}.png"))
                else:
                    expect(panel.get_by_role("status")).to_have_count(0)
                    expect(page.get_by_text("Archivierter Prüfstand ohne aktuelle Zeitbelegprüfung", exact=False)).to_have_count(0)
                    if state == "no_run":
                        expect(button).to_have_count(0)
                layout = page.evaluate("""() => ({viewport:innerWidth, page:document.documentElement.scrollWidth, scrollX,
                  panel:document.querySelector('.valuationControlPanel').getBoundingClientRect().toJSON(),
                  controls:[...document.querySelectorAll('.valuationControlPanel label, .valuationControlPanel input, .valuationControlPanel button')].map(el=>({
                    tag:el.tagName,text:el.textContent.slice(0,80),box:el.getBoundingClientRect().toJSON(),
                    minWidth:getComputedStyle(el).minWidth,width:getComputedStyle(el).width})),
                  parents:[document.querySelector('.valuationControlPanel'),document.querySelector('.valuationControlPanel').parentElement].map(el=>({
                    cls:el.className,width:getComputedStyle(el).width,minWidth:getComputedStyle(el).minWidth,
                    cols:getComputedStyle(el).gridTemplateColumns})),
                  outside:[...document.body.querySelectorAll('*')].map(el=>({cls:el.className,tag:el.tagName,
                    box:el.getBoundingClientRect().toJSON(),text:el.textContent.slice(0,70),
                    visible:el.getClientRects().length>0})).filter(el=>el.visible&&el.box.right>innerWidth+1).slice(0,12),
                  wide:[...document.querySelectorAll('.content *, .valuationControlPanel *')].map(el=>({
                    tag:el.tagName, cls:el.className, width:el.getBoundingClientRect().width,
                    text:el.textContent.slice(0,80)})).filter(el=>el.width>innerWidth).slice(0,8)})""")
                assert layout["page"] <= width and layout["scrollX"] == 0, layout
                assert layout["panel"]["left"] >= 0 and layout["panel"]["right"] <= width, layout
                own_requests = requests[before:]
                latest = [entry for entry in own_requests if entry["path"] == LATEST]
                assert latest and all(entry["query"] == {"include_archived": ["true"]} for entry in latest), latest
                assert not any(".zip" in entry["path"] or "rebuild" in entry["path"] for entry in own_requests)
                assert not blocked, blocked
                assert not errors, errors
                assert not downloads, downloads
                completed.append({"width": width, "state": state, "latest_gets": len(latest), "time_counters": counters, "layout": layout})
                context.close()
        browser.close()
    assert sha(main_path) == main_sha, "main.tsx waehrend des Tests geaendert; erneut pruefen"
    result = {"synthetic": True, "real_main_tsx": True, "source_root": str(source), "main_sha256": main_sha,
              "fixture_helper_sha256": sha(helper), "script_sha256": sha(Path(__file__).resolve()),
              "cases": len(completed), "results": completed, "post_requests": 0, "external_requests": 0,
              "automatic_recalculations": 0, "downloads_started": 0, "screenshots": str(output),
              "legacy_counter_assertion": "Nicht geprueft statt Default-Null wird fuer beide Legacy-Gates geprueft."}
    (output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(json.dumps({key: value for key, value in result.items() if key != "results"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
