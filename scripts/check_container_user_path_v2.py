"""Exercise a synthetic file-import-to-year-report path over a release image's HTTP API.

The caller must provide a disposable, network-isolated container with a fresh
``/state`` volume. This test never writes directly to the database and never
uses an external provider or an AI endpoint.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import time


DRIVER = r'''import base64, csv as csv_module, hashlib, json, sys, urllib.error, urllib.request, zipfile
from decimal import Decimal
from io import BytesIO
from pypdf import PdfReader

BASE = "http://127.0.0.1:8010"
PHASE = sys.argv[1]
EXPECTED = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
HTTP_PATHS = []

def request(method, path, payload=None, timeout=240):
    HTTP_PATHS.append(path)
    data = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        response = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:1000]
        raise AssertionError(f"{method} {path}: HTTP {exc.code}: {body}") from None
    with response:
        headers = {key.lower(): value for key, value in response.headers.items()}
        return response.status, headers, response.read()

def api(method, path, payload=None, timeout=240):
    status, headers, content = request(method, path, payload, timeout)
    assert status == 200, (method, path, status)
    value = json.loads(content)
    assert value.get("status") in {"ok", "warning"}, (path, value.get("errors"))
    return value["data"]

def download(path):
    status, headers, content = request("GET", path)
    assert status == 200, (path, status)
    return headers, content

def dec(value):
    return Decimal(str(value))

health = api("GET", "/api/v1/health")
assert health["database_type"] == "duckdb", health

if PHASE == "create":
    assert api("GET", "/api/v1/import/batches") == [], "Testvolume ist nicht frisch"
    assert api("GET", "/api/v1/events/canonical") == [], "Testvolume enthaelt bereits Ereignisse"
    assert api("GET", "/api/v1/tax-years/2025/reports/pdf")["artifacts"] == []

    csv = (
        "time,asset,amount,type,quote_asset,quote_quantity,account,tx_id\n"
        "2025-01-01T10:00:00Z,TEST,10,buy,EUR,100,synthetic-e2e,buy-1\n"
        "2025-02-01T10:00:00Z,TEST,-4,sell,EUR,60,synthetic-e2e,sell-1\n"
        "2025-03-01T10:00:00Z,UNPRICED,-1,sell,,,synthetic-e2e,missing-price-1\n"
    ).encode()
    input_sha256 = hashlib.sha256(csv).hexdigest()
    upload = {"source": "manual-csv", "import_mode": "file",
              "filename": "issue-9-synthetic.csv",
              "content_base64": base64.b64encode(csv).decode("ascii")}

    preview = api("POST", "/api/v1/import/assistant/preview", upload)
    assert preview["can_execute"] is True, preview
    assert preview["preview"]["row_count"] == 3
    assert api("GET", "/api/v1/import/batches") == [], "Vorschau hat Daten importiert"

    outcome = api("POST", "/api/v1/import/assistant/execute", upload, timeout=300)
    batch = outcome["batch"]
    assert batch["file_hash"] == "sha256:" + input_sha256, batch
    assert outcome["run"]["normalized_events"] == 3
    assert outcome["run"]["pipeline"]["tax_lines"] == 1

    events = api("GET", "/api/v1/events/canonical")
    assert len(events) == 3, events
    trades = {(row["tx_id"], row["asset"]): row for row in events}
    assert dec(trades[("buy-1", "TEST")]["quantity"]) == Decimal("10")
    assert dec(trades[("buy-1", "TEST")]["quote_quantity"]) == Decimal("100")
    assert trades[("buy-1", "TEST")]["quote_asset"] == "EUR"
    assert dec(trades[("sell-1", "TEST")]["quantity"]) == Decimal("-4")
    assert dec(trades[("sell-1", "TEST")]["quote_quantity"]) == Decimal("60")
    assert trades[("sell-1", "TEST")]["quote_asset"] == "EUR"

    tax_lines = api("GET", "/api/v1/tax/lines")
    valid_lines = [row for row in tax_lines if row["asset"] == "TEST"]
    assert len(valid_lines) == 1, tax_lines
    line = valid_lines[0]
    assert dec(line["quantity"]) == Decimal("4")
    assert dec(line["acquisition_cost_eur"]) == Decimal("40")
    assert dec(line["disposal_proceeds_eur"]) == Decimal("60")
    assert dec(line["gain_loss_eur"]) == Decimal("20")

    lots = [row for row in api("GET", "/api/v1/tax/lots") if row["asset"] == "TEST"]
    assert len(lots) == 1, lots
    lot = lots[0]
    assert dec(lot["quantity_total"]) == Decimal("10")
    assert dec(lot["quantity_remaining"]) == Decimal("6")
    remaining_basis = dec(lot["cost_basis_eur_total"]) * dec(lot["quantity_remaining"]) / dec(lot["quantity_total"])
    assert remaining_basis == Decimal("60"), remaining_basis

    year = api("GET", "/api/v1/tax-years/2025")
    assert dec(year["realized_gain_loss_eur"]) == Decimal("20")
    assert dec(year["taxable_disposal_proceeds_eur"]) == Decimal("60")
    assert dec(year["acquisition_cost_eur"]) == Decimal("40")
    assert year["tax_lines_count"] == 1
    assert year["missing_price_groups"] == 1 and year["unmatched_disposals"] == 1, year
    assert year["export_blocked"] is True and year["state"] == "blocked", year

    created = api("POST", "/api/v1/tax-years/2025/reports/pdf", {})
    manifest = created["manifest"]
    assert manifest["report_status"] == "preview"
    assert manifest["final_filing_allowed"] is False
    assert manifest["missing_price_groups"] == 1 and manifest["unmatched_disposals"] == 1
    assert dec(manifest["summary"]["taxable_private_disposals_eur"]) == Decimal("20")
    assert dec(manifest["summary"]["taxable_disposal_proceeds_eur"]) == Decimal("60")
    assert dec(manifest["summary"]["acquisition_cost_eur"]) == Decimal("40")
    manifest_status, _, archived_manifest_bytes = request("GET", created["manifest_endpoint"])
    assert manifest_status == 200
    archived_manifest = json.loads(archived_manifest_bytes)
    assert archived_manifest["manifest_sha256"] == manifest["manifest_sha256"]
    pdf = manifest["files"][0]
    pdf_headers, pdf_bytes = download(pdf["download_endpoint"])
    assert hashlib.sha256(pdf_bytes).hexdigest() == pdf["sha256"]
    assert len(PdfReader(BytesIO(pdf_bytes), strict=True).pages) == pdf["page_count"] <= 100
    assert pdf_headers.get("content-type", "").startswith("application/pdf")

    captured = api("POST", "/api/v1/tax-years/2025/filing-snapshots", {
        "state": "reference", "filing_kind": "original",
        "note": "synthetischer Issue-9-E2E-Test",
    }, timeout=300)
    snapshot = captured["snapshot"]
    assert snapshot["state"] == "reference" and snapshot["filing_usage_confirmed"] is False
    assert snapshot["integrity_status"] == "verified"
    snapshot_headers, package = download(snapshot["package_download_endpoint"])
    package_sha256 = hashlib.sha256(package).hexdigest()
    assert package_sha256 == snapshot["package_sha256"]
    assert snapshot_headers.get("content-type", "").startswith("application/zip")
    with zipfile.ZipFile(BytesIO(package)) as evidence_package:
        package_names = set(evidence_package.namelist())
        assert "00_Manifest/year-evidence-manifest.json" in package_names
        assert "02_Steuerliche_CSVs/tax-year-2025-filing-summary.json" in package_names
        assert "02_Steuerliche_CSVs/tax-year-2025-tax-lines.csv" in package_names
        evidence_manifest = json.loads(evidence_package.read("00_Manifest/year-evidence-manifest.json"))
        assert evidence_manifest["calculation_run_id"] == manifest["calculation_run_id"]
        assert evidence_manifest["export_ready"] is False
        summary = json.loads(evidence_package.read("02_Steuerliche_CSVs/tax-year-2025-filing-summary.json"))
        assert summary["export_ready"] is False and summary["status_label"] == "blockiert"
        assert dec(summary["taxable_private_disposals_eur"]) == Decimal("20")
        assert dec(summary["taxable_disposal_proceeds_eur"]) == Decimal("60")
        assert dec(summary["acquisition_cost_eur"]) == Decimal("40")
        tax_csv = evidence_package.read("02_Steuerliche_CSVs/tax-year-2025-tax-lines.csv").decode("utf-8-sig")
        csv_lines = list(csv_module.DictReader(tax_csv.splitlines()))
        test_line = [row for row in csv_lines if row["Asset"] == "TEST"]
        assert len(test_line) == 1
        assert dec(test_line[0]["Menge"]) == Decimal("4")
        assert dec(test_line[0]["Anschaffungskosten_EUR"]) == Decimal("40")
        assert dec(test_line[0]["Veraeusserungserloes_EUR"]) == Decimal("60")
        assert dec(test_line[0]["Gewinn_Verlust_EUR"]) == Decimal("20")
    ai_endpoint_requests = sum("/api/v1/ai/" in path for path in HTTP_PATHS)
    assert ai_endpoint_requests == 0

    result = {
        "phase": "create", "version": health["app_version"],
        "schema_version": health["schema_version"],
        "input_sha256": input_sha256,
        "file_hash": batch["file_hash"],
        "calculation_run_id": manifest["calculation_run_id"],
        "fifo_method": manifest["fifo_method"],
        "pdf_artifact_id": manifest["artifact_id"],
        "pdf_manifest_sha256": manifest["manifest_sha256"],
        "pdf_sha256": pdf["sha256"],
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_package_sha256": package_sha256,
        "summary": {"proceeds_eur": "60", "acquisition_cost_eur": "40",
                    "gain_eur": "20", "remaining_quantity": "6",
                    "remaining_basis_eur": "60"},
        "blocked_missing_price_and_lot": True,
        "final_filing_allowed": False,
        "ai_endpoint_requests": ai_endpoint_requests,
    }
elif PHASE == "verify":
    reports = api("GET", "/api/v1/tax-years/2025/reports/pdf")["artifacts"]
    report = next((row for row in reports if row["manifest"]["artifact_id"] == EXPECTED["pdf_artifact_id"]), None)
    assert report is not None, "Jahresbericht nach Neustart nicht archiviert"
    assert report["manifest"]["manifest_sha256"] == EXPECTED["pdf_manifest_sha256"]
    manifest_status, _, manifest_bytes = request("GET", report["manifest_endpoint"])
    assert manifest_status == 200
    manifest = json.loads(manifest_bytes)
    assert manifest["calculation_run_id"] == EXPECTED["calculation_run_id"]
    _, pdf_bytes = download(manifest["files"][0]["download_endpoint"])
    assert hashlib.sha256(pdf_bytes).hexdigest() == EXPECTED["pdf_sha256"]

    snapshots = api("GET", "/api/v1/tax-years/2025/filing-snapshots")["snapshots"]
    snapshot = next((row for row in snapshots if row["snapshot_id"] == EXPECTED["snapshot_id"]), None)
    assert snapshot is not None, "Abgabestand nach Neustart nicht vorhanden"
    assert snapshot["package_sha256"] == EXPECTED["snapshot_package_sha256"]
    _, package = download(snapshot["package_download_endpoint"])
    assert hashlib.sha256(package).hexdigest() == EXPECTED["snapshot_package_sha256"]
    events = api("GET", "/api/v1/events/canonical")
    assert len(events) == 3, "Ereignisbestand nach Neustart geaendert"
    year = api("GET", "/api/v1/tax-years/2025")
    assert dec(year["realized_gain_loss_eur"]) == Decimal("20")
    assert year["missing_price_groups"] == 1 and year["unmatched_disposals"] == 1
    ai_endpoint_requests = sum("/api/v1/ai/" in path for path in HTTP_PATHS)
    assert ai_endpoint_requests == 0
    result = {"phase": "verify", "restart_verified": True,
              "calculation_run_id": manifest["calculation_run_id"],
              "pdf_manifest_sha256": manifest["manifest_sha256"],
              "snapshot_package_sha256": snapshot["package_sha256"],
              "canonical_event_count": len(events), "year_state": year["state"],
              "ai_endpoint_requests": ai_endpoint_requests}
else:
    raise AssertionError("unknown test phase")

print(json.dumps(result, sort_keys=True))
'''


def docker(*args: str, timeout: int = 60) -> str:
    result = subprocess.run(
        ["docker", *args], check=False, capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode:
        label = "docker " + " ".join(args[:3])
        detail = (result.stderr or result.stdout)[-2000:]
        raise RuntimeError(f"{label} failed: {detail}")
    return result.stdout.strip()


def wait_healthy(container: str) -> None:
    for _ in range(90):
        status = docker("inspect", "--format", "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}", container)
        if status == "running healthy":
            return
        if status.startswith(("exited", "dead")):
            raise RuntimeError("container exited during E2E run")
        time.sleep(2)
    raise TimeoutError("container health timeout after restart")


def run_driver(container: str, phase: str, expected: dict | None = None) -> dict:
    output = docker(
        "exec", container, "python", "-c", DRIVER,
        phase, json.dumps(expected or {}, separators=(",", ":")), timeout=900,
    )
    try:
        result = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError("container E2E driver returned invalid JSON") from exc
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.container):
        raise ValueError("invalid_test_container_name")
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_sha):
        raise ValueError("invalid_source_sha")

    container_info = json.loads(docker("inspect", args.container))[0]
    labels = container_info["Config"].get("Labels") or {}
    image_id = container_info["Image"]
    expected_labels = {
        "org.opencontainers.image.version": args.version,
        "org.opencontainers.image.revision": args.source_sha,
    }
    if any(labels.get(key) != value for key, value in expected_labels.items()):
        raise ValueError("test_container_source_labels_mismatch")

    wait_healthy(args.container)
    first = run_driver(args.container, "create")
    if first["version"] != args.version:
        raise ValueError("test_container_application_version_mismatch")
    docker("restart", args.container, timeout=120)
    wait_healthy(args.container)
    second = run_driver(args.container, "verify", first)
    if second["calculation_run_id"] != first["calculation_run_id"]:
        raise ValueError("calculation_run_changed_after_restart")
    result = {
        "result": "passed",
        "test_scope": "synthetic_file_import_to_tax_report_snapshot_and_restart",
        "image_id": image_id,
        "source_sha": args.source_sha,
        "version": args.version,
        "schema_version": first["schema_version"],
        "method": first["fifo_method"],
        "input_sha256": first["input_sha256"],
        "calculation_run_id": first["calculation_run_id"],
        "report": {"artifact_id": first["pdf_artifact_id"],
                   "manifest_sha256": first["pdf_manifest_sha256"],
                   "pdf_sha256": first["pdf_sha256"]},
        "filing_snapshot": {"snapshot_id": first["snapshot_id"],
                            "package_sha256": first["snapshot_package_sha256"]},
        "synthetic_summary": first["summary"],
        "missing_price_and_lot_blocked": first["blocked_missing_price_and_lot"],
        "final_filing_allowed": first["final_filing_allowed"],
        "restart": second,
        "external_network": "disabled_by_container_network_none",
        "direct_database_writes": False,
        "ai_endpoint_requests": first["ai_endpoint_requests"] + second["ai_endpoint_requests"],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
