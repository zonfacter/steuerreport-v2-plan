#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from steuerreport_v2.domain.legal_research import LegalResearchService  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prueft aktuelle offizielle Steuer- und Kryptorechtsquellen fail-closed."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=LegalResearchService.DEFAULT_CONFIG_PATH,
    )
    parser.add_argument(
        "--artifact-root",
        type=Path,
        default=LegalResearchService.DEFAULT_ARTIFACT_ROOT,
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = LegalResearchService(
        config_path=args.config,
        artifact_root=args.artifact_root,
    ).run()
    print(json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False))
    if report.status == "error":
        return 2
    if report.status == "review_required":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
