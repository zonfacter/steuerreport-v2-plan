"""Recent-UI mit echtem PriceWorkspace und kontrollierten Antworten, ohne Backend."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


BASE = "/api/v1/prices/historical"
ORIGIN = "http://synthetic.invalid"
LOCATION = ORIGIN + "/#portfolio?tab=prices&year=2024&asset=SOL"
WIDTHS = (390, 768, 1280, 1440)
NULL_FIELDS = ("created_at", "prices_count", "applied", "preview_sha256", "pending_count", "open_count",
               "parent_preview_id", "collection_complete", "manual")


def request_id(index):
    return f"00000000-0000-4000-8000-{index:012x}"


def verified(index, count=0, applied=False):
    return {"id": request_id(index), "status": "ready", "integrity_status": "verified", "error_code": None,
            "created_at": "2024-06-01T12:00:00Z", "prices_count": count, "applied": applied,
            "preview_sha256": "a" * 64, "pending_count": 0, "open_count": 0, "parent_preview_id": None,
            "collection_complete": True, "manual": False}


def unavailable(index, code="historical_price_preview_unavailable"):
    return {"id": request_id(index), "status": "unavailable", "integrity_status": "unavailable", "error_code": code,
            **dict.fromkeys(NULL_FIELDS)}


def full_preview(index, count=0, applied=False):
    return {**verified(index, count, applied), "requests_started": 0, "rows": [], "year_summary": [],
            "query": {"year": 2024, "assets": ["SOL"], "scope": "tax_required", "strategy": "standard", "max_requests": 2}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-modules", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--browser-executable")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    modules = (args.node_modules or root / "frontend/node_modules").resolve()
    output = (args.output or Path(tempfile.mkdtemp(prefix="steuerreport-recent-ui-"))).resolve()
    if not (output.is_relative_to(Path("/tmp")) or output.is_relative_to(root / "var")):
        parser.error("Testausgabe nur unter /tmp oder ignoriertem var ablegen")
    output.mkdir(parents=True, exist_ok=True)
    harness = '''import React from "react";
import {createRoot} from "react-dom/client";
import {PriceWorkspace} from "./src/workspace/PriceWorkspace";
createRoot(document.getElementById("root")).render(<React.StrictMode><PriceWorkspace onCurrentPrices={()=>{throw Error("unexpected-provider-action")}}/></React.StrictMode>);'''
    options = {"stdin": {"contents": harness, "resolveDir": str(root / "frontend"), "loader": "tsx"},
               "bundle": True, "write": False, "format": "iife", "jsx": "automatic", "nodePaths": [str(modules)],
               "define": {"import.meta.env.VITE_API_BASE": json.dumps(ORIGIN)}}
    code = f'''import {{build}} from {json.dumps((modules / "esbuild/lib/main.js").as_uri())};
const r=await build({json.dumps(options)});process.stdout.write(r.outputFiles[0].text);'''
    bundle = subprocess.check_output(["node", "--input-type=module", "-e", code], text=True)
    styles = (root / "frontend/src/styles.css").read_text() + (root / "frontend/src/workspace/workspace.css").read_text()
    document = f'<!doctype html><html lang="de"><meta name="viewport" content="width=device-width,initial-scale=1"><style>{styles}</style><main id="root" style="max-width:1100px;margin:auto;padding:16px"></main><script>{bundle}</script></html>'
    mixed = [verified(1), verified(2, 3, True), unavailable(3, "historical_price_apply_decision_invalid"),
             unavailable(4), unavailable(5, "historical_price_evidence_changed")]
    mixed[0]["status"] = "no_prices"
    cases, calls, blocked, errors = [], [], [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.browser_executable)
        for width in WIDTHS:
            state = {"data": [], "mode": "hold"}
            held = []
            details = {request_id(1): full_preview(1), request_id(2): full_preview(2, 3, True)}
            context = browser.new_context(viewport={"width": width, "height": 1000}, device_scale_factor=1,
                                          service_workers="block", reduced_motion="reduce")
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))

            def send_recent(route):
                if state["mode"] == "error":
                    route.fulfill(status=503, content_type="application/json", body='{"status":"error","data":null,"detail":"synthetic-secret /private/synthetic"}')
                else:
                    partial = isinstance(state["data"], list) and any(row.get("integrity_status") == "unavailable" for row in state["data"])
                    route.fulfill(content_type="application/json", body=json.dumps({"status": "warning" if partial else "ok", "data": state["data"],
                        "warnings": [{"code": "historical_price_recent_partial", "message": "Synthetischer Teilfehler"}] if partial else []}))

            def route(route):
                request, url = route.request, urlsplit(route.request.url)
                if url.netloc != "synthetic.invalid" or request.method != "GET":
                    blocked.append((request.method, request.url))
                    route.abort()
                elif url.path == "/":
                    route.fulfill(content_type="text/html", body=document)
                elif url.path == BASE + "/previews":
                    calls.append((request.method, url.path))
                    if state["mode"] == "hold":
                        held.append(route)
                    else:
                        send_recent(route)
                elif url.path == BASE + "/mappings":
                    calls.append((request.method, url.path))
                    route.fulfill(content_type="application/json", body='{"status":"ok","data":{}}')
                elif url.path.startswith(BASE + "/previews/") and url.path.rsplit("/", 1)[-1] in {request_id(n) for n in range(1, 7)}:
                    calls.append((request.method, url.path))
                    value = details.get(url.path.rsplit("/", 1)[-1])
                    route.fulfill(status=200 if value else 409, content_type="application/json", body=json.dumps({
                        "status": "ok" if value else "error", "data": value,
                        "errors": [] if value else [{"code": "historical_price_apply_decision_invalid", "message": "synthetic-secret"}]}))
                else:
                    blocked.append((request.method, request.url))
                    route.abort()

            page.route("**/*", route)
            page.goto(LOCATION, wait_until="domcontentloaded")
            summary = page.locator("summary").filter(has_text="Gespeicherte Preisvorschauen")
            summary.focus()
            page.keyboard.press("Enter")
            recent = page.get_by_role("region", name="Gespeicherte Preisvorschauen", exact=True)
            workspace = page.get_by_role("region", name="EUR-Preise ermitteln", exact=True)
            expect(recent).to_be_visible()
            expect(recent.get_by_text("Gespeicherte Preisvorschauen werden geladen.", exact=True)).to_be_visible()
            expect(recent.get_by_text("Noch keine gespeicherte Preisvorschau.", exact=True)).to_have_count(0)
            expect(recent.get_by_role("button", name="Liste wird gelesen", exact=True)).to_be_disabled()
            cases.append((width, "initial_loading"))
            state["mode"] = "ready"
            for pending in held:
                send_recent(pending)
            held.clear()
            expect(recent.get_by_text("Noch keine gespeicherte Preisvorschau.", exact=True)).to_be_visible()
            cases.append((width, "verified_empty"))

            def refresh(data=None, mode="ready"):
                state.update(data=data, mode=mode)
                recent.get_by_role("button", name="Liste aktualisieren", exact=True).click()
                expect(recent).to_have_attribute("aria-busy", "false")

            def row(index):
                return recent.get_by_role("listitem", name="Preisvorschau " + request_id(index), exact=True)

            def context_unchanged():
                expect(workspace.get_by_role("combobox", name="Jahr", exact=True)).to_have_value("2024")
                expect(workspace.get_by_role("textbox", name="Asset", exact=True)).to_have_value("SOL")
                assert page.url == LOCATION

            refresh(mode="error")
            expect(recent.get_by_role("alert")).to_be_visible()
            expect(recent.get_by_text("Noch keine gespeicherte Preisvorschau.", exact=True)).to_have_count(0)
            cases.append((width, "global_error_not_empty"))
            refresh(deepcopy(mixed))
            expect(recent.get_by_role("listitem")).to_have_count(5)
            expect(row(1).get_by_role("button", name="0 Preise", exact=False)).to_be_visible()
            expect(row(2).get_by_role("button", name="übernommen", exact=False)).to_be_visible()
            for index in (3, 4, 5):
                expect(row(index).get_by_text("Datum unbekannt", exact=False)).to_be_visible()
                assert "0 Preise" not in row(index).inner_text() and "Vorschau" not in row(index).get_by_role("button").inner_text()
                expect(row(index).get_by_text("Übernahme nicht bestätigt", exact=False)).to_be_visible()
            cases.append((width, "mixed_and_verified_zero"))
            tip = recent.get_by_role("button", name="Hilfe: Integrität gespeicherter Preisvorschauen", exact=True)
            tip.focus()
            expect(page.get_by_role("tooltip")).to_contain_text("keine Inhalts-, Methoden- oder Jahresfreigabe")
            box = page.get_by_role("tooltip").bounding_box()
            assert box and box["x"] >= 0 and box["x"] + box["width"] <= width
            page.keyboard.press("Escape")
            expect(page.get_by_role("tooltip")).to_have_count(0)
            cases.append((width, "keyboard_tooltip"))
            row(1).get_by_role("button").click()
            expect(workspace.get_by_role("heading", name="Gespeicherte Preisvorschau", exact=True)).to_be_visible()
            actor = workspace.get_by_label("Freigebende Person", exact=True)
            actor.fill("Synthetische Freigabe")
            approvals = [workspace.get_by_role("checkbox", name=label, exact=False) for label in ("Die ausgewiesenen EUR-Preise", "Die gezeigte Neuberechnung")]
            for approval in approvals:
                approval.check()

            def approvals_unchanged():
                expect(actor).to_have_value("Synthetische Freigabe")
                for approval in approvals:
                    expect(approval).to_be_checked()
                context_unchanged()

            state["mode"] = "hold"
            recent.get_by_role("button", name="Liste aktualisieren", exact=True).click()
            expect(recent.get_by_text("Vorheriger Listenstand", exact=False)).to_be_visible()
            expect(recent.get_by_text("Integrität und Importbindung geprüft.", exact=True)).to_have_count(0)
            expect(recent.get_by_role("listitem")).to_have_count(5)
            approvals_unchanged()
            state["mode"] = "error"
            for pending in held:
                send_recent(pending)
            held.clear()
            expect(recent.get_by_role("alert")).to_be_visible()
            expect(recent.get_by_text("Noch keine gespeicherte Preisvorschau.", exact=True)).to_have_count(0)
            approvals_unchanged()
            cases.append((width, "refresh_error_preserves_stale_context"))
            refresh(deepcopy(mixed))
            approvals_unchanged()
            refresh(deepcopy(mixed[2:]))
            expect(recent.get_by_text("Keine der gespeicherten Vorschauen ist derzeit prüfbar.", exact=False)).to_be_visible()
            expect(recent.get_by_text("Noch keine gespeicherte Preisvorschau.", exact=True)).to_have_count(0)
            approvals_unchanged()
            cases.append((width, "all_unavailable_not_empty"))
            before = len(calls)
            row(3).get_by_role("button").focus()
            page.keyboard.press("Enter")
            expect(recent.get_by_role("button", name="Liste aktualisieren", exact=True)).to_be_enabled()
            assert calls[before:] == [("GET", BASE + "/previews/" + request_id(3))]
            approvals_unchanged()
            cases.append((width, "failed_row_recheck_preserves_other_preview"))
            details[request_id(3)] = full_preview(3, 2)
            state["data"] = [verified(3, 2), *deepcopy(mixed[3:])]
            row(3).get_by_role("button").click()
            expect(row(3).get_by_role("button", name="2 Preise", exact=False)).to_be_visible()
            approvals_unchanged()
            cases.append((width, "restored_row_verified_after_get_only"))
            legacy = verified(6, 0, True)
            legacy.pop("integrity_status")
            refresh([legacy])
            expect(row(6).get_by_text("Ältere API-Antwort", exact=False)).to_be_visible()
            expect(row(6).get_by_text("Preisanzahl unbekannt", exact=False)).to_be_visible()
            assert "0 Preise" not in row(6).inner_text() and "übernommen" not in row(6).inner_text()
            cases.append((width, "legacy_not_verified"))
            for name, value in (("count_null", None), ("count_string", "0"), ("count_boolean", False)):
                refresh([{**verified(6), "prices_count": value}])
                expect(row(6).get_by_text("Preisanzahl unbekannt", exact=False)).to_be_visible()
                expect(row(6).get_by_text("Integrität und Importbindung geprüft.", exact=True)).to_have_count(0)
                cases.append((width, name))
            for name, changes in (("verified_without_hash", {"preview_sha256": None}),
                                  ("applied_unknown", {"applied": None}),
                                  ("applied_blocked", {"status": "blocked", "applied": True}),
                                  ("bad_pending_count", {"pending_count": False})):
                refresh([{**verified(6), **changes}])
                expect(row(6).get_by_text("Übernahme nicht bestätigt", exact=False)).to_be_visible()
                expect(row(6).get_by_text("Integrität und Importbindung geprüft.", exact=True)).to_have_count(0)
                cases.append((width, name))
            refresh([{**unavailable(6), "created_at": "1970-01-01T00:00:00Z", "prices_count": 0,
                      "applied": False, "error_code": "synthetic-secret /private/path"}])
            expect(row(6).get_by_text("Preisanzahl unbekannt", exact=False)).to_be_visible()
            assert "1970" not in row(6).inner_text()
            cases.append((width, "unavailable_dirty_metadata_suppressed"))
            for name, value in (("null_list", None), ("object_list", {}), ("duplicate_ids", [verified(6), verified(6)]),
                                ("unsafe_id", [{**verified(6), "id": "../../synthetic-secret"}])):
                refresh(value)
                expect(recent.get_by_role("alert")).to_be_visible()
                expect(recent.get_by_text("Noch keine gespeicherte Preisvorschau.", exact=True)).to_have_count(0)
                cases.append((width, name))
            refresh(deepcopy(mixed))
            approvals_unchanged()
            refresh([unavailable(1, "historical_price_apply_decision_invalid")])
            expect(workspace.get_by_role("heading", name="Prüfstand nicht mehr bestätigt", exact=True)).to_be_visible()
            for approval in approvals:
                expect(approval).not_to_be_checked()
            state["data"] = deepcopy(mixed)
            row(1).get_by_role("button").click()
            expect(workspace.get_by_role("heading", name="Gespeicherte Preisvorschau", exact=True)).to_be_visible()
            expect(row(1).get_by_role("button", name="0 Preise", exact=False)).to_be_visible()
            expect(actor).to_have_value("Synthetische Freigabe")
            for approval in approvals:
                expect(approval).not_to_be_checked()
            context_unchanged()
            cases.append((width, "selected_preview_integrity_recovery_no_auto_consent"))
            recent.scroll_into_view_if_needed()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            assert recent.evaluate("""el => [...el.querySelectorAll('li,button,p')].filter(n=>n.getClientRects().length).every(n=>{
              const r=n.getBoundingClientRect();return r.left>=0 && r.right<=innerWidth+1 && n.scrollWidth<=n.clientWidth+1})""")
            assert "synthetic-secret" not in recent.inner_text() and "/private/" not in recent.inner_text()
            page.screenshot(path=str(output / f"recent-mixed-{width}.png"), full_page=True)
            context.close()
        browser.close()
    assert not errors, errors
    assert not blocked, blocked
    assert all(method == "GET" for method, _ in calls)
    summary = {"synthetic": True, "component": "PriceWorkspace", "cases": len(cases), "viewports": list(WIDTHS),
               "get_requests": len(calls), "post_requests": 0, "provider_requests": 0, "external_requests": 0,
               "source_sha256": hashlib.sha256((root / "frontend/src/workspace/PriceWorkspace.tsx").read_bytes()).hexdigest(),
               "native_backend": False, "screenshots": str(output)}
    (output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
