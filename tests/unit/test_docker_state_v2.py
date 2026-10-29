from __future__ import annotations

from contextlib import contextmanager
import hashlib
import gzip
import importlib.util
import io
import json
from pathlib import Path
import stat
import tarfile

import duckdb
import pytest
from steuerreport_v2.domain.secret_vault import encrypt_secret_setting

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "docker_state_v2.py"
_SPEC = importlib.util.spec_from_file_location("docker_state_v2", _SCRIPT)
assert _SPEC and _SPEC.loader
ops = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ops)


def _fixture_state(root: Path) -> tuple[list[dict], dict, Path]:
    state = root / "state"
    for name in ("data", "keys", "imports", "configs"):
        (state / name).mkdir(parents=True, exist_ok=True)
    database = state / "data" / "steuerreport_v2.duckdb"
    key_file = state / "keys" / "vault.key"
    key = bytes(range(32))
    key_file.write_bytes(key)
    key_file.chmod(0o600)
    token = state / "keys" / "connector-setup.token"
    token.write_text("synthetic-setup-token\n", encoding="ascii")
    token.chmod(0o600)
    profile = state / "private_profile.json"
    profile.write_text(json.dumps({"import_root": "/fixture/state/imports"}) + "\n", encoding="utf-8")
    profile.chmod(0o600)

    connection = duckdb.connect(str(database))
    connection.execute("CREATE TABLE schema_meta (key VARCHAR PRIMARY KEY, value VARCHAR NOT NULL)")
    connection.execute("INSERT INTO schema_meta VALUES ('schema_version', '1')")
    connection.execute("CREATE TABLE admin_settings (key VARCHAR PRIMARY KEY, value_json VARCHAR NOT NULL)")
    connection.execute(
        "INSERT INTO admin_settings VALUES (?, ?)",
        ["secret.cex.synthetic.api_key", encrypt_secret_setting("secret.cex.synthetic.api_key", "NOT-A-REAL-SECRET", key)],
    )
    connection.execute("CREATE TABLE canonical_events (event_id VARCHAR, amount DECIMAL(18, 8))")
    connection.execute("INSERT INTO canonical_events VALUES ('synthetic-1', 1.25), ('synthetic-2', 0.50)")
    connection.close()
    (state / "unrelated.wal").write_bytes(b"synthetic wal fixture")

    mount = {
        "id": "m000",
        "kind": "volume",
        "target": "/fixture/state",
        "read_only": False,
        "source": "fixture-volume",
        "archive_prefix": "mounts/m000",
        "helper_root": str(state),
    }
    runtime_paths = {
        "STEUERREPORT_STATE_DIR": "/fixture/state",
        "STEUERREPORT_V2_DB": "/fixture/state/data/steuerreport_v2.duckdb",
        "STEUERREPORT_USERTRANSFER_ROOT": "/fixture/state/imports",
        "STEUERREPORT_PRIVATE_PROFILE": "/fixture/state/private_profile.json",
        "STEUERREPORT_PRIVATE_CONFIG_DIR": "/fixture/state/configs",
        "STEUERREPORT_V2_SECRET_VAULT_KEY_FILE": "/fixture/state/keys/vault.key",
        "STEUERREPORT_V2_CONNECTOR_SETUP_TOKEN_FILE": "/fixture/state/keys/connector-setup.token",
    }
    return [mount], runtime_paths, state


class _BinaryStdout:
    def __init__(self) -> None:
        self.buffer = io.BytesIO()


@contextmanager
def _redirect_binary_stdout(target):
    previous = ops.sys.stdout
    ops.sys.stdout = target
    try:
        yield
    finally:
        ops.sys.stdout = previous


def _write_test_archive(path: Path, mounts: list[dict]) -> list[dict]:
    stdout = _BinaryStdout()
    with _redirect_binary_stdout(stdout):
        ops._helper_archive({"mounts": mounts})
    path.write_bytes(stdout.buffer.getvalue())
    path.chmod(0o600)
    return ops._safe_archive_records(path, mounts)


def test_inventory_checks_private_paths_and_secret_decryption(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mounts, runtime_paths, state = _fixture_state(tmp_path)
    monkeypatch.setenv("STEUERREPORT_V2_SECRET_VAULT_KEY_FILE", str(state / "keys" / "vault.key"))

    result = ops._helper_inventory({"mounts": mounts, "runtime_paths": runtime_paths}, semantic=False)

    assert result["complete"] is True
    assert result["schema_version"] == 1
    assert result["tables"]["main.canonical_events"]["rows"] == 2
    assert result["vault"] == {
        "key_readable": True,
        "secret_rows": 1,
        "encrypted_rows": 1,
        "unreadable_rows": 0,
        "decryptable": True,
    }
    assert result["wal_files"] == ["mounts/m000/unrelated.wal"]
    assert all("NOT-A-REAL-SECRET" not in json.dumps(row) for row in result["archive_members"])


def test_vault_summary_restores_previous_key_path_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, _, state = _fixture_state(tmp_path)
    previous_path = "/previous/profile/vault.key"
    monkeypatch.setenv("STEUERREPORT_V2_SECRET_VAULT_KEY_FILE", previous_path)

    result = ops._vault_summary(
        state / "data" / "steuerreport_v2.duckdb",
        state / "keys" / "vault.key",
    )

    assert result["decryptable"] is True
    assert ops.os.environ["STEUERREPORT_V2_SECRET_VAULT_KEY_FILE"] == previous_path


def test_unmounted_configured_path_blocks_full_backup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mounts, runtime_paths, state = _fixture_state(tmp_path)
    monkeypatch.setenv("STEUERREPORT_V2_SECRET_VAULT_KEY_FILE", str(state / "keys" / "vault.key"))
    profile = state / "private_profile.json"
    profile.write_text(json.dumps({"import_root": "/outside/imports"}) + "\n", encoding="utf-8")
    profile.chmod(0o600)

    with pytest.raises(ops.OpsError, match="configured_path_outside_persistent_mounts"):
        ops._helper_inventory({"mounts": mounts, "runtime_paths": runtime_paths}, semantic=False)


def test_missing_original_vault_key_blocks_instead_of_generating_one(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    mounts, runtime_paths, state = _fixture_state(tmp_path)
    (state / "keys" / "vault.key").unlink()
    monkeypatch.setenv("STEUERREPORT_V2_SECRET_VAULT_KEY_FILE", str(state / "keys" / "vault.key"))

    with pytest.raises(ops.OpsError, match="required_private_file_missing"):
        ops._helper_inventory({"mounts": mounts, "runtime_paths": runtime_paths}, semantic=False)

    assert not (state / "keys" / "vault.key").exists()


def test_archive_and_restore_preserve_wal_hash_and_private_modes(tmp_path: Path) -> None:
    mounts, _, state = _fixture_state(tmp_path)
    archive_path = tmp_path / "state.tar.gz"
    records = _write_test_archive(archive_path, mounts)
    target = tmp_path / "restored"
    target.mkdir(mode=0o700)
    target_mounts = [{**mounts[0], "helper_root": str(target)}]
    manifest = {"archive_members": records, "mounts": [{key: mounts[0][key] for key in ("id", "kind", "target", "archive_prefix")} ]}
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = ops._helper_extract({
        "targets": target_mounts,
        "archive": str(archive_path),
        "manifest": str(manifest_path),
        "max_restore_bytes": 64 * 1024 * 1024,
        "max_expanded_archive_bytes": 128 * 1024 * 1024,
    })

    assert result == {"status": "extracted", "member_count": len(records)}
    assert (target / "unrelated.wal").read_bytes() == b"synthetic wal fixture"
    assert stat.S_IMODE((target / "keys" / "vault.key").stat().st_mode) == 0o600
    assert hashlib.sha256((target / "data" / "steuerreport_v2.duckdb").read_bytes()).digest() == hashlib.sha256(
        (state / "data" / "steuerreport_v2.duckdb").read_bytes()
    ).digest()


def test_archive_verifier_rejects_traversal_and_symlinks(tmp_path: Path) -> None:
    traversal = tmp_path / "traversal.tar.gz"
    with tarfile.open(traversal, "w:gz") as archive:
        member = tarfile.TarInfo("mounts/m000/../../escape")
        member.size = 1
        archive.addfile(member, io.BytesIO(b"x"))
    with pytest.raises(ops.OpsError, match="archive_member_path_invalid"):
        ops._safe_archive_records(traversal)

    linked = tmp_path / "linked.tar.gz"
    with tarfile.open(linked, "w:gz") as archive:
        member = tarfile.TarInfo("mounts/m000/link")
        member.type = tarfile.SYMTYPE
        member.linkname = "/etc/passwd"
        archive.addfile(member)
    with pytest.raises(ops.OpsError, match="archive_member_type_unsupported"):
        ops._safe_archive_records(linked)


def test_restore_comparison_includes_wal_and_non_database_files() -> None:
    before = {
        "tables": {"main.events": {"rows": 1, "sha256": "a"}},
        "database_archive_paths": ["mounts/m000/data/steuerreport_v2.duckdb"],
        "schema_version": 1,
        "vault": {"decryptable": True, "unreadable_rows": 0},
        "archive_members": [
            {"path": "mounts/m000/data/steuerreport_v2.duckdb", "sha256": "db-a"},
            {"path": "mounts/m000/data/steuerreport_v2.duckdb.wal", "sha256": "wal-a"},
        ],
    }
    after = json.loads(json.dumps(before))
    assert ops._equal_after_start(before, after)
    after["archive_members"][1]["sha256"] = "wal-changed"
    assert not ops._equal_after_start(before, after)


def _minimal_backup(root: Path, payload: bytes = b"synthetic backup payload") -> Path:
    backup = root / "backup"
    backup.mkdir(mode=0o700)
    archive_path = backup / "state.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        member = tarfile.TarInfo("mounts/m000/data.bin")
        member.size = len(payload)
        member.mode = 0o600
        archive.addfile(member, io.BytesIO(payload))
    archive_path.chmod(0o600)
    digest = hashlib.sha256(payload).hexdigest()
    database_tables = {}
    manifest = {
        "format_version": ops.FORMAT_VERSION,
        "source_image": {
            "image_id": "sha256:" + "a" * 64,
            "revision": "b" * 40,
            "version": "0.0.1-test",
            "platform": "linux/amd64",
        },
        "schema_version": 1,
        "database_present": True,
        "database_tables": database_tables,
        "database_table_count": 0,
        "database_row_count": 0,
        "database_semantic_sha256": hashlib.sha256(ops._json_bytes(database_tables)).hexdigest(),
        "mounts": [{
            "id": "m000",
            "kind": "volume",
            "target": "/state",
            "read_only": False,
            "archive_prefix": "mounts/m000",
        }],
        "archive_members": [{
            "path": "mounts/m000/data.bin",
            "type": "file",
            "uid": 0,
            "gid": 0,
            "mode": 0o600,
            "size": len(payload),
            "sha256": digest,
        }],
        "archive_sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        "archive_size_bytes": archive_path.stat().st_size,
        "wal_files": [],
        "runtime_paths": {},
    }
    manifest_path = backup / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_path.chmod(0o600)
    return backup


def test_restore_size_limit_is_checked_before_archive_hashing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backup = _minimal_backup(tmp_path, b"x" * 4096)

    def unexpected_hash(_: Path) -> str:
        raise AssertionError("archive was read before the size limit")

    monkeypatch.setattr(ops, "_sha256", unexpected_hash)
    with pytest.raises(ops.OpsError, match="restore_size_exceeds_operator_limit"):
        ops._load_backup(backup, max_uncompressed_bytes=1024, max_archive_bytes=1024 * 1024)


def test_archive_byte_limit_is_checked_before_archive_hashing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backup = _minimal_backup(tmp_path)

    def unexpected_hash(_: Path) -> str:
        raise AssertionError("archive was read before the compressed-size limit")

    monkeypatch.setattr(ops, "_sha256", unexpected_hash)
    with pytest.raises(ops.OpsError, match="archive_size_exceeds_operator_limit"):
        ops._load_backup(backup, max_uncompressed_bytes=1024, max_archive_bytes=1)


def test_restore_stages_only_the_manifest_hashed_archive(tmp_path: Path) -> None:
    backup_dir = _minimal_backup(tmp_path)
    archive, manifest = ops._load_backup(
        backup_dir,
        max_uncompressed_bytes=1024,
        max_archive_bytes=1024 * 1024,
        max_expanded_archive_bytes=2 * 1024 * 1024,
    )
    with archive.open("r+b") as source:
        source.seek(-1, 2)
        last_byte = source.read(1)
        source.seek(-1, 2)
        source.write(bytes([last_byte[0] ^ 1]))
    staged = tmp_path / "staged.tar.gz"

    with pytest.raises(ops.OpsError, match="backup_archive_changed_after_verification"):
        ops._stage_backup_archive(archive, manifest, staged, 1024 * 1024)
    assert not staged.exists()


def test_tar_member_limit_is_checked_before_member_hashing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive_path = tmp_path / "oversized.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        member = tarfile.TarInfo("mounts/m000/big.bin")
        member.size = 4096
        archive.addfile(member, io.BytesIO(b"x" * member.size))

    def unexpected_extractfile(*_: object, **__: object) -> None:
        raise AssertionError("tar member was read before its declared size was checked")

    monkeypatch.setattr(tarfile.TarFile, "extractfile", unexpected_extractfile)
    with pytest.raises(ops.OpsError, match="restore_size_exceeds_operator_limit"):
        ops._safe_archive_records(archive_path, max_uncompressed_bytes=1024)


def test_expanded_tar_limit_counts_pax_metadata(tmp_path: Path) -> None:
    archive_path = tmp_path / "pax.tar.gz"
    with tarfile.open(archive_path, "w:gz", format=tarfile.PAX_FORMAT) as archive:
        member = tarfile.TarInfo("mounts/m000/" + "x" * 200)
        member.size = 1
        archive.addfile(member, io.BytesIO(b"x"))

    with pytest.raises(ops.OpsError, match="expanded_archive_exceeds_operator_limit"):
        ops._safe_archive_records(
            archive_path, max_uncompressed_bytes=1024, max_expanded_archive_bytes=128,
        )


def test_expanded_tar_limit_counts_trailing_gzip_data(tmp_path: Path) -> None:
    archive_path = tmp_path / "trailing.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        member = tarfile.TarInfo("mounts/m000/small")
        member.size = 1
        archive.addfile(member, io.BytesIO(b"x"))
    with archive_path.open("ab") as output:
        output.write(gzip.compress(b"x" * 4096))

    with pytest.raises(ops.OpsError, match="expanded_archive_exceeds_operator_limit"):
        ops._safe_archive_records(
            archive_path, max_uncompressed_bytes=1024, max_expanded_archive_bytes=2048,
        )


def test_compose_override_pins_image_and_maps_new_volumes() -> None:
    image_digest = "ghcr.io/example/steuerreport@sha256:" + "a" * 64
    mounts = [{"id": "m000", "target": "/state", "read_only": False}]
    rendered = ops._compose_override(image_digest, mounts, ["sr-restore-run-001-000"], {
        "STEUERREPORT_V2_DB": "/state/data/steuerreport_v2.duckdb",
    })

    assert f'image: "{image_digest}"' in rendered
    assert "pull_policy: never" in rendered
    assert "name: sr-restore-run-001-000" in rendered
    assert 'target: "/state"' in rendered
    assert 'STEUERREPORT_V2_DB: "/state/data/steuerreport_v2.duckdb"' in rendered

    readonly = ops._compose_override(image_digest, [
        {"id": "m000", "target": "/evidence", "read_only": True},
    ], ["sr-restore-run-002-000"], {})
    assert "read_only: true" in readonly


def test_restore_requires_repository_digest_for_compose_activation() -> None:
    with pytest.raises(ops.OpsError, match="restore_requires_immutable_repository_digest"):
        ops._immutable_image_reference({"repo_digests": []})
    assert ops._immutable_image_reference({
        "repo_digests": ["ghcr.io/example/app@sha256:" + "a" * 64],
    }) == "ghcr.io/example/app@sha256:" + "a" * 64


def test_restore_cleanup_failure_is_not_reported_as_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def inspect_failure(*_: object) -> str:
        raise ops.OpsError("docker_inspect_failed")

    monkeypatch.setattr(ops, "_resource_state", inspect_failure)
    monkeypatch.setattr(ops, "RESTORE_CLEANUP_ATTEMPTS", 1)
    failures = ops._cleanup_restore_resources("sr-restore-run-001", True, ["sr-restore-run-001-000"], "run-001")

    assert failures == [
        "container_inspect_failed:docker_inspect_failed",
        "volume_inspect_failed:docker_inspect_failed",
    ]


def test_restore_cleanup_attempts_volumes_after_container_remove_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    removed = []

    def state(kind: str, *_: object) -> str:
        return "owned"

    def docker(args: list[str], **_: object) -> str:
        removed.append(args)
        raise ops.OpsError("docker_command_failed")

    monkeypatch.setattr(ops, "_resource_state", state)
    monkeypatch.setattr(ops, "_docker", docker)
    monkeypatch.setattr(ops, "RESTORE_CLEANUP_ATTEMPTS", 2)
    monkeypatch.setattr(ops.time, "sleep", lambda _: None)
    failures = ops._cleanup_restore_resources("sr-restore-run-001", True, ["sr-restore-run-001-000"], "run-001")

    assert removed == [
        ["rm", "--force", "sr-restore-run-001"],
        ["rm", "--force", "sr-restore-run-001"],
        ["volume", "rm", "sr-restore-run-001-000"],
        ["volume", "rm", "sr-restore-run-001-000"],
    ]
    assert failures == ["container_remove_failed", "volume_remove_failed"]


@pytest.mark.parametrize("kind", ["container", "volume"])
def test_restore_cleanup_retries_transient_remove_failure(
    monkeypatch: pytest.MonkeyPatch, kind: str,
) -> None:
    state = {kind: "owned"}
    attempts = 0

    def inspect(resource_kind: str, *_: object) -> str:
        return state.get(resource_kind, "missing")

    def docker(args: list[str], **_: object) -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ops.OpsError("docker_resource_temporarily_busy")
        state[kind] = "missing"
        return ""

    monkeypatch.setattr(ops, "_resource_state", inspect)
    monkeypatch.setattr(ops, "_docker", docker)
    monkeypatch.setattr(ops, "RESTORE_CLEANUP_ATTEMPTS", 3)
    monkeypatch.setattr(ops.time, "sleep", lambda _: None)

    assert ops._cleanup_restore_resource(kind, "sr-restore-run-001", "run-001") is None
    assert attempts == 2


def test_restore_cleanup_never_removes_unowned_resource(monkeypatch: pytest.MonkeyPatch) -> None:
    removed = []
    monkeypatch.setattr(ops, "_resource_state", lambda *_: "not_owned")
    monkeypatch.setattr(ops, "_docker", lambda args, **_: removed.append(args))

    assert ops._cleanup_restore_resource("volume", "foreign-volume", "run-001") == "volume_ownership_unverified"
    assert removed == []


@pytest.mark.parametrize("other_suffix", ["data/subdir", "."])
def test_backup_rejects_nested_running_bind_consumers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, other_suffix: str,
) -> None:
    target = tmp_path / "data"
    other_source = target / "subdir" if other_suffix == "data/subdir" else tmp_path
    other = [{
        "Id": "other-container",
        "Mounts": [{"Type": "bind", "Source": str(other_source)}],
    }]

    def docker(args: list[str], **_: object) -> str:
        if args == ["ps", "--quiet"]:
            return "other-container\n"
        if args == ["inspect", "other-container"]:
            return json.dumps(other)
        raise AssertionError(args)

    monkeypatch.setattr(ops, "_docker", docker)
    source = {"Id": "source-container", "State": {"Status": "exited", "ExitCode": 0}}
    mounts = [{"kind": "bind", "source": str(target)}]

    with pytest.raises(ops.OpsError, match="external_bind_has_running_consumer"):
        ops._assert_no_running_consumers(source, mounts)


def test_mount_manifest_preserves_original_read_only_mode() -> None:
    rows = ops._mounts({"Mounts": [{
        "Type": "volume", "Name": "fixture", "Destination": "/state", "RW": False,
    }]})

    assert rows[0]["read_only"] is True
    with pytest.raises(ops.OpsError, match="persistent_mount_access_mode_unknown"):
        ops._mounts({"Mounts": [{
            "Type": "volume", "Name": "fixture", "Destination": "/state",
        }]})


def test_created_volume_is_tracked_before_ownership_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ops, "_inspect_optional", lambda *_: None)
    monkeypatch.setattr(ops, "_create_restore_volume", lambda *_: None)

    def ownership_failure(*_: object) -> str:
        raise ops.OpsError("docker_inspect_failed")

    monkeypatch.setattr(ops, "_resource_state", ownership_failure)
    created = []
    with pytest.raises(ops.OpsError, match="docker_inspect_failed"):
        ops._new_restore_volumes([{"id": "m000", "target": "/state"}], "run-001", created)
    assert created == ["sr-restore-run-001-000"]


def test_helper_timeout_cleanup_requires_matching_ownership_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cidfile = tmp_path / "container.id"
    cidfile.write_text("a" * 64, encoding="ascii")
    monkeypatch.setattr(ops, "_resource_state", lambda *_: "not_owned")

    assert not ops._cleanup_helper_container(cidfile, "helper-run-001")


def test_helper_timeout_cleanup_finds_container_when_cidfile_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    container_id = "a" * 64
    cidfile = tmp_path / "missing-container.id"
    state = {container_id: "owned"}
    commands = []

    def docker(args: list[str], **_: object) -> str:
        commands.append(args)
        if args[0] == "ps":
            return container_id + "\n"
        if args == ["rm", "--force", container_id]:
            if commands.count(args) == 1:
                raise ops.OpsError("docker_resource_temporarily_busy")
            state[container_id] = "missing"
            return container_id + "\n"
        raise AssertionError(args)

    monkeypatch.setattr(ops, "_docker", docker)
    monkeypatch.setattr(ops, "_resource_state", lambda _kind, name, _run: state.get(name, "missing"))
    monkeypatch.setattr(ops, "RESTORE_CLEANUP_ATTEMPTS", 3)
    monkeypatch.setattr(ops.time, "sleep", lambda _: None)

    assert ops._cleanup_helper_container(cidfile, "helper-run-001") is True
    assert commands == [
        ["ps", "--all", "--quiet", "--no-trunc", "--filter", "label=steuerreport.ops.restore=helper-run-001"],
        ["rm", "--force", container_id],
        ["rm", "--force", container_id],
    ]


def test_helper_timeout_cleanup_does_not_remove_unowned_container_without_cid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    container_id = "b" * 64
    removals = []
    cidfile = tmp_path / "missing-container.id"
    monkeypatch.setattr(ops, "_docker", lambda args, **_: container_id if args[0] == "ps" else removals.append(args))
    monkeypatch.setattr(ops, "_resource_state", lambda *_: "not_owned")

    assert ops._cleanup_helper_container(cidfile, "helper-run-002") is False
    assert removals == []


def test_docker_wrapper_converts_os_errors_to_safe_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_: object, **__: object) -> None:
        raise PermissionError(13, "synthetic docker cli permission failure")

    monkeypatch.setattr(ops.subprocess, "run", fail)

    with pytest.raises(ops.OpsError, match="docker_command_os_error:13"):
        ops._docker(["version"])
