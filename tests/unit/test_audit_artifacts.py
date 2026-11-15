from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal, Inexact, Rounded, localcontext
import errno
import os
import stat
from threading import Barrier, Event
from types import SimpleNamespace

import pytest

from steuerreport_v2.domain import audit_artifacts as artifacts
from steuerreport_v2.domain.audit_artifacts import (
    ArtifactIntegrityError,
    artifact_lock,
    read_json_object,
    read_regular_bytes,
    write_once,
)


@pytest.mark.parametrize("content", [b"", b"abc", b"x" * 70000])
def test_regular_read_is_exact_and_bounded(tmp_path, content):
    path = tmp_path / "report"
    path.write_bytes(content)
    assert read_regular_bytes(path, len(content)) == content
    if content:
        with pytest.raises(ArtifactIntegrityError, match="too_large"):
            read_regular_bytes(path, len(content) - 1)
    assert path.read_bytes() == content


@pytest.mark.parametrize("limit", [-1, True, False, 1.0, "1", None])
def test_invalid_read_limit_never_opens_file(tmp_path, monkeypatch, limit):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid limit must fail before opening any file")
    monkeypatch.setattr(artifacts.os, "open", forbidden)
    with pytest.raises(ArtifactIntegrityError):
        read_regular_bytes(tmp_path / "absent", limit)


@pytest.mark.parametrize("kind", ["symlink", "dangling_symlink", "fifo", "directory"])
def test_regular_read_rejects_special_targets_nonblocking(tmp_path, monkeypatch, kind):
    path = tmp_path / "target"
    if kind in {"symlink", "dangling_symlink"}:
        source = tmp_path / "source"
        if kind == "symlink":
            source.write_bytes(b"secret")
        path.symlink_to(source)
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        path.mkdir()
    original = artifacts.os.open
    def checked_open(name, flags, *args, **kwargs):
        assert flags & os.O_NOFOLLOW and flags & os.O_NONBLOCK
        return original(name, flags, *args, **kwargs)
    monkeypatch.setattr(artifacts.os, "open", checked_open)
    with pytest.raises(ArtifactIntegrityError):
        read_regular_bytes(path, 20)


def test_missing_file_is_not_created_and_errors_do_not_leak_path(tmp_path):
    path = tmp_path / "private-original-name"
    with pytest.raises(ArtifactIntegrityError) as caught:
        read_regular_bytes(path, 10)
    assert str(tmp_path) not in str(caught.value)
    assert path.name not in str(caught.value)
    assert not path.exists()


def test_read_failure_closes_descriptor_and_redacts_os_error(tmp_path, monkeypatch):
    path = tmp_path / "report"
    path.write_bytes(b"content")
    original_close = artifacts.os.close
    closed = []
    def close(descriptor):
        closed.append(descriptor)
        return original_close(descriptor)
    def fail(*args):
        raise OSError(errno.EIO, "private-secret-source")
    monkeypatch.setattr(artifacts.os, "read", fail)
    monkeypatch.setattr(artifacts.os, "close", close)
    with pytest.raises(ArtifactIntegrityError) as caught:
        read_regular_bytes(path, 10)
    assert len(closed) == 1
    assert "secret" not in str(caught.value)
    with pytest.raises(OSError):
        os.fstat(closed[0])


@pytest.mark.parametrize("change", ["grow", "shrink", "rewrite"])
def test_change_on_open_descriptor_is_rejected(tmp_path, monkeypatch, change):
    path = tmp_path / "report"
    path.write_bytes(b"original")
    original = artifacts.os.read
    called = False
    def changed_read(descriptor, size):
        nonlocal called
        content = original(descriptor, size)
        if not called:
            called = True
            path.write_bytes({"grow": b"original-longer", "shrink": b"short", "rewrite": b"tampered"}[change])
        return content
    monkeypatch.setattr(artifacts.os, "read", changed_read)
    with pytest.raises(ArtifactIntegrityError):
        read_regular_bytes(path, 100)


def test_replacing_path_does_not_redirect_open_descriptor(tmp_path, monkeypatch):
    path = tmp_path / "report"
    replacement = tmp_path / "replacement"
    path.write_bytes(b"original")
    replacement.write_bytes(b"different")
    original = artifacts.os.open
    def replace_after_open(name, flags, *args, **kwargs):
        descriptor = original(name, flags, *args, **kwargs)
        replacement.replace(path)
        return descriptor
    monkeypatch.setattr(artifacts.os, "open", replace_after_open)
    assert read_regular_bytes(path, 8) == b"original"
    assert path.read_bytes() == b"different"


def test_json_preserves_values_without_float_or_model_coercion():
    with localcontext() as context:
        context.prec = 3
        context.traps[Inexact] = context.traps[Rounded] = True
        value = read_json_object(b'{"amount":1.123456789012345678,"id":123,"yes":true,"text":"1.0","none":null}')
    assert value == {"amount": Decimal("1.123456789012345678"), "id": 123,
                     "yes": True, "text": "1.0", "none": None}
    assert type(value["amount"]) is Decimal and type(value["id"]) is int
    assert type(value["yes"]) is bool and type(value["text"]) is str
    assert read_json_object(b'{"text":"NaN"}') == {"text": "NaN"}


@pytest.mark.parametrize("content", [
    b'{"x":1,"x":2}', b'{"nested":{"x":1,"x":2}}', b'{"x":1,"\\u0078":2}',
    b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}', b'{"x":[NaN]}',
    b'[]', b'null', b'true', b'"text"', b'123', b'', b'{',
    b'{"private":"secret",}', b'{"x":"\xff"}', b'\xef\xbb\xbf{}', '{}'.encode("utf-16"),
    b'{"x":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}',
    "{}", bytearray(b'{}'), None,
])
def test_strict_json_rejects_bad_inputs_with_safe_error(content):
    with pytest.raises(ArtifactIntegrityError) as caught:
        read_json_object(content)
    assert str(caught.value) == "artifact_invalid_json_object"


def test_write_once_publishes_full_mode_before_link_and_syncs(tmp_path, monkeypatch):
    target = tmp_path / "report.json"
    original_link, original_sync = artifacts.os.link, artifacts.os.fsync
    events = []
    def sync(descriptor):
        events.append("directory_sync" if stat.S_ISDIR(os.fstat(descriptor).st_mode) else "file_sync")
        return original_sync(descriptor)
    def link(source, destination, **kwargs):
        directory = kwargs["src_dir_fd"]
        assert directory == kwargs["dst_dir_fd"]
        assert kwargs["follow_symlinks"] is False
        assert stat.S_IMODE(os.stat(source, dir_fd=directory).st_mode) == 0o444
        descriptor = os.open(source, os.O_RDONLY, dir_fd=directory)
        try:
            assert os.read(descriptor, 100) == b"complete"
        finally:
            os.close(descriptor)
        assert events == ["file_sync"]
        events.append("link")
        return original_link(source, destination, **kwargs)
    monkeypatch.setattr(artifacts.os, "fsync", sync)
    monkeypatch.setattr(artifacts.os, "link", link)
    write_once(target, b"complete")
    assert events == ["file_sync", "link", "directory_sync"]
    assert target.read_bytes() == b"complete"
    assert list(tmp_path.iterdir()) == [target]


def test_identical_existing_file_is_not_replaced_or_chmodded(tmp_path):
    target = tmp_path / "report"
    write_once(target, b"original", mode=0o400)
    before = target.stat()
    write_once(target, b"original", mode=0o400)
    after = target.stat()
    assert (before.st_ino, before.st_mtime_ns, before.st_ctime_ns, before.st_mode) == (
        after.st_ino, after.st_mtime_ns, after.st_ctime_ns, after.st_mode,
    )
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("replacement", [b"different", b"short", b"a much longer replacement"])
def test_existing_mismatch_is_never_repaired(tmp_path, replacement):
    target = tmp_path / "report"
    write_once(target, b"original")
    inode = target.stat().st_ino
    with pytest.raises(ArtifactIntegrityError):
        write_once(target, replacement)
    assert target.read_bytes() == b"original" and target.stat().st_ino == inode
    assert list(tmp_path.iterdir()) == [target]


def test_existing_wrong_permissions_fail_without_repair(tmp_path):
    target = tmp_path / "report"
    target.write_bytes(b"original")
    target.chmod(0o600)
    with pytest.raises(ArtifactIntegrityError, match="mode_mismatch"):
        write_once(target, b"original")
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert target.read_bytes() == b"original"


@pytest.mark.parametrize("kind", ["symlink", "dangling_symlink", "fifo", "directory"])
def test_write_once_does_not_follow_or_replace_nonregular_existing_target(tmp_path, kind):
    target = tmp_path / "report"
    if kind in {"symlink", "dangling_symlink"}:
        source = tmp_path / "source"
        if kind == "symlink":
            write_once(source, b"original")
        target.symlink_to(source)
    elif kind == "fifo":
        os.mkfifo(target)
    else:
        target.mkdir()
    before = target.lstat()
    with pytest.raises(ArtifactIntegrityError):
        write_once(target, b"original")
    after = target.lstat()
    assert (before.st_ino, before.st_mode) == (after.st_ino, after.st_mode)
    assert not list(tmp_path.glob(".audit-artifact-*"))


@pytest.mark.parametrize("same", [True, False])
def test_concurrent_no_replace_publication_has_one_complete_winner(tmp_path, monkeypatch, same):
    target = tmp_path / "report"
    original = artifacts.os.link
    barrier = Barrier(2)
    def race(*args, **kwargs):
        barrier.wait(timeout=3)
        return original(*args, **kwargs)
    monkeypatch.setattr(artifacts.os, "link", race)
    values = [b"first", b"first" if same else b"other"]
    def publish(value):
        try:
            write_once(target, value)
        except ArtifactIntegrityError:
            return False
        return True
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(publish, values))
    assert sum(outcomes) == (2 if same else 1)
    assert target.read_bytes() in values
    assert stat.S_IMODE(target.stat().st_mode) == 0o444
    assert list(tmp_path.iterdir()) == [target]


@pytest.mark.parametrize("phase", ["write", "chmod", "file_sync", "link", "directory_sync"])
def test_publication_fault_is_reported_without_partial_or_repaired_target(tmp_path, monkeypatch, phase):
    target = tmp_path / "report"
    original_sync = artifacts.os.fsync
    def fail(*args, **kwargs):
        raise OSError(errno.EIO, "private-source-secret")
    def sync(descriptor):
        is_directory = stat.S_ISDIR(os.fstat(descriptor).st_mode)
        if is_directory == (phase == "directory_sync"):
            fail()
        return original_sync(descriptor)
    with monkeypatch.context() as patch:
        if phase in {"file_sync", "directory_sync"}:
            patch.setattr(artifacts.os, "fsync", sync)
        else:
            patch.setattr(artifacts.os, {"write": "write", "chmod": "fchmod", "link": "link"}[phase], fail)
        with pytest.raises(ArtifactIntegrityError) as caught:
            write_once(target, b"complete")
    assert "secret" not in str(caught.value) and str(tmp_path) not in str(caught.value)
    assert not list(tmp_path.glob(".audit-artifact-*"))
    if phase == "directory_sync":
        assert target.read_bytes() == b"complete"
        write_once(target, b"complete")
    else:
        assert not target.exists()


def test_short_writes_are_completed_and_zero_write_is_rejected(tmp_path, monkeypatch):
    original = artifacts.os.write
    with monkeypatch.context() as patch:
        patch.setattr(artifacts.os, "write", lambda fd, value: original(fd, value[:2]))
        write_once(tmp_path / "report", b"complete")
    assert (tmp_path / "report").read_bytes() == b"complete"
    monkeypatch.setattr(artifacts.os, "write", lambda *args: 0)
    with pytest.raises(ArtifactIntegrityError):
        write_once(tmp_path / "failed", b"content")
    assert not (tmp_path / "failed").exists()
    assert not list(tmp_path.glob(".audit-artifact-*"))


def test_colliding_temp_is_not_removed_or_modified(tmp_path, monkeypatch):
    monkeypatch.setattr(artifacts, "uuid4", lambda: SimpleNamespace(hex="collision"))
    sentinel = tmp_path / ".audit-artifact-collision.tmp"
    sentinel.write_bytes(b"unrelated")
    with pytest.raises(ArtifactIntegrityError):
        write_once(tmp_path / "report", b"new")
    assert sentinel.read_bytes() == b"unrelated"
    assert not (tmp_path / "report").exists()


@pytest.mark.parametrize("content,mode", [("text", 0o444), (bytearray(b"x"), 0o444),
                                         (b"x", True), (b"x", -1), (b"x", 0o1000)])
def test_invalid_write_arguments_do_not_create_files(tmp_path, content, mode):
    with pytest.raises(ArtifactIntegrityError):
        write_once(tmp_path / "report", content, mode)
    assert not list(tmp_path.iterdir())


def test_missing_parent_is_not_created(tmp_path):
    parent = tmp_path / "absent"
    with pytest.raises(ArtifactIntegrityError):
        write_once(parent / "report", b"new")
    assert not parent.exists()


def test_lock_is_persistent_regular_and_reusable_after_body_exception(tmp_path):
    path = tmp_path / "artifact.lock"
    problem = ValueError("caller semantic validation failed")
    with pytest.raises(ValueError) as caught:
        with artifact_lock(path):
            assert stat.S_ISREG(path.stat().st_mode)
            inode = path.stat().st_ino
            raise problem
    assert caught.value is problem
    with artifact_lock(path, timeout_seconds=0):
        assert path.stat().st_ino == inode
    assert path.exists() and path.read_bytes() == b""


def test_lock_open_flags_and_caller_os_error_are_preserved(tmp_path, monkeypatch):
    path = tmp_path / "artifact.lock"
    original = artifacts.os.open
    def checked_open(name, flags, *args, **kwargs):
        assert flags & os.O_NOFOLLOW and flags & os.O_NONBLOCK and flags & os.O_CLOEXEC
        return original(name, flags, *args, **kwargs)
    monkeypatch.setattr(artifacts.os, "open", checked_open)
    problem = OSError("caller computation failed")
    with pytest.raises(OSError) as caught:
        with artifact_lock(path):
            raise problem
    assert caught.value is problem
    with artifact_lock(path, timeout_seconds=0):
        pass


def test_lock_acquisition_io_error_closes_file_without_leaking_os_details(tmp_path, monkeypatch):
    original = artifacts.fcntl.flock
    def fail(*args):
        raise OSError(errno.EIO, "private-secret-source")
    with monkeypatch.context() as patch:
        patch.setattr(artifacts.fcntl, "flock", fail)
        with pytest.raises(ArtifactIntegrityError) as caught:
            with artifact_lock(tmp_path / "artifact.lock"):
                pytest.fail("Unexpected lock acquisition")
    assert "secret" not in str(caught.value)
    assert artifacts.fcntl.flock is original
    with artifact_lock(tmp_path / "artifact.lock", timeout_seconds=0):
        pass


def test_aborted_lock_acquisition_closes_descriptor_and_preserves_abort(tmp_path, monkeypatch):
    original = artifacts.os.open
    opened = []
    problem = KeyboardInterrupt("synthetic acquisition abort")
    def track_open(*args, **kwargs):
        descriptor = original(*args, **kwargs)
        opened.append(descriptor)
        return descriptor
    def abort(*args):
        raise problem
    with monkeypatch.context() as patch:
        patch.setattr(artifacts.os, "open", track_open)
        patch.setattr(artifacts.fcntl, "flock", abort)
        with pytest.raises(KeyboardInterrupt) as caught:
            with artifact_lock(tmp_path / "artifact.lock"):
                pytest.fail("Aborted acquisition must not yield")
    assert caught.value is problem and len(opened) == 1
    try:
        with pytest.raises(OSError):
            os.fstat(opened[0])
    finally:
        try:
            os.close(opened[0])
        except OSError:
            pass


@pytest.mark.parametrize("kind", ["symlink", "dangling_symlink", "fifo", "directory"])
def test_lock_rejects_special_files_without_replacing_them(tmp_path, kind):
    path = tmp_path / "artifact.lock"
    if kind in {"symlink", "dangling_symlink"}:
        source = tmp_path / "source"
        if kind == "symlink":
            source.write_bytes(b"original")
        path.symlink_to(source)
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        path.mkdir()
    before = path.lstat()
    with pytest.raises(ArtifactIntegrityError):
        with artifact_lock(path, timeout_seconds=0):
            pytest.fail("Nonregular lock acquired")
    assert path.lstat().st_ino == before.st_ino


@pytest.mark.parametrize("timeout", [-1, True, "1", None, float("nan"), float("inf"), 61, 10 ** 1000])
def test_lock_timeout_is_strict_and_bounded(tmp_path, timeout):
    path = tmp_path / "artifact.lock"
    with pytest.raises(ArtifactIntegrityError):
        with artifact_lock(path, timeout_seconds=timeout):
            pytest.fail("Invalid timeout acquired lock")
    assert not path.exists()


def test_busy_lock_times_out_and_next_writer_can_acquire(tmp_path):
    path = tmp_path / "artifact.lock"
    with artifact_lock(path):
        with pytest.raises(ArtifactIntegrityError, match="timeout"):
            with artifact_lock(path, timeout_seconds=0):
                pytest.fail("Contending descriptor acquired lock")
    with artifact_lock(path, timeout_seconds=0):
        pass


def test_lock_serializes_first_winner_for_cooperating_trio_writers(tmp_path):
    lock, entered = tmp_path / "artifact.lock", Event()
    release, attempting = Event(), Event()
    def first():
        with artifact_lock(lock):
            entered.set()
            assert release.wait(timeout=3)
            for suffix in ("json", "md", "integrity.json"):
                write_once(tmp_path / suffix, b"first-winner")
    def second():
        assert entered.wait(timeout=3)
        attempting.set()
        with artifact_lock(lock, timeout_seconds=2):
            return [read_regular_bytes(tmp_path / suffix, 100)
                    for suffix in ("json", "md", "integrity.json")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        one, two = pool.submit(first), pool.submit(second)
        try:
            assert attempting.wait(timeout=3)
            assert not two.done()
        finally:
            release.set()
        one.result(timeout=3)
        assert two.result(timeout=3) == [b"first-winner"] * 3


def test_parent_symlink_is_explicitly_outside_the_traversal_guarantee(tmp_path):
    directory = tmp_path / "real"
    directory.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(directory, target_is_directory=True)
    write_once(alias / "report", b"content")
    assert read_regular_bytes(alias / "report", 7) == b"content"
