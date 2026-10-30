#!/usr/bin/env python3
"""Read-only, aggregate storage diagnostics for a Steuerreport V2 operator.

The command reports filesystem capacity for explicitly selected paths and the
non-verbose aggregate from ``docker system df``. It does not enumerate files,
container names, image names, volume names, or perform cleanup operations.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Sequence


DOCKER_DF_FORMAT = "{{.Type}}|{{.TotalCount}}|{{.Active}}|{{.Size}}|{{.Reclaimable}}"
_SIZE = r"\d+(?:\.\d+)?\s*(?:B|kB|KB|MB|GB|TB|PB|KiB|MiB|GiB|TiB|PiB)"
_SIZE_RE = re.compile(rf"^{_SIZE}$")
_RECLAIMABLE_RE = re.compile(rf"^{_SIZE}(?:\s+\(\d+(?:\.\d+)?%\))?$")
_RESOURCE_TYPES = {
    "Images": "images",
    "Containers": "containers",
    "Local Volumes": "local_volumes",
    "Build Cache": "build_cache",
}

DockerRunner = Callable[..., subprocess.CompletedProcess[str]]


def _filesystem_capacity(label: str, path: Path) -> dict[str, Any]:
    try:
        stats = os.statvfs(path)
    except PermissionError:
        return {"label": label, "status": "unavailable", "reason": "permission_denied"}
    except FileNotFoundError:
        return {"label": label, "status": "unavailable", "reason": "path_not_found"}
    except (OSError, ValueError):
        return {"label": label, "status": "unavailable", "reason": "filesystem_query_failed"}

    block_size = stats.f_frsize or stats.f_bsize
    if block_size <= 0 or stats.f_blocks < 0 or stats.f_bfree < 0 or stats.f_bavail < 0:
        return {"label": label, "status": "unavailable", "reason": "filesystem_stats_invalid"}

    total = stats.f_blocks * block_size
    free = stats.f_bfree * block_size
    available = stats.f_bavail * block_size
    if free > total or available > total:
        return {"label": label, "status": "unavailable", "reason": "filesystem_stats_invalid"}
    return {
        "label": label,
        "status": "available",
        "basis": "statvfs",
        "total_bytes": total,
        "used_bytes": total - free,
        "free_bytes": free,
        "available_to_unprivileged_bytes": available,
    }


def _parse_docker_summary(output: str) -> list[dict[str, Any]] | None:
    resources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for line in output.splitlines():
        if not line:
            continue
        fields = line.split("|")
        if len(fields) != 5:
            return None
        docker_type, total_text, active_text, size_text, reclaimable_text = fields
        resource_type = _RESOURCE_TYPES.get(docker_type)
        if resource_type is None or resource_type in seen:
            return None
        total_text = total_text.strip()
        if not total_text.isdecimal():
            return None
        active_count: int | None
        if active_text.strip().isdecimal():
            active_count = int(active_text)
        elif active_text.strip().lower() in {"n/a", "-"}:
            active_count = None
        else:
            return None
        if active_count is not None and active_count > int(total_text):
            return None
        if not _SIZE_RE.fullmatch(size_text.strip()):
            return None
        if not _RECLAIMABLE_RE.fullmatch(reclaimable_text.strip()):
            return None

        resources.append(
            {
                "type": resource_type,
                "total_count": int(total_text),
                "active_count": active_count,
                "docker_reported_size": size_text.strip(),
                "docker_reported_reclaimable": reclaimable_text.strip(),
                "reclaimable_is_safe_to_delete": False,
            }
        )
        seen.add(resource_type)

    return resources or None


def _docker_summary(runner: DockerRunner) -> dict[str, Any]:
    command = ["docker", "system", "df", "--format", DOCKER_DF_FORMAT]
    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except FileNotFoundError:
        return {"status": "unavailable", "reason": "docker_cli_not_found", "resources": []}
    except subprocess.TimeoutExpired:
        return {"status": "unavailable", "reason": "docker_command_timeout", "resources": []}
    except OSError:
        return {"status": "unavailable", "reason": "docker_command_unavailable", "resources": []}

    if result.returncode != 0:
        return {"status": "unavailable", "reason": "docker_command_failed", "resources": []}

    resources = _parse_docker_summary(result.stdout or "")
    if resources is None:
        return {"status": "unavailable", "reason": "docker_output_unrecognized", "resources": []}
    return {
        "status": "available",
        "basis": "docker system df aggregate; Docker-reported human-readable sizes",
        "resources": resources,
        "reclaimable_note": "Docker-Schaetzung, keine Aussage zur sicheren Loeschbarkeit oder Rollback-Abhaengigkeit.",
    }


def collect_inventory(
    paths: Sequence[tuple[str, Path]],
    docker_data_path: Path | None,
    runner: DockerRunner,
) -> dict[str, Any]:
    filesystems = [
        _filesystem_capacity(label, path) for label, path in paths
    ]
    if docker_data_path is not None:
        filesystems.append(_filesystem_capacity("docker_data_path", docker_data_path))
    docker = _docker_summary(runner)
    complete = docker["status"] == "available" and all(
        filesystem["status"] == "available" for filesystem in filesystems
    )
    return {
        "status": "complete" if complete else "partial",
        "mode": "read_only",
        "filesystems": filesystems,
        "docker": docker,
        "scope_note": (
            "Keine Dateinamen oder Docker-Ressourcennamen werden inventarisiert. "
            "Es werden keine Bereinigungs- oder Schreibaktionen ausgefuehrt."
        ),
    }


def _human_bytes(value: int) -> str:
    amount = float(value)
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    for unit in units:
        if amount < 1024 or unit == units[-1]:
            return f"{amount:.1f} {unit}"
        amount /= 1024
    return f"{value} B"


def _render_text(report: dict[str, Any]) -> str:
    lines = ["Speicherdiagnose (nur lesend)", f"Status: {report['status']}", "Dateisysteme:"]
    for filesystem in report["filesystems"]:
        label = filesystem["label"]
        if filesystem["status"] != "available":
            lines.append(f"  {label}: nicht verfuegbar ({filesystem['reason']})")
            continue
        lines.append(
            f"  {label}: frei {_human_bytes(filesystem['free_bytes'])}; "
            f"verfuegbar {_human_bytes(filesystem['available_to_unprivileged_bytes'])}; "
            f"belegt {_human_bytes(filesystem['used_bytes'])} von {_human_bytes(filesystem['total_bytes'])}"
        )

    docker = report["docker"]
    lines.append("Docker:")
    if docker["status"] != "available":
        lines.append(f"  Zusammenfassung nicht verfuegbar ({docker['reason']})")
    else:
        for resource in docker["resources"]:
            active = "unbekannt" if resource["active_count"] is None else str(resource["active_count"])
            lines.append(
                f"  {resource['type']}: gesamt {resource['total_count']}, aktiv {active}; "
                f"Docker meldet {resource['docker_reported_size']}, "
                f"reclaimable {resource['docker_reported_reclaimable']}"
            )
        lines.append(f"  Hinweis: {docker['reclaimable_note']}")
    lines.append(report["scope_note"])
    return "\n".join(lines)


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        action="append",
        dest="paths",
        help="zusaetzliches Dateisystem pruefen; der Pfad wird nicht ausgegeben",
    )
    parser.add_argument(
        "--docker-data-path",
        help="bekannten lokalen Docker-Datenpfad pruefen; nicht fuer entfernte Daemons",
    )
    parser.add_argument("--json", action="store_true", help="strukturierte Ausgabe")
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    docker_runner: DockerRunner | None = None,
) -> int:
    args = _arguments(argv)
    if args.paths:
        paths = [(f"requested_path_{index}", Path(value)) for index, value in enumerate(args.paths, 1)]
    else:
        paths = [("current_directory", Path.cwd())]
    docker_data_path = Path(args.docker_data_path) if args.docker_data_path else None
    report = collect_inventory(paths, docker_data_path, docker_runner or subprocess.run)
    if args.json:
        print(json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True))
    else:
        print(_render_text(report))
    return 0 if report["status"] == "complete" else 1


if __name__ == "__main__":
    raise SystemExit(main())
