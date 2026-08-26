#!/usr/bin/env python3
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.solana_staking_position import (
    SolanaStakingPositionReconciliationService,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = PROJECT_ROOT / "var/solana_staking_position_reconciliation"


def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def main() -> None:
    report = SolanaStakingPositionReconciliationService(
        DuckDbStore(PROJECT_ROOT / "data/steuerreport_v2.duckdb")
    ).report()
    content = json.dumps(
        report.model_dump(mode="json"), indent=2, ensure_ascii=False
    ).encode("utf-8")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_path = ARTIFACT_ROOT / f"{timestamp}_solana_staking_position_reconciliation.json"
    latest_path = ARTIFACT_ROOT / "latest_solana_staking_position_reconciliation.json"
    atomic_write(artifact_path, content)
    atomic_write(latest_path, content)
    print(
        json.dumps(
            {
                "artifact_path": str(artifact_path),
                "status": report.status,
                "strict_ready": report.strict_ready,
                "principal_quantity": str(report.principal_quantity),
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
