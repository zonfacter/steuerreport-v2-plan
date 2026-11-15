"""64 Browserfaelle mit echter FastAPI-Statusroute und eigener synthetischer DuckDB.

Kein HTTP-Server, keine Provider, keine Pipelineausfuehrung. Playwright bekommt
unveraenderte TestClient-Antwortbytes. Nur prepare/marker/record seeden Belege;
allow_export=False im Fake-PipelineResult ist keine Jahresfreigabe.
Bestehende Frontendabhaengigkeiten via --node-modules, keine Installation.
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
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5


ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://synthetic.invalid"
KINDS = ("current_portfolio", "historical")
WIDTHS = (390, 768, 1280, 1440)
STATES = (
    "recorded_completed", "recorded_failed", "recorded_empty", "checkpoint_not_started",
    "checkpoint_running", "legacy_record", "unknown_reserved", "not_found",
)
PATHS = {
    "current_portfolio": "/api/v1/prices/backfill/current-portfolio/status",
    "historical": "/api/v1/prices/backfill/external/status",
}
TITLES = {
    "current_portfolio": "Portfolio-Preisauftrag pr\u00fcfen",
    "historical": "Historischer Direktabruf: Preisauftrag pr\u00fcfen",
}
STATUS_LABELS = {
    "recorded": "Finale damalige Antwort gespeichert.",
    "checkpointed": "Preisspeicherung belegt; finale Antwort fehlt.",
    "unknown_or_running": "Ausgang unbekannt oder Auftrag noch in Arbeit; Abschluss nicht best\u00e4tigt.",
    "not_found": "Kein gespeicherter Auftrag zu dieser Kennung gefunden; kein Abschlussnachweis.",
}
PIPELINE_LABELS = {
    "not_started": "Pipeline damals nicht gestartet.",
    "running_or_interrupted": "Pipelinebeginn vorgemerkt; Lauf und Abschluss nicht best\u00e4tigt.",
    "completed": "Pipeline damals abgeschlossen.",
    "failed": "Pipeline fehlgeschlagen; Folgen unbekannt oder teilweise.",
}
SOURCE = "synthetic-checkpoint-browser"
STAMP = datetime(2026, 11, 15, 12, tzinfo=UTC)
BIND_FILES = (
    "scripts/check_price_checkpoint_backend_browser_v2.py",
    "frontend/src/workspace/CurrentPriceRequestStatus.tsx", "frontend/src/api-base.ts",
    "frontend/src/styles.css", "frontend/src/workspace/workspace.css", "frontend/package.json",
    "src/steuerreport_v2/api/app.py", "src/steuerreport_v2/db/duckdb_store.py",
    "src/steuerreport_v2/contracts/prices.py", "src/steuerreport_v2/domain/external_price_backfill.py",
)


class ProbeFailure(RuntimeError):
    pass


def require(condition, code):
    if not condition:
        raise ProbeFailure(code)


def source_binding():
    files = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in BIND_FILES}
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"sha256": digest, "files": files}


def new_output(value):
    if value is None:
        return Path(tempfile.mkdtemp(prefix="price-checkpoint-backend-browser-", dir="/tmp"))
    output = value.expanduser().absolute()
    resolved = output.resolve()
    allowed = resolved.is_relative_to(Path("/tmp")) or (
        resolved.is_relative_to(ROOT / "var") and (ROOT / "var").resolve() == ROOT / "var"
    )
    require(allowed and not output.exists() and not output.is_symlink(), "output_must_be_new_tmp_or_var")
    output.mkdir(mode=0o700, parents=True)
    return output


def bundle_component(node_modules):
    modules = node_modules.expanduser().resolve()
    require((modules / "esbuild/lib/main.js").is_file(), "existing_esbuild_required")
    require((modules / "react/package.json").is_file(), "existing_react_required")
    require((modules / "react-dom/package.json").is_file(), "existing_react_dom_required")
    require((modules / "lucide-react/package.json").is_file(), "existing_lucide_required")
    entry = '''import React from "react";
import {createRoot} from "react-dom/client";
import {CurrentPriceRequestStatus,rememberCurrentPriceRequest,rememberHistoricalPriceRequest}
  from "./src/workspace/CurrentPriceRequestStatus";
window.rememberPriceRequest={current_portfolio:rememberCurrentPriceRequest,historical:rememberHistoricalPriceRequest};
const kind=location.pathname === "/historical" ? "historical" : "current_portfolio";
createRoot(document.getElementById("root")).render(<CurrentPriceRequestStatus kind={kind}/>);'''
    code = f'''const {{build}}=await import({json.dumps((modules / "esbuild/lib/main.js").as_uri())});
const result=await build({{stdin:{{contents:{json.dumps(entry)},resolveDir:process.cwd(),loader:"tsx"}},
bundle:true,write:false,format:"iife",jsx:"automatic",nodePaths:[{json.dumps(str(modules))}],
alias:{{react:{json.dumps(str(modules / "react"))},"react-dom":{json.dumps(str(modules / "react-dom"))},
"lucide-react":{json.dumps(str(modules / "lucide-react"))}}},
define:{{"import.meta.env.VITE_API_BASE":'""'}}}});
process.stdout.write(result.outputFiles[0].text);'''
    try:
        process = subprocess.run(["node", "--input-type=module", "-e", code], cwd=ROOT / "frontend",
                                 capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        raise ProbeFailure("frontend_bundle_failed") from None
    require(process.returncode == 0 and bool(process.stdout), "frontend_bundle_failed")
    styles = "\n".join((ROOT / name).read_text(encoding="utf-8") for name in (
        "frontend/src/styles.css", "frontend/src/workspace/workspace.css",
    ))
    return ('<!doctype html><html lang="de"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<style>{styles}</style></head><body><main id="root"></main>'
            f'<script>{process.stdout}</script></body></html>')


def fingerprint(store):
    digest = hashlib.sha256()
    with store.read_snapshot() as snapshot, snapshot.connect() as connection:
        names = connection.execute(
            "select table_name from information_schema.tables "
            "where table_schema='main' and table_type='BASE TABLE' order by table_name"
        ).fetchall()
        for (name,) in names:
            quoted = '"' + name.replace('"', '""') + '"'
            rows = connection.execute("select * from " + quoted + " order by all").fetchall()
            digest.update(json.dumps([name, rows], default=str, ensure_ascii=True,
                                     separators=(",", ":")).encode())
    return digest.hexdigest()


def seed(store):
    from steuerreport_v2.contracts.pipeline import PipelineResult
    from steuerreport_v2.contracts.prices import (
        CurrentPortfolioPriceBackfillJob, CurrentPortfolioPriceBackfillResult,
        ExternalPriceBackfillJob, ExternalPriceBackfillResult, PricePointCreate,
    )
    from steuerreport_v2.domain.external_price_backfill import ExternalPriceBackfillService

    cases = {}
    for kind in KINDS:
        for state in STATES:
            identifier = str(uuid5(NAMESPACE_URL, "synthetic-price-checkpoint:" + kind + ":" + state))
            key = (ExternalPriceBackfillService._explicit_current_request_hash(identifier)
                   if kind == "current_portfolio" else
                   ExternalPriceBackfillService._explicit_historical_request_hash(identifier))
            reserve = (store.reserve_current_price_backfill if kind == "current_portfolio"
                       else store.reserve_historical_price_backfill)
            entry = {"request_id": identifier, "stored_ids": [], "source": None}
            cases[kind, state] = entry
            if state == "not_found":
                continue
            require(reserve(key) is True, "synthetic_reservation_failed")
            if state == "unknown_reserved":
                continue
            phase = "not_started" if state == "recorded_empty" else "failed" if state == "recorded_failed" else "completed"
            if state == "legacy_record":
                # Deliberately unproven old receipt, not a claim of price presence.
                ids = [str(uuid5(NAMESPACE_URL, "synthetic-legacy-price:" + kind))]
            else:
                payloads = [] if state == "recorded_empty" else [PricePointCreate(
                    asset="SYNTHETIC", price_eur=Decimal("1"), priced_at=STAMP, source=SOURCE,
                )]
                prices = store.prepare_price_backfill(key, kind, payloads)
                ids = [price.price_id for price in prices]
                entry["source"] = SOURCE if prices else None
            entry["stored_ids"] = ids
            if state == "checkpoint_not_started":
                continue
            if ids and state != "legacy_record":
                store.mark_price_backfill_pipeline_started(key, kind)
            if state == "checkpoint_running":
                continue
            partial = state == "recorded_completed"
            common = dict(
                configured_assets=["SYNTHETIC"], asset_filter=[], planned_jobs=len(ids), attempted=len(ids) + int(partial),
                imported_prices=len(ids), skipped=2 if partial else 0, failed=int(partial), dry_run=False,
                stored_price_ids=ids, pipeline_status=phase,
                pipeline_effects={"completed": "completed", "failed": "unknown_or_partial", "not_started": "not_started"}[phase],
                result_journal_status="recorded",
                pipeline=PipelineResult(normalized_events=0, balance_entries=0, flow_entries=0,
                                        tax_lines=0, review_issues_open=0, allow_export=False) if phase == "completed" else None,
            )
            job_model = CurrentPortfolioPriceBackfillJob if kind == "current_portfolio" else ExternalPriceBackfillJob
            job_extra = {} if kind == "current_portfolio" else {"price_date": STAMP.date()}
            jobs = [job_model(asset="SYNTHETIC", status="imported", price_eur=Decimal("1"), source=SOURCE,
                              **job_extra)] if ids else []
            if partial:
                jobs.append(job_model(asset="SYNTHETIC", status="failed", reason="price_provider_error", **job_extra))
            result = (CurrentPortfolioPriceBackfillResult(portfolio_assets_count=1, priced_at=STAMP, jobs=jobs, **common)
                      if kind == "current_portfolio" else
                      ExternalPriceBackfillResult(requirements_count=1, jobs=jobs, **common))
            raw = result.model_dump_json()
            if state == "legacy_record":
                old = json.loads(raw)
                old.pop("operation_kind")
                old.pop("result_journal_status")
                raw = json.dumps(old, separators=(",", ":"))
            record = (store.record_current_price_backfill if kind == "current_portfolio"
                      else store.record_historical_price_backfill)
            record(key, raw)
    return cases


def check_backend(kind, state, case, body):
    expected = expected_status(state)
    data = body["data"]
    require(body["status"] in {"ok", "warning"} and data["status"] == expected, "backend_status_mismatch")
    result, checkpoint = data.get("result"), data.get("checkpoint")
    require((result is not None) == (expected == "recorded"), "backend_result_mismatch")
    has_checkpoint = expected in {"recorded", "checkpointed"} and state != "legacy_record"
    require((checkpoint is not None) == has_checkpoint, "backend_checkpoint_mismatch")
    if checkpoint is not None:
        require(checkpoint["operation_kind"] == kind and checkpoint["stored_price_ids"] == case["stored_ids"],
                "backend_checkpoint_ids_mismatch")
        require(isinstance(data["checkpoint_sha256"], str) and len(data["checkpoint_sha256"]) == 64,
                "backend_checkpoint_hash_missing")
    else:
        require(data.get("checkpoint_sha256") is None, "backend_unproven_hash")
    if result is not None:
        require(result["stored_price_ids"] == case["stored_ids"], "backend_result_ids_mismatch")
        require(result["imported_prices"] == len(case["stored_ids"]), "backend_import_count_mismatch")
        if result.get("pipeline"):
            require(result["pipeline"]["allow_export"] is False, "synthetic_pipeline_claimed_release")
        if case["source"]:
            imported = [job for job in result["jobs"] if job["status"] == "imported"]
            require(imported and all(job["source"] == SOURCE for job in imported), "backend_source_changed")
    codes = {warning["code"] for warning in body.get("warnings", [])}
    if state == "recorded_completed":
        require({"price_provider_error", "price_backfill_partial_failure"} <= codes, "backend_partial_warnings_missing")
    if state == "recorded_failed":
        require("price_backfill_pipeline_failed" in codes, "backend_pipeline_warning_missing")
    return data


def expected_status(state):
    return ("not_found" if state == "not_found" else "unknown_or_running" if state == "unknown_reserved"
            else "checkpointed" if state.startswith("checkpoint_") else "recorded")


def check_browser(page, section, body, expect):
    data = body["data"]
    expect(section.get_by_text(STATUS_LABELS[data["status"]], exact=True)).to_be_visible()
    expect(section.get_by_text(data["explanation"], exact=True)).to_be_visible()
    result, checkpoint = data.get("result"), data.get("checkpoint")
    if result is not None:
        expect(section).to_contain_text(f'Damals gespeichert: {result["imported_prices"]} Preise.')
        expect(section).to_contain_text(f'Fehlgeschlagen: {result["failed"]}.')
        expect(section).to_contain_text(f'\u00dcbersprungen: {result["skipped"]}.')
        expect(section).to_contain_text(PIPELINE_LABELS[result["pipeline_status"]])
    else:
        expect(section).not_to_contain_text("Damals gespeichert:")
    if checkpoint is not None:
        details = section.locator("details")
        expect(details).to_have_count(1)
        details.locator("summary").click()
        ids = checkpoint["stored_price_ids"]
        expect(section).to_contain_text(f"Speicherbeleg: {len(ids)} damals gespeicherte Preis-IDs.")
        expect(section).to_contain_text(PIPELINE_LABELS[checkpoint["pipeline_status"]])
        expect(details.locator("time")).to_have_attribute("datetime", checkpoint["stored_at"])
        expect(details.get_by_text(data["checkpoint_sha256"], exact=True)).to_be_visible()
        listing = details.get_by_role("list", name="Damals gespeicherte Preis-IDs")
        if ids:
            expect(listing).to_be_visible()
            require(listing.locator("li").all_text_contents() == ids, "browser_checkpoint_ids_mismatch")
        else:
            expect(listing).to_have_count(0)
            expect(section).to_contain_text("Bekannt leer:")
    else:
        expect(section.locator("details")).to_have_count(0)
        if result is not None:
            expect(section).to_contain_text("Kein zus\u00e4tzlicher Speicherbeleg vorhanden")
    if result is not None or checkpoint is not None:
        expect(section).to_contain_text("Dies ist keine Jahresfreigabe.")
    if data["status"] in {"unknown_or_running", "not_found"} or (
        checkpoint is not None and checkpoint["pipeline_status"] != "completed"
    ):
        expect(section).not_to_contain_text(PIPELINE_LABELS["completed"])
    for warning in body.get("warnings", []):
        expect(section.get_by_text(warning["message"], exact=True)).to_be_visible()
    require(page.evaluate('''() => {
      if(document.documentElement.scrollWidth > innerWidth + 1) return false;
      return [...document.body.querySelectorAll("*")].every(el => {
        if(!el.getClientRects().length) return true;
        const r=el.getBoundingClientRect();
        return r.left >= -1 && r.right <= innerWidth + 1
          && !(el.clientWidth > 0 && el.scrollWidth > el.clientWidth + 1);
      });
    }'''), "browser_horizontal_overflow")


def run(args, output, report):
    with ExitStack() as stack:
        state = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix="price-checkpoint-private-", dir="/tmp")))
        stack.enter_context(patch.dict(os.environ))
        for name in list(os.environ):
            if name.startswith("STEUERREPORT_"):
                del os.environ[name]
        os.environ.update(STEUERREPORT_V2_ROOT=str(ROOT), STEUERREPORT_STATE_DIR=str(state),
                          STEUERREPORT_V2_DB=str(state / "synthetic.duckdb"),
                          STEUERREPORT_PRIVATE_PROFILE=str(state / "profile.json"),
                          STEUERREPORT_PRIVATE_CONFIG_DIR=str(state / "configs"),
                          STEUERREPORT_USERTRANSFER_ROOT=str(state / "imports"),
                          STEUERREPORT_V2_SECRET_VAULT_KEY_FILE=str(state / "vault.key"),
                          STEUERREPORT_V2_CONNECTOR_SETUP_TOKEN_FILE=str(state / "setup.token"))
        (state / "profile.json").write_text("{}", encoding="ascii")
        from fastapi.testclient import TestClient
        import httpx
        from playwright.sync_api import expect, sync_playwright
        from steuerreport_v2.api.app import create_app
        from steuerreport_v2.db.duckdb_store import DuckDbStore
        from steuerreport_v2.domain import external_price_backfill as backfill
        from steuerreport_v2.domain.pipeline import PipelineService

        binding = source_binding()
        report["source_binding"] = binding
        html = bundle_component(args.node_modules)
        report["bundle_sha256"] = hashlib.sha256(html.encode("utf-8")).hexdigest()
        store = DuckDbStore(state / "synthetic.duckdb")
        cases = seed(store)
        forbidden_calls = {"provider": 0, "pipeline": 0, "apply": 0, "store_write": 0, "network": 0}
        def forbidden(category):
            def fail(*arguments, **keywords):
                forbidden_calls[category] += 1
                raise ProbeFailure("forbidden_" + category)
            return fail
        stack.enter_context(patch.object(backfill, "managed_client", forbidden("provider")))
        stack.enter_context(patch.object(PipelineService, "rebuild_all", forbidden("pipeline")))
        for name in ("run", "run_current_portfolio"):
            stack.enter_context(patch.object(backfill.ExternalPriceBackfillService, name, forbidden("apply")))
        for name in ("reserve_current_price_backfill", "reserve_historical_price_backfill", "prepare_price_backfill",
                     "mark_price_backfill_pipeline_started", "record_current_price_backfill", "record_historical_price_backfill",
                     "add_price_point", "add_price_points"):
            stack.enter_context(patch.object(store, name, forbidden("store_write")))
        stack.enter_context(patch.object(httpx.HTTPTransport, "handle_request", forbidden("provider")))
        stack.enter_context(patch.object(httpx.AsyncHTTPTransport, "handle_async_request", forbidden("provider")))
        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex
        def connect(sock, address):
            if sock.family in {socket.AF_INET, socket.AF_INET6}:
                return forbidden("network")()
            return original_connect(sock, address)
        def connect_ex(sock, address):
            if sock.family in {socket.AF_INET, socket.AF_INET6}:
                return forbidden("network")()
            return original_connect_ex(sock, address)
        stack.enter_context(patch.object(socket.socket, "connect", connect))
        stack.enter_context(patch.object(socket.socket, "connect_ex", connect_ex))
        client = stack.enter_context(TestClient(create_app(store), raise_server_exceptions=False))
        paths = {route.path for route in client.app.routes if "POST" in (getattr(route, "methods", None) or set())}
        require(set(PATHS.values()) <= paths, "integrated_status_routes_required")
        baseline = fingerprint(store)
        expect.set_options(timeout=10000)
        playwright = stack.enter_context(sync_playwright())
        browser = stack.enter_context(playwright.chromium.launch(
            executable_path=args.browser_executable, headless=True,
            args=["--disable-background-networking", "--disable-component-update", "--disable-sync", "--no-first-run"],
        ))
        shot_cases = {("current_portfolio", 390, "recorded_completed"), ("historical", 390, "checkpoint_running"),
                      ("current_portfolio", 1440, "recorded_empty"), ("historical", 1440, "legacy_record")}
        for kind in KINDS:
            for width in WIDTHS:
                for scenario in STATES:
                    case = cases[kind, scenario]
                    calls, errors, answers = [], [], []
                    context = browser.new_context(viewport={"width": width, "height": 900}, service_workers="block")
                    try:
                        page = context.new_page()
                        page.on("pageerror", lambda error: errors.append(True))
                        def bridge(route):
                            request = route.request
                            parsed = urlsplit(request.url)
                            require(parsed.scheme == "http" and parsed.netloc == "synthetic.invalid"
                                    and not parsed.query, "unexpected_browser_url")
                            if parsed.path == "/" + kind and request.method == "GET":
                                route.fulfill(content_type="text/html", body=html,
                                              headers={"Cache-Control": "no-store"})
                                return
                            if parsed.path == "/favicon.ico" and request.method == "GET":
                                route.fulfill(status=204)
                                return
                            require(parsed.path == PATHS[kind] and request.method == "POST", "browser_write_or_wrong_route")
                            payload = request.post_data_json
                            require(payload == {"request_id": case["request_id"]}
                                    and str(UUID(payload["request_id"])) == payload["request_id"], "browser_uuid_body_mismatch")
                            calls.append(True)
                            response = client.post(parsed.path, content=request.post_data,
                                                   headers={"Content-Type": "application/json"})
                            require(response.status_code == 200, "real_status_backend_failed")
                            body = response.json()
                            check_backend(kind, scenario, case, body)
                            answers.append(body)
                            # No fixture payload, status translation or JSON re-encoding.
                            route.fulfill(status=response.status_code, content_type=response.headers["content-type"],
                                          body=response.content)
                        page.route("**/*", bridge)
                        page.goto(ORIGIN + "/" + kind)
                        section = page.get_by_role("region", name=TITLES[kind], exact=True)
                        field = section.get_by_label("Auftragskennung", exact=True)
                        button = section.get_by_role("button", name="Auftragsstatus lesen", exact=True)
                        expect(field).to_be_visible()
                        expect(button).to_be_disabled()
                        require(not calls, "status_called_on_mount")
                        page.evaluate("({kind,id}) => window.rememberPriceRequest[kind](id)",
                                      {"kind": kind, "id": case["request_id"]})
                        expect(field).to_have_value(case["request_id"])
                        page.reload()
                        expect(field).to_have_value(case["request_id"])
                        expect(button).to_be_enabled()
                        require(not calls, "status_called_on_reload")
                        button.click()
                        expect(section.get_by_text(STATUS_LABELS[expected_status(scenario)], exact=True)).to_be_visible()
                        expect(button).to_be_enabled()
                        require(len(calls) == len(answers) == 1, "status_request_count_mismatch")
                        check_browser(page, section, answers[0], expect)
                        if (kind, width, scenario) in shot_cases:
                            filename = f"{kind}-{scenario}-{width}.png"
                            page.screenshot(path=str(output / filename), full_page=True, animations="disabled")
                            report["screenshots"].append(filename)
                        page.reload()
                        expect(field).to_have_value(case["request_id"])
                        expect(button).to_be_enabled()
                        require(len(calls) == 1, "status_called_on_result_reload")
                        require(fingerprint(store) == baseline, "browser_status_changed_database")
                        require(not errors and not any(forbidden_calls.values()), "browser_or_side_effect_error")
                        report["cases"].append({"kind": kind, "width": width, "state": scenario,
                            "backend_status": answers[0]["data"]["status"], "http_status": 200,
                            "warnings": len(answers[0].get("warnings", [])), "status_requests": 1,
                            "unchanged_database": True, "overflow": False})
                    finally:
                        context.close()
        require(len(report["cases"]) == 64, "case_matrix_incomplete")
        require(source_binding() == binding, "bound_sources_changed_during_probe")
        require(not any(forbidden_calls.values()), "forbidden_backend_calls")
        report.update(passed=True, cases_passed=64, forbidden_calls=forbidden_calls,
                      real_backend=True, real_synthetic_duckdb=True, response_bytes_unmodified=True,
                      no_server=True, tax_release_claimed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-modules", type=Path, default=ROOT / "frontend/node_modules")
    parser.add_argument("--browser-executable")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = {"format_version": 1, "passed": False, "synthetic": True, "cases": [], "screenshots": []}
    output = None
    try:
        output = new_output(args.output)
        run(args, output, report)
    except ProbeFailure as error:
        report["error"] = str(error)
    except Exception:
        report["error"] = "backend_browser_probe_failed"
    if output is not None:
        (output / "summary.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="ascii")
    print(json.dumps({key: value for key, value in report.items() if key != "cases"}, sort_keys=True))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
