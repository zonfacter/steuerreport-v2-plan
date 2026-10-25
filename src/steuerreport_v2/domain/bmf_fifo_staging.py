from __future__ import annotations

from steuerreport_v2.paths import PROJECT_ROOT as SOFTWARE_ROOT

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from steuerreport_v2.contracts.bmf_fifo_staging import (
    BmfCombinedFifoAssetRow,
    BmfCombinedFifoEventRow,
    BmfCombinedFifoSphereRow,
    BmfCombinedFifoStagingReport,
    BmfCombinedFifoYearRow,
    BmfFifoScenarioTotals,
    BmfFifoStagingRunRequest,
)
from steuerreport_v2.contracts.events import CanonicalEvent
from steuerreport_v2.contracts.tax import TaxLine, TaxUnmatchedDisposal
from steuerreport_v2.contracts.tax_wallet_fifo import (
    WalletFifoPreviewLine,
    WalletFifoPreviewUnmatched,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.business_inventory import (
    BusinessRewardInventoryReviewService,
)
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_time import reporting_tax_year
from steuerreport_v2.domain.tax_wallet_fifo import WalletFifoPreviewService
from steuerreport_v2.domain.wallet_fifo_runs import WalletFifoParallelRunService


TaxLineLike = TaxLine | WalletFifoPreviewLine
UnmatchedLike = TaxUnmatchedDisposal | WalletFifoPreviewUnmatched
@dataclass
class _Totals:
    tax_lines_count: int = 0
    quantity: Decimal = Decimal("0")
    acquisition_cost_eur: Decimal = Decimal("0")
    disposal_proceeds_eur: Decimal = Decimal("0")
    gain_loss_eur: Decimal = Decimal("0")

    def add(self, line: TaxLineLike) -> None:
        self.tax_lines_count += 1
        self.quantity += line.quantity
        self.acquisition_cost_eur += line.acquisition_cost_eur
        self.disposal_proceeds_eur += line.disposal_proceeds_eur
        self.gain_loss_eur += line.gain_loss_eur


@dataclass
class _SphereTotals(_Totals):
    origin_event_ids: set[str] = field(default_factory=set)

    def add_line(self, line: WalletFifoPreviewLine) -> None:
        super().add(line)
        if line.acquisition_source_event_id:
            self.origin_event_ids.add(line.acquisition_source_event_id)


class BmfCombinedFifoStagingService:
    MATERIAL_DELTA_EUR = Decimal("0.01")
    PROJECT_ROOT = SOFTWARE_ROOT
    DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
    DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT / "var/bmf_fifo_staging"
    ACTIVE_GLOBAL_POLICY = "active_global_asset_fifo_and_active_price_ranking"
    RECEIVED_GLOBAL_POLICY = "global_asset_fifo_received_token_market_value_first"
    ACTIVE_WALLET_POLICY = "wallet_depot_fifo_and_active_price_ranking"
    RECEIVED_WALLET_POLICY = "wallet_depot_fifo_received_token_market_value_first"

    def __init__(
        self,
        store: DuckDbStore,
        *,
        artifact_root: Path | None = None,
    ) -> None:
        self.store = store
        self.artifact_root = artifact_root or self._default_artifact_root()

    def run(
        self,
        request: BmfFifoStagingRunRequest,
    ) -> BmfCombinedFifoStagingReport:
        generated_at = datetime.now(timezone.utc)
        years = self._validated_years(request.years, generated_at.year)
        as_of = self._resolve_as_of(request.as_of, years, generated_at)
        input_fingerprint = WalletFifoParallelRunService(self.store).input_fingerprint(
            as_of
        )
        productive_before = self._productive_tax_sha256()

        tax_service = TaxService(self.store)
        active_global_result = tax_service.preview_global_fifo()
        received_global_result = tax_service.preview_global_fifo(
            received_asset_first=True
        )
        wallet_service = WalletFifoPreviewService(self.store)
        active_wallet_state = wallet_service.replay(as_of=as_of)
        received_wallet_state = wallet_service.replay(
            as_of=as_of,
            received_asset_first=True,
        )

        active_global_lines = self._selected_lines(
            active_global_result.tax_lines,
            years=years,
            as_of=as_of,
        )
        received_global_lines = self._selected_lines(
            received_global_result.tax_lines,
            years=years,
            as_of=as_of,
        )
        active_wallet_lines = self._selected_lines(
            active_wallet_state.tax_lines,
            years=years,
            as_of=as_of,
        )
        received_wallet_lines = self._selected_lines(
            received_wallet_state.tax_lines,
            years=years,
            as_of=as_of,
        )
        active_global_unmatched = self._selected_unmatched(
            active_global_result.unmatched,
            years=years,
            as_of=as_of,
        )
        received_global_unmatched = self._selected_unmatched(
            received_global_result.unmatched,
            years=years,
            as_of=as_of,
        )
        active_wallet_unmatched = self._selected_unmatched(
            active_wallet_state.unmatched,
            years=years,
            as_of=as_of,
        )
        received_wallet_unmatched = self._selected_unmatched(
            received_wallet_state.unmatched,
            years=years,
            as_of=as_of,
        )

        events_by_id = {
            event.event_id: event for event in received_wallet_state.canonical_events
        }
        sphere_rows, sphere_by_year_asset = self._sphere_rows(
            received_wallet_lines,
            events_by_id,
        )
        scenario_lines = {
            "active_global": active_global_lines,
            "received_global": received_global_lines,
            "active_wallet": active_wallet_lines,
            "received_wallet": received_wallet_lines,
        }
        scenario_unmatched = {
            "active_global": active_global_unmatched,
            "received_global": received_global_unmatched,
            "active_wallet": active_wallet_unmatched,
            "received_wallet": received_wallet_unmatched,
        }
        year_rows = self._year_rows(
            years,
            scenario_lines,
            scenario_unmatched,
            sphere_by_year_asset,
        )
        asset_rows = self._asset_rows(
            scenario_lines,
            sphere_by_year_asset,
        )
        event_rows = self._event_rows(
            scenario_lines,
            received_wallet_lines,
            events_by_id,
        )

        active_global = self._scenario_totals(
            active_global_lines, active_global_unmatched
        )
        received_global = self._scenario_totals(
            received_global_lines, received_global_unmatched
        )
        active_wallet = self._scenario_totals(
            active_wallet_lines, active_wallet_unmatched
        )
        received_wallet = self._scenario_totals(
            received_wallet_lines, received_wallet_unmatched
        )
        price_delta = received_global.gain_loss_eur - active_global.gain_loss_eur
        wallet_delta = active_wallet.gain_loss_eur - active_global.gain_loss_eur
        combined_delta = received_wallet.gain_loss_eur - active_global.gain_loss_eur
        interaction_delta = combined_delta - price_delta - wallet_delta
        potential_business_count = sum(
            row.tax_lines_count
            for row in sphere_rows
            if row.classification == "potential_business_inventory"
        )
        unresolved_reward_count = sum(
            row.tax_lines_count
            for row in sphere_rows
            if row.classification
            in BusinessRewardInventoryReviewService.UNRESOLVED_STATUSES
        )
        unmatched_count = sum(
            len(items) for items in scenario_unmatched.values()
        )
        affected_years = sorted(
            row.year
            for row in year_rows
            if abs(row.combined_delta_eur) >= self.MATERIAL_DELTA_EUR
            or row.received_first_wallet.unmatched_count
            or row.potential_business_inventory_tax_lines_count
            or row.unresolved_reward_origin_tax_lines_count
        )
        material_delta = abs(combined_delta) >= self.MATERIAL_DELTA_EUR
        status = (
            "blocked"
            if unmatched_count
            or potential_business_count
            or unresolved_reward_count
            or material_delta
            else "ready_for_professional_review"
        )

        run_id = (
            f"bmf-fifo-staging-{generated_at.strftime('%Y%m%dT%H%M%S%fZ')}-"
            f"{input_fingerprint.digest[:12]}"
        )
        artifact_path = self.artifact_root / f"{run_id}.json"
        latest_path = self.artifact_root / "latest.json"
        productive_after = self._productive_tax_sha256()
        unchanged = productive_before == productive_after
        if not unchanged:
            raise RuntimeError(
                "Read-only BMF-FIFO-Staging hat produktive Tax-Tabellen veraendert."
            )

        report = BmfCombinedFifoStagingReport(
            run_id=run_id,
            generated_at=generated_at,
            as_of=as_of,
            years=years,
            status=status,
            strict_ready=False,
            active_global_policy=self.ACTIVE_GLOBAL_POLICY,
            received_first_global_policy=self.RECEIVED_GLOBAL_POLICY,
            active_wallet_policy=self.ACTIVE_WALLET_POLICY,
            received_first_wallet_policy=self.RECEIVED_WALLET_POLICY,
            wallet_method_version=wallet_service.METHOD_VERSION,
            input_fingerprint_digest=input_fingerprint.digest,
            productive_tax_component_sha256=productive_before,
            productive_tax_tables_unchanged=unchanged,
            active_global=active_global,
            received_first_global=received_global,
            active_wallet=active_wallet,
            received_first_wallet=received_wallet,
            price_policy_delta_eur=price_delta,
            wallet_scope_delta_eur=wallet_delta,
            combined_delta_eur=combined_delta,
            interaction_delta_eur=interaction_delta,
            absolute_year_combined_delta_eur=sum(
                (abs(row.combined_delta_eur) for row in year_rows), Decimal("0")
            ),
            potential_business_inventory_tax_lines_count=potential_business_count,
            unresolved_reward_origin_tax_lines_count=unresolved_reward_count,
            affected_years=affected_years,
            year_rows=year_rows,
            top_assets=asset_rows[: request.limit],
            sphere_rows=sphere_rows,
            top_events=event_rows[: request.limit],
            artifact_path=self._display_path(artifact_path),
            latest_artifact_path=self._display_path(latest_path),
            findings=self._findings(
                price_delta=price_delta,
                wallet_delta=wallet_delta,
                combined_delta=combined_delta,
                interaction_delta=interaction_delta,
                unmatched_count=unmatched_count,
                potential_business_count=potential_business_count,
                unresolved_reward_count=unresolved_reward_count,
            ),
            next_actions=[
                "Top-Events mit Original-CEX-Ledger oder DEX-/On-Chain-Beleg gegen die erhaltene Tokenmenge und den EUR-Zeitwert pruefen.",
                "Reward-Ursprungslots als betrieblich, dokumentiert entnommen oder anderweitig geklaert versionieren; keine automatische Privatklassifikation.",
                "Erst nach fachlicher Abnahme einen neuen gebundenen Staging-Lauf erzeugen und eine kontrollierte Migration separat freigeben.",
            ],
            methodology=(
                "Versionierter read-only Vier-Wege-Vergleich. Er stellt aktive globale "
                "Asset-FIFO, globale FIFO mit Marktwert des erhaltenen Tokens zuerst, "
                "Wallet-/Depot-FIFO mit aktiver Preisregel und Wallet-/Depot-FIFO mit "
                "erhaltenem Token zuerst gegenueber. Eigene Transfers tragen Lots im "
                "Wallet-Replay fort. Die Zielvariante wird zusaetzlich anhand des "
                "Anschaffungs-Events in potenzielles Reward-Betriebsvermoegen, offenen "
                "Reward-Ursprung oder ausserhalb des Reward-Pruefumfangs gruppiert. Keine "
                "Gruppe ist damit automatisch privat steuerpflichtig. tax_lots, tax_lines, "
                "Events, Preise, Ledger und Importdaten werden nicht geschrieben."
            ),
        )
        content = json.dumps(
            report.model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8")
        self._atomic_write(artifact_path, content)
        self._atomic_write(latest_path, content)
        return report

    def latest(self) -> BmfCombinedFifoStagingReport | None:
        try:
            return BmfCombinedFifoStagingReport.model_validate_json(
                (self.artifact_root / "latest.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None

    def _year_rows(
        self,
        years: list[int],
        scenarios: dict[str, list[TaxLineLike]],
        unmatched: dict[str, list[UnmatchedLike]],
        spheres: dict[tuple[int, str, str], _SphereTotals],
    ) -> list[BmfCombinedFifoYearRow]:
        totals = {
            name: self._aggregate(lines, key="year")
            for name, lines in scenarios.items()
        }
        unmatched_counts = {
            name: self._unmatched_counts(items, key="year")
            for name, items in unmatched.items()
        }
        rows: list[BmfCombinedFifoYearRow] = []
        for year in years:
            scenario_totals = {
                name: self._scenario_from_totals(
                    values.get(year), unmatched_counts[name].get(year, 0)
                )
                for name, values in totals.items()
            }
            active_global = scenario_totals["active_global"]
            received_global = scenario_totals["received_global"]
            active_wallet = scenario_totals["active_wallet"]
            received_wallet = scenario_totals["received_wallet"]
            price_delta = received_global.gain_loss_eur - active_global.gain_loss_eur
            wallet_delta = active_wallet.gain_loss_eur - active_global.gain_loss_eur
            combined_delta = received_wallet.gain_loss_eur - active_global.gain_loss_eur
            sphere_totals = self._sphere_year_totals(spheres, year)
            potential_count = sum(
                total.tax_lines_count
                for (item_year, _asset, classification), total in spheres.items()
                if item_year == year
                and classification == "potential_business_inventory"
            )
            unresolved_count = sum(
                total.tax_lines_count
                for (item_year, _asset, classification), total in spheres.items()
                if item_year == year
                and classification
                in BusinessRewardInventoryReviewService.UNRESOLVED_STATUSES
            )
            rows.append(
                BmfCombinedFifoYearRow(
                    year=year,
                    active_global=active_global,
                    received_first_global=received_global,
                    active_wallet=active_wallet,
                    received_first_wallet=received_wallet,
                    price_policy_delta_eur=price_delta,
                    wallet_scope_delta_eur=wallet_delta,
                    combined_delta_eur=combined_delta,
                    interaction_delta_eur=(
                        combined_delta - price_delta - wallet_delta
                    ),
                    potential_business_inventory_tax_lines_count=potential_count,
                    unresolved_reward_origin_tax_lines_count=unresolved_count,
                    potential_business_inventory_gain_loss_eur=sphere_totals[
                        "potential"
                    ],
                    unresolved_reward_origin_gain_loss_eur=sphere_totals[
                        "unresolved"
                    ],
                    outside_reward_scope_gain_loss_eur=sphere_totals["outside"],
                )
            )
        return rows

    def _asset_rows(
        self,
        scenarios: dict[str, list[TaxLineLike]],
        spheres: dict[tuple[int, str, str], _SphereTotals],
    ) -> list[BmfCombinedFifoAssetRow]:
        totals = {
            name: self._aggregate(lines, key="asset")
            for name, lines in scenarios.items()
        }
        keys = set().union(*(values.keys() for values in totals.values()))
        rows: list[BmfCombinedFifoAssetRow] = []
        for year, asset in keys:
            values = {
                name: scenario.get((year, asset), _Totals())
                for name, scenario in totals.items()
            }
            active_global = values["active_global"].gain_loss_eur
            received_global = values["received_global"].gain_loss_eur
            active_wallet = values["active_wallet"].gain_loss_eur
            received_wallet = values["received_wallet"].gain_loss_eur
            price_delta = received_global - active_global
            wallet_delta = active_wallet - active_global
            combined_delta = received_wallet - active_global
            potential_count = self._sphere_asset_count(
                spheres, year, asset, {"potential_business_inventory"}
            )
            unresolved_count = self._sphere_asset_count(
                spheres,
                year,
                asset,
                BusinessRewardInventoryReviewService.UNRESOLVED_STATUSES,
            )
            rows.append(
                BmfCombinedFifoAssetRow(
                    year=year,
                    asset=asset,
                    active_global_gain_loss_eur=active_global,
                    received_first_global_gain_loss_eur=received_global,
                    active_wallet_gain_loss_eur=active_wallet,
                    received_first_wallet_gain_loss_eur=received_wallet,
                    price_policy_delta_eur=price_delta,
                    wallet_scope_delta_eur=wallet_delta,
                    combined_delta_eur=combined_delta,
                    interaction_delta_eur=(
                        combined_delta - price_delta - wallet_delta
                    ),
                    received_first_wallet_tax_lines_count=values[
                        "received_wallet"
                    ].tax_lines_count,
                    potential_business_inventory_tax_lines_count=potential_count,
                    unresolved_reward_origin_tax_lines_count=unresolved_count,
                )
            )
        rows.sort(
            key=lambda row: (
                -max(
                    abs(row.combined_delta_eur),
                    abs(row.wallet_scope_delta_eur),
                    abs(row.price_policy_delta_eur),
                ),
                row.year,
                row.asset,
            )
        )
        return [
            row
            for row in rows
            if max(
                abs(row.combined_delta_eur),
                abs(row.wallet_scope_delta_eur),
                abs(row.price_policy_delta_eur),
            )
            >= self.MATERIAL_DELTA_EUR
            or row.potential_business_inventory_tax_lines_count
            or row.unresolved_reward_origin_tax_lines_count
        ]

    def _sphere_rows(
        self,
        lines: list[WalletFifoPreviewLine],
        events_by_id: dict[str, CanonicalEvent],
    ) -> tuple[
        list[BmfCombinedFifoSphereRow],
        dict[tuple[int, str, str], _SphereTotals],
    ]:
        totals: dict[tuple[int, str, str], _SphereTotals] = defaultdict(
            _SphereTotals
        )
        for line in lines:
            asset = line.asset.upper()
            origin = events_by_id.get(line.acquisition_source_event_id or "")
            classification = self._origin_classification(asset, origin)
            totals[(reporting_tax_year(line.disposed_at), asset, classification)].add_line(
                line
            )
        rows = [
            BmfCombinedFifoSphereRow(
                year=year,
                asset=asset,
                classification=classification,  # type: ignore[arg-type]
                origin_events_count=len(total.origin_event_ids),
                tax_lines_count=total.tax_lines_count,
                quantity=total.quantity,
                acquisition_cost_eur=total.acquisition_cost_eur,
                disposal_proceeds_eur=total.disposal_proceeds_eur,
                gain_loss_eur=total.gain_loss_eur,
            )
            for (year, asset, classification), total in totals.items()
        ]
        rows.sort(key=lambda row: (row.year, row.asset, row.classification))
        return rows, totals

    def _event_rows(
        self,
        scenarios: dict[str, list[TaxLineLike]],
        received_wallet_lines: list[WalletFifoPreviewLine],
        events_by_id: dict[str, CanonicalEvent],
    ) -> list[BmfCombinedFifoEventRow]:
        totals = {
            name: self._aggregate(lines, key="event")
            for name, lines in scenarios.items()
        }
        keys = set().union(*(values.keys() for values in totals.values()))
        wallet_context: dict[
            tuple[int, str, str], dict[str, set[str]]
        ] = defaultdict(lambda: {"pools": set(), "origins": set(), "classes": set()})
        disposed_at_by_key: dict[tuple[int, str, str], datetime] = {}
        for line in received_wallet_lines:
            key = (
                reporting_tax_year(line.disposed_at),
                line.asset.upper(),
                line.source_event_id,
            )
            wallet_context[key]["pools"].add(line.pool_id)
            if line.acquisition_source_event_id:
                wallet_context[key]["origins"].add(line.acquisition_source_event_id)
            origin = events_by_id.get(line.acquisition_source_event_id or "")
            wallet_context[key]["classes"].add(
                self._origin_classification(line.asset.upper(), origin)
            )
            disposed_at_by_key[key] = line.disposed_at

        rows: list[BmfCombinedFifoEventRow] = []
        for year, asset, event_id in keys:
            values = {
                name: scenario.get((year, asset, event_id), _Totals())
                for name, scenario in totals.items()
            }
            active_global = values["active_global"].gain_loss_eur
            received_global = values["received_global"].gain_loss_eur
            active_wallet = values["active_wallet"].gain_loss_eur
            received_wallet = values["received_wallet"].gain_loss_eur
            price_delta = received_global - active_global
            wallet_delta = active_wallet - active_global
            combined_delta = received_wallet - active_global
            context = wallet_context[(year, asset, event_id)]
            classifications = sorted(context["classes"])
            if (
                max(abs(price_delta), abs(wallet_delta), abs(combined_delta))
                < self.MATERIAL_DELTA_EUR
                and not set(classifications)
                & (
                    {"potential_business_inventory"}
                    | BusinessRewardInventoryReviewService.UNRESOLVED_STATUSES
                )
            ):
                continue
            event = events_by_id.get(event_id)
            disposed_at = (
                event.event_time
                if event is not None
                else disposed_at_by_key.get(
                    (year, asset, event_id),
                    datetime(year, 1, 1, tzinfo=timezone.utc),
                )
            )
            rows.append(
                BmfCombinedFifoEventRow(
                    year=year,
                    asset=asset,
                    disposal_event_id=event_id,
                    disposed_at=disposed_at,
                    source=event.source if event else None,
                    account=(event.account or event.wallet) if event else None,
                    tx_id=event.tx_id if event else None,
                    wallet_pool_ids=sorted(context["pools"]),
                    acquisition_source_event_ids=sorted(context["origins"]),
                    origin_classifications=classifications,
                    active_global_quantity=values["active_global"].quantity,
                    received_first_global_quantity=values["received_global"].quantity,
                    active_wallet_quantity=values["active_wallet"].quantity,
                    received_first_wallet_quantity=values["received_wallet"].quantity,
                    active_global_gain_loss_eur=active_global,
                    received_first_global_gain_loss_eur=received_global,
                    active_wallet_gain_loss_eur=active_wallet,
                    received_first_wallet_gain_loss_eur=received_wallet,
                    price_policy_delta_eur=price_delta,
                    wallet_scope_delta_eur=wallet_delta,
                    combined_delta_eur=combined_delta,
                    interaction_delta_eur=(
                        combined_delta - price_delta - wallet_delta
                    ),
                )
            )
        rows.sort(
            key=lambda row: (
                -max(
                    abs(row.combined_delta_eur),
                    abs(row.wallet_scope_delta_eur),
                    abs(row.price_policy_delta_eur),
                ),
                row.year,
                row.asset,
                row.disposal_event_id,
            )
        )
        return rows

    @staticmethod
    def _origin_classification(
        asset: str,
        origin: CanonicalEvent | None,
    ) -> str:
        if asset in BusinessRewardInventoryReviewService.DEFAULT_ASSETS:
            return BusinessRewardInventoryReviewService.classify_origin(
                origin.source if origin else None,
                origin.event_type if origin else None,
            )[0]
        if origin is not None and origin.event_type in {"mining", "reward", "staking"}:
            return "separate_income_review"
        return "outside_reward_scope"

    @staticmethod
    def _aggregate(
        lines: list[TaxLineLike],
        *,
        key: str,
    ) -> dict[object, _Totals]:
        result: dict[object, _Totals] = defaultdict(_Totals)
        for line in lines:
            year = reporting_tax_year(line.disposed_at)
            if key == "year":
                group: object = year
            elif key == "asset":
                group = (year, line.asset.upper())
            elif key == "event":
                group = (year, line.asset.upper(), line.source_event_id)
            else:
                raise ValueError(f"unsupported_aggregation_key:{key}")
            result[group].add(line)
        return result

    @staticmethod
    def _unmatched_counts(
        items: list[UnmatchedLike],
        *,
        key: str,
    ) -> dict[object, int]:
        result: dict[object, int] = defaultdict(int)
        for item in items:
            year = reporting_tax_year(item.event_time)
            group: object = year if key == "year" else (year, item.asset.upper())
            result[group] += 1
        return result

    @staticmethod
    def _scenario_from_totals(
        totals: _Totals | None,
        unmatched_count: int,
    ) -> BmfFifoScenarioTotals:
        values = totals or _Totals()
        return BmfFifoScenarioTotals(
            tax_lines_count=values.tax_lines_count,
            unmatched_count=unmatched_count,
            acquisition_cost_eur=values.acquisition_cost_eur,
            disposal_proceeds_eur=values.disposal_proceeds_eur,
            gain_loss_eur=values.gain_loss_eur,
        )

    def _scenario_totals(
        self,
        lines: list[TaxLineLike],
        unmatched: list[UnmatchedLike],
    ) -> BmfFifoScenarioTotals:
        totals = _Totals()
        for line in lines:
            totals.add(line)
        return self._scenario_from_totals(totals, len(unmatched))

    @staticmethod
    def _sphere_year_totals(
        spheres: dict[tuple[int, str, str], _SphereTotals],
        year: int,
    ) -> dict[str, Decimal]:
        result = {
            "potential": Decimal("0"),
            "unresolved": Decimal("0"),
            "outside": Decimal("0"),
        }
        for (item_year, _asset, classification), totals in spheres.items():
            if item_year != year:
                continue
            if classification == "potential_business_inventory":
                result["potential"] += totals.gain_loss_eur
            elif classification in BusinessRewardInventoryReviewService.UNRESOLVED_STATUSES:
                result["unresolved"] += totals.gain_loss_eur
            else:
                result["outside"] += totals.gain_loss_eur
        return result

    @staticmethod
    def _sphere_asset_count(
        spheres: dict[tuple[int, str, str], _SphereTotals],
        year: int,
        asset: str,
        classifications: set[str],
    ) -> int:
        return sum(
            totals.tax_lines_count
            for (item_year, item_asset, classification), totals in spheres.items()
            if item_year == year
            and item_asset == asset
            and classification in classifications
        )

    @classmethod
    def _selected_lines(
        cls,
        lines: list[TaxLineLike],
        *,
        years: list[int],
        as_of: datetime,
    ) -> list[TaxLineLike]:
        return [
            line
            for line in lines
            if reporting_tax_year(line.disposed_at) in years
            and cls._as_utc(line.disposed_at) <= as_of
        ]

    @classmethod
    def _selected_unmatched(
        cls,
        items: list[UnmatchedLike],
        *,
        years: list[int],
        as_of: datetime,
    ) -> list[UnmatchedLike]:
        return [
            item
            for item in items
            if reporting_tax_year(item.event_time) in years
            and cls._as_utc(item.event_time) <= as_of
        ]

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _validated_years(years: list[int], current_year: int) -> list[int]:
        result = sorted(set(years))
        invalid = [year for year in result if year < 2009 or year > current_year]
        if not result or invalid:
            raise ValueError(
                "Ungueltige Steuerjahre: "
                + ", ".join(str(year) for year in invalid or years)
            )
        return result

    @classmethod
    def _resolve_as_of(
        cls,
        requested: datetime | None,
        years: list[int],
        now: datetime,
    ) -> datetime:
        if requested is None:
            if max(years) == now.year:
                return now
            return datetime(
                max(years),
                12,
                31,
                23,
                59,
                59,
                999999,
                tzinfo=timezone.utc,
            )
        as_of = cls._as_utc(requested)
        if as_of.year < max(years):
            raise ValueError("Der Stichtag liegt vor einem angeforderten Steuerjahr.")
        if as_of > now:
            raise ValueError("Der Stichtag darf nicht in der Zukunft liegen.")
        return as_of

    def _productive_tax_sha256(self) -> str:
        digest = hashlib.sha256()
        with self.store.connect() as con:
            for query in (
                """
                select lot_id, asset, acquired_at, quantity_total,
                       quantity_remaining, cost_basis_eur_total, source_event_id
                from tax_lots order by all
                """,
                """
                select tax_line_id, lot_id, asset, acquired_at, disposed_at,
                       quantity, acquisition_cost_eur, disposal_proceeds_eur,
                       gain_loss_eur, holding_days, source_event_id,
                       acquisition_source_event_id
                from tax_lines order by all
                """,
            ):
                cursor = con.execute(query)
                while rows := cursor.fetchmany(2000):
                    for row in rows:
                        digest.update(
                            json.dumps(
                                [self._json_value(value) for value in row],
                                ensure_ascii=True,
                                separators=(",", ":"),
                            ).encode("utf-8")
                        )
                        digest.update(b"\n")
        return digest.hexdigest()

    @staticmethod
    def _json_value(value: object) -> object:
        if isinstance(value, (datetime, Decimal)):
            return str(value)
        if isinstance(value, bytes):
            return value.hex()
        return value

    @staticmethod
    def _findings(
        *,
        price_delta: Decimal,
        wallet_delta: Decimal,
        combined_delta: Decimal,
        interaction_delta: Decimal,
        unmatched_count: int,
        potential_business_count: int,
        unresolved_reward_count: int,
    ) -> list[str]:
        return [
            f"Preisrangfolge allein verschiebt das globale G/V um {price_delta} EUR.",
            f"Wallet-/Depot-FIFO allein verschiebt das G/V um {wallet_delta} EUR.",
            f"Die kombinierte Zielvorschau weicht um {combined_delta} EUR von der aktiven globalen Berechnung ab.",
            f"Der nichtadditive Interaktionseffekt betraegt {interaction_delta} EUR.",
            f"Alle vier Szenarien enthalten zusammen {unmatched_count} unmatched Hinweise im gewaehlten Zeitraum.",
            f"Die Zielvorschau enthaelt {potential_business_count} Zeilen aus potenziellem Reward-Betriebsvermoegen und {unresolved_reward_count} Zeilen mit offenem Reward-Ursprung.",
        ]

    def _default_artifact_root(self) -> Path:
        if self.store.path.resolve() == self.DEFAULT_DB.resolve():
            return self.DEFAULT_ARTIFACT_ROOT
        return self.store.path.parent / "var/bmf_fifo_staging"

    @classmethod
    def _display_path(cls, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(cls.PROJECT_ROOT.resolve()))
        except ValueError:
            return str(path.resolve())

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)
