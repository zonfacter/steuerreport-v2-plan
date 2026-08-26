#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shutil
import sys
from typing import Any

import httpx


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from steuerreport_v2.db.duckdb_store import DuckDbStore  # noqa: E402
from steuerreport_v2.domain.portfolio import PortfolioService  # noqa: E402
from steuerreport_v2.domain.review import ReviewService  # noqa: E402


DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
DEFAULT_CONFIG = PROJECT_ROOT / "configs/crypto_price_sources.json"
DEFAULT_BACKUP_DIR = Path("/workspace/backups/steuerreport-v2-plan/database")
DEFAULT_ARTIFACT_DIR = PROJECT_ROOT / "var/price_source_identity"
DEFAULT_API_BASE = "http://127.0.0.1:8010"

CWIF_MINT = "7atgF8KQo4wJrD5ATGX7t1V2zVvykPJbFfNeVf1icFv1"
CWIF_INCOME_QUANTITY = Decimal("384000")
CWIF_PRICE_EUR = Decimal("0.00000033943898562")
CWIF_EXPECTED_COST_EUR = CWIF_INCOME_QUANTITY * CWIF_PRICE_EUR
CWIF_PRICE_AT = "2024-03-30T00:00:00Z"
CWIF_SOURCE = (
    f"defillama_token_history:solana:{CWIF_MINT}:"
    "usd_eur:v1_fx_cache:2024-03-30"
)

CURRENT_ASSETS = (
    "CBDC",
    "CWIF",
    "HNT",
    "JLWSOL",
    "JUP",
    "SHARK",
    "SOL",
    "SPCXX",
    "USDC",
    "USDT",
)
PRICE_RANGES_EUR = {
    "CBDC": (Decimal("0.0000000001"), Decimal("0.001")),
    "CWIF": (Decimal("0.000000000001"), Decimal("0.0001")),
    "HNT": (Decimal("0.0001"), Decimal("100")),
    "JLWSOL": (Decimal("1"), Decimal("1000")),
    "JUP": (Decimal("0.0001"), Decimal("100")),
    "SHARK": (Decimal("0.00000001"), Decimal("1")),
    "SOL": (Decimal("1"), Decimal("1000")),
    "SPCXX": (Decimal("1"), Decimal("10000")),
    "USDC": (Decimal("0.5"), Decimal("1.5")),
    "USDT": (Decimal("0.5"), Decimal("1.5")),
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _tax_line_totals(store: DuckDbStore) -> list[dict[str, object]]:
    with store.connect() as con:
        rows = con.execute(
            """
            select year(disposed_at)::integer, count(*)::integer,
                   coalesce(sum(acquisition_cost_eur), 0),
                   coalesce(sum(disposal_proceeds_eur), 0),
                   coalesce(sum(gain_loss_eur), 0)
            from tax_lines
            group by 1
            order by 1
            """
        ).fetchall()
    return [
        {
            "year": int(year),
            "lines_count": int(count),
            "acquisition_cost_eur": str(cost),
            "disposal_proceeds_eur": str(proceeds),
            "gain_loss_eur": str(gain),
        }
        for year, count, cost, proceeds, gain in rows
    ]


def _cwif_income_lot(store: DuckDbStore) -> dict[str, str]:
    with store.connect() as con:
        row = con.execute(
            """
            select e.event_id, e.event_time, l.quantity_total,
                   l.cost_basis_eur_total
            from tax_lots l
            join canonical_events e on e.event_id = l.source_event_id
            where upper(l.asset) = 'CWIF' and e.event_type = 'income'
            order by e.event_time
            """
        ).fetchone()
    if row is None:
        raise RuntimeError("cwif_income_lot_missing")
    return {
        "event_id": str(row[0]),
        "event_time": str(row[1]),
        "quantity": str(row[2]),
        "cost_basis_eur": str(row[3]),
    }


def _validate_config(path: Path) -> list[dict[str, str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assets = {
        str(item.get("symbol") or "").upper(): item
        for item in payload.get("assets", [])
        if isinstance(item, dict)
    }
    expected = {
        "CBDC": "solana:2KFZCkfxj1Us8YRQZa5vktSxy3GPzFZvVhWj91n8Fv2J",
        "CWIF": f"solana:{CWIF_MINT}",
        "JLWSOL": "solana:2uQsyo1fXXQkDtcpXnLofWy88PxcvnfH2L8FPSE62FVU",
        "SHARK": "solana:SHARKSYJjqaNyxVfrpnBN9pjgkhwDhatnMyicWPnr1s",
    }
    rows: list[dict[str, str]] = []
    for asset, expected_id in expected.items():
        actual = str((assets.get(asset) or {}).get("defillama_id") or "")
        if actual != expected_id:
            raise RuntimeError(
                f"price_identity_config_mismatch:{asset}:"
                f"expected={expected_id}:actual={actual}"
            )
        rows.append({"asset": asset, "defillama_id": actual})
    return rows


def _post_json(api_base: str, path: str, payload: dict[str, object]) -> dict[str, Any]:
    response = httpx.post(
        f"{api_base.rstrip('/')}{path}",
        json=payload,
        timeout=180,
    )
    response.raise_for_status()
    body = response.json()
    if not isinstance(body, dict) or body.get("status") not in {"ok", "warning"}:
        raise RuntimeError(f"api_call_failed:{path}")
    return body


def _backup(db_path: Path, backup_dir: Path) -> tuple[Path, str]:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / (
        f"{db_path.stem}_before_mint_exact_price_fix_{stamp}{db_path.suffix}"
    )
    shutil.copy2(db_path, target)
    source_sha = _sha256(db_path)
    target_sha = _sha256(target)
    if db_path.stat().st_size != target.stat().st_size or source_sha != target_sha:
        target.unlink(missing_ok=True)
        raise RuntimeError("mint_exact_price_backup_integrity_failed")
    return target, target_sha


def _reuse_verified_backup(
    db_path: Path,
    artifact_path: Path,
) -> tuple[Path, str]:
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    if payload.get("status") != "rolled_back":
        raise RuntimeError("mint_exact_reuse_artifact_not_rolled_back")
    backup_path = Path(str(payload.get("backup_path") or "")).resolve()
    backup_sha = str(payload.get("backup_sha256") or "")
    restored_sha = str(payload.get("restored_sha256") or "")
    if not backup_path.is_file() or not backup_sha or restored_sha != backup_sha:
        raise RuntimeError("mint_exact_reuse_artifact_invalid")
    if backup_path.stat().st_size != db_path.stat().st_size:
        raise RuntimeError("mint_exact_reuse_backup_size_mismatch")
    current_sha = _sha256(db_path)
    if current_sha != backup_sha:
        raise RuntimeError(
            "mint_exact_reuse_database_changed:"
            f"expected={backup_sha}:actual={current_sha}"
        )
    return backup_path, backup_sha


def _write_artifact(payload: dict[str, object], artifact_dir: Path) -> Path:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = artifact_dir / f"mint_exact_price_apply_{stamp}.json"
    content = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
    path.write_text(content, encoding="utf-8")
    (artifact_dir / "latest_mint_exact_price_apply.json").write_text(
        content,
        encoding="utf-8",
    )
    return path


def _validate_current_jobs(body: dict[str, Any]) -> list[dict[str, str]]:
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    jobs = data.get("jobs") if isinstance(data.get("jobs"), list) else []
    imported = [item for item in jobs if isinstance(item, dict) and item.get("status") == "imported"]
    failed = [item for item in jobs if not isinstance(item, dict) or item.get("status") != "imported"]
    if failed or int(data.get("failed") or 0) or len(imported) != int(data.get("imported_prices") or 0):
        raise RuntimeError("mint_exact_current_price_refresh_incomplete")
    result: list[dict[str, str]] = []
    for item in imported:
        asset = str(item.get("asset") or "").upper()
        price = Decimal(str(item.get("price_eur") or "0"))
        minimum, maximum = PRICE_RANGES_EUR[asset]
        if not minimum <= price <= maximum:
            raise RuntimeError(
                f"mint_exact_current_price_out_of_range:{asset}:{price}"
            )
        source = str(item.get("source") or "")
        if not source.startswith("defillama_token_current:usd_eur:frankfurter_latest:"):
            raise RuntimeError(f"mint_exact_current_source_invalid:{asset}:{source}")
        result.append(
            {
                "asset": asset,
                "provider_id": str(item.get("provider_id") or ""),
                "price_eur": str(price),
                "source": source,
            }
        )
    return result


def run(args: argparse.Namespace) -> int:
    db_path = Path(args.db).resolve()
    config_path = Path(args.config).resolve()
    backup_dir = Path(args.backup_dir).resolve()
    artifact_dir = Path(args.artifact_dir).resolve()
    store = DuckDbStore(db_path)
    identities = _validate_config(config_path)
    before_tax = _tax_line_totals(store)
    before_lot = _cwif_income_lot(store)
    payload: dict[str, object] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "execute" if args.execute else "dry-run",
        "database": str(db_path),
        "config": str(config_path),
        "config_sha256": _sha256(config_path),
        "validated_identities": identities,
        "historical_correction": {
            "asset": "CWIF",
            "mint": CWIF_MINT,
            "quantity": str(CWIF_INCOME_QUANTITY),
            "price_eur": str(CWIF_PRICE_EUR),
            "expected_cost_basis_eur": str(CWIF_EXPECTED_COST_EUR),
            "priced_at": CWIF_PRICE_AT,
            "source": CWIF_SOURCE,
        },
        "current_assets": list(CURRENT_ASSETS),
        "before_tax_line_totals": before_tax,
        "before_cwif_income_lot": before_lot,
    }
    if not args.execute:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    with store.connect() as con:
        con.execute("checkpoint")
    if args.reuse_verified_backup_artifact:
        backup_path, backup_sha = _reuse_verified_backup(
            db_path,
            Path(args.reuse_verified_backup_artifact).resolve(),
        )
    else:
        backup_path, backup_sha = _backup(db_path, backup_dir)
    payload.update(
        {
            "backup_path": str(backup_path),
            "backup_sha256": backup_sha,
            "backup_size_bytes": backup_path.stat().st_size,
        }
    )
    try:
        historical = _post_json(
            args.api_base,
            "/api/v1/prices",
            {
                "asset": "CWIF",
                "price_eur": str(CWIF_PRICE_EUR),
                "priced_at": CWIF_PRICE_AT,
                "source": CWIF_SOURCE,
                "confidence": "0.99",
            },
        )
        current = _post_json(
            args.api_base,
            "/api/v1/prices/backfill/current-portfolio",
            {
                "config_path": str(config_path),
                "provider": "coingecko",
                "assets": list(CURRENT_ASSETS),
                "max_requests": len(CURRENT_ASSETS),
                "timeout_seconds": 30,
                "confidence": "0.99",
                "dry_run": False,
            },
        )
        current_jobs = _validate_current_jobs(current)
        after_tax = _tax_line_totals(store)
        after_lot = _cwif_income_lot(store)
        if before_tax != after_tax:
            raise RuntimeError("mint_exact_price_unexpected_realized_tax_change")
        if Decimal(after_lot["quantity"]) != CWIF_INCOME_QUANTITY:
            raise RuntimeError("mint_exact_price_cwif_quantity_changed")
        if Decimal(after_lot["cost_basis_eur"]) != CWIF_EXPECTED_COST_EUR:
            raise RuntimeError(
                "mint_exact_price_cwif_cost_mismatch:"
                f"expected={CWIF_EXPECTED_COST_EUR}:"
                f"actual={after_lot['cost_basis_eur']}"
            )
        gate = ReviewService(store).gate()
        if not gate.allow_export or gate.issues_open:
            raise RuntimeError(
                f"mint_exact_price_review_gate_failed:{gate.allow_export}:"
                f"{gate.issues_open}"
            )
        portfolio = PortfolioService(store).snapshot()
        payload.update(
            {
                "status": "applied",
                "historical_api_result": historical,
                "current_api_result": current,
                "current_price_jobs": current_jobs,
                "after_tax_line_totals": after_tax,
                "after_cwif_income_lot": after_lot,
                "review_gate": gate.model_dump(mode="json"),
                "portfolio": {
                    "total_value_eur": str(portfolio.total_value_eur),
                    "positions_count": len(portfolio.positions),
                },
            }
        )
    except Exception as exc:
        shutil.copy2(backup_path, db_path)
        restored_sha = _sha256(db_path)
        if restored_sha != backup_sha:
            raise RuntimeError("mint_exact_price_rollback_integrity_failed") from exc
        payload.update(
            {
                "status": "rolled_back",
                "error": str(exc),
                "restored_sha256": restored_sha,
            }
        )
        artifact_path = _write_artifact(payload, artifact_dir)
        raise RuntimeError(
            f"mint_exact_price_apply_failed_and_rolled_back:{exc}:"
            f"artifact={artifact_path}"
        ) from exc

    artifact_path = _write_artifact(payload, artifact_dir)
    print(
        json.dumps(
            {
                "status": "applied",
                "artifact_path": str(artifact_path),
                "backup_path": str(backup_path),
                "backup_sha256": backup_sha,
                "before_cwif_income_lot": before_lot,
                "after_cwif_income_lot": payload["after_cwif_income_lot"],
                "current_price_jobs": payload["current_price_jobs"],
                "review_gate": payload["review_gate"],
                "portfolio": payload["portfolio"],
                "realized_tax_line_parity": True,
            },
            indent=2,
            ensure_ascii=False,
            default=str,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--backup-dir", default=str(DEFAULT_BACKUP_DIR))
    parser.add_argument("--artifact-dir", default=str(DEFAULT_ARTIFACT_DIR))
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--reuse-verified-backup-artifact", default="")
    parser.add_argument("--execute", action="store_true")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
