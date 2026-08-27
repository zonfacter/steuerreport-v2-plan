import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  AlertTriangle,
  Archive,
  ArrowRight,
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
  LockKeyhole,
  Menu,
  PackageCheck,
  ReceiptText,
  RefreshCcw,
  Route,
  Scale,
  Settings,
  ShieldCheck,
  Smartphone,
  Trash2,
  Upload,
  WalletCards,
  X
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

type BitgetBasisDecisionPayload = {
  decision:
    | "retain_provider_gap_pending_professional_review"
    | "approve_zero_basis_estimate_for_staging"
    | "approve_settlement_value_proxy_estimate_for_staging"
    | "rejected_requires_rework";
  rationale: string;
  actor: string;
  acknowledge_provider_fill_data_missing: true;
  acknowledge_estimate_not_observed_transaction: true;
  acknowledge_consistent_application: true;
  acknowledge_no_automatic_tax_effect: true;
  acknowledge_professional_review_before_filing: true;
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

type DivorceValuationGate = {
  valuation_at: string;
  materiality_threshold_eur: string;
  positions_count: number;
  material_positions_count: number;
  same_day_price_count: number;
  prior_day_price_count: number;
  stale_price_count: number;
  missing_price_count: number;
  review_asset_count: number;
  accepted_review_asset_count: number;
  strict_ready: boolean;
  status: string;
  affected_assets: string[];
  accepted_review_assets: string[];
  token_review_evidence_refs: string[];
  findings: string[];
};

type AsOfPriceGateCandidate = {
  asset: string;
  accounts: string[];
  quantity: string;
  value_eur: string;
  current_price_eur?: string | null;
  current_priced_at?: string | null;
  current_price_source?: string | null;
  current_price_age_days?: number | null;
  current_price_status: string;
  provider_id?: string | null;
  token_mint?: string | null;
  token_verified?: boolean | null;
  token_risk_status?: string | null;
  token_review_status: "not_required" | "pending" | "accepted";
  token_review_decision_id?: string | null;
  token_review_evidence_ref?: string | null;
  status: string;
  reason: string;
};

type AsOfPriceGateReport = {
  generated_at: string;
  as_of: string;
  materiality_threshold_eur: string;
  strict_ready: boolean;
  status: string;
  material_assets_count: number;
  requirements_count: number;
  fetchable_count: number;
  review_only_count: number;
  not_configured_count: number;
  candidates: AsOfPriceGateCandidate[];
  gate: DivorceValuationGate;
  methodology: string;
};

type DivorceCapitalFlowGate = {
  cutoff_at: string;
  valuation_at: string;
  materiality_threshold_eur: string;
  opening_value_eur: string;
  closing_value_eur: string;
  confirmed_contributions_eur: string;
  provisional_contributions_eur: string;
  total_contributions_eur: string;
  confirmed_external_distributions_eur: string;
  review_outflow_value_eur: string;
  internal_transfer_value_eur: string;
  internal_service_position_loss_value_eur: string;
  technical_fee_value_eur: string;
  operational_adjustment_value_eur: string;
  flow_adjusted_change_eur: string;
  flow_adjusted_change_if_all_review_outflows_are_external_eur: string | null;
  outflows_count: number;
  internal_outflows_count: number;
  confirmed_service_position_loss_count: number;
  confirmed_external_distributions_count: number;
  material_review_outflows_count: number;
  unpriced_review_outflows_count: number;
  capital_origin_pending_count: number;
  strict_ready: boolean;
  status: "blocked" | "review" | "strict_ready";
  contributions: Array<Record<string, unknown>>;
  outflows: Array<Record<string, unknown>>;
  findings: string[];
  methodology: string;
};

type DivorceServiceRouteEvidenceReport = {
  generated_at: string;
  status: "ready_for_review" | "review_required" | "failed";
  strict_ready: boolean;
  end_asset_date: string;
  tx_id: string;
  canonical_event_id?: string | null;
  wallet?: string | null;
  wallet_source_id?: string | null;
  collateral_quantity?: string | null;
  collateral_added_usd?: string | null;
  position_account?: string | null;
  liquidation_tx_id?: string | null;
  liquidation_block_time?: string | null;
  liquidation_instruction?: string | null;
  liquidation_net_loss_usd?: string | null;
  residual_position_account_quantity?: string | null;
  residual_position_account_value_eur?: string | null;
  semantic_sha256: string;
  evidence_files: Array<{
    kind: string;
    path: string;
    size_bytes: number;
    sha256: string;
  }>;
  errors: string[];
  findings: string[];
  methodology: string;
};

type DivorceInheritanceOriginGate = {
  generated_at: string;
  separation_date: string;
  end_asset_date: string;
  status: "blocked" | "review" | "strict_ready";
  strict_ready: boolean;
  bank_statement_status: "missing" | "partial" | "complete";
  bank_statement_from?: string | null;
  bank_statement_to?: string | null;
  bank_files_count: number;
  opening_balance_eur?: string | null;
  end_asset_closing_balance_eur?: string | null;
  minimum_closing_balance_after_inheritance_eur?: string | null;
  inheritance_credit?: Record<string, unknown> | null;
  inheritance_credits: Array<{
    booking_date: string;
    amount_eur: string;
    evidence_status: "bank_primary_evidence" | "review";
    evidence_source: "bank_camt" | "supporting_document";
    date_basis: "bank_booking_date" | "document_date";
    credit_kind: "estate_account_transfer" | "estate_asset_realization" | "estate_refund";
    classification_source: "camt_marker" | "review_decision";
    transaction_reference_sha256: string;
    evidence_ref: string;
    supporting_evidence_ref?: string | null;
    review_decision_id?: string | null;
    note: string;
  }>;
  inheritance_credit_count: number;
  inheritance_credit_eur: string;
  user_declaration_status: "missing" | "recorded";
  formal_inheritance_document_status: "missing" | "documented";
  formal_inheritance_connector: {
    document_root: string;
    document_files_count: number;
    document_manifest_sha256?: string | null;
    status: "missing" | "candidate_present" | "reviewed";
    review_ready: boolean;
    accepted_document_sha256?: string | null;
    accepted_evidence_ref?: string | null;
    documents: Array<{
      document_sha256: string;
      media_type: "application/pdf" | "image/jpeg" | "image/png";
      size_bytes: number;
      source_kind: "configured_path" | "managed_upload";
      review_status: "candidate" | "reviewed";
      evidence_ref: string;
    }>;
    note: string;
  };
  bank_identified_investment_eur: string;
  platform_only_investment_eur: string;
  total_identified_investment_eur: string;
  declared_inheritance_headroom_eur?: string | null;
  crypto_tracked_investment_eur: string;
  external_asset_investment_eur: string;
  external_asset_end_value_eur?: string | null;
  external_asset_gain_loss_eur?: string | null;
  provider_summaries: Array<Record<string, unknown>>;
  investment_flows: Array<Record<string, unknown>>;
  sparkasse_statement_connector?: {
    status: "missing" | "parsed" | "partial" | "failed";
    document_files_count: number;
    parsed_documents_count: number;
    parse_error_count: number;
    period_from?: string | null;
    period_to?: string | null;
    crypto_debits_count: number;
    crypto_debits_eur: string;
    exact_camt_matches_count: number;
    ambiguous_camt_matches_count: number;
    missing_camt_matches_count: number;
    duplicate_investment_flows_prevented_count: number;
    calculation_effect: "corroboration_only_no_duplicate_flow";
    findings: string[];
    methodology: string;
  };
  trade_republic_connector: Record<string, unknown> & {
    official_psd2_api_available?: boolean;
    direct_retail_api_available?: boolean;
    access_model?: string;
    confirmed_api_scope?: string;
    selected_ingestion_mode?: string;
    document_files_count?: number;
    document_parse_status?: "missing" | "parsed" | "partial" | "failed";
    parsed_documents_count?: number;
    parse_error_count?: number;
    exact_date_documents_count?: number;
    valuation_candidates_count?: number;
    end_asset_statement_status?: string;
    valuation_review_status?: "missing" | "ready" | "ambiguous" | "reviewed";
    valuation_review_ready?: boolean;
    candidate_end_asset_value_eur?: string | null;
    candidate_cash_value_eur?: string | null;
    candidate_securities_value_eur?: string | null;
    candidate_document_sha256?: string | null;
    accepted_end_asset_value_eur?: string | null;
    accepted_evidence_ref?: string | null;
    documents?: Array<{
      document_sha256: string;
      container_sha256?: string | null;
      source_kind: string;
      document_type: string;
      extraction_status: string;
      statement_date?: string | null;
      period_from?: string | null;
      period_to?: string | null;
      end_asset_date_match_source: string;
      cash_value_eur?: string | null;
      securities_value_eur?: string | null;
      total_value_eur?: string | null;
      valuation_status: string;
      evidence_ref: string;
      findings: string[];
    }>;
    required_documents?: string[];
    official_api_guide_url?: string;
    official_statement_help_url?: string;
    note?: string;
  };
  coinbase_connector: {
    official_accounts_api_url: string;
    official_transactions_api_url: string;
    official_statements_help_url: string;
    credential_status: "configured" | "missing";
    latest_live_snapshot_at?: string | null;
    latest_live_assets_count: number;
    history_batches_count: number;
    history_events_count: number;
    history_from?: string | null;
    history_to?: string | null;
    history_manifest_sha256?: string | null;
    history_status: "missing" | "imported_pending_review" | "reviewed";
    valuation_review_ready: boolean;
    candidate_end_asset_value_eur?: string | null;
    accepted_end_asset_value_eur?: string | null;
    accepted_evidence_ref?: string | null;
    missing_price_assets: string[];
    negative_quantity_assets: string[];
    assets: Array<{
      asset: string;
      quantity: string;
      value_eur?: string | null;
      price_source?: string | null;
      priced_at?: string | null;
    }>;
    note: string;
  };
  findings: string[];
  next_actions: string[];
  semantic_sha256: string;
  methodology: string;
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
    portfolio_performance: {
      display_value_eur: string;
      display_value_basis: string;
      live_value_eur: string | null;
      calculated_value_eur: string;
      open_cost_basis_eur: string;
      unrealized_return_eur: string;
      unrealized_return_pct: string | null;
      net_fiat_invested_eur: string;
      cost_basis_status: string;
      detail: string;
    };
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
  productReadiness?: {
    generated_at: string;
    overall_status: string;
    can_prepare_tax_report: boolean;
    can_file_without_review: boolean;
    headline: string;
    next_action: string;
    next_action_path: string;
    checks: Array<Record<string, unknown>>;
    sources: Array<Record<string, unknown>>;
    ready_years: number[];
    conservative_ready_years: number[];
    review_years: number[];
    blocked_years: number[];
    setup_required_sources: number;
    review_items_count: number;
    blocking_items_count: number;
    methodology: string;
  };
  connectorCatalog?: {
    generated_at: string;
    security: {
      auth_mode: "disabled" | "setup_token" | "oidc";
      connector_writes_enabled: boolean;
      internet_ready: boolean;
      public_base_url?: string | null;
      owner_scope: "single_user_local" | "multi_tenant";
      vault: {
        configured: boolean;
        require_encrypted_secrets: boolean;
        key_id?: string | null;
        encrypted_secrets: number;
        plaintext_secrets: number;
        unreadable_secrets: number;
        status: "encrypted" | "migration_required" | "not_configured" | "error";
      };
      blockers: string[];
    };
    connectors: Array<{
      connector_id: string;
      label: string;
      category: string;
      auth_method: string;
      availability: string;
      connection_status: string;
      mobile_platforms: string[];
      capabilities: string[];
      required_fields: string[];
      safety_notes: string[];
      limitation?: string | null;
      last_sync_at?: string | null;
    }>;
    connections: Array<{
      connection_id: string;
      connector_id: string;
      external_identifier: string;
      display_label: string;
      source_id?: string | null;
      status: string;
      created_at: string;
      verified_at?: string | null;
      revoked_at?: string | null;
      last_sync_at?: string | null;
      tax_activation: "review_required" | "registry_active";
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
    live_nonledger_accrual_value_eur?: string;
    reconciliation_live_value_eur?: string | null;
    raw_delta_value_eur?: string | null;
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
    diagnostics: Array<Record<string, unknown> & {
      last_attempt?: {
        connector_id: string;
        attempted_at: string;
        status: string;
        snapshots_count: number;
        source?: string | null;
        message?: string | null;
      } | null;
    }>;
    missing_credentials: number;
    stale_snapshots: number;
    missing_snapshots: number;
    failed_latest_attempts: number;
    methodology: string;
  };
  sourceRegistry?: {
    generated_at: string;
    registry_version: string;
    status: string;
    strict_ready: boolean;
    entries_count: number;
    owned_entries_count: number;
    complete_entries_count: number;
    partial_entries_count: number;
    provider_coverage_gap_entries_count: number;
    user_evidence_gap_entries_count: number;
    documented_route_entries_count: number;
    observed_groups_count: number;
    unregistered_observations_count: number;
    portfolio_policy_violations_count: number;
    quantity_blocker_entries_count: number;
    ledger_adjustments_count: number;
    applied_ledger_adjustments_count: number;
    transfer_evidence_count: number;
    approved_transfer_evidence_count: number;
    entries: Array<Record<string, unknown>>;
    unregistered_observations: Array<Record<string, unknown>>;
    portfolio_policy_violations: string[];
    findings: string[];
    next_actions: string[];
    semantic_sha256: string;
    methodology: string;
  } | null;
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
    live_nonledger_accrual_value_eur?: string;
    reconciliation_live_value_eur?: string | null;
    raw_delta_value_eur?: string | null;
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
    excluded_value_semantics?: string;
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
    excluded_value_semantics?: string;
    resolved_account_aliases: Array<Record<string, unknown>>;
    unresolved_truncated_accounts: string[];
    methodology: string;
    transfer_context_note?: string | null;
  };
  portfolioValueHistory?: {
    from_date: string;
    to_date: string;
    interval: string;
    points: Array<Record<string, unknown>>;
    points_count: number;
    negative_points_count: number;
    min_total_value_eur?: string | null;
    max_total_value_eur?: string | null;
    methodology: string;
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
    ledger_adjustment_value_eur: string;
    total_reconciled_ledger_value_eur?: string | null;
    applied_ledger_adjustments_count: number;
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
    stichtage: {
      separation_date: string;
      separation_at_utc: string;
      end_asset_date: string;
      end_asset_at_utc: string;
      timezone: string;
      end_asset_legal_basis: string;
      end_asset_date_source: "user_provided";
      court_evidence_status: "pending_document" | "documented";
      court_evidence_reference?: string | null;
      court_evidence_note: string;
    };
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
    confirmed_external_invest_since_cutoff_eur: string;
    confirmed_onramp_invest_since_cutoff_eur: string;
    provisional_onramp_invest_since_cutoff_eur: string;
    adjusted_gain_loss_excluding_new_invest_eur: string;
    adjusted_gain_loss_without_review_assets_eur: string;
    cutoff_missing_price_assets: string[];
    valuation_missing_price_assets: string[];
    fiat_deposits_since_cutoff_eur: string;
    direct_eur_buys_since_cutoff_eur: string;
    eur_asset_spent_without_quote_since_cutoff_eur: string;
    inheritance_origin_gate: DivorceInheritanceOriginGate;
    capital_flow_gate: DivorceCapitalFlowGate;
    cutoff_price_gate: DivorceValuationGate;
    valuation_price_gate: DivorceValuationGate;
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
  divorceServiceRouteEvidence?: DivorceServiceRouteEvidenceReport;
  divorceValuationRun?: {
    run_id: string;
    generated_at: string;
    status: string;
    strict_ready: boolean;
    cutoff_at: string;
    valuation_at: string;
    cutoff_value_eur: string;
    valuation_value_eur: string;
    gross_change_eur: string;
    external_invest_eur: string;
    adjusted_gain_loss_eur: string;
    cutoff_price_gate: DivorceValuationGate;
    valuation_price_gate: DivorceValuationGate;
    fifo_checkpoints: Array<Record<string, unknown>>;
    source_registry_status: string;
    source_registry_strict_ready: boolean;
    source_provider_coverage_gap_count: number;
    source_user_evidence_gap_count: number;
    source_quantity_blocker_count: number;
    source_registry_semantic_sha256?: string | null;
    source_registry_report_url: string;
    source_accounts: string[];
    semantic_sha256: string;
    evidence_files: Array<Record<string, unknown>>;
    findings: string[];
    next_actions: string[];
    methodology: string;
  } | null;
  asOfPriceGate?: AsOfPriceGateReport;
  asOfCutoffPriceGate?: AsOfPriceGateReport;
  asOfPriceGateBackfill?: {
    generated_at: string;
    dry_run: boolean;
    attempted: number;
    imported_prices: number;
    skipped: number;
    failed: number;
    gate_before: Record<string, unknown>;
    gate_after: Record<string, unknown>;
    jobs: Array<Record<string, unknown>>;
    artifact_path: string;
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
  taxBmfComplianceMatrix?: {
    generated_at: string;
    matrix_version: string;
    bmf_reference: string;
    bmf_reference_url: string;
    scope_years: number[];
    strict_bmf_ready: boolean;
    strict_ready_years: number[];
    conservative_years: number[];
    review_years: number[];
    blocked_years: number[];
    requirements_count: number;
    satisfied_count: number;
    review_count: number;
    blocked_count: number;
    not_applicable_count: number;
    requirements: Array<{
      requirement_id: string;
      title: string;
      bmf_paragraphs: string[];
      requirement: string;
      implementation_status: string;
      evidence_status: string;
      strict_ready: boolean;
      affected_years: number[];
      metrics: Array<Record<string, unknown>>;
      evidence_refs: string[];
      findings: string[];
      next_action: string;
    }>;
    caveats: string[];
    methodology: string;
  };
  legalResearchFreshness?: {
    generated_at: string;
    fresh_until: string;
    registry_version: string;
    status: "fresh" | "review_required" | "error" | "stale" | "missing";
    is_fresh: boolean;
    official_sources_reachable: boolean;
    source_checks: Array<{
      source_id: string;
      title: string;
      authority: string;
      kind: string;
      url: string;
      status: "ok" | "changed" | "error";
    }>;
    monitor_checks: Array<{
      monitor_id: string;
      title: string;
      authority: string;
      status: "ok" | "error";
      hits_count: number;
      review_required_count: number;
    }>;
    changed_source_ids: string[];
    failed_check_ids: string[];
    review_required_urls: string[];
    findings: string[];
    next_actions: string[];
  };
  walletFifoParallelRun?: {
    run_id: string;
    generated_at: string;
    as_of: string;
    years: number[];
    report_schema_version: string;
    method_version: string;
    status: "blocked" | "review" | "ready_for_method_review";
    strict_ready: boolean;
    method_acceptance_required: boolean;
    material_delta_threshold_eur: string;
    semantic_sha256: string;
    input_events_count: number;
    pools_count: number;
    all_lots_count: number;
    open_lots_count: number;
    wallet_tax_lines_count: number;
    unmatched_count: number;
    provider_basis_gap_count: number;
    unexplained_unmatched_count: number;
    transfer_traces_count: number;
    unresolved_inbound_provenance_count: number;
    transfer_evidence_review_count: number;
    acquisition_cost_evidence_review_count: number;
    global_gain_loss_eur: string;
    wallet_gain_loss_eur: string;
    delta_gain_loss_eur: string;
    material_delta_years: number[];
    event_set_parity_years: number[];
    event_set_mismatch_years: number[];
    proceeds_parity_years: number[];
    valuation_review_years: number[];
    blocked_years: number[];
    review_years: number[];
    ready_for_method_review_years: number[];
    year_results: Array<{
      year: number;
      status: string;
      global_gain_loss_eur: string;
      wallet_gain_loss_eur: string;
      delta_gain_loss_eur: string;
      material_delta: boolean;
      unmatched_count: number;
      provider_basis_gap_count: number;
      unexplained_unmatched_count: number;
      unresolved_inbound_provenance_count: number;
      transfer_evidence_review_count: number;
      acquisition_cost_evidence_review_count: number;
      affected_assets: string[];
      event_set_parity: boolean;
      proceeds_parity: boolean;
      event_set_mismatch_assets: string[];
      valuation_review_assets: string[];
      explicit_fee_assets: string[];
      basis_method_delta_assets: string[];
    }>;
    evidence_files: Array<{
      kind: string;
      path: string;
      records_count: number;
      size_bytes: number;
      sha256: string;
      semantic_sha256: string;
      download_url?: string | null;
    }>;
    findings: string[];
    next_actions: string[];
    methodology: string;
  } | null;
  bitgetStrategyFifoGaps?: {
    run_id: string;
    generated_at: string;
    as_of: string;
    status: "no_gap" | "quantity_reconciled_basis_pending" | "blocked_unallocated_quantity" | "evidence_error";
    strict_ready: boolean;
    read_only: boolean;
    productive_tables_unchanged: boolean;
    quantity_reconciled: boolean;
    original_acquisition_basis_complete: boolean;
    groups_count: number;
    assets: string[];
    years: number[];
    unmatched_disposals_count: number;
    out_of_scope_bitget_unmatched_disposals_count: number;
    linked_unmatched_disposals_count: number;
    unallocated_unmatched_disposals_count: number;
    blockpit_reference_count: number;
    blockpit_classification_conflict_count: number;
    support_package: {
      status: string;
      expected_files_count: number;
      available_files_count: number;
      missing_files: string[];
      package_complete: boolean;
      additional_user_export_required: boolean;
      provider_export_field_gap: boolean;
      strategy_rows_count: number;
      spot_execution_rows_count: number;
      relevant_strategy_matches_count: number;
      strategy_linked_fill_rows_count: number;
      same_pair_window_execution_rows_count: number;
      semantic_sha256: string;
      findings: string[];
    };
    asset_totals: Array<{
      asset: string;
      groups_count: number;
      strategy_quantity_without_cost_basis: string;
      allocated_missing_quantity: string;
      residual_quantity: string;
    }>;
    api_history_boundary: {
      status: string;
      requested_year: number;
      retention_days: number;
      older_data_retrieval: string;
      finding: string;
    };
    groups: Array<{
      settlement_group_id: string;
      year: number;
      asset: string;
      pool_id: string;
      settlement_event_id: string;
      settlement_transaction_id: string;
      settlement_at: string;
      settlement_quantity: string;
      settlement_reference_value_usdt?: string | null;
      supported_principal_carried_quantity: string;
      strategy_quantity_without_cost_basis: string;
      linked_disposals_count: number;
      linked_disposal_quantity: string;
      linked_matched_wallet_lot_quantity: string;
      allocated_missing_quantity: string;
      residual_quantity: string;
      quantity_reconciled: boolean;
      quantity_equation: string;
      acquisition_time_status: string;
      acquisition_cost_status: string;
      final_tax_status: string;
      reward_classification_effect: "none";
      basis_gap_responsibility: string;
      settlement_filename?: string | null;
      settlement_row_number?: number | null;
      blockpit_reference: {
        available: boolean;
        label?: string | null;
        row_number?: number | null;
        classification_conflict: boolean;
        reward_classification_effect: "none";
        note: string;
      };
      support_strategy_match?: {
        strategy_id: string;
        strategy_row_number: number;
        asset: string;
        trading_pair: string;
        strategy_type: string;
        created_at: string;
        terminated_at: string;
        settlement_delta_seconds: string;
        investment_amount: string;
        total_gains: string;
        fee_base_asset: string;
        fee_quote_asset: string;
        same_pair_window_execution_rows_count: number;
        strategy_linked_fill_rows_count: number;
        exact_settlement_match: boolean;
      } | null;
      linked_disposals: Array<{
        settlement_group_id: string;
        source_event_id: string;
        event_time: string;
        asset: string;
        disposal_quantity: string;
        matched_wallet_lot_quantity: string;
        missing_wallet_lot_quantity: string;
        allocated_strategy_gap_quantity: string;
        quantity_fully_allocated: boolean;
        order_number?: string | null;
        quote_asset?: string | null;
        quote_quantity?: string | null;
        source_filename?: string | null;
        source_row_number?: number | null;
      }>;
    }>;
    findings: string[];
    next_actions: string[];
    semantic_sha256: string;
    methodology: string;
  } | null;
  bitgetStrategyReconstruction?: {
    run_id: string;
    generated_at: string;
    as_of: string;
    status: "no_gap" | "ready_for_professional_review" | "blocked_missing_inputs";
    strict_ready: boolean;
    read_only: boolean;
    productive_tax_effect: "none";
    provider_export_field_gap: boolean;
    support_package_complete: boolean;
    groups_count: number;
    linked_disposals_count: number;
    quantity_reconciled_groups_count: number;
    price_evidence_complete_groups_count: number;
    definitely_within_one_year_disposals_count: number;
    definitely_over_one_year_disposals_count: number;
    uncertain_holding_period_disposals_count: number;
    attributable_disposal_proceeds_total_eur: string;
    documented_cost_basis_floor_total_eur: string;
    documented_cost_basis_ceiling_total_eur?: string | null;
    settlement_value_proxy_basis_total_eur: string;
    zero_basis_gain_sensitivity_total_eur: string;
    settlement_value_proxy_gain_sensitivity_total_eur: string;
    groups: Array<{
      settlement_group_id: string;
      year: number;
      asset: string;
      strategy_id: string;
      strategy_type: string;
      acquisition_window_start: string;
      acquisition_window_end: string;
      settlement_at: string;
      allocated_missing_quantity: string;
      quantity_reconciled: boolean;
      strategy_investment_reference_usdt: string;
      strategy_reported_gain_reference_usdt: string;
      attributable_disposal_proceeds_eur?: string | null;
      documented_cost_basis_floor_eur: string;
      documented_cost_basis_ceiling_eur?: string | null;
      allocated_settlement_value_proxy_eur?: string | null;
      zero_basis_gain_sensitivity_eur?: string | null;
      settlement_value_proxy_gain_sensitivity_eur?: string | null;
      price_evidence_complete: boolean;
      basis_reconstruction_status: string;
      tax_basis_use: string;
      productive_tax_effect: "none";
      linked_disposals: Array<{
        source_event_id: string;
        event_time: string;
        asset: string;
        allocated_strategy_quantity: string;
        minimum_holding_days: string;
        maximum_holding_days: string;
        holding_period_certainty: string;
        attributable_disposal_proceeds_eur?: string | null;
        zero_basis_gain_sensitivity_eur?: string | null;
        settlement_value_proxy_basis_eur?: string | null;
        settlement_value_proxy_gain_sensitivity_eur?: string | null;
        tax_basis_status: string;
      }>;
      findings: string[];
    }>;
    findings: string[];
    next_actions: string[];
    semantic_sha256: string;
    methodology: string;
  } | null;
  bitgetStrategyBasisDecision?: {
    generated_at: string;
    run_id?: string | null;
    run_as_of?: string | null;
    run_input_fingerprint_digest?: string | null;
    current_input_fingerprint_digest?: string | null;
    input_fingerprint_current: boolean;
    gap_semantic_sha256?: string | null;
    reconstruction_semantic_sha256?: string | null;
    status: "missing" | "blocked" | "ready_for_professional_decision" | "decision_recorded";
    decision_ready: boolean;
    decision_status:
      | "pending"
      | "retain_provider_gap_pending_professional_review"
      | "approve_zero_basis_estimate_for_staging"
      | "approve_settlement_value_proxy_estimate_for_staging"
      | "rejected_requires_rework";
    selected_method: "none" | "zero_basis_estimate" | "settlement_value_proxy_estimate";
    decision_id?: string | null;
    decision_at?: string | null;
    decision_actor?: string | null;
    decision_rationale?: string | null;
    support_package_complete: boolean;
    provider_export_field_gap: boolean;
    quantity_reconciled: boolean;
    price_evidence_complete: boolean;
    holding_period_classification_complete: boolean;
    linked_disposals_count: number;
    attributable_disposal_proceeds_total_eur: string;
    selected_estimated_cost_basis_total_eur?: string | null;
    selected_estimated_gain_loss_total_eur?: string | null;
    estimate_selected_for_staging: boolean;
    strict_ready: boolean;
    staging_only: boolean;
    productive_tax_effect: "none";
    checks: Array<{
      key: string;
      label: string;
      passed: boolean;
      blocking: boolean;
      detail: string;
    }>;
    blockers: string[];
    findings: string[];
    evidence_refs: string[];
    methodology: string;
  } | null;
  walletFifoMethodDeltaExplanation?: {
    run_id: string;
    generated_at: string;
    as_of: string;
    method_version: string;
    status: "blocked" | "review" | "ready_for_method_review";
    method_acceptance_required: boolean;
    input_fingerprint_digest: string;
    semantic_sha256: string;
    years: number[];
    assets: string[];
    material_delta_threshold_eur: string;
    groups_count: number;
    material_groups_count: number;
    event_set_gap_groups_count: number;
    quantity_gap_groups_count: number;
    proceeds_delta_groups_count: number;
    reconciled_proceeds_delta_groups_count: number;
    unexplained_proceeds_delta_groups_count: number;
    quote_asset_fee_netting_groups_count: number;
    quote_asset_fee_netting_events_count: number;
    pool_reordering_groups_count: number;
    exact_groups_count: number;
    compared_events_count: number;
    global_gain_loss_eur: string;
    wallet_gain_loss_eur: string;
    gain_loss_delta_eur: string;
    global_proceeds_eur: string;
    wallet_proceeds_eur: string;
    turnover_delta_eur: string;
    proceeds_contribution_to_gain_delta_eur: string;
    unexplained_proceeds_delta_eur: string;
    global_cost_basis_eur: string;
    wallet_cost_basis_eur: string;
    cost_basis_delta_eur: string;
    cost_basis_contribution_to_gain_delta_eur: string;
    extra_turnover_detected: boolean;
    material_turnover_delta_detected: boolean;
    groups: Array<{
      year: number;
      asset: string;
      compared_events_count: number;
      material_events_count: number;
      explicit_fee_events_count: number;
      quantity_gap_events_count: number;
      proceeds_delta_events_count: number;
      pool_reordering_events_count: number;
      quantity_delta: string;
      proceeds_delta_eur: string;
      cost_basis_delta_eur: string;
      gain_loss_delta_eur: string;
      event_set_parity: boolean;
      quantity_parity: boolean;
      proceeds_parity: boolean;
      drivers: string[];
      explanation: string;
    }>;
    source_run_report_url: string;
    full_event_csv_download_url: string;
    findings: string[];
    methodology: string;
  } | null;
  walletFifoMethodAcceptance?: {
    generated_at: string;
    run_id?: string | null;
    run_generated_at?: string | null;
    run_as_of?: string | null;
    method_version?: string | null;
    run_status: string;
    method_delta_status: string;
    input_fingerprint_current: boolean;
    provider_basis_gap_count: number;
    unexplained_unmatched_count: number;
    provider_basis_event_set_gap_groups_count: number;
    provider_basis_quantity_gap_groups_count: number;
    unexplained_method_gap_groups_count: number;
    provider_basis_resolution_required: boolean;
    decision_ready: boolean;
    decision_status: string;
    decision_id?: string | null;
    decision_at?: string | null;
    method_acceptance_required: boolean;
    active_fifo_scope: string;
    target_fifo_scope: string;
    activation_applied: boolean;
    activation_ready: boolean;
    strict_ready: boolean;
    checks: Array<{
      key: string;
      label: string;
      passed: boolean;
      blocking: boolean;
      detail: string;
    }>;
    blockers: string[];
    findings: string[];
    evidence_refs: string[];
    methodology: string;
  };
  walletFifoMigrationRehearsal?: {
    rehearsal_id: string;
    generated_at: string;
    status: "blocked" | "ready_for_method_decision" | "ready_for_controlled_migration" | "already_active";
    run_id: string;
    run_generated_at: string;
    run_as_of: string;
    run_semantic_sha256: string;
    input_fingerprint_digest: string;
    input_fingerprint_current: boolean;
    method_version: string;
    decision_status: string;
    decision_id?: string | null;
    decision_ready: boolean;
    approved_decision_bound: boolean;
    active_fifo_scope: string;
    target_fifo_scope: string;
    technical_ready: boolean;
    migration_ready: boolean;
    production_write_performed: boolean;
    production_tax_semantic_unchanged: boolean;
    provider_basis_gap_count: number;
    unexplained_unmatched_count: number;
    source_all_lots_count: number;
    source_open_lots_count: number;
    source_tax_lines_count: number;
    staging_lots_count: number;
    staging_open_lots_count: number;
    staging_tax_lines_count: number;
    staging_orphan_tax_lines_count: number;
    staging_negative_lots_count: number;
    staging_arithmetic_delta_eur: string;
    staging_tax_lots_semantic_sha256: string;
    staging_tax_lines_semantic_sha256: string;
    semantic_sha256: string;
    year_checks: Array<{
      year: number;
      source_wallet_gain_loss_eur: string;
      staging_gain_loss_eur: string;
      delta_eur: string;
      source_wallet_tax_lines_count: number;
      staging_tax_lines_count: number;
      parity: boolean;
    }>;
    checks: Array<{
      key: string;
      label: string;
      gate: "technical" | "governance";
      passed: boolean;
      blocking: boolean;
      detail: string;
    }>;
    blockers: string[];
    findings: string[];
    next_actions: string[];
    evidence_refs: string[];
    artifact_path: string;
    latest_artifact_path: string;
    methodology: string;
  } | null;
  walletFifoMigrationApplyReadiness?: {
    generated_at: string;
    status: "blocked" | "ready_for_controlled_apply" | "already_active";
    ready: boolean;
    run_id?: string | null;
    rehearsal_id?: string | null;
    decision_id?: string | null;
    decision_status: string;
    input_fingerprint_current: boolean;
    rehearsal_bound: boolean;
    active_fifo_scope: string;
    target_fifo_scope: string;
    backup_root: string;
    required_backup_bytes: number;
    available_backup_bytes: number;
    checks: Array<{
      key: string;
      label: string;
      gate: "technical" | "governance" | "operational";
      passed: boolean;
      blocking: boolean;
      detail: string;
    }>;
    blockers: string[];
    next_actions: string[];
    evidence_refs: string[];
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
  taxBmfFinalizationMatrix?: {
    generated_at: string;
    years: Array<Record<string, unknown>>;
    available_years: number[];
    ready_years: number[];
    conservative_ready_years: number[];
    review_years: number[];
    blocked_years: number[];
    empty_years: number[];
    total_taxable_private_disposals_eur: string;
    total_rewards_mining_staking_income_eur: string;
    total_derivative_pnl_eur: string;
    ascii_table: string;
    methodology: string;
  };
  taxBmfSubmissionGuide?: {
    generated_at: string;
    years: Array<Record<string, unknown>>;
    available_years: number[];
    ready_years: number[];
    conservative_ready_years: number[];
    review_years: number[];
    blocked_years: number[];
    empty_years: number[];
    amendment_review_years: number[];
    total_taxable_private_disposals_eur: string;
    total_rewards_mining_staking_income_eur: string;
    total_derivative_pnl_eur: string;
    total_tax_free_private_disposals_eur: string;
    ascii_table: string;
    methodology: string;
  };
  taxBmfPriorFilingComparison?: {
    generated_at: string;
    setting_key: string;
    setting_exists: boolean;
    years: Array<Record<string, unknown>>;
    available_years: number[];
    match_years: number[];
    delta_review_years: number[];
    missing_declared_years: number[];
    untrusted_declared_years: number[];
    empty_years: number[];
    total_delta_taxable_private_disposals_eur: string;
    total_delta_rewards_mining_staking_income_eur: string;
    total_delta_derivative_pnl_eur: string;
    total_absolute_delta_eur: string;
    example_setting_json: string;
    ascii_table: string;
    methodology: string;
  };
  taxBmfPriorFilingDeclaredAmounts?: {
    setting_key: string;
    years: Array<Record<string, unknown>>;
    example_setting_json: string;
    methodology: string;
  };
  taxBmfAmendmentWorklist?: {
    generated_at: string;
    years: Array<Record<string, unknown>>;
    available_years: number[];
    correction_review_years: number[];
    compare_declared_years: number[];
    archive_only_years: number[];
    blocked_years: number[];
    total_v2_taxable_private_disposals_eur: string;
    total_v2_rewards_mining_staking_income_eur: string;
    total_v2_derivative_pnl_eur: string;
    ascii_table: string;
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
    internal_transfer_carry_count: number;
    internal_transfer_carry_fully_covered_count: number;
    internal_transfer_carry_basis_pending_count: number;
    internal_transfer_carried_cost_basis_eur: string;
    internal_transfer_status_counts: Record<string, number>;
    internal_transfer_source_counts: Record<string, number>;
    internal_transfer_evidence_status_counts: Record<string, number>;
    internal_transfer_asset_counts: Record<string, number>;
    internal_transfer_basis_pending: Array<Record<string, unknown>>;
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
  pionexHntReconciliation?: {
    generated_at: string;
    status: string;
    preflight_ready: boolean;
    reconciliation_ready: boolean;
    wallet_fifo_ready: boolean;
    strict_ready: boolean;
    missing_primary_acquisition_evidence: boolean;
    canceled_partial_fills_count: number;
    canceled_buy_quantity: string;
    canceled_sell_quantity: string;
    canceled_base_fee_quantity: string;
    canceled_net_quantity: string;
    imported_raw_objects: number;
    imported_canceled_events: number;
    asset: string;
    adjustment_event_time: string;
    adjustment_quantity: string;
    adjustment_cost_basis_eur: string;
    balance_min_quantity: string | null;
    balance_final_quantity: string | null;
    zero_cost_lot_consumed_quantity: string;
    historical_api_rows: number;
    decision_layer: Record<string, boolean>;
    evidence_refs: string[];
    errors: string[];
    methodology: string;
  };
  crossCexTransferEvidence?: {
    generated_at: string;
    status: string;
    strict_ready: boolean;
    source_run_id?: string | null;
    records_count: number;
    ready_count: number;
    review_count: number;
    years: number[];
    records: Array<{
      evidence_id: string;
      year: number;
      tx_id: string;
      asset: string;
      quantity: string;
      fee_quantity: string;
      source_id: string;
      target_source_id: string;
      source_pool_id: string;
      target_pool_id: string;
      source_event_time: string;
      target_event_time: string;
      lots_moved: number;
      carried_cost_basis_eur: string;
      status: string;
      ready: boolean;
    }>;
    errors: string[];
    semantic_sha256: string;
    methodology: string;
  };
  fairspotStakingReconciliation?: {
    generated_at: string;
    status: string;
    strict_ready: boolean;
    main_wallet: string;
    staking_wallet: string;
    outbound_events_count: number;
    return_events_count: number;
    reward_events_count: number;
    principal_outbound_quantity: string;
    principal_return_quantity: string;
    total_received_quantity: string;
    reward_quantity: string;
    reward_income_eur: string;
    source_run_id?: string | null;
    errors: string[];
    semantic_sha256: string;
    methodology: string;
  };
  solanaStakingPositionReconciliation?: {
    generated_at: string;
    status: string;
    strict_ready: boolean;
    reconciliation_id: string;
    year: number;
    wallet: string;
    program_id: string;
    asset: string;
    mint: string;
    principal_quantity: string;
    received_quantity: string;
    reward_quantity: string;
    reward_income_eur: string;
    wallet_fifo_run_id?: string | null;
    wallet_fifo_lots_moved: number;
    wallet_fifo_carried_cost_basis_eur: string;
    native_settlement_quantity: string;
    decision_layer: Record<string, boolean>;
    errors: string[];
    semantic_sha256: string;
    methodology: string;
  };
  moonpayReceipts?: {
    generated_at: string;
    status: string;
    strict_ready: boolean;
    sender_address: string;
    trade_history_path: string;
    trade_history_exists: boolean;
    trade_history_sha256?: string | null;
    trade_history_rows_count: number;
    completed_buy_rows_count: number;
    matched_trade_rows_count: number;
    unmatched_trade_rows_count: number;
    candidates_count: number;
    ready_count: number;
    total_base_payment_amount_eur: string;
    total_receipt_cost_basis_eur: string;
    total_fee_components_eur: string;
    total_bank_debits_eur: string;
    bank_camt_exists: boolean;
    bank_camt_files_count: number;
    bank_camt_semantic_sha256?: string | null;
    bank_debits_count: number;
    bank_debits_matched_count: number;
    bank_debits_unmatched_count: number;
    items: Array<{
      tx_id: string;
      event_time: string;
      asset: string;
      received_quantity: string;
      cost_basis_eur?: string | null;
      payment_amount_eur?: string | null;
      gross_payment_amount_eur?: string | null;
      fee_eur?: string | null;
      bank_debit_amount_eur?: string | null;
      bank_booking_date?: string | null;
      moonpay_trade_id?: string | null;
      payment_to_chain_seconds?: number | null;
      strict_ready: boolean;
    }>;
    semantic_sha256: string;
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
    declaration_income_eur: string;
    review_only_income_eur: string;
    taxable_reward_events_count: number;
    review_only_events_count: number;
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
  taxBusinessRewardInventoryReview?: {
    generated_at: string;
    assets: string[];
    affected_years: number[];
    strict_ready: boolean;
    total_tax_lines_count: number;
    potential_business_tax_lines_count: number;
    unresolved_tax_lines_count: number;
    potential_business_acquisition_cost_eur: string;
    potential_business_proceeds_eur: string;
    potential_business_gain_loss_eur: string;
    rows: Array<Record<string, unknown>>;
    findings: string[];
    next_actions: string[];
    methodology: string;
  };
  taxCryptoSwapValuationReview?: {
    generated_at: string;
    year: number | null;
    strict_ready: boolean;
    candidates_count: number;
    aligned_count: number;
    policy_mismatch_count: number;
    material_delta_count: number;
    received_price_fallback_review_count: number;
    missing_both_prices_count: number;
    current_value_eur: string;
    bmf_preview_value_eur: string;
    signed_value_delta_eur: string;
    absolute_value_delta_eur: string;
    affected_years: number[];
    rows_returned: number;
    rows: Array<Record<string, unknown>>;
    findings: string[];
    next_actions: string[];
    current_policy: string;
    bmf_preview_policy: string;
    methodology: string;
  };
  taxCryptoSwapFifoParallelPreview?: {
    generated_at: string;
    year: number | null;
    status: "matched" | "delta" | "unmatched_changed";
    read_only: boolean;
    current_tax_lines_count: number;
    preview_tax_lines_count: number;
    current_lots_count: number;
    preview_lots_count: number;
    current_unmatched_disposals: number;
    preview_unmatched_disposals: number;
    current_gain_loss_eur: string;
    preview_gain_loss_eur: string;
    gain_loss_delta_eur: string;
    absolute_year_gain_loss_delta_eur: string;
    affected_years: number[];
    years: Array<Record<string, unknown>>;
    top_assets: Array<Record<string, unknown>>;
    top_events: Array<Record<string, unknown>>;
    findings: string[];
    next_actions: string[];
    current_policy: string;
    preview_policy: string;
    methodology: string;
  };
  taxBmfCombinedFifoStaging?: {
    run_id: string;
    generated_at: string;
    as_of: string;
    years: number[];
    status: "blocked" | "review" | "ready_for_professional_review";
    strict_ready: boolean;
    read_only: boolean;
    productive_tax_tables_unchanged: boolean;
    active_global: Record<string, unknown>;
    received_first_global: Record<string, unknown>;
    active_wallet: Record<string, unknown>;
    received_first_wallet: Record<string, unknown>;
    price_policy_delta_eur: string;
    wallet_scope_delta_eur: string;
    combined_delta_eur: string;
    interaction_delta_eur: string;
    absolute_year_combined_delta_eur: string;
    potential_business_inventory_tax_lines_count: number;
    unresolved_reward_origin_tax_lines_count: number;
    affected_years: number[];
    year_rows: Array<Record<string, unknown>>;
    top_assets: Array<Record<string, unknown>>;
    sphere_rows: Array<Record<string, unknown>>;
    top_events: Array<Record<string, unknown>>;
    findings: string[];
    next_actions: string[];
    methodology: string;
  };
  taxBmfFifoEventEvidence?: {
    run_id: string;
    generated_at: string;
    status: "blocked" | "review" | "ready_for_professional_review";
    strict_ready: boolean;
    read_only: boolean;
    staging_run_id: string;
    staging_matches_current_input: boolean;
    staging_matches_current_tax_component: boolean;
    productive_tax_tables_unchanged: boolean;
    scope_complete_for_staging_artifact: boolean;
    full_ledger_scope: boolean;
    ledger_events_count: number;
    tax_graph_events_count: number;
    tax_graph_missing_events_count: number;
    unknown_event_type_count: number;
    unknown_tax_graph_events_count: number;
    staging_rows_count: number;
    selected_discrepancy_rows_count: number;
    unique_events_count: number;
    ready_events_count: number;
    review_events_count: number;
    blocked_events_count: number;
    raw_evidence_ready_count: number;
    independent_price_ready_count: number;
    derived_price_review_count: number;
    stale_price_review_count: number;
    missing_price_count: number;
    missing_canonical_events_count: number;
    missing_raw_evidence_count: number;
    missing_required_identifiers_count: number;
    unresolved_origin_rows_count: number;
    documented_business_inventory_rows_count: number;
    documented_swap_acquisition_rows_count: number;
    internal_transfer_fifo_carry_rows_count: number;
    opening_reconstruction_rows_count: number;
    unclassified_origin_rows_count: number;
    separate_income_review_rows_count: number;
    opening_balance_events_count: number;
    signed_combined_delta_eur: string;
    absolute_combined_delta_eur: string;
    groups: Array<Record<string, unknown>>;
    ledger_groups: Array<Record<string, unknown>>;
    origin_evidence_groups: Array<Record<string, unknown>>;
    opening_balance_evidence: Array<Record<string, unknown>>;
    discrepancy_rows: Array<Record<string, unknown>>;
    discrepancy_rows_truncated: boolean;
    event_issues: Array<{
      event_id: string;
      event_time: string | null;
      source: string | null;
      source_ref: string | null;
      event_type: string | null;
      asset: string | null;
      quantity: string | null;
      quote_asset: string | null;
      quote_quantity: string | null;
      tx_id: string | null;
      wallet: string | null;
      account: string | null;
      source_evidence: Record<string, unknown>;
      received_price: Record<string, unknown> | null;
      given_price: Record<string, unknown> | null;
      status: "blocked" | "review" | "ready";
      issue_codes: string[];
      evidence_digest: string;
    }>;
    event_issues_truncated: boolean;
    all_event_evidence_artifact_path: string | null;
    all_event_evidence_artifact_sha256: string | null;
    all_event_evidence_artifact_bytes: number;
    all_event_evidence_compression: "gzip-jsonl" | null;
    findings: string[];
    next_actions: string[];
    methodology: string;
  };
  taxBmfEventPriceRemediation?: {
    run_id: string;
    generated_at: string;
    status: "planned" | "applied" | "partial" | "blocked";
    execute: boolean;
    read_only: boolean;
    productive_tax_tables_unchanged: boolean;
    requirements_count: number;
    planned_count: number;
    imported_count: number;
    already_ready_count: number;
    failed_count: number;
    token_risk_blocked_count: number;
    request_limit_count: number;
    provider_requests_count: number;
    fx_requests_count: number;
    unique_assets: string[];
    unique_dates_count: number;
    before_review_events_count: number;
    before_derived_price_review_count: number;
    before_stale_price_review_count: number;
    after_review_events_count: number | null;
    after_derived_price_review_count: number | null;
    after_stale_price_review_count: number | null;
    jobs: Array<Record<string, unknown>>;
    findings: string[];
    next_actions: string[];
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
  taxYearGainEvidenceReview?: {
    year: number;
    generated_at: string;
    taxable_gain_loss_eur: string;
    reviewed_gain_loss_eur: string;
    reviewed_lines_count: number;
    high_risk_lines_count: number;
    review_lines_count: number;
    ok_lines_count: number;
    price_delta_lines_count: number;
    event_level_reconciled_lines_count: number;
    acquisition_event_level_reconciled_lines_count: number;
    material_price_delta_eur: string;
    open_price_delta_eur: string;
    delta_groups: Array<Record<string, unknown>>;
    lines: Array<Record<string, unknown>>;
    caveats: string[];
    ascii_table: string;
    methodology: string;
  };
  taxYearGainEvidencePriceDeltas?: {
    year: number;
    generated_at: string;
    classification_filter?: string | null;
    lines_count: number;
    gain_loss_eur: string;
    absolute_delta_eur: string;
    acquisition_delta_eur: string;
    disposal_delta_eur: string;
    dominant_acquisition_count: number;
    dominant_disposal_count: number;
    dominant_both_count: number;
    split_line_review_count: number;
    root_cause_counts: Record<string, number>;
    event_level_reconciled_count: number;
    event_level_review_count: number;
    event_level_unchecked_count: number;
    lines: Array<Record<string, unknown>>;
    caveats: string[];
    methodology: string;
  };
  taxYearGainEvidenceEventDeltas?: {
    year: number;
    generated_at: string;
    events_count: number;
    event_level_ok_count: number;
    event_level_review_count: number;
    missing_price_count: number;
    tax_line_count: number;
    actual_proceeds_eur: string;
    expected_proceeds_eur: string;
    event_delta_eur: string;
    split_line_absolute_delta_eur: string;
    lines: Array<Record<string, unknown>>;
    caveats: string[];
    methodology: string;
  };
  taxYearGainEvidenceAcquisitionEventDeltas?: {
    year: number;
    generated_at: string;
    events_count: number;
    event_level_ok_count: number;
    event_level_review_count: number;
    missing_price_count: number;
    tax_line_count: number;
    actual_cost_eur: string;
    expected_cost_eur: string;
    event_delta_eur: string;
    lines: Array<Record<string, unknown>>;
    caveats: string[];
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
  taxHeliumSwapContext?: {
    generated_at: string;
    year?: number | null;
    events_count: number;
    total_context_value_eur: string;
    total_taxable_trade_gain_loss_eur: string;
    total_tax_free_trade_gain_loss_eur: string;
    total_trade_gain_loss_eur: string;
    total_reward_income_eur: string;
    years: Array<Record<string, unknown>>;
    assets: Array<Record<string, unknown>>;
    rows: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxHeliumSwapEvidenceReview?: {
    generated_at: string;
    year?: number | null;
    tx_count: number;
    raw_evidence_ready_count: number;
    raw_evidence_missing_count: number;
    total_context_value_eur: string;
    rows: Array<Record<string, unknown>>;
    methodology: string;
  };
  taxHeliumSwapAlchemyAudit?: {
    generated_at?: string | null;
    year?: number | null;
    provider?: string | null;
    rpc_url?: string | null;
    tx_count: number;
    alchemy_found_count: number;
    confirmed_count: number;
    alchemy_failed_count: number;
    review_status_counts: Record<string, number>;
    alchemy_status_counts: Record<string, number>;
    rows: Array<Record<string, unknown>>;
    methodology?: string | null;
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
  priceStablecoinFxAnchorPreview?: {
    generated_at: string;
    artifact_found: boolean;
    artifact_path?: string | null;
    artifact_generated_at?: string | null;
    required_days: number;
    ready_days: number;
    missing_days: number;
    groups_count: number;
    groups_requiring_review: number;
    taxable_gain_loss_delta_eur?: string | null;
    groups: Array<Record<string, unknown>>;
    anchors: Array<Record<string, unknown>>;
    tax_impact: Array<Record<string, unknown>>;
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
  { id: "dashboard", label: "Uebersicht", description: "Gesamtstatus, naechster Schritt und Live-Datenstand", group: "workflow", icon: <LayoutDashboard size={18} /> },
  { id: "sources", label: "Quellen & Wallets", description: "Eigene Quellen, Live-Status und Ledger-Abgleich", group: "workflow", icon: <WalletCards size={18} /> },
  { id: "import", label: "Daten importieren", description: "Daten einlesen, Preflights und Importabdeckung", group: "workflow", icon: <Upload size={18} /> },
  { id: "flows", label: "Transaktionen", description: "Geldfluesse, Transferkandidaten und Netto-Fluesse", group: "workflow", icon: <GitBranch size={18} /> },
  { id: "review", label: "Hinweise pruefen", description: "Offene Fachentscheidungen und Belegspuren", group: "workflow", icon: <ClipboardCheck size={18} /> },
  { id: "tax", label: "Steuerjahre", description: "Eingabehilfe, BMF-Status und Jahresbelege", group: "workflow", icon: <ReceiptText size={18} /> },
  { id: "export", label: "Berichte & Belege", description: "Report-Center, Finanzamtspakete und CSV/ZIP/PDF", group: "workflow", icon: <FileDown size={18} /> },
  { id: "portfolio", label: "Portfolio & Haltefristen", description: "Bestand, Preisdeckung und steuerfreie Positionen", group: "evidence", icon: <WalletCards size={18} /> },
  { id: "stichtage", label: "Stichtagswerte", description: "Historische Bestands- und Wertansicht", group: "evidence", icon: <CalendarDays size={18} /> },
  { id: "zugewinn", label: "Zugewinndossier", description: "Stichtagswerte, Erbgeld und familienrechtliche Belege", group: "evidence", icon: <Scale size={18} /> },
  { id: "parity", label: "V1/V2 Pruefung", description: "Paritaet, Referenzen und Diagnose", group: "expert", icon: <Scale size={18} /> },
  { id: "admin", label: "Administration", description: "Settings, Credentials und Systemstatus", group: "expert", icon: <Settings size={18} /> },
  { id: "ai", label: "Lokale KI", description: "Jahrespaket-QA und KI-Aufgaben", group: "expert", icon: <Bot size={18} /> }
];

const API_BASE = import.meta.env.VITE_API_BASE || `${window.location.protocol}//${window.location.hostname}:8010`;
const API_TIMEOUT_MS = 60_000;

function sectionFromLocation(): Section {
  const candidate = window.location.hash.replace(/^#\/?/, "") as Section;
  return navItems.some((item) => item.id === candidate) ? candidate : "dashboard";
}

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
  const headers = new Headers(init.headers);
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
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

async function putApi<T>(path: string, payload: unknown): Promise<T> {
  const body = await fetchApiResponse<T>(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  return body.data;
}

function App() {
  const [active, setActive] = useState<Section>(() => sectionFromLocation());
  const [snapshot, setSnapshot] = useState<Snapshot>({});
  const [loading, setLoading] = useState(false);
  const [pageLoading, setPageLoading] = useState(false);
  const [loaderStatuses, setLoaderStatuses] = useState<LoaderStatus[]>([]);
  const [lastRefreshAt, setLastRefreshAt] = useState<string | null>(null);
  const [lastLoadFailureCount, setLastLoadFailureCount] = useState(0);
  const [showExpertNav, setShowExpertNav] = useState(false);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const refreshRunId = useRef(0);
  const [sourceRefreshLoading, setSourceRefreshLoading] = useState(false);
  const [sourceRegistryRunLoading, setSourceRegistryRunLoading] = useState(false);
  const [walletFifoRunLoading, setWalletFifoRunLoading] = useState(false);
  const [bitgetBasisDecisionLoading, setBitgetBasisDecisionLoading] = useState(false);
  const [swapFifoParallelLoading, setSwapFifoParallelLoading] = useState(false);
  const [bmfCombinedFifoStagingLoading, setBmfCombinedFifoStagingLoading] = useState(false);
  const [bmfFifoEventEvidenceLoading, setBmfFifoEventEvidenceLoading] = useState(false);
  const [bmfEventPriceRemediationLoading, setBmfEventPriceRemediationLoading] = useState(false);
  const [walletFifoMigrationLoading, setWalletFifoMigrationLoading] = useState(false);
  const [divorceValuationRunLoading, setDivorceValuationRunLoading] = useState(false);
  const [asOfPriceGateLoading, setAsOfPriceGateLoading] = useState(false);
  const [serviceRouteEvidenceLoading, setServiceRouteEvidenceLoading] = useState(false);
  const [tradeRepublicValuationLoading, setTradeRepublicValuationLoading] = useState(false);
  const [tradeRepublicDocumentUploadLoading, setTradeRepublicDocumentUploadLoading] = useState(false);
  const [inheritanceDocumentUploadLoading, setInheritanceDocumentUploadLoading] = useState(false);
  const [inheritanceDocumentReviewLoading, setInheritanceDocumentReviewLoading] = useState(false);
  const [bankCamtUploadLoading, setBankCamtUploadLoading] = useState(false);
  const [coinbaseValuationLoading, setCoinbaseValuationLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [flowYear, setFlowYear] = useState("all");
  const [asOfDate, setAsOfDate] = useState("2025-06-13");
  const [divorceCutoffDate, setDivorceCutoffDate] = useState("2025-06-13");
  const [divorceValuationDate, setDivorceValuationDate] = useState("2026-07-24");
  const [divorceMaterialityEur, setDivorceMaterialityEur] = useState("1");
  const [selectedSourceId, setSelectedSourceId] = useState<string | null>(null);
  const [selectedTaxYear, setSelectedTaxYear] = useState(() => window.localStorage.getItem("steuerreport:selected-tax-year") ?? "2025");
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

  useEffect(() => {
    const expectedHash = `#${active}`;
    if (window.location.hash !== expectedHash) {
      window.location.hash = active;
    }
  }, [active]);

  useEffect(() => {
    const handleHashChange = () => {
      setActive(sectionFromLocation());
      setMobileNavOpen(false);
    };
    window.addEventListener("hashchange", handleHashChange);
    return () => window.removeEventListener("hashchange", handleHashChange);
  }, []);

  useEffect(() => {
    if (!mobileNavOpen) {
      return undefined;
    }
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setMobileNavOpen(false);
      }
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", closeOnEscape);
    };
  }, [mobileNavOpen]);

  useEffect(() => {
    window.localStorage.setItem("steuerreport:selected-tax-year", selectedTaxYear);
  }, [selectedTaxYear]);

  async function refresh() {
    const runId = refreshRunId.current + 1;
    refreshRunId.current = runId;
    setPageLoading(true);
    setLoading(true);
    setError(null);
    setNotice(null);
    try {
      const allLoaders: Record<string, SnapshotLoader> = {
        health: { key: "health", label: "Health", load: () => getApi<Record<string, unknown>>("/api/v1/health") },
        cockpit: { key: "cockpit", label: "Cockpit", load: () => getApi<Snapshot["cockpit"]>("/api/v1/cockpit/summary") },
        productReadiness: { key: "productReadiness", label: "Produkt-Readiness", load: () => getApi<Snapshot["productReadiness"]>("/api/v1/product/readiness") },
        connectorCatalog: { key: "connectorCatalog", label: "Connector-Katalog", load: () => getApi<Snapshot["connectorCatalog"]>("/api/v1/connectors/catalog") },
        sourcesOverview: { key: "sourcesOverview", label: "Quellen", load: () => getApi<Snapshot["sourcesOverview"]>("/api/v1/sources/overview") },
        sourceConnectorDiagnostics: { key: "sourceConnectorDiagnostics", label: "Connector-Diagnose", load: () => getApi<Snapshot["sourceConnectorDiagnostics"]>("/api/v1/sources/connector-diagnostics") },
        sourceRegistry: { key: "sourceRegistry", label: "Quellenregistry", load: () => getApi<Snapshot["sourceRegistry"]>("/api/v1/sources/registry/runs/latest") },
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
        portfolioValueHistory: { key: "portfolioValueHistory", label: "V2-Portfolio-Verlauf", load: () => getApi<Snapshot["portfolioValueHistory"]>(`/api/v1/portfolio/value-history?to_date=${encodeURIComponent(asOfDate)}&interval=month&max_points=72`) },
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
        divorceEqualization: {
          key: "divorceEqualization",
          label: "Zugewinn-Auswertung",
          load: () => getApi<Snapshot["divorceEqualization"]>(
            `/api/v1/divorce/equalization-summary?separation_date=${encodeURIComponent(divorceCutoffDate)}&end_asset_date=${encodeURIComponent(divorceValuationDate)}&materiality_threshold_eur=${encodeURIComponent(divorceMaterialityEur || "1")}`
          )
        },
        divorceValuationRun: { key: "divorceValuationRun", label: "Stichtags-Dossier", load: () => getApi<Snapshot["divorceValuationRun"]>("/api/v1/divorce/valuation-runs/latest") },
        asOfCutoffPriceGate: { key: "asOfCutoffPriceGate", label: "Trennungspreise", load: () => getApi<Snapshot["asOfCutoffPriceGate"]>(`/api/v1/prices/as-of-gate?as_of_date=${encodeURIComponent(divorceCutoffDate)}&materiality_threshold_eur=${encodeURIComponent(divorceMaterialityEur || "1")}`) },
        asOfPriceGate: { key: "asOfPriceGate", label: "Endvermoegenspreise", load: () => getApi<Snapshot["asOfPriceGate"]>(`/api/v1/prices/as-of-gate?as_of_date=${encodeURIComponent(divorceValuationDate)}&materiality_threshold_eur=${encodeURIComponent(divorceMaterialityEur || "1")}`) },
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
        taxBmfComplianceMatrix: { key: "taxBmfComplianceMatrix", label: "BMF-Anforderungsmatrix", load: () => getApi<Snapshot["taxBmfComplianceMatrix"]>("/api/v1/tax-methodology/bmf-compliance-matrix") },
        legalResearchFreshness: { key: "legalResearchFreshness", label: "Aktueller Rechtsstand", load: () => getApi<Snapshot["legalResearchFreshness"]>("/api/v1/tax-methodology/legal-research/freshness") },
        walletFifoParallelRun: { key: "walletFifoParallelRun", label: "Wallet-FIFO-Prueflauf", load: () => getApi<Snapshot["walletFifoParallelRun"]>("/api/v1/tax/wallet-fifo-runs/latest") },
        bitgetStrategyFifoGaps: { key: "bitgetStrategyFifoGaps", label: "Bitget Strategy-FIFO", load: () => getApi<Snapshot["bitgetStrategyFifoGaps"]>("/api/v1/tax/wallet-fifo/bitget-strategy-gaps") },
        bitgetStrategyReconstruction: { key: "bitgetStrategyReconstruction", label: "Bitget Strategy-Rekonstruktion", load: () => getApi<Snapshot["bitgetStrategyReconstruction"]>("/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction") },
        bitgetStrategyBasisDecision: { key: "bitgetStrategyBasisDecision", label: "Bitget Basismethodenentscheidung", load: () => getApi<Snapshot["bitgetStrategyBasisDecision"]>("/api/v1/tax/wallet-fifo/bitget-strategy-basis-decision") },
        walletFifoMethodDeltaExplanation: { key: "walletFifoMethodDeltaExplanation", label: "Wallet-FIFO-Erklaerung", load: () => getApi<Snapshot["walletFifoMethodDeltaExplanation"]>(`/api/v1/tax/wallet-fifo-runs/latest/method-delta-explanation?year=${encodeURIComponent(selectedTaxYear)}&event_limit=5`) },
        walletFifoMethodAcceptance: { key: "walletFifoMethodAcceptance", label: "Wallet-FIFO-Abnahmeakte", load: () => getApi<Snapshot["walletFifoMethodAcceptance"]>("/api/v1/tax/wallet-fifo-runs/latest/method-acceptance") },
        walletFifoMigrationRehearsal: { key: "walletFifoMigrationRehearsal", label: "Wallet-FIFO-Migrationsprobe", load: () => getApi<Snapshot["walletFifoMigrationRehearsal"]>("/api/v1/tax/wallet-fifo-migrations/rehearsals/latest") },
        walletFifoMigrationApplyReadiness: { key: "walletFifoMigrationApplyReadiness", label: "Wallet-FIFO-Apply-Gate", load: () => getApi<Snapshot["walletFifoMigrationApplyReadiness"]>("/api/v1/tax/wallet-fifo-migrations/apply-readiness") },
        taxBmfActionPlan: { key: "taxBmfActionPlan", label: "BMF-Aktionsliste", load: () => getApi<Snapshot["taxBmfActionPlan"]>(`/api/v1/tax-methodology/bmf-action-plan?year=${encodeURIComponent(selectedTaxYear)}`) },
        taxBmfFinalizationMatrix: { key: "taxBmfFinalizationMatrix", label: "BMF-Finalisierung", load: () => getApi<Snapshot["taxBmfFinalizationMatrix"]>("/api/v1/tax-methodology/bmf-finalization-matrix") },
        taxBmfSubmissionGuide: { key: "taxBmfSubmissionGuide", label: "BMF-Abgabehilfe", load: () => getApi<Snapshot["taxBmfSubmissionGuide"]>("/api/v1/tax-methodology/bmf-submission-guide") },
        taxBmfPriorFilingComparison: { key: "taxBmfPriorFilingComparison", label: "Alt-Erklaerungsvergleich", load: () => getApi<Snapshot["taxBmfPriorFilingComparison"]>("/api/v1/tax-methodology/bmf-prior-filing-comparison") },
        taxBmfPriorFilingDeclaredAmounts: { key: "taxBmfPriorFilingDeclaredAmounts", label: "Alt-Erklaerungswerte", load: () => getApi<Snapshot["taxBmfPriorFilingDeclaredAmounts"]>("/api/v1/tax-methodology/bmf-prior-filing-declared-amounts") },
        taxBmfAmendmentWorklist: { key: "taxBmfAmendmentWorklist", label: "Korrekturpruefungs-Worklist", load: () => getApi<Snapshot["taxBmfAmendmentWorklist"]>("/api/v1/tax-methodology/bmf-amendment-worklist") },
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
        pionexHntReconciliation: {
          key: "pionexHntReconciliation",
          label: "Pionex HNT-Reconciliation",
          load: () => selectedTaxYear === "2022"
            ? getApi<Snapshot["pionexHntReconciliation"]>("/api/v1/tax/pionex-hnt-reconciliation")
            : Promise.resolve(undefined)
        },
        crossCexTransferEvidence: {
          key: "crossCexTransferEvidence",
          label: "Cross-CEX Transfernachweise",
          load: () => getApi<Snapshot["crossCexTransferEvidence"]>(
            "/api/v1/tax/cross-cex-transfer-evidence"
          )
        },
        fairspotStakingReconciliation: {
          key: "fairspotStakingReconciliation",
          label: "Fairspot Staking-Reconciliation",
          load: () => selectedTaxYear === "2022"
            ? getApi<Snapshot["fairspotStakingReconciliation"]>(
                "/api/v1/tax/fairspot-staking-reconciliation"
              )
            : Promise.resolve(undefined)
        },
        solanaStakingPositionReconciliation: {
          key: "solanaStakingPositionReconciliation",
          label: "Solana Staking-Position",
          load: () => selectedTaxYear === "2026"
            ? getApi<Snapshot["solanaStakingPositionReconciliation"]>(
                "/api/v1/tax/solana-staking-position-reconciliation"
              )
            : Promise.resolve(undefined)
        },
        moonpayReceipts: {
          key: "moonpayReceipts",
          label: "MoonPay Anschaffungsbelege",
          load: () => selectedTaxYear === "2026"
            ? getApi<Snapshot["moonpayReceipts"]>("/api/v1/tax/moonpay-receipts")
            : Promise.resolve(undefined)
        },
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
        taxBusinessRewardInventoryReview: { key: "taxBusinessRewardInventoryReview", label: "Reward Ursprungssphaere", load: () => getApi<Snapshot["taxBusinessRewardInventoryReview"]>("/api/v1/tax-years/business-reward-inventory-review") },
        taxCryptoSwapValuationReview: { key: "taxCryptoSwapValuationReview", label: "Krypto-Tausch Bewertung", load: () => getApi<Snapshot["taxCryptoSwapValuationReview"]>(`/api/v1/tax/crypto-swap-valuation-review?year=${encodeURIComponent(selectedTaxYear)}&limit=200`) },
        taxCryptoSwapFifoParallelPreview: { key: "taxCryptoSwapFifoParallelPreview", label: "Preis-FIFO Parallelvergleich", load: () => getApi<Snapshot["taxCryptoSwapFifoParallelPreview"]>("/api/v1/tax/crypto-swap-fifo-parallel-preview/latest") },
        taxBmfCombinedFifoStaging: { key: "taxBmfCombinedFifoStaging", label: "BMF Gesamt-FIFO Staging", load: () => getApi<Snapshot["taxBmfCombinedFifoStaging"]>("/api/v1/tax/bmf-combined-fifo-staging/latest") },
        taxBmfFifoEventEvidence: { key: "taxBmfFifoEventEvidence", label: "BMF FIFO-Eventbelege", load: () => getApi<Snapshot["taxBmfFifoEventEvidence"]>("/api/v1/tax/bmf-fifo-event-evidence/latest") },
        taxBmfEventPriceRemediation: { key: "taxBmfEventPriceRemediation", label: "BMF Event-Preisanker", load: () => getApi<Snapshot["taxBmfEventPriceRemediation"]>("/api/v1/tax/bmf-event-price-remediation/latest") },
        taxYearDrivers: { key: "taxYearDrivers", label: "Gewinntreiber", load: () => getApi<Snapshot["taxYearDrivers"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/drivers?limit=80`) },
        taxYearGainLossRealityCheck: { key: "taxYearGainLossRealityCheck", label: "Realisiert vs gehalten", load: () => getApi<Snapshot["taxYearGainLossRealityCheck"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/gain-loss-reality-check?limit=40`) },
        taxYearGainEvidenceReview: { key: "taxYearGainEvidenceReview", label: "Gewinn-Belegcheck", load: () => getApi<Snapshot["taxYearGainEvidenceReview"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/gain-evidence-review?limit=80`) },
        taxYearGainEvidencePriceDeltas: { key: "taxYearGainEvidencePriceDeltas", label: "Preisdelta-Drilldown", load: () => getApi<Snapshot["taxYearGainEvidencePriceDeltas"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/gain-evidence-price-deltas?limit=200`) },
        taxYearGainEvidenceEventDeltas: { key: "taxYearGainEvidenceEventDeltas", label: "Event-Level Preisdelta", load: () => getApi<Snapshot["taxYearGainEvidenceEventDeltas"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/gain-evidence-event-deltas?limit=200`) },
        taxYearGainEvidenceAcquisitionEventDeltas: { key: "taxYearGainEvidenceAcquisitionEventDeltas", label: "Erwerbs-Event Preisdelta", load: () => getApi<Snapshot["taxYearGainEvidenceAcquisitionEventDeltas"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/gain-evidence-acquisition-event-deltas?limit=200`) },
        taxYearTurnoverAudit: { key: "taxYearTurnoverAudit", label: "Umsatz-Plausibilitaet", load: () => getApi<Snapshot["taxYearTurnoverAudit"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/turnover-audit?limit=20`) },
        taxYearsTurnoverAuditSummary: { key: "taxYearsTurnoverAuditSummary", label: "Umsatz-Plausibilitaet alle Jahre", load: () => getApi<Snapshot["taxYearsTurnoverAuditSummary"]>("/api/v1/tax-years/turnover-audit-summary?limit=8") },
        taxSolanaProgramIncomeReview: { key: "taxSolanaProgramIncomeReview", label: "Solana Programm-Kontext", load: () => getApi<Snapshot["taxSolanaProgramIncomeReview"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/solana-program-income-review?limit=20`) },
        taxHeliumSwapContext: { key: "taxHeliumSwapContext", label: "Helium Swap-Kontext", load: () => getApi<Snapshot["taxHeliumSwapContext"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/helium-swap-context?limit=20`) },
        taxHeliumSwapEvidenceReview: { key: "taxHeliumSwapEvidenceReview", label: "Helium TxID-Belege", load: () => getApi<Snapshot["taxHeliumSwapEvidenceReview"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/helium-swap-evidence-review?limit=20`) },
        taxHeliumSwapAlchemyAudit: { key: "taxHeliumSwapAlchemyAudit", label: "Helium Alchemy-Audit", load: () => getApi<Snapshot["taxHeliumSwapAlchemyAudit"]>(`/api/v1/tax-years/${encodeURIComponent(selectedTaxYear)}/helium-swap-alchemy-audit?limit=12`) },
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
        priceStablecoinFxAnchorPreview: { key: "priceStablecoinFxAnchorPreview", label: "Stablecoin-FX-Anker", load: () => getApi<Snapshot["priceStablecoinFxAnchorPreview"]>("/api/v1/prices/quality/stablecoin-fx-anchor-preview-latest") },
        priceSolscanSignatureReview: { key: "priceSolscanSignatureReview", label: "Solscan-Signatur-Review", load: () => getApi<Snapshot["priceSolscanSignatureReview"]>("/api/v1/prices/quality/solscan-signature-review") },
        priceBinanceNormalizerReview: { key: "priceBinanceNormalizerReview", label: "Binance-Normalizer-Review", load: () => getApi<Snapshot["priceBinanceNormalizerReview"]>("/api/v1/prices/quality/binance-normalizer-review") },
        priceEventQuoteEvidenceReview: { key: "priceEventQuoteEvidenceReview", label: "Event-Quote-Evidenz", load: () => getApi<Snapshot["priceEventQuoteEvidenceReview"]>("/api/v1/prices/quality/event-quote-evidence-review") },
        priceRequirements: { key: "priceRequirements", label: "Preis-Anforderungen", load: () => getApi<Snapshot["priceRequirements"]>("/api/v1/prices/requirements") }
      };
      const taxCoreLoaderKeys = [
        "health",
        "taxYearsSummary",
        "taxPaymentOverview",
        "taxYearFilingSummary",
        "taxYearFilingMatrix",
        "taxFilingClosureOverview",
        "taxBmfComplianceMatrix",
        "legalResearchFreshness",
        "walletFifoParallelRun",
        "bitgetStrategyFifoGaps",
        "bitgetStrategyReconstruction",
        "bitgetStrategyBasisDecision",
        "walletFifoMethodDeltaExplanation",
        "walletFifoMethodAcceptance",
        "walletFifoMigrationRehearsal",
        "walletFifoMigrationApplyReadiness",
        "taxBmfFinalizationMatrix",
        "taxBmfPriorFilingDeclaredAmounts",
        "taxHoldingPeriods",
        "taxLossRealizationPlanner",
        "taxSummary",
        "derivativeSummary",
      ];
      const taxEvidenceLoaderKeys = [
        "taxYearsCorrectionMap",
        "taxBmfSubmissionGuide",
        "taxBmfPriorFilingComparison",
        "taxBmfAmendmentWorklist",
        "taxYearDetail",
        "taxDeclarationGuide",
        "taxYearEvidence",
        "taxYearTurnoverAudit",
        "taxYearsTurnoverAuditSummary",
        "taxMethodologySummary",
        "taxBmfActionPlan",
        "taxYearMethodology",
        "taxYearWalletFifoDelta",
        "taxYearWalletFifoProvenanceClosure",
        "pionexHntReconciliation",
        "crossCexTransferEvidence",
        "fairspotStakingReconciliation",
        "solanaStakingPositionReconciliation",
        "moonpayReceipts",
        "taxLegacyHeliumOverview",
        "taxIncomeGuide",
        "taxRewardTradingSeparation",
        "taxBusinessRewardInventoryReview",
        "taxCryptoSwapValuationReview",
        "taxYearDrivers",
        "taxYearGainLossRealityCheck",
        "taxExternalInflows"
      ];
      const taxExpertLoaderKeys = [
        "taxCryptoSwapFifoParallelPreview",
        "taxBmfCombinedFifoStaging",
        "taxBmfFifoEventEvidence",
        "taxBmfEventPriceRemediation",
        "taxYearGainEvidenceReview",
        "taxYearGainEvidencePriceDeltas",
        "taxYearGainEvidenceEventDeltas",
        "taxYearGainEvidenceAcquisitionEventDeltas",
        "taxSolanaProgramIncomeReview",
        "taxHeliumSwapContext",
        "taxHeliumSwapEvidenceReview",
        "taxHeliumSwapAlchemyAudit",
        "taxStablecoinFifoReview",
        "taxStablecoinQuoteLegReview",
        "taxSolanaStablecoinSwapContext",
        "taxSolanaStablecoinFxReview",
        "taxYearWalletFifoGaps",
        "taxYearWalletFifoOriginTrace",
        "taxYearCexDepositTransferEvidence",
        "taxYearCexSenderOwnershipLatest",
        "taxYearCexExchangeOutflowEvidence",
        "taxYearCexExchangeOutflowAnchorFeasibility",
        "taxYearWalletFifoProvenancePriorities",
        "taxYearWalletFifoRawProvenanceBreakdown",
        "taxYearWalletFifoExchangeEvidenceGaps",
        "taxYearWalletFifoSolanaProvenanceClassification",
        "taxYearWalletFifoSolanaProvenanceBatchLatest",
        "taxYearWalletFifoSolanaRawProvenanceSenders",
        "taxYearWalletFifoSolanaRawProvenancePriorities",
        "taxYearWalletFifoSolanaRawBmfEvidenceSummary",
        "taxYearWalletFifoSolanaRawBmfEvidenceDrilldown",
        "taxYearWalletFifoSolanaSenderClusters",
        "taxYearWalletFifoSolanaSenderClusterOutflows",
        "taxYearWalletFifoSolanaOrigin",
        "taxUnmatchedDisposals",
        "taxLots",
        "taxLines",
        "derivativeLines"
      ];
      const taxLoaderKeys = [
        ...taxCoreLoaderKeys,
        ...(taxViewMode !== "guided" ? taxEvidenceLoaderKeys : []),
        ...(taxViewMode === "expert" ? taxExpertLoaderKeys : [])
      ];
      const loaderKeysBySection: Record<Section, string[]> = {
        dashboard: [
          "health",
          "cockpit",
          "productReadiness",
          "taxYearsSummary",
          "taxPaymentOverview",
          "taxYearFilingMatrix",
          "taxFilingClosureOverview"
        ],
        sources: [
          "health",
          "connectorCatalog",
          "sourcesOverview",
          "sourceConnectorDiagnostics",
          "sourceRegistry",
          ...(sourceViewMode !== "overview"
            ? ["sourceDetail", "sourceReconciliation", "sourceReconciliationEvidence", "binanceEarnHistoryPreflight", "binanceEarnHistoryApiPreview"]
            : []),
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
          "taxLossRealizationPlanner",
          "priceCoverage",
          ...(portfolioViewMode !== "overview"
            ? ["portfolioReconciliation", "portfolioValuationAudit", "separationReport", "fiatDeposits", "latestPrices"]
            : []),
          ...(portfolioViewMode === "expert"
            ? ["prices", "priceQuality", "priceManualReview", "priceStablecoinFxReview", "priceStablecoinFxAnchorPreview", "priceSolscanSignatureReview", "priceBinanceNormalizerReview", "priceEventQuoteEvidenceReview", "priceRequirements"]
            : [])
        ],
        stichtage: ["health", "portfolioAsOf", "portfolioValueHistory", "priceCoverage"],
        zugewinn: ["health", "divorceEqualization", "divorceValuationRun", "asOfCutoffPriceGate", "asOfPriceGate"],
        flows: ["health", "flows", "transferCandidates"],
        review: [
          "health",
          "review",
          "reviewTasks",
          "jupiterRiskReview",
          "reviewDecisions",
          ...(reviewViewMode !== "tasks" ? ["reviewEvidenceTraces", "reviewDecisionSuggestions", "blockpitSolanaPreflight"] : []),
          ...(reviewViewMode === "expert" ? ["priceCoverage", "priceQuality", "priceManualReview", "priceStablecoinFxReview", "priceStablecoinFxAnchorPreview", "priceSolscanSignatureReview", "priceBinanceNormalizerReview", "priceEventQuoteEvidenceReview", "priceRequirements"] : [])
        ],
        parity: ["health", "parity", "parityDiagnostics", "parityReleaseReadiness", "parityReferences", "hntFifoProvenance"],
        tax: taxLoaderKeys,
        export: [
          "health",
          "reportCenter",
          "exportReadiness",
          "parityReleaseReadiness",
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
          refreshRunId.current === runId
            ? current.map((item) => (item.key === loader.key ? { ...item, status: "loading", detail: undefined, duration_ms: undefined } : item))
            : current
        );
        const startedAt = performance.now();
        try {
          const value = await loader.load();
          const durationMs = performance.now() - startedAt;
          setLoaderStatuses((current) =>
            refreshRunId.current === runId
              ? current.map((item) =>
                  item.key === loader.key
                    ? {
                        ...item,
                        status: "ok",
                        detail: `${loader.label} geladen in ${formatDurationMs(durationMs)}`,
                        duration_ms: durationMs
                      }
                    : item
                )
              : current
          );
          setSnapshot((current) => ({ ...current, [loader.key]: value as never }));
          return value;
        } catch (caught) {
          const durationMs = performance.now() - startedAt;
          const detail = caught instanceof Error ? caught.message : "fehlgeschlagen";
          setLoaderStatuses((current) =>
            refreshRunId.current === runId
              ? current.map((item) =>
                  item.key === loader.key
                    ? {
                        ...item,
                        status: "error",
                        detail: `${detail} nach ${formatDurationMs(durationMs)}`,
                        duration_ms: durationMs
                      }
                    : item
                )
              : current
          );
          throw caught;
        }
      };
      const results: PromiseSettledResult<unknown>[] = [];
      // The tax-year services share one DuckDB store and several deep FIFO/price scans.
      // Serial loading avoids cold-start contention while still streaming each result into the UI.
      const maxParallelLoaders = active === "tax" ? 1 : active === "dashboard" ? 3 : 6;
      for (let offset = 0; offset < loaders.length; offset += maxParallelLoaders) {
        const batch = loaders.slice(offset, offset + maxParallelLoaders);
        const batchResults = await Promise.allSettled(batch.map((loader) => runLoader(loader)));
        results.push(...batchResults);
      }
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
      if (refreshRunId.current !== runId) {
        return;
      }
      setSnapshot((current) => ({ ...current, ...nextSnapshot }));
      setLastRefreshAt(new Date().toISOString());
      setLastLoadFailureCount(failures.length);
      if (failures.length > 0) {
        setError(`Teilweise geladen. Fehlgeschlagen: ${failures.slice(0, 4).join(" | ")}${failures.length > 4 ? ` | +${failures.length - 4} weitere` : ""}`);
      }
    } catch (caught) {
      if (refreshRunId.current === runId) {
        setLastLoadFailureCount(1);
        setError(caught instanceof Error ? caught.message : "Unbekannter API-Fehler");
      }
    } finally {
      if (refreshRunId.current === runId) {
        setPageLoading(false);
        setLoading(false);
      }
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

  async function runSourceRegistry() {
    setSourceRegistryRunLoading(true);
    setError(null);
    setNotice("Quellen, Portfolio-Policies und Live-vs-Ledger-Mengen werden read-only abgeglichen.");
    try {
      const sourceRegistry = await postApi<NonNullable<Snapshot["sourceRegistry"]>>(
        "/api/v1/sources/registry/runs",
        undefined,
        180_000
      );
      setSnapshot((current) => ({ ...current, sourceRegistry }));
      setNotice(
        `Quellenregistry ${sourceRegistry.status}: ${sourceRegistry.entries_count} Eintraege, `
        + `${sourceRegistry.unregistered_observations_count} unregistrierte Gruppen, `
        + `${sourceRegistry.provider_coverage_gap_entries_count ?? 0} Provider-Grenzen, `
        + `${sourceRegistry.user_evidence_gap_entries_count ?? 0} echte Belegluecken, `
        + `${sourceRegistry.quantity_blocker_entries_count} materielle Mengengates.`
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Quellenregistry konnte nicht geprueft werden");
    } finally {
      setSourceRegistryRunLoading(false);
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

  async function runWalletFifoParallel() {
    setWalletFifoRunLoading(true);
    setError(null);
    setNotice(null);
    try {
      const walletFifoParallelRun = await postApi<NonNullable<Snapshot["walletFifoParallelRun"]>>(
        "/api/v1/tax/wallet-fifo-runs",
        {
          years: [2021, 2022, 2023, 2024, 2025, 2026],
          material_delta_threshold_eur: "0.01"
        },
        300_000
      );
      const [
        taxBmfComplianceMatrix,
        walletFifoMethodDeltaExplanation,
        walletFifoMethodAcceptance,
        bitgetStrategyFifoGaps,
        bitgetStrategyReconstruction,
        bitgetStrategyBasisDecision
      ] = await Promise.all([
        getApi<Snapshot["taxBmfComplianceMatrix"]>(
          "/api/v1/tax-methodology/bmf-compliance-matrix"
        ),
        getApi<Snapshot["walletFifoMethodDeltaExplanation"]>(
          `/api/v1/tax/wallet-fifo-runs/latest/method-delta-explanation?year=${encodeURIComponent(selectedTaxYear)}&event_limit=5`
        ),
        getApi<Snapshot["walletFifoMethodAcceptance"]>(
          "/api/v1/tax/wallet-fifo-runs/latest/method-acceptance"
        ),
        getApi<Snapshot["bitgetStrategyFifoGaps"]>(
          "/api/v1/tax/wallet-fifo/bitget-strategy-gaps"
        ),
        getApi<Snapshot["bitgetStrategyReconstruction"]>(
          "/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction"
        ),
        getApi<Snapshot["bitgetStrategyBasisDecision"]>(
          "/api/v1/tax/wallet-fifo/bitget-strategy-basis-decision"
        )
      ]);
      setSnapshot((current) => ({
        ...current,
        walletFifoParallelRun,
        walletFifoMethodDeltaExplanation,
        walletFifoMethodAcceptance,
        bitgetStrategyFifoGaps,
        bitgetStrategyReconstruction,
        bitgetStrategyBasisDecision,
        walletFifoMigrationRehearsal: null,
        walletFifoMigrationApplyReadiness: undefined,
        taxBmfComplianceMatrix
      }));
      setNotice(
        `Wallet-FIFO-Prueflauf ${walletFifoParallelRun.status}: Delta ${formatCurrency(walletFifoParallelRun.delta_gain_loss_eur)} EUR, `
        + `${walletFifoParallelRun.provider_basis_gap_count} belegte Provider-Basisluecken, `
        + `${walletFifoParallelRun.unexplained_unmatched_count} wirklich ungeklaerte Abgaenge.`
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Wallet-FIFO-Prueflauf fehlgeschlagen");
    } finally {
      setWalletFifoRunLoading(false);
    }
  }

  async function saveBitgetBasisDecision(payload: BitgetBasisDecisionPayload) {
    const runId = snapshot.bitgetStrategyBasisDecision?.run_id
      ?? snapshot.walletFifoParallelRun?.run_id;
    if (!runId) {
      setError("Ein gebundener Wallet-FIFO-Lauf fehlt.");
      return;
    }
    setBitgetBasisDecisionLoading(true);
    setError(null);
    setNotice("Bitget-Basismethodenentscheidung wird hashgebunden dokumentiert.");
    try {
      const result = await postApi<{
        decision_id: string;
        created: boolean;
        report: NonNullable<Snapshot["bitgetStrategyBasisDecision"]>;
      }>(
        `/api/v1/tax/wallet-fifo/bitget-strategy-basis-decision/${encodeURIComponent(runId)}`,
        payload,
        120_000
      );
      const [taxBmfComplianceMatrix, reviewDecisions] = await Promise.all([
        getApi<Snapshot["taxBmfComplianceMatrix"]>(
          "/api/v1/tax-methodology/bmf-compliance-matrix"
        ),
        getApi<Array<Record<string, unknown>>>("/api/v1/review/decisions")
      ]);
      setSnapshot((current) => ({
        ...current,
        bitgetStrategyBasisDecision: result.report,
        taxBmfComplianceMatrix,
        reviewDecisions
      }));
      setNotice(
        `Bitget-Entscheidung ${result.created ? "gespeichert" : "war bereits vorhanden"}: `
        + `${result.report.decision_status}. Produktive Steuerwirkung: keine.`
      );
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Bitget-Basismethodenentscheidung konnte nicht gespeichert werden"
      );
    } finally {
      setBitgetBasisDecisionLoading(false);
    }
  }

  async function runSwapFifoParallelPreview() {
    setSwapFifoParallelLoading(true);
    setError(null);
    setNotice("Preisrangfolgen-FIFO wird mit zwei unveraenderten In-Memory-Laeufen verglichen.");
    try {
      const report = await postApi<NonNullable<Snapshot["taxCryptoSwapFifoParallelPreview"]>>(
        "/api/v1/tax/crypto-swap-fifo-parallel-preview/run",
        { limit: 200 },
        300_000
      );
      setSnapshot((current) => ({
        ...current,
        taxCryptoSwapFifoParallelPreview: report
      }));
      setNotice(
        `Preis-FIFO ${report.status}: saldiertes G/V-Delta ${formatCurrency(report.gain_loss_delta_eur)} EUR, `
        + `absolute Jahresdeltas ${formatCurrency(report.absolute_year_gain_loss_delta_eur)} EUR. Keine Steuerdaten wurden geschrieben.`
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Preis-FIFO-Parallelvergleich fehlgeschlagen");
    } finally {
      setSwapFifoParallelLoading(false);
    }
  }

  async function runBmfCombinedFifoStaging() {
    setBmfCombinedFifoStagingLoading(true);
    setError(null);
    setNotice(
      "Gemeinsamer Preis-/Wallet-/Reward-Lauf gestartet. Die Berechnung bleibt read-only und kann mehrere Minuten dauern."
    );
    try {
      const report = await postApi<NonNullable<Snapshot["taxBmfCombinedFifoStaging"]>>(
        "/api/v1/tax/bmf-combined-fifo-staging/run",
        { years: [2021, 2022, 2023, 2024, 2025, 2026], limit: 200 },
        900_000
      );
      const eventEvidence = await postApi<NonNullable<Snapshot["taxBmfFifoEventEvidence"]>>(
        "/api/v1/tax/bmf-fifo-event-evidence/run",
        { limit: 200, issue_limit: 500, min_abs_delta_eur: "0.01" },
        120_000
      );
      const taxBmfComplianceMatrix = await getApi<Snapshot["taxBmfComplianceMatrix"]>(
        "/api/v1/tax-methodology/bmf-compliance-matrix"
      );
      setSnapshot((current) => ({
        ...current,
        taxBmfCombinedFifoStaging: report,
        taxBmfFifoEventEvidence: eventEvidence,
        taxBmfComplianceMatrix
      }));
      setNotice(
        `BMF-Gesamtstaging ${report.status}: Preisdelta ${formatCurrency(report.price_policy_delta_eur)} EUR, `
        + `Wallet-Delta ${formatCurrency(report.wallet_scope_delta_eur)} EUR, kombiniert ${formatCurrency(report.combined_delta_eur)} EUR. `
        + "Produktive Steuerdaten blieben unveraendert."
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "BMF-Gesamtstaging fehlgeschlagen");
    } finally {
      setBmfCombinedFifoStagingLoading(false);
    }
  }

  async function runBmfFifoEventEvidence(
    scopeMode: "priority_delta" | "full_ledger" = "priority_delta"
  ) {
    setBmfFifoEventEvidenceLoading(true);
    setError(null);
    setNotice(
      scopeMode === "full_ledger"
        ? "Der gesamte Ledger und FIFO-Steuergraph werden mit Rohimport, Referenzen und historischen Preisen gebunden."
        : "FIFO-Eventbelege werden mit Rohimport, TxID/CEX-Referenz und historischen Preisen neu gebunden."
    );
    try {
      const report = await postApi<NonNullable<Snapshot["taxBmfFifoEventEvidence"]>>(
        "/api/v1/tax/bmf-fifo-event-evidence/run",
        {
          limit: scopeMode === "full_ledger" ? 5000 : 200,
          issue_limit: scopeMode === "full_ledger" ? 5000 : 500,
          min_abs_delta_eur: "0.01",
          scope_mode: scopeMode
        },
        scopeMode === "full_ledger" ? 300_000 : 120_000
      );
      const taxBmfComplianceMatrix = await getApi<Snapshot["taxBmfComplianceMatrix"]>(
        "/api/v1/tax-methodology/bmf-compliance-matrix"
      );
      setSnapshot((current) => ({
        ...current,
        taxBmfFifoEventEvidence: report,
        taxBmfComplianceMatrix
      }));
      setNotice(
        `${report.full_ledger_scope ? "Gesamtledger" : "Eventbelege"} ${report.status}: `
        + `${report.raw_evidence_ready_count}/${report.unique_events_count} Rohbelege, `
        + `${report.derived_price_review_count} abgeleitete und ${report.stale_price_review_count} veraltete Preisanker. `
        + "Produktive Steuerdaten blieben unveraendert."
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "BMF-FIFO-Eventbelegpruefung fehlgeschlagen");
    } finally {
      setBmfFifoEventEvidenceLoading(false);
    }
  }

  async function runBmfEventPriceRemediation(execute: boolean) {
    setBmfEventPriceRemediationLoading(true);
    setError(null);
    setNotice(
      execute
        ? "Belegte ECB-/DefiLlama-Tagesanker werden additiv importiert; Tax-Tabellen bleiben unveraendert."
        : "ECB-/DefiLlama-Tagesanker werden live geprueft; der Dry-run schreibt keine Preise."
    );
    try {
      const report = await postApi<NonNullable<Snapshot["taxBmfEventPriceRemediation"]>>(
        "/api/v1/tax/bmf-event-price-remediation/run",
        { execute, include_roles: ["received", "given"], max_jobs: 1000, timeout_seconds: 20 },
        900_000
      );
      const taxBmfFifoEventEvidence = execute
        ? await getApi<Snapshot["taxBmfFifoEventEvidence"]>("/api/v1/tax/bmf-fifo-event-evidence/latest")
        : undefined;
      const taxBmfComplianceMatrix = await getApi<Snapshot["taxBmfComplianceMatrix"]>(
        "/api/v1/tax-methodology/bmf-compliance-matrix"
      );
      setSnapshot((current) => ({
        ...current,
        taxBmfEventPriceRemediation: report,
        ...(taxBmfFifoEventEvidence ? { taxBmfFifoEventEvidence } : {}),
        taxBmfComplianceMatrix
      }));
      setNotice(
        `Preisanker ${report.status}: ${report.imported_count} importiert, ${report.planned_count} geplant, `
        + `${report.failed_count} fehlgeschlagen, ${report.token_risk_blocked_count} durch Token-Risiko blockiert. `
        + "Tax-Tabellen blieben unveraendert."
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "BMF-Event-Preisremediation fehlgeschlagen");
    } finally {
      setBmfEventPriceRemediationLoading(false);
    }
  }

  async function runWalletFifoMigrationRehearsal() {
    setWalletFifoMigrationLoading(true);
    setError(null);
    setNotice(
      "Wallet-/Depot-FIFO wird in einer temporaeren Staging-Datenbank geprueft. Produktive Steuerdaten werden nicht veraendert."
    );
    try {
      const walletFifoMigrationRehearsal = await postApi<
        NonNullable<Snapshot["walletFifoMigrationRehearsal"]>
      >(
        "/api/v1/tax/wallet-fifo-migrations/rehearsals",
        { run_id: snapshot.walletFifoParallelRun?.run_id ?? null },
        300_000
      );
      const [taxBmfComplianceMatrix, walletFifoMigrationApplyReadiness] = await Promise.all([
        getApi<Snapshot["taxBmfComplianceMatrix"]>(
          "/api/v1/tax-methodology/bmf-compliance-matrix"
        ),
        getApi<Snapshot["walletFifoMigrationApplyReadiness"]>(
          "/api/v1/tax/wallet-fifo-migrations/apply-readiness"
        )
      ]);
      setSnapshot((current) => ({
        ...current,
        walletFifoMigrationRehearsal,
        walletFifoMigrationApplyReadiness,
        taxBmfComplianceMatrix
      }));
      const statusText = walletFifoMigrationRehearsal.migration_ready
        ? "Technisch und fachlich fuer eine kontrollierte Migration bereit"
        : walletFifoMigrationRehearsal.technical_ready
          ? "Technisch bereit; die explizite Methodenentscheidung ist noch offen"
          : "Technische Migrationsprobe blockiert";
      setNotice(
        `${statusText}. Produktiver Schreibzugriff: ${walletFifoMigrationRehearsal.production_write_performed ? "ja" : "nein"}.`
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Wallet-FIFO-Migrationsprobe fehlgeschlagen");
    } finally {
      setWalletFifoMigrationLoading(false);
    }
  }

  async function runDivorceValuationDossier() {
    setDivorceValuationRunLoading(true);
    setError(null);
    setNotice("Stichtagswerte und zwei Wallet-FIFO-Verlaeufe werden read-only rekonstruiert. Das kann mehrere Minuten dauern.");
    try {
      const divorceValuationRun = await postApi<NonNullable<Snapshot["divorceValuationRun"]>>(
        "/api/v1/divorce/valuation-runs",
        {
          separation_date: divorceCutoffDate,
          end_asset_date: divorceValuationDate,
          materiality_threshold_eur: divorceMaterialityEur || "1",
          material_delta_threshold_eur: "0.01"
        },
        900_000
      );
      const [divorceEqualization, taxBmfComplianceMatrix] = await Promise.all([
        getApi<Snapshot["divorceEqualization"]>(
          `/api/v1/divorce/equalization-summary?separation_date=${encodeURIComponent(divorceCutoffDate)}&end_asset_date=${encodeURIComponent(divorceValuationDate)}&materiality_threshold_eur=${encodeURIComponent(divorceMaterialityEur || "1")}`
        ),
        getApi<Snapshot["taxBmfComplianceMatrix"]>("/api/v1/tax-methodology/bmf-compliance-matrix")
      ]);
      setSnapshot((current) => ({
        ...current,
        divorceValuationRun,
        divorceEqualization,
        taxBmfComplianceMatrix
      }));
      setNotice(
        `Stichtags-Dossier ${divorceValuationRun.status}: ${formatCurrency(divorceValuationRun.cutoff_value_eur)} EUR am ${formatDate(divorceValuationRun.cutoff_at)}, `
        + `${formatCurrency(divorceValuationRun.valuation_value_eur)} EUR am ${formatDate(divorceValuationRun.valuation_at)}. `
        + `${divorceValuationRun.fifo_checkpoints.length} FIFO-Stichtage versioniert, `
        + `${divorceValuationRun.fifo_checkpoints.filter((checkpoint) => checkpoint.reused_existing_run === true).length} unveraenderte Beleglaeufe wiederverwendet.`
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Stichtags-Dossier fehlgeschlagen");
    } finally {
      setDivorceValuationRunLoading(false);
    }
  }

  async function acceptTradeRepublicValuation(documentSha256: string) {
    setTradeRepublicValuationLoading(true);
    setError(null);
    setNotice("Trade-Republic-Stichtagsbeleg wird validiert und als Review Decision gebunden.");
    try {
      const result = await postApi<{
        already_recorded: boolean;
        valuation_date: string;
        value_eur: string;
      }>(
        "/api/v1/divorce/trade-republic/valuation-decisions",
        {
          end_asset_date: divorceValuationDate,
          document_sha256: documentSha256,
          actor: "user"
        },
        120_000
      );
      const divorceEqualization = await getApi<Snapshot["divorceEqualization"]>(
        `/api/v1/divorce/equalization-summary?separation_date=${encodeURIComponent(divorceCutoffDate)}&end_asset_date=${encodeURIComponent(divorceValuationDate)}&materiality_threshold_eur=${encodeURIComponent(divorceMaterialityEur || "1")}`
      );
      setSnapshot((current) => ({ ...current, divorceEqualization }));
      setNotice(
        `Trade-Republic-Stichtagswert ${formatCurrency(result.value_eur)} EUR zum ${formatDate(result.valuation_date)} `
        + (result.already_recorded ? "war bereits freigegeben." : "wurde als Review Decision gespeichert.")
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Trade-Republic-Stichtagswert konnte nicht freigegeben werden");
    } finally {
      setTradeRepublicValuationLoading(false);
    }
  }

  async function uploadTradeRepublicDocuments(files: File[]) {
    if (files.length === 0) {
      return;
    }
    setTradeRepublicDocumentUploadLoading(true);
    setError(null);
    setNotice(`${files.length} Trade-Republic-Dokument(e) werden lokal gehasht und geprueft.`);
    try {
      let uploaded = 0;
      let alreadyPresent = 0;
      for (const file of files) {
        const formData = new FormData();
        formData.append("end_asset_date", divorceValuationDate);
        formData.append("file", file);
        const response = await fetchApiResponse<{
          already_present: boolean;
          connector: DivorceInheritanceOriginGate["trade_republic_connector"];
        }>(
          "/api/v1/divorce/trade-republic/documents",
          { method: "POST", body: formData },
          180_000
        );
        if (response.data.already_present) {
          alreadyPresent += 1;
        } else {
          uploaded += 1;
        }
      }
      const divorceEqualization = await getApi<Snapshot["divorceEqualization"]>(
        `/api/v1/divorce/equalization-summary?separation_date=${encodeURIComponent(divorceCutoffDate)}&end_asset_date=${encodeURIComponent(divorceValuationDate)}&materiality_threshold_eur=${encodeURIComponent(divorceMaterialityEur || "1")}`
      );
      setSnapshot((current) => ({ ...current, divorceEqualization }));
      setNotice(
        `Trade Republic: ${uploaded} Dokument(e) neu gespeichert, ${alreadyPresent} bereits hashgleich vorhanden. `
        + "Ein erkannter Stichtagswert bleibt bis zur Originalbeleg-Pruefung unfreigegeben."
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Trade-Republic-Dokumentimport fehlgeschlagen");
    } finally {
      setTradeRepublicDocumentUploadLoading(false);
    }
  }

  async function uploadInheritanceDocuments(files: File[]) {
    if (files.length === 0) {
      return;
    }
    setInheritanceDocumentUploadLoading(true);
    setError(null);
    setNotice(`${files.length} Erbnachweis-Dokument(e) werden lokal validiert und gehasht.`);
    try {
      let uploaded = 0;
      let alreadyPresent = 0;
      for (const file of files) {
        const formData = new FormData();
        formData.append("file", file);
        const response = await fetchApiResponse<{
          already_present: boolean;
          connector: DivorceInheritanceOriginGate["formal_inheritance_connector"];
        }>(
          "/api/v1/divorce/inheritance-documents",
          { method: "POST", body: formData },
          180_000
        );
        if (response.data.already_present) {
          alreadyPresent += 1;
        } else {
          uploaded += 1;
        }
      }
      const divorceEqualization = await getApi<Snapshot["divorceEqualization"]>(
        `/api/v1/divorce/equalization-summary?separation_date=${encodeURIComponent(divorceCutoffDate)}&end_asset_date=${encodeURIComponent(divorceValuationDate)}&materiality_threshold_eur=${encodeURIComponent(divorceMaterialityEur || "1")}`
      );
      setSnapshot((current) => ({ ...current, divorceEqualization }));
      setNotice(
        `Erbnachweis: ${uploaded} Dokument(e) neu gespeichert, ${alreadyPresent} bereits hashgleich vorhanden. `
        + "Der Nachweis bleibt bis zum Abgleich mit dem Original als Kandidat markiert."
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Erbnachweis-Dokumentimport fehlgeschlagen");
    } finally {
      setInheritanceDocumentUploadLoading(false);
    }
  }

  async function acceptInheritanceDocument(documentSha256: string) {
    setInheritanceDocumentReviewLoading(true);
    setError(null);
    setNotice("Der formale Erbnachweis wird als SHA-256-gebundene Review Decision gespeichert.");
    try {
      const result = await postApi<{
        already_recorded: boolean;
        document_sha256: string;
      }>(
        "/api/v1/divorce/inheritance-documents/review-decisions",
        { document_sha256: documentSha256, actor: "user" },
        120_000
      );
      const divorceEqualization = await getApi<Snapshot["divorceEqualization"]>(
        `/api/v1/divorce/equalization-summary?separation_date=${encodeURIComponent(divorceCutoffDate)}&end_asset_date=${encodeURIComponent(divorceValuationDate)}&materiality_threshold_eur=${encodeURIComponent(divorceMaterialityEur || "1")}`
      );
      setSnapshot((current) => ({ ...current, divorceEqualization }));
      setNotice(
        result.already_recorded
          ? "Der formale Erbnachweis war bereits freigegeben."
          : "Der formale Erbnachweis wurde geprueft und unveraenderlich an seine SHA-256-Summe gebunden."
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Erbnachweis konnte nicht freigegeben werden");
    } finally {
      setInheritanceDocumentReviewLoading(false);
    }
  }

  async function uploadBankCamtDocuments(files: File[]) {
    if (files.length === 0) {
      return;
    }
    setBankCamtUploadLoading(true);
    setError(null);
    setNotice(`${files.length} Sparkassen-CAMT-Export(e) werden validiert und mit dem vorhandenen Zeitraum zusammengefuehrt.`);
    try {
      let uploaded = 0;
      let alreadyPresent = 0;
      for (const file of files) {
        const formData = new FormData();
        formData.append("separation_date", divorceCutoffDate);
        formData.append("end_asset_date", divorceValuationDate);
        formData.append("file", file);
        const response = await fetchApiResponse<{
          uploaded_files: number;
          already_present_files: number;
        }>(
          "/api/v1/divorce/sparkasse-camt",
          { method: "POST", body: formData },
          240_000
        );
        uploaded += response.data.uploaded_files;
        alreadyPresent += response.data.already_present_files;
      }
      const divorceEqualization = await getApi<Snapshot["divorceEqualization"]>(
        `/api/v1/divorce/equalization-summary?separation_date=${encodeURIComponent(divorceCutoffDate)}&end_asset_date=${encodeURIComponent(divorceValuationDate)}&materiality_threshold_eur=${encodeURIComponent(divorceMaterialityEur || "1")}`
      );
      setSnapshot((current) => ({ ...current, divorceEqualization }));
      const bankStatus = divorceEqualization?.inheritance_origin_gate?.bank_statement_status ?? "missing";
      setNotice(
        `Sparkasse: ${uploaded} CAMT-Datei(en) neu gespeichert, ${alreadyPresent} bereits hashgleich vorhanden. `
        + `Zeitraumstatus: ${bankStatus}.`
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Sparkassen-CAMT-Import fehlgeschlagen");
    } finally {
      setBankCamtUploadLoading(false);
    }
  }

  async function acceptCoinbaseValuation(historyManifestSha256: string) {
    setCoinbaseValuationLoading(true);
    setError(null);
    setNotice("Coinbase-Historie, Ledger-Mengen und Stichtagspreise werden an die Review Decision gebunden.");
    try {
      const result = await postApi<{
        already_recorded: boolean;
        valuation_date: string;
        value_eur: string;
      }>(
        "/api/v1/divorce/coinbase/valuation-decisions",
        {
          end_asset_date: divorceValuationDate,
          history_manifest_sha256: historyManifestSha256,
          actor: "user"
        },
        180_000
      );
      const divorceEqualization = await getApi<Snapshot["divorceEqualization"]>(
        `/api/v1/divorce/equalization-summary?separation_date=${encodeURIComponent(divorceCutoffDate)}&end_asset_date=${encodeURIComponent(divorceValuationDate)}&materiality_threshold_eur=${encodeURIComponent(divorceMaterialityEur || "1")}`
      );
      setSnapshot((current) => ({ ...current, divorceEqualization }));
      setNotice(
        `Coinbase-Stichtagswert ${formatCurrency(result.value_eur)} EUR zum ${formatDate(result.valuation_date)} `
        + (result.already_recorded ? "war bereits freigegeben." : "wurde hashgebunden freigegeben.")
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Coinbase-Stichtagswert konnte nicht freigegeben werden");
    } finally {
      setCoinbaseValuationLoading(false);
    }
  }

  async function refreshDivorcePriceGates() {
    const [asOfCutoffPriceGate, asOfPriceGate, divorceEqualization] = await Promise.all([
      getApi<Snapshot["asOfCutoffPriceGate"]>(`/api/v1/prices/as-of-gate?as_of_date=${encodeURIComponent(divorceCutoffDate)}&materiality_threshold_eur=${encodeURIComponent(divorceMaterialityEur || "1")}`),
      getApi<Snapshot["asOfPriceGate"]>(`/api/v1/prices/as-of-gate?as_of_date=${encodeURIComponent(divorceValuationDate)}&materiality_threshold_eur=${encodeURIComponent(divorceMaterialityEur || "1")}`),
      getApi<Snapshot["divorceEqualization"]>(
        `/api/v1/divorce/equalization-summary?separation_date=${encodeURIComponent(divorceCutoffDate)}&end_asset_date=${encodeURIComponent(divorceValuationDate)}&materiality_threshold_eur=${encodeURIComponent(divorceMaterialityEur || "1")}`
      )
    ]);
    setSnapshot((current) => ({
      ...current,
      asOfCutoffPriceGate,
      asOfPriceGate,
      divorceEqualization
    }));
    return { asOfCutoffPriceGate, asOfPriceGate };
  }

  async function runAsOfPriceGateBackfill(
    dryRun: boolean,
    targetDate = divorceValuationDate
  ) {
    setAsOfPriceGateLoading(true);
    setError(null);
    setNotice(dryRun ? "Stichtagspreise werden ohne Schreibzugriff vorgeprueft." : "Belegte Stichtagspreise werden in das Price-Ledger geschrieben.");
    try {
      const asOfPriceGateBackfill = await postApi<NonNullable<Snapshot["asOfPriceGateBackfill"]>>(
        "/api/v1/prices/as-of-gate/backfill",
        {
          as_of_date: targetDate,
          materiality_threshold_eur: divorceMaterialityEur || "1",
          provider: "defillama",
          max_requests: 25,
          confidence: "0.99",
          dry_run: dryRun
        },
        180_000
      );
      const refreshed = await refreshDivorcePriceGates();
      const activeGate = targetDate === divorceCutoffDate
        ? refreshed.asOfCutoffPriceGate
        : refreshed.asOfPriceGate;
      setSnapshot((current) => ({ ...current, asOfPriceGateBackfill }));
      setNotice(
        `${dryRun ? "Preis-Preview" : "Preisimport"}: ${asOfPriceGateBackfill.attempted} geprueft, `
        + `${asOfPriceGateBackfill.imported_prices} importiert, ${asOfPriceGateBackfill.failed} fehlgeschlagen. `
        + `${activeGate?.requirements_count ?? 0} Preis-/Tokenreviews bleiben offen.`
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Stichtagspreis-Lauf fehlgeschlagen");
    } finally {
      setAsOfPriceGateLoading(false);
    }
  }

  async function acceptAsOfTokenValuation(asset: string, asOfDate: string) {
    setAsOfPriceGateLoading(true);
    setError(null);
    setNotice(`${asset} wird fuer den Stichtag ${asOfDate} beleggebunden geprueft.`);
    try {
      const result = await postApi<{
        already_recorded: boolean;
        decision: { decision_id: string };
        gate_after: AsOfPriceGateReport;
      }>(
        "/api/v1/prices/as-of-gate/token-review-decisions",
        {
          as_of_date: asOfDate,
          asset,
          materiality_threshold_eur: divorceMaterialityEur || "1",
          actor: "user"
        }
      );
      await refreshDivorcePriceGates();
      setNotice(
        `${asset}: Stichtagsbewertung ${result.already_recorded ? "war bereits dokumentiert" : "wurde dokumentiert"}. `
        + `Entscheidung ${result.decision.decision_id}.`
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Token-Stichtagsbewertung konnte nicht dokumentiert werden");
    } finally {
      setAsOfPriceGateLoading(false);
    }
  }

  async function refreshDivorceServiceRouteEvidence(txId: string) {
    setServiceRouteEvidenceLoading(true);
    setError(null);
    setNotice("Jupiter-Perps-Position und spaeterer On-chain-Verbleib werden geprueft.");
    try {
      const divorceServiceRouteEvidence = await postApi<DivorceServiceRouteEvidenceReport>(
        "/api/v1/divorce/service-route-evidence/refresh",
        {
          tx_id: txId,
          end_asset_date: divorceValuationDate,
          materiality_threshold_eur: divorceMaterialityEur || "1",
          timeout_seconds: 30
        },
        180_000
      );
      setSnapshot((current) => ({ ...current, divorceServiceRouteEvidence }));
      setNotice(
        divorceServiceRouteEvidence.strict_ready
          ? "On-chain-Lebenszyklus belegt: Collateral-Zufuehrung und vollstaendige Liquidation wurden gefunden. Die fachliche Freigabe bleibt separat."
          : `Service-Route bleibt offen: ${divorceServiceRouteEvidence.findings.join(" ")}`
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Service-Route konnte nicht geprueft werden");
    } finally {
      setServiceRouteEvidenceLoading(false);
    }
  }

  async function acceptDivorceServiceRouteEvidence(txId: string, semanticSha256: string) {
    setServiceRouteEvidenceLoading(true);
    setError(null);
    setNotice("Der gepruefte Jupiter-Perps-Lebenszyklus wird SHA-256-gebunden freigegeben.");
    try {
      const result = await postApi<{
        already_recorded: boolean;
        decision: { decision_id: string };
        evidence: DivorceServiceRouteEvidenceReport;
      }>(
        "/api/v1/divorce/service-route-evidence/decisions",
        {
          tx_id: txId,
          semantic_sha256: semanticSha256,
          actor: "user"
        },
        120_000
      );
      const divorceEqualizationResponse = await fetchApiResponse<Snapshot["divorceEqualization"]>(
        `/api/v1/divorce/equalization-summary?separation_date=${encodeURIComponent(divorceCutoffDate)}&end_asset_date=${encodeURIComponent(divorceValuationDate)}&materiality_threshold_eur=${encodeURIComponent(divorceMaterialityEur || "1")}`,
        {},
        180_000
      );
      const divorceEqualization = divorceEqualizationResponse.data;
      setSnapshot((current) => ({
        ...current,
        divorceEqualization,
        divorceServiceRouteEvidence: result.evidence
      }));
      setNotice(
        `Serviceposition ${result.already_recorded ? "war bereits" : "wurde"} als vollstaendig liquidierter Vermoegensverlust dokumentiert. Entscheidung ${result.decision.decision_id}; Steuer-FIFO bleibt unveraendert.`
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Service-Route konnte nicht freigegeben werden");
    } finally {
      setServiceRouteEvidenceLoading(false);
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

  async function addStablecoinFxAnchorDecision(row: Record<string, unknown>, action: string) {
    const asset = String(row.asset ?? "").trim();
    const year = Number(row.year ?? 0);
    const source = String(row.source ?? "derived:event_quote").trim() || "derived:event_quote";
    if (!asset || !year) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await postApi("/api/v1/prices/quality/stablecoin-fx-anchor-preview-decisions", {
        asset,
        year,
        source,
        action,
        rationale:
          action === "apply_replacement"
            ? "In der V2-Oberflaeche freigegebener Stablecoin-FX-Anker. Die Decision selbst schreibt keine Preise; der Apply-Pfad bleibt separat."
            : "In der V2-Oberflaeche dokumentierte Stablecoin-FX-Anker-Entscheidung ohne Preis-Write.",
        evidence_ref: "api:/api/v1/prices/quality/stablecoin-fx-anchor-preview-latest?include_rows=true"
      });
      setNotice(`Stablecoin-FX-Ankerentscheidung gespeichert: ${asset} ${year} ${action}`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Stablecoin-FX-Ankerentscheidung konnte nicht gespeichert werden");
      setLoading(false);
    }
  }

  async function applyStablecoinFxAnchor(row: Record<string, unknown>, dryRun: boolean) {
    const asset = String(row.asset ?? "").trim();
    const year = Number(row.year ?? 0);
    const source = String(row.source ?? "derived:event_quote").trim() || "derived:event_quote";
    if (!asset || !year) {
      return;
    }
    if (!dryRun && !window.confirm(`${asset} ${year}: Stablecoin-FX-Anker wirklich live anwenden und FIFO/Tax neu berechnen?`)) {
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const result = await postApi<Record<string, unknown>>(
        "/api/v1/prices/quality/stablecoin-fx-anchor-apply",
        {
          asset,
          year,
          source,
          dry_run: dryRun,
          confirm_apply: !dryRun
        },
        180_000
      );
      setNotice(
        dryRun
          ? `Stablecoin-FX-Anker Dry-Run: ${asset} ${year}, geplante Preiszeilen ${String(result.inserted_anchor_prices ?? 0)}`
          : `Stablecoin-FX-Anker angewendet: ${asset} ${year}, Preiszeilen ${String(result.inserted_anchor_prices ?? 0)}`
      );
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Stablecoin-FX-Anker-Apply konnte nicht ausgefuehrt werden");
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

  async function savePriorFilingDeclaredAmounts(years: Array<Record<string, unknown>>) {
    setLoading(true);
    setError(null);
    try {
      const result = await putApi<Record<string, unknown>>(
        "/api/v1/tax-methodology/bmf-prior-filing-declared-amounts",
        { years }
      );
      const written = Array.isArray(result.written_years) ? result.written_years.length : 0;
      setNotice(`Alt-Erklaerungswerte gespeichert: ${written} Jahr(e)`);
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Alt-Erklaerungswerte konnten nicht gespeichert werden");
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

  function navigateTo(section: Section) {
    setActive(section);
    setMobileNavOpen(false);
  }

  return (
    <main className="shell" aria-busy={pageLoading}>
      <button
        aria-label="Navigation schliessen"
        className={`mobileNavBackdrop ${mobileNavOpen ? "open" : ""}`}
        onClick={() => setMobileNavOpen(false)}
        type="button"
      />
      <aside aria-label="Hauptnavigation" className={`sidebar ${mobileNavOpen ? "open" : ""}`} id="main-navigation">
        <div className="sidebarHeader">
          <div className="brand">
            <strong>Steuerreport Cockpit</strong>
            <span>BMF/FIFO · Portfolio · Belege</span>
          </div>
          <button className="sidebarClose" type="button" onClick={() => setMobileNavOpen(false)} title="Navigation schliessen">
            <X size={20} />
          </button>
        </div>
        <nav>
          {(["workflow", "evidence", "expert"] as const).map((group) => (
            <div className="navGroup" key={group}>
              {group === "expert" && !showExpertNav ? (
                <button className="expertToggle" type="button" onClick={() => setShowExpertNav(true)}>
                  <Settings size={18} />
                  <span>Expertenwerkzeuge anzeigen</span>
                </button>
              ) : null}
              {group === "expert" && !showExpertNav ? null : (
                <>
              <span className="navGroupLabel">
                {group === "workflow" ? "Arbeitsablauf" : group === "evidence" ? "Auswertungen" : "Werkzeuge"}
              </span>
              {navItems.filter((item) => item.group === group).map((item) => (
                <button
                  key={item.id}
                  className={`${active === item.id ? "active" : ""} ${item.group === "expert" ? "expertNav" : ""}`}
                  onClick={() => navigateTo(item.id)}
                  type="button"
                  title={item.description}
                >
                  {item.icon}
                  <span>{item.label}</span>
                </button>
              ))}
              {group === "expert" ? (
                <button className="expertToggle" type="button" onClick={() => setShowExpertNav(false)}>
                  <Settings size={18} />
                  <span>Expertenwerkzeuge ausblenden</span>
                </button>
              ) : null}
                </>
              )}
            </div>
          ))}
        </nav>
      </aside>
      <section className="workspace">
        <header className="topbar">
          <div className="topbarTitle">
            <button
              aria-controls="main-navigation"
              aria-expanded={mobileNavOpen}
              aria-label="Navigation oeffnen"
              className="mobileNavToggle"
              onClick={() => setMobileNavOpen(true)}
              type="button"
            >
              <Menu size={20} />
            </button>
            <div>
              <h1>{activeLabel}</h1>
              <p>{activeDescription}</p>
            </div>
          </div>
          <div className="topbarStatus">
            <span className={`statusPill ${readinessTone(snapshot.productReadiness?.overall_status ?? "warning")}`}>
              {snapshot.productReadiness ? readinessLabel(snapshot.productReadiness.overall_status) : "Status laedt"}
            </span>
            {snapshot.productReadiness?.next_action ? <em>{snapshot.productReadiness.next_action}</em> : null}
          </div>
          <button className="statusButton" type="button" onClick={refresh} disabled={pageLoading}>
            <RefreshCcw className={pageLoading ? "spin" : ""} size={16} />
            {pageLoading ? "Laedt" : "Aktualisieren"}
          </button>
        </header>
        {error ? <div className="error">{error}</div> : null}
        {notice ? <div className="notice">{notice}</div> : null}
        <LoadingStatusPanel
          loading={pageLoading}
          statuses={loaderStatuses}
          activeLabel={activeLabel}
          lastRefreshAt={lastRefreshAt}
          lastLoadFailureCount={lastLoadFailureCount}
        />
        <Content
          active={active}
          snapshot={snapshot}
          onRebuildFlows={rebuildFlows}
          onRebuildTax={rebuildTax}
          onRunWalletFifoParallel={runWalletFifoParallel}
          walletFifoRunLoading={walletFifoRunLoading}
          onSaveBitgetBasisDecision={saveBitgetBasisDecision}
          bitgetBasisDecisionLoading={bitgetBasisDecisionLoading}
          onRunSwapFifoParallelPreview={runSwapFifoParallelPreview}
          swapFifoParallelLoading={swapFifoParallelLoading}
          onRunBmfCombinedFifoStaging={runBmfCombinedFifoStaging}
          bmfCombinedFifoStagingLoading={bmfCombinedFifoStagingLoading}
          onRunBmfFifoEventEvidence={runBmfFifoEventEvidence}
          bmfFifoEventEvidenceLoading={bmfFifoEventEvidenceLoading}
          onRunBmfEventPriceRemediation={runBmfEventPriceRemediation}
          bmfEventPriceRemediationLoading={bmfEventPriceRemediationLoading}
          onRunWalletFifoMigrationRehearsal={runWalletFifoMigrationRehearsal}
          walletFifoMigrationLoading={walletFifoMigrationLoading}
          onRunDivorceValuationDossier={runDivorceValuationDossier}
          divorceValuationRunLoading={divorceValuationRunLoading}
          onAcceptTradeRepublicValuation={acceptTradeRepublicValuation}
          tradeRepublicValuationLoading={tradeRepublicValuationLoading}
          onUploadTradeRepublicDocuments={uploadTradeRepublicDocuments}
          tradeRepublicDocumentUploadLoading={tradeRepublicDocumentUploadLoading}
          onUploadInheritanceDocuments={uploadInheritanceDocuments}
          inheritanceDocumentUploadLoading={inheritanceDocumentUploadLoading}
          onAcceptInheritanceDocument={acceptInheritanceDocument}
          inheritanceDocumentReviewLoading={inheritanceDocumentReviewLoading}
          onUploadBankCamtDocuments={uploadBankCamtDocuments}
          bankCamtUploadLoading={bankCamtUploadLoading}
          onAcceptCoinbaseValuation={acceptCoinbaseValuation}
          coinbaseValuationLoading={coinbaseValuationLoading}
          onRunAsOfPriceGateBackfill={runAsOfPriceGateBackfill}
          onAcceptAsOfTokenValuation={acceptAsOfTokenValuation}
          asOfPriceGateLoading={asOfPriceGateLoading}
          onRefreshDivorceServiceRouteEvidence={refreshDivorceServiceRouteEvidence}
          onAcceptDivorceServiceRouteEvidence={acceptDivorceServiceRouteEvidence}
          serviceRouteEvidenceLoading={serviceRouteEvidenceLoading}
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
          onAddStablecoinFxAnchorDecision={addStablecoinFxAnchorDecision}
          onApplyStablecoinFxAnchor={applyStablecoinFxAnchor}
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
          onSavePriorFilingDeclaredAmounts={savePriorFilingDeclaredAmounts}
          onDeleteV1Reference={deleteV1Reference}
          onAcceptReviewSuggestion={acceptReviewSuggestion}
          onCanonicalizeReviewEvidenceTraces={canonicalizeReviewEvidenceTraces}
          onCreateAiTask={createAiTask}
          onDeleteAiTask={deleteAiTask}
          onNavigate={navigateTo}
          onRefreshConfiguredSources={refreshConfiguredSources}
          sourceRefreshLoading={sourceRefreshLoading}
          onRunSourceRegistry={runSourceRegistry}
          sourceRegistryRunLoading={sourceRegistryRunLoading}
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
          divorceCutoffDate={divorceCutoffDate}
          onDivorceCutoffDateChange={setDivorceCutoffDate}
          divorceValuationDate={divorceValuationDate}
          onDivorceValuationDateChange={setDivorceValuationDate}
          divorceMaterialityEur={divorceMaterialityEur}
          onDivorceMaterialityEurChange={setDivorceMaterialityEur}
          minHoldingValueEur={minHoldingValueEur}
          onMinHoldingValueEurChange={setMinHoldingValueEur}
          jupiterTokenQuery={jupiterTokenQuery}
          onJupiterTokenQueryChange={setJupiterTokenQuery}
        />
      </section>
    </main>
  );
}

function LoadingStatusPanel({
  loading,
  statuses,
  activeLabel,
  lastRefreshAt,
  lastLoadFailureCount
}: {
  loading: boolean;
  statuses: LoaderStatus[];
  activeLabel: string;
  lastRefreshAt: string | null;
  lastLoadFailureCount: number;
}) {
  if (statuses.length === 0 && !lastRefreshAt) {
    return null;
  }
  const done = statuses.filter((item) => item.status === "ok" || item.status === "error").length;
  const failed = statuses.filter((item) => item.status === "error").length;
  const active = statuses.find((item) => item.status === "loading") ?? statuses.find((item) => item.status === "pending");
  const slowStatuses = statuses
    .filter((item) => item.status === "ok" && Number(item.duration_ms ?? 0) >= 5000)
    .sort((left, right) => Number(right.duration_ms ?? 0) - Number(left.duration_ms ?? 0));
  const progress = statuses.length > 0 ? Math.round((done / statuses.length) * 100) : 100;
  const slowSummary = slowStatuses
    .slice(0, 3)
    .map((item) => `${item.label} ${formatDurationMs(item.duration_ms)}`)
    .join(" · ");
  if (!loading && failed === 0 && slowStatuses.length === 0) {
    return (
      <section className="loadingPanel compact" aria-live="polite">
        <div className="loadingPanelHeader">
          <div>
            <strong>Datenstand {lastRefreshAt ? formatDateTime(lastRefreshAt) : "-"}</strong>
            <span>{activeLabel}: {done || statuses.length} Datenpaket(e) geladen{lastLoadFailureCount > 0 ? `, ${lastLoadFailureCount} fehlgeschlagen` : ""}.</span>
          </div>
          <span className="loadingPercent">bereit</span>
        </div>
      </section>
    );
  }
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
  onRunWalletFifoParallel,
  walletFifoRunLoading,
  onSaveBitgetBasisDecision,
  bitgetBasisDecisionLoading,
  onRunSwapFifoParallelPreview,
  swapFifoParallelLoading,
  onRunBmfCombinedFifoStaging,
  bmfCombinedFifoStagingLoading,
  onRunBmfFifoEventEvidence,
  bmfFifoEventEvidenceLoading,
  onRunBmfEventPriceRemediation,
  bmfEventPriceRemediationLoading,
  onRunWalletFifoMigrationRehearsal,
  walletFifoMigrationLoading,
  onRunDivorceValuationDossier,
  divorceValuationRunLoading,
  onAcceptTradeRepublicValuation,
  tradeRepublicValuationLoading,
  onUploadTradeRepublicDocuments,
  tradeRepublicDocumentUploadLoading,
  onUploadInheritanceDocuments,
  inheritanceDocumentUploadLoading,
  onAcceptInheritanceDocument,
  inheritanceDocumentReviewLoading,
  onUploadBankCamtDocuments,
  bankCamtUploadLoading,
  onAcceptCoinbaseValuation,
  coinbaseValuationLoading,
  onRunAsOfPriceGateBackfill,
  onAcceptAsOfTokenValuation,
  asOfPriceGateLoading,
  onRefreshDivorceServiceRouteEvidence,
  onAcceptDivorceServiceRouteEvidence,
  serviceRouteEvidenceLoading,
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
  onAddStablecoinFxAnchorDecision,
  onApplyStablecoinFxAnchor,
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
  onSavePriorFilingDeclaredAmounts,
  onDeleteV1Reference,
  onAcceptReviewSuggestion,
  onCanonicalizeReviewEvidenceTraces,
  onCreateAiTask,
  onDeleteAiTask,
  onNavigate,
  onRefreshConfiguredSources,
  sourceRefreshLoading,
  onRunSourceRegistry,
  sourceRegistryRunLoading,
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
  divorceCutoffDate,
  onDivorceCutoffDateChange,
  divorceValuationDate,
  onDivorceValuationDateChange,
  divorceMaterialityEur,
  onDivorceMaterialityEurChange,
  minHoldingValueEur,
  onMinHoldingValueEurChange,
  jupiterTokenQuery,
  onJupiterTokenQueryChange
}: {
  active: Section;
  snapshot: Snapshot;
  onRebuildFlows: () => void;
  onRebuildTax: () => void;
  onRunWalletFifoParallel: () => void;
  walletFifoRunLoading: boolean;
  onSaveBitgetBasisDecision: (payload: BitgetBasisDecisionPayload) => void;
  bitgetBasisDecisionLoading: boolean;
  onRunSwapFifoParallelPreview: () => void;
  swapFifoParallelLoading: boolean;
  onRunBmfCombinedFifoStaging: () => void;
  bmfCombinedFifoStagingLoading: boolean;
  onRunBmfFifoEventEvidence: (
    scopeMode?: "priority_delta" | "full_ledger"
  ) => void;
  bmfFifoEventEvidenceLoading: boolean;
  onRunBmfEventPriceRemediation: (execute: boolean) => void;
  bmfEventPriceRemediationLoading: boolean;
  onRunWalletFifoMigrationRehearsal: () => void;
  walletFifoMigrationLoading: boolean;
  onRunDivorceValuationDossier: () => void;
  divorceValuationRunLoading: boolean;
  onAcceptTradeRepublicValuation: (documentSha256: string) => void;
  tradeRepublicValuationLoading: boolean;
  onUploadTradeRepublicDocuments: (files: File[]) => void;
  tradeRepublicDocumentUploadLoading: boolean;
  onUploadInheritanceDocuments: (files: File[]) => void;
  inheritanceDocumentUploadLoading: boolean;
  onAcceptInheritanceDocument: (documentSha256: string) => void;
  inheritanceDocumentReviewLoading: boolean;
  onUploadBankCamtDocuments: (files: File[]) => void;
  bankCamtUploadLoading: boolean;
  onAcceptCoinbaseValuation: (historyManifestSha256: string) => void;
  coinbaseValuationLoading: boolean;
  onRunAsOfPriceGateBackfill: (dryRun: boolean, targetDate?: string) => void;
  onAcceptAsOfTokenValuation: (asset: string, asOfDate: string) => void;
  asOfPriceGateLoading: boolean;
  onRefreshDivorceServiceRouteEvidence: (txId: string) => void;
  onAcceptDivorceServiceRouteEvidence: (
    txId: string,
    semanticSha256: string
  ) => void;
  serviceRouteEvidenceLoading: boolean;
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
  onAddStablecoinFxAnchorDecision: (row: Record<string, unknown>, action: string) => void;
  onApplyStablecoinFxAnchor: (row: Record<string, unknown>, dryRun: boolean) => void;
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
  onSavePriorFilingDeclaredAmounts: (years: Array<Record<string, unknown>>) => void;
  onDeleteV1Reference: (referenceId: string) => void;
  onAcceptReviewSuggestion: (suggestionId: string) => void;
  onCanonicalizeReviewEvidenceTraces: (execute: boolean) => void;
  onCreateAiTask: (taskType: string, prompt: string, allowExternal: boolean) => void;
  onDeleteAiTask: (taskId: string) => void;
  onNavigate: (section: Section) => void;
  onRefreshConfiguredSources: () => void;
  sourceRefreshLoading: boolean;
  onRunSourceRegistry: () => void;
  sourceRegistryRunLoading: boolean;
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
  divorceCutoffDate: string;
  onDivorceCutoffDateChange: (date: string) => void;
  divorceValuationDate: string;
  onDivorceValuationDateChange: (date: string) => void;
  divorceMaterialityEur: string;
  onDivorceMaterialityEurChange: (value: string) => void;
  minHoldingValueEur: string;
  onMinHoldingValueEurChange: (value: string) => void;
  jupiterTokenQuery: string;
  onJupiterTokenQueryChange: (query: string) => void;
}) {
  if (active === "dashboard") {
    return (
      <CockpitDashboard
        summary={snapshot.cockpit}
        readiness={snapshot.productReadiness}
        database={snapshot.health}
        taxYearsSummary={snapshot.taxYearsSummary}
        taxPaymentOverview={snapshot.taxPaymentOverview}
        taxYearFilingMatrix={snapshot.taxYearFilingMatrix}
        taxFilingClosureOverview={snapshot.taxFilingClosureOverview}
        selectedTaxYear={selectedTaxYear}
        onSelectedTaxYearChange={onSelectedTaxYearChange}
        onDownload={onDownload}
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
          connectorCatalog={snapshot.connectorCatalog}
          connectorDiagnostics={snapshot.sourceConnectorDiagnostics}
          sourceRegistry={snapshot.sourceRegistry}
          detail={snapshot.sourceDetail}
          sourceReconciliation={snapshot.sourceReconciliation}
          sourceReconciliationEvidence={snapshot.sourceReconciliationEvidence}
          binanceEarnHistoryPreflight={snapshot.binanceEarnHistoryPreflight}
          binanceEarnHistoryApiPreview={snapshot.binanceEarnHistoryApiPreview}
          selectedSourceId={selectedSourceId}
          onSelectedSourceIdChange={onSelectedSourceIdChange}
          onNavigate={onNavigate}
          onRefreshConfiguredSources={onRefreshConfiguredSources}
          sourceRefreshLoading={sourceRefreshLoading}
          onRunSourceRegistry={onRunSourceRegistry}
          sourceRegistryRunLoading={sourceRegistryRunLoading}
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
          lossPlanner={snapshot.taxLossRealizationPlanner}
          priceCoverage={snapshot.priceCoverage}
          onViewModeChange={onPortfolioViewModeChange}
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
          title="Technische Belegkonten (nicht Vermoegen)"
          rows={snapshot.portfolio?.excluded_account_summary ?? []}
          footer={`${snapshot.portfolio?.excluded_value_semantics ?? "Kein Konto- oder Portfoliobestand; nicht zum Gesamtwert addieren."} Rechnerischer Diagnosewert: ${formatCurrency(snapshot.portfolio?.excluded_value_eur)} EUR.`}
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
              stablecoinFxAnchorPreview={snapshot.priceStablecoinFxAnchorPreview}
              solscanSignatureReview={snapshot.priceSolscanSignatureReview}
              binanceNormalizerReview={snapshot.priceBinanceNormalizerReview}
              eventQuoteEvidenceReview={snapshot.priceEventQuoteEvidenceReview}
              onDownload={onDownload}
              onAddDecision={onAddPriceQualityDecision}
              onAddStablecoinFxAnchorDecision={onAddStablecoinFxAnchorDecision}
              onApplyStablecoinFxAnchor={onApplyStablecoinFxAnchor}
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
        history={snapshot.portfolioValueHistory}
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
        taxBmfComplianceMatrix={snapshot.taxBmfComplianceMatrix}
        legalResearchFreshness={snapshot.legalResearchFreshness}
        walletFifoParallelRun={snapshot.walletFifoParallelRun}
        bitgetStrategyFifoGaps={snapshot.bitgetStrategyFifoGaps}
        bitgetStrategyReconstruction={snapshot.bitgetStrategyReconstruction}
        bitgetStrategyBasisDecision={snapshot.bitgetStrategyBasisDecision}
        walletFifoMethodDeltaExplanation={snapshot.walletFifoMethodDeltaExplanation}
        walletFifoMethodAcceptance={snapshot.walletFifoMethodAcceptance}
        walletFifoMigrationRehearsal={snapshot.walletFifoMigrationRehearsal}
        walletFifoMigrationApplyReadiness={snapshot.walletFifoMigrationApplyReadiness}
        taxBmfActionPlan={snapshot.taxBmfActionPlan}
        taxBmfFinalizationMatrix={snapshot.taxBmfFinalizationMatrix}
        taxBmfSubmissionGuide={snapshot.taxBmfSubmissionGuide}
        taxBmfPriorFilingComparison={snapshot.taxBmfPriorFilingComparison}
        taxBmfPriorFilingDeclaredAmounts={snapshot.taxBmfPriorFilingDeclaredAmounts}
        taxBmfAmendmentWorklist={snapshot.taxBmfAmendmentWorklist}
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
        pionexHntReconciliation={snapshot.pionexHntReconciliation}
        crossCexTransferEvidence={snapshot.crossCexTransferEvidence}
        fairspotStakingReconciliation={snapshot.fairspotStakingReconciliation}
        solanaStakingPositionReconciliation={snapshot.solanaStakingPositionReconciliation}
        moonpayReceipts={snapshot.moonpayReceipts}
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
        taxBusinessRewardInventoryReview={snapshot.taxBusinessRewardInventoryReview}
        taxCryptoSwapValuationReview={snapshot.taxCryptoSwapValuationReview}
        taxCryptoSwapFifoParallelPreview={snapshot.taxCryptoSwapFifoParallelPreview}
        taxBmfCombinedFifoStaging={snapshot.taxBmfCombinedFifoStaging}
        taxBmfFifoEventEvidence={snapshot.taxBmfFifoEventEvidence}
        taxBmfEventPriceRemediation={snapshot.taxBmfEventPriceRemediation}
        taxYearDrivers={snapshot.taxYearDrivers}
        taxYearGainLossRealityCheck={snapshot.taxYearGainLossRealityCheck}
        taxYearGainEvidenceReview={snapshot.taxYearGainEvidenceReview}
        taxYearGainEvidencePriceDeltas={snapshot.taxYearGainEvidencePriceDeltas}
        taxYearGainEvidenceEventDeltas={snapshot.taxYearGainEvidenceEventDeltas}
        taxYearGainEvidenceAcquisitionEventDeltas={snapshot.taxYearGainEvidenceAcquisitionEventDeltas}
        taxYearTurnoverAudit={snapshot.taxYearTurnoverAudit}
        taxYearsTurnoverAuditSummary={snapshot.taxYearsTurnoverAuditSummary}
        taxSolanaProgramIncomeReview={snapshot.taxSolanaProgramIncomeReview}
        taxHeliumSwapContext={snapshot.taxHeliumSwapContext}
        taxHeliumSwapEvidenceReview={snapshot.taxHeliumSwapEvidenceReview}
        taxHeliumSwapAlchemyAudit={snapshot.taxHeliumSwapAlchemyAudit}
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
        onRunWalletFifoParallel={onRunWalletFifoParallel}
        walletFifoRunLoading={walletFifoRunLoading}
        onSaveBitgetBasisDecision={onSaveBitgetBasisDecision}
        bitgetBasisDecisionLoading={bitgetBasisDecisionLoading}
        onRunSwapFifoParallelPreview={onRunSwapFifoParallelPreview}
        swapFifoParallelLoading={swapFifoParallelLoading}
        onRunBmfCombinedFifoStaging={onRunBmfCombinedFifoStaging}
        bmfCombinedFifoStagingLoading={bmfCombinedFifoStagingLoading}
        onRunBmfFifoEventEvidence={onRunBmfFifoEventEvidence}
        bmfFifoEventEvidenceLoading={bmfFifoEventEvidenceLoading}
        onRunBmfEventPriceRemediation={onRunBmfEventPriceRemediation}
        bmfEventPriceRemediationLoading={bmfEventPriceRemediationLoading}
        onRunWalletFifoMigrationRehearsal={onRunWalletFifoMigrationRehearsal}
        walletFifoMigrationLoading={walletFifoMigrationLoading}
        onRebuildDerivatives={onRebuildDerivatives}
        onAddCexSenderOwnershipDecision={onAddCexSenderOwnershipDecision}
        onSavePriorFilingDeclaredAmounts={onSavePriorFilingDeclaredAmounts}
        onDownload={onDownload}
      />
    );
  }
  if (active === "zugewinn") {
    return (
      <DivorceEqualizationPanel
        report={snapshot.divorceEqualization}
        valuationRun={snapshot.divorceValuationRun}
        cutoffPriceGate={snapshot.asOfCutoffPriceGate}
        priceGate={snapshot.asOfPriceGate}
        cutoffDate={divorceCutoffDate}
        onCutoffDateChange={onDivorceCutoffDateChange}
        valuationDate={divorceValuationDate}
        onValuationDateChange={onDivorceValuationDateChange}
        materialityEur={divorceMaterialityEur}
        onMaterialityEurChange={onDivorceMaterialityEurChange}
        onRunDossier={onRunDivorceValuationDossier}
        runLoading={divorceValuationRunLoading}
        onAcceptTradeRepublicValuation={onAcceptTradeRepublicValuation}
        tradeRepublicValuationLoading={tradeRepublicValuationLoading}
        onUploadTradeRepublicDocuments={onUploadTradeRepublicDocuments}
        tradeRepublicDocumentUploadLoading={tradeRepublicDocumentUploadLoading}
        onUploadInheritanceDocuments={onUploadInheritanceDocuments}
        inheritanceDocumentUploadLoading={inheritanceDocumentUploadLoading}
        onAcceptInheritanceDocument={onAcceptInheritanceDocument}
        inheritanceDocumentReviewLoading={inheritanceDocumentReviewLoading}
        onUploadBankCamtDocuments={onUploadBankCamtDocuments}
        bankCamtUploadLoading={bankCamtUploadLoading}
        onAcceptCoinbaseValuation={onAcceptCoinbaseValuation}
        coinbaseValuationLoading={coinbaseValuationLoading}
        priceGateLoading={asOfPriceGateLoading}
        onRunPriceGateBackfill={onRunAsOfPriceGateBackfill}
        onAcceptTokenValuation={onAcceptAsOfTokenValuation}
        serviceRouteEvidence={snapshot.divorceServiceRouteEvidence}
        onRefreshServiceRouteEvidence={onRefreshDivorceServiceRouteEvidence}
        onAcceptServiceRouteEvidence={onAcceptDivorceServiceRouteEvidence}
        serviceRouteEvidenceLoading={serviceRouteEvidenceLoading}
        onDownload={onDownload}
        onNavigate={onNavigate}
      />
    );
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
          parityReleaseReadiness={snapshot.parityReleaseReadiness}
          exportViewMode={exportViewMode}
          onExportViewModeChange={onExportViewModeChange}
          onCreatePdfExport={onCreatePdfExport}
          onRunReportAction={onRunReportAction}
          onAddParityDecision={onAddParityDecision}
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
        <AdminCexCredentialForm
          connectorDiagnostics={snapshot.sourceConnectorDiagnostics}
          onSaveCexCredentials={onSaveCexCredentials}
          onRefreshConfiguredSources={onRefreshConfiguredSources}
          sourceRefreshLoading={sourceRefreshLoading}
        />
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
              letzter_api_versuch: row.last_attempt?.attempted_at ? formatDateTime(row.last_attempt.attempted_at) : "-",
              api_ergebnis: row.last_attempt?.status ?? "-",
              api_meldung: row.last_attempt?.message ?? "-",
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
  connectorCatalog,
  connectorDiagnostics,
  sourceRegistry,
  detail,
  sourceReconciliation,
  sourceReconciliationEvidence,
  binanceEarnHistoryPreflight,
  binanceEarnHistoryApiPreview,
  selectedSourceId,
  onSelectedSourceIdChange,
  onNavigate,
  onRefreshConfiguredSources,
  sourceRefreshLoading,
  onRunSourceRegistry,
  sourceRegistryRunLoading,
  sourceViewMode,
  onSourceViewModeChange
}: {
  overview: Snapshot["sourcesOverview"];
  connectorCatalog: Snapshot["connectorCatalog"];
  connectorDiagnostics: Snapshot["sourceConnectorDiagnostics"];
  sourceRegistry: Snapshot["sourceRegistry"];
  detail: Snapshot["sourceDetail"];
  sourceReconciliation: Snapshot["sourceReconciliation"];
  sourceReconciliationEvidence: Snapshot["sourceReconciliationEvidence"];
  binanceEarnHistoryPreflight: Snapshot["binanceEarnHistoryPreflight"];
  binanceEarnHistoryApiPreview: Snapshot["binanceEarnHistoryApiPreview"];
  selectedSourceId: string | null;
  onSelectedSourceIdChange: (sourceId: string) => void;
  onNavigate: (section: Section) => void;
  onRefreshConfiguredSources: () => void;
  sourceRefreshLoading: boolean;
  onRunSourceRegistry: () => void;
  sourceRegistryRunLoading: boolean;
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
  const overviewReady = Boolean(overview);
  const registryReady = Boolean(sourceRegistry);

  return (
    <Stack>
      <section className="sourcesHero">
        <div>
          <span className="heroKicker">Quellen-Cockpit</span>
          <h2>{overviewReady ? `${formatCurrency(totalValue)} EUR` : "Quellen werden geladen"}</h2>
          <p>Eigene Wallets und Handelsplattformen mit aktuellem Live-, Ledger- und Belegstatus.</p>
          {overview?.methodology ? (
            <details className="cockpitDetails sourceMethodology">
              <summary>Bewertungsmethode</summary>
              <p>{overview.methodology}</p>
            </details>
          ) : null}
          <div className="sourceHeroActions">
            <button type="button" onClick={onRefreshConfiguredSources} disabled={sourceRefreshLoading}>
              <WalletCards size={16} />
              <span>{sourceRefreshLoading ? "Quellen werden abgefragt" : "Alle konfigurierten Quellen per API abfragen"}</span>
            </button>
          </div>
        </div>
        <div className="sourceHeroStats">
          <Metric title="Quellen" value={overviewReady ? String(sources.length) : "Wird geladen"} />
          <Metric title="Ausgewaehlt" value={overviewReady && selected ? String(selected.label) : "Wird geladen"} />
          <Metric title="Live verbunden" value={health ? `${health.live_connected_sources}/${health.sources_count ?? sources.length}` : "Wird geladen"} />
          <Metric title="Live veraltet" value={health ? String(health.stale_live_sources ?? 0) : "Wird geladen"} />
          <Metric title="Ledger-only" value={health ? String(health.ledger_only_sources ?? sources.length) : "Wird geladen"} />
          <Metric title="Issues" value={health ? String(healthIssues) : "Wird geladen"} />
        </div>
      </section>
      {health ? (
        <div className={`notice inlineNotice sourceHealthNotice ${String(health.status)}`}>
          Quellenstatus: {sourceHealthLabel(health.status)} · {health.detail}
          {health.missing_live_sources > 0 ? ` · ${health.missing_live_sources} Live-Anker fehlen` : ""}
        </div>
      ) : null}
      <MobileConnectorCatalog catalog={connectorCatalog} />
      <section className="sourceRegistryBand">
        <div className="sourceRegistryHeader">
          <div>
            <span className="heroKicker">Ownership und Abdeckung</span>
            <h3>Zeitabhaengige Quellenregistry</h3>
            <p>Legt fest, welche Adressen zum Portfolio gehoeren und welche nur Transfer- oder Servicepfade belegen.</p>
          </div>
          <div className="toolbarActions">
            <span className={`statusPill ${!registryReady ? "loading" : sourceRegistry?.strict_ready ? "ok" : sourceRegistry?.status === "blocked" ? "blocked" : "warning"}`}>
              {sourceRegistry?.status ?? "wird geladen"}
            </span>
            <button type="button" onClick={onRunSourceRegistry} disabled={sourceRegistryRunLoading}>
              <ClipboardCheck size={16} />
              {sourceRegistryRunLoading ? "Registry wird geprueft" : "Registry pruefen"}
            </button>
          </div>
        </div>
        <div className="sourceRegistryMetrics">
          <Metric title="Eintraege" value={registryReady ? String(sourceRegistry?.entries_count ?? 0) : "Wird geladen"} />
          <Metric title="Eigene Quellen" value={registryReady ? String(sourceRegistry?.owned_entries_count ?? 0) : "Wird geladen"} />
          <Metric title="Abdeckung partial" value={registryReady ? String(sourceRegistry?.partial_entries_count ?? 0) : "Wird geladen"} />
          <Metric title="Provider-Grenzen" value={registryReady ? String(sourceRegistry?.provider_coverage_gap_entries_count ?? 0) : "Wird geladen"} />
          <Metric title="Echte Belegluecken" value={registryReady ? String(sourceRegistry?.user_evidence_gap_entries_count ?? 0) : "Wird geladen"} />
          <Metric title="Belegte Servicepfade" value={registryReady ? String(sourceRegistry?.documented_route_entries_count ?? 0) : "Wird geladen"} />
          <Metric title="Unregistriert" value={registryReady ? String(sourceRegistry?.unregistered_observations_count ?? 0) : "Wird geladen"} />
          <Metric title="Portfolio-Policy" value={registryReady ? String(sourceRegistry?.portfolio_policy_violations_count ?? 0) : "Wird geladen"} />
          <Metric title="Mengengate" value={registryReady ? String(sourceRegistry?.quantity_blocker_entries_count ?? 0) : "Wird geladen"} />
          <Metric title="Belegkorrekturen" value={registryReady ? String(sourceRegistry?.applied_ledger_adjustments_count ?? 0) : "Wird geladen"} />
          <Metric title="Transferbelege" value={registryReady ? String(sourceRegistry?.approved_transfer_evidence_count ?? 0) : "Wird geladen"} />
        </div>
        {sourceRegistry?.methodology ? (
          <details className="cockpitDetails sourceMethodology">
            <summary>Registry-Methode und Grenzen</summary>
            <p>{sourceRegistry.methodology}</p>
          </details>
        ) : null}
        {(sourceRegistry?.findings ?? []).length > 0 ? (
          <div className="sourceRegistryFindings">
            {(sourceRegistry?.findings ?? []).slice(0, 8).map((finding) => <span key={finding}>{finding}</span>)}
          </div>
        ) : null}
      </section>
      {sourceRegistry ? (
        <TablePanel
          title="Registrierte eigene Wallets und Plattformen"
          rows={sourceRegistry.entries
            .filter((entry) => ["owned", "owned_historical_route"].includes(String(entry.ownership ?? "")))
            .map((entry) => ({
              quelle: entry.label,
              rolle: entry.role,
              eigentum: entry.ownership,
              portfolio: entry.portfolio_policy,
              fifo: entry.fifo_policy,
              gueltig_ab: formatDateTime(entry.valid_from),
              gueltig_bis: entry.valid_to ? formatDateTime(entry.valid_to) : "offen",
              abdeckung: entry.coverage_status,
              abdeckungsart: entry.coverage_gate_status,
              limitation: entry.coverage_limitation === "none" ? "-" : entry.coverage_limitation,
              nutzerbeleg_noetig: entry.additional_user_evidence_required ? "ja" : "nein",
              events: entry.observed_events_count,
              event_zeitraum: `${formatDate(entry.observed_first_event_at)} bis ${formatDate(entry.observed_last_event_at)}`,
              ledger_rohwert: `${formatCurrency(entry.current_ledger_value_eur)} EUR`,
              belegkorrektur: `${formatCurrency(entry.current_ledger_adjustment_value_eur)} EUR`,
              ledger_abgeglichen: `${formatCurrency(entry.current_reconciled_ledger_value_eur)} EUR`,
              wertbasis: entry.live_balance_basis === "current_live_snapshot" ? "Live-API" : entry.live_balance_basis === "ledger_fallback" ? "Ledger-Fallback" : "nicht anwendbar",
              live_stand: entry.latest_live_snapshot_at ? formatDateTime(entry.latest_live_snapshot_at) : "kein Live-Anker",
              live_wert: entry.live_balance_basis === "current_live_snapshot" ? `${formatCurrency(entry.current_live_anchored_value_eur)} EUR` : "nicht aktuell",
              delta: entry.live_balance_basis === "current_live_snapshot" ? `${formatCurrency(entry.current_value_delta_eur)} EUR` : "nicht belastbar",
              mengengate: entry.quantity_gate_status,
              strict: entry.strict_ready ? "ja" : "nein"
            }))}
          footer={`Registry ${sourceRegistry.registry_version} · SHA-256 ${sourceRegistry.semantic_sha256}`}
          compact
        />
      ) : null}
      {sourceRegistry?.entries.some((entry) => entry.coverage_gate_status === "documented_route") ? (
        <TablePanel
          title="Belegte historische Service- und Transferpfade"
          rows={sourceRegistry.entries
            .filter((entry) => entry.coverage_gate_status === "documented_route")
            .map((entry) => ({
              quelle: entry.label,
              rolle: entry.role,
              eigentum: "Service / Infrastruktur",
              portfolio: "ausgeschlossen",
              fifo: entry.fifo_policy,
              gueltig_ab: formatDateTime(entry.valid_from),
              gueltig_bis: entry.valid_to ? formatDateTime(entry.valid_to) : "offen",
              nachweis: entry.coverage_gate_status,
              hinweis: entry.coverage_limitation_note ?? "Historischer Belegpfad"
            }))}
          footer="Diese Adressen belegen einen Transferpfad, sind aber keine aktuellen eigenen Portfolio-Wallets."
          compact
        />
      ) : null}
      <SourceCommandCenter
        sources={sources}
        connectorRows={connectorRows}
        activeId={activeId}
        onSelectSource={onSelectedSourceIdChange}
        onNavigate={onNavigate}
        onRefreshConfiguredSources={onRefreshConfiguredSources}
        sourceRefreshLoading={sourceRefreshLoading}
      />
      <SourceSetupBlockers
        connectorDiagnostics={connectorDiagnostics}
        onNavigate={onNavigate}
        onRefreshConfiguredSources={onRefreshConfiguredSources}
        sourceRefreshLoading={sourceRefreshLoading}
      />
      <SourceSetupWizard
        sources={sources}
        connectorRows={connectorRows}
        onNavigate={onNavigate}
        onRefreshConfiguredSources={onRefreshConfiguredSources}
        sourceRefreshLoading={sourceRefreshLoading}
      />
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
            <span className={`statusPill ${connectorDiagnostics.missing_credentials > 0 || connectorDiagnostics.failed_latest_attempts > 0 ? "blocked" : connectorDiagnostics.stale_snapshots > 0 || connectorDiagnostics.missing_snapshots > 0 ? "warning" : "ok"}`}>
              {connectorDiagnostics.missing_credentials} Credentials fehlen · {connectorDiagnostics.failed_latest_attempts} Abrufe fehlgeschlagen
            </span>
          </div>
          <div className="portfolioSummaryStrip">
            <Metric title="Gepruefte Connectoren" value={String(connectorRows.length)} />
            <Metric title="Credentials fehlen" value={String(connectorDiagnostics.missing_credentials)} />
            <Metric title="Snapshots fehlen" value={String(connectorDiagnostics.missing_snapshots)} />
            <Metric title="Snapshots veraltet" value={String(connectorDiagnostics.stale_snapshots)} />
            <Metric title="API-Abrufe fehlgeschlagen" value={String(connectorDiagnostics.failed_latest_attempts)} />
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
              letzter_api_versuch: row.last_attempt?.attempted_at ? formatDateTime(row.last_attempt.attempted_at) : "-",
              api_ergebnis: row.last_attempt?.status ?? "-",
              api_meldung: row.last_attempt?.message ?? "-",
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

function MobileConnectorCatalog({
  catalog
}: {
  catalog: Snapshot["connectorCatalog"];
}) {
  const connectors = catalog?.connectors ?? [];
  const connections = catalog?.connections ?? [];
  const security = catalog?.security;
  const connected = connectors.filter((item) =>
    ["configured", "registered"].includes(item.connection_status)
  ).length;
  const pending = connectors.filter(
    (item) => item.connection_status === "ownership_verified_pending_registry"
  ).length;
  const mobileReady = connectors.filter((item) =>
    item.mobile_platforms.some((platform) => platform === "android" || platform === "ios")
  ).length;
  const securityTone = !security
    ? "loading"
    : security.vault.status === "error" || security.vault.status === "migration_required"
      ? "blocked"
      : security.auth_mode === "setup_token" && security.vault.status === "encrypted"
        ? "ok"
        : "warning";
  const securityLabel = !security
    ? "wird geladen"
    : securityTone === "ok"
      ? "lokal abgesichert"
      : security.vault.status === "migration_required"
        ? "Vault-Migration offen"
        : security.vault.status === "error"
          ? "Vault nicht lesbar"
          : "Server-Setup offen";
  const authLabels: Record<string, string> = {
    wallet_signature: "Wallet-Signatur",
    api_key: "Read-only API-Key",
    oauth_partner: "Partner-OAuth",
    oauth_redirect: "OAuth-Weiterleitung",
    file_import: "Dateiimport",
    server_api_key: "Server API-Key",
    device_capture: "Geraete-Scan",
    bank_reconciliation: "Bankabgleich"
  };
  const availabilityLabels: Record<string, string> = {
    available: "verfuegbar",
    server_admin_only: "Server-Setup",
    planned: "geplant",
    partner_access_required: "Partnerzugang nötig",
    evidence_only: "nur Nachweis"
  };
  const connectionLabels: Record<string, string> = {
    configured: "konfiguriert",
    not_configured: "nicht eingerichtet",
    ownership_verified_pending_registry: "Eigentum geprüft, Registry offen",
    registered: "Registry aktiv",
    revoked: "widerrufen"
  };
  const connectionTone = (status: string) => {
    if (["configured", "registered"].includes(status)) return "ok";
    if (status === "ownership_verified_pending_registry") return "warning";
    if (status === "revoked") return "blocked";
    return "loading";
  };

  return (
    <section className={`mobileConnectorBand ${securityTone}`}>
      <div className="mobileConnectorHeader">
        <div>
          <span className="heroKicker">Connector-Zentrale</span>
          <h3>Web, Android und iPhone</h3>
          <p>Wallets, Boersen, Datenanbieter, Zahlungsbelege und Dokumente in einem Statusmodell.</p>
        </div>
        <div className="mobileConnectorSecurity">
          <ShieldCheck size={20} />
          <span className={`statusPill ${securityTone}`}>{securityLabel}</span>
        </div>
      </div>
      <div className="mobileConnectorMetrics">
        <Metric title="Connectoren" value={catalog ? String(connectors.length) : "Wird geladen"} />
        <Metric title="Eingerichtet" value={catalog ? String(connected) : "Wird geladen"} />
        <Metric title="Registry-Review" value={catalog ? String(pending) : "Wird geladen"} />
        <Metric title="Mobil vorgesehen" value={catalog ? String(mobileReady) : "Wird geladen"} />
        <Metric
          title="Secret-Vault"
          value={security ? security.vault.status : "Wird geladen"}
        />
        <Metric
          title="Betriebsmodus"
          value={security?.internet_ready ? "Internet" : "LAN / VPN"}
        />
      </div>
      {security?.blockers.length ? (
        <div className="mobileConnectorBlockers">
          {security.blockers.map((blocker) => (
            <span key={blocker}>{blocker.replaceAll("_", " ")}</span>
          ))}
        </div>
      ) : null}
      <div className="mobileConnectorGrid">
        {connectors.map((connector) => (
          <article key={connector.connector_id} className="mobileConnectorItem">
            <div className="mobileConnectorItemHeader">
              <div className="mobileConnectorIdentity">
                {connector.category === "wallet" ? (
                  <Smartphone size={18} />
                ) : connector.category === "exchange" ? (
                  <WalletCards size={18} />
                ) : (
                  <Database size={18} />
                )}
                <strong>{connector.label}</strong>
              </div>
              <span className={`statusPill ${connectionTone(connector.connection_status)}`}>
                {connectionLabels[connector.connection_status] ?? connector.connection_status}
              </span>
            </div>
            <div className="mobileConnectorFacts">
              <span>{authLabels[connector.auth_method] ?? connector.auth_method}</span>
              <span>{availabilityLabels[connector.availability] ?? connector.availability}</span>
              <span>{connector.mobile_platforms.join(" · ") || "Server"}</span>
              <span>
                {connector.last_sync_at ? `Stand ${formatDateTime(connector.last_sync_at)}` : "Noch kein Abruf"}
              </span>
            </div>
            <p>{connector.capabilities.join(" · ")}</p>
            {connector.limitation ? <small>{connector.limitation}</small> : null}
            {connector.safety_notes.length ? (
              <div className="mobileConnectorSafety">
                <LockKeyhole size={14} />
                <span>{connector.safety_notes.join(" ")}</span>
              </div>
            ) : null}
          </article>
        ))}
      </div>
      {connections.length ? (
        <div className="mobileConnectorConnections">
          <strong>Signierte Wallet-Verbindungen</strong>
          {connections.map((connection) => (
            <div key={connection.connection_id} className="mobileConnectorConnectionRow">
              <span>{connection.display_label}</span>
              <code title={connection.external_identifier}>
                {shortAccount(connection.external_identifier)}
              </code>
              <span className={`statusPill ${connectionTone(connection.status)}`}>
                {connection.tax_activation === "registry_active" ? "steuerlich aktiv" : "Review erforderlich"}
              </span>
              <details>
                <summary>Vollstaendige Adresse</summary>
                <code>{connection.external_identifier}</code>
              </details>
            </div>
          ))}
        </div>
      ) : null}
      {catalog?.methodology ? (
        <details className="cockpitDetails">
          <summary>Aktivierungsregel</summary>
          <p>{catalog.methodology}</p>
        </details>
      ) : null}
    </section>
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
        <Metric title="API-Live gesamt" value={report?.live_value_eur === null || report?.live_value_eur === undefined ? "-" : `${formatCurrency(report.live_value_eur)} EUR`} />
        <Metric title="Earn noch nicht gutgeschrieben" value={`${formatCurrency(report?.live_nonledger_accrual_value_eur)} EUR`} />
        <Metric title="FIFO-Abgleich Live" value={report?.reconciliation_live_value_eur === null || report?.reconciliation_live_value_eur === undefined ? "-" : `${formatCurrency(report.reconciliation_live_value_eur)} EUR`} />
        <Metric title="FIFO-Abgleich Delta" value={report?.delta_value_eur === null || report?.delta_value_eur === undefined ? "-" : `${formatCurrency(report.delta_value_eur)} EUR`} />
        <Metric title="Live-Stand" value={report?.last_live_at ? formatDateTime(report.last_live_at) : "-"} />
      </div>
      <div className="statusRows">
        <StatusRow label="Delta-Formel" value="gutgeschriebener API-Livewert minus steuerlicher V2-Ledgerwert" />
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
          live_quantity_gesamt: row.live_quantity,
          earn_noch_nicht_gutgeschrieben: row.live_nonledger_accrual_quantity,
          fifo_abgleich_live_quantity: row.reconciliation_live_quantity,
          fifo_abgleich_delta_quantity: row.delta_quantity,
          ledger_value_eur: row.ledger_value_eur,
          live_value_eur_gesamt: row.live_value_eur,
          earn_noch_nicht_gutgeschrieben_eur: row.live_nonledger_accrual_value_eur,
          fifo_abgleich_live_value_eur: row.reconciliation_live_value_eur,
          fifo_abgleich_delta_value_eur: row.delta_value_eur,
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
      <div className="portfolioSummaryStrip">
        <Metric title="Binance Ledger" value={`${formatCurrency(report.ledger_value_eur)} EUR`} />
        <Metric title="Binance Live gesamt" value={report.live_value_eur === null || report.live_value_eur === undefined ? "-" : `${formatCurrency(report.live_value_eur)} EUR`} />
        <Metric title="Earn noch nicht gutgeschrieben" value={`${formatCurrency(report.live_nonledger_accrual_value_eur)} EUR`} />
        <Metric title="FIFO-Abgleich Live" value={report.reconciliation_live_value_eur === null || report.reconciliation_live_value_eur === undefined ? "-" : `${formatCurrency(report.reconciliation_live_value_eur)} EUR`} />
        <Metric title="FIFO-Abgleich Delta" value={report.delta_value_eur === null || report.delta_value_eur === undefined ? "-" : `${formatCurrency(report.delta_value_eur)} EUR`} />
      </div>
      <TablePanel
        title="Binance Evidence 2025+"
        rows={assetReports.map((assetReport) => ({
          asset: assetReport.asset,
          suspected_gap: assetReport.suspected_gap,
          ledger_quantity: assetReport.ledger_quantity,
          live_quantity_gesamt: assetReport.live_quantity,
          earn_noch_nicht_gutgeschrieben: assetReport.live_nonledger_accrual_quantity,
          fifo_abgleich_live_quantity: assetReport.reconciliation_live_quantity,
          fifo_abgleich_delta_quantity: assetReport.delta_quantity,
          ledger_value_eur: assetReport.ledger_value_eur,
          live_value_eur_gesamt: assetReport.live_value_eur,
          earn_noch_nicht_gutgeschrieben_eur: assetReport.live_nonledger_accrual_value_eur,
          fifo_abgleich_live_value_eur: assetReport.reconciliation_live_value_eur,
          fifo_abgleich_delta_value_eur: assetReport.delta_value_eur,
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
    connector_error: "API-Abruf fehlgeschlagen",
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
  readiness,
  database,
  taxYearsSummary,
  taxPaymentOverview,
  taxYearFilingMatrix,
  taxFilingClosureOverview,
  selectedTaxYear,
  onSelectedTaxYearChange,
  onDownload,
  onNavigate,
  onRebuildPipeline,
  onRefreshConfiguredSources,
  sourceRefreshLoading
}: {
  summary: Snapshot["cockpit"];
  readiness: Snapshot["productReadiness"];
  database: Record<string, unknown> | undefined;
  taxYearsSummary: Snapshot["taxYearsSummary"];
  taxPaymentOverview: Snapshot["taxPaymentOverview"];
  taxYearFilingMatrix: Snapshot["taxYearFilingMatrix"];
  taxFilingClosureOverview: Snapshot["taxFilingClosureOverview"];
  selectedTaxYear: string;
  onSelectedTaxYearChange: (year: string) => void;
  onDownload: (path: string) => void;
  onNavigate: (section: Section) => void;
  onRebuildPipeline: () => void;
  onRefreshConfiguredSources: () => void;
  sourceRefreshLoading: boolean;
}) {
  const cockpitReady = summary !== undefined;
  const readinessReady = readiness !== undefined;
  const taxDataReady = Boolean(taxYearsSummary && taxPaymentOverview && taxYearFilingMatrix && taxFilingClosureOverview);
  const tasks = summary?.tasks ?? [];
  const assets = summary?.top_assets ?? [];
  const sources = summary?.top_sources ?? [];
  const priceCoverage = summary?.price_coverage;
  const live = summary?.live_reconciliation;
  const evidenceHealth = summary?.evidence_health;
  const taxProductRows = taxDataReady
    ? buildTaxProductYearRows({
        years: taxYearsSummary?.years ?? [],
        paymentRows: taxPaymentOverview?.rows ?? [],
        filingMatrixRows: taxYearFilingMatrix?.rows ?? [],
        filingClosureRows: taxFilingClosureOverview?.rows ?? [],
        submissionRows: [],
        finalizationRows: []
      })
    : [];
  const dashboardTaxYear = taxProductRows.some((row) => row.year === selectedTaxYear)
    ? selectedTaxYear
    : taxProductRows.at(-1)?.year ?? selectedTaxYear;
  const dashboardTaxRow = taxProductRows.find((row) => row.year === dashboardTaxYear);
  const primaryTask = tasks[0];
  const hasLiveBlockers = (live?.blocker_count ?? 0) > 0 || live?.status === "blocked";
  const hasWarnings = cockpitReady && (hasLiveBlockers || (live?.warning_count ?? 0) > 0 || tasks.length > 0);
  const statusClass = !cockpitReady ? "loading" : !summary.export_allowed ? "blocked" : hasWarnings ? "warning" : "ok";
  const filingHeadline = !cockpitReady
    ? "Cockpit-Daten werden geladen"
    : !summary.export_allowed
      ? "Export ist blockiert"
      : hasWarnings
        ? "Steuerexport frei, aber Pruefung offen"
        : "Steuerstatus sauber";
  const filingDetail = !cockpitReady
    ? "Portfolio, Review-Gate und Quellenstatus werden getrennt geladen. Bereits fertige Bereiche erscheinen sofort."
    : !summary.export_allowed
      ? "Mindestens ein Review- oder Belegproblem verhindert aktuell einen sauberen Export."
      : hasWarnings
        ? "Die Steuerfreigabe ist offen, aber Live-Abgleich oder Quellenstatus sollten vor Abgabe nachvollziehbar dokumentiert werden."
        : "Keine priorisierten Aufgaben offen. Die Ansicht kann als Einstieg fuer Belege und Steuerjahre genutzt werden.";
  const nextStepLabel = !cockpitReady
    ? "Status wird ermittelt"
    : primaryTask?.title ?? (summary.export_allowed ? "Steuerjahre pruefen" : "Review oeffnen");
  const nextStepDetail = !cockpitReady
    ? "Die priorisierte Aktion erscheint nach dem Cockpit-Paket."
    : primaryTask?.detail ?? (summary.export_allowed ? "Eingabehilfe und Jahrespakete kontrollieren." : "Blockierende Punkte bearbeiten.");
  const nextStepTarget = primaryTask?.target ?? (summary?.export_allowed ? "tax" : "review");
  const coveragePct = formatPercent(priceCoverage?.coverage_pct ?? 0);
  const liveStatusText = live?.status === "ok" ? "belegt" : live?.status === "warning" ? "Warnung" : "offen";
  const evidenceStatusText = evidenceHealth?.status === "complete" ? "vollstaendig" : evidenceHealth?.status ?? "-";
  const performance = summary?.portfolio_performance;
  const livePortfolioValue = performance?.live_value_eur ?? summary?.portfolio_value_eur;
  const hasCalculatedValue = performance?.calculated_value_eur !== undefined && performance?.calculated_value_eur !== null;
  const hasLiveValue = livePortfolioValue !== undefined && livePortfolioValue !== null;
  const liveLedgerDelta = hasCalculatedValue && hasLiveValue
    ? parseNumber(livePortfolioValue) - parseNumber(performance?.calculated_value_eur)
    : null;

  return (
    <Stack>
      <section className={`cockpitHero ${statusClass}`}>
        <div className="cockpitHeroMain">
          <span className="heroKicker">Portfolio, Steuern und Nachweise</span>
          <h2>{hasLiveValue ? `${formatCurrency(livePortfolioValue)} EUR` : "Portfolio wird geladen"}</h2>
          <p className="cockpitHeroLead"><strong>{filingHeadline}.</strong> {filingDetail}</p>
          <div className="cockpitHeroMeta">
            <span className={`statusPill ${statusClass}`}>
              {cockpitReady ? `Export ${summary.export_status}` : "Status wird geladen"}
            </span>
            <span>Live-Stand {live?.latest_live_snapshot_at ? formatDateTime(live.latest_live_snapshot_at) : summary?.generated_at ? formatDateTime(summary.generated_at) : "-"}</span>
            <span>Preisdeckung {coveragePct}</span>
            <span>DB {String(database?.database_type ?? "-")}</span>
          </div>
        </div>
        <div className="cockpitDecisionRail">
          <button className={`nextActionCard ${statusClass}`} type="button" disabled={!cockpitReady} onClick={() => onNavigate(nextStepTarget)}>
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

      <section className="cockpitHeadlineMetrics" aria-label="Wichtigste Kennzahlen">
        <Metric title="API-Livewert" value={hasLiveValue ? `${formatCurrency(livePortfolioValue)} EUR` : "-"} />
        <Metric title="Berechneter Ledgerwert" value={hasCalculatedValue ? `${formatCurrency(performance?.calculated_value_eur)} EUR` : "-"} />
        <Metric title="Live minus Ledger" value={liveLedgerDelta === null ? "-" : `${formatCurrency(liveLedgerDelta)} EUR`} />
        <Metric title={`Steuerpflichtiger G/V ${dashboardTaxYear}`} value={taxDataReady && dashboardTaxRow ? `${formatCurrency(dashboardTaxRow.taxablePrivateDisposalsEur)} EUR` : "wird geladen"} />
        <Metric title="Offene Aufgaben" value={cockpitReady ? String(summary.open_tasks) : "wird geladen"} />
      </section>

      <CockpitFilingJourney
        summary={summary}
        readiness={readiness}
        onNavigate={onNavigate}
        onRefreshConfiguredSources={onRefreshConfiguredSources}
        sourceRefreshLoading={sourceRefreshLoading}
        onRebuildPipeline={onRebuildPipeline}
        loading={!cockpitReady || !readinessReady}
      />

      <BlockpitWorkspaceOverview
        summary={summary}
        readiness={readiness}
        activeTaxYear={dashboardTaxYear}
        activeTaxRow={dashboardTaxRow}
        sources={sources}
        onNavigate={onNavigate}
        onRefreshConfiguredSources={onRefreshConfiguredSources}
        sourceRefreshLoading={sourceRefreshLoading}
        taxDataReady={taxDataReady}
      />

      <CockpitPortfolioCommand
        summary={summary}
        onNavigate={onNavigate}
        onRefreshConfiguredSources={onRefreshConfiguredSources}
        sourceRefreshLoading={sourceRefreshLoading}
      />

      <TaxProductCommandCenter
        rows={taxProductRows}
        activeYear={dashboardTaxYear}
        activeRow={dashboardTaxRow}
        onSelectYear={onSelectedTaxYearChange}
        onDownload={onDownload}
        loading={!taxDataReady}
      />

      <details className="cockpitDetails">
        <summary>
          <span>
            <strong>Pruefstatus und technische Details</strong>
            <em>Preisdeckung, Live-Abgleich, Prioritaeten und Pipeline</em>
          </span>
          <span className={`statusPill ${statusClass}`}>{tasks.length} Aufgabe(n)</span>
        </summary>
        <div className="cockpitDetailsBody">
          <CockpitPriorityStrip
            summary={summary}
            activeTaxYear={dashboardTaxYear}
            activeTaxRow={dashboardTaxRow}
            onNavigate={onNavigate}
          />

          <ProductReadinessPanel report={readiness} onNavigate={onNavigate} />

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
        </div>
      </details>
    </Stack>
  );
}

function CockpitPriorityStrip({
  summary,
  activeTaxYear,
  activeTaxRow,
  onNavigate
}: {
  summary: Snapshot["cockpit"];
  activeTaxYear: string;
  activeTaxRow: TaxProductYearRow | undefined;
  onNavigate: (section: Section) => void;
}) {
  const primaryTask = summary?.tasks?.[0];
  const assets = summary?.top_assets ?? [];
  const topPerformanceAsset = assets
    .filter((asset) => asset.unrealized_return_eur !== undefined && asset.unrealized_return_eur !== null)
    .sort((left, right) => Math.abs(parseNumber(right.unrealized_return_eur)) - Math.abs(parseNumber(left.unrealized_return_eur)))[0];
  const live = summary?.live_reconciliation;
  const taskTone = primaryTask?.priority === "high" ? "blocked" : primaryTask ? "warning" : "ok";
  const liveTone = live?.status === "ok" ? "ok" : live?.status === "warning" ? "warning" : "blocked";
  const performanceTone = assetPerformanceTone(topPerformanceAsset ?? {});
  const items = [
    {
      key: "task",
      tone: taskTone,
      icon: taskTone === "ok" ? <Check size={18} /> : <AlertTriangle size={18} />,
      title: primaryTask?.title ?? "Keine priorisierte Aufgabe",
      value: primaryTask?.count !== null && primaryTask?.count !== undefined ? String(primaryTask.count) : summary?.export_allowed ? "frei" : "offen",
      detail: primaryTask?.detail ?? "Review-Gate ist frei; naechster Schritt ist Jahrespaket oder Export pruefen.",
      target: primaryTask?.target ?? "export"
    },
    {
      key: "tax",
      tone: activeTaxRow?.tone ?? "warning",
      icon: <ReceiptText size={18} />,
      title: `Steuerjahr ${activeTaxYear}`,
      value: `${formatCurrency(activeTaxRow?.taxablePrivateDisposalsEur)} EUR`,
      detail: activeTaxRow?.nextAction ?? "Eingabehilfe und Belegpaket werden vorbereitet.",
      target: "tax"
    },
    {
      key: "performance",
      tone: performanceTone,
      icon: <WalletCards size={18} />,
      title: topPerformanceAsset ? `${String(topPerformanceAsset.asset)} Performance` : "Portfolio Performance",
      value: `${formatCurrency(topPerformanceAsset?.unrealized_return_eur)} EUR`,
      detail: topPerformanceAsset
        ? `Kostenbasis ${formatCurrency(topPerformanceAsset.open_cost_basis_eur)} EUR · ${topPerformanceAsset.unrealized_return_pct !== null && topPerformanceAsset.unrealized_return_pct !== undefined ? formatPercent(topPerformanceAsset.unrealized_return_pct) : "ohne Prozentwert"}`
        : "Top-Asset-Performance wird geladen.",
      target: "portfolio"
    },
    {
      key: "live",
      tone: liveTone,
      icon: <RefreshCcw size={18} />,
      title: "Live-Abgleich",
      value: live?.status === "ok" ? "synchron" : live?.status === "warning" ? "pruefen" : "offen",
      detail: `${live?.blocker_count ?? 0} Blocker · ${live?.warning_count ?? 0} Warnungen · ${live?.latest_live_snapshot_at ? formatDateTime(live.latest_live_snapshot_at) : "kein Snapshot"}`,
      target: "portfolio"
    }
  ] satisfies Array<{
    key: string;
    tone: "ok" | "warning" | "blocked";
    icon: React.ReactNode;
    title: string;
    value: string;
    detail: string;
    target: Section;
  }>;
  return (
    <section className="cockpitPriorityStrip" aria-label="Wichtige Hinweise">
      <div className="priorityStripHeader">
        <span className="heroKicker">Im Blick behalten</span>
        <strong>Prioritaeten</strong>
      </div>
      <div className="priorityItemGrid">
        {items.map((item) => (
          <button key={item.key} className={`priorityItem ${item.tone}`} type="button" onClick={() => onNavigate(item.target)}>
            <span>{item.icon}</span>
            <div>
              <strong>{item.title}</strong>
              <em>{item.detail}</em>
            </div>
            <b>{item.value}</b>
          </button>
        ))}
      </div>
    </section>
  );
}

function BlockpitWorkspaceOverview({
  summary,
  readiness,
  activeTaxYear,
  activeTaxRow,
  sources,
  onNavigate,
  onRefreshConfiguredSources,
  sourceRefreshLoading,
  taxDataReady
}: {
  summary: Snapshot["cockpit"];
  readiness: Snapshot["productReadiness"];
  activeTaxYear: string;
  activeTaxRow: TaxProductYearRow | undefined;
  sources: Array<Record<string, unknown>>;
  onNavigate: (section: Section) => void;
  onRefreshConfiguredSources: () => void;
  sourceRefreshLoading: boolean;
  taxDataReady: boolean;
}) {
  const cockpitReady = summary !== undefined;
  const readinessReady = readiness !== undefined;
  const live = summary?.live_reconciliation;
  const priceCoverage = summary?.price_coverage;
  const reviewTone = !cockpitReady ? "loading" : summary.export_allowed ? "ok" : "blocked";
  const liveTone = !cockpitReady ? "loading" : live?.status === "ok" ? "ok" : live?.status === "warning" ? "warning" : "blocked";
  const readinessToneValue = !readinessReady ? "loading" : readinessTone(readiness.overall_status);
  const sourceCount = sources.length;
  const openTasks = summary?.open_tasks ?? 0;
  return (
    <section className="blockpitWorkspaceGrid" aria-label="Arbeitsbereiche">
      <button className={`workspaceCard ${liveTone}`} type="button" onClick={() => onNavigate("portfolio")}>
        <div className="workspaceCardHeader">
          <WalletCards size={20} />
          <span className={`statusPill ${liveTone}`}>{!cockpitReady ? "laedt" : live?.status === "ok" ? "synchron" : "abgleichen"}</span>
        </div>
        <strong>Portfolio</strong>
        <em>{cockpitReady ? `${formatCurrency(summary.portfolio_value_eur)} EUR` : "wird geladen"}</em>
        <p>{priceCoverage ? `${formatPercent(priceCoverage.coverage_pct)} Preisdeckung` : "Bewertung wird geladen"} · {live?.stored_live_connectors ?? 0} Live-Connectoren</p>
      </button>

      <button className={`workspaceCard ${taxDataReady ? activeTaxRow?.tone ?? "warning" : "loading"}`} type="button" onClick={() => onNavigate("tax")}>
        <div className="workspaceCardHeader">
          <ReceiptText size={20} />
          <span className={`statusPill ${taxDataReady ? activeTaxRow?.tone ?? "warning" : "loading"}`}>{taxDataReady ? activeTaxRow?.statusLabel ?? "pruefen" : "laedt"}</span>
        </div>
        <strong>Steuern {activeTaxYear}</strong>
        <em>{taxDataReady && activeTaxRow ? `${formatCurrency(activeTaxRow.taxablePrivateDisposalsEur)} EUR` : "wird geladen"}</em>
        <p>{activeTaxRow?.nextAction ?? "Eingabehilfe und Jahrespaket werden geladen."}</p>
      </button>

      <button className={`workspaceCard ${liveTone}`} type="button" onClick={() => onNavigate("sources")}>
        <div className="workspaceCardHeader">
          <Database size={20} />
          <span className={`statusPill ${liveTone}`}>{cockpitReady ? `${sourceCount} Quellen` : "laedt"}</span>
        </div>
        <strong>Quellen</strong>
        <em>{!cockpitReady ? "wird geladen" : live?.latest_live_snapshot_at ? formatDateTime(live.latest_live_snapshot_at) : "kein Snapshot"}</em>
        <p>{cockpitReady ? `${live?.blocker_count ?? 0} Blocker · ${live?.warning_count ?? 0} Warnungen` : "Live-Status wird geladen"} · {sourceRefreshLoading ? "Sync laeuft" : "API-Sync bereit"}</p>
      </button>

      <button className={`workspaceCard ${reviewTone}`} type="button" onClick={() => onNavigate(openTasks > 0 ? "review" : "export")}>
        <div className="workspaceCardHeader">
          <ClipboardCheck size={20} />
          <span className={`statusPill ${readinessToneValue}`}>{readiness ? readinessLabel(readiness.overall_status) : "laedt"}</span>
        </div>
        <strong>Review & Export</strong>
        <em>{cockpitReady ? summary.export_allowed ? "freigegeben" : "blockiert" : "wird geladen"}</em>
        <p>{summary?.review?.detail ?? "Review-Gate wird geladen"}{cockpitReady ? ` · ${openTasks} Aufgabe(n)` : ""}</p>
      </button>

      <div className="workspaceSyncBar">
        <span>Direktaktionen</span>
        <button type="button" onClick={onRefreshConfiguredSources} disabled={sourceRefreshLoading}>
          <RefreshCcw size={16} />
          {sourceRefreshLoading ? "Quellen werden abgefragt" : "Alle Quellen per API abfragen"}
        </button>
        <button type="button" onClick={() => onNavigate("export")}>
          <PackageCheck size={16} />
          Belegpakete
        </button>
      </div>
    </section>
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

function CockpitPortfolioCommand({
  summary,
  onNavigate,
  onRefreshConfiguredSources,
  sourceRefreshLoading
}: {
  summary: Snapshot["cockpit"];
  onNavigate: (section: Section) => void;
  onRefreshConfiguredSources: () => void;
  sourceRefreshLoading: boolean;
}) {
  if (!summary) {
    return (
      <section className="blockpitPortfolioCommand loading" aria-busy="true" aria-live="polite">
        <div className="portfolioCommandMain">
          <div className="portfolioCommandHeader">
            <div>
              <span className="heroKicker">Bestand und Entwicklung</span>
              <h3>Portfolio wird geladen</h3>
              <p>Live-Bestand, Ledgerwert und FIFO-Kostenbasis werden getrennt uebernommen.</p>
            </div>
            <span className="statusPill loading">laedt</span>
          </div>
          <div className="portfolioCommandMetrics">
            <Metric title="API-Livewert" value="wird geladen" />
            <Metric title="Berechneter Wert" value="wird geladen" />
            <Metric title="FIFO-Kostenbasis" value="wird geladen" />
            <Metric title="Unrealisierter G/V" value="wird geladen" />
            <Metric title="Netto in EUR investiert" value="wird geladen" />
          </div>
        </div>
        <div className="portfolioCommandSide loadingPlaceholder" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      </section>
    );
  }
  const performance = summary?.portfolio_performance;
  const live = summary?.live_reconciliation;
  const assets = summary?.top_assets ?? [];
  const sources = summary?.top_sources ?? [];
  const unrealizedReturn = parseNumber(performance?.unrealized_return_eur);
  const unrealizedTone = unrealizedReturn < 0 ? "blocked" : unrealizedReturn > 0 ? "ok" : "warning";
  const valueBasisLabel = performance?.display_value_basis === "live_api" ? "API-Livewert" : "berechneter Ledgerwert";
  const liveTone = live?.status === "ok" ? "ok" : live?.status === "warning" ? "warning" : "blocked";
  const costBasisLabel = performance?.cost_basis_status === "available" ? "Offene FIFO-Kostenbasis" : "Kostenbasis pruefen";
  return (
    <section className="blockpitPortfolioCommand">
      <div className="portfolioCommandMain">
        <div className="portfolioCommandHeader">
          <div>
            <span className="heroKicker">Bestand und Entwicklung</span>
            <h3>{formatCurrency(performance?.display_value_eur ?? summary?.portfolio_value_eur)} EUR</h3>
            <p>
              {valueBasisLabel} · Stand {summary?.generated_at ? formatDateTime(summary.generated_at) : "-"}
            </p>
          </div>
          <span className={`statusPill ${liveTone}`}>
            {live?.status === "ok" ? "synchron" : live?.status === "warning" ? "Abgleich pruefen" : "Sync offen"}
          </span>
        </div>
        <div className="portfolioCommandMetrics">
          <Metric title="API-Livewert" value={performance?.live_value_eur !== undefined && performance?.live_value_eur !== null ? `${formatCurrency(performance.live_value_eur)} EUR` : "-"} />
          <Metric title="Berechneter Wert" value={`${formatCurrency(performance?.calculated_value_eur)} EUR`} />
          <Metric title={costBasisLabel} value={`${formatCurrency(performance?.open_cost_basis_eur)} EUR`} />
          <Metric
            title="Unrealisierter G/V"
            value={`${formatCurrency(performance?.unrealized_return_eur)} EUR${performance?.unrealized_return_pct ? ` · ${formatPercent(performance.unrealized_return_pct)}` : ""}`}
          />
          <Metric title="Netto in EUR investiert" value={`${formatCurrency(performance?.net_fiat_invested_eur)} EUR`} />
        </div>
        <div className={`portfolioReturnBand ${unrealizedTone}`}>
          <div>
            <strong>{unrealizedReturn < 0 ? "Buchverlust sichtbar" : unrealizedReturn > 0 ? "Buchgewinn sichtbar" : "Performance neutral"}</strong>
            <span>{performance?.detail ?? "Performance-Kennzahlen werden aus Cockpit-Daten geladen."}</span>
          </div>
          <div className="portfolioCommandActions">
            <button type="button" onClick={onRefreshConfiguredSources} disabled={sourceRefreshLoading}>
              <RefreshCcw size={16} />
              <span>{sourceRefreshLoading ? "Abgleich laeuft" : "Alle Quellen"}</span>
            </button>
            <button type="button" onClick={() => onNavigate("portfolio")}>
              <WalletCards size={16} />
              <span>Bestaende</span>
            </button>
            <button type="button" onClick={() => onNavigate("tax")}>
              <ReceiptText size={16} />
              <span>Steuerplanung</span>
            </button>
          </div>
        </div>
      </div>
      <div className="portfolioCommandSide">
        <div className="portfolioMiniPanel">
          <div className="panelToolbar">
            <strong>Bestaende</strong>
            <span>{assets.length}</span>
          </div>
          <div className="portfolioMiniList">
            {assets.slice(0, 5).map((asset) => (
              <button
                key={String(asset.asset)}
                type="button"
                className={assetPerformanceTone(asset)}
                onClick={() => onNavigate("portfolio")}
              >
                <strong>{String(asset.asset)}</strong>
                <span>{formatCurrency(asset.value_eur)} EUR</span>
                <em>
                  {formatPercent(asset.share_pct)} · KB {formatCurrency(asset.open_cost_basis_eur)} EUR · G/V{" "}
                  {formatCurrency(asset.unrealized_return_eur)} EUR
                  {asset.unrealized_return_pct !== null && asset.unrealized_return_pct !== undefined
                    ? ` · ${formatPercent(asset.unrealized_return_pct)}`
                    : ""}
                </em>
              </button>
            ))}
          </div>
        </div>
        <div className="portfolioMiniPanel">
          <div className="panelToolbar">
            <strong>Quellen</strong>
            <span>{sources.length}</span>
          </div>
          <div className="portfolioMiniList">
            {sources.slice(0, 4).map((source) => (
              <button key={String(source.source_group)} type="button" onClick={() => onNavigate("sources")}>
                <strong>{String(source.source_group)}</strong>
                <span>{formatCurrency(source.live_value_eur ?? source.value_eur)} EUR</span>
                <em>{source.last_live_at ? formatDateTime(source.last_live_at) : String(source.current_status ?? "-")}</em>
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function assetPerformanceTone(asset: Record<string, unknown>): "ok" | "warning" | "blocked" {
  const status = String(asset.performance_status ?? "");
  if (status === "gain" || status === "flat") {
    return "ok";
  }
  if (status === "loss") {
    return "blocked";
  }
  return "warning";
}

function CockpitFilingJourney({
  summary,
  readiness,
  onNavigate,
  onRefreshConfiguredSources,
  sourceRefreshLoading,
  onRebuildPipeline,
  loading
}: {
  summary: Snapshot["cockpit"];
  readiness: Snapshot["productReadiness"];
  onNavigate: (section: Section) => void;
  onRefreshConfiguredSources: () => void;
  sourceRefreshLoading: boolean;
  onRebuildPipeline: () => void;
  loading: boolean;
}) {
  const checks = readiness?.checks ?? [];
  const checkByKey = new Map(checks.map((check) => [String(check.key), check]));
  const sourcesCheck = checkByKey.get("sources_connected");
  const reviewCheck = checkByKey.get("review_gate");
  const taxYearsCheck = checkByKey.get("tax_years");
  const evidenceCheck = checkByKey.get("evidence_package");
  const liveCheck = checkByKey.get("portfolio_live");
  const live = summary?.live_reconciliation;
  const reviewStatus = reviewCheck?.status ?? (summary?.export_allowed ? "ok" : "blocked");
  const pipelineReady = (summary?.pipeline?.import_batches ?? 0) > 0 && Boolean(summary?.pipeline?.last_canonical_event_at);
  const steps = [
    {
      key: "sources",
      title: "1. Quellen verbinden",
      detail: sourcesCheck?.detail ?? "Wallets und Handelsplattformen pruefen.",
      status: loading ? "loading" as const : readinessTone(String(sourcesCheck?.status ?? "warning")),
      target: "sources" as Section,
      action: "Quellen oeffnen",
      secondary: sourceRefreshLoading ? "API-Abfrage laeuft" : "Alle APIs abfragen",
      secondaryAction: onRefreshConfiguredSources,
      disabled: sourceRefreshLoading
    },
    {
      key: "pipeline",
      title: "2. Daten berechnen",
      detail: pipelineReady
        ? `Letztes Canonical Event ${formatDateTime(summary?.pipeline?.last_canonical_event_at)}.`
        : "Importe normalisieren und FIFO-/Steuerdaten berechnen.",
      status: loading ? "loading" as const : pipelineReady ? "ok" as const : "warning" as const,
      target: "import" as Section,
      action: "Importstatus",
      secondary: "Neu berechnen",
      secondaryAction: onRebuildPipeline,
      disabled: false
    },
    {
      key: "review",
      title: "3. Review abschliessen",
      detail: reviewCheck?.detail ?? live?.detail ?? "Offene fachliche Entscheidungen und Live-Abgleich pruefen.",
      status: loading ? "loading" as const : readinessTone(String(reviewStatus)),
      target: "review" as Section,
      action: "Review"
    },
    {
      key: "tax",
      title: "4. Steuerjahr bestaetigen",
      detail: taxYearsCheck?.detail ?? "Jahreszahlen, BMF-Methodik und Eingabehilfe kontrollieren.",
      status: loading ? "loading" as const : readinessTone(String(taxYearsCheck?.status ?? "warning")),
      target: "tax" as Section,
      action: "Steuerjahre"
    },
    {
      key: "export",
      title: "5. Bericht & Belege",
      detail: evidenceCheck?.detail ?? "Finanzamtspaket, Evidence-Manifest und CSV/PDF bereitstellen.",
      status: loading ? "loading" as const : readinessTone(String(evidenceCheck?.status ?? "warning")),
      target: "export" as Section,
      action: "Export"
    }
  ];
  const overall = loading ? "loading" : readinessTone(readiness?.overall_status ?? "warning");
  const conservativeReadyCount = readiness?.conservative_ready_years?.length ?? 0;
  const canFileWithAppendix = readiness?.overall_status === "ready" && !readiness?.can_file_without_review && conservativeReadyCount > 0;
  return (
    <section className={`filingJourney ${overall}`}>
      <div className="filingJourneyHeader">
        <div>
          <span className="heroKicker">Ihr Arbeitsablauf</span>
          <h3>
            {loading
              ? "Abgabestatus wird geladen"
              : readiness?.can_file_without_review
              ? "Der Steuerreport ist abgabefertig"
              : canFileWithAppendix
                ? "Abgabe mit konservativen Anlagen vorbereitet"
                : "Noch nicht abgabefertig"}
          </h3>
          <p>
            {readiness?.headline ?? "Von synchronisierten Quellen ueber Berechnung und Review bis zur Eingabehilfe und zum Belegpaket."}
          </p>
        </div>
        <div className="filingJourneyFacts">
          <Metric title="Finale Abgabe" value={loading ? "wird geladen" : readiness?.can_file_without_review ? "ohne Review" : canFileWithAppendix ? "mit Anlage" : "offen"} />
          <Metric title="Vorbereitung" value={loading ? "wird geladen" : readiness?.can_prepare_tax_report ? "moeglich" : "offen"} />
          <div className="filingJourneyNextAction">
            <span>Naechste Aktion</span>
            <strong>{loading ? "wird ermittelt" : readiness?.next_action ?? "Status pruefen"}</strong>
          </div>
        </div>
      </div>
      <div className="filingJourneySteps">
        {steps.map((step) => (
          <div className={`filingStep ${step.status}`} key={step.key}>
            <span className={`statusPill ${step.status}`}>{step.status === "loading" ? "laedt" : step.status === "ok" ? "ok" : step.status === "blocked" ? "blockiert" : "pruefen"}</span>
            <strong>{step.title}</strong>
            <p>{String(step.detail)}</p>
            <div className="filingStepActions">
              <button type="button" onClick={() => onNavigate(step.target)}>
                <ExternalLink size={15} />
                <span>{step.action}</span>
              </button>
              {step.secondary ? (
                <button type="button" className="secondary" disabled={step.disabled || loading} onClick={step.secondaryAction}>
                  <RefreshCcw size={15} />
                  <span>{step.secondary}</span>
                </button>
              ) : null}
            </div>
          </div>
        ))}
      </div>
      {liveCheck && String(liveCheck.status) !== "ok" ? (
        <div className="notice inlineNotice reviewNotice">{String(liveCheck.detail ?? "Live-Daten sollten vor Abgabe aktualisiert werden.")}</div>
      ) : null}
    </section>
  );
}

function SourceCommandCenter({
  sources,
  connectorRows,
  activeId,
  onSelectSource,
  onNavigate,
  onRefreshConfiguredSources,
  sourceRefreshLoading
}: {
  sources: Array<Record<string, unknown>>;
  connectorRows: Array<Record<string, unknown>>;
  activeId: string;
  onSelectSource: (sourceId: string) => void;
  onNavigate: (section: Section) => void;
  onRefreshConfiguredSources: () => void;
  sourceRefreshLoading: boolean;
}) {
  const diagnosticsBySource = new Map(connectorRows.map((row) => [String(row.source_id), row]));
  const missingCredentials = connectorRows.filter((row) => String(row.credential_status) === "missing").length;
  const staleSnapshots = connectorRows.filter((row) => Number(row.last_snapshot_age_days ?? 0) > 3).length;
  const openReconciliation = sources.reduce((total, source) => total + Number(source.open_reconciliation_issues ?? 0), 0);
  const overallTone = missingCredentials > 0 ? "blocked" : staleSnapshots > 0 || openReconciliation > 0 ? "warning" : "ok";
  return (
    <section className={`sourceCommandCenter ${overallTone}`}>
      <div className="sourceCommandHeader">
        <div>
          <span className="heroKicker">Quellen verbinden</span>
          <h3>{missingCredentials > 0 ? "API-Zugriff einrichten" : staleSnapshots > 0 ? "Live-Bestaende aktualisieren" : "Quellenstatus pruefen"}</h3>
          <p>
            Vorhandene Wallets und Handelsplattformen bleiben getrennt sichtbar. Steuerdaten werden hier nicht veraendert;
            die Aktionen aktualisieren nur Credentials oder Live-Snapshots.
          </p>
        </div>
        <div className="sourceCommandActions">
          <button type="button" onClick={() => onNavigate("admin")}>
            <Settings size={16} />
            <span>Credentials</span>
          </button>
          <button type="button" onClick={onRefreshConfiguredSources} disabled={sourceRefreshLoading}>
            <RefreshCcw size={16} />
            <span>{sourceRefreshLoading ? "Abfrage laeuft" : "Live abfragen"}</span>
          </button>
        </div>
      </div>
      <div className="sourceCommandMetrics">
        <Metric title="Credentials fehlen" value={String(missingCredentials)} />
        <Metric title="Snapshots veraltet" value={String(staleSnapshots)} />
        <Metric title="Abgleich offen" value={String(openReconciliation)} />
        <Metric title="Quellen" value={String(sources.length)} />
      </div>
      <div className="sourceCommandGrid">
        {sources.map((source) => {
          const sourceId = String(source.source_id);
          const diagnostic = diagnosticsBySource.get(sourceId);
          const credentialStatus = String(diagnostic?.credential_status ?? "not_required");
          const liveStatus = String(source.live_freshness ?? diagnostic?.status ?? "missing");
          const tone = credentialStatus === "missing"
            ? "blocked"
            : Number(source.open_reconciliation_issues ?? 0) > 0 || liveStatus === "stale"
              ? "warning"
              : "ok";
          return (
            <button
              key={`source-command-${sourceId}`}
              className={`sourceCommandCard ${tone} ${sourceId === activeId ? "active" : ""}`}
              type="button"
              onClick={() => onSelectSource(sourceId)}
            >
              <span className={`statusPill ${tone}`}>
                {credentialStatus === "missing" ? "Credentials fehlen" : liveStatus === "stale" ? "Live veraltet" : "ok"}
              </span>
              <strong>{String(source.label ?? sourceId)}</strong>
              <em>{String(source.source_type ?? diagnostic?.connector_type ?? "-")} · {formatCurrency(source.value_eur)} EUR</em>
              <small>
                Credentials {sourceCredentialStatusLabel(credentialStatus)} · Live {sourceLiveFreshnessLabel(liveStatus, source.live_age_days)}
              </small>
              <small>{String(source.open_reconciliation_issues ?? 0)} Abgleich · {String(source.open_price_issues ?? 0)} Preis</small>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function SourceSetupBlockers({
  connectorDiagnostics,
  onNavigate,
  onRefreshConfiguredSources,
  sourceRefreshLoading
}: {
  connectorDiagnostics: Snapshot["sourceConnectorDiagnostics"];
  onNavigate: (section: Section) => void;
  onRefreshConfiguredSources: () => void;
  sourceRefreshLoading: boolean;
}) {
  const rows = connectorDiagnostics?.diagnostics ?? [];
  const missingCredentials = rows.filter((row) => String(row.credential_status) === "missing");
  const staleSnapshots = rows.filter((row) => Number(row.last_snapshot_age_days ?? 0) > 3 || String(row.status) === "stale_snapshot");
  const failedAttempts = rows.filter((row) => String(row.status) === "connector_error");
  const tone = missingCredentials.length > 0 || failedAttempts.length > 0 ? "blocked" : staleSnapshots.length > 0 ? "warning" : "ok";
  if (!connectorDiagnostics) {
    return (
      <section className="sourceSetupBlockers warning">
        <div>
          <span className="heroKicker">Quellen-Setup</span>
          <h3>Connector-Diagnose wird geladen</h3>
          <p>Die Uebersicht zeigt danach, welche API-Zugaenge und Live-Snapshots fuer Product-Readiness fehlen.</p>
        </div>
      </section>
    );
  }
  return (
    <section className={`sourceSetupBlockers ${tone}`}>
      <div className="sourceSetupBlockerHeader">
        <div>
          <span className="heroKicker">Product-Readiness: Quellen</span>
          <h3>
            {missingCredentials.length > 0
              ? `${missingCredentials.length} CEX-Credential-Set(s) fehlen`
              : failedAttempts.length > 0
                ? `${failedAttempts.length} API-Abruf(e) fehlgeschlagen`
              : staleSnapshots.length > 0
                ? `${staleSnapshots.length} Live-Snapshot(s) veraltet`
                : "Quellen-Setup ohne Blocker"}
          </h3>
          <p>
            Diese Karte zeigt nur Secret-Metadaten und Snapshot-Alter. Secret-Werte werden nicht angezeigt und es werden keine Steuerdaten veraendert.
          </p>
        </div>
        <div className="sourceSetupBlockerActions">
          <button type="button" onClick={() => onNavigate("admin")}>
            <Settings size={16} />
            <span>Credentials oeffnen</span>
          </button>
          <button type="button" onClick={onRefreshConfiguredSources} disabled={sourceRefreshLoading}>
            <RefreshCcw size={16} />
            <span>{sourceRefreshLoading ? "Abfrage laeuft" : "Live abfragen"}</span>
          </button>
        </div>
      </div>
      <div className="sourceSetupBlockerMetrics">
        <Metric title="Credentials fehlen" value={String(connectorDiagnostics.missing_credentials)} />
        <Metric title="Snapshots veraltet" value={String(connectorDiagnostics.stale_snapshots)} />
        <Metric title="Snapshots fehlen" value={String(connectorDiagnostics.missing_snapshots)} />
        <Metric title="API-Abrufe fehlgeschlagen" value={String(connectorDiagnostics.failed_latest_attempts)} />
        <Metric title="Geprueft" value={String(rows.length)} />
      </div>
      <div className="sourceSetupBlockerGrid">
        {rows.map((row) => {
          const credentialMissing = String(row.credential_status) === "missing";
          const stale = Number(row.last_snapshot_age_days ?? 0) > 3 || String(row.status) === "stale_snapshot";
          const connectorFailed = String(row.status) === "connector_error";
          const rowTone = credentialMissing || connectorFailed ? "blocked" : stale ? "warning" : "ok";
          return (
            <div key={`source-setup-blocker-${String(row.source_id ?? row.connector_id)}`} className={`sourceSetupBlockerCard ${rowTone}`}>
              <span className={`statusPill ${rowTone}`}>
                {credentialMissing ? "Credentials fehlen" : connectorFailed ? "API-Abruf fehlgeschlagen" : stale ? "Live veraltet" : "ok"}
              </span>
              <strong>{String(row.label ?? row.source_id ?? row.connector_id)}</strong>
              <p>{String(row.message ?? row.next_action ?? "-")}</p>
              <div className="sourceSetupBlockerFacts">
                <StatusRow label="Connector" value={String(row.connector_id ?? "-")} />
                <StatusRow label="Typ" value={String(row.connector_type ?? "-")} />
                <StatusRow label="Secrets" value={`${String(row.credential_keys_present ?? 0)}/${String(row.credential_keys_required ?? 0)}`} />
                <StatusRow label="Snapshot" value={row.last_snapshot_at ? formatDateTime(row.last_snapshot_at) : "-"} />
                <StatusRow label="Letzter API-Versuch" value={row.last_attempt?.attempted_at ? formatDateTime(row.last_attempt.attempted_at) : "-"} />
                <StatusRow label="API-Ergebnis" value={sourceConnectorStatusLabel(row.last_attempt?.status)} />
                <StatusRow label="Alter" value={row.last_snapshot_age_days === null || row.last_snapshot_age_days === undefined ? "-" : `${String(row.last_snapshot_age_days)} Tage`} />
                <StatusRow label="Wert" value={`${formatCurrency(row.last_snapshot_value_eur)} EUR`} />
              </div>
              <em>{String(row.next_action ?? "")}</em>
            </div>
          );
        })}
      </div>
      <div className="footer">{connectorDiagnostics.methodology}</div>
    </section>
  );
}

function SourceSetupWizard({
  sources,
  connectorRows,
  onNavigate,
  onRefreshConfiguredSources,
  sourceRefreshLoading
}: {
  sources: Array<Record<string, unknown>>;
  connectorRows: Array<Record<string, unknown>>;
  onNavigate: (section: Section) => void;
  onRefreshConfiguredSources: () => void;
  sourceRefreshLoading: boolean;
}) {
  const missingCredentials = connectorRows.filter((row) => String(row.credential_status) === "missing");
  const staleSources = sources.filter((source) => String(source.live_freshness ?? "") === "stale");
  const missingLiveSources = sources.filter((source) => !source.last_live_at);
  const openReconciliationSources = sources.filter((source) => Number(source.open_reconciliation_issues ?? 0) > 0 || source.display_warning);
  const evidenceOpenSources = sources.filter((source) => {
    const files = Array.isArray(source.last_evidence_files) ? source.last_evidence_files : [];
    return files.length === 0;
  });
  const steps = [
    {
      title: "1. API-Zugriff",
      status: missingCredentials.length > 0 ? "blocked" : "ok",
      value: missingCredentials.length > 0 ? `${missingCredentials.length} fehlt` : "vollstaendig",
      detail: missingCredentials.length > 0
        ? missingCredentials.map((row) => String(row.label ?? row.source_id)).join(", ")
        : "Alle erforderlichen Credential-Slots sind belegt.",
      action: "Credentials verwalten",
      onAction: () => onNavigate("admin")
    },
    {
      title: "2. Live-Bestaende",
      status: staleSources.length > 0 || missingLiveSources.length > 0 ? "warning" : "ok",
      value: `${staleSources.length} veraltet`,
      detail: staleSources.length > 0
        ? staleSources.map((source) => `${String(source.label)} (${String(source.live_age_days ?? "-")} Tage)`).join(", ")
        : missingLiveSources.length > 0
          ? missingLiveSources.map((source) => String(source.label)).join(", ")
          : "Live-Snapshots sind aktuell genug.",
      action: sourceRefreshLoading ? "API-Abfrage laeuft" : "Live abfragen",
      onAction: onRefreshConfiguredSources,
      disabled: sourceRefreshLoading
    },
    {
      title: "3. Ledger-Abgleich",
      status: openReconciliationSources.length > 0 ? "warning" : "ok",
      value: `${openReconciliationSources.length} offen`,
      detail: openReconciliationSources.length > 0
        ? openReconciliationSources.map((source) => String(source.label)).join(", ")
        : "Keine offenen Quellen-Abgleiche im Ueberblick.",
      action: "Abgleich ansehen",
      onAction: () => onNavigate("sources")
    },
    {
      title: "4. Belege",
      status: evidenceOpenSources.length > 0 ? "warning" : "ok",
      value: `${evidenceOpenSources.length} ohne Datei`,
      detail: evidenceOpenSources.length > 0
        ? evidenceOpenSources.map((source) => String(source.label)).join(", ")
        : "Import-/API-Belege sind je Quelle referenziert.",
      action: "Belege oeffnen",
      onAction: () => onNavigate("export")
    }
  ];
  return (
    <section className="sourceSetupWizard">
      <div className="sourceSetupHeader">
        <div>
          <span className="heroKicker">Setup-Wizard</span>
          <h3>Quellen steuerlich verwendbar machen</h3>
          <p>Diese Checkliste schreibt keine Steuerdaten. Sie zeigt nur, welche Voraussetzung fuer einen Blockpit-aehnlichen Quellenstatus noch fehlt.</p>
        </div>
      </div>
      <div className="sourceSetupSteps">
        {steps.map((step) => (
          <div key={step.title} className={`sourceSetupStep ${step.status}`}>
            <span className={`statusPill ${step.status}`}>{step.value}</span>
            <strong>{step.title}</strong>
            <p>{step.detail}</p>
            <button type="button" disabled={step.disabled} onClick={step.onAction}>
              <ExternalLink size={15} />
              <span>{step.action}</span>
            </button>
          </div>
        ))}
      </div>
    </section>
  );
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

function ProductReadinessPanel({
  report,
  onNavigate
}: {
  report: Snapshot["productReadiness"];
  onNavigate: (section: Section) => void;
}) {
  if (!report) {
    return (
      <section className="panel productReadinessPanel">
        <div className="panelToolbar">
          <strong>Abgabe-Readiness</strong>
          <span className="statusPill neutral">wird geladen</span>
        </div>
        <div className="empty">Produkt-Readiness wird geladen.</div>
      </section>
    );
  }
  const tone = readinessTone(report.overall_status);
  const checks = report.checks ?? [];
  const sources = report.sources ?? [];
  const nextSection = readinessSectionForPath(report.next_action_path);
  const years = readinessYearsLine(report);
  return (
    <section className={`panel productReadinessPanel ${tone}`}>
      <div className="panelToolbar">
        <div>
          <strong>Abgabe-Readiness</strong>
          <span>{report.generated_at ? `Stand ${formatDateTime(report.generated_at)}` : ""}</span>
        </div>
        <span className={`statusPill ${tone}`}>{readinessLabel(report.overall_status)}</span>
      </div>
      <div className="productReadinessHeader">
        <div>
          <h3>{report.headline}</h3>
          <p>{years}</p>
        </div>
        <button type="button" onClick={() => onNavigate(nextSection)}>
          {tone === "ok" ? <Check size={16} /> : <AlertTriangle size={16} />}
          <span>{report.next_action}</span>
        </button>
      </div>
      <div className="productReadinessGrid">
        <Metric title="Abgabe" value={report.can_file_without_review ? "ohne Review" : (report.conservative_ready_years ?? []).length > 0 ? "mit Anlage" : "offen"} />
        <Metric title="Vorbereitung moeglich" value={report.can_prepare_tax_report ? "ja" : "nein"} />
        <Metric title="Setup-Quellen" value={String(report.setup_required_sources ?? 0)} />
        <Metric title="Review/Blocker" value={`${report.review_items_count ?? 0}/${report.blocking_items_count ?? 0}`} />
      </div>
      <div className="readinessCheckGrid">
        {checks.map((check) => (
          <button
            key={String(check.key)}
            className={`readinessCheck ${readinessTone(String(check.status))}`}
            type="button"
            onClick={() => onNavigate(readinessSectionForPath(String(check.action_path ?? "")))}
            title={String(check.detail ?? "")}
          >
            <span className={`statusPill ${readinessTone(String(check.status))}`}>{String(check.status ?? "-")}</span>
            <strong>{String(check.label ?? check.key)}</strong>
            <em>{String(check.detail ?? "-")}</em>
            <b>{String(check.next_action ?? "-")}</b>
          </button>
        ))}
      </div>
      <div className="sourceReadinessGrid">
        {sources.slice(0, 6).map((source) => (
          <button
            key={String(source.source_id)}
            className={`sourceReadinessCard ${readinessTone(String(source.status))}`}
            type="button"
            onClick={() => onNavigate(readinessSectionForPath(String(source.action_path ?? "")))}
            title={String(source.next_action ?? "")}
          >
            <span className={`statusPill ${readinessTone(String(source.status))}`}>{String(source.status ?? "-")}</span>
            <strong>{String(source.label ?? source.source_id)}</strong>
            <em>{String(source.connector_id ?? "-")} · Credentials {String(source.credential_status ?? "-")} · Live {String(source.live_status ?? "-")}</em>
            <small>
              Ledger {formatCurrency(source.ledger_value_eur)} EUR
              {source.live_value_eur !== null && source.live_value_eur !== undefined
                ? ` · Live ${formatCurrency(source.live_value_eur)} EUR · Delta ${formatCurrency(source.delta_value_eur ?? 0)} EUR`
                : ""}
            </small>
          </button>
        ))}
      </div>
    </section>
  );
}

function readinessTone(status: string | undefined): "ok" | "warning" | "blocked" | "neutral" {
  const normalized = String(status ?? "");
  if (normalized === "ready" || normalized === "ok") {
    return "ok";
  }
  if (normalized === "review" || normalized === "warning") {
    return "warning";
  }
  if (normalized === "info") {
    return "neutral";
  }
  if (normalized === "blocked" || normalized === "blocker" || normalized === "setup_required") {
    return "blocked";
  }
  return "neutral";
}

function readinessLabel(status: string | undefined): string {
  return {
    ready: "bereit",
    review: "Review",
    blocked: "blockiert",
    setup_required: "Setup offen"
  }[String(status ?? "")] ?? String(status ?? "-");
}

function readinessSectionForPath(path: string | undefined): Section {
  const value = String(path ?? "");
  if (value.includes("/admin")) {
    return "admin";
  }
  if (value.includes("/sources")) {
    return "sources";
  }
  if (value.includes("/review")) {
    return "review";
  }
  if (value.includes("/tax")) {
    return "tax";
  }
  if (value.includes("/reports") || value.includes("/export")) {
    return "export";
  }
  if (value.includes("/portfolio")) {
    return "portfolio";
  }
  return "dashboard";
}

function readinessYearsLine(report: NonNullable<Snapshot["productReadiness"]>): string {
  const ready = report.ready_years ?? [];
  const conservative = report.conservative_ready_years ?? [];
  const review = report.review_years ?? [];
  const blocked = report.blocked_years ?? [];
  const parts = [
    ready.length > 0 ? `BMF-ready: ${ready.join(", ")}` : "",
    conservative.length > 0 ? `konservativ: ${conservative.join(", ")}` : "",
    review.length > 0 ? `Review: ${review.join(", ")}` : "",
    blocked.length > 0 ? `blockiert: ${blocked.join(", ")}` : ""
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(" · ") : "Noch kein Jahres-Snapshot fuer die Abgabe geladen.";
}

function DashboardPortfolioStatus({
  portfolio,
  review
}: {
  portfolio: Snapshot["portfolio"];
  review: Snapshot["review"];
}) {
  const total = Number(portfolio?.total_value_eur ?? 0);
  const excludedAccounts = portfolio?.excluded_account_summary ?? [];
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
            {review?.allow_export ? "Review frei" : "Review blockiert"}
          </span>
        </div>
        <div className="statusRows">
          <StatusRow label="Aktueller Bestand" value={`${formatCurrency(total)} EUR`} />
          <StatusRow label="Technische Belegkonten" value={`${excludedAccounts.length} · nicht im Bestand`} />
          <StatusRow label="Bestandslogik" value="Belegkonten nicht addieren" />
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
  lossPlanner,
  priceCoverage,
  onViewModeChange
}: {
  portfolio: Snapshot["portfolio"];
  sources: Snapshot["portfolioSources"];
  holdingPeriods: Snapshot["taxHoldingPeriods"];
  lossPlanner: Snapshot["taxLossRealizationPlanner"];
  priceCoverage: Snapshot["priceCoverage"];
  onViewModeChange: (mode: PortfolioViewMode) => void;
}) {
  const missingPrices = portfolio?.missing_price_assets ?? [];
  const portfolioReady = Boolean(portfolio);
  const priceCoveragePct = (priceCoverage?.missing_count ?? missingPrices.length) === 0 ? "100" : "0";
  const tone = !portfolioReady ? "loading" : missingPrices.length > 0 ? "warning" : "ok";
  const latestPriceAt = (portfolio?.asset_summary ?? [])
    .map((row) => String(row.priced_at_latest ?? ""))
    .filter(Boolean)
    .sort()
    .at(-1);
  const topSource = (sources?.groups ?? [])[0];
  return (
    <Stack>
      <section className={`portfolioDecision ${tone}`}>
        <div className="portfolioDecisionMain">
          <span className="heroKicker">Portfolio-Uebersicht</span>
          <h2>{portfolioReady ? `${formatCurrency(portfolio?.total_value_eur)} EUR` : "Portfolio wird geladen"}</h2>
          <p>
            Aktueller Bestand mit Preisdeckung, Quellenverteilung und Haltefrist-Ausblick. Detailabgleich und Preisdiagnosen liegen in den Tabs.
          </p>
          <div className="taxFilingTargets">
            <span className={`statusPill ${tone}`}>{!portfolioReady ? "wird geladen" : missingPrices.length === 0 ? "Preise vollstaendig" : "Preise pruefen"}</span>
            <span>Preisstand {portfolioReady ? latestPriceAt ? formatDateTime(latestPriceAt) : "nicht belegt" : "wird geladen"}</span>
            <span>Top-Quelle {portfolioReady ? topSource ? String(topSource.source_group) : "nicht vorhanden" : "wird geladen"}</span>
          </div>
        </div>
        <div className="portfolioDecisionActions">
          <button type="button" onClick={() => onViewModeChange("overview")}>
            <WalletCards size={18} />
            <span>Bestaende</span>
          </button>
          <button type="button" onClick={() => onViewModeChange("reconciliation")}>
            <RefreshCcw size={18} />
            <span>Live-Abgleich</span>
          </button>
          <button type="button" onClick={() => onViewModeChange("expert")}>
            <Settings size={18} />
            <span>Diagnose</span>
          </button>
        </div>
        <div className="taxFilingDecisionMetrics">
          <Metric title="Preisdeckung" value={portfolioReady && priceCoverage ? formatPercent(priceCoveragePct) : "Wird geladen"} />
          <Metric title="Jetzt steuerfrei" value={holdingPeriods ? `${formatCurrency(holdingPeriods.tax_free_now_value_eur)} EUR` : "Wird geladen"} />
          <Metric title="30 Tage" value={holdingPeriods ? `${formatCurrency(holdingPeriods.next_30_days_value_eur)} EUR` : "Wird geladen"} />
          <Metric title="Technische Belegkonten" value={portfolioReady ? String(portfolio?.excluded_account_summary?.length ?? 0) : "Wird geladen"} />
        </div>
      </section>
      <PortfolioHoldingDecisionPanel
        holdingPeriods={holdingPeriods}
        lossPlanner={lossPlanner}
      />
    </Stack>
  );
}

function PortfolioHoldingDecisionPanel({
  holdingPeriods,
  lossPlanner
}: {
  holdingPeriods: Snapshot["taxHoldingPeriods"];
  lossPlanner: Snapshot["taxLossRealizationPlanner"];
}) {
  const buckets = holdingPeriods?.buckets ?? [];
  const lots = holdingPeriods?.lots ?? [];
  const lossRows = lossPlanner?.rows ?? [];
  const topLossRows = lossRows
    .filter((row) => String(row.status) === "tax_relevant_loss_if_sold_now")
    .slice(0, 4);
  const maxBucketValue = Math.max(...buckets.map((bucket) => parseNumber(bucket.value_eur)), 1);
  const holdingReady = Boolean(holdingPeriods);
  const lossPlannerReady = Boolean(lossPlanner);
  return (
    <section className="holdingDecisionPanel">
      <div className="holdingDecisionHeader">
        <div>
          <span className="heroKicker">Haltefrist & Verkaufsfenster</span>
          <h3>Was kann steuerfrei oder verlustrelevant sein?</h3>
          <p>
            {holdingReady
              ? `Sicht aus offenen FIFO-Lots ab ${formatDateTime(holdingPeriods?.as_of)}. Dust unter ${formatCurrency(holdingPeriods?.min_value_eur ?? 1)} EUR wird ausgeblendet.`
              : "Offene FIFO-Lots und steuerliche Verkaufsfenster werden geladen."}
          </p>
        </div>
      </div>
      <div className="holdingTimelineMetrics">
        <Metric title="Jetzt steuerfrei" value={holdingReady ? `${formatCurrency(holdingPeriods?.tax_free_now_value_eur)} EUR` : "Wird geladen"} />
        <Metric title="7 Tage" value={holdingReady ? `${formatCurrency(holdingPeriods?.next_7_days_value_eur)} EUR` : "Wird geladen"} />
        <Metric title="7 Monate" value={holdingReady ? `${formatCurrency(holdingPeriods?.next_7_months_value_eur)} EUR` : "Wird geladen"} />
        <Metric title="1 Jahr" value={holdingReady ? `${formatCurrency(holdingPeriods?.next_year_value_eur)} EUR` : "Wird geladen"} />
        <Metric title="Verlust jetzt nutzbar" value={lossPlannerReady ? `${formatCurrency(lossPlanner?.tax_relevant_loss_if_sold_now_eur)} EUR` : "Wird geladen"} />
      </div>
      <div className="holdingTimelineGrid">
        <div className="holdingBucketList">
          {!holdingReady ? (
            <div className="loadingPlaceholder" aria-label="Haltefrist-Buckets werden geladen"><span /><span /><span /></div>
          ) : buckets.length === 0 ? (
            <div className="empty">Keine Haltefrist-Buckets vorhanden.</div>
          ) : (
            buckets.map((bucket) => (
              <div key={String(bucket.bucket)} className="holdingBucketRow">
                <div>
                  <strong>{String(bucket.label ?? bucket.bucket)}</strong>
                  <span>{String(bucket.lots_count ?? 0)} Lot(s) · {(Array.isArray(bucket.assets) ? bucket.assets : []).join(", ") || "-"}</span>
                </div>
                <em>{formatCurrency(bucket.value_eur)} EUR</em>
                <div className="barTrack" aria-hidden="true">
                  <div className="barFill" style={{ width: `${Math.max(4, Math.min((parseNumber(bucket.value_eur) / maxBucketValue) * 100, 100))}%` }} />
                </div>
              </div>
            ))
          )}
        </div>
        <div className="holdingActionList">
          <div className="holdingActionHeader">
            <strong>Top-Verlustfenster</strong>
            <span>{topLossRows.length} Position(en)</span>
          </div>
          {!lossPlannerReady ? (
            <div className="loadingPlaceholder" aria-label="Verlustfenster werden geladen"><span /><span /><span /></div>
          ) : topLossRows.length === 0 ? (
            <div className="empty">Keine steuerrelevanten Verlustfenster ueber Filter sichtbar.</div>
          ) : (
            topLossRows.map((row) => (
              <div key={String(row.lot_id)} className="holdingActionItem">
                <strong>{String(row.asset)}</strong>
                <span>{formatCurrency(row.unrealized_gain_loss_eur)} EUR · steuerfrei ab {row.tax_free_at ? formatDate(row.tax_free_at) : "-"}</span>
                <em>{String(row.action_note ?? row.evidence_note ?? "")}</em>
              </div>
            ))
          )}
        </div>
      </div>
      <div className="holdingLotStrip">
        {lots.slice(0, 8).map((lot) => (
          <div key={String(lot.lot_id)} className={`holdingLotChip ${parseNumber(lot.days_until_tax_free) <= 0 ? "ok" : parseNumber(lot.days_until_tax_free) <= 30 ? "warning" : ""}`}>
            <strong>{String(lot.asset)}</strong>
            <span>{formatCurrency(lot.current_value_eur)} EUR</span>
            <em>{parseNumber(lot.days_until_tax_free) <= 0 ? "steuerfrei" : `${String(lot.days_until_tax_free)} Tage`}</em>
          </div>
        ))}
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
        title="Technische Belegkonten (nicht Vermoegen)"
        rows={portfolio?.excluded_account_summary ?? []}
        footer={`${portfolio?.excluded_value_semantics ?? "Kein Konto- oder Portfoliobestand; nicht zum Gesamtwert addieren."} Rechnerischer Diagnosewert: ${formatCurrency(portfolio?.excluded_value_eur)} EUR.`}
      />
    </Stack>
  );
}

function PortfolioTokenRiskPanel({
  report,
  reviewDecisions,
  filter,
  onFilterChange
}: {
  report: Snapshot["portfolioTokenRisk"];
  reviewDecisions: Snapshot["reviewDecisions"];
  filter: TokenRiskFilter;
  onFilterChange: (mode: TokenRiskFilter) => void;
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
  const rawLedgerValue = parseNumber(report?.total_ledger_value_eur);
  const adjustmentValue = parseNumber(report?.ledger_adjustment_value_eur);
  const reconciledLedgerValue = parseNumber(
    report?.total_reconciled_ledger_value_eur ?? report?.total_ledger_value_eur
  );
  const overlayRows = rows.filter(
    (row) => Array.isArray(row.ledger_adjustment_ids) && row.ledger_adjustment_ids.length > 0
  );
  const topRows = rows.filter((row) => !overlayRows.includes(row)).slice(0, 12);

  return (
    <div className="panel portfolioBreakdown">
      <div className="panelToolbar">
        <strong>Live-Abgleich gegen API-/RPC-Anker</strong>
        <span>{blockers} Blocker · {warnings} Warnungen</span>
      </div>
      <div className="portfolioSummaryStrip">
        <Metric title="Rohledger" value={`${formatCurrency(rawLedgerValue)} EUR`} />
        <Metric title="Beleg-Overlays" value={String(report?.applied_ledger_adjustments_count ?? 0)} />
        <Metric title="Overlay-Wert" value={`${formatCurrency(adjustmentValue)} EUR`} />
        <Metric title="Abgleichswert" value={`${formatCurrency(reconciledLedgerValue)} EUR`} />
        <Metric title="Erwartet Null, Ledger offen" value={`${formatCurrency(expectedZero)} EUR`} />
        <Metric title="Noch ohne Live-Anker" value={`${formatCurrency(unverified)} EUR`} />
        <Metric title="Fehlende Wallets" value={String(report?.missing_wallets?.length ?? 0)} />
        <Metric title="Abgleichzeilen" value={String(rows.length)} />
      </div>
      {overlayRows.length > 0 ? (
        <TablePanel
          title="TxID-gebundene Beleg-Overlays"
          rows={overlayRows.map((row) => ({
            quelle: row.source_group,
            asset: row.asset,
            rohledger_menge: row.raw_ledger_quantity,
            beleg_overlay_menge: row.ledger_adjustment_quantity,
            abgleich_menge: row.ledger_quantity,
            live_menge: row.external_quantity ?? "0",
            status: row.status,
            txid: Array.isArray(row.ledger_adjustment_tx_ids)
              ? row.ledger_adjustment_tx_ids.map((value) => shortAccount(String(value))).join(", ")
              : "-",
            txid_full: Array.isArray(row.ledger_adjustment_tx_ids)
              ? row.ledger_adjustment_tx_ids.join(" | ")
              : ""
          }))}
          footer="Das Overlay korrigiert ausschließlich den Live-Abgleich. Rohledger, Canonical Events, FIFO und Steuerzeilen bleiben unverändert; die vollständige TxID steht im Tooltip."
          compact
        />
      ) : null}
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

function PortfolioValueHistoryPanel({
  history,
  selectedDate
}: {
  history: Snapshot["portfolioValueHistory"];
  selectedDate: string;
}) {
  const rawPoints = history?.points ?? [];
  const pointsData = rawPoints
    .map((point) => ({
      date: String(point.date ?? ""),
      value: parseNumber(point.total_value_eur),
      missing: Array.isArray(point.missing_price_assets) ? point.missing_price_assets.length : 0,
      positions: Number(point.positions_count ?? 0)
    }))
    .filter((point) => point.date);
  const minValue = Math.min(...pointsData.map((point) => point.value), 0);
  const maxValue = Math.max(...pointsData.map((point) => point.value), 1);
  const latest = pointsData[pointsData.length - 1];
  const negativeCount = Number(history?.negative_points_count ?? 0);
  const width = 920;
  const height = 220;
  const left = 58;
  const right = 28;
  const top = 24;
  const bottom = 40;
  const chartWidth = width - left - right;
  const chartHeight = height - top - bottom;
  const range = Math.max(maxValue - minValue, 1);
  const chartPoints = pointsData.map((point, index) => {
    const x = left + (pointsData.length <= 1 ? 0 : (index / (pointsData.length - 1)) * chartWidth);
    const y = top + chartHeight - ((point.value - minValue) / range) * chartHeight;
    return { ...point, x, y };
  });
  const zeroY = top + chartHeight - ((0 - minValue) / range) * chartHeight;
  const path = chartPoints
    .map((point, index) => `${index === 0 ? "M" : "L"} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
    .join(" ");

  return (
    <div className="panel portfolioHistoryPanel">
      <div className="panelToolbar">
        <strong>V2-Portfolioverlauf</strong>
        <span>{history?.interval ?? "month"} · {history?.points_count ?? 0} Punkte</span>
      </div>
      <div className="portfolioSummaryStrip">
        <Metric title="Letzter Stichtag" value={latest ? `${formatCurrency(latest.value)} EUR` : "-"} />
        <Metric title="Von" value={history?.from_date ?? "-"} />
        <Metric title="Bis" value={history?.to_date ?? selectedDate} />
        <Metric title="Negative V2-Punkte" value={String(negativeCount)} />
      </div>
      {negativeCount > 0 ? (
        <div className="notice inlineNotice reviewNotice">
          Der V2-Verlauf enthaelt negative Stichtage. Das ist ein echter Ledger-Prueffall und nicht der alte Legacy-Roh-Event-Chart.
        </div>
      ) : (
        <div className="notice inlineNotice">
          Keine negativen V2-Stichtagswerte im geladenen Verlauf. Diese Kurve nutzt dieselbe Methodik wie die Stichtagsbewertung.
        </div>
      )}
      <div className="trendCanvas portfolioValueCanvas">
        {chartPoints.length === 0 ? (
          <div className="empty">Keine Verlaufspunkte vorhanden.</div>
        ) : (
          <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="V2-Portfolioverlauf">
            <line x1={left} y1={top + chartHeight} x2={width - right} y2={top + chartHeight} />
            <line x1={left} y1={top} x2={left} y2={top + chartHeight} />
            {minValue < 0 ? <line className="zeroLine" x1={left} y1={zeroY} x2={width - right} y2={zeroY} /> : null}
            <text x={left} y={height - 12}>{chartPoints[0]?.date}</text>
            <text x={width - right - 92} y={height - 12}>{chartPoints[chartPoints.length - 1]?.date}</text>
            <text x={left + 4} y={top + 14}>{formatCurrency(maxValue)} EUR</text>
            <text x={left + 4} y={top + chartHeight - 4}>{formatCurrency(minValue)} EUR</text>
            <path d={path} />
            {chartPoints.map((point, index) => (
              <g key={`${point.date}-${index}`}>
                <circle cx={point.x} cy={point.y} r={point.value < 0 ? "5" : "4"} className={point.value < 0 ? "negativePoint" : ""} />
                <title>{`${point.date}: ${formatCurrency(point.value)} EUR · Positionen: ${point.positions} · fehlende Preise: ${point.missing}`}</title>
              </g>
            ))}
          </svg>
        )}
      </div>
      <div className="footer">{history?.methodology ?? ""}</div>
    </div>
  );
}

function PortfolioAsOfPage({
  snapshot,
  history,
  asOfDate,
  onAsOfDateChange
}: {
  snapshot: Snapshot["portfolioAsOf"];
  history: Snapshot["portfolioValueHistory"];
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
            Mengen aus dem Ledger bis einschliesslich Stichtag, Bewertung mit dem letzten unabhaengig belegten EUR-Preis am oder vor dem Stichtag.
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

      <PortfolioValueHistoryPanel history={history} selectedDate={asOfDate} />

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
            <StatusRow label="Technische Belegkonten" value={`${snapshot?.excluded_account_summary?.length ?? 0} · nicht eingerechnet`} />
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
        excluded_value_semantics: snapshot.excluded_value_semantics,
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
          <Metric title="Review-Gate" value={review?.allow_export ? "frei" : "blockiert"} />
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
      <TokenRiskReviewPanel report={jupiterRiskReview} />
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
  report
}: {
  report: Snapshot["jupiterRiskReview"];
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
          <FileDown size={16} />
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
  stablecoinFxAnchorPreview,
  solscanSignatureReview,
  binanceNormalizerReview,
  eventQuoteEvidenceReview,
  onDownload,
  onAddDecision,
  onAddStablecoinFxAnchorDecision,
  onApplyStablecoinFxAnchor,
  compact = false
}: {
  quality: Snapshot["priceQuality"];
  manualReview?: Snapshot["priceManualReview"];
  stablecoinFxReview?: Snapshot["priceStablecoinFxReview"];
  stablecoinFxAnchorPreview?: Snapshot["priceStablecoinFxAnchorPreview"];
  solscanSignatureReview?: Snapshot["priceSolscanSignatureReview"];
  binanceNormalizerReview?: Snapshot["priceBinanceNormalizerReview"];
  eventQuoteEvidenceReview?: Snapshot["priceEventQuoteEvidenceReview"];
  onDownload?: (path: string) => void;
  onAddDecision?: (row: Record<string, unknown>, decisionStatus: string) => void;
  onAddStablecoinFxAnchorDecision?: (row: Record<string, unknown>, action: string) => void;
  onApplyStablecoinFxAnchor?: (row: Record<string, unknown>, dryRun: boolean) => void;
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
      {stablecoinFxAnchorPreview ? (
        <StablecoinFxAnchorPreviewPanel
          report={stablecoinFxAnchorPreview}
          onDownload={onDownload}
          onAddDecision={onAddStablecoinFxAnchorDecision}
          onApply={onApplyStablecoinFxAnchor}
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

function StablecoinFxAnchorPreviewPanel({
  report,
  onDownload,
  onAddDecision,
  onApply
}: {
  report: Snapshot["priceStablecoinFxAnchorPreview"];
  onDownload?: (path: string) => void;
  onAddDecision?: (row: Record<string, unknown>, action: string) => void;
  onApply?: (row: Record<string, unknown>, dryRun: boolean) => void;
}) {
  const groups = report?.groups ?? [];
  const rows = groups.map((row) => ({
    status: row.status,
    asset: row.asset,
    year: row.year,
    source: row.source ?? "derived:event_quote",
    ready_days: row.ready_days,
    missing_days: row.missing_days,
    decisions: row.existing_decisions_count,
    action: row.latest_decision_action ?? "-",
    tax_lines_count: row.tax_lines_count,
    next_action: row.recommended_next_action
  }));
  const canAct = onAddDecision !== undefined || onApply !== undefined || onDownload !== undefined;
  return (
    <Stack>
      <div className="panel">
        <div className="panelToolbar">
          <strong>Stablecoin-FX-Anker</strong>
          <span>{report?.artifact_generated_at ? formatDateTime(report.artifact_generated_at) : "-"}</span>
        </div>
        <div className="reviewSummary">
          <Metric title="Offene Tage" value={String(report?.required_days ?? 0)} />
          <Metric title="Bereit" value={String(report?.ready_days ?? 0)} />
          <Metric title="Fehlend" value={String(report?.missing_days ?? 0)} />
          <Metric title="Review offen" value={String(report?.groups_requiring_review ?? 0)} />
          <Metric title="Tax-Delta" value={`${formatCurrency(report?.taxable_gain_loss_delta_eur)} EUR`} />
        </div>
        <div className="footer">
          {report?.artifact_found
            ? "V1-USD/EUR-FX-Anker sind als Artefakt vorhanden. Apply ist erst nach Review-Freigabe je Asset/Jahr moeglich."
            : "Kein Stablecoin-FX-Anker-Artefakt vorhanden."}
        </div>
      </div>
      <TablePanel
        title="Stablecoin-FX-Anker Gruppen"
        rows={rows}
        footer={report?.methodology ?? "Stablecoin-FX-Ankerstatus wird geladen."}
        rowActions={canAct ? [
          ...(onDownload ? [{
            label: "Artefakt JSON",
            icon: <FileJson size={16} />,
            onClick: () => onDownload("/api/v1/prices/quality/stablecoin-fx-anchor-preview-latest?include_rows=true")
          }] : []),
          ...(onAddDecision ? [
            {
              label: "Apply freigeben",
              icon: <Check size={16} />,
              onClick: (row: Record<string, unknown>) => onAddDecision(row, "apply_replacement")
            },
            {
              label: "Nur dokumentieren",
              icon: <ReceiptText size={16} />,
              onClick: (row: Record<string, unknown>) => onAddDecision(row, "document_delta_only")
            },
            {
              label: "Bestehende Bewertung behalten",
              icon: <AlertTriangle size={16} />,
              onClick: (row: Record<string, unknown>) => onAddDecision(row, "keep_existing")
            }
          ] : []),
          ...(onApply ? [
            {
              label: "Dry-Run",
              icon: <Database size={16} />,
              onClick: (row: Record<string, unknown>) => onApply(row, true)
            },
            {
              label: "Live anwenden",
              icon: <PackageCheck size={16} />,
              tone: "danger" as const,
              onClick: (row: Record<string, unknown>) => onApply(row, false)
            }
          ] : [])
        ] : undefined}
      />
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
  valuationRun,
  cutoffPriceGate,
  priceGate,
  cutoffDate,
  onCutoffDateChange,
  valuationDate,
  onValuationDateChange,
  materialityEur,
  onMaterialityEurChange,
  onRunDossier,
  runLoading,
  onAcceptTradeRepublicValuation,
  tradeRepublicValuationLoading,
  onUploadTradeRepublicDocuments,
  tradeRepublicDocumentUploadLoading,
  onUploadInheritanceDocuments,
  inheritanceDocumentUploadLoading,
  onAcceptInheritanceDocument,
  inheritanceDocumentReviewLoading,
  onUploadBankCamtDocuments,
  bankCamtUploadLoading,
  onAcceptCoinbaseValuation,
  coinbaseValuationLoading,
  priceGateLoading,
  onRunPriceGateBackfill,
  onAcceptTokenValuation,
  serviceRouteEvidence,
  onRefreshServiceRouteEvidence,
  onAcceptServiceRouteEvidence,
  serviceRouteEvidenceLoading,
  onDownload,
  onNavigate
}: {
  report: Snapshot["divorceEqualization"];
  valuationRun: Snapshot["divorceValuationRun"];
  cutoffPriceGate: Snapshot["asOfCutoffPriceGate"];
  priceGate: Snapshot["asOfPriceGate"];
  cutoffDate: string;
  onCutoffDateChange: (date: string) => void;
  valuationDate: string;
  onValuationDateChange: (date: string) => void;
  materialityEur: string;
  onMaterialityEurChange: (value: string) => void;
  onRunDossier: () => void;
  runLoading: boolean;
  onAcceptTradeRepublicValuation: (documentSha256: string) => void;
  tradeRepublicValuationLoading: boolean;
  onUploadTradeRepublicDocuments: (files: File[]) => void;
  tradeRepublicDocumentUploadLoading: boolean;
  onUploadInheritanceDocuments: (files: File[]) => void;
  inheritanceDocumentUploadLoading: boolean;
  onAcceptInheritanceDocument: (documentSha256: string) => void;
  inheritanceDocumentReviewLoading: boolean;
  onUploadBankCamtDocuments: (files: File[]) => void;
  bankCamtUploadLoading: boolean;
  onAcceptCoinbaseValuation: (historyManifestSha256: string) => void;
  coinbaseValuationLoading: boolean;
  priceGateLoading: boolean;
  onRunPriceGateBackfill: (dryRun: boolean, targetDate?: string) => void;
  onAcceptTokenValuation: (asset: string, asOfDate: string) => void;
  serviceRouteEvidence: Snapshot["divorceServiceRouteEvidence"];
  onRefreshServiceRouteEvidence: (txId: string) => void;
  onAcceptServiceRouteEvidence: (
    txId: string,
    semanticSha256: string
  ) => void;
  serviceRouteEvidenceLoading: boolean;
  onDownload: (path: string) => void;
  onNavigate: (section: Section) => void;
}) {
  const [priceGateMode, setPriceGateMode] = useState<"cutoff" | "valuation">(
    "valuation"
  );
  const marital = report?.marital_pre_cutoff ?? {};
  const direct = report?.post_cutoff_direct_eur_invest ?? {};
  const allLots = report?.post_cutoff_all_lots ?? {};
  const accounts = report?.accounts ?? [];
  const capitalFlow = report?.capital_flow_gate;
  const capitalOutflows = capitalFlow?.outflows ?? [];
  const serviceRouteCandidate = capitalOutflows.find(
    (row) => row.classification === "trade_or_service_route" && Boolean(row.tx_id)
  );
  const acceptedServiceRoute = capitalOutflows.find(
    (row) => row.classification === "internal_service_position_loss" && Boolean(row.tx_id)
  );
  const serviceRouteTxId = String(
    serviceRouteCandidate?.tx_id
      ?? acceptedServiceRoute?.tx_id
      ?? serviceRouteEvidence?.tx_id
      ?? ""
  );
  const serviceRouteEvidenceMatches = Boolean(
    serviceRouteEvidence
      && serviceRouteTxId
      && serviceRouteEvidence.tx_id === serviceRouteTxId
  );
  const inheritanceOrigin = report?.inheritance_origin_gate;
  const inheritanceCredits = inheritanceOrigin?.inheritance_credits ?? [];
  const activePriceGate = priceGateMode === "cutoff" ? cutoffPriceGate : priceGate;
  const activePriceGateDate = priceGateMode === "cutoff" ? cutoffDate : valuationDate;
  const bankStatementTone = inheritanceOrigin?.bank_statement_status === "complete"
    ? "ok"
    : inheritanceOrigin?.bank_statement_status === "partial"
      ? "warning"
      : "blocked";
  const bankStatementLabel = inheritanceOrigin?.bank_statement_status === "complete"
    ? "Zeitraum vollstaendig"
    : inheritanceOrigin?.bank_statement_status === "partial"
      ? "Zeitraumluecke"
      : "Bankbeleg fehlt";
  const sparkasseStatementConnector = inheritanceOrigin?.sparkasse_statement_connector;
  const sparkasseStatementTone = sparkasseStatementConnector?.status === "parsed"
    && (sparkasseStatementConnector?.missing_camt_matches_count ?? 0) === 0
    && (sparkasseStatementConnector?.ambiguous_camt_matches_count ?? 0) === 0
    ? "ok"
    : sparkasseStatementConnector?.status === "partial"
      || (sparkasseStatementConnector?.exact_camt_matches_count ?? 0) > 0
      ? "warning"
      : "blocked";
  const sparkasseStatementLabel = sparkasseStatementConnector?.status === "parsed"
    && (sparkasseStatementConnector?.missing_camt_matches_count ?? 0) === 0
    && (sparkasseStatementConnector?.ambiguous_camt_matches_count ?? 0) === 0
    ? "PDF und CAMT stimmen ueberein"
    : sparkasseStatementConnector?.status === "missing"
      ? "PDF-Auszug fehlt"
      : "PDF-Abgleich pruefen";
  const inheritanceDocumentConnector = inheritanceOrigin?.formal_inheritance_connector;
  const inheritanceDocuments = inheritanceDocumentConnector?.documents ?? [];
  const inheritanceDocumentCandidate = inheritanceDocuments.find(
    (item) => item.review_status === "candidate"
  );
  const inheritanceDocumentTone = inheritanceDocumentConnector?.status === "reviewed"
    ? "ok"
    : inheritanceDocumentConnector?.status === "candidate_present"
      ? "warning"
      : "blocked";
  const inheritanceDocumentLabel = inheritanceDocumentConnector?.status === "reviewed"
    ? "Formal belegt"
    : inheritanceDocumentConnector?.status === "candidate_present"
      ? "Pruefung erforderlich"
      : "Dokument fehlt";
  const tradeRepublicConnector = inheritanceOrigin?.trade_republic_connector;
  const tradeRepublicDocuments = tradeRepublicConnector?.documents ?? [];
  const tradeRepublicStatus = String(
    tradeRepublicConnector?.end_asset_statement_status ?? "missing"
  );
  const tradeRepublicStatusTone = tradeRepublicStatus === "reviewed"
    ? "ok"
    : tradeRepublicStatus === "exact_date_candidate" || tradeRepublicStatus === "candidate_present"
      ? "warning"
      : "blocked";
  const tradeRepublicStatusLabel = tradeRepublicStatus === "reviewed"
    ? "Stichtagswert freigegeben"
    : tradeRepublicStatus === "exact_date_candidate"
      ? "Pruefbarer Wert erkannt"
      : tradeRepublicStatus === "ambiguous"
        ? "Werte widersprechen sich"
        : tradeRepublicStatus === "candidate_present"
          ? "Dokument in Pruefung"
          : "Stichtagsbeleg fehlt";
  const coinbaseConnector = inheritanceOrigin?.coinbase_connector;
  const coinbaseStatusTone = coinbaseConnector?.history_status === "reviewed"
    ? "ok"
    : coinbaseConnector?.history_status === "imported_pending_review"
      ? "warning"
      : "blocked";
  const coinbaseStatusLabel = coinbaseConnector?.history_status === "reviewed"
    ? "Stichtagswert freigegeben"
    : coinbaseConnector?.history_status === "imported_pending_review"
      ? "Historie in Pruefung"
      : "Historie fehlt";
  const valuationTokenRows = equalizationValuationTokenRows(accounts);
  const cutoffLabel = formatDate(report?.stichtage?.separation_date ?? cutoffDate);
  const valuationLabel = formatDate(report?.stichtage?.end_asset_date ?? valuationDate);
  const exportQuery = `?separation_date=${encodeURIComponent(cutoffDate)}&end_asset_date=${encodeURIComponent(valuationDate)}&materiality_threshold_eur=${encodeURIComponent(materialityEur || "1")}`;
  const dossierDownload = String(
    valuationRun?.evidence_files?.find((item) => item.kind === "evidence_package")?.download_url ?? ""
  );
  return (
    <Stack>
      <section className="panel valuationControlPanel">
        <div className="panelToolbar">
          <strong>Stichtagsdossier festlegen</strong>
          <span className={`statusPill ${valuationRun?.strict_ready ? "ok" : valuationRun?.status === "blocked" ? "blocked" : "warning"}`}>
            {valuationRun ? valuationRun.status : "noch kein Lauf"}
          </span>
        </div>
        <div className="valuationControlGrid">
          <label>
            Trennungsstichtag
            <input type="date" value={cutoffDate} onChange={(event) => onCutoffDateChange(event.target.value)} />
          </label>
          <label>
            Endvermoegensstichtag
            <input type="date" value={valuationDate} onChange={(event) => onValuationDateChange(event.target.value)} />
          </label>
          <label>
            Preis-Materialitaet in EUR
            <input min="0" step="0.01" type="number" value={materialityEur} onChange={(event) => onMaterialityEurChange(event.target.value)} />
          </label>
          <button type="button" onClick={onRunDossier} disabled={runLoading || !cutoffDate || !valuationDate}>
            <RefreshCcw size={16} />
            {runLoading ? "FIFO und Stichtage werden geprueft" : "Dossier neu erzeugen"}
          </button>
          {dossierDownload ? (
            <button type="button" onClick={() => onDownload(dossierDownload)}>
              <FileDown size={16} />
              Letztes Dossier
            </button>
          ) : null}
        </div>
        {runLoading ? (
          <div className="notice reviewNotice">Zwei vollstaendige Wallet-/Depot-FIFO-Replays laufen. Die Ansicht bleibt geoeffnet und meldet das Ergebnis nach Abschluss.</div>
        ) : null}
        <div className={`notice ${report?.stichtage?.court_evidence_status === "documented" ? "" : "reviewNotice"}`}>
          <strong>{report?.stichtage?.end_asset_legal_basis ?? "§ 1384 BGB"}:</strong>{" "}
          {report?.stichtage?.court_evidence_note ?? "Gerichts-/Zustellungsbeleg fuer den Endvermoegensstichtag beilegen."}
        </div>
      </section>

      <section className="divorceHero">
        <div>
          <span className="heroKicker">Zugewinnausgleich</span>
          <h2>{cutoffLabel} bis {valuationLabel}</h2>
          <p>{report?.legal_note ?? "Auswertung wird geladen."}</p>
        </div>
        <div className="reportHeroStats">
          <Metric title="Vermoegen bei Trennung" value={`${formatCurrency(report?.cutoff_portfolio_value_eur)} EUR`} />
          <Metric title="Endvermoegen" value={`${formatCurrency(report?.valuation_portfolio_value_eur)} EUR`} />
          <Metric title="Bruttoveraenderung" value={`${formatCurrency(report?.gross_portfolio_change_eur)} EUR`} />
          <Metric title="Brutto ohne Review" value={`${formatCurrency(report?.gross_portfolio_change_without_review_assets_eur)} EUR`} />
          <Metric title="Vorlaeufig flussbereinigt" value={`${formatCurrency(report?.adjusted_gain_loss_excluding_new_invest_eur)} EUR`} />
          <Metric title="Vorlaeufig ohne Review-Token" value={`${formatCurrency(report?.adjusted_gain_loss_without_review_assets_eur)} EUR`} />
          <Metric title="Trennungsstichtag" value={cutoffLabel} />
          <Metric title="Endvermoegensstichtag" value={valuationLabel} />
          <Metric title="Stichtags-Zeitzone" value={report?.stichtage?.timezone ?? "Europe/Berlin"} />
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
          <Metric title={`Portfolio ${cutoffLabel}`} value={`${formatCurrency(report?.cutoff_portfolio_value_eur)} EUR`} />
          <Metric title={`Portfolio ${valuationLabel}`} value={`${formatCurrency(report?.valuation_portfolio_value_eur)} EUR`} />
          <Metric title="ohne Review-Token" value={`${formatCurrency(report?.valuation_value_without_review_assets_eur)} EUR`} />
          <Metric title="Review-Token" value={`${formatCurrency(report?.valuation_review_value_eur)} EUR`} />
          <Metric title="Staub" value={`${formatCurrency(report?.valuation_dust_value_eur)} EUR`} />
          <Metric title="Neue externe Einzahlungen" value={`${formatCurrency(report?.net_external_invest_since_cutoff_eur)} EUR`} />
          <Metric title="davon bestaetigt" value={`${formatCurrency(report?.confirmed_external_invest_since_cutoff_eur)} EUR`} />
          <Metric title="davon MoonPay belegt" value={`${formatCurrency(report?.confirmed_onramp_invest_since_cutoff_eur)} EUR`} />
          <Metric title="davon Onramp vorlaeufig" value={`${formatCurrency(report?.provisional_onramp_invest_since_cutoff_eur)} EUR`} />
          <Metric title="Vorlaeufige Flussveraenderung" value={`${formatCurrency(report?.adjusted_gain_loss_excluding_new_invest_eur)} EUR`} />
          <Metric title="Vorlaeufig ohne Review-Token" value={`${formatCurrency(report?.adjusted_gain_loss_without_review_assets_eur)} EUR`} />
          <p className="reportYearSummary">
            Diese Karte nutzt echte Portfolio-Stichtagswerte. Das Ergebnis ist erst belastbar, wenn Preis-, FIFO-, Quellen- und Vermoegensfluss-Gates freigegeben sind.
          </p>
        </div>
      </div>

      <section className="valuationGateBand">
        <div className="valuationGateHeader">
          <div>
            <span className="heroKicker">Mittelherkunft</span>
            <h3>Erbgeld- und Depotspur</h3>
          </div>
          <div className="reportActionBand compactActions">
            <span className={`statusPill ${inheritanceOrigin?.strict_ready ? "ok" : "blocked"}`}>
              {inheritanceOrigin?.strict_ready ? "vollstaendig belegt" : "Nachweise offen"}
            </span>
            <button type="button" onClick={() => onDownload(`/api/v1/divorce/inheritance-origin.csv${exportQuery}`)}>
              <FileDown size={16} />
              Erbgeldspur CSV
            </button>
            <button type="button" onClick={() => onDownload(`/api/v1/divorce/inheritance-credits.csv${exportQuery}`)}>
              <FileDown size={16} />
              Erbmittelbelege
            </button>
          </div>
        </div>
        <div className="valuationGateMetrics">
          <Metric title="Erbmittelzufluesse gesamt" value={`${formatCurrency(inheritanceOrigin?.inheritance_credit_eur)} EUR`} />
          <Metric title="Belegte Erbmittelzufluesse" value={String(inheritanceOrigin?.inheritance_credit_count ?? inheritanceCredits.length)} />
          <Metric title="Bankseitige Investments" value={`${formatCurrency(inheritanceOrigin?.bank_identified_investment_eur)} EUR`} />
          <Metric title="Nur Plattformbeleg" value={`${formatCurrency(inheritanceOrigin?.platform_only_investment_eur)} EUR`} />
          <Metric title="Identifizierte Investments" value={`${formatCurrency(inheritanceOrigin?.total_identified_investment_eur)} EUR`} />
          <Metric title="Davon im Krypto-Ledger" value={`${formatCurrency(inheritanceOrigin?.crypto_tracked_investment_eur)} EUR`} />
          <Metric title="Externe Depots" value={`${formatCurrency(inheritanceOrigin?.external_asset_investment_eur)} EUR`} />
          <Metric
            title="Externe Depots am Endstichtag"
            value={inheritanceOrigin?.external_asset_end_value_eur == null
              ? "Beleg fehlt"
              : `${formatCurrency(inheritanceOrigin.external_asset_end_value_eur)} EUR`}
          />
          <Metric
            title="Nicht zugeordneter Erbbetrag"
            value={inheritanceOrigin?.declared_inheritance_headroom_eur == null
              ? "nicht berechenbar"
              : `${formatCurrency(inheritanceOrigin.declared_inheritance_headroom_eur)} EUR`}
          />
          <Metric title="Bankzeitraum" value={`${formatDate(inheritanceOrigin?.bank_statement_from)} bis ${formatDate(inheritanceOrigin?.bank_statement_to)}`} />
          <Metric title="Erbnachweis" value={inheritanceOrigin?.formal_inheritance_document_status === "documented" ? "referenziert" : "Dokument fehlt"} />
        </div>
        <TablePanel
          title="Belegte Erbmittelzufluesse"
          rows={inheritanceCredits.map((credit) => ({
            datum: formatDate(credit.booking_date),
            betrag: `${formatCurrency(credit.amount_eur)} EUR`,
            art: equalizationInheritanceCreditKindLabel(credit.credit_kind),
            datumsbasis: credit.date_basis === "bank_booking_date" ? "Bankbuchung" : "Dokumentdatum",
            primaerbeleg: credit.evidence_source === "bank_camt" ? "CAMT" : "Nachlassdokument",
            klassifikation: credit.classification_source === "camt_marker" ? "Nachlassmarker" : "Review",
            beleg: shortAccount(credit.transaction_reference_sha256),
            hinweis: credit.note
          }))}
          footer="Die Summe dokumentiert die Mittelherkunft. Spaetere Auszahlungen geerbter Vermoegenswerte werden einzeln gezeigt und duerfen in der familienrechtlichen Anfangsvermoegensbewertung nicht doppelt angesetzt werden."
          compact
        />
        <TablePanel
          title="Investitionen je Anbieter"
          rows={(inheritanceOrigin?.provider_summaries ?? []).filter((row) => Number(row.identified_investment_eur ?? 0) !== 0).map((row) => ({
            anbieter: row.label,
            bankbuchungen: row.bank_transactions_count,
            bankabfluss: `${formatCurrency(row.bank_outflow_eur)} EUR`,
            nur_plattform: `${formatCurrency(row.platform_only_outflow_eur)} EUR`,
            investiert: `${formatCurrency(row.identified_investment_eur)} EUR`,
            mittelherkunft: equalizationCapitalOriginLabel(String(row.capital_origin ?? "claimed_inheritance")),
            herkunftsbeleg: row.capital_origin_evidence_status,
            portfolioabdeckung: row.portfolio_coverage_status,
            stichtagswert: row.end_asset_value_eur == null ? "Beleg fehlt" : `${formatCurrency(row.end_asset_value_eur)} EUR`,
            hinweis: row.finding
          }))}
          footer="Ein belegter Bankabfluss beweist die Investitionshoehe, aber noch nicht den Depot- und Cash-Wert am Endvermoegensstichtag."
          compact
        />
        <div className="valuationGateGrid">
          <div className="valuationGateItem">
            <div className="panelToolbar">
              <strong>Sparkassen-Bankspur</strong>
              <span className={`statusPill ${sparkasseStatementConnector ? sparkasseStatementTone : bankStatementTone}`}>
                {sparkasseStatementConnector ? sparkasseStatementLabel : bankStatementLabel}
              </span>
            </div>
            <div className="evidenceFactGrid">
              <div><span>CAMT-Dateien</span><strong>{inheritanceOrigin?.bank_files_count ?? 0}</strong></div>
              <div><span>Von</span><strong>{formatDate(inheritanceOrigin?.bank_statement_from)}</strong></div>
              <div><span>Bis</span><strong>{formatDate(inheritanceOrigin?.bank_statement_to)}</strong></div>
              <div><span>PDF-Auszuege</span><strong>{sparkasseStatementConnector?.parsed_documents_count ?? 0}</strong></div>
              <div><span>PDF-Kryptobuchungen</span><strong>{sparkasseStatementConnector?.crypto_debits_count ?? 0}</strong></div>
              <div><span>PDF-Belegsumme</span><strong>{formatCurrency(sparkasseStatementConnector?.crypto_debits_eur)} EUR</strong></div>
              <div><span>Exakt gegen CAMT</span><strong>{sparkasseStatementConnector?.exact_camt_matches_count ?? 0}</strong></div>
              <div><span>Abgleich offen</span><strong>{(sparkasseStatementConnector?.missing_camt_matches_count ?? 0) + (sparkasseStatementConnector?.ambiguous_camt_matches_count ?? 0)}</strong></div>
            </div>
            <p>
              Fuer die lueckenlose Mittelherkunft muss der Kontozeitraum den Trennungsstichtag bis zum Endvermoegensstichtag abdecken.
              PDF-Auszuege dienen nur als zusaetzlicher Primaerbeleg; exakt gematchte CAMT-Fluesse werden nicht doppelt gezaehlt. Rohbuchungen und Kontodaten bleiben lokal.
            </p>
            <div className="reportActionBand compactActions evidenceActions">
              <label
                className={`fileActionButton ${bankCamtUploadLoading ? "disabled" : ""}`}
                title="Native Sparkassen-CAMT.052-Dateien als XML oder ZIP importieren"
              >
                <Upload size={16} />
                {bankCamtUploadLoading ? "CAMT wird geprueft" : "CAMT-Luecke importieren"}
                <input
                  type="file"
                  accept=".xml,.zip,application/xml,text/xml,application/zip"
                  multiple
                  disabled={bankCamtUploadLoading}
                  onChange={(event) => {
                    const files = Array.from(event.currentTarget.files ?? []);
                    event.currentTarget.value = "";
                    onUploadBankCamtDocuments(files);
                  }}
                />
              </label>
              <button
                type="button"
                onClick={() => onDownload("/api/v1/divorce/sparkasse-statements.csv")}
                disabled={(sparkasseStatementConnector?.document_files_count ?? 0) === 0}
                title="Datensparsamen PDF-zu-CAMT-Abgleich als CSV herunterladen"
              >
                <FileDown size={16} />
                PDF-Belegabgleich
              </button>
            </div>
          </div>
          <div className="valuationGateItem">
            <div className="panelToolbar">
              <strong>Trade-Republic-Anbindung</strong>
              <span className={`statusPill ${tradeRepublicStatusTone}`}>{tradeRepublicStatusLabel}</span>
            </div>
            <div className="evidenceFactGrid">
              <div><span>Dateien</span><strong>{tradeRepublicConnector?.document_files_count ?? 0}</strong></div>
              <div><span>Geparst</span><strong>{tradeRepublicConnector?.parsed_documents_count ?? 0}</strong></div>
              <div><span>Exakter Stichtag</span><strong>{tradeRepublicConnector?.exact_date_documents_count ?? 0}</strong></div>
              <div>
                <span>Stichtagswert</span>
                <strong>
                  {tradeRepublicConnector?.accepted_end_asset_value_eur != null
                    ? `${formatCurrency(tradeRepublicConnector.accepted_end_asset_value_eur)} EUR`
                    : tradeRepublicConnector?.candidate_end_asset_value_eur != null
                      ? `${formatCurrency(tradeRepublicConnector.candidate_end_asset_value_eur)} EUR`
                      : "Beleg fehlt"}
                </strong>
              </div>
            </div>
            <p>{tradeRepublicConnector?.note ?? "Connectorstatus wird geladen."}</p>
            <div className="reportActionBand compactActions evidenceActions">
              <label
                className={`fileActionButton ${tradeRepublicDocumentUploadLoading ? "disabled" : ""}`}
                title="Offizielle Trade-Republic-PDF-, CSV- oder ZIP-Dokumente importieren"
              >
                <Upload size={16} />
                {tradeRepublicDocumentUploadLoading ? "Dokumente werden geprueft" : "Dokumente importieren"}
                <input
                  type="file"
                  accept=".pdf,.csv,.zip,application/pdf,text/csv,application/zip"
                  multiple
                  disabled={tradeRepublicDocumentUploadLoading}
                  onChange={(event) => {
                    const files = Array.from(event.currentTarget.files ?? []);
                    event.currentTarget.value = "";
                    onUploadTradeRepublicDocuments(files);
                  }}
                />
              </label>
              <button
                type="button"
                onClick={() => onDownload(`/api/v1/divorce/trade-republic/documents.csv?end_asset_date=${encodeURIComponent(valuationDate)}`)}
                disabled={(tradeRepublicConnector?.document_files_count ?? 0) === 0}
                title="Datensparsamen Dokumentnachweis als CSV herunterladen"
              >
                <FileDown size={16} />
                Dokumentnachweis
              </button>
              <button
                type="button"
                disabled={!tradeRepublicConnector?.valuation_review_ready || !tradeRepublicConnector?.candidate_document_sha256 || tradeRepublicValuationLoading}
                onClick={() => {
                  const documentSha256 = String(tradeRepublicConnector?.candidate_document_sha256 ?? "");
                  const value = formatCurrency(tradeRepublicConnector?.candidate_end_asset_value_eur);
                  if (documentSha256 && window.confirm(`Trade-Republic-Stichtagswert ${value} EUR nach Abgleich mit dem Originalbeleg freigeben?`)) {
                    onAcceptTradeRepublicValuation(documentSha256);
                  }
                }}
                title="Erst nach Abgleich mit dem Originalbeleg als Stichtagswert freigeben"
              >
                <Check size={16} />
                {tradeRepublicValuationLoading ? "Wird geprueft" : "Stichtagswert freigeben"}
              </button>
            </div>
          </div>
          <div className="valuationGateItem">
            <div className="panelToolbar">
              <strong>Formaler Erbnachweis</strong>
              <span className={`statusPill ${inheritanceDocumentTone}`}>{inheritanceDocumentLabel}</span>
            </div>
            <div className="evidenceFactGrid">
              <div><span>Dokumente</span><strong>{inheritanceDocumentConnector?.document_files_count ?? 0}</strong></div>
              <div><span>Review</span><strong>{inheritanceDocumentConnector?.status ?? "missing"}</strong></div>
              <div>
                <span>Belegbindung</span>
                <strong>{inheritanceDocumentConnector?.accepted_document_sha256
                  ? shortAccount(inheritanceDocumentConnector.accepted_document_sha256)
                  : "offen"}</strong>
              </div>
            </div>
            <p>{inheritanceDocumentConnector?.note ?? "Erbnachweisstatus wird geladen."}</p>
            <div className="reportActionBand compactActions evidenceActions">
              <label
                className={`fileActionButton ${inheritanceDocumentUploadLoading ? "disabled" : ""}`}
                title="Formalen Erbnachweis als PDF, JPEG oder PNG lokal hinterlegen"
              >
                <Upload size={16} />
                {inheritanceDocumentUploadLoading ? "Dokument wird geprueft" : "Erbnachweis importieren"}
                <input
                  type="file"
                  accept=".pdf,.jpg,.jpeg,.png,application/pdf,image/jpeg,image/png"
                  multiple
                  disabled={inheritanceDocumentUploadLoading}
                  onChange={(event) => {
                    const files = Array.from(event.currentTarget.files ?? []);
                    event.currentTarget.value = "";
                    onUploadInheritanceDocuments(files);
                  }}
                />
              </label>
              <button
                type="button"
                onClick={() => onDownload("/api/v1/divorce/inheritance-documents.csv")}
                disabled={(inheritanceDocumentConnector?.document_files_count ?? 0) === 0}
                title="Datensparsamen SHA-256-Nachweis als CSV herunterladen"
              >
                <FileDown size={16} />
                Dokumentnachweis
              </button>
              <button
                type="button"
                disabled={!inheritanceDocumentCandidate || inheritanceDocumentReviewLoading}
                onClick={() => {
                  const documentSha256 = inheritanceDocumentCandidate?.document_sha256 ?? "";
                  if (
                    documentSha256
                    && window.confirm(
                      "Original geprueft: Ist dieses Dokument tatsaechlich ein Erbschein, Testament/Erbvertrag oder eine belastbare Nachlassabrechnung?"
                    )
                  ) {
                    onAcceptInheritanceDocument(documentSha256);
                  }
                }}
                title="Nur nach Sichtpruefung des Originaldokuments als formalen Erbnachweis freigeben"
              >
                <Check size={16} />
                {inheritanceDocumentReviewLoading ? "Wird gebunden" : "Nach Sichtpruefung freigeben"}
              </button>
            </div>
          </div>
          <div className="valuationGateItem">
            <div className="panelToolbar">
              <strong>Coinbase-Anbindung</strong>
              <span className={`statusPill ${coinbaseStatusTone}`}>{coinbaseStatusLabel}</span>
            </div>
            <div className="evidenceFactGrid">
              <div>
                <span>CDP-Zugang</span>
                <strong>{coinbaseConnector?.credential_status === "configured" ? "eingerichtet" : "fehlt"}</strong>
              </div>
              <div>
                <span>Live-Bestand</span>
                <strong>{coinbaseConnector?.latest_live_snapshot_at
                  ? `${coinbaseConnector.latest_live_assets_count} Assets · ${formatDateTime(coinbaseConnector.latest_live_snapshot_at)}`
                  : "noch nicht abgerufen"}</strong>
              </div>
              <div>
                <span>Historie</span>
                <strong>{coinbaseConnector?.history_events_count ?? 0} Events in {coinbaseConnector?.history_batches_count ?? 0} Importen</strong>
              </div>
              <div>
                <span>Historienzeitraum</span>
                <strong>{coinbaseConnector?.history_from
                  ? `${formatDate(coinbaseConnector.history_from)} bis ${formatDate(coinbaseConnector.history_to)}`
                  : "fehlt"}</strong>
              </div>
              <div>
                <span>Stichtagswert</span>
                <strong>{coinbaseConnector?.accepted_end_asset_value_eur != null
                  ? `${formatCurrency(coinbaseConnector.accepted_end_asset_value_eur)} EUR`
                  : coinbaseConnector?.candidate_end_asset_value_eur != null
                    ? `${formatCurrency(coinbaseConnector.candidate_end_asset_value_eur)} EUR (Pruefung)`
                    : "nicht berechenbar"}</strong>
              </div>
              <div>
                <span>Preis-/Mengen-Gates</span>
                <strong>{(coinbaseConnector?.missing_price_assets.length ?? 0) === 0
                  && (coinbaseConnector?.negative_quantity_assets.length ?? 0) === 0
                  ? "ohne Befund"
                  : `${coinbaseConnector?.missing_price_assets.length ?? 0} Preise · ${coinbaseConnector?.negative_quantity_assets.length ?? 0} negative Mengen`}</strong>
              </div>
            </div>
            <p>{coinbaseConnector?.note ?? "Connectorstatus wird geladen."}</p>
            <div className="reportActionBand compactActions evidenceActions">
              <button type="button" onClick={() => onNavigate("admin")} title="Coinbase-CDP-Zugang lokal im V2 Secret Store einrichten">
                <Settings size={16} />
                CDP-Zugang
              </button>
              <button type="button" onClick={() => onNavigate("import")} title="Offizielle Coinbase Transaction History importieren">
                <Upload size={16} />
                Historie importieren
              </button>
              <button
                type="button"
                onClick={() => onDownload(`/api/v1/divorce/coinbase/connector.csv?end_asset_date=${encodeURIComponent(valuationDate)}`)}
                disabled={(coinbaseConnector?.history_events_count ?? 0) === 0}
                title="Hashgebundenen Coinbase-Historien- und Stichtagsnachweis herunterladen"
              >
                <FileDown size={16} />
                Nachweis CSV
              </button>
              <button
                type="button"
                onClick={() => window.open(coinbaseConnector?.official_statements_help_url, "_blank", "noopener,noreferrer")}
                disabled={!coinbaseConnector?.official_statements_help_url}
                title="Offizielle Coinbase-Hilfe fuer Berichte und Transaction History oeffnen"
              >
                <ExternalLink size={16} />
                Coinbase-Hilfe
              </button>
              <button
                type="button"
                disabled={!coinbaseConnector?.valuation_review_ready || !coinbaseConnector?.history_manifest_sha256 || coinbaseValuationLoading}
                onClick={() => {
                  const historyManifestSha256 = String(coinbaseConnector?.history_manifest_sha256 ?? "");
                  const value = formatCurrency(coinbaseConnector?.candidate_end_asset_value_eur);
                  if (
                    historyManifestSha256
                    && window.confirm(
                      `Coinbase-Stichtagswert ${value} EUR freigeben? Damit bestaetigst du, dass die offizielle Historie ab Kontoeroeffnung vollstaendig ist und Mengen sowie Preise geprueft wurden.`
                    )
                  ) {
                    onAcceptCoinbaseValuation(historyManifestSha256);
                  }
                }}
                title="Nur nach Vollstaendigkeits-, Mengen- und Preispruefung hashgebunden freigeben"
              >
                <Check size={16} />
                {coinbaseValuationLoading ? "Wird gebunden" : "Stichtagswert freigeben"}
              </button>
            </div>
          </div>
          <div className="valuationGateItem">
            <div className="panelToolbar"><strong>Noch erforderlich</strong></div>
            {(inheritanceOrigin?.next_actions ?? []).map((item) => <p key={item}>{item}</p>)}
          </div>
        </div>
        {tradeRepublicDocuments.length > 0 ? (
          <TablePanel
            title="Trade-Republic-Dokumentpruefung"
            rows={tradeRepublicDocuments.map((item) => ({
              typ: item.document_type,
              parser: item.extraction_status,
              stichtag: item.statement_date ? formatDate(item.statement_date) : "-",
              datumsbeleg: item.end_asset_date_match_source,
              cash_eur: item.cash_value_eur == null ? "-" : formatCurrency(item.cash_value_eur),
              depot_eur: item.securities_value_eur == null ? "-" : formatCurrency(item.securities_value_eur),
              gesamt_eur: item.total_value_eur == null ? "-" : formatCurrency(item.total_value_eur),
              beleg: shortAccount(item.document_sha256),
              beleg_full: item.document_sha256
            }))}
            footer="Dateinamen und Rohinhalte werden nicht ausgegeben. Der vollstaendige SHA-256 steht im Zellenhinweis und im CSV-Beleg."
            compact
          />
        ) : null}
        {inheritanceDocuments.length > 0 ? (
          <TablePanel
            title="Erbnachweis-Dokumentpruefung"
            rows={inheritanceDocuments.map((item) => ({
              medientyp: item.media_type,
              groesse_kib: (item.size_bytes / 1024).toFixed(1),
              quelle: item.source_kind,
              review: item.review_status,
              beleg: shortAccount(item.document_sha256),
              beleg_full: item.document_sha256
            }))}
            footer="Dateinamen und Rohdokumente werden nicht ausgegeben. Die Freigabe bestaetigt nur die Sichtpruefung und bindet den Nachweis an SHA-256."
            compact
          />
        ) : null}
        {(coinbaseConnector?.assets.length ?? 0) > 0 ? (
          <TablePanel
            title={`Coinbase-Bestand zum ${valuationLabel}`}
            rows={(coinbaseConnector?.assets ?? []).map((item) => ({
              asset: item.asset,
              menge: formatAmount(item.quantity),
              wert_eur: item.value_eur == null ? "Preis fehlt" : formatCurrency(item.value_eur),
              preisquelle: item.price_source ?? "-",
              preiszeitpunkt: formatDateTime(item.priced_at)
            }))}
            footer="Der Bestand wird aus der importierten Coinbase-Historie rekonstruiert. Eine Freigabe bindet Historienmanifest, Mengen, Preise und EUR-Stichtagswert gemeinsam."
            compact
          />
        ) : null}
        <div className="valuationGateFindings">
          {(inheritanceOrigin?.findings ?? []).map((finding) => <span key={finding}>{finding}</span>)}
        </div>
        <p className="reportYearSummary">{inheritanceOrigin?.methodology ?? "Erbgeldspur wird geladen."}</p>
      </section>

      <section className="valuationGateBand">
        <div className="valuationGateHeader">
          <div>
            <span className="heroKicker">Kapitalbewegungen</span>
            <h3>Vermoegensfluss-Gate</h3>
          </div>
          <div className="reportActionBand compactActions">
            <span className={`statusPill ${capitalFlow?.strict_ready ? "ok" : capitalFlow?.status === "blocked" ? "blocked" : "warning"}`}>
              {capitalFlow?.strict_ready ? "belegt" : capitalFlow?.status === "blocked" ? "Nachweise offen" : "Herkunft offen"}
            </span>
            <button type="button" onClick={() => onDownload(`/api/v1/divorce/equalization-summary/capital-flows.csv${exportQuery}`)}>
              <FileDown size={16} />
              Flussbeleg CSV
            </button>
            {serviceRouteTxId ? (
              <button
                type="button"
                onClick={() => onRefreshServiceRouteEvidence(serviceRouteTxId)}
                disabled={serviceRouteEvidenceLoading}
                title="Signer, Collateral, Positionskonto und spaetere Liquidation per Solana RPC pruefen"
              >
                <RefreshCcw size={16} />
                {serviceRouteEvidenceLoading ? "On-chain-Pruefung laeuft" : "Servicepfad pruefen"}
              </button>
            ) : null}
            {serviceRouteCandidate && serviceRouteEvidenceMatches && serviceRouteEvidence?.strict_ready ? (
              <button
                type="button"
                disabled={serviceRouteEvidenceLoading}
                onClick={() => {
                  if (
                    window.confirm(
                      "On-chain-Beleg geprueft: Soll dieser Jupiter-Perps-Abfluss als vor dem Endstichtag vollstaendig liquidierte Serviceposition dokumentiert werden? Steuer-FIFO und Steuerklassifikation bleiben unveraendert."
                    )
                  ) {
                    onAcceptServiceRouteEvidence(
                      serviceRouteEvidence.tx_id,
                      serviceRouteEvidence.semantic_sha256
                    );
                  }
                }}
                title="Nur den familienrechtlichen Vermoegensfluss SHA-256-gebunden freigeben"
              >
                <Check size={16} />
                Liquidationspfad freigeben
              </button>
            ) : null}
          </div>
        </div>
        <div className="valuationGateMetrics">
          <Metric title="Vermoegen bei Trennung" value={`${formatCurrency(capitalFlow?.opening_value_eur)} EUR`} />
          <Metric title="Endvermoegen" value={`${formatCurrency(capitalFlow?.closing_value_eur)} EUR`} />
          <Metric title="Kapitalzufluesse" value={`${formatCurrency(capitalFlow?.total_contributions_eur)} EUR`} />
          <Metric title="Bestaetigte externe Auszahlungen" value={`${formatCurrency(capitalFlow?.confirmed_external_distributions_eur)} EUR`} />
          <Metric title="Vorlaeufig flussbereinigt" value={`${formatCurrency(capitalFlow?.flow_adjusted_change_eur)} EUR`} />
          <Metric
            title="Szenario: bewertete Reviews extern"
            value={capitalFlow?.flow_adjusted_change_if_all_review_outflows_are_external_eur == null
              ? "nicht berechenbar"
              : `${formatCurrency(capitalFlow?.flow_adjusted_change_if_all_review_outflows_are_external_eur)} EUR`}
          />
          <Metric title="Internes Transfer-Volumen" value={`${formatCurrency(capitalFlow?.internal_transfer_value_eur)} EUR`} />
          <Metric title="Belegter Servicepositionsverlust" value={`${formatCurrency(capitalFlow?.internal_service_position_loss_value_eur)} EUR`} />
          <Metric title="Materielle Reviews" value={String(capitalFlow?.material_review_outflows_count ?? 0)} />
        </div>
        <div className="valuationGateFindings">
          {(capitalFlow?.findings ?? []).map((finding) => <span key={finding}>{finding}</span>)}
        </div>
        {serviceRouteEvidenceMatches && serviceRouteEvidence ? (
          <div className="valuationGateItem serviceRouteEvidence">
            <div className="panelToolbar">
              <strong>Jupiter-Perps-On-chain-Beleg</strong>
              <span className={`statusPill ${serviceRouteEvidence.strict_ready ? "ok" : serviceRouteEvidence.status === "failed" ? "blocked" : "warning"}`}>
                {acceptedServiceRoute
                  ? "im Vermoegensfluss belegt"
                  : serviceRouteEvidence.strict_ready
                    ? "freigabebereit"
                    : "Pruefung offen"}
              </span>
            </div>
            <div className="evidenceFactGrid">
              <div>
                <span>Eigene Wallet</span>
                <strong title={serviceRouteEvidence.wallet ?? ""}>{shortAccount(serviceRouteEvidence.wallet ?? "-")}</strong>
              </div>
              <div>
                <span>Collateral</span>
                <strong>{formatAmount(serviceRouteEvidence.collateral_quantity)} SOL</strong>
              </div>
              <div>
                <span>Positionskonto</span>
                <strong title={serviceRouteEvidence.position_account ?? ""}>{shortAccount(serviceRouteEvidence.position_account ?? "-")}</strong>
              </div>
              <div>
                <span>Liquidation</span>
                <strong>{formatDateTime(serviceRouteEvidence.liquidation_block_time)}</strong>
              </div>
              <div>
                <span>On-chain-Nettoverlust</span>
                <strong>{formatAmount(serviceRouteEvidence.liquidation_net_loss_usd)} USD</strong>
              </div>
              <div>
                <span>Rest-Rent am Stichtag</span>
                <strong>{formatCurrency(serviceRouteEvidence.residual_position_account_value_eur)} EUR</strong>
              </div>
            </div>
            <div className="valuationGateFindings">
              {serviceRouteEvidence.findings.map((finding) => <span key={finding}>{finding}</span>)}
            </div>
            <div className="reportActionBand compactActions evidenceActions">
              {serviceRouteEvidence.evidence_files.map((item) => {
                const filename = item.path.split("/").pop() ?? "";
                return (
                  <button
                    type="button"
                    key={item.sha256}
                    onClick={() => onDownload(`/api/v1/divorce/service-route-evidence/${encodeURIComponent(serviceRouteEvidence.tx_id)}/artifacts/${encodeURIComponent(filename)}`)}
                    title={`SHA-256 ${item.sha256}`}
                  >
                    <FileDown size={16} />
                    {item.kind === "opening_get_transaction"
                      ? "Positionsaufbau"
                      : item.kind === "position_signatures"
                        ? "Lebenszyklus"
                        : "Liquidation"}
                  </button>
                );
              })}
            </div>
            <p className="reportYearSummary">SHA-256: {serviceRouteEvidence.semantic_sha256}</p>
          </div>
        ) : null}
        <TablePanel
          title="Kapitalzufluesse und Mittelherkunft"
          rows={(capitalFlow?.contributions ?? []).filter((row) => Number(row.amount_eur ?? 0) !== 0).map((row) => ({
            zuflussgruppe: row.label,
            betrag: `${formatCurrency(row.amount_eur)} EUR`,
            transaktionsbeleg: row.transaction_evidence_status,
            mittelherkunft: equalizationCapitalOriginLabel(String(row.capital_origin ?? "unclassified")),
            herkunftsbeleg: row.capital_origin_evidence_status,
            beleg: row.evidence_ref ?? "-",
            hinweis: row.note
          }))}
          footer="Eine Behauptung wie Erbgeld wird erst nach referenziertem Zahlungs- und Herkunftsbeleg als dokumentiert behandelt."
          compact
        />
        <TablePanel
          title="Abfluss- und Service-Pruefung"
          rows={capitalOutflows.map((row) => ({
            zeitpunkt: formatDateTime(row.event_time),
            quelle: row.source,
            konto: shortAccount(String(row.account ?? "")),
            konto_voll: String(row.account ?? ""),
            asset: row.asset,
            menge: formatAmount(row.quantity),
            wert: row.value_eur === null || row.value_eur === undefined ? "nicht bewertet" : `${formatCurrency(row.value_eur)} EUR`,
            einordnung: equalizationCapitalFlowClassificationLabel(String(row.classification ?? "")),
            belegstatus: row.evidence_status,
            tx: row.tx_id ? shortAccount(String(row.tx_id)) : "-",
            tx_voll: row.tx_id ?? "",
            hinweis: row.note
          }))}
          footer="Interne Transfers, CEX-Produktumbuchungen und Gebuehren werden nicht als Entnahmen gerechnet. Nur bestaetigte externe Auszahlungen veraendern die Flussrechnung."
          compact
        />
        <p className="reportYearSummary">{capitalFlow?.methodology ?? "Vermoegensfluss wird geladen."}</p>
      </section>

      <section className="valuationGateBand">
        <div className="valuationGateHeader">
          <div>
            <span className="heroKicker">Nachweisstatus</span>
            <h3>Preis- und FIFO-Gates</h3>
          </div>
          <span className={`statusPill ${valuationRun?.strict_ready ? "ok" : valuationRun?.status === "blocked" ? "blocked" : "warning"}`}>
            {valuationRun?.strict_ready ? "stichtagsfest" : valuationRun?.status === "blocked" ? "Belege offen" : "fachliche Abnahme offen"}
          </span>
        </div>
        <div className="valuationGateGrid">
          {[report?.cutoff_price_gate, report?.valuation_price_gate].map((gate, index) => (
            <div className="valuationGateItem" key={index === 0 ? "cutoff-price-gate" : "valuation-price-gate"}>
              <div className="panelToolbar">
                <strong>{index === 0 ? `Trennungspreise ${cutoffLabel}` : `Endvermoegenspreise ${valuationLabel}`}</strong>
                <span className={`statusPill ${gate?.strict_ready ? "ok" : "blocked"}`}>{gate?.strict_ready ? "vollstaendig" : "offen"}</span>
              </div>
              <div className="valuationGateMetrics">
                <Metric title="Same Day" value={String(gate?.same_day_price_count ?? 0)} />
                <Metric title="Vortag" value={String(gate?.prior_day_price_count ?? 0)} />
                <Metric title="veraltet" value={String(gate?.stale_price_count ?? 0)} />
                <Metric title="ohne Preis" value={String(gate?.missing_price_count ?? 0)} />
              </div>
              <p>{(gate?.findings ?? []).join(" ") || "Preis-Gate wird geladen."}</p>
              {(gate?.affected_assets ?? []).length > 0 ? <span>Betroffen: {(gate?.affected_assets ?? []).join(", ")}</span> : null}
            </div>
          ))}
          <div className="valuationGateItem">
            <div className="panelToolbar">
              <strong>Quellen und Mengen</strong>
              <span className={`statusPill ${valuationRun?.source_registry_strict_ready ? "ok" : "blocked"}`}>
                {valuationRun?.source_registry_strict_ready ? "vollstaendig" : "offen"}
              </span>
            </div>
            <div className="valuationGateMetrics">
              <Metric title="Registry" value={valuationRun?.source_registry_status ?? "fehlt"} />
              <Metric title="Konten" value={String(valuationRun?.source_accounts?.length ?? 0)} />
              <Metric title="Provider-Grenzen" value={String(valuationRun?.source_provider_coverage_gap_count ?? 0)} />
              <Metric title="Eigene Belege offen" value={String(valuationRun?.source_user_evidence_gap_count ?? 0)} />
              <Metric title="Mengendifferenzen" value={String(valuationRun?.source_quantity_blocker_count ?? 0)} />
            </div>
            <p>
              Historische Ledger-Mengen werden gegen registrierte Eigentumsrollen und aktuelle Live-Anker geprueft.
              Provider-Grenzen verlangen keine erneute Lieferung bereits vorhandener Exporte; eigene Belegpflichten stehen separat.
            </p>
            {valuationRun?.source_registry_semantic_sha256 ? <span>SHA-256: {valuationRun.source_registry_semantic_sha256}</span> : null}
          </div>
        </div>
        <div className="valuationGateFindings">
          {(valuationRun?.findings ?? []).map((finding) => <span key={finding}>{finding}</span>)}
        </div>
      </section>

      <TablePanel
        title="Versionierte FIFO-Stichtage"
        rows={(valuationRun?.fifo_checkpoints ?? []).map((checkpoint) => ({
          stichtag: checkpoint.label === "cutoff" ? "Trennung" : "Endvermoegen",
          zeitpunkt_utc: formatDateTime(checkpoint.as_of),
          laufbasis: checkpoint.reused_existing_run === true ? "Fingerprint-Lauf wiederverwendet" : "neu berechnet",
          status: String(checkpoint.status ?? ""),
          jahre: Array.isArray(checkpoint.years) ? checkpoint.years.join(", ") : "",
          mengenabweichung_jahre: Array.isArray(checkpoint.event_set_mismatch_years) ? checkpoint.event_set_mismatch_years.join(", ") || "keine" : "-",
          bewertungsreview_jahre: Array.isArray(checkpoint.valuation_review_years) ? checkpoint.valuation_review_years.join(", ") || "keine" : "-",
          provider_basis_offen: checkpoint.unmatched_classification_complete === true ? checkpoint.provider_basis_gap_count ?? 0 : "noch nicht klassifiziert",
          wirklich_ungeklaert: checkpoint.unmatched_classification_complete === true ? checkpoint.unexplained_unmatched_count ?? 0 : checkpoint.unmatched_count,
          provider_event_gaps: checkpoint.method_gap_classification_complete === true ? checkpoint.provider_basis_event_set_gap_groups_count ?? 0 : "noch nicht klassifiziert",
          provider_mengen_gaps: checkpoint.method_gap_classification_complete === true ? checkpoint.provider_basis_quantity_gap_groups_count ?? 0 : "noch nicht klassifiziert",
          methodisch_ungeklaert: checkpoint.method_gap_classification_complete === true ? checkpoint.unexplained_method_gap_groups_count ?? 0 : "noch nicht klassifiziert",
          offene_herkunft: checkpoint.unresolved_inbound_provenance_count,
          kaufbeleg_review: checkpoint.acquisition_cost_evidence_review_count,
          run_id: checkpoint.run_id
        }))}
        footer={valuationRun ? `Lauf ${valuationRun.run_id} · SHA-256 ${valuationRun.semantic_sha256}` : "Noch kein versionierter Dossierlauf vorhanden."}
        compact
      />

      <section className="priceGateActionBand">
        <div>
          <span className="heroKicker">Historische Kurse</span>
          <h3>
            {priceGateMode === "cutoff" ? "Trennungspreise" : "Endvermoegenspreise"}{" "}
            {priceGateMode === "cutoff" ? cutoffLabel : valuationLabel}
          </h3>
          <p>{activePriceGate?.methodology ?? "Preis-Gate wird geladen."}</p>
        </div>
        <div className="modeSelector" role="tablist" aria-label="Preisstichtag">
          <button
            type="button"
            role="tab"
            aria-selected={priceGateMode === "cutoff"}
            className={priceGateMode === "cutoff" ? "active" : ""}
            onClick={() => setPriceGateMode("cutoff")}
          >
            Trennung
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={priceGateMode === "valuation"}
            className={priceGateMode === "valuation" ? "active" : ""}
            onClick={() => setPriceGateMode("valuation")}
          >
            Endvermoegen
          </button>
        </div>
        <div className="priceGateActionMetrics">
          <Metric title="materielle Assets" value={String(activePriceGate?.material_assets_count ?? 0)} />
          <Metric title="fetchable" value={String(activePriceGate?.fetchable_count ?? 0)} />
          <Metric title="Tokenreview offen" value={String(activePriceGate?.review_only_count ?? 0)} />
          <Metric title="Tokenreview belegt" value={String(activePriceGate?.gate.accepted_review_asset_count ?? 0)} />
          <Metric title="nicht konfiguriert" value={String(activePriceGate?.not_configured_count ?? 0)} />
        </div>
        <div className="toolbarActions">
          <button type="button" onClick={() => onRunPriceGateBackfill(true, activePriceGateDate)} disabled={priceGateLoading || !activePriceGate?.fetchable_count}>
            <ClipboardCheck size={16} />
            {priceGateLoading ? "Preis-Lauf aktiv" : "Backfill pruefen"}
          </button>
          <button type="button" onClick={() => onRunPriceGateBackfill(false, activePriceGateDate)} disabled={priceGateLoading || !activePriceGate?.fetchable_count}>
            <Database size={16} />
            Belegte Preise importieren
          </button>
          <button
            type="button"
            onClick={() => onDownload(`/api/v1/prices/as-of-gate/token-review-decisions.csv?separation_date=${encodeURIComponent(cutoffDate)}&end_asset_date=${encodeURIComponent(valuationDate)}`)}
          >
            <FileDown size={16} />
            Tokenentscheide CSV
          </button>
        </div>
      </section>
      <TablePanel
        title={`Preisbedarf am ${priceGateMode === "cutoff" ? "Trennungsstichtag" : "Endvermoegensstichtag"}`}
        rows={(activePriceGate?.candidates ?? []).filter((candidate) => candidate.status !== "satisfied").map((candidate) => ({
          asset: candidate.asset,
          konten: Array.isArray(candidate.accounts) ? candidate.accounts.map(String).map(shortAccount).join(" | ") : "",
          wert: `${formatCurrency(candidate.value_eur)} EUR`,
          bisheriger_preisstand: candidate.current_priced_at ? formatDateTime(candidate.current_priced_at) : "fehlt",
          preisalter_tage: candidate.current_price_age_days ?? "-",
          preisstatus: equalizationPriceStatusLabel(String(candidate.current_price_status ?? "missing")),
          provider: candidate.provider_id ?? "-",
          tokenreview: candidate.token_review_status,
          aktion: candidate.status,
          grund: candidate.reason
        }))}
        footer="Der Import schreibt ausschliesslich belegte Price-Ledger-Punkte. Eine Tokenentscheidung gilt nur fuer den ausgewaehlten Stichtag und veraendert weder FIFO noch Steuerdaten."
        compact
      />
      <TablePanel
        title="Freigabebereite Tokenbewertungen"
        rows={(activePriceGate?.candidates ?? [])
          .filter((candidate) => candidate.token_review_status === "pending" && candidate.current_price_status === "same_day")
          .map((candidate) => ({
            asset: candidate.asset,
            mint: candidate.token_mint ?? "-",
            risiko: candidate.token_risk_status ?? "-",
            wert: `${formatCurrency(candidate.value_eur)} EUR`,
            preis: `${formatCurrency(candidate.current_price_eur)} EUR`,
            preisquelle: candidate.current_price_source ?? "-",
            stichtag: activePriceGateDate
          }))}
        rowActions={[
          {
            label: "Same-Day-Bewertung beleggebunden annehmen",
            icon: <ClipboardCheck size={16} />,
            onClick: (row) => onAcceptTokenValuation(String(row.asset ?? ""), activePriceGateDate)
          }
        ]}
        footer="Die Annahme bestaetigt nur Mint und Same-Day-Preis fuer diesen Stichtag. Bestand, Ledger, FIFO, Steuerzeilen und Tokenmenge bleiben unveraendert."
        compact
      />

      <div className="equalizationGrid">
        <EqualizationSummaryCard title="Technische FIFO-Kontrollsicht Alt-Lots" bucket={marital} tone="neutral" />
        <EqualizationSummaryCard title="Erbgeld-/EUR-Spur ab Stichtag" bucket={direct} tone="focus" />
        <EqualizationSummaryCard title="Alle Lots ab Stichtag" bucket={allLots} tone="wide" />
      </div>

      <div className="panel">
        <div className="panelToolbar">
          <strong>BMF-Abgrenzung zur Steuererklaerung</strong>
          <div className="reportActionBand compactActions">
            <button type="button" onClick={() => onDownload(`/api/v1/divorce/equalization-summary/evidence-package.zip${exportQuery}`)}>
              <FileDown size={16} />
              Belegpaket ZIP
            </button>
            <button type="button" onClick={() => onNavigate("tax")}>
              <ReceiptText size={16} />
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
          <button type="button" onClick={() => onDownload(`/api/v1/divorce/equalization-summary/accounts.csv${exportQuery}`)}>
            <FileDown size={16} />
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
            wert_ausgang: `${formatCurrency(account.cutoff_value_eur)} EUR`,
            wert_bewertung: `${formatCurrency(account.valuation_value_eur)} EUR`,
            wert_ohne_review_token: `${formatCurrency(account.valuation_value_without_review_assets_eur)} EUR`,
            review_token_wert: `${formatCurrency(account.valuation_review_value_eur)} EUR`,
            veraenderung: `${formatCurrency(account.gross_change_eur)} EUR`,
            externe_einzahlung: `${formatCurrency(account.external_invest_since_cutoff_eur)} EUR`,
            bereinigte_veraenderung: `${formatCurrency(account.adjusted_gain_loss_eur)} EUR`,
            quellkonten: Array.isArray(account.source_accounts) ? account.source_accounts.join(" | ") : "",
            assets_ausgang: Array.isArray(account.asset_labels_cutoff) ? account.asset_labels_cutoff.join(", ") : "",
            assets_bewertung: Array.isArray(account.asset_labels_valuation) ? account.asset_labels_valuation.join(", ") : "",
            token_details_bewertung: equalizationAccountAssetSummary(account.valuation_assets),
            hinweis: String(account.note ?? "")
          }))}
          footer="Wallet-Adressen werden links gekuerzt angezeigt; konto_voll enthaelt die vollstaendige Adresse fuer Belege und Drilldown."
        />
      </div>

      <div className="panel">
        <div className="panelToolbar">
          <strong>Token je Wallet zum Bewertungsstand</strong>
          <button type="button" onClick={() => onDownload(`/api/v1/divorce/equalization-summary/valuation-tokens.csv${exportQuery}`)}>
            <FileDown size={16} />
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
          <button type="button" onClick={() => onDownload(`/api/v1/divorce/equalization-summary/live-reconciliation.csv${exportQuery}`)}>
            <FileDown size={16} />
            CSV herunterladen
          </button>
        </div>
        <TablePanel
          title="Reconciliation fuer relevante Wallets und Quellen"
          rows={(report?.live_reconciliation ?? []).map((row) => ({
            quelle: row.source_group,
            asset: row.asset ?? "-",
            rohledger_menge: row.raw_ledger_quantity === null || row.raw_ledger_quantity === undefined
              ? row.ledger_quantity === null || row.ledger_quantity === undefined ? "-" : formatAmount(row.ledger_quantity)
              : formatAmount(row.raw_ledger_quantity),
            beleg_overlay: formatAmount(row.ledger_adjustment_quantity ?? 0),
            abgleich_menge: row.ledger_quantity === null || row.ledger_quantity === undefined ? "-" : formatAmount(row.ledger_quantity),
            live_menge: row.external_quantity === null || row.external_quantity === undefined ? "-" : formatAmount(row.external_quantity),
            delta_wert: row.delta_value_eur === null || row.delta_value_eur === undefined ? "-" : `${formatCurrency(row.delta_value_eur)} EUR`,
            status: row.status,
            txid: Array.isArray(row.ledger_adjustment_tx_ids)
              ? row.ledger_adjustment_tx_ids.map((value) => shortAccount(String(value))).join(", ")
              : "-",
            txid_full: Array.isArray(row.ledger_adjustment_tx_ids)
              ? row.ledger_adjustment_tx_ids.join(" | ")
              : ""
          }))}
          footer="Live- und RPC-Werte sind Kontrollquellen. Beleg-Overlays schließen nur nach TxID-Prüfung fehlende Gegenposten im Abgleich; Rohledger, FIFO und Steuerdaten bleiben unverändert."
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
  if (classification === "exchange_binance") {
    return "Binance";
  }
  if (classification === "exchange_bitget") {
    return "Bitget";
  }
  if (classification === "exchange_pionex") {
    return "Pionex";
  }
  if (classification === "exchange_coinbase") {
    return "Coinbase";
  }
  return "Portfolio-Konto";
}

function equalizationCapitalOriginLabel(origin: string): string {
  if (origin === "inheritance") {
    return "Erbe belegt";
  }
  if (origin === "claimed_inheritance") {
    return "Erbe angegeben, Beleg offen";
  }
  if (origin === "marital_funds") {
    return "Eheliche Mittel";
  }
  if (origin === "other_separate_property") {
    return "Sonstiges Anfangsvermoegen";
  }
  return "Noch nicht eingeordnet";
}

function equalizationInheritanceCreditKindLabel(kind: string): string {
  if (kind === "estate_account_transfer") {
    return "Nachlasskonto-Uebertrag";
  }
  if (kind === "estate_asset_realization") {
    return "Auszahlung geerbter Vermoegenswert";
  }
  if (kind === "estate_refund") {
    return "Nachlassbezogene Erstattung";
  }
  return "Erbmittelzufluss";
}

function equalizationCapitalFlowClassificationLabel(classification: string): string {
  const labels: Record<string, string> = {
    internal_transfer_confirmed: "Interner Transfer belegt",
    internal_product_transfer: "Interne Produktumbuchung",
    internal_service_position_loss: "Serviceposition vollstaendig liquidiert",
    trade_or_service_route: "Trade-/Service-Route pruefen",
    technical_fee: "Technische Gebuehr",
    operational_adjustment_review: "Operative Korrektur pruefen",
    external_distribution_confirmed: "Externe Auszahlung belegt",
    external_distribution_review: "Moegliche externe Auszahlung pruefen"
  };
  return labels[classification] ?? classification;
}

function equalizationValuationBasisLabel(basis: string): string {
  if (basis === "historical_ledger_as_of") {
    return "Historisches Ledger zum Stichtag";
  }
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
      preisalter_tage: asset.price_age_days ?? "-",
      preisstatus: equalizationPriceStatusLabel(String(asset.price_status ?? "missing")),
      hinweis: String(asset.note ?? "")
    }));
  });
}

function equalizationPriceStatusLabel(status: string): string {
  if (status === "same_day") return "Stichtag";
  if (status === "prior_day") return "Vortag";
  if (status === "stale") return "veraltet";
  if (status === "derived_event_quote") return "abgeleitet";
  if (status === "missing") return "fehlt";
  return status;
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

type GateStatusItem = {
  label: string;
  status: string;
  tone: "ok" | "warning" | "blocked";
  detail: string;
};

function GateStatusLegend({ items }: { items: GateStatusItem[] }) {
  return (
    <section className="gateStatusLegend" aria-label="Status-Erklaerung">
      {items.map((item) => (
        <div key={item.label} className={`gateStatusItem ${item.tone}`}>
          <span className={`statusPill ${item.tone}`}>{item.status}</span>
          <div>
            <strong>{item.label}</strong>
            <p>{item.detail}</p>
          </div>
        </div>
      ))}
    </section>
  );
}

function ParityBlockerFocus({
  rows,
  onAddParityDecision,
  onDownload
}: {
  rows: Array<Record<string, unknown>>;
  onAddParityDecision: (scope: string, decisionStatus: string) => void;
  onDownload: (path: string) => void;
}) {
  if (rows.length === 0) {
    return (
      <section className="parityBlockerFocus ok">
        <div>
          <span className="heroKicker">Parity-Blocker</span>
          <h3>Keine blockierende Parity-Gruppe offen</h3>
          <p>Der Legacy-Vergleich verhindert den Export aktuell nicht.</p>
        </div>
        <span className="statusPill ok">frei</span>
      </section>
    );
  }
  const primary = rows[0];
  const scope = String(primary.scope ?? "");
  const metrics = Array.isArray(primary.metrics) ? primary.metrics.join(", ") : String(primary.metrics ?? "-");
  return (
    <section className="parityBlockerFocus blocked">
      <div className="parityBlockerHeader">
        <div>
          <span className="heroKicker">Offener Parity-Blocker</span>
          <h3>{String(primary.year ?? "-")} · {String(primary.asset ?? "-")} · {String(primary.status ?? "-")}</h3>
          <p>
            Diese Legacy-Vergleichsgruppe blockiert die Export-Readiness, obwohl das Review-Gate frei ist.
            Fachlich muss entschieden werden, ob V1 falsch war, V2 Daten fehlen, manuelle Evidenz noetig ist oder die Differenz akzeptiert wird.
          </p>
        </div>
        <span className="statusPill blocked">{rows.length} offen</span>
      </div>
      <div className="parityBlockerFacts">
        <StatusRow label="Scope" value={scope} />
        <StatusRow label="Entscheidung" value={String(primary.decision_status ?? "unreviewed")} />
        <StatusRow label="Metriken" value={metrics} />
        <StatusRow label="Issue Count" value={String(primary.issue_count ?? 0)} />
        <StatusRow label="V1 Summe" value={`${formatCurrency(primary.v1_total_eur)} EUR`} />
        <StatusRow label="V2 Summe" value={`${formatCurrency(primary.v2_total_eur)} EUR`} />
        <StatusRow label="Absolute Differenz" value={`${formatCurrency(primary.absolute_difference_eur)} EUR`} />
        <StatusRow label="Max. Differenz" value={`${formatCurrency(primary.max_absolute_difference)} EUR`} />
      </div>
      <div className="parityBlockerActions">
        <button type="button" onClick={() => onDownload(`/api/v1/parity/group-detail?scope=${encodeURIComponent(scope)}`)}>
          <FileJson size={16} />
          <span>Details JSON</span>
        </button>
        <button type="button" onClick={() => onDownload("/api/v1/export/parity-diagnostics.csv")}>
          <FileDown size={16} />
          <span>Parity CSV</span>
        </button>
        <button type="button" onClick={() => onAddParityDecision(scope, "v1_known_wrong")}>
          <Scale size={16} />
          <span>V1 falsch</span>
        </button>
        <button type="button" onClick={() => onAddParityDecision(scope, "v2_missing_data")}>
          <Database size={16} />
          <span>V2 Datenluecke</span>
        </button>
        <button type="button" onClick={() => onAddParityDecision(scope, "needs_manual_evidence")}>
          <ReceiptText size={16} />
          <span>Evidenz noetig</span>
        </button>
        <button type="button" onClick={() => onAddParityDecision(scope, "accepted_difference")}>
          <Check size={16} />
          <span>Akzeptieren</span>
        </button>
      </div>
    </section>
  );
}

function ReportFilingWorkflow({
  exportAllowed,
  activeYearsCount,
  readyYearsCount,
  reviewYearsCount,
  packagesCount,
  requiredEvidenceCount,
  warningsCount,
  evidenceStatus,
  latestPackageCreatedAt,
  parityReleaseReady,
  parityBlockingGroups,
  onDownload,
  onRunReportAction,
  onExportViewModeChange
}: {
  exportAllowed: boolean;
  activeYearsCount: number;
  readyYearsCount: number;
  reviewYearsCount: number;
  packagesCount: number;
  requiredEvidenceCount: number;
  warningsCount: number;
  evidenceStatus: string;
  latestPackageCreatedAt: string | null;
  parityReleaseReady: boolean;
  parityBlockingGroups: number;
  onDownload: (path: string) => void;
  onRunReportAction: (path: string, label: string) => void;
  onExportViewModeChange: (mode: ExportViewMode) => void;
}) {
  const gateTone = exportAllowed ? "ok" : "blocked";
  const evidenceTone = reportEvidenceTone(evidenceStatus);
  const blockedReason = !exportAllowed && !parityReleaseReady && parityBlockingGroups > 0
    ? "Parity klaeren"
    : !exportAllowed
      ? "Export-Gate klaeren"
      : "Einreichung technisch freigegeben";
  return (
    <section className="reportWorkflow">
      <div className="reportWorkflowHeader">
        <div>
          <span className="heroKicker">Abgabe-Fahrplan</span>
          <h3>{blockedReason}</h3>
          <p>Der Bereich trennt Steuererklaerungswerte, Jahresbelege, Vorjahres-/Review-Aufgaben und technische Exporte.</p>
        </div>
        <div className="reportWorkflowBadges">
          <span className={`statusPill ${gateTone}`}>{exportAllowed ? "Export frei" : "Export blockiert"}</span>
          <span className={`statusPill ${evidenceTone}`}>Belege {evidenceStatus}</span>
        </div>
      </div>
      <div className="reportWorkflowGrid">
        <div className={`reportWorkflowStep ${gateTone}`}>
          <div className="reportWorkflowStepHead">
            <ReceiptText size={18} />
            <strong>1. Steuererklaerung</strong>
          </div>
          <p>
            {readyYearsCount} von {activeYearsCount} aktiven Jahr(en) sind ohne Export-Blocker markiert.
            {!parityReleaseReady && parityBlockingGroups > 0 ? ` V1/V2-Parity blockiert noch ${parityBlockingGroups} Gruppe(n).` : ""}
          </p>
          <div className="reportWorkflowMetrics">
            <Metric title="Aktive Jahre" value={String(activeYearsCount)} />
            <Metric title="Parity-Blocker" value={String(parityBlockingGroups)} />
          </div>
          <button type="button" onClick={() => onRunReportAction("/api/v1/export/elster-prep", "ELSTER-Prep")}>
            <PackageCheck size={16} />
            <span>ELSTER-Prep erzeugen</span>
          </button>
        </div>
        <div className={`reportWorkflowStep ${evidenceTone}`}>
          <div className="reportWorkflowStepHead">
            <PackageCheck size={18} />
            <strong>2. Belege beilegen</strong>
          </div>
          <p>{requiredEvidenceCount} Pflichtbeleg(e), {packagesCount} vorhandene PDF-/Exportpaket(e).</p>
          <div className="reportWorkflowMetrics">
            <Metric title="Pflichtbelege" value={String(requiredEvidenceCount)} />
            <Metric title="Letztes Paket" value={latestPackageCreatedAt ? formatDateTime(latestPackageCreatedAt) : "-"} />
          </div>
          <button type="button" onClick={() => onDownload("/api/v1/export/evidence-package.zip")}>
            <FileDown size={16} />
            <span>Gesamt-Belegpaket</span>
          </button>
        </div>
        <div className={`reportWorkflowStep ${warningsCount > 0 || reviewYearsCount > 0 ? "warning" : "ok"}`}>
          <div className="reportWorkflowStepHead">
            <AlertTriangle size={18} />
            <strong>3. Review & Korrektur</strong>
          </div>
          <p>{warningsCount} Report-Warnung(en), {reviewYearsCount} Jahr(e) mit Review- oder Export-Hinweis.</p>
          <div className="reportWorkflowMetrics">
            <Metric title="Warnungen" value={String(warningsCount)} />
            <Metric title="Review-Jahre" value={String(reviewYearsCount)} />
          </div>
          <button type="button" onClick={() => onExportViewModeChange("evidence")}>
            <ClipboardCheck size={16} />
            <span>Belege pruefen</span>
          </button>
        </div>
        <div className="reportWorkflowStep ok">
          <div className="reportWorkflowStepHead">
            <Database size={18} />
            <strong>4. Expertenexporte</strong>
          </div>
          <p>CSV, Audit JSON, FIFO- und Integritaetsdaten bleiben verfuegbar, aber unter Expertenmodus gebuendelt.</p>
          <div className="reportWorkflowMetrics">
            <Metric title="Audit" value="JSON" />
            <Metric title="CSV/FIFO" value="Expert" />
          </div>
          <button type="button" onClick={() => onExportViewModeChange("expert")}>
            <FileJson size={16} />
            <span>Expertenmodus</span>
          </button>
        </div>
      </div>
    </section>
  );
}

function ReportCenterPanel({
  center,
  evidenceManifest,
  evidencePackageIndex,
  readiness,
  priceQuality,
  reviewDecisions,
  parityReleaseReadiness,
  exportViewMode,
  onExportViewModeChange,
  onCreatePdfExport,
  onRunReportAction,
  onAddParityDecision,
  onDownload
}: {
  center: Snapshot["reportCenter"];
  evidenceManifest: Snapshot["reportEvidenceManifest"];
  evidencePackageIndex: Snapshot["reportEvidencePackageIndex"];
  readiness: Record<string, unknown> | undefined;
  priceQuality: Snapshot["priceQuality"];
  reviewDecisions: Snapshot["reviewDecisions"];
  parityReleaseReadiness: Snapshot["parityReleaseReadiness"];
  exportViewMode: ExportViewMode;
  onExportViewModeChange: (mode: ExportViewMode) => void;
  onCreatePdfExport: (label: string, estimatedPages: string) => void;
  onRunReportAction: (path: string, label: string) => void;
  onAddParityDecision: (scope: string, decisionStatus: string) => void;
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
  const parityBlockingRows = parityReleaseReadiness?.blocking_groups_top ?? [];
  const reportReadyYears = years.filter((year) => !year.export_blocked && ["ready", "finished", "conservative_ready"].includes(String(year.filing_status ?? year.tax_state ?? "")));
  const reportReviewYears = years.filter((year) => year.export_blocked || ["review", "blocked"].includes(String(year.filing_status ?? year.package_status ?? "")));
  const reportActiveYears = years.filter((year) => Number(year.tax_lines_count ?? 0) > 0 || Number(year.rewards_mining_staking_income_eur ?? 0) !== 0);
  const requiredEvidenceCount = requiredManifestFiles.length || years.reduce((total, year) => total + Number(year.required_evidence_count ?? 0), 0);
  const reviewGateOpenIssues = Number(readiness?.review_issues_open_total ?? readiness?.review_issues_open ?? 0);
  const reviewGateBlockingIssues = Number(readiness?.review_blocking_issues_open ?? 0);
  const parityBlockingGroups = Number(readiness?.parity_blocking_groups ?? 0);
  const parityReleaseReady = readiness?.parity_release_ready === true;
  const gateStatuses: GateStatusItem[] = [
    {
      label: "Review-Gate",
      status: reviewGateBlockingIssues === 0 ? "frei" : "blockiert",
      tone: reviewGateBlockingIssues === 0 ? "ok" : "blocked",
      detail: `${reviewGateOpenIssues} offene Review-Issue(s), davon ${reviewGateBlockingIssues} blockierend. Das ist die fachliche Datenpruefung.`
    },
    {
      label: "V1/V2-Parity",
      status: parityReleaseReady ? "releasebereit" : "blockiert",
      tone: parityReleaseReady ? "ok" : "blocked",
      detail: `${parityBlockingGroups} blockierende Parity-Gruppe(n). Parity ist Teil der technischen Export-Freigabe.`
    },
    {
      label: "Export-Readiness",
      status: exportAllowed ? "freigegeben" : "blockiert",
      tone: exportAllowed ? "ok" : "blocked",
      detail: exportAllowed
        ? "Review-Gate und Parity erlauben die finale Exporterzeugung."
        : "Export bleibt blockiert, solange Review-Gate oder Parity nicht frei sind."
    },
    {
      label: "Belege",
      status: String(evidenceHealth?.status ?? "offen"),
      tone: reportEvidenceTone(String(evidenceHealth?.status ?? "offen")),
      detail: `${requiredEvidenceCount} Pflichtbeleg(e) im aktuellen Report-Center-Kontext.`
    }
  ];
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

      <GateStatusLegend items={gateStatuses} />

      <ParityBlockerFocus
        rows={parityBlockingRows}
        onAddParityDecision={onAddParityDecision}
        onDownload={onDownload}
      />

      <ReportFilingWorkflow
        exportAllowed={exportAllowed}
        activeYearsCount={reportActiveYears.length}
        readyYearsCount={reportReadyYears.length}
        reviewYearsCount={reportReviewYears.length}
        packagesCount={Number(center?.packages_count ?? 0)}
        requiredEvidenceCount={requiredEvidenceCount}
        warningsCount={warnings.length}
        evidenceStatus={String(evidenceHealth?.status ?? "offen")}
        latestPackageCreatedAt={center?.latest_package_created_at ?? null}
        parityReleaseReady={parityReleaseReady}
        parityBlockingGroups={parityBlockingGroups}
        onDownload={onDownload}
        onRunReportAction={onRunReportAction}
        onExportViewModeChange={onExportViewModeChange}
      />

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
            <Metric title="Rewards eintragen" value={`${formatCurrency(year.rewards_mining_staking_income_eur)} EUR`} />
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
              <button type="button" onClick={() => onDownload(humanReadableFilingEndpoint(String(year.filing_endpoint ?? taxYearFilingSummaryHtmlPath(year.year))))}>
                <ReceiptText size={16} />
                Eingabehilfe
              </button>
              <button type="button" onClick={() => onDownload(humanReadableTaxEndpoint(String(year.evidence_endpoint ?? `/api/v1/tax-years/${String(year.year)}/evidence`)))}>
                <FileDown size={16} />
                Belegkarte
              </button>
              <button type="button" onClick={() => onDownload(String(year.evidence_package_endpoint ?? `/api/v1/export/tax-years/${String(year.year)}/evidence-package.zip`))}>
                <PackageCheck size={16} />
                Jahrespaket
              </button>
              <button type="button" onClick={() => onDownload(String(year.wallet_fifo_endpoint ?? `/api/v1/tax-years/${String(year.year)}/wallet-fifo-delta`))}>
                <GitBranch size={16} />
                FIFO JSON
              </button>
              <button type="button" onClick={() => onDownload(String(year.wallet_fifo_gaps_endpoint ?? `/api/v1/tax-years/${String(year.year)}/wallet-fifo-gaps?limit=80`))}>
                <AlertTriangle size={16} />
                FIFO-Gaps JSON
              </button>
              {year.cex_fifo_anchor_endpoint ? (
                <button type="button" onClick={() => onDownload(String(year.cex_fifo_anchor_endpoint))}>
                  <ClipboardCheck size={16} />
                  CEX-Anker JSON
                </button>
              ) : null}
            </div>
            {Array.isArray(year.required_evidence_refs) && year.required_evidence_refs.length > 0 ? (
              <div className="reportEvidenceRefs">
                {year.required_evidence_refs.slice(0, 6).map((ref, index) => (
                  <button key={String(ref)} type="button" onClick={() => onDownload(humanReadableTaxEndpoint(String(ref)))} title={String(ref)}>
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

function BmfComplianceMatrixPanel({
  matrix,
  legalFreshness,
  run,
  methodDelta,
  methodAcceptance,
  migrationRehearsal,
  applyReadiness,
  running,
  migrationRunning,
  onRun,
  onRunMigration,
  onDownload
}: {
  matrix: Snapshot["taxBmfComplianceMatrix"];
  legalFreshness: Snapshot["legalResearchFreshness"];
  run: Snapshot["walletFifoParallelRun"];
  methodDelta: Snapshot["walletFifoMethodDeltaExplanation"];
  methodAcceptance: Snapshot["walletFifoMethodAcceptance"];
  migrationRehearsal: Snapshot["walletFifoMigrationRehearsal"];
  applyReadiness: Snapshot["walletFifoMigrationApplyReadiness"];
  running: boolean;
  migrationRunning: boolean;
  onRun: () => void;
  onRunMigration: () => void;
  onDownload: (path: string) => void;
}) {
  if (!matrix) {
    return (
      <section className="bmfMatrixPanel isLoading" aria-live="polite">
        <div className="sectionHeading">
          <div>
            <span className="heroKicker">BMF-Anforderungsmatrix</span>
            <h3>Pruefstatus wird geladen</h3>
          </div>
        </div>
      </section>
    );
  }
  const statusRank: Record<string, number> = { blocked: 0, review: 1, satisfied: 2, not_applicable: 3 };
  const rows = [...matrix.requirements].sort(
    (left, right) => (statusRank[left.evidence_status] ?? 9) - (statusRank[right.evidence_status] ?? 9)
  );
  const statusLabel = (status: string) => {
    if (status === "satisfied") return "erfuellt";
    if (status === "review") return "pruefen";
    if (status === "blocked") return "blockiert";
    return "nicht relevant";
  };
  const tone = (status: string) => status === "satisfied" ? "ok" : status === "blocked" ? "blocked" : "warning";
  const runTone = run?.status === "ready_for_method_review" ? "ok" : run?.status === "blocked" ? "blocked" : "warning";
  const acceptanceTone = methodAcceptance?.strict_ready
    ? "ok"
    : methodAcceptance?.decision_ready
      ? "warning"
      : "blocked";
  const acceptedChecks = methodAcceptance?.checks.filter((item) => item.passed).length ?? 0;
  const providerOnlyMethodGaps = Boolean(
    methodAcceptance?.provider_basis_resolution_required
    && methodAcceptance.unexplained_unmatched_count === 0
    && methodAcceptance.unexplained_method_gap_groups_count === 0
  );
  const migrationTechnicalChecks = migrationRehearsal?.checks.filter((item) => item.gate === "technical") ?? [];
  const migrationTechnicalChecksPassed = migrationTechnicalChecks.filter((item) => item.passed).length;
  const migrationParityYears = migrationRehearsal?.year_checks.filter((item) => item.parity).length ?? 0;
  const migrationTone = migrationRehearsal?.status === "already_active"
    ? "ok"
    : migrationRehearsal?.status === "blocked"
      ? "blocked"
      : "warning";
  const migrationHeadline = migrationRehearsal?.status === "already_active"
    ? "Wallet-/Depot-FIFO ist produktiv aktiv"
    : migrationRehearsal?.status === "ready_for_controlled_migration"
      ? "Bereit zur kontrollierten Migration"
      : migrationRehearsal?.status === "ready_for_method_decision"
        ? "Technisch bereit, Methodenentscheidung offen"
        : migrationRehearsal?.status === "blocked"
          ? "Migrationsprobe technisch blockiert"
          : "Noch keine Migrationsprobe vorhanden";
  const applyChecksPassed = applyReadiness?.checks.filter((item) => item.passed).length ?? 0;
  const applyTone = applyReadiness?.status === "already_active"
    ? "ok"
    : applyReadiness?.status === "ready_for_controlled_apply"
      ? "warning"
      : "blocked";
  const applyHeadline = applyReadiness?.status === "already_active"
    ? "Wallet-/Depot-FIFO produktiv aktiv"
    : applyReadiness?.status === "ready_for_controlled_apply"
      ? "Kontrollierter Apply technisch freigegeben"
      : "Produktivaktivierung gesperrt";
  const formatStorage = (bytes: number) => `${new Intl.NumberFormat("de-DE", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1
  }).format(bytes / (1024 ** 3))} GB`;
  const acceptanceDecisionLabel = methodAcceptance?.decision_status === "approved_for_controlled_migration"
    ? "Migration freigegeben"
    : methodAcceptance?.decision_status === "retain_global_fifo_pending_professional_review"
      ? "Globale Methode in Fachpruefung"
      : methodAcceptance?.decision_status === "rejected_requires_rework"
        ? "Nacharbeit angefordert"
        : "Entscheidung offen";
  const materialDeltaGroups = [...(methodDelta?.groups ?? [])]
    .sort((left, right) => Math.abs(Number(right.gain_loss_delta_eur)) - Math.abs(Number(left.gain_loss_delta_eur)))
    .slice(0, 6);
  const legalTone = legalFreshness?.is_fresh
    ? "ok"
    : legalFreshness?.status === "review_required" || legalFreshness?.status === "stale"
      ? "warning"
      : "blocked";
  const legalHeadline = legalFreshness?.is_fresh
    ? "Offizielle Rechtsquellen sind aktuell geprueft"
    : legalFreshness?.status === "review_required"
      ? "Neue Fundstellen warten auf fachliche Pruefung"
      : legalFreshness?.status === "stale"
        ? "Rechtsstands-Pruefung ist abgelaufen"
        : "Aktueller Rechtsstand ist nicht bestaetigt";
  const legalFinding = legalFreshness?.findings[0]
    ?? "Ohne aktuellen Lauf werden keine Aussagen als aktueller Rechtsstand freigegeben.";
  return (
    <section className={`bmfMatrixPanel ${matrix.strict_bmf_ready ? "ok" : "blocked"}`}>
      <div className="sectionHeading bmfMatrixHeading">
        <div>
          <span className="heroKicker">BMF-Anforderungsmatrix</span>
          <h3>{matrix.strict_bmf_ready ? "Streng BMF-ready" : "Noch nicht streng BMF-ready"}</h3>
          <p>Freigabe nach Anforderung, Datenbeleg und produktiver Berechnungsmethode.</p>
        </div>
        <span className={`statusPill ${matrix.strict_bmf_ready ? "ok" : "blocked"}`}>
          {matrix.strict_bmf_ready ? <Check size={15} /> : <AlertTriangle size={15} />}
          {matrix.strict_bmf_ready ? "vollstaendig" : `${matrix.blocked_count} Blocker`}
        </span>
      </div>
      <div className="bmfMatrixMetrics">
        <Metric title="Erfuellt" value={String(matrix.satisfied_count)} />
        <Metric title="Zu pruefen" value={String(matrix.review_count)} />
        <Metric title="Blockiert" value={String(matrix.blocked_count)} />
        <Metric title="Konservative Jahre" value={matrix.conservative_years.join(", ") || "keine"} />
      </div>
      <div className={`legalFreshnessNotice ${legalTone}`} aria-live="polite">
        <div className="legalFreshnessIcon" aria-hidden="true">
          {legalFreshness?.is_fresh ? <ClipboardCheck size={19} /> : <AlertTriangle size={19} />}
        </div>
        <div className="legalFreshnessMain">
          <span className="heroKicker">Rechtsstand und neue Urteile</span>
          <strong>{legalHeadline}</strong>
          <p>{legalFinding}</p>
          <div className="legalFreshnessMeta">
            <span>Geprueft: {legalFreshness ? formatDateTime(legalFreshness.generated_at) : "noch nicht"}</span>
            <span>Gueltig bis: {legalFreshness ? formatDateTime(legalFreshness.fresh_until) : "-"}</span>
            <span>{legalFreshness?.source_checks.length ?? 0} Quellen · {legalFreshness?.monitor_checks.length ?? 0} Suchmonitore</span>
          </div>
        </div>
        <a href={matrix.bmf_reference_url} target="_blank" rel="noreferrer" title="Aktuelles BMF-Schreiben in der offiziellen Quelle oeffnen">
          <ExternalLink size={16} />
          BMF-Quelle
        </a>
      </div>
      <div className={`walletFifoRunSummary ${runTone}`}>
        <div className="walletFifoRunHeader">
          <div>
            <span className="heroKicker">Wallet-/Depot-FIFO {run?.years[0] ?? 2021}-{run?.years.at(-1) ?? 2026}</span>
            <strong>{run ? (run.status === "ready_for_method_review" ? "Bereit zur Methodenpruefung" : run.status === "blocked" ? "Prueflauf blockiert" : "Delta fachlich pruefen") : "Noch kein versionierter Prueflauf"}</strong>
            <p>{run?.findings[0] ?? "Erzeugt einen read-only Stichtagslauf mit vollstaendigen CSV-Belegspuren, ohne produktive Steuerdaten zu veraendern."}</p>
          </div>
          <button type="button" onClick={onRun} disabled={running} title="Wallet-/Depot-FIFO fuer den aktuellen Datenstand neu berechnen">
            <RefreshCcw size={16} />
            {running ? "Prueflauf laeuft" : "Prueflauf starten"}
          </button>
        </div>
        {run ? (
          <>
            <div className="walletFifoRunMetrics">
              <Metric title="Stichtag" value={formatDateTime(run.as_of)} />
              <Metric title="Globales G/V" value={`${formatCurrency(run.global_gain_loss_eur)} EUR`} />
              <Metric title="Wallet-FIFO G/V" value={`${formatCurrency(run.wallet_gain_loss_eur)} EUR`} />
              <Metric title="Delta" value={`${formatCurrency(run.delta_gain_loss_eur)} EUR`} />
              <Metric title="Pool-Luecken" value={String(run.unmatched_count)} />
              <Metric title="Provider-Basisluecken" value={run.report_schema_version === "wallet_fifo_run_v2_provider_basis_classification" ? String(run.provider_basis_gap_count) : "noch nicht klassifiziert"} />
              <Metric title="Wirklich ungeklaert" value={run.report_schema_version === "wallet_fifo_run_v2_provider_basis_classification" ? String(run.unexplained_unmatched_count) : String(run.unmatched_count)} />
              <Metric title="Offene Herkunft" value={String(run.unresolved_inbound_provenance_count)} />
              <Metric title="Transferbeleg-Review" value={String(run.transfer_evidence_review_count)} />
              <Metric title="Kaufbeleg-Review" value={String(run.acquisition_cost_evidence_review_count)} />
            </div>
            <div className={`walletFifoParityNotice ${run.event_set_mismatch_years.length ? "blocked" : "ok"}`}>
              {run.event_set_mismatch_years.length ? <AlertTriangle size={18} /> : <Check size={18} />}
              <div>
                <strong>
                  {run.event_set_mismatch_years.length
                    ? providerOnlyMethodGaps
                      ? `Provider-Kostenbasis in ${run.event_set_mismatch_years.join(", ")} offen`
                      : `Mengenabweichung in ${run.event_set_mismatch_years.join(", ")}`
                    : "Veraeusserungsmengen je Jahr/Asset stimmen"}
                </strong>
                <span>
                  {providerOnlyMethodGaps
                    ? `${methodAcceptance?.provider_basis_gap_count ?? 0} Bitget-Abgaenge sind mengenmaessig belegt; nur die vom Provider nicht exportierten Bot-Fill-Anschaffungskosten fehlen.`
                    : <>Explizite Netzwerkgebuehren, Bewertungserloese und Cost Basis werden getrennt ausgewiesen
                      {run.valuation_review_years.length ? `; Bewertungsreview: ${run.valuation_review_years.join(", ")}.` : "."}</>}
                </span>
              </div>
            </div>
            {methodAcceptance ? (
              <div className={`walletFifoParityNotice ${acceptanceTone}`}>
                {methodAcceptance.strict_ready ? <Check size={18} /> : <ClipboardCheck size={18} />}
                <div>
                  <strong>
                    {methodAcceptance.strict_ready
                      ? "Wallet-/Depot-FIFO ist abgenommen und produktiv aktiv"
                      : methodAcceptance.decision_ready
                        ? "Methodenakte ist entscheidungsreif"
                        : "Methodenakte ist noch nicht entscheidungsreif"}
                  </strong>
                  <span>{methodAcceptance.blockers[0] ?? methodAcceptance.findings[0]}</span>
                  <div className="walletFifoRunMetrics">
                    <Metric title="Run-Bindung" value={methodAcceptance.input_fingerprint_current ? "aktuell" : "veraltet"} />
                    <Metric title="Checks" value={`${acceptedChecks}/${methodAcceptance.checks.length}`} />
                    <Metric title="Provider-Basis" value={String(methodAcceptance.provider_basis_gap_count)} />
                    <Metric title="Wirklich ungeklaert" value={String(methodAcceptance.unexplained_unmatched_count)} />
                    <Metric title="Methodengruppen ungeklaert" value={String(methodAcceptance.unexplained_method_gap_groups_count)} />
                    <Metric title="Entscheidung" value={acceptanceDecisionLabel} />
                    <Metric title="Aktive Methode" value={methodAcceptance.activation_applied ? "Wallet-/Depot-FIFO" : "Globales Asset-FIFO"} />
                  </div>
                </div>
              </div>
            ) : null}
            <div className={`walletFifoParityNotice ${migrationTone}`}>
              {migrationRehearsal?.technical_ready ? <Database size={18} /> : <AlertTriangle size={18} />}
              <div>
                <strong>{migrationHeadline}</strong>
                <span>
                  {migrationRehearsal?.blockers[0]
                    ?? migrationRehearsal?.findings[0]
                    ?? "Die Zieltabellen werden nur temporaer aufgebaut und gegen den gebundenen Wallet-FIFO-Lauf geprueft."}
                </span>
                {migrationRehearsal ? (
                  <div className="walletFifoRunMetrics">
                    <Metric title="Technische Checks" value={`${migrationTechnicalChecksPassed}/${migrationTechnicalChecks.length}`} />
                    <Metric title="Provider-Basis" value={String(migrationRehearsal.provider_basis_gap_count)} />
                    <Metric title="Wirklich ungeklaert" value={String(migrationRehearsal.unexplained_unmatched_count)} />
                    <Metric title="Lots im Staging" value={String(migrationRehearsal.staging_lots_count)} />
                    <Metric title="Tax-Lines im Staging" value={String(migrationRehearsal.staging_tax_lines_count)} />
                    <Metric title="Jahresparitaet" value={`${migrationParityYears}/${migrationRehearsal.year_checks.length}`} />
                    <Metric title="Verwaiste Tax-Lines" value={String(migrationRehearsal.staging_orphan_tax_lines_count)} />
                    <Metric title="Produktiver Schreibzugriff" value={migrationRehearsal.production_write_performed ? "ja" : "nein"} />
                  </div>
                ) : null}
                <div className="walletFifoEvidenceActions">
                  <button
                    type="button"
                    onClick={onRunMigration}
                    disabled={running || migrationRunning}
                    title="Wallet-/Depot-FIFO ausschliesslich in einer temporaeren Staging-Datenbank pruefen"
                  >
                    <Database size={16} />
                    {migrationRunning ? "Migrationsprobe laeuft" : "Migrationsprobe starten"}
                  </button>
                </div>
              </div>
            </div>
            <div className={`walletFifoParityNotice ${applyTone}`}>
              {applyReadiness?.status === "already_active" ? <Check size={18} /> : <GitBranch size={18} />}
              <div>
                <strong>{applyHeadline}</strong>
                <span>
                  {applyReadiness?.blockers[0]
                    ?? applyReadiness?.next_actions[0]
                    ?? "Run-, Rehearsal-, Entscheidungs-, Backup- und Atomaritaetsgate werden gemeinsam geprueft."}
                </span>
                {applyReadiness ? (
                  <div className="walletFifoRunMetrics">
                    <Metric title="Apply-Gates" value={`${applyChecksPassed}/${applyReadiness.checks.length}`} />
                    <Metric title="Entscheidung" value={acceptanceDecisionLabel} />
                    <Metric title="Run/Rehearsal" value={applyReadiness.input_fingerprint_current && applyReadiness.rehearsal_bound ? "gebunden" : "offen"} />
                    <Metric title="Backup erforderlich" value={formatStorage(applyReadiness.required_backup_bytes)} />
                    <Metric title="Backup verfuegbar" value={formatStorage(applyReadiness.available_backup_bytes)} />
                    <Metric title="Aktive Methode" value={applyReadiness.status === "already_active" ? "Wallet-/Depot-FIFO" : "Globales Asset-FIFO"} />
                  </div>
                ) : null}
              </div>
            </div>
            {methodDelta ? (
              <div className="walletFifoDeltaExplanation">
                <div className="walletFifoDeltaHeading">
                  <div>
                    <span className="heroKicker">Warum weichen die Ergebnisse ab?</span>
                    <strong>
                      {methodDelta.extra_turnover_detected
                        ? "Zusaetzlicher Veraeusserungsumsatz muss geprueft werden"
                        : "Kein zusaetzlicher Veraeusserungsumsatz erkannt"}
                    </strong>
                    <p>
                      Ergebnisdelta = Erlosbeitrag plus Cost-Basis-Beitrag. Andere historische Lots
                      veraendern den Gewinn, ohne dass dadurch ein weiterer Verkauf entsteht.
                    </p>
                  </div>
                  <span className={`statusPill ${methodDelta.status === "blocked" ? "blocked" : methodDelta.status === "review" ? "warning" : "ok"}`}>
                    {methodDelta.status === "blocked"
                      ? providerOnlyMethodGaps ? "Provider-Kostenbasis offen" : "Primaerdaten offen"
                      : "rechnerisch erklaert"}
                  </span>
                </div>
                <div className="walletFifoRunMetrics">
                  <Metric title="Ergebnisdelta" value={`${formatCurrency(methodDelta.gain_loss_delta_eur)} EUR`} />
                  <Metric title="Erlosbeitrag" value={`${formatCurrency(methodDelta.proceeds_contribution_to_gain_delta_eur)} EUR`} />
                  <Metric title="Cost-Basis-Beitrag" value={`${formatCurrency(methodDelta.cost_basis_contribution_to_gain_delta_eur)} EUR`} />
                  <Metric title="Verglichene Ereignisse" value={String(methodDelta.compared_events_count)} />
                  <Metric
                    title={providerOnlyMethodGaps ? "Provider-Mengengruppen" : "Mengenluecken"}
                    value={String(methodDelta.quantity_gap_groups_count)}
                  />
                  <Metric title="Lot-Reihenfolge" value={String(methodDelta.pool_reordering_groups_count)} />
                  <Metric title="Unerklaerte Erlosreviews" value={String(methodDelta.unexplained_proceeds_delta_groups_count)} />
                  <Metric title="Gebuehren-Events" value={String(methodDelta.quote_asset_fee_netting_events_count)} />
                </div>
                {materialDeltaGroups.length ? (
                  <div className="walletFifoDeltaRows" aria-label="Groesste Wallet-FIFO Methodendifferenzen">
                    {materialDeltaGroups.map((group) => (
                      <div className="walletFifoDeltaRow" key={`${group.year}-${group.asset}`}>
                        <strong>{group.year} · {group.asset}</strong>
                        <span>{formatCurrency(group.gain_loss_delta_eur)} EUR G/V</span>
                        <small>
                          Erlos {formatCurrency(group.proceeds_delta_eur)} EUR · Cost Basis {formatCurrency(group.cost_basis_delta_eur)} EUR
                        </small>
                        <span className={`statusPill ${group.quantity_parity ? "warning" : "blocked"}`}>
                          {group.quantity_parity
                            ? "andere Lots"
                            : providerOnlyMethodGaps ? "Provider-Basis offen" : "Menge offen"}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : null}
                <div className="walletFifoEvidenceActions">
                  <button type="button" onClick={() => onDownload(methodDelta.full_event_csv_download_url)}>
                    <FileDown size={15} />
                    Vollstaendige Ereignis-CSV
                  </button>
                </div>
              </div>
            ) : null}
            <div className="walletFifoRunYears" aria-label="Wallet-FIFO Jahresstatus">
              {run.year_results.map((item) => (
                <span
                  className={`statusPill ${item.status === "ready_for_method_review" ? "ok" : item.status === "blocked" ? "blocked" : "warning"}`}
                  key={item.year}
                  title={item.event_set_parity
                    ? `Mengen paritaetisch; Bewertung: ${item.proceeds_parity ? "gleich" : item.valuation_review_assets.join(", ")}; Cost-Basis-Assets: ${item.basis_method_delta_assets.join(", ") || "keine"}`
                    : `Menge pruefen: ${item.event_set_mismatch_assets.join(", ")}`}
                >
                  {item.year}: {formatCurrency(item.delta_gain_loss_eur)} EUR · {item.event_set_parity ? (item.proceeds_parity ? "Menge/Wert ok" : "Menge ok, Wert pruefen") : "Menge offen"}
                </span>
              ))}
            </div>
            <div className="walletFifoEvidenceActions">
              {run.evidence_files.filter((file) => file.download_url).map((file) => (
                <button type="button" key={file.kind} onClick={() => onDownload(String(file.download_url))}>
                  <FileDown size={15} />
                  {file.kind.replace("wallet_fifo_", "").replaceAll("_", " ")}
                </button>
              ))}
            </div>
          </>
        ) : null}
      </div>
      <div className="bmfMatrixRows">
        {rows.map((row) => (
          <article className={`bmfMatrixRow ${tone(row.evidence_status)}`} key={row.requirement_id}>
            <div className="bmfMatrixRowIcon" aria-hidden="true">
              {row.evidence_status === "satisfied" ? <ClipboardCheck size={18} /> : <AlertTriangle size={18} />}
            </div>
            <div className="bmfMatrixRowMain">
              <div className="bmfMatrixRowTitle">
                <strong>{row.title}</strong>
                <span>Rn. {row.bmf_paragraphs.join(", ")}</span>
              </div>
              <p>{row.findings[0] ?? row.requirement}</p>
              <small>{row.next_action}</small>
            </div>
            <div className="bmfMatrixRowStatus">
              <span className={`statusPill ${tone(row.evidence_status)}`}>{statusLabel(row.evidence_status)}</span>
              <span>{row.implementation_status === "implemented" ? "implementiert" : "teilweise"}</span>
            </div>
          </article>
        ))}
      </div>
      <footer>
        Stand {formatDateTime(matrix.generated_at)} · Version {matrix.matrix_version}
      </footer>
    </section>
  );
}

function BitgetStrategyBasisDecisionPanel({
  report,
  reconstruction,
  loading,
  onSave
}: {
  report: Snapshot["bitgetStrategyBasisDecision"];
  reconstruction: Snapshot["bitgetStrategyReconstruction"];
  loading: boolean;
  onSave: (payload: BitgetBasisDecisionPayload) => void;
}) {
  const [decision, setDecision] = useState<BitgetBasisDecisionPayload["decision"]>(
    "retain_provider_gap_pending_professional_review"
  );
  const [actor, setActor] = useState("user");
  const [rationale, setRationale] = useState("");
  const [acknowledged, setAcknowledged] = useState(false);

  useEffect(() => {
    if (report?.decision_status && report.decision_status !== "pending") {
      setDecision(report.decision_status);
      setActor(report.decision_actor || "user");
      setRationale(report.decision_rationale || "");
    }
  }, [report?.decision_id]);

  if (!report || !reconstruction) {
    return null;
  }

  const estimateDecision = decision === "approve_zero_basis_estimate_for_staging"
    || decision === "approve_settlement_value_proxy_estimate_for_staging";
  const technicallyAllowed = report.input_fingerprint_current
    && (!estimateDecision || report.decision_ready);
  const canSave = technicallyAllowed
    && rationale.trim().length >= 30
    && actor.trim().length >= 2
    && acknowledged
    && !loading;
  const statusTone = report.decision_status === "pending"
    ? report.decision_ready ? "warning" : "blocked"
    : report.estimate_selected_for_staging ? "warning" : "ok";
  const decisionLabel = {
    pending: "Fachentscheidung offen",
    retain_provider_gap_pending_professional_review: "Providerluecke bleibt offen",
    approve_zero_basis_estimate_for_staging: "Nullbasis nur im Staging",
    approve_settlement_value_proxy_estimate_for_staging: "Settlement-Proxy nur im Staging",
    rejected_requires_rework: "Rekonstruktion abgelehnt"
  }[report.decision_status];

  return (
    <div className="bitgetDecisionBand">
      <div className="panelToolbar">
        <div>
          <span className="heroKicker">Bitget 2024</span>
          <strong>Basismethodenentscheidung</strong>
        </div>
        <span className={`statusPill ${statusTone}`}>{decisionLabel}</span>
      </div>
      <p>
        Die Mengen und Verkaeufe sind belegt; nur die nicht exportierten Bot-Fills fehlen.
        Ein Kontoauszug wuerde diese interne Providerluecke nicht schliessen. Keine der
        folgenden Varianten veraendert automatisch FIFO, Lots oder Steuerwerte.
      </p>
      <div className="fifoProofMetrics">
        <Metric
          title="Belegte Erloese"
          value={`${formatCurrency(reconstruction.attributable_disposal_proceeds_total_eur)} EUR`}
        />
        <Metric
          title="Nullbasis G/V"
          value={`${formatCurrency(reconstruction.zero_basis_gain_sensitivity_total_eur)} EUR`}
        />
        <Metric
          title="Settlement-Basis"
          value={`${formatCurrency(reconstruction.settlement_value_proxy_basis_total_eur)} EUR`}
        />
        <Metric
          title="Settlement G/V"
          value={`${formatCurrency(reconstruction.settlement_value_proxy_gain_sensitivity_total_eur)} EUR`}
        />
      </div>
      <div className="formGrid bitgetDecisionForm">
        <label>
          Entscheidung
          <select
            value={decision}
            onChange={(event) => setDecision(
              event.target.value as BitgetBasisDecisionPayload["decision"]
            )}
          >
            <option value="retain_provider_gap_pending_professional_review">
              Offen lassen bis zur Fachpruefung
            </option>
            <option value="approve_settlement_value_proxy_estimate_for_staging">
              Settlement-Proxy fuer Staging
            </option>
            <option value="approve_zero_basis_estimate_for_staging">
              Nullbasis fuer Staging
            </option>
            <option value="rejected_requires_rework">
              Rekonstruktion zur Ueberarbeitung ablehnen
            </option>
          </select>
        </label>
        <label>
          Bearbeiter
          <input value={actor} onChange={(event) => setActor(event.target.value)} />
        </label>
        <label className="bitgetDecisionRationale">
          Begruendung
          <textarea
            value={rationale}
            onChange={(event) => setRationale(event.target.value)}
            placeholder="Mindestens 30 Zeichen; verwendete Belege und fachliche Begruendung festhalten."
          />
        </label>
        <label className="checkboxLabel bitgetDecisionAcknowledge">
          <input
            type="checkbox"
            checked={acknowledged}
            onChange={(event) => setAcknowledged(event.target.checked)}
          />
          <span>
            Provider-Fills fehlen; Schaetzwerte sind keine beobachteten Transaktionen,
            gelten konsistent nur im Staging und werden vor einer Abgabe fachlich geprueft.
          </span>
        </label>
      </div>
      {report.blockers.length ? (
        <div className="walletFifoParityNotice blocked">
          <AlertTriangle size={18} />
          <div>
            <strong>Entscheidung noch blockiert</strong>
            <span>{report.blockers[0]}</span>
          </div>
        </div>
      ) : null}
      <div className="reportActionBand compactActions">
        <button
          type="button"
          disabled={!canSave}
          onClick={() => onSave({
            decision,
            rationale: rationale.trim(),
            actor: actor.trim(),
            acknowledge_provider_fill_data_missing: true,
            acknowledge_estimate_not_observed_transaction: true,
            acknowledge_consistent_application: true,
            acknowledge_no_automatic_tax_effect: true,
            acknowledge_professional_review_before_filing: true
          })}
          title="Entscheidung an Run und Evidenzhashes binden"
        >
          <ClipboardCheck size={16} />
          {loading ? "Wird dokumentiert" : "Entscheidung dokumentieren"}
        </button>
        <button
          type="button"
          onClick={() => window.open(
            `${API_BASE}/api/v1/tax/wallet-fifo/bitget-strategy-review.html`,
            "_blank",
            "noopener,noreferrer"
          )}
        >
          <ExternalLink size={16} />
          Fachakte
        </button>
      </div>
      {report.decision_id ? (
        <div className="footer">
          Entscheidung {shortAccount(report.decision_id)} · {formatDateTime(report.decision_at)} ·
          produktive Steuerwirkung: keine
        </div>
      ) : null}
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
  taxBmfComplianceMatrix,
  legalResearchFreshness,
  walletFifoParallelRun,
  bitgetStrategyFifoGaps,
  bitgetStrategyReconstruction,
  bitgetStrategyBasisDecision,
  walletFifoMethodDeltaExplanation,
  walletFifoMethodAcceptance,
  walletFifoMigrationRehearsal,
  walletFifoMigrationApplyReadiness,
  taxBmfActionPlan,
  taxBmfFinalizationMatrix,
  taxBmfSubmissionGuide,
  taxBmfPriorFilingComparison,
  taxBmfPriorFilingDeclaredAmounts,
  taxBmfAmendmentWorklist,
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
  pionexHntReconciliation,
  crossCexTransferEvidence,
  fairspotStakingReconciliation,
  solanaStakingPositionReconciliation,
  moonpayReceipts,
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
  taxBusinessRewardInventoryReview,
  taxCryptoSwapValuationReview,
  taxCryptoSwapFifoParallelPreview,
  taxBmfCombinedFifoStaging,
  taxBmfFifoEventEvidence,
  taxBmfEventPriceRemediation,
  taxYearDrivers,
  taxYearGainLossRealityCheck,
  taxYearGainEvidenceReview,
  taxYearGainEvidencePriceDeltas,
  taxYearGainEvidenceEventDeltas,
  taxYearGainEvidenceAcquisitionEventDeltas,
  taxYearTurnoverAudit,
  taxYearsTurnoverAuditSummary,
  taxSolanaProgramIncomeReview,
  taxHeliumSwapContext,
  taxHeliumSwapEvidenceReview,
  taxHeliumSwapAlchemyAudit,
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
  onRunWalletFifoParallel,
  walletFifoRunLoading,
  onSaveBitgetBasisDecision,
  bitgetBasisDecisionLoading,
  onRunSwapFifoParallelPreview,
  swapFifoParallelLoading,
  onRunBmfCombinedFifoStaging,
  bmfCombinedFifoStagingLoading,
  onRunBmfFifoEventEvidence,
  bmfFifoEventEvidenceLoading,
  onRunBmfEventPriceRemediation,
  bmfEventPriceRemediationLoading,
  onRunWalletFifoMigrationRehearsal,
  walletFifoMigrationLoading,
  onRebuildDerivatives,
  onAddCexSenderOwnershipDecision,
  onSavePriorFilingDeclaredAmounts,
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
  taxBmfComplianceMatrix: Snapshot["taxBmfComplianceMatrix"];
  legalResearchFreshness: Snapshot["legalResearchFreshness"];
  walletFifoParallelRun: Snapshot["walletFifoParallelRun"];
  bitgetStrategyFifoGaps: Snapshot["bitgetStrategyFifoGaps"];
  bitgetStrategyReconstruction: Snapshot["bitgetStrategyReconstruction"];
  bitgetStrategyBasisDecision: Snapshot["bitgetStrategyBasisDecision"];
  walletFifoMethodDeltaExplanation: Snapshot["walletFifoMethodDeltaExplanation"];
  walletFifoMethodAcceptance: Snapshot["walletFifoMethodAcceptance"];
  walletFifoMigrationRehearsal: Snapshot["walletFifoMigrationRehearsal"];
  walletFifoMigrationApplyReadiness: Snapshot["walletFifoMigrationApplyReadiness"];
  taxBmfActionPlan: Snapshot["taxBmfActionPlan"];
  taxBmfFinalizationMatrix: Snapshot["taxBmfFinalizationMatrix"];
  taxBmfSubmissionGuide: Snapshot["taxBmfSubmissionGuide"];
  taxBmfPriorFilingComparison: Snapshot["taxBmfPriorFilingComparison"];
  taxBmfPriorFilingDeclaredAmounts: Snapshot["taxBmfPriorFilingDeclaredAmounts"];
  taxBmfAmendmentWorklist: Snapshot["taxBmfAmendmentWorklist"];
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
  pionexHntReconciliation: Snapshot["pionexHntReconciliation"];
  crossCexTransferEvidence: Snapshot["crossCexTransferEvidence"];
  fairspotStakingReconciliation: Snapshot["fairspotStakingReconciliation"];
  solanaStakingPositionReconciliation: Snapshot["solanaStakingPositionReconciliation"];
  moonpayReceipts: Snapshot["moonpayReceipts"];
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
  taxBusinessRewardInventoryReview: Snapshot["taxBusinessRewardInventoryReview"];
  taxCryptoSwapValuationReview: Snapshot["taxCryptoSwapValuationReview"];
  taxCryptoSwapFifoParallelPreview: Snapshot["taxCryptoSwapFifoParallelPreview"];
  taxBmfCombinedFifoStaging: Snapshot["taxBmfCombinedFifoStaging"];
  taxBmfFifoEventEvidence: Snapshot["taxBmfFifoEventEvidence"];
  taxBmfEventPriceRemediation: Snapshot["taxBmfEventPriceRemediation"];
  taxYearDrivers: Snapshot["taxYearDrivers"];
  taxYearGainLossRealityCheck: Snapshot["taxYearGainLossRealityCheck"];
  taxYearGainEvidenceReview: Snapshot["taxYearGainEvidenceReview"];
  taxYearGainEvidencePriceDeltas: Snapshot["taxYearGainEvidencePriceDeltas"];
  taxYearGainEvidenceEventDeltas: Snapshot["taxYearGainEvidenceEventDeltas"];
  taxYearGainEvidenceAcquisitionEventDeltas: Snapshot["taxYearGainEvidenceAcquisitionEventDeltas"];
  taxYearTurnoverAudit: Snapshot["taxYearTurnoverAudit"];
  taxYearsTurnoverAuditSummary: Snapshot["taxYearsTurnoverAuditSummary"];
  taxSolanaProgramIncomeReview: Snapshot["taxSolanaProgramIncomeReview"];
  taxHeliumSwapContext: Snapshot["taxHeliumSwapContext"];
  taxHeliumSwapEvidenceReview: Snapshot["taxHeliumSwapEvidenceReview"];
  taxHeliumSwapAlchemyAudit: Snapshot["taxHeliumSwapAlchemyAudit"];
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
  onRunWalletFifoParallel: () => void;
  walletFifoRunLoading: boolean;
  onSaveBitgetBasisDecision: (payload: BitgetBasisDecisionPayload) => void;
  bitgetBasisDecisionLoading: boolean;
  onRunSwapFifoParallelPreview: () => void;
  swapFifoParallelLoading: boolean;
  onRunBmfCombinedFifoStaging: () => void;
  bmfCombinedFifoStagingLoading: boolean;
  onRunBmfFifoEventEvidence: (
    scopeMode?: "priority_delta" | "full_ledger"
  ) => void;
  bmfFifoEventEvidenceLoading: boolean;
  onRunBmfEventPriceRemediation: (execute: boolean) => void;
  bmfEventPriceRemediationLoading: boolean;
  onRunWalletFifoMigrationRehearsal: () => void;
  walletFifoMigrationLoading: boolean;
  onRebuildDerivatives: () => void;
  onAddCexSenderOwnershipDecision: (row: Record<string, unknown>, decisionStatus: string) => void;
  onSavePriorFilingDeclaredAmounts: (years: Array<Record<string, unknown>>) => void;
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
  const taxCoreReady = Boolean(activePaymentRow || taxYearFilingSummary || taxYearDetail);
  const yearNeedsReview = taxCoreReady
    && (checklistWarnings.length > 0
      || blockingMethodologyGaps.length > 0
      || taxYearFilingSummary?.export_ready === false);
  const taxReadyTone: "ok" | "warning" = yearNeedsReview ? "warning" : "ok";
  const yearDecisionTone = !taxCoreReady ? "loading" : taxReadyTone;
  const yearDecisionHeadline = !taxCoreReady
    ? `${activeYearValue}: Daten werden geladen`
    : yearNeedsReview
    ? `${activeYearValue}: vor Abgabe pruefen`
    : `${activeYearValue}: Eingabewerte vorbereitet`;
  const yearDecisionText = activePaymentRow?.what_to_do
    ? String(activePaymentRow.what_to_do)
    : taxYearFilingSummary?.plain_language_summary ?? "Jahreswerte werden geladen. Die Ansicht zeigt danach die eintragbaren Betraege und Belege.";
  const nextChecklistItem = checklistWarnings[0] ?? paymentChecklist[0];
  const nextChecklistEvidence = humanReadableTaxEndpoint(
    String(nextChecklistItem?.evidence_ref ?? taxYearFilingSummaryHtmlPath(activeYearValue))
  );
  const walletFifoUnmatched = Number(taxYearWalletFifoDelta?.unmatched_count ?? 0);
  const walletFifoTransfers = taxYearWalletFifoDelta?.transfer_traces ?? [];
  const internalTransferBasisPending = taxYearWalletFifoDelta?.internal_transfer_basis_pending ?? [];
  const activeBitgetStrategyGroups = (bitgetStrategyFifoGaps?.groups ?? []).filter(
    (group) => String(group.year) === activeYearValue
  );
  const activeBitgetStrategyDisposals = activeBitgetStrategyGroups.flatMap(
    (group) => group.linked_disposals
  );
  const bitgetStrategyQuantityExplained = activeBitgetStrategyGroups.length > 0
    && Boolean(bitgetStrategyFifoGaps?.quantity_reconciled)
    && Number(bitgetStrategyFifoGaps?.unallocated_unmatched_disposals_count ?? 0) === 0;
  const activeBitgetReconstructionGroups = (bitgetStrategyReconstruction?.groups ?? []).filter(
    (group) => String(group.year) === activeYearValue
  );
  const activeBitgetReconstructionDisposals = activeBitgetReconstructionGroups.flatMap(
    (group) => group.linked_disposals
  );
  const bitgetReconstructionReady = activeBitgetReconstructionGroups.length > 0
    && activeBitgetReconstructionGroups.every(
      (group) => group.basis_reconstruction_status === "ready_for_professional_review"
    );
  const walletFifoProvenanceGroups = taxYearWalletFifoProvenancePriorities?.groups ?? [];
  const unresolvedInboundProvenance = Number(
    taxYearWalletFifoProvenancePriorities?.unresolved_inbound_provenance_count
      ?? taxYearWalletFifoDelta?.unresolved_inbound_provenance_count
      ?? 0
  );
  const walletFifoFeeTransfers = walletFifoTransfers.filter((trace) => Number(trace.fee_quantity ?? 0) > 0);
  const acquisitionCostReviewTransfers = walletFifoTransfers.filter((trace) => {
    const status = String(trace.status ?? "");
    return status.includes("cost_basis_pending") || status.includes("reward_component_review");
  });
  const walletFifoOk = Boolean(taxYearWalletFifoDelta) && walletFifoUnmatched === 0 && unresolvedInboundProvenance === 0;
  const cexOutflowAnchorItems = taxYearCexExchangeOutflowAnchorFeasibility?.items ?? [];
  const cexOutflowAnchorTone = Number(taxYearCexExchangeOutflowAnchorFeasibility?.anchor_missing_count ?? 0) > 0 ? "warning" : "ok";
  const legacyHeliumWallets = taxLegacyHeliumOverview?.wallets ?? [];
  const legacyHeliumTransfers = taxLegacyHeliumOverview?.fairspot_transfers ?? [];
  const walletFifoClosureItems = taxYearWalletFifoProvenanceClosure?.items ?? [];
  const serviceSwapClosureItems = walletFifoClosureItems.filter(
    (item) => String(item.category ?? "") === "service_mediated_jupiter_swap"
  );
  const readyServiceSwapCount = serviceSwapClosureItems.filter(
    (item) => String(item.closure_status ?? "").endsWith("tax_mapping_ready")
  ).length;
  const walletFifoClosureTone = Number(taxYearWalletFifoProvenanceClosure?.review_required_count ?? 0) > 0 ? "warning" : "ok";
  const pionexReconciliationTone = pionexHntReconciliation?.reconciliation_ready
    ? "ok"
    : pionexHntReconciliation?.preflight_ready
      ? "warning"
      : "blocked";
  const activeCrossCexRecords = (crossCexTransferEvidence?.records ?? []).filter(
    (record) => String(record.year) === activeYearValue
  );
  const crossCexEvidenceTone = activeCrossCexRecords.length > 0
    && activeCrossCexRecords.every((record) => record.ready)
      ? "ok"
      : activeCrossCexRecords.length > 0
        ? "warning"
        : "blocked";
  const fairspotReconciliationTone = fairspotStakingReconciliation?.strict_ready
    ? "ok"
    : fairspotStakingReconciliation
      ? "warning"
      : "blocked";
  const solanaStakingReconciliationTone = solanaStakingPositionReconciliation?.strict_ready
    ? "ok"
    : solanaStakingPositionReconciliation
      ? "warning"
      : "blocked";
  const moonpayReceiptTone = moonpayReceipts?.strict_ready
    ? "ok"
    : moonpayReceipts
      ? "warning"
      : "blocked";
  const walletFifoTone = walletFifoOk ? "ok" : walletFifoUnmatched > 0 ? "blocked" : "warning";
  const walletFifoProofLabel = walletFifoOk
    ? "FIFO-Nachverfolgung ohne offene Pool-Luecken"
    : walletFifoUnmatched > 0
      ? bitgetStrategyQuantityExplained
        ? `${walletFifoUnmatched} Mengen erklaert, Basis offen`
        : `${walletFifoUnmatched} offene Pool-Luecke(n)`
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
  const activeBusinessInventoryRows = (taxBusinessRewardInventoryReview?.rows ?? []).filter(
    (row) => String(row.disposal_year) === activeYearValue
  );
  const activeBusinessInventoryTotals = activeBusinessInventoryRows.reduce(
    (
      totals: { potentialLines: number; unresolvedLines: number; potentialGainLoss: number },
      row
    ) => {
      const classification = String(row.classification ?? "");
      const lines = Number(row.tax_lines_count ?? 0);
      if (classification === "potential_business_inventory") {
        totals.potentialLines += lines;
        totals.potentialGainLoss += Number(row.gain_loss_eur ?? 0);
      } else if (classification !== "non_reward_origin") {
        totals.unresolvedLines += lines;
      }
      return totals;
    },
    { potentialLines: 0, unresolvedLines: 0, potentialGainLoss: 0 }
  );
  const activeSwapFifoParallelYear = (taxCryptoSwapFifoParallelPreview?.years ?? []).find(
    (row) => String(row.year) === activeYearValue
  );
  const activeSwapFifoParallelAssets = (taxCryptoSwapFifoParallelPreview?.top_assets ?? []).filter(
    (row) => String(row.year) === activeYearValue
  );
  const activeSwapFifoParallelEvents = (taxCryptoSwapFifoParallelPreview?.top_events ?? []).filter(
    (row) => String(row.year) === activeYearValue
  );
  const activeCombinedFifoYear = (taxBmfCombinedFifoStaging?.year_rows ?? []).find(
    (row) => String(row.year) === activeYearValue
  );
  const activeCombinedFifoAssets = (taxBmfCombinedFifoStaging?.top_assets ?? []).filter(
    (row) => String(row.year) === activeYearValue
  );
  const activeCombinedFifoEvents = (taxBmfCombinedFifoStaging?.top_events ?? []).filter(
    (row) => String(row.year) === activeYearValue
  );
  const activeCombinedFifoSpheres = (taxBmfCombinedFifoStaging?.sphere_rows ?? []).filter(
    (row) => String(row.year) === activeYearValue
  );
  const activeFifoEventEvidenceRows = (taxBmfFifoEventEvidence?.discrepancy_rows ?? []).filter(
    (row) => String(row.year) === activeYearValue
  );
  const activeFifoEventIssues = (taxBmfFifoEventEvidence?.event_issues ?? []).filter(
    (row) => row.event_time && String(new Date(row.event_time).getUTCFullYear()) === activeYearValue
  );
  const activeCombinedActiveGlobal = (activeCombinedFifoYear?.active_global ?? {}) as Record<string, unknown>;
  const activeCombinedReceivedGlobal = (activeCombinedFifoYear?.received_first_global ?? {}) as Record<string, unknown>;
  const activeCombinedActiveWallet = (activeCombinedFifoYear?.active_wallet ?? {}) as Record<string, unknown>;
  const activeCombinedReceivedWallet = (activeCombinedFifoYear?.received_first_wallet ?? {}) as Record<string, unknown>;
  const incomeAssets = taxIncomeGuide?.assets ?? [];
  const declarationIncomeAssets = incomeAssets.filter(
    (row) => String(row.classification ?? "") === "reward_income_candidate"
  );
  const reviewOnlyIncomeAssets = incomeAssets.filter(
    (row) => String(row.classification ?? "") !== "reward_income_candidate"
  );
  const reviewOnlyIncomeEvents = (taxIncomeGuide?.events ?? []).filter(
    (row) => String(row.classification ?? "") !== "reward_income_candidate"
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
  const taxProductRows = buildTaxProductYearRows({
    years,
    paymentRows,
    filingMatrixRows,
    filingClosureRows,
    submissionRows: taxBmfSubmissionGuide?.years ?? [],
    finalizationRows: taxBmfFinalizationMatrix?.years ?? []
  });
  const activeTaxProductRow = taxProductRows.find((row) => row.year === activeYearValue);
  const atAGlanceEntryItems: TaxAtAGlanceItem[] = [
    {
      label: "Anlage SO G/V",
      value: `${formatCurrency(activePaymentRow?.private_disposals_gain_loss_eur ?? taxYearFilingSummary?.taxable_private_disposals_eur)} EUR`,
      detail: String(activePaymentRow?.where_to_enter ?? "In die Eingabehilfe fuer das Steuerjahr uebernehmen."),
      tone: taxReadyTone
    },
    {
      label: "Rewards / Mining / Staking",
      value: `${formatCurrency(activePaymentRow?.rewards_mining_staking_income_eur ?? taxYearFilingSummary?.rewards_mining_staking_income_eur)} EUR`,
      detail: "Nur als Reward/Mining/Staking klassifizierte Zufluesse, Handel bleibt getrennt.",
      tone: "ok"
    },
    {
      label: "Derivate",
      value: `${formatCurrency(activePaymentRow?.derivative_pnl_eur ?? taxYearFilingSummary?.derivative_pnl_eur)} EUR`,
      detail: "Separat ausweisen, falls im Jahr vorhanden.",
      tone: Number(activePaymentRow?.derivative_pnl_eur ?? taxYearFilingSummary?.derivative_pnl_eur ?? 0) === 0 ? "ok" : "warning"
    },
    {
      label: "Steuerfrei archivieren",
      value: `${formatCurrency(activePaymentRow?.tax_free_private_disposals_eur ?? taxYearFilingSummary?.tax_free_private_disposals_eur)} EUR`,
      detail: "Nicht in die steuerpflichtige Summe mischen, aber fuer Haltefrist und Nachweis aufbewahren.",
      tone: "ok"
    }
  ];
  const atAGlanceEvidenceItems: TaxAtAGlanceItem[] = [
    ...primaryEvidenceItems.slice(0, 4).map((item) => ({
      label: String(item.label ?? item.evidence_id ?? "Beleg"),
      value: item.required ? "Pflicht" : "Nachweis",
      detail: String(item.note ?? item.endpoint ?? "Beleg im Jahrespaket enthalten."),
      endpoint: item.endpoint ? humanReadableTaxEndpoint(String(item.endpoint)) : undefined,
      tone: item.required ? "warning" as const : "ok" as const
    })),
    ...proofLines.slice(0, 4).map((line) => ({
      label: String(line.label ?? line.source_topic ?? "Nachweis"),
      value: String(line.topic ?? "Beleg"),
      detail: String(line.target ?? line.action ?? line.done_when ?? ""),
      endpoint: line.evidence_ref ? humanReadableTaxEndpoint(String(line.evidence_ref)) : undefined,
      tone: String(line.topic) === "review" ? "warning" as const : "ok" as const
    }))
  ].slice(0, 6);
  const atAGlanceReviewItems: TaxAtAGlanceItem[] = [
    ...(taxYearFilingSummary?.warnings ?? []).slice(0, 4).map((warning) => ({
      label: "Filing-Warnung",
      value: "pruefen",
      detail: String(warning),
      tone: "warning" as const
    })),
    ...checklistWarnings.slice(0, 4).map((item) => ({
      label: String(item.label ?? "Checkliste"),
      value: String(item.severity ?? "warning"),
      detail: String(item.done_when ?? item.action ?? item.evidence_ref ?? ""),
      endpoint: item.evidence_ref ? humanReadableTaxEndpoint(String(item.evidence_ref)) : undefined,
      tone: "warning" as const
    })),
    ...blockingMethodologyGaps.slice(0, 4).map((gap) => ({
      label: String(gap.label ?? gap.topic ?? "Methodik"),
      value: "blockiert",
      detail: String(gap.recommendation ?? gap.detail ?? gap.status ?? ""),
      tone: "blocked" as const
    })),
    ...yearReviewDecisions.slice(0, 4).map((decision) => ({
      label: String(decision.label ?? decision.topic ?? "Review"),
      value: String(decision.status ?? "review"),
      detail: String(decision.reason ?? decision.decision ?? decision.action ?? ""),
      tone: String(decision.status ?? "").includes("ready") ? "ok" as const : "warning" as const
    }))
  ].slice(0, 6);
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
          <span className={`statusPill ${taxCoreReady ? taxYearTone(String(selectedYear?.state ?? "")) : "loading"}`}>
            {taxCoreReady ? String(selectedYear?.label ?? "Jahresdaten vorhanden") : "wird geladen"}
          </span>
        </div>
      </section>

      <BmfComplianceMatrixPanel
        matrix={taxBmfComplianceMatrix}
        legalFreshness={legalResearchFreshness}
        run={walletFifoParallelRun}
        methodDelta={walletFifoMethodDeltaExplanation}
        methodAcceptance={walletFifoMethodAcceptance}
        migrationRehearsal={walletFifoMigrationRehearsal}
        applyReadiness={walletFifoMigrationApplyReadiness}
        running={walletFifoRunLoading}
        migrationRunning={walletFifoMigrationLoading}
        onRun={onRunWalletFifoParallel}
        onRunMigration={onRunWalletFifoMigrationRehearsal}
        onDownload={onDownload}
      />

      <section className={`taxFilingDecision ${yearDecisionTone}`}>
        <div className="taxFilingDecisionMain">
          <span className="heroKicker">Was bedeutet das fuer die Steuererklaerung?</span>
          <h3>{yearDecisionHeadline}</h3>
          <p>{yearDecisionText}</p>
          <div className="taxFilingTargets">
            <span className={`statusPill ${yearDecisionTone}`}>
              {taxCoreReady ? String(activePaymentRow?.declaration_bucket ?? (yearNeedsReview ? "pruefen" : "bereit")) : "wird geladen"}
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
          <button type="button" disabled={!taxCoreReady} onClick={() => onDownload(nextChecklistEvidence)}>
            {yearNeedsReview ? <AlertTriangle size={18} /> : <Check size={18} />}
            <span>{String(nextChecklistItem?.label ?? "Eingabehilfe oeffnen")}</span>
          </button>
          <button type="button" disabled={!taxCoreReady} onClick={() => onDownload(taxYearFilingSummaryHtmlPath(activeYearValue))}>
            <ReceiptText size={18} />
            <span>Eingabehilfe Website</span>
          </button>
          <button type="button" disabled={!taxCoreReady} onClick={() => onDownload(`/api/v1/export/tax-years/${activeYearValue}/evidence-package.zip`)}>
            <PackageCheck size={18} />
            <span>Jahres-Belegpaket</span>
          </button>
        </div>
        <div className="taxFilingDecisionMetrics">
          <Metric title="Anlage SO G/V" value={taxCoreReady ? `${formatCurrency(activePaymentRow?.private_disposals_gain_loss_eur ?? taxYearFilingSummary?.taxable_private_disposals_eur)} EUR` : "Wird geladen"} />
          <Metric title="Rewards eintragen" value={taxCoreReady ? `${formatCurrency(activePaymentRow?.rewards_mining_staking_income_eur ?? taxYearFilingSummary?.rewards_mining_staking_income_eur)} EUR` : "Wird geladen"} />
          <Metric title="Derivate" value={taxCoreReady ? `${formatCurrency(activePaymentRow?.derivative_pnl_eur ?? taxYearFilingSummary?.derivative_pnl_eur)} EUR` : "Wird geladen"} />
          <Metric title="Steuerfrei" value={taxCoreReady ? `${formatCurrency(activePaymentRow?.tax_free_private_disposals_eur ?? taxYearFilingSummary?.tax_free_private_disposals_eur)} EUR` : "Wird geladen"} />
        </div>
      </section>

      {taxCoreReady ? (
        <TaxFilingAtAGlance
          year={activeYearValue}
          tone={taxReadyTone}
          headline={activeTaxProductRow?.statusLabel ?? yearDecisionHeadline}
          summary={taxYearFilingSummary?.plain_language_summary ?? yearDecisionText}
          entries={atAGlanceEntryItems}
          evidence={atAGlanceEvidenceItems}
          reviews={atAGlanceReviewItems}
          generatedAt={taxYearFilingSummary?.generated_at ?? taxDeclarationGuide?.generated_at}
          filingEndpoint={taxYearFilingSummaryHtmlPath(activeYearValue)}
          guideEndpoint={taxYearDeclarationGuideHtmlPath(activeYearValue)}
          evidencePackageEndpoint={`/api/v1/export/tax-years/${activeYearValue}/evidence-package.zip`}
          onDownload={onDownload}
        />
      ) : (
        <section className="loadingPlaceholder" aria-label="Steuerjahr-Kernwerte werden geladen">
          <span />
          <span />
          <span />
        </section>
      )}

      <TaxProductCommandCenter
        rows={taxProductRows}
        activeYear={activeYearValue}
        activeRow={activeTaxProductRow}
        onSelectYear={onSelectedTaxYearChange}
        onDownload={onDownload}
        loading={!taxCoreReady}
      />

      {taxViewMode === "guided" ? (
        <section className="toolSafetyPanel ok">
          <div>
            <span className="heroKicker">Detailberichte bei Bedarf laden</span>
            <h2>BMF-Nachweise bleiben verfuegbar</h2>
            <p>
              Die Eingabehilfe laedt zuerst die schnellen Kernzahlen. BMF-Abgabehilfe,
              Alt-Erklaerungsvergleich, Korrektur-Worklist und forensische FIFO-Details
              werden in den naechsten Ansichten nachgeladen, damit der Steuer-Tab nicht
              durch schwere Jahresreports blockiert.
            </p>
          </div>
          <div className="toolSafetyFacts">
            <strong>Fuer Abgabe und Pruefung</strong>
            <button type="button" onClick={() => onTaxViewModeChange("details")}>
              <ReceiptText size={16} />
              <span>BMF & Nachweise laden</span>
            </button>
            <button type="button" onClick={() => onTaxViewModeChange("expert")}>
              <Database size={16} />
              <span>Expertenmodus laden</span>
            </button>
          </div>
        </section>
      ) : null}

      {taxBmfSubmissionGuide ? (
        <div className="panel declarationGuidePanel">
          <div className="panelToolbar">
            <strong>BMF-Abgabehilfe 2021-2025</strong>
            <span className={`statusPill ${(taxBmfSubmissionGuide.blocked_years ?? []).length > 0 ? "blocked" : (taxBmfSubmissionGuide.review_years ?? []).length > 0 ? "warning" : "ok"}`}>
              {(taxBmfSubmissionGuide.ready_years ?? []).length} ready · {(taxBmfSubmissionGuide.conservative_ready_years ?? []).length} konservativ
            </span>
          </div>
          <div className="portfolioSummaryStrip">
            <Metric title="Anlage SO G/V" value={`${formatCurrency(taxBmfSubmissionGuide.total_taxable_private_disposals_eur)} EUR`} />
            <Metric title="Rewards/Mining" value={`${formatCurrency(taxBmfSubmissionGuide.total_rewards_mining_staking_income_eur)} EUR`} />
            <Metric title="Derivate" value={`${formatCurrency(taxBmfSubmissionGuide.total_derivative_pnl_eur)} EUR`} />
            <Metric title="Korrektur pruefen" value={String((taxBmfSubmissionGuide.amendment_review_years ?? []).length)} />
          </div>
          <TablePanel
            title="Was fuer die Steuererklaerung zu tun ist"
            rows={(taxBmfSubmissionGuide.years ?? []).map((row) => ({
              jahr: row.year,
              status: row.status_label,
              einreichbar: row.can_submit ? "ja" : row.can_submit_conservative ? "konservativ" : "nein",
              eintragen: row.declaration_bucket,
              ziel: row.where_to_enter,
              anlage_so_eur: formatCurrency(row.taxable_private_disposals_eur),
              rewards_eur: formatCurrency(row.rewards_mining_staking_income_eur),
              derivate_eur: formatCurrency(row.derivative_pnl_eur),
              beilegen: row.attach_count,
              fachreview: row.technical_review_requirements_count,
              erklaerung_vergleichen: row.declaration_compare_required ? "ja" : "nein",
              archivieren: row.archive_count,
              grund: row.amendment_reason,
              naechster_schritt: row.next_action,
              filing: row.filing_summary_endpoint,
              checklist_csv: row.filing_checklist_csv_endpoint,
              korrektur: row.correction_map_endpoint,
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
                label: "Eingabehilfe",
                icon: <ReceiptText size={16} />,
                onClick: (row) => onDownload(humanReadableTaxEndpoint(String(row.filing ?? "")))
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
            footer={taxBmfSubmissionGuide.methodology}
          />
          <div className="evidenceGrid">
            {(taxBmfSubmissionGuide.years ?? []).map((row) => (
              <div className="evidenceCard" key={`bmf-submission-${String(row.year)}`}>
                <div className="evidenceCardHeader">
                  <strong>{String(row.year)}</strong>
                  <span className={`statusPill ${String(row.status) === "blocked" ? "blocked" : String(row.status) === "review_required" ? "warning" : "ok"}`}>
                    {String(row.status_label ?? "-")}
                  </span>
                </div>
                <p>{String(row.filing_sentence ?? "")}</p>
                <p>{String(row.attachment_sentence ?? "")}</p>
                <p>{String(row.archive_sentence ?? "")}</p>
                <p>{String(row.review_sentence ?? "")}</p>
              </div>
            ))}
          </div>
          {taxBmfSubmissionGuide.ascii_table ? (
            <pre className="asciiTable" aria-label="Kopierbare BMF-Abgabehilfe">
              {taxBmfSubmissionGuide.ascii_table}
            </pre>
          ) : null}
        </div>
      ) : null}

      {taxBmfAmendmentWorklist ? (
        <div className="panel declarationGuidePanel">
          <div className="panelToolbar">
            <strong>Korrekturpruefungs-Worklist</strong>
            <span className={`statusPill ${(taxBmfAmendmentWorklist.blocked_years ?? []).length > 0 ? "blocked" : (taxBmfAmendmentWorklist.correction_review_years ?? []).length > 0 ? "warning" : "ok"}`}>
              {(taxBmfAmendmentWorklist.correction_review_years ?? []).length} Korrekturpruefung · {(taxBmfAmendmentWorklist.compare_declared_years ?? []).length} Delta-Vergleich
            </span>
            <button type="button" onClick={() => onDownload("/api/v1/export/tax-methodology/bmf-amendment-worklist.csv")}>
              <FileDown size={18} />
              <span>Worklist CSV</span>
            </button>
          </div>
          <div className="portfolioSummaryStrip">
            <Metric title="V2 Anlage SO" value={`${formatCurrency(taxBmfAmendmentWorklist.total_v2_taxable_private_disposals_eur)} EUR`} />
            <Metric title="V2 Rewards" value={`${formatCurrency(taxBmfAmendmentWorklist.total_v2_rewards_mining_staking_income_eur)} EUR`} />
            <Metric title="V2 Derivate" value={`${formatCurrency(taxBmfAmendmentWorklist.total_v2_derivative_pnl_eur)} EUR`} />
            <Metric title="Blockiert" value={String((taxBmfAmendmentWorklist.blocked_years ?? []).length)} />
          </div>
          <TablePanel
            title="Naechste Schritte fuer Vorjahre"
            rows={(taxBmfAmendmentWorklist.years ?? []).map((row) => ({
              jahr: row.year,
              status: row.status_label,
              altwert_status: row.prior_filing_status,
              anlage_so_eur: formatCurrency(row.v2_taxable_private_disposals_eur),
              rewards_eur: formatCurrency(row.v2_rewards_mining_staking_income_eur),
              derivate_eur: formatCurrency(row.v2_derivative_pnl_eur),
              fachreview: row.technical_review_requirements_count,
              grund: row.correction_reason,
              naechster_schritt: row.next_action,
              summary: row.filing_summary_endpoint,
              korrektur: row.correction_map_endpoint,
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
                label: "Eingabehilfe",
                icon: <ReceiptText size={16} />,
                onClick: (row) => onDownload(humanReadableTaxEndpoint(String(row.summary ?? "")))
              },
              {
                label: "Korrekturkarte CSV",
                icon: <FileDown size={16} />,
                onClick: (row) => onDownload(String(row.korrektur_csv ?? row.korrektur ?? ""))
              },
              {
                label: "Belegpaket",
                icon: <PackageCheck size={16} />,
                onClick: (row) => onDownload(String(row.paket ?? ""))
              }
            ]}
            footer={taxBmfAmendmentWorklist.methodology}
          />
          {taxBmfAmendmentWorklist.ascii_table ? (
            <pre className="asciiTable" aria-label="Kopierbare Korrekturpruefungs-Worklist">
              {taxBmfAmendmentWorklist.ascii_table}
            </pre>
          ) : null}
        </div>
      ) : null}

      {taxBmfPriorFilingComparison ? (
        <div className="panel declarationGuidePanel">
          <div className="panelToolbar">
            <strong>Alt-Erklaerungsvergleich</strong>
            <span className={`statusPill ${(taxBmfPriorFilingComparison.delta_review_years ?? []).length > 0 || (taxBmfPriorFilingComparison.untrusted_declared_years ?? []).length > 0 ? "warning" : (taxBmfPriorFilingComparison.missing_declared_years ?? []).length > 0 ? "warning" : "ok"}`}>
              {(taxBmfPriorFilingComparison.delta_review_years ?? []).length} Abweichung · {(taxBmfPriorFilingComparison.untrusted_declared_years ?? []).length} unklar/falsch · {(taxBmfPriorFilingComparison.missing_declared_years ?? []).length} ohne Altwert
            </span>
          </div>
          <div className="portfolioSummaryStrip">
            <Metric title="Delta Anlage SO" value={`${formatCurrency(taxBmfPriorFilingComparison.total_delta_taxable_private_disposals_eur)} EUR`} />
            <Metric title="Delta Rewards" value={`${formatCurrency(taxBmfPriorFilingComparison.total_delta_rewards_mining_staking_income_eur)} EUR`} />
            <Metric title="Delta Derivate" value={`${formatCurrency(taxBmfPriorFilingComparison.total_delta_derivative_pnl_eur)} EUR`} />
            <Metric title="Absolute Abweichung" value={`${formatCurrency(taxBmfPriorFilingComparison.total_absolute_delta_eur)} EUR`} />
          </div>
          <TablePanel
            title="V2 gegen urspruenglich erklaerte Werte"
            rows={(taxBmfPriorFilingComparison.years ?? []).map((row) => ({
              jahr: row.year,
              status: row.status_label,
              altwerte: row.declared_values_configured ? "hinterlegt" : "fehlen",
              altwert_status: row.declared_values_status,
              notiz: row.declared_values_note,
              v2_anlage_so_eur: formatCurrency(row.v2_taxable_private_disposals_eur),
              erklaert_anlage_so_eur: row.declared_taxable_private_disposals_eur == null ? "-" : formatCurrency(row.declared_taxable_private_disposals_eur),
              delta_anlage_so_eur: row.delta_taxable_private_disposals_eur == null ? "-" : formatCurrency(row.delta_taxable_private_disposals_eur),
              v2_rewards_eur: formatCurrency(row.v2_rewards_mining_staking_income_eur),
              erklaert_rewards_eur: row.declared_rewards_mining_staking_income_eur == null ? "-" : formatCurrency(row.declared_rewards_mining_staking_income_eur),
              delta_rewards_eur: row.delta_rewards_mining_staking_income_eur == null ? "-" : formatCurrency(row.delta_rewards_mining_staking_income_eur),
              absolut_delta_eur: formatCurrency(row.absolute_delta_eur),
              naechster_schritt: row.next_action,
              filing: row.filing_summary_endpoint,
              korrektur: row.correction_map_endpoint,
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
                label: "Korrekturkarte CSV",
                icon: <FileDown size={16} />,
                onClick: (row) => onDownload(String(row.korrektur_csv ?? row.korrektur ?? ""))
              },
              {
                label: "Belegpaket",
                icon: <PackageCheck size={16} />,
                onClick: (row) => onDownload(String(row.paket ?? ""))
              }
            ]}
            footer={taxBmfPriorFilingComparison.methodology}
          />
          <PriorFilingDeclaredAmountsForm
            comparison={taxBmfPriorFilingComparison}
            declaredAmounts={taxBmfPriorFilingDeclaredAmounts}
            onSave={onSavePriorFilingDeclaredAmounts}
          />
          {!taxBmfPriorFilingComparison.setting_exists ? (
            <div className="evidenceCard">
              <div className="evidenceCardHeader">
                <strong>Altwerte hinterlegen</strong>
                <span className="statusPill warning">Admin-Setting fehlt</span>
              </div>
              <p>
                Nutze die Eingabefelder oben oder lege im Admin-Bereich das Setting <code>{taxBmfPriorFilingComparison.setting_key}</code> an.
                Danach kann V2 die urspruenglich erklaerten Werte je Jahr gegenrechnen.
              </p>
              <pre className="asciiTable" aria-label="Beispiel JSON fuer Alt-Erklaerungswerte">
                {taxBmfPriorFilingComparison.example_setting_json}
              </pre>
            </div>
          ) : null}
          {taxBmfPriorFilingComparison.ascii_table ? (
            <pre className="asciiTable" aria-label="Kopierbarer Alt-Erklaerungsvergleich">
              {taxBmfPriorFilingComparison.ascii_table}
            </pre>
          ) : null}
        </div>
      ) : null}

      {taxBmfFinalizationMatrix ? (
        <div className="panel declarationGuidePanel">
          <div className="panelToolbar">
            <strong>BMF-Finalisierung 2021-2025</strong>
            <span className={`statusPill ${(taxBmfFinalizationMatrix.blocked_years ?? []).length > 0 ? "blocked" : (taxBmfFinalizationMatrix.review_years ?? []).length > 0 ? "warning" : "ok"}`}>
              {(taxBmfFinalizationMatrix.ready_years ?? []).length} ready · {(taxBmfFinalizationMatrix.conservative_ready_years ?? []).length} konservativ
            </span>
          </div>
          <div className="portfolioSummaryStrip">
            <Metric title="Anlage SO G/V" value={`${formatCurrency(taxBmfFinalizationMatrix.total_taxable_private_disposals_eur)} EUR`} />
            <Metric title="Rewards/Mining" value={`${formatCurrency(taxBmfFinalizationMatrix.total_rewards_mining_staking_income_eur)} EUR`} />
            <Metric title="Derivate" value={`${formatCurrency(taxBmfFinalizationMatrix.total_derivative_pnl_eur)} EUR`} />
            <Metric title="Blockiert" value={String((taxBmfFinalizationMatrix.blocked_years ?? []).length)} />
          </div>
          <TablePanel
            title="BMF-Abschlussampel je Steuerjahr"
            rows={(taxBmfFinalizationMatrix.years ?? []).map((row) => ({
              jahr: row.year,
              status: row.status_label,
              einreichbar: row.can_submit ? "ja" : row.can_submit_conservative ? "konservativ" : "nein",
              korrektur_pruefen: row.correction_review_recommended ? "ja" : "nein",
              anlage_so_eur: formatCurrency(row.taxable_private_disposals_eur),
              rewards_eur: formatCurrency(row.rewards_mining_staking_income_eur),
              blocker: row.blocking_count,
              review: row.review_count,
              naechster_schritt: row.next_action,
              summary: row.filing_summary_endpoint,
              korrektur: row.correction_map_endpoint,
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
                label: "Eingabehilfe",
                icon: <ReceiptText size={16} />,
                onClick: (row) => onDownload(humanReadableTaxEndpoint(String(row.summary ?? "")))
              },
              {
                label: "Korrekturkarte CSV",
                icon: <FileDown size={16} />,
                onClick: (row) => onDownload(String(row.korrektur_csv ?? row.korrektur ?? ""))
              },
              {
                label: "Belegpaket",
                icon: <PackageCheck size={16} />,
                onClick: (row) => onDownload(String(row.paket ?? ""))
              }
            ]}
            footer={taxBmfFinalizationMatrix.methodology}
          />
          {taxBmfFinalizationMatrix.ascii_table ? (
            <pre className="asciiTable" aria-label="Kopierbare BMF-Finalisierungsmatrix">
              {taxBmfFinalizationMatrix.ascii_table}
            </pre>
          ) : null}
        </div>
      ) : null}

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
            <Metric title="Rewards eintragen" value={`${formatCurrency(taxFilingClosureOverview.total_rewards_mining_staking_income_eur)} EUR`} />
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
                icon: <FileDown size={16} />,
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
                        <button type="button" onClick={() => onDownload(humanReadableTaxEndpoint(String(item.evidence_ref)))} title="Beleg oeffnen">
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
          <Metric title="Rewards eintragen" value={`${formatCurrency(activeCorrectionMap?.rewards_mining_staking_income_eur)} EUR`} />
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
                onClick: (row) => onDownload(humanReadableTaxEndpoint(String(row.beleg ?? "")))
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
          <strong>Handelsvolumen-Plausibilitaet</strong>
          <span>{taxYearTurnoverAudit?.generated_at ? formatDateTime(taxYearTurnoverAudit.generated_at) : "wird geladen"}</span>
        </div>
        <div className="portfolioSummaryStrip">
          <Metric title="Handelsvolumen" value={`${formatCurrency(taxYearTurnoverAudit?.gross_disposal_proceeds_eur)} EUR`} />
          <Metric title="Steuerpflichtig G/V" value={`${formatCurrency(taxYearTurnoverAudit?.taxable_gain_loss_eur)} EUR`} />
          <Metric title="Steuerfrei G/V" value={`${formatCurrency(taxYearTurnoverAudit?.tax_free_gain_loss_eur)} EUR`} />
          <Metric title="Stablecoin-Handel" value={`${formatCurrency(taxYearTurnoverAudit?.stablecoin_gross_disposal_proceeds_eur)} EUR`} />
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
          title="Top-Handelsvolumen nach Asset"
          rows={(taxYearTurnoverAudit?.top_assets_by_proceeds ?? []).slice(0, 8).map((row) => ({
            asset: row.asset,
            handelsvolumen_eur: formatCurrency(row.gross_disposal_proceeds_eur),
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
          title="Top-Quellen nach Handelsvolumen"
          rows={(taxYearTurnoverAudit?.top_sources_by_proceeds ?? []).slice(0, 8).map((row) => ({
            quelle: row.source,
            typ: row.event_type,
            asset: row.asset,
            quote: row.quote_asset ?? "-",
            handelsvolumen_eur: formatCurrency(row.gross_disposal_proceeds_eur),
            gewinn_verlust_eur: formatCurrency(row.gain_loss_eur),
            zeilen: row.tax_line_count
          }))}
          footer="Handelsvolumen ist die EUR-Bewertung der Disposals/Swaps. Es ist kein eingezahltes Kapital, kein ausgezahltes EUR und kein steuerpflichtiger Gewinn."
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
        title="Handelsvolumen-/Stablecoin-Plausibilitaet alle Steuerjahre"
        rows={(taxYearsTurnoverAuditSummary?.years ?? []).map((row) => ({
          jahr: row.year,
          risiko: row.risk_level,
          handelsvolumen_eur: formatCurrency(row.gross_disposal_proceeds_eur),
          steuerpflichtig_eur: formatCurrency(row.taxable_gain_loss_eur),
          steuerfrei_eur: formatCurrency(row.tax_free_gain_loss_eur),
          stablecoin_handel_eur: formatCurrency(row.stablecoin_gross_disposal_proceeds_eur),
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
          <strong>Helium Swap-/Trading-Kontext</strong>
          <span>{taxHeliumSwapContext?.generated_at ? formatDateTime(taxHeliumSwapContext.generated_at) : "wird geladen"}</span>
        </div>
        <div className="portfolioSummaryStrip">
          <Metric title="Swap-Kontext" value={`${formatCurrency(taxHeliumSwapContext?.total_context_value_eur)} EUR`} />
          <Metric title="steuerpfl. FIFO" value={`${formatCurrency(taxHeliumSwapContext?.total_taxable_trade_gain_loss_eur)} EUR`} />
          <Metric title="steuerfrei FIFO" value={`${formatCurrency(taxHeliumSwapContext?.total_tax_free_trade_gain_loss_eur)} EUR`} />
          <Metric title="gesamt FIFO" value={`${formatCurrency(taxHeliumSwapContext?.total_trade_gain_loss_eur)} EUR`} />
          <Metric title="Rewards getrennt" value={`${formatCurrency(taxHeliumSwapContext?.total_reward_income_eur)} EUR`} />
          <Metric title="Events" value={String(taxHeliumSwapContext?.events_count ?? 0)} />
        </div>
        <div className="portfolioSummaryStrip">
          <Metric title="TxIDs" value={String(taxHeliumSwapEvidenceReview?.tx_count ?? 0)} />
          <Metric title="lokal belegt" value={String(taxHeliumSwapEvidenceReview?.raw_evidence_ready_count ?? 0)} />
          <Metric title="Raw offen" value={String(taxHeliumSwapEvidenceReview?.raw_evidence_missing_count ?? 0)} />
          <Metric title="TxID-Kontext" value={`${formatCurrency(taxHeliumSwapEvidenceReview?.total_context_value_eur)} EUR`} />
        </div>
        <div className="portfolioSummaryStrip">
          <Metric title="Alchemy TxIDs" value={String(taxHeliumSwapAlchemyAudit?.tx_count ?? 0)} />
          <Metric title="Onchain bestaetigt" value={String(taxHeliumSwapAlchemyAudit?.confirmed_count ?? 0)} />
          <Metric title="Alchemy Fehler" value={String(taxHeliumSwapAlchemyAudit?.alchemy_failed_count ?? 0)} />
          <Metric title="Provider" value={String(taxHeliumSwapAlchemyAudit?.provider ?? "alchemy")} />
        </div>
        <TablePanel
          title="HNT/IOT/MOBILE: Reward vs Swap/FIFO"
          rows={(taxHeliumSwapContext?.assets ?? []).slice(0, 10).map((row) => ({
            jahr: row.year,
            asset: row.asset,
            swap_events: row.swap_context_events_count,
            swap_menge: row.swap_context_quantity,
            swap_wert_eur: formatCurrency(row.swap_context_value_eur),
            fifo_steuerpflichtig_eur: formatCurrency(row.taxable_trade_gain_loss_eur),
            fifo_steuerfrei_eur: formatCurrency(row.tax_free_trade_gain_loss_eur),
            reward_eur: formatCurrency(row.reward_income_eur),
            reward_menge: row.reward_quantity,
            status: row.classification
          }))}
          compact
        />
        <TablePanel
          title="Top Helium-Solana-Swap-Events"
          rows={(taxHeliumSwapContext?.rows ?? []).slice(0, 12).map((row) => ({
            zeit: row.event_time,
            asset: row.asset,
            menge: row.quantity,
            wert_eur: formatCurrency(row.value_eur),
            behandlung: row.tax_treatment,
            tx_assets: row.tx_assets,
            grund: row.review_reason,
            tx: row.tx_id,
            fifo: row.fifo_drilldown_endpoint
          }))}
          footer={taxHeliumSwapContext?.methodology ?? "Helium-Swap-Kontext wird geladen."}
          compact
        />
        <TablePanel
          title="Top Helium-TxIDs: lokale Belege"
          rows={(taxHeliumSwapEvidenceReview?.rows ?? []).slice(0, 12).map((row) => ({
            zeit: row.first_event_time,
            status: row.evidence_status,
            raw_belege: row.raw_evidence_count,
            assets: row.assets,
            wert_eur: formatCurrency(row.context_value_eur),
            dateien: Array.isArray(row.raw_filenames) ? row.raw_filenames.join(" | ") : row.raw_filenames,
            behandlung: row.tax_treatment,
            grund: row.review_reason,
            tx: row.tx_id,
            fifo: row.fifo_drilldown_endpoint
          }))}
          footer={taxHeliumSwapEvidenceReview?.methodology ?? "Helium-TxID-Belege werden geladen."}
          compact
        />
        <TablePanel
          title="Top Helium-TxIDs: Alchemy Onchain-Audit"
          rows={(taxHeliumSwapAlchemyAudit?.rows ?? []).slice(0, 12).map((row) => ({
            zeit: row.onchain_time_utc,
            status: row.review_status,
            alchemy: row.alchemy_status,
            wallet: row.wallet_seen ? "ja" : "nein",
            delta: row.helium_token_delta_seen ? "ja" : "nein",
            slot: row.slot,
            assets: row.assets,
            tx: row.tx_id
          }))}
          footer={taxHeliumSwapAlchemyAudit?.methodology ?? "Alchemy-Audit wird geladen."}
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
                : bitgetStrategyQuantityExplained
                  ? "Die Bitget-Abgangsmengen sind vollstaendig gegen vier Strategy-Settlements abgeglichen. Fuer eine strikte FIFO fehlen weiterhin die originalen Bot-Fills mit Anschaffungszeitpunkt und Kostenbasis."
                : unresolvedInboundProvenance > 0
                  ? "FIFO kann rechnerisch weiterlaufen, aber Zufluss-Herkunft ist noch nicht vollstaendig mit Transfer-, Deposit-, Withdrawal- oder Anfangsbestandsbelegen nachgewiesen."
                  : "Mindestens ein Abgang kann in der wallet-/depotbezogenen FIFO-Preview noch nicht vollstaendig aus Lots gedeckt werden."}
            </p>
          </div>
          <div className="fifoProofMetrics">
            <Metric title="Offene FIFO-Luecken" value={String(walletFifoUnmatched)} />
            <Metric title="Offene Herkunft" value={String(unresolvedInboundProvenance)} />
            <Metric title="Belegte Transfers" value={String(taxYearWalletFifoDelta?.transfer_traces_count ?? 0)} />
            <Metric title="Interne Uebertraege" value={String(taxYearWalletFifoDelta?.internal_transfer_carry_count ?? 0)} />
            <Metric title="Interne Basis offen" value={String(taxYearWalletFifoDelta?.internal_transfer_carry_basis_pending_count ?? 0)} />
            <Metric title="Fee-Transfers" value={String(walletFifoFeeTransfers.length)} />
          </div>
        </div>
        {internalTransferBasisPending.length > 0 ? (
          <TablePanel
            title="Interne Umbuchungen mit offener Alt-Basis"
            rows={internalTransferBasisPending.map((trace) => ({
              datum: formatDateTime(trace.event_time),
              asset: trace.asset ?? "-",
              richtung: trace.direction ?? "-",
              menge: formatQuantity(trace.quantity),
              belegt: formatQuantity(trace.basis_covered_quantity),
              offen: formatQuantity(trace.basis_missing_quantity),
              vorgang: trace.evidence_operation ?? trace.evidence_status ?? "-",
              beleg: `${String(trace.evidence_filename ?? "-").split("/").pop() ?? "-"}:${String(trace.evidence_row_number ?? "-")}`,
            }))}
            compact
          />
        ) : null}
        {activeBitgetStrategyGroups.length > 0 ? (
          <div className={`panelInlineBlock ${bitgetStrategyQuantityExplained ? "warning" : "blocked"}`}>
            <div className="panelToolbar">
              <strong>Bitget Bot-Settlements {activeYearValue}</strong>
              <span className={`statusPill ${bitgetStrategyQuantityExplained ? "warning" : "blocked"}`}>
                {bitgetStrategyFifoGaps?.support_package.package_complete
                  ? "Supportpaket vollstaendig"
                  : bitgetStrategyQuantityExplained
                    ? "Mengen belegt, Basis offen"
                    : "Mengen offen"}
              </span>
            </div>
            <div className="fifoProofBand">
              <div className="fifoProofSummary">
                <span className="heroKicker">Primaerbeleg-Abgrenzung</span>
                <strong>{activeBitgetStrategyDisposals.length} Abgaenge in {activeBitgetStrategyGroups.length} Ketten</strong>
                <p>
                  Alle vom Bitget-Support gelieferten Dateien sind vorhanden und hashgebunden.
                  Strategy.csv ordnet alle vier Settlements sekundengenau zu. Der Anbieterexport
                  enthaelt jedoch keine Bot-Einzelfills mit Strategy-ID; deshalb bleibt die exakte
                  Kaufzeit- und Kostenbasis offen. Es werden keine weiteren Dateien von dir verlangt.
                </p>
              </div>
              <div className="fifoProofMetrics">
                <Metric title="Zugeordnet" value={`${activeBitgetStrategyDisposals.length}/${bitgetStrategyFifoGaps?.unmatched_disposals_count ?? 0}`} />
                <Metric title="Nicht zugeordnet" value={String(bitgetStrategyFifoGaps?.unallocated_unmatched_disposals_count ?? 0)} />
                <Metric title="Supportdateien" value={`${bitgetStrategyFifoGaps?.support_package.available_files_count ?? 0}/${bitgetStrategyFifoGaps?.support_package.expected_files_count ?? 6}`} />
                <Metric title="Strategien belegt" value={`${bitgetStrategyFifoGaps?.support_package.relevant_strategy_matches_count ?? 0}/${activeBitgetStrategyGroups.length}`} />
                <Metric title="Bot-Fills mit ID" value={String(bitgetStrategyFifoGaps?.support_package.strategy_linked_fill_rows_count ?? 0)} />
                <Metric title="Blockpit Konflikte" value={String(bitgetStrategyFifoGaps?.blockpit_classification_conflict_count ?? 0)} />
                <Metric title="API Historie" value={`${bitgetStrategyFifoGaps?.api_history_boundary.retention_days ?? 90} Tage`} />
              </div>
            </div>
            <TablePanel
              title="Settlement-Ketten"
              rows={activeBitgetStrategyGroups.map((group) => ({
                datum: formatDateTime(group.settlement_at),
                asset: group.asset,
                settlement: formatQuantity(group.settlement_quantity),
                principal_belegt: formatQuantity(group.supported_principal_carried_quantity),
                basis_offen: formatQuantity(group.strategy_quantity_without_cost_basis),
                abgaenge: group.linked_disposals_count,
                zugeordnet: formatQuantity(group.allocated_missing_quantity),
                rest: formatQuantity(group.residual_quantity),
                strategie: group.support_strategy_match
                  ? `${group.support_strategy_match.strategy_type} · ${group.support_strategy_match.strategy_id}`
                  : "-",
                export_gewinn: group.support_strategy_match
                  ? `${formatQuantity(group.support_strategy_match.total_gains)} USDT`
                  : "-",
                blockpit: group.blockpit_reference.classification_conflict
                  ? `${group.blockpit_reference.label ?? "-"} verworfen`
                  : group.blockpit_reference.label ?? "-",
                beleg: `${group.settlement_filename ?? "-"}:${group.settlement_row_number ?? "-"}`,
              }))}
              compact
            />
            <TablePanel
              title="Zugeordnete FIFO-Abgaenge"
              rows={activeBitgetStrategyDisposals.map((disposal) => ({
                datum: formatDateTime(disposal.event_time),
                asset: disposal.asset,
                verkauf: formatQuantity(disposal.disposal_quantity),
                lot_belegt: formatQuantity(disposal.matched_wallet_lot_quantity),
                settlement_belegt: formatQuantity(disposal.allocated_strategy_gap_quantity),
                offen: disposal.quantity_fully_allocated
                  ? "0"
                  : formatQuantity(disposal.missing_wallet_lot_quantity),
                order: disposal.order_number ?? "-",
                beleg: `${disposal.source_filename ?? "-"}:${disposal.source_row_number ?? "-"}`,
              }))}
              footer={bitgetStrategyFifoGaps?.api_history_boundary.finding}
              compact
            />
            {activeBitgetReconstructionGroups.length > 0 ? (
              <div className="fifoReconstructionBand">
                <div className="panelToolbar">
                  <strong>Konservative Basis-Rekonstruktionsakte</strong>
                  <span className={`statusPill ${bitgetReconstructionReady ? "warning" : "blocked"}`}>
                    {bitgetReconstructionReady ? "Pruefakte bereit" : "Referenzbeleg offen"}
                  </span>
                </div>
                <p>
                  Die Akte grenzt Erwerbszeitfenster und anteilige Verkaufserloese ein.
                  Nullbasis und Settlement-Zeitwert sind nur Sensitivitaeten. Sie aendern keine
                  Lots, keine FIFO und keinen Steuerwert; die fehlenden Bot-Fills bleiben sichtbar.
                </p>
                <div className="fifoProofMetrics">
                  <Metric title="Abgaenge" value={String(activeBitgetReconstructionDisposals.length)} />
                  <Metric
                    title="Verkaufserloese"
                    value={`${formatCurrency(activeBitgetReconstructionGroups.reduce(
                      (total, group) => total + parseNumber(group.attributable_disposal_proceeds_eur),
                      0
                    ))} EUR`}
                  />
                  <Metric
                    title="Nullbasis-Sensitivitaet"
                    value={`${formatCurrency(activeBitgetReconstructionGroups.reduce(
                      (total, group) => total + parseNumber(group.zero_basis_gain_sensitivity_eur),
                      0
                    ))} EUR`}
                  />
                  <Metric title="Basis-Obergrenze" value="nicht belegbar" />
                </div>
                <TablePanel
                  title="Rekonstruktionskorridor je Strategy"
                  rows={activeBitgetReconstructionGroups.map((group) => ({
                    asset: group.asset,
                    strategie: group.strategy_id,
                    erwerbsfenster: `${formatDateTime(group.acquisition_window_start)} bis ${formatDateTime(group.acquisition_window_end)}`,
                    menge: formatQuantity(group.allocated_missing_quantity),
                    erloes_eur: `${formatCurrency(group.attributable_disposal_proceeds_eur)} EUR`,
                    basis_floor_eur: `${formatCurrency(group.documented_cost_basis_floor_eur)} EUR`,
                    settlement_proxy_eur: `${formatCurrency(group.allocated_settlement_value_proxy_eur)} EUR`,
                    proxy_gv_eur: `${formatCurrency(group.settlement_value_proxy_gain_sensitivity_eur)} EUR`,
                    haltefrist: group.linked_disposals.every(
                      (row) => row.holding_period_certainty === "definitely_within_one_year"
                    )
                      ? "innerhalb 1 Jahr"
                      : group.linked_disposals.every(
                          (row) => row.holding_period_certainty === "definitely_over_one_year"
                        )
                        ? "ueber 1 Jahr"
                        : "zeitlich offen",
                    steuerwirkung: "keine",
                  }))}
                  footer="Settlement-Proxy ist kein Anschaffungskostenbeleg und darf erst nach dokumentierter Methodenentscheidung verwendet werden."
                  compact
                />
              </div>
            ) : null}
            {activeBitgetReconstructionGroups.length > 0 ? (
              <BitgetStrategyBasisDecisionPanel
                report={bitgetStrategyBasisDecision}
                reconstruction={bitgetStrategyReconstruction}
                loading={bitgetBasisDecisionLoading}
                onSave={onSaveBitgetBasisDecision}
              />
            ) : null}
            <div className="reportActionBand compactActions">
              {activeBitgetReconstructionGroups.length > 0 ? (
                <button type="button" onClick={() => onDownload("/api/v1/tax/wallet-fifo/bitget-strategy-review.html")}>
                  <ExternalLink size={16} />
                  Fachakte oeffnen
                </button>
              ) : null}
              {activeBitgetReconstructionGroups.length > 0 ? (
                <button type="button" onClick={() => onDownload("/api/v1/tax/wallet-fifo/bitget-strategy-review-package.zip")}>
                  <Archive size={16} />
                  Pruefpaket ZIP
                </button>
              ) : null}
              <button type="button" onClick={() => onDownload("/api/v1/tax/wallet-fifo/bitget-strategy-gaps.csv")}>
                <FileDown size={16} />
                Mengenbeleg CSV
              </button>
              {activeBitgetReconstructionGroups.length > 0 ? (
                <button type="button" onClick={() => onDownload("/api/v1/tax/wallet-fifo/bitget-strategy-reconstruction.csv")}>
                  <FileDown size={16} />
                  Rekonstruktionsakte CSV
                </button>
              ) : null}
              <button type="button" onClick={() => onDownload("/api/v1/tax/wallet-fifo/bitget-support-package.zip")}>
                <Archive size={16} />
                Bitget Supportpaket
              </button>
            </div>
          </div>
        ) : null}
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
              <Metric title="Service-Swaps" value={`${readyServiceSwapCount}/${serviceSwapClosureItems.length}`} />
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
              {serviceSwapClosureItems.length > 0 ? (
                <button type="button" onClick={() => onDownload("/api/v1/tax/service-swap-mappings")}>
                  <Route size={16} />
                  Service-Swap Beleg
                </button>
              ) : null}
            </div>
          </div>
        ) : null}
        {activeYearValue === "2022" && pionexHntReconciliation ? (
          <div className={`panelInlineBlock ${pionexReconciliationTone}`}>
            <div className="panelToolbar">
              <strong>Pionex HNT Bestandsnachweis</strong>
              <span className={`statusPill ${pionexReconciliationTone}`}>
                {pionexHntReconciliation.reconciliation_ready
                  ? "konservativ belegt"
                  : pionexHntReconciliation.preflight_ready
                    ? "Migration vorbereitet"
                    : "Pruefung offen"}
              </span>
            </div>
            <div className="portfolioSummaryStrip">
              <Metric title="Teilfills erhalten" value={String(pionexHntReconciliation.canceled_partial_fills_count ?? 0)} />
              <Metric title="Rekonstruiert HNT" value={formatQuantity(pionexHntReconciliation.adjustment_quantity)} />
              <Metric title="Kostenbasis" value={formatCurrency(pionexHntReconciliation.adjustment_cost_basis_eur)} />
              <Metric title="Mindestbestand" value={formatQuantity(pionexHntReconciliation.balance_min_quantity)} />
              <Metric title="Restbestand HNT" value={formatQuantity(pionexHntReconciliation.balance_final_quantity)} />
              <Metric title="Historische API-Zeilen" value={String(pionexHntReconciliation.historical_api_rows ?? 0)} />
            </div>
            <p className="panelHint">
              Die sechs ausgefuehrten Teilfills bleiben trotz spaeterem Orderstatus CANCELED erhalten.
              Der historische Mindestbestand von {formatQuantity(pionexHntReconciliation.adjustment_quantity)} HNT
              wird mangels abrufbarem Primaerbeleg mit {formatCurrency(pionexHntReconciliation.adjustment_cost_basis_eur)}
              Kostenbasis angesetzt. Er wird weder als Reward noch als externer Deposit behauptet.
            </p>
            <div className="reportActionBand compactActions">
              <button type="button" onClick={() => onDownload("/api/v1/tax/pionex-hnt-reconciliation")}>
                <ClipboardCheck size={16} />
                Pionex HNT Beleg
              </button>
              <button type="button" onClick={() => onDownload("/api/v1/export/tax-years/2022/evidence-package.zip")}>
                <PackageCheck size={16} />
                Jahres-Belegpaket
              </button>
            </div>
          </div>
        ) : null}
        {activeYearValue === "2022" && fairspotStakingReconciliation ? (
          <div className={`panelInlineBlock ${fairspotReconciliationTone}`}>
            <div className="panelToolbar">
              <strong>Fairspot HNT Principal und Reward</strong>
              <span className={`statusPill ${fairspotReconciliationTone}`}>
                {fairspotStakingReconciliation.strict_ready ? "vollstaendig belegt" : "Review offen"}
              </span>
            </div>
            <div className="portfolioSummaryStrip">
              <Metric title="Principal gesendet" value={`${formatQuantity(fairspotStakingReconciliation.principal_outbound_quantity)} HNT`} />
              <Metric title="Principal erhalten" value={`${formatQuantity(fairspotStakingReconciliation.principal_return_quantity)} HNT`} />
              <Metric title="Reward" value={`${formatQuantity(fairspotStakingReconciliation.reward_quantity)} HNT`} />
              <Metric title="Reward-Zuflusswert" value={`${formatCurrency(fairspotStakingReconciliation.reward_income_eur)} EUR`} />
              <Metric title="Ausgaenge / Ruecklaeufe" value={`${fairspotStakingReconciliation.outbound_events_count} / ${fairspotStakingReconciliation.return_events_count}`} />
            </div>
            <div className="proofRouteLine">
              <code title={fairspotStakingReconciliation.main_wallet}>{shortAccount(fairspotStakingReconciliation.main_wallet)}</code>
              <ArrowRight size={15} />
              <code title={fairspotStakingReconciliation.staking_wallet}>{shortAccount(fairspotStakingReconciliation.staking_wallet)}</code>
              <ArrowRight size={15} />
              <code title={fairspotStakingReconciliation.main_wallet}>{shortAccount(fairspotStakingReconciliation.main_wallet)}</code>
            </div>
            <div className="reportActionBand compactActions">
              <button type="button" onClick={() => onDownload("/api/v1/export/tax-years/2022/evidence-package.zip")}>
                <PackageCheck size={16} />
                Jahres-Belegpaket 2022
              </button>
            </div>
          </div>
        ) : null}
        {activeYearValue === "2026" && moonpayReceipts ? (
          <div className={`panelInlineBlock ${moonpayReceiptTone}`}>
            <div className="panelToolbar">
              <strong>MoonPay EUR-Anschaffungen</strong>
              <span className={`statusPill ${moonpayReceiptTone}`}>
                {moonpayReceipts.strict_ready
                  ? `${moonpayReceipts.matched_trade_rows_count}/${moonpayReceipts.completed_buy_rows_count} belegt`
                  : `${moonpayReceipts.unmatched_trade_rows_count} Zuordnung(en) offen`}
              </span>
            </div>
            <div className="portfolioSummaryStrip">
              <Metric title="Brutto vom Bankkonto" value={`${formatCurrency(moonpayReceipts.total_bank_debits_eur)} EUR`} />
              <Metric title="FIFO-Kostenbasis" value={`${formatCurrency(moonpayReceipts.total_receipt_cost_basis_eur)} EUR`} />
              <Metric title="MoonPay-Basisbetrag" value={`${formatCurrency(moonpayReceipts.total_base_payment_amount_eur)} EUR`} />
              <Metric title="Gebuehren addiert" value={`${formatCurrency(moonpayReceipts.total_fee_components_eur)} EUR`} />
              <Metric title="Bankabgleich" value={`${moonpayReceipts.bank_debits_matched_count}/${moonpayReceipts.bank_debits_count}`} />
              <Metric title="On-chain gebunden" value={`${moonpayReceipts.ready_count}/${moonpayReceipts.candidates_count}`} />
              <Metric title="Nicht zugeordnet" value={String(moonpayReceipts.unmatched_trade_rows_count)} />
              <Metric title="CAMT-Dateien" value={String(moonpayReceipts.bank_camt_files_count)} />
            </div>
            <TablePanel
              title="Fiat-Onramp mit exakter FIFO-Kostenbasis"
              rows={moonpayReceipts.items.map((item) => ({
                status: item.strict_ready ? "belegt" : "pruefen",
                zeit_utc: formatDateTime(item.event_time),
                asset: item.asset,
                menge: formatQuantity(item.received_quantity),
                brutto_eur: formatCurrency(item.gross_payment_amount_eur),
                bank_eur: formatCurrency(item.bank_debit_amount_eur),
                bank_buchung: item.bank_booking_date ?? "-",
                basis_eur: formatCurrency(item.payment_amount_eur),
                gebuehr_eur: formatCurrency(item.fee_eur),
                chain_delta_s: item.payment_to_chain_seconds ?? "-",
                trade: shortAccount(item.moonpay_trade_id ?? "-"),
                txid: shortAccount(item.tx_id)
              }))}
              footer={moonpayReceipts.methodology}
              compact
            />
            <div className="reportActionBand compactActions">
              <button type="button" onClick={() => onDownload("/api/v1/tax/moonpay-receipts/trade-history.csv")}>
                <ReceiptText size={16} />
                MoonPay Original-CSV
              </button>
              <button type="button" onClick={() => onDownload("/api/v1/export/tax-years/2026/evidence-package.zip")}>
                <PackageCheck size={16} />
                Jahres-Belegpaket 2026
              </button>
            </div>
          </div>
        ) : null}
        {activeYearValue === "2026" && solanaStakingPositionReconciliation ? (
          <div className={`panelInlineBlock ${solanaStakingReconciliationTone}`}>
            <div className="panelToolbar">
              <strong>Solana Staking-Position: {solanaStakingPositionReconciliation.asset}</strong>
              <span className={`statusPill ${solanaStakingReconciliationTone}`}>
                {solanaStakingPositionReconciliation.strict_ready ? "FIFO und Reward belegt" : "Review offen"}
              </span>
            </div>
            <div className="portfolioSummaryStrip">
              <Metric title="Principal" value={`${formatQuantity(solanaStakingPositionReconciliation.principal_quantity)} ${solanaStakingPositionReconciliation.asset}`} />
              <Metric title="Ruecklauf gesamt" value={`${formatQuantity(solanaStakingPositionReconciliation.received_quantity)} ${solanaStakingPositionReconciliation.asset}`} />
              <Metric title="Reward" value={`${formatQuantity(solanaStakingPositionReconciliation.reward_quantity)} ${solanaStakingPositionReconciliation.asset}`} />
              <Metric title="Reward-Zuflusswert" value={`${formatCurrency(solanaStakingPositionReconciliation.reward_income_eur)} EUR`} />
              <Metric title="Fortgefuehrte Kostenbasis" value={`${formatCurrency(solanaStakingPositionReconciliation.wallet_fifo_carried_cost_basis_eur)} EUR`} />
              <Metric title="FIFO-Lots" value={String(solanaStakingPositionReconciliation.wallet_fifo_lots_moved)} />
              <Metric title="SOL Rent-Ruecklauf" value={`${formatQuantity(solanaStakingPositionReconciliation.native_settlement_quantity)} SOL`} />
            </div>
            <div className="proofRouteLine">
              <code title={solanaStakingPositionReconciliation.wallet}>{shortAccount(solanaStakingPositionReconciliation.wallet)}</code>
              <ArrowRight size={15} />
              <code title={solanaStakingPositionReconciliation.program_id}>{shortAccount(solanaStakingPositionReconciliation.program_id)}</code>
              <ArrowRight size={15} />
              <code title={solanaStakingPositionReconciliation.wallet}>{shortAccount(solanaStakingPositionReconciliation.wallet)}</code>
            </div>
            <div className="reportActionBand compactActions">
              <button type="button" onClick={() => onDownload("/api/v1/export/tax-years/2026/evidence-package.zip")}>
                <PackageCheck size={16} />
                Jahres-Belegpaket 2026
              </button>
            </div>
          </div>
        ) : null}
        {activeCrossCexRecords.length > 0 ? (
          <div className={`panelInlineBlock ${crossCexEvidenceTone}`}>
            <div className="panelToolbar">
              <strong>Cross-CEX Transferketten</strong>
              <span className={`statusPill ${crossCexEvidenceTone}`}>
                {activeCrossCexRecords.every((record) => record.ready)
                  ? `${activeCrossCexRecords.length}/${activeCrossCexRecords.length} belegt`
                  : `${activeCrossCexRecords.filter((record) => record.ready).length}/${activeCrossCexRecords.length} belegt`}
              </span>
            </div>
            <TablePanel
              title="Steuerneutrale Depotwechsel mit fortgefuehrter FIFO"
              rows={activeCrossCexRecords.map((record) => ({
                status: record.ready ? "belegt" : "pruefen",
                asset: record.asset,
                menge: formatQuantity(record.quantity),
                gebuehr: formatQuantity(record.fee_quantity),
                route: `${record.source_id} -> ${record.target_source_id}`,
                lots: record.lots_moved,
                basis_eur: formatCurrency(record.carried_cost_basis_eur),
                zeit: formatDateTime(record.target_event_time),
                txid: shortAccount(record.tx_id)
              }))}
              footer={crossCexTransferEvidence?.methodology}
              compact
            />
            <div className="reportActionBand compactActions">
              <button type="button" onClick={() => onDownload(`/api/v1/export/tax-years/${activeYearValue}/evidence-package.zip`)}>
                <PackageCheck size={16} />
                Jahres-Belegpaket {activeYearValue}
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
        {acquisitionCostReviewTransfers.length > 0 ? (
          <TablePanel
            title="Offene Anschaffungs- und Reward-Belege"
            rows={acquisitionCostReviewTransfers.map((row) => ({
              zeit_utc: formatDateTime(row.event_time),
              asset: row.asset,
              menge: formatQuantity(row.quantity),
              vorlaeufige_basis_eur: formatCurrency(row.carried_cost_basis_eur),
              quelle: row.source_pool_id,
              ziel: row.target_pool_id,
              status: row.status,
              txid: row.tx_id,
              benoetigt: String(row.status ?? "").includes("reward_component_review")
                ? "Staking-Abrechnung und Reward-Wert bestaetigen"
                : "MoonPay-/Apple-Pay-Beleg mit EUR-Betrag und Gebuehr"
            }))}
            footer="Marktkurse sind nur vorlaeufig. Fuer die Kostenbasis gilt der tatsaechliche EUR-Aufwand inklusive belegter Gebuehren."
            compact
          />
        ) : null}
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
          <Metric title="Rewards eintragen" value={`${formatCurrency(taxYearFilingSummary?.rewards_mining_staking_income_eur)} EUR`} />
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
                  <button type="button" onClick={() => onDownload(humanReadableTaxEndpoint(String(line.evidence_ref)))} title={String(line.evidence_ref)}>
                    <FileDown size={16} />
                    Beleg
                  </button>
                ) : null}
              </div>
            </div>
          ))}
        </div>
        <div className="declarationActionBand">
          <button type="button" onClick={() => onDownload(taxYearFilingSummaryHtmlPath(activeYearValue))}>
            <ReceiptText size={16} />
            Eingabehilfe Website
          </button>
          <button type="button" onClick={() => onDownload(`/api/v1/export/tax-years/${activeYearValue}/filing-checklist.csv`)}>
            <FileDown size={16} />
            Checkliste CSV
          </button>
          <button type="button" onClick={() => onDownload(taxYearEvidenceHtmlPath(activeYearValue))}>
            <FileDown size={16} />
            Belegkarte Website
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
                onClick: (row) => onDownload(humanReadableTaxEndpoint(String(row.beleg ?? "")))
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
              onClick: (row) => onDownload(humanReadableTaxEndpoint(String(row.beleg ?? "")))
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
                onClick: (row) => onDownload(humanReadableTaxEndpoint(String(row.beleg ?? "")))
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
                onClick: (row) => onDownload(humanReadableTaxEndpoint(String(row.beleg ?? "")))
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
                onClick={() => onDownload(humanReadableTaxEndpoint(String(item.endpoint)))}
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
          <Metric title="Rewards eintragen" value={`${formatCurrency(activePaymentRow?.rewards_mining_staking_income_eur)} EUR`} />
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
            <StatusRow label="Rewards eintragen" value={`${formatCurrency(selectedYear?.rewards_income_eur)} EUR`} />
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
            <Metric title="Rewards eintragen" value={`${formatCurrency(taxDeclarationGuide?.rewards_income_eur)} EUR`} />
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
              onClick: (row) => onDownload(humanReadableTaxEndpoint(String(row.endpoint ?? "")))
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
            <Metric title="Eintragen" value={`${formatCurrency(taxIncomeGuide?.declaration_income_eur ?? taxIncomeGuide?.reward_income_eur)} EUR`} />
            <Metric title="Nur pruefen" value={`${formatCurrency(taxIncomeGuide?.review_only_income_eur ?? taxIncomeGuide?.generic_income_eur)} EUR`} />
            <Metric title="Reward-Events" value={String(taxIncomeGuide?.taxable_reward_events_count ?? 0)} />
            <Metric title="Review-Events" value={String(taxIncomeGuide?.review_only_events_count ?? 0)} />
            <Metric title="Ohne Preis" value={String(taxIncomeGuide?.missing_value_count ?? 0)} />
            <Metric title="Ignoriert <=0" value={String(taxIncomeGuide?.ignored_non_positive_count ?? 0)} />
          </div>
          <TablePanel
            title="Einzutragende Rewards / Mining"
            rows={declarationIncomeAssets}
            footer="Diese Summe fliesst als einzutragende Rewards/Mining/Staking in die Eingabehilfe. Aktuell eng auf HNT/IOT/MOBILE Reward-/Mining-Events begrenzt."
            compact
          />
          <TablePanel
            title="Nur pruefen, nicht automatisch eintragen"
            rows={reviewOnlyIncomeAssets.slice(0, 30)}
            footer={`Diese Werte sind Review-Kontext und werden nicht blind zur Reward-Summe addiert. Fehlende Assets: ${(taxIncomeGuide?.missing_assets ?? []).join(", ") || "keine"} | ${taxIncomeGuide?.methodology ?? ""}`}
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
            <strong>Reward-Ursprung und Verwertung HNT / IOT / MOBILE</strong>
            <span className={`statusPill ${activeBusinessInventoryRows.length === 0 || (activeBusinessInventoryTotals.potentialLines === 0 && activeBusinessInventoryTotals.unresolvedLines === 0) ? "ok" : "blocked"}`}>
              {activeBusinessInventoryRows.length === 0
                ? "keine Zeilen"
                : activeBusinessInventoryTotals.potentialLines === 0 && activeBusinessInventoryTotals.unresolvedLines === 0
                  ? "Sphaere geklaert"
                  : "Sphaere pruefen"}
            </span>
          </div>
          <div className="portfolioSummaryStrip">
            <Metric title="Reward Einnahme" value={`${formatCurrency(activeRewardTradingTotals.reward)} EUR`} />
            <Metric title="Aktuelle FIFO bis 365 T." value={`${formatCurrency(activeRewardTradingTotals.taxableTrade)} EUR`} />
            <Metric title="Potenziell betrieblich" value={String(activeBusinessInventoryTotals.potentialLines)} />
            <Metric title="Ursprung offen" value={String(activeBusinessInventoryTotals.unresolvedLines)} />
          </div>
          <TablePanel
            title={`Aktuelle FIFO-Berechnung ${activeYearValue}`}
            rows={activeRewardTradingRows.map((row) => ({
              asset: row.asset,
              reward_einnahme_eur: formatCurrency(row.reward_income_eur),
              reward_menge: row.reward_quantity,
              reward_events: row.reward_events_count,
              fifo_bis_365_tage_eur: formatCurrency(row.trade_taxable_gain_loss_eur),
              fifo_ueber_365_tage_eur: formatCurrency(row.trade_tax_free_gain_loss_eur),
              fifo_zeilen: Number(row.trade_taxable_lines_count ?? 0) + Number(row.trade_tax_free_lines_count ?? 0),
              einordnung: row.tax_note
            }))}
            footer={taxRewardTradingSeparation?.methodology ?? "Reward-/Handels-Trennung wird geladen."}
            compact
          />
          <TablePanel
            title={`Ursprungssphaere der Verwertungen ${activeYearValue}`}
            rows={activeBusinessInventoryRows.map((row) => ({
              asset: row.asset,
              origin_source: row.origin_source,
              origin_event_type: row.origin_event_type,
              origin_account: row.origin_account,
              tax_lines: row.tax_lines_count,
              anschaffung_eur: formatCurrency(row.acquisition_cost_eur),
              veraeusserung_eur: formatCurrency(row.disposal_proceeds_eur),
              gewinn_verlust_eur: formatCurrency(row.gain_loss_eur),
              classification: row.classification
            }))}
            footer={taxBusinessRewardInventoryReview?.methodology ?? "Reward-Ursprungslot-Audit wird geladen."}
            compact
          />
        </div>
        <TablePanel
          title="Review-only Income Event Preview"
          rows={reviewOnlyIncomeEvents.slice(0, 80)}
          footer="Diese Ereignisse sind nicht automatisch als steuerpflichtige Reward-/Mining-Summe eingetragen. Volle Nachweise bleiben in Canonical Events und Exporten."
        />
      </section>

      <section className="panel">
        <div className="panelToolbar">
          <strong>Krypto-zu-Krypto-Bewertung {activeYearValue}</strong>
          <span className={`statusPill ${taxCryptoSwapValuationReview?.strict_ready ? "ok" : "blocked"}`}>
            {taxCryptoSwapValuationReview?.strict_ready ? "BMF-Rangfolge erfuellt" : "Preisrangfolge pruefen"}
          </span>
        </div>
        <div className="portfolioSummaryStrip">
          <Metric title="Tauschvorgaenge" value={String(taxCryptoSwapValuationReview?.candidates_count ?? 0)} />
          <Metric title="Rangfolge abweichend" value={String(taxCryptoSwapValuationReview?.policy_mismatch_count ?? 0)} />
          <Metric title="Materialdelta" value={String(taxCryptoSwapValuationReview?.material_delta_count ?? 0)} />
          <Metric title="Preis-Fallback Review" value={String(taxCryptoSwapValuationReview?.received_price_fallback_review_count ?? 0)} />
          <Metric title="Delta saldiert" value={`${formatCurrency(taxCryptoSwapValuationReview?.signed_value_delta_eur)} EUR`} />
          <Metric title="Delta absolut" value={`${formatCurrency(taxCryptoSwapValuationReview?.absolute_value_delta_eur)} EUR`} />
        </div>
        <TablePanel
          title={`Groesste direkte Bewertungsdeltas ${activeYearValue}`}
          rows={(taxCryptoSwapValuationReview?.rows ?? []).map((row) => ({
            zeitpunkt: formatDateTime(row.event_time),
            quelle: row.source,
            erhalten: `${formatQuantity(row.received_quantity)} ${String(row.received_asset ?? "")}`,
            hingegeben: `${formatQuantity(row.given_quantity)} ${String(row.given_asset ?? "")}`,
            aktuell_eur: formatCurrency(row.current_value_eur),
            bmf_preview_eur: formatCurrency(row.bmf_preview_value_eur),
            delta_eur: formatCurrency(row.value_delta_eur),
            status: row.status
          }))}
          footer={`${taxCryptoSwapValuationReview?.bmf_preview_policy ?? ""} ${taxCryptoSwapValuationReview?.methodology ?? "Bewertungs-Delta wird geladen."}`}
          compact
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

      {taxViewMode === "expert" ? (
      <section className="cockpitDataGrid">
        <div className="panel">
          <div className="panelToolbar">
            <strong>Gewinn-Belegcheck {activeYearValue}</strong>
            <span>{formatDateTime(taxYearGainEvidenceReview?.generated_at)}</span>
          </div>
          <div className="portfolioSummaryStrip">
            <Metric title="Gepruefter G/V" value={`${formatCurrency(taxYearGainEvidenceReview?.reviewed_gain_loss_eur)} EUR`} />
            <Metric title="High" value={String(taxYearGainEvidenceReview?.high_risk_lines_count ?? 0)} />
            <Metric title="Review" value={String(taxYearGainEvidenceReview?.review_lines_count ?? 0)} />
            <Metric title="OK" value={String(taxYearGainEvidenceReview?.ok_lines_count ?? 0)} />
            <Metric title="Preisdelta-Zeilen" value={String(taxYearGainEvidenceReview?.price_delta_lines_count ?? 0)} />
            <Metric title="Event abgeglichen" value={String(taxYearGainEvidenceReview?.event_level_reconciled_lines_count ?? 0)} />
            <Metric title="Erwerb abgeglichen" value={String(taxYearGainEvidenceReview?.acquisition_event_level_reconciled_lines_count ?? 0)} />
            <Metric title="Delta-Artefakt" value={`${formatCurrency(taxYearGainEvidenceReview?.material_price_delta_eur)} EUR`} />
            <Metric title="Delta offen" value={`${formatCurrency(taxYearGainEvidenceReview?.open_price_delta_eur)} EUR`} />
          </div>
          <TablePanel
            title="Preisdelta-Gruppen"
            rows={(taxYearGainEvidenceReview?.delta_groups ?? []).map((group) => ({
              risiko: group.risk_level,
              ursache: group.classification,
              zeilen: group.lines_count,
              gv_eur: formatCurrency(group.gain_loss_eur),
              delta_eur: formatCurrency(group.absolute_delta_eur),
              offen_eur: formatCurrency(group.open_delta_eur),
              max_delta_pct: formatPercent(group.max_delta_pct),
              assets: Array.isArray(group.assets) ? group.assets.join(", ") : group.assets,
              quote_assets: Array.isArray(group.quote_assets) ? group.quote_assets.join(", ") : group.quote_assets,
              quellen: Array.isArray(group.sources) ? group.sources.join(", ") : group.sources,
              erklaerung: group.explanation,
              aktion: group.recommended_action
            }))}
            footer="Gruppen fassen Preisabweichungen zusammen, damit USD/EUR-FX, DEX-Quote, Transferkontext und Normalizer-Themen getrennt pruefbar sind."
            compact
          />
          <div className="portfolioSummaryStrip">
            <Metric title="Delta-Drilldown" value={String(taxYearGainEvidencePriceDeltas?.lines_count ?? 0)} />
            <Metric title="Split-Line Review" value={String(taxYearGainEvidencePriceDeltas?.split_line_review_count ?? 0)} />
            <Metric title="Event abgeglichen" value={String(taxYearGainEvidencePriceDeltas?.event_level_reconciled_count ?? 0)} />
            <Metric title="Event Review" value={String(taxYearGainEvidencePriceDeltas?.event_level_review_count ?? 0)} />
            <Metric title="Erwerb dominiert" value={String(taxYearGainEvidencePriceDeltas?.dominant_acquisition_count ?? 0)} />
            <Metric title="Verkauf dominiert" value={String(taxYearGainEvidencePriceDeltas?.dominant_disposal_count ?? 0)} />
            <Metric title="Beide Seiten" value={String(taxYearGainEvidencePriceDeltas?.dominant_both_count ?? 0)} />
          </div>
          <TablePanel
            title="Preisdelta Root-Causes"
            rows={Object.entries(taxYearGainEvidencePriceDeltas?.root_cause_counts ?? {}).map(([rootCause, count]) => ({
              root_cause: rootCause,
              zeilen: count
            }))}
            footer={taxYearGainEvidencePriceDeltas?.methodology ?? ""}
            compact
          />
          <TablePanel
            title="Groesste Preisdelta-Zeilen"
            rows={(taxYearGainEvidencePriceDeltas?.lines ?? []).slice(0, 30).map((line) => ({
              root_cause: line.root_cause,
              dominant: line.dominant_side,
              asset: line.asset,
              gv_eur: formatCurrency(line.gain_loss_eur),
              delta_eur: formatCurrency(line.absolute_delta_eur),
              erwerb_delta: formatCurrency(line.acquisition_delta_eur),
              erwerb_pct: formatPercent(line.acquisition_delta_pct),
              erwerb_split: line.acquisition_event_split_count,
              erwerb_diag: line.acquisition_side_diagnosis,
              verkauf_delta: formatCurrency(line.disposal_delta_eur),
              verkauf_pct: formatPercent(line.disposal_delta_pct),
              verkauf_split: line.disposal_event_split_count,
              verkauf_diag: line.disposal_side_diagnosis,
              event_status: line.event_level_status ?? "-",
              event_delta_eur: line.event_level_delta_eur === null || line.event_level_delta_eur === undefined ? "-" : formatCurrency(line.event_level_delta_eur),
              erwerb_event_status: line.acquisition_event_level_status ?? "-",
              erwerb_event_delta: line.acquisition_event_level_delta_eur === null || line.acquisition_event_level_delta_eur === undefined ? "-" : formatCurrency(line.acquisition_event_level_delta_eur),
              erklaerung: line.explanation,
              aktion: line.recommended_action,
              drilldown: line.asset_fifo_drilldown_endpoint
            }))}
            footer={(taxYearGainEvidencePriceDeltas?.caveats ?? []).join(" ")}
            compact
          />
          <div className="portfolioSummaryStrip">
            <Metric title="Event-Level OK" value={String(taxYearGainEvidenceEventDeltas?.event_level_ok_count ?? 0)} />
            <Metric title="Event Review" value={String(taxYearGainEvidenceEventDeltas?.event_level_review_count ?? 0)} />
            <Metric title="Preis fehlt" value={String(taxYearGainEvidenceEventDeltas?.missing_price_count ?? 0)} />
            <Metric title="Event-Delta" value={`${formatCurrency(taxYearGainEvidenceEventDeltas?.event_delta_eur)} EUR`} />
            <Metric title="Teilzeilen-Delta" value={`${formatCurrency(taxYearGainEvidenceEventDeltas?.split_line_absolute_delta_eur)} EUR`} />
          </div>
          <TablePanel
            title="Event-Level Preisdelta-Plausibilisierung"
            rows={(taxYearGainEvidenceEventDeltas?.lines ?? []).slice(0, 30).map((line) => ({
              status: line.status,
              zeit: formatDateTime(line.disposed_at),
              quelle: line.source,
              typ: line.event_type,
              assets: Array.isArray(line.assets) ? line.assets.join(", ") : line.assets,
              tax_lines: line.tax_line_count,
              steuerpfl_menge: formatQuantity(line.taxable_disposed_quantity),
              event_menge: line.total_event_disposed_quantity === null || line.total_event_disposed_quantity === undefined ? "-" : formatQuantity(line.total_event_disposed_quantity),
              steuerpfl_anteil: line.taxable_event_fraction === null || line.taxable_event_fraction === undefined ? "-" : formatPercent(Number(line.taxable_event_fraction) * 100),
              quote: `${line.quote_quantity ?? "-"} ${line.quote_asset ?? ""}`.trim(),
              event_gesamtwert: line.event_total_proceeds_eur === null || line.event_total_proceeds_eur === undefined ? "-" : formatCurrency(line.event_total_proceeds_eur),
              erloes_eur: formatCurrency(line.actual_proceeds_eur),
              erwartet_eur: line.expected_proceeds_eur === null || line.expected_proceeds_eur === undefined ? "-" : formatCurrency(line.expected_proceeds_eur),
              event_delta_eur: line.event_delta_eur === null || line.event_delta_eur === undefined ? "-" : formatCurrency(line.event_delta_eur),
              event_delta_pct: line.event_delta_pct === null || line.event_delta_pct === undefined ? "-" : formatPercent(line.event_delta_pct),
              teilzeilen_delta: formatCurrency(line.split_line_absolute_delta_eur),
              split_zeilen: line.split_line_count,
              preisquelle: line.price_source ?? "-",
              erklaerung: line.explanation,
              aktion: line.recommended_action
            }))}
            footer={(taxYearGainEvidenceEventDeltas?.caveats ?? []).join(" ") || taxYearGainEvidenceEventDeltas?.methodology || ""}
            compact
          />
          <div className="portfolioSummaryStrip">
            <Metric title="Erwerbs-Event OK" value={String(taxYearGainEvidenceAcquisitionEventDeltas?.event_level_ok_count ?? 0)} />
            <Metric title="Erwerbs-Review" value={String(taxYearGainEvidenceAcquisitionEventDeltas?.event_level_review_count ?? 0)} />
            <Metric title="Preis fehlt" value={String(taxYearGainEvidenceAcquisitionEventDeltas?.missing_price_count ?? 0)} />
            <Metric title="Erwerbs-Delta" value={`${formatCurrency(taxYearGainEvidenceAcquisitionEventDeltas?.event_delta_eur)} EUR`} />
          </div>
          <TablePanel
            title="Erwerbs-Event Preisdelta-Plausibilisierung"
            rows={(taxYearGainEvidenceAcquisitionEventDeltas?.lines ?? []).slice(0, 30).map((line) => ({
              status: line.status,
              zeit: formatDateTime(line.acquired_at),
              quelle: line.source,
              typ: line.event_type,
              assets: Array.isArray(line.assets) ? line.assets.join(", ") : line.assets,
              tax_lines: line.tax_line_count,
              steuerpfl_menge: formatQuantity(line.taxable_consumed_quantity),
              event_menge: line.total_event_acquired_quantity === null || line.total_event_acquired_quantity === undefined ? "-" : formatQuantity(line.total_event_acquired_quantity),
              steuerpfl_anteil: line.taxable_event_fraction === null || line.taxable_event_fraction === undefined ? "-" : formatPercent(Number(line.taxable_event_fraction) * 100),
              quote: `${line.quote_quantity ?? "-"} ${line.quote_asset ?? ""}`.trim(),
              event_gesamtwert: line.event_total_cost_eur === null || line.event_total_cost_eur === undefined ? "-" : formatCurrency(line.event_total_cost_eur),
              kosten_eur: formatCurrency(line.actual_cost_eur),
              erwartet_eur: line.expected_cost_eur === null || line.expected_cost_eur === undefined ? "-" : formatCurrency(line.expected_cost_eur),
              event_delta_eur: line.event_delta_eur === null || line.event_delta_eur === undefined ? "-" : formatCurrency(line.event_delta_eur),
              event_delta_pct: line.event_delta_pct === null || line.event_delta_pct === undefined ? "-" : formatPercent(line.event_delta_pct),
              preisquelle: line.price_source ?? "-",
              erklaerung: line.explanation,
              aktion: line.recommended_action
            }))}
            footer={(taxYearGainEvidenceAcquisitionEventDeltas?.caveats ?? []).join(" ") || taxYearGainEvidenceAcquisitionEventDeltas?.methodology || ""}
            compact
          />
          <TablePanel
            title="Top-Gewinnzeilen mit Belegstatus"
            rows={(taxYearGainEvidenceReview?.lines ?? []).slice(0, 30).map((line) => ({
              risiko: line.risk_level,
              asset: line.asset,
              gv_eur: formatCurrency(line.gain_loss_eur),
              kosten_eur: formatCurrency(line.acquisition_cost_eur),
              erloes_eur: formatCurrency(line.disposal_proceeds_eur),
              haltedauer: line.holding_days,
              erwerb_roh: line.acquisition_raw_evidence,
              verkauf_roh: line.disposal_raw_evidence,
              bewertung: line.valuation_path,
              erwerb_preisquelle: line.acquisition_price_source ?? "-",
              erwerb_preisalter_tage: line.acquisition_price_age_days ?? "-",
              erwerb_delta_pct: line.acquisition_cost_delta_pct === null || line.acquisition_cost_delta_pct === undefined ? "-" : formatPercent(line.acquisition_cost_delta_pct),
              verkauf_preisquelle: line.disposal_price_source ?? "-",
              verkauf_preisalter_tage: line.disposal_price_age_days ?? "-",
              verkauf_delta_pct: line.disposal_proceeds_delta_pct === null || line.disposal_proceeds_delta_pct === undefined ? "-" : formatPercent(line.disposal_proceeds_delta_pct),
              delta_klasse: line.delta_classification,
              delta_eur: formatCurrency(line.absolute_price_delta_eur),
              offen_eur: formatCurrency(line.open_price_delta_eur),
              event_status: line.event_level_status ?? "-",
              event_abgeglichen: line.event_level_reconciled ? "ja" : "nein",
              delta_erklaerung: line.delta_explanation,
              delta_aktion: line.delta_recommended_action,
              gruende: Array.isArray(line.review_reasons) ? line.review_reasons.join(", ") : line.review_reasons,
              drilldown: line.asset_fifo_drilldown_endpoint
            }))}
            footer={(taxYearGainEvidenceReview?.caveats ?? []).join(" ") || taxYearGainEvidenceReview?.methodology || ""}
            compact
          />
        </div>
        <pre className="asciiTable" aria-label="Kopierbarer Gewinn-Belegcheck">
          {taxYearGainEvidenceReview?.ascii_table ?? "Gewinn-Belegcheck wird geladen."}
        </pre>
      </section>
      ) : null}

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
      <section className="panel">
        <div className="panelToolbar">
          <div>
            <strong>BMF Gesamtstaging {activeYearValue}</strong>
            <span>{formatDateTime(taxBmfCombinedFifoStaging?.generated_at)}</span>
          </div>
          <div className="buttonRow">
            <span className={`statusPill ${taxBmfCombinedFifoStaging?.status === "ready_for_professional_review" ? "ok" : "blocked"}`}>
              {taxBmfCombinedFifoStaging?.status === "ready_for_professional_review" ? "pruefbereit" : "fachlich blockiert"}
            </span>
            <button
              type="button"
              onClick={onRunBmfCombinedFifoStaging}
              disabled={bmfCombinedFifoStagingLoading}
            >
              <RefreshCcw size={16} />
              <span>{bmfCombinedFifoStagingLoading ? "Berechnet" : "Gesamtlauf starten"}</span>
            </button>
          </div>
        </div>
        <div className="portfolioSummaryStrip">
          <Metric title="Global aktiv" value={`${formatCurrency(activeCombinedActiveGlobal.gain_loss_eur)} EUR`} />
          <Metric title="Global BMF-Preis" value={`${formatCurrency(activeCombinedReceivedGlobal.gain_loss_eur)} EUR`} />
          <Metric title="Wallet aktiv" value={`${formatCurrency(activeCombinedActiveWallet.gain_loss_eur)} EUR`} />
          <Metric title="Wallet + BMF-Preis" value={`${formatCurrency(activeCombinedReceivedWallet.gain_loss_eur)} EUR`} />
          <Metric title="Preisdelta" value={`${formatCurrency(activeCombinedFifoYear?.price_policy_delta_eur)} EUR`} />
          <Metric title="Wallet-Delta" value={`${formatCurrency(activeCombinedFifoYear?.wallet_scope_delta_eur)} EUR`} />
          <Metric title="Kombiniertes Delta" value={`${formatCurrency(activeCombinedFifoYear?.combined_delta_eur)} EUR`} />
          <Metric title="Interaktion" value={`${formatCurrency(activeCombinedFifoYear?.interaction_delta_eur)} EUR`} />
        </div>
        <TablePanel
          title={`Kombinierte Assetwirkung ${activeYearValue}`}
          rows={activeCombinedFifoAssets.map((row) => ({
            asset: row.asset,
            global_aktiv_eur: formatCurrency(row.active_global_gain_loss_eur),
            global_bmf_eur: formatCurrency(row.received_first_global_gain_loss_eur),
            wallet_aktiv_eur: formatCurrency(row.active_wallet_gain_loss_eur),
            wallet_bmf_eur: formatCurrency(row.received_first_wallet_gain_loss_eur),
            preisdelta_eur: formatCurrency(row.price_policy_delta_eur),
            wallet_delta_eur: formatCurrency(row.wallet_scope_delta_eur),
            kombiniert_eur: formatCurrency(row.combined_delta_eur),
            reward_betriebsvermoegen_zeilen: row.potential_business_inventory_tax_lines_count,
            reward_ursprung_offen: row.unresolved_reward_origin_tax_lines_count
          }))}
          footer={taxBmfCombinedFifoStaging?.methodology ?? "Noch kein gemeinsamer Staging-Lauf vorhanden."}
          compact
        />
        <section className="cockpitDataGrid">
          <TablePanel
            title={`Reward-Ursprungsgruppen ${activeYearValue}`}
            rows={activeCombinedFifoSpheres.map((row) => ({
              asset: row.asset,
              klassifikation: row.classification,
              ursprungs_events: row.origin_events_count,
              tax_lines: row.tax_lines_count,
              menge: row.quantity,
              anschaffung_eur: formatCurrency(row.acquisition_cost_eur),
              erloes_eur: formatCurrency(row.disposal_proceeds_eur),
              gv_eur: formatCurrency(row.gain_loss_eur)
            }))}
            footer="Technische Ursprungsklassifikation; keine automatische private oder betriebliche Buchung."
            compact
          />
          <TablePanel
            title={`Groesste kombinierte Eventdeltas ${activeYearValue}`}
            rows={activeCombinedFifoEvents.map((row) => ({
              asset: row.asset,
              source: row.source,
              account: row.account,
              tx_id: row.tx_id,
              preisdelta_eur: formatCurrency(row.price_policy_delta_eur),
              wallet_delta_eur: formatCurrency(row.wallet_scope_delta_eur),
              kombiniert_eur: formatCurrency(row.combined_delta_eur),
              ursprung: Array.isArray(row.origin_classifications) ? row.origin_classifications.join(", ") : "",
              disposal_event_id: row.disposal_event_id
            }))}
            footer="Vollstaendige IDs bleiben im API-Artefakt und im Zellen-Tooltip erhalten."
            compact
          />
        </section>
      </section>
      <section className="panel">
        <div className="panelToolbar">
          <div>
            <strong>FIFO-Eventbelege {activeYearValue}</strong>
            <span>{formatDateTime(taxBmfFifoEventEvidence?.generated_at)}</span>
          </div>
          <div className="buttonRow">
            <span
              className={`statusPill ${
                taxBmfFifoEventEvidence?.status === "ready_for_professional_review"
                  ? "ok"
                  : taxBmfFifoEventEvidence?.status === "review"
                    ? "warning"
                    : "blocked"
              }`}
            >
              {taxBmfFifoEventEvidence?.status === "ready_for_professional_review"
                ? "belege pruefbereit"
                : taxBmfFifoEventEvidence?.status === "review"
                  ? "preispruefung offen"
                  : "belege blockiert"}
            </span>
            <button
              type="button"
              onClick={() => onRunBmfFifoEventEvidence("priority_delta")}
              disabled={bmfFifoEventEvidenceLoading || bmfEventPriceRemediationLoading}
            >
              <RefreshCcw size={16} />
              <span>{bmfFifoEventEvidenceLoading ? "Prueft" : "Eventbelege aktualisieren"}</span>
            </button>
            <button
              className="secondary"
              type="button"
              onClick={() => onRunBmfFifoEventEvidence("full_ledger")}
              disabled={bmfFifoEventEvidenceLoading || bmfEventPriceRemediationLoading}
              title="Alle Canonical Events und FIFO-Anschaffungs-/Veraeusserungsreferenzen pruefen"
            >
              <Database size={16} />
              <span>{bmfFifoEventEvidenceLoading ? "Prueft" : "Gesamtledger pruefen"}</span>
            </button>
            {taxBmfFifoEventEvidence?.all_event_evidence_artifact_path ? (
              <button
                className="secondary"
                type="button"
                onClick={() => onDownload("/api/v1/tax/bmf-fifo-event-evidence/events.jsonl.gz")}
                title="Komprimierten, SHA-256-gebundenen Einzelnachweis herunterladen"
              >
                <FileDown size={16} />
                <span>Vollnachweis</span>
              </button>
            ) : null}
            <button
              className="secondary"
              type="button"
              onClick={() => onRunBmfEventPriceRemediation(false)}
              disabled={bmfEventPriceRemediationLoading || bmfFifoEventEvidenceLoading}
            >
              <RefreshCcw size={16} />
              <span>{bmfEventPriceRemediationLoading ? "Prueft" : "Preisanker pruefen"}</span>
            </button>
            <button
              type="button"
              onClick={() => onRunBmfEventPriceRemediation(true)}
              disabled={bmfEventPriceRemediationLoading || bmfFifoEventEvidenceLoading}
            >
              <Check size={16} />
              <span>{bmfEventPriceRemediationLoading ? "Verarbeitet" : "Belegte Anker anwenden"}</span>
            </button>
          </div>
        </div>
        <div className="portfolioSummaryStrip">
          <Metric
            title="Rohbelege"
            value={`${taxBmfFifoEventEvidence?.raw_evidence_ready_count ?? 0} / ${taxBmfFifoEventEvidence?.unique_events_count ?? 0}`}
          />
          <Metric
            title="Ledgerumfang"
            value={taxBmfFifoEventEvidence?.full_ledger_scope
              ? String(taxBmfFifoEventEvidence.ledger_events_count ?? 0)
              : "priorisiert"}
          />
          <Metric title="FIFO-Graph" value={String(taxBmfFifoEventEvidence?.tax_graph_events_count ?? 0)} />
          <Metric title="Unabhaengige Preise" value={String(taxBmfFifoEventEvidence?.independent_price_ready_count ?? 0)} />
          <Metric title="Abgeleitete Preise" value={String(taxBmfFifoEventEvidence?.derived_price_review_count ?? 0)} />
          <Metric title="Veraltete Preise" value={String(taxBmfFifoEventEvidence?.stale_price_review_count ?? 0)} />
          <Metric title="Fehlende Preise" value={String(taxBmfFifoEventEvidence?.missing_price_count ?? 0)} />
          <Metric title="Betriebsinventar belegt" value={String(taxBmfFifoEventEvidence?.documented_business_inventory_rows_count ?? 0)} />
          <Metric title="Swap-Erwerbe belegt" value={String(taxBmfFifoEventEvidence?.documented_swap_acquisition_rows_count ?? 0)} />
          <Metric title="Transfer-FIFO offen" value={String(taxBmfFifoEventEvidence?.internal_transfer_fifo_carry_rows_count ?? 0)} />
          <Metric title="Rekonstruktionsgrenzen" value={String(taxBmfFifoEventEvidence?.opening_reconstruction_rows_count ?? 0)} />
          <Metric title="Echt unklassifiziert" value={String(taxBmfFifoEventEvidence?.unclassified_origin_rows_count ?? 0)} />
          <Metric title="Separate Einkunft" value={String(taxBmfFifoEventEvidence?.separate_income_review_rows_count ?? 0)} />
          <Metric title="Opening Balances" value={String(taxBmfFifoEventEvidence?.opening_balance_events_count ?? 0)} />
          <Metric
            title="Eventtyp unknown"
            value={`${taxBmfFifoEventEvidence?.unknown_tax_graph_events_count ?? 0} FIFO / ${taxBmfFifoEventEvidence?.unknown_event_type_count ?? 0} gesamt`}
          />
          <Metric title="Absolute Deltawirkung" value={`${formatCurrency(taxBmfFifoEventEvidence?.absolute_combined_delta_eur)} EUR`} />
          <Metric
            title="An aktuelles Staging gebunden"
            value={taxBmfFifoEventEvidence?.staging_matches_current_input ? "ja" : "nein"}
          />
        </div>
        <TablePanel
          title="Belegstatus nach Pruefgruppe"
          rows={(taxBmfFifoEventEvidence?.groups ?? []).map((row) => ({
            gruppe: row.label,
            status: row.status,
            delta_events: row.discrepancy_rows_count,
            referenzierte_events: row.unique_events_count,
            rohbelege: row.raw_evidence_ready_count,
            unabhaengige_preise: row.independent_price_ready_count,
            abgeleitete_preise: row.derived_price_review_count,
            veraltete_preise: row.stale_price_review_count,
            blockiert: row.blocked_events_count,
            absolutes_delta_eur: formatCurrency(row.absolute_combined_delta_eur),
            pruefgruende: Array.isArray(row.issue_codes) ? row.issue_codes.join(", ") : ""
          }))}
          footer="HNT Legacy/Solana sowie JUP, SOL, TRUMP, USDT und MXC werden getrennt bewertet; leere Gruppen erzeugen keinen Scheinfehler."
          compact
        />
        <TablePanel
          title="Ursprungsnachweis nach Steuersphaere"
          rows={(taxBmfFifoEventEvidence?.origin_evidence_groups ?? []).map((row) => ({
            status: row.status,
            steuersphaere: row.tax_sphere,
            klassifikation: row.classification,
            asset: row.asset,
            canonical_assets: Array.isArray(row.canonical_event_assets) ? row.canonical_event_assets.join(", ") : "",
            source: row.source,
            event_typ: row.event_type,
            ursprungs_events: row.unique_origin_events_count,
            delta_zeilen: row.affected_discrepancy_rows_count,
            rohbelege: row.raw_evidence_ready_count,
            fifo_fortfuehrung: row.fifo_carry_forward_required ? "offen" : "nicht erforderlich",
            belegmarker: Array.isArray(row.evidence_markers) ? row.evidence_markers.join(" | ") : "",
            entscheidungsbasis: row.decision_basis
          }))}
          footer="Reward, Swap, CEX-Umbuchung und Rekonstruktionsgrenze werden getrennt ausgewiesen. Interne Transfers erzeugen keinen Ertrag, benoetigen aber die belegte Fortfuehrung des Vorlots."
          compact
        />
        {(taxBmfFifoEventEvidence?.opening_balance_evidence ?? []).length > 0 ? (
          <TablePanel
            title="Opening-Balance-Nachweise und Grenzen"
            rows={(taxBmfFifoEventEvidence?.opening_balance_evidence ?? []).map((row) => ({
              datum: formatDateTime(row.event_time),
              status: row.documentation_status,
              asset: row.asset,
              menge: row.quantity,
              account: row.account,
              rohdatei: row.raw_filename,
              zeile: row.raw_row_number,
              originaltransaktion: row.original_transaction_available ? "vorhanden" : "nicht vorhanden",
              portfolio_wirkung: row.live_balance_effect,
              steuer_event: row.tax_event_effect,
              grenzen: Array.isArray(row.limitations) ? row.limitations.join(" | ") : "",
              event_id: row.event_id
            }))}
            footer="Opening Balances sind Anfangslots oder Rekonstruktionsgrenzen. Sie erzeugen weder einen Live-Bestand noch automatisch einen Reward, Kauf oder Eigenwallet-Transfer."
            compact
          />
        ) : null}
        {taxBmfFifoEventEvidence?.full_ledger_scope ? (
          <TablePanel
            title={`Ledger-Vollstaendigkeit ${activeYearValue}`}
            rows={(taxBmfFifoEventEvidence.ledger_groups ?? [])
              .filter((row) => String(row.year) === activeYearValue)
              .map((row) => ({
                source: row.source,
                event_typ: row.event_type,
                events: row.events_count,
                fifo_graph: row.tax_graph_events_count,
                rohbelege: row.raw_evidence_ready_count,
                bereit: row.ready_events_count,
                review: row.review_events_count,
                blockiert: row.blocked_events_count,
                unabhaengige_preise: row.independent_price_ready_count,
                fehlende_preise: row.missing_price_count,
                pruefgruende: Array.isArray(row.issue_codes) ? row.issue_codes.join(", ") : ""
              }))}
            footer={`Komprimierter Vollnachweis: ${taxBmfFifoEventEvidence.all_event_evidence_artifact_bytes ?? 0} Bytes; SHA-256 ${taxBmfFifoEventEvidence.all_event_evidence_artifact_sha256 ?? "-"}.`}
            compact
          />
        ) : null}
        <TablePanel
          title={`Letzte Preisanker-Pruefung ${activeYearValue}`}
          rows={(taxBmfEventPriceRemediation?.jobs ?? [])
            .filter((row) => String(row.price_date ?? "").startsWith(activeYearValue))
            .map((row) => ({
              status: row.status,
              asset: row.asset,
              tag: row.price_date,
              rollen: Array.isArray(row.roles) ? row.roles.join(", ") : "",
              bisher: Array.isArray(row.previous_qualities) ? row.previous_qualities.join(", ") : "",
              token_risiko: row.token_risk_status ?? "-",
              preis_eur: formatCurrency(row.price_eur),
              provider: row.provider_id,
              provider_confidence: row.provider_confidence,
              fx_quelltag: row.fx_rate_date,
              betroffene_events: Array.isArray(row.affected_event_ids) ? row.affected_event_ids.length : 0,
              ergebnis: row.reason
            }))}
          footer={taxBmfEventPriceRemediation
            ? `${taxBmfEventPriceRemediation.status}: ${taxBmfEventPriceRemediation.imported_count} importiert, ${taxBmfEventPriceRemediation.planned_count} geplant, ${taxBmfEventPriceRemediation.failed_count} fehlgeschlagen, ${taxBmfEventPriceRemediation.token_risk_blocked_count} durch Token-Risiko blockiert. Tax-Tabellen unveraendert: ${taxBmfEventPriceRemediation.productive_tax_tables_unchanged ? "ja" : "nein"}.`
            : "Noch keine gezielte Event-Preisankerpruefung vorhanden."}
          compact
        />
        <section className="cockpitDataGrid">
          <TablePanel
            title={`Delta-Worklist ${activeYearValue}`}
            rows={activeFifoEventEvidenceRows.map((row) => ({
              status: row.status,
              datum: formatDateTime(row.disposed_at),
              asset: row.asset,
              source: row.source,
              account: row.account,
              tx_id: row.tx_id,
              kombiniert_eur: formatCurrency(row.combined_delta_eur),
              disposal_beleg: row.disposal_evidence_status,
              anschaffungsbelege: `${row.acquisition_raw_ready_count ?? 0} / ${row.acquisition_events_count ?? 0}`,
              unabhaengige_anschaffungspreise: `${row.acquisition_independent_price_count ?? 0} / ${row.acquisition_events_count ?? 0}`,
              reward_ursprung: Array.isArray(row.origin_classifications) ? row.origin_classifications.join(", ") : "",
              pruefgruende: Array.isArray(row.issue_codes) ? row.issue_codes.join(", ") : "",
              disposal_event_id: row.disposal_event_id
            }))}
            footer="Vollstaendige TxIDs, Accounts, Event-IDs und Acquisition-Fingerprints bleiben im API-Artefakt erhalten."
            compact
          />
          <TablePanel
            title={`Konkrete Event-/Preispruefungen ${activeYearValue}`}
            rows={activeFifoEventIssues.slice(0, 80).map((row) => {
              const sourceEvidence = row.source_evidence ?? {};
              const receivedPrice = row.received_price ?? {};
              return {
                status: row.status,
                datum: formatDateTime(row.event_time),
                source: row.source,
                typ: row.event_type,
                asset: row.asset,
                menge: row.quantity,
                quote_asset: row.quote_asset,
                quote_menge: row.quote_quantity,
                tx_oder_cex_ref: row.tx_id ?? row.source_ref,
                rohdatei: sourceEvidence.filename,
                zeile: sourceEvidence.row_number,
                preis_asset: receivedPrice.asset,
                preis_eur: formatCurrency(receivedPrice.price_eur),
                preisquelle: receivedPrice.source,
                preisalter_stunden: receivedPrice.age_hours,
                pruefgruende: row.issue_codes.join(", "),
                event_id: row.event_id
              };
            })}
            footer={taxBmfFifoEventEvidence?.event_issues_truncated
              ? "Anzeige ist durch das Issue-Limit gekuerzt; das Artefakt weist dies explizit aus."
              : "Nur Events mit konkretem Preis- oder Quellenreview; Rohpayloads sind per SHA-256 gebunden."}
            compact
          />
        </section>
        {(taxBmfFifoEventEvidence?.next_actions ?? []).length > 0 ? (
          <div className="valuationGateFindings">
            {(taxBmfFifoEventEvidence?.next_actions ?? []).map((action) => (
              <span key={action}>{action}</span>
            ))}
          </div>
        ) : null}
        <p className="panelFooter">{taxBmfFifoEventEvidence?.methodology ?? "Eventbeleg-Report wird geladen."}</p>
      </section>
      <section className="panel">
        <div className="panelToolbar">
          <div>
            <strong>Preisrangfolgen-FIFO Parallelvergleich {activeYearValue}</strong>
            <span>{formatDateTime(taxCryptoSwapFifoParallelPreview?.generated_at)}</span>
          </div>
          <div className="buttonRow">
            <span className={`statusPill ${taxCryptoSwapFifoParallelPreview?.status === "matched" ? "ok" : "blocked"}`}>
              {taxCryptoSwapFifoParallelPreview?.status === "matched" ? "paritaet" : "jahresdelta"}
            </span>
            <button
              type="button"
              onClick={onRunSwapFifoParallelPreview}
              disabled={swapFifoParallelLoading}
            >
              <RefreshCcw size={16} />
              <span>{swapFifoParallelLoading ? "Berechnet" : "Neu berechnen"}</span>
            </button>
          </div>
        </div>
        <div className="portfolioSummaryStrip">
          <Metric title="Aktueller G/V" value={`${formatCurrency(activeSwapFifoParallelYear?.current_gain_loss_eur)} EUR`} />
          <Metric title="BMF-Preispreview G/V" value={`${formatCurrency(activeSwapFifoParallelYear?.preview_gain_loss_eur)} EUR`} />
          <Metric title="Jahresdelta" value={`${formatCurrency(activeSwapFifoParallelYear?.gain_loss_delta_eur)} EUR`} />
          <Metric title="Bis 365 Tage Delta" value={`${formatCurrency(activeSwapFifoParallelYear?.short_holding_gain_loss_delta_eur)} EUR`} />
          <Metric title="Ueber 365 Tage Delta" value={`${formatCurrency(activeSwapFifoParallelYear?.long_holding_gain_loss_delta_eur)} EUR`} />
          <Metric title="Unmatched aktuell / Preview" value={`${taxCryptoSwapFifoParallelPreview?.current_unmatched_disposals ?? 0} / ${taxCryptoSwapFifoParallelPreview?.preview_unmatched_disposals ?? 0}`} />
        </div>
        <TablePanel
          title={`Groesste Assetdeltas ${activeYearValue}`}
          rows={activeSwapFifoParallelAssets.map((row) => ({
            asset: row.asset,
            aktuell_gv_eur: formatCurrency(row.current_gain_loss_eur),
            preview_gv_eur: formatCurrency(row.preview_gain_loss_eur),
            delta_eur: formatCurrency(row.gain_loss_delta_eur),
            bis_365_tage_delta_eur: formatCurrency(row.short_holding_gain_loss_delta_eur),
            ueber_365_tage_delta_eur: formatCurrency(row.long_holding_gain_loss_delta_eur),
            tax_lines_aktuell: row.current_tax_lines_count,
            tax_lines_preview: row.preview_tax_lines_count
          }))}
          footer={taxCryptoSwapFifoParallelPreview?.methodology ?? "FIFO-Parallelvergleich wird geladen."}
          compact
        />
        <TablePanel
          title={`Groesste Eventdeltas ${activeYearValue}`}
          rows={activeSwapFifoParallelEvents.map((row) => ({
            asset: row.asset,
            source: row.source,
            account: row.account,
            tx_id: row.tx_id,
            aktuell_gv_eur: formatCurrency(row.current_gain_loss_eur),
            preview_gv_eur: formatCurrency(row.preview_gain_loss_eur),
            delta_eur: formatCurrency(row.gain_loss_delta_eur),
            disposal_event_id: row.disposal_event_id
          }))}
          footer="Vollstaendige Account-, TxID- und Eventwerte stehen im Zellen-Tooltip und im API-Artefakt."
          compact
        />
      </section>
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

type TaxProductYearRow = {
  year: string;
  tone: "ok" | "warning" | "blocked";
  statusLabel: string;
  declarationBucket: string;
  whereToEnter: string;
  taxablePrivateDisposalsEur: unknown;
  rewardsMiningStakingIncomeEur: unknown;
  derivativePnlEur: unknown;
  taxFreePrivateDisposalsEur: unknown;
  attachCount: number;
  reviewCount: number;
  nextAction: string;
  filingEndpoint: string;
  checklistEndpoint: string;
  evidencePackageEndpoint: string;
};

type TaxAtAGlanceItem = {
  label: string;
  value: string;
  detail: string;
  endpoint?: string;
  tone?: "ok" | "warning" | "blocked";
};

function TaxFilingAtAGlance({
  year,
  tone,
  headline,
  summary,
  entries,
  evidence,
  reviews,
  generatedAt,
  filingEndpoint,
  guideEndpoint,
  evidencePackageEndpoint,
  onDownload
}: {
  year: string;
  tone: "ok" | "warning" | "blocked";
  headline: string;
  summary: string;
  entries: TaxAtAGlanceItem[];
  evidence: TaxAtAGlanceItem[];
  reviews: TaxAtAGlanceItem[];
  generatedAt?: string | null;
  filingEndpoint: string;
  guideEndpoint: string;
  evidencePackageEndpoint: string;
  onDownload: (path: string) => void;
}) {
  return (
    <section className={`taxAtAGlancePanel ${tone}`}>
      <div className="taxAtAGlanceHeader">
        <div>
          <span className="heroKicker">Steuererklaerung auf einen Blick</span>
          <h3>{year}: {headline}</h3>
          <p>{summary}</p>
        </div>
        <div className="taxAtAGlanceMeta">
          <span className={`statusPill ${tone}`}>{tone === "ok" ? "bereit" : tone === "blocked" ? "blockiert" : "pruefen"}</span>
          <span>Stand {generatedAt ? formatDateTime(generatedAt) : "-"}</span>
        </div>
      </div>
      <div className="taxAtAGlanceGrid">
        <TaxAtAGlanceColumn
          title="Eintragen"
          icon={<ReceiptText size={18} />}
          emptyText="Noch keine Eingabewerte geladen."
          items={entries}
          onDownload={onDownload}
        />
        <TaxAtAGlanceColumn
          title="Beilegen"
          icon={<PackageCheck size={18} />}
          emptyText="Keine Pflichtbelege fuer die Top-Ansicht gefunden."
          items={evidence}
          onDownload={onDownload}
        />
        <TaxAtAGlanceColumn
          title="Pruefen"
          icon={<ClipboardCheck size={18} />}
          emptyText="Keine offenen Pruefpunkte im Jahreskopf."
          items={reviews}
          onDownload={onDownload}
        />
      </div>
      <div className="taxAtAGlanceActions">
        <button type="button" onClick={() => onDownload(filingEndpoint)}>
          <ReceiptText size={16} />
          <span>Eingabehilfe</span>
        </button>
        <button type="button" onClick={() => onDownload(guideEndpoint)}>
          <ReceiptText size={16} />
          <span>ELSTER-Hilfe</span>
        </button>
        <button type="button" onClick={() => onDownload(evidencePackageEndpoint)}>
          <PackageCheck size={16} />
          <span>Belegpaket</span>
        </button>
      </div>
    </section>
  );
}

function TaxAtAGlanceColumn({
  title,
  icon,
  items,
  emptyText,
  onDownload
}: {
  title: string;
  icon: React.ReactNode;
  items: TaxAtAGlanceItem[];
  emptyText: string;
  onDownload: (path: string) => void;
}) {
  return (
    <div className="taxAtAGlanceColumn">
      <div className="taxAtAGlanceColumnHeader">
        <span>{icon}</span>
        <strong>{title}</strong>
      </div>
      <div className="taxAtAGlanceItems">
        {items.length === 0 ? (
          <span className="taxAtAGlanceEmpty">{emptyText}</span>
        ) : (
          items.map((item, index) => (
            <div key={`${title}-${index}`} className={`taxAtAGlanceItem ${item.tone ?? "ok"}`}>
              <div>
                <strong>{item.label}</strong>
                <span>{item.detail}</span>
              </div>
              <div className="taxAtAGlanceValue">
                <em>{item.value}</em>
                {item.endpoint ? (
                  <button type="button" onClick={() => onDownload(humanReadableTaxEndpoint(item.endpoint ?? ""))} title="Nachweis oeffnen">
                    <FileDown size={14} />
                  </button>
                ) : null}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function TaxProductCommandCenter({
  rows,
  activeYear,
  activeRow,
  onSelectYear,
  onDownload,
  loading = false
}: {
  rows: TaxProductYearRow[];
  activeYear: string;
  activeRow: TaxProductYearRow | undefined;
  onSelectYear: (year: string) => void;
  onDownload: (path: string) => void;
  loading?: boolean;
}) {
  if (loading) {
    return (
      <section className="taxProductCenter loading" aria-busy="true" aria-live="polite">
        <div className="taxProductHeader">
          <div>
            <span className="heroKicker">Abgabe-Navigator</span>
            <h3>{activeYear}: Jahresdaten werden geladen</h3>
            <p>Fertige Jahrespakete werden sofort angezeigt; bis dahin werden keine Nullwerte angenommen.</p>
          </div>
          <span className="statusPill loading">laedt</span>
        </div>
        <div className="taxProductSummary">
          <Metric title="Eintragen Anlage SO" value="wird geladen" />
          <Metric title="Rewards/Mining" value="wird geladen" />
          <Metric title="Derivate" value="wird geladen" />
          <Metric title="Steuerfrei archivieren" value="wird geladen" />
        </div>
        <div className="taxProductLoadingRows" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      </section>
    );
  }
  const readyCount = rows.filter((row) => row.tone === "ok").length;
  const reviewCount = rows.filter((row) => row.tone === "warning").length;
  const blockedCount = rows.filter((row) => row.tone === "blocked").length;
  return (
    <section className="taxProductCenter">
      <div className="taxProductHeader">
        <div>
          <span className="heroKicker">Abgabe-Navigator</span>
          <h3>{activeYear}: {activeRow?.statusLabel ?? "Jahresstatus wird geladen"}</h3>
          <p>{activeRow?.nextAction ?? "Waehle ein Steuerjahr, um Eingabewerte, Belege und naechste Schritte zu sehen."}</p>
        </div>
        <div className="taxProductStatusStack">
          <span className="statusPill ok">{readyCount} bereit</span>
          <span className="statusPill warning">{reviewCount} pruefen</span>
          <span className="statusPill blocked">{blockedCount} blockiert</span>
        </div>
      </div>
      <div className="taxProductSummary">
        <Metric title="Eintragen Anlage SO" value={`${formatCurrency(activeRow?.taxablePrivateDisposalsEur)} EUR`} />
        <Metric title="Rewards/Mining" value={`${formatCurrency(activeRow?.rewardsMiningStakingIncomeEur)} EUR`} />
        <Metric title="Derivate" value={`${formatCurrency(activeRow?.derivativePnlEur)} EUR`} />
        <Metric title="Steuerfrei archivieren" value={`${formatCurrency(activeRow?.taxFreePrivateDisposalsEur)} EUR`} />
      </div>
      <div className="taxProductActiveActions">
        <div>
          <strong>{activeRow?.declarationBucket ?? "Eingabeziel offen"}</strong>
          <span>{activeRow?.whereToEnter ?? "Eingabeziel wird aus der Jahreslogik geladen."}</span>
        </div>
        <button
          type="button"
          disabled={!activeRow?.filingEndpoint}
          onClick={() => onDownload(humanReadableTaxEndpoint(activeRow?.filingEndpoint ?? ""))}
        >
          <ReceiptText size={16} />
          <span>Eingabehilfe</span>
        </button>
        <button type="button" disabled={!activeRow?.checklistEndpoint} onClick={() => onDownload(activeRow?.checklistEndpoint ?? "")}>
          <FileDown size={16} />
          <span>Checkliste</span>
        </button>
        <button type="button" disabled={!activeRow?.evidencePackageEndpoint} onClick={() => onDownload(activeRow?.evidencePackageEndpoint ?? "")}>
          <PackageCheck size={16} />
          <span>Belegpaket</span>
        </button>
      </div>
      <div className="taxProductYearGrid">
        {rows.map((row) => (
          <button
            key={row.year}
            className={`taxProductYearCard ${row.tone} ${row.year === activeYear ? "active" : ""}`}
            type="button"
            onClick={() => onSelectYear(row.year)}
          >
            <span className={`statusPill ${row.tone}`}>{row.statusLabel}</span>
            <strong>{row.year}</strong>
            <em>{row.declarationBucket}</em>
            <small>
              SO {formatCurrency(row.taxablePrivateDisposalsEur)} EUR · Rewards {formatCurrency(row.rewardsMiningStakingIncomeEur)} EUR
            </small>
            <small>{row.attachCount} beilegen · {row.reviewCount} pruefen</small>
          </button>
        ))}
      </div>
    </section>
  );
}

function buildTaxProductYearRows({
  years,
  paymentRows,
  filingMatrixRows,
  filingClosureRows,
  submissionRows,
  finalizationRows
}: {
  years: Array<Record<string, unknown>>;
  paymentRows: Array<Record<string, unknown>>;
  filingMatrixRows: Array<Record<string, unknown>>;
  filingClosureRows: Array<Record<string, unknown>>;
  submissionRows: Array<Record<string, unknown>>;
  finalizationRows: Array<Record<string, unknown>>;
}): TaxProductYearRow[] {
  const yearValues = new Set<string>();
  for (const list of [years, paymentRows, filingMatrixRows, filingClosureRows, submissionRows, finalizationRows]) {
    for (const row of list) {
      if (row.year !== undefined && row.year !== null) {
        yearValues.add(String(row.year));
      }
    }
  }
  return Array.from(yearValues)
    .sort((left, right) => Number(left) - Number(right))
    .map((year) => {
      const payment = paymentRows.find((row) => String(row.year) === year);
      const matrix = filingMatrixRows.find((row) => String(row.year) === year);
      const closure = filingClosureRows.find((row) => String(row.year) === year);
      const submission = submissionRows.find((row) => String(row.year) === year);
      const finalization = finalizationRows.find((row) => String(row.year) === year);
      const status = String(
        closure?.filing_status
          ?? matrix?.action_status
          ?? submission?.status
          ?? finalization?.status
          ?? payment?.status
          ?? ""
      );
      const tone = taxProductTone(status);
      return {
        year,
        tone,
        statusLabel: String(
          submission?.status_label
            ?? finalization?.status_label
            ?? filingActionStatusLabel(status || matrix?.action_status || closure?.filing_status)
            ?? "-"
        ),
        declarationBucket: String(
          payment?.declaration_bucket
            ?? submission?.declaration_bucket
            ?? closure?.declaration_bucket
            ?? "Steuerjahr pruefen"
        ),
        whereToEnter: String(
          payment?.where_to_enter
            ?? submission?.where_to_enter
            ?? "Eingabeziel im Filing Summary pruefen"
        ),
        taxablePrivateDisposalsEur: firstDefined(
          payment?.private_disposals_gain_loss_eur,
          submission?.taxable_private_disposals_eur,
          finalization?.taxable_private_disposals_eur,
          closure?.private_disposals_gain_loss_eur,
          matrix?.taxable_private_disposals_eur
        ),
        rewardsMiningStakingIncomeEur: firstDefined(
          payment?.rewards_mining_staking_income_eur,
          submission?.rewards_mining_staking_income_eur,
          finalization?.rewards_mining_staking_income_eur,
          closure?.rewards_mining_staking_income_eur,
          matrix?.rewards_mining_staking_income_eur
        ),
        derivativePnlEur: firstDefined(
          payment?.derivative_pnl_eur,
          submission?.derivative_pnl_eur,
          finalization?.derivative_pnl_eur,
          closure?.derivative_pnl_eur,
          matrix?.derivative_pnl_eur
        ),
        taxFreePrivateDisposalsEur: firstDefined(
          payment?.tax_free_private_disposals_eur,
          closure?.tax_free_private_disposals_eur,
          submission?.tax_free_private_disposals_eur,
          finalization?.tax_free_private_disposals_eur
        ),
        attachCount: Number(
          closure?.beilegen_count
            ?? submission?.attach_count
            ?? matrix?.bmf_closure_appendix_items_count
            ?? 0
        ),
        reviewCount: Number(
          closure?.pruefen_count
            ?? submission?.technical_review_requirements_count
            ?? finalization?.review_count
            ?? 0
        ),
        nextAction: String(
          closure?.next_action
            ?? submission?.next_action
            ?? finalization?.next_action
            ?? matrix?.next_action
            ?? payment?.what_to_do
            ?? "Jahresdetails pruefen"
        ),
        filingEndpoint: String(
          humanReadableFilingEndpoint(
            String(
              closure?.filing_summary_endpoint
                ?? submission?.filing_summary_endpoint
                ?? finalization?.filing_summary_endpoint
                ?? matrix?.filing_summary_endpoint
                ?? taxYearFilingSummaryHtmlPath(year)
            )
          )
        ),
        checklistEndpoint: String(
          closure?.filing_checklist_csv_endpoint
            ?? submission?.filing_checklist_csv_endpoint
            ?? matrix?.filing_checklist_csv_endpoint
            ?? `/api/v1/export/tax-years/${year}/filing-checklist.csv`
        ),
        evidencePackageEndpoint: String(
          closure?.evidence_package_endpoint
            ?? submission?.evidence_package_endpoint
            ?? finalization?.evidence_package_endpoint
            ?? matrix?.evidence_package_endpoint
            ?? `/api/v1/export/tax-years/${year}/evidence-package.zip`
        )
      };
    });
}

function firstDefined(...values: unknown[]): unknown {
  return values.find((value) => value !== undefined && value !== null) ?? 0;
}

function taxProductTone(status: string): "ok" | "warning" | "blocked" {
  if (["ready", "conservative_ready", "bmf_ready", "ok", "finished"].includes(status)) {
    return "ok";
  }
  if (["blocked", "not_ready"].includes(status)) {
    return "blocked";
  }
  return "warning";
}

function taxYearFilingSummaryHtmlPath(year: unknown): string {
  return `/api/v1/tax-years/${encodeURIComponent(String(year))}/filing-summary.html`;
}

function taxYearDeclarationGuideHtmlPath(year: unknown): string {
  return `/api/v1/tax-years/${encodeURIComponent(String(year))}/declaration-guide.html`;
}

function taxYearEvidenceHtmlPath(year: unknown): string {
  return `/api/v1/tax-years/${encodeURIComponent(String(year))}/evidence.html`;
}

function humanReadableFilingEndpoint(endpoint: string): string {
  return endpoint.replace(/\/filing-summary($|\?)/, "/filing-summary.html$1");
}

function humanReadableTaxEndpoint(endpoint: string): string {
  return humanReadableFilingEndpoint(endpoint)
    .replace(/\/declaration-guide($|\?)/, "/declaration-guide.html$1")
    .replace(/\/evidence($|\?)/, "/evidence.html$1");
}

function PriorFilingDeclaredAmountsForm({
  comparison,
  declaredAmounts,
  onSave
}: {
  comparison: Snapshot["taxBmfPriorFilingComparison"];
  declaredAmounts: Snapshot["taxBmfPriorFilingDeclaredAmounts"];
  onSave: (years: Array<Record<string, unknown>>) => void;
}) {
  const baseYears = useMemo(
    () => (comparison?.available_years ?? [2021, 2022, 2023, 2024, 2025]).map(Number),
    [comparison?.available_years]
  );
  const [rows, setRows] = useState<Array<Record<string, string | number>>>([]);

  useEffect(() => {
    const existing = new Map((declaredAmounts?.years ?? []).map((row) => [Number(row.year), row]));
    setRows(
      baseYears.map((year) => {
        const current = existing.get(year);
        return {
          year,
          taxable_private_disposals_eur: String(current?.taxable_private_disposals_eur ?? "0.00"),
          rewards_mining_staking_income_eur: String(current?.rewards_mining_staking_income_eur ?? "0.00"),
          derivative_pnl_eur: String(current?.derivative_pnl_eur ?? "0.00"),
          tax_free_private_disposals_eur: String(current?.tax_free_private_disposals_eur ?? "0.00"),
          declared_values_status: String(current?.declared_values_status ?? "unknown"),
          note: String(current?.note ?? "")
        };
      })
    );
  }, [baseYears, declaredAmounts?.years]);

  function updateRow(year: number, key: string, value: string) {
    const nextValue = key.endsWith("_eur") ? value.replace(",", ".") : value;
    setRows((current) => current.map((row) => row.year === year ? { ...row, [key]: nextValue } : row));
  }

  return (
    <div className="evidenceCard">
      <div className="evidenceCardHeader">
        <strong>Urspruenglich erklaerte Werte erfassen</strong>
        <span className={`statusPill ${comparison?.setting_exists ? "ok" : "warning"}`}>
          {comparison?.setting_exists ? "Altwerte vorhanden" : "Altwerte fehlen"}
        </span>
      </div>
      <div className="tableWrap">
        <table>
          <thead>
            <tr>
              <th>Jahr</th>
              <th>Anlage SO G/V</th>
              <th>Rewards/Mining</th>
              <th>Derivate</th>
              <th>Steuerfrei archiviert</th>
              <th>Status</th>
              <th>Notiz</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const year = Number(row.year);
              return (
                <tr key={year}>
                  <td>{year}</td>
                  <td><input value={String(row.taxable_private_disposals_eur)} onChange={(event) => updateRow(year, "taxable_private_disposals_eur", event.target.value)} /></td>
                  <td><input value={String(row.rewards_mining_staking_income_eur)} onChange={(event) => updateRow(year, "rewards_mining_staking_income_eur", event.target.value)} /></td>
                  <td><input value={String(row.derivative_pnl_eur)} onChange={(event) => updateRow(year, "derivative_pnl_eur", event.target.value)} /></td>
                  <td><input value={String(row.tax_free_private_disposals_eur)} onChange={(event) => updateRow(year, "tax_free_private_disposals_eur", event.target.value)} /></td>
                  <td>
                    <select value={String(row.declared_values_status)} onChange={(event) => updateRow(year, "declared_values_status", event.target.value)}>
                      <option value="unknown">unbekannt</option>
                      <option value="probably_wrong">vermutlich falsch</option>
                      <option value="declared_values">belegte Werte</option>
                      <option value="not_filed">nicht erklaert</option>
                    </select>
                  </td>
                  <td><input value={String(row.note)} onChange={(event) => updateRow(year, "note", event.target.value)} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="panelToolbar">
        <span>EUR-Werte mit Punkt oder Komma eingeben. Leere Jahre mit 0,00 stehen lassen.</span>
        <button type="button" onClick={() => onSave(rows)}>
          <ClipboardCheck size={18} />
          <span>Altwerte speichern</span>
        </button>
      </div>
    </div>
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
      { value: "coinbase", label: "Coinbase Transaction History" },
      { value: "bitget", label: "Bitget" },
      { value: "helium", label: "Helium Legacy/Fairspot" }
    ],
    api: [
      { value: "binance", label: "Binance" },
      { value: "bitget", label: "Bitget" },
      { value: "pionex", label: "Pionex" },
      { value: "coinbase", label: "Coinbase Live-Bestand" }
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
  connectorDiagnostics,
  onSaveCexCredentials,
  onRefreshConfiguredSources,
  sourceRefreshLoading
}: {
  connectorDiagnostics: Snapshot["sourceConnectorDiagnostics"];
  onSaveCexCredentials: (connectorId: string, apiKey: string, apiSecret: string, passphrase: string) => void;
  onRefreshConfiguredSources: () => void;
  sourceRefreshLoading: boolean;
}) {
  const [connectorId, setConnectorId] = useState("binance");
  const [apiKey, setApiKey] = useState("");
  const [apiSecret, setApiSecret] = useState("");
  const [passphrase, setPassphrase] = useState("");
  const needsPassphrase = connectorId === "bitget";
  const cexRows = (connectorDiagnostics?.diagnostics ?? []).filter((row) => row.connector_type === "cex");
  const activeDiagnostic = cexRows.find((row) => row.connector_id === connectorId);
  const missingCredentials = cexRows.filter((row) => row.credential_status !== "configured");
  const orderedRows = [
    ...missingCredentials,
    ...cexRows.filter((row) => row.credential_status === "configured")
  ];
  const firstMissing = missingCredentials[0];
  const selectConnector = (nextConnectorId: string) => {
    setConnectorId(nextConnectorId);
    setApiKey("");
    setApiSecret("");
    setPassphrase("");
  };
  useEffect(() => {
    const firstMissingId = firstMissing?.connector_id ? String(firstMissing.connector_id) : "";
    if (firstMissingId && activeDiagnostic?.credential_status === "configured") {
      selectConnector(firstMissingId);
    }
  }, [firstMissing?.connector_id, activeDiagnostic, connectorId]);
  const selectedKeysRequired = Number(activeDiagnostic?.credential_keys_required ?? (needsPassphrase ? 3 : 2));
  const selectedKeysPresent = Number(activeDiagnostic?.credential_keys_present ?? 0);
  return (
    <div className="panel formPanel">
      <div className="panelToolbar">
        <div>
          <strong>CEX-Credentials speichern</strong>
          <span>{missingCredentials.length} vorhandene CEX-Quelle(n) brauchen Credentials</span>
        </div>
        <button
          type="button"
          onClick={() => onSaveCexCredentials(connectorId, apiKey, apiSecret, passphrase)}
          disabled={!apiKey.trim() || !apiSecret.trim() || (needsPassphrase && !passphrase.trim())}
        >
          <Settings size={16} />
          <span>Verschluesselt speichern</span>
        </button>
      </div>
      <div className="connectorSetupNextStep">
        <span className={`statusPill ${missingCredentials.length > 0 ? "blocked" : "ok"}`}>
          {missingCredentials.length > 0 ? `${missingCredentials.length} offen` : "vollstaendig"}
        </span>
        <div>
          <strong>
            {activeDiagnostic
              ? `${String(activeDiagnostic.label ?? connectorId)}: ${sourceCredentialStatusLabel(activeDiagnostic.credential_status)}`
              : "Connector auswaehlen"}
          </strong>
          <p>
            Erforderliche Secret-Keys: {selectedKeysRequired}. Aktuell gespeichert: {selectedKeysPresent}.
            Nach dem Speichern sollte direkt `Live abfragen` ausgefuehrt werden, damit Product-Readiness den neuen Snapshot sieht.
          </p>
        </div>
        <button type="button" onClick={onRefreshConfiguredSources} disabled={sourceRefreshLoading || missingCredentials.length > 0}>
          <RefreshCcw size={16} />
          <span>{sourceRefreshLoading ? "Live-Abfrage laeuft" : "Live abfragen"}</span>
        </button>
      </div>
      <div className="connectorSetupGrid">
        {orderedRows.map((row) => {
          const tone = row.credential_status === "configured" ? "ok" : "blocked";
          return (
            <button
              key={String(row.connector_id)}
              className={`connectorSetupCard ${tone} ${connectorId === row.connector_id ? "active" : ""}`}
              type="button"
              onClick={() => selectConnector(String(row.connector_id))}
            >
              <span className={`statusPill ${tone}`}>{sourceCredentialStatusLabel(row.credential_status)}</span>
              <strong>{String(row.label ?? row.connector_id)}</strong>
              <em>{sourceConnectorStatusLabel(row.status)}</em>
              <small>
                Secret-Keys {String(row.credential_keys_present ?? 0)}/{String(row.credential_keys_required ?? 0)}
                {row.last_snapshot_at ? ` · Snapshot ${formatDateTime(row.last_snapshot_at)}` : " · kein Snapshot"}
              </small>
              <small>{String(row.next_action ?? "")}</small>
            </button>
          );
        })}
      </div>
      {activeDiagnostic ? (
        <div className={`connectorSetupHint ${activeDiagnostic.credential_status === "configured" ? "ok" : "blocked"}`}>
          <span className={`statusPill ${activeDiagnostic.credential_status === "configured" ? "ok" : "blocked"}`}>
            {sourceCredentialStatusLabel(activeDiagnostic.credential_status)}
          </span>
          <strong>{String(activeDiagnostic.message ?? "-")}</strong>
          <em>{String(activeDiagnostic.next_action ?? "-")}</em>
        </div>
      ) : null}
      <div className="formGrid">
        <label>
          Connector
          <select
            value={connectorId}
            onChange={(event) => {
              selectConnector(event.target.value);
            }}
          >
            <option value="binance">Binance</option>
            <option value="bitget">Bitget</option>
            <option value="pionex">Pionex</option>
            <option value="coinbase">Coinbase</option>
          </select>
        </label>
        <label>
          {connectorId === "coinbase" ? "CDP Key Name" : "API Key"}
          <input value={apiKey} type="password" autoComplete="off" onChange={(event) => setApiKey(event.target.value)} />
        </label>
        <label>
          {connectorId === "coinbase" ? "ECDSA Private Key" : "API Secret"}
          <textarea
            value={apiSecret}
            autoComplete="off"
            rows={connectorId === "coinbase" ? 5 : 2}
            placeholder={connectorId === "coinbase" ? "-----BEGIN EC PRIVATE KEY-----" : ""}
            onChange={(event) => setApiSecret(event.target.value)}
          />
        </label>
        <label>
          Passphrase {needsPassphrase ? "" : "(falls erforderlich)"}
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
                      <td key={column} title={fullValue(row[`${column}_full`] ?? row[column])} className={cellClass(column)}>
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

function formatDate(value: unknown): string {
  if (!value) {
    return "-";
  }
  const date = new Date(String(value));
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleDateString("de-DE", {
    dateStyle: "medium",
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
