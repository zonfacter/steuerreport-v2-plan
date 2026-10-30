#!/usr/bin/env python3
"""Check BuildKit's second-build log without printing build output."""
from __future__ import annotations

import re
import sys
from pathlib import Path


def _one_step(lines: list[str], fragment: str) -> str | None:
    matches = []
    for line in lines:
        match = re.match(r"^#(\d+) \[.*\] RUN (.*)$", line)
        if match and fragment in match.group(2):
            matches.append(match.group(1))
    return matches[0] if len(matches) == 1 else None


def valid_cache_evidence(log: str) -> bool:
    lines = log.splitlines()
    dependency = _one_step(lines, "pip install --no-cache-dir --no-deps -r requirements-runtime.lock")
    project = _one_step(lines, "pip install --no-cache-dir --no-deps .")
    if dependency is None or project is None or dependency == project:
        return False
    if not any(line == f"#{dependency} CACHED" for line in lines):
        return False
    if any(line == f"#{project} CACHED" for line in lines):
        return False
    if not any(re.match(rf"^#{project} DONE(?:\s|$)", line) for line in lines):
        return False
    return any(line.startswith(f"#{project} ") and "No broken requirements found." in line for line in lines)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: check_docker_dependency_cache_v2.py BUILD_LOG", file=sys.stderr)
        return 2
    try:
        log = Path(args[0]).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        print("Buildnachweis nicht lesbar.", file=sys.stderr)
        return 1
    if not valid_cache_evidence(log):
        print("Abhaengigkeitscache oder erneuter Projektinstall nicht nachgewiesen.", file=sys.stderr)
        return 1
    print("Abhaengigkeits-Layer wiederverwendet; Projektinstall und pip check erneut ausgefuehrt.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
