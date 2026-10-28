"""Bereinigte lokale Bestandsaufnahme; kein Fetch, Build, Import oder Fachaufruf."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request


def cmd(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=20)
    return result.stdout.strip() if result.returncode == 0 else None


def repo(path):
    prefix = ["git", "-c", "safe.directory=" + path, "-C", path]
    # Ohne strip(): Spalte 1 ist der Indexstatus, Spalte 2 der Worktree.
    result = subprocess.run(prefix + ["status", "--porcelain=v1", "-z", "--no-renames"], capture_output=True, text=True, check=True)
    entries = [entry for entry in result.stdout.split("\0") if entry]
    divergence = cmd(prefix + ["rev-list", "--left-right", "--count", "@{upstream}...HEAD"])
    return {"path": path, "head": cmd(prefix + ["rev-parse", "HEAD"]),
            "branch": cmd(prefix + ["branch", "--show-current"]), "dirty_entries": len(entries),
            "untracked": sum(e.startswith("??") for e in entries),
            "index_changed": sum(e[0] not in " ?" for e in entries),
            "worktree_changed": sum(e[1] not in " ?" for e in entries),
            "behind_local_upstream": int(divergence.split()[0]) if divergence else None,
            "ahead_local_upstream": int(divergence.split()[1]) if divergence else None,
            "all_branch_commits_not_in_cached_remotes": int(cmd(prefix + ["rev-list", "--count", "--branches", "--not", "--remotes"])),
            "upstream": cmd(prefix + ["rev-parse", "--abbrev-ref", "@{upstream}"]),
            "remote_freshness": "nur lokaler Trackingstand; kein Fetch"}


def file_digest(path):
    path = Path(path)
    if not path.is_file():
        return None
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def http(port, path, openapi=False):
    try:
        with urllib.request.urlopen("http://127.0.0.1:" + str(port) + path, timeout=10) as response:
            body = response.read()
            result = {"status": response.status, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
        if openapi:
            spec = json.loads(body)
            result.update({"api_version": spec["info"]["version"], "paths": len(spec["paths"]),
                           "operations": sum(method in {"get", "put", "post", "delete", "patch", "options", "head"}
                                             for item in spec["paths"].values() for method in item)})
        return result
    except Exception as exc:
        return {"error_type": type(exc).__name__}


def parity():
    specs = []
    for port in (8010, 18010):
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/openapi.json", timeout=10) as response:
            specs.append(json.load(response))
    def operations(spec):
        return {(method.upper(), path): value for path, item in spec["paths"].items()
                for method, value in item.items()
                if method in {"get", "put", "post", "delete", "patch", "options", "head"}}
    legacy, live = map(operations, specs)
    common = set(legacy) & set(live)
    # Nur Strukturvergleich: keine Methodenaktivierung oder fachliche Berechnung.
    return {"common_operations": len(common),
            "legacy_only_operations": [" ".join(key) for key in sorted(set(legacy) - set(live))],
            "docker_only_operations": [" ".join(key) for key in sorted(set(live) - set(legacy))],
            "changed_common_operation_objects": sum(legacy[key] != live[key] for key in common),
            "same_component_schemas": specs[0].get("components") == specs[1].get("components")}


def static_assets(port, path):
    import re
    from urllib.parse import urljoin, urlsplit
    base = f"http://127.0.0.1:{port}"
    with urllib.request.urlopen(base + path, timeout=10) as response:
        html = response.read().decode("utf-8")
    assets = re.findall(r'<script[^>]+src="([^"]+)"', html)
    result = []
    for asset in assets:
        url = urljoin(base + path, asset)
        if urlsplit(url).netloc != f"127.0.0.1:{port}":
            result.append({"same_origin": False, "fetched": False})
            continue
        with urllib.request.urlopen(url, timeout=10) as response:
            data = response.read()
        result.append({"same_origin": True, "fetched": True, "sha256": hashlib.sha256(data).hexdigest(),
                       "bytes": len(data), "contains_8010_literal": b":8010" in data,
                       "contains_location_origin": b"location.origin" in data})
    return result


if __name__ == "__main__":
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    live = json.loads(cmd(["docker", "inspect", "steuerreport-v2-lan"]))[0]
    image = json.loads(cmd(["docker", "image", "inspect", live["Image"]]))[0]
    previous = json.loads(cmd(["docker", "inspect", "steuerreport-v2-lan-before-rc32-20261028t083400z"]))[0]
    paths = ["/workspace/steuerreport", "/workspace/steuerreport-v2-plan"]
    result = {"live": {"id": live["Id"], "image_id": live["Image"], "image_reference": live["Config"]["Image"],
                       "state": live["State"]["Status"], "health": live["State"].get("Health", {}).get("Status"),
                       "repo_digests": image["RepoDigests"],
                       "image_labels": {key:image["Config"].get("Labels", {}).get(key) for key in
                                        ("org.opencontainers.image.revision", "org.opencontainers.image.version", "org.opencontainers.image.source")},
                       "ports": live["NetworkSettings"]["Ports"],
                       "mounts": [{k:m.get(k) for k in ("Type", "Name", "Destination", "RW")} for m in live["Mounts"]],
                       "started_at": live["State"]["StartedAt"]},
              "previous_container": {"id":previous["Id"], "state":previous["State"]["Status"],
                                     "finished_at":previous["State"]["FinishedAt"], "image_id":previous["Image"]},
              "repositories": [repo(path) for path in paths],
              "http": {"legacy8000_health": http(8000, "/api/v1/health"),
                       "legacy8000_v2_html": http(8000, "/ui/static/v2/index.html"),
                       "legacy8010_openapi": http(8010, "/openapi.json", True),
                       "docker18010_html": http(18010, "/"),
                       "docker18010_openapi": http(18010, "/openapi.json", True)},
              "files": {path: file_digest(path) for path in (
                  "/workspace/steuerreport-v2-plan/scripts/start_v2.sh",
                  "/workspace/steuerreport/src/tax_engine/ui/static/v2/index.html",
                  "/workspace/steuerreport-v2-plan/frontend/dist/index.html",
                  "/workspace/steuerreport-v2-plan/src/steuerreport_v2/api/app.py")},
              "api_structure_parity": parity(),
              "javascript_assets": {"legacy8000": static_assets(8000, "/ui/static/v2/index.html"),
                                    "docker18010": static_assets(18010, "/")},
              "method_source_comparison": {file: {"legacy_on_disk_sha256": file_digest("/workspace/steuerreport-v2-plan/src/steuerreport_v2/domain/" + file),
                                                  "rc32_checkout_sha256": file_digest(Path(__file__).resolve().parents[3] / "src/steuerreport_v2/domain" / file)}
                                           for file in ("tax.py", "tax_wallet_fifo.py", "fifo_methods.py", "reports.py", "price_lookup.py")}}
    output = Path(args.output)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
