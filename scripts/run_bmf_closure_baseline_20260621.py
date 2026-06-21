#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "var" / "bmf_closure_2021_2025"
DEFAULT_API_BASE = "http://127.0.0.1:8010"
DEFAULT_YEARS = [2021, 2022, 2023, 2024, 2025]


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only BMF closure baseline export for tax years 2021-2025.")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--years", default=",".join(str(year) for year in DEFAULT_YEARS))
    parser.add_argument("--include-packages", action="store_true", help="Also download evidence package ZIPs.")
    parser.add_argument("--include-slow-detail", action="store_true", help="Also fetch slower secondary review endpoints.")
    args = parser.parse_args()

    years = [int(item.strip()) for item in args.years.split(",") if item.strip()]
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = OUT_ROOT / f"run_{run_id}"
    raw_dir = out / "raw"
    package_dir = out / "packages"
    raw_dir.mkdir(parents=True, exist_ok=True)
    package_dir.mkdir(parents=True, exist_ok=True)

    api_base = args.api_base.rstrip("/")
    summary: dict[str, Any] = {
        "run_id": run_id,
        "generated_at": datetime.now(UTC).isoformat(),
        "api_base": api_base,
        "mode": "readonly_bmf_closure_baseline",
        "years": [],
        "rules": [
            "No database writes.",
            "No imports.",
            "No review decisions.",
            "No FIFO rebuild.",
            "Evidence packages are downloaded as immutable baseline artifacts.",
        ],
    }

    global_endpoints = {
        "health": "/api/v1/health",
        "review_gates": "/api/v1/review/gates",
        "portfolio_snapshot": "/api/v1/portfolio/snapshot",
        "price_coverage": "/api/v1/prices/coverage",
        "tax_methodology_summary": "/api/v1/tax-methodology/summary",
    }
    for name, path in global_endpoints.items():
        print(f"global {name} {path}", flush=True)
        try:
            payload = fetch_json(api_base, path)
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            payload = {
                "status": "error",
                "data": {},
                "errors": [{"message": f"{type(exc).__name__}: {exc}", "path": path}],
                "warnings": [],
            }
        write_json(raw_dir / f"{name}.json", payload)

    for year in years:
        year_dir = raw_dir / str(year)
        year_dir.mkdir(parents=True, exist_ok=True)
        endpoints = {
            "methodology": f"/api/v1/tax-years/{year}/methodology",
            "filing_summary": f"/api/v1/tax-years/{year}/filing-summary",
            "evidence": f"/api/v1/tax-years/{year}/evidence",
            "wallet_fifo_delta": f"/api/v1/tax-years/{year}/wallet-fifo-delta",
            "wallet_fifo_gaps": f"/api/v1/tax-years/{year}/wallet-fifo-gaps?limit=500",
            "wallet_fifo_provenance_closure": f"/api/v1/tax-years/{year}/wallet-fifo-provenance-closure?limit=500",
        }
        if args.include_slow_detail:
            endpoints.update(
                {
                    "wallet_fifo_origin_trace": f"/api/v1/tax-years/{year}/wallet-fifo-origin-trace?limit=200",
                    "income_guide": f"/api/v1/tax-years/{year}/income-guide",
                    "turnover_audit": f"/api/v1/tax-years/{year}/turnover-audit?limit=50",
                    "stablecoin_fifo_review": f"/api/v1/tax-years/{year}/stablecoin-fifo-review?limit=50",
                }
            )
        year_payloads: dict[str, dict[str, Any]] = {}
        for name, path in endpoints.items():
            print(f"{year} {name} {path}", flush=True)
            try:
                payload = fetch_json(api_base, path)
            except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
                payload = {
                    "status": "error",
                    "data": {},
                    "errors": [{"message": f"{type(exc).__name__}: {exc}", "path": path}],
                    "warnings": [],
                }
            write_json(year_dir / f"{name}.json", payload)
            year_payloads[name] = payload

        package_path = None
        package_size = None
        package_error = None
        if args.include_packages:
            try:
                print(f"{year} evidence_package", flush=True)
                package_bytes = fetch_bytes(api_base, f"/api/v1/export/tax-years/{year}/evidence-package.zip")
                package_path = package_dir / f"tax-year-{year}-evidence-package.zip"
                package_path.write_bytes(package_bytes)
                package_size = len(package_bytes)
            except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
                package_error = f"{type(exc).__name__}: {exc}"

        summary["years"].append(summarize_year(year, year_payloads, package_path, package_size, package_error))

    write_json(out / "summary.json", summary)
    (out / "summary.md").write_text(render_summary(summary), encoding="utf-8")
    print(json.dumps({"status": "ok", "output": str(out), "years": years}, indent=2))
    return 0


def fetch_json(api_base: str, path: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"{api_base}{path}", timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_bytes(api_base: str, path: str) -> bytes:
    with urllib.request.urlopen(f"{api_base}{path}", timeout=240) as response:
        return response.read()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def data(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("data")
    return value if isinstance(value, dict) else {}


def summarize_year(
    year: int,
    payloads: dict[str, dict[str, Any]],
    package_path: Path | None,
    package_size: int | None,
    package_error: str | None,
) -> dict[str, Any]:
    methodology = data(payloads["methodology"])
    filing = data(payloads["filing_summary"])
    delta = data(payloads["wallet_fifo_delta"])
    gaps = data(payloads["wallet_fifo_gaps"])
    closure = data(payloads["wallet_fifo_provenance_closure"])
    return {
        "year": year,
        "bmf_status": methodology.get("status"),
        "bmf_ready": methodology.get("bmf_ready"),
        "methodology_gap_count": len(methodology.get("gaps") or methodology.get("open_gaps") or []),
        "methodology_gap_codes": sorted(
            {
                str(gap.get("code") or gap.get("gap_code") or gap.get("id") or gap.get("category"))
                for gap in (methodology.get("gaps") or methodology.get("open_gaps") or [])
                if isinstance(gap, dict)
            }
        ),
        "export_ready": filing.get("export_ready"),
        "taxable_private_disposals_eur": filing.get("taxable_private_disposals_eur"),
        "income_rewards_mining_staking_eur": filing.get("income_rewards_mining_staking_eur"),
        "wallet_fifo_unmatched_count": delta.get("unmatched_count"),
        "wallet_fifo_gap_count": gaps.get("gaps_count"),
        "wallet_fifo_likely_causes": gaps.get("likely_causes") or {},
        "closure_unresolved_inbound_provenance_count": closure.get("unresolved_inbound_provenance_count"),
        "closure_groups_count": closure.get("groups_count"),
        "closure_review_required_count": closure.get("review_required_count"),
        "closure_statuses": [
            {
                "category": item.get("category"),
                "closure_status": item.get("closure_status"),
                "asset": item.get("asset"),
                "source": item.get("source"),
                "events_count": item.get("events_count"),
                "requires_review": item.get("requires_review"),
            }
            for item in (closure.get("items") or [])
            if isinstance(item, dict)
        ],
        "package_path": str(package_path.relative_to(ROOT)) if package_path else None,
        "package_size_bytes": package_size,
        "package_error": package_error,
    }


def render_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# BMF Closure Baseline 2021-2025",
        "",
        f"- Run: `{summary['run_id']}`",
        f"- API: `{summary['api_base']}`",
        f"- Modus: `{summary['mode']}`",
        "",
        "| Jahr | BMF | Ready | Gaps | FIFO-Luecken | Offene Herkunft | Closure Review | Private G/V EUR | Export |",
        "|---:|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for year in summary["years"]:
        lines.append(
            f"| {year['year']} | {year['bmf_status']} | {year['bmf_ready']} | "
            f"{year['methodology_gap_count']} | {year['wallet_fifo_unmatched_count']} | "
            f"{year['closure_unresolved_inbound_provenance_count']} | {year['closure_review_required_count']} | "
            f"{year['taxable_private_disposals_eur']} | {year['export_ready']} |"
        )
    lines.extend(["", "## Closure-Gruppen", ""])
    for year in summary["years"]:
        lines.append(f"### {year['year']}")
        statuses = year["closure_statuses"]
        if not statuses:
            lines.append("")
            lines.append("Keine Closure-Review-Gruppen.")
            lines.append("")
            continue
        for item in statuses:
            lines.append(
                "- "
                f"`{item['asset']}` `{item['source']}` `{item['closure_status']}` "
                f"Events={item['events_count']} Review={item['requires_review']}"
            )
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
