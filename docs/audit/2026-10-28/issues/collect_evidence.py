"""Originale Issue-Referenzen und Browsernachweise einmalig einfrieren."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[4]
BASE = "7d184627791a10d87c45dbf901c9c7db310b7f38"


def git(*args):
    return subprocess.check_output(["git", "-c", f"safe.directory={ROOT}", *args], cwd=ROOT)


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    commit = git("rev-parse", args.source_commit).decode().strip()
    git("diff", "--exit-code", commit, "--", "src", "frontend", "scripts", "tests", ".github", "pyproject.toml", "docs/openapi")
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    originals = {
        "unit.xml": "/tmp/sr-issues-20261028/full-unit-final.xml",
        "unit-before-shared-limiter.xml": "/tmp/sr-issues-20261028/full-unit.xml",
        "original-reference.xml": "/tmp/sr-issues-20261028/original-reference-final.xml",
        "additional-reference.xml": "/tmp/sr-issues-20261028/acceptance-final.xml",
        "updates-focused.xml": "/tmp/sr-issues-20261028/updates-final.xml",
        "managed-transport.xml": "/tmp/sr-issues-20261028/managed-focused.xml",
        "managed-default-path.xml": "/tmp/sr-issues-20261028/managed-path.xml",
        "bitget-focused.xml": "/tmp/sr-issues-20261028/bitget-final.xml",
        "issue2-before.json": "/tmp/sr-issues-20261028/issue2-before.json",
        "issue2-after.json": "/tmp/sr-issues-20261028/issue2-after-final-managed.json",
        "stale-review-before.xml": "/tmp/sr-issues-20261028-bitget-review/review.xml",
        "stale-review-after.xml": "/tmp/sr-issues-20261028-bitget-stale/local-final.xml",
        "cache-coherence-before.xml": "/tmp/sr-issues-20261028/coherence-repro.xml",
        "adapter-cash-before.xml": "/tmp/sr-issues-20261028/cash.xml",
        "adapter-cache-before.xml": "/tmp/sr-issues-20261028/coherence-before.xml",
        "adapter-version-before.json": "/tmp/sr-issues-20261028/issue2-after-final.json",
        "browser-fixtures.json": "/tmp/sr-issues-20261028/component-final/result.json",
        "browser-backend.json": "/tmp/sr-issues-20261028/browser-managed-final/result.json",
        "review-browser.json": "/tmp/sr-issues-20261028/review-regression/review-verification.json",
        "workspace-browser.json": "/tmp/sr-issues-20261028/ux-regression/workspace-verification.json",
        "review-panel-browser.json": "/tmp/sr-issues-20261028/ux-regression/review-panel-verification.json",
        "general-ux-browser.json": "/tmp/sr-issues-20261028/ux-regression/verification.json",
        "reference-source-freeze.json": "/tmp/sr-issues-20261028/acceptance-final/bitget-stale-source-freeze.json",
        "updates-source-freeze.json": "/tmp/sr-issues-20261028/managed-focused/updates-source-freeze.json",
        "source-secret-review.json": "/tmp/sr-issues-20261028/source-secret-review-managed.json",
        "frontend-build.log": "/tmp/sr-issues-20261028/frontend-build.log",
        "ruff.log": "/tmp/sr-issues-20261028/ruff.log",
        "url-utc.log": "/tmp/sr-issues-20261028/url-utc.log",
        "url-berlin.log": "/tmp/sr-issues-20261028/url-berlin.log",
        "private-defaults.log": "/tmp/sr-issues-20261028/private-defaults.log",
        "openapi-drift.log": "/tmp/sr-issues-20261028/openapi-drift.log",
        "endpoint-drift.log": "/tmp/sr-issues-20261028/endpoint-drift.log",
        "import-drift.log": "/tmp/sr-issues-20261028/import-drift.log",
        "ai-guide-drift.log": "/tmp/sr-issues-20261028/ai-guide-drift.log",
    }
    for name, source in originals.items():
        shutil.copyfile(source, out / name)
        assert sha(Path(source)) == sha(out / name)
    for source in sorted(Path("/tmp/sr-issues-20261028/browser-managed-final").glob("*.png")):
        shutil.copyfile(source, out / source.name)
    (out / "changes.patch").write_bytes(git("diff", "--binary", BASE, commit))
    tests = {}
    for name in originals:
        if name.endswith(".xml"):
            tree = ET.parse(out / name).getroot()
            tests[name] = {"tests": len(list(tree.iter("testcase"))), "failures": len(list(tree.iter("failure"))),
                           "errors": len(list(tree.iter("error"))), "skipped": len(list(tree.iter("skipped")))}
    for name in ("unit.xml", "original-reference.xml", "additional-reference.xml", "updates-focused.xml", "managed-transport.xml", "managed-default-path.xml", "bitget-focused.xml", "stale-review-after.xml"):
        assert tests[name]["failures"] == tests[name]["errors"] == 0, name
    assert json.loads((out / "issue2-after.json").read_text())["summary"] == {"cases": 15, "passed": 15, "failed": 0, "execution_errors": 0}
    for name in ("browser-fixtures.json", "browser-backend.json"):
        assert json.loads((out / name).read_text())["passed"]
    for name in ("reference-source-freeze.json", "updates-source-freeze.json"):
        assert json.loads((out / name).read_text())["unchanged"]
    assert json.loads((out / "source-secret-review.json").read_text())["unreviewed_findings"] == 0
    manifest = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "source_commit": commit,
        "diff_base": BASE, "tests": tests, "financial_approval": False, "production_deployed": False,
        "frontend_build": [{"path": p.relative_to(ROOT).as_posix(), "sha256": sha(p)}
                           for p in sorted((ROOT / "frontend/dist").rglob("*")) if p.is_file()],
        "original_reproducer_sha256": sha(ROOT / "docs/audit/2026-10-28/issues/issue2-original.py"),
        "files": [{"path": p.name, "sha256": sha(p)} for p in sorted(out.iterdir()) if p.is_file()]}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"source_commit": commit, "tests": tests, "artifacts": len(manifest["files"])}))


if __name__ == "__main__":
    main()
