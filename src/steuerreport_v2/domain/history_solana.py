"""Wiederaufnehmbare Solana-Seiten, ohne Import oder Ledger-Schreibzugriffe."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Callable

from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.history_types import (
    HistoryFetchError, HistoryOptions, HistoryPage, HistoryRecord, HistoryTarget,
)
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.request_limits import RequestCancelled, RequestDeadlineExceeded


_BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _identifier(value: object, size: int) -> bool:
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 90:
        return False
    try:
        number = 0
        for character in value:
            number = number * 58 + _BASE58.index(character)
        return (number.bit_length() + 7) // 8 + len(value) - len(value.lstrip("1")) == size
    except ValueError:
        return False


class SolanaHistoryCollector(PortfolioService):
    PAGE_SIZE = 25
    DETAILS_PER_PAGE = 5
    MAX_ADDRESSES = 5000
    PUBLIC_RPC_URL = "https://api.mainnet.solana.com"
    NOTES = (
        "Aktuelle SPL-/Token-2022-Owner-Konten beweisen keine vollstaendige historische "
        "Eigentuemerschaft; geschlossene Tokenkonten/ATAs koennen fehlen.",
        "RPC-Seitenende beweist keine vollstaendige Solana-Historie; Provider koennen "
        "historische Daten begrenzen. Die Vollstaendigkeit bleibt unbestaetigt.",
    )

    def __init__(self, store: DuckDbStore, target: HistoryTarget, options: HistoryOptions) -> None:
        if not _identifier(target.wallet_address, 32):
            raise HistoryFetchError("solana_wallet_address_required", resumable=False)
        if options.symbols:
            raise HistoryFetchError("solana_asset_filter_not_supported", resumable=False)
        for bound in (options.start, options.end):
            if not isinstance(bound, datetime) or bound.tzinfo is None or bound.utcoffset() is None:
                raise HistoryFetchError("solana_time_window_invalid", resumable=False)
        if options.start > options.end:
            raise HistoryFetchError("solana_time_window_invalid", resumable=False)
        super().__init__(store)
        self.target, self.options = target, options
        self.wallet_address = target.wallet_address
        self.start, self.end = options.start.astimezone(timezone.utc), options.end.astimezone(timezone.utc)

    def _solana_rpc_urls(self) -> list[str]:
        # Vor jeder Secret-, Profil- oder Umgebungsaufloesung abbrechen.
        if self.options.public_rpc_only:
            return [self.PUBLIC_RPC_URL]
        return super()._solana_rpc_urls()

    def _scope(self) -> dict[str, object]:
        return {
            "source_ref": self.target.source_ref,
            "provider": self.target.provider, "account": self.target.account,
            "wallet_address": self.wallet_address,
            "start": self.start.isoformat(), "end": self.end.isoformat(),
            "public_rpc_only": self.options.public_rpc_only,
            "symbols": list(self.options.symbols),
        }

    def _owner_address(self, entry: object, program: str) -> dict[str, object]:
        if not isinstance(entry, dict) or not _identifier(entry.get("pubkey"), 32):
            raise HistoryFetchError("solana_owner_accounts_invalid")
        account = entry.get("account")
        data = account.get("data") if isinstance(account, dict) else None
        parsed = data.get("parsed") if isinstance(data, dict) else None
        info = parsed.get("info") if isinstance(parsed, dict) else None
        if (
            not isinstance(account, dict) or account.get("owner") != program
            or not isinstance(parsed, dict) or parsed.get("type") != "account"
            or not isinstance(info, dict) or info.get("owner") != self.wallet_address
            or not _identifier(info.get("mint"), 32) or entry["pubkey"] == self.wallet_address
        ):
            raise HistoryFetchError("solana_owner_accounts_invalid")
        # Es gibt auch nicht-assoziierte Tokenkonten. Keine ATA aus einem Mint ableiten.
        return {"address": entry["pubkey"], "mint": info["mint"], "program": program,
                "owner_account": deepcopy(entry)}

    def _signature_page(self, payload: object) -> list[dict[str, object]]:
        if not isinstance(payload, list) or len(payload) > self.PAGE_SIZE:
            raise HistoryFetchError("solana_signatures_invalid")
        signatures: set[str] = set()
        for item in payload:
            if not isinstance(item, dict) or not _identifier(item.get("signature"), 64):
                raise HistoryFetchError("solana_signatures_invalid")
            signature = item["signature"]
            if signature in signatures:
                raise HistoryFetchError("solana_signature_cursor_loop")
            signatures.add(signature)
            block_time = item.get("blockTime")
            if block_time is not None and (type(block_time) is not int or block_time < 0):
                raise HistoryFetchError("solana_signatures_invalid")
            if "confirmationStatus" in item and item["confirmationStatus"] != "finalized":
                raise HistoryFetchError("solana_signatures_not_finalized")
        return deepcopy(payload)

    def _state(self, cursor: dict) -> dict:
        if not isinstance(cursor, dict):
            raise HistoryFetchError("solana_cursor_invalid", resumable=False)
        if not cursor:
            return {
                "version": 1, "scope": self._scope(), "discovered": False,
                "addresses": [{"address": self.wallet_address}], "scan_index": 0,
                "before": None, "pending": [], "pending_before": None,
                "scan_seen": [], "seen": [],
            }
        state = deepcopy(cursor)
        try:
            if type(state["version"]) is not int or state["version"] != 1:
                raise ValueError
            if state["scope"] != self._scope() or type(state["discovered"]) is not bool:
                raise ValueError
            addresses = state["addresses"]
            if not isinstance(addresses, list) or not 1 <= len(addresses) <= self.MAX_ADDRESSES:
                raise ValueError
            if addresses[0] != {"address": self.wallet_address}:
                raise ValueError
            for item in addresses[1:]:
                if item["program"] not in self.SOLANA_TOKEN_PROGRAM_IDS:
                    raise ValueError
                if self._owner_address(item["owner_account"], item["program"]) != item:
                    raise ValueError
            if len({item["address"] for item in addresses}) != len(addresses):
                raise ValueError
            index = state["scan_index"]
            if type(index) is not int or not 0 <= index <= len(addresses):
                raise ValueError
            for field in ("seen", "scan_seen"):
                values = state[field]
                if not isinstance(values, list) or any(not _identifier(v, 64) for v in values):
                    raise ValueError
                if len(set(values)) != len(values):
                    raise ValueError
            pending = self._signature_page(state["pending"])
            for field in ("before", "pending_before"):
                if state[field] is not None and not _identifier(state[field], 64):
                    raise ValueError
            if state["before"] is not None and state["before"] not in state["scan_seen"]:
                raise ValueError
            if pending:
                if index == len(addresses) or state["pending_before"] != pending[-1]["signature"]:
                    raise ValueError
                if [item["signature"] for item in pending] != state["scan_seen"][-len(pending):]:
                    raise ValueError
            elif state["pending_before"] is not None:
                raise ValueError
            elif state["before"] != (state["scan_seen"][-1] if state["scan_seen"] else None):
                raise ValueError
            if not state["discovered"] and state != self._state({}):
                raise ValueError
            if index == len(addresses) and (pending or state["before"] or state["scan_seen"]):
                raise ValueError
        except (KeyError, TypeError, ValueError, HistoryFetchError):
            raise HistoryFetchError("solana_cursor_invalid", resumable=False) from None
        return state

    def fetch_page(self, cursor: dict, check: Callable[[], None]) -> HistoryPage:
        state = self._state(cursor)
        requests = 0

        def rpc(method: str, params: list[object]) -> object:
            nonlocal requests
            check()
            requests += 1
            try:
                return self._solana_rpc(method, params, timeout_seconds=30)
            except (RequestCancelled, RequestDeadlineExceeded):
                raise
            except Exception:
                # Der Legacy-RPC-Helfer kann Transportabbruch als RuntimeError melden.
                check()
                code = "solana_transaction_fetch_failed" if method == "getTransaction" else "solana_rpc_failed"
                raise HistoryFetchError(code) from None

        if not state["discovered"]:
            by_address = {self.wallet_address: state["addresses"][0]}
            for program in self.SOLANA_TOKEN_PROGRAM_IDS:
                payload = rpc("getTokenAccountsByOwner", [
                    self.wallet_address, {"programId": program},
                    {"encoding": "jsonParsed", "commitment": "finalized"},
                ])
                entries = payload.get("value") if isinstance(payload, dict) else None
                if not isinstance(entries, list):
                    raise HistoryFetchError("solana_owner_accounts_invalid")
                for entry in entries:
                    owned = self._owner_address(entry, program)
                    old = by_address.get(owned["address"])
                    if old is not None and old != owned:
                        raise HistoryFetchError("solana_owner_accounts_conflict")
                    by_address[owned["address"]] = owned
                    if len(by_address) > self.MAX_ADDRESSES:
                        raise HistoryFetchError("solana_address_limit", resumable=False)
            state["addresses"] = list(by_address.values())
            state["discovered"] = True

        records: list[HistoryRecord] = []
        index = state["scan_index"]
        if index < len(state["addresses"]):
            address = state["addresses"][index]
            if not state["pending"]:
                config = {"limit": self.PAGE_SIZE, "commitment": "finalized"}
                if state["before"] is not None:
                    config["before"] = state["before"]
                page = self._signature_page(rpc("getSignaturesForAddress", [address["address"], config]))
                scan_seen = set(state["scan_seen"])
                if any(item["signature"] in scan_seen for item in page):
                    raise HistoryFetchError("solana_signature_cursor_loop")
                if not page:
                    state.update(scan_index=index + 1, before=None, scan_seen=[])
                else:
                    state["pending"] = page
                    state["pending_before"] = page[-1]["signature"]
                    state["scan_seen"].extend(item["signature"] for item in page)

            seen = set(state["seen"])
            details = 0
            while state["pending"]:
                item = state["pending"][0]
                signature = item["signature"]
                if signature in seen:
                    state["pending"].pop(0)
                    continue
                if details >= self.DETAILS_PER_PAGE:
                    break
                tx = rpc("getTransaction", [signature, {
                    "encoding": "jsonParsed", "maxSupportedTransactionVersion": 0,
                    "commitment": "finalized",
                }])
                details += 1
                if not isinstance(tx, dict):
                    raise HistoryFetchError("solana_transaction_missing")
                try:
                    rows = self._solana_transaction_rows(self.wallet_address, signature, tx)
                    transaction = tx["transaction"]
                    if "signatures" in transaction and (
                        not isinstance(transaction["signatures"], list)
                        or not transaction["signatures"] or transaction["signatures"][0] != signature
                    ):
                        raise ValueError
                    timestamp = datetime.fromtimestamp(tx["blockTime"], timezone.utc)
                except (RequestCancelled, RequestDeadlineExceeded):
                    raise
                except Exception:
                    check()
                    raise HistoryFetchError("solana_transaction_incomplete") from None
                if self.start <= timestamp <= self.end:
                    records.append(HistoryRecord(
                        identity="solana:" + signature, source="solana_rpc", rows=rows,
                        raw={"source_ref": self.target.source_ref,
                             "wallet_address": self.wallet_address, "signature": signature,
                             "signature_info": deepcopy(item), "transaction": deepcopy(tx),
                             "scan_address": address["address"], "address_evidence": deepcopy(address)},
                    ))
                state["seen"].append(signature)
                seen.add(signature)
                state["pending"].pop(0)
            # before bleibt bis zum letzten erfolgreichen Detail auf der alten Seite.
            if not state["pending"] and state["pending_before"] is not None:
                state["before"] = state["pending_before"]
                state["pending_before"] = None

        check()
        return HistoryPage(
            records=records, cursor=state, done=state["scan_index"] == len(state["addresses"]),
            requests=requests, notes=self.NOTES, complete_history_proven=False,
            extra={"scan_address_index": state["scan_index"], "scan_address_count": len(state["addresses"])},
        )
