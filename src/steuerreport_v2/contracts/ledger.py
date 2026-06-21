from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class BalanceLedgerEntry(BaseModel):
    ledger_id: str
    event_id: str
    event_time: datetime
    account: str
    asset: str
    delta_quantity: Decimal
    balance_quantity: Decimal


class BalancePosition(BaseModel):
    account: str
    asset: str
    quantity: Decimal
