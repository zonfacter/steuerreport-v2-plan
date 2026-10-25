#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import textwrap
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "var" / "local_ai_prework" / "packages" / "fairspot_fifo_rebuild_20260526"
DB_PATH = ROOT / "data" / "steuerreport_v2.duckdb"
API_BASE = os.environ.get("STEUERREPORT_V2_API", "http://127.0.0.1:8010")
LLM_BASE = os.environ.get("LOCAL_LLM_BASE", "http://192.168.2.203:11435/v1")
LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "qwen3.6-35b-a3b-iq4xs")

MAIN_WALLET = "133iWieuwSsyRYopuykZFnxs5qJJW1AiRgXqH43S9rJxU6WUW8v"
FAIRSPOT_WALLET = "133mLjQyaZs6RpT3Mo9aBW4MHMJar3VsmjQ9FUpSsFzuocRZRuN"
FAIRSPOT_URL = (
    "https://www.fairspot.host/hnt-export-mining-tax"
    f"?account={FAIRSPOT_WALLET}"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local-AI Fairspot/FIFO rebuild prework.")
    parser.add_argument("--dry-run", action="store_true", help="Collect evidence but skip LLM call.")
    args = parser.parse_args()

    started_at = datetime.now(UTC).isoformat()
    raw_dir = PACKAGE / "raw"
    reports_dir = PACKAGE / "reports"
    raw_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    evidence = collect_evidence(raw_dir)
    manifest = {
        "package": "fairspot_fifo_rebuild_20260526",
        "started_at": started_at,
        "rules": [
            "Readonly local-AI task: no database writes.",
            "Do not run imports, batch deletion, FIFO rebuild or review decisions.",
            "Separate confirmed evidence from hypotheses.",
            "Return exact Codex verification and implementation steps.",
        ],
        "wallets": {
            "main_legacy": MAIN_WALLET,
            "fairspot_counterparty": FAIRSPOT_WALLET,
            "fairspot_url": FAIRSPOT_URL,
        },
        "raw_files": sorted(str(path.relative_to(PACKAGE)) for path in raw_dir.glob("*.json")),
    }
    write_json(PACKAGE / "manifest.json", manifest)

    if args.dry_run:
        report = dry_run_report(evidence)
        status = "dry_run"
    else:
        report, status = call_llm(build_prompt(evidence))

    report_path = reports_dir / "fairspot_fifo_rebuild_plan.md"
    report_path.write_text(report.strip() + "\n", encoding="utf-8")
    write_json(
        PACKAGE / "run_status.json",
        {
            "status": status,
            "started_at": started_at,
            "finished_at": datetime.now(UTC).isoformat(),
            "report": str(report_path.relative_to(PACKAGE)),
        },
    )
    return 0


def collect_evidence(raw_dir: Path) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "api": {},
        "db": {},
        "code_fix_context": {
            "normalizer_fix": "Helium payment_v2 payer/payee rows are now classified as transfer in code.",
            "portfolio_fix": "Fairspot account is treated as transfer counterparty and excluded from portfolio/source display.",
            "open_issue": "Existing DuckDB rows were normalized before that fix and still need a safe rebuild path.",
        },
    }

    for path in (
        "/api/v1/health",
        "/api/v1/review/gates",
        "/api/v1/tax/summary",
        "/api/v1/tax/unmatched-disposals",
        "/api/v1/sources/overview",
        "/api/v1/portfolio/snapshot",
        "/api/v1/portfolio/reconciliation",
    ):
        payload = fetch_api(path)
        key = path.removeprefix("/api/v1/").replace("/", "_")
        evidence["api"][key] = compact_api(path, payload)
        write_json(raw_dir / f"api_{key}.json", payload)

    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        db_queries = {
            "event_span": """
                select count(*) as events, min(event_time) as first_event, max(event_time) as last_event
                from canonical_events
            """,
            "event_counts_by_source": """
                select source, count(*) as events, min(event_time) as first_event, max(event_time) as last_event
                from canonical_events
                group by source
                order by events desc
            """,
            "event_counts_by_type": """
                select event_type, count(*) as events, min(event_time) as first_event, max(event_time) as last_event
                from canonical_events
                group by event_type
                order by events desc
            """,
            "fifo_integrity": """
                select
                    (select count(*) from tax_lots) as tax_lots,
                    (select count(*) from tax_lines) as tax_lines,
                    (select count(*) from tax_unmatched_disposals) as unmatched_disposals,
                    (select count(*) from tax_lots where cost_basis_eur_total = 0) as zero_cost_lots
            """,
            "fairspot_canonical_events": """
                select
                    e.event_id,
                    e.raw_object_id,
                    e.source,
                    e.source_ref,
                    e.event_time,
                    e.event_type,
                    e.asset,
                    e.quantity,
                    e.account,
                    e.tx_id
                from canonical_events e
                where e.account = ?
                   or e.tx_id like '%Kk7ZTefj1fQOZ%'
                   or e.tx_id like '%tLOGE2C0v%'
                order by e.event_time, e.event_id
            """,
            "fairspot_raw_objects": """
                select
                    r.raw_object_id,
                    r.batch_id,
                    b.source,
                    b.filename,
                    r.row_number,
                    r.payload_json
                from raw_objects r
                join raw_import_batches b on b.batch_id = r.batch_id
                where r.payload_json like ?
                   or r.payload_json like '%Kk7ZTefj1fQOZ%'
                   or r.payload_json like '%tLOGE2C0v%'
                order by b.filename, r.row_number
            """,
            "helium_batches": """
                select batch_id, source, filename, created_at
                from raw_import_batches
                where lower(source) = 'helium'
                   or lower(filename) like '%helium%'
                   or lower(filename) like '%fairspot%'
                order by created_at desc, filename
            """,
        }
        params = {
            "fairspot_canonical_events": [FAIRSPOT_WALLET],
            "fairspot_raw_objects": [f"%{FAIRSPOT_WALLET}%"],
        }
        for name, sql in db_queries.items():
            rows = query_dicts(con, sql, params.get(name, []))
            evidence["db"][name] = rows
            write_json(raw_dir / f"db_{name}.json", rows)

    return evidence


def compact_api(path: str, payload: dict[str, Any]) -> Any:
    data = payload.get("data", payload)
    if path == "/api/v1/portfolio/snapshot":
        return {
            "total_value_eur": data.get("total_value_eur"),
            "missing_price_assets": data.get("missing_price_assets", []),
            "fairspot_presence": {
                "in_positions": any(item.get("account") == FAIRSPOT_WALLET for item in data.get("positions", [])),
                "in_account_summary": any(item.get("account") == FAIRSPOT_WALLET for item in data.get("account_summary", [])),
                "in_excluded_account_summary": any(
                    item.get("account") == FAIRSPOT_WALLET for item in data.get("excluded_account_summary", [])
                ),
            },
            "top_accounts": data.get("account_summary", [])[:10],
            "top_assets": data.get("asset_summary", [])[:10],
        }
    if path == "/api/v1/sources/overview":
        return {
            "total_value_eur": data.get("total_value_eur"),
            "sources": [
                {
                    "label": item.get("label"),
                    "source_type": item.get("source_type"),
                    "value_eur": item.get("value_eur"),
                    "value_basis": item.get("value_basis"),
                    "ledger_value_eur": item.get("ledger_value_eur"),
                    "live_value_eur": item.get("live_value_eur"),
                    "delta_value_eur": item.get("delta_value_eur"),
                    "open_reconciliation_issues": item.get("open_reconciliation_issues"),
                    "last_live_at": item.get("last_live_at"),
                }
                for item in data.get("sources", [])
            ],
        }
    if path == "/api/v1/portfolio/reconciliation":
        rows = data.get("rows", [])
        return {
            "total_ledger_value_eur": data.get("total_ledger_value_eur"),
            "expected_zero_ledger_value_eur": data.get("expected_zero_ledger_value_eur"),
            "live_unverified_ledger_value_eur": data.get("live_unverified_ledger_value_eur"),
            "missing_wallets": data.get("missing_wallets", []),
            "blockers": [row for row in rows if row.get("severity") == "blocker"][:20],
        }
    if isinstance(data, list):
        return {"count": len(data), "sample": data[:10]}
    return data


def query_dicts(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    result = con.execute(sql, params)
    columns = [item[0] for item in result.description]
    rows = []
    for row in result.fetchall():
        rows.append({column: json_safe(value) for column, value in zip(columns, row, strict=True)})
    return rows


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def fetch_api(path: str) -> dict[str, Any]:
    with urllib.request.urlopen(f"{API_BASE}{path}", timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def build_prompt(evidence: dict[str, Any]) -> str:
    return textwrap.dedent(
        f"""
        Du bist lokale KI fuer Steuerreport V2. Arbeite ausschliesslich im Readonly-Modus.

        Harte Regeln:
        - Keine Datenbank schreiben.
        - Keine Imports ausfuehren.
        - Kein FIFO-Rebuild ausfuehren.
        - Keine Review-Entscheidungen setzen.
        - Keine steuerliche Endentscheidung treffen.
        - Keine Werte erfinden.
        - Unterscheide Beleg, Hypothese und erforderliche Codex-Aktion.

        Fachliches Ziel:
        Pruefe, wie der Fairspot/HNT-Transfer sauber in eine rueckwaerts
        nachvollziehbare FIFO-Kette bis 2021 gebracht werden soll.

        Bekannte Wallets:
        - Main Legacy: {MAIN_WALLET}
        - Fairspot/Staking-Gegenpartei: {FAIRSPOT_WALLET}
        - Fairspot-Beleg: {FAIRSPOT_URL}

        Erwartete fachliche Behandlung:
        - 23.06.2021 payment_v2 Main Legacy -> Fairspot ist Transfer, kein Mining.
        - 08.07.2021 payment_v2 Fairspot -> Main Legacy ist Transfer, kein Mining.
        - Fairspot darf nicht als aktuelle Portfolio-Wallet oder Dashboard-Quelle erscheinen.
        - Fairspot muss als Transfer-Gegenpartei/FIFO-Beleg nachvollziehbar bleiben.

        Evidenz:
        {json.dumps(evidence, ensure_ascii=False, indent=2)[:50000]}

        Schreibe einen deutschen Markdown-Report mit exakt diesen Abschnitten:
        # Fairspot FIFO Rebuild Plan
        ## Kurzurteil
        ## Gesicherte Datenlage
        ## Fairspot-Events
        ## Betroffene Batches
        ## Warum aktueller FIFO-Lauf noch nicht fachlich 100 Prozent ist
        ## Sicherer Rebuild-Vorschlag fuer Codex
        ## Akzeptanzkriterien
        ## Stop-Kriterien
        ## Reihenfolge der naechsten Codex-Schritte

        Der Rebuild-Vorschlag muss konkrete, aber noch nicht auszufuehrende
        Schritte enthalten. Wenn ein Schritt reale Daten schreibt, markiere ihn
        ausdruecklich als Codex-manuell-zu-pruefen.
        """
    ).strip()


def call_llm(prompt: str) -> tuple[str, str]:
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 3600,
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
        content = data["choices"][0]["message"].get("content") or ""
        return content or "Leere Modellantwort.", "ok"
    except (KeyError, urllib.error.URLError, TimeoutError, OSError) as exc:
        return f"# Lokale KI Aufgabe fehlgeschlagen\n\n`{type(exc).__name__}: {exc}`\n", "failed"


def dry_run_report(evidence: dict[str, Any]) -> str:
    fairspot_events = evidence.get("db", {}).get("fairspot_canonical_events", [])
    return textwrap.dedent(
        f"""
        # Fairspot FIFO Rebuild Plan

        ## Kurzurteil

        Dry-Run erfolgreich. Evidenz wurde gesammelt, LLM-Aufruf wurde uebersprungen.

        ## Gesicherte Datenlage

        - Fairspot Canonical Events: {len(fairspot_events)}
        - API/DB Rohdaten liegen unter `raw/`.

        ## Naechster Schritt

        Dienst ohne `--dry-run` starten.
        """
    ).strip()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
