from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import hashlib
import json

from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.fairspot_staking import (
    FairspotStakingReconciliationService,
)
from steuerreport_v2.domain.tax import TaxService


def test_fairspot_staking_reconciliation_binds_principal_reward_and_fifo(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    main_wallet = "main-wallet"
    staking_wallet = "staking-wallet"
    file_hash = "sha256:unit-main"
    batch = store.create_import_batch(
        ImportBatchCreate(
            source="helium",
            filename="helium-main.csv",
            file_hash=file_hash,
        )
    )
    outbound_raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=1,
            payload_json=json.dumps(
                {"payer": main_wallet, "payee": staking_wallet, "type": "payment_v2"}
            ),
        ),
    )
    return_raw = store.add_raw_object(
        batch.batch_id,
        RawObjectCreate(
            row_number=2,
            payload_json=json.dumps(
                {"payer": staking_wallet, "payee": main_wallet, "type": "payment_v2"}
            ),
        ),
    )
    outbound, principal, reward = store.add_canonical_events(
        [
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2022, 1, 1, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("-8"),
                tx_id="outbound-tx",
                account=main_wallet,
                raw_object_id=outbound_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2022, 12, 31, tzinfo=timezone.utc),
                event_type="transfer",
                asset="HNT",
                quantity=Decimal("8"),
                tx_id="return-tx",
                account=main_wallet,
                raw_object_id=return_raw.raw_object_id,
            ),
            CanonicalEventCreate(
                source="helium",
                event_time=datetime(2022, 12, 31, tzinfo=timezone.utc),
                event_type="reward",
                asset="HNT",
                quantity=Decimal("2"),
                tx_id="return-tx",
                account=main_wallet,
                raw_object_id=return_raw.raw_object_id,
            ),
        ]
    )
    store.add_price_point(
        PricePointCreate(
            asset="HNT",
            price_eur=Decimal("1.5"),
            priced_at=datetime(2022, 12, 31, tzinfo=timezone.utc),
            source="unit",
        )
    )
    TaxService(store).rebuild_fifo()
    independent_path = tmp_path / "fairspot.csv"
    independent_path.write_text(
        "block,date,type,transaction_hash,hnt_amount,hnt_fee,mobile_amount,usd_oracle_price,usd_amount,usd_fee,payer,payee\n"
        f"1,2022-01-01,payment_v2,outbound-tx,8,0,0,1,8,0,{main_wallet},{staking_wallet}\n"
        f"2,2022-12-31,payment_v2,return-tx,10,0,0,1,10,0,{staking_wallet},{main_wallet}\n",
        encoding="utf-8",
    )
    config_path = tmp_path / "fairspot.json"
    config_path.write_text(
        json.dumps(
            {
                "review_status": "approved_evidence_overlay",
                "main_wallet": main_wallet,
                "staking_wallet": staking_wallet,
                "primary_source": {"file_hash": file_hash},
                "independent_source": {
                    "sha256": hashlib.sha256(independent_path.read_bytes()).hexdigest()
                },
                "principal_outbound_quantity": "8",
                "principal_return_quantity": "8",
                "total_received_quantity": "10",
                "reward_quantity": "2",
                "principal_outbound_tx_ids": ["outbound-tx"],
                "principal_return_tx_ids": ["return-tx"],
                "evidence_refs": ["unit"],
            }
        ),
        encoding="utf-8",
    )
    trace_path = tmp_path / "wallet_fifo_transfer_traces.csv.gz"
    fieldnames = [
        "tx_id",
        "asset",
        "event_time",
        "source_pool_id",
        "target_pool_id",
        "quantity",
        "fee_quantity",
        "lots_moved",
        "carried_cost_basis_eur",
        "status",
        "source_event_id",
        "target_event_id",
    ]
    with gzip.open(trace_path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(
            {
                "tx_id": "outbound-tx",
                "asset": "HNT",
                "event_time": "2022-01-01T00:00:00Z",
                "source_pool_id": f"helium:{main_wallet}",
                "target_pool_id": f"helium_counterparty:{staking_wallet}",
                "quantity": "8",
                "fee_quantity": "",
                "lots_moved": "1",
                "carried_cost_basis_eur": "8",
                "status": "known_staking_counterparty_outbound",
                "source_event_id": outbound.event_id,
                "target_event_id": "synthetic-outbound",
            }
        )
        writer.writerow(
            {
                "tx_id": "return-tx",
                "asset": "HNT",
                "event_time": "2022-12-31T00:00:00Z",
                "source_pool_id": f"helium_counterparty:{staking_wallet}",
                "target_pool_id": f"helium:{main_wallet}",
                "quantity": "8",
                "fee_quantity": "",
                "lots_moved": "1",
                "carried_cost_basis_eur": "8",
                "status": "known_staking_counterparty_return",
                "source_event_id": "synthetic-return",
                "target_event_id": principal.event_id,
            }
        )
    latest_run_path = tmp_path / "latest_wallet_fifo_run.json"
    latest_run_path.write_text(
        json.dumps(
            {
                "run_id": "unit-wallet-run",
                "evidence_files": [
                    {
                        "kind": "wallet_fifo_transfer_traces",
                        "path": str(trace_path),
                        "sha256": hashlib.sha256(trace_path.read_bytes()).hexdigest(),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    report = FairspotStakingReconciliationService(
        store,
        config_path=config_path,
        independent_source_path=independent_path,
        latest_wallet_fifo_path=latest_run_path,
    ).report()

    assert all(report.decision_layer.model_dump().values()), (
        report.decision_layer.model_dump()
    )
    assert report.status == "ready"
    assert report.strict_ready is True
    assert report.reward_event_id == reward.event_id
    assert report.reward_quantity == Decimal("2")
    assert report.reward_income_eur == Decimal("3")
    assert len(report.reward_lot_ids) == 1
