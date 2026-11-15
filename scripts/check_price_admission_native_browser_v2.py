"""Nativer Admission-Browsernachweis: echte API, isolierte synthetische DuckDB.

Keine Admission-/Gate-Response-Mocks. Nur Loopback, keine produktiven Daten.
Der manuelle Import wird vor der Finanzdaten-Baseline synthetisch vorbereitet.
"""
import argparse
import base64
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import traceback
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright


AT = datetime(2025, 6, 13, 1, tzinfo=timezone.utc)
REFERENCE = AT - timedelta(minutes=30)
METHOD = b"Synthetic BTC observed EUR100 quote, available at cutoff; no overall release."
METHOD_SHA = hashlib.sha256(METHOD).hexdigest()
PRICE_ORIGINAL = b"Synthetic BTC original: EUR100 at 2025-06-13T00:30:00Z"
SUMMARY = "Preiszeit und Methode menschlich bestätigen"
POSITIVE = "Preiszeit und Methode für diesen Bewertungszeitpunkt menschlich bestätigt."
GROUP = "Gebundene Preiszeitprüfung"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_manifest(root):
    return {str(path.relative_to(root)): digest(path)
            for directory in (root / "src/steuerreport_v2", root / "frontend/src")
            for path in sorted(directory.rglob("*"))
            if path.is_file() and path.suffix in {".py", ".ts", ".tsx", ".css"}}


def git(root, *args):
    return subprocess.check_output(["git", "-c", f"safe.directory={root}", "-C", str(root), *args])


def bundle(source, modules, evidence_path):
    entry = '''import React,{useEffect,useState} from "react";
import {createRoot} from "react-dom/client";
import {PriceAdmission} from "./src/workspace/PriceAdmission";
import {PriceAdmissionEvidence} from "./src/workspace/PriceAdmissionEvidence";
import {readApi} from "./src/workspace/resource";
function NativeFixture(){
  const [binding,setBinding]=useState(null),[gate,setGate]=useState(null),[error,setError]=useState("");
  useEffect(()=>{readApi(EVIDENCE_PATH).then(setBinding).catch(()=>setError("Importbindung konnte nicht gelesen werden."));
    window.readNativeGate=async(at)=>{const value=await readApi("/api/v1/prices/as-of-gate?as_of="+encodeURIComponent(at));setGate(value);return value};
  },[]);
  const candidate=gate?.candidates.find(row=>row.asset==="BTC");
  return <main className="wsPage wsPriceWorkspace" style={{maxWidth:1040,margin:"auto",padding:16}}>
    {error&&<p role="alert">{error}</p>}
    {binding&&<PriceAdmission previewId={binding.preview_id} priceId={binding.price_id} previewSha256={binding.preview_sha256}
      priceFingerprint={binding.price_fingerprint} asset={binding.asset} originals={binding.originals}
      priceEur={binding.price_eur} storedReferenceAt={binding.stored_reference_at}/>}
    {gate&&<section aria-label="Nativer Stichtagsnachweis"><p role="status">{gate.strict_ready?"Stichtagsprüfung: Preiszeit bestätigt":"Stichtagsprüfung: nicht bereit"}</p>
      {candidate&&<PriceAdmissionEvidence admission={candidate.price_admission} legacy={candidate.price_time} asset={candidate.asset} valuationAt={gate.as_of}/>}
    </section>}
  </main>
}createRoot(document.getElementById("root")).render(<NativeFixture/>);'''
    options = {"stdin": {"contents": entry, "resolveDir": str(source / "frontend"), "loader": "tsx"},
               "nodePaths": [str(modules)], "bundle": True, "write": False, "format": "iife", "jsx": "automatic",
               "define": {"import.meta.env.VITE_API_BASE": '""', "EVIDENCE_PATH": json.dumps(evidence_path)}}
    command = f'''import {{build}} from {json.dumps((modules / "esbuild/lib/main.js").as_uri())};
const result=await build({json.dumps(options)});process.stdout.write(result.outputFiles[0].text);'''
    javascript = subprocess.check_output(["node", "--input-type=module", "-e", command], text=True)
    css = (source / "frontend/src/styles.css").read_text() + (source / "frontend/src/workspace/workspace.css").read_text()
    return f'<!doctype html><html lang="de"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"><style>{css}</style><div id="root"></div><script>{javascript}</script></html>'


@contextmanager
def loopback_only(blocked, port):
    original = socket.socket.connect
    original_ex = socket.socket.connect_ex

    def check(sock, address):
        if sock.family == socket.AF_UNIX:
            return
        if not isinstance(address, tuple) or address[0] != "127.0.0.1" or address[1] != port[0]:
            blocked.append({"kind": "python_socket", "address": str(address)[:200]})
            raise RuntimeError("native_browser_non_fixture_network_forbidden")

    def connect(sock, address):
        check(sock, address)
        return original(sock, address)

    def connect_ex(sock, address):
        check(sock, address)
        return original_ex(sock, address)

    with patch.object(socket.socket, "connect", connect), patch.object(socket.socket, "connect_ex", connect_ex):
        yield


@contextmanager
def running_server(app, active_port):
    import uvicorn

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    sock.listen(32)
    active_port[0] = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False, lifespan="off", loop="asyncio"))
    worker = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    worker.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started and worker.is_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert server.started and worker.is_alive(), "isolated_loopback_server_not_started"
        yield f"http://127.0.0.1:{active_port[0]}"
    finally:
        server.should_exit = True
        worker.join(20)
        sock.close()
        assert not worker.is_alive(), "isolated_server_did_not_stop"
        active_port[0] = None


def isolate_environment(runtime):
    for name in list(os.environ):
        if name.startswith("STEUERREPORT_"):
            del os.environ[name]
    values = {"V2_ROOT": runtime, "V2_DB": runtime / "unused-default.duckdb", "STATE_DIR": runtime / "state",
              "PRIVATE_PROFILE": "", "PRIVATE_CONFIG_DIR": runtime / "configs", "USERTRANSFER_ROOT": runtime / "imports",
              "ALLOWED_HOSTS": "127.0.0.1", "CORS_ORIGINS": ""}
    for name in ("SPARKASSE_CAMT_DIR", "SPARKASSE_STATEMENT_DIR", "TRADE_REPUBLIC_DOCUMENT_ROOT", "INHERITANCE_DOCUMENT_ROOT"):
        values[name] = runtime / "empty-documents"
    os.environ.update({"STEUERREPORT_" + key: str(value) for key, value in values.items()})
    (runtime / "configs").mkdir()
    (runtime / "configs/crypto_price_sources.json").write_text(json.dumps({"assets": [
        {"symbol": "BTC", "coingecko_id": "synthetic-bitcoin", "defillama_id": None},
    ]}))
    os.chdir(runtime)


def fixture(root):
    from steuerreport_v2.contracts.events import CanonicalEventCreate
    from steuerreport_v2.contracts.historical_prices import HistoricalPriceApply, HistoricalPriceQuery, ManualHistoricalPricePreviewRequest
    from steuerreport_v2.db.duckdb_store import DuckDbStore
    from steuerreport_v2.domain.historical_prices import HistoricalPriceService

    root.mkdir()
    store = DuckDbStore(root / "synthetic.duckdb")
    store.add_canonical_event(CanonicalEventCreate(source="synthetic-native-browser", source_ref="position", asset="BTC",
        quantity=Decimal("2"), event_time=AT - timedelta(minutes=15), event_type="transfer", account="synthetic-wallet"))
    history = HistoricalPriceService(store)
    query = HistoricalPriceQuery(scope="all_observed", assets=["BTC"])
    planned = history.plan(query)
    preview = history.manual_preview(ManualHistoricalPricePreviewRequest.model_validate({
        "request_id": str(uuid4()), "query": query, "plan_sha256": planned["plan_sha256"],
        "asset": "BTC", "price_date": AT.date(), "price_value": "100", "price_currency": "EUR", "priced_at": REFERENCE,
        "price_evidence": {"filename": "synthetic-price.txt", "media_type": "text/plain", "source_name": "Synthetic original",
                           "source_reference": "synthetic row 1", "source_observed_at": AT,
                           "content_base64": base64.b64encode(PRICE_ORIGINAL).decode()},
    }))
    assert preview["status"] == "ready", preview.get("validation_errors")
    history.apply(preview["id"], HistoricalPriceApply(preview_sha256=preview["preview_sha256"],
        actor="Synthetic fixture setup", confirm_prices=True, confirm_recalculation=True))
    binding, = preview["price_bindings"]
    assert store.path.resolve().is_relative_to(root.resolve())
    return store, history, preview, binding


def database_rows(store):
    with store.connect() as con:
        names = [row[0] for row in con.execute("select table_name from information_schema.tables where table_schema='main' order by table_name").fetchall()]
        return {name: con.execute('select * from "' + name.replace('"', '""') + '" order by all').fetchall() for name in names}


def original_files(root):
    return {str(path.relative_to(root)): digest(path) for path in sorted(root.rglob("*"))
            if path.is_file() and "admissions" not in path.relative_to(root).parts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    own = Path(__file__).resolve().parents[1]
    parser.add_argument("--source-root", type=Path, default=own)
    parser.add_argument("--node-modules", type=Path, default=own / "frontend/node_modules")
    parser.add_argument("--output", type=Path, default=own / "var/price-admission-native")
    parser.add_argument("--widths", nargs="+", type=int, default=[390, 768, 1280, 1440], choices=[390, 768, 1280, 1440])
    parser.add_argument("--browser-executable")
    parser.add_argument("--keep-synthetic-runtime", action="store_true", help="Auch nach Erfolg nur die eigene synthetische Runtime zur Analyse behalten")
    parser.add_argument("--previous-proof", type=Path, action="append", default=[], help="Vorherigen Nachweis unveraendert erhalten und Source-Geltung vergleichen")
    args = parser.parse_args()
    source, output, modules = args.source_root.resolve(), args.output.resolve(), args.node_modules.resolve()
    if not output.is_relative_to(own / "var"):
        parser.error("Artefakte nur im eigenen ignorierten var")
    for name in ("PriceAdmission.tsx", "PriceAdmissionEvidence.tsx"):
        if not (source / "frontend/src/workspace" / name).is_file():
            parser.error("Integriertes --source-root mit beiden Admission-Komponenten erforderlich")
    sys.dont_write_bytecode = True
    output.mkdir(parents=True, exist_ok=True)
    runtime = output / ("runtime-" + str(uuid4()))
    runtime.mkdir()
    initial_sources = source_manifest(source)
    previous_proofs = []
    for directory in args.previous_proof:
        directory = directory.resolve()
        previous_report = json.loads((directory / "summary.json").read_text())
        previous_sources = json.loads((directory / "source-freeze.json").read_text())["files_sha256"]
        differences = sorted(name for name in set(initial_sources) | set(previous_sources)
                             if initial_sources.get(name) != previous_sources.get(name))
        previous_proofs.append({"directory": str(directory), "summary_sha256": digest(directory / "summary.json"),
            "original_status": previous_report["status"], "source_matches_current": not differences,
            "usable_for_current_source": not differences and previous_report["status"] == "passed",
            "invalidated_for_current_source": bool(differences), "changed_source_files": differences})
    source_info = {"root": str(source), "head": git(source, "rev-parse", "HEAD").decode().strip(),
                   "uncommitted_diff_sha256": hashlib.sha256(git(source, "diff", "HEAD", "--", "src", "frontend/src")).hexdigest(),
                   "files_sha256": initial_sources}
    (output / "source-freeze.json").write_text(json.dumps(source_info, indent=2))
    frozen_own = {name: digest(own / name) for name in ("frontend/src/workspace/PriceAdmission.tsx", "scripts/check_price_admission_browser_v2.py")}
    isolate_environment(runtime)
    sys.path.insert(0, str(source / "src"))
    results, requests, blocked, js_errors, invariants = [], [], [], [], []
    active_port = [None]
    events = output / "events.jsonl"
    events.write_text("")

    def record(width, step, action):
        row = {"width": width, "step": step, "status": "passed"}
        try:
            value = action()
        except Exception as exc:
            row.update(status="failed", error=str(exc)[:2500], traceback=traceback.format_exc()[-6000:])
            results.append(row)
            with events.open("a") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            raise
        results.append(row)
        with events.open("a") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        return value

    with loopback_only(blocked, active_port):
        from fastapi.responses import HTMLResponse, JSONResponse
        from steuerreport_v2.api.app import create_app
        from steuerreport_v2.domain.pipeline import PipelineService

        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path=args.browser_executable)
            try:
                for width in args.widths:
                    page = None
                    context = None
                    try:
                        store, history, preview, binding = record(width, "synthetic_manual_import_setup", lambda: fixture(runtime / str(width)))
                        app = create_app(store)
                        base = f"/api/v1/prices/historical/previews/{preview['id']}/prices/{binding['price_id']}"
                        document = bundle(source, modules, base + "/evidence")

                        @app.get("/__native_fixture__", response_class=HTMLResponse)
                        def fixture_html():
                            return document

                        def allowed(method, path, query):
                            if method == "GET" and path == "/__native_fixture__" and not query:
                                return True
                            if method == "GET" and path in {"/api/v1/prices/as-of-gate", "/api/v1/portfolio/as-of"}:
                                return set(parse_qs(query)) == {"as_of"}
                            if method == "GET" and path == "/api/v1/divorce/equalization-summary":
                                return set(parse_qs(query)) == {"cutoff_at", "valuation_at"}
                            if not path.startswith(base):
                                return False
                            suffix = path[len(base):]
                            if suffix == "/evidence" and method == "GET" and not query:
                                return True
                            if suffix == "/admissions" and method == "GET":
                                return set(parse_qs(query)) == {"valuation_at"}
                            if query:
                                return False
                            if suffix == "/admission-previews":
                                return method == "POST"
                            uuid_path = r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}"
                            if re.fullmatch(r"/admission-previews/" + uuid_path + r"(?:/method-original)?", suffix):
                                return method == "GET"
                            return method == "POST" and bool(re.fullmatch(r"/admission-previews/" + uuid_path + r"/apply|/admissions/" + uuid_path + r"/revoke", suffix))

                        @app.middleware("http")
                        async def fixture_scope(request, call_next):
                            if not allowed(request.method, request.url.path, request.url.query):
                                blocked.append({"kind": "server_route", "method": request.method, "path": request.url.path})
                                return JSONResponse({"detail": "native_fixture_route_forbidden"}, status_code=403)
                            response = await call_next(request)
                            requests.append({"width": width, "method": request.method, "path": request.url.path,
                                             "query": request.url.query, "status": response.status_code})
                            return response

                        baseline = database_rows(store)
                        financial = {key: value for key, value in baseline.items() if key != "review_decisions"}
                        reviews = {row[0]: row for row in baseline["review_decisions"]}
                        originals = original_files(history.root)

                        def unchanged(extra_reviews):
                            now = database_rows(store)
                            assert {key: value for key, value in now.items() if key != "review_decisions"} == financial, "financial_or_non_review_database_rows_changed"
                            current_reviews = {row[0]: row for row in now["review_decisions"]}
                            assert len(current_reviews) == len(reviews) + extra_reviews, "unexpected_review_count"
                            assert all(current_reviews.get(key) == value for key, value in reviews.items()), "existing_review_modified"
                            assert original_files(history.root) == originals, "original_import_bytes_changed"
                            assert source_manifest(source) == initial_sources, "coordinator_source_changed_during_run"
                            invariants.append({"width": width, "extra_reviews": extra_reviews, "non_review_tables_unchanged": len(financial)})
                            return current_reviews

                        def no_pipeline(*_args, **_kwargs):
                            blocked.append({"kind": "pipeline_after_fixture"})
                            raise AssertionError("native_admission_must_not_recalculate_financials")

                        with patch.object(PipelineService, "rebuild_all", no_pipeline), patch.object(PipelineService, "rebuild_ledgers", no_pipeline), running_server(app, active_port) as origin:
                            context = browser.new_context(viewport={"width": width, "height": 1000}, device_scale_factor=1,
                                service_workers="block", reduced_motion="reduce", locale="de-DE", accept_downloads=True)
                            page = context.new_page()
                            page.set_default_timeout(15000)
                            page.on("pageerror", lambda error: js_errors.append(str(error)))

                            def browser_network(route):
                                url = urlsplit(route.request.url)
                                if f"{url.scheme}://{url.netloc}" != origin or not allowed(route.request.method, url.path, url.query):
                                    blocked.append({"kind": "browser_route", "method": route.request.method, "url": route.request.url})
                                    route.abort()
                                else:
                                    route.continue_()

                            page.route("**/*", browser_network)
                            page.goto(origin + "/__native_fixture__#synthetic-native")
                            group = page.get_by_role("region", name=GROUP, exact=True)
                            evidence = page.get_by_role("region", name="Nativer Stichtagsnachweis", exact=True)
                            prepare = page.get_by_role("button", name="Technische Vorschau vorbereiten", exact=True)
                            apply = page.get_by_role("button", name="Menschliche Bestätigung speichern", exact=True)
                            def field(label):
                                return page.get_by_label(label, exact=True)

                            def open_editor():
                                summary = page.get_by_text(SUMMARY, exact=True)
                                summary.focus()
                                page.keyboard.press("Enter")
                                expect(prepare).to_be_disabled()
                                assert not any(row["method"] == "POST" and row["width"] == width for row in requests), "automatic_POST"

                            record(width, "real_import_evidence_props_no_auto_post", open_editor)

                            def get_gate(at, positive, expected_status=None):
                                gate = page.evaluate("at=>window.readNativeGate(at)", at.isoformat(timespec="microseconds"))
                                assert gate["strict_ready"] is positive and gate["gate"]["strict_ready"] is positive, gate
                                assert gate["gate"]["accepted_price_time_count"] == (1 if positive else 0), gate["gate"]
                                candidate, = gate["candidates"]
                                assert candidate["asset"] == "BTC" and Decimal(candidate["current_price_eur"]) == Decimal("100")
                                assert candidate["price_time"]["strict_eligible"] is False, "legacy_time_must_remain_independent"
                                admission = candidate["price_admission"]
                                if expected_status:
                                    assert admission["status"] == expected_status and admission["price_id"] == binding["price_id"]
                                else:
                                    assert admission is None
                                expect(evidence.get_by_text("Stichtagsprüfung: Preiszeit bestätigt" if positive else "Stichtagsprüfung: nicht bereit", exact=True)).to_be_visible()
                                if positive:
                                    expect(evidence.get_by_text(POSITIVE, exact=True)).to_be_visible()
                                else:
                                    expect(evidence.get_by_text(POSITIVE, exact=True)).to_have_count(0)
                                return gate

                            record(width, "baseline_gate_false", lambda: get_gate(AT, False))
                            record(width, "baseline_financial_and_review_snapshot", lambda: unchanged(0))

                            def get_summary(valuation_at, cutoff_positive, valuation_positive):
                                value = page.evaluate("""async args=>{
                                  const query=new URLSearchParams({cutoff_at:args[0],valuation_at:args[1]});
                                  const response=await fetch('/api/v1/divorce/equalization-summary?'+query);
                                  const envelope=await response.json();
                                  if(!response.ok||!['ok','warning'].includes(envelope.status))throw Error('native_summary_failed HTTP '+response.status+' '+JSON.stringify(envelope.detail||envelope.errors));
                                  return envelope.data;
                                }""", [(AT - timedelta(microseconds=1)).isoformat(timespec="microseconds"), valuation_at.isoformat(timespec="microseconds")])
                                for name, positive in (("cutoff_price_gate", cutoff_positive), ("valuation_price_gate", valuation_positive)):
                                    assert value[name]["strict_ready"] is positive, {name: value[name]}
                                    assert value[name]["accepted_price_time_count"] == (1 if positive else 0), {name: value[name]}
                                return value

                            def fill():
                                values = {"Netzwerk": "bitcoin", "Contract / eindeutige Assetkennung": "native", "Token-Dezimalstellen": "8",
                                    "Bewertungszeitpunkt (UTC)": "2025-06-13T01:00", "Beobachteter Kurswert": "100",
                                    "Beobachtet am (UTC)": "2025-06-13T00:30", "Preis veröffentlicht am (UTC)": "2025-06-13T00:30",
                                    "Fundstelle im Preisoriginal": "synthetic row 1", "Preisquelle": "Synthetic original", "Methodenkennung": "synthetic-observed-available",
                                    "Methodenversion": "1", "Methodenzeitzone": "UTC", "Bestätigende Person": "Synthetic browser reviewer",
                                    "Begründung": "Synthetic method/identity scope only; not a real review."}
                                for label, value in values.items():
                                    field(label).fill(value)
                                field("Preisoriginal").select_option(hashlib.sha256(PRICE_ORIGINAL).hexdigest())
                                field("Methodendokument (1 Byte bis 2 MiB)").set_input_files({"name": "synthetic-method.txt", "mimeType": "text/plain", "buffer": METHOD})
                                expect(prepare).to_be_enabled()

                            record(width, "explicit_facts_and_webcrypto_method", fill)

                            def post_preview():
                                with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith(base + "/admission-previews")) as event:
                                    prepare.focus()
                                    page.keyboard.press("Enter")
                                response = event.value
                                assert response.status == 200, response.text()
                                payload = response.request.post_data_json
                                assert "captured_at" not in payload["observation"] and payload["observation"]["fx"] is None
                                report = response.json()["data"]
                                assert report["status"] == "prepared" and report["can_apply"] is True, report
                                assert report["assessment"]["strict_eligible"] is False
                                assert report["assessment"]["reason_codes"] == ["approval_missing"]
                                assert report["method_original"]["sha256"] == METHOD_SHA == payload["method"]["evidence_sha256"]
                                assert report["price_id"] == binding["price_id"] and re.fullmatch(r"[a-f0-9]{64}", report["validation_policy_sha256"])
                                expect(group.get_by_role("heading", name="Technische Vorschau – noch nicht bestätigt", exact=True)).to_be_visible()
                                expect(apply).to_be_disabled()
                                return report

                            prepared = record(width, "native_prepare_not_approval", post_preview)
                            record(width, "prepare_does_not_write_reviews_or_financials", lambda: unchanged(0))
                            artifacts = {str(path.relative_to(history.root)): digest(path) for path in (history.root / "admissions").rglob("*") if path.is_file()}

                            def two_acks():
                                boxes = group.get_by_role("checkbox")
                                boxes.nth(0).focus()
                                page.keyboard.press("Space")
                                expect(apply).to_be_disabled()
                                boxes.nth(1).focus()
                                page.keyboard.press("Space")
                                expect(apply).to_be_enabled()

                            record(width, "two_separate_keyboard_acknowledgements", two_acks)

                            def approve():
                                with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/apply")) as event:
                                    apply.focus()
                                    page.keyboard.press("Enter")
                                response = event.value
                                assert response.status == 200, response.text()
                                assert response.request.post_data_json == {"draft_sha256": prepared["draft_sha256"], "acknowledge_original_verified": True, "acknowledge_scope_limited": True}
                                report = response.json()["data"]
                                assert report["status"] == "human_approved" and report["assessment"]["strict_eligible"] is True, report
                                expect(group.get_by_role("heading", name="Menschliche Bestätigung für diese Preis-ID und diesen Bewertungszeitpunkt gespeichert", exact=True)).to_be_visible()
                                return report

                            approved = record(width, "native_apply", approve)
                            applied_reviews = record(width, "apply_only_appends_one_review", lambda: unchanged(1))

                            def read_status():
                                with page.expect_response(lambda r: "/admissions?" in r.url and r.request.method == "GET") as event:
                                    page.get_by_role("button", name="Bestätigungsstatus lesen", exact=True).click()
                                response = event.value
                                assert response.status == 200 and response.json()["data"] == approved, response.text()
                                expect(group).to_be_visible()

                            record(width, "real_get_admissions_after_apply", read_status)
                            exact = record(width, "real_asof_exact_cutoff_true", lambda: get_gate(AT, True, "human_approved"))
                            summary_exact = record(width, "real_summary_exact_valuation_true_earlier_cutoff_unapproved", lambda: get_summary(AT, False, True))

                            def selected_id():
                                result = page.evaluate("async at=>{const r=await fetch('/api/v1/portfolio/as-of?as_of='+encodeURIComponent(at));if(!r.ok)throw Error('portfolio_failed');return r.json()}", AT.isoformat())
                                position, = result["data"]["positions"]
                                assert position["price_id"] == binding["price_id"], "actual_portfolio_selected_price_id_not_bound"
                                assert Decimal(position["price_eur"]) == 100

                            record(width, "actual_portfolio_selected_price_id", selected_id)
                            record(width, "real_asof_plus_one_microsecond_false", lambda: get_gate(AT + timedelta(microseconds=1), False))
                            record(width, "real_summary_valuation_plus_one_microsecond_false", lambda: get_summary(AT + timedelta(microseconds=1), False, False))
                            record(width, "exact_cutoff_positive_again", lambda: get_gate(AT, True, "human_approved"))

                            def focus_layout():
                                summary = evidence.get_by_text("Entscheidung und Legacy-Diagnose", exact=True)
                                summary.focus()
                                page.keyboard.press("Enter")
                                expect(evidence.get_by_text(approved["price_id"], exact=True)).to_be_visible()
                                assert page.evaluate("document.compatMode==='CSS1Compat' && document.documentElement.scrollWidth<=innerWidth"), "document_overflow"
                                overflow = page.locator("main").evaluate("""el=>[...el.querySelectorAll('input,select,textarea,button,p,dd,dt,a,summary')].filter(n=>n.getClientRects().length).flatMap(n=>{
                                  const r=n.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth+1?[]:[{tag:n.tagName,left:r.left,right:r.right,text:n.textContent.slice(0,100)}]})""")
                                assert not overflow, overflow
                                page.screenshot(path=str(output / f"approved-{width}.png"), full_page=True)
                                summary.press("Enter")

                            record(width, "actual_admission_evidence_keyboard_and_overflow", focus_layout)

                            def download():
                                group.get_by_text("Methode, Originale und technische Bindung", exact=True).click()
                                link = group.get_by_role("link", name="Methodendokument herunterladen", exact=True)
                                url = urlsplit(link.evaluate("element=>element.href"))
                                assert f"{url.scheme}://{url.netloc}" == origin, "method_download_left_fixture_origin"
                                assert url.path == base + f"/admission-previews/{prepared['request_id']}/method-original", "method_download_not_bound_to_current_draft"
                                assert not url.query and not url.fragment, "method_download_unexpected_url_parameters"
                                link.focus()
                                expect(link).to_be_focused()
                                with page.expect_download() as event:
                                    link.press("Enter")
                                saved = output / f"downloaded-method-{width}.txt"
                                event.value.save_as(saved)
                                assert saved.read_bytes() == METHOD and digest(saved) == METHOD_SHA
                                assert event.value.suggested_filename == "synthetic-method.txt"

                            record(width, "actual_method_download_exact_bytes", download)
                            record(width, "all_reads_leave_financials_and_reviews_unchanged", lambda: unchanged(1))

                            def revoke():
                                group.get_by_text("Bestätigung ausdrücklich widerrufen", exact=True).click()
                                button = group.get_by_role("button", name="Bestätigung widerrufen", exact=True)
                                expect(button).to_be_disabled()
                                field("Widerrufende Person").fill("Synthetic browser revoker")
                                field("Widerrufsbegründung").fill("Synthetic withdrawal; retain original decision.")
                                expect(button).to_be_disabled()
                                group.get_by_role("checkbox").check()
                                with page.expect_response(lambda r: r.request.method == "POST" and r.url.endswith("/revoke")) as event:
                                    button.focus()
                                    page.keyboard.press("Enter")
                                response = event.value
                                assert response.status == 200, response.text()
                                report = response.json()["data"]
                                assert report["status"] == "revoked" and report["assessment"]["strict_eligible"] is False
                                assert report["decision"] == approved["decision"] and report["revocation"] is not None
                                expect(group.get_by_role("heading", name="Menschliche Bestätigung widerrufen", exact=True)).to_be_visible()
                                return report

                            revoked = record(width, "native_explicit_revoke", revoke)

                            def append_only():
                                current = unchanged(2)
                                assert all(current.get(key) == value for key, value in applied_reviews.items()), "apply_review_not_append_only"
                                assert {str(path.relative_to(history.root)): digest(path) for path in (history.root / "admissions").rglob("*") if path.is_file()} == artifacts, "draft_or_method_original_changed"

                            record(width, "revoke_append_only_and_artifacts_immutable", append_only)
                            after = record(width, "real_gate_false_after_revoke", lambda: get_gate(AT, False, "revoked"))
                            summary_revoked = record(width, "real_summary_both_price_gates_false_after_revoke", lambda: get_summary(AT, False, False))
                            assert exact["gate"]["price_admission_state_sha256"] != after["gate"]["price_admission_state_sha256"]
                            record(width, "after_revoke_reads_are_financially_unchanged", lambda: unchanged(2))
                            expect(evidence.get_by_text("Keine aktuell bestätigte Preiszeit-/Methodenzuordnung.", exact=True)).to_be_visible()
                            page.screenshot(path=str(output / f"revoked-{width}.png"), full_page=True)
                            (output / f"lifecycle-{width}.json").write_text(json.dumps({"preview": preview["id"], "price_id": binding["price_id"],
                                "prepared": prepared, "approved": approved, "revoked": revoked, "exact_cutoff": exact, "after_revoke": after}, indent=2))
                            (output / f"summary-reports-{width}.json").write_text(json.dumps({"exact_cutoff": summary_exact, "after_revoke": summary_revoked}, indent=2))
                            assert not blocked and not js_errors
                    except Exception:
                        if page is not None:
                            page.screenshot(path=str(output / f"failure-{width}.png"), full_page=True)
                            (output / f"failure-{width}.html").write_text(page.content())
                        if not results or results[-1]["status"] != "failed":
                            results.append({"width": width, "step": "lifecycle", "status": "failed", "error": traceback.format_exc()[-6000:]})
                    finally:
                        if context is not None:
                            context.close()
            finally:
                browser.close()
    changed = source_manifest(source) != initial_sources
    own_unchanged = all(digest(own / name) == sha for name, sha in frozen_own.items())
    failures = [row for row in results if row["status"] == "failed"]
    report = {"status": "failed" if failures or blocked or js_errors or changed or not own_unchanged else "passed",
        "scope": "real_coordinator_components_actual_fastapi_routes_isolated_duckdb_not_full_main_app",
        "widths": args.widths, "steps": len(results), "failures": len(failures), "results": results,
        "source_root": str(source), "source_head": source_info["head"], "source_changed_during_run": changed,
        "source_manifest": str(output / "source-freeze.json"), "script_sha256": digest(Path(__file__)),
        "previous_proofs": previous_proofs,
        "own_frozen_files_unchanged": own_unchanged, "own_frozen_sha256": frozen_own,
        "requests": requests, "blocked_requests": blocked, "javascript_errors": js_errors, "financial_invariants": invariants,
        "mocked_admission_responses": 0, "mocked_gate_responses": 0,
        "isolation": "runtime environment and private config replaced before product imports; loopback-only server; provider sockets forbidden",
        "reader_limit": "No physical read-only API claim; actual product connection/schema initialization behavior is unchanged."}
    cleanup = {"path": str(runtime), "status": "kept_failure" if report["status"] != "passed" else "kept_requested"}
    # All browser contexts and loopback servers have exited before cleanup.
    if report["status"] == "passed" and not args.keep_synthetic_runtime:
        try:
            if (active_port[0] is not None or runtime.is_symlink() or runtime.resolve(strict=True).parent != output
                    or not re.fullmatch(r"runtime-[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", runtime.name)):
                raise ValueError("synthetic_runtime_cleanup_guard_failed")
            os.chdir(output)
            shutil.rmtree(runtime)
            cleanup["status"] = "removed"
        except (OSError, ValueError) as exc:
            report["status"] = "failed"
            cleanup.update(status="failed", error=type(exc).__name__)
    report["synthetic_runtime_cleanup"] = cleanup
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({key: value for key, value in report.items() if key not in {"results", "requests", "financial_invariants"}}, ensure_ascii=False))
    if report["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
