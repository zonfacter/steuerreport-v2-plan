#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from steuerreport_v2.contracts.tax_filing_snapshots import (
    TaxFilingSnapshotCaptureRequest,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_filing_snapshots import (
    SUBMISSION_CONFIRMATION_TEXT,
    TaxFilingSnapshotService,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Vorhandenes Steuerjahr-Belegpaket unveraenderlich im V2-Abgabearchiv registrieren."
        )
    )
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument(
        "--state",
        choices=("reference", "submitted"),
        default="reference",
    )
    parser.add_argument(
        "--filing-kind",
        choices=("original", "correction"),
        default="original",
    )
    parser.add_argument("--submitted-at")
    parser.add_argument("--note")
    parser.add_argument(
        "--confirm-submitted",
        action="store_true",
        help="Bestaetigt, dass genau dieses Paket tatsaechlich uebermittelt wurde.",
    )
    parser.add_argument("--database", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    confirmation = (
        SUBMISSION_CONFIRMATION_TEXT
        if args.state == "submitted" and args.confirm_submitted
        else None
    )
    request = TaxFilingSnapshotCaptureRequest(
        state=args.state,
        filing_kind=args.filing_kind,
        submitted_at=args.submitted_at,
        note=args.note,
        confirmation_text=confirmation,
    )
    service = TaxFilingSnapshotService(DuckDbStore(args.database))
    result = service.import_existing_package(
        year=args.year,
        package_path=args.package,
        request=request,
    )
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
