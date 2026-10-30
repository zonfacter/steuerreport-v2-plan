import re
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


ROOT = Path(__file__).resolve().parents[2]


def test_runtime_lock_layer_precedes_application_source_layer():
    lines = (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()

    lock_copy = lines.index("COPY requirements-runtime.lock ./")
    lock_install = next(
        index
        for index, line in enumerate(lines)
        if "pip install --no-cache-dir -r requirements-runtime.lock" in line
    )
    project_copy = lines.index("COPY pyproject.toml README.md ./")
    source_copy = lines.index("COPY src/ ./src/")
    app_install = next(
        index
        for index, line in enumerate(lines)
        if "pip install --no-cache-dir --no-deps ." in line
    )
    pip_check = next(
        index for index, line in enumerate(lines) if "&& pip check" in line
    )

    assert lock_copy < lock_install < project_copy < source_copy < app_install
    assert app_install < pip_check
    assert not any(
        "-c requirements-runtime.lock ." in line for line in lines
    )


def test_runtime_security_and_state_contract_remains_in_dockerfile():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    for required in (
        "STEUERREPORT_V2_SECRET_VAULT_KEY_FILE=/state/keys/vault.key",
        "STEUERREPORT_V2_REQUIRE_ENCRYPTED_SECRETS=true",
        "STEUERREPORT_V2_DB=/state/data/steuerreport_v2.duckdb",
        "&& chown -R 10001:10001 /state",
        "USER 10001:10001",
        'ENTRYPOINT ["python", "-m", "steuerreport_v2.container_entrypoint"]',
    ):
        assert required in dockerfile


def test_runtime_lock_pins_every_project_runtime_dependency():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock_lines = (ROOT / "requirements-runtime.lock").read_text(encoding="utf-8").splitlines()
    pinned_names = set()
    for line in lock_lines:
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==[^\s;]+", entry)
        assert match, f"Runtime-Lock-Eintrag ist nicht exakt gepinnt: {entry}"
        pinned_names.add(canonicalize_name(match.group(1)))

    missing = {
        canonicalize_name(Requirement(dependency).name)
        for dependency in project["project"]["dependencies"]
    } - pinned_names

    assert not missing, f"Runtime-Lock ohne Pins fuer: {sorted(missing)}"
