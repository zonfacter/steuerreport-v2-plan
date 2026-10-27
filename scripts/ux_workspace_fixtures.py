"""Disposable deterministic browser responses. Never forwards a request."""
from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from io import StringIO
import json
from urllib.parse import parse_qs, urlparse


STAMP = "2026-10-26T10:00:00Z"
SOURCE = "s_" + "a" * 20
OTHER = "s_" + "b" * 20


class WorkspaceFixture:
    def __init__(self):
        self.fresh = False
        self.fail: set[str] = set()
        self.hold: set[str] = set()
        self.pending = []
        self.calls = []
        self.zero = False
        self.sync_failed = False
        self.events = [dict(event_id=f"evt-{index:03}", event_time=(datetime(2025, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)).isoformat(),
                            source="synthetic", event_type="trade" if index % 2 else "reward", asset="BTC" if index % 2 else "SOL",
                            quantity="0.123456789012345678", quote_asset="EUR", quote_quantity="-10.000000000000000000",
                            fee_asset="EUR", fee_quantity="0.010000000000000000", tx_id=f"synthetic-tx-{index:03}",
                            source_ref=None, raw_object_id=f"raw-{index:03}", account="synthetic-account", wallet=None) for index in range(45)]

    @staticmethod
    def send(route, data, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps({"status": "ok" if status == 200 else "error", "data": data, "errors": [], "warnings": []}))

    def sources(self):
        if self.fresh:
            return []
        source = dict(ref=SOURCE, label="Demo-Börse", source_type="exchange", connector_id="binance", legacy_source_id="binance",
                      connection_status="configured", ownership_status="not_assessed", freshness="stale", last_success_at="2026-10-24T08:00:00Z",
                      last_attempt={"status": "fetch_failed", "attempted_at": STAMP}, value_eur="0.000000000000000000" if self.zero else "1250.00",
                      ledger_value_eur="1200.00", value_basis="stored_live_snapshot", events_count=45, imports_count=1, issues_count=0,
                      reconciliation_status="review", can_sync=True, warning=None,
                      price_issues_count=0, reconciliation_issues_count=0, review_tasks_count=1,
                      blocking_review_tasks_count=1, review_reconciliation_tasks_count=0, ambiguous_review_tasks_count=0)
        other = {**source, "ref": OTHER, "label": "Demo-Dateiquelle", "connector_id": None, "source_type": "import", "can_sync": False,
                 "connection_status": "imported", "freshness": "missing", "last_success_at": None, "last_attempt": None, "value_eur": None, "value_basis": "unavailable", "events_count": 0, "review_tasks_count": 0, "blocking_review_tasks_count": 0}
        return [source, other]

    def review_item(self):
        task = dict(task_id="review-demo", title="Originalbeleg prüfen", priority="high", category="evidence", detail="Der Quellennachweis muss geprüft werden.", source="synthetic", source_group=None, scope="evt-000", asset="SOL", blocks_export=True, tax_year=2025, action_label="Beleg prüfen", action_path=None, evidence_refs=["raw-000"], decision_status=None)
        return dict(task=task, event_ids=["evt-000"], source_ref=SOURCE, candidate_source_refs=[SOURCE], account=None, account_ref=None, context_status="matched", context_label="Demo-Börse · Asset SOL", context_note="Über die gespeicherte Ereignis-ID zugeordnet.")

    def status(self, year):
        return dict(generated_at=STAMP, year=year, events_count=0 if self.fresh else 45, year_events_count=0 if self.fresh else 45,
                    imports_count=0 if self.fresh else 1, balance_entries=0 if self.fresh else 90, owned_sources_count=len(self.sources()),
                    last_import_at=None if self.fresh else STAMP, calculation_at=None if self.fresh else STAMP, calculation_stale=False,
                    review={"allow_export": True, "issues_open": 0, "blocking_issues_open": 0, "issues": []},
                    readiness={"can_file_without_review": False, "ready_years": [], "checks": [], "methodology": "Synthetic"},
                    preview_available=not self.fresh, final_available=False,
                    summary="Noch keine berechnete Jahresvorschau" if self.fresh else "Vorschau verfügbar — finale Abgabe nicht freigegeben",
                    next_section="sources" if self.fresh else "tax", next_action="Erste Quelle hinzufügen" if self.fresh else "Steuerjahr und Freigaben prüfen",
                    dimensions={"data": "Einrichtung erforderlich" if self.fresh else "Historie vorhanden — Abdeckung prüfen", "calculation": "Noch nicht berechnet" if self.fresh else "Berechnungsstand vorhanden",
                                "review": "Noch nicht prüfbar" if self.fresh else "Keine Gate-Hinweise im geprüften Datenstand", "year": "Bestätigung erforderlich", "export": "Noch nicht verfügbar" if self.fresh else "Nur Vorschau"})

    def activity(self, query):
        events = [] if self.fresh else self.events
        for field, key in (("asset", "asset"), ("event_type", "event_type")):
            if query.get(field):
                events = [row for row in events if row[key] == query[field]]
        if query.get("source_ref") == OTHER:
            events = []
        if query.get("year"):
            events = [row for row in events if int(row["event_time"][:4]) == query["year"]]
        if query.get("search"):
            events = [row for row in events if query["search"].lower() in json.dumps(row).lower()]
        if query.get("start"):
            events = [row for row in events if row["event_time"][:10] >= query["start"]]
        if query.get("end"):
            events = [row for row in events if row["event_time"][:10] <= query["end"]]
        if query.get("hint") == "present":
            events = [row for row in events if row["event_id"] == "evt-000"]
        if query.get("hint") == "none":
            events = [row for row in events if row["event_id"] != "evt-000"]
        events = sorted(events, key=lambda row: row["event_time"], reverse=query.get("sort") != "oldest")
        ledger = query.get("mode") == "ledger"
        rows = [dict(row_id=event["event_id"] + (f"-ledger-{part}" if ledger else ""), event=event, has_hint=event["event_id"] == "evt-000", corrected=False,
                     ledger_asset="EUR" if part else event["asset"], ledger_quantity="-10" if part else event["quantity"], ledger_account="synthetic-account")
                for event in events for part in range(2 if ledger else 1)]
        size = query.get("page_size", 25)
        pages = max(1, (len(rows) + size - 1) // size)
        page = min(query.get("page", 1), pages)
        return dict(rows=rows[(page-1)*size:page*size], total=len(rows), page=page, pages=pages, page_size=size, mode=query.get("mode", "events"), generated_at=STAMP)

    def handle(self, route):
        path = urlparse(route.request.url).path
        body = route.request.post_data_json if route.request.method == "POST" and route.request.post_data else {}
        self.calls.append((route.request.method, path, body))
        if path in self.hold:
            self.pending.append(route)
            return True
        if path in self.fail:
            self.send(route, {}, 503)
            return True
        if path == "/api/v1/workspace/environment":
            data = {"synthetic_preview": True, "read_only": True}
        elif path == "/api/v1/admin/connections":
            data = {"connections": [], "legacy_connections": [], "vault_ready": False, "automatic_migration": False}
        elif path == "/api/v1/admin/connections/jobs":
            data = {"jobs": [], "max_active": 4, "max_retained": 100}
        elif path == "/api/v1/admin/request-limits":
            data = {"schema_version": 1, "revision": 0, "scheduler_enabled": False, "group_profiles": {}, "provider_groups": {}, "endpoint_costs": {}, "provider_ceilings": {}, "default_profile": {
                "origin": "local_conservative", "manufacturer_limit_verified": False, "cost_unit": "local_units", "requests_per_second": 1, "requests_per_minute": 30, "burst": 1, "max_concurrency": 1, "weighted_cost_per_minute": None,
                "timeout_seconds": 30, "max_retries": 2, "backoff_base_seconds": 1, "backoff_max_seconds": 30, "jitter_ratio": 0.2, "job_deadline_seconds": 300}}
        elif path == "/api/v1/admin/request-limits/presets":
            data = {"presets": [], "current_revision": 0}
        elif path == "/api/v1/admin/request-limits/status":
            data = {"schema_version": 1, "config_revision": 0, "observed_at": 1793000000, "clock_rollback": False, "groups": [], "provider_observations": {}, "manufacturer_telemetry_available": False, "coordination_scope": "host_local_flock_shared_volume", "concurrency_recovery": "explicit_release_only"}
        elif path == "/api/v1/admin/request-limits/endpoints":
            data = {"fallback": "default", "unit": "local_units", "http": [{"id": "account", "path": "/api/v3/account"}], "rpc": [{"id": "rpc_gettransaction", "method": "getTransaction"}]}
        elif path == "/api/v1/admin/provider-references":
            data = {"checked_at": "2026-10-26", "automatic_plan_detection": False, "providers": []}
        elif path == "/api/v1/workspace/sources":
            data = dict(generated_at=STAMP, sources=self.sources(), events_count=0 if self.fresh else 45, methodology="Synthetic")
        elif path.startswith("/api/v1/workspace/sources/") and path.endswith("/sync"):
            data = {"connector_results": [{"status": "fetch_failed" if self.sync_failed else "refreshed", "message": "Synthetic"}]}
        elif path.startswith("/api/v1/workspace/sources/"):
            source = next((row for row in self.sources() if row["ref"] == path.rsplit("/", 1)[1]), None)
            if not source:
                self.send(route, {}, 404)
                return True
            data = dict(source=source, review_tasks=[self.review_item()] if source["ref"] == SOURCE else [], evidence={"ownership": "not_assessed", "source": "synthetic"}, valuation={"assets": [{"asset": "SOL", "quantity": "10", "value_eur": source["value_eur"], "price_status": "available"}], "full_accounts": ["synthetic-account"], "reconciliation": {}, "evidence_refs": ["synthetic.csv"], "methodology": "Synthetic"})
        elif path == "/api/v1/workspace/status":
            data = self.status(int(parse_qs(urlparse(route.request.url).query).get("year", [2025])[0]))
        elif path == "/api/v1/activity/query":
            data = self.activity(body)
        elif path == "/api/v1/activity/assets":
            data = {"assets": ["BTC", "EUR", "SOL"], "truncated": False}
        elif path.startswith("/api/v1/activity/events/"):
            event = next(row for row in self.events if row["event_id"] == path.rsplit("/", 1)[1])
            data = dict(event=event, raw={"row_number": 2, "filename": "synthetic.csv", "file_hash": "a"*64, "batch_id": "synthetic-batch", "payload_json": '{"synthetic": true}'}, ledger=[], tax_lines=[], decisions=[], corrections=[], ledger_count=2, tax_lines_count=0, details_limit=200, transfer_relationship="Keine automatische Transferzuordnung.")
        elif path == "/api/v1/activity/export.csv":
            query = {"mode": body.get("query", {}).get("mode", "events")} if body["scope"] == "all" else body["query"]
            rows = self.activity({**query, "page": 1, "page_size": 25000})["rows"]
            if body["scope"] == "selected":
                rows = [row for row in rows if row["row_id"] in body["selected_ids"]]
            output = StringIO()
            writer = csv.writer(output)
            writer.writerow(["event_id", "asset", "quantity"])
            writer.writerows((row["event"]["event_id"], row["event"]["asset"], row["event"]["quantity"]) for row in rows)
            route.fulfill(content_type="text/csv", body=output.getvalue(), headers={"X-Export-Row-Count": str(len(rows))})
            return True
        elif path == "/api/v1/workspace/review/query":
            items = [] if self.fresh or body.get("search") or body.get("category") not in (None, self.review_item()["task"]["category"]) or body.get("source_ref") == OTHER else [self.review_item()]
            items = [item for item in items if not body.get("task_id") or item["task"]["task_id"] == body["task_id"]]
            data = dict(items=items, total=len(items), unfiltered_total=0 if self.fresh else 1, blocking_total=0 if self.fresh else 1, page=1, pages=1, page_size=body.get("page_size", 25), generated_at=STAMP)
        elif path == "/api/v1/portfolio/snapshot":
            data = dict(total_value_eur="0" if self.zero or self.fresh else "1200", positions=[] if self.fresh else [{}], asset_summary=[] if self.fresh else [{"asset": "SOL", "quantity": "10", "value_eur": "0" if self.zero else "1200", "price_status": "available", "priced_at_latest": STAMP, "price_sources": ["synthetic"]}], missing_price_assets=[])
        elif path == "/api/v1/cockpit/summary":
            data = dict(generated_at=STAMP, portfolio_performance={"live_value_eur": None, "calculated_value_eur": "0" if self.zero else "1200"}, price_coverage={"total_assets": 0 if self.fresh else 1, "priced_assets": 0 if self.fresh else 1}, live_reconciliation={"latest_live_snapshot_at": None}, tasks=[], top_assets=[], top_sources=[], open_tasks=0, export_allowed=False)
        elif path == "/api/v1/import/profiles":
            data = [{"source": source, "label": source.title()} for source in ["manual-csv", "binance", "bitget", "helium", "solana_rpc"]]
        elif path == "/api/v1/import/batches":
            data = []
        elif path == "/api/v1/connectors/catalog":
            data = dict(security={"connector_writes_enabled": False, "auth_mode": "local", "vault": {"status": "encrypted", "configured": True}, "blockers": []}, connections=[], connectors=[dict(connector_id=name, label=name.title(), category="exchange", availability="server_admin_only", limitation=None, connection_status="not_configured", supported_auth=[], scopes=[], capabilities=[], required_fields=[], mobile_platforms=[], safety_notes=[]) for name in ["binance", "bitget", "coinbase", "pionex"]])
        elif path == "/api/v1/sources/registry/runs/latest":
            data = {"entries": [], "findings": [], "strict_ready": False, "status": "not_run"}
        elif path == "/api/v1/sources/overview":
            data = {"sources": [], "total_value_eur": "0", "methodology": "Synthetic"}
        elif path == "/api/v1/pipeline/rebuild":
            data = {"allow_export": False}
        elif path.startswith("/api/v1/tax-years/") and path.count("/") == 4:
            data = {"year": int(path.rsplit("/", 1)[1]), "state": "review_required", "realized_gain_loss_eur": "10.12", "tax_free_gain_loss_eur": "0", "rewards_income_eur": "2.34", "derivative_pnl_eur": "0", "taxable_disposal_proceeds_eur": "100", "acquisition_cost_eur": "89.88", "tax_lines_count": 2, "issues": [], "methodology": "Synthetic"}
        else:
            return False
        self.send(route, data)
        return True
