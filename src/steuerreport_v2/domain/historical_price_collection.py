"""Begrenzte Preisabschnitte ohne produktive Daten- oder Klassifikationsaenderung."""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, localcontext
import hashlib
import json

from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.domain.request_limits import RequestLimitError
from steuerreport_v2.importers.source_history_importer import canonical_json

UTC = timezone.utc
POINTS_PER_BATCH = 25


def quote_target(row):
    midnight = datetime.combine(date.fromisoformat(row["price_date"]), time(), UTC)
    first = datetime.fromisoformat(row["first_event_at"])
    return max(midnight, first - timedelta(minutes=30))


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
    if not isinstance(payload, list) or not payload:
        fail("historical_price_fx_date_invalid")
    candidates = []
    for row in payload:
        if not isinstance(row, dict) or row.get("base") != "USD" or row.get("quote") != "EUR":
            fail("historical_price_fx_date_invalid")
        instant = date.fromisoformat(row["date"])
        if instant <= day:
            candidates.append((instant, positive(row.get("rate"))))
    if not candidates:
        fail("historical_price_fx_date_invalid")
    candidates.sort()
    latest = candidates[-1]
    if (day - latest[0]).days > 7 or any(item[0] == latest[0] and item[1] != latest[1] for item in candidates):
        fail("historical_price_fx_date_invalid")
    return latest[1], latest[0].isoformat()


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

    def finish(row, eur, instant, fx_day, linked, fx_sha=None):
        hashes = list(dict.fromkeys([*(item["sha256"] for item in linked), *([fx_sha] if fx_sha else [])]))
        identity = hashlib.sha256(canonical_json(hashes).encode()).hexdigest()
        source = f"historical:v2:{query.provider}:{row['provider_id']}:day:{row['price_date']}:evidence:{identity}"
        prices.append(PricePointCreate(asset=row["asset"], price_eur=eur, priced_at=instant, source=source, confidence=Decimal("0.95")))
        row.update(status="fetched", reason=None, price_eur=str(eur), priced_at=instant.isoformat(), fx_date=fx_day,
                   source=source, evidence_sha256=hashes)

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
                    historical_fx(payload, day, positive, fail)
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
                if not ready or scope.budget.requests_started >= query.max_requests:
                    checkpoint("Abrufabschnitt beendet")
                    break
                coins = defaultdict(set)
                for row in ready:
                    coins[row["provider_id"]].add(int(quote_target(row).timestamp()))
                linked = []
                before = len(evidence)
                try:
                    payload, linked = request("defillama", "https://coins.llama.fi/batchHistorical",
                                              {"coins": canonical_json({key: sorted(values) for key, values in sorted(coins.items())}), "searchWidth": "1h"})
                    for row in ready:
                        try:
                            usd, instant = historical_quote(payload, row, positive, fail)
                            rate, fx_day, fx_sha = row["_fx"]
                            with localcontext() as arithmetic:
                                arithmetic.prec = 60
                                eur = positive((usd * rate).quantize(Decimal("0.000000000000000001")))
                            finish(row, eur, instant, fx_day, linked, fx_sha)
                        except Exception as error:
                            mark_open(row, error)
                            row["evidence_sha256"] = list(dict.fromkeys([*row.get("evidence_sha256", []), *(item["sha256"] for item in linked)]))
                except RequestLimitError:
                    break
                except Exception as error:
                    for row in ready:
                        mark_open(row, error)
                        row["evidence_sha256"] = [item["sha256"] for item in evidence[before:]]
                checkpoint("Kurse abrufen")
        for row in rows:
            row.pop("_fx", None)
        checkpoint("Vorschau berechnen")
        unique = {canonical_json(item): item for item in evidence}
        return rows, list(unique.values()), prices, fx_series, scope.budget.requests_started
