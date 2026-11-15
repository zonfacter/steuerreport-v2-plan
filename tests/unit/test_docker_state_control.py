"""Kleine gemockte Steuerpfadproben; kein Zugriff auf einen Docker-Daemon."""
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def ops():
    spec = importlib.util.spec_from_file_location("state_control_subject", ROOT / "scripts/docker_state_v2.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def restore_case(ops, tmp_path, monkeypatch):
    image_id = "sha256:" + "a" * 64
    image = {"image_id": image_id, "revision": "b" * 40, "version": "synthetic",
             "repo_digests": ["example.invalid/synthetic@sha256:" + "c" * 64]}
    mounts = [{"id": "m000", "kind": "volume", "target": "/state", "read_only": False,
               "archive_prefix": "mounts/m000"}]
    manifest = {"source_image": image, "mounts": mounts, "archive_members": [], "wal_files": [],
                "schema_version": 3, "database_tables": {}, "database_semantic_sha256": "d" * 64,
                "runtime_paths": {}}
    snapshot = {"database_present": True, "required_private_files_present": True,
                "vault": {"decryptable": True, "encrypted_rows": 1, "unreadable_rows": 0},
                "schema_version": 3, "tables": {}, "database_semantic_sha256": "d" * 64,
                "database_catalog_sha256": "e" * 64,
                "archive_members": [], "wal_files": []}
    monkeypatch.setattr(ops, "_load_backup", lambda *a, **kw: (tmp_path / "synthetic.tar.gz", manifest))
    monkeypatch.setattr(ops, "_image_info", lambda *a: image)
    monkeypatch.setattr(ops, "_stage_backup_archive", lambda *a: tmp_path / "staged.tar.gz")
    monkeypatch.setattr(ops, "_run_helper_command", lambda *a, **kw: {})
    monkeypatch.setattr(ops, "_runtime_snapshot", lambda *a: snapshot)
    monkeypatch.setattr(ops.time, "sleep", lambda *a: None)
    args = SimpleNamespace(backup_dir=tmp_path, output_dir=tmp_path / "output", evidence_dir=tmp_path / "evidence",
                           run_id="synthetic-ops", max_restore_bytes=1024, max_archive_bytes=1024,
                           max_expanded_archive_bytes=2048, image=None)
    resources, commands = {}, []
    monkeypatch.setattr(ops, "_inspect_optional", lambda kind, name: resources.get((kind, name)))
    def docker(command, **kwargs):
        commands.append(command)
        if command[:2] == ["volume", "create"]:
            name = command[-1]
            resources["volume", name] = {"Labels": {ops.RESOURCE_LABEL: args.run_id,
                                                    ops.OWNER_LABEL: ops.OWNER_NONCE}}
            return name
        if command[:2] == ["volume", "rm"]:
            resources.pop(("volume", command[-1]), None)
        if command[:2] == ["rm", "--force"]:
            for key, obj in list(resources.items()):
                if key[0] == "container" and obj.get("Id") == command[-1]:
                    resources.pop(key)
        return ""
    monkeypatch.setattr(ops, "_docker", docker)
    return args, resources, commands, docker


@pytest.mark.parametrize("action", ["restore", "restore_check"])
def test_volume_created_before_response_failure_is_tracked_and_removed(ops, restore_case, monkeypatch, action):
    args, resources, commands, real_docker = restore_case
    def uncertain_create(command, **kwargs):
        result = real_docker(command, **kwargs)
        return "unexpected-response" if command[:2] == ["volume", "create"] else result
    monkeypatch.setattr(ops, "_docker", uncertain_create)
    with pytest.raises(ops.OpsError, match="restore_volume_create_response_mismatch"):
        getattr(ops, action)(args)
    assert resources == {}, "Created labelled volume must not be orphaned"
    assert any(command[:2] == ["volume", "rm"] for command in commands)


def test_container_created_before_timeout_is_tracked_and_removed(ops, restore_case, monkeypatch):
    args, resources, commands, real_docker = restore_case
    def uncertain_create(command, **kwargs):
        if command[0] == "create":
            name = command[command.index("--name") + 1]
            resources["container", name] = {"Id": "a" * 64, "Config": {"Labels": {
                ops.RESOURCE_LABEL: args.run_id, ops.OWNER_LABEL: ops.OWNER_NONCE}}}
            raise ops.OpsError("docker_command_timeout:create")
        return real_docker(command, **kwargs)
    monkeypatch.setattr(ops, "_docker", uncertain_create)
    with pytest.raises(ops.OpsError, match="docker_command_timeout:create"):
        ops.restore_check(args)
    assert resources == {}, "Created labelled container must not be orphaned"
    assert any(command[:2] == ["rm", "--force"] for command in commands)


def test_existing_restore_container_is_rejected_before_new_volumes(ops, restore_case):
    args, resources, commands, _ = restore_case
    resources["container", "sr-restore-" + args.run_id] = {"Config": {"Labels": {"unrelated": "keep"}}}
    original = copy.deepcopy(resources)
    with pytest.raises(ops.OpsError, match="restore_container_already_exists"):
        ops.restore_check(args)
    assert commands == [] and resources == original


@pytest.mark.parametrize("signal", [KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("cleanup", [True, False])
def test_helper_interrupt_cleans_only_own_resources_and_never_claims_success(ops, tmp_path, monkeypatch, signal, cleanup):
    calls = []
    def interrupted(*args, **kwargs):
        raise signal()
    monkeypatch.setattr(ops.subprocess, "run", interrupted)
    monkeypatch.setattr(ops, "_cleanup_helper_container", lambda cid, owner, **kw: calls.append((cid, owner)) or cleanup)
    expected = signal if cleanup else ops.OpsError
    with pytest.raises(BaseException) as caught:
        ops._run_helper_command(["run"], tmp_path / "container.id", run_id="synthetic-owner", timeout=1)
    assert isinstance(caught.value, expected)
    assert calls == [(tmp_path / "container.id", "synthetic-owner")]


@pytest.mark.parametrize("returncode,body", [(0, '{"status":"ok"}'), (1, '{"error":"synthetic_failure"}'), (0, 'invalid')])
def test_helper_exit_always_checks_owned_resource_cleanup(ops, tmp_path, monkeypatch, returncode, body):
    calls = []
    monkeypatch.setattr(ops.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=returncode, stdout=body))
    monkeypatch.setattr(ops, "_cleanup_helper_container", lambda cid, owner, **kw: calls.append(owner) or True)
    if returncode == 0 and body.startswith("{"):
        assert ops._run_helper_command(["run"], tmp_path / "cid", run_id="synthetic", timeout=1) == {"status": "ok"}
    else:
        with pytest.raises(ops.OpsError):
            ops._run_helper_command(["run"], tmp_path / "cid", run_id="synthetic", timeout=1)
    assert calls == ["synthetic"]


def test_helper_success_with_unconfirmed_cleanup_is_blocked(ops, tmp_path, monkeypatch):
    monkeypatch.setattr(ops.subprocess, "run", lambda *a, **kw: SimpleNamespace(returncode=0, stdout='{"status":"ok"}'))
    monkeypatch.setattr(ops, "_cleanup_helper_container", lambda *a, **kw: False)
    with pytest.raises(ops.OpsError, match="cleanup_unconfirmed"):
        ops._run_helper_command(["run"], tmp_path / "cid", run_id="synthetic", timeout=1)


def test_direct_backup_requires_explicit_confirmation_before_inspect(ops, tmp_path, monkeypatch):
    monkeypatch.setattr(ops, "_inspect", lambda *a: pytest.fail("No unconfirmed backup inspection"))
    with pytest.raises(ops.OpsError, match="confirm_source_stopped_required"):
        ops.backup(SimpleNamespace(container="synthetic", output_dir=tmp_path / "out", confirm_source_stopped=False))


@pytest.fixture
def backup_case(ops, tmp_path, monkeypatch):
    source = {"Id": "a" * 64, "Image": "sha256:" + "b" * 64, "Config": {"Env": []}, "Mounts": [],
              "State": {"Status": "exited", "ExitCode": 0, "StartedAt": "synthetic-start", "FinishedAt": "synthetic-stop"}}
    snapshot = {"database_present": True, "schema_version": 3, "archive_members": [],
                "vault": {"decryptable": True}, "tables": {}, "database_semantic_sha256": "c" * 64,
                "database_catalog_sha256": "e" * 64}
    inventory = {**snapshot, "complete": True, "wal_files": [], "configured_path_count_checked": 1}
    monkeypatch.setattr(ops, "_inspect", lambda *a: copy.deepcopy(source))
    monkeypatch.setattr(ops, "_mounts", lambda *a: [])
    monkeypatch.setattr(ops, "_docker", lambda *a, **kw: "")
    monkeypatch.setattr(ops, "_image_info", lambda *a: {"version": "synthetic", "revision": "d" * 40})
    monkeypatch.setattr(ops, "_helper_json", lambda *a, **kw: inventory)
    monkeypatch.setattr(ops, "_runtime_snapshot", lambda *a: snapshot)
    monkeypatch.setattr(ops, "_safe_archive_records", lambda *a, **kw: [])
    monkeypatch.setattr(ops, "_cleanup_helper_container", lambda *a, **kw: True)
    args = SimpleNamespace(container="synthetic", output_dir=tmp_path / "backup",
                           confirm_source_stopped=True, confirm_external_paths_quiesced=False)
    class Process:
        def wait(self, **kw):
            return 0
    monkeypatch.setattr(ops.subprocess, "Popen", lambda *a, **kw: Process())
    return args, source


@pytest.mark.parametrize("state", ["restarted", "running"])
def test_source_restart_during_backup_prevents_success(ops, backup_case, monkeypatch, state):
    args, source = backup_case
    calls = []
    def inspect(*a):
        current = copy.deepcopy(source)
        if a[0] == "container" and calls:
            current["State"]["StartedAt"] = "synthetic-new-start"
            if state == "running":
                current["State"]["Status"] = "running"
        if a[0] == "container":
            calls.append(a)
        return current
    monkeypatch.setattr(ops, "_inspect", inspect)
    with pytest.raises(ops.OpsError):
        ops.backup(args)
    assert not (args.output_dir / "manifest.json").exists()


def test_archive_interrupt_stops_cli_and_checks_owned_helper_cleanup(ops, backup_case, monkeypatch):
    args, _ = backup_case
    events = []
    class Process:
        stopped = False
        def wait(self, **kw):
            if not self.stopped:
                raise KeyboardInterrupt()
            return 0
        def terminate(self):
            self.stopped = True
            events.append("terminate")
        def kill(self):
            self.stopped = True
            events.append("kill")
    monkeypatch.setattr(ops.subprocess, "Popen", lambda *a, **kw: Process())
    monkeypatch.setattr(ops, "_cleanup_helper_container", lambda *a, **kw: events.append("cleanup") or True)
    with pytest.raises(KeyboardInterrupt):
        ops.backup(args)
    assert events == ["terminate", "cleanup"]
    assert not (args.output_dir / "manifest.json").exists()


def test_unknown_helper_start_without_observed_identity_is_not_cleanup_proof(ops, tmp_path, monkeypatch):
    monkeypatch.setattr(ops, "_docker", lambda *a, **kw: "")
    assert ops._cleanup_helper_container(tmp_path / "missing-cid", "synthetic", require_observed=True) is False
    assert ops._cleanup_helper_container(tmp_path / "missing-cid", "synthetic") is True


def test_archive_stop_failure_still_attempts_cleanup_and_preserves_partial_output(ops, backup_case, monkeypatch):
    args, _ = backup_case
    calls = []
    class Process:
        def wait(self, **kw):
            raise KeyboardInterrupt()
        def terminate(self):
            raise OSError("synthetic private stop detail")
        def kill(self):
            raise OSError("synthetic private kill detail")
    monkeypatch.setattr(ops.subprocess, "Popen", lambda *a, **kw: Process())
    monkeypatch.setattr(ops, "_cleanup_helper_container", lambda *a, **kw: calls.append("cleanup") or True)
    with pytest.raises(ops.OpsError, match="backup_archive_cleanup_unconfirmed"):
        ops.backup(args)
    assert calls == ["cleanup"]
    assert (args.output_dir / "state.tar.gz").is_file()
    assert not (args.output_dir / "manifest.json").exists()


@pytest.mark.parametrize("key", ["STEUERREPORT_PRIMARY_SOLANA_WALLET", "STEUERREPORT_CUSTOM_SECRET", "STEUERREPORT_V2_ROOT"])
def test_unpersisted_runtime_overrides_cannot_be_silently_lost_or_echoed(ops, monkeypatch, key):
    source = {"Config": {"Env": [key + "=synthetic-private-value"]}}
    monkeypatch.setattr(ops, "_inspect", lambda *a: {"Config": {"Env": []}})
    with pytest.raises(ops.OpsError, match="application_environment_not_persisted") as error:
        ops._check_runtime_environment(source, "synthetic")
    assert "synthetic-private-value" not in str(error.value)


def test_image_defaults_and_explicitly_archived_runtime_paths_are_supported(ops, monkeypatch):
    default = "STEUERREPORT_V2_REQUIRE_ENCRYPTED_SECRETS=true"
    source = {"Config": {"Env": [default, "STEUERREPORT_V2_DB=/state/custom.duckdb"]}}
    monkeypatch.setattr(ops, "_inspect", lambda *a: {"Config": {"Env": [default]}})
    ops._check_runtime_environment(source, "synthetic")


@pytest.mark.parametrize("value", [None, "invalid", "f" * 64])
def test_source_catalog_missing_invalid_or_changed_cannot_create_backup(ops, backup_case, monkeypatch, value):
    args, _ = backup_case
    original_snapshot = ops._runtime_snapshot(None)
    changed = {**original_snapshot, "database_catalog_sha256": value}
    monkeypatch.setattr(ops, "_runtime_snapshot", lambda *a: changed)
    with pytest.raises(ops.OpsError):
        ops.backup(args)
    assert not args.output_dir.exists()


@pytest.mark.parametrize("action", ["restore", "restore_check"])
@pytest.mark.parametrize("condition", ["missing", "invalid", "mismatch"])
def test_restore_catalog_failure_prevents_activation_and_cleans_new_volumes(ops, restore_case, monkeypatch, action, condition):
    args, resources, commands, _ = restore_case
    _, manifest = ops._load_backup(None)
    snapshot = ops._runtime_snapshot(None)
    if condition == "mismatch":
        manifest["database_catalog_sha256"] = "f" * 64
    else:
        snapshot = {**snapshot, "database_catalog_sha256": None if condition == "missing" else "invalid"}
    monkeypatch.setattr(ops, "_runtime_snapshot", lambda *a: snapshot)
    with pytest.raises(ops.OpsError, match="restored_catalog_"):
        getattr(ops, action)(args)
    assert resources == {}
    assert not any(command[0] in ("create", "start") for command in commands)
