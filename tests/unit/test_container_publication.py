import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import urllib.error
import tomllib

import pytest

from steuerreport_v2 import __version__


def load_script(name):
    path = Path(__file__).resolve().parents[2] / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_versions_match_runtime_package_frontend_and_container_defaults():
    root = Path(__file__).resolve().parents[2]
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    assert __version__ == version
    frontend_version = version.replace("rc", "-rc.")
    assert json.loads((root / "frontend/package.json").read_text())["version"] == frontend_version
    lock = json.loads((root / "frontend/package-lock.json").read_text())
    assert lock["version"] == lock["packages"][""]["version"] == frontend_version
    for name in ("compose.yml", "compose.ghcr.yml"):
        assert "steuerreport-v2:" + version in (root / name).read_text()
    assert "default: v" + version in (root / ".github/workflows/publish-image.yml").read_text()


@pytest.fixture
def release_repo(tmp_path):
    def git(*args):
        return subprocess.check_output(
            ["git", "-c", "user.name=Test Contributor", "-c", "user.email=test@example.invalid", *args],
            cwd=tmp_path, text=True, stderr=subprocess.DEVNULL,
        ).strip()

    git("init", "--quiet")
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "0.2.0rc3"\n')
    (tmp_path / "src").mkdir()
    (tmp_path / "src/app.py").write_text('VERSION = "0.2.0rc3"\n')
    git("add", ".")
    git("commit", "--quiet", "-m", "Synthetic release")
    git("tag", "v0.2.0rc3")
    return tmp_path, git


def test_resolver_uses_exact_tag_and_accepts_only_nonruntime_changes(release_repo):
    root, git = release_repo
    script = load_script("container_release_v2")
    sha = git("rev-parse", "HEAD")
    (root / "README.md").write_text("Publication instructions\n")
    git("add", ".")
    git("commit", "--quiet", "-m", "Documentation only")
    result = script.resolve_release(root, "v0.2.0rc3", "Example-Owner")
    assert result["source_sha"] == sha
    assert result["image"] == "ghcr.io/example-owner/steuerreport-v2"
    (root / "src/app.py").write_text('VERSION = "changed"\n')
    git("add", ".")
    git("commit", "--quiet", "-m", "Changed runtime")
    with pytest.raises(ValueError, match="runtime_differs"):
        script.resolve_release(root, "v0.2.0rc3", "Example-Owner")


@pytest.mark.parametrize("tag,owner", [("main", "example"), ("v0.2.0rc3;id", "example"), ("v0.2.0rc3", "bad/owner")])
def test_resolver_rejects_untrusted_references(release_repo, tag, owner):
    with pytest.raises(ValueError, match="invalid_release"):
        load_script("container_release_v2").resolve_release(release_repo[0], tag, owner)


def test_resolver_rejects_tag_version_mismatch(release_repo):
    root, git = release_repo
    git("tag", "v0.2.0rc4")
    with pytest.raises(ValueError, match="version_mismatch"):
        load_script("container_release_v2").resolve_release(root, "v0.2.0rc4", "example")


def test_provider_references_are_packaged_and_part_of_release_source_check(release_repo):
    root, git = release_repo
    script = load_script("container_release_v2")
    repository = Path(__file__).resolve().parents[2]
    name = "configs/provider_request_references.json"
    assert "!" + name in (repository / ".dockerignore").read_text().splitlines()
    assert name in script.IMAGE_INPUTS
    (root / "configs").mkdir()
    (root / name).write_text('{"providers": []}\n')
    git("add", ".")
    git("commit", "--quiet", "-m", "Changed provider references")
    with pytest.raises(ValueError, match="runtime_differs"):
        script.resolve_release(root, "v0.2.0rc3", "example")


def image_inspect():
    return [{
        "Id": "sha256:" + "0" * 64, "Os": "linux", "Architecture": "amd64",
        "RepoDigests": ["ghcr.io/example/steuerreport-v2@sha256:" + "1" * 64],
        "Config": {"User": "10001:10001", "Env": ["LANG=C.UTF-8"], "Labels": {
            "org.opencontainers.image.source": "https://github.com/example/project",
            "org.opencontainers.image.revision": "a" * 40,
            "org.opencontainers.image.version": "0.2.0rc3",
        }},
    }]


def test_image_requires_exact_release_nonroot_and_no_baked_credentials():
    script = load_script("container_release_v2")
    good = image_inspect()
    assert script.verify_image(good, "0.2.0rc3", "a" * 40, "example/project")["non_root"]
    for field, value in [("User", "root"), ("Env", ["HELIUS_API_KEY=synthetic-not-a-key"])]:
        bad = image_inspect()
        bad[0]["Config"][field] = value
        with pytest.raises(ValueError):
            script.verify_image(bad, "0.2.0rc3", "a" * 40, "example/project")
    with pytest.raises(ValueError, match="source_labels"):
        script.verify_image(good, "0.2.0rc4", "a" * 40, "example/project")
    good[0]["Architecture"] = "arm64"
    with pytest.raises(ValueError, match="platform"):
        script.verify_image(good, "0.2.0rc3", "a" * 40, "example/project")


def test_secret_reviews_are_exact_whole_line_and_rule_scoped(tmp_path):
    script = load_script("check_release_secrets_v2")
    text = 'EXAMPLE = "replace-before-use"\n'
    (tmp_path / "example.py").write_text(text)
    finding = {"File": "example.py", "StartLine": 1, "EndLine": 1, "RuleID": "generic-api-key"}
    approved = [{"file": "example.py", "rule": "generic-api-key", "source_lines_sha256": hashlib.sha256(text.encode()).hexdigest(), "reason": "Explicit placeholder"}]
    assert script.review(tmp_path, [finding], approved, 1)["unreviewed_findings"] == 0
    assert script.review(tmp_path, [{**finding, "RuleID": "new-rule"}], approved, 1)["unreviewed_findings"] == 1
    (tmp_path / "example.py").write_text(text.rstrip() + ' # changed content\n')
    assert script.review(tmp_path, [finding], approved, 1)["unreviewed_findings"] == 1
    with pytest.raises(ValueError, match="outside_source"):
        script.review(tmp_path, [{**finding, "File": "../outside.py"}], approved, 1)


@pytest.mark.parametrize("findings,code", [([], 1), ([], 2), ([{}], 0)])
def test_secret_scanner_errors_fail_closed(tmp_path, findings, code):
    with pytest.raises(ValueError, match="scanner_failed"):
        load_script("check_release_secrets_v2").review(tmp_path, findings, [], code)


def test_registry_lookup_requires_valid_digest_and_fails_on_denied_access(monkeypatch):
    script = load_script("container_release_v2")
    digest = "sha256:" + "b" * 64
    row = {"name": digest, "metadata": {"container": {"tags": ["0.2.0rc3"]}}}
    monkeypatch.setattr(script.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(json.dumps([row]).encode()))
    assert script.registry_version("example", "User", "0.2.0rc3", "test-only") == digest
    row["name"] = "invalid-digest"
    with pytest.raises(ValueError, match="digest_invalid"):
        script.registry_version("example", "User", "0.2.0rc3", "test-only")

    def denied(*args, **kwargs):
        raise urllib.error.HTTPError("https://api.github.com", 403, "Forbidden", {}, None)

    monkeypatch.setattr(script.urllib.request, "urlopen", denied)
    with pytest.raises(RuntimeError, match="http_403"):
        script.registry_version("example", "User", "0.2.0rc3", "test-only")


def test_registry_lookup_handles_first_publication(monkeypatch):
    script = load_script("container_release_v2")

    def missing(*args, **kwargs):
        raise urllib.error.HTTPError("https://api.github.com", 404, "Not Found", {}, None)

    monkeypatch.setattr(script.urllib.request, "urlopen", missing)
    assert script.registry_version("example", "User", "0.2.0rc3", "test-only") == ""
