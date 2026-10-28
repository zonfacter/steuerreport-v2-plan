"""Exakte Audit-Hash-Findings pruefen; keine Scanner-Regel pauschal ausnehmen."""
import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
AUDIT = Path(__file__).parent


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def review(finding):
    path = Path(finding["File"])
    path = path if path.is_absolute() else ROOT / path
    if not path.resolve().is_relative_to(AUDIT.resolve()):
        raise ValueError("scan_path_outside_audit")
    lines = path.read_text().splitlines(keepends=True)
    start, end = finding["StartLine"], finding["EndLine"]
    text = "".join(lines[start - 1:end])
    verified, target_name = False, None
    if start == end and finding["RuleID"] in {"generic-api-key", "coinbase-access-token"}:
        try:
            entry = json.loads("{" + text.strip().removesuffix(",") + "}")
            target_name, value = next(iter(entry.items()))
            data = json.loads(path.read_text())
            if path == AUDIT / "reference-additional-results.json":
                known = data["source_manifest"].get(target_name) == value
                target = ROOT / target_name
            elif path == AUDIT / "evidence/manifest.json":
                if data["files"].get(target_name) == value:
                    known, target = True, AUDIT / "evidence" / target_name
                else:
                    known = data["frontend_build"].get(target_name) == value
                    target = ROOT / target_name
            else:
                known, target = False, ROOT
            verified = (known and target.resolve().is_relative_to(ROOT.resolve())
                        and len(value) == 64 and sha(target) == value)
        except (ValueError, TypeError, KeyError, OSError):
            verified = False
    return {"file": str(path.relative_to(ROOT)), "line": start, "rule": finding["RuleID"],
        "source_lines_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "reviewed_nonsecret": verified, "recomputed_target": target_name if verified else None,
        "reason": "Exakter SHA256 von getrackter Quelle, Builddatei oder gepruefter Original-Testbelegdatei; keine Zugangsdaten." if verified else "Ungeklaerter Verdacht; Veroeffentlichung blockiert."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    findings = [review(row) for row in json.loads(args.report.read_text())]
    result = {"scope": "exact_artifact_hashes_only_no_scanner_allowlist", "raw_findings": len(findings),
        "unreviewed_findings": sum(not row["reviewed_nonsecret"] for row in findings), "findings": findings}
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("raw_findings", "unreviewed_findings")}))
    return int(result["unreviewed_findings"] != 0)


if __name__ == "__main__":
    raise SystemExit(main())
