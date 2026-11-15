import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from xml.etree import ElementTree

import pytest


ADMISSION_ORIGINAL = (
    b"def test_native_gate_consumes_only_selected_price_and_exact_valuation(env):\n"
    b"    with context:\n"
    b'        current = _data(client.get("/api/v1/prices/as-of-gate", params={"as_of_date": VALUATION}))\n'
    b'        other = _data(client.get("/api/v1/prices/as-of-gate", params={"as_of_date": "2025-06-13T01:00:00.123457Z"}))\n'
    b"    assert current is not other\n"
)
ADMISSION_V2 = (
    b"def test_native_gate_consumes_only_selected_price_and_exact_valuation(env):\n"
    b"    with context:\n"
    b'        current = _data(client.get("/api/v1/prices/as-of-gate", params={"as_of": VALUATION}))\n'
    b'        other = _data(client.get("/api/v1/prices/as-of-gate", params={"as_of": "2025-06-13T01:00:00.123457Z"}))\n'
    b"    assert current is not other\n"
)


@pytest.fixture
def guard(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[2] / "scripts/check_reference_baseline_v2.py"
    spec = importlib.util.spec_from_file_location("checkpoint_reference_guard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original = tmp_path / "docs/audit/2026-10-28/acceptance_tests.py"
    checkpoint = tmp_path / "tests/unit/test_price_backfill_checkpoint_acceptance.py"
    review = tmp_path / "tests/unit/test_price_backfill_checkpoint_review.py"
    temporal = tmp_path / "tests/unit/test_as_of_temporal_evidence_acceptance.py"
    bound = tmp_path / "tests/unit/test_price_evidence_acceptance.py"
    bound_review = tmp_path / "tests/unit/test_price_evidence_review.py"
    recent = tmp_path / "tests/unit/test_historical_price_recent_acceptance.py"
    import_evidence = tmp_path / "tests/unit/test_price_import_evidence_acceptance.py"
    admission_original = tmp_path / "docs/audit/2026-11-15/price_admission_acceptance_original.py"
    admission_v2 = tmp_path / "tests/unit/test_price_admission_acceptance_v2.py"
    admission_identity = tmp_path / "tests/unit/test_price_admission_identity_acceptance.py"
    original.parent.mkdir(parents=True)
    checkpoint.parent.mkdir(parents=True)
    original.write_bytes(b"original synthetic probe\n")
    checkpoint.write_bytes(b"independent synthetic checkpoint\n")
    review.write_bytes(b"independent synthetic review\n")
    temporal.write_bytes(b"independent synthetic time evidence\n")
    bound.write_bytes(b"independent synthetic bound evidence\n")
    bound_review.write_bytes(b"independent synthetic bound review\n")
    recent.write_bytes(b"independent synthetic recent price\n")
    import_evidence.write_bytes(b"independent synthetic import price evidence\n")
    admission_original.parent.mkdir(parents=True)
    admission_original.write_bytes(ADMISSION_ORIGINAL)
    admission_v2.write_bytes(ADMISSION_V2)
    admission_identity.write_bytes(b"synthetic identity reference\n")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "EXPECTED", hashlib.sha256(original.read_bytes()).hexdigest())
    monkeypatch.setattr(module, "CHECKPOINT_EXPECTED", hashlib.sha256(checkpoint.read_bytes()).hexdigest())
    monkeypatch.setattr(module, "CHECKPOINT_REVIEW_EXPECTED", hashlib.sha256(review.read_bytes()).hexdigest())
    monkeypatch.setattr(module, "AS_OF_TIME_EXPECTED", hashlib.sha256(temporal.read_bytes()).hexdigest())
    monkeypatch.setattr(module, "BOUND_PRICE_EVIDENCE_EXPECTED", hashlib.sha256(bound.read_bytes()).hexdigest())
    monkeypatch.setattr(module, "BOUND_PRICE_REVIEW_EXPECTED", hashlib.sha256(bound_review.read_bytes()).hexdigest())
    monkeypatch.setattr(module, "RECENT_PRICE_EXPECTED", hashlib.sha256(recent.read_bytes()).hexdigest())
    monkeypatch.setattr(module, "IMPORT_PRICE_EVIDENCE_EXPECTED", hashlib.sha256(import_evidence.read_bytes()).hexdigest())
    monkeypatch.setattr(module, "PRICE_ADMISSION_ORIGINAL_EXPECTED", hashlib.sha256(admission_original.read_bytes()).hexdigest())
    monkeypatch.setattr(module, "PRICE_ADMISSION_V2_EXPECTED", hashlib.sha256(admission_v2.read_bytes()).hexdigest())
    monkeypatch.setattr(module, "PRICE_ADMISSION_IDENTITY_EXPECTED", hashlib.sha256(admission_identity.read_bytes()).hexdigest())
    files = {"original": original, "checkpoint": checkpoint, "review": review, "temporal": temporal,
             "bound": bound, "bound_review": bound_review, "recent": recent, "import_evidence": import_evidence,
             "admission_original": admission_original, "admission_v2": admission_v2, "admission_identity": admission_identity}
    return module, files


@pytest.mark.parametrize("tampered", [None, "original", "checkpoint", "review", "temporal", "bound", "bound_review", "recent", "import_evidence", "admission_original", "admission_v2", "admission_identity"])
def test_independent_probes_are_hash_bound(guard, capsys, tampered):
    module, files = guard
    if tampered:
        files[tampered].write_bytes(b"unexpected change\n")
    assert module.main() == (1 if tampered else 0)
    output = capsys.readouterr().out
    if tampered:
        assert "changed" in output and "verified" not in output
    else:
        assert output.count("verified:") == 11


@pytest.mark.parametrize("missing", ["admission_original", "admission_v2", "admission_identity"])
def test_missing_admission_reference_fails_closed(guard, capsys, missing):
    module, files = guard
    files[missing].unlink()
    assert module.main() == 1
    output = capsys.readouterr().out
    assert "unavailable" in output and "verified" not in output


@pytest.mark.parametrize("change", ["business_assertion", "one_query_only", "other_cutoff", "extra_edit", "line_endings"])
def test_repinning_v2_hash_cannot_allow_other_harness_changes(guard, monkeypatch, capsys, change):
    module, files = guard
    altered = {
        "business_assertion": ADMISSION_V2.replace(b"assert current is not other", b"assert True"),
        "one_query_only": ADMISSION_V2.replace(b'"as_of": VALUATION', b'"as_of_date": VALUATION'),
        "other_cutoff": ADMISSION_V2.replace(b"123457Z", b"123458Z"),
        "extra_edit": ADMISSION_V2 + b"# extra edit\n",
        "line_endings": ADMISSION_V2.replace(b"\n", b"\r\n"),
    }[change]
    files["admission_v2"].write_bytes(altered)
    monkeypatch.setattr(module, "PRICE_ADMISSION_V2_EXPECTED", hashlib.sha256(altered).hexdigest())
    assert module.main() == 1
    output = capsys.readouterr().out
    assert "independent_price_admission_harness_changed" in output and "verified" not in output


@pytest.mark.parametrize("change", ["missing_test", "duplicate_query", "later_function"])
def test_harness_requires_exactly_two_query_lines_in_last_gate_test(guard, change):
    module, _ = guard
    original = {
        "missing_test": ADMISSION_ORIGINAL.replace(b"test_native_gate_consumes_only_selected_price_and_exact_valuation", b"other_test"),
        "duplicate_query": ADMISSION_ORIGINAL + ADMISSION_ORIGINAL.splitlines(keepends=True)[2],
        "later_function": ADMISSION_ORIGINAL + b"\ndef later_test():\n    pass\n",
    }[change]
    assert module.admission_harness_matches(original, ADMISSION_V2) is False


def _xml(path, count):
    root = ElementTree.Element("testsuites")
    suite = ElementTree.SubElement(root, "testsuite", tests=str(count), failures="0", errors="0", skipped="0")
    for index in range(count):
        ElementTree.SubElement(suite, "testcase", classname="synthetic", name=f"case_{index}")
    ElementTree.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _reports(module, directory):
    for filename, count in module.ADMISSION_RESULTS:
        _xml(directory / filename, count)


def test_original_xml_names_counts_and_bytes_are_verified_read_only(guard, tmp_path, capsys):
    module, _ = guard
    assert module.ADMISSION_RESULTS == (("reference-price-admission-v2.xml", 92), ("reference-price-admission-identity.xml", 3))
    _reports(module, tmp_path)
    before = {name: (tmp_path / name).read_bytes() for name, _ in module.ADMISSION_RESULTS}
    assert module.check_admission_results(tmp_path) == 0
    assert "results_verified:92+3" in capsys.readouterr().out
    assert {name: (tmp_path / name).read_bytes() for name in before} == before


@pytest.mark.parametrize("damage", ["missing_v2", "missing_identity", "malformed", "empty", "wrong_count", "zero_tests",
                                    "failures", "errors", "skipped", "child_only_failure", "aggregate_failure", "nonnumeric",
                                    "multiple_suites", "missing_tests_count", "wrong_root"])
def test_missing_or_nonpassing_original_xml_fails_closed(guard, tmp_path, capsys, damage):
    module, _ = guard
    _reports(module, tmp_path)
    path = tmp_path / module.ADMISSION_RESULTS[0][0]
    if damage in {"missing_v2", "missing_identity"}:
        (tmp_path / module.ADMISSION_RESULTS[int(damage == "missing_identity")][0]).unlink()
    elif damage in {"malformed", "empty"}:
        path.write_bytes(b"<unfinished" if damage == "malformed" else b"")
    elif damage in {"wrong_count", "zero_tests"}:
        _xml(path, 91 if damage == "wrong_count" else 0)
    else:
        tree = ElementTree.parse(path)
        root, suite = tree.getroot(), tree.getroot().find("testsuite")
        if damage in {"failures", "errors", "skipped"}:
            suite.set(damage, "1")
            ElementTree.SubElement(suite.find("testcase"), {"failures": "failure", "errors": "error", "skipped": "skipped"}[damage])
        elif damage == "child_only_failure":
            ElementTree.SubElement(suite.find("testcase"), "failure")
        elif damage == "aggregate_failure":
            root.set("failures", "1")
        elif damage == "nonnumeric":
            suite.set("errors", "invalid")
        elif damage == "multiple_suites":
            ElementTree.SubElement(root, "testsuite", tests="0")
        elif damage == "missing_tests_count":
            del suite.attrib["tests"]
        else:
            root.tag = "not_junit"
        tree.write(path, encoding="utf-8", xml_declaration=True)
    assert module.check_admission_results(tmp_path) == 1
    output = capsys.readouterr().out
    assert "results_invalid:" in output and "verified" not in output


@pytest.mark.parametrize("valid", [False, True])
def test_results_cli_propagates_failure_without_importing_reference_code(guard, tmp_path, valid):
    module, _ = guard
    if valid:
        _reports(module, tmp_path)
    path = Path(__file__).resolve().parents[2] / "scripts/check_reference_baseline_v2.py"
    result = subprocess.run([sys.executable, str(path), "--admission-results", str(tmp_path)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == (0 if valid else 1), result.stderr


def _ci_run():
    text = (Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml").read_text()
    job = text.split("  reference-acceptance:\n", 1)[1].split("\n  backend:", 1)[0]
    step = job.split("      - name: Immutable independent human price admission probes\n", 1)[1].split("\n      - name:", 1)[0]
    assert "continue-on-error:" not in job and "        if:" not in step
    assert "python scripts/check_reference_baseline_v2.py\n" in job
    assert "if: always()" in job and "if-no-files-found: error" in job and "reference-*.xml" in job
    assert "price_admission_acceptance_original.py" not in step
    for name in ("reference-price-admission-v2.xml", "reference-price-admission-identity.xml"):
        assert f"--junitxml={name}" in step
    return "\n".join(line.removeprefix("          ") for line in step.split("        run: |\n", 1)[1].splitlines())


@pytest.mark.parametrize("v2,identity,reports", [(0, 0, 0), (1, 0, 0), (0, 2, 0), (0, 0, 1), (5, 5, 1)])
def test_mandatory_ci_runs_both_suites_and_propagates_each_exit_code(tmp_path, v2, identity, reports):
    fake, log = tmp_path / "python", tmp_path / "calls.jsonl"
    fake.write_text(f"""#!{sys.executable}
import json, os, sys
with open(os.environ['REFERENCE_CALL_LOG'], 'a') as output:
    output.write(json.dumps(sys.argv[1:]) + '\\n')
if sys.argv[1:3] == ['-m', 'pytest']:
    key = 'V2_EXIT' if sys.argv[3].endswith('_v2.py') else 'IDENTITY_EXIT'
else:
    key = 'REPORTS_EXIT'
sys.exit(int(os.environ[key]))
""")
    fake.chmod(0o700)
    env = {**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"], "RUNNER_TEMP": str(tmp_path),
           "REFERENCE_CALL_LOG": str(log), "V2_EXIT": str(v2), "IDENTITY_EXIT": str(identity), "REPORTS_EXIT": str(reports)}
    result = subprocess.run(["bash", "-c", _ci_run()], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == int(bool(v2 or identity or reports)), result.stderr
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert len(calls) == 3
    assert calls[0][2] == "tests/unit/test_price_admission_acceptance_v2.py"
    assert calls[1][2] == "tests/unit/test_price_admission_identity_acceptance.py"
    assert calls[2] == ["scripts/check_reference_baseline_v2.py", "--admission-results", "."]
