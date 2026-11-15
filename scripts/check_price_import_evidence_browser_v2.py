"""Fokussierter Mockbrowser fuer die echte PriceImportEvidence-Komponente.

Keine Backend-/DB-Imports, keine Server und kein echter Originaldownload.
--prepare-only prueft nur Fixtures; --source-root waehlt den lesenden UI-Checkout.
"""
import argparse
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright


WIDTHS = (390, 768, 1280, 1440)
ORIGIN = "http://synthetic.invalid"
LOCATION = ORIGIN + "/#portfolio?tab=prices&year=2024&asset=SYNTHETIC"
BASE = "/api/v1/prices/historical/previews"
SUMMARY = "Originalzuordnung der übernommenen Preise"
SUCCESS = "Importbindung dieser Preis-ID bestätigt. Keine Preiszeit-, Methoden- oder Jahresfreigabe."
GROUP = "Originalbindung der Preiszeile"
UUID = re.compile(r"^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$")


def identifier(number):
    return f"00000000-0000-4000-8000-{number:012x}"


def bindings():
    return [{"price_id": identifier(101), "price_fingerprint": "a" * 64, "asset": "SYNTHETIC_A",
             "price_eur": "123.123456789012345678", "stored_reference_at": "2024-06-01T00:00:00+00:00"},
            {"price_id": identifier(102), "price_fingerprint": "b" * 64, "asset": "SYNTHETIC_B",
             "price_eur": "456.125", "stored_reference_at": "2024-06-02T00:00:00Z"}]


def props(preview=1):
    return {"previewId": identifier(preview), "version": 1, "bindings": bindings()}


def evidence(preview=1, price=101):
    binding = next(row for row in bindings() if row["price_id"] == identifier(price))
    sha = "c" * 64
    return {"format_version": 1, "status": "verified_import_binding", "integrity_scope": "selected_price_only",
            "preview_id": identifier(preview), "preview_sha256": "d" * 64, **binding,
            "stored_reference_at": binding["stored_reference_at"].replace("+00:00", "Z"),
            "strict_eligible": False, "admission_status": "not_reviewed", "observed_at": None,
            "price_published_at": None, "fx_published_at": None,
            "originals": [{"sha256": sha, "byte_length": 128, "filename": "synthetic-original.bin",
                           "download_url": f"{BASE}/{identifier(preview)}/prices/{identifier(price)}/evidence/{sha}"}],
            "explanation": "Synthetische Importbindung, keine fachliche Freigabe."}


def invalid_payloads():
    source = evidence()
    mutations = {
        "null_data": None, "empty_data": {},
        "wrong_preview": {**source, "preview_id": identifier(2)},
        "wrong_price": {**source, "price_id": identifier(102)},
        "wrong_fingerprint": {**source, "price_fingerprint": "e" * 64},
        "wrong_asset": {**source, "asset": "SYNTHETIC_OTHER"},
        "wrong_value": {**source, "price_eur": "999"},
        "wrong_reference": {**source, "stored_reference_at": "2024-06-01T00:00:01Z"},
        "naive_reference": {**source, "stored_reference_at": "2024-06-01T00:00:00"},
        "wrong_status": {**source, "status": "approved"},
        "wrong_scope": {**source, "integrity_scope": "entire_preview"},
        "strict_eligible": {**source, "strict_eligible": True},
        "wrong_admission": {**source, "admission_status": "approved"},
    }
    for name, originals in {
        "missing_originals": None, "empty_originals": [], "null_original": [None],
        "bad_hash": [{"sha256": "../../synthetic-secret", "byte_length": 1}],
        "zero_bytes": [{"sha256": "c" * 64, "byte_length": 0}],
        "negative_bytes": [{"sha256": "c" * 64, "byte_length": -1}],
        "string_bytes": [{"sha256": "c" * 64, "byte_length": "128"}],
        "boolean_bytes": [{"sha256": "c" * 64, "byte_length": True}],
        "oversized_bytes": [{"sha256": "c" * 64, "byte_length": 2 * 1024 * 1024 + 1}],
        "duplicate_original": deepcopy(source["originals"]) * 2,
    }.items():
        mutations[name] = {**source, "originals": originals}
    return mutations


def legacy_props():
    default = props()
    return {
        "missing_bindings": {"previewId": identifier(1)},
        "missing_version": {"previewId": identifier(1), "bindings": bindings()},
        "unknown_version": {**default, "version": 2},
        "empty_bindings": {**default, "bindings": []},
        "duplicate_binding": {**default, "bindings": bindings()[:1] * 2},
        "invalid_preview_id": {**default, "previewId": "../../synthetic-secret"},
        "invalid_price_id": {**default, "bindings": [{**bindings()[0], "price_id": "synthetic-not-uuid"}]},
        "invalid_fingerprint": {**default, "bindings": [{**bindings()[0], "price_fingerprint": "bad"}]},
        "naive_binding_time": {**default, "bindings": [{**bindings()[0], "stored_reference_at": "2024-06-01T00:00:00"}]},
    }


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(source, modules):
    harness = '''import React from "react";
import {createRoot} from "react-dom/client";
import {PriceImportEvidence} from "./src/workspace/PriceImportEvidence";
const root=createRoot(document.getElementById("root"));
(window as any).renderImport=(props:any)=>root.render(<React.StrictMode><section className="wsPage wsPriceWorkspace"><PriceImportEvidence {...props}/></section></React.StrictMode>);
(window as any).hideImport=()=>root.render(null);'''
    options = {"stdin": {"contents": harness, "resolveDir": str(source / "frontend"), "loader": "tsx"},
               "nodePaths": [str(modules)], "bundle": True, "write": False, "format": "iife", "jsx": "automatic",
               "define": {"import.meta.env.VITE_API_BASE": json.dumps(ORIGIN)}}
    code = f'''import {{build}} from {json.dumps((modules / "esbuild/lib/main.js").as_uri())};
const r=await build({json.dumps(options)});process.stdout.write(r.outputFiles[0].text);'''
    bundle = subprocess.check_output(["node", "--input-type=module", "-e", code], text=True)
    styles = (source / "frontend/src/styles.css").read_text() + (source / "frontend/src/workspace/workspace.css").read_text()
    return f'<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>{styles}</style><main id="root" style="max-width:1000px;margin:auto;padding:16px"></main><script>{bundle}</script></html>'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--source-root", type=Path, default=root)
    parser.add_argument("--node-modules", type=Path, default=root / "frontend/node_modules")
    parser.add_argument("--output", type=Path, default=root / "var/price-import-evidence-browser")
    parser.add_argument("--browser-executable")
    parser.add_argument("--prepare-only", action="store_true", help="Nur Fixture-Validierung und Testplan, kein UI-/Browserlauf")
    args = parser.parse_args()
    output, source = args.output.resolve(), args.source_root.resolve()
    if not output.is_relative_to(root / "var"):
        parser.error("Ausgabe ausschliesslich unter dem eigenen ignorierten var ablegen")
    output.mkdir(parents=True, exist_ok=True)
    malformed, old_formats = invalid_payloads(), legacy_props()
    assert all(UUID.fullmatch(row["price_id"]) and len(row["price_fingerprint"]) == 64 for row in bindings())
    assert datetime.fromisoformat(bindings()[0]["stored_reference_at"]) == datetime.fromisoformat(evidence()["stored_reference_at"])
    names = ["no_auto_get", "explicit_loading", "success_normalized_utc", "http_error_retry", "envelope_error",
             "invalid_json", "selection_late_response", "preview_late_response", "metadata_change_resets",
             "unmount_late_response", "bounded_download_url", "exact_quantity", "long_filename_layout",
             *malformed, *old_formats]
    plan = {"status": "prepared", "browser_executed": False, "source_root": str(source), "viewports": list(WIDTHS),
            "cases_planned": len(names) * len(WIDTHS), "scenarios": names, "script_sha256": fingerprint(Path(__file__))}
    (output / "plan.json").write_text(json.dumps(plan, indent=2))
    if args.prepare_only:
        print(json.dumps({key: value for key, value in plan.items() if key != "scenarios"}))
        return
    component = source / "frontend/src/workspace/PriceImportEvidence.tsx"
    if not component.is_file():
        parser.error("Komponente fehlt; nach UI-Integration --source-root auf den Koordinator-Checkout setzen")
    source_sha = fingerprint(component)
    dependencies = ["frontend/src/workspace/PriceImportEvidence.tsx", "frontend/src/workspace/Ui.tsx",
                    "frontend/src/workspace/resource.ts", "frontend/src/api-base.ts", "frontend/src/Help.tsx",
                    "frontend/src/styles.css", "frontend/src/workspace/workspace.css"]
    dependency_hashes = {name: fingerprint(source / name) for name in dependencies}
    document = build(source, args.node_modules.resolve())
    results, calls, blocked, javascript_errors = [], [], [], []
    events = output / "events.jsonl"
    events.write_text("")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.browser_executable)
        try:
            for width in WIDTHS:
                state = {"mode": "success", "data": None}
                context = browser.new_context(viewport={"width": width, "height": 1000}, device_scale_factor=1,
                                              service_workers="block", reduced_motion="reduce")
                page = context.new_page()
                page.set_default_timeout(5000)
                page.on("pageerror", lambda error: javascript_errors.append(str(error)))
                page.add_init_script("""(() => {
                  const fetch=window.fetch.bind(window);
                  window.delayImportBody=false; window.delayedBodies=[]; window.resumedBodies=0; window.importAborts=0;
                  window.fetch=async (...args)=>{
                    args[1]?.signal?.addEventListener('abort',()=>window.importAborts++);
                    const response=await fetch(...args);
                    if(window.delayImportBody){
                      window.delayImportBody=false; const json=response.json.bind(response);
                      response.json=async()=>{const body=await json();await new Promise(resolve=>window.delayedBodies.push(resolve));window.resumedBodies++;return body};
                    } return response;
                  };
                  window.releaseImportBodies=()=>window.delayedBodies.splice(0).forEach(resolve=>resolve());
                })();""")

                def intercept(route):
                    request, url = route.request, urlsplit(route.request.url)
                    if request.url == ORIGIN + "/" and request.method == "GET":
                        route.fulfill(content_type="text/html", body=document)
                        return
                    match = re.fullmatch(BASE + r"/([a-f0-9-]{36})/prices/([a-f0-9-]{36})/evidence", url.path)
                    if url.scheme != "http" or url.netloc != "synthetic.invalid" or request.method != "GET" or url.query or not match:
                        blocked.append({"method": request.method, "url": request.url})
                        route.abort()
                        return
                    preview, price = match.groups()
                    assert preview in {identifier(1), identifier(2)} and price in {identifier(101), identifier(102)}
                    calls.append({"method": request.method, "path": url.path})
                    data = evidence(1 if preview == identifier(1) else 2, 101 if price == identifier(101) else 102)
                    if state["mode"] == "invalid":
                        data = state["data"]
                    if state["mode"] == "bad_json":
                        route.fulfill(content_type="application/json", body="{")
                    else:
                        failure = state["mode"] in {"http_error", "envelope_error"}
                        route.fulfill(status=409 if state["mode"] == "http_error" else 200, content_type="application/json",
                                      body=json.dumps({"status": "error" if failure else "ok", "data": data,
                                          "errors": [{"code": "historical_price_binding_invalid", "message": "synthetic-secret"}] if failure else []}))

                page.route("**/*", intercept)
                page.goto(LOCATION)
                area = page.locator("details.wsTechnical").filter(has=page.get_by_text(SUMMARY, exact=True))
                selection = area.get_by_role("combobox", name="Übernommene Preiszeile", exact=True)
                button = area.get_by_role("button", name="Importbelege prüfen", exact=True)
                group = area.get_by_role("group", name=GROUP, exact=True)

                def reset(value=None):
                    page.evaluate("window.releaseImportBodies(); window.hideImport()")
                    expect(page.get_by_text(SUMMARY, exact=True)).to_have_count(0)
                    state.update(mode="success", data=None)
                    page.evaluate("value=>window.renderImport(value)", props() if value is None else value)
                    summary = page.get_by_text(SUMMARY, exact=True)
                    summary.focus()
                    page.keyboard.press("Enter")
                    expect(area).to_have_attribute("open", "")

                def ready():
                    expect(group.get_by_text(SUCCESS, exact=True)).to_be_visible()
                    expect(group.get_by_text("Beobachtungs- und Veröffentlichungszeiten: nicht geprüft.", exact=True)).to_be_visible()
                    expect(button).to_be_enabled()

                def reject():
                    expect(area.get_by_role("alert")).to_be_visible()
                    expect(group).to_have_count(0)
                    expect(area.get_by_role("link")).to_have_count(0)
                    assert "synthetic-secret" not in area.inner_text()

                def assert_layout():
                    assert page.evaluate("document.compatMode === 'CSS1Compat'")
                    overflow = area.evaluate("""el=>[...el.querySelectorAll('p,li,a,button,select,small,code')].filter(n=>n.getClientRects().length).flatMap(n=>{
                      const r=n.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth+1&&n.scrollWidth<=n.clientWidth+1?[]:
                        [{tag:n.tagName,left:r.left,right:r.right,clientWidth:n.clientWidth,scrollWidth:n.scrollWidth,text:n.textContent.slice(0,200)}]})""")
                    assert not overflow, json.dumps({"overflow": overflow}, ensure_ascii=False)
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "document_overflow"
                    assert page.url == LOCATION

                def run_case(name, action):
                    record = {"width": width, "case": name, "status": "passed"}
                    try:
                        before_mount = len(calls)
                        reset()
                        action()
                        if name == "no_auto_get":
                            page.evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))")
                            assert len(calls) == before_mount, "GET without explicit check, including mount"
                        assert not blocked, blocked
                        assert not javascript_errors, javascript_errors
                    except Exception as error:
                        record.update(status="failed", error=str(error)[:3000])
                        page.screenshot(path=str(output / f"failure-{name}-{width}.png"), full_page=True)
                        (output / f"failure-{name}-{width}.html").write_text(area.evaluate("el=>el.outerHTML"))
                    results.append(record)
                    with events.open("a") as stream:
                        stream.write(json.dumps(record, ensure_ascii=False) + "\n")

                def no_auto_get():
                    before = len(calls)
                    expect(button).to_be_disabled()
                    selection.select_option(identifier(101))
                    expect(button).to_be_enabled()
                    page.get_by_text(SUMMARY, exact=True).press("Enter")
                    page.get_by_text(SUMMARY, exact=True).press("Enter")
                    assert len(calls) == before
                    expect(group).to_have_count(0)

                run_case("no_auto_get", no_auto_get)

                def explicit_loading():
                    selection.select_option(identifier(101))
                    page.evaluate("window.delayImportBody=true")
                    before = len(calls)
                    button.focus()
                    page.keyboard.press("Enter")
                    page.wait_for_function("window.delayedBodies.length===1")
                    expect(button).to_be_disabled()
                    expect(area.get_by_text("Importbelegprüfung läuft.", exact=False)).to_be_visible()
                    expect(group).to_have_count(0)
                    assert len(calls) == before + 1
                    page.screenshot(path=str(output / f"loading-{width}.png"), full_page=True)
                    page.evaluate("window.releaseImportBodies()")
                    ready()

                run_case("explicit_loading", explicit_loading)

                def success():
                    selection.select_option(identifier(101))
                    button.click()
                    ready()
                    assert_layout()
                    page.screenshot(path=str(output / f"success-{width}.png"), full_page=True)

                run_case("success_normalized_utc", success)

                def error_retry():
                    selection.select_option(identifier(101))
                    state["mode"] = "http_error"
                    button.click()
                    reject()
                    state["mode"] = "success"
                    button.click()
                    ready()

                run_case("http_error_retry", error_retry)
                for name, mode in (("envelope_error", "envelope_error"), ("invalid_json", "bad_json")):
                    def error_case(mode=mode):
                        selection.select_option(identifier(101))
                        state["mode"] = mode
                        button.click()
                        reject()
                    run_case(name, error_case)

                def late_response(kind):
                    selection.select_option(identifier(101))
                    page.evaluate("window.delayImportBody=true")
                    button.click()
                    page.wait_for_function("window.delayedBodies.length===1")
                    resumed, aborts = page.evaluate("[window.resumedBodies,window.importAborts]")
                    if kind == "selection":
                        selection.select_option(identifier(102))
                    else:
                        page.evaluate("value=>window.renderImport(value)", props(2))
                        expect(selection).to_have_value("")
                        selection.select_option(identifier(102))
                    expect(group).to_have_count(0)
                    button.click()
                    ready()
                    expect(group).to_contain_text("SYNTHETIC_B")
                    page.evaluate("window.releaseImportBodies()")
                    page.wait_for_function("before=>window.resumedBodies>before", arg=resumed)
                    expect(group).to_contain_text("SYNTHETIC_B")
                    assert "SYNTHETIC_A" not in group.inner_text()
                    assert page.evaluate("window.importAborts") > aborts

                run_case("selection_late_response", lambda: late_response("selection"))
                run_case("preview_late_response", lambda: late_response("preview"))

                def metadata_change():
                    success()
                    before = len(calls)
                    changed = props()
                    changed["bindings"][0]["price_fingerprint"] = "e" * 64
                    page.evaluate("value=>window.renderImport(value)", changed)
                    expect(selection).to_have_value("")
                    expect(group).to_have_count(0)
                    assert len(calls) == before

                run_case("metadata_change_resets", metadata_change)

                def unmount_late():
                    selection.select_option(identifier(101))
                    page.evaluate("window.delayImportBody=true")
                    button.click()
                    page.wait_for_function("window.delayedBodies.length===1")
                    resumed = page.evaluate("window.resumedBodies")
                    page.evaluate("window.hideImport();window.releaseImportBodies()")
                    page.wait_for_function("before=>window.resumedBodies>before", arg=resumed)
                    expect(page.get_by_role("group", name=GROUP)).to_have_count(0)

                run_case("unmount_late_response", unmount_late)

                def bounded_url():
                    selection.select_option(identifier(101))
                    data = evidence()
                    data["originals"][0]["download_url"] = "https://synthetic-external.invalid/evil?token=synthetic-secret"
                    state.update(mode="invalid", data=data)
                    button.click()
                    ready()
                    link = group.get_by_role("link")
                    expect(link).to_have_count(1)
                    url = urlsplit(link.get_attribute("href"))
                    expected = f"{BASE}/{identifier(1)}/prices/{identifier(101)}/evidence/{'c' * 64}"
                    assert url.scheme == "http" and url.netloc == "synthetic.invalid" and url.path == expected
                    assert not url.query and not url.fragment and link.get_attribute("download") is not None
                    before = len(calls)
                    link.focus()
                    expect(link).to_be_focused()
                    assert len(calls) == before
                    assert "synthetic-secret" not in area.inner_text()

                run_case("bounded_download_url", bounded_url)

                def exact_quantity():
                    success()
                    quantity = group.get_by_role("button", name="Exakten Mengenwert anzeigen", exact=False)
                    # ExactQuantity verwendet ein natives summary, dessen Rolle browserabhaengig ist.
                    if quantity.count() == 0:
                        quantity = group.locator("details.wsQuantity > summary")
                    quantity.focus()
                    page.keyboard.press("Enter")
                    expect(group.locator("details.wsQuantity code")).to_have_text(bindings()[0]["price_eur"])

                run_case("exact_quantity", exact_quantity)

                def long_filename():
                    selection.select_option(identifier(101))
                    data = evidence()
                    data["originals"][0]["filename"] = "synthetic-" + "x" * 160 + ".bin"
                    state.update(mode="invalid", data=data)
                    button.click()
                    ready()
                    assert_layout()

                run_case("long_filename_layout", long_filename)
                for name, payload in malformed.items():
                    def invalid_case(payload=payload):
                        selection.select_option(identifier(101))
                        state.update(mode="invalid", data=payload)
                        button.click()
                        reject()
                    run_case(name, invalid_case)
                for name, value in old_formats.items():
                    def legacy_case(value=value):
                        before = len(calls)
                        reset(value)
                        expect(area.get_by_text("Für diesen Archivstand fehlt", exact=False)).to_be_visible()
                        expect(area.get_by_role("combobox")).to_have_count(0)
                        expect(area.get_by_role("link")).to_have_count(0)
                        expect(group).to_have_count(0)
                        assert len(calls) == before
                    run_case(name, legacy_case)
                context.close()
        finally:
            browser.close()
    changed = any(fingerprint(source / name) != sha for name, sha in dependency_hashes.items())
    failed = [record for record in results if record["status"] == "failed"]
    report = {"status": "failed" if failed or blocked or javascript_errors or changed else "passed", "browser_executed": True,
              "scope": "real_component_mock_api_not_native_backend", "source_root": str(source), "source_sha256": source_sha,
              "script_sha256": fingerprint(Path(__file__)), "source_changed_during_run": changed,
              "source_dependencies_sha256": dependency_hashes, "node_modules": str(args.node_modules.resolve()),
              "cases": len(results), "failures": len(failed), "viewports": list(WIDTHS), "results": results,
              "get_requests": len(calls), "blocked_requests": blocked, "javascript_errors": javascript_errors,
              "post_requests": sum(row["method"] == "POST" for row in blocked), "provider_requests": 0,
              "downloads_clicked": False, "screenshots": str(output)}
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False))
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
