"""Prueft die unveraenderte unabhaengige Ausgangsprobe vor dem CI-Gate."""
import argparse
import hashlib
from pathlib import Path
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = "09f674b350a9a83943df8980bbceafd88821ee1400e03b5b22ea1ee0f8cd6bfb"
CHECKPOINT_EXPECTED = "68beedb2b00d9b87c55b03f0c6da8a89c87a8e78529467fb34562072dc2b5f48"
CHECKPOINT_REVIEW_EXPECTED = "db10e6259ba1953792a66eb7a8396ccc4841810bf0818264b2dd6fd8670ac337"
AS_OF_TIME_EXPECTED = "06d4d1115cf1f5dfa1ff240d37a87c23709685e151d7df7902432a3fb5a3fdc8"
BOUND_PRICE_EVIDENCE_EXPECTED = "da94ef9bc2c4b3031d640dfa12d56242ae286ba3b05d501f64e77451ff1bb325"
BOUND_PRICE_REVIEW_EXPECTED = "841ab5bb008e8e435087118dd0c97df940090eaa9fccaf062dd555719e7d252d"
RECENT_PRICE_EXPECTED = "d36acb12257d601c19d896d016194caf68c34b7f7200f77edb8b32fec0588f85"
IMPORT_PRICE_EVIDENCE_EXPECTED = "164300f4355d8214fd90abb0bf9a79f5529b097687c8e63b93282f2ce6490adf"
PRICE_ADMISSION_ORIGINAL_EXPECTED = "3b4223cdd6c1f7a34b84f1922a3311cf1b7784b497585abbd4996e299a7b14e9"
PRICE_ADMISSION_V2_EXPECTED = "50efa1a9df24286e7fddc4e5d095542aadab0bfbfe0fe11dfcc79e89dbf95851"
PRICE_ADMISSION_IDENTITY_EXPECTED = "c41bce4dec09e2886e5830518ce419e2b65caf32924df9a0ed69a00f2b3bb483"
ADMISSION_RESULTS = (
    ("reference-price-admission-v2.xml", 92),
    ("reference-price-admission-identity.xml", 3),
)
AUDIT_PROBES = (
    ("test_tax_filing_audit_independent_review.py", "df62c3379bf5464abe7c3fef6f052b629715bc1e7d072c5c0e7469890c7f31bf"),
    ("test_tax_filing_audit_identity_review.py", "7f500d2d8a253819c70a7837016e54c565bd70d97d29acbbeacaf2f9399f2142"),
    ("test_tax_filing_audit_additional_review.py", "1d6255f969e8b9e90275caa80ef4a8516e10693deff55680fb5a75e82a4a8ff9"),
    ("test_tax_filing_audit_io_review.py", "26cf95f5758fa3972b0ab6a4e598bcc7687564baf7cb9cb02dff722682af648e"),
)
AUDIT_RESULTS = (("reference-filing-audit.xml", 35),)
ADMISSION_HARNESS_LINES = (
    b'        current = _data(client.get("/api/v1/prices/as-of-gate", params={"as_of_date": VALUATION}))\n',
    b'        other = _data(client.get("/api/v1/prices/as-of-gate", params={"as_of_date": "2025-06-13T01:00:00.123457Z"}))\n',
)


def admission_harness_matches(original: bytes, corrected: bytes) -> bool:
    """Only the two agreed query lines in the last gate test may differ."""
    marker = b"def test_native_gate_consumes_only_selected_price_and_exact_valuation(env):\n"
    if original.count(marker) != 1:
        return False
    head, _, tail = original.partition(marker)
    if b"\ndef " in tail:
        return False
    for line in ADMISSION_HARNESS_LINES:
        if line in head or tail.count(line) != 1:
            return False
        tail = tail.replace(line, line.replace(b'"as_of_date"', b'"as_of"'), 1)
    return head + marker + tail == corrected


def _check_results(directory: Path, expected_results, prefix: str) -> int:
    for filename, count in expected_results:
        try:
            root = ElementTree.parse(directory / filename).getroot()
            suites = list(root.iter("testsuite"))
            if root.tag not in {"testsuite", "testsuites"} or len(suites) != 1:
                raise ValueError("unexpected_suite")
            cases = list(root.iter("testcase"))
            if len(cases) != count or int(suites[0].get("tests", "-1")) != count:
                raise ValueError("unexpected_test_count")
            for summary in (root, suites[0]):
                if any(int(summary.get(field, "0")) != 0 for field in ("failures", "errors", "skipped")):
                    raise ValueError("nonzero_result")
            if any(list(root.iter(tag)) for tag in ("failure", "error", "skipped")):
                raise ValueError("nonpassing_case")
        except (OSError, ElementTree.ParseError, ValueError):
            print(prefix + "_results_invalid:" + filename)
            return 1
    print(prefix + "_results_verified:" + "+".join(str(count) for _, count in expected_results))
    return 0


def check_admission_results(directory: Path) -> int:
    return _check_results(directory, ADMISSION_RESULTS, "independent_price_admission")


def check_audit_results(directory: Path) -> int:
    return _check_results(directory, AUDIT_RESULTS, "independent_filing_audit")


def check_audit_probes() -> int:
    for filename, expected in AUDIT_PROBES:
        try:
            content = (ROOT / "tests/unit" / filename).read_bytes()
        except OSError:
            print("independent_audit_probe_unavailable:" + filename)
            return 1
        if hashlib.sha256(content).hexdigest() != expected:
            print("independent_audit_probe_changed:" + filename)
            return 1
    print("independent_audit_probes_verified:" + str(len(AUDIT_PROBES)))
    return 0


def main() -> int:
    probe = ROOT / "docs/audit/2026-10-28/acceptance_tests.py"
    actual = hashlib.sha256(probe.read_bytes()).hexdigest()
    if actual != EXPECTED:
        print("independent_reference_baseline_changed")
        return 1
    checkpoint_probe = ROOT / "tests/unit/test_price_backfill_checkpoint_acceptance.py"
    checkpoint_actual = hashlib.sha256(checkpoint_probe.read_bytes()).hexdigest()
    if checkpoint_actual != CHECKPOINT_EXPECTED:
        print("independent_checkpoint_baseline_changed")
        return 1
    review_probe = ROOT / "tests/unit/test_price_backfill_checkpoint_review.py"
    review_actual = hashlib.sha256(review_probe.read_bytes()).hexdigest()
    if review_actual != CHECKPOINT_REVIEW_EXPECTED:
        print("independent_checkpoint_review_changed")
        return 1
    temporal_probe = ROOT / "tests/unit/test_as_of_temporal_evidence_acceptance.py"
    temporal_actual = hashlib.sha256(temporal_probe.read_bytes()).hexdigest()
    if temporal_actual != AS_OF_TIME_EXPECTED:
        print("independent_as_of_time_baseline_changed")
        return 1
    bound_probe = ROOT / "tests/unit/test_price_evidence_acceptance.py"
    bound_actual = hashlib.sha256(bound_probe.read_bytes()).hexdigest()
    if bound_actual != BOUND_PRICE_EVIDENCE_EXPECTED:
        print("independent_bound_price_evidence_changed")
        return 1
    bound_review = ROOT / "tests/unit/test_price_evidence_review.py"
    bound_review_actual = hashlib.sha256(bound_review.read_bytes()).hexdigest()
    if bound_review_actual != BOUND_PRICE_REVIEW_EXPECTED:
        print("independent_bound_price_review_changed")
        return 1
    recent_probe = ROOT / "tests/unit/test_historical_price_recent_acceptance.py"
    recent_actual = hashlib.sha256(recent_probe.read_bytes()).hexdigest()
    if recent_actual != RECENT_PRICE_EXPECTED:
        print("independent_recent_price_changed")
        return 1
    import_probe = ROOT / "tests/unit/test_price_import_evidence_acceptance.py"
    import_actual = hashlib.sha256(import_probe.read_bytes()).hexdigest()
    if import_actual != IMPORT_PRICE_EVIDENCE_EXPECTED:
        print("independent_import_price_evidence_changed")
        return 1
    admission_files = (
        ("docs/audit/2026-11-15/price_admission_acceptance_original.py", PRICE_ADMISSION_ORIGINAL_EXPECTED, "original"),
        ("tests/unit/test_price_admission_acceptance_v2.py", PRICE_ADMISSION_V2_EXPECTED, "v2"),
        ("tests/unit/test_price_admission_identity_acceptance.py", PRICE_ADMISSION_IDENTITY_EXPECTED, "identity"),
    )
    admission_bytes = []
    for relative, expected, name in admission_files:
        try:
            content = (ROOT / relative).read_bytes()
        except OSError:
            print("independent_price_admission_" + name + "_unavailable")
            return 1
        if hashlib.sha256(content).hexdigest() != expected:
            print("independent_price_admission_" + name + "_changed")
            return 1
        admission_bytes.append(content)
    if not admission_harness_matches(admission_bytes[0], admission_bytes[1]):
        print("independent_price_admission_harness_changed")
        return 1
    print("independent_reference_baseline_verified:" + actual)
    print("independent_checkpoint_baseline_verified:" + checkpoint_actual)
    print("independent_checkpoint_review_verified:" + review_actual)
    print("independent_as_of_time_baseline_verified:" + temporal_actual)
    print("independent_bound_price_evidence_verified:" + bound_actual)
    print("independent_bound_price_review_verified:" + bound_review_actual)
    print("independent_recent_price_verified:" + recent_actual)
    print("independent_import_price_evidence_verified:" + import_actual)
    print("independent_price_admission_original_verified:" + PRICE_ADMISSION_ORIGINAL_EXPECTED)
    print("independent_price_admission_v2_verified:" + PRICE_ADMISSION_V2_EXPECTED)
    print("independent_price_admission_identity_verified:" + PRICE_ADMISSION_IDENTITY_EXPECTED)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--admission-results", type=Path, help="Pruefe beide unveraenderten Admission-JUnit-Dateien.")
    mode.add_argument("--audit-probes", action="store_true", help="Pruefe die unveraenderten Audit-Gegenproben.")
    mode.add_argument("--audit-results", type=Path, help="Pruefe35 Audit-JUnit-Faelle ohne Skip/Fehler.")
    args = parser.parse_args()
    raise SystemExit(
        check_admission_results(args.admission_results) if args.admission_results is not None
        else check_audit_results(args.audit_results) if args.audit_results is not None
        else check_audit_probes() if args.audit_probes else main()
    )
