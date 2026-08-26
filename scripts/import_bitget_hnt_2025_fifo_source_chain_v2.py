#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter


PROJECT_ROOT = Path("/workspace/steuerreport-v2-plan")
DEFAULT_V1_DB = Path("/root/.local/share/steuerreport/steuerreport.db")
DEFAULT_V2_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
SOURCE = "bitget"
FILENAME = "bitget-hnt-2025-withdrawal-fifo-source-chain.csv"
BLOCKPIT_SOURCE = "bulk:blockpit:2025 Transaktionen Blockpit.csv"
MAIN_WALLET = "G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY"
BITGET_HNT_DEPOSIT_ADDRESS = "4txxDLNGsGF1HyaW957fdhpnGbPxeuyEhA2V6x284kTN"
BITGET_WITHDRAWAL_ONCHAIN_TX = (
    "4svDe4ns9YFCnpFYQ2yro5ABbmhAevyuqsoQgkT2V4TzL5tprhW6njPpA9CciK3toP3FiHcf4m97n2WuZ2xq2m27"
)
BITGET_DEPOSIT_ONCHAIN_TX = (
    "3ptDFkaw5acjo8aYa2sbAB8AZGqUC5SPAanb1EikDr7GJM1RKWzxUzRTDAg9D5rNh4f5xiqWBU7Zg9Rcn3JEoQMf"
)


@dataclass(frozen=True)
class SourceChainRow:
    time: str
    operation: str
    amount: str
    quote_amount: str | None
    fee_asset: str | None
    fee: str
    api_ids: tuple[str, ...]
    balance_after: str
    blockpit_date: str
    incoming_amount: str
    incoming_asset: str
    outgoing_amount: str
    outgoing_asset: str
    blockpit_fee: str
    blockpit_fee_asset: str
    tx_id: str
    source_ref: str
    address: str | None = None
    network: str | None = None


SOURCE_CHAIN = (
    SourceChainRow(
        time="2025-01-29T05:58:45.618000+00:00",
        operation="buy",
        amount="989.722",
        quote_amount="3640.9995719999997",
        fee_asset="HNT",
        fee="0.989722",
        api_ids=(
            "1268376005322551300",
            "1268376005322551303",
            "1268376005322551306",
        ),
        balance_after="988.733269",
        blockpit_date="29.01.2025 05:58:45",
        incoming_amount="989.722",
        incoming_asset="HNT",
        outgoing_amount="3640.9995719999997",
        outgoing_asset="USDT",
        blockpit_fee="0.989722",
        blockpit_fee_asset="HNT",
        tx_id="bitget-tax-api-merged:1268376005322551300-1268376005322551306",
        source_ref="bitget-tax-api:1268376005322551300,1268376005322551303,1268376005322551306",
    ),
    SourceChainRow(
        time="2025-01-29T05:59:03.852000+00:00",
        operation="buy",
        amount="12",
        quote_amount="44.112",
        fee_asset="HNT",
        fee="0.012",
        api_ids=("1268376081839239176",),
        balance_after="1000.721269",
        blockpit_date="29.01.2025 05:59:03",
        incoming_amount="12",
        incoming_asset="HNT",
        outgoing_amount="44.112",
        outgoing_asset="USDT",
        blockpit_fee="0.012",
        blockpit_fee_asset="HNT",
        tx_id="bitget-tax-api:1268376081839239176",
        source_ref="bitget-tax-api:1268376081839239176",
    ),
    SourceChainRow(
        time="2025-01-30T05:36:02.308000+00:00",
        operation="sell",
        amount="140.283",
        quote_amount="599.999634",
        fee_asset="USDT",
        fee="0.599999634",
        api_ids=(
            "1268732675030593538",
            "1268732675030593541",
            "1268732675030593544",
            "1268732675030593547",
        ),
        balance_after="860.438269",
        blockpit_date="30.01.2025 05:36:02",
        incoming_amount="599.999634",
        incoming_asset="USDT",
        outgoing_amount="140.283",
        outgoing_asset="HNT",
        blockpit_fee="0.599999634",
        blockpit_fee_asset="USDT",
        tx_id="bitget-tax-api-merged:1268732675030593538-1268732675030593547",
        source_ref="bitget-tax-api:1268732675030593538,1268732675030593541,1268732675030593544,1268732675030593547",
    ),
    SourceChainRow(
        time="2025-03-09T19:00:22.011000+00:00",
        operation="withdrawal",
        amount="859.9208492",
        quote_amount=None,
        fee_asset="HNT",
        fee="0.5174198",
        api_ids=("1282705829779644421",),
        balance_after="0",
        blockpit_date="09.03.2025 19:00:22",
        incoming_amount="",
        incoming_asset="",
        outgoing_amount="859.9208492",
        outgoing_asset="HNT",
        blockpit_fee="0.5174198",
        blockpit_fee_asset="HNT",
        tx_id=BITGET_WITHDRAWAL_ONCHAIN_TX,
        source_ref="bitget-tax-api:1282705829779644421",
        address=MAIN_WALLET,
        network="SOL",
    ),
    SourceChainRow(
        time="2025-04-04T17:09:22.107000+00:00",
        operation="deposit",
        amount="16.16462275",
        quote_amount=None,
        fee_asset=None,
        fee="0",
        api_ids=("1292099980770058240",),
        balance_after="16.16462275",
        blockpit_date="04.04.2025 17:09:22",
        incoming_amount="16.16462275",
        incoming_asset="HNT",
        outgoing_amount="",
        outgoing_asset="",
        blockpit_fee="",
        blockpit_fee_asset="",
        tx_id=BITGET_DEPOSIT_ONCHAIN_TX,
        source_ref="bitget-tax-api:1292099980770058240",
        address=BITGET_HNT_DEPOSIT_ADDRESS,
        network="SOL",
    ),
    SourceChainRow(
        time="2025-04-04T17:12:55.009000+00:00",
        operation="sell",
        amount="7.85",
        quote_amount="21.98",
        fee_asset="USDT",
        fee="0.02198",
        api_ids=("1292100873615745024",),
        balance_after="8.31462275",
        blockpit_date="04.04.2025 17:12:55",
        incoming_amount="21.98",
        incoming_asset="USDT",
        outgoing_amount="7.85",
        outgoing_asset="HNT",
        blockpit_fee="0.02198",
        blockpit_fee_asset="USDT",
        tx_id="bitget-tax-api-merged:1292100873611550720-1292100873615745024",
        source_ref="bitget-tax-api:1292100873615745024",
    ),
    SourceChainRow(
        time="2025-04-04T17:12:55.009000+00:00",
        operation="sell",
        amount="2.229",
        quote_amount="6.238971",
        fee_asset="USDT",
        fee="0.006238971",
        api_ids=("1292100873615745027",),
        balance_after="6.08562275",
        blockpit_date="04.04.2025 17:12:55",
        incoming_amount="6.238971",
        incoming_asset="USDT",
        outgoing_amount="2.229",
        outgoing_asset="HNT",
        blockpit_fee="0.006238971",
        blockpit_fee_asset="USDT",
        tx_id="bitget-tax-api-merged:1292100873615745026-1292100873615745027",
        source_ref="bitget-tax-api:1292100873615745027",
    ),
    SourceChainRow(
        time="2025-04-04T17:12:55.009000+00:00",
        operation="sell",
        amount="6.085",
        quote_amount="17.02583",
        fee_asset="USDT",
        fee="0.01702583",
        api_ids=("1292100873615745030",),
        balance_after="0.00062275",
        blockpit_date="04.04.2025 17:12:55",
        incoming_amount="17.02583",
        incoming_asset="USDT",
        outgoing_amount="6.085",
        outgoing_asset="HNT",
        blockpit_fee="0.01702583",
        blockpit_fee_asset="USDT",
        tx_id="bitget-tax-api-merged:1292100873615745029-1292100873615745030",
        source_ref="bitget-tax-api:1292100873615745030",
    ),
)


def _raw_events(connection: sqlite3.Connection, source_name: str) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        select raw.payload_json
        from raw_events raw
        join source_files source on source.source_file_id = raw.source_file_id
        where source.source_name = ?
        order by raw.row_index
        """,
        (source_name,),
    ).fetchall()
    return [json.loads(str(row[0])) for row in rows]


def _api_records(connection: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    rows = connection.execute(
        """
        select raw.payload_json
        from raw_events raw
        join source_files source on source.source_file_id = raw.source_file_id
        where source.source_name like 'bitget_api_tax_%'
          and json_extract(raw.payload_json, '$.asset') = 'HNT'
        """
    ).fetchall()
    records: dict[str, dict[str, Any]] = {}
    for row in rows:
        payload = json.loads(str(row[0]))
        raw_record = payload.get("raw_row")
        if isinstance(raw_record, dict) and raw_record.get("id"):
            records[str(raw_record["id"])] = raw_record
    return records


def _assert_v1_evidence(v1_db: Path) -> dict[str, str]:
    connection = sqlite3.connect(f"file:{v1_db}?mode=ro", uri=True)
    try:
        blockpit_rows = _raw_events(connection, BLOCKPIT_SOURCE)
        api_records = _api_records(connection)
    finally:
        connection.close()
    unique_blockpit_rows = {
        json.dumps(payload["raw_row"], sort_keys=True): payload["raw_row"]
        for payload in blockpit_rows
        if isinstance(payload.get("raw_row"), dict)
    }.values()
    evidence_hashes: dict[str, str] = {}
    for spec in SOURCE_CHAIN:
        missing_api_ids = [api_id for api_id in spec.api_ids if api_id not in api_records]
        if missing_api_ids:
            raise RuntimeError(f"missing_bitget_tax_api_ids:{','.join(missing_api_ids)}")
        final_api_record = api_records[spec.api_ids[-1]]
        if (
            str(final_api_record.get("coin") or "").upper() != "HNT"
            or Decimal(str(final_api_record.get("balance") or "0"))
            != Decimal(spec.balance_after)
        ):
            raise RuntimeError(f"bitget_balance_mismatch:{spec.source_ref}")
        matches = [
            row
            for row in unique_blockpit_rows
            if str(row.get("Integration Name") or "") == "Bitget"
            and str(row.get("Date (UTC)") or "") == spec.blockpit_date
            and str(row.get("Incoming Amount") or "") == spec.incoming_amount
            and str(row.get("Incoming Asset") or "") == spec.incoming_asset
            and str(row.get("Outgoing Amount") or "") == spec.outgoing_amount
            and str(row.get("Outgoing Asset") or "") == spec.outgoing_asset
            and str(row.get("Fee Amount (optional)") or "") == spec.blockpit_fee
            and str(row.get("Fee Asset (optional)") or "") == spec.blockpit_fee_asset
        ]
        if len(matches) != 1:
            raise RuntimeError(
                f"blockpit_evidence_match_count:{spec.source_ref}:{len(matches)}"
            )
        evidence_hashes[spec.source_ref] = hashlib.sha256(
            json.dumps(matches[0], sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
    return evidence_hashes


def prepared_rows(v1_db: Path) -> list[dict[str, object]]:
    evidence_hashes = _assert_v1_evidence(v1_db)
    rows: list[dict[str, object]] = []
    for spec in SOURCE_CHAIN:
        row: dict[str, object] = {
            "record_type": "bitget_hnt_2025_fifo_source_chain",
            "time": spec.time,
            "type": spec.operation,
            "asset": "HNT",
            "amount": spec.amount,
            "account": "bitget",
            "fee_asset": spec.fee_asset or "",
            "fee": spec.fee,
            "withdrawal fee": spec.fee if spec.operation == "withdrawal" else "",
            "quote_asset": "USDT" if spec.quote_amount is not None else "",
            "quote_quantity": spec.quote_amount or "",
            "tx_id": spec.tx_id,
            "source_ref": spec.source_ref,
            "bitget_tax_api_ids": ",".join(spec.api_ids),
            "bitget_balance_after": spec.balance_after,
            "address": spec.address or "",
            "network": spec.network or "",
            "evidence_source": "bitget_tax_api+blockpit+alchemy_onchain",
            "blockpit_row_sha256": evidence_hashes[spec.source_ref],
        }
        rows.append(row)
    return rows


def _semantic_sha256(rows: list[dict[str, object]]) -> str:
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
            "Validates the 2025 Bitget HNT FIFO source chain against read-only "
            "V1 evidence and imports it through V2 services only when --execute is set."
        )
    )
    parser.add_argument("--v1-db", type=Path, default=DEFAULT_V1_DB)
    parser.add_argument("--db", type=Path, default=DEFAULT_V2_DB)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--artifact", type=Path)
    args = parser.parse_args()

    rows = prepared_rows(args.v1_db)
    semantic_sha256 = _semantic_sha256(rows)
    file_hash = f"sha256:{semantic_sha256}"
    store = DuckDbStore(args.db)
    duplicate = store.get_import_batch_by_file_hash(SOURCE, file_hash)
    result: dict[str, object] = {
        "status": "duplicate" if duplicate else "preview",
        "execute": args.execute,
        "source": SOURCE,
        "filename": FILENAME,
        "rows_count": len(rows),
        "semantic_sha256": semantic_sha256,
        "duplicate_batch_id": duplicate.batch_id if duplicate else None,
        "fifo_equation": {
            "opening_dust_hnt": "0.000991",
            "net_buys_hnt": "1000.720278",
            "sales_hnt": "140.283",
            "pre_withdrawal_balance_hnt": "860.438269",
            "withdrawal_hnt": "859.9208492",
            "withdrawal_fee_hnt": "0.5174198",
            "post_withdrawal_balance_hnt": "0",
        },
        "rows": rows,
        "methodology": (
            "V1 wird nur als unveraenderter historischer Read-only-Belegfundus "
            "gelesen. Import erfolgt ausschliesslich ueber CsvRawImporter und "
            "PipelineService in V2. Bitget-Tax-API-IDs, Blockpit-Mengen/Quotes, "
            "Kontosalden und die zwei Alchemy-verifizierten Solana-TXIDs werden "
            "vor dem Import exakt validiert."
        ),
    }
    if args.execute and duplicate is None:
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
