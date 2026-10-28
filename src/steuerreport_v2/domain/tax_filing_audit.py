from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
import csv
import hashlib
import io
import json
import os
from pathlib import Path
from typing import Any
import zipfile
from zoneinfo import ZoneInfo

from steuerreport_v2 import __version__
from steuerreport_v2.contracts.tax_filing_audit import (
    TaxAuditAggregateReconciliation,
    TaxAuditCashSeparation,
    TaxAuditDelta,
    TaxAuditEndpointEvidence,
    TaxAuditReproducibility,
    TaxAuditSnapshotMetadata,
    TaxAuditSourceEvent,
    TaxAuditSourceReconciliation,
    TaxAuditMirrorMatch,
    TaxFilingAuditReport,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.derivatives import DerivativesManager
from steuerreport_v2.domain.portfolio import PortfolioService
from steuerreport_v2.domain.tax import TaxService
from steuerreport_v2.domain.tax_filing_snapshots import (
    METHOD_VERSION,
    TaxFilingSnapshotService,
)
from steuerreport_v2.domain.tax_methodology import TaxMethodologyService
from steuerreport_v2.domain.tax_time import PRIVATE_HOLDING_POLICY_VERSION, reporting_tax_year
from steuerreport_v2.domain.tax_years import TaxYearService


ENDPOINT_TEMPLATES = (
    "filing-snapshot-comparison",
    "filing-snapshots",
    "methodology",
    "drivers",
    "turnover-audit",
    "gain-evidence-event-deltas",
    "gain-evidence-acquisition-event-deltas",
    "gain-evidence-price-deltas",
)
BERLIN = ZoneInfo("Europe/Berlin")
PRIMARY_SOURCE_NAMES = frozenset(
    {
        "binance",
        "binance_simple_earn_api",
        "binance_withdrawal_api",
        "helium",
        "solana_rpc",
    }
)
AGGREGATOR_SOURCE_NAMES = frozenset({"blockpit"})


class TaxFilingAuditError(ValueError):
    pass


class TaxFilingAuditService:
    """Read-only, content-addressed comparison of a filed tax-year stand."""

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store
        self.snapshots = TaxFilingSnapshotService(store)
        self.archive_root = store.path.parent / "tax_filing_audit_archive"

    def build(
        self,
        year: int,
        *,
        query_time: datetime | None = None,
        materialize: bool = True,
    ) -> TaxFilingAuditReport:
        queried_at = (query_time or datetime.now(timezone.utc)).astimezone(timezone.utc)
        comparison = self.snapshots.comparison(year)
        current_summary = TaxYearService(self.store).filing_summary(year)
        current_values = self.snapshots._values_from_summary(current_summary)
        baseline = comparison.baseline

        reference_package: dict[str, Any] | None = None
        reference_tax_lines: list[dict[str, Any]] = []
        reference_rewards: list[dict[str, Any]] = []
        reference_derivatives: list[dict[str, Any]] = []
        reference_files: list[dict[str, Any]] = []
        open_points: list[str] = []
        if baseline is not None:
            if baseline.integrity_status != "verified":
                open_points.append(
                    "Der Referenzstand ist nicht hashverifiziert; der Vergleich ist blockiert."
                )
            else:
                try:
                    reference_package = self._read_reference_package(baseline.snapshot_id)
                    reference_tax_lines = self._reference_tax_lines(
                        reference_package, year
                    )
                    reference_rewards = self._reference_rewards(
                        reference_package, year
                    )
                    reference_derivatives = self._reference_derivatives(
                        reference_package, year
                    )
                    reference_files = [
                        dict(item)
                        for item in reference_package["manifest"].get("files", [])
                    ]
                except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
                    open_points.append(f"Referenzpaket konnte nicht gelesen werden: {exc}")
        else:
            open_points.append("Kein unveraenderlicher Referenzstand fuer das Steuerjahr vorhanden.")
        if reference_tax_lines and all(item.get("lot_id") is None for item in reference_tax_lines):
            open_points.append(
                "Das historische Tax-Line-Exportformat enthaelt keine FIFO-Lot-ID; die aktuelle Lot-Zuordnung ist deshalb separat reviewpflichtig."
            )
        if reference_tax_lines and all(item.get("source") is None for item in reference_tax_lines):
            open_points.append(
                "Das historische Tax-Line-Exportformat enthaelt keine Quellspalte; die zugrunde liegende Importquelle ist fuer diese Positionen nicht direkt reproduzierbar."
            )

        source_reconciliation, source_evidence = self._source_reconciliation(year)
        if source_reconciliation.status == "review_required":
            open_points.extend(source_reconciliation.open_review_points)

        current_tax_lines = self._current_tax_lines(year, source_evidence)
        tax_deltas, _tax_delta_objects = self._compare_positions(
            reference_tax_lines, current_tax_lines, position_kind="tax_line"
        )
        reward_deltas, reward_delta_objects = self._compare_reward_positions(
            reference_rewards, year
        )
        derivative_deltas, derivative_delta_objects = self._compare_derivative_positions(
            reference_derivatives, year, source_evidence
        )
        deltas = tax_deltas + reward_deltas + derivative_deltas
        deltas.sort(
            key=lambda item: (
                item.position_kind,
                item.stable_event_id_or_fingerprint,
                item.change_kind,
            )
        )

        current_runtime_sha, current_runtime = self.snapshots._runtime_fingerprint()
        current_input_fingerprint = self._fingerprint(
            {
                "year": year,
                "method_version": METHOD_VERSION,
                "runtime": current_runtime,
                "tax_lines": current_tax_lines,
                "rewards": reward_delta_objects["current"],
                "derivatives": derivative_delta_objects["current"],
                "source_reconciliation": source_reconciliation.model_dump(mode="json"),
                "source_evidence": [
                    {"event_id": event_id, **details}
                    for event_id, details in sorted(source_evidence.items())
                ],
            }
        )
        reference_input_fingerprint = self._fingerprint(
            {
                "package_sha256": baseline.package_sha256 if baseline else None,
                "manifest_sha256": baseline.manifest_sha256 if baseline else None,
                "files": reference_files,
            }
        )
        current_manifest_sha = self._fingerprint(
            {
                "year": year,
                "source_files": self._current_source_files(),
                "endpoints": list(ENDPOINT_TEMPLATES),
                "input_fingerprint": current_input_fingerprint,
            }
        )
        current_package_sha = self._fingerprint(
            {
                "kind": "current_runtime_derived_stand",
                "input_fingerprint": current_input_fingerprint,
                "manifest_sha256": current_manifest_sha,
            }
        )
        current_metadata = TaxAuditSnapshotMetadata(
            snapshot_id=f"current-runtime-{current_input_fingerprint[:24]}",
            package_name=f"tax-year-{year}-current-runtime-derived-stand.json",
            package_sha256=current_package_sha,
            manifest_sha256=current_manifest_sha,
            package_generated_at_utc=queried_at.isoformat(),
            package_generated_at_europe_berlin=queried_at.astimezone(BERLIN).isoformat(),
            created_at_utc=queried_at.isoformat(),
            created_at_europe_berlin=queried_at.astimezone(BERLIN).isoformat(),
            software_version=__version__,
            method_version=METHOD_VERSION,
            database_fingerprint_sha256=current_runtime_sha,
            runtime_fingerprint_sha256=current_runtime_sha,
            integrity_status="derived_and_verified",
            source_kind="current_runtime_derived",
            confirmation_scope=(
                "Read-only current runtime stand; no filing-use confirmation is implied."
            ),
        )
        reference_metadata = self._reference_metadata(baseline) if baseline else None
        if reference_metadata and (
            reference_metadata.software_version == "unknown_at_capture"
            or reference_metadata.method_version == "unknown_at_capture"
        ):
            open_points.append(
                "Der historische Referenzstand vom 05.07.2026 enthaelt keine aufgezeichnete "
                "Software-/Methodenversion; dies bleibt ein menschlicher Review-Punkt."
            )

        endpoints = self._endpoint_evidence(
            year=year,
            queried_at=queried_at,
            comparison=comparison,
        )
        reconciliation = self._reconciliation(
            baseline_values=baseline.values if baseline else None,
            current_values=current_values,
            deltas=deltas,
        )
        if any(item.status == "reconciliation_failed" for item in reconciliation):
            open_points.append(
                "Mindestens eine Einzelpositionssumme leitet nicht exakt auf die Aggregatdifferenz ueber."
            )
        if any(item.cause == "unknown" for item in deltas):
            open_points.append(
                "Unbekannte Ursachen sind mit einer Erklaerung markiert und duerfen nicht automatisch als fachlich geklaert gelten."
            )

        cash = self._cash_separation(year)
        cause_counts = dict(sorted(Counter(item.cause for item in deltas).items()))
        reconciliation_failed = any(
            item.status == "reconciliation_failed" for item in reconciliation
        )
        tax_count_reference = len(reference_tax_lines) if baseline is not None else None
        reproducibility_differences: list[str] = []
        snapshot_hashes_identical = False
        tax_line_count_identical = False
        delta_list_identical = False
        if baseline is None:
            reproducibility_differences.append("reference_snapshot_missing")
        else:
            snapshot_hashes_identical = (
                baseline.package_sha256 == current_package_sha
                and baseline.manifest_sha256 == current_manifest_sha
            )
            tax_line_count_identical = tax_count_reference == len(current_tax_lines)
            delta_list_identical = not deltas
            if not snapshot_hashes_identical:
                reproducibility_differences.append("snapshot_hashes")
            if not tax_line_count_identical:
                reproducibility_differences.append("tax_line_count")
            if not delta_list_identical:
                reproducibility_differences.append("delta_list")
            if baseline.method_version != __version__:
                reproducibility_differences.append("method_version")
            if baseline.software_version != __version__:
                reproducibility_differences.append("software_version")
            if (
                baseline.database_fingerprint_sha256
                and baseline.database_fingerprint_sha256 != current_runtime_sha
            ):
                reproducibility_differences.append("database_fingerprint")
            if (
                baseline.runtime_fingerprint_sha256
                and baseline.runtime_fingerprint_sha256 != current_runtime_sha
            ):
                reproducibility_differences.append("runtime_fingerprint")
            if source_reconciliation.status == "review_required":
                reproducibility_differences.append("source_reconciliation")
        reproducibility_differences.extend(
            item.key
            for item in reconciliation
            if item.status == "reconciliation_failed"
            and item.key not in reproducibility_differences
        )
        reproducibility_failed = reconciliation_failed or bool(
            reproducibility_differences
        )
        integrity_blocked = baseline is not None and baseline.integrity_status != "verified"
        status = (
            "integrity_blocked"
            if integrity_blocked
            else "reconciliation_failed"
            if reconciliation_failed
            else "review_required"
            if deltas or open_points
            else "reconciled"
        )
        reproducibility = TaxAuditReproducibility(
            snapshot_hashes_identical=snapshot_hashes_identical,
            tax_line_count_identical=tax_line_count_identical,
            sums_identical=not reconciliation_failed,
            delta_list_identical=delta_list_identical,
            status="not_reproducible" if reproducibility_failed else "reproducible",
            reference_input_fingerprint=reference_input_fingerprint,
            current_input_fingerprint=current_input_fingerprint,
            differences=reproducibility_differences,
        )
        report = TaxFilingAuditReport(
            year=year,
            report_id="pending",
            generated_at_utc=queried_at.isoformat(),
            generated_at_europe_berlin=queried_at.astimezone(BERLIN).isoformat(),
            status=status,
            reference=reference_metadata,
            current=current_metadata,
            endpoints=endpoints,
            deltas=deltas,
            cause_counts=cause_counts,
            reconciliation=reconciliation,
            cash_separation=cash,
            source_reconciliation=source_reconciliation,
            reproducibility=reproducibility,
            tax_line_count_reference=tax_count_reference,
            tax_line_count_current=len(current_tax_lines),
            source_files=reference_files + self._current_source_files(),
            open_review_points=sorted(set(open_points)),
            human_approvals=[],
            report_content_sha256="pending",
            markdown_content_sha256="pending",
            json_artifact_endpoint="pending",
            markdown_artifact_endpoint="pending",
            methodology=(
                "Read-only Vergleich des unveraenderlichen Referenzpakets mit der aktuellen "
                "V2-Auswertung. Referenzpaket, Manifest, Laufzeitfingerprint, Quellen- und "
                "Tax-Line-Daten werden gehasht; keine Tax-Line, kein Lot und keine Datenbankzeile "
                "wird durch diesen Lauf veraendert. Blockpit-/Aggregator-Ereignisse werden gegen "
                "primaere Quellen gespiegelt und ohne Gegenbeleg als pending_review ausgewiesen. "
                "Materiale Aenderungen benoetigen eine menschliche Freigabe."
            ),
        )
        stable_core = self._stable_payload(report.model_dump(mode="json"))
        content_hash = self._fingerprint(stable_core)
        report_id = f"tax-filing-audit-{year}-{content_hash[:24]}"
        report = report.model_copy(
            update={
                "report_id": report_id,
                "report_content_sha256": content_hash,
                "json_artifact_endpoint": f"/api/v1/tax-years/{year}/filing-audit-report.json",
                "markdown_artifact_endpoint": f"/api/v1/tax-years/{year}/filing-audit-report.md",
            }
        )
        if materialize:
            report = self._materialize(report)
        return report

    def read_artifact(self, year: int, suffix: str) -> tuple[TaxFilingAuditReport, bytes]:
        report = self.build(year)
        if suffix == ".json":
            path = self.archive_root / str(year) / f"{report.report_id}.json"
        elif suffix == ".md":
            path = self.archive_root / str(year) / f"{report.report_id}.md"
        else:
            raise TaxFilingAuditError("Unbekanntes Auditformat.")
        try:
            content = path.read_bytes()
        except OSError as exc:
            raise TaxFilingAuditError(f"Auditdatei fehlt: {path}") from exc
        return report, content

    def _materialize(self, report: TaxFilingAuditReport) -> TaxFilingAuditReport:
        root = self.archive_root / str(report.year)
        root.mkdir(parents=True, exist_ok=True)
        json_path = root / f"{report.report_id}.json"
        markdown_path = root / f"{report.report_id}.md"
        if json_path.exists() or markdown_path.exists():
            if not json_path.is_file() or not markdown_path.is_file():
                raise TaxFilingAuditError("Auditartefakt ist unvollstaendig und wird nicht ueberschrieben.")
            try:
                return TaxFilingAuditReport.model_validate_json(json_path.read_text("utf-8"))
            except Exception as exc:
                raise TaxFilingAuditError("Vorhandenes Audit-JSON ist nicht lesbar.") from exc

        markdown = self._markdown(report)
        markdown_hash = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        report = report.model_copy(update={"markdown_content_sha256": markdown_hash})
        json_bytes = (
            json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n"
        ).encode("utf-8")
        self._write_once(json_path, json_bytes, mode=0o444)
        self._write_once(markdown_path, markdown.encode("utf-8"), mode=0o444)
        return report

    @staticmethod
    def _write_once(path: Path, content: bytes, *, mode: int) -> None:
        if path.exists():
            if path.read_bytes() != content:
                raise TaxFilingAuditError(f"Unveraenderliches Auditartefakt abweichend: {path}")
            return
        temporary = path.with_suffix(f".{os.getpid()}.tmp")
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.replace(path)
            try:
                path.chmod(mode)
            except OSError:
                pass
        finally:
            if temporary.exists():
                temporary.unlink()

    def _read_reference_package(self, snapshot_id: str) -> dict[str, Any]:
        snapshot = self.snapshots.get(snapshot_id)
        content = self.snapshots.read_package(snapshot_id)
        with zipfile.ZipFile(io.BytesIO(content)) as package:
            members = {name: package.read(name) for name in package.namelist()}
        manifest_name = next(
            (name for name in members if name.endswith("year-evidence-manifest.json")),
            None,
        )
        if manifest_name is None:
            raise TaxFilingAuditError("Referenzmanifest fehlt.")
        return {
            "snapshot": snapshot,
            "members": members,
            "manifest": json.loads(members[manifest_name].decode("utf-8")),
        }

    @staticmethod
    def _archived_taxable(value: Any) -> bool | None:
        label = str(value or "").strip().casefold()
        if label in {"ja", "yes", "true"}:
            return True
        if label in {"nein", "no", "false"}:
            return False
        return None

    def _reference_tax_lines(self, package: dict[str, Any], year: int) -> list[dict[str, Any]]:
        members = package["members"]
        name = self._member(members, "tax-lines.csv")
        if name is None:
            return []
        manifest_file = self._manifest_file(package["manifest"], name)
        canonical = self._reference_canonical_events(package)
        rows: list[dict[str, Any]] = []
        for row_number, row in enumerate(self._csv(members[name]), start=2):
            disposed_at = self._parse_event_time(row.get("Datum_Verkauf"))
            if disposed_at is None or reporting_tax_year(disposed_at) != year:
                continue
            asset = str(row.get("Asset") or "").upper()
            event = self._match_reference_event(canonical, asset, disposed_at)
            rows.append(
                {
                    "asset": asset,
                    "quantity": self._decimal(row.get("Menge")),
                    "acquisition_cost": self._decimal(row.get("Anschaffungskosten_EUR")),
                    "proceeds": self._decimal(row.get("Veraeusserungserloes_EUR")),
                    "gain": self._decimal(row.get("Gewinn_Verlust_EUR")),
                    "holding_days": self._int(row.get("Haltedauer_Tage")),
                    "taxable": self._archived_taxable(row.get("Steuerpflichtig")),
                    "classification_policy": row.get("Frist_Methodenversion") or "archived_report_label",
                    "disposed_at": disposed_at,
                    "acquired_at": self._parse_event_time(row.get("Datum_Kauf")),
                    "event_id": event.get("event_id") if event else None,
                    "source": event.get("source") if event else None,
                    "source_ref": event.get("source_ref") if event else None,
                    "lot_id": None,
                    "acquisition_event_id": None,
                    "filename": name,
                    "file_hash": manifest_file.get("sha256") if manifest_file else hashlib.sha256(members[name]).hexdigest(),
                    "row_number": row_number,
                    "reference_export_only": True,
                }
            )
        return self._add_occurrences(rows)

    def _current_tax_lines(
        self,
        year: int,
        source_evidence: dict[str, dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        from steuerreport_v2.domain.tax_time import private_disposal_within_year

        events = {item.event_id: item for item in self.store.list_canonical_events()}
        raw_metadata = self._raw_metadata()
        rows: list[dict[str, Any]] = []
        for line in TaxService(self.store).list_tax_lines():
            if reporting_tax_year(line.disposed_at) != year:
                continue
            event = events.get(line.source_event_id)
            raw = raw_metadata.get(event.raw_object_id) if event else None
            validation = (source_evidence or {}).get(line.source_event_id, {})
            rows.append(
                {
                    "asset": line.asset.upper(),
                    "quantity": line.quantity,
                    "acquisition_cost": line.acquisition_cost_eur,
                    "proceeds": line.disposal_proceeds_eur,
                    "gain": line.gain_loss_eur,
                    "holding_days": line.holding_days,
                    "taxable": private_disposal_within_year(line.acquired_at, line.disposed_at),
                    "classification_policy": PRIVATE_HOLDING_POLICY_VERSION,
                    "disposed_at": line.disposed_at,
                    "acquired_at": line.acquired_at,
                    "event_id": line.source_event_id,
                    "source": event.source if event else None,
                    "source_ref": event.source_ref if event else None,
                    "lot_id": line.lot_id,
                    "acquisition_event_id": line.acquisition_source_event_id,
                    "filename": raw.get("filename") if raw else None,
                    "file_hash": raw.get("file_hash") if raw else None,
                    "row_number": raw.get("row_number") if raw else None,
                    "source_role": validation.get("source_role", "unknown"),
                    "source_validation_status": validation.get(
                        "source_validation_status", "not_applicable"
                    ),
                    "logical_event_group_id": validation.get("logical_event_group_id"),
                    "counterpart_event_ids": validation.get(
                        "counterpart_event_ids", []
                    ),
                    "tax_inclusion_status": validation.get(
                        "tax_inclusion_status", "included_current_runtime"
                    ),
                    "reference_export_only": False,
                }
            )
        return self._add_occurrences(rows)

    def _compare_positions(
        self,
        old: list[dict[str, Any]],
        new: list[dict[str, Any]],
        *,
        position_kind: str,
    ) -> tuple[list[TaxAuditDelta], dict[str, Any]]:
        pairs, removed, added = self._pair_positions(old, new)
        deltas: list[TaxAuditDelta] = []
        for prior, current in pairs:
            if not self._position_equal(prior, current):
                deltas.append(self._delta_from_position(prior, current, "changed", position_kind))
        for prior in removed:
            deltas.append(self._delta_from_position(prior, None, "removed", position_kind))
        for current in added:
            deltas.append(self._delta_from_position(None, current, "added", position_kind))
        return deltas, {"old": old, "current": new}

    def _pair_positions(
        self,
        old: list[dict[str, Any]],
        new: list[dict[str, Any]],
    ) -> tuple[list[tuple[dict[str, Any], dict[str, Any]]], list[dict[str, Any]], list[dict[str, Any]]]:
        old_by_key = defaultdict(list)
        new_by_key = defaultdict(list)
        for item in old:
            old_by_key[self._stable_position_key(item)].append(item)
        for item in new:
            new_by_key[self._stable_position_key(item)].append(item)
        pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
        remaining_old: list[dict[str, Any]] = []
        remaining_new: list[dict[str, Any]] = []
        for key in sorted(set(old_by_key) | set(new_by_key)):
            left = old_by_key[key]
            right = new_by_key[key]
            pair_count = min(len(left), len(right))
            pairs.extend(zip(left[:pair_count], right[:pair_count], strict=False))
            remaining_old.extend(left[pair_count:])
            remaining_new.extend(right[pair_count:])

        old_by_shape = defaultdict(list)
        new_by_shape = defaultdict(list)
        for item in remaining_old:
            old_by_shape[self._shape_key(item)].append(item)
        for item in remaining_new:
            new_by_shape[self._shape_key(item)].append(item)
        removed: list[dict[str, Any]] = []
        added: list[dict[str, Any]] = []
        for key in sorted(set(old_by_shape) | set(new_by_shape)):
            left = sorted(old_by_shape[key], key=self._position_sort_key)
            right = sorted(new_by_shape[key], key=self._position_sort_key)
            pair_count = min(len(left), len(right))
            pairs.extend(zip(left[:pair_count], right[:pair_count], strict=False))
            removed.extend(left[pair_count:])
            added.extend(right[pair_count:])
        return pairs, removed, added

    def _delta_from_position(
        self,
        old: dict[str, Any] | None,
        new: dict[str, Any] | None,
        change_kind: str,
        position_kind: str,
    ) -> TaxAuditDelta:
        item = new or old or {}
        cause, explanation = self._classify_cause(old, new, change_kind, position_kind)
        stable_key = self._stable_position_key(item)
        if old and new and old.get("event_id") and new.get("event_id"):
            stable_key = f"{new['event_id']}#{new.get('occurrence', 1)}"
        return TaxAuditDelta(
            position_kind=position_kind,
            change_kind=change_kind,
            stable_event_id_or_fingerprint=stable_key,
            source=item.get("source"),
            import_filename=item.get("filename"),
            import_file_sha256=item.get("file_hash"),
            import_row_number=item.get("row_number"),
            event_datetime_utc=self._iso(item.get("disposed_at") or item.get("event_time")),
            event_datetime_europe_berlin=self._berlin_iso(item.get("disposed_at") or item.get("event_time")),
            asset=item.get("asset"),
            quantity_old=old.get("quantity") if old else None,
            quantity_new=new.get("quantity") if new else None,
            quantity_delta=(new.get("quantity", Decimal("0")) if new else Decimal("0")) - (old.get("quantity", Decimal("0")) if old else Decimal("0")),
            acquisition_cost_old_eur=old.get("acquisition_cost") if old else None,
            acquisition_cost_new_eur=new.get("acquisition_cost") if new else None,
            acquisition_cost_delta_eur=(new.get("acquisition_cost", Decimal("0")) if new else Decimal("0")) - (old.get("acquisition_cost", Decimal("0")) if old else Decimal("0")),
            disposal_proceeds_old_eur=old.get("proceeds") if old else None,
            disposal_proceeds_new_eur=new.get("proceeds") if new else None,
            disposal_proceeds_delta_eur=(new.get("proceeds", Decimal("0")) if new else Decimal("0")) - (old.get("proceeds", Decimal("0")) if old else Decimal("0")),
            fifo_lot_old=old.get("lot_id") if old else None,
            fifo_lot_new=new.get("lot_id") if new else None,
            old_value_eur=old.get("gain") if old else None,
            new_value_eur=new.get("gain") if new else None,
            value_delta_eur=(new.get("gain", Decimal("0")) if new else Decimal("0")) - (old.get("gain", Decimal("0")) if old else Decimal("0")),
            holding_days_old=old.get("holding_days") if old else None,
            holding_days_new=new.get("holding_days") if new else None,
            taxable_old=old.get("taxable") if old else None,
            taxable_new=new.get("taxable") if new else None,
            classification_policy_old=old.get("classification_policy") if old else None,
            classification_policy_new=new.get("classification_policy") if new else None,
            cause=cause,
            cause_explanation=explanation,
            source_role=item.get("source_role", "unknown"),
            source_validation_status=item.get(
                "source_validation_status", "not_applicable"
            ),
            logical_event_group_id=item.get("logical_event_group_id"),
            counterpart_event_ids=item.get("counterpart_event_ids", []),
            tax_inclusion_status=item.get(
                "tax_inclusion_status", "included_current_runtime"
            ),
            review_required=True,
            human_approval_status="required",
        )

    def _classify_cause(
        self,
        old: dict[str, Any] | None,
        new: dict[str, Any] | None,
        change_kind: str,
        position_kind: str,
    ) -> tuple[str, str]:
        if position_kind == "derivative_line":
            return "derivatives", "Die Position stammt aus der separaten Derivate-Auswertung."
        if position_kind == "reward_income_position":
            return "rewards_mining_staking", "Die Position stammt aus der getrennten Reward-/Mining-/Staking-Klassifikation."
        if change_kind == "added":
            if new and new.get("filename") and new.get("file_hash"):
                return "new_import", "Die aktuelle Position ist in der Referenzposition nicht enthalten und stammt aus einem aktuellen Import."
            return "previously_unconsidered_source", "Die aktuelle Position hat keine passende Referenzquelle."
        if change_kind == "removed":
            return "unknown", "Die Referenzposition ist aktuell nicht auffindbar; eine Korrektur oder Loeschung ist nicht belegt."
        if old and new:
            if old.get("lot_id") != new.get("lot_id") or old.get("acquisition_event_id") != new.get("acquisition_event_id"):
                return "fifo_lot_assignment", "FIFO-Lot oder Anschaffungs-Event ist zwischen den Staenden anders zugeordnet."
            if old.get("holding_days") != new.get("holding_days") or old.get("taxable") != new.get("taxable"):
                return "holding_period_classification", "Haltedauer oder steuerliche Haltefristklassifikation hat sich geaendert."
            if old.get("source") != new.get("source"):
                return "previously_unconsidered_source", "Die Positionsquelle hat sich zwischen Referenz und aktueller Auswertung geaendert."
            if any(old.get(key) != new.get(key) for key in ("acquisition_cost", "proceeds", "gain")):
                return "price_or_fx_change", "Ereignis und Lot bleiben strukturell gleich, aber mindestens ein EUR-Wert ist anders."
        return "unknown", "Die Position ist geaendert, aber die vorhandenen Daten belegen keine spezifischere Ursache."

    def _compare_reward_positions(
        self, old: list[dict[str, Any]], year: int
    ) -> tuple[list[TaxAuditDelta], dict[str, Any]]:
        current_report = TaxYearService(self.store).income_report(year)
        current = [
            {
                "asset": item.asset.upper(),
                "event_type": item.event_type,
                "classification": item.classification,
                "quantity": item.quantity,
                "gain": item.income_eur,
                "source": ",".join(item.sources),
                "event_count": item.events_count,
                "filename": None,
                "file_hash": None,
            }
            for item in current_report.assets
            if item.income_eur != 0 and self._is_declaration_reward(item.classification)
        ]
        pairs, removed, added = self._pair_reward_positions(old, current)
        deltas: list[TaxAuditDelta] = []
        for prior, item in pairs:
            if prior.get("quantity") != item.get("quantity") or prior.get("gain") != item.get("gain"):
                deltas.append(self._delta_from_position(prior, item, "changed", "reward_income_position"))
        deltas.extend(self._delta_from_position(item, None, "removed", "reward_income_position") for item in removed)
        deltas.extend(self._delta_from_position(None, item, "added", "reward_income_position") for item in added)
        return deltas, {"old": old, "current": current}

    @staticmethod
    def _pair_reward_positions(old: list[dict[str, Any]], new: list[dict[str, Any]]):
        old_map = {TaxFilingAuditService._reward_key(item): item for item in old}
        new_map = {TaxFilingAuditService._reward_key(item): item for item in new}
        pairs = [(old_map[key], new_map[key]) for key in sorted(set(old_map) & set(new_map))]
        removed = [old_map[key] for key in sorted(set(old_map) - set(new_map))]
        added = [new_map[key] for key in sorted(set(new_map) - set(old_map))]
        return pairs, removed, added

    def _compare_derivative_positions(
        self,
        old: list[dict[str, Any]],
        year: int,
        source_evidence: dict[str, dict[str, Any]] | None = None,
    ) -> tuple[list[TaxAuditDelta], dict[str, Any]]:
        current = []
        for item in DerivativesManager(self.store).list_lines():
            if reporting_tax_year(item.event_time) != year:
                continue
            validation = (source_evidence or {}).get(item.event_id, {})
            current.append(
                {
                    "asset": item.asset.upper(),
                    "event_id": item.event_id,
                    "event_time": item.event_time,
                    "quantity": item.quantity,
                    "gain": item.value_eur,
                    "source": item.source,
                    "source_ref": item.source_ref,
                    "filename": None,
                    "file_hash": None,
                    "source_role": validation.get("source_role", "unknown"),
                    "source_validation_status": validation.get(
                        "source_validation_status", "not_applicable"
                    ),
                    "logical_event_group_id": validation.get("logical_event_group_id"),
                    "counterpart_event_ids": validation.get(
                        "counterpart_event_ids", []
                    ),
                    "tax_inclusion_status": validation.get(
                        "tax_inclusion_status", "included_current_runtime"
                    ),
                }
            )
        deltas, _ = self._compare_positions(old, current, position_kind="derivative_line")
        return deltas, {"old": old, "current": current}

    def _reconciliation(
        self,
        *,
        baseline_values: Any,
        current_values: Any,
        deltas: list[TaxAuditDelta],
    ) -> list[TaxAuditAggregateReconciliation]:
        result: list[TaxAuditAggregateReconciliation] = []
        definitions = (
            ("private_disposals", "Private Veraeusserungen", "taxable_private_disposals_eur"),
            ("tax_free_disposals", "Steuerfreie Veraeusserungen", "tax_free_private_disposals_eur"),
            ("rewards_mining_staking", "Rewards/Mining/Staking", "rewards_mining_staking_income_eur"),
            ("derivatives", "Derivate", "derivative_pnl_eur"),
            ("disposal_proceeds", "Veraeusserungserloese", "taxable_disposal_proceeds_eur"),
            ("acquisition_costs", "Anschaffungskosten", "acquisition_cost_eur"),
        )
        for key, label, value_key in definitions:
            reference = Decimal(getattr(baseline_values, value_key)) if baseline_values else Decimal("0")
            current = Decimal(getattr(current_values, value_key))
            aggregate_delta = current - reference
            if key == "private_disposals":
                individual = self._line_delta(deltas, taxable=True)
            elif key == "tax_free_disposals":
                individual = self._line_delta(deltas, taxable=False)
            elif key == "disposal_proceeds":
                individual = self._line_amount_delta(
                    deltas, field="disposal_proceeds_delta_eur", taxable=True
                )
            elif key == "acquisition_costs":
                individual = self._line_amount_delta(
                    deltas, field="acquisition_cost_delta_eur", taxable=True
                )
            elif key == "rewards_mining_staking":
                individual = sum((item.value_delta_eur or Decimal("0") for item in deltas if item.position_kind == "reward_income_position"), Decimal("0"))
            else:
                individual = sum((item.value_delta_eur or Decimal("0") for item in deltas if item.position_kind == "derivative_line"), Decimal("0"))
            residual = individual - aggregate_delta
            status = "reconciled" if residual == 0 else "reconciliation_failed"
            result.append(
                TaxAuditAggregateReconciliation(
                    key=key,
                    label=label,
                    reference_value_eur=reference,
                    current_value_eur=current,
                    aggregate_delta_eur=aggregate_delta,
                    individual_delta_eur=individual,
                    residual_eur=residual,
                    status=status,
                    source="reference snapshot summary + current V2 tax lines/income/derivatives",
                    explanation=(
                        "Einzelpositionen leiten exakt auf die Aggregatdifferenz ueber."
                        if status == "reconciled"
                        else "Die Differenz zwischen Einzelpositionen und Aggregat ist nicht null; fachliche Klaerung erforderlich."
                    ),
                )
            )
        return result

    @staticmethod
    def _line_delta(deltas: list[TaxAuditDelta], *, taxable: bool) -> Decimal:
        total = Decimal("0")
        for item in deltas:
            if item.position_kind != "tax_line":
                continue
            old_part = item.old_value_eur if item.taxable_old is not None and item.taxable_old == taxable else Decimal("0")
            new_part = item.new_value_eur if item.taxable_new is not None and item.taxable_new == taxable else Decimal("0")
            total += (new_part or Decimal("0")) - (old_part or Decimal("0"))
        return total

    @staticmethod
    def _line_amount_delta(
        deltas: list[TaxAuditDelta], *, field: str, taxable: bool
    ) -> Decimal:
        total = Decimal("0")
        for item in deltas:
            if item.position_kind != "tax_line":
                continue
            old_in_bucket = (
                item.taxable_old is not None
                and item.taxable_old == taxable
            )
            new_in_bucket = (
                item.taxable_new is not None
                and item.taxable_new == taxable
            )
            value = getattr(item, field) or Decimal("0")
            if old_in_bucket and new_in_bucket:
                total += value
            elif new_in_bucket:
                total += getattr(item, field.replace("delta", "new")) or Decimal("0")
            elif old_in_bucket:
                total -= getattr(item, field.replace("delta", "old")) or Decimal("0")
        return total

    def _cash_separation(self, year: int) -> TaxAuditCashSeparation:
        turnover = TaxYearService(self.store).turnover_audit(year, limit=0)
        deposit_report = PortfolioService(self.store).fiat_deposit_report(
            cutoff=datetime(year, 1, 1, tzinfo=timezone.utc), source="binance"
        )
        deposits = sum(
            (
                item.receive_amount_eur
                for item in deposit_report.rows
                if reporting_tax_year(item.time_utc) == year
            ),
            Decimal("0"),
        )
        return TaxAuditCashSeparation(
            trade_swap_volume_eur=turnover.gross_disposal_proceeds_eur,
            actual_eur_deposits_eur=deposits,
            actual_eur_withdrawals_eur=None,
            taxable_gain_loss_eur=turnover.taxable_gain_loss_eur,
            tax_free_gain_loss_eur=turnover.tax_free_gain_loss_eur,
            internal_transfers_eur=None,
            actual_eur_deposits_status="evidence_derived_binance_eur_transfers",
            actual_eur_withdrawals_status="not_available_without_source_bound_withdrawal_evidence",
            internal_transfers_status="not_available_without_cross_account_reconciliation",
            notes=[
                "Handels-/Swapvolumen ist eine EUR-Bewertung von Veraeusserungen und Swaps, nicht Einkommen und kein ausgezahltes Geld.",
                "EUR-Einzahlungen sind nur als belegte positive Binance-EUR-Transferereignisse ausgewiesen.",
                "Ein allgemeiner quellenuebergreifender EUR-Auszahlungsbeleg und eine sichere interne Transfer-Gesamtsumme liegen nicht vor.",
            ],
        )

    def _endpoint_evidence(
        self, *, year: int, queried_at: datetime, comparison: Any
    ) -> list[TaxAuditEndpointEvidence]:
        tax_year = TaxYearService(self.store)
        payloads: dict[str, Any] = {
            "filing-snapshot-comparison": comparison,
            "filing-snapshots": self.snapshots.list(year=year),
            "methodology": TaxMethodologyService(self.store).report(year),
            "drivers": tax_year.driver_report(year, limit=50),
            "turnover-audit": tax_year.turnover_audit(year, limit=50),
            "gain-evidence-event-deltas": tax_year.gain_evidence_event_delta_review(year, limit=200),
            "gain-evidence-acquisition-event-deltas": tax_year.gain_evidence_acquisition_event_delta_review(year, limit=200),
            "gain-evidence-price-deltas": tax_year.gain_evidence_price_delta_drilldown(year, limit=200),
        }
        result: list[TaxAuditEndpointEvidence] = []
        for endpoint_name in ENDPOINT_TEMPLATES:
            payload = payloads[endpoint_name]
            encoded = self._canonical_json(
                self._stable_payload(payload.model_dump(mode="json"))
            )
            result.append(
                TaxAuditEndpointEvidence(
                    endpoint=f"/api/v1/tax-years/{year}/{endpoint_name}",
                    query_timestamp_utc=queried_at.isoformat(),
                    query_timestamp_europe_berlin=queried_at.astimezone(BERLIN).isoformat(),
                    payload_sha256=hashlib.sha256(encoded).hexdigest(),
                    source="current_runtime",
                    available=True,
                    note="Interner read-only Serviceaufruf entsprechend dem API-Vertrag.",
                )
            )
        return result

    def _source_reconciliation(
        self, year: int
    ) -> tuple[TaxAuditSourceReconciliation, dict[str, dict[str, Any]]]:
        """Build a read-only provenance map before tax deltas are compared.

        Aggregator rows remain in the database and in the current runtime result.
        They are only certified as a transfer mirror when a primary-source event
        has the same transaction identifier, asset, and opposite quantity.
        """
        events = [
            event
            for event in self.store.list_canonical_events()
            if reporting_tax_year(event.event_time) == year
        ]
        raw_metadata = self._raw_metadata()
        tax_event_counts = Counter(
            line.source_event_id
            for line in TaxService(self.store).list_tax_lines()
            if reporting_tax_year(line.disposed_at) == year
        )
        derivative_event_ids = {
            line.event_id
            for line in DerivativesManager(self.store).list_lines()
            if reporting_tax_year(line.event_time) == year
        }
        primary_events = [
            event for event in events if event.source in PRIMARY_SOURCE_NAMES
        ]
        aggregator_events = [
            event for event in events if event.source in AGGREGATOR_SOURCE_NAMES
        ]
        primary_index: defaultdict[tuple[str, str], list[Any]] = defaultdict(list)
        for event in primary_events:
            for identifier in self._event_identifiers(event):
                primary_index[(identifier, event.asset.upper())].append(event)

        evidence: dict[str, dict[str, Any]] = {}
        aggregator_mirror_matches: list[TaxAuditMirrorMatch] = []
        primary_transfer_matches: list[TaxAuditMirrorMatch] = []
        matched_primary_ids: set[str] = set()
        matched_aggregator_ids: set[str] = set()

        for event in events:
            role = self._source_role(event.source)
            evidence[event.event_id] = {
                "source_role": role,
                "source_validation_status": "not_applicable",
                "logical_event_group_id": None,
                "counterpart_event_ids": [],
                "tax_inclusion_status": (
                    "included_current_runtime"
                    if role != "aggregator_mirror"
                    else "pending_review"
                ),
            }

        for event in sorted(aggregator_events, key=lambda item: item.event_id):
            match = self._find_primary_transfer_match(
                event,
                primary_index,
                matched_primary_ids,
            )
            if match is None:
                evidence[event.event_id].update(
                    {
                        "source_validation_status": "unmatched_review",
                        "tax_inclusion_status": "pending_review",
                    }
                )
                continue

            primary, match_basis = match
            group_id = "mirror:" + self._fingerprint(
                {"events": sorted([event.event_id, primary.event_id]), "basis": match_basis}
            )[:24]
            matched_primary_ids.add(primary.event_id)
            matched_aggregator_ids.add(event.event_id)
            evidence[event.event_id].update(
                {
                    "source_validation_status": "matched_primary_transfer",
                    "logical_event_group_id": group_id,
                    "counterpart_event_ids": [primary.event_id],
                    "tax_inclusion_status": "not_independent_tax_event",
                }
            )
            evidence[primary.event_id].update(
                {
                    "source_validation_status": "matched_aggregator_mirror",
                    "logical_event_group_id": group_id,
                    "counterpart_event_ids": [event.event_id],
                }
            )
            aggregator_mirror_matches.append(
                TaxAuditMirrorMatch(
                    logical_event_group_id=group_id,
                    asset=event.asset.upper(),
                    match_basis=match_basis,
                    events=[
                        self._source_event_contract(
                            event,
                            raw_metadata.get(event.raw_object_id),
                            self._source_role(event.source),
                            "not_independent_tax_event",
                        ),
                        self._source_event_contract(
                            primary,
                            raw_metadata.get(primary.raw_object_id),
                            self._source_role(primary.source),
                            "included_current_runtime",
                        ),
                    ],
                )
            )

        matched_primary_transfer_ids: set[str] = set()
        for event in sorted(primary_events, key=lambda item: item.event_id):
            if (
                event.event_id in matched_primary_ids
                or event.event_id in matched_primary_transfer_ids
            ):
                continue
            match = self._find_primary_transfer_match(
                event,
                primary_index,
                matched_primary_ids | matched_primary_transfer_ids,
                require_distinct_source=True,
            )
            if match is None:
                continue

            counterpart, match_basis = match
            group_id = "mirror:" + self._fingerprint(
                {
                    "events": sorted([event.event_id, counterpart.event_id]),
                    "basis": match_basis,
                }
            )[:24]
            matched_primary_transfer_ids.update(
                {event.event_id, counterpart.event_id}
            )
            for current, other in ((event, counterpart), (counterpart, event)):
                evidence[current.event_id].update(
                    {
                        "source_validation_status": "matched_primary_transfer",
                        "logical_event_group_id": group_id,
                        "counterpart_event_ids": [other.event_id],
                        "tax_inclusion_status": "not_independent_tax_event",
                    }
                )
            primary_transfer_matches.append(
                TaxAuditMirrorMatch(
                    logical_event_group_id=group_id,
                    asset=event.asset.upper(),
                    match_basis=match_basis,
                    events=[
                        self._source_event_contract(
                            event,
                            raw_metadata.get(event.raw_object_id),
                            self._source_role(event.source),
                            "not_independent_tax_event",
                        ),
                        self._source_event_contract(
                            counterpart,
                            raw_metadata.get(counterpart.raw_object_id),
                            self._source_role(counterpart.source),
                            "not_independent_tax_event",
                        ),
                    ],
                )
            )

        unmatched_aggregator_events = [
            event for event in aggregator_events if event.event_id not in matched_aggregator_ids
        ]
        unmatched_tax_count = sum(
            tax_event_counts.get(event.event_id, 0)
            for event in unmatched_aggregator_events
        )
        unmatched_derivative_count = sum(
            1
            for event in unmatched_aggregator_events
            if event.event_id in derivative_event_ids
        )
        unmatched_count = len(unmatched_aggregator_events)
        mirror_matches = aggregator_mirror_matches + primary_transfer_matches
        open_points: list[str] = []
        if aggregator_mirror_matches:
            open_points.append(
                f"{len(aggregator_mirror_matches)} Blockpit-Transfergruppe(n) wurden als Spiegel einer "
                "primaeren Binance-/Solana-Gegenbuchung erkannt; sie duerfen nicht doppelt "
                "als eigenstaendige Transaktionen gelten."
            )
        if primary_transfer_matches:
            open_points.append(
                f"{len(primary_transfer_matches)} primaere Transfergruppe(n) wurden zwischen "
                "Binance und Solana/RPC mit identischer Transaktions-ID, identischem Asset "
                "und Gegenmenge erkannt; sie werden als ein logisches internes Ereignis "
                "gefuehrt und nicht doppelt bewertet."
            )
        if unmatched_tax_count or unmatched_derivative_count:
            open_points.append(
                f"{unmatched_tax_count} Blockpit-Steuerzeile(n) und "
                f"{unmatched_derivative_count} Blockpit-Derivatezeile(n) haben keine "
                "primaere Gegenquelle. Sie bleiben pending_review und werden durch diesen "
                "Audit nicht als steuerlich bestaetigt freigegeben."
            )
        if unmatched_count:
            open_points.append(
                f"{unmatched_count} Blockpit-Ereignis(se) sind nicht gegen eine primaere "
                "Quelle gematcht; gleiche Menge oder gleiche Uhrzeit allein reicht nicht "
                "fuer eine Anerkennung."
            )

        role_counts = Counter(self._source_role(event.source) for event in events)
        reconciliation = TaxAuditSourceReconciliation(
            status="review_required" if unmatched_count else "verified",
            primary_sources=sorted(PRIMARY_SOURCE_NAMES),
            aggregator_sources=sorted(AGGREGATOR_SOURCE_NAMES),
            source_role_counts=dict(sorted(role_counts.items())),
            matched_mirror_group_count=len(aggregator_mirror_matches),
            matched_mirror_event_count=len(aggregator_mirror_matches) * 2,
            matched_primary_transfer_group_count=len(primary_transfer_matches),
            matched_primary_transfer_event_count=len(primary_transfer_matches) * 2,
            unmatched_aggregator_event_count=unmatched_count,
            unmatched_aggregator_tax_line_count=unmatched_tax_count,
            unmatched_aggregator_derivative_count=unmatched_derivative_count,
            mirror_matches=mirror_matches,
            open_review_points=open_points,
        )
        return reconciliation, evidence

    @staticmethod
    def _source_role(source: str | None) -> str:
        if source in PRIMARY_SOURCE_NAMES:
            return "primary"
        if source in AGGREGATOR_SOURCE_NAMES:
            return "aggregator_mirror"
        return "unknown"

    @staticmethod
    def _event_identifiers(event: Any) -> list[str]:
        result: list[str] = []
        for value in (event.tx_id, event.source_ref):
            normalized = str(value or "").strip()
            if normalized and normalized not in result:
                result.append(normalized)
        return result

    def _find_primary_transfer_match(
        self,
        aggregator_event: Any,
        primary_index: defaultdict[tuple[str, str], list[Any]],
        matched_primary_ids: set[str],
        *,
        require_distinct_source: bool = False,
    ) -> tuple[Any, str] | None:
        if aggregator_event.event_type not in {"transfer", "unknown"}:
            return None
        for identifier_kind, identifier in (
            ("tx_id", str(aggregator_event.tx_id or "").strip()),
            ("source_ref", str(aggregator_event.source_ref or "").strip()),
        ):
            if not identifier:
                continue
            candidates = primary_index.get(
                (identifier, aggregator_event.asset.upper()), []
            )
            for candidate in candidates:
                if candidate.event_id in matched_primary_ids:
                    continue
                if require_distinct_source and candidate.source == aggregator_event.source:
                    continue
                if candidate.event_type not in {"transfer", "unknown"}:
                    continue
                if candidate.quantity != -aggregator_event.quantity:
                    continue
                return candidate, f"exact_{identifier_kind}_asset_opposite_quantity"
        return None

    def _source_event_contract(
        self,
        event: Any,
        raw: dict[str, Any] | None,
        source_role: str,
        tax_inclusion_status: str,
    ) -> TaxAuditSourceEvent:
        payload: dict[str, Any] = {}
        if raw and raw.get("payload_json"):
            try:
                parsed = json.loads(str(raw["payload_json"]))
                if isinstance(parsed, dict):
                    payload = parsed
            except (TypeError, ValueError):
                payload = {}
        return TaxAuditSourceEvent(
            event_id=event.event_id,
            source=event.source,
            source_role=source_role,
            event_type=event.event_type,
            source_ref=event.source_ref,
            tx_id=event.tx_id,
            event_datetime_utc=self._iso(event.event_time),
            asset=event.asset.upper(),
            quantity=event.quantity,
            import_filename=raw.get("filename") if raw else None,
            import_file_sha256=raw.get("file_hash") if raw else None,
            import_row_number=raw.get("row_number") if raw else None,
            reported_integration=(
                payload.get("Integration Name") or payload.get("integration_name")
            ),
            tax_inclusion_status=tax_inclusion_status,
        )

    def _current_source_files(self) -> list[dict[str, Any]]:
        return [
            {
                "source": item.source,
                "filename": item.filename,
                "sha256": item.file_hash,
                "status": item.status,
                "batch_id": item.batch_id,
                "source_role": self._source_role(item.source),
                "review_status": (
                    "pending_review"
                    if item.source in AGGREGATOR_SOURCE_NAMES
                    else "not_applicable"
                ),
            }
            for item in sorted(
                self.store.list_import_batches(),
                key=lambda item: (item.source, item.filename, item.file_hash),
            )
        ]

    def _raw_metadata(self) -> dict[str, dict[str, Any]]:
        with self.store.connect() as con:
            rows = con.execute(
                """
                select r.raw_object_id, r.row_number, b.filename, b.file_hash,
                       r.payload_json
                from raw_objects r join raw_import_batches b on b.batch_id = r.batch_id
                """
            ).fetchall()
        return {
            str(row[0]): {
                "row_number": int(row[1]) if row[1] is not None else None,
                "filename": row[2],
                "file_hash": row[3],
                "payload_json": row[4],
            }
            for row in rows
        }

    def _reference_metadata(self, snapshot: Any) -> TaxAuditSnapshotMetadata:
        return TaxAuditSnapshotMetadata(
            snapshot_id=snapshot.snapshot_id,
            package_name=snapshot.package_filename,
            package_sha256=snapshot.package_sha256,
            manifest_sha256=snapshot.manifest_sha256,
            package_generated_at_utc=snapshot.package_generated_at,
            package_generated_at_europe_berlin=snapshot.package_generated_at_europe_berlin,
            created_at_utc=snapshot.created_at,
            created_at_europe_berlin=snapshot.created_at_europe_berlin,
            software_version=snapshot.software_version,
            method_version=snapshot.method_version,
            database_fingerprint_sha256=snapshot.database_fingerprint_sha256,
            runtime_fingerprint_sha256=snapshot.runtime_fingerprint_sha256,
            filing_usage_confirmed=snapshot.filing_usage_confirmed,
            filing_usage_confirmation_event_id=self._usage_event_id(snapshot.snapshot_id),
            filing_usage_confirmation_statement=snapshot.filing_usage_confirmation_statement,
            integrity_status=snapshot.integrity_status,
            source_kind=snapshot.source_kind,
            confirmation_scope=(
                "Vom Nutzer als fuer die Steuererklaerung verwendet bestaetigt."
                if snapshot.filing_usage_confirmed
                else "Nur als Referenz registriert; Verwendung fuer die Steuererklaerung nicht bestaetigt."
            ),
        )

    def _usage_event_id(self, snapshot_id: str) -> str | None:
        with self.store.connect() as con:
            row = con.execute(
                """
                select event_id from tax_filing_snapshot_events
                where snapshot_id = ? and event_type = 'filing_package_usage_confirmed'
                order by created_at, event_id limit 1
                """,
                [snapshot_id],
            ).fetchone()
        return str(row[0]) if row else None

    def _reference_rewards(self, package: dict[str, Any], year: int) -> list[dict[str, Any]]:
        name = self._member(package["members"], "tax-income-guide.csv")
        if name is None:
            return []
        manifest_file = self._manifest_file(package["manifest"], name)
        result = []
        for row in self._csv(package["members"][name]):
            if self._int(row.get("Jahr")) != year:
                continue
            treatment = str(row.get("Steuerliche_Behandlung") or "").lower()
            classification = str(row.get("Klassifizierung") or "")
            if not (treatment.startswith("eintragen") or self._is_declaration_reward(classification)):
                continue
            result.append(
                {
                    "asset": str(row.get("Asset") or "").upper(),
                    "event_type": str(row.get("Event_Typ") or ""),
                    "classification": classification,
                    "quantity": self._decimal(row.get("Menge")),
                    "gain": self._decimal(row.get("Wert_EUR")),
                    "source": str(row.get("Quellen") or ""),
                    "filename": name,
                    "file_hash": manifest_file.get("sha256") if manifest_file else hashlib.sha256(package["members"][name]).hexdigest(),
                }
            )
        return result

    def _reference_derivatives(self, package: dict[str, Any], year: int) -> list[dict[str, Any]]:
        name = self._member(package["members"], "derivative-lines.csv")
        if name is None:
            return []
        result = []
        for row in self._csv(package["members"][name]):
            event_time = self._parse_event_time(row.get("event_time") or row.get("Zeitpunkt_UTC"))
            if event_time is None or reporting_tax_year(event_time) != year:
                continue
            result.append(
                {
                    "asset": str(row.get("asset") or row.get("Asset") or "").upper(),
                    "event_id": row.get("event_id") or row.get("Event_ID"),
                    "event_time": event_time,
                    "quantity": self._decimal(row.get("quantity") or row.get("Menge")),
                    "gain": self._decimal(row.get("value_eur") or row.get("Wert_EUR") or row.get("pnl_eur")),
                    "source": row.get("source") or row.get("Quelle"),
                }
            )
        return result

    def _reference_canonical_events(self, package: dict[str, Any]) -> list[dict[str, Any]]:
        name = self._member(package["members"], "canonical-events.csv")
        if name is None:
            return []
        result = []
        for row in self._csv(package["members"][name]):
            result.append(
                {
                    "event_id": row.get("Event_ID"),
                    "event_time": self._parse_event_time(row.get("Zeitpunkt_UTC")),
                    "source": row.get("Quelle"),
                    "source_ref": row.get("Source_Ref"),
                    "event_type": row.get("Event_Typ"),
                    "asset": str(row.get("Asset") or "").upper(),
                }
            )
        return result

    @staticmethod
    def _match_reference_event(events: list[dict[str, Any]], asset: str, at: datetime) -> dict[str, Any] | None:
        candidates = [item for item in events if item.get("asset") == asset and item.get("event_time")]
        exact = [item for item in candidates if item["event_time"] == at]
        if exact:
            return exact[0]
        same_day = [item for item in candidates if item["event_time"].date() == at.date()]
        return same_day[0] if len(same_day) == 1 else None

    @staticmethod
    def _add_occurrences(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counts: defaultdict[str, int] = defaultdict(int)
        result = []
        for item in sorted(rows, key=TaxFilingAuditService._position_sort_key):
            key = TaxFilingAuditService._base_stable_key(item)
            counts[key] += 1
            copy = dict(item)
            copy["occurrence"] = counts[key]
            result.append(copy)
        return result

    @staticmethod
    def _base_stable_key(item: dict[str, Any]) -> str:
        if item.get("event_id"):
            return str(item["event_id"])
        return TaxFilingAuditService._fingerprint(
            {
                "asset": item.get("asset"),
                "disposed_at": TaxFilingAuditService._iso(item.get("disposed_at")),
                "quantity": str(item.get("quantity", "")),
            }
        )[:32]

    @staticmethod
    def _stable_position_key(item: dict[str, Any]) -> str:
        return f"{TaxFilingAuditService._base_stable_key(item)}#{item.get('occurrence', 1)}"

    @staticmethod
    def _shape_key(item: dict[str, Any]) -> tuple[str, str]:
        when = item.get("disposed_at") or item.get("event_time")
        return str(item.get("asset") or ""), TaxFilingAuditService._iso(when)[:10]

    @staticmethod
    def _position_sort_key(item: dict[str, Any]) -> tuple[str, str, str, str]:
        return (
            str(item.get("asset") or ""),
            TaxFilingAuditService._iso(item.get("disposed_at") or item.get("event_time")),
            TaxFilingAuditService._iso(item.get("acquired_at")),
            str(item.get("quantity") or "0"),
        )

    @staticmethod
    def _position_equal(old: dict[str, Any], new: dict[str, Any]) -> bool:
        keys = (
            "asset",
            "quantity",
            "acquisition_cost",
            "proceeds",
            "gain",
            "holding_days",
            "lot_id",
            "acquisition_event_id",
            "taxable",
        )
        return all(old.get(key) == new.get(key) for key in keys)

    @staticmethod
    def _reward_key(item: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(item.get("asset") or ""),
            str(item.get("event_type") or ""),
            str(item.get("classification") or ""),
        )

    @staticmethod
    def _is_declaration_reward(classification: str) -> bool:
        normalized = classification.lower()
        return "reward_income_candidate" in normalized or normalized in {"reward", "mining", "staking"}

    @staticmethod
    def _member(members: dict[str, bytes], suffix: str) -> str | None:
        return next((name for name in members if name.endswith(suffix)), None)

    @staticmethod
    def _manifest_file(manifest: dict[str, Any], name: str) -> dict[str, Any] | None:
        return next((item for item in manifest.get("files", []) if item.get("path") == name), None)

    @staticmethod
    def _csv(content: bytes) -> list[dict[str, str]]:
        return list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        if value is None or str(value).strip() == "":
            return Decimal("0")
        text = str(value).strip().replace(" ", "")
        if "," in text and "." in text:
            text = text.replace(".", "").replace(",", ".")
        elif "," in text:
            text = text.replace(",", ".")
        return Decimal(text)

    @staticmethod
    def _int(value: Any) -> int:
        try:
            return int(str(value or "0").strip())
        except ValueError:
            return 0

    @staticmethod
    def _parse_event_time(value: Any) -> datetime | None:
        if value is None or not str(value).strip():
            return None
        try:
            parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d"):
                try:
                    parsed = datetime.strptime(str(value).strip(), fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _iso(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, datetime):
            parsed = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat()
        return str(value)

    @staticmethod
    def _berlin_iso(value: Any) -> str | None:
        if value is None:
            return None
        parsed = value if isinstance(value, datetime) else TaxFilingAuditService._parse_event_time(value)
        return parsed.astimezone(BERLIN).isoformat() if parsed else None

    @staticmethod
    def _canonical_json(value: Any) -> bytes:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")

    @classmethod
    def _fingerprint(cls, value: Any) -> str:
        return hashlib.sha256(cls._canonical_json(value)).hexdigest()

    @classmethod
    def _stable_payload(cls, value: Any) -> Any:
        volatile = {
            "generated_at",
            "generated_at_utc",
            "generated_at_europe_berlin",
            "created_at_utc",
            "created_at_europe_berlin",
            "package_generated_at_utc",
            "package_generated_at_europe_berlin",
            "query_timestamp_utc",
            "query_timestamp_europe_berlin",
            "report_id",
            "report_content_sha256",
            "markdown_content_sha256",
            "json_artifact_endpoint",
            "markdown_artifact_endpoint",
        }
        if isinstance(value, dict):
            return {
                key: cls._stable_payload(item)
                for key, item in sorted(value.items())
                if key not in volatile
            }
        if isinstance(value, list):
            return [cls._stable_payload(item) for item in value]
        return value

    def _markdown(self, report: TaxFilingAuditReport) -> str:
        lines = [
            f"# Steuerjahr {report.year}: revisionssicherer Auditvergleich",
            "",
            f"- Report-ID: {report.report_id}",
            f"- Status: {report.status}",
            f"- API-Abfrage UTC: {report.generated_at_utc}",
            f"- API-Abfrage Europe/Berlin: {report.generated_at_europe_berlin}",
            f"- JSON-Inhaltsfingerprint: {report.report_content_sha256}",
            "- Automatische steuerliche Korrektur: nein",
            "- Datenbank veraendert: nein",
            "",
            "## Referenzstand",
            "",
        ]
        if report.reference:
            lines.extend(self._metadata_markdown(report.reference))
        else:
            lines.append("Kein Referenzstand vorhanden.")
        lines.extend(["", "## Aktueller Vergleichsstand", ""])
        lines.extend(self._metadata_markdown(report.current))
        lines.extend(
            [
                "",
                "## Summenabgleich",
                "",
                "| Bereich | Referenz | Aktuell | Aggregatdelta | Einzeldelta | Rest | Status |",
                "|---|---:|---:|---:|---:|---:|---|",
            ]
        )
        for item in report.reconciliation:
            lines.append(
                f"| {item.label} | {item.reference_value_eur} | {item.current_value_eur} | "
                f"{item.aggregate_delta_eur} | {item.individual_delta_eur} | "
                f"{item.residual_eur} | {item.status} |"
            )
        lines.extend(
            [
                "",
                "## Vollstaendige Delta-Tabelle",
                "",
                "| Art | Aenderung | stabile ID/Fingerprint | Quelle | Quellenrolle | Quellenpruefung | Steuerstatus | Gegenereignisse | Importdatei/Hash/Zeile | Zeitpunkt | Asset/Menge | Anschaffung | Erloes | FIFO-Lot | Alter Wert | Neuer Wert | Differenz | Ursache | Erklaerung | Freigabe |",
                "|---|---|---|---|---|---|---|---|---|---|---|---:|---:|---|---:|---:|---:|---|---|---|",
            ]
        )
        for item in report.deltas:
            source_file = (
                f"{item.import_filename or '-'} / {item.import_file_sha256 or '-'} / "
                f"{item.import_row_number or '-'}"
            )
            lines.append(
                f"| {item.position_kind} | {item.change_kind} | {item.stable_event_id_or_fingerprint} | "
                f"{item.source or '-'} | {item.source_role} | {item.source_validation_status} | "
                f"{item.tax_inclusion_status} | {', '.join(item.counterpart_event_ids) or '-'} | "
                f"{source_file} | {item.event_datetime_utc or '-'} | "
                f"{item.asset or '-'} / {item.quantity_delta or 0} | "
                f"{item.acquisition_cost_delta_eur or 0} | {item.disposal_proceeds_delta_eur or 0} | "
                f"{item.fifo_lot_old or '-'} -> {item.fifo_lot_new or '-'} | "
                f"{item.old_value_eur or 0} | {item.new_value_eur or 0} | {item.value_delta_eur or 0} | "
                f"{item.cause} | {item.cause_explanation} | "
                f"{'erforderlich' if item.review_required else 'nicht erforderlich'} |"
            )
        lines.extend(
            [
                "",
                "## Ursachenklassifikation",
                "",
                "JSON:",
                json.dumps(report.cause_counts, ensure_ascii=False, sort_keys=True),
                "",
                "## Quellen- und Dublettenpruefung",
                "",
                f"- Status: {report.source_reconciliation.status}",
                f"- Primaerquellen: {', '.join(report.source_reconciliation.primary_sources)}",
                f"- Aggregator-/Spiegelquellen: {', '.join(report.source_reconciliation.aggregator_sources)}",
                f"- Gematchte Spiegelgruppen: {report.source_reconciliation.matched_mirror_group_count}",
                f"- Gematchte primaere Transfergruppen: {report.source_reconciliation.matched_primary_transfer_group_count}",
                f"- Nicht gematchte Aggregator-Ereignisse: {report.source_reconciliation.unmatched_aggregator_event_count}",
                f"- Davon Steuerzeilen: {report.source_reconciliation.unmatched_aggregator_tax_line_count}",
                f"- Davon Derivatezeilen: {report.source_reconciliation.unmatched_aggregator_derivative_count}",
                "",
                "### Erkannte Spiegelgruppen",
                "",
                "| Gruppe | Asset | Abgleichbasis | Ereignisse |",
                "|---|---|---|---|",
            ]
        )
        for match in report.source_reconciliation.mirror_matches:
            event_summary = "; ".join(
                f"{event.source}:{event.event_id} {event.quantity} "
                f"({event.import_filename or '-'})"
                for event in match.events
            )
            lines.append(
                f"| {match.logical_event_group_id} | {match.asset} | {match.match_basis} | {event_summary} |"
            )
        lines.extend(
            [
                "",
                "### Quellenpruefung offen",
            ]
        )
        if report.source_reconciliation.open_review_points:
            lines.extend(
                f"- {item}" for item in report.source_reconciliation.open_review_points
            )
        else:
            lines.append("- Keine offenen Quellenpruefungen.")
        lines.extend(
            [
                "",
                "## Cash- und Handelsvolumen-Trennung",
                "",
                f"- Handels-/Swapvolumen: {report.cash_separation.trade_swap_volume_eur} EUR; nicht Einkommen und nicht ausgezahltes Geld.",
                f"- Tatsaechliche EUR-Einzahlungen: {report.cash_separation.actual_eur_deposits_eur} EUR ({report.cash_separation.actual_eur_deposits_status}).",
                f"- Tatsaechliche EUR-Auszahlungen: {report.cash_separation.actual_eur_withdrawals_eur} EUR ({report.cash_separation.actual_eur_withdrawals_status}).",
                f"- Steuerpflichtiger Gewinn/Verlust: {report.cash_separation.taxable_gain_loss_eur} EUR.",
                f"- Steuerfreie Gewinne/Verluste: {report.cash_separation.tax_free_gain_loss_eur} EUR.",
                f"- Interne Transfers: {report.cash_separation.internal_transfers_eur} EUR ({report.cash_separation.internal_transfers_status}).",
                "",
                "## Verwendete API-Nachweise",
                "",
                "| Endpoint | Payload-SHA256 | Abfrage UTC | Verfuegbar |",
                "|---|---|---|---|",
            ]
        )
        for item in report.endpoints:
            lines.append(
                f"| {item.endpoint} | {item.payload_sha256 or '-'} | "
                f"{item.query_timestamp_utc} | {item.available} |"
            )
        lines.extend(["", "## Offene Review-Punkte", ""])
        if report.open_review_points:
            lines.extend(f"- {item}" for item in report.open_review_points)
        else:
            lines.append("- Keine offenen Punkte.")
        lines.extend(
            [
                "",
                "## Menschliche Freigaben",
                "",
                "Jede wesentliche Aenderung benoetigt eine menschliche Freigabe. Dieser Bericht erzeugt keine Freigabe und keine steuerliche Korrekturentscheidung.",
                "",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _metadata_markdown(metadata: TaxAuditSnapshotMetadata) -> list[str]:
        return [
            f"- Snapshot-ID: {metadata.snapshot_id}",
            f"- Paketname: {metadata.package_name}",
            f"- Paket-SHA256: {metadata.package_sha256}",
            f"- Manifest-SHA256: {metadata.manifest_sha256}",
            f"- Erzeugt UTC: {metadata.package_generated_at_utc}",
            f"- Erzeugt Europe/Berlin: {metadata.package_generated_at_europe_berlin}",
            f"- Softwareversion: {metadata.software_version}",
            f"- Methodenversion: {metadata.method_version}",
            f"- Datenbankfingerprint: {metadata.database_fingerprint_sha256}",
            f"- Fuer Steuererklaerung bestaetigt: {metadata.filing_usage_confirmed}",
            f"- Integritaet: {metadata.integrity_status}",
        ]
