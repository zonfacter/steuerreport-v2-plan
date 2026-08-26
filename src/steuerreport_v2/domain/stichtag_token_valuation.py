from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import io

from steuerreport_v2.contracts.jupiter import JupiterTokenMetadataCacheItem
from steuerreport_v2.contracts.review import ReviewDecision, ReviewDecisionCreate
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.jupiter import JupiterTokenService


@dataclass(frozen=True)
class StichtagTokenAssessment:
    asset: str
    mint: str | None
    risk_status: str | None
    token_verified: bool | None
    review_required: bool
    accepted_decision: ReviewDecision | None


class StichtagTokenValuationService:
    DECISION_TYPE = "stichtag_token_valuation"
    TREATMENT = "include_with_documented_same_day_price"
    REVIEW_RISK_STATUSES = {"spam_review", "review"}

    def __init__(self, store: DuckDbStore) -> None:
        self.store = store
        self._metadata = JupiterTokenService(store).cached_metadata_by_asset()
        self._decisions = store.list_review_decisions()

    def assessment(self, asset: str, as_of_date: date) -> StichtagTokenAssessment:
        normalized_asset = self._normalize_asset(asset)
        metadata = self._metadata.get(normalized_asset)
        risk_status = metadata.risk_status if metadata is not None else None
        review_required = bool(
            metadata is not None
            and metadata.is_verified is not True
            and risk_status in self.REVIEW_RISK_STATUSES
        )
        decision = self._accepted_decision(
            asset=normalized_asset,
            as_of_date=as_of_date,
            metadata=metadata,
        )
        return StichtagTokenAssessment(
            asset=normalized_asset,
            mint=metadata.mint if metadata is not None else None,
            risk_status=risk_status,
            token_verified=metadata.is_verified if metadata is not None else None,
            review_required=review_required,
            accepted_decision=decision,
        )

    def accept_same_day_valuation(
        self,
        *,
        asset: str,
        as_of_date: date,
        price_eur: Decimal,
        price_source: str,
        evidence_ref: str,
        rationale: str | None = None,
        actor: str = "user",
    ) -> tuple[ReviewDecision, bool]:
        assessment = self.assessment(asset, as_of_date)
        if not assessment.review_required or not assessment.mint:
            raise ValueError("token_review_not_required")
        if assessment.accepted_decision is not None:
            return assessment.accepted_decision, True
        if price_eur <= 0:
            raise ValueError("same_day_price_must_be_positive")
        source = str(price_source or "").strip()
        if not source:
            raise ValueError("same_day_price_source_required")
        scope = self.scope(
            asset=assessment.asset,
            mint=assessment.mint,
            as_of_date=as_of_date,
        )
        decision = self.store.add_review_decision(
            ReviewDecisionCreate(
                decision_type=self.DECISION_TYPE,
                scope=scope,
                title=(
                    f"Stichtagsbewertung {assessment.asset} "
                    f"am {as_of_date.isoformat()} annehmen"
                ),
                rationale=(
                    str(rationale or "").strip()
                    or (
                        "Der exakte Token-Mint bleibt als Risikofall dokumentiert. "
                        "Fuer diesen Stichtag wird ausschliesslich der belegte "
                        "Same-Day-Preis in die Vermoegensbewertung einbezogen. "
                        "Bestand, Ledger, FIFO und Steuerzeilen werden nicht veraendert."
                    )
                ),
                evidence_ref=evidence_ref,
                actor=str(actor or "user").strip() or "user",
                source="api:/api/v1/prices/as-of-gate/token-review-decisions",
                affected_ids=[
                    f"asset:{assessment.asset}",
                    f"token_mint:{assessment.mint}",
                    f"as_of_date:{as_of_date.isoformat()}",
                ],
                payload={
                    "treatment": self.TREATMENT,
                    "asset": assessment.asset,
                    "token_mint": assessment.mint,
                    "token_risk_status": assessment.risk_status,
                    "token_verified": assessment.token_verified,
                    "as_of_date": as_of_date.isoformat(),
                    "price_eur": str(price_eur),
                    "price_source": source,
                    "valuation_effect": (
                        "include_existing_position_with_same_day_price"
                    ),
                    "import_effect": "none",
                    "ledger_effect": "none",
                    "fifo_effect": "none",
                    "tax_line_effect": "none",
                },
            )
        )
        self._decisions.insert(0, decision)
        return decision, False

    def decisions_csv(self, as_of_dates: set[date] | None = None) -> str:
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "decision_id",
                "as_of_date",
                "asset",
                "token_mint",
                "token_risk_status",
                "treatment",
                "price_eur",
                "price_source",
                "evidence_ref",
                "created_at",
            ],
        )
        writer.writeheader()
        for decision in self._decisions:
            if decision.decision_type != self.DECISION_TYPE:
                continue
            payload = decision.payload
            raw_date = str(payload.get("as_of_date") or "")
            try:
                decision_date = date.fromisoformat(raw_date)
            except ValueError:
                continue
            if as_of_dates is not None and decision_date not in as_of_dates:
                continue
            writer.writerow(
                {
                    "decision_id": decision.decision_id,
                    "as_of_date": raw_date,
                    "asset": payload.get("asset"),
                    "token_mint": payload.get("token_mint"),
                    "token_risk_status": payload.get("token_risk_status"),
                    "treatment": payload.get("treatment"),
                    "price_eur": payload.get("price_eur"),
                    "price_source": payload.get("price_source"),
                    "evidence_ref": decision.evidence_ref,
                    "created_at": decision.created_at.isoformat(),
                }
            )
        return output.getvalue()

    def _accepted_decision(
        self,
        *,
        asset: str,
        as_of_date: date,
        metadata: JupiterTokenMetadataCacheItem | None,
    ) -> ReviewDecision | None:
        if metadata is None:
            return None
        expected_scope = self.scope(
            asset=asset,
            mint=metadata.mint,
            as_of_date=as_of_date,
        )
        for decision in self._decisions:
            if (
                decision.decision_type != self.DECISION_TYPE
                or decision.scope != expected_scope
            ):
                continue
            if decision.payload.get("treatment") != self.TREATMENT:
                continue
            return decision
        return None

    @staticmethod
    def scope(*, asset: str, mint: str, as_of_date: date) -> str:
        return (
            f"stichtag_token_valuation:date:{as_of_date.isoformat()}:"
            f"asset:{StichtagTokenValuationService._normalize_asset(asset)}:"
            f"mint:{mint}"
        )

    @staticmethod
    def _normalize_asset(asset: str) -> str:
        return str(asset or "").strip().lstrip("$").upper()
