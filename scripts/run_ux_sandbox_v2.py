"""Start an isolated, synthetic, read-only UX preview; never use an existing database."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import socket


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True, help="New disposable directory, outside the repository.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--allowed-host", action="append", default=[], help="Explicit additional HTTP Host for LAN testing; repeatable.")
    parser.add_argument("--port", type=int, default=18014)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    state = args.directory.resolve()
    if state.exists():
        parser.error("Use a new directory; existing data will never be overwritten.")
    state.mkdir(parents=True, mode=0o700)
    for key in list(os.environ):
        if key.startswith("STEUERREPORT_"):
            del os.environ[key]
    os.environ.update(STEUERREPORT_V2_ROOT=str(root), STEUERREPORT_STATE_DIR=str(state),
                      STEUERREPORT_V2_DB=str(state / "synthetic.duckdb"), STEUERREPORT_PRIVATE_PROFILE="",
                      STEUERREPORT_PRIVATE_CONFIG_DIR=str(state / "configs"), STEUERREPORT_USERTRANSFER_ROOT=str(state / "imports"))
    allowed_hosts = ["localhost", "127.0.0.1", "[::1]", *args.allowed_host]
    if args.host not in {"0.0.0.0", "::"}:
        allowed_hosts.append(args.host)
    os.environ["STEUERREPORT_ALLOWED_HOSTS"] = ",".join(allowed_hosts)
    from steuerreport_v2.contracts.events import CanonicalEventCreate
    from steuerreport_v2.contracts.imports import ImportBatchCreate, RawObjectCreate
    from steuerreport_v2.contracts.prices import PricePointCreate
    from steuerreport_v2.db.duckdb_store import DuckDbStore
    from steuerreport_v2.domain.tax import TaxService
    from steuerreport_v2.ledger.balance import BalanceLedgerBuilder
    store = DuckDbStore(state / "synthetic.duckdb")
    batch = store.create_import_batch(ImportBatchCreate(source="synthetic", filename="synthetic.csv", file_hash=hashlib.sha256(b"synthetic").hexdigest()))
    for index in range(45):
        at = datetime(2025, 1, 1, 12, tzinfo=timezone.utc) + timedelta(days=index)
        raw = store.add_raw_object(batch.batch_id, RawObjectCreate(row_number=index + 2, payload_json=json.dumps({"synthetic": index})))
        store.add_canonical_event(CanonicalEventCreate(source="synthetic", event_time=at, event_type="trade" if index % 2 else "reward",
                                                      asset="BTC" if index % 2 else "SOL", quantity=Decimal("0.123456789012345678"),
                                                      account="synthetic-account", raw_object_id=raw.raw_object_id,
                                                      quote_asset="EUR" if index % 2 else None, quote_quantity=Decimal("-10") if index % 2 else None,
                                                      tx_id=f"synthetic-tx-{index:03}"))
        store.add_price_point(PricePointCreate(asset="BTC" if index % 2 else "SOL", price_eur=Decimal("100"), priced_at=at, source="synthetic"))
    BalanceLedgerBuilder(store).rebuild()
    TaxService(store).rebuild_fifo()
    # Deny outbound sockets in this preview process, including accidental provider requests.
    def deny_outbound(*args, **kwargs):
        raise OSError("UX sandbox: outbound connections disabled")
    socket.socket.connect = deny_outbound
    socket.socket.connect_ex = deny_outbound
    from fastapi.responses import JSONResponse
    from steuerreport_v2.api.app import create_app
    import uvicorn
    app = create_app(store)
    allowed_posts = {"/api/v1/activity/query", "/api/v1/activity/export.csv", "/api/v1/workspace/review/query"}
    @app.middleware("http")
    async def readonly_preview(request, call_next):
        if request.url.path.startswith("/api/"):
            # Some legacy GETs perform external work or create artefact caches.
            safe = request.method == "GET" and not any(part in request.url.path for part in (".zip", "api-preview", "refresh", "download"))
            if not safe and not (request.method == "POST" and request.url.path in allowed_posts):
                return JSONResponse(status_code=403, content={"detail": "synthetic_preview_read_only"})
        response = await call_next(request)
        response.headers["X-Steuerreport-UX-Sandbox"] = "synthetic-read-only"
        return response
    print(f"Synthetic preview only: http://{args.host}:{args.port}/#dashboard", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
