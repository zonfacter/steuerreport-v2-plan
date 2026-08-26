from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(
    os.environ.get(
        "STEUERREPORT_V2_ROOT",
        Path(__file__).resolve().parents[2],
    )
).expanduser().resolve()

USERTRANSFER_ROOT = Path(
    os.environ.get(
        "STEUERREPORT_USERTRANSFER_ROOT",
        PROJECT_ROOT.parent / "steuerreport" / "usertransfer",
    )
).expanduser().resolve()


def resolve_project_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else PROJECT_ROOT / candidate


def resolve_usertransfer_path(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    return candidate if candidate.is_absolute() else USERTRANSFER_ROOT / candidate
