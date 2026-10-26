#!/usr/bin/env python3
from __future__ import annotations

from steuerreport_v2.private_settings import private_value

import argparse
import json
import os
import textwrap
import time
import urllib.error
import urllib.request
from steuerreport_v2.domain.external_http import managed_urlopen
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "var" / "local_ai_prework" / "packages" / "source_fifo_overnight_xt7900_20260613"
DB_PATH = ROOT / "data" / "steuerreport_v2.duckdb"
API_BASE = os.environ.get("STEUERREPORT_V2_API", "http://127.0.0.1:8010")
LLM_BASE = os.environ.get("LOCAL_LLM_BASE") or private_value("local_llm_base") or "http://127.0.0.1:11435/v1"
LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL") or private_value("local_llm_model") or "local-model"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run read-only XT 7900 source/FIFO overnight audit.")
    parser.add_argument("--dry-run", action="store_true", help="Prepare package without LLM calls.")
    parser.add_argument("--max-tasks", type=int, default=0, help="Limit LLM tasks, 0 means all.")
    args = parser.parse_args()

    started_at = datetime.now(UTC).isoformat()
    raw_dir = PACKAGE / "raw"
    tasks_dir = PACKAGE / "tasks"
    reports_dir = PACKAGE / "reports"
    raw_dir.mkdir(parents=True, exist_ok=True)
    tasks_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    evidence = build_evidence(raw_dir)
    tasks = build_tasks(evidence)
    if args.max_tasks > 0:
        tasks = tasks[: args.max_tasks]

    manifest = {
        "package": PACKAGE.name,
        "started_at": started_at,
        "mode": "readonly_xt7900_source_fifo_overnight",
        "api_base": API_BASE,
        "llm_base": LLM_BASE,
        "llm_model": LLM_MODEL,
        "db": str(DB_PATH.relative_to(ROOT)),
        "tasks": [
            {
                "task_id": task["task_id"],
                "title": task["title"],
                "input": f"tasks/{task['task_id']}.json",
                "report": f"reports/{task['task_id']}.md",
            }
            for task in tasks
        ],
        "rules": [
            "Read-only evidence collection.",
            "No database writes.",
            "No imports.",
            "No FIFO rebuild.",
            "No review decisions.",
            "No tax final decision.",
            "Codex must verify every recommendation before implementation.",
        ],
    }
    write_json(PACKAGE / "manifest.json", manifest)
    log_progress(f"started package={PACKAGE.name} tasks={len(tasks)} model={LLM_MODEL} base={LLM_BASE}")

    statuses: list[dict[str, str]] = []
    write_status(started_at, None, "running", statuses)
    for task in tasks:
        task_path = tasks_dir / f"{task['task_id']}.json"
        report_path = reports_dir / f"{task['task_id']}.md"
        write_json(task_path, task)
        log_progress(f"task_start task_id={task['task_id']} title={task['title']}")
        if args.dry_run:
            report = dry_run_report(task)
            status = "dry_run"
        else:
            report, status = call_llm(build_prompt(task), max_tokens=4096)
        report_path.write_text(report.strip() + "\n", encoding="utf-8")
        statuses.append({"task_id": task["task_id"], "status": status, "report": str(report_path.relative_to(PACKAGE))})
        write_status(started_at, None, "running", statuses)
        log_progress(f"task_done task_id={task['task_id']} status={status} report={report_path.relative_to(PACKAGE)}")
        time.sleep(2)

    log_progress("summary_start")
    if args.dry_run:
        summary = "# XT 7900 Source/FIFO Overnight Summary\n\nDry-Run erfolgreich. Keine lokale KI aufgerufen.\n"
        summary_status = "dry_run"
    else:
        summary, summary_status = call_llm(build_summary_prompt(statuses), max_tokens=4096)
    (reports_dir / "summary.md").write_text(summary.strip() + "\n", encoding="utf-8")
    statuses.append({"task_id": "summary", "status": summary_status, "report": "reports/summary.md"})
    log_progress(f"summary_done status={summary_status}")

    write_status(
        started_at,
        datetime.now(UTC).isoformat(),
        "ok" if all(item["status"] in {"ok", "dry_run"} for item in statuses) else "partial",
        statuses,
    )
    log_progress("finished")
    return 0


def build_evidence(raw_dir: Path) -> dict[str, Any]:
    api_state = {
        "health": get_api("health"),
        "review_gates": get_api("review/gates"),
        "sources_overview": get_api("sources/overview"),
        "portfolio_snapshot": get_api("portfolio/snapshot"),
        "portfolio_reconciliation": get_api("portfolio/reconciliation"),
        "tax_years_summary": get_api("tax-years/summary"),
        "report_center": get_api("reports/center"),
        "review_evidence_traces": get_api("review/evidence-traces"),
        "transfer_candidates": get_api("transfers/candidates"),
        "hnt_fifo_provenance": get_api("parity/hnt-fifo-provenance"),
    }
    write_json(raw_dir / "api_state.json", api_state)

    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        db_state = {
            "canonical_event_counts": query_dicts(
                con,
                """
                select
                    coalesce(source, '') as source,
                    coalesce(event_type, '') as event_type,
                    coalesce(asset, '') as asset,
                    count(*) as events,
                    min(event_time) as first_event_at,
                    max(event_time) as last_event_at
                from canonical_events
                group by source, event_type, asset
                order by events desc, source, event_type, asset
                limit 500
                """,
            ),
            "balance_negative_clusters": query_dicts(
                con,
                """
                select
                    account,
                    asset,
                    min(balance_quantity) as min_balance,
                    count(*) as negative_rows,
                    min(event_time) as first_seen_at,
                    max(event_time) as last_seen_at
                from balance_ledger
                where balance_quantity < 0
                group by account, asset
                order by abs(min_balance) desc
                limit 300
                """,
            ),
            "tax_lot_remaining_by_asset": query_dicts(
                con,
                """
                select
                    asset,
                    count(*) as lots,
                    sum(quantity_remaining) as quantity_remaining,
                    sum(cost_basis_eur_total) as cost_basis_eur_total,
                    min(acquired_at) as first_acquired_at,
                    max(acquired_at) as last_acquired_at
                from tax_lots
                where quantity_remaining != 0
                group by asset
                order by abs(sum(cost_basis_eur_total)) desc
                limit 200
                """,
            ),
            "external_like_events": query_dicts(
                con,
                """
                select
                    event_time,
                    source,
                    event_type,
                    asset,
                    quantity,
                    wallet,
                    account,
                    tx_id,
                    source_ref
                from canonical_events
                where event_type in ('deposit', 'withdrawal', 'transfer_in', 'transfer_out')
                   or lower(coalesce(source, '')) in ('helium', 'solana', 'manual-csv')
                   or coalesce(wallet, '') != ''
                order by event_time
                limit 1200
                """,
            ),
            "recent_high_value_tax_lines": query_dicts(
                con,
                """
                select
                    year(disposed_at) as tax_year,
                    asset,
                    quantity,
                    disposal_proceeds_eur,
                    acquisition_cost_eur,
                    gain_loss_eur,
                    disposed_at,
                    source_event_id
                from tax_lines
                order by abs(coalesce(gain_loss_eur, 0)) desc
                limit 300
                """,
            ),
        }
    write_json(raw_dir / "db_state.json", db_state)
    return {"api": api_state, "db": db_state}


def build_tasks(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    sources = data(evidence["api"].get("sources_overview"))
    portfolio = data(evidence["api"].get("portfolio_snapshot"))
    reconciliation = data(evidence["api"].get("portfolio_reconciliation"))
    tax_years = data(evidence["api"].get("tax_years_summary"))
    report_center = data(evidence["api"].get("report_center"))
    transfer_candidates = data(evidence["api"].get("transfer_candidates"))
    hnt = data(evidence["api"].get("hnt_fifo_provenance"))
    review_gates = data(evidence["api"].get("review_gates"))
    traces = data(evidence["api"].get("review_evidence_traces"))
    db = evidence["db"]
    context = {
        "review_gate": review_gates,
        "portfolio_value_eur": portfolio.get("total_value_eur"),
        "positions_count": len(portfolio.get("positions") or []),
        "sources_health": sources.get("health"),
        "report_center_status": report_center.get("status") or report_center.get("readiness"),
        "tax_years_count": len(tax_years.get("years") or []),
    }
    return [
        task(
            "01_sources_health_and_live_staleness",
            "Quellen-Health und Live-Aktualitaet",
            context,
            {
                "sources_overview": sources,
                "portfolio_reconciliation": reconciliation,
            },
            "Erklaere alle Quellen-Warnungen. Trenne veraltete Live-Snapshots von echten steuerlichen/FIFO-Risiken.",
        ),
        task(
            "02_fifo_trace_risk_clusters",
            "FIFO-Risikocluster aus Ledger und Lots",
            context,
            {
                "negative_balance_clusters": db["balance_negative_clusters"],
                "tax_lot_remaining_by_asset": db["tax_lot_remaining_by_asset"],
                "high_value_tax_lines": db["recent_high_value_tax_lines"],
            },
            "Priorisiere FIFO-Risiken nach Asset, Quelle und Belegbedarf. Markiere Dust getrennt von echten Luecken.",
        ),
        task(
            "03_transfer_bridge_and_staking_candidates",
            "Transfer-, Bridge- und Staking-Kandidaten",
            context,
            {
                "transfer_candidates": transfer_candidates,
                "external_like_events": db["external_like_events"],
                "hnt_fifo_provenance": hnt,
            },
            "Finde Kandidaten fuer eigene Transfers, Blockchain-Wechsel, Staking-Plattformen und echte externe Zufluesse.",
        ),
        task(
            "04_tax_year_and_report_readiness",
            "Steuerjahr- und Report-Readiness",
            context,
            {
                "tax_years_summary": tax_years,
                "report_center": report_center,
                "review_evidence_traces": traces,
            },
            "Bewerte, ob Steuerjahre und Report-Center fachlich plausibel wirken und welche Belege noch zu pruefen sind.",
        ),
        task(
            "05_event_coverage_source_parser_gaps",
            "Event-Abdeckung und Parser-Luecken",
            context,
            {
                "canonical_event_counts": db["canonical_event_counts"],
                "sources_overview": sources,
            },
            "Suche auffaellige Event-/Source-Kombinationen, die Parser-, Import- oder Klassifikationsarbeit nahelegen.",
        ),
    ]


def task(task_id: str, title: str, context: dict[str, Any], payload: dict[str, Any], question: str) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "title": title,
        "question": question,
        "context": context,
        "payload": payload,
        "hard_rules": [
            "Nur Findings erzeugen.",
            "Keine steuerliche Endentscheidung.",
            "Keine Datenbank-, Import-, FIFO- oder Review-Aktion empfehlen ohne Codex-Verifikation.",
            "Jede Hypothese muss mit konkretem Belegpfad oder fehlendem Beleg markiert werden.",
        ],
    }


def build_prompt(task_data: dict[str, Any]) -> str:
    return textwrap.dedent(
        f"""
        Du bist die lokale XT-7900 KI fuer Steuerreport V2. Arbeite streng read-only.

        Harte Regeln:
        - Keine Datenbank schreiben.
        - Keine Imports ausfuehren.
        - Kein FIFO-Rebuild.
        - Keine Review-Entscheidung.
        - Keine erfundenen Belege.
        - Trenne Beleg, Hypothese, Risiko und naechste Codex-Aktion.

        Aufgabe: {task_data['title']}
        Frage: {task_data['question']}

        Daten:
        {json.dumps(task_data, ensure_ascii=False, indent=2, default=str)[:90000]}

        Schreibe einen deutschen Markdown-Report mit exakt diesen Abschnitten:
        # {task_data['title']}
        ## Kurzurteil
        ## Gepruefter Umfang
        ## Belegte Fakten
        ## Hypothesen
        ## Risiken fuer FIFO/Steuerreport
        ## Priorisierte naechste Codex-Schritte
        ## Nicht entscheiden ohne weitere Belege
        """
    ).strip()


def build_summary_prompt(statuses: list[dict[str, str]]) -> str:
    report_texts = []
    for item in statuses:
        path = PACKAGE / item["report"]
        if path.exists():
            report_texts.append(f"## {item['task_id']}\n\n{path.read_text(encoding='utf-8')[:20000]}")
    return textwrap.dedent(
        f"""
        Fasse diese read-only XT-7900 Overnight-Reports fuer Codex zusammen.
        Keine neuen Fakten erfinden. Priorisiere konkrete naechste Umsetzungsschritte.

        {chr(10).join(report_texts)[:100000]}

        Schreibe Markdown mit:
        # XT 7900 Source/FIFO Overnight Summary
        ## Top-Findings
        ## Sofort von Codex pruefen
        ## Nur beobachten
        ## Offene Belege
        """
    ).strip()


def call_llm(prompt: str, *, max_tokens: int) -> tuple[str, str]:
    body = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": "Du bist ein vorsichtiger deutscher Steuerreport-Audit-Assistent im Readonly-Modus."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        f"{LLM_BASE.rstrip('/')}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with managed_urlopen(request, timeout=1800) as response:
            payload = json.loads(response.read().decode("utf-8"))
        content = payload["choices"][0]["message"].get("content") or ""
        return content, "ok" if content.strip() else "empty"
    except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
        return f"# LLM-Aufruf fehlgeschlagen\n\n`{exc}`\n", "failed"


def dry_run_report(task_data: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"# {task_data['title']}",
            "",
            "Dry-Run erfolgreich. Keine lokale KI aufgerufen.",
            "",
            f"- Task-ID: `{task_data['task_id']}`",
            f"- Payload-Groesse: {len(json.dumps(task_data, default=str))} Zeichen",
        ]
    )


def get_api(path: str) -> dict[str, Any]:
    url = f"{API_BASE.rstrip('/')}/api/v1/{path.lstrip('/')}"
    try:
        with managed_urlopen(url, timeout=240) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"status": "error", "errors": [{"message": str(exc), "endpoint": url}]}


def query_dicts(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    columns = None
    rows = con.execute(sql).fetchall()
    columns = [item[0] for item in con.description or []]
    return [normalize(dict(zip(columns, row))) for row in rows]


def data(response: Any) -> dict[str, Any]:
    if isinstance(response, dict) and isinstance(response.get("data"), dict):
        return response["data"]
    return response if isinstance(response, dict) else {}


def normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def write_json(path: Path, data_obj: Any) -> None:
    path.write_text(json.dumps(normalize(data_obj), ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def write_status(started_at: str, finished_at: str | None, status: str, tasks: list[dict[str, str]]) -> None:
    write_json(
        PACKAGE / "run_status.json",
        {
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "tasks": tasks,
        },
    )


def log_progress(message: str) -> None:
    log_path = PACKAGE / "progress.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now(UTC).isoformat()} {message}\n")


if __name__ == "__main__":
    raise SystemExit(main())
