"""Prueft vorhandene Auditbelege; kein Appimport, Provideraufruf oder DB-Zugriff."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[4]
BASE = "1aecfb131d189267a01a6303f5a9b67a5a99efe2"
CODE = "b036b8ad4212d08d719fedec7dbc7115cf5704a9"
HANDOFF = "33bbdbf976405f2fade4fe45b6d167b6c950b740"
RUNTIME_PATHS = ("src", "configs", "frontend", "scripts", "pyproject.toml",
                 "requirements-runtime.lock", "Dockerfile", "compose.yml", "README.md")


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def git(*args: str) -> bytes:
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={ROOT}", "-C", str(ROOT), *args],
        stderr=subprocess.DEVNULL,
    )


def junit(path: Path) -> dict:
    root = ET.parse(path).getroot()
    cases = []
    for row in root.iter("testcase"):
        status = next((name for name in ("failure", "error", "skipped")
                       if row.find(name) is not None), "passed")
        cases.append({"id": row.get("classname", "") + "::" + row.get("name", ""),
                      "status": status})
    return {"path": str(path), "sha256": digest(path), "counts": dict(Counter(
        row["status"] for row in cases)), "cases": cases}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def evidence() -> dict:
    attached = Path(__file__).parent
    unit = junit(attached / "unit.xml")
    before = junit(attached / "F52_vorher.xml")
    after = junit(attached / "F52_nachher.xml")
    focus = junit(attached / "fokus.xml")
    require(unit["counts"] == {"passed": 2464, "skipped": 4}, "unexpected_full_unit_result")
    require(before["counts"] == {"passed": 22, "failure": 30}, "unexpected_baseline_result")
    require(after["counts"] == {"passed": 51, "failure": 1}, "unexpected_acceptance_result")
    require(set(focus["counts"]) == {"passed"}, "new_focus_run_not_green")
    failures = [row["id"] for row in after["cases"] if row["status"] == "failure"]
    require(len(failures) == 1 and "test_G04_" in failures[0], "unexpected_fiscal_failure")
    require({row["id"] for row in before["cases"]} == {
        row["id"] for row in after["cases"]}, "changed_acceptance_case_ids")
    test_path = "docs/audit/2026-10-28/acceptance_tests.py"
    test_hash = hashlib.sha256(git("show", f"{CODE}:{test_path}")).hexdigest()
    require(test_hash == "09f674b350a9a83943df8980bbceafd88821ee1400e03b5b22ea1ee0f8cd6bfb",
            "changed_independent_test_code")
    require(digest(ROOT / test_path) == test_hash, "working_test_code_drift")
    require(not git("diff", CODE, HANDOFF, "--", *RUNTIME_PATHS), "handoff_runtime_drift")
    require(not git("diff", CODE, "HEAD", "--", *RUNTIME_PATHS), "current_runtime_drift")
    require(not git("diff", CODE, "--", *RUNTIME_PATHS), "working_runtime_drift")
    patch = Path(__file__).with_name("AENDERUNGEN.patch")
    require(patch.read_bytes() == git("diff", "--binary", "--full-index", BASE, HANDOFF),
            "patch_does_not_match_commits")

    private = Path("/root/.local/share/steuerreport/migration-audit-20261028/coordinator")
    inventory_path = private / "private-data-inventory.json"
    inventory = json.loads(inventory_path.read_text())
    legacy, docker = inventory["legacy_disk_candidate"], inventory["docker"]
    restore_path = private / "final-restore-b036b8a/restore-result.json"
    restore = json.loads(restore_path.read_text())
    preservation = {key: restore[key] for key in (
        "passed", "cleanup", "isolation_verified", "private_key_token_profile_preserved",
        "restore_all_tables_preserved_start", "restore_all_tables_preserved_restart",
        "restore_all_non_database_files_preserved", "source_all_tables_unchanged",
        "source_all_non_database_files_unchanged", "source_container_identity_and_config_unchanged")}
    require(all(preservation.values()), "restore_evidence_failed")
    return {
        "scope": "documentary_verification_not_fiscal_approval",
        "baseline_commit": BASE, "code_commit": CODE, "handoff_commit": HANDOFF,
        "patch_sha256": digest(patch), "independent_test_sha256": test_hash,
        "runtime_unchanged_since_code_freeze": True,
        "unit": {key: value for key, value in unit.items() if key != "cases"},
        "focus_rerun": {key: value for key, value in focus.items() if key != "cases"},
        "acceptance_baseline": before, "acceptance_final": after,
        "data_parity": {
            "status": "not_proven", "private_inventory_sha256": digest(inventory_path),
            "legacy_disk_database_runtime_mapping_confirmed": legacy["runtime_database_mapping_confirmed"],
            "docker_database_runtime_mapping_confirmed": docker["runtime_database_mapping_confirmed"],
            "observed_table_counts_equal": legacy["counts"] == docker["counts"],
            "observed_latest_method_name_equal": legacy["latest_method_run"][0] == docker["latest_method_run"][0],
            "limits": "Counts/method names do not establish event, lot, tax-line or filing parity.",
        },
        "restore": {"sha256": digest(restore_path), "image_id": restore["image_id"],
                    "network": restore["network"], "checks": preservation},
        "full_fiscal_approval": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Neue JSON-Datei, vorhandene Datei wird nicht ersetzt")
    args = parser.parse_args()
    result = evidence()
    rendered = json.dumps(result, indent=2, ensure_ascii=True) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(rendered)
    print(json.dumps({"verification": "passed", "unit": result["unit"]["counts"],
                      "focus": result["focus_rerun"]["counts"],
                      "fiscal_cases": result["acceptance_final"]["counts"],
                      "data_parity": result["data_parity"]["status"],
                      "full_fiscal_approval": False}))


if __name__ == "__main__":
    main()
