"""Isolierter Browsernachweis fuer PriceAdmission mit kontrollierter Mock-API.

Echte React-Komponente, keine Server, Datenbanken, Provider oder Zustimmungen.
Alle Artefakte bleiben im eigenen ignorierten var. Keine Abhaengigkeiten installieren.
"""
import argparse
import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright


WIDTHS = (390, 768, 1280, 1440)
ORIGIN = "https://synthetic.invalid"
LOCATION = ORIGIN + "/#portfolio?tab=prices&year=2024&asset=SYNTHETIC"
SUMMARY = "Preiszeit und Methode menschlich bestätigen"
GROUP = "Gebundene Preiszeitprüfung"
PREPARE = "Technische Vorschau vorbereiten"
APPLY = "Menschliche Bestätigung speichern"
VALUATION = "2024-06-01T12:00:00.000000Z"
CAPTURE = "2026-11-15T12:00:00.123456Z"
METHOD_BYTES = b"SYNTHETIC method document, no real admission.\n"
METHOD_SHA = hashlib.sha256(METHOD_BYTES).hexdigest()


def identifier(number):
    return f"00000000-0000-4000-8000-{number:012x}"


def props():
    return {"previewId": identifier(1), "priceId": identifier(101), "previewSha256": "a" * 64,
            "priceFingerprint": "b" * 64, "asset": "SYNTHETIC", "priceEur": "12.123456789012345678",
            "storedReferenceAt": "2024-06-01T11:00:00+00:00",
            "originals": [{"sha256": "c" * 64, "byte_length": 128, "filename": "synthetic-price.txt"},
                          {"sha256": "d" * 64, "byte_length": 256, "filename": "synthetic-fx.txt"}]}


def fixture_draft():
    identity = {"asset": "SYNTHETIC", "network": "synthetic-network", "contract": "synthetic-contract", "decimals": 18}
    return {"request_id": identifier(201), "preview_sha256": "a" * 64, "price_fingerprint": "b" * 64,
            "valuation_at": VALUATION, "identity": identity,
            "observation": {"identity": identity, "quote_currency": "EUR", "value": "12.123456789012345678",
                            "kind": "observed_quote", "observed_at": "2024-06-01T11:00:00.000000Z",
                            "period_start": None, "period_end": None, "published_at": "2024-06-01T11:01:00.000000Z",
                            "evidence_sha256": "c" * 64, "locator": "synthetic row 1", "source": "synthetic-source", "fx": None},
            "method": {"method_id": "synthetic-method", "version": 1, "kind": "observed_quote",
                       "daily_statistic": None, "daily_time": None, "timezone": "Europe/Berlin",
                       "availability_rule": "available_at_cutoff", "fx_max_age_days": None, "evidence_sha256": METHOD_SHA},
            "method_original": {"filename": "synthetic-method.txt", "media_type": "text/plain",
                                "content_base64": base64.b64encode(METHOD_BYTES).decode()},
            "actor": "Synthetic operator", "rationale": "Synthetic binding review only"}


def make_report(draft=None, status="prepared"):
    draft = deepcopy(draft or fixture_draft())
    approved = status == "human_approved"
    decision = {"decision_id": "price-time-admission:" + draft["request_id"], "created_at": CAPTURE, "updated_at": None,
                "decision_type": "stichtag_price_time_admission", "scope": "price_time_admission:synthetic",
                "title": "Synthetic admission", "actor": draft["actor"], "rationale": draft["rationale"],
                "evidence_ref": None, "source": None, "affected_ids": [identifier(101)], "payload": {"draft_sha256": "e" * 64}}
    observation = draft["observation"]
    observation["captured_at"] = CAPTURE
    if observation["fx"]:
        observation["fx"]["captured_at"] = CAPTURE
    original = {"sha256": draft["method"]["evidence_sha256"],
                "byte_length": len(base64.b64decode(draft["method_original"]["content_base64"])),
                "filename": draft["method_original"]["filename"], "download_url": "https://synthetic-external.invalid/ignored?token=synthetic-secret"}
    return {"format_version": 1, "status": status, "request_id": draft["request_id"], "preview_id": identifier(1),
            "price_id": identifier(101), "draft_sha256": "e" * 64, "price_fingerprint": "b" * 64,
            "created_at": CAPTURE, "validation_policy_sha256": "9" * 64,
            "valuation_at": draft["valuation_at"], "identity": draft["identity"],
            "observation": observation, "method": draft["method"], "actor": draft["actor"], "rationale": draft["rationale"],
            "assessment": {"policy_id": "stichtag-price-evidence-admission", "policy_version": 1,
                           "status": "human_approved" if approved else "rejected" if status in {"revoked", "rejected"} else "not_approved", "strict_eligible": approved,
                           "binding_sha256": "f" * 64, "decision_id": decision["decision_id"] if status in {"human_approved", "revoked", "rejected"} else None,
                           "reason_codes": [] if approved else ["price_admission_revoked"] if status == "revoked" else ["price_admission_policy_changed"] if status == "rejected" else ["approval_missing"], "original_integrity_verified": True,
                           "evidence_origin": "operator_confirmed" if approved else "unverified"},
            "can_apply": status == "prepared", "decision": decision if status in {"human_approved", "revoked", "rejected"} else None,
            "revocation": {**decision, "decision_id": "synthetic-revocation"} if status == "revoked" else None,
            "method_original": original,
            "originals": [{**row, "download_url": "synthetic-original-unused"} for row in props()["originals"]]}


def mutate(report, path, value):
    result = deepcopy(report)
    target = result
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    return result


INVALID = {
    "format": (("format_version",), 2), "status": (("status",), "ready"),
    "request_id": (("request_id",), identifier(999)), "preview_id": (("preview_id",), identifier(2)),
    "price_id": (("price_id",), identifier(102)), "fingerprint": (("price_fingerprint",), "0" * 64),
    "draft_sha": (("draft_sha256",), "bad"), "valuation": (("valuation_at",), "2024-06-01T12:00:00.000001Z"),
    "validation_policy_missing": (("validation_policy_sha256",), None), "validation_policy_invalid": (("validation_policy_sha256",), "bad"),
    "valuation_naive": (("valuation_at",), "2024-06-01T12:00:00"), "created_naive": (("created_at",), "2026-11-15T12:00:00"),
    "asset": (("identity", "asset"), "OTHER"), "network": (("identity", "network"), "OTHER"),
    "observation_identity": (("observation", "identity", "contract"), "OTHER"),
    "value": (("observation", "value"), "999"), "float_value": (("observation", "value"), 12.5),
    "observation_time": (("observation", "observed_at"), "2024-06-01T11:00:00.000001Z"),
    "capture_missing": (("observation", "captured_at"), None),
    "foreign_original": (("observation", "evidence_sha256"), "0" * 64),
    "method_hash": (("method", "evidence_sha256"), "0" * 64),
    "method_id": (("method", "method_id"), "OTHER"), "timezone": (("method", "timezone"), "not/a-zone"),
    "actor": (("actor",), "OTHER"), "rationale": (("rationale",), "OTHER"),
    "original_size": (("method_original", "byte_length"), 2 * 1024 * 1024 + 1),
    "originals": (("originals",), []), "policy": (("assessment", "policy_version"), 2),
    "assessment_status": (("assessment", "status"), "ready"), "strict": (("assessment", "strict_eligible"), True),
    "origin": (("assessment", "evidence_origin"), "operator_confirmed"),
    "integrity": (("assessment", "original_integrity_verified"), False),
    "can_apply_number": (("can_apply",), 1), "reason": (("assessment", "reason_codes"), ["original_missing"]),
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(source, modules):
    harness = '''import React from "react";import {createRoot} from "react-dom/client";
import {PriceAdmission} from "./src/workspace/PriceAdmission";
const root=createRoot(document.getElementById("root"));
window.renderAdmission=(props)=>root.render(<React.StrictMode><section className="wsPage wsPriceWorkspace"><PriceAdmission {...props}/></section></React.StrictMode>);
window.hideAdmission=()=>root.render(null);'''
    options = {"stdin": {"contents": harness, "resolveDir": str(source / "frontend"), "loader": "tsx"},
               "nodePaths": [str(modules)], "bundle": True, "write": False, "format": "iife", "jsx": "automatic",
               "define": {"import.meta.env.VITE_API_BASE": json.dumps(ORIGIN)}}
    code = f'''import {{build}} from {json.dumps((modules / "esbuild/lib/main.js").as_uri())};
const r=await build({json.dumps(options)});process.stdout.write(r.outputFiles[0].text);'''
    bundle = subprocess.check_output(["node", "--input-type=module", "-e", code], text=True)
    styles = (source / "frontend/src/styles.css").read_text() + (source / "frontend/src/workspace/workspace.css").read_text()
    return f'<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>{styles}</style><main id="root" style="max-width:1040px;margin:auto;padding:16px"></main><script>{bundle}</script></html>'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    root = Path(__file__).resolve().parents[1]
    parser.add_argument("--source-root", type=Path, default=root)
    parser.add_argument("--node-modules", type=Path, default=root / "frontend/node_modules")
    parser.add_argument("--output", type=Path, default=root / "var/price-admission-browser")
    parser.add_argument("--browser-executable")
    parser.add_argument("--case", default=".", help="Regulaerer Ausdruck fuer gezielte Teilpruefung")
    args = parser.parse_args()
    output, source, modules = args.output.resolve(), args.source_root.resolve(), args.node_modules.resolve()
    if not output.is_relative_to(root / "var"):
        parser.error("Ausgabe nur im eigenen var")
    output.mkdir(parents=True, exist_ok=True)
    selected = re.compile(args.case)
    dependencies = ["frontend/src/workspace/PriceAdmission.tsx", "frontend/src/workspace/resource.ts", "frontend/src/api-base.ts", "frontend/src/Help.tsx",
                    "frontend/src/styles.css", "frontend/src/workspace/workspace.css"]
    hashes = {name: digest(source / name) for name in dependencies}
    html = build(source, modules)
    results, calls, blocked, errors = [], [], [], []
    events = output / "events.jsonl"
    events.write_text("")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=args.browser_executable)
        try:
            for width in WIDTHS:
                context = browser.new_context(viewport={"width": width, "height": 1000}, device_scale_factor=1,
                                              service_workers="block", reduced_motion="reduce")
                page = context.new_page()
                page.set_default_timeout(6000)
                page.on("pageerror", lambda error: errors.append(str(error)))
                state = {}
                page.add_init_script("""(() => {
                  const fetch=window.fetch.bind(window), digest=crypto.subtle.digest.bind(crypto.subtle);
                  window.pauseBody=false;window.bodies=[];window.released=0;window.aborts=0;
                  window.pauseHash=false;window.hashes=[];
                  window.fetch=async(...args)=>{
                    args[1]?.signal?.addEventListener('abort',()=>window.aborts++);
                    const response=await fetch(...args);
                    if(window.pauseBody){window.pauseBody=false;const json=response.json.bind(response);
                      response.json=async()=>{const data=await json();await new Promise(resolve=>window.bodies.push(resolve));window.released++;return data}}
                    return response;
                  };
                  crypto.subtle.digest=async(...args)=>{const result=await digest(...args);if(window.pauseHash){window.pauseHash=false;await new Promise(resolve=>window.hashes.push(resolve))}return result};
                  window.release=()=>window.bodies.splice(0).forEach(resolve=>resolve());
                  window.releaseHashes=()=>window.hashes.splice(0).forEach(resolve=>resolve());
                })();""")

                def intercept(route):
                    req, url = route.request, urlsplit(route.request.url)
                    if req.url == ORIGIN + "/" and req.method == "GET":
                        route.fulfill(content_type="text/html; charset=utf-8", body=html)
                        return
                    base = f"/api/v1/prices/historical/previews/{identifier(1)}/prices/{identifier(101)}"
                    suffix = url.path.removeprefix(base)
                    match = re.fullmatch(r"/admission-previews/([a-f0-9-]{36})(/apply)?|/admissions/([a-f0-9-]{36})/revoke", suffix)
                    if url.scheme != "https" or url.netloc != "synthetic.invalid" or not url.path.startswith(base) or not (
                        suffix == "/admission-previews" and req.method == "POST" and not url.query
                        or suffix == "/admissions" and req.method == "GET" and set(parse_qs(url.query)) == {"valuation_at"}
                        or match and (req.method == "POST" if suffix.endswith(("/apply", "/revoke")) else req.method == "GET") and not url.query
                    ):
                        blocked.append({"method": req.method, "url": req.url})
                        route.abort()
                        return
                    body = req.post_data_json if req.method == "POST" else None
                    calls.append({"method": req.method, "path": url.path, "query": url.query, "body": body})
                    if suffix == "/admission-previews" and body:
                        assert set(body) == set(fixture_draft()), "unexpected request fields"
                        assert "captured_at" not in body["observation"]
                        assert body["observation"]["fx"] is None or "captured_at" not in body["observation"]["fx"]
                        assert isinstance(body["observation"]["value"], str)
                        assert hashlib.sha256(base64.b64decode(body["method_original"]["content_base64"])).hexdigest() == body["method"]["evidence_sha256"]
                        state["draft"] = deepcopy(body)
                        data = make_report(body)
                    elif suffix.endswith("/apply"):
                        assert body == {"draft_sha256": "e" * 64, "acknowledge_original_verified": True, "acknowledge_scope_limited": True}
                        data = make_report(state["draft"], "human_approved")
                    elif suffix.endswith("/revoke"):
                        assert set(body) == {"draft_sha256", "actor", "rationale", "acknowledge_revocation"} and body["acknowledge_revocation"] is True
                        data = make_report(state["draft"], "revoked")
                    else:
                        data = state.get("report")
                    if "transform" in state:
                        data = state["transform"](data)
                    state["report"] = data
                    if state.get("http_error"):
                        route.fulfill(status=409, json={"status": "error", "data": data, "errors": [{"code": state.get("error_code", "synthetic_failure"), "message": "synthetic-secret"}]})
                    elif state.get("bad_json"):
                        route.fulfill(content_type="application/json", body="{")
                    else:
                        route.fulfill(json={"status": state.get("envelope", "ok"), "data": data})

                page.route("**/*", intercept)
                page.goto(LOCATION)
                area = page.locator("details").filter(has=page.get_by_text(SUMMARY, exact=True)).first
                group = page.get_by_role("region", name=GROUP, exact=True)
                prepare = page.get_by_role("button", name=PREPARE, exact=True)
                apply = page.get_by_role("button", name=APPLY, exact=True)

                def field(label):
                    return page.get_by_label(label, exact=True)

                def reset(value=None):
                    page.evaluate("window.release();window.releaseHashes();window.hideAdmission()")
                    expect(page.get_by_text(SUMMARY, exact=True)).to_have_count(0)
                    state.clear()
                    page.evaluate("p=>window.renderAdmission(p)", value or props())
                    summary = page.get_by_text(SUMMARY, exact=True)
                    summary.focus()
                    page.keyboard.press("Enter")

                def fill(kind="observed_quote", currency="EUR", direction="USD/EUR"):
                    values = {"Netzwerk": "synthetic-network", "Contract / eindeutige Assetkennung": "synthetic-contract",
                              "Token-Dezimalstellen": "18", "Bewertungszeitpunkt (UTC)": "2024-06-01T12:00",
                              "Beobachteter Kurswert": "12.123456789012345678", "Preis veröffentlicht am (UTC)": "2024-06-01T11:01",
                              "Fundstelle im Preisoriginal": "synthetic row 1", "Preisquelle": "synthetic-source",
                              "Methodenkennung": "synthetic-method", "Methodenversion": "1", "Methodenzeitzone": "Europe/Berlin",
                              "Bestätigende Person": "Synthetic operator", "Begründung": "Synthetic binding review only"}
                    for label, value in values.items():
                        field(label).fill(value)
                    field("Referenzart").select_option(kind)
                    if kind == "observed_quote":
                        field("Beobachtet am (UTC)").fill("2024-06-01T11:00")
                    else:
                        field("Periodenbeginn (UTC)").fill("2024-05-31T22:00")
                        field("Periodenende (exklusiv) (UTC)").fill("2024-06-01T22:00")
                        field("Preis veröffentlicht am (UTC)").fill("2024-06-01T22:01")
                        field("Tagesstatistik").select_option("daily_mean")
                        field("Verfügbarkeitsregel").select_option("retrospective_daily_reference")
                    field("Kurswährung").select_option(currency)
                    if currency == "USD":
                        field("FX-Richtung").select_option(direction)
                        for label, value in {"FX-Kurswert": "0.923456789012345678", "FX-Referenzzeit (UTC)": "2024-06-01T10:00",
                                             "FX veröffentlicht am (UTC)": "2024-06-01T10:01", "Fundstelle im FX-Original": "synthetic row 2",
                                             "FX-Quelle": "synthetic-fx", "Maximales FX-Alter in Tagen (0–7)": "1"}.items():
                            field(label).fill(value)
                        field("FX-Original").select_option("d" * 64)
                    field("Preisoriginal").select_option("c" * 64)
                    upload(METHOD_BYTES)
                    expect(prepare).to_be_enabled()

                def upload(content, name="synthetic-method.txt"):
                    field("Methodendokument (1 Byte bis 2 MiB)").set_input_files({"name": name, "mimeType": "text/plain", "buffer": content})
                    if content and len(content) <= 2 * 1024 * 1024 and len(name) <= 180:
                        expect(area.get_by_text("SHA-256:", exact=False).first).to_be_visible()

                def prepared():
                    prepare.click()
                    expect(group.get_by_role("heading", name="Technische Vorschau – noch nicht bestätigt", exact=True)).to_be_visible()
                    expect(apply).to_be_disabled()

                def acknowledge():
                    boxes = group.get_by_role("checkbox")
                    boxes.nth(0).check()
                    expect(apply).to_be_disabled()
                    boxes.nth(1).check()
                    expect(apply).to_be_enabled()

                def reject():
                    expect(page.get_by_role("alert")).to_be_visible()
                    expect(group).to_have_count(0)
                    expect(apply).to_have_count(0)
                    assert "synthetic-secret" not in area.inner_text()

                def layout():
                    assert page.evaluate("document.compatMode==='CSS1Compat' && document.documentElement.scrollWidth<=innerWidth")
                    overflow = area.evaluate("""el=>[...el.querySelectorAll('input,select,textarea,button,p,a,li,legend')].filter(n=>n.getClientRects().length).flatMap(n=>{
                      const r=n.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth+1?[]:[{tag:n.tagName,left:r.left,right:r.right,text:n.textContent.slice(0,100)}]})""")
                    assert not overflow, overflow
                    assert page.url == LOCATION

                def case(name, action):
                    if not selected.search(name):
                        return
                    record = {"width": width, "case": name, "status": "passed"}
                    try:
                        reset()
                        action()
                        assert not blocked, blocked
                        assert not errors, errors
                    except Exception as error:
                        record.update(status="failed", error=str(error)[:3000])
                        if not (output / f"failure-{width}.png").exists():
                            page.screenshot(path=str(output / f"failure-{width}.png"), full_page=True)
                            (output / f"failure-{width}.html").write_text(area.evaluate("el=>el.outerHTML"))
                    results.append(record)
                    with events.open("a") as stream:
                        stream.write(json.dumps(record, ensure_ascii=False) + "\n")

                def no_auto():
                    before = len(calls)
                    reset()
                    page.evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))")
                    assert len(calls) == before
                    expect(prepare).to_be_disabled()
                    for label in ["Bewertungszeitpunkt (UTC)", "Beobachtet am (UTC)", "Preis veröffentlicht am (UTC)", "Beobachteter Kurswert", "Methodenzeitzone"]:
                        expect(field(label)).to_have_value("")
                    layout()

                case("no_auto_requests_no_inferred_facts", no_auto)

                def status_none():
                    before = len(calls)
                    field("Bewertungszeitpunkt (UTC)").fill("2024-06-01T12:00")
                    page.get_by_role("button", name="Bestätigungsstatus lesen", exact=True).click()
                    expect(page.get_by_text("Keine Bestätigung für diesen Bewertungszeitpunkt gespeichert.", exact=True)).to_be_visible()
                    assert len(calls) == before + 1 and calls[-1]["method"] == "GET"
                    assert parse_qs(calls[-1]["query"]) == {"valuation_at": [VALUATION]}

                case("status_none_readonly", status_none)

                def read_existing(status):
                    before = len(calls)
                    state["report"] = make_report(status=status)
                    field("Bewertungszeitpunkt (UTC)").fill("2024-06-01T12:00")
                    page.get_by_role("button", name="Bestätigungsstatus lesen", exact=True).click()
                    expect(group).to_be_visible()
                    expect(apply).to_have_count(0)
                    expect(field("Beobachtet am (UTC)")).to_have_value("")
                    assert len(calls) == before + 1 and calls[-1]["method"] == "GET"
                    if status == "rejected":
                        expect(group.get_by_text("Prüfmethode geändert, neue Vorschau erforderlich.", exact=True)).to_be_visible()

                for status in ("human_approved", "rejected", "revoked"):
                    case("read_existing_" + status, lambda status=status: read_existing(status))

                def flow(currency="EUR", kind="observed_quote", direction="USD/EUR"):
                    fill(kind, currency, direction)
                    prepared()
                    layout()
                    acknowledge()
                    apply.focus()
                    page.keyboard.press("Enter")
                    expect(group.get_by_role("heading", name="Menschliche Bestätigung für diese Preis-ID und diesen Bewertungszeitpunkt gespeichert", exact=True)).to_be_visible()
                    expect(group.get_by_text("Keine Gesamtfreigabe.", exact=False)).to_be_visible()
                    layout()
                    page.screenshot(path=str(output / f"approved-{width}.png"), full_page=True)

                case("eur_prepare_two_acks_apply_keyboard", flow)
                case("usd_multiply", lambda: flow("USD"))
                case("usd_divide", lambda: flow("USD", direction="EUR/USD"))
                case("daily_mean", lambda: flow(kind="daily_reference"))

                def daily_close():
                    fill("daily_reference")
                    field("Tagesstatistik").select_option("daily_close")
                    prepared()
                    assert state["draft"]["method"]["daily_statistic"] == "daily_close"

                case("daily_close", daily_close)

                def fixed_daily():
                    fill("daily_reference")
                    field("Tagesstatistik").select_option("daily_fixed_time")
                    expect(prepare).to_be_disabled()
                    field("Lokale Methodenuhrzeit").fill("12:00")
                    prepared()
                    assert state["draft"]["method"]["daily_time"] == "12:00"

                case("daily_fixed_time_explicit", fixed_daily)

                def loading_cancel():
                    fill()
                    page.evaluate("window.pauseBody=true")
                    prepare.click()
                    page.wait_for_function("window.bodies.length===1")
                    expect(prepare).to_be_disabled()
                    expect(group).to_have_count(0)
                    page.get_by_role("button", name="Abbrechen", exact=True).click()
                    page.evaluate("window.release()")
                    page.wait_for_function("window.released>0")
                    reject()
                    expect(field("Bestätigende Person")).to_have_value("Synthetic operator")

                case("loading_cancel_no_false_rollback", loading_cancel)

                def error_retry():
                    fill()
                    state["http_error"] = True
                    prepare.click()
                    reject()
                    old = deepcopy(calls[-1]["body"])
                    expect(field("Begründung")).to_have_value("Synthetic binding review only")
                    state.pop("http_error")
                    prepared()
                    assert calls[-1]["body"] == old

                case("prepare_error_preserves_inputs_idempotent_retry", error_retry)

                def edit_resets():
                    fill()
                    prepared()
                    acknowledge()
                    field("Begründung").fill("Synthetic changed rationale")
                    expect(group).to_have_count(0)
                    old = calls[-1]["body"]["request_id"]
                    prepared()
                    assert calls[-1]["body"]["request_id"] != old

                case("edit_resets_preview_acks_request_id", edit_resets)

                def reload():
                    fill()
                    prepared()
                    acknowledge()
                    before = len(calls)
                    page.get_by_role("button", name="Vorschau erneut lesen", exact=True).click()
                    expect(apply).to_be_disabled()
                    assert len(calls) == before + 1 and calls[-1]["method"] == "GET"
                    assert not group.get_by_role("checkbox").nth(0).is_checked()

                case("revalidation_is_get_resets_acks", reload)

                def apply_error():
                    fill()
                    prepared()
                    acknowledge()
                    state["http_error"] = True
                    before = len(calls)
                    apply.click()
                    reject()
                    assert len(calls) == before + 1
                    state.pop("http_error")
                    page.get_by_role("button", name="Vorschau erneut lesen", exact=True).click()
                    expect(group.get_by_role("heading", name="Menschliche Bestätigung für diese Preis-ID und diesen Bewertungszeitpunkt gespeichert", exact=True)).to_be_visible()
                    assert calls[-1]["method"] == "GET"

                case("apply_error_no_auto_retry_read_recovery", apply_error)

                def policy_error(code):
                    fill()
                    state.update(http_error=True, error_code=code)
                    before = len(calls)
                    prepare.click()
                    reject()
                    expect(page.get_by_role("alert")).to_contain_text("Prüfmethode")
                    assert len(calls) == before + 1
                    if code == "price_admission_policy_changed":
                        old = state["draft"]["request_id"]
                        state.pop("http_error")
                        page.get_by_role("button", name="Neue technische Vorschau vorbereiten", exact=True).click()
                        expect(group).to_be_visible()
                        assert state["draft"]["request_id"] != old

                for code in ("price_admission_policy_changed", "price_admission_policy_unavailable"):
                    case(code, lambda code=code: policy_error(code))

                def policy_changed_on_apply():
                    fill()
                    prepared()
                    acknowledge()
                    old = state["draft"]["request_id"]
                    state.update(http_error=True, error_code="price_admission_policy_changed")
                    before = len(calls)
                    apply.click()
                    reject()
                    expect(field("Begründung")).to_have_value("Synthetic binding review only")
                    expect(page.get_by_role("alert")).to_contain_text("Prüfmethode geändert")
                    assert len(calls) == before + 1
                    state.pop("http_error")
                    page.get_by_role("button", name="Neue technische Vorschau vorbereiten", exact=True).click()
                    expect(apply).to_be_disabled()
                    expect(group.get_by_role("checkbox").nth(0)).not_to_be_checked()
                    expect(group.get_by_role("checkbox").nth(1)).not_to_be_checked()
                    assert state["draft"]["request_id"] != old
                    assert calls[-1]["path"].endswith("/admission-previews")

                case("policy_changed_during_apply_old_acks_never_reused", policy_changed_on_apply)

                def race(kind):
                    fill()
                    if kind == "apply":
                        prepared()
                        acknowledge()
                    page.evaluate("window.pauseBody=true")
                    (apply if kind == "apply" else prepare).click()
                    page.wait_for_function("window.bodies.length===1")
                    if kind == "props":
                        page.evaluate("p=>window.renderAdmission(p)", {**props(), "priceFingerprint": "0" * 64})
                        expect(field("Bestätigende Person")).to_have_value("")
                    else:
                        field("Bestätigende Person").fill("Synthetic changed operator")
                    before = page.evaluate("window.released")
                    page.evaluate("window.release()")
                    page.wait_for_function("before=>window.released>before", arg=before)
                    expect(group).to_have_count(0)
                    assert page.evaluate("window.aborts") > 0

                case("late_prepare_after_input_change", lambda: race("prepare"))
                case("late_apply_after_input_change", lambda: race("apply"))
                case("late_response_after_prop_change", lambda: race("props"))

                def late_status():
                    field("Bewertungszeitpunkt (UTC)").fill("2024-06-01T12:00")
                    page.evaluate("window.pauseBody=true")
                    page.get_by_role("button", name="Bestätigungsstatus lesen", exact=True).click()
                    page.wait_for_function("window.bodies.length===1")
                    field("Bewertungszeitpunkt (UTC)").fill("2024-06-02T12:00")
                    before = page.evaluate("window.released")
                    page.evaluate("window.release()")
                    page.wait_for_function("before=>window.released>before", arg=before)
                    expect(page.get_by_text("Keine Bestätigung für diesen Bewertungszeitpunkt gespeichert.", exact=True)).to_have_count(0)

                case("late_status_after_valuation_change", late_status)

                def invalid_response(path, value):
                    fill()
                    state["transform"] = lambda data: mutate(data, path, value)
                    prepare.click()
                    reject()

                for name, (path, value) in INVALID.items():
                    case("invalid_" + name, lambda path=path, value=value: invalid_response(path, value))
                for name, value in [("null", None), ("array", []), ("empty", {})]:
                    def invalid_root(value=value):
                        fill()
                        state["transform"] = lambda data: value
                        prepare.click()
                        reject()
                    case("invalid_root_" + name, invalid_root)

                for name, settings in [("envelope_error", {"envelope": "error"}), ("envelope_unknown", {"envelope": "ready"}), ("bad_json", {"bad_json": True})]:
                    def response_error(settings=settings):
                        fill()
                        state.update(settings)
                        prepare.click()
                        reject()
                    case(name, response_error)

                def blocked_report():
                    fill()
                    def transform(data):
                        data["status"] = "blocked"
                        data["can_apply"] = False
                        data["assessment"]["reason_codes"] = ["original_missing"]
                        return data
                    state["transform"] = transform
                    prepare.click()
                    expect(group.get_by_role("heading", name="Technische Prüfung blockiert", exact=True)).to_be_visible()
                    expect(apply).to_have_count(0)

                case("blocked_no_acknowledgement", blocked_report)

                def revoke_flow():
                    flow()
                    group.get_by_text("Bestätigung ausdrücklich widerrufen", exact=True).click()
                    button = group.get_by_role("button", name="Bestätigung widerrufen", exact=True)
                    expect(button).to_be_disabled()
                    field("Widerrufende Person").fill("Synthetic revoker")
                    field("Widerrufsbegründung").fill("Synthetic correction")
                    expect(button).to_be_disabled()
                    group.get_by_role("checkbox").check()
                    button.click()
                    expect(group.get_by_role("heading", name="Menschliche Bestätigung widerrufen", exact=True)).to_be_visible()
                    expect(apply).to_have_count(0)

                case("explicit_revoke", revoke_flow)

                def revoke_error():
                    flow()
                    group.get_by_text("Bestätigung ausdrücklich widerrufen", exact=True).click()
                    field("Widerrufende Person").fill("Synthetic revoker")
                    field("Widerrufsbegründung").fill("Synthetic correction")
                    group.get_by_role("checkbox").check()
                    state["http_error"] = True
                    group.get_by_role("button", name="Bestätigung widerrufen", exact=True).click()
                    reject()
                    state.pop("http_error")
                    state["report"] = make_report(state["draft"], "human_approved")
                    page.get_by_role("button", name="Vorschau erneut lesen", exact=True).click()
                    expect(group).to_be_visible()
                    group.get_by_text("Bestätigung ausdrücklich widerrufen", exact=True).click()
                    expect(field("Widerrufsbegründung")).to_have_value("Synthetic correction")
                    expect(group.get_by_role("checkbox")).not_to_be_checked()
                    expect(group.get_by_role("button", name="Bestätigung widerrufen", exact=True)).to_be_disabled()

                case("revoke_error_preserves_reason_resets_ack", revoke_error)

                for name, path, value in [("decision_missing", ("decision",), None), ("decision_actor", ("decision", "actor"), "OTHER"),
                                          ("decision_id", ("decision", "decision_id"), "OTHER"), ("reasons_present", ("assessment", "reason_codes"), ["original_missing"]),
                                          ("origin", ("assessment", "evidence_origin"), "unverified"), ("strict_false", ("assessment", "strict_eligible"), False)]:
                    def bad_approval(path=path, value=value):
                        state["report"] = mutate(make_report(status="human_approved"), path, value)
                        field("Bewertungszeitpunkt (UTC)").fill("2024-06-01T12:00")
                        page.get_by_role("button", name="Bestätigungsstatus lesen", exact=True).click()
                        reject()
                    case("invalid_approval_" + name, bad_approval)

                def scientific_decimal():
                    fill()
                    state["transform"] = lambda data: mutate(data, ("observation", "value"), "1.2123456789012345678E1")
                    prepared()

                case("exact_decimal_scientific_equivalence", scientific_decimal)

                for label, value in [("Token-Dezimalstellen", "256"), ("Methodenversion", "0"), ("Methodenzeitzone", "unknown/zone"),
                                     ("Beobachteter Kurswert", "0"), ("Beobachteter Kurswert", "-1"), ("Beobachteter Kurswert", "1,25")]:
                    def bad_input(label=label, value=value):
                        fill()
                        before = len(calls)
                        field(label).fill(value)
                        expect(prepare).to_be_disabled()
                        assert len(calls) == before
                    case("invalid_input_" + label + "_" + value, bad_input)

                def bounded_download():
                    fill()
                    prepared()
                    group.get_by_text("Methode, Originale und technische Bindung", exact=True).click()
                    link = group.get_by_role("link", name="Methodendokument herunterladen", exact=True)
                    href = urlsplit(link.get_attribute("href"))
                    assert href.scheme == "https" and href.netloc == "synthetic.invalid" and not href.query and not href.fragment
                    assert href.path.endswith(f'/admission-previews/{state["draft"]["request_id"]}/method-original')
                    assert link.get_attribute("download") is not None
                    link.focus()
                    expect(link).to_be_focused()
                    layout()
                    assert "synthetic-secret" not in area.inner_text()

                case("bounded_download_no_click", bounded_download)

                def invalid_file(content):
                    fill()
                    upload(content)
                    expect(prepare).to_be_disabled()
                    expect(page.get_by_role("alert")).to_be_visible()

                case("file_empty", lambda: invalid_file(b""))
                case("file_over_2mib", lambda: invalid_file(b"x" * (2 * 1024 * 1024 + 1)))

                def max_file():
                    fill()
                    upload(b"x" * (2 * 1024 * 1024))
                    expect(prepare).to_be_enabled()
                    expect(area.get_by_text(hashlib.sha256(b"x" * (2 * 1024 * 1024)).hexdigest(), exact=True)).to_be_visible()

                case("file_exact_2mib", max_file)

                def file_race():
                    fill()
                    page.evaluate("window.pauseHash=true")
                    field("Methodendokument (1 Byte bis 2 MiB)").set_input_files({"name": "old.txt", "mimeType": "text/plain", "buffer": b"synthetic-old"})
                    page.wait_for_function("window.hashes.length===1")
                    upload(b"synthetic-new", "new.txt")
                    page.evaluate("window.releaseHashes()")
                    expect(area.get_by_text(hashlib.sha256(b"synthetic-new").hexdigest(), exact=True)).to_be_visible()
                    prepared()
                    assert state["draft"]["method_original"]["filename"] == "new.txt"

                case("late_file_hash", file_race)

                def tooltip():
                    page.get_by_role("button", name="Hilfe: Methodenzeitzone", exact=True).focus()
                    expect(page.get_by_role("tooltip")).to_be_visible()
                    page.keyboard.press("Escape")
                    expect(page.get_by_role("tooltip")).to_have_count(0)

                case("tooltip_keyboard", tooltip)

                def long_context():
                    value = props()
                    value["originals"][0]["filename"] = "synthetic-" + "x" * 160 + ".txt"
                    reset(value)
                    area.get_by_text("Gebundener Importkontext", exact=True).click()
                    fill()
                    prepared()
                    layout()
                    page.screenshot(path=str(output / f"prepared-{width}.png"), full_page=True)

                case("long_original_name_layout", long_context)

                for name, value in [("missing_originals", {**props(), "originals": []}), ("bad_preview", {**props(), "previewId": "../bad"})]:
                    def unsupported(value=value):
                        before = len(calls)
                        reset(value)
                        expect(page.get_by_role("alert")).to_be_visible()
                        expect(prepare).to_have_count(0)
                        assert len(calls) == before
                    case(name, unsupported)
                context.close()
        finally:
            browser.close()
    changed = any(digest(source / name) != value for name, value in hashes.items())
    failures = [row for row in results if row["status"] != "passed"]
    report = {"status": "failed" if failures or errors or blocked or changed or not results else "passed",
              "scope": "real_component_mock_api_not_native_backend", "source_root": str(source), "node_modules": str(modules),
              "source_dependencies_sha256": hashes, "source_changed_during_run": changed,
              "script_sha256": digest(Path(__file__)), "widths": list(WIDTHS), "cases": len(results), "failures": len(failures),
              "results": results, "get_requests": sum(row["method"] == "GET" for row in calls),
              "mock_post_requests": sum(row["method"] == "POST" for row in calls), "blocked_requests": blocked,
              "javascript_errors": errors, "external_requests": 0, "provider_requests": 0, "downloads_clicked": False}
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({key: value for key, value in report.items() if key != "results"}, ensure_ascii=False))
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
