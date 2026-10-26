from __future__ import annotations

from steuerreport_v2.paths import PROJECT_ROOT as SOFTWARE_ROOT

from steuerreport_v2.paths import configured_import_path, PROJECT_ROOT

from steuerreport_v2.private_settings import private_config_path, private_value
from steuerreport_v2.contracts.installation import InstallationSettings, InstallationSettingsWrite, PrivateConfigDocument, PrivateConfigWrite, ProviderSecretWrite
from steuerreport_v2.domain.installation import InstallationSettingsError, InstallationSettingsService

import csv
import gzip
import hashlib
import html
import io
import json
import os
from pathlib import Path
from threading import Lock, RLock
from time import monotonic
from uuid import uuid4
from urllib.parse import urlsplit, urlencode
from urllib.parse import quote
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from fastapi.routing import APIRoute

from steuerreport_v2 import __version__
from steuerreport_v2.contracts.workspace import ActivityQuery, ActivityPage, ActivityDetail, ActivityExport, WorkspaceSources, WorkspaceSourceDetail, WorkspaceStatus
from steuerreport_v2.contracts.workspace import WorkspaceReviewPage, WorkspaceReviewQuery
from steuerreport_v2.domain.workspace import ActivityService, WorkspaceService
from steuerreport_v2.api.openapi import OPENAPI_TAGS, configure_openapi_routes
from steuerreport_v2.contracts.api_meta import ApiCapabilities
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
from steuerreport_v2.contracts.ai_changes import (
    AiChangeApply, AiChangeDraft, AiChangeGenerate, AiChangePreview,
    AiChangeRevert, AiChangeSet, AiDataContext, AiDataQuery,
)
from steuerreport_v2.domain.ai_changes import AiChangeError, AiChangeService
from steuerreport_v2.db.ai_corrections import CorrectionConflict
from steuerreport_v2.contracts.ai_agents import AiAgentsStatus, AiAgentsWrite
from steuerreport_v2.domain.ai_agents import AiAgentError, AiAgentService
from steuerreport_v2.contracts.audit import AuditExport, ElsterPrepExport
from steuerreport_v2.contracts.binance_earn import (
    BinanceAssetDividendPreview,
    BinanceCapitalWithdrawalPreview,
    BinanceEarnHistoryApiPreview,
)
from steuerreport_v2.contracts.binance_earn_import import (
    BinanceAssetDividendApiImportRequest,
    BinanceAssetDividendApiImportResult,
    BinanceCapitalWithdrawalApiImportRequest,
    BinanceCapitalWithdrawalApiImportResult,
    BinanceEarnApiImportRequest,
    BinanceEarnApiImportResult,
    BinanceEarnHarvestImportRequest,
    BinanceEarnHarvestImportResult,
)
from steuerreport_v2.contracts.bitget import BitgetWithdrawalPreview
from steuerreport_v2.contracts.bitget_strategy_basis_decisions import (
    BitgetStrategyBasisDecisionReport,
    BitgetStrategyBasisDecisionRequest,
    BitgetStrategyBasisDecisionResult,
)
from steuerreport_v2.contracts.bitget_strategy_fifo import (
    BitgetStrategyFifoGapReport,
)
from steuerreport_v2.contracts.bitget_strategy_reconstruction import (
    BitgetStrategyBasisReconstructionReport,
    BitgetStrategyReferencePriceBackfillRequest,
    BitgetStrategyReferencePriceBackfillResult,
)
from steuerreport_v2.contracts.bitget_import import (
    BitgetWithdrawalApiImportRequest,
    BitgetWithdrawalApiImportResult,
)
from steuerreport_v2.contracts.blockpit_solana import (
    BlockpitSolanaPreflightReport,
    BlockpitSolanaPriceProbeRequest,
    BlockpitSolanaPriceProbeResult,
)
from steuerreport_v2.contracts.business_inventory import (
    BusinessRewardInventoryReviewReport,
)
from steuerreport_v2.contracts.common import ApiMessage, ApiResponse
from steuerreport_v2.contracts.cockpit import CockpitSummary
from steuerreport_v2.contracts.connectors import (
    ConnectorCatalogReport,
    ConnectorConnection,
    MobileConnectorPairing,
    MobileConnectorPairingRequest,
    MobileConnectorScope,
    MobileConnectorSession,
    MobileConnectorSessionExchangeRequest,
    MobileConnectorSessionToken,
    WalletOwnershipChallenge,
    WalletOwnershipChallengeRequest,
    WalletOwnershipVerificationRequest,
    WalletOwnershipVerificationResult,
)
from steuerreport_v2.contracts.coverage import ImportCoverageSummary
from steuerreport_v2.contracts.mobile_documents import (
    MobileDocumentInboxReport,
    MobileDocumentKind,
    MobileDocumentUploadResult,
)
from steuerreport_v2.contracts.derivatives import (
    DerivativeLine,
    DerivativeRunResult,
    DerivativeRunSummary,
)
from steuerreport_v2.contracts.divorce import DivorceEqualizationSummary
from steuerreport_v2.contracts.divorce_service_routes import (
    DivorceServiceRouteDecisionRequest,
    DivorceServiceRouteDecisionResult,
    DivorceServiceRouteEvidenceRefreshRequest,
    DivorceServiceRouteEvidenceReport,
)
from steuerreport_v2.contracts.divorce_inheritance import (
    BankCamtUploadResult,
    CoinbaseConnectorStatus,
    CoinbaseValuationDecisionRequest,
    CoinbaseValuationDecisionResult,
    DivorceInheritanceOriginReport,
    InheritanceBankCreditCandidateReport,
    InheritanceBankCreditDecisionRequest,
    InheritanceBankCreditDecisionResult,
    InheritanceDocumentConnectorStatus,
    InheritanceDocumentCreditDecisionRequest,
    InheritanceDocumentCreditDecisionResult,
    InheritanceDocumentDecisionRequest,
    InheritanceDocumentDecisionResult,
    InheritanceDocumentUploadResult,
    SparkasseStatementConnectorStatus,
    TradeRepublicConnectorStatus,
    TradeRepublicDocumentUploadResult,
    TradeRepublicValuationDecisionRequest,
    TradeRepublicValuationDecisionResult,
)
from steuerreport_v2.contracts.valuation_runs import (
    DivorceValuationRunReport,
    DivorceValuationRunRequest,
)
from steuerreport_v2.contracts.events import CanonicalEvent
from steuerreport_v2.contracts.bmf_event_evidence import (
    BmfFifoEventEvidenceReport,
    BmfFifoEventEvidenceRunRequest,
)
from steuerreport_v2.contracts.bmf_event_price_remediation import (
    BmfEventPriceRemediationReport,
    BmfEventPriceRemediationRunRequest,
)
from steuerreport_v2.contracts.bmf_fifo_staging import (
    BmfCombinedFifoStagingReport,
    BmfFifoStagingRunRequest,
)
from steuerreport_v2.contracts.fairspot_staking import (
    FairspotStakingReconciliationReport,
)
from steuerreport_v2.contracts.moonpay_receipts import (
    MoonpayReceiptReport,
    MoonpayReceiptUpsertRequest,
    MoonpayReceiptUpsertResult,
)
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
    PortfolioValueHistoryReport,
    PortfolioValuationAuditReport,
    PortfolioWalletHistoryImportRequest,
    PortfolioWalletHistoryImportResult,
)
from steuerreport_v2.contracts.pionex_reconciliation import (
    PionexHntReconciliationReport,
)
from steuerreport_v2.contracts.cross_cex_evidence import (
    CrossCexTransferEvidenceReport,
)
from steuerreport_v2.contracts.prices import (
    AsOfPriceGateBackfillRequest,
    AsOfPriceGateBackfillResult,
    AsOfPriceGateReport,
    AsOfTokenValuationDecisionRequest,
    AsOfTokenValuationDecisionResult,
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
from steuerreport_v2.contracts.product_readiness import ProductReadinessReport
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
from steuerreport_v2.contracts.service_swap_tax_mapping import (
    ServiceSwapTaxMappingReport,
)
from steuerreport_v2.contracts.reports import ReportCenterStatus
from steuerreport_v2.contracts.solscan import (
    SolanaRpcProbeRequest,
    SolanaRpcProbeResult,
    SolscanEvidenceTraceReport,
    SolscanTokenPreflightReport,
)
from steuerreport_v2.contracts.solana_staking_position import (
    SolanaStakingPositionReconciliationReport,
)
from steuerreport_v2.contracts.legal_research import (
    LegalResearchConfig,
    LegalResearchFreshnessReport,
)
from steuerreport_v2.contracts.source_registry import (
    SourceRegistryConfig,
    SourceRegistryRunReport,
)
from steuerreport_v2.contracts.sources import (
    BinanceEarnHistoryPreflightReport,
    BinanceReconciliationEvidenceReport,
    SourceConnectorDiagnosticsReport,
    SourceDetail,
    SourceOverview,
    SourceReconciliationBreakdown,
)
from steuerreport_v2.contracts.swap_valuation import (
    CryptoSwapFifoParallelPreviewReport,
    CryptoSwapFifoParallelRunRequest,
    CryptoSwapValuationReviewReport,
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
    TaxBmfAmendmentWorklist,
    TaxBmfComplianceMatrix,
    TaxBmfClosureBacklogReport,
    TaxBmfClosureBacklogSnapshot,
    TaxBmfFinalizationMatrix,
    TaxBmfFilingReadinessReport,
    TaxBmfFilingReadinessSnapshot,
    TaxBmfPriorFilingComparison,
    TaxBmfPriorFilingDeclaredAmounts,
    TaxBmfPriorFilingDeclaredAmountsWrite,
    TaxBmfPriorFilingDeclaredAmountsWriteResult,
    TaxBmfSubmissionGuide,
    TaxRewardBmfRecheckReport,
    TaxMethodologyReport,
    TaxMethodologySummary,
    TaxTimePrecisionAudit,
    TaxYearComplianceStatus,
)
from steuerreport_v2.contracts.tax_wallet_fifo import (
    LegacyHeliumOverviewReport,
    WalletFifoGapDiagnosisReport,
    WalletFifoInternalTransferCarryReport,
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
    WalletFifoSolanaProgramSettlementEvidenceReport,
    WalletFifoSolanaServiceSwapEvidenceReport,
    WalletFifoSolanaRawBmfEvidenceDrilldownReport,
    WalletFifoSolanaRawBmfEvidenceSummaryReport,
    WalletFifoSolanaRawProvenancePriorityReport,
    WalletFifoSolanaRawProvenanceSenderSummaryReport,
    WalletFifoSolanaSenderClusterOutflowReport,
    WalletFifoSolanaSenderClusterReport,
    WalletFifoSolanaOriginTraceReport,
    WalletFifoWithdrawalGapReport,
)
from steuerreport_v2.contracts.wallet_fifo_runs import (
    WalletFifoMethodAcceptanceReport,
    WalletFifoMethodAcceptanceRequest,
    WalletFifoMethodAcceptanceResult,
    WalletFifoMethodDeltaEvent,
    WalletFifoMethodDeltaExplanationReport,
    WalletFifoParallelRunReport,
    WalletFifoParallelRunRequest,
)
from steuerreport_v2.contracts.wallet_fifo_migrations import (
    WalletFifoMigrationApplyReadinessReport,
    WalletFifoMigrationApplyReport,
    WalletFifoMigrationApplyRequest,
    WalletFifoMigrationRehearsalReport,
    WalletFifoMigrationRehearsalRequest,
)
from steuerreport_v2.contracts.tax_years import (
    TaxExternalInflowReport,
    TaxIncomeReport,
    TaxLossRealizationPlanner,
    TaxPaymentOverview,
    TaxRewardTradingSeparationReport,
    TaxHeliumSwapContextReview,
    TaxHeliumSwapEvidenceReview,
    TaxYearGainLossRealityCheck,
    TaxYearGainEvidenceAcquisitionEventDeltaReview,
    TaxYearGainEvidenceEventDeltaReview,
    TaxYearGainEvidencePriceDeltaDrilldown,
    TaxYearGainEvidenceReview,
    TaxYearBmfClosureAppendix,
    TaxYearAssetFifoCorrectionReviewReport,
    TaxYearAssetFifoDrilldown,
    TaxYearAssetFifoPlausibilityReport,
    TaxYearDetail,
    TaxYearDriverReport,
    TaxYearEvidenceReport,
    TaxYearCorrectionMap,
    TaxYearsFilingClosureOverview,
    TaxYearFilingMatrix,
    TaxYearFilingSummary,
    TaxYearTurnoverAudit,
    TaxYearsCorrectionMap,
    TaxYearsTurnoverAuditSummary,
    TaxSolanaProgramIncomeReview,
    TaxSolanaStablecoinFxReview,
    TaxSolanaStablecoinSwapContextReview,
    TaxStablecoinFifoReview,
    TaxStablecoinQuoteLegReview,
    TaxYearsSummary,
)
from steuerreport_v2.contracts.tax_filing_snapshots import (
    TaxFilingSnapshotCaptureRequest,
    TaxFilingSnapshotCaptureResult,
    TaxFilingSnapshotComparison,
    TaxFilingSnapshotList,
    TaxFilingSnapshotUsageConfirmationRequest,
    TaxFilingSnapshotUsageConfirmationResult,
)
from steuerreport_v2.contracts.tax_filing_audit import TaxFilingAuditReport
from steuerreport_v2.contracts.transfers import TransferCandidateReport
from steuerreport_v2.contracts.valuation import (
    PriceCoverageReport,
    PriceQualityBinanceNormalizerReport,
    PriceQualityClosureCandidateReport,
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
    PriceQualityStablecoinFxAnchorApplyRequest,
    PriceQualityStablecoinFxAnchorApplyResult,
    PriceQualityStablecoinFxAnchorPreviewDecisionCreate,
    PriceQualityStablecoinFxAnchorPreviewLatest,
    PriceQualityStablecoinFxReplacementImpactReport,
    PriceQualityStablecoinFxReplacementReport,
    PriceQualityStablecoinFxTaxImpactDecisionCreate,
    PriceQualityStablecoinFxTaxImpactDecisionResult,
    PriceQualityStablecoinFxTaxImpactLatestReport,
    PriceRequirementReport,
)
from steuerreport_v2.contracts.wallet_monthly import WalletMonthlyPreflightReport
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.admin import AdminService
from steuerreport_v2.domain.api_meta import ApiCapabilitiesService
from steuerreport_v2.domain.ai import AiService
from steuerreport_v2.domain.ai_provider import AiProviderError, AiProviderService
from steuerreport_v2.contracts.ai import AiModel, AiProbeResult, AiProviderStatus, AiProviderWrite, AiTaskExecute
from steuerreport_v2.domain.as_of_price_gate import AsOfPriceGateService
from steuerreport_v2.domain.audit import AuditService
from steuerreport_v2.domain.binance_earn import BinanceEarnHistoryService
from steuerreport_v2.domain.bitget import BitgetWalletHistoryService
from steuerreport_v2.domain.bitget_strategy_basis_decisions import (
    BitgetStrategyBasisDecisionService,
)
from steuerreport_v2.domain.bitget_strategy_fifo import BitgetStrategyFifoGapService
from steuerreport_v2.domain.bitget_strategy_reconstruction import (
    BitgetStrategyBasisReconstructionService,
)
from steuerreport_v2.domain.bmf_compliance import BmfComplianceMatrixService
from steuerreport_v2.domain.bmf_fifo_staging import BmfCombinedFifoStagingService
from steuerreport_v2.domain.bmf_event_evidence import BmfFifoEventEvidenceService
from steuerreport_v2.domain.bmf_event_price_remediation import (
    BmfEventPriceRemediationService,
)
from steuerreport_v2.domain.business_inventory import (
    BusinessRewardInventoryReviewService,
)
from steuerreport_v2.domain.blockpit_solana_preflight import (
    BlockpitSolanaPreflightService,
)
from steuerreport_v2.domain.cockpit import CockpitService
from steuerreport_v2.domain.connectors import ConnectorAccessPolicy, ConnectorService
from steuerreport_v2.domain.mobile_documents import MobileDocumentInboxService
from steuerreport_v2.domain.cross_cex_evidence import (
    CrossCexTransferEvidenceService,
)
from steuerreport_v2.domain.derivatives import DerivativesManager
from steuerreport_v2.domain.divorce import DivorceEqualizationService
from steuerreport_v2.domain.divorce_service_routes import (
    DivorceServiceRouteEvidenceService,
)
from steuerreport_v2.domain.divorce_inheritance import (
    DivorceInheritanceOriginService,
)
from steuerreport_v2.domain.valuation_runs import DivorceValuationRunService
from steuerreport_v2.domain.exports import ExportService
from steuerreport_v2.domain.fairspot_staking import (
    FairspotStakingReconciliationService,
)
from steuerreport_v2.domain.moonpay_receipts import MoonpayReceiptService
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
from steuerreport_v2.domain.pionex_reconciliation import (
    PionexHntReconciliationService,
)
from steuerreport_v2.domain.product_readiness import ProductReadinessService
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.review import ReviewService
from steuerreport_v2.domain.reports import ReportCenterService
from steuerreport_v2.domain.solscan_preflight import SolscanPreflightService
from steuerreport_v2.domain.solana_staking_position import (
    SolanaStakingPositionReconciliationService,
)
from steuerreport_v2.domain.legal_research import LegalResearchService
from steuerreport_v2.domain.sources import SourceService
from steuerreport_v2.domain.swap_valuation import CryptoSwapValuationReviewService
from steuerreport_v2.domain.swap_valuation_parallel import (
    CryptoSwapFifoParallelPreviewService,
)
from steuerreport_v2.domain.source_registry import SourceRegistryService
from steuerreport_v2.domain.service_swap_tax_mapping import (
    ServiceSwapTaxMappingService,
)
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_methodology import TaxMethodologyService
from steuerreport_v2.domain.tax_time import (
    TaxTimePolicyService,
    event_reporting_year_sql,
    reporting_tax_year,
    reporting_year_utc_bounds,
)
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService
from steuerreport_v2.domain.wallet_fifo_acceptance import (
    WalletFifoMethodAcceptanceService,
)
from steuerreport_v2.domain.wallet_fifo_runs import WalletFifoParallelRunService
from steuerreport_v2.domain.wallet_fifo_migrations import (
    WalletFifoMigrationApplyService,
    WalletFifoMigrationRehearsalService,
)
from steuerreport_v2.domain.tax_years import TaxYearService
from steuerreport_v2.domain.tax_filing_snapshots import (
    SUBMISSION_CONFIRMATION_TEXT,
    TaxFilingSnapshotError,
    TaxFilingSnapshotService,
)
from steuerreport_v2.domain.tax_filing_audit import (
    TaxFilingAuditError,
    TaxFilingAuditService,
)
from steuerreport_v2.domain.transfers import TransferCandidateService
from steuerreport_v2.domain.valuation import PriceCoverageService, PriceQualityService
from steuerreport_v2.domain.v1_fx_cache_importer import V1FxCacheImporter
from steuerreport_v2.domain.wallet_monthly_preflight import (
    WalletMonthlyPreflightService,
)
from steuerreport_v2.importers.csv_raw_importer import CsvRawImporter
from steuerreport_v2.importers.file_raw_importer import FileRawImporter
from steuerreport_v2.importers.raw_normalizer import RawNormalizer
from steuerreport_v2.importers.source_profiles import list_profiles
from steuerreport_v2.importers.wiso_reference_importer import WisoReferenceImporter
from steuerreport_v2.ledger.balance import BalanceLedgerBuilder

HELIUM_SWAP_ALCHEMY_AUDIT_PATH = (
    Path(PROJECT_ROOT)
    / "var"
    / "helium_swap_alchemy_audits"
    / "latest_all_years_helium_swap_alchemy_audit.json"
)
SOLANA_TX_ALCHEMY_AUDIT_PATH = (
    Path(PROJECT_ROOT)
    / "var"
    / "solana_tx_alchemy_audits"
    / "latest_solana_rpc_tx_alchemy_audit.json"
)
SOLANA_FAILED_TX_TAX_IMPACT_PATH = (
    Path(PROJECT_ROOT)
    / "var"
    / "solana_failed_tx_tax_impacts"
    / "latest_solana_failed_tx_tax_impact.json"
)
ALL_TRANSACTION_EVIDENCE_MATRIX_PATH = (
    Path(PROJECT_ROOT)
    / "var"
    / "all_transaction_evidence_matrices"
    / "latest_all_transaction_evidence_matrix.json"
)
ALL_TRANSACTION_EVIDENCE_CLOSURE_PATH = (
    Path(PROJECT_ROOT)
    / "var"
    / "all_transaction_evidence_closures"
    / "latest_all_transaction_evidence_closure.json"
)
ALL_TRANSACTION_OPEN_DETAIL_REVIEW_PATH = (
    Path(PROJECT_ROOT)
    / "var"
    / "all_transaction_open_detail_reviews"
    / "latest_all_transaction_open_detail_review.json"
)
ALL_TRANSACTION_DECISION_CANDIDATES_PATH = (
    Path(PROJECT_ROOT)
    / "var"
    / "all_transaction_decision_candidates"
    / "latest_all_transaction_decision_candidates.json"
)


def build_health_payload(db: DuckDbStore) -> dict:
    return {
        "app_version": __version__,
        **db.health(),
    }


def _import_preview_warnings(
    preview: CsvImportPreview, content_field: str
) -> list[dict[str, str]]:
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


def _import_preview_errors(
    preview: CsvImportPreview, content_field: str
) -> list[dict[str, str]]:
    return [
        warning
        for warning in _import_preview_warnings(preview, content_field)
        if warning["code"] in {"missing_required_columns", "empty_import_file"}
    ]


def create_app(store: DuckDbStore | None = None) -> FastAPI:
    app = FastAPI(
        title="Steuerreport V2 API",
        summary="Nachvollziehbare Krypto-Steuer-, FIFO-, Portfolio- und Beleg-API",
        description=(
            "Versionierte V2-API fuer das Web-Cockpit und kuenftige Android-/iOS-Clients. "
            "Decimal-Werte werden verlustfrei als JSON-Strings transportiert. Die API ist "
            "ohne vorgeschaltete Authentifizierung ausschliesslich fuer ein vertrauenswuerdiges "
            "LAN bestimmt und darf nicht direkt im Internet exponiert werden."
        ),
        version=__version__,
        openapi_tags=OPENAPI_TAGS,
        servers=[{"url": "/", "description": "Aktueller Steuerreport-V2-API-Host"}],
    )
    cors_origins = [value.strip() for value in os.environ.get("STEUERREPORT_CORS_ORIGINS", "").split(",") if value.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[value.strip() for value in os.environ.get("STEUERREPORT_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1],testserver").split(",") if value.strip()],
    )

    @app.middleware("http")
    async def reject_untrusted_browser_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/") and origin not in cors_origins:
            return Response(status_code=403)
        return await call_next(request)
    db = store or DuckDbStore()
    workspace_operation_lock = Lock()
    installation = InstallationSettingsService(db)

    @app.get("/api/v1/admin/installation")
    def read_installation() -> ApiResponse[InstallationSettings]:
        try:
            return ApiResponse(data=installation.read())
        except InstallationSettingsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.put("/api/v1/admin/installation")
    def write_installation(payload: InstallationSettingsWrite) -> ApiResponse[InstallationSettings]:
        try:
            return ApiResponse(data=installation.write(payload))
        except InstallationSettingsError as exc:
            raise HTTPException(status_code=409 if "conflict" in str(exc) else 400, detail=str(exc)) from None

    @app.put("/api/v1/admin/installation/providers/{provider}")
    def write_installation_provider(provider: str, payload: ProviderSecretWrite) -> ApiResponse[dict[str, bool]]:
        try:
            installation.save_provider(provider, payload.api_key)
        except InstallationSettingsError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        return ApiResponse(data={"configured": True})

    @app.delete("/api/v1/admin/installation/providers/{provider}")
    def delete_installation_provider(provider: str) -> ApiResponse[dict[str, bool]]:
        try:
            installation.delete_provider(provider)
        except InstallationSettingsError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        return ApiResponse(data={"configured": False})

    @app.get("/api/v1/admin/installation/configs/{filename}")
    def read_installation_config(filename: str) -> ApiResponse[PrivateConfigDocument]:
        try:
            return ApiResponse(data=installation.read_config(filename))
        except InstallationSettingsError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None

    @app.put("/api/v1/admin/installation/configs/{filename}")
    def write_installation_config(filename: str, payload: PrivateConfigWrite) -> ApiResponse[PrivateConfigDocument]:
        try:
            return ApiResponse(data=installation.write_config(filename, payload))
        except InstallationSettingsError as exc:
            raise HTTPException(status_code=409 if "conflict" in str(exc) else 400, detail=str(exc)) from None
    response_cache: dict[str, tuple[float, object]] = {}
    response_cache_locks: dict[str, RLock] = {}
    response_cache_guard = RLock()

    def cached_response(key: str, ttl_seconds: float, factory):
        now = monotonic()
        with response_cache_guard:
            entry = response_cache.get(key)
            if entry is not None and now - entry[0] <= ttl_seconds:
                return entry[1]
            key_lock = response_cache_locks.setdefault(key, RLock())
        with key_lock:
            now = monotonic()
            with response_cache_guard:
                entry = response_cache.get(key)
                if entry is not None and now - entry[0] <= ttl_seconds:
                    return entry[1]
            value = factory()
            with response_cache_guard:
                response_cache[key] = (monotonic(), value)
            return value

    def clear_response_cache() -> None:
        with response_cache_guard:
            response_cache.clear()

    def authorize_connector_admin(authorization: str | None) -> None:
        try:
            ConnectorAccessPolicy().authorize(authorization)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail=str(exc),
            ) from exc
        except PermissionError as exc:
            raise HTTPException(
                status_code=401,
                detail=str(exc),
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    def authorize_connector_write(
        authorization: str | None,
        *,
        required_scope: MobileConnectorScope,
    ) -> MobileConnectorSession | None:
        try:
            return ConnectorAccessPolicy().authorize_scoped(
                db,
                authorization,
                required_scope,
            )
        except RuntimeError as exc:
            raise HTTPException(
                status_code=503,
                detail=str(exc),
            ) from exc
        except PermissionError as exc:
            status_code = 403 if str(exc) == "mobile_session_scope_missing" else 401
            raise HTTPException(
                status_code=status_code,
                detail=str(exc),
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

    @app.get("/health")
    @app.get("/api/v1/health")
    def health() -> ApiResponse[dict]:
        return ApiResponse(data=build_health_payload(db))

    @app.get("/api/v1/meta/capabilities")
    def api_capabilities() -> ApiResponse[ApiCapabilities]:
        api_routes = [route for route in app.routes if isinstance(route, APIRoute)]
        return ApiResponse(
            data=ApiCapabilitiesService().report(
                operation_count=sum(len(route.methods or {"GET"}) for route in api_routes),
                path_count=len({route.path for route in api_routes}),
            )
        )

    @app.get("/api/v1/admin/database")
    def database_status() -> ApiResponse[dict]:
        return ApiResponse(data=db.health())

    @app.get("/api/v1/admin/status")
    def admin_status() -> ApiResponse[AdminStatus]:
        return ApiResponse(data=AdminService(db).status())

    @app.get("/api/v1/cockpit/summary")
    def cockpit_summary() -> ApiResponse[CockpitSummary]:
        return ApiResponse(
            data=cached_response(
                "cockpit:summary", 10, lambda: CockpitService(db).summary()
            )
        )

    @app.get("/api/v1/product/readiness")
    def product_readiness() -> ApiResponse[ProductReadinessReport]:
        return ApiResponse(
            data=cached_response(
                "product:readiness", 60, lambda: ProductReadinessService(db).report()
            )
        )

    @app.get("/api/v1/connectors/catalog")
    def connector_catalog() -> ApiResponse[ConnectorCatalogReport]:
        return ApiResponse(data=ConnectorService(db).catalog())

    @app.get("/api/v1/connectors/connections")
    def connector_connections() -> ApiResponse[list[ConnectorConnection]]:
        return ApiResponse(data=ConnectorService(db).connections())

    @app.post("/api/v1/connectors/mobile/pairings")
    def create_mobile_connector_pairing(
        payload: MobileConnectorPairingRequest,
        authorization: str | None = Header(default=None),
    ) -> ApiResponse[MobileConnectorPairing]:
        authorize_connector_admin(authorization)
        try:
            return ApiResponse(data=ConnectorService(db).create_mobile_pairing(payload))
        except ValueError as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code=str(exc),
                        message="Die Mobilgeraete-Kopplung konnte nicht erstellt werden.",
                        field="device_name",
                    )
                ],
            )

    @app.post("/api/v1/connectors/mobile/sessions")
    def exchange_mobile_connector_pairing(
        payload: MobileConnectorSessionExchangeRequest,
    ) -> ApiResponse[MobileConnectorSessionToken]:
        try:
            return ApiResponse(data=ConnectorService(db).exchange_mobile_pairing(payload))
        except ValueError as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code=str(exc),
                        message="Die Kopplung ist ungueltig oder nicht mehr aktiv.",
                        field="pairing_code",
                    )
                ],
            )

    @app.get("/api/v1/connectors/mobile/sessions")
    def mobile_connector_sessions(
        authorization: str | None = Header(default=None),
    ) -> ApiResponse[list[MobileConnectorSession]]:
        authorize_connector_admin(authorization)
        return ApiResponse(data=ConnectorService(db).mobile_sessions())

    @app.get("/api/v1/connectors/mobile/session")
    def current_mobile_connector_session(
        authorization: str | None = Header(default=None),
    ) -> ApiResponse[MobileConnectorSession]:
        try:
            access_token = ConnectorAccessPolicy._bearer_token(authorization)
            session = ConnectorService(db).authorize_mobile_session(
                access_token,
                required_scope="connector:read",
            )
        except PermissionError as exc:
            status_code = 403 if str(exc) == "mobile_session_scope_missing" else 401
            raise HTTPException(
                status_code=status_code,
                detail=str(exc),
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        return ApiResponse(data=session)

    @app.post("/api/v1/connectors/mobile/documents")
    async def upload_mobile_connector_document(
        response: Response,
        file: UploadFile = File(...),
        document_kind: MobileDocumentKind = Form("other"),
        source_hint: str | None = Form(default=None),
        note: str | None = Form(default=None),
        captured_at: datetime | None = Form(default=None),
        authorization: str | None = Header(default=None),
    ) -> ApiResponse[MobileDocumentUploadResult]:
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        session = authorize_connector_write(
            authorization,
            required_scope="document:upload",
        )
        content = await file.read(MobileDocumentInboxService.MAX_FILE_BYTES + 1)
        try:
            result = MobileDocumentInboxService(db).store_document(
                filename=file.filename or "",
                content=content,
                declared_media_type=file.content_type,
                document_kind=document_kind,
                source_hint=source_hint,
                note=note,
                captured_at=captured_at,
                uploaded_by_session_id=session.session_id if session else None,
            )
        except ValueError as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="mobile_document_rejected",
                        message=str(exc),
                        field="file",
                    )
                ],
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ApiResponse(
            status="warning" if result.already_present else "ok",
            data=result,
            warnings=(
                [
                    ApiMessage(
                        code="mobile_document_already_present",
                        message=(
                            "Der Beleg war bereits hashgleich in der privaten Inbox vorhanden."
                        ),
                        field="file",
                    )
                ]
                if result.already_present
                else []
            ),
        )

    @app.get("/api/v1/connectors/mobile/documents")
    def mobile_connector_documents(
        response: Response,
        limit: int = Query(default=100, ge=1, le=500),
        authorization: str | None = Header(default=None),
    ) -> ApiResponse[MobileDocumentInboxReport]:
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        authorize_connector_admin(authorization)
        return ApiResponse(data=MobileDocumentInboxService(db).report(limit=limit))

    @app.get("/api/v1/connectors/mobile/documents/{document_id}/content")
    def mobile_connector_document_content(
        document_id: str,
        authorization: str | None = Header(default=None),
    ) -> Response:
        authorize_connector_admin(authorization)
        try:
            document, content = MobileDocumentInboxService(db).content(document_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        encoded_filename = quote(document.original_filename, safe="")
        suffix = Path(document.original_filename).suffix.lower()
        return Response(
            content=content,
            media_type=document.media_type,
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": (
                    f"attachment; filename=mobile-document-{document.document_id}{suffix}; "
                    f"filename*=UTF-8''{encoded_filename}"
                ),
                "X-Content-SHA256": document.document_sha256,
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.delete("/api/v1/connectors/mobile/sessions/{session_id}")
    def revoke_mobile_connector_session(
        session_id: str,
        authorization: str | None = Header(default=None),
    ) -> ApiResponse[MobileConnectorSession]:
        authorize_connector_admin(authorization)
        try:
            return ApiResponse(
                data=ConnectorService(db).revoke_mobile_session(session_id)
            )
        except ValueError as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code=str(exc),
                        message="Die Mobilgeraete-Sitzung wurde nicht gefunden.",
                        field="session_id",
                    )
                ],
            )

    @app.post("/api/v1/connectors/wallet/challenges")
    def create_wallet_ownership_challenge(
        payload: WalletOwnershipChallengeRequest,
        authorization: str | None = Header(default=None),
    ) -> ApiResponse[WalletOwnershipChallenge]:
        authorize_connector_write(authorization, required_scope="wallet:verify")
        try:
            challenge = ConnectorService(db).create_wallet_challenge(payload)
        except (ValueError, RuntimeError) as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code=str(exc),
                        message="Die Solana-Wallet-Adresse ist ungueltig.",
                        field="wallet_address",
                    )
                ],
            )
        return ApiResponse(data=challenge)

    @app.post("/api/v1/connectors/wallet/verifications")
    def verify_wallet_ownership_challenge(
        payload: WalletOwnershipVerificationRequest,
        authorization: str | None = Header(default=None),
    ) -> ApiResponse[WalletOwnershipVerificationResult]:
        authorize_connector_write(authorization, required_scope="wallet:verify")
        try:
            result = ConnectorService(db).verify_wallet_challenge(
                payload.challenge_id,
                payload.signature,
            )
        except ValueError as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code=str(exc),
                        message="Der Wallet-Eigentumsnachweis konnte nicht bestaetigt werden.",
                        field="signature",
                    )
                ],
            )
        return ApiResponse(data=result)

    @app.get("/api/v1/admin/settings")
    def list_admin_settings() -> ApiResponse[list[AdminSetting]]:
        return ApiResponse(data=AdminService(db).list_settings())

    @app.patch("/api/v1/admin/settings")
    def update_admin_setting(payload: AdminSettingWrite) -> ApiResponse[AdminSetting]:
        try:
            return ApiResponse(data=AdminService(db).upsert_setting(payload))
        except (ValueError, RuntimeError) as exc:
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
    def save_cex_credentials(
        payload: CexCredentialWrite,
    ) -> ApiResponse[CexCredentialWriteResult]:
        try:
            result = AdminService(db).save_cex_credentials(payload)
        except (ValueError, RuntimeError) as exc:
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
        except (ValueError, RuntimeError) as exc:
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
    def jupiter_token_metadata_cache(
        limit: int = 200,
    ) -> ApiResponse[JupiterTokenMetadataCacheResult]:
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
            result = JupiterTokenService(db).refresh_metadata_cache(
                limit=limit, force=force
            )
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
            result = JupiterTokenService(db).risk_review(
                risk_status=risk_status, limit=limit
            )
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
    def v1_cex_credentials_takeover_report() -> ApiResponse[
        V1CexCredentialTakeoverReport
    ]:
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
        root_path: str = str(configured_import_path("import_root")),
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
        root_path: str = str(configured_import_path("import_root")),
    ) -> ApiResponse[ImportPolicyAudit]:
        return ApiResponse(data=ImportPolicyService(db).audit(root_path))

    @app.get("/api/v1/import/parser-preflight")
    def parser_preflight(
        root_path: str = str(configured_import_path("import_root")),
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
        file_path: str = str(configured_import_path("blockpit_reference_file", "blockpit/transactions.csv")),
        integration: str = "Solana",
        max_year: int = 2024,
        account: str = "Solana",
        price_config_path: str = str(PROJECT_ROOT / "configs/crypto_price_sources.json"),
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
        file_path: str = str(configured_import_path("solscan_export_file", "solscan/export.csv")),
        blockpit_file_path: str = str(configured_import_path("blockpit_reference_file", "blockpit/transactions.csv")),
        wallet: str = private_value('primary_solana_wallet', ''),
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
        from steuerreport_v2.domain.secrets import resolve_secret_value

        endpoint = urlsplit(payload.rpc_url)
        # Never send a saved provider secret to an arbitrary caller-supplied host.
        if endpoint.scheme == "https" and endpoint.hostname in {"mainnet.helius-rpc.com", "devnet.helius-rpc.com"} and not endpoint.query and not endpoint.username and not endpoint.password and endpoint.port in {None, 443}:
            key = resolve_secret_value(db, "secret.helius.api_key")
            if key:
                payload = payload.model_copy(update={"rpc_url": payload.rpc_url.rstrip("/") + "/?" + urlencode({"api-key": key})})
        return ApiResponse(
            data=SolscanPreflightService().probe_missing_signatures_rpc(payload)
        )

    @app.get("/api/v1/import/solscan/evidence-trace")
    def solscan_evidence_trace(
        file_path: str = str(configured_import_path("solscan_export_file", "solscan/export.csv")),
        blockpit_file_path: str = str(configured_import_path("blockpit_reference_file", "blockpit/transactions.csv")),
        wallet: str = private_value('primary_solana_wallet', ''),
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
        return ApiResponse(
            data=SolscanPreflightService().helium_reward_evidence(
                artifact_path=artifact_path
            )
        )

    @app.get("/api/v1/import/wallet-monthly/preflight")
    def wallet_monthly_preflight(
        file_path: str = str(configured_import_path("wallet_monthly_file", "wallet-month.csv")),
        wallet: str = private_value('primary_solana_wallet', ''),
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
        file_path: str = str(configured_import_path("jup_perps_file", "jup/perps.csv")),
        v1_fx_db_path: str = str(configured_import_path("v1_fx_db_file", "reference/legacy-prices.db")),
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

    @app.get("/api/v1/workspace/sources")
    def workspace_sources() -> ApiResponse[WorkspaceSources]:
        return ApiResponse(data=WorkspaceService(db).sources())

    @app.get("/api/v1/workspace/sources/{ref}")
    def workspace_source(ref: str) -> ApiResponse[WorkspaceSourceDetail]:
        try:
            return ApiResponse(data=WorkspaceService(db).source(ref))
        except LookupError:
            raise HTTPException(status_code=404, detail="workspace_source_not_found") from None

    @app.get("/api/v1/workspace/status")
    def workspace_status(year: int = Query(default=2025, ge=2000, le=2100)) -> ApiResponse[WorkspaceStatus]:
        return ApiResponse(data=WorkspaceService(db).status(year))

    @app.post("/api/v1/workspace/review/query")
    def workspace_review(payload: WorkspaceReviewQuery) -> ApiResponse[WorkspaceReviewPage]:
        return ApiResponse(data=WorkspaceService(db).review_page(payload))

    @app.post("/api/v1/activity/query")
    def activity_query(payload: ActivityQuery) -> ApiResponse[ActivityPage]:
        """Lesende, serverseitig paginierte Abfrage. Suchtext bleibt im Body, nicht in URLs."""
        try:
            return ApiResponse(data=ActivityService(db).query(payload))
        except LookupError:
            raise HTTPException(status_code=404, detail="workspace_source_not_found") from None

    @app.get("/api/v1/activity/assets")
    def activity_assets() -> ApiResponse[dict[str, object]]:
        with db.connect() as con:
            rows = con.execute("select distinct asset from (select asset from canonical_events union select quote_asset from canonical_events union select fee_asset from canonical_events) where asset is not null order by asset limit 5001").fetchall()
        return ApiResponse(data={"assets": [row[0] for row in rows[:5000]], "truncated": len(rows) > 5000})

    @app.get("/api/v1/activity/events/{event_id}")
    def activity_detail(event_id: str) -> ApiResponse[ActivityDetail]:
        try:
            return ApiResponse(data=ActivityService(db).detail(event_id))
        except LookupError:
            raise HTTPException(status_code=404, detail="activity_event_not_found") from None

    @app.post("/api/v1/activity/export.csv")
    def activity_export(payload: ActivityExport) -> Response:
        """Lesender CSV-Export ohne Artefakt-/Job-Persistenz; Umfang ist ausdruecklich erforderlich."""
        try:
            rows = ActivityService(db).export(payload)
        except LookupError:
            raise HTTPException(status_code=404, detail="workspace_source_not_found") from None
        except ValueError:
            raise HTTPException(status_code=400, detail="activity_export_selection_empty") from None
        except OverflowError:
            raise HTTPException(status_code=413, detail="activity_export_too_large") from None
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["row_id", "event_id", "event_time_utc", "source", "type", "asset", "quantity", "quote_asset", "quote_quantity", "fee_asset", "fee_quantity", "ledger_asset", "ledger_quantity", "has_hint", "corrected"])
        def cell(value):
            text = "" if value is None else str(value)
            return "'" + text if isinstance(value, str) and text.startswith(("=", "+", "-", "@")) else text
        for row in rows:
            event = row.event
            writer.writerow([cell(value) for value in [row.row_id, event.event_id, event.event_time.isoformat(), event.source, event.event_type, event.asset,
                event.quantity, event.quote_asset, event.quote_quantity, event.fee_asset, event.fee_quantity, row.ledger_asset, row.ledger_quantity, row.has_hint, row.corrected]])
        return Response(content="\ufeff" + output.getvalue(), media_type="text/csv; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="activity-{payload.scope}.csv"',
            "X-Export-Row-Count": str(len(rows)), "X-Export-Scope": payload.scope, "Cache-Control": "no-store"})

    @app.post("/api/v1/workspace/sources/{ref}/sync")
    def workspace_source_sync(ref: str) -> ApiResponse[PortfolioReconciliationRefreshResult]:
        try:
            source = WorkspaceService(db).scope(ref).item
        except LookupError:
            raise HTTPException(status_code=404, detail="workspace_source_not_found") from None
        if not source.can_sync:
            raise HTTPException(status_code=409, detail="source_sync_not_configured")
        if not workspace_operation_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="workspace_operation_running")
        try:
            result = PortfolioService(db).refresh_reconciliation_snapshots(connectors=[source.connector_id])
            clear_response_cache()
            return ApiResponse(data=result)
        finally:
            workspace_operation_lock.release()

    @app.get("/api/v1/import/batches/{batch_id}/trace.json")
    def download_import_batch_trace(batch_id: str) -> Response:
        batch = db.get_import_batch(batch_id)
        payload = {
            "batch": batch.model_dump(mode="json") if batch is not None else None,
            "raw_objects": [
                item.model_dump(mode="json")
                for item in db.list_raw_objects(batch_id=batch_id, limit=None)
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
    def preview_import_assistant(
        payload: ImportAssistantRequest,
    ) -> ApiResponse[ImportAssistantPreview]:
        try:
            preview = ImportAssistantService(db).preview(payload)
        except ValueError:
            return ApiResponse(status="error", errors=[ApiMessage(
                code="import_assistant_invalid_file",
                message="Datei nicht lesbar. CSV-Zeichensatz, Excel-Format und Tabellenblatt pruefen.",
                field="content",
            )])
        return ApiResponse(
            status="ok" if preview.can_execute else "warning",
            data=preview,
            warnings=[
                {
                    "code": "import_assistant_warning",
                    "message": warning,
                    "field": "content",
                }
                for warning in preview.warnings
            ],
        )

    @app.post("/api/v1/import/assistant/execute")
    def execute_import_assistant(
        payload: ImportAssistantRequest,
    ) -> ApiResponse[ImportAssistantExecuteResult]:
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
        return ApiResponse(
            data=TransferCandidateService(db).candidates(asset=asset, limit=limit)
        )

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
    def preview_price_csv(
        payload: PriceCsvImportRequest,
    ) -> ApiResponse[PriceCsvPreview]:
        preview = PriceCsvImporter().preview(payload.content, payload.default_source)
        return ApiResponse(
            status="ok" if preview.can_import else "warning", data=preview
        )

    @app.post("/api/v1/prices/import/csv")
    def import_price_csv(
        payload: PriceCsvImportRequest,
    ) -> ApiResponse[PriceCsvImportResult]:
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
        if result.imported_prices:
            clear_response_cache()
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
        if result.imported_prices:
            clear_response_cache()
        return ApiResponse(
            status="ok" if result.dry_run or result.imported_prices else "warning",
            data=result,
        )

    @app.get("/api/v1/prices/as-of-gate")
    def prices_as_of_gate(
        as_of: datetime | None = None,
        as_of_date: date | None = None,
        materiality_threshold_eur: Decimal = Decimal("1"),
    ) -> ApiResponse[AsOfPriceGateReport]:
        try:
            report = AsOfPriceGateService(db).report(
                as_of=as_of,
                as_of_date=as_of_date,
                materiality_threshold_eur=materiality_threshold_eur,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return ApiResponse(data=report)

    @app.post("/api/v1/prices/as-of-gate/backfill")
    def prices_as_of_gate_backfill(
        payload: AsOfPriceGateBackfillRequest,
    ) -> ApiResponse[AsOfPriceGateBackfillResult]:
        try:
            result = AsOfPriceGateService(db).backfill(payload)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return ApiResponse(
            status="ok" if result.dry_run or result.imported_prices else "warning",
            data=result,
        )

    @app.post("/api/v1/prices/as-of-gate/token-review-decisions")
    def accept_as_of_token_valuation(
        payload: AsOfTokenValuationDecisionRequest,
    ) -> ApiResponse[AsOfTokenValuationDecisionResult]:
        try:
            result = AsOfPriceGateService(db).accept_token_valuation(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        clear_response_cache()
        return ApiResponse(data=result)

    @app.get("/api/v1/prices/as-of-gate/token-review-decisions.csv")
    def as_of_token_valuation_decisions_csv(
        separation_date: date | None = None,
        end_asset_date: date | None = None,
    ) -> Response:
        content = AsOfPriceGateService(db).token_valuation_decisions_csv(
            separation_date=separation_date,
            end_asset_date=end_asset_date,
        )
        return Response(
            content=content,
            media_type="text/csv",
            headers={
                "Content-Disposition": (
                    "attachment; filename=stichtag-token-valuation-decisions.csv"
                )
            },
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
    def price_quality_manual_review(
        limit: int = 120,
    ) -> ApiResponse[PriceQualityManualReviewReport]:
        return ApiResponse(
            data=PriceQualityService(db).manual_review_report(limit=limit)
        )

    @app.get("/api/v1/prices/quality/stablecoin-fx-review")
    def price_quality_stablecoin_fx_review(
        limit: int = 120,
    ) -> ApiResponse[PriceQualityStablecoinFxReport]:
        return ApiResponse(
            data=PriceQualityService(db).stablecoin_fx_review(limit=limit)
        )

    @app.get("/api/v1/prices/quality/stablecoin-fx-replacement-preview")
    def price_quality_stablecoin_fx_replacement_preview(
        limit: int = 120,
        days_per_group: int = 20,
    ) -> ApiResponse[PriceQualityStablecoinFxReplacementReport]:
        return ApiResponse(
            data=PriceQualityService(db).stablecoin_fx_replacement_preview(
                limit=limit,
                days_per_group=days_per_group,
            )
        )

    @app.get("/api/v1/prices/quality/stablecoin-fx-replacement-impact")
    def price_quality_stablecoin_fx_replacement_impact(
        asset: str,
        year: int,
        source: str = "derived:event_quote",
        limit: int = 200,
    ) -> ApiResponse[PriceQualityStablecoinFxReplacementImpactReport]:
        return ApiResponse(
            data=PriceQualityService(db).stablecoin_fx_replacement_impact(
                asset=asset,
                year=year,
                source=source,
                limit=limit,
            )
        )

    @app.get("/api/v1/prices/quality/stablecoin-fx-tax-impact-latest")
    def price_quality_stablecoin_fx_tax_impact_latest(
        asset: str = "USDT",
        year: int = 2024,
        source: str = "derived:event_quote",
    ) -> ApiResponse[PriceQualityStablecoinFxTaxImpactLatestReport]:
        return ApiResponse(
            data=PriceQualityService(db).stablecoin_fx_tax_impact_latest(
                asset=asset,
                year=year,
                source=source,
            )
        )

    @app.post("/api/v1/prices/quality/stablecoin-fx-tax-impact-decisions")
    def add_price_quality_stablecoin_fx_tax_impact_decision(
        payload: PriceQualityStablecoinFxTaxImpactDecisionCreate,
    ) -> ApiResponse[PriceQualityStablecoinFxTaxImpactDecisionResult]:
        try:
            result = PriceQualityService(db).add_stablecoin_fx_tax_impact_decision(
                payload
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ApiResponse(data=result)

    @app.get("/api/v1/prices/quality/stablecoin-fx-anchor-preview-latest")
    def price_quality_stablecoin_fx_anchor_preview_latest(
        include_rows: bool = False,
    ) -> ApiResponse[PriceQualityStablecoinFxAnchorPreviewLatest]:
        return ApiResponse(
            data=PriceQualityService(db).stablecoin_fx_anchor_preview_latest(
                include_rows=include_rows,
            )
        )

    @app.post("/api/v1/prices/quality/stablecoin-fx-anchor-preview-decisions")
    def add_price_quality_stablecoin_fx_anchor_preview_decision(
        payload: PriceQualityStablecoinFxAnchorPreviewDecisionCreate,
    ) -> ApiResponse[PriceQualityStablecoinFxTaxImpactDecisionResult]:
        try:
            result = PriceQualityService(db).add_stablecoin_fx_anchor_preview_decision(
                payload
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ApiResponse(data=result)

    @app.post("/api/v1/prices/quality/stablecoin-fx-anchor-apply")
    def apply_price_quality_stablecoin_fx_anchor_prices(
        payload: PriceQualityStablecoinFxAnchorApplyRequest,
    ) -> ApiResponse[PriceQualityStablecoinFxAnchorApplyResult]:
        try:
            result = PriceQualityService(db).apply_stablecoin_fx_anchor_prices(payload)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ApiResponse(data=result)

    @app.get("/api/v1/prices/quality/solscan-signature-review")
    def price_quality_solscan_signature_review(
        limit: int = 120,
    ) -> ApiResponse[PriceQualitySolscanSignatureReport]:
        return ApiResponse(
            data=PriceQualityService(db).solscan_signature_review(limit=limit)
        )

    @app.get("/api/v1/prices/quality/binance-normalizer-review")
    def price_quality_binance_normalizer_review(
        limit: int = 120,
    ) -> ApiResponse[PriceQualityBinanceNormalizerReport]:
        return ApiResponse(
            data=PriceQualityService(db).binance_normalizer_review(limit=limit)
        )

    @app.get("/api/v1/prices/quality/event-quote-evidence-review")
    def price_quality_event_quote_evidence_review(
        limit: int = 120,
    ) -> ApiResponse[PriceQualityEventQuoteEvidenceReport]:
        return ApiResponse(
            data=PriceQualityService(db).event_quote_evidence_review(limit=limit)
        )

    @app.get("/api/v1/prices/quality/closure-candidates")
    def price_quality_closure_candidates(
        limit: int = 120,
    ) -> ApiResponse[PriceQualityClosureCandidateReport]:
        return ApiResponse(data=PriceQualityService(db).closure_candidates(limit=limit))

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
    def add_price_gap_decision(
        payload: PriceGapDecisionCreate,
    ) -> ApiResponse[PriceGapDecisionResult]:
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
        return ApiResponse(
            data=cached_response(
                "portfolio:snapshot", 10, lambda: PortfolioService(db).snapshot()
            )
        )

    @app.get("/api/v1/portfolio/valuation-audit")
    def portfolio_valuation_audit() -> ApiResponse[PortfolioValuationAuditReport]:
        return ApiResponse(data=PortfolioService(db).valuation_audit())

    @app.get("/api/v1/portfolio/as-of")
    def portfolio_as_of(as_of: str | None = None) -> ApiResponse[PortfolioAsOfSnapshot]:
        return ApiResponse(data=PortfolioService(db).as_of_snapshot(as_of))

    @app.get("/api/v1/portfolio/value-history")
    def portfolio_value_history(
        from_date: str | None = None,
        to_date: str | None = None,
        interval: str = "month",
        max_points: int = 72,
    ) -> ApiResponse[PortfolioValueHistoryReport]:
        cache_key = f"portfolio:value-history:{from_date or ''}:{to_date or ''}:{interval}:{max_points}"
        return ApiResponse(
            data=cached_response(
                cache_key,
                60,
                lambda: PortfolioService(db).value_history(
                    from_date=from_date,
                    to_date=to_date,
                    interval=interval,
                    max_points=max_points,
                ),
            )
        )

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
    def portfolio_reconciliation_refresh() -> ApiResponse[
        PortfolioReconciliationRefreshResult
    ]:
        if not workspace_operation_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="workspace_operation_running")
        try:
            result = PortfolioService(db).refresh_reconciliation_snapshots()
        finally:
            workspace_operation_lock.release()
        clear_response_cache()
        warnings = [
            ApiMessage(
                code=f"connector_{item.status}",
                message=f"{item.connector_id}: {item.message}",
                field=item.connector_id,
            )
            for item in result.connector_results
            if item.status not in {"refreshed", "empty_response"}
        ]
        if result.imported_snapshots == 0 and not any(
            item.status == "empty_response" for item in result.connector_results
        ):
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
        return ApiResponse(
            data=PortfolioService(db).fiat_deposit_report(source="binance")
        )

    @app.get("/api/v1/divorce/inheritance-origin")
    def divorce_inheritance_origin(
        separation_date: date = DivorceInheritanceOriginService.DEFAULT_SEPARATION_DATE,
        end_asset_date: date = DivorceInheritanceOriginService.DEFAULT_END_ASSET_DATE,
    ) -> ApiResponse[DivorceInheritanceOriginReport]:
        return ApiResponse(
            data=DivorceInheritanceOriginService(db).report(
                separation_date=separation_date,
                end_asset_date=end_asset_date,
            )
        )

    @app.get("/api/v1/divorce/sparkasse-statements")
    def divorce_sparkasse_statements() -> ApiResponse[
        SparkasseStatementConnectorStatus
    ]:
        return ApiResponse(
            data=DivorceInheritanceOriginService(db).sparkasse_statements()
        )

    @app.get("/api/v1/divorce/sparkasse-statements.csv")
    def divorce_sparkasse_statements_csv() -> Response:
        content = DivorceInheritanceOriginService(db).sparkasse_statements_csv()
        return Response(
            content=content,
            media_type="text/csv",
            headers={
                "Content-Disposition": (
                    "attachment; filename=sparkasse-statement-camt-evidence.csv"
                )
            },
        )

    @app.get("/api/v1/divorce/inheritance-credit-candidates")
    def divorce_inheritance_credit_candidates(
        separation_date: date = DivorceInheritanceOriginService.DEFAULT_SEPARATION_DATE,
        end_asset_date: date = DivorceInheritanceOriginService.DEFAULT_END_ASSET_DATE,
    ) -> ApiResponse[InheritanceBankCreditCandidateReport]:
        return ApiResponse(
            data=DivorceInheritanceOriginService(db).inheritance_bank_credit_candidates(
                separation_date=separation_date,
                end_asset_date=end_asset_date,
            )
        )

    @app.get("/api/v1/divorce/inheritance-credits.csv")
    def divorce_inheritance_credits_csv(
        separation_date: date = DivorceInheritanceOriginService.DEFAULT_SEPARATION_DATE,
        end_asset_date: date = DivorceInheritanceOriginService.DEFAULT_END_ASSET_DATE,
    ) -> Response:
        content = DivorceInheritanceOriginService(db).inheritance_credits_csv(
            separation_date=separation_date,
            end_asset_date=end_asset_date,
        )
        return Response(
            content=content,
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=inheritance-credit-evidence.csv"
            },
        )

    @app.post("/api/v1/divorce/inheritance-credit-decisions")
    def divorce_inheritance_credit_decision(
        payload: InheritanceBankCreditDecisionRequest,
        separation_date: date = DivorceInheritanceOriginService.DEFAULT_SEPARATION_DATE,
        end_asset_date: date = DivorceInheritanceOriginService.DEFAULT_END_ASSET_DATE,
    ) -> ApiResponse[InheritanceBankCreditDecisionResult]:
        try:
            result = DivorceInheritanceOriginService(db).accept_inheritance_bank_credit(
                payload,
                separation_date=separation_date,
                end_asset_date=end_asset_date,
            )
        except ValueError as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="inheritance_credit_not_reviewable",
                        message=str(exc),
                        field="transaction_reference_sha256",
                    )
                ],
            )
        clear_response_cache()
        return ApiResponse(
            status="warning" if result.already_recorded else "ok",
            data=result,
            warnings=(
                [
                    ApiMessage(
                        code="inheritance_credit_already_reviewed",
                        message="Diese Erbmittelgutschrift ist bereits freigegeben.",
                        field="transaction_reference_sha256",
                    )
                ]
                if result.already_recorded
                else []
            ),
        )

    @app.post("/api/v1/divorce/inheritance-document-credit-decisions")
    def divorce_inheritance_document_credit_decision(
        payload: InheritanceDocumentCreditDecisionRequest,
        separation_date: date = DivorceInheritanceOriginService.DEFAULT_SEPARATION_DATE,
        end_asset_date: date = DivorceInheritanceOriginService.DEFAULT_END_ASSET_DATE,
    ) -> ApiResponse[InheritanceDocumentCreditDecisionResult]:
        try:
            result = DivorceInheritanceOriginService(
                db
            ).accept_inheritance_document_credit(
                payload,
                separation_date=separation_date,
                end_asset_date=end_asset_date,
            )
        except ValueError as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="inheritance_document_credit_not_reviewable",
                        message=str(exc),
                        field="document_sha256",
                    )
                ],
            )
        clear_response_cache()
        return ApiResponse(
            status="warning" if result.already_recorded else "ok",
            data=result,
            warnings=(
                [
                    ApiMessage(
                        code="inheritance_document_credit_already_reviewed",
                        message="Dieser dokumentierte Erbmittelzufluss ist bereits freigegeben.",
                        field="document_sha256",
                    )
                ]
                if result.already_recorded
                else []
            ),
        )

    @app.post("/api/v1/divorce/sparkasse-camt")
    async def divorce_sparkasse_camt_upload(
        file: UploadFile = File(...),
        separation_date: date = Form(
            DivorceInheritanceOriginService.DEFAULT_SEPARATION_DATE
        ),
        end_asset_date: date = Form(
            DivorceInheritanceOriginService.DEFAULT_END_ASSET_DATE
        ),
    ) -> ApiResponse[BankCamtUploadResult]:
        content = await file.read(
            DivorceInheritanceOriginService.MAX_BANK_CAMT_UPLOAD_BYTES + 1
        )
        try:
            result = DivorceInheritanceOriginService(db).store_bank_camt_document(
                filename=file.filename or "",
                content=content,
                separation_date=separation_date,
                end_asset_date=end_asset_date,
            )
        except ValueError as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="sparkasse_camt_rejected",
                        message=str(exc),
                        field="file",
                    )
                ],
            )
        clear_response_cache()
        return ApiResponse(
            status="warning" if result.uploaded_files == 0 else "ok",
            data=result,
            warnings=(
                [
                    ApiMessage(
                        code="sparkasse_camt_already_present",
                        message="Alle enthaltenen CAMT-Dateien waren bereits hashgleich vorhanden.",
                        field="file",
                    )
                ]
                if result.uploaded_files == 0
                else []
            ),
        )

    @app.get("/api/v1/divorce/inheritance-documents")
    def divorce_inheritance_documents() -> ApiResponse[
        InheritanceDocumentConnectorStatus
    ]:
        return ApiResponse(
            data=DivorceInheritanceOriginService(db).inheritance_documents()
        )

    @app.get("/api/v1/divorce/inheritance-documents.csv")
    def divorce_inheritance_documents_csv() -> Response:
        content = DivorceInheritanceOriginService(db).inheritance_documents_csv()
        return Response(
            content=content,
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=inheritance-document-evidence.csv"
            },
        )

    @app.post("/api/v1/divorce/inheritance-documents")
    async def divorce_inheritance_document_upload(
        file: UploadFile = File(...),
    ) -> ApiResponse[InheritanceDocumentUploadResult]:
        content = await file.read(
            DivorceInheritanceOriginService.MAX_INHERITANCE_DOCUMENT_BYTES + 1
        )
        try:
            result = DivorceInheritanceOriginService(db).store_inheritance_document(
                filename=file.filename or "",
                content=content,
            )
        except ValueError as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="inheritance_document_rejected",
                        message=str(exc),
                        field="file",
                    )
                ],
            )
        clear_response_cache()
        return ApiResponse(
            status="warning" if result.already_present else "ok",
            data=result,
            warnings=(
                [
                    ApiMessage(
                        code="inheritance_document_already_present",
                        message="Dieser Erbnachweis war bereits hashgleich vorhanden.",
                        field="file",
                    )
                ]
                if result.already_present
                else []
            ),
        )

    @app.post("/api/v1/divorce/inheritance-documents/review-decisions")
    def divorce_inheritance_document_review_decision(
        payload: InheritanceDocumentDecisionRequest,
    ) -> ApiResponse[InheritanceDocumentDecisionResult]:
        try:
            result = DivorceInheritanceOriginService(db).accept_inheritance_document(
                payload
            )
        except ValueError as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="inheritance_document_not_reviewable",
                        message=str(exc),
                        field="document_sha256",
                    )
                ],
            )
        clear_response_cache()
        return ApiResponse(
            status="warning" if result.already_recorded else "ok",
            data=result,
            warnings=(
                [
                    ApiMessage(
                        code="inheritance_document_already_reviewed",
                        message="Dieser formale Erbnachweis ist bereits freigegeben.",
                        field="document_sha256",
                    )
                ]
                if result.already_recorded
                else []
            ),
        )

    @app.get("/api/v1/divorce/inheritance-origin.csv")
    def divorce_inheritance_origin_csv(
        separation_date: date = DivorceInheritanceOriginService.DEFAULT_SEPARATION_DATE,
        end_asset_date: date = DivorceInheritanceOriginService.DEFAULT_END_ASSET_DATE,
    ) -> Response:
        content = DivorceInheritanceOriginService(db).csv(
            separation_date=separation_date,
            end_asset_date=end_asset_date,
        )
        return Response(
            content=content,
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=divorce-inheritance-origin.csv"
            },
        )

    @app.get("/api/v1/divorce/trade-republic/documents")
    def divorce_trade_republic_documents(
        end_asset_date: date = DivorceInheritanceOriginService.DEFAULT_END_ASSET_DATE,
    ) -> ApiResponse[TradeRepublicConnectorStatus]:
        return ApiResponse(
            data=DivorceInheritanceOriginService(db).trade_republic_documents(
                end_asset_date=end_asset_date
            )
        )

    @app.get("/api/v1/divorce/coinbase/connector")
    def divorce_coinbase_connector(
        end_asset_date: date = DivorceInheritanceOriginService.DEFAULT_END_ASSET_DATE,
    ) -> ApiResponse[CoinbaseConnectorStatus]:
        return ApiResponse(
            data=DivorceInheritanceOriginService(db).coinbase_connector(
                end_asset_date=end_asset_date
            )
        )

    @app.get("/api/v1/divorce/coinbase/connector.csv")
    def divorce_coinbase_connector_csv(
        end_asset_date: date = DivorceInheritanceOriginService.DEFAULT_END_ASSET_DATE,
    ) -> Response:
        content = DivorceInheritanceOriginService(db).coinbase_connector_csv(
            end_asset_date=end_asset_date
        )
        return Response(
            content=content,
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=coinbase-history-valuation-evidence.csv"
            },
        )

    @app.post("/api/v1/divorce/coinbase/valuation-decisions")
    def divorce_coinbase_valuation_decision(
        payload: CoinbaseValuationDecisionRequest,
    ) -> ApiResponse[CoinbaseValuationDecisionResult]:
        try:
            result = DivorceInheritanceOriginService(db).accept_coinbase_valuation(
                payload
            )
        except ValueError as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="coinbase_valuation_not_reviewable",
                        message=str(exc),
                        field="history_manifest_sha256",
                    )
                ],
            )
        clear_response_cache()
        return ApiResponse(
            status="warning" if result.already_recorded else "ok",
            data=result,
            warnings=(
                [
                    ApiMessage(
                        code="coinbase_valuation_already_reviewed",
                        message="Diese Coinbase-Historie ist bereits fuer den Stichtag freigegeben.",
                        field="history_manifest_sha256",
                    )
                ]
                if result.already_recorded
                else []
            ),
        )

    @app.get("/api/v1/divorce/trade-republic/documents.csv")
    def divorce_trade_republic_documents_csv(
        end_asset_date: date = DivorceInheritanceOriginService.DEFAULT_END_ASSET_DATE,
    ) -> Response:
        content = DivorceInheritanceOriginService(db).trade_republic_documents_csv(
            end_asset_date=end_asset_date
        )
        return Response(
            content=content,
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=trade-republic-document-evidence.csv"
            },
        )

    @app.post("/api/v1/divorce/trade-republic/documents")
    async def divorce_trade_republic_document_upload(
        file: UploadFile = File(...),
        end_asset_date: date = Form(
            DivorceInheritanceOriginService.DEFAULT_END_ASSET_DATE
        ),
    ) -> ApiResponse[TradeRepublicDocumentUploadResult]:
        content = await file.read(
            DivorceInheritanceOriginService.MAX_TRADE_REPUBLIC_DOCUMENT_BYTES + 1
        )
        try:
            result = DivorceInheritanceOriginService(db).store_trade_republic_document(
                filename=file.filename or "",
                content=content,
                end_asset_date=end_asset_date,
            )
        except ValueError as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="trade_republic_document_rejected",
                        message=str(exc),
                        field="file",
                    )
                ],
            )
        clear_response_cache()
        return ApiResponse(
            status="warning" if result.already_present else "ok",
            data=result,
            warnings=(
                [
                    ApiMessage(
                        code="trade_republic_document_already_present",
                        message="Dieses Dokument war bereits hashgleich vorhanden.",
                        field="file",
                    )
                ]
                if result.already_present
                else []
            ),
        )

    @app.post("/api/v1/divorce/trade-republic/valuation-decisions")
    def divorce_trade_republic_valuation_decision(
        payload: TradeRepublicValuationDecisionRequest,
    ) -> ApiResponse[TradeRepublicValuationDecisionResult]:
        try:
            result = DivorceInheritanceOriginService(
                db
            ).accept_trade_republic_valuation(payload)
        except ValueError as exc:
            return ApiResponse(
                status="error",
                errors=[
                    ApiMessage(
                        code="trade_republic_valuation_not_reviewable",
                        message=str(exc),
                        field="document_sha256",
                    )
                ],
            )
        clear_response_cache()
        return ApiResponse(
            status="warning" if result.already_recorded else "ok",
            data=result,
            warnings=(
                [
                    ApiMessage(
                        code="trade_republic_valuation_already_recorded",
                        message="Dieser Trade-Republic-Stichtagswert ist bereits freigegeben.",
                        field="document_sha256",
                    )
                ]
                if result.already_recorded
                else []
            ),
        )

    @app.post("/api/v1/divorce/service-route-evidence/refresh")
    def divorce_service_route_evidence_refresh(
        payload: DivorceServiceRouteEvidenceRefreshRequest,
    ) -> ApiResponse[DivorceServiceRouteEvidenceReport]:
        try:
            report = DivorceServiceRouteEvidenceService(db).refresh(payload)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return ApiResponse(
            status="ok" if report.strict_ready else "warning",
            data=report,
        )

    @app.get("/api/v1/divorce/service-route-evidence/{tx_id}")
    def divorce_service_route_evidence(
        tx_id: str,
    ) -> ApiResponse[DivorceServiceRouteEvidenceReport]:
        try:
            report = DivorceServiceRouteEvidenceService(db).latest(tx_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if report is None:
            raise HTTPException(
                status_code=404, detail="service_route_evidence_not_found"
            )
        return ApiResponse(data=report)

    @app.post("/api/v1/divorce/service-route-evidence/decisions")
    def divorce_service_route_decision(
        payload: DivorceServiceRouteDecisionRequest,
    ) -> ApiResponse[DivorceServiceRouteDecisionResult]:
        try:
            result = DivorceServiceRouteEvidenceService(db).accept(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        clear_response_cache()
        return ApiResponse(
            status="warning" if result.already_recorded else "ok",
            data=result,
        )

    @app.get("/api/v1/divorce/service-route-evidence/{tx_id}/artifacts/{filename}")
    def divorce_service_route_evidence_artifact(
        tx_id: str,
        filename: str,
    ) -> Response:
        try:
            path = DivorceServiceRouteEvidenceService(db).evidence_path(
                tx_id,
                filename,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if path is None:
            raise HTTPException(
                status_code=404, detail="service_route_artifact_not_found"
            )
        return Response(
            content=path.read_bytes(),
            media_type="application/gzip",
            headers={"Content-Disposition": f"attachment; filename={path.name}"},
        )

    @app.get("/api/v1/divorce/equalization-summary")
    def divorce_equalization_summary(
        separation_date: date | None = None,
        end_asset_date: date | None = None,
        court_evidence_reference: str | None = None,
        cutoff_at: datetime | None = None,
        valuation_at: datetime | None = None,
        materiality_threshold_eur: Decimal = Decimal("1"),
    ) -> ApiResponse[DivorceEqualizationSummary]:
        try:
            report = DivorceEqualizationService(db).summary(
                separation_date=separation_date,
                end_asset_date=end_asset_date,
                court_evidence_reference=court_evidence_reference,
                cutoff_at=cutoff_at,
                valuation_at=valuation_at,
                materiality_threshold_eur=materiality_threshold_eur,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return ApiResponse(data=report)

    @app.get("/api/v1/divorce/equalization-summary/valuation-tokens.csv")
    def divorce_equalization_valuation_tokens_csv(
        separation_date: date | None = None,
        end_asset_date: date | None = None,
        court_evidence_reference: str | None = None,
        cutoff_at: datetime | None = None,
        valuation_at: datetime | None = None,
        materiality_threshold_eur: Decimal = Decimal("1"),
    ) -> Response:
        try:
            content = DivorceEqualizationService(db).valuation_tokens_csv(
                separation_date=separation_date,
                end_asset_date=end_asset_date,
                court_evidence_reference=court_evidence_reference,
                cutoff_at=cutoff_at,
                valuation_at=valuation_at,
                materiality_threshold_eur=materiality_threshold_eur,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return Response(
            content=content,
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=divorce-equalization-valuation-tokens.csv"
            },
        )

    @app.get("/api/v1/divorce/equalization-summary/accounts.csv")
    def divorce_equalization_accounts_csv(
        separation_date: date | None = None,
        end_asset_date: date | None = None,
        court_evidence_reference: str | None = None,
        cutoff_at: datetime | None = None,
        valuation_at: datetime | None = None,
        materiality_threshold_eur: Decimal = Decimal("1"),
    ) -> Response:
        try:
            content = DivorceEqualizationService(db).accounts_csv(
                separation_date=separation_date,
                end_asset_date=end_asset_date,
                court_evidence_reference=court_evidence_reference,
                cutoff_at=cutoff_at,
                valuation_at=valuation_at,
                materiality_threshold_eur=materiality_threshold_eur,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return Response(
            content=content,
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=divorce-equalization-accounts.csv"
            },
        )

    @app.get("/api/v1/divorce/equalization-summary/live-reconciliation.csv")
    def divorce_equalization_live_reconciliation_csv(
        separation_date: date | None = None,
        end_asset_date: date | None = None,
        court_evidence_reference: str | None = None,
        cutoff_at: datetime | None = None,
        valuation_at: datetime | None = None,
        materiality_threshold_eur: Decimal = Decimal("1"),
    ) -> Response:
        try:
            content = DivorceEqualizationService(db).live_reconciliation_csv(
                separation_date=separation_date,
                end_asset_date=end_asset_date,
                court_evidence_reference=court_evidence_reference,
                cutoff_at=cutoff_at,
                valuation_at=valuation_at,
                materiality_threshold_eur=materiality_threshold_eur,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return Response(
            content=content,
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=divorce-equalization-live-reconciliation.csv"
            },
        )

    @app.get("/api/v1/divorce/equalization-summary/capital-flows.csv")
    def divorce_equalization_capital_flows_csv(
        separation_date: date | None = None,
        end_asset_date: date | None = None,
        court_evidence_reference: str | None = None,
        cutoff_at: datetime | None = None,
        valuation_at: datetime | None = None,
        materiality_threshold_eur: Decimal = Decimal("1"),
    ) -> Response:
        try:
            content = DivorceEqualizationService(db).capital_flows_csv(
                separation_date=separation_date,
                end_asset_date=end_asset_date,
                court_evidence_reference=court_evidence_reference,
                cutoff_at=cutoff_at,
                valuation_at=valuation_at,
                materiality_threshold_eur=materiality_threshold_eur,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return Response(
            content=content,
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=divorce-equalization-capital-flows.csv"
            },
        )

    @app.get("/api/v1/divorce/equalization-summary/evidence-package.zip")
    def divorce_equalization_evidence_package_zip(
        separation_date: date | None = None,
        end_asset_date: date | None = None,
        court_evidence_reference: str | None = None,
        cutoff_at: datetime | None = None,
        valuation_at: datetime | None = None,
        materiality_threshold_eur: Decimal = Decimal("1"),
    ) -> Response:
        try:
            content = DivorceEqualizationService(db).evidence_package_zip(
                separation_date=separation_date,
                end_asset_date=end_asset_date,
                court_evidence_reference=court_evidence_reference,
                cutoff_at=cutoff_at,
                valuation_at=valuation_at,
                materiality_threshold_eur=materiality_threshold_eur,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return Response(
            content=content,
            media_type="application/zip",
            headers={
                "Content-Disposition": "attachment; filename=divorce-equalization-evidence-package.zip"
            },
        )

    @app.post("/api/v1/divorce/valuation-runs")
    def divorce_valuation_run(
        payload: DivorceValuationRunRequest,
    ) -> ApiResponse[DivorceValuationRunReport]:
        try:
            report = DivorceValuationRunService(db).run(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return ApiResponse(data=report)

    @app.get("/api/v1/divorce/valuation-runs/latest")
    def divorce_valuation_run_latest() -> ApiResponse[DivorceValuationRunReport | None]:
        return ApiResponse(data=DivorceValuationRunService(db).latest())

    @app.get("/api/v1/divorce/valuation-runs/{run_id}")
    def divorce_valuation_run_by_id(
        run_id: str,
    ) -> ApiResponse[DivorceValuationRunReport]:
        report = DivorceValuationRunService(db).get(run_id)
        if report is None:
            raise HTTPException(status_code=404, detail="Stichtagslauf nicht gefunden")
        return ApiResponse(data=report)

    @app.get("/api/v1/divorce/valuation-runs/{run_id}/evidence/{filename}")
    def divorce_valuation_run_evidence(run_id: str, filename: str) -> Response:
        path = DivorceValuationRunService(db).evidence_path(run_id, filename)
        if path is None:
            raise HTTPException(
                status_code=404, detail="Stichtags-Belegdatei nicht gefunden"
            )
        media_type = (
            "application/zip"
            if path.suffix == ".zip"
            else "text/csv"
            if path.suffix == ".csv"
            else "application/json"
        )
        return Response(
            content=path.read_bytes(),
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/v1/sources/overview")
    def sources_overview() -> ApiResponse[SourceOverview]:
        return ApiResponse(data=SourceService(db).overview())

    @app.get("/api/v1/sources/connector-diagnostics")
    def sources_connector_diagnostics() -> ApiResponse[
        SourceConnectorDiagnosticsReport
    ]:
        return ApiResponse(data=SourceService(db).connector_diagnostics())

    @app.get("/api/v1/sources/registry/config")
    def sources_registry_config() -> ApiResponse[SourceRegistryConfig]:
        try:
            config = SourceRegistryService(db).config()
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=500, detail=f"Quellenregistry ungueltig: {exc}"
            ) from exc
        return ApiResponse(data=config)

    @app.post("/api/v1/sources/registry/runs")
    def sources_registry_run() -> ApiResponse[SourceRegistryRunReport]:
        try:
            report = SourceRegistryService(db).run()
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=500, detail=f"Quellenregistry-Lauf fehlgeschlagen: {exc}"
            ) from exc
        clear_response_cache()
        return ApiResponse(data=report)

    @app.get("/api/v1/sources/registry/runs/latest")
    def sources_registry_run_latest() -> ApiResponse[SourceRegistryRunReport | None]:
        return ApiResponse(data=SourceRegistryService(db).latest())

    @app.get("/api/v1/tax-methodology/legal-research/sources")
    def legal_research_sources() -> ApiResponse[LegalResearchConfig]:
        try:
            config = LegalResearchService().config()
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=500, detail=f"Rechtsquellen-Registry ungueltig: {exc}"
            ) from exc
        return ApiResponse(data=config)

    @app.get("/api/v1/tax-methodology/legal-research/freshness")
    def legal_research_freshness() -> ApiResponse[LegalResearchFreshnessReport | None]:
        return ApiResponse(data=LegalResearchService().latest())

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
    def source_reconciliation(
        source_id: str,
    ) -> ApiResponse[SourceReconciliationBreakdown]:
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
        selected_assets = (
            [item.strip().upper() for item in assets.split(",") if item.strip()]
            if assets
            else None
        )
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
    def binance_earn_history_preflight() -> ApiResponse[
        BinanceEarnHistoryPreflightReport
    ]:
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
        selected_assets = (
            [item.strip().upper() for item in assets.split(",") if item.strip()]
            if assets
            else None
        )
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
        selected_assets = (
            [item.strip().upper() for item in assets.split(",") if item.strip()]
            if assets
            else None
        )
        return ApiResponse(
            data=BinanceEarnHistoryService(db).withdrawal_history_api_preview(
                since=since_at,
                until=until_at,
                assets=selected_assets,
                max_records=max(1, min(max_records, 5000)),
            )
        )

    @app.get("/api/v1/sources/binance/asset-dividend-api-preview")
    def binance_asset_dividend_api_preview(
        since: str | None = None,
        until: str | None = None,
        assets: str | None = "SOL",
        max_records: int = 5000,
    ) -> ApiResponse[BinanceAssetDividendPreview]:
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
        selected_assets = (
            [item.strip().upper() for item in assets.split(",") if item.strip()]
            if assets
            else None
        )
        return ApiResponse(
            data=BinanceEarnHistoryService(db).asset_dividend_history_api_preview(
                since=since_at,
                until=until_at,
                assets=selected_assets,
                max_records=max(1, min(max_records, 50000)),
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
        selected_assets = (
            [item.strip().upper() for item in assets.split(",") if item.strip()]
            if assets
            else None
        )
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
        selected_assets = [
            item.strip().upper() for item in payload.assets if item.strip()
        ]
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
        selected_assets = [
            item.strip().upper() for item in payload.assets if item.strip()
        ]
        return ApiResponse(
            data=BinanceEarnHistoryService(db).import_withdrawal_api_history(
                since=since_at,
                until=until_at,
                assets=selected_assets or None,
                max_records=max(1, min(payload.max_records, 5000)),
                execute=payload.execute,
            )
        )

    @app.post("/api/v1/sources/binance/asset-dividend-api/import")
    def binance_asset_dividend_api_import(
        payload: BinanceAssetDividendApiImportRequest,
    ) -> ApiResponse[BinanceAssetDividendApiImportResult]:
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
        selected_assets = [
            item.strip().upper() for item in payload.assets if item.strip()
        ]
        return ApiResponse(
            data=BinanceEarnHistoryService(db).import_asset_dividend_api_history(
                since=since_at,
                until=until_at,
                assets=selected_assets or ["SOL"],
                max_records=max(1, min(payload.max_records, 50000)),
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
        selected_assets = [
            item.strip().upper() for item in payload.assets if item.strip()
        ]
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
        return ApiResponse(
            data=cached_response("review:gates", 60, lambda: ReviewService(db).gate())
        )

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
    def add_review_decision(
        payload: ReviewDecisionCreate,
    ) -> ApiResponse[ReviewDecision]:
        decision = db.add_review_decision(payload)
        clear_response_cache()
        return ApiResponse(data=decision)

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
    def delete_v1_reference_metric(
        reference_id: str,
    ) -> ApiResponse[V1ReferenceDeleteResult]:
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
    def parity_hnt_wallet_bridge(
        year: int = 2022,
    ) -> ApiResponse[HntWalletBridgeReport]:
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
    def add_parity_decision(
        payload: V1ParityDecisionCreate,
    ) -> ApiResponse[V1ParityDecisionResult]:
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
    def tax_holding_periods(
        min_value_eur: Decimal = Decimal("1"),
    ) -> ApiResponse[TaxHoldingPeriodReport]:
        return ApiResponse(
            data=cached_response(
                f"tax:holding-periods:{min_value_eur}",
                60,
                lambda: TaxService(db).holding_period_report(
                    min_value_eur=min_value_eur
                ),
            )
        )

    @app.get("/api/v1/tax/loss-realization-planner")
    def tax_loss_realization_planner(
        min_loss_eur: Decimal = Decimal("1"),
        min_value_eur: Decimal = Decimal("1"),
        limit: int = 100,
    ) -> ApiResponse[TaxLossRealizationPlanner]:
        return ApiResponse(
            data=cached_response(
                f"tax:loss-realization-planner:{min_loss_eur}:{min_value_eur}:{limit}",
                60,
                lambda: TaxYearService(db).loss_realization_planner(
                    min_loss_eur=min_loss_eur,
                    min_value_eur=min_value_eur,
                    limit=limit,
                ),
            )
        )

    @app.get("/api/v1/tax/summary")
    def tax_summary() -> ApiResponse[TaxRunSummary | None]:
        return ApiResponse(data=TaxService(db).latest_summary())

    @app.get("/api/v1/tax/service-swap-mappings")
    def tax_service_swap_mappings() -> ApiResponse[ServiceSwapTaxMappingReport]:
        return ApiResponse(data=ServiceSwapTaxMappingService(db).report())

    @app.get("/api/v1/tax/pionex-hnt-reconciliation")
    def tax_pionex_hnt_reconciliation() -> ApiResponse[PionexHntReconciliationReport]:
        return ApiResponse(data=PionexHntReconciliationService(db).report())

    @app.get("/api/v1/tax/cross-cex-transfer-evidence")
    def tax_cross_cex_transfer_evidence() -> ApiResponse[
        CrossCexTransferEvidenceReport
    ]:
        return ApiResponse(data=CrossCexTransferEvidenceService(db).report())

    @app.get("/api/v1/tax/fairspot-staking-reconciliation")
    def tax_fairspot_staking_reconciliation() -> ApiResponse[
        FairspotStakingReconciliationReport
    ]:
        return ApiResponse(data=FairspotStakingReconciliationService(db).report())

    @app.get("/api/v1/tax/moonpay-receipts")
    def tax_moonpay_receipts(
        as_of: datetime | None = None,
    ) -> ApiResponse[MoonpayReceiptReport]:
        return ApiResponse(data=MoonpayReceiptService(db).report(as_of=as_of))

    @app.get("/api/v1/tax/moonpay-receipts/trade-history.csv")
    def tax_moonpay_trade_history_document() -> Response:
        service = MoonpayReceiptService(db)
        report = service.report()
        path = service.trade_history_path
        if (
            not report.trade_history_exists
            or report.trade_history_sha256 is None
            or not path.is_file()
            or hashlib.sha256(path.read_bytes()).hexdigest()
            != report.trade_history_sha256
        ):
            raise HTTPException(
                status_code=404, detail="moonpay_trade_history_not_found"
            )
        return Response(
            content=path.read_bytes(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="MoonPay_trade-history.csv"'
                ),
                "X-Content-SHA256": report.trade_history_sha256,
            },
        )

    @app.get("/api/v1/tax/moonpay-receipts/{tx_id}/document")
    def tax_moonpay_receipt_document(tx_id: str) -> Response:
        service = MoonpayReceiptService(db)
        path = service.document_path(tx_id)
        if path is None:
            raise HTTPException(status_code=404, detail="moonpay_receipt_not_found")
        media_type = (
            "text/csv; charset=utf-8"
            if path.suffix.lower() == ".csv"
            else "application/octet-stream"
        )
        return Response(
            content=path.read_bytes(),
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{path.name}"',
                "X-Content-SHA256": hashlib.sha256(path.read_bytes()).hexdigest(),
            },
        )

    @app.post("/api/v1/tax/moonpay-receipts")
    def tax_moonpay_receipt_upsert(
        payload: MoonpayReceiptUpsertRequest,
    ) -> ApiResponse[MoonpayReceiptUpsertResult]:
        try:
            result = MoonpayReceiptService(db).upsert(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        clear_response_cache()
        return ApiResponse(data=result)

    @app.get("/api/v1/tax/solana-staking-position-reconciliation")
    def tax_solana_staking_position_reconciliation() -> ApiResponse[
        SolanaStakingPositionReconciliationReport
    ]:
        return ApiResponse(data=SolanaStakingPositionReconciliationService(db).report())

    @app.get("/api/v1/tax/wallet-fifo-preview")
    def tax_wallet_fifo_preview(
        year: int | None = None,
        as_of: datetime | None = None,
    ) -> ApiResponse[WalletFifoPreviewReport]:
        return ApiResponse(
            data=WalletFifoPreviewService(db).preview(year=year, as_of=as_of)
        )

    @app.get("/api/v1/tax/wallet-fifo-internal-transfer-carry")
    def tax_wallet_fifo_internal_transfer_carry(
        year: int | None = None,
        limit: int = 200,
    ) -> ApiResponse[WalletFifoInternalTransferCarryReport]:
        return ApiResponse(
            data=WalletFifoPreviewService(db).internal_transfer_carry_report(
                year=year,
                limit=limit,
            )
        )

    @app.post("/api/v1/tax/wallet-fifo-runs")
    def tax_wallet_fifo_parallel_run(
        payload: WalletFifoParallelRunRequest,
    ) -> ApiResponse[WalletFifoParallelRunReport]:
        try:
            report = WalletFifoParallelRunService(db).run(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        clear_response_cache()
        return ApiResponse(data=report)

    @app.get("/api/v1/tax/wallet-fifo-runs/latest")
    def tax_wallet_fifo_parallel_run_latest() -> ApiResponse[
        WalletFifoParallelRunReport | None
    ]:
        return ApiResponse(data=WalletFifoParallelRunService(db).latest())

    @app.get("/api/v1/tax/wallet-fifo/bitget-strategy-gaps")
    def tax_wallet_fifo_bitget_strategy_gaps(
        run_id: str | None = None,
    ) -> ApiResponse[BitgetStrategyFifoGapReport]:
        report = BitgetStrategyFifoGapService(db).report(run_id=run_id)
        if report is None:
            raise HTTPException(
                status_code=404,
                detail="Wallet-FIFO-Lauf fuer Bitget-Strategy-Nachweis nicht gefunden",
            )
        return ApiResponse(data=report)

    @app.get("/api/v1/tax/wallet-fifo/bitget-strategy-gaps.csv")
    def tax_wallet_fifo_bitget_strategy_gaps_csv(
        run_id: str | None = None,
    ) -> Response:
        service = BitgetStrategyFifoGapService(db)
        report = service.report(run_id=run_id)
        if report is None:
            raise HTTPException(
                status_code=404,
                detail="Wallet-FIFO-Lauf fuer Bitget-Strategy-Nachweis nicht gefunden",
            )
        return Response(
            content=service.csv_bytes(report),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="bitget-strategy-fifo-gaps.csv"'
                )
            },
        )

    @app.get("/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction")
    def tax_wallet_fifo_bitget_strategy_reconstruction(
        run_id: str | None = None,
    ) -> ApiResponse[BitgetStrategyBasisReconstructionReport]:
        report = BitgetStrategyBasisReconstructionService(db).report(run_id=run_id)
        if report is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Gebundene Bitget-Strategy-Rekonstruktionsakte nicht gefunden; "
                    "neuen Wallet-FIFO-Lauf erzeugen"
                ),
            )
        return ApiResponse(data=report)

    @app.get("/api/v1/tax/wallet-fifo/bitget-strategy-basis-decision")
    def tax_wallet_fifo_bitget_strategy_basis_decision(
        run_id: str | None = None,
    ) -> ApiResponse[BitgetStrategyBasisDecisionReport]:
        report = BitgetStrategyBasisDecisionService(db).readiness(run_id=run_id)
        if report.run_id is None:
            raise HTTPException(
                status_code=404,
                detail="Wallet-FIFO-Lauf fuer Bitget-Basisentscheidung nicht gefunden",
            )
        return ApiResponse(data=report)

    @app.post(
        "/api/v1/tax/wallet-fifo/bitget-strategy-basis-decision/{run_id}"
    )
    def tax_wallet_fifo_bitget_strategy_basis_decision_create(
        run_id: str,
        payload: BitgetStrategyBasisDecisionRequest,
    ) -> ApiResponse[BitgetStrategyBasisDecisionResult]:
        try:
            result = BitgetStrategyBasisDecisionService(db).decide(
                run_id=run_id,
                request=payload,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        clear_response_cache()
        return ApiResponse(data=result)

    @app.get("/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction.csv")
    def tax_wallet_fifo_bitget_strategy_reconstruction_csv(
        run_id: str | None = None,
    ) -> Response:
        service = BitgetStrategyBasisReconstructionService(db)
        report = service.report(run_id=run_id)
        if report is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "Gebundene Bitget-Strategy-Rekonstruktionsakte nicht gefunden; "
                    "neuen Wallet-FIFO-Lauf erzeugen"
                ),
            )
        return Response(
            content=service.csv_bytes(report),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (
                    'attachment; filename="bitget-strategy-basis-reconstruction.csv"'
                )
            },
        )

    @app.get(
        "/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction/"
        "reference-price-backfill/latest"
    )
    def tax_wallet_fifo_bitget_strategy_reference_price_backfill_latest() -> (
        ApiResponse[BitgetStrategyReferencePriceBackfillResult | None]
    ):
        return ApiResponse(
            data=BitgetStrategyBasisReconstructionService(db).latest_backfill()
        )

    @app.post(
        "/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction/"
        "reference-price-backfill"
    )
    def tax_wallet_fifo_bitget_strategy_reference_price_backfill(
        payload: BitgetStrategyReferencePriceBackfillRequest,
    ) -> ApiResponse[BitgetStrategyReferencePriceBackfillResult]:
        try:
            result = BitgetStrategyBasisReconstructionService(
                db
            ).backfill_reference_prices(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if result.imported_count:
            clear_response_cache()
        return ApiResponse(data=result)

    @app.get("/api/v1/tax/wallet-fifo/bitget-support-package.zip")
    def tax_wallet_fifo_bitget_support_package(
        run_id: str | None = None,
    ) -> Response:
        service = BitgetStrategyFifoGapService(db)
        report = service.report(run_id=run_id)
        if report is None:
            raise HTTPException(
                status_code=404,
                detail="Wallet-FIFO-Lauf fuer Bitget-Supportpaket nicht gefunden",
            )
        try:
            content = service.support_package_zip_bytes(report.support_package)
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Bitget-Supportpaket konnte nicht gebunden werden: {exc}",
            ) from exc
        return Response(
            content=content,
            media_type="application/zip",
            headers={
                "Content-Disposition": (
                    'attachment; filename="bitget-support-package.zip"'
                )
            },
        )

    @app.get("/api/v1/tax/wallet-fifo/bitget-strategy-review.html")
    def tax_wallet_fifo_bitget_strategy_review_html(
        run_id: str | None = None,
    ) -> Response:
        gap_service = BitgetStrategyFifoGapService(db)
        reconstruction_service = BitgetStrategyBasisReconstructionService(db)
        gap_report = gap_service.report(run_id=run_id)
        reconstruction = reconstruction_service.report(run_id=run_id)
        if gap_report is None or reconstruction is None:
            raise HTTPException(
                status_code=404,
                detail="Gebundene Bitget-Strategy-Fachakte nicht gefunden",
            )
        if gap_report.run_id != reconstruction.run_id:
            raise HTTPException(
                status_code=409,
                detail="Bitget-Gap- und Rekonstruktionsakte sind nicht an denselben Lauf gebunden",
            )
        return Response(
            content=reconstruction_service.professional_review_html(
                reconstruction,
                gap_report,
                BitgetStrategyBasisDecisionService(db).readiness(
                    run_id=reconstruction.run_id
                ),
            ),
            media_type="text/html; charset=utf-8",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/v1/tax/wallet-fifo/bitget-strategy-review-package.zip")
    def tax_wallet_fifo_bitget_strategy_review_package(
        run_id: str | None = None,
    ) -> Response:
        gap_service = BitgetStrategyFifoGapService(db)
        reconstruction_service = BitgetStrategyBasisReconstructionService(db)
        gap_report = gap_service.report(run_id=run_id)
        reconstruction = reconstruction_service.report(run_id=run_id)
        if gap_report is None or reconstruction is None:
            raise HTTPException(
                status_code=404,
                detail="Gebundenes Bitget-Strategy-Pruefpaket nicht gefunden",
            )
        if gap_report.run_id != reconstruction.run_id:
            raise HTTPException(
                status_code=409,
                detail="Bitget-Gap- und Rekonstruktionsakte sind nicht an denselben Lauf gebunden",
            )
        try:
            support_zip = gap_service.support_package_zip_bytes(
                gap_report.support_package
            )
            content = reconstruction_service.professional_review_package_bytes(
                reconstruction,
                gap_report,
                support_package_zip=support_zip,
            )
        except (OSError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail=f"Bitget-Strategy-Pruefpaket konnte nicht gebunden werden: {exc}",
            ) from exc
        return Response(
            content=content,
            media_type="application/zip",
            headers={
                "Content-Disposition": (
                    'attachment; filename="bitget-strategy-fifo-review-package.zip"'
                ),
                "Cache-Control": "no-store",
            },
        )

    @app.get("/api/v1/tax/wallet-fifo-runs/latest/method-acceptance")
    def tax_wallet_fifo_latest_method_acceptance() -> ApiResponse[
        WalletFifoMethodAcceptanceReport
    ]:
        return ApiResponse(
            data=cached_response(
                "tax:wallet-fifo:latest:method-acceptance",
                60,
                lambda: WalletFifoMethodAcceptanceService(db).readiness(),
            )
        )

    @app.get("/api/v1/tax/wallet-fifo-runs/latest/method-delta-explanation")
    def tax_wallet_fifo_latest_method_delta_explanation(
        year: int | None = None,
        asset: str | None = None,
        event_limit: int = 20,
    ) -> ApiResponse[WalletFifoMethodDeltaExplanationReport | None]:
        try:
            report = WalletFifoParallelRunService(db).method_delta_explanation(
                year=year,
                asset=asset,
                event_limit=event_limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return ApiResponse(data=report)

    @app.get("/api/v1/tax/wallet-fifo-runs/{run_id}")
    def tax_wallet_fifo_parallel_run_by_id(
        run_id: str,
    ) -> ApiResponse[WalletFifoParallelRunReport]:
        report = WalletFifoParallelRunService(db).get(run_id)
        if report is None:
            raise HTTPException(
                status_code=404, detail="Wallet-FIFO-Lauf nicht gefunden"
            )
        return ApiResponse(data=report)

    @app.get("/api/v1/tax/wallet-fifo-runs/{run_id}/method-acceptance")
    def tax_wallet_fifo_method_acceptance(
        run_id: str,
    ) -> ApiResponse[WalletFifoMethodAcceptanceReport]:
        report = WalletFifoMethodAcceptanceService(db).readiness(run_id=run_id)
        if report.run_id is None:
            raise HTTPException(
                status_code=404,
                detail="Wallet-FIFO-Lauf nicht gefunden",
            )
        return ApiResponse(data=report)

    @app.post("/api/v1/tax/wallet-fifo-runs/{run_id}/method-acceptance")
    def tax_wallet_fifo_method_acceptance_create(
        run_id: str,
        payload: WalletFifoMethodAcceptanceRequest,
    ) -> ApiResponse[WalletFifoMethodAcceptanceResult]:
        try:
            result = WalletFifoMethodAcceptanceService(db).accept(run_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        clear_response_cache()
        return ApiResponse(data=result)

    @app.post("/api/v1/tax/wallet-fifo-migrations/rehearsals")
    def tax_wallet_fifo_migration_rehearsal(
        payload: WalletFifoMigrationRehearsalRequest,
    ) -> ApiResponse[WalletFifoMigrationRehearsalReport]:
        try:
            report = WalletFifoMigrationRehearsalService(db).rehearse(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        clear_response_cache()
        return ApiResponse(data=report)

    @app.get("/api/v1/tax/wallet-fifo-migrations/rehearsals/latest")
    def tax_wallet_fifo_migration_rehearsal_latest() -> ApiResponse[
        WalletFifoMigrationRehearsalReport | None
    ]:
        return ApiResponse(data=WalletFifoMigrationRehearsalService(db).latest())

    @app.get("/api/v1/tax/wallet-fifo-migrations/rehearsals/{rehearsal_id}")
    def tax_wallet_fifo_migration_rehearsal_by_id(
        rehearsal_id: str,
    ) -> ApiResponse[WalletFifoMigrationRehearsalReport]:
        report = WalletFifoMigrationRehearsalService(db).get(rehearsal_id)
        if report is None:
            raise HTTPException(
                status_code=404,
                detail="Wallet-FIFO-Migrationsprobe nicht gefunden",
            )
        return ApiResponse(data=report)

    @app.get("/api/v1/tax/wallet-fifo-migrations/apply-readiness")
    def tax_wallet_fifo_migration_apply_readiness(
        run_id: str | None = None,
        rehearsal_id: str | None = None,
    ) -> ApiResponse[WalletFifoMigrationApplyReadinessReport]:
        return ApiResponse(
            data=WalletFifoMigrationApplyService(db).readiness(
                run_id=run_id,
                rehearsal_id=rehearsal_id,
            )
        )

    @app.post("/api/v1/tax/wallet-fifo-migrations/apply")
    def tax_wallet_fifo_migration_apply(
        payload: WalletFifoMigrationApplyRequest,
    ) -> ApiResponse[WalletFifoMigrationApplyReport]:
        try:
            report = WalletFifoMigrationApplyService(db).apply(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        clear_response_cache()
        return ApiResponse(data=report)

    @app.get("/api/v1/tax/wallet-fifo-migrations/applies/latest")
    def tax_wallet_fifo_migration_apply_latest() -> ApiResponse[
        WalletFifoMigrationApplyReport | None
    ]:
        return ApiResponse(data=WalletFifoMigrationApplyService(db).latest())

    @app.get("/api/v1/tax/wallet-fifo-runs/{run_id}/method-delta-explanation")
    def tax_wallet_fifo_method_delta_explanation(
        run_id: str,
        year: int | None = None,
        asset: str | None = None,
        event_limit: int = 20,
    ) -> ApiResponse[WalletFifoMethodDeltaExplanationReport]:
        try:
            report = WalletFifoParallelRunService(db).method_delta_explanation(
                run_id=run_id,
                year=year,
                asset=asset,
                event_limit=event_limit,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if report is None:
            raise HTTPException(
                status_code=404,
                detail="Methodendifferenz-Erklaerreport nicht gefunden",
            )
        return ApiResponse(data=report)

    @app.get("/api/v1/tax/wallet-fifo-runs/{run_id}/evidence/{filename}")
    def tax_wallet_fifo_parallel_run_evidence(run_id: str, filename: str) -> Response:
        path = WalletFifoParallelRunService(db).evidence_path(run_id, filename)
        if path is None:
            raise HTTPException(
                status_code=404, detail="Wallet-FIFO-Belegdatei nicht gefunden"
            )
        return Response(
            content=path.read_bytes(),
            media_type=(
                "application/json" if path.suffix == ".json" else "application/gzip"
            ),
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/v1/tax/legacy-helium-overview")
    def tax_legacy_helium_overview(
        limit: int = 200,
    ) -> ApiResponse[LegacyHeliumOverviewReport]:
        return ApiResponse(
            data=cached_response(
                f"tax:legacy-helium-overview:{limit}",
                60,
                lambda: WalletFifoPreviewService(db).legacy_helium_overview(
                    limit=limit
                ),
            )
        )

    @app.get("/api/v1/tax-years/summary")
    def tax_years_summary() -> ApiResponse[TaxYearsSummary]:
        return ApiResponse(
            data=cached_response(
                "tax-years:summary",
                60,
                lambda: TaxYearService(db).summary(),
            )
        )

    @app.get("/api/v1/tax-years/payment-overview")
    def tax_years_payment_overview() -> ApiResponse[TaxPaymentOverview]:
        return ApiResponse(
            data=cached_response(
                "tax-years:payment-overview",
                60,
                lambda: TaxYearService(db).payment_overview(),
            )
        )

    @app.get("/api/v1/tax-years/filing-matrix")
    def tax_years_filing_matrix() -> ApiResponse[TaxYearFilingMatrix]:
        return ApiResponse(
            data=cached_response(
                "tax-years:filing-matrix",
                10,
                lambda: TaxYearService(db).filing_matrix(),
            )
        )

    @app.get("/api/v1/tax-years/filing-closure-overview")
    def tax_years_filing_closure_overview() -> ApiResponse[
        TaxYearsFilingClosureOverview
    ]:
        return ApiResponse(
            data=cached_response(
                "tax-years:filing-closure-overview",
                10,
                lambda: TaxYearService(db).filing_closure_overview(),
            )
        )

    @app.get("/api/v1/tax-years/reward-trading-separation")
    def tax_years_reward_trading_separation() -> ApiResponse[
        TaxRewardTradingSeparationReport
    ]:
        return ApiResponse(
            data=cached_response(
                "tax-years:reward-trading-separation",
                60,
                lambda: TaxYearService(db).reward_trading_separation(),
            )
        )

    @app.get("/api/v1/tax-years/business-reward-inventory-review")
    def tax_years_business_reward_inventory_review() -> ApiResponse[
        BusinessRewardInventoryReviewReport
    ]:
        return ApiResponse(
            data=cached_response(
                "tax-years:business-reward-inventory-review",
                60,
                lambda: BusinessRewardInventoryReviewService(db).review(),
            )
        )

    @app.get("/api/v1/tax/crypto-swap-valuation-review")
    def tax_crypto_swap_valuation_review(
        limit: int = 200,
        year: int | None = None,
    ) -> ApiResponse[CryptoSwapValuationReviewReport]:
        return ApiResponse(
            data=cached_response(
                f"tax:crypto-swap-valuation-review:{year}:{limit}",
                60,
                lambda: CryptoSwapValuationReviewService(db).review(
                    limit=limit,
                    year=year,
                ),
            )
        )

    @app.get("/api/v1/tax/crypto-swap-fifo-parallel-preview/latest")
    def tax_crypto_swap_fifo_parallel_preview_latest() -> ApiResponse[
        CryptoSwapFifoParallelPreviewReport
    ]:
        report = CryptoSwapFifoParallelPreviewService(db).latest()
        if report is None:
            raise HTTPException(
                status_code=404,
                detail="crypto_swap_fifo_parallel_preview_missing",
            )
        return ApiResponse(data=report)

    @app.post("/api/v1/tax/crypto-swap-fifo-parallel-preview/run")
    def tax_crypto_swap_fifo_parallel_preview_run(
        payload: CryptoSwapFifoParallelRunRequest,
    ) -> ApiResponse[CryptoSwapFifoParallelPreviewReport]:
        return ApiResponse(
            data=CryptoSwapFifoParallelPreviewService(db).run(
                limit=max(1, min(payload.limit, 5000))
            )
        )

    @app.get("/api/v1/tax/bmf-combined-fifo-staging/latest")
    def tax_bmf_combined_fifo_staging_latest() -> ApiResponse[
        BmfCombinedFifoStagingReport
    ]:
        report = BmfCombinedFifoStagingService(db).latest()
        if report is None:
            raise HTTPException(
                status_code=404,
                detail="bmf_combined_fifo_staging_missing",
            )
        return ApiResponse(data=report)

    @app.post("/api/v1/tax/bmf-combined-fifo-staging/run")
    def tax_bmf_combined_fifo_staging_run(
        payload: BmfFifoStagingRunRequest,
    ) -> ApiResponse[BmfCombinedFifoStagingReport]:
        try:
            report = BmfCombinedFifoStagingService(db).run(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return ApiResponse(data=report)

    @app.get("/api/v1/tax/bmf-fifo-event-evidence/latest")
    def tax_bmf_fifo_event_evidence_latest() -> ApiResponse[BmfFifoEventEvidenceReport]:
        report = BmfFifoEventEvidenceService(db).latest()
        if report is None:
            raise HTTPException(
                status_code=404,
                detail="bmf_fifo_event_evidence_missing",
            )
        return ApiResponse(data=report)

    @app.get("/api/v1/tax/bmf-fifo-event-evidence/events.jsonl.gz")
    def tax_bmf_fifo_event_evidence_events_artifact() -> Response:
        service = BmfFifoEventEvidenceService(db)
        report = service.latest()
        if report is None or not report.all_event_evidence_artifact_path:
            raise HTTPException(
                status_code=404,
                detail="bmf_fifo_event_evidence_artifact_missing",
            )
        artifact_path = Path(report.all_event_evidence_artifact_path)
        if not artifact_path.is_absolute():
            artifact_path = service.PROJECT_ROOT / artifact_path
        artifact_path = artifact_path.resolve()
        artifact_root = service.artifact_root.resolve()
        if (
            artifact_path != artifact_root
            and artifact_root not in artifact_path.parents
        ):
            raise HTTPException(
                status_code=403,
                detail="bmf_fifo_event_evidence_artifact_path_invalid",
            )
        try:
            content = artifact_path.read_bytes()
        except OSError as exc:
            raise HTTPException(
                status_code=404,
                detail="bmf_fifo_event_evidence_artifact_missing",
            ) from exc
        return Response(
            content=content,
            media_type="application/gzip",
            headers={
                "Content-Disposition": (f'attachment; filename="{artifact_path.name}"'),
                "X-Content-SHA256": (report.all_event_evidence_artifact_sha256 or ""),
            },
        )

    @app.post("/api/v1/tax/bmf-fifo-event-evidence/run")
    def tax_bmf_fifo_event_evidence_run(
        payload: BmfFifoEventEvidenceRunRequest,
    ) -> ApiResponse[BmfFifoEventEvidenceReport]:
        try:
            report = BmfFifoEventEvidenceService(db).run(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return ApiResponse(data=report)

    @app.get("/api/v1/tax/bmf-event-price-remediation/latest")
    def tax_bmf_event_price_remediation_latest() -> ApiResponse[
        BmfEventPriceRemediationReport
    ]:
        report = BmfEventPriceRemediationService(db).latest()
        if report is None:
            raise HTTPException(
                status_code=404,
                detail="bmf_event_price_remediation_missing",
            )
        return ApiResponse(data=report)

    @app.post("/api/v1/tax/bmf-event-price-remediation/run")
    def tax_bmf_event_price_remediation_run(
        payload: BmfEventPriceRemediationRunRequest,
    ) -> ApiResponse[BmfEventPriceRemediationReport]:
        try:
            report = BmfEventPriceRemediationService(db).run(payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return ApiResponse(
            status="ok" if report.status in {"planned", "applied"} else "warning",
            data=report,
        )

    @app.get("/api/v1/tax-years/correction-map")
    def tax_years_correction_map() -> ApiResponse[TaxYearsCorrectionMap]:
        return ApiResponse(
            data=cached_response(
                "tax-years:correction-map",
                60,
                lambda: TaxYearService(db).correction_map(),
            )
        )

    @app.get("/api/v1/tax-years/turnover-audit-summary")
    def tax_years_turnover_audit_summary(
        limit: int = 20,
    ) -> ApiResponse[TaxYearsTurnoverAuditSummary]:
        return ApiResponse(
            data=cached_response(
                f"tax-years:turnover-audit-summary:{limit}",
                60,
                lambda: TaxYearService(db).turnover_audit_summary(limit=limit),
            )
        )

    @app.get("/api/v1/tax-years/solana-program-income-review")
    def tax_years_solana_program_income_review(
        limit: int = 200,
    ) -> ApiResponse[TaxSolanaProgramIncomeReview]:
        return ApiResponse(
            data=TaxYearService(db).solana_program_income_review(limit=limit)
        )

    @app.get("/api/v1/tax-years/helium-swap-context")
    def tax_years_helium_swap_context(
        limit: int = 200,
    ) -> ApiResponse[TaxHeliumSwapContextReview]:
        return ApiResponse(
            data=TaxYearService(db).helium_swap_context_review(limit=limit)
        )

    @app.get("/api/v1/tax-years/helium-swap-evidence-review")
    def tax_years_helium_swap_evidence_review(
        limit: int = 50,
    ) -> ApiResponse[TaxHeliumSwapEvidenceReview]:
        return ApiResponse(
            data=TaxYearService(db).helium_swap_evidence_review(limit=limit)
        )

    @app.get("/api/v1/tax-years/stablecoin-fifo-review")
    def tax_years_stablecoin_fifo_review(
        limit: int = 200,
    ) -> ApiResponse[TaxStablecoinFifoReview]:
        return ApiResponse(data=TaxYearService(db).stablecoin_fifo_review(limit=limit))

    @app.get("/api/v1/tax-years/stablecoin-quote-leg-review")
    def tax_years_stablecoin_quote_leg_review(
        limit: int = 200,
    ) -> ApiResponse[TaxStablecoinQuoteLegReview]:
        return ApiResponse(
            data=TaxYearService(db).stablecoin_quote_leg_review(limit=limit)
        )

    @app.get("/api/v1/tax-years/solana-stablecoin-swap-context")
    def tax_years_solana_stablecoin_swap_context(
        limit: int = 200,
    ) -> ApiResponse[TaxSolanaStablecoinSwapContextReview]:
        return ApiResponse(
            data=TaxYearService(db).solana_stablecoin_swap_context_review(limit=limit)
        )

    @app.get("/api/v1/tax-years/solana-stablecoin-fx-review")
    def tax_years_solana_stablecoin_fx_review(
        limit: int = 200,
    ) -> ApiResponse[TaxSolanaStablecoinFxReview]:
        return ApiResponse(
            data=TaxYearService(db).solana_stablecoin_fx_review(limit=limit)
        )

    @app.get("/api/v1/tax-methodology/summary")
    def tax_methodology_summary(
        year: int | None = None,
    ) -> ApiResponse[TaxMethodologySummary]:
        return ApiResponse(
            data=cached_response(
                f"tax-methodology:summary:{year or 'all'}",
                60,
                lambda: TaxMethodologyService(db).summary(year=year),
            )
        )

    @app.get("/api/v1/tax-methodology/bmf-compliance-matrix")
    def tax_methodology_bmf_compliance_matrix() -> ApiResponse[TaxBmfComplianceMatrix]:
        return ApiResponse(
            data=cached_response(
                "tax-methodology:bmf-compliance-matrix",
                60,
                lambda: BmfComplianceMatrixService(db).matrix(),
            )
        )

    @app.get("/api/v1/tax-methodology/time-precision-audit")
    def tax_methodology_time_precision_audit(
        limit: int = 200,
    ) -> ApiResponse[TaxTimePrecisionAudit]:
        return ApiResponse(
            data=cached_response(
                f"tax-methodology:time-precision-audit:{limit}",
                60,
                lambda: TaxTimePolicyService(db).audit(limit=limit),
            )
        )

    @app.get("/api/v1/tax-methodology/bmf-action-plan")
    def tax_methodology_bmf_action_plan(
        year: int | None = None,
        include_gain_evidence: bool = False,
    ) -> ApiResponse[TaxBmfActionPlan]:
        return ApiResponse(
            data=cached_response(
                f"tax-methodology:bmf-action-plan:{year or 'all'}:{include_gain_evidence}",
                60,
                lambda: TaxMethodologyService(db).bmf_action_plan(
                    year=year,
                    include_gain_evidence=include_gain_evidence,
                    prefer_snapshot=True,
                ),
            )
        )

    @app.get("/api/v1/tax-methodology/bmf-closure-backlog")
    def tax_methodology_bmf_closure_backlog(
        year: int | None = None,
    ) -> ApiResponse[TaxBmfClosureBacklogReport]:
        return ApiResponse(
            data=TaxMethodologyService(db).bmf_closure_backlog(year=year)
        )

    @app.get("/api/v1/tax-methodology/bmf-closure-backlog-snapshot")
    def tax_methodology_bmf_closure_backlog_snapshot() -> ApiResponse[
        TaxBmfClosureBacklogSnapshot
    ]:
        return ApiResponse(
            data=TaxMethodologyService(db).bmf_closure_backlog_snapshot()
        )

    @app.get("/api/v1/tax-methodology/bmf-filing-readiness")
    def tax_methodology_bmf_filing_readiness(
        year: int | None = None,
    ) -> ApiResponse[TaxBmfFilingReadinessReport]:
        service = TaxMethodologyService(db)
        if year is None:
            snapshot = service.bmf_filing_readiness_snapshot()
            if snapshot.status == "available" and snapshot.report is not None:
                return ApiResponse(data=snapshot.report)
        return ApiResponse(data=service.bmf_filing_readiness(year=year))

    @app.get("/api/v1/tax-methodology/bmf-filing-readiness-snapshot")
    def tax_methodology_bmf_filing_readiness_snapshot() -> ApiResponse[
        TaxBmfFilingReadinessSnapshot
    ]:
        return ApiResponse(
            data=TaxMethodologyService(db).bmf_filing_readiness_snapshot()
        )

    @app.get("/api/v1/tax-methodology/bmf-finalization-matrix")
    def tax_methodology_bmf_finalization_matrix(
        include_reward_recheck: bool = False,
    ) -> ApiResponse[TaxBmfFinalizationMatrix]:
        return ApiResponse(
            data=cached_response(
                f"tax-methodology:bmf-finalization-matrix:{include_reward_recheck}",
                60,
                lambda: TaxMethodologyService(db).bmf_finalization_matrix(
                    include_reward_recheck=include_reward_recheck,
                ),
            )
        )

    @app.get("/api/v1/tax-methodology/bmf-submission-guide")
    def tax_methodology_bmf_submission_guide() -> ApiResponse[TaxBmfSubmissionGuide]:
        return ApiResponse(
            data=cached_response(
                "tax-methodology:bmf-submission-guide",
                300,
                lambda: TaxMethodologyService(db).bmf_submission_guide(),
            )
        )

    @app.get("/api/v1/tax-methodology/bmf-prior-filing-comparison")
    def tax_methodology_bmf_prior_filing_comparison() -> ApiResponse[
        TaxBmfPriorFilingComparison
    ]:
        return ApiResponse(
            data=cached_response(
                "tax-methodology:bmf-prior-filing-comparison",
                300,
                lambda: TaxMethodologyService(db).bmf_prior_filing_comparison(),
            )
        )

    @app.get("/api/v1/tax-methodology/bmf-amendment-worklist")
    def tax_methodology_bmf_amendment_worklist() -> ApiResponse[
        TaxBmfAmendmentWorklist
    ]:
        return ApiResponse(
            data=cached_response(
                "tax-methodology:bmf-amendment-worklist",
                300,
                lambda: TaxMethodologyService(db).bmf_amendment_worklist(),
            )
        )

    def render_bmf_amendment_worklist_csv(
        *, service: TaxMethodologyService | None = None
    ) -> str:
        worklist = (service or TaxMethodologyService(db)).bmf_amendment_worklist()
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "Year",
                "Status",
                "Prior_Filing_Status",
                "Prior_Filing_Values_Source",
                "Prior_Filing_Snapshot_ID",
                "Prior_Filing_Absolute_Delta_EUR",
                "ELSTER_Field_Verification_Required",
                "V2_Taxable_Private_Disposals_EUR",
                "V2_Rewards_Mining_Staking_Income_EUR",
                "V2_Derivative_Pnl_EUR",
                "V2_Tax_Free_Private_Disposals_EUR",
                "Technical_Review_Requirements_Count",
                "Amendment_Review_Recommended",
                "Correction_Reason",
                "Next_Action",
                "Filing_Summary_Endpoint",
                "Correction_Map_Endpoint",
                "Correction_Map_CSV_Endpoint",
                "Evidence_Package_Endpoint",
            ],
        )
        writer.writeheader()
        for row in worklist.years:
            writer.writerow(
                {
                    "Year": row.year,
                    "Status": row.status,
                    "Prior_Filing_Status": row.prior_filing_status,
                    "Prior_Filing_Values_Source": row.prior_filing_values_source,
                    "Prior_Filing_Snapshot_ID": row.prior_filing_snapshot_id,
                    "Prior_Filing_Absolute_Delta_EUR": row.prior_filing_absolute_delta_eur.quantize(
                        Decimal("0.01")
                    ),
                    "ELSTER_Field_Verification_Required": "yes"
                    if row.elster_field_verification_required
                    else "no",
                    "V2_Taxable_Private_Disposals_EUR": row.v2_taxable_private_disposals_eur.quantize(
                        Decimal("0.01")
                    ),
                    "V2_Rewards_Mining_Staking_Income_EUR": row.v2_rewards_mining_staking_income_eur.quantize(
                        Decimal("0.01")
                    ),
                    "V2_Derivative_Pnl_EUR": row.v2_derivative_pnl_eur.quantize(
                        Decimal("0.01")
                    ),
                    "V2_Tax_Free_Private_Disposals_EUR": row.v2_tax_free_private_disposals_eur.quantize(
                        Decimal("0.01")
                    ),
                    "Technical_Review_Requirements_Count": row.technical_review_requirements_count,
                    "Amendment_Review_Recommended": "yes"
                    if row.amendment_review_recommended
                    else "no",
                    "Correction_Reason": row.correction_reason,
                    "Next_Action": row.next_action,
                    "Filing_Summary_Endpoint": row.filing_summary_endpoint,
                    "Correction_Map_Endpoint": row.correction_map_endpoint,
                    "Correction_Map_CSV_Endpoint": row.correction_map_csv_endpoint,
                    "Evidence_Package_Endpoint": row.evidence_package_endpoint,
                }
            )
        return output.getvalue()

    @app.get("/api/v1/export/tax-methodology/bmf-amendment-worklist.csv")
    def download_bmf_amendment_worklist_csv() -> Response:
        return Response(
            content=render_bmf_amendment_worklist_csv(),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=bmf-amendment-worklist.csv"
            },
        )

    @app.get("/api/v1/tax-methodology/bmf-prior-filing-declared-amounts")
    def tax_methodology_bmf_prior_filing_declared_amounts() -> ApiResponse[
        TaxBmfPriorFilingDeclaredAmounts
    ]:
        return ApiResponse(
            data=TaxMethodologyService(db).bmf_prior_filing_declared_amounts()
        )

    @app.put("/api/v1/tax-methodology/bmf-prior-filing-declared-amounts")
    def tax_methodology_write_bmf_prior_filing_declared_amounts(
        payload: TaxBmfPriorFilingDeclaredAmountsWrite,
    ) -> ApiResponse[TaxBmfPriorFilingDeclaredAmountsWriteResult]:
        result = TaxMethodologyService(db).write_bmf_prior_filing_declared_amounts(
            payload
        )
        clear_response_cache()
        return ApiResponse(data=result)

    @app.get("/api/v1/tax-years/reward-bmf-recheck")
    def tax_years_reward_bmf_recheck() -> ApiResponse[TaxRewardBmfRecheckReport]:
        return ApiResponse(data=TaxMethodologyService(db).reward_bmf_recheck())

    @app.get("/api/v1/tax-years/{year}")
    def tax_year_detail(year: int) -> ApiResponse[TaxYearDetail]:
        return ApiResponse(
            data=cached_response(
                f"tax-years:detail:{year}",
                60,
                lambda: TaxYearService(db).detail(year),
            )
        )

    def wants_html_response(accept: str | None) -> bool:
        if not isinstance(accept, str) or not accept:
            return False
        normalized = accept.lower()
        return "text/html" in normalized and "application/json" not in normalized

    @app.get("/api/v1/tax-years/{year}/declaration-guide")
    def tax_year_declaration_guide(
        year: int, accept: str | None = Header(default=None)
    ):
        if wants_html_response(accept):
            summary = cached_response(
                f"tax-years:filing-summary:{year}",
                60,
                lambda: TaxYearService(db).filing_summary(year),
            )
            return Response(
                content=render_tax_year_filing_summary_html(summary),
                media_type="text/html; charset=utf-8",
            )
        return ApiResponse(
            data=cached_response(
                f"tax-years:declaration-guide:{year}",
                60,
                lambda: TaxYearService(db).declaration_guide(year),
            )
        )

    @app.get("/api/v1/tax-years/{year}/declaration-guide.html")
    def tax_year_declaration_guide_html(year: int) -> Response:
        summary = cached_response(
            f"tax-years:filing-summary:{year}",
            60,
            lambda: TaxYearService(db).filing_summary(year),
        )
        return Response(
            content=render_tax_year_filing_summary_html(summary),
            media_type="text/html; charset=utf-8",
        )

    @app.get("/api/v1/tax-years/{year}/filing-summary")
    def tax_year_filing_summary(year: int) -> ApiResponse[TaxYearFilingSummary]:
        return ApiResponse(
            data=cached_response(
                f"tax-years:filing-summary:{year}",
                60,
                lambda: TaxYearService(db).filing_summary(year),
            )
        )

    @app.get("/api/v1/tax-years/{year}/filing-summary.html")
    def tax_year_filing_summary_html(year: int) -> Response:
        summary = cached_response(
            f"tax-years:filing-summary:{year}",
            60,
            lambda: TaxYearService(db).filing_summary(year),
        )
        return Response(
            content=render_tax_year_filing_summary_html(summary),
            media_type="text/html; charset=utf-8",
        )

    def render_tax_year_evidence_html(report: TaxYearEvidenceReport) -> str:
        rows = "\n".join(
            f"""
            <tr>
              <td>{html_escape(item.category)}</td>
              <td>{html_escape(item.label)}</td>
              <td><span class="pill">{html_escape(item.file_format.upper())}</span></td>
              <td>{item.record_count}</td>
              <td class="amount">{html_eur(item.amount_eur)}</td>
              <td>{html_escape(item.status)}</td>
              <td>{html_escape(item.note)}</td>
              <td><a class="button small" href="{html_escape(item.endpoint)}">Quelle oeffnen</a></td>
            </tr>
            """
            for item in report.items
        )
        return f"""<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Steuerjahr {report.year} Belegkarte</title>
    <style>
      :root {{
        color: #17201b;
        background: #f6f8f4;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }}
      body {{ margin: 0; }}
      main {{ display: grid; gap: 16px; margin: 0 auto; max-width: 1180px; padding: 28px; }}
      .hero, .panel {{
        background: #ffffff;
        border: 1px solid #d8d6cf;
        border-radius: 8px;
        box-shadow: 0 1px 2px rgba(30, 40, 34, 0.06);
      }}
      .hero {{ display: grid; gap: 12px; padding: 24px; }}
      .panel {{ display: grid; gap: 12px; padding: 18px; }}
      .kicker {{ color: #5d685f; font-size: 12px; font-weight: 800; text-transform: uppercase; }}
      h1, h2 {{ margin: 0; }}
      h1 {{ font-size: 34px; line-height: 1.1; }}
      p {{ color: #4d5a52; line-height: 1.45; margin: 0; }}
      .actions {{ display: flex; flex-wrap: wrap; gap: 10px; }}
      a.button {{
        align-items: center;
        background: #26372f;
        border-radius: 6px;
        color: #ffffff;
        display: inline-flex;
        font-weight: 700;
        min-height: 38px;
        padding: 8px 12px;
        text-decoration: none;
      }}
      a.button.small {{ font-size: 12px; min-height: 30px; padding: 6px 9px; }}
      .table-wrap {{ overflow-x: auto; }}
      table {{ border-collapse: collapse; min-width: 980px; width: 100%; }}
      th, td {{ border-bottom: 1px solid #ece8e0; padding: 10px; text-align: left; vertical-align: top; }}
      th {{ color: #5d685f; font-size: 12px; text-transform: uppercase; }}
      td {{ font-size: 13px; }}
      .amount {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
      .pill {{ background: #eef4ef; border: 1px solid #cfd8cf; border-radius: 999px; padding: 4px 8px; }}
      @media (max-width: 760px) {{
        main {{ padding: 16px; }}
        h1 {{ font-size: 28px; }}
      }}
    </style>
  </head>
  <body>
    <main>
      <section class="hero">
        <span class="kicker">Steuerjahr Belegkarte</span>
        <h1>Steuerjahr {report.year}</h1>
        <p>{html_escape(report.methodology)}</p>
        <div class="actions">
          <a class="button" href="/api/v1/tax-years/{report.year}/filing-summary.html">Eingabehilfe</a>
          <a class="button" href="/api/v1/export/tax-years/{report.year}/evidence-package.zip">Jahres-Belegpaket</a>
          <a class="button" href="/api/v1/tax-years/{report.year}/evidence">JSON fuer KI/API</a>
        </div>
      </section>
      <section class="panel">
        <h2>Belege und Nachweise</h2>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>Kategorie</th><th>Beleg</th><th>Format</th><th>Datensaetze</th><th>Betrag</th><th>Status</th><th>Hinweis</th><th>Quelle</th></tr>
            </thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
      </section>
    </main>
  </body>
</html>"""

    @app.get("/api/v1/tax-years/{year}/correction-map")
    def tax_year_correction_map(year: int) -> ApiResponse[TaxYearCorrectionMap]:
        return ApiResponse(
            data=cached_response(
                f"tax-years:correction-map:{year}",
                60,
                lambda: TaxYearService(db).year_correction_map(year),
            )
        )

    def html_escape(value: object) -> str:
        return html.escape("" if value is None else str(value), quote=True)

    def html_eur(value: Decimal | None) -> str:
        if value is None:
            return "-"
        return f"{value.quantize(Decimal('0.01'))} EUR"

    def render_tax_year_filing_summary_html(summary: TaxYearFilingSummary) -> str:
        lines = "\n".join(
            f"""
            <tr>
              <td>{line.order}</td>
              <td>{html_escape(line.label)}</td>
              <td class="amount">{html_eur(line.amount_eur)}</td>
              <td>{html_escape(line.tax_treatment)}</td>
              <td>{html_escape(line.declaration_target)}</td>
              <td>{html_escape(line.note)}</td>
            </tr>
            """
            for line in summary.lines
        )
        checklist = "\n".join(
            f"""
            <tr>
              <td>{item.order}</td>
              <td><span class="pill">{html_escape(item.category)}</span></td>
              <td>{html_escape(item.label)}</td>
              <td class="amount">{html_eur(item.amount_eur)}</td>
              <td>{html_escape(item.action)}</td>
              <td>{html_escape(item.done_when)}</td>
            </tr>
            """
            for item in summary.checklist
        )
        warnings = "\n".join(
            f"<li>{html_escape(item)}</li>" for item in summary.warnings
        )
        warnings_block = (
            f"""
            <section class="panel warning">
              <h2>Hinweise</h2>
              <ul>{warnings}</ul>
            </section>
            """
            if summary.warnings
            else ""
        )
        return f"""<!doctype html>
<html lang="de">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Steuerjahr {summary.year} Eingabehilfe</title>
    <style>
      :root {{
        color: #17201b;
        background: #f6f8f4;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }}
      body {{ margin: 0; }}
      main {{ display: grid; gap: 16px; margin: 0 auto; max-width: 1180px; padding: 28px; }}
      .hero, .panel {{
        background: #ffffff;
        border: 1px solid #d8d6cf;
        border-radius: 8px;
        box-shadow: 0 1px 2px rgba(30, 40, 34, 0.06);
      }}
      .hero {{ display: grid; gap: 14px; padding: 24px; }}
      .kicker {{ color: #5d685f; font-size: 12px; font-weight: 800; text-transform: uppercase; }}
      h1, h2 {{ margin: 0; }}
      h1 {{ font-size: 34px; line-height: 1.1; }}
      h2 {{ font-size: 19px; }}
      p {{ color: #4d5a52; line-height: 1.45; margin: 0; }}
      .metrics {{ display: grid; gap: 10px; grid-template-columns: repeat(4, minmax(0, 1fr)); }}
      .metric {{
        background: #f9faf8;
        border: 1px solid #e2dfd6;
        border-radius: 8px;
        display: grid;
        gap: 5px;
        padding: 12px;
      }}
      .metric span {{ color: #5d685f; font-size: 12px; font-weight: 700; }}
      .metric strong {{ font-size: 18px; overflow-wrap: anywhere; }}
      .actions {{ display: flex; flex-wrap: wrap; gap: 10px; }}
      a.button {{
        align-items: center;
        background: #26372f;
        border-radius: 6px;
        color: #ffffff;
        display: inline-flex;
        font-weight: 700;
        min-height: 38px;
        padding: 8px 12px;
        text-decoration: none;
      }}
      .panel {{ display: grid; gap: 12px; padding: 18px; }}
      .panel.warning {{ border-color: #e2c56c; }}
      .table-wrap {{ overflow-x: auto; }}
      table {{ border-collapse: collapse; min-width: 900px; width: 100%; }}
      th, td {{ border-bottom: 1px solid #ece8e0; padding: 10px; text-align: left; vertical-align: top; }}
      th {{ color: #5d685f; font-size: 12px; text-transform: uppercase; }}
      td {{ font-size: 13px; }}
      .amount {{ font-variant-numeric: tabular-nums; white-space: nowrap; }}
      .pill {{ background: #eef4ef; border: 1px solid #cfd8cf; border-radius: 999px; padding: 4px 8px; }}
      pre {{
        background: #17201b;
        border-radius: 8px;
        color: #f7f8f5;
        overflow-x: auto;
        padding: 14px;
        white-space: pre;
      }}
      @media (max-width: 760px) {{
        main {{ padding: 16px; }}
        .metrics {{ grid-template-columns: 1fr; }}
        h1 {{ font-size: 28px; }}
      }}
    </style>
  </head>
  <body>
    <main>
      <section class="hero">
        <span class="kicker">Steuererklaerung Eingabehilfe</span>
        <h1>Steuerjahr {summary.year}</h1>
        <p>{html_escape(summary.plain_language_summary)}</p>
        <div class="metrics">
          <div class="metric"><span>Anlage SO G/V</span><strong>{html_eur(summary.taxable_private_disposals_eur)}</strong></div>
          <div class="metric"><span>Rewards / Mining / Staking</span><strong>{html_eur(summary.rewards_mining_staking_income_eur)}</strong></div>
          <div class="metric"><span>Derivate</span><strong>{html_eur(summary.derivative_pnl_eur)}</strong></div>
          <div class="metric"><span>Steuerfrei archivieren</span><strong>{html_eur(summary.tax_free_private_disposals_eur)}</strong></div>
        </div>
        <div class="actions">
          <a class="button" href="/api/v1/export/tax-years/{summary.year}/filing-checklist.csv">Checkliste CSV</a>
          <a class="button" href="/api/v1/export/tax-years/{summary.year}/evidence-package.zip">Jahres-Belegpaket</a>
          <a class="button" href="/api/v1/tax-years/{summary.year}/declaration-guide">JSON fuer KI/API</a>
        </div>
      </section>
      {warnings_block}
      <section class="panel">
        <h2>Was muss eingetragen oder belegt werden?</h2>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>#</th><th>Bereich</th><th>Betrag</th><th>Behandlung</th><th>Ziel</th><th>Hinweis</th></tr>
            </thead>
            <tbody>{lines}</tbody>
          </table>
        </div>
      </section>
      <section class="panel">
        <h2>Finanzamt-Checkliste</h2>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>#</th><th>Kategorie</th><th>Punkt</th><th>Betrag</th><th>Aktion</th><th>Erledigt wenn</th></tr>
            </thead>
            <tbody>{checklist}</tbody>
          </table>
        </div>
      </section>
      <section class="panel">
        <h2>Kopierbare Kurzuebersicht</h2>
        <pre>{html_escape(summary.ascii_table)}</pre>
      </section>
      <section class="panel">
        <h2>Methodik</h2>
        <p>{html_escape(summary.methodology)}</p>
      </section>
    </main>
  </body>
</html>
"""

    def render_tax_year_correction_map_csv(
        year: int, *, service: TaxYearService | None = None
    ) -> str:
        correction_map = (service or TaxYearService(db)).year_correction_map(year)
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "Year",
                "Order",
                "Action_Category",
                "Topic",
                "Label",
                "Amount_EUR",
                "Risk_Level",
                "Declaration_Target",
                "Evidence_Ref",
                "Correction_Note",
            ],
        )
        writer.writeheader()
        for line in correction_map.lines:
            writer.writerow(
                {
                    "Year": year,
                    "Order": line.order,
                    "Action_Category": line.action_category,
                    "Topic": line.topic,
                    "Label": line.label,
                    "Amount_EUR": line.amount_eur.quantize(Decimal("0.01"))
                    if line.amount_eur is not None
                    else "",
                    "Risk_Level": line.risk_level,
                    "Declaration_Target": line.declaration_target,
                    "Evidence_Ref": line.evidence_ref or "",
                    "Correction_Note": line.correction_note,
                }
            )
        return output.getvalue()

    def render_tax_years_correction_map_csv(
        *, service: TaxYearService | None = None
    ) -> str:
        correction_maps = (service or TaxYearService(db)).correction_map()
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "Year",
                "Filing_Status",
                "Amendment_Review_Recommended",
                "Taxable_Private_Disposals_EUR",
                "Rewards_Mining_Staking_Income_EUR",
                "Derivative_Pnl_EUR",
                "Tax_Free_Private_Disposals_EUR",
                "Amendment_Reason",
            ],
        )
        writer.writeheader()
        for item in correction_maps.years:
            writer.writerow(
                {
                    "Year": item.year,
                    "Filing_Status": item.filing_status,
                    "Amendment_Review_Recommended": "yes"
                    if item.amendment_review_recommended
                    else "no",
                    "Taxable_Private_Disposals_EUR": item.taxable_private_disposals_eur.quantize(
                        Decimal("0.01")
                    ),
                    "Rewards_Mining_Staking_Income_EUR": item.rewards_mining_staking_income_eur.quantize(
                        Decimal("0.01")
                    ),
                    "Derivative_Pnl_EUR": item.derivative_pnl_eur.quantize(
                        Decimal("0.01")
                    ),
                    "Tax_Free_Private_Disposals_EUR": item.tax_free_private_disposals_eur.quantize(
                        Decimal("0.01")
                    ),
                    "Amendment_Reason": item.amendment_reason,
                }
            )
        return output.getvalue()

    @app.get("/api/v1/export/tax-years/correction-map.csv")
    def download_tax_years_correction_map_csv() -> Response:
        return Response(
            content=render_tax_years_correction_map_csv(),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=tax-years-correction-map.csv"
            },
        )

    @app.get("/api/v1/export/tax-years/{year}/correction-map.csv")
    def download_tax_year_correction_map_csv(year: int) -> Response:
        return Response(
            content=render_tax_year_correction_map_csv(year),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=tax-year-{year}-correction-map.csv"
            },
        )

    def render_tax_year_filing_checklist_csv(
        year: int, *, service: TaxYearService | None = None
    ) -> str:
        summary = (service or TaxYearService(db)).filing_summary(year)
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "Year",
                "Order",
                "Category",
                "Label",
                "Amount_EUR",
                "Action",
                "Done_When",
                "Evidence_Ref",
                "Source_Topic",
                "Note",
            ],
        )
        writer.writeheader()
        for item in summary.checklist:
            writer.writerow(
                {
                    "Year": year,
                    "Order": item.order,
                    "Category": item.category,
                    "Label": item.label,
                    "Amount_EUR": item.amount_eur.quantize(Decimal("0.01"))
                    if item.amount_eur is not None
                    else "",
                    "Action": item.action,
                    "Done_When": item.done_when,
                    "Evidence_Ref": item.evidence_ref or "",
                    "Source_Topic": item.source_topic,
                    "Note": item.note,
                }
            )
        return output.getvalue()

    @app.get("/api/v1/export/tax-years/{year}/filing-checklist.csv")
    def download_tax_year_filing_checklist_csv(year: int) -> Response:
        return Response(
            content=render_tax_year_filing_checklist_csv(year),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=tax-year-{year}-filing-checklist.csv"
            },
        )

    @app.get("/api/v1/tax-years/{year}/methodology")
    def tax_year_methodology(year: int) -> ApiResponse[TaxMethodologyReport]:
        return ApiResponse(
            data=cached_response(
                f"tax-years:methodology:{year}",
                60,
                lambda: TaxMethodologyService(db).report(year),
            )
        )

    @app.get("/api/v1/tax-years/{year}/compliance-status")
    def tax_year_compliance_status(year: int) -> ApiResponse[TaxYearComplianceStatus]:
        return ApiResponse(data=TaxMethodologyService(db).status(year))

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-delta")
    def tax_year_wallet_fifo_delta(year: int) -> ApiResponse[WalletFifoPreviewReport]:
        return ApiResponse(
            data=cached_response(
                f"tax-years:wallet-fifo-delta:{year}",
                60,
                lambda: WalletFifoPreviewService(db).preview(year=year),
            )
        )

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-gaps")
    def tax_year_wallet_fifo_gaps(
        year: int, limit: int = 80
    ) -> ApiResponse[WalletFifoGapDiagnosisReport]:
        return ApiResponse(
            data=WalletFifoPreviewService(db).gap_diagnosis(year=year, limit=limit)
        )

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
        decision_item = next(
            (item for item in report.decisions if item.txid == payload.txid), None
        )
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
        row = next(
            (item for item in report.rows if item.deposit_txid == payload.deposit_txid),
            None,
        )
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
        ready_statuses = {
            "exchange_outflow_txid_match_ready",
            "exchange_outflow_address_txid_ready",
        }
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
                affected_ids=[
                    payload.deposit_txid,
                    *([best.raw_object_id] if best and best.raw_object_id else []),
                ],
                payload={
                    "decision_status": payload.decision_status,
                    "year": year,
                    "source_exchange": source_exchange.lower(),
                    "target_cex": target_cex.lower(),
                    "network": network,
                    "deposit_txid": payload.deposit_txid,
                    "deposit_time": row.deposit_time.isoformat()
                    if row.deposit_time
                    else None,
                    "deposit_address": row.deposit_address,
                    "source_sender": row.source_sender,
                    "source_sender_label": row.source_sender_label,
                    "asset": row.asset,
                    "deposit_amount": str(row.amount),
                    "evidence_status": row.status,
                    "exchange_outflow_event_id": best.event_id if best else None,
                    "exchange_outflow_raw_object_id": best.raw_object_id
                    if best
                    else None,
                    "exchange_outflow_tx_id": best.withdrawal_tx_id if best else None,
                    "exchange_outflow_address": best.withdrawal_address
                    if best
                    else None,
                    "exchange_outflow_amount": str(best.quantity) if best else None,
                    "exchange_outflow_gross_amount": str(best.withdrawal_amount)
                    if best and best.withdrawal_amount is not None
                    else None,
                    "exchange_outflow_fee": str(best.withdrawal_fee)
                    if best and best.withdrawal_fee is not None
                    else None,
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
        return ApiResponse(
            data=WalletFifoPreviewService(db).provenance_priorities(
                year=year, limit=limit
            )
        )

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-provenance-closure")
    def tax_year_wallet_fifo_provenance_closure(
        year: int,
        limit: int = 50,
    ) -> ApiResponse[WalletFifoYearProvenanceClosureReport]:
        return ApiResponse(
            data=cached_response(
                f"tax-years:wallet-fifo-provenance-closure:{year}:{limit}",
                60,
                lambda: WalletFifoPreviewService(db).provenance_closure_report(
                    year=year, limit=limit
                ),
            )
        )

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
        return ApiResponse(
            data=WalletFifoPreviewService(db).solana_provenance_batch_latest(
                year=year, asset=asset
            )
        )

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-solana-program-settlement-evidence")
    def tax_year_wallet_fifo_solana_program_settlement_evidence(
        year: int,
    ) -> ApiResponse[WalletFifoSolanaProgramSettlementEvidenceReport]:
        return ApiResponse(
            data=WalletFifoPreviewService(db).solana_program_settlement_evidence_latest(
                year
            )
        )

    @app.get("/api/v1/tax-years/{year}/wallet-fifo-solana-service-swap-evidence")
    def tax_year_wallet_fifo_solana_service_swap_evidence(
        year: int,
    ) -> ApiResponse[WalletFifoSolanaServiceSwapEvidenceReport]:
        return ApiResponse(
            data=WalletFifoPreviewService(db).solana_service_swap_evidence_latest(year)
        )

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
        return ApiResponse(
            data=WalletFifoPreviewService(db).solana_sender_clusters(
                year=year, asset=asset, limit=limit
            )
        )

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
        return ApiResponse(
            data=WalletFifoPreviewService(db).withdrawal_gap_trace(
                year=year, limit=limit
            )
        )

    @app.get("/api/v1/tax-years/{year}/income-guide")
    def tax_year_income_guide(year: int) -> ApiResponse[TaxIncomeReport]:
        return ApiResponse(
            data=cached_response(
                f"tax-years:income-guide:{year}",
                60,
                lambda: TaxYearService(db).income_report(year),
            )
        )

    @app.get("/api/v1/tax-years/{year}/solana-program-income-review")
    def tax_year_solana_program_income_review(
        year: int, limit: int = 200
    ) -> ApiResponse[TaxSolanaProgramIncomeReview]:
        return ApiResponse(
            data=TaxYearService(db).solana_program_income_review(year=year, limit=limit)
        )

    @app.get("/api/v1/tax-years/{year}/helium-swap-context")
    def tax_year_helium_swap_context(
        year: int, limit: int = 200
    ) -> ApiResponse[TaxHeliumSwapContextReview]:
        return ApiResponse(
            data=TaxYearService(db).helium_swap_context_review(year=year, limit=limit)
        )

    @app.get("/api/v1/tax-years/{year}/helium-swap-evidence-review")
    def tax_year_helium_swap_evidence_review(
        year: int, limit: int = 50
    ) -> ApiResponse[TaxHeliumSwapEvidenceReview]:
        return ApiResponse(
            data=TaxYearService(db).helium_swap_evidence_review(year=year, limit=limit)
        )

    @app.get("/api/v1/tax-years/{year}/stablecoin-fifo-review")
    def tax_year_stablecoin_fifo_review(
        year: int, limit: int = 200
    ) -> ApiResponse[TaxStablecoinFifoReview]:
        return ApiResponse(
            data=TaxYearService(db).stablecoin_fifo_review(year=year, limit=limit)
        )

    @app.get("/api/v1/tax-years/{year}/stablecoin-quote-leg-review")
    def tax_year_stablecoin_quote_leg_review(
        year: int, limit: int = 200
    ) -> ApiResponse[TaxStablecoinQuoteLegReview]:
        return ApiResponse(
            data=TaxYearService(db).stablecoin_quote_leg_review(year=year, limit=limit)
        )

    @app.get("/api/v1/tax-years/{year}/solana-stablecoin-swap-context")
    def tax_year_solana_stablecoin_swap_context(
        year: int, limit: int = 200
    ) -> ApiResponse[TaxSolanaStablecoinSwapContextReview]:
        return ApiResponse(
            data=TaxYearService(db).solana_stablecoin_swap_context_review(
                year=year, limit=limit
            )
        )

    @app.get("/api/v1/tax-years/{year}/solana-stablecoin-fx-review")
    def tax_year_solana_stablecoin_fx_review(
        year: int, limit: int = 200
    ) -> ApiResponse[TaxSolanaStablecoinFxReview]:
        return ApiResponse(
            data=TaxYearService(db).solana_stablecoin_fx_review(year=year, limit=limit)
        )

    @app.get("/api/v1/tax-years/{year}/drivers")
    def tax_year_drivers(
        year: int, limit: int = 50
    ) -> ApiResponse[TaxYearDriverReport]:
        return ApiResponse(
            data=cached_response(
                f"tax-years:drivers:{year}:{limit}",
                60,
                lambda: TaxYearService(db).driver_report(year, limit=limit),
            )
        )

    @app.get("/api/v1/tax-years/{year}/gain-loss-reality-check")
    def tax_year_gain_loss_reality_check(
        year: int, limit: int = 40
    ) -> ApiResponse[TaxYearGainLossRealityCheck]:
        return ApiResponse(
            data=cached_response(
                f"tax-years:gain-loss-reality-check:{year}:{limit}",
                60,
                lambda: TaxYearService(db).gain_loss_reality_check(year, limit=limit),
            )
        )

    @app.get("/api/v1/tax-years/{year}/gain-evidence-review")
    def tax_year_gain_evidence_review(
        year: int, limit: int = 80
    ) -> ApiResponse[TaxYearGainEvidenceReview]:
        return ApiResponse(
            data=TaxYearService(db).gain_evidence_review(year, limit=limit)
        )

    @app.get("/api/v1/tax-years/{year}/gain-evidence-price-deltas")
    def tax_year_gain_evidence_price_deltas(
        year: int,
        classification: str | None = None,
        limit: int = 200,
    ) -> ApiResponse[TaxYearGainEvidencePriceDeltaDrilldown]:
        return ApiResponse(
            data=TaxYearService(db).gain_evidence_price_delta_drilldown(
                year,
                classification=classification,
                limit=limit,
            )
        )

    @app.get("/api/v1/tax-years/{year}/gain-evidence-event-deltas")
    def tax_year_gain_evidence_event_deltas(
        year: int,
        limit: int = 200,
    ) -> ApiResponse[TaxYearGainEvidenceEventDeltaReview]:
        return ApiResponse(
            data=TaxYearService(db).gain_evidence_event_delta_review(year, limit=limit)
        )

    @app.get("/api/v1/tax-years/{year}/gain-evidence-acquisition-event-deltas")
    def tax_year_gain_evidence_acquisition_event_deltas(
        year: int,
        limit: int = 200,
    ) -> ApiResponse[TaxYearGainEvidenceAcquisitionEventDeltaReview]:
        return ApiResponse(
            data=TaxYearService(db).gain_evidence_acquisition_event_delta_review(
                year, limit=limit
            )
        )

    @app.get("/api/v1/tax-years/{year}/asset-fifo-drilldown")
    def tax_year_asset_fifo_drilldown(
        year: int,
        asset: str,
        limit: int = 200,
    ) -> ApiResponse[TaxYearAssetFifoDrilldown]:
        return ApiResponse(
            data=TaxYearService(db).asset_fifo_drilldown(year, asset=asset, limit=limit)
        )

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
    def tax_year_turnover_audit(
        year: int, limit: int = 20
    ) -> ApiResponse[TaxYearTurnoverAudit]:
        return ApiResponse(
            data=cached_response(
                f"tax-years:turnover-audit:{year}:{limit}",
                60,
                lambda: TaxYearService(db).turnover_audit(year, limit=limit),
            )
        )

    @app.get("/api/v1/tax-years/{year}/evidence")
    def tax_year_evidence(year: int, accept: str | None = Header(default=None)):
        if wants_html_response(accept):
            report = cached_response(
                f"tax-years:evidence:{year}",
                60,
                lambda: TaxYearService(db).evidence_report(year),
            )
            return Response(
                content=render_tax_year_evidence_html(report),
                media_type="text/html; charset=utf-8",
            )
        return ApiResponse(
            data=cached_response(
                f"tax-years:evidence:{year}",
                60,
                lambda: TaxYearService(db).evidence_report(year),
            )
        )

    @app.get("/api/v1/tax-years/{year}/evidence.html")
    def tax_year_evidence_html(year: int) -> Response:
        report = cached_response(
            f"tax-years:evidence:{year}",
            60,
            lambda: TaxYearService(db).evidence_report(year),
        )
        return Response(
            content=render_tax_year_evidence_html(report),
            media_type="text/html; charset=utf-8",
        )

    @app.get("/api/v1/tax-years/{year}/bmf-closure-appendix")
    def tax_year_bmf_closure_appendix(
        year: int,
    ) -> ApiResponse[TaxYearBmfClosureAppendix]:
        return ApiResponse(data=TaxYearService(db).bmf_closure_appendix(year))

    @app.get("/api/v1/tax-years/{year}/external-inflows")
    def tax_year_external_inflows(
        year: int, limit: int = 200
    ) -> ApiResponse[TaxExternalInflowReport]:
        return ApiResponse(
            data=cached_response(
                f"tax-years:external-inflows:{year}:{limit}",
                60,
                lambda: TaxYearService(db).external_inflow_report(year, limit=limit),
            )
        )

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
        if not workspace_operation_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="workspace_operation_running")
        try:
            result = PipelineService(db).rebuild_all()
            clear_response_cache()
            return ApiResponse(data=result)
        finally:
            workspace_operation_lock.release()

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
        return ApiResponse(
            data=cached_response(
                "export:readiness", 60, lambda: ExportService(db).readiness()
            )
        )

    @app.get("/api/v1/reports/center")
    def report_center() -> ApiResponse[ReportCenterStatus]:
        return ApiResponse(
            data=cached_response(
                "reports:center", 60, lambda: ReportCenterService(db).center()
            )
        )

    @app.get("/api/v1/export/evidence-manifest.json")
    def download_evidence_manifest() -> Response:
        payload = ReportCenterService(db).evidence_manifest().model_dump(mode="json")
        return Response(
            content=json.dumps(payload, indent=2, ensure_ascii=False),
            media_type="application/json",
            headers={
                "Content-Disposition": "attachment; filename=evidence-manifest.json"
            },
        )

    @app.get("/api/v1/export/evidence-package-index.json")
    def download_evidence_package_index() -> Response:
        payload = (
            ReportCenterService(db).evidence_package_index().model_dump(mode="json")
        )
        return Response(
            content=json.dumps(payload, indent=2, ensure_ascii=False),
            media_type="application/json",
            headers={
                "Content-Disposition": "attachment; filename=evidence-package-index.json"
            },
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
        safe_label = (
            "".join(
                char if char.isalnum() or char in {"-", "_"} else "_"
                for char in package.label
            ).strip("_")
            or "steuerreport"
        )
        filename = f"{safe_label}-{package.file_index:03d}.pdf"
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    @app.delete("/api/v1/export/packages/{package_id}")
    def delete_export_package(
        package_id: str,
    ) -> ApiResponse[ExportPackageDeleteResult]:
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
            headers={
                "Content-Disposition": "attachment; filename=tax-payment-overview.json"
            },
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
                    "affected_ids": json.dumps(
                        decision.affected_ids, ensure_ascii=False
                    ),
                    "payload_json": json.dumps(
                        decision.payload, ensure_ascii=False, sort_keys=True
                    ),
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
                    "accounts": json.dumps(
                        accounts if isinstance(accounts, list) else [],
                        ensure_ascii=False,
                    ),
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
                    "sample_event_ids": json.dumps(
                        gap.sample_event_ids, ensure_ascii=False
                    ),
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
                    "sample_event_ids": json.dumps(
                        item.sample_event_ids, ensure_ascii=False
                    ),
                }
            )
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=price-requirements.csv"
            },
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
            headers={
                "Content-Disposition": "attachment; filename=parity-diagnostics.csv"
            },
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
                    "first_event_at": step.first_event_at.isoformat()
                    if step.first_event_at
                    else "",
                    "last_event_at": step.last_event_at.isoformat()
                    if step.last_event_at
                    else "",
                    "note": step.note,
                    "filter_source": report.filter_source or "",
                    "filter_account": report.filter_account or "",
                }
            )
        return Response(
            content=output.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition": "attachment; filename=hnt-provenance-timeline.csv"
            },
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
            headers={
                "Content-Disposition": "attachment; filename=hnt-provenance-events.csv"
            },
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
            headers={
                "Content-Disposition": "attachment; filename=binance-fiat-deposits.csv"
            },
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
                "Source_Event_ID",
                "Lot_ID",
                "Anschaffungs_Event_ID",
            ],
        )
        writer.writeheader()
        acquisition_event_by_lot_id = {
            lot.lot_id: lot.source_event_id for lot in TaxService(db).list_tax_lots()
        }
        for line in TaxService(db).list_tax_lines():
            if year is not None and reporting_tax_year(line.disposed_at) != year:
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
                    "Source_Event_ID": line.source_event_id,
                    "Lot_ID": line.lot_id,
                    "Anschaffungs_Event_ID": acquisition_event_by_lot_id.get(
                        line.lot_id, ""
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
            if year is not None and reporting_tax_year(line.event_time) != year:
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
        selected_years = (
            years if years is not None else service.summary().available_years
        )
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
                "Steuerliche_Behandlung",
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
                        "Steuerliche_Behandlung": (
                            "eintragen_reward_mining"
                            if row.classification == "reward_income_candidate"
                            else "review_only_nicht_automatisch_eintragen"
                        ),
                        "Fehlende_Bewertungen": row.missing_value_count,
                        "Quellen": ", ".join(row.sources),
                    }
                )
        return output.getvalue()

    @app.get("/api/v1/export/tax-income-guide.csv")
    def download_tax_income_guide_csv(year: int | None = None) -> Response:
        filename = (
            f"tax-income-guide-{year}.csv"
            if year is not None
            else "tax-income-guide.csv"
        )
        return Response(
            content=render_tax_income_guide_csv(
                years=[year] if year is not None else None
            ),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    def render_tax_external_inflows_csv(
        *,
        years: list[int] | None = None,
        service: TaxYearService | None = None,
    ) -> str:
        service = service or TaxYearService(db)
        selected_years = (
            years if years is not None else service.summary().available_years
        )
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
            headers={
                "Content-Disposition": "attachment; filename=tax-external-inflows.csv"
            },
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

    def helium_swap_alchemy_audit_payload() -> dict[str, object]:
        if HELIUM_SWAP_ALCHEMY_AUDIT_PATH.exists():
            try:
                payload = json.loads(
                    HELIUM_SWAP_ALCHEMY_AUDIT_PATH.read_text(encoding="utf-8")
                )
                if isinstance(payload, dict):
                    return payload
            except Exception as exc:
                return {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "status": "invalid_artifact",
                    "artifact_path": str(HELIUM_SWAP_ALCHEMY_AUDIT_PATH),
                    "error": type(exc).__name__,
                    "methodology": (
                        "Fallback fuer Helium-Swap-Alchemy-Audit: Artefakt konnte "
                        "nicht gelesen werden. Keine Steuerdaten wurden veraendert."
                    ),
                }
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "missing_artifact",
            "artifact_path": str(HELIUM_SWAP_ALCHEMY_AUDIT_PATH),
            "tx_count": 0,
            "alchemy_found_count": 0,
            "confirmed_count": 0,
            "alchemy_failed_count": 0,
            "review_status_counts": {},
            "rows": [],
            "methodology": (
                "Fallback fuer Helium-Swap-Alchemy-Audit: Noch kein lokales "
                "read-only Alchemy-Audit-Artefakt vorhanden."
            ),
        }

    def solana_tx_alchemy_audit_payload() -> dict[str, object]:
        if SOLANA_TX_ALCHEMY_AUDIT_PATH.exists():
            try:
                payload = json.loads(
                    SOLANA_TX_ALCHEMY_AUDIT_PATH.read_text(encoding="utf-8")
                )
                if isinstance(payload, dict):
                    return payload
            except Exception as exc:
                return {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "status": "invalid_artifact",
                    "artifact_path": str(SOLANA_TX_ALCHEMY_AUDIT_PATH),
                    "error": type(exc).__name__,
                    "methodology": (
                        "Fallback fuer Solana-TxID-Alchemy-Audit: Artefakt konnte "
                        "nicht gelesen werden. Keine Steuerdaten wurden veraendert."
                    ),
                }
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "missing_artifact",
            "artifact_path": str(SOLANA_TX_ALCHEMY_AUDIT_PATH),
            "tx_count": 0,
            "alchemy_found_count": 0,
            "confirmed_count": 0,
            "alchemy_failed_count": 0,
            "review_status_counts": {},
            "rows": [],
            "methodology": (
                "Fallback fuer Solana-TxID-Alchemy-Audit: Noch kein lokales "
                "read-only Alchemy-Audit-Artefakt vorhanden."
            ),
        }

    def solana_failed_tx_tax_impact_payload() -> dict[str, object]:
        if SOLANA_FAILED_TX_TAX_IMPACT_PATH.exists():
            try:
                payload = json.loads(
                    SOLANA_FAILED_TX_TAX_IMPACT_PATH.read_text(encoding="utf-8")
                )
                if isinstance(payload, dict):
                    return payload
            except Exception as exc:
                return {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "status": "invalid_artifact",
                    "artifact_path": str(SOLANA_FAILED_TX_TAX_IMPACT_PATH),
                    "error": type(exc).__name__,
                    "methodology": (
                        "Fallback fuer Solana-Failed-Tx-Steuerwirkungspruefung: Artefakt konnte "
                        "nicht gelesen werden. Keine Steuerdaten wurden veraendert."
                    ),
                }
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "missing_artifact",
            "artifact_path": str(SOLANA_FAILED_TX_TAX_IMPACT_PATH),
            "failed_tx_count": 0,
            "tax_lines_count": 0,
            "tax_lots_count": 0,
            "unmatched_disposals_count": 0,
            "tax_impact_status": "artifact_missing",
            "methodology": (
                "Fallback fuer Solana-Failed-Tx-Steuerwirkungspruefung: Noch kein lokales "
                "read-only Steuerwirkungsartefakt vorhanden."
            ),
        }

    def all_transaction_evidence_matrix_payload() -> dict[str, object]:
        if ALL_TRANSACTION_EVIDENCE_MATRIX_PATH.exists():
            try:
                payload = json.loads(
                    ALL_TRANSACTION_EVIDENCE_MATRIX_PATH.read_text(encoding="utf-8")
                )
                if isinstance(payload, dict):
                    return payload
            except Exception as exc:
                return {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "status": "invalid_artifact",
                    "artifact_path": str(ALL_TRANSACTION_EVIDENCE_MATRIX_PATH),
                    "error": type(exc).__name__,
                    "methodology": (
                        "Fallback fuer Gesamt-Transaktions-Belegmatrix: Artefakt konnte "
                        "nicht gelesen werden. Keine Steuerdaten wurden veraendert."
                    ),
                }
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "missing_artifact",
            "artifact_path": str(ALL_TRANSACTION_EVIDENCE_MATRIX_PATH),
            "tx_count": 0,
            "solana_signature_count": 0,
            "non_solana_txid_count": 0,
            "review_status_counts": {},
            "rows": [],
            "methodology": (
                "Fallback fuer Gesamt-Transaktions-Belegmatrix: Noch kein lokales "
                "read-only Matrixartefakt vorhanden."
            ),
        }

    def all_transaction_evidence_closure_payload() -> dict[str, object]:
        if ALL_TRANSACTION_EVIDENCE_CLOSURE_PATH.exists():
            try:
                payload = json.loads(
                    ALL_TRANSACTION_EVIDENCE_CLOSURE_PATH.read_text(encoding="utf-8")
                )
                if isinstance(payload, dict):
                    return payload
            except Exception as exc:
                return {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "status": "invalid_artifact",
                    "artifact_path": str(ALL_TRANSACTION_EVIDENCE_CLOSURE_PATH),
                    "error": type(exc).__name__,
                    "methodology": (
                        "Fallback fuer Gesamt-Transaktions-Abschlussreport: Artefakt konnte "
                        "nicht gelesen werden. Keine Steuerdaten wurden veraendert."
                    ),
                }
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "missing_artifact",
            "artifact_path": str(ALL_TRANSACTION_EVIDENCE_CLOSURE_PATH),
            "tx_count": 0,
            "evidence_path_assigned_count": 0,
            "needs_review_count": 0,
            "tax_impact_review_count": 0,
            "open_rows": [],
            "methodology": (
                "Fallback fuer Gesamt-Transaktions-Abschlussreport: Noch kein lokales "
                "read-only Abschlussartefakt vorhanden."
            ),
        }

    def all_transaction_open_detail_review_payload() -> dict[str, object]:
        if ALL_TRANSACTION_OPEN_DETAIL_REVIEW_PATH.exists():
            try:
                payload = json.loads(
                    ALL_TRANSACTION_OPEN_DETAIL_REVIEW_PATH.read_text(encoding="utf-8")
                )
                if isinstance(payload, dict):
                    return payload
            except Exception as exc:
                return {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "status": "invalid_artifact",
                    "artifact_path": str(ALL_TRANSACTION_OPEN_DETAIL_REVIEW_PATH),
                    "error": type(exc).__name__,
                    "methodology": (
                        "Fallback fuer offenen Transaktions-Detailreview: Artefakt konnte "
                        "nicht gelesen werden. Keine Steuerdaten wurden veraendert."
                    ),
                }
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "missing_artifact",
            "artifact_path": str(ALL_TRANSACTION_OPEN_DETAIL_REVIEW_PATH),
            "open_tx_count": 0,
            "tax_impact_open_count": 0,
            "classification_counts": {},
            "rows": [],
            "methodology": (
                "Fallback fuer offenen Transaktions-Detailreview: Noch kein lokales "
                "read-only Detailartefakt vorhanden."
            ),
        }

    def all_transaction_decision_candidates_payload() -> dict[str, object]:
        if ALL_TRANSACTION_DECISION_CANDIDATES_PATH.exists():
            try:
                payload = json.loads(
                    ALL_TRANSACTION_DECISION_CANDIDATES_PATH.read_text(encoding="utf-8")
                )
                if isinstance(payload, dict):
                    return payload
            except Exception as exc:
                return {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                    "status": "invalid_artifact",
                    "artifact_path": str(ALL_TRANSACTION_DECISION_CANDIDATES_PATH),
                    "error": type(exc).__name__,
                    "methodology": (
                        "Fallback fuer Transaktions-Entscheidungskandidaten: Artefakt konnte "
                        "nicht gelesen werden. Keine Steuerdaten wurden veraendert."
                    ),
                }
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "missing_artifact",
            "artifact_path": str(ALL_TRANSACTION_DECISION_CANDIDATES_PATH),
            "open_tx_count": 0,
            "manual_decision_safe_count": 0,
            "tax_review_required_count": 0,
            "candidate_status_counts": {},
            "rows": [],
            "methodology": (
                "Fallback fuer Transaktions-Entscheidungskandidaten: Noch kein lokales "
                "read-only Kandidatenartefakt vorhanden."
            ),
        }

    @app.get("/api/v1/export/solana-tx-alchemy-audit.json")
    def download_solana_tx_alchemy_audit_json() -> Response:
        return Response(
            content=json.dumps(
                solana_tx_alchemy_audit_payload(), indent=2, ensure_ascii=False
            ),
            media_type="application/json",
            headers={
                "Content-Disposition": "attachment; filename=solana-tx-alchemy-audit.json"
            },
        )

    @app.get("/api/v1/export/solana-failed-tx-tax-impact.json")
    def download_solana_failed_tx_tax_impact_json() -> Response:
        return Response(
            content=json.dumps(
                solana_failed_tx_tax_impact_payload(), indent=2, ensure_ascii=False
            ),
            media_type="application/json",
            headers={
                "Content-Disposition": "attachment; filename=solana-failed-tx-tax-impact.json"
            },
        )

    @app.get("/api/v1/export/all-transaction-evidence-matrix.json")
    def download_all_transaction_evidence_matrix_json() -> Response:
        return Response(
            content=json.dumps(
                all_transaction_evidence_matrix_payload(), indent=2, ensure_ascii=False
            ),
            media_type="application/json",
            headers={
                "Content-Disposition": "attachment; filename=all-transaction-evidence-matrix.json"
            },
        )

    @app.get("/api/v1/export/all-transaction-evidence-closure.json")
    def download_all_transaction_evidence_closure_json() -> Response:
        return Response(
            content=json.dumps(
                all_transaction_evidence_closure_payload(), indent=2, ensure_ascii=False
            ),
            media_type="application/json",
            headers={
                "Content-Disposition": "attachment; filename=all-transaction-evidence-closure.json"
            },
        )

    @app.get("/api/v1/export/all-transaction-open-detail-review.json")
    def download_all_transaction_open_detail_review_json() -> Response:
        return Response(
            content=json.dumps(
                all_transaction_open_detail_review_payload(),
                indent=2,
                ensure_ascii=False,
            ),
            media_type="application/json",
            headers={
                "Content-Disposition": "attachment; filename=all-transaction-open-detail-review.json"
            },
        )

    @app.get("/api/v1/export/all-transaction-decision-candidates.json")
    def download_all_transaction_decision_candidates_json() -> Response:
        return Response(
            content=json.dumps(
                all_transaction_decision_candidates_payload(),
                indent=2,
                ensure_ascii=False,
            ),
            media_type="application/json",
            headers={
                "Content-Disposition": "attachment; filename=all-transaction-decision-candidates.json"
            },
        )

    def helium_swap_alchemy_audit_summary(
        year: int | None = None, limit: int = 20
    ) -> dict[str, object]:
        payload = helium_swap_alchemy_audit_payload()
        rows = payload.get("rows") if isinstance(payload.get("rows"), list) else []
        filtered_rows = [
            row
            for row in rows
            if isinstance(row, dict)
            and (year is None or int(row.get("year") or 0) == year)
        ]
        limited_rows = filtered_rows[: max(0, limit)]
        review_counts: dict[str, int] = {}
        alchemy_counts: dict[str, int] = {}
        for row in filtered_rows:
            review_status = str(row.get("review_status") or "unknown")
            alchemy_status = str(row.get("alchemy_status") or "unknown")
            review_counts[review_status] = review_counts.get(review_status, 0) + 1
            alchemy_counts[alchemy_status] = alchemy_counts.get(alchemy_status, 0) + 1
        return {
            "generated_at": payload.get("generated_at"),
            "year": year,
            "provider": payload.get("provider", "alchemy"),
            "rpc_url": payload.get("rpc_url"),
            "tx_count": len(filtered_rows),
            "alchemy_found_count": sum(
                1
                for row in filtered_rows
                if row.get("alchemy_status") == "alchemy_found"
            ),
            "confirmed_count": sum(
                1
                for row in filtered_rows
                if row.get("review_status") == "alchemy_confirmed"
            ),
            "alchemy_failed_count": sum(
                1
                for row in filtered_rows
                if str(row.get("alchemy_status") or "")
                in {"alchemy_failed", "alchemy_not_found", "alchemy_http_error"}
            ),
            "review_status_counts": review_counts,
            "alchemy_status_counts": alchemy_counts,
            "rows": limited_rows,
            "methodology": payload.get("methodology"),
        }

    @app.get("/api/v1/tax-years/helium-swap-alchemy-audit")
    def tax_years_helium_swap_alchemy_audit(
        limit: int = 20,
    ) -> ApiResponse[dict[str, object]]:
        return ApiResponse(data=helium_swap_alchemy_audit_summary(limit=limit))

    @app.get("/api/v1/tax-years/{year}/helium-swap-alchemy-audit")
    def tax_year_helium_swap_alchemy_audit(
        year: int, limit: int = 20
    ) -> ApiResponse[dict[str, object]]:
        return ApiResponse(
            data=helium_swap_alchemy_audit_summary(year=year, limit=limit)
        )

    @app.get("/api/v1/export/tax-helium-swap-alchemy-audit.json")
    def download_tax_helium_swap_alchemy_audit_json() -> Response:
        return Response(
            content=json.dumps(
                helium_swap_alchemy_audit_payload(), indent=2, ensure_ascii=False
            ),
            media_type="application/json",
            headers={
                "Content-Disposition": "attachment; filename=tax-helium-swap-alchemy-audit.json"
            },
        )

    def render_tax_solana_stablecoin_swap_evidence_csv(
        *,
        years: list[int] | None = None,
        service: TaxYearService | None = None,
        limit: int = 10_000,
    ) -> str:
        service = service or TaxYearService(db)
        selected_years = (
            years if years is not None else service.summary().available_years
        )
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
            swap_report = service.solana_stablecoin_swap_context_review(
                year=selected_year, limit=limit
            )
            fx_by_event_id = {
                row.event_id: row
                for row in service.solana_stablecoin_fx_review(
                    year=selected_year, limit=limit
                ).rows
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
                            for filename in (
                                evidence_filename(item) for item in row.raw_filenames
                            )
                            if filename
                        ),
                        "Jupiter_Asset_Status": row.jupiter_asset_status,
                        "Jupiter_Quote_Status": row.jupiter_quote_status,
                        "Preis_EUR": fx_row.selected_price_eur if fx_row else None,
                        "Preisquelle": fx_row.selected_price_source if fx_row else None,
                        "Preiszeit_UTC": fx_row.selected_priced_at if fx_row else None,
                        "Preisalter_Tage": fx_row.price_age_days if fx_row else None,
                        "Preis_Delta_Prozent": fx_row.price_delta_pct
                        if fx_row
                        else None,
                        "FX_Basis_Status": fx_row.fx_basis_status if fx_row else None,
                        "Review_Grund": row.review_reason,
                        "FX_Review_Grund": fx_row.review_reason if fx_row else None,
                        "Empfehlung": row.recommended_action,
                    }
                )
        return output.getvalue()

    @app.get("/api/v1/export/tax-solana-stablecoin-swap-evidence.csv")
    def download_tax_solana_stablecoin_swap_evidence_csv(
        year: int | None = None,
    ) -> Response:
        filename = (
            f"tax-year-{year}-solana-stablecoin-swap-evidence.csv"
            if year is not None
            else "tax-solana-stablecoin-swap-evidence.csv"
        )
        return Response(
            content=render_tax_solana_stablecoin_swap_evidence_csv(
                years=[year] if year is not None else None
            ),
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
        selected_years = (
            years if years is not None else service.summary().available_years
        )
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
                for row in service.solana_stablecoin_swap_context_review(
                    year=selected_year, limit=limit
                ).rows
            }
            fifo_report = service.stablecoin_fifo_review(
                year=selected_year, limit=limit
            )
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
                        "Disposal_Datei": evidence_filename(
                            row.disposal_batch_filename
                        ),
                        "Disposal_Zeile": row.disposal_row_number,
                        "Acquisition_Event_ID": row.acquisition_event_id,
                        "Acquisition_Quelle": row.acquisition_source,
                        "Acquisition_Event_Typ": row.acquisition_event_type,
                        "Acquisition_TX_ID": row.acquisition_tx_id,
                        "Acquisition_Konto": row.acquisition_account,
                        "Acquisition_Datei": evidence_filename(
                            row.acquisition_batch_filename
                        ),
                        "Acquisition_Zeile": row.acquisition_row_number,
                        "Acquisition_Evidence_Status": row.acquisition_evidence_status,
                        "Acquisition_Klassifizierung": row.acquisition_classification,
                        "Review_Grund": row.review_reason,
                    }
                )
        return output.getvalue()

    @app.get("/api/v1/export/tax-solana-stablecoin-swap-fifo-lines.csv")
    def download_tax_solana_stablecoin_swap_fifo_lines_csv(
        year: int | None = None,
    ) -> Response:
        filename = (
            f"tax-year-{year}-solana-stablecoin-swap-fifo-lines.csv"
            if year is not None
            else "tax-solana-stablecoin-swap-fifo-lines.csv"
        )
        return Response(
            content=render_tax_solana_stablecoin_swap_fifo_lines_csv(
                years=[year] if year is not None else None
            ),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    def render_tax_helium_swap_context_csv(
        *,
        years: list[int] | None = None,
        service: TaxYearService | None = None,
        limit: int = 100_000,
    ) -> str:
        service = service or TaxYearService(db)
        selected_years = (
            years if years is not None else service.summary().available_years
        )
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "Jahr",
                "Zeit_UTC",
                "Event_ID",
                "TX_ID",
                "Konto",
                "Quelle",
                "Asset",
                "Menge",
                "Kontextwert_EUR",
                "TX_Assets",
                "TX_Events",
                "TX_Positive_Events",
                "TX_Negative_Events",
                "Klassifizierung",
                "Steuerliche_Behandlung",
                "Review_Grund",
                "FIFO_Drilldown",
            ],
        )
        writer.writeheader()
        for selected_year in selected_years:
            report = service.helium_swap_context_review(year=selected_year, limit=limit)
            for row in report.rows:
                writer.writerow(
                    {
                        "Jahr": row.year,
                        "Zeit_UTC": row.event_time,
                        "Event_ID": row.event_id,
                        "TX_ID": row.tx_id,
                        "Konto": row.account,
                        "Quelle": row.source,
                        "Asset": row.asset,
                        "Menge": row.quantity,
                        "Kontextwert_EUR": row.value_eur,
                        "TX_Assets": row.tx_assets,
                        "TX_Events": row.tx_total_count,
                        "TX_Positive_Events": row.tx_positive_count,
                        "TX_Negative_Events": row.tx_negative_count,
                        "Klassifizierung": row.classification,
                        "Steuerliche_Behandlung": row.tax_treatment,
                        "Review_Grund": row.review_reason,
                        "FIFO_Drilldown": row.fifo_drilldown_endpoint,
                    }
                )
        return output.getvalue()

    @app.get("/api/v1/export/tax-helium-swap-context.csv")
    def download_tax_helium_swap_context_csv(year: int | None = None) -> Response:
        filename = (
            f"tax-year-{year}-helium-swap-context.csv"
            if year is not None
            else "tax-helium-swap-context.csv"
        )
        return Response(
            content=render_tax_helium_swap_context_csv(
                years=[year] if year is not None else None
            ),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )

    def render_tax_helium_swap_evidence_review_csv(
        *,
        years: list[int] | None = None,
        service: TaxYearService | None = None,
        limit: int = 100_000,
    ) -> str:
        service = service or TaxYearService(db)
        selected_years = (
            years if years is not None else service.summary().available_years
        )
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "Jahr",
                "Erste_Zeit_UTC",
                "TX_ID",
                "Konto",
                "Assets",
                "Events",
                "Positive_Events",
                "Negative_Events",
                "Kontextwert_EUR",
                "Max_Eventwert_EUR",
                "Raw_Belege",
                "Raw_Dateien",
                "Raw_Quellen",
                "Belegstatus",
                "Steuerliche_Behandlung",
                "Review_Grund",
                "Kontext_Endpoint",
                "FIFO_Drilldown",
            ],
        )
        writer.writeheader()
        for selected_year in selected_years:
            report = service.helium_swap_evidence_review(
                year=selected_year, limit=limit
            )
            for row in report.rows:
                writer.writerow(
                    {
                        "Jahr": row.year,
                        "Erste_Zeit_UTC": row.first_event_time,
                        "TX_ID": row.tx_id,
                        "Konto": row.account,
                        "Assets": row.assets,
                        "Events": row.events_count,
                        "Positive_Events": row.positive_events_count,
                        "Negative_Events": row.negative_events_count,
                        "Kontextwert_EUR": row.context_value_eur,
                        "Max_Eventwert_EUR": row.max_event_value_eur,
                        "Raw_Belege": row.raw_evidence_count,
                        "Raw_Dateien": " | ".join(
                            evidence_filename(item) for item in row.raw_filenames
                        ),
                        "Raw_Quellen": " | ".join(row.raw_sources),
                        "Belegstatus": row.evidence_status,
                        "Steuerliche_Behandlung": row.tax_treatment,
                        "Review_Grund": row.review_reason,
                        "Kontext_Endpoint": row.context_endpoint,
                        "FIFO_Drilldown": row.fifo_drilldown_endpoint,
                    }
                )
        return output.getvalue()

    @app.get("/api/v1/export/tax-helium-swap-evidence-review.csv")
    def download_tax_helium_swap_evidence_review_csv(
        year: int | None = None,
    ) -> Response:
        filename = (
            f"tax-year-{year}-helium-swap-evidence-review.csv"
            if year is not None
            else "tax-helium-swap-evidence-review.csv"
        )
        return Response(
            content=render_tax_helium_swap_evidence_review_csv(
                years=[year] if year is not None else None
            ),
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
                    json.dumps(
                        AuditService(db).export().model_dump(mode="json"),
                        indent=2,
                        ensure_ascii=False,
                    ).encode("utf-8"),
                )
            if file_id == "elster-prep":
                return (
                    "elster-prep.json",
                    json.dumps(
                        AuditService(db).elster_prep().model_dump(mode="json"),
                        indent=2,
                        ensure_ascii=False,
                    ).encode("utf-8"),
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
                        SolscanPreflightService()
                        .evidence_trace()
                        .model_dump(mode="json"),
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
            if file_id == "tax-helium-swap-alchemy-audit":
                return (
                    "tax-helium-swap-alchemy-audit.json",
                    json.dumps(
                        helium_swap_alchemy_audit_payload(),
                        indent=2,
                        ensure_ascii=False,
                    ).encode("utf-8"),
                )
            if file_id == "solana-tx-alchemy-audit":
                return (
                    "solana-tx-alchemy-audit.json",
                    json.dumps(
                        solana_tx_alchemy_audit_payload(),
                        indent=2,
                        ensure_ascii=False,
                    ).encode("utf-8"),
                )
            if file_id == "solana-failed-tx-tax-impact":
                return (
                    "solana-failed-tx-tax-impact.json",
                    json.dumps(
                        solana_failed_tx_tax_impact_payload(),
                        indent=2,
                        ensure_ascii=False,
                    ).encode("utf-8"),
                )
            if file_id == "all-transaction-evidence-matrix":
                return (
                    "all-transaction-evidence-matrix.json",
                    json.dumps(
                        all_transaction_evidence_matrix_payload(),
                        indent=2,
                        ensure_ascii=False,
                    ).encode("utf-8"),
                )
            if file_id == "all-transaction-evidence-closure":
                return (
                    "all-transaction-evidence-closure.json",
                    json.dumps(
                        all_transaction_evidence_closure_payload(),
                        indent=2,
                        ensure_ascii=False,
                    ).encode("utf-8"),
                )
            if file_id == "all-transaction-open-detail-review":
                return (
                    "all-transaction-open-detail-review.json",
                    json.dumps(
                        all_transaction_open_detail_review_payload(),
                        indent=2,
                        ensure_ascii=False,
                    ).encode("utf-8"),
                )
            if file_id == "all-transaction-decision-candidates":
                return (
                    "all-transaction-decision-candidates.json",
                    json.dumps(
                        all_transaction_decision_candidates_payload(),
                        indent=2,
                        ensure_ascii=False,
                    ).encode("utf-8"),
                )
            csv_responses = {
                "review-decisions": (
                    "review-decisions.csv",
                    download_review_decisions_csv,
                ),
                "token-risk-documentation": (
                    "token-risk-documentation.csv",
                    download_token_risk_documentation_csv,
                ),
                "price-gaps": ("price-gaps.csv", download_price_gaps_csv),
                "price-requirements": (
                    "price-requirements.csv",
                    download_price_requirements_csv,
                ),
                "parity-diagnostics": (
                    "parity-diagnostics.csv",
                    download_parity_diagnostics_csv,
                ),
                "hnt-provenance-timeline": (
                    "hnt-provenance-timeline.csv",
                    download_hnt_provenance_timeline_csv,
                ),
                "hnt-provenance-events": (
                    "hnt-provenance-events.csv",
                    download_hnt_provenance_events_csv,
                ),
                "binance-fiat-deposits": (
                    "binance-fiat-deposits.csv",
                    download_binance_fiat_deposits_csv,
                ),
                "tax-lines": ("tax-lines.csv", download_tax_lines_csv),
                "derivative-lines": (
                    "derivative-lines.csv",
                    download_derivative_lines_csv,
                ),
                "tax-income-guide": (
                    "tax-income-guide.csv",
                    download_tax_income_guide_csv,
                ),
                "tax-external-inflows": (
                    "tax-external-inflows.csv",
                    download_tax_external_inflows_csv,
                ),
                "tax-solana-stablecoin-swap-evidence": (
                    "tax-solana-stablecoin-swap-evidence.csv",
                    download_tax_solana_stablecoin_swap_evidence_csv,
                ),
                "tax-solana-stablecoin-swap-fifo-lines": (
                    "tax-solana-stablecoin-swap-fifo-lines.csv",
                    download_tax_solana_stablecoin_swap_fifo_lines_csv,
                ),
                "tax-helium-swap-context": (
                    "tax-helium-swap-context.csv",
                    download_tax_helium_swap_context_csv,
                ),
                "tax-helium-swap-evidence-review": (
                    "tax-helium-swap-evidence-review.csv",
                    download_tax_helium_swap_evidence_review_csv,
                ),
            }
            if file_id == "hnt-fairspot-timeline":
                return (
                    "hnt-fairspot-timeline.csv",
                    response_body(
                        download_hnt_provenance_timeline_csv(
                            account=ReportCenterService.FAIRSPOT_STAKING_WALLET
                        )
                    ),
                )
            if file_id == "hnt-fairspot-events":
                return (
                    "hnt-fairspot-events.csv",
                    response_body(
                        download_hnt_provenance_events_csv(
                            account=ReportCenterService.FAIRSPOT_STAKING_WALLET
                        )
                    ),
                )
            csv_entry = csv_responses.get(file_id)
            if csv_entry is None:
                return None
            filename, factory = csv_entry
            return filename, response_body(factory())

        with zipfile.ZipFile(
            buffer, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as package:
            manifest_content = json.dumps(
                manifest.model_dump(mode="json"), indent=2, ensure_ascii=False
            ).encode("utf-8")
            indexed_files_by_id = {
                entry.file_id: entry for entry in package_index.files
            }
            manifest_index_entry = indexed_files_by_id.get("evidence-manifest")
            if manifest_index_entry is not None:
                manifest_index_entry.size_bytes = len(manifest_content)
                manifest_index_entry.sha256 = hashlib.sha256(
                    manifest_content
                ).hexdigest()
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
                indexed = next(
                    (
                        entry
                        for entry in package_index.files
                        if entry.file_id == file.file_id
                    ),
                    None,
                )
                if indexed is None:
                    continue
                path = indexed.path
                package.writestr(path, content)
                indexed.size_bytes = len(content)
                indexed.sha256 = hashlib.sha256(content).hexdigest()
            package.writestr(
                "00_Manifest/package-index.json",
                json.dumps(
                    package_index.model_dump(mode="json"), indent=2, ensure_ascii=False
                ).encode("utf-8"),
            )

        buffer.seek(0)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return Response(
            content=buffer.getvalue(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename=steuerreport-v2-evidence-{timestamp}.zip"
            },
        )

    @app.get("/api/v1/export/tax-years/{year}/evidence-package.zip")
    def download_tax_year_evidence_package_zip(year: int) -> Response:
        project_root = SOFTWARE_ROOT
        cache_inputs = [
            db.path,
            Path(__file__),
            project_root / "src/steuerreport_v2/contracts/tax_methodology.py",
            project_root / "src/steuerreport_v2/domain/bmf_compliance.py",
            project_root / "src/steuerreport_v2/domain/source_registry.py",
            project_root / "src/steuerreport_v2/domain/cross_cex_evidence.py",
            project_root / "src/steuerreport_v2/domain/fairspot_staking.py",
            project_root / "src/steuerreport_v2/domain/solana_staking_position.py",
            project_root / "src/steuerreport_v2/domain/service_swap_tax_mapping.py",
            project_root / "src/steuerreport_v2/domain/pionex_reconciliation.py",
            project_root / "src/steuerreport_v2/domain/tax_methodology.py",
            project_root / "src/steuerreport_v2/domain/tax_years.py",
            project_root / "src/steuerreport_v2/domain/tax_wallet_fifo.py",
            project_root / "src/steuerreport_v2/domain/tax_time.py",
            project_root / "src/steuerreport_v2/domain/valuation.py",
            project_root / "src/steuerreport_v2/domain/valuation_runs.py",
            project_root / "src/steuerreport_v2/domain/wallet_fifo_runs.py",
            private_config_path('source_registry.json'),
            private_config_path('solana_service_swap_tax_mappings.json'),
            private_config_path('pionex_hnt_reconciliation.json'),
            project_root / "configs/pionex_hnt_minimum_reconciliation_2022.csv",
            project_root / "configs/pionex_hnt_api_probe_2022.json",
            private_config_path('fairspot_hnt_staking_reconciliation.json'),
            private_config_path('solana_staking_position_reconciliations.json'),
            Path(str(configured_import_path("import_root", "") / "pionex/raw-trading-details.csv")),
            Path(str(configured_import_path("import_root", "") / "pionex/trading.csv")),
            project_root / "var/wallet_fifo_runs/latest_wallet_fifo_run.json",
            project_root
            / "var/cross_cex_transfer_evidence/latest_cross_cex_transfer_evidence.json",
            project_root
            / "var/fairspot_staking_reconciliation/latest_fairspot_staking_reconciliation.json",
            project_root
            / "var/fairspot_staking_reconciliation/latest_fairspot_staking_source.csv",
            project_root
            / "var/solana_staking_position_reconciliation/latest_solana_staking_position_reconciliation.json",
            project_root / "var/source_registry/latest_source_registry.json",
            project_root / "var/valuation_runs/latest_valuation_gate.json",
            project_root
            / "var/bmf_filing_readiness/latest_bmf_filing_readiness_2021_2025.json",
            project_root
            / "var/bmf_closure_backlog/latest_bmf_closure_backlog_2021_2025.json",
            project_root
            / "var/helium_swap_alchemy_audits/latest_all_years_helium_swap_alchemy_audit.json",
            project_root
            / f"var/solana_program_settlement_evidence/latest_{year}_SOL_program_settlement_evidence.json",
            project_root
            / f"var/solana_service_swap_evidence/latest_{year}_service_swap_evidence.json",
        ]
        cache_fingerprint = {
            "schema": "tax_year_evidence_package_v2",
            "app_version": __version__,
            "year": year,
            "inputs": [
                {
                    "path": str(path.relative_to(project_root))
                    if path.is_relative_to(project_root)
                    else str(path),
                    "exists": path.exists(),
                    "size": path.stat().st_size if path.exists() else 0,
                    "mtime_ns": path.stat().st_mtime_ns if path.exists() else 0,
                }
                for path in cache_inputs
            ],
        }
        cache_digest = hashlib.sha256(
            json.dumps(cache_fingerprint, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        ).hexdigest()
        cache_dir = db.path.parent / ".steuerreport_v2_cache/tax_year_evidence_package"
        cache_path = cache_dir / f"{year}-{cache_digest}.zip"
        try:
            cached_content = cache_path.read_bytes()
        except OSError:
            cached_content = None
        if cached_content:
            return Response(
                content=cached_content,
                media_type="application/zip",
                headers={
                    "Content-Disposition": (
                        f"attachment; filename=steuerreport-v2-tax-year-{year}-evidence.zip"
                    ),
                    "X-Steuerreport-Cache": "hit",
                },
            )

        reporting_year_start_utc, reporting_year_end_utc = reporting_year_utc_bounds(
            year
        )
        tax_year_service = TaxYearService(db)
        wallet_fifo_service = WalletFifoPreviewService(db)
        filing_summary = tax_year_service.filing_summary(year)
        correction_map = tax_year_service.year_correction_map(year)
        evidence_report = tax_year_service.evidence_report(year)
        stablecoin_fx_tax_impact = PriceQualityService(
            db
        ).stablecoin_fx_tax_impact_latest(
            asset="USDT",
            year=year,
        )
        bmf_closure_appendix = tax_year_service.bmf_closure_appendix(year)
        wallet_fifo_delta = wallet_fifo_service.preview(year=year)
        bmf_compliance_matrix = BmfComplianceMatrixService(db).matrix()
        time_precision_audit = TaxTimePolicyService(db).audit(limit=1000)
        wallet_fifo_parallel_service = WalletFifoParallelRunService(db)
        wallet_fifo_parallel_run = wallet_fifo_parallel_service.latest()
        wallet_fifo_method_delta_explanation = (
            wallet_fifo_parallel_service.method_delta_explanation(
                run_id=wallet_fifo_parallel_run.run_id,
                year=year,
                event_limit=50,
            )
            if wallet_fifo_parallel_run is not None
            else None
        )
        solana_program_settlement_evidence = (
            wallet_fifo_service.solana_program_settlement_evidence_latest(year)
        )
        solana_service_swap_evidence = (
            wallet_fifo_service.solana_service_swap_evidence_latest(year)
        )
        service_swap_tax_mappings = ServiceSwapTaxMappingService(db).report()
        pionex_hnt_reconciliation = PionexHntReconciliationService(db).report()
        cross_cex_transfer_evidence = CrossCexTransferEvidenceService(db).report()
        fairspot_staking_reconciliation = FairspotStakingReconciliationService(
            db
        ).report()
        solana_staking_position_reconciliation = (
            SolanaStakingPositionReconciliationService(db).report()
        )
        moonpay_receipts = MoonpayReceiptService(db).report(
            as_of=reporting_year_end_utc
        )
        source_registry_run = SourceRegistryService(db).latest()
        valuation_gate_run = DivorceValuationRunService(db).latest()
        cex_exchange_outflow_evidence = (
            wallet_fifo_service.cex_exchange_outflow_evidence(
                year,
                source_exchange="bitget",
                target_cex="binance",
                network="SOL",
            )
        )
        cex_exchange_outflow_anchor_feasibility = (
            wallet_fifo_service.cex_exchange_outflow_anchor_feasibility(
                year,
                source_exchange="bitget",
                target_cex="binance",
                network="SOL",
            )
        )
        if wallet_fifo_delta.unmatched_count:
            wallet_fifo_gaps = wallet_fifo_service.gap_diagnosis(year=year, limit=80)
            wallet_fifo_withdrawal_gaps = wallet_fifo_service.withdrawal_gap_trace(
                year=year
            )
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
        required_refs = {
            line.evidence_ref for line in filing_summary.lines if line.evidence_ref
        }
        required_refs.update(
            item.endpoint for item in evidence_report.items if item.required
        )
        required_refs.add(f"/api/v1/tax-years/{year}/correction-map")
        required_refs.add(f"/api/v1/export/tax-years/{year}/correction-map.csv")
        required_refs.add(f"/api/v1/export/tax-years/{year}/filing-checklist.csv")
        required_refs.add("/api/v1/export/tax-payment-overview.json")
        required_refs.add(f"/api/v1/tax-years/{year}/wallet-fifo-delta")
        required_refs.add(f"/api/v1/tax-years/{year}/wallet-fifo-gaps?limit=80")
        required_refs.add(f"/api/v1/tax-years/{year}/wallet-fifo-withdrawal-gaps")
        required_refs.add("/api/v1/tax-methodology/bmf-compliance-matrix")
        required_refs.add("/api/v1/tax-methodology/time-precision-audit")
        required_refs.add("/api/v1/tax/wallet-fifo-runs/latest")
        required_refs.add(
            f"/api/v1/tax/wallet-fifo-runs/latest/method-delta-explanation?year={year}&event_limit=50"
        )
        required_refs.add(
            f"/api/v1/tax-years/{year}/wallet-fifo-solana-program-settlement-evidence"
        )
        if any(record.year == year for record in service_swap_tax_mappings.records):
            required_refs.add("/api/v1/tax/service-swap-mappings")
        if year == 2022:
            required_refs.add("/api/v1/tax/pionex-hnt-reconciliation")
            required_refs.add("/api/v1/tax/fairspot-staking-reconciliation")
        if year == 2026:
            required_refs.add("/api/v1/tax/solana-staking-position-reconciliation")
            required_refs.add("/api/v1/tax/moonpay-receipts")
            required_refs.add("/api/v1/tax/moonpay-receipts/trade-history.csv")
        if any(record.year == year for record in cross_cex_transfer_evidence.records):
            required_refs.add("/api/v1/tax/cross-cex-transfer-evidence")
        required_refs.add("/api/v1/sources/registry/runs/latest")
        required_refs.add("/api/v1/divorce/valuation-runs/latest")
        if cex_exchange_outflow_evidence.rows_count:
            required_refs.add(
                f"/api/v1/tax-years/{year}/cex-exchange-outflow-evidence?source_exchange=bitget&target_cex=binance&network=SOL"
            )
        if cex_exchange_outflow_anchor_feasibility.decisions_count:
            required_refs.add(
                f"/api/v1/tax-years/{year}/cex-exchange-outflow-anchor-feasibility?source_exchange=bitget&target_cex=binance&network=SOL"
            )
        solana_swap_context = tax_year_service.solana_stablecoin_swap_context_review(
            year, limit=1
        )
        if solana_swap_context.events_count:
            required_refs.add("/api/v1/export/tax-solana-stablecoin-swap-evidence.csv")
        if solana_swap_context.stable_tax_lines_count:
            required_refs.add(
                "/api/v1/export/tax-solana-stablecoin-swap-fifo-lines.csv"
            )
        helium_swap_context = tax_year_service.helium_swap_context_review(year, limit=1)
        if helium_swap_context.events_count:
            required_refs.add("/api/v1/export/tax-helium-swap-context.csv")
            required_refs.add("/api/v1/export/tax-helium-swap-evidence-review.csv")
            required_refs.add("/api/v1/export/tax-helium-swap-alchemy-audit.json")
        buffer = io.BytesIO()

        def response_body(response: Response) -> bytes:
            return bytes(response.body or b"")

        def render_tax_year_canonical_events_csv() -> bytes:
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(
                [
                    "Event_ID",
                    "Zeitpunkt_UTC",
                    "Quelle",
                    "Source_Ref",
                    "Event_Typ",
                    "Asset",
                    "Menge",
                    "Quote_Asset",
                    "Quote_Menge",
                    "Fee_Asset",
                    "Fee_Menge",
                    "TxID",
                    "Wallet",
                    "Account",
                    "Confidence",
                    "Raw_Object_ID",
                    "Export_Klassifizierung",
                    "Steuerwirkung_Hinweis",
                ]
            )
            with db.connect() as con:
                rows = con.execute(
                    f"""
                    select
                        e.event_id,
                        e.event_time::varchar,
                        e.source,
                        coalesce(e.source_ref, ''),
                        e.event_type,
                        e.asset,
                        e.quantity::varchar,
                        coalesce(e.quote_asset, ''),
                        coalesce(e.quote_quantity::varchar, ''),
                        coalesce(e.fee_asset, ''),
                        coalesce(e.fee_quantity::varchar, ''),
                        coalesce(e.tx_id, ''),
                        coalesce(e.wallet, ''),
                        coalesce(e.account, ''),
                        e.confidence::varchar,
                        coalesce(e.raw_object_id, ''),
                        case
                            when lower(e.event_type) = 'unknown'
                             and e.quantity = 0
                             and e.source = 'binance'
                             and lower(coalesce(json_extract_string(r.payload_json, '$.Operation'), '')) in (
                                'transaction fee',
                                'transaction sold',
                                'transaction spend'
                             )
                                then 'binance_merged_trade_component_no_own_tax_line'
                            when lower(e.event_type) = 'unknown'
                             and e.quantity = 0
                             and e.source = 'binance_withdrawal_api'
                                then 'binance_withdrawal_evidence_anchor_no_own_tax_line'
                            when lower(e.event_type) = 'unknown'
                                then 'unknown_requires_review'
                            else 'tax_or_ledger_event'
                        end as export_classification,
                        case
                            when lower(e.event_type) = 'unknown'
                             and e.quantity = 0
                             and e.source = 'binance'
                             and lower(coalesce(json_extract_string(r.payload_json, '$.Operation'), '')) in (
                                'transaction fee',
                                'transaction sold',
                                'transaction spend'
                             )
                                then 'Rohkomponente eines Binance-Trades; in zusammengefuehrter Trade-Zeile beruecksichtigt, keine eigene Tax-Line.'
                            when lower(e.event_type) = 'unknown'
                             and e.quantity = 0
                             and e.source = 'binance_withdrawal_api'
                                then 'Binance-Withdrawal-Beleganker; dient dem Transfernachweis, keine eigene FIFO-Veräusserung.'
                            when lower(e.event_type) = 'unknown'
                                then 'Review noetig: nicht als steuerneutral oder steuerfrei behaupten.'
                            else ''
                        end as tax_effect_note
                    from canonical_events e
                    left join raw_objects r on r.raw_object_id = e.raw_object_id
                    where {event_reporting_year_sql("e", "r")} = ?
                    order by e.event_time, e.event_id
                    """,
                    [year],
                ).fetchall()
            writer.writerows(rows)
            return output.getvalue().encode("utf-8")

        def render_tax_year_unknown_event_review_csv() -> bytes:
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(
                [
                    "Event_ID",
                    "Zeitpunkt_UTC",
                    "Quelle",
                    "Account",
                    "Asset",
                    "Menge",
                    "Raw_Operation",
                    "Raw_Change",
                    "TxID",
                    "Raw_Object_ID",
                    "Export_Klassifizierung",
                    "Steuerwirkung_Hinweis",
                ]
            )
            with db.connect() as con:
                rows = con.execute(
                    f"""
                    select
                        e.event_id,
                        e.event_time::varchar,
                        e.source,
                        coalesce(e.account, ''),
                        e.asset,
                        e.quantity::varchar,
                        coalesce(json_extract_string(r.payload_json, '$.Operation'), ''),
                        coalesce(json_extract_string(r.payload_json, '$.Change'), ''),
                        coalesce(e.tx_id, json_extract_string(r.payload_json, '$.tx_id'), ''),
                        coalesce(e.raw_object_id, ''),
                        case
                            when e.quantity = 0
                             and e.source = 'binance'
                             and lower(coalesce(json_extract_string(r.payload_json, '$.Operation'), '')) in (
                                'transaction fee',
                                'transaction sold',
                                'transaction spend'
                             )
                                then 'binance_merged_trade_component_no_own_tax_line'
                            when e.quantity = 0
                             and e.source = 'binance_withdrawal_api'
                                then 'binance_withdrawal_evidence_anchor_no_own_tax_line'
                            else 'unknown_requires_review'
                        end as export_classification,
                        case
                            when e.quantity = 0
                             and e.source = 'binance'
                             and lower(coalesce(json_extract_string(r.payload_json, '$.Operation'), '')) in (
                                'transaction fee',
                                'transaction sold',
                                'transaction spend'
                             )
                                then 'Rohkomponente eines Binance-Trades; in zusammengefuehrter Trade-Zeile beruecksichtigt, keine eigene Tax-Line.'
                            when e.quantity = 0
                             and e.source = 'binance_withdrawal_api'
                                then 'Binance-Withdrawal-Beleganker; dient dem Transfernachweis, keine eigene FIFO-Veräusserung.'
                            else 'Review noetig: nicht als steuerneutral oder steuerfrei behaupten.'
                        end as tax_effect_note
                    from canonical_events e
                    left join raw_objects r on r.raw_object_id = e.raw_object_id
                    where {event_reporting_year_sql("e", "r")} = ?
                      and lower(e.event_type) = 'unknown'
                    order by e.event_time, e.event_id
                    """,
                    [year],
                ).fetchall()
            writer.writerows(rows)
            return output.getvalue().encode("utf-8")

        def render_tax_year_reward_mining_events_csv() -> bytes:
            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(
                [
                    "Event_ID",
                    "Zeitpunkt_UTC",
                    "Quelle",
                    "Event_Typ",
                    "Asset",
                    "Menge",
                    "Quote_Asset",
                    "Quote_Menge",
                    "TxID",
                    "Wallet",
                    "Account",
                    "Raw_Object_ID",
                    "Steuerlicher_Hinweis",
                ]
            )
            with db.connect() as con:
                rows = con.execute(
                    f"""
                    select
                        e.event_id,
                        e.event_time::varchar,
                        e.source,
                        e.event_type,
                        e.asset,
                        e.quantity::varchar,
                        coalesce(e.quote_asset, ''),
                        coalesce(e.quote_quantity::varchar, ''),
                        coalesce(e.tx_id, ''),
                        coalesce(e.wallet, ''),
                        coalesce(e.account, ''),
                        coalesce(e.raw_object_id, ''),
                        case
                            when lower(e.event_type) = 'mining' then 'mining_reward_detail'
                            when lower(e.event_type) = 'reward' then 'reward_detail'
                            when lower(e.event_type) = 'staking' then 'staking_detail'
                            else 'income_detail_review'
                        end
                    from canonical_events e
                    left join raw_objects r on r.raw_object_id = e.raw_object_id
                    where {event_reporting_year_sql("e", "r")} = ?
                      and lower(e.event_type) in ('mining', 'reward', 'staking', 'income')
                    order by e.event_time, e.event_id
                    """,
                    [year],
                ).fetchall()
            writer.writerows(rows)
            return output.getvalue().encode("utf-8")

        def render_latest_governance_artifact(
            *,
            artifact: str,
            source_endpoint: str,
            report: object | None,
        ) -> bytes:
            payload = {
                "artifact": artifact,
                "package_year": year,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "available": report is not None,
                "source_endpoint": source_endpoint,
                "report": (
                    report.model_dump(mode="json")
                    if report is not None and hasattr(report, "model_dump")
                    else report
                ),
                "methodology": (
                    "Read-only Snapshot des neuesten versionierten Governance-Artefakts. "
                    "available=false bedeutet, dass fuer die verwendete Datenbank noch kein "
                    "entsprechender Lauf erzeugt wurde; es werden keine Produktivdaten veraendert."
                ),
            }
            return json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")

        def render_wallet_fifo_method_delta_events_csv() -> bytes:
            output = io.StringIO()
            fieldnames = list(WalletFifoMethodDeltaEvent.model_fields)
            writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\n")
            writer.writeheader()
            if wallet_fifo_parallel_run is None:
                return output.getvalue().encode("utf-8")
            path = wallet_fifo_parallel_service.evidence_path(
                wallet_fifo_parallel_run.run_id,
                "wallet_fifo_method_delta_events.csv.gz",
            )
            if path is None:
                return output.getvalue().encode("utf-8")
            with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    if str(row.get("year") or "") == str(year):
                        writer.writerow({key: row.get(key, "") for key in fieldnames})
            return output.getvalue().encode("utf-8")

        files: list[tuple[str, bytes, str]] = [
            (
                f"02_Steuerliche_CSVs/tax-year-{year}-filing-summary.json",
                json.dumps(
                    filing_summary.model_dump(mode="json"), indent=2, ensure_ascii=False
                ).encode("utf-8"),
                f"/api/v1/tax-years/{year}/filing-summary",
            ),
            (
                f"02_Steuerliche_CSVs/tax-year-{year}-filing-checklist.csv",
                render_tax_year_filing_checklist_csv(
                    year, service=tax_year_service
                ).encode("utf-8"),
                f"/api/v1/export/tax-years/{year}/filing-checklist.csv",
            ),
            (
                f"02_Steuerliche_CSVs/tax-year-{year}-correction-map.json",
                json.dumps(
                    correction_map.model_dump(mode="json"), indent=2, ensure_ascii=False
                ).encode("utf-8"),
                f"/api/v1/tax-years/{year}/correction-map",
            ),
            (
                f"02_Steuerliche_CSVs/tax-year-{year}-correction-map.csv",
                render_tax_year_correction_map_csv(
                    year, service=tax_year_service
                ).encode("utf-8"),
                f"/api/v1/export/tax-years/{year}/correction-map.csv",
            ),
            (
                f"02_Steuerliche_CSVs/tax-year-{year}-evidence.json",
                json.dumps(
                    evidence_report.model_dump(mode="json"),
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
                f"/api/v1/tax-years/{year}/evidence",
            ),
            (
                f"04_Preise_Paritaet/tax-year-{year}-stablecoin-fx-tax-impact.json",
                json.dumps(
                    stablecoin_fx_tax_impact.model_dump(mode="json"),
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
                f"/api/v1/prices/quality/stablecoin-fx-tax-impact-latest?asset=USDT&year={year}",
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
                    tax_year_service.payment_overview(years=[year]).model_dump(
                        mode="json"
                    ),
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
                "/api/v1/export/tax-payment-overview.json",
            ),
            (
                f"06_Solana_FIFO_Belege/tax-year-{year}-wallet-fifo-delta.json",
                json.dumps(
                    wallet_fifo_delta.model_dump(mode="json"),
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
                f"/api/v1/tax-years/{year}/wallet-fifo-delta",
            ),
            (
                f"06_Solana_FIFO_Belege/tax-year-{year}-wallet-fifo-gaps.json",
                json.dumps(
                    wallet_fifo_gaps.model_dump(mode="json")
                    if hasattr(wallet_fifo_gaps, "model_dump")
                    else wallet_fifo_gaps,
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
                f"00_Manifest/tax-year-{year}-bmf-compliance-matrix.json",
                json.dumps(
                    bmf_compliance_matrix.model_dump(mode="json"),
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
                "/api/v1/tax-methodology/bmf-compliance-matrix",
            ),
            (
                f"00_Manifest/tax-year-{year}-time-precision-audit.json",
                json.dumps(
                    time_precision_audit.model_dump(mode="json"),
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
                "/api/v1/tax-methodology/time-precision-audit",
            ),
            (
                f"06_Solana_FIFO_Belege/tax-year-{year}-latest-wallet-fifo-run.json",
                render_latest_governance_artifact(
                    artifact="wallet_fifo_parallel_run",
                    source_endpoint="/api/v1/tax/wallet-fifo-runs/latest",
                    report=wallet_fifo_parallel_run,
                ),
                "/api/v1/tax/wallet-fifo-runs/latest",
            ),
            (
                f"06_Solana_FIFO_Belege/tax-year-{year}-wallet-fifo-method-delta-explanation.json",
                render_latest_governance_artifact(
                    artifact="wallet_fifo_method_delta_explanation",
                    source_endpoint=(
                        "/api/v1/tax/wallet-fifo-runs/latest/"
                        f"method-delta-explanation?year={year}&event_limit=50"
                    ),
                    report=wallet_fifo_method_delta_explanation,
                ),
                (
                    "/api/v1/tax/wallet-fifo-runs/latest/"
                    f"method-delta-explanation?year={year}&event_limit=50"
                ),
            ),
            (
                f"06_Solana_FIFO_Belege/tax-year-{year}-wallet-fifo-method-delta-events.csv",
                render_wallet_fifo_method_delta_events_csv(),
                (
                    wallet_fifo_method_delta_explanation.full_event_csv_download_url
                    if wallet_fifo_method_delta_explanation is not None
                    else "/api/v1/tax/wallet-fifo-runs/latest"
                ),
            ),
            (
                f"06_Solana_FIFO_Belege/tax-year-{year}-solana-program-settlement-evidence.json",
                json.dumps(
                    solana_program_settlement_evidence.model_dump(mode="json"),
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
                f"/api/v1/tax-years/{year}/wallet-fifo-solana-program-settlement-evidence",
            ),
            (
                f"06_Solana_FIFO_Belege/tax-year-{year}-solana-service-swap-evidence.json",
                json.dumps(
                    solana_service_swap_evidence.model_dump(mode="json"),
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
                f"/api/v1/tax-years/{year}/wallet-fifo-solana-service-swap-evidence",
            ),
            (
                f"06_Solana_FIFO_Belege/tax-year-{year}-service-swap-tax-mapping.json",
                json.dumps(
                    {
                        **service_swap_tax_mappings.model_dump(mode="json"),
                        "records": [
                            record.model_dump(mode="json")
                            for record in service_swap_tax_mappings.records
                            if record.year == year
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
                "/api/v1/tax/service-swap-mappings",
            ),
            (
                f"00_Manifest/tax-year-{year}-latest-source-registry.json",
                render_latest_governance_artifact(
                    artifact="source_registry_run",
                    source_endpoint="/api/v1/sources/registry/runs/latest",
                    report=source_registry_run,
                ),
                "/api/v1/sources/registry/runs/latest",
            ),
            (
                f"07_Stichtag_Bewertung/tax-year-{year}-latest-valuation-gate.json",
                render_latest_governance_artifact(
                    artifact="divorce_valuation_gate",
                    source_endpoint="/api/v1/divorce/valuation-runs/latest",
                    report=valuation_gate_run,
                ),
                "/api/v1/divorce/valuation-runs/latest",
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
            (
                f"01_Transaktionen/tax-year-{year}-canonical-events.csv",
                render_tax_year_canonical_events_csv(),
                "/api/v1/events/canonical",
            ),
            (
                f"01_Transaktionen/tax-year-{year}-unknown-event-review.csv",
                render_tax_year_unknown_event_review_csv(),
                "/api/v1/events/canonical?event_type=unknown",
            ),
            (
                f"01_Transaktionen/tax-year-{year}-reward-mining-staking-events.csv",
                render_tax_year_reward_mining_events_csv(),
                "/api/v1/events/canonical?event_type=reward_mining_staking_income",
            ),
        ]
        if year == 2022:
            files.append(
                (
                    "06_Solana_FIFO_Belege/tax-year-2022-pionex-hnt-reconciliation.json",
                    json.dumps(
                        pionex_hnt_reconciliation.model_dump(mode="json"),
                        indent=2,
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    "/api/v1/tax/pionex-hnt-reconciliation",
                )
            )
            files.append(
                (
                    "05_HNT_Fairspot/tax-year-2022-fairspot-staking-reconciliation.json",
                    json.dumps(
                        fairspot_staking_reconciliation.model_dump(mode="json"),
                        indent=2,
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    "/api/v1/tax/fairspot-staking-reconciliation",
                )
            )
            fairspot_source_path = Path(
                fairspot_staking_reconciliation.independent_source_path
            )
            if fairspot_source_path.exists():
                files.append(
                    (
                        "05_HNT_Fairspot/tax-year-2022-fairspot-staking-source.csv",
                        fairspot_source_path.read_bytes(),
                        "/api/v1/tax/fairspot-staking-reconciliation",
                    )
                )
        if year == 2026:
            files.append(
                (
                    "06_Solana_FIFO_Belege/tax-year-2026-solana-staking-position-reconciliation.json",
                    json.dumps(
                        solana_staking_position_reconciliation.model_dump(mode="json"),
                        indent=2,
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    "/api/v1/tax/solana-staking-position-reconciliation",
                )
            )
            files.append(
                (
                    "06_Solana_FIFO_Belege/tax-year-2026-moonpay-onramp-reconciliation.json",
                    json.dumps(
                        moonpay_receipts.model_dump(mode="json"),
                        indent=2,
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    "/api/v1/tax/moonpay-receipts",
                )
            )
            moonpay_trade_history_path = Path(moonpay_receipts.trade_history_path)
            if (
                moonpay_receipts.trade_history_exists
                and moonpay_trade_history_path.is_file()
                and hashlib.sha256(moonpay_trade_history_path.read_bytes()).hexdigest()
                == moonpay_receipts.trade_history_sha256
            ):
                files.append(
                    (
                        "06_Solana_FIFO_Belege/MoonPay_trade-history.csv",
                        moonpay_trade_history_path.read_bytes(),
                        "/api/v1/tax/moonpay-receipts/trade-history.csv",
                    )
                )
        cross_cex_year_records = [
            record
            for record in cross_cex_transfer_evidence.records
            if record.year == year
        ]
        if cross_cex_year_records:
            cross_cex_year_payload = cross_cex_transfer_evidence.model_dump(mode="json")
            cross_cex_year_payload["records"] = [
                record.model_dump(mode="json") for record in cross_cex_year_records
            ]
            cross_cex_year_payload["records_count"] = len(cross_cex_year_records)
            cross_cex_year_payload["ready_count"] = sum(
                record.ready for record in cross_cex_year_records
            )
            cross_cex_year_payload["review_count"] = sum(
                not record.ready for record in cross_cex_year_records
            )
            cross_cex_year_payload["years"] = [year]
            files.append(
                (
                    f"06_Solana_FIFO_Belege/tax-year-{year}-cross-cex-transfer-evidence.json",
                    json.dumps(
                        cross_cex_year_payload,
                        indent=2,
                        ensure_ascii=False,
                    ).encode("utf-8"),
                    "/api/v1/tax/cross-cex-transfer-evidence",
                )
            )
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
            "/api/v1/export/tax-helium-swap-context.csv": (
                f"06_Solana_FIFO_Belege/tax-year-{year}-helium-swap-context.csv",
                lambda: render_tax_helium_swap_context_csv(
                    years=[year],
                    service=tax_year_service,
                ).encode("utf-8"),
            ),
            "/api/v1/export/tax-helium-swap-evidence-review.csv": (
                f"06_Solana_FIFO_Belege/tax-year-{year}-helium-swap-evidence-review.csv",
                lambda: render_tax_helium_swap_evidence_review_csv(
                    years=[year],
                    service=tax_year_service,
                ).encode("utf-8"),
            ),
            "/api/v1/export/tax-helium-swap-alchemy-audit.json": (
                f"06_Solana_FIFO_Belege/tax-year-{year}-helium-swap-alchemy-audit.json",
                lambda: json.dumps(
                    {
                        **helium_swap_alchemy_audit_payload(),
                        "package_year": year,
                        "package_note": (
                            "Gesamtartefakt fuer alle lokal geprueften Helium-Swap-TxIDs; "
                            "im Jahrespaket als externer Onchain-Gegenbeleg beigelegt."
                        ),
                    },
                    indent=2,
                    ensure_ascii=False,
                ).encode("utf-8"),
            ),
            "/api/v1/export/hnt-provenance-events.csv": (
                f"05_HNT_Fairspot/tax-year-{year}-hnt-provenance-events.csv",
                lambda: response_body(
                    download_hnt_provenance_events_csv(
                        from_at=reporting_year_start_utc,
                        to_at=reporting_year_end_utc,
                    )
                ),
            ),
            "/api/v1/export/hnt-provenance-timeline.csv": (
                f"05_HNT_Fairspot/tax-year-{year}-hnt-provenance-timeline.csv",
                lambda: response_body(
                    download_hnt_provenance_timeline_csv(
                        from_at=reporting_year_start_utc,
                        to_at=reporting_year_end_utc,
                    )
                ),
            ),
        }
        for endpoint, (path, factory) in csv_factories.items():
            if endpoint in required_refs:
                files.append((path, factory(), endpoint))

        for correction in AiChangeService(db).year_audits(year):
            endpoint = f"/api/v1/ai/changes/{correction.change_set_id}/audit.json"
            required_refs.add(endpoint)
            files.append((f"01_Audit/ai-change-{correction.change_set_id}.json",
                          correction.model_dump_json(indent=2).encode("utf-8"), endpoint))

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

        with zipfile.ZipFile(
            buffer, mode="w", compression=zipfile.ZIP_DEFLATED
        ) as package:
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
                    f"Transfers {wallet_fifo_delta.transfer_traces_count}\n\n"
                    "Governance-Nachweise:\n"
                    "00_Manifest: BMF-Matrix, Zeitpraezisions-Audit und Quellenregistry\n"
                    "06_Solana_FIFO_Belege: neuester versionierter Wallet-FIFO-Run\n"
                    "07_Stichtag_Bewertung: neuestes Stichtags-/Bewertungsgate\n"
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
        content = buffer.getvalue()
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            temporary_cache_path = cache_path.with_suffix(f".{uuid4().hex}.tmp")
            temporary_cache_path.write_bytes(content)
            temporary_cache_path.replace(cache_path)
        except OSError:
            pass
        return Response(
            content=content,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename=steuerreport-v2-tax-year-{year}-evidence.zip",
                "X-Steuerreport-Cache": "miss",
            },
        )

    @app.get("/api/v1/tax-filing-snapshots")
    def tax_filing_snapshots(
        year: int | None = Query(default=None, ge=2009, le=2100),
    ) -> ApiResponse[TaxFilingSnapshotList]:
        return ApiResponse(data=TaxFilingSnapshotService(db).list(year=year))

    @app.get("/api/v1/tax-years/{year}/filing-snapshots")
    def tax_year_filing_snapshots(year: int) -> ApiResponse[TaxFilingSnapshotList]:
        return ApiResponse(data=TaxFilingSnapshotService(db).list(year=year))

    @app.post("/api/v1/tax-years/{year}/filing-snapshots")
    def capture_tax_filing_snapshot(
        year: int,
        payload: TaxFilingSnapshotCaptureRequest,
    ) -> ApiResponse[TaxFilingSnapshotCaptureResult]:
        if (
            payload.state == "submitted"
            and payload.confirmation_text != SUBMISSION_CONFIRMATION_TEXT
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Eine tatsaechliche Abgabe muss mit dem vorgegebenen "
                    "Bestaetigungstext bestaetigt werden."
                ),
            )
        service = TaxFilingSnapshotService(db)
        try:
            if payload.source_snapshot_id:
                result = service.capture_from_snapshot(year=year, request=payload)
            else:
                package_response = download_tax_year_evidence_package_zip(year)
                result = service.capture_package(
                    year=year,
                    package_bytes=bytes(package_response.body or b""),
                    request=payload,
                    source_kind="current_generated_package",
                )
        except KeyError as exc:
            raise HTTPException(
                status_code=404,
                detail="Der angegebene Quell-Snapshot wurde nicht gefunden.",
            ) from exc
        except (TaxFilingSnapshotError, FileNotFoundError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        clear_response_cache()
        return ApiResponse(data=result)

    @app.post("/api/v1/tax-filing-snapshots/{snapshot_id}/usage-confirmation")
    def confirm_tax_filing_snapshot_usage(
        snapshot_id: str,
        payload: TaxFilingSnapshotUsageConfirmationRequest,
    ) -> ApiResponse[TaxFilingSnapshotUsageConfirmationResult]:
        try:
            result = TaxFilingSnapshotService(db).confirm_package_usage(
                snapshot_id=snapshot_id,
                request=payload,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Snapshot nicht gefunden.") from exc
        except TaxFilingSnapshotError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        clear_response_cache()
        return ApiResponse(data=result)

    @app.get("/api/v1/tax-years/{year}/filing-snapshot-comparison")
    def tax_filing_snapshot_comparison(
        year: int,
    ) -> ApiResponse[TaxFilingSnapshotComparison]:
        summary = cached_response(
            f"tax-years:filing-summary:{year}",
            60,
            lambda: TaxYearService(db).filing_summary(year),
        )
        return ApiResponse(
            data=TaxFilingSnapshotService(db).comparison(
                year,
                current_summary=summary,
            )
        )

    @app.get("/api/v1/tax-years/{year}/filing-audit-report")
    def tax_filing_audit_report(year: int) -> ApiResponse[TaxFilingAuditReport]:
        try:
            report = TaxFilingAuditService(db).build(year)
        except (KeyError, TaxFilingAuditError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return ApiResponse(data=report)

    @app.get("/api/v1/tax-years/{year}/filing-audit-report.json")
    def tax_filing_audit_report_json(year: int) -> Response:
        try:
            report, content = TaxFilingAuditService(db).read_artifact(year, ".json")
        except (KeyError, TaxFilingAuditError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "Content-Disposition": (
                    f"attachment; filename={report.report_id}.json"
                ),
                "X-Steuerreport-Audit-SHA256": report.report_content_sha256,
                "X-Steuerreport-Audit-Immutable": "true",
            },
        )

    @app.get("/api/v1/tax-years/{year}/filing-audit-report.md")
    def tax_filing_audit_report_markdown(year: int) -> Response:
        try:
            report, content = TaxFilingAuditService(db).read_artifact(year, ".md")
        except (KeyError, TaxFilingAuditError, ValueError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return Response(
            content=content,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f"attachment; filename={report.report_id}.md"
                ),
                "X-Steuerreport-Audit-SHA256": report.markdown_content_sha256,
                "X-Steuerreport-Audit-Immutable": "true",
            },
        )

    def format_snapshot_eur(value: Decimal) -> str:
        rendered = f"{value:,.2f}"
        return rendered.replace(",", "_").replace(".", ",").replace("_", ".")

    def render_tax_filing_snapshot_comparison_html(
        report: TaxFilingSnapshotComparison,
    ) -> str:
        tone = (
            "blocked"
            if report.integrity_blocked
            else "warning"
            if report.amendment_review_required
            or report.submission_confirmation_required
            or report.submission_timestamp_required
            else "ok"
        )
        baseline = report.baseline
        baseline_label = (
            f"Revision {baseline.revision} · "
            f"{'eingereicht' if baseline.state == 'submitted' else 'verwendetes Paket, Zeitpunkt offen' if baseline.filing_usage_confirmed else 'Referenz'} · "
            f"{html.escape(baseline.package_generated_at)}"
            if baseline
            else "Kein archivierter Abgabestand"
        )
        delta_rows = "".join(
            (
                "<tr>"
                f"<td><strong>{html.escape(item.label)}</strong><span>{html.escape(item.category)}</span></td>"
                f"<td>{format_snapshot_eur(item.filed_value_eur)} EUR</td>"
                f"<td>{format_snapshot_eur(item.current_value_eur)} EUR</td>"
                f"<td class='{('delta-up' if item.delta_eur > 0 else 'delta-down' if item.delta_eur < 0 else '')}'>"
                f"{format_snapshot_eur(item.delta_eur)} EUR</td>"
                f"<td>{html.escape(item.explanation)}</td>"
                "</tr>"
            )
            for item in report.deltas
        ) or (
            "<tr><td colspan='5'>Noch kein archivierter Vergleichsstand vorhanden.</td></tr>"
        )
        package_link = (
            f"<a class='button secondary' href='{html.escape(baseline.package_download_endpoint)}'>"
            "Archivpaket herunterladen</a>"
            if baseline
            else ""
        )
        package_hash = html.escape(baseline.package_sha256) if baseline else "-"
        integrity = html.escape(baseline.integrity_status) if baseline else "-"
        return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Steuerjahr {report.year} · Abgabestand-Vergleich</title>
  <style>
    :root {{ color-scheme: light; font-family: Inter, system-ui, sans-serif; color: #17211d; background: #f4f7f5; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; }}
    main {{ max-width: 1160px; margin: 0 auto; padding: 32px 24px 56px; }}
    header {{ display: flex; justify-content: space-between; gap: 24px; align-items: end; border-bottom: 1px solid #cdd8d2; padding-bottom: 22px; }}
    .eyebrow {{ color: #4b675b; font-size: 12px; font-weight: 750; text-transform: uppercase; }}
    h1 {{ margin: 6px 0 8px; font-size: 32px; letter-spacing: 0; }}
    p {{ line-height: 1.55; }}
    .status {{ margin: 24px 0; padding: 20px; border-left: 5px solid #2c7a57; background: #fff; }}
    .status.warning {{ border-color: #c47b17; }} .status.blocked {{ border-color: #b53c37; }}
    .status h2 {{ margin: 0 0 8px; font-size: 20px; }} .status p {{ margin: 6px 0; }}
    .facts {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 20px 0; }}
    .fact {{ border: 1px solid #d7e0db; background: #fff; padding: 14px; }}
    .fact span, td span {{ display: block; color: #63736b; font-size: 12px; margin-top: 4px; }}
    .fact code {{ display: block; overflow-wrap: anywhere; font-size: 11px; margin-top: 5px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #d7e0db; }}
    th, td {{ padding: 12px; border-bottom: 1px solid #e2e8e5; text-align: left; vertical-align: top; }}
    th {{ background: #edf3ef; color: #3d5148; font-size: 12px; text-transform: uppercase; }}
    td:nth-child(2), td:nth-child(3), td:nth-child(4) {{ white-space: nowrap; text-align: right; }}
    .delta-up {{ color: #9b3a31; font-weight: 700; }} .delta-down {{ color: #246b4c; font-weight: 700; }}
    .actions {{ display: flex; flex-wrap: wrap; gap: 10px; margin: 22px 0; }}
    .button, button {{ border: 0; background: #145c43; color: #fff; padding: 10px 14px; font: inherit; font-weight: 700; text-decoration: none; cursor: pointer; }}
    .button.secondary {{ background: #e3ece7; color: #1d4d3a; }}
    .legal {{ margin-top: 24px; color: #53635b; font-size: 13px; }}
    @media (max-width: 760px) {{ header {{ align-items: start; flex-direction: column; }} .facts {{ grid-template-columns: 1fr; }} .table-wrap {{ overflow-x: auto; }} main {{ padding: 22px 14px; }} }}
    @media print {{ body {{ background: #fff; }} main {{ max-width: none; padding: 0; }} .actions {{ display: none; }} }}
  </style>
</head>
<body>
<main>
  <header>
    <div><div class="eyebrow">Revisionssicherer Steuerreport</div><h1>Steuerjahr {report.year}</h1><p>Abgegebener bzw. archivierter Stand gegen aktuelle Berechnung.</p></div>
    <div><strong>Erzeugt</strong><br>{html.escape(report.generated_at)}</div>
  </header>
  <section class="status {tone}"><h2>{html.escape(report.headline)}</h2><p>{html.escape(report.next_action)}</p></section>
  <section class="facts">
    <div class="fact"><strong>Vergleichsbasis</strong><span>{baseline_label}</span></div>
    <div class="fact"><strong>Integritaet</strong><span>{integrity}</span><code>{package_hash}</code></div>
    <div class="fact"><strong>Korrekturpruefung</strong><span>{'erforderlich' if report.amendment_review_required else 'aktuell nicht aus diesem Vergleich abgeleitet'}</span></div>
    <div class="fact"><strong>Uebermittlungszeitpunkt</strong><span>{'noch aus ELSTER-Protokoll nachzutragen' if report.submission_timestamp_required else html.escape(baseline.submitted_at) if baseline and baseline.submitted_at else 'nicht erforderlich oder kein Stand'}</span></div>
  </section>
  <div class="actions"><button type="button" onclick="window.print()">Drucken / als PDF sichern</button>{package_link}<a class="button secondary" href="/api/v1/export/tax-years/{report.year}/filing-snapshot-comparison.csv">Delta-CSV</a></div>
  <div class="table-wrap"><table>
    <thead><tr><th>Bereich</th><th>Abgabestand</th><th>Aktuell</th><th>Delta</th><th>Einordnung</th></tr></thead>
    <tbody>{delta_rows}</tbody>
  </table></div>
  <p class="legal"><strong>Rechtlicher Hinweis:</strong> {html.escape(report.legal_notice)}</p>
  <p class="legal"><strong>Methodik:</strong> {html.escape(report.methodology)}</p>
</main>
</body>
</html>"""

    @app.get("/api/v1/tax-years/{year}/filing-snapshot-comparison.html")
    def tax_filing_snapshot_comparison_html(year: int) -> Response:
        summary = cached_response(
            f"tax-years:filing-summary:{year}",
            60,
            lambda: TaxYearService(db).filing_summary(year),
        )
        report = TaxFilingSnapshotService(db).comparison(
            year,
            current_summary=summary,
        )
        return Response(
            content=render_tax_filing_snapshot_comparison_html(report),
            media_type="text/html; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f"inline; filename=steuerjahr-{year}-abgabestand-vergleich.html"
                )
            },
        )

    @app.get("/api/v1/export/tax-years/{year}/filing-snapshot-comparison.csv")
    def tax_filing_snapshot_comparison_csv(year: int) -> Response:
        summary = cached_response(
            f"tax-years:filing-summary:{year}",
            60,
            lambda: TaxYearService(db).filing_summary(year),
        )
        report = TaxFilingSnapshotService(db).comparison(
            year,
            current_summary=summary,
        )
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(
            [
                "Year",
                "Category",
                "Key",
                "Label",
                "Filed_Value_EUR",
                "Current_Value_EUR",
                "Delta_EUR",
                "Changed_At_Cent_Precision",
                "Requires_Review",
                "Explanation",
            ]
        )
        for item in report.deltas:
            writer.writerow(
                [
                    year,
                    item.category,
                    item.key,
                    item.label,
                    item.filed_value_eur,
                    item.current_value_eur,
                    item.delta_eur,
                    item.changed_at_cent_precision,
                    item.requires_review,
                    item.explanation,
                ]
            )
        return Response(
            content=output.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": (
                    f"attachment; filename=tax-year-{year}-filing-snapshot-comparison.csv"
                )
            },
        )

    @app.get("/api/v1/tax-filing-snapshots/{snapshot_id}/package.zip")
    def download_tax_filing_snapshot_package(snapshot_id: str) -> Response:
        service = TaxFilingSnapshotService(db)
        try:
            snapshot = service.get(snapshot_id)
            content = service.read_package(snapshot_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Snapshot nicht gefunden.") from exc
        except (TaxFilingSnapshotError, FileNotFoundError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return Response(
            content=content,
            media_type="application/zip",
            headers={
                "Content-Disposition": (
                    "attachment; filename="
                    f"steuerreport-v2-{snapshot.year}-revision-{snapshot.revision}-"
                    f"{snapshot.state}.zip"
                ),
                "X-Steuerreport-SHA256": snapshot.package_sha256,
                "X-Steuerreport-Integrity": snapshot.integrity_status,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def safe_ai_validation(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/api/v1/ai/"):
            return JSONResponse(status_code=422, content={"detail": "ai_request_invalid"})
        if request.url.path.startswith(("/api/v1/activity/", "/api/v1/workspace/")):
            return JSONResponse(status_code=422, content={"detail": "workspace_request_invalid"})
        return await request_validation_exception_handler(request, exc)

    @app.exception_handler(AiProviderError)
    async def safe_ai_error(_request: Request, exc: AiProviderError):
        code = str(exc)
        status = 404 if code == "ai_task_not_found" else 409 if code in {"ai_config_revision_conflict", "ai_task_not_queued"} else 400
        return JSONResponse(status_code=status, content={"detail": code})

    @app.get("/api/v1/ai/provider")
    def ai_provider_status() -> ApiResponse[AiProviderStatus]:
        return ApiResponse(data=AiProviderService(db).status())

    @app.exception_handler(AiChangeError)
    async def safe_ai_change_error(_request: Request, exc: AiChangeError):
        code = str(exc)
        status = 404 if code == "ai_change_not_found" else 409 if code in {
            "ai_change_stale", "ai_change_context_stale", "ai_change_state_conflict",
            "ai_change_preview_required", "ai_change_prepared_mismatch",
        } else 400
        return JSONResponse(status_code=status, content={"detail": code})

    @app.exception_handler(CorrectionConflict)
    async def safe_correction_conflict(_request: Request, exc: CorrectionConflict):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(AiAgentError)
    async def safe_ai_agent_error(_request: Request, exc: AiAgentError):
        return JSONResponse(status_code=409 if str(exc) == "ai_agent_revision_conflict" else 400, content={"detail": str(exc)})

    @app.get("/api/v1/ai/agents")
    def ai_agents() -> ApiResponse[AiAgentsStatus]:
        return ApiResponse(data=AiAgentService(db).status())

    @app.put("/api/v1/ai/agents")
    def save_ai_agents(payload: AiAgentsWrite) -> ApiResponse[AiAgentsStatus]:
        return ApiResponse(data=AiAgentService(db).save(payload))

    @app.post("/api/v1/ai/data-context")
    def ai_data_context(payload: AiDataQuery) -> ApiResponse[AiDataContext]:
        return ApiResponse(data=AiChangeService(db).context(payload))

    @app.get("/api/v1/ai/changes")
    def ai_change_sets() -> ApiResponse[list[AiChangeSet]]:
        return ApiResponse(data=AiChangeService(db).list())

    @app.post("/api/v1/ai/changes")
    def create_ai_change_set(payload: AiChangeDraft) -> ApiResponse[AiChangeSet]:
        return ApiResponse(data=AiChangeService(db).create(payload))

    @app.post("/api/v1/ai/changes/generate")
    def generate_ai_change_set(payload: AiChangeGenerate) -> ApiResponse[AiChangeSet]:
        return ApiResponse(data=AiChangeService(db).generate(payload))

    @app.get("/api/v1/ai/changes/{identifier}")
    def ai_change_set(identifier: str) -> ApiResponse[AiChangeSet]:
        return ApiResponse(data=AiChangeService(db).get(identifier))

    @app.post("/api/v1/ai/changes/{identifier}/revise")
    def revise_ai_change_set(identifier: str, payload: AiChangeDraft) -> ApiResponse[AiChangeSet]:
        return ApiResponse(data=AiChangeService(db).revise(identifier, payload))

    @app.post("/api/v1/ai/changes/{identifier}/preview")
    def preview_ai_change_set(identifier: str, payload: AiChangePreview) -> ApiResponse[AiChangeSet]:
        return ApiResponse(data=AiChangeService(db).preview(identifier, payload))

    @app.post("/api/v1/ai/changes/{identifier}/apply")
    def apply_ai_change_set(identifier: str, payload: AiChangeApply) -> ApiResponse[AiChangeSet]:
        result = AiChangeService(db).apply(identifier, payload)
        clear_response_cache()
        return ApiResponse(data=result)

    @app.post("/api/v1/ai/changes/{identifier}/reject")
    def reject_ai_change_set(identifier: str) -> ApiResponse[AiChangeSet]:
        return ApiResponse(data=AiChangeService(db).reject(identifier))

    @app.post("/api/v1/ai/changes/{identifier}/revert")
    def revert_ai_change_set(identifier: str, payload: AiChangeRevert) -> ApiResponse[AiChangeSet]:
        return ApiResponse(data=AiChangeService(db).revert(identifier, payload.reason))

    @app.get("/api/v1/ai/changes/{identifier}/audit.json")
    def ai_change_audit(identifier: str) -> Response:
        item = AiChangeService(db).get(identifier)
        return Response(content=item.model_dump_json(indent=2), media_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="ai-change-audit.json"'})

    @app.put("/api/v1/ai/provider")
    def save_ai_provider(payload: AiProviderWrite) -> ApiResponse[AiProviderStatus]:
        return ApiResponse(data=AiProviderService(db).save(payload))

    @app.post("/api/v1/ai/provider/models")
    def ai_provider_models() -> ApiResponse[list[AiModel]]:
        return ApiResponse(data=AiProviderService(db).models())

    @app.post("/api/v1/ai/provider/test")
    def test_ai_provider() -> ApiResponse[AiProbeResult]:
        return ApiResponse(data=AiProviderService(db).probe())

    @app.post("/api/v1/ai/tasks/{task_id}/execute")
    def execute_ai_task(task_id: str, payload: AiTaskExecute) -> ApiResponse[AiTask]:
        return ApiResponse(data=AiProviderService(db).execute(task_id, payload))

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
    def local_ai_asset_fifo_correction_review() -> ApiResponse[
        LocalAiAssetFifoCorrectionStatus
    ]:
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
    def local_ai_wallet_fifo_provenance_review() -> ApiResponse[
        LocalAiWalletFifoProvenanceStatus
    ]:
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

    configure_openapi_routes(app)
    static_root = SOFTWARE_ROOT / "frontend/dist"
    if (static_root / "index.html").is_file():
        app.mount("/", StaticFiles(directory=static_root, html=True), name="frontend")
    return app


app = create_app()
