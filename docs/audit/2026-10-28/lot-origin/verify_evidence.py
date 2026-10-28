"""Pruefe unveraenderte Belegbytes; keine neue Fach- oder Produktionspruefung."""
import hashlib
import json
from pathlib import Path


def main():
    base = Path(__file__).parent / "evidence"
    manifest = json.loads((base / "manifest.json").read_text())
    checked = 0
    for name, expected in manifest["files"].items():
        path = (base / name).resolve()
        if not path.is_relative_to(base.resolve()):
            raise ValueError("artifact_path_outside_evidence")
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise ValueError("artifact_hash_mismatch:" + name)
        checked += 1
    print(json.dumps({"verified_files": checked, "source_commit": manifest["source_commit"],
                      "scope": "artifact_integrity_only", "fiscal_approval": False}))


if __name__ == "__main__":
    main()
