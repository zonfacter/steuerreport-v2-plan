from __future__ import annotations

import copy
import importlib.util
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_portable_state_ci_v2.py"
SPEC = importlib.util.spec_from_file_location("portable_state_ci", SCRIPT)
assert SPEC and SPEC.loader
ci = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ci)

RUN = "123456"
NAME = f"sr-cache-a-{RUN}"
RESTORE_RUN = f"ci-{RUN}-a"
SECRET = "DO-NOT-PUBLISH-PRIVATE-EVIDENCE"
REAL_POPEN = subprocess.Popen
REAL_RMTREE = ci.shutil.rmtree


def source_info() -> dict:
    return {
        "Id": "a" * 64,
        "Name": "/" + NAME,
        "Image": "sha256:" + "b" * 64,
        "Config": {"Labels": {ci.SYNTHETIC_LABEL: RUN}, "Env": ["PRIVATE=" + SECRET]},
        "HostConfig": {"NetworkMode": "none", "ReadonlyRootfs": True, "PortBindings": {},
                       "Binds": None, "VolumesFrom": None},
        "State": {"Status": "exited", "Running": False, "Paused": False, "Restarting": False,
                  "Dead": False, "OOMKilled": False, "Error": "", "ExitCode": 0,
                  "StartedAt": "synthetic-start", "FinishedAt": "synthetic-stop"},
        "Mounts": [{"Type": "volume", "Destination": "/state", "Name": "c" * 64, "RW": True}],
    }


def responses() -> dict:
    metadata = {"image_version": "0.2.0rc40", "image_revision": "d" * 40,
                "schema_version": 3, "mount_count": 1, "archive_sha256": "e" * 64,
                "archive_members": ["/private/member"], "secret": SECRET}
    summary = {"database_present": True, "schema_version": 3,
               "required_private_files_present": True, "vault_decryptable": True,
               "catalog_fingerprint_present": True,
               "encrypted_secret_rows": 2, "unreadable_secret_rows": 0}
    return {
        "backup": {**metadata, "status": "backup_created", "backup_dir": "/private/backup",
                   "source_pause_boundary_checked": True},
        "verify": {**metadata, "status": "verified"},
        "restore-check": {
            "status": "passed", "cleanup": True, "cleanup_failures": [],
            "image_id": "sha256:" + "b" * 64, "version": metadata["image_version"],
            "revision": metadata["image_revision"], "run_id": RESTORE_RUN,
            "network": "none", "published_ports": False,
            "first_start_preserved": True, "restart_preserved": True,
            "restored_before_start": copy.deepcopy(summary),
            "after_first_start": copy.deepcopy(summary), "after_restart": copy.deepcopy(summary),
            "secret": SECRET,
        },
    }


class FakeCommands:
    def __init__(self):
        self.source = source_info()
        self.answers = responses()
        self.calls = []
        self.actions = []
        self.private_roots = []
        self.after_action = lambda action: None
        self.inspect_hook = lambda target: None
        self.fail_action = None
        self.raw_stdout = {}
        self.inspect_stdout = None
        self.inspect_error = None
        self.action_error = None
        self.processes = []
        self.stop_error = None
        self.send_error = None

    def popen(self, command, **kwargs):
        assert kwargs.pop("start_new_session") is True
        owner = self

        class Process:
            returncode = None

            def __init__(self):
                self.signals = []
                self.waits = []

            def wait(self, timeout=None):
                self.waits.append(timeout)
                if timeout is not None:
                    if owner.stop_error:
                        raise owner.stop_error
                    self.returncode = 130
                else:
                    self.returncode = owner(command, **kwargs).returncode
                return self.returncode

            def poll(self):
                return self.returncode

            def send_signal(self, signum):
                self.signals.append(signum)
                if owner.send_error:
                    raise owner.send_error

            def kill(self):
                pytest.fail("Harness must not SIGKILL the operator")

        process = Process()
        self.processes.append(process)
        return process

    def __call__(self, command, **kwargs):
        self.calls.append(command)
        if command[:3] == ["docker", "container", "inspect"]:
            assert len(command) == 4
            assert kwargs == {"capture_output": True, "text": True, "timeout": 30}
            if self.inspect_error:
                raise self.inspect_error
            self.inspect_hook(command[3])
            raw = self.inspect_stdout
            if raw is None:
                raw = json.dumps([self.source])
            return SimpleNamespace(returncode=0, stdout=raw)
        # Anything except read-only inspect must be the existing operator CLI.
        assert command[:2] == [sys.executable, str(ci.OPERATOR)]
        action = command[2]
        assert action in ("backup", "verify", "restore-check")
        self.actions.append(action)
        if self.action_error:
            raise self.action_error
        args = dict(zip(command[3::2], command[4::2]))
        private = Path(kwargs["env"]["TMPDIR"])
        assert kwargs["env"]["TMP"] == kwargs["env"]["TEMP"] == str(private)
        assert stat.S_IMODE(private.stat().st_mode) == 0o700
        assert private.parent == Path(os.environ["RUNNER_TEMP"])
        assert private.name.startswith("steuerreport-state-private-")
        self.private_roots.append(private)
        if action == "backup":
            assert command[-1] == "--confirm-source-stopped"
            assert args["--container"] == "a" * 64
            backup_dir = Path(args["--output-dir"])
            assert backup_dir == private / "backup"
            backup_dir.mkdir(mode=0o700)
            (backup_dir / "state.tar.gz").write_text(SECRET)
            (backup_dir / "manifest.json").write_text(json.dumps(self.answers[action]))
        else:
            assert args["--backup-dir"] == str(private / "backup")
            assert args["--max-archive-bytes"] == str(32 * 1024 * 1024)
            assert args["--max-expanded-archive-bytes"] == str(256 * 1024 * 1024)
            if action == "verify":
                assert args["--max-uncompressed-bytes"] == str(256 * 1024 * 1024)
            else:
                assert args["--max-restore-bytes"] == str(256 * 1024 * 1024)
                assert args["--image"] == "sha256:" + "b" * 64
                assert args["--run-id"] in (RESTORE_RUN, f"ci-{RUN}-b")
                evidence = Path(args["--evidence-dir"])
                assert evidence == private / "evidence"
                evidence.mkdir(mode=0o700)
                (evidence / "restore-check.json").write_text(json.dumps(self.answers[action]))
        raw = self.raw_stdout.get(action, json.dumps(self.answers[action]))
        kwargs["stdout"].write(raw)
        kwargs["stderr"].write("private stderr: " + SECRET)
        self.after_action(action)
        return SimpleNamespace(returncode=2 if self.fail_action == action else 0)


@pytest.fixture(autouse=True)
def forbid_real_processes(monkeypatch):
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    def forbidden(*args, **kwargs):
        pytest.fail("Only explicitly allowed synthetic Python signal children may run")
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    yield
    assert {sig: signal.getsignal(sig) for sig in handlers} == handlers


@pytest.fixture
def harness(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("GITHUB_RUN_ID", RUN)
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    fake = FakeCommands()
    monkeypatch.setattr(ci.subprocess, "run", fake)
    monkeypatch.setattr(ci.subprocess, "Popen", fake.popen)
    output = tmp_path / "publishable"
    yield fake, output
    # Mock resources never run. Real synthetic children are reaped by their
    # dependent fixture before this test-only temporary-directory cleanup.
    for private in tmp_path.glob("steuerreport-state-private-*"):
        REAL_RMTREE(private)


def invoke(output, *, name=NAME, run_id=RUN):
    return ci.main(["--container", name, "--run-id", run_id, "--output", str(output)])


def assert_result(output, *, passed):
    assert {path.name for path in output.iterdir()} == {"result.json"}
    path = output / "result.json"
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    raw = path.read_text()
    assert len(raw) < 2048
    result = json.loads(raw)
    assert result["status"] == ("passed" if passed else "failed")
    assert result["passed"] is passed
    allowed = {"format_version", "status", "reason", "backup_created", "verified", "passed",
               "cleanup", "source_unchanged", "schema_match", "image_match",
               "vault_decryptable", "vault_rows_present"}
    allowed.add("private_staging_retained")
    assert set(result) <= allowed
    assert type(result["private_staging_retained"]) is bool
    if result["private_staging_retained"]:
        assert result["cleanup"] is False
    for value in (SECRET, "/private", "archive_sha256", "archive_members", "PRIVATE=",
                  "d" * 40, "e" * 64, "c" * 64, str(output)):
        assert value not in raw
    return result


@pytest.mark.parametrize("suffix", ["a", "b"])
@pytest.mark.parametrize("exit_code", [0, 143])
def test_success_chain_is_private_sanitized_and_preserves_source(harness, capsys, suffix, exit_code):
    fake, output = harness
    name, run_id = f"sr-cache-{suffix}-{RUN}", f"ci-{RUN}-{suffix}"
    fake.source["Name"] = "/" + name
    fake.source["State"]["ExitCode"] = exit_code
    fake.answers["restore-check"]["run_id"] = run_id
    original = copy.deepcopy(fake.source)
    assert invoke(output, name=name) == 0
    result = assert_result(output, passed=True)
    assert all(result[key] is True for key in result if key not in (
        "format_version", "status", "private_staging_retained"))
    assert result["private_staging_retained"] is False
    assert fake.actions == ["backup", "verify", "restore-check"]
    assert fake.source == original
    assert fake.calls[-2:] == [["docker", "container", "inspect", name],
                              ["docker", "container", "inspect", original["Id"]]]
    assert all(not path.exists() for path in fake.private_roots)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("key,value", [
    ("GITHUB_ACTIONS", None), ("GITHUB_ACTIONS", "TRUE"), ("GITHUB_ACTIONS", "false"),
    ("GITHUB_RUN_ID", None), ("GITHUB_RUN_ID", ""), ("GITHUB_RUN_ID", "123-456"),
    ("GITHUB_RUN_ID", "123\n"), ("GITHUB_RUN_ID", "１２３"), ("RUNNER_TEMP", None),
    ("RUNNER_TEMP", "relative"), ("RUNNER_TEMP", "/not/a/runner/directory"),
])
def test_environment_refusal_before_inspection_or_mutation(harness, monkeypatch, key, value, capsys):
    fake, output = harness
    if value is None:
        monkeypatch.delenv(key, raising=False)
    else:
        monkeypatch.setenv(key, value)
    assert invoke(output) == 2
    assert fake.calls == []
    assert not output.exists()
    assert capsys.readouterr() == ("", "portable_state_ci_refused\n")


@pytest.mark.parametrize("name,run_id", [
    ("production", RUN), (NAME + "-extra", RUN),
    ("sr-cache-c-" + RUN, RUN), ("sr-cache-a-123", RUN),
    (NAME, "ci-" + RUN + "-b"), (NAME, "123"), (NAME, RUN + "\n"),
    (NAME, RESTORE_RUN),
])
def test_cli_bindings_refused_before_mutation(harness, name, run_id):
    fake, output = harness
    assert invoke(output, name=name, run_id=run_id) == 2
    assert not fake.calls
    assert not output.exists()


@pytest.mark.parametrize("field,value", [
    (("Id",), "short"), (("Id",), int("1" * 64)),
    (("Image",), "mutable:tag"), (("Name",), "/production"),
    (("Config",), None), (("Config", "Labels"), None),
    (("Config", "Labels", ci.SYNTHETIC_LABEL), "another-run"),
    (("Config", "Labels", ci.SYNTHETIC_LABEL), int(RUN)),
    (("State",), None), (("State", "Status"), "running"),
    (("State", "Running"), True), (("State", "Paused"), True),
    (("State", "Restarting"), True), (("State", "Dead"), True),
    (("State", "OOMKilled"), True), (("State", "Error"), SECRET),
    (("State", "ExitCode"), 137), (("State", "ExitCode"), False),
    (("HostConfig",), None), (("HostConfig", "NetworkMode"), "bridge"),
    (("HostConfig", "ReadonlyRootfs"), False), (("HostConfig", "ReadonlyRootfs"), 1),
    (("HostConfig", "PortBindings"), {"8010/tcp": [{"HostPort": "8010"}]}),
    (("HostConfig", "Binds"), ["/private:/state"]),
    (("HostConfig", "VolumesFrom"), ["production"]),
    (("Mounts",), None), (("Mounts",), []),
    (("Mounts",), [{"Type": "bind", "Destination": "/state", "RW": True}]),
    (("Mounts",), [{"Type": "volume", "Destination": "/state", "Name": "named-volume", "RW": True}]),
    (("Mounts",), [{"Type": "volume", "Destination": "/state", "Name": int("1" * 64), "RW": True}]),
    (("Mounts",), [{"Type": "volume", "Destination": "/wrong", "Name": "c" * 64, "RW": True}]),
    (("Mounts",), [{"Type": "volume", "Destination": "/state", "Name": "c" * 64, "RW": False}]),
    (("Mounts",), [{"Type": "volume", "Destination": "/state", "Name": "c" * 64, "RW": 1}]),
    (("Mounts",), [None]),
    (("Mounts",), [{"Type": "tmpfs", "Destination": "/state"}]),
])
def test_source_refusal_before_any_mutation(harness, field, value):
    fake, output = harness
    target = fake.source
    for part in field[:-1]:
        target = target[part]
    target[field[-1]] = value
    assert invoke(output) == 2
    assert not fake.actions
    assert not output.exists()


@pytest.mark.parametrize("field", [
    "Id", "Name", "Image", "Config", "HostConfig", "State", "Mounts",
    "State.ExitCode", "State.Error", "State.Running", "State.OOMKilled",
    "HostConfig.PortBindings", "HostConfig.ReadonlyRootfs", "Config.Labels",
])
def test_missing_safety_fields_refused_before_mutation(harness, field):
    fake, output = harness
    parts = field.split(".")
    target = fake.source if len(parts) == 1 else fake.source[parts[0]]
    del target[parts[-1]]
    assert invoke(output) == 2
    assert not fake.actions
    assert not output.exists()


def test_second_volume_is_refused(harness):
    fake, output = harness
    fake.source["Mounts"].append({"Type": "volume", "Name": "f" * 64,
                                  "Destination": "/other", "RW": False})
    assert invoke(output) == 2
    assert not output.exists()
    assert not fake.actions


def test_expected_tmpfs_and_null_ports_are_accepted(harness):
    fake, output = harness
    fake.source["Mounts"].append({"Type": "tmpfs", "Destination": "/tmp", "RW": True})
    fake.source["HostConfig"]["PortBindings"] = None
    assert invoke(output) == 0
    assert_result(output, passed=True)


def test_successful_output_cannot_be_reused(harness):
    fake, output = harness
    assert invoke(output) == 0
    before = (output / "result.json").read_bytes()
    calls = list(fake.calls)
    assert invoke(output) == 2
    assert fake.calls == calls
    assert (output / "result.json").read_bytes() == before


def test_overlong_restore_id_is_refused_before_mutation(harness, monkeypatch):
    fake, output = harness
    long_run = "1" * 37
    monkeypatch.setenv("GITHUB_RUN_ID", long_run)
    assert invoke(output, name="sr-cache-a-" + long_run, run_id=long_run) == 2
    assert fake.calls == []
    assert not output.exists()


@pytest.mark.parametrize("kind", ["existing", "file", "symlink", "broken-symlink", "outside", "parent-symlink", "missing-parent", "dotdot"])
def test_output_refusal_never_reuses_or_follows_symlinks(harness, tmp_path, kind):
    fake, output = harness
    marker = tmp_path / "existing-state"
    marker.mkdir()
    (marker / "keep").write_text(SECRET)
    if kind == "existing":
        output.mkdir()
    elif kind == "file":
        output.write_text(SECRET)
    elif kind == "symlink":
        output.symlink_to(marker, target_is_directory=True)
    elif kind == "broken-symlink":
        output.symlink_to(tmp_path / "missing")
    elif kind == "outside":
        output = tmp_path.parent / (tmp_path.name + "-outside")
    elif kind == "parent-symlink":
        output.symlink_to(marker, target_is_directory=True)
        output = output / "child"
    elif kind == "missing-parent":
        output = output / "child"
    else:
        output = marker / ".." / "new"
    assert invoke(output) == 2
    assert not fake.calls
    assert (marker / "keep").read_text() == SECRET


@pytest.mark.parametrize("raw", ["not json " + SECRET, "{}", "[]", "[{},{}]", "[null]"])
def test_invalid_inspect_refused_before_mutation(harness, raw):
    fake, output = harness
    fake.inspect_stdout = raw
    assert invoke(output) == 2
    assert not fake.actions
    assert not output.exists()


@pytest.mark.parametrize("error", [FileNotFoundError(SECRET), subprocess.TimeoutExpired(SECRET, 30)])
def test_inspect_errors_are_sanitized(harness, error, capsys):
    fake, output = harness
    fake.inspect_error = error
    assert invoke(output) == 2
    assert not output.exists()
    assert capsys.readouterr() == ("", "portable_state_ci_refused\n")


@pytest.mark.parametrize("action", ["backup", "verify", "restore-check"])
def test_operator_failure_does_not_advance_and_retains_private_files(harness, action, capsys):
    fake, output = harness
    fake.fail_action = action
    assert invoke(output) == 2
    result = assert_result(output, passed=False)
    assert result["reason"] == "operator_failed"
    assert result["source_unchanged"] is True
    assert fake.actions == ["backup", "verify", "restore-check"][:["backup", "verify", "restore-check"].index(action) + 1]
    assert result["private_staging_retained"] is True
    assert all(path.is_dir() for path in fake.private_roots)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("action,raw", [
    ("backup", "not json " + SECRET), ("verify", "[]"), ("restore-check", "null"),
    ("verify", "x" * (ci.JSON_LIMIT + 1)),
])
def test_invalid_operator_json_is_not_published(harness, action, raw):
    fake, output = harness
    fake.raw_stdout[action] = raw
    assert invoke(output) == 2
    result = assert_result(output, passed=False)
    assert result["private_staging_retained"] is True
    assert fake.actions[-1] == action


@pytest.mark.parametrize("action,field,value", [
    ("backup", "status", "blocked"), ("verify", "status", "blocked"),
    ("verify", "schema_version", 4), ("verify", "schema_version", True),
    ("backup", "schema_version", None), ("backup", "schema_version", True),
    ("verify", "image_revision", "wrong"), ("backup", "image_revision", None),
    ("backup", "image_revision", int("1" * 40)),
    ("verify", "image_version", "wrong"), ("backup", "image_version", ""),
    ("backup", "mount_count", 2), ("verify", "mount_count", True),
    ("restore-check", "status", "failed"), ("restore-check", "cleanup", False),
    ("restore-check", "cleanup", 1), ("restore-check", "cleanup_failures", [SECRET]),
    ("restore-check", "image_id", "sha256:" + "f" * 64),
    ("restore-check", "run_id", "ci-another-run-a"),
    ("restore-check", "revision", "f" * 40), ("restore-check", "version", "wrong"),
    ("restore-check", "network", "bridge"), ("restore-check", "published_ports", True),
    ("restore-check", "first_start_preserved", False), ("restore-check", "restart_preserved", False),
    ("restore-check", "after_restart", None),
])
def test_operator_assertions_fail_closed(harness, action, field, value):
    fake, output = harness
    fake.answers[action][field] = value
    assert invoke(output) == 2
    assert_result(output, passed=False)
    assert fake.actions[-1] == action


@pytest.mark.parametrize("stage", ["restored_before_start", "after_first_start", "after_restart"])
@pytest.mark.parametrize("field,value", [
    ("schema_version", 4), ("schema_version", True), ("database_present", False),
    ("required_private_files_present", False), ("vault_decryptable", False),
    ("vault_decryptable", 1), ("encrypted_secret_rows", 0), ("encrypted_secret_rows", -1),
    ("encrypted_secret_rows", True), ("encrypted_secret_rows", "2"),
    ("unreadable_secret_rows", 1), ("unreadable_secret_rows", False),
    ("catalog_fingerprint_present", False), ("catalog_fingerprint_present", None),
    ("catalog_fingerprint_present", 1),
])
def test_restore_summary_is_required_at_all_three_stages(harness, stage, field, value):
    fake, output = harness
    fake.answers["restore-check"][stage][field] = value
    assert invoke(output) == 2
    result = assert_result(output, passed=False)
    assert result["schema_match"] is False
    assert result["vault_decryptable"] is False


@pytest.mark.parametrize("stage", ["restored_before_start", "after_first_start", "after_restart"])
def test_missing_restore_summary_refused(harness, stage):
    fake, output = harness
    del fake.answers["restore-check"][stage]
    assert invoke(output) == 2
    assert_result(output, passed=False)


@pytest.mark.parametrize("action,field", [
    ("backup", "status"), ("backup", "schema_version"), ("backup", "mount_count"),
    ("backup", "image_version"), ("backup", "image_revision"),
    ("verify", "status"), ("verify", "schema_version"), ("verify", "mount_count"),
    ("verify", "image_version"), ("verify", "image_revision"),
    ("restore-check", "status"), ("restore-check", "cleanup"),
    ("restore-check", "cleanup_failures"), ("restore-check", "image_id"),
    ("restore-check", "version"), ("restore-check", "revision"), ("restore-check", "run_id"),
    ("restore-check", "network"), ("restore-check", "published_ports"),
    ("restore-check", "first_start_preserved"), ("restore-check", "restart_preserved"),
])
def test_missing_operator_fields_cannot_pass(harness, action, field):
    fake, output = harness
    del fake.answers[action][field]
    assert invoke(output) == 2
    assert_result(output, passed=False)
    assert fake.actions[-1] == action


@pytest.mark.parametrize("boundary", [
    {"source_pause_boundary_checked": False}, {},
    {"source_pause_boundary_checked": None},
    {"source_pause_boundary_checked": 1},
    {"source_pause_boundary_checked": "true"},
], ids=["false", "missing", "null", "integer", "string"])
def test_backup_pause_boundary_must_be_explicitly_confirmed(harness, boundary, capsys):
    fake, output = harness
    del fake.answers["backup"]["source_pause_boundary_checked"]
    fake.answers["backup"].update(boundary)
    assert invoke(output) == 2
    result = assert_result(output, passed=False)
    assert result["reason"] == "source_pause_boundary_unchecked"
    assert result["backup_created"] is False
    assert result["verified"] is False
    assert result["source_unchanged"] is True
    assert fake.actions == ["backup"]
    assert fake.calls[-2:] == [["docker", "container", "inspect", NAME],
                              ["docker", "container", "inspect", "a" * 64]]
    assert result["private_staging_retained"] is True
    assert all(path.is_dir() for path in fake.private_roots)
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("error", [
    FileNotFoundError(SECRET), subprocess.SubprocessError(SECRET),
    UnicodeError(SECRET), RuntimeError(SECRET),
])
def test_subprocess_errors_are_private_and_still_check_source(harness, error, capsys):
    fake, output = harness
    fake.action_error = error
    assert invoke(output) == 2
    result = assert_result(output, passed=False)
    assert result["source_unchanged"] is True
    assert fake.actions == ["backup"]
    assert result["private_staging_retained"] is True
    assert list(output.parent.glob("steuerreport-state-private-*"))
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("after", [None, "backup", "verify", "restore-check"])
@pytest.mark.parametrize("change", ["label", "id", "volume", "state", "env"])
def test_identity_rechecked_before_each_step_and_at_end(harness, after, change):
    fake, output = harness

    def mutate():
        if change == "label":
            fake.source["Config"]["Labels"][ci.SYNTHETIC_LABEL] = "other-run"
        elif change == "id":
            fake.source["Id"] = "f" * 64
        elif change == "volume":
            fake.source["Mounts"][0]["Name"] = "f" * 64
        elif change == "state":
            fake.source["State"]["StartedAt"] = "restarted-then-stopped"
        else:
            fake.source["Config"]["Env"].append("CHANGED=true")

    if after is None:
        def on_inspect(target):
            if len(fake.calls) == 2:
                mutate()
        fake.inspect_hook = on_inspect
    else:
        fake.after_action = lambda action: mutate() if action == after else None
    assert invoke(output) == 2
    result = assert_result(output, passed=False)
    assert result["source_unchanged"] is False
    assert result["reason"] == "final_source_check_failed"
    expected = [] if after is None else ["backup", "verify", "restore-check"][:["backup", "verify", "restore-check"].index(after) + 1]
    assert fake.actions == expected


def test_final_id_inspection_cannot_be_skipped(harness):
    fake, output = harness
    def on_inspect(target):
        if target == "a" * 64:
            raise OSError(SECRET)
    fake.inspect_hook = on_inspect
    assert invoke(output) == 2
    result = assert_result(output, passed=False)
    assert result["reason"] == "final_source_check_failed"
    assert result["source_unchanged"] is False


def test_private_cleanup_failure_cannot_report_success(harness, monkeypatch):
    fake, output = harness
    real_rmtree = ci.shutil.rmtree
    def failed_cleanup(path):
        raise OSError(SECRET)
    monkeypatch.setattr(ci.shutil, "rmtree", failed_cleanup)
    try:
        assert invoke(output) == 2
        result = assert_result(output, passed=False)
        assert result["passed"] is False
        assert result["cleanup"] is False
        assert result["reason"] == "private_cleanup_failed"
        assert SECRET not in (output / "result.json").read_text()
    finally:
        for path in set(fake.private_roots):
            real_rmtree(path)


def test_umask_restored_even_on_failure(harness):
    fake, output = harness
    previous = os.umask(0o022)
    try:
        fake.fail_action = "backup"
        assert invoke(output) == 2
        observed = os.umask(0o022)
        assert observed == 0o022
    finally:
        os.umask(previous)


@pytest.mark.parametrize("action", ["backup", "verify", "restore-check"])
def test_interrupt_retains_private_logs_checks_identity_and_restores_umask(harness, action, capsys):
    fake, output = harness

    def interrupt(current):
        if current == action:
            raise KeyboardInterrupt(SECRET)

    fake.after_action = interrupt
    previous = os.umask(0o022)
    try:
        assert invoke(output) == 2
        observed = os.umask(0o022)
        assert observed == 0o022
    finally:
        os.umask(previous)
    assert fake.actions[-1] == action
    assert fake.calls[-2:] == [["docker", "container", "inspect", NAME],
                              ["docker", "container", "inspect", "a" * 64]]
    assert all(path.is_dir() for path in fake.private_roots)
    result = assert_result(output, passed=False)
    assert result["reason"] == "operator_interrupted"
    assert result["cleanup"] is False
    assert result["private_staging_retained"] is True
    assert fake.processes[-1].signals == [signal.SIGINT]
    assert fake.processes[-1].waits[-1] == ci.OPERATOR_CLEANUP_WAIT_SECONDS
    assert fake.processes[-1].returncode == 130
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("failure", ["timeout", "send-error", "wait-error"])
@pytest.mark.parametrize("action", ["backup", "verify", "restore-check"])
def test_unconfirmed_stop_retains_private_staging_and_never_reports_cleanup(harness, failure, action, capsys):
    fake, output = harness
    def interrupt(current):
        if current == action:
            raise KeyboardInterrupt()
    fake.after_action = interrupt
    if failure == "send-error":
        fake.send_error = PermissionError(SECRET)
    elif failure == "wait-error":
        fake.stop_error = OSError(SECRET)
    else:
        fake.stop_error = subprocess.TimeoutExpired(SECRET, ci.OPERATOR_CLEANUP_WAIT_SECONDS)
    try:
        assert invoke(output) == 2
        result = assert_result(output, passed=False)
        assert result["reason"] == "operator_stop_unconfirmed"
        assert result["cleanup"] is False
        assert result["source_unchanged"] is True
        assert fake.actions[-1] == action
        assert fake.processes[-1].returncode is None
        for private in set(fake.private_roots):
            assert private.is_dir() and output not in private.parents
            assert stat.S_IMODE(private.stat().st_mode) == 0o700
            assert (private / (action + ".stderr")).read_text().endswith(SECRET)
            assert stat.S_IMODE((private / (action + ".stderr")).stat().st_mode) == 0o600
        assert capsys.readouterr() == ("", "")
    finally:
        # The fake child is declared terminal before test-only staging removal.
        fake.processes[-1].returncode = 130
        for private in set(fake.private_roots):
            ci.shutil.rmtree(private)


@pytest.mark.parametrize("error", [KeyboardInterrupt(), OSError(SECRET)])
def test_uncertain_popen_retains_staging_even_without_a_child_handle(harness, monkeypatch, error):
    fake, output = harness
    def uncertain_launch(*args, **kwargs):
        raise error
    monkeypatch.setattr(ci.subprocess, "Popen", uncertain_launch)
    try:
        assert invoke(output) == 2
        result = assert_result(output, passed=False)
        assert result["reason"] == "operator_stop_unconfirmed"
        assert result["cleanup"] is False
        assert result["source_unchanged"] is True
        assert not fake.actions
        private, = output.parent.glob("steuerreport-state-private-*")
        assert private.is_dir()
        assert (private / "backup.stderr").exists()
    finally:
        for private in output.parent.glob("steuerreport-state-private-*"):
            ci.shutil.rmtree(private)


def test_failed_operator_launch_conservatively_retains_staging(harness, monkeypatch):
    _, output = harness
    def unavailable(*args, **kwargs):
        raise FileNotFoundError(SECRET)
    monkeypatch.setattr(ci.subprocess, "Popen", unavailable)
    assert invoke(output) == 2
    result = assert_result(output, passed=False)
    assert result["reason"] == "operator_failed"
    assert result["private_staging_retained"] is True
    assert list(output.parent.glob("steuerreport-state-private-*"))


def test_repeated_signals_during_cleanup_are_deferred(harness, monkeypatch):
    fake, output = harness
    def interrupt(action):
        raise KeyboardInterrupt()
    fake.after_action = interrupt
    original_popen = fake.popen
    def popen(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        wait = process.wait
        def interrupt_cleanup(timeout=None):
            if timeout is not None:
                os.kill(os.getpid(), signal.SIGINT)
                os.kill(os.getpid(), signal.SIGTERM)
            return wait(timeout)
        process.wait = interrupt_cleanup
        return process
    monkeypatch.setattr(ci.subprocess, "Popen", popen)
    assert invoke(output) == 2
    result = assert_result(output, passed=False)
    assert result["reason"] == "operator_interrupted"
    assert fake.processes[-1].signals == [signal.SIGINT]
    assert result["private_staging_retained"] is True
    assert list(output.parent.glob("steuerreport-state-private-*"))


def test_cancelled_operator_exit_zero_is_still_not_success(harness, monkeypatch):
    fake, output = harness
    def interrupt(action):
        raise KeyboardInterrupt()
    fake.after_action = interrupt
    original_popen = fake.popen
    def popen(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        wait = process.wait
        def successful_cleanup(timeout=None):
            code = wait(timeout)
            if timeout is not None:
                process.returncode = 0
                return 0
            return code
        process.wait = successful_cleanup
        return process
    monkeypatch.setattr(ci.subprocess, "Popen", popen)
    assert invoke(output) == 2
    result = assert_result(output, passed=False)
    assert result["reason"] == "operator_interrupted"
    assert result["cleanup"] is False
    assert fake.actions == ["backup"]
    assert fake.processes[-1].returncode == 0


def test_signals_during_final_checks_cannot_publish_success(harness, monkeypatch):
    fake, output = harness
    def interrupt_final(target):
        if target == "a" * 64:
            os.kill(os.getpid(), signal.SIGINT)
            os.kill(os.getpid(), signal.SIGTERM)
    fake.inspect_hook = interrupt_final
    assert invoke(output) == 2
    result = assert_result(output, passed=False)
    assert result["reason"] == "operator_interrupted"
    assert result["cleanup"] is False
    assert result["source_unchanged"] is True
    assert fake.actions == ["backup", "verify", "restore-check"]


@pytest.mark.parametrize("interrupt", [False, True])
def test_staging_removal_requires_terminal_child_and_positive_cleanup(harness, monkeypatch, interrupt):
    fake, output = harness
    original_remove = ci.shutil.rmtree
    removals = []
    if interrupt:
        def after_action(action):
            raise KeyboardInterrupt()
        fake.after_action = after_action
    def remove(private):
        assert fake.processes and all(process.poll() is not None for process in fake.processes)
        removals.append(private)
        original_remove(private)
    monkeypatch.setattr(ci.shutil, "rmtree", remove)
    assert invoke(output) == (2 if interrupt else 0)
    assert len(removals) == (0 if interrupt else 1)
    result = assert_result(output, passed=not interrupt)
    assert result["private_staging_retained"] is interrupt


@pytest.fixture
def synthetic_signal_child(harness, tmp_path, monkeypatch):
    fake, output = harness
    script = tmp_path / "synthetic_signal_child.py"
    events = tmp_path / "child-cleanup-started"
    terminal = tmp_path / "child-cleanup-finished"
    release = tmp_path / "release-child"
    script.write_text('''import os
from pathlib import Path
import signal
import sys
import time

private = Path(os.environ["TMPDIR"])
events = Path(os.environ["CI_SIGNAL_EVENTS"])
terminal = Path(os.environ["CI_SIGNAL_TERMINAL"])
release = Path(os.environ["CI_SIGNAL_RELEASE"])

def cancel(signum, frame):
    events.write_text("cleanup-started")
    if os.environ.get("CI_SIGNAL_STUBBORN") == "1":
        while not release.exists():
            time.sleep(0.01)
    else:
        time.sleep(0.15)
    assert private.is_dir()
    assert (private / "backup.stderr").is_file()
    terminal.write_text("cleanup-finished")
    raise SystemExit(int(os.environ.get("CI_SIGNAL_EXIT", "130")))

signal.signal(signal.SIGINT, cancel)
print("DO-NOT-PUBLISH-PRIVATE-EVIDENCE", file=sys.stderr, flush=True)
(private / "ready").write_text("ready")
while True:
    time.sleep(1)
''', encoding="ascii")
    monkeypatch.setattr(ci, "OPERATOR", script)
    monkeypatch.setenv("CI_SIGNAL_EVENTS", str(events))
    monkeypatch.setenv("CI_SIGNAL_TERMINAL", str(terminal))
    monkeypatch.setenv("CI_SIGNAL_RELEASE", str(release))
    processes = []
    def allowed_popen(command, **kwargs):
        assert command[:2] == [sys.executable, str(script)]
        assert kwargs["start_new_session"] is True
        process = REAL_POPEN(command, **kwargs)
        processes.append(process)
        assert os.getsid(process.pid) == process.pid
        return process
    monkeypatch.setattr(ci.subprocess, "Popen", allowed_popen)
    try:
        yield output, events, terminal, processes
    finally:
        release.touch()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Test-only fallback for this exact synthetic native child PID.
                process.kill()
                process.wait(timeout=5)
        for private in tmp_path.glob("steuerreport-state-private-*"):
            ci.shutil.rmtree(private)


def _signal_when_ready(output, events, parent_signal, *, repeat=False):
    stop = threading.Event()
    errors = []
    def send():
        deadline = time.monotonic() + 5
        while not stop.is_set():
            if list(output.parent.glob("steuerreport-state-private-*/ready")):
                break
            if time.monotonic() >= deadline:
                errors.append("synthetic child readiness timeout")
                break
            stop.wait(0.01)
        if stop.is_set():
            return
        os.kill(os.getpid(), parent_signal)
        if repeat:
            while not stop.is_set() and not events.exists() and time.monotonic() < deadline:
                stop.wait(0.01)
            if not stop.is_set() and events.exists():
                os.kill(os.getpid(), signal.SIGTERM)
    thread = threading.Thread(target=send)
    thread.start()
    return thread, stop, errors


@pytest.mark.parametrize("parent_signal", [signal.SIGINT, signal.SIGTERM])
@pytest.mark.parametrize("exit_code", [1, 130])
def test_real_signal_retains_staging_even_after_synthetic_child_cleanup(
    synthetic_signal_child, monkeypatch, capsys, parent_signal, exit_code,
):
    output, events, terminal, processes = synthetic_signal_child
    monkeypatch.setenv("CI_SIGNAL_EXIT", str(exit_code))
    thread, stop, errors = _signal_when_ready(output, events, parent_signal, repeat=True)
    previous = os.umask(0o022)
    try:
        assert invoke(output) == 2
        observed = os.umask(0o022)
        assert observed == 0o022
    finally:
        stop.set()
        thread.join(timeout=6)
        os.umask(previous)
    assert not thread.is_alive() and not errors
    assert events.exists() and terminal.read_text() == "cleanup-finished"
    assert processes[0].poll() == exit_code
    assert list(output.parent.glob("steuerreport-state-private-*"))
    result = assert_result(output, passed=False)
    assert result["reason"] == "operator_interrupted"
    assert result["cleanup"] is False and result["source_unchanged"] is True
    assert result["private_staging_retained"] is True
    assert capsys.readouterr() == ("", "")


def test_real_cleanup_deadline_retains_staging_until_synthetic_child_ends(synthetic_signal_child, monkeypatch, capsys):
    output, events, terminal, processes = synthetic_signal_child
    monkeypatch.setenv("CI_SIGNAL_STUBBORN", "1")
    monkeypatch.setattr(ci, "OPERATOR_CLEANUP_WAIT_SECONDS", 0.1)
    thread, stop, errors = _signal_when_ready(output, events, signal.SIGINT)
    try:
        assert invoke(output) == 2
    finally:
        stop.set()
        thread.join(timeout=6)
    assert not thread.is_alive() and not errors
    assert events.exists() and not terminal.exists()
    assert processes[0].poll() is None
    private, = output.parent.glob("steuerreport-state-private-*")
    assert private.is_dir() and output not in private.parents
    assert SECRET in (private / "backup.stderr").read_text()
    result = assert_result(output, passed=False)
    assert result["reason"] == "operator_stop_unconfirmed"
    assert result["cleanup"] is False and result["source_unchanged"] is True
    assert capsys.readouterr() == ("", "")
