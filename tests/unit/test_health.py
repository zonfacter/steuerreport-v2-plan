from fastapi.testclient import TestClient

from steuerreport_v2.api.app import build_health_payload, create_app
from steuerreport_v2.contracts.review import ReviewDecisionCreate, ReviewGate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.review import ReviewService


def test_health_payload_reports_duckdb(tmp_path):
    payload = build_health_payload(DuckDbStore(tmp_path / "steuerreport_v2.duckdb"))

    assert payload["database_type"] == "duckdb"
    assert payload["schema_version"] == 1


def test_health_route_is_registered(tmp_path):
    app = create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb"))

    assert any(route.path == "/api/v1/health" for route in app.routes)
    assert any(route.path == "/health" for route in app.routes)


def test_heavy_read_only_routes_are_cached_and_invalidated(tmp_path, monkeypatch):
    calls = {"gate": 0}

    def fake_gate(self):
        calls["gate"] += 1
        return ReviewGate(
            allow_export=True,
            issues_open=0,
            issues_high_open=0,
            issues=[],
        )

    monkeypatch.setattr(ReviewService, "gate", fake_gate)
    app = create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb"))
    client = TestClient(app)

    assert client.get("/api/v1/review/gates").status_code == 200
    assert client.get("/api/v1/review/gates").status_code == 200
    assert calls["gate"] == 1

    decision = ReviewDecisionCreate(
        decision_type="test",
        scope="test:cache",
        title="Cache invalidation",
        rationale="Unit test",
        actor="test",
        source="test",
    )
    assert client.post("/api/v1/review/decisions", json=decision.model_dump(mode="json")).status_code == 200
    assert client.get("/api/v1/review/gates").status_code == 200
    assert calls["gate"] == 2


def test_vertical_slice_routes_are_registered(tmp_path):
    app = create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb"))
    paths = {route.path for route in app.routes}

    assert "/api/v1/import/csv/raw" in paths
    assert "/api/v1/import/csv/preview" in paths
    assert "/api/v1/import/file/raw" in paths
    assert "/api/v1/import/file/preview" in paths
    assert "/api/v1/import/profiles" in paths
    assert "/api/v1/import/coverage" in paths
    assert "/api/v1/import/parser-preflight" in paths
    assert "/api/v1/import/blockpit-solana/preflight" in paths
    assert "/api/v1/import/blockpit-solana/price-probe" in paths
    assert "/api/v1/import/solscan/token-preflight" in paths
    assert "/api/v1/import/solscan/rpc-probe" in paths
    assert "/api/v1/import/solscan/evidence-trace" in paths
    assert "/api/v1/import/wallet-monthly/preflight" in paths
    assert "/api/v1/import/jup-perps/preview" in paths
    assert "/api/v1/import/batches/{batch_id}" in paths
    assert "/api/v1/import/batches/{batch_id}/normalize" in paths
    assert "/api/v1/import/batches/{batch_id}/run" in paths
    assert "/api/v1/import/batches/{batch_id}/trace.json" in paths
    assert "/api/v1/raw/objects" in paths
    assert "/api/v1/events/canonical" in paths
    assert "/api/v1/ledger/balances/rebuild" in paths
    assert "/api/v1/ledger/balances" in paths
    assert "/api/v1/transfers/candidates" in paths
    assert "/api/v1/prices" in paths
    assert "/api/v1/prices/import/csv/preview" in paths
    assert "/api/v1/prices/import/csv" in paths
    assert "/api/v1/prices/import/v1-fx-cache/preview" in paths
    assert "/api/v1/prices/import/v1-fx-cache" in paths
    assert "/api/v1/prices/backfill/external" in paths
    assert "/api/v1/prices/backfill/current-portfolio" in paths
    assert "/api/v1/prices/latest" in paths
    assert "/api/v1/prices/coverage" in paths
    assert "/api/v1/prices/quality" in paths
    assert "/api/v1/prices/quality/group" in paths
    assert "/api/v1/prices/quality/manual-review" in paths
    assert "/api/v1/prices/quality/stablecoin-fx-review" in paths
    assert "/api/v1/prices/quality/stablecoin-fx-replacement-preview" in paths
    assert "/api/v1/prices/quality/stablecoin-fx-replacement-impact" in paths
    assert "/api/v1/prices/quality/stablecoin-fx-tax-impact-latest" in paths
    assert "/api/v1/prices/quality/stablecoin-fx-tax-impact-decisions" in paths
    assert "/api/v1/prices/quality/solscan-signature-review" in paths
    assert "/api/v1/prices/quality/binance-normalizer-review" in paths
    assert "/api/v1/prices/quality/event-quote-evidence-review" in paths
    assert "/api/v1/prices/quality/closure-candidates" in paths
    assert "/api/v1/prices/quality/decisions" in paths
    assert "/api/v1/prices/requirements" in paths
    assert "/api/v1/prices/coverage/decisions" in paths
    assert "/api/v1/prices/{price_id}" in paths
    assert "/api/v1/portfolio/snapshot" in paths
    assert "/api/v1/portfolio/reconciliation" in paths
    assert "/api/v1/portfolio/reconciliation/refresh" in paths
    assert "/api/v1/portfolio/jup-wallet/import-history" in paths
    assert "/api/v1/portfolio/separation-report" in paths
    assert "/api/v1/divorce/equalization-summary" in paths
    assert "/api/v1/divorce/equalization-summary/accounts.csv" in paths
    assert "/api/v1/divorce/equalization-summary/capital-flows.csv" in paths
    assert "/api/v1/divorce/equalization-summary/evidence-package.zip" in paths
    assert "/api/v1/divorce/equalization-summary/live-reconciliation.csv" in paths
    assert "/api/v1/divorce/equalization-summary/valuation-tokens.csv" in paths
    assert "/api/v1/review/gates" in paths
    assert "/api/v1/review/tasks" in paths
    assert "/api/v1/review/decisions" in paths
    assert "/api/v1/review/decision-suggestions" in paths
    assert "/api/v1/review/evidence-traces" in paths
    assert "/api/v1/review/evidence-traces/canonicalize" in paths
    assert "/api/v1/review/decision-suggestions/{suggestion_id}/accept" in paths
    assert "/api/v1/product/readiness" in paths
    assert "/api/v1/parity/v1/references" in paths
    assert "/api/v1/parity/v1/references/{reference_id}" in paths
    assert "/api/v1/parity/v1/import/wiso" in paths
    assert "/api/v1/parity/compare" in paths
    assert "/api/v1/parity/group-detail" in paths
    assert "/api/v1/parity/hnt-wallet-bridge" in paths
    assert "/api/v1/parity/release-readiness" in paths
    assert "/api/v1/parity/decisions" in paths
    assert "/api/v1/flows/rebuild" in paths
    assert "/api/v1/flows/net" in paths
    assert "/api/v1/export/pdf" in paths
    assert "/api/v1/export/packages" in paths
    assert "/api/v1/export/packages/{package_id}" in paths
    assert "/api/v1/export/packages/{package_id}/download.pdf" in paths
    assert "/api/v1/export/readiness" in paths
    assert "/api/v1/export/evidence-manifest.json" in paths
    assert "/api/v1/export/evidence-package-index.json" in paths
    assert "/api/v1/export/evidence-package.zip" in paths
    assert "/api/v1/export/audit" in paths
    assert "/api/v1/export/elster-prep" in paths
    assert "/api/v1/admin/status" in paths
    assert "/api/v1/admin/settings" in paths
    assert "/api/v1/admin/settings/{key}" in paths
    assert "/api/v1/ai/tasks" in paths
    assert "/api/v1/ai/tasks/{task_id}" in paths
    assert "/api/v1/ai/local-wallet-fifo-provenance-review" in paths
    assert "/api/v1/ai/local-wallet-fifo-provenance-review/artifacts/{artifact}" in paths
    assert "/api/v1/tax/fifo/rebuild" in paths
    assert "/api/v1/tax/lots" in paths
    assert "/api/v1/tax/holding-periods" in paths
    assert "/api/v1/tax/lines" in paths
    assert "/api/v1/tax/unmatched-disposals" in paths
    assert "/api/v1/tax/summary" in paths
    assert "/api/v1/tax-methodology/bmf-action-plan" in paths
    assert "/api/v1/tax-years/{year}/declaration-guide" in paths
    assert "/api/v1/pipeline/rebuild" in paths
    assert "/api/v1/demo/seed" in paths
    assert "/api/v1/export/audit.json" in paths
    assert "/api/v1/export/review-decisions.csv" in paths
    assert "/api/v1/export/token-risk-documentation.csv" in paths
    assert "/api/v1/export/price-gaps.csv" in paths
    assert "/api/v1/export/price-requirements.csv" in paths
    assert "/api/v1/export/parity-diagnostics.csv" in paths
    assert "/api/v1/export/binance-fiat-deposits.csv" in paths
    assert "/api/v1/export/tax-lines.csv" in paths
