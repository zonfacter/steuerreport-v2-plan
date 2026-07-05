from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from steuerreport_v2.contracts.jupiter import (
    JupiterTokenAudit,
    JupiterTokenMetadataCacheItem,
    JupiterTokenMetadataCacheResult,
    JupiterTokenMetadataRefreshResult,
    JupiterTokenRiskReviewResult,
    JupiterTokenSearchItem,
    JupiterTokenSearchResult,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.secrets import resolve_secret_value


class JupiterTokenService:
    SEARCH_URL = "https://api.jup.ag/tokens/v2/search"
    V1_DB_PATH = Path("/root/.local/share/steuerreport/steuerreport.db")
    SOLANA_MINT_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
    MINT_KEY_HINTS = {
        "mint",
        "mintaddress",
        "mint_address",
        "tokenmint",
        "token_mint",
        "tokenaddress",
        "token_address",
        "tokenaccountmint",
    }
    SECRET_KEYS = (
        "secret.jupiter.api_key",
        "secret.jup.api_key",
        "secret.jup_ag.api_key",
    )

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def search(self, query: str) -> JupiterTokenSearchResult:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query_required")
        mint_queries = [item.strip() for item in normalized_query.split(",") if item.strip()]
        if len(mint_queries) > 100:
            raise ValueError("query_mint_limit_100")

        api_key = self._api_key()
        if not api_key:
            return JupiterTokenSearchResult(
                generated_at=datetime.now(timezone.utc),
                query=normalized_query,
                configured=False,
                status="missing_api_key",
                methodology=(
                    "Read-only Jupiter Token Search. Es wurde kein API-Key "
                    "gefunden; der Endpunkt fuehrt ohne Key keine externe "
                    "Abfrage aus."
                ),
            )

        with httpx.Client(timeout=20) as client:
            response = client.get(
                self.SEARCH_URL,
                headers={"x-api-key": api_key},
                params={"query": normalized_query},
            )
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, list):
            raise ValueError("unexpected_jupiter_response")
        tokens = [self._token_from_payload(item) for item in payload if isinstance(item, dict)]
        return JupiterTokenSearchResult(
            generated_at=datetime.now(timezone.utc),
            query=normalized_query,
            configured=True,
            status="ok",
            tokens=tokens,
            tokens_count=len(tokens),
            methodology=(
                "Read-only Suche ueber Jupiter Token API v2. Der API-Key wird "
                "nur als x-api-key Header genutzt und nicht in Responses "
                "ausgegeben. Die Ergebnisse schreiben keine Preise, Imports, "
                "FIFO-Lots oder Steuerdaten."
            ),
        )

    def _api_key(self) -> str:
        for key in self.SECRET_KEYS:
            value = self._secret_value(key)
            if value:
                return value
        for env_key in ("JUPITER_API_KEY", "JUP_API_KEY", "JUP_AG_API_KEY"):
            value = os.environ.get(env_key, "").strip()
            if value:
                return value
        return ""

    def _secret_value(self, key: str) -> str:
        return resolve_secret_value(self.store, key)

    def metadata_cache(self, limit: int = 200) -> JupiterTokenMetadataCacheResult:
        normalized_limit = min(max(int(limit), 1), 1000)
        candidates = self._mint_candidates(raw_limit=50000)
        cached_mints = self._cached_mints()
        return JupiterTokenMetadataCacheResult(
            generated_at=datetime.now(timezone.utc),
            configured=bool(self._api_key()),
            status="ok",
            candidates_count=len(candidates),
            cached_count=len(cached_mints),
            uncached_count=len([mint for mint in candidates if mint not in cached_mints]),
            items=self._cached_items(limit=normalized_limit),
            methodology=(
                "Read-only Jupiter-Metadata-Cache fuer Solana-Mints aus vorhandenen "
                "V2-Daten. Der Cache schreibt nur Token-Metadaten und keine Preise, "
                "Imports, FIFO-Lots, Tax-Lines oder Review-Entscheidungen."
            ),
        )

    def cached_metadata_by_asset(self) -> dict[str, JupiterTokenMetadataCacheItem]:
        result: dict[str, JupiterTokenMetadataCacheItem] = {}
        for item in sorted(self._cached_items(limit=10000), key=self._metadata_rank):
            result.setdefault(item.mint, item)
            if item.symbol:
                result.setdefault(item.symbol.upper(), item)
        return result

    def risk_review(self, risk_status: str = "spam_review", limit: int = 200) -> JupiterTokenRiskReviewResult:
        normalized_risk = str(risk_status or "spam_review").strip().lower()
        allowed = {"spam_review", "review", "unverified_plausible", "verified", "all"}
        if normalized_risk not in allowed:
            raise ValueError("unsupported_risk_status")
        normalized_limit = min(max(int(limit), 1), 1000)
        all_items = self._cached_items(limit=10000)
        filtered = [
            item
            for item in all_items
            if normalized_risk == "all" or item.risk_status == normalized_risk
        ][:normalized_limit]
        return JupiterTokenRiskReviewResult(
            generated_at=datetime.now(timezone.utc),
            status="ok",
            risk_status=normalized_risk,
            items_count=len(filtered),
            spam_review_count=sum(1 for item in all_items if item.risk_status == "spam_review"),
            review_count=sum(1 for item in all_items if item.risk_status == "review"),
            unverified_plausible_count=sum(1 for item in all_items if item.risk_status == "unverified_plausible"),
            verified_count=sum(1 for item in all_items if item.risk_status == "verified"),
            items=filtered,
            methodology=(
                "Read-only Token-Risk-Review aus `jupiter_token_metadata_cache`. "
                "Markierungen wie spam_review sind Anzeige-/Pruefsignale und "
                "loeschen keine Bestands-, Ledger-, FIFO- oder Steuerdaten."
            ),
        )

    def refresh_metadata_cache(self, limit: int = 50, force: bool = False) -> JupiterTokenMetadataRefreshResult:
        normalized_limit = min(max(int(limit), 1), 100)
        candidates = self._mint_candidates(raw_limit=50000)
        cached_before = self._cached_mints()
        requested = candidates if force else [mint for mint in candidates if mint not in cached_before]
        requested = requested[:normalized_limit]
        if not self._api_key():
            return JupiterTokenMetadataRefreshResult(
                generated_at=datetime.now(timezone.utc),
                configured=False,
                status="missing_api_key",
                candidates_count=len(candidates),
                requested_count=len(requested),
                refreshed_count=0,
                cached_count=len(cached_before),
                uncached_count=len([mint for mint in candidates if mint not in cached_before]),
                skipped_count=len(requested),
                methodology="Jupiter-Metadata-Refresh wurde nicht ausgefuehrt, weil kein API-Key konfiguriert ist.",
            )

        refreshed: list[JupiterTokenMetadataCacheItem] = []
        if requested:
            search_result = self.search(",".join(requested))
            discovered_sources = self._mint_candidates_with_sources(raw_limit=50000)
            refreshed_at = datetime.now(timezone.utc)
            for token in search_result.tokens:
                if token.id not in requested:
                    continue
                item = self._cache_item_from_token(
                    token,
                    discovered_sources=sorted(discovered_sources.get(token.id, set())),
                    refreshed_at=refreshed_at,
                )
                self._upsert_cache_item(item)
                refreshed.append(item)

        cached_after = self._cached_mints()
        return JupiterTokenMetadataRefreshResult(
            generated_at=datetime.now(timezone.utc),
            configured=True,
            status="ok",
            candidates_count=len(candidates),
            requested_count=len(requested),
            refreshed_count=len(refreshed),
            cached_count=len(cached_after),
            uncached_count=len([mint for mint in candidates if mint not in cached_after]),
            skipped_count=max(len(requested) - len(refreshed), 0),
            items=refreshed,
            methodology=(
                "Aktualisiert maximal 100 Solana-Mints pro Lauf ueber Jupiter Token "
                "Search. Ergebnisse landen ausschliesslich in "
                "`jupiter_token_metadata_cache`."
            ),
        )

    def _mint_candidates(self, raw_limit: int) -> list[str]:
        return sorted(self._mint_candidates_with_sources(raw_limit=raw_limit))

    def _mint_candidates_with_sources(self, raw_limit: int) -> dict[str, set[str]]:
        candidates: dict[str, set[str]] = {}
        with self.store.connect() as con:
            for row in con.execute(
                """
                select distinct asset, connector_id
                from portfolio_live_balance_snapshots
                """
            ).fetchall():
                self._add_mint_candidate(candidates, row[0], f"live:{row[1]}")
            rows = con.execute(
                """
                select b.source, o.payload_json
                from raw_objects o
                join raw_import_batches b on b.batch_id = o.batch_id
                where lower(o.payload_json) like '%mint%'
                   or lower(o.payload_json) like '%tokenaddress%'
                   or lower(o.payload_json) like '%token_address%'
                   or lower(o.payload_json) like '%token_mint%'
                order by o.created_at desc
                limit ?
                """,
                [raw_limit],
            ).fetchall()
        for source, payload_json in rows:
            try:
                payload = json.loads(str(payload_json))
            except json.JSONDecodeError:
                continue
            for value in self._extract_mint_values(payload):
                self._add_mint_candidate(candidates, value, f"raw:{source}")
        self._add_v1_solscan_mint_candidates(candidates)
        return candidates

    def _add_v1_solscan_mint_candidates(self, candidates: dict[str, set[str]]) -> None:
        if not self.V1_DB_PATH.exists():
            return
        try:
            with sqlite3.connect(self.V1_DB_PATH) as con:
                rows = con.execute(
                    """
                    select distinct token_address, wallet_address
                    from solscan_account_transfers
                    where token_address is not null
                      and trim(token_address) != ''
                    """
                ).fetchall()
        except sqlite3.Error:
            return
        for token_address, wallet_address in rows:
            self._add_mint_candidate(candidates, token_address, f"v1_solscan:{wallet_address}")

    def _extract_mint_values(self, value: Any) -> list[str]:
        if isinstance(value, dict):
            found: list[str] = []
            for key, child in value.items():
                normalized_key = str(key).replace("-", "_").lower()
                if self._is_mint_key(normalized_key):
                    if isinstance(child, str):
                        found.append(child)
                    elif isinstance(child, list):
                        found.extend(str(item) for item in child if isinstance(item, str))
                found.extend(self._extract_mint_values(child))
            return found
        if isinstance(value, list):
            found = []
            for child in value:
                found.extend(self._extract_mint_values(child))
            return found
        return []

    def _is_mint_key(self, key: str) -> bool:
        compact = key.replace("_", "")
        compact_hints = {item.replace("_", "") for item in self.MINT_KEY_HINTS}
        return key in self.MINT_KEY_HINTS or compact in compact_hints

    def _add_mint_candidate(self, candidates: dict[str, set[str]], value: object, source: str) -> None:
        mint = str(value or "").strip()
        if self.SOLANA_MINT_RE.match(mint):
            candidates.setdefault(mint, set()).add(source)

    def _cached_mints(self) -> set[str]:
        with self.store.connect() as con:
            rows = con.execute("select mint from jupiter_token_metadata_cache").fetchall()
        return {str(row[0]) for row in rows}

    def _cached_items(self, limit: int) -> list[JupiterTokenMetadataCacheItem]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select
                    mint, symbol, name, decimals, icon, token_program, is_verified,
                    organic_score, organic_score_label, holder_count, liquidity_usd,
                    usd_price, market_cap_usd, risk_status, source,
                    discovered_sources_json, refreshed_at, jupiter_updated_at
                from jupiter_token_metadata_cache
                order by refreshed_at desc, symbol nulls last, mint
                limit ?
                """,
                [limit],
            ).fetchall()
        return [self._cache_item_from_row(row) for row in rows]

    def _cache_item_from_token(
        self,
        token: JupiterTokenSearchItem,
        discovered_sources: list[str],
        refreshed_at: datetime,
    ) -> JupiterTokenMetadataCacheItem:
        return JupiterTokenMetadataCacheItem(
            mint=token.id,
            symbol=token.symbol,
            name=token.name,
            decimals=token.decimals,
            icon=token.icon,
            token_program=token.token_program,
            is_verified=token.is_verified,
            organic_score=token.organic_score,
            organic_score_label=token.organic_score_label,
            holder_count=token.holder_count,
            liquidity_usd=token.liquidity_usd,
            usd_price=token.usd_price,
            market_cap_usd=token.market_cap_usd,
            risk_status=self._risk_status(token),
            discovered_sources=discovered_sources,
            refreshed_at=refreshed_at,
            jupiter_updated_at=token.updated_at,
        )

    def _cache_item_from_row(self, row: tuple[Any, ...]) -> JupiterTokenMetadataCacheItem:
        try:
            discovered_sources = json.loads(str(row[15]))
        except json.JSONDecodeError:
            discovered_sources = []
        if not isinstance(discovered_sources, list):
            discovered_sources = []
        return JupiterTokenMetadataCacheItem(
            mint=str(row[0]),
            symbol=self._optional_str(row[1]),
            name=self._optional_str(row[2]),
            decimals=self._optional_int(row[3]),
            icon=self._optional_str(row[4]),
            token_program=self._optional_str(row[5]),
            is_verified=row[6] if isinstance(row[6], bool) else None,
            organic_score=self._optional_decimal(row[7]),
            organic_score_label=self._optional_str(row[8]),
            holder_count=self._optional_int(row[9]),
            liquidity_usd=self._optional_decimal(row[10]),
            usd_price=self._optional_decimal(row[11]),
            market_cap_usd=self._optional_decimal(row[12]),
            risk_status=str(row[13]),
            source=str(row[14]),
            discovered_sources=[str(item) for item in discovered_sources],
            refreshed_at=row[16],
            jupiter_updated_at=row[17],
        )

    def _upsert_cache_item(self, item: JupiterTokenMetadataCacheItem) -> None:
        with self.store.connect() as con:
            con.execute(
                """
                insert or replace into jupiter_token_metadata_cache (
                    mint, symbol, name, decimals, icon, token_program,
                    is_verified, organic_score, organic_score_label,
                    holder_count, liquidity_usd, usd_price, market_cap_usd,
                    risk_status, source, discovered_sources_json,
                    refreshed_at, jupiter_updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    item.mint,
                    item.symbol,
                    item.name,
                    item.decimals,
                    item.icon,
                    item.token_program,
                    item.is_verified,
                    item.organic_score,
                    item.organic_score_label,
                    item.holder_count,
                    item.liquidity_usd,
                    item.usd_price,
                    item.market_cap_usd,
                    item.risk_status,
                    item.source,
                    json.dumps(item.discovered_sources, ensure_ascii=False),
                    item.refreshed_at,
                    item.jupiter_updated_at,
                ],
            )

    def _risk_status(self, token: JupiterTokenSearchItem) -> str:
        if token.is_verified is True:
            return "verified"
        label = str(token.organic_score_label or "").lower()
        liquidity = token.liquidity_usd or Decimal("0")
        if label in {"high", "medium"} and liquidity > 0:
            return "unverified_plausible"
        if label in {"low", "very_low"} or liquidity <= 0:
            return "spam_review"
        return "review"

    @staticmethod
    def _metadata_rank(item: JupiterTokenMetadataCacheItem) -> tuple[int, Decimal, str]:
        risk_order = {
            "verified": 0,
            "unverified_plausible": 1,
            "review": 2,
            "spam_review": 3,
        }
        return (
            risk_order.get(item.risk_status, 9),
            -(item.liquidity_usd or Decimal("0")),
            item.mint,
        )

    def _token_from_payload(self, data: dict[str, Any]) -> JupiterTokenSearchItem:
        audit = data.get("audit") if isinstance(data.get("audit"), dict) else None
        return JupiterTokenSearchItem(
            id=str(data.get("id") or ""),
            name=self._optional_str(data.get("name")),
            symbol=self._optional_str(data.get("symbol")),
            icon=self._optional_str(data.get("icon")),
            decimals=self._optional_int(data.get("decimals")),
            token_program=self._optional_str(data.get("tokenProgram")),
            created_at=self._optional_datetime(data.get("createdAt")),
            updated_at=self._optional_datetime(data.get("updatedAt")),
            website=self._optional_str(data.get("website")),
            twitter=self._optional_str(data.get("twitter")),
            dev=self._optional_str(data.get("dev")),
            holder_count=self._optional_int(data.get("holderCount")),
            organic_score=self._optional_decimal(data.get("organicScore")),
            organic_score_label=self._optional_str(data.get("organicScoreLabel")),
            is_verified=data.get("isVerified") if isinstance(data.get("isVerified"), bool) else None,
            tags=[str(item) for item in data.get("tags", []) if isinstance(item, str)],
            fdv_usd=self._optional_decimal(data.get("fdv")),
            market_cap_usd=self._optional_decimal(data.get("mcap")),
            usd_price=self._optional_decimal(data.get("usdPrice")),
            price_block_id=self._optional_int(data.get("priceBlockId")),
            liquidity_usd=self._optional_decimal(data.get("liquidity")),
            audit=(
                JupiterTokenAudit(
                    mint_authority_disabled=(
                        audit.get("mintAuthorityDisabled")
                        if isinstance(audit.get("mintAuthorityDisabled"), bool)
                        else None
                    ),
                    freeze_authority_disabled=(
                        audit.get("freezeAuthorityDisabled")
                        if isinstance(audit.get("freezeAuthorityDisabled"), bool)
                        else None
                    ),
                    top_holders_percentage=self._optional_decimal(audit.get("topHoldersPercentage")),
                    dev_mints=self._optional_int(audit.get("devMints")),
                )
                if audit is not None
                else None
            ),
        )

    @staticmethod
    def _optional_str(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_decimal(value: Any) -> Decimal | None:
        if value is None:
            return None
        try:
            return Decimal(str(value))
        except Exception:
            return None

    @staticmethod
    def _optional_datetime(value: Any) -> datetime | None:
        if value is None:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
