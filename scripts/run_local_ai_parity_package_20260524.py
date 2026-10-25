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
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "var" / "local_ai_prework" / "packages" / "parity_release_batch_20260524"
LLM_BASE = os.environ.get("LOCAL_LLM_BASE") or private_value("local_llm_base") or "http://127.0.0.1:11435/v1"
LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL") or private_value("local_llm_model") or "local-model"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run readonly local-AI parity report package.")
    parser.add_argument("--package", default=str(PACKAGE), help="Package directory.")
    parser.add_argument("--max-tasks", type=int, default=0, help="Limit number of tasks, 0 means all.")
    parser.add_argument("--dry-run", action="store_true", help="Validate package and print planned tasks only.")
    args = parser.parse_args()

    package = Path(args.package).resolve()
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    reports = package / "reports"
    reports.mkdir(parents=True, exist_ok=True)

    tasks = manifest["tasks"]
    if args.max_tasks > 0:
        tasks = tasks[: args.max_tasks]

    status: list[dict[str, str]] = []
    for task in tasks:
        task_id = task["task_id"]
        if args.dry_run:
            print(f"planned {task_id} -> {task['expected_report']}")
            status.append({"task_id": task_id, "status": "planned", "path": task["expected_report"]})
            continue

        detail = json.loads((package / task["detail_file"]).read_text(encoding="utf-8"))
        prompt = build_prompt(task, compact_detail(detail))
        print(f"start {task_id}")
        report, call_status = call_llm(prompt)
        target = package / task["expected_report"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(report.strip() + "\n", encoding="utf-8")
        status.append({"task_id": task_id, "status": call_status, "path": task["expected_report"]})
        print(f"done {task_id} status={call_status}")
        time.sleep(2)

    if not args.dry_run:
        summary_prompt = build_summary_prompt(package, manifest)
        summary, call_status = call_llm(summary_prompt, max_tokens=2200, timeout=1800)
        (reports / "summary.md").write_text(summary.strip() + "\n", encoding="utf-8")
        status.append({"task_id": "summary", "status": call_status, "path": "reports/summary.md"})

    (package / "run_status.json").write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0


def compact_detail(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data", payload)
    samples = []
    for sample in data.get("tax_event_samples", [])[:12]:
        payload_data = sample.get("payload") or {}
        samples.append(
            {
                "event_time": sample.get("event_time"),
                "source": sample.get("source"),
                "account": sample.get("account"),
                "source_ref": sample.get("source_ref"),
                "filename": sample.get("filename"),
                "quantity": sample.get("quantity"),
                "quote_asset": sample.get("quote_asset"),
                "quote_quantity": sample.get("quote_quantity"),
                "disposal_proceeds_eur": sample.get("disposal_proceeds_eur"),
                "acquisition_cost_eur": sample.get("acquisition_cost_eur"),
                "gain_loss_eur": sample.get("gain_loss_eur"),
                "payload_hint": {
                    "event_type": payload_data.get("event_type"),
                    "defi_label": payload_data.get("defi_label"),
                    "side": payload_data.get("side"),
                    "tx_id": payload_data.get("tx_id"),
                    "raw_row": str(payload_data.get("raw_row") or "")[:1200],
                },
            }
        )
    return {
        "scope": data.get("scope"),
        "year": data.get("year"),
        "asset": data.get("asset"),
        "status": data.get("status"),
        "decision_status": data.get("decision_status"),
        "metrics": data.get("metrics", []),
        "tax_source_summaries": data.get("tax_source_summaries", []),
        "tax_event_samples": samples,
    }


def build_prompt(task: dict[str, str], detail: dict[str, Any]) -> str:
    return textwrap.dedent(
        f"""
        Du bist lokale KI fuer Steuerreport V2. Arbeite ausschliesslich im Readonly-Modus.

        Harte Regeln:
        - Keine Datenbank schreiben.
        - Keine API-Entscheidung setzen.
        - Kein Import mit --execute.
        - Keine Preiswerte erfinden.
        - Keine steuerliche Endentscheidung.
        - V1/WISO/CoinTracking ist Plausibilitaetsreferenz, nicht Wahrheit.
        - Trenne Beleg, Interpretation und Unsicherheit sauber.

        Aufgabe:
        - Task-ID: {task["task_id"]}
        - Scope: {task["scope"]}
        - Detaildump: {task["detail_file"]}
        - Zielreport: {task["expected_report"]}

        Detaildaten:
        {json.dumps(detail, ensure_ascii=False, indent=2)}

        Schreibe einen deutschen Markdown-Report mit exakt diesen Abschnitten:
        # {task["task_id"]}
        ## Kurzurteil
        ## Zahlen
        ## V2-Quellen
        ## Wichtigste Belege
        ## Ursachenhypothese
        ## Unsicherheiten
        ## Empfehlung
        ## Konkrete Codex-Pruefschritte
        ## Stop-Kriterien

        Die Empfehlung muss genau einen Status enthalten:
        v2_corrected, accepted_difference, v1_known_wrong, missing_data oder needs_manual_evidence.
        Wenn keine eindeutige Belegkette vorhanden ist, waehle needs_manual_evidence oder missing_data.
        """
    ).strip()


def build_summary_prompt(package: Path, manifest: dict[str, Any]) -> str:
    reports = []
    for task in manifest["tasks"]:
        path = package / task["expected_report"]
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        reports.append({"task_id": task["task_id"], "report": text[:6000]})
    return textwrap.dedent(
        f"""
        Du bist lokale KI fuer Steuerreport V2. Fasse die folgenden Readonly-Reports zusammen.
        Keine Live-Entscheidung, keine Steuerentscheidung.

        Reports:
        {json.dumps(reports, ensure_ascii=False, indent=2)}

        Schreibe reports/summary.md mit:
        # Summary
        ## Wahrscheinlich entscheidbar
        ## Braucht manuelle Belege
        ## Fehlende Datenquellen
        ## Naechste Codex-Pruefung
        ## Hoechste Release-Wirkung
        """
    ).strip()


def call_llm(prompt: str, *, max_tokens: int = 2600, timeout: int = 1800) -> tuple[str, str]:
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
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = data["choices"][0]["message"].get("content") or ""
        return content or "Leere Modellantwort.", "ok"
    except (KeyError, urllib.error.URLError, TimeoutError, OSError) as exc:
        return f"# Lokale KI Aufgabe fehlgeschlagen\n\n`{type(exc).__name__}: {exc}`\n", "failed"


if __name__ == "__main__":
    raise SystemExit(main())
