"""Interne, geheimnisfreie Seitenvertraege fuer automatische Historienabrufe."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable


@dataclass(frozen=True)
class HistoryTarget:
    source_ref: str
    label: str
    provider: str
    account: str
    wallet_address: str | None = None
    connection_id: str | None = None
    budget_groups: tuple[str, ...] = ()
    legacy_credentials: bool = False


@dataclass(frozen=True)
class HistoryOptions:
    start: datetime
    end: datetime
    symbols: tuple[str, ...] = ()
    public_rpc_only: bool = False


@dataclass(frozen=True)
class HistoryRecord:
    # Stable within one provider account, independent of page and job IDs.
    identity: str
    source: str
    rows: list[dict[str, object]]
    raw: dict[str, object]


@dataclass(frozen=True)
class HistoryPage:
    records: list[HistoryRecord]
    cursor: dict[str, object]
    done: bool
    notes: tuple[str, ...] = ()
    requests: int = 0
    phase: str = "Transaktionen abrufen"
    # False unless the adapter can prove more than its own endpoint coverage.
    complete_history_proven: bool = False
    extra: dict[str, object] = field(default_factory=dict)


class HistoryFetchError(RuntimeError):
    def __init__(self, code: str, *, resumable: bool = True) -> None:
        super().__init__(code)
        self.code = code
        self.resumable = resumable


Checkpoint = Callable[[], None]
