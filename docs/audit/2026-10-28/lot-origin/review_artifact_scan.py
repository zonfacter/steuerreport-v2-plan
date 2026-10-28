"""Nur exakte, nachgerechnete Beleg-/Quellhashes als Nicht-Secrets bewerten."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[4]
AUDIT = Path(__file__).parent
EVIDENCE = AUDIT / "evidence"


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads((EVIDENCE / "manifest.json").read_text())
    known = {}
    for key, value in manifest["files"].items():
        if sha(EVIDENCE / key) == value:
            known[key] = value
    for key, value in manifest["source_sha256"].items():
        data = subprocess.check_output(["git", "-c", f"safe.directory={ROOT}", "show", manifest["source_commit"] + ":" + key], cwd=ROOT)
        if hashlib.sha256(data).hexdigest() == value:
            known[key] = value
    for key, value in manifest["frontend_build"].items():
        if sha(ROOT / key) == value:
            known[key] = value
    rows = []
    for finding in json.loads(args.report.read_text()):
        path = (ROOT / finding["File"]).resolve()
        if not path.is_relative_to(EVIDENCE.resolve()):
            raise ValueError("finding_outside_exact_artifact_scope")
        start, end = finding["StartLine"], finding["EndLine"]
        lines = path.read_text().splitlines(keepends=True)
        text = "".join(lines[start - 1:end])
        approved = False
        if start == end and finding["RuleID"] in {"generic-api-key", "coinbase-access-token"}:
            try:
                key, value = next(iter(json.loads("{" + text.strip().removesuffix(",") + "}").items()))
                if path.name == "manifest.json":
                    approved = known.get(key) == value
                elif path.name in {"integrated-reference-freeze.json", "independent-before-freeze.json", "independent-after-freeze.json"}:
                    approved = known.get("src/steuerreport_v2/" + key) == value
            except (ValueError, TypeError, StopIteration):
                pass
        rows.append({"file": path.relative_to(ROOT).as_posix(), "line": start, "rule": finding["RuleID"],
                     "source_lines_sha256": hashlib.sha256(text.encode()).hexdigest(), "reviewed_nonsecret": approved,
                     "reason": "Exakt nachgerechneter SHA256 eines Belegs oder einer gebundenen Quelldatei" if approved else "Ungeklaert; Veroeffentlichung blockiert"})
    result = {"scope": "exact_artifact_hashes_no_rule_exemption", "manifest_sha256": sha(EVIDENCE / "manifest.json"),
              "raw_findings": len(rows), "unreviewed_findings": sum(not row["reviewed_nonsecret"] for row in rows), "findings": rows}
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("raw_findings", "unreviewed_findings")}))
    return int(result["unreviewed_findings"] != 0)


if __name__ == "__main__":
    raise SystemExit(main())
