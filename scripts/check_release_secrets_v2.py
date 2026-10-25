"""Fail closed on secrets; accept only individually reviewed, exact source lines."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REVIEWS = ROOT / "configs/reviewed_secret_findings.json"


def review(root: Path, findings: list[dict], approved: list[dict], scanner_exit: int) -> dict:
    if scanner_exit not in {0, 1} or bool(findings) != (scanner_exit == 1):
        raise ValueError("secret_scanner_failed_or_inconsistent")
    root = root.resolve()
    allowed = {(row["file"], row["rule"], row["source_lines_sha256"]): row["reason"] for row in approved}
    rows = []
    for finding in findings:
        path = Path(finding["File"])
        path = path if path.is_absolute() else root / path
        path = path.resolve()
        if not path.is_relative_to(root):
            raise ValueError("secret_report_path_outside_source")
        name = path.relative_to(root).as_posix()
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        start, end = int(finding["StartLine"]), int(finding["EndLine"])
        if start < 1 or end < start or end > len(lines):
            raise ValueError("secret_report_line_invalid")
        digest = hashlib.sha256("".join(lines[start - 1:end]).encode()).hexdigest()
        reason = allowed.get((name, finding["RuleID"], digest))
        rows.append({"file": name, "line": start, "rule": finding["RuleID"], "reviewed_nonsecret": reason is not None, "reason": reason or "Ungepruefter Secret-Verdacht; Veroeffentlichung blockiert."})
    return {"scanner_exit_code": scanner_exit, "raw_findings": len(rows), "unreviewed_findings": sum(not row["reviewed_nonsecret"] for row in rows), "findings": rows}


def account_defaults(root: Path) -> list[str]:
    spec = importlib.util.spec_from_file_location("private_data_guard", ROOT / "scripts/check_private_data_v2.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    problems = module.violations(root)
    profile = json.loads((root / "configs/private_profile.example.json").read_text())
    if not isinstance(profile, dict) or any(value != "" for value in profile.values()):
        problems.append("private_profile_example_not_empty")
    registry = json.loads((root / "configs/source_registry.example.json").read_text())
    if any(registry.get(key) for key in ("entries", "ledger_adjustments", "transfer_evidence")):
        problems.append("source_registry_example_not_empty")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--scanner-exit", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = review(args.root, json.loads(args.report.read_text()), json.loads(REVIEWS.read_text()), args.scanner_exit)
    result["private_default_violations"] = account_defaults(args.root)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "findings"}))
    return int(bool(result["unreviewed_findings"] or result["private_default_violations"]))


if __name__ == "__main__":
    raise SystemExit(main())
