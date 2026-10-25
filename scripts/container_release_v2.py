"""Resolve tested release sources and verify published container metadata."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import time
import tomllib
import urllib.error
import urllib.request


IMAGE_INPUTS = (
    "Dockerfile", ".dockerignore", "pyproject.toml", "requirements-runtime.lock",
    "src", "frontend",
    "configs/crypto_price_sources.json",
    "configs/binance_small_assets_price_evidence_20260710.json",
    "configs/legal_research_sources.json", "configs/source_registry.example.json",
    "configs/private_profile.example.json",
)
TAG = re.compile(r"v(\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?)\Z")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def resolve_release(repo: Path, tag: str, owner: str) -> dict[str, str]:
    match = TAG.fullmatch(tag)
    if match is None or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", owner):
        raise ValueError("invalid_release_tag_or_owner")
    sha = git(repo, "rev-parse", "--verify", f"refs/tags/{tag}^{{commit}}")
    metadata = tomllib.loads(git(repo, "show", f"{sha}:pyproject.toml"))
    if metadata["project"]["version"] != match[1]:
        raise ValueError("release_tag_version_mismatch")
    if git(repo, "diff", "--name-only", "HEAD", sha, "--", *IMAGE_INPUTS):
        raise ValueError("release_runtime_differs_from_validated_source")
    return {"version": match[1], "source_sha": sha, "image": f"ghcr.io/{owner.lower()}/steuerreport-v2", "commit_tag": "sha-" + sha}


def registry_version(owner: str, owner_type: str, version: str, token: str) -> str:
    if owner_type not in {"User", "Organization"} or not re.fullmatch(r"[A-Za-z0-9-]{1,39}", owner):
        raise ValueError("invalid_registry_owner")
    kind = "users" if owner_type == "User" else "orgs"
    for page in range(1, 101):
        url = f"https://api.github.com/{kind}/{owner}/packages/container/steuerreport-v2/versions?per_page=100&page={page}"
        request = urllib.request.Request(url, headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                rows = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return ""
            raise RuntimeError(f"registry_version_lookup_failed_http_{exc.code}") from None
        if not isinstance(rows, list):
            raise ValueError("registry_version_response_invalid")
        for row in rows:
            if version in row.get("metadata", {}).get("container", {}).get("tags", []):
                digest = row["name"]
                if not DIGEST.fullmatch(digest):
                    raise ValueError("registry_digest_invalid")
                return digest
        if len(rows) < 100:
            return ""
    raise RuntimeError("registry_version_pagination_limit")


def verify_image(inspect: list[dict], version: str, sha: str, repository: str) -> dict:
    if len(inspect) != 1:
        raise ValueError("expected_one_container_image")
    item = inspect[0]
    labels = item.get("Config", {}).get("Labels") or {}
    expected = {"org.opencontainers.image.version": version, "org.opencontainers.image.revision": sha, "org.opencontainers.image.source": "https://github.com/" + repository}
    if any(labels.get(key) != value for key, value in expected.items()):
        raise ValueError("container_source_labels_mismatch")
    if item["Config"].get("User") != "10001:10001" or item.get("Os") != "linux" or item.get("Architecture") != "amd64":
        raise ValueError("container_user_or_platform_invalid")
    for entry in item["Config"].get("Env", []):
        key, _, value = entry.partition("=")
        if value and re.search(r"(?:API_KEY|API_SECRET|PASSWORD|PASSPHRASE|TOKEN|ACCESS_KEY_ID|SECRET_ACCESS_KEY)$", key, re.I):
            raise ValueError("credential_environment_baked_into_image")
    return {"image_id": item["Id"], "version": version, "source_sha": sha, "repository": repository, "platform": "linux/amd64", "non_root": True, "repo_digests": item.get("RepoDigests", [])}


def smoke_container(container: str, version: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", container):
        raise ValueError("invalid_test_container_name")
    for _ in range(60):
        status = subprocess.check_output(["docker", "inspect", "--format", "{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}", container], text=True).strip()
        if status == "running healthy":
            break
        if status.startswith(("exited", "dead")):
            raise RuntimeError("test_container_did_not_start")
        time.sleep(2)
    else:
        raise RuntimeError("test_container_health_timeout")
    code = '''import json,stat,urllib.request
from pathlib import Path
def get(path):
    return json.load(urllib.request.urlopen("http://127.0.0.1:8010"+path))["data"]
health=get("/api/v1/health")
settings=get("/api/v1/admin/installation")
assert all(not row["value"] for row in settings["fields"])
assert not any(settings["providers"].values())
assert not settings["restart_required"]
assert settings["encrypted_secrets_available"]
legacy=get("/api/v1/admin/cex-credentials/v1-takeover")
assert not legacy["items"] and legacy["blocked"] == 0 and legacy["transferable"] == 0
assert not any(row["key"].startswith("secret.") for row in get("/api/v1/admin/settings"))
assert urllib.request.urlopen("http://127.0.0.1:8010/").status == 200
assert urllib.request.urlopen("http://127.0.0.1:8010/benutzerleitfaden.html").status == 200
assert urllib.request.urlopen("http://127.0.0.1:8010/benutzerleitfaden.pdf").read(5) == b"%PDF-"
assert urllib.request.urlopen("http://127.0.0.1:8010/import-vorlage.csv").read().count(b"\\n") == 1
assert not any(json.loads(Path("/state/private_profile.json").read_text()).values())
key=Path("/state/keys/vault.key")
assert key.stat().st_size == 32 and stat.S_IMODE(key.stat().st_mode) == 0o600
print(json.dumps({"version":health["app_version"],"database_type":health["database_type"],"configured_accounts":0,"provider_keys":0,"empty_profile":True,"encrypted_vault_ready":True,"frontend_http_status":200,"legacy_service_required":False}))
'''
    result = subprocess.run(["docker", "exec", container, "python", "-c", code], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError("test_container_private_defaults_or_frontend_check_failed")
    report = json.loads(result.stdout)
    if report["version"] != version:
        raise ValueError("container_application_version_mismatch")
    return report


def outputs(values: dict) -> None:
    filename = os.environ.get("GITHUB_OUTPUT")
    if filename:
        with Path(filename).open("a", encoding="utf-8") as handle:
            for key, value in values.items():
                if isinstance(value, str) and "\n" not in value:
                    handle.write(f"{key}={value}\n")
    print(json.dumps(values))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    resolve = sub.add_parser("resolve")
    resolve.add_argument("--repo", type=Path, required=True)
    resolve.add_argument("--tag", required=True)
    resolve.add_argument("--owner", required=True)
    lookup = sub.add_parser("lookup")
    lookup.add_argument("--owner", required=True)
    lookup.add_argument("--owner-type", required=True)
    lookup.add_argument("--version", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--inspect", type=Path, required=True)
    verify.add_argument("--version", required=True)
    verify.add_argument("--sha", required=True)
    verify.add_argument("--repository", required=True)
    verify.add_argument("--image", required=True)
    verify.add_argument("--output", type=Path, required=True)
    verify.add_argument("--local", action="store_true")
    smoke = sub.add_parser("smoke")
    smoke.add_argument("--container", required=True)
    smoke.add_argument("--version", required=True)
    smoke.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "resolve":
        outputs(resolve_release(args.repo, args.tag, args.owner))
    elif args.action == "lookup":
        outputs({"existing_digest": registry_version(args.owner, args.owner_type, args.version, os.environ["GH_TOKEN"])})
    elif args.action == "verify":
        result = verify_image(json.loads(args.inspect.read_text()), args.version, args.sha, args.repository)
        digests = [entry.split("@", 1)[1] for entry in result["repo_digests"] if entry.startswith(args.image + "@")]
        if (not digests and not args.local) or (digests and not DIGEST.fullmatch(digests[0])):
            raise ValueError("published_registry_digest_missing")
        if digests:
            result["digest"] = digests[0]
        result["verified_at_utc"] = datetime.now(timezone.utc).isoformat()
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        outputs({"digest": result["digest"]} if digests else {"image_id": result["image_id"]})
    else:
        result = smoke_container(args.container, args.version)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        outputs(result)


if __name__ == "__main__":
    main()
