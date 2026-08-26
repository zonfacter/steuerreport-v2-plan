#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from steuerreport_v2.db.duckdb_store import DuckDbStore  # noqa: E402
from steuerreport_v2.domain.binance_earn import BinanceEarnHistoryService  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Harvest Binance Simple Earn history read-only into var/binance_simple_earn_history."
    )
    parser.add_argument("--since", default="2021-01-01", help="ISO start date, default 2021-01-01.")
    parser.add_argument("--until", default=None, help="ISO end date, default now.")
    parser.add_argument("--assets", default="", help="Comma-separated asset filter, default live earn products.")
    parser.add_argument("--max-pages", type=int, default=10, help="Max pages per endpoint/window.")
    parser.add_argument("--max-records", type=int, default=50000, help="Max records overall.")
    parser.add_argument("--db", default=str(ROOT / "data" / "steuerreport_v2.duckdb"))
    args = parser.parse_args()

    started = datetime.now(UTC)
    run_id = started.strftime("%Y%m%dT%H%M%SZ")
    out_dir = ROOT / "var" / "binance_simple_earn_history" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    since = parse_datetime(args.since)
    until = parse_datetime(args.until) if args.until else None
    assets = [item.strip().upper() for item in args.assets.split(",") if item.strip()]

    report = BinanceEarnHistoryService(DuckDbStore(args.db)).api_preview(
        since=since,
        until=until,
        assets=assets or None,
        max_pages=args.max_pages,
        max_records=args.max_records,
    )
    payload = report.model_dump(mode="json")
    write_json(out_dir / "binance_simple_earn_history_preview.json", payload)
    write_csv(out_dir / "binance_simple_earn_records.csv", payload.get("records", []))
    write_json(
        out_dir / "manifest.json",
        {
            "run_id": run_id,
            "mode": "read_only_binance_simple_earn_history_harvest",
            "started_at": started.isoformat(),
            "finished_at": datetime.now(UTC).isoformat(),
            "db": str(Path(args.db)),
            "since": payload.get("since"),
            "until": payload.get("until"),
            "credential_status": payload.get("credential_status"),
            "records_returned": payload.get("records_returned"),
            "records_available_hint": payload.get("records_available_hint"),
            "truncated": payload.get("truncated"),
            "requests": len(payload.get("requests", [])),
            "files": [
                "binance_simple_earn_history_preview.json",
                "binance_simple_earn_records.csv",
                "manifest.json",
                "summary.md",
            ],
            "rules": [
                "read-only Binance API calls",
                "no database writes",
                "no raw import",
                "no canonical events",
                "no FIFO or ledger changes",
                "no secrets written",
            ],
        },
    )
    (out_dir / "summary.md").write_text(build_summary(payload, out_dir), encoding="utf-8")
    print(str(out_dir))
    return 0


def parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_csv(path: Path, records: list[dict[str, Any]]) -> None:
    fieldnames = [
        "record_type",
        "endpoint",
        "asset",
        "product_id",
        "position_id",
        "payload_asset",
        "payload_amount",
        "payload_rewards",
        "payload_principal",
        "payload_time",
        "payload_status",
        "payload_type",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
            writer.writerow(
                {
                    "record_type": record.get("record_type"),
                    "endpoint": record.get("endpoint"),
                    "asset": record.get("asset"),
                    "product_id": record.get("product_id"),
                    "position_id": record.get("position_id"),
                    "payload_asset": payload.get("asset"),
                    "payload_amount": payload.get("amount"),
                    "payload_rewards": payload.get("rewards"),
                    "payload_principal": payload.get("principal"),
                    "payload_time": payload.get("time"),
                    "payload_status": payload.get("status"),
                    "payload_type": payload.get("type"),
                }
            )


def build_summary(payload: dict[str, Any], out_dir: Path) -> str:
    requests = payload.get("requests", [])
    records = payload.get("records", [])
    request_status = Counter(str(item.get("status")) for item in requests if isinstance(item, dict))
    record_types = Counter(str(item.get("record_type")) for item in records if isinstance(item, dict))
    lines = [
        "# Binance Simple Earn History Harvest",
        "",
        f"Output: `{out_dir}`",
        f"Credential status: `{payload.get('credential_status')}`",
        f"Since: `{payload.get('since')}`",
        f"Until: `{payload.get('until')}`",
        f"Records returned: `{payload.get('records_returned')}`",
        f"Records available hint: `{payload.get('records_available_hint')}`",
        f"Truncated: `{payload.get('truncated')}`",
        f"Requests: `{len(requests)}`",
        "",
        "## Request Status",
        "",
    ]
    lines.extend(f"- `{key}`: `{value}`" for key, value in sorted(request_status.items()))
    lines.extend(["", "## Record Types", ""])
    lines.extend(f"- `{key}`: `{value}`" for key, value in sorted(record_types.items()))
    lines.extend(
        [
            "",
            "## Files",
            "",
            "- `binance_simple_earn_history_preview.json`",
            "- `binance_simple_earn_records.csv`",
            "- `manifest.json`",
            "",
            "No database, FIFO, ledger, tax or import data was changed.",
        ]
    )
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
