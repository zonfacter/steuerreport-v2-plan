from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from steuerreport_v2 import __version__
from steuerreport_v2.contracts.admin import (
    AdminSetting,
    AdminSettingDeleteResult,
    AdminSettingWrite,
    AdminStatus,
    ApiKeyWrite,
    ApiKeyWriteResult,
    CexCredentialWrite,
    CexCredentialWriteResult,
    V1CexCredentialTakeoverReport,
    V1CexCredentialTakeoverRequest,
    V1CexCredentialTakeoverResult,
)
from steuerreport_v2.contracts.ai import (
    AiTask,
    AiTaskCreate,
    AiTaskDeleteResult,
    LocalAiAssetFifoCorrectionStatus,
    LocalAiWalletFifoProvenanceStatus,
    LocalAiYearPackageQaStatus,
)
from steuerreport_v2.contracts.audit import AuditExport, ElsterPrepExport
from steuerreport_v2.contracts.binance_earn import BinanceCapitalWithdrawalPreview, BinanceEarnHistoryApiPreview
from steuerreport_v2.contracts.binance_earn_import import (
    BinanceCapitalWithdrawalApiImportRequest,
    BinanceCapitalWithdrawalApiImportResult,
    BinanceEarnApiImportRequest,
    BinanceEarnApiImportResult,
    BinanceEarnHarvestImportRequest,
    BinanceEarnHarvestImportResult,
)
from steuerreport_v2.contracts.bitget import BitgetWithdrawalPreview
from steuerreport_v2.contracts.bitget_import import BitgetWithdrawalApiImportRequest, BitgetWithdrawalApiImportResult
from steuerreport_v2.contracts.blockpit_solana import (
    BlockpitSolanaPreflightReport,
    BlockpitSolanaPriceProbeRequest,
    BlockpitSolanaPriceProbeResult,
)
from steuerreport_v2.contracts.common import ApiMessage, ApiResponse
from steuerreport_v2.contracts.cockpit import CockpitSummary
from steuerreport_v2.contracts.coverage import ImportCoverageSummary
from steuerreport_v2.contracts.derivatives import (
    DerivativeLine,
    DerivativeRunResult,
    DerivativeRunSummary,
)
from steuerreport_v2.contracts.divorce import DivorceEqualizationSummary
from steuerreport_v2.contracts.events import CanonicalEvent
from steuerreport_v2.contracts.exports import (
    ExportPackage,
    ExportPackageDeleteResult,
    ExportReadiness,
    ExportResult,
    PdfExportRequest,
)
from steuerreport_v2.contracts.flows import FlowEntry, NetFlowSummary
from steuerreport_v2.contracts.imports import (
    CsvImportPreview,
    ImportAssistantExecuteResult,
    ImportAssistantPreview,
    ImportAssistantRequest,
    ImportBatch,
    ImportBatchCreate,
    RawObject,
)
from steuerreport_v2.contracts.import_policy import ImportPolicyAudit
from steuerreport_v2.contracts.jup_perps import JupPerpsPreview
from steuerreport_v2.contracts.jupiter import (
    JupiterTokenMetadataCacheResult,
    JupiterTokenMetadataRefreshResult,
    JupiterTokenRiskReviewResult,
    JupiterTokenSearchResult,
)
from steuerreport_v2.contracts.ledger import BalanceLedgerEntry, BalancePosition
from steuerreport_v2.contracts.parity import (
    HntFifoProvenanceReport,
    HntWalletBridgeReport,
    V1ParityDecisionCreate,
    V1ParityDecisionResult,
    V1ParityDiagnostics,
    V1ParityGroupDetail,
    V1ParityReleaseReadiness,
    V1ParitySummary,
    V1ReferenceDeleteResult,
    V1ReferenceMetric,
    V1ReferenceMetricCreate,
    V1WisoReferenceImportRequest,
    V1WisoReferenceImportResult,
)
from steuerreport_v2.contracts.parser_preflight import ParserPreflightReport
from steuerreport_v2.contracts.portfolio import (
    PortfolioAsOfSnapshot,
    PortfolioFiatDepositReport,
    PortfolioReconciliationRefreshResult,
    PortfolioReconciliationReport,
    PortfolioSeparationReport,
    PortfolioSnapshot,
    PortfolioSourceOverview,
    PortfolioTokenRiskReport,
    PortfolioValuationAuditReport,
    PortfolioWalletHistoryImportRequest,
    PortfolioWalletHistoryImportResult,
)
from steuerreport_v2.contracts.prices import (
    CurrentPortfolioPriceBackfillRequest,
    CurrentPortfolioPriceBackfillResult,
    ExternalPriceBackfillRequest,
    ExternalPriceBackfillResult,
    PriceCsvImportRequest,
    PriceCsvImportResult,
    PriceCsvPreview,
    PriceDeleteResult,
    PricePoint,
    PricePointCreate,
    PriceWriteResult,
    V1FxCacheImportPreview,
    V1FxCacheImportRequest,
    V1FxCacheImportResult,
)
from steuerreport_v2.contracts.pipeline import (
    DemoSeedResult,
    ImportDeleteResult,
    ImportRunResult,
    PipelineResult,
)
from steuerreport_v2.contracts.review import (
    ReviewDecision,
    ReviewDecisionCreate,
    ReviewDecisionSuggestion,
    ReviewEvidenceTraceCanonicalizeRequest,
    ReviewEvidenceTraceCanonicalizeResult,
    ReviewEvidenceTraceReport,
    ReviewGate,
    ReviewTaskSummary,
)
from steuerreport_v2.contracts.reports import ReportCenterStatus
from steuerreport_v2.contracts.solscan import (
    SolanaRpcProbeRequest,
    SolanaRpcProbeResult,
    SolscanEvidenceTraceReport,
    SolscanTokenPreflightReport,
)
from steuerreport_v2.contracts.sources import (
    BinanceEarnHistoryPreflightReport,
    BinanceReconciliationEvidenceReport,
    SourceConnectorDiagnosticsReport,
    SourceDetail,
    SourceOverview,
    SourceReconciliationBreakdown,
)
from steuerreport_v2.contracts.tax import (
    TaxLine,
    TaxHoldingPeriodReport,
    TaxLot,
    TaxRunResult,
    TaxRunSummary,
    TaxUnmatchedDisposal,
)
from steuerreport_v2.contracts.tax_methodology import (
    TaxBmfActionPlan,
    TaxBmfClosureBacklogReport,
    TaxBmfFilingReadinessReport,
    TaxBmfFilingReadinessSnapshot,
    TaxRewardBmfRecheckReport,
    TaxMethodologyReport,
    TaxMethodologySummary,
    TaxYearComplianceStatus,
)
from steuerreport_v2.contracts.tax_wallet_fifo import (
    LegacyHeliumOverviewReport,
    WalletFifoGapDiagnosisReport,
    WalletFifoCexDepositTransferEvidenceReport,
    WalletFifoCexExchangeOutflowAnchorFeasibilityReport,
    WalletFifoCexExchangeOutflowEvidenceReport,
    WalletFifoCexExchangeOutflowReviewDecisionCreate,
    WalletFifoCexExchangeOutflowReviewDecisionResult,
    WalletFifoCexSenderOwnershipReviewDecisionCreate,
    WalletFifoCexSenderOwnershipReviewDecisionResult,
    WalletFifoCexSenderOwnershipSummaryReport,
    WalletFifoExchangeEvidenceGapReport,
    WalletFifoOriginTraceReport,
    WalletFifoOpeningBalanceEvidenceReport,
    WalletFifoPreviewReport,
    WalletFifoProvenanceEventReport,
    WalletFifoProvenancePriorityReport,
    WalletFifoYearProvenanceClosureReport,
    WalletFifoRawProvenanceBreakdownReport,
    WalletFifoSolanaProvenanceBatchLatest,
    WalletFifoSolanaProvenanceClassificationReport,
    WalletFifoSolanaRawBmfEvidenceDrilldownReport,
    WalletFifoSolanaRawBmfEvidenceSummaryReport,
    WalletFifoSolanaRawProvenancePriorityReport,
    WalletFifoSolanaRawProvenanceSenderSummaryReport,
    WalletFifoSolanaSenderClusterOutflowReport,
    WalletFifoSolanaSenderClusterReport,
    WalletFifoSolanaOriginTraceReport,
    WalletFifoWithdrawalGapReport,
)
from steuerreport_v2.contracts.tax_years import (
    TaxDeclarationGuide,
    TaxExternalInflowReport,
    TaxIncomeReport,
    TaxPaymentOverview,
    TaxYearBmfClosureAppendix,
    TaxYearAssetFifoCorrectionReviewReport,
    TaxYearAssetFifoDrilldown,
    TaxYearAssetFifoPlausibilityReport,
    TaxYearDetail,
    TaxYearDriverReport,
    TaxYearEvidenceReport,
    TaxYearFilingSummary,
    TaxYearTurnoverAudit,
    TaxYearsTurnoverAuditSummary,
    TaxSolanaProgramIncomeReview,
    TaxSolanaStablecoinFxReview,
    TaxSolanaStablecoinSwapContextReview,
    TaxStablecoinFifoReview,
    TaxStablecoinQuoteLegReview,
    TaxYearsSummary,
)
from steuerreport_v2.contracts.transfers import TransferCandidateReport
from steuerreport_v2.contracts.valuation import (
    PriceCoverageReport,
    PriceQualityBinanceNormalizerReport,
    PriceGapDecisionCreate,
    PriceGapDecisionResult,
    PriceQualityDecisionCreate,
    PriceQualityDecisionResult,
    PriceQualityEventQuoteEvidenceReport,
    PriceQualityGroupDetail,
    PriceQualityManualReviewReport,
    PriceQualityReport,
    PriceQualitySolscanSignatureReport,
    PriceQualityStablecoinFxReport,
    PriceRequirementReport,
)
from steuerreport_v2.contracts.wallet_monthly import WalletMonthlyPreflightReport
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.admin import AdminService
from steuerreport_v2.domain.ai import AiService
from steuerreport_v2.domain.audit import AuditService
from steuerreport_v2.domain.binance_earn import BinanceEarnHistoryService
from steuerreport_v2.domain.bitget import BitgetWalletHistoryService
from steuerreport_v2.domain.blockpit_solana_preflight import BlockpitSolanaPreflightService
from steuerreport_v2.domain.cockpit import CockpitService
from steuerreport_v2.domain.derivatives import DerivativesManager
from steuerreport_v2.domain.divorce import DivorceEqualizationService
from steuerreport_v2.domain.exports import ExportService
from steuerreport_v2.domain.external_price_backfill import ExternalPriceBackfillService
from steuerreport_v2.domain.flows import FlowService
from steuerreport_v2.domain.import_coverage import ImportCoverageService
from steuerreport_v2.domain.import_policy import ImportPolicyService
from steuerreport_v2.domain.import_assistant import ImportAssistantService
from steuerreport_v2.domain.jup_perps import JupPerpsPreviewService
from steuerreport_v2.domain.jupiter import JupiterTokenService
from steuerreport_v2.domain.parity import V1ParityService
from steuerreport_v2.domain.parser_preflight import ParserPreflightService
from steuerreport_v2.domain.price_csv_importer import PriceCsvImporter
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.reports import ReportCenterService
from steuerreport_v2.domain.solscan_preflight import SolscanPreflightService
from steuerreport_v2.domain.sources import SourceService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_methodology import TaxMethodologyService
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService
from steuerreport_v2.domain.tax_years import TaxYearService
from steuerreport_v2.domain.transfers import TransferCandidateService
from steuerreport_v2.domain.valuation import PriceCoverageService, PriceQualityService
from steuerreport_v2.domain.v1_fx_cache_importer import V1FxCacheImporter
from steuerreport_v2.domain.wallet_monthly_preflight import WalletMonthlyPreflightService
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.file_raw_importer import FileRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.importers.source_profiles import list_profiles
from steuerreport_v2.importers.wiso_reference_importer import WisoReferenceImporter
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder


def build_health_payload(db: DuckDbStore) -> dict:
    return {
        "app_version": __version__,
        **db.health(),
    }


def _import_preview_warnings(preview: CsvImportPreview, content_field: str) -> list[dict[str, str]]:
    warnings = []
    if preview.missing_required_groups:
        warnings.append(
            {
                "code": "missing_required_columns",
                "message": (
                    "Pflichtgruppen fehlen: "
                    + ", ".join(preview.missing_required_groups)
                ),
                "field": content_field,
            }
        )
    if preview.row_count == 0:
        warnings.append(
            {
                "code": "empty_import_file",
                "message": "Die Datei enthaelt keine Datenzeilen.",
                "field": content_field,
            }
        )
    if preview.duplicate_batch_id is not None:
        warnings.append(
            {
                "code": "duplicate_import",
                "message": (
                    "Diese Datei wurde fuer diese Quelle bereits importiert: "
                    + preview.duplicate_batch_id
                ),
                "field": content_field,
            }
        )
    return warnings


def _import_preview_errors(preview: CsvImportPreview, content_field: str) -> list[dict[str, str]]:
    return [
        warning
        for warning in _import_preview_warnings(preview, content_field)
        if warning["code"] in {"missing_required_columns", "empty_import_file"}
    ]


def create_app(store: DuckDbStore | None = None) -> FastAPI:
    app = FastAPI(title="Steuerreport V2", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    db = store or DuckDbStore()

    @app.get("/api/v1/health")
    def health() -> ApiResponse[dict]:
        return ApiResponse(data=build_health_payload(db))

    @app.get("/api/v1/admin/database")
    def database_status() -> ApiResponse[dict]:
        return ApiResponse(data=db.health())

    @app.get("/api/v1/admin/status")
    def admin_status() -> ApiResponse[AdminStatus]:
        return ApiResponse(data=AdminService(db).status())

    @app.get("/api/v1/cockpit/summary")
    def cockpit_summary() -> ApiResponse[CockpitSummary]:
        return ApiResponse(data=CockpitService(db).summary())

    @app.get("/api/v1/admin/settings")
    def list_admin_settings() -> ApiResponse[list[AdminSetting]]:
        return ApiResponse(data=AdminService(db).list_settings())

    @app.patch("/api/v1/admin/settings")
    def update_admin_setting(payload: AdminSettingWrite) -> ApiResponse[AdminSetting]:
        try:
            return ApiResponse(data=AdminService(db).upsert_setting(payload))
        except ValueError as exc:
            return ApiResponse(
                status="error",
                errors=[
                    {
                        "code": "invalid_setting_json",
                        "message": str(exc),
                        "field": "value_json",
                    }
                ],
            )

    @app.delete("/api/v1/admin/settings/{key}")
    def delete_admin_setting(key: str) -> ApiResponse[AdminSettingDeleteResult]:
        deleted = AdminService(db).delete_setting(key)
        warnings = []
        if not deleted:
            warnings.append(
                {
                    "code": "admin_setting_not_found",
                    "message": f"Admin-Setting nicht gefunden: {key}",
                    "field": "key",
                }
            )
        return ApiResponse(
            status="warning" if warnings else "ok",
            data=AdminSettingDeleteResult(key=key, deleted=deleted),
            warnings=warnings,
        )

    @app.post("/api/v1/admin/cex-credentials")
    def save_cex_credentials(payload: CexCredentialWrite) -> ApiResponse[CexCredentialWriteResult]:
        try:
            result = AdminService(db).save_cex_credentials(payload)
        except ValueError as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="cex_credentials_save_failed",
                        message=str(exc),
                        field="connector_id",
                    )
                ],
            )
        return ApiResponse(
            status="warning" if result.status == "warning" else "ok",
            data=result,
            warnings=[
                ApiMessage(
                    code="cex_credentials_saved_but_not_usable",
                    message=result.message,
                    field="connector_id",
                )
            ]
            if result.status == "warning"
            else [],
        )

    @app.post("/api/v1/admin/jupiter/api-key")
    def save_jupiter_api_key(payload: ApiKeyWrite) -> ApiResponse[ApiKeyWriteResult]:
        try:
            result = AdminService(db).save_jupiter_api_key(payload)
        except ValueError as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="jupiter_api_key_save_failed",
                        message=str(exc),
                        field="api_key",
                    )
                ],
            )
        return ApiResponse(data=result)

    @app.get("/api/v1/sources/jupiter/tokens/search")
    def jupiter_token_search(query: str) -> ApiResponse[JupiterTokenSearchResult]:
        try:
            result = JupiterTokenService(db).search(query)
        except ValueError as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="jupiter_token_search_failed",
                        message=str(exc),
                        field="query",
                    )
                ],
            )
        except Exception as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="jupiter_token_search_request_failed",
                        message=f"{type(exc).__name__}: {exc}",
                        field="query",
                    )
                ],
            )
        return ApiResponse(
            status="warning" if result.status != "ok" else "ok",
            data=result,
            warnings=[
                ApiMessage(
                    code=result.status,
                    message="Jupiter API-Key fehlt oder ist nicht lesbar.",
                    field="api_key",
                )
            ]
            if result.status != "ok"
            else [],
        )

    @app.get("/api/v1/sources/jupiter/tokens/metadata-cache")
    def jupiter_token_metadata_cache(limit: int = 200) -> ApiResponse[JupiterTokenMetadataCacheResult]:
        try:
            result = JupiterTokenService(db).metadata_cache(limit=limit)
        except Exception as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="jupiter_token_metadata_cache_failed",
                        message=f"{type(exc).__name__}: {exc}",
                    )
                ],
            )
        return ApiResponse(data=result)

    @app.post("/api/v1/sources/jupiter/tokens/metadata-cache/refresh")
    def refresh_jupiter_token_metadata_cache(
        limit: int = 50,
        force: bool = False,
    ) -> ApiResponse[JupiterTokenMetadataRefreshResult]:
        try:
            result = JupiterTokenService(db).refresh_metadata_cache(limit=limit, force=force)
        except ValueError as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="jupiter_token_metadata_refresh_failed",
                        message=str(exc),
                    )
                ],
            )
        except Exception as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="jupiter_token_metadata_refresh_request_failed",
                        message=f"{type(exc).__name__}: {exc}",
                    )
                ],
            )
        return ApiResponse(
            status="warning" if result.status != "ok" else "ok",
            data=result,
        )

    @app.get("/api/v1/sources/jupiter/tokens/risk-review")
    def jupiter_token_risk_review(
        risk_status: str = "spam_review",
        limit: int = 200,
    ) -> ApiResponse[JupiterTokenRiskReviewResult]:
        try:
            result = JupiterTokenService(db).risk_review(risk_status=risk_status, limit=limit)
        except ValueError as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="jupiter_token_risk_review_failed",
                        message=str(exc),
                        field="risk_status",
                    )
                ],
            )
        except Exception as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="jupiter_token_risk_review_request_failed",
                        message=f"{type(exc).__name__}: {exc}",
                    )
                ],
            )
        return ApiResponse(data=result)

    @app.get("/api/v1/admin/cex-credentials/v1-takeover")
    def v1_cex_credentials_takeover_report() -> ApiResponse[V1CexCredentialTakeoverReport]:
        return ApiResponse(data=AdminService(db).v1_cex_credential_takeover_report())

    @app.post("/api/v1/admin/cex-credentials/v1-takeover")
    def import_v1_cex_credentials(
        payload: V1CexCredentialTakeoverRequest | None = None,
    ) -> ApiResponse[V1CexCredentialTakeoverResult]:
        try:
            result = AdminService(db).import_v1_cex_credentials(
                connectors=payload.connectors if payload is not None else None,
            )
        except ValueError as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="v1_cex_credentials_takeover_failed",
                        message=str(exc),
                        field="connectors",
                    )
                ],
            )
        return ApiResponse(
            status="warning" if result.skipped else "ok",
            data=result,
            warnings=[
                ApiMessage(
                    code="v1_cex_credentials_not_transferable",
                    message=f"{len(result.skipped)} Connector(en) konnten nicht aus V1 uebernommen werden.",
                    field="connectors",
                )
            ]
            if result.skipped
            else [],
        )

    @app.get("/api/v1/contracts/event-types")
    def event_types() -> ApiResponse[dict]:
        return ApiResponse(
            data={
                "event_types": [
                    "trade",
                    "transfer",
                    "fee",
                    "reward",
                    "income",
                    "staking",
                    "mining",
                    "derivative",
                    "unknown",
                ]
            }
        )

    @app.get("/api/v1/import/profiles")
    def import_profiles() -> ApiResponse[list[dict[str, object]]]:
        return ApiResponse(data=list_profiles())

    @app.get("/api/v1/import/coverage")
    def import_coverage(
        root_path: str = "/workspace/steuerreport/usertransfer",
        limit: int = 80,
        max_seconds: float = 8.0,
    ) -> ApiResponse[ImportCoverageSummary]:
        return ApiResponse(
            data=ImportCoverageService(db).scan(
                root_path=root_path,
                limit=limit,
                max_seconds=max_seconds,
            )
        )

    @app.get("/api/v1/import/policy/audit")
    def import_policy_audit(
        root_path: str = "/workspace/steuerreport/usertransfer",
    ) -> ApiResponse[ImportPolicyAudit]:
        return ApiResponse(data=ImportPolicyService(db).audit(root_path))

    @app.get("/api/v1/import/parser-preflight")
    def parser_preflight(
        root_path: str = "/workspace/steuerreport/usertransfer",
        limit: int = 20,
    ) -> ApiResponse[ParserPreflightReport]:
        return ApiResponse(
            data=ParserPreflightService(CsvRawImporter(db)).inspect(
                root_path=root_path,
                limit=limit,
            )
        )

    @app.get("/api/v1/import/blockpit-solana/preflight")
    def blockpit_solana_preflight(
        file_path: str = "/workspace/steuerreport/usertransfer/blockpit/blockpit 09052026 Transactions.csv",
        integration: str = "Solana",
        max_year: int = 2024,
        account: str = "Solana",
        price_config_path: str = "/workspace/steuerreport-v2-plan/configs/crypto_price_sources.json",
    ) -> ApiResponse[BlockpitSolanaPreflightReport]:
        return ApiResponse(
            data=BlockpitSolanaPreflightService(db).inspect(
                file_path=file_path,
                integration=integration,
                max_year=max_year,
                account=account,
                price_config_path=price_config_path,
            )
        )

    @app.post("/api/v1/import/blockpit-solana/price-probe")
    def blockpit_solana_price_probe(
        payload: BlockpitSolanaPriceProbeRequest,
    ) -> ApiResponse[BlockpitSolanaPriceProbeResult]:
        return ApiResponse(
            data=BlockpitSolanaPreflightService(db).probe_historical_prices(
                file_path=payload.file_path,
                integration=payload.integration,
                max_year=payload.max_year,
                account=payload.account,
                price_config_path=payload.price_config_path,
                v1_fx_db_path=payload.v1_fx_db_path,
                provider=payload.provider,
                assets_filter=payload.assets,
                max_requests=payload.max_requests,
                timeout_seconds=payload.timeout_seconds,
                confidence=payload.confidence,
                dry_run=payload.dry_run,
            )
        )

    @app.get("/api/v1/import/solscan/token-preflight")
    def solscan_token_preflight(
        file_path: str = "/workspace/steuerreport/usertransfer/legacy_daten/Steuer-2022/export-solscan.csv",
        blockpit_file_path: str = "/workspace/steuerreport/usertransfer/blockpit/blockpit 09052026 Transactions.csv",
        wallet: str = "G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY",
        asset: str = "IOT",
        token_address: str = "iotEVVZLEywoTn1QdwNPddxPWszn3zFhEot3MfL9fns",
        max_year: int = 2024,
    ) -> ApiResponse[SolscanTokenPreflightReport]:
        return ApiResponse(
            data=SolscanPreflightService().inspect_token(
                file_path=file_path,
                blockpit_file_path=blockpit_file_path,
                wallet=wallet,
                asset=asset,
                token_address=token_address,
                max_year=max_year,
            )
        )

    @app.post("/api/v1/import/solscan/rpc-probe")
    def solscan_rpc_probe(
        payload: SolanaRpcProbeRequest,
    ) -> ApiResponse[SolanaRpcProbeResult]:
        return ApiResponse(
            data=SolscanPreflightService().probe_missing_signatures_rpc(payload)
        )

    @app.get("/api/v1/import/solscan/evidence-trace")
    def solscan_evidence_trace(
        file_path: str = "/workspace/steuerreport/usertransfer/legacy_daten/Steuer-2022/export-solscan.csv",
        blockpit_file_path: str = "/workspace/steuerreport/usertransfer/blockpit/blockpit 09052026 Transactions.csv",
        wallet: str = "G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY",
        asset: str = "IOT",
        token_address: str = "iotEVVZLEywoTn1QdwNPddxPWszn3zFhEot3MfL9fns",
        max_year: int = 2024,
    ) -> ApiResponse[SolscanEvidenceTraceReport]:
        return ApiResponse(
            data=SolscanPreflightService().evidence_trace(
                file_path=file_path,
                blockpit_file_path=blockpit_file_path,
                wallet=wallet,
                asset=asset,
                token_address=token_address,
                max_year=max_year,
            )
        )

    @app.get("/api/v1/import/solscan/helium-reward-evidence")
    def solscan_helium_reward_evidence(
        artifact_path: str | None = None,
    ) -> ApiResponse[dict[str, object]]:
        if artifact_path is None:
            return ApiResponse(data=SolscanPreflightService().helium_reward_evidence())
        return ApiResponse(data=SolscanPreflightService().helium_reward_evidence(artifact_path=artifact_path))

    @app.get("/api/v1/import/wallet-monthly/preflight")
    def wallet_monthly_preflight(
        file_path: str = "/workspace/steuerreport/usertransfer/Wallet.G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY-month.csv",
        wallet: str = "G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY",
        asset: str = "IOT",
        cutoff_at: str = "2024-02-23T21:01:15",
        required_quantity: Decimal = Decimal("339834.071782"),
    ) -> ApiResponse[WalletMonthlyPreflightReport]:
        return ApiResponse(
            data=WalletMonthlyPreflightService().inspect(
                file_path=file_path,
                wallet=wallet,
                asset=asset,
                cutoff_at=cutoff_at,
                required_quantity=required_quantity,
            )
        )

    @app.get("/api/v1/import/jup-perps/preview")
    def jup_perps_preview(
        file_path: str = "/workspace/steuerreport/usertransfer/jup/G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY.csv",
        v1_fx_db_path: str = "/root/.local/share/steuerreport/steuerreport.db",
        sample_limit: int = 20,
    ) -> ApiResponse[JupPerpsPreview]:
        return ApiResponse(
            data=JupPerpsPreviewService().preview(
                file_path=file_path,
                v1_fx_db_path=v1_fx_db_path,
                sample_limit=sample_limit,
            )
        )

    @app.post("/api/v1/import/batches")
    def create_import_batch(payload: ImportBatchCreate) -> ApiResponse[ImportBatch]:
        return ApiResponse(data=db.create_import_batch(payload))

    @app.get("/api/v1/import/batches")
    def list_import_batches() -> ApiResponse[list[ImportBatch]]:
        return ApiResponse(data=db.list_import_batches())

    @app.get("/api/v1/import/batches/{batch_id}")
    def get_import_batch(batch_id: str) -> ApiResponse[ImportBatch]:
        batch = db.get_import_batch(batch_id)
        if batch is None:
            return ApiResponse(
                status="error",
                errors=[
                    {
                        "code": "import_batch_not_found",
                        "message": f"Import-Batch nicht gefunden: {batch_id}",
                        "field": "batch_id",
                    }
                ],
            )
        return ApiResponse(data=batch)

    @app.delete("/api/v1/import/batches/{batch_id}")
    def delete_import_batch(batch_id: str) -> ApiResponse[ImportDeleteResult]:
        result = PipelineService(db).delete_import_and_rebuild(batch_id)
        warnings = []
        if not result.deleted:
            warnings.append(
                {
                    "code": "import_batch_not_found",
                    "message": f"Import-Batch nicht gefunden: {batch_id}",
                    "field": "batch_id",
                }
            )
        return ApiResponse(
            status="warning" if warnings else "ok",
            data=result,
            warnings=warnings,
        )

    @app.get("/api/v1/raw/objects")
    def list_raw_objects(
        batch_id: str | None = None,
        limit: int = 500,
    ) -> ApiResponse[list[RawObject]]:
        return ApiResponse(data=db.list_raw_objects(batch_id=batch_id, limit=limit))

    @app.get("/api/v1/events/canonical")
    def list_canonical_events(
        batch_id: str | None = None,
    ) -> ApiResponse[list[CanonicalEvent]]:
        return ApiResponse(data=db.list_canonical_events(batch_id=batch_id))

    @app.get("/api/v1/import/batches/{batch_id}/trace.json")
    def download_import_batch_trace(batch_id: str) -> Response:
        batch = db.get_import_batch(batch_id)
        payload = {
            "batch": batch.model_dump(mode="json") if batch is not None else None,
            "raw_objects": [
                item.model_dump(mode="json") for item in db.list_raw_objects(batch_id=batch_id, limit=None)
            ],
            "canonical_events": [
                item.model_dump(mode="json")
                for item in db.list_canonical_events(batch_id=batch_id)
            ],
        }
        return Response(
            content=json.dumps(payload, indent=2, ensure_ascii=False),
            media_type="application/json",
            headers={
                "Content-Disposition": f"attachment; filename=import-trace-{batch_id}.json"
            },
        )

    @app.post("/api/v1/import/csv/raw")
    def import_csv_raw(payload: dict) -> ApiResponse[ImportBatch]:
        importer = CsvRawImporter(db)
        preview = importer.preview_text(
            source=str(payload["source"]),
            filename=str(payload["filename"]),
            content=str(payload["content"]),
        )
        errors = _import_preview_errors(preview, "content")
        if errors:
            return ApiResponse(status="error", errors=errors)
        batch = importer.import_text(
            source=str(payload["source"]),
            filename=str(payload["filename"]),
            content=str(payload["content"]),
        )
        warnings = _import_preview_warnings(preview, "content")
        return ApiResponse(
            status="warning" if warnings else "ok",
            data=batch,
            warnings=warnings,
        )

    @app.post("/api/v1/import/csv/preview")
    def preview_csv_import(payload: dict) -> ApiResponse[CsvImportPreview]:
        preview = CsvRawImporter(db).preview_text(
            source=str(payload["source"]),
            filename=str(payload["filename"]),
            content=str(payload["content"]),
        )
        warnings = _import_preview_warnings(preview, "content")
        return ApiResponse(
            status="warning" if warnings else "ok",
            data=preview,
            warnings=warnings,
        )

    @app.post("/api/v1/import/file/preview")
    def preview_file_import(payload: dict) -> ApiResponse[CsvImportPreview]:
        preview = FileRawImporter(CsvRawImporter(db)).preview_base64(
            source=str(payload["source"]),
            filename=str(payload["filename"]),
            content_base64=str(payload["content_base64"]),
            sheet_name=payload.get("sheet_name"),
        )
        warnings = _import_preview_warnings(preview, "content_base64")
        return ApiResponse(
            status="warning" if warnings else "ok",
            data=preview,
            warnings=warnings,
        )

    @app.post("/api/v1/import/file/raw")
    def import_file_raw(payload: dict) -> ApiResponse[ImportBatch]:
        importer = FileRawImporter(CsvRawImporter(db))
        preview = importer.preview_base64(
            source=str(payload["source"]),
            filename=str(payload["filename"]),
            content_base64=str(payload["content_base64"]),
            sheet_name=payload.get("sheet_name"),
        )
        errors = _import_preview_errors(preview, "content_base64")
        if errors:
            return ApiResponse(status="error", errors=errors)
        batch = importer.import_base64(
            source=str(payload["source"]),
            filename=str(payload["filename"]),
            content_base64=str(payload["content_base64"]),
            sheet_name=payload.get("sheet_name"),
        )
        warnings = _import_preview_warnings(preview, "content_base64")
        return ApiResponse(
            status="warning" if warnings else "ok",
            data=batch,
            warnings=warnings,
        )

    @app.post("/api/v1/import/assistant/preview")
    def preview_import_assistant(payload: ImportAssistantRequest) -> ApiResponse[ImportAssistantPreview]:
        preview = ImportAssistantService(db).preview(payload)
        return ApiResponse(
            status="ok" if preview.can_execute else "warning",
            data=preview,
            warnings=[
                {"code": "import_assistant_warning", "message": warning, "field": "content"}
                for warning in preview.warnings
            ],
        )

    @app.post("/api/v1/import/assistant/execute")
    def execute_import_assistant(payload: ImportAssistantRequest) -> ApiResponse[ImportAssistantExecuteResult]:
        try:
            return ApiResponse(data=ImportAssistantService(db).execute(payload))
        except ValueError as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="import_assistant_blocked",
                        message=str(exc),
                        field="content",
                    )
                ],
            )

    @app.post("/api/v1/import/batches/{batch_id}/normalize")
    def normalize_import_batch(batch_id: str) -> ApiResponse[dict]:
        _, report = RawNormalizer(db).normalize_batch_with_report(batch_id)
        warnings = []
        if report.skipped_raw_objects:
            warnings.append(
                {
                    "code": "raw_objects_skipped",
                    "message": (
                        f"{report.skipped_raw_objects} Rohzeilen konnten nicht "
                        "normalisiert werden."
                    ),
                    "field": "batch_id",
                }
            )
        return ApiResponse(
            status="warning" if warnings else "ok",
            data={
                "batch_id": report.batch_id,
                "raw_objects": report.raw_objects,
                "created_events": report.created_events,
                "skipped_raw_objects": report.skipped_raw_objects,
            },
            warnings=warnings,
        )

    @app.post("/api/v1/import/batches/{batch_id}/run")
    def run_import_pipeline(batch_id: str) -> ApiResponse[ImportRunResult]:
        result = PipelineService(db).rebuild_after_import(batch_id)
        warnings = []
        if result.skipped_raw_objects:
            warnings.append(
                {
                    "code": "raw_objects_skipped",
                    "message": (
                        f"{result.skipped_raw_objects} Rohzeilen konnten nicht "
                        "normalisiert werden."
                    ),
                    "field": "batch_id",
                }
            )
        return ApiResponse(
            status="warning" if warnings else "ok",
            data=result,
            warnings=warnings,
        )

    @app.post("/api/v1/ledger/balances/rebuild")
    def rebuild_balance_ledger() -> ApiResponse[list[BalanceLedgerEntry]]:
        return ApiResponse(data=BalanceLedgerBuilder(db).rebuild())

    @app.get("/api/v1/ledger/balances")
    def list_balance_positions() -> ApiResponse[list[BalancePosition]]:
        return ApiResponse(data=BalanceLedgerBuilder(db).positions())

    @app.get("/api/v1/transfers/candidates")
    def transfer_candidates(
        asset: str | None = None,
        limit: int = 200,
    ) -> ApiResponse[TransferCandidateReport]:
        return ApiResponse(data=TransferCandidateService(db).candidates(asset=asset, limit=limit))

    @app.post("/api/v1/prices")
    def add_price_point(payload: PricePointCreate) -> ApiResponse[PriceWriteResult]:
        price = db.add_price_point(payload)
        pipeline = PipelineService(db).rebuild_all()
        return ApiResponse(data=PriceWriteResult(price=price, pipeline=pipeline))

    @app.get("/api/v1/prices")
    def list_price_points(limit: int = 500) -> ApiResponse[list[PricePoint]]:
        return ApiResponse(data=db.list_price_points(limit=limit))

    @app.get("/api/v1/prices/latest")
    def list_latest_price_points() -> ApiResponse[list[PricePoint]]:
        return ApiResponse(data=db.list_latest_price_points())

    @app.post("/api/v1/prices/import/csv/preview")
    def preview_price_csv(payload: PriceCsvImportRequest) -> ApiResponse[PriceCsvPreview]:
        preview = PriceCsvImporter().preview(payload.content, payload.default_source)
        return ApiResponse(status="ok" if preview.can_import else "warning", data=preview)

    @app.post("/api/v1/prices/import/csv")
    def import_price_csv(payload: PriceCsvImportRequest) -> ApiResponse[PriceCsvImportResult]:
        preview, prices = PriceCsvImporter().to_price_points(
            payload.content,
            payload.default_source,
        )
        if not preview.can_import:
            return ApiResponse(
                status="error",
                data=PriceCsvImportResult(imported_prices=0, preview=preview),
                errors=[
                    {
                        "code": "invalid_price_csv",
                        "message": "Preis-CSV enthaelt ungueltige oder fehlende Werte.",
                        "field": "content",
                    }
                ],
            )
        db.add_price_points(prices)
        pipeline = PipelineService(db).rebuild_all()
        return ApiResponse(
            data=PriceCsvImportResult(
                imported_prices=len(prices),
                preview=preview,
                pipeline=pipeline,
            )
        )

    @app.post("/api/v1/prices/import/v1-fx-cache/preview")
    def preview_v1_fx_cache_import(
        payload: V1FxCacheImportRequest,
    ) -> ApiResponse[V1FxCacheImportPreview]:
        preview = V1FxCacheImporter(db).preview(payload.db_path)
        return ApiResponse(
            status="ok" if preview.importable_count else "warning",
            data=preview,
        )

    @app.post("/api/v1/prices/import/v1-fx-cache")
    def import_v1_fx_cache(
        payload: V1FxCacheImportRequest,
    ) -> ApiResponse[V1FxCacheImportResult]:
        preview, prices = V1FxCacheImporter(db).to_price_points(
            payload.db_path,
            payload.confidence,
        )
        if not prices:
            return ApiResponse(
                status="warning",
                data=V1FxCacheImportResult(imported_prices=0, preview=preview),
                warnings=[
                    {
                        "code": "no_v1_fx_cache_matches",
                        "message": "Keine passenden V1-FX-Cache-Preise fuer offene V2-Preisbedarfe gefunden.",
                        "field": "db_path",
                    }
                ],
            )
        db.add_price_points(prices)
        pipeline = PipelineService(db).rebuild_all()
        return ApiResponse(
            data=V1FxCacheImportResult(
                imported_prices=len(prices),
                preview=preview,
                pipeline=pipeline,
            )
        )

    @app.post("/api/v1/prices/backfill/external")
    def backfill_external_prices(
        payload: ExternalPriceBackfillRequest,
    ) -> ApiResponse[ExternalPriceBackfillResult]:
        result = ExternalPriceBackfillService(db).run(
            config_path=payload.config_path,
            v1_fx_db_path=payload.v1_fx_db_path,
            provider=payload.provider,
            assets_filter=payload.assets,
            max_requests=payload.max_requests,
            timeout_seconds=payload.timeout_seconds,
            confidence=payload.confidence,
            dry_run=payload.dry_run,
        )
        return ApiResponse(
            status="ok" if result.dry_run or result.imported_prices else "warning",
            data=result,
        )

    @app.post("/api/v1/prices/backfill/current-portfolio")
    def backfill_current_portfolio_prices(
        payload: CurrentPortfolioPriceBackfillRequest,
    ) -> ApiResponse[CurrentPortfolioPriceBackfillResult]:
        result = ExternalPriceBackfillService(db).run_current_portfolio(
            config_path=payload.config_path,
            provider=payload.provider,
            assets_filter=payload.assets,
            max_requests=payload.max_requests,
            timeout_seconds=payload.timeout_seconds,
            confidence=payload.confidence,
            dry_run=payload.dry_run,
        )
        return ApiResponse(
            status="ok" if result.dry_run or result.imported_prices else "warning",
            data=result,
        )

    @app.get("/api/v1/prices/coverage")
    def price_coverage() -> ApiResponse[PriceCoverageReport]:
        return ApiResponse(data=PriceCoverageService(db).report())

    @app.get("/api/v1/prices/quality")
    def price_quality(limit: int = 120) -> ApiResponse[PriceQualityReport]:
        return ApiResponse(data=PriceQualityService(db).report(limit=limit))

    @app.get("/api/v1/prices/quality/group")
    def price_quality_group(
        asset: str,
        year: int,
        source: str,
        limit: int = 25,
    ) -> ApiResponse[PriceQualityGroupDetail]:
        return ApiResponse(
            data=PriceQualityService(db).group_detail(
                asset=asset,
                year=year,
                source=source,
                limit=limit,
            )
        )

    @app.get("/api/v1/prices/quality/manual-review")
    def price_quality_manual_review(limit: int = 120) -> ApiResponse[PriceQualityManualReviewReport]:
        return ApiResponse(data=PriceQualityService(db).manual_review_report(limit=limit))

    @app.get("/api/v1/prices/quality/stablecoin-fx-review")
    def price_quality_stablecoin_fx_review(limit: int = 120) -> ApiResponse[PriceQualityStablecoinFxReport]:
        return ApiResponse(data=PriceQualityService(db).stablecoin_fx_review(limit=limit))

    @app.get("/api/v1/prices/quality/solscan-signature-review")
    def price_quality_solscan_signature_review(limit: int = 120) -> ApiResponse[PriceQualitySolscanSignatureReport]:
        return ApiResponse(data=PriceQualityService(db).solscan_signature_review(limit=limit))

    @app.get("/api/v1/prices/quality/binance-normalizer-review")
    def price_quality_binance_normalizer_review(limit: int = 120) -> ApiResponse[PriceQualityBinanceNormalizerReport]:
        return ApiResponse(data=PriceQualityService(db).binance_normalizer_review(limit=limit))

    @app.get("/api/v1/prices/quality/event-quote-evidence-review")
    def price_quality_event_quote_evidence_review(limit: int = 120) -> ApiResponse[PriceQualityEventQuoteEvidenceReport]:
        return ApiResponse(data=PriceQualityService(db).event_quote_evidence_review(limit=limit))

    @app.post("/api/v1/prices/quality/decisions")
    def add_price_quality_decision(
        payload: PriceQualityDecisionCreate,
    ) -> ApiResponse[PriceQualityDecisionResult]:
        scope = PriceQualityService.issue_scope(
            asset=payload.asset,
            year=payload.year,
            source=payload.source,
        )
        decision = db.add_review_decision(
            ReviewDecisionCreate(
                decision_type="price_quality",
                scope=scope,
                title=payload.title,
                rationale=payload.rationale,
                evidence_ref=payload.evidence_ref,
                actor="user",
                source="api:/api/v1/prices/quality/decisions",
                payload={
                    "decision_status": payload.decision_status,
                    "asset": payload.asset.upper(),
                    "year": payload.year,
                    "price_source": payload.source,
                    "import_effect": "none",
                },
            )
        )
        return ApiResponse(
            data=PriceQualityDecisionResult(
                decision_id=decision.decision_id,
                scope=scope,
                decision_status=payload.decision_status,
            )
        )

    @app.get("/api/v1/prices/requirements")
    def price_requirements() -> ApiResponse[PriceRequirementReport]:
        return ApiResponse(data=PriceCoverageService(db).requirements())

    @app.post("/api/v1/prices/coverage/decisions")
    def add_price_gap_decision(payload: PriceGapDecisionCreate) -> ApiResponse[PriceGapDecisionResult]:
        decision = db.add_review_decision(
            ReviewDecisionCreate(
                decision_type="price_gap",
                scope=payload.scope,
                title=payload.title,
                rationale=payload.rationale,
                evidence_ref=payload.evidence_ref,
                actor="user",
                source="api:/api/v1/prices/coverage/decisions",
                affected_ids=[payload.scope],
                payload={"decision_status": payload.decision_status},
            )
        )
        return ApiResponse(
            data=PriceGapDecisionResult(
                decision_id=decision.decision_id,
                scope=decision.scope,
                decision_status=payload.decision_status,
            )
        )

    @app.delete("/api/v1/prices/{price_id}")
    def delete_price_point(price_id: str) -> ApiResponse[PriceDeleteResult]:
        deleted = db.delete_price_point(price_id)
        PipelineService(db).rebuild_all()
        warnings = []
        if not deleted:
            warnings.append(
                {
                    "code": "price_not_found",
                    "message": f"Preis-Eintrag nicht gefunden: {price_id}",
                    "field": "price_id",
                }
            )
        return ApiResponse(
            status="warning" if warnings else "ok",
            data=PriceDeleteResult(price_id=price_id, deleted=deleted),
            warnings=warnings,
        )

    @app.get("/api/v1/portfolio/snapshot")
    def portfolio_snapshot() -> ApiResponse[PortfolioSnapshot]:
        return ApiResponse(data=PortfolioService(db).snapshot())

    @app.get("/api/v1/portfolio/valuation-audit")
    def portfolio_valuation_audit() -> ApiResponse[PortfolioValuationAuditReport]:
        return ApiResponse(data=PortfolioService(db).valuation_audit())

    @app.get("/api/v1/portfolio/as-of")
    def portfolio_as_of(as_of: str | None = None) -> ApiResponse[PortfolioAsOfSnapshot]:
        return ApiResponse(data=PortfolioService(db).as_of_snapshot(as_of))

    @app.get("/api/v1/portfolio/sources")
    def portfolio_sources() -> ApiResponse[PortfolioSourceOverview]:
        return ApiResponse(data=PortfolioService(db).source_overview())

    @app.get("/api/v1/portfolio/token-risk")
    def portfolio_token_risk(
        risk_status: str = "all",
        min_value_eur: str = "1",
    ) -> ApiResponse[PortfolioTokenRiskReport]:
        try:
            result = PortfolioService(db).token_risk_report(
                risk_status=risk_status,
                min_value_eur=Decimal(str(min_value_eur)),
            )
        except ValueError as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="portfolio_token_risk_failed",
                        message=str(exc),
                        field="risk_status",
                    )
                ],
            )
        return ApiResponse(data=result)

    @app.get("/api/v1/portfolio/reconciliation")
    def portfolio_reconciliation() -> ApiResponse[PortfolioReconciliationReport]:
        return ApiResponse(data=PortfolioService(db).reconciliation_report())

    @app.post("/api/v1/portfolio/reconciliation/refresh")
    def portfolio_reconciliation_refresh() -> ApiResponse[PortfolioReconciliationRefreshResult]:
        result = PortfolioService(db).refresh_reconciliation_snapshots()
        warnings = [
            ApiMessage(
                code=f"connector_{item.status}",
                message=f"{item.connector_id}: {item.message}",
                field=item.connector_id,
            )
            for item in result.connector_results
            if item.status != "refreshed"
        ]
        if result.imported_snapshots == 0:
            warnings.append(
                ApiMessage(
                    code="no_live_snapshots_imported",
                    message="Keine neuen Live-Snapshots importiert; vorhandene Snapshot-Anker bleiben erhalten.",
                    field="imported_snapshots",
                )
            )
        return ApiResponse(
            status="warning" if warnings else "ok",
            data=result,
            warnings=warnings,
        )

    @app.post("/api/v1/portfolio/jup-wallet/import-history")
    def portfolio_jup_wallet_import_history(
        payload: PortfolioWalletHistoryImportRequest | None = None,
    ) -> ApiResponse[PortfolioWalletHistoryImportResult]:
        return ApiResponse(data=PortfolioService(db).import_jup_wallet_history(payload))

    @app.get("/api/v1/portfolio/separation-report")
    def portfolio_separation_report() -> ApiResponse[PortfolioSeparationReport]:
        return ApiResponse(data=PortfolioService(db).separation_report())

    @app.get("/api/v1/portfolio/fiat-deposits/binance")
    def portfolio_binance_fiat_deposits() -> ApiResponse[PortfolioFiatDepositReport]:
        return ApiResponse(data=PortfolioService(db).fiat_deposit_report(source="binance"))

    @app.get("/api/v1/divorce/equalization-summary")
    def divorce_equalization_summary() -> ApiResponse[DivorceEqualizationSummary]:
        return ApiResponse(data=DivorceEqualizationService(db).summary())

    @app.get("/api/v1/divorce/equalization-summary/valuation-tokens.csv")
    def divorce_equalization_valuation_tokens_csv() -> Response:
        return Response(
            content=DivorceEqualizationService(db).valuation_tokens_csv(),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=divorce-equalization-valuation-tokens.csv"
            },
        )

    @app.get("/api/v1/divorce/equalization-summary/accounts.csv")
    def divorce_equalization_accounts_csv() -> Response:
        return Response(
            content=DivorceEqualizationService(db).accounts_csv(),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=divorce-equalization-accounts.csv"
            },
        )

    @app.get("/api/v1/divorce/equalization-summary/live-reconciliation.csv")
    def divorce_equalization_live_reconciliation_csv() -> Response:
        return Response(
            content=DivorceEqualizationService(db).live_reconciliation_csv(),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=divorce-equalization-live-reconciliation.csv"
            },
        )

    @app.get("/api/v1/divorce/equalization-summary/evidence-package.zip")
    def divorce_equalization_evidence_package_zip() -> Response:
        return Response(
            content=DivorceEqualizationService(db).evidence_package_zip(),
            media_type="application/zip",
            headers={
                "Content-Disposition": "attachment; filename=divorce-equalization-evidence-package.zip"
            },
        )

    @app.get("/api/v1/sources/overview")
    def sources_overview() -> ApiResponse[SourceOverview]:
        return ApiResponse(data=SourceService(db).overview())

    @app.get("/api/v1/sources/connector-diagnostics")
    def sources_connector_diagnostics() -> ApiResponse[SourceConnectorDiagnosticsReport]:
        return ApiResponse(data=SourceService(db).connector_diagnostics())

    @app.get("/api/v1/sources/{source_id}")
    def source_detail(source_id: str) -> ApiResponse[SourceDetail]:
        detail = SourceService(db).detail(source_id)
        if detail is None:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="source_not_found",
                        message=f"Quelle nicht gefunden: {source_id}",
                        field="source_id",
                    )
                ],
            )
        return ApiResponse(data=detail)

    @app.get("/api/v1/sources/{source_id}/reconciliation")
    def source_reconciliation(source_id: str) -> ApiResponse[SourceReconciliationBreakdown]:
        breakdown = SourceService(db).reconciliation_breakdown(source_id)
        if breakdown is None:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="source_not_found",
                        message=f"Quelle nicht gefunden: {source_id}",
                        field="source_id",
                    )
                ],
            )
        return ApiResponse(data=breakdown)

    @app.get("/api/v1/sources/binance/reconciliation/evidence")
    def binance_reconciliation_evidence(
        since: str | None = None,
        assets: str | None = None,
    ) -> ApiResponse[BinanceReconciliationEvidenceReport]:
        since_at = None
        if since:
            since_at = datetime.fromisoformat(since.replace("Z", "+00:00"))
            if since_at.tzinfo is None:
                since_at = since_at.replace(tzinfo=timezone.utc)
        selected_assets = [item.strip().upper() for item in assets.split(",") if item.strip()] if assets else None
        report = SourceService(db).binance_reconciliation_evidence(
            since=since_at,
            assets=selected_assets,
        )
        if report is None:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="source_not_found",
                        message="Binance-Quelle nicht gefunden.",
                        field="source_id",
                    )
                ],
            )
        return ApiResponse(data=report)

    @app.get("/api/v1/sources/binance/earn-history-preflight")
    def binance_earn_history_preflight() -> ApiResponse[BinanceEarnHistoryPreflightReport]:
        return ApiResponse(data=SourceService(db).binance_earn_history_preflight())

    @app.get("/api/v1/sources/binance/earn-history-api-preview")
    def binance_earn_history_api_preview(
        since: str | None = None,
        until: str | None = None,
        assets: str | None = None,
        max_pages: int = 20,
        max_records: int = 5000,
    ) -> ApiResponse[BinanceEarnHistoryApiPreview]:
        since_at = None
        until_at = None
        if since:
            since_at = datetime.fromisoformat(since.replace("Z", "+00:00"))
            if since_at.tzinfo is None:
                since_at = since_at.replace(tzinfo=timezone.utc)
        if until:
            until_at = datetime.fromisoformat(until.replace("Z", "+00:00"))
            if until_at.tzinfo is None:
                until_at = until_at.replace(tzinfo=timezone.utc)
        selected_assets = [item.strip().upper() for item in assets.split(",") if item.strip()] if assets else None
        return ApiResponse(
            data=BinanceEarnHistoryService(db).api_preview(
                since=since_at,
                until=until_at,
                assets=selected_assets,
                max_pages=max(1, min(max_pages, 200)),
                max_records=max(1, min(max_records, 50000)),
            )
        )

    @app.get("/api/v1/sources/binance/withdraw-history-api-preview")
    def binance_withdraw_history_api_preview(
        since: str | None = None,
        until: str | None = None,
        assets: str | None = "JUP",
        max_records: int = 1000,
    ) -> ApiResponse[BinanceCapitalWithdrawalPreview]:
        since_at = None
        until_at = None
        if since:
            since_at = datetime.fromisoformat(since.replace("Z", "+00:00"))
            if since_at.tzinfo is None:
                since_at = since_at.replace(tzinfo=timezone.utc)
        if until:
            until_at = datetime.fromisoformat(until.replace("Z", "+00:00"))
            if until_at.tzinfo is None:
                until_at = until_at.replace(tzinfo=timezone.utc)
        selected_assets = [item.strip().upper() for item in assets.split(",") if item.strip()] if assets else None
        return ApiResponse(
            data=BinanceEarnHistoryService(db).withdrawal_history_api_preview(
                since=since_at,
                until=until_at,
                assets=selected_assets,
                max_records=max(1, min(max_records, 5000)),
            )
        )

    @app.get("/api/v1/sources/bitget/withdraw-history-api-preview")
    def bitget_withdraw_history_api_preview(
        since: str | None = "2025-06-14T00:00:00Z",
        until: str | None = "2025-06-16T23:59:59Z",
        assets: str | None = "JUP,SOL",
        max_records: int = 1000,
    ) -> ApiResponse[BitgetWithdrawalPreview]:
        since_at = None
        until_at = None
        if since:
            since_at = datetime.fromisoformat(since.replace("Z", "+00:00"))
            if since_at.tzinfo is None:
                since_at = since_at.replace(tzinfo=timezone.utc)
        if until:
            until_at = datetime.fromisoformat(until.replace("Z", "+00:00"))
            if until_at.tzinfo is None:
                until_at = until_at.replace(tzinfo=timezone.utc)
        selected_assets = [item.strip().upper() for item in assets.split(",") if item.strip()] if assets else None
        return ApiResponse(
            data=BitgetWalletHistoryService(db).withdrawal_history_api_preview(
                since=since_at,
                until=until_at,
                assets=selected_assets,
                max_records=max(1, min(max_records, 5000)),
            )
        )

    @app.post("/api/v1/sources/binance/earn-history-harvest/import")
    def binance_earn_history_harvest_import(
        payload: BinanceEarnHarvestImportRequest,
    ) -> ApiResponse[BinanceEarnHarvestImportResult]:
        return ApiResponse(
            data=BinanceEarnHistoryService(db).import_harvest(
                harvest_path=payload.harvest_path,
                execute=payload.execute,
            )
        )

    @app.post("/api/v1/sources/binance/earn-history-api/import")
    def binance_earn_history_api_import(
        payload: BinanceEarnApiImportRequest,
    ) -> ApiResponse[BinanceEarnApiImportResult]:
        since_at = None
        until_at = None
        if payload.since:
            since_at = datetime.fromisoformat(payload.since.replace("Z", "+00:00"))
            if since_at.tzinfo is None:
                since_at = since_at.replace(tzinfo=timezone.utc)
        if payload.until:
            until_at = datetime.fromisoformat(payload.until.replace("Z", "+00:00"))
            if until_at.tzinfo is None:
                until_at = until_at.replace(tzinfo=timezone.utc)
        selected_assets = [item.strip().upper() for item in payload.assets if item.strip()]
        return ApiResponse(
            data=BinanceEarnHistoryService(db).import_api_history(
                since=since_at,
                until=until_at,
                assets=selected_assets or None,
                max_pages=max(1, min(payload.max_pages, 200)),
                max_records=max(1, min(payload.max_records, 50000)),
                execute=payload.execute,
            )
        )

    @app.post("/api/v1/sources/binance/withdraw-history-api/import")
    def binance_withdraw_history_api_import(
        payload: BinanceCapitalWithdrawalApiImportRequest,
    ) -> ApiResponse[BinanceCapitalWithdrawalApiImportResult]:
        since_at = None
        until_at = None
        if payload.since:
            since_at = datetime.fromisoformat(payload.since.replace("Z", "+00:00"))
            if since_at.tzinfo is None:
                since_at = since_at.replace(tzinfo=timezone.utc)
        if payload.until:
            until_at = datetime.fromisoformat(payload.until.replace("Z", "+00:00"))
            if until_at.tzinfo is None:
                until_at = until_at.replace(tzinfo=timezone.utc)
        selected_assets = [item.strip().upper() for item in payload.assets if item.strip()]
        return ApiResponse(
            data=BinanceEarnHistoryService(db).import_withdrawal_api_history(
                since=since_at,
                until=until_at,
                assets=selected_assets or None,
                max_records=max(1, min(payload.max_records, 5000)),
                execute=payload.execute,
            )
        )

    @app.post("/api/v1/sources/bitget/withdraw-history-api/import")
    def bitget_withdraw_history_api_import(
        payload: BitgetWithdrawalApiImportRequest,
    ) -> ApiResponse[BitgetWithdrawalApiImportResult]:
        since_at = None
        until_at = None
        if payload.since:
            since_at = datetime.fromisoformat(payload.since.replace("Z", "+00:00"))
            if since_at.tzinfo is None:
                since_at = since_at.replace(tzinfo=timezone.utc)
        if payload.until:
            until_at = datetime.fromisoformat(payload.until.replace("Z", "+00:00"))
            if until_at.tzinfo is None:
                until_at = until_at.replace(tzinfo=timezone.utc)
        selected_assets = [item.strip().upper() for item in payload.assets if item.strip()]
        return ApiResponse(
            data=BitgetWalletHistoryService(db).import_withdrawal_api_history(
                since=since_at,
                until=until_at,
                assets=selected_assets or None,
                max_records=max(1, min(payload.max_records, 5000)),
                execute=payload.execute,
            )
        )

    @app.get("/api/v1/review/gates")
    def review_gates() -> ApiResponse[ReviewGate]:
        return ApiResponse(data=ReviewService(db).gate())

    @app.get("/api/v1/review/tasks")
    def review_tasks(
        limit: int = 80,
        include_reconciliation: bool = False,
    ) -> ApiResponse[ReviewTaskSummary]:
        return ApiResponse(
            data=ReviewService(db).tasks(
                limit=limit,
                include_reconciliation=include_reconciliation,
            )
        )

    @app.post("/api/v1/review/decisions")
    def add_review_decision(payload: ReviewDecisionCreate) -> ApiResponse[ReviewDecision]:
        return ApiResponse(data=db.add_review_decision(payload))

    @app.get("/api/v1/review/decisions")
    def list_review_decisions() -> ApiResponse[list[ReviewDecision]]:
        return ApiResponse(data=db.list_review_decisions())

    @app.get("/api/v1/review/decision-suggestions")
    def review_decision_suggestions() -> ApiResponse[list[ReviewDecisionSuggestion]]:
        return ApiResponse(data=ReviewService(db).decision_suggestions())

    @app.get("/api/v1/review/evidence-traces")
    def review_evidence_traces() -> ApiResponse[ReviewEvidenceTraceReport]:
        return ApiResponse(data=ReviewService(db).evidence_traces())

    @app.post("/api/v1/review/evidence-traces/canonicalize")
    def canonicalize_review_evidence_traces(
        payload: ReviewEvidenceTraceCanonicalizeRequest,
    ) -> ApiResponse[ReviewEvidenceTraceCanonicalizeResult]:
        return ApiResponse(
            data=ReviewService(db).canonicalize_evidence_traces(
                execute=payload.execute,
            )
        )

    @app.post("/api/v1/review/decision-suggestions/{suggestion_id}/accept")
    def accept_review_decision_suggestion(
        suggestion_id: str,
    ) -> ApiResponse[ReviewDecision]:
        suggestions = {
            suggestion.suggestion_id: suggestion
            for suggestion in ReviewService(db).decision_suggestions()
        }
        suggestion = suggestions.get(suggestion_id)
        if suggestion is None:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="review_suggestion_not_found",
                        message=f"Review-Vorschlag nicht gefunden: {suggestion_id}",
                        field="suggestion_id",
                    )
                ],
            )
        for decision in db.list_review_decisions():
            if (
                decision.payload.get("suggestion_id") == suggestion_id
                and decision.source == "api:/api/v1/review/decision-suggestions"
            ):
                return ApiResponse(
                    status="warning",
                    data=decision,
                    warnings=[
                        ApiMessage(
                            code="review_suggestion_already_accepted",
                            message="Review-Vorschlag wurde bereits uebernommen.",
                            field="suggestion_id",
                        )
                    ],
                )
        payload = dict(suggestion.payload)
        payload["suggestion_id"] = suggestion.suggestion_id
        payload["confidence"] = suggestion.confidence
        payload["auto_persist"] = suggestion.auto_persist
        decision = db.add_review_decision(
            ReviewDecisionCreate(
                decision_type=suggestion.decision_type,
                scope=suggestion.scope,
                title=suggestion.title,
                rationale=suggestion.rationale,
                evidence_ref=suggestion.evidence_ref,
                actor=suggestion.actor,
                source="api:/api/v1/review/decision-suggestions",
                affected_ids=suggestion.affected_ids,
                payload=payload,
            )
        )
        return ApiResponse(data=decision)

    @app.post("/api/v1/parity/v1/references")
    def add_v1_reference_metric(
        payload: V1ReferenceMetricCreate,
    ) -> ApiResponse[V1ReferenceMetric]:
        return ApiResponse(data=db.add_v1_reference_metric(payload))

    @app.get("/api/v1/parity/v1/references")
    def list_v1_reference_metrics() -> ApiResponse[list[V1ReferenceMetric]]:
        return ApiResponse(data=db.list_v1_reference_metrics())

    @app.delete("/api/v1/parity/v1/references/{reference_id}")
    def delete_v1_reference_metric(reference_id: str) -> ApiResponse[V1ReferenceDeleteResult]:
        deleted = db.delete_v1_reference_metric(reference_id)
        warnings = []
        if not deleted:
            warnings.append(
                {
                    "code": "v1_reference_not_found",
                    "message": f"V1-Referenzwert nicht gefunden: {reference_id}",
                    "field": "reference_id",
                }
            )
        return ApiResponse(
            status="warning" if warnings else "ok",
            data=V1ReferenceDeleteResult(reference_id=reference_id, deleted=deleted),
            warnings=warnings,
        )

    @app.post("/api/v1/parity/v1/import/wiso")
    def import_wiso_v1_references(
        payload: V1WisoReferenceImportRequest,
    ) -> ApiResponse[V1WisoReferenceImportResult]:
        try:
            importer = WisoReferenceImporter(db)
            if payload.content is not None:
                result = importer.import_text(payload.content, label=payload.label)
            elif payload.file_path is not None:
                result = importer.import_path(payload.file_path, label=payload.label)
            else:
                return ApiResponse(
                    status="error",
                    errors=[
                        {
                            "code": "missing_wiso_input",
                            "message": "file_path oder content muss gesetzt sein.",
                            "field": "file_path",
                        }
                    ],
                )
        except (OSError, ValueError) as exc:
            return ApiResponse(
                status="error",
                errors=[
                    {
                        "code": "wiso_reference_import_failed",
                        "message": str(exc),
                        "field": "file_path",
                    }
                ],
            )
        return ApiResponse(data=result)

    @app.get("/api/v1/parity/compare")
    def compare_v1_v2_parity() -> ApiResponse[V1ParitySummary]:
        return ApiResponse(data=V1ParityService(db).compare())

    @app.get("/api/v1/parity/diagnostics")
    def parity_diagnostics() -> ApiResponse[V1ParityDiagnostics]:
        return ApiResponse(data=V1ParityService(db).diagnostics())

    @app.get("/api/v1/parity/release-readiness")
    def parity_release_readiness() -> ApiResponse[V1ParityReleaseReadiness]:
        return ApiResponse(data=V1ParityService(db).release_readiness())

    @app.get("/api/v1/parity/group-detail")
    def parity_group_detail(scope: str) -> ApiResponse[V1ParityGroupDetail]:
        return ApiResponse(data=V1ParityService(db).group_detail(scope))

    @app.get("/api/v1/parity/hnt-wallet-bridge")
    def parity_hnt_wallet_bridge(year: int = 2022) -> ApiResponse[HntWalletBridgeReport]:
        return ApiResponse(data=V1ParityService(db).hnt_wallet_bridge(year))

    @app.get("/api/v1/parity/hnt-fifo-provenance")
    def parity_hnt_fifo_provenance(
        limit: int = 200,
        source: str | None = None,
        account: str | None = None,
        from_at: datetime | None = None,
        to_at: datetime | None = None,
    ) -> ApiResponse[HntFifoProvenanceReport]:
        return ApiResponse(
            data=V1ParityService(db).hnt_fifo_provenance(
                limit=limit,
                source=source,
                account=account,
                from_at=from_at,
                to_at=to_at,
            )
        )

    @app.post("/api/v1/parity/decisions")
    def add_parity_decision(payload: V1ParityDecisionCreate) -> ApiResponse[V1ParityDecisionResult]:
        decision = db.add_review_decision(
            ReviewDecisionCreate(
                decision_type="parity_finding",
                scope=payload.scope,
                title=payload.title,
                rationale=payload.rationale,
                evidence_ref=payload.evidence_ref,
                actor="user",
                source="api:/api/v1/parity/decisions",
                affected_ids=[payload.scope],
                payload={"decision_status": payload.decision_status},
            )
        )
        return ApiResponse(
            data=V1ParityDecisionResult(
                decision_id=decision.decision_id,
                scope=decision.scope,
                decision_status=payload.decision_status,
            )
        )

    @app.post("/api/v1/tax/fifo/rebuild")
    def rebuild_fifo_tax() -> ApiResponse[TaxRunResult]:
        return ApiResponse(data=TaxService(db).rebuild_fifo())

    @app.get("/api/v1/tax/lines")
    def list_tax_lines() -> ApiResponse[list[TaxLine]]:
        return ApiResponse(data=TaxService(db).list_tax_lines())

    @app.get("/api/v1/tax/lots")
    def list_tax_lots() -> ApiResponse[list[TaxLot]]:
        return ApiResponse(data=TaxService(db).list_tax_lots())

    @app.get("/api/v1/tax/unmatched-disposals")
    def list_tax_unmatched_disposals() -> ApiResponse[list[TaxUnmatchedDisposal]]:
        return ApiResponse(data=TaxService(db).list_unmatched_disposals())

    @app.get("/api/v1/tax/holding-periods")
    def tax_holding_periods(min_value_eur: Decimal = Decimal("1")) -> ApiResponse[TaxHoldingPeriodReport]:
        return ApiResponse(data=TaxService(db).holding_period_report(min_value_eur=min_value_eur))

    @app.get("/api/v1/tax/summary")
    def tax_summary() -> ApiResponse[TaxRunSummary | None]:
        return ApiResponse(data=TaxService(db).latest_summary())

    @app.get("/api/v1/tax/wallet-fifo-preview")
    def tax_wallet_fifo_preview() -> ApiResponse[WalletFifoPreviewReport]:
        return ApiResponse(data=WalletFifoPreviewService(db).preview())

    @app.get("/api/v1/tax/legacy-helium-overview")
    def tax_legacy_helium_overview(limit: int = 200) -> ApiResponse[LegacyHeliumOverviewReport]:
        return ApiResponse(data=WalletFifoPreviewService(db).legacy_helium_overview(limit=limit))

    @app.get("/api/v1/tax-years/summary")
    def tax_years_summary() -> ApiResponse[TaxYearsSummary]:
        return ApiResponse(data=TaxYearService(db).summary())

    @app.get("/api/v1/tax-years/payment-overview")
    def tax_years_payment_overview() -> ApiResponse[TaxPaymentOverview]:
        return ApiResponse(data=TaxYearService(db).payment_overview())

    @app.get("/api/v1/tax-years/turnover-audit-summary")
    def tax_years_turnover_audit_summary(limit: int = 20) -> ApiResponse[TaxYearsTurnoverAuditSummary]:
        return ApiResponse(data=TaxYearService(db).turnover_audit_summary(limit=limit))

    @app.get("/api/v1/tax-years/solana-program-income-review")
    def tax_years_solana_program_income_review(limit: int = 200) -> ApiResponse[TaxSolanaProgramIncomeReview]:
        return ApiResponse(data=TaxYearService(db).solana_program_income_review(limit=limit))

    @app.get("/api/v1/tax-years/stablecoin-fifo-review")
    def tax_years_stablecoin_fifo_review(limit: int = 200) -> ApiResponse[TaxStablecoinFifoReview]:
        return ApiResponse(data=TaxYearService(db).stablecoin_fifo_review(limit=limit))

    @app.get("/api/v1/tax-years/stablecoin-quote-leg-review")
    def tax_years_stablecoin_quote_leg_review(limit: int = 200) -> ApiResponse[TaxStablecoinQuoteLegReview]:
        return ApiResponse(data=TaxYearService(db).stablecoin_quote_leg_review(limit=limit))

    @app.get("/api/v1/tax-years/solana-stablecoin-swap-context")
    def tax_years_solana_stablecoin_swap_context(limit: int = 200) -> ApiResponse[TaxSolanaStablecoinSwapContextReview]:
        return ApiResponse(data=TaxYearService(db).solana_stablecoin_swap_context_review(limit=limit))

    @app.get("/api/v1/tax-years/solana-stablecoin-fx-review")
    def tax_years_solana_stablecoin_fx_review(limit: int = 200) -> ApiResponse[TaxSolanaStablecoinFxReview]:
        return ApiResponse(data=TaxYearService(db).solana_stablecoin_fx_review(limit=limit))

    @app.get("/api/v1/tax-methodology/summary")
    def tax_methodology_summary(year: int | None = None) -> ApiResponse[TaxMethodologySummary]:
        return ApiResponse(data=TaxMethodologyService(db).summary(year=year))

    @app.get("/api/v1/tax-methodology/bmf-action-plan")
    def tax_methodology_bmf_action_plan(year: int | None = None) -> ApiResponse[TaxBmfActionPlan]:
        return ApiResponse(data=TaxMethodologyService(db).bmf_action_plan(year=year))

    @app.get("/api/v1/tax-methodology/bmf-closure-backlog")
    def tax_methodology_bmf_closure_backlog(year: int | None = None) -> ApiResponse[TaxBmfClosureBacklogReport]:
        return ApiResponse(data=TaxMethodologyService(db).bmf_closure_backlog(year=year))

    @app.get("/api/v1/tax-methodology/bmf-filing-readiness")
    def tax_methodology_bmf_filing_readiness(year: int | None = None) -> ApiResponse[TaxBmfFilingReadinessReport]:
        return ApiResponse(data=TaxMethodologyService(db).bmf_filing_readiness(year=year))

    @app.get("/api/v1/tax-methodology/bmf-filing-readiness-snapshot")
    def tax_methodology_bmf_filing_readiness_snapshot() -> ApiResponse[TaxBmfFilingReadinessSnapshot]:
        return ApiResponse(data=TaxMethodologyService(db).bmf_filing_readiness_snapshot())

    @app.get("/api/v1/tax-years/reward-bmf-recheck")
    def tax_years_reward_bmf_recheck() -> ApiResponse[TaxRewardBmfRecheckReport]:
        return ApiResponse(data=TaxMethodologyService(db).reward_bmf_recheck())

    @app.get("/api/v1/tax-years/{year}")
    def tax_year_detail(year: int) -> ApiResponse[TaxYearDetail]:
        return ApiResponse(data=TaxYearService(db).detail(year))

    @app.get("/api/v1/tax-years/{year}/declaration-guide")
    def tax_year_declaration_guide(year: int) -> ApiResponse[TaxDeclarationGuide]:
        return ApiResponse(data=TaxYearService(db).declaration_guide(year))

    @app.get("/api/v1/tax-years/{year}/filing-summary")
    def tax_year_filing_summary(year: int) -> ApiResponse[TaxYearFilingSummary]:
        return ApiResponse(data=TaxYearService(db).filing_summary(year))

    @app.get("/api/v1/tax-years/{year}/methodology")
    def tax_year_methodology(year: int) -> ApiResponse[TaxMethodologyReport]:
        return ApiResponse(data=TaxMethodologyService(db).report(year))

    @app.get("/api/v1/tax-years/{year}/compliance-status")
    def tax_year_compliance_status(year: int) -> ApiResponse[TaxYearComplianceStatus]:
        return ApiResponse(data=TaxMethodologyService(db).status(year))

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-delta")
    def tax_year_wallet_fifo_delta(year: int) -> ApiResponse[WalletFifoPreviewReport]:
        return ApiResponse(data=WalletFifoPreviewService(db).preview(year=year))

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-gaps")
    def tax_year_wallet_fifo_gaps(year: int, limit: int = 80) -> ApiResponse[WalletFifoGapDiagnosisReport]:
        return ApiResponse(data=WalletFifoPreviewService(db).gap_diagnosis(year=year, limit=limit))

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-origin-trace")
    def tax_year_wallet_fifo_origin_trace(
        year: int,
        asset: str | None = None,
        pool_id: str | None = None,
        limit: int = 20,
    ) -> ApiResponse[WalletFifoOriginTraceReport]:
        return ApiResponse(
            data=WalletFifoPreviewService(db).origin_trace(
                year=year,
                asset=asset,
                pool_id=pool_id,
                limit=limit,
            )
        )

    @app.get("/api/v1/tax-years/{year}/cex-deposit-transfer-evidence")
    def tax_year_cex_deposit_transfer_evidence(
        year: int,
        cex: str = "binance",
        network: str | None = "SOL",
        limit: int = 100,
    ) -> ApiResponse[WalletFifoCexDepositTransferEvidenceReport]:
        return ApiResponse(
            data=WalletFifoPreviewService(db).cex_deposit_transfer_evidence(
                year=year,
                cex=cex,
                network=network,
                limit=limit,
            )
        )

    @app.get("/api/v1/tax-years/{year}/cex-sender-ownership-latest")
    def tax_year_cex_sender_ownership_latest(
        year: int,
        cex: str = "binance",
        network: str | None = "SOL",
        limit: int = 100,
    ) -> ApiResponse[WalletFifoCexSenderOwnershipSummaryReport]:
        return ApiResponse(
            data=WalletFifoPreviewService(db).cex_sender_ownership_latest(
                year=year,
                cex=cex,
                network=network,
                limit=limit,
            )
        )

    @app.post("/api/v1/tax-years/{year}/cex-sender-ownership-decisions")
    def add_tax_year_cex_sender_ownership_decision(
        year: int,
        payload: WalletFifoCexSenderOwnershipReviewDecisionCreate,
        cex: str = "binance",
        network: str | None = "SOL",
    ) -> ApiResponse[WalletFifoCexSenderOwnershipReviewDecisionResult]:
        service = WalletFifoPreviewService(db)
        report = service.cex_sender_ownership_latest(
            year=year,
            cex=cex,
            network=network,
            limit=500,
        )
        decision_item = next((item for item in report.decisions if item.txid == payload.txid), None)
        if decision_item is None:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="cex_sender_ownership_tx_not_found",
                        message="TXID wurde im letzten CEX-Sender-Ownership-Artifact nicht gefunden.",
                        field="txid",
                    )
                ],
            )
        required_flags = [
            "binance_deposit_address_owned",
            "sender_is_own_wallet",
            "exchange_deposit_transfer_neutral",
        ]
        if payload.decision_status == "tax_neutral_transfer_reviewed" and not all(
            decision_item.decision_layer.get(flag) is True for flag in required_flags
        ):
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="cex_sender_ownership_not_tax_neutral_candidate",
                        message=(
                            "Diese TX ist im aktuellen Artifact kein eigener "
                            "steuerneutraler Transfer-Kandidat."
                        ),
                        field="decision_status",
                    )
                ],
            )
        if (
            payload.decision_status == "exchange_outflow_evidence_required"
            and decision_item.sender_classification != "exchange_infrastructure"
        ):
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="cex_sender_ownership_not_exchange_infrastructure",
                        message=(
                            "Diese TX ist im aktuellen Artifact nicht als "
                            "bekannte Exchange-Infrastruktur klassifiziert."
                        ),
                        field="decision_status",
                    )
                ],
            )
        scope = (
            f"cex_sender_ownership:year:{year}:cex:{cex.lower()}:"
            f"network:{network or 'all'}:tx:{payload.txid}"
        )
        title = payload.title or (
            "CEX Deposit als steuerneutralen Transfer dokumentiert"
            if payload.decision_status == "tax_neutral_transfer_reviewed"
            else (
                "CEX Deposit benoetigt Exchange-Outflow-Beleg"
                if payload.decision_status == "exchange_outflow_evidence_required"
                else "CEX Deposit Sender bleibt ungeprueft"
            )
        )
        rationale = payload.rationale or (
            "Review-Decision aus CEX Sender Ownership Artifact. Diese Entscheidung "
            "dokumentiert den fachlichen Status, schreibt aber keine FIFO-, Ledger- "
            "oder Steuerzeilen um."
        )
        for existing in db.list_review_decisions():
            if (
                existing.decision_type == "cex_sender_ownership"
                and existing.scope == scope
                and existing.payload.get("decision_status") == payload.decision_status
            ):
                return ApiResponse(
                    status="warning",
                    data=WalletFifoCexSenderOwnershipReviewDecisionResult(
                        decision_id=existing.decision_id,
                        scope=scope,
                        decision_status=payload.decision_status,
                        txid=payload.txid,
                    ),
                    warnings=[
                        ApiMessage(
                            code="cex_sender_ownership_decision_already_exists",
                            message="Diese CEX-Sender-Ownership-Entscheidung ist bereits gespeichert.",
                            field="txid",
                        )
                    ],
                )
        decision = db.add_review_decision(
            ReviewDecisionCreate(
                decision_type="cex_sender_ownership",
                scope=scope,
                title=title,
                rationale=rationale,
                evidence_ref=report.artifact_path,
                actor="user",
                source=f"api:/api/v1/tax-years/{year}/cex-sender-ownership-decisions",
                affected_ids=[payload.txid],
                payload={
                    "decision_status": payload.decision_status,
                    "year": year,
                    "cex": cex.lower(),
                    "network": network,
                    "txid": payload.txid,
                    "asset": decision_item.asset,
                    "amount": str(decision_item.amount),
                    "onchain_sender": decision_item.onchain_sender,
                    "onchain_sender_label": decision_item.onchain_sender_label,
                    "sender_classification": decision_item.sender_classification,
                    "primary_signer": decision_item.primary_signer,
                    "deposit_address": decision_item.deposit_address,
                    "fifo_transfer_status": decision_item.fifo_transfer_status,
                    "carried_cost_basis_eur": str(decision_item.carried_cost_basis_eur),
                    "artifact_final_tax_status": decision_item.final_tax_status,
                    "decision_layer": decision_item.decision_layer,
                    "import_effect": "review_decision_only",
                },
            )
        )
        return ApiResponse(
            data=WalletFifoCexSenderOwnershipReviewDecisionResult(
                decision_id=decision.decision_id,
                scope=scope,
                decision_status=payload.decision_status,
                txid=payload.txid,
            )
        )

    @app.get("/api/v1/tax-years/{year}/cex-exchange-outflow-evidence")
    def tax_year_cex_exchange_outflow_evidence(
        year: int,
        source_exchange: str = "bitget",
        target_cex: str = "binance",
        network: str | None = "SOL",
        window_hours: int = 72,
        limit: int = 100,
    ) -> ApiResponse[WalletFifoCexExchangeOutflowEvidenceReport]:
        return ApiResponse(
            data=WalletFifoPreviewService(db).cex_exchange_outflow_evidence(
                year=year,
                source_exchange=source_exchange,
                target_cex=target_cex,
                network=network,
                window_hours=max(1, min(window_hours, 24 * 30)),
                limit=limit,
            )
        )

    @app.get("/api/v1/tax-years/{year}/cex-exchange-outflow-anchor-feasibility")
    def tax_year_cex_exchange_outflow_anchor_feasibility(
        year: int,
        source_exchange: str = "bitget",
        target_cex: str = "binance",
        network: str | None = "SOL",
        window_hours: int = 72,
        limit: int = 200,
    ) -> ApiResponse[WalletFifoCexExchangeOutflowAnchorFeasibilityReport]:
        return ApiResponse(
            data=WalletFifoPreviewService(db).cex_exchange_outflow_anchor_feasibility(
                year=year,
                source_exchange=source_exchange,
                target_cex=target_cex,
                network=network,
                window_hours=max(1, min(window_hours, 24 * 30)),
                limit=limit,
            )
        )

    @app.post("/api/v1/tax-years/{year}/cex-exchange-outflow-decisions")
    def add_tax_year_cex_exchange_outflow_decision(
        year: int,
        payload: WalletFifoCexExchangeOutflowReviewDecisionCreate,
        source_exchange: str = "bitget",
        target_cex: str = "binance",
        network: str | None = "SOL",
        window_hours: int = 72,
    ) -> ApiResponse[WalletFifoCexExchangeOutflowReviewDecisionResult]:
        service = WalletFifoPreviewService(db)
        report = service.cex_exchange_outflow_evidence(
            year=year,
            source_exchange=source_exchange,
            target_cex=target_cex,
            network=network,
            window_hours=max(1, min(window_hours, 24 * 30)),
            limit=500,
        )
        row = next((item for item in report.rows if item.deposit_txid == payload.deposit_txid), None)
        if row is None:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="cex_exchange_outflow_deposit_not_found",
                        message="Deposit-TXID wurde im aktuellen CEX-Exchange-Outflow-Evidence-Report nicht gefunden.",
                        field="deposit_txid",
                    )
                ],
            )
        ready_statuses = {"exchange_outflow_txid_match_ready", "exchange_outflow_address_txid_ready"}
        if (
            payload.decision_status == "transfer_neutral_fifo_carry_forward_reviewed"
            and row.status not in ready_statuses
        ):
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="cex_exchange_outflow_not_ready",
                        message=(
                            "Diese Deposit-TX hat noch keinen matching-ready "
                            "Exchange-Outflow-Beleg."
                        ),
                        field="decision_status",
                    )
                ],
            )
        best = row.best_candidate
        scope = (
            f"cex_exchange_outflow:year:{year}:source:{source_exchange.lower()}:"
            f"target:{target_cex.lower()}:network:{network or 'all'}:deposit_tx:{payload.deposit_txid}"
        )
        title = payload.title or (
            "CEX-zu-CEX-Transfer steuerneutral dokumentiert"
            if payload.decision_status == "transfer_neutral_fifo_carry_forward_reviewed"
            else "CEX-zu-CEX-Outflow-Beleg bleibt in Review"
        )
        rationale = payload.rationale or (
            "Review-Decision aus CEX Exchange Outflow Evidence. Der Bitget "
            "Withdrawal-Beleg wurde gegen den Binance-Onchain-Deposit gematcht. "
            "Diese Entscheidung dokumentiert die steuerneutrale FIFO-Fortfuehrung "
            "fachlich, schreibt aber keine Ledger-, FIFO- oder Steuerzeilen um."
        )
        for existing in db.list_review_decisions():
            if (
                existing.decision_type == "cex_exchange_outflow"
                and existing.scope == scope
                and existing.payload.get("decision_status") == payload.decision_status
            ):
                return ApiResponse(
                    status="warning",
                    data=WalletFifoCexExchangeOutflowReviewDecisionResult(
                        decision_id=existing.decision_id,
                        scope=scope,
                        decision_status=payload.decision_status,
                        deposit_txid=payload.deposit_txid,
                    ),
                    warnings=[
                        ApiMessage(
                            code="cex_exchange_outflow_decision_already_exists",
                            message="Diese CEX-Exchange-Outflow-Entscheidung ist bereits gespeichert.",
                            field="deposit_txid",
                        )
                    ],
                )
        decision = db.add_review_decision(
            ReviewDecisionCreate(
                decision_type="cex_exchange_outflow",
                scope=scope,
                title=title,
                rationale=rationale,
                evidence_ref=(
                    f"/api/v1/tax-years/{year}/cex-exchange-outflow-evidence"
                    f"?source_exchange={source_exchange.lower()}&target_cex={target_cex.lower()}"
                    f"&network={network or 'all'}&window_hours={max(1, min(window_hours, 24 * 30))}"
                ),
                actor="user",
                source=f"api:/api/v1/tax-years/{year}/cex-exchange-outflow-decisions",
                affected_ids=[payload.deposit_txid, *( [best.raw_object_id] if best and best.raw_object_id else [] )],
                payload={
                    "decision_status": payload.decision_status,
                    "year": year,
                    "source_exchange": source_exchange.lower(),
                    "target_cex": target_cex.lower(),
                    "network": network,
                    "deposit_txid": payload.deposit_txid,
                    "deposit_time": row.deposit_time.isoformat() if row.deposit_time else None,
                    "deposit_address": row.deposit_address,
                    "source_sender": row.source_sender,
                    "source_sender_label": row.source_sender_label,
                    "asset": row.asset,
                    "deposit_amount": str(row.amount),
                    "evidence_status": row.status,
                    "exchange_outflow_event_id": best.event_id if best else None,
                    "exchange_outflow_raw_object_id": best.raw_object_id if best else None,
                    "exchange_outflow_tx_id": best.withdrawal_tx_id if best else None,
                    "exchange_outflow_address": best.withdrawal_address if best else None,
                    "exchange_outflow_amount": str(best.quantity) if best else None,
                    "exchange_outflow_gross_amount": str(best.withdrawal_amount) if best and best.withdrawal_amount is not None else None,
                    "exchange_outflow_fee": str(best.withdrawal_fee) if best and best.withdrawal_fee is not None else None,
                    "amount_delta": str(best.amount_delta) if best else None,
                    "time_delta_seconds": best.seconds_delta if best else None,
                    "import_effect": "none",
                    "ledger_effect": "none",
                    "fifo_effect": "carry_forward_documented_pending_fifo_anchor",
                    "tax_line_effect": "none",
                },
            )
        )
        return ApiResponse(
            data=WalletFifoCexExchangeOutflowReviewDecisionResult(
                decision_id=decision.decision_id,
                scope=scope,
                decision_status=payload.decision_status,
                deposit_txid=payload.deposit_txid,
            )
        )

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-provenance-priorities")
    def tax_year_wallet_fifo_provenance_priorities(
        year: int,
        limit: int = 50,
    ) -> ApiResponse[WalletFifoProvenancePriorityReport]:
        return ApiResponse(data=WalletFifoPreviewService(db).provenance_priorities(year=year, limit=limit))

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-provenance-closure")
    def tax_year_wallet_fifo_provenance_closure(
        year: int,
        limit: int = 50,
    ) -> ApiResponse[WalletFifoYearProvenanceClosureReport]:
        return ApiResponse(data=WalletFifoPreviewService(db).provenance_closure_report(year=year, limit=limit))

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-provenance-events")
    def tax_year_wallet_fifo_provenance_events(
        year: int,
        asset: str | None = None,
        pool_id: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> ApiResponse[WalletFifoProvenanceEventReport]:
        return ApiResponse(
            data=WalletFifoPreviewService(db).provenance_events(
                year=year,
                asset=asset,
                pool_id=pool_id,
                offset=offset,
                limit=limit,
            )
        )

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-raw-provenance-breakdown")
    def tax_year_wallet_fifo_raw_provenance_breakdown(
        year: int,
        asset: str | None = None,
        pool_id: str | None = None,
        limit: int = 50,
    ) -> ApiResponse[WalletFifoRawProvenanceBreakdownReport]:
        return ApiResponse(
            data=WalletFifoPreviewService(db).raw_provenance_breakdown(
                year=year,
                asset=asset,
                pool_id=pool_id,
                limit=limit,
            )
        )

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-opening-balance-evidence")
    def tax_year_wallet_fifo_opening_balance_evidence(
        year: int,
        asset: str | None = None,
        pool_id: str | None = None,
        limit: int = 50,
    ) -> ApiResponse[WalletFifoOpeningBalanceEvidenceReport]:
        return ApiResponse(
            data=WalletFifoPreviewService(db).opening_balance_evidence(
                year=year,
                asset=asset,
                pool_id=pool_id,
                limit=limit,
            )
        )

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-exchange-evidence-gaps")
    def tax_year_wallet_fifo_exchange_evidence_gaps(
        year: int,
        asset: str | None = None,
        pool_id: str | None = None,
        limit: int = 50,
    ) -> ApiResponse[WalletFifoExchangeEvidenceGapReport]:
        return ApiResponse(
            data=WalletFifoPreviewService(db).exchange_evidence_gaps(
                year=year,
                asset=asset,
                pool_id=pool_id,
                limit=limit,
            )
        )

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-solana-provenance-classification")
    def tax_year_wallet_fifo_solana_provenance_classification(
        year: int,
        asset: str = "SOL",
        pool_id: str | None = None,
        offset: int = 0,
        limit: int = 5,
        provider: str = "rpc_public",
        rpc_url: str = WalletFifoPreviewService.DEFAULT_SOLANA_RPC_URL,
    ) -> ApiResponse[WalletFifoSolanaProvenanceClassificationReport]:
        return ApiResponse(
            data=WalletFifoPreviewService(db).solana_provenance_classification(
                year=year,
                asset=asset,
                pool_id=pool_id,
                offset=offset,
                limit=limit,
                provider=provider,
                rpc_url=rpc_url,
            )
        )

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-solana-provenance-batch-latest")
    def tax_year_wallet_fifo_solana_provenance_batch_latest(
        year: int,
        asset: str = "SOL",
    ) -> ApiResponse[WalletFifoSolanaProvenanceBatchLatest]:
        return ApiResponse(data=WalletFifoPreviewService(db).solana_provenance_batch_latest(year=year, asset=asset))

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-solana-raw-provenance-priorities")
    def tax_year_wallet_fifo_solana_raw_provenance_priorities(
        year: int,
        asset: str = "SOL",
        pool_id: str | None = None,
        limit: int = 50,
    ) -> ApiResponse[WalletFifoSolanaRawProvenancePriorityReport]:
        return ApiResponse(
            data=WalletFifoPreviewService(db).solana_raw_provenance_priorities(
                year=year,
                asset=asset,
                pool_id=pool_id,
                limit=limit,
            )
        )

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-solana-raw-provenance-senders")
    def tax_year_wallet_fifo_solana_raw_provenance_senders(
        year: int,
        asset: str = "SOL",
        pool_id: str | None = None,
        limit: int = 50,
    ) -> ApiResponse[WalletFifoSolanaRawProvenanceSenderSummaryReport]:
        return ApiResponse(
            data=WalletFifoPreviewService(db).solana_raw_provenance_sender_summary(
                year=year,
                asset=asset,
                pool_id=pool_id,
                limit=limit,
            )
        )

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-solana-raw-bmf-evidence-summary")
    def tax_year_wallet_fifo_solana_raw_bmf_evidence_summary(
        year: int,
        asset: str = "SOL",
        pool_id: str | None = None,
        limit: int = 50,
    ) -> ApiResponse[WalletFifoSolanaRawBmfEvidenceSummaryReport]:
        return ApiResponse(
            data=WalletFifoPreviewService(db).solana_raw_bmf_evidence_summary(
                year=year,
                asset=asset,
                pool_id=pool_id,
                limit=limit,
            )
        )

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-solana-raw-bmf-evidence-drilldown")
    def tax_year_wallet_fifo_solana_raw_bmf_evidence_drilldown(
        year: int,
        asset: str = "SOL",
        pool_id: str | None = None,
        route_classification: str | None = "program_service_route",
        bmf_evidence_priority: str | None = "high",
        limit: int = 50,
    ) -> ApiResponse[WalletFifoSolanaRawBmfEvidenceDrilldownReport]:
        return ApiResponse(
            data=WalletFifoPreviewService(db).solana_raw_bmf_evidence_drilldown(
                year=year,
                asset=asset,
                pool_id=pool_id,
                route_classification=route_classification,
                bmf_evidence_priority=bmf_evidence_priority,
                limit=limit,
            )
        )

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-solana-sender-clusters")
    def tax_year_wallet_fifo_solana_sender_clusters(
        year: int,
        asset: str = "SOL",
        limit: int = 50,
    ) -> ApiResponse[WalletFifoSolanaSenderClusterReport]:
        return ApiResponse(data=WalletFifoPreviewService(db).solana_sender_clusters(year=year, asset=asset, limit=limit))

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-solana-sender-cluster-outflows")
    def tax_year_wallet_fifo_solana_sender_cluster_outflows(
        year: int,
        asset: str = "SOL",
        sender_owner: str | None = None,
        limit: int = 25,
        window_hours: int = 48,
        amount_tolerance_percent: Decimal = Decimal("1"),
    ) -> ApiResponse[WalletFifoSolanaSenderClusterOutflowReport]:
        return ApiResponse(
            data=WalletFifoPreviewService(db).solana_sender_cluster_outflows(
                year=year,
                asset=asset,
                sender_owner=sender_owner,
                limit=limit,
                window_hours=window_hours,
                amount_tolerance_percent=amount_tolerance_percent,
            )
        )

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-solana-origin")
    def tax_year_wallet_fifo_solana_origin(
        year: int,
        asset: str = "JUP",
        pool_id: str = "binance:Spot",
        limit: int = 5,
    ) -> ApiResponse[WalletFifoSolanaOriginTraceReport]:
        return ApiResponse(
            data=WalletFifoPreviewService(db).solana_origin_trace(
                year=year,
                asset=asset,
                pool_id=pool_id,
                limit=limit,
            )
        )

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-withdrawal-gaps")
    def tax_year_wallet_fifo_withdrawal_gaps(
        year: int,
        limit: int = 20,
    ) -> ApiResponse[WalletFifoWithdrawalGapReport]:
        return ApiResponse(data=WalletFifoPreviewService(db).withdrawal_gap_trace(year=year, limit=limit))

    @app.get("/api/v1/tax-years/{year}/income-guide")
    def tax_year_income_guide(year: int) -> ApiResponse[TaxIncomeReport]:
        return ApiResponse(data=TaxYearService(db).income_report(year))

    @app.get("/api/v1/tax-years/{year}/solana-program-income-review")
    def tax_year_solana_program_income_review(year: int, limit: int = 200) -> ApiResponse[TaxSolanaProgramIncomeReview]:
        return ApiResponse(data=TaxYearService(db).solana_program_income_review(year=year, limit=limit))

    @app.get("/api/v1/tax-years/{year}/stablecoin-fifo-review")
    def tax_year_stablecoin_fifo_review(year: int, limit: int = 200) -> ApiResponse[TaxStablecoinFifoReview]:
        return ApiResponse(data=TaxYearService(db).stablecoin_fifo_review(year=year, limit=limit))

    @app.get("/api/v1/tax-years/{year}/stablecoin-quote-leg-review")
    def tax_year_stablecoin_quote_leg_review(year: int, limit: int = 200) -> ApiResponse[TaxStablecoinQuoteLegReview]:
        return ApiResponse(data=TaxYearService(db).stablecoin_quote_leg_review(year=year, limit=limit))

    @app.get("/api/v1/tax-years/{year}/solana-stablecoin-swap-context")
    def tax_year_solana_stablecoin_swap_context(year: int, limit: int = 200) -> ApiResponse[TaxSolanaStablecoinSwapContextReview]:
        return ApiResponse(data=TaxYearService(db).solana_stablecoin_swap_context_review(year=year, limit=limit))

    @app.get("/api/v1/tax-years/{year}/solana-stablecoin-fx-review")
    def tax_year_solana_stablecoin_fx_review(year: int, limit: int = 200) -> ApiResponse[TaxSolanaStablecoinFxReview]:
        return ApiResponse(data=TaxYearService(db).solana_stablecoin_fx_review(year=year, limit=limit))

    @app.get("/api/v1/tax-years/{year}/drivers")
    def tax_year_drivers(year: int, limit: int = 50) -> ApiResponse[TaxYearDriverReport]:
        return ApiResponse(data=TaxYearService(db).driver_report(year, limit=limit))

    @app.get("/api/v1/tax-years/{year}/asset-fifo-drilldown")
    def tax_year_asset_fifo_drilldown(
        year: int,
        asset: str,
        limit: int = 200,
    ) -> ApiResponse[TaxYearAssetFifoDrilldown]:
        return ApiResponse(data=TaxYearService(db).asset_fifo_drilldown(year, asset=asset, limit=limit))

    @app.get("/api/v1/tax-years/{year}/asset-fifo-plausibility")
    def tax_year_asset_fifo_plausibility(
        year: int,
        limit: int = 100,
        min_abs_gain_eur: Decimal = Decimal("100"),
    ) -> ApiResponse[TaxYearAssetFifoPlausibilityReport]:
        return ApiResponse(
            data=TaxYearService(db).asset_fifo_plausibility(
                year,
                limit=limit,
                min_abs_gain_eur=min_abs_gain_eur,
            )
        )

    @app.get("/api/v1/tax-years/{year}/asset-fifo-correction-review")
    def tax_year_asset_fifo_correction_review(
        year: int,
        limit: int = 100,
        min_abs_gain_eur: Decimal = Decimal("100"),
    ) -> ApiResponse[TaxYearAssetFifoCorrectionReviewReport]:
        return ApiResponse(
            data=TaxYearService(db).asset_fifo_correction_review(
                year,
                limit=limit,
                min_abs_gain_eur=min_abs_gain_eur,
            )
        )

    @app.get("/api/v1/tax-years/{year}/turnover-audit")
    def tax_year_turnover_audit(year: int, limit: int = 20) -> ApiResponse[TaxYearTurnoverAudit]:
        return ApiResponse(data=TaxYearService(db).turnover_audit(year, limit=limit))

    @app.get("/api/v1/tax-years/{year}/evidence")
    def tax_year_evidence(year: int) -> ApiResponse[TaxYearEvidenceReport]:
        return ApiResponse(data=TaxYearService(db).evidence_report(year))

    @app.get("/api/v1/tax-years/{year}/bmf-closure-appendix")
    def tax_year_bmf_closure_appendix(year: int) -> ApiResponse[TaxYearBmfClosureAppendix]:
        return ApiResponse(data=TaxYearService(db).bmf_closure_appendix(year))

    @app.get("/api/v1/tax-years/{year}/external-inflows")
    def tax_year_external_inflows(year: int, limit: int = 200) -> ApiResponse[TaxExternalInflowReport]:
        return ApiResponse(data=TaxYearService(db).external_inflow_report(year, limit=limit))

    @app.post("/api/v1/derivatives/rebuild")
    def rebuild_derivatives() -> ApiResponse[DerivativeRunResult]:
        return ApiResponse(data=DerivativesManager(db).rebuild())

    @app.get("/api/v1/derivatives/lines")
    def list_derivative_lines() -> ApiResponse[list[DerivativeLine]]:
        return ApiResponse(data=DerivativesManager(db).list_lines())

    @app.get("/api/v1/derivatives/summary")
    def derivative_summary() -> ApiResponse[DerivativeRunSummary | None]:
        return ApiResponse(data=DerivativesManager(db).latest_summary())

    @app.post("/api/v1/pipeline/rebuild")
    def rebuild_pipeline() -> ApiResponse[PipelineResult]:
        return ApiResponse(data=PipelineService(db).rebuild_all())

    @app.post("/api/v1/demo/seed")
    def seed_demo() -> ApiResponse[DemoSeedResult]:
        return ApiResponse(data=PipelineService(db).seed_demo())

    @app.post("/api/v1/flows/rebuild")
    def rebuild_flows() -> ApiResponse[list[FlowEntry]]:
        return ApiResponse(data=FlowService(db).rebuild())

    @app.get("/api/v1/flows/net")
    def net_flows(year: int | None = None) -> ApiResponse[NetFlowSummary]:
        return ApiResponse(data=FlowService(db).summary(year=year))

    @app.post("/api/v1/export/pdf")
    def create_pdf_export(payload: PdfExportRequest) -> ApiResponse[ExportResult]:
        return ApiResponse(data=ExportService(db).create_pdf_packages(payload))

    @app.get("/api/v1/export/packages")
    def list_export_packages() -> ApiResponse[list[ExportPackage]]:
        return ApiResponse(data=ExportService(db).list_packages())

    @app.get("/api/v1/export/readiness")
    def export_readiness() -> ApiResponse[ExportReadiness]:
        return ApiResponse(data=ExportService(db).readiness())

    @app.get("/api/v1/reports/center")
    def report_center() -> ApiResponse[ReportCenterStatus]:
        return ApiResponse(data=ReportCenterService(db).center())

    @app.get("/api/v1/export/evidence-manifest.json")
    def download_evidence_manifest() -> Response:
        payload = ReportCenterService(db).evidence_manifest().model_dump(mode="json")
        return Response(
            content=json.dumps(payload, indent=2, ensure_ascii=False),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=evidence-manifest.json"},
        )

    @app.get("/api/v1/export/evidence-package-index.json")
    def download_evidence_package_index() -> Response:
        payload = ReportCenterService(db).evidence_package_index().model_dump(mode="json")
        return Response(
            content=json.dumps(payload, indent=2, ensure_ascii=False),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=evidence-package-index.json"},
        )

    @app.get("/api/v1/export/packages/{package_id}/download.pdf")
    def download_export_package_pdf(package_id: str) -> Response:
        rendered = ExportService(db).render_pdf_package(package_id)
        if rendered is None:
            payload = ApiResponse(
                status="error",
                errors=[
                    {
                        "code": "export_package_not_downloadable",
                        "message": f"Exportpaket nicht gefunden oder blockiert: {package_id}",
                        "field": "package_id",
                    }
                ],
            ).model_dump(mode="json")
            return Response(
                content=json.dumps(payload, ensure_ascii=False),
                media_type="application/json",
                status_code=404,
            )
        package, content = rendered
        safe_label = "".join(
            char if char.isalnum() or char in {"-", "_"} else "_"
            for char in package.label
        ).strip("_") or "steuerreport"
        filename = f"{safe_label}-{package.file_index:03d}.pdf"
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    @app.delete("/api/v1/export/packages/{package_id}")
    def delete_export_package(package_id: str) -> ApiResponse[ExportPackageDeleteResult]:
        deleted = ExportService(db).delete_package(package_id)
        warnings = []
        if not deleted:
            warnings.append(
                {
                    "code": "export_package_not_found",
                    "message": f"Exportpaket nicht gefunden: {package_id}",
                    "field": "package_id",
                }
            )
        return ApiResponse(
            status="warning" if warnings else "ok",
            data=ExportPackageDeleteResult(package_id=package_id, deleted=deleted),
            warnings=warnings,
        )

    @app.post("/api/v1/export/audit")
    def export_audit() -> ApiResponse[AuditExport]:
        return ApiResponse(data=AuditService(db).export())

    @app.post("/api/v1/export/elster-prep")
    def export_elster_prep() -> ApiResponse[ElsterPrepExport]:
        return ApiResponse(data=AuditService(db).elster_prep())

    @app.get("/api/v1/export/audit.json")
    def download_audit_json() -> Response:
        payload = AuditService(db).export().model_dump(mode="json")
        return Response(
            content=json.dumps(payload, indent=2, ensure_ascii=False),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=audit.json"},
        )

    @app.get("/api/v1/export/tax-payment-overview.json")
    def download_tax_payment_overview_json() -> Response:
        payload = TaxYearService(db).payment_overview().model_dump(mode="json")
        return Response(
            content=json.dumps(payload, indent=2, ensure_ascii=False),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=tax-payment-overview.json"},
        )

    @app.get("/api/v1/export/review-decisions.csv")
    def download_review_decisions_csv() -> Response:
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "created_at",
                "decision_id",
                "decision_type",
                "scope",
                "title",
                "rationale",
                "evidence_ref",
                "actor",
                "source",
                "affected_ids",
                "payload_json",
            ],
        )
        writer.writeheader()
        for decision in db.list_review_decisions():
            writer.writerow(
                {
                    "created_at": decision.created_at.isoformat(),
                    "decision_id": decision.decision_id,
                    "decision_type": decision.decision_type,
                    "scope": decision.scope,
                    "title": decision.title,
                    "rationale": decision.rationale,
                    "evidence_ref": decision.evidence_ref,
                    "actor": decision.actor,
                    "source": decision.source,
                    "affected_ids": json.dumps(decision.affected_ids, ensure_ascii=False),
                    "payload_json": json.dumps(decision.payload, ensure_ascii=False, sort_keys=True),
                }
            )
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=review-decisions.csv"
            },
        )

    @app.get("/api/v1/export/token-risk-documentation.csv")
    def download_token_risk_documentation_csv() -> Response:
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "created_at",
                "decision_id",
                "scope",
                "asset",
                "token_symbol",
                "token_name",
                "token_mint",
                "token_risk_status",
                "quantity",
                "value_eur",
                "accounts",
                "evidence_ref",
                "import_effect",
                "ledger_effect",
                "fifo_effect",
                "tax_line_effect",
            ],
        )
        writer.writeheader()
        for decision in db.list_review_decisions():
            if decision.decision_type != "token_risk_documentation":
                continue
            payload = decision.payload
            accounts = payload.get("accounts")
            writer.writerow(
                {
                    "created_at": decision.created_at.isoformat(),
                    "decision_id": decision.decision_id,
                    "scope": decision.scope,
                    "asset": payload.get("asset"),
                    "token_symbol": payload.get("token_symbol"),
                    "token_name": payload.get("token_name"),
                    "token_mint": payload.get("token_mint"),
                    "token_risk_status": payload.get("token_risk_status"),
                    "quantity": payload.get("quantity"),
                    "value_eur": payload.get("value_eur"),
                    "accounts": json.dumps(accounts if isinstance(accounts, list) else [], ensure_ascii=False),
                    "evidence_ref": decision.evidence_ref,
                    "import_effect": payload.get("import_effect"),
                    "ledger_effect": payload.get("ledger_effect"),
                    "fifo_effect": payload.get("fifo_effect"),
                    "tax_line_effect": payload.get("tax_line_effect"),
                }
            )
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=token-risk-documentation.csv"
            },
        )

    @app.get("/api/v1/export/price-gaps.csv")
    def download_price_gaps_csv() -> Response:
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "scope",
                "decision_status",
                "decision_id",
                "decision_title",
                "asset",
                "year",
                "source",
                "event_type",
                "role",
                "event_count",
                "first_event_at",
                "last_event_at",
                "gross_quantity",
                "sample_event_ids",
            ],
        )
        writer.writeheader()
        for gap in PriceCoverageService(db).report().missing:
            writer.writerow(
                {
                    "scope": gap.scope,
                    "decision_status": gap.decision_status,
                    "decision_id": gap.decision_id,
                    "decision_title": gap.decision_title,
                    "asset": gap.asset,
                    "year": gap.year,
                    "source": gap.source,
                    "event_type": gap.event_type,
                    "role": gap.role,
                    "event_count": gap.event_count,
                    "first_event_at": gap.first_event_at.isoformat(),
                    "last_event_at": gap.last_event_at.isoformat(),
                    "gross_quantity": str(gap.gross_quantity),
                    "sample_event_ids": json.dumps(gap.sample_event_ids, ensure_ascii=False),
                }
            )
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=price-gaps.csv"},
        )

    @app.get("/api/v1/export/price-requirements.csv")
    def download_price_requirements_csv() -> Response:
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "asset",
                "price_date",
                "year",
                "source",
                "event_type",
                "role",
                "event_count",
                "first_event_at",
                "last_event_at",
                "gross_quantity",
                "sample_event_ids",
            ],
        )
        writer.writeheader()
        for item in PriceCoverageService(db).requirements().requirements:
            writer.writerow(
                {
                    "asset": item.asset,
                    "price_date": item.price_date.isoformat(),
                    "year": item.year,
                    "source": item.source,
                    "event_type": item.event_type,
                    "role": item.role,
                    "event_count": item.event_count,
                    "first_event_at": item.first_event_at.isoformat(),
                    "last_event_at": item.last_event_at.isoformat(),
                    "gross_quantity": str(item.gross_quantity),
                    "sample_event_ids": json.dumps(item.sample_event_ids, ensure_ascii=False),
                }
            )
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=price-requirements.csv"},
        )

    @app.get("/api/v1/export/parity-diagnostics.csv")
    def download_parity_diagnostics_csv() -> Response:
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "scope",
                "decision_status",
                "decision_id",
                "decision_title",
                "year",
                "asset",
                "status",
                "issue_count",
                "metrics",
                "v1_total_eur",
                "v2_total_eur",
                "absolute_difference_eur",
                "max_absolute_difference",
            ],
        )
        writer.writeheader()
        for group in V1ParityService(db).diagnostics().groups:
            writer.writerow(
                {
                    "scope": group.scope,
                    "decision_status": group.decision_status,
                    "decision_id": group.decision_id,
                    "decision_title": group.decision_title,
                    "year": group.year,
                    "asset": group.asset,
                    "status": group.status,
                    "issue_count": group.issue_count,
                    "metrics": json.dumps(group.metrics, ensure_ascii=False),
                    "v1_total_eur": str(group.v1_total_eur),
                    "v2_total_eur": str(group.v2_total_eur),
                    "absolute_difference_eur": str(group.absolute_difference_eur),
                    "max_absolute_difference": str(group.max_absolute_difference),
                }
            )
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=parity-diagnostics.csv"},
        )

    @app.get("/api/v1/export/hnt-provenance-timeline.csv")
    def download_hnt_provenance_timeline_csv(
        source: str | None = None,
        account: str | None = None,
        from_at: datetime | None = None,
        to_at: datetime | None = None,
    ) -> Response:
        report = V1ParityService(db).hnt_fifo_provenance(
            limit=1000,
            source=source,
            account=account,
            from_at=from_at,
            to_at=to_at,
        )
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "label",
                "role",
                "event_count",
                "quantity_in",
                "quantity_out",
                "net_quantity",
                "first_event_at",
                "last_event_at",
                "note",
                "filter_source",
                "filter_account",
            ],
        )
        writer.writeheader()
        for step in report.timeline:
            writer.writerow(
                {
                    "label": step.label,
                    "role": step.role,
                    "event_count": step.event_count,
                    "quantity_in": str(step.quantity_in),
                    "quantity_out": str(step.quantity_out),
                    "net_quantity": str(step.net_quantity),
                    "first_event_at": step.first_event_at.isoformat() if step.first_event_at else "",
                    "last_event_at": step.last_event_at.isoformat() if step.last_event_at else "",
                    "note": step.note,
                    "filter_source": report.filter_source or "",
                    "filter_account": report.filter_account or "",
                }
            )
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=hnt-provenance-timeline.csv"},
        )

    @app.get("/api/v1/export/hnt-provenance-events.csv")
    def download_hnt_provenance_events_csv(
        source: str | None = None,
        account: str | None = None,
        from_at: datetime | None = None,
        to_at: datetime | None = None,
    ) -> Response:
        report = V1ParityService(db).hnt_fifo_provenance(
            limit=1000,
            source=source,
            account=account,
            from_at=from_at,
            to_at=to_at,
        )
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "event_time",
                "source",
                "event_type",
                "direction",
                "quantity",
                "account",
                "counterparty_account",
                "current_portfolio_account",
                "fifo_relevant",
                "tx_id",
                "source_ref",
                "filename",
                "note",
                "filter_source",
                "filter_account",
            ],
        )
        writer.writeheader()
        for event in report.events:
            writer.writerow(
                {
                    "event_time": event.event_time.isoformat(),
                    "source": event.source,
                    "event_type": event.event_type,
                    "direction": event.direction,
                    "quantity": str(event.quantity),
                    "account": event.account or "",
                    "counterparty_account": event.counterparty_account or "",
                    "current_portfolio_account": event.current_portfolio_account,
                    "fifo_relevant": event.fifo_relevant,
                    "tx_id": event.tx_id or "",
                    "source_ref": event.source_ref or "",
                    "filename": event.filename or "",
                    "note": event.note,
                    "filter_source": report.filter_source or "",
                    "filter_account": report.filter_account or "",
                }
            )
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=hnt-provenance-events.csv"},
        )

    @app.get("/api/v1/export/binance-fiat-deposits.csv")
    def download_binance_fiat_deposits_csv() -> Response:
        report = PortfolioService(db).fiat_deposit_report(source="binance")
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "Zeit_UTC",
                "Brutto_Zahlungsbeleg",
                "Binance_Gutschrift_EUR",
                "Methode",
                "Status",
                "Binance_Transaction_ID",
                "Quelldatei",
                "Quellzeile",
                "Raw_Object_ID",
            ],
        )
        writer.writeheader()
        for row in report.rows:
            writer.writerow(
                {
                    "Zeit_UTC": row.time_utc.isoformat(),
                    "Brutto_Zahlungsbeleg": row.deposit_amount_original,
                    "Binance_Gutschrift_EUR": row.receive_amount_eur,
                    "Methode": row.method,
                    "Status": row.status,
                    "Binance_Transaction_ID": row.transaction_id,
                    "Quelldatei": row.source_file,
                    "Quellzeile": row.source_row,
                    "Raw_Object_ID": row.raw_object_id,
                }
            )
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=binance-fiat-deposits.csv"},
        )

    def render_tax_lines_csv(*, year: int | None = None) -> str:
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "Datum_Kauf",
                "Datum_Verkauf",
                "Asset",
                "Menge",
                "Anschaffungskosten_EUR",
                "Veraeusserungserloes_EUR",
                "Gewinn_Verlust_EUR",
                "Haltedauer_Tage",
                "Steuerpflichtig",
                "Steuerliche_Behandlung",
            ],
        )
        writer.writeheader()
        for line in TaxService(db).list_tax_lines():
            if year is not None and line.disposed_at.year != year:
                continue
            writer.writerow(
                {
                    "Datum_Kauf": line.acquired_at.isoformat(),
                    "Datum_Verkauf": line.disposed_at.isoformat(),
                    "Asset": line.asset,
                    "Menge": line.quantity,
                    "Anschaffungskosten_EUR": line.acquisition_cost_eur,
                    "Veraeusserungserloes_EUR": line.disposal_proceeds_eur,
                    "Gewinn_Verlust_EUR": line.gain_loss_eur,
                    "Haltedauer_Tage": line.holding_days,
                    "Steuerpflichtig": "ja" if line.holding_days <= 365 else "nein",
                    "Steuerliche_Behandlung": (
                        "steuerpflichtig_bis_365_tage"
                        if line.holding_days <= 365
                        else "steuerfrei_nach_haltefrist"
                    ),
                }
            )
        return output.getvalue()

    @app.get("/api/v1/export/tax-lines.csv")
    def download_tax_lines_csv() -> Response:
        return Response(
            content=render_tax_lines_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=tax-lines.csv"},
        )

    def render_derivative_lines_csv(*, year: int | None = None) -> str:
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "Datum",
                "Quelle",
                "Referenz",
                "Konto",
                "Asset",
                "Menge",
                "Preis_EUR",
                "Ergebnis_EUR",
                "Preisquelle",
            ],
        )
        writer.writeheader()
        for line in DerivativesManager(db).list_lines():
            if year is not None and line.event_time.year != year:
                continue
            writer.writerow(
                {
                    "Datum": line.event_time.isoformat(),
                    "Quelle": line.source,
                    "Referenz": line.source_ref,
                    "Konto": line.account,
                    "Asset": line.asset,
                    "Menge": line.quantity,
                    "Preis_EUR": line.price_eur,
                    "Ergebnis_EUR": line.value_eur,
                    "Preisquelle": line.price_source,
                }
            )
        return output.getvalue()

    @app.get("/api/v1/export/derivative-lines.csv")
    def download_derivative_lines_csv() -> Response:
        return Response(
            content=render_derivative_lines_csv(),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=derivative-lines.csv"
            },
        )

    def render_tax_income_guide_csv(
        *,
        years: list[int] | None = None,
        service: TaxYearService | None = None,
        use_lot_breakdown: bool = False,
    ) -> str:
        service = service or TaxYearService(db)
        selected_years = years if years is not None else service.summary().available_years
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "Jahr",
                "Asset",
                "Event_Typ",
                "Klassifizierung",
                "Events",
                "Menge",
                "Wert_EUR",
                "Fehlende_Bewertungen",
                "Quellen",
            ],
        )
        writer.writeheader()
        for selected_year in selected_years:
            rows = (
                service.income_asset_breakdown_from_lots(selected_year)
                if use_lot_breakdown
                else service.income_report(selected_year).assets
            )
            for row in rows:
                writer.writerow(
                    {
                        "Jahr": selected_year,
                        "Asset": row.asset,
                        "Event_Typ": row.event_type,
                        "Klassifizierung": row.classification,
                        "Events": row.events_count,
                        "Menge": row.quantity,
                        "Wert_EUR": row.income_eur,
                        "Fehlende_Bewertungen": row.missing_value_count,
                        "Quellen": ", ".join(row.sources),
                    }
                )
        return output.getvalue()

    @app.get("/api/v1/export/tax-income-guide.csv")
    def download_tax_income_guide_csv() -> Response:
        return Response(
            content=render_tax_income_guide_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=tax-income-guide.csv"},
        )

    def render_tax_external_inflows_csv(
        *,
        years: list[int] | None = None,
        service: TaxYearService | None = None,
    ) -> str:
        service = service or TaxYearService(db)
        selected_years = years if years is not None else service.summary().available_years
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "Jahr",
                "Zeit_UTC",
                "Status",
                "Asset",
                "Menge",
                "Wert_EUR",
                "Quelle",
                "Konto",
                "TX_ID",
                "Match_Score",
                "Match_Event_ID",
                "Match_Zeit_UTC",
                "Match_Quelle",
                "Match_Konto",
                "Match_Menge",
                "Match_TX_ID",
                "Mengen_Delta",
                "Zeit_Delta_Sekunden",
                "Gruende",
                "Warnungen",
                "Inflow_Event_ID",
            ],
        )
        writer.writeheader()
        for selected_year in selected_years:
            report = service.external_inflow_report(selected_year, limit=10_000)
            for row in report.rows:
                writer.writerow(
                    {
                        "Jahr": selected_year,
                        "Zeit_UTC": row.event_time,
                        "Status": row.status,
                        "Asset": row.asset,
                        "Menge": row.quantity,
                        "Wert_EUR": row.value_eur,
                        "Quelle": row.source,
                        "Konto": row.account,
                        "TX_ID": row.tx_id,
                        "Match_Score": row.best_match_score,
                        "Match_Event_ID": row.matched_event_id,
                        "Match_Zeit_UTC": row.matched_time,
                        "Match_Quelle": row.matched_source,
                        "Match_Konto": row.matched_account,
                        "Match_Menge": row.matched_quantity,
                        "Match_TX_ID": row.matched_tx_id,
                        "Mengen_Delta": row.amount_delta,
                        "Zeit_Delta_Sekunden": row.time_delta_seconds,
                        "Gruende": " | ".join(row.reasons),
                        "Warnungen": " | ".join(row.warnings),
                        "Inflow_Event_ID": row.inflow_event_id,
                    }
                )
        return output.getvalue()

    @app.get("/api/v1/export/tax-external-inflows.csv")
    def download_tax_external_inflows_csv() -> Response:
        return Response(
            content=render_tax_external_inflows_csv(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=tax-external-inflows.csv"},
        )

    def evidence_filename(value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        normalized = text.replace("\\", "/").rstrip("/")
        basename = normalized.rsplit("/", 1)[-1] or normalized
        if basename == "steuerreport_ai_readonly.tmp.sqlite":
            return "read-only-sqlite-evidence"
        return basename

    def render_tax_solana_stablecoin_swap_evidence_csv(
        *,
        years: list[int] | None = None,
        service: TaxYearService | None = None,
        limit: int = 10_000,
    ) -> str:
        service = service or TaxYearService(db)
        selected_years = years if years is not None else service.summary().available_years
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "Jahr",
                "Zeit_UTC",
                "TX_ID",
                "Event_ID",
                "Konto",
                "Asset",
                "Menge",
                "Quote_Asset",
                "Quote_Menge",
                "Klassifizierung",
                "Sicherheit",
                "Stable_Rolle",
                "Steuerwirkung",
                "Stable_Tax_Lines",
                "Stable_Erloes_EUR",
                "Stable_GV_EUR",
                "TX_Assets",
                "TX_Event_Typen",
                "Raw_Belege",
                "Raw_Dateien",
                "Jupiter_Asset_Status",
                "Jupiter_Quote_Status",
                "Preis_EUR",
                "Preisquelle",
                "Preiszeit_UTC",
                "Preisalter_Tage",
                "Preis_Delta_Prozent",
                "FX_Basis_Status",
                "Review_Grund",
                "FX_Review_Grund",
                "Empfehlung",
            ],
        )
        writer.writeheader()
        for selected_year in selected_years:
            swap_report = service.solana_stablecoin_swap_context_review(year=selected_year, limit=limit)
            fx_by_event_id = {
                row.event_id: row
                for row in service.solana_stablecoin_fx_review(year=selected_year, limit=limit).rows
            }
            for row in swap_report.rows:
                fx_row = fx_by_event_id.get(row.event_id)
                writer.writerow(
                    {
                        "Jahr": row.year,
                        "Zeit_UTC": row.event_time,
                        "TX_ID": row.tx_id,
                        "Event_ID": row.event_id,
                        "Konto": row.account,
                        "Asset": row.asset,
                        "Menge": row.quantity,
                        "Quote_Asset": row.quote_asset,
                        "Quote_Menge": row.quote_quantity,
                        "Klassifizierung": row.classification,
                        "Sicherheit": row.confidence,
                        "Stable_Rolle": row.stable_role,
                        "Steuerwirkung": row.expected_tax_effect,
                        "Stable_Tax_Lines": row.stable_tax_lines_count,
                        "Stable_Erloes_EUR": row.stable_disposal_proceeds_eur,
                        "Stable_GV_EUR": row.stable_gain_loss_eur,
                        "TX_Assets": row.tx_assets,
                        "TX_Event_Typen": row.tx_event_types,
                        "Raw_Belege": row.raw_evidence_count,
                        "Raw_Dateien": " | ".join(
                            filename
                            for filename in (evidence_filename(item) for item in row.raw_filenames)
                            if filename
                        ),
                        "Jupiter_Asset_Status": row.jupiter_asset_status,
                        "Jupiter_Quote_Status": row.jupiter_quote_status,
                        "Preis_EUR": fx_row.selected_price_eur if fx_row else None,
                        "Preisquelle": fx_row.selected_price_source if fx_row else None,
                        "Preiszeit_UTC": fx_row.selected_priced_at if fx_row else None,
                        "Preisalter_Tage": fx_row.price_age_days if fx_row else None,
                        "Preis_Delta_Prozent": fx_row.price_delta_pct if fx_row else None,
                        "FX_Basis_Status": fx_row.fx_basis_status if fx_row else None,
                        "Review_Grund": row.review_reason,
                        "FX_Review_Grund": fx_row.review_reason if fx_row else None,
                        "Empfehlung": row.recommended_action,
                    }
                )
        return output.getvalue()

    @app.get("/api/v1/export/tax-solana-stablecoin-swap-evidence.csv")
    def download_tax_solana_stablecoin_swap_evidence_csv(year: int | None = None) -> Response:
        filename = (
            f"tax-year-{year}-solana-stablecoin-swap-evidence.csv"
            if year is not None
            else "tax-solana-stablecoin-swap-evidence.csv"
        )
        return Response(
            content=render_tax_solana_stablecoin_swap_evidence_csv(years=[year] if year is not None else None),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    def render_tax_solana_stablecoin_swap_fifo_lines_csv(
        *,
        years: list[int] | None = None,
        service: TaxYearService | None = None,
        limit: int = 100_000,
    ) -> str:
        service = service or TaxYearService(db)
        selected_years = years if years is not None else service.summary().available_years
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "Jahr",
                "TX_ID",
                "Swap_Event_ID",
                "Tax_Line_ID",
                "Lot_ID",
                "Asset",
                "Menge",
                "Anschaffung_Zeit_UTC",
                "Veraeusserung_Zeit_UTC",
                "Halte_Tage",
                "Steuerpflichtig",
                "Kostenbasis_EUR",
                "Erloes_EUR",
                "GV_EUR",
                "Disposal_Quelle",
                "Disposal_Event_Typ",
                "Disposal_Quote_Asset",
                "Disposal_Quote_Menge",
                "Disposal_Konto",
                "Disposal_Datei",
                "Disposal_Zeile",
                "Acquisition_Event_ID",
                "Acquisition_Quelle",
                "Acquisition_Event_Typ",
                "Acquisition_TX_ID",
                "Acquisition_Konto",
                "Acquisition_Datei",
                "Acquisition_Zeile",
                "Acquisition_Evidence_Status",
                "Acquisition_Klassifizierung",
                "Review_Grund",
            ],
        )
        writer.writeheader()
        for selected_year in selected_years:
            swap_event_ids = {
                row.event_id
                for row in service.solana_stablecoin_swap_context_review(year=selected_year, limit=limit).rows
            }
            fifo_report = service.stablecoin_fifo_review(year=selected_year, limit=limit)
            for row in fifo_report.rows:
                if row.disposal_event_id not in swap_event_ids:
                    continue
                writer.writerow(
                    {
                        "Jahr": row.year,
                        "TX_ID": row.disposal_tx_id,
                        "Swap_Event_ID": row.disposal_event_id,
                        "Tax_Line_ID": row.tax_line_id,
                        "Lot_ID": row.lot_id,
                        "Asset": row.asset,
                        "Menge": row.quantity,
                        "Anschaffung_Zeit_UTC": row.acquired_at,
                        "Veraeusserung_Zeit_UTC": row.disposed_at,
                        "Halte_Tage": row.holding_days,
                        "Steuerpflichtig": "ja" if row.taxable else "nein",
                        "Kostenbasis_EUR": row.acquisition_cost_eur,
                        "Erloes_EUR": row.disposal_proceeds_eur,
                        "GV_EUR": row.gain_loss_eur,
                        "Disposal_Quelle": row.disposal_source,
                        "Disposal_Event_Typ": row.disposal_event_type,
                        "Disposal_Quote_Asset": row.disposal_quote_asset,
                        "Disposal_Quote_Menge": row.disposal_quote_quantity,
                        "Disposal_Konto": row.disposal_account,
                        "Disposal_Datei": evidence_filename(row.disposal_batch_filename),
                        "Disposal_Zeile": row.disposal_row_number,
                        "Acquisition_Event_ID": row.acquisition_event_id,
                        "Acquisition_Quelle": row.acquisition_source,
                        "Acquisition_Event_Typ": row.acquisition_event_type,
                        "Acquisition_TX_ID": row.acquisition_tx_id,
                        "Acquisition_Konto": row.acquisition_account,
                        "Acquisition_Datei": evidence_filename(row.acquisition_batch_filename),
                        "Acquisition_Zeile": row.acquisition_row_number,
                        "Acquisition_Evidence_Status": row.acquisition_evidence_status,
                        "Acquisition_Klassifizierung": row.acquisition_classification,
                        "Review_Grund": row.review_reason,
                    }
                )
        return output.getvalue()

    @app.get("/api/v1/export/tax-solana-stablecoin-swap-fifo-lines.csv")
    def download_tax_solana_stablecoin_swap_fifo_lines_csv(year: int | None = None) -> Response:
        filename = (
            f"tax-year-{year}-solana-stablecoin-swap-fifo-lines.csv"
            if year is not None
            else "tax-solana-stablecoin-swap-fifo-lines.csv"
        )
        return Response(
            content=render_tax_solana_stablecoin_swap_fifo_lines_csv(years=[year] if year is not None else None),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    @app.get("/api/v1/export/evidence-package.zip")
    def download_evidence_package_zip() -> Response:
        report_service = ReportCenterService(db)
        manifest = report_service.evidence_manifest()
        package_index = report_service.evidence_package_index()
        buffer = io.BytesIO()

        def response_body(response: Response) -> bytes:
            content = response.body
            return bytes(content or b"")

        def file_content(file_id: str) -> tuple[str, bytes] | None:
            if file_id == "audit-json":
                return (
                    "audit.json",
                    json.dumps(AuditService(db).export().model_dump(mode="json"), indent=2, ensure_ascii=False).encode("utf-8"),
                )
            if file_id == "elster-prep":
                return (
                    "elster-prep.json",
                    json.dumps(AuditService(db).elster_prep().model_dump(mode="json"), indent=2, ensure_ascii=False).encode("utf-8"),
                )
            if file_id == "tax-payment-overview":
                return (
                    "tax-payment-overview.json",
                    json.dumps(
                        TaxYearService(db).payment_overview().model_dump(mode="json"),
                        indent=2,
                        ensure_ascii=False,
                    ).encode("utf-8"),
                )
            if file_id == "solscan-evidence-trace":
                return (
                    "solscan-evidence-trace.json",
                    json.dumps(
                        SolscanPreflightService().evidence_trace().model_dump(mode="json"),
                        indent=2,
                        ensure_ascii=False,
                    ).encode("utf-8"),
                )
            if file_id == "helium-solana-reward-rpc-evidence":
                return (
                    "helium-solana-reward-rpc-evidence.json",
                    json.dumps(
                        SolscanPreflightService().helium_reward_evidence(),
                        indent=2,
                        ensure_ascii=False,
                    ).encode("utf-8"),
                )
            csv_responses = {
                "review-decisions": ("review-decisions.csv", download_review_decisions_csv),
                "token-risk-documentation": ("token-risk-documentation.csv", download_token_risk_documentation_csv),
                "price-gaps": ("price-gaps.csv", download_price_gaps_csv),
                "price-requirements": ("price-requirements.csv", download_price_requirements_csv),
                "parity-diagnostics": ("parity-diagnostics.csv", download_parity_diagnostics_csv),
                "hnt-provenance-timeline": ("hnt-provenance-timeline.csv", download_hnt_provenance_timeline_csv),
                "hnt-provenance-events": ("hnt-provenance-events.csv", download_hnt_provenance_events_csv),
                "binance-fiat-deposits": ("binance-fiat-deposits.csv", download_binance_fiat_deposits_csv),
                "tax-lines": ("tax-lines.csv", download_tax_lines_csv),
                "derivative-lines": ("derivative-lines.csv", download_derivative_lines_csv),
                "tax-income-guide": ("tax-income-guide.csv", download_tax_income_guide_csv),
                "tax-external-inflows": ("tax-external-inflows.csv", download_tax_external_inflows_csv),
                "tax-solana-stablecoin-swap-evidence": (
                    "tax-solana-stablecoin-swap-evidence.csv",
                    download_tax_solana_stablecoin_swap_evidence_csv,
                ),
                "tax-solana-stablecoin-swap-fifo-lines": (
                    "tax-solana-stablecoin-swap-fifo-lines.csv",
                    download_tax_solana_stablecoin_swap_fifo_lines_csv,
                ),
            }
            if file_id == "hnt-fairspot-timeline":
                return (
                    "hnt-fairspot-timeline.csv",
                    response_body(download_hnt_provenance_timeline_csv(account=ReportCenterService.FAIRSPOT_STAKING_WALLET)),
                )
            if file_id == "hnt-fairspot-events":
                return (
                    "hnt-fairspot-events.csv",
                    response_body(download_hnt_provenance_events_csv(account=ReportCenterService.FAIRSPOT_STAKING_WALLET)),
                )
            csv_entry = csv_responses.get(file_id)
            if csv_entry is None:
                return None
            filename, factory = csv_entry
            return filename, response_body(factory())

        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as package:
            manifest_content = json.dumps(manifest.model_dump(mode="json"), indent=2, ensure_ascii=False).encode("utf-8")
            indexed_files_by_id = {entry.file_id: entry for entry in package_index.files}
            manifest_index_entry = indexed_files_by_id.get("evidence-manifest")
            if manifest_index_entry is not None:
                manifest_index_entry.size_bytes = len(manifest_content)
                manifest_index_entry.sha256 = hashlib.sha256(manifest_content).hexdigest()
            package.writestr(
                "README.txt",
                (
                    "steuerreport-v2 Belegpaket\n"
                    "Read-only Export. Dieses Paket wurde on demand erzeugt und "
                    "schreibt keine Steuerdaten, FIFO-Lots, Imports oder "
                    "Review-Entscheidungen.\n\n"
                    "Ordner:\n"
                    "01_Struktur_Audit\n"
                    "02_Steuerliche_CSVs\n"
                    "03_Review_Entscheidungen\n"
                    "04_Preise_Paritaet\n"
                    "05_HNT_Fairspot\n"
                    "06_Solana_FIFO_Belege\n"
                ),
            )
            package.writestr(
                "00_Manifest/evidence-manifest.json",
                manifest_content,
            )
            for file in manifest.files:
                rendered = file_content(file.file_id)
                if rendered is None:
                    continue
                filename, content = rendered
                if not content:
                    continue
                indexed = next((entry for entry in package_index.files if entry.file_id == file.file_id), None)
                if indexed is None:
                    continue
                path = indexed.path
                package.writestr(path, content)
                indexed.size_bytes = len(content)
                indexed.sha256 = hashlib.sha256(content).hexdigest()
            package.writestr(
                "00_Manifest/package-index.json",
                json.dumps(package_index.model_dump(mode="json"), indent=2, ensure_ascii=False).encode("utf-8"),
            )

        buffer.seek(0)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return Response(
            content=buffer.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename=steuerreport-v2-evidence-{timestamp}.zip"},
        )

    @app.get("/api/v1/export/tax-years/{year}/evidence-package.zip")
    def download_tax_year_evidence_package_zip(year: int) -> Response:
        tax_year_service = TaxYearService(db)
        wallet_fifo_service = WalletFifoPreviewService(db)
        filing_summary = tax_year_service.filing_summary(year)
        evidence_report = tax_year_service.evidence_report(year)
        bmf_closure_appendix = tax_year_service.bmf_closure_appendix(year)
        wallet_fifo_delta = wallet_fifo_service.preview(year=year)
        cex_exchange_outflow_evidence = wallet_fifo_service.cex_exchange_outflow_evidence(
            year,
            source_exchange="bitget",
            target_cex="binance",
            network="SOL",
        )
        cex_exchange_outflow_anchor_feasibility = wallet_fifo_service.cex_exchange_outflow_anchor_feasibility(
            year,
            source_exchange="bitget",
            target_cex="binance",
            network="SOL",
        )
        if wallet_fifo_delta.unmatched_count:
            wallet_fifo_gaps = wallet_fifo_service.gap_diagnosis(year=year, limit=80)
            wallet_fifo_withdrawal_gaps = wallet_fifo_service.withdrawal_gap_trace(year=year)
        else:
            wallet_fifo_gaps = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "year": year,
                "gaps_count": 0,
                "affected_assets": [],
                "affected_pools": [],
                "likely_causes": {},
                "diagnoses": [],
                "methodology": (
                    "Jahrespaket-Shortcut: Wallet-FIFO-Preview meldet unmatched_count=0; "
                    "deshalb sind keine Gap-Diagnosen noetig."
                ),
            }
            wallet_fifo_withdrawal_gaps = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "year": year,
                "traces_count": 0,
                "traces": [],
                "methodology": (
                    "Jahrespaket-Shortcut: Wallet-FIFO-Preview meldet unmatched_count=0; "
                    "deshalb sind keine Exchange-Withdrawal-Gaps offen."
                ),
            }
        required_refs = {line.evidence_ref for line in filing_summary.lines if line.evidence_ref}
        required_refs.update(item.endpoint for item in evidence_report.items if item.required)
        required_refs.add("/api/v1/export/tax-payment-overview.json")
        required_refs.add(f"/api/v1/tax-years/{year}/wallet-fifo-delta")
        required_refs.add(f"/api/v1/tax-years/{year}/wallet-fifo-gaps?limit=80")
        required_refs.add(f"/api/v1/tax-years/{year}/wallet-fifo-withdrawal-gaps")
        if cex_exchange_outflow_evidence.rows_count:
            required_refs.add(
                f"/api/v1/tax-years/{year}/cex-exchange-outflow-evidence?source_exchange=bitget&target_cex=binance&network=SOL"
            )
        if cex_exchange_outflow_anchor_feasibility.decisions_count:
            required_refs.add(
                f"/api/v1/tax-years/{year}/cex-exchange-outflow-anchor-feasibility?source_exchange=bitget&target_cex=binance&network=SOL"
            )
        solana_swap_context = tax_year_service.solana_stablecoin_swap_context_review(year, limit=1)
        if solana_swap_context.events_count:
            required_refs.add("/api/v1/export/tax-solana-stablecoin-swap-evidence.csv")
        if solana_swap_context.stable_tax_lines_count:
            required_refs.add("/api/v1/export/tax-solana-stablecoin-swap-fifo-lines.csv")
        buffer = io.BytesIO()

        def response_body(response: Response) -> bytes:
            return bytes(response.body or b"")

        files: list[tuple[str, bytes, str]] = [
            (
                f"02_Steuerliche_CSVs/tax-year-{year}-filing-summary.json",
                json.dumps(filing_summary.model_dump(mode="json"), indent=2, ensure_ascii=False).encode("utf-8"),
                f"/api/v1/tax-years/{year}/filing-summary",
            ),
            (
                f"02_Steuerliche_CSVs/tax-year-{year}-evidence.json",
                json.dumps(evidence_report.model_dump(mode="json"), indent=2, ensure_ascii=False).encode("utf-8"),
                f"/api/v1/tax-years/{year}/evidence",
            ),
            (
                f"02_Steuerliche_CSVs/tax-year-{year}-bmf-closure-appendix.json",
                json.dumps(
                    bmf_closure_appendix.model_dump(mode="json"),
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
                f"/api/v1/tax-years/{year}/bmf-closure-appendix",
            ),
            (
                f"03_Review_Entscheidungen/tax-year-{year}-review-decisions.json",
                json.dumps(
                    {
                        "year": year,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "decisions_count": len(filing_summary.review_decisions),
                        "decisions": [
                            decision.model_dump(mode="json")
                            for decision in filing_summary.review_decisions
                        ],
                        "source_endpoint": "/api/v1/export/review-decisions.csv",
                        "methodology": (
                            "Jahresbezogener Auszug aus bestehenden Review-Entscheidungen. "
                            "Die Datei schreibt keine Entscheidungen und erzeugt keine Steuerdaten."
                        ),
                    },
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
                "/api/v1/export/review-decisions.csv",
            ),
            (
                "02_Steuerliche_CSVs/tax-payment-overview.json",
                json.dumps(
                    tax_year_service.payment_overview(years=[year]).model_dump(mode="json"),
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
                "/api/v1/export/tax-payment-overview.json",
            ),
            (
                f"06_Solana_FIFO_Belege/tax-year-{year}-wallet-fifo-delta.json",
                json.dumps(wallet_fifo_delta.model_dump(mode="json"), indent=2, ensure_ascii=False).encode("utf-8"),
                f"/api/v1/tax-years/{year}/wallet-fifo-delta",
            ),
            (
                f"06_Solana_FIFO_Belege/tax-year-{year}-wallet-fifo-gaps.json",
                json.dumps(
                    wallet_fifo_gaps.model_dump(mode="json") if hasattr(wallet_fifo_gaps, "model_dump") else wallet_fifo_gaps,
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
                f"/api/v1/tax-years/{year}/wallet-fifo-gaps?limit=80",
            ),
            (
                f"06_Solana_FIFO_Belege/tax-year-{year}-wallet-fifo-withdrawal-gaps.json",
                json.dumps(
                    wallet_fifo_withdrawal_gaps.model_dump(mode="json")
                    if hasattr(wallet_fifo_withdrawal_gaps, "model_dump")
                    else wallet_fifo_withdrawal_gaps,
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
                f"/api/v1/tax-years/{year}/wallet-fifo-withdrawal-gaps",
            ),
            (
                f"06_Solana_FIFO_Belege/tax-year-{year}-cex-exchange-outflow-evidence.json",
                json.dumps(
                    cex_exchange_outflow_evidence.model_dump(mode="json"),
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
                f"/api/v1/tax-years/{year}/cex-exchange-outflow-evidence?source_exchange=bitget&target_cex=binance&network=SOL",
            ),
            (
                f"06_Solana_FIFO_Belege/tax-year-{year}-cex-exchange-outflow-anchor-feasibility.json",
                json.dumps(
                    cex_exchange_outflow_anchor_feasibility.model_dump(mode="json"),
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
                f"/api/v1/tax-years/{year}/cex-exchange-outflow-anchor-feasibility?source_exchange=bitget&target_cex=binance&network=SOL",
            ),
        ]
        csv_factories = {
            "/api/v1/export/tax-lines.csv": (
                f"02_Steuerliche_CSVs/tax-year-{year}-tax-lines.csv",
                lambda: render_tax_lines_csv(year=year).encode("utf-8"),
            ),
            "/api/v1/export/tax-income-guide.csv": (
                f"02_Steuerliche_CSVs/tax-year-{year}-tax-income-guide.csv",
                lambda: render_tax_income_guide_csv(
                    years=[year],
                    service=tax_year_service,
                    use_lot_breakdown=True,
                ).encode("utf-8"),
            ),
            "/api/v1/export/derivative-lines.csv": (
                f"02_Steuerliche_CSVs/tax-year-{year}-derivative-lines.csv",
                lambda: render_derivative_lines_csv(year=year).encode("utf-8"),
            ),
            "/api/v1/export/tax-external-inflows.csv": (
                f"02_Steuerliche_CSVs/tax-year-{year}-tax-external-inflows.csv",
                lambda: render_tax_external_inflows_csv(
                    years=[year],
                    service=tax_year_service,
                ).encode("utf-8"),
            ),
            "/api/v1/export/tax-solana-stablecoin-swap-evidence.csv": (
                f"06_Solana_FIFO_Belege/tax-year-{year}-solana-stablecoin-swap-evidence.csv",
                lambda: render_tax_solana_stablecoin_swap_evidence_csv(
                    years=[year],
                    service=tax_year_service,
                ).encode("utf-8"),
            ),
            "/api/v1/export/tax-solana-stablecoin-swap-fifo-lines.csv": (
                f"06_Solana_FIFO_Belege/tax-year-{year}-solana-stablecoin-swap-fifo-lines.csv",
                lambda: render_tax_solana_stablecoin_swap_fifo_lines_csv(
                    years=[year],
                    service=tax_year_service,
                ).encode("utf-8"),
            ),
            "/api/v1/export/hnt-provenance-events.csv": (
                f"05_HNT_Fairspot/tax-year-{year}-hnt-provenance-events.csv",
                lambda: response_body(download_hnt_provenance_events_csv(
                    from_at=datetime(year, 1, 1, tzinfo=timezone.utc),
                    to_at=datetime(year + 1, 1, 1, tzinfo=timezone.utc),
                )),
            ),
            "/api/v1/export/hnt-provenance-timeline.csv": (
                f"05_HNT_Fairspot/tax-year-{year}-hnt-provenance-timeline.csv",
                lambda: response_body(download_hnt_provenance_timeline_csv(
                    from_at=datetime(year, 1, 1, tzinfo=timezone.utc),
                    to_at=datetime(year + 1, 1, 1, tzinfo=timezone.utc),
                )),
            ),
        }
        for endpoint, (path, factory) in csv_factories.items():
            if endpoint in required_refs:
                files.append((path, factory(), endpoint))

        package_files = []
        for path, content, endpoint in files:
            package_files.append(
                {
                    "path": path,
                    "source_endpoint": endpoint,
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
        manifest = {
            "label": f"steuerreport-v2-tax-year-{year}-evidence-package",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "year": year,
            "export_ready": filing_summary.export_ready,
            "filing_summary": filing_summary.plain_language_summary,
            "required_refs": sorted(required_refs),
            "files": package_files,
            "methodology": (
                "Read-only Jahrespaket aus Steuerjahr-Erklaerung, Jahres-Belegkarte "
                "Wallet-FIFO-Jahresstatus und relevanten Exportdateien. Es schreibt "
                "keine Steuerdaten, FIFO-Lots, Imports, Preise oder Review-Entscheidungen."
            ),
        }

        with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as package:
            package.writestr(
                "README.txt",
                (
                    f"steuerreport-v2 Jahres-Belegpaket {year}\n"
                    "Read-only Export. Dieses Paket wurde on demand erzeugt und "
                    "schreibt keine Steuerdaten, FIFO-Lots, Imports, Preise oder "
                    "Review-Entscheidungen.\n\n"
                    f"Kurzfassung: {filing_summary.plain_language_summary}\n"
                    f"Wallet-FIFO: {wallet_fifo_delta.status}, "
                    f"offene Luecken {wallet_fifo_delta.unmatched_count}, "
                    f"Transfers {wallet_fifo_delta.transfer_traces_count}\n"
                ),
            )
            package.writestr(
                "00_Manifest/year-evidence-manifest.json",
                json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"),
            )
            for path, content, _endpoint in files:
                if content:
                    package.writestr(path, content)

        buffer.seek(0)
        return Response(
            content=buffer.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f"attachment; filename=steuerreport-v2-tax-year-{year}-evidence.zip"},
        )

    @app.post("/api/v1/ai/tasks")
    def create_ai_task(payload: AiTaskCreate) -> ApiResponse[AiTask]:
        return ApiResponse(data=AiService(db).create_task(payload))

    @app.get("/api/v1/ai/tasks")
    def list_ai_tasks() -> ApiResponse[list[AiTask]]:
        return ApiResponse(data=AiService(db).list_tasks())

    @app.get("/api/v1/ai/local-year-package-qa")
    def local_ai_year_package_qa() -> ApiResponse[LocalAiYearPackageQaStatus]:
        return ApiResponse(data=AiService(db).local_year_package_qa_status())

    @app.get("/api/v1/ai/local-year-package-qa/artifacts/{artifact}")
    def download_local_ai_year_package_qa_artifact(artifact: str) -> Response:
        rendered = AiService(db).local_year_package_qa_artifact(artifact)
        if rendered is None:
            payload = ApiResponse(
                status="warning",
                data={"artifact": artifact, "available": False},
                warnings=[
                    {
                        "code": "local_ai_year_package_qa_artifact_missing",
                        "message": f"Lokales KI-QA-Artefakt nicht gefunden: {artifact}",
                        "field": "artifact",
                    }
                ],
            )
            return Response(
                content=payload.model_dump_json(),
                media_type="application/json",
                status_code=404,
            )
        filename, media_type, content = rendered
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    @app.get("/api/v1/ai/local-asset-fifo-correction-review")
    def local_ai_asset_fifo_correction_review() -> ApiResponse[LocalAiAssetFifoCorrectionStatus]:
        return ApiResponse(data=AiService(db).local_asset_fifo_correction_status())

    @app.get("/api/v1/ai/local-asset-fifo-correction-review/artifacts/{artifact}")
    def download_local_ai_asset_fifo_correction_artifact(artifact: str) -> Response:
        rendered = AiService(db).local_asset_fifo_correction_artifact(artifact)
        if rendered is None:
            payload = ApiResponse(
                status="warning",
                data={"artifact": artifact, "available": False},
                warnings=[
                    {
                        "code": "local_ai_asset_fifo_correction_artifact_missing",
                        "message": f"Lokales Asset-FIFO-KI-Artefakt nicht gefunden: {artifact}",
                        "field": "artifact",
                    }
                ],
            )
            return Response(
                content=payload.model_dump_json(),
                media_type="application/json",
                status_code=404,
            )
        filename, media_type, content = rendered
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    @app.get("/api/v1/ai/local-wallet-fifo-provenance-review")
    def local_ai_wallet_fifo_provenance_review() -> ApiResponse[LocalAiWalletFifoProvenanceStatus]:
        return ApiResponse(data=AiService(db).local_wallet_fifo_provenance_status())

    @app.get("/api/v1/ai/local-wallet-fifo-provenance-review/artifacts/{artifact}")
    def download_local_ai_wallet_fifo_provenance_artifact(artifact: str) -> Response:
        rendered = AiService(db).local_wallet_fifo_provenance_artifact(artifact)
        if rendered is None:
            payload = ApiResponse(
                status="warning",
                data={"artifact": artifact, "available": False},
                warnings=[
                    {
                        "code": "local_ai_wallet_fifo_provenance_artifact_missing",
                        "message": f"Lokales Wallet-FIFO-Provenance-KI-Artefakt nicht gefunden: {artifact}",
                        "field": "artifact",
                    }
                ],
            )
            return Response(
                content=payload.model_dump_json(),
                media_type="application/json",
                status_code=404,
            )
        filename, media_type, content = rendered
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    @app.delete("/api/v1/ai/tasks/{task_id}")
    def delete_ai_task(task_id: str) -> ApiResponse[AiTaskDeleteResult]:
        deleted = AiService(db).delete_task(task_id)
        warnings = []
        if not deleted:
            warnings.append(
                {
                    "code": "ai_task_not_found",
                    "message": f"KI-Aufgabe nicht gefunden: {task_id}",
                    "field": "task_id",
                }
            )
        return ApiResponse(
            status="warning" if warnings else "ok",
            data=AiTaskDeleteResult(task_id=task_id, deleted=deleted),
            warnings=warnings,
        )

    return app


app = create_app()
