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
from collections import Counter, defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "var" / "local_ai_prework" / "packages" / "binance_live_ledger_20260529"
DB_PATH = ROOT / "data" / "steuerreport_v2.duckdb"
API_BASE = os.environ.get("STEUERREPORT_V2_API", "http://127.0.0.1:8010")
LLM_BASE = os.environ.get("LOCAL_LLM_BASE") or private_value("local_llm_base") or "http://127.0.0.1:11435/v1"
LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL") or private_value("local_llm_model") or "local-model"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local-AI Binance live-vs-ledger analysis.")
    parser.add_argument("--dry-run", action="store_true", help="Prepare package without LLM calls.")
    parser.add_argument("--max-tasks", type=int, default=0, help="Limit LLM tasks, 0 means all.")
    args = parser.parse_args()

    started_at = datetime.now(UTC).isoformat()
    raw_dir = PACKAGE / "raw"
    reports_dir = PACKAGE / "reports"
    tasks_dir = PACKAGE / "tasks"
    raw_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)
    tasks_dir.mkdir(parents=True, exist_ok=True)

    evidence = build_evidence(raw_dir)
    tasks = build_tasks(evidence)
    if args.max_tasks > 0:
        tasks = tasks[: args.max_tasks]

    manifest = {
        "package": "binance_live_ledger_20260529",
        "started_at": started_at,
        "mode": "readonly_local_ai_binance_live_ledger",
        "db": str(DB_PATH.relative_to(ROOT)),
        "api_base": API_BASE,
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
            "No database writes.",
            "No imports.",
            "No FIFO rebuild.",
            "No review decisions.",
            "No artificial zero bookings.",
            "Codex must verify every recommendation before implementation.",
        ],
        "raw_files": sorted(str(path.relative_to(PACKAGE)) for path in raw_dir.glob("*")),
    }
    write_json(PACKAGE / "manifest.json", manifest)

    statuses: list[dict[str, str]] = []
    for task in tasks:
        task_path = tasks_dir / f"{task['task_id']}.json"
        report_path = reports_dir / f"{task['task_id']}.md"
        write_json(task_path, task)
        if args.dry_run:
            report = dry_run_report(task)
            status = "dry_run"
        else:
            report, status = call_llm(build_prompt(task))
        report_path.write_text(report.strip() + "\n", encoding="utf-8")
        statuses.append({"task_id": task["task_id"], "status": status, "report": str(report_path.relative_to(PACKAGE))})
        time.sleep(2)

    if args.dry_run:
        summary = "# Binance Live-vs-Ledger Summary\n\nDry-Run erfolgreich. Keine lokale KI aufgerufen.\n"
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


def build_evidence(raw_dir: Path) -> dict[str, Any]:
    api_state = {
        "health": get_api("health"),
        "review_gates": get_api("review/gates"),
        "portfolio_snapshot": get_api("portfolio/snapshot"),
        "portfolio_reconciliation": get_api("portfolio/reconciliation"),
        "cockpit_summary": get_api("cockpit/summary"),
    }
    write_json(raw_dir / "api_state.json", api_state)

    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        binance_ledger_positions = query_dicts(
            con,
            """
            with ranked as (
                select
                    account, asset, balance_quantity, event_time, event_id,
                    row_number() over (
                        partition by account, asset
                        order by event_time desc, event_id desc, ledger_id desc
                    ) as rn
                from balance_ledger
                where lower(account) in ('spot', 'funding', 'binance')
                   or lower(account) like '%binance%'
            )
            select account, asset, balance_quantity, event_time, event_id
            from ranked
            where rn = 1 and balance_quantity != 0
            order by abs(balance_quantity) desc, account, asset
            """,
        )
        binance_live_snapshots = query_dicts(
            con,
            """
            select
                connector_id, asset, quantity, source, fetched_at,
                account_type, product_id, position_id, event_type
            from portfolio_live_balance_snapshots
            where connector_id = 'binance'
              and fetched_at = (
                select max(fetched_at)
                from portfolio_live_balance_snapshots
                where connector_id = 'binance'
              )
            order by asset, account_type, product_id, position_id
            """,
        )
        binance_events_recent = query_dicts(
            con,
            """
            select
                e.event_time, e.event_type, e.asset, e.quantity,
                e.quote_asset, e.quote_quantity, e.fee_asset, e.fee_quantity,
                e.account, e.source, e.source_ref, e.tx_id, e.raw_object_id,
                b.filename, r.row_number, left(r.payload_json, 1000) as payload_preview
            from canonical_events e
            left join raw_objects r on r.raw_object_id = e.raw_object_id
            left join raw_import_batches b on b.batch_id = r.batch_id
            where lower(coalesce(e.account, '')) in ('spot', 'funding', 'binance')
               or lower(coalesce(e.account, '')) like '%binance%'
               or e.source = 'binance'
            order by e.event_time desc, e.event_id desc
            limit 350
            """,
        )
        binance_events_by_type = query_dicts(
            con,
            """
            select
                coalesce(account, '') as account,
                event_type,
                asset,
                count(*) as events,
                sum(quantity) as net_quantity
            from canonical_events
            where lower(coalesce(account, '')) in ('spot', 'funding', 'binance')
               or lower(coalesce(account, '')) like '%binance%'
               or source = 'binance'
            group by account, event_type, asset
            order by events desc, account, event_type, asset
            limit 300
            """,
        )
        raw_batches = query_dicts(
            con,
            """
            select
                b.batch_id, b.source, b.filename, b.status, b.created_at,
                count(r.raw_object_id) as raw_object_count
            from raw_import_batches b
            left join raw_objects r on r.batch_id = b.batch_id
            where b.source = 'binance' or lower(b.filename) like '%binance%'
            group by b.batch_id, b.source, b.filename, b.status, b.created_at
            order by b.created_at desc
            limit 80
            """,
        )

    prices = latest_prices_from_snapshot(api_state["portfolio_snapshot"].get("data") or {})
    ledger_by_asset = aggregate_positions(binance_ledger_positions, prices)
    live_by_asset = aggregate_live(binance_live_snapshots, prices)
    deltas = build_deltas(ledger_by_asset, live_by_asset)
    product_buckets = cluster_live_products(binance_live_snapshots, prices)

    raw_payload = {
        "binance_ledger_positions": binance_ledger_positions,
        "binance_live_snapshots": binance_live_snapshots,
        "binance_events_recent": binance_events_recent,
        "binance_events_by_type": binance_events_by_type,
        "raw_batches": raw_batches,
        "ledger_by_asset": ledger_by_asset,
        "live_by_asset": live_by_asset,
        "deltas": deltas,
        "product_buckets": product_buckets,
    }
    for name, payload in raw_payload.items():
        write_json(raw_dir / f"{name}.json", payload)

    return {
        "api_state": compact_api_state(api_state),
        **raw_payload,
        "summary": {
            "ledger_assets": len(ledger_by_asset),
            "live_assets": len(live_by_asset),
            "delta_assets": len(deltas),
            "largest_delta_value_eur": max((abs(to_decimal(item.get("delta_value_eur"))) for item in deltas), default=Decimal("0")),
            "event_type_counts": dict(Counter(item["event_type"] for item in binance_events_recent).most_common()),
        },
    }


def build_tasks(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    base = compact_evidence(evidence)
    return [
        {
            "task_id": "01_binance_delta_overview",
            "title": "Binance Live-vs-Ledger Differenzuebersicht",
            "question": (
                "Bewerte die groessten Binance-Deltas je Asset. Trenne echte Live-Abweichung, "
                "Produkt-/Earn-Bucket, Preis-/FX-Effekt und moegliche Importluecke."
            ),
            "evidence": base,
            "focus": {
                "deltas": evidence["deltas"][:80],
                "ledger_by_asset": evidence["ledger_by_asset"],
                "live_by_asset": evidence["live_by_asset"],
            },
        },
        {
            "task_id": "02_binance_product_bucket_mapping",
            "title": "Binance Produkt-Bucket Mapping",
            "question": (
                "Ordne die Live-Snapshots nach Spot/Funding/Earn/Product. Welche Buckets "
                "duerfen als aktueller Live-Bestand angezeigt werden, welche brauchen "
                "separate steuerliche Nachverfolgung?"
            ),
            "evidence": base,
            "focus": {
                "product_buckets": evidence["product_buckets"],
                "live_snapshots": evidence["binance_live_snapshots"][:220],
            },
        },
        {
            "task_id": "03_binance_repair_plan",
            "title": "Binance Reparaturplan ohne Steuerlogik-Risiko",
            "question": (
                "Formuliere eine umsetzbare Reihenfolge fuer Codex. Keine kuenstlichen "
                "Ausbuchungen. Nenne Tests, API-Checks und Stop-Kriterien."
            ),
            "evidence": base,
            "focus": {
                "recent_events": evidence["binance_events_recent"][:140],
                "events_by_type": evidence["binance_events_by_type"],
                "raw_batches": evidence["raw_batches"],
            },
        },
    ]


def compact_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": evidence["summary"],
        "api_state": evidence["api_state"],
        "top_deltas": evidence["deltas"][:20],
        "product_buckets_top": evidence["product_buckets"][:40],
        "raw_artifact_note": "Vollstaendige JSON-Dateien liegen im Paket unter raw/.",
    }


def compact_api_state(api_state: dict[str, Any]) -> dict[str, Any]:
    snapshot = api_state["portfolio_snapshot"].get("data") or {}
    reconciliation = api_state["portfolio_reconciliation"].get("data") or {}
    cockpit = api_state["cockpit_summary"].get("data") or {}
    return {
        "health": api_state["health"].get("data"),
        "review_gates": api_state["review_gates"].get("data"),
        "snapshot": {
            "total_value_eur": snapshot.get("total_value_eur"),
            "missing_price_assets": snapshot.get("missing_price_assets"),
            "account_summary": snapshot.get("account_summary"),
        },
        "reconciliation": {
            "severity_counts": dict(Counter(row.get("severity") for row in reconciliation.get("rows", []))),
            "binance_rows": [
                row for row in reconciliation.get("rows", [])
                if str(row.get("source_group", "")).lower().startswith("binance")
            ],
        },
        "cockpit": {
            "portfolio_value_eur": cockpit.get("portfolio_value_eur"),
            "live_reconciliation": cockpit.get("live_reconciliation"),
            "top_sources": cockpit.get("top_sources"),
        },
    }


def latest_prices_from_snapshot(snapshot: dict[str, Any]) -> dict[str, Decimal]:
    prices: dict[str, Decimal] = {}
    for position in snapshot.get("positions", []):
        asset = str(position.get("asset") or "").upper()
        if asset and position.get("price_eur") is not None:
            prices[asset] = to_decimal(position["price_eur"])
    return prices


def aggregate_positions(rows: list[dict[str, Any]], prices: dict[str, Decimal]) -> list[dict[str, str]]:
    totals: dict[str, Decimal] = defaultdict(Decimal)
    accounts: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        asset = str(row["asset"]).upper()
        totals[asset] += to_decimal(row["balance_quantity"])
        accounts[asset].add(str(row["account"]))
    return [
        {
            "asset": asset,
            "quantity": str(quantity),
            "value_eur": str(quantity * prices.get(asset, Decimal("0"))),
            "accounts": sorted(accounts[asset]),
        }
        for asset, quantity in sorted(
            totals.items(),
            key=lambda item: abs(item[1] * prices.get(item[0], Decimal("0"))),
            reverse=True,
        )
    ]


def aggregate_live(rows: list[dict[str, Any]], prices: dict[str, Decimal]) -> list[dict[str, str]]:
    totals: dict[str, Decimal] = defaultdict(Decimal)
    product_count: dict[str, int] = defaultdict(int)
    for row in rows:
        asset = str(row["asset"]).upper()
        totals[asset] += to_decimal(row["quantity"])
        product_count[asset] += 1
    return [
        {
            "asset": asset,
            "quantity": str(quantity),
            "value_eur": str(quantity * prices.get(asset, Decimal("0"))),
            "snapshot_rows": product_count[asset],
        }
        for asset, quantity in sorted(
            totals.items(),
            key=lambda item: abs(item[1] * prices.get(item[0], Decimal("0"))),
            reverse=True,
        )
    ]


def build_deltas(
    ledger_by_asset: list[dict[str, str]],
    live_by_asset: list[dict[str, str]],
) -> list[dict[str, str]]:
    ledger = {row["asset"]: row for row in ledger_by_asset}
    live = {row["asset"]: row for row in live_by_asset}
    rows = []
    for asset in sorted(set(ledger) | set(live)):
        ledger_quantity = to_decimal(ledger.get(asset, {}).get("quantity"))
        live_quantity = to_decimal(live.get(asset, {}).get("quantity"))
        ledger_value = to_decimal(ledger.get(asset, {}).get("value_eur"))
        live_value = to_decimal(live.get(asset, {}).get("value_eur"))
        rows.append(
            {
                "asset": asset,
                "ledger_quantity": str(ledger_quantity),
                "live_quantity": str(live_quantity),
                "delta_quantity": str(live_quantity - ledger_quantity),
                "ledger_value_eur": str(ledger_value),
                "live_value_eur": str(live_value),
                "delta_value_eur": str(live_value - ledger_value),
                "ledger_accounts": ledger.get(asset, {}).get("accounts", []),
                "live_snapshot_rows": live.get(asset, {}).get("snapshot_rows", 0),
            }
        )
    return sorted(rows, key=lambda item: abs(to_decimal(item["delta_value_eur"])), reverse=True)


def cluster_live_products(rows: list[dict[str, Any]], prices: dict[str, Decimal]) -> list[dict[str, str]]:
    clusters: dict[tuple[str, str, str, str], Decimal] = defaultdict(Decimal)
    for row in rows:
        key = (
            str(row.get("asset") or "").upper(),
            str(row.get("account_type") or ""),
            str(row.get("product_id") or ""),
            str(row.get("event_type") or ""),
        )
        clusters[key] += to_decimal(row.get("quantity"))
    result = []
    for (asset, account_type, product_id, event_type), quantity in clusters.items():
        result.append(
            {
                "asset": asset,
                "account_type": account_type,
                "product_id": product_id,
                "event_type": event_type,
                "quantity": str(quantity),
                "value_eur": str(quantity * prices.get(asset, Decimal("0"))),
            }
        )
    return sorted(result, key=lambda item: abs(to_decimal(item["value_eur"])), reverse=True)


def build_prompt(task: dict[str, Any]) -> str:
    return textwrap.dedent(
        f"""
        Du bist lokale KI fuer Steuerreport V2. Arbeite ausschliesslich im Readonly-Modus.

        Harte Regeln:
        - Keine Datenbank schreiben.
        - Keine Imports ausfuehren.
        - Kein FIFO-Rebuild.
        - Keine Review-Entscheidung.
        - Keine kuenstlichen Demo-Daten oder Nullbuchungen vorschlagen.
        - Trenne Beleg, Hypothese und Codex-Aktion.
        - Steuerliche FIFO-Entscheidungen muessen spaeter deterministisch validiert werden.

        Aufgabe: {task['title']}
        Task-ID: {task['task_id']}
        Frage: {task['question']}

        Daten:
        {json.dumps(task, ensure_ascii=False, indent=2, default=str)[:70000]}

        Schreibe einen deutschen Markdown-Report mit exakt diesen Abschnitten:
        # {task['title']}
        ## Kurzurteil
        ## Gepruefter Umfang
        ## Wichtigste Belege
        ## Wahrscheinlichste Ursache
        ## FIFO- und Steuer-Risiko
        ## Konkrete Codex-Reparaturschritte
        ## Validierung
        ## Stop-Kriterien

        Wenn nicht genug Belege vorhanden sind, sage das explizit.
        """
    ).strip()


def build_summary_prompt(statuses: list[dict[str, str]]) -> str:
    reports = []
    for status in statuses:
        path = PACKAGE / status["report"]
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        reports.append({"task_id": status["task_id"], "status": status["status"], "report": text[:8000]})
    return textwrap.dedent(
        f"""
        Du bist lokale KI fuer Steuerreport V2. Fasse die Binance-Live-vs-Ledger-Analyse zusammen.
        Keine Daten schreiben, keine finale Steuerentscheidung.

        Reports:
        {json.dumps(reports, ensure_ascii=False, indent=2)}

        Schreibe einen deutschen Markdown-Report mit exakt:
        # Binance Live-vs-Ledger Summary
        ## Gesamtlage
        ## Top-Ursachen
        ## Was Codex zuerst pruefen soll
        ## Was nicht automatisch korrigiert werden darf
        ## Tests und Gates
        """
    ).strip()


def call_llm(prompt: str, *, max_tokens: int = 4200) -> tuple[str, str]:
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
    return f"# {task['title']}\n\nDry-Run vorbereitet. Keine lokale KI aufgerufen.\n"


def get_api(endpoint: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(f"{API_BASE}/api/v1/{endpoint}", timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        return {"status": "failed", "errors": [{"code": type(exc).__name__, "message": str(exc)}], "data": None}


def query_dicts(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict[str, Any]]:
    cursor = con.execute(sql)
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def to_decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
