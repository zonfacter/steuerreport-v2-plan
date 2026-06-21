from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class SolscanTokenMovementSummary(BaseModel):
    rows: int
    signatures: int
    incoming_quantity: Decimal
    outgoing_quantity: Decimal
    net_quantity: Decimal


class SolscanFileCoverage(BaseModel):
    first_event_at: str | None = None
    last_event_at: str | None = None
    first_token_event_at: str | None = None
    last_token_event_at: str | None = None


class SolscanBlockpitMissingSignature(BaseModel):
    signature: str
    event_time: str
    label: str
    quantity: Decimal


class SolscanMissingSignatureSummary(BaseModel):
    period: str
    label: str
    signatures: int
    net_quantity: Decimal


class SolscanCoverageCheckpoint(BaseModel):
    cutoff_at: str
    blockpit_net_quantity: Decimal
    solscan_net_quantity: Decimal
    delta_quantity: Decimal


class SolscanRpcEvidenceSummary(BaseModel):
    status: str
    artifact_path: str | None = None
    signatures_total: int = 0
    verified: int = 0
    failed: int = 0
    rate_limited: int = 0
    expected_quantity_sum: Decimal = Decimal("0")
    wallet_delta_quantity_sum: Decimal = Decimal("0")
    quantity_delta_sum: Decimal = Decimal("0")


class SolscanTokenPreflightReport(BaseModel):
    file_path: str
    blockpit_file_path: str
    wallet: str
    asset: str
    token_address: str
    max_year: int | None
    file_coverage: SolscanFileCoverage
    solscan: SolscanTokenMovementSummary
    blockpit: SolscanTokenMovementSummary
    matched_signatures: int
    blockpit_missing_signatures: int
    solscan_extra_signatures: int
    matched_quantity_delta: Decimal
    missing_summary: list[SolscanMissingSignatureSummary]
    missing_blockpit_signatures: list[SolscanBlockpitMissingSignature]
    coverage_checkpoints: list[SolscanCoverageCheckpoint]
    rpc_evidence: SolscanRpcEvidenceSummary
    target_changed: bool = False


class SolanaRpcProbeRequest(BaseModel):
    file_path: str = "/workspace/steuerreport/usertransfer/legacy_daten/Steuer-2022/export-solscan.csv"
    blockpit_file_path: str = "/workspace/steuerreport/usertransfer/blockpit/blockpit 09052026 Transactions.csv"
    wallet: str = "G39FV6RkM6U4LTGMcph7HWi7zZQJavzGaw9YvSvueLhY"
    asset: str = "IOT"
    token_address: str = "iotEVVZLEywoTn1QdwNPddxPWszn3zFhEot3MfL9fns"
    max_year: int | None = 2024
    rpc_url: str = "https://api.mainnet-beta.solana.com"
    signatures: list[str] = Field(default_factory=list)
    max_requests: int = 5
    timeout_seconds: int = 20
    delay_seconds: Decimal = Decimal("0")


class SolanaRpcSignatureProbe(BaseModel):
    signature: str
    status: str
    expected_quantity: Decimal | None = None
    wallet_delta_quantity: Decimal | None = None
    quantity_delta: Decimal | None = None
    block_time: str | None = None
    slot: int | None = None
    label: str | None = None
    reason: str | None = None


class SolanaRpcProbeResult(BaseModel):
    requested_signatures: int
    attempted: int
    verified: int
    failed: int
    rate_limited: int
    target_changed: bool = False
    jobs: list[SolanaRpcSignatureProbe]


class SolscanEvidenceTraceStep(BaseModel):
    step_id: str
    label: str
    status: str
    evidence_ref: str | None = None
    import_effect: str = "none"
    note: str


class SolscanEvidenceTraceReport(BaseModel):
    asset: str
    wallet: str
    token_address: str
    max_year: int | None
    status: str
    target_changed: bool = False
    import_effect: str = "none"
    missing_signatures: int
    verified_signatures: int
    quantity_delta_sum: Decimal
    preflight: SolscanTokenPreflightReport
    trace_steps: list[SolscanEvidenceTraceStep] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    review_scope: str | None = None
    review_suggestion_id: str | None = None
    methodology: str
