#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any

from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.review import ReviewService


PROJECT_ROOT = Path("/workspace/steuerreport-v2-plan")
DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
DEFAULT_PACKAGE = PROJECT_ROOT / "configs/binance_small_assets_price_evidence_20260710.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var/binance_small_assets_price_evidence"
SOURCE_PREFIX = "binance_public_klines"


def _decimal(value: object) -> Decimal:
    return Decimal(str(value))


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("price evidence package must be a JSON object")
    return payload


def build_points(payload: dict[str, Any]) -> list[PricePointCreate]:
    fx_rates = payload.get("fx_rates")
    rows = payload.get("prices")
    if not isinstance(fx_rates, dict) or not isinstance(rows, list):
        raise ValueError("price evidence package is missing fx_rates or prices")
    points: list[PricePointCreate] = []
    seen: set[tuple[str, datetime]] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("price evidence row must be an object")
        asset = str(row.get("asset") or "").strip().upper()
        pair = str(row.get("pair") or "").strip().upper()
        quote_asset = str(row.get("quote_asset") or "").strip().upper()
        priced_at = datetime.fromisoformat(str(row.get("priced_at") or "").replace("Z", "+00:00"))
        if priced_at.tzinfo is None:
            priced_at = priced_at.replace(tzinfo=timezone.utc)
        priced_at = priced_at.astimezone(timezone.utc)
        if int(priced_at.timestamp() * 1000) != int(row.get("open_time_ms") or -1):
            raise ValueError(f"open_time_mismatch:{asset}:{priced_at.isoformat()}")
        key = (asset, priced_at)
        if not asset or not pair or key in seen:
            raise ValueError(f"invalid_or_duplicate_price_row:{asset}:{priced_at.isoformat()}")
        seen.add(key)
        close = _decimal(row.get("close"))
        if quote_asset in {"USD", "USDT", "BUSD", "USDC"}:
            price_usd = close
            bridge = "quote_usd"
        elif quote_asset == "BTC":
            bridge_close = _decimal(row.get("bridge_close_usd"))
            if str(row.get("bridge_pair") or "").upper() != "BTCUSDT":
                raise ValueError(f"unsupported_btc_bridge:{asset}")
            price_usd = close * bridge_close
            bridge = "btc_usdt_cross"
        else:
            raise ValueError(f"unsupported_quote_asset:{asset}:{quote_asset}")
        fx = fx_rates.get(priced_at.date().isoformat())
        if not isinstance(fx, dict):
            raise ValueError(f"missing_fx_rate:{priced_at.date().isoformat()}")
        usd_eur = _decimal(fx.get("usd_eur"))
        if close <= 0 or price_usd <= 0 or usd_eur <= 0:
            raise ValueError(f"non_positive_price_component:{asset}")
        source = (
            f"{SOURCE_PREFIX}:{pair}:1m:close:{bridge}:"
            f"usd_eur:{fx.get('source')}:{priced_at.date().isoformat()}"
        )
        points.append(
            PricePointCreate(
                asset=asset,
                price_eur=price_usd * usd_eur,
                priced_at=priced_at,
                source=source,
                confidence=Decimal("0.98"),
            )
        )
    return points


def _tax_years(store: DuckDbStore) -> list[dict[str, object]]:
    with store.connect() as con:
        rows = con.execute(
            """
            select year(disposed_at), count(*), coalesce(sum(gain_loss_eur), 0)
            from tax_lines group by 1 order by 1
            """
        ).fetchall()
    return [
        {"year": int(year), "tax_lines": int(count), "gain_loss_eur": str(value)}
        for year, count, value in rows
    ]


def _existing_keys(store: DuckDbStore, points: list[PricePointCreate]) -> set[tuple[str, datetime, str]]:
    if not points:
        return set()
    with store.connect() as con:
        rows = con.execute(
            """
            select asset, priced_at, source from price_ledger
            where source like ?
            """,
            [f"{SOURCE_PREFIX}:%"],
        ).fetchall()
    return {(str(asset), priced_at, str(source)) for asset, priced_at, source in rows}


def run(args: argparse.Namespace) -> dict[str, object]:
    package_path = Path(args.package)
    payload = _load(package_path)
    points = build_points(payload)
    store = DuckDbStore(Path(args.db))
    existing = _existing_keys(store, points)
    pending = [point for point in points if (point.asset, point.priced_at, point.source) not in existing]
    generated_at = datetime.now(timezone.utc)
    report: dict[str, object] = {
        "generated_at": generated_at.isoformat(),
        "mode": "apply" if args.apply else "preview",
        "status": "ready",
        "package": str(package_path.relative_to(PROJECT_ROOT)),
        "package_sha256": hashlib.sha256(package_path.read_bytes()).hexdigest(),
        "points_count": len(points),
        "pending_points_count": len(pending),
        "points": [point.model_dump(mode="json") for point in points],
        "target_changed": False,
        "methodology": str(payload.get("methodology") or ""),
    }
    if args.apply and pending:
        report["pre_apply_tax_years"] = _tax_years(store)
        created = store.add_price_points(pending)
        try:
            pipeline = PipelineService(store).rebuild_all()
            gate = ReviewService(store).gate()
            if not gate.allow_export or gate.issues_open:
                raise RuntimeError(
                    f"post_apply_review_gate_closed:allow_export={gate.allow_export}:issues={gate.issues_open}"
                )
        except Exception:
            for point in created:
                store.delete_price_point(point.price_id)
            PipelineService(store).rebuild_all()
            raise
        report.update(
            {
                "status": "applied",
                "target_changed": True,
                "created_price_ids": [point.price_id for point in created],
                "pipeline": pipeline.model_dump(mode="json"),
                "review_gate": gate.model_dump(mode="json"),
                "post_apply_tax_years": _tax_years(store),
            }
        )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    content = json.dumps(report, indent=2, ensure_ascii=False)
    versioned = output_dir / f"binance_small_assets_prices_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    latest = output_dir / "latest_binance_small_assets_prices.json"
    versioned.write_text(content, encoding="utf-8")
    latest.write_text(content, encoding="utf-8")
    report["artifact_path"] = str(versioned.relative_to(PROJECT_ROOT))
    report["latest_artifact_path"] = str(latest.relative_to(PROJECT_ROOT))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Import exact Binance small-assets price evidence")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--package", default=str(DEFAULT_PACKAGE))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--apply", action="store_true")
    print(json.dumps(run(parser.parse_args()), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
