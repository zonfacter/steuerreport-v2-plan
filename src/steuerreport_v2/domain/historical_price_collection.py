"""Begrenzte Preisabschnitte ohne produktive Daten- oder Klassifikationsaenderung."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, localcontext
import hashlib
import json

from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.domain.request_limits import RequestLimitError
from steuerreport_v2.domain.historical_fx import select_fx_reference
from steuerreport_v2.importers.source_history_importer import canonical_json

UTC = timezone.utc
POINTS_PER_BATCH = 25
WSOL_ID = "solana:So11111111111111111111111111111111111111112"
SEARCH_FAILURES = {"historical_price_quote_missing", "historical_price_timestamp_mismatch"}


def quote_target(row):
    midnight = datetime.combine(date.fromisoformat(row["price_date"]), time(), UTC)
    first = datetime.fromisoformat(row["first_event_at"])
    return max(midnight, first - timedelta(minutes=30))


def nearby_targets(row):
    midnight = int(datetime.combine(date.fromisoformat(row["price_date"]), time(), UTC).timestamp())
    first = int(datetime.fromisoformat(row["first_event_at"]).timestamp())
    target = int(quote_target(row).timestamp())
    return sorted({max(midnight, min(first - 1, target + offset)) for offset in (-1800, 900, 1800)})


def fallback_candidates(row):
    result = [(row["provider_id"], "nearby")]
    native = (row.get("identity_basis") == "native_sol_reference" and not row.get("mints"))
    native_fee = (row.get("sources") == ["solana_rpc"] and row.get("event_types") == ["fee"]
                  and set(row.get("mints", [])) <= {WSOL_ID.split(":", 1)[1]})
    if row["asset"] == "SOL" and (native or native_fee) and row["provider_id"] in {WSOL_ID, "coingecko:wrapped-solana"}:
        result.append(("coingecko:solana", "native_sol"))
    return result


def historical_quote(payload, row, positive, fail):
    coin = payload.get("coins", {}).get(row["provider_id"], {})
    if not isinstance(coin, dict) or not isinstance(coin.get("prices"), list):
        fail("historical_price_quote_missing")
    target = int(quote_target(row).timestamp())
    first = datetime.fromisoformat(row["first_event_at"])
    candidates = []
    for item in coin["prices"]:
        if not isinstance(item, dict) or type(item.get("timestamp")) is not int:
            continue
        instant = datetime.fromtimestamp(item["timestamp"], UTC)
        if instant.date().isoformat() != row["price_date"] or instant > first or abs(item["timestamp"] - target) > 3600:
            continue
        value = positive(item.get("price"))
        confidence = item.get("confidence")
        if confidence is not None and not Decimal("0.95") <= positive(confidence) <= 1:
            continue
        candidates.append((abs(item["timestamp"] - target), -item["timestamp"], value))
    if not candidates:
        fail("historical_price_timestamp_mismatch")
    candidates.sort()
    selected = candidates[0]
    if any(item[1] == selected[1] and item[2] != selected[2] for item in candidates):
        fail("historical_price_quote_conflict")
    return selected[2], datetime.fromtimestamp(-selected[1], UTC)


def historical_fx(payload, day, positive, fail):
    reference = select_fx_reference(payload, day)
    if reference is None:
        fail("historical_price_fx_date_invalid")
    return positive(reference.rate_eur_per_usd), reference.reference_date.isoformat()


def mark_open(row, error):
    code = str(error)
    row.update(status="open", reason=code if code.startswith("historical_price_") else "historical_price_provider_unavailable")


def collect_section(service, query, rows, previous, progress, positive, fail, *, client_factory, scope_factory):
    """Alle Pending-Zeilen beachten, nie nur die sichtbare Listenseite."""
    evidence = list((previous or {}).get("evidence", []))
    prices = [PricePointCreate.model_validate(item) for item in (previous or {}).get("prices", [])]
    fx_series = dict((previous or {}).get("fx_series", {}))
    fx_errors = {}
    pending = [row for row in rows if row["status"] == "pending"]

    def finish(row, eur, instant, fx_day, linked, fx_sha=None, resolved_provider_id=None, search="primary"):
        hashes = list(dict.fromkeys([*row.get("evidence_sha256", []), *(item["sha256"] for item in linked), *([fx_sha] if fx_sha else [])]))
        identity = hashlib.sha256(canonical_json(hashes).encode()).hexdigest()
        provider_id = resolved_provider_id or row["provider_id"]
        source = f"historical:v2:{query.provider}:{provider_id}:day:{row['price_date']}:evidence:{identity}"
        prices.append(PricePointCreate(asset=row["asset"], price_eur=eur, priced_at=instant, source=source, confidence=Decimal("0.95")))
        row.update(status="fetched", reason=None, price_eur=str(eur), priced_at=instant.isoformat(), fx_date=fx_day,
                   source=source, evidence_sha256=hashes, resolved_provider_id=provider_id, resolved_search=search, lookup_stage="complete")

    with scope_factory(max_requests=query.max_requests) as scope, client_factory(timeout=20) as client:
        def checkpoint(phase):
            progress({"phase": phase, "rows_processed": sum(row["status"] != "pending" for row in rows),
                      "total_rows": len(rows), "requests_started": scope.budget.requests_started})

        def request(provider, url, params):
            linked = []
            try:
                return service._request(client, provider, url, params, linked), linked
            finally:
                evidence.extend(linked)

        def fx_for(row):
            day = date.fromisoformat(row["price_date"])
            key = str(day.year)
            if key in fx_errors:
                raise fx_errors[key]
            if key not in fx_series:
                days = [date.fromisoformat(item["price_date"]) for item in rows if item["price_date"].startswith(key) and item["status"] in {"pending", "fetched"}]
                try:
                    payload, linked = request("fx", "https://api.frankfurter.dev/v2/providers/ecb/rates",
                                              {"base": "USD", "quotes": "EUR", "from": (min(days) - timedelta(days=7)).isoformat(), "to": max(days).isoformat()})
                    if not isinstance(payload, list) or not payload:
                        fail("historical_price_fx_date_invalid")
                except RequestLimitError:
                    raise
                except Exception as error:
                    fx_errors[key] = error
                    raise
                fx_series[key] = linked[-1]
            entry = fx_series[key]
            content = service._path("evidence", entry["sha256"] + ".body").read_bytes()
            payload = json.loads(content, parse_float=Decimal)
            rate, fx_day = historical_fx(payload, day, positive, fail)
            return rate, fx_day, entry["sha256"]

        def resolve(row, payload, provider_id, search, linked):
            attempt = {"provider_id": provider_id, "search": search, "evidence_sha256": [entry["sha256"] for entry in linked]}
            row.setdefault("lookup_attempts", []).append(attempt)
            row["evidence_sha256"] = list(dict.fromkeys([*row.get("evidence_sha256", []), *attempt["evidence_sha256"]]))
            try:
                usd, instant = historical_quote(payload, {**row, "provider_id": provider_id}, positive, fail)
                rate, fx_day, fx_sha = row["_fx"]
                with localcontext() as arithmetic:
                    arithmetic.prec = 60
                    eur = positive((usd * rate).quantize(Decimal("0.000000000000000001")))
                attempt.update(status="fetched", reason=None)
                finish(row, eur, instant, fx_day, linked, fx_sha, provider_id, search)
                return True
            except Exception as error:
                mark_open(row, error)
                attempt.update(status="open", reason=row["reason"])
                return False

        def batch_request(candidates):
            coins = defaultdict(set)
            for row, provider_id, search in candidates:
                coins[provider_id].update(nearby_targets(row) if search != "primary" else [int(quote_target(row).timestamp())])
                if search == "native_sol":
                    coins[provider_id].add(int(quote_target(row).timestamp()))
            return request("defillama", "https://coins.llama.fi/batchHistorical",
                           {"coins": canonical_json({key: sorted(values) for key, values in sorted(coins.items())}), "searchWidth": "1h"})

        if query.provider == "coingecko":
            for row in pending:
                if scope.budget.requests_started >= query.max_requests:
                    break
                linked = []
                try:
                    eur, instant, fx_day = service._quote(client, row, query, linked, {})
                    finish(row, eur, instant, fx_day, linked)
                except RequestLimitError:
                    break
                except Exception as error:
                    mark_open(row, error)
                finally:
                    evidence.extend(linked)
                    row["evidence_sha256"] = list(dict.fromkeys([*row.get("evidence_sha256", []), *(item["sha256"] for item in linked)]))
                    checkpoint("Kurse abrufen")
        else:
            for offset in range(0, len(pending), POINTS_PER_BATCH):
                batch = pending[offset:offset + POINTS_PER_BATCH]
                ready = []
                for row in batch:
                    before = len(evidence)
                    try:
                        row["_fx"] = fx_for(row)
                        ready.append(row)
                    except RequestLimitError:
                        break
                    except Exception as error:
                        mark_open(row, error)
                        row["evidence_sha256"] = [item["sha256"] for item in evidence[before:]]
                if scope.budget.requests_started >= query.max_requests:
                    checkpoint("Abrufabschnitt beendet")
                    break
                if not ready:
                    continue
                primary = [row for row in ready if row.get("lookup_stage") != "fallback"]
                if primary:
                    before = len(evidence)
                    try:
                        payload, linked = batch_request([(row, row["provider_id"], "primary") for row in primary])
                        for row in primary:
                            if (not resolve(row, payload, row["provider_id"], "primary", linked)
                                    and query.strategy == "automatic" and row["reason"] in SEARCH_FAILURES):
                                row.update(status="pending", lookup_stage="fallback")
                    except RequestLimitError:
                        break
                    except Exception as error:
                        for row in primary:
                            mark_open(row, error)
                            row["evidence_sha256"] = [item["sha256"] for item in evidence[before:]]
                alternatives = [row for row in ready if row["status"] == "pending" and row.get("lookup_stage") == "fallback"]
                if alternatives and scope.budget.requests_started < query.max_requests:
                    before = len(evidence)
                    try:
                        payload, linked = batch_request([(row, identifier, search) for row in alternatives for identifier, search in fallback_candidates(row)])
                        for row in alternatives:
                            for identifier, search in fallback_candidates(row):
                                if resolve(row, payload, identifier, search, linked):
                                    break
                                if row["reason"] not in SEARCH_FAILURES:
                                    break
                            if row["status"] != "fetched":
                                row["lookup_stage"] = "exhausted"
                    except RequestLimitError:
                        break
                    except Exception as error:
                        for row in alternatives:
                            mark_open(row, error)
                            row["evidence_sha256"] = list(dict.fromkeys([*row.get("evidence_sha256", []), *(item["sha256"] for item in evidence[before:])]))
                            row["lookup_stage"] = "exhausted"
                checkpoint("Kurse abrufen")
        for row in rows:
            row.pop("_fx", None)
        checkpoint("Vorschau berechnen")
        unique = {canonical_json(item): item for item in evidence}
        return rows, list(unique.values()), prices, fx_series, scope.budget.requests_started
