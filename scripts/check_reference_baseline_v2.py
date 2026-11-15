"""Prueft die unveraenderte unabhaengige Ausgangsprobe vor dem CI-Gate."""
from pathlib import Path
import hashlib


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = "09f674b350a9a83943df8980bbceafd88821ee1400e03b5b22ea1ee0f8cd6bfb"
CHECKPOINT_EXPECTED = "68beedb2b00d9b87c55b03f0c6da8a89c87a8e78529467fb34562072dc2b5f48"
CHECKPOINT_REVIEW_EXPECTED = "db10e6259ba1953792a66eb7a8396ccc4841810bf0818264b2dd6fd8670ac337"
AS_OF_TIME_EXPECTED = "06d4d1115cf1f5dfa1ff240d37a87c23709685e151d7df7902432a3fb5a3fdc8"


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
    print("independent_reference_baseline_verified:" + actual)
    print("independent_checkpoint_baseline_verified:" + checkpoint_actual)
    print("independent_checkpoint_review_verified:" + review_actual)
    print("independent_as_of_time_baseline_verified:" + temporal_actual)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
