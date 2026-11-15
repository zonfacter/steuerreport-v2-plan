#!/usr/bin/env python3
"""CI-only smoke harness for an already stopped, labelled synthetic container.

--output is a NEW directory below RUNNER_TEMP; only result.json survives.
--run-id must equal GITHUB_RUN_ID; restore IDs are derived as ci-RUNID-a/b.
The existing operator owns backup/restore logic and labelled Docker cleanup.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile


OPERATOR = Path(__file__).resolve().with_name("docker_state_v2.py")
ARCHIVE_LIMIT = 32 * 1024 * 1024
EXPANDED_LIMIT = 256 * 1024 * 1024
JSON_LIMIT = 1024 * 1024
OPERATOR_CLEANUP_WAIT_SECONDS = 120
SYNTHETIC_LABEL = "steuerreport.ci.synthetic"


class CIError(RuntimeError):
    pass


class OperatorStopUnknown(CIError):
    pass


@contextmanager
def _cancellation_handlers():
    previous = {}
    cancelled = False

    def cancel(signum, frame):
        nonlocal cancelled
        if not cancelled:
            cancelled = True
            raise KeyboardInterrupt

    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, cancel)
        yield
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


@contextmanager
def _defer_cancellation():
    previous = {}
    received = []
    try:
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.signal(signum, lambda sig, frame: received.append(sig))
        yield received
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise CIError(code)


def _json_object(raw: str) -> dict:
    try:
        value = json.loads(raw)
    except (ValueError, TypeError):
        raise CIError("invalid_json") from None
    _require(isinstance(value, dict), "invalid_json")
    return value


def _matches(pattern: str, value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def _inspect(container: str) -> dict:
    try:
        process = subprocess.run(
            ["docker", "container", "inspect", container],
            capture_output=True, text=True, timeout=30,
        )
        _require(process.returncode == 0, "source_inspect_failed")
        rows = json.loads(process.stdout)
        _require(isinstance(rows, list) and len(rows) == 1, "invalid_inspect")
        _require(isinstance(rows[0], dict), "invalid_inspect")
        return rows[0]
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        raise CIError("source_inspect_failed") from None


def _validate_source(info: dict, container: str, github_run: str) -> None:
    _require(_matches(r"[0-9a-f]{64}", info.get("Id")), "source_id_invalid")
    _require(info.get("Name") == "/" + container, "source_name_mismatch")
    _require(_matches(r"sha256:[0-9a-f]{64}", info.get("Image")), "source_image_invalid")
    config = info.get("Config")
    _require(isinstance(config, dict), "source_config_missing")
    labels = config.get("Labels")
    _require(isinstance(labels, dict) and labels.get(SYNTHETIC_LABEL) == github_run,
             "synthetic_label_mismatch")
    state = info.get("State")
    _require(isinstance(state, dict), "source_state_missing")
    _require(state.get("Status") == "exited" and state.get("Running") is False
             and state.get("Paused") is False and state.get("Restarting") is False
             and state.get("Dead") is False and state.get("OOMKilled") is False
             and state.get("Error") == "" and type(state.get("ExitCode")) is int
             and state["ExitCode"] in (0, 143), "source_not_cleanly_stopped")
    host = info.get("HostConfig")
    _require(isinstance(host, dict), "source_host_config_missing")
    _require(host.get("NetworkMode") == "none" and host.get("ReadonlyRootfs") is True,
             "source_isolation_mismatch")
    _require("PortBindings" in host and host["PortBindings"] in (None, {}), "source_ports_present")
    _require(not host.get("Binds") and not host.get("VolumesFrom"), "source_external_mounts")
    mounts = info.get("Mounts")
    _require(isinstance(mounts, list), "source_mounts_missing")
    volumes = []
    for mount in mounts:
        _require(isinstance(mount, dict), "source_mount_invalid")
        if mount.get("Type") == "tmpfs":
            _require(mount.get("Destination") == "/tmp", "source_tmpfs_mismatch")
            continue
        _require(mount.get("Type") == "volume", "source_non_volume_mount")
        volumes.append(mount)
    _require(len(volumes) == 1, "source_volume_count_mismatch")
    volume = volumes[0]
    _require(volume.get("Destination") == "/state" and volume.get("RW") is True
             and _matches(r"[0-9a-f]{64}", volume.get("Name")),
             "source_volume_mismatch")


def _check_source(original: dict, container: str, github_run: str, *, final: bool = False) -> None:
    current = _inspect(container)
    _validate_source(current, container, github_run)
    _require(current == original, "source_identity_changed")
    if final:
        by_id = _inspect(original["Id"])
        _validate_source(by_id, container, github_run)
        _require(by_id == original, "source_identity_changed")


def _bindings(container: str, run_id: str, output: Path) -> tuple[str, str, Path, Path]:
    github_run = os.environ.get("GITHUB_RUN_ID", "")
    _require(os.environ.get("GITHUB_ACTIONS") == "true", "github_actions_required")
    _require(bool(re.fullmatch(r"[0-9]+", github_run)), "github_run_id_invalid")
    match = re.fullmatch(r"sr-cache-([ab])-" + re.escape(github_run), container)
    _require(match is not None, "container_binding_mismatch")
    _require(run_id == github_run, "github_run_id_mismatch")
    restore_id = f"ci-{github_run}-{match[1]}"
    _require(len(restore_id) <= 41, "restore_run_id_invalid")
    runner = Path(os.environ.get("RUNNER_TEMP", ""))
    _require(runner.is_absolute() and runner.is_dir(), "runner_temp_required")
    runner = runner.resolve(strict=True)
    output = output.absolute()
    _require(".." not in output.parts, "output_path_invalid")
    _require(not output.exists() and not output.is_symlink(), "output_already_exists")
    _require(output.parent.is_dir(), "output_parent_missing")
    resolved = output.resolve(strict=False)
    _require(resolved == output and runner in resolved.parents, "output_not_in_runner_temp")
    return github_run, restore_id, output, runner


def _stop_operator(process: subprocess.Popen) -> bool:
    # Only interrupt the operator. Its cleanup commands must not receive a
    # process-group interrupt or an automatic SIGKILL from subprocess.run.
    with _defer_cancellation():
        try:
            if process.poll() is None:
                try:
                    process.send_signal(signal.SIGINT)
                except ProcessLookupError:
                    pass
            process.wait(timeout=OPERATOR_CLEANUP_WAIT_SECONDS)
            return process.returncode is not None
        except (Exception, KeyboardInterrupt, SystemExit):
            return False


def _operator(action: str, arguments: list[str], private: Path) -> dict:
    # Keep operator tempfile staging and raw output out of the publishable result.
    env = {**os.environ, "TMPDIR": str(private), "TMP": str(private), "TEMP": str(private)}
    stdout = private / (action + ".stdout.json")
    stderr = private / (action + ".stderr")
    stop_confirmed = True
    try:
        with stdout.open("x", encoding="utf-8") as out, stderr.open("x", encoding="utf-8") as err:
            process = None
            try:
                stop_confirmed = False
                process = subprocess.Popen([sys.executable, str(OPERATOR), action, *arguments],
                                           stdout=out, stderr=err, env=env, start_new_session=True)
                # The operator bounds its own work. Only cancellation has a
                # harness deadline, and an unconfirmed stop retains staging.
                process.wait()
                if process.returncode is None:
                    raise OperatorStopUnknown("operator_stop_unconfirmed")
                stop_confirmed = True
            except BaseException as exc:
                if process is None:
                    if isinstance(exc, FileNotFoundError):
                        stop_confirmed = True
                        raise CIError("operator_failed") from None
                    raise OperatorStopUnknown("operator_stop_unconfirmed") from None
                if not _stop_operator(process):
                    raise OperatorStopUnknown("operator_stop_unconfirmed") from None
                stop_confirmed = True
                if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                    raise CIError("operator_interrupted") from None
                raise CIError("operator_failed") from None
        _require(process.returncode == 0, "operator_failed")
        _require(stdout.stat().st_size <= JSON_LIMIT, "operator_json_too_large")
        return _json_object(stdout.read_text(encoding="utf-8"))
    except BaseException as exc:
        if not stop_confirmed:
            raise OperatorStopUnknown("operator_stop_unconfirmed") from None
        if isinstance(exc, (OSError, UnicodeError, subprocess.SubprocessError)):
            raise CIError("operator_failed") from None
        raise


def _positive_int(value: object) -> bool:
    return type(value) is int and value > 0


def _assert_metadata(backup: dict, verified: dict) -> None:
    _require(_positive_int(backup.get("schema_version"))
             and verified.get("schema_version") == backup["schema_version"]
             and type(verified.get("schema_version")) is int, "schema_mismatch")
    _require(isinstance(backup.get("image_version"), str) and bool(backup["image_version"])
             and verified.get("image_version") == backup["image_version"]
             and _matches(r"[0-9a-f]{40}", backup.get("image_revision"))
             and verified.get("image_revision") == backup["image_revision"], "image_mismatch")
    _require(type(backup.get("mount_count")) is int and backup["mount_count"] == 1
             and type(verified.get("mount_count")) is int and verified["mount_count"] == 1,
             "backup_mount_mismatch")


def _assert_restore(restored: dict, backup: dict, original: dict, run_id: str) -> None:
    _require(restored.get("status") == "passed" and restored.get("cleanup") is True
             and restored.get("cleanup_failures") == [], "restore_or_cleanup_failed")
    _require(restored.get("run_id") == run_id, "restore_run_id_mismatch")
    _require(restored.get("image_id") == original["Image"]
             and restored.get("version") == backup["image_version"]
             and restored.get("revision") == backup["image_revision"], "image_mismatch")
    _require(restored.get("network") == "none" and restored.get("published_ports") is False,
             "restore_isolation_mismatch")
    _require(restored.get("first_start_preserved") is True and restored.get("restart_preserved") is True,
             "restore_state_not_preserved")
    for key in ("restored_before_start", "after_first_start", "after_restart"):
        summary = restored.get(key)
        _require(isinstance(summary, dict), "restore_summary_missing")
        _require(type(summary.get("schema_version")) is int
                 and summary["schema_version"] == backup["schema_version"], "schema_mismatch")
        _require(summary.get("database_present") is True
                 and summary.get("required_private_files_present") is True, "restore_state_missing")
        _require(summary.get("catalog_fingerprint_present") is True, "catalog_check_missing")
        _require(summary.get("vault_decryptable") is True
                 and _positive_int(summary.get("encrypted_secret_rows"))
                 and type(summary.get("unreadable_secret_rows")) is int
                 and summary["unreadable_secret_rows"] == 0, "vault_check_failed")


def run(container: str, run_id: str, output: Path) -> dict:
    github_run, restore_id, output, runner = _bindings(container, run_id, output)
    original = _inspect(container)
    _validate_source(original, container, github_run)
    with _cancellation_handlers():
        return _run_checked(original, container, github_run, restore_id, output, runner)


def _run_checked(original: dict, container: str, github_run: str, restore_id: str,
                 output: Path, runner: Path) -> dict:
    result = {key: False for key in (
        "backup_created", "verified", "passed", "cleanup", "source_unchanged",
        "schema_match", "image_match", "vault_decryptable", "vault_rows_present",
        "private_staging_retained",
    )}
    result.update(format_version=1, status="failed")
    old_umask = os.umask(0o077)
    private = None
    private_safe = True
    try:
        output.mkdir(mode=0o700)  # No parents, reuse or symlinks.
        try:
            _check_source(original, container, github_run)
            private = Path(tempfile.mkdtemp(prefix="steuerreport-state-private-", dir=runner))
            result["private_staging_retained"] = True
            backup_dir = private / "backup"
            _check_source(original, container, github_run)
            # A terminal operator alone does not prove its Docker helpers were
            # cleaned. Retain staging until the complete positive response.
            private_safe = False
            backup = _operator("backup", ["--container", original["Id"], "--output-dir", str(backup_dir),
                                           "--confirm-source-stopped"], private)
            _require(backup.get("status") == "backup_created", "backup_not_created")
            _require(backup.get("source_pause_boundary_checked") is True,
                     "source_pause_boundary_unchecked")
            result["backup_created"] = True
            _assert_metadata(backup, backup)
            private_safe = True
            _check_source(original, container, github_run)
            private_safe = False
            verified = _operator("verify", ["--backup-dir", str(backup_dir),
                "--max-archive-bytes", str(ARCHIVE_LIMIT),
                "--max-uncompressed-bytes", str(EXPANDED_LIMIT),
                "--max-expanded-archive-bytes", str(EXPANDED_LIMIT)], private)
            _require(verified.get("status") == "verified", "backup_not_verified")
            _assert_metadata(backup, verified)
            result["verified"] = True
            private_safe = True
            _check_source(original, container, github_run)
            private_safe = False
            restored = _operator("restore-check", ["--backup-dir", str(backup_dir),
                "--evidence-dir", str(private / "evidence"), "--run-id", restore_id,
                "--image", original["Image"], "--max-archive-bytes", str(ARCHIVE_LIMIT),
                "--max-restore-bytes", str(EXPANDED_LIMIT),
                "--max-expanded-archive-bytes", str(EXPANDED_LIMIT)], private)
            _assert_restore(restored, backup, original, restore_id)
            private_safe = True
            for key in ("passed", "cleanup", "schema_match", "image_match", "vault_decryptable",
                        "vault_rows_present"):
                result[key] = True
        except OperatorStopUnknown:
            private_safe = False
            result.update(cleanup=False, reason="operator_stop_unconfirmed")
        except CIError as exc:
            result["reason"] = str(exc)
        except (KeyboardInterrupt, SystemExit):
            result["reason"] = "operator_interrupted"
        except Exception:
            result["reason"] = "harness_failed"
        finally:
            with _defer_cancellation() as received:
                try:
                    if private is not None and private_safe:
                        shutil.rmtree(private)
                        result["private_staging_retained"] = False
                except OSError:
                    result.update(cleanup=False, reason="private_cleanup_failed")
                try:
                    _check_source(original, container, github_run, final=True)
                    result["source_unchanged"] = True
                except Exception:
                    if private_safe:
                        result["reason"] = "final_source_check_failed"
            if received:
                result["cleanup"] = False
                result.setdefault("reason", "operator_interrupted")
        if result["private_staging_retained"]:
            result["cleanup"] = False
            result.setdefault("reason", "operator_cleanup_unconfirmed")
        if "reason" not in result:
            result["status"] = "passed"
        else:
            result["passed"] = False
        with (output / "result.json").open("x", encoding="ascii") as handle:
            json.dump(result, handle, sort_keys=True, indent=2)
            handle.write("\n")
        return result
    finally:
        os.umask(old_umask)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--container", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = run(args.container, args.run_id, args.output)
        return 0 if result["status"] == "passed" else 2
    except (CIError, OSError, ValueError, KeyboardInterrupt):
        print("portable_state_ci_refused", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
