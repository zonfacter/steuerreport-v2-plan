"""Read private runtime configuration from outside the software repository."""
from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
import re

from steuerreport_v2.paths import PROJECT_ROOT


@lru_cache(maxsize=8)
def _read_profile(filename: str) -> dict[str, str]:
    if not filename:
        return {}
    try:
        value = json.loads(Path(filename).expanduser().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise RuntimeError("private_profile_unreadable") from None
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and isinstance(item, str) for key, item in value.items()
    ):
        raise RuntimeError("private_profile_requires_string_values")
    return value


def private_value(name: str, default: str = "") -> str:
    environment_name = "STEUERREPORT_" + name.upper()
    if environment_name in os.environ:
        return os.environ[environment_name]
    profile = _read_profile(os.environ.get("STEUERREPORT_PRIVATE_PROFILE", ""))
    return profile.get(name, default)


def private_template(template: str) -> str:
    return re.sub(r"\{([a-z][a-z0-9_]*)\}", lambda match: private_value(match.group(1)), template)


def private_alias(name: str, prefix_length: int, suffix_length: int, separator: str = "...") -> str:
    value = private_value(name)
    if not value:
        return ""
    return value[:prefix_length] + separator + (value[-suffix_length:] if suffix_length else "")


def private_config_path(filename: str) -> Path:
    if Path(filename).name != filename:
        raise ValueError("private_config_filename_invalid")
    directory = os.environ.get("STEUERREPORT_PRIVATE_CONFIG_DIR", "")
    if directory:
        candidate = Path(directory).expanduser() / filename
        if candidate.is_file():
            return candidate
    default = PROJECT_ROOT / "configs" / filename
    if filename == "source_registry.json" and not default.is_file():
        return PROJECT_ROOT / "configs/source_registry.example.json"
    return default
