#!/usr/bin/env python3
"""Stage and package the software without local case work or runtime data."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tomllib
import zipfile


ROOT = Path(__file__).resolve().parents[1]
CASE_MODULES = {
    "barclays_documents", "family_law_disclosure", "family_law_statements",
    "lawyer_disclosure", "legal_email_archive", "legal_tax_documents",
    "property_documents",
}
ROOT_FILES = {".env.example", ".gitignore", ".dockerignore", ".gitleaks.toml", "Dockerfile", "compose.yml", "compose.ghcr.yml", "requirements-runtime.lock", "AGENTS.md", "README.md", "CHANGELOG.md", "pyproject.toml"}
PUBLIC_DOCUMENTS = {
    "frontend/public/benutzerleitfaden.html", "frontend/public/benutzerleitfaden.pdf",
    "frontend/public/import-vorlage.csv", "frontend/public/importformate.pdf",
    "frontend/public/ki-einsatzleitfaden.pdf",
    "frontend/public/import-vorlagen/import-vorlagen.xlsx",
    *(f"frontend/public/import-vorlagen/{source}.csv" for source in (
        "manual-csv", "binance", "bitget", "pionex", "coinbase", "helium", "solana_rpc",
    )),
}
DOCUMENTS = {
    "docs/RELEASE_0.2.0rc33.md",
    "docs/audit/2026-10-28/acceptance_tests.py",
    "docs/audit/2026-10-28/issues/issue2-original.py",
    "docs/RELEASE_0.2.0rc32.md",
    "docs/RELEASE_0.2.0rc31.md",
    "docs/RELEASE_0.2.0rc30.md",
    "docs/RELEASE_0.2.0rc29.md",
    "docs/HISTORISCHE_EUR_PREISE.md",
    "docs/RELEASE_0.2.0rc28.md",
    "docs/RELEASE_0.2.0rc27.md",
    "docs/RELEASE_0.2.0rc26.md",
    "docs/RELEASE_0.2.0rc25.md",
    "docs/RELEASE_0.2.0rc24.md",
    "docs/SOLANA_ABRUFLIMITS.md",
    "docs/RELEASE_0.2.0rc23.md",
    "docs/RELEASE_0.2.0rc22.md",
    "docs/RELEASE_0.2.0rc21.md",
    "docs/AUTOMATISCHER_QUELLENIMPORT.md",
    "docs/HISTORY_CEX_PROVIDER_REFERENCES.md",
    "docs/QUELLENIMPORT_PRUEFUNG_2026-10-27.md",
    "docs/RELEASE_0.2.0rc20.md",
    "docs/FEHLERKORREKTUR_SOLANA_HISTORIE_2026-10-27.md",
    "docs/RELEASE_0.2.0rc16.md",
    "docs/RELEASE_0.2.0rc17.md",
    "docs/RELEASE_0.2.0rc18.md",
    "docs/RELEASE_0.2.0rc19.md",
    "docs/RELEASE_0.2.0rc15.md",
    "docs/INBETRIEBNAHME.md",
    "docs/RELEASE_0.2.0rc14.md",
    "docs/UX_BEDIENKONZEPT_2026-10-26.md",
    "docs/UX_REVIEW_KORREKTUREN_2026-10-26.md",
    "docs/UX_REVIEW_R1_2026-10-26.md",
    "docs/API_EINRICHTUNG_ABRUFLIMITS_2026-10-26.md",
    "docs/UX_PRUEFUNG_2026-10-26.md",
    "docs/KI_EINSATZLEITFADEN.md",
    "docs/IMPORTFORMATE.md",
    "docs/007_MOBILE_APP_API_INTEGRATION_2026-08-26.md",
    "docs/API_CONTRACTS_V2.md",
    "docs/626_API_ENDPOINT_REFERENZ_VOLLSTAENDIG_2026-07-05.md",
    "docs/openapi/steuerreport-v2-openapi.json",
    "docs/750_PRIVACY_CLEAN_SOFTWARE_2026-10-25.md",
    "docs/751_INSTALLATION_SETTINGS_DOCKER_RC3_2026-10-25.md",
}
GENERIC_CONFIGS = {
    "configs/binance_small_assets_price_evidence_20260710.json",
    "configs/crypto_price_sources.json",
    "configs/legal_research_sources.json",
    "configs/source_registry.example.json",
    "configs/private_profile.example.json",
    "configs/reviewed_secret_findings.json",
    "configs/provider_request_references.json",
}
PRIVATE_SCRIPTS = {
    "build_family_law_disclosure_package_v2.py",
    "build_lawyer_crypto_disclosure_package_v2.py",
    "build_legal_email_archive_v2.py",
    "generate_complete_source_audit_2025_v3.py",
    "generate_tax_classification_2025.py",
}
IGNORED_PARTS = {
    "__pycache__", "node_modules", "dist", "data", "var", "artifacts",
    ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache",
}


def software_path(name: str) -> bool:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        return False
    if any(part in IGNORED_PARTS or part.endswith(".egg-info") for part in path.parts):
        return False
    if name in PUBLIC_DOCUMENTS:
        return True
    if path.suffix.lower() in {".db", ".duckdb", ".wal", ".sqlite", ".sqlite3", ".msg", ".eml", ".pdf", ".xlsx", ".csv", ".key", ".pem", ".token", ".pyc"}:
        return False
    if name in ROOT_FILES or name in DOCUMENTS:
        return True
    if name.startswith("configs/"):
        return name in GENERIC_CONFIGS
    if name.startswith("src/steuerreport_v2/"):
        return not (path.parent.name == "domain" and path.stem in CASE_MODULES)
    if name.startswith("tests/"):
        return path.stem.removeprefix("test_") not in CASE_MODULES
    if name.startswith("scripts/"):
        return path.name not in PRIVATE_SCRIPTS
    return name.startswith(("frontend/", "integrations/", ".github/"))


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def stage(output: Path) -> None:
    if output.exists():
        raise ValueError("Output already exists; choose a new release directory.")
    names = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT
    ).decode().split("\0")
    selected = sorted({name for name in names if name and software_path(name)})
    files = []
    for name in selected:
        source = ROOT / name
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"Expected a regular source file: {name}")
        content = source.read_bytes()
        target_name = name
        target = output / "source" / target_name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        target.chmod(0o755 if source.stat().st_mode & 0o111 else 0o644)
        files.append({"path": target_name, "source_path": name, "size_bytes": len(content), "sha256": sha256(content)})
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text())
    manifest = {
        "version": metadata["project"]["version"],
        "base_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
        "includes_local_changes": bool(subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"], cwd=ROOT
        ).strip()),
        "scope": "software_only; local case modules and private evidence excluded",
        "source_tree_sha256": sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()),
        "files": files,
    }
    (output / "SOURCE_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(output), "source_files": len(files), "version": manifest["version"], "source_tree_sha256": manifest["source_tree_sha256"]}))


def write_zip(path: Path, files: list[tuple[str, Path]]) -> None:
    with zipfile.ZipFile(path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, source in sorted(files):
            entry = zipfile.ZipInfo(name, date_time=(2026, 10, 25, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = (0o100755 if source.stat().st_mode & 0o111 else 0o100644) << 16
            archive.writestr(entry, source.read_bytes())


def package(output: Path) -> None:
    manifest = json.loads((output / "SOURCE_MANIFEST.json").read_text())
    files = []
    for item in manifest["files"]:
        source = output / "source" / item["path"]
        if sha256(source.read_bytes()) != item["sha256"]:
            raise ValueError(f"Staged source changed: {item['path']}")
        files.append((f"steuerreport-v2-{manifest['version']}/{item['path']}", source))
    dist = output / "distributions"
    dist.mkdir(exist_ok=True)
    write_zip(dist / f"steuerreport-v2-{manifest['version']}-source.zip", files)
    frontend = output / "source/frontend/dist"
    if not (frontend / "index.html").is_file():
        raise ValueError("Build the frontend before packaging.")
    write_zip(
        dist / f"steuerreport-v2-{manifest['version']}-frontend.zip",
        [(str(path.relative_to(frontend)), path) for path in frontend.rglob("*") if path.is_file()],
    )
    sums = []
    for path in sorted(dist.iterdir()):
        if path.is_file():
            sums.append(f"{sha256(path.read_bytes())}  distributions/{path.name}")
    sums.append(f"{sha256((output / 'SOURCE_MANIFEST.json').read_bytes())}  SOURCE_MANIFEST.json")
    (output / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n")
    print(json.dumps({"output": str(output), "artifacts": len(sums) - 1, "source_verified": True}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["stage", "package"])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser().resolve()
    if args.action == "stage":
        stage(output)
    else:
        package(output)


if __name__ == "__main__":
    main()
