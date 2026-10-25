import os
from pathlib import Path

import pytest


# Tests always use generated fixture identities, never the operator's profile.
os.environ["STEUERREPORT_PRIVATE_PROFILE"] = str(Path(__file__).parent / "fixture_profile.json")
os.environ.pop("STEUERREPORT_PRIVATE_CONFIG_DIR", None)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call":
        item._steuerreport_call_passed = report.passed


@pytest.fixture(autouse=True)
def prune_successful_test_databases(request):
    yield
    if os.environ.get("STEUERREPORT_TEST_PRUNE_PASSED_DBS") != "1":
        return
    if not getattr(request.node, "_steuerreport_call_passed", False):
        return
    base = request.node.funcargs.get("tmp_path")
    if base is None or base.is_symlink():
        return
    # Keep directory names reserved: report caches use database paths as keys.
    for path in base.rglob("*.duckdb"):
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(base.resolve()):
            continue
        with path.open("rb") as handle:
            if b"DUCK" not in handle.read(16):
                continue
        path.unlink()
