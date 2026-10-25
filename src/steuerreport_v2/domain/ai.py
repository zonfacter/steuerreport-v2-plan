from __future__ import annotations

from steuerreport_v2.paths import PROJECT_ROOT as SOFTWARE_ROOT

from datetime import datetime
import json
from pathlib import Path

from steuerreport_v2.contracts.ai import (
    AiTask,
    AiTaskCreate,
    LocalAiAssetFifoCorrectionCandidate,
    LocalAiAssetFifoCorrectionStatus,
    LocalAiAssetFifoCorrectionYear,
    LocalAiWalletFifoProvenanceStatus,
    LocalAiWalletFifoProvenanceYear,
    LocalAiYearPackageQaStatus,
    LocalAiYearPackageQaYear,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.admin import AdminService
from steuerreport_v2.domain.ai_provider import AiProviderError


class AiService:
    YEAR_PACKAGE_QA_ROOT = SOFTWARE_ROOT / "var" / "local_ai_prework" / "year_package_qa_20260614"
    ASSET_FIFO_CORRECTION_ROOT = SOFTWARE_ROOT / "var" / "local_ai_prework" / "asset_fifo_correction_review_20260620"
    WALLET_FIFO_PROVENANCE_ROOT = SOFTWARE_ROOT / "var" / "local_ai_prework" / "wallet_fifo_provenance_review_20260620"
    YEAR_PACKAGE_QA_ARTIFACTS = {
        "summary": ("summary.md", "text/markdown; charset=utf-8"),
        "review": ("local_ai_review.md", "text/markdown; charset=utf-8"),
        "findings": ("findings.json", "application/json"),
        "run-status": ("run_status.json", "application/json"),
    }
    ASSET_FIFO_CORRECTION_ARTIFACTS = {
        "summary": ("summary.md", "text/markdown; charset=utf-8"),
        "review": ("local_ai_review.md", "text/markdown; charset=utf-8"),
        "findings": ("findings.json", "application/json"),
        "run-status": ("run_status.json", "application/json"),
    }
    WALLET_FIFO_PROVENANCE_ARTIFACTS = {
        "summary": ("summary.md", "text/markdown; charset=utf-8"),
        "review": ("local_ai_review.md", "text/markdown; charset=utf-8"),
        "findings": ("findings.json", "application/json"),
        "run-status": ("run_status.json", "application/json"),
        "groups-csv": ("reports/wallet_fifo_gap_groups.csv", "text/csv; charset=utf-8"),
    }

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def create_task(self, payload: AiTaskCreate) -> AiTask:
        settings = {setting.key: setting.value_json for setting in AdminService(self.store).list_settings()}
        external_enabled = json.loads(settings.get("ai.external.enabled", "false"))
        if payload.allow_external and not external_enabled:
            return self.store.create_ai_task(
                payload,
                status="failed",
                result_json=json.dumps(
                    {"error": "external_ai_disabled"},
                    sort_keys=True,
                ),
            )

        return self.store.create_ai_task(
            payload,
            status="queued",
            result_json=None,
        )

    def list_tasks(self) -> list[AiTask]:
        return self.store.list_ai_tasks()

    def delete_task(self, task_id: str) -> bool:
        with self.store.exclusive_access():
            task = self.store.get_ai_task(task_id)
            if task is not None and task.status == "running":
                raise AiProviderError("ai_task_running")
            return self.store.delete_ai_task(task_id)

    def local_year_package_qa_status(self) -> LocalAiYearPackageQaStatus:
        runs = sorted(self.YEAR_PACKAGE_QA_ROOT.glob("run_*"), reverse=True)
        if not runs:
            return LocalAiYearPackageQaStatus(
                status="missing",
                methodology=(
                    "Read-only Status aus lokalen Jahrespaket-QA-Artefakten. "
                    "Es wurden noch keine Laufartefakte gefunden."
                ),
            )
        latest = runs[0]
        run_status_path = latest / "run_status.json"
        summary_path = latest / "summary.md"
        review_path = latest / "local_ai_review.md"
        if not run_status_path.exists():
            return LocalAiYearPackageQaStatus(
                status="incomplete",
                latest_run_id=latest.name.removeprefix("run_"),
                latest_run_path=str(latest),
                summary_md=self._read_optional_text(summary_path),
                local_ai_review_md=self._read_optional_text(review_path),
                methodology="Latest local AI year-package QA run exists but run_status.json is missing.",
            )
        try:
            data = json.loads(run_status_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return LocalAiYearPackageQaStatus(
                status="invalid",
                latest_run_id=latest.name.removeprefix("run_"),
                latest_run_path=str(latest),
                summary_md=self._read_optional_text(summary_path),
                local_ai_review_md=self._read_optional_text(review_path),
                methodology="Latest local AI year-package QA run_status.json is not valid JSON.",
            )
        return LocalAiYearPackageQaStatus(
            status=str(data.get("status") or "unknown"),
            llm_status=data.get("llm_status"),
            latest_run_id=latest.name.removeprefix("run_"),
            latest_run_path=str(latest),
            generated_at=self._parse_dt(data.get("finished_at")),
            findings_count=len(data.get("findings") or []),
            years=[
                LocalAiYearPackageQaYear(
                    year=int(row.get("year") or 0),
                    export_ready=row.get("export_ready"),
                    zip_file_count=int(row.get("zip_file_count") or 0),
                    manifest_file_count=int(row.get("manifest_file_count") or 0),
                    tax_line_years=[str(item) for item in row.get("tax_line_years") or []],
                    findings_count=len(row.get("findings") or []),
                )
                for row in data.get("years") or []
            ],
            summary_md=self._read_optional_text(summary_path),
            local_ai_review_md=self._read_optional_text(review_path),
            methodology=(
                "Read-only Status aus lokalen Jahrespaket-QA-Artefakten unter "
                "var/local_ai_prework/year_package_qa_20260614. Der Endpunkt "
                "startet keinen KI-Lauf und schreibt keine Daten."
            ),
        )

    def local_year_package_qa_artifact(self, artifact: str) -> tuple[str, str, bytes] | None:
        entry = self.YEAR_PACKAGE_QA_ARTIFACTS.get(artifact)
        if entry is None:
            return None
        runs = sorted(self.YEAR_PACKAGE_QA_ROOT.glob("run_*"), reverse=True)
        if not runs:
            return None
        filename, media_type = entry
        path = runs[0] / filename
        if not path.exists() or not path.is_file():
            return None
        return filename, media_type, path.read_bytes()

    def local_asset_fifo_correction_status(self) -> LocalAiAssetFifoCorrectionStatus:
        runs = sorted(self.ASSET_FIFO_CORRECTION_ROOT.glob("run_*"), reverse=True)
        if not runs:
            return LocalAiAssetFifoCorrectionStatus(
                status="missing",
                methodology=(
                    "Read-only Status aus lokalen Asset-FIFO-Korrekturreview-Artefakten. "
                    "Es wurden noch keine Laufartefakte gefunden."
                ),
            )
        latest = runs[0]
        run_status_path = latest / "run_status.json"
        summary_path = latest / "summary.md"
        review_path = latest / "local_ai_review.md"
        if not run_status_path.exists():
            return LocalAiAssetFifoCorrectionStatus(
                status="incomplete",
                latest_run_id=latest.name.removeprefix("run_"),
                latest_run_path=str(latest),
                summary_md=self._read_optional_text(summary_path),
                local_ai_review_md=self._read_optional_text(review_path),
                methodology="Latest local AI asset-FIFO correction run exists but run_status.json is missing.",
            )
        try:
            data = json.loads(run_status_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return LocalAiAssetFifoCorrectionStatus(
                status="invalid",
                latest_run_id=latest.name.removeprefix("run_"),
                latest_run_path=str(latest),
                summary_md=self._read_optional_text(summary_path),
                local_ai_review_md=self._read_optional_text(review_path),
                methodology="Latest local AI asset-FIFO correction run_status.json is not valid JSON.",
            )
        candidates = data.get("candidates") or []
        return LocalAiAssetFifoCorrectionStatus(
            status=str(data.get("status") or "unknown"),
            llm_status=data.get("llm_status"),
            latest_run_id=latest.name.removeprefix("run_"),
            latest_run_path=str(latest),
            generated_at=self._parse_dt(data.get("finished_at")),
            candidates_count=len(candidates),
            years=[
                LocalAiAssetFifoCorrectionYear(
                    year=int(row.get("year") or 0),
                    rows_count=int(row.get("rows_count") or 0),
                    possible_recalculation_assets_count=int(row.get("possible_recalculation_assets_count") or 0),
                    attribution_review_assets_count=int(row.get("attribution_review_assets_count") or 0),
                    candidate_assets=[str(item) for item in row.get("candidate_assets") or []],
                )
                for row in data.get("years") or []
            ],
            candidates=[
                LocalAiAssetFifoCorrectionCandidate(
                    year=int(row.get("year") or 0),
                    asset=str(row.get("asset") or ""),
                    tax_sum_impact=str(row.get("tax_sum_impact") or ""),
                    direct_gain_loss_eur=row.get("direct_gain_loss_eur"),
                    linked_gain_loss_eur=row.get("linked_gain_loss_eur"),
                    related_tax_lines_count=int(row.get("related_tax_lines_count") or 0),
                    related_tax_lines_csv=row.get("related_tax_lines_csv"),
                )
                for row in candidates
            ],
            summary_md=self._read_optional_text(summary_path),
            local_ai_review_md=self._read_optional_text(review_path),
            methodology=(
                "Read-only Status aus lokalen Asset-FIFO-Korrekturreview-Artefakten "
                "unter var/local_ai_prework/asset_fifo_correction_review_20260620. "
                "Der Endpunkt startet keinen KI-Lauf und schreibt keine Daten."
            ),
        )

    def local_asset_fifo_correction_artifact(self, artifact: str) -> tuple[str, str, bytes] | None:
        entry = self.ASSET_FIFO_CORRECTION_ARTIFACTS.get(artifact)
        if entry is None:
            return None
        runs = sorted(self.ASSET_FIFO_CORRECTION_ROOT.glob("run_*"), reverse=True)
        if not runs:
            return None
        filename, media_type = entry
        path = runs[0] / filename
        if not path.exists() or not path.is_file():
            return None
        return filename, media_type, path.read_bytes()

    def local_wallet_fifo_provenance_status(self) -> LocalAiWalletFifoProvenanceStatus:
        runs = sorted(self.WALLET_FIFO_PROVENANCE_ROOT.glob("run_*"), reverse=True)
        if not runs:
            return LocalAiWalletFifoProvenanceStatus(
                status="missing",
                methodology=(
                    "Read-only Status aus lokalen Wallet-FIFO-Provenance-Artefakten. "
                    "Es wurden noch keine Laufartefakte gefunden."
                ),
            )
        latest = runs[0]
        run_status_path = latest / "run_status.json"
        summary_path = latest / "summary.md"
        review_path = latest / "local_ai_review.md"
        if not run_status_path.exists():
            return LocalAiWalletFifoProvenanceStatus(
                status="incomplete",
                latest_run_id=latest.name.removeprefix("run_"),
                latest_run_path=str(latest),
                summary_md=self._read_optional_text(summary_path),
                local_ai_review_md=self._read_optional_text(review_path),
                methodology="Latest local AI wallet-FIFO provenance run exists but run_status.json is missing.",
            )
        try:
            data = json.loads(run_status_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return LocalAiWalletFifoProvenanceStatus(
                status="invalid",
                latest_run_id=latest.name.removeprefix("run_"),
                latest_run_path=str(latest),
                summary_md=self._read_optional_text(summary_path),
                local_ai_review_md=self._read_optional_text(review_path),
                methodology="Latest local AI wallet-FIFO provenance run_status.json is not valid JSON.",
            )
        return LocalAiWalletFifoProvenanceStatus(
            status=str(data.get("status") or "unknown"),
            llm_status=data.get("llm_status"),
            latest_run_id=latest.name.removeprefix("run_"),
            latest_run_path=str(latest),
            generated_at=self._parse_dt(data.get("finished_at")),
            groups_count=int(data.get("groups_count") or 0),
            blocking_groups_count=int(data.get("blocking_groups_count") or 0),
            groups_csv=data.get("groups_csv"),
            years=[
                LocalAiWalletFifoProvenanceYear(
                    year=int(row.get("year") or 0),
                    bmf_status=row.get("bmf_status"),
                    blocking_items_count=int(row.get("blocking_items_count") or 0),
                    wallet_unmatched_count=int(row.get("wallet_unmatched_count") or 0),
                    wallet_delta_gain_loss_eur=row.get("wallet_delta_gain_loss_eur"),
                    groups_count=int(row.get("groups_count") or 0),
                    likely_causes={str(key): int(value) for key, value in (row.get("likely_causes") or {}).items()},
                )
                for row in data.get("years") or []
            ],
            summary_md=self._read_optional_text(summary_path),
            local_ai_review_md=self._read_optional_text(review_path),
            methodology=(
                "Read-only Status aus lokalen Wallet-FIFO-Provenance-Artefakten "
                "unter var/local_ai_prework/wallet_fifo_provenance_review_20260620. "
                "Der Endpunkt startet keinen KI-Lauf und schreibt keine Daten."
            ),
        )

    def local_wallet_fifo_provenance_artifact(self, artifact: str) -> tuple[str, str, bytes] | None:
        entry = self.WALLET_FIFO_PROVENANCE_ARTIFACTS.get(artifact)
        if entry is None:
            return None
        runs = sorted(self.WALLET_FIFO_PROVENANCE_ROOT.glob("run_*"), reverse=True)
        if not runs:
            return None
        filename, media_type = entry
        path = runs[0] / filename
        if not path.exists() or not path.is_file():
            return None
        return Path(filename).name, media_type, path.read_bytes()

    @staticmethod
    def _read_optional_text(path: Path) -> str | None:
        return path.read_text(encoding="utf-8") if path.exists() else None

    @staticmethod
    def _parse_dt(value: object) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
