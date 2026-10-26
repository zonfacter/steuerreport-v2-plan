#!/usr/bin/env python3
from __future__ import annotations

from steuerreport_v2.private_settings import private_value

import argparse
import csv
import io
import json
import os
import shutil
import urllib.error
import urllib.request
from steuerreport_v2.domain.external_http import managed_urlopen
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_methodology import TaxMethodologyService
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService


ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "var" / "local_ai_prework" / "wallet_fifo_provenance_review_20260620"
DB_PATH = ROOT / "data" / "steuerreport_v2.duckdb"
LLM_BASE = os.environ.get("LOCAL_LLM_BASE") or private_value("local_llm_base") or "http://127.0.0.1:11435/v1"
LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL") or private_value("local_llm_model") or "local-model"
DEFAULT_YEARS = [2021, 2022, 2023, 2024, 2025, 2026]


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only local AI review for Wallet-/Depot-FIFO provenance gaps.")
    parser.add_argument("--dry-run", action="store_true", help="Skip local LLM call.")
    parser.add_argument("--years", default=",".join(str(year) for year in DEFAULT_YEARS))
    parser.add_argument("--gap-limit", type=int, default=240)
    parser.add_argument("--origin-limit", type=int, default=80)
    parser.add_argument("--withdrawal-limit", type=int, default=120)
    parser.add_argument("--keep-work-db", action="store_true", help="Keep the temporary DuckDB snapshot in the run directory.")
    args = parser.parse_args()

    years = [int(item.strip()) for item in args.years.split(",") if item.strip()]
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = OUT_ROOT / f"run_{run_id}"
    raw_dir = out / "raw"
    reports_dir = out / "reports"
    raw_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    work_db_path = out / "steuerreport_v2_readonly_snapshot.duckdb"
    shutil.copy2(DB_PATH, work_db_path)
    store = DuckDbStore(work_db_path)
    methodology = TaxMethodologyService(store)
    wallet_fifo = WalletFifoPreviewService(store)

    year_reports: list[dict[str, Any]] = []
    all_groups: list[dict[str, Any]] = []
    for year in years:
        action_plan = methodology.bmf_action_plan(year=year)
        delta = wallet_fifo.preview(year=year)
        gaps = wallet_fifo.gap_diagnosis(year=year, limit=args.gap_limit)
        origin = wallet_fifo.origin_trace(year=year, limit=args.origin_limit)
        withdrawal = wallet_fifo.withdrawal_gap_trace(year=year, limit=args.withdrawal_limit)

        write_json(raw_dir / f"{year}_bmf_action_plan.json", action_plan.model_dump(mode="json"))
        write_json(raw_dir / f"{year}_wallet_fifo_delta.json", delta.model_dump(mode="json"))
        write_json(raw_dir / f"{year}_wallet_fifo_gaps.json", gaps.model_dump(mode="json"))
        write_json(raw_dir / f"{year}_wallet_fifo_origin_trace.json", origin.model_dump(mode="json"))
        write_json(raw_dir / f"{year}_wallet_fifo_withdrawal_gaps.json", withdrawal.model_dump(mode="json"))

        groups = group_gap_diagnoses(year, gaps.model_dump(mode="json"), origin.model_dump(mode="json"), withdrawal.model_dump(mode="json"))
        all_groups.extend(groups)
        year_reports.append(
            {
                "year": year,
                "bmf_status": action_plan.blocked_years and "blocked" or action_plan.review_years and "review" or "ok",
                "blocking_items_count": action_plan.blocking_items_count,
                "wallet_unmatched_count": delta.unmatched_count,
                "wallet_delta_gain_loss_eur": str(delta.delta_gain_loss_eur),
                "likely_causes": gaps.likely_causes,
                "groups_count": len(groups),
                "top_groups": groups[:12],
            }
        )

    groups_csv = reports_dir / "wallet_fifo_gap_groups.csv"
    write_csv(groups_csv, all_groups)
    payload = {
        "package": "wallet_fifo_provenance_review_20260620",
        "run_id": run_id,
        "started_at": run_id,
        "finished_at": datetime.now(UTC).isoformat(),
        "mode": "readonly_local_ai_wallet_fifo_provenance_review",
        "db_path": str(DB_PATH),
        "work_db_path": str(work_db_path),
        "llm_base": LLM_BASE,
        "llm_model": LLM_MODEL,
        "years": year_reports,
        "groups_count": len(all_groups),
        "blocking_groups_count": sum(1 for group in all_groups if group["blocks_bmf_ready"]),
        "groups_csv": str(groups_csv.relative_to(ROOT)),
        "rules": [
            "No database writes.",
            "No imports.",
            "No FIFO rebuild.",
            "No review decisions.",
            "No synthetic opening balances.",
            "Only propose evidence-backed transfer/opening-balance work items.",
            "Codex must verify every recommendation before implementation.",
        ],
    }
    payload["status"] = "review" if payload["blocking_groups_count"] else "ok"
    write_json(out / "findings.json", payload)
    (out / "summary.md").write_text(render_summary(payload), encoding="utf-8")

    if args.dry_run:
        (out / "local_ai_review.md").write_text(
            "# Lokale KI Wallet-FIFO-Provenance Review\n\nDry-Run: lokale KI wurde nicht aufgerufen.\n",
            encoding="utf-8",
        )
        llm_status = "dry_run"
    else:
        review, llm_status = call_llm(build_prompt(payload, all_groups[:80]))
        (out / "local_ai_review.md").write_text(review.strip() + "\n", encoding="utf-8")

    payload["llm_status"] = llm_status
    if not args.keep_work_db:
        try:
            work_db_path.unlink(missing_ok=True)
            payload["work_db_removed"] = True
        except OSError as exc:
            payload["work_db_removed"] = False
            payload["work_db_cleanup_error"] = f"{type(exc).__name__}: {exc}"
    write_json(out / "run_status.json", payload)
    print(
        json.dumps(
            {
                "status": payload["status"],
                "llm_status": llm_status,
                "output": str(out),
                "groups": payload["groups_count"],
                "blocking_groups": payload["blocking_groups_count"],
            },
            indent=2,
        )
    )
    return 0


def group_gap_diagnoses(
    year: int,
    gaps: dict[str, Any],
    origin: dict[str, Any],
    withdrawal: dict[str, Any],
) -> list[dict[str, Any]]:
    origin_by_key = defaultdict(list)
    for trace in origin.get("traces") or []:
        origin_by_key[(trace.get("asset"), trace.get("pool_id"))].append(trace)

    withdrawal_by_key = defaultdict(list)
    for trace in withdrawal.get("traces") or []:
        withdrawal_by_key[(trace.get("asset"), trace.get("pool_id"))].append(trace)

    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for diagnosis in gaps.get("diagnoses") or []:
        key = (
            str(diagnosis.get("likely_cause") or "unknown"),
            str(diagnosis.get("asset") or ""),
            str(diagnosis.get("pool_id") or ""),
        )
        entry = grouped.setdefault(
            key,
            {
                "year": year,
                "likely_cause": key[0],
                "asset": key[1],
                "pool_id": key[2],
                "gaps_count": 0,
                "missing_quantity_total": "0",
                "candidate_relations": {},
                "withdrawal_candidates_count": 0,
                "ready_withdrawal_candidates_count": 0,
                "sample_gap_ids": [],
                "sample_candidate_events": [],
                "recommended_action": diagnosis.get("recommended_action") or "",
                "blocks_bmf_ready": True,
            },
        )
        entry["gaps_count"] += 1
        entry["missing_quantity_total"] = str_decimal_add(
            entry["missing_quantity_total"],
            diagnosis.get("missing_quantity"),
        )
        if len(entry["sample_gap_ids"]) < 8:
            entry["sample_gap_ids"].append(diagnosis.get("gap_id"))
        relation_counter = Counter()
        for candidate in diagnosis.get("candidate_events") or []:
            relation = str(candidate.get("relation") or "unknown")
            relation_counter[relation] += 1
            if relation != "gap_event" and len(entry["sample_candidate_events"]) < 8:
                entry["sample_candidate_events"].append(
                    {
                        "event_id": candidate.get("event_id"),
                        "event_time": candidate.get("event_time"),
                        "source": candidate.get("source"),
                        "account": candidate.get("account"),
                        "pool_id": candidate.get("pool_id"),
                        "quantity": candidate.get("quantity"),
                        "tx_id": candidate.get("tx_id"),
                        "relation": relation,
                        "raw_object_id": candidate.get("raw_object_id"),
                    }
                )
        for relation, count in relation_counter.items():
            entry["candidate_relations"][relation] = entry["candidate_relations"].get(relation, 0) + count

    for key, entry in grouped.items():
        asset_pool = (entry["asset"], entry["pool_id"])
        withdrawal_traces = withdrawal_by_key.get(asset_pool, [])
        ready = 0
        candidates = 0
        for trace in withdrawal_traces:
            for candidate in trace.get("candidates") or []:
                candidates += 1
                if candidate.get("status") == "ready_for_transfer_anchor":
                    ready += 1
        entry["withdrawal_candidates_count"] = candidates
        entry["ready_withdrawal_candidates_count"] = ready
        entry["origin_traces_count"] = len(origin_by_key.get(asset_pool, []))
        entry["priority"] = priority_for_group(entry)

    return sorted(grouped.values(), key=lambda item: (item["priority"], -item["gaps_count"], item["year"], item["asset"], item["pool_id"]))


def priority_for_group(group: dict[str, Any]) -> int:
    cause = str(group.get("likely_cause") or "")
    if int(group.get("ready_withdrawal_candidates_count") or 0) > 0:
        return 10
    if cause == "unresolved_inbound_transfer_or_opening_balance":
        return 20
    if cause == "possible_cross_pool_transfer_missing_link":
        return 30
    if cause == "quote_asset_disposal_without_pool_lot":
        return 40
    return 50


def str_decimal_add(left: object, right: object) -> str:
    from decimal import Decimal

    return str(Decimal(str(left or "0")) + Decimal(str(right or "0")))


def render_summary(payload: dict[str, Any]) -> str:
    lines = [
        "# Wallet-FIFO Provenance Review",
        "",
        f"- Status: `{payload['status']}`",
        f"- Lokale KI Modellziel: `{payload['llm_model']}`",
        f"- Gruppen: `{payload['groups_count']}`",
        f"- Blockierende Gruppen: `{payload['blocking_groups_count']}`",
        f"- CSV: `{payload['groups_csv']}`",
        "",
        "| Jahr | BMF | Wallet unmatched | Wallet-Delta EUR | Gruppen | Ursachen |",
        "|---:|---|---:|---:|---:|---|",
    ]
    for report in payload["years"]:
        causes = ", ".join(f"{key}: {value}" for key, value in (report.get("likely_causes") or {}).items()) or "-"
        lines.append(
            f"| {report['year']} | {report['bmf_status']} | {report['wallet_unmatched_count']} | "
            f"{report['wallet_delta_gain_loss_eur']} | {report['groups_count']} | {causes} |"
        )
    lines.extend(["", "## Top-Gruppen", ""])
    for report in payload["years"]:
        lines.append(f"### {report['year']}")
        if not report["top_groups"]:
            lines.append("- Keine Wallet-FIFO-Gruppen.")
        for group in report["top_groups"]:
            lines.append(
                f"- `{group['asset']}` `{group['pool_id']}`: {group['gaps_count']} Gap(s), "
                f"Ursache `{group['likely_cause']}`, fehlende Menge `{group['missing_quantity_total']}`, "
                f"Withdrawal-Kandidaten `{group['withdrawal_candidates_count']}`."
            )
        lines.append("")
    lines.extend(
        [
            "## Regeln",
            "",
            "- Read-only: keine DB-Schreiboperationen, keine Imports, kein FIFO-Rebuild.",
            "- KI-Empfehlungen sind Arbeitsvorschlaege und muessen vor Umsetzung im Code/Belegpfad geprueft werden.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_prompt(payload: dict[str, Any], groups: list[dict[str, Any]]) -> str:
    compact = {
        "package": payload["package"],
        "status": payload["status"],
        "rules": payload["rules"],
        "years": payload["years"],
        "top_groups": groups,
    }
    return (
        "Du bist ein lokaler read-only Steuer/FIFO-Pruefer. Analysiere Wallet-/Depot-FIFO-Provenance-Luecken. "
        "Erstelle eine priorisierte Arbeitsliste fuer Codex: Welche Gruppen sind wahrscheinlich interne Transfers, "
        "Opening Balances, fehlende Imports oder manuelle Fachentscheidungen? "
        "Keine Steuerdaten veraendern, keine synthetischen Daten fordern ohne Beleg. "
        "Antworte strukturiert auf Deutsch mit: Prioritaet, Befund, Belege/Endpoints, empfohlener naechster technischer Schritt.\n\n"
        + json.dumps(compact, ensure_ascii=False, indent=2)
    )


def call_llm(prompt: str) -> tuple[str, str]:
    url = f"{LLM_BASE.rstrip('/')}/chat/completions"
    body = {
        "model": LLM_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "Du bist ein strenger read-only Auditor fuer Crypto FIFO, BMF-Nachweise und Wallet-Provenance.",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 6000,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with managed_urlopen(req, timeout=900) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"].get("content") or "", "ok"
    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
        return f"# Lokale KI Review fehlgeschlagen\n\n`{type(exc).__name__}: {exc}`\n", "failed"


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    output = io.StringIO()
    fieldnames = sorted({key for row in rows for key in row.keys() if key != "sample_candidate_events"})
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        csv_row = {key: json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, (dict, list)) else value for key, value in row.items() if key in fieldnames}
        writer.writerow(csv_row)
    path.write_text(output.getvalue(), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
