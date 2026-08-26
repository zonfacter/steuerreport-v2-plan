#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import urllib.request

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.fairspot_staking import (
    FairspotStakingReconciliationService,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "configs/fairspot_hnt_staking_reconciliation.json"
ARTIFACT_ROOT = PROJECT_ROOT / "var/fairspot_staking_reconciliation"
DB_PATH = PROJECT_ROOT / "data/steuerreport_v2.duckdb"


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def main() -> None:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    request = urllib.request.Request(
        str(config["independent_source"]["url"]),
        headers={"User-Agent": "steuerreport-v2-fairspot-evidence/1.0"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        content = response.read()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    source_path = ARTIFACT_ROOT / f"{timestamp}_fairspot_staking_source.csv"
    latest_source_path = ARTIFACT_ROOT / "latest_fairspot_staking_source.csv"
    atomic_write(source_path, content)
    atomic_write(latest_source_path, content)
    service = FairspotStakingReconciliationService(
        DuckDbStore(DB_PATH),
        independent_source_path=latest_source_path,
    )
    report = service.report()
    report_content = json.dumps(
        report.model_dump(mode="json"),
        indent=2,
        ensure_ascii=False,
    ).encode("utf-8")
    artifact_path = ARTIFACT_ROOT / f"{timestamp}_fairspot_staking_reconciliation.json"
    latest_path = ARTIFACT_ROOT / "latest_fairspot_staking_reconciliation.json"
    atomic_write(artifact_path, report_content)
    atomic_write(latest_path, report_content)
    print(
        json.dumps(
            {
                "artifact_path": str(artifact_path),
                "source_path": str(source_path),
                "status": report.status,
                "strict_ready": report.strict_ready,
                "reward_quantity": str(report.reward_quantity),
                "reward_income_eur": str(report.reward_income_eur),
                "semantic_sha256": report.semantic_sha256,
                "errors": report.errors,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
