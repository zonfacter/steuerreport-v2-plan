"""Insecure-HTTP-Nachweis mit echtem Browser und unabhaengigen SHA256-Sollwerten.

Nur kontrollierte Admission-Antworten, kein Server, keine echte API oder Datenbank.
HTTP-Origin ist nicht localhost. Crypto-APIs werden nicht entfernt oder simuliert.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit
from uuid import RFC_4122, UUID

from playwright.sync_api import expect, sync_playwright

from check_price_admission_browser_v2 import fixture_draft, make_report, props


ORIGIN = "http://admission-insecure.invalid"
SUMMARY = "Preiszeit und Methode menschlich bestätigen"
VECTORS = {"empty": b"", "one_byte": b"\x00", "ascii": b"abc",
           "non_ascii": "Ärger, Grüße und Preisbeleg: € ☃".encode("utf-8"), "two_mib": b"x" * (2 * 1024 * 1024)}
KNOWN = {"empty": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
         "ascii": "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"}
ORACLE_SHA = "cc611225ccd8f7b5da922e6aceb528625e053ce77f1d32051b45779bf3ae65a4"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bundle(source, modules):
    helper = source / "frontend/src/sha256.ts"
    imports = 'import {sha256Bytes} from "./src/sha256";' if helper.is_file() else ""
    assignment = "window.hashAdmission=async(bytes)=>Array.from(await sha256Bytes(bytes),v=>v.toString(16).padStart(2,'0')).join('');" if helper.is_file() else ""
    entry = '''import React from "react";import {createRoot} from "react-dom/client";
import {PriceAdmission} from "./src/workspace/PriceAdmission";
import {newRequestId} from "./src/request-id";
const root=createRoot(document.getElementById("root"));
window.renderAdmission=p=>root.render(<section className="wsPage wsPriceWorkspace"><PriceAdmission {...p}/></section>);
window.hideAdmission=()=>root.render(null);window.requestAdmissionId=newRequestId;''' + imports + assignment
    options = {"stdin": {"contents": entry, "resolveDir": str(source / "frontend"), "loader": "tsx"},
               "nodePaths": [str(modules)], "bundle": True, "write": False, "format": "iife", "jsx": "automatic",
               "define": {"import.meta.env.VITE_API_BASE": json.dumps(ORIGIN)}}
    code = f'''import {{build}} from {json.dumps((modules / "esbuild/lib/main.js").as_uri())};
const result=await build({json.dumps(options)});process.stdout.write(result.outputFiles[0].text);'''
    javascript = subprocess.check_output(["node", "--input-type=module", "-e", code], text=True)
    css = (source / "frontend/src/styles.css").read_text() + (source / "frontend/src/workspace/workspace.css").read_text()
    return f'<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"><style>{css}</style><main id="root" style="max-width:1040px;padding:16px;margin:auto"></main><script>{javascript}</script></html>'


def main():
    own = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=own)
    parser.add_argument("--node-modules", type=Path, default=own / "frontend/node_modules")
    parser.add_argument("--output", type=Path, default=own / "var/price-admission-http")
    parser.add_argument("--case", default=".", help="Teilprobe, etwa insecure_context|prepare_ascii fuer alte UI")
    args = parser.parse_args()
    source, output, modules = args.source_root.resolve(), args.output.resolve(), args.node_modules.resolve()
    if not output.is_relative_to(own / "var"):
        parser.error("Ausgabe nur im eigenen ignorierten var")
    output.mkdir(parents=True, exist_ok=True)
    selected = re.compile(args.case)
    expected = {name: hashlib.sha256(content).hexdigest() for name, content in VECTORS.items()}
    assert all(expected[name] == known for name, known in KNOWN.items())
    oracle = own / "scripts/check_price_admission_browser_v2.py"
    assert digest(oracle) == ORACLE_SHA, "original_352_script_changed"
    files = [source / name for name in ["frontend/src/workspace/PriceAdmission.tsx", "frontend/src/request-id.ts", "frontend/src/sha256.ts",
             "frontend/src/workspace/resource.ts", "frontend/src/Help.tsx", "frontend/src/api-base.ts", "frontend/src/styles.css",
             "frontend/src/workspace/workspace.css", "frontend/package.json", "frontend/package-lock.json"] if (source / name).is_file()]
    hashes = {str(path.relative_to(source)): digest(path) for path in files}
    html = bundle(source, modules)
    results, calls, blocked, errors, environments = [], [], [], [], []
    events = output / "events.jsonl"
    events.write_text("")
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width in (390, 768, 1280, 1440):
                context = browser.new_context(viewport={"width": width, "height": 1000}, device_scale_factor=1, service_workers="block")
                page = context.new_page()
                page.set_default_timeout(5000)
                page.on("pageerror", lambda error: errors.append(str(error)))

                def intercept(route):
                    req = route.request
                    if req.url == ORIGIN + "/" and req.method == "GET":
                        route.fulfill(content_type="text/html; charset=utf-8", body=html)
                        return
                    path = f"/api/v1/prices/historical/previews/{props()['previewId']}/prices/{props()['priceId']}/admission-previews"
                    url = urlsplit(req.url)
                    if req.method != "POST" or req.url != ORIGIN + path or url.query:
                        blocked.append({"url": req.url, "method": req.method})
                        route.abort()
                        return
                    body = req.post_data_json
                    calls.append(body)
                    route.fulfill(json={"status": "ok", "data": make_report(body)})

                page.route("**/*", intercept)
                page.goto(ORIGIN + "/#synthetic")
                prepare = page.get_by_role("button", name="Technische Vorschau vorbereiten", exact=True)
                group = page.get_by_role("region", name="Gebundene Preiszeitprüfung", exact=True)

                def field(label):
                    return page.get_by_label(label, exact=True)

                def reset():
                    page.evaluate("window.hideAdmission()")
                    expect(page.get_by_text(SUMMARY, exact=True)).to_have_count(0)
                    page.evaluate("p=>window.renderAdmission(p)", props())
                    page.get_by_text(SUMMARY, exact=True).press("Enter")

                def case(name, action):
                    if not selected.search(name):
                        return
                    row = {"width": width, "case": name, "status": "passed"}
                    try:
                        reset()
                        action()
                        assert not blocked and not errors
                    except Exception as exc:
                        row.update(status="failed", error=str(exc)[:2500])
                        if not (output / f"failure-{width}.png").exists():
                            page.screenshot(path=str(output / f"failure-{width}.png"), full_page=True)
                    results.append(row)
                    with events.open("a") as stream:
                        stream.write(json.dumps(row, ensure_ascii=False) + "\n")

                def insecure():
                    actual = page.evaluate("({secure:isSecureContext,subtle:typeof crypto.subtle,randomUUID:typeof crypto.randomUUID,getRandomValues:typeof crypto.getRandomValues})")
                    environments.append({"width": width, **actual})
                    assert actual == {"secure": False, "subtle": "undefined", "randomUUID": "undefined", "getRandomValues": "function"}, actual
                    assert page.url.startswith(ORIGIN + "/")

                case("insecure_context_native_apis_absent", insecure)
                for name, content in VECTORS.items():
                    def vector(name=name, content=content):
                        result = page.evaluate("""async data=>{
                          const bytes=Uint8Array.from(atob(data),c=>c.charCodeAt(0));
                          return window.hashAdmission(bytes);
                        }""", base64.b64encode(content).decode())
                        assert result == expected[name], {"expected": expected[name], "actual": result}
                    case("sha256_" + name, vector)

                def request_ids():
                    actual = page.evaluate("""()=>{
                      const random=Math.random, getRandomValues=crypto.getRandomValues;let calls=0;
                      try {
                        Math.random=()=>{throw Error('Math.random forbidden')};
                        crypto.getRandomValues=bytes=>{calls++;return getRandomValues.call(crypto,bytes)};
                        return {ids:Array.from({length:100},()=>window.requestAdmissionId()),calls};
                      } finally {Math.random=random;crypto.getRandomValues=getRandomValues}
                    }""")
                    assert len(set(actual["ids"])) == actual["calls"] == 100
                    assert all(UUID(value).version == 4 and UUID(value).variant == RFC_4122 for value in actual["ids"])

                case("request_uuid_v4_getrandomvalues_no_mathrandom", request_ids)

                def fill(content):
                    request = fixture_draft()
                    values = {"Netzwerk": request["identity"]["network"], "Contract / eindeutige Assetkennung": request["identity"]["contract"],
                              "Token-Dezimalstellen": "18", "Bewertungszeitpunkt (UTC)": "2024-06-01T12:00", "Beobachteter Kurswert": request["observation"]["value"],
                              "Beobachtet am (UTC)": "2024-06-01T11:00", "Preis veröffentlicht am (UTC)": "2024-06-01T11:01",
                              "Fundstelle im Preisoriginal": request["observation"]["locator"], "Preisquelle": request["observation"]["source"],
                              "Methodenkennung": request["method"]["method_id"], "Methodenversion": "1", "Methodenzeitzone": "Europe/Berlin",
                              "Bestätigende Person": request["actor"], "Begründung": request["rationale"]}
                    for label, value in values.items():
                        field(label).fill(value)
                    field("Preisoriginal").select_option("c" * 64)
                    field("Methodendokument (1 Byte bis 2 MiB)").set_input_files({"name": "synthetic-method.txt", "mimeType": "text/plain", "buffer": content})

                for name in ("one_byte", "ascii", "non_ascii", "two_mib"):
                    def prepare_file(name=name):
                        before = len(calls)
                        fill(VECTORS[name])
                        expect(prepare).to_be_enabled()
                        prepare.focus()
                        page.keyboard.press("Enter")
                        expect(group.get_by_role("heading", name="Technische Vorschau – noch nicht bestätigt", exact=True)).to_be_visible()
                        assert len(calls) == before + 1
                        payload = calls[-1]
                        assert payload["method"]["evidence_sha256"] == expected[name]
                        assert base64.b64decode(payload["method_original"]["content_base64"], validate=True) == VECTORS[name]
                        assert UUID(payload["request_id"]).version == 4 and UUID(payload["request_id"]).variant == RFC_4122
                        assert "captured_at" not in payload["observation"]
                        expect(page.get_by_role("button", name="Menschliche Bestätigung speichern", exact=True)).to_be_disabled()
                        assert page.evaluate("document.documentElement.scrollWidth<=innerWidth")
                        if name == "non_ascii":
                            page.screenshot(path=str(output / f"http-prepared-{width}.png"), full_page=True)
                    case("prepare_" + name, prepare_file)

                for name, content in (("empty_file_rejected", b""), ("oversize_file_rejected", b"x" * (2 * 1024 * 1024 + 1))):
                    def invalid_file(content=content):
                        before = len(calls)
                        fill(content)
                        expect(prepare).to_be_disabled()
                        expect(page.get_by_role("alert")).to_be_visible()
                        assert len(calls) == before
                    case(name, invalid_file)
                context.close()
        finally:
            browser.close()
    changed = any(digest(source / path) != value for path, value in hashes.items())
    failures = sum(row["status"] == "failed" for row in results)
    report = {"status": "passed" if results and not failures and not blocked and not errors and not changed else "failed",
              "scope": "actual_insecure_browser_origin_controlled_admission_responses_no_backend", "source_root": str(source),
              "origin": ORIGIN, "environments": environments, "cases": len(results), "failures": failures, "results": results,
              "expected_sha256_python_hashlib": expected, "known_vectors": KNOWN, "source_dependencies_sha256": hashes,
              "source_changed_during_run": changed, "original_352_sha256": digest(oracle), "original_352_unchanged": digest(oracle) == ORACLE_SHA,
              "script_sha256": digest(Path(__file__)), "mock_post_requests": len(calls), "blocked_requests": blocked,
              "javascript_errors": errors, "crypto_apis_removed_or_stubbed": False, "network_forwarded": False}
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({key: value for key, value in report.items() if key not in {"results", "source_dependencies_sha256"}}, ensure_ascii=False))
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
