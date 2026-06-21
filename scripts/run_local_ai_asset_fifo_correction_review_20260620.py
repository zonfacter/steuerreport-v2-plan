#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import urllib.error
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_years import TaxYearService


ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "var" / "local_ai_prework" / "asset_fifo_correction_review_20260620"
DB_PATH = ROOT / "data" / "steuerreport_v2.duckdb"
LLM_BASE = os.environ.get("LOCAL_LLM_BASE", "http://192.168.2.155:11435/v1")
LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "qwen3.6-35b-a3b-iq4xs-xt7900")
DEFAULT_YEARS = [2024, 2025]


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only local AI review for asset FIFO correction candidates.")
    parser.add_argument("--dry-run", action="store_true", help="Skip local LLM call.")
    parser.add_argument("--years", default=",".join(str(year) for year in DEFAULT_YEARS))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--min-abs-gain-eur", default="100")
    args = parser.parse_args()

    years = [int(item.strip()) for item in args.years.split(",") if item.strip()]
    min_abs_gain = Decimal(str(args.min_abs_gain_eur))
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = OUT_ROOT / f"run_{run_id}"
    raw_dir = out / "raw"
    candidates_dir = out / "candidates"
    raw_dir.mkdir(parents=True, exist_ok=True)
    candidates_dir.mkdir(parents=True, exist_ok=True)

    store = DuckDbStore(DB_PATH)
    service = TaxYearService(store)
    year_reports: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    for year in years:
        report = service.asset_fifo_correction_review(
            year,
            limit=args.limit,
            min_abs_gain_eur=min_abs_gain,
        )
        report_json = report.model_dump(mode="json")
        write_json(raw_dir / f"correction_review_{year}.json", report_json)
        year_entry = {
            "year": year,
            "rows_count": report.rows_count,
            "possible_recalculation_assets_count": report.possible_recalculation_assets_count,
            "attribution_review_assets_count": report.attribution_review_assets_count,
            "no_action_assets_count": report.no_action_assets_count,
            "candidate_assets": [],
        }
        for row in report.rows:
            if row.tax_sum_impact != "possible_recalculation_after_review":
                continue
            candidate = build_candidate_package(store, row.model_dump(mode="json"), candidates_dir)
            candidates.append(candidate)
            year_entry["candidate_assets"].append(row.asset)
        year_reports.append(year_entry)

    payload = {
        "package": "asset_fifo_correction_review_20260620",
        "run_id": run_id,
        "started_at": run_id,
        "finished_at": datetime.now(UTC).isoformat(),
        "mode": "readonly_local_ai_asset_fifo_correction_review",
        "db_path": str(DB_PATH),
        "llm_base": LLM_BASE,
        "llm_model": LLM_MODEL,
        "years": year_reports,
        "candidates": candidates,
        "rules": [
            "No database writes.",
            "No imports.",
            "No FIFO rebuild.",
            "No review decisions.",
            "Linked quote values are not extra taxable sums.",
            "Codex must verify every recommendation before implementation.",
        ],
    }
    status = "review" if candidates else "ok"
    payload["status"] = status
    write_json(out / "findings.json", payload)
    (out / "summary.md").write_text(render_summary(payload), encoding="utf-8")

    if args.dry_run:
        (out / "local_ai_review.md").write_text(
            "# Lokale KI Review\n\nDry-Run: lokale KI wurde nicht aufgerufen.\n",
            encoding="utf-8",
        )
        llm_status = "dry_run"
    else:
        review, llm_status = call_llm(build_prompt(payload))
        (out / "local_ai_review.md").write_text(review.strip() + "\n", encoding="utf-8")

    payload["llm_status"] = llm_status
    write_json(out / "run_status.json", payload)
    print(json.dumps({"status": status, "llm_status": llm_status, "output": str(out), "candidates": len(candidates)}, indent=2))
    return 0


def build_candidate_package(store: DuckDbStore, row: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    year = int(row["year"])
    asset = str(row["asset"]).upper()
    rows = related_tax_lines(store, year, asset)
    safe_asset = asset.replace("/", "_")
    csv_path = out_dir / f"{year}_{safe_asset}_related_tax_lines.csv"
    json_path = out_dir / f"{year}_{safe_asset}_candidate.json"
    write_csv(csv_path, rows)
    candidate = {
        "year": year,
        "asset": asset,
        "risk_level": row["risk_level"],
        "recommended_action": row["recommended_action"],
        "tax_sum_impact": row["tax_sum_impact"],
        "direct_gain_loss_eur": row["direct_gain_loss_eur"],
        "linked_gain_loss_eur": row["linked_gain_loss_eur"],
        "direct_tax_lines_count": row["direct_tax_lines_count"],
        "linked_tax_lines_count": row["linked_tax_lines_count"],
        "related_raw_evidence_count": row["related_raw_evidence_count"],
        "related_missing_raw_evidence_count": row["related_missing_raw_evidence_count"],
        "conclusion": row["conclusion"],
        "next_step": row["next_step"],
        "reasons": row["reasons"],
        "related_tax_lines_count": len(rows),
        "related_tax_lines_csv": str(csv_path.relative_to(ROOT)),
        "candidate_json": str(json_path.relative_to(ROOT)),
        "first_related_lines": rows[:12],
    }
    write_json(json_path, candidate)
    return candidate


def related_tax_lines(store: DuckDbStore, year: int, asset: str) -> list[dict[str, Any]]:
    with store.connect() as con:
        rows = con.execute(
            """
            select
                l.tax_line_id,
                l.asset as tax_asset,
                l.quantity,
                lot.acquired_at,
                l.disposed_at,
                l.holding_days,
                l.acquisition_cost_eur,
                l.disposal_proceeds_eur,
                l.gain_loss_eur,
                de.event_id as disposal_event_id,
                de.source as disposal_source,
                de.event_type as disposal_event_type,
                de.asset as disposal_asset,
                de.quantity as disposal_quantity,
                de.quote_asset as disposal_quote_asset,
                de.quote_quantity as disposal_quote_quantity,
                de.raw_object_id as disposal_raw_object_id,
                db.filename as disposal_filename,
                dr.row_number as disposal_row_number,
                dr.payload_json as disposal_payload_json,
                ae.event_id as acquisition_event_id,
                ae.source as acquisition_source,
                ae.event_type as acquisition_event_type,
                ae.asset as acquisition_asset,
                ae.quantity as acquisition_quantity,
                ae.quote_asset as acquisition_quote_asset,
                ae.quote_quantity as acquisition_quote_quantity,
                ae.raw_object_id as acquisition_raw_object_id,
                ab.filename as acquisition_filename,
                ar.row_number as acquisition_row_number,
                ar.payload_json as acquisition_payload_json
            from tax_lines l
            join tax_lots lot on lot.lot_id = l.lot_id
            left join canonical_events de on de.event_id = l.source_event_id
            left join canonical_events ae on ae.event_id = lot.source_event_id
            left join raw_objects dr on dr.raw_object_id = de.raw_object_id
            left join raw_import_batches db on db.batch_id = dr.batch_id
            left join raw_objects ar on ar.raw_object_id = ae.raw_object_id
            left join raw_import_batches ab on ab.batch_id = ar.batch_id
            where date_part('year', l.disposed_at)::integer = ?
              and (
                  upper(l.asset) = ?
                  or upper(coalesce(de.asset, '')) = ?
                  or upper(coalesce(de.quote_asset, '')) = ?
                  or upper(coalesce(ae.asset, '')) = ?
                  or upper(coalesce(ae.quote_asset, '')) = ?
              )
            order by l.disposed_at, l.tax_line_id
            """,
            [year, asset, asset, asset, asset, asset],
        ).fetchall()
    columns = [
        "tax_line_id",
        "tax_asset",
        "quantity",
        "acquired_at",
        "disposed_at",
        "holding_days",
        "acquisition_cost_eur",
        "disposal_proceeds_eur",
        "gain_loss_eur",
        "disposal_event_id",
        "disposal_source",
        "disposal_event_type",
        "disposal_asset",
        "disposal_quantity",
        "disposal_quote_asset",
        "disposal_quote_quantity",
        "disposal_raw_object_id",
        "disposal_filename",
        "disposal_row_number",
        "disposal_payload_json",
        "acquisition_event_id",
        "acquisition_source",
        "acquisition_event_type",
        "acquisition_asset",
        "acquisition_quantity",
        "acquisition_quote_asset",
        "acquisition_quote_quantity",
        "acquisition_raw_object_id",
        "acquisition_filename",
        "acquisition_row_number",
        "acquisition_payload_json",
    ]
    return [dict(zip(columns, row, strict=True)) for row in rows]


def render_summary(payload: dict[str, Any]) -> str:
    lines = [
        "# Asset-FIFO Korrekturreview",
        "",
        f"- Status: `{payload['status']}`",
        f"- Lokale KI Modellziel: `{payload['llm_model']}`",
        f"- Kandidaten mit moeglicher Neubewertung: `{len(payload['candidates'])}`",
        "",
        "| Jahr | Zeilen | moegliche Neubewertung | Attributionsreview | Kandidaten |",
        "|---:|---:|---:|---:|---|",
    ]
    for report in payload["years"]:
        lines.append(
            f"| {report['year']} | {report['rows_count']} | "
            f"{report['possible_recalculation_assets_count']} | "
            f"{report['attribution_review_assets_count']} | "
            f"{', '.join(report['candidate_assets']) or '-'} |"
        )
    lines.extend(["", "## Kandidaten", ""])
    if not payload["candidates"]:
        lines.append("Keine Kandidaten mit moeglicher Neubewertung.")
    for candidate in payload["candidates"]:
        lines.append(
            f"- `{candidate['year']} {candidate['asset']}`: "
            f"direct `{candidate['direct_gain_loss_eur']}`, "
            f"linked `{candidate['linked_gain_loss_eur']}`, "
            f"related lines `{candidate['related_tax_lines_count']}`, "
            f"CSV `{candidate['related_tax_lines_csv']}`"
        )
    lines.append("")
    return "\n".join(lines)


def build_prompt(payload: dict[str, Any]) -> str:
    compact = {
        "status": payload["status"],
        "years": payload["years"],
        "candidates": [
            {
                "year": candidate["year"],
                "asset": candidate["asset"],
                "risk_level": candidate["risk_level"],
                "tax_sum_impact": candidate["tax_sum_impact"],
                "direct_gain_loss_eur": candidate["direct_gain_loss_eur"],
                "linked_gain_loss_eur": candidate["linked_gain_loss_eur"],
                "direct_tax_lines_count": candidate["direct_tax_lines_count"],
                "linked_tax_lines_count": candidate["linked_tax_lines_count"],
                "related_tax_lines_count": candidate["related_tax_lines_count"],
                "reasons": candidate["reasons"],
                "first_related_lines": candidate["first_related_lines"],
            }
            for candidate in payload["candidates"]
        ],
    }
    return (
        "Du bist lokale KI fuer Steuerreport V2. Arbeite ausschliesslich im Readonly-Modus.\n"
        "Aufgabe: Pruefe Asset-FIFO-Korrekturkandidaten. Wichtig: linked_gain_loss_eur ist "
        "kein zusaetzlicher Steuerbetrag, sondern ein Plausibilitaets-/Attributionssignal.\n"
        "Bewerte fuer jeden Kandidaten:\n"
        "1. Ist eher nur Darstellung/Attribution betroffen oder Normalizer/FIFO?\n"
        "2. Welche Raw-Zeilen/Felder muss Codex als erstes pruefen?\n"
        "3. Welche konkrete Hypothese erklaert die Abweichung?\n"
        "4. Darf eine Steuerjahressumme schon geaendert werden? Antworte nur mit nein, "
        "ausser die gelieferten Daten beweisen einen Fehler eindeutig.\n"
        "Gib knappe, priorisierte Findings aus.\n\n"
        f"Kontext:\n{json.dumps(compact, ensure_ascii=False, indent=2, default=str)}"
    )


def call_llm(prompt: str) -> tuple[str, str]:
    data = json.dumps(
        {
            "model": LLM_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
            "max_tokens": 3000,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{LLM_BASE.rstrip('/')}/chat/completions",
        data=data,
        headers={"content-type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=1800) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return payload["choices"][0]["message"]["content"], "ok"
    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
        return f"# Lokale KI Aufgabe fehlgeschlagen\n\n`{type(exc).__name__}: {exc}`\n", "failed"


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    path.write_text(buffer.getvalue(), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
