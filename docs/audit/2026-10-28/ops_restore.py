"""Offline-Restore in eigene Ressourcen; niemals Produktionsdaten mounten.

Aufruf: python3 ops_restore.py --backup ABSOLUT --evidence PRIVAT --run-id NAME
Nur lokal vorhandenes Image des angegebenen Live-Containers, kein Pull/Build.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time


LABEL = "steuerreport.audit.ops.20261028"
HERE = Path(__file__).resolve().parent


def command(args, content=None, timeout=180):
    result = subprocess.run(args, input=content, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        # Docker-/Anwendungsfehler koennen private Inhalte enthalten.
        raise RuntimeError("command_failed:" + args[0] + ":" + str(result.returncode))
    return result.stdout


def inspect(kind, name):
    return json.loads(command(["docker", kind, "inspect", name]))[0]


def write_private(root, name, value):
    target = root / name
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def owned(kind, name, run_id):
    obj = inspect(kind, name)
    labels = obj.get("Labels", {}) if kind == "volume" else obj["Config"].get("Labels", {})
    return (labels or {}).get(LABEL) == run_id


def run(args):
    os.umask(0o077)
    evidence = Path(args.evidence).resolve()
    evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    if evidence.stat().st_mode & 0o077:
        raise RuntimeError("evidence_directory_not_private")
    backup = Path(args.backup).resolve(strict=True)
    if not backup.is_file():
        raise RuntimeError("backup_not_regular_file")
    live = inspect("container", args.live)
    source_image = live["Image"]
    image = args.candidate_image or source_image
    image_meta = inspect("image", image)
    image = image_meta["Id"]
    source_meta = inspect("image", source_image)
    if source_meta.get("Config", {}).get("Labels", {}).get("org.opencontainers.image.revision") != args.revision:
        raise RuntimeError("live_revision_mismatch")
    expected_revision = args.candidate_revision if args.candidate_image else args.revision
    if not expected_revision or image_meta.get("Config", {}).get("Labels", {}).get("org.opencontainers.image.revision") != expected_revision:
        raise RuntimeError("restore_image_revision_mismatch")
    if live["State"]["Status"] != "running":
        raise RuntimeError("live_not_running")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{3,65}", args.run_id):
        raise RuntimeError("invalid_run_id")
    volume = "sr-ops-" + args.run_id + "-data"
    container = "sr-ops-" + args.run_id
    for kind, name in (("volume", volume), ("container", container)):
        check = subprocess.run(["docker", kind, "inspect", name], capture_output=True)
        if check.returncode == 0:
            raise RuntimeError("resource_already_exists")
    # Keine Umgebungsvariablen des Produktivcontainers uebernehmen.
    common = ["--pull=never", "--network", "none", "--read-only", "--cap-drop", "ALL",
              "--security-opt", "no-new-privileges", "--tmpfs", "/tmp:rw,size=256m,mode=1777",
              "--label", LABEL + "=" + args.run_id]
    snapshot = (HERE / "ops_snapshot.py").read_text()
    with backup.open("rb") as handle:
        backup_digest = hashlib.file_digest(handle, "sha256").hexdigest()
    summary = {"image_id": image, "revision": expected_revision, "source_image_id": source_image, "volume": volume,
               "container": container, "backup_sha256": backup_digest,
               "network": "none", "published_ports": {}, "cleanup": False}
    volume_created = False
    container_created = False

    def helper(code):
        return command(["docker", "run", "--rm", "-i", *common, "--user", "10001:10001",
                        "-v", volume + ":/state", "--entrypoint", "python", image, "-"], code)

    def live_snapshot():
        # Ausschliesslich read_only=True und SELECT im bereits laufenden Container.
        return json.loads(command(["docker", "exec", "-i", args.live, "python", "-"], snapshot))

    try:
        source_before = live_snapshot()
        write_private(evidence, "source-before.json", source_before)
        command(["docker", "volume", "create", "--label", LABEL + "=" + args.run_id, volume])
        volume_created = True
        extract = '''import tarfile
from pathlib import Path
with tarfile.open('/backup.tar.gz', 'r:gz') as archive:
    members = archive.getmembers()
    for member in members:
        path = Path(member.name)
        if path.is_absolute() or '..' in path.parts or member.issym() or member.islnk() or member.isdev():
            raise RuntimeError('unsafe_archive_member')
    def safe_filter(member, destination):
        filtered = tarfile.data_filter(member, destination)
        return filtered.replace(uid=member.uid, gid=member.gid)
    archive.extractall('/state', members=members, numeric_owner=True, filter=safe_filter)
print('archive_extracted')
'''
        # Genau eine bekannte Backup-Datei, nicht /root, V1 oder das Live-Volume.
        command(["docker", "run", "--rm", "-i", *common, "--user", "0:0",
                 "--cap-add", "CHOWN", "--cap-add", "FOWNER", "--cap-add", "DAC_OVERRIDE",
                 "-v", volume + ":/state", "-v", str(backup) + ":/backup.tar.gz:ro",
                 "--entrypoint", "python", image, "-"], extract)
        before = json.loads(helper(snapshot))
        write_private(evidence, "restore-before.json", before)
        if not before["database_present"] or not before["tables"]:
            raise RuntimeError("backup_has_no_database")
        for file in ("keys/vault.key", "keys/connector-setup.token", "private_profile.json"):
            if file not in before["files"]:
                raise RuntimeError("backup_missing_required_private_file")
        command(["docker", "create", *common, "--name", container, "--no-healthcheck",
                 "--restart", "no", "-v", volume + ":/state", image])
        container_created = True
        isolated = inspect("container", container)
        if isolated["HostConfig"]["NetworkMode"] != "none" or isolated["HostConfig"].get("PortBindings"):
            raise RuntimeError("isolation_check_failed")
        if {m.get("Name") for m in isolated["Mounts"] if m["Type"] == "volume"} != {volume}:
            raise RuntimeError("unexpected_volume")
        summary["isolation_verified"] = True
        command(["docker", "start", container])
        health_code = "import json,urllib.request; d=json.load(urllib.request.urlopen('http://127.0.0.1:8010/api/v1/health',timeout=3)); print(json.dumps({'app_version':d['data']['app_version'],'database_type':d['data']['database_type']}))"

        def health():
            for attempt in range(30):
                try:
                    return json.loads(command(["docker", "exec", container, "python", "-c", health_code], timeout=10))
                except RuntimeError:
                    time.sleep(1)
            raise RuntimeError("restore_start_timeout")

        summary["health_first_start"] = health()
        # Nur lokale statische Auslieferung: keine UI-JS-Ausfuehrung/Fachabfragen.
        static_code = "import hashlib,json,urllib.request; b=urllib.request.urlopen('http://127.0.0.1:8010/',timeout=3).read(); print(json.dumps({'http':200,'sha256':hashlib.sha256(b).hexdigest(),'contains_root':b'id=\"root\"' in b}))"
        summary["frontend"] = json.loads(command(["docker", "exec", container, "python", "-c", static_code]))
        command(["docker", "stop", "--time", "20", container])
        after_start = json.loads(helper(snapshot))
        write_private(evidence, "restore-after-start.json", after_start)
        command(["docker", "start", container])
        summary["health_restart"] = health()
        command(["docker", "stop", "--time", "20", container])
        after_restart = json.loads(helper(snapshot))
        write_private(evidence, "restore-after-restart.json", after_restart)
        source_after = live_snapshot()
        write_private(evidence, "source-after.json", source_after)
        summary["source_all_tables_unchanged"] = source_before["tables"] == source_after["tables"]
        summary["source_all_non_database_files_unchanged"] = source_before["files"] == source_after["files"]
        summary["restore_all_tables_preserved_start"] = before["tables"] == after_start["tables"]
        summary["restore_all_tables_preserved_restart"] = before["tables"] == after_restart["tables"]
        summary["restore_all_non_database_files_preserved"] = before["files"] == after_start["files"] == after_restart["files"]
        summary["source_db_matches_backup"] = source_before["tables"] == before["tables"]
        source_now = inspect("container", args.live)
        summary["source_container_identity_and_config_unchanged"] = all(
            source_now[key] == live[key] for key in ("Id", "Image", "Config", "HostConfig", "Mounts")) and (
            source_now["State"]["StartedAt"] == live["State"]["StartedAt"] and source_now["State"]["Running"])
        summary["private_key_token_profile_preserved"] = all(
            before["files"][file] == after_start["files"].get(file) == after_restart["files"].get(file)
            for file in ("keys/vault.key", "keys/connector-setup.token", "private_profile.json"))
        changed = {stage: [key for key in set(before["tables"]) | set(value["tables"])
                           if before["tables"].get(key) != value["tables"].get(key)]
                   for stage, value in (("start", after_start), ("restart", after_restart))}
        write_private(evidence, "table-differences.json", changed)
        summary["passed"] = all(summary[key] for key in (
            "source_all_tables_unchanged", "source_all_non_database_files_unchanged",
            "source_container_identity_and_config_unchanged", "restore_all_tables_preserved_start",
            "restore_all_tables_preserved_restart", "restore_all_non_database_files_preserved",
            "private_key_token_profile_preserved")) and all(
                summary[key]["app_version"] == image_meta["Config"]["Labels"]["org.opencontainers.image.version"]
                for key in ("health_first_start", "health_restart"))
    finally:
        if container_created and owned("container", container, args.run_id):
            command(["docker", "rm", "-f", container])
        if volume_created and owned("volume", volume, args.run_id):
            command(["docker", "volume", "rm", volume])
        summary["cleanup"] = True
        write_private(evidence, "restore-result.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    if not summary.get("passed"):
        raise RuntimeError("restore_preservation_check_failed_see_private_evidence")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup", required=True)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--live", default="steuerreport-v2-lan")
    parser.add_argument("--revision", default="1aecfb131d189267a01a6303f5a9b67a5a99efe2")
    parser.add_argument("--candidate-image", help="Nur lokal vorhandenes Pruefimage fuer die isolierte Kopie")
    parser.add_argument("--candidate-revision", help="Erwartetes Commitlabel des Pruefimages")
    run(parser.parse_args())
