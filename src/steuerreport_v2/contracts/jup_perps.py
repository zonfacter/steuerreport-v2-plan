from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class JupPerpsAssetSummary(BaseModel):
    asset: str
    rows: int
    increases: int
    decreases: int
    trade_size_usd: Decimal
    collateral_flow_usd: Decimal
    realized_pnl_usd: Decimal
    trade_fee_usd: Decimal
    liquidation_fee_usd: Decimal
    net_result_usd: Decimal
    net_result_eur: Decimal


class JupPerpsPreviewRow(BaseModel):
    event_time: datetime
    tx_id: str
    asset: str
    position: str
    position_change: str
    order_type: str
    collateral_flow_usd: Decimal
    execution_price_usd: Decimal
    trade_size_usd: Decimal
    realized_pnl_usd: Decimal
    trade_fee_usd: Decimal
    liquidation_fee_usd: Decimal
    net_result_usd: Decimal
    usd_eur: Decimal
    net_result_eur: Decimal


class JupPerpsPreview(BaseModel):
    file_path: str
    row_count: int
    assets: list[str]
    increases: int
    decreases: int
    collateral_flow_usd: Decimal
    realized_pnl_usd: Decimal
    trade_fee_usd: Decimal
    liquidation_fee_usd: Decimal
    net_result_usd: Decimal
    net_result_eur: Decimal
    missing_fx_count: int
    asset_summaries: list[JupPerpsAssetSummary]
    sample_rows: list[JupPerpsPreviewRow]
