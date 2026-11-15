"""12 Zeitbeleg-Browserfaelle gegen echte API und drei eigene synthetische DBs.

Keine Statusfixtures, kein TCP-Server, keine Provider/Pipeline/Reviewaktionen.
Die unveraenderte API-price_time wird an die echte React-Komponente gegeben.
Nur bestehende Node-/Browserabhaengigkeiten; Ergebnisse ausschliesslich neu
unter /tmp oder root/var. Keine positive Nicht-EUR-Belegzulassung behaupten.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import UTC, datetime
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://synthetic.invalid"
AS_OF = "2025-06-13T01:00:00Z"
API = "/api/v1/prices/as-of-gate"
WIDTHS = (390, 768, 1280, 1440)
SCENARIOS = {
    "daily_btc": ("BTC", "unverified_time", False),
    "eur_identity": ("EUR", "fixed_eur_identity", True),
    "missing_price": ("BTC", "missing", False),
}
SOURCE = "coingecko_history:usd_eur:v1_fx_cache:2025-06-12"
EVIDENCE_FIELDS = ("observed_at", "period_start", "period_end", "price_published_at", "fx_published_at",
                   "valuation_method_id", "valuation_method_version", "price_evidence_ref", "fx_evidence_ref")
LABELS = {"unverified_time": "Zeitbeleg nicht belegt.",
          "fixed_eur_identity": "EUR-Identit\u00e4t: 1 EUR = 1 EUR. Kein Marktkurs.",
          "missing": "Preis- oder Zeitreferenz fehlt."}
BIND_FILES = (
    "scripts/check_price_time_backend_browser_v2.py", "frontend/src/workspace/PriceTimeEvidence.tsx",
    "frontend/src/styles.css", "frontend/src/workspace/workspace.css", "frontend/package.json",
    "src/steuerreport_v2/api/app.py", "src/steuerreport_v2/db/duckdb_store.py",
    "src/steuerreport_v2/ledger/balance.py", "src/steuerreport_v2/domain/as_of_price_gate.py",
    "src/steuerreport_v2/domain/divorce.py", "src/steuerreport_v2/domain/portfolio.py",
    "src/steuerreport_v2/domain/price_lookup.py", "src/steuerreport_v2/domain/price_time.py",
    "src/steuerreport_v2/contracts/price_time.py", "src/steuerreport_v2/contracts/prices.py",
    "src/steuerreport_v2/contracts/divorce.py",
)


class ProbeFailure(RuntimeError):
    pass


def require(condition, code):
    if not condition:
        raise ProbeFailure(code)


def binding():
    files = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in BIND_FILES}
    return {"sha256": hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest(), "files": files}


def new_output(value):
    if value is None:
        return Path(tempfile.mkdtemp(prefix="price-time-browser-", dir="/tmp"))
    path = value.expanduser().absolute()
    resolved = path.resolve()
    allowed = resolved.is_relative_to(Path("/tmp")) or (
        resolved.is_relative_to(ROOT / "var") and (ROOT / "var").resolve() == ROOT / "var")
    require(allowed and not path.exists() and not path.is_symlink(), "output_must_be_new_tmp_or_var")
    path.mkdir(parents=True, mode=0o700)
    return path


def bundle(modules):
    modules = modules.expanduser().resolve()
    for name in ("esbuild", "react", "react-dom"):
        require((modules / name / "package.json").is_file(), "existing_node_modules_required")
    entry = '''import React,{useEffect,useState} from "react";
import {createRoot} from "react-dom/client";
import {PriceTimeEvidence} from "./src/workspace/PriceTimeEvidence";
function Probe(){const [data,setData]=useState(null),[failed,setFailed]=useState(false);
useEffect(()=>{fetch("/api/v1/prices/as-of-gate?as_of=2025-06-13T01:00:00Z",{cache:"no-store"})
.then(r=>{if(!r.ok)throw Error("api_failed");return r.json();}).then(body=>setData(body.data))
.catch(()=>setFailed(true));},[]);
return <main>{failed?<p role="alert">API unlesbar</p>:data?<>
<output aria-label="Preisgate">{String(data.strict_ready)}</output>
<PriceTimeEvidence assessment={data.candidates[0].price_time}/></>:<p>Laden</p>}</main>;}
createRoot(document.getElementById("root")).render(<Probe/>);'''
    options = dict(stdin=dict(contents=entry, resolveDir=str(ROOT / "frontend"), loader="tsx"),
                   bundle=True, write=False, format="iife", jsx="automatic", nodePaths=[str(modules)],
                   alias={"react": str(modules / "react"), "react-dom": str(modules / "react-dom")})
    code = (f'const {{build}}=await import({json.dumps((modules / "esbuild/lib/main.js").as_uri())});'
            f'const r=await build({json.dumps(options)});process.stdout.write(r.outputFiles[0].text);')
    result = subprocess.run(["node", "--input-type=module", "-e", code], cwd=ROOT / "frontend",
                            capture_output=True, text=True, timeout=120)
    require(result.returncode == 0 and result.stdout, "component_bundle_failed")
    styles = "\n".join((ROOT / path).read_text(encoding="utf-8") for path in (
        "frontend/src/styles.css", "frontend/src/workspace/workspace.css"))
    return ('<!doctype html><html lang="de"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<style>{styles}</style><body><div id="root"></div><script>{result.stdout}</script></body></html>')


def fingerprint(store):
    digest = hashlib.sha256()
    with store.read_snapshot() as snapshot, snapshot.connect() as con:
        tables = con.execute("select table_name from information_schema.tables where table_schema='main' "
                             "and table_type='BASE TABLE' order by table_name").fetchall()
        for (name,) in tables:
            rows = con.execute('select * from "' + name.replace('"', '""') + '" order by all').fetchall()
            digest.update(json.dumps([name, rows], default=str, sort_keys=True).encode())
    return digest.hexdigest()


def seed(state):
    from steuerreport_v2.contracts.events import CanonicalEventCreate
    from steuerreport_v2.contracts.prices import PricePointCreate
    from steuerreport_v2.db.duckdb_store import DuckDbStore
    from steuerreport_v2.ledger.balance import BalanceLedgerBuilder
    stores = {}
    for scenario, (asset, _, _) in SCENARIOS.items():
        store = DuckDbStore(state / (scenario + ".duckdb"))
        store.add_canonical_event(CanonicalEventCreate(source="synthetic-time-browser", source_ref=scenario,
            event_time=datetime(2025, 1, 1, tzinfo=UTC), event_type="transfer", asset=asset,
            quantity=Decimal("10"), account="synthetic-wallet"))
        if scenario == "daily_btc":
            store.add_price_point(PricePointCreate(asset="BTC", price_eur=Decimal("50"),
                priced_at=datetime(2025, 6, 13, tzinfo=UTC), source=SOURCE))
        BalanceLedgerBuilder(store).rebuild()
        stores[scenario] = store
    return stores


def check_answer(body, scenario):
    asset, status, ready = SCENARIOS[scenario]
    data = body["data"]
    require(data["strict_ready"] is ready and data["gate"]["strict_ready"] is ready, "native_gate_mismatch")
    require(len(data["candidates"]) == 1, "native_candidate_count_mismatch")
    candidate = data["candidates"][0]
    assessment = candidate["price_time"]
    require(candidate["asset"] == assessment["asset"] == asset and assessment["status"] == status,
            "native_assessment_mismatch")
    require(assessment["policy_id"] == "stichtag-temporal-evidence" and assessment["policy_version"] == 1
            and assessment["strict_eligible"] is ready, "native_policy_mismatch")
    require(all(field in assessment and assessment[field] is None for field in EVIDENCE_FIELDS), "invented_original_evidence")
    if scenario == "daily_btc":
        require(candidate["status"] == "time_review" and candidate["current_price_source"] == SOURCE
                and assessment["reference_kind"] == "daily_reference_candidate", "daily_label_became_proof")
        require(data["time_review_count"] == data["gate"]["unverified_price_time_count"] == 1, "time_review_count_mismatch")
    elif scenario == "eur_identity":
        require(candidate["current_price_source"] == "fiat:EUR" and assessment["stored_reference_at"] is None,
                "fiat_identity_became_quote_event")
    else:
        require(candidate["current_price_eur"] is None and assessment["stored_reference_at"] is None,
                "missing_price_was_imputed")
    return assessment


def check_ui(page, assessment, expect):
    group = page.get_by_role("group", name="Zeitbeleg", exact=True)
    expect(group.get_by_text(LABELS[assessment["status"]], exact=True)).to_be_visible()
    group.get_by_text("Zeitbeleg im Detail", exact=True).click()
    expect(group.locator("dd")).to_have_count(9)
    require(group.locator("dd").all_text_contents() == ["Nicht belegt."] * 9, "browser_invented_evidence")
    require(group.get_by_role("list", name="API-Pr\u00fcfgr\u00fcnde").locator("li").all_text_contents()
            == assessment["reason_codes"], "browser_reason_codes_changed")
    if assessment["stored_reference_at"] is not None:
        expect(group.locator("time")).to_have_attribute("datetime", assessment["stored_reference_at"])
        expect(group).to_contain_text("Hinweis auf eine Tagesreferenz aus ungepr\u00fcftem Quellenlabel.")
    else:
        expect(group.locator("time")).to_have_count(0)
        expect(group).to_contain_text("Zeitlos; kein Kursereignis." if assessment["strict_eligible"] else "Nicht vorhanden.")
    require(page.evaluate('''() => document.documentElement.scrollWidth <= innerWidth + 1 &&
      [...document.body.querySelectorAll('*')].every(e => {if(!e.getClientRects().length)return true;
      const r=e.getBoundingClientRect();return r.left>=-1 && r.right<=innerWidth+1
        && !(e.clientWidth>0 && e.scrollWidth>e.clientWidth+1);})'''), "browser_horizontal_overflow")


def run(args, output, report):
    with ExitStack() as stack:
        state = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="price-time-private-", dir="/tmp")))
        stack.enter_context(patch.dict(os.environ))
        for key in list(os.environ):
            if key.startswith("STEUERREPORT_"):
                del os.environ[key]
        os.environ.update(STEUERREPORT_V2_ROOT=str(state), STEUERREPORT_STATE_DIR=str(state),
            STEUERREPORT_V2_DB=str(state / "unused-default.duckdb"), STEUERREPORT_PRIVATE_PROFILE=str(state / "profile.json"),
            STEUERREPORT_PRIVATE_CONFIG_DIR=str(state / "configs"), STEUERREPORT_USERTRANSFER_ROOT=str(state / "imports"),
            STEUERREPORT_V2_SECRET_VAULT_KEY_FILE=str(state / "vault.key"),
            STEUERREPORT_V2_CONNECTOR_SETUP_TOKEN_FILE=str(state / "setup.token"))
        (state / "profile.json").write_text("{}", encoding="ascii")
        (state / "configs").mkdir()
        (state / "configs/crypto_price_sources.json").write_text(json.dumps({"assets": [
            {"symbol": "BTC", "coingecko_id": "synthetic-btc", "aliases": ["BTC"]}]}), encoding="ascii")
        prohibited = []
        def forbid(*unused_args, **unused_kwargs):
            prohibited.append(True)
            raise ProbeFailure("forbidden_provider_pipeline_review_or_write")
        for name in ("connect", "connect_ex"):
            original = getattr(socket.socket, name)
            def guarded(sock, address, original=original):
                return forbid() if sock.family in {socket.AF_INET, socket.AF_INET6} else original(sock, address)
            stack.enter_context(patch.object(socket.socket, name, guarded))
        from fastapi.testclient import TestClient
        import httpx
        for transport, method in ((httpx.HTTPTransport, "handle_request"), (httpx.AsyncHTTPTransport, "handle_async_request")):
            stack.enter_context(patch.object(transport, method, forbid))
        from playwright.sync_api import expect, sync_playwright
        from steuerreport_v2.api.app import create_app
        from steuerreport_v2.domain import as_of_price_gate, external_http, external_price_backfill
        from steuerreport_v2.domain.pipeline import PipelineService
        from steuerreport_v2.domain.stichtag_token_valuation import StichtagTokenValuationService
        from steuerreport_v2.ledger.balance import BalanceLedgerBuilder

        sources = binding()
        html = bundle(args.node_modules)
        report.update(source_binding=sources, bundle_sha256=hashlib.sha256(html.encode()).hexdigest())
        for module in (as_of_price_gate, external_http, external_price_backfill):
            stack.enter_context(patch.object(module, "managed_client", forbid))
        for name in ("rebuild_all", "rebuild_after_import", "rebuild_ledgers"):
            stack.enter_context(patch.object(PipelineService, name, forbid))
        stack.enter_context(patch.object(StichtagTokenValuationService, "accept_same_day_valuation", forbid))
        for name in ("backfill", "accept_token_valuation"):
            stack.enter_context(patch.object(as_of_price_gate.AsOfPriceGateService, name, forbid))
        stores = seed(state)
        stack.enter_context(patch.object(BalanceLedgerBuilder, "rebuild", forbid))
        for store in stores.values():
            for name in ("add_canonical_event", "add_canonical_events", "add_price_point", "add_price_points", "add_review_decision"):
                stack.enter_context(patch.object(store, name, forbid))
        clients = {key: stack.enter_context(TestClient(create_app(store), raise_server_exceptions=False)) for key, store in stores.items()}
        before = {key: fingerprint(store) for key, store in stores.items()}
        expect.set_options(timeout=10000)
        playwright = stack.enter_context(sync_playwright())
        browser = stack.enter_context(playwright.chromium.launch(headless=True, executable_path=args.browser_executable,
            args=["--disable-background-networking", "--disable-component-update", "--disable-sync", "--no-first-run"]))
        for scenario, (_, _, ready) in SCENARIOS.items():
            for width in WIDTHS:
                context = browser.new_context(viewport={"width": width, "height": 900}, service_workers="block")
                try:
                    page = context.new_page()
                    answers, errors = [], []
                    page.on("pageerror", lambda error: errors.append(True))
                    def bridge(route):
                        request, parsed = route.request, urlsplit(route.request.url)
                        require(parsed.scheme == "http" and parsed.netloc == "synthetic.invalid" and request.method == "GET",
                                "browser_write_or_external_request")
                        if parsed.path == "/" and not parsed.query:
                            route.fulfill(content_type="text/html", body=html)
                        elif parsed.path == "/favicon.ico" and not parsed.query:
                            route.fulfill(status=204)
                        else:
                            require(parsed.path == API and parse_qs(parsed.query) == {"as_of": [AS_OF]}, "wrong_as_of_request")
                            response = clients[scenario].get(parsed.path + "?" + parsed.query)
                            route.fulfill(status=response.status_code, content_type=response.headers.get("content-type", "application/json"),
                                          body=response.content)
                            require(response.status_code == 200, "real_as_of_api_failed")
                            body = response.json()
                            answers.append(check_answer(body, scenario))
                    page.route("**/*", bridge)
                    page.goto(ORIGIN)
                    expect(page.get_by_label("Preisgate", exact=True)).to_have_text(str(ready).lower())
                    require(len(answers) == 1, "as_of_request_count_mismatch")
                    check_ui(page, answers[0], expect)
                    if width == 390 or (scenario == "eur_identity" and width == 1440):
                        filename = f"{scenario}-{width}.png"
                        page.screenshot(path=str(output / filename), full_page=True, animations="disabled")
                        report["screenshots"].append(filename)
                    require(fingerprint(stores[scenario]) == before[scenario], "as_of_read_changed_database")
                    require(not errors and not prohibited, "browser_or_side_effect_error")
                    report["cases"].append(dict(scenario=scenario, width=width, http_status=200, gate_strict_ready=ready,
                                               assessment_status=answers[0]["status"], unchanged_database=True, overflow=False))
                finally:
                    context.close()
        require(len(report["cases"]) == 12 and binding() == sources, "case_count_or_source_binding_changed")
        require(all(fingerprint(store) == before[key] for key, store in stores.items()) and not prohibited, "database_or_side_effect_changed")
        report.update(passed=True, cases_passed=12, real_api=True, real_synthetic_duckdb=True,
                      provider_pipeline_review_calls=0, response_bytes_unmodified=True, no_server=True, tax_release_claimed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-modules", type=Path, default=ROOT / "frontend/node_modules")
    parser.add_argument("--browser-executable")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = dict(format_version=1, passed=False, synthetic=True, cases=[], screenshots=[])
    output = None
    try:
        output = new_output(args.output)
        run(args, output, report)
    except ProbeFailure as error:
        report["error"] = str(error)
    except Exception:
        report["error"] = "price_time_backend_browser_failed"
    if output is not None:
        (output / "summary.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="ascii")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, sort_keys=True))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
