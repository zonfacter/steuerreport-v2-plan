#!/usr/bin/env python3
"""Portable, offline Docker state backup and isolated restore verifier.

This tool never switches a production Compose project. Backup requires an
explicitly stopped source container. Restore verification uses new, labelled
volumes, no network, and no published ports, then removes only its own test
resources.
"""
from __future__ import annotations

import argparse
import datetime as dt
import decimal
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
import zlib


FORMAT_VERSION = 1
MAX_MANIFEST_SIZE_BYTES = 32 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 250_000
RESTORE_CLEANUP_ATTEMPTS = 10
RESTORE_CLEANUP_DELAY_SECONDS = 0.25
RESOURCE_LABEL = "steuerreport.ops.restore"
PATH_ENV_KEYS = (
    "STEUERREPORT_STATE_DIR",
    "STEUERREPORT_V2_DB",
    "STEUERREPORT_USERTRANSFER_ROOT",
    "STEUERREPORT_PRIVATE_PROFILE",
    "STEUERREPORT_PRIVATE_CONFIG_DIR",
    "STEUERREPORT_V2_SECRET_VAULT_KEY_FILE",
    "STEUERREPORT_V2_CONNECTOR_SETUP_TOKEN_FILE",
    "STEUERREPORT_V2_MOBILE_DOCUMENT_ROOT",
    "STEUERREPORT_MOONPAY_TRADE_HISTORY_PATH",
    "STEUERREPORT_SPARKASSE_CAMT_DIR",
    "STEUERREPORT_SPARKASSE_STATEMENT_DIR",
    "STEUERREPORT_TRADE_REPUBLIC_DOCUMENT_ROOT",
    "STEUERREPORT_INHERITANCE_DOCUMENT_ROOT",
    "STEUERREPORT_INHERITANCE_DOCUMENT_PATH",
)
IMAGE_LABELS = (
    "org.opencontainers.image.version",
    "org.opencontainers.image.revision",
    "org.opencontainers.image.source",
)
SOFTWARE_PATH_ENV_KEYS = {"STEUERREPORT_V2_ROOT"}


class OpsError(RuntimeError):
    pass


class _CappedReader:
    def __init__(self, source, limit: int) -> None:
        self.source = source
        self.limit = limit
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        remaining_with_probe = self.limit - self.bytes_read + 1
        requested = remaining_with_probe if size < 0 else min(size, remaining_with_probe)
        data = self.source.read(requested)
        self.bytes_read += len(data)
        if self.bytes_read > self.limit:
            _fail("expanded_archive_exceeds_operator_limit")
        return data


def _fail(code: str) -> None:
    raise OpsError(code)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      default=_encode_value).encode("ascii")


def _encode_value(value: object) -> object:
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, (dt.date, dt.time, decimal.Decimal, uuid.UUID)):
        return {type(value).__name__: str(value)}
    if isinstance(value, dt.timedelta):
        return {"timedelta": str(value)}
    raise TypeError(type(value).__name__)


def _docker(args: list[str], *, timeout: int = 120) -> str:
    try:
        result = subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        _fail("docker_cli_not_found")
    except subprocess.TimeoutExpired:
        _fail("docker_command_timeout:" + (args[0] if args else "unknown"))
    except OSError as exc:
        _fail("docker_command_os_error:" + str(exc.errno or "unknown"))
    if result.returncode:
        _fail("docker_command_failed:" + (args[0] if args else "unknown") + ":" + str(result.returncode))
    return result.stdout


def _inspect(kind: str, name: str) -> dict:
    try:
        value = json.loads(_docker([kind, "inspect", name]))
    except (json.JSONDecodeError, TypeError):
        _fail("docker_inspect_response_invalid")
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        _fail("docker_inspect_response_invalid")
    return value[0]


def _image_info(image: str) -> dict:
    value = _inspect("image", image)
    labels = value.get("Config", {}).get("Labels") or {}
    if not all(labels.get(key) for key in IMAGE_LABELS):
        _fail("image_release_labels_missing")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", value.get("Id", "")):
        _fail("image_id_invalid")
    if not re.fullmatch(r"[0-9a-f]{40}", labels[IMAGE_LABELS[1]]):
        _fail("image_revision_invalid")
    return {
        "image_id": value["Id"],
        "version": labels[IMAGE_LABELS[0]],
        "revision": labels[IMAGE_LABELS[1]],
        "source": labels[IMAGE_LABELS[2]],
        "platform": value.get("Os", "") + "/" + value.get("Architecture", ""),
        "repo_digests": value.get("RepoDigests") or [],
    }


def _mounts(container: dict) -> list[dict]:
    rows = []
    for index, item in enumerate(container.get("Mounts") or []):
        kind = item.get("Type")
        target = item.get("Destination")
        if kind == "tmpfs":
            continue
        if kind not in {"volume", "bind"} or not isinstance(target, str) or not target.startswith("/"):
            _fail("unsupported_persistent_mount_type")
        writable = item.get("RW")
        if not isinstance(writable, bool):
            _fail("persistent_mount_access_mode_unknown")
        target = posixpath.normpath(target)
        if target == "/" or "," in target or any(ord(char) < 32 for char in target):
            _fail("persistent_mount_target_unsupported")
        if kind == "volume":
            source = item.get("Name")
            if not isinstance(source, str) or not source:
                _fail("volume_mount_name_missing")
        else:
            source = item.get("Source")
            if not isinstance(source, str) or not Path(source).is_absolute():
                _fail("bind_mount_source_invalid")
            source_path = Path(source)
            if source_path.is_symlink() or not source_path.is_dir():
                _fail("bind_mount_must_be_real_directory")
        rows.append({
            "id": f"m{index:03d}",
            "kind": kind,
            "target": target,
            "read_only": not writable,
            "source": source,
            "archive_prefix": f"mounts/m{index:03d}",
            "helper_root": f"/backup-input/m{index:03d}",
        })
    if not rows:
        _fail("persistent_mounts_not_found")
    targets = [item["target"] for item in rows]
    if len(targets) != len(set(targets)):
        _fail("duplicate_mount_target")
    for parent in targets:
        if any(child.startswith(parent.rstrip("/") + "/") for child in targets if child != parent):
            _fail("overlapping_persistent_mounts_unsupported")
    return rows


def _assert_no_running_consumers(source_container: dict, mounts: list[dict]) -> None:
    if source_container.get("State", {}).get("Status") != "exited":
        _fail("source_container_must_be_stopped")
    state = source_container.get("State", {})
    if state.get("OOMKilled") or state.get("Error"):
        _fail("source_container_has_unclean_exit")
    if state.get("ExitCode") not in {0, 143}:
        _fail("source_container_exit_code_not_clean")
    ids = [item for item in _docker(["ps", "--quiet"]).splitlines() if item]
    if not ids:
        return
    containers = json.loads(_docker(["inspect", *ids]))
    volume_names = {item["source"] for item in mounts if item["kind"] == "volume"}
    bind_sources = [Path(item["source"]).resolve() for item in mounts if item["kind"] == "bind"]
    source_id = source_container.get("Id")
    for other in containers:
        if other.get("Id") == source_id:
            _fail("source_container_must_be_stopped")
        for mount in other.get("Mounts") or []:
            if mount.get("Type") == "volume" and mount.get("Name") in volume_names:
                _fail("persistent_volume_has_running_consumer")
            if mount.get("Type") == "bind" and mount.get("Source"):
                other_source = Path(mount["Source"]).resolve()
                if any(other_source == source or other_source in source.parents or source in other_source.parents
                       for source in bind_sources):
                    _fail("external_bind_has_running_consumer")


def _helper_mount_args(mounts: list[dict], *, writable_ids: set[str] | None = None) -> list[str]:
    writable_ids = writable_ids or set()
    args: list[str] = []
    for item in mounts:
        target = item.get("helper_root") or "/restore-input/" + item["id"]
        source = item["source"]
        readonly = item["id"] not in writable_ids
        mode = ",readonly" if readonly else ""
        if item["kind"] == "volume":
            args.extend(["--mount", f"type=volume,src={source},dst={target}{mode}"])
        else:
            if "," in source:
                _fail("bind_mount_source_contains_unsupported_separator")
            args.extend(["--mount", f"type=bind,src={source},dst={target}{mode}"])
    return args


def _helper_command(image: str, script: Path, mode: str, mounts: list[dict], payload: dict,
                    *, cidfile: Path, run_id: str, writable_ids: set[str] | None = None,
                    extra_mounts: list[tuple[Path, str]] | None = None) -> list[str]:
    capabilities = ["CHOWN", "DAC_OVERRIDE", "FOWNER"] if mode == "extract" else ["DAC_READ_SEARCH"]
    args = [
        "run", "--rm", "--cidfile", str(cidfile), "--stop-timeout", "10",
        "--label", RESOURCE_LABEL + "=" + run_id,
        "--pull=never", "--network", "none", "--read-only",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true", "--user", "0:0",
        "--cpus", "1", "--memory", "1g", "--memory-swap", "1g", "--pids-limit", "128",
        "--tmpfs", "/tmp:rw,size=768m,mode=1777",
    ]
    for capability in capabilities:
        args.extend(["--cap-add", capability])
    args.extend(_helper_mount_args(mounts, writable_ids=writable_ids))
    if "," in str(script):
        _fail("host_path_contains_unsupported_separator")
    args.extend(["--mount", f"type=bind,src={script},dst=/tmp/steuerreport_operator.py,readonly"])
    for host, dest in extra_mounts or []:
        if "," in str(host):
            _fail("host_path_contains_unsupported_separator")
        args.extend(["--mount", f"type=bind,src={host},dst={dest},readonly"])
    args.extend(["--entrypoint", "python", image, "/tmp/steuerreport_operator.py", "_helper", mode,
                 _json_bytes(payload).decode("ascii")])
    return args


def _helper_json(image: str, script: Path, mode: str, mounts: list[dict], payload: dict,
                 *, writable_ids: set[str] | None = None, extra_mounts: list[tuple[Path, str]] | None = None) -> dict:
    with tempfile.TemporaryDirectory(prefix="steuerreport-helper-") as temp_dir:
        cidfile = Path(temp_dir) / "container.id"
        run_id = "helper-" + uuid.uuid4().hex
        command = _helper_command(image, script, mode, mounts, payload, cidfile=cidfile,
                                  run_id=run_id, writable_ids=writable_ids, extra_mounts=extra_mounts)
        return _run_helper_command(command, cidfile, run_id=run_id, timeout=600)


def _run_helper_command(command: list[str], cidfile: Path, *, run_id: str, timeout: int) -> dict:
    try:
        completed = subprocess.run(["docker", *command], capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        _fail("docker_cli_not_found")
    except subprocess.TimeoutExpired:
        if not _cleanup_helper_container(cidfile, run_id):
            _fail("operator_helper_timeout_cleanup_unconfirmed")
        _fail("operator_helper_timeout")
    except OSError as exc:
        _fail("docker_run_os_error:" + str(exc.errno or "unknown"))
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        if completed.returncode:
            _fail("docker_command_failed:run:" + str(completed.returncode))
        _fail("operator_helper_response_invalid")
    if completed.returncode:
        reason = result.get("error") if isinstance(result, dict) else None
        _fail(str(reason) if isinstance(reason, str) else "docker_command_failed:run:" + str(completed.returncode))
    if not isinstance(result, dict):
        _fail("operator_helper_response_invalid")
    return result


def _cleanup_helper_container(cidfile: Path, run_id: str) -> bool:
    try:
        container_id = cidfile.read_text(encoding="ascii").strip()
        container_ids = [container_id]
    except FileNotFoundError:
        try:
            container_ids = _docker([
                "ps", "--all", "--quiet", "--no-trunc",
                "--filter", f"label={RESOURCE_LABEL}={run_id}",
            ]).split()
        except OpsError:
            return False
    except OpsError:
        return False
    except OSError:
        return False
    if not all(re.fullmatch(r"[0-9a-f]{64}", container_id) for container_id in container_ids):
        return False
    return all(
        _cleanup_restore_resource("container", container_id, run_id) is None
        for container_id in container_ids
    )


def _ensure_new_private_dir(path: Path) -> None:
    if path.exists():
        _fail("output_directory_already_exists")
    if not path.parent.is_dir():
        _fail("output_parent_directory_missing")
    path.mkdir(mode=0o700)
    if stat.S_IMODE(path.stat().st_mode) != 0o700:
        _fail("output_directory_permissions_invalid")


def _write_private_json(path: Path, value: dict) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _safe_archive_records(
    archive_path: Path,
    expected_mounts: list[dict] | None = None,
    *,
    max_uncompressed_bytes: int | None = None,
    max_archive_bytes: int | None = None,
    max_expanded_archive_bytes: int | None = None,
) -> list[dict]:
    if max_uncompressed_bytes is not None and (
        not isinstance(max_uncompressed_bytes, int) or isinstance(max_uncompressed_bytes, bool)
        or max_uncompressed_bytes < 1
    ):
        _fail("restore_size_limit_invalid")
    if max_archive_bytes is not None and (
        not isinstance(max_archive_bytes, int) or isinstance(max_archive_bytes, bool) or max_archive_bytes < 1
    ):
        _fail("archive_size_limit_invalid")
    if max_expanded_archive_bytes is not None and (
        not isinstance(max_expanded_archive_bytes, int) or isinstance(max_expanded_archive_bytes, bool)
        or max_expanded_archive_bytes < 1
    ):
        _fail("expanded_archive_size_limit_invalid")
    try:
        archive_size = archive_path.stat().st_size
    except OSError:
        _fail("archive_unreadable")
    if max_archive_bytes is not None and archive_size > max_archive_bytes:
        _fail("archive_size_exceeds_operator_limit")
    records = []
    seen = set()
    uncompressed_size = 0
    try:
        with archive_path.open("rb") as compressed:
            with gzip.GzipFile(fileobj=compressed, mode="rb") as expanded:
                capped = _CappedReader(expanded, max_expanded_archive_bytes) if max_expanded_archive_bytes else expanded
                with tarfile.open(fileobj=capped, mode="r|") as archive:
                    for member in archive:
                        name = member.name
                        path = PurePosixPath(name)
                        canonical_name = name.rstrip("/")
                        if (path.is_absolute() or not path.parts or ".." in path.parts
                                or path.as_posix() != canonical_name or name in seen):
                            _fail("archive_member_path_invalid")
                        if not (member.isdir() or member.isreg()):
                            _fail("archive_member_type_unsupported")
                        if member.size < 0:
                            _fail("archive_member_size_invalid")
                        if member.isreg():
                            uncompressed_size += member.size
                            if max_uncompressed_bytes is not None and uncompressed_size > max_uncompressed_bytes:
                                _fail("restore_size_exceeds_operator_limit")
                        if len(records) >= MAX_ARCHIVE_MEMBERS:
                            _fail("archive_member_count_exceeds_limit")
                        seen.add(name)
                        record = {
                            "path": name,
                            "type": "directory" if member.isdir() else "file",
                            "uid": member.uid,
                            "gid": member.gid,
                            "mode": stat.S_IMODE(member.mode),
                            "size": member.size,
                        }
                        if member.isreg():
                            extracted = archive.extractfile(member)
                            if extracted is None:
                                _fail("archive_member_unreadable")
                            digest = hashlib.sha256()
                            for chunk in iter(lambda: extracted.read(1024 * 1024), b""):
                                digest.update(chunk)
                            record["sha256"] = digest.hexdigest()
                        records.append(record)
                    if isinstance(capped, _CappedReader):
                        while capped.read(1024 * 1024):
                            pass
    except (tarfile.TarError, OSError, EOFError, gzip.BadGzipFile, zlib.error):
        _fail("archive_unreadable")
    if not records:
        _fail("archive_empty")
    if expected_mounts is not None:
        if not isinstance(expected_mounts, list) or not expected_mounts or not all(
            isinstance(item, dict) and isinstance(item.get("archive_prefix"), str) for item in expected_mounts
        ):
            _fail("backup_mount_manifest_invalid")
        valid_prefixes = {item["archive_prefix"] for item in expected_mounts}
        for row in records:
            if not any(row["path"] == prefix or row["path"].startswith(prefix + "/")
                       for prefix in valid_prefixes):
                _fail("archive_contains_unlisted_mount_path")
    records.sort(key=lambda item: item["path"])
    return records


def _load_backup(
    directory: Path,
    *,
    max_uncompressed_bytes: int | None = None,
    max_archive_bytes: int | None = None,
    max_expanded_archive_bytes: int | None = None,
) -> tuple[Path, dict]:
    if max_uncompressed_bytes is not None and (
        not isinstance(max_uncompressed_bytes, int) or isinstance(max_uncompressed_bytes, bool)
        or max_uncompressed_bytes < 1
    ):
        _fail("restore_size_limit_invalid")
    if max_archive_bytes is not None and (
        not isinstance(max_archive_bytes, int) or isinstance(max_archive_bytes, bool) or max_archive_bytes < 1
    ):
        _fail("archive_size_limit_invalid")
    if max_expanded_archive_bytes is not None and (
        not isinstance(max_expanded_archive_bytes, int) or isinstance(max_expanded_archive_bytes, bool)
        or max_expanded_archive_bytes < 1
    ):
        _fail("expanded_archive_size_limit_invalid")
    if directory.is_symlink() or not directory.is_dir() or stat.S_IMODE(directory.stat().st_mode) & 0o077:
        _fail("backup_directory_not_private")
    archive = directory / "state.tar.gz"
    manifest_path = directory / "manifest.json"
    if archive.is_symlink() or manifest_path.is_symlink() or not archive.is_file() or not manifest_path.is_file():
        _fail("backup_files_missing")
    if manifest_path.stat().st_size > MAX_MANIFEST_SIZE_BYTES:
        _fail("backup_manifest_too_large")
    if stat.S_IMODE(archive.stat().st_mode) & 0o077 or stat.S_IMODE(manifest_path.stat().st_mode) & 0o077:
        _fail("backup_file_permissions_invalid")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        _fail("backup_manifest_invalid")
    if (not isinstance(manifest, dict) or isinstance(manifest.get("format_version"), bool)
            or manifest.get("format_version") != FORMAT_VERSION):
        _fail("backup_format_unsupported")
    if not isinstance(manifest.get("mounts"), list) or not manifest["mounts"] or not all(
        isinstance(row, dict)
        and all(isinstance(row.get(key), str) for key in ("id", "kind", "target", "archive_prefix"))
        and isinstance(row.get("read_only"), bool)
        for row in manifest["mounts"]
    ):
        _fail("backup_mount_manifest_invalid")
    if not isinstance(manifest.get("source_image"), dict) or not all(
        isinstance(manifest["source_image"].get(key), str)
        for key in ("image_id", "revision", "version", "platform")
    ):
        _fail("backup_image_manifest_invalid")
    if (not re.fullmatch(r"sha256:[0-9a-f]{64}", manifest["source_image"]["image_id"])
            or not re.fullmatch(r"[0-9a-f]{40}", manifest["source_image"]["revision"])):
        _fail("backup_image_manifest_invalid")
    if not isinstance(manifest.get("archive_members"), list) or not manifest["archive_members"]:
        _fail("backup_member_manifest_invalid")
    if (not isinstance(manifest.get("schema_version"), int) or isinstance(manifest.get("schema_version"), bool)
            or manifest["schema_version"] < 1
            or not isinstance(manifest.get("archive_size_bytes"), int)
            or isinstance(manifest.get("archive_size_bytes"), bool)
            or manifest["archive_size_bytes"] < 1
            or not isinstance(manifest.get("archive_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", manifest["archive_sha256"])
            or not isinstance(manifest.get("wal_files"), list)
            or not all(isinstance(item, str) for item in manifest["wal_files"])):
        _fail("backup_manifest_invalid")
    tables = manifest.get("database_tables")
    if (manifest.get("database_present") is not True or not isinstance(tables, dict)
            or not isinstance(manifest.get("database_table_count"), int)
            or isinstance(manifest.get("database_table_count"), bool)
            or manifest["database_table_count"] != len(tables)
            or not isinstance(manifest.get("database_row_count"), int)
            or isinstance(manifest.get("database_row_count"), bool)):
        _fail("backup_database_manifest_invalid")
    if any(not isinstance(name, str) or not isinstance(row, dict)
           or not isinstance(row.get("rows"), int) or isinstance(row.get("rows"), bool) or row["rows"] < 0
           or not isinstance(row.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
           for name, row in tables.items()):
        _fail("backup_database_manifest_invalid")
    if (sum(row["rows"] for row in tables.values()) != manifest["database_row_count"]
            or hashlib.sha256(_json_bytes(tables)).hexdigest() != manifest.get("database_semantic_sha256")):
        _fail("backup_database_manifest_invalid")
    runtime_paths = manifest.get("runtime_paths")
    if not isinstance(runtime_paths, dict) or not all(
        key in PATH_ENV_KEYS and isinstance(value, str) for key, value in runtime_paths.items()
    ):
        _fail("backup_manifest_runtime_path_invalid")
    mount_ids = [row["id"] for row in manifest["mounts"]]
    mount_targets = [row["target"] for row in manifest["mounts"]]
    prefixes = [row["archive_prefix"] for row in manifest["mounts"]]
    if (len(set(mount_ids)) != len(mount_ids) or len(set(mount_targets)) != len(mount_targets)
            or len(set(prefixes)) != len(prefixes)
            or any(not re.fullmatch(r"m[0-9]{3}", item) for item in mount_ids)
            or any(not target.startswith("/") or posixpath.normpath(target) != target or target == "/"
                   or any(ord(char) < 32 for char in target) or "," in target
                   for target in mount_targets)
            or any(row.get("kind") not in {"volume", "bind"} for row in manifest["mounts"])
            or any(not isinstance(row.get("read_only"), bool) for row in manifest["mounts"])
            or any(prefix != "mounts/" + mount_id for prefix, mount_id in zip(prefixes, mount_ids))):
        _fail("backup_mount_manifest_invalid")
    for parent in mount_targets:
        if any(child.startswith(parent.rstrip("/") + "/") for child in mount_targets if child != parent):
            _fail("backup_mount_manifest_invalid")
    member_paths = []
    declared_uncompressed_size = 0
    for row in manifest["archive_members"]:
        if (not isinstance(row, dict) or not isinstance(row.get("path"), str)
                or row.get("type") not in {"file", "directory"}
                or any(not isinstance(row.get(key), int) or isinstance(row.get(key), bool)
                       for key in ("uid", "gid", "mode", "size"))
                or row["uid"] < 0 or row["gid"] < 0 or row["mode"] < 0 or row["mode"] > 0o7777
                or row["size"] < 0):
            _fail("backup_member_manifest_invalid")
        path = PurePosixPath(row["path"])
        if path.is_absolute() or not path.parts or ".." in path.parts or path.as_posix() != row["path"]:
            _fail("backup_member_manifest_invalid")
        if row["type"] == "file":
            if not isinstance(row.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
                _fail("backup_member_manifest_invalid")
            declared_uncompressed_size += row["size"]
        elif row["size"] != 0 or "sha256" in row:
            _fail("backup_member_manifest_invalid")
        member_paths.append(row["path"])
    if len(set(member_paths)) != len(member_paths):
        _fail("backup_member_manifest_invalid")
    wal_paths = manifest["wal_files"]
    archived_wal_paths = [path for path in member_paths if PurePosixPath(path).name.endswith(".wal")]
    if sorted(wal_paths) != sorted(archived_wal_paths):
        _fail("backup_wal_manifest_mismatch")
    if max_uncompressed_bytes is not None and declared_uncompressed_size > max_uncompressed_bytes:
        _fail("restore_size_exceeds_operator_limit")
    if max_archive_bytes is not None and archive.stat().st_size > max_archive_bytes:
        _fail("archive_size_exceeds_operator_limit")
    if archive.stat().st_size != manifest["archive_size_bytes"]:
        _fail("backup_archive_size_mismatch")
    if _sha256(archive) != manifest["archive_sha256"]:
        _fail("backup_archive_hash_mismatch")
    records = _safe_archive_records(
        archive, manifest["mounts"], max_uncompressed_bytes=max_uncompressed_bytes,
        max_archive_bytes=max_archive_bytes, max_expanded_archive_bytes=max_expanded_archive_bytes,
    )
    if records != manifest.get("archive_members"):
        _fail("backup_member_manifest_mismatch")
    return archive, manifest


def backup(args: argparse.Namespace) -> dict:
    source = _inspect("container", args.container)
    mounts = _mounts(source)
    _assert_no_running_consumers(source, mounts)
    if any(item["kind"] == "bind" for item in mounts) and not args.confirm_external_paths_quiesced:
        _fail("confirm_external_paths_quiesced_required")
    image_id = source.get("Image")
    if not image_id:
        _fail("source_image_missing")
    image = _image_info(image_id)
    image["container_reference"] = source.get("Config", {}).get("Image", "")
    env_rows = source.get("Config", {}).get("Env") or []
    env = dict(entry.split("=", 1) for entry in env_rows if "=" in entry)
    path_like = re.compile(r"(?:PATH|FILE|ROOT|DIR)$", re.I)
    if any(key.startswith("STEUERREPORT_") and path_like.search(key)
           and key not in PATH_ENV_KEYS and key not in SOFTWARE_PATH_ENV_KEYS
           and value for key, value in env.items()):
        _fail("unrecognized_persistent_path_environment")
    runtime_paths = {key: env[key] for key in PATH_ENV_KEYS if key in env}
    script = Path(__file__).resolve()
    inventory = _helper_json(image_id, script, "inventory", mounts,
                             {"mounts": mounts, "runtime_paths": runtime_paths})
    if not inventory.get("complete"):
        _fail("backup_scope_incomplete:" + str(inventory.get("reason") or "unknown"))
    semantic_snapshot = _runtime_snapshot(image_id, script, mounts, runtime_paths)
    if (not semantic_snapshot["database_present"]
            or semantic_snapshot["schema_version"] != inventory["schema_version"]
            or semantic_snapshot["archive_members"] != inventory["archive_members"]
            or semantic_snapshot["vault"] != inventory["vault"]):
        _fail("source_changed_during_semantic_inspection")
    output_dir = Path(args.output_dir).expanduser().absolute()
    _ensure_new_private_dir(output_dir)
    archive_path = output_dir / "state.tar.gz"
    manifest_path = output_dir / "manifest.json"
    created_archive = False
    try:
        with tempfile.TemporaryDirectory(prefix="steuerreport-archive-") as temp_dir:
            cidfile = Path(temp_dir) / "container.id"
            helper_run_id = "helper-" + uuid.uuid4().hex
            command = _helper_command(image_id, script, "archive", mounts, {"mounts": mounts},
                                      cidfile=cidfile, run_id=helper_run_id)
            with archive_path.open("xb") as target:
                os.chmod(archive_path, 0o600)
                created_archive = True
                try:
                    process = subprocess.Popen(["docker", *command], stdout=target, stderr=subprocess.DEVNULL)
                except FileNotFoundError:
                    _fail("docker_cli_not_found")
                try:
                    return_code = process.wait(timeout=3600)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=10)
                    if not _cleanup_helper_container(cidfile, helper_run_id):
                        _fail("backup_archive_timeout_cleanup_unconfirmed")
                    _fail("backup_archive_timeout")
        if return_code:
            _fail("docker_command_failed:run:" + str(return_code))
        records = _safe_archive_records(archive_path, mounts)
        if records != inventory["archive_members"]:
            _fail("source_changed_during_backup_or_archive_mismatch")
        manifest = {
            "format_version": FORMAT_VERSION,
            "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "application": "steuerreport-v2",
            "source_image": image,
            "source_container_stopped_confirmed": args.confirm_source_stopped,
            "schema_version": inventory["schema_version"],
            "database_table_count": len(semantic_snapshot["tables"]),
            "database_row_count": sum(row["rows"] for row in semantic_snapshot["tables"].values()),
            "database_present": inventory["database_present"],
            "database_tables": semantic_snapshot["tables"],
            "database_semantic_sha256": semantic_snapshot["database_semantic_sha256"],
            "wal_files": inventory["wal_files"],
            "runtime_paths": runtime_paths,
            "mounts": [{key: item[key] for key in ("id", "kind", "target", "read_only", "archive_prefix")}
                       for item in mounts],
            "archive_members": records,
            "archive_sha256": _sha256(archive_path),
            "archive_size_bytes": archive_path.stat().st_size,
            "configured_path_count_checked": inventory["configured_path_count_checked"],
            "external_paths_quiesced_confirmed": args.confirm_external_paths_quiesced,
            "vault": inventory["vault"],
            "secret_values_in_manifest": False,
        }
        _write_private_json(manifest_path, manifest)
    except Exception:
        if created_archive:
            archive_path.unlink(missing_ok=True)
        try:
            output_dir.rmdir()
        except OSError:
            pass
        raise
    return {
        "status": "backup_created",
        "backup_dir": str(output_dir),
        "image_version": image["version"],
        "image_revision": image["revision"],
        "schema_version": semantic_snapshot["schema_version"],
        "mount_count": len(mounts),
        "file_count": sum(row["type"] == "file" for row in records),
        "wal_file_count": len(inventory["wal_files"]),
        "archive_sha256": manifest["archive_sha256"],
    }


def verify(args: argparse.Namespace) -> dict:
    archive, manifest = _load_backup(
        Path(args.backup_dir).expanduser().absolute(),
        max_uncompressed_bytes=args.max_uncompressed_bytes,
        max_archive_bytes=args.max_archive_bytes,
        max_expanded_archive_bytes=args.max_expanded_archive_bytes,
    )
    return {
        "status": "verified",
        "image_version": manifest["source_image"]["version"],
        "image_revision": manifest["source_image"]["revision"],
        "schema_version": manifest["schema_version"],
        "mount_count": len(manifest["mounts"]),
        "file_count": sum(row["type"] == "file" for row in manifest["archive_members"]),
        "wal_file_count": len(manifest["wal_files"]),
        "archive_sha256": _sha256(archive),
    }


def _validated_run_id(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{3,40}", value):
        _fail("invalid_run_id")
    return value


def _validate_restore_size(manifest: dict, limit: int) -> int:
    if not isinstance(limit, int) or limit < 1:
        _fail("restore_size_limit_invalid")
    size = sum(row["size"] for row in manifest["archive_members"] if row["type"] == "file")
    if size > limit:
        _fail("restore_size_exceeds_operator_limit")
    if manifest["wal_files"]:
        _fail("restore_blocked_by_archived_wal")
    return size


def _new_restore_volumes(
    mounts: list[dict], run_id: str, created_volumes: list[str] | None = None
) -> tuple[list[str], list[dict]]:
    volumes = created_volumes if created_volumes is not None else []
    rows = []
    for index, mount in enumerate(mounts):
        volume_name = f"sr-restore-{run_id}-{index:03d}"
        if _inspect_optional("volume", volume_name) is not None:
            _fail("restore_volume_already_exists")
        _create_restore_volume(volume_name, run_id)
        volumes.append(volume_name)
        if _resource_state("volume", volume_name, run_id) != "owned":
            _fail("restore_volume_ownership_unverified")
        rows.append({**mount, "kind": "volume", "source": volume_name,
                     "helper_root": "/restore-target/" + mount["id"]})
    return volumes, rows


def _stage_backup_archive(archive: Path, manifest: dict, destination: Path, max_archive_bytes: int) -> Path:
    source_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        source_fd = os.open(archive, source_flags)
    except OSError:
        _fail("backup_archive_changed_after_verification")
    destination_fd = -1
    try:
        source_info = os.fstat(source_fd)
        if not stat.S_ISREG(source_info.st_mode) or source_info.st_size != manifest["archive_size_bytes"]:
            _fail("backup_archive_changed_after_verification")
        if source_info.st_size > max_archive_bytes:
            _fail("archive_size_exceeds_operator_limit")
        destination_fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        digest = hashlib.sha256()
        copied = 0
        with os.fdopen(source_fd, "rb") as source, os.fdopen(destination_fd, "wb") as output:
            source_fd = -1
            destination_fd = -1
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                copied += len(chunk)
                if copied > max_archive_bytes or copied > manifest["archive_size_bytes"]:
                    _fail("backup_archive_changed_after_verification")
                output.write(chunk)
                digest.update(chunk)
            output.flush()
            os.fsync(output.fileno())
        if copied != manifest["archive_size_bytes"] or digest.hexdigest() != manifest["archive_sha256"]:
            _fail("backup_archive_changed_after_verification")
        return destination
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        if source_fd >= 0:
            os.close(source_fd)
        if destination_fd >= 0:
            os.close(destination_fd)


def _extract_to_new_volumes(archive: Path, manifest: dict, image_id: str,
                            target_mounts: list[dict], *,
                            max_archive_bytes: int, max_restore_bytes: int,
                            max_expanded_archive_bytes: int, run_id: str) -> None:
    with tempfile.TemporaryDirectory(prefix="steuerreport-restore-") as temp_dir:
        temp = Path(temp_dir)
        staged_archive = _stage_backup_archive(archive, manifest, temp / "state.tar.gz", max_archive_bytes)
        manifest_copy = temp / "manifest.json"
        _write_private_json(manifest_copy, manifest)
        payload = {
            "targets": target_mounts,
            "manifest": "/backup/manifest.json",
            "archive": "/backup/state.tar.gz",
            "max_restore_bytes": max_restore_bytes,
            "max_expanded_archive_bytes": max_expanded_archive_bytes,
        }
        command = _helper_command(
            image_id, Path(__file__).resolve(), "extract", target_mounts, payload,
            cidfile=temp / "container.id", run_id=run_id,
            writable_ids={row["id"] for row in target_mounts},
            extra_mounts=[(staged_archive, "/backup/state.tar.gz"), (manifest_copy, "/backup/manifest.json")],
        )
        _run_helper_command(command, temp / "container.id", run_id=run_id, timeout=1800)


def _restored_snapshot(image_id: str, mounts: list[dict], volumes: list[str], runtime_paths: dict) -> dict:
    rows = [
        {**mount, "kind": "volume", "source": volumes[index],
         "helper_root": "/backup-input/" + mount["id"]}
        for index, mount in enumerate(mounts)
    ]
    return _runtime_snapshot(image_id, Path(__file__).resolve(), rows, runtime_paths)


def _immutable_image_reference(image: dict) -> str:
    candidates = [
        value for value in image.get("repo_digests", [])
        if isinstance(value, str) and re.fullmatch(r"[^@\s]+@sha256:[0-9a-f]{64}", value)
    ]
    if not candidates:
        _fail("restore_requires_immutable_repository_digest")
    return sorted(candidates)[0]


def _compose_override(image_reference: str, mounts: list[dict], volumes: list[str], runtime_paths: dict) -> str:
    lines = [
        "# Generated by scripts/docker_state_v2.py; review before applying.",
        "services:",
        "  steuerreport:",
        f"    image: {json.dumps(image_reference)}",
        "    pull_policy: never",
        "    volumes:",
    ]
    for index, mount in enumerate(mounts):
        source = f"restore_{index:03d}"
        lines.extend([
            "      - type: volume",
            f"        source: {source}",
            f"        target: {json.dumps(mount['target'])}",
            f"        read_only: {'true' if mount['read_only'] else 'false'}",
        ])
    if runtime_paths:
        lines.append("    environment:")
        for key, value in sorted(runtime_paths.items()):
            if key not in PATH_ENV_KEYS:
                _fail("backup_manifest_runtime_path_key_invalid")
            lines.append(f"      {key}: {json.dumps(value)}")
    lines.append("volumes:")
    for index, volume_name in enumerate(volumes):
        logical = f"restore_{index:03d}"
        lines.extend([
            f"  {logical}:",
            "    external: true",
            f"    name: {volume_name}",
        ])
    return "\n".join(lines) + "\n"


def restore(args: argparse.Namespace) -> dict:
    backup_dir = Path(args.backup_dir).expanduser().absolute()
    archive, manifest = _load_backup(
        backup_dir,
        max_uncompressed_bytes=args.max_restore_bytes,
        max_archive_bytes=args.max_archive_bytes,
        max_expanded_archive_bytes=args.max_expanded_archive_bytes,
    )
    run_id = _validated_run_id(args.run_id)
    uncompressed_size = _validate_restore_size(manifest, args.max_restore_bytes)
    image_id = args.image or manifest["source_image"]["image_id"]
    image = _image_info(image_id)
    if image["image_id"] != manifest["source_image"]["image_id"]:
        _fail("restore_image_id_mismatch")
    if image["revision"] != manifest["source_image"]["revision"] or image["version"] != manifest["source_image"]["version"]:
        _fail("restore_image_metadata_mismatch")
    image_reference = _immutable_image_reference(image)
    output_dir = Path(args.output_dir).expanduser().absolute()
    _ensure_new_private_dir(output_dir)
    mounts = manifest["mounts"]
    volumes = []
    succeeded = False
    try:
        _, target_mounts = _new_restore_volumes(mounts, run_id, volumes)
        _extract_to_new_volumes(
            archive, manifest, image_id, target_mounts,
            max_archive_bytes=args.max_archive_bytes,
            max_restore_bytes=args.max_restore_bytes,
            max_expanded_archive_bytes=args.max_expanded_archive_bytes,
            run_id=run_id,
        )
        snapshot = _restored_snapshot(image_id, mounts, volumes, manifest.get("runtime_paths", {}))
        if snapshot["archive_members"] != manifest["archive_members"]:
            _fail("restored_file_manifest_mismatch")
        if snapshot["schema_version"] != manifest["schema_version"]:
            _fail("restored_schema_version_mismatch")
        if (snapshot["tables"] != manifest["database_tables"]
                or snapshot["database_semantic_sha256"] != manifest["database_semantic_sha256"]):
            _fail("restored_database_semantic_mismatch")
        expected_rows = manifest.get("database_row_count")
        actual_rows = sum(row["rows"] for row in snapshot["tables"].values())
        if expected_rows is not None and actual_rows != expected_rows:
            _fail("restored_database_row_count_mismatch")
        if not snapshot["required_private_files_present"] or not snapshot["vault"]["decryptable"]:
            _fail("restored_private_state_or_vault_check_failed")
        override = _compose_override(image_reference, mounts, volumes, manifest.get("runtime_paths", {}))
        override_path = output_dir / "compose.restore.override.yml"
        override_descriptor = os.open(override_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(override_descriptor, "w", encoding="utf-8") as handle:
            handle.write(override)
        report = {
            "status": "restored_to_new_volumes_not_activated",
            "run_id": run_id,
            "image_id": image_id,
            "image_reference": image_reference,
            "image_version": image["version"],
            "image_revision": image["revision"],
            "schema_version": snapshot["schema_version"],
            "database_table_count": len(snapshot["tables"]),
            "database_row_count": actual_rows,
            "file_count": len(snapshot["archive_members"]),
            "wal_file_count": len(snapshot["wal_files"]),
            "vault_decryptable": snapshot["vault"]["decryptable"],
            "encrypted_secret_rows": snapshot["vault"]["encrypted_rows"],
            "volume_mounts": [
                {"container_target": mount["target"], "volume": volumes[index]}
                for index, mount in enumerate(mounts)
            ],
            "compose_override": str(override_path),
            "activation_performed": False,
            "network_started": False,
            "restore_size_bytes": uncompressed_size,
        }
        _write_private_json(output_dir / "restore.json", report)
        succeeded = True
        return report
    finally:
        if not succeeded:
            cleanup_failures = []
            for volume in reversed(volumes):
                failure = _cleanup_restore_resource("volume", volume, run_id)
                if failure:
                    cleanup_failures.append(failure)
            for child in output_dir.iterdir():
                if child.is_file() and not child.is_symlink():
                    child.unlink()
            try:
                output_dir.rmdir()
            except OSError:
                pass
            if cleanup_failures:
                _fail("restore_cleanup_incomplete:" + ",".join(cleanup_failures))


def _create_restore_volume(name: str, run_id: str) -> None:
    created_name = _docker(["volume", "create", "--label", RESOURCE_LABEL + "=" + run_id, name]).strip()
    if created_name != name:
        _fail("restore_volume_create_response_mismatch")


def _inspect_optional(kind: str, name: str) -> dict | None:
    try:
        completed = subprocess.run(["docker", kind, "inspect", name], capture_output=True, text=True, timeout=30)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        _fail("docker_inspect_failed:" + kind)
    except OSError as exc:
        _fail("docker_inspect_os_error:" + kind + ":" + str(exc.errno or "unknown"))
    if completed.returncode:
        message = completed.stderr.lower()
        if f"no such {kind}" in message:
            return None
        _fail("docker_inspect_failed:" + kind)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        _fail("docker_inspect_response_invalid")
    if not isinstance(payload, list) or len(payload) != 1 or not isinstance(payload[0], dict):
        _fail("docker_inspect_response_invalid")
    return payload[0]


def _resource_state(kind: str, name: str, run_id: str) -> str:
    obj = _inspect_optional(kind, name)
    if obj is None:
        return "missing"
    labels = obj.get("Labels", {}) if kind == "volume" else (obj.get("Config", {}).get("Labels") or {})
    return "owned" if (labels or {}).get(RESOURCE_LABEL) == run_id else "not_owned"


def _cleanup_restore_resource(kind: str, name: str, run_id: str) -> str | None:
    command = ["rm", "--force", name] if kind == "container" else ["volume", "rm", name]
    for attempt in range(RESTORE_CLEANUP_ATTEMPTS):
        try:
            state = _resource_state(kind, name, run_id)
        except OpsError as exc:
            if attempt + 1 < RESTORE_CLEANUP_ATTEMPTS:
                time.sleep(RESTORE_CLEANUP_DELAY_SECONDS)
                continue
            return f"{kind}_inspect_failed:{exc}"
        if state == "missing":
            return None
        if state != "owned":
            return f"{kind}_ownership_unverified"
        try:
            _docker(command)
        except OpsError:
            if attempt + 1 < RESTORE_CLEANUP_ATTEMPTS:
                time.sleep(RESTORE_CLEANUP_DELAY_SECONDS)
                continue
            try:
                if _resource_state(kind, name, run_id) == "missing":
                    return None
            except OpsError:
                pass
            return f"{kind}_remove_failed"
        try:
            state = _resource_state(kind, name, run_id)
        except OpsError as exc:
            return f"{kind}_inspect_failed:{exc}"
        if state == "missing":
            return None
        if state != "owned":
            return f"{kind}_ownership_unverified"
        if attempt + 1 < RESTORE_CLEANUP_ATTEMPTS:
            time.sleep(RESTORE_CLEANUP_DELAY_SECONDS)
    try:
        if _resource_state(kind, name, run_id) == "missing":
            return None
    except OpsError:
        pass
    return f"{kind}_remove_failed"


def _cleanup_restore_resources(container_name: str, created_container: bool,
                               volumes: list[str], run_id: str) -> list[str]:
    failures = []
    if created_container:
        failure = _cleanup_restore_resource("container", container_name, run_id)
        if failure:
            failures.append(failure)
    for volume in reversed(volumes):
        failure = _cleanup_restore_resource("volume", volume, run_id)
        if failure:
            failures.append(failure)
    return failures


def _runtime_snapshot(image_id: str, script: Path, mounts: list[dict], runtime_paths: dict) -> dict:
    return _helper_json(image_id, script, "snapshot", mounts, {"mounts": mounts, "runtime_paths": runtime_paths},
                        writable_ids=set())


def _summary_snapshot(snapshot: dict) -> dict:
    return {
        "database_present": snapshot["database_present"],
        "schema_version": snapshot["schema_version"],
        "table_count": len(snapshot["tables"]),
        "file_count": len(snapshot["archive_members"]),
        "wal_file_count": len(snapshot["wal_files"]),
        "required_private_files_present": snapshot["required_private_files_present"],
        "vault_decryptable": snapshot["vault"]["decryptable"],
        "encrypted_secret_rows": snapshot["vault"]["encrypted_rows"],
        "unreadable_secret_rows": snapshot["vault"]["unreadable_rows"],
    }


def _equal_after_start(before: dict, after: dict) -> bool:
    if before["tables"] != after["tables"]:
        return False
    db_files = set(before["database_archive_paths"])
    before_files = [row for row in before["archive_members"] if row["path"] not in db_files]
    after_files = [row for row in after["archive_members"] if row["path"] not in db_files]
    return (before_files == after_files and before["schema_version"] == after["schema_version"]
            and before["vault"] == after["vault"])


def _wait_health(container: str, version: str) -> dict:
    code = (
        "import json,urllib.request; d=json.load(urllib.request.urlopen("
        "'http://127.0.0.1:8010/api/v1/health',timeout=3))['data']; "
        "print(json.dumps({'version':d.get('app_version'),'database_type':d.get('database_type')}))"
    )
    for _ in range(45):
        result = subprocess.run(["docker", "exec", container, "python", "-c", code],
                                capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            try:
                payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                _fail("restore_health_response_invalid")
            if payload.get("version") != version or payload.get("database_type") != "duckdb":
                _fail("restore_health_version_or_database_mismatch")
            return payload
        info = _inspect("container", container)
        if info.get("State", {}).get("Status") in {"exited", "dead"}:
            _fail("restore_container_exited_before_health")
        time.sleep(1)
    _fail("restore_health_timeout")


def restore_check(args: argparse.Namespace) -> dict:
    archive, manifest = _load_backup(
        Path(args.backup_dir).expanduser().absolute(),
        max_uncompressed_bytes=args.max_restore_bytes,
        max_archive_bytes=args.max_archive_bytes,
        max_expanded_archive_bytes=args.max_expanded_archive_bytes,
    )
    run_id = _validated_run_id(args.run_id)
    _validate_restore_size(manifest, args.max_restore_bytes)
    image_id = args.image or manifest["source_image"]["image_id"]
    image = _image_info(image_id)
    if image["image_id"] != manifest["source_image"]["image_id"]:
        _fail("restore_image_id_mismatch")
    if image["revision"] != manifest["source_image"]["revision"] or image["version"] != manifest["source_image"]["version"]:
        _fail("restore_image_metadata_mismatch")
    evidence = Path(args.evidence_dir).expanduser().absolute()
    _ensure_new_private_dir(evidence)
    if not isinstance(args.max_restore_bytes, int) or args.max_restore_bytes < 1:
        _fail("restore_size_limit_invalid")
    uncompressed_size = sum(row["size"] for row in manifest["archive_members"] if row["type"] == "file")
    if uncompressed_size > args.max_restore_bytes:
        _fail("restore_size_exceeds_operator_limit")
    mounts = manifest["mounts"]
    volumes = []
    names = []
    container_name = "sr-restore-" + run_id
    created_container = False
    result = {"status": "failed", "run_id": run_id, "image_id": image_id,
              "revision": image["revision"], "version": image["version"],
              "network": "none", "published_ports": False, "cleanup": False,
              "cleanup_failures": []}
    operation_error = None
    try:
        for index, mount in enumerate(mounts):
            volume_name = f"sr-restore-{run_id}-{index:03d}"
            if _inspect_optional("volume", volume_name) is not None:
                _fail("restore_volume_already_exists")
            _create_restore_volume(volume_name, run_id)
            volumes.append(volume_name)
            if _resource_state("volume", volume_name, run_id) != "owned":
                _fail("restore_volume_ownership_unverified")
            names.append({**mount, "source": volume_name,
                          "helper_root": "/restore-target/" + mount["id"]})
        with tempfile.TemporaryDirectory(prefix="steuerreport-restore-") as temp_dir:
            temp = Path(temp_dir)
            manifest_copy = temp / "manifest.json"
            staged_archive = _stage_backup_archive(
                archive, manifest, temp / "state.tar.gz", args.max_archive_bytes
            )
            _write_private_json(manifest_copy, manifest)
            helper_mounts = [{**row, "source": row["source"], "helper_root": "/restore-target/" + row["id"]}
                             for row in names]
            payload = {
                "targets": helper_mounts,
                "manifest": "/backup/manifest.json",
                "archive": "/backup/state.tar.gz",
                "max_restore_bytes": args.max_restore_bytes,
                "max_expanded_archive_bytes": args.max_expanded_archive_bytes,
            }
            command = _helper_command(image_id, Path(__file__).resolve(), "extract", helper_mounts,
                                      payload, cidfile=temp / "container.id", run_id=run_id,
                                      writable_ids={row["id"] for row in helper_mounts},
                                      extra_mounts=[(staged_archive, "/backup/state.tar.gz"),
                                                    (manifest_copy, "/backup/manifest.json")])
            _run_helper_command(command, temp / "container.id", run_id=run_id, timeout=1800)
        restored_mounts = [{**mount, "kind": "volume", "source": volumes[index],
                            "helper_root": "/backup-input/" + mount["id"]}
                           for index, mount in enumerate(mounts)]
        runtime_paths = manifest.get("runtime_paths", {})
        before = _runtime_snapshot(image_id, Path(__file__).resolve(), restored_mounts, runtime_paths)
        if not before["required_private_files_present"] or not before["vault"]["decryptable"]:
            _fail("restored_private_state_or_vault_check_failed")
        if (before["schema_version"] != manifest["schema_version"]
                or before["tables"] != manifest["database_tables"]
                or before["database_semantic_sha256"] != manifest["database_semantic_sha256"]):
            _fail("restored_database_semantic_mismatch")
        result["restored_before_start"] = _summary_snapshot(before)
        env_args = []
        for key, value in manifest.get("runtime_paths", {}).items():
            if key not in PATH_ENV_KEYS:
                _fail("backup_manifest_runtime_path_key_invalid")
            env_args.extend(["--env", key + "=" + value])
        create = [
            "create", "--pull=never", "--name", container_name,
            "--label", RESOURCE_LABEL + "=" + run_id,
            "--network", "none", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true", "--no-healthcheck",
            "--restart", "no", "--cpus", "1", "--memory", "1g",
            "--memory-swap", "1g", "--pids-limit", "128",
            "--tmpfs", "/tmp:size=256m,mode=1777",
        ]
        for index, row in enumerate(mounts):
            readonly = ",readonly" if row["read_only"] else ""
            create.extend(["--mount", f"type=volume,src={volumes[index]},dst={row['target']}{readonly}"])
        create.extend(env_args)
        create.append(image_id)
        _docker(create, timeout=120)
        created_container = True
        inspected = _inspect("container", container_name)
        if _resource_state("container", container_name, run_id) != "owned":
            _fail("restore_container_ownership_unverified")
        if inspected.get("HostConfig", {}).get("NetworkMode") != "none" or inspected.get("HostConfig", {}).get("PortBindings"):
            _fail("restore_container_isolation_failed")
        if not inspected.get("HostConfig", {}).get("ReadonlyRootfs"):
            _fail("restore_container_root_not_readonly")
        actual_mounts = inspected.get("Mounts") or []
        if {item.get("Name") for item in actual_mounts if item.get("Type") == "volume"} != set(volumes):
            _fail("restore_container_mount_mismatch")
        actual_modes = {
            item.get("Destination"): item.get("RW")
            for item in actual_mounts if item.get("Type") == "volume"
        }
        expected_modes = {row["target"]: not row["read_only"] for row in mounts}
        if actual_modes != expected_modes:
            _fail("restore_container_mount_access_mode_mismatch")
        _docker(["start", container_name], timeout=120)
        result["first_start"] = _wait_health(container_name, image["version"])
        _docker(["stop", "--time", "20", container_name], timeout=60)
        first = _runtime_snapshot(image_id, Path(__file__).resolve(), restored_mounts, runtime_paths)
        result["after_first_start"] = _summary_snapshot(first)
        result["first_start_preserved"] = _equal_after_start(before, first)
        if not result["first_start_preserved"]:
            _fail("restore_data_changed_on_first_start")
        _docker(["start", container_name], timeout=120)
        result["restart"] = _wait_health(container_name, image["version"])
        _docker(["stop", "--time", "20", container_name], timeout=60)
        second = _runtime_snapshot(image_id, Path(__file__).resolve(), restored_mounts, runtime_paths)
        result["after_restart"] = _summary_snapshot(second)
        result["restart_preserved"] = _equal_after_start(before, second)
        if not result["restart_preserved"]:
            _fail("restore_data_changed_on_restart")
        result["status"] = "passed"
    except Exception as exc:
        result["error"] = exc.args[0] if isinstance(exc, OpsError) and exc.args else "restore_check_failed"
        operation_error = exc
    finally:
        result["cleanup_failures"] = _cleanup_restore_resources(
            container_name, created_container, volumes, run_id
        )
        result["cleanup"] = not result["cleanup_failures"]
        if not result["cleanup"] and result["status"] == "passed":
            result["status"] = "cleanup_incomplete"
            result["error"] = "restore_check_cleanup_incomplete"
        _write_private_json(evidence / "restore-check.json", result)
    if operation_error is not None:
        raise operation_error
    if not result["cleanup"]:
        _fail("restore_check_cleanup_incomplete")
    return {key: value for key, value in result.items() if key not in {"error"}}


def _helper_mount_path(mounts: list[dict], container_path: str) -> Path:
    if not isinstance(container_path, str) or not container_path.startswith("/"):
        _fail("configured_path_must_be_absolute")
    normalized = posixpath.normpath(container_path)
    choices = [row for row in mounts if normalized == row["target"] or normalized.startswith(row["target"].rstrip("/") + "/")]
    if not choices:
        _fail("configured_path_outside_persistent_mounts")
    row = max(choices, key=lambda item: len(item["target"]))
    relative = posixpath.relpath(normalized, row["target"])
    root = Path(row["helper_root"])
    path = root if relative == "." else root.joinpath(*PurePosixPath(relative).parts)
    return path


def _file_sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _db_connection(path: Path):
    import duckdb
    return duckdb.connect(str(path), read_only=True,
                          config={"temp_directory": "/tmp", "memory_limit": "512MB"})


def _db_schema_summary(path: Path) -> tuple[int, dict]:
    try:
        connection = _db_connection(path)
        try:
            connection.execute("BEGIN TRANSACTION")
            row = connection.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
            if row is None:
                _fail("database_schema_version_missing")
            schema_version = int(row[0])
            tables = connection.execute(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_type='BASE TABLE' AND table_schema NOT IN "
                "('information_schema','pg_catalog') ORDER BY 1,2"
            ).fetchall()
            result = {}
            for schema, name in tables:
                quoted = ".".join('"' + value.replace('"', '""') + '"' for value in (schema, name))
                count = connection.execute("SELECT COUNT(*) FROM " + quoted).fetchone()[0]
                result[schema + "." + name] = {"rows": int(count)}
            connection.execute("COMMIT")
            return schema_version, result
        finally:
            connection.close()
    except OpsError:
        raise
    except Exception:
        _fail("database_read_only_inspection_failed")


def _db_semantics(path: Path) -> tuple[int, dict]:
    try:
        connection = _db_connection(path)
        try:
            connection.execute("BEGIN TRANSACTION")
            row = connection.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
            if row is None:
                _fail("database_schema_version_missing")
            schema_version = int(row[0])
            rows = connection.execute(
                "SELECT table_schema, table_name FROM information_schema.tables "
                "WHERE table_type='BASE TABLE' AND table_schema NOT IN "
                "('information_schema','pg_catalog') ORDER BY 1,2"
            ).fetchall()
            result = {}
            for schema, name in rows:
                quoted = ".".join('"' + value.replace('"', '""') + '"' for value in (schema, name))
                cursor = connection.execute("SELECT * FROM " + quoted)
                description = [(item[0], str(item[1])) for item in cursor.description]
                columns = [item[0] for item in cursor.description]
                if not columns:
                    _fail("database_table_without_columns")
                order_by = ", ".join('"' + column.replace('"', '""') + '"' for column in columns)
                cursor = connection.execute("SELECT * FROM " + quoted + " ORDER BY " + order_by)
                digest = hashlib.sha256(_json_bytes(description))
                row_count = 0
                while batch := cursor.fetchmany(2048):
                    for record in batch:
                        digest.update(hashlib.sha256(_json_bytes(record)).digest())
                        row_count += 1
                result[schema + "." + name] = {"rows": row_count, "sha256": digest.hexdigest()}
            connection.execute("COMMIT")
            return schema_version, result
        finally:
            connection.close()
    except OpsError:
        raise
    except Exception:
        _fail("database_semantic_snapshot_failed")


def _vault_summary(path: Path, key_path: Path) -> dict:
    try:
        import duckdb
        from steuerreport_v2.domain.secret_vault import (
            decode_secret_setting,
            is_encrypted_envelope,
            load_vault_key,
        )
        env_key = "STEUERREPORT_V2_SECRET_VAULT_KEY_FILE"
        previous_key_path = os.environ.get(env_key)
        os.environ[env_key] = str(key_path)
        try:
            key = load_vault_key()
            connection = duckdb.connect(str(path), read_only=True)
            try:
                rows = connection.execute(
                    "SELECT key, value_json FROM admin_settings WHERE lower(key) LIKE 'secret.%' ORDER BY key"
                ).fetchall()
            finally:
                connection.close()
            unreadable = 0
            encrypted = 0
            for key_name, value in rows:
                if is_encrypted_envelope(value):
                    encrypted += 1
                try:
                    decode_secret_setting(key_name, value)
                except (RuntimeError, ValueError, UnicodeError):
                    unreadable += 1
            return {
                "key_readable": key is not None,
                "secret_rows": len(rows),
                "encrypted_rows": encrypted,
                "unreadable_rows": unreadable,
                "decryptable": key is not None and unreadable == 0,
            }
        finally:
            if previous_key_path is None:
                os.environ.pop(env_key, None)
            else:
                os.environ[env_key] = previous_key_path
    except OpsError:
        raise
    except Exception:
        _fail("secret_vault_read_only_check_failed")


def _helper_inventory(payload: dict, *, semantic: bool) -> dict:
    mounts = payload["mounts"]
    runtime_paths = payload.get("runtime_paths", {})
    mapped = {}
    for key, value in runtime_paths.items():
        if key not in PATH_ENV_KEYS or not isinstance(value, str):
            _fail("backup_manifest_runtime_path_key_invalid")
        mapped[key] = str(_helper_mount_path(mounts, value)) if value else ""
    previous = {key: os.environ.get(key) for key in mapped}
    try:
        for key, value in mapped.items():
            os.environ[key] = value
        return _helper_inventory_mapped(payload, semantic=semantic)
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _helper_inventory_mapped(payload: dict, *, semantic: bool) -> dict:
    mounts = payload["mounts"]
    runtime_paths = payload.get("runtime_paths", {})
    all_files = []
    database_paths = []
    wal_files = []
    for mount in mounts:
        root = Path(mount["helper_root"])
        if not root.is_dir() or root.is_symlink():
            _fail("persistent_mount_root_invalid")
        for current, directories, filenames in os.walk(root, followlinks=False):
            current_path = Path(current)
            for name in list(directories):
                child = current_path / name
                if child.is_symlink() or not child.is_dir():
                    _fail("persistent_mount_contains_link_or_special_file")
                rel = child.relative_to(root).as_posix()
                all_files.append(_record(child, mount, rel, is_directory=True))
            for name in filenames:
                child = current_path / name
                info = child.lstat()
                if not stat.S_ISREG(info.st_mode):
                    _fail("persistent_mount_contains_link_or_special_file")
                rel = child.relative_to(root).as_posix()
                row = _record(child, mount, rel)
                all_files.append(row)
                if name.endswith(".wal"):
                    wal_files.append(row["path"])
        all_files.append(_record(root, mount, "", is_directory=True))
    all_files.sort(key=lambda item: item["path"])
    database = runtime_paths.get("STEUERREPORT_V2_DB", "/state/data/steuerreport_v2.duckdb")
    db_host = _helper_mount_path(mounts, database)
    if db_host.exists():
        database_paths.append((database, db_host))
    if len(database_paths) > 1:
        _fail("multiple_database_paths_resolved")
    database_present = bool(database_paths)
    schema_version = None
    tables = {}
    database_semantic_sha256 = None
    vault = None
    db_archive_paths = []
    if database_present:
        db_path, db_host = database_paths[0]
        if not db_host.is_file() or db_host.is_symlink():
            _fail("database_path_not_regular_file")
        db_mount = max(
            (row for row in mounts if db_path == row["target"] or db_path.startswith(row["target"].rstrip("/") + "/")),
            key=lambda row: len(row["target"]),
        )
        rel = posixpath.relpath(db_path, db_mount["target"])
        db_archive_paths.append(db_mount["archive_prefix"] + "/" + rel)
        if semantic:
            schema_version, tables = _db_semantics(db_host)
            database_semantic_sha256 = hashlib.sha256(_json_bytes(tables)).hexdigest()
        else:
            schema_version, tables = _db_schema_summary(db_host)
        vault_key_for_check = runtime_paths.get(
            "STEUERREPORT_V2_SECRET_VAULT_KEY_FILE",
            posixpath.join(runtime_paths.get("STEUERREPORT_STATE_DIR", "/state"), "keys/vault.key"),
        )
        vault = _vault_summary(db_host, _helper_mount_path(mounts, vault_key_for_check))
    if semantic and not database_present:
        _fail("database_missing_for_restore_check")
    profile = runtime_paths.get("STEUERREPORT_PRIVATE_PROFILE", "/state/private_profile.json")
    state_root = runtime_paths.get("STEUERREPORT_STATE_DIR", "/state")
    config_dir = runtime_paths.get("STEUERREPORT_PRIVATE_CONFIG_DIR", posixpath.join(state_root, "configs"))
    vault_key = runtime_paths.get("STEUERREPORT_V2_SECRET_VAULT_KEY_FILE", posixpath.join(state_root, "keys/vault.key"))
    connector_token = runtime_paths.get(
        "STEUERREPORT_V2_CONNECTOR_SETUP_TOKEN_FILE",
        posixpath.join(state_root, "keys/connector-setup.token"),
    )
    required_paths = [profile, vault_key]
    if connector_token:
        required_paths.append(connector_token)
    if semantic:
        required_private_files_present = all(_helper_mount_path(mounts, path).is_file() for path in required_paths)
    else:
        required_private_files_present = None
    if not semantic:
        if not database_present:
            _fail("database_missing_from_persistent_mounts")
        profile_path = _helper_mount_path(mounts, profile)
        if not profile_path.is_file():
            _fail("private_profile_missing_from_persistent_mounts")
        try:
            profile_data = json.loads(profile_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            _fail("private_profile_unreadable")
        if not isinstance(profile_data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in profile_data.items()):
            _fail("private_profile_schema_invalid")
        if not all(_helper_mount_path(mounts, path).is_file() for path in required_paths):
            _fail("required_private_file_missing")
        for private_path in required_paths:
            mode = stat.S_IMODE(_helper_mount_path(mounts, private_path).stat().st_mode)
            if mode & 0o077:
                _fail("private_file_permissions_too_broad")
        for value in runtime_paths.values():
            if value:
                _helper_mount_path(mounts, value)
        for value in (config_dir, vault_key, database, runtime_paths.get("STEUERREPORT_USERTRANSFER_ROOT", posixpath.join(state_root, "imports"))):
            _helper_mount_path(mounts, value)
        if connector_token:
            _helper_mount_path(mounts, connector_token)
        configured_path_count = 0
        path_key = re.compile(r"(?:path|file|root|dir)$", re.I)
        for key, value in profile_data.items():
            if path_key.search(key) and value.startswith("/") and "://" not in value:
                _helper_mount_path(mounts, value)
                configured_path_count += 1
        if wal_files:
            # WALs are included in the archive and reported; DuckDB read-only
            # metadata below verifies whether this stopped snapshot is readable.
            pass
    else:
        configured_path_count = 0
    if not semantic and (vault is None or not vault["decryptable"]):
        _fail("secret_vault_decryption_check_failed")
    return {
        "complete": True,
        "archive_members": all_files,
        "database_present": database_present,
        "schema_version": schema_version,
        "tables": tables,
        "database_semantic_sha256": database_semantic_sha256,
        "vault": vault,
        "database_archive_paths": db_archive_paths,
        "wal_files": wal_files,
        "required_private_files_present": required_private_files_present,
        "configured_path_count_checked": configured_path_count,
    }


def _record(path: Path, mount: dict, relative: str, *, is_directory: bool = False) -> dict:
    info = path.stat(follow_symlinks=False)
    record = {
        "path": mount["archive_prefix"] + ("/" + relative if relative else ""),
        "type": "directory" if is_directory else "file",
        "uid": info.st_uid,
        "gid": info.st_gid,
        "mode": stat.S_IMODE(info.st_mode),
        "size": 0 if is_directory else info.st_size,
    }
    if not is_directory:
        record["sha256"] = _file_sha(path)
    return record


def _helper_archive(payload: dict) -> None:
    mounts = payload["mounts"]
    with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz", format=tarfile.PAX_FORMAT) as archive:
        for mount in mounts:
            root = Path(mount["helper_root"])
            if not root.is_dir() or root.is_symlink():
                _fail("persistent_mount_root_invalid")
            paths = [root]
            for current, dirs, files in os.walk(root, followlinks=False):
                current_path = Path(current)
                for name in sorted(dirs + files):
                    path = current_path / name
                    info = path.lstat()
                    if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                        _fail("persistent_mount_contains_link_or_special_file")
                    paths.append(path)
            paths.sort(key=lambda path: "" if path == root else path.relative_to(root).as_posix())
            for path in paths:
                relative = path.relative_to(root).as_posix()
                arcname = mount["archive_prefix"] if relative == "." else mount["archive_prefix"] + "/" + relative
                archive.add(path, arcname=arcname, recursive=False)


def _helper_extract(payload: dict) -> dict:
    archive_path = Path(payload["archive"])
    manifest_path = Path(payload["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    targets = payload["targets"]
    records = _safe_archive_records(
        archive_path,
        targets,
        max_uncompressed_bytes=payload.get("max_restore_bytes"),
        max_expanded_archive_bytes=payload.get("max_expanded_archive_bytes"),
    )
    if records != manifest.get("archive_members"):
        _fail("backup_member_manifest_mismatch")
    roots = {row["archive_prefix"]: Path(row["helper_root"]) for row in targets}
    expected_mounts = set(roots)
    hashes = {row["path"]: row.get("sha256") for row in manifest["archive_members"]}
    extracted = set()
    max_restore_bytes = payload["max_restore_bytes"]
    max_expanded_archive_bytes = payload["max_expanded_archive_bytes"]
    written_total = 0
    with archive_path.open("rb") as compressed:
        with gzip.GzipFile(fileobj=compressed, mode="rb") as expanded:
            capped = _CappedReader(expanded, max_expanded_archive_bytes)
            with tarfile.open(fileobj=capped, mode="r|") as archive:
                for member in archive:
                    if len(extracted) >= MAX_ARCHIVE_MEMBERS:
                        _fail("archive_member_count_exceeds_limit")
                    if member.issym() or member.islnk() or member.isdev() or not (member.isdir() or member.isreg()):
                        _fail("archive_member_type_unsupported")
                    if member.size < 0:
                        _fail("archive_member_size_invalid")
                    if member.isreg():
                        written_total += member.size
                        if written_total > max_restore_bytes:
                            _fail("restore_size_exceeds_operator_limit")
                    path = PurePosixPath(member.name)
                    if path.is_absolute() or ".." in path.parts:
                        _fail("archive_member_path_invalid")
                    prefix = next((item for item in expected_mounts
                                   if member.name == item or member.name.startswith(item + "/")), None)
                    if prefix is None:
                        _fail("archive_contains_unlisted_mount_path")
                    root = roots[prefix]
                    relative = path.relative_to(PurePosixPath(prefix))
                    destination = root.joinpath(*relative.parts) if relative.parts else root
                    if not destination.resolve().is_relative_to(root.resolve()):
                        _fail("archive_member_path_invalid")
                    if member.isdir():
                        destination.mkdir(parents=True, exist_ok=True)
                        os.chown(destination, member.uid, member.gid)
                        os.chmod(destination, stat.S_IMODE(member.mode))
                    else:
                        if destination.exists():
                            _fail("restore_destination_not_empty")
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        source = archive.extractfile(member)
                        if source is None:
                            _fail("archive_member_unreadable")
                        digest = hashlib.sha256()
                        copied = 0
                        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                        with source, os.fdopen(descriptor, "wb") as output:
                            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                                copied += len(chunk)
                                if copied > member.size or copied > max_restore_bytes:
                                    _fail("archive_member_size_invalid")
                                output.write(chunk)
                                digest.update(chunk)
                        if copied != member.size:
                            _fail("archive_member_size_invalid")
                        if digest.hexdigest() != hashes.get(member.name):
                            _fail("restored_file_hash_mismatch")
                        os.chown(destination, member.uid, member.gid)
                        os.chmod(destination, stat.S_IMODE(member.mode))
                    extracted.add(member.name)
                while capped.read(1024 * 1024):
                    pass
    if extracted != {row["path"] for row in manifest["archive_members"]}:
        _fail("restore_archive_member_set_mismatch")
    return {"status": "extracted", "member_count": len(extracted)}


def _helper_main(mode: str, encoded: str) -> None:
    try:
        payload = json.loads(encoded)
        if mode == "inventory":
            result = _helper_inventory(payload, semantic=False)
        elif mode == "snapshot":
            result = _helper_inventory(payload, semantic=True)
        elif mode == "archive":
            _helper_archive(payload)
            return
        elif mode == "extract":
            result = _helper_extract(payload)
        else:
            _fail("unknown_helper_mode")
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    except OpsError as exc:
        print(json.dumps({"error": str(exc)}, separators=(",", ":")))
        raise SystemExit(2)


def main() -> None:
    if len(sys.argv) >= 4 and sys.argv[1] == "_helper":
        _helper_main(sys.argv[2], sys.argv[3])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    make_backup = subparsers.add_parser("backup", help="Sichert einen gestoppten Docker-Datenstand")
    make_backup.add_argument("--container", required=True)
    make_backup.add_argument("--output-dir", type=Path, required=True)
    make_backup.add_argument("--confirm-source-stopped", action="store_true", required=True)
    make_backup.add_argument("--confirm-external-paths-quiesced", action="store_true")
    verify_parser = subparsers.add_parser("verify", help="Prueft Manifest, Archivhash und alle Mitglieder")
    verify_parser.add_argument("--backup-dir", type=Path, required=True)
    verify_parser.add_argument("--max-uncompressed-bytes", type=int, required=True)
    verify_parser.add_argument("--max-archive-bytes", type=int, required=True)
    verify_parser.add_argument("--max-expanded-archive-bytes", type=int, required=True)
    restore_parser = subparsers.add_parser("restore-check", help="Prueft Restore/Neustart offline in neuen Volumes")
    restore_parser.add_argument("--backup-dir", type=Path, required=True)
    restore_parser.add_argument("--evidence-dir", type=Path, required=True)
    restore_parser.add_argument("--run-id", required=True)
    restore_parser.add_argument("--image", help="Lokales Image; muss exakt zum Backupmanifest passen")
    restore_parser.add_argument("--max-restore-bytes", type=int, required=True,
                                help="Maximale expandierte Backupgroesse fuer neue Testvolumes")
    restore_parser.add_argument("--max-archive-bytes", type=int, required=True,
                                help="Maximale komprimierte Archivgroesse vor dem Lesen")
    restore_parser.add_argument("--max-expanded-archive-bytes", type=int, required=True,
                                help="Maximale expandierte Tar-Gesamtgroesse einschliesslich Headern")
    recover_parser = subparsers.add_parser("restore", help="Stellt in neue Docker-Volumes wieder her, ohne sie zu aktivieren")
    recover_parser.add_argument("--backup-dir", type=Path, required=True)
    recover_parser.add_argument("--output-dir", type=Path, required=True)
    recover_parser.add_argument("--run-id", required=True)
    recover_parser.add_argument("--max-restore-bytes", type=int, required=True,
                                help="Maximale expandierte Backupgroesse fuer neue Volumes")
    recover_parser.add_argument("--max-archive-bytes", type=int, required=True,
                                help="Maximale komprimierte Archivgroesse vor dem Lesen")
    recover_parser.add_argument("--max-expanded-archive-bytes", type=int, required=True,
                                help="Maximale expandierte Tar-Gesamtgroesse einschliesslich Headern")
    recover_parser.add_argument("--image", help="Lokales Image; muss exakt zum Backupmanifest passen")
    args = parser.parse_args()
    try:
        if args.action == "backup":
            result = backup(args)
        elif args.action == "verify":
            result = verify(args)
        elif args.action == "restore-check":
            result = restore_check(args)
        else:
            result = restore(args)
        print(json.dumps(result, indent=2, sort_keys=True))
    except OpsError as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, indent=2, sort_keys=True), file=sys.stderr)
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
