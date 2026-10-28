"""Originale Tokenidentitaet vor Preisplanung und Freigabe pruefen, nie raten."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
import json
import re

from steuerreport_v2.db.duckdb_store import DuckDbStore


_MINT = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
_EVM = re.compile(r"0x[0-9a-fA-F]{40}")
_ALIASES = {"eth": "ethereum", "eip155:1": "ethereum", "sol": "solana"}


def network_name(value: str) -> str:
    normalized = value.strip().lower()
    return _ALIASES.get(normalized, normalized)


@dataclass(frozen=True)
class TokenIdentity:
    network: str
    contract: str
    decimals: int | None = None

    @property
    def key(self) -> tuple[str, str]:
        return self.network, self.contract

    @property
    def provider_id(self) -> str:
        return self.network + ":" + self.contract


def identity_from_payload(payload: dict, *, role: str, source: str,
                          quantity: Decimal) -> TokenIdentity | None:
    prefix = "" if role == "asset" else "quote_" if role == "quote_asset" else "fee_"
    mint = payload.get(prefix + "mint")
    contract = mint or payload.get(prefix + "contract_address") or payload.get(prefix + "token_address")
    if contract is None:
        return None
    if not isinstance(contract, str) or not contract.strip():
        raise ValueError("asset_contract_invalid")
    contract = contract.strip()
    network = payload.get(prefix + "network") or payload.get(prefix + "chain")
    if network is None and (mint is not None or "solana" in source.lower()):
        network = "solana"
    if not isinstance(network, str) or not network.strip():
        raise ValueError("asset_network_missing")
    network = network_name(network)
    if network == "solana":
        if _MINT.fullmatch(contract) is None:
            raise ValueError("asset_contract_invalid")
    elif contract.startswith("0x"):
        if _EVM.fullmatch(contract) is None:
            raise ValueError("asset_contract_invalid")
        contract = contract.lower()
    elif re.fullmatch(r"[A-Za-z0-9_.:/-]{1,150}", contract) is None:
        raise ValueError("asset_contract_invalid")
    decimals = payload.get(prefix + "decimals")
    if decimals is not None:
        if isinstance(decimals, bool) or not isinstance(decimals, (int, str)):
            raise ValueError("asset_decimals_invalid")
        if isinstance(decimals, str) and not decimals.isdecimal():
            raise ValueError("asset_decimals_invalid")
        decimals = int(decimals)
        if not 0 <= decimals <= 255:
            raise ValueError("asset_decimals_invalid")
    raw_amount = payload.get(prefix + "amount_raw")
    if raw_amount is not None:
        if decimals is None:
            raise ValueError("asset_decimals_missing_for_raw_amount")
        try:
            amount = Decimal(str(raw_amount))
            if not amount.is_finite() or amount != amount.to_integral_value():
                raise ValueError("asset_raw_amount_invalid")
            with localcontext() as context:
                context.prec = 80
                if abs(amount.scaleb(-decimals)) != abs(quantity):
                    raise ValueError("asset_quantity_decimals_mismatch")
        except InvalidOperation as exc:
            raise ValueError("asset_raw_amount_invalid") from exc
    return TokenIdentity(network, contract, decimals)


class AssetIdentityIndex:
    def __init__(self, store: DuckDbStore) -> None:
        self.identities: dict[str, TokenIdentity] = {}
        self.problems: dict[str, str] = {}
        candidates: dict[str, list[TokenIdentity]] = {}
        with store.connect() as con:
            rows = con.execute("""select e.asset,e.quantity,e.quote_asset,e.quote_quantity,
                e.fee_asset,e.fee_quantity,e.source,r.payload_json from canonical_events e
                join raw_objects r on r.raw_object_id=e.raw_object_id order by e.event_id""").fetchall()
        for asset, quantity, quote, quote_quantity, fee, fee_quantity, source, raw in rows:
            try:
                payload = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if not isinstance(payload, dict):
                continue
            for role, symbol, amount in (("asset", asset, quantity), ("quote_asset", quote, quote_quantity),
                                         ("fee_asset", fee, fee_quantity)):
                if not symbol or not amount or symbol.upper() == "EUR":
                    continue
                symbol = symbol.upper()
                try:
                    identity = identity_from_payload(payload, role=role, source=source, quantity=amount)
                    if identity:
                        candidates.setdefault(symbol, []).append(identity)
                except ValueError as exc:
                    self.problems[symbol] = str(exc)
        for symbol, identities in candidates.items():
            if len({row.key for row in identities}) > 1:
                self.problems[symbol] = "asset_identity_conflict"
            elif len({row.decimals for row in identities if row.decimals is not None}) > 1:
                self.problems[symbol] = "asset_decimals_conflict"
            else:
                self.identities[symbol] = max(identities, key=lambda row: row.decimals is not None)

    def problems_for_mappings(self, mappings: dict) -> dict[str, str]:
        problems = dict(self.problems)
        for symbol, identity in self.identities.items():
            mapping = mappings.get(symbol, {})
            configured = mapping.get("defillama_id")
            network = mapping.get("network")
            contract = mapping.get("contract_address") or mapping.get("solana_mint")
            if contract and identity.network != "solana" and contract.startswith("0x"):
                contract = contract.lower()
            if ((configured and configured != identity.provider_id and not configured.startswith("coingecko:"))
                    or (network and network_name(network) != identity.network)
                    or (contract and contract != identity.contract)
                    or (mapping.get("decimals") is not None and identity.decimals is not None
                        and mapping["decimals"] != identity.decimals)):
                problems[symbol] = "price_mapping_identity_mismatch"
        return problems

    def apply_to_plan(self, rows: list[dict], mappings: dict, *, provider: str) -> None:
        problems = self.problems_for_mappings(mappings)
        for row in rows:
            symbol = row["asset"].upper()
            reason = problems.get(symbol)
            identity = self.identities.get(symbol)
            if identity:
                row["asset_identity"] = {"network": identity.network, "contract_address": identity.contract,
                                         "decimals": identity.decimals, "basis": "original_raw_object"}
                if not reason and provider == "defillama":
                    row["provider_id"] = identity.provider_id
                    if row.get("reason") == "asset_not_configured":
                        row.update(status="planned", reason=None)
            if reason:
                row.update(status="blocked", reason=reason, price_eur=None, priced_at=None, source=None)
