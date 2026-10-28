"""Bestehende exakt gepruefte Nicht-Secrets aus eingefrorenem Git-Stand verifizieren.

Neue oder inhaltlich veraenderte Fundstellen blockieren weiterhin. Kein
Regel-/Pfad-Allowlisting, keine nachtraegliche Aenderung alter Auditbelege.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[4]
BASE = "7d184627791a10d87c45dbf901c9c7db310b7f38"


def frozen(path):
    return json.loads(subprocess.check_output([
        "git", "-c", f"safe.directory={ROOT}", "show", BASE + ":" + path], cwd=ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    approved = frozen("configs/reviewed_secret_findings.json")
    for path in ("docs/audit/2026-10-28/blocker-closure/artifact-secret-review.json",
                 "docs/audit/2026-10-28/lot-origin/artifact-secret-review.json"):
        data = frozen(path)
        assert data["unreviewed_findings"] == 0
        approved.extend(row for row in data["findings"] if row["reviewed_nonsecret"])
    known = {(row["file"], row["rule"], row["source_lines_sha256"]): row["reason"] for row in approved}
    rows = []
    for finding in json.loads(args.report.read_text()):
        path = Path(finding["File"])
        path = path if path.is_absolute() else args.root / path
        path = path.resolve()
        assert path.is_relative_to(args.root.resolve())
        name = path.relative_to(args.root.resolve()).as_posix()
        lines = path.read_text().splitlines(keepends=True)
        start, end = finding["StartLine"], finding["EndLine"]
        assert 1 <= start <= end <= len(lines)
        digest = hashlib.sha256("".join(lines[start - 1:end]).encode()).hexdigest()
        reason = known.get((name, finding["RuleID"], digest))
        rows.append(dict(file=name, line=start, rule=finding["RuleID"], source_lines_sha256=digest,
                         reviewed_nonsecret=reason is not None,
                         reason=reason or "Neue Fundstelle; Veroeffentlichung blockiert."))
    result = dict(approval_commit=BASE, scope="exact_previously_reviewed_source_lines_only",
                  raw_findings=len(rows), unreviewed_findings=sum(not row["reviewed_nonsecret"] for row in rows), findings=rows)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("raw_findings", "unreviewed_findings")}))
    return int(result["unreviewed_findings"] != 0)


if __name__ == "__main__":
    raise SystemExit(main())
