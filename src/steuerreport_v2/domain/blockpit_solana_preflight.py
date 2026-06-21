from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import httpx

from steuerreport_v2.contracts.blockpit_solana import (
    BlockpitSolanaClassPreflight,
    BlockpitSolanaCombinedReadiness,
    BlockpitSolanaHistoricalPriceRequirement,
    BlockpitSolanaOpeningBalanceEvidenceCandidate,
    BlockpitSolanaOpeningBalanceIncident,
    BlockpitSolanaPriceProbeJob,
    BlockpitSolanaPriceProbeResult,
    BlockpitSolanaPreflightReport,
    BlockpitSolanaPriceSourceStatus,
)
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.external_price_backfill import ExternalPriceBackfillService
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.price_lookup import HistoricalPriceLookup
from steuerreport_v2.domain.wallet_monthly_preflight import (
    DEFAULT_WALLET_MONTHLY_FILE,
    WalletMonthlyPreflightService,
)


DEFAULT_BLOCKPIT_SOLANA_FILE = (
    Path("/workspace/steuerreport/usertransfer")
    / "blockpit"
    / "blockpit 09052026 Transactions.csv"
)
DEFAULT_PRICE_CONFIG = Path("/workspace/steuerreport-v2-plan/configs/crypto_price_sources.json")
DEFAULT_ALLOWED_ASSETS = {
    "ADA",
    "BNB",
    "BTC",
    "BTT",
    "BTTOLD",
    "BUSD",
    "CBDC",
    "CDT",
    "COTI",
    "DOCK",
    "DOGE",
    "ETH",
    "GFT",
    "HNT",
    "HOT",
    "IOT",
    "JUP",
    "JUPDROP",
    "JUPSOL",
    "MANEKI",
    "MOBILE",
    "PEPE",
    "POPCAT",
    "PYTH",
    "SOL",
    "USDC",
    "USDT",
    "VET",
    "VTHO",
    "WABI",
    "WBTC",
    "WIN",
    "WRX",
    "ZEUS",
}
STABLE_ASSETS = {"EUR", "USD", "USDT", "USDC", "BUSD", "DAI", "TUSD", "FDUSD"}


class BlockpitSolanaPreflightService:
    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def inspect(
        self,
        *,
        file_path: str = str(DEFAULT_BLOCKPIT_SOLANA_FILE),
        integration: str = "Solana",
        max_year: int | None = 2024,
        account: str = "Solana",
        price_config_path: str = str(DEFAULT_PRICE_CONFIG),
        allowed_assets: set[str] | None = None,
        wallet_monthly_file_path: str = str(DEFAULT_WALLET_MONTHLY_FILE),
    ) -> BlockpitSolanaPreflightReport:
        path = Path(file_path)
        rows, skipped_unknown_assets, class_counts, skipped_class_counts = (
            self._filtered_rows(
                path=path,
                integration=integration,
                max_year=max_year,
                allowed_assets=allowed_assets or DEFAULT_ALLOWED_ASSETS,
                exclude_classes={"deposit_airdrop_missing_price"},
            )
        )
        classes = [
            self._class_preflight(row_class, class_rows, account)
            for row_class, class_rows in sorted(self._rows_by_class(rows).items())
        ]
        missing_price_assets = sorted(
            {
                asset
                for item in classes
                for asset in item.missing_latest_price_assets
            }
        )
        return BlockpitSolanaPreflightReport(
            file_path=str(path),
            integration=integration,
            max_year=max_year,
            account=account,
            filtered_rows=len(rows),
            skipped_unknown_assets=skipped_unknown_assets,
            skipped_class_counts=dict(sorted(skipped_class_counts.items())),
            class_counts=dict(sorted(class_counts.items())),
            classes=classes,
            combined_readiness=self._combined_readiness(
                rows,
                account,
                wallet_monthly_file_path=wallet_monthly_file_path,
            ),
            price_source_status=self._price_source_status(
                missing_price_assets,
                Path(price_config_path),
            ),
            historical_price_requirements=self._historical_price_requirements(
                rows,
                Path(price_config_path),
            ),
            importable_classes=[
                item.row_class for item in classes if item.status == "importable"
            ],
            blocked_classes=[
                item.row_class for item in classes if item.status != "importable"
            ],
            target_changed=False,
        )

    def _combined_readiness(
        self,
        rows: list[dict[str, str]],
        account: str,
        *,
        wallet_monthly_file_path: str = str(DEFAULT_WALLET_MONTHLY_FILE),
    ) -> BlockpitSolanaCombinedReadiness:
        running = self._current_balances(account)
        min_balance = dict(running)
        incidents_by_asset: dict[str, BlockpitSolanaOpeningBalanceIncident] = {}
        gross_negative: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        gross_positive: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for row in sorted(rows, key=self._row_time):
            row_time = self._row_time(row)
            row_class = self._row_class(row)
            for asset, delta in self._row_movements(row):
                before = running.get(asset, Decimal("0"))
                after = before + delta
                running[asset] = after
                if delta < 0:
                    gross_negative[asset] += abs(delta)
                elif delta > 0:
                    gross_positive[asset] += delta
                if after < min_balance.get(asset, before):
                    min_balance[asset] = after
                    incidents_by_asset[asset] = BlockpitSolanaOpeningBalanceIncident(
                        asset=asset,
                        required_quantity=abs(after),
                        first_deficit_at=row_time.isoformat(),
                        row_class=row_class,
                        balance_before=before,
                        movement_quantity=delta,
                        balance_after=after,
                        source_row={
                            key: str(row.get(key) or "")
                            for key in (
                                "Date (UTC)",
                                "Label",
                                "Outgoing Asset",
                                "Outgoing Amount",
                                "Incoming Asset",
                                "Incoming Amount",
                                "Fee Asset (optional)",
                                "Fee Amount (optional)",
                                "Trx. ID (optional)",
                            )
                        },
                    )
        required = {
            asset: abs(quantity)
            for asset, quantity in sorted(min_balance.items())
            if quantity < 0
        }
        incidents = [
            incidents_by_asset[asset].model_copy(
                update={
                    "evidence_candidates": self._opening_balance_evidence_candidates(
                        asset=asset,
                        required_quantity=required[asset],
                        deficit_at=datetime.fromisoformat(
                            incidents_by_asset[asset].first_deficit_at
                        ),
                        wallet_monthly_file_path=wallet_monthly_file_path,
                    )
                }
            )
            for asset in sorted(required)
            if asset in incidents_by_asset
        ]
        return BlockpitSolanaCombinedReadiness(
            status="importable" if not required else "blocked",
            required_opening_balance=required,
            incidents=incidents,
            gross_positive_movements={
                asset: quantity
                for asset, quantity in sorted(gross_positive.items())
                if quantity != 0
            },
            gross_negative_movements={
                asset: quantity
                for asset, quantity in sorted(gross_negative.items())
                if quantity != 0
            },
        )

    def _opening_balance_evidence_candidates(
        self,
        *,
        asset: str,
        required_quantity: Decimal,
        deficit_at: datetime,
        limit: int = 8,
        wallet_monthly_file_path: str = str(DEFAULT_WALLET_MONTHLY_FILE),
    ) -> list[BlockpitSolanaOpeningBalanceEvidenceCandidate]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select event_time, source, event_type, account, quantity, tx_id, source_ref
                from canonical_events
                where upper(asset) = ?
                  and quantity != 0
                  and event_time <= ?
                order by abs(abs(quantity) - ?) asc, event_time desc
                limit ?
                """,
                [asset.upper(), deficit_at, required_quantity, limit],
            ).fetchall()

        candidates: list[BlockpitSolanaOpeningBalanceEvidenceCandidate] = []
        for row in rows:
            event_time = row[0]
            quantity = Decimal(str(row[4]))
            quantity_delta = abs(abs(quantity) - required_quantity)
            score, reasons = self._opening_evidence_score(
                quantity=quantity,
                required_quantity=required_quantity,
            )
            candidates.append(
                BlockpitSolanaOpeningBalanceEvidenceCandidate(
                    score=score,
                    event_time=event_time.isoformat(),
                    source=str(row[1]),
                    event_type=str(row[2]),
                    account=str(row[3]) if row[3] is not None else None,
                    quantity=quantity,
                    required_quantity=required_quantity,
                    quantity_delta=quantity_delta,
                    tx_id=str(row[5]) if row[5] is not None else None,
                    source_ref=str(row[6]) if row[6] is not None else None,
                    reasons=reasons,
                )
            )
        candidates.sort(
            key=lambda item: (item.score, -item.quantity_delta),
            reverse=True,
        )
        candidates.extend(
            self._wallet_monthly_opening_candidates(
                asset=asset,
                required_quantity=required_quantity,
                deficit_at=deficit_at,
                wallet_monthly_file_path=wallet_monthly_file_path,
            )
        )
        candidates.sort(
            key=lambda item: (item.score, -item.quantity_delta),
            reverse=True,
        )
        return candidates[:limit]

    def _wallet_monthly_opening_candidates(
        self,
        *,
        asset: str,
        required_quantity: Decimal,
        deficit_at: datetime,
        wallet_monthly_file_path: str,
    ) -> list[BlockpitSolanaOpeningBalanceEvidenceCandidate]:
        if asset.upper() not in {"IOT", "MOBILE"}:
            return []
        path = Path(wallet_monthly_file_path)
        if not path.exists():
            return []
        report = WalletMonthlyPreflightService().inspect(
            file_path=str(path),
            asset=asset,
            cutoff_at=deficit_at.isoformat(),
            required_quantity=required_quantity,
        )
        quantity = report.quantity_until_cutoff
        if quantity <= 0:
            return []
        reasons = [
            "Asset stimmt ueberein",
            "Monatssummen liegen vor dem Defizitzeitpunkt",
        ]
        score = 60
        if report.covers_required_quantity:
            score += 35
            reasons.append("Monatssummen decken den erforderlichen Startbestand")
        else:
            reasons.append("Monatssummen decken den Startbestand nur teilweise")
        return [
            BlockpitSolanaOpeningBalanceEvidenceCandidate(
                score=score,
                event_time=deficit_at.isoformat(),
                source="wallet_monthly",
                event_type="reward_monthly_coverage",
                account=report.wallet,
                quantity=quantity,
                required_quantity=required_quantity,
                quantity_delta=abs(quantity - required_quantity),
                tx_id=None,
                source_ref=report.file_path,
                reasons=reasons,
            )
        ]

    def _opening_evidence_score(
        self,
        *,
        quantity: Decimal,
        required_quantity: Decimal,
    ) -> tuple[int, list[str]]:
        if required_quantity == 0:
            return 0, ["Kein Startbestand erforderlich"]
        delta = abs(abs(quantity) - required_quantity)
        ratio = delta / required_quantity
        reasons = ["Asset stimmt ueberein", "Ereignis liegt vor Defizit"]
        score = 40
        if delta == 0:
            score += 50
            reasons.append("Menge exakt gleich")
        elif ratio <= Decimal("0.000001"):
            score += 45
            reasons.append("Menge praktisch gleich")
        elif ratio <= Decimal("0.01"):
            score += 35
            reasons.append("Menge innerhalb 1 Prozent")
        elif ratio <= Decimal("0.10"):
            score += 20
            reasons.append("Menge innerhalb 10 Prozent")
        else:
            score += 5
            reasons.append("Menge nur grob aehnlich")
        if quantity < 0:
            reasons.append("Abfluss kann externe Solana-Zufuehrung erklaeren")
            score += 10
        else:
            reasons.append("Zufluss ist Bestandshinweis, aber kein Transferabfluss")
        return score, reasons

    def probe_historical_prices(
        self,
        *,
        file_path: str = str(DEFAULT_BLOCKPIT_SOLANA_FILE),
        integration: str = "Solana",
        max_year: int | None = 2024,
        account: str = "Solana",
        price_config_path: str = str(DEFAULT_PRICE_CONFIG),
        v1_fx_db_path: str = "/root/.local/share/steuerreport/steuerreport.db",
        provider: str = "auto",
        assets_filter: list[str] | None = None,
        max_requests: int = 25,
        timeout_seconds: int = 20,
        confidence: Decimal = Decimal("1.0"),
        dry_run: bool = True,
    ) -> BlockpitSolanaPriceProbeResult:
        report = self.inspect(
            file_path=file_path,
            integration=integration,
            max_year=max_year,
            account=account,
            price_config_path=price_config_path,
        )
        requested_assets = sorted(
            {asset.strip().upper() for asset in (assets_filter or []) if asset.strip()}
        )
        max_requests = max(0, min(max_requests, 1000))
        timeout_seconds = max(3, min(timeout_seconds, 60))
        backfill = ExternalPriceBackfillService(self.store)
        jobs: list[BlockpitSolanaPriceProbeJob] = []
        attempted = 0
        available = 0
        skipped = 0
        failed = 0
        price_points: list[PricePointCreate] = []
        with httpx.Client(
            timeout=timeout_seconds,
            headers={"user-agent": "steuerreport-v2/0.1"},
        ) as client:
            for requirement in report.historical_price_requirements:
                if requested_assets and requirement.asset.upper() not in requested_assets:
                    continue
                if attempted >= max_requests:
                    break
                if requirement.provider_id is None:
                    skipped += 1
                    jobs.append(
                        self._probe_job(
                            requirement,
                            status="skipped",
                            reason="asset_not_configured",
                        )
                    )
                    continue
                usd_eur = backfill._usd_eur_rate(  # noqa: SLF001 - shared provider logic.
                    v1_fx_db_path,
                    requirement.price_date.isoformat(),
                )
                if usd_eur <= 0:
                    skipped += 1
                    jobs.append(
                        self._probe_job(
                            requirement,
                            status="skipped",
                            reason="usd_eur_missing",
                            usd_eur=usd_eur,
                        )
                    )
                    continue
                attempted += 1
                price_usd, source = backfill._fetch_price_usd(  # noqa: SLF001 - shared provider logic.
                    client=client,
                    coingecko_id=requirement.provider_id,
                    date_str=requirement.price_date.isoformat(),
                    provider=provider,
                )
                if price_usd <= 0:
                    failed += 1
                    jobs.append(
                        self._probe_job(
                            requirement,
                            status="failed",
                            reason="asset_usd_missing",
                            usd_eur=usd_eur,
                        )
                    )
                    continue
                available += 1
                price_eur = price_usd * usd_eur
                source_label = f"{source}:usd_eur:v1_fx_cache"
                price_points.append(
                    PricePointCreate(
                        asset=requirement.asset,
                        price_eur=price_eur,
                        priced_at=datetime.combine(
                            requirement.price_date,
                            datetime.min.time(),
                            tzinfo=timezone.utc,
                        ),
                        source=source_label,
                        confidence=confidence,
                    )
                )
                jobs.append(
                    self._probe_job(
                        requirement,
                        status="available",
                        price_usd=price_usd,
                        usd_eur=usd_eur,
                        price_eur=price_eur,
                        source=source_label,
                    )
                )
        pipeline = None
        imported_prices = 0
        if price_points and not dry_run:
            self.store.add_price_points(price_points)
            imported_prices = len(price_points)
            pipeline = PipelineService(self.store).rebuild_all()
        return BlockpitSolanaPriceProbeResult(
            requirements_count=len(report.historical_price_requirements),
            asset_filter=requested_assets,
            attempted=attempted,
            available=available,
            skipped=skipped,
            failed=failed,
            max_requests=max_requests,
            imported_prices=imported_prices,
            dry_run=dry_run,
            target_changed=imported_prices > 0,
            jobs=jobs,
            pipeline=pipeline,
        )

    def _probe_job(
        self,
        requirement: BlockpitSolanaHistoricalPriceRequirement,
        *,
        status: str,
        reason: str | None = None,
        price_usd: Decimal | None = None,
        usd_eur: Decimal | None = None,
        price_eur: Decimal | None = None,
        source: str | None = None,
    ) -> BlockpitSolanaPriceProbeJob:
        return BlockpitSolanaPriceProbeJob(
            asset=requirement.asset,
            price_date=requirement.price_date,
            row_class=requirement.row_class,
            event_count=requirement.event_count,
            gross_quantity=requirement.gross_quantity,
            provider_id=requirement.provider_id,
            status=status,
            reason=reason,
            price_usd=price_usd,
            usd_eur=usd_eur,
            price_eur=price_eur,
            source=source,
        )

    def _historical_price_requirements(
        self,
        rows: list[dict[str, str]],
        config_path: Path,
    ) -> list[BlockpitSolanaHistoricalPriceRequirement]:
        configured = self._configured_price_sources(config_path)
        price_lookup = HistoricalPriceLookup(self.store)
        requirements: dict[tuple[str, datetime.date, str], tuple[int, Decimal]] = {}
        for row in rows:
            row_time = self._row_time(row)
            if row_time == datetime.min:
                continue
            row_class = self._row_class(row)
            for asset, delta in self._row_movements(row):
                if delta <= 0 or asset in STABLE_ASSETS or asset == "EUR":
                    continue
                if price_lookup.at_or_before(asset, row_time) is not None:
                    continue
                key = (asset, row_time.date(), row_class)
                count, quantity = requirements.get(key, (0, Decimal("0")))
                requirements[key] = (count + 1, quantity + abs(delta))
        return [
            BlockpitSolanaHistoricalPriceRequirement(
                asset=asset,
                price_date=price_date,
                row_class=row_class,
                event_count=count,
                gross_quantity=quantity,
                provider_id=configured.get(asset.upper()),
                status="configured" if configured.get(asset.upper()) else "not_configured",
            )
            for (asset, price_date, row_class), (count, quantity) in sorted(
                requirements.items(),
                key=lambda item: (item[0][1], item[0][0], item[0][2]),
            )
        ]

    def _price_source_status(
        self,
        assets: list[str],
        config_path: Path,
    ) -> list[BlockpitSolanaPriceSourceStatus]:
        configured = self._configured_price_sources(config_path)
        result: list[BlockpitSolanaPriceSourceStatus] = []
        for asset in assets:
            provider_id = configured.get(asset.upper())
            result.append(
                BlockpitSolanaPriceSourceStatus(
                    asset=asset,
                    configured=provider_id is not None,
                    provider_id=provider_id,
                    status="configured" if provider_id else "not_configured",
                )
            )
        return result

    def _configured_price_sources(self, config_path: Path) -> dict[str, str]:
        if not config_path.exists():
            return {}
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        result: dict[str, str] = {}
        for item in payload.get("assets", []):
            if not isinstance(item, dict):
                continue
            provider_id = str(item.get("coingecko_id") or "").strip()
            if not provider_id:
                continue
            keys = [
                item.get("symbol"),
                *(item.get("store_keys") or []),
                *(item.get("aliases") or []),
            ]
            for key in keys:
                normalized = str(key or "").strip().upper()
                if normalized:
                    result[normalized] = provider_id
        return result

    def _class_preflight(
        self,
        row_class: str,
        rows: list[dict[str, str]],
        account: str,
    ) -> BlockpitSolanaClassPreflight:
        balances = self._current_balances(account)
        latest_prices = self.store.latest_price_points()
        needed_prices = self._assets_requiring_latest_price(rows)
        missing_prices = sorted(asset for asset in needed_prices if asset not in latest_prices)
        running = dict(balances)
        min_balance = dict(balances)
        gross_negative: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        gross_positive: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
        for row in sorted(rows, key=self._row_time):
            for asset, delta in self._row_movements(row):
                running[asset] = running.get(asset, Decimal("0")) + delta
                min_balance[asset] = min(min_balance.get(asset, running[asset]), running[asset])
                if delta < 0:
                    gross_negative[asset] += abs(delta)
                elif delta > 0:
                    gross_positive[asset] += delta
        required_opening = {
            asset: abs(quantity)
            for asset, quantity in sorted(min_balance.items())
            if quantity < 0
        }
        blocker_codes = [
            f"missing_latest_price:{asset}" for asset in missing_prices
        ] + [
            f"required_opening_balance:{account}:{asset}" for asset in required_opening
        ]
        status = "importable" if not blocker_codes else "blocked"
        return BlockpitSolanaClassPreflight(
            row_class=row_class,
            rows=len(rows),
            status=status,
            missing_latest_price_assets=missing_prices,
            required_opening_balance=required_opening,
            gross_positive_movements={
                asset: quantity
                for asset, quantity in sorted(gross_positive.items())
                if quantity != 0
            },
            gross_negative_movements={
                asset: quantity
                for asset, quantity in sorted(gross_negative.items())
                if quantity != 0
            },
            blocker_codes=blocker_codes,
        )

    def _filtered_rows(
        self,
        *,
        path: Path,
        integration: str,
        max_year: int | None,
        allowed_assets: set[str],
        exclude_classes: set[str],
    ) -> tuple[list[dict[str, str]], int, dict[str, int], dict[str, int]]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle, delimiter=";")
            rows: list[dict[str, str]] = []
            skipped_unknown_assets = 0
            class_counts: dict[str, int] = {}
            skipped_class_counts: dict[str, int] = {}
            for row in reader:
                if row.get("Integration Name") != integration:
                    continue
                year = self._parse_year(str(row.get("Date (UTC)") or ""))
                if max_year is not None and (year is None or year > max_year):
                    continue
                row_class = self._row_class(row)
                assets = self._asset_values(row)
                if assets and not assets <= allowed_assets:
                    skipped_unknown_assets += 1
                    continue
                if row_class in exclude_classes:
                    skipped_class_counts[row_class] = skipped_class_counts.get(row_class, 0) + 1
                    continue
                class_counts[row_class] = class_counts.get(row_class, 0) + 1
                rows.append(dict(row))
        return rows, skipped_unknown_assets, class_counts, skipped_class_counts

    def _rows_by_class(
        self,
        rows: list[dict[str, str]],
    ) -> dict[str, list[dict[str, str]]]:
        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in rows:
            grouped[self._row_class(row)].append(row)
        return grouped

    def _current_balances(self, account: str) -> dict[str, Decimal]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select asset, sum(delta_quantity) as quantity
                from balance_ledger
                where account = ?
                group by asset
                """,
                [account],
            ).fetchall()
        return {str(row[0]): Decimal(str(row[1])) for row in rows}

    def _assets_requiring_latest_price(self, rows: list[dict[str, str]]) -> set[str]:
        assets: set[str] = set()
        for row in rows:
            for asset, delta in self._row_movements(row):
                if delta > 0 and asset not in STABLE_ASSETS and asset != "EUR":
                    assets.add(asset)
        return assets

    def _row_movements(self, row: dict[str, str]) -> list[tuple[str, Decimal]]:
        label = str(row.get("Label") or "").strip()
        incoming = self._asset(row, "Incoming Asset")
        outgoing = self._asset(row, "Outgoing Asset")
        fee = self._asset(row, "Fee Asset (optional)")
        incoming_amount = self._decimal(row.get("Incoming Amount"))
        outgoing_amount = self._decimal(row.get("Outgoing Amount"))
        fee_amount = self._decimal(row.get("Fee Amount (optional)"))
        movements: list[tuple[str, Decimal]] = []
        if label == "Trade":
            if incoming and incoming_amount:
                movements.append((incoming, incoming_amount))
            if outgoing and outgoing_amount:
                movements.append((outgoing, -outgoing_amount))
        elif label == "Deposit":
            if incoming and incoming_amount:
                movements.append((incoming, incoming_amount))
        elif label in {"Withdrawal", "Fee"}:
            if outgoing and outgoing_amount:
                movements.append((outgoing, -outgoing_amount))
        else:
            if incoming and incoming_amount:
                movements.append((incoming, incoming_amount))
            if outgoing and outgoing_amount:
                movements.append((outgoing, -outgoing_amount))
        if fee and fee_amount:
            movements.append((fee, -abs(fee_amount)))
        return movements

    def _row_class(self, row: dict[str, str]) -> str:
        label = str(row.get("Label") or "").strip()
        incoming = self._asset(row, "Incoming Asset")
        outgoing = self._asset(row, "Outgoing Asset")
        fee = self._asset(row, "Fee Asset (optional)")
        if label == "Trade":
            if incoming in STABLE_ASSETS and outgoing not in STABLE_ASSETS:
                return "trade_sell_to_stable"
            if outgoing in STABLE_ASSETS and incoming not in STABLE_ASSETS:
                return "trade_buy_from_stable"
            if incoming and outgoing:
                return "trade_crypto_crypto"
            return "trade_incomplete"
        if label == "Deposit":
            if incoming in {"JUPDROP", "PYTH"}:
                return "deposit_airdrop_missing_price"
            if incoming and fee == "SOL":
                return "deposit_with_sol_fee"
            if incoming:
                return "deposit_plain"
            return "deposit_other"
        if label == "Withdrawal":
            if outgoing == "SOL":
                return "withdrawal_sol"
            if outgoing in STABLE_ASSETS:
                return "withdrawal_stable"
            if outgoing:
                return "withdrawal_crypto"
            return "withdrawal_other"
        if label == "Fee":
            return "fee_only"
        return "other_" + label.lower().replace(" ", "_").replace("-", "_")

    def _asset_values(self, row: dict[str, str]) -> set[str]:
        return {
            self._asset(row, column)
            for column in (
                "Outgoing Asset",
                "Incoming Asset",
                "Fee Asset (optional)",
            )
            if self._asset(row, column)
        }

    def _asset(self, row: dict[str, str], column: str) -> str:
        return str(row.get(column) or "").strip().upper()

    def _decimal(self, value: str | None) -> Decimal:
        if value is None or str(value).strip() == "":
            return Decimal("0")
        try:
            return Decimal(str(value).strip().replace(",", "."))
        except InvalidOperation:
            return Decimal("0")

    def _parse_year(self, value: str) -> int | None:
        try:
            return datetime.strptime(value, "%d.%m.%Y %H:%M:%S").year
        except ValueError:
            return None

    def _row_time(self, row: dict[str, str]) -> datetime:
        try:
            return datetime.strptime(str(row.get("Date (UTC)") or ""), "%d.%m.%Y %H:%M:%S")
        except ValueError:
            return datetime.min
