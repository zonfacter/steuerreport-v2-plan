#!/usr/bin/env python3
from __future__ import annotations

from steuerreport_v2.private_settings import private_value

import argparse
import csv
import json
import os
import textwrap
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SOURCE_PACKAGE = ROOT / "var" / "local_ai_prework" / "packages" / "full_fifo_audit_20260526"
PACKAGE = ROOT / "var" / "local_ai_prework" / "packages" / "overnight_fifo_findings_20260526"
LLM_BASE = os.environ.get("LOCAL_LLM_BASE") or private_value("local_llm_base") or "http://127.0.0.1:11435/v1"
LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL") or private_value("local_llm_model") or "local-model"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run overnight local-AI analysis for full FIFO findings.")
    parser.add_argument("--dry-run", action="store_true", help="Prepare task package without LLM calls.")
    parser.add_argument("--max-tasks", type=int, default=0, help="Limit LLM tasks, 0 means all.")
    args = parser.parse_args()

    started_at = datetime.now(UTC).isoformat()
    reports_dir = PACKAGE / "reports"
    tasks_dir = PACKAGE / "tasks"
    reports_dir.mkdir(parents=True, exist_ok=True)
    tasks_dir.mkdir(parents=True, exist_ok=True)

    audit_summary = read_json(SOURCE_PACKAGE / "raw" / "full_audit_summary.json")
    api_state = read_json(SOURCE_PACKAGE / "raw" / "api_state.json")
    chunk_summaries = read_json(SOURCE_PACKAGE / "raw" / "canonical_event_chunk_summaries.json")
    findings = read_csv(SOURCE_PACKAGE / "raw" / "all_findings.csv")
    tasks = build_tasks(findings, audit_summary, api_state, chunk_summaries)
    if args.max_tasks > 0:
        tasks = tasks[: args.max_tasks]

    manifest = {
        "package": "overnight_fifo_findings_20260526",
        "started_at": started_at,
        "source_package": str(SOURCE_PACKAGE.relative_to(ROOT)),
        "mode": "readonly_local_ai_overnight",
        "tasks": [
            {
                "task_id": task["task_id"],
                "title": task["title"],
                "report": f"reports/{task['task_id']}.md",
                "input": f"tasks/{task['task_id']}.json",
            }
            for task in tasks
        ],
        "rules": [
            "No database writes.",
            "No imports.",
            "No FIFO rebuild.",
            "No review decisions.",
            "Codex must verify every recommendation before implementation.",
        ],
    }
    write_json(PACKAGE / "manifest.json", manifest)

    statuses: list[dict[str, str]] = []
    for task in tasks:
        task_path = tasks_dir / f"{task['task_id']}.json"
        write_json(task_path, task)
        report_path = reports_dir / f"{task['task_id']}.md"
        if args.dry_run:
            report = dry_run_report(task)
            status = "dry_run"
        else:
            report, status = call_llm(build_prompt(task))
        report_path.write_text(report.strip() + "\n", encoding="utf-8")
        statuses.append({"task_id": task["task_id"], "status": status, "report": str(report_path.relative_to(PACKAGE))})
        time.sleep(2)

    if args.dry_run:
        summary = "# Overnight FIFO Findings Summary\n\nDry-Run erfolgreich. Keine lokale KI aufgerufen.\n"
        summary_status = "dry_run"
    else:
        summary, summary_status = call_llm(build_summary_prompt(statuses), max_tokens=3200)
    (reports_dir / "summary.md").write_text(summary.strip() + "\n", encoding="utf-8")
    statuses.append({"task_id": "summary", "status": summary_status, "report": "reports/summary.md"})

    write_json(
        PACKAGE / "run_status.json",
        {
            "status": "ok" if all(item["status"] in {"ok", "dry_run"} for item in statuses) else "partial",
            "started_at": started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "tasks": statuses,
        },
    )
    return 0


def build_tasks(
    findings: list[dict[str, str]],
    audit_summary: dict[str, Any],
    api_state: dict[str, Any],
    chunk_summaries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_code: dict[str, list[dict[str, str]]] = defaultdict(list)
    for finding in findings:
        by_code[finding["code"]].append(finding)

    tasks = [
        task(
            "01_live_ledger_delta",
            "Live-vs-Ledger Blocker",
            by_code["live_ledger_delta"],
            audit_summary,
            extra={"api_state": api_state},
            question=(
                "Bewerte je Quelle, ob es eine fehlende Historie, eine falsche Live-Ankerung "
                "oder eine echte Abgangsluecke ist. Erstelle eine Reparaturreihenfolge."
            ),
        ),
        task(
            "02_helium_fairspot_payment_transfers",
            "Helium/Fairspot payment_v2 Transferklassifikation",
            by_code["fairspot_not_transfer"] + by_code["helium_payment_not_transfer"],
            audit_summary,
            question=(
                "Cluster alle Helium-payment-Findings nach Gegenpartei und Richtung. "
                "Unterscheide eigene Wallet, Staking/Service-Plattform, echte Mining-Rewards "
                "und unbekannte Gegenpartei. Priorisiere FIFO-relevante Transfers."
            ),
        ),
        task(
            "03_negative_balance_ledger",
            "Negative Balance-Ledger-Stellen",
            by_code["negative_balance_ledger"],
            audit_summary,
            extra={"cluster": cluster_findings(by_code["negative_balance_ledger"], ["account", "asset"])},
            question=(
                "Finde die negativen Bestandscluster, die FIFO wirklich gefaehrden. "
                "Markiere Dust/Mini-Rundungsfaelle getrennt von echten fehlenden Startbestaenden."
            ),
        ),
        task(
            "04_unknown_event_type",
            "Unknown Events",
            by_code["unknown_event_type"],
            audit_summary,
            extra={
                "cluster_by_source_asset": cluster_findings(by_code["unknown_event_type"], ["source", "asset"]),
                "chunk_summaries_with_findings": [
                    item for item in chunk_summaries if int(item.get("findings_count") or 0) > 0
                ][:30],
            },
            question=(
                "Priorisiere unknown Events nach Steuer-/FIFO-Risiko. "
                "Welche Parser-Regeln braucht Codex zuerst, welche Zeilen sind Dust/irrelevant?"
            ),
        ),
        task(
            "05_positive_transfer_with_quote",
            "Positive Transfers mit Quote",
            by_code["positive_transfer_with_quote_lot"],
            audit_summary,
            question=(
                "Pruefe, welche positiven Transfers mit Quote echte externe Anschaffungen sind "
                "und welche interne Transfers sein koennten. Formuliere Akzeptanzkriterien."
            ),
        ),
        task(
            "06_duplicate_txid",
            "Hohe TXID-Duplikate",
            by_code["high_duplicate_txid_count"],
            audit_summary,
            question=(
                "Bewerte, ob hohe TXID-Zaehler erwartbare Sammel-/Splitbuchungen sind oder "
                "Duplikatimporte. Nenne konkrete Pruefschritte."
            ),
        ),
    ]
    return tasks


def task(
    task_id: str,
    title: str,
    findings: list[dict[str, str]],
    audit_summary: dict[str, Any],
    *,
    question: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "title": title,
        "question": question,
        "audit_summary": compact_audit_summary(audit_summary),
        "finding_count": len(findings),
        "findings_by_code": dict(Counter(item["code"] for item in findings).most_common()),
        "findings_by_source": dict(Counter(item.get("source", "") for item in findings).most_common(20)),
        "findings_by_asset": dict(Counter(item.get("asset", "") for item in findings).most_common(20)),
        "findings": findings[:350],
        "extra": extra or {},
        "full_artifact_note": (
            "Vollstaendige Listen liegen im Source-Paket unter "
            "var/local_ai_prework/packages/full_fifo_audit_20260526/raw/."
        ),
    }


def compact_audit_summary(audit_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "canonical_events": audit_summary.get("canonical_events"),
        "tax_lines": audit_summary.get("tax_lines"),
        "tax_lots": audit_summary.get("tax_lots"),
        "findings_total": audit_summary.get("findings_total"),
        "findings_by_code": audit_summary.get("findings_by_code"),
        "event_span": audit_summary.get("event_span"),
        "api": {
            "review_gates": audit_summary.get("api", {}).get("review_gates"),
            "tax_summary": audit_summary.get("api", {}).get("tax_summary"),
        },
    }


def cluster_findings(findings: list[dict[str, str]], keys: list[str]) -> list[dict[str, Any]]:
    grouped: Counter[tuple[str, ...]] = Counter(tuple(item.get(key, "") for key in keys) for item in findings)
    return [
        {"count": count, **{key: group[index] for index, key in enumerate(keys)}}
        for group, count in grouped.most_common(80)
    ]


def build_prompt(task: dict[str, Any]) -> str:
    return textwrap.dedent(
        f"""
        Du bist lokale KI fuer Steuerreport V2. Arbeite ausschliesslich im Readonly-Modus.

        Harte Regeln:
        - Keine Datenbank schreiben.
        - Keine Imports ausfuehren.
        - Kein FIFO-Rebuild.
        - Keine Review-Entscheidung.
        - Keine steuerliche Endentscheidung.
        - Trenne Beleg, Hypothese und Codex-Aktion.

        Aufgabe: {task['title']}
        Task-ID: {task['task_id']}
        Frage: {task['question']}

        Daten:
        {json.dumps(task, ensure_ascii=False, indent=2)[:60000]}

        Schreibe einen deutschen Markdown-Report mit exakt diesen Abschnitten:
        # {task['title']}
        ## Kurzurteil
        ## Gepruefter Umfang
        ## Wichtigste Cluster
        ## Echte FIFO-Risiken
        ## Wahrscheinlich harmlose Faelle
        ## Konkrete Codex-Reparaturschritte
        ## Akzeptanzkriterien
        ## Stop-Kriterien

        Wenn nicht genug Belege vorhanden sind, sage das explizit.
        """
    ).strip()


def build_summary_prompt(statuses: list[dict[str, str]]) -> str:
    reports = []
    for status in statuses:
        path = PACKAGE / status["report"]
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        reports.append({"task_id": status["task_id"], "status": status["status"], "report": text[:7000]})
    return textwrap.dedent(
        f"""
        Du bist lokale KI fuer Steuerreport V2. Fasse die Overnight-FIFO-Findings zusammen.
        Keine Daten schreiben, keine finale Steuerentscheidung.

        Reports:
        {json.dumps(reports, ensure_ascii=False, indent=2)}

        Schreibe einen deutschen Markdown-Report mit exakt:
        # Overnight FIFO Findings Summary
        ## Gesamtlage
        ## Top-10 Reparaturen
        ## Sofort-Blocker
        ## Danach pruefen
        ## Was vermutlich harmlos ist
        ## Konkreter Arbeitsplan fuer Codex
        """
    ).strip()


def call_llm(prompt: str, *, max_tokens: int = 3600) -> tuple[str, str]:
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.1,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    try:
        request = urllib.request.Request(
            f"{LLM_BASE}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2400) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"].get("content") or "Leere Modellantwort.", "ok"
    except (KeyError, urllib.error.URLError, TimeoutError, OSError) as exc:
        return f"# Lokale KI Aufgabe fehlgeschlagen\n\n`{type(exc).__name__}: {exc}`\n", "failed"


def dry_run_report(task: dict[str, Any]) -> str:
    return (
        f"# {task['title']}\n\n"
        f"Dry-Run vorbereitet. Findings: {task['finding_count']}.\n"
    )


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
