"""Prueft die unveraenderte unabhaengige Ausgangsprobe vor dem CI-Gate."""
from pathlib import Path
import hashlib


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = "09f674b350a9a83943df8980bbceafd88821ee1400e03b5b22ea1ee0f8cd6bfb"


def main() -> int:
    probe = ROOT / "docs/audit/2026-10-28/acceptance_tests.py"
    actual = hashlib.sha256(probe.read_bytes()).hexdigest()
    if actual != EXPECTED:
        print("independent_reference_baseline_changed")
        return 1
    print("independent_reference_baseline_verified:" + actual)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
