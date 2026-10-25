#!/usr/bin/env python3
from __future__ import annotations

from steuerreport_v2.paths import PROJECT_ROOT as SOFTWARE_ROOT

from steuerreport_v2.private_settings import private_value

import argparse
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer


PROJECT_ROOT = SOFTWARE_ROOT
DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var/solana_native_evidence_backfills"
DEFAULT_WALLET = private_value('primary_solana_wallet')
DEFAULT_AUDIT = (
    PROJECT_ROOT
    / "var/solana_native_balance_coverage"
    / f"latest_{DEFAULT_WALLET}_native_balance_coverage.json"
)
BALANCE_EFFECTIVE_STATUSES = {"onchain_success", "onchain_failed"}
SOURCE = "solana_rpc"


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except Exception:
        return Decimal("0")


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"invalid JSON object: {path}")
    return payload


def _canonical_sol_state(
    store: DuckDbStore,
    signatures: list[str],
    wallet: str,
) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    if not signatures:
        return {}, {}
    with store.connect() as con:
        effects = con.execute(
            """
            select event.tx_id, sum(ledger.delta_quantity)
            from balance_ledger ledger
            join canonical_events event on event.event_id = ledger.event_id
            where ledger.account = ?
              and ledger.asset = 'SOL'
              and event.tx_id in (select unnest(?))
            group by event.tx_id
            """,
            [wallet, signatures],
        ).fetchall()
        fees = con.execute(
            """
            select tx_id, sum(abs(fee_quantity))
            from canonical_events
            where (account = ? or wallet = ?)
              and fee_asset = 'SOL'
              and tx_id in (select unnest(?))
            group by tx_id
            """,
            [wallet, wallet, signatures],
        ).fetchall()
    return (
        {str(signature): _decimal(quantity) for signature, quantity in effects},
        {str(signature): _decimal(quantity) for signature, quantity in fees},
    )


def build_backfill_rows(
    payload: dict[str, Any],
    *,
    canonical_effects: dict[str, Decimal],
    canonical_fees: dict[str, Decimal],
    audit_path: Path,
) -> tuple[list[dict[str, object]], list[str], dict[str, Decimal]]:
    findings: list[str] = []
    if payload.get("history_complete") is not True:
        findings.append("wallet_history_not_complete")
    reconciliation = payload.get("reconciliation") if isinstance(payload.get("reconciliation"), dict) else {}
    if reconciliation.get("chain_net_matches_live") is not True:
        findings.append("chain_net_does_not_match_live")
    wallet = str(payload.get("wallet") or "")
    if not wallet:
        findings.append("wallet_missing")
    rows: list[dict[str, object]] = []
    expected: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    seen: set[str] = set()
    for transaction in payload.get("chain_transactions", []):
        if not isinstance(transaction, dict):
            continue
        signature = str(transaction.get("signature") or "")
        if not signature or signature in seen:
            continue
        seen.add(signature)
        if transaction.get("chain_status") not in BALANCE_EFFECTIVE_STATUSES:
            findings.append(f"non_balance_effective_transaction:{signature}")
            continue
        chain_effect = _decimal(transaction.get("wallet_native_sol_delta"))
        canonical_effect = canonical_effects.get(signature, Decimal("0"))
        effect_gap = chain_effect - canonical_effect
        actual_fee = abs(_decimal(transaction.get("wallet_fee_sol")))
        canonical_fee = abs(canonical_fees.get(signature, Decimal("0")))
        fee_gap = actual_fee - canonical_fee
        if fee_gap < 0:
            findings.append(f"canonical_fee_exceeds_chain_fee:{signature}:{fee_gap}")
            continue
        non_fee_gap = effect_gap + fee_gap
        if not effect_gap and not fee_gap:
            continue
        row: dict[str, object] = {
            "timestamp_utc": transaction.get("block_time_utc"),
            "event_type": "sol_transfer",
            "asset": "SOL",
            "quantity": str(abs(non_fee_gap)),
            "side": "in" if non_fee_gap > 0 else "out",
            "tx_id": signature,
            "wallet_address": wallet,
            "evidence_class": "native_pre_post_balance_gap",
            "chain_status": transaction.get("chain_status"),
            "chain_native_sol_delta": str(chain_effect),
            "canonical_native_sol_effect_before": str(canonical_effect),
            "native_non_fee_gap": str(non_fee_gap),
            "audit_artifact": str(audit_path.relative_to(PROJECT_ROOT)),
        }
        if fee_gap:
            row["fee_asset"] = "SOL"
            row["fee_quantity"] = str(fee_gap)
        rows.append(row)
        expected[signature] += effect_gap
    rows.sort(key=lambda row: (str(row.get("timestamp_utc") or ""), str(row.get("tx_id") or "")))
    return rows, sorted(set(findings)), dict(expected)


def _event_effect(events: list[object]) -> Decimal:
    effect = Decimal("0")
    for event in events:
        if event.asset == "SOL":
            effect += event.quantity
        if event.quote_asset == "SOL" and event.quote_quantity is not None:
            quote = abs(event.quote_quantity)
            effect += -quote if event.quantity > 0 else quote
        if event.fee_asset == "SOL" and event.fee_quantity is not None:
            effect -= abs(event.fee_quantity)
    return effect


def verify_rows(
    rows: list[dict[str, object]],
    expected_by_txid: dict[str, Decimal],
    directory: Path,
) -> dict[str, object]:
    if not rows:
        return {
            "status": "ready",
            "raw_rows_count": 0,
            "normalized_events_count": 0,
            "expected_effect": "0",
            "normalized_effect": "0",
            "effect_delta": "0",
        }
    store = DuckDbStore(directory / "solana-native-preview.duckdb")
    content = json.dumps(rows, sort_keys=True, ensure_ascii=False)
    batch = CsvRawImporter(store).import_rows(
        source=SOURCE,
        filename="solana-native-evidence-preview.json",
        file_hash="sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest(),
        rows=rows,
    )
    events = RawNormalizer(store).normalize_batch(batch.batch_id)
    expected = sum(expected_by_txid.values(), Decimal("0"))
    actual = _event_effect(events)
    return {
        "status": "ready" if len(events) == len(rows) and actual == expected else "blocked",
        "raw_rows_count": len(rows),
        "normalized_events_count": len(events),
        "expected_effect": str(expected),
        "normalized_effect": str(actual),
        "effect_delta": str(actual - expected),
    }


def _state(store: DuckDbStore, wallet: str) -> dict[str, object]:
    with store.connect() as con:
        balance = _decimal(
            con.execute(
                """
                select coalesce(sum(delta_quantity), 0)
                from balance_ledger where account = ? and asset = 'SOL'
                """,
                [wallet],
            ).fetchone()[0]
        )
    gate = ReviewService(store).gate()
    return {
        "sol_balance": str(balance),
        "allow_export": gate.allow_export,
        "issues_open": gate.issues_open,
    }


def run(args: argparse.Namespace) -> dict[str, object]:
    audit_path = Path(args.audit).resolve()
    payload = _load_json(audit_path)
    wallet = str(payload.get("wallet") or "")
    store = DuckDbStore(Path(args.db))
    signatures = [
        str(row.get("signature") or "")
        for row in payload.get("chain_transactions", [])
        if isinstance(row, dict) and row.get("signature")
    ]
    effects, fees = _canonical_sol_state(store, signatures, wallet)
    rows, findings, expected = build_backfill_rows(
        payload,
        canonical_effects=effects,
        canonical_fees=fees,
        audit_path=audit_path,
    )
    with tempfile.TemporaryDirectory(prefix="steuerreport-solana-native-") as temp_dir:
        verification = verify_rows(rows, expected, Path(temp_dir))
    ready = not findings and verification["status"] == "ready"
    generated_at = datetime.now(timezone.utc)
    content = json.dumps(rows, sort_keys=True, ensure_ascii=False)
    file_hash = "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
    report: dict[str, object] = {
        "generated_at": generated_at.isoformat(),
        "mode": "apply" if args.apply else "preview",
        "status": "ready" if ready and not args.apply else "blocked" if not ready else "applying",
        "source_audit": str(audit_path.relative_to(PROJECT_ROOT)),
        "source_audit_sha256": hashlib.sha256(audit_path.read_bytes()).hexdigest(),
        "candidate_transactions_count": len(rows),
        "file_hash": file_hash,
        "findings": findings,
        "verification": verification,
        "target_changed": False,
        "methodology": (
            "Evidence-bound native SOL correction. Per finalized TxID, the exact wallet pre/post Lamport "
            "effect is reduced by the current V2 SOL ledger effect. Missing network fees are separated "
            "from non-fee native movement; an overcharged canonical fee blocks apply."
        ),
    }
    if args.apply:
        if not ready:
            raise RuntimeError("native_backfill_not_ready: " + ", ".join(findings))
        report["pre_apply_state"] = _state(store, wallet)
        batch = CsvRawImporter(store).import_rows(
            source=SOURCE,
            filename=f"solana-native-evidence-{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json",
            file_hash=file_hash,
            rows=rows,
        )
        try:
            pipeline = PipelineService(store).rebuild_after_import(batch.batch_id)
            if not pipeline.pipeline.allow_export or pipeline.pipeline.review_issues_open:
                gate = ReviewService(store).gate()
                issue_refs = ",".join(
                    f"{issue.code}:{issue.scope}" for issue in gate.issues
                )
                raise RuntimeError(
                    "post_apply_review_gate_closed: "
                    f"allow_export={pipeline.pipeline.allow_export}, "
                    f"issues_open={pipeline.pipeline.review_issues_open}, "
                    f"issues={issue_refs or '-'}"
                )
        except Exception:
            PipelineService(store).delete_import_and_rebuild(batch.batch_id)
            raise
        report.update(
            {
                "status": "applied",
                "batch_id": batch.batch_id,
                "pipeline": pipeline.model_dump(mode="json"),
                "post_apply_state": _state(store, wallet),
                "target_changed": True,
                "rollback": {
                    "method": "existing_import_delete_api",
                    "endpoint": f"DELETE /api/v1/import/batches/{batch.batch_id}",
                },
            }
        )
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_content = json.dumps(report, indent=2, ensure_ascii=False)
    versioned = output_dir / f"solana_native_evidence_backfill_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    latest = output_dir / "latest_solana_native_evidence_backfill.json"
    versioned.write_text(report_content, encoding="utf-8")
    latest.write_text(report_content, encoding="utf-8")
    report["artifact_path"] = str(versioned.relative_to(PROJECT_ROOT))
    report["latest_artifact_path"] = str(latest.relative_to(PROJECT_ROOT))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Evidence-bound native SOL balance backfill")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--audit", default=str(DEFAULT_AUDIT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(run(args), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
