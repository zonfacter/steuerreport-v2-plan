from __future__ import annotations

from steuerreport_v2.private_settings import private_config_path

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from steuerreport_v2.contracts.events import CanonicalEvent
from steuerreport_v2.contracts.service_swap_tax_mapping import (
    ServiceSwapTaxMappingDecisionLayer,
    ServiceSwapTaxMappingRecord,
    ServiceSwapTaxMappingReport,
)
from steuerreport_v2.contracts.tax_wallet_fifo import (
    WalletFifoSolanaServiceSwapEvidenceRecord,
)
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.paths import PROJECT_ROOT


class ServiceSwapTaxMappingService:
    DEFAULT_CONFIG_PATH = private_config_path('solana_service_swap_tax_mappings.json')
    DEFAULT_EVIDENCE_DIR = PROJECT_ROOT / "var/solana_service_swap_evidence"
    LAMPORTS_PER_SOL = Decimal("1000000000")
    VALUATION_METHOD = "received_asset_market_value_at_swap_time"
    DIRECT_COST_TREATMENT = (
        "deduct_from_source_disposal_and_realize_cost_asset_disposal"
    )
    TAX_TREATMENT = "taxable_crypto_to_crypto_swap"

    def __init__(
        self,
        store: DuckDbStore,
        *,
        config_path: Path | None = None,
        evidence_dir: Path | None = None,
    ) -> None:
        self.store = store
        self.config_path = config_path or self.DEFAULT_CONFIG_PATH
        self.evidence_dir = evidence_dir or self.DEFAULT_EVIDENCE_DIR

    def report(
        self,
        *,
        events: list[CanonicalEvent] | None = None,
    ) -> ServiceSwapTaxMappingReport:
        methodology = (
            "Read-only, explizit freigegebene Steuerabbildung fuer technisch belegte "
            "servicevermittelte Krypto-Tausche. Die Konfiguration ist an den "
            "semantischen SHA-256 des On-chain-/CEX-Artefakts und an konkrete "
            "Canonical Events gebunden. Input-Veraeusserung, Output-Anschaffung "
            "und direkt aus der eigenen Wallet bezahlte Kosten werden getrennt "
            "abgebildet; die Service-Route wird nicht als Eigenwallet eingestuft."
        )
        errors: list[str] = []
        records: list[ServiceSwapTaxMappingRecord] = []
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return ServiceSwapTaxMappingReport(
                generated_at=datetime.now(timezone.utc),
                status="not_available",
                config_path=str(self.config_path),
                evidence_dir=str(self.evidence_dir),
                errors=[f"config_read_failed:{exc}"],
                methodology=methodology,
            )
        mappings = payload.get("mappings")
        if int(payload.get("schema_version") or 0) != 1 or not isinstance(
            mappings, list
        ):
            return ServiceSwapTaxMappingReport(
                generated_at=datetime.now(timezone.utc),
                status="invalid_config",
                config_path=str(self.config_path),
                evidence_dir=str(self.evidence_dir),
                errors=["invalid_schema_or_mappings"],
                methodology=methodology,
            )
        event_rows = events if events is not None else self.store.list_canonical_events()
        events_by_id = {event.event_id: event for event in event_rows}
        for raw_mapping in mappings:
            try:
                records.append(
                    self._mapping_record(
                        raw_mapping=raw_mapping,
                        events_by_id=events_by_id,
                    )
                )
            except (KeyError, OSError, TypeError, ValueError) as exc:
                mapping_id = (
                    str(raw_mapping.get("mapping_id") or "unknown")
                    if isinstance(raw_mapping, dict)
                    else "unknown"
                )
                errors.append(f"{mapping_id}:{exc}")
        ready_count = sum(1 for record in records if record.tax_mapping_ready)
        strict_ready = bool(
            records
            and ready_count == len(records)
            and len(records) == len(mappings)
            and not errors
        )
        return ServiceSwapTaxMappingReport(
            generated_at=datetime.now(timezone.utc),
            status="ready" if strict_ready else "review_required",
            strict_ready=strict_ready,
            config_path=str(self.config_path),
            evidence_dir=str(self.evidence_dir),
            mappings_count=len(mappings),
            ready_count=ready_count,
            review_count=len(mappings) - ready_count,
            records=records,
            errors=errors,
            methodology=methodology,
        )

    def ready_mappings(
        self,
        *,
        events: list[CanonicalEvent] | None = None,
    ) -> list[ServiceSwapTaxMappingRecord]:
        return [
            record
            for record in self.report(events=events).records
            if record.tax_mapping_ready
        ]

    def _mapping_record(
        self,
        *,
        raw_mapping: object,
        events_by_id: dict[str, CanonicalEvent],
    ) -> ServiceSwapTaxMappingRecord:
        if not isinstance(raw_mapping, dict):
            raise TypeError("mapping_not_an_object")
        year = int(raw_mapping["year"])
        evidence_path = self.evidence_dir / f"latest_{year}_service_swap_evidence.json"
        evidence_payload = json.loads(evidence_path.read_text(encoding="utf-8"))
        records_payload = evidence_payload.get("records")
        if not isinstance(records_payload, list):
            raise ValueError("evidence_records_not_a_list")
        calculated_sha = hashlib.sha256(
            json.dumps(
                records_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        evidence_sha = str(evidence_payload.get("semantic_sha256") or "")
        configured_sha = str(raw_mapping["evidence_semantic_sha256"])
        source_event_id = str(raw_mapping["source_event_id"])
        evidence_matches = [
            item
            for item in records_payload
            if isinstance(item, dict)
            and str(item.get("source_event_id") or "") == source_event_id
        ]
        if len(evidence_matches) != 1:
            raise ValueError("evidence_record_not_unique")
        evidence = WalletFifoSolanaServiceSwapEvidenceRecord.model_validate(
            evidence_matches[0]
        )
        source_event = events_by_id.get(source_event_id)
        funding_event = events_by_id.get(str(raw_mapping["funding_event_id"]))
        deposit_event = events_by_id.get(str(raw_mapping["deposit_event_id"]))
        mirror_event_ids = [
            str(value) for value in raw_mapping.get("deposit_mirror_event_ids", [])
        ]
        mirror_events = [events_by_id.get(event_id) for event_id in mirror_event_ids]
        mirror_raw_payloads = self._raw_payloads(
            [event for event in mirror_events if event is not None]
        )
        source_asset = str(raw_mapping["source_asset"]).upper()
        acquired_asset = str(raw_mapping["acquired_asset"]).upper()
        direct_cost_asset = str(raw_mapping["direct_cost_asset"]).upper()
        source_quantity = Decimal(str(raw_mapping["source_quantity"]))
        acquired_quantity = Decimal(str(raw_mapping["acquired_quantity"]))
        source_direct_cost = Decimal(
            str(raw_mapping["source_direct_cost_quantity"])
        )
        funding_direct_cost = Decimal(
            str(raw_mapping["funding_direct_cost_quantity"])
        )
        direct_cost = Decimal(str(raw_mapping["direct_cost_quantity"]))
        output_withheld = Decimal(str(raw_mapping["output_withheld_quantity"]))
        swap_event_time = self._parse_datetime(raw_mapping["swap_event_time"])
        expected_source_pool = self._pool_id(source_event) if source_event else ""
        expected_deposit_pool = self._pool_id(deposit_event) if deposit_event else ""
        expected_target_pool = (
            self._pool_id(mirror_events[0])
            if mirror_events and mirror_events[0] is not None
            else expected_deposit_pool
        )
        decision = ServiceSwapTaxMappingDecisionLayer(
            config_enabled=raw_mapping.get("enabled") is True,
            evidence_integrity_valid=bool(
                int(evidence_payload.get("year") or 0) == year
                and int(evidence_payload.get("records_count") or 0)
                == len(records_payload)
                and evidence_sha == calculated_sha
            ),
            evidence_sha_matches=bool(evidence_sha and configured_sha == evidence_sha),
            evidence_route_ready=bool(
                evidence.classification
                == "service_mediated_jupiter_swap_evidence_ready"
                and all(evidence.decision_layer.model_dump().values())
            ),
            source_event_matches=bool(
                source_event
                and source_event.event_type == "transfer"
                and source_event.asset.upper() == source_asset
                and source_event.quantity == -source_quantity
                and str(source_event.tx_id or "") == evidence.source_tx_id
                and evidence.source_event_id == source_event.event_id
            ),
            funding_event_matches=bool(
                funding_event
                and funding_event.event_type == "transfer"
                and funding_event.asset.upper() == direct_cost_asset
                and funding_event.quantity < 0
                and str(funding_event.tx_id or "") == evidence.funding_tx_id
                and evidence.funding_event_id == funding_event.event_id
            ),
            deposit_event_matches=bool(
                deposit_event
                and deposit_event.event_type == "transfer"
                and deposit_event.asset.upper() == acquired_asset
                and deposit_event.quantity == acquired_quantity
                and str(deposit_event.tx_id or "") == evidence.deposit_tx_id
                and evidence.deposit_event_id == deposit_event.event_id
            ),
            deposit_mirrors_reconcile=bool(
                len(mirror_events) == len(mirror_event_ids)
                and len(set(mirror_event_ids)) == len(mirror_event_ids)
                and all(
                    event is not None
                    and deposit_event is not None
                    and event.source.lower() == deposit_event.source.lower()
                    and event.event_type == "transfer"
                    and event.asset.upper() == acquired_asset
                    and event.quantity == acquired_quantity
                    and Decimal(
                        "0"
                    )
                    <= Decimal(
                        str(
                            (
                                self._as_utc(event.event_time)
                                - self._as_utc(deposit_event.event_time)
                            ).total_seconds()
                        )
                    )
                    <= Decimal("600")
                    and self._mirror_payload_matches(
                        mirror_raw_payloads.get(event.raw_object_id or ""),
                        asset=acquired_asset,
                        quantity=acquired_quantity,
                    )
                    for event in mirror_events
                )
            ),
            swap_timestamp_matches=bool(
                swap_event_time == self._as_utc(evidence.swap_event_time)
                and funding_event
                and deposit_event
                and self._as_utc(funding_event.event_time)
                <= swap_event_time
                <= self._as_utc(deposit_event.event_time)
            ),
            asset_quantities_reconcile=bool(
                source_asset == evidence.source_asset.upper()
                and source_quantity == evidence.source_quantity
                and acquired_asset == evidence.deposit_asset.upper()
                and acquired_quantity == evidence.deposit_quantity
                and output_withheld == evidence.output_withheld_quantity
            ),
            direct_costs_reconcile=bool(
                source_direct_cost
                == Decimal(evidence.source_native_outflow_lamports)
                / self.LAMPORTS_PER_SOL
                and funding_direct_cost
                == Decimal(evidence.funding_native_outflow_lamports)
                / self.LAMPORTS_PER_SOL
                and direct_cost == source_direct_cost + funding_direct_cost
                and direct_cost == evidence.direct_wallet_cost_quantity
                and direct_cost_asset == "SOL"
            ),
            pools_explicit=bool(
                str(raw_mapping["source_pool_id"]) == expected_source_pool
                and str(raw_mapping["deposit_evidence_pool_id"])
                == expected_deposit_pool
                and str(raw_mapping["target_pool_id"]) == expected_target_pool
                and expected_source_pool != expected_target_pool
            ),
            tax_treatment_explicit=bool(
                str(raw_mapping["valuation_method"]) == self.VALUATION_METHOD
                and str(raw_mapping["direct_cost_treatment"])
                == self.DIRECT_COST_TREATMENT
                and str(raw_mapping["tax_treatment"]) == self.TAX_TREATMENT
            ),
        )
        tax_mapping_ready = all(decision.model_dump().values())
        return ServiceSwapTaxMappingRecord(
            mapping_id=str(raw_mapping["mapping_id"]),
            year=year,
            status="ready" if tax_mapping_ready else "review_required",
            tax_mapping_ready=tax_mapping_ready,
            evidence_semantic_sha256=configured_sha,
            source_event_id=source_event_id,
            source_event_time=source_event.event_time if source_event else swap_event_time,
            funding_event_id=str(raw_mapping["funding_event_id"]),
            funding_event_time=(
                funding_event.event_time if funding_event else swap_event_time
            ),
            deposit_event_id=str(raw_mapping["deposit_event_id"]),
            deposit_event_time=(
                deposit_event.event_time if deposit_event else swap_event_time
            ),
            deposit_mirror_event_ids=mirror_event_ids,
            swap_tx_id=str(raw_mapping["swap_tx_id"]),
            swap_event_time=swap_event_time,
            source_asset=source_asset,
            source_quantity=source_quantity,
            acquired_asset=acquired_asset,
            acquired_quantity=acquired_quantity,
            source_direct_cost_quantity=source_direct_cost,
            funding_direct_cost_quantity=funding_direct_cost,
            direct_cost_asset=direct_cost_asset,
            direct_cost_quantity=direct_cost,
            output_withheld_quantity=output_withheld,
            source_pool_id=str(raw_mapping["source_pool_id"]),
            deposit_evidence_pool_id=str(raw_mapping["deposit_evidence_pool_id"]),
            target_pool_id=str(raw_mapping["target_pool_id"]),
            valuation_method=str(raw_mapping["valuation_method"]),
            direct_cost_treatment=str(raw_mapping["direct_cost_treatment"]),
            tax_treatment=str(raw_mapping["tax_treatment"]),
            decision_layer=decision,
            evidence_ref=str(evidence_path),
            bmf_reference=str(raw_mapping["bmf_reference"]),
        )

    @staticmethod
    def _pool_id(event: CanonicalEvent | None) -> str:
        if event is None:
            return ""
        value = event.account or event.wallet or event.source
        return f"{event.source}:{value}".replace(" ", "_")

    def _raw_payloads(
        self,
        events: list[CanonicalEvent],
    ) -> dict[str, dict[str, object]]:
        raw_ids = sorted(
            {event.raw_object_id for event in events if event.raw_object_id}
        )
        if not raw_ids:
            return {}
        placeholders = ", ".join("?" for _ in raw_ids)
        with self.store.connect() as con:
            rows = con.execute(
                f"select raw_object_id, payload_json from raw_objects where raw_object_id in ({placeholders})",
                raw_ids,
            ).fetchall()
        result: dict[str, dict[str, object]] = {}
        for raw_object_id, payload_json in rows:
            try:
                payload = json.loads(str(payload_json))
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                result[str(raw_object_id)] = payload
        return result

    @staticmethod
    def _mirror_payload_matches(
        payload: dict[str, object] | None,
        *,
        asset: str,
        quantity: Decimal,
    ) -> bool:
        if payload is None:
            return False
        try:
            change = Decimal(str(payload.get("Change") or payload.get("change")))
        except Exception:
            return False
        return bool(
            str(payload.get("Operation") or payload.get("operation") or "").lower()
            == "deposit"
            and str(payload.get("Coin") or payload.get("coin") or "").upper()
            == asset.upper()
            and change == quantity
        )

    @classmethod
    def _parse_datetime(cls, value: object) -> datetime:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return cls._as_utc(parsed)

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
