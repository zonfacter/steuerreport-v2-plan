from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts/storage_inventory_v2.py"
SPEC = importlib.util.spec_from_file_location("storage_inventory_v2", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
storage_inventory = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(storage_inventory)


def _docker_result(stdout: str = "", *, returncode: int = 0, stderr: str = ""):
    return subprocess.CompletedProcess(
        args=["docker", "system", "df"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _summary() -> str:
    return "\n".join(
        [
            "Images|4|2|1.25GB|250MB (20%)",
            "Containers|3|1|12.5MB|8.0MB (64%)",
            "Local Volumes|5|3|4.0GB|1.0GB (25%)",
            "Build Cache|7|2|750MB|500MB (66.7%)",
        ]
    )


def test_aggregate_summary_reports_sizes_without_names_or_cleanup(tmp_path, capsys):
    calls = []

    def runner(command, **kwargs):
        calls.append((command, kwargs))
        return _docker_result(_summary())

    sentinel = tmp_path / "personal-wallet-export.csv"
    sentinel.write_text("must not be read", encoding="utf-8")
    before = sentinel.stat()
    exit_code = storage_inventory.main(
        ["--path", str(tmp_path), "--docker-data-path", str(tmp_path), "--json"],
        docker_runner=runner,
    )
    after = sentinel.stat()

    assert exit_code == 0
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["mode"] == "read_only"
    assert report["docker"]["status"] == "available"
    assert {row["type"] for row in report["docker"]["resources"]} == {
        "images",
        "containers",
        "local_volumes",
        "build_cache",
    }
    volumes = next(row for row in report["docker"]["resources"] if row["type"] == "local_volumes")
    assert volumes["docker_reported_size"] == "4.0GB"
    assert volumes["docker_reported_reclaimable"] == "1.0GB (25%)"
    assert volumes["reclaimable_is_safe_to_delete"] is False
    assert all(row["free_bytes"] >= 0 for row in report["filesystems"])
    assert str(tmp_path) not in output
    assert sentinel.name not in json.dumps(report)
    assert before.st_mtime_ns == after.st_mtime_ns
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command == ["docker", "system", "df", "--format", storage_inventory.DOCKER_DF_FORMAT]
    assert kwargs["capture_output"] is True and kwargs["check"] is False
    assert not any(word in command for word in ("prune", "rm", "volume", "inspect"))


def test_docker_failure_is_partial_and_stderr_is_redacted(tmp_path, capsys):
    def runner(command, **kwargs):
        return _docker_result(returncode=1, stderr="token=secret /home/private/account")

    exit_code = storage_inventory.main(["--path", str(tmp_path), "--json"], docker_runner=runner)
    output = capsys.readouterr().out
    report = json.loads(output)

    assert exit_code == 1
    assert report["status"] == "partial"
    assert report["docker"]["reason"] == "docker_command_failed"
    assert "secret" not in output and "/home/private/account" not in output


def test_unrecognized_docker_output_is_not_echoed(tmp_path, capsys):
    private_value = "wallet-seed-file.csv"

    def runner(command, **kwargs):
        return _docker_result(f"{private_value}|4|2|1GB|1GB (100%)")

    assert storage_inventory.main(["--path", str(tmp_path), "--json"], docker_runner=runner) == 1
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["docker"]["reason"] == "docker_output_unrecognized"
    assert private_value not in output


def test_filesystem_error_does_not_echo_path(tmp_path, capsys):
    missing_path = tmp_path / "private" / "wallet-data"

    def runner(command, **kwargs):
        return _docker_result(_summary())

    assert storage_inventory.main(["--path", str(missing_path), "--json"], docker_runner=runner) == 1
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["filesystems"][0]["reason"] == "path_not_found"
    assert str(missing_path) not in output


def test_docker_timeout_is_reported_without_exception_details(tmp_path, capsys):
    def runner(command, **kwargs):
        raise subprocess.TimeoutExpired(command, timeout=kwargs["timeout"], stderr="secret-path")

    assert storage_inventory.main(["--path", str(tmp_path), "--json"], docker_runner=runner) == 1
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["docker"]["reason"] == "docker_command_timeout"
    assert "secret-path" not in output


def test_missing_docker_cli_is_reported_without_path(tmp_path, capsys):
    def runner(command, **kwargs):
        raise FileNotFoundError("/private/docker-binary")

    assert storage_inventory.main(["--path", str(tmp_path), "--json"], docker_runner=runner) == 1
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["docker"]["reason"] == "docker_cli_not_found"
    assert "/private/docker-binary" not in output


def test_human_output_is_path_free_and_warns_against_deletion(tmp_path, capsys):
    def runner(command, **kwargs):
        return _docker_result(_summary())

    assert storage_inventory.main(["--path", str(tmp_path)], docker_runner=runner) == 0
    output = capsys.readouterr().out
    assert "Speicherdiagnose (nur lesend)" in output
    assert "reclaimable 1.0GB (25%)" in output
    assert "keine Aussage zur sicheren Loeschbarkeit" in output
    assert str(tmp_path) not in output
