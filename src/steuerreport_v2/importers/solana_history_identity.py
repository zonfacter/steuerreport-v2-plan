from __future__ import annotations

import json
import os
from collections import defaultdict
from contextlib import contextmanager

from steuerreport_v2.db.duckdb_store import DuckDbStore


class SolanaHistoryConflict(ValueError):
    pass


@contextmanager
def exclusive_history_import(store: DuckDbStore):
    # DuckDB's per-instance lock alone does not serialize separate store handles.
    # Reserve the complete read/deduplicate/write/rebuild sequence across workers.
    try:
        import fcntl
    except ImportError as exc:
        raise RuntimeError("Sichere Historien-Importsperre ist auf diesem System nicht verfuegbar.") from exc
    path = store.path.resolve()
    descriptor = os.open(
        str(path) + ".solana-history.lock",
        os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise SolanaHistoryConflict(
                "Ein Solana-Historienimport laeuft bereits. Nach Abschluss erneut versuchen."
            ) from exc
        with store.exclusive_access():
            yield
    finally:
        os.close(descriptor)


def new_transaction_rows(
    store: DuckDbStore,
    wallet: str,
    rows: list[dict[str, object]],
) -> tuple[list[dict[str, object]], int, str | None]:
    """Call under exclusive_history_import, through normalization."""
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        signature = str(row.get("tx_id") or "").strip()
        if not signature or str(row.get("wallet_address") or "") != wallet:
            raise SolanaHistoryConflict("Historienzeile ohne eindeutige Wallet-/Signaturzuordnung; kein Import.")
        groups[signature].append(row)
    if not groups:
        return [], 0, None

    with store.connect() as con:
        existing = con.execute(
            """
            select distinct r.batch_id, r.payload_json, b.status
            from raw_objects r
            join raw_import_batches b on b.batch_id = r.batch_id
            left join canonical_events e on e.raw_object_id = r.raw_object_id
            where b.source = 'solana_rpc'
              and coalesce(json_extract_string(r.payload_json, '$.tx_id'), e.tx_id)
                  in (select unnest(?))
              and (json_extract_string(r.payload_json, '$.wallet_address') = ?
                   or e.account = ? or e.wallet = ?)
            order by r.batch_id, r.payload_json
            """,
            [list(groups), wallet, wallet, wallet],
        ).fetchall()
    prior: dict[str, dict[str, list[dict[str, object]]]] = defaultdict(lambda: defaultdict(list))
    for batch_id, payload_json, status in existing:
        if status != "normalized":
            raise SolanaHistoryConflict(
                "Vorheriger Solana-Import ist nicht als vollstaendig berechnet bestaetigt. "
                "Manuelle Pruefung erforderlich; kein erneuter Import."
            )
        payload = json.loads(payload_json)
        signature = str(payload.get("tx_id") or "")
        # A legacy source without explicit row identity needs manual review.
        if signature not in groups:
            raise SolanaHistoryConflict("Bestehende Solana-Belege sind nicht eindeutig zuordenbar; kein Import.")
        prior[signature][batch_id].append(payload)

    def fingerprint(items: list[dict[str, object]]) -> list[str]:
        # CSV persistence stringifies scalar fields; mirror that representation.
        return sorted(json.dumps(
            {str(key): None if value is None else str(value) for key, value in row.items()},
            ensure_ascii=False, sort_keys=True,
        ) for row in items)

    accepted: list[dict[str, object]] = []
    duplicates = 0
    prior_batch: str | None = None
    for signature, items in groups.items():
        batches = prior.get(signature)
        if not batches:
            accepted.extend(items)
            continue
        candidate = fingerprint(items)
        # Never silently replace a prior mapper interpretation or a partial leg set.
        if any(fingerprint(previous) != candidate for previous in batches.values()):
            raise SolanaHistoryConflict(
                "Solana-Transaktion bereits mit abweichenden Belegen/Importregeln vorhanden. "
                "Manuelle Pruefung erforderlich; keine Daten wurden ersetzt."
            )
        duplicates += 1
        prior_batch = prior_batch or next(iter(batches))
    return accepted, duplicates, prior_batch
