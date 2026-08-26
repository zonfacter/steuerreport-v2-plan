from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path

from steuerreport_v2.contracts.swap_valuation import (
    CryptoSwapFifoParallelAssetRow,
    CryptoSwapFifoParallelEventRow,
    CryptoSwapFifoParallelPreviewReport,
    CryptoSwapFifoParallelYearRow,
)
from steuerreport_v2.contracts.tax import TaxLine
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_time import reporting_tax_year


@dataclass
class _Totals:
    gain_loss_eur: Decimal = Decimal("0")
    short_holding_gain_loss_eur: Decimal = Decimal("0")
    long_holding_gain_loss_eur: Decimal = Decimal("0")
    proceeds_eur: Decimal = Decimal("0")
    acquisition_cost_eur: Decimal = Decimal("0")
    tax_lines_count: int = 0

    def add(self, line: TaxLine) -> None:
        self.gain_loss_eur += line.gain_loss_eur
        self.proceeds_eur += line.disposal_proceeds_eur
        self.acquisition_cost_eur += line.acquisition_cost_eur
        self.tax_lines_count += 1
        if line.holding_days <= 365:
            self.short_holding_gain_loss_eur += line.gain_loss_eur
        else:
            self.long_holding_gain_loss_eur += line.gain_loss_eur


class CryptoSwapFifoParallelPreviewService:
    MATERIAL_DELTA_EUR = Decimal("0.01")
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    DEFAULT_DB = PROJECT_ROOT / "data/steuerreport_v2.duckdb"
    DEFAULT_ARTIFACT_ROOT = PROJECT_ROOT / "var/swap_valuation_parallel"

    def __init__(
        self,
        store: DuckDbStore,
        *,
        artifact_root: Path | None = None,
    ) -> None:
        self.store = store
        self.artifact_root = artifact_root or self._default_artifact_root()

    def run(self, *, limit: int = 100) -> CryptoSwapFifoParallelPreviewReport:
        report = self.preview(limit=limit)
        content = json.dumps(
            report.model_dump(mode="json"),
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self._atomic_write(self.artifact_root / "latest.json", content)
        self._atomic_write(
            self.artifact_root / f"swap_valuation_parallel_{timestamp}.json",
            content,
        )
        return report

    def latest(self) -> CryptoSwapFifoParallelPreviewReport | None:
        try:
            return CryptoSwapFifoParallelPreviewReport.model_validate_json(
                (self.artifact_root / "latest.json").read_text(encoding="utf-8")
            )
        except (OSError, ValueError):
            return None

    def preview(
        self,
        *,
        year: int | None = None,
        limit: int = 100,
    ) -> CryptoSwapFifoParallelPreviewReport:
        tax_service = TaxService(self.store)
        current = tax_service.preview_global_fifo()
        received_first = tax_service.preview_global_fifo(received_asset_first=True)
        current_lines = self._selected_lines(current.tax_lines, year)
        preview_lines = self._selected_lines(received_first.tax_lines, year)
        current_years = self._aggregate(current_lines, key="year")
        preview_years = self._aggregate(preview_lines, key="year")
        current_assets = self._aggregate(current_lines, key="asset")
        preview_assets = self._aggregate(preview_lines, key="asset")
        current_events = self._aggregate(current_lines, key="event")
        preview_events = self._aggregate(preview_lines, key="event")
        event_context = {
            event.event_id: event
            for event in self.store.list_canonical_events()
        }

        year_rows = [
            self._year_row(item_year, current_years.get(item_year), preview_years.get(item_year))
            for item_year in sorted(set(current_years) | set(preview_years))
        ]
        asset_rows = [
            self._asset_row(key, current_assets.get(key), preview_assets.get(key))
            for key in set(current_assets) | set(preview_assets)
        ]
        asset_rows.sort(
            key=lambda row: (
                -abs(row.gain_loss_delta_eur),
                row.year,
                row.asset,
            )
        )
        event_rows = [
            self._event_row(
                key,
                current_events.get(key),
                preview_events.get(key),
                event_context.get(key[2]),
            )
            for key in set(current_events) | set(preview_events)
        ]
        event_rows.sort(
            key=lambda row: (
                -abs(row.gain_loss_delta_eur),
                row.year,
                row.asset,
                row.disposal_event_id,
            )
        )

        affected_years = [
            row.year
            for row in year_rows
            if abs(row.gain_loss_delta_eur) >= self.MATERIAL_DELTA_EUR
            or row.current_tax_lines_count != row.preview_tax_lines_count
        ]
        unmatched_changed = (
            current.unmatched_disposals != received_first.unmatched_disposals
        )
        has_delta = bool(affected_years) or any(
            abs(row.gain_loss_delta_eur) >= self.MATERIAL_DELTA_EUR
            for row in asset_rows
        )
        status = "unmatched_changed" if unmatched_changed else "delta" if has_delta else "matched"
        current_total = self._sum(current_lines)
        preview_total = self._sum(preview_lines)
        selected_limit = max(1, min(limit, 5000))

        findings = [
            (
                f"Die erhaltene-Token-zuerst-Regel veraendert den saldierten G/V im "
                f"gewaehlten Bereich um {preview_total.gain_loss_eur - current_total.gain_loss_eur} EUR."
            ),
            (
                f"Die Summe der absoluten Jahresdeltas betraegt "
                f"{sum((abs(row.gain_loss_delta_eur) for row in year_rows), Decimal('0'))} EUR."
            ),
        ]
        if unmatched_changed:
            findings.append(
                "Die Zahl nicht zugeordneter Abgaenge aendert sich; vor jeder Methodenfreigabe ist eine Mengenpruefung erforderlich."
            )
        if not affected_years:
            findings.append("Kein Jahres-G/V-Delta von mindestens 0,01 EUR vorhanden.")

        return CryptoSwapFifoParallelPreviewReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            year=year,
            status=status,
            current_tax_lines_count=len(current_lines),
            preview_tax_lines_count=len(preview_lines),
            current_lots_count=len(current.lots),
            preview_lots_count=len(received_first.lots),
            current_unmatched_disposals=current.unmatched_disposals,
            preview_unmatched_disposals=received_first.unmatched_disposals,
            current_gain_loss_eur=current_total.gain_loss_eur,
            preview_gain_loss_eur=preview_total.gain_loss_eur,
            gain_loss_delta_eur=preview_total.gain_loss_eur - current_total.gain_loss_eur,
            absolute_year_gain_loss_delta_eur=sum(
                (abs(row.gain_loss_delta_eur) for row in year_rows), Decimal("0")
            ),
            affected_years=affected_years,
            years=year_rows,
            top_assets=asset_rows[:selected_limit],
            top_events=event_rows[:selected_limit],
            findings=findings,
            next_actions=(
                [
                    "Jahres- und Assetdeltas gegen die direkten Preisquellen und Ausfuehrungsbelege pruefen.",
                    "Steuersphaeren- und Wallet-FIFO-Parallelrechnung vor einer produktiven Methodenentscheidung kombinieren.",
                    "Erst eine versionierte, fachlich freigegebene Migration darf produktive Tax-Tabellen ersetzen.",
                ]
                if status != "matched"
                else []
            ),
            current_policy="Produktive globale Asset-FIFO mit bestehender V2-Preisrangfolge.",
            preview_policy=(
                "Globale Asset-FIFO im Speicher; bei Krypto-zu-Krypto zuerst Marktwert des "
                "erhaltenen Tokens, bei fehlendem Preis Fallback auf den hingegebenen Token."
            ),
            methodology=(
                "Beide FIFO-Varianten werden vollstaendig im Arbeitsspeicher aus denselben "
                "Canonical Events, Preisen, MoonPay-Belegen und Service-Swap-Mappings berechnet. "
                "Tax-Lots, Tax-Lines, Run-Summaries und unmatched Tabellen werden nicht geschrieben. "
                "short_holding bezeichnet nur die bestehende technische <=365-Tage-Gruppe; die "
                "betriebliche/private Steuersphaere ist in diesem Preisvergleich noch nicht neu zugeordnet."
            ),
        )

    @staticmethod
    def _selected_lines(lines: list[TaxLine], year: int | None) -> list[TaxLine]:
        if year is None:
            return lines
        return [line for line in lines if reporting_tax_year(line.disposed_at) == year]

    @staticmethod
    def _aggregate(
        lines: list[TaxLine],
        *,
        key: str,
    ) -> dict[object, _Totals]:
        result: dict[object, _Totals] = {}
        for line in lines:
            item_year = reporting_tax_year(line.disposed_at)
            if key == "year":
                item_key: object = item_year
            elif key == "asset":
                item_key = (item_year, line.asset.upper())
            elif key == "event":
                item_key = (item_year, line.asset.upper(), line.source_event_id)
            else:
                raise ValueError(f"unsupported aggregate key: {key}")
            result.setdefault(item_key, _Totals()).add(line)
        return result

    @staticmethod
    def _sum(lines: list[TaxLine]) -> _Totals:
        result = _Totals()
        for line in lines:
            result.add(line)
        return result

    def _year_row(
        self,
        year: int,
        current: _Totals | None,
        preview: _Totals | None,
    ) -> CryptoSwapFifoParallelYearRow:
        return self._base_row(
            CryptoSwapFifoParallelYearRow,
            year=year,
            current=current,
            preview=preview,
        )

    def _asset_row(
        self,
        key: tuple[int, str],
        current: _Totals | None,
        preview: _Totals | None,
    ) -> CryptoSwapFifoParallelAssetRow:
        return self._base_row(
            CryptoSwapFifoParallelAssetRow,
            year=key[0],
            asset=key[1],
            current=current,
            preview=preview,
        )

    @staticmethod
    def _base_row(
        model: type[CryptoSwapFifoParallelYearRow],
        *,
        year: int,
        current: _Totals | None,
        preview: _Totals | None,
        **extra: object,
    ) -> CryptoSwapFifoParallelYearRow:
        current = current or _Totals()
        preview = preview or _Totals()
        return model(
            year=year,
            current_gain_loss_eur=current.gain_loss_eur,
            preview_gain_loss_eur=preview.gain_loss_eur,
            gain_loss_delta_eur=preview.gain_loss_eur - current.gain_loss_eur,
            current_short_holding_gain_loss_eur=current.short_holding_gain_loss_eur,
            preview_short_holding_gain_loss_eur=preview.short_holding_gain_loss_eur,
            short_holding_gain_loss_delta_eur=(
                preview.short_holding_gain_loss_eur - current.short_holding_gain_loss_eur
            ),
            current_long_holding_gain_loss_eur=current.long_holding_gain_loss_eur,
            preview_long_holding_gain_loss_eur=preview.long_holding_gain_loss_eur,
            long_holding_gain_loss_delta_eur=(
                preview.long_holding_gain_loss_eur - current.long_holding_gain_loss_eur
            ),
            current_proceeds_eur=current.proceeds_eur,
            preview_proceeds_eur=preview.proceeds_eur,
            current_acquisition_cost_eur=current.acquisition_cost_eur,
            preview_acquisition_cost_eur=preview.acquisition_cost_eur,
            current_tax_lines_count=current.tax_lines_count,
            preview_tax_lines_count=preview.tax_lines_count,
            **extra,
        )

    @staticmethod
    def _event_row(
        key: tuple[int, str, str],
        current: _Totals | None,
        preview: _Totals | None,
        event: object | None,
    ) -> CryptoSwapFifoParallelEventRow:
        current = current or _Totals()
        preview = preview or _Totals()
        return CryptoSwapFifoParallelEventRow(
            year=key[0],
            asset=key[1],
            disposal_event_id=key[2],
            source=str(getattr(event, "source", "") or "") or None,
            account=str(getattr(event, "account", "") or "") or None,
            tx_id=str(getattr(event, "tx_id", "") or "") or None,
            current_gain_loss_eur=current.gain_loss_eur,
            preview_gain_loss_eur=preview.gain_loss_eur,
            gain_loss_delta_eur=preview.gain_loss_eur - current.gain_loss_eur,
            current_proceeds_eur=current.proceeds_eur,
            preview_proceeds_eur=preview.proceeds_eur,
            current_acquisition_cost_eur=current.acquisition_cost_eur,
            preview_acquisition_cost_eur=preview.acquisition_cost_eur,
            current_tax_lines_count=current.tax_lines_count,
            preview_tax_lines_count=preview.tax_lines_count,
        )

    def _default_artifact_root(self) -> Path:
        try:
            if self.store.path.resolve() == self.DEFAULT_DB.resolve():
                return self.DEFAULT_ARTIFACT_ROOT
        except FileNotFoundError:
            pass
        return self.store.path.parent / "var/swap_valuation_parallel"

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(content)
        temporary.replace(path)
