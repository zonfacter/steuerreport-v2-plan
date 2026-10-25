from datetime import datetime, timezone
from decimal import Decimal
import json

import pytest
from fastapi.testclient import TestClient

from steuerreport_v2.api.app import create_app
from steuerreport_v2.contracts.admin import AdminSettingWrite, CexCredentialWrite
from steuerreport_v2.contracts.ai import AiTaskCreate
from steuerreport_v2.contracts.events import CanonicalEventCreate
from steuerreport_v2.contracts.parity import V1ReferenceMetricCreate
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.contracts.sources import (
    SourceConnectorDiagnostic,
    SourceConnectorDiagnosticsReport,
)
from steuerreport_v2.contracts.review import ReviewDecisionCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.admin import AdminService
from steuerreport_v2.domain.ai import AiService
from steuerreport_v2.domain.audit import AuditService
from steuerreport_v2.domain.sources import SourceService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


def _seed_clean_store(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    batch = CsvRawImporter(store).import_text(
        source="pionex",
        filename="pionex.csv",
        content="time,coin,change,type\n2021-04-28T10:00:00Z,USDT,10,deposit\n",
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="USDT",
            price_eur=Decimal("0.90"),
            priced_at=datetime(2021, 4, 28, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    return store


def test_admin_settings_validate_json_and_report_status(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    service = AdminService(store)

    setting = service.upsert_setting(
        AdminSettingWrite(key="ai.external.enabled", value_json="true")
    )
    status = service.status()

    assert setting.key == "ai.external.enabled"
    assert status.external_ai_enabled is True
    assert status.local_ai_enabled is True
    assert status.settings_count == 1


def test_admin_settings_reject_invalid_json(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    with pytest.raises(ValueError):
        AdminService(store).upsert_setting(
            AdminSettingWrite(key="broken", value_json="{not-json")
        )


def test_admin_settings_endpoint_writes_and_lists_setting(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))

    write_response = client.patch(
        "/api/v1/admin/settings",
        json={"key": "ai.external.enabled", "value_json": "true"},
    )
    list_response = client.get("/api/v1/admin/settings")
    status_response = client.get("/api/v1/admin/status")

    assert write_response.status_code == 200
    assert write_response.json()["data"]["key"] == "ai.external.enabled"
    assert list_response.json()["data"][0]["value_json"] == "true"
    assert status_response.json()["data"]["external_ai_enabled"] is True


def test_admin_settings_endpoint_rejects_invalid_json(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))

    response = client.patch(
        "/api/v1/admin/settings",
        json={"key": "broken", "value_json": "{not-json"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["errors"][0]["code"] == "invalid_setting_json"


def test_admin_settings_endpoint_deletes_setting(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    service = AdminService(store)
    service.upsert_setting(AdminSettingWrite(key="ui.test", value_json="true"))
    client = TestClient(create_app(store))

    response = client.delete("/api/v1/admin/settings/ui.test")

    assert response.status_code == 200
    assert response.json()["data"] == {"key": "ui.test", "deleted": True}
    assert service.list_settings() == []


def test_admin_settings_endpoint_warns_for_missing_delete(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))

    response = client.delete("/api/v1/admin/settings/missing")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "warning"


def test_admin_service_saves_cex_credentials_in_v2_secret_store(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    def fake_diagnostics(_self):
        return SourceConnectorDiagnosticsReport(
            generated_at=datetime.now(timezone.utc),
            diagnostics=[
                SourceConnectorDiagnostic(
                    source_id="binance",
                    label="Binance",
                    connector_id="binance",
                    connector_type="cex",
                    status="missing_snapshot",
                    credential_status="configured",
                    credential_keys_present=2,
                    credential_keys_required=2,
                    message="ok",
                    next_action="refresh",
                )
            ],
            methodology="test",
        )

    monkeypatch.setattr(SourceService, "connector_diagnostics", fake_diagnostics)

    result = AdminService(store).save_cex_credentials(
        CexCredentialWrite(
            connector_id="binance",
            api_key="api-key",
            api_secret="api-secret",
        )
    )

    assert result.status == "ok"
    assert result.credential_status == "configured"
    stored = {setting.key: setting.value_json for setting in store.list_admin_settings()}
    assert json.loads(stored["secret.cex.binance.api_key"]) == "api-key"
    assert json.loads(stored["secret.cex.binance.api_secret"]) == "api-secret"
    assert {setting.key: setting.value_json for setting in AdminService(store).list_settings()} == {
        "secret.cex.binance.api_key": '"***"',
        "secret.cex.binance.api_secret": '"***"',
    }


def test_admin_cex_credentials_endpoint_rejects_missing_secret(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/admin/cex-credentials",
        json={"connector_id": "binance", "api_key": "key", "api_secret": ""},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "error"
    assert body["errors"][0]["code"] == "cex_credentials_save_failed"


def test_admin_cex_credentials_endpoint_saves_without_echoing_secret(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    monkeypatch.setattr(
        SourceService,
        "connector_diagnostics",
        lambda _self: SourceConnectorDiagnosticsReport(
            generated_at=datetime.now(timezone.utc),
            diagnostics=[
                SourceConnectorDiagnostic(
                    source_id="bitget",
                    label="Bitget",
                    connector_id="bitget",
                    connector_type="cex",
                    status="missing_snapshot",
                    credential_status="configured",
                    credential_keys_present=3,
                    credential_keys_required=3,
                    message="ok",
                    next_action="refresh",
                )
            ],
            methodology="test",
        ),
    )
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/admin/cex-credentials",
        json={
            "connector_id": "bitget",
            "api_key": "key",
            "api_secret": "dummy-secret-no-echo",
            "passphrase": "dummy-passphrase-no-echo",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["data"]["credential_status"] == "configured"
    assert "dummy-secret-no-echo" not in str(body)
    assert "dummy-passphrase-no-echo" not in str(body)


def test_v1_cex_takeover_report_marks_empty_v1_credentials_not_transferable(tmp_path, monkeypatch):
    monkeypatch.setattr(AdminService, "V1_ADMIN_BASE_URL", "https://legacy.invalid")
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": "success",
                "data": {"connector_id": "binance", "api_key": "", "api_secret": "", "passphrase": ""},
                "errors": [],
            }

    monkeypatch.setattr("steuerreport_v2.domain.admin.httpx.post", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(
        SourceService,
        "connector_diagnostics",
        lambda _self: SourceConnectorDiagnosticsReport(
            generated_at=datetime.now(timezone.utc),
            diagnostics=[
                SourceConnectorDiagnostic(
                    source_id="binance",
                    label="Binance",
                    connector_id="binance",
                    connector_type="cex",
                    status="credential_decrypt_failed",
                    credential_status="decrypt_failed",
                    credential_issue="secret_rows_present_but_empty_after_decrypt",
                    credential_keys_present=2,
                    credential_keys_required=2,
                    message="not decryptable",
                    next_action="restore key",
                )
            ],
            methodology="test",
        ),
    )

    item = AdminService(store)._v1_cex_takeover_item("binance")

    assert item.status == "not_decryptable"
    assert item.can_take_over is False
    assert item.keys_present == 2
    assert item.keys_required == 2


def test_v1_cex_takeover_imports_transferable_credentials_without_echoing(tmp_path, monkeypatch):
    monkeypatch.setattr(AdminService, "V1_ADMIN_BASE_URL", "https://legacy.invalid")
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    saved: list[CexCredentialWrite] = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": "success",
                "data": {"connector_id": "binance", "api_key": "old-key", "api_secret": "old-secret", "passphrase": ""},
                "errors": [],
            }

    monkeypatch.setattr("steuerreport_v2.domain.admin.httpx.post", lambda *_args, **_kwargs: Response())
    monkeypatch.setattr(
        SourceService,
        "connector_diagnostics",
        lambda _self: SourceConnectorDiagnosticsReport(
            generated_at=datetime.now(timezone.utc),
            diagnostics=[
                SourceConnectorDiagnostic(
                    source_id="binance",
                    label="Binance",
                    connector_id="binance",
                    connector_type="cex",
                    status="fresh",
                    credential_status="configured",
                    credential_keys_present=2,
                    credential_keys_required=2,
                    message="ok",
                    next_action="refresh",
                )
            ],
            methodology="test",
        ),
    )

    def fake_save(self, payload: CexCredentialWrite):
        saved.append(payload)
        return CexCredentialWriteResult(
            connector_id=payload.connector_id,
            status="ok",
            written_keys=[f"secret.cex.{payload.connector_id}.api_key", f"secret.cex.{payload.connector_id}.api_secret"],
            diagnostic_status="fresh",
            credential_status="configured",
            message="ok",
        )

    from steuerreport_v2.contracts.admin import CexCredentialWriteResult

    monkeypatch.setattr(AdminService, "save_cex_credentials", fake_save)

    result = AdminService(store).import_v1_cex_credentials(connectors=["binance"])

    assert len(result.imported) == 1
    assert result.skipped == []
    assert saved[0].api_key == "old-key"
    assert saved[0].api_secret == "old-secret"
    assert "old-secret" not in str(result)


def test_v1_cex_takeover_api_reports_skipped_connectors(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    skipped = [
        SourceConnectorDiagnostic(
            source_id="binance",
            label="Binance",
            connector_id="binance",
            connector_type="cex",
            status="credential_decrypt_failed",
            credential_status="decrypt_failed",
            credential_keys_present=2,
            credential_keys_required=2,
            message="not decryptable",
            next_action="restore key",
        )
    ]

    monkeypatch.setattr(
        AdminService,
        "import_v1_cex_credentials",
        lambda _self, connectors=None: __import__("steuerreport_v2.contracts.admin", fromlist=["V1CexCredentialTakeoverResult"]).V1CexCredentialTakeoverResult(
            generated_at=datetime.now(timezone.utc),
            imported=[],
            skipped=[
                __import__("steuerreport_v2.contracts.admin", fromlist=["V1CexCredentialTakeoverItem"]).V1CexCredentialTakeoverItem(
                    connector_id="binance",
                    status="not_decryptable",
                    can_take_over=False,
                    has_api_key=False,
                    has_api_secret=False,
                    keys_present=2,
                    keys_required=2,
                    credential_issue="v1_returned_empty_credentials",
                    next_action="restore key",
                )
            ],
            methodology="test",
        ),
    )
    client = TestClient(create_app(store))

    response = client.post("/api/v1/admin/cex-credentials/v1-takeover", json={"connectors": ["binance"]})

    assert skipped[0].connector_id == "binance"
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "warning"
    assert body["data"]["skipped"][0]["status"] == "not_decryptable"


def test_ai_external_task_is_blocked_by_default(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    task = AiService(store).create_task(
        AiTaskCreate(task_type="review", prompt="analyse", allow_external=True)
    )

    assert task.status == "failed"
    assert task.result_json == '{"error": "external_ai_disabled"}'


def test_ai_local_task_is_queued(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")

    task = AiService(store).create_task(
        AiTaskCreate(task_type="review", prompt="analyse", allow_external=False)
    )

    assert task.status == "queued"
    assert AiService(store).list_tasks()[0].task_id == task.task_id


def test_ai_task_endpoint_creates_local_task(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/ai/tasks",
        json={"task_type": "review", "prompt": "analyse", "allow_external": False},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["task_type"] == "review"
    assert data["status"] == "queued"
    assert client.get("/api/v1/ai/tasks").json()["data"][0]["task_id"] == data["task_id"]


def test_ai_task_endpoint_blocks_external_task_by_default(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))

    response = client.post(
        "/api/v1/ai/tasks",
        json={"task_type": "review", "prompt": "analyse", "allow_external": True},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "failed"
    assert data["result_json"] == '{"error": "external_ai_disabled"}'


def test_ai_task_endpoint_deletes_task(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    task = AiService(store).create_task(
        AiTaskCreate(task_type="review", prompt="analyse", allow_external=False)
    )
    client = TestClient(create_app(store))

    response = client.delete(f"/api/v1/ai/tasks/{task.task_id}")

    assert response.status_code == 200
    assert response.json()["data"] == {"task_id": task.task_id, "deleted": True}
    assert AiService(store).list_tasks() == []


def test_ai_task_endpoint_warns_for_missing_delete(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    client = TestClient(create_app(store))

    response = client.delete("/api/v1/ai/tasks/missing")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "warning"
    assert body["data"] == {"task_id": "missing", "deleted": False}
    assert body["warnings"][0]["code"] == "ai_task_not_found"


def test_local_year_package_qa_status_reads_latest_run(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    root = tmp_path / "year_package_qa_20260614"
    run = root / "run_20260614T160900Z"
    run.mkdir(parents=True)
    (run / "summary.md").write_text("# Summary\n", encoding="utf-8")
    (run / "local_ai_review.md").write_text("# Review\n", encoding="utf-8")
    (run / "run_status.json").write_text(
        json.dumps(
            {
                "status": "ok",
                "llm_status": "ok",
                "finished_at": "2026-06-14T16:14:12+00:00",
                "findings": [],
                "years": [
                    {
                        "year": 2024,
                        "export_ready": True,
                        "zip_file_count": 10,
                        "manifest_file_count": 8,
                        "tax_line_years": ["2024"],
                        "findings": [],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(AiService, "YEAR_PACKAGE_QA_ROOT", root)

    status = AiService(store).local_year_package_qa_status()

    assert status.status == "ok"
    assert status.llm_status == "ok"
    assert status.latest_run_id == "20260614T160900Z"
    assert status.findings_count == 0
    assert status.years[0].year == 2024
    assert status.years[0].tax_line_years == ["2024"]
    assert status.summary_md == "# Summary\n"
    assert status.local_ai_review_md == "# Review\n"


def test_local_year_package_qa_status_missing_when_no_runs(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    monkeypatch.setattr(AiService, "YEAR_PACKAGE_QA_ROOT", tmp_path / "missing")

    status = AiService(store).local_year_package_qa_status()

    assert status.status == "missing"
    assert status.years == []


def test_local_year_package_qa_endpoint(tmp_path, monkeypatch):
    root = tmp_path / "year_package_qa_20260614"
    run = root / "run_20260614T160900Z"
    run.mkdir(parents=True)
    (run / "run_status.json").write_text(
        json.dumps({"status": "ok", "llm_status": "ok", "findings": [], "years": []}),
        encoding="utf-8",
    )
    monkeypatch.setattr(AiService, "YEAR_PACKAGE_QA_ROOT", root)
    client = TestClient(create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb")))

    response = client.get("/api/v1/ai/local-year-package-qa")

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "ok"


def test_local_year_package_qa_artifact_download_endpoint(tmp_path, monkeypatch):
    root = tmp_path / "year_package_qa_20260614"
    run = root / "run_20260614T160900Z"
    run.mkdir(parents=True)
    (run / "summary.md").write_text("# Summary\n", encoding="utf-8")
    monkeypatch.setattr(AiService, "YEAR_PACKAGE_QA_ROOT", root)
    client = TestClient(create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb")))

    response = client.get("/api/v1/ai/local-year-package-qa/artifacts/summary")

    assert response.status_code == 200
    assert response.text == "# Summary\n"
    assert "filename=summary.md" in response.headers["content-disposition"]


def test_local_year_package_qa_artifact_download_endpoint_warns_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(AiService, "YEAR_PACKAGE_QA_ROOT", tmp_path / "missing")
    client = TestClient(create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb")))

    response = client.get("/api/v1/ai/local-year-package-qa/artifacts/summary")

    assert response.status_code == 404
    body = response.json()
    assert body["status"] == "warning"
    assert body["warnings"][0]["code"] == "local_ai_year_package_qa_artifact_missing"


def test_local_asset_fifo_correction_status_reads_latest_run(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    root = tmp_path / "asset_fifo_correction_review_20260620"
    run = root / "run_20260620T120000Z"
    run.mkdir(parents=True)
    (run / "summary.md").write_text("# Summary\n", encoding="utf-8")
    (run / "local_ai_review.md").write_text("# Review\n", encoding="utf-8")
    (run / "run_status.json").write_text(
        json.dumps(
            {
                "status": "review",
                "llm_status": "ok",
                "finished_at": "2026-06-20T12:00:00+00:00",
                "years": [
                    {
                        "year": 2025,
                        "rows_count": 8,
                        "possible_recalculation_assets_count": 2,
                        "attribution_review_assets_count": 6,
                        "candidate_assets": ["BTC", "WBTC"],
                    }
                ],
                "candidates": [
                    {
                        "year": 2025,
                        "asset": "BTC",
                        "tax_sum_impact": "possible_recalculation_after_review",
                        "direct_gain_loss_eur": "0",
                        "linked_gain_loss_eur": "379.99",
                        "related_tax_lines_count": 7,
                        "related_tax_lines_csv": "var/local_ai_prework/x.csv",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(AiService, "ASSET_FIFO_CORRECTION_ROOT", root)

    status = AiService(store).local_asset_fifo_correction_status()

    assert status.status == "review"
    assert status.llm_status == "ok"
    assert status.candidates_count == 1
    assert status.years[0].candidate_assets == ["BTC", "WBTC"]
    assert status.candidates[0].asset == "BTC"
    assert status.summary_md == "# Summary\n"
    assert status.local_ai_review_md == "# Review\n"


def test_local_asset_fifo_correction_endpoint_and_artifact(tmp_path, monkeypatch):
    root = tmp_path / "asset_fifo_correction_review_20260620"
    run = root / "run_20260620T120000Z"
    run.mkdir(parents=True)
    (run / "run_status.json").write_text(
        json.dumps({"status": "review", "llm_status": "dry_run", "years": [], "candidates": []}),
        encoding="utf-8",
    )
    (run / "summary.md").write_text("# Asset Summary\n", encoding="utf-8")
    monkeypatch.setattr(AiService, "ASSET_FIFO_CORRECTION_ROOT", root)
    client = TestClient(create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb")))

    status_response = client.get("/api/v1/ai/local-asset-fifo-correction-review")
    artifact_response = client.get("/api/v1/ai/local-asset-fifo-correction-review/artifacts/summary")

    assert status_response.status_code == 200
    assert status_response.json()["data"]["status"] == "review"
    assert artifact_response.status_code == 200
    assert artifact_response.text == "# Asset Summary\n"
    assert "filename=summary.md" in artifact_response.headers["content-disposition"]


def test_local_wallet_fifo_provenance_status_reads_latest_run(tmp_path, monkeypatch):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    root = tmp_path / "wallet_fifo_provenance_review_20260620"
    run = root / "run_20260620T180000Z"
    (run / "reports").mkdir(parents=True)
    (run / "summary.md").write_text("# Wallet Summary\n", encoding="utf-8")
    (run / "local_ai_review.md").write_text("# Wallet Review\n", encoding="utf-8")
    (run / "reports" / "wallet_fifo_gap_groups.csv").write_text("year,asset\n2024,SOL\n", encoding="utf-8")
    (run / "run_status.json").write_text(
        json.dumps(
            {
                "status": "review",
                "llm_status": "ok",
                "finished_at": "2026-06-20T18:00:00+00:00",
                "groups_count": 4,
                "blocking_groups_count": 3,
                "groups_csv": "var/local_ai_prework/wallet_fifo_provenance_review_20260620/run_x/reports/wallet_fifo_gap_groups.csv",
                "years": [
                    {
                        "year": 2024,
                        "bmf_status": "blocked",
                        "blocking_items_count": 1,
                        "wallet_unmatched_count": 16,
                        "wallet_delta_gain_loss_eur": "-24112.53",
                        "groups_count": 4,
                        "likely_causes": {"missing_pool_lot": 4},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(AiService, "WALLET_FIFO_PROVENANCE_ROOT", root)

    status = AiService(store).local_wallet_fifo_provenance_status()

    assert status.status == "review"
    assert status.llm_status == "ok"
    assert status.groups_count == 4
    assert status.blocking_groups_count == 3
    assert status.years[0].wallet_unmatched_count == 16
    assert status.years[0].likely_causes == {"missing_pool_lot": 4}
    assert status.summary_md == "# Wallet Summary\n"
    assert status.local_ai_review_md == "# Wallet Review\n"


def test_local_wallet_fifo_provenance_endpoint_and_artifact(tmp_path, monkeypatch):
    root = tmp_path / "wallet_fifo_provenance_review_20260620"
    run = root / "run_20260620T180000Z"
    (run / "reports").mkdir(parents=True)
    (run / "run_status.json").write_text(
        json.dumps({"status": "review", "llm_status": "dry_run", "years": [], "groups_count": 0}),
        encoding="utf-8",
    )
    (run / "reports" / "wallet_fifo_gap_groups.csv").write_text("year,asset\n2024,SOL\n", encoding="utf-8")
    monkeypatch.setattr(AiService, "WALLET_FIFO_PROVENANCE_ROOT", root)
    client = TestClient(create_app(DuckDbStore(tmp_path / "steuerreport_v2.duckdb")))

    status_response = client.get("/api/v1/ai/local-wallet-fifo-provenance-review")
    artifact_response = client.get("/api/v1/ai/local-wallet-fifo-provenance-review/artifacts/groups-csv")

    assert status_response.status_code == 200
    assert status_response.json()["data"]["status"] == "review"
    assert artifact_response.status_code == 200
    assert artifact_response.text == "year,asset\n2024,SOL\n"
    assert "filename=wallet_fifo_gap_groups.csv" in artifact_response.headers["content-disposition"]


def test_audit_and_elster_prep_exports(tmp_path):
    store = _seed_clean_store(tmp_path)
    decision = store.add_review_decision(
        ReviewDecisionCreate(
            decision_type="parity_finding",
            scope="parity:year:2024:asset:SOL:status:diff",
            title="SOL Differenz akzeptiert",
            rationale="Belegter V2-Korrekturpfad.",
            evidence_ref="docs/test.md",
            actor="codex",
            source="unit-test",
            affected_ids=["event-1", "event-2"],
            payload={"decision_status": "accepted_difference"},
        )
    )
    token_risk_decision = store.add_review_decision(
        ReviewDecisionCreate(
            decision_type="token_risk_documentation",
            scope=(
                "token_risk:spam_review:asset:CBDC:"
                "mint:2KFZCkfxj1Us8YRQZa5vktSxy3GPzFZvVhWj91n8Fv2J"
            ),
            title="Spam/Dust-Token dokumentieren: CBDC",
            rationale="Read-only Dokumentation ohne Steuerdatenwirkung.",
            evidence_ref="/api/v1/portfolio/token-risk?risk_status=spam_review&min_value_eur=1",
            actor="codex",
            source="api:/api/v1/review/decision-suggestions",
            affected_ids=[
                "asset:CBDC",
                "token_mint:2KFZCkfxj1Us8YRQZa5vktSxy3GPzFZvVhWj91n8Fv2J",
                "account:wallet-main",
            ],
            payload={
                "asset": "CBDC",
                "token_symbol": "CBDC",
                "token_name": "Central Bank Digital Currency",
                "token_mint": "2KFZCkfxj1Us8YRQZa5vktSxy3GPzFZvVhWj91n8Fv2J",
                "token_risk_status": "spam_review",
                "quantity": "4202343.53",
                "value_eur": "42.56973995890000000000000000",
                "accounts": ["wallet-main"],
                "import_effect": "none",
                "ledger_effect": "none",
                "fifo_effect": "none",
                "tax_line_effect": "none",
            },
        )
    )

    audit = AuditService(store).export()
    elster = AuditService(store).elster_prep()

    assert audit.import_batches == 1
    assert audit.raw_objects == 1
    assert audit.canonical_events == 1
    assert audit.balance_entries == 1
    assert audit.review_allow_export is True
    assert audit.export_ready is True
    assert audit.parity_release_ready is True
    assert audit.parity_blocking_groups == 0
    assert audit.hnt_provenance is not None
    assert "Transfer-/Bridge-Nachweise" in audit.hnt_provenance.methodology
    assert audit.transfer_context_note is not None
    assert "stichtagsgenaue Historie" in audit.transfer_context_note
    assert audit.review_decisions_count == 2
    parity_decision = next(
        item for item in audit.review_decisions if item.decision_id == decision.decision_id
    )
    assert parity_decision.actor == "codex"
    assert parity_decision.affected_ids == ["event-1", "event-2"]
    assert audit.token_risk_documentation.documented_count == 1
    assert audit.token_risk_documentation.total_value_eur == "42.56973995890000000000000000"
    assert audit.token_risk_documentation.items[0].decision_id == token_risk_decision.decision_id
    assert audit.token_risk_documentation.items[0].asset == "CBDC"
    assert audit.token_risk_documentation.items[0].accounts == ["wallet-main"]
    assert audit.token_risk_documentation.items[0].fifo_effect == "none"
    assert audit.token_risk_documentation.items[0].tax_line_effect == "none"
    assert elster.direct_eric_submission is False
    assert elster.export_ready is True
    assert elster.parity_release_ready is True
    assert elster.token_risk_documentation_count == 1
    assert any("Token-Risiko-Dokumentationen" in note for note in elster.notes)


def test_audit_export_separates_historical_review_issues(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.upsert_admin_setting(
        AdminSettingWrite(
            key="runtime.review.closed_tax_years",
            value_json="[2020, 2021, 2022]",
        )
    )
    batch = CsvRawImporter(store).import_text(
        source="binance",
        filename="bnb.csv",
        content=(
            "time,asset,amount,type,quote_asset,quote_quantity\n"
            "2021-04-27T00:00:00Z,BNB,2.235,transfer,,\n"
            "2021-04-28T07:53:14Z,BNB,-2.47,sell,EUR,1136.09\n"
            "2021-04-29T00:00:00Z,BNB,0.235,transfer,,\n"
        ),
    )
    RawNormalizer(store).normalize_batch(batch.batch_id)
    BalanceLedgerBuilder(store).rebuild()
    store.add_price_point(
        PricePointCreate(
            asset="BNB",
            price_eur=Decimal("460"),
            priced_at=datetime(2021, 4, 28, tzinfo=timezone.utc),
            source="manual-test",
        )
    )
    TaxService(store).rebuild_fifo()

    audit = AuditService(store).export()

    assert audit.export_ready is True
    assert audit.review_issues_open == 0
    assert audit.review_issues_current_open == 0
    assert audit.review_issues_historical_open == 1
    assert audit.review_issues_open_total == 1
    assert audit.review_blocking_issues_open == 0


def test_audit_and_elster_block_when_parity_is_unresolved(tmp_path):
    store = _seed_clean_store(tmp_path)
    store.add_v1_reference_metric(
        V1ReferenceMetricCreate(
            scope="year:2021:asset:USDT",
            metric="gain_loss_eur",
            unit="EUR",
            value=Decimal("12.34"),
            year=2021,
            asset="USDT",
            source="test",
            note="audit export must include parity gate",
        )
    )

    audit = AuditService(store).export()
    elster = AuditService(store).elster_prep()

    assert audit.review_allow_export is True
    assert audit.export_ready is False
    assert audit.parity_release_ready is False
    assert audit.parity_unresolved_groups == 1
    assert audit.parity_blocking_groups == 1
    assert audit.parity_blocking_difference_eur == "0"
    assert elster.export_ready is False
    assert elster.parity_release_ready is False
    assert elster.parity_blocking_groups == 1


def test_audit_export_contains_price_gaps(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="manual-test",
            source_ref="iot-buy-1",
            event_time=datetime(2024, 4, 1, tzinfo=timezone.utc),
            event_type="trade",
            asset="SOL",
            quantity=Decimal("1"),
            quote_asset="IOT",
            quote_quantity=Decimal("100"),
        )
    )

    audit = AuditService(store).export()

    assert audit.price_gaps_count == 1
    assert audit.price_gap_assets == ["IOT"]
    assert audit.price_gaps[0].scope == (
        "price_gap:asset:IOT:year:2024:source:manual-test:event_type:trade:role:quote_asset"
    )


def test_review_decisions_csv_export(tmp_path):
    store = _seed_clean_store(tmp_path)
    store.add_review_decision(
        ReviewDecisionCreate(
            decision_type="opening_balance_candidate",
            scope="account:Solana:asset:SOL",
            title="SOL Opening",
            rationale="Staging-Kandidat.",
            actor="codex",
            source="unit-test",
            affected_ids=["evt-1"],
            payload={"asset": "SOL", "amount": "1"},
        )
    )
    client = TestClient(create_app(store))

    response = client.get("/api/v1/export/review-decisions.csv")

    assert response.status_code == 200
    assert "review-decisions.csv" in response.headers["content-disposition"]
    text = response.text
    assert "opening_balance_candidate" in text
    assert "account:Solana:asset:SOL" in text
    assert "codex" in text


def test_token_risk_documentation_csv_export(tmp_path):
    store = _seed_clean_store(tmp_path)
    store.add_review_decision(
        ReviewDecisionCreate(
            decision_type="token_risk_documentation",
            scope=(
                "token_risk:spam_review:asset:CBDC:"
                "mint:2KFZCkfxj1Us8YRQZa5vktSxy3GPzFZvVhWj91n8Fv2J"
            ),
            title="Spam/Dust-Token dokumentieren: CBDC",
            rationale="Read-only Dokumentation ohne Steuerdatenwirkung.",
            evidence_ref="/api/v1/portfolio/token-risk?risk_status=spam_review&min_value_eur=1",
            actor="codex",
            source="unit-test",
            affected_ids=["asset:CBDC"],
            payload={
                "asset": "CBDC",
                "token_symbol": "CBDC",
                "token_name": "Central Bank Digital Currency",
                "token_mint": "2KFZCkfxj1Us8YRQZa5vktSxy3GPzFZvVhWj91n8Fv2J",
                "token_risk_status": "spam_review",
                "quantity": "4202343.53",
                "value_eur": "42.56973995890000000000000000",
                "accounts": ["wallet-main"],
                "import_effect": "none",
                "ledger_effect": "none",
                "fifo_effect": "none",
                "tax_line_effect": "none",
            },
        )
    )
    store.add_review_decision(
        ReviewDecisionCreate(
            decision_type="opening_balance_candidate",
            scope="account:Solana:asset:SOL",
            title="SOL Opening",
            rationale="Nicht im Spezialexport.",
            actor="codex",
            source="unit-test",
            payload={"asset": "SOL"},
        )
    )
    client = TestClient(create_app(store))

    response = client.get("/api/v1/export/token-risk-documentation.csv")

    assert response.status_code == 200
    assert "token-risk-documentation.csv" in response.headers["content-disposition"]
    text = response.text
    assert "CBDC" in text
    assert "Central Bank Digital Currency" in text
    assert "42.56973995890000000000000000" in text
    assert "wallet-main" in text
    assert "opening_balance_candidate" not in text


def test_price_gaps_csv_export(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="manual-test",
            source_ref="iot-buy-1",
            event_time=datetime(2024, 4, 1, tzinfo=timezone.utc),
            event_type="trade",
            asset="SOL",
            quantity=Decimal("1"),
            quote_asset="IOT",
            quote_quantity=Decimal("100"),
        )
    )
    client = TestClient(create_app(store))

    response = client.get("/api/v1/export/price-gaps.csv")

    assert response.status_code == 200
    assert "price-gaps.csv" in response.headers["content-disposition"]
    text = response.text
    assert "price_gap:asset:IOT:year:2024:source:manual-test:event_type:trade:role:quote_asset" in text
    assert "unreviewed" in text
    assert "100.000000000000000000" in text


def test_price_requirements_csv_export(tmp_path):
    store = DuckDbStore(tmp_path / "steuerreport_v2.duckdb")
    store.add_canonical_event(
        CanonicalEventCreate(
            source="manual-test",
            source_ref="iot-buy-1",
            event_time=datetime(2024, 4, 1, tzinfo=timezone.utc),
            event_type="trade",
            asset="SOL",
            quantity=Decimal("1"),
            quote_asset="IOT",
            quote_quantity=Decimal("100"),
        )
    )
    client = TestClient(create_app(store))

    response = client.get("/api/v1/export/price-requirements.csv")

    assert response.status_code == 200
    assert "price-requirements.csv" in response.headers["content-disposition"]
    text = response.text
    assert "IOT" in text
    assert "2024-04-01" in text
    assert "100.000000000000000000" in text
