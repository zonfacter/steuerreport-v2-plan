#!/usr/bin/env python3
from __future__ import annotations

from steuerreport_v2.paths import PROJECT_ROOT as SOFTWARE_ROOT

from steuerreport_v2.private_settings import private_value

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from steuerreport_v2.contracts.events import CanonicalEvent, CanonicalEventCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer


PROJECT_ROOT = SOFTWARE_ROOT
DEFAULT_SOURCE_CSV = Path(
    "/workspace/steuerreport/usertransfer/2025 Transaktionen Blockpit.csv"
)
DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
EXPECTED_SOURCE_SHA256 = (
    "3a8ce90440f17d0da51f0b7db7309c7c16ca2c401decd53b43e9af6c5748a331"
)
SOURCE = "blockpit"
FILENAME = "bitget-2025-complete-withdrawal-account-history-blockpit.csv"
EXPECTED_SOURCE_ROWS = 2304
EXPECTED_FIAT_CONVERSION_PAIRS = 2
EXPECTED_UNMERGED_TRADE_PAIRS = 2


KNOWN_TRANSFER_EVIDENCE = {
    ("29.01.2025 05:56:22", "Deposit", "USDT", "5009.09824537"): {
        "tx_id": "0xafe24daadbd2adbae1636acfffa8f45e4b8c740013509c9394c9ce0efaec6260",
        "exchange_reference": "1268375403930660876",
        "address": private_value('configured_identifier_04'),
        "network": "BSC",
        "evidence": "binance_withdrawal_api+bitget_tax_api+blockpit",
    },
    ("09.03.2025 19:00:22", "Withdrawal", "HNT", "859.9208492"): {
        "tx_id": "2aXZm773QRWKY3pQGLqQbgVm6JKAg7FZ2L3mLMBK6kBFYQPjbuk2DavdxEuN2BYTnDQx4YhAz6HxyfTZT2ya29PR",
        "exchange_reference": "1282705829779644421",
        "address": private_value('primary_solana_wallet'),
        "network": "SOL",
        "evidence": "bitget_tax_api+blockpit+alchemy_onchain",
    },
    ("04.04.2025 17:09:22", "Deposit", "HNT", "16.16462275"): {
        "tx_id": "493kaSDxGNSg68id3pT3EYMMLrYFHCsuDPacbyBtmxqE9eQdDJCRqoai2r6qSc1ZGHBV2Lco9bVTVNEFQdgTtYRt",
        "exchange_reference": "1292099980770058240",
        "address": private_value('configured_identifier_79'),
        "network": "SOL",
        "evidence": "bitget_tax_api+blockpit+alchemy_onchain",
    },
    ("15.06.2025 07:30:36", "Withdrawal", "JUP", "4680.175116"): {
        "tx_id": "7uGkDCMh3HLNuoGWDicgjHr2qxRYHc2npkKbZQnm9xuBYX4FbUB5dS7dGfkW9pNoW34rofKgG6cbNKcVK7froQd",
        "exchange_reference": "1318045704815505408",
        "address": private_value('configured_identifier_100'),
        "network": "SOL",
        "evidence": "bitget_withdrawal_api+blockpit+alchemy_onchain",
    },
    ("15.06.2025 07:45:46", "Withdrawal", "SOL", "7.0700475"): {
        "tx_id": "at5BgXG6YqAdQDXhMe3hygE7Z1Kh74GTtGBmZACerbsR8SgjCqhYGGtN4bVp4f9WSawDPxfop9wguuVPnUHscpw",
        "exchange_reference": "1318049559880003584",
        "address": private_value('configured_identifier_100'),
        "network": "SOL",
        "evidence": "bitget_withdrawal_api+blockpit+alchemy_onchain",
    },
}


def _source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _transfer_key(row: dict[str, str]) -> tuple[str, str, str, str] | None:
    label = str(row.get("Label") or "")
    asset = str(row.get("Incoming Asset") or row.get("Outgoing Asset") or "")
    amount = str(row.get("Incoming Amount") or row.get("Outgoing Amount") or "")
    if not asset or not amount:
        return None
    return str(row.get("Date (UTC)") or ""), label, asset, amount


def _row_time(row: dict[str, str]) -> datetime:
    return datetime.strptime(str(row.get("Date (UTC)") or ""), "%d.%m.%Y %H:%M:%S")


def _pair_bitget_account_rows(
    source_rows: list[dict[str, str]],
    *,
    expected_fiat_conversion_pairs: int = EXPECTED_FIAT_CONVERSION_PAIRS,
    expected_unmerged_trade_pairs: int = EXPECTED_UNMERGED_TRADE_PAIRS,
) -> list[dict[str, str]]:
    rows = [dict(row) for row in source_rows]
    evidence_only_indexes: dict[int, str] = {}
    conversion_pairs = 0
    unmerged_pairs = 0

    for incoming_index, incoming in enumerate(rows):
        label = str(incoming.get("Label") or "")
        comment = str(incoming.get("Comment (optional)") or "")
        if label != "Deposit" or not incoming.get("Incoming Amount"):
            continue
        if comment == "Fiat/Crypto Conversion":
            candidates = [
                (index, outgoing)
                for index, outgoing in enumerate(rows)
                if index not in evidence_only_indexes
                and outgoing.get("Label") == "Withdrawal"
                and outgoing.get("Comment (optional)") == comment
                and outgoing.get("Outgoing Amount")
                and outgoing.get("Outgoing Asset")
                and 0
                <= (_row_time(incoming) - _row_time(outgoing)).total_seconds()
                <= 10
            ]
            record_type = "bitget_fiat_conversion_trade"
            evidence_record_type = "bitget_fiat_conversion_out_evidence"
        elif comment == "Unmerged Trade (deal_in)":
            candidates = [
                (index, outgoing)
                for index, outgoing in enumerate(rows)
                if index not in evidence_only_indexes
                and outgoing.get("Label") == "Withdrawal"
                and outgoing.get("Comment (optional)") == "Unmerged Trade (deal_out)"
                and outgoing.get("Outgoing Amount")
                and outgoing.get("Outgoing Asset")
                and _row_time(incoming) == _row_time(outgoing)
            ]
            record_type = "bitget_unmerged_trade"
            evidence_record_type = "bitget_unmerged_trade_out_evidence"
        else:
            continue
        if len(candidates) != 1:
            raise RuntimeError(
                "ambiguous_bitget_trade_pair:"
                f"{incoming.get('Date (UTC)')}:{comment}:{len(candidates)}"
            )
        outgoing_index, outgoing = candidates[0]
        incoming["Original Label"] = label
        incoming["Label"] = "Trade"
        incoming["Outgoing Amount"] = str(outgoing["Outgoing Amount"])
        incoming["Outgoing Asset"] = str(outgoing["Outgoing Asset"])
        incoming["Record Type"] = record_type
        incoming["Paired Out Trx. ID"] = str(outgoing.get("Trx. ID (optional)") or "")
        incoming["Trx. ID (optional)"] = "-".join(
            value
            for value in (
                str(outgoing.get("Trx. ID (optional)") or ""),
                str(incoming.get("Trx. ID (optional)") or ""),
            )
            if value
        )
        evidence_only_indexes[outgoing_index] = evidence_record_type
        if record_type == "bitget_fiat_conversion_trade":
            conversion_pairs += 1
        else:
            unmerged_pairs += 1

    if conversion_pairs != expected_fiat_conversion_pairs:
        raise RuntimeError(
            f"unexpected_fiat_conversion_pairs:{conversion_pairs}:"
            f"expected:{expected_fiat_conversion_pairs}"
        )
    if unmerged_pairs != expected_unmerged_trade_pairs:
        raise RuntimeError(
            f"unexpected_unmerged_trade_pairs:{unmerged_pairs}:"
            f"expected:{expected_unmerged_trade_pairs}"
        )
    for index, record_type in evidence_only_indexes.items():
        rows[index]["Record Type"] = record_type
    return rows


def source_rows(path: Path) -> list[dict[str, str]]:
    source_hash = _source_sha256(path)
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise RuntimeError(
            f"unexpected_source_sha256:{source_hash}:expected:{EXPECTED_SOURCE_SHA256}"
        )
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [
            dict(row)
            for row in csv.DictReader(handle, delimiter=";")
            if str(row.get("Integration Name") or "").strip() == "Bitget"
        ]
    if len(rows) != EXPECTED_SOURCE_ROWS:
        raise RuntimeError(
            f"unexpected_bitget_source_rows:{len(rows)}:expected:{EXPECTED_SOURCE_ROWS}"
        )
    enriched: list[dict[str, str]] = []
    for source_row in _pair_bitget_account_rows(rows):
        row = dict(source_row)
        # Consolidate Blockpit's display casing with the existing V2 Bitget pool.
        row["Integration Name"] = "bitget"
        row["Source Name"] = "bitget"
        evidence = KNOWN_TRANSFER_EVIDENCE.get(_transfer_key(row))
        if evidence:
            row["Trx. ID (optional)"] = evidence["tx_id"]
            row["Bitget Exchange Reference"] = evidence["exchange_reference"]
            row["Address"] = evidence["address"]
            row["Network"] = evidence["network"]
            row["Evidence Source"] = evidence["evidence"]
            row["amount"] = str(
                row.get("Incoming Amount") or row.get("Outgoing Amount") or ""
            )
            row["withdrawal fee"] = str(row.get("Fee Amount (optional)") or "")
            row["tx_id"] = evidence["tx_id"]
        enriched.append(row)
    return enriched


def _normalized_event(
    normalizer: RawNormalizer,
    row: dict[str, str],
) -> CanonicalEventCreate | None:
    return normalizer._row_to_event(SOURCE, "preview", row)


def _event_key(event: CanonicalEvent | CanonicalEventCreate) -> tuple[object, ...]:
    event_time = event.event_time.astimezone(timezone.utc).replace(microsecond=0)
    account = str(event.account or event.wallet or "").strip().lower()
    return (
        event_time,
        account,
        event.event_type,
        event.asset.upper(),
        event.quantity,
        str(event.quote_asset or "").upper(),
        event.quote_quantity,
        str(event.fee_asset or "").upper(),
        abs(event.fee_quantity) if event.fee_quantity is not None else None,
    )


def prepared_rows(
    store: DuckDbStore,
    path: Path,
) -> tuple[list[dict[str, str]], int, dict[str, int]]:
    normalizer = RawNormalizer(store)
    existing_keys = {
        _event_key(event)
        for event in store.list_canonical_events()
        if (
            str(event.account or event.wallet or "").strip().lower() == "bitget"
            or event.source.lower().startswith("bitget")
        )
        and event.event_time.year == 2025
    }
    selected: list[dict[str, str]] = []
    duplicate_count = 0
    labels: dict[str, int] = {}
    for row in source_rows(path):
        event = _normalized_event(normalizer, row)
        if event is None:
            raise RuntimeError(
                f"bitget_blockpit_row_not_normalizable:{row.get('Date (UTC)')}:{row.get('Label')}"
            )
        if _event_key(event) in existing_keys:
            duplicate_count += 1
            continue
        selected.append(row)
        label = str(row.get("Label") or "unknown")
        labels[label] = labels.get(label, 0) + 1
    return selected, duplicate_count, dict(sorted(labels.items()))


def _semantic_sha256(rows: list[dict[str, str]]) -> str:
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _write_artifact(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Imports the complete Bitget 2025 Blockpit account history through "
            "V2 services after exact source-hash and semantic duplicate checks."
        )
    )
    parser.add_argument("--source-csv", type=Path, default=DEFAULT_SOURCE_CSV)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--artifact", type=Path)
    args = parser.parse_args()

    store = DuckDbStore(args.db)
    rows, duplicates, labels = prepared_rows(store, args.source_csv)
    semantic_sha256 = _semantic_sha256(rows)
    file_hash = f"sha256:{semantic_sha256}"
    duplicate_batch = store.get_import_batch_by_file_hash(SOURCE, file_hash)
    already_current = not rows and duplicates == EXPECTED_SOURCE_ROWS
    result: dict[str, object] = {
        "status": (
            "already_current"
            if already_current
            else "duplicate"
            if duplicate_batch
            else "preview"
        ),
        "execute": args.execute,
        "source_csv": str(args.source_csv),
        "source_sha256": _source_sha256(args.source_csv),
        "source_bitget_rows_count": EXPECTED_SOURCE_ROWS,
        "existing_semantic_duplicates_skipped": duplicates,
        "rows_prepared": len(rows),
        "labels": labels,
        "known_transfer_evidence_count": sum(
            1 for row in rows if row.get("Evidence Source")
        ),
        "fiat_conversion_trade_count": sum(
            1 for row in rows if row.get("Record Type") == "bitget_fiat_conversion_trade"
        ),
        "unmerged_trade_count": sum(
            1 for row in rows if row.get("Record Type") == "bitget_unmerged_trade"
        ),
        "evidence_only_pair_legs_count": sum(
            1
            for row in rows
            if str(row.get("Record Type") or "").endswith("_out_evidence")
        ),
        "semantic_sha256": semantic_sha256,
        "duplicate_batch_id": duplicate_batch.batch_id if duplicate_batch else None,
        "methodology": (
            "Vollstaendiger Bitget-2025-Accountverlauf aus dem originalen, "
            "SHA-256-gebundenen Blockpit-Export. Bereits vorhandene semantisch "
            "identische V2-Events werden vor dem Import uebersprungen. Bekannte "
            "Binance/Bitget/Solana-Transfers werden mit vorhandenen API- und "
            "Alchemy-TXIDs angereichert. Fiat/Krypto-Konvertierungen und von "
            "Blockpit getrennt exportierte deal_in/deal_out-Legs werden "
            "deterministisch zu Trades verbunden; das Ausgangs-Leg bleibt als "
            "mengenneutraler Rohbeleg erhalten. Schreibzugriff erfolgt nur ueber "
            "CsvRawImporter und PipelineService bei --execute."
        ),
    }
    if args.execute and duplicate_batch is None and not already_current:
        batch = CsvRawImporter(store).import_rows(
            source=SOURCE,
            filename=FILENAME,
            file_hash=file_hash,
            rows=rows,
        )
        pipeline = PipelineService(store).rebuild_after_import(batch.batch_id)
        result.update(
            {
                "status": "imported",
                "batch_id": batch.batch_id,
                "pipeline": pipeline.model_dump(mode="json"),
            }
        )
    if args.artifact:
        _write_artifact(args.artifact, result)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
