from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from steuerreport_v2.contracts.business_inventory import BusinessRewardOriginStatus


BmfFifoStagingStatus = Literal[
    "blocked",
    "review",
    "ready_for_professional_review",
]


class BmfFifoStagingRunRequest(BaseModel):
    years: list[int] = Field(
        default_factory=lambda: [2021, 2022, 2023, 2024, 2025, 2026],
        min_length=1,
    )
    as_of: datetime | None = None
    limit: int = Field(default=200, ge=1, le=5000)


class BmfFifoScenarioTotals(BaseModel):
    tax_lines_count: int = 0
    unmatched_count: int = 0
    acquisition_cost_eur: Decimal = Decimal("0")
    disposal_proceeds_eur: Decimal = Decimal("0")
    gain_loss_eur: Decimal = Decimal("0")


class BmfCombinedFifoYearRow(BaseModel):
    year: int
    active_global: BmfFifoScenarioTotals
    received_first_global: BmfFifoScenarioTotals
    active_wallet: BmfFifoScenarioTotals
    received_first_wallet: BmfFifoScenarioTotals
    price_policy_delta_eur: Decimal = Decimal("0")
    wallet_scope_delta_eur: Decimal = Decimal("0")
    combined_delta_eur: Decimal = Decimal("0")
    interaction_delta_eur: Decimal = Decimal("0")
    potential_business_inventory_tax_lines_count: int = 0
    unresolved_reward_origin_tax_lines_count: int = 0
    potential_business_inventory_gain_loss_eur: Decimal = Decimal("0")
    unresolved_reward_origin_gain_loss_eur: Decimal = Decimal("0")
    outside_reward_scope_gain_loss_eur: Decimal = Decimal("0")


class BmfCombinedFifoAssetRow(BaseModel):
    year: int
    asset: str
    active_global_gain_loss_eur: Decimal = Decimal("0")
    received_first_global_gain_loss_eur: Decimal = Decimal("0")
    active_wallet_gain_loss_eur: Decimal = Decimal("0")
    received_first_wallet_gain_loss_eur: Decimal = Decimal("0")
    price_policy_delta_eur: Decimal = Decimal("0")
    wallet_scope_delta_eur: Decimal = Decimal("0")
    combined_delta_eur: Decimal = Decimal("0")
    interaction_delta_eur: Decimal = Decimal("0")
    received_first_wallet_tax_lines_count: int = 0
    potential_business_inventory_tax_lines_count: int = 0
    unresolved_reward_origin_tax_lines_count: int = 0


class BmfCombinedFifoSphereRow(BaseModel):
    year: int
    asset: str
    classification: BusinessRewardOriginStatus | Literal["outside_reward_scope"]
    origin_events_count: int = 0
    tax_lines_count: int = 0
    quantity: Decimal = Decimal("0")
    acquisition_cost_eur: Decimal = Decimal("0")
    disposal_proceeds_eur: Decimal = Decimal("0")
    gain_loss_eur: Decimal = Decimal("0")


class BmfCombinedFifoEventRow(BaseModel):
    year: int
    asset: str
    disposal_event_id: str
    disposed_at: datetime
    source: str | None = None
    account: str | None = None
    tx_id: str | None = None
    wallet_pool_ids: list[str] = Field(default_factory=list)
    acquisition_source_event_ids: list[str] = Field(default_factory=list)
    origin_classifications: list[str] = Field(default_factory=list)
    lineage_issue_codes: list[str] = Field(default_factory=list)
    direct_acquisition_event_ids: list[str] = Field(default_factory=list)
    active_global_quantity: Decimal = Decimal("0")
    received_first_global_quantity: Decimal = Decimal("0")
    active_wallet_quantity: Decimal = Decimal("0")
    received_first_wallet_quantity: Decimal = Decimal("0")
    active_global_gain_loss_eur: Decimal = Decimal("0")
    received_first_global_gain_loss_eur: Decimal = Decimal("0")
    active_wallet_gain_loss_eur: Decimal = Decimal("0")
    received_first_wallet_gain_loss_eur: Decimal = Decimal("0")
    price_policy_delta_eur: Decimal = Decimal("0")
    wallet_scope_delta_eur: Decimal = Decimal("0")
    combined_delta_eur: Decimal = Decimal("0")
    interaction_delta_eur: Decimal = Decimal("0")


class BmfCombinedFifoStagingReport(BaseModel):
    run_id: str
    generated_at: datetime
    as_of: datetime
    years: list[int] = Field(default_factory=list)
    status: BmfFifoStagingStatus
    strict_ready: bool = False
    read_only: Literal[True] = True
    active_global_policy: str
    received_first_global_policy: str
    active_wallet_policy: str
    received_first_wallet_policy: str
    wallet_method_version: str
    input_fingerprint_digest: str
    productive_tax_component_sha256: str
    productive_tax_tables_unchanged: bool = False
    active_global: BmfFifoScenarioTotals
    received_first_global: BmfFifoScenarioTotals
    active_wallet: BmfFifoScenarioTotals
    received_first_wallet: BmfFifoScenarioTotals
    price_policy_delta_eur: Decimal = Decimal("0")
    wallet_scope_delta_eur: Decimal = Decimal("0")
    combined_delta_eur: Decimal = Decimal("0")
    interaction_delta_eur: Decimal = Decimal("0")
    absolute_year_combined_delta_eur: Decimal = Decimal("0")
    potential_business_inventory_tax_lines_count: int = 0
    unresolved_reward_origin_tax_lines_count: int = 0
    affected_years: list[int] = Field(default_factory=list)
    year_rows: list[BmfCombinedFifoYearRow] = Field(default_factory=list)
    top_assets: list[BmfCombinedFifoAssetRow] = Field(default_factory=list)
    sphere_rows: list[BmfCombinedFifoSphereRow] = Field(default_factory=list)
    top_events: list[BmfCombinedFifoEventRow] = Field(default_factory=list)
    artifact_path: str
    latest_artifact_path: str
    findings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    methodology: str
