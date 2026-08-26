#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.cross_cex_evidence import (
    CrossCexTransferEvidenceService,
)


PROJECT_ROOT = Path("/workspace/steuerreport-v2-plan")
DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var/cross_cex_transfer_evidence"


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Erzeugt den SHA-gebundenen Cross-CEX-Transfernachweis."
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    report = CrossCexTransferEvidenceService(DuckDbStore(args.db)).report()
    payload = report.model_dump(mode="json")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_path = args.output_dir / f"{timestamp}_cross_cex_transfer_evidence.json"
    latest_path = args.output_dir / "latest_cross_cex_transfer_evidence.json"
    _write_json(run_path, payload)
    _write_json(latest_path, payload)
    print(
        json.dumps(
            {
                "artifact_path": str(run_path),
                "latest_path": str(latest_path),
                "status": report.status,
                "strict_ready": report.strict_ready,
                "records_count": report.records_count,
                "ready_count": report.ready_count,
                "review_count": report.review_count,
                "semantic_sha256": report.semantic_sha256,
                "errors": report.errors,
            },
            indent=2,
        )
    )
    return 0 if report.strict_ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
