"""Portabler Hash-/JUnit-Abgleich ohne App, Datenbank, Netzwerk oder Schreibzugriff."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET


def main():
    root = Path(__file__).with_name("evidence")
    manifest = json.loads((root / "manifest.json").read_text())
    for name, expected in manifest["files"].items():
        path = root / name
        if not path.resolve().is_relative_to(root.resolve()):
            raise RuntimeError("invalid_evidence_path")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise RuntimeError("evidence_hash_mismatch:" + name)
    for name, result in manifest["test_results"].items():
        actual = Counter()
        for case in ET.parse(root / name).getroot().iter("testcase"):
            actual[next((key for key in ("failure", "error", "skipped") if case.find(key) is not None), "passed")] += 1
        if dict(actual) != result["counts"]:
            raise RuntimeError("junit_count_mismatch:" + name)
    matrix = json.loads((root / "matrix.json").read_text())
    if len(matrix) != 25 or any(row["fiscal_approval"] for row in matrix):
        raise RuntimeError("matrix_or_approval_invalid")
    if manifest["full_fiscal_approval"]:
        raise RuntimeError("unexpected_fiscal_approval")
    print(json.dumps({"evidence": "verified", "code_commit": manifest["integrated_code_commit"],
        "unit": manifest["test_results"]["unit.xml"]["counts"],
        "original": manifest["test_results"]["reference-original.xml"]["counts"],
        "additional": manifest["test_results"]["reference-additional.xml"]["counts"],
        "matrix_rows": len(matrix), "fiscal_approval": False}))


if __name__ == "__main__":
    main()
