import json
from pathlib import Path
import tomllib

from steuerreport_v2 import __version__


ROOT = Path(__file__).resolve().parents[2]


def test_readme_installation_names_current_release_and_image():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    installation = readme.split("### Lokal aus dem Quellstand bauen", 1)[0]
    assert f"Version {__version__}," in installation
    assert f"docs/RELEASE_{__version__}.md" in installation
    assert (ROOT / "docs" / f"RELEASE_{__version__}.md").is_file()
    assert f"docker pull ghcr.io/zonfacter/steuerreport-v2:{__version__}" in installation


def test_published_version_matches_project_frontend_and_compose():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == __version__
    frontend = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    normalized = __version__.replace("rc", "-rc.")
    assert frontend["version"] == normalized
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    assert lock["version"] == normalized
    assert lock["packages"][""]["version"] == normalized
    assert f"steuerreport-v2:{__version__}" in (ROOT / "compose.yml").read_text(encoding="utf-8")
    assert f"ghcr.io/zonfacter/steuerreport-v2:{__version__}" in (ROOT / "compose.ghcr.yml").read_text(encoding="utf-8")
