#!/usr/bin/env python3
"""Archive DuckDB snapshots bit-for-bit with verified Zstandard files."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


CHUNK_SIZE = 8 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _decoded_sha256(zstd: str, archive: Path) -> tuple[str, int]:
    process = subprocess.Popen(
        [zstd, "-q", "-d", "-c", str(archive)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: process.stdout.read(CHUNK_SIZE), b""):
        digest.update(chunk)
        size += len(chunk)
    stderr = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
    return_code = process.wait()
    if return_code:
        raise RuntimeError(f"zstd decode failed for {archive}: {stderr.strip()}")
    return digest.hexdigest(), size


def _archive_one(source: Path, zstd: str, level: int) -> dict[str, Any]:
    source_stat = source.stat()
    archive = source.with_name(source.name + ".zst")
    manifest = archive.with_name(archive.name + ".manifest.json")
    temporary_archive = archive.with_name(archive.name + f".tmp-{os.getpid()}")
    if archive.exists() or manifest.exists():
        raise FileExistsError(
            f"Archive or manifest already exists for {source}; review it before retrying"
        )

    digest = hashlib.sha256()
    process: subprocess.Popen[bytes] | None = None
    try:
        with source.open("rb") as input_handle, temporary_archive.open("xb") as output_handle:
            process = subprocess.Popen(
                [zstd, "-q", f"-{level}", "-T0", "-c"],
                stdin=subprocess.PIPE,
                stdout=output_handle,
                stderr=subprocess.PIPE,
            )
            assert process.stdin is not None
            for chunk in iter(lambda: input_handle.read(CHUNK_SIZE), b""):
                digest.update(chunk)
                process.stdin.write(chunk)
            process.stdin.close()
            stderr = (
                process.stderr.read().decode("utf-8", errors="replace")
                if process.stderr
                else ""
            )
            return_code = process.wait()
            if return_code:
                raise RuntimeError(
                    f"zstd compression failed for {source}: {stderr.strip()}"
                )
            output_handle.flush()
            os.fsync(output_handle.fileno())
        source_stat_after = source.stat()
        if (
            source_stat.st_size != source_stat_after.st_size
            or source_stat.st_mtime_ns != source_stat_after.st_mtime_ns
        ):
            raise RuntimeError(f"Source changed during archive creation: {source}")

        os.replace(temporary_archive, archive)
        _fsync_file(archive)
        source_sha256 = digest.hexdigest()
        decoded_sha256, decoded_size = _decoded_sha256(zstd, archive)
        if decoded_sha256 != source_sha256 or decoded_size != source_stat.st_size:
            raise RuntimeError(f"Decoded archive does not match source: {source}")

        result = {
            "status": "verified_and_source_removed",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "source_path": str(source),
            "source_size_bytes": source_stat.st_size,
            "source_sha256": source_sha256,
            "source_mtime_ns": source_stat.st_mtime_ns,
            "source_mode": oct(source_stat.st_mode & 0o777),
            "archive_path": str(archive),
            "archive_size_bytes": archive.stat().st_size,
            "archive_sha256": _sha256(archive),
            "decoded_size_bytes": decoded_size,
            "decoded_sha256": decoded_sha256,
            "bytes_saved": source_stat.st_size - archive.stat().st_size,
            "restore_command": f"zstd -d --stdout {archive} > {source}",
        }
        temporary_manifest = manifest.with_name(manifest.name + f".tmp-{os.getpid()}")
        temporary_manifest.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        _fsync_file(temporary_manifest)
        os.replace(temporary_manifest, manifest)
        source.unlink()
        return result
    except Exception:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait()
        temporary_archive.unlink(missing_ok=True)
        raise


def _candidates(root: Path, recursive: bool) -> list[Path]:
    pattern = "**/*.duckdb" if recursive else "*.duckdb"
    return sorted(
        (path for path in root.glob(pattern) if path.is_file()),
        key=lambda path: (path.stat().st_mtime_ns, str(path)),
        reverse=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", type=Path, nargs="+")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--keep-newest", type=int, default=0)
    parser.add_argument("--min-size-bytes", type=int, default=100 * 1024 * 1024)
    parser.add_argument("--level", type=int, default=6, choices=range(1, 20))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if args.keep_newest < 0:
        parser.error("--keep-newest must be zero or greater")

    zstd = shutil.which("zstd")
    if args.execute and not zstd:
        raise RuntimeError("zstd is required for --execute")

    selected: list[Path] = []
    kept: list[Path] = []
    for root in args.roots:
        root = root.resolve()
        if not root.is_dir():
            raise NotADirectoryError(root)
        candidates = _candidates(root, args.recursive)
        kept.extend(candidates[: args.keep_newest])
        selected.extend(
            path
            for path in candidates[args.keep_newest :]
            if path.stat().st_size >= args.min_size_bytes
        )

    print(
        f"mode={'execute' if args.execute else 'dry-run'} "
        f"selected={len(selected)} kept_uncompressed={len(kept)}",
        flush=True,
    )
    results: list[dict[str, Any]] = []
    for index, source in enumerate(selected, start=1):
        size = source.stat().st_size
        print(f"[{index}/{len(selected)}] {size} {source}", flush=True)
        if args.execute:
            assert zstd is not None
            result = _archive_one(source, zstd, args.level)
            results.append(result)
            print(
                f"  archived={result['archive_size_bytes']} "
                f"saved={result['bytes_saved']} sha256={result['source_sha256']}",
                flush=True,
            )

    report = {
        "status": "completed" if args.execute else "dry_run",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "roots": [str(root.resolve()) for root in args.roots],
        "recursive": args.recursive,
        "keep_newest": args.keep_newest,
        "min_size_bytes": args.min_size_bytes,
        "selected_count": len(selected),
        "kept_uncompressed": [str(path) for path in kept],
        "selected": [str(path) for path in selected],
        "results": results,
        "source_bytes_archived": sum(item["source_size_bytes"] for item in results),
        "archive_bytes": sum(item["archive_size_bytes"] for item in results),
        "bytes_saved": sum(item["bytes_saved"] for item in results),
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        temporary_report = args.report.with_name(args.report.name + f".tmp-{os.getpid()}")
        temporary_report.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(temporary_report, args.report)
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
