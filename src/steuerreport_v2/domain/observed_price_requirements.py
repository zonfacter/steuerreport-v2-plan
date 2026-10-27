"""Lesender all_observed-Plan; keine steuerliche Bedarfs- oder Einkommensaussage."""
from __future__ import annotations

from datetime import datetime, timezone
import re

from steuerreport_v2.contracts.historical_prices import HistoricalPriceQuery
from steuerreport_v2.db.duckdb_store import DuckDbStore
from steuerreport_v2.domain.price_lookup import fiat_price_point
from steuerreport_v2.domain.tax_time import as_utc, event_reporting_year_sql


SOL_MINT = "So11111111111111111111111111111111111111112"
_MINT = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")

_OBSERVED_SQL = f"""
    with observed as (
        select e.event_id, e.event_time, e.event_type, e.source,
               upper(tokens.asset) as asset,
               {event_reporting_year_sql('e', 'r')} as event_year,
               case when tokens.role = 'asset'
                    then json_extract_string(r.payload_json, '$.mint') end as mint,
               case when tokens.role = 'asset'
                    then json_type(r.payload_json, '$.mint') end as mint_type
        from canonical_events e
        left join (
            select raw_object_id, try_cast(payload_json as json) as payload_json
            from raw_objects
        ) r on r.raw_object_id = e.raw_object_id
        cross join lateral (values
            (e.asset, e.quantity, 'asset'),
            (e.quote_asset, e.quote_quantity, 'quote_asset'),
            (e.fee_asset, e.fee_quantity, 'fee_asset')
        ) tokens(asset, quantity, role)
        where tokens.asset is not null and trim(tokens.asset) <> ''
          and tokens.quantity is not null and tokens.quantity <> 0
    ), identities as (
        select asset,
               list_sort(list(distinct mint) filter (where mint is not null)) as mints,
               bool_or(mint_type is not null and mint_type not in ('VARCHAR', 'NULL'))
                   as invalid_mint_type,
               bool_or(contains(lower(source), 'solana') or starts_with(asset, 'SOLANA_'))
                   as solana_observed
        from observed group by asset
    ), global_days as (
        select asset, cast(event_time as date) as price_date,
               min(event_time) as first_event_at
        from observed group by asset, cast(event_time as date)
    ), selected as (
        select * from observed
        where (?::integer is null or event_year = ?::integer)
          and (len(?::varchar[]) = 0 or list_contains(?::varchar[], asset))
    ), yearly as (
        select asset, cast(event_time as date) as price_date, event_year,
               count(distinct event_id) as event_count,
               list_sort(list(distinct event_type)) as event_types
        from selected group by asset, cast(event_time as date), event_year
    )
    select y.asset, y.price_date, y.event_year, y.event_count, y.event_types,
           g.first_event_at, i.mints, i.invalid_mint_type, i.solana_observed,
           p.price_eur, p.priced_at, p.source
    from yearly y
    join global_days g using (asset, price_date)
    join identities i using (asset)
    left join lateral (
        select price_eur, priced_at, source
        from price_ledger p
        where upper(p.asset) = y.asset and p.price_eur > 0
          and p.priced_at >= g.price_date and p.priced_at <= g.first_event_at
        order by starts_with(lower(trim(p.source)), 'derived:') asc,
                 p.priced_at desc, p.confidence desc, p.source desc,
                 p.price_eur desc, p.price_id desc
        limit 1
    ) p on true
    order by y.price_date, y.asset, y.event_year
"""


def _identity_and_provider(asset, mints, invalid_type, solana_observed, provider, mappings):
    """Original-Mints sind case-sensitive; normalisierte Aliase sind kein Beleg."""
    mint = mints[0] if len(mints) == 1 else None
    if asset == "SOL" and not mints:
        mint = SOL_MINT
    if len(mints) > 1:
        return mint, None, "asset_mint_conflict"
    if invalid_type or any(_MINT.fullmatch(value) is None for value in mints):
        return mint, None, "solana_mint_invalid"
    if asset == "SOL" and mint != SOL_MINT:
        return mint, None, "solana_mint_identity_mismatch"
    if solana_observed and mint is None:
        return None, None, "solana_mint_missing"

    mapping = mappings.get(asset, {})
    exact_mapping = False
    if mint:
        # HistoricalPriceService liefert auch grossgeschriebene store_keys.
        for key in (mint, "solana:" + mint, mint.upper(), "SOLANA:" + mint.upper()):
            if key in mappings:
                if mapping.get("origin") == "operator" and mappings[key].get("origin") == "bundled":
                    continue
                mapping = mappings[key]
                exact_mapping = key in (mint, "solana:" + mint) or mapping.get("solana_mint") == mint
                break
    reference = "solana:" + mint if mint else None
    configured = mapping.get("defillama_id")
    if reference and ((configured and configured != reference) or (mapping.get("solana_mint") and mapping["solana_mint"] != mint)):
        return mint, None, "price_mapping_mint_mismatch"
    coingecko = mapping.get("coingecko_id")
    if provider == "defillama":
        identifier = reference or configured or ("coingecko:" + coingecko if coingecko else None)
    else:
        # Ein Symbol allein bindet eine CoinGecko-ID nicht an den Original-Mint.
        proven = not mint or asset == "SOL" or exact_mapping or mapping.get("solana_mint") == mint or configured == reference
        identifier = coingecko if proven else None
    return mint, identifier, None


def observed_requirements(
    store: DuckDbStore,
    query: HistoricalPriceQuery,
    mappings: dict,
    risks: dict,
) -> list[dict]:
    """Eine Zeile je beobachtetem Asset/UTC-Tag, einschliesslich Transfers.

    Baustein fuer den geplanten Query-Scope ``all_observed``; der bisherige
    ``tax_required``-Pfad und der Query-Vertrag bleiben unveraendert. Erwartet
    einen vorbereiteten Store; fuehrt selbst nur SELECTs aus, ohne Abruf oder
    Mapping-/Originalwrites. Jahre folgen der bestehenden Berichtszeitregel
    (Europe/Berlin, Helium-Periodenaggregate behalten ihr Quelljahr).

    event_count ist je Zeile distinct ueber alle Rollen. event_types, years und
    event_year_counts (String-Jahresschluessel) beziehen sich auf den Filter;
    first_event_at und mints dagegen auf alle Jahre vor dem Filter. Datum und
    Zeitstempel sind ISO-Strings, price_eur ist ein Decimal-String oder None.
    planned/blocked/covered ist keine steuerliche Freigabe.
    """
    with store.connect() as con:
        rows = con.execute(
            _OBSERVED_SQL, [query.year, query.year, query.assets, query.assets]
        ).fetchall()
        spam = con.execute(
            """select mint, symbol from jupiter_token_metadata_cache
               where risk_status = 'spam_review'"""
        ).fetchall()

    spam_mints = {mint for mint, _ in spam}
    spam_symbols = {symbol.upper() for _, symbol in spam if symbol}
    risk_keys = {key.upper() for key, value in risks.items() if value == "spam_review"}
    combined = {}
    today = datetime.now(timezone.utc).date()
    for (asset, day, year, count, event_types, first, raw_mints, invalid_type,
         solana_observed, price_eur, priced_at, source) in rows:
        key = (day, asset)
        if key in combined:
            row = combined[key]
            row["event_count"] += count
            row["event_types"] = sorted(set(row["event_types"]) | set(event_types))
            row["years"].append(year)
            row["event_year_counts"][str(year)] = count
            continue

        mints = list(raw_mints or [])
        mint, identifier, reason = _identity_and_provider(
            asset, mints, invalid_type, solana_observed, query.provider, mappings
        ) if asset != "EUR" else (None, None, None)
        provenance_mints = set(mints) | ({mint} if mint else set())
        if (asset in risk_keys or asset in spam_symbols
                or provenance_mints & spam_mints
                or any(value.upper() in risk_keys for value in provenance_mints)):
            reason = "token_risk_spam_review"

        first = as_utc(first)
        fiat = fiat_price_point(asset, first)
        row = {
            "asset": asset, "price_date": day.isoformat(),
            "event_count": count, "event_types": list(event_types), "years": [year],
            "event_year_counts": {str(year): count},
            "first_event_at": first.isoformat(), "mint": mint, "mints": mints,
            "identity_basis": "original_mint" if mints else "native_sol_reference" if asset == "SOL" else "configured_mapping" if identifier else None,
            "provider_id": identifier, "status": "blocked" if reason else "planned",
            "reason": reason, "price_eur": None, "priced_at": None, "source": None,
        }
        if reason is None:
            if fiat is not None or price_eur is not None:
                row.update(
                    status="covered",
                    price_eur=str(fiat.price_eur if fiat else price_eur),
                    priced_at=(fiat.priced_at if fiat else as_utc(priced_at)).isoformat(),
                    source=fiat.source if fiat else source,
                )
            elif not identifier or day >= today:
                row.update(status="blocked", reason="asset_not_configured" if not identifier else "future_date")
        combined[key] = row
    return sorted(combined.values(), key=lambda row: (
        row["status"] != "planned", row["price_date"], row["asset"]
    ))
