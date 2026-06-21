from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from steuerreport_v2.contracts.events import CanonicalEvent
from steuerreport_v2.contracts.transfers import TransferCandidate, TransferCandidateReport
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.account_aliases import (
    build_account_alias_map_for_store,
    canonical_account_label,
)

TRANSFER_TIME_WINDOWS = (
    (timedelta(hours=6), 35, "Zeitfenster <= 6h"),
    (timedelta(days=1), 25, "Zeitfenster <= 24h"),
    (timedelta(days=7), 15, "Zeitfenster <= 7d"),
    (timedelta(days=30), 5, "Zeitfenster <= 30d"),
)


class TransferCandidateService:
    def __init__(self, store: DuckDbStore) -> None:
        self.store = store

    def candidates(
        self,
        asset: str | None = None,
        limit: int = 200,
    ) -> TransferCandidateReport:
        events = [
            event
            for event in self.store.list_canonical_events()
            if event.event_type == "transfer" and event.quantity != 0
        ]
        account_aliases = build_account_alias_map_for_store(self.store)
        by_asset: dict[str, list[CanonicalEvent]] = defaultdict(list)
        for event in events:
            if asset is not None and event.asset.upper() != asset.upper():
                continue
            by_asset[event.asset.upper()].append(event)

        candidates: list[TransferCandidate] = []
        for asset_key, asset_events in by_asset.items():
            outgoing = [event for event in asset_events if event.quantity < 0]
            incoming = [event for event in asset_events if event.quantity > 0]
            for out_event in outgoing:
                for in_event in incoming:
                    candidate = self._candidate(asset_key, out_event, in_event, account_aliases)
                    if candidate is not None:
                        candidates.append(candidate)

        candidates.sort(
            key=lambda item: (
                item.score,
                -abs(item.time_delta_seconds),
                item.asset,
                item.out_time,
            ),
            reverse=True,
        )
        limited = candidates[: max(limit, 0)]
        return TransferCandidateReport(
            candidates_count=len(candidates),
            assets=sorted({candidate.asset for candidate in candidates}),
            candidates=limited,
        )

    def _candidate(
        self,
        asset: str,
        out_event: CanonicalEvent,
        in_event: CanonicalEvent,
        account_aliases: dict[str, str],
    ) -> TransferCandidate | None:
        amount_out = abs(out_event.quantity)
        amount_in = abs(in_event.quantity)
        amount_delta = amount_out - amount_in
        tolerance = self._amount_tolerance(amount_out, amount_in)
        if abs(amount_delta) > tolerance:
            return None

        score = 0
        reasons: list[str] = []
        warnings: list[str] = []

        if amount_delta == 0:
            score += 35
            reasons.append("Menge exakt gleich")
        else:
            score += 25
            reasons.append(f"Menge innerhalb Toleranz {tolerance}")

        time_delta = in_event.event_time - out_event.event_time
        abs_delta = abs(time_delta)
        if time_delta.total_seconds() >= 0:
            reasons.append("Zeitreihenfolge plausibel")
            for window, points, label in TRANSFER_TIME_WINDOWS:
                if abs_delta <= window:
                    score += points
                    reasons.append(label)
                    break
        else:
            score -= 25
            warnings.append("Eingang liegt vor Ausgang")
            for window, points, label in TRANSFER_TIME_WINDOWS:
                if abs_delta <= window:
                    score += max(points - 10, 0)
                    reasons.append(label + " rueckwaerts")
                    break

        out_account = canonical_account_label(out_event.account, account_aliases)
        in_account = canonical_account_label(in_event.account, account_aliases)

        if out_account and in_account and out_account != in_account:
            score += 10
            reasons.append("Unterschiedliche Konten")
        elif out_account and in_account and out_account == in_account:
            score -= 10
            warnings.append("Gleiches Konto auf beiden Seiten")

        if out_event.source != in_event.source:
            score += 5
            reasons.append("Unterschiedliche Quellen")

        out_tx = self._clean_tx_id(out_event.tx_id)
        in_tx = self._clean_tx_id(in_event.tx_id)
        if out_tx and in_tx and out_tx == in_tx:
            score += 35
            reasons.append("TX-ID stimmt ueberein")
        elif out_tx and in_tx:
            score -= 20
            warnings.append("TX-IDs unterscheiden sich")
        else:
            warnings.append("TX-ID nicht auf beiden Seiten vorhanden")

        if self._same_event_family(out_event, in_event, account_aliases):
            score -= 15
            warnings.append("Quelle, Konto und Zeit sind sehr aehnlich")

        status = self._status(score=score, warnings=warnings)
        return TransferCandidate(
            asset=asset,
            score=score,
            status=status,
            amount_out=amount_out,
            amount_in=amount_in,
            amount_delta=amount_delta,
            out_event_id=out_event.event_id,
            in_event_id=in_event.event_id,
            out_time=out_event.event_time,
            in_time=in_event.event_time,
            time_delta_seconds=int(time_delta.total_seconds()),
            out_account=out_account,
            in_account=in_account,
            out_source=out_event.source,
            in_source=in_event.source,
            out_tx_id=out_event.tx_id,
            in_tx_id=in_event.tx_id,
            reasons=reasons,
            warnings=warnings,
        )

    def _amount_tolerance(self, amount_out: Decimal, amount_in: Decimal) -> Decimal:
        base = max(amount_out, amount_in)
        relative = base * Decimal("0.000001")
        return max(relative, Decimal("0.00000001"))

    def _clean_tx_id(self, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip().lower()
        return stripped or None

    def _same_event_family(
        self,
        out_event: CanonicalEvent,
        in_event: CanonicalEvent,
        account_aliases: dict[str, str],
    ) -> bool:
        return (
            out_event.source == in_event.source
            and canonical_account_label(out_event.account, account_aliases)
            == canonical_account_label(in_event.account, account_aliases)
            and abs((in_event.event_time - out_event.event_time).total_seconds()) < 2
        )

    def _status(self, score: int, warnings: list[str]) -> str:
        if score >= 85 and "Eingang liegt vor Ausgang" not in warnings:
            return "strong_candidate"
        if score >= 60:
            return "review_candidate"
        return "weak_candidate"
