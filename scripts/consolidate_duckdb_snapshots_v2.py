#!/usr/bin/env python3
"""Compact historical DuckDB snapshots in place after semantic verification."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from compact_duckdb_v2 import compact


def _candidates(root: Path, recursive: bool) -> list[Path]:
    pattern = "**/*.duckdb" if recursive else "*.duckdb"
    return sorted(
        (path for path in root.glob(pattern) if path.is_file()),
        key=lambda path: (path.stat().st_mtime_ns, str(path)),
        reverse=True,
    )


def _compact_in_place(source: Path, report_dir: Path) -> dict[str, Any]:
    original_stat = source.stat()
    temporary_compact = source.with_name(
        source.name + f".compact-tmp-{os.getpid()}.duckdb"
    )
    temporary_original = source.with_name(
        source.name + f".original-tmp-{os.getpid()}"
    )
    path_id = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:12]
    report_path = report_dir / (
        f"{source.name}-{original_stat.st_mtime_ns}-{path_id}.json"
    )
    verification = compact(source, temporary_compact, report_path)
    if verification["status"] != "verified":
        raise RuntimeError(f"Compaction was not verified for {source}")

    os.replace(source, temporary_original)
    try:
        os.replace(temporary_compact, source)
        os.chmod(source, original_stat.st_mode & 0o777)
        os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    except Exception:
        source.unlink(missing_ok=True)
        os.replace(temporary_original, source)
        raise

    if source.stat().st_size != verification["target_size_bytes"]:
        source.unlink(missing_ok=True)
        os.replace(temporary_original, source)
        raise RuntimeError(f"Final compact file size mismatch for {source}")
    temporary_original.unlink()
    return {
        "status": "verified_compact_replacement",
        "path": str(source),
        "original_size_bytes": verification["source_size_bytes"],
        "compact_size_bytes": verification["target_size_bytes"],
        "bytes_saved": verification["bytes_saved_after_swap"],
        "original_sha256": verification["source_sha256"],
        "compact_sha256": verification["target_sha256"],
        "verification_report": str(report_path),
        "table_count": len(verification["tables"]),
        "row_count": sum(item["rows"] for item in verification["tables"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", type=Path, nargs="+")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--keep-newest", type=int, default=0)
    parser.add_argument("--min-size-bytes", type=int, default=500 * 1024 * 1024)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--report-dir", type=Path, required=True)
    parser.add_argument("--run-report", type=Path)
    args = parser.parse_args()
    if args.keep_newest < 0:
        parser.error("--keep-newest must be zero or greater")

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

    args.report_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"mode={'execute' if args.execute else 'dry-run'} "
        f"selected={len(selected)} kept_uncompressed={len(kept)}",
        flush=True,
    )
    results: list[dict[str, Any]] = []
    for index, source in enumerate(selected, start=1):
        print(f"[{index}/{len(selected)}] {source.stat().st_size} {source}", flush=True)
        if args.execute:
            result = _compact_in_place(source, args.report_dir.resolve())
            results.append(result)
            print(
                f"  compact={result['compact_size_bytes']} saved={result['bytes_saved']} "
                f"sha256={result['original_sha256']}",
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
        "source_bytes_compacted": sum(item["original_size_bytes"] for item in results),
        "compact_bytes": sum(item["compact_size_bytes"] for item in results),
        "bytes_saved": sum(item["bytes_saved"] for item in results),
    }
    run_report = args.run_report or args.report_dir / "run.json"
    temporary_report = run_report.with_name(run_report.name + f".tmp-{os.getpid()}")
    temporary_report.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temporary_report, run_report)
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
