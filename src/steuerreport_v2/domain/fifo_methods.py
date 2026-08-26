from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from steuerreport_v2.db.duckdb_store import DuckDbStore


GLOBAL_ASSET_FIFO_SCOPE = "global_asset_with_wallet_fifo_evidence_overlay_v1"
WALLET_DEPOT_FIFO_SCOPE = "wallet_depot_fifo_v1"
SUPPORTED_FIFO_SCOPES = {
    GLOBAL_ASSET_FIFO_SCOPE,
    WALLET_DEPOT_FIFO_SCOPE,
}


def active_fifo_scope(store: DuckDbStore) -> str:
    with store.connect() as con:
        row = con.execute(
            """
            select fifo_method
            from tax_run_summaries
            order by created_at desc
            limit 1
            """
        ).fetchone()
    value = str(row[0] or "") if row is not None else ""
    return value if value in SUPPORTED_FIFO_SCOPES else GLOBAL_ASSET_FIFO_SCOPE
