#!/usr/bin/env python3
from __future__ import annotations

from steuerreport_v2.paths import configured_import_path

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from steuerreport_v2.contracts.prices import PricePointCreate  # noqa: E402
from steuerreport_v2.db.duckdb_store import DuckDbStore  # noqa: E402

DEFAULT_DB = PROJECT_ROOT / "data" / "steuerreport_v2.duckdb"
DEFAULT_V1_DB = Path(str(configured_import_path("v1_fx_db_file", "reference/legacy-prices.db")))
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var" / "stablecoin_fx_anchor_apply"
STABLECOINS = ("USDT", "USDC", "BUSD", "FDUSD", "TUSD", "DAI", "EURC", "EURS")
SOURCE_PREFIX = "stablecoin_fx_anchor:v1_fx_cache"


@dataclass(frozen=True)
class AnchorCandidate:
    asset: str
    price_date: str
    year: int
    derived_price_count: int
    min_derived_price_eur: str
    max_derived_price_eur: str
    first_derived_at: str
    last_derived_at: str
    fx_status: str
    usd_eur: str | None
    fx_source: str | None
    fx_rate_date: str | None
    fx_source_rate_date: str | None
    source: str | None
    already_exists: bool


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply all-year Stablecoin USD/EUR FX anchors for derived:event_quote stablecoin days."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--v1-db", default=str(DEFAULT_V1_DB))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--confirm-apply", action="store_true")
    args = parser.parse_args()

    db_path = Path(args.db)
    v1_db_path = Path(args.v1_db)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    store = DuckDbStore(db_path)
    raw_days = derived_stablecoin_days(store)
    candidates = build_candidates(store, raw_days, v1_db_path)
    ready = [row for row in candidates if row.fx_status == "ready" and not row.already_exists]
    inserted = 0
    if args.confirm_apply and ready:
        points = [
            PricePointCreate(
                asset=row.asset,
                price_eur=Decimal(str(row.usd_eur)),
                priced_at=datetime.fromisoformat(f"{row.price_date}T00:00:00+00:00"),
                source=str(row.source),
                confidence=Decimal("1.0"),
            )
            for row in ready
        ]
        store.add_price_points(points)
        inserted = len(points)

    report = {
        "mode": "apply" if args.confirm_apply else "dry_run",
        "generated_at": datetime.now(UTC).isoformat(),
        "db_path": str(db_path),
        "v1_db_path": str(v1_db_path),
        "stablecoins": list(STABLECOINS),
        "summary": summarize(candidates, inserted=inserted),
        "candidates": [asdict(row) for row in candidates],
        "methodology": (
            "Findet Stablecoin-Preis-Tage, die aus derived:event_quote stammen, "
            "liest USD/EUR aus dem V1-fx_cache und fuegt pro Asset/Tag einen "
            "primaeren Stablecoin-FX-Anker ein. Rohimporte, Canonical Events und "
            "Tax-Lines werden nicht direkt geaendert; Tax-Lines aendern sich erst "
            "durch separaten FIFO-Rebuild."
        ),
    }
    run_id = datetime.now(UTC).strftime("run_%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"{run_id}_stablecoin_fx_anchor_apply.json"
    latest_path = output_dir / "latest_stablecoin_fx_anchor_apply.json"
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    output_path.write_text(payload, encoding="utf-8")
    latest_path.write_text(payload, encoding="utf-8")
    print(json.dumps({"output_path": str(output_path), "summary": report["summary"]}, indent=2))


def derived_stablecoin_days(store: DuckDbStore) -> list[dict[str, object]]:
    placeholders = ", ".join("?" for _ in STABLECOINS)
    with store.connect() as con:
        rows = con.execute(
            f"""
            select
                upper(asset) as asset,
                cast(priced_at as date) as price_date,
                date_part('year', priced_at)::integer as year,
                count(*)::integer as derived_price_count,
                min(price_eur) as min_derived_price_eur,
                max(price_eur) as max_derived_price_eur,
                min(priced_at) as first_derived_at,
                max(priced_at) as last_derived_at
            from price_ledger
            where upper(asset) in ({placeholders})
              and lower(source) like 'derived:%'
            group by upper(asset), cast(priced_at as date), date_part('year', priced_at)::integer
            order by year, price_date, asset
            """,
            list(STABLECOINS),
        ).fetchall()
    return [
        {
            "asset": row[0],
            "price_date": row[1].isoformat(),
            "year": int(row[2]),
            "derived_price_count": int(row[3]),
            "min_derived_price_eur": str(row[4]),
            "max_derived_price_eur": str(row[5]),
            "first_derived_at": row[6].isoformat(),
            "last_derived_at": row[7].isoformat(),
        }
        for row in rows
    ]


def build_candidates(
    store: DuckDbStore,
    raw_days: list[dict[str, object]],
    v1_db_path: Path,
) -> list[AnchorCandidate]:
    if not v1_db_path.exists():
        return [
            candidate_from_raw(row, fx_status="missing_v1_db")
            for row in raw_days
        ]
    result: list[AnchorCandidate] = []
    with sqlite3.connect(f"file:{v1_db_path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        for row in raw_days:
            price_date = str(row["price_date"])
            fx = read_usd_eur_fx(con, price_date)
            if fx is None:
                result.append(candidate_from_raw(row, fx_status="missing_usd_eur_fx"))
                continue
            rate = Decimal(str(fx["rate"]))
            if rate <= 0:
                result.append(candidate_from_raw(row, fx_status="non_positive_usd_eur_fx"))
                continue
            source = (
                f"{SOURCE_PREFIX}:{fx['source']}:"
                f"rate_date:{price_date}:source_rate_date:{fx['rate_date']}"
            )
            exists = price_point_exists(
                store,
                asset=str(row["asset"]),
                price_date=price_date,
                source=source,
            )
            result.append(
                candidate_from_raw(
                    row,
                    fx_status="ready",
                    usd_eur=format(rate, "f"),
                    fx_source=str(fx["source"]),
                    fx_rate_date=str(fx["rate_date"]),
                    fx_source_rate_date=str(fx["source_rate_date"] or fx["rate_date"]),
                    source=source,
                    already_exists=exists,
                )
            )
    return result


def read_usd_eur_fx(con: sqlite3.Connection, price_date: str) -> sqlite3.Row | None:
    exact = con.execute(
        """
        select rate_date, base_ccy, quote_ccy, rate, source, source_rate_date
        from fx_cache
        where rate_date = ? and base_ccy = 'USD' and quote_ccy = 'EUR'
        limit 1
        """,
        [price_date],
    ).fetchone()
    if exact is not None:
        return exact
    return con.execute(
        """
        select rate_date, base_ccy, quote_ccy, rate, source, source_rate_date
        from fx_cache
        where rate_date <= ? and base_ccy = 'USD' and quote_ccy = 'EUR'
        order by rate_date desc
        limit 1
        """,
        [price_date],
    ).fetchone()


def price_point_exists(store: DuckDbStore, *, asset: str, price_date: str, source: str) -> bool:
    with store.connect() as con:
        row = con.execute(
            """
            select 1
            from price_ledger
            where upper(asset) = ?
              and priced_at = cast(? as timestamp)
              and source = ?
            limit 1
            """,
            [asset.upper(), f"{price_date} 00:00:00", source],
        ).fetchone()
    return row is not None


def candidate_from_raw(
    row: dict[str, object],
    *,
    fx_status: str,
    usd_eur: str | None = None,
    fx_source: str | None = None,
    fx_rate_date: str | None = None,
    fx_source_rate_date: str | None = None,
    source: str | None = None,
    already_exists: bool = False,
) -> AnchorCandidate:
    return AnchorCandidate(
        asset=str(row["asset"]),
        price_date=str(row["price_date"]),
        year=int(row["year"]),
        derived_price_count=int(row["derived_price_count"]),
        min_derived_price_eur=str(row["min_derived_price_eur"]),
        max_derived_price_eur=str(row["max_derived_price_eur"]),
        first_derived_at=str(row["first_derived_at"]),
        last_derived_at=str(row["last_derived_at"]),
        fx_status=fx_status,
        usd_eur=usd_eur,
        fx_source=fx_source,
        fx_rate_date=fx_rate_date,
        fx_source_rate_date=fx_source_rate_date,
        source=source,
        already_exists=already_exists,
    )


def summarize(candidates: list[AnchorCandidate], *, inserted: int) -> dict[str, object]:
    by_status: dict[str, int] = {}
    by_year: dict[str, dict[str, int]] = {}
    for row in candidates:
        by_status[row.fx_status] = by_status.get(row.fx_status, 0) + 1
        year = str(row.year)
        item = by_year.setdefault(year, {"days": 0, "ready": 0, "already_exists": 0})
        item["days"] += 1
        if row.fx_status == "ready":
            item["ready"] += 1
        if row.already_exists:
            item["already_exists"] += 1
    return {
        "candidate_days": len(candidates),
        "ready_days": sum(1 for row in candidates if row.fx_status == "ready"),
        "already_existing_days": sum(1 for row in candidates if row.already_exists),
        "insertable_days": sum(
            1 for row in candidates if row.fx_status == "ready" and not row.already_exists
        ),
        "inserted_days": inserted,
        "by_status": by_status,
        "by_year": by_year,
    }


if __name__ == "__main__":
    main()
