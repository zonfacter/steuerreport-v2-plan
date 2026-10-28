"""Beleggebundene Inventarumstellung, keine neutrale Wrapping-Vermutung."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
from typing import Callable

from pydantic import ValidationError

from steuerreport_v2.contracts.events import CanonicalEvent
from steuerreport_v2.contracts.token_conversion import TokenConversionConfig, TokenConversionMapping
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.tax_time import as_utc
from steuerreport_v2.private_settings import private_config_path


POLICY = "evidence_bound_token_conversion_v1"


def config_binding() -> str:
    path = private_config_path("token_conversion_mappings.json")
    if not path.exists():
        return hashlib.sha256(b"{}").hexdigest()
    if path.is_symlink():
        raise ValueError("conversion_config_symlink")
    content = path.read_bytes()
    bound = {"config": hashlib.sha256(content).hexdigest(), "evidence": {}}
    try:
        config = TokenConversionConfig.model_validate_json(content)
        for mapping in config.mappings:
            relative = Path(mapping.evidence_ref)
            evidence = path.parent / relative
            safe = (not relative.is_absolute() and ".." not in relative.parts
                    and evidence.resolve().is_relative_to(path.parent.resolve()))
            current = path.parent
            for part in relative.parts:
                current = current / part
                safe = safe and not current.is_symlink()
            bound["evidence"][mapping.mapping_id] = (
                hashlib.sha256(evidence.read_bytes()).hexdigest()
                if safe and evidence.is_file() else "missing_or_unsafe")
    except (ValueError, OSError):
        bound["invalid"] = True
    return hashlib.sha256(json.dumps(bound, sort_keys=True).encode()).hexdigest()


def event_binding(event: CanonicalEvent) -> str:
    row = event.model_dump(mode="python")
    row["event_time"] = as_utc(event.event_time).isoformat()
    with localcontext() as context:
        context.prec = 80
        for key, value in row.items():
            if isinstance(value, Decimal):
                row[key] = str(value.normalize())
    return hashlib.sha256(json.dumps(row, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class ReadyTokenConversion:
    mapping: TokenConversionMapping
    source: CanonicalEvent
    target: CanonicalEvent

    @property
    def factor(self) -> Decimal:
        with localcontext() as context:
            context.prec = 80
            return self.mapping.ratio_numerator / self.mapping.ratio_denominator


class TokenConversionService:
    def __init__(self, store: DuckDbStore, config_path: Path | None = None) -> None:
        self.store = store
        self.config_path = config_path or private_config_path("token_conversion_mappings.json")

    def _evidence_matches(self, mapping: TokenConversionMapping) -> bool:
        # Nur explizit gebundene lokale Belege; keine Netzabfrage durch Vorschau.
        relative = Path(mapping.evidence_ref)
        if relative.is_absolute() or ".." in relative.parts:
            return False
        path = self.config_path.parent / relative
        if not path.resolve().is_relative_to(self.config_path.parent.resolve()):
            return False
        current = self.config_path.parent
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                return False
        try:
            return path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == mapping.evidence_sha256
        except OSError:
            return False

    def report(self, events: list[CanonicalEvent] | None = None) -> dict:
        events = events if events is not None else self.store.list_canonical_events()
        by_id = {event.event_id: event for event in events}
        ready, issues, mapped = [], [], set()
        with self.store.connect() as con:
            raw = dict(con.execute("select raw_object_id,payload_json from raw_objects").fetchall())
        candidates = set()
        for event in events:
            try:
                body = json.loads(raw.get(event.raw_object_id, "{}"))
            except (ValueError, TypeError):
                continue
            if isinstance(body, dict) and body.get("conversion_kind") in {"redenomination", "wrapping"}:
                candidates.add(event.event_id)
        try:
            if self.config_path.is_symlink():
                raise ValueError("conversion_config_symlink")
            config = TokenConversionConfig.model_validate_json(
                self.config_path.read_text() if self.config_path.exists() else "{}")
        except (ValueError, OSError, ValidationError):
            return {"ready": [], "issues": [{"event_id": None, "reason": "conversion_config_invalid"}],
                    "policy": POLICY}
        used = set()
        enabled = [mapping for mapping in config.mappings if mapping.enabled]
        duplicate_ids = {mapping.mapping_id for mapping in enabled
                         if sum(item.mapping_id == mapping.mapping_id for item in enabled) > 1}
        duplicates = {event_id for mapping in enabled for event_id in (mapping.source_event_id, mapping.target_event_id)
                      if sum(event_id in (item.source_event_id, item.target_event_id) for item in enabled) > 1}
        for mapping in config.mappings:
            event_ids = {mapping.source_event_id, mapping.target_event_id}
            mapped |= event_ids
            source, target = by_id.get(mapping.source_event_id), by_id.get(mapping.target_event_id)
            reason = None
            if not mapping.enabled:
                reason = "conversion_not_enabled"
            elif mapping.mapping_id in duplicate_ids or duplicates & event_ids or event_ids & used:
                reason = "conversion_mapping_not_unique"
            elif source is None or target is None:
                reason = "conversion_event_missing"
            elif not self._evidence_matches(mapping):
                reason = "conversion_evidence_missing_or_changed"
            elif (source.event_type != "transfer" or target.event_type != "transfer"
                  or source.quantity >= 0 or target.quantity <= 0 or source.asset == target.asset
                  or as_utc(source.event_time) != as_utc(target.event_time)
                  or source.source != target.source or source.account != target.account
                  or source.wallet != target.wallet or any((source.fee_quantity, target.fee_quantity))):
                reason = "conversion_shape_or_scope_unproven"
            elif (event_binding(source) != mapping.source_event_sha256
                  or event_binding(target) != mapping.target_event_sha256):
                reason = "conversion_event_binding_stale"
            elif (not source.raw_object_id or not target.raw_object_id
                  or source.raw_object_id not in raw or target.raw_object_id not in raw
                  or hashlib.sha256(raw[source.raw_object_id].encode()).hexdigest() != mapping.source_raw_sha256
                  or hashlib.sha256(raw[target.raw_object_id].encode()).hexdigest() != mapping.target_raw_sha256):
                reason = "conversion_raw_binding_stale"
            else:
                with localcontext() as context:
                    context.prec = 80
                    if abs(source.quantity) * mapping.ratio_numerator != target.quantity * mapping.ratio_denominator:
                        reason = "conversion_quantity_ratio_mismatch"
            if reason:
                issues.append({"event_id": mapping.source_event_id, "reason": reason})
            else:
                ready.append(ReadyTokenConversion(mapping, source, target))
                used |= event_ids
        for event_id in sorted(candidates - mapped):
            issues.append({"event_id": event_id, "reason": "conversion_evidence_mapping_required"})
        return {"ready": ready, "issues": issues, "policy": POLICY}


def carry_conversion_lots(lots: deque, conversion: ReadyTokenConversion, create_lot: Callable) -> tuple[list, Decimal]:
    """Verbraucht alte Menge und traegt Datum/Basis fort; keine Steuerzeile."""
    remaining = abs(conversion.source.quantity)
    converted = []
    with localcontext() as context:
        context.prec = 80
        while remaining > 0 and lots:
            lot = lots[0]
            if lot.quantity_total <= 0 or lot.quantity_remaining < 0:
                raise ValueError("conversion_source_lot_invalid")
            used = min(remaining, lot.quantity_remaining)
            if used > 0:
                converted.append(create_lot(lot, used * conversion.factor,
                    lot.cost_basis_eur_total * used / lot.quantity_total))
                lot.quantity_remaining -= used
                remaining -= used
            if lot.quantity_remaining == 0:
                lots.popleft()
    return converted, remaining
