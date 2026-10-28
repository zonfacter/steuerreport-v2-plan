"""Sammle originale synthetische Testbelege; Originale und Produktion bleiben lesend."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[4]
BASE = "87b231b5a40716f41468e56a68048f3abd79f4cc"


def git(*args):
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={ROOT}", *args], cwd=ROOT
    )


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def junit(path):
    suites = ET.parse(path).getroot()
    cases = list(suites.iter("testcase"))
    return {
        "tests": len(cases),
        "failures": len(list(suites.iter("failure"))),
        "errors": len(list(suites.iter("error"))),
        "skipped": len(list(suites.iter("skipped"))),
        "skip_reasons": sorted({x.attrib.get("message", "") for x in suites.iter("skipped")}),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    code = git("rev-parse", args.source_commit).decode().strip()
    git("diff", "--exit-code", code, "--", "src", "frontend", "scripts", "tests", ".github", "docs/openapi")
    originals = {
        "unit.xml": "/tmp/sr-origin-20261028-unit-final.xml",
        "unit-interrupted-before-review-fix.xml": "/tmp/sr-origin-20261028-unit-interrupted.xml",
        "test-adapter-before-portability.xml": "/tmp/sr-origin-20261028-acceptance.xml",
        "original-reference.xml": "/tmp/sr-origin-20261028-original-final.xml",
        "additional-reference.xml": "/tmp/sr-origin-20261028-reference-final.xml",
        "focused.xml": "/tmp/sr-origin-20261028-focused.xml",
        "chain-consumers.xml": "/tmp/sr-origin-20261028-chain.xml",
        "review-export.xml": "/tmp/sr-origin-20261028-review.xml",
        "independent-before.xml": "/tmp/sr-origin-20261028-independent/baseline-v3.xml",
        "review-before.xml": "/tmp/sr-origin-20261028-independent/baseline-review.xml",
        "lineage-only-summary-before.xml": "/tmp/sr-origin-20261028-independent/final.xml",
        "independent-after.xml": "/tmp/sr-origin-20261028-independent/verified.xml",
        "portable-explicit.xml": "/tmp/sr-origin-20261028-independent/portable-explicit.xml",
        "portable-default.xml": "/tmp/sr-origin-20261028-independent/portable-factory.xml",
        "intermediate-prior-year-before.xml": "/tmp/sr-origin-20261028-evidence-before-27703bf.xml",
        "intermediate-prior-year-after.xml": "/tmp/sr-origin-20261028-evidence-after-4026e77.xml",
        "independent-before-freeze.json": "/tmp/sr-origin-20261028-independent/baseline-v3-source-freeze.json",
        "independent-after-freeze.json": "/tmp/sr-origin-20261028-independent/verified-source-freeze.json",
        "integrated-reference-freeze.json": "/tmp/sr-origin-20261028-coordinator-reference-final/sr-origin-20261028-reference-final-source-freeze.json",
        "secret-review.json": "/tmp/sr-origin-20261028-final-source-secret-review.json",
        "storage-cleanup.json": "/tmp/sr-origin-20261028-storage-cleanup.json",
    }
    for name, original in originals.items():
        source = Path(original)
        shutil.copyfile(source, output / name)
        assert sha(source) == sha(output / name)
    browser = Path("/tmp/sr-origin-20261028-browser-final-chain")
    for source in sorted(browser.glob("*.png")):
        shutil.copyfile(source, output / source.name)
    shutil.copyfile(browser / "result.json", output / "browser.json")
    review_browser = Path("/tmp/sr-origin-20261028-review-browser-final")
    shutil.copyfile(review_browser / "review-verification.json", output / "review-browser.json")
    patch = git("diff", "--binary", BASE, code)
    (output / "changes.patch").write_bytes(patch)
    commit = code
    (output / "source-commit.txt").write_text(commit + "\n")
    sources = {name: sha(ROOT / name) for name in git("ls-files", "src", "frontend/src", "tests", "scripts", ".github", "docs/openapi").decode().splitlines()}
    test_results = {name: junit(output / name) for name in originals if name.endswith(".xml")}
    current_cases = {}
    for name in ("original-reference.xml", "additional-reference.xml"):
        for case in ET.parse(output / name).getroot().iter("testcase"):
            status = "passed" if not any(case.find(x) is not None for x in ("failure", "error", "skipped")) else "not_passed"
            current_cases[case.attrib.get("classname", "") + "::" + case.attrib["name"]] = status
    matrix = json.loads((ROOT / "docs/audit/2026-10-28/blocker-closure/evidence/matrix.json").read_text())
    extensions = {
        "G12": ("stored_reward_root", "real_bmf_preview"), "G13": ("stored_reward_root", "real_bmf_preview"),
        "G14": ("stored_unknown_root", "stored_broken_lineage"), "G17": ("review_gate_reads", "stored_broken_lineage"),
        "G19": ("stored_reward_root", "resolver_follows", "intermediate", "prior_year"),
        "G21": ("legacy_staging",), "G22": ("resolver_follows",),
        "G23": ("zero_eur", "lineage_only", "review_gate_reads", "intermediate"),
    }
    for row in matrix:
        for test in row["tests"]:
            test["status"] = current_cases.get(test["id"], "not_run")
        row["lot_origin_tests"] = [{"id": key, "status": status} for key, status in current_cases.items()
                                   if "lot_origin" in key and any(token in key for token in extensions.get(row["id"], ()))]
        assert all(test["status"] == "passed" for test in row["tests"] + row["lot_origin_tests"]), row["id"]
    (output / "matrix.json").write_text(json.dumps(matrix, indent=2, sort_keys=True) + "\n")
    # Bekannte Vorherfehler sind Belege, keine erwarteten Fehler im CI-Gate.
    for name in ("unit.xml", "original-reference.xml", "additional-reference.xml", "independent-after.xml", "portable-explicit.xml", "portable-default.xml"):
        assert test_results[name]["failures"] == test_results[name]["errors"] == 0, name
    assert json.loads((output / "browser.json").read_text())["passed"]
    assert json.loads((output / "secret-review.json").read_text())["unreviewed_findings"] == 0
    for name in ("independent-before-freeze.json", "independent-after-freeze.json", "integrated-reference-freeze.json"):
        assert json.loads((output / name).read_text())["unchanged"]
    user_source = ROOT / "docs/blockpit-analysis"
    user_hashes = {}
    user_paths = [user_source / name for name in (
        "BMF-Quellenpruefung-2026-10-28.md", "Docker-Nachpruefung-18010-2026-10-28.md")]
    for name in ("v1-baseline-evidence-2026-10-28", "v2-baseline-evidence-2026-10-28"):
        user_paths.extend((user_source / name).rglob("*"))
    for path in sorted(user_paths):
        name = path.relative_to(user_source).as_posix()
        if path.is_file():
            user_hashes[name] = sha(path)
    deployment = json.loads(subprocess.check_output([
        "docker", "inspect", "--format",
        '{"Id":{{json .Id}},"Image":{{json .Image}},"State":{"StartedAt":{{json .State.StartedAt}},"Running":{{json .State.Running}}},"Mounts":{{json .Mounts}}}',
        "steuerreport-v2-lan"
    ]))
    production = {"container_id": deployment["Id"], "image_id": deployment["Image"],
                  "started_at": deployment["State"]["StartedAt"], "running": deployment["State"]["Running"],
                  "mounts": [{key: row.get(key) for key in ("Type", "Name", "Destination")} for row in deployment["Mounts"]],
                  "scope": "Docker-Metadaten, keine produktive API-/DB-Abfrage; keine Datenparitaetsaussage"}
    expected = ("fd7fe921c016029345f5a5f702ad39bd40516a05e1a70e7f8af5f40e969efcbf",
                "sha256:eabf14414fd02fb48d098995e52880d6f3d9419ee58aa1972b9c51f5364b877a",
                "2026-10-28T08:34:25.792124179Z")
    assert (production["container_id"], production["image_id"], production["started_at"]) == expected
    usage = shutil.disk_usage("/")
    numerical_sources = {}
    for name in ("domain/tax.py", "domain/tax_wallet_fifo.py", "domain/token_conversion.py",
                 "domain/tax_time.py", "domain/price_lookup.py", "domain/valuation.py",
                 "domain/reports.py", "domain/exports.py", "db/duckdb_store.py", "ledger/balance.py"):
        path = "src/steuerreport_v2/" + name
        old = hashlib.sha256(git("show", BASE + ":" + path)).hexdigest()
        current = sha(ROOT / path)
        assert old == current, path
        numerical_sources[path] = {"baseline_sha256": old, "current_sha256": current, "unchanged": True}
    manifest = {"created_at_utc": datetime.now(timezone.utc).isoformat(), "source_commit": commit,
                "diff_base": BASE, "head_at_collection": git("rev-parse", "HEAD").decode().strip(),
                "origin_trace_policy": "linked_lot_origin_v1", "fiscal_approval": False,
                "incomplete_runs": {"unit-interrupted-before-review-fix.xml": {
                    "exit_code": 2, "status": "interrupted_not_passed",
                    "reason": "Vor abschliessendem P1-Fix bewusst abgebrochen; kein Vollsuitenachweis"}},
                "unchanged_numerical_source_files": numerical_sources,
                "tests": test_results, "source_sha256": sources, "user_source_sha256": user_hashes,
                "production_metadata": production, "disk_free_bytes_at_collection": usage.free,
                "frontend_build": {path.relative_to(ROOT).as_posix(): sha(path) for path in sorted((ROOT / "frontend/dist").rglob("*")) if path.is_file()},
                "files": {path.name: sha(path) for path in sorted(output.iterdir()) if path.is_file()}}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"source_commit": commit, "tests": test_results, "files": len(manifest["files"])}))


if __name__ == "__main__":
    main()
