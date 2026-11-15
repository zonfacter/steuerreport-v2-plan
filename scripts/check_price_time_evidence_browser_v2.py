"""Isolierte Zeitbeleg-UI mit synthetischen Props, ohne API, Hostserver oder Provider."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

from playwright.sync_api import expect, sync_playwright


WIDTHS = (390, 768, 1280, 1440)
ORIGIN = "http://synthetic.invalid/"
LOCATION = ORIGIN + "#portfolio?tab=prices&asset=SYNTHETIC&year=2024"
UNKNOWN = "Zeitbeleg nicht ermittelt."
IDENTITY = "EUR-Identität: 1 EUR = 1 EUR. Kein Marktkurs."
HEADLINES = {
    "unverified_time": "Zeitbeleg nicht belegt.",
    "missing": "Preis- oder Zeitreferenz fehlt.",
    "future_reference": "Referenzzeit liegt nach dem Stichtag.",
    "non_positive": "Preisreferenz nicht positiv.",
    "fixed_eur_identity": IDENTITY,
}
DETAIL_LABELS = (
    "Beobachtungszeit", "Periodenbeginn", "Periodenende", "Preisveröffentlichung", "FX-Veröffentlichung",
    "Freigegebene Bewertungsmethode", "Methodenversion", "Preis-Originalbeleg", "FX-Originalbeleg",
)
ABSENT_FIELDS = (
    "observed_at", "period_start", "period_end", "price_published_at", "fx_published_at",
    "valuation_method_id", "valuation_method_version", "price_evidence_ref", "fx_evidence_ref",
)


def assessment(**changes):
    return {
        "policy_id": "stichtag-temporal-evidence", "policy_version": 1,
        "asset": "SYNTHETIC", "status": "unverified_time", "strict_eligible": False,
        "reference_kind": "unknown", "stored_reference_at": "2024-06-01T00:00:00Z",
        **dict.fromkeys(ABSENT_FIELDS),
        "reason_codes": ["synthetic_time_unverified"],
        "explanation": "Synthetischer Referenzzeitwert ohne Originalbeleg.",
        **changes,
    }


def fixtures():
    cases = []

    def add(name, value, *, valid=False):
        cases.append({"name": name, "assessment": value, "valid": valid})

    fiat = assessment(asset="EUR", status="fixed_eur_identity", strict_eligible=True,
                      reference_kind="fixed_identity", stored_reference_at=None,
                      reason_codes=["synthetic_eur_identity"])
    add("loading", None)
    add("legacy_null", None)
    add("api_unknown", {"status": "unknown", "strict_eligible": True})
    add("unknown", assessment(), valid=True)
    add("daily", assessment(reference_kind="daily_reference_candidate"), valid=True)
    add("derived", assessment(reference_kind="derived_reference_candidate"), valid=True)
    add("missing", assessment(status="missing", stored_reference_at=None), valid=True)
    add("missing_price_reference", assessment(status="missing"), valid=True)
    # Der Stichtag ist hier 01:00 UTC am 1. Juni 2024, nicht die Browser-Uhrzeit.
    add("future", assessment(status="future_reference", stored_reference_at="2024-06-01T02:00:00Z"), valid=True)
    add("non_positive", assessment(status="non_positive"), valid=True)
    add("fiat", fiat, valid=True)
    add("eur_market", assessment(asset="EUR", reference_kind="daily_reference_candidate"), valid=True)
    add("utc_offset", assessment(stored_reference_at="2024-06-01T00:00:00+00:00"), valid=True)
    add("microseconds", assessment(stored_reference_at="2024-06-01T00:00:00.123456Z"), valid=True)
    add("label_not_approval", assessment(reference_kind="daily_reference_candidate", price_source="fiat:EUR",
                                         explanation="Freigegeben! 1 EUR = 1 EUR. synthetic-secret"), valid=True)
    add("long_reason", assessment(reason_codes=["synthetic_" + "unverified_" * 40]), valid=True)
    add("fiat_wrong_asset", {**fiat, "asset": "USDC"})
    add("fiat_lowercase_asset", {**fiat, "asset": "eur"})
    add("fiat_not_eligible", {**fiat, "strict_eligible": False})
    add("fiat_wrong_kind", {**fiat, "reference_kind": "daily_reference_candidate"})
    add("fiat_epoch", {**fiat, "stored_reference_at": "1970-01-01T00:00:00Z"})
    add("fiat_wrong_policy", {**fiat, "policy_version": 2})
    add("daily_eligible", assessment(strict_eligible=True, reference_kind="daily_reference_candidate"))
    add("unknown_eligible", assessment(strict_eligible=True))
    add("unknown_fixed_kind", assessment(reference_kind="fixed_identity"))
    add("future_without_reference", assessment(status="future_reference", stored_reference_at=None))
    add("future_eligible", assessment(status="future_reference", strict_eligible=True))
    add("unknown_status", assessment(status="observed_and_approved", strict_eligible=True))
    add("unknown_kind", assessment(reference_kind="observed"))
    add("unknown_policy", assessment(policy_id="synthetic-other-policy"))
    add("boolean_version", assessment(policy_version=True))
    add("string_eligibility", assessment(strict_eligible="false"))
    add("naive_reference", assessment(stored_reference_at="2024-06-01T00:00:00"))
    add("non_utc_reference", assessment(stored_reference_at="2024-06-01T00:00:00+01:00"))
    add("invalid_reference", assessment(stored_reference_at="2024-02-30T00:00:00Z"))
    add("numeric_reference", assessment(stored_reference_at=0))
    add("invalid_reason_codes", assessment(reason_codes="synthetic-not-a-list"))
    add("blank_asset", assessment(asset=""))
    add("array_assessment", [])
    for field in ("policy_id", "policy_version", "strict_eligible", "stored_reference_at", "reason_codes", *ABSENT_FIELDS):
        value = deepcopy(fiat)
        del value[field]
        add("missing_" + field, value)
    for field in ABSENT_FIELDS:
        value = "synthetic-method" if field.endswith("_id") or field.endswith("_ref") else 1 if field.endswith("_version") else "2024-06-01T00:00:00Z"
        add("unsupported_" + field, assessment(**{field: value}))
        add("fiat_with_" + field, {**fiat, field: value})
    return cases


def assert_layout(page):
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Horizontaler Seitenueberlauf"
    assert page.evaluate("""() => [...document.querySelectorAll('#root, #root p, #root dt, #root dd, #root summary, #root li')]
      .filter(el => el.getClientRects().length).every(el => {
        const r=el.getBoundingClientRect();
        return r.left >= 0 && r.right <= innerWidth + 1 && el.scrollWidth <= el.clientWidth + 1;
      })"""), "Inhalt passt nicht ins native Viewport"
    assert page.url == LOCATION, "Rueckweg oder Filter veraendert"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-modules", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--browser-executable")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    modules = (args.node_modules or root / "frontend/node_modules").resolve()
    output = (args.output or Path(tempfile.mkdtemp(prefix="steuerreport-price-time-browser-"))).resolve()
    if not (output.is_relative_to(Path("/tmp").resolve()) or output.is_relative_to(root / "var")):
        parser.error("Testausgabe nur unter /tmp oder ignoriertem var ablegen")
    output.mkdir(parents=True, exist_ok=True)
    harness = '''import {StrictMode} from "react";
import {createRoot} from "react-dom/client";
import {PriceTimeEvidence, type PriceTimeAssessment} from "./src/workspace/PriceTimeEvidence";
const root=createRoot(document.getElementById("root"));
(window as any).renderAssessment=(assessment?:PriceTimeAssessment|null)=>root.render(
  <StrictMode><PriceTimeEvidence assessment={assessment}/></StrictMode>);
(window as any).renderLoading=()=>root.render(<StrictMode><PriceTimeEvidence/></StrictMode>);
(window as any).renderLoading();'''
    build_code = f'''import {{build}} from {json.dumps((modules / "esbuild/lib/main.js").as_uri())};
const result=await build({{stdin:{{contents:{json.dumps(harness)},resolveDir:process.cwd(),loader:"tsx"}},
nodePaths:[{json.dumps(str(modules))}],bundle:true,write:false,format:"iife",jsx:"automatic"}});
process.stdout.write(result.outputFiles[0].text);'''
    bundle = subprocess.check_output(["node", "--input-type=module", "-e", build_code], cwd=root / "frontend", text=True)
    styles = (root / "frontend/src/styles.css").read_text() + (root / "frontend/src/workspace/workspace.css").read_text()
    document = f'<html lang="de"><meta name="viewport" content="width=device-width,initial-scale=1"><style>{styles}</style><main id="root" style="max-width:960px;margin:auto;padding:16px"></main><script>{bundle}</script></html>'
    unexpected, errors, requests, completed = [], [], [], []

    def route(route):
        if route.request.url == ORIGIN and route.request.method == "GET":
            requests.append(route.request.url)
            route.fulfill(content_type="text/html", body=document)
        else:
            unexpected.append(route.request.url)
            route.abort()

    cases = fixtures()
    fiat = next(case["assessment"] for case in cases if case["name"] == "fiat")
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.browser_executable)
        for width in WIDTHS:
            context = browser.new_context(viewport={"width": width, "height": 900}, device_scale_factor=1,
                                          service_workers="block", reduced_motion="reduce")
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script("""(() => {
              window.sideEffects=[];
              window.fetch=(...args)=>{window.sideEffects.push('fetch');throw Error('unexpected-fetch')};
              Storage.prototype.setItem=function(){window.sideEffects.push('storage-write');throw Error('unexpected-storage-write')};
            })();""")
            page.route("**/*", route)
            page.goto(LOCATION)
            group = page.get_by_role("group", name="Zeitbeleg", exact=True)
            expect(group.get_by_text(UNKNOWN, exact=True)).to_be_visible()
            for case in cases:
                name, value, valid = case["name"], case["assessment"], case["valid"]
                # Auch Loading und jede ungueltige Antwort muessen alte EUR-Identitaet sofort verwerfen.
                page.evaluate("value => window.renderAssessment(value)", fiat)
                expect(group.get_by_text(IDENTITY, exact=True)).to_be_visible()
                if name == "loading":
                    page.evaluate("window.renderLoading()")
                else:
                    page.evaluate("value => window.renderAssessment(value)", value)
                expect(group.get_by_text(HEADLINES[value["status"]] if valid else UNKNOWN, exact=True)).to_be_visible()
                if not valid:
                    expect(group.locator("details, time")).to_have_count(0)
                    expect(group.get_by_text(IDENTITY, exact=True)).to_have_count(0)
                    assert "1970" not in group.inner_text()
                else:
                    details = group.locator("details")
                    assert not details.evaluate("el => el.open"), "Details nicht initial eingeklappt"
                    summary = group.get_by_text("Zeitbeleg im Detail", exact=True)
                    summary.focus()
                    page.keyboard.press("Enter")
                    expect(details).to_have_attribute("open", "")
                    for label in DETAIL_LABELS:
                        expect(group.locator("dt").filter(has_text=label)).to_have_count(1)
                    expect(group.locator("dd").filter(has_text="Nicht belegt.")).to_have_count(9)
                    if value["status"] == "fixed_eur_identity":
                        expect(group.locator("time")).to_have_count(0)
                        expect(group.get_by_text("Zeitlos; kein Kursereignis.", exact=False)).to_be_visible()
                        assert "1970" not in group.inner_text()
                    else:
                        expect(group.get_by_text(IDENTITY, exact=True)).to_have_count(0)
                        expect(group.get_by_text("Ledger-Zeitwert belegt weder Beobachtung", exact=False)).to_be_visible()
                        if value["stored_reference_at"] is not None:
                            expect(group.locator("time")).to_have_attribute("datetime", value["stored_reference_at"])
                            expect(group.locator("time")).to_have_text(value["stored_reference_at"] + " (UTC)")
                        else:
                            expect(group.locator("time")).to_have_count(0)
                        if value["reference_kind"] in {"daily_reference_candidate", "derived_reference_candidate"}:
                            expect(group.get_by_text("ungeprüftem Quellenlabel.", exact=False)).to_be_visible()
                    assert "synthetic-secret" not in group.inner_text(), "Freitext als Beleg uebernommen"
                    assert_layout(page)
                    # Tastatur-Rueckweg, dann erneut oeffnen fuer den visuellen Nachweis.
                    summary.focus()
                    page.keyboard.press("Enter")
                    assert not details.evaluate("el => el.open")
                    summary.press("Enter")
                    expect(details).to_have_attribute("open", "")
                assert_layout(page)
                expect(group.locator("button, input, a, form")).to_have_count(0)
                assert page.evaluate("window.sideEffects") == []
                assert page.evaluate("localStorage.length === 0 && sessionStorage.length === 0")
                screenshot = (width in {390, 1440} and name in {"loading", "unknown", "daily", "derived", "missing", "future", "fiat", "fiat_epoch"})
                if screenshot or (width in {768, 1280} and name in {"daily", "fiat"}):
                    page.screenshot(path=str(output / f"price-time-{name}-{width}.png"), full_page=True)
                completed.append((width, name))
            context.close()
        browser.close()
    assert not unexpected, unexpected
    assert not errors, errors
    assert requests == [ORIGIN] * len(WIDTHS), requests
    summary = {"synthetic": True, "cases": len(completed), "scenarios": len(cases), "viewports": list(WIDTHS),
               "external_requests": 0, "api_requests": 0, "provider_calls": 0, "review_actions": 0,
               "screenshots": str(output), "component_sha256": hashlib.sha256((root / "frontend/src/workspace/PriceTimeEvidence.tsx").read_bytes()).hexdigest()}
    (output / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
