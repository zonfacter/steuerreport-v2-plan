import hashlib
import importlib.util
from pathlib import Path
from xml.etree import ElementTree

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def guard(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("audit_reference_guard", ROOT / "scripts/check_reference_baseline_v2.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert len(module.AUDIT_PROBES) == 4
    pins = []
    for filename, _ in module.AUDIT_PROBES:
        path = tmp_path / "tests/unit" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        content = ("synthetic immutable probe: " + filename).encode()
        path.write_bytes(content)
        pins.append((filename, hashlib.sha256(content).hexdigest()))
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "AUDIT_PROBES", tuple(pins))
    return module


def test_all_audit_probes_are_hash_bound_and_never_rewritten(guard):
    before = {name: (guard.ROOT / "tests/unit" / name).read_bytes() for name, _ in guard.AUDIT_PROBES}
    assert guard.check_audit_probes() == 0
    assert before == {name: (guard.ROOT / "tests/unit" / name).read_bytes() for name in before}


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_audit_reference_tampering_fails_closed(guard, index, damage):
    name, _ = guard.AUDIT_PROBES[index]
    path = guard.ROOT / "tests/unit" / name
    if damage == "missing":
        path.unlink()
    else:
        path.write_bytes(b"unexpected changed assertion")
    assert guard.check_audit_probes() == 1


def test_ci_runs_every_audit_reference_in_the_mandatory_job():
    text = (ROOT / ".github/workflows/ci.yml").read_text()
    job = text.split("  reference-acceptance:\n", 1)[1].split("\n  backend:", 1)[0]
    step = job.split("      - name: Immutable independent filing audit probes\n", 1)[1].split("\n      - name:", 1)[0]
    assert "continue-on-error" not in job
    assert "continue-on-error" not in step and "        if:" not in step
    assert "python scripts/check_reference_baseline_v2.py --audit-probes" in step
    assert step.index("--audit-probes") < step.index("-m pytest")
    for name in (
        "test_tax_filing_audit_independent_review.py", "test_tax_filing_audit_identity_review.py",
        "test_tax_filing_audit_additional_review.py", "test_tax_filing_audit_io_review.py",
    ):
        assert "tests/unit/" + name in step
    assert "--junitxml=reference-filing-audit.xml" in step
    assert "python scripts/check_reference_baseline_v2.py --audit-results ." in step


@pytest.mark.parametrize("damage", [None, "missing", "empty", "skipped", "failure", "error", "short", "wrong_count", "duplicate_suite", "bad_root"])
def test_audit_junit_must_contain_all_35_passing_cases(guard, tmp_path, damage):
    path = tmp_path / "reference-filing-audit.xml"
    root = ElementTree.Element("testsuites")
    suite = ElementTree.SubElement(root, "testsuite", tests="35", failures="0", errors="0", skipped="0")
    cases = [ElementTree.SubElement(suite, "testcase", classname="synthetic", name=f"case_{index}") for index in range(35)]
    if damage in {"skipped", "failure", "error"}:
        ElementTree.SubElement(cases[0], damage)
    elif damage == "short":
        suite.remove(cases[-1])
    elif damage == "wrong_count":
        suite.set("tests", "34")
    elif damage == "duplicate_suite":
        ElementTree.SubElement(root, "testsuite", tests="0")
    elif damage == "bad_root":
        root.tag = "not-junit"
    if damage != "missing":
        path.write_bytes(b"" if damage == "empty" else ElementTree.tostring(root))
    before = path.read_bytes() if path.exists() else None
    assert guard.check_audit_results(tmp_path) == (0 if damage is None else 1)
    assert (path.read_bytes() if path.exists() else None) == before
