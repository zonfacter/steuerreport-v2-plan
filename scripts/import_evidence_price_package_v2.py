#!/usr/bin/env python3
from __future__ import annotations

from steuerreport_v2.paths import PROJECT_ROOT as SOFTWARE_ROOT

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any

from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore


PROJECT_ROOT = SOFTWARE_ROOT
DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
DEFAULT_PACKAGE = PROJECT_ROOT / "configs/solana_evidence_prices_20260710.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var/evidence_price_imports"


def load_package(path: Path) -> list[PricePointCreate]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or int(payload.get("version") or 0) != 1:
        raise ValueError(f"unsupported price package: {path}")
    confidence = Decimal(str(payload.get("confidence") or "0"))
    source_prefix = str(payload.get("source_prefix") or "").strip()
    if confidence <= 0 or not source_prefix:
        raise ValueError(f"invalid price package metadata: {path}")
    result: list[PricePointCreate] = []
    seen: set[tuple[str, datetime, str]] = set()
    for value in payload.get("points", []):
        if not isinstance(value, list) or len(value) != 3:
            raise ValueError(f"invalid price point row: {value!r}")
        asset = str(value[0]).strip().upper()
        priced_at = datetime.fromisoformat(f"{value[1]}T00:00:00+00:00").astimezone(timezone.utc)
        price = Decimal(str(value[2]))
        source = f"{source_prefix}:{value[1]}"
        key = (asset, priced_at, source)
        if not asset or price <= 0 or key in seen:
            raise ValueError(f"invalid or duplicate price point: {value!r}")
        seen.add(key)
        result.append(
            PricePointCreate(
                asset=asset,
                price_eur=price,
                priced_at=priced_at,
                source=source,
                confidence=confidence,
            )
        )
    return result


def classify_existing(
    store: DuckDbStore,
    points: list[PricePointCreate],
) -> tuple[list[PricePointCreate], list[dict[str, str]], list[dict[str, str]]]:
    missing: list[PricePointCreate] = []
    matched: list[dict[str, str]] = []
    conflicts: list[dict[str, str]] = []
    with store.connect() as con:
        for point in points:
            rows = con.execute(
                """
                select price_eur, confidence
                from price_ledger
                where asset = ? and priced_at = ? and source = ?
                """,
                [point.asset, point.priced_at, point.source],
            ).fetchall()
            if not rows:
                missing.append(point)
                continue
            exact = any(
                Decimal(str(price)) == point.price_eur
                and Decimal(str(confidence)) == point.confidence
                for price, confidence in rows
            )
            detail = {
                "asset": point.asset,
                "priced_at": point.priced_at.isoformat(),
                "source": point.source,
            }
            if exact:
                matched.append(detail)
            else:
                conflicts.append(detail)
    return missing, matched, conflicts


def _json_point(point: PricePointCreate) -> dict[str, str]:
    return {
        "asset": point.asset,
        "price_eur": str(point.price_eur),
        "priced_at": point.priced_at.isoformat(),
        "source": point.source,
        "confidence": str(point.confidence),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    package_path = Path(args.package)
    points = load_package(package_path)
    store = DuckDbStore(Path(args.db))
    missing, matched, conflicts = classify_existing(store, points)
    if conflicts:
        raise RuntimeError(f"price_package_conflicts:{len(conflicts)}")
    created = store.add_price_points(missing) if args.apply and missing else []
    generated_at = datetime.now(timezone.utc)
    report: dict[str, Any] = {
        "generated_at": generated_at.isoformat(),
        "mode": "apply" if args.apply else "preview",
        "status": "applied" if args.apply else "ready",
        "package": str(package_path.relative_to(PROJECT_ROOT)),
        "package_sha256": hashlib.sha256(package_path.read_bytes()).hexdigest(),
        "points_count": len(points),
        "missing_count": len(missing),
        "matched_count": len(matched),
        "conflicts_count": len(conflicts),
        "missing_points": [_json_point(point) for point in missing],
        "created_price_ids": [point.price_id for point in created],
        "target_changed": bool(created),
        "rollback": {
            "method": "existing_price_delete_api",
            "endpoints": [f"DELETE /api/v1/prices/{point.price_id}" for point in created],
        },
    }
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    content = json.dumps(report, indent=2, ensure_ascii=False)
    versioned = output_dir / f"evidence_price_import_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    latest = output_dir / "latest_evidence_price_import.json"
    versioned.write_text(content, encoding="utf-8")
    latest.write_text(content, encoding="utf-8")
    report["artifact_path"] = str(versioned.relative_to(PROJECT_ROOT))
    report["latest_artifact_path"] = str(latest.relative_to(PROJECT_ROOT))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Import a versioned historical EUR price evidence package")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--package", default=str(DEFAULT_PACKAGE))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
