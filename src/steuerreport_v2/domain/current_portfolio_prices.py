"""Preiswahl fuer den aktuellen Portfolio-Snapshot, nicht fuer Steuerbewertungen."""

from dataclasses import dataclass
from datetime import datetime

from steuerreport_v2.contracts.portfolio import PortfolioPriceSelectionDiagnostic
from steuerreport_v2.contracts.prices import PricePoint
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.price_policy import SOURCE_WHITESPACE, as_utc


@dataclass(frozen=True)
class CurrentPortfolioPrices:
    selected: dict[str, PricePoint]
    previous: dict[str, PricePoint]
    diagnostics: dict[str, PortfolioPriceSelectionDiagnostic]


def select_current_portfolio_prices(store: DuckDbStore, valuation_at: datetime) -> CurrentPortfolioPrices:
    # The ledger uses UTC timestamps without timezone information.
    cutoff = as_utc(valuation_at).replace(tzinfo=None)
    source = f"lower(trim(source, '{SOURCE_WHITESPACE}'))"
    event_quote = f"starts_with({source}, 'derived:event_quote')"
    with store.connect() as con:
        rows = con.execute(
            f"""
            with candidates as (
                select *, priced_at > ? as future,
                       price_eur <= 0 as nonpositive,
                       {event_quote} as event_quote
                from price_ledger
            ), diagnostics as (
                select asset, count(*) as candidate_count,
                       count(*) filter (where future) as future_count,
                       count(*) filter (where nonpositive) as nonpositive_count,
                       count(*) filter (where event_quote) as event_quote_count
                from candidates group by asset
            ), eligible as (
                select *, row_number() over (
                    partition by asset order by priced_at desc, confidence desc,
                    {source} asc, source asc, price_eur desc, price_id asc
                ) as price_rank
                from candidates where not future and not nonpositive and not event_quote
            )
            select d.asset, d.candidate_count, d.future_count, d.nonpositive_count,
                   d.event_quote_count, e.price_id, e.price_eur, e.priced_at,
                   e.source, e.confidence, e.price_rank
            from diagnostics d left join eligible e
              on d.asset = e.asset and e.price_rank <= 2
            order by d.asset, e.price_rank
            """,
            [cutoff],
        ).fetchall()

    selected: dict[str, PricePoint] = {}
    previous: dict[str, PricePoint] = {}
    diagnostics: dict[str, PortfolioPriceSelectionDiagnostic] = {}
    for row in rows:
        (asset, count, future, nonpositive, event_quote_count, price_id, price,
         priced_at, source_name, confidence, rank) = row
        diagnostics[asset] = PortfolioPriceSelectionDiagnostic(
            asset=asset, candidate_count=count, future_count=future,
            nonpositive_count=nonpositive, event_quote_count=event_quote_count,
            eligible_price_found=price_id is not None,
        )
        if price_id is not None:
            point = PricePoint(
                price_id=price_id, asset=asset, price_eur=price,
                priced_at=priced_at,
                source=source_name, confidence=confidence,
            )
            (selected if rank == 1 else previous)[asset] = point
    return CurrentPortfolioPrices(selected=selected, previous=previous, diagnostics=diagnostics)
