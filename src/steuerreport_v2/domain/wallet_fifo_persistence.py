from __future__ import annotations

from typing import TYPE_CHECKING

from steuerreport_v2.contracts.tax import TaxLine, TaxLot
from steuerreport_v2.domain.fifo_methods import WALLET_DEPOT_FIFO_SCOPE

if TYPE_CHECKING:
    from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoReplayState


def wallet_fifo_tax_rows(
    state: WalletFifoReplayState,
) -> tuple[list[TaxLot], list[TaxLine]]:
    lots = [
        TaxLot(
            lot_id=item.lot_id,
            asset=item.asset,
            acquired_at=item.acquired_at,
            quantity_total=item.quantity_total,
            quantity_remaining=item.quantity_remaining,
            cost_basis_eur_total=item.cost_basis_eur_total,
            source_event_id=item.source_event_id,
            pool_id=item.pool_id,
            origin_lot_id=item.origin_lot_id,
            fifo_method=WALLET_DEPOT_FIFO_SCOPE,
        )
        for item in state.all_lots
    ]
    lines = [
        TaxLine(
            tax_line_id=item.tax_line_id,
            asset=item.asset,
            acquired_at=item.acquired_at,
            disposed_at=item.disposed_at,
            quantity=item.quantity,
            acquisition_cost_eur=item.acquisition_cost_eur,
            disposal_proceeds_eur=item.disposal_proceeds_eur,
            gain_loss_eur=item.gain_loss_eur,
            holding_days=item.holding_days,
            source_event_id=item.source_event_id,
            lot_id=item.lot_id,
            pool_id=item.pool_id,
            acquisition_source_event_id=item.acquisition_source_event_id,
            origin_lot_id=item.origin_lot_id,
            fifo_method=WALLET_DEPOT_FIFO_SCOPE,
        )
        for item in state.tax_lines
    ]
    return lots, lines
