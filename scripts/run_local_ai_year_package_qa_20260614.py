#!/usr/bin/env python3
from __future__ import annotations

from steuerreport_v2.private_settings import private_value

import argparse
import csv
import io
import json
import os
import urllib.error
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "var" / "local_ai_prework" / "year_package_qa_20260614"
API_BASE = os.environ.get("STEUERREPORT_V2_API", "http://127.0.0.1:8010")
LLM_BASE = os.environ.get("LOCAL_LLM_BASE") or private_value("local_llm_base") or "http://127.0.0.1:11435/v1"
LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL") or private_value("local_llm_model") or "local-model"
DEFAULT_YEARS = list(range(2020, 2027))


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only local-AI QA for yearly evidence packages.")
    parser.add_argument("--dry-run", action="store_true", help="Skip local LLM call.")
    parser.add_argument("--years", default=",".join(str(year) for year in DEFAULT_YEARS))
    args = parser.parse_args()

    years = [int(item.strip()) for item in args.years.split(",") if item.strip()]
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = OUT_ROOT / f"run_{run_id}"
    raw_dir = out / "raw"
    package_dir = out / "packages"
    raw_dir.mkdir(parents=True, exist_ok=True)
    package_dir.mkdir(parents=True, exist_ok=True)

    findings: list[dict[str, Any]] = []
    year_reports: list[dict[str, Any]] = []
    for year in years:
        report = inspect_year(year, raw_dir=raw_dir, package_dir=package_dir)
        year_reports.append(report)
        findings.extend(report["findings"])

    status = "ok" if not any(finding["severity"] in {"high", "blocker"} for finding in findings) else "review"
    payload = {
        "package": "year_package_qa_20260614",
        "run_id": run_id,
        "started_at": run_id,
        "finished_at": datetime.now(UTC).isoformat(),
        "mode": "readonly_local_ai_year_package_qa",
        "api_base": API_BASE,
        "llm_base": LLM_BASE,
        "llm_model": LLM_MODEL,
        "status": status,
        "years": year_reports,
        "findings": findings,
        "rules": [
            "No database writes.",
            "No imports.",
            "No FIFO rebuild.",
            "No review decisions.",
            "Codex must verify every recommendation before implementation.",
        ],
    }
    write_json(out / "findings.json", payload)
    (out / "summary.md").write_text(render_summary(payload), encoding="utf-8")

    if args.dry_run:
        (out / "local_ai_review.md").write_text(
            "# Lokale KI Review\n\nDry-Run: lokale KI wurde nicht aufgerufen.\n",
            encoding="utf-8",
        )
        llm_status = "dry_run"
    else:
        review, llm_status = call_llm(build_prompt(payload))
        (out / "local_ai_review.md").write_text(review.strip() + "\n", encoding="utf-8")

    payload["llm_status"] = llm_status
    write_json(out / "run_status.json", payload)
    print(json.dumps({"status": status, "llm_status": llm_status, "output": str(out), "findings": len(findings)}, indent=2))
    return 0


def inspect_year(year: int, *, raw_dir: Path, package_dir: Path) -> dict[str, Any]:
    package_path = package_dir / f"tax-year-{year}-evidence.zip"
    content = fetch_bytes(f"/api/v1/export/tax-years/{year}/evidence-package.zip")
    package_path.write_bytes(content)
    report: dict[str, Any] = {
        "year": year,
        "package_path": str(package_path.relative_to(ROOT)),
        "package_size_bytes": len(content),
        "export_ready": None,
        "manifest_file_count": 0,
        "zip_file_count": 0,
        "required_refs": [],
        "tax_line_years": [],
        "income_years": [],
        "derivative_years": [],
        "external_inflow_years": [],
        "findings": [],
    }
    with zipfile.ZipFile(io.BytesIO(content)) as package:
        names = package.namelist()
        report["zip_file_count"] = len(names)
        required_names = {
            "README.txt",
            "00_Manifest/year-evidence-manifest.json",
            f"02_Steuerliche_CSVs/tax-year-{year}-filing-summary.json",
            f"02_Steuerliche_CSVs/tax-year-{year}-evidence.json",
            "02_Steuerliche_CSVs/tax-payment-overview.json",
        }
        missing = sorted(required_names - set(names))
        if missing:
            add_finding(report, "missing_package_files", "high", f"{year}: Pflichtdateien fehlen: {', '.join(missing)}")

        manifest = json.loads(package.read("00_Manifest/year-evidence-manifest.json").decode("utf-8"))
        write_json(raw_dir / f"year_{year}_manifest.json", manifest)
        report["export_ready"] = manifest.get("export_ready")
        report["manifest_file_count"] = len(manifest.get("files") or [])
        report["required_refs"] = manifest.get("required_refs") or []
        if manifest.get("year") != year:
            add_finding(report, "manifest_year_mismatch", "blocker", f"{year}: Manifestjahr ist {manifest.get('year')}.")
        if report["manifest_file_count"] > report["zip_file_count"]:
            add_finding(report, "manifest_zip_count_mismatch", "medium", f"{year}: Manifest listet mehr Dateien als ZIP enthaelt.")

        report["tax_line_years"] = csv_years(package, f"02_Steuerliche_CSVs/tax-year-{year}-tax-lines.csv", "Datum_Verkauf")
        report["income_years"] = csv_values(package, f"02_Steuerliche_CSVs/tax-year-{year}-tax-income-guide.csv", "Jahr")
        report["derivative_years"] = csv_years(package, f"02_Steuerliche_CSVs/tax-year-{year}-derivative-lines.csv", "Datum")
        report["external_inflow_years"] = csv_values(package, f"02_Steuerliche_CSVs/tax-year-{year}-tax-external-inflows.csv", "Jahr")

        for label, values in [
            ("tax-lines", report["tax_line_years"]),
            ("income-guide", report["income_years"]),
            ("derivative-lines", report["derivative_years"]),
            ("external-inflows", report["external_inflow_years"]),
        ]:
            invalid = [value for value in values if value and value != str(year)]
            if invalid:
                add_finding(report, "csv_year_filter_mismatch", "high", f"{year}: {label} enthaelt Fremdjahre {invalid}.")
    return report


def csv_years(package: zipfile.ZipFile, name: str, field: str) -> list[str]:
    values = csv_values(package, name, field)
    return sorted({value[:4] for value in values if value})


def csv_values(package: zipfile.ZipFile, name: str, field: str) -> list[str]:
    if name not in package.namelist():
        return []
    text = package.read(name).decode("utf-8")
    return sorted({str(row.get(field) or "") for row in csv.DictReader(io.StringIO(text)) if row.get(field)})


def add_finding(report: dict[str, Any], code: str, severity: str, message: str) -> None:
    report["findings"].append({"year": report["year"], "code": code, "severity": severity, "message": message})


def render_summary(payload: dict[str, Any]) -> str:
    lines = [
        "# Jahrespaket-QA",
        "",
        f"- Status: `{payload['status']}`",
        f"- Lokale KI Modellziel: `{payload['llm_model']}`",
        f"- API: `{payload['api_base']}`",
        "",
        "| Jahr | Export | ZIP-Dateien | Manifest-Dateien | Tax-Line-Jahre | Findings |",
        "|---:|---|---:|---:|---|---:|",
    ]
    for report in payload["years"]:
        lines.append(
            f"| {report['year']} | {report['export_ready']} | {report['zip_file_count']} | "
            f"{report['manifest_file_count']} | {', '.join(report['tax_line_years']) or '-'} | {len(report['findings'])} |"
        )
    lines.extend(["", "## Findings", ""])
    if payload["findings"]:
        for finding in payload["findings"]:
            lines.append(f"- `{finding['severity']}` `{finding['code']}`: {finding['message']}")
    else:
        lines.append("Keine blockierenden Findings in den maschinellen Checks.")
    lines.append("")
    return "\n".join(lines)


def build_prompt(payload: dict[str, Any]) -> str:
    compact = {
        "status": payload["status"],
        "years": [
            {
                "year": report["year"],
                "export_ready": report["export_ready"],
                "zip_file_count": report["zip_file_count"],
                "manifest_file_count": report["manifest_file_count"],
                "expected_zip_file_count": int(report["manifest_file_count"]) + 2,
                "required_refs": report["required_refs"],
                "tax_line_years": report["tax_line_years"],
                "income_years": report["income_years"],
                "derivative_years": report["derivative_years"],
                "external_inflow_years": report["external_inflow_years"],
                "findings": report["findings"],
            }
            for report in payload["years"]
        ],
        "findings": payload["findings"],
    }
    return (
        "Du bist lokale KI fuer Steuerreport V2. Arbeite ausschliesslich im Readonly-Modus.\n"
        "Bewerte die maschinelle QA der Jahres-Belegpakete. Keine Steuerentscheidung, keine Datenbankwrites.\n"
        "Wichtig: `manifest_file_count` zaehlt nur Payload-Dateien im Manifest. "
        "`README.txt` und `00_Manifest/year-evidence-manifest.json` sind absichtlich extra im ZIP. "
        "Eine Struktur ist konsistent, wenn `zip_file_count == expected_zip_file_count` gilt. "
        "Fehlende CSV-Arten sind nur dann ein Risiko, wenn sie in `required_refs` stehen oder maschinelle Findings existieren.\n"
        "Gib aus: 1) Ampel je Jahr, 2) wichtigste Risiken, 3) konkrete Codex-Pruefschritte.\n\n"
        f"Kontext:\n{json.dumps(compact, ensure_ascii=False, indent=2)}"
    )


def call_llm(prompt: str) -> tuple[str, str]:
    data = json.dumps(
        {
            "model": LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 2600,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{LLM_BASE.rstrip('/')}/chat/completions",
        data=data,
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=1800) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"], "ok"
    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
        return f"# Lokale KI Aufgabe fehlgeschlagen\n\n`{type(exc).__name__}: {exc}`\n", "failed"


def fetch_bytes(path: str) -> bytes:
    with urllib.request.urlopen(f"{API_BASE}{path}", timeout=240) as response:
        return response.read()


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
