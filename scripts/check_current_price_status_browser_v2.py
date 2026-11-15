"""Isolierter Browsernachweis fuer Current und historische Direktabruf-Statusauskunft.

Nur synthetische HTTP-Antworten, kein Hostserver, Backend oder Anbieterzugriff.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


KINDS = ("current_portfolio", "historical")
WIDTHS = (390, 768, 1280, 1440)
KEYS = {
    "current_portfolio": "steuerreport:current-price-request",
    "historical": "steuerreport:external-historical-price-request",
}
TITLES = {
    "current_portfolio": "Portfolio-Preisauftrag prüfen",
    "historical": "Historischer Direktabruf: Preisauftrag prüfen",
}
PATHS = {
    "/api/v1/prices/backfill/current-portfolio/status": "current_portfolio",
    "/api/v1/prices/backfill/external/status": "historical",
}
IDS = {
    "current_portfolio": "11111111-1111-4111-8111-111111111111",
    "historical": "22222222-2222-4222-8222-222222222222",
}
ALTERNATE = "33333333-3333-4333-8333-333333333333"
MODERN_KEY = "steuerreport:historical-price-request"
LOCATION = "http://synthetic.invalid/#portfolio?tab=prices&asset=SYNTHETIC&year=2024"
ERROR = "Auftragsstatus nicht sicher lesbar"
PIPELINES = {
    "not_started": "Pipeline damals nicht gestartet.",
    "running_or_interrupted": "Pipelinebeginn vorgemerkt; Lauf und Abschluss nicht bestätigt.",
    "completed": "Pipeline damals abgeschlossen.",
    "failed": "Pipeline fehlgeschlagen; Folgen unbekannt oder teilweise.",
}
BASE_SCENARIOS = (
    "recorded_legacy", "recorded", "recorded_failed", "recorded_not_started", "recorded_no_result",
    "checkpoint_no_hash", "checkpoint_not_started", "checkpoint_running_or_interrupted",
    "checkpoint_completed", "checkpoint_failed", "checkpoint_empty", "checkpoint_long",
    "unknown_or_running", "not_found", "error", "network_error", "malformed", "invalid_status", "missing_checkpoint",
    "invalid_kind", "invalid_version", "invalid_date", "invalid_pipeline", "invalid_hash",
    "duplicate_ids", "over_cap", "recorded_unknown_pipeline",
)
REGRESSION_SCENARIOS = (
    "recorded_no_result", "recorded_missing_result", "checkpoint_completed", "checkpoint_failed",
    "checkpoint_no_hash", "checkpoint_null_hash", "recorded_no_hash", "recorded_hash_without_checkpoint",
    "naive_date", "non_utc_date", "invalid_calendar_date", "non_uuid_ids", "noncanonical_ids", "newline_id",
    "duplicate_ids", "empty_running", "empty_completed", "empty_failed", "checkpoint_with_result",
    "recorded_id_mismatch", "recorded_id_order_mismatch", "recorded_count_mismatch", "recorded_phase_mismatch",
    "recorded_unknown_pipeline", "recorded_running_pipeline", "recorded_nonempty_not_started",
    "recorded_empty_completed", "recorded_empty_failed", "recorded_wrong_kind", "recorded_dry_run",
    "recorded_unconfirmed_journal", "recorded_missing_pipeline", "recorded_wrong_effects",
    "unknown_result", "unknown_checkpoint", "unknown_hash", "not_found_result", "not_found_checkpoint", "not_found_hash",
    "extra_checkpoint_field", "array_checkpoint", "uppercase_hash", "newline_hash",
    "recorded_failed_with_pipeline", "recorded_not_started_with_pipeline", "recorded_error_envelope",
)
EXTRA_VALID_SCENARIOS = ("checkpoint_utc_offset", "checkpoint_microseconds")
INVALID_SCENARIOS = frozenset(REGRESSION_SCENARIOS) | {
    "error", "network_error", "malformed", "invalid_status", "missing_checkpoint", "invalid_kind", "invalid_version",
    "invalid_date", "invalid_pipeline", "invalid_hash", "over_cap",
}


def price_ids(count):
    return [f"00000000-0000-4000-8000-{index + 10:012x}" for index in range(count)]


def result_for(kind, phase="completed"):
    ids = [] if phase == "not_started" else price_ids(2)
    return {
        "operation_kind": kind, "pipeline_status": phase,
        "pipeline_effects": {"completed": "completed", "failed": "unknown_or_partial", "not_started": "not_started"}[phase],
        "imported_prices": len(ids), "failed": 1, "skipped": 3, "stored_price_ids": ids,
        "dry_run": False, "planned_jobs": 6, "attempted": 3,
        "configured_assets": ["SYNTHETIC"], "asset_filter": [], "jobs": [],
        "pipeline": {"normalized_events": 0, "balance_entries": 0, "flow_entries": 0, "tax_lines": 0,
                     "derivative_lines": 0, "review_issues_open": 0, "allow_export": False} if phase == "completed" else None,
        "result_journal_status": "recorded",
        **({"portfolio_assets_count": 1, "priced_at": "2026-11-15T12:00:00Z"}
           if kind == "current_portfolio" else {"requirements_count": 1}),
    }


def response_for(kind, scenario):
    recorded = scenario.startswith("recorded")
    data = {
        "status": "recorded" if recorded else "checkpointed",
        "explanation": "Synthetische Statusauskunft, keine Finanzdaten.",
        "result": None,
    }
    if recorded:
        phase = {"recorded_failed": "failed", "recorded_empty_failed": "failed", "recorded_not_started": "not_started",
                 "recorded_failed_with_pipeline": "failed", "recorded_not_started_with_pipeline": "not_started"}.get(scenario, "completed")
        data["result"] = result_for(kind, phase)
    if scenario.startswith("unknown_") or scenario.startswith("not_found"):
        data["status"] = "not_found" if scenario.startswith("not_found") else "unknown_or_running"
    if (data["status"] not in {"unknown_or_running", "not_found"} and scenario not in {
        "recorded_legacy", "recorded_unknown_pipeline", "recorded_running_pipeline", "recorded_hash_without_checkpoint",
    }) or scenario in {"unknown_checkpoint", "not_found_checkpoint"}:
        count = (1000 if kind == "historical" else 250) if scenario == "checkpoint_long" else 2
        if scenario in {"checkpoint_empty", "recorded_not_started", "recorded_not_started_with_pipeline", "empty_running", "empty_completed", "empty_failed",
                        "recorded_empty_completed", "recorded_empty_failed"}:
            count = 0
        pipeline = data["result"]["pipeline_status"] if recorded else scenario.removeprefix("checkpoint_")
        if scenario.startswith("empty_"):
            pipeline = "running_or_interrupted" if scenario == "empty_running" else scenario.removeprefix("empty_")
        checkpoint = {
            "format_version": 1, "operation_kind": kind,
            "stored_at": "2026-11-15T12:34:56Z",
            "stored_price_ids": price_ids(count),
            "pipeline_status": pipeline if pipeline in PIPELINES else "not_started",
        }
        data["checkpoint"] = checkpoint
        if scenario == "invalid_kind":
            checkpoint["operation_kind"] = "historical" if kind == "current_portfolio" else "current_portfolio"
        elif scenario == "invalid_version":
            checkpoint["format_version"] = 2
        elif scenario == "invalid_pipeline":
            checkpoint["pipeline_status"] = "unconfirmed"
        elif scenario == "invalid_date":
            checkpoint["stored_at"] = "kein-datum"
        elif scenario == "duplicate_ids":
            checkpoint["stored_price_ids"] = price_ids(1) * 2
        elif scenario == "over_cap":
            checkpoint["stored_price_ids"] = price_ids((1000 if kind == "historical" else 250) + 1)
        elif scenario == "naive_date":
            checkpoint["stored_at"] = "2026-11-15T12:34:56"
        elif scenario == "non_utc_date":
            checkpoint["stored_at"] = "2026-11-15T12:34:56+01:00"
        elif scenario == "checkpoint_utc_offset":
            checkpoint["stored_at"] = "2026-11-15T12:34:56+00:00"
        elif scenario == "checkpoint_microseconds":
            checkpoint["stored_at"] = "2026-11-15T12:34:56.123456Z"
        elif scenario == "invalid_calendar_date":
            checkpoint["stored_at"] = "2026-02-30T12:34:56Z"
        elif scenario == "non_uuid_ids":
            checkpoint["stored_price_ids"] = ["synthetic-not-a-uuid"]
        elif scenario == "noncanonical_ids":
            checkpoint["stored_price_ids"] = [price_ids(1)[0].upper()]
        elif scenario == "newline_id":
            checkpoint["stored_price_ids"] = [price_ids(1)[0] + "\n"]
        elif scenario == "extra_checkpoint_field":
            checkpoint["unexpected"] = "synthetic-extra"
        elif scenario == "array_checkpoint":
            data["checkpoint"] = []
    if scenario in {"recorded_unknown_pipeline", "recorded_running_pipeline"}:
        data["result"]["pipeline_status"] = "future_unknown_status" if scenario == "recorded_unknown_pipeline" else "running_or_interrupted"
    if scenario in {"recorded_no_result", "recorded_missing_result"}:
        if scenario == "recorded_no_result":
            data["result"] = None
        else:
            del data["result"]
    if scenario in {"unknown_result", "not_found_result", "checkpoint_with_result"}:
        data["result"] = result_for(kind)
    if scenario == "recorded_id_mismatch":
        data["result"]["stored_price_ids"] = price_ids(3)[1:]
    elif scenario == "recorded_id_order_mismatch":
        data["result"]["stored_price_ids"].reverse()
    elif scenario == "recorded_count_mismatch":
        data["result"]["imported_prices"] = 1
    elif scenario == "recorded_phase_mismatch":
        data["result"] = result_for(kind, "failed")
    elif scenario == "recorded_nonempty_not_started":
        data["result"]["pipeline_status"] = "not_started"
        data["result"]["pipeline_effects"] = "not_started"
        data["result"]["pipeline"] = None
        data["checkpoint"]["pipeline_status"] = "not_started"
    elif scenario in {"recorded_empty_completed", "recorded_empty_failed"}:
        data["result"]["stored_price_ids"] = []
        data["result"]["imported_prices"] = 0
    elif scenario == "recorded_wrong_kind":
        data["result"]["operation_kind"] = "historical" if kind == "current_portfolio" else "current_portfolio"
    elif scenario == "recorded_dry_run":
        data["result"]["dry_run"] = True
    elif scenario == "recorded_unconfirmed_journal":
        data["result"]["result_journal_status"] = "unknown"
    elif scenario == "recorded_missing_pipeline":
        data["result"]["pipeline"] = None
    elif scenario == "recorded_wrong_effects":
        data["result"]["pipeline_effects"] = "not_started"
    elif scenario in {"recorded_failed_with_pipeline", "recorded_not_started_with_pipeline"}:
        data["result"]["pipeline"] = result_for(kind)["pipeline"]
    if "checkpoint" in data:
        data["checkpoint_sha256"] = hashlib.sha256(json.dumps(data["checkpoint"]).encode()).hexdigest()
    if scenario in {"checkpoint_no_hash", "recorded_no_hash"}:
        del data["checkpoint_sha256"]
    elif scenario == "checkpoint_null_hash":
        data["checkpoint_sha256"] = None
    elif scenario in {"recorded_hash_without_checkpoint", "unknown_hash", "not_found_hash"}:
        data["checkpoint_sha256"] = "a" * 64
    elif scenario == "invalid_hash":
        data["checkpoint_sha256"] = "synthetic-not-a-hash"
    elif scenario == "uppercase_hash":
        data["checkpoint_sha256"] = "A" * 64
    elif scenario == "newline_hash":
        data["checkpoint_sha256"] += "\n"
    if scenario == "missing_checkpoint":
        del data["checkpoint"]
    if scenario == "invalid_status":
        data = {"status": "finished", "explanation": "Kein gueltiger Status"}
    return {
        "status": "error" if scenario == "recorded_error_envelope" else "warning" if recorded else "ok", "errors": [],
        "warnings": [{"code": "synthetic_warning", "message": "Ein Preisabruf ist fehlgeschlagen."}] if recorded else [],
        "data": data,
    }


def assert_layout(page):
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Horizontaler Seitenueberlauf"
    assert page.evaluate("""() => [...document.querySelectorAll('section input, section button, section summary, section code, section time')]
      .filter(el => el.getClientRects().length).every(el => {
        const r = el.getBoundingClientRect();
        return r.left >= 0 && r.right <= innerWidth + 1 && el.scrollWidth <= el.clientWidth + 1;
      })"""), "Inhalt passt nicht ins native Viewport"
    assert page.url == LOCATION, "Statusauskunft hat Filter oder Rueckweg veraendert"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--node-modules", type=Path, help="Vorhandene Frontend-Abhaengigkeiten wiederverwenden")
    parser.add_argument("--browser-executable")
    parser.add_argument("--regressions-only", action="store_true", help="Gezielte Widersprueche gesammelt pruefen (Rotnachweis)")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    modules = (args.node_modules or root / "frontend/node_modules").resolve()
    harness = '''import React from "react";
import {createRoot} from "react-dom/client";
import {CurrentPriceRequestStatus,rememberCurrentPriceRequest,rememberHistoricalPriceRequest} from "./src/workspace/CurrentPriceRequestStatus";
const root=createRoot(document.getElementById("root"));
(window as any).rememberPriceRequest=rememberCurrentPriceRequest;
(window as any).rememberHistoricalPriceRequest=rememberHistoricalPriceRequest;
(window as any).mountStatus=(kind: "current_portfolio" | "historical" | null)=>root.render(
  <React.StrictMode>{kind && <CurrentPriceRequestStatus kind={kind}/>}</React.StrictMode>);
(window as any).mountBoth=()=>root.render(<React.StrictMode>
  <CurrentPriceRequestStatus/><CurrentPriceRequestStatus kind="historical"/>
</React.StrictMode>);
(window as any).mountBoth();'''
    code = f'''import {{build}} from {json.dumps((modules / "esbuild/lib/main.js").as_uri())};
const result=await build({{stdin:{{contents:{json.dumps(harness)},resolveDir:process.cwd(),loader:"tsx"}},nodePaths:[{json.dumps(str(modules))}],bundle:true,write:false,format:"iife",define:{{"import.meta.env.VITE_API_BASE":'""'}}}});
process.stdout.write(result.outputFiles[0].text);'''
    bundle = subprocess.check_output(["node", "--input-type=module", "-e", code], cwd=root / "frontend", text=True)
    styles = (root / "frontend/src/styles.css").read_text() + (root / "frontend/src/workspace/workspace.css").read_text()
    output = args.output or Path(tempfile.mkdtemp(prefix="steuerreport-price-status-browser-"))
    output = output.resolve()
    if not (output.is_relative_to(Path(tempfile.gettempdir()).resolve()) or output.is_relative_to(root / "var")):
        parser.error("Testbilder nur unter /tmp oder ignoriertem var ablegen")
    output.mkdir(parents=True, exist_ok=True)
    calls = []
    state = {kind: "recorded" for kind in KINDS}
    errors, unexpected, cases, regressions = [], [], [], []

    def route(route):
        request = route.request
        url = urlsplit(request.url)
        if request.url == "http://synthetic.invalid/":
            route.fulfill(content_type="text/html", body=f'<html lang="de"><meta name="viewport" content="width=device-width,initial-scale=1"><style>{styles}</style><main class="wsPriceWorkspace" id="root" style="padding:16px;max-width:1100px;margin:auto"></main><script>{bundle}</script></html>')
        elif url.netloc == "synthetic.invalid" and url.path in PATHS:
            kind = PATHS[url.path]
            assert not url.query and request.method == "POST"
            assert request.headers["content-type"] == "application/json"
            assert set(request.post_data_json) == {"request_id"}
            assert request.post_data_json["request_id"] in {*IDS.values(), ALTERNATE}
            calls.append((kind, request.post_data_json))
            if state[kind] == "error":
                route.fulfill(status=500, body='{"detail":"synthetic-secret /private/synthetic-path"}')
            elif state[kind] == "malformed":
                route.fulfill(content_type="application/json", body="kein JSON")
            elif state[kind] == "network_error":
                route.abort("failed")
            else:
                route.fulfill(content_type="application/json", body=json.dumps(response_for(kind, state[kind])))
        else:
            unexpected.append(request.url)
            route.abort()

    with sync_playwright() as browser:
        chromium = browser.chromium.launch(executable_path=args.browser_executable)
        for width in WIDTHS:
            page = chromium.new_page(viewport={"width": width, "height": 900})
            page.on("pageerror", lambda error: errors.append(str(error)))
            # Echte Fetch-Antwort, nur das Lesen des Bodys wird kontrolliert verzoegert.
            page.add_init_script("""(() => {
              const originalFetch=window.fetch.bind(window);
              window.heldBodies=[]; window.abortCount=0; window.holdBody=false; window.resumedBodies=0;
              window.fetch=async (...args) => {
                args[1]?.signal?.addEventListener('abort', () => window.abortCount++);
                const response=await originalFetch(...args);
                if (window.holdBody) {
                  window.holdBody=false;
                  const json=response.json.bind(response);
                  response.json=async () => {
                    const body=await json();
                    await new Promise(resolve => window.heldBodies.push(resolve));
                    window.resumedBodies++; return body;
                  };
                }
                return response;
              };
              window.releaseBodies=()=>window.heldBodies.splice(0).forEach(resolve=>resolve());
            })();""")
            page.route("**/*", route)
            page.goto(LOCATION)
            for kind in KINDS:
                region = page.get_by_role("region", name=TITLES[kind], exact=True)
                expect(region.get_by_label("Auftragskennung", exact=True)).to_be_visible()
                expect(region.get_by_role("button")).to_be_disabled()
            assert calls == []
            page.evaluate("key => sessionStorage.setItem(key, 'synthetic-modern-preview')", MODERN_KEY)
            for kind, function in (("current_portfolio", "rememberPriceRequest"), ("historical", "rememberHistoricalPriceRequest")):
                page.evaluate("([fn, id]) => window[fn](id)", [function, IDS[kind]])
                page.evaluate("fn => window[fn]('invalid-and-never-stored')", function)
                page.evaluate("([fn, id]) => window[fn](id + '\\n')", [function, IDS[kind]])
            page.reload()
            assert calls == []
            for kind in KINDS:
                region = page.get_by_role("region", name=TITLES[kind], exact=True)
                field = region.get_by_label("Auftragskennung", exact=True)
                button = region.get_by_role("button", name="Auftragsstatus lesen", exact=True)
                expect(field).to_have_value(IDS[kind])
                field.fill("ungueltig")
                expect(field).to_have_attribute("aria-invalid", "true")
                expect(button).to_be_disabled()
                field.fill(IDS[kind])
                scenarios = REGRESSION_SCENARIOS if args.regressions_only else tuple(dict.fromkeys((*BASE_SCENARIOS, *REGRESSION_SCENARIOS, *EXTRA_VALID_SCENARIOS)))
                for scenario in scenarios:
                    state[kind] = scenario
                    before = len(calls)
                    button.click()
                    expect(button).to_be_enabled()
                    assert calls[before:] == [(kind, {"request_id": IDS[kind]})]
                    if args.regressions_only:
                        if region.get_by_text(ERROR, exact=False).count() != 1 or region.locator("details, strong").count() != 0:
                            regressions.append({"width": width, "kind": kind, "scenario": scenario, "rendered": region.inner_text()})
                            if width == 390 and kind == "current_portfolio" and scenario in {
                                "recorded_no_result", "checkpoint_completed", "checkpoint_no_hash", "naive_date", "non_uuid_ids",
                                "recorded_failed_with_pipeline", "recorded_not_started_with_pipeline", "recorded_error_envelope",
                            }:
                                page.screenshot(path=str(output / f"red-{scenario}.png"), full_page=True)
                        cases.append((width, kind, scenario))
                        continue
                    if scenario in INVALID_SCENARIOS:
                        expect(region.get_by_text(ERROR, exact=False)).to_be_visible()
                        expect(region.locator("details")).to_have_count(0)
                        expect(region.locator("strong")).to_have_count(0)
                        expect(region.get_by_text("heutige Preisgültigkeit", exact=False)).to_have_count(0)
                    elif scenario in {"unknown_or_running", "not_found"}:
                        expected = "Ausgang unbekannt oder Auftrag noch in Arbeit" if scenario == "unknown_or_running" else "Kein gespeicherter Auftrag"
                        expect(region.get_by_text(expected, exact=False)).to_be_visible()
                        expect(region.get_by_text("Damals gespeichert:", exact=False)).to_have_count(0)
                        expect(region.get_by_text("Pipeline damals abgeschlossen.", exact=False)).to_have_count(0)
                    else:
                        if scenario.startswith("recorded"):
                            expect(region.get_by_text("Finale damalige Antwort gespeichert.", exact=True)).to_be_visible()
                            expect(region.get_by_text("Fehlgeschlagen: 1", exact=False)).to_be_visible()
                            expect(region.get_by_text("Übersprungen: 3", exact=False)).to_be_visible()
                            expect(region.get_by_text("Ein Preisabruf ist fehlgeschlagen.", exact=True)).to_be_visible()
                        else:
                            expect(region.get_by_text("Preisspeicherung belegt; finale Antwort fehlt.", exact=True)).to_be_visible()
                        if scenario == "recorded_legacy":
                            expect(region.get_by_text("älteres Ergebnisjournal", exact=False)).to_be_visible()
                        else:
                            summary = region.get_by_text("Speicherbeleg und damalige Preis-IDs", exact=True)
                            summary.click()
                            expect(region.get_by_text("Formatversion: 1.", exact=False)).to_be_visible()
                            expect(region.locator("time")).to_have_text("2026-11-15T12:34:56.123Z" if scenario == "checkpoint_microseconds" else "2026-11-15T12:34:56.000Z")
                            expect(region.get_by_text("Checkpoint-SHA256", exact=False)).to_be_visible()
                            if scenario == "checkpoint_long":
                                ids = region.get_by_role("list", name="Damals gespeicherte Preis-IDs")
                                expect(ids.get_by_role("listitem")).to_have_count(1000 if kind == "historical" else 250)
                                assert ids.evaluate("el => el.clientHeight <= 260 && el.scrollHeight > el.clientHeight")
                                ids.focus()
                                page.keyboard.press("End")
                            if scenario == "checkpoint_empty":
                                expect(region.get_by_text("Bekannt leer:", exact=False)).to_be_visible()
                        if scenario.removeprefix("checkpoint_") in PIPELINES:
                            expect(region.get_by_text(PIPELINES[scenario.removeprefix("checkpoint_")], exact=False)).to_be_visible()
                        if scenario == "checkpoint_running_or_interrupted":
                            expect(region.get_by_text("Pipeline laufend", exact=False)).to_have_count(0)
                            expect(region.get_by_text("Pipeline läuft", exact=False)).to_have_count(0)
                        if scenario in {"recorded_failed", "recorded_not_started"}:
                            expect(region.get_by_text(PIPELINES[scenario.removeprefix("recorded_")], exact=False).first).to_be_visible()
                        expect(region.get_by_text("heutige Preisgültigkeit", exact=False)).to_be_visible()
                    assert_layout(page)
                    assert "synthetic-secret" not in page.locator("body").inner_text()
                    assert "/private/" not in page.locator("body").inner_text()
                    if scenario == "checkpoint_long" or (width in {390, 1440} and scenario in {"recorded", "checkpoint_empty", "error", "checkpoint_running_or_interrupted"}):
                        page.screenshot(path=str(output / f"{kind}-{scenario}-{width}.png"), full_page=True)
                    if (width, kind) in {(390, "current_portfolio"), (1440, "historical")} and scenario in {
                        "recorded_no_result", "checkpoint_completed", "checkpoint_no_hash", "naive_date", "non_uuid_ids",
                        "recorded_failed_with_pipeline", "recorded_not_started_with_pipeline", "recorded_error_envelope",
                    }:
                        page.screenshot(path=str(output / f"rejected-{kind}-{scenario}-{width}.png"), full_page=True)
                    cases.append((width, kind, scenario))

                if args.regressions_only:
                    continue
                # Antwort A kommt erst nach Kennungswechsel und neuer Antwort B zurueck.
                state[kind] = "recorded_legacy"
                page.evaluate("window.holdBody=true")
                button.click()
                page.wait_for_function("window.heldBodies.length === 1")
                expect(region.get_by_role("button", name="Status wird gelesen")).to_be_disabled()
                aborts = page.evaluate("window.abortCount")
                field.fill(ALTERNATE)
                state[kind] = "not_found"
                button.click()
                expect(region.get_by_text("Kein gespeicherter Auftrag", exact=False)).to_be_visible()
                resumed = page.evaluate("window.resumedBodies")
                page.evaluate("window.releaseBodies()")
                page.wait_for_function("before => window.resumedBodies > before", arg=resumed)
                expect(region.get_by_text("Finale damalige Antwort gespeichert.", exact=True)).to_have_count(0)
                assert page.evaluate("window.abortCount") > aborts
                function = "rememberPriceRequest" if kind == "current_portfolio" else "rememberHistoricalPriceRequest"
                page.evaluate("([fn, id]) => window[fn](id)", [function, IDS[kind]])
                expect(field).to_have_value(IDS[kind])

            if args.regressions_only:
                calls.clear()
                page.close()
                continue
            # Typwechsel am selben Component und Abbau brechen die alte Anfrage ab.
            page.evaluate("window.mountStatus('current_portfolio')")
            region = page.get_by_role("region", name=TITLES["current_portfolio"], exact=True)
            state["current_portfolio"] = "recorded_legacy"
            page.evaluate("window.holdBody=true")
            region.get_by_role("button", name="Auftragsstatus lesen").click()
            page.wait_for_function("window.heldBodies.length === 1")
            page.evaluate("window.mountStatus('historical')")
            expect(page.get_by_role("region", name=TITLES["historical"], exact=True)).to_be_visible()
            resumed = page.evaluate("window.resumedBodies")
            page.evaluate("window.releaseBodies()")
            page.wait_for_function("before => window.resumedBodies > before", arg=resumed)
            expect(page.get_by_text("Finale damalige Antwort gespeichert.", exact=True)).to_have_count(0)
            # Navigations-/Filterkontext bleibt ausserhalb der Statuskomponente.
            before = len(calls)
            page.evaluate("window.mountStatus(null); history.pushState({}, '', '#review')")
            page.go_back()
            page.evaluate("window.mountBoth()")
            for kind in KINDS:
                region = page.get_by_role("region", name=TITLES[kind], exact=True)
                expect(region.get_by_label("Auftragskennung", exact=True)).to_have_value(IDS[kind])
            assert len(calls) == before
            assert_layout(page)
            storage = page.evaluate("Object.fromEntries(Object.entries(sessionStorage))")
            assert set(storage) == {*KEYS.values(), MODERN_KEY}
            assert storage[MODERN_KEY] == "synthetic-modern-preview"
            assert all(len(storage[key]) == 36 for key in KEYS.values())
            # Sessionstorage-Ausfall verhindert weder Mount noch Event oder lesende Auskunft.
            before = len(calls)
            page.evaluate("window.mountStatus(null)")
            expect(page.get_by_role("region")).to_have_count(0)
            page.evaluate("""() => {
              for (const method of ['setItem', 'getItem'])
                Object.defineProperty(Storage.prototype, method, {value(){throw Error('synthetic-unavailable')}});
              window.mountBoth();
            }""")
            for kind, function in (("current_portfolio", "rememberPriceRequest"), ("historical", "rememberHistoricalPriceRequest")):
                region = page.get_by_role("region", name=TITLES[kind], exact=True)
                expect(region.get_by_label("Auftragskennung", exact=True)).to_have_value("")
                expect(region.get_by_role("button")).to_be_disabled()
                assert len(calls) == before
                page.evaluate("([fn, id]) => window[fn](id)", [function, IDS[kind]])
                expect(region.get_by_label("Auftragskennung", exact=True)).to_have_value(IDS[kind])
                state[kind] = "not_found"
                region.get_by_role("button", name="Auftragsstatus lesen").click()
                expect(region.get_by_text("Kein gespeicherter Auftrag", exact=False)).to_be_visible()
                before += 1
            calls.clear()
            page.close()
        chromium.close()
    assert not errors, errors
    assert not unexpected, unexpected
    if args.regressions_only:
        report = {"cases": len(cases), "failures": len(regressions), "details": regressions,
                  "component_sha256": hashlib.sha256((root / "frontend/src/workspace/CurrentPriceRequestStatus.tsx").read_bytes()).hexdigest()}
        (output / "regressions.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({"cases": len(cases), "failures": len(regressions), "report": str(output / "regressions.json")}))
        if regressions:
            raise SystemExit(1)
        return
    summary = {"synthetic": True, "viewports": list(WIDTHS), "cases": len(cases),
               "base_cases": len(BASE_SCENARIOS) * len(WIDTHS) * len(KINDS),
               "kinds": list(KINDS), "screenshots": str(output), "external_requests": 0,
               "provider_calls": 0, "pipeline_calls": 0, "unexpected_requests": 0,
               "component_sha256": hashlib.sha256((root / "frontend/src/workspace/CurrentPriceRequestStatus.tsx").read_bytes()).hexdigest()}
    (output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
