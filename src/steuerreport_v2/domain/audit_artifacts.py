"""Bounded immutable-file primitives; report/pair semantics belong to the caller.

The caller supplies trusted, existing parent directories and size limits. Parent
symlink traversal is NOT prevented. Final symlinks and non-regular files are
rejected. Publication is atomic per file, not across a JSON/Markdown pair.
No authentication against a writer replacing both data and hash anchors is implied.
"""

from contextlib import contextmanager
from decimal import Decimal
import fcntl
import json
import os
from pathlib import Path
import stat
import time
from uuid import uuid4


class ArtifactIntegrityError(ValueError):
    """Artifact I/O or format validation failed; messages contain no source data."""


def _read_regular(path, max_bytes, *, dir_fd=None, expected_mode=None):
    if type(max_bytes) is not int or max_bytes < 0:
        raise ArtifactIntegrityError("artifact_invalid_limit")
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
    try:
        descriptor = os.open(path, flags, dir_fd=dir_fd)
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise ArtifactIntegrityError("artifact_not_regular")
            if expected_mode is not None and stat.S_IMODE(before.st_mode) != expected_mode:
                raise ArtifactIntegrityError("artifact_mode_mismatch")
            if before.st_size > max_bytes:
                raise ArtifactIntegrityError("artifact_too_large")
            chunks = []
            size = 0
            while True:
                chunk = os.read(descriptor, min(65536, max_bytes + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise ArtifactIntegrityError("artifact_too_large")
                chunks.append(chunk)
            after = os.fstat(descriptor)
            fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_mode")
            if size != before.st_size or any(getattr(before, key) != getattr(after, key) for key in fields):
                raise ArtifactIntegrityError("artifact_changed_during_read")
            return b"".join(chunks)
        finally:
            os.close(descriptor)
    except ArtifactIntegrityError:
        raise
    except (OSError, ValueError):
        raise ArtifactIntegrityError("artifact_read_failed") from None


def read_regular_bytes(path: str | Path, max_bytes: int) -> bytes:
    """Read at most max_bytes from one regular-file descriptor, without repairs.

Linux O_NOFOLLOW/O_NONBLOCK are required. A same-size in-place modification is
checked via descriptor metadata, not guaranteed atomic against hostile writers.
Path replacement does not redirect the already-open descriptor.
"""
    return _read_regular(path, max_bytes)


def read_json_object(content: bytes) -> dict:
    """Parse bounded-by-caller UTF-8 JSON, preserving fractional numbers as Decimal.

Reject duplicate keys at every depth, NaN/Infinity, invalid UTF-8 and non-objects.
No model validation, string/boolean coercion or semantic report checking occurs.
"""
    if type(content) is not bytes:
        raise ArtifactIntegrityError("artifact_invalid_json_object")

    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_key")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError("nonfinite_number")

    try:
        value = json.loads(
            content.decode("utf-8"), object_pairs_hook=unique_keys,
            parse_float=Decimal, parse_constant=reject_constant,
        )
        if not isinstance(value, dict):
            raise ValueError("not_object")
        return value
    except (ValueError, UnicodeError, ArithmeticError, RecursionError):
        raise ArtifactIntegrityError("artifact_invalid_json_object") from None


def write_once(path: str | Path, content: bytes, mode: int = 0o444) -> None:
    """Publish via same-directory temp + fsync + no-replace hardlink.

The parent must already exist. Existing bytes AND permission mode must match;
otherwise fail without modifying the existing target. Temp permissions are set
before publication. Directory fsync errors fail even if publication succeeded;
an identical retry is safe. The caller must handle incomplete multi-file pairs.
"""
    if type(content) is not bytes or type(mode) is not int or not 0 <= mode <= 0o777:
        raise ArtifactIntegrityError("artifact_invalid_write")
    target = Path(path)
    if not target.name or target.name in {".", ".."}:
        raise ArtifactIntegrityError("artifact_invalid_write")
    try:
        directory = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            temporary = ".audit-artifact-" + uuid4().hex + ".tmp"
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600, dir_fd=directory,
            )
            try:
                try:
                    remaining = memoryview(content)
                    while remaining:
                        count = os.write(descriptor, remaining)
                        if count <= 0:
                            raise OSError("short_write")
                        remaining = remaining[count:]
                    os.fchmod(descriptor, mode)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                try:
                    os.link(temporary, target.name, src_dir_fd=directory, dst_dir_fd=directory,
                            follow_symlinks=False)
                except FileExistsError:
                    if _read_regular(target.name, len(content), dir_fd=directory, expected_mode=mode) != content:
                        raise ArtifactIntegrityError("artifact_content_mismatch")
            finally:
                os.unlink(temporary, dir_fd=directory)
            os.fsync(directory)
        finally:
            os.close(directory)
    except ArtifactIntegrityError:
        raise
    except (OSError, ValueError):
        raise ArtifactIntegrityError("artifact_write_failed") from None


@contextmanager
def artifact_lock(path: str | Path, *, timeout_seconds: float = 5.0):
    """Serialize artifact work with a persistent regular-file flock, at most 60s.

The caller supplies a trusted existing parent. Never unlink/replace the lockfile:
all cooperating writers must use the same inode and hold this lock for the whole
publication/read-validation of their pair or trio. No database lock is taken.
"""
    if type(timeout_seconds) not in (int, float) or not 0 <= timeout_seconds <= 60:
        raise ArtifactIntegrityError("artifact_invalid_lock_timeout")
    descriptor = None
    try:
        descriptor = os.open(
            path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, 0o600,
        )
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ArtifactIntegrityError("artifact_lock_not_regular")
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, InterruptedError):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ArtifactIntegrityError("artifact_lock_timeout") from None
                time.sleep(min(0.01, remaining))
    except BaseException as error:
        if descriptor is not None:
            os.close(descriptor)
        if isinstance(error, ArtifactIntegrityError) or not isinstance(error, (OSError, ValueError)):
            raise
        raise ArtifactIntegrityError("artifact_lock_failed") from None
    try:
        yield
    finally:
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)
        except OSError:
            raise ArtifactIntegrityError("artifact_lock_failed") from None
