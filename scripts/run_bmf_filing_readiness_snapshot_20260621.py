from __future__ import annotations

import argparse
import json
from pathlib import Path

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_methodology import TaxMethodologyService


DEFAULT_DB = Path("/workspace/steuerreport-v2-plan/data/steuerreport_v2.duckdb")
DEFAULT_OUT = Path("/workspace/steuerreport-v2-plan/var/bmf_filing_readiness")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build a read-only BMF filing-readiness snapshot for 2021-2025. "
            "Writes JSON artifacts only; does not change DB tax data."
        )
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    service = TaxMethodologyService(DuckDbStore(args.db))
    latest = service.write_bmf_filing_readiness_snapshot(output_dir=args.out)
    snapshot = service.bmf_filing_readiness_snapshot(artifact_path=latest)
    print(
        json.dumps(
            {
                "artifact_path": str(latest),
                "status": snapshot.status,
                "snapshot_exists": snapshot.snapshot_exists,
                "years": snapshot.report.available_years if snapshot.report else [],
                "conservative_appendix_years": (
                    snapshot.report.conservative_appendix_years if snapshot.report else []
                ),
                "blocked_years": snapshot.report.blocked_years if snapshot.report else [],
                "review_years": snapshot.report.review_years if snapshot.report else [],
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
