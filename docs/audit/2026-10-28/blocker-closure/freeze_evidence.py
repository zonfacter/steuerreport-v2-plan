"""Neue Auditbelege einfrieren; keine Appinitialisierung oder Finanzdatenzugriffe."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import json
import io
from pathlib import Path
import shutil
import subprocess
import re
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[4]
BASE = "ce51a9d42963e25cb7b96dda19efce0703c55b26"
FREEZE = "f8e60d9e74b3d5ef92c710c0ae75d0cd84ac9fd6"
PROBE_SHA = "09f674b350a9a83943df8980bbceafd88821ee1400e03b5b22ea1ee0f8cd6bfb"
RUNTIME = ("src", "configs", "frontend", "scripts", "tests/unit", "pyproject.toml",
           "requirements-runtime.lock", "Dockerfile", "compose.yml")


def git(*args):
    return subprocess.check_output(["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT), *args])


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def junit(path):
    counts = Counter()
    cases = []
    for row in ET.parse(path).getroot().iter("testcase"):
        result = next((name for name in ("failure", "error", "skipped") if row.find(name) is not None), "passed")
        counts[result] += 1
        cases.append({"id": row.get("classname", "") + "::" + row.get("name", ""), "status": result})
    return {"counts": dict(counts), "cases": cases}


def require(value, reason):
    if not value:
        raise RuntimeError(reason)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--code-commit", required=True)
    parser.add_argument("--original-before", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(__file__).with_name("evidence"))
    args = parser.parse_args()
    code = git("rev-parse", args.code_commit).decode().strip()
    require(not git("diff", FREEZE, code, "--", *RUNTIME), "runtime_or_unit_tree_changed_since_freeze")
    require(not git("diff", code, "--", *RUNTIME), "uncommitted_runtime_or_unit_tree")
    require(sha(ROOT / "docs/audit/2026-10-28/acceptance_tests.py") == PROBE_SHA, "original_oracles_changed")
    sources = {
        "unit.xml": Path("/tmp/sr-blockers-all-final.xml"),
        "reference-original.xml": Path("/tmp/sr-blockers-reference52-final.xml"),
        "reference-additional.xml": Path("/tmp/sr-blockers-independent-final.xml"),
        "reference-additional-before.xml": args.original_before,
        "unit-interrupted-before-fixes.xml": Path("/tmp/sr-blockers-all-unit.xml"),
        "parity-helper.xml": Path("/tmp/sr-blockers-parity11.xml"),
        "browser.json": Path("/tmp/sr-blockers-browser-verified/result.json"),
        "source-secret-review.json": Path("/tmp/sr-blockers-source-secret-review.json"),
        "cli-checks.json": Path("/tmp/sr-blockers-cli-checks.json"),
    }
    results = {name: junit(path) for name, path in sources.items() if name.endswith(".xml")}
    require(results["unit.xml"]["counts"].get("passed", 0) >= 2464, "incomplete_unit_suite")
    require(set(results["unit.xml"]["counts"]) <= {"passed", "skipped"}, "unit_failure")
    require(results["unit.xml"]["counts"].get("skipped", 0) == 4, "unexpected_skip_count")
    require(results["reference-original.xml"]["counts"] == {"passed": 52}, "original_reference_failure")
    require(results["reference-additional.xml"]["counts"] == {"passed": 38}, "additional_reference_failure")
    require(results["reference-additional-before.xml"]["counts"] == {"passed": 30, "failure": 8}, "unexpected_before_result")
    require(results["parity-helper.xml"]["counts"] == {"passed": 11}, "parity_helper_failure")
    browser = json.loads(sources["browser.json"].read_text())
    require(browser["passed"] and browser["real_external_requests"] == 0, "browser_failure")
    secrets = json.loads(sources["source-secret-review.json"].read_text())
    require(secrets["unreviewed_findings"] == 0 and not secrets["private_default_violations"], "unreviewed_secret")
    require(all(row["exit_code"] == 0 for row in json.loads(sources["cli-checks.json"].read_text())), "cli_check_failure")
    # Ausgabeverzeichnis ist append-only: vorhandenen Lauf niemals ersetzen.
    args.output.mkdir(parents=True, exist_ok=False)
    for name, source in sources.items():
        shutil.copyfile(source, args.output / name)
    for screenshot in Path("/tmp/sr-blockers-browser-verified").glob("*.png"):
        shutil.copyfile(screenshot, args.output / screenshot.name)
    shutil.copyfile("/tmp/sr-blockers-browser-verified/synthetic-year-report.zip", args.output / "synthetic-year-report.zip")
    patch = args.output / "AENDERUNGEN.patch"
    patch.write_bytes(git("diff", "--binary", "--full-index", BASE, code))
    before_ids = {row["id"] for row in results["reference-additional-before.xml"]["cases"]}
    after_ids = {row["id"] for row in results["reference-additional.xml"]["cases"]}
    require(before_ids == after_ids, "independent_case_ids_changed")
    references = results["reference-original.xml"]["cases"] + results["reference-additional.xml"]["cases"]
    matrix = []
    with Path(__file__).with_name("MATRIX.md").open() as stream:
        for fields in csv.reader(stream, delimiter="|"):
            fields = [field.strip() for field in fields]
            if len(fields) != 6 or re.fullmatch(r"G\d{2}", fields[1]) is None:
                continue
            identifier = fields[1]
            matched = [row for row in references if identifier in re.findall(r"G\d{2}", row["id"])]
            require(matched and all(row["status"] == "passed" for row in matched), "matrix_reference_missing_or_failed:" + identifier)
            matrix.append({"id": identifier, "implementation_scope": fields[2], "validation_scope": fields[3],
                "technical_status": "passed_scoped", "tests": matched, "open": fields[4], "fiscal_approval": False})
    require([row["id"] for row in matrix] == [f"G{number:02d}" for number in range(1, 26)], "incomplete_matrix")
    (args.output / "matrix.json").write_text(json.dumps(matrix, indent=2) + "\n")
    csv_output = io.StringIO(newline="")
    writer = csv.writer(csv_output)
    writer.writerow(("ID", "Implementierter Umfang", "Technischer Status", "Proben", "Offen", "Fachlich abgenommen"))
    for row in matrix:
        writer.writerow((row["id"], row["implementation_scope"], row["technical_status"], len(row["tests"]), row["open"], "nein"))
    (args.output / "matrix.csv").write_text(csv_output.getvalue())
    container = json.loads(subprocess.check_output(["docker", "inspect", "--format",
        '{"id":{{json .Id}},"image":{{json .Image}},"started_at":{{json .State.StartedAt}}}',
        "steuerreport-v2-lan"]))
    require(container["id"] == "fd7fe921c016029345f5a5f702ad39bd40516a05e1a70e7f8af5f40e969efcbf", "production_container_changed")
    require(container["image"] == "sha256:eabf14414fd02fb48d098995e52880d6f3d9419ee58aa1972b9c51f5364b877a", "production_image_changed")
    require(container["started_at"] == "2026-10-28T08:34:25.792124179Z", "production_restarted")
    volume = subprocess.check_output(["docker", "inspect", "--format",
        '{{range .Mounts}}{{if eq .Destination "/state"}}{{json .Name}}{{end}}{{end}}',
        "steuerreport-v2-lan"]).decode().strip()
    container["state_volume"] = json.loads(volume)
    manifest = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "baseline_commit": BASE,
        "runtime_freeze_commit": FREEZE, "integrated_code_commit": code,
        "runtime_and_unit_tree_match_freeze": True, "original_reference_sha256": PROBE_SHA,
        "frontend_build": {str(path.relative_to(ROOT)): sha(path)
                           for path in sorted((ROOT / "frontend/dist").rglob("*")) if path.is_file()},
        "production": container, "production_api_called": False,
        "production_recalculated_or_deployed": False, "full_fiscal_approval": False,
        "test_results": results, "browser": browser,
        "files": {p.name: sha(p) for p in sorted(args.output.iterdir()) if p.is_file()}}
    with (args.output / "manifest.json").open("x") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
    for path in args.output.iterdir():
        path.chmod(0o444)
    print(json.dumps({"integrated_code_commit": code, "tests": {key: value["counts"] for key, value in results.items()},
                      "production_identity_unchanged": True, "fiscal_approval": False}))


if __name__ == "__main__":
    main()
