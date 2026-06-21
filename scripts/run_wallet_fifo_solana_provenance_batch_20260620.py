#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService


PROJECT_ROOT = Path("/workspace/steuerreport-v2-plan")
DEFAULT_DB = PROJECT_ROOT / "data" / "steuerreport_v2.duckdb"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "var" / "solana_provenance_batches"
DEFAULT_POOL_ID = "solana_rpc:G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY"
FAILED_STATUSES = {"failed", "not_found", "rate_limited", "missing_txid"}


def _log(message: str) -> None:
    print(f"{datetime.now(timezone.utc).isoformat()} {message}", flush=True)


def _summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        k: result[k]
        for k in (
            "run_id",
            "year",
            "asset",
            "pool_id",
            "provider",
            "total_events",
            "classified_count",
            "own_transfer_candidates_count",
            "external_or_unknown_count",
            "failed_count",
        )
    }


def _build_result(
    *,
    run_id: str,
    args: argparse.Namespace,
    db_path: Path,
    batch_size: int,
    max_events: int,
    total_events: int | None,
    classifications_by_event: dict[str, dict[str, Any]],
    batches: list[dict[str, Any]],
) -> dict[str, Any]:
    classifications = list(classifications_by_event.values())
    return {
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db": str(db_path.resolve()),
        "year": args.year,
        "asset": args.asset.upper(),
        "pool_id": args.pool_id,
        "provider": args.provider,
        "rpc_url": args.rpc_url if args.provider != "solscan" else None,
        "batch_size": batch_size,
        "max_events": max_events,
        "total_events": total_events or 0,
        "classified_count": len(classifications),
        "own_transfer_candidates_count": sum(1 for item in classifications if item.get("status") == "own_wallet_transfer_candidate"),
        "external_or_unknown_count": sum(1 for item in classifications if item.get("status") == "external_or_unknown_origin"),
        "failed_count": sum(1 for item in classifications if item.get("status") in FAILED_STATUSES),
        "classifications": classifications,
        "batches": batches,
        "methodology": (
            "Read-only Batch-Artefakt fuer Wallet-FIFO-Solana-Provenance. "
            "Es werden bekannte TXIDs ueber Solana Public RPC oder optional Solscan klassifiziert. "
            "Es werden keine Imports, Transferanker, Tax-Lines, Lots oder Review-Entscheidungen geschrieben."
        ),
    }


def _write_result(paths: tuple[Path, Path], result: dict[str, Any]) -> None:
    output_path, latest_path = paths
    payload = json.dumps(result, indent=2, ensure_ascii=False, default=str)
    for path in (output_path, latest_path):
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only Batch-Klassifizierung offener SOL Wallet-FIFO-Provenance-Events."
    )
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--year", type=int, default=2024)
    parser.add_argument("--asset", default="SOL")
    parser.add_argument("--pool-id", default=DEFAULT_POOL_ID)
    parser.add_argument("--provider", default="rpc_public", choices=("rpc_public", "rpc", "solscan"))
    parser.add_argument("--rpc-url", default=WalletFifoPreviewService.DEFAULT_SOLANA_RPC_URL)
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--max-events", type=int, default=50)
    parser.add_argument("--delay-seconds", type=float, default=0.25)
    parser.add_argument("--retry-failed", type=int, default=1)
    parser.add_argument("--retry-delay-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=int, default=20)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("run_%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"{run_id}_{args.year}_{args.asset.upper()}_provenance_classification.json"
    latest_path = output_dir / f"latest_{args.year}_{args.asset.upper()}_provenance_classification.json"

    db_path = Path(args.db)
    service = WalletFifoPreviewService(DuckDbStore(args.db))
    batch_size = max(1, min(int(args.batch_size), 25))
    max_events = max(1, int(args.max_events))
    classifications_by_event: dict[str, dict[str, Any]] = {}
    if args.resume and latest_path.exists():
        try:
            previous = json.loads(latest_path.read_text(encoding="utf-8"))
            for item in previous.get("classifications", []):
                if item.get("event_id") and item.get("status") not in {"failed", "not_found", "rate_limited", "missing_txid"}:
                    classifications_by_event[str(item["event_id"])] = item
        except Exception:
            classifications_by_event = {}
    batches: list[dict[str, Any]] = []
    offset = 0
    total_events: int | None = None
    paths = (output_path, latest_path)

    _log(
        "start "
        f"run_id={run_id} year={args.year} asset={args.asset.upper()} pool_id={args.pool_id} "
        f"provider={args.provider} max_events={max_events} batch_size={batch_size} "
        f"resume_cached={len(classifications_by_event)}"
    )
    event_report = service.provenance_events(
        args.year,
        asset=args.asset,
        pool_id=args.pool_id,
        offset=0,
        limit=max_events,
    )
    total_events = event_report.events_count
    all_events = event_report.events[:max_events]
    normalized_provider = args.provider.strip().lower()
    if normalized_provider == "rpc_public":
        normalized_provider = "rpc"
    solscan_key = service._solscan_api_key() if normalized_provider == "solscan" else ""
    _log(f"loaded_events total_events={total_events} selected={len(all_events)}")

    with httpx.Client(timeout=max(3, min(int(args.timeout_seconds), 60))) as client:
      while offset < max_events and offset < len(all_events):
        limit = min(batch_size, max_events - offset)
        events = all_events[offset : offset + limit]
        event_ids = [event.event_id for event in events]
        if event_ids and all(event_id in classifications_by_event for event_id in event_ids):
            batches.append(
                {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "year": args.year,
                    "asset": args.asset.upper(),
                    "pool_id": args.pool_id,
                    "offset": offset,
                    "limit": limit,
                    "requested_events_count": total_events,
                    "classified_count": len(event_ids),
                    "failed_count": 0,
                    "attempt": 0,
                    "status": "skipped_resume_cache",
                    "classifications": [classifications_by_event[event_id] for event_id in event_ids],
                }
            )
            result = _build_result(
                run_id=run_id,
                args=args,
                db_path=db_path,
                batch_size=batch_size,
                max_events=max_events,
                total_events=total_events,
                classifications_by_event=classifications_by_event,
                batches=batches,
            )
            _write_result(paths, result)
            _log(
                f"skip offset={offset} limit={limit} cached={len(event_ids)} "
                f"classified={result['classified_count']} failed={result['failed_count']}"
            )
            if offset + limit >= total_events:
                break
            offset += limit
            continue
        if not event_ids:
            break
        classifications = []
        for event in events:
            signature = event.onchain_tx_id or event.tx_id
            if not signature:
                classifications.append(
                    service._solana_provenance_classification_error(
                        event=event,
                        signature="",
                        status="missing_txid",
                        reason="provenance_event_without_txid",
                    ).model_dump(mode="json")
                )
            elif normalized_provider == "solscan":
                if not solscan_key:
                    classifications.append(
                        service._solana_provenance_classification_error(
                            event=event,
                            signature=signature,
                            status="failed",
                            reason="solscan_api_key_missing",
                            evidence_source="solscan",
                        ).model_dump(mode="json")
                    )
                else:
                    classifications.append(
                        service._fetch_solscan_provenance_classification(
                            client=client,
                            api_key=solscan_key,
                            event=event,
                        ).model_dump(mode="json")
                    )
            else:
                classifications.append(
                    service._fetch_solana_provenance_classification(
                        client=client,
                        rpc_url=args.rpc_url,
                        event=event,
                    ).model_dump(mode="json")
                )
        batch_payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "year": args.year,
            "asset": args.asset.upper(),
            "pool_id": args.pool_id,
            "offset": offset,
            "limit": limit,
            "requested_events_count": total_events,
            "classified_count": len(classifications),
            "own_transfer_candidates_count": sum(1 for item in classifications if item.get("status") == "own_wallet_transfer_candidate"),
            "external_or_unknown_count": sum(1 for item in classifications if item.get("status") == "external_or_unknown_origin"),
            "failed_count": sum(1 for item in classifications if item.get("status") in FAILED_STATUSES),
            "classifications": classifications,
            "methodology": "Read-only direct batch classification from preloaded provenance events.",
        }
        batch_payload["attempt"] = 1
        batches.append(batch_payload)
        _log(
            f"batch offset={offset} limit={limit} attempt=1 "
            f"classified={batch_payload.get('classified_count')} failed={batch_payload.get('failed_count')}"
        )
        failed = [
            item for item in classifications
            if item.get("status") in FAILED_STATUSES
        ]
        attempts = 1
        while failed and attempts <= max(0, int(args.retry_failed)):
            if args.retry_delay_seconds > 0:
                time.sleep(float(args.retry_delay_seconds) * attempts)
            retry_classifications = []
            failed_event_ids = {str(item.get("event_id")) for item in failed if item.get("event_id")}
            for event in events:
                if event.event_id not in failed_event_ids:
                    continue
                signature = event.onchain_tx_id or event.tx_id
                if not signature:
                    retry_classifications.append(
                        service._solana_provenance_classification_error(
                            event=event,
                            signature="",
                            status="missing_txid",
                            reason="provenance_event_without_txid",
                        ).model_dump(mode="json")
                    )
                elif normalized_provider == "solscan":
                    if not solscan_key:
                        retry_classifications.append(
                            service._solana_provenance_classification_error(
                                event=event,
                                signature=signature,
                                status="failed",
                                reason="solscan_api_key_missing",
                                evidence_source="solscan",
                            ).model_dump(mode="json")
                        )
                    else:
                        retry_classifications.append(
                            service._fetch_solscan_provenance_classification(
                                client=client,
                                api_key=solscan_key,
                                event=event,
                            ).model_dump(mode="json")
                        )
                else:
                    retry_classifications.append(
                        service._fetch_solana_provenance_classification(
                            client=client,
                            rpc_url=args.rpc_url,
                            event=event,
                        ).model_dump(mode="json")
                    )
            retry_payload = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "year": args.year,
                "asset": args.asset.upper(),
                "pool_id": args.pool_id,
                "offset": offset,
                "limit": limit,
                "requested_events_count": total_events,
                "classified_count": len(retry_classifications),
                "own_transfer_candidates_count": sum(1 for item in retry_classifications if item.get("status") == "own_wallet_transfer_candidate"),
                "external_or_unknown_count": sum(1 for item in retry_classifications if item.get("status") == "external_or_unknown_origin"),
                "failed_count": sum(1 for item in retry_classifications if item.get("status") in FAILED_STATUSES),
                "classifications": retry_classifications,
                "methodology": "Read-only retry classification from preloaded provenance events.",
            }
            retry_payload["attempt"] = attempts + 1
            batches.append(retry_payload)
            _log(
                f"batch offset={offset} limit={limit} attempt={attempts + 1} "
                f"classified={retry_payload.get('classified_count')} failed={retry_payload.get('failed_count')}"
            )
            retry_by_event = {
                str(item.get("event_id")): item
                for item in retry_payload.get("classifications", [])
                if item.get("event_id")
            }
            classifications = [
                retry_by_event.get(str(item.get("event_id")), item)
                if item.get("status") in {"failed", "not_found", "rate_limited", "missing_txid"}
                else item
                for item in classifications
            ]
            failed = [
                item for item in classifications
                if item.get("status") in FAILED_STATUSES
            ]
            attempts += 1
        for item in classifications:
            if item.get("event_id"):
                classifications_by_event[str(item["event_id"])] = item
        result = _build_result(
            run_id=run_id,
            args=args,
            db_path=db_path,
            batch_size=batch_size,
            max_events=max_events,
            total_events=total_events,
            classifications_by_event=classifications_by_event,
            batches=batches,
        )
        _write_result(paths, result)
        _log(
            f"progress offset={offset} total_events={result['total_events']} "
            f"classified={result['classified_count']} failed={result['failed_count']} "
            f"own={result['own_transfer_candidates_count']} external_unknown={result['external_or_unknown_count']}"
        )
        if not batch_payload.get("classifications") or offset + limit >= (total_events or 0):
            break
        offset += limit
        if args.delay_seconds > 0:
            time.sleep(float(args.delay_seconds))

    result = _build_result(
        run_id=run_id,
        args=args,
        db_path=db_path,
        batch_size=batch_size,
        max_events=max_events,
        total_events=total_events,
        classifications_by_event=classifications_by_event,
        batches=batches,
    )
    _write_result(paths, result)
    print(json.dumps(_summary(result), indent=2), flush=True)
    print(f"artifact={output_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
