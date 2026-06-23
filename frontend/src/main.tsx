import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertTriangle,
  Bot,
  CalendarDays,
  Database,
  Check,
  ClipboardCheck,
  ExternalLink,
  FileDown,
  FileJson,
  GitBranch,
  LayoutDashboard,
  PackageCheck,
  ReceiptText,
  RefreshCcw,
  Scale,
  Settings,
  Trash2,
  Upload,
  WalletCards
} from "lucide-react";
import "./styles.css";

type Section =
  | "dashboard"
  | "sources"
  | "import"
  | "portfolio"
  | "stichtage"
  | "zugewinn"
  | "flows"
  | "review"
  | "parity"
  | "tax"
  | "export"
  | "admin"
  | "ai";

type ApiResponse<T> = {
  status: string;
  data: T;
  errors: Array<{ code: string; message: string }>;
  warnings: Array<{ code: string; message: string }>;
};

type ReconciliationRefreshResult = {
  fetched_at: string;
  connectors: string[];
  imported_snapshots: number;
  snapshots: Array<Record<string, unknown>>;
  connector_results?: Array<{
    connector_id: string;
    status: string;
    snapshots: number;
    previous_snapshot_at: string | null;
    message: string;
  }>;
  report: Snapshot["portfolioReconciliation"];
};

type EvidenceManifest = {
  generated_at: string;
  label: string;
  files: Array<{
    file_id: string;
    label: string;
    kind: string;
    endpoint: string;
    group: string;
    group_label: string;
    required: boolean;
    note?: string | null;
  }>;
  methodology: string;
};

type EvidencePackageIndex = {
  generated_at: string;
  label: string;
  manifest_label: string;
  files_count: number;
  groups: Array<{
    group: string;
    folder: string;
    files_count: number;
    required_count: number;
  }>;
  files: Array<{
    path: string;
    file_id: string;
    label: string;
    group: string;
    group_label: string;
    required: boolean;
    source_endpoint: string;
    size_bytes?: number | null;
    sha256?: string | null;
  }>;
  methodology: string;
};

type EvidenceHealth = {
  status: string;
  traces_count: number;
  canonical_count: number;
  legacy_ref_count: number;
  missing_decision_count: number;
  action_path: string;
  detail: string;
};

type Snapshot = {
  cockpit?: {
    generated_at: string;
    portfolio_value_eur: string;
    export_allowed: boolean;
    export_status: string;
    open_tasks: number;
    top_assets: Array<Record<string, unknown>>;
    top_sources: Array<Record<string, unknown>>;
    price_coverage: {
      priced_assets: number;
      total_assets: number;
      missing_assets: string[];
      missing_event_price_groups: number;
      status_counts: Record<string, number>;
      coverage_pct: string;
    };
    live_reconciliation: {
      status: string;
      stored_live_connectors: number;
      stored_live_assets: number;
      latest_live_snapshot_at: string | null;
      missing_wallets: string[];
      expected_zero_sources_open_value_eur: string;
      live_unverified_value_eur: string;
      blocker_count: number;
      warning_count: number;
      detail: string;
    };
    evidence_health: EvidenceHealth;
    review: {
      label: string;
      value: boolean | string | number | null;
      status: string | null;
      detail: string | null;
    };
    pipeline: {
      last_import_at: string | null;
      last_import_source: string | null;
      last_canonical_event_at: string | null;
      import_batches: number;
    };
    tasks: Array<{
      priority: "high" | "medium" | "low";
      title: string;
      detail: string;
      target: Section;
      count: number | null;
    }>;
    quick_actions: Array<{
      label: string;
      target: Section;
      action_type: string;
      enabled: boolean;
    }>;
    methodology: string;
  };
  sourcesOverview?: {
    generated_at: string;
    total_value_eur: string;
    health?: {
      status: string;
      sources_count: number;
      live_connected_sources: number;
      ledger_only_sources: number;
      stale_live_sources: number;
      warning_sources: number;
      blocker_sources: number;
      missing_live_sources: number;
      total_open_reconciliation_issues: number;
      total_open_price_issues: number;
      issues?: Array<Record<string, unknown>>;
      detail: string;
    } | null;
    sources: Array<Record<string, unknown>>;
    methodology: string;
  };
  sourceDetail?: Record<string, unknown> & {
    source_id?: string;
    label?: string;
    source_type?: string;
    value_eur?: string;
    share_pct?: string;
    current_status?: string;
    last_imported_at?: string | null;
    last_live_at?: string | null;
    ledger_value_eur?: string;
    live_value_eur?: string | null;
    delta_value_eur?: string | null;
    open_price_issues?: number;
    open_reconciliation_issues?: number;
    import_batches?: number;
    accounts?: Array<Record<string, unknown>>;
    assets?: Array<Record<string, unknown>>;
    reconciliation?: Record<string, unknown>;
    recent_events?: Array<Record<string, unknown>>;
    open_issues?: Array<Record<string, unknown>>;
    evidence_refs?: string[];
    full_accounts?: string[];
    note?: string | null;
    methodology?: string;
  };
  sourceReconciliation?: {
    generated_at: string;
    source_id: string;
    label: string;
    source_type: string;
    ledger_value_eur: string;
    live_value_eur?: string | null;
    delta_value_eur?: string | null;
    last_live_at?: string | null;
    live_anchor_source?: string | null;
    display_warning?: string | null;
    status: string;
    severity: string;
    rows: Array<Record<string, unknown>>;
    live_components: Array<Record<string, unknown>>;
    methodology: string;
  };
  sourceConnectorDiagnostics?: {
    generated_at: string;
    diagnostics: Array<Record<string, unknown>>;
    missing_credentials: number;
    stale_snapshots: number;
    missing_snapshots: number;
    methodology: string;
  };
  v1CexCredentialTakeover?: {
    generated_at: string;
    items: Array<Record<string, unknown>>;
    transferable: number;
    blocked: number;
    methodology: string;
  };
  sourceReconciliationEvidence?: {
    generated_at: string;
    source_id: string;
    since: string;
    assets: string[];
    ledger_value_eur: string;
    live_value_eur?: string | null;
    delta_value_eur?: string | null;
    last_live_at?: string | null;
    import_batches: Array<Record<string, unknown>>;
    history_requirements: Array<Record<string, unknown>>;
    asset_reports: Array<Record<string, unknown>>;
    methodology: string;
  };
  binanceEarnHistoryPreflight?: {
    generated_at: string;
    source_id: string;
    status: string;
    products: Array<Record<string, unknown>>;
    missing_products: number;
    partial_products: number;
    covered_products: number;
    connector_endpoint: string;
    methodology: string;
  };
  binanceEarnHistoryApiPreview?: {
    generated_at: string;
    source_id: string;
    credential_status: string;
    since: string;
    until: string;
    assets: string[];
    requests: Array<Record<string, unknown>>;
    records: Array<Record<string, unknown>>;
    records_returned: number;
    records_available_hint: number;
    truncated: boolean;
    methodology: string;
  };
  health?: Record<string, unknown>;
  imports?: Array<Record<string, unknown>>;
  importCoverage?: {
    root_path: string;
    files_total: number;
    files_scanned: number;
    importable: number;
    blocked: number;
    scan_truncated: boolean;
    scan_seconds: number;
    rows: Array<Record<string, unknown>>;
  };
  parserPreflight?: {
    root_path: string;
    parser_needed: number;
    inspected: number;
    files: Array<Record<string, unknown>>;
  };
  blockpitSolanaPreflight?: {
    file_path: string;
    integration: string;
    max_year: number | null;
    account: string;
    filtered_rows: number;
    skipped_unknown_assets: number;
    skipped_class_counts: Record<string, number>;
    class_counts: Record<string, number>;
    classes: Array<Record<string, unknown>>;
    combined_readiness?: {
      status: string;
      required_opening_balance: Record<string, unknown>;
      incidents: Array<Record<string, unknown>>;
      gross_positive_movements: Record<string, unknown>;
      gross_negative_movements: Record<string, unknown>;
    };
    price_source_status: Array<Record<string, unknown>>;
    historical_price_requirements: Array<Record<string, unknown>>;
    importable_classes: string[];
    blocked_classes: string[];
    target_changed: boolean;
  };
  solscanTokenPreflight?: {
    file_path: string;
    blockpit_file_path: string;
    wallet: string;
    asset: string;
    token_address: string;
    max_year: number | null;
    file_coverage: Record<string, unknown>;
    solscan: Record<string, unknown>;
    blockpit: Record<string, unknown>;
    matched_signatures: number;
    blockpit_missing_signatures: number;
    solscan_extra_signatures: number;
    matched_quantity_delta: string;
    missing_summary: Array<Record<string, unknown>>;
    missing_blockpit_signatures: Array<Record<string, unknown>>;
    coverage_checkpoints: Array<Record<string, unknown>>;
    rpc_evidence: Record<string, unknown>;
    target_changed: boolean;
  };
  walletMonthlyPreflight?: {
    file_path: string;
    wallet: string;
    asset: string;
    cutoff_at: string;
    required_quantity: string;
    rows: number;
    gateways: number;
    first_period: string | null;
    last_period: string | null;
    total_quantity: string;
    quantity_until_cutoff: string;
    covers_required_quantity: boolean;
    coverage_ratio: string;
    monthly_totals: Array<Record<string, unknown>>;
    target_changed: boolean;
  };
  portfolio?: {
    total_value_eur: string;
    missing_price_assets: string[];
    positions: Array<Record<string, unknown>>;
    asset_summary: Array<Record<string, unknown>>;
    account_summary: Array<Record<string, unknown>>;
    excluded_account_summary: Array<Record<string, unknown>>;
    excluded_value_eur: string;
    separation_virtual_wallet?: {
      label: string;
      cutoff_date: string;
      positions: Array<Record<string, unknown>>;
      total_value_eur: string;
      missing_price_assets: string[];
      methodology: string;
    } | null;
    resolved_account_aliases: Array<Record<string, unknown>>;
    unresolved_truncated_accounts: string[];
  };
  portfolioValuationAudit?: {
    generated_at: string;
    total_value_eur: string;
    previous_total_value_eur?: string | null;
    value_delta_eur?: string | null;
    rows: Array<Record<string, unknown>>;
    methodology: string;
  };
  portfolioAsOf?: {
    as_of: string;
    label: string;
    total_value_eur: string;
    missing_price_assets: string[];
    positions: Array<Record<string, unknown>>;
    asset_summary: Array<Record<string, unknown>>;
    account_summary: Array<Record<string, unknown>>;
    excluded_account_summary: Array<Record<string, unknown>>;
    excluded_value_eur: string;
    resolved_account_aliases: Array<Record<string, unknown>>;
    unresolved_truncated_accounts: string[];
    methodology: string;
    transfer_context_note?: string | null;
  };
  portfolioSources?: {
    total_value_eur: string;
    groups: Array<Record<string, unknown>>;
    accounts: Array<Record<string, unknown>>;
    methodology: string;
  };
  portfolioTokenRisk?: {
    generated_at: string;
    risk_status: string;
    min_value_eur: string;
    total_value_eur: string;
    rows_count: number;
    spam_review_count: number;
    review_count: number;
    unverified_plausible_count: number;
    verified_count: number;
    rows: Array<Record<string, unknown>>;
    methodology: string;
  };
  portfolioReconciliation?: {
    generated_at: string;
    total_ledger_value_eur: string;
    expected_zero_ledger_value_eur: string;
    live_unverified_ledger_value_eur: string;
    missing_wallets: string[];
    rows: Array<Record<string, unknown>>;
    connector_actions: string[];
    methodology: string;
  };
  separationReport?: {
    label: string;
    cutoff_date: string;
    virtual_wallet: {
      total_value_eur: string;
      positions: Array<Record<string, unknown>>;
      missing_price_assets: string[];
    };
    trend: Array<Record<string, unknown>>;
    investment_locations: Array<Record<string, unknown>>;
    unrealized_lots: Array<Record<string, unknown>>;
    price_quality: Array<Record<string, unknown>>;
    unmatched_lot_assets: string[];
    cost_basis_eur_total: string;
    current_value_eur_total: string;
    unrealized_gain_loss_eur_total: string;
    grafana_hint: string;
  };
  fiatDeposits?: {
    cutoff_date: string;
    target_source: string;
    rows: Array<Record<string, unknown>>;
    rows_count: number;
    total_receive_amount_eur: string;
    total_deposit_amount_eur?: string | null;
    total_fee_or_difference_eur?: string | null;
    methodology: string;
  };
  review?: {
    allow_export: boolean;
    issues_open: number;
    issues_open_total?: number;
    issues_current_open?: number;
    issues_historical_open?: number;
    issues_high_open: number;
    issues_medium_open: number;
    issues_low_open: number;
    blocking_issues_open: number;
    issues: Array<Record<string, unknown>>;
  };
  reviewTasks?: {
    generated_at: string;
    open_tasks: number;
    blocking_tasks: number;
    high_priority_tasks: number;
    medium_priority_tasks: number;
    low_priority_tasks: number;
    fifo_relevant_tasks: number;
    evidence_tasks: number;
    tasks: Array<Record<string, unknown>>;
    methodology: string;
  };
  reviewEvidenceTraces?: {
    generated_at: string;
    traces_count: number;
    canonical_count: number;
    legacy_ref_count: number;
    missing_decision_count: number;
    traces: Array<Record<string, unknown>>;
    methodology: string;
  };
  reviewDecisions?: Array<Record<string, unknown>>;
  reviewDecisionSuggestions?: Array<Record<string, unknown>>;
  parity?: {
    compared: number;
    matches: number;
    differences: number;
    missing_v2: number;
    max_absolute_difference: string;
    rows: Array<Record<string, unknown>>;
  };
  parityDiagnostics?: {
    compared: number;
    matches: number;
    differences: number;
    missing_v2: number;
    groups: Array<Record<string, unknown>>;
  };
  parityReleaseReadiness?: {
    release_ready: boolean;
    compared: number;
    matches: number;
    differences: number;
    missing_v2: number;
    groups_total: number;
    unresolved_groups: number;
    blocking_groups: number;
    accepted_groups: number;
    max_absolute_difference: string;
    blocking_difference_eur: string;
    blocking_groups_top: Array<Record<string, unknown>>;
  };
  parityReferences?: Array<Record<string, unknown>>;
  hntFifoProvenance?: {
    generated_at: string;
    asset: string;
    event_limit: number;
    filter_source?: string | null;
    filter_account?: string | null;
    filter_from?: string | null;
    filter_to?: string | null;
    current_portfolio_accounts: string[];
    transfer_counterparty_accounts: string[];
    current_portfolio_events: number;
    transfer_counterparty_events: number;
    fifo_relevant_events: number;
    open_lots: number;
    disposals: number;
    timeline: Array<Record<string, unknown>>;
    events: Array<Record<string, unknown>>;
    open_fifo_lots: Array<Record<string, unknown>>;
    disposal_tax_lines: Array<Record<string, unknown>>;
    methodology: string;
  };
  flows?: {
    year: number | null;
    available_years: number[];
    total_visible_value_eur: string;
    missing_price_assets: string[];
    edges: Array<Record<string, unknown>>;
  };
  divorceEqualization?: {
    generated_at: string;
    cutoff_at: string;
    valuation_at?: string | null;
    latest_event_at?: string | null;
    latest_price_at?: string | null;
    cutoff_portfolio_value_eur: string;
    valuation_portfolio_value_eur: string;
    valuation_review_value_eur: string;
    valuation_dust_value_eur: string;
    valuation_value_without_review_assets_eur: string;
    gross_portfolio_change_eur: string;
    gross_portfolio_change_without_review_assets_eur: string;
    net_external_invest_since_cutoff_eur: string;
    adjusted_gain_loss_excluding_new_invest_eur: string;
    adjusted_gain_loss_without_review_assets_eur: string;
    cutoff_missing_price_assets: string[];
    valuation_missing_price_assets: string[];
    fiat_deposits_since_cutoff_eur: string;
    direct_eur_buys_since_cutoff_eur: string;
    eur_asset_spent_without_quote_since_cutoff_eur: string;
    marital_pre_cutoff: Record<string, unknown> & { assets?: Array<Record<string, unknown>> };
    post_cutoff_direct_eur_invest: Record<string, unknown> & { assets?: Array<Record<string, unknown>> };
    post_cutoff_all_lots: Record<string, unknown> & { assets?: Array<Record<string, unknown>> };
    accounts: Array<Record<string, unknown>>;
    live_reconciliation: Array<Record<string, unknown>>;
    bmf_tax_boundary: Record<string, unknown> & { boundary_notes?: string[] };
    cash_flows: Array<Record<string, unknown>>;
    caveats: string[];
    legal_note: string;
    methodology: string;
  };
  transferCandidates?: {
    candidates_count: number;
    assets: string[];
    candidates: Array<Record<string, unknown>>;
  };
  exportReadiness?: Record<string, unknown>;
  exports?: Array<Record<string, unknown>>;
  reportEvidenceManifest?: EvidenceManifest;
  reportEvidencePackageIndex?: EvidencePackageIndex;
  reportCenter?: {
    generated_at: string;
    export_allowed: boolean;
    export_status: string;
    max_pdf_pages_per_file: number;
    packages_count: number;
    created_pdf_packages_count: number;
    blocked_pdf_packages_count: number;
    latest_package_created_at: string | null;
    years: Array<Record<string, unknown>>;
    artifacts: Array<Record<string, unknown>>;
    csv_exports: Array<Record<string, unknown>>;
    actions: Array<Record<string, unknown>>;
    quality_warnings: Array<Record<string, unknown>>;
    evidence_health?: EvidenceHealth | null;
    packages: Array<Record<string, unknown>>;
    methodology: string;
  };
  admin?: Record<string, unknown>;
  adminSettings?: Array<Record<string, unknown>>;
  jupiterTokenSearch?: {
    generated_at: string;
    query: string;
    configured: boolean;
    status: string;
    tokens: Array<Record<string, unknown>>;
    tokens_count: number;
    source_url: string;
    methodology: string;
  };
  jupiterMetadataCache?: {
    generated_at: string;
    configured: boolean;
    status: string;
    candidates_count: number;
    cached_count: number;
    uncached_count: number;
    requested_count?: number;
    refreshed_count?: number;
    skipped_count?: number;
    items: Array<Record<string, unknown>>;
    methodology: string;
  };
  jupiterRiskReview?: {
    generated_at: string;
    status: string;
    risk_status: string;
    items_count: number;
    spam_review_count: number;
    review_count: number;
    unverified_plausible_count: number;
    verified_count: number;
    items: Array<Record<string, unknown>>;
    methodology: string;
  };
  ai?: Array<Record<string, unknown>>;
  localAiYearPackageQa?: {
    status: string;
    llm_status?: string | null;
    latest_run_id?: string | null;
    latest_run_path?: string | null;
    generated_at?: string | null;
    findings_count: number;
    years: Array<Record<string, unknown>>;
    summary_md?: string | null;
    local_ai_review_md?: string | null;
    service_name: string;
    methodology: string;
  };
  taxLots?: Array<Record<string, unknown>>;
  taxLines?: Array<Record<string, unknown>>;
  taxUnmatchedDisposals?: Array<Record<string, unknown>>;
  taxSummary?: Record<string, unknown> | null;
  taxHoldingPeriods?: {
    generated_at: string;
    as_of: string;
    min_value_eur: string;
    visible_lots_count: number;
    hidden_dust_lots_count: number;
    missing_price_assets: string[];
    tax_free_now_value_eur: string;
    next_7_days_value_eur: string;
    next_30_days_value_eur: string;
    next_7_months_value_eur: string;
    next_year_value_eur: string;
    buckets: Array<Record<string, unknown>>;
    lots: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxLossRealizationPlanner?: {
    generated_at: string;
    as_of: string;
    min_loss_eur: string;
    min_value_eur: string;
    tax_relevant_loss_if_sold_now_eur: string;
    expired_loss_not_tax_relevant_eur: string;
    unrealized_gain_eur: string;
    tax_relevant_lots_count: number;
    expired_loss_lots_count: number;
    rows: Array<Record<string, unknown>>;
    caveats: string[];
    ascii_table: string;
    methodology: string;
  };
  taxYearsSummary?: {
    years: Array<Record<string, unknown>>;
    available_years: number[];
    methodology: string;
  };
  taxPaymentOverview?: {
    generated_at: string;
    rows: Array<Record<string, unknown>>;
    ascii_table: string;
    methodology: string;
  };
  taxYearFilingMatrix?: {
    generated_at: string;
    rows: Array<Record<string, unknown>>;
    ready_years: number[];
    conservative_ready_years?: number[];
    review_years: number[];
    blocked_years: number[];
    ascii_table: string;
    methodology: string;
  };
  taxFilingClosureOverview?: {
    generated_at: string;
    rows: Array<Record<string, unknown>>;
    ready_years: number[];
    conservative_ready_years?: number[];
    review_years: number[];
    blocked_years: number[];
    amendment_review_years: number[];
    total_private_disposals_gain_loss_eur: string;
    total_rewards_mining_staking_income_eur: string;
    total_derivative_pnl_eur: string;
    total_tax_free_private_disposals_eur: string;
    ascii_table: string;
    methodology: string;
  };
  taxYearsCorrectionMap?: {
    generated_at: string;
    years: Array<Record<string, unknown>>;
    amendment_review_years: number[];
    archive_only_years: number[];
    blocked_years: number[];
    ascii_table: string;
    methodology: string;
  };
  taxMethodologySummary?: {
    generated_at: string;
    years: Array<Record<string, unknown>>;
    available_years: number[];
    policy: Record<string, unknown>;
    ok_years: number;
    review_years: number;
    blocked_years: number;
    empty_years: number;
    methodology: string;
  };
  taxBmfActionPlan?: {
    generated_at: string;
    available_years: number[];
    ready_years: number[];
    review_years: number[];
    blocked_years: number[];
    empty_years: number[];
    blocking_items_count: number;
    review_items_count: number;
    info_items_count: number;
    items: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxYearMethodology?: {
    year: number;
    generated_at: string;
    status: string;
    label: string;
    bmf_ready: boolean;
    policy: Record<string, unknown>;
    metrics: Array<Record<string, unknown>>;
    gaps: Array<Record<string, unknown>>;
    tax_lines_count: number;
    income_events_count: number;
    derivative_lines_count: number;
    sources: string[];
    accounts_count: number;
    assets_count: number;
    traceability_score: string;
    methodology: string;
  };
  taxYearWalletFifoDelta?: {
    generated_at: string;
    method_version: string;
    status: string;
    pools_count: number;
    lots_count: number;
    tax_lines_count: number;
    unmatched_count: number;
    transfer_traces_count: number;
    unresolved_inbound_provenance_count: number;
    global_gain_loss_eur: string;
    wallet_gain_loss_eur: string;
    delta_gain_loss_eur: string;
    year_deltas: Array<Record<string, unknown>>;
    unmatched: Array<Record<string, unknown>>;
    transfer_traces: Array<Record<string, unknown>>;
    sample_lines: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxYearWalletFifoGaps?: {
    generated_at: string;
    year: number;
    gaps_count: number;
    affected_assets: string[];
    affected_pools: string[];
    likely_causes: Record<string, number>;
    diagnoses: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxYearWalletFifoOriginTrace?: {
    generated_at: string;
    year: number;
    traces_count: number;
    traces: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxYearCexDepositTransferEvidence?: {
    generated_at: string;
    year: number;
    cex: string;
    network?: string | null;
    deposits_count: number;
    transfer_neutral_count: number;
    evidence_ready_count: number;
    missing_evidence_count: number;
    total_credited_quantity_by_asset: Record<string, string>;
    total_carried_cost_basis_eur: string;
    deposits: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxYearCexSenderOwnershipLatest?: {
    generated_at: string;
    year: number;
    cex: string;
    network?: string | null;
    artifact_path?: string | null;
    artifact_exists: boolean;
    transactions_count: number;
    status_counts: Record<string, number>;
    tax_neutral_candidates: number;
    complex_route_review: number;
    unverified_third_party: number;
    pending_review: number;
    decisions: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxYearCexExchangeOutflowEvidence?: {
    generated_at: string;
    year: number;
    source_exchange: string;
    target_cex: string;
    network?: string | null;
    window_hours: number;
    rows_count: number;
    ready_count: number;
    missing_count: number;
    rows: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxYearCexExchangeOutflowAnchorFeasibility?: {
    generated_at: string;
    year: number;
    source_exchange: string;
    target_cex: string;
    network?: string | null;
    decisions_count: number;
    evidence_ready_count: number;
    anchor_ready_count: number;
    anchor_missing_count: number;
    items: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxYearWalletFifoProvenancePriorities?: {
    generated_at: string;
    year: number;
    unresolved_inbound_provenance_count: number;
    groups_count: number;
    groups: Array<Record<string, unknown>>;
    status_breakdown: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxYearWalletFifoProvenanceClosure?: {
    generated_at: string;
    year: number;
    unresolved_inbound_provenance_count: number;
    groups_count: number;
    documented_non_live_count: number;
    external_or_unknown_count: number;
    unverified_cex_count: number;
    tax_neutral_candidate_count: number;
    review_required_count: number;
    items: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxYearWalletFifoRawProvenanceBreakdown?: {
    generated_at: string;
    year: number;
    groups_count: number;
    raw_transaction_evidence_only_count: number;
    solana_tiny_raw_credit_count: number;
    groups: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxYearWalletFifoExchangeEvidenceGaps?: {
    generated_at: string;
    year: number;
    gaps_count: number;
    gaps: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxYearWalletFifoSolanaProvenanceClassification?: {
    generated_at: string;
    year: number;
    asset: string;
    pool_id?: string | null;
    requested_events_count: number;
    classified_count: number;
    own_transfer_candidates_count: number;
    external_or_unknown_count: number;
    failed_count: number;
    classifications: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxYearWalletFifoSolanaProvenanceBatchLatest?: {
    generated_at?: string | null;
    year: number;
    asset: string;
    pool_id?: string | null;
    provider?: string | null;
    run_id?: string | null;
    artifact_path: string;
    exists: boolean;
    total_events: number;
    classified_count: number;
    remaining_count: number;
    progress_percent: string;
    own_transfer_candidates_count: number;
    external_or_unknown_count: number;
    failed_count: number;
    batches_count: number;
    last_batch_offset?: number | null;
    last_batch_failed_count?: number | null;
    last_batch_status?: string | null;
    methodology: string;
  };
  taxYearWalletFifoSolanaRawProvenancePriorities?: {
    generated_at: string;
    year: number;
    asset: string;
    pool_id?: string | null;
    artifact_path: string;
    artifact_exists: boolean;
    events_count: number;
    priorities_count: number;
    raw_transaction_evidence_only_count: number;
    solana_tiny_raw_credit_count: number;
    total_quantity: string;
    total_cost_basis_eur: string;
    priorities: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxYearWalletFifoSolanaRawProvenanceSenders?: {
    generated_at: string;
    year: number;
    asset: string;
    pool_id?: string | null;
    senders_count: number;
    events_count: number;
    raw_transaction_evidence_only_count: number;
    solana_tiny_raw_credit_count: number;
    total_quantity: string;
    total_cost_basis_eur: string;
    senders: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxYearWalletFifoSolanaRawBmfEvidenceSummary?: {
    generated_at: string;
    year: number;
    asset: string;
    pool_id?: string | null;
    groups_count: number;
    high_priority_events_count: number;
    high_priority_cost_basis_eur: string;
    total_quantity: string;
    total_cost_basis_eur: string;
    groups: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxYearWalletFifoSolanaRawBmfEvidenceDrilldown?: {
    generated_at: string;
    year: number;
    asset: string;
    pool_id?: string | null;
    route_filter?: string | null;
    priority_filter?: string | null;
    events_count: number;
    groups_count: number;
    total_quantity: string;
    total_cost_basis_eur: string;
    signer_groups: Array<Record<string, unknown>>;
    events: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxYearWalletFifoSolanaSenderClusters?: {
    generated_at: string;
    year: number;
    asset: string;
    artifact_path: string;
    artifact_exists: boolean;
    run_id?: string | null;
    total_events: number;
    clusters_count: number;
    own_transfer_candidate_events: number;
    external_or_unknown_events: number;
    failed_events: number;
    clusters: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxYearWalletFifoSolanaSenderClusterOutflows?: {
    generated_at: string;
    year: number;
    asset: string;
    artifact_path: string;
    artifact_exists: boolean;
    sender_owner?: string | null;
    checked_events_count: number;
    events_with_candidates_count: number;
    candidates_count: number;
    window_hours: number;
    amount_tolerance_percent: string;
    samples: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxYearWalletFifoSolanaOrigin?: {
    generated_at: string;
    year: number;
    traces_count: number;
    traces: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxLegacyHeliumOverview?: {
    generated_at: string;
    asset: string;
    main_legacy_wallet: string;
    fairspot_staking_wallet: string;
    solana_migration_wallet: string;
    wallets: Array<Record<string, unknown>>;
    fairspot_transfers: Array<Record<string, unknown>>;
    fairspot_transfers_count: number;
    included_in_portfolio_count: number;
    total_canonical_events_count: number;
    total_net_hnt_quantity: string;
    methodology: string;
  };
  taxYearDetail?: Record<string, unknown> & {
    year?: number;
    state?: string;
    label?: string;
    asset_breakdown?: Array<Record<string, unknown>>;
    missing_price_assets?: string[];
    sample_unmatched_ids?: string[];
    sample_tax_line_ids?: string[];
    issues?: Array<Record<string, unknown>>;
    methodology?: string;
  };
  taxDeclarationGuide?: {
    year: number;
    generated_at: string;
    export_ready: boolean;
    realized_gain_loss_eur: string;
    taxable_disposal_proceeds_eur: string;
    acquisition_cost_eur: string;
    tax_free_gain_loss_eur: string;
    tax_free_disposal_proceeds_eur: string;
    tax_free_acquisition_cost_eur: string;
    tax_free_lines_count: number;
    rewards_income_eur: string;
    derivative_pnl_eur: string;
    hnt_gain_loss_eur: string;
    hnt_disposal_proceeds_eur: string;
    hnt_acquisition_cost_eur: string;
    hnt_tax_line_count: number;
    loss_assets: Array<Record<string, unknown>>;
    gain_assets: Array<Record<string, unknown>>;
    entries: Array<Record<string, unknown>>;
    review_decisions: Array<Record<string, unknown>>;
    caveats: string[];
    evidence_exports: string[];
    methodology: string;
  };
  taxYearFilingSummary?: {
    year: number;
    generated_at: string;
    export_ready: boolean;
    status_label: string;
    plain_language_summary: string;
    taxable_private_disposals_eur: string;
    taxable_disposal_proceeds_eur: string;
    acquisition_cost_eur: string;
    rewards_mining_staking_income_eur: string;
    derivative_pnl_eur: string;
    tax_free_private_disposals_eur: string;
    tax_free_lines_count: number;
    bmf_closure_appendix_status?: string | null;
    bmf_closure_appendix_items_count?: number;
    bmf_closure_appendix_manual_evidence_required_count?: number;
    can_file_with_conservative_appendix?: boolean;
    lines: Array<Record<string, unknown>>;
    checklist?: Array<Record<string, unknown>>;
    review_decisions: Array<Record<string, unknown>>;
    warnings: string[];
    ascii_table: string;
    checklist_ascii?: string;
    methodology: string;
  };
  taxYearCorrectionMap?: {
    year: number;
    generated_at: string;
    filing_status: string;
    amendment_review_recommended: boolean;
    amendment_reason: string;
    taxable_private_disposals_eur: string;
    rewards_mining_staking_income_eur: string;
    derivative_pnl_eur: string;
    tax_free_private_disposals_eur: string;
    lines: Array<Record<string, unknown>>;
    ascii_table: string;
    methodology: string;
  };
  taxIncomeGuide?: {
    year: number;
    generated_at: string;
    total_income_eur: string;
    reward_income_eur: string;
    generic_income_eur: string;
    events_count: number;
    valued_events_count: number;
    missing_value_count: number;
    ignored_non_positive_count: number;
    classification_counts: Record<string, number>;
    assets: Array<Record<string, unknown>>;
    missing_assets: string[];
    events: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxRewardTradingSeparation?: {
    generated_at: string;
    years: number[];
    assets: string[];
    total_reward_income_eur: string;
    total_trade_taxable_gain_loss_eur: string;
    total_trade_tax_free_gain_loss_eur: string;
    rows: Array<Record<string, unknown>>;
    ascii_table: string;
    methodology: string;
  };
  taxYearDrivers?: {
    year: number;
    generated_at: string;
    taxable_gain_loss_eur: string;
    tax_free_gain_loss_eur: string;
    top_taxable_assets: Array<Record<string, unknown>>;
    top_tax_free_assets: Array<Record<string, unknown>>;
    top_taxable_lines: Array<Record<string, unknown>>;
    top_tax_free_lines: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxYearGainLossRealityCheck?: {
    year: number;
    generated_at: string;
    taxable_gain_loss_eur: string;
    tax_free_gain_loss_eur: string;
    gross_disposal_proceeds_eur: string;
    open_current_value_eur: string;
    open_cost_basis_eur: string;
    open_unrealized_gain_loss_eur: string;
    potential_loss_not_realized_eur: string;
    rows: Array<Record<string, unknown>>;
    plain_language_summary: string;
    caveats: string[];
    ascii_table: string;
    methodology: string;
  };
  taxYearTurnoverAudit?: {
    year: number;
    generated_at: string;
    gross_disposal_proceeds_eur: string;
    taxable_gain_loss_eur: string;
    tax_free_gain_loss_eur: string;
    combined_gain_loss_eur: string;
    taxable_disposal_proceeds_eur: string;
    tax_free_disposal_proceeds_eur: string;
    stablecoin_gross_disposal_proceeds_eur: string;
    stablecoin_gain_loss_eur: string;
    tax_lines_count: number;
    tax_free_lines_count: number;
    external_inflows_review_count: number;
    external_inflows_unmatched_count: number;
    external_inflows_review_unmatched_value_eur: string;
    plain_language_summary: string;
    caveats: string[];
    top_assets_by_proceeds: Array<Record<string, unknown>>;
    top_assets_by_gain: Array<Record<string, unknown>>;
    top_sources_by_proceeds: Array<Record<string, unknown>>;
    top_taxable_lines_by_gain: Array<Record<string, unknown>>;
    top_lines_by_proceeds: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxYearsTurnoverAuditSummary?: {
    generated_at: string;
    years: Array<Record<string, unknown>>;
    high_risk_years_count: number;
    review_years_count: number;
    ok_years_count: number;
    methodology: string;
  };
  taxSolanaProgramIncomeReview?: {
    generated_at: string;
    year?: number | null;
    events_count: number;
    total_value_eur: string;
    years: Array<Record<string, unknown>>;
    assets: Array<Record<string, unknown>>;
    rows: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxStablecoinFifoReview?: {
    generated_at: string;
    year?: number | null;
    tax_line_count: number;
    disposal_proceeds_eur: string;
    acquisition_cost_eur: string;
    gain_loss_eur: string;
    taxable_gain_loss_eur: string;
    tax_free_gain_loss_eur: string;
    assets: Array<Record<string, unknown>>;
    sources: Array<Record<string, unknown>>;
    rows: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxStablecoinQuoteLegReview?: {
    generated_at: string;
    year?: number | null;
    events_count: number;
    expected_tax_line_events_count: number;
    missing_expected_tax_line_events_count: number;
    same_stable_pair_events_count: number;
    stable_to_stable_events_count: number;
    stable_tax_lines_count: number;
    stable_disposal_proceeds_eur: string;
    stable_gain_loss_eur: string;
    summaries: Array<Record<string, unknown>>;
    rows: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxSolanaStablecoinSwapContext?: {
    generated_at: string;
    year?: number | null;
    events_count: number;
    material_events_count: number;
    stable_to_stable_events_count: number;
    missing_raw_evidence_count: number;
    verified_or_known_token_events_count: number;
    stable_tax_lines_count: number;
    stable_disposal_proceeds_eur: string;
    stable_gain_loss_eur: string;
    assets: Array<Record<string, unknown>>;
    rows: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxSolanaStablecoinFxReview?: {
    generated_at: string;
    year?: number | null;
    events_count: number;
    material_events_count: number;
    missing_price_count: number;
    stale_price_count: number;
    derived_price_count: number;
    fx_backed_price_count: number;
    market_price_count: number;
    stable_disposal_proceeds_eur: string;
    stable_gain_loss_eur: string;
    assets: Array<Record<string, unknown>>;
    rows: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxYearEvidence?: {
    year: number;
    generated_at: string;
    export_ready: boolean;
    items: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxExternalInflows?: {
    year: number;
    generated_at: string;
    inflows_count: number;
    matched_count: number;
    review_count: number;
    unmatched_count: number;
    total_value_eur: string;
    matched_value_eur: string;
    review_value_eur: string;
    unmatched_value_eur: string;
    assets: string[];
    rows: Array<Record<string, unknown>>;
    methodology: string;
  };
  derivativeLines?: Array<Record<string, unknown>>;
  derivativeSummary?: Record<string, unknown> | null;
  rawObjects?: Array<Record<string, unknown>>;
  canonicalEvents?: Array<Record<string, unknown>>;
  importProfiles?: Array<Record<string, unknown>>;
  prices?: Array<Record<string, unknown>>;
  latestPrices?: Array<Record<string, unknown>>;
  priceCoverage?: {
    missing_count: number;
    missing_assets: string[];
    missing: Array<Record<string, unknown>>;
  };
  priceQuality?: {
    generated_at: string;
    price_points_count: number;
    assets_count: number;
    sources_count: number;
    low_confidence_count: number;
    proxy_count: number;
    zero_or_negative_count: number;
    tax_relevant_issue_groups: number;
    issue_groups_count: number;
    high_risk_groups: number;
    medium_risk_groups: number;
    low_risk_groups: number;
    groups: Array<Record<string, unknown>>;
    source_summaries: Array<Record<string, unknown>>;
    latest_assets: Array<Record<string, unknown>>;
    methodology: string;
  };
  priceManualReview?: {
    generated_at: string;
    manual_groups_count: number;
    tax_relevant_groups_count: number;
    total_tax_lines_count: number;
    groups: Array<Record<string, unknown>>;
    methodology: string;
  };
  priceStablecoinFxReview?: {
    generated_at: string;
    groups_count: number;
    tax_relevant_groups_count: number;
    total_tax_lines_count: number;
    assets: string[];
    groups: Array<Record<string, unknown>>;
    methodology: string;
  };
  priceSolscanSignatureReview?: {
    generated_at: string;
    groups_count: number;
    tax_relevant_groups_count: number;
    total_tax_lines_count: number;
    total_signature_refs: number;
    assets: string[];
    groups: Array<Record<string, unknown>>;
    methodology: string;
  };
  priceBinanceNormalizerReview?: {
    generated_at: string;
    groups_count: number;
    tax_relevant_groups_count: number;
    total_tax_lines_count: number;
    missing_quote_groups_count: number;
    unknown_or_zero_groups_count: number;
    missing_sample_ref_groups_count: number;
    assets: string[];
    groups: Array<Record<string, unknown>>;
    methodology: string;
  };
  priceEventQuoteEvidenceReview?: {
    generated_at: string;
    groups_count: number;
    tax_relevant_groups_count: number;
    total_tax_lines_count: number;
    stable_quote_groups_count: number;
    missing_sample_ref_groups_count: number;
    assets: string[];
    groups: Array<Record<string, unknown>>;
    methodology: string;
  };
  priceRequirements?: {
    requirements_count: number;
    missing_assets: string[];
    requirements: Array<Record<string, unknown>>;
  };
};

const navItems: Array<{
  id: Section;
  label: string;
  description: string;
  group: "workflow" | "evidence" | "expert";
  icon: React.ReactNode;
}> = [
  { id: "dashboard", label: "Start", description: "Gesamtstatus, naechster Schritt und Live-Datenstand", group: "workflow", icon: <LayoutDashboard size={18} /> },
  { id: "tax", label: "Steuerjahre", description: "Eingabehilfe, BMF-Status und Jahresbelege", group: "workflow", icon: <ReceiptText size={18} /> },
  { id: "sources", label: "Quellen & Wallets", description: "Eigene Quellen, Live-Status und Ledger-Abgleich", group: "workflow", icon: <WalletCards size={18} /> },
  { id: "portfolio", label: "Portfolio", description: "Bestand, Preisdeckung und Haltefristen", group: "workflow", icon: <WalletCards size={18} /> },
  { id: "zugewinn", label: "Zugewinn & Stichtage", description: "Stichtagswerte, Erbgeld und familienrechtliche Belege", group: "workflow", icon: <Scale size={18} /> },
  { id: "export", label: "Belege & Export", description: "Report-Center, Finanzamtspakete und CSV/ZIP/PDF", group: "evidence", icon: <FileDown size={18} /> },
  { id: "review", label: "Review", description: "Offene Fachentscheidungen und Belegspuren", group: "evidence", icon: <Database size={18} /> },
  { id: "import", label: "Import", description: "Daten einlesen, Preflights und Importabdeckung", group: "expert", icon: <Upload size={18} /> },
  { id: "flows", label: "Geldfluesse", description: "Transferkandidaten und Netto-Fluesse", group: "expert", icon: <GitBranch size={18} /> },
  { id: "stichtage", label: "Stichtage", description: "Technische Stichtagsportfolio-Ansicht", group: "expert", icon: <CalendarDays size={18} /> },
  { id: "parity", label: "V1/V2 Pruefung", description: "Paritaet, Referenzen und Diagnose", group: "expert", icon: <Scale size={18} /> },
  { id: "admin", label: "Administration", description: "Settings, Credentials und Systemstatus", group: "expert", icon: <Settings size={18} /> },
  { id: "ai", label: "Lokale KI", description: "Jahrespaket-QA und KI-Aufgaben", group: "expert", icon: <Bot size={18} /> }
];

const API_BASE = import.meta.env.VITE_API_BASE || `${window.location.protocol}//${window.location.hostname}:8010`;
const API_TIMEOUT_MS = 60_000;

type SnapshotLoader = {
  key: keyof Snapshot;
  label: string;
  load: () => Promise<unknown>;
};

type LoaderStatus = {
  key: keyof Snapshot;
  label: string;
  status: "pending" | "loading" | "ok" | "error";
  detail?: string;
  duration_ms?: number;
};

type TaxViewMode = "guided" | "details" | "expert";
type PortfolioViewMode = "overview" | "reconciliation" | "expert";
type TokenRiskFilter = "all" | "verified" | "unverified_plausible" | "spam_review";
type SourceViewMode = "overview" | "reconciliation" | "expert";
type ExportViewMode = "packages" | "evidence" | "expert";
type ReviewViewMode = "tasks" | "evidence" | "expert";
type ImportViewMode = "assistant" | "preflight" | "expert";

async function fetchApiResponse<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs = API_TIMEOUT_MS
): Promise<ApiResponse<T>> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: controller.signal
    });
    if (!response.ok) {
      throw new Error(`${path}: HTTP ${response.status}`);
    }
    const body = (await response.json()) as ApiResponse<T>;
    if (body.status === "error") {
      throw new Error(body.errors.map((error) => error.message).join(", "));
    }
    return body;
  } catch (caught) {
    if (caught instanceof DOMException && caught.name === "AbortError") {
      throw new Error(`${path}: Timeout nach ${Math.round(timeoutMs / 1000)}s`);
    }
    throw caught;
  } finally {
    window.clearTimeout(timeout);
  }
}

async function getApi<T>(path: string): Promise<T> {
  const body = await fetchApiResponse<T>(path);
  return body.data;
}

async function getRawJson<T>(path: string): Promise<T> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      signal: controller.signal
    });
    if (!response.ok) {
      throw new Error(`${path}: HTTP ${response.status}`);
    }
    return (await response.json()) as T;
  } catch (caught) {
    if (caught instanceof DOMException && caught.name === "AbortError") {
      throw new Error(`${path}: Timeout nach ${Math.round(API_TIMEOUT_MS / 1000)}s`);
    }
    throw caught;
  } finally {
    window.clearTimeout(timeout);
  }
}

async function postApi<T>(path: string, payload?: unknown, timeoutMs = API_TIMEOUT_MS): Promise<T> {
  const body = await postApiResponse<T>(path, payload, timeoutMs);
  return body.data;
}

async function postApiResponse<T>(
  path: string,
  payload?: unknown,
  timeoutMs = API_TIMEOUT_MS
): Promise<ApiResponse<T>> {
  return fetchApiResponse<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: payload === undefined ? undefined : JSON.stringify(payload)
  }, timeoutMs);
}

async function patchApi<T>(path: string, payload: unknown): Promise<T> {
  const body = await fetchApiResponse<T>(path, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return body.data;
}

function App() {
  const [active, setActive] = useState<Section>("dashboard");
  const [snapshot, setSnapshot] = useState<Snapshot>({});
  const [loading, setLoading] = useState(false);
  const [loaderStatuses, setLoaderStatuses] = useState<LoaderStatus[]>([]);
  const [sourceRefreshLoading, setSourceRefreshLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [flowYear, setFlowYear] = useState("all");
  const [asOfDate, setAsOfDate] = useState("2025-06-13");
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  const [selectedTaxYear, setSelectedTaxYear] = useState("2024");
  const [taxViewMode, setTaxViewMode] = useState<TaxViewMode>("guided");
  const [portfolioViewMode, setPortfolioViewMode] = useState<PortfolioViewMode>("overview");
  const [tokenRiskFilter, setTokenRiskFilter] = useState<TokenRiskFilter>("all");
  const [sourceViewMode, setSourceViewMode] = useState<SourceViewMode>("overview");
  const [exportViewMode, setExportViewMode] = useState<ExportViewMode>("packages");
  const [reviewViewMode, setReviewViewMode] = useState<ReviewViewMode>("tasks");
  const [importViewMode, setImportViewMode] = useState<ImportViewMode>("assistant");
  const [minHoldingValueEur, setMinHoldingValueEur] = useState("1");
  const [jupiterTokenQuery, setJupiterTokenQuery] = useState("JUP");
  const activeLabel = useMemo(
    () => navItems.find((item) => item.id === active)?.label ?? "Dashboard",
    [active]
  );
  const activeDescription = useMemo(
    () => navItems.find((item) => item.id === active)?.description ?? API_BASE,
    [active]
  );

  async function refresh() {
    setLoading(true);
    setError(null);
    setNotice(null);
    try {
      const allLoaders: Record<string, SnapshotLoader> = {
        health: { key: "health", label: "Health", load: () => getApi<Record<string, unknown>>("/api/v1/health") },
        cockpit: { key: "cockpit", label: "Cockpit", load: () => getApi<Snapshot["cockpit"]>("/api/v1/cockpit/summary") },
        sourcesOverview: { key: "sourcesOverview", label: "Quellen", load: () => getApi<Snapshot["sourcesOverview"]>("/api/v1/sources/overview") },
        sourceConnectorDiagnostics: { key: "sourceConnectorDiagnostics", label: "Connector-Diagnose", load: () => getApi<Snapshot["sourceConnectorDiagnostics"]>("/api/v1/sources/connector-diagnostics") },
        v1CexCredentialTakeover: { key: "v1CexCredentialTakeover", label: "V1-CEX-Credential-Uebernahme", load: () => getApi<Snapshot["v1CexCredentialTakeover"]>("/api/v1/admin/cex-credentials/v1-takeover") },
        sourceDetail: {
          key: "sourceDetail",
          label: "Quellen-Detail",
          load: () => {
            const defaultSourceId = String(snapshot.sourcesOverview?.sources?.[0]?.source_id ?? "binance");
            return getApi<Snapshot["sourceDetail"]>(`/api/v1/sources/${encodeURIComponent(selectedSourceId ?? defaultSourceId)}`);
          }
        },
        sourceReconciliation: {
          key: "sourceReconciliation",
          label: "Quellen-Reconciliation",
          load: () => {
            const defaultSourceId = String(snapshot.sourcesOverview?.sources?.[0]?.source_id ?? "binance");
            return getApi<Snapshot["sourceReconciliation"]>(`/api/v1/sources/${encodeURIComponent(selectedSourceId ?? defaultSourceId)}/reconciliation`);
          }
        },
        sourceReconciliationEvidence: {
          key: "sourceReconciliationEvidence",
          label: "Binance Evidence",
          load: () => {
            const defaultSourceId = String(snapshot.sourcesOverview?.sources?.[0]?.source_id ?? "binance");
            const sourceId = selectedSourceId ?? defaultSourceId;
            if (sourceId !== "binance") {
              return Promise.resolve(undefined);
            }
            return getApi<Snapshot["sourceReconciliationEvidence"]>("/api/v1/sources/binance/reconciliation/evidence");
          }
        },
        binanceEarnHistoryPreflight: {
          key: "binanceEarnHistoryPreflight",
          label: "Binance Earn Preflight",
          load: () => {
            const defaultSourceId = String(snapshot.sourcesOverview?.sources?.[0]?.source_id ?? "binance");
            const sourceId = selectedSourceId ?? defaultSourceId;
            if (sourceId !== "binance") {
              return Promise.resolve(undefined);
            }
            return getApi<Snapshot["binanceEarnHistoryPreflight"]>("/api/v1/sources/binance/earn-history-preflight");
          }
        },
        binanceEarnHistoryApiPreview: {
          key: "binanceEarnHistoryApiPreview",
          label: "Binance Earn API",
          load: () => {
            const defaultSourceId = String(snapshot.sourcesOverview?.sources?.[0]?.source_id ?? "binance");
            const sourceId = selectedSourceId ?? defaultSourceId;
            if (sourceId !== "binance") {
              return Promise.resolve(undefined);
            }
            return getApi<Snapshot["binanceEarnHistoryApiPreview"]>("/api/v1/sources/binance/earn-history-api-preview?since=2025-01-01&max_pages=2&max_records=500");
          }
        },
        imports: { key: "imports", label: "Import-Batches", load: () => getApi<Array<Record<string, unknown>>>("/api/v1/import/batches") },
        importCoverage: { key: "importCoverage", label: "Import-Coverage", load: () => getApi<Snapshot["importCoverage"]>("/api/v1/import/coverage?limit=80&max_seconds=8") },
        parserPreflight: { key: "parserPreflight", label: "Parser-Preflight", load: () => getApi<Snapshot["parserPreflight"]>("/api/v1/import/parser-preflight?limit=20") },
        blockpitSolanaPreflight: { key: "blockpitSolanaPreflight", label: "Blockpit/Solana-Preflight", load: () => getApi<Snapshot["blockpitSolanaPreflight"]>("/api/v1/import/blockpit-solana/preflight") },
        solscanTokenPreflight: { key: "solscanTokenPreflight", label: "Solscan/IOT-Preflight", load: () => getApi<Snapshot["solscanTokenPreflight"]>("/api/v1/import/solscan/token-preflight") },
        walletMonthlyPreflight: { key: "walletMonthlyPreflight", label: "Wallet-Monats-Preflight", load: () => getApi<Snapshot["walletMonthlyPreflight"]>("/api/v1/import/wallet-monthly/preflight") },
        rawObjects: { key: "rawObjects", label: "Raw Objects", load: () => getApi<Array<Record<string, unknown>>>("/api/v1/raw/objects") },
        canonicalEvents: { key: "canonicalEvents", label: "Canonical Events", load: () => getApi<Array<Record<string, unknown>>>("/api/v1/events/canonical") },
        importProfiles: { key: "importProfiles", label: "Import-Profile", load: () => getApi<Array<Record<string, unknown>>>("/api/v1/import/profiles") },
        portfolio: { key: "portfolio", label: "Portfolio", load: () => getApi<Snapshot["portfolio"]>("/api/v1/portfolio/snapshot") },
        portfolioTokenRisk: { key: "portfolioTokenRisk", label: "Token-Risiko", load: () => getApi<Snapshot["portfolioTokenRisk"]>(`/api/v1/portfolio/token-risk?risk_status=${encodeURIComponent(tokenRiskFilter)}&min_value_eur=1`) },
        portfolioValuationAudit: { key: "portfolioValuationAudit", label: "Portfolio-Bewertungsanalyse", load: () => getApi<Snapshot["portfolioValuationAudit"]>("/api/v1/portfolio/valuation-audit") },
        portfolioSources: { key: "portfolioSources", label: "Portfolio-Quellen", load: () => getApi<Snapshot["portfolioSources"]>("/api/v1/portfolio/sources") },
        portfolioReconciliation: { key: "portfolioReconciliation", label: "Portfolio-Abgleich", load: () => getApi<Snapshot["portfolioReconciliation"]>("/api/v1/portfolio/reconciliation") },
        portfolioAsOf: { key: "portfolioAsOf", label: "Stichtags-Portfolio", load: () => getApi<Snapshot["portfolioAsOf"]>(`/api/v1/portfolio/as-of?as_of=${encodeURIComponent(asOfDate)}`) },
        separationReport: { key: "separationReport", label: "Trennungs-Portfolio", load: () => getApi<Snapshot["separationReport"]>("/api/v1/portfolio/separation-report") },
        fiatDeposits: { key: "fiatDeposits", label: "Binance-Fiat-Einzahlungen", load: () => getApi<Snapshot["fiatDeposits"]>("/api/v1/portfolio/fiat-deposits/binance") },
        review: { key: "review", label: "Review", load: () => getApi<Snapshot["review"]>("/api/v1/review/gates") },
        reviewTasks: { key: "reviewTasks", label: "Review-Aufgaben", load: () => getApi<Snapshot["reviewTasks"]>("/api/v1/review/tasks") },
        reviewDecisions: { key: "reviewDecisions", label: "Review-Entscheidungen", load: () => getApi<Array<Record<string, unknown>>>("/api/v1/review/decisions") },
        reviewDecisionSuggestions: { key: "reviewDecisionSuggestions", label: "Review-Vorschlaege", load: () => getApi<Array<Record<string, unknown>>>("/api/v1/review/decision-suggestions") },
        reviewEvidenceTraces: { key: "reviewEvidenceTraces", label: "Review-Belegspuren", load: () => getApi<Snapshot["reviewEvidenceTraces"]>("/api/v1/review/evidence-traces") },
        parity: { key: "parity", label: "V1/V2-Paritaet", load: () => getApi<Snapshot["parity"]>("/api/v1/parity/compare") },
        parityDiagnostics: { key: "parityDiagnostics", label: "V1/V2-Diagnose", load: () => getApi<Snapshot["parityDiagnostics"]>("/api/v1/parity/diagnostics") },
        parityReleaseReadiness: { key: "parityReleaseReadiness", label: "Paritaets-Release", load: () => getApi<Snapshot["parityReleaseReadiness"]>("/api/v1/parity/release-readiness") },
        parityReferences: { key: "parityReferences", label: "V1-Referenzen", load: () => getApi<Array<Record<string, unknown>>>("/api/v1/parity/v1/references") },
        hntFifoProvenance: { key: "hntFifoProvenance", label: "HNT FIFO-Herkunft", load: () => getApi<Snapshot["hntFifoProvenance"]>("/api/v1/parity/hnt-fifo-provenance?limit=1000") },
        flows: {
          key: "flows",
          label: "Geldfluesse",
          load: () => getApi<Snapshot["flows"]>(flowYear === "all" ? "/api/v1/flows/net" : `/api/v1/flows/net?year=${flowYear}`)
        },
        transferCandidates: { key: "transferCandidates", label: "Transfer-Kandidaten", load: () => getApi<Snapshot["transferCandidates"]>("/api/v1/transfers/candidates?limit=200") },
        exportReadiness: { key: "exportReadiness", label: "Export-Freigabe", load: () => getApi<Record<string, unknown>>("/api/v1/export/readiness") },
        exports: { key: "exports", label: "Export-Pakete", load: () => getApi<Array<Record<string, unknown>>>("/api/v1/export/packages") },
        reportCenter: { key: "reportCenter", label: "Report-Center", load: () => getApi<Snapshot["reportCenter"]>("/api/v1/reports/center") },
        reportEvidenceManifest: { key: "reportEvidenceManifest", label: "Belegmanifest", load: () => getRawJson<EvidenceManifest>("/api/v1/export/evidence-manifest.json") },
        reportEvidencePackageIndex: { key: "reportEvidencePackageIndex", label: "Belegpaket-Index", load: () => getRawJson<EvidencePackageIndex>("/api/v1/export/evidence-package-index.json") },
        divorceEqualization: { key: "divorceEqualization", label: "Zugewinn-Auswertung", load: () => getApi<Snapshot["divorceEqualization"]>("/api/v1/divorce/equalization-summary") },
        admin: { key: "admin", label: "Admin-Status", load: () => getApi<Record<string, unknown>>("/api/v1/admin/status") },
        adminSettings: { key: "adminSettings", label: "Admin-Settings", load: () => getApi<Array<Record<string, unknown>>>("/api/v1/admin/settings") },
        jupiterMetadataCache: { key: "jupiterMetadataCache", label: "Jupiter Token-Metadata", load: () => getApi<Snapshot["jupiterMetadataCache"]>("/api/v1/sources/jupiter/tokens/metadata-cache?limit=200") },
        jupiterRiskReview: { key: "jupiterRiskReview", label: "Token-Risiko-Review", load: () => getApi<Snapshot["jupiterRiskReview"]>("/api/v1/sources/jupiter/tokens/risk-review?risk_status=spam_review&limit=200") },
        ai: { key: "ai", label: "KI-Aufgaben", load: () => getApi<Array<Record<string, unknown>>>("/api/v1/ai/tasks") },
        localAiYearPackageQa: { key: "localAiYearPackageQa", label: "Lokale KI Jahrespaket-QA", load: () => getApi<Snapshot["localAiYearPackageQa"]>("/api/v1/ai/local-year-package-qa") },
        taxLots: { key: "taxLots", label: "FIFO-Lots", load: () => getApi<Array<Record<string, unknown>>>("/api/v1/tax/lots") },
        taxLines: { key: "taxLines", label: "Tax-Lines", load: () => getApi<Array<Record<string, unknown>>>("/api/v1/tax/lines") },
        taxUnmatchedDisposals: { key: "taxUnmatchedDisposals", label: "Nicht zugeordnete FIFO-Abgaenge", load: () => getApi<Array<Record<string, unknown>>>("/api/v1/tax/unmatched-disposals") },
        taxHoldingPeriods: { key: "taxHoldingPeriods", label: "Haltefristen", load: () => getApi<Snapshot["taxHoldingPeriods"]>(`/api/v1/tax/holding-periods?min_value_eur=${encodeURIComponent(minHoldingValueEur || "1")}`) },
        taxLossRealizationPlanner: { key: "taxLossRealizationPlanner", label: "Verlustplanung", load: () => getApi<Snapshot["taxLossRealizationPlanner"]>(`/api/v1/tax/loss-realization-planner?min_loss_eur=1&min_value_eur=${encodeURIComponent(minHoldingValueEur || "1")}&limit=120`) },
        taxSummary: { key: "taxSummary", label: "Tax-Summary", load: () => getApi<Record<string, unknown> | null>("/api/v1/tax/summary") },
        taxYearsSummary: { key: "taxYearsSummary", label: "Steuerjahre", load: () => getApi<Snapshot["taxYearsSummary"]>("/api/v1/tax-years/summary") },
        taxPaymentOverview: { key: "taxPaymentOverview", label: "Steuer-Eingabezettel", load: () => getApi<Snapshot["taxPaymentOverview"]>("/api/v1/tax-years/payment-overview") },
        taxYearFilingMatrix: { key: "taxYearFilingMatrix", label: "Steuerjahr-Matrix", load: () => getApi<Snapshot["taxYearFilingMatrix"]>("/api/v1/tax-years/filing-matrix") },
        taxFilingClosureOverview: { key: "taxFilingClosureOverview", label: "Finale Abgabeuebersicht", load: () => getApi<Snapshot["taxFilingClosureOverview"]>("/api/v1/tax-years/filing-closure-overview") },
        taxYearsCorrectionMap: { key: "taxYearsCorrectionMap", label: "Korrekturkarte Jahre", load: () => getApi<Snapshot["taxYearsCorrectionMap"]>("/api/v1/tax-years/correction-map") },
        taxMethodologySummary: { key: "taxMethodologySummary", label: "BMF-Methodik", load: () => getApi<Snapshot["taxMethodologySummary"]>(`/api/v1/tax-methodology/summary?year=${encodeURIComponent(selectedTaxYear)}`) },
        taxBmfActionPlan: { key: "taxBmfActionPlan", label: "BMF-Aktionsliste", load: () => getApi<Snapshot["taxBmfActionPlan"]>(`/api/v1/tax-methodology/bmf-action-plan?year=${encodeURIComponent(selectedTaxYear)}`) },
        taxYearDetail: { key: "taxYearDetail", label: "Steuerjahr-Detail", load: () => getApi<Snapshot["taxYearDetail"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}`) },
        taxDeclarationGuide: { key: "taxDeclarationGuide", label: "Steuererklaerungshilfe", load: () => getApi<Snapshot["taxDeclarationGuide"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/declaration-guide`) },
        taxYearFilingSummary: { key: "taxYearFilingSummary", label: "Steuerjahr-Erklaerung", load: () => getApi<Snapshot["taxYearFilingSummary"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/filing-summary`) },
        taxYearCorrectionMap: { key: "taxYearCorrectionMap", label: "Korrekturkarte", load: () => getApi<Snapshot["taxYearCorrectionMap"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/correction-map`) },
        taxYearMethodology: { key: "taxYearMethodology", label: "BMF-Jahrescheck", load: () => getApi<Snapshot["taxYearMethodology"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/methodology`) },
        taxYearWalletFifoDelta: { key: "taxYearWalletFifoDelta", label: "Wallet-FIFO-Delta", load: () => getApi<Snapshot["taxYearWalletFifoDelta"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/wallet-fifo-delta`) },
        taxYearWalletFifoGaps: { key: "taxYearWalletFifoGaps", label: "Wallet-FIFO-Luecken", load: () => getApi<Snapshot["taxYearWalletFifoGaps"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/wallet-fifo-gaps?limit=80`) },
        taxYearWalletFifoOriginTrace: { key: "taxYearWalletFifoOriginTrace", label: "Wallet-FIFO-Herkunft", load: () => getApi<Snapshot["taxYearWalletFifoOriginTrace"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/wallet-fifo-origin-trace?asset=JUP&pool_id=binance%3ASpot&limit=20`) },
        taxYearCexDepositTransferEvidence: { key: "taxYearCexDepositTransferEvidence", label: "CEX Deposit Evidence", load: () => getApi<Snapshot["taxYearCexDepositTransferEvidence"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/cex-deposit-transfer-evidence?cex=binance&network=SOL&limit=100`) },
        taxYearCexSenderOwnershipLatest: { key: "taxYearCexSenderOwnershipLatest", label: "CEX Sender Ownership", load: () => getApi<Snapshot["taxYearCexSenderOwnershipLatest"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/cex-sender-ownership-latest?cex=binance&network=SOL&limit=100`) },
        taxYearCexExchangeOutflowEvidence: { key: "taxYearCexExchangeOutflowEvidence", label: "CEX Exchange Outflow Evidence", load: () => getApi<Snapshot["taxYearCexExchangeOutflowEvidence"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/cex-exchange-outflow-evidence?source_exchange=bitget&target_cex=binance&network=SOL&window_hours=72&limit=100`) },
        taxYearCexExchangeOutflowAnchorFeasibility: { key: "taxYearCexExchangeOutflowAnchorFeasibility", label: "CEX FIFO-Anker", load: () => getApi<Snapshot["taxYearCexExchangeOutflowAnchorFeasibility"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/cex-exchange-outflow-anchor-feasibility?source_exchange=bitget&target_cex=binance&network=SOL`) },
        taxYearWalletFifoProvenanceClosure: { key: "taxYearWalletFifoProvenanceClosure", label: "Wallet-FIFO Jahresampel", load: () => getApi<Snapshot["taxYearWalletFifoProvenanceClosure"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/wallet-fifo-provenance-closure?limit=20`) },
        taxYearWalletFifoProvenancePriorities: { key: "taxYearWalletFifoProvenancePriorities", label: "Wallet-FIFO Provenance", load: () => getApi<Snapshot["taxYearWalletFifoProvenancePriorities"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/wallet-fifo-provenance-priorities?limit=25`) },
        taxYearWalletFifoRawProvenanceBreakdown: { key: "taxYearWalletFifoRawProvenanceBreakdown", label: "Raw Provenance Breakdown", load: () => getApi<Snapshot["taxYearWalletFifoRawProvenanceBreakdown"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/wallet-fifo-raw-provenance-breakdown?limit=50`) },
        taxYearWalletFifoExchangeEvidenceGaps: { key: "taxYearWalletFifoExchangeEvidenceGaps", label: "Exchange Evidence Gaps", load: () => getApi<Snapshot["taxYearWalletFifoExchangeEvidenceGaps"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/wallet-fifo-exchange-evidence-gaps?limit=50`) },
        taxYearWalletFifoSolanaProvenanceClassification: { key: "taxYearWalletFifoSolanaProvenanceClassification", label: "Solana Provenance", load: () => getApi<Snapshot["taxYearWalletFifoSolanaProvenanceClassification"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/wallet-fifo-solana-provenance-classification?asset=SOL&pool_id=solana_rpc%3AG39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY&limit=5&provider=rpc_public`) },
        taxYearWalletFifoSolanaProvenanceBatchLatest: { key: "taxYearWalletFifoSolanaProvenanceBatchLatest", label: "Solana Provenance Batch", load: () => getApi<Snapshot["taxYearWalletFifoSolanaProvenanceBatchLatest"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/wallet-fifo-solana-provenance-batch-latest?asset=SOL`) },
        taxYearWalletFifoSolanaRawProvenanceSenders: { key: "taxYearWalletFifoSolanaRawProvenanceSenders", label: "Solana Raw Sender", load: () => getApi<Snapshot["taxYearWalletFifoSolanaRawProvenanceSenders"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/wallet-fifo-solana-raw-provenance-senders?asset=SOL&pool_id=solana_rpc%3AG39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY&limit=25`) },
        taxYearWalletFifoSolanaRawProvenancePriorities: { key: "taxYearWalletFifoSolanaRawProvenancePriorities", label: "Solana Raw Prioritaeten", load: () => getApi<Snapshot["taxYearWalletFifoSolanaRawProvenancePriorities"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/wallet-fifo-solana-raw-provenance-priorities?asset=SOL&pool_id=solana_rpc%3AG39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY&limit=30`) },
        taxYearWalletFifoSolanaRawBmfEvidenceSummary: { key: "taxYearWalletFifoSolanaRawBmfEvidenceSummary", label: "Solana BMF-Belege", load: () => getApi<Snapshot["taxYearWalletFifoSolanaRawBmfEvidenceSummary"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/wallet-fifo-solana-raw-bmf-evidence-summary?asset=SOL&pool_id=solana_rpc%3AG39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY&limit=25`) },
        taxYearWalletFifoSolanaRawBmfEvidenceDrilldown: { key: "taxYearWalletFifoSolanaRawBmfEvidenceDrilldown", label: "Solana BMF-Drilldown", load: () => getApi<Snapshot["taxYearWalletFifoSolanaRawBmfEvidenceDrilldown"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/wallet-fifo-solana-raw-bmf-evidence-drilldown?asset=SOL&pool_id=solana_rpc%3AG39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY&route_classification=program_service_route&bmf_evidence_priority=high&limit=25`) },
        taxYearWalletFifoSolanaSenderClusters: { key: "taxYearWalletFifoSolanaSenderClusters", label: "Solana Sender-Cluster", load: () => getApi<Snapshot["taxYearWalletFifoSolanaSenderClusters"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/wallet-fifo-solana-sender-clusters?asset=SOL&limit=25`) },
        taxYearWalletFifoSolanaSenderClusterOutflows: { key: "taxYearWalletFifoSolanaSenderClusterOutflows", label: "Solana Outflow-Kandidaten", load: () => getApi<Snapshot["taxYearWalletFifoSolanaSenderClusterOutflows"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/wallet-fifo-solana-sender-cluster-outflows?asset=SOL&limit=25&window_hours=48&amount_tolerance_percent=1`) },
        taxYearWalletFifoSolanaOrigin: { key: "taxYearWalletFifoSolanaOrigin", label: "Solana-Herkunft", load: () => getApi<Snapshot["taxYearWalletFifoSolanaOrigin"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/wallet-fifo-solana-origin?asset=JUP&pool_id=binance%3ASpot&limit=5`) },
        taxLegacyHeliumOverview: { key: "taxLegacyHeliumOverview", label: "Legacy HNT", load: () => getApi<Snapshot["taxLegacyHeliumOverview"]>("/api/v1/tax/legacy-helium-overview?limit=20") },
        taxIncomeGuide: { key: "taxIncomeGuide", label: "Mining/Rewards", load: () => getApi<Snapshot["taxIncomeGuide"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/income-guide`) },
        taxRewardTradingSeparation: { key: "taxRewardTradingSeparation", label: "Reward vs Handel", load: () => getApi<Snapshot["taxRewardTradingSeparation"]>("/api/v1/tax-years/reward-trading-separation") },
        taxYearDrivers: { key: "taxYearDrivers", label: "Gewinntreiber", load: () => getApi<Snapshot["taxYearDrivers"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/drivers?limit=80`) },
        taxYearGainLossRealityCheck: { key: "taxYearGainLossRealityCheck", label: "Realisiert vs gehalten", load: () => getApi<Snapshot["taxYearGainLossRealityCheck"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/gain-loss-reality-check?limit=40`) },
        taxYearTurnoverAudit: { key: "taxYearTurnoverAudit", label: "Umsatz-Plausibilitaet", load: () => getApi<Snapshot["taxYearTurnoverAudit"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/turnover-audit?limit=20`) },
        taxYearsTurnoverAuditSummary: { key: "taxYearsTurnoverAuditSummary", label: "Umsatz-Plausibilitaet alle Jahre", load: () => getApi<Snapshot["taxYearsTurnoverAuditSummary"]>("/api/v1/tax-years/turnover-audit-summary?limit=8") },
        taxSolanaProgramIncomeReview: { key: "taxSolanaProgramIncomeReview", label: "Solana Programm-Kontext", load: () => getApi<Snapshot["taxSolanaProgramIncomeReview"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/solana-program-income-review?limit=20`) },
        taxStablecoinFifoReview: { key: "taxStablecoinFifoReview", label: "Stablecoin FIFO", load: () => getApi<Snapshot["taxStablecoinFifoReview"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/stablecoin-fifo-review?limit=20`) },
        taxStablecoinQuoteLegReview: { key: "taxStablecoinQuoteLegReview", label: "Stablecoin Quote-Beine", load: () => getApi<Snapshot["taxStablecoinQuoteLegReview"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/stablecoin-quote-leg-review?limit=20`) },
        taxSolanaStablecoinSwapContext: { key: "taxSolanaStablecoinSwapContext", label: "Solana Stablecoin-Swaps", load: () => getApi<Snapshot["taxSolanaStablecoinSwapContext"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/solana-stablecoin-swap-context?limit=20`) },
        taxSolanaStablecoinFxReview: { key: "taxSolanaStablecoinFxReview", label: "Solana Stablecoin FX", load: () => getApi<Snapshot["taxSolanaStablecoinFxReview"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/solana-stablecoin-fx-review?limit=20`) },
        taxYearEvidence: { key: "taxYearEvidence", label: "Jahres-Belegkarte", load: () => getApi<Snapshot["taxYearEvidence"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/evidence`) },
        taxExternalInflows: { key: "taxExternalInflows", label: "Externe Solana-Zufluesse", load: () => getApi<Snapshot["taxExternalInflows"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/external-inflows?limit=200`) },
        derivativeLines: { key: "derivativeLines", label: "Derivate-Zeilen", load: () => getApi<Array<Record<string, unknown>>>("/api/v1/derivatives/lines") },
        derivativeSummary: { key: "derivativeSummary", label: "Derivate-Summary", load: () => getApi<Record<string, unknown> | null>("/api/v1/derivatives/summary") },
        prices: { key: "prices", label: "Preis-Ledger", load: () => getApi<Array<Record<string, unknown>>>("/api/v1/prices") },
        latestPrices: { key: "latestPrices", label: "Wirksame Preise", load: () => getApi<Array<Record<string, unknown>>>("/api/v1/prices/latest") },
        priceCoverage: { key: "priceCoverage", label: "Preis-Coverage", load: () => getApi<Snapshot["priceCoverage"]>("/api/v1/prices/coverage") },
        priceQuality: { key: "priceQuality", label: "Preisqualitaet", load: () => getApi<Snapshot["priceQuality"]>("/api/v1/prices/quality") },
        priceManualReview: { key: "priceManualReview", label: "Preisqualitaet manuell", load: () => getApi<Snapshot["priceManualReview"]>("/api/v1/prices/quality/manual-review") },
        priceStablecoinFxReview: { key: "priceStablecoinFxReview", label: "Stablecoin-FX-Review", load: () => getApi<Snapshot["priceStablecoinFxReview"]>("/api/v1/prices/quality/stablecoin-fx-review") },
        priceSolscanSignatureReview: { key: "priceSolscanSignatureReview", label: "Solscan-Signatur-Review", load: () => getApi<Snapshot["priceSolscanSignatureReview"]>("/api/v1/prices/quality/solscan-signature-review") },
        priceBinanceNormalizerReview: { key: "priceBinanceNormalizerReview", label: "Binance-Normalizer-Review", load: () => getApi<Snapshot["priceBinanceNormalizerReview"]>("/api/v1/prices/quality/binance-normalizer-review") },
        priceEventQuoteEvidenceReview: { key: "priceEventQuoteEvidenceReview", label: "Event-Quote-Evidenz", load: () => getApi<Snapshot["priceEventQuoteEvidenceReview"]>("/api/v1/prices/quality/event-quote-evidence-review") },
        priceRequirements: { key: "priceRequirements", label: "Preis-Anforderungen", load: () => getApi<Snapshot["priceRequirements"]>("/api/v1/prices/requirements") }
      };
      const taxLoaderKeys = [
        "health",
        "taxYearsSummary",
        "taxPaymentOverview",
        "taxYearFilingMatrix",
        "taxFilingClosureOverview",
        "taxYearsCorrectionMap",
        "taxYearDetail",
        "taxDeclarationGuide",
        "taxYearFilingSummary",
        "taxYearTurnoverAudit",
        "taxYearsTurnoverAuditSummary",
        "taxSolanaProgramIncomeReview",
        "taxStablecoinFifoReview",
        "taxStablecoinQuoteLegReview",
        "taxSolanaStablecoinSwapContext",
        "taxSolanaStablecoinFxReview",
        "taxYearEvidence",
        "taxHoldingPeriods",
        "taxLossRealizationPlanner",
        "taxSummary",
        "derivativeSummary",
        ...(taxViewMode !== "guided"
          ? [
              "taxMethodologySummary",
              "taxBmfActionPlan",
              "taxYearMethodology",
              "taxYearWalletFifoDelta",
              "taxYearWalletFifoGaps",
              "taxYearWalletFifoOriginTrace",
              "taxYearCexDepositTransferEvidence",
              "taxYearCexSenderOwnershipLatest",
              "taxYearCexExchangeOutflowEvidence",
              "taxYearCexExchangeOutflowAnchorFeasibility",
              "taxYearWalletFifoProvenanceClosure",
              "taxYearWalletFifoSolanaOrigin",
              "taxLegacyHeliumOverview",
              "taxIncomeGuide",
              "taxRewardTradingSeparation",
              "taxYearDrivers",
              "taxYearGainLossRealityCheck",
              "taxExternalInflows",
              "taxUnmatchedDisposals"
            ]
          : [])
      ];
      const loaderKeysBySection: Record<Section, string[]> = {
        dashboard: ["health", "cockpit"],
        sources: [
          "health",
          "sourcesOverview",
          ...(sourceViewMode !== "overview"
            ? ["sourceDetail", "sourceReconciliation", "sourceReconciliationEvidence", "binanceEarnHistoryPreflight", "binanceEarnHistoryApiPreview"]
            : []),
          ...(sourceViewMode === "expert" ? ["sourceConnectorDiagnostics"] : [])
        ],
        import: [
          "health",
          "imports",
          ...(importViewMode !== "assistant" ? ["importCoverage"] : []),
          ...(importViewMode !== "assistant" ? ["parserPreflight", "blockpitSolanaPreflight", "solscanTokenPreflight", "walletMonthlyPreflight"] : []),
          ...(importViewMode === "expert" ? ["rawObjects", "canonicalEvents", "importProfiles"] : [])
        ],
        portfolio: [
          "health",
          "portfolio",
          "portfolioTokenRisk",
          "portfolioSources",
          "taxHoldingPeriods",
          "priceCoverage",
          ...(portfolioViewMode !== "overview"
            ? ["portfolioReconciliation", "portfolioValuationAudit", "separationReport", "fiatDeposits", "latestPrices"]
            : []),
          ...(portfolioViewMode === "expert"
            ? ["prices", "priceQuality", "priceManualReview", "priceStablecoinFxReview", "priceSolscanSignatureReview", "priceBinanceNormalizerReview", "priceEventQuoteEvidenceReview", "priceRequirements"]
            : [])
        ],
        stichtage: ["health", "portfolioAsOf", "priceCoverage"],
        zugewinn: ["health", "divorceEqualization"],
        flows: ["health", "flows", "transferCandidates"],
        review: [
          "health",
          "review",
          "reviewTasks",
          "jupiterRiskReview",
          "reviewDecisions",
          ...(reviewViewMode !== "tasks" ? ["reviewEvidenceTraces", "reviewDecisionSuggestions", "blockpitSolanaPreflight"] : []),
          ...(reviewViewMode === "expert" ? ["priceCoverage", "priceQuality", "priceManualReview", "priceStablecoinFxReview", "priceSolscanSignatureReview", "priceBinanceNormalizerReview", "priceEventQuoteEvidenceReview", "priceRequirements"] : [])
        ],
        parity: ["health", "parity", "parityDiagnostics", "parityReleaseReadiness", "parityReferences", "hntFifoProvenance"],
        tax: taxLoaderKeys,
        export: [
          "health",
          "reportCenter",
          "exportReadiness",
          "review",
          "reviewDecisions",
          ...(exportViewMode !== "packages" ? ["reportEvidenceManifest", "reportEvidencePackageIndex"] : []),
          ...(exportViewMode === "expert" ? ["exports", "priceQuality"] : [])
        ],
        admin: ["health", "admin", "adminSettings", "sourceConnectorDiagnostics", "v1CexCredentialTakeover", "jupiterMetadataCache"],
        ai: ["health", "ai", "localAiYearPackageQa"]
      };
      const loaders = loaderKeysBySection[active].map((key) => allLoaders[key]);
      setLoaderStatuses(loaders.map((loader) => ({ key: loader.key, label: loader.label, status: "pending" })));
      const runLoader = async (loader: SnapshotLoader) => {
        setLoaderStatuses((current) =>
          current.map((item) => (item.key === loader.key ? { ...item, status: "loading", detail: undefined, duration_ms: undefined } : item))
        );
        const startedAt = performance.now();
        try {
          const value = await loader.load();
          const durationMs = performance.now() - startedAt;
          setLoaderStatuses((current) =>
            current.map((item) =>
              item.key === loader.key
                ? {
                    ...item,
                    status: "ok",
                    detail: `${loader.label} geladen in ${formatDurationMs(durationMs)}`,
                    duration_ms: durationMs
                  }
                : item
            )
          );
          return value;
        } catch (caught) {
          const durationMs = performance.now() - startedAt;
          const detail = caught instanceof Error ? caught.message : "fehlgeschlagen";
          setLoaderStatuses((current) =>
            current.map((item) =>
              item.key === loader.key
                ? {
                    ...item,
                    status: "error",
                    detail: `${detail} nach ${formatDurationMs(durationMs)}`,
                    duration_ms: durationMs
                  }
                : item
            )
          );
          throw caught;
        }
      };
      const results = await Promise.allSettled(loaders.map((loader) => runLoader(loader)));
      const nextSnapshot: Partial<Snapshot> = {};
      const failures: string[] = [];
      results.forEach((result, index) => {
        const loader = loaders[index];
        if (result.status === "fulfilled") {
          nextSnapshot[loader.key] = result.value as never;
          return;
        }
        failures.push(`${loader.label}: ${result.reason instanceof Error ? result.reason.message : "fehlgeschlagen"}`);
      });
      setSnapshot((current) => ({ ...current, ...nextSnapshot }));
      if (failures.length > 0) {
        setError(`Teilweise geladen. Fehlgeschlagen: ${failures.slice(0, 4).join(" | ")}${failures.length > 4 ? ` | +${failures.length - 4} weitere` : ""}`);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unbekannter API-Fehler");
    } finally {
      setLoading(false);
    }
  }

  async function rebuildFlows() {
    setLoading(true);
    try {
      await postApi("/api/v1/flows/rebuild");
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Flow-Rebuild fehlgeschlagen");
      setLoading(false);
    }
  }

  async function refreshConfiguredSources() {
    setSourceRefreshLoading(true);
    setError(null);
    setNotice(null);
    try {
      const response = await postApiResponse<ReconciliationRefreshResult>("/api/v1/portfolio/reconciliation/refresh");
      const result = response.data;
      const cockpit = await getApi<Snapshot["cockpit"]>("/api/v1/cockpit/summary");
      const sourcesOverview = await getApi<Snapshot["sourcesOverview"]>("/api/v1/sources/overview");
      const sourceConnectorDiagnostics = await getApi<Snapshot["sourceConnectorDiagnostics"]>("/api/v1/sources/connector-diagnostics");
      const sourceId = selectedSourceId ?? String(sourcesOverview?.sources?.[0]?.source_id ?? "binance");
      const [sourceDetail, sourceReconciliation] = await Promise.all([
        getApi<Snapshot["sourceDetail"]>(`/api/v1/sources/${encodeURIComponent(sourceId)}`),
        getApi<Snapshot["sourceReconciliation"]>(`/api/v1/sources/${encodeURIComponent(sourceId)}/reconciliation`)
      ]);
      setSnapshot((current) => ({
        ...current,
        cockpit,
        portfolioReconciliation: result.report,
        sourcesOverview,
        sourceConnectorDiagnostics,
        sourceDetail,
        sourceReconciliation
      }));
      const connectors = result.connectors.length > 0 ? result.connectors.join(", ") : "keine";
      const reconciliationRows = result.report?.rows ?? [];
      const blockerCount = reconciliationRows.filter((row) => row.severity === "blocker").length;
      const warningCount = reconciliationRows.filter((row) => row.severity === "warning").length;
      const emptyConnectors = (result.connector_results ?? [])
        .filter((item) => item.status !== "refreshed")
        .map((item) => `${item.connector_id}: ${item.status}`)
        .join(", ");
      const apiWarnings = (response.warnings ?? []).map((warning) => warning.message).join(" | ");
      setNotice(
        `Quellen abgefragt: ${connectors}. Live-Snapshots: ${result.imported_snapshots}. Blocker/Warnungen: ${blockerCount}/${warningCount}. Stand ${formatDateTime(result.fetched_at)}.${emptyConnectors ? ` Ohne neue Snapshots: ${emptyConnectors}.` : ""}${apiWarnings ? ` Hinweise: ${apiWarnings}` : ""}`
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Quellen konnten nicht abgefragt werden");
    } finally {
      setSourceRefreshLoading(false);
    }
  }

  async function rebuildTax() {
    setLoading(true);
    try {
      await postApi("/api/v1/tax/fifo/rebuild");
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Tax-Rebuild fehlgeschlagen");
      setLoading(false);
    }
  }

  async function rebuildDerivatives() {
    setLoading(true);
    try {
      await postApi("/api/v1/derivatives/rebuild");
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Derivate-Rebuild fehlgeschlagen");
      setLoading(false);
    }
  }

  async function importCsv(
    source: string,
    filename: string,
    content: string,
    contentBase64?: string | null,
    sheetName?: string | null
  ) {
    setLoading(true);
    setError(null);
    try {
      const result = await postApi<Record<string, unknown>>("/api/v1/import/assistant/execute", {
        source,
        import_mode: "file",
        filename,
        content: contentBase64 ? null : content,
        content_base64: contentBase64,
        sheet_name: sheetName || undefined
      });
      const batch = result.batch as Record<string, unknown> | undefined;
      const run = result.run as Record<string, unknown> | undefined;
      const skipped = Number(run?.skipped_raw_objects ?? 0);
      const suffix = skipped > 0 ? `, ${skipped} Rohzeile(n) nicht normalisiert` : "";
      setNotice(`Import und Pipeline abgeschlossen: ${String(batch?.batch_id ?? "-")}${suffix}`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Import fehlgeschlagen");
      setLoading(false);
    }
  }

  async function deleteImportBatch(batchId: string) {
    const trimmed = batchId.trim();
    if (!trimmed) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/api/v1/import/batches/${encodeURIComponent(trimmed)}`, {
        method: "DELETE"
      });
      if (!response.ok) {
        throw new Error(`DELETE Import-Batch: HTTP ${response.status}`);
      }
      const body = (await response.json()) as ApiResponse<Record<string, unknown>>;
      if (body.status === "error") {
        throw new Error(body.errors.map((item) => item.message).join(", "));
      }
      const deleted = body.data?.deleted === true;
      setNotice(deleted ? `Import-Batch geloescht: ${trimmed}` : `Import-Batch nicht gefunden: ${trimmed}`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Import-Batch konnte nicht geloescht werden");
      setLoading(false);
    }
  }

  async function runImportBatch(batchId: string) {
    const trimmed = batchId.trim();
    if (!trimmed) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await postApiResponse<Record<string, unknown>>(
        `/api/v1/import/batches/${encodeURIComponent(trimmed)}/run`
      );
      const skipped = Number(response.data?.skipped_raw_objects ?? 0);
      const suffix = skipped > 0 ? `, ${skipped} Rohzeile(n) nicht normalisiert` : "";
      setNotice(`Pipeline fuer Import-Batch ausgefuehrt: ${trimmed}${suffix}`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Import-Pipeline konnte nicht ausgefuehrt werden");
      setLoading(false);
    }
  }

  async function addPrice(asset: string, priceEur: string, pricedAt: string, source: string, confidence: string) {
    setLoading(true);
    setError(null);
    try {
      await postApi("/api/v1/prices", {
        asset,
        price_eur: priceEur,
        priced_at: new Date(pricedAt).toISOString(),
        source,
        confidence
      });
      setNotice(`Preis gespeichert und Pipeline neu berechnet: ${asset}`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Preis konnte nicht gespeichert werden");
      setLoading(false);
    }
  }

  async function importPriceCsv(content: string, defaultSource: string) {
    setLoading(true);
    setError(null);
    try {
      const result = await postApi<Record<string, unknown>>("/api/v1/prices/import/csv", {
        content,
        default_source: defaultSource
      });
      setNotice(`Preis-CSV importiert: ${String(result.imported_prices ?? 0)} Preise`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Preis-CSV konnte nicht importiert werden");
      setLoading(false);
    }
  }

  async function importV1FxCache(dbPath: string, confidence: string) {
    setLoading(true);
    setError(null);
    try {
      const result = await postApi<Record<string, unknown>>("/api/v1/prices/import/v1-fx-cache", {
        db_path: dbPath,
        confidence
      });
      setNotice(`V1-Preiscache importiert: ${String(result.imported_prices ?? 0)} Preise`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "V1-Preiscache konnte nicht importiert werden");
      setLoading(false);
    }
  }

  async function backfillExternalPrices(maxRequests: string, provider: string, dryRun: boolean, assets: string) {
    setLoading(true);
    setError(null);
    try {
      const assetFilter = assets
        .split(",")
        .map((asset) => asset.trim().toUpperCase())
        .filter((asset) => asset.length > 0);
      const result = await postApi<Record<string, unknown>>(
        "/api/v1/prices/backfill/external",
        {
          provider,
          assets: assetFilter,
          max_requests: Number(maxRequests),
          dry_run: dryRun,
          confidence: "1.0"
        },
        180_000
      );
      setNotice(
        dryRun
          ? `Externer Preisbackfill geplant: ${String(result.planned_jobs ?? 0)} Jobs`
          : `Externer Preisbackfill importiert: ${String(result.imported_prices ?? 0)} Preise`
      );
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Externer Preisbackfill konnte nicht ausgefuehrt werden");
      setLoading(false);
    }
  }

  async function backfillCurrentPortfolioPrices(maxRequests: string, dryRun: boolean, assets: string) {
    setLoading(true);
    setError(null);
    try {
      const assetFilter = assets
        .split(",")
        .map((asset) => asset.trim().toUpperCase())
        .filter((asset) => asset.length > 0);
      const result = await postApi<Record<string, unknown>>(
        "/api/v1/prices/backfill/current-portfolio",
        {
          provider: "coingecko",
          assets: assetFilter,
          max_requests: Number(maxRequests),
          dry_run: dryRun,
          confidence: "0.95"
        },
        180_000
      );
      setNotice(
        dryRun
          ? `Aktuelle Portfolio-Preise geplant: ${String(result.planned_jobs ?? 0)} Jobs`
          : `Aktuelle Portfolio-Preise importiert: ${String(result.imported_prices ?? 0)} Preise`
      );
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Aktuelle Portfolio-Preise konnten nicht geladen werden");
      setLoading(false);
    }
  }

  async function addPriceGapDecision(scope: string, decisionStatus: string) {
    if (!scope.trim()) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await postApi("/api/v1/prices/coverage/decisions", {
        scope,
        decision_status: decisionStatus,
        title: `Preis-Luecke: ${decisionStatus}`,
        rationale: "In der V2-Oberflaeche gesetzter Bearbeitungsstatus. Diese Entscheidung ersetzt keinen Preis.",
        evidence_ref: "ui:price-coverage"
      });
      setNotice(`Preis-Lueckenstatus gespeichert: ${decisionStatus}`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Preis-Lueckenstatus konnte nicht gespeichert werden");
      setLoading(false);
    }
  }

  async function addPriceQualityDecision(row: Record<string, unknown>, decisionStatus: string) {
    const asset = String(row.asset ?? "").trim();
    const year = Number(row.year ?? 0);
    const source = String(row.source ?? "").trim();
    if (!asset || !year || !source) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await postApi("/api/v1/prices/quality/decisions", {
        asset,
        year,
        source,
        decision_status: decisionStatus,
        title: `Preisqualitaet: ${asset} ${year} ${decisionStatus}`,
        rationale: "In der V2-Oberflaeche gesetzte Preisqualitaetsentscheidung. Diese Entscheidung aendert keine Preiszeile.",
        evidence_ref: `api:/api/v1/prices/quality/group?asset=${encodeURIComponent(asset)}&year=${year}&source=${encodeURIComponent(source)}`
      });
      setNotice(`Preisqualitaetsentscheidung gespeichert: ${asset} ${year} ${decisionStatus}`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Preisqualitaetsentscheidung konnte nicht gespeichert werden");
      setLoading(false);
    }
  }

  async function deletePricePoint(priceId: string) {
    const trimmed = priceId.trim();
    if (!trimmed) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/api/v1/prices/${encodeURIComponent(trimmed)}`, {
        method: "DELETE"
      });
      if (!response.ok) {
        throw new Error(`DELETE Preis: HTTP ${response.status}`);
      }
      const body = (await response.json()) as ApiResponse<Record<string, unknown>>;
      if (body.status === "error") {
        throw new Error(body.errors.map((item) => item.message).join(", "));
      }
      const deleted = body.data?.deleted === true;
      setNotice(deleted ? `Preis geloescht: ${trimmed}` : `Preis nicht gefunden: ${trimmed}`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Preis konnte nicht geloescht werden");
      setLoading(false);
    }
  }

  async function createPdfExport(label: string, estimatedPages: string) {
    setLoading(true);
    setError(null);
    try {
      await postApi("/api/v1/export/pdf", {
        label,
        estimated_pages: Number.parseInt(estimatedPages, 10)
      });
      setNotice("PDF-Exportpakete erzeugt");
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "PDF-Export fehlgeschlagen");
      setLoading(false);
    }
  }

  async function runReportAction(path: string, label: string) {
    setLoading(true);
    setError(null);
    try {
      await postApi(path);
      setNotice(`${label} erzeugt`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : `${label} fehlgeschlagen`);
      setLoading(false);
    }
  }

  async function deleteExportPackage(packageId: string) {
    const trimmed = packageId.trim();
    if (!trimmed) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/api/v1/export/packages/${encodeURIComponent(trimmed)}`, {
        method: "DELETE"
      });
      if (!response.ok) {
        throw new Error(`DELETE Exportpaket: HTTP ${response.status}`);
      }
      const body = (await response.json()) as ApiResponse<Record<string, unknown>>;
      if (body.status === "error") {
        throw new Error(body.errors.map((item) => item.message).join(", "));
      }
      const deleted = body.data?.deleted === true;
      setNotice(deleted ? `Exportpaket geloescht: ${trimmed}` : `Exportpaket nicht gefunden: ${trimmed}`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Exportpaket konnte nicht geloescht werden");
      setLoading(false);
    }
  }

  async function rebuildPipeline() {
    setLoading(true);
    setError(null);
    try {
      await postApi("/api/v1/pipeline/rebuild");
      setNotice("Pipeline neu berechnet");
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Pipeline-Rebuild fehlgeschlagen");
      setLoading(false);
    }
  }

  async function seedDemo() {
    setLoading(true);
    setError(null);
    try {
      await postApi("/api/v1/demo/seed");
      setNotice("Demo-Daten geladen");
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Demo-Daten konnten nicht geladen werden");
      setLoading(false);
    }
  }

  async function saveAdminSetting(key: string, valueJson: string) {
    const trimmedKey = key.trim();
    if (!trimmedKey) {
      setError("Setting-Key darf nicht leer sein");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await patchApi("/api/v1/admin/settings", {
        key: trimmedKey,
        value_json: valueJson
      });
      setNotice(`Setting gespeichert: ${trimmedKey}`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Setting konnte nicht gespeichert werden");
      setLoading(false);
    }
  }

  async function saveCexCredentials(connectorId: string, apiKey: string, apiSecret: string, passphrase: string) {
    setLoading(true);
    setError(null);
    try {
      const result = await postApi<Record<string, unknown>>("/api/v1/admin/cex-credentials", {
        connector_id: connectorId,
        api_key: apiKey,
        api_secret: apiSecret,
        passphrase
      });
      setNotice(`CEX-Credentials gespeichert: ${String(result.connector_id ?? connectorId)} (${sourceCredentialStatusLabel(result.credential_status)})`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "CEX-Credentials konnten nicht gespeichert werden");
      setLoading(false);
    }
  }

  async function saveJupiterApiKey(apiKey: string) {
    if (!apiKey.trim()) {
      setError("Jupiter API-Key darf nicht leer sein");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await postApi<Record<string, unknown>>("/api/v1/admin/jupiter/api-key", {
        api_key: apiKey
      });
      setNotice("Jupiter API-Key gespeichert");
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Jupiter API-Key konnte nicht gespeichert werden");
      setLoading(false);
    }
  }

  async function searchJupiterTokens(query: string) {
    const trimmed = query.trim();
    if (!trimmed) {
      setError("Jupiter Token-Suche braucht Symbol, Name oder Mint-Adresse");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await getApi<Snapshot["jupiterTokenSearch"]>(
        `/api/v1/sources/jupiter/tokens/search?query=${encodeURIComponent(trimmed)}`
      );
      setSnapshot((current) => ({ ...current, jupiterTokenSearch: result }));
      setNotice(`Jupiter Token-Suche: ${result?.tokens_count ?? 0} Treffer`);
      setLoading(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Jupiter Token-Suche fehlgeschlagen");
      setLoading(false);
    }
  }

  async function refreshJupiterMetadataCache(limit = 50, force = false) {
    setLoading(true);
    setError(null);
    try {
      const result = await postApi<Snapshot["jupiterMetadataCache"]>(
        `/api/v1/sources/jupiter/tokens/metadata-cache/refresh?limit=${encodeURIComponent(String(limit))}&force=${force ? "true" : "false"}`,
        undefined,
        60000
      );
      setSnapshot((current) => ({ ...current, jupiterMetadataCache: result }));
      setNotice(`Jupiter Metadata-Cache: ${result?.refreshed_count ?? 0} aktualisiert, ${result?.cached_count ?? 0} gecacht`);
      setLoading(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Jupiter Metadata-Cache konnte nicht aktualisiert werden");
      setLoading(false);
    }
  }

  async function importV1CexCredentials() {
    setLoading(true);
    setError(null);
    try {
      const result = await postApi<Record<string, unknown>>("/api/v1/admin/cex-credentials/v1-takeover", {});
      const imported = Array.isArray(result.imported) ? result.imported.length : 0;
      const skipped = Array.isArray(result.skipped) ? result.skipped.length : 0;
      setNotice(`V1-CEX-Credentials Uebernahme: ${imported} uebernommen, ${skipped} nicht uebernehmbar`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "V1-CEX-Credentials konnten nicht uebernommen werden");
      setLoading(false);
    }
  }

  async function createAiTask(taskType: string, prompt: string, allowExternal: boolean) {
    if (!prompt.trim()) {
      setError("KI-Prompt darf nicht leer sein");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const task = await postApi<Record<string, unknown>>("/api/v1/ai/tasks", {
        task_type: taskType,
        prompt,
        allow_external: allowExternal
      });
      setNotice(`KI-Aufgabe erstellt: ${String(task.task_id ?? "-")} (${String(task.status ?? "-")})`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "KI-Aufgabe konnte nicht erstellt werden");
      setLoading(false);
    }
  }

  async function deleteAiTask(taskId: string) {
    const trimmed = taskId.trim();
    if (!trimmed) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/api/v1/ai/tasks/${encodeURIComponent(trimmed)}`, {
        method: "DELETE"
      });
      if (!response.ok) {
        throw new Error(`DELETE KI-Aufgabe: HTTP ${response.status}`);
      }
      const body = (await response.json()) as ApiResponse<Record<string, unknown>>;
      if (body.status === "error") {
        throw new Error(body.errors.map((item) => item.message).join(", "));
      }
      const deleted = body.data?.deleted === true;
      setNotice(deleted ? `KI-Aufgabe geloescht: ${trimmed}` : `KI-Aufgabe nicht gefunden: ${trimmed}`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "KI-Aufgabe konnte nicht geloescht werden");
      setLoading(false);
    }
  }

  async function deleteAdminSetting(key: string) {
    const trimmed = key.trim();
    if (!trimmed) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/api/v1/admin/settings/${encodeURIComponent(trimmed)}`, {
        method: "DELETE"
      });
      if (!response.ok) {
        throw new Error(`DELETE Setting: HTTP ${response.status}`);
      }
      const body = (await response.json()) as ApiResponse<Record<string, unknown>>;
      if (body.status === "error") {
        throw new Error(body.errors.map((item) => item.message).join(", "));
      }
      const deleted = body.data?.deleted === true;
      setNotice(deleted ? `Setting geloescht: ${trimmed}` : `Setting nicht gefunden: ${trimmed}`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Setting konnte nicht geloescht werden");
      setLoading(false);
    }
  }

  async function addV1Reference(payload: Record<string, unknown>) {
    setLoading(true);
    setError(null);
    try {
      await postApi("/api/v1/parity/v1/references", payload);
      setNotice("V1-Referenzwert gespeichert");
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "V1-Referenzwert konnte nicht gespeichert werden");
      setLoading(false);
    }
  }

  async function addParityDecision(scope: string, decisionStatus: string) {
    setLoading(true);
    setError(null);
    try {
      await postApi("/api/v1/parity/decisions", {
        scope,
        decision_status: decisionStatus,
        title: `Parity-Entscheidung: ${decisionStatus}`,
        rationale: "In der V2-Oberflaeche gesetzte Review-Entscheidung. Belege muessen im Audit nachgefuehrt werden.",
        evidence_ref: "ui:parity"
      });
      setNotice(`Parity-Entscheidung gespeichert: ${decisionStatus}`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Parity-Entscheidung konnte nicht gespeichert werden");
      setLoading(false);
    }
  }

  async function addCexSenderOwnershipDecision(row: Record<string, unknown>, decisionStatus: string) {
    const txid = String(row.txid_full ?? row.txid ?? "").trim();
    if (!txid) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await postApiResponse<Record<string, unknown>>(
        `/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/cex-sender-ownership-decisions?cex=binance&network=SOL`,
        {
          txid,
          decision_status: decisionStatus,
          title: decisionStatus === "tax_neutral_transfer_reviewed"
            ? "CEX Deposit als steuerneutralen Transfer dokumentiert"
            : "CEX Deposit Sender bleibt ungeprueft",
          rationale: "In der V2-Oberflaeche gesetzte Review-Entscheidung. Dokumentiert den fachlichen Status ohne FIFO-, Ledger- oder Steuerzeilen zu veraendern."
        }
      );
      if (response.status === "error") {
        throw new Error(response.errors.map((item) => item.message).join(", "));
      }
      setNotice(`CEX Sender Ownership gespeichert: ${decisionStatus}`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "CEX Sender Ownership konnte nicht gespeichert werden");
      setLoading(false);
    }
  }

  async function acceptReviewSuggestion(suggestionId: string) {
    const trimmed = suggestionId.trim();
    if (!trimmed) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await postApiResponse<Record<string, unknown>>(
        `/api/v1/review/decision-suggestions/${encodeURIComponent(trimmed)}/accept`
      );
      if (response.status === "error") {
        throw new Error(response.errors.map((item) => item.message).join(", "));
      }
      setNotice(
        response.status === "warning"
          ? "Review-Vorschlag war bereits uebernommen"
          : "Review-Vorschlag als Entscheidung gespeichert"
      );
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Review-Vorschlag konnte nicht uebernommen werden");
      setLoading(false);
    }
  }

  async function canonicalizeReviewEvidenceTraces(execute: boolean) {
    if (execute && !window.confirm("Review-Beleglinks wirklich auf kanonische Evidence-Traces setzen?")) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await postApiResponse<Record<string, unknown>>(
        "/api/v1/review/evidence-traces/canonicalize",
        { execute }
      );
      const data = response.data;
      setNotice(
        execute
          ? `Review-Beleglinks kanonisiert: ${String(data.updated_count ?? 0)} Entscheidung(en)`
          : `Review-Beleglink Dry-run: ${String(data.candidates_count ?? 0)} Kandidat(en)`
      );
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Review-Beleglinks konnten nicht kanonisiert werden");
      setLoading(false);
    }
  }

  async function deleteV1Reference(referenceId: string) {
    const trimmed = referenceId.trim();
    if (!trimmed) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${API_BASE}/api/v1/parity/v1/references/${encodeURIComponent(trimmed)}`, {
        method: "DELETE"
      });
      if (!response.ok) {
        throw new Error(`DELETE V1-Referenz: HTTP ${response.status}`);
      }
      const body = (await response.json()) as ApiResponse<Record<string, unknown>>;
      if (body.status === "error") {
        throw new Error(body.errors.map((item) => item.message).join(", "));
      }
      const deleted = body.data?.deleted === true;
      setNotice(deleted ? `V1-Referenz geloescht: ${trimmed}` : `V1-Referenz nicht gefunden: ${trimmed}`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "V1-Referenz konnte nicht geloescht werden");
      setLoading(false);
    }
  }

  function download(path: string) {
    window.open(`${API_BASE}${path}`, "_blank", "noopener,noreferrer");
  }

  useEffect(() => {
    void refresh();
  }, [active, flowYear, asOfDate, selectedSourceId, selectedTaxYear, taxViewMode, portfolioViewMode, tokenRiskFilter, sourceViewMode, exportViewMode, reviewViewMode, importViewMode]);

  return (
    <main className="shell">
      <aside className="sidebar">
        <div className="brand">
          <strong>Steuerreport V2</strong>
          <span>DuckDB Ledger</span>
        </div>
        <nav>
          {(["workflow", "evidence", "expert"] as const).map((group) => (
            <div className="navGroup" key={group}>
              <span className="navGroupLabel">
                {group === "workflow" ? "Arbeitsablauf" : group === "evidence" ? "Belege" : "Werkzeuge"}
              </span>
              {navItems.filter((item) => item.group === group).map((item) => (
                <button
                  key={item.id}
                  className={`${active === item.id ? "active" : ""} ${item.group === "expert" ? "expertNav" : ""}`}
                  onClick={() => setActive(item.id)}
                  type="button"
                  title={item.description}
                >
                  {item.icon}
                  <span>{item.label}</span>
                </button>
              ))}
            </div>
          ))}
        </nav>
      </aside>
      <section className="workspace">
        <header className="topbar">
          <div>
            <h1>{activeLabel}</h1>
            <p>{activeDescription} · {API_BASE}</p>
          </div>
          <button className="statusButton" type="button" onClick={refresh}>
            <RefreshCcw size={16} />
            {loading ? "Laedt" : "Aktualisieren"}
          </button>
        </header>
        {error ? <div className="error">{error}</div> : null}
        {notice ? <div className="notice">{notice}</div> : null}
        <LoadingStatusPanel loading={loading} statuses={loaderStatuses} />
        <Content
          active={active}
          snapshot={snapshot}
          onRebuildFlows={rebuildFlows}
          onRebuildTax={rebuildTax}
          onRebuildDerivatives={rebuildDerivatives}
          onImportCsv={importCsv}
          onDeleteImportBatch={deleteImportBatch}
          onRunImportBatch={runImportBatch}
          onAddPrice={addPrice}
          onImportPriceCsv={importPriceCsv}
          onImportV1FxCache={importV1FxCache}
          onBackfillExternalPrices={backfillExternalPrices}
          onBackfillCurrentPortfolioPrices={backfillCurrentPortfolioPrices}
          onAddPriceGapDecision={addPriceGapDecision}
          onAddPriceQualityDecision={addPriceQualityDecision}
          onDeletePricePoint={deletePricePoint}
          onCreatePdfExport={createPdfExport}
          onRunReportAction={runReportAction}
          onDeleteExportPackage={deleteExportPackage}
          onRebuildPipeline={rebuildPipeline}
          onSeedDemo={seedDemo}
          onDownload={download}
          onSaveAdminSetting={saveAdminSetting}
          onSaveCexCredentials={saveCexCredentials}
          onSaveJupiterApiKey={saveJupiterApiKey}
          onSearchJupiterTokens={searchJupiterTokens}
          onRefreshJupiterMetadataCache={refreshJupiterMetadataCache}
          onImportV1CexCredentials={importV1CexCredentials}
          onDeleteAdminSetting={deleteAdminSetting}
          onAddV1Reference={addV1Reference}
          onAddParityDecision={addParityDecision}
          onAddCexSenderOwnershipDecision={addCexSenderOwnershipDecision}
          onDeleteV1Reference={deleteV1Reference}
          onAcceptReviewSuggestion={acceptReviewSuggestion}
          onCanonicalizeReviewEvidenceTraces={canonicalizeReviewEvidenceTraces}
          onCreateAiTask={createAiTask}
          onDeleteAiTask={deleteAiTask}
          onNavigate={setActive}
          onRefreshConfiguredSources={refreshConfiguredSources}
          sourceRefreshLoading={sourceRefreshLoading}
          selectedSourceId={selectedSourceId}
          onSelectedSourceIdChange={setSelectedSourceId}
          sourceViewMode={sourceViewMode}
          onSourceViewModeChange={setSourceViewMode}
          selectedTaxYear={selectedTaxYear}
          onSelectedTaxYearChange={setSelectedTaxYear}
          taxViewMode={taxViewMode}
          onTaxViewModeChange={setTaxViewMode}
          portfolioViewMode={portfolioViewMode}
          onPortfolioViewModeChange={setPortfolioViewMode}
          tokenRiskFilter={tokenRiskFilter}
          onTokenRiskFilterChange={setTokenRiskFilter}
          exportViewMode={exportViewMode}
          onExportViewModeChange={setExportViewMode}
          reviewViewMode={reviewViewMode}
          onReviewViewModeChange={setReviewViewMode}
          importViewMode={importViewMode}
          onImportViewModeChange={setImportViewMode}
          flowYear={flowYear}
          onFlowYearChange={setFlowYear}
          asOfDate={asOfDate}
          onAsOfDateChange={setAsOfDate}
          minHoldingValueEur={minHoldingValueEur}
          onMinHoldingValueEurChange={setMinHoldingValueEur}
          jupiterTokenQuery={jupiterTokenQuery}
          onJupiterTokenQueryChange={setJupiterTokenQuery}
        />
      </section>
    </main>
  );
}

function LoadingStatusPanel({ loading, statuses }: { loading: boolean; statuses: LoaderStatus[] }) {
  if (statuses.length === 0) {
    return null;
  }
  const done = statuses.filter((item) => item.status === "ok" || item.status === "error").length;
  const failed = statuses.filter((item) => item.status === "error").length;
  const active = statuses.find((item) => item.status === "loading") ?? statuses.find((item) => item.status === "pending");
  const slowStatuses = statuses
    .filter((item) => item.status === "ok" && Number(item.duration_ms ?? 0) >= 5000)
    .sort((left, right) => Number(right.duration_ms ?? 0) - Number(left.duration_ms ?? 0));
  if (!loading && failed === 0 && slowStatuses.length === 0) {
    return null;
  }
  const progress = Math.round((done / statuses.length) * 100);
  const slowSummary = slowStatuses
    .slice(0, 3)
    .map((item) => `${item.label} ${formatDurationMs(item.duration_ms)}`)
    .join(" · ");
  return (
    <section className={`loadingPanel ${failed > 0 ? "hasFailures" : ""}`} aria-live="polite">
      <div className="loadingPanelHeader">
        <div>
          <strong>
            {loading
              ? `Daten werden geladen (${done}/${statuses.length})`
              : failed > 0
                ? `Teilweise geladen (${done}/${statuses.length})`
                : `Geladen (${done}/${statuses.length})`}
          </strong>
          <span>
            {active
              ? `Aktuell: ${active.label}`
              : failed > 0
                ? `${failed} Datenpaket(e) fehlgeschlagen`
                : slowSummary
                  ? `Langsame Pakete: ${slowSummary}`
                  : "Abgeschlossen"}
          </span>
        </div>
        <span className="loadingPercent">{progress}%</span>
      </div>
      <div className="loadingTrack">
        <div style={{ width: `${progress}%` }} />
      </div>
      <div className="loadingStepList">
        {statuses.map((item) => (
          <span key={String(item.key)} className={`loadingStep ${item.status}`} title={item.detail ?? item.label}>
            {item.label}
            {item.duration_ms ? <span className="loadingStepDuration">{formatDurationMs(item.duration_ms)}</span> : null}
          </span>
        ))}
      </div>
    </section>
  );
}

function Content({
  active,
  snapshot,
  onRebuildFlows,
  onRebuildTax,
  onRebuildDerivatives,
  onImportCsv,
  onDeleteImportBatch,
  onRunImportBatch,
  onAddPrice,
  onImportPriceCsv,
  onImportV1FxCache,
  onBackfillExternalPrices,
  onBackfillCurrentPortfolioPrices,
  onAddPriceGapDecision,
  onAddPriceQualityDecision,
  onDeletePricePoint,
  onCreatePdfExport,
  onRunReportAction,
  onDeleteExportPackage,
  onRebuildPipeline,
  onSeedDemo,
  onDownload,
  onSaveAdminSetting,
  onSaveCexCredentials,
  onSaveJupiterApiKey,
  onSearchJupiterTokens,
  onRefreshJupiterMetadataCache,
  onImportV1CexCredentials,
  onDeleteAdminSetting,
  onAddV1Reference,
  onAddParityDecision,
  onAddCexSenderOwnershipDecision,
  onDeleteV1Reference,
  onAcceptReviewSuggestion,
  onCanonicalizeReviewEvidenceTraces,
  onCreateAiTask,
  onDeleteAiTask,
  onNavigate,
  onRefreshConfiguredSources,
  sourceRefreshLoading,
  selectedSourceId,
  onSelectedSourceIdChange,
  sourceViewMode,
  onSourceViewModeChange,
  selectedTaxYear,
  onSelectedTaxYearChange,
  taxViewMode,
  onTaxViewModeChange,
  portfolioViewMode,
  onPortfolioViewModeChange,
  tokenRiskFilter,
  onTokenRiskFilterChange,
  exportViewMode,
  onExportViewModeChange,
  reviewViewMode,
  onReviewViewModeChange,
  importViewMode,
  onImportViewModeChange,
  flowYear,
  onFlowYearChange,
  asOfDate,
  onAsOfDateChange,
  minHoldingValueEur,
  onMinHoldingValueEurChange,
  jupiterTokenQuery,
  onJupiterTokenQueryChange
}: {
  active: Section;
  snapshot: Snapshot;
  onRebuildFlows: () => void;
  onRebuildTax: () => void;
  onRebuildDerivatives: () => void;
  onImportCsv: (
    source: string,
    filename: string,
    content: string,
    contentBase64?: string | null,
    sheetName?: string | null
  ) => void;
  onDeleteImportBatch: (batchId: string) => void;
  onRunImportBatch: (batchId: string) => void;
  onAddPrice: (asset: string, priceEur: string, pricedAt: string, source: string, confidence: string) => void;
  onImportPriceCsv: (content: string, defaultSource: string) => void;
  onImportV1FxCache: (dbPath: string, confidence: string) => void;
  onBackfillExternalPrices: (maxRequests: string, provider: string, dryRun: boolean, assets: string) => void;
  onBackfillCurrentPortfolioPrices: (maxRequests: string, dryRun: boolean, assets: string) => void;
  onAddPriceGapDecision: (scope: string, decisionStatus: string) => void;
  onAddPriceQualityDecision: (row: Record<string, unknown>, decisionStatus: string) => void;
  onDeletePricePoint: (priceId: string) => void;
  onCreatePdfExport: (label: string, estimatedPages: string) => void;
  onRunReportAction: (path: string, label: string) => void;
  onDeleteExportPackage: (packageId: string) => void;
  onRebuildPipeline: () => void;
  onSeedDemo: () => void;
  onDownload: (path: string) => void;
  onSaveAdminSetting: (key: string, valueJson: string) => void;
  onSaveCexCredentials: (connectorId: string, apiKey: string, apiSecret: string, passphrase: string) => void;
  onSaveJupiterApiKey: (apiKey: string) => void;
  onSearchJupiterTokens: (query: string) => void;
  onRefreshJupiterMetadataCache: (limit?: number, force?: boolean) => void;
  onImportV1CexCredentials: () => void;
  onDeleteAdminSetting: (key: string) => void;
  onAddV1Reference: (payload: Record<string, unknown>) => void;
  onAddParityDecision: (scope: string, decisionStatus: string) => void;
  onAddCexSenderOwnershipDecision: (row: Record<string, unknown>, decisionStatus: string) => void;
  onDeleteV1Reference: (referenceId: string) => void;
  onAcceptReviewSuggestion: (suggestionId: string) => void;
  onCanonicalizeReviewEvidenceTraces: (execute: boolean) => void;
  onCreateAiTask: (taskType: string, prompt: string, allowExternal: boolean) => void;
  onDeleteAiTask: (taskId: string) => void;
  onNavigate: (section: Section) => void;
  onRefreshConfiguredSources: () => void;
  sourceRefreshLoading: boolean;
  selectedSourceId: string | null;
  onSelectedSourceIdChange: (sourceId: string) => void;
  sourceViewMode: SourceViewMode;
  onSourceViewModeChange: (mode: SourceViewMode) => void;
  selectedTaxYear: string;
  onSelectedTaxYearChange: (year: string) => void;
  taxViewMode: TaxViewMode;
  onTaxViewModeChange: (mode: TaxViewMode) => void;
  portfolioViewMode: PortfolioViewMode;
  onPortfolioViewModeChange: (mode: PortfolioViewMode) => void;
  tokenRiskFilter: TokenRiskFilter;
  onTokenRiskFilterChange: (mode: TokenRiskFilter) => void;
  exportViewMode: ExportViewMode;
  onExportViewModeChange: (mode: ExportViewMode) => void;
  reviewViewMode: ReviewViewMode;
  onReviewViewModeChange: (mode: ReviewViewMode) => void;
  importViewMode: ImportViewMode;
  onImportViewModeChange: (mode: ImportViewMode) => void;
  flowYear: string;
  onFlowYearChange: (year: string) => void;
  asOfDate: string;
  onAsOfDateChange: (date: string) => void;
  minHoldingValueEur: string;
  onMinHoldingValueEurChange: (value: string) => void;
  jupiterTokenQuery: string;
  onJupiterTokenQueryChange: (query: string) => void;
}) {
  if (active === "dashboard") {
    return (
      <CockpitDashboard
        summary={snapshot.cockpit}
        database={snapshot.health}
        onNavigate={onNavigate}
        onRebuildPipeline={onRebuildPipeline}
        onRefreshConfiguredSources={onRefreshConfiguredSources}
        sourceRefreshLoading={sourceRefreshLoading}
      />
    );
  }

  if (active === "sources") {
    return (
        <SourcesPage
          overview={snapshot.sourcesOverview}
          connectorDiagnostics={snapshot.sourceConnectorDiagnostics}
          detail={snapshot.sourceDetail}
          sourceReconciliation={snapshot.sourceReconciliation}
          sourceReconciliationEvidence={snapshot.sourceReconciliationEvidence}
          binanceEarnHistoryPreflight={snapshot.binanceEarnHistoryPreflight}
          binanceEarnHistoryApiPreview={snapshot.binanceEarnHistoryApiPreview}
          selectedSourceId={selectedSourceId}
          onSelectedSourceIdChange={onSelectedSourceIdChange}
          onRefreshConfiguredSources={onRefreshConfiguredSources}
          sourceRefreshLoading={sourceRefreshLoading}
          sourceViewMode={sourceViewMode}
          onSourceViewModeChange={onSourceViewModeChange}
        />
    );
  }

  if (active === "import") {
    return (
      <Stack>
        <div className="taxViewSwitch" role="tablist" aria-label="Import Ansicht">
          <button type="button" className={importViewMode === "assistant" ? "active" : ""} onClick={() => onImportViewModeChange("assistant")}>
            Assistent
          </button>
          <button type="button" className={importViewMode === "preflight" ? "active" : ""} onClick={() => onImportViewModeChange("preflight")}>
            Preflights
          </button>
          <button type="button" className={importViewMode === "expert" ? "active" : ""} onClick={() => onImportViewModeChange("expert")}>
            Expertenmodus
          </button>
        </div>
        <ImportForm onImportCsv={onImportCsv} />
        {importViewMode !== "assistant" ? (
          <>
            <ImportCoveragePanel coverage={snapshot.importCoverage} />
            <ParserPreflightPanel preflight={snapshot.parserPreflight} />
            <BlockpitSolanaPreflightPanel report={snapshot.blockpitSolanaPreflight} />
            <SolscanTokenPreflightPanel report={snapshot.solscanTokenPreflight} />
            <WalletMonthlyPreflightPanel report={snapshot.walletMonthlyPreflight} />
          </>
        ) : null}
        {importViewMode === "expert" ? (
          <>
        <DeleteImportForm onDeleteImportBatch={onDeleteImportBatch} />
        <TablePanel title="Import-Profile" rows={snapshot.importProfiles ?? []} />
        <TablePanel
          title="Import-Batches"
          rows={snapshot.imports ?? []}
          rowActions={[
            {
              label: "Pipeline ausfuehren",
              icon: <RefreshCcw size={16} />,
              onClick: (row) => onRunImportBatch(String(row.batch_id ?? ""))
            },
            {
              label: "Import entfernen",
              icon: <Trash2 size={16} />,
              tone: "danger",
              onClick: (row) => onDeleteImportBatch(String(row.batch_id ?? ""))
            }
          ]}
        />
        <BatchTracePanel
          imports={snapshot.imports ?? []}
          rawObjects={snapshot.rawObjects ?? []}
          canonicalEvents={snapshot.canonicalEvents ?? []}
          onDownload={onDownload}
        />
          </>
        ) : null}
      </Stack>
    );
  }
  if (active === "portfolio") {
    return (
      <Stack>
        <PortfolioDecisionPanel
          portfolio={snapshot.portfolio}
          sources={snapshot.portfolioSources}
          holdingPeriods={snapshot.taxHoldingPeriods}
          priceCoverage={snapshot.priceCoverage}
          onDownload={onDownload}
        />
        <div className="taxViewSwitch" role="tablist" aria-label="Portfolio Ansicht">
          <button
            type="button"
            className={portfolioViewMode === "overview" ? "active" : ""}
            onClick={() => onPortfolioViewModeChange("overview")}
          >
            Uebersicht
          </button>
          <button
            type="button"
            className={portfolioViewMode === "reconciliation" ? "active" : ""}
            onClick={() => onPortfolioViewModeChange("reconciliation")}
          >
            Live-Abgleich
          </button>
          <button
            type="button"
            className={portfolioViewMode === "expert" ? "active" : ""}
            onClick={() => onPortfolioViewModeChange("expert")}
          >
            Expertenmodus
          </button>
        </div>
        <PortfolioSourcesPanel overview={snapshot.portfolioSources} />
        <PortfolioTokenRiskPanel
          report={snapshot.portfolioTokenRisk}
          reviewDecisions={snapshot.reviewDecisions}
          filter={tokenRiskFilter}
          onFilterChange={onTokenRiskFilterChange}
          onDownload={onDownload}
        />
        <PortfolioBreakdownPanel portfolio={snapshot.portfolio} />
        <TablePanel
          title="Portfolio nach Asset"
          rows={snapshot.portfolio?.asset_summary ?? []}
          footer={`Summe: ${formatCurrency(snapshot.portfolio?.total_value_eur)} EUR | Fehlende Preise: ${(snapshot.portfolio?.missing_price_assets ?? []).join(", ") || "keine"}`}
        />
        <TablePanel
          title="Portfolio nach Konto"
          rows={snapshot.portfolio?.account_summary ?? []}
          footer="Bewertung je Konto/Wallet nach aktuellen Portfolio-Positionen."
        />
        <TablePanel
          title="Aus Portfolio ausgeklammerte Quellkonten"
          rows={snapshot.portfolio?.excluded_account_summary ?? []}
          footer={`Nicht geloescht, nur nicht als aktueller Bestand gewertet. Ausgeklammerter Wert: ${formatCurrency(snapshot.portfolio?.excluded_value_eur)} EUR`}
        />
        {portfolioViewMode !== "overview" ? (
          <>
            <PortfolioReconciliationPanel report={snapshot.portfolioReconciliation} />
            <PortfolioValuationAuditPanel report={snapshot.portfolioValuationAudit} />
            <TablePanel
              title={String(snapshot.portfolio?.separation_virtual_wallet?.label ?? "Virtuelle Wallet: Neubestand ab 13.06.2025")}
              rows={snapshot.portfolio?.separation_virtual_wallet?.positions ?? []}
              footer={`Stichtag: ${snapshot.portfolio?.separation_virtual_wallet?.cutoff_date ?? "2025-06-13"} | Gesamtwert: ${formatCurrency(snapshot.portfolio?.separation_virtual_wallet?.total_value_eur)} EUR | Fehlende Preise: ${(snapshot.portfolio?.separation_virtual_wallet?.missing_price_assets ?? []).join(", ") || "keine"}`}
            />
            <FiatDepositPanel report={snapshot.fiatDeposits} onDownload={onDownload} />
            <SeparationTrendPanel report={snapshot.separationReport} />
          </>
        ) : null}
        {portfolioViewMode === "expert" ? (
          <>
            <PriceForm onAddPrice={onAddPrice} />
            <PriceCsvImportForm onImportPriceCsv={onImportPriceCsv} />
            <V1FxCacheImportForm onImportV1FxCache={onImportV1FxCache} />
            <ExternalPriceBackfillForm onBackfillExternalPrices={onBackfillExternalPrices} />
            <CurrentPortfolioPriceBackfillForm onBackfillCurrentPortfolioPrices={onBackfillCurrentPortfolioPrices} />
            <PriceCoveragePanel
              coverage={snapshot.priceCoverage}
              requirements={snapshot.priceRequirements}
              onAddPriceGapDecision={onAddPriceGapDecision}
            />
            <PriceQualityPanel
              quality={snapshot.priceQuality}
              manualReview={snapshot.priceManualReview}
              stablecoinFxReview={snapshot.priceStablecoinFxReview}
              solscanSignatureReview={snapshot.priceSolscanSignatureReview}
              binanceNormalizerReview={snapshot.priceBinanceNormalizerReview}
              eventQuoteEvidenceReview={snapshot.priceEventQuoteEvidenceReview}
              onDownload={onDownload}
              onAddDecision={onAddPriceQualityDecision}
            />
            <TablePanel
              title="Portfolio-Positionen"
              rows={snapshot.portfolio?.positions ?? []}
              footer={`Fehlende Preise: ${(snapshot.portfolio?.missing_price_assets ?? []).join(", ") || "keine"} | Aufgeloeste Account-Aliase: ${snapshot.portfolio?.resolved_account_aliases?.length ?? 0} | Unaufgeloeste gekuerzte Accounts: ${snapshot.portfolio?.unresolved_truncated_accounts?.length ?? 0}`}
            />
            <TablePanel
              title="Aufgeloeste Account-Aliase"
              rows={snapshot.portfolio?.resolved_account_aliases ?? []}
            />
            <TablePanel
              title="Unaufgeloeste gekuerzte Accounts"
              rows={(snapshot.portfolio?.unresolved_truncated_accounts ?? []).map((account) => ({ account }))}
            />
            <TablePanel title="Wirksame Preise" rows={snapshot.latestPrices ?? []} />
            <TablePanel
              title="Preis-Ledger"
              rows={snapshot.prices ?? []}
              rowActions={[
                {
                  label: "Preis entfernen",
                  icon: <Trash2 size={16} />,
                  tone: "danger",
                  onClick: (row) => onDeletePricePoint(String(row.price_id ?? ""))
                }
              ]}
            />
          </>
        ) : null}
      </Stack>
    );
  }
  if (active === "stichtage") {
    return (
      <PortfolioAsOfPage
        snapshot={snapshot.portfolioAsOf}
        asOfDate={asOfDate}
        onAsOfDateChange={onAsOfDateChange}
      />
    );
  }
  if (active === "flows") {
    return (
      <Stack>
        <FlowSankeyPanel
          flows={snapshot.flows}
          flowYear={flowYear}
          onFlowYearChange={onFlowYearChange}
          onRebuildFlows={onRebuildFlows}
        />
        <TransferCandidatesPanel report={snapshot.transferCandidates} />
        <TablePanel
          title="Sankey-Netto-Kanten"
          rows={snapshot.flows?.edges ?? []}
          footer={`Fehlende Preise: ${(snapshot.flows?.missing_price_assets ?? []).join(", ") || "keine"}`}
        />
      </Stack>
    );
  }
  if (active === "review") {
    return (
      <Stack>
        <ReviewPanel
          review={snapshot.review}
          reviewTasks={snapshot.reviewTasks}
          jupiterRiskReview={snapshot.jupiterRiskReview}
          decisions={snapshot.reviewDecisions ?? []}
          suggestions={snapshot.reviewDecisionSuggestions ?? []}
          evidenceTraces={snapshot.reviewEvidenceTraces}
          reviewViewMode={reviewViewMode}
          onReviewViewModeChange={onReviewViewModeChange}
          onAcceptSuggestion={onAcceptReviewSuggestion}
          onCanonicalizeEvidenceTraces={onCanonicalizeReviewEvidenceTraces}
          onDownload={onDownload}
        />
        {reviewViewMode !== "tasks" ? <BlockpitSolanaPreflightPanel report={snapshot.blockpitSolanaPreflight} /> : null}
        {reviewViewMode === "expert" ? <SolscanTokenPreflightPanel report={snapshot.solscanTokenPreflight} /> : null}
        {reviewViewMode === "expert" ? <WalletMonthlyPreflightPanel report={snapshot.walletMonthlyPreflight} /> : null}
      </Stack>
    );
  }
  if (active === "parity") {
    return (
        <ParityPanel
          parity={snapshot.parity}
          diagnostics={snapshot.parityDiagnostics}
          releaseReadiness={snapshot.parityReleaseReadiness}
          references={snapshot.parityReferences ?? []}
          hntFifoProvenance={snapshot.hntFifoProvenance}
          onAddV1Reference={onAddV1Reference}
          onAddParityDecision={onAddParityDecision}
          onDeleteV1Reference={onDeleteV1Reference}
          onDownload={onDownload}
      />
    );
  }
  if (active === "tax") {
    return (
      <TaxPanel
        taxSummary={snapshot.taxSummary}
        taxHoldingPeriods={snapshot.taxHoldingPeriods}
        taxLossRealizationPlanner={snapshot.taxLossRealizationPlanner}
        taxYearsSummary={snapshot.taxYearsSummary}
        taxPaymentOverview={snapshot.taxPaymentOverview}
        taxYearFilingMatrix={snapshot.taxYearFilingMatrix}
        taxFilingClosureOverview={snapshot.taxFilingClosureOverview}
        taxYearsCorrectionMap={snapshot.taxYearsCorrectionMap}
        taxMethodologySummary={snapshot.taxMethodologySummary}
        taxBmfActionPlan={snapshot.taxBmfActionPlan}
        taxYearDetail={snapshot.taxYearDetail}
        taxDeclarationGuide={snapshot.taxDeclarationGuide}
        taxYearFilingSummary={snapshot.taxYearFilingSummary}
        taxYearCorrectionMap={snapshot.taxYearCorrectionMap}
        taxYearMethodology={snapshot.taxYearMethodology}
        taxYearWalletFifoDelta={snapshot.taxYearWalletFifoDelta}
        taxYearWalletFifoGaps={snapshot.taxYearWalletFifoGaps}
        taxYearWalletFifoOriginTrace={snapshot.taxYearWalletFifoOriginTrace}
        taxYearCexDepositTransferEvidence={snapshot.taxYearCexDepositTransferEvidence}
        taxYearCexSenderOwnershipLatest={snapshot.taxYearCexSenderOwnershipLatest}
        taxYearCexExchangeOutflowEvidence={snapshot.taxYearCexExchangeOutflowEvidence}
        taxYearCexExchangeOutflowAnchorFeasibility={snapshot.taxYearCexExchangeOutflowAnchorFeasibility}
        taxYearWalletFifoProvenanceClosure={snapshot.taxYearWalletFifoProvenanceClosure}
        taxYearWalletFifoProvenancePriorities={snapshot.taxYearWalletFifoProvenancePriorities}
        taxYearWalletFifoRawProvenanceBreakdown={snapshot.taxYearWalletFifoRawProvenanceBreakdown}
        taxYearWalletFifoExchangeEvidenceGaps={snapshot.taxYearWalletFifoExchangeEvidenceGaps}
        taxYearWalletFifoSolanaProvenanceClassification={snapshot.taxYearWalletFifoSolanaProvenanceClassification}
        taxYearWalletFifoSolanaProvenanceBatchLatest={snapshot.taxYearWalletFifoSolanaProvenanceBatchLatest}
        taxYearWalletFifoSolanaRawProvenanceSenders={snapshot.taxYearWalletFifoSolanaRawProvenanceSenders}
        taxYearWalletFifoSolanaRawProvenancePriorities={snapshot.taxYearWalletFifoSolanaRawProvenancePriorities}
        taxYearWalletFifoSolanaRawBmfEvidenceSummary={snapshot.taxYearWalletFifoSolanaRawBmfEvidenceSummary}
        taxYearWalletFifoSolanaRawBmfEvidenceDrilldown={snapshot.taxYearWalletFifoSolanaRawBmfEvidenceDrilldown}
        taxYearWalletFifoSolanaSenderClusters={snapshot.taxYearWalletFifoSolanaSenderClusters}
        taxYearWalletFifoSolanaSenderClusterOutflows={snapshot.taxYearWalletFifoSolanaSenderClusterOutflows}
        taxYearWalletFifoSolanaOrigin={snapshot.taxYearWalletFifoSolanaOrigin}
        taxLegacyHeliumOverview={snapshot.taxLegacyHeliumOverview}
        taxIncomeGuide={snapshot.taxIncomeGuide}
        taxRewardTradingSeparation={snapshot.taxRewardTradingSeparation}
        taxYearDrivers={snapshot.taxYearDrivers}
        taxYearGainLossRealityCheck={snapshot.taxYearGainLossRealityCheck}
        taxYearTurnoverAudit={snapshot.taxYearTurnoverAudit}
        taxYearsTurnoverAuditSummary={snapshot.taxYearsTurnoverAuditSummary}
        taxSolanaProgramIncomeReview={snapshot.taxSolanaProgramIncomeReview}
        taxStablecoinFifoReview={snapshot.taxStablecoinFifoReview}
        taxStablecoinQuoteLegReview={snapshot.taxStablecoinQuoteLegReview}
        taxSolanaStablecoinSwapContext={snapshot.taxSolanaStablecoinSwapContext}
        taxSolanaStablecoinFxReview={snapshot.taxSolanaStablecoinFxReview}
        taxYearEvidence={snapshot.taxYearEvidence}
        taxExternalInflows={snapshot.taxExternalInflows}
        taxLots={snapshot.taxLots ?? []}
        taxLines={snapshot.taxLines ?? []}
        taxUnmatchedDisposals={snapshot.taxUnmatchedDisposals ?? []}
        derivativeSummary={snapshot.derivativeSummary}
        derivativeLines={snapshot.derivativeLines ?? []}
        selectedTaxYear={selectedTaxYear}
        onSelectedTaxYearChange={onSelectedTaxYearChange}
        taxViewMode={taxViewMode}
        onTaxViewModeChange={onTaxViewModeChange}
        minHoldingValueEur={minHoldingValueEur}
        onMinHoldingValueEurChange={onMinHoldingValueEurChange}
        onRebuildTax={onRebuildTax}
        onRebuildDerivatives={onRebuildDerivatives}
        onAddCexSenderOwnershipDecision={onAddCexSenderOwnershipDecision}
        onDownload={onDownload}
      />
    );
  }
  if (active === "zugewinn") {
    return <DivorceEqualizationPanel report={snapshot.divorceEqualization} onDownload={onDownload} />;
  }
  if (active === "export") {
    return (
      <Stack>
        <ReportCenterPanel
          center={snapshot.reportCenter}
          evidenceManifest={snapshot.reportEvidenceManifest}
          evidencePackageIndex={snapshot.reportEvidencePackageIndex}
          readiness={snapshot.exportReadiness}
          priceQuality={snapshot.priceQuality}
          reviewDecisions={snapshot.reviewDecisions ?? []}
          exportViewMode={exportViewMode}
          onExportViewModeChange={onExportViewModeChange}
          onCreatePdfExport={onCreatePdfExport}
          onRunReportAction={onRunReportAction}
          onDownload={onDownload}
        />
        {exportViewMode === "expert" ? (
          <TablePanel
            title="Export-Pakete"
            rows={snapshot.reportCenter?.packages ?? snapshot.exports ?? []}
            actionLabel="Pipeline neu berechnen"
            onAction={onRebuildPipeline}
            rowActions={[
              {
                label: "PDF herunterladen",
                icon: <FileDown size={16} />,
                onClick: (row) => onDownload(`/api/v1/export/packages/${String(row.package_id ?? "")}/download.pdf`)
              },
              {
                label: "Exportpaket entfernen",
                icon: <Trash2 size={16} />,
                tone: "danger",
                onClick: (row) => onDeleteExportPackage(String(row.package_id ?? ""))
              }
            ]}
            footer={`Report-Center: ${formatDateTime(snapshot.reportCenter?.generated_at)} | Pakete: ${snapshot.reportCenter?.packages_count ?? snapshot.exports?.length ?? 0}`}
          />
        ) : null}
      </Stack>
    );
  }
  if (active === "admin") {
    return (
      <Stack>
        <ToolSafetyPanel
          title="Administration"
          tone="warning"
          mode="Schreibfaehiges Werkzeug"
          detail="Settings und CEX-Credentials koennen hier gespeichert oder geloescht werden. Das aendert keine Steuerdaten direkt, beeinflusst aber kuenftige Live-Abfragen und Systemverhalten."
          nextAction="Credentials nur aktualisieren, wenn Quelle und Secret sicher bekannt sind."
        />
        <KeyValuePanel title="Admin-Status" data={snapshot.admin ?? {}} />
        <V1CexCredentialTakeoverPanel report={snapshot.v1CexCredentialTakeover} onImportV1CexCredentials={onImportV1CexCredentials} />
        <AdminCexCredentialForm onSaveCexCredentials={onSaveCexCredentials} />
        <JupiterTokenApiPanel
          query={jupiterTokenQuery}
          result={snapshot.jupiterTokenSearch}
          metadataCache={snapshot.jupiterMetadataCache}
          onQueryChange={onJupiterTokenQueryChange}
          onSaveApiKey={onSaveJupiterApiKey}
          onSearch={onSearchJupiterTokens}
          onRefreshMetadataCache={onRefreshJupiterMetadataCache}
        />
        <TablePanel
          title="CEX-Credential-Diagnose"
          rows={(snapshot.sourceConnectorDiagnostics?.diagnostics ?? [])
            .filter((row) => row.connector_type === "cex")
            .map((row) => ({
              connector: row.connector_id,
              status: sourceConnectorStatusLabel(row.status),
              credentials: sourceCredentialStatusLabel(row.credential_status),
              problem: row.credential_issue,
              secret_keys: `${String(row.credential_keys_present ?? 0)}/${String(row.credential_keys_required ?? 0)}`,
              credential_geaendert: row.credential_updated_at_latest ? formatDateTime(row.credential_updated_at_latest) : "-",
              letzter_snapshot: row.last_snapshot_at ? formatDateTime(row.last_snapshot_at) : "-",
              snapshot_alter_tage: row.last_snapshot_age_days,
              naechster_schritt: row.next_action
            }))}
          compact
        />
        <AdminSettingForm onSaveAdminSetting={onSaveAdminSetting} />
        <TablePanel
          title="Admin-Settings"
          rows={snapshot.adminSettings ?? []}
          rowActions={[
            {
              label: "Setting entfernen",
              icon: <Trash2 size={16} />,
              tone: "danger",
              onClick: (row) => onDeleteAdminSetting(String(row.key ?? ""))
            }
          ]}
        />
      </Stack>
    );
  }
  return (
    <Stack>
      <ToolSafetyPanel
        title="Lokale KI"
        tone="ok"
        mode="Read-only QA und Task-Verwaltung"
        detail="Der Jahrespaket-QA-Status liest vorhandene lokale KI-Artefakte. Neue KI-Aufgaben werden erst ueber das Formular angelegt; externe KI bleibt separat markiert."
        nextAction="QA-Ergebnis als Hinweis nutzen, steuerliche Freigabe bleibt Review/BMF/Export-Gate."
      />
      <LocalAiYearPackageQaPanel report={snapshot.localAiYearPackageQa} onDownload={onDownload} />
      <AiTaskForm onCreateAiTask={onCreateAiTask} />
      <TablePanel
        title="KI-Aufgaben"
        rows={snapshot.ai ?? []}
        rowActions={[
          {
            label: "KI-Aufgabe entfernen",
            icon: <Trash2 size={16} />,
            tone: "danger",
            onClick: (row) => onDeleteAiTask(String(row.task_id ?? ""))
          }
        ]}
      />
    </Stack>
  );
}

function Stack({ children }: { children: React.ReactNode }) {
  return <div className="stack">{children}</div>;
}

function ToolSafetyPanel({
  title,
  mode,
  detail,
  nextAction,
  tone
}: {
  title: string;
  mode: string;
  detail: string;
  nextAction: string;
  tone: "ok" | "warning" | "blocked";
}) {
  return (
    <section className={`toolSafetyPanel ${tone}`}>
      <div>
        <span className="heroKicker">Werkzeugbereich</span>
        <h2>{title}</h2>
        <p>{detail}</p>
      </div>
      <div className="toolSafetyFacts">
        <span className={`statusPill ${tone}`}>{mode}</span>
        <strong>{nextAction}</strong>
      </div>
    </section>
  );
}

function SourcesPage({
  overview,
  connectorDiagnostics,
  detail,
  sourceReconciliation,
  sourceReconciliationEvidence,
  binanceEarnHistoryPreflight,
  binanceEarnHistoryApiPreview,
  selectedSourceId,
  onSelectedSourceIdChange,
  onRefreshConfiguredSources,
  sourceRefreshLoading,
  sourceViewMode,
  onSourceViewModeChange
}: {
  overview: Snapshot["sourcesOverview"];
  connectorDiagnostics: Snapshot["sourceConnectorDiagnostics"];
  detail: Snapshot["sourceDetail"];
  sourceReconciliation: Snapshot["sourceReconciliation"];
  sourceReconciliationEvidence: Snapshot["sourceReconciliationEvidence"];
  binanceEarnHistoryPreflight: Snapshot["binanceEarnHistoryPreflight"];
  binanceEarnHistoryApiPreview: Snapshot["binanceEarnHistoryApiPreview"];
  selectedSourceId: string | null;
  onSelectedSourceIdChange: (sourceId: string) => void;
  onRefreshConfiguredSources: () => void;
  sourceRefreshLoading: boolean;
  sourceViewMode: SourceViewMode;
  onSourceViewModeChange: (mode: SourceViewMode) => void;
}) {
  const sources = overview?.sources ?? [];
  const activeId = selectedSourceId ?? String(sources[0]?.source_id ?? "");
  const selected = sources.find((source) => String(source.source_id) === activeId) ?? sources[0];
  const sourceValue = parseNumber(selected?.value_eur);
  const totalValue = parseNumber(overview?.total_value_eur);
  const reconciliation = detail?.reconciliation ?? {};
  const accounts = detail?.accounts ?? [];
  const assets = detail?.assets ?? [];
  const recentEvents = detail?.recent_events ?? [];
  const issues = detail?.open_issues ?? [];
  const evidenceRefs = detail?.evidence_refs ?? [];
  const health = overview?.health;
  const healthIssues = (health?.total_open_reconciliation_issues ?? 0) + (health?.total_open_price_issues ?? 0);
  const connectorRows = connectorDiagnostics?.diagnostics ?? [];

  return (
    <Stack>
      <section className="sourcesHero">
        <div>
          <span className="heroKicker">Quellen-Cockpit</span>
          <h2>{formatCurrency(totalValue)} EUR</h2>
          <p>{overview?.methodology ?? "Quellen werden geladen."}</p>
          <div className="sourceHeroActions">
            <button type="button" onClick={onRefreshConfiguredSources} disabled={sourceRefreshLoading}>
              <WalletCards size={16} />
              <span>{sourceRefreshLoading ? "Quellen werden abgefragt" : "Alle konfigurierten Quellen per API abfragen"}</span>
            </button>
          </div>
        </div>
        <div className="sourceHeroStats">
          <Metric title="Quellen" value={String(sources.length)} />
          <Metric title="Ausgewaehlt" value={selected ? String(selected.label) : "-"} />
          <Metric title="Live verbunden" value={`${health?.live_connected_sources ?? 0}/${health?.sources_count ?? sources.length}`} />
          <Metric title="Live veraltet" value={String(health?.stale_live_sources ?? 0)} />
          <Metric title="Ledger-only" value={String(health?.ledger_only_sources ?? sources.length)} />
          <Metric title="Issues" value={String(healthIssues)} />
        </div>
      </section>
      {health ? (
        <div className={`notice inlineNotice sourceHealthNotice ${String(health.status)}`}>
          Quellenstatus: {sourceHealthLabel(health.status)} · {health.detail}
          {health.missing_live_sources > 0 ? ` · ${health.missing_live_sources} Live-Anker fehlen` : ""}
        </div>
      ) : null}
      <div className="taxViewSwitch" role="tablist" aria-label="Quellen Ansicht">
        <button
          type="button"
          className={sourceViewMode === "overview" ? "active" : ""}
          onClick={() => onSourceViewModeChange("overview")}
        >
          Uebersicht
        </button>
        <button
          type="button"
          className={sourceViewMode === "reconciliation" ? "active" : ""}
          onClick={() => onSourceViewModeChange("reconciliation")}
        >
          Abgleich
        </button>
        <button
          type="button"
          className={sourceViewMode === "expert" ? "active" : ""}
          onClick={() => onSourceViewModeChange("expert")}
        >
          Expertenmodus
        </button>
      </div>
      {health?.issues?.length ? (
        <TablePanel
          title="Quellen-Health-Hinweise"
          rows={health.issues.map((issue) => ({
            quelle: issue.label,
            prioritaet: issue.severity,
            hinweis: sourceHealthIssueLabel(issue.issue),
            detail: issue.detail,
            live_alter_tage: issue.live_age_days,
            letzte_live_abfrage: issue.last_live_at,
            naechster_schritt: issue.next_action
          }))}
          compact
        />
      ) : null}
      {sourceViewMode === "expert" && connectorDiagnostics ? (
        <div className="panel">
          <div className="panelToolbar">
            <strong>Connector-Diagnose</strong>
            <span className={`statusPill ${connectorDiagnostics.missing_credentials > 0 ? "blocked" : connectorDiagnostics.stale_snapshots > 0 || connectorDiagnostics.missing_snapshots > 0 ? "warning" : "ok"}`}>
              {connectorDiagnostics.missing_credentials} Credentials fehlen · {connectorDiagnostics.stale_snapshots} veraltet
            </span>
          </div>
          <div className="portfolioSummaryStrip">
            <Metric title="Gepruefte Connectoren" value={String(connectorRows.length)} />
            <Metric title="Credentials fehlen" value={String(connectorDiagnostics.missing_credentials)} />
            <Metric title="Snapshots fehlen" value={String(connectorDiagnostics.missing_snapshots)} />
            <Metric title="Snapshots veraltet" value={String(connectorDiagnostics.stale_snapshots)} />
          </div>
          <TablePanel
            title="API-/Snapshot-Status je Quelle"
            rows={connectorRows.map((row) => ({
              quelle: row.label,
              connector: row.connector_id,
              typ: row.connector_type,
              status: sourceConnectorStatusLabel(row.status),
              credentials: sourceCredentialStatusLabel(row.credential_status),
              credential_problem: row.credential_issue,
              secret_keys: `${String(row.credential_keys_present ?? 0)}/${String(row.credential_keys_required ?? 0)}`,
              credential_geaendert: row.credential_updated_at_latest ? formatDateTime(row.credential_updated_at_latest) : "-",
              letzter_snapshot: row.last_snapshot_at ? formatDateTime(row.last_snapshot_at) : "-",
              snapshot_alter_tage: row.last_snapshot_age_days,
              assets: row.last_snapshot_assets,
              snapshot_wert_eur: row.last_snapshot_value_eur,
              hinweis: row.message,
              naechster_schritt: row.next_action
            }))}
            compact
            footer={`${connectorDiagnostics.methodology} Stand ${formatDateTime(connectorDiagnostics.generated_at)}.`}
          />
        </div>
      ) : null}

      <div className="sourceCardGrid">
        {sources.map((source, index) => {
          const sourceId = String(source.source_id);
          const isActive = sourceId === activeId;
          return (
            <button
              key={sourceId}
              className={`sourceCard ${isActive ? "active" : ""}`}
              type="button"
              onClick={() => onSelectedSourceIdChange(sourceId)}
            >
              <div className="sourceCardHeader">
                <strong>{String(source.label)}</strong>
                <span className={`statusPill ${sourceStatusTone(String(source.current_status), Number(source.open_reconciliation_issues ?? 0))}`}>
                  {sourceStatusLabel(source.current_status)}
                </span>
              </div>
              <div className="sourceCardValue">{formatCurrency(source.value_eur)} EUR</div>
              <div className="barTrack" aria-hidden="true">
                <div className="barFill" style={{ width: `${Math.max(3, Math.min(parseNumber(source.share_pct), 100))}%`, backgroundColor: flowColor(index) }} />
              </div>
              <div className="sourceCardMeta">
                <span>{formatPercent(source.share_pct)}</span>
                <span>{String(source.value_basis ?? "ledger")}</span>
                <span>{String(source.asset_count ?? 0)} Assets</span>
                <span>{String(source.account_count ?? 0)} Konten</span>
                <span>{String(source.open_reconciliation_issues ?? 0)} Abgleich</span>
                <span className={`sourceLiveTag ${String(source.live_freshness ?? "missing")}`}>
                  {sourceLiveFreshnessLabel(source.live_freshness, source.live_age_days)}
                </span>
                {source.display_warning ? <span className="sourceWarningTag">Delta offen</span> : null}
              </div>
            </button>
          );
        })}
      </div>

      {sourceViewMode !== "overview" ? (
        <>
      <section className="sourceDetailGrid">
        <div className="panel sourceDetailMain">
          <div className="panelToolbar">
            <strong>{String(detail?.label ?? selected?.label ?? "Quelle")}</strong>
            <span>{String(detail?.source_type ?? selected?.source_type ?? "-")}</span>
          </div>
          <div className="sourceDetailValue">{formatCurrency(detail?.value_eur ?? sourceValue)} EUR</div>
          <div className="statusRows sourceStatusRows">
            <StatusRow label="Wertbasis" value={String(detail?.value_basis ?? selected?.value_basis ?? "ledger")} />
            <StatusRow label="Portfolio-Anteil" value={formatPercent(detail?.share_pct ?? selected?.share_pct ?? 0)} />
            <StatusRow label="Import-Batches" value={String(detail?.import_batches ?? selected?.import_batches ?? 0)} />
            <StatusRow label="Letzter Import" value={detail?.last_imported_at ? formatDateTime(detail.last_imported_at) : "-"} />
            <StatusRow label="Letzte Live-Abfrage" value={detail?.last_live_at ? formatDateTime(detail.last_live_at) : "-"} />
            <StatusRow label="Live-Aktualitaet" value={sourceLiveFreshnessLabel(detail?.live_freshness ?? selected?.live_freshness, detail?.live_age_days ?? selected?.live_age_days)} />
            <StatusRow label="Live-Quelle" value={String(detail?.live_anchor_source ?? "-")} />
            <StatusRow label="Preis-Issues" value={String(detail?.open_price_issues ?? selected?.open_price_issues ?? 0)} />
            <StatusRow label="Abgleich-Issues" value={String(detail?.open_reconciliation_issues ?? selected?.open_reconciliation_issues ?? 0)} />
          </div>
          {detail?.display_warning ? <div className="notice inlineNotice sourceWarningNotice">{String(detail.display_warning)}</div> : null}
        </div>

        <div className="panel">
          <div className="panelToolbar">
            <strong>Ledger vs. Live</strong>
            <span className={`statusPill ${sourceReconciliationTone(String(reconciliation.severity ?? ""))}`}>
              {String(reconciliation.severity ?? "-")}
            </span>
          </div>
          <div className="statusRows">
            <StatusRow label="Ledger" value={`${formatCurrency(reconciliation.ledger_value_eur ?? detail?.ledger_value_eur)} EUR`} />
            <StatusRow label="Live" value={reconciliation.live_value_eur === null || reconciliation.live_value_eur === undefined ? "-" : `${formatCurrency(reconciliation.live_value_eur)} EUR`} />
            <StatusRow label="Delta" value={reconciliation.delta_value_eur === null || reconciliation.delta_value_eur === undefined ? "-" : `${formatCurrency(reconciliation.delta_value_eur)} EUR`} />
            <StatusRow label="Live-Stand" value={reconciliation.last_live_at ? formatDateTime(reconciliation.last_live_at) : "-"} />
            <StatusRow label="Live-Quelle" value={String(reconciliation.live_anchor_source ?? "-")} />
            <StatusRow label="Status" value={sourceStatusLabel(reconciliation.status)} />
          </div>
        </div>
      </section>

      <SourceReconciliationBreakdownPanel report={sourceReconciliation} />
      {activeId === "binance" ? <BinanceEvidencePanel report={sourceReconciliationEvidence} /> : null}
      {activeId === "binance" ? <BinanceEarnHistoryPreflightPanel report={binanceEarnHistoryPreflight} /> : null}
      {activeId === "binance" ? <BinanceEarnHistoryApiPanel report={binanceEarnHistoryApiPreview} /> : null}

      <section className="cockpitDataGrid">
        <div className="panel">
          <div className="panelToolbar">
            <strong>Asset-Aufbau</strong>
            <span>{assets.length}</span>
          </div>
          <div className="cockpitBars">
            {assets.slice(0, 12).map((asset, index) => (
              <CockpitBar
                key={String(asset.asset)}
                label={tokenDisplay(asset)}
                value={`${formatCurrency(asset.value_eur)} EUR`}
                meta={`${formatValue(asset.quantity, "quantity")} ${String(asset.asset)} · ${formatPercent(asset.share_pct)} · ${String(asset.value_basis ?? "ledger")} · ${tokenMeta(asset)} · ${asset.priced_at_latest ? formatDateTime(asset.priced_at_latest) : "ohne Datum"}`}
                width={parseNumber(asset.share_pct)}
                color={flowColor(index)}
              />
            ))}
          </div>
        </div>

        <div className="panel">
          <div className="panelToolbar">
            <strong>Wallets / Konten</strong>
            <span>{accounts.length}</span>
          </div>
          <div className="sourceAccountList">
            {accounts.map((account) => (
              <div key={String(account.full_account ?? account.account)} className="sourceAccountRow">
                <strong title={String(account.full_account ?? account.account)}>{String(account.display_account ?? shortAccount(String(account.account ?? "")))}</strong>
                <span>{formatCurrency(account.value_eur)} EUR</span>
                <code>{String(account.full_account ?? account.account)}</code>
              </div>
            ))}
          </div>
        </div>
      </section>
        </>
      ) : null}

      {sourceViewMode === "expert" ? (
        <>
      <TablePanel
        title="Letzte Transaktionen"
        rows={recentEvents.map((event) => ({
          event_time: event.event_time,
          source: event.source,
          event_type: event.event_type,
          asset: event.asset,
          quantity: event.quantity,
          account: event.account,
          counterparty_account: event.counterparty_account,
          raw_type: event.raw_type,
          match_basis: event.match_basis,
          tx_id: event.tx_id
        }))}
      />
      <TablePanel title="Offene Issues dieser Quelle" rows={issues} />
      <TablePanel
        title="Belege / Hinweise"
        rows={[
          ...((detail?.last_evidence_files ?? selected?.last_evidence_files ?? []) as Array<unknown>).map((file, index) => ({
            nr: index + 1,
            typ: "Datei",
            evidence_ref: file
          })),
          ...evidenceRefs.map((ref, index) => ({
            nr: index + 1 + ((detail?.last_evidence_files ?? selected?.last_evidence_files ?? []) as Array<unknown>).length,
            typ: "Hinweis",
            evidence_ref: ref
          }))
        ]}
        footer={detail?.methodology ?? ""}
      />
        </>
      ) : null}
    </Stack>
  );
}

function SourceReconciliationBreakdownPanel({
  report
}: {
  report: Snapshot["sourceReconciliation"];
}) {
  const rows = report?.rows ?? [];
  const blockers = rows.filter((row) => String(row.severity) === "blocker").length;
  const warnings = rows.filter((row) => String(row.severity) === "warning").length;
  return (
    <div className="panel">
      <div className="panelToolbar">
        <strong>Asset-Level Live-Abgleich</strong>
        <span className={`statusPill ${sourceReconciliationTone(String(report?.severity ?? ""))}`}>
          {blockers} Blocker · {warnings} Warnungen
        </span>
      </div>
      <div className="portfolioSummaryStrip">
        <Metric title="Ledger" value={`${formatCurrency(report?.ledger_value_eur)} EUR`} />
        <Metric title="API-Live" value={report?.live_value_eur === null || report?.live_value_eur === undefined ? "-" : `${formatCurrency(report.live_value_eur)} EUR`} />
        <Metric title="API-Live minus Ledger" value={report?.delta_value_eur === null || report?.delta_value_eur === undefined ? "-" : `${formatCurrency(report.delta_value_eur)} EUR`} />
        <Metric title="Live-Stand" value={report?.last_live_at ? formatDateTime(report.last_live_at) : "-"} />
      </div>
      <div className="statusRows">
        <StatusRow label="Delta-Formel" value="API-Livewert minus steuerlicher V2-Ledgerwert" />
        <StatusRow label="Ledger-Basis" value="FIFO-/Steuerledger aus importierten Canonical Events" />
        <StatusRow label="Live-Basis" value="Gespeicherter API-Snapshot; keine automatische Steuerkorrektur" />
      </div>
      {report?.display_warning ? <div className="notice inlineNotice sourceWarningNotice">{String(report.display_warning)}</div> : null}
      <TablePanel
        title="Asset-Deltas"
        rows={rows.map((row) => ({
          severity: row.severity,
          status: sourceStatusLabel(row.status),
          asset: row.asset,
          ledger_quantity: row.ledger_quantity,
          live_quantity: row.live_quantity,
          delta_quantity: row.delta_quantity,
          ledger_value_eur: row.ledger_value_eur,
          live_value_eur: row.live_value_eur,
          delta_value_eur: row.delta_value_eur,
          live_components: row.live_components,
          live_account_types: Array.isArray(row.live_account_types) ? row.live_account_types.join(", ") : "",
          live_products: Array.isArray(row.live_products) ? row.live_products.join(", ") : "",
          price_source: row.price_source,
          next_action: row.next_action
        }))}
        footer={`${report?.live_anchor_source ?? "kein Live-Anker"} | ${report?.methodology ?? ""}`}
      />
      <TablePanel
        title="Live-Komponenten"
        rows={(report?.live_components ?? []).map((component) => ({
          asset: component.asset,
          quantity: component.quantity,
          value_eur: component.value_eur,
          account_type: component.account_type,
          product_id: component.product_id,
          position_id: component.position_id,
          event_type: component.event_type,
          price_eur: component.price_eur,
          price_source: component.price_source
        }))}
        footer="Einzelkomponenten des gespeicherten Live-Snapshots. Binance-Produkte werden hier getrennt von Ledger-/FIFO-Korrekturen sichtbar."
      />
    </div>
  );
}

function BinanceEvidencePanel({
  report
}: {
  report: Snapshot["sourceReconciliationEvidence"];
}) {
  if (!report) {
    return null;
  }
  const assetReports = report.asset_reports ?? [];
  const eventRows = assetReports.flatMap((assetReport) => {
    const summaries = Array.isArray(assetReport.event_summaries) ? assetReport.event_summaries : [];
    return summaries.map((summary) => ({
      asset: assetReport.asset,
      year: (summary as Record<string, unknown>).year,
      event_type: (summary as Record<string, unknown>).event_type,
      account: (summary as Record<string, unknown>).account,
      event_count: (summary as Record<string, unknown>).event_count,
      quantity_sum: (summary as Record<string, unknown>).quantity_sum
    }));
  });
  return (
    <>
      <TablePanel
        title="Binance Evidence 2025+"
        rows={assetReports.map((assetReport) => ({
          asset: assetReport.asset,
          suspected_gap: assetReport.suspected_gap,
          ledger_quantity: assetReport.ledger_quantity,
          live_quantity: assetReport.live_quantity,
          delta_quantity: assetReport.delta_quantity,
          ledger_value_eur: assetReport.ledger_value_eur,
          live_value_eur: assetReport.live_value_eur,
          delta_value_eur: assetReport.delta_value_eur,
          unknown_event_count: assetReport.unknown_event_count,
          next_action: assetReport.next_action
        }))}
        footer={`${report.methodology} Stand ${formatDateTime(report.generated_at)}; seit ${formatDateTime(report.since)}.`}
      />
      <TablePanel
        title="Binance Event-Aggregate"
        rows={eventRows}
        footer="Canonical Events seit 2025 nach Jahr, Asset, Event-Typ und Account. Unknown-Zeilen sind Parser-/Mapping-Arbeit, keine FIFO-Korrektur."
      />
      <TablePanel
        title="Binance Historienbedarf"
        rows={(report.history_requirements ?? []).map((requirement) => ({
          asset: requirement.asset,
          current_status: requirement.current_status,
          requirement: requirement.requirement,
          account_type: requirement.account_type,
          product_id: requirement.product_id,
          gap_reason: requirement.gap_reason,
          recommended_source: requirement.recommended_source,
          evidence_refs: Array.isArray(requirement.evidence_refs) ? requirement.evidence_refs.join(", ") : requirement.evidence_refs
        }))}
        footer="Fehlende Produkt-/Fiat-Historie wird hier als Import-/API-Bedarf markiert. Diese Liste bucht nichts in FIFO oder Ledger."
      />
      <TablePanel
        title="Binance Import-Belege"
        rows={(report.import_batches ?? []).map((batch) => ({
          filename: batch.filename,
          status: batch.status,
          created_at: batch.created_at
        }))}
        footer="Vorhandene Binance-Import-Batches als Nachweisbasis fuer die Historie."
      />
    </>
  );
}

function BinanceEarnHistoryPreflightPanel({
  report
}: {
  report: Snapshot["binanceEarnHistoryPreflight"];
}) {
  if (!report) {
    return null;
  }
  return (
    <TablePanel
      title="Binance Earn-History Preflight"
      rows={(report.products ?? []).map((product) => ({
        asset: product.asset,
        import_status: product.import_status,
        account_type: product.account_type,
        product_id: product.product_id,
        position_id: product.position_id,
        live_quantity: product.live_quantity,
        live_value_eur: product.live_value_eur,
        required_movements: Array.isArray(product.required_movements) ? product.required_movements.join(", ") : product.required_movements,
        live_event_types: Array.isArray(product.live_event_types) ? product.live_event_types.join(", ") : product.live_event_types,
        next_action: product.next_action
      }))}
      footer={`${report.status}: ${report.missing_products} fehlend, ${report.partial_products} teilweise, ${report.covered_products} belegt. ${report.methodology}`}
    />
  );
}

function BinanceEarnHistoryApiPanel({
  report
}: {
  report: Snapshot["binanceEarnHistoryApiPreview"];
}) {
  if (!report) {
    return null;
  }
  const records = report.records ?? [];
  return (
    <>
      <TablePanel
        title="Binance Earn API-Abruf"
        rows={(report.requests ?? []).map((request) => ({
          status: request.status,
          record_type: request.record_type,
          asset: request.asset,
          product_id: request.product_id,
          position_id: request.position_id,
          records: request.records,
          total: request.total,
          pages_requested: request.pages_requested,
          error: request.error
        }))}
        footer={`${report.credential_status}: ${report.records_returned} Records geladen${report.truncated ? " (gekürzt)" : ""}. ${report.methodology}`}
      />
      <TablePanel
        title="Binance Earn API-Records"
        rows={records.slice(0, 80).map((record) => {
          const payload = typeof record.payload === "object" && record.payload !== null ? record.payload as Record<string, unknown> : {};
          return {
            record_type: record.record_type,
            asset: record.asset ?? payload.asset,
            product_id: record.product_id ?? payload.productId,
            position_id: record.position_id ?? payload.positionId,
            time: payload.time,
            amount: payload.amount ?? payload.rewards ?? payload.principal,
            status: payload.status,
            type: payload.type
          };
        })}
        footer="Anzeige der ersten 80 geladenen Records. Diese Daten sind noch nicht als Canonical Events importiert."
      />
    </>
  );
}

function sourceStatusTone(status: string, issueCount: number): "ok" | "warning" | "blocked" {
  if (issueCount > 0 || status.includes("missing") || status.includes("expected_zero")) {
    return "blocked";
  }
  if (status.includes("needs")) {
    return "warning";
  }
  return "ok";
}

function sourceStatusLabel(status: unknown): string {
  const normalized = String(status ?? "");
  const labels: Record<string, string> = {
    complete_export_strategy_reference_live_zero: "Export belegt, Live-Dust",
    dust_delta: "Dust-Delta",
    expected_live_zero: "Erwartet Null",
    expected_zero_delta: "Nullbestand klaeren",
    ledger_current: "Ledger aktuell",
    ledger_current_needs_live_anchor: "Live-Anker fehlt",
    ledger_only_dust: "Ledger-Dust",
    live_anchor_present: "Live-Anker vorhanden",
    live_anchor_reconciled: "Live abgeglichen",
    material_live_ledger_delta: "Materiales Delta",
    missing_live_asset: "Live-Asset fehlt",
    product_live_anchor_present: "Produkt-Live-Anker",
    quantity_reconciled: "Menge abgeglichen",
    reconciled_with_dust: "Abgeglichen mit Dust",
    wallet_history_partially_imported: "Wallet-Historie offen"
  };
  return labels[normalized] ?? (normalized.replaceAll("_", " ") || "-");
}

function sourceHealthLabel(status: unknown): string {
  const normalized = String(status ?? "");
  if (normalized === "ok") {
    return "vollstaendig";
  }
  if (normalized === "warning") {
    return "pruefen";
  }
  if (normalized === "blocked") {
    return "offen";
  }
  return normalized || "-";
}

function sourceLiveFreshnessLabel(status: unknown, ageDays: unknown): string {
  const normalized = String(status ?? "missing");
  const age = Number(ageDays);
  if (normalized === "fresh") {
    return Number.isFinite(age) ? `Live ${age} Tage alt` : "Live aktuell";
  }
  if (normalized === "stale") {
    return Number.isFinite(age) ? `Live veraltet (${age} Tage)` : "Live veraltet";
  }
  return "kein Live-Anker";
}

function sourceHealthIssueLabel(issue: unknown): string {
  const normalized = String(issue ?? "");
  const labels: Record<string, string> = {
    display_warning: "Delta-Hinweis",
    missing_live_anchor: "Live-Anker fehlt",
    price_issue: "Preisproblem",
    reconciliation_issue: "Abgleich offen",
    stale_live_snapshot: "Live veraltet"
  };
  return labels[normalized] ?? (normalized.replaceAll("_", " ") || "-");
}

function sourceConnectorStatusLabel(status: unknown): string {
  const normalized = String(status ?? "");
  const labels: Record<string, string> = {
    credential_check_failed: "Credential-Pruefung fehlgeschlagen",
    credential_decrypt_failed: "Credentials nicht entschluesselbar",
    fresh: "Frisch",
    fresh_zero_or_dust: "Frisch, Null/Dust",
    missing_credentials: "Credentials fehlen",
    missing_snapshot: "Snapshot fehlt",
    missing_in_v1: "In V1 unvollstaendig",
    not_decryptable: "Nicht entschluesselbar",
    stale_snapshot: "Snapshot veraltet",
    transferable: "Uebernehmbar",
    v1_load_error: "V1-Load-Fehler",
    v1_load_failed: "V1 nicht erreichbar"
  };
  return labels[normalized] ?? (normalized.replaceAll("_", " ") || "-");
}

function sourceCredentialStatusLabel(status: unknown): string {
  const normalized = String(status ?? "");
  const labels: Record<string, string> = {
    configured: "hinterlegt",
    decrypt_failed: "nicht entschluesselbar",
    error: "nicht pruefbar",
    missing: "fehlt",
    not_required: "nicht erforderlich"
  };
  return labels[normalized] ?? (normalized.replaceAll("_", " ") || "-");
}

function sourceReconciliationTone(severity: string): "ok" | "warning" | "blocked" {
  if (severity === "ok" || severity === "info") {
    return "ok";
  }
  if (severity === "warning") {
    return "warning";
  }
  return "blocked";
}

function taxYearTone(state: string): "ok" | "warning" | "blocked" {
  if (state === "finished") {
    return "ok";
  }
  if (state === "historical_open" || state === "empty" || state === "open") {
    return "warning";
  }
  return "blocked";
}

function filingActionStatusLabel(status: unknown): string {
  const normalized = String(status ?? "");
  const labels: Record<string, string> = {
    ready: "bereit",
    conservative_ready: "konservativ bereit",
    review: "pruefen",
    blocked: "blockiert"
  };
  return labels[normalized] ?? normalized;
}

function formatDurationMs(durationMs: unknown): string {
  const value = Number(durationMs ?? 0);
  if (!Number.isFinite(value) || value <= 0) {
    return "";
  }
  if (value < 1000) {
    return `${Math.round(value)}ms`;
  }
  return `${(value / 1000).toFixed(value >= 10000 ? 0 : 1)}s`;
}

function bmfTone(status: string): "ok" | "warning" | "blocked" {
  if (status === "ok") {
    return "ok";
  }
  if (status === "review" || status === "empty") {
    return "warning";
  }
  return "blocked";
}

function paymentChecklistCategoryLabel(value: unknown): string {
  const labels: Record<string, string> = {
    eintragen: "Eintragen",
    beleg: "Nur Beleg",
    pruefen: "Pruefen",
    paket: "Paket"
  };
  const normalized = String(value ?? "");
  return labels[normalized] ?? normalized.replaceAll("_", " ");
}

function reportTone(status: unknown): "ok" | "warning" | "blocked" {
  const value = String(status ?? "");
  if (value === "ready" || value === "available" || value === "freigegeben") {
    return "ok";
  }
  if (value === "planned" || value === "not_created") {
    return "warning";
  }
  return "blocked";
}

function CockpitDashboard({
  summary,
  database,
  onNavigate,
  onRebuildPipeline,
  onRefreshConfiguredSources,
  sourceRefreshLoading
}: {
  summary: Snapshot["cockpit"];
  database: Record<string, unknown> | undefined;
  onNavigate: (section: Section) => void;
  onRebuildPipeline: () => void;
  onRefreshConfiguredSources: () => void;
  sourceRefreshLoading: boolean;
}) {
  const tasks = summary?.tasks ?? [];
  const assets = summary?.top_assets ?? [];
  const sources = summary?.top_sources ?? [];
  const priceCoverage = summary?.price_coverage;
  const live = summary?.live_reconciliation;
  const evidenceHealth = summary?.evidence_health;
  const primaryTask = tasks[0];
  const hasLiveBlockers = (live?.blocker_count ?? 0) > 0 || live?.status === "blocked";
  const hasWarnings = hasLiveBlockers || (live?.warning_count ?? 0) > 0 || tasks.length > 0;
  const statusClass = !summary?.export_allowed ? "blocked" : hasWarnings ? "warning" : "ok";
  const filingHeadline = !summary?.export_allowed
    ? "Export ist blockiert"
    : hasWarnings
      ? "Steuerexport frei, aber Pruefung offen"
      : "Steuerstatus sauber";
  const filingDetail = !summary?.export_allowed
    ? "Mindestens ein Review- oder Belegproblem verhindert aktuell einen sauberen Export."
    : hasWarnings
      ? "Die Steuerfreigabe ist offen, aber Live-Abgleich oder Quellenstatus sollten vor Abgabe nachvollziehbar dokumentiert werden."
      : "Keine priorisierten Aufgaben offen. Die Ansicht kann als Einstieg fuer Belege und Steuerjahre genutzt werden.";
  const nextStepLabel = primaryTask?.title ?? (summary?.export_allowed ? "Steuerjahre pruefen" : "Review oeffnen");
  const nextStepDetail = primaryTask?.detail ?? (summary?.export_allowed ? "Eingabehilfe und Jahrespakete kontrollieren." : "Blockierende Punkte bearbeiten.");
  const nextStepTarget = primaryTask?.target ?? (summary?.export_allowed ? "tax" : "review");
  const coveragePct = formatPercent(priceCoverage?.coverage_pct ?? 0);
  const liveStatusText = live?.status === "ok" ? "belegt" : live?.status === "warning" ? "Warnung" : "offen";
  const evidenceStatusText = evidenceHealth?.status === "complete" ? "vollstaendig" : evidenceHealth?.status ?? "-";

  return (
    <Stack>
      <section className={`cockpitHero ${statusClass}`}>
        <div className="cockpitHeroMain">
          <span className="heroKicker">Steuer- und Portfolio-Cockpit</span>
          <h2>{filingHeadline}</h2>
          <p className="cockpitHeroLead">{filingDetail}</p>
          <div className="cockpitHeroMeta">
            <span className={`statusPill ${statusClass}`}>
              Export {summary?.export_status ?? "-"}
            </span>
            <span>Portfolio {formatCurrency(summary?.portfolio_value_eur)} EUR</span>
            <span>{summary?.review?.detail ?? "Review-Gate wird geladen"}</span>
            <span>Stand {summary?.generated_at ? formatDateTime(summary.generated_at) : "-"}</span>
            <span>DB {String(database?.database_type ?? "-")}</span>
          </div>
        </div>
        <div className="cockpitDecisionRail">
          <button className={`nextActionCard ${statusClass}`} type="button" onClick={() => onNavigate(nextStepTarget)}>
            {statusClass === "ok" ? <Check size={20} /> : <AlertTriangle size={20} />}
            <span>Naechster Schritt</span>
            <strong>{nextStepLabel}</strong>
            <em>{nextStepDetail}</em>
          </button>
          <div className="cockpitActionRail">
            <button type="button" onClick={onRefreshConfiguredSources} disabled={sourceRefreshLoading}>
              <WalletCards size={16} />
              <span>{sourceRefreshLoading ? "Quellen werden abgefragt" : "Alle Quellen per API abfragen"}</span>
            </button>
            {(summary?.quick_actions ?? []).slice(0, 4).map((action) => (
              <button
                key={`${action.target}-${action.label}`}
                type="button"
                disabled={!action.enabled}
                onClick={() => onNavigate(action.target)}
              >
                {quickActionIcon(action.target)}
                <span>{action.label}</span>
              </button>
            ))}
            <button
              type="button"
              onClick={onRebuildPipeline}
            >
              <RefreshCcw size={16} />
              <span>Pipeline neu berechnen</span>
            </button>
          </div>
        </div>
      </section>

      <div className="cockpitMetricGrid">
        <Metric title="API-Livebestand" value={`${formatCurrency(summary?.portfolio_value_eur)} EUR`} />
        <Metric title="Offene Aufgaben" value={String(summary?.open_tasks ?? 0)} />
        <Metric title="Preisdeckung" value={coveragePct} />
        <Metric title="Live-Abgleich" value={liveStatusText} />
        <Metric title="Belegstatus" value={evidenceStatusText} />
      </div>

      <section className="cockpitStatusStrip">
        <div>
          <span>Live-Snapshot</span>
          <strong>{live?.latest_live_snapshot_at ? formatDateTime(live.latest_live_snapshot_at) : "-"}</strong>
        </div>
        <div>
          <span>Live-Blocker/Warnungen</span>
          <strong>{live?.blocker_count ?? 0}/{live?.warning_count ?? 0}</strong>
        </div>
        <div>
          <span>Unverifizierter Live-Wert</span>
          <strong>{formatCurrency(live?.live_unverified_value_eur ?? 0)} EUR</strong>
        </div>
        <div>
          <span>Expected-Zero-Restwerte</span>
          <strong>{formatCurrency(live?.expected_zero_sources_open_value_eur ?? 0)} EUR</strong>
        </div>
      </section>

      <section className="cockpitOverviewGrid">
        <div className="panel cockpitTodo">
          <div className="panelToolbar">
            <strong>Naechste Aufgaben</strong>
            <span>{tasks.length}/3</span>
          </div>
          {tasks.length === 0 ? (
            <div className="empty">Keine priorisierten Aufgaben offen.</div>
          ) : (
            <div className="taskList">
              {tasks.map((task) => (
                <button
                  key={`${task.priority}-${task.title}`}
                  className={`taskItem ${task.priority}`}
                  type="button"
                  onClick={() => onNavigate(task.target)}
                >
                  <span>{task.priority}</span>
                  <strong>{task.title}</strong>
                  <em>{task.detail}</em>
                  {task.count !== null ? <b>{task.count}</b> : null}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="panel cockpitSignalPanel">
          <div className="panelToolbar">
            <strong>Preisdeckung</strong>
            <span>{coveragePct}</span>
          </div>
          <div className="coverageGauge" aria-label={`Preisdeckung ${coveragePct}`}>
            <div style={{ width: `${Math.min(Math.max(parseNumber(priceCoverage?.coverage_pct), 0), 100)}%` }} />
          </div>
          <div className="statusRows">
            <StatusRow label="Bewertete Assets" value={`${priceCoverage?.priced_assets ?? 0}/${priceCoverage?.total_assets ?? 0}`} />
            <StatusRow label="Historische Preisgruppen" value={String(priceCoverage?.missing_event_price_groups ?? 0)} />
            <StatusRow label="Fehlende Assets" value={(priceCoverage?.missing_assets ?? []).join(", ") || "keine"} />
          </div>
        </div>

        <div className="panel cockpitSignalPanel">
          <div className="panelToolbar">
            <strong>Live-Abgleich</strong>
            <span className={`statusPill ${live?.status === "ok" ? "ok" : live?.status === "warning" ? "warning" : "blocked"}`}>
              {liveStatusText}
            </span>
          </div>
          <div className="statusRows">
            <StatusRow label="Connector-Anker" value={String(live?.stored_live_connectors ?? 0)} />
            <StatusRow label="Live-Assets" value={String(live?.stored_live_assets ?? 0)} />
            <StatusRow label="Blocker/Warnungen" value={`${live?.blocker_count ?? 0}/${live?.warning_count ?? 0}`} />
            <StatusRow label="Letzter Snapshot" value={live?.latest_live_snapshot_at ? formatDateTime(live.latest_live_snapshot_at) : "-"} />
          </div>
        </div>
      </section>

      <section className="cockpitDataGrid">
        <div className="panel">
          <div className="panelToolbar">
            <strong>Top-Assets API-Live</strong>
            <span>{assets.length}</span>
          </div>
          <div className="cockpitBars">
            {assets.map((asset, index) => (
              <CockpitBar
                key={String(asset.asset)}
                label={String(asset.asset)}
                value={`${formatCurrency(asset.value_eur)} EUR`}
                meta={`Live ${formatValue(asset.quantity, "quantity")} · ${formatPercent(asset.share_pct)} · Preis ${String(asset.price_status ?? "-")} · ${asset.priced_at_latest ? formatDateTime(asset.priced_at_latest) : "ohne Datum"}`}
                width={parseNumber(asset.share_pct)}
                color={flowColor(index)}
                title="Aggregierter API-Livebestand aus den letzten gespeicherten Connector-Snapshots."
              />
            ))}
          </div>
        </div>

        <div className="panel">
          <div className="panelToolbar">
            <strong>Top-Quellen</strong>
            <span>{sources.length}</span>
          </div>
          <div className="cockpitBars">
            {sources.map((source, index) => (
              <CockpitBar
                key={String(source.source_group)}
                label={String(source.source_group)}
                value={`${formatCurrency(source.live_value_eur ?? source.value_eur)} EUR`}
                meta={sourceMeta(source)}
                width={parseNumber(source.share_pct)}
                color={flowColor(index + 2)}
                title={Array.isArray(source.accounts) ? source.accounts.map((account) => String(account)).join("\n") : undefined}
              />
            ))}
          </div>
        </div>
      </section>

      <div className="panel">
        <div className="panelToolbar">
          <strong>Pipeline-Status</strong>
          <span>{summary?.generated_at ? formatDateTime(summary.generated_at) : "-"}</span>
        </div>
        <div className="statusRows pipelineRows">
          <StatusRow label="Import-Batches" value={String(summary?.pipeline?.import_batches ?? 0)} />
          <StatusRow label="Letzter Import" value={summary?.pipeline?.last_import_at ? formatDateTime(summary.pipeline.last_import_at) : "-"} />
          <StatusRow label="Quelle" value={summary?.pipeline?.last_import_source ?? "-"} />
          <StatusRow label="Letztes Canonical Event" value={summary?.pipeline?.last_canonical_event_at ? formatDateTime(summary.pipeline.last_canonical_event_at) : "-"} />
        </div>
      </div>
    </Stack>
  );
}

function sourceMeta(source: Record<string, unknown>): string {
  const parts = [
    `${formatPercent(source.share_pct)} · ${String(source.source_type ?? "-")}`,
    `Ledger ${formatCurrency(source.ledger_value_eur ?? source.value_eur)} EUR`
  ];
  if (source.live_value_eur !== null && source.live_value_eur !== undefined) {
    parts.push(`API live ${formatCurrency(source.live_value_eur)} EUR`);
    parts.push(`Delta ${formatCurrency(source.delta_value_eur ?? 0)} EUR`);
    parts.push(`Stand ${source.last_live_at ? formatDateTime(source.last_live_at) : "-"}`);
    parts.push(`Quelle ${String(source.live_anchor_source ?? "-")}`);
  } else {
    parts.push("kein API-Livewert");
  }
  if (source.display_warning) {
    parts.push(String(source.display_warning));
  }
  parts.push(String(source.current_status ?? "-"));
  return parts.join(" · ");
}

function CockpitBar({
  label,
  value,
  meta,
  width,
  color,
  title
}: {
  label: string;
  value: string;
  meta: string;
  width: number;
  color: string;
  title?: string;
}) {
  return (
    <div className="cockpitBarRow" title={title}>
      <div className="cockpitBarHeader">
        <strong>{shortAccount(label)}</strong>
        <span>{value}</span>
      </div>
      <div className="barTrack" aria-hidden="true">
        <div className="barFill" style={{ width: `${Math.max(3, Math.min(width, 100))}%`, backgroundColor: color }} />
      </div>
      <p>{meta}</p>
    </div>
  );
}

function quickActionIcon(section: Section): React.ReactNode {
  if (section === "import") {
    return <Upload size={16} />;
  }
  if (section === "portfolio") {
    return <WalletCards size={16} />;
  }
  if (section === "export") {
    return <FileDown size={16} />;
  }
  if (section === "review") {
    return <Database size={16} />;
  }
  return <LayoutDashboard size={16} />;
}

function DashboardPortfolioStatus({
  portfolio,
  review
}: {
  portfolio: Snapshot["portfolio"];
  review: Snapshot["review"];
}) {
  const total = Number(portfolio?.total_value_eur ?? 0);
  const excluded = Number(portfolio?.excluded_value_eur ?? 0);
  const grossTracked = total + excluded;
  const topAssets = (portfolio?.asset_summary ?? []).slice(0, 5);
  const topAccounts = (portfolio?.account_summary ?? []).slice(0, 5);
  const historicalIssues = Number(review?.issues_historical_open ?? 0);
  const currentIssues = Number(review?.issues_current_open ?? review?.issues_open ?? 0);
  const priceStatusRows = (portfolio?.asset_summary ?? []).reduce<Record<string, number>>((acc, row) => {
    const status = String(row.price_status ?? "unknown");
    acc[status] = (acc[status] ?? 0) + 1;
    return acc;
  }, {});
  const statusText = Object.entries(priceStatusRows)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([status, count]) => `${status}: ${count}`)
    .join(" | ");

  return (
    <div className="dashboardStatusGrid">
      <div className="panel statusCard">
        <div className="panelToolbar">
          <strong>Bestandsabgleich</strong>
          <span className={`statusPill ${review?.allow_export ? "ok" : "blocked"}`}>
            {review?.allow_export ? "Export frei" : "Export blockiert"}
          </span>
        </div>
        <div className="statusRows">
          <StatusRow label="Aktueller Bestand" value={`${formatCurrency(total)} EUR`} />
          <StatusRow label="Ausgeklammert" value={`${formatCurrency(excluded)} EUR`} />
          <StatusRow label="Nachverfolgte Bruttosumme" value={`${formatCurrency(grossTracked)} EUR`} />
          <StatusRow label="Preisstatus" value={statusText || "-"} />
        </div>
      </div>
      <div className="panel statusCard">
        <div className="panelToolbar">
          <strong>Top-Bestand</strong>
        </div>
        <div className="compactList">
          {topAssets.map((row) => (
            <StatusRow
              key={String(row.asset)}
              label={String(row.asset)}
              value={`${formatCurrency(row.value_eur)} EUR`}
            />
          ))}
        </div>
      </div>
      <div className="panel statusCard">
        <div className="panelToolbar">
          <strong>Wo liegt es</strong>
        </div>
        <div className="compactList">
          {topAccounts.map((row) => (
            <StatusRow
              key={String(row.account)}
              label={String(row.account)}
              value={`${formatCurrency(row.value_eur)} EUR`}
            />
          ))}
        </div>
      </div>
      <div className="panel statusCard">
        <div className="panelToolbar">
          <strong>Review</strong>
        </div>
        <div className="statusRows">
          <StatusRow label="Aktuell offen" value={String(currentIssues)} />
          <StatusRow label="Historisch offen" value={String(historicalIssues)} />
          <StatusRow label="Blockierend" value={String(review?.blocking_issues_open ?? 0)} />
          <StatusRow label="Gesamt sichtbar" value={String(review?.issues_open_total ?? review?.issues_open ?? 0)} />
        </div>
      </div>
    </div>
  );
}

function StatusRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="statusRow">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function PortfolioDecisionPanel({
  portfolio,
  sources,
  holdingPeriods,
  priceCoverage,
  onDownload
}: {
  portfolio: Snapshot["portfolio"];
  sources: Snapshot["portfolioSources"];
  holdingPeriods: Snapshot["taxHoldingPeriods"];
  priceCoverage: Snapshot["priceCoverage"];
  onDownload: (path: string) => void;
}) {
  const missingPrices = portfolio?.missing_price_assets ?? [];
  const excludedValue = parseNumber(portfolio?.excluded_value_eur);
  const priceCoveragePct = (priceCoverage?.missing_count ?? missingPrices.length) === 0 ? "100" : "0";
  const tone = missingPrices.length > 0 ? "warning" : excludedValue > 0 ? "warning" : "ok";
  const latestPriceAt = (portfolio?.asset_summary ?? [])
    .map((row) => String(row.priced_at_latest ?? ""))
    .filter(Boolean)
    .sort()
    .at(-1);
  const topSource = (sources?.groups ?? [])[0];
  return (
    <section className={`portfolioDecision ${tone}`}>
      <div className="portfolioDecisionMain">
        <span className="heroKicker">Portfolio-Uebersicht</span>
        <h2>{formatCurrency(portfolio?.total_value_eur)} EUR</h2>
        <p>
          Aktueller Bestand mit Preisdeckung, Quellenverteilung und Haltefrist-Ausblick. Detailabgleich und Preisdiagnosen liegen in den Tabs.
        </p>
        <div className="taxFilingTargets">
          <span className={`statusPill ${tone}`}>{missingPrices.length === 0 ? "Preise vollstaendig" : "Preise pruefen"}</span>
          <span>Preisstand {latestPriceAt ? formatDateTime(latestPriceAt) : "-"}</span>
          <span>Top-Quelle {topSource ? String(topSource.source_group) : "-"}</span>
        </div>
      </div>
      <div className="portfolioDecisionActions">
        <button type="button" onClick={() => onDownload("/api/v1/portfolio/snapshot")}>
          <FileJson size={18} />
          <span>Snapshot JSON</span>
        </button>
        <button type="button" onClick={() => onDownload("/api/v1/prices/coverage")}>
          <FileJson size={18} />
          <span>Preisdeckung JSON</span>
        </button>
        <button type="button" onClick={() => onDownload("/api/v1/tax/holding-periods")}>
          <FileJson size={18} />
          <span>Haltefristen JSON</span>
        </button>
      </div>
      <div className="taxFilingDecisionMetrics">
        <Metric title="Preisdeckung" value={formatPercent(priceCoveragePct)} />
        <Metric title="Jetzt steuerfrei" value={`${formatCurrency(holdingPeriods?.tax_free_now_value_eur)} EUR`} />
        <Metric title="30 Tage" value={`${formatCurrency(holdingPeriods?.next_30_days_value_eur)} EUR`} />
        <Metric title="Ausgeklammert" value={`${formatCurrency(portfolio?.excluded_value_eur)} EUR`} />
      </div>
    </section>
  );
}

function PortfolioCompositionPanel({
  portfolio
}: {
  portfolio: Snapshot["portfolio"];
}) {
  const assetRows = (portfolio?.asset_summary ?? []).slice(0, 12);
  const accountRows = (portfolio?.account_summary ?? []).slice(0, 12);
  const total = Number(portfolio?.total_value_eur ?? 0);
  const assetDisplayRows = assetRows.map((row) => {
    const value = Number(row.value_eur ?? 0);
    return {
      asset: row.asset,
      token: tokenDisplay(row),
      token_status: tokenMeta(row),
      quantity: row.quantity,
      value_eur: row.value_eur,
      share_pct: total === 0 ? "0" : ((value / total) * 100).toFixed(2),
      accounts: row.accounts,
      price_sources: Array.isArray(row.price_sources) ? row.price_sources.join(", ") : row.price_sources,
      priced_at_latest: row.priced_at_latest,
      price_age_days: row.price_age_days,
      price_status: row.price_status
    };
  });
  return (
    <Stack>
      <TablePanel
        title="Portfolio-Aufbau nach Asset"
        rows={assetDisplayRows}
        footer={`Top ${assetDisplayRows.length} Assets von ${(portfolio?.asset_summary ?? []).length}. Summe: ${formatCurrency(portfolio?.total_value_eur)} EUR`}
      />
      <TablePanel
        title="Portfolio-Aufbau nach Konto"
        rows={accountRows}
        footer={`Top ${accountRows.length} Konten/Wallets von ${(portfolio?.account_summary ?? []).length}.`}
      />
      <TablePanel
        title="Nicht als aktueller Bestand gewertet"
        rows={portfolio?.excluded_account_summary ?? []}
        footer={`Ausgeklammert: ${formatCurrency(portfolio?.excluded_value_eur)} EUR. Diese Konten bleiben fuer Audit/Steuerdaten erhalten.`}
      />
    </Stack>
  );
}

function PortfolioTokenRiskPanel({
  report,
  reviewDecisions,
  filter,
  onFilterChange,
  onDownload
}: {
  report: Snapshot["portfolioTokenRisk"];
  reviewDecisions: Snapshot["reviewDecisions"];
  filter: TokenRiskFilter;
  onFilterChange: (mode: TokenRiskFilter) => void;
  onDownload: (path: string) => void;
}) {
  const documentedScopes = new Set(
    (reviewDecisions ?? [])
      .filter((decision) => decision.decision_type === "token_risk_documentation")
      .map((decision) => String(decision.scope ?? ""))
  );
  const rows = (report?.rows ?? []).map((row) => ({
    asset: row.asset,
    token: tokenDisplay(row),
    risiko: row.token_risk_status ?? "unknown",
    dokumentiert: documentedScopes.has(
      `token_risk:spam_review:asset:${String(row.asset ?? "")}:mint:${String(row.token_mint ?? row.asset ?? "")}`
    )
      ? "ja"
      : "offen",
    verified: row.token_verified === true ? "ja" : row.token_verified === false ? "nein" : "-",
    mint: row.token_mint ? shortAccount(String(row.token_mint)) : "-",
    quantity: row.quantity,
    value_eur: row.value_eur,
    accounts: row.accounts,
    positions: row.position_count,
    position_detail: Array.isArray(row.positions)
      ? row.positions
          .map((position) => `${shortAccount(String(position.account ?? ""))}: ${formatValue(position.quantity, "quantity")} / ${formatCurrency(position.value_eur)} EUR`)
          .join(" | ")
      : "",
    fundstellen: Array.isArray(row.discovered_sources) ? row.discovered_sources.join(" | ") : "",
    price_status: row.price_status,
    priced_at: row.priced_at_latest ? formatDateTime(String(row.priced_at_latest)) : "-"
  }));
  const filters: Array<{ value: TokenRiskFilter; label: string }> = [
    { value: "all", label: "Alle" },
    { value: "verified", label: "Verified" },
    { value: "unverified_plausible", label: "Plausibel" },
    { value: "spam_review", label: "Spam Review" }
  ];
  return (
    <div className="panel">
      <div className="panelToolbar">
        <strong>Portfolio Token-Risiko</strong>
        <span className={`statusPill ${(report?.spam_review_count ?? 0) > 0 ? "blocked" : "ok"}`}>
          {(report?.spam_review_count ?? 0) > 0 ? `${report?.spam_review_count ?? 0} Spam Review` : "keine Spam-Position"}
        </span>
        <button type="button" onClick={() => onDownload(`/api/v1/portfolio/token-risk?risk_status=${encodeURIComponent(filter)}&min_value_eur=1`)}>
          <FileJson size={16} />
          JSON
        </button>
      </div>
      <div className="taxViewSwitch compact" role="tablist" aria-label="Token-Risiko Filter">
        {filters.map((item) => (
          <button
            key={item.value}
            type="button"
            className={filter === item.value ? "active" : ""}
            onClick={() => onFilterChange(item.value)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div className="reviewSummary">
        <Metric title="Spam Review" value={String(report?.spam_review_count ?? 0)} />
        <Metric title="Review" value={String(report?.review_count ?? 0)} />
        <Metric title="Plausibel" value={String(report?.unverified_plausible_count ?? 0)} />
        <Metric title="Verified" value={String(report?.verified_count ?? 0)} />
        <Metric title="Gefilterter Wert" value={`${formatCurrency(report?.total_value_eur)} EUR`} />
      </div>
      <TablePanel
        title="Token-Risiko Positionen"
        rows={rows}
        compact
        footer={report?.methodology ?? "Read-only Filter ab 1 EUR; keine automatische Bestandskorrektur."}
      />
    </div>
  );
}

function PortfolioValuationAuditPanel({
  report
}: {
  report: Snapshot["portfolioValuationAudit"];
}) {
  const rows = (report?.rows ?? []).slice(0, 18).map((row) => ({
    asset: row.asset,
    quantity: row.quantity,
    wert_eur: row.current_value_eur,
    delta_eur: row.value_delta_eur ?? "-",
    aktueller_preis: row.current_price_eur,
    vorheriger_preis: row.previous_price_eur ?? "-",
    preis_delta_pct: row.price_delta_pct ?? "-",
    status: row.current_price_status,
    preisquelle: row.current_price_source,
    preiszeit: row.current_priced_at ? formatDateTime(row.current_priced_at) : "-",
    vorheriger_preiszeit: row.previous_priced_at ? formatDateTime(row.previous_priced_at) : "-",
    hinweis: row.note
  }));
  return (
    <div className="panel">
      <div className="panelToolbar">
        <strong>Bewertungsanalyse</strong>
        <span>{report?.generated_at ? formatDateTime(report.generated_at) : "-"}</span>
      </div>
      <div className="portfolioSummaryStrip">
        <Metric title="Aktueller Wert" value={`${formatCurrency(report?.total_value_eur)} EUR`} />
        <Metric title="Vorheriger Preisstand" value={report?.previous_total_value_eur === null || report?.previous_total_value_eur === undefined ? "-" : `${formatCurrency(report.previous_total_value_eur)} EUR`} />
        <Metric title="Wertdelta" value={report?.value_delta_eur === null || report?.value_delta_eur === undefined ? "-" : `${formatCurrency(report.value_delta_eur)} EUR`} />
        <Metric title="Assets" value={String(report?.rows?.length ?? 0)} />
      </div>
      <TablePanel
        title="Groesste Bewertungsdeltas"
        rows={rows}
        footer={report?.methodology ?? "Read-only Preisvergleich aus aktuellem und vorherigem Preisledger-Punkt."}
        compact
      />
    </div>
  );
}

function PortfolioBreakdownPanel({
  portfolio
}: {
  portfolio: Snapshot["portfolio"];
}) {
  const total = parseNumber(portfolio?.total_value_eur);
  const assetRows = (portfolio?.asset_summary ?? []).slice(0, 10);
  const positions = portfolio?.positions ?? [];
  const visibleTotal = assetRows.reduce((sum, row) => sum + parseNumber(row.value_eur), 0);
  const remaining = Math.max(total - visibleTotal, 0);
  const maxValue = Math.max(...assetRows.map((row) => parseNumber(row.value_eur)), 1);
  const priceStatus = assetRows.reduce<Record<string, number>>((acc, row) => {
    const status = String(row.price_status ?? "unknown");
    acc[status] = (acc[status] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="panel portfolioBreakdown">
      <div className="panelToolbar">
        <strong>Portfolio-Aufbau</strong>
        <span>{formatCurrency(total)} EUR · {portfolio?.positions?.length ?? 0} Positionen</span>
      </div>
      <div className="portfolioSummaryStrip">
        <Metric title="Top-Assets" value={String(assetRows.length)} />
        <Metric title="Weitere Assets" value={formatCurrency(remaining)} />
        <Metric title="Preisdeckung" value={(portfolio?.missing_price_assets ?? []).length === 0 ? "vollstaendig" : "offen"} />
        <Metric title="Preisstatus" value={Object.entries(priceStatus).map(([key, count]) => `${key}: ${count}`).join(" | ") || "-"} />
      </div>
      <div className="assetBars">
        {assetRows.map((row, index) => {
          const value = parseNumber(row.value_eur);
          const share = total > 0 ? (value / total) * 100 : 0;
          const width = Math.max(3, (value / maxValue) * 100);
          const accountRows = positions
            .filter((position) => String(position.asset) === String(row.asset))
            .sort((left, right) => parseNumber(right.value_eur) - parseNumber(left.value_eur))
            .slice(0, 4);
          return (
            <div className="assetBarRow" key={String(row.asset)}>
              <div className="assetBarHeader">
                <strong>{tokenDisplay(row)}</strong>
                <span>{formatCurrency(value)} EUR · {share.toFixed(1)}%</span>
              </div>
              <div className="barTrack" aria-hidden="true">
                <div className="barFill" style={{ width: `${width}%`, backgroundColor: flowColor(index) }} />
              </div>
              <div className="assetMeta">
                <span>{formatValue(row.quantity, "quantity")} {String(row.asset)}</span>
                <span>{String(row.position_count ?? 0)} Position(en)</span>
                <span>{String(row.price_status ?? "unknown")}</span>
                {row.token_risk_status ? (
                  <span className={`statusPill ${tokenRiskTone(row.token_risk_status)}`}>{String(row.token_risk_status)}</span>
                ) : null}
                <span>{String(row.priced_at_latest ?? "-")}</span>
              </div>
              {accountRows.length > 0 ? (
                <div className="assetAccounts">
                  {accountRows.map((position) => (
                    <span key={`${String(row.asset)}-${String(position.account)}`}>
                      {shortAccount(String(position.account))}: {formatCurrency(position.value_eur)} EUR
                    </span>
                  ))}
                </div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function PortfolioSourcesPanel({
  overview
}: {
  overview: Snapshot["portfolioSources"];
}) {
  const groups = overview?.groups ?? [];
  const accounts = overview?.accounts ?? [];
  const total = parseNumber(overview?.total_value_eur);
  const topGroups = groups.slice(0, 8);
  const maxValue = Math.max(...topGroups.map((group) => parseNumber(group.value_eur)), 1);
  const heliumAccounts = accounts.filter((account) => String(account.source_type ?? "").includes("legacy"));

  return (
    <div className="panel portfolioBreakdown">
      <div className="panelToolbar">
        <strong>Bestand nach Quelle / Wallet</strong>
        <span>{formatCurrency(total)} EUR · {groups.length} Quellen</span>
      </div>
      <div className="portfolioSummaryStrip">
        <Metric title="Binance/Pionex/Bitget" value={formatCurrency(groups
          .filter((group) => String(group.source_type) === "exchange")
          .reduce((sum, group) => sum + parseNumber(group.value_eur), 0))} />
        <Metric title="Solana Wallets" value={formatCurrency(groups
          .filter((group) => String(group.source_type) === "solana_wallet")
          .reduce((sum, group) => sum + parseNumber(group.value_eur), 0))} />
        <Metric title="Helium Legacy" value={formatCurrency(groups
          .filter((group) => String(group.source_type) === "legacy_wallet")
          .reduce((sum, group) => sum + parseNumber(group.value_eur), 0))} />
        <Metric title="Helium Wallets" value={String(heliumAccounts.length)} />
      </div>
      <div className="assetBars">
        {topGroups.map((group, index) => {
          const value = parseNumber(group.value_eur);
          const share = total > 0 ? (value / total) * 100 : 0;
          const width = Math.max(3, (value / maxValue) * 100);
          const accountRows = Array.isArray(group.accounts) ? group.accounts.slice(0, 5) : [];
          const assetRows = Array.isArray(group.asset_summary) ? group.asset_summary.slice(0, 4) : [];
          return (
            <div className="assetBarRow" key={String(group.source_group)}>
              <div className="assetBarHeader">
                <strong>{String(group.source_group)}</strong>
                <span>{formatCurrency(value)} EUR · {share.toFixed(1)}%</span>
              </div>
              <div className="barTrack" aria-hidden="true">
                <div className="barFill" style={{ width: `${width}%`, backgroundColor: flowColor(index) }} />
              </div>
              <div className="assetMeta">
                <span>{String(group.source_type)}</span>
                <span>{String(group.current_status ?? "ledger_current")}</span>
                <span>{String(group.account_count ?? 0)} Konto/Wallet</span>
                <span>{String(group.assets ?? 0)} Assets</span>
                <span>{String(group.position_count ?? 0)} Positionen</span>
              </div>
              <div className="assetAccounts">
                {accountRows.map((account) => (
                  <span key={String(account.account)}>
                    {shortAccount(String(account.account))}: {formatCurrency(account.value_eur)} EUR
                  </span>
                ))}
                {assetRows.map((asset) => (
                  <span key={`${String(group.source_group)}-${String(asset.asset)}`}>
                    {tokenDisplay(asset)} {formatValue(asset.quantity, "quantity")}
                  </span>
                ))}
              </div>
            </div>
          );
        })}
      </div>
      <TablePanel
        title="Quellen-Gruppen"
        rows={groups.map((group) => ({
          source_group: group.source_group,
          source_type: group.source_type,
          current_status: group.current_status,
          note: group.note,
          value_eur: group.value_eur,
          account_count: group.account_count,
          assets: group.assets,
          position_count: group.position_count
        }))}
        footer={overview?.methodology ?? ""}
      />
      <TablePanel
        title="Einzelne Wallets / Plattform-Konten"
        rows={accounts.map((account) => ({
          source_group: account.source_group,
          source_type: account.source_type,
          current_status: account.current_status,
          account: account.account,
          note: account.note,
          value_eur: account.value_eur,
          assets: account.assets,
          position_count: account.position_count
        }))}
      />
    </div>
  );
}

function PortfolioReconciliationPanel({
  report
}: {
  report: Snapshot["portfolioReconciliation"];
}) {
  const rows = report?.rows ?? [];
  const blockers = rows.filter((row) => String(row.severity) === "blocker").length;
  const warnings = rows.filter((row) => String(row.severity) === "warning").length;
  const expectedZero = parseNumber(report?.expected_zero_ledger_value_eur);
  const unverified = parseNumber(report?.live_unverified_ledger_value_eur);
  const topRows = rows.slice(0, 12);

  return (
    <div className="panel portfolioBreakdown">
      <div className="panelToolbar">
        <strong>Live-Abgleich gegen V1-API-Anker</strong>
        <span>{blockers} Blocker · {warnings} Warnungen</span>
      </div>
      <div className="portfolioSummaryStrip">
        <Metric title="Erwartet Null, Ledger offen" value={`${formatCurrency(expectedZero)} EUR`} />
        <Metric title="Noch ohne Live-Anker" value={`${formatCurrency(unverified)} EUR`} />
        <Metric title="Fehlende Wallets" value={String(report?.missing_wallets?.length ?? 0)} />
        <Metric title="Abgleichzeilen" value={String(rows.length)} />
      </div>
      <TablePanel
        title="Abweichungen und offene Live-Anker"
        rows={topRows.map((row) => ({
          severity: row.severity,
          status: row.status,
          source_group: row.source_group,
          asset: row.asset,
          ledger_quantity: row.ledger_quantity,
          ledger_value_eur: row.ledger_value_eur,
          external_quantity: row.external_quantity,
          external_value_eur: row.external_value_eur,
          delta_value_eur: row.delta_value_eur,
          next_action: row.next_action,
          evidence: row.evidence
        }))}
        footer={report?.methodology ?? ""}
      />
      <TablePanel
        title="Connector-Migration"
        rows={(report?.connector_actions ?? []).map((action, index) => ({
          nr: index + 1,
          action
        }))}
      />
    </div>
  );
}

function PortfolioAsOfPage({
  snapshot,
  asOfDate,
  onAsOfDateChange
}: {
  snapshot: Snapshot["portfolioAsOf"];
  asOfDate: string;
  onAsOfDateChange: (date: string) => void;
}) {
  const presets = ["2020-12-31", "2021-12-31", "2022-12-31", "2023-12-31", "2024-12-31", "2025-06-13"];
  const assetRows = snapshot?.asset_summary ?? [];
  const accountRows = snapshot?.account_summary ?? [];
  const positions = snapshot?.positions ?? [];
  const total = parseNumber(snapshot?.total_value_eur);
  const missing = snapshot?.missing_price_assets ?? [];
  const topAsset = assetRows[0];
  const topAccount = accountRows[0];
  const pricedAssets = assetRows.filter((row) => String(row.price_status ?? "missing") !== "missing").length;
  const coverage = assetRows.length === 0 ? 100 : Math.round((pricedAssets / assetRows.length) * 100);

  return (
    <Stack>
      <div className="asOfHero">
        <div>
          <span className="heroKicker">Stichtags-Cockpit</span>
          <h2>{snapshot?.label ?? "Portfolio zum Stichtag"}</h2>
          <p>
            Mengen aus dem Ledger bis einschliesslich Stichtag, Bewertung mit dem letzten belegten EUR-Preis am oder vor dem Stichtag.
          </p>
        </div>
        <div className="asOfControls">
          <label>
            Stichtag
            <input type="date" value={asOfDate} onChange={(event) => onAsOfDateChange(event.target.value)} />
          </label>
          <div className="presetRow">
            {presets.map((preset) => (
              <button
                key={preset}
                className={asOfDate === preset ? "active" : ""}
                type="button"
                onClick={() => onAsOfDateChange(preset)}
              >
                {preset.slice(0, 4)}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="asOfMetricGrid">
        <Metric title="Besitzwert" value={`${formatCurrency(total)} EUR`} />
        <Metric title="Assets" value={String(assetRows.length)} />
        <Metric title="Konten/Wallets" value={String(accountRows.length)} />
        <Metric title="Preisdeckung" value={`${coverage}%`} />
      </div>

      {snapshot?.transfer_context_note ? (
        <div className="notice inlineNotice">
          {snapshot.transfer_context_note}
        </div>
      ) : null}

      <div className="asOfCockpitGrid">
        <div className="panel asOfMainCard">
          <div className="panelToolbar">
            <strong>Vermoegensaufbau</strong>
            <span>{snapshot?.as_of ? formatDateTime(snapshot.as_of) : "-"}</span>
          </div>
          <div className="asOfMainValue">{formatCurrency(total)} EUR</div>
          <div className="asOfSubGrid">
            <StatusRow label="Groesstes Asset" value={topAsset ? `${String(topAsset.asset)} · ${formatCurrency(topAsset.value_eur)} EUR` : "-"} />
            <StatusRow label="Groesster Ort" value={topAccount ? `${shortAccount(String(topAccount.account))} · ${formatCurrency(topAccount.value_eur)} EUR` : "-"} />
            <StatusRow label="Fehlende Preise" value={missing.length ? missing.join(", ") : "keine"} />
            <StatusRow label="Ausgeklammert" value={`${formatCurrency(snapshot?.excluded_value_eur)} EUR`} />
          </div>
        </div>
        <div className="panel">
          <div className="panelToolbar">
            <strong>Preisstatus</strong>
            <span>{pricedAssets}/{assetRows.length}</span>
          </div>
          <div className="statusRows">
            <StatusRow label="Bewertet" value={String(pricedAssets)} />
            <StatusRow label="Offen" value={String(missing.length)} />
            <StatusRow label="Aliase aufgeloest" value={String(snapshot?.resolved_account_aliases?.length ?? 0)} />
            <StatusRow label="Gekuerzte Wallets offen" value={String(snapshot?.unresolved_truncated_accounts?.length ?? 0)} />
          </div>
        </div>
      </div>

      <PortfolioBreakdownPanel portfolio={snapshot ? {
        total_value_eur: snapshot.total_value_eur,
        missing_price_assets: snapshot.missing_price_assets,
        positions: snapshot.positions,
        asset_summary: snapshot.asset_summary,
        account_summary: snapshot.account_summary,
        excluded_account_summary: snapshot.excluded_account_summary,
        excluded_value_eur: snapshot.excluded_value_eur,
        resolved_account_aliases: snapshot.resolved_account_aliases,
        unresolved_truncated_accounts: snapshot.unresolved_truncated_accounts
      } : undefined} />

      <TablePanel
        title="Stichtag nach Asset"
        rows={assetRows}
        footer={`Summe: ${formatCurrency(snapshot?.total_value_eur)} EUR | Fehlende Preise: ${missing.join(", ") || "keine"}`}
      />
      <TablePanel
        title="Stichtag nach Konto/Wallet"
        rows={accountRows}
        footer="Aggregierte Orte des Besitzes zum gewaehlten Stichtag."
      />
      <TablePanel
        title="Stichtags-Positionen"
        rows={positions}
        footer={snapshot?.methodology ?? ""}
      />
    </Stack>
  );
}

function ReviewPanel({
  review,
  reviewTasks,
  jupiterRiskReview,
  decisions,
  suggestions,
  evidenceTraces,
  reviewViewMode,
  onReviewViewModeChange,
  onAcceptSuggestion,
  onCanonicalizeEvidenceTraces,
  onDownload
}: {
  review: Snapshot["review"];
  reviewTasks: Snapshot["reviewTasks"];
  jupiterRiskReview: Snapshot["jupiterRiskReview"];
  decisions: Array<Record<string, unknown>>;
  suggestions: Array<Record<string, unknown>>;
  evidenceTraces: Snapshot["reviewEvidenceTraces"];
  reviewViewMode: ReviewViewMode;
  onReviewViewModeChange: (mode: ReviewViewMode) => void;
  onAcceptSuggestion: (suggestionId: string) => void;
  onCanonicalizeEvidenceTraces: (execute: boolean) => void;
  onDownload: (path: string) => void;
}) {
  const [filter, setFilter] = useState("all");
  const issues = review?.issues ?? [];
  const filteredIssues = issues.filter((issue) => {
    if (filter === "all") {
      return true;
    }
    if (filter === "blocking") {
      return issue.blocks_export === true;
    }
    return String(issue.severity) === filter;
  });
  const groupedIssues = ["high", "medium", "low"].map((severity) => ({
    severity,
    count: issues.filter((issue) => String(issue.severity) === severity).length
  }));

  return (
    <Stack>
      <div className={`panel reviewStatusPanel ${review?.allow_export ? "ok" : "blocked"}`}>
        <div className="panelToolbar">
          <strong>Review-Freigabe</strong>
          <select value={filter} onChange={(event) => setFilter(event.target.value)}>
            <option value="all">Alle Issues</option>
            <option value="blocking">Blockierend</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </div>
        <div className="reviewSummary">
          <Metric title="Export" value={review?.allow_export ? "erlaubt" : "blockiert"} />
          <Metric title="Aktuell offen" value={String(review?.issues_current_open ?? review?.issues_open ?? 0)} />
          <Metric title="Historisch" value={String(review?.issues_historical_open ?? 0)} />
          <Metric title="Gesamt sichtbar" value={String(review?.issues_open_total ?? review?.issues_open ?? 0)} />
          <Metric title="Blockierend" value={String(review?.blocking_issues_open ?? 0)} />
          <Metric title="High" value={String(review?.issues_high_open ?? 0)} />
          <Metric title="Medium" value={String(review?.issues_medium_open ?? 0)} />
          <Metric title="Low" value={String(review?.issues_low_open ?? 0)} />
        </div>
        {issues.length === 0 ? (
          <div className="notice inlineNotice reviewNotice">Keine offenen Review-Issues.</div>
        ) : (
          <div className="severityStrip">
            {groupedIssues.map((item) => (
              <span key={item.severity} className={`severityPill ${item.severity}`}>
                {item.severity}: {item.count}
              </span>
            ))}
          </div>
        )}
      </div>
      <div className="taxViewSwitch" role="tablist" aria-label="Review Ansicht">
        <button type="button" className={reviewViewMode === "tasks" ? "active" : ""} onClick={() => onReviewViewModeChange("tasks")}>
          Aufgaben
        </button>
        <button type="button" className={reviewViewMode === "evidence" ? "active" : ""} onClick={() => onReviewViewModeChange("evidence")}>
          Belegspuren
        </button>
        <button type="button" className={reviewViewMode === "expert" ? "active" : ""} onClick={() => onReviewViewModeChange("expert")}>
          Expertenmodus
        </button>
      </div>
      <TokenRiskReviewPanel report={jupiterRiskReview} onDownload={onDownload} />
      <TokenRiskDocumentationPanel decisions={decisions} onDownload={onDownload} />
      <ReviewTasksPanel tasks={reviewTasks} onDownload={onDownload} onAcceptSuggestion={onAcceptSuggestion} />
      {reviewViewMode !== "tasks" ? (
        <>
      <div className="panel">
        <div className="panelToolbar">
          <strong>Review-Belegspuren</strong>
          <span className={`statusPill ${(evidenceTraces?.legacy_ref_count ?? 0) === 0 && (evidenceTraces?.missing_decision_count ?? 0) === 0 ? "ok" : "blocked"}`}>
            {(evidenceTraces?.legacy_ref_count ?? 0) === 0 && (evidenceTraces?.missing_decision_count ?? 0) === 0 ? "vollstaendig" : "pruefen"}
          </span>
          <div className="buttonRow">
            <button type="button" onClick={() => onCanonicalizeEvidenceTraces(false)}>
              <RefreshCcw size={16} />
              Dry-run
            </button>
            <button type="button" onClick={() => onCanonicalizeEvidenceTraces(true)}>
              <Check size={16} />
              Kanonisieren
            </button>
          </div>
        </div>
        <div className="reviewSummary">
          <Metric title="Belegspuren" value={String(evidenceTraces?.traces_count ?? 0)} />
          <Metric title="Kanonisch" value={String(evidenceTraces?.canonical_count ?? 0)} />
          <Metric title="Legacy" value={String(evidenceTraces?.legacy_ref_count ?? 0)} />
          <Metric title="Fehlend" value={String(evidenceTraces?.missing_decision_count ?? 0)} />
        </div>
        <TablePanel
          title="Belegspur-Status"
          rows={(evidenceTraces?.traces ?? []).map((trace) => ({
            status: trace.status,
            scope: trace.scope,
            evidence_trace_status: trace.evidence_trace_status,
            import_effect: trace.import_effect,
            target_changed: trace.target_changed,
            decision_id: trace.decision_id,
            stored_evidence_ref: trace.stored_evidence_ref,
            canonical_evidence_ref: trace.canonical_evidence_ref,
            note: trace.note
          }))}
          rowActions={[
            {
              label: "Trace oeffnen",
              icon: <FileJson size={16} />,
              onClick: (row) => onDownload(String(row.canonical_evidence_ref ?? ""))
            }
          ]}
          footer={evidenceTraces?.methodology ?? "Belegspuren werden geladen."}
          compact
        />
      </div>
        </>
      ) : null}
      {reviewViewMode === "expert" ? (
        <>
      <TablePanel
        title="Review-Issues"
        rows={filteredIssues}
        footer={`Filter: ${filter} | Angezeigt: ${filteredIssues.length}/${issues.length}`}
      />
      <TablePanel
        title="Review-Entscheidungsvorschlaege"
        rows={suggestions.map((suggestion) => ({
          suggestion_id: suggestion.suggestion_id,
          confidence: suggestion.confidence,
          decision_type: suggestion.decision_type,
          scope: suggestion.scope,
          title: suggestion.title,
          evidence_ref: suggestion.evidence_ref,
          auto_persist: suggestion.auto_persist,
          rationale: suggestion.rationale
        }))}
        rowActions={[
          {
            label: "Vorschlag uebernehmen",
            icon: <Check size={16} />,
            onClick: (row) => onAcceptSuggestion(String(row.suggestion_id ?? ""))
          }
        ]}
        footer="Vorschlaege werden nicht automatisch gespeichert und erzeugen keine Buchung."
      />
      <TablePanel
        title="Review-Entscheidungen"
        rows={decisions.map((decision) => ({
          created_at: decision.created_at,
          decision_type: decision.decision_type,
          scope: decision.scope,
          title: decision.title,
          actor: decision.actor,
          source: decision.source,
          evidence_ref: decision.evidence_ref,
          affected_ids: Array.isArray(decision.affected_ids) ? decision.affected_ids.join(", ") : ""
        }))}
        footer={`Entscheidungen: ${decisions.length}`}
      />
        </>
      ) : null}
    </Stack>
  );
}

type ReviewBucketDisplay = {
  label: string;
  focus: string;
  tone: string;
};

const priceQualityBucketDisplay: Record<string, ReviewBucketDisplay> = {
  stablecoin_fx_review: {
    label: "Stablecoin-FX",
    focus: "FX- und EUR/USD-Belege fuer Stablecoins pruefen",
    tone: "fx"
  },
  solscan_signature_review: {
    label: "Solscan-Signaturen",
    focus: "Solana-Signaturen und On-Chain-Evidenz pruefen",
    tone: "solscan"
  },
  binance_normalizer_review: {
    label: "Binance-Normalizer",
    focus: "Bitget/Binance-Quellfelder und Normalisierung pruefen",
    tone: "exchange"
  },
  event_quote_evidence_review: {
    label: "Event-Quote-Evidenz",
    focus: "Transaktionsnahe Quotes und Ableitungen pruefen",
    tone: "quotes"
  }
};

function ReviewTasksPanel({
  tasks,
  onDownload,
  onAcceptSuggestion
}: {
  tasks: Snapshot["reviewTasks"];
  onDownload: (path: string) => void;
  onAcceptSuggestion: (suggestionId: string) => void;
}) {
  const rows = tasks?.tasks ?? [];
  const solscanTraceTask = rows.find((task) => task.scope === "solscan_iot:blockpit_missing_signatures");
  const topRows = rows.filter((task) => task !== solscanTraceTask).slice(0, 8);
  return (
    <div className="panel">
      <div className="panelToolbar">
        <strong>Gefuehrte Review-Aufgaben</strong>
        <span>{tasks?.generated_at ? formatDateTime(tasks.generated_at) : "-"}</span>
      </div>
      <div className="reviewSummary">
        <Metric title="Offen" value={String(tasks?.open_tasks ?? 0)} />
        <Metric title="Blockierend" value={String(tasks?.blocking_tasks ?? 0)} />
        <Metric title="FIFO-relevant" value={String(tasks?.fifo_relevant_tasks ?? 0)} />
        <Metric title="Belege/Preise" value={String(tasks?.evidence_tasks ?? 0)} />
        <Metric title="High" value={String(tasks?.high_priority_tasks ?? 0)} />
        <Metric title="Medium" value={String(tasks?.medium_priority_tasks ?? 0)} />
      </div>
      {rows.length === 0 ? (
        <div className="notice inlineNotice reviewNotice">Keine gefuehrten Review-Aufgaben offen.</div>
      ) : (
        <div className="reviewTaskList">
          {solscanTraceTask ? (
            <div className="reviewTaskItem high bucketTask solscan">
              <div className="reviewTaskHead">
                <div className="reviewTaskTitle">
                  <span>Solscan FIFO</span>
                  <strong>{String(solscanTraceTask.title ?? "Solscan/RPC Evidence Trace")}</strong>
                </div>
                <span className="statusPill ok">{String(solscanTraceTask.decision_status ?? "rpc_verified")}</span>
              </div>
              <p>{String(solscanTraceTask.detail ?? "-")}</p>
              <div className="reviewTaskMeta">
                <span>{String(solscanTraceTask.category ?? "evidence")}</span>
                <span title={String(solscanTraceTask.scope ?? "")}>{shortAccount(String(solscanTraceTask.scope ?? ""))}</span>
                <span>Importeffekt none</span>
              </div>
              <div className="reviewTaskAction">
                <button type="button" onClick={() => onDownload("/api/v1/import/solscan/evidence-trace")}>
                  <FileJson size={16} />
                  Trace oeffnen
                </button>
                <button type="button" onClick={() => onAcceptSuggestion("solscan_iot_missing_signatures_rpc_verified")}>
                  <Check size={16} />
                  Vorschlag uebernehmen
                </button>
                <code>/api/v1/import/solscan/evidence-trace</code>
              </div>
            </div>
          ) : null}
          {topRows.map((task) => {
            const scope = String(task.scope ?? "");
            const isTokenRiskDocumentation = scope.startsWith("token_risk:spam_review:");
            const bucketKey = scope.startsWith("price_quality_bucket:")
              ? scope.replace("price_quality_bucket:", "")
              : "";
            const bucket = priceQualityBucketDisplay[bucketKey];
            const actionPath = String(task.action_path ?? "");
            const suggestionId = actionPath.includes("/review/decision-suggestions/")
              ? actionPath.split("/review/decision-suggestions/")[1]?.replace("/accept", "")
              : "";
            return (
              <div
                key={String(task.task_id)}
                className={`reviewTaskItem ${String(task.priority ?? "low")} ${task.blocks_export ? "blocked" : ""} ${bucket ? `bucketTask ${bucket.tone}` : ""}`}
              >
                <div className="reviewTaskHead">
                  <div className="reviewTaskTitle">
                    {bucket ? <span>{bucket.label}</span> : null}
                    <strong>{String(task.title ?? "-")}</strong>
                  </div>
                  <span className={`statusPill ${task.blocks_export ? "blocked" : priorityTone(task.priority)}`}>
                    {String(task.priority ?? "-")}
                  </span>
                </div>
                <p>{bucket?.focus ?? String(task.detail ?? "-")}</p>
                {bucket ? <p className="reviewTaskDetail">{String(task.detail ?? "-")}</p> : null}
                <div className="reviewTaskMeta">
                  <span>{String(task.category ?? "-")}</span>
                  <span title={scope}>{bucket?.label ?? shortAccount(scope)}</span>
                  {isTokenRiskDocumentation ? <span className="statusPill ok">keine Datenwirkung</span> : null}
                  {task.count !== null && task.count !== undefined ? <span>{String(task.count)} Gruppen</span> : null}
                  {task.asset ? <span>{tokenDisplay(task)}</span> : null}
                  {task.token_risk_status ? (
                    <span className={`statusPill ${tokenRiskTone(task.token_risk_status)}`}>{String(task.token_risk_status)}</span>
                  ) : null}
                  {task.value_eur !== null && task.value_eur !== undefined ? (
                    <span>{formatCurrency(task.value_eur)} EUR</span>
                  ) : null}
                </div>
                <div className="reviewTaskAction">
                  <button
                    type="button"
                    disabled={!actionPath || actionPath === "-"}
                    onClick={() => {
                      if (suggestionId) {
                        onAcceptSuggestion(suggestionId);
                      } else {
                        onDownload(actionPath);
                      }
                    }}
                    title={actionPath || "Kein API-Pfad vorhanden"}
                  >
                    {suggestionId ? <Check size={16} /> : <ExternalLink size={16} />}
                    {String(task.action_label ?? "Pruefen")}
                  </button>
                  <code title={actionPath || "-"}>{actionPath || "-"}</code>
                </div>
              </div>
            );
          })}
        </div>
      )}
      <div className="footer">{tasks?.methodology ?? "Review-Aufgaben werden geladen."}</div>
    </div>
  );
}

function TokenRiskReviewPanel({
  report,
  onDownload
}: {
  report: Snapshot["jupiterRiskReview"];
  onDownload: (path: string) => void;
}) {
  const rows = report?.items ?? [];
  const displayRows = rows.map((token) => ({
    symbol: token.symbol ?? "-",
    name: token.name ?? "-",
    mint: shortAccount(String(token.mint ?? "")),
    risiko: token.risk_status ?? "-",
    verified: token.is_verified === true ? "ja" : token.is_verified === false ? "nein" : "-",
    score: token.organic_score_label ?? token.organic_score ?? "-",
    liquidity_usd: token.liquidity_usd ?? "-",
    fundstellen: Array.isArray(token.discovered_sources) ? token.discovered_sources.join(", ") : "",
    refreshed: token.refreshed_at ? formatDateTime(String(token.refreshed_at)) : "-"
  }));
  return (
    <div className="panel">
      <div className="panelToolbar">
        <strong>Token-Risiko-Review</strong>
        <span className={`statusPill ${(report?.spam_review_count ?? 0) > 0 ? "blocked" : "ok"}`}>
          {(report?.spam_review_count ?? 0) > 0 ? "spam_review sichtbar" : "keine Spam-Markierung"}
        </span>
        <button type="button" onClick={() => onDownload("/api/v1/sources/jupiter/tokens/risk-review?risk_status=spam_review&limit=200")}>
          <FileJson size={16} />
          JSON
        </button>
      </div>
      <div className="reviewSummary">
        <Metric title="Spam Review" value={String(report?.spam_review_count ?? 0)} />
        <Metric title="Review" value={String(report?.review_count ?? 0)} />
        <Metric title="Plausibel" value={String(report?.unverified_plausible_count ?? 0)} />
        <Metric title="Verified" value={String(report?.verified_count ?? 0)} />
      </div>
      <TablePanel
        title="Spam-/Fake-Token Kandidaten"
        rows={displayRows}
        compact
        footer={report?.methodology ?? "Read-only Token-Risiko aus Jupiter Metadata Cache. Keine automatische Ausbuchung."}
      />
    </div>
  );
}

function TokenRiskDocumentationPanel({
  decisions,
  onDownload,
  compact = false
}: {
  decisions: Array<Record<string, unknown>>;
  onDownload: (path: string) => void;
  compact?: boolean;
}) {
  const tokenRiskDecisions = decisions.filter((decision) => decision.decision_type === "token_risk_documentation");
  const rows = tokenRiskDecisions.map((decision) => {
    const payload = recordPayload(decision.payload);
    const accounts = Array.isArray(payload.accounts) ? payload.accounts.map((account: unknown) => shortAccount(String(account))).join(", ") : "";
    return {
      asset: payload.asset ?? scopePart(String(decision.scope ?? ""), "asset") ?? "-",
      token: tokenDisplay({
        token_symbol: payload.token_symbol,
        token_name: payload.token_name,
        token_mint: payload.token_mint
      }),
      risiko: payload.token_risk_status ?? "-",
      wert_eur: payload.value_eur ?? "-",
      menge: payload.quantity ?? "-",
      mint: payload.token_mint ? shortAccount(String(payload.token_mint)) : "-",
      accounts,
      wirkung: [
        `Import ${payload.import_effect ?? "none"}`,
        `Ledger ${payload.ledger_effect ?? "none"}`,
        `FIFO ${payload.fifo_effect ?? "none"}`,
        `Tax ${payload.tax_line_effect ?? "none"}`
      ].join(" | "),
      evidence_ref: decision.evidence_ref ?? "-",
      entschieden: decision.created_at ? formatDateTime(String(decision.created_at)) : "-"
    };
  });
  const documentedValue = tokenRiskDecisions.reduce((sum, decision) => {
    const payload = recordPayload(decision.payload);
    return sum + parseNumber(payload.value_eur);
  }, 0);
  return (
    <div className="panel">
      <div className="panelToolbar">
        <strong>Token-Risiko Dokumentation</strong>
        <span className={`statusPill ${tokenRiskDecisions.length > 0 ? "ok" : "warning"}`}>
          {tokenRiskDecisions.length > 0 ? `${tokenRiskDecisions.length} dokumentiert` : "nichts dokumentiert"}
        </span>
        <button type="button" onClick={() => onDownload("/api/v1/export/token-risk-documentation.csv")}>
          <FileJson size={16} />
          CSV
        </button>
      </div>
      <div className="reviewSummary">
        <Metric title="Dokumentiert" value={String(tokenRiskDecisions.length)} />
        <Metric title="Dokumentierter Wert" value={`${formatCurrency(documentedValue)} EUR`} />
        <Metric title="Datenwirkung" value="keine" />
      </div>
      {tokenRiskDecisions.length === 0 ? (
        <div className="notice inlineNotice reviewNotice">
          Noch keine Token-Risiko-Dokumentation angenommen. Offene Spam/Dust-Vorschlaege bleiben in den Review-Aufgaben sichtbar.
        </div>
      ) : null}
      <TablePanel
        title="Dokumentierte Spam-/Dust-Token"
        rows={rows}
        compact={compact}
        rowActions={[
          {
            label: "Evidence oeffnen",
            icon: <ExternalLink size={16} />,
            onClick: (row) => onDownload(String(row.evidence_ref ?? ""))
          }
        ]}
        footer="Read-only Nachweis: angenommene Review-Entscheidungen ohne Import-, Ledger-, FIFO- oder Steuerzeilenwirkung."
      />
    </div>
  );
}

function recordPayload(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function scopePart(scope: string, key: string): string | null {
  const marker = `${key}:`;
  if (!scope.includes(marker)) {
    return null;
  }
  const value = scope.split(marker, 2)[1]?.split(":", 1)[0]?.trim();
  return value || null;
}

function SeparationTrendPanel({ report }: { report: Snapshot["separationReport"] }) {
  const trend = report?.trend ?? [];
  const locations = report?.investment_locations ?? [];
  const unrealizedLots = report?.unrealized_lots ?? [];
  const priceQuality = report?.price_quality ?? [];
  const latestValue = trend.length ? trend[trend.length - 1]?.total_value_eur : report?.virtual_wallet?.total_value_eur;
  const maxValue = Math.max(...trend.map((point) => Number(point.total_value_eur ?? 0)), 1);
  const width = 920;
  const height = 260;
  const left = 54;
  const right = 24;
  const top = 24;
  const bottom = 42;
  const chartWidth = width - left - right;
  const chartHeight = height - top - bottom;
  const points = trend.map((point, index) => {
    const x = left + (trend.length <= 1 ? 0 : (index / (trend.length - 1)) * chartWidth);
    const value = Number(point.total_value_eur ?? 0);
    const y = top + chartHeight - (value / maxValue) * chartHeight;
    return { x, y, value, date: String(point.date ?? "") };
  });
  const path = points
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
    .join(" ");
  return (
    <Stack>
      <div className="panel separationPanel">
        <div className="panelToolbar">
          <strong>Trennungs-Portfolio Verlauf</strong>
          <span>{report?.cutoff_date ?? "2025-06-13"}</span>
        </div>
        <div className="reviewSummary">
          <Metric title="Aktueller Neubestand" value={`${formatCurrency(latestValue)} EUR`} />
          <Metric title="Anschaffungskosten" value={`${formatCurrency(report?.cost_basis_eur_total)} EUR`} />
          <Metric title="Unrealisiert G/V" value={`${formatCurrency(report?.unrealized_gain_loss_eur_total)} EUR`} />
          <Metric title="Trendpunkte" value={String(trend.length)} />
          <Metric title="Investment-Orte" value={String(locations.length)} />
          <Metric title="Lot-Luecken" value={(report?.unmatched_lot_assets ?? []).join(", ") || "keine"} />
          <Metric title="Fehlende Preise" value={(report?.virtual_wallet?.missing_price_assets ?? []).join(", ") || "keine"} />
        </div>
        <div className="trendCanvas">
          {trend.length === 0 ? (
            <div className="empty">Keine Trenddaten vorhanden.</div>
          ) : (
            <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Trennungs-Portfolio Verlauf">
              <line x1={left} y1={top + chartHeight} x2={width - right} y2={top + chartHeight} />
              <line x1={left} y1={top} x2={left} y2={top + chartHeight} />
              <text x={left} y={height - 12}>{points[0]?.date}</text>
              <text x={width - right - 84} y={height - 12}>{points[points.length - 1]?.date}</text>
              <text x={left + 4} y={top + 14}>{formatCurrency(maxValue)} EUR</text>
              <path d={path} />
              {points.map((point, index) => (
                <g key={`${point.date}-${index}`}>
                  <circle cx={point.x} cy={point.y} r="4" />
                  <title>{`${point.date}: ${formatCurrency(point.value)} EUR`}</title>
                </g>
              ))}
            </svg>
          )}
        </div>
      </div>
      <TablePanel
        title="Anschaffungslots seit Stichtag"
        rows={unrealizedLots}
        footer="Restbestand je FIFO-Lot: Anschaffungskosten, aktueller Wert und unrealisiertes Ergebnis; real steuerwirksam erst bei Veraeusserung."
      />
      <TablePanel
        title="Preisqualitaet Stichtagswallet"
        rows={priceQuality}
        footer="ok = frische externe Preisquelle; aged/stale = alter Preis; derived_event_quote = aus Transaktions-Quote statt unabhaengiger Marktpreisquelle."
      />
      <TablePanel
        title="Investment-Orte seit Stichtag"
        rows={locations}
        footer="Account-/Asset-Liste fuer den aktuell positiven Netto-Neubestand; keine steuerwirksame Buchung."
      />
    </Stack>
  );
}

function FiatDepositPanel({
  report,
  onDownload
}: {
  report: Snapshot["fiatDeposits"];
  onDownload: (path: string) => void;
}) {
  const rows = report?.rows ?? [];
  return (
    <Stack>
      <div className="panel">
        <div className="panelToolbar">
          <strong>FIAT-EUR Einzahlungen nach Binance</strong>
          <span>ab {report?.cutoff_date ?? "2025-06-13"}</span>
        </div>
        <div className="reviewSummary">
          <Metric title="Brutto laut Zahlungsbeleg" value={`${formatCurrency(report?.total_deposit_amount_eur)} EUR`} />
          <Metric title="Binance-Gutschrift" value={`${formatCurrency(report?.total_receive_amount_eur)} EUR`} />
          <Metric title="Differenz/Gebuehr" value={`${formatCurrency(report?.total_fee_or_difference_eur)} EUR`} />
          <Metric title="Buchungen" value={String(report?.rows_count ?? 0)} />
        </div>
      </div>
      <TablePanel
        title="Einzelne FIAT-EUR Einzahlungen"
        rows={rows.map((row) => ({
          time_utc: row.time_utc,
          deposit_amount_original: row.deposit_amount_original,
          receive_amount_eur: row.receive_amount_eur,
          method: row.method,
          status: row.status,
          transaction_id: row.transaction_id,
          source_file: row.source_file,
          source_row: row.source_row
        }))}
        actionLabel="CSV Export"
        onAction={() => onDownload("/api/v1/export/binance-fiat-deposits.csv")}
        footer={report?.methodology ?? "Nur externe Fiat-Einzahlungen; interne Spot-Gegenbuchungen werden nicht doppelt gezaehlt."}
      />
    </Stack>
  );
}

function ImportCoveragePanel({ coverage }: { coverage: Snapshot["importCoverage"] }) {
  const rows = coverage?.rows ?? [];
  const blockedRows = rows.filter((row) => row.can_import !== true);
  return (
    <Stack>
      <div className="grid">
        <Metric title="Dateien gescannt" value={String(coverage?.files_scanned ?? 0)} />
        <Metric title="Dateien gesamt" value={String(coverage?.files_total ?? coverage?.files_scanned ?? 0)} />
        <Metric title="Importierbar" value={String(coverage?.importable ?? 0)} />
        <Metric title="Blockiert" value={String(coverage?.blocked ?? 0)} />
        <Metric title="Scan" value={coverage?.scan_truncated ? `gekürzt nach ${coverage.scan_seconds}s` : `${coverage?.scan_seconds ?? 0}s`} />
      </div>
      <TablePanel
        title="Import-Coverage blockiert"
        rows={blockedRows.map((row) => ({
          source: row.source,
          file_format: row.file_format,
          row_count: row.row_count,
          missing_required_groups: Array.isArray(row.missing_required_groups)
            ? row.missing_required_groups.join(", ")
            : "",
          file_path: row.file_path,
          error: row.error
        }))}
        footer={`Blockiert: ${blockedRows.length}/${rows.length}`}
      />
    </Stack>
  );
}

function ParserPreflightPanel({ preflight }: { preflight: Snapshot["parserPreflight"] }) {
  const files = preflight?.files ?? [];
  return (
    <Stack>
      <div className="grid">
        <Metric title="Parser offen" value={String(preflight?.parser_needed ?? 0)} />
        <Metric title="Inspiziert" value={String(preflight?.inspected ?? 0)} />
        <Metric
          title="Warnungen"
          value={String(files.filter((file) => Array.isArray(file.warnings) && file.warnings.length > 0).length)}
        />
      </div>
      <TablePanel
        title="Parser-Preflight"
        rows={files.map((file) => ({
          parser_kind: file.parser_kind,
          row_count: file.row_count,
          file_format: file.file_format,
          columns: Array.isArray(file.columns) ? file.columns.slice(0, 8).join(", ") : "",
          warnings: Array.isArray(file.warnings) ? file.warnings.join(" | ") : "",
          relative_path: file.relative_path
        }))}
        footer="Diese Dateien bleiben blockiert, bis ein dedizierter Parser getestet ist."
      />
    </Stack>
  );
}

function BlockpitSolanaPreflightPanel({
  report
}: {
  report: Snapshot["blockpitSolanaPreflight"];
}) {
  const classes = report?.classes ?? [];
  const blocked = report?.blocked_classes ?? [];
  const importable = report?.importable_classes ?? [];
  const priceSourceStatus = report?.price_source_status ?? [];
  const historicalPriceRequirements = report?.historical_price_requirements ?? [];
  const combinedReadiness = report?.combined_readiness;
  const combinedRequiredOpening = combinedReadiness?.required_opening_balance ?? {};
  const combinedIncidents = combinedReadiness?.incidents ?? [];
  const openingEvidenceRows = combinedIncidents.flatMap((incident) =>
    Array.isArray(incident.evidence_candidates)
      ? incident.evidence_candidates.map((candidate) => ({
          asset: incident.asset,
          score: candidate.score,
          event_time: candidate.event_time,
          source: candidate.source,
          event_type: candidate.event_type,
          account: candidate.account,
          quantity: candidate.quantity,
          required_quantity: candidate.required_quantity,
          quantity_delta: candidate.quantity_delta,
          tx_id: candidate.tx_id
        }))
      : []
  );
  const missingAssets = Array.from(
    new Set(
      classes.flatMap((item) =>
        Array.isArray(item.missing_latest_price_assets)
          ? item.missing_latest_price_assets.map((asset) => String(asset))
          : []
      )
    )
  ).sort();
  const requiredOpeningAssets = Array.from(
    new Set(
      Object.keys(combinedRequiredOpening).length > 0
        ? Object.keys(combinedRequiredOpening)
        : classes.flatMap((item) =>
            Object.keys((item.required_opening_balance as Record<string, unknown> | undefined) ?? {})
          )
    )
  ).sort();
  const classRows = classes.map((item) => {
    const requiredOpening = (item.required_opening_balance as Record<string, unknown> | undefined) ?? {};
    const grossPositive = (item.gross_positive_movements as Record<string, unknown> | undefined) ?? {};
    const grossNegative = (item.gross_negative_movements as Record<string, unknown> | undefined) ?? {};
    return {
      status: item.status,
      row_class: item.row_class,
      rows: item.rows,
      missing_prices: Array.isArray(item.missing_latest_price_assets)
        ? item.missing_latest_price_assets.join(", ")
        : "",
      opening_balance: formatAssetMap(requiredOpening),
      gross_positive: formatAssetMap(grossPositive),
      gross_negative: formatAssetMap(grossNegative),
      blockers: Array.isArray(item.blocker_codes) ? item.blocker_codes.join(" | ") : ""
    };
  });
  return (
    <Stack>
      <div className="panel">
        <div className="panelToolbar">
          <strong>Blockpit/Solana Preflight</strong>
          <span className={`statusPill ${importable.length > 0 && blocked.length === 0 ? "ok" : "blocked"}`}>
            {blocked.length === 0 && classes.length > 0 ? "importierbar" : "blockiert"}
          </span>
        </div>
        <div className="reviewSummary">
          <Metric title="Gefilterte Zeilen" value={String(report?.filtered_rows ?? 0)} />
          <Metric title="Importierbare Klassen" value={String(importable.length)} />
          <Metric title="Blockierte Klassen" value={String(blocked.length)} />
          <Metric title="Fehlende Preisassets" value={missingAssets.join(", ") || "keine"} />
          <Metric title="Historische Preisjobs" value={String(historicalPriceRequirements.length)} />
          <Metric title="Chronologischer Status" value={combinedReadiness?.status === "importable" ? "importierbar" : "blockiert"} />
          <Metric title="Vorbestand-Assets" value={requiredOpeningAssets.join(", ") || "keine"} />
          <Metric title="Live geaendert" value={report?.target_changed ? "ja" : "nein"} />
        </div>
      </div>
      <TablePanel
        title="Chronologischer Startbestand"
        rows={Object.entries(combinedRequiredOpening).map(([asset, quantity]) => ({
          asset,
          required_quantity: quantity
        }))}
        footer={`Entscheidend fuer den Liveimport: alle gefilterten Solana-Zeilen werden zeitlich zusammen bewertet. Klassenblocker darunter sind nur Diagnosewerte.`}
      />
      <TablePanel
        title="Erste chronologische Defizite"
        rows={combinedIncidents.map((item) => ({
          asset: item.asset,
          required_quantity: item.required_quantity,
          first_deficit_at: item.first_deficit_at,
          row_class: item.row_class,
          balance_before: item.balance_before,
          movement_quantity: item.movement_quantity,
          balance_after: item.balance_after,
          evidence_candidates: Array.isArray(item.evidence_candidates) ? item.evidence_candidates.length : 0,
          transaction_id: typeof item.source_row === "object" && item.source_row !== null
            ? (item.source_row as Record<string, unknown>)["Trx. ID (optional)"]
            : ""
        }))}
        footer="Diese Tabelle zeigt, wo der benoetigte Startbestand erstmals sichtbar wird."
      />
      <TablePanel
        title="Moegliche Herkunft aus V2-Daten"
        rows={openingEvidenceRows}
        footer="Kandidaten sind Hinweise aus bereits importierten Canonical Events. Sie sind kein automatischer Import und keine finale Belegentscheidung."
      />
      <TablePanel
        title="Preisquellen fuer fehlende Assets"
        rows={priceSourceStatus.map((item) => ({
          asset: item.asset,
          status: item.status,
          configured: item.configured === true ? "ja" : "nein",
          provider_id: item.provider_id
        }))}
        footer="Konfiguriert bedeutet: technische Preisquelle ist bekannt. Der konkrete historische Preis wird erst ueber Backfill oder manuellen Beleg importiert."
      />
      <TablePanel
        title="Historische Preisplanung vor Import"
        rows={historicalPriceRequirements.map((item) => ({
          asset: item.asset,
          price_date: item.price_date,
          row_class: item.row_class,
          status: item.status,
          provider_id: item.provider_id,
          event_count: item.event_count,
          gross_quantity: item.gross_quantity
        }))}
        footer="Diese Liste entsteht aus der Blockpit-Datei selbst. Sie zeigt, welche Tagespreise vor einem Live-Import belegbar sein muessen."
      />
      <TablePanel
        title="Blockpit/Solana Klassen"
        rows={classRows}
        footer={`Einzelklassen-Diagnose, nicht der finale Startbestand. Quelle: ${report?.file_path ?? "-"} | Integration: ${report?.integration ?? "Solana"} | Jahr bis: ${String(report?.max_year ?? "-")} | Unbekannte Assets uebersprungen: ${report?.skipped_unknown_assets ?? 0}`}
      />
    </Stack>
  );
}

function SolscanTokenPreflightPanel({
  report
}: {
  report: Snapshot["solscanTokenPreflight"];
}) {
  const solscan = report?.solscan ?? {};
  const blockpit = report?.blockpit ?? {};
  const fileCoverage = report?.file_coverage ?? {};
  const missing = report?.missing_blockpit_signatures ?? [];
  const missingSummary = report?.missing_summary ?? [];
  const checkpoints = report?.coverage_checkpoints ?? [];
  const rpcEvidence = report?.rpc_evidence ?? {};
  const rpcStatus = String(rpcEvidence.status ?? "missing");
  return (
    <Stack>
      <div className="panel">
        <div className="panelToolbar">
          <strong>Solscan/IOT Preflight</strong>
          <span className={`statusPill ${Number(report?.blockpit_missing_signatures ?? 0) === 0 || rpcStatus === "verified" ? "ok" : "blocked"}`}>
            {Number(report?.blockpit_missing_signatures ?? 0) === 0 ? "vollstaendig" : rpcStatus === "verified" ? "RPC belegt" : "Teilabdeckung"}
          </span>
        </div>
        <div className="reviewSummary">
          <Metric title="Asset" value={report?.asset ?? "IOT"} />
          <Metric title="Solscan Signaturen" value={String(report?.solscan?.signatures ?? 0)} />
          <Metric title="Blockpit Signaturen" value={String(report?.blockpit?.signatures ?? 0)} />
          <Metric title="Gematcht" value={String(report?.matched_signatures ?? 0)} />
          <Metric title="Blockpit fehlt in Solscan" value={String(report?.blockpit_missing_signatures ?? 0)} />
          <Metric title="Solscan extra" value={String(report?.solscan_extra_signatures ?? 0)} />
          <Metric title="Mengen-Delta Match" value={formatValue(report?.matched_quantity_delta ?? "0", "quantity")} />
          <Metric title="RPC Belegstatus" value={rpcStatus} />
          <Metric title="RPC verifiziert" value={`${String(rpcEvidence.verified ?? 0)} / ${String(rpcEvidence.signatures_total ?? 0)}`} />
          <Metric title="RPC Delta" value={formatValue(String(rpcEvidence.quantity_delta_sum ?? "0"), "quantity")} />
          <Metric title="Live geaendert" value={report?.target_changed ? "ja" : "nein"} />
        </div>
      </div>
      <TablePanel
        title="Solscan-Dateiabdeckung"
        rows={[fileCoverage]}
        footer="Die aktuelle Datei erklaert, warum Januar- und November/Dezember-Signaturen fehlen koennen."
      />
      <TablePanel
        title="Solscan vs. Blockpit Mengen"
        rows={[
          { source: "Solscan", ...solscan },
          { source: "Blockpit", ...blockpit }
        ]}
        footer={`Wallet: ${report?.wallet ?? "-"} | Token: ${report?.token_address ?? "-"} | Jahr bis: ${String(report?.max_year ?? "-")}`}
      />
      <TablePanel
        title="Coverage an IOT-Defizitpunkten"
        rows={checkpoints}
        footer="Delta = Solscan-Netto minus Blockpit-Netto bis zum jeweiligen Defizitzeitpunkt."
      />
      <TablePanel
        title="RPC-Beleg fuer fehlende Blockpit-IOT-Signaturen"
        rows={[rpcEvidence]}
        footer="Dieser Nachweis prueft die in der Solscan-CSV fehlenden Blockpit-Signaturen gegen Solana RPC, ohne daraus doppelte Importereignisse zu erzeugen."
      />
      <TablePanel
        title="Fehlende Blockpit-IOT-Signaturen gruppiert"
        rows={missingSummary}
        footer="Diese Gruppierung trennt kritische fruehe Abdeckung von spaeteren November-/Dezember-Luecken."
      />
      <TablePanel
        title="Blockpit-IOT-Signaturen ohne Solscan-Datei-Treffer"
        rows={missing}
        footer="Diese Signaturen sind in Blockpit enthalten, aber in der aktuell vorliegenden Solscan-CSV nicht enthalten. Das ist eine Parser-/Datenabdeckungsfrage, kein Liveimport."
      />
    </Stack>
  );
}

function WalletMonthlyPreflightPanel({
  report
}: {
  report: Snapshot["walletMonthlyPreflight"];
}) {
  const monthlyTotals = report?.monthly_totals ?? [];
  return (
    <Stack>
      <div className="panel">
        <div className="panelToolbar">
          <strong>Wallet-Monats-Preflight</strong>
          <span className={`statusPill ${report?.covers_required_quantity ? "ok" : "blocked"}`}>
            {report?.covers_required_quantity ? "Startbestand gedeckt" : "Startbestand offen"}
          </span>
        </div>
        <div className="reviewSummary">
          <Metric title="Asset" value={report?.asset ?? "IOT"} />
          <Metric title="Bis Stichtag" value={formatValue(report?.quantity_until_cutoff ?? "0", "quantity")} />
          <Metric title="Erforderlich" value={formatValue(report?.required_quantity ?? "0", "quantity")} />
          <Metric title="Deckungsfaktor" value={formatValue(report?.coverage_ratio ?? "0", "number")} />
          <Metric title="Gateways" value={String(report?.gateways ?? 0)} />
          <Metric title="Zeitraum" value={`${report?.first_period ?? "-"} bis ${report?.last_period ?? "-"}`} />
        </div>
      </div>
      <TablePanel
        title="Wallet-Monatssummen"
        rows={monthlyTotals}
        footer={`Quelle: ${report?.file_path ?? "-"} | Wallet: ${report?.wallet ?? "-"} | Stichtag: ${report?.cutoff_at ?? "-"}`}
      />
    </Stack>
  );
}

function PriceCoveragePanel({
  coverage,
  requirements,
  onAddPriceGapDecision
}: {
  coverage: Snapshot["priceCoverage"];
  requirements: Snapshot["priceRequirements"];
  onAddPriceGapDecision: (scope: string, decisionStatus: string) => void;
}) {
  const rows = coverage?.missing ?? [];
  const requirementRows = requirements?.requirements ?? [];
  return (
    <Stack>
      <div className="grid">
        <Metric title="Preis-Luecken" value={String(coverage?.missing_count ?? 0)} />
        <Metric title="Assets" value={(coverage?.missing_assets ?? []).join(", ") || "keine"} />
        <Metric title="Preisbedarf" value={String(requirements?.requirements_count ?? 0)} />
      </div>
      <TablePanel
        title="Datumsgenauer Preisbedarf"
        rows={requirementRows.map((row) => ({
          asset: row.asset,
          price_date: row.price_date,
          source: row.source,
          event_type: row.event_type,
          role: row.role,
          event_count: row.event_count,
          gross_quantity: row.gross_quantity,
          first_event_at: row.first_event_at,
          last_event_at: row.last_event_at,
          sample_event_ids: Array.isArray(row.sample_event_ids) ? row.sample_event_ids.join(", ") : ""
        }))}
        footer="Diese Liste ist die konkrete Arbeitsliste fuer historische Preisbelege; sie importiert keine Preise."
      />
      <TablePanel
        title="Fehlende historische Bewertungen"
        rows={rows.map((row) => ({
          scope: row.scope,
          decision_status: row.decision_status,
          decision_title: row.decision_title,
          asset: row.asset,
          year: row.year,
          source: row.source,
          event_type: row.event_type,
          role: row.role,
          event_count: row.event_count,
          gross_quantity: row.gross_quantity,
          first_event_at: row.first_event_at,
          last_event_at: row.last_event_at
        }))}
        footer="Fehlende Bewertungen blockieren den Export, damit keine verdeckten 0-EUR-Werte entstehen."
        rowActions={[
          {
            label: "Preisquelle erforderlich",
            icon: <Database size={16} />,
            onClick: (row) => onAddPriceGapDecision(String(row.scope ?? ""), "price_source_needed")
          },
          {
            label: "Manueller Preis erforderlich",
            icon: <ReceiptText size={16} />,
            onClick: (row) => onAddPriceGapDecision(String(row.scope ?? ""), "manual_price_required")
          },
          {
            label: "Parserdaten erforderlich",
            icon: <Upload size={16} />,
            onClick: (row) => onAddPriceGapDecision(String(row.scope ?? ""), "parser_data_needed")
          }
        ]}
      />
    </Stack>
  );
}

function PriceQualityPanel({
  quality,
  manualReview,
  stablecoinFxReview,
  solscanSignatureReview,
  binanceNormalizerReview,
  eventQuoteEvidenceReview,
  onDownload,
  onAddDecision,
  compact = false
}: {
  quality: Snapshot["priceQuality"];
  manualReview?: Snapshot["priceManualReview"];
  stablecoinFxReview?: Snapshot["priceStablecoinFxReview"];
  solscanSignatureReview?: Snapshot["priceSolscanSignatureReview"];
  binanceNormalizerReview?: Snapshot["priceBinanceNormalizerReview"];
  eventQuoteEvidenceReview?: Snapshot["priceEventQuoteEvidenceReview"];
  onDownload?: (path: string) => void;
  onAddDecision?: (row: Record<string, unknown>, decisionStatus: string) => void;
  compact?: boolean;
}) {
  const groups = quality?.groups ?? [];
  const sources = quality?.source_summaries ?? [];
  const latest = quality?.latest_assets ?? [];
  const rowActions = [
    ...(onDownload ? [{
      label: "Drilldown JSON",
      icon: <FileJson size={16} />,
      onClick: (row: Record<string, unknown>) => onDownload(
        `/api/v1/prices/quality/group?asset=${encodeURIComponent(String(row.asset ?? ""))}`
        + `&year=${encodeURIComponent(String(row.year ?? ""))}`
        + `&source=${encodeURIComponent(String(row.source ?? ""))}`
      )
    }] : []),
    ...(onAddDecision ? [
      {
        label: "Event-Quote akzeptieren",
        icon: <Check size={16} />,
        onClick: (row: Record<string, unknown>) => onAddDecision(row, "accepted_event_quote")
      },
      {
        label: "Externer Preis erforderlich",
        icon: <Database size={16} />,
        onClick: (row: Record<string, unknown>) => onAddDecision(row, "external_price_required")
      },
      {
        label: "Manuelle Pruefung erforderlich",
        icon: <AlertTriangle size={16} />,
        onClick: (row: Record<string, unknown>) => onAddDecision(row, "manual_review_required")
      }
    ] : [])
  ];
  return (
    <Stack>
      <div className="panel">
        <div className="panelToolbar">
          <strong>Preisqualitaet</strong>
          <span>{quality?.generated_at ? formatDateTime(quality.generated_at) : "-"}</span>
        </div>
        <div className="reviewSummary">
          <Metric title="Preiszeilen" value={String(quality?.price_points_count ?? 0)} />
          <Metric title="Low Confidence" value={String(quality?.low_confidence_count ?? 0)} />
          <Metric title="Proxy/Derived" value={String(quality?.proxy_count ?? 0)} />
          <Metric title="Steuerrelevant" value={String(quality?.tax_relevant_issue_groups ?? 0)} />
          <Metric title="High Risk" value={String(quality?.high_risk_groups ?? 0)} />
          <Metric title="Medium Risk" value={String(quality?.medium_risk_groups ?? 0)} />
        </div>
        <div className="footer">{quality?.methodology ?? "Preisqualitaet wird geladen."}</div>
      </div>
      {manualReview ? (
        <TablePanel
          title="Manuelle Preispruefung"
          rows={(manualReview.groups ?? []).map((row) => ({
            rank: row.priority_rank,
            asset: row.asset,
            year: row.year,
            source: row.source,
            bucket: row.review_bucket,
            tax_lines_count: row.tax_lines_count,
            price_count: row.price_count,
            reason: row.reason,
            next_action: row.next_action,
            evidence_ref: row.evidence_ref,
            event_sources: row.event_sources,
            quote_assets: row.quote_assets
          }))}
          footer={`Manuell: ${manualReview.manual_groups_count} | steuerrelevant: ${manualReview.tax_relevant_groups_count} | Tax-Lines: ${manualReview.total_tax_lines_count}`}
          rowActions={onDownload ? [
            {
              label: "Drilldown JSON",
              icon: <FileJson size={16} />,
              onClick: (row) => onDownload(String(row.evidence_ref ?? ""))
            }
          ] : undefined}
        />
      ) : null}
      {stablecoinFxReview ? (
        <TablePanel
          title="Stablecoin-FX-Pruefung"
          rows={(stablecoinFxReview.groups ?? []).map((row) => ({
            asset: row.asset,
            year: row.year,
            source: row.source,
            tax_lines_count: row.tax_lines_count,
            tax_quantity: row.tax_quantity,
            price_count: row.price_count,
            expected_price_basis: row.expected_price_basis,
            recommended_action: row.recommended_action,
            reason: row.reason,
            event_sources: row.event_sources,
            quote_assets: row.quote_assets,
            evidence_ref: row.evidence_ref
          }))}
          footer={`Stablecoin/Fiat: ${stablecoinFxReview.groups_count} | steuerrelevant: ${stablecoinFxReview.tax_relevant_groups_count} | Tax-Lines: ${stablecoinFxReview.total_tax_lines_count}`}
          rowActions={onDownload ? [
            {
              label: "Drilldown JSON",
              icon: <FileJson size={16} />,
              onClick: (row) => onDownload(String(row.evidence_ref ?? ""))
            }
          ] : undefined}
        />
      ) : null}
      {solscanSignatureReview ? (
        <TablePanel
          title="Solscan-Signatur-Pruefung"
          rows={(solscanSignatureReview.groups ?? []).map((row) => ({
            asset: row.asset,
            year: row.year,
            source: row.source,
            tax_lines_count: row.tax_lines_count,
            tax_quantity: row.tax_quantity,
            price_count: row.price_count,
            signature_count: row.signature_count,
            non_signature_ref_count: row.non_signature_ref_count,
            recommended_action: row.recommended_action,
            reason: row.reason,
            event_sources: row.event_sources,
            quote_assets: row.quote_assets,
            signature_refs: row.signature_refs,
            non_signature_refs: row.non_signature_refs,
            evidence_ref: row.evidence_ref
          }))}
          footer={`Solscan: ${solscanSignatureReview.groups_count} | steuerrelevant: ${solscanSignatureReview.tax_relevant_groups_count} | Tax-Lines: ${solscanSignatureReview.total_tax_lines_count} | Signatur-Refs: ${solscanSignatureReview.total_signature_refs}`}
          rowActions={onDownload ? [
            {
              label: "Drilldown JSON",
              icon: <FileJson size={16} />,
              onClick: (row) => onDownload(String(row.evidence_ref ?? ""))
            }
          ] : undefined}
        />
      ) : null}
      {binanceNormalizerReview ? (
        <TablePanel
          title="Binance-Normalizer-Pruefung"
          rows={(binanceNormalizerReview.groups ?? []).map((row) => ({
            asset: row.asset,
            year: row.year,
            source: row.source,
            tax_lines_count: row.tax_lines_count,
            tax_quantity: row.tax_quantity,
            price_count: row.price_count,
            has_missing_quote_fields: row.has_missing_quote_fields,
            has_unknown_events: row.has_unknown_events,
            has_zero_quantity_samples: row.has_zero_quantity_samples,
            missing_sample_refs: row.missing_sample_refs,
            sample_ref_count: row.sample_ref_count,
            recommended_action: row.recommended_action,
            reason: row.reason,
            event_sources: row.event_sources,
            quote_assets: row.quote_assets,
            sample_event_refs: row.sample_event_refs,
            evidence_ref: row.evidence_ref
          }))}
          footer={`Binance: ${binanceNormalizerReview.groups_count} | steuerrelevant: ${binanceNormalizerReview.tax_relevant_groups_count} | Tax-Lines: ${binanceNormalizerReview.total_tax_lines_count} | fehlende Quotes: ${binanceNormalizerReview.missing_quote_groups_count} | unknown/zero: ${binanceNormalizerReview.unknown_or_zero_groups_count}`}
          rowActions={onDownload ? [
            {
              label: "Drilldown JSON",
              icon: <FileJson size={16} />,
              onClick: (row) => onDownload(String(row.evidence_ref ?? ""))
            }
          ] : undefined}
        />
      ) : null}
      {eventQuoteEvidenceReview ? (
        <TablePanel
          title="Event-Quote-Evidenzpruefung"
          rows={(eventQuoteEvidenceReview.groups ?? []).map((row) => ({
            asset: row.asset,
            year: row.year,
            source: row.source,
            tax_lines_count: row.tax_lines_count,
            tax_quantity: row.tax_quantity,
            price_count: row.price_count,
            evidence_class: row.evidence_class,
            stable_quote_evidence: row.stable_quote_evidence,
            missing_sample_refs: row.missing_sample_refs,
            sample_ref_count: row.sample_ref_count,
            recommended_action: row.recommended_action,
            reason: row.reason,
            event_sources: row.event_sources,
            quote_assets: row.quote_assets,
            sample_event_refs: row.sample_event_refs,
            evidence_ref: row.evidence_ref
          }))}
          footer={`Event-Quote: ${eventQuoteEvidenceReview.groups_count} | steuerrelevant: ${eventQuoteEvidenceReview.tax_relevant_groups_count} | Tax-Lines: ${eventQuoteEvidenceReview.total_tax_lines_count} | stabile Quotes: ${eventQuoteEvidenceReview.stable_quote_groups_count} | fehlende Refs: ${eventQuoteEvidenceReview.missing_sample_ref_groups_count}`}
          rowActions={onDownload ? [
            {
              label: "Drilldown JSON",
              icon: <FileJson size={16} />,
              onClick: (row) => onDownload(String(row.evidence_ref ?? ""))
            }
          ] : undefined}
        />
      ) : null}
      <TablePanel
        title="Preisqualitaet nach Asset/Jahr/Quelle"
        rows={groups.map((row) => ({
          risk_level: row.risk_level,
          status: row.status,
          asset: row.asset,
          year: row.year,
          source: row.source,
          price_count: row.price_count,
          low_confidence_count: row.low_confidence_count,
          proxy_count: row.proxy_count,
          tax_lines_count: row.tax_lines_count,
          min_confidence: row.min_confidence,
          first_priced_at: row.first_priced_at,
          last_priced_at: row.last_priced_at
        }))}
        compact={compact}
        footer="High-Risk-Gruppen zuerst. Diese Tabelle ist Diagnose, kein Preisimport."
        rowActions={rowActions.length ? rowActions : undefined}
      />
      {compact ? null : (
        <>
          <TablePanel
            title="Preisqualitaet nach Quelle"
            rows={sources}
            footer="Quellenaggregation fuer Low-Confidence- und Proxy/Derived-Preisquellen."
          />
          <TablePanel
            title="Letzte wirksame Preise"
            rows={latest}
            footer="Letzter Preis je Asset; auffaellige aktuelle Preise stehen oben."
          />
        </>
      )}
    </Stack>
  );
}

function TransferCandidatesPanel({ report }: { report: Snapshot["transferCandidates"] }) {
  const candidates = report?.candidates ?? [];
  return (
    <Stack>
      <div className="grid">
        <Metric title="Kandidaten" value={String(report?.candidates_count ?? 0)} />
        <Metric title="Assets" value={(report?.assets ?? []).join(", ") || "keine"} />
        <Metric
          title="Stark"
          value={String(candidates.filter((candidate) => candidate.status === "strong_candidate").length)}
        />
        <Metric
          title="Review"
          value={String(candidates.filter((candidate) => candidate.status === "review_candidate").length)}
        />
      </div>
      <TablePanel
        title="Transfer-Kandidaten"
        rows={candidates.map((candidate) => ({
          status: candidate.status,
          score: candidate.score,
          asset: candidate.asset,
          amount_out: candidate.amount_out,
          amount_in: candidate.amount_in,
          out_time: candidate.out_time,
          in_time: candidate.in_time,
          out_account: candidate.out_account,
          in_account: candidate.in_account,
          out_source: candidate.out_source,
          in_source: candidate.in_source,
          reasons: Array.isArray(candidate.reasons) ? candidate.reasons.join(" | ") : "",
          warnings: Array.isArray(candidate.warnings) ? candidate.warnings.join(" | ") : ""
        }))}
        footer="Kandidaten sind nur Pruefhinweise. Eine steuerwirksame Transferentscheidung braucht eine Review Decision oder belegbare Quelle."
      />
    </Stack>
  );
}

function DivorceEqualizationPanel({
  report,
  onDownload
}: {
  report: Snapshot["divorceEqualization"];
  onDownload: (path: string) => void;
}) {
  const marital = report?.marital_pre_cutoff ?? {};
  const direct = report?.post_cutoff_direct_eur_invest ?? {};
  const allLots = report?.post_cutoff_all_lots ?? {};
  const accounts = report?.accounts ?? [];
  const valuationTokenRows = equalizationValuationTokenRows(accounts);
  return (
    <Stack>
      <section className="divorceHero">
        <div>
          <span className="heroKicker">Zugewinnausgleich</span>
          <h2>Stichtag 13.06.2025</h2>
          <p>{report?.legal_note ?? "Auswertung wird geladen."}</p>
        </div>
        <div className="reportHeroStats">
          <Metric title="Startwert Stichtag" value={`${formatCurrency(report?.cutoff_portfolio_value_eur)} EUR`} />
          <Metric title="Endwert Bewertung" value={`${formatCurrency(report?.valuation_portfolio_value_eur)} EUR`} />
          <Metric title="Bruttoveraenderung" value={`${formatCurrency(report?.gross_portfolio_change_eur)} EUR`} />
          <Metric title="Brutto ohne Review" value={`${formatCurrency(report?.gross_portfolio_change_without_review_assets_eur)} EUR`} />
          <Metric title="Bereinigt um Invest" value={`${formatCurrency(report?.adjusted_gain_loss_excluding_new_invest_eur)} EUR`} />
          <Metric title="Bereinigt ohne Review" value={`${formatCurrency(report?.adjusted_gain_loss_without_review_assets_eur)} EUR`} />
          <Metric title="Bewertung" value={formatDateTime(report?.valuation_at)} />
          <Metric title="Events bis" value={formatDateTime(report?.latest_event_at)} />
          <Metric title="Fiat ab Stichtag" value={`${formatCurrency(report?.fiat_deposits_since_cutoff_eur)} EUR`} />
          <Metric title="EUR-Kaeufe" value={`${formatCurrency(report?.direct_eur_buys_since_cutoff_eur)} EUR`} />
        </div>
      </section>

      <div className="equalizationGrid">
        <div className="equalizationCard focus">
          <div className="panelToolbar">
            <strong>Kernrechnung Zugewinn</strong>
            <span>Portfolio-Stichtagswerte</span>
          </div>
          <Metric title="Portfolio 13.06.2025" value={`${formatCurrency(report?.cutoff_portfolio_value_eur)} EUR`} />
          <Metric title="Portfolio 15.06.2026" value={`${formatCurrency(report?.valuation_portfolio_value_eur)} EUR`} />
          <Metric title="ohne Review-Token" value={`${formatCurrency(report?.valuation_value_without_review_assets_eur)} EUR`} />
          <Metric title="Review-Token" value={`${formatCurrency(report?.valuation_review_value_eur)} EUR`} />
          <Metric title="Staub" value={`${formatCurrency(report?.valuation_dust_value_eur)} EUR`} />
          <Metric title="Neue externe Einzahlungen" value={`${formatCurrency(report?.net_external_invest_since_cutoff_eur)} EUR`} />
          <Metric title="Wertveraenderung ohne Neuinvest" value={`${formatCurrency(report?.adjusted_gain_loss_excluding_new_invest_eur)} EUR`} />
          <Metric title="ohne Review & Neuinvest" value={`${formatCurrency(report?.adjusted_gain_loss_without_review_assets_eur)} EUR`} />
          <p className="reportYearSummary">
            Diese Karte nutzt echte Portfolio-Stichtagswerte. Review-Token bleiben erhalten, werden aber getrennt markiert.
          </p>
        </div>
      </div>

      <div className="equalizationGrid">
        <EqualizationSummaryCard title="Technische FIFO-Kontrollsicht Alt-Lots" bucket={marital} tone="neutral" />
        <EqualizationSummaryCard title="Erbgeld-/EUR-Spur ab Stichtag" bucket={direct} tone="focus" />
        <EqualizationSummaryCard title="Alle Lots ab Stichtag" bucket={allLots} tone="wide" />
      </div>

      <div className="panel">
        <div className="panelToolbar">
          <strong>BMF-Abgrenzung zur Steuererklaerung</strong>
          <div className="reportActionBand compactActions">
            <button type="button" onClick={() => onDownload("/api/v1/divorce/equalization-summary/evidence-package.zip")}>
              Belegpaket ZIP
            </button>
            <button type="button" onClick={() => onDownload(String(report?.bmf_tax_boundary?.tax_methodology_summary_endpoint ?? "/api/v1/tax-methodology/summary"))}>
              BMF-Methodik
            </button>
          </div>
        </div>
        <div className="reportWarningGrid">
          {(report?.bmf_tax_boundary?.boundary_notes ?? []).map((item, index) => (
            <div key={`${item}-${index}`} className="reportWarning">
              <ReceiptText size={18} />
              <div>
                <strong>{item}</strong>
              </div>
            </div>
          ))}
        </div>
        <TablePanel
          title="BMF-Referenzen und Steuer-Endpunkte"
          rows={[
            {
              referenz: report?.bmf_tax_boundary?.bmf_reference,
              url: report?.bmf_tax_boundary?.bmf_reference_url
            },
            {
              zweck: "BMF-Methodik alle Jahre",
              endpoint: report?.bmf_tax_boundary?.tax_methodology_summary_endpoint
            },
            {
              zweck: "BMF-Methodik je Steuerjahr",
              endpoint: report?.bmf_tax_boundary?.tax_year_methodology_endpoint_template
            },
            {
              zweck: "Belegpaket je Steuerjahr",
              endpoint: report?.bmf_tax_boundary?.tax_year_evidence_package_endpoint_template
            }
          ]}
          compact
          footer="Die Zugewinnseite ist Beleg- und Portfolioauswertung. Steuerliche Einreichungsfaehigkeit wird ueber die Steuerjahr-/BMF-Endpunkte bewertet."
        />
      </div>

      <div className="panel">
        <div className="panelToolbar">
          <strong>Wallets / Konten getrennt</strong>
          <button type="button" onClick={() => onDownload("/api/v1/divorce/equalization-summary/accounts.csv")}>
            CSV herunterladen
          </button>
        </div>
        <TablePanel
          title="Stichtagswerte je Wallet / Konto"
          rows={accounts.map((account) => ({
            konto: shortAccount(String(account.account ?? "")),
            konto_voll: String(account.account ?? ""),
            klasse: equalizationAccountLabel(String(account.classification ?? "")),
            wertbasis: equalizationValuationBasisLabel(String(account.valuation_basis ?? "")),
            wert_13_06_2025: `${formatCurrency(account.cutoff_value_eur)} EUR`,
            wert_15_06_2026: `${formatCurrency(account.valuation_value_eur)} EUR`,
            wert_ohne_review_token: `${formatCurrency(account.valuation_value_without_review_assets_eur)} EUR`,
            review_token_wert: `${formatCurrency(account.valuation_review_value_eur)} EUR`,
            veraenderung: `${formatCurrency(account.gross_change_eur)} EUR`,
            assets_13_06: Array.isArray(account.asset_labels_cutoff) ? account.asset_labels_cutoff.join(", ") : "",
            assets_15_06: Array.isArray(account.asset_labels_valuation) ? account.asset_labels_valuation.join(", ") : "",
            token_details_15_06: equalizationAccountAssetSummary(account.valuation_assets),
            hinweis: String(account.note ?? "")
          }))}
          footer="Wallet-Adressen werden links gekuerzt angezeigt; konto_voll enthaelt die vollstaendige Adresse fuer Belege und Drilldown."
        />
      </div>

      <div className="panel">
        <div className="panelToolbar">
          <strong>Token je Wallet zum Bewertungsstand</strong>
          <button type="button" onClick={() => onDownload("/api/v1/divorce/equalization-summary/valuation-tokens.csv")}>
            CSV herunterladen
          </button>
        </div>
        <TablePanel
          title="Aktuelle Token-Bewertung je Konto"
          rows={valuationTokenRows}
          footer="Review-Token und Staub werden nur markiert. Die steuerlichen Rohdaten und FIFO-Spuren bleiben unveraendert."
          compact
        />
      </div>

      <div className="panel">
        <div className="panelToolbar">
          <strong>Live-/Solscan-Abgleich</strong>
          <button type="button" onClick={() => onDownload("/api/v1/divorce/equalization-summary/live-reconciliation.csv")}>
            CSV herunterladen
          </button>
        </div>
        <TablePanel
          title="Reconciliation fuer relevante Wallets und Quellen"
          rows={(report?.live_reconciliation ?? []).map((row) => ({
            quelle: row.source_group,
            typ: row.source_type,
            asset: row.asset ?? "-",
            v2_menge: row.ledger_quantity === null || row.ledger_quantity === undefined ? "-" : formatAmount(row.ledger_quantity),
            v2_wert: `${formatCurrency(row.ledger_value_eur)} EUR`,
            live_menge: row.external_quantity === null || row.external_quantity === undefined ? "-" : formatAmount(row.external_quantity),
            live_wert: row.external_value_eur === null || row.external_value_eur === undefined ? "-" : `${formatCurrency(row.external_value_eur)} EUR`,
            delta_wert: row.delta_value_eur === null || row.delta_value_eur === undefined ? "-" : `${formatCurrency(row.delta_value_eur)} EUR`,
            status: row.status,
            schwere: row.severity,
            naechster_schritt: row.next_action
          }))}
          footer="Live- und Solscan-Werte sind Kontrollquellen. Steuerliche Historie bleibt ueber importierte Transaktionen, FIFO und Belege nachzuweisen."
          compact
        />
      </div>

      <div className="panel">
        <div className="panelToolbar">
          <strong>Geldfluss-Abgleich</strong>
          <span>read-only</span>
        </div>
        <div className="evidencePackageSummary">
          <Metric title="Neue Binance-EUR-Zufluesse" value={`${formatCurrency(report?.fiat_deposits_since_cutoff_eur)} EUR`} />
          <Metric title="Direkte EUR-Kaeufe" value={`${formatCurrency(report?.direct_eur_buys_since_cutoff_eur)} EUR`} />
          <Metric title="EUR ohne Zielquote" value={`${formatCurrency(report?.eur_asset_spent_without_quote_since_cutoff_eur)} EUR`} />
          <Metric title="Erstellt" value={formatDateTime(report?.generated_at)} />
        </div>
        <div className="reportWarningGrid">
          {(report?.cash_flows ?? []).map((flow, index) => (
            <div key={`${String(flow.label)}-${index}`} className="reportWarning">
              <ReceiptText size={18} />
              <div>
                <strong>{String(flow.label ?? "")}: {formatCurrency(flow.amount_eur)} EUR</strong>
                <span>{String(flow.note ?? "")}</span>
              </div>
            </div>
          ))}
        </div>
      </div>

      <EqualizationBucketPanel bucket={marital} />
      <EqualizationBucketPanel bucket={direct} />
      <EqualizationBucketPanel bucket={allLots} />

      <div className="panel">
        <div className="panelToolbar">
          <strong>Hinweise fuer Belegfuehrung</strong>
          <span>keine Rechtsberatung</span>
        </div>
        <div className="reportWarningGrid">
          {(report?.caveats ?? []).map((item, index) => (
            <div key={`${item}-${index}`} className="reportWarning">
              <AlertTriangle size={18} />
              <div>
                <strong>{item}</strong>
              </div>
            </div>
          ))}
        </div>
        <div className="footer">{report?.methodology ?? ""}</div>
      </div>
    </Stack>
  );
}

function EqualizationSummaryCard({
  title,
  bucket,
  tone
}: {
  title: string;
  bucket: Record<string, unknown>;
  tone: "neutral" | "focus" | "wide";
}) {
  return (
    <div className={`equalizationCard ${tone}`}>
      <div className="panelToolbar">
        <strong>{title}</strong>
        <span>{String(bucket.open_lots_count ?? 0)} Lots</span>
      </div>
      <Metric title="Anschaffung" value={`${formatCurrency(bucket.total_cost_basis_eur)} EUR`} />
      <Metric title="Wert/Erlöse" value={`${formatCurrency(bucket.total_value_or_proceeds_eur)} EUR`} />
      <Metric title="G/V gesamt" value={`${formatCurrency(bucket.total_gain_loss_eur)} EUR`} />
      <Metric title="davon realisiert" value={`${formatCurrency(bucket.realized_gain_loss_eur)} EUR`} />
      <Metric title="davon offen" value={`${formatCurrency(bucket.unrealized_gain_loss_eur)} EUR`} />
      <p className="reportYearSummary">{String(bucket.description ?? "")}</p>
    </div>
  );
}

function EqualizationBucketPanel({ bucket }: { bucket: Record<string, unknown> }) {
  const assets = Array.isArray(bucket.assets) ? bucket.assets : [];
  return (
    <div className="panel">
      <div className="panelToolbar">
        <strong>{String(bucket.label ?? "Zugewinn-Gruppe")}</strong>
        <span>{assets.length} Assets</span>
      </div>
      <div className="evidencePackageSummary">
        <Metric title="Anschaffung offen" value={`${formatCurrency(bucket.open_cost_basis_eur)} EUR`} />
        <Metric title="Wert offen" value={`${formatCurrency(bucket.open_value_eur)} EUR`} />
        <Metric title="G/V offen" value={`${formatCurrency(bucket.unrealized_gain_loss_eur)} EUR`} />
        <Metric title="Erlöse verkauft" value={`${formatCurrency(bucket.sold_proceeds_eur)} EUR`} />
        <Metric title="G/V verkauft" value={`${formatCurrency(bucket.realized_gain_loss_eur)} EUR`} />
      </div>
      <TablePanel
        title="Asset-Aufschluesselung"
        rows={assets.map((asset) => ({
          asset: asset.asset,
          menge_offen: formatAmount(asset.quantity_open),
          anschaffung_offen: `${formatCurrency(asset.open_cost_basis_eur)} EUR`,
          wert_offen: `${formatCurrency(asset.open_value_eur)} EUR`,
          gv_offen: `${formatCurrency(asset.unrealized_gain_loss_eur)} EUR`,
          menge_verkauft: formatAmount(asset.sold_quantity),
          erloes_verkauft: `${formatCurrency(asset.sold_proceeds_eur)} EUR`,
          gv_gesamt: `${formatCurrency(asset.total_gain_loss_eur)} EUR`,
          preisstand: asset.latest_price_at ? formatDateTime(asset.latest_price_at) : "-"
        }))}
        compact
      />
      {Array.isArray(bucket.missing_price_assets) && bucket.missing_price_assets.length > 0 ? (
        <div className="notice reviewNotice">
          Fehlende Preise: {bucket.missing_price_assets.map(String).join(", ")}
        </div>
      ) : null}
    </div>
  );
}

function equalizationAccountLabel(classification: string): string {
  if (classification === "inheritance_jup_wallet") {
    return "JUP Erbgeld-Wallet";
  }
  if (classification === "solana_main_wallet") {
    return "Solana Main Wallet";
  }
  if (classification === "binance_jup_product") {
    return "Binance JUP-Produkt";
  }
  return "Portfolio-Konto";
}

function equalizationValuationBasisLabel(basis: string): string {
  if (basis === "current_live_anchored_snapshot") {
    return "Live-Anker Snapshot";
  }
  return basis || "Snapshot";
}

function equalizationAccountAssetSummary(value: unknown): string {
  if (!Array.isArray(value)) {
    return "";
  }
  return value
    .slice(0, 8)
    .map((asset) => {
      const label = String(asset.asset ?? "");
      const amount = `${formatCurrency(asset.value_eur)} EUR`;
      const flag = String(asset.valuation_flag ?? "valued");
      return flag === "valued" ? `${label} ${amount}` : `${label} ${amount} (${equalizationAssetFlagLabel(flag)})`;
    })
    .join(" | ");
}

function equalizationValuationTokenRows(accounts: Array<Record<string, unknown>>): Array<Record<string, unknown>> {
  return accounts.flatMap((account) => {
    const assets = Array.isArray(account.valuation_assets) ? account.valuation_assets : [];
    return assets.map((asset) => ({
      konto: shortAccount(String(account.account ?? "")),
      konto_voll: String(account.account ?? ""),
      klasse: equalizationAccountLabel(String(account.classification ?? "")),
      asset: String(asset.asset ?? ""),
      menge: formatAmount(asset.quantity),
      wert: `${formatCurrency(asset.value_eur)} EUR`,
      markierung: equalizationAssetFlagLabel(String(asset.valuation_flag ?? "valued")),
      preisquelle: String(asset.price_source ?? ""),
      preisstand: asset.priced_at ? formatDateTime(asset.priced_at) : "-",
      hinweis: String(asset.note ?? "")
    }));
  });
}

function equalizationAssetFlagLabel(flag: string): string {
  if (flag === "review_low_confidence_token") {
    return "Review";
  }
  if (flag === "dust_under_1_eur") {
    return "Staub";
  }
  if (flag === "valued") {
    return "bewertet";
  }
  return flag;
}

function ReportCenterPanel({
  center,
  evidenceManifest,
  evidencePackageIndex,
  readiness,
  priceQuality,
  reviewDecisions,
  exportViewMode,
  onExportViewModeChange,
  onCreatePdfExport,
  onRunReportAction,
  onDownload
}: {
  center: Snapshot["reportCenter"];
  evidenceManifest: Snapshot["reportEvidenceManifest"];
  evidencePackageIndex: Snapshot["reportEvidencePackageIndex"];
  readiness: Record<string, unknown> | undefined;
  priceQuality: Snapshot["priceQuality"];
  reviewDecisions: Snapshot["reviewDecisions"];
  exportViewMode: ExportViewMode;
  onExportViewModeChange: (mode: ExportViewMode) => void;
  onCreatePdfExport: (label: string, estimatedPages: string) => void;
  onRunReportAction: (path: string, label: string) => void;
  onDownload: (path: string) => void;
}) {
  const [label, setLabel] = useState("steuerreport-v2-final");
  const [estimatedPages, setEstimatedPages] = useState("80");
  const years = center?.years ?? [];
  const artifacts = center?.artifacts ?? [];
  const warnings = center?.quality_warnings ?? [];
  const csvExports = center?.csv_exports ?? [];
  const pdfAction = (center?.actions ?? []).find((action) => action.action_id === "create-pdf");
  const auditAction = (center?.actions ?? []).find((action) => action.action_id === "create-audit-json");
  const elsterAction = (center?.actions ?? []).find((action) => action.action_id === "create-elster-prep");
  const exportAllowed = center?.export_allowed ?? Boolean(readiness?.allow_export);
  const manifestFiles = evidenceManifest?.files ?? [];
  const requiredManifestFiles = manifestFiles.filter((file) => file.required);
  const optionalManifestFiles = manifestFiles.filter((file) => !file.required);
  const evidenceArtifact = artifacts.find((artifact) => artifact.artifact_id === "evidence-package");
  const evidenceHealth = center?.evidence_health ?? null;
  const indexGroups = evidencePackageIndex?.groups ?? [];
  const indexFiles = evidencePackageIndex?.files ?? [];
  const manifestGroups = manifestFiles.reduce<Array<{ key: string; label: string; files: EvidenceManifest["files"] }>>((groups, file) => {
    const key = file.group || "other";
    const existing = groups.find((group) => group.key === key);
    if (existing) {
      existing.files.push(file);
      return groups;
    }
    groups.push({
      key,
      label: file.group_label || "Sonstige Belege",
      files: [file]
    });
    return groups;
  }, []);

  return (
    <Stack>
      <section className={`reportHero ${exportAllowed ? "ok" : "blocked"}`}>
        <div>
          <span className="heroKicker">Report-Center</span>
          <h2>{exportAllowed ? "Export freigegeben" : "Export blockiert"}</h2>
          <p>{center?.methodology ?? "Reportstatus wird geladen."}</p>
        </div>
        <div className="reportHeroStats">
          <Metric title="PDF-Pakete" value={String(center?.packages_count ?? 0)} />
          <Metric title="Qualitaetswarnungen" value={String(warnings.length)} />
          <Metric title="Belegstatus" value={String(evidenceHealth?.status ?? "-")} />
          <Metric title="PDF-Seitenlimit" value={String(center?.max_pdf_pages_per_file ?? readiness?.max_pdf_pages_per_file ?? 100)} />
          <Metric title="Aktualisiert" value={formatDateTime(center?.generated_at)} />
        </div>
      </section>

      <div className="taxViewSwitch" role="tablist" aria-label="Belege und Export Ansicht">
        <button
          type="button"
          className={exportViewMode === "packages" ? "active" : ""}
          onClick={() => onExportViewModeChange("packages")}
        >
          Jahrespakete
        </button>
        <button
          type="button"
          className={exportViewMode === "evidence" ? "active" : ""}
          onClick={() => onExportViewModeChange("evidence")}
        >
          Belegstruktur
        </button>
        <button
          type="button"
          className={exportViewMode === "expert" ? "active" : ""}
          onClick={() => onExportViewModeChange("expert")}
        >
          Expertenmodus
        </button>
      </div>

      <div className="reportActionBand">
        <label>
          Label
          <input value={label} onChange={(event) => setLabel(event.target.value)} />
        </label>
        <label>
          Seiten
          <input value={estimatedPages} onChange={(event) => setEstimatedPages(event.target.value)} inputMode="numeric" />
        </label>
        <button
          type="button"
          disabled={pdfAction?.enabled === false}
          onClick={() => onCreatePdfExport(label, estimatedPages)}
          title={String(pdfAction?.blocked_reason ?? pdfAction?.description ?? "PDF-Paket erzeugen")}
        >
          <FileDown size={16} />
          PDF-Paket
        </button>
        <button type="button" onClick={() => onDownload("/api/v1/export/audit.json")}>
          <FileJson size={16} />
          Audit JSON
        </button>
        <button type="button" onClick={() => onRunReportAction(String(elsterAction?.path ?? "/api/v1/export/elster-prep"), "ELSTER-Prep")}>
          <PackageCheck size={16} />
          ELSTER-Prep
        </button>
        <button type="button" onClick={() => onRunReportAction(String(auditAction?.path ?? "/api/v1/export/audit"), "Audit-Snapshot")}>
          <Check size={16} />
          Audit-Snapshot
        </button>
        <button type="button" onClick={() => onDownload(String(evidenceArtifact?.endpoint ?? "/api/v1/export/evidence-package.zip"))}>
          <PackageCheck size={16} />
          Belegpaket
        </button>
      </div>

      {warnings.length ? (
        <div className="reportWarningGrid">
          {warnings.map((warning, index) => (
            <div key={`${warning.code}-${index}`} className={`reportWarning ${warning.blocks_export ? "blocked" : ""}`}>
              <AlertTriangle size={18} />
              <div>
                <strong>{String(warning.message ?? warning.code)}</strong>
                <span>{String(warning.severity ?? "medium")} | Anzahl {String(warning.count ?? 1)}</span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="reportWarning empty">Keine Report-Warnungen vorhanden.</div>
      )}

      {exportViewMode === "expert" ? <PriceQualityPanel quality={priceQuality} compact onDownload={onDownload} /> : null}

      {evidenceHealth ? (
        <div className={`notice inlineNotice ${evidenceHealth.status === "complete" ? "" : "reviewNotice"}`}>
          Belegstatus: {evidenceHealth.status} | kanonisch {evidenceHealth.canonical_count}/{evidenceHealth.traces_count} | {evidenceHealth.detail}
        </div>
      ) : null}

      <TokenRiskDocumentationPanel decisions={reviewDecisions ?? []} onDownload={onDownload} compact />

      {exportViewMode !== "packages" ? (
        <>
      <div className="panel evidencePackagePanel">
        <div className="panelToolbar">
          <strong>Belegpaket Inhalt</strong>
          <span className="statusPill ok">{manifestFiles.length} Dateien</span>
        </div>
        <div className="evidencePackageSummary">
          <Metric title="Pflichtbelege" value={String(requiredManifestFiles.length)} />
          <Metric title="Optionale Belege" value={String(optionalManifestFiles.length)} />
          <Metric title="Manifest" value={formatDateTime(evidenceManifest?.generated_at)} />
          <Metric title="Paket" value="on demand" />
        </div>
        <div className="evidenceGroupList">
          {manifestGroups.map((group) => (
            <div key={group.key} className="evidenceGroup">
              <div className="panelToolbar">
                <strong>{group.label}</strong>
                <span>{group.files.filter((file) => file.required).length}/{group.files.length} Pflicht</span>
              </div>
              <div className="evidenceFileList">
                {group.files.map((file) => (
                  <div key={file.file_id} className="evidenceFileItem">
                    <div>
                      <strong>{file.label}</strong>
                      <span>{file.file_id} | {file.kind} | {file.required ? "Pflicht" : "optional"}</span>
                    </div>
                    <button type="button" onClick={() => onDownload(file.endpoint)}>
                      <FileDown size={16} />
                      Datei
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="footer">
          {evidenceManifest?.methodology ?? "Manifest wird geladen. Das ZIP wird erst beim Download erzeugt."}
        </div>
      </div>

      <div className="panel evidencePackagePanel">
        <div className="panelToolbar">
          <strong>Paket-Integritaet</strong>
          <span className="statusPill ok">{indexFiles.length} ZIP-Pfade</span>
        </div>
        <div className="evidencePackageSummary">
          <Metric title="Kapitel" value={String(indexGroups.length)} />
          <Metric title="Index-Dateien" value={String(evidencePackageIndex?.files_count ?? indexFiles.length)} />
          <Metric title="Pflichtpfade" value={String(indexFiles.filter((file) => file.required).length)} />
          <Metric title="Hashes" value={String(indexFiles.filter((file) => file.sha256).length)} />
          <Metric title="Index" value={formatDateTime(evidencePackageIndex?.generated_at)} />
        </div>
        <div className="evidenceGroupList">
          {indexGroups.map((group) => (
            <div key={group.folder} className="evidenceGroup">
              <div className="panelToolbar">
                <strong>{group.folder}</strong>
                <span>{group.required_count}/{group.files_count} Pflicht</span>
              </div>
              <div className="evidenceFileList">
                {indexFiles.filter((file) => file.path.startsWith(`${group.folder}/`)).map((file) => (
                  <div key={file.path} className="evidenceFileItem">
                    <div>
                      <strong>{file.path}</strong>
                      <span>{file.file_id} | {file.required ? "Pflicht" : "optional"} | {file.size_bytes ? `${file.size_bytes} B` : "Hash erst im ZIP"} | {file.sha256 ? `sha256 ${file.sha256.slice(0, 12)}...` : file.source_endpoint}</span>
                    </div>
                    <button type="button" onClick={() => onDownload(file.source_endpoint)}>
                      <FileDown size={16} />
                      Quelle
                    </button>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="footer">
          {evidencePackageIndex?.methodology ?? "Paketindex wird geladen."}
        </div>
      </div>
        </>
      ) : null}

      <div className="panel">
        <div className="panelToolbar">
          <strong>HNT / Solana Beleg-Exports</strong>
          <span>Fairspot / Bridge / FIFO</span>
        </div>
        <div className="reportActionBand compactActions">
          <button type="button" onClick={() => onDownload("/api/v1/export/hnt-provenance-timeline.csv")}>
            <FileDown size={16} />
            HNT Timeline
          </button>
          <button type="button" onClick={() => onDownload("/api/v1/export/hnt-provenance-events.csv")}>
            <FileDown size={16} />
            HNT Events
          </button>
          <button type="button" onClick={() => onDownload("/api/v1/export/hnt-provenance-timeline.csv?account=13xfSeV2UcVgUiTKmd9V1Htunc6N7wsAgkGRHtquN9hpCbA78Yp")}>
            <FileDown size={16} />
            Fairspot Timeline
          </button>
          <button type="button" onClick={() => onDownload("/api/v1/export/hnt-provenance-events.csv?account=13xfSeV2UcVgUiTKmd9V1Htunc6N7wsAgkGRHtquN9hpCbA78Yp")}>
            <FileDown size={16} />
            Fairspot Events
          </button>
          <button type="button" onClick={() => onDownload("/api/v1/import/solscan/evidence-trace")}>
            <FileJson size={16} />
            Solscan Trace
          </button>
        </div>
        <div className="footer">
          Read-only Belege fuer Transfer-/Bridge- und Solana-FIFO-Kontexte. Diese Exports erzeugen keine FIFO- oder Ledger-Aenderung.
        </div>
      </div>

      <div className="reportYearGrid">
        {years.map((year) => (
          <div key={String(year.year)} className={`reportYearCard ${year.export_blocked ? "blocked" : ""}`}>
            <div className="panelToolbar">
              <strong>{String(year.year)}</strong>
              <div className="yearStatusPills">
                <span className={`statusPill ${reportYearFilingTone(String(year.filing_status ?? ""))}`}>
                  {String(year.filing_status_label ?? (year.export_blocked ? "pruefen" : "bereit"))}
                </span>
                <span className={`statusPill ${reportEvidenceTone(String(year.evidence_status ?? ""))}`}>
                  {String(year.evidence_status_label ?? "Nachweise")}
                </span>
              </div>
            </div>
            <Metric title="G/V" value={`${formatCurrency(year.realized_gain_loss_eur)} EUR`} />
            <Metric title="Rewards" value={`${formatCurrency(year.rewards_mining_staking_income_eur)} EUR`} />
            <Metric title="Steuerfrei" value={`${formatCurrency(year.tax_free_private_disposals_eur)} EUR`} />
            <Metric title="Tax-Lines" value={String(year.tax_lines_count ?? 0)} />
            <Metric title="Issues" value={String(year.review_issues_count ?? 0)} />
            <Metric title="CEX-FIFO" value={String(year.cex_fifo_anchor_status_label ?? "Keine CEX-FIFO-Anker")} />
            <Metric title="Pflichtbelege" value={String(year.required_evidence_count ?? (Array.isArray(year.required_evidence_refs) ? year.required_evidence_refs.length : 0))} />
            <Metric title="Paketdateien" value={String(year.expected_package_files_count ?? "-")} />
            <p className="reportYearSummary">{String(year.filing_summary ?? "")}</p>
            <p className="reportYearEvidenceSummary">{String(year.evidence_summary ?? "")}</p>
            <div className="reportYearProofGrid">
              <span className={reportYearFilingTone(String(year.filing_status ?? ""))}>
                Eingabehilfe: {String(year.filing_status_label ?? "-")}
              </span>
              <span className={reportEvidenceTone(String(year.evidence_status ?? ""))}>
                Nachweise: {String(year.evidence_status_label ?? "-")}
              </span>
              <span className={(Number(year.required_evidence_count ?? 0) > 0) ? "ok" : "warning"}>
                Pflichtbelege: {String(year.required_evidence_count ?? 0)}
              </span>
              <span className={(Number(year.expected_package_files_count ?? 0) > 0) ? "ok" : "warning"}>
                Paketumfang: {String(year.expected_package_files_count ?? 0)}
              </span>
              <span className={reportEvidenceTone(String(year.package_status ?? ""))}>
                Paket: {String(year.package_status_label ?? "abrufbar")}
              </span>
              <span className={Number(year.cex_fifo_anchor_decisions_count ?? 0) > 0 ? "ok" : "warning"}>
                CEX-FIFO: {String(year.cex_fifo_anchor_status_label ?? "Keine CEX-FIFO-Anker")}
              </span>
            </div>
            <div className="reportNextAction">
              <Check size={16} />
              <span>{String(year.next_action_label ?? year.primary_action ?? "")}</span>
            </div>
            <div className="reportStatusStrip">
              <span className={reportTone(year.pdf_status)}>PDF {String(year.pdf_status ?? "-")}</span>
              <span className={reportTone(year.audit_status)}>Audit {String(year.audit_status ?? "-")}</span>
              <span className={reportTone(year.elster_prep_status)}>ELSTER {String(year.elster_prep_status ?? "-")}</span>
              <span className={reportTone(year.csv_status)}>CSV {String(year.csv_status ?? "-")}</span>
            </div>
            <div className="reportYearActions">
              <button type="button" onClick={() => onDownload(String(year.filing_endpoint ?? `/api/v1/tax-years/${String(year.year)}/filing-summary`))}>
                <FileJson size={16} />
                Erklärung
              </button>
              <button type="button" onClick={() => onDownload(String(year.evidence_endpoint ?? `/api/v1/tax-years/${String(year.year)}/evidence`))}>
                <FileJson size={16} />
                Belegkarte
              </button>
              <button type="button" onClick={() => onDownload(String(year.evidence_package_endpoint ?? `/api/v1/export/tax-years/${String(year.year)}/evidence-package.zip`))}>
                <PackageCheck size={16} />
                Jahrespaket
              </button>
              <button type="button" onClick={() => onDownload(String(year.wallet_fifo_endpoint ?? `/api/v1/tax-years/${String(year.year)}/wallet-fifo-delta`))}>
                <GitBranch size={16} />
                FIFO
              </button>
              <button type="button" onClick={() => onDownload(String(year.wallet_fifo_gaps_endpoint ?? `/api/v1/tax-years/${String(year.year)}/wallet-fifo-gaps?limit=80`))}>
                <AlertTriangle size={16} />
                FIFO-Gaps
              </button>
              {year.cex_fifo_anchor_endpoint ? (
                <button type="button" onClick={() => onDownload(String(year.cex_fifo_anchor_endpoint))}>
                  <ClipboardCheck size={16} />
                  CEX-Anker
                </button>
              ) : null}
            </div>
            {Array.isArray(year.required_evidence_refs) && year.required_evidence_refs.length > 0 ? (
              <div className="reportEvidenceRefs">
                {year.required_evidence_refs.slice(0, 6).map((ref, index) => (
                  <button key={String(ref)} type="button" onClick={() => onDownload(String(ref))} title={String(ref)}>
                    {String(Array.isArray(year.required_evidence_labels) ? year.required_evidence_labels[index] : "").trim() || String(ref).split("/").pop() || String(ref)}
                  </button>
                ))}
              </div>
            ) : null}
          </div>
        ))}
      </div>

      {exportViewMode === "expert" ? (
        <>
      <div className="reportArtifactGrid">
        {artifacts.map((artifact) => (
          <div key={String(artifact.artifact_id)} className="reportArtifact">
            <div className="panelToolbar">
              <strong>{String(artifact.label ?? artifact.artifact_id)}</strong>
              <span className={`statusPill ${reportTone(artifact.status)}`}>{String(artifact.status ?? "-")}</span>
            </div>
            <p>{String(artifact.note ?? artifact.endpoint ?? "")}</p>
            {artifact.created_at ? <span>Erstellt {formatDateTime(artifact.created_at)}</span> : null}
            {artifact.package_id ? (
              <button type="button" onClick={() => onDownload(`/api/v1/export/packages/${String(artifact.package_id)}/download.pdf`)}>
                <FileDown size={16} />
                herunterladen
              </button>
            ) : null}
            {artifact.endpoint && !artifact.package_id && artifact.kind !== "pdf" ? (
              <button type="button" onClick={() => onDownload(String(artifact.endpoint))}>
                <FileDown size={16} />
                herunterladen
              </button>
            ) : null}
          </div>
        ))}
      </div>

      <TablePanel
        title="CSV-Exports"
        rows={csvExports}
        rowActions={[
          {
            label: "CSV herunterladen",
            icon: <FileDown size={16} />,
            onClick: (row) => onDownload(String(row.endpoint ?? ""))
          }
        ]}
      />
        </>
      ) : null}
    </Stack>
  );
}

function ExportReadinessPanel({
  readiness
}: {
  readiness: Record<string, unknown> | undefined;
}) {
  return (
    <Stack>
      <div className={`panel reviewStatusPanel ${readiness?.allow_export ? "ok" : "blocked"}`}>
        <div className="panelToolbar">
          <strong>Export-Freigabe</strong>
          <span className={`statusPill ${readiness?.allow_export ? "ok" : "blocked"}`}>
            {readiness?.allow_export ? "freigegeben" : "blockiert"}
          </span>
        </div>
        <div className="reviewSummary">
          <Metric title="Aktuell offen" value={String(readiness?.review_issues_current_open ?? readiness?.review_issues_open ?? 0)} />
          <Metric title="Historisch offen" value={String(readiness?.review_issues_historical_open ?? 0)} />
          <Metric title="Gesamt sichtbar" value={String(readiness?.review_issues_open_total ?? readiness?.review_issues_open ?? 0)} />
          <Metric title="Blockierend" value={String(readiness?.review_blocking_issues_open ?? 0)} />
          <Metric title="Parity" value={readiness?.parity_release_ready ? "releasebereit" : "blockiert"} />
          <Metric title="Parity offen" value={String(readiness?.parity_unresolved_groups ?? 0)} />
          <Metric title="Parity blockierend" value={String(readiness?.parity_blocking_groups ?? 0)} />
          <Metric title="Parity Diff EUR" value={formatCurrency(readiness?.parity_blocking_difference_eur ?? 0)} />
          <Metric title="Tax-Lines" value={String(readiness?.tax_lines_count ?? 0)} />
          <Metric title="Unmatched FIFO" value={String(readiness?.unmatched_disposals ?? 0)} />
          <Metric title="Derivate-Zeilen" value={String(readiness?.derivative_lines_count ?? 0)} />
          <Metric title="PDF-Seitenlimit" value={String(readiness?.max_pdf_pages_per_file ?? 100)} />
        </div>
      </div>
      <KeyValuePanel title="Export-Freigabe Details" data={readiness ?? {}} />
    </Stack>
  );
}

function ParityPanel({
  parity,
  diagnostics,
  releaseReadiness,
  references,
  hntFifoProvenance,
  onAddV1Reference,
  onAddParityDecision,
  onDeleteV1Reference,
  onDownload
}: {
  parity: Snapshot["parity"];
  diagnostics: Snapshot["parityDiagnostics"];
  releaseReadiness: Snapshot["parityReleaseReadiness"];
  references: Array<Record<string, unknown>>;
  hntFifoProvenance: Snapshot["hntFifoProvenance"];
  onAddV1Reference: (payload: Record<string, unknown>) => void;
  onAddParityDecision: (scope: string, decisionStatus: string) => void;
  onDeleteV1Reference: (referenceId: string) => void;
  onDownload: (path: string) => void;
}) {
  const rows = (parity?.rows ?? []).map((row) => {
    const reference = row.reference as Record<string, unknown> | undefined;
    return {
      status: row.status,
      scope: reference?.scope,
      metric: reference?.metric,
      unit: reference?.unit,
      year: reference?.year,
      asset: reference?.asset,
      source: reference?.source,
      v1_value: reference?.value,
      v2_value: row.v2_value,
      difference: row.difference,
      note: reference?.note,
      reference_id: reference?.reference_id
    };
  });
  const diagnosticRows = (diagnostics?.groups ?? []).map((group) => ({
    scope: group.scope,
    decision_status: group.decision_status,
    year: group.year,
    asset: group.asset,
    status: group.status,
    issue_count: group.issue_count,
    metrics: Array.isArray(group.metrics) ? group.metrics.join(", ") : group.metrics,
    absolute_difference_eur: group.absolute_difference_eur,
    max_absolute_difference: group.max_absolute_difference,
    v1_total_eur: group.v1_total_eur,
    v2_total_eur: group.v2_total_eur
  }));
  return (
    <Stack>
      <div className={`panel reviewStatusPanel ${releaseReadiness?.release_ready ? "ok" : "blocked"}`}>
        <div className="panelToolbar">
          <strong>Paritaets-Release</strong>
          <span className={`statusPill ${releaseReadiness?.release_ready ? "ok" : "blocked"}`}>
            {releaseReadiness?.release_ready ? "bereit" : "nicht bereit"}
          </span>
        </div>
        <div className="reviewSummary">
          <Metric title="Blockierende Gruppen" value={String(releaseReadiness?.blocking_groups ?? 0)} />
          <Metric title="Unreviewed" value={String(releaseReadiness?.unresolved_groups ?? 0)} />
          <Metric title="Akzeptiert" value={String(releaseReadiness?.accepted_groups ?? 0)} />
          <Metric title="Blockierende EUR-Diff" value={formatCurrency(releaseReadiness?.blocking_difference_eur)} />
        </div>
      </div>
      <div className="grid">
        <Metric title="Verglichen" value={String(parity?.compared ?? 0)} />
        <Metric title="Matches" value={String(parity?.matches ?? 0)} />
        <Metric title="Abweichungen" value={String(parity?.differences ?? 0)} />
        <Metric title="Fehlt in V2" value={String(parity?.missing_v2 ?? 0)} />
      </div>
      <HntFifoProvenancePanel report={hntFifoProvenance} onDownload={onDownload} />
      <V1ReferenceForm onAddV1Reference={onAddV1Reference} />
      <TablePanel
        title="Blockierende Paritaetsgruppen"
        rows={releaseReadiness?.blocking_groups_top ?? []}
        footer="Diese Gruppen verhindern nicht den technischen Export, aber den fachlichen Wechsel von V1 zu V2."
        rowActions={[
          {
            label: "Details JSON",
            icon: <FileDown size={16} />,
            onClick: (row) => onDownload(`/api/v1/parity/group-detail?scope=${encodeURIComponent(String(row.scope ?? ""))}`)
          },
          {
            label: "Als V1-Fehler markieren",
            icon: <Scale size={16} />,
            onClick: (row) => onAddParityDecision(String(row.scope ?? ""), "v1_known_wrong")
          },
          {
            label: "Als V2-Datenluecke markieren",
            icon: <Database size={16} />,
            onClick: (row) => onAddParityDecision(String(row.scope ?? ""), "v2_missing_data")
          },
          {
            label: "Manuelle Evidenz erforderlich",
            icon: <ReceiptText size={16} />,
            onClick: (row) => onAddParityDecision(String(row.scope ?? ""), "needs_manual_evidence")
          },
          {
            label: "Differenz akzeptieren",
            icon: <Check size={16} />,
            onClick: (row) => onAddParityDecision(String(row.scope ?? ""), "accepted_difference")
          }
        ]}
      />
      <TablePanel
        title="Paritaets-Diagnose"
        rows={diagnosticRows}
        actionLabel="CSV"
        onAction={() => onDownload("/api/v1/export/parity-diagnostics.csv")}
        footer={`Gruppen: ${diagnosticRows.length} | Diff: ${diagnostics?.differences ?? 0} | Missing: ${diagnostics?.missing_v2 ?? 0}`}
        rowActions={[
          {
            label: "Details JSON",
            icon: <FileDown size={16} />,
            onClick: (row) => onDownload(`/api/v1/parity/group-detail?scope=${encodeURIComponent(String(row.scope ?? ""))}`)
          },
          {
            label: "Als V1-Fehler markieren",
            icon: <Scale size={16} />,
            onClick: (row) => onAddParityDecision(String(row.scope ?? ""), "v1_known_wrong")
          },
          {
            label: "Als V2-Datenluecke markieren",
            icon: <Database size={16} />,
            onClick: (row) => onAddParityDecision(String(row.scope ?? ""), "v2_missing_data")
          },
          {
            label: "Differenz akzeptieren",
            icon: <ReceiptText size={16} />,
            onClick: (row) => onAddParityDecision(String(row.scope ?? ""), "accepted_difference")
          }
        ]}
      />
      <TablePanel
        title="V1/V2-Abweichungen"
        rows={rows}
        footer={`Max Differenz: ${String(parity?.max_absolute_difference ?? "0")}`}
      />
      <TablePanel
        title="V1-Referenzwerte"
        rows={references}
        rowActions={[
          {
            label: "Referenz entfernen",
            icon: <Trash2 size={16} />,
            tone: "danger",
            onClick: (row) => onDeleteV1Reference(String(row.reference_id ?? ""))
          }
        ]}
      />
    </Stack>
  );
}

function HntFifoProvenancePanel({
  report,
  onDownload
}: {
  report: Snapshot["hntFifoProvenance"];
  onDownload: (path: string) => void;
}) {
  if (!report) {
    return null;
  }
  const eventRows = (report.events ?? []).slice(0, 80).map((event) => ({
    event_time: event.event_time,
    source: event.source,
    event_type: sourceStatusLabel(event.event_type),
    direction: event.direction,
    quantity: event.quantity,
    account: event.account,
    counterparty_account: event.counterparty_account,
    current_portfolio_account: event.current_portfolio_account,
    fifo_relevant: event.fifo_relevant,
    tx_id: event.tx_id,
    note: event.note
  }));
  const timelineRows = (report.timeline ?? []).map((step) => ({
    label: step.label,
    role: step.role,
    event_count: step.event_count,
    quantity_in: step.quantity_in,
    quantity_out: step.quantity_out,
    net_quantity: step.net_quantity,
    first_event_at: step.first_event_at,
    last_event_at: step.last_event_at,
    note: step.note
  }));
  const lotRows = (report.open_fifo_lots ?? []).slice(0, 80).map((lot) => ({
    acquired_at: lot.acquired_at,
    quantity_total: lot.quantity_total,
    quantity_remaining: lot.quantity_remaining,
    cost_basis_eur_total: lot.cost_basis_eur_total,
    source: lot.source,
    account: lot.account,
    source_ref: lot.source_ref,
    tx_id: lot.tx_id
  }));
  const disposalRows = (report.disposal_tax_lines ?? []).slice(0, 80).map((line) => ({
    disposed_at: line.disposed_at,
    acquired_at: line.acquired_at,
    quantity: line.quantity,
    acquisition_cost_eur: line.acquisition_cost_eur,
    disposal_proceeds_eur: line.disposal_proceeds_eur,
    gain_loss_eur: line.gain_loss_eur,
    holding_days: line.holding_days,
    disposal_source: line.disposal_source,
    disposal_account: line.disposal_account,
    source_ref: line.source_ref,
    tx_id: line.tx_id
  }));
  return (
    <div className="panel">
      <div className="panelToolbar">
        <strong>HNT FIFO-Herkunft</strong>
        <div className="toolbarActions">
          <button type="button" onClick={() => onDownload("/api/v1/parity/hnt-fifo-provenance?limit=1000")}>
            JSON
          </button>
          <button type="button" onClick={() => onDownload("/api/v1/parity/hnt-fifo-provenance?limit=1000&source=binance")}>
            Binance
          </button>
          <button type="button" onClick={() => onDownload("/api/v1/parity/hnt-fifo-provenance?limit=1000&account=13xfSeV2UcVgUiTKmd9V1Htunc6N7wsAgkGRHtquN9hpCbA78Yp")}>
            Fairspot
          </button>
        </div>
      </div>
      <div className="portfolioSummaryStrip">
        <Metric title="FIFO-Events" value={String(report.fifo_relevant_events ?? 0)} />
        <Metric title="Aktuelle Wallet-Events" value={String(report.current_portfolio_events ?? 0)} />
        <Metric title="Transfer-Gegenparteien" value={String(report.transfer_counterparty_events ?? 0)} />
        <Metric title="Offene HNT-Lots" value={String(report.open_lots ?? 0)} />
      </div>
      <div className="statusRows">
        <StatusRow label="Aktiver Filter" value={[report.filter_source ? `Quelle ${report.filter_source}` : null, report.filter_account ? `Konto ${shortAccount(report.filter_account)}` : null].filter(Boolean).join(" · ") || "keiner"} />
        <StatusRow label="Aktuelle Wallets" value={(report.current_portfolio_accounts ?? []).map((account) => shortAccount(account)).join(", ") || "-"} />
        <StatusRow label="Transfer-Kontext" value={(report.transfer_counterparty_accounts ?? []).map((account) => shortAccount(account)).join(", ") || "-"} />
        <StatusRow label="Methodik" value={report.methodology ?? "-"} />
      </div>
      <TablePanel
        title="HNT Bridge-Timeline"
        rows={timelineRows}
        footer="Komprimierte Sicht auf Legacy-, CEX- und aktuelle Wallet-Kontexte in der geladenen Belegkette."
      />
      <TablePanel
        title="HNT Belegkette"
        rows={eventRows}
        footer="Transfers bleiben als Herkunftsbelege sichtbar. Nur Erwerb/Verkauf/Income ist FIFO-relevant."
      />
      <TablePanel
        title="Offene HNT FIFO-Lots"
        rows={lotRows}
        footer="Offene Lots aus der bestehenden FIFO-Tabelle; read-only."
      />
      <TablePanel
        title="Genutzte HNT Tax-Lines"
        rows={disposalRows}
        footer={`Tax-Lines: ${report.disposals ?? 0}. Vollstaendige Event-IDs sind im JSON enthalten.`}
      />
    </div>
  );
}

function V1ReferenceForm({
  onAddV1Reference
}: {
  onAddV1Reference: (payload: Record<string, unknown>) => void;
}) {
  const [scope, setScope] = useState("tax");
  const [metric, setMetric] = useState("gain_loss_eur");
  const [unit, setUnit] = useState("EUR");
  const [value, setValue] = useState("0");
  const [year, setYear] = useState("2021");
  const [asset, setAsset] = useState("");
  const [source, setSource] = useState("");
  const [note, setNote] = useState("");
  return (
    <div className="panel formPanel">
      <div className="panelToolbar">
        <strong>V1-Referenzwert</strong>
        <button
          type="button"
          onClick={() =>
            onAddV1Reference({
              scope,
              metric,
              unit,
              value,
              year: year.trim() ? Number.parseInt(year, 10) : null,
              asset: asset.trim() || null,
              source: source.trim() || null,
              note: note.trim() || null
            })
          }
        >
          Speichern
        </button>
      </div>
      <div className="formGrid">
        <label>
          Scope
          <select value={scope} onChange={(event) => setScope(event.target.value)}>
            <option value="tax">Steuer</option>
            <option value="portfolio">Portfolio</option>
            <option value="flow">Geldfluss</option>
          </select>
        </label>
        <label>
          Kennzahl
          <input value={metric} onChange={(event) => setMetric(event.target.value)} />
        </label>
        <label>
          Einheit
          <input value={unit} onChange={(event) => setUnit(event.target.value.toUpperCase())} />
        </label>
        <label>
          V1-Wert
          <input value={value} onChange={(event) => setValue(event.target.value)} />
        </label>
        <label>
          Jahr
          <input value={year} onChange={(event) => setYear(event.target.value)} />
        </label>
        <label>
          Asset
          <input value={asset} onChange={(event) => setAsset(event.target.value.toUpperCase())} />
        </label>
        <label>
          Quelle
          <input value={source} onChange={(event) => setSource(event.target.value)} />
        </label>
        <label>
          Notiz
          <input value={note} onChange={(event) => setNote(event.target.value)} />
        </label>
      </div>
    </div>
  );
}

function TaxPanel({
  taxSummary,
  taxHoldingPeriods,
  taxLossRealizationPlanner,
  taxYearsSummary,
  taxPaymentOverview,
  taxYearFilingMatrix,
  taxFilingClosureOverview,
  taxYearsCorrectionMap,
  taxMethodologySummary,
  taxBmfActionPlan,
  taxYearDetail,
  taxDeclarationGuide,
  taxYearFilingSummary,
  taxYearCorrectionMap,
  taxYearMethodology,
  taxYearWalletFifoDelta,
  taxYearWalletFifoGaps,
  taxYearWalletFifoOriginTrace,
  taxYearCexDepositTransferEvidence,
  taxYearCexSenderOwnershipLatest,
  taxYearCexExchangeOutflowEvidence,
  taxYearCexExchangeOutflowAnchorFeasibility,
  taxYearWalletFifoProvenanceClosure,
  taxYearWalletFifoProvenancePriorities,
  taxYearWalletFifoRawProvenanceBreakdown,
  taxYearWalletFifoExchangeEvidenceGaps,
  taxYearWalletFifoSolanaProvenanceClassification,
  taxYearWalletFifoSolanaProvenanceBatchLatest,
  taxYearWalletFifoSolanaRawProvenanceSenders,
  taxYearWalletFifoSolanaRawProvenancePriorities,
  taxYearWalletFifoSolanaRawBmfEvidenceSummary,
  taxYearWalletFifoSolanaRawBmfEvidenceDrilldown,
  taxYearWalletFifoSolanaSenderClusters,
  taxYearWalletFifoSolanaSenderClusterOutflows,
  taxYearWalletFifoSolanaOrigin,
  taxLegacyHeliumOverview,
  taxIncomeGuide,
  taxRewardTradingSeparation,
  taxYearDrivers,
  taxYearGainLossRealityCheck,
  taxYearTurnoverAudit,
  taxYearsTurnoverAuditSummary,
  taxSolanaProgramIncomeReview,
  taxStablecoinFifoReview,
  taxStablecoinQuoteLegReview,
  taxSolanaStablecoinSwapContext,
  taxSolanaStablecoinFxReview,
  taxYearEvidence,
  taxExternalInflows,
  taxLots,
  taxLines,
  taxUnmatchedDisposals,
  derivativeSummary,
  derivativeLines,
  selectedTaxYear,
  onSelectedTaxYearChange,
  taxViewMode,
  onTaxViewModeChange,
  minHoldingValueEur,
  onMinHoldingValueEurChange,
  onRebuildTax,
  onRebuildDerivatives,
  onAddCexSenderOwnershipDecision,
  onDownload
}: {
  taxSummary: Record<string, unknown> | null | undefined;
  taxHoldingPeriods: Snapshot["taxHoldingPeriods"];
  taxLossRealizationPlanner: Snapshot["taxLossRealizationPlanner"];
  taxYearsSummary: Snapshot["taxYearsSummary"];
  taxPaymentOverview: Snapshot["taxPaymentOverview"];
  taxYearFilingMatrix: Snapshot["taxYearFilingMatrix"];
  taxFilingClosureOverview: Snapshot["taxFilingClosureOverview"];
  taxYearsCorrectionMap: Snapshot["taxYearsCorrectionMap"];
  taxMethodologySummary: Snapshot["taxMethodologySummary"];
  taxBmfActionPlan: Snapshot["taxBmfActionPlan"];
  taxYearDetail: Snapshot["taxYearDetail"];
  taxDeclarationGuide: Snapshot["taxDeclarationGuide"];
  taxYearFilingSummary: Snapshot["taxYearFilingSummary"];
  taxYearCorrectionMap: Snapshot["taxYearCorrectionMap"];
  taxYearMethodology: Snapshot["taxYearMethodology"];
  taxYearWalletFifoDelta: Snapshot["taxYearWalletFifoDelta"];
  taxYearWalletFifoGaps: Snapshot["taxYearWalletFifoGaps"];
  taxYearWalletFifoOriginTrace: Snapshot["taxYearWalletFifoOriginTrace"];
  taxYearCexDepositTransferEvidence: Snapshot["taxYearCexDepositTransferEvidence"];
  taxYearCexSenderOwnershipLatest: Snapshot["taxYearCexSenderOwnershipLatest"];
  taxYearCexExchangeOutflowEvidence: Snapshot["taxYearCexExchangeOutflowEvidence"];
  taxYearCexExchangeOutflowAnchorFeasibility: Snapshot["taxYearCexExchangeOutflowAnchorFeasibility"];
  taxYearWalletFifoProvenanceClosure: Snapshot["taxYearWalletFifoProvenanceClosure"];
  taxYearWalletFifoProvenancePriorities: Snapshot["taxYearWalletFifoProvenancePriorities"];
  taxYearWalletFifoRawProvenanceBreakdown: Snapshot["taxYearWalletFifoRawProvenanceBreakdown"];
  taxYearWalletFifoExchangeEvidenceGaps: Snapshot["taxYearWalletFifoExchangeEvidenceGaps"];
  taxYearWalletFifoSolanaProvenanceClassification: Snapshot["taxYearWalletFifoSolanaProvenanceClassification"];
  taxYearWalletFifoSolanaProvenanceBatchLatest: Snapshot["taxYearWalletFifoSolanaProvenanceBatchLatest"];
  taxYearWalletFifoSolanaRawProvenanceSenders: Snapshot["taxYearWalletFifoSolanaRawProvenanceSenders"];
  taxYearWalletFifoSolanaRawProvenancePriorities: Snapshot["taxYearWalletFifoSolanaRawProvenancePriorities"];
  taxYearWalletFifoSolanaRawBmfEvidenceSummary: Snapshot["taxYearWalletFifoSolanaRawBmfEvidenceSummary"];
  taxYearWalletFifoSolanaRawBmfEvidenceDrilldown: Snapshot["taxYearWalletFifoSolanaRawBmfEvidenceDrilldown"];
  taxYearWalletFifoSolanaSenderClusters: Snapshot["taxYearWalletFifoSolanaSenderClusters"];
  taxYearWalletFifoSolanaSenderClusterOutflows: Snapshot["taxYearWalletFifoSolanaSenderClusterOutflows"];
  taxYearWalletFifoSolanaOrigin: Snapshot["taxYearWalletFifoSolanaOrigin"];
  taxLegacyHeliumOverview: Snapshot["taxLegacyHeliumOverview"];
  taxIncomeGuide: Snapshot["taxIncomeGuide"];
  taxRewardTradingSeparation: Snapshot["taxRewardTradingSeparation"];
  taxYearDrivers: Snapshot["taxYearDrivers"];
  taxYearGainLossRealityCheck: Snapshot["taxYearGainLossRealityCheck"];
  taxYearTurnoverAudit: Snapshot["taxYearTurnoverAudit"];
  taxYearsTurnoverAuditSummary: Snapshot["taxYearsTurnoverAuditSummary"];
  taxSolanaProgramIncomeReview: Snapshot["taxSolanaProgramIncomeReview"];
  taxStablecoinFifoReview: Snapshot["taxStablecoinFifoReview"];
  taxStablecoinQuoteLegReview: Snapshot["taxStablecoinQuoteLegReview"];
  taxSolanaStablecoinSwapContext: Snapshot["taxSolanaStablecoinSwapContext"];
  taxSolanaStablecoinFxReview: Snapshot["taxSolanaStablecoinFxReview"];
  taxYearEvidence: Snapshot["taxYearEvidence"];
  taxExternalInflows: Snapshot["taxExternalInflows"];
  taxLots: Array<Record<string, unknown>>;
  taxLines: Array<Record<string, unknown>>;
  taxUnmatchedDisposals: Array<Record<string, unknown>>;
  derivativeSummary: Record<string, unknown> | null | undefined;
  derivativeLines: Array<Record<string, unknown>>;
  selectedTaxYear: string;
  onSelectedTaxYearChange: (year: string) => void;
  taxViewMode: TaxViewMode;
  onTaxViewModeChange: (mode: TaxViewMode) => void;
  minHoldingValueEur: string;
  onMinHoldingValueEurChange: (value: string) => void;
  onRebuildTax: () => void;
  onRebuildDerivatives: () => void;
  onAddCexSenderOwnershipDecision: (row: Record<string, unknown>, decisionStatus: string) => void;
  onDownload: (path: string) => void;
}) {
  const gainLossTotal = taxLines.reduce(
    (total, line) => total + Number(line.gain_loss_eur ?? 0),
    0
  );
  const derivativeTotal = derivativeLines.reduce(
    (total, line) => total + Number(line.value_eur ?? 0),
    0
  );
  const years = taxYearsSummary?.years ?? [];
  const selectedYear = taxYearDetail ?? years.find((year) => String(year.year) === selectedTaxYear);
  const activeYearValue = String(selectedYear?.year ?? selectedTaxYear);
  const holdingLots = taxHoldingPeriods?.lots ?? [];
  const holdingBuckets = taxHoldingPeriods?.buckets ?? [];
  const paymentRows = taxPaymentOverview?.rows ?? [];
  const activePaymentRow = paymentRows.find((row) => String(row.year) === activeYearValue);
  const methodologyYears = taxMethodologySummary?.years ?? [];
  const activeMethodologyStatus = methodologyYears.find((row) => String(row.year) === activeYearValue);
  const activeBmfActionItems = (taxBmfActionPlan?.items ?? [])
    .filter((item) => String(item.year) === activeYearValue)
    .slice(0, 8);
  const methodologyGaps = taxYearMethodology?.gaps ?? [];
  const methodologyMetrics = taxYearMethodology?.metrics ?? [];
  const paymentChecklist = Array.isArray(activePaymentRow?.checklist)
    ? activePaymentRow.checklist as Array<Record<string, unknown>>
    : [];
  const checklistWarnings = paymentChecklist.filter((item) => String(item.severity ?? "") === "warning");
  const blockingMethodologyGaps = methodologyGaps.filter((gap) => gap.blocks_bmf_ready);
  const yearNeedsReview = checklistWarnings.length > 0 || blockingMethodologyGaps.length > 0 || taxYearFilingSummary?.export_ready === false;
  const yearDecisionTone = yearNeedsReview ? "warning" : activePaymentRow || taxYearFilingSummary ? "ok" : "blocked";
  const yearDecisionHeadline = yearNeedsReview
    ? `${activeYearValue}: vor Abgabe pruefen`
    : activePaymentRow || taxYearFilingSummary
      ? `${activeYearValue}: Eingabewerte vorbereitet`
      : `${activeYearValue}: Daten werden geladen`;
  const yearDecisionText = activePaymentRow?.what_to_do
    ? String(activePaymentRow.what_to_do)
    : taxYearFilingSummary?.plain_language_summary ?? "Jahreswerte werden geladen. Die Ansicht zeigt danach die eintragbaren Betraege und Belege.";
  const nextChecklistItem = checklistWarnings[0] ?? paymentChecklist[0];
  const nextChecklistEvidence = String(nextChecklistItem?.evidence_ref ?? `/api/v1/tax-years/${activeYearValue}/filing-summary`);
  const walletFifoUnmatched = Number(taxYearWalletFifoDelta?.unmatched_count ?? 0);
  const walletFifoTransfers = taxYearWalletFifoDelta?.transfer_traces ?? [];
  const walletFifoProvenanceGroups = taxYearWalletFifoProvenancePriorities?.groups ?? [];
  const unresolvedInboundProvenance = Number(
    taxYearWalletFifoProvenancePriorities?.unresolved_inbound_provenance_count
      ?? taxYearWalletFifoDelta?.unresolved_inbound_provenance_count
      ?? 0
  );
  const walletFifoFeeTransfers = walletFifoTransfers.filter((trace) => Number(trace.fee_quantity ?? 0) > 0);
  const walletFifoOk = Boolean(taxYearWalletFifoDelta) && walletFifoUnmatched === 0 && unresolvedInboundProvenance === 0;
  const cexOutflowAnchorItems = taxYearCexExchangeOutflowAnchorFeasibility?.items ?? [];
  const cexOutflowAnchorTone = Number(taxYearCexExchangeOutflowAnchorFeasibility?.anchor_missing_count ?? 0) > 0 ? "warning" : "ok";
  const legacyHeliumWallets = taxLegacyHeliumOverview?.wallets ?? [];
  const legacyHeliumTransfers = taxLegacyHeliumOverview?.fairspot_transfers ?? [];
  const walletFifoClosureItems = taxYearWalletFifoProvenanceClosure?.items ?? [];
  const walletFifoClosureTone = Number(taxYearWalletFifoProvenanceClosure?.review_required_count ?? 0) > 0 ? "warning" : "ok";
  const walletFifoTone = walletFifoOk ? "ok" : walletFifoUnmatched > 0 ? "blocked" : "warning";
  const walletFifoProofLabel = walletFifoOk
    ? "FIFO-Nachverfolgung ohne offene Pool-Luecken"
    : walletFifoUnmatched > 0
      ? `${walletFifoUnmatched} offene Pool-Luecke(n)`
      : unresolvedInboundProvenance > 0
        ? `${unresolvedInboundProvenance} offene Zufluss-Herkunft(en)`
      : "FIFO-Nachverfolgung wird geladen";
  const filingLines = taxYearFilingSummary?.lines ?? [];
  const entryLines = filingLines.filter((line) => !["appendix", "evidence", "review"].includes(String(line.topic)));
  const proofLines = filingLines.filter((line) => ["appendix", "evidence", "review"].includes(String(line.topic)));
  const filingChecklist = taxYearFilingSummary?.checklist ?? [];
  const filingMatrixRows = taxYearFilingMatrix?.rows ?? [];
  const filingClosureRows = taxFilingClosureOverview?.rows ?? [];
  const activeFilingMatrixRow = filingMatrixRows.find((row) => String(row.year) === activeYearValue);
  const activeRewardTradingRows = (taxRewardTradingSeparation?.rows ?? []).filter(
    (row) => String(row.year) === activeYearValue
  );
  const activeRewardTradingTotals = activeRewardTradingRows.reduce(
    (totals: { reward: number; taxableTrade: number; taxFreeTrade: number }, row) => ({
      reward: totals.reward + Number(row.reward_income_eur ?? 0),
      taxableTrade: totals.taxableTrade + Number(row.trade_taxable_gain_loss_eur ?? 0),
      taxFreeTrade: totals.taxFreeTrade + Number(row.trade_tax_free_gain_loss_eur ?? 0)
    }),
    { reward: 0, taxableTrade: 0, taxFreeTrade: 0 }
  );
  const groupedFilingChecklist = {
    eintragen: filingChecklist.filter((item) => String(item.category) === "eintragen"),
    beilegen: filingChecklist.filter((item) => String(item.category) === "beilegen"),
    pruefen: filingChecklist.filter((item) => String(item.category) === "pruefen"),
    archivieren: filingChecklist.filter((item) => String(item.category) === "archivieren")
  };
  const filingActionGroups = [
    {
      key: "eintragen",
      label: "Eintragen",
      detail: "Betraege fuer Anlage SO, Rewards oder Sonderposten uebernehmen.",
      tone: "ok",
      icon: <ReceiptText size={18} />,
      items: groupedFilingChecklist.eintragen
    },
    {
      key: "beilegen",
      label: "Beilegen",
      detail: "BMF-/Herkunftsbeilage und Jahrespaket zur Erklaerung bereithalten.",
      tone: "warning",
      icon: <PackageCheck size={18} />,
      items: groupedFilingChecklist.beilegen
    },
    {
      key: "pruefen",
      label: "Separat pruefen",
      detail: "Nicht automatisch in die Hauptsumme mischen; vor Abgabe fachlich ansehen.",
      tone: groupedFilingChecklist.pruefen.length > 0 ? "warning" : "ok",
      icon: <AlertTriangle size={18} />,
      items: groupedFilingChecklist.pruefen
    },
    {
      key: "archivieren",
      label: "Archivieren",
      detail: "Nicht eintragen, aber fuer Stichtag, Haltefrist und Nachweis aufbewahren.",
      tone: "ok",
      icon: <Database size={18} />,
      items: groupedFilingChecklist.archivieren
    }
  ];
  const correctionMapYears = (taxYearsCorrectionMap?.years ?? []) as Array<Record<string, unknown>>;
  const activeCorrectionMap = (taxYearCorrectionMap ?? correctionMapYears.find((row) => String(row.year) === activeYearValue)) as Record<string, unknown> | undefined;
  const correctionLines = (Array.isArray(activeCorrectionMap?.lines) ? activeCorrectionMap.lines : []) as Array<Record<string, unknown>>;
  const yearReviewDecisions = taxYearFilingSummary?.review_decisions ?? taxDeclarationGuide?.review_decisions ?? [];
  const activeEvidenceItems = taxYearEvidence?.items ?? [];
  const primaryEvidenceItems = activeEvidenceItems.filter((item) => item.required || item.category === "eintragen");
  const solanaSwapEvidenceItem = activeEvidenceItems.find((item) => String(item.evidence_id) === "tax-solana-stablecoin-swap-evidence");
  const solanaSwapFifoEvidenceItem = activeEvidenceItems.find((item) => String(item.evidence_id) === "tax-solana-stablecoin-swap-fifo-lines");
  const hasSolanaSwapEvidence = Boolean(solanaSwapEvidenceItem || solanaSwapFifoEvidenceItem || (taxSolanaStablecoinSwapContext?.events_count ?? 0) > 0);
  return (
    <Stack>
      <section className="taxYearHero">
        <div>
          <span className="heroKicker">Steuerjahr-Cockpit</span>
          <h2>{activeYearValue}</h2>
          <p>Gefuehrte Sicht auf Steuererklaerung, BMF-Status, FIFO-Nachweis und Belege fuer das gewaehlte Jahr.</p>
        </div>
        <div className="taxYearSelector">
          <label>
            Steuerjahr
            <select value={selectedTaxYear} onChange={(event) => onSelectedTaxYearChange(event.target.value)}>
              {(taxYearsSummary?.available_years ?? [2020, 2021, 2022, 2023, 2024, 2025, 2026]).map((year) => (
                <option key={year} value={String(year)}>{year}</option>
              ))}
            </select>
          </label>
          <span className={`statusPill ${taxYearTone(String(selectedYear?.state ?? ""))}`}>
            {String(selectedYear?.label ?? "-")}
          </span>
        </div>
      </section>

      <section className={`taxFilingDecision ${yearDecisionTone}`}>
        <div className="taxFilingDecisionMain">
          <span className="heroKicker">Was bedeutet das fuer die Steuererklaerung?</span>
          <h3>{yearDecisionHeadline}</h3>
          <p>{yearDecisionText}</p>
          <div className="taxFilingTargets">
            <span className={`statusPill ${yearDecisionTone}`}>
              {String(activePaymentRow?.declaration_bucket ?? (yearNeedsReview ? "pruefen" : "bereit"))}
            </span>
            {activeFilingMatrixRow?.action_status ? (
              <span className={`statusPill ${String(activeFilingMatrixRow.action_status) === "blocked" ? "blocked" : String(activeFilingMatrixRow.action_status) === "review" ? "warning" : "ok"}`}>
                {filingActionStatusLabel(activeFilingMatrixRow.action_status)}
              </span>
            ) : null}
            <span>{String(activePaymentRow?.where_to_enter ?? "Eingabeziel wird geladen")}</span>
          </div>
        </div>
        <div className="taxFilingDecisionActions">
          <button type="button" onClick={() => onDownload(nextChecklistEvidence)}>
            {yearNeedsReview ? <AlertTriangle size={18} /> : <Check size={18} />}
            <span>{String(nextChecklistItem?.label ?? "Eingabehilfe oeffnen")}</span>
          </button>
          <button type="button" onClick={() => onDownload(`/api/v1/tax-years/${activeYearValue}/filing-summary`)}>
            <FileJson size={18} />
            <span>Eingabehilfe JSON</span>
          </button>
          <button type="button" onClick={() => onDownload(`/api/v1/export/tax-years/${activeYearValue}/evidence-package.zip`)}>
            <PackageCheck size={18} />
            <span>Jahres-Belegpaket</span>
          </button>
        </div>
        <div className="taxFilingDecisionMetrics">
          <Metric title="Anlage SO G/V" value={`${formatCurrency(activePaymentRow?.private_disposals_gain_loss_eur ?? taxYearFilingSummary?.taxable_private_disposals_eur)} EUR`} />
          <Metric title="Rewards/Mining" value={`${formatCurrency(activePaymentRow?.rewards_mining_staking_income_eur ?? taxYearFilingSummary?.rewards_mining_staking_income_eur)} EUR`} />
          <Metric title="Derivate" value={`${formatCurrency(activePaymentRow?.derivative_pnl_eur ?? taxYearFilingSummary?.derivative_pnl_eur)} EUR`} />
          <Metric title="Steuerfrei" value={`${formatCurrency(activePaymentRow?.tax_free_private_disposals_eur ?? taxYearFilingSummary?.tax_free_private_disposals_eur)} EUR`} />
        </div>
      </section>

      {taxFilingClosureOverview ? (
        <div className="panel declarationGuidePanel">
          <div className="panelToolbar">
            <strong>Finale Abgabeuebersicht 2021-2025</strong>
            <span className={`statusPill ${(taxFilingClosureOverview.blocked_years ?? []).length > 0 ? "blocked" : (taxFilingClosureOverview.review_years ?? []).length > 0 ? "warning" : "ok"}`}>
              {(taxFilingClosureOverview.conservative_ready_years ?? []).length} konservativ bereit
            </span>
          </div>
          <div className="portfolioSummaryStrip">
            <Metric title="Anlage SO G/V" value={`${formatCurrency(taxFilingClosureOverview.total_private_disposals_gain_loss_eur)} EUR`} />
            <Metric title="Rewards/Mining" value={`${formatCurrency(taxFilingClosureOverview.total_rewards_mining_staking_income_eur)} EUR`} />
            <Metric title="Derivate" value={`${formatCurrency(taxFilingClosureOverview.total_derivative_pnl_eur)} EUR`} />
            <Metric title="Steuerfrei archivieren" value={`${formatCurrency(taxFilingClosureOverview.total_tax_free_private_disposals_eur)} EUR`} />
          </div>
          <TablePanel
            title="Was je Steuerjahr zu tun ist"
            rows={filingClosureRows.map((row) => ({
              jahr: row.year,
              status: filingActionStatusLabel(row.filing_status),
              anlage_so_eur: formatCurrency(row.private_disposals_gain_loss_eur),
              rewards_eur: formatCurrency(row.rewards_mining_staking_income_eur),
              derivate_eur: formatCurrency(row.derivative_pnl_eur),
              eintragen: row.eintragen_count ?? 0,
              beilegen: row.beilegen_count ?? 0,
              pruefen: row.pruefen_count ?? 0,
              korrektur: row.correction_action,
              naechster_schritt: row.next_action,
              summary: row.filing_summary_endpoint,
              checklist_csv: row.filing_checklist_csv_endpoint,
              korrektur_json: row.correction_map_endpoint,
              korrektur_csv: row.correction_map_csv_endpoint,
              paket: row.evidence_package_endpoint
            }))}
            compact
            rowActions={[
              {
                label: "Jahr oeffnen",
                icon: <ReceiptText size={16} />,
                onClick: (row) => onSelectedTaxYearChange(String(row.jahr ?? activeYearValue))
              },
              {
                label: "Checkliste CSV",
                icon: <FileDown size={16} />,
                onClick: (row) => onDownload(String(row.checklist_csv ?? ""))
              },
              {
                label: "Korrekturkarte CSV",
                icon: <FileJson size={16} />,
                onClick: (row) => onDownload(String(row.korrektur_csv ?? ""))
              },
              {
                label: "Belegpaket",
                icon: <PackageCheck size={16} />,
                onClick: (row) => onDownload(String(row.paket ?? ""))
              }
            ]}
            footer={taxFilingClosureOverview.methodology}
          />
          {taxFilingClosureOverview.ascii_table ? (
            <pre className="asciiTable" aria-label="Kopierbare finale Abgabeuebersicht">
              {taxFilingClosureOverview.ascii_table}
            </pre>
          ) : null}
        </div>
      ) : null}

      <section className="taxFilingActionGrid" aria-label="Jahresaktionen fuer die Steuererklaerung">
        {filingActionGroups.map((group) => (
          <div key={group.key} className={`taxFilingActionColumn ${group.tone}`}>
            <div className="taxFilingActionHeader">
              <span>{group.icon}</span>
              <div>
                <strong>{group.label}</strong>
                <small>{group.items.length} Punkt(e)</small>
              </div>
            </div>
            <p>{group.detail}</p>
            <div className="taxFilingActionItems">
              {group.items.length === 0 ? (
                <span className="taxFilingActionEmpty">Keine Aktion in diesem Bereich.</span>
              ) : (
                group.items.slice(0, 4).map((item, index) => (
                  <div key={`${group.key}-${index}`} className="taxFilingActionItem">
                    <div>
                      <strong>{String(item.label ?? item.source_topic ?? group.label)}</strong>
                      <span>{String(item.target ?? item.done_when ?? item.action ?? "")}</span>
                    </div>
                    <div className="taxFilingActionMeta">
                      {item.amount_eur !== null && item.amount_eur !== undefined ? (
                        <span>{formatCurrency(item.amount_eur)} EUR</span>
                      ) : null}
                      {item.evidence_ref ? (
                        <button type="button" onClick={() => onDownload(String(item.evidence_ref))} title="Beleg oeffnen">
                          <FileDown size={14} />
                        </button>
                      ) : null}
                    </div>
                  </div>
                ))
              )}
              {group.items.length > 4 ? (
                <span className="taxFilingActionMore">+{group.items.length - 4} weitere in der Checkliste</span>
              ) : null}
            </div>
          </div>
        ))}
      </section>

      {filingMatrixRows.length > 0 ? (
        <TablePanel
          title="Jahresmatrix: Eintragen, Beilegen, Pruefen"
          rows={filingMatrixRows.map((row) => {
            const counts = (row.checklist_counts && typeof row.checklist_counts === "object")
              ? row.checklist_counts as Record<string, unknown>
              : {};
            return {
              jahr: row.year,
              status: filingActionStatusLabel(row.action_status),
              anlage_so_eur: formatCurrency(row.taxable_private_disposals_eur),
              rewards_eur: formatCurrency(row.rewards_mining_staking_income_eur),
              derivate_eur: formatCurrency(row.derivative_pnl_eur),
              beilegen: counts.beilegen ?? 0,
              pruefen: counts.pruefen ?? 0,
              herkunft: row.bmf_closure_appendix_items_count ?? 0,
              naechster_schritt: row.next_action,
              filing: row.filing_summary_endpoint,
              checklist_csv: row.filing_checklist_csv_endpoint,
              paket: row.evidence_package_endpoint
            };
          })}
          compact
          rowActions={[
            {
              label: "Jahr oeffnen",
              icon: <ReceiptText size={16} />,
              onClick: (row) => onSelectedTaxYearChange(String(row.jahr ?? activeYearValue))
            },
            {
              label: "Checkliste CSV",
              icon: <FileDown size={16} />,
              onClick: (row) => onDownload(String(row.checklist_csv ?? ""))
            },
            {
              label: "Belegpaket",
              icon: <PackageCheck size={16} />,
              onClick: (row) => onDownload(String(row.paket ?? ""))
            }
          ]}
          footer={taxYearFilingMatrix?.methodology ?? ""}
        />
      ) : null}

      <div className="panel declarationGuidePanel">
        <div className="panelToolbar">
          <strong>Korrekturkarte Vorjahre</strong>
          <span className={`statusPill ${activeCorrectionMap?.amendment_review_recommended ? "warning" : "ok"}`}>
            {activeCorrectionMap?.amendment_review_recommended ? "Korrektur pruefen" : "archivieren"}
          </span>
        </div>
        <p className="panelLead">
          {String(activeCorrectionMap?.amendment_reason ?? "Korrekturkarte wird geladen.")}
        </p>
        <div className="portfolioSummaryStrip">
          <Metric title="Privat G/V" value={`${formatCurrency(activeCorrectionMap?.taxable_private_disposals_eur)} EUR`} />
          <Metric title="Rewards/Mining" value={`${formatCurrency(activeCorrectionMap?.rewards_mining_staking_income_eur)} EUR`} />
          <Metric title="Derivate" value={`${formatCurrency(activeCorrectionMap?.derivative_pnl_eur)} EUR`} />
          <Metric title="Steuerfrei" value={`${formatCurrency(activeCorrectionMap?.tax_free_private_disposals_eur)} EUR`} />
          <Metric title="Jahre pruefen" value={String(taxYearsCorrectionMap?.amendment_review_years?.length ?? 0)} />
        </div>
        <div className="declarationActionBand">
          <button type="button" onClick={() => onDownload(`/api/v1/tax-years/${activeYearValue}/correction-map`)}>
            <FileJson size={16} />
            Korrekturkarte JSON
          </button>
          <button type="button" onClick={() => onDownload(`/api/v1/export/tax-years/${activeYearValue}/correction-map.csv`)}>
            <FileDown size={16} />
            Korrekturkarte CSV
          </button>
          <button type="button" onClick={() => onDownload("/api/v1/tax-years/correction-map")}>
            <FileJson size={16} />
            Alle Jahre JSON
          </button>
          <button type="button" onClick={() => onDownload("/api/v1/export/tax-years/correction-map.csv")}>
            <FileDown size={16} />
            Alle Jahre CSV
          </button>
          <button type="button" onClick={() => onDownload(`/api/v1/export/tax-years/${activeYearValue}/evidence-package.zip`)}>
            <PackageCheck size={16} />
            Jahres-Belegpaket
          </button>
        </div>
        {correctionLines.length > 0 ? (
          <TablePanel
            title="Korrektur-/Archivierungszeilen"
            rows={correctionLines.map((line) => ({
              aktion: line.action_category,
              bereich: line.label,
              betrag_eur: line.amount_eur === null || line.amount_eur === undefined ? "-" : formatCurrency(line.amount_eur),
              ziel: line.declaration_target,
              risiko: line.risk_level,
              beleg: line.evidence_ref ?? "-",
              hinweis: line.correction_note
            }))}
            compact
            rowActions={[
              {
                label: "Beleg oeffnen",
                icon: <FileDown size={16} />,
                onClick: (row) => onDownload(String(row.beleg ?? ""))
              }
            ]}
            footer={String(activeCorrectionMap?.methodology ?? "")}
          />
        ) : null}
        {taxYearsCorrectionMap?.ascii_table ? (
          <pre className="asciiTable" aria-label="Kopierbare Korrekturkarte alle Jahre">
            {taxYearsCorrectionMap.ascii_table}
          </pre>
        ) : null}
      </div>

      <div className="panel">
        <div className="panelToolbar">
          <strong>Umsatz-Plausibilitaet</strong>
          <span>{taxYearTurnoverAudit?.generated_at ? formatDateTime(taxYearTurnoverAudit.generated_at) : "wird geladen"}</span>
        </div>
        <div className="portfolioSummaryStrip">
          <Metric title="Brutto-Umsatz" value={`${formatCurrency(taxYearTurnoverAudit?.gross_disposal_proceeds_eur)} EUR`} />
          <Metric title="Steuerpflichtig G/V" value={`${formatCurrency(taxYearTurnoverAudit?.taxable_gain_loss_eur)} EUR`} />
          <Metric title="Steuerfrei G/V" value={`${formatCurrency(taxYearTurnoverAudit?.tax_free_gain_loss_eur)} EUR`} />
          <Metric title="Stablecoin-Umsatz" value={`${formatCurrency(taxYearTurnoverAudit?.stablecoin_gross_disposal_proceeds_eur)} EUR`} />
          <Metric title="Stablecoin G/V" value={`${formatCurrency(taxYearTurnoverAudit?.stablecoin_gain_loss_eur)} EUR`} />
          <Metric title="Offene Zufluesse" value={`${formatCurrency(taxYearTurnoverAudit?.external_inflows_review_unmatched_value_eur)} EUR`} />
        </div>
        <p className="reportYearSummary">
          {taxYearTurnoverAudit?.plain_language_summary ?? "Der Jahresumsatz-Audit wird geladen."}
        </p>
        {(taxYearTurnoverAudit?.caveats ?? []).length > 0 ? (
          <div className="notice inlineNotice reviewNotice">
            {(taxYearTurnoverAudit?.caveats ?? []).join(" ")}
          </div>
        ) : null}
        <TablePanel
          title="Top-Umsatztreiber nach Asset"
          rows={(taxYearTurnoverAudit?.top_assets_by_proceeds ?? []).slice(0, 8).map((row) => ({
            asset: row.asset,
            brutto_erloes_eur: formatCurrency(row.gross_disposal_proceeds_eur),
            anschaffung_eur: formatCurrency(row.acquisition_cost_eur),
            gewinn_verlust_eur: formatCurrency(row.gain_loss_eur),
            steuerpflichtig_eur: formatCurrency(row.taxable_gain_loss_eur),
            steuerfrei_eur: formatCurrency(row.tax_free_gain_loss_eur),
            stablecoin: row.stablecoin_like ? "ja" : "nein",
            zeilen: row.tax_line_count
          }))}
          compact
        />
        <TablePanel
          title="Top-Quellen nach Brutto-Umsatz"
          rows={(taxYearTurnoverAudit?.top_sources_by_proceeds ?? []).slice(0, 8).map((row) => ({
            quelle: row.source,
            typ: row.event_type,
            asset: row.asset,
            quote: row.quote_asset ?? "-",
            brutto_erloes_eur: formatCurrency(row.gross_disposal_proceeds_eur),
            gewinn_verlust_eur: formatCurrency(row.gain_loss_eur),
            zeilen: row.tax_line_count
          }))}
          footer="Brutto-Umsatz ist die EUR-Bewertung der Disposals/Swaps, nicht automatisch eingezahltes oder ausgezahltes EUR."
          compact
        />
      </div>

      <div className="panel">
        <div className="panelToolbar">
          <strong>Realisiert vs gehalten {activeYearValue}</strong>
          <span>{taxYearGainLossRealityCheck?.generated_at ? formatDateTime(taxYearGainLossRealityCheck.generated_at) : "wird geladen"}</span>
        </div>
        <div className="portfolioSummaryStrip">
          <Metric title="Realisiert steuerpfl." value={`${formatCurrency(taxYearGainLossRealityCheck?.taxable_gain_loss_eur)} EUR`} />
          <Metric title="Heute offen" value={`${formatCurrency(taxYearGainLossRealityCheck?.open_current_value_eur)} EUR`} />
          <Metric title="Heute unrealisiert" value={`${formatCurrency(taxYearGainLossRealityCheck?.open_unrealized_gain_loss_eur)} EUR`} />
          <Metric title="Verlust nicht geltend" value={`${formatCurrency(taxYearGainLossRealityCheck?.potential_loss_not_realized_eur)} EUR`} />
        </div>
        <p className="reportYearSummary">
          {taxYearGainLossRealityCheck?.plain_language_summary ?? "Realisiert-vs-gehalten-Check wird geladen."}
        </p>
        <TablePanel
          title="Asset-Bruecke: Gewinn gegen heutige offene Position"
          rows={(taxYearGainLossRealityCheck?.rows ?? []).slice(0, 12).map((row) => ({
            asset: row.asset,
            realisiert_steuerpflichtig_eur: formatCurrency(row.realized_taxable_gain_loss_eur),
            steuerfrei_eur: formatCurrency(row.realized_tax_free_gain_loss_eur),
            heute_offen_eur: formatCurrency(row.open_current_value_eur),
            offene_kosten_eur: formatCurrency(row.open_cost_basis_eur),
            heute_unrealisiert_eur: formatCurrency(row.open_unrealized_gain_loss_eur),
            verlust_nicht_geltend_eur: formatCurrency(row.potential_loss_not_realized_eur),
            hinweis: row.note
          }))}
          footer={(taxYearGainLossRealityCheck?.caveats ?? []).join(" ") || taxYearGainLossRealityCheck?.methodology || ""}
          compact
        />
      </div>

      <TablePanel
        title="Umsatz-/Stablecoin-Plausibilitaet alle Steuerjahre"
        rows={(taxYearsTurnoverAuditSummary?.years ?? []).map((row) => ({
          jahr: row.year,
          risiko: row.risk_level,
          brutto_erloes_eur: formatCurrency(row.gross_disposal_proceeds_eur),
          steuerpflichtig_eur: formatCurrency(row.taxable_gain_loss_eur),
          steuerfrei_eur: formatCurrency(row.tax_free_gain_loss_eur),
          stablecoin_brutto_eur: formatCurrency(row.stablecoin_gross_disposal_proceeds_eur),
          stablecoin_gv_eur: formatCurrency(row.stablecoin_gain_loss_eur),
          stablecoin_ratio_pct: formatPercent(row.stablecoin_gain_ratio_pct),
          offene_zufluesse_eur: formatCurrency(row.external_inflows_review_unmatched_value_eur),
          gruende: Array.isArray(row.reasons) ? row.reasons.join(", ") : row.reasons,
          audit: row.audit_endpoint
        }))}
        footer={
          taxYearsTurnoverAuditSummary
            ? `High: ${taxYearsTurnoverAuditSummary.high_risk_years_count} | Review: ${taxYearsTurnoverAuditSummary.review_years_count} | OK: ${taxYearsTurnoverAuditSummary.ok_years_count}. ${taxYearsTurnoverAuditSummary.methodology}`
            : "Jahresuebersicht wird geladen."
        }
        compact
      />

      <div className="panel">
        <div className="panelToolbar">
          <strong>Solana Programm-/Swap-Kontext</strong>
          <span>{taxSolanaProgramIncomeReview?.generated_at ? formatDateTime(taxSolanaProgramIncomeReview.generated_at) : "wird geladen"}</span>
        </div>
        <div className="portfolioSummaryStrip">
          <Metric title="Review-Events" value={String(taxSolanaProgramIncomeReview?.events_count ?? 0)} />
          <Metric title="Bewerteter Kontext" value={`${formatCurrency(taxSolanaProgramIncomeReview?.total_value_eur)} EUR`} />
          <Metric title="Jahr" value={String(taxSolanaProgramIncomeReview?.year ?? activeYearValue)} />
        </div>
        <TablePanel
          title="Assets im Solana-Programmkontext"
          rows={(taxSolanaProgramIncomeReview?.assets ?? []).slice(0, 8).map((row) => ({
            jahr: row.year,
            asset: row.asset,
            events: row.events_count,
            menge: row.quantity,
            wert_eur: formatCurrency(row.value_eur)
          }))}
          compact
        />
        <TablePanel
          title="Top Solana-Programm-/Swap-Events"
          rows={(taxSolanaProgramIncomeReview?.rows ?? []).slice(0, 10).map((row) => ({
            zeit: row.event_time,
            asset: row.asset,
            menge: row.quantity,
            wert_eur: formatCurrency(row.value_eur),
            tx_events: row.tx_total_count,
            tx_assets: row.tx_assets,
            grund: row.review_reason,
            tx: row.tx_id
          }))}
          footer={taxSolanaProgramIncomeReview?.methodology ?? "Solana-Programmkontext wird geladen."}
          compact
        />
      </div>

      <div className="panel">
        <div className="panelToolbar">
          <strong>Stablecoin-FIFO-Drilldown</strong>
          <span>{taxStablecoinFifoReview?.generated_at ? formatDateTime(taxStablecoinFifoReview.generated_at) : "wird geladen"}</span>
        </div>
        <div className="portfolioSummaryStrip">
          <Metric title="Tax-Lines" value={String(taxStablecoinFifoReview?.tax_line_count ?? 0)} />
          <Metric title="Brutto-Erloes" value={`${formatCurrency(taxStablecoinFifoReview?.disposal_proceeds_eur)} EUR`} />
          <Metric title="Kostenbasis" value={`${formatCurrency(taxStablecoinFifoReview?.acquisition_cost_eur)} EUR`} />
          <Metric title="FIFO G/V" value={`${formatCurrency(taxStablecoinFifoReview?.gain_loss_eur)} EUR`} />
          <Metric title="Steuerpflichtig" value={`${formatCurrency(taxStablecoinFifoReview?.taxable_gain_loss_eur)} EUR`} />
          <Metric title="Steuerfrei" value={`${formatCurrency(taxStablecoinFifoReview?.tax_free_gain_loss_eur)} EUR`} />
        </div>
        <TablePanel
          title="Stablecoin-FIFO nach Asset"
          rows={(taxStablecoinFifoReview?.assets ?? []).slice(0, 8).map((row) => ({
            jahr: row.year,
            asset: row.asset,
            zeilen: row.tax_line_count,
            erloes_eur: formatCurrency(row.disposal_proceeds_eur),
            kosten_eur: formatCurrency(row.acquisition_cost_eur),
            gv_eur: formatCurrency(row.gain_loss_eur),
            steuerpflichtig_eur: formatCurrency(row.taxable_gain_loss_eur),
            steuerfrei_eur: formatCurrency(row.tax_free_gain_loss_eur)
          }))}
          compact
        />
        <TablePanel
          title="Stablecoin-FIFO nach Quelle"
          rows={(taxStablecoinFifoReview?.sources ?? []).slice(0, 10).map((row) => ({
            jahr: row.year,
            asset: row.asset,
            disposal: `${row.disposal_source ?? "-"} / ${row.disposal_event_type ?? "-"}`,
            quote: row.disposal_quote_asset ?? "-",
            acquisition: `${row.acquisition_source ?? "-"} / ${row.acquisition_event_type ?? "-"}`,
            zeilen: row.tax_line_count,
            raw: row.acquisition_raw_evidence_count ?? 0,
            ohne_raw: row.acquisition_missing_raw_evidence_count ?? 0,
            erloes_eur: formatCurrency(row.disposal_proceeds_eur),
            kosten_eur: formatCurrency(row.acquisition_cost_eur),
            gv_eur: formatCurrency(row.gain_loss_eur)
          }))}
          compact
        />
        <TablePanel
          title="Top Stablecoin-FIFO-Zeilen"
          rows={(taxStablecoinFifoReview?.rows ?? []).slice(0, 12).map((row) => ({
            verkauf: row.disposed_at,
            asset: row.asset,
            menge: row.quantity,
            gv_eur: formatCurrency(row.gain_loss_eur),
            erloes_eur: formatCurrency(row.disposal_proceeds_eur),
            kosten_eur: formatCurrency(row.acquisition_cost_eur),
            halte_tage: row.holding_days,
            disposal: `${row.disposal_source ?? "-"} / ${row.disposal_quote_asset ?? "-"}`,
            acquisition: row.acquisition_classification,
            beleg: row.acquisition_evidence_status,
            datei: row.acquisition_batch_filename ?? "-",
            zeile: row.acquisition_row_number ?? "-",
            grund: row.review_reason,
            tx: row.disposal_tx_id
          }))}
          footer={taxStablecoinFifoReview?.methodology ?? "Stablecoin-FIFO wird geladen."}
          compact
        />
      </div>

      <div className="panel">
        <div className="panelToolbar">
          <strong>Stablecoin-Quote-Beine</strong>
          <span>{taxStablecoinQuoteLegReview?.generated_at ? formatDateTime(taxStablecoinQuoteLegReview.generated_at) : "wird geladen"}</span>
        </div>
        <div className="portfolioSummaryStrip">
          <Metric title="Events" value={String(taxStablecoinQuoteLegReview?.events_count ?? 0)} />
          <Metric title="erwartete Tax-Lines" value={String(taxStablecoinQuoteLegReview?.expected_tax_line_events_count ?? 0)} />
          <Metric title="fehlend" value={String(taxStablecoinQuoteLegReview?.missing_expected_tax_line_events_count ?? 0)} />
          <Metric title="Stable-Stable" value={String(taxStablecoinQuoteLegReview?.stable_to_stable_events_count ?? 0)} />
          <Metric title="Tax-Lines" value={String(taxStablecoinQuoteLegReview?.stable_tax_lines_count ?? 0)} />
          <Metric title="G/V" value={`${formatCurrency(taxStablecoinQuoteLegReview?.stable_gain_loss_eur)} EUR`} />
        </div>
        <TablePanel
          title="Stablecoin-Quote-Beine nach Quelle"
          rows={(taxStablecoinQuoteLegReview?.summaries ?? []).slice(0, 10).map((row) => ({
            jahr: row.year,
            quelle: row.source,
            stable: row.stable_asset,
            rolle: row.stable_role,
            events: row.events_count,
            erwartet: row.expected_tax_line_events_count,
            fehlend: row.missing_expected_tax_line_events_count,
            tax_lines: row.stable_tax_lines_count,
            erloes_eur: formatCurrency(row.stable_disposal_proceeds_eur),
            gv_eur: formatCurrency(row.stable_gain_loss_eur)
          }))}
          compact
        />
        <TablePanel
          title="Auffaellige Stablecoin-Quote-Events"
          rows={(taxStablecoinQuoteLegReview?.rows ?? []).slice(0, 12).map((row) => ({
            zeit: row.event_time,
            quelle: row.source,
            asset: `${row.asset} ${row.quantity}`,
            quote: `${row.quote_asset ?? "-"} ${row.quote_quantity ?? "-"}`,
            rolle: row.stable_role,
            erwartung: row.expected_tax_effect,
            tax_lines: row.stable_tax_lines_count,
            gv_eur: formatCurrency(row.stable_gain_loss_eur),
            beleg: row.batch_filename ?? "-",
            zeile: row.row_number ?? "-",
            grund: row.review_reason
          }))}
          footer={taxStablecoinQuoteLegReview?.methodology ?? "Stablecoin-Quote-Beine werden geladen."}
          compact
        />
      </div>

      <div className="panel">
        <div className="panelToolbar">
          <strong>Solana Stablecoin-Swap-Kontext</strong>
          <span>{taxSolanaStablecoinSwapContext?.generated_at ? formatDateTime(taxSolanaStablecoinSwapContext.generated_at) : "wird geladen"}</span>
        </div>
        <div className="portfolioSummaryStrip">
          <Metric title="Events" value={String(taxSolanaStablecoinSwapContext?.events_count ?? 0)} />
          <Metric title="materiell" value={String(taxSolanaStablecoinSwapContext?.material_events_count ?? 0)} />
          <Metric title="Stable-Stable" value={String(taxSolanaStablecoinSwapContext?.stable_to_stable_events_count ?? 0)} />
          <Metric title="ohne Raw" value={String(taxSolanaStablecoinSwapContext?.missing_raw_evidence_count ?? 0)} />
          <Metric title="Tax-Lines" value={String(taxSolanaStablecoinSwapContext?.stable_tax_lines_count ?? 0)} />
          <Metric title="G/V" value={`${formatCurrency(taxSolanaStablecoinSwapContext?.stable_gain_loss_eur)} EUR`} />
        </div>
        <div className="reportActionBand compactActions">
          <button
            type="button"
            disabled={!hasSolanaSwapEvidence}
            onClick={() => onDownload(`/api/v1/export/tax-solana-stablecoin-swap-evidence.csv?year=${activeYearValue}`)}
            title="CSV mit Signatur, Tokenstatus, FX-Basis und Review-Grund je Solana-Stablecoin-Swap"
          >
            <FileDown size={16} />
            Swap-Signaturen CSV
          </button>
          <button
            type="button"
            disabled={!hasSolanaSwapEvidence}
            onClick={() => onDownload(`/api/v1/export/tax-solana-stablecoin-swap-fifo-lines.csv?year=${activeYearValue}`)}
            title="CSV mit den konkreten FIFO-Tax-Line-Splits zu den Solana-Stablecoin-Swaps"
          >
            <GitBranch size={16} />
            FIFO-Splits CSV
          </button>
          <button
            type="button"
            onClick={() => onDownload(`/api/v1/export/tax-years/${activeYearValue}/evidence-package.zip`)}
            title="Jahrespaket inklusive Solana-Swap-Belegen herunterladen"
          >
            <PackageCheck size={16} />
            Jahrespaket
          </button>
        </div>
        {hasSolanaSwapEvidence ? (
          <div className="evidenceQuickGrid">
            {[solanaSwapEvidenceItem, solanaSwapFifoEvidenceItem].filter(Boolean).map((item) => (
              <button
                type="button"
                className={`evidenceQuickCard ${String(item?.status ?? "available")}`}
                key={String(item?.evidence_id)}
                onClick={() => onDownload(`${String(item?.endpoint ?? "")}?year=${activeYearValue}`)}
                title={`${String(item?.endpoint ?? "")}?year=${activeYearValue}`}
              >
                <span>{String(item?.category ?? "beleg")}</span>
                <strong>{String(item?.label ?? "-")}</strong>
                <small>{String(item?.record_count ?? 0)} Datensaetze · {item?.amount_eur === null || item?.amount_eur === undefined ? "-" : `${formatCurrency(item?.amount_eur)} EUR`}</small>
              </button>
            ))}
          </div>
        ) : null}
        <TablePanel
          title="Solana-Swap-Kontext nach Asset"
          rows={(taxSolanaStablecoinSwapContext?.assets ?? []).slice(0, 10).map((row) => ({
            jahr: row.year,
            asset: row.asset,
            quote: row.quote_asset ?? "-",
            events: row.events_count,
            raw: row.raw_evidence_count,
            tax_lines: row.stable_tax_lines_count,
            erloes_eur: formatCurrency(row.stable_disposal_proceeds_eur),
            gv_eur: formatCurrency(row.stable_gain_loss_eur)
          }))}
          compact
        />
        <TablePanel
          title="Klassifizierte Solana-Swap-Zeilen"
          rows={(taxSolanaStablecoinSwapContext?.rows ?? []).slice(0, 12).map((row) => ({
            zeit: row.event_time,
            asset: `${row.asset} ${row.quantity}`,
            quote: `${row.quote_asset ?? "-"} ${row.quote_quantity ?? "-"}`,
            tx_assets: row.tx_assets,
            tax_lines: row.stable_tax_lines_count,
            gv_eur: formatCurrency(row.stable_gain_loss_eur),
            klasse: row.classification,
            sicherheit: row.confidence,
            raw: row.raw_evidence_count,
            jupiter: `${row.jupiter_asset_status ?? "-"} / ${row.jupiter_quote_status ?? "-"}`,
            grund: row.review_reason,
            tx: row.tx_id
          }))}
          footer={taxSolanaStablecoinSwapContext?.methodology ?? "Solana-Stablecoin-Swap-Kontext wird geladen."}
          compact
        />
      </div>

      <div className="panel">
        <div className="panelToolbar">
          <strong>Solana Stablecoin Preis-/FX-Basis</strong>
          <span>{taxSolanaStablecoinFxReview?.generated_at ? formatDateTime(taxSolanaStablecoinFxReview.generated_at) : "wird geladen"}</span>
        </div>
        <div className="portfolioSummaryStrip">
          <Metric title="Events" value={String(taxSolanaStablecoinFxReview?.events_count ?? 0)} />
          <Metric title="materiell" value={String(taxSolanaStablecoinFxReview?.material_events_count ?? 0)} />
          <Metric title="fehlende Preise" value={String(taxSolanaStablecoinFxReview?.missing_price_count ?? 0)} />
          <Metric title="stale" value={String(taxSolanaStablecoinFxReview?.stale_price_count ?? 0)} />
          <Metric title="FX-basiert" value={String(taxSolanaStablecoinFxReview?.fx_backed_price_count ?? 0)} />
          <Metric title="G/V" value={`${formatCurrency(taxSolanaStablecoinFxReview?.stable_gain_loss_eur)} EUR`} />
        </div>
        <TablePanel
          title="Preis-/FX-Basis nach Stablecoin"
          rows={(taxSolanaStablecoinFxReview?.assets ?? []).slice(0, 10).map((row) => ({
            jahr: row.year,
            stable: row.stable_asset,
            quelle: row.price_source ?? "-",
            events: row.events_count,
            materiell: row.material_events_count,
            menge: row.stable_quantity,
            erloes_eur: formatCurrency(row.stable_disposal_proceeds_eur),
            gv_eur: formatCurrency(row.stable_gain_loss_eur),
            max_age: row.max_price_age_days,
            max_delta_pct: row.max_abs_price_delta_pct
          }))}
          compact
        />
        <TablePanel
          title="Materielle Solana-Stablecoin-FX-Zeilen"
          rows={(taxSolanaStablecoinFxReview?.rows ?? []).slice(0, 12).map((row) => ({
            zeit: row.event_time,
            asset: `${row.asset} ${row.quantity}`,
            stable: `${row.stable_asset} ${row.stable_quantity}`,
            preis_eur: formatCurrency(row.selected_price_eur),
            quelle: row.selected_price_source ?? "-",
            age: row.price_age_days ?? "-",
            delta_pct: row.price_delta_pct ?? "-",
            basis: row.fx_basis_status,
            gv_eur: formatCurrency(row.stable_gain_loss_eur),
            grund: row.review_reason,
            tx: row.tx_id
          }))}
          footer={taxSolanaStablecoinFxReview?.methodology ?? "Solana-Stablecoin-FX-Review wird geladen."}
          compact
        />
      </div>

      <div className="taxViewSwitch" role="tablist" aria-label="Steuerjahr Ansicht">
        <button
          type="button"
          className={taxViewMode === "guided" ? "active" : ""}
          onClick={() => onTaxViewModeChange("guided")}
        >
          Eingabehilfe
        </button>
        <button
          type="button"
          className={taxViewMode === "details" ? "active" : ""}
          onClick={() => onTaxViewModeChange("details")}
        >
          BMF & Nachweise
        </button>
        <button
          type="button"
          className={taxViewMode === "expert" ? "active" : ""}
          onClick={() => onTaxViewModeChange("expert")}
        >
          Expertenmodus
        </button>
      </div>

      {taxViewMode !== "guided" ? (
        <>
      <div className={`panel bmfReadinessPanel ${bmfTone(String(taxYearMethodology?.status ?? activeMethodologyStatus?.status ?? ""))}`}>
        <div className="panelToolbar">
          <strong>BMF-Check</strong>
          <span className={`statusPill ${bmfTone(String(taxYearMethodology?.status ?? activeMethodologyStatus?.status ?? ""))}`}>
            {String(taxYearMethodology?.label ?? activeMethodologyStatus?.label ?? "wird geladen")}
          </span>
        </div>
        <div className="portfolioSummaryStrip">
          <Metric title="BMF-ready" value={taxYearMethodology?.bmf_ready ? "ja" : "nein"} />
          <Metric title="Score" value={`${formatCurrency(taxYearMethodology?.traceability_score ?? activeMethodologyStatus?.traceability_score ?? 0)} %`} />
          <Metric title="Gaps" value={String(taxYearMethodology?.gaps?.length ?? activeMethodologyStatus?.gaps_count ?? 0)} />
          <Metric title="Blockierend" value={String(activeMethodologyStatus?.blocking_gaps_count ?? methodologyGaps.filter((gap) => gap.blocks_bmf_ready).length)} />
          <Metric title="Quellen" value={String(taxYearMethodology?.sources?.length ?? 0)} />
          <Metric title="Konten" value={String(taxYearMethodology?.accounts_count ?? 0)} />
        </div>
        <div className="statusRows">
          <StatusRow label="FIFO-Methode" value={String(taxYearMethodology?.policy?.fifo_scope ?? taxMethodologySummary?.policy?.fifo_scope ?? "-")} />
          <StatusRow label="Bewertung" value={String(taxYearMethodology?.policy?.valuation_policy ?? taxMethodologySummary?.policy?.valuation_policy ?? "-")} />
          <StatusRow label="Zeitzone" value={String(taxYearMethodology?.policy?.timezone_policy ?? taxMethodologySummary?.policy?.timezone_policy ?? "-")} />
          <StatusRow label="Methodik" value={taxYearMethodology?.methodology ?? taxMethodologySummary?.methodology ?? "-"} />
        </div>
        <TablePanel
          title="Naechste BMF-Aktionen"
          rows={activeBmfActionItems.map((item) => ({
            prioritaet: item.severity,
            bereich: item.category,
            punkt: item.title,
            anzahl: item.count,
            blockiert: item.blocks_bmf_ready ? "ja" : "nein",
            aktion: item.action,
            beleg: item.evidence_ref ?? "-"
          }))}
          footer={
            taxBmfActionPlan
              ? `${taxBmfActionPlan.blocking_items_count} blockierende Punkte ueber alle Jahre. ${taxBmfActionPlan.methodology}`
              : "BMF-Aktionsliste wird geladen."
          }
          compact
        />
        <TablePanel
          title="BMF-Pruefpunkte"
          rows={methodologyMetrics.map((metric) => ({
            pruefpunkt: metric.label,
            status: metric.status,
            wert: metric.value,
            ziel: metric.target,
            detail: metric.detail
          }))}
          compact
        />
        <TablePanel
          title="Offene BMF-Gaps"
          rows={methodologyGaps.map((gap) => ({
            code: gap.code,
            schwere: gap.severity,
            anzahl: gap.count,
            blockiert: gap.blocks_bmf_ready ? "ja" : "nein",
            meldung: gap.message,
            aktion: gap.action,
            beleg: gap.evidence_ref ?? "-"
          }))}
          footer="BMF-ready wird erst gruen, wenn Methodik, FIFO-Spur, Preise, Quellen und externe Zufluesse ohne blockierende Gaps sind."
          compact
        />
        <div className="reportActionBand compactActions">
          <button type="button" onClick={() => onDownload(`/api/v1/tax-years/${activeYearValue}/methodology`)}>
            <FileJson size={16} />
            Methodik JSON
          </button>
          <button type="button" onClick={() => onDownload(`/api/v1/tax-years/${activeYearValue}/compliance-status`)}>
            <FileJson size={16} />
            Status JSON
          </button>
          <button type="button" onClick={() => onDownload(`/api/v1/export/tax-years/${activeYearValue}/evidence-package.zip`)}>
            <PackageCheck size={16} />
            Jahrespaket
          </button>
        </div>
      </div>

      <div className={`panel walletFifoPanel ${walletFifoTone}`}>
        <div className="panelToolbar">
          <strong>FIFO-Nachweis und Transferkette</strong>
          <span className={`statusPill ${walletFifoTone}`}>
            {walletFifoProofLabel}
          </span>
        </div>
        <div className="fifoProofBand">
          <div className="fifoProofSummary">
            <span className="heroKicker">Nachweisstatus</span>
            <strong>{walletFifoOk ? "Stichtaggenau nachvollziehbar" : "Pruefung erforderlich"}</strong>
            <p>
              {walletFifoOk
                ? "Alle Wallet-/Depot-Abgaenge des Jahres haben in der Preview einen passenden Pool-Bestand oder einen belegten Transferanker."
                : unresolvedInboundProvenance > 0
                  ? "FIFO kann rechnerisch weiterlaufen, aber Zufluss-Herkunft ist noch nicht vollstaendig mit Transfer-, Deposit-, Withdrawal- oder Anfangsbestandsbelegen nachgewiesen."
                  : "Mindestens ein Abgang kann in der wallet-/depotbezogenen FIFO-Preview noch nicht vollstaendig aus Lots gedeckt werden."}
            </p>
          </div>
          <div className="fifoProofMetrics">
            <Metric title="Offene FIFO-Luecken" value={String(walletFifoUnmatched)} />
            <Metric title="Offene Herkunft" value={String(unresolvedInboundProvenance)} />
            <Metric title="Belegte Transfers" value={String(taxYearWalletFifoDelta?.transfer_traces_count ?? 0)} />
            <Metric title="Fee-Transfers" value={String(walletFifoFeeTransfers.length)} />
          </div>
        </div>
        {taxLegacyHeliumOverview ? (
          <div className="fifoProofBand legacyHeliumBand">
            <div className="fifoProofSummary">
              <span className="heroKicker">Legacy HNT</span>
              <strong>Helium Main / Fairspot / Solana-Migration</strong>
              <p>
                Main-Legacy und Fairspot bleiben als FIFO- und Belegkette sichtbar,
                erzeugen aber keinen aktuellen Portfolio-Wert.
              </p>
            </div>
            <div className="fifoProofMetrics">
              <Metric title="Legacy Events" value={String(taxLegacyHeliumOverview.total_canonical_events_count ?? 0)} />
              <Metric title="Netto HNT" value={formatQuantity(taxLegacyHeliumOverview.total_net_hnt_quantity)} />
              <Metric title="Fairspot Transfers" value={String(taxLegacyHeliumOverview.fairspot_transfers_count ?? 0)} />
              <Metric title="Portfolio-Wallets" value={String(taxLegacyHeliumOverview.included_in_portfolio_count ?? 0)} />
            </div>
            <TablePanel
              title="Legacy-HNT Wallet-/Gegenpartei-Uebersicht"
              rows={legacyHeliumWallets.map((wallet) => ({
                rolle: wallet.role,
                adresse: shortAccount(String(wallet.address ?? "")),
                portfolio: wallet.included_in_portfolio ? "ja" : "nein",
                events: wallet.canonical_events_count ?? 0,
                mining: wallet.mining_events_count ?? 0,
                transfers: wallet.transfer_events_count ?? 0,
                netto_hnt: formatQuantity(wallet.net_hnt_quantity),
                von: wallet.first_event_at ?? "-",
                bis: wallet.last_event_at ?? "-"
              }))}
              compact
            />
            <TablePanel
              title="Fairspot Transfer-Belege"
              rows={legacyHeliumTransfers.slice(0, 6).map((transfer) => ({
                zeit: transfer.event_time ?? "-",
                richtung: transfer.direction,
                hnt: formatQuantity(transfer.quantity),
                payer: shortAccount(String(transfer.payer ?? "")),
                payee: shortAccount(String(transfer.payee ?? "")),
                portfolio: transfer.included_in_portfolio ? "ja" : "nein",
                zeile: transfer.row_number ?? "-"
              }))}
              footer={taxLegacyHeliumOverview.methodology}
              compact
            />
            <div className="reportActionBand compactActions">
              <button type="button" onClick={() => onDownload("/api/v1/tax/legacy-helium-overview?limit=200")}>
                <FileJson size={16} />
                Legacy HNT JSON
              </button>
            </div>
          </div>
        ) : null}
        {taxYearWalletFifoProvenanceClosure ? (
          <div className={`panelInlineBlock ${walletFifoClosureTone}`}>
            <div className="panelToolbar">
              <strong>Wallet-FIFO Jahresampel</strong>
              <span className={`statusPill ${walletFifoClosureTone}`}>
                {Number(taxYearWalletFifoProvenanceClosure.review_required_count ?? 0) > 0 ? "Review offen" : "belegt"}
              </span>
            </div>
            <div className="portfolioSummaryStrip">
              <Metric title="Offene Herkunft" value={String(taxYearWalletFifoProvenanceClosure.unresolved_inbound_provenance_count ?? 0)} />
              <Metric title="Gruppen" value={String(taxYearWalletFifoProvenanceClosure.groups_count ?? 0)} />
              <Metric title="Anfangsbestand" value={String(taxYearWalletFifoProvenanceClosure.documented_non_live_count ?? 0)} />
              <Metric title="Extern/unklar" value={String(taxYearWalletFifoProvenanceClosure.external_or_unknown_count ?? 0)} />
              <Metric title="CEX ungeprueft" value={String(taxYearWalletFifoProvenanceClosure.unverified_cex_count ?? 0)} />
              <Metric title="Review" value={String(taxYearWalletFifoProvenanceClosure.review_required_count ?? 0)} />
            </div>
            <TablePanel
              title="Jahresabschluss offene FIFO-Herkunft"
              rows={walletFifoClosureItems.map((item) => ({
                status: item.closure_status ?? "-",
                kategorie: item.category ?? "-",
                asset: item.asset ?? "-",
                quelle: item.source ?? "-",
                pool: item.pool_id ? shortAccount(String(item.pool_id)) : "-",
                account: item.account ? shortAccount(String(item.account)) : "-",
                faelle: item.events_count ?? 0,
                menge: formatQuantity(item.quantity_total),
                basis_eur: formatCurrency(item.carried_cost_basis_eur_total),
                review: item.requires_review ? "ja" : "nein",
                belege: Array.isArray(item.evidence_refs) ? item.evidence_refs.length : 0,
                hinweis: item.tax_treatment_hint ?? "-",
                aktion: item.recommended_action ?? "-"
              }))}
              footer={taxYearWalletFifoProvenanceClosure.methodology}
              compact
            />
            <div className="reportActionBand compactActions">
              <button type="button" onClick={() => onDownload(`/api/v1/tax-years/${activeYearValue}/wallet-fifo-provenance-closure?limit=100`)}>
                <FileJson size={16} />
                Jahresampel JSON
              </button>
            </div>
          </div>
        ) : null}
        {(taxYearCexDepositTransferEvidence?.deposits ?? []).length > 0 ? (
          <TablePanel
            title="CEX Deposit Transfer Evidence"
            rows={(taxYearCexDepositTransferEvidence?.deposits ?? []).map((row) => ({
              status: row.evidence_status,
              steuer_label: row.tax_label,
              haltefrist: row.holding_period_continues ? "fortgefuehrt" : "pruefen",
              asset: row.asset,
              netzwerk: row.network ?? "-",
              menge_cex: formatQuantity(row.credited_quantity),
              menge_onchain: row.onchain_quantity ? formatQuantity(row.onchain_quantity) : "-",
              delta: row.quantity_delta ? formatQuantity(row.quantity_delta) : "-",
              onchain_zeit: row.onchain_time ? formatDateTime(row.onchain_time) : "-",
              gutschrift: row.cex_credit_time ? formatDateTime(row.cex_credit_time) : "-",
              txid: row.tx_id ? shortAccount(String(row.tx_id)) : "-",
              deposit_wallet: row.deposit_address ? shortAccount(String(row.deposit_address)) : "-",
              cex_hot_wallet: row.cex_main_wallet ? shortAccount(String(row.cex_main_wallet)) : "-",
              account: row.cex_account ?? "-",
              fifo: row.fifo_transfer_status,
              source_pool: row.fifo_source_pool_id ?? "-",
              target_pool: row.fifo_target_pool_id ?? "-",
              lots: row.fifo_lots_moved ?? 0,
              basis_eur: formatCurrency(row.carried_cost_basis_eur),
              fehlt: Array.isArray(row.missing_evidence) ? row.missing_evidence.join(", ") : "-",
              aktion: row.recommended_action
            }))}
            footer={`${taxYearCexDepositTransferEvidence?.deposits_count ?? 0} Deposits, steuerneutral fortgefuehrt: ${taxYearCexDepositTransferEvidence?.transfer_neutral_count ?? 0}, fehlende Belege: ${taxYearCexDepositTransferEvidence?.missing_evidence_count ?? 0}. ${taxYearCexDepositTransferEvidence?.methodology ?? ""}`}
            compact
          />
        ) : null}
        {(taxYearCexSenderOwnershipLatest?.decisions ?? []).length > 0 ? (
          <TablePanel
            title="CEX Sender Ownership Review"
            rows={(taxYearCexSenderOwnershipLatest?.decisions ?? []).map((row) => {
              const flags = (row.decision_layer ?? {}) as Record<string, unknown>;
              const enabledFlags = Object.entries(flags)
                .filter(([, value]) => Boolean(value))
                .map(([key]) => key)
                .join(", ");
              return {
                status: row.final_tax_status,
                provider: row.provider_status,
                asset: row.asset,
                menge: formatQuantity(row.amount),
                zeit: row.timestamp_utc ? formatDateTime(row.timestamp_utc) : "-",
                txid: row.txid ? shortAccount(String(row.txid)) : "-",
                txid_full: row.txid ?? "",
                sender: row.onchain_sender ? shortAccount(String(row.onchain_sender)) : "-",
                sender_label: row.onchain_sender_label ?? row.sender_classification ?? "-",
                signer: row.primary_signer ? shortAccount(String(row.primary_signer)) : "-",
                deposit_wallet: row.deposit_address ? shortAccount(String(row.deposit_address)) : "-",
                account: row.cex_account ?? "-",
                fifo: row.fifo_transfer_status ?? "-",
                basis_eur: formatCurrency(row.carried_cost_basis_eur),
                flags_ok: enabledFlags || "-",
                programme: Array.isArray(row.program_ids) ? row.program_ids.length : 0,
                hinweis: row.review_note
              };
            })}
            rowActions={[
              {
                label: "Steuerneutralen Transfer dokumentieren",
                icon: <Check size={15} />,
                onClick: (row) => onAddCexSenderOwnershipDecision(row, "tax_neutral_transfer_reviewed")
              },
              {
                label: "Bitget-/Exchange-Outflow-Beleg erforderlich",
                icon: <ClipboardCheck size={15} />,
                onClick: (row) => onAddCexSenderOwnershipDecision(row, "exchange_outflow_evidence_required")
              }
            ]}
            footer={`${taxYearCexSenderOwnershipLatest?.transactions_count ?? 0} TXs im letzten Artifact, Kandidaten fuer steuerneutralen Transfer: ${taxYearCexSenderOwnershipLatest?.tax_neutral_candidates ?? 0}, ungepruefte Dritt-Sender: ${taxYearCexSenderOwnershipLatest?.unverified_third_party ?? 0}. Artifact: ${taxYearCexSenderOwnershipLatest?.artifact_path ? shortAccount(String(taxYearCexSenderOwnershipLatest.artifact_path)) : "nicht vorhanden"}. ${taxYearCexSenderOwnershipLatest?.methodology ?? ""}`}
            compact
          />
        ) : null}
        {(taxYearCexExchangeOutflowEvidence?.rows ?? []).length > 0 ? (
          <TablePanel
            title="CEX Exchange Outflow Evidence"
            rows={(taxYearCexExchangeOutflowEvidence?.rows ?? []).map((row) => {
              const best = (row.best_candidate ?? {}) as Record<string, unknown>;
              return {
                status: row.status,
                asset: row.asset,
                menge: formatQuantity(row.amount),
                deposit_zeit: row.deposit_time ? formatDateTime(row.deposit_time) : "-",
                deposit_txid: row.deposit_txid ? shortAccount(String(row.deposit_txid)) : "-",
                sender_label: row.source_sender_label ?? "-",
                source_exchange: row.source_exchange,
                kandidaten: row.candidates_count ?? 0,
                best_zeit: best.event_time ? formatDateTime(best.event_time) : "-",
                best_menge: best.quantity ? formatQuantity(best.quantity) : "-",
                best_delta: best.amount_delta ? formatQuantity(best.amount_delta) : "-",
                best_txid: best.withdrawal_tx_id ? shortAccount(String(best.withdrawal_tx_id)) : "-",
                best_status: best.evidence_status ?? "-",
                aktion: row.recommended_action
              };
            })}
            footer={`${taxYearCexExchangeOutflowEvidence?.rows_count ?? 0} Exchange-Sender-Deposits, belegbereit: ${taxYearCexExchangeOutflowEvidence?.ready_count ?? 0}, fehlend/offen: ${taxYearCexExchangeOutflowEvidence?.missing_count ?? 0}, Suchfenster: ${taxYearCexExchangeOutflowEvidence?.window_hours ?? 72}h. ${taxYearCexExchangeOutflowEvidence?.methodology ?? ""}`}
            compact
          />
        ) : null}
        {cexOutflowAnchorItems.length > 0 ? (
          <div className={`panelInlineBlock ${cexOutflowAnchorTone}`}>
            <div className="panelToolbar">
              <strong>CEX-FIFO-Anker Bitget -&gt; Binance</strong>
              <span className={`statusPill ${cexOutflowAnchorTone}`}>
                {taxYearCexExchangeOutflowAnchorFeasibility?.anchor_missing_count === 0 ? "vollstaendig" : "pruefen"}
              </span>
            </div>
            <div className="portfolioSummaryStrip">
              <Metric title="Entscheidungen" value={String(taxYearCexExchangeOutflowAnchorFeasibility?.decisions_count ?? 0)} />
              <Metric title="Belege ready" value={String(taxYearCexExchangeOutflowAnchorFeasibility?.evidence_ready_count ?? 0)} />
              <Metric title="FIFO-Anker ready" value={String(taxYearCexExchangeOutflowAnchorFeasibility?.anchor_ready_count ?? 0)} />
              <Metric title="Offen" value={String(taxYearCexExchangeOutflowAnchorFeasibility?.anchor_missing_count ?? 0)} />
            </div>
            <TablePanel
              title="CEX-FIFO-Anker je Deposit"
              rows={cexOutflowAnchorItems.map((item) => ({
                status: item.anchor_status,
                anchor: item.anchor_ready ? "ja" : "nein",
                asset: item.asset,
                menge: formatQuantity(item.amount),
                deposit_zeit: item.deposit_time ? formatDateTime(item.deposit_time) : "-",
                deposit_txid: item.deposit_txid ? shortAccount(String(item.deposit_txid)) : "-",
                exchange_outflow: item.exchange_outflow_tx_id ? shortAccount(String(item.exchange_outflow_tx_id)) : "-",
                fee: item.exchange_outflow_fee ? formatQuantity(item.exchange_outflow_fee) : "-",
                source_pool: item.fifo_source_pool_id ?? "-",
                target_pool: item.fifo_target_pool_id ?? "-",
                fehlt: Array.isArray(item.missing_requirements) ? item.missing_requirements.join(", ") : "-",
                aktion: item.recommended_action
              }))}
              footer={taxYearCexExchangeOutflowAnchorFeasibility?.methodology ?? "Read-only CEX-FIFO-Ankerstatus."}
              compact
            />
            <div className="reportActionBand compactActions">
              <button type="button" onClick={() => onDownload(`/api/v1/tax-years/${activeYearValue}/cex-exchange-outflow-anchor-feasibility?source_exchange=bitget&target_cex=binance&network=SOL`)}>
                <FileJson size={16} />
                Ankerstatus JSON
              </button>
              <button type="button" onClick={() => onDownload(`/api/v1/export/tax-years/${activeYearValue}/evidence-package.zip`)}>
                <PackageCheck size={16} />
                Jahrespaket
              </button>
            </div>
          </div>
        ) : null}
        {walletFifoProvenanceGroups.length > 0 ? (
          <TablePanel
            title="Offene Zufluss-Herkunft: Prioritaeten"
            rows={walletFifoProvenanceGroups.map((group) => {
              const best = (group.best_outflow_candidate ?? {}) as Record<string, unknown>;
              return {
                asset: group.asset,
                pool: group.pool_id,
                quelle: group.source,
                account: group.account ? shortAccount(String(group.account)) : "-",
                faelle: group.events_count,
                menge: formatQuantity(group.quantity_total),
                basis_eur: formatCurrency(group.carried_cost_basis_eur_total),
                abgang_kandidaten: group.local_outflow_candidate_count ?? 0,
                exchange_abgang: group.exchange_outflow_candidate_count ?? 0,
                exchange_intern: group.exchange_internal_context_count ?? 0,
                withdrawal_ready: group.withdrawal_evidence_ready_count ?? 0,
                status_mix: formatStatusCounts(group.event_status_counts),
                bester_abgang: best.tx_id ? shortAccount(String(best.tx_id)) : "-",
                withdrawal_tx: best.withdrawal_tx_id ? shortAccount(String(best.withdrawal_tx_id)) : "-",
                zieladresse: best.withdrawal_address ? shortAccount(String(best.withdrawal_address)) : "-",
                raw: group.raw_evidence_count,
                deposit: group.deposit_evidence_count,
                txid: group.onchain_tx_id_count,
                status: group.evidence_status,
                von: group.first_event_at ? formatDateTime(group.first_event_at) : "-",
                bis: group.last_event_at ? formatDateTime(group.last_event_at) : "-",
                details: `/api/v1/tax-years/${activeYearValue}/wallet-fifo-provenance-events?asset=${encodeURIComponent(String(group.asset ?? ""))}&pool_id=${encodeURIComponent(String(group.pool_id ?? ""))}`,
                naechster_schritt: group.recommended_action
              };
            })}
            footer={taxYearWalletFifoProvenancePriorities?.methodology ?? "Offene provisorische Inbound-Lots werden gruppiert."}
            compact
          />
        ) : null}
        {(taxYearWalletFifoProvenancePriorities?.status_breakdown ?? []).length > 0 ? (
          <TablePanel
            title="Offene Zufluss-Herkunft: Status-Aufteilung"
            rows={(taxYearWalletFifoProvenancePriorities?.status_breakdown ?? []).map((row) => {
              const best = (row.best_outflow_candidate ?? {}) as Record<string, unknown>;
              return {
                status: row.evidence_status,
                faelle: row.events_count,
                menge: formatQuantity(row.quantity_total),
                basis_eur: formatCurrency(row.carried_cost_basis_eur_total),
                lokale_abgaenge: row.local_outflow_candidate_count ?? 0,
                exchange_abgang: row.exchange_outflow_candidate_count ?? 0,
                exchange_intern: row.exchange_internal_context_count ?? 0,
                withdrawal_ready: row.withdrawal_evidence_ready_count ?? 0,
                bester_status: best.exchange_evidence_status ?? best.withdrawal_evidence_status ?? "-",
                tx: best.withdrawal_tx_id ? shortAccount(String(best.withdrawal_tx_id)) : best.tx_id ? shortAccount(String(best.tx_id)) : "-",
                von: row.first_event_at ? formatDateTime(row.first_event_at) : "-",
                bis: row.last_event_at ? formatDateTime(row.last_event_at) : "-",
                naechster_schritt: row.recommended_action
              };
            })}
            compact
          />
        ) : null}
        {(taxYearWalletFifoRawProvenanceBreakdown?.groups ?? []).length > 0 ? (
          <TablePanel
            title="Raw-Provenance Breakdown"
            rows={(taxYearWalletFifoRawProvenanceBreakdown?.groups ?? []).map((group) => {
              const sampleTxIds = Array.isArray(group.sample_tx_ids) ? group.sample_tx_ids : [];
              const sampleEventIds = Array.isArray(group.sample_event_ids) ? group.sample_event_ids : [];
              return {
                status: group.evidence_status,
                muster: group.raw_pattern,
                asset: group.asset,
                pool: group.pool_id,
                quelle: group.source,
                account: group.account ? shortAccount(String(group.account)) : "-",
                raw_quelle: group.raw_source ?? "-",
                raw_datei: group.raw_filename ? shortAccount(String(group.raw_filename)) : "-",
                faelle: group.events_count,
                txids: group.tx_id_count,
                tiny: group.tiny_quantity_count,
                menge: formatQuantity(group.quantity_total),
                basis_eur: formatCurrency(group.carried_cost_basis_eur_total),
                von: group.first_event_at ? formatDateTime(group.first_event_at) : "-",
                bis: group.last_event_at ? formatDateTime(group.last_event_at) : "-",
                sample_tx: sampleTxIds.length > 0 ? sampleTxIds.slice(0, 2).map((tx) => shortAccount(String(tx))).join(", ") : "-",
                sample_event: sampleEventIds.length > 0 ? sampleEventIds.slice(0, 2).map((id) => shortAccount(String(id))).join(", ") : "-",
                naechster_schritt: group.recommended_action
              };
            })}
            footer={`${taxYearWalletFifoRawProvenanceBreakdown?.raw_transaction_evidence_only_count ?? 0} Raw-only und ${taxYearWalletFifoRawProvenanceBreakdown?.solana_tiny_raw_credit_count ?? 0} SOL-Dust/Rent-Events in ${taxYearWalletFifoRawProvenanceBreakdown?.groups_count ?? 0} Gruppen. ${taxYearWalletFifoRawProvenanceBreakdown?.methodology ?? ""}`}
            compact
          />
        ) : null}
        {(taxYearWalletFifoExchangeEvidenceGaps?.gaps ?? []).length > 0 ? (
          <TablePanel
            title="Exchange Evidence Gaps"
            rows={(taxYearWalletFifoExchangeEvidenceGaps?.gaps ?? []).map((gap) => {
              const outflow = (gap.outflow_candidate ?? {}) as Record<string, unknown>;
              const inboundRaw = (gap.inbound_raw_evidence ?? {}) as Record<string, unknown>;
              const outflowRaw = (gap.outflow_raw_evidence ?? {}) as Record<string, unknown>;
              const missing = Array.isArray(gap.missing_fields) ? gap.missing_fields.join(", ") : "-";
              return {
                asset: gap.asset,
                pool: gap.pool_id,
                quelle: outflow.source ?? "-",
                inbound: gap.inbound_tx_id ? shortAccount(String(gap.inbound_tx_id)) : shortAccount(String(gap.inbound_event_id ?? "")),
                betrag_in: formatQuantity(gap.inbound_quantity),
                outflow_tx: outflow.tx_id ? shortAccount(String(outflow.tx_id)) : "-",
                betrag_out: outflow.quantity ? formatQuantity(outflow.quantity) : "-",
                delta: outflow.amount_delta ? formatQuantity(outflow.amount_delta) : "-",
                fehlend: missing,
                erwartet: gap.expected_evidence_source,
                inbound_raw: inboundRaw.filename ? `${String(inboundRaw.filename)}:${String(inboundRaw.row_number ?? "-")}` : "-",
                outflow_raw: outflowRaw.filename ? `${String(outflowRaw.filename)}:${String(outflowRaw.row_number ?? "-")}` : "-",
                naechster_schritt: gap.recommended_action
              };
            })}
            footer={`${taxYearWalletFifoExchangeEvidenceGaps?.gaps_count ?? 0} harte Exchange-Evidence-Gaps. ${taxYearWalletFifoExchangeEvidenceGaps?.methodology ?? ""}`}
            compact
          />
        ) : null}
        {taxYearWalletFifoSolanaProvenanceBatchLatest ? (
          <div className="panel">
            <div className="panelHeader">
              <div>
                <span className="heroKicker">Solana Provenance Batch</span>
                <h3>TXID-Abgleich 2024 SOL</h3>
              </div>
              <span className={`statusPill ${taxYearWalletFifoSolanaProvenanceBatchLatest.failed_count > 0 ? "warning" : taxYearWalletFifoSolanaProvenanceBatchLatest.remaining_count > 0 ? "warning" : "ok"}`}>
                {taxYearWalletFifoSolanaProvenanceBatchLatest.exists ? `${taxYearWalletFifoSolanaProvenanceBatchLatest.progress_percent}%` : "kein Artefakt"}
              </span>
            </div>
            <div className="metricGrid compact">
              <Metric title="Klassifiziert" value={`${taxYearWalletFifoSolanaProvenanceBatchLatest.classified_count}/${taxYearWalletFifoSolanaProvenanceBatchLatest.total_events}`} />
              <Metric title="Offen" value={String(taxYearWalletFifoSolanaProvenanceBatchLatest.remaining_count)} />
              <Metric title="Eigene Kandidaten" value={String(taxYearWalletFifoSolanaProvenanceBatchLatest.own_transfer_candidates_count)} />
              <Metric title="Extern/unklar" value={String(taxYearWalletFifoSolanaProvenanceBatchLatest.external_or_unknown_count)} />
              <Metric title="Fehler" value={String(taxYearWalletFifoSolanaProvenanceBatchLatest.failed_count)} />
              <Metric title="Stand" value={taxYearWalletFifoSolanaProvenanceBatchLatest.generated_at ? formatDateTime(taxYearWalletFifoSolanaProvenanceBatchLatest.generated_at) : "-"} />
            </div>
            <p className="panelNote">
              {taxYearWalletFifoSolanaProvenanceBatchLatest.exists
                ? `Run ${taxYearWalletFifoSolanaProvenanceBatchLatest.run_id ?? "-"} aus ${shortAccount(taxYearWalletFifoSolanaProvenanceBatchLatest.artifact_path)}. ${taxYearWalletFifoSolanaProvenanceBatchLatest.methodology}`
                : taxYearWalletFifoSolanaProvenanceBatchLatest.methodology}
            </p>
          </div>
        ) : null}
        {(taxYearWalletFifoSolanaRawBmfEvidenceSummary?.groups ?? []).length > 0 ? (
          <TablePanel
            title="Solana BMF-Beleguebersicht"
            rows={(taxYearWalletFifoSolanaRawBmfEvidenceSummary?.groups ?? []).map((group) => {
              const programs = Array.isArray(group.primary_programs) ? group.primary_programs : [];
              const senders = Array.isArray(group.sample_senders) ? group.sample_senders : [];
              const signatures = Array.isArray(group.sample_signatures) ? group.sample_signatures : [];
              return {
                prioritaet: group.bmf_evidence_priority ?? "-",
                route: group.route_classification ?? "-",
                faelle: group.events_count,
                sender: group.senders_count,
                raw: group.raw_transaction_evidence_only_count,
                tiny: group.solana_tiny_raw_credit_count,
                menge: formatQuantity(group.quantity_total),
                basis_eur: formatCurrency(group.carried_cost_basis_eur_total),
                wallet_signer: group.wallet_signed_events_count ?? 0,
                programme: programs.length > 0 ? programs.slice(0, 3).map((program) => shortAccount(String(program))).join(", ") : "-",
                beispiel_sender: senders.length > 0 ? senders.slice(0, 3).map((sender) => shortAccount(String(sender))).join(", ") : "-",
                beispiel_tx: signatures.length > 0 ? signatures.slice(0, 2).map((signature) => shortAccount(String(signature))).join(", ") : "-",
                checklist: Array.isArray(group.evidence_checklist) ? group.evidence_checklist.join(" | ") : "-",
                naechster_schritt: group.recommended_action
              };
            })}
            footer={`${taxYearWalletFifoSolanaRawBmfEvidenceSummary?.groups_count ?? 0} Gruppen, hohe Prioritaet: ${taxYearWalletFifoSolanaRawBmfEvidenceSummary?.high_priority_events_count ?? 0} Events / ${formatCurrency(taxYearWalletFifoSolanaRawBmfEvidenceSummary?.high_priority_cost_basis_eur)} EUR. ${taxYearWalletFifoSolanaRawBmfEvidenceSummary?.methodology ?? ""}`}
            compact
          />
        ) : null}
        {(taxYearWalletFifoSolanaRawBmfEvidenceDrilldown?.signer_groups ?? []).length > 0 ? (
          <TablePanel
            title="Solana BMF-Drilldown Signergruppen"
            rows={(taxYearWalletFifoSolanaRawBmfEvidenceDrilldown?.signer_groups ?? []).map((group) => {
              const senders = Array.isArray(group.sample_senders) ? group.sample_senders : [];
              const signatures = Array.isArray(group.sample_signatures) ? group.sample_signatures : [];
              return {
                signer: group.primary_signer ? shortAccount(String(group.primary_signer)) : "-",
                programm: group.primary_program ? shortAccount(String(group.primary_program)) : "-",
                route: group.route_classification ?? "-",
                prioritaet: group.bmf_evidence_priority ?? "-",
                faelle: group.events_count,
                menge: formatQuantity(group.quantity_total),
                basis_eur: formatCurrency(group.carried_cost_basis_eur_total),
                von: group.first_event_at ? formatDateTime(group.first_event_at) : "-",
                bis: group.last_event_at ? formatDateTime(group.last_event_at) : "-",
                beispiel_sender: senders.length > 0 ? senders.slice(0, 3).map((sender) => shortAccount(String(sender))).join(", ") : "-",
                beispiel_tx: signatures.length > 0 ? signatures.slice(0, 2).map((signature) => shortAccount(String(signature))).join(", ") : "-",
                vorschlag: group.decision_suggestion ?? "-",
                checklist: Array.isArray(group.evidence_checklist) ? group.evidence_checklist.join(" | ") : "-"
              };
            })}
            footer={`${taxYearWalletFifoSolanaRawBmfEvidenceDrilldown?.groups_count ?? 0} Signergruppen, ${taxYearWalletFifoSolanaRawBmfEvidenceDrilldown?.events_count ?? 0} Events, Summe ${formatQuantity(taxYearWalletFifoSolanaRawBmfEvidenceDrilldown?.total_quantity)} SOL / ${formatCurrency(taxYearWalletFifoSolanaRawBmfEvidenceDrilldown?.total_cost_basis_eur)} EUR. ${taxYearWalletFifoSolanaRawBmfEvidenceDrilldown?.methodology ?? ""}`}
            compact
          />
        ) : null}
        {(taxYearWalletFifoSolanaRawBmfEvidenceDrilldown?.events ?? []).length > 0 ? (
          <TablePanel
            title="Solana BMF-Drilldown Einzelereignisse"
            rows={(taxYearWalletFifoSolanaRawBmfEvidenceDrilldown?.events ?? []).map((event) => {
              const signers = Array.isArray(event.signers) ? event.signers : [];
              const programs = Array.isArray(event.program_ids) ? event.program_ids : [];
              return {
                zeit: event.event_time ? formatDateTime(event.event_time) : "-",
                menge: formatQuantity(event.quantity),
                basis_eur: formatCurrency(event.carried_cost_basis_eur),
                tx: event.signature ? shortAccount(String(event.signature)) : "-",
                sender: event.sender_owner ? shortAccount(String(event.sender_owner)) : "-",
                empfaenger: event.receiver_owner ? shortAccount(String(event.receiver_owner)) : "-",
                signer: event.primary_signer ? shortAccount(String(event.primary_signer)) : (signers.length > 0 ? shortAccount(String(signers[0])) : "-"),
                programm: event.primary_program ? shortAccount(String(event.primary_program)) : (programs.length > 0 ? shortAccount(String(programs[0])) : "-"),
                wallet_signer: event.wallet_is_signer === true ? "ja" : "nein",
                vorschlag: event.decision_suggestion ?? "-",
                begruendung: event.decision_reason ?? "-",
                belegbedarf: event.evidence_needed ?? "-"
              };
            })}
            footer="Einzelereignisse sind read-only Vorschlaege fuer Beleg-/Review-Arbeit; keine automatische steuerliche Umklassifizierung."
            compact
          />
        ) : null}
        {(taxYearWalletFifoSolanaRawProvenanceSenders?.senders ?? []).length > 0 ? (
          <TablePanel
            title="Solana Raw-Provenance Sender"
            rows={(taxYearWalletFifoSolanaRawProvenanceSenders?.senders ?? []).map((row) => {
              const samples = Array.isArray(row.sample_signatures) ? row.sample_signatures : [];
              const sampleSigners = Array.isArray(row.sample_signers) ? row.sample_signers : [];
              const samplePrograms = Array.isArray(row.sample_program_ids) ? row.sample_program_ids : [];
              return {
                sender: row.sender_owner ? shortAccount(String(row.sender_owner)) : "-",
                empfaenger: row.receiver_owner ? shortAccount(String(row.receiver_owner)) : "-",
                status: row.classification_status ?? "-",
                hinweis: row.origin_hint ?? "-",
                route: row.route_classification ?? "-",
                prioritaet: row.bmf_evidence_priority ?? "-",
                wallet_signer: row.wallet_signed_events_count ?? 0,
                signer: sampleSigners.length > 0 ? sampleSigners.slice(0, 2).map((signer) => shortAccount(String(signer))).join(", ") : "-",
                programm: row.primary_program ? shortAccount(String(row.primary_program)) : (samplePrograms.length > 0 ? shortAccount(String(samplePrograms[0])) : "-"),
                faelle: row.events_count,
                raw: row.raw_transaction_evidence_only_count,
                tiny: row.solana_tiny_raw_credit_count,
                menge: formatQuantity(row.quantity_total),
                basis_eur: formatCurrency(row.carried_cost_basis_eur_total),
                von: row.first_event_at ? formatDateTime(row.first_event_at) : "-",
                bis: row.last_event_at ? formatDateTime(row.last_event_at) : "-",
                top_tx: row.top_signature ? shortAccount(String(row.top_signature)) : "-",
                top_eur: row.top_cost_basis_eur ? formatCurrency(row.top_cost_basis_eur) : "-",
                samples: samples.length > 0 ? samples.slice(0, 2).map((signature) => shortAccount(String(signature))).join(", ") : "-",
                belegbedarf: row.evidence_needed ?? "-",
                checklist: Array.isArray(row.evidence_checklist) ? row.evidence_checklist.join(" | ") : "-",
                naechster_schritt: row.recommended_action
              };
            })}
            footer={`${taxYearWalletFifoSolanaRawProvenanceSenders?.senders_count ?? 0} Sender, ${taxYearWalletFifoSolanaRawProvenanceSenders?.raw_transaction_evidence_only_count ?? 0} Raw-only und ${taxYearWalletFifoSolanaRawProvenanceSenders?.solana_tiny_raw_credit_count ?? 0} Tiny-SOL Events. ${taxYearWalletFifoSolanaRawProvenanceSenders?.methodology ?? ""}`}
            compact
          />
        ) : null}
        {(taxYearWalletFifoSolanaRawProvenancePriorities?.priorities ?? []).length > 0 ? (
          <TablePanel
            title="Solana Raw-Provenance Prioritaeten"
            rows={(taxYearWalletFifoSolanaRawProvenancePriorities?.priorities ?? []).map((row) => {
              const signers = Array.isArray(row.signers) ? row.signers : [];
              const programs = Array.isArray(row.program_ids) ? row.program_ids : [];
              return {
                status: row.evidence_status,
                batch_status: row.classification_status ?? "-",
                zeit: row.event_time ? formatDateTime(row.event_time) : "-",
                menge: formatQuantity(row.quantity),
                basis_eur: formatCurrency(row.carried_cost_basis_eur),
                tx: row.signature ? shortAccount(String(row.signature)) : "-",
                sender: row.sender_owner ? shortAccount(String(row.sender_owner)) : "-",
                empfaenger: row.receiver_owner ? shortAccount(String(row.receiver_owner)) : "-",
                wallet_signer: row.wallet_is_signer === true ? "ja" : "nein",
                signer: signers.length > 0 ? signers.slice(0, 2).map((signer) => shortAccount(String(signer))).join(", ") : "-",
                programm: row.primary_program ? shortAccount(String(row.primary_program)) : (programs.length > 0 ? shortAccount(String(programs[0])) : "-"),
                route: row.route_classification ?? "-",
                prioritaet: row.bmf_evidence_priority ?? "-",
                hinweis: row.origin_hint ?? "-",
                matched: row.matched_amount ? formatQuantity(row.matched_amount) : "-",
                wallet_delta: row.wallet_delta_quantity ? formatQuantity(row.wallet_delta_quantity) : "-",
                quelle: row.evidence_source ?? "-",
                belegbedarf: row.evidence_needed ?? "-",
                checklist: Array.isArray(row.evidence_checklist) ? row.evidence_checklist.join(" | ") : "-",
                naechster_schritt: row.recommended_action
              };
            })}
            footer={`${taxYearWalletFifoSolanaRawProvenancePriorities?.raw_transaction_evidence_only_count ?? 0} Raw-only und ${taxYearWalletFifoSolanaRawProvenancePriorities?.solana_tiny_raw_credit_count ?? 0} Tiny-SOL Events, Summe ${formatQuantity(taxYearWalletFifoSolanaRawProvenancePriorities?.total_quantity)} SOL / ${formatCurrency(taxYearWalletFifoSolanaRawProvenancePriorities?.total_cost_basis_eur)} EUR. ${taxYearWalletFifoSolanaRawProvenancePriorities?.methodology ?? ""}`}
            compact
          />
        ) : null}
        {(taxYearWalletFifoSolanaSenderClusters?.clusters ?? []).length > 0 ? (
          <TablePanel
            title="Solana Sender-Cluster"
            rows={(taxYearWalletFifoSolanaSenderClusters?.clusters ?? []).map((cluster) => ({
              status: cluster.status,
              sender: cluster.sender_owner ? shortAccount(String(cluster.sender_owner)) : "-",
              empfaenger: cluster.receiver_owner ? shortAccount(String(cluster.receiver_owner)) : "-",
              faelle: cluster.events_count,
              summe_erwartet: formatQuantity(cluster.expected_amount_total),
              summe_erkannt: formatQuantity(cluster.matched_amount_total),
              von: cluster.first_block_time ? formatDateTime(cluster.first_block_time) : "-",
              bis: cluster.last_block_time ? formatDateTime(cluster.last_block_time) : "-",
              sender_eigen: cluster.own_wallet_sender ? "ja" : "nein",
              empfaenger_eigen: cluster.own_wallet_receiver ? "ja" : "nein",
              raw_sender: cluster.local_raw_sender_hits ?? 0,
              txid_belege: cluster.local_signature_evidence_count ?? 0,
              canonical_tx: cluster.local_canonical_signature_count ?? 0,
              naechster_schritt: cluster.recommended_action
            }))}
            footer={`${taxYearWalletFifoSolanaSenderClusters?.clusters_count ?? 0} Sender-Cluster, ${taxYearWalletFifoSolanaSenderClusters?.own_transfer_candidate_events ?? 0} eigene Transferkandidaten, ${taxYearWalletFifoSolanaSenderClusters?.external_or_unknown_events ?? 0} externe/unklare Events, ${taxYearWalletFifoSolanaSenderClusters?.failed_events ?? 0} Fehler. ${taxYearWalletFifoSolanaSenderClusters?.methodology ?? ""}`}
            compact
          />
        ) : null}
        {(taxYearWalletFifoSolanaSenderClusterOutflows?.samples ?? []).length > 0 ? (
          <TablePanel
            title="Solana nahe lokale Abgaenge"
            rows={(taxYearWalletFifoSolanaSenderClusterOutflows?.samples ?? []).map((sample) => {
              const candidates = Array.isArray(sample.candidates) ? sample.candidates as Array<Record<string, unknown>> : [];
              const best = candidates[0] ?? {};
              const seconds = Number(best.seconds_delta ?? 0);
              return {
                inbound: sample.inbound_signature ? shortAccount(String(sample.inbound_signature)) : "-",
                sender: sample.inbound_sender_owner ? shortAccount(String(sample.inbound_sender_owner)) : "-",
                betrag_in: formatQuantity(sample.inbound_amount),
                kandidaten: candidates.length,
                bester_abgang: best.tx_id ? shortAccount(String(best.tx_id)) : "-",
                kategorie: best.evidence_category ?? "-",
                exchange_status: best.exchange_evidence_status ?? "-",
                withdrawal_status: best.withdrawal_evidence_status ?? "-",
                zieladresse: best.withdrawal_address ? shortAccount(String(best.withdrawal_address)) : "-",
                withdrawal_tx: best.withdrawal_tx_id ? shortAccount(String(best.withdrawal_tx_id)) : "-",
                fee: best.withdrawal_fee ? formatQuantity(best.withdrawal_fee) : "-",
                quelle: best.source ?? "-",
                raw: best.raw_filename ? `${String(best.raw_filename)}:${String(best.raw_row_number ?? "-")}` : "-",
                typ: best.event_type ?? "-",
                betrag_out: best.quantity ? formatQuantity(best.quantity) : "-",
                zeit_delta_h: seconds ? (seconds / 3600).toFixed(1) : "0.0",
                mengen_delta: best.amount_delta ? formatQuantity(best.amount_delta) : "-",
                hinweis: best.recommended_action ?? "Review-Evidence, kein automatischer Transferanker"
              };
            })}
            footer={`${taxYearWalletFifoSolanaSenderClusterOutflows?.events_with_candidates_count ?? 0}/${taxYearWalletFifoSolanaSenderClusterOutflows?.checked_events_count ?? 0} gepruefte Inbounds mit lokalen Abgangskandidaten, ${taxYearWalletFifoSolanaSenderClusterOutflows?.candidates_count ?? 0} Kandidaten. Fenster ${taxYearWalletFifoSolanaSenderClusterOutflows?.window_hours ?? 48}h, Toleranz ${taxYearWalletFifoSolanaSenderClusterOutflows?.amount_tolerance_percent ?? "1"}%. ${taxYearWalletFifoSolanaSenderClusterOutflows?.methodology ?? ""}`}
            compact
          />
        ) : null}
        <div className="reportActionBand compactActions">
          <button type="button" onClick={() => onDownload(`/api/v1/tax-years/${activeYearValue}/wallet-fifo-provenance-closure?limit=100`)}>
            <FileJson size={16} />
            Jahresampel JSON
          </button>
          <button type="button" onClick={() => onDownload(`/api/v1/tax-years/${activeYearValue}/wallet-fifo-provenance-priorities?limit=100`)}>
            <FileJson size={16} />
            Provenance-Prioritaeten JSON
          </button>
          <button type="button" onClick={() => onDownload(`/api/v1/tax-years/${activeYearValue}/wallet-fifo-provenance-events?limit=200`)}>
            <FileJson size={16} />
            Provenance-Events JSON
          </button>
          <button type="button" onClick={() => onDownload(`/api/v1/tax-years/${activeYearValue}/wallet-fifo-solana-provenance-classification?asset=SOL&pool_id=solana_rpc%3AG39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY&limit=10&provider=rpc_public`)}>
            <FileJson size={16} />
            SOL-Klassifizierung JSON
          </button>
          <button type="button" onClick={() => onDownload(`/api/v1/tax-years/${activeYearValue}/wallet-fifo-solana-provenance-batch-latest?asset=SOL`)}>
            <FileJson size={16} />
            Batch-Status JSON
          </button>
          <button type="button" onClick={() => onDownload(`/api/v1/tax-years/${activeYearValue}/wallet-fifo-solana-sender-clusters?asset=SOL&limit=100`)}>
            <FileJson size={16} />
            Sender-Cluster JSON
          </button>
          <button type="button" onClick={() => onDownload(`/api/v1/tax-years/${activeYearValue}/wallet-fifo-solana-sender-cluster-outflows?asset=SOL&limit=100&window_hours=48&amount_tolerance_percent=1`)}>
            <FileJson size={16} />
            Outflow-Kandidaten JSON
          </button>
        </div>
        {(taxYearWalletFifoSolanaProvenanceClassification?.classifications ?? []).length > 0 ? (
          <TablePanel
            title="Solana Provenance Klassifizierung"
            rows={(taxYearWalletFifoSolanaProvenanceClassification?.classifications ?? []).map((row) => ({
              status: row.status,
              asset: row.asset,
              erwartet: formatQuantity(row.expected_amount),
              erkannt: row.matched_amount ? formatQuantity(row.matched_amount) : "-",
              wallet_delta: row.wallet_delta_quantity ? formatQuantity(row.wallet_delta_quantity) : "-",
              sender: row.sender_owner ? shortAccount(String(row.sender_owner)) : "-",
              sender_eigen: row.sender_is_known_own_wallet ? "ja" : "nein",
              empfaenger: row.receiver_owner ? shortAccount(String(row.receiver_owner)) : "-",
              empfaenger_eigen: row.receiver_is_known_own_wallet ? "ja" : "nein",
              txid: row.signature ? shortAccount(String(row.signature)) : "-",
              blockzeit: row.block_time ? formatDateTime(row.block_time) : "-",
              aktion: row.recommended_action,
              grund: row.reason ?? "-"
            }))}
            footer={`${taxYearWalletFifoSolanaProvenanceClassification?.own_transfer_candidates_count ?? 0} eigene Transferkandidaten, ${taxYearWalletFifoSolanaProvenanceClassification?.external_or_unknown_count ?? 0} externe/unklare, ${taxYearWalletFifoSolanaProvenanceClassification?.failed_count ?? 0} fehlgeschlagen. ${taxYearWalletFifoSolanaProvenanceClassification?.methodology ?? ""}`}
            compact
          />
        ) : null}
        {walletFifoTransfers.length > 0 ? (
          <div className="fifoTraceCards">
            {walletFifoTransfers.slice(0, 6).map((trace, index) => {
              const txId = String(trace.tx_id ?? "");
              const sourcePool = String(trace.source_pool_id ?? "-");
              const targetPool = String(trace.target_pool_id ?? "-");
              return (
                <div className="fifoTraceCard" key={`${txId}-${index}`}>
                  <div className="fifoTraceHeader">
                    <GitBranch size={16} />
                    <strong>{String(trace.asset ?? "-")}</strong>
                    <span className={`statusPill ${String(trace.status ?? "") === "ok" ? "ok" : "warning"}`}>
                      {String(trace.status ?? "-")}
                    </span>
                  </div>
                  <div className="fifoTraceRoute">
                    <span title={sourcePool}>{shortAccount(sourcePool)}</span>
                    <span>-&gt;</span>
                    <span title={targetPool}>{shortAccount(targetPool)}</span>
                  </div>
                  <div className="fifoTraceAmounts">
                    <span>{formatQuantity(trace.quantity)} {String(trace.asset ?? "")}</span>
                    {Number(trace.fee_quantity ?? 0) > 0 ? (
                      <span>{formatQuantity(trace.fee_quantity)} {String(trace.asset ?? "")} Fee</span>
                    ) : null}
                  </div>
                  <div className="fifoTraceMeta">
                    <span>{formatDateTime(trace.event_time)}</span>
                    <span title={txId}>{shortAccount(txId)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        ) : null}
        <div className="portfolioSummaryStrip">
          <Metric title="Global FIFO G/V" value={`${formatCurrency(taxYearWalletFifoDelta?.global_gain_loss_eur)} EUR`} />
          <Metric title="Wallet FIFO G/V" value={`${formatCurrency(taxYearWalletFifoDelta?.wallet_gain_loss_eur)} EUR`} />
          <Metric title="Delta" value={`${formatCurrency(taxYearWalletFifoDelta?.delta_gain_loss_eur)} EUR`} />
          <Metric title="Pools" value={String(taxYearWalletFifoDelta?.pools_count ?? 0)} />
          <Metric title="Transfers" value={String(taxYearWalletFifoDelta?.transfer_traces_count ?? 0)} />
          <Metric title="Unmatched" value={String(taxYearWalletFifoDelta?.unmatched_count ?? 0)} />
          <Metric title="Offene Herkunft" value={String(unresolvedInboundProvenance)} />
        </div>
        <TablePanel
          title="Delta je Asset"
          rows={(taxYearWalletFifoDelta?.year_deltas ?? []).map((row) => ({
            jahr: row.year,
            asset: row.asset,
            global_fifo_eur: formatCurrency(row.global_gain_loss_eur),
            wallet_fifo_eur: formatCurrency(row.wallet_gain_loss_eur),
            delta_eur: formatCurrency(row.delta_eur),
            global_lines: row.global_tax_lines_count,
            wallet_lines: row.wallet_tax_lines_count
          }))}
          compact
        />
        <TablePanel
          title="Transfer-Lot-Fortschreibung"
          rows={walletFifoTransfers.slice(0, 80).map((row) => ({
            zeit: row.event_time,
            asset: row.asset,
            menge: row.quantity,
            fee: Number(row.fee_quantity ?? 0) > 0 ? row.fee_quantity : "-",
            von: row.source_pool_id,
            nach: row.target_pool_id,
            lots: row.lots_moved,
            basis_eur: formatCurrency(row.carried_cost_basis_eur),
            status: row.status,
            tx: row.tx_id
          }))}
          compact
        />
        {(taxYearWalletFifoDelta?.unmatched ?? []).length > 0 ? (
          <TablePanel
            title="Offene Pool-Luecken"
            rows={(taxYearWalletFifoDelta?.unmatched ?? []).slice(0, 80).map((row) => ({
              zeit: row.event_time,
              pool: row.pool_id,
              asset: row.asset,
              menge: row.quantity,
              fehlt: row.missing_quantity,
              grund: row.reason,
              event: row.source_event_id
            }))}
            compact
          />
        ) : null}
        {(taxYearWalletFifoGaps?.diagnoses ?? []).length > 0 ? (
          <TablePanel
            title="Luecken-Diagnose"
            rows={(taxYearWalletFifoGaps?.diagnoses ?? []).slice(0, 80).map((row) => {
              const candidates = Array.isArray(row.candidate_events) ? row.candidate_events as Array<Record<string, unknown>> : [];
              const firstCandidate = candidates[0];
              return {
                zeit: row.event_time,
                pool: row.pool_id,
                asset: row.asset,
                fehlt: row.missing_quantity,
                ursache: row.likely_cause,
                aktion: row.recommended_action,
                kandidat: firstCandidate
                  ? `${String(firstCandidate.relation)} ${String(firstCandidate.event_time)} ${String(firstCandidate.quantity)} ${String(firstCandidate.asset)} ${String(firstCandidate.pool_id)}`
                  : "-",
                event: row.disposal_event_id
              };
            })}
            footer={taxYearWalletFifoGaps?.methodology ?? ""}
            compact
          />
        ) : null}
        {(taxYearWalletFifoOriginTrace?.traces ?? []).length > 0 ? (
          <TablePanel
            title="Herkunftsspur"
            rows={(taxYearWalletFifoOriginTrace?.traces ?? []).slice(0, 40).map((row) => {
              const txEvidence = row.transaction_history_evidence as Record<string, unknown> | undefined;
              const depositEvidence = row.deposit_history_evidence as Record<string, unknown> | undefined;
              const txPayload = txEvidence?.payload as Record<string, unknown> | undefined;
              const depositPayload = depositEvidence?.payload as Record<string, unknown> | undefined;
              return {
                zeit: row.gap_event_time,
                asset: row.asset,
                pool: row.pool_id,
                fehlt: row.missing_quantity,
                kandidat: row.candidate_event ? `${String((row.candidate_event as Record<string, unknown>).event_time)} ${String((row.candidate_event as Record<string, unknown>).quantity)} ${String((row.candidate_event as Record<string, unknown>).asset)}` : "-",
                tx_history: txEvidence ? `${String(txEvidence.filename)} #${String(txEvidence.row_number)} ${String(txPayload?.Operation ?? "")}` : "-",
                deposit_history: depositEvidence ? `${String(depositEvidence.filename)} #${String(depositEvidence.row_number)} ${String(depositPayload?.Status ?? "")}` : "-",
                netzwerk: row.network ?? "-",
                adresse: row.deposit_address ? shortAccount(String(row.deposit_address)) : "-",
                txid: row.onchain_tx_id ? shortAccount(String(row.onchain_tx_id)) : "-",
                aktion: row.recommended_action
              };
            })}
            footer={taxYearWalletFifoOriginTrace?.methodology ?? ""}
            compact
          />
        ) : null}
        {(taxYearWalletFifoSolanaOrigin?.traces ?? []).length > 0 ? (
          <TablePanel
            title="Solana-TX Ursprung"
            rows={(taxYearWalletFifoSolanaOrigin?.traces ?? []).slice(0, 20).map((row) => ({
              status: row.status,
              asset: row.asset,
              betrag: row.matched_amount ?? row.expected_amount ?? "-",
              sender: row.sender_owner ? shortAccount(String(row.sender_owner)) : "-",
              sender_eigen: row.sender_is_known_own_wallet ? "ja" : "nein",
              empfaenger: row.receiver_owner ? shortAccount(String(row.receiver_owner)) : "-",
              deposit_adresse: row.receiver_is_deposit_address ? "ja" : "nein",
              txid: row.signature ? shortAccount(String(row.signature)) : "-",
              blockzeit: row.block_time ?? "-",
              aktion: row.recommended_action,
              grund: row.reason ?? "-"
            }))}
            footer={taxYearWalletFifoSolanaOrigin?.methodology ?? ""}
            compact
          />
        ) : null}
        <div className="footer">
          {taxYearWalletFifoDelta?.methodology ?? "Read-only Preview. Die produktiven Tax-Lines bleiben unveraendert."}
        </div>
      </div>
        </>
      ) : null}

      <div className="panel declarationGuidePanel">
        <div className="panelToolbar">
          <strong>Steuererklaerung: Zahlen und Nachweise</strong>
          <span className={`statusPill ${taxYearFilingSummary?.export_ready ? "ok" : "warning"}`}>
            {taxYearFilingSummary?.export_ready ? "bereit" : "pruefen"}
          </span>
        </div>
        <p className="panelLead">{taxYearFilingSummary?.plain_language_summary ?? "Steuerjahr-Erklaerung wird geladen."}</p>
        <div className="portfolioSummaryStrip">
          <Metric title="Privat G/V" value={`${formatCurrency(taxYearFilingSummary?.taxable_private_disposals_eur)} EUR`} />
          <Metric title="Rewards/Mining" value={`${formatCurrency(taxYearFilingSummary?.rewards_mining_staking_income_eur)} EUR`} />
          <Metric title="Derivate" value={`${formatCurrency(taxYearFilingSummary?.derivative_pnl_eur)} EUR`} />
          <Metric title="Steuerfrei" value={`${formatCurrency(taxYearFilingSummary?.tax_free_private_disposals_eur)} EUR`} />
          <Metric
            title="Herkunftsbeilage"
            value={
              taxYearFilingSummary?.bmf_closure_appendix_items_count
                ? `${taxYearFilingSummary.bmf_closure_appendix_items_count} Position(en)`
                : "keine"
            }
          />
        </div>
        <div className="declarationSummaryGrid">
          {entryLines.map((line) => (
            <div className={`declarationEntryCard ${declarationTopicTone(String(line.topic))}`} key={`${line.topic}-${line.label}`}>
              <div className="declarationEntryHeader">
                <span className="heroKicker">{declarationTopicLabel(String(line.topic))}</span>
                <span className={`statusPill ${declarationTopicTone(String(line.topic))}`}>
                  {line.amount_eur === null || line.amount_eur === undefined ? "Nachweis" : `${formatCurrency(line.amount_eur)} EUR`}
                </span>
              </div>
              <strong>{String(line.label ?? "-")}</strong>
              <p>{String(line.declaration_target ?? "-")}</p>
              <div className="declarationEntryMeta">
                <span>{String(line.tax_treatment ?? "-")}</span>
                {line.evidence_ref ? (
                  <button type="button" onClick={() => onDownload(String(line.evidence_ref))} title={String(line.evidence_ref)}>
                    <FileDown size={16} />
                    Beleg
                  </button>
                ) : null}
              </div>
            </div>
          ))}
        </div>
        <div className="declarationActionBand">
          <button type="button" onClick={() => onDownload(`/api/v1/tax-years/${activeYearValue}/filing-summary`)}>
            <FileJson size={16} />
            Jahres-Erklaerung JSON
          </button>
          <button type="button" onClick={() => onDownload(`/api/v1/export/tax-years/${activeYearValue}/filing-checklist.csv`)}>
            <FileDown size={16} />
            Checkliste CSV
          </button>
          <button type="button" onClick={() => onDownload(`/api/v1/tax-years/${activeYearValue}/evidence`)}>
            <FileJson size={16} />
            Belegkarte JSON
          </button>
          <button type="button" onClick={() => onDownload("/api/v1/export/tax-payment-overview.json")}>
            <FileJson size={16} />
            Eingabezettel JSON
          </button>
          <button type="button" onClick={() => onDownload(`/api/v1/export/tax-years/${activeYearValue}/evidence-package.zip`)}>
            <PackageCheck size={16} />
            Jahres-Belegpaket
          </button>
        </div>
        {filingChecklist.length > 0 ? (
          <TablePanel
            title="Finanzamt-Checkliste"
            rows={filingChecklist.map((item) => ({
              kategorie: item.category,
              punkt: item.label,
              betrag_eur: item.amount_eur === null || item.amount_eur === undefined ? "-" : formatCurrency(item.amount_eur),
              aktion: item.action,
              erledigt_wenn: item.done_when,
              beleg: item.evidence_ref ?? "-"
            }))}
            compact
            rowActions={[
              {
                label: "Beleg oeffnen",
                icon: <FileDown size={16} />,
                onClick: (row) => onDownload(String(row.beleg ?? ""))
              }
            ]}
            footer="Eintragen sind Steuererklaerungswerte. Beilegen und Archivieren sind Nachweise, keine zusaetzlichen Betragszeilen."
          />
        ) : null}
        <TablePanel
          title="Eintragung und Behandlung"
          rows={entryLines.map((line) => ({
            bereich: line.label,
            betrag_eur: line.amount_eur === null || line.amount_eur === undefined ? "-" : formatCurrency(line.amount_eur),
            behandlung: line.tax_treatment,
            ziel: line.declaration_target,
            beleg: line.evidence_ref ?? "-",
            hinweis: line.note
          }))}
          footer={taxYearFilingSummary?.methodology ?? ""}
          compact
          rowActions={[
            {
              label: "Beleg oeffnen",
              icon: <FileDown size={16} />,
              onClick: (row) => onDownload(String(row.beleg ?? ""))
            }
          ]}
        />
        {proofLines.length > 0 ? (
          <TablePanel
            title="Nachweise und Pruefpunkte"
            rows={proofLines.map((line) => ({
              bereich: line.label,
              behandlung: line.tax_treatment,
              ziel: line.declaration_target,
              beleg: line.evidence_ref ?? "-",
              hinweis: line.note
            }))}
            compact
            rowActions={[
              {
                label: "Beleg oeffnen",
                icon: <FileDown size={16} />,
                onClick: (row) => onDownload(String(row.beleg ?? ""))
              }
            ]}
          />
        ) : null}
        {yearReviewDecisions.length > 0 ? (
          <TablePanel
            title="Review-Entscheidungen fuer dieses Steuerjahr"
            rows={yearReviewDecisions.map((decision) => ({
              typ: decision.decision_type,
              kategorie: decision.category,
              titel: decision.title,
              wirkung: decision.effect_summary,
              scope: decision.scope,
              beleg: decision.evidence_ref ?? "-",
              entschieden: decision.created_at ? formatDateTime(String(decision.created_at)) : "-"
            }))}
            compact
            rowActions={[
              {
                label: "Beleg oeffnen",
                icon: <FileDown size={16} />,
                onClick: (row) => onDownload(String(row.beleg ?? ""))
              }
            ]}
            footer="Jahresbezogene Review-Entscheidungen sind Beleg-/Methodikentscheidungen. Sie werden nicht als zusaetzlicher Betrag eingetragen."
          />
        ) : null}
        {primaryEvidenceItems.length > 0 ? (
          <div className="evidenceQuickGrid">
            {primaryEvidenceItems.slice(0, 8).map((item) => (
              <button
                type="button"
                className={`evidenceQuickCard ${String(item.status ?? "available")}`}
                key={String(item.evidence_id)}
                onClick={() => onDownload(String(item.endpoint))}
                title={String(item.endpoint)}
              >
                <span>{String(item.category ?? "-")}</span>
                <strong>{String(item.label ?? "-")}</strong>
                <small>{String(item.record_count ?? 0)} Datensaetze · {item.amount_eur === null || item.amount_eur === undefined ? "-" : `${formatCurrency(item.amount_eur)} EUR`}</small>
              </button>
            ))}
          </div>
        ) : null}
        {taxYearFilingSummary?.ascii_table ? (
          <pre className="asciiTable" aria-label="Kopierbare Steuerjahr-Erklaerung">
            {taxYearFilingSummary.ascii_table}
          </pre>
        ) : null}
        {taxYearFilingSummary?.checklist_ascii ? (
          <pre className="asciiTable" aria-label="Kopierbare Finanzamt-Checkliste">
            {taxYearFilingSummary.checklist_ascii}
          </pre>
        ) : null}
        {(taxYearFilingSummary?.warnings ?? []).length > 0 ? (
          <div className="statusRows">
            {(taxYearFilingSummary?.warnings ?? []).slice(0, 5).map((warning, index) => (
              <StatusRow key={`${warning}-${index}`} label={`Hinweis ${index + 1}`} value={warning} />
            ))}
          </div>
        ) : null}
      </div>

      <div className="panel">
        <div className="panelToolbar">
          <strong>Was muss ich eintragen?</strong>
          <span>{taxPaymentOverview?.generated_at ? formatDateTime(taxPaymentOverview.generated_at) : "-"}</span>
        </div>
        <div className="portfolioSummaryStrip">
          <Metric title="Anlage SO G/V" value={`${formatCurrency(activePaymentRow?.private_disposals_gain_loss_eur)} EUR`} />
          <Metric title="Rewards/Mining" value={`${formatCurrency(activePaymentRow?.rewards_mining_staking_income_eur)} EUR`} />
          <Metric title="Derivate" value={`${formatCurrency(activePaymentRow?.derivative_pnl_eur)} EUR`} />
          <Metric title="Steuerfrei" value={`${formatCurrency(activePaymentRow?.tax_free_private_disposals_eur)} EUR`} />
        </div>
        {activePaymentRow ? (
          <div className="statusRows">
            <StatusRow label="Eintragen bei" value={String(activePaymentRow.where_to_enter ?? "-")} />
            <StatusRow label="Jetzt tun" value={String(activePaymentRow.what_to_do ?? "-")} />
            <StatusRow label="Kurzzeile" value={String(activePaymentRow.display_line ?? "-")} />
          </div>
        ) : null}
        <TablePanel
          title="Gefuehrte Jahresaufgaben"
          rows={paymentChecklist.map((item) => ({
            bereich: paymentChecklistCategoryLabel(item.category),
            aufgabe: item.label,
            betrag_eur: item.amount_eur === null || item.amount_eur === undefined ? "-" : formatCurrency(item.amount_eur),
            ziel: item.target,
            detail: item.detail,
            beleg: item.evidence_ref ?? "-",
            status: item.severity
          }))}
          compact
        />
        {taxPaymentOverview?.ascii_table ? (
          <pre className="asciiTable" aria-label="Kopierbare Steueruebersicht">
            {taxPaymentOverview.ascii_table}
          </pre>
        ) : null}
        <TablePanel
          title="Steuer-Eingabezettel alle Jahre"
          rows={paymentRows.map((row) => ({
            jahr: row.year,
            status: row.status,
            anlage_so_gv_eur: row.private_disposals_gain_loss_eur,
            rewards_mining_eur: row.rewards_mining_staking_income_eur,
            derivate_eur: row.derivative_pnl_eur,
            steuerfrei_eur: row.tax_free_private_disposals_eur,
            wo_eintragen: row.declaration_bucket,
            was_tun: row.what_to_do,
            kurzzeile: row.display_line
          }))}
          footer={taxPaymentOverview?.methodology ?? ""}
          compact
        />
      </div>

      <div className="panel">
        <div className="panelToolbar">
          <strong>Steuerfreie Veraeusserung</strong>
          <label className="inlineControl">
            Mindestwert EUR
            <input
              value={minHoldingValueEur}
              onChange={(event) => onMinHoldingValueEurChange(event.target.value)}
              inputMode="decimal"
            />
          </label>
        </div>
        <div className="portfolioSummaryStrip">
          <Metric title="Jetzt steuerfrei" value={`${formatCurrency(taxHoldingPeriods?.tax_free_now_value_eur)} EUR`} />
          <Metric title="7 Tage" value={`${formatCurrency(taxHoldingPeriods?.next_7_days_value_eur)} EUR`} />
          <Metric title="30 Tage" value={`${formatCurrency(taxHoldingPeriods?.next_30_days_value_eur)} EUR`} />
          <Metric title="7 Monate" value={`${formatCurrency(taxHoldingPeriods?.next_7_months_value_eur)} EUR`} />
          <Metric title="1 Jahr" value={`${formatCurrency(taxHoldingPeriods?.next_year_value_eur)} EUR`} />
          <Metric title="Dust ausgeblendet" value={String(taxHoldingPeriods?.hidden_dust_lots_count ?? 0)} />
        </div>
        <TablePanel
          title="Haltefrist-Buckets"
          rows={holdingBuckets}
          footer={`Mindestwert: ${formatCurrency(taxHoldingPeriods?.min_value_eur ?? minHoldingValueEur)} EUR | Fehlende Preise: ${(taxHoldingPeriods?.missing_price_assets ?? []).join(", ") || "keine"}`}
          compact
        />
        <TablePanel
          title="Steuerfreie / bald steuerfreie FIFO-Lots"
          rows={holdingLots.slice(0, 120).map((lot) => ({
            bucket: lot.bucket,
            asset: lot.asset,
            current_value_eur: lot.current_value_eur,
            quantity_remaining: lot.quantity_remaining,
            acquired_at: lot.acquired_at,
            tax_free_at: lot.tax_free_at,
            days_until_tax_free: lot.days_until_tax_free,
            unrealized_gain_loss_eur: lot.unrealized_gain_loss_eur,
            price_source: lot.price_source,
            priced_at: lot.priced_at,
            source: lot.source,
            account: lot.account
          }))}
          footer={taxHoldingPeriods?.methodology ?? "Read-only aus offenen FIFO-Lots."}
        />
      </div>

      <div className="panel">
        <div className="panelToolbar">
          <strong>Verlustrealisierung planen</strong>
          <span>{taxLossRealizationPlanner?.generated_at ? formatDateTime(taxLossRealizationPlanner.generated_at) : "wird geladen"}</span>
        </div>
        <div className="portfolioSummaryStrip">
          <Metric title="Jetzt nutzbar" value={`${formatCurrency(taxLossRealizationPlanner?.tax_relevant_loss_if_sold_now_eur)} EUR`} />
          <Metric title="Frist abgelaufen" value={`${formatCurrency(taxLossRealizationPlanner?.expired_loss_not_tax_relevant_eur)} EUR`} />
          <Metric title="Lots nutzbar" value={String(taxLossRealizationPlanner?.tax_relevant_lots_count ?? 0)} />
          <Metric title="Lots abgelaufen" value={String(taxLossRealizationPlanner?.expired_loss_lots_count ?? 0)} />
        </div>
        <TablePanel
          title="FIFO-Lots mit Verlustfenster"
          rows={(taxLossRealizationPlanner?.rows ?? []).slice(0, 80).map((lot) => ({
            status: lot.status,
            asset: lot.asset,
            anschaffung: lot.acquired_at,
            letzter_steuerrelevanter_tag: lot.last_tax_relevant_disposal_date,
            tage_bis_steuerfrei: lot.days_until_tax_free,
            menge: lot.quantity_remaining,
            kosten_eur: formatCurrency(lot.cost_basis_eur_remaining),
            wert_eur: formatCurrency(lot.current_value_eur),
            unrealisiert_eur: formatCurrency(lot.unrealized_gain_loss_eur),
            lot_id: lot.lot_id,
            source_event_id: lot.source_event_id,
            quelle: lot.source,
            account: lot.account,
            preisquelle: lot.price_source,
            hinweis: lot.action_note
          }))}
          footer={(taxLossRealizationPlanner?.caveats ?? []).join(" ") || taxLossRealizationPlanner?.methodology || ""}
          compact
        />
      </div>

      <div className="taxYearGrid">
        {years.map((year) => (
          <button
            key={String(year.year)}
            className={`taxYearCard ${String(year.year) === activeYearValue ? "active" : ""}`}
            type="button"
            onClick={() => onSelectedTaxYearChange(String(year.year))}
          >
            <div className="sourceCardHeader">
              <strong>{String(year.year)}</strong>
              <span className={`statusPill ${taxYearTone(String(year.state ?? ""))}`}>
                {String(year.label ?? "-")}
              </span>
            </div>
            <div className="sourceCardValue">{formatCurrency(year.realized_gain_loss_eur)} EUR</div>
            <div className="sourceCardMeta">
              <span>{String(year.tax_lines_count ?? 0)} Tax-Lines</span>
              <span>{String(year.missing_price_groups ?? 0)} Preise</span>
              <span>{String(year.unmatched_disposals ?? 0)} FIFO</span>
              <span>{String(year.derivative_lines_count ?? 0)} Derivate</span>
            </div>
          </button>
        ))}
      </div>

      {taxViewMode !== "guided" ? (
        <>
      <section className="sourceDetailGrid">
        <div className="panel sourceDetailMain">
          <div className="panelToolbar">
            <strong>Jahresabschluss {activeYearValue}</strong>
            <span>{selectedYear?.is_closed_historical_year ? "historisch geschlossen" : "aktueller Scope"}</span>
          </div>
          <div className="sourceDetailValue">{formatCurrency(selectedYear?.realized_gain_loss_eur)} EUR</div>
          <div className="statusRows sourceStatusRows">
            <StatusRow label="Veraeusserungserloese" value={`${formatCurrency(selectedYear?.taxable_disposal_proceeds_eur)} EUR`} />
            <StatusRow label="Anschaffungskosten" value={`${formatCurrency(selectedYear?.acquisition_cost_eur)} EUR`} />
            <StatusRow label="Steuerfrei >365 Tage" value={`${formatCurrency(selectedYear?.tax_free_gain_loss_eur)} EUR`} />
            <StatusRow label="Steuerfreie Zeilen" value={String(selectedYear?.tax_free_lines_count ?? 0)} />
            <StatusRow label="Rewards/Einkuenfte" value={`${formatCurrency(selectedYear?.rewards_income_eur)} EUR`} />
            <StatusRow label="Derivate PnL" value={`${formatCurrency(selectedYear?.derivative_pnl_eur)} EUR`} />
            <StatusRow label="Fees" value={`${formatCurrency(selectedYear?.fees_eur)} EUR`} />
            <StatusRow label="Offene Issues" value={String(selectedYear?.review_issues_count ?? 0)} />
          </div>
        </div>
        <div className="panel">
          <div className="panelToolbar">
            <strong>Freigabegruende</strong>
            <span>{selectedYear?.export_blocked ? "blockiert" : "frei"}</span>
          </div>
          <div className="statusRows">
            <StatusRow label="Fehlende Preise" value={String(selectedYear?.missing_price_groups ?? 0)} />
            <StatusRow label="Unmatched FIFO" value={String(selectedYear?.unmatched_disposals ?? 0)} />
            <StatusRow label="Derivate-Zeilen" value={String(selectedYear?.derivative_lines_count ?? 0)} />
            <StatusRow label="Reward Events" value={String(selectedYear?.rewards_events_count ?? 0)} />
          </div>
        </div>
      </section>

      <section className="cockpitDataGrid">
        <div className="panel">
          <div className="panelToolbar">
            <strong>Gefuehrte Steuererklaerung {activeYearValue}</strong>
            <span className={`statusPill ${taxDeclarationGuide?.export_ready ? "ok" : "blocked"}`}>
              {taxDeclarationGuide?.export_ready ? "bereit" : "pruefen"}
            </span>
          </div>
          <div className="portfolioSummaryStrip">
            <Metric title="Saldo G/V" value={`${formatCurrency(taxDeclarationGuide?.realized_gain_loss_eur)} EUR`} />
            <Metric title="HNT G/V" value={`${formatCurrency(taxDeclarationGuide?.hnt_gain_loss_eur)} EUR`} />
            <Metric title="Steuerfrei" value={`${formatCurrency(taxDeclarationGuide?.tax_free_gain_loss_eur)} EUR`} />
            <Metric title="HNT Tax-Lines" value={String(taxDeclarationGuide?.hnt_tax_line_count ?? 0)} />
            <Metric title="Rewards" value={`${formatCurrency(taxDeclarationGuide?.rewards_income_eur)} EUR`} />
          </div>
          <TablePanel
            title="Eingabehilfe"
            rows={taxDeclarationGuide?.entries ?? []}
            footer={taxDeclarationGuide?.methodology ?? ""}
            compact
          />
          <TablePanel
            title="Verlust-Assets"
            rows={taxDeclarationGuide?.loss_assets ?? []}
            footer={`Belege: ${(taxDeclarationGuide?.evidence_exports ?? []).join(" | ")}`}
            compact
          />
        </div>
        <div className="panel">
          <div className="panelToolbar">
            <strong>Hinweise</strong>
            <span>{formatDateTime(taxDeclarationGuide?.generated_at)}</span>
          </div>
          <div className="statusRows">
            {(taxDeclarationGuide?.caveats ?? []).map((item, index) => (
              <StatusRow key={`${item}-${index}`} label={`Hinweis ${index + 1}`} value={item} />
            ))}
          </div>
        </div>
      </section>

      <div className="panel">
        <div className="panelToolbar">
          <strong>Jahres-Belegkarte {activeYearValue}</strong>
          <span className={`statusPill ${taxYearEvidence?.export_ready ? "ok" : "warning"}`}>
            {taxYearEvidence?.export_ready ? "bereit" : "pruefen"}
          </span>
        </div>
        <TablePanel
          title="Welche Datei belegt welchen Teil?"
          rows={(taxYearEvidence?.items ?? []).map((item) => ({
            bereich: paymentChecklistCategoryLabel(item.category),
            beleg: item.label,
            status: item.status,
            pflicht: item.required ? "ja" : "nein",
            zeilen: item.record_count,
            betrag_eur: item.amount_eur === null || item.amount_eur === undefined ? "-" : formatCurrency(item.amount_eur),
            format: item.file_format,
            endpoint: item.endpoint
          }))}
          footer={taxYearEvidence?.methodology ?? "Belegkarte wird geladen."}
          rowActions={[
            {
              label: "Beleg herunterladen",
              icon: <FileDown size={16} />,
              onClick: (row) => onDownload(String(row.endpoint ?? ""))
            }
          ]}
          compact
        />
      </div>

      <section className="cockpitDataGrid">
        <div className="panel">
          <div className="panelToolbar">
            <strong>Mining / Rewards / Income {activeYearValue}</strong>
            <span>{formatDateTime(taxIncomeGuide?.generated_at)}</span>
          </div>
          <div className="portfolioSummaryStrip">
            <Metric title="Reward/EÜR nah" value={`${formatCurrency(taxIncomeGuide?.reward_income_eur)} EUR`} />
            <Metric title="Generisches Income" value={`${formatCurrency(taxIncomeGuide?.generic_income_eur)} EUR`} />
            <Metric title="Events" value={String(taxIncomeGuide?.events_count ?? 0)} />
            <Metric title="Ohne Preis" value={String(taxIncomeGuide?.missing_value_count ?? 0)} />
            <Metric title="Ignoriert <=0" value={String(taxIncomeGuide?.ignored_non_positive_count ?? 0)} />
          </div>
          <TablePanel
            title="Income nach Asset und Typ"
            rows={taxIncomeGuide?.assets ?? []}
            footer={`Fehlende Assets: ${(taxIncomeGuide?.missing_assets ?? []).join(", ") || "keine"} | ${taxIncomeGuide?.methodology ?? ""}`}
            compact
          />
          <TablePanel
            title="Income Klassifizierung"
            rows={Object.entries(taxIncomeGuide?.classification_counts ?? {}).map(([classification, count]) => ({
              classification,
              count
            }))}
            footer="Review-Kategorien fuer generische Income-Zufluesse."
            compact
          />
        </div>
        <div className="panel">
          <div className="panelToolbar">
            <strong>Reward vs Handel HNT / IOT / MOBILE</strong>
            <span>{formatDateTime(taxRewardTradingSeparation?.generated_at)}</span>
          </div>
          <div className="portfolioSummaryStrip">
            <Metric title="Reward Einnahme" value={`${formatCurrency(activeRewardTradingTotals.reward)} EUR`} />
            <Metric title="Handel steuerpfl." value={`${formatCurrency(activeRewardTradingTotals.taxableTrade)} EUR`} />
            <Metric title="Handel steuerfrei" value={`${formatCurrency(activeRewardTradingTotals.taxFreeTrade)} EUR`} />
            <Metric title="Assets" value={String(activeRewardTradingRows.length)} />
          </div>
          <TablePanel
            title={`BMF-Trennung ${activeYearValue}`}
            rows={activeRewardTradingRows.map((row) => ({
              asset: row.asset,
              reward_einnahme_eur: formatCurrency(row.reward_income_eur),
              reward_menge: row.reward_quantity,
              reward_events: row.reward_events_count,
              handel_steuerpflichtig_eur: formatCurrency(row.trade_taxable_gain_loss_eur),
              handel_steuerfrei_eur: formatCurrency(row.trade_tax_free_gain_loss_eur),
              fifo_zeilen: Number(row.trade_taxable_lines_count ?? 0) + Number(row.trade_tax_free_lines_count ?? 0),
              einordnung: row.tax_note
            }))}
            footer={taxRewardTradingSeparation?.methodology ?? "Reward-/Handels-Trennung wird geladen."}
            compact
          />
        </div>
        <TablePanel
          title="Income Event Preview"
          rows={taxIncomeGuide?.events ?? []}
          footer="Maximal 200 Ereignisse; volle Nachweise bleiben in den Canonical Events und Exporten."
        />
      </section>

      <section className="cockpitDataGrid">
        <div className="panel">
          <div className="panelToolbar">
            <strong>Externe Solana-Zufluesse {activeYearValue}</strong>
            <span>{formatDateTime(taxExternalInflows?.generated_at)}</span>
          </div>
          <div className="portfolioSummaryStrip">
            <Metric title="Zufluesse" value={String(taxExternalInflows?.inflows_count ?? 0)} />
            <Metric title="Matched" value={String(taxExternalInflows?.matched_count ?? 0)} />
            <Metric title="Review" value={String(taxExternalInflows?.review_count ?? 0)} />
            <Metric title="Unmatched" value={String(taxExternalInflows?.unmatched_count ?? 0)} />
            <Metric title="Wert gesamt" value={`${formatCurrency(taxExternalInflows?.total_value_eur)} EUR`} />
            <Metric title="Review Wert" value={`${formatCurrency(taxExternalInflows?.review_value_eur)} EUR`} />
            <Metric title="Unmatched Wert" value={`${formatCurrency(taxExternalInflows?.unmatched_value_eur)} EUR`} />
          </div>
          <TablePanel
            title="External Inflow Matching"
            rows={taxExternalInflows?.rows ?? []}
            footer={`${taxExternalInflows?.methodology ?? ""} Assets: ${(taxExternalInflows?.assets ?? []).join(", ") || "keine"}`}
          />
        </div>
        <TablePanel
          title="Unmatched externe Solana-Zufluesse"
          rows={(taxExternalInflows?.rows ?? []).filter((row) => row.status === "unmatched_external_inflow")}
          footer="Diese Zeilen brauchen Beleg: eigener Transfer, Airdrop/Claim oder Importklassifizierung."
        />
      </section>

      <section className="cockpitDataGrid">
        <div className="panel">
          <div className="panelToolbar">
            <strong>Gewinntreiber {activeYearValue}</strong>
            <span>{formatDateTime(taxYearDrivers?.generated_at)}</span>
          </div>
          <div className="portfolioSummaryStrip">
            <Metric title="Steuerpflichtig" value={`${formatCurrency(taxYearDrivers?.taxable_gain_loss_eur)} EUR`} />
            <Metric title="Steuerfrei >365" value={`${formatCurrency(taxYearDrivers?.tax_free_gain_loss_eur)} EUR`} />
            <Metric title="Top steuerpfl." value={String(taxYearDrivers?.top_taxable_lines?.length ?? 0)} />
            <Metric title="Top steuerfrei" value={String(taxYearDrivers?.top_tax_free_lines?.length ?? 0)} />
          </div>
          <TablePanel
            title="Top steuerpflichtige Assets"
            rows={taxYearDrivers?.top_taxable_assets ?? []}
            footer={taxYearDrivers?.methodology ?? ""}
            compact
          />
        </div>
        <TablePanel
          title="Top steuerpflichtige Tax-Lines"
          rows={taxYearDrivers?.top_taxable_lines ?? []}
          footer="Nach absolutem Gewinn/Verlust sortiert."
        />
      </section>

      <section className="cockpitDataGrid">
        <TablePanel
          title="Top steuerfreie Assets >365 Tage"
          rows={taxYearDrivers?.top_tax_free_assets ?? []}
          footer="Nachrichtlich; nicht im steuerpflichtigen Saldo enthalten."
          compact
        />
        <TablePanel
          title="Top steuerfreie Tax-Lines >365 Tage"
          rows={taxYearDrivers?.top_tax_free_lines ?? []}
          footer="Dient der Plausibilisierung des Unterschieds zwischen Gesamt-FIFO und steuerpflichtigem Jahreswert."
        />
      </section>

      <section className="cockpitDataGrid">
        <TablePanel
          title={`Assets ${activeYearValue}`}
          rows={asRows(taxYearDetail?.asset_breakdown ?? selectedYear?.top_assets)}
          footer={taxYearDetail?.methodology ?? ""}
        />
        <TablePanel
          title={`Issues ${activeYearValue}`}
          rows={asRows(taxYearDetail?.issues ?? selectedYear?.issues)}
          footer={`Fehlende Preisassets: ${(taxYearDetail?.missing_price_assets ?? []).join(", ") || "keine"}`}
        />
      </section>
        </>
      ) : null}

      {taxViewMode === "expert" ? (
        <>
      <div className="panel">
        <div className="panelToolbar">
          <strong>Steuerlaeufe und Detailtabellen</strong>
          <div className="buttonRow">
            <button type="button" onClick={onRebuildTax}>
              FIFO neu berechnen
            </button>
            <button type="button" onClick={onRebuildDerivatives}>
              Derivate neu berechnen
            </button>
            <button type="button" onClick={() => onDownload("/api/v1/export/tax-lines.csv")}>
              Tax CSV
            </button>
            <button type="button" onClick={() => onDownload("/api/v1/export/derivative-lines.csv")}>
              Derivate CSV
            </button>
          </div>
        </div>
        <div className="reviewSummary">
          <Metric title="Tax-Lines" value={String(taxSummary?.tax_lines_count ?? taxLines.length)} />
          <Metric title="Unmatched" value={String(taxSummary?.unmatched_disposals ?? 0)} />
          <Metric title="Gewinn/Verlust EUR" value={formatCurrency(gainLossTotal)} />
          <Metric title="Derivate-Zeilen" value={String(derivativeSummary?.derivative_lines_count ?? derivativeLines.length)} />
          <Metric title="Derivate EUR" value={formatCurrency(derivativeSummary?.realized_pnl_eur ?? derivativeTotal)} />
          <Metric title="Derivate ohne Preis" value={String(derivativeSummary?.missing_price_count ?? 0)} />
          <Metric title="FIFO Run-ID" value={String(taxSummary?.run_id ?? "-")} />
          <Metric title="Derivate Run-ID" value={String(derivativeSummary?.run_id ?? "-")} />
          <Metric title="FIFO-Lots" value={String(taxLots.length)} />
        </div>
        <div className="notice inlineNotice">
          Rohdaten wie vollstaendige Tax-Lines und FIFO-Lots werden nicht mehr automatisch beim Oeffnen der Steuerseite geladen. Nutze die CSV-/API-Exports fuer vollstaendige Detailbelege.
        </div>
      </div>
      <TablePanel
        title="Nicht zugeordnete FIFO-Abgaenge"
        rows={taxUnmatchedDisposals}
        footer={`Abgaenge: ${taxUnmatchedDisposals.length}`}
      />
      <TablePanel title="FIFO-Lots" rows={taxLots} footer={`Lots: ${taxLots.length}`} />
      <TablePanel title="Tax-Lines" rows={taxLines} footer={`Zeilen: ${taxLines.length}`} />
      <TablePanel title="Derivate-Zeilen" rows={derivativeLines} footer={`Zeilen: ${derivativeLines.length}`} />
        </>
      ) : null}
    </Stack>
  );
}

function FlowSankeyPanel({
  flows,
  flowYear,
  onFlowYearChange,
  onRebuildFlows
}: {
  flows: Snapshot["flows"];
  flowYear: string;
  onFlowYearChange: (year: string) => void;
  onRebuildFlows: () => void;
}) {
  const edges = flows?.edges ?? [];
  const missingPrices = flows?.missing_price_assets ?? [];
  const availableYears = flows?.available_years ?? [];
  const nodes = Array.from(
    new Set(edges.flatMap((edge) => [String(edge.source_node), String(edge.target_node)]))
  ).sort();
  const sources = nodes.filter((node) => edges.some((edge) => String(edge.source_node) === node));
  const targets = nodes.filter((node) => edges.some((edge) => String(edge.target_node) === node));
  const height = Math.max(220, Math.max(sources.length, targets.length, 1) * 58 + 70);
  const maxValue = Math.max(...edges.map((edge) => parseMagnitude(edge.value_eur)), 1);
  const sourceY = positionMap(sources, height);
  const targetY = positionMap(targets, height);

  return (
    <div className="panel sankeyPanel">
      <div className="panelToolbar">
        <strong>Netto-Geldfluesse</strong>
        <div className="toolbarControls">
          <select value={flowYear} onChange={(event) => onFlowYearChange(event.target.value)}>
            <option value="all">Alle Jahre</option>
            {availableYears.map((year) => (
              <option key={year} value={String(year)}>
                {year}
              </option>
            ))}
          </select>
          <button type="button" onClick={onRebuildFlows}>
            Flows neu berechnen
          </button>
        </div>
      </div>
      <div className="flowSummary">
        <Metric title="Sichtbarer Nettofluss EUR" value={formatCurrency(flows?.total_visible_value_eur)} />
        <Metric title="Jahr" value={flows?.year ? String(flows.year) : "alle"} />
        <Metric title="Kanten" value={String(edges.length)} />
        <Metric title="Knoten" value={String(nodes.length)} />
        <Metric title="Fehlende Preise" value={missingPrices.length ? missingPrices.join(", ") : "keine"} />
      </div>
      {edges.length === 0 ? (
        <div className="empty">Keine sichtbaren Nettofluesse vorhanden.</div>
      ) : (
        <>
          <div className="sankeyCanvas">
            <svg viewBox={`0 0 960 ${height}`} role="img" aria-label="Netto-Geldfluesse">
              {edges.map((edge, index) => {
                const source = String(edge.source_node);
                const target = String(edge.target_node);
                const y1 = sourceY.get(source) ?? height / 2;
                const y2 = targetY.get(target) ?? height / 2;
                const width = 4 + (parseMagnitude(edge.value_eur) / maxValue) * 22;
                const color = flowColor(index);
                return (
                  <path
                    key={`${source}-${target}-${index}`}
                    d={`M 210 ${y1} C 390 ${y1}, 570 ${y2}, 750 ${y2}`}
                    fill="none"
                    stroke={color}
                    strokeLinecap="round"
                    strokeOpacity="0.72"
                    strokeWidth={width}
                  />
                );
              })}
              {sources.map((node) => (
                <g key={`source-${node}`}>
                  <rect x="32" y={(sourceY.get(node) ?? 0) - 16} width="156" height="32" rx="6" />
                  <text x="48" y={(sourceY.get(node) ?? 0) + 5}>
                    {node}
                  </text>
                </g>
              ))}
              {targets.map((node) => (
                <g key={`target-${node}`}>
                  <rect x="772" y={(targetY.get(node) ?? 0) - 16} width="156" height="32" rx="6" />
                  <text x="788" y={(targetY.get(node) ?? 0) + 5}>
                    {node}
                  </text>
                </g>
              ))}
            </svg>
          </div>
          <div className="flowLegend">
            {edges.map((edge, index) => (
              <div key={`${edge.source_node}-${edge.target_node}-${index}`} className="flowLegendItem">
                <span style={{ backgroundColor: flowColor(index) }} />
                <strong>
                  {String(edge.source_node)} {"->"} {String(edge.target_node)}
                </strong>
                <em>
                  {formatCurrency(edge.value_eur)} EUR · {String(edge.event_count)} Event(s)
                </em>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function ImportForm({
  onImportCsv
}: {
  onImportCsv: (
    source: string,
    filename: string,
    content: string,
    contentBase64?: string | null,
    sheetName?: string | null
  ) => void;
}) {
  type ImportMode = "file" | "api" | "onchain" | "v1_cache";
  const importModeOptions: Array<{ id: ImportMode; label: string; icon: React.ReactNode }> = [
    { id: "file", label: "Datei", icon: <Upload size={16} /> },
    { id: "api", label: "API", icon: <Database size={16} /> },
    { id: "onchain", label: "Onchain", icon: <GitBranch size={16} /> },
    { id: "v1_cache", label: "V1 Cache", icon: <PackageCheck size={16} /> }
  ];
  const sourceOptionsByMode: Record<ImportMode, Array<{ value: string; label: string }>> = {
    file: [
      { value: "manual-csv", label: "Manuelles CSV" },
      { value: "pionex", label: "Pionex" },
      { value: "binance", label: "Binance" },
      { value: "bitget", label: "Bitget" },
      { value: "helium", label: "Helium Legacy/Fairspot" }
    ],
    api: [
      { value: "binance", label: "Binance" },
      { value: "bitget", label: "Bitget" },
      { value: "pionex", label: "Pionex" }
    ],
    onchain: [
      { value: "solana_wallet", label: "Solana Wallet" },
      { value: "jup_wallet", label: "Jup Wallet" },
      { value: "helium", label: "Helium Legacy" }
    ],
    v1_cache: [
      { value: "v1_fx_cache", label: "V1 FX-Cache" }
    ]
  };
  const defaultSourceByMode: Record<ImportMode, string> = {
    file: "manual-csv",
    api: "binance",
    onchain: "solana_wallet",
    v1_cache: "v1_fx_cache"
  };
  const [importMode, setImportMode] = useState<ImportMode>("file");
  const [source, setSource] = useState("manual-csv");
  const [filename, setFilename] = useState("import.csv");
  const [content, setContent] = useState("");
  const [contentBase64, setContentBase64] = useState<string | null>(null);
  const [selectedSheet, setSelectedSheet] = useState<string | null>(null);
  const [preview, setPreview] = useState<Record<string, unknown> | null>(null);
  const [previewWarnings, setPreviewWarnings] = useState<Array<{ code: string; message: string }>>([]);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [preflightResult, setPreflightResult] = useState<Record<string, unknown> | null>(null);
  const [preflightLoading, setPreflightLoading] = useState(false);
  const [preflightError, setPreflightError] = useState<string | null>(null);
  const [harvestPath, setHarvestPath] = useState("var/binance_simple_earn_history/20260531T105555Z");
  const [harvestResult, setHarvestResult] = useState<Record<string, unknown> | null>(null);
  const [harvestLoading, setHarvestLoading] = useState(false);
  const [harvestError, setHarvestError] = useState<string | null>(null);
  const [binanceApiSince, setBinanceApiSince] = useState("2021-01-01");
  const [binanceApiAssets, setBinanceApiAssets] = useState("");
  const [binanceApiResult, setBinanceApiResult] = useState<Record<string, unknown> | null>(null);
  const [binanceApiLoading, setBinanceApiLoading] = useState(false);
  const [binanceApiError, setBinanceApiError] = useState<string | null>(null);
  const [rpcMaxRequests, setRpcMaxRequests] = useState("2");
  const [rpcDelaySeconds, setRpcDelaySeconds] = useState("0.25");
  const [rpcResult, setRpcResult] = useState<Record<string, unknown> | null>(null);
  const [rpcLoading, setRpcLoading] = useState(false);
  const [rpcError, setRpcError] = useState<string | null>(null);
  const isFileMode = importMode === "file";
  const isBinaryFile = contentBase64 !== null;
  const hasImportContent = isFileMode ? Boolean(content.trim() || contentBase64) : true;
  const importPreview = preview?.preview as Record<string, unknown> | undefined;
  const taxImpact = preview?.tax_impact as Record<string, unknown> | undefined;
  const currentState = preview?.current_state as Record<string, unknown> | undefined;
  const estimatedState = preview?.estimated_state as Record<string, unknown> | undefined;
  const executionPlan = preview?.execution_plan as Record<string, unknown> | undefined;
  const linkedPreflights = Array.isArray(preview?.linked_preflights)
    ? preview.linked_preflights as Array<Record<string, unknown>>
    : [];
  const canImportPreview = preview?.can_execute === true;
  const duplicateBatchId = typeof taxImpact?.duplicate_batch_id === "string" ? taxImpact.duplicate_batch_id : null;
  const canStartImport = isFileMode && hasImportContent && canImportPreview && duplicateBatchId === null;

  function resetPreview() {
    setPreview(null);
    setPreviewWarnings([]);
    setPreviewError(null);
    setPreflightResult(null);
    setPreflightError(null);
        setHarvestResult(null);
        setHarvestError(null);
        setBinanceApiResult(null);
        setBinanceApiError(null);
        setRpcResult(null);
        setRpcError(null);
  }

  function selectImportMode(mode: ImportMode) {
    setImportMode(mode);
    setSource(defaultSourceByMode[mode]);
    if (mode !== "file") {
      setContent("");
      setContentBase64(null);
      setSelectedSheet(null);
    }
    resetPreview();
  }

  async function readFile(file: File | undefined) {
    if (!file) {
      return;
    }
    setFilename(file.name);
    const extension = file.name.toLowerCase().split(".").pop();
    if (extension === "xlsx" || extension === "xls") {
      setContent("");
      setContentBase64(await readFileBase64(file));
      setSelectedSheet(null);
    } else {
      setContent(await file.text());
      setContentBase64(null);
      setSelectedSheet(null);
    }
    setPreview(null);
    setPreviewWarnings([]);
    setPreviewError(null);
  }

  async function previewImport() {
    setPreviewError(null);
    try {
      const payload = !isFileMode
        ? {
            source,
            import_mode: importMode,
            filename
          }
        : contentBase64
          ? {
            source,
            import_mode: importMode,
            filename,
            content_base64: contentBase64,
            sheet_name: selectedSheet || undefined
          }
          : {
            source,
            import_mode: importMode,
            filename,
            content
          };
      const result = await postApiResponse<Record<string, unknown>>("/api/v1/import/assistant/preview", payload);
      setPreview(result.data);
      setPreviewWarnings(result.warnings);
      setPreflightResult(null);
      setPreflightError(null);
      setHarvestResult(null);
      setHarvestError(null);
      setRpcResult(null);
      setRpcError(null);
      const nestedPreview = result.data?.preview as Record<string, unknown> | undefined;
      const sheetName = nestedPreview?.sheet_name;
      if (typeof sheetName === "string") {
        setSelectedSheet(sheetName);
      }
    } catch (caught) {
      setPreviewError(caught instanceof Error ? caught.message : "Preview fehlgeschlagen");
      setPreview(null);
      setPreviewWarnings([]);
    }
  }

  async function runSolanaRpcProbe() {
    const maxRequests = Math.max(1, Math.min(Number.parseInt(rpcMaxRequests, 10) || 1, 10));
    const delay = Math.max(0, Math.min(Number.parseFloat(rpcDelaySeconds) || 0, 10));
    if (!window.confirm(`Solana RPC Probe fuer maximal ${maxRequests} Signatur(en) starten?`)) {
      return;
    }
    setRpcLoading(true);
    setRpcError(null);
    try {
      const response = await postApiResponse<Record<string, unknown>>(
        "/api/v1/import/solscan/rpc-probe",
        {
          max_requests: maxRequests,
          delay_seconds: String(delay)
        },
        90000
      );
      setRpcResult(response.data);
    } catch (caught) {
      setRpcError(caught instanceof Error ? caught.message : "RPC-Probe fehlgeschlagen");
    } finally {
      setRpcLoading(false);
    }
  }

  async function runBinanceHarvestImport(execute: boolean) {
    const trimmed = harvestPath.trim();
    if (!trimmed) {
      setHarvestError("Harvest-Pfad fehlt.");
      return;
    }
    if (execute && !window.confirm("Binance Harvest wirklich importieren und Pipeline neu berechnen?")) {
      return;
    }
    setHarvestLoading(true);
    setHarvestError(null);
    try {
      const response = await postApiResponse<Record<string, unknown>>(
        "/api/v1/sources/binance/earn-history-harvest/import",
        {
          harvest_path: trimmed,
          execute
        },
        60000
      );
      setHarvestResult(response.data);
    } catch (caught) {
      setHarvestError(caught instanceof Error ? caught.message : "Harvest-Preview fehlgeschlagen");
    } finally {
      setHarvestLoading(false);
    }
  }

  async function runBinanceApiImport(execute: boolean) {
    if (execute && !window.confirm("Binance Simple-Earn-Historie direkt per API importieren und Pipeline neu berechnen?")) {
      return;
    }
    setBinanceApiLoading(true);
    setBinanceApiError(null);
    try {
      const assets = binanceApiAssets
        .split(",")
        .map((asset) => asset.trim().toUpperCase())
        .filter((asset) => asset.length > 0);
      const response = await postApiResponse<Record<string, unknown>>(
        "/api/v1/sources/binance/earn-history-api/import",
        {
          since: binanceApiSince.trim() || null,
          assets,
          max_pages: 200,
          max_records: 50000,
          execute
        },
        240000
      );
      setBinanceApiResult(response.data);
    } catch (caught) {
      setBinanceApiError(caught instanceof Error ? caught.message : "Binance API-Historie fehlgeschlagen");
    } finally {
      setBinanceApiLoading(false);
    }
  }

  async function runLinkedPreflight(row: Record<string, unknown>) {
    const endpoint = String(row.endpoint ?? "");
    const method = String(row.method ?? "GET").toUpperCase();
    const externalRequests = row.external_requests === true;
    const writesDatabase = row.writes_database === true;
    if (!endpoint || method !== "GET" || externalRequests || writesDatabase) {
      setPreflightError("Dieser Preflight wird nicht direkt ausgefuehrt. Nutze den angezeigten Spezialpfad bewusst.");
      return;
    }
    setPreflightLoading(true);
    setPreflightError(null);
    try {
      const result = await getApi<Record<string, unknown>>(endpoint);
      setPreflightResult({
        endpoint,
        label: row.label,
        ...result
      });
    } catch (caught) {
      setPreflightError(caught instanceof Error ? caught.message : "Preflight fehlgeschlagen");
    } finally {
      setPreflightLoading(false);
    }
  }
  const assistantSteps = Array.isArray(preview?.steps) ? preview.steps : [
    "Quelle",
    "Importart",
    "Vorschau",
    "Preisbedarf",
    "Steuerwirkung",
    "Ausfuehren"
  ];

  return (
    <div className="panel formPanel">
      <div className="panelToolbar">
        <strong>Import-Assistent</strong>
        <button type="button" onClick={previewImport} disabled={!hasImportContent}>
          Preview
        </button>
        <button
          type="button"
          onClick={() => onImportCsv(source, filename, content, contentBase64, selectedSheet)}
          disabled={!canStartImport}
        >
          Import starten
        </button>
      </div>
      <div className="modeSelector" role="tablist" aria-label="Importart">
        {importModeOptions.map((option) => (
          <button
            key={option.id}
            type="button"
            className={importMode === option.id ? "active" : ""}
            onClick={() => selectImportMode(option.id)}
          >
            {option.icon}
            <span>{option.label}</span>
          </button>
        ))}
      </div>
      <div className="formGrid">
        <label>
          Quelle
          <select
            value={source}
            onChange={(event) => {
              setSource(event.target.value);
              resetPreview();
            }}
          >
            {sourceOptionsByMode[importMode].map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        {isFileMode ? (
          <label>
            Datei
            <input
              type="file"
              accept=".csv,.xlsx,.xls,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.ms-excel"
              onChange={(event) => void readFile(event.target.files?.[0])}
            />
          </label>
        ) : (
          <label>
            Importpfad
            <input value="Preview-only, Execute ueber verlinkten Spezialpfad" readOnly />
          </label>
        )}
      </div>
      {isFileMode ? (
        isBinaryFile ? (
          <div className="fileInfo">Excel-Datei geladen: {filename}</div>
        ) : (
          <textarea
            value={content}
            onChange={(event) => {
              setContent(event.target.value);
              setContentBase64(null);
              setSelectedSheet(null);
              resetPreview();
            }}
            placeholder="time,asset,amount,type,quote_asset,quote_quantity"
          />
        )
      ) : (
        <div className="fileInfo">
          Dieser Modus sammelt die passenden Preflight-Pfade und startet keine externen API-Abfragen automatisch.
        </div>
      )}
      {previewError ? <div className="error">{previewError}</div> : null}
      {isFileMode && contentBase64 && Array.isArray(importPreview?.sheet_names) && importPreview.sheet_names.length > 0 ? (
        <div className="sheetSelect">
          <label>
            Tabellenblatt
            <select
              value={selectedSheet ?? String(importPreview.sheet_name ?? importPreview.sheet_names[0])}
              onChange={(event) => {
                setSelectedSheet(event.target.value);
                setPreview(null);
                setPreviewWarnings([]);
                setPreviewError(null);
              }}
            >
              {importPreview.sheet_names.map((sheet) => (
                <option key={String(sheet)} value={String(sheet)}>
                  {String(sheet)}
                </option>
              ))}
            </select>
          </label>
        </div>
      ) : null}
      {preview ? (
        <div className="previewBox">
          <strong>Preview</strong>
          <div className="stepper">
            {assistantSteps.map((step, index) => (
              <span
                key={String(step)}
                className={index < assistantSteps.length - 1 || canStartImport ? "done" : "pending"}
              >
                {String(step)}
              </span>
            ))}
          </div>
          <div className="reviewSummary">
            <Metric title="Zeilen" value={String(importPreview?.row_count ?? taxImpact?.estimated_new_rows ?? 0)} />
            <Metric title="Normalisierbar" value={String(taxImpact?.estimated_normalizable_rows ?? 0)} />
            <Metric title="Profil" value={String(importPreview?.profile_label ?? "-")} />
            <Metric title="Assets" value={Array.isArray(taxImpact?.detected_assets) ? taxImpact.detected_assets.join(", ") : "-"} />
            <Metric title="Jahre" value={Array.isArray(taxImpact?.detected_years) ? taxImpact.detected_years.join(", ") : "-"} />
          </div>
          <div className="reviewSummary">
            <Metric title="Batches vorher" value={String(currentState?.import_batches ?? 0)} />
            <Metric title="Raw vorher" value={String(currentState?.raw_objects ?? 0)} />
            <Metric title="Raw nach Preview" value={String(estimatedState?.raw_objects ?? currentState?.raw_objects ?? 0)} />
            <Metric title="Export vorher" value={currentState?.allow_export === true ? "frei" : "pruefen"} />
          </div>
          <TablePanel title="Preisbedarf" rows={asRows(preview.price_needs)} compact />
          {executionPlan ? (
            <TablePanel
              title="Execute-Plan"
              rows={[
                {
                  writes_database: executionPlan.writes_database,
                  will_create_batch: executionPlan.will_create_batch,
                  will_normalize_batch: executionPlan.will_normalize_batch,
                  will_rebuild_pipeline: executionPlan.will_rebuild_pipeline,
                  affected_tables: Array.isArray(executionPlan.affected_tables)
                    ? executionPlan.affected_tables.join(", ")
                    : "",
                  trace_url_template: executionPlan.trace_url_template
                }
              ]}
              footer={String(executionPlan.note ?? "")}
              compact
            />
          ) : null}
          {linkedPreflights.length > 0 ? (
            <TablePanel
              title="Verknuepfte Preflights"
              rows={linkedPreflights.map((item) => ({
                label: item.label,
                method: item.method,
                endpoint: item.endpoint,
                writes_database: item.writes_database,
                external_requests: item.external_requests,
                purpose: item.purpose,
                next_step: item.next_step
              }))}
              footer="Diese Pfade sind read-only bzw. explizit markiert; Execute bleibt getrennt."
              rowActions={[
                {
                  label: "Read-only GET ausfuehren",
                  icon: <RefreshCcw size={16} />,
                  onClick: runLinkedPreflight
                }
              ]}
              compact
            />
          ) : null}
          {preflightLoading ? <div className="notice inlineNotice">Preflight laeuft...</div> : null}
          {preflightError ? <div className="error inlineNotice">{preflightError}</div> : null}
          {preflightResult ? <PreflightResultPanel result={preflightResult} /> : null}
          {importMode === "api" && source === "binance" ? (
            <div className="assistantActionPanel">
              <div className="panelToolbar">
                <strong>Binance API-Historie</strong>
                <div className="buttonRow">
                  <button type="button" onClick={() => void runBinanceApiImport(false)} disabled={binanceApiLoading}>
                    API Preview
                  </button>
                  <button
                    type="button"
                    onClick={() => void runBinanceApiImport(true)}
                    disabled={binanceApiLoading || !harvestCanExecute(binanceApiResult)}
                  >
                    API importieren
                  </button>
                  <button type="button" onClick={() => void runBinanceHarvestImport(false)} disabled={harvestLoading}>
                    Datei-Preview
                  </button>
                  <button
                    type="button"
                    onClick={() => void runBinanceHarvestImport(true)}
                    disabled={harvestLoading || !harvestCanExecute(harvestResult)}
                  >
                    Datei importieren
                  </button>
                </div>
              </div>
              <div className="formGrid">
                <label>
                  API seit
                  <input
                    value={binanceApiSince}
                    onChange={(event) => {
                      setBinanceApiSince(event.target.value);
                      setBinanceApiResult(null);
                      setBinanceApiError(null);
                    }}
                  />
                </label>
                <label>
                  API Assets
                  <input
                    value={binanceApiAssets}
                    placeholder="leer = aktuelle Earn-Produkte"
                    onChange={(event) => {
                      setBinanceApiAssets(event.target.value);
                      setBinanceApiResult(null);
                      setBinanceApiError(null);
                    }}
                  />
                </label>
                <label>
                  Lokaler Harvest-Pfad
                  <input
                    value={harvestPath}
                    onChange={(event) => {
                      setHarvestPath(event.target.value);
                      setHarvestResult(null);
                      setHarvestError(null);
                    }}
                  />
                </label>
              </div>
              <div className="fileInfo">
                API Preview und Datei-Preview nutzen `execute=false`. Import schreibt erst nach bestaetigter Preview und bewusster Bestaetigung.
              </div>
              {binanceApiLoading ? <div className="notice inlineNotice">Binance API-Historie laeuft...</div> : null}
              {binanceApiError ? <div className="error inlineNotice">{binanceApiError}</div> : null}
              {binanceApiResult ? <BinanceHarvestResultPanel result={binanceApiResult} /> : null}
              {harvestLoading ? <div className="notice inlineNotice">Harvest wird geprueft...</div> : null}
              {harvestError ? <div className="error inlineNotice">{harvestError}</div> : null}
              {harvestResult ? <BinanceHarvestResultPanel result={harvestResult} /> : null}
            </div>
          ) : null}
          {importMode === "onchain" && ["solana_wallet", "jup_wallet", "helium"].includes(source) ? (
            <div className="assistantActionPanel">
              <div className="panelToolbar">
                <strong>Solana RPC Probe</strong>
                <button type="button" onClick={() => void runSolanaRpcProbe()} disabled={rpcLoading}>
                  RPC Probe starten
                </button>
              </div>
              <div className="formGrid">
                <label>
                  Max. Signaturen
                  <input
                    value={rpcMaxRequests}
                    onChange={(event) => {
                      setRpcMaxRequests(event.target.value);
                      setRpcResult(null);
                      setRpcError(null);
                    }}
                    inputMode="numeric"
                  />
                </label>
                <label>
                  Delay Sekunden
                  <input
                    value={rpcDelaySeconds}
                    onChange={(event) => {
                      setRpcDelaySeconds(event.target.value);
                      setRpcResult(null);
                      setRpcError(null);
                    }}
                    inputMode="decimal"
                  />
                </label>
              </div>
              <div className="fileInfo">
                Die Probe ist read-only, erzeugt externe RPC-Requests und importiert keine V2-Daten.
              </div>
              {rpcLoading ? <div className="notice inlineNotice">RPC-Probe laeuft...</div> : null}
              {rpcError ? <div className="error inlineNotice">{rpcError}</div> : null}
              {rpcResult ? <SolanaRpcProbeResultPanel result={rpcResult} /> : null}
            </div>
          ) : null}
          <div className={canStartImport ? "notice inlineNotice" : "error inlineNotice"}>
            {canStartImport
              ? "Importfreigabe: ok"
              : `Importfreigabe: blockiert${duplicateBatchId ? `, Dublette ${duplicateBatchId}` : ""}`}
          </div>
          {previewWarnings.length > 0 ? (
            <ul className="warningList">
              {previewWarnings.map((warning) => (
                <li key={`${warning.code}-${warning.message}`}>{warning.message}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function PriceForm({
  onAddPrice
}: {
  onAddPrice: (asset: string, priceEur: string, pricedAt: string, source: string, confidence: string) => void;
}) {
  const [asset, setAsset] = useState("USDT");
  const [price, setPrice] = useState("0.90");
  const [pricedAt, setPricedAt] = useState(() => new Date().toISOString().slice(0, 16));
  const [source, setSource] = useState("frontend-manual");
  const [confidence, setConfidence] = useState("1.0");
  return (
    <div className="panel formPanel">
      <div className="panelToolbar">
        <strong>Preis setzen</strong>
        <button type="button" onClick={() => onAddPrice(asset, price, pricedAt, source, confidence)}>
          Speichern
        </button>
      </div>
      <div className="formGrid">
        <label>
          Asset
          <input value={asset} onChange={(event) => setAsset(event.target.value.toUpperCase())} />
        </label>
        <label>
          EUR Preis
          <input value={price} onChange={(event) => setPrice(event.target.value)} />
        </label>
        <label>
          Bewertungszeit
          <input type="datetime-local" value={pricedAt} onChange={(event) => setPricedAt(event.target.value)} />
        </label>
        <label>
          Quelle
          <input value={source} onChange={(event) => setSource(event.target.value)} />
        </label>
        <label>
          Confidence
          <input value={confidence} onChange={(event) => setConfidence(event.target.value)} />
        </label>
      </div>
    </div>
  );
}

function PriceCsvImportForm({
  onImportPriceCsv
}: {
  onImportPriceCsv: (content: string, defaultSource: string) => void;
}) {
  const [content, setContent] = useState("asset,price_eur,priced_at,source\nMOBILE,0.001,2021-05-15,manual-source");
  const [source, setSource] = useState("manual-price-csv");
  return (
    <div className="panel formPanel">
      <div className="panelToolbar">
        <strong>Preis-CSV importieren</strong>
        <button type="button" onClick={() => onImportPriceCsv(content, source)} disabled={!content.trim()}>
          Importieren
        </button>
      </div>
      <div className="formGrid single">
        <label>
          Default-Quelle
          <input value={source} onChange={(event) => setSource(event.target.value)} />
        </label>
      </div>
      <textarea
        value={content}
        onChange={(event) => setContent(event.target.value)}
        placeholder="asset,price_eur,priced_at,source"
      />
    </div>
  );
}

function V1FxCacheImportForm({
  onImportV1FxCache
}: {
  onImportV1FxCache: (dbPath: string, confidence: string) => void;
}) {
  const [dbPath, setDbPath] = useState("/root/.local/share/steuerreport/steuerreport.db");
  const [confidence, setConfidence] = useState("1.0");
  return (
    <div className="panel formPanel">
      <div className="panelToolbar">
        <strong>V1-Preiscache importieren</strong>
        <button type="button" onClick={() => onImportV1FxCache(dbPath, confidence)} disabled={!dbPath.trim()}>
          Importieren
        </button>
      </div>
      <div className="formGrid">
        <label>
          V1-Datenbank
          <input value={dbPath} onChange={(event) => setDbPath(event.target.value)} />
        </label>
        <label>
          Confidence
          <input value={confidence} onChange={(event) => setConfidence(event.target.value)} />
        </label>
      </div>
    </div>
  );
}

function ExternalPriceBackfillForm({
  onBackfillExternalPrices
}: {
  onBackfillExternalPrices: (maxRequests: string, provider: string, dryRun: boolean, assets: string) => void;
}) {
  const [maxRequests, setMaxRequests] = useState("25");
  const [provider, setProvider] = useState("auto");
  const [assets, setAssets] = useState("BTTC,VTHO,NFT");
  const [dryRun, setDryRun] = useState(true);
  return (
    <div className="panel formPanel">
      <div className="panelToolbar">
        <strong>Externe Preise nachladen</strong>
        <button type="button" onClick={() => onBackfillExternalPrices(maxRequests, provider, dryRun, assets)}>
          {dryRun ? "Planen" : "Importieren"}
        </button>
      </div>
      <div className="formGrid">
        <label>
          Provider
          <select value={provider} onChange={(event) => setProvider(event.target.value)}>
            <option value="auto">Auto</option>
            <option value="defillama">DefiLlama</option>
            <option value="coingecko">CoinGecko</option>
          </select>
        </label>
        <label>
          Max. Requests
          <input value={maxRequests} onChange={(event) => setMaxRequests(event.target.value)} />
        </label>
        <label>
          Assets
          <input value={assets} onChange={(event) => setAssets(event.target.value)} />
        </label>
        <label className="checkboxLabel">
          <input type="checkbox" checked={dryRun} onChange={(event) => setDryRun(event.target.checked)} />
          Dry Run
        </label>
      </div>
    </div>
  );
}

function CurrentPortfolioPriceBackfillForm({
  onBackfillCurrentPortfolioPrices
}: {
  onBackfillCurrentPortfolioPrices: (maxRequests: string, dryRun: boolean, assets: string) => void;
}) {
  const [maxRequests, setMaxRequests] = useState("50");
  const [assets, setAssets] = useState("");
  const [dryRun, setDryRun] = useState(false);
  return (
    <div className="panel formPanel">
      <div className="panelToolbar">
        <strong>Aktuelle Portfolio-Marktpreise</strong>
        <button type="button" onClick={() => onBackfillCurrentPortfolioPrices(maxRequests, dryRun, assets)}>
          {dryRun ? "Planen" : "Importieren"}
        </button>
      </div>
      <div className="formGrid">
        <label>
          Assets
          <input value={assets} onChange={(event) => setAssets(event.target.value)} />
        </label>
        <label>
          Max. Requests
          <input value={maxRequests} onChange={(event) => setMaxRequests(event.target.value)} />
        </label>
        <label className="checkboxLabel">
          <input type="checkbox" checked={dryRun} onChange={(event) => setDryRun(event.target.checked)} />
          Dry Run
        </label>
      </div>
    </div>
  );
}

function DeleteImportForm({
  onDeleteImportBatch
}: {
  onDeleteImportBatch: (batchId: string) => void;
}) {
  const [batchId, setBatchId] = useState("");
  return (
    <div className="panel formPanel">
      <div className="panelToolbar">
        <strong>Import entfernen</strong>
        <button type="button" onClick={() => onDeleteImportBatch(batchId)} disabled={!batchId.trim()}>
          Loeschen
        </button>
      </div>
      <div className="formGrid single">
        <label>
          Batch-ID
          <input value={batchId} onChange={(event) => setBatchId(event.target.value)} />
        </label>
      </div>
    </div>
  );
}

function BatchTracePanel({
  imports,
  rawObjects,
  canonicalEvents,
  onDownload
}: {
  imports: Array<Record<string, unknown>>;
  rawObjects: Array<Record<string, unknown>>;
  canonicalEvents: Array<Record<string, unknown>>;
  onDownload: (path: string) => void;
}) {
  const [selectedBatchId, setSelectedBatchId] = useState("");
  const activeBatchId = selectedBatchId || String(imports[0]?.batch_id ?? "");
  const filteredRawObjects = activeBatchId
    ? rawObjects.filter((row) => String(row.batch_id ?? "") === activeBatchId)
    : rawObjects;
  const rawObjectIds = new Set(filteredRawObjects.map((row) => String(row.raw_object_id ?? "")));
  const filteredCanonicalEvents = activeBatchId
    ? canonicalEvents.filter((row) => rawObjectIds.has(String(row.raw_object_id ?? "")))
    : canonicalEvents;

  return (
    <Stack>
      <div className="panel formPanel">
        <div className="panelToolbar">
          <strong>Batch-Trace</strong>
          <button
            type="button"
            onClick={() => onDownload(`/api/v1/import/batches/${activeBatchId}/trace.json`)}
            disabled={!activeBatchId}
          >
            Trace JSON
          </button>
        </div>
        <div className="formGrid single">
          <label>
            Import-Batch
            <select value={activeBatchId} onChange={(event) => setSelectedBatchId(event.target.value)}>
              {imports.map((batch) => (
                <option key={String(batch.batch_id)} value={String(batch.batch_id)}>
                  {String(batch.filename ?? batch.source ?? batch.batch_id)} | {String(batch.raw_object_count ?? 0)} Raw
                </option>
              ))}
            </select>
          </label>
        </div>
      </div>
      <TablePanel title="Raw Objects im Batch" rows={filteredRawObjects} />
      <TablePanel title="Canonical Events im Batch" rows={filteredCanonicalEvents} />
    </Stack>
  );
}

function ExportForm({
  onCreatePdfExport
}: {
  onCreatePdfExport: (label: string, estimatedPages: string) => void;
}) {
  const [label, setLabel] = useState("steuerreport");
  const [pages, setPages] = useState("1");
  return (
    <div className="panel formPanel">
      <div className="panelToolbar">
        <strong>PDF-Pakete erzeugen</strong>
        <button type="button" onClick={() => onCreatePdfExport(label, pages)}>
          Erzeugen
        </button>
      </div>
      <div className="formGrid">
        <label>
          Label
          <input value={label} onChange={(event) => setLabel(event.target.value)} />
        </label>
        <label>
          geschaetzte Seiten
          <input value={pages} onChange={(event) => setPages(event.target.value)} />
        </label>
      </div>
    </div>
  );
}

function AdminSettingForm({
  onSaveAdminSetting
}: {
  onSaveAdminSetting: (key: string, valueJson: string) => void;
}) {
  const [key, setKey] = useState("ai.external.enabled");
  const [valueJson, setValueJson] = useState("false");
  return (
    <div className="panel formPanel">
      <div className="panelToolbar">
        <strong>Setting schreiben</strong>
        <button type="button" onClick={() => onSaveAdminSetting(key, valueJson)}>
          Speichern
        </button>
      </div>
      <div className="formGrid">
        <label>
          Key
          <input value={key} onChange={(event) => setKey(event.target.value)} />
        </label>
        <label>
          JSON-Wert
          <input value={valueJson} onChange={(event) => setValueJson(event.target.value)} />
        </label>
      </div>
    </div>
  );
}

function V1CexCredentialTakeoverPanel({
  report,
  onImportV1CexCredentials
}: {
  report: Snapshot["v1CexCredentialTakeover"];
  onImportV1CexCredentials: () => void;
}) {
  const items = report?.items ?? [];
  return (
    <div className="panel">
      <div className="panelToolbar">
        <strong>V1-CEX-Credential-Uebernahme</strong>
        <button type="button" onClick={onImportV1CexCredentials} disabled={(report?.transferable ?? 0) === 0}>
          <RefreshCcw size={16} />
          <span>Aus V1 uebernehmen</span>
        </button>
      </div>
      <div className="portfolioSummaryStrip">
        <Metric title="Uebernehmbar" value={String(report?.transferable ?? 0)} />
        <Metric title="Blockiert" value={String(report?.blocked ?? 0)} />
        <Metric title="Stand" value={report?.generated_at ? formatDateTime(report.generated_at) : "-"} />
      </div>
      <TablePanel
        title="V1-Preflight"
        rows={items.map((item) => ({
          connector: item.connector_id,
          status: sourceConnectorStatusLabel(item.status),
          uebernehmbar: item.can_take_over ? "ja" : "nein",
          api_key: item.has_api_key ? "vorhanden" : "fehlt",
          api_secret: item.has_api_secret ? "vorhanden" : "fehlt",
          passphrase: item.has_passphrase ? "vorhanden" : "-",
          secret_keys: `${String(item.keys_present ?? 0)}/${String(item.keys_required ?? 0)}`,
          problem: item.credential_issue,
          naechster_schritt: item.next_action
        }))}
        compact
        footer={report?.methodology ?? ""}
      />
    </div>
  );
}

function AdminCexCredentialForm({
  onSaveCexCredentials
}: {
  onSaveCexCredentials: (connectorId: string, apiKey: string, apiSecret: string, passphrase: string) => void;
}) {
  const [connectorId, setConnectorId] = useState("binance");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const needsPassphrase = connectorId === "bitget";
  return (
    <div className="panel formPanel">
      <div className="panelToolbar">
        <strong>CEX-Credentials speichern</strong>
        <button
          type="button"
          onClick={() => onSaveCexCredentials(connectorId, apiKey, apiSecret, passphrase)}
          disabled={!apiKey.trim() || !apiSecret.trim() || (needsPassphrase && !passphrase.trim())}
        >
          <Settings size={16} />
          <span>Verschluesselt speichern</span>
        </button>
      </div>
      <div className="formGrid">
        <label>
          Connector
          <select
            value={connectorId}
            onChange={(event) => {
              setConnectorId(event.target.value);
              setApiKey("");
              setApiSecret("");
              setPassphrase("");
            }}
          >
            <option value="binance">Binance</option>
            <option value="bitget">Bitget</option>
            <option value="pionex">Pionex</option>
          </select>
        </label>
        <label>
          API Key
          <input value={apiKey} type="password" autoComplete="off" onChange={(event) => setApiKey(event.target.value)} />
        </label>
        <label>
          API Secret
          <input value={apiSecret} type="password" autoComplete="off" onChange={(event) => setApiSecret(event.target.value)} />
        </label>
        <label>
          Passphrase
          <input value={passphrase} type="password" autoComplete="off" onChange={(event) => setPassphrase(event.target.value)} />
        </label>
      </div>
    </div>
  );
}

function JupiterTokenApiPanel({
  query,
  result,
  metadataCache,
  onQueryChange,
  onSaveApiKey,
  onSearch,
  onRefreshMetadataCache
}: {
  query: string;
  result: Snapshot["jupiterTokenSearch"];
  metadataCache: Snapshot["jupiterMetadataCache"];
  onQueryChange: (query: string) => void;
  onSaveApiKey: (apiKey: string) => void;
  onSearch: (query: string) => void;
  onRefreshMetadataCache: (limit?: number, force?: boolean) => void;
}) {
  const [apiKey, setApiKey] = useState("");
  const rows = (result?.tokens ?? []).map((token) => ({
    symbol: token.symbol,
    name: token.name,
    mint: shortAccount(String(token.id ?? "")),
    verified: token.is_verified === true ? "ja" : token.is_verified === false ? "nein" : "-",
    score: token.organic_score ?? "-",
    preis_usd: token.usd_price ?? "-",
    liquidity_usd: token.liquidity_usd ?? "-",
    tags: Array.isArray(token.tags) ? token.tags.join(", ") : "",
    updated: token.updated_at ? formatDateTime(String(token.updated_at)) : "-"
  }));
  const cacheRows = (metadataCache?.items ?? []).map((token) => ({
    symbol: token.symbol ?? "-",
    name: token.name ?? "-",
    mint: shortAccount(String(token.mint ?? "")),
    verified: token.is_verified === true ? "ja" : token.is_verified === false ? "nein" : "-",
    risiko: token.risk_status ?? "-",
    score: token.organic_score_label ?? token.organic_score ?? "-",
    preis_usd: token.usd_price ?? "-",
    liquidity_usd: token.liquidity_usd ?? "-",
    fundstellen: Array.isArray(token.discovered_sources) ? token.discovered_sources.join(", ") : "",
    refreshed: token.refreshed_at ? formatDateTime(String(token.refreshed_at)) : "-"
  }));
  return (
    <div className="panel formPanel">
      <div className="panelToolbar">
        <strong>Jupiter Token API</strong>
        <span className={`statusPill ${metadataCache?.configured === false || result?.configured === false ? "warning" : metadataCache?.status === "ok" || result?.status === "ok" ? "ok" : "neutral"}`}>
          {metadataCache?.configured === false || result?.configured === false ? "Key fehlt" : metadataCache?.status ?? result?.status ?? "bereit"}
        </span>
      </div>
      <div className="metricGrid compact">
        <Metric title="Mint-Kandidaten" value={String(metadataCache?.candidates_count ?? 0)} />
        <Metric title="Gecacht" value={String(metadataCache?.cached_count ?? 0)} />
        <Metric title="Offen" value={String(metadataCache?.uncached_count ?? 0)} />
        <Metric title="Letzter Lauf" value={metadataCache?.generated_at ? formatDateTime(metadataCache.generated_at) : "-"} />
      </div>
      <div className="formGrid">
        <label>
          API Key
          <input
            value={apiKey}
            type="password"
            autoComplete="off"
            placeholder="x-api-key"
            onChange={(event) => setApiKey(event.target.value)}
          />
        </label>
        <label>
          Token Suche
          <input
            value={query}
            placeholder="Symbol, Name oder Mint"
            onChange={(event) => onQueryChange(event.target.value)}
          />
        </label>
      </div>
      <div className="formActions">
        <button type="button" onClick={() => onSaveApiKey(apiKey)} disabled={!apiKey.trim()}>
          <Settings size={16} />
          <span>Key speichern</span>
        </button>
        <button type="button" onClick={() => onSearch(query)} disabled={!query.trim()}>
          <RefreshCcw size={16} />
          <span>Token suchen</span>
        </button>
        <button type="button" onClick={() => onRefreshMetadataCache(50, false)}>
          <Database size={16} />
          <span>Wallet-Mints anreichern</span>
        </button>
        <button type="button" className="secondary" onClick={() => onRefreshMetadataCache(50, true)}>
          <RefreshCcw size={16} />
          <span>Cache erneuern</span>
        </button>
      </div>
      <TablePanel
        title="Jupiter Metadata-Cache"
        rows={cacheRows}
        compact
        footer={
          metadataCache
            ? `Kandidaten: ${metadataCache.candidates_count ?? 0} | Gecacht: ${metadataCache.cached_count ?? 0} | Offen: ${metadataCache.uncached_count ?? 0} | Read-only Metadata`
            : "Noch kein Cache geladen"
        }
      />
      <TablePanel
        title="Jupiter Token Search"
        rows={rows}
        compact
        footer={
          result
            ? `Treffer: ${result.tokens_count ?? 0} | Query: ${result.query ?? "-"} | ${result.source_url ?? ""}`
            : "Read-only Suche ueber https://api.jup.ag/tokens/v2/search"
        }
      />
    </div>
  );
}

function LocalAiYearPackageQaPanel({
  report,
  onDownload
}: {
  report: Snapshot["localAiYearPackageQa"];
  onDownload: (path: string) => void;
}) {
  const years = report?.years ?? [];
  const review = String(report?.local_ai_review_md ?? "");
  return (
    <div className="panel">
      <div className="panelToolbar">
        <strong>Lokale KI Jahrespaket-QA</strong>
        <span className={`statusPill ${report?.status === "ok" ? "ok" : report?.status === "missing" ? "warning" : "blocked"}`}>
          {String(report?.status ?? "-")}
        </span>
      </div>
      <div className="portfolioSummaryStrip">
        <Metric title="LLM" value={String(report?.llm_status ?? "-")} />
        <Metric title="Findings" value={String(report?.findings_count ?? 0)} />
        <Metric title="Jahre" value={String(years.length)} />
        <Metric title="Letzter Lauf" value={String(report?.latest_run_id ?? "-")} />
      </div>
      <div className="reportActionBand compactActions">
        <button type="button" onClick={() => onDownload("/api/v1/ai/local-year-package-qa/artifacts/summary")}>
          <FileDown size={16} />
          Summary
        </button>
        <button type="button" onClick={() => onDownload("/api/v1/ai/local-year-package-qa/artifacts/review")}>
          <FileDown size={16} />
          KI-Review
        </button>
        <button type="button" onClick={() => onDownload("/api/v1/ai/local-year-package-qa/artifacts/findings")}>
          <FileJson size={16} />
          Findings
        </button>
        <button type="button" onClick={() => onDownload("/api/v1/ai/local-year-package-qa/artifacts/run-status")}>
          <FileJson size={16} />
          Run-Status
        </button>
      </div>
      <TablePanel
        title="Jahrespaket-Pruefung"
        rows={years.map((year) => ({
          jahr: year.year,
          export_ready: year.export_ready,
          zip_dateien: year.zip_file_count,
          manifest_dateien: year.manifest_file_count,
          tax_line_jahre: Array.isArray(year.tax_line_years) ? year.tax_line_years.join(", ") || "-" : "-",
          findings: year.findings_count
        }))}
        footer={report?.methodology ?? "Lokale KI-QA Status wird geladen."}
        compact
      />
      {review ? (
        <pre className="asciiTable" aria-label="Lokale KI Review">
          {review.slice(0, 5000)}
        </pre>
      ) : null}
    </div>
  );
}

function AiTaskForm({
  onCreateAiTask
}: {
  onCreateAiTask: (taskType: string, prompt: string, allowExternal: boolean) => void;
}) {
  const [taskType, setTaskType] = useState("review");
  const [prompt, setPrompt] = useState("Pruefe die aktuelle Steuerreport-V2-Datenlage auf Risiken.");
  const [allowExternal, setAllowExternal] = useState(false);
  return (
    <div className="panel formPanel">
      <div className="panelToolbar">
        <strong>KI-Aufgabe erstellen</strong>
        <button type="button" onClick={() => onCreateAiTask(taskType, prompt, allowExternal)}>
          Erstellen
        </button>
      </div>
      <div className="formGrid">
        <label>
          Typ
          <select value={taskType} onChange={(event) => setTaskType(event.target.value)}>
            <option value="review">Review</option>
            <option value="risk_scan">Risk Scan</option>
            <option value="import_mapping">Import Mapping</option>
            <option value="documentation">Dokumentation</option>
          </select>
        </label>
        <label className="checkboxLabel">
          <input
            type="checkbox"
            checked={allowExternal}
            onChange={(event) => setAllowExternal(event.target.checked)}
          />
          Externe KI erlauben
        </label>
      </div>
      <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} />
    </div>
  );
}

function readFileBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Datei konnte nicht gelesen werden"));
    reader.onload = () => {
      const result = String(reader.result ?? "");
      resolve(result.includes(",") ? result.split(",")[1] : result);
    };
    reader.readAsDataURL(file);
  });
}

function PreflightResultPanel({ result }: { result: Record<string, unknown> }) {
  const endpoint = String(result.endpoint ?? "");
  if (endpoint.includes("/sources/binance/earn-history-preflight")) {
    const products = asRows(result.products);
    return (
      <div className="preflightResult">
        <div className="panelToolbar">
          <strong>Binance Earn Preflight</strong>
          <span>{formatDateTime(result.generated_at)}</span>
        </div>
        <div className="reviewSummary">
          <Metric title="Produkte" value={String(products.length)} />
          <Metric title="Covered" value={String(result.covered_products ?? 0)} />
          <Metric title="Partial" value={String(result.partial_products ?? 0)} />
          <Metric title="Missing" value={String(result.missing_products ?? 0)} />
        </div>
        <TablePanel
          title="Earn-Produkte"
          rows={products.map((product) => ({
            asset: product.asset,
            account_type: product.account_type,
            product_id: product.product_id,
            position_id: product.position_id,
            live_quantity: product.live_quantity,
            live_value_eur: product.live_value_eur,
            import_status: product.import_status,
            required_movements: Array.isArray(product.required_movements) ? product.required_movements.join(", ") : "",
            evidence_refs: Array.isArray(product.evidence_refs) ? product.evidence_refs.join(" | ") : "",
            next_action: product.next_action
          }))}
          footer={String(result.methodology ?? "")}
          compact
        />
      </div>
    );
  }
  if (endpoint.includes("/import/solscan/evidence-trace")) {
    const preflight = result.preflight as Record<string, unknown> | undefined;
    const refs = Array.isArray(result.evidence_refs) ? result.evidence_refs : [];
    return (
      <div className="preflightResult">
        <div className="panelToolbar">
          <strong>Solana Evidence Trace</strong>
          <span>{String(result.status ?? "-")}</span>
        </div>
        <div className="reviewSummary">
          <Metric title="Asset" value={String(result.asset ?? "-")} />
          <Metric title="Fehlend" value={String(result.missing_signatures ?? 0)} />
          <Metric title="RPC verifiziert" value={String(result.verified_signatures ?? 0)} />
          <Metric title="RPC Delta" value={formatQuantity(result.quantity_delta_sum ?? 0)} />
          <Metric title="Importeffekt" value={String(result.import_effect ?? "none")} />
          <Metric title="Schreibt Daten" value={result.target_changed === true ? "ja" : "nein"} />
        </div>
        <TablePanel
          title="Belegspur"
          rows={asRows(result.trace_steps).map((step) => ({
            step: step.label,
            status: step.status,
            evidence_ref: step.evidence_ref,
            import_effect: step.import_effect,
            note: step.note
          }))}
          footer={String(result.methodology ?? "")}
          compact
        />
        <TablePanel
          title="Coverage Snapshot"
          rows={[
            {
              matched_signatures: preflight?.matched_signatures,
              blockpit_missing_signatures: preflight?.blockpit_missing_signatures,
              solscan_extra_signatures: preflight?.solscan_extra_signatures,
              review_scope: result.review_scope,
              review_suggestion_id: result.review_suggestion_id
            }
          ]}
          footer={`Evidence-Refs: ${refs.map((ref) => String(ref)).join(" | ")}`}
          compact
        />
      </div>
    );
  }
  if (endpoint.includes("/import/solscan/token-preflight")) {
    const solscan = result.solscan as Record<string, unknown> | undefined;
    const blockpit = result.blockpit as Record<string, unknown> | undefined;
    const rpcEvidence = result.rpc_evidence as Record<string, unknown> | undefined;
    return (
      <div className="preflightResult">
        <div className="panelToolbar">
          <strong>Solscan Token Coverage</strong>
          <span>{String(result.asset ?? "-")}</span>
        </div>
        <div className="reviewSummary">
          <Metric title="Matched" value={String(result.matched_signatures ?? 0)} />
          <Metric title="Blockpit fehlt" value={String(result.blockpit_missing_signatures ?? 0)} />
          <Metric title="Solscan extra" value={String(result.solscan_extra_signatures ?? 0)} />
          <Metric title="Delta Menge" value={formatQuantity(result.matched_quantity_delta ?? 0)} />
          <Metric title="Schreibt Daten" value={result.target_changed === true ? "ja" : "nein"} />
        </div>
        <TablePanel
          title="Coverage-Vergleich"
          rows={[
            {
              source: "Solscan",
              rows: solscan?.rows,
              signatures: solscan?.signatures,
              incoming_quantity: solscan?.incoming_quantity,
              outgoing_quantity: solscan?.outgoing_quantity,
              net_quantity: solscan?.net_quantity
            },
            {
              source: "Blockpit",
              rows: blockpit?.rows,
              signatures: blockpit?.signatures,
              incoming_quantity: blockpit?.incoming_quantity,
              outgoing_quantity: blockpit?.outgoing_quantity,
              net_quantity: blockpit?.net_quantity
            },
            {
              source: "RPC Evidence",
              status: rpcEvidence?.status,
              signatures_total: rpcEvidence?.signatures_total,
              verified: rpcEvidence?.verified,
              failed: rpcEvidence?.failed,
              quantity_delta_sum: rpcEvidence?.quantity_delta_sum
            }
          ]}
          footer={`Wallet: ${shortAccount(String(result.wallet ?? ""))} | Token: ${shortAccount(String(result.token_address ?? ""))}`}
          compact
        />
        <TablePanel
          title="Fehlende Signaturgruppen"
          rows={asRows(result.missing_summary)}
          footer="Diese Gruppen dienen als Kandidaten fuer RPC-Belege oder Importabdeckungsarbeit."
          compact
        />
      </div>
    );
  }
  return (
    <TablePanel
      title="Preflight-Ergebnis"
      rows={summarizePreflightResult(result)}
      footer="Detaildaten bleiben im jeweiligen API-Endpoint nachvollziehbar."
      compact
    />
  );
}

function BinanceHarvestResultPanel({ result }: { result: Record<string, unknown> }) {
  const preview = (result.preview ?? result.import_preview) as Record<string, unknown> | undefined;
  const apiPreview = result.api_preview as Record<string, unknown> | undefined;
  const batch = result.batch as Record<string, unknown> | undefined;
  const run = result.run as Record<string, unknown> | undefined;
  const pipeline = run?.pipeline as Record<string, unknown> | undefined;
  return (
    <div className="preflightResult">
      <div className="reviewSummary">
        <Metric title="API Records" value={String(apiPreview?.records_returned ?? preview?.records_total ?? 0)} />
        <Metric title="Records gesamt" value={String(preview?.records_total ?? 0)} />
        <Metric title="Vorbereitet" value={String(preview?.rows_prepared ?? 0)} />
        <Metric title="Importierbar" value={preview?.can_execute === true ? "ja" : "nein"} />
        <Metric title="Batch" value={String(batch?.batch_id ?? "-")} />
      </div>
      <TablePanel
        title="Harvest Preview"
        rows={[
          {
            harvest_path: preview?.harvest_path,
            can_execute: preview?.can_execute,
            blocked_reason: preview?.blocked_reason,
            duplicate_batch_id: preview?.duplicate_batch_id,
            assets: Array.isArray(preview?.assets) ? preview.assets.join(", ") : "",
            api_assets: Array.isArray(apiPreview?.assets) ? apiPreview.assets.join(", ") : "",
            api_truncated: apiPreview?.truncated,
            warnings: Array.isArray(preview?.warnings) ? preview.warnings.join(" | ") : ""
          },
          {
            record_types: preview?.record_types
          }
        ]}
        footer="execute=false prueft nur. Erst execute=true importiert neue Records als binance_simple_earn_api."
        compact
      />
      {run ? (
        <TablePanel
          title="Harvest Import Run"
          rows={[
            {
              batch_id: run.batch_id,
              imported_rows: run.imported_rows,
              normalized_events: run.normalized_events,
              skipped_raw_objects: run.skipped_raw_objects,
              balance_entries: pipeline?.balance_entries,
              tax_lines: pipeline?.tax_lines,
              review_issues_open: pipeline?.review_issues_open,
              allow_export: pipeline?.allow_export
            }
          ]}
          footer="Nach einem Import wurden Normalisierung und Pipeline-Rebuild ueber den spezialisierten Service ausgefuehrt."
          compact
        />
      ) : null}
    </div>
  );
}

function SolanaRpcProbeResultPanel({ result }: { result: Record<string, unknown> }) {
  const jobs = Array.isArray(result.jobs) ? result.jobs as Array<Record<string, unknown>> : [];
  return (
    <div className="preflightResult">
      <div className="reviewSummary">
        <Metric title="Angefragt" value={String(result.requested_signatures ?? jobs.length)} />
        <Metric title="Versucht" value={String(result.attempted ?? 0)} />
        <Metric title="Verifiziert" value={String(result.verified ?? 0)} />
        <Metric title="Fehler" value={String(result.failed ?? 0)} />
        <Metric title="Rate Limit" value={String(result.rate_limited ?? 0)} />
        <Metric title="Schreibt Daten" value={result.target_changed === true ? "ja" : "nein"} />
      </div>
      <TablePanel
        title="RPC Evidence"
        rows={jobs.map((job) => ({
          signature: shortAccount(String(job.signature ?? "")),
          status: job.status,
          expected_quantity: job.expected_quantity,
          wallet_delta_quantity: job.wallet_delta_quantity,
          quantity_delta: job.quantity_delta,
          block_time: job.block_time,
          slot: job.slot,
          label: job.label,
          reason: job.reason
        }))}
        footer="Read-only RPC-Probe: externe Abfrage, kein Import und keine Aenderung an V2-Steuerdaten."
        compact
      />
    </div>
  );
}

function harvestCanExecute(result: Record<string, unknown> | null): boolean {
  const preview = (result?.preview ?? result?.import_preview) as Record<string, unknown> | undefined;
  return preview?.can_execute === true;
}

function summarizePreflightResult(result: Record<string, unknown>): Array<Record<string, unknown>> {
  const rows: Array<Record<string, unknown>> = [
    {
      label: result.label,
      endpoint: result.endpoint,
      status: "geladen"
    }
  ];
  const scalarKeys = [
    "source_id",
    "credential_status",
    "records_returned",
    "records_available_hint",
    "truncated",
    "products_count",
    "file_path",
    "wallet",
    "asset",
    "matched_signatures",
    "blockpit_missing_signatures",
    "solscan_extra_signatures",
    "matched_quantity_delta",
    "target_changed",
    "parser_needed",
    "inspected"
  ];
  const scalars: Record<string, unknown> = {};
  for (const key of scalarKeys) {
    if (result[key] !== undefined && typeof result[key] !== "object") {
      scalars[key] = result[key];
    }
  }
  if (Object.keys(scalars).length > 0) {
    rows.push(scalars);
  }
  for (const key of ["products", "requests", "records", "missing_summary", "coverage_checkpoints", "files"]) {
    const value = result[key];
    if (Array.isArray(value)) {
      rows.push({ field: key, rows: value.length });
    }
  }
  const methodology = result.methodology;
  if (typeof methodology === "string") {
    rows.push({ field: "methodology", value: methodology });
  }
  return rows;
}

function TablePanel({
  title,
  rows,
  footer,
  actionLabel,
  onAction,
  rowActions,
  compact = false
}: {
  title: string;
  rows: Array<Record<string, unknown>>;
  footer?: string;
  actionLabel?: string;
  onAction?: () => void;
  compact?: boolean;
  rowActions?: Array<{
    label: string;
    icon: React.ReactNode;
    tone?: "danger" | "default";
    onClick: (row: Record<string, unknown>) => void;
  }>;
}) {
  const columns = Array.from(
    new Set(rows.flatMap((row) => Object.keys(row).filter((key) => !key.endsWith("_full"))))
  ).slice(0, 8);
  const hasRowActions = rowActions !== undefined && rowActions.length > 0;
  return (
    <div className={`panel ${compact ? "compactTablePanel" : ""}`}>
      <div className="panelToolbar">
        <strong>{title}</strong>
        {actionLabel ? (
          <button type="button" onClick={onAction}>
            {actionLabel}
          </button>
        ) : null}
      </div>
      {rows.length === 0 ? (
        <div className="empty">Keine Daten vorhanden.</div>
      ) : (
        <div className="tableWrap">
          <table>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th key={column}>{column}</th>
                ))}
                {hasRowActions ? <th className="actionColumn">Aktion</th> : null}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr key={index}>
                  {columns.map((column) => {
                    const value = formatValue(row[column], column);
                    return (
                      <td key={column} title={fullValue(row[column])} className={cellClass(column)}>
                        {value}
                      </td>
                    );
                  })}
                  {hasRowActions ? (
                    <td className="actionCell">
                      <div className="rowActions">
                        {rowActions.map((action) => (
                          <button
                            key={action.label}
                            type="button"
                            className={`iconButton ${action.tone === "danger" ? "danger" : ""}`}
                            onClick={() => action.onClick(row)}
                            title={action.label}
                          >
                            {action.icon}
                          </button>
                        ))}
                      </div>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {footer ? <div className="footer">{footer}</div> : null}
    </div>
  );
}

function KeyValuePanel({ title, data }: { title: string; data: Record<string, unknown> }) {
  return (
    <TablePanel
      title={title}
      rows={Object.entries(data).map(([key, value]) => ({
        key,
        value: formatValue(value, key)
      }))}
    />
  );
}

function Metric({ title, value }: { title: string; value: string }) {
  return (
    <div className="metric">
      <span>{title}</span>
      <strong>{value}</strong>
    </div>
  );
}

function positionMap(nodes: string[], height: number): Map<string, number> {
  const top = 44;
  const bottom = height - 44;
  if (nodes.length === 0) {
    return new Map();
  }
  if (nodes.length === 1) {
    return new Map([[nodes[0], height / 2]]);
  }
  const step = (bottom - top) / (nodes.length - 1);
  return new Map(nodes.map((node, index) => [node, top + step * index]));
}

function parseNumber(value: unknown): number {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

function parseMagnitude(value: unknown): number {
  return Math.abs(parseNumber(value));
}

function formatCurrency(value: unknown): string {
  return parseNumber(value).toLocaleString("de-DE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
}

function formatAmount(value: unknown): string {
  return parseNumber(value).toLocaleString("de-DE", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 8
  });
}

function priorityTone(value: unknown): "ok" | "warning" | "blocked" {
  const priority = String(value ?? "");
  if (priority === "high") {
    return "blocked";
  }
  if (priority === "medium") {
    return "warning";
  }
  return "ok";
}

function declarationTopicTone(value: string): "ok" | "warning" | "blocked" {
  if (value === "private_disposal" || value === "income") {
    return "warning";
  }
  if (value === "review") {
    return "blocked";
  }
  if (value === "appendix") {
    return "warning";
  }
  return "ok";
}

function reportYearFilingTone(value: string): "ok" | "warning" | "blocked" {
  if (value === "ready") {
    return "ok";
  }
  if (value === "blocked") {
    return "blocked";
  }
  return "warning";
}

function reportEvidenceTone(value: string): "ok" | "warning" | "blocked" {
  if (value === "complete" || value === "available") {
    return "ok";
  }
  if (value === "review") {
    return "blocked";
  }
  return "warning";
}

function declarationTopicLabel(value: string): string {
  if (value === "private_disposal") {
    return "Anlage SO";
  }
  if (value === "income") {
    return "Einkuenfte";
  }
  if (value === "derivative") {
    return "Derivate";
  }
  if (value === "tax_free") {
    return "Steuerfrei";
  }
  if (value === "appendix") {
    return "Herkunft";
  }
  if (value === "review") {
    return "Pruefen";
  }
  return "Beleg";
}

function formatQuantity(value: unknown): string {
  return parseNumber(value).toLocaleString("de-DE", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 8
  });
}

function formatStatusCounts(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return "-";
  }
  const entries = Object.entries(value as Record<string, unknown>)
    .map(([status, count]) => ({ status, count: parseNumber(count) }))
    .filter((entry) => entry.count > 0)
    .sort((left, right) => right.count - left.count || left.status.localeCompare(right.status));
  if (entries.length === 0) {
    return "-";
  }
  return entries.map((entry) => `${entry.status}:${entry.count}`).join(" · ");
}

function formatPercent(value: unknown): string {
  return `${parseNumber(value).toLocaleString("de-DE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  })}%`;
}

function formatDateTime(value: unknown): string {
  if (!value) {
    return "-";
  }
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString("de-DE", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC"
  });
}

function flowColor(index: number): string {
  const colors = ["#1f6f8b", "#9b4d3d", "#347a45", "#7a5c9e", "#b8792f", "#4f6f9f"];
  return colors[index % colors.length];
}

function tokenDisplay(row: Record<string, unknown>): string {
  const symbol = String(row.token_symbol ?? row.asset ?? "").trim();
  const name = String(row.token_name ?? "").trim();
  if (name && symbol && name.toUpperCase() !== symbol.toUpperCase()) {
    return `${symbol} · ${name}`;
  }
  return symbol || String(row.asset ?? "-");
}

function tokenRiskTone(status: unknown): string {
  const value = String(status ?? "");
  if (value === "verified") {
    return "ok";
  }
  if (value === "spam_review") {
    return "blocked";
  }
  if (value) {
    return "warning";
  }
  return "neutral";
}

function tokenMeta(row: Record<string, unknown>): string {
  const risk = String(row.token_risk_status ?? "");
  const mint = String(row.token_mint ?? "");
  const verified = row.token_verified === true ? "verified" : row.token_verified === false ? "unverified" : "";
  return [risk, verified, mint ? shortAccount(mint) : ""].filter(Boolean).join(" · ") || "-";
}

function formatValue(value: unknown, column?: string): string {
  if (value === null || value === undefined) {
    return "-";
  }
  if (typeof value === "string" && looksLikeAddressColumn(column)) {
    return shortAccount(value);
  }
  if (shouldFormatAsQuantity(value, column)) {
    return formatQuantity(value);
  }
  if (shouldFormatAsFixedNumber(value, column)) {
    return formatCurrency(value);
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function fullValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "-";
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function cellClass(column?: string): string {
  const normalized = String(column ?? "").toLowerCase();
  if (looksLikeAddressColumn(column)) {
    return "monoCell addressCell";
  }
  if (normalized.includes("eur") || normalized.includes("value") || normalized.includes("price")) {
    return "numericCell";
  }
  if (normalized.includes("quantity") || normalized.includes("amount") || normalized.includes("balance")) {
    return "numericCell";
  }
  return "";
}

function asRows(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => (
        typeof item === "object" && item !== null && !Array.isArray(item)
      ))
    : [];
}

function formatAssetMap(value: Record<string, unknown>): string {
  const entries = Object.entries(value);
  if (entries.length === 0) {
    return "";
  }
  return entries
    .map(([asset, amount]) => `${asset}: ${formatValue(amount, "quantity")}`)
    .join(" | ");
}

function shortAccount(value: string): string {
  if (value.length <= 22) {
    return value;
  }
  return `${value.slice(0, 10)}...${value.slice(-8)}`;
}

function shouldFormatAsFixedNumber(value: unknown, column?: string): boolean {
  if (typeof value === "number") {
    return Number.isFinite(value) && isDisplayNumericColumn(column);
  }
  if (typeof value !== "string" || !isDisplayNumericColumn(column)) {
    return false;
  }
  return /^-?\d+(\.\d+)?$/.test(value.trim());
}

function shouldFormatAsQuantity(value: unknown, column?: string): boolean {
  if (!column) {
    return false;
  }
  const normalized = column.toLowerCase();
  if (normalized.includes("eur") || normalized.includes("price") || normalized.includes("value")) {
    return false;
  }
  if (!["quantity", "amount", "balance"].some((token) => normalized.includes(token))) {
    return false;
  }
  if (typeof value === "number") {
    return Number.isFinite(value);
  }
  return typeof value === "string" && /^-?\d+(\.\d+)?(e-?\d+)?$/i.test(value.trim());
}

function looksLikeAddressColumn(column?: string): boolean {
  if (!column) {
    return false;
  }
  const normalized = column.toLowerCase();
  return ["account", "wallet", "address", "tx_id", "signature"].some((token) => normalized.includes(token));
}

function isDisplayNumericColumn(column?: string): boolean {
  if (!column) {
    return false;
  }
  const normalized = column.toLowerCase();
  return [
    "eur",
    "value",
    "price",
    "quantity",
    "amount",
    "total",
    "gross",
    "fee",
    "pnl",
    "confidence",
    "difference",
    "delta",
    "balance",
    "rate"
  ].some((token) => normalized.includes(token));
}

createRoot(document.getElementById("root") as HTMLElement).render(<App />);
