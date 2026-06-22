from __future__ import annotations

import argparse
import json
from pathlib import Path

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_methodology import TaxMethodologyService


DEFAULT_DB = Path("/workspace/steuerreport-v2-plan/data/steuerreport_v2.duckdb")
DEFAULT_OUT = Path("/workspace/steuerreport-v2-plan/var/bmf_closure_backlog")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build a read-only BMF closure-backlog snapshot for 2021-2025. "
            "Writes JSON artifacts only; does not change DB tax data."
        )
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    service = TaxMethodologyService(DuckDbStore(args.db))
    latest = service.write_bmf_closure_backlog_snapshot(output_dir=args.out)
    snapshot = service.bmf_closure_backlog_snapshot(artifact_path=latest)
    report = snapshot.report
    print(
        json.dumps(
            {
                "artifact_path": str(latest),
                "status": snapshot.status,
                "snapshot_exists": snapshot.snapshot_exists,
                "years": report.available_years if report else [],
                "blocker_items_count": report.blocker_items_count if report else 0,
                "review_items_count": report.review_items_count if report else 0,
                "next_year_to_close": report.next_year_to_close if report else None,
                "total_exposure_eur": str(report.total_exposure_eur) if report else "0",
            },
            indent=2,
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
