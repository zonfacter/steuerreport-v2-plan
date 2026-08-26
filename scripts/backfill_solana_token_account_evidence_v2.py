#!/usr/bin/env python3
from __future__ import annotations

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


PROJECT_ROOT = Path("/workspace/steuerreport-v2-plan")
DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
DEFAULT_AUDIT = (
    PROJECT_ROOT
    / "var/solana_token_account_coverage"
    / "latest_G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY_token_account_coverage.json"
)
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var/solana_evidence_backfills"
SOURCE = "solana_rpc"
SUPPORTED_CLASSIFICATIONS = {
    "helium_reward",
    "direct_token_transfer",
    "defi_position_transfer",
    "defi_redeem",
    "program_spend",
    "swap_or_order_route",
}


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


def _candidate_transactions(payload: dict[str, Any]) -> tuple[list[dict[str, object]], list[str]]:
    by_signature: defaultdict[str, list[tuple[str, dict[str, object]]]] = defaultdict(list)
    for target in payload.get("targets", []):
        if not isinstance(target, dict):
            continue
        target_asset = str(target.get("asset") or "")
        for row in target.get("transactions", []):
            if not isinstance(row, dict) or row.get("chain_status") != "onchain_success":
                continue
            if _decimal(row.get("quantity_delta")) == 0 or not row.get("signature"):
                continue
            by_signature[str(row["signature"])].append((target_asset, row))

    findings: list[str] = []
    candidates: list[dict[str, object]] = []
    for signature, target_rows in sorted(by_signature.items()):
        missing = [
            (asset, row)
            for asset, row in target_rows
            if row.get("evidence_status")
            in {"canonical_missing_balance_change", "canonical_quantity_mismatch"}
        ]
        if not missing:
            continue
        if len(missing) != len(target_rows):
            findings.append(f"partial_canonical_signature:{signature}")
            continue
        representative = dict(missing[0][1])
        representative["target_assets"] = sorted({asset for asset, _row in missing})
        representative["target_classifications"] = sorted(
            {str(row.get("movement_classification") or "") for _asset, row in missing}
        )
        candidates.append(representative)
    return candidates, findings


def _base_row(
    transaction: dict[str, object],
    *,
    event_type: str,
    asset: str,
    quantity_delta: Decimal,
    wallet: str,
    audit_path: Path,
) -> dict[str, object]:
    return {
        "timestamp_utc": transaction.get("block_time_utc"),
        "event_type": event_type,
        "asset": asset,
        "quantity": str(abs(quantity_delta)),
        "side": "in" if quantity_delta > 0 else "out",
        "tx_id": transaction.get("signature"),
        "wallet_address": wallet,
        "movement_classification": transaction.get("movement_classification"),
        "classification_reason": transaction.get("classification_reason"),
        "instruction_labels": "|".join(
            str(value) for value in transaction.get("instruction_labels", [])
        ),
        "program_ids": "|".join(str(value) for value in transaction.get("program_ids", [])),
        "counterpart_token_accounts": "|".join(
            str(value) for value in transaction.get("counterpart_token_accounts", [])
        ),
        "evidence_artifact": str(audit_path.relative_to(PROJECT_ROOT)),
    }


def build_backfill_rows(
    payload: dict[str, Any],
    *,
    audit_path: Path,
    existing_effects_by_tx: dict[str, dict[str, Decimal]] | None = None,
    existing_fees_by_tx: dict[str, Decimal] | None = None,
) -> tuple[list[dict[str, object]], list[str]]:
    findings: list[str] = []
    if payload.get("history_complete") is not True:
        findings.append("token_account_history_not_complete")
    wallet = str(payload.get("wallet") or "")
    if not wallet:
        findings.append("wallet_missing")
    candidates, candidate_findings = _candidate_transactions(payload)
    findings.extend(candidate_findings)
    existing_effects_by_tx = existing_effects_by_tx or {}
    existing_fees_by_tx = existing_fees_by_tx or {}
    rows: list[dict[str, object]] = []
    for transaction in candidates:
        classifications = {
            str(value) for value in transaction.get("target_classifications", []) if value
        }
        signature = str(transaction.get("signature") or "")
        unsupported = classifications - SUPPORTED_CLASSIFICATIONS
        if unsupported:
            findings.append(
                f"unsupported_classification:{signature}:{'|'.join(sorted(unsupported))}"
            )
            continue
        token_deltas = [
            {
                **row,
                "quantity_delta": str(
                    _decimal(row.get("quantity_delta"))
                    - existing_effects_by_tx.get(signature, {}).get(
                        str(row.get("asset") or ""),
                        Decimal("0"),
                    )
                ),
            }
            for row in transaction.get("wallet_token_deltas", [])
            if isinstance(row, dict)
            and _decimal(row.get("quantity_delta"))
            - existing_effects_by_tx.get(signature, {}).get(
                str(row.get("asset") or ""),
                Decimal("0"),
            )
            != 0
        ]
        unknown_deltas = [row for row in token_deltas if not row.get("asset")]
        if unknown_deltas:
            labels = {str(value) for value in transaction.get("instruction_labels", [])}
            is_closed_position_receipt = (
                "defi_position_transfer" in classifications
                and bool(labels & {"Burn", "ClosePositionV0", "burn"})
                and all(abs(_decimal(row.get("quantity_delta"))) == 1 for row in unknown_deltas)
            )
            if not is_closed_position_receipt:
                findings.append(f"unknown_asset_in_wallet_delta:{signature}")
                continue
            token_deltas = [row for row in token_deltas if row.get("asset")]
        is_reward = "helium_reward" in classifications
        is_multi_asset_route = bool(classifications & {"defi_redeem", "swap_or_order_route"})
        if is_reward:
            if any(
                str(row.get("asset")) not in {"HNT", "IOT", "MOBILE"}
                or _decimal(row.get("quantity_delta")) <= 0
                for row in token_deltas
            ):
                findings.append(f"invalid_reward_wallet_deltas:{signature}")
                continue
            transaction_rows = [
                _base_row(
                    transaction,
                    event_type="reward",
                    asset=str(row.get("asset")),
                    quantity_delta=_decimal(row.get("quantity_delta")),
                    wallet=wallet,
                    audit_path=audit_path,
                )
                for row in token_deltas
            ]
        elif is_multi_asset_route:
            if len(token_deltas) < 2 and not _decimal(transaction.get("wallet_non_fee_sol_delta")):
                findings.append(f"route_without_two_asset_legs:{signature}")
                continue
            transaction_rows = [
                _base_row(
                    transaction,
                    event_type="token_transfer",
                    asset=str(row.get("asset")),
                    quantity_delta=_decimal(row.get("quantity_delta")),
                    wallet=wallet,
                    audit_path=audit_path,
                )
                for row in token_deltas
            ]
        else:
            transaction_rows = [
                _base_row(
                    transaction,
                    event_type="transfer",
                    asset=str(row.get("asset")),
                    quantity_delta=_decimal(row.get("quantity_delta")),
                    wallet=wallet,
                    audit_path=audit_path,
                )
                for row in token_deltas
            ]

        chain_sol = _decimal(transaction.get("wallet_native_sol_delta"))
        existing_sol = existing_effects_by_tx.get(signature, {}).get("SOL", Decimal("0"))
        actual_fee_sol = _decimal(transaction.get("wallet_fee_sol"))
        existing_fee_sol = existing_fees_by_tx.get(signature, Decimal("0"))
        fee_sol = actual_fee_sol - existing_fee_sol
        if fee_sol < 0:
            findings.append(f"canonical_fee_exceeds_chain_fee:{signature}:{fee_sol}")
            continue
        non_fee_sol = chain_sol - existing_sol + fee_sol
        if non_fee_sol:
            transaction_rows.append(
                _base_row(
                    transaction,
                    event_type="sol_transfer",
                    asset="SOL",
                    quantity_delta=non_fee_sol,
                    wallet=wallet,
                    audit_path=audit_path,
                )
            )
        primary = next(
            (row for row in transaction_rows if str(row.get("side")) == "in"),
            transaction_rows[0],
        )
        if fee_sol > 0:
            primary["fee_asset"] = "SOL"
            primary["fee_quantity"] = str(fee_sol)
        rows.extend(transaction_rows)
    rows.sort(key=lambda row: (str(row.get("timestamp_utc")), str(row.get("tx_id")), str(row.get("asset"))))
    return rows, sorted(set(findings))


def _event_balance_effect(events: list[object]) -> dict[str, Decimal]:
    result: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for event in events:
        result[str(event.asset)] += event.quantity
        if event.event_type == "trade" and event.quote_asset and event.quote_quantity is not None:
            quote_delta = abs(event.quote_quantity)
            result[event.quote_asset] += -quote_delta if event.quantity > 0 else quote_delta
        if event.fee_asset and event.fee_quantity is not None:
            result[event.fee_asset] -= abs(event.fee_quantity)
    return dict(result)


def _expected_balance_effect(
    payload: dict[str, Any],
    existing_effects_by_tx: dict[str, dict[str, Decimal]] | None = None,
) -> dict[str, Decimal]:
    result: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    existing_effects_by_tx = existing_effects_by_tx or {}
    transactions, _findings = _candidate_transactions(payload)
    for transaction in transactions:
        signature = str(transaction.get("signature") or "")
        for row in transaction.get("wallet_token_deltas", []):
            if isinstance(row, dict) and row.get("asset"):
                asset = str(row["asset"])
                result[asset] += _decimal(row.get("quantity_delta")) - existing_effects_by_tx.get(
                    signature, {}
                ).get(asset, Decimal("0"))
        result["SOL"] += _decimal(transaction.get("wallet_native_sol_delta")) - existing_effects_by_tx.get(
            signature, {}
        ).get("SOL", Decimal("0"))
    return {asset: quantity for asset, quantity in result.items() if quantity != 0}


def verify_rows(
    payload: dict[str, Any],
    rows: list[dict[str, object]],
    directory: Path,
    existing_effects_by_tx: dict[str, dict[str, Decimal]] | None = None,
) -> dict[str, object]:
    store = DuckDbStore(directory / "solana-evidence-preview.duckdb")
    content = json.dumps(rows, sort_keys=True, ensure_ascii=False)
    batch = CsvRawImporter(store).import_rows(
        source=SOURCE,
        filename="solana-token-account-evidence-preview.json",
        file_hash="sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest(),
        rows=rows,
    )
    events = RawNormalizer(store).normalize_batch(batch.batch_id)
    expected = _expected_balance_effect(payload, existing_effects_by_tx)
    actual = _event_balance_effect(events)
    assets = sorted(set(expected) | set(actual))
    deltas = {asset: actual.get(asset, Decimal("0")) - expected.get(asset, Decimal("0")) for asset in assets}
    status = "ready" if events and all(delta == 0 for delta in deltas.values()) else "blocked"
    return {
        "status": status,
        "raw_rows_count": len(rows),
        "normalized_events_count": len(events),
        "event_type_counts": {
            event_type: sum(event.event_type == event_type for event in events)
            for event_type in sorted({event.event_type for event in events})
        },
        "expected_balance_effect": {asset: str(expected.get(asset, Decimal("0"))) for asset in assets},
        "normalized_balance_effect": {asset: str(actual.get(asset, Decimal("0"))) for asset in assets},
        "balance_effect_delta": {asset: str(deltas[asset]) for asset in assets},
    }


def _existing_wallet_txids(store: DuckDbStore, txids: list[str], wallet: str) -> set[str]:
    if not txids:
        return set()
    with store.connect() as con:
        rows = con.execute(
            """
            select distinct tx_id
            from canonical_events
            where tx_id in (select unnest(?))
              and (account = ? or wallet = ?)
            """,
            [txids, wallet, wallet],
        ).fetchall()
    return {str(row[0]) for row in rows}


def _existing_wallet_effects(
    store: DuckDbStore,
    txids: list[str],
    wallet: str,
) -> tuple[dict[str, dict[str, Decimal]], dict[str, Decimal]]:
    if not txids:
        return {}, {}
    with store.connect() as con:
        effect_rows = con.execute(
            """
            select event.tx_id, ledger.asset, sum(ledger.delta_quantity)
            from balance_ledger ledger
            join canonical_events event on event.event_id = ledger.event_id
            where ledger.account = ?
              and event.tx_id in (select unnest(?))
            group by event.tx_id, ledger.asset
            """,
            [wallet, txids],
        ).fetchall()
        fee_rows = con.execute(
            """
            select tx_id, sum(abs(fee_quantity))
            from canonical_events
            where (account = ? or wallet = ?)
              and fee_asset = 'SOL'
              and tx_id in (select unnest(?))
            group by tx_id
            """,
            [wallet, wallet, txids],
        ).fetchall()
    effects: defaultdict[str, dict[str, Decimal]] = defaultdict(dict)
    for signature, asset, quantity in effect_rows:
        effects[str(signature)][str(asset)] = _decimal(quantity)
    return dict(effects), {str(signature): _decimal(quantity) for signature, quantity in fee_rows}


def _production_state(store: DuckDbStore, wallet: str) -> dict[str, object]:
    with store.connect() as con:
        counts = {
            table: int(con.execute(f"select count(*) from {table}").fetchone()[0])
            for table in ("raw_import_batches", "raw_objects", "canonical_events", "tax_lots", "tax_lines")
        }
        balances = con.execute(
            """
            select asset, sum(delta_quantity)
            from balance_ledger
            where account = ?
              and asset in ('HNT', 'IOT', 'JUP', 'MOBILE', 'SOL', 'USDC')
            group by asset
            order by asset
            """,
            [wallet],
        ).fetchall()
        rewards = con.execute(
            """
            select extract(year from event_time)::integer, asset, count(*), sum(quantity)
            from canonical_events
            where event_type in ('reward', 'mining', 'staking')
              and asset in ('HNT', 'IOT', 'MOBILE')
              and extract(year from event_time)::integer in (2025, 2026)
            group by 1, 2
            order by 1, 2
            """
        ).fetchall()
        tax_lines = con.execute(
            """
            select extract(year from disposed_at)::integer, count(*), sum(gain_loss_eur)
            from tax_lines
            where extract(year from disposed_at)::integer in (2025, 2026)
            group by 1
            order by 1
            """
        ).fetchall()
    gate = ReviewService(store).gate()
    state = {
        "counts": counts,
        "wallet_balances": {str(asset): str(quantity) for asset, quantity in balances},
        "reward_quantities": [
            {"year": int(year), "asset": str(asset), "events_count": int(count), "quantity": str(quantity)}
            for year, asset, count, quantity in rewards
        ],
        "tax_lines": [
            {"year": int(year), "lines_count": int(count), "gain_loss_eur": str(gain_loss or Decimal("0"))}
            for year, count, gain_loss in tax_lines
        ],
        "review_gate": {
            "allow_export": gate.allow_export,
            "issues_open": gate.issues_open,
        },
    }
    state["sha256"] = hashlib.sha256(
        json.dumps(state, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return state


def run(args: argparse.Namespace) -> dict[str, object]:
    audit_path = Path(args.audit).resolve()
    payload = _load_json(audit_path)
    store = DuckDbStore(Path(args.db))
    candidate_transactions, candidate_findings = _candidate_transactions(payload)
    candidate_txids = sorted(
        {str(row.get("signature") or "") for row in candidate_transactions if row.get("signature")}
    )
    wallet = str(payload.get("wallet") or "")
    existing_effects, existing_fees = _existing_wallet_effects(store, candidate_txids, wallet)
    rows, findings = build_backfill_rows(
        payload,
        audit_path=audit_path,
        existing_effects_by_tx=existing_effects,
        existing_fees_by_tx=existing_fees,
    )
    findings.extend(candidate_findings)
    txids = sorted({str(row.get("tx_id") or "") for row in rows if row.get("tx_id")})
    existing = _existing_wallet_txids(store, txids, str(payload.get("wallet") or ""))
    with tempfile.TemporaryDirectory(prefix="steuerreport-solana-evidence-") as temp_dir:
        verification = verify_rows(payload, rows, Path(temp_dir), existing_effects)
    ready = bool(rows) and not findings and verification["status"] == "ready"
    generated_at = datetime.now(timezone.utc)
    row_content = json.dumps(rows, sort_keys=True, ensure_ascii=False)
    file_hash = "sha256:" + hashlib.sha256(row_content.encode("utf-8")).hexdigest()
    report: dict[str, object] = {
        "generated_at": generated_at.isoformat(),
        "mode": "apply" if args.apply else "preview",
        "status": "ready" if ready and not args.apply else "blocked" if not ready else "applying",
        "source_audit": str(audit_path.relative_to(PROJECT_ROOT)),
        "source_audit_sha256": hashlib.sha256(audit_path.read_bytes()).hexdigest(),
        "file_hash": file_hash,
        "candidate_transactions_count": len(txids),
        "candidate_raw_rows_count": len(rows),
        "existing_canonical_txids_count": len(existing),
        "findings": sorted(set(findings)),
        "verification": verification,
        "target_changed": False,
        "rollback": None,
        "methodology": (
            "Evidence-bound Solana backfill through CsvRawImporter, RawNormalizer and PipelineService. "
            "The same rows are first normalized in an isolated temporary V2 database and every asset "
            "balance effect must equal the Alchemy token-account evidence exactly. Existing effects under "
            "the same TXID are subtracted before partial rows are built; unknown mints, overcharged fees, "
            "unsupported classifications or incomplete history block apply."
        ),
    }
    if args.apply:
        if not ready:
            raise RuntimeError("backfill_not_ready: " + ", ".join(report["findings"]))
        report["pre_apply_state"] = _production_state(store, str(payload.get("wallet") or ""))
        batch = CsvRawImporter(store).import_rows(
            source=SOURCE,
            filename=f"solana-token-account-evidence-{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json",
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
                "target_changed": True,
                "rollback": {
                    "method": "existing_import_delete_api",
                    "endpoint": f"DELETE /api/v1/import/batches/{batch.batch_id}",
                },
                "post_apply_state": _production_state(store, str(payload.get("wallet") or "")),
            }
        )

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    content = json.dumps(report, indent=2, ensure_ascii=False)
    versioned = output_dir / f"solana_evidence_backfill_{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    latest = output_dir / "latest_solana_evidence_backfill.json"
    versioned.write_text(content, encoding="utf-8")
    latest.write_text(content, encoding="utf-8")
    report["artifact_path"] = str(versioned.relative_to(PROJECT_ROOT))
    report["latest_artifact_path"] = str(latest.relative_to(PROJECT_ROOT))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Evidence-bound Solana token-account backfill")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--audit", default=str(DEFAULT_AUDIT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    report = run(args)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
