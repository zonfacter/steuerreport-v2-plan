import hashlib
import importlib.util
from pathlib import Path

import pytest


@pytest.mark.parametrize("tampered", [None, "original", "checkpoint", "review"])
def test_independent_probes_are_hash_bound(tmp_path, monkeypatch, capsys, tampered):
    path = Path(__file__).resolve().parents[2] / "scripts/check_reference_baseline_v2.py"
    spec = importlib.util.spec_from_file_location("checkpoint_reference_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = tmp_path / "docs/audit/2026-10-28/acceptance_tests.py"
    checkpoint = tmp_path / "tests/unit/test_price_backfill_checkpoint_acceptance.py"
    review = tmp_path / "tests/unit/test_price_backfill_checkpoint_review.py"
    original.parent.mkdir(parents=True)
    checkpoint.parent.mkdir(parents=True)
    original.write_bytes(b"original synthetic probe\n")
    checkpoint.write_bytes(b"independent synthetic checkpoint\n")
    review.write_bytes(b"independent synthetic review\n")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "EXPECTED", hashlib.sha256(original.read_bytes()).hexdigest())
    monkeypatch.setattr(module, "CHECKPOINT_EXPECTED", hashlib.sha256(checkpoint.read_bytes()).hexdigest())
    monkeypatch.setattr(module, "CHECKPOINT_REVIEW_EXPECTED", hashlib.sha256(review.read_bytes()).hexdigest())
    if tampered:
        {"original": original, "checkpoint": checkpoint, "review": review}[tampered].write_bytes(b"unexpected change\n")
    assert module.main() == (1 if tampered else 0)
    output = capsys.readouterr().out
    if tampered:
        assert "changed" in output and "verified" not in output
    else:
        assert output.count("verified:") == 3
