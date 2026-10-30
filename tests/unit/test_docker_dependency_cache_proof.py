from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "check_docker_dependency_cache_v2", Path(__file__).resolve().parents[2] / "scripts/check_docker_dependency_cache_v2.py"
)
assert SPEC is not None and SPEC.loader is not None
proof = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proof)

GOOD = """#11 [stage-1 3/9] RUN pip install --no-cache-dir --no-deps -r requirements-runtime.lock
#11 CACHED
#17 [stage-1 6/9] RUN pip install --no-cache-dir --no-deps .     && pip check
#17 2.5 No broken requirements found.
#17 DONE 2.6s
"""


def test_exact_dependency_step_cached_and_project_rebuilt():
    assert proof.valid_cache_evidence(GOOD)


def test_repeated_header_for_same_buildkit_step_is_accepted():
    header = "#11 [stage-1 3/9] RUN pip install --no-cache-dir --no-deps -r requirements-runtime.lock"
    assert proof.valid_cache_evidence(GOOD + header + "\n#11 CACHED\n")


@pytest.mark.parametrize("bad", [
    GOOD.replace("#11 CACHED", "#99 CACHED"),
    GOOD.replace("#17 DONE 2.6s", "#17 CACHED"),
    GOOD.replace("#17 DONE 2.6s", ""),
    GOOD.replace("No broken requirements found.", "not checked"),
    GOOD + "#18 [stage-1 4/9] RUN pip install --no-cache-dir --no-deps -r requirements-runtime.lock\n",
    GOOD.replace("#17 2.5", "#99 2.5"),
])
def test_unrelated_or_incomplete_build_output_is_not_evidence(bad):
    assert not proof.valid_cache_evidence(bad)


def test_failure_does_not_print_build_output(tmp_path, capsys):
    log = tmp_path / "build.log"
    log.write_text("sensitive-build-data", encoding="utf-8")
    assert proof.main([str(log)]) == 1
    assert "sensitive-build-data" not in capsys.readouterr().err
