"""Ressourcenidentitaet und unklare Docker-Erstellung; ausschliesslich Mocks."""
import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def ops(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "scripts/docker_state_v2.py"
    spec = importlib.util.spec_from_file_location("state_identity_subject", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "RESTORE_CLEANUP_ATTEMPTS", 3)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    return module


def owned(ops, kind="container"):
    labels = {ops.RESOURCE_LABEL: "synthetic-run",
              getattr(ops, "OWNER_LABEL", "steuerreport.ops.owner"): getattr(ops, "OWNER_NONCE", "new-owner")}
    return {"Id": "a" * 64, "Config": {"Labels": labels}} if kind == "container" else {"Labels": labels}


def test_container_cleanup_uses_inspected_immutable_id_not_reassignable_name(ops, monkeypatch):
    removed = []
    obj = owned(ops)
    def inspect(kind, reference):
        if reference == "synthetic-name":
            return obj  # Name kann nach dieser Antwort auf einen fremden Container zeigen.
        assert reference == obj["Id"]
        return None if removed else obj
    monkeypatch.setattr(ops, "_inspect_optional", inspect)
    monkeypatch.setattr(ops, "_docker", lambda cmd, **kw: removed.append(cmd) or "")
    assert ops._cleanup_restore_resource("container", "synthetic-name", "synthetic-run") is None
    assert removed == [["rm", "--force", obj["Id"]]]


@pytest.mark.parametrize("kind", ["container", "volume"])
def test_initial_missing_after_unknown_create_is_not_cleanup_confirmation(ops, monkeypatch, kind):
    reads = []
    monkeypatch.setattr(ops, "_inspect_optional", lambda *a: reads.append(a) or None)
    assert ops._cleanup_restore_resource(kind, "unknown-create", "synthetic-run") == kind + "_create_state_unknown"
    assert len(reads) == 3


@pytest.mark.parametrize("kind", ["container", "volume"])
def test_late_created_owned_resource_is_found_and_cleaned(ops, monkeypatch, kind):
    reads, commands = [], []
    obj = owned(ops, kind)
    def inspect(*args):
        reads.append(args)
        return None if len(reads) == 1 or commands else obj
    monkeypatch.setattr(ops, "_inspect_optional", inspect)
    monkeypatch.setattr(ops, "_docker", lambda cmd, **kw: commands.append(cmd) or "")
    assert ops._cleanup_restore_resource(kind, "late-create", "synthetic-run") is None
    assert len(commands) == 1


@pytest.mark.parametrize("kind", ["container", "volume"])
def test_matching_run_label_without_this_operation_nonce_never_deleted(ops, monkeypatch, kind):
    obj = owned(ops, kind)
    labels = obj["Config"]["Labels"] if kind == "container" else obj["Labels"]
    labels[getattr(ops, "OWNER_LABEL", "steuerreport.ops.owner")] = "another-operation"
    commands = []
    monkeypatch.setattr(ops, "_inspect_optional", lambda *a: obj)
    monkeypatch.setattr(ops, "_docker", lambda cmd, **kw: commands.append(cmd) or "")
    assert ops._cleanup_restore_resource(kind, "same-run-id", "synthetic-run") == kind + "_ownership_unverified"
    assert commands == []


def test_volume_namespace_not_reused_for_same_human_run_id(ops, monkeypatch):
    names = []
    monkeypatch.setattr(ops, "_inspect_optional", lambda *a: None)
    monkeypatch.setattr(ops, "_create_restore_volume", lambda name, *a: names.append(name))
    monkeypatch.setattr(ops, "_resource_state", lambda *a: "owned")
    for _ in range(2):
        ops._new_restore_volumes([{"id": "m000", "target": "/state"}], "synthetic-run")
    assert len(set(names)) == 2


def test_confirmed_volume_creation_can_be_known_missing(ops, monkeypatch):
    monkeypatch.setattr(ops, "_docker", lambda cmd, **kw: cmd[-1])
    monkeypatch.setattr(ops, "_inspect_optional", lambda *a: None)
    ops._create_restore_volume("confirmed-volume", "synthetic-run")
    assert ops._cleanup_restore_resource("volume", "confirmed-volume", "synthetic-run") is None
