#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import os
import subprocess
import textwrap
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "var" / "local_ai_prework"
RAW = OUT / "raw"
API_BASE = os.environ.get("STEUERREPORT_V2_API", "http://127.0.0.1:8010")
LLM_BASE = os.environ.get("LOCAL_LLM_BASE", "http://192.168.2.203:11435/v1")
LLM_MODEL = os.environ.get("LOCAL_LLM_MODEL", "qwen3.6-35b-a3b-iq4xs")


def main() -> int:
    global OUT, RAW
    started_at = now()
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = OUT / f"run_{run_id}"
    OUT = run_dir
    RAW = OUT / "raw"
    OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    commands: list[str] = []

    readiness = run_json_command(
        ["python3", "scripts/import_blockpit_supplement_v2.py", "--readiness-report"],
        "blockpit_readiness.json",
        commands,
        timeout=900,
    )
    class_analysis = run_json_command(
        ["python3", "scripts/import_blockpit_supplement_v2.py", "--analyze-classes"],
        "blockpit_classes.json",
        commands,
        timeout=600,
    )
    policy = fetch_api("/api/v1/import/policy/audit", "import_policy_audit.json", commands)
    parity = fetch_api("/api/v1/parity/diagnostics", "parity_diagnostics.json", commands)
    export_readiness = fetch_api("/api/v1/export/readiness", "export_readiness.json", commands)
    review_gates = fetch_api("/api/v1/review/gates", "review_gates.json", commands)
    events_payload = fetch_api("/api/v1/events/canonical", "canonical_events.json", commands)

    events = events_payload.get("data", []) if isinstance(events_payload, dict) else []
    write_solana_priority(readiness.get("readiness", {}), class_analysis)
    parity_findings = write_parity_findings(parity.get("data", parity))
    write_parser_specs(policy.get("data", policy))
    transfer_count = write_transfer_candidates(events)
    llm_status = write_llm_review(readiness, parity, policy, export_readiness, review_gates)
    task_results = write_llm_task_pack(
        readiness=readiness,
        class_analysis=class_analysis,
        policy=policy,
        parity=parity,
        export_readiness=export_readiness,
        review_gates=review_gates,
    )
    write_summary(
        started_at=started_at,
        commands=commands,
        llm_status=llm_status,
        task_results=task_results,
        transfer_count=transfer_count,
        parity_count=len(parity_findings),
        export_readiness=export_readiness.get("data", export_readiness),
        review_gates=review_gates.get("data", review_gates),
    )
    return 0


def run_json_command(command: list[str], filename: str, commands: list[str], *, timeout: int) -> dict[str, Any]:
    commands.append(" ".join(command))
    proc = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, timeout=timeout, check=False)
    (RAW / f"{filename}.stdout").write_text(proc.stdout, encoding="utf-8")
    (RAW / f"{filename}.stderr").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} failed: {(proc.stderr or proc.stdout)[-2000:]}")
    data = json.loads(proc.stdout)
    write_json(RAW / filename, data)
    return data


def fetch_api(path: str, filename: str, commands: list[str]) -> dict[str, Any]:
    url = f"{API_BASE}{path}"
    commands.append(f"GET {url}")
    with urllib.request.urlopen(url, timeout=120) as response:
        data = json.loads(response.read().decode("utf-8"))
    write_json(RAW / filename, data)
    return data


def write_solana_priority(readiness: dict[str, Any], class_analysis: dict[str, Any]) -> None:
    class_counts = class_analysis.get("class_counts", {})
    rows: list[dict[str, Any]] = []
    for class_name, info in sorted(readiness.items()):
        missing_prices = list(info.get("missing_latest_price_assets") or [])
        required = dict(info.get("required_opening_balance") or {})
        count = int(class_counts.get(class_name, 0) or 0)
        risk_score = len(missing_prices) * 3 + len(required) * 2
        if count >= 100:
            risk_score += 1
        risk = "niedrig" if risk_score <= 2 else "mittel" if risk_score <= 7 else "hoch"
        rows.append(
            {
                "class": class_name,
                "rows": count,
                "missing_prices": ", ".join(missing_prices) or "-",
                "required_opening_balance": ", ".join(f"{asset} {amount}" for asset, amount in required.items()) or "-",
                "risk": risk,
                "risk_score": risk_score,
            }
        )
    top = sorted(rows, key=lambda row: (row["risk_score"], -row["rows"], row["class"]))[:3]
    lines = [
        "# Solana-/Blockpit-Priorisierung",
        "",
        "Diese Datei ist lokale-KI-/Readonly-Vorarbeit. Keine Klasse wurde live importiert.",
        "",
        "| Klasse | Zeilen | Fehlende Preise | Benoetigter Startbestand | Risiko |",
        "|---|---:|---|---|---|",
    ]
    for row in rows:
        lines.append(
            f"| `{row['class']}` | {row['rows']} | {row['missing_prices']} | "
            f"{row['required_opening_balance']} | {row['risk']} |"
        )
    lines.extend(["", "## Top-3-Pruefpakete", ""])
    for idx, row in enumerate(top, start=1):
        lines.append(
            f"{idx}. `{row['class']}`: {row['rows']} Zeilen, Risiko {row['risk']}. "
            f"Blocker: Preise `{row['missing_prices']}`, Startbestand `{row['required_opening_balance']}`."
        )
    lines.extend(
        [
            "",
            "## Codex-Pruefung",
            "",
            "Vor jeder Implementierung muss Codex je Klasse einen Staging-Preflight pruefen. "
            "Eine Live-Freigabe ist aus dieser Vorarbeit nicht ableitbar.",
        ]
    )
    (OUT / "solana_blockpit_priority.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_parity_findings(data: dict[str, Any]) -> list[dict[str, Any]]:
    groups = data.get("groups", [])
    findings = []
    for group in groups:
        if int(group.get("year") or 0) != 2024:
            continue
        delta = dec(group.get("absolute_difference_eur"))
        if delta == 0:
            continue
        findings.append(
            {
                "year": group.get("year"),
                "asset": group.get("asset"),
                "status": group.get("status"),
                "metrics": group.get("metrics", []),
                "v1_total_eur": str(group.get("v1_total_eur")),
                "v2_total_eur": str(group.get("v2_total_eur")),
                "absolute_difference_eur": str(group.get("absolute_difference_eur")),
                "max_absolute_difference": str(group.get("max_absolute_difference")),
                "hypothesis": "Hypothese: Abweichung haengt wahrscheinlich mit noch nicht live-faehigen Solana/Blockpit/Jupiter-Quellen oder Startbestaenden zusammen. Muss per Rohdatenkette belegt werden.",
                "next_codex_step": "Canonical Events und Import-Policy fuer dieses Asset gegen Blockpit/Solana-Klassen und vorhandene Exchange-Transfers pruefen.",
            }
        )
    findings.sort(key=lambda item: dec(item["absolute_difference_eur"]), reverse=True)
    write_json(OUT / "parity_2024_findings.json", findings)
    lines = [
        "# Paritaets-/Plausibilitaetsabweichungen 2024",
        "",
        "Altreports sind Plausibilitaetsreferenz, nicht Wahrheit. Alle Ursachen sind bis zur Rohdatenpruefung Hypothesen.",
        "",
        "| Asset | Status | V1 EUR | V2 EUR | Delta EUR | Metriken | Naechster Codex-Schritt |",
        "|---|---|---:|---:|---:|---|---|",
    ]
    for item in findings[:25]:
        lines.append(
            f"| `{item['asset']}` | {item['status']} | {item['v1_total_eur']} | {item['v2_total_eur']} | "
            f"{item['absolute_difference_eur']} | {', '.join(item['metrics'])} | {item['next_codex_step']} |"
        )
    (OUT / "parity_2024_findings.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return findings


def write_parser_specs(policy: dict[str, Any]) -> None:
    decisions = policy.get("decisions", [])
    parser_needed = [item for item in decisions if item.get("category") == "parser_needed"]
    lines = [
        "# Parser-Bedarf aus Import-Policy",
        "",
        "Diese Liste beschreibt Parser-Kandidaten. Sie ist keine Importfreigabe.",
        "",
    ]
    for item in parser_needed:
        path = item.get("relative_path")
        reason = item.get("reason")
        expected = expected_events_for_parser_path(str(path))
        lines.extend(
            [
                f"## `{path}`",
                "",
                f"- Grund: {reason}",
                f"- Erwartete fachliche Events: {expected}",
                "- Benoetigte Spalten: vor Implementierung per Datei-Header pruefen.",
                "- Doppelimport-Risiko: hoch, wenn dieselben Bewegungen bereits in Blockpit, Binance, Pionex, Bitget oder Helium enthalten sind.",
                "- Testvorschlag: Preview-Test, Normalizer-Test, Staging-Import gegen Review-Gates, Duplikatabgleich gegen Canonical Events.",
                "",
            ]
        )
    (OUT / "parser_needed_specs.md").write_text("\n".join(lines), encoding="utf-8")


def write_transfer_candidates(events: list[dict[str, Any]]) -> int:
    assets = {"HNT", "SOL", "USDT", "USDC"}
    relevant = []
    for event in events:
        asset = str(event.get("asset") or "").upper()
        if asset not in assets:
            continue
        qty = dec(event.get("quantity"))
        if qty == 0:
            continue
        relevant.append(
            {
                "event_id": event.get("event_id"),
                "event_time": event.get("event_time"),
                "asset": asset,
                "quantity": qty,
                "account": event.get("account") or "",
                "source": event.get("source") or "",
                "event_type": event.get("event_type") or "",
                "tx_id": event.get("tx_id") or "",
            }
        )
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in relevant:
        key = (event["asset"], str(abs(event["quantity"].quantize(Decimal("0.000001")))))
        buckets[key].append(event)
    candidates = []
    for (_asset, _amount), bucket in buckets.items():
        positives = [item for item in bucket if item["quantity"] > 0]
        negatives = [item for item in bucket if item["quantity"] < 0]
        for neg in negatives[:20]:
            for pos in positives[:20]:
                if neg["account"] == pos["account"]:
                    continue
                candidates.append(
                    {
                        "asset": neg["asset"],
                        "amount_abs": str(abs(neg["quantity"])),
                        "out_time": neg["event_time"],
                        "out_account": neg["account"],
                        "out_source": neg["source"],
                        "out_event_id": neg["event_id"],
                        "in_time": pos["event_time"],
                        "in_account": pos["account"],
                        "in_source": pos["source"],
                        "in_event_id": pos["event_id"],
                        "evidence_level": "amount_exact_rounded_6dp",
                    }
                )
    candidates = candidates[:500]
    with (OUT / "transfer_chain_candidates.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "asset",
                "amount_abs",
                "out_time",
                "out_account",
                "out_source",
                "out_event_id",
                "in_time",
                "in_account",
                "in_source",
                "in_event_id",
                "evidence_level",
            ],
        )
        writer.writeheader()
        writer.writerows(candidates)
    lines = [
        "# Transfer-Chain-Kandidaten",
        "",
        "Kandidaten basieren nur auf Asset und gerundeter gleicher Menge. Sie sind keine automatische Transferentscheidung.",
        "",
        f"- Kandidaten: `{len(candidates)}`",
        "- Priorisierte Assets: `HNT`, `SOL`, `USDT`, `USDC`",
        "",
        "Details stehen in `transfer_chain_candidates.csv`.",
    ]
    (OUT / "transfer_chain_candidates.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(candidates)


def write_llm_review(
    readiness: dict[str, Any],
    parity: dict[str, Any],
    policy: dict[str, Any],
    export_readiness: dict[str, Any],
    review_gates: dict[str, Any],
) -> str:
    prompt = textwrap.dedent(
        f"""
        Du bist lokale KI fuer Steuerreport V2. Bewerte nur die folgenden Readonly-Snapshots.
        Keine Steuerentscheidung, keine Schaetzung. Markiere Unsicherheit.

        Blockpit readiness keys: {json.dumps(readiness.get('readiness', {}), ensure_ascii=False)[:12000]}
        Parity groups sample: {json.dumps(parity.get('data', parity).get('groups', [])[:20], ensure_ascii=False)[:12000]}
        Import policy counts: {json.dumps({k: policy.get('data', policy).get(k) for k in ['files_total','classified','unclassified','curated_primary','staging_required','parser_needed','reference_only']}, ensure_ascii=False)}
        Export readiness: {json.dumps(export_readiness.get('data', export_readiness), ensure_ascii=False)}
        Review gates: {json.dumps(review_gates.get('data', review_gates), ensure_ascii=False)}

        Schreibe eine knappe deutsche Review:
        1. wichtigste Risiken,
        2. beste naechste Codex-Pruefschritte,
        3. was nicht entschieden werden darf.
        """
    ).strip()
    payload = {
        "model": LLM_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1800,
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
        with urllib.request.urlopen(request, timeout=900) as response:
            data = json.loads(response.read().decode("utf-8"))
        write_json(RAW / "local_llm_review.json", data)
        content = data["choices"][0]["message"].get("content") or ""
        (OUT / "local_ai_model_review.md").write_text(content.strip() + "\n", encoding="utf-8")
        return "ok"
    except (KeyError, urllib.error.URLError, TimeoutError, OSError) as exc:
        (OUT / "local_ai_model_review.md").write_text(
            f"# Lokale KI Review\n\nLokaler Modellaufruf fehlgeschlagen: `{type(exc).__name__}: {exc}`.\n",
            encoding="utf-8",
        )
        return f"failed: {type(exc).__name__}: {exc}"


def write_llm_task_pack(
    *,
    readiness: dict[str, Any],
    class_analysis: dict[str, Any],
    policy: dict[str, Any],
    parity: dict[str, Any],
    export_readiness: dict[str, Any],
    review_gates: dict[str, Any],
) -> list[dict[str, str]]:
    tasks_dir = OUT / "task_reviews"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    context = build_llm_context(
        readiness=readiness,
        class_analysis=class_analysis,
        policy=policy,
        parity=parity,
        export_readiness=export_readiness,
        review_gates=review_gates,
    )
    tasks = build_overnight_tasks()
    max_tasks = int(os.environ.get("LOCAL_AI_PREWORK_MAX_TASKS", "900"))
    tasks = tasks[:max_tasks]
    results: list[dict[str, str]] = []
    for task_id, instruction in tasks:
        log_progress(f"local-ai task start {task_id}")
        prompt = (
            "Du bist lokale KI fuer Steuerreport V2. Du darfst nichts entscheiden und nichts live aendern.\n"
            "Nutze nur den folgenden kompakten Readonly-Kontext. Keine Schaetzungen ohne Beleg.\n\n"
            f"{context}\n\n"
            f"Aufgabe: {instruction}\n\n"
            "Antworte auf Deutsch mit diesen Abschnitten: Befund, Belege aus Kontext, "
            "Unsicherheiten, konkrete Codex-Pruefschritte, moegliche Tests, "
            "Nicht-Implementieren-ohne-Pruefung. Arbeite gruendlich, aber erfinde keine Fakten."
        )
        status, content = call_llm(prompt, max_tokens=2400, timeout=1800)
        target = tasks_dir / f"{task_id}.md"
        target.write_text(content.strip() + "\n", encoding="utf-8")
        results.append({"task_id": task_id, "status": status, "path": str(target.relative_to(OUT))})
        log_progress(f"local-ai task done {task_id} status={status}")
        time.sleep(2)
    write_json(OUT / "task_reviews_status.json", results)
    return results


def build_overnight_tasks() -> list[tuple[str, str]]:
    tasks: list[tuple[str, str]] = []

    solana_classes = [
        "fee_only",
        "withdrawal_sol",
        "deposit_with_sol_fee",
        "deposit_plain",
        "trade_buy_from_stable",
        "trade_crypto_crypto",
        "trade_sell_to_stable",
        "withdrawal_stable",
        "withdrawal_crypto",
    ]
    solana_aspects = [
        ("readiness", "Bewerte Readiness, Blocker, Startbestaende und fehlende Preise."),
        ("opening_balance", "Leite ab, welche Opening-Balance-Entscheidungen denkbar sind und welche Belege fehlen."),
        ("duplicate_risk", "Analysiere Doppelimport- und Ueberlappungsrisiken mit anderen Klassen/Quellen."),
        ("tax_effect", "Bewerte moegliche Steuerwirkung und warum dies noch keine Steuerentscheidung ist."),
        ("staging_plan", "Entwirf einen konkreten Staging-Preflight-Plan mit Akzeptanzkriterien."),
        ("review_gates", "Schlage Review-Gates oder Warnungen fuer diese Klasse vor."),
        ("source_evidence", "Liste welche Rohdatenbelege, TXIDs, Wallets oder Kontoquellen Codex pruefen sollte."),
        ("failure_modes", "Beschreibe harte Fehlerbilder, die bei Live-Import verhindert werden muessen."),
    ]
    for row_class in solana_classes:
        for aspect_key, aspect in solana_aspects:
            tasks.append(
                (
                    f"solana_{row_class}_{aspect_key}",
                    f"Solana/Blockpit Klasse `{row_class}`: {aspect}",
                )
            )

    parity_assets = ["SOL", "USDC", "JUP", "USDT", "HNT", "BTC"]
    parity_aspects = [
        ("root_cause", "Erstelle Hypothesen zur Ursache der V1/V2-Abweichung und trenne Beleg von Vermutung."),
        ("source_mapping", "Welche Quellen/Parser/Import-Policy-Entscheidungen koennen diese Abweichung beeinflussen?"),
        ("transfer_chain", "Welche Transferketten muessen fuer dieses Asset priorisiert geprueft werden?"),
        ("price_effect", "Welche Preis-/Bewertungsfragen koennen das Delta erklaeren?"),
        ("fifo_effect", "Welche FIFO-/Lot-/Quote-Effekte koennen das Delta erklaeren?"),
        ("codex_plan", "Formuliere einen Codex-Pruefplan mit konkreten SQL/API/Staging-Schritten."),
        ("risk_statement", "Formuliere einen kurzen Risiko-/Audittext fuer die Dokumentation."),
    ]
    for asset in parity_assets:
        for aspect_key, aspect in parity_aspects:
            tasks.append((f"parity_2024_{asset.lower()}_{aspect_key}", f"Paritaet 2024 Asset `{asset}`: {aspect}"))

    parser_files = [
        ("binance_c2c", "Binance C2C Order History"),
        ("wallet_month", "Wallet-Monatsaggregat"),
        ("jup_perps", "JUP/Perps/DCA Datei"),
        ("solscan", "Solscan Legacy Export"),
    ]
    parser_aspects = [
        ("schema", "Erwartetes Schema, Pflichtspalten, optionale Spalten und Header-Fallen."),
        ("normalization", "Mapping zu Canonical Events mit Eventtypen, Mengen, Quote, Fee und Konto."),
        ("dedupe", "Deduplizierung gegen bestehende Quellen und Import-Policy."),
        ("tests", "Unit-, Preview-, Staging- und Regressionstests."),
        ("tax_risks", "Steuerliche Risiken ohne finale Steuerentscheidung."),
        ("failure_modes", "Fehlerbilder, die zu falschem Portfolio oder Steuerlauf fuehren koennen."),
        ("ui_workflow", "Noetige Browser-/Admin-Controls fuer sicheren Import."),
        ("acceptance", "Akzeptanzkriterien fuer Codex vor Live-Freigabe."),
    ]
    for parser_key, parser_name in parser_files:
        for aspect_key, aspect in parser_aspects:
            tasks.append((f"parser_{parser_key}_{aspect_key}", f"Parser-Kandidat `{parser_name}`: {aspect}"))

    transfer_assets = ["HNT", "SOL", "USDT", "USDC", "JUP", "IOT", "MOBILE", "BTC"]
    transfer_aspects = [
        ("time_windows", "Definiere sinnvolle Zeitfenster und Richtungskriterien."),
        ("txid_matching", "Welche TXID-/Onchain-/Exchange-Belege sind erforderlich?"),
        ("fee_tolerance", "Welche Mengenabweichungen durch Fees sind plausibel und wie pruefen?"),
        ("opening_overlap", "Wie verhindert man Dopplung mit Opening-Balance-Adjustments?"),
        ("account_mapping", "Welche Konto-/Walletnamen muessen vereinheitlicht werden?"),
        ("false_positives", "Welche False Positives entstehen bei reinem Mengenmatching?"),
    ]
    for asset in transfer_assets:
        for aspect_key, aspect in transfer_aspects:
            tasks.append((f"transfer_{asset.lower()}_{aspect_key}", f"Transferketten Asset `{asset}`: {aspect}"))

    review_topics = [
        ("import_policy_ui", "Admin-/Frontend-Ansicht fuer Import-Policy-Audit"),
        ("staging_dashboard", "Admin-/Frontend-Ansicht fuer Staging-Matrix und Preflight-Ergebnisse"),
        ("review_decisions", "UI und API-Verwendung fuer Review-Entscheidungen ohne Gate-Lockerung"),
        ("price_coverage", "Review-Gate fuer historische und aktuelle Preisabdeckung"),
        ("parity_thresholds", "Warnlogik fuer signifikante Altreport-Plausibilitaetsabweichungen"),
        ("pdf_evidence", "PDF-/Export-Belegstruktur fuer Quellen, Entscheidungen und offene Risiken"),
        ("elster_prep", "ELSTER-Prep-Datenumfang und Grenzen ohne ERiC-Uebertragung"),
        ("audit_trail", "Audit-Trail fuer Import, Staging, Review-Decisions und Preisquellen"),
        ("local_ai_quality", "Qualitaetsgate fuer lokale KI-Artefakte vor Codex-Uebernahme"),
        ("regression_suite", "Welche Regressionstests harte Fehler wie Portfolio-Explosionen verhindern"),
        ("database_integrity", "DuckDB-Lock-, Snapshot- und Staging-Sicherheitsregeln"),
        ("frontend_status", "Frontend-Statusanzeigen fuer Backend, Import-Policy, Review und Paritaet"),
        ("source_coverage", "Wie neue Dateien als curated/staging/parser/reference klassifiziert werden sollen"),
        ("manual_evidence", "Workflow fuer manuelle Bank-/Kreditkarten-/Wallet-Belege"),
        ("derivatives_depth", "Naechste fachliche Schritte fuer Derivate/Perps/Margin"),
        ("stablecoin_fifo", "Sicherer Plan fuer Stablecoin-Quote-FIFO ohne Startbestandschaos"),
        ("opening_balance_policy", "Regelwerk fuer Opening-Balance-Adjustments mit Belegen"),
        ("iot_price_policy", "Preis-/Asset-Strategie fuer IOT ohne unbewiesene Schaetzung"),
        ("hnt_legacy_policy", "Helium/HNT Legacy- und Mining-Reward-Nachweisstrategie"),
        ("release_readiness", "Definition einer echten V2-Abgabereife gegen aktuellen MVP-Stand"),
    ]
    for topic_key, instruction in review_topics:
        tasks.append((f"crosscut_{topic_key}", instruction))

    # Repeat task families with multiple review passes. The local model was very
    # fast in earlier runs, so the overnight batch needs enough independent
    # artifacts to be useful even if each task finishes quickly.
    first_pass = list(tasks)
    for task_id, instruction in first_pass:
        tasks.append(
            (
                f"critique_{task_id}",
                f"Kritisiere die Aufgabe `{task_id}` aus Sicht eines Reviewers: {instruction} "
                "Suche Gegenargumente, fehlende Belege, False Positives und harte Abbruchkriterien.",
            )
        )
    for task_id, instruction in first_pass:
        tasks.append(
            (
                f"evidence_{task_id}",
                f"Erstelle fuer `{task_id}` eine Belegmatrix: {instruction} "
                "Trenne vorhandene Belege, fehlende Belege, moegliche Datenquellen und konkrete Codex-Kommandos/API-Checks.",
            )
        )
    for task_id, instruction in first_pass:
        tasks.append(
            (
                f"acceptance_{task_id}",
                f"Definiere fuer `{task_id}` harte Akzeptanzkriterien und Regressionstests: {instruction} "
                "Nenne klare Stop-Kriterien, damit Codex nichts unsicher live uebernimmt.",
            )
        )

    return tasks


def build_llm_context(
    *,
    readiness: dict[str, Any],
    class_analysis: dict[str, Any],
    policy: dict[str, Any],
    parity: dict[str, Any],
    export_readiness: dict[str, Any],
    review_gates: dict[str, Any],
) -> str:
    readiness_data = readiness.get("readiness", {})
    policy_data = policy.get("data", policy)
    parser_needed = [
        {
            "relative_path": item.get("relative_path"),
            "reason": item.get("reason"),
        }
        for item in policy_data.get("decisions", [])
        if item.get("category") == "parser_needed"
    ]
    groups = parity.get("data", parity).get("groups", [])
    groups_2024 = sorted(
        [group for group in groups if int(group.get("year") or 0) == 2024],
        key=lambda group: dec(group.get("absolute_difference_eur")),
        reverse=True,
    )[:12]
    compact = {
        "rules": [
            "Altreports sind Plausibilitaetsreferenz, nicht Wahrheit.",
            "Keine Live-DB-Aenderung, kein --execute, kein --force.",
            "Fuer Codex nur belegte Pruefschritte vorbereiten.",
        ],
        "class_counts": class_analysis.get("class_counts", {}),
        "readiness": readiness_data,
        "parser_needed": parser_needed,
        "parity_2024_top": groups_2024,
        "policy_counts": {
            key: policy_data.get(key)
            for key in ["files_total", "classified", "unclassified", "curated_primary", "staging_required", "parser_needed", "reference_only"]
        },
        "export_readiness": export_readiness.get("data", export_readiness),
        "review_gates": review_gates.get("data", review_gates),
    }
    return json.dumps(compact, ensure_ascii=False, default=str)[:30000]


def call_llm(prompt: str, *, max_tokens: int, timeout: int) -> tuple[str, str]:
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
        return "ok", content or "Leere Modellantwort."
    except (KeyError, urllib.error.URLError, TimeoutError, OSError) as exc:
        return "failed", f"# Lokale KI Aufgabe fehlgeschlagen\n\n`{type(exc).__name__}: {exc}`\n"


def write_summary(
    *,
    started_at: str,
    commands: list[str],
    llm_status: str,
    task_results: list[dict[str, str]],
    transfer_count: int,
    parity_count: int,
    export_readiness: dict[str, Any],
    review_gates: dict[str, Any],
) -> None:
    files = [
        "SUMMARY.md",
        "solana_blockpit_priority.md",
        "parity_2024_findings.md",
        "parity_2024_findings.json",
        "parser_needed_specs.md",
        "transfer_chain_candidates.md",
        "transfer_chain_candidates.csv",
        "local_ai_model_review.md",
        "task_reviews_status.json",
    ]
    files.extend(f"task_reviews/{item['task_id']}.md" for item in task_results)
    lines = [
        "# Lokale-KI-Vorarbeit: Zusammenfassung",
        "",
        f"- Start UTC: `{started_at}`",
        f"- Ende UTC: `{now()}`",
        f"- Lokaler Modellaufruf: `{llm_status}`",
        f"- Einzelauftraege: `{len(task_results)}`",
        f"- Einzelauftraege erfolgreich: `{sum(1 for item in task_results if item['status'] == 'ok')}`",
        f"- Export-Readiness: `allow_export={export_readiness.get('allow_export')}`",
        f"- Review-Gates: `issues_open={review_gates.get('issues_open')}`",
        f"- Paritaetsfindings 2024: `{parity_count}`",
        f"- Transfer-Kandidaten: `{transfer_count}`",
        "",
        "## Ausgefuehrte Befehle",
        "",
    ]
    lines.extend(f"- `{command}`" for command in commands)
    lines.extend(["", "## Erzeugte Dateien", ""])
    lines.extend(f"- `var/local_ai_prework/{file}`" for file in files)
    lines.extend(
        [
            "",
            "## Sichere Aussagen",
            "",
            "- Es wurden nur Readonly-Endpunkte und nicht-live-faehige Analysebefehle genutzt.",
            "- Es wurde kein `--execute` und kein `--force` ausgefuehrt.",
            "- Ergebnisse sind Vorarbeit und keine Steuerfreigabe.",
            "",
            "## Unsichere Aussagen",
            "",
            "- Transfer-Kandidaten sind nur Kandidaten nach Menge/Asset und muessen zeitlich sowie per TXID/Quelle validiert werden.",
            "- Paritaetsursachen sind Hypothesen, bis Codex sie an Rohdaten und Importketten geprueft hat.",
            "",
            "## Erste Codex-Pruefpunkte",
            "",
            "1. `solana_blockpit_priority.md` gegen Staging-Preflight pruefen.",
            "2. `parity_2024_findings.json` nach groesstem Delta abarbeiten.",
            "3. `parser_needed_specs.md` in konkrete Parser-Tests ueberfuehren.",
            "4. `transfer_chain_candidates.csv` nur nach TXID-/Zeit-/Kontobeleg verwenden.",
        ]
    )
    (OUT / "SUMMARY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_json(
        OUT / "run_status.json",
        {
            "started_at_utc": started_at,
            "finished_at_utc": now(),
            "llm_status": llm_status,
            "files": files,
            "task_results": task_results,
            "transfer_count": transfer_count,
            "parity_count": parity_count,
        },
    )


def log_progress(message: str) -> None:
    line = f"{now()} {message}"
    print(line, flush=True)
    with (OUT / "runner_progress.log").open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def expected_events_for_parser_path(path: str) -> str:
    lower = path.lower()
    if "c2c" in lower:
        return "Fiat-/Crypto-C2C-Kaeufe und -Verkaeufe mit Gegenpartei-/Zahlungsstatus."
    if "jup" in lower:
        return "Jupiter-/Perps-/DCA-Events, eventuell Derivate- oder Swap-Cashflows."
    if "wallet." in lower:
        return "Wallet-Monatsaggregat mit Rewards, Transfers oder Swap-Summen."
    if "solscan" in lower:
        return "Solana-Wallet-Transfers mit Mint-Mapping, Richtung und Fees."
    return "Noch offen; Header und Beispielzeilen pruefen."


def dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def now() -> str:
    return datetime.now(UTC).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
