"""Historische EUR-Tagespreise: lokaler Plan, belegter Abruf, atomare Freigabe.

Keine V1-Datenbank, keine Fortschreibung spaeterer Kurse, keine automatische
Token-, Quellen- oder Jahresfreigabe. Originalantworten bleiben privat erhalten.
"""
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, DecimalException, InvalidOperation, localcontext
import base64
import binascii
import fcntl
import hashlib
import json
import os
import shutil
from uuid import UUID

from steuerreport_v2 import __version__
from steuerreport_v2.contracts.admin import AdminSettingWrite
from steuerreport_v2.contracts.historical_prices import (
    HistoricalPriceQuery,
    ManualHistoricalPricePreviewRequest,
    PriceMapping,
)
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.contracts.review import ReviewDecision
from steuerreport_v2.domain.ai_changes import DERIVED_TABLES, _fingerprint, _summary, _tax_delta, _tax_groups, encoded
from steuerreport_v2.domain.connections import ConnectionService
from steuerreport_v2.domain.external_http import managed_client, outbound_scope
from steuerreport_v2.domain.external_price_backfill import ExternalPriceBackfillService
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.request_limits import RequestLimitError
from steuerreport_v2.domain.valuation import PriceCoverageService
from steuerreport_v2.domain.tax_time import event_reporting_year_sql, reporting_tax_year
from steuerreport_v2.importers.source_history_importer import canonical_json

MAPPING_PREFIX = "price.mapping."
METHOD = "historical-eur-daily-v2"


class HistoricalPriceError(ValueError):
    pass


def fail(code):
    raise HistoricalPriceError(code)


def digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def positive(value):
    try:
        number = Decimal(str(value))
        if number.is_finite() and 0 < number < Decimal("1e19"):
            return number
    except (ValueError, InvalidOperation):
        pass
    fail("historical_price_value_invalid")


class HistoricalPriceService:
    def __init__(self, store):
        self.store = store
        self.root = store.path.parent / "historical_prices"

    def _path(self, *parts):
        path = self.root
        if path.is_symlink():
            fail("historical_price_storage_invalid")
        for part in parts:
            path = path / part
            if path.is_symlink():
                fail("historical_price_storage_invalid")
        return path

    def _write(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o400)
        except FileExistsError:
            if path.is_symlink() or path.read_bytes() != content:
                fail("historical_price_evidence_conflict")
            return
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())

    def _json(self, path):
        if not path.is_file() or path.is_symlink():
            fail("historical_price_not_found")
        return json.loads(path.read_bytes())

    def mappings(self):
        helper = ExternalPriceBackfillService(self.store)
        aliases = helper._alias_map(helper._load_assets("configs/crypto_price_sources.json"))
        result = {key: {"asset": key, "coingecko_id": row.coingecko_id, "defillama_id": row.defillama_id, "origin": "bundled"} for key, row in aliases.items()}
        with self.store.connect() as con:
            rows = con.execute("select value_json from admin_settings where starts_with(key, ?)", [MAPPING_PREFIX]).fetchall()
        for row in rows:
            mapping = PriceMapping.model_validate_json(row[0], context={"stored_mapping": True})
            result[mapping.asset] = {**mapping.model_dump(), "origin": "operator"}
        return result

    def save_mapping(self, mapping):
        if not mapping.coingecko_id and not mapping.defillama_id:
            fail("historical_price_mapping_required")
        with ConnectionService(self.store)._mutation():
            self.store.write_admin_settings_batch([AdminSettingWrite(
                key=MAPPING_PREFIX + mapping.asset, value_json=mapping.model_dump_json())], [])
        return mapping.model_dump()

    def _revision(self):
        with self.store.connect() as con:
            return _fingerprint(con, excluded_admin_prefixes=("history.job.",))

    def _full_plan(self, query):
        with self.store.exclusive_access():
            return self._build_full_plan(query)

    def _build_full_plan(self, query):
        mappings = self.mappings()
        risks = ExternalPriceBackfillService(self.store)._token_risk_statuses()
        if query.scope == "all_observed":
            from steuerreport_v2.domain.observed_price_requirements import observed_requirements
            rows = observed_requirements(self.store, query, mappings, risks)
            return self._finish_plan(query, rows)
        year_context = self._required_year_context()
        combined = {}
        for item in PriceCoverageService(self.store).requirements().requirements:
            counts = year_context.get((item.asset, item.price_date, item.source, item.event_type, item.role), {})
            if query.year is not None and query.year not in counts or query.assets and item.asset.upper() not in query.assets:
                continue
            selected_counts = {year: count for year, count in counts.items() if query.year is None or query.year == year}
            key = (item.price_date.isoformat(), item.asset.upper())
            if key not in combined:
                mapping = mappings.get(key[1], {})
                identifier = mapping.get("coingecko_id") if query.provider == "coingecko" else mapping.get("defillama_id") or ("coingecko:" + mapping["coingecko_id"] if mapping.get("coingecko_id") else None)
                reason = "token_risk_spam_review" if risks.get(key[1]) == "spam_review" else "asset_not_configured" if not identifier else "future_date" if item.price_date >= datetime.now(timezone.utc).date() else None
                combined[key] = {"asset": key[1], "price_date": key[0], "event_count": 0, "provider_id": identifier,
                                 "status": "blocked" if reason else "planned", "reason": reason,
                                 "years": [], "event_year_counts": {}, "event_types": [],
                                 "sources": [],
                                 "first_event_at": item.first_event_at.replace(tzinfo=timezone.utc).isoformat()}
            combined[key]["event_count"] += sum(selected_counts.values())
            combined[key]["years"] = sorted(set(combined[key]["years"]) | set(selected_counts))
            combined[key]["event_types"] = sorted(set(combined[key]["event_types"]) | {item.event_type})
            combined[key]["sources"] = sorted(set(combined[key]["sources"]) | {item.source})
            for year, count in selected_counts.items():
                combined[key]["event_year_counts"][str(year)] = combined[key]["event_year_counts"].get(str(year), 0) + count
            combined[key]["first_event_at"] = min(combined[key]["first_event_at"], item.first_event_at.replace(tzinfo=timezone.utc).isoformat())
        if query.strategy == "automatic" and any(row["asset"] == "SOL" for row in combined.values()):
            from steuerreport_v2.domain.observed_price_requirements import observed_requirements
            # Native SOL darf auch im Steuerbedarf nicht aus einem Symbol abgeleitet werden,
            # wenn Originaldaten widersprechende Mints enthalten. Alle Quelljahre pruefen.
            identities = observed_requirements(self.store, query.model_copy(update={"year": None, "assets": ["SOL"]}), mappings, risks)
            identity = identities[0] if identities else None
            for row in combined.values():
                if row["asset"] != "SOL":
                    continue
                if identity is None:
                    row.update(status="blocked", reason="solana_mint_missing")
                    continue
                row.update(mints=identity["mints"], identity_basis=identity["identity_basis"])
                if identity["reason"] in {"asset_mint_conflict", "solana_mint_invalid", "solana_mint_identity_mismatch", "price_mapping_mint_mismatch", "token_risk_spam_review"}:
                    row.update(status="blocked", reason=identity["reason"])
        rows = sorted(combined.values(), key=lambda row: (row["status"] != "planned", row["price_date"], row["asset"]))
        return self._finish_plan(query, rows)

    def _required_year_context(self):
        year = f"(select {event_reporting_year_sql('e', 'r')} from canonical_events e left join raw_objects r on r.raw_object_id=e.raw_object_id where e.event_id=req.event_id)"
        sql = PriceCoverageService(self.store)._missing_price_query(
            f"req.asset, cast(req.event_time as date), req.source, req.event_type, req.role, {year} as reporting_year, count(*)",
            "1,2,3,4,5,6", "1,2,3,4,5,6")
        with self.store.connect() as con:
            rows = con.execute(sql).fetchall()
        result = {}
        for asset, day, source, event_type, role, reporting_year, count in rows:
            result.setdefault((asset, day, source, event_type, role), {})[int(reporting_year)] = int(count)
        return result

    def _source_context(self, query):
        year = event_reporting_year_sql("e", "r")
        predicate, params = [], []
        if query.year is not None:
            predicate.append(f"{year} = ?")
            params.append(query.year)
        if query.assets:
            predicate.append("(upper(e.asset) in (select unnest(?)) or upper(e.quote_asset) in (select unnest(?)) or upper(e.fee_asset) in (select unnest(?)))")
            params.extend([query.assets] * 3)
        with self.store.connect() as con:
            rows = con.execute(f"select {year}, e.event_type, count(*) from canonical_events e left join raw_objects r on r.raw_object_id=e.raw_object_id "
                               + ("where " + " and ".join(predicate) if predicate else "") + " group by 1,2 order by 1,2", params).fetchall()
        return rows

    def _finish_plan(self, query, rows):
        from steuerreport_v2.domain.asset_identity import AssetIdentityIndex
        AssetIdentityIndex(self.store).apply_to_plan(rows, self.mappings(), provider=query.provider)
        if len(rows) > 50_000:
            fail("historical_price_plan_too_large")
        context = self._source_context(query)
        types = {}
        year_events = {}
        for year, event_type, count in context:
            year_events[int(year)] = year_events.get(int(year), 0) + int(count)
            types[event_type] = types.get(event_type, 0) + int(count)
        summaries = self._year_summary(rows, years=[query.year] if query.year else sorted(year_events), year_events=year_events)
        result = {"query": query.model_dump(mode="json", exclude={"page", "page_size"}), "scope": query.scope,
                  "methodology": METHOD, "time_basis": "CoinGecko: UTC-Tagesreferenz; DefiLlama: belegter Quote vor erstem Ereignis des UTC-Tags; kein Ausfuehrungskurs",
                  "database_revision": self._revision(), "requirements_count": sum(row["status"] != "covered" for row in rows), "rows": rows,
                  "rows_total": len(rows), "inventory_count": len(rows), "source_events_count": sum(types.values()),
                  "source_event_types": types, "year_summary": summaries, "events_count": sum(row["event_count"] for row in rows),
                  "fetchable_count": sum(row["status"] == "planned" for row in rows),
                  "max_requests": query.max_requests, "writes_financial_data": False}
        result["plan_sha256"] = digest(result)
        return result

    @staticmethod
    def _year_summary(rows, *, years=None, year_events=None):
        years = years if years is not None else sorted({year for row in rows for year in row.get("years", [reporting_tax_year(datetime.fromisoformat(row["first_event_at"]))])})
        results = []
        for year in years:
            items = [row for row in rows if year in row.get("years", [reporting_tax_year(datetime.fromisoformat(row["first_event_at"]))])]
            results.append({"year": year, "events_count": (year_events or {}).get(year, sum(row.get("event_year_counts", {}).get(str(year), row["event_count"]) for row in items)),
                            "tokens_count": len({row["asset"] for row in items}), "inventory_count": len(items),
                            "requirements_count": sum(row["status"] not in {"covered", "fetched"} for row in items),
                            "covered_count": sum(row["status"] in {"covered", "fetched"} for row in items),
                            "fetchable_count": sum(row["status"] in {"planned", "pending"} for row in items),
                            "blocked_count": sum(row["status"] == "blocked" for row in items),
                            "open_count": sum(row["status"] == "open" for row in items)})
        return results

    def plan(self, query):
        result = self._full_plan(query)
        count = len(result["rows"])
        page = min(query.page, max(1, (count + query.page_size - 1) // query.page_size))
        offset = (page - 1) * query.page_size
        return {**result, "rows": result["rows"][offset:offset + query.page_size], "rows_truncated": count > query.page_size,
                "page": page, "page_size": query.page_size, "row_offset": offset, "rows_limit": query.page_size,
                "next_offset": offset + query.page_size if offset + query.page_size < count else None}

    def _request(self, client, provider, url, params, evidence):
        response = client.get(url, params=params, follow_redirects=False)
        body = response.content
        if len(body) > 1024 * 1024:
            fail("historical_price_response_too_large")
        sha = hashlib.sha256(body).hexdigest()
        self._write(self._path("evidence", sha + ".body"), body)
        evidence.append({"provider": provider, "url": url, "params": params, "http_status": response.status_code,
                         "sha256": sha, "fetched_at_utc": datetime.now(timezone.utc).isoformat()})
        if response.status_code != 200:
            fail("historical_price_http_" + str(response.status_code))
        try:
            return json.loads(body, parse_float=Decimal)
        except ValueError:
            fail("historical_price_response_invalid")

    def _quote(self, client, row, query, evidence, fx_cache):
        day = date.fromisoformat(row["price_date"])
        midnight = datetime.combine(day, time(), timezone.utc)
        provider_id = row["provider_id"]
        if query.provider == "coingecko":
            data = self._request(client, "coingecko", "https://api.coingecko.com/api/v3/coins/" + provider_id + "/history",
                                 {"date": day.isoformat(), "localization": "false"}, evidence)
            if data.get("id") != provider_id:
                fail("historical_price_identity_mismatch")
            eur = positive(data.get("market_data", {}).get("current_price", {}).get("eur"))
            return eur, midnight, None
        first_event = datetime.fromisoformat(row["first_event_at"])
        target = max(midnight, first_event - timedelta(minutes=30))
        data = self._request(client, "defillama", f"https://coins.llama.fi/prices/historical/{int(target.timestamp())}/{provider_id}",
                             {"searchWidth": "1h"}, evidence)
        coin = data.get("coins", {}).get(provider_id, {})
        instant = coin.get("timestamp")
        if type(instant) is not int or not int(midnight.timestamp()) <= instant <= int(first_event.timestamp()) or abs(instant - int(target.timestamp())) > 3600:
            # Keine spaeteren oder still zurueckdatierten Quotes in historische Ereignisse schreiben.
            fail("historical_price_timestamp_mismatch")
        usd = positive(coin.get("price"))
        if day not in fx_cache:
            from steuerreport_v2.domain.historical_price_collection import historical_fx
            quotes = self._request(client, "fx", "https://api.frankfurter.dev/v2/providers/ecb/rates",
                                  {"base": "USD", "quotes": "EUR", "from": (day - timedelta(days=7)).isoformat(), "to": day.isoformat()}, evidence)
            rate, fx_date = historical_fx(quotes, day, positive, fail)
            fx_cache[day] = (rate, fx_date, evidence[-1])
        rate, fx_date, fx_evidence = fx_cache[day]
        if fx_evidence not in evidence:
            evidence.append(fx_evidence)
        with localcontext() as arithmetic:
            arithmetic.prec = 60
            eur = (usd * rate).quantize(Decimal("0.000000000000000001"))
        return positive(eur), datetime.fromtimestamp(instant, timezone.utc), fx_date

    def _directory(self, request_id):
        return self._path(str(UUID(str(request_id))))

    @contextmanager
    def _lock(self, directory):
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = directory / "operation.lock"
        if path.is_symlink():
            fail("historical_price_storage_invalid")
        fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                fail("historical_price_operation_running")
            yield
        finally:
            os.close(fd)

    def fetch(self, request):
        if request.scope == "all_observed" or request.strategy == "automatic":
            return self._fetch_observed(request)
        return self._fetch_tax_required(request)

    @staticmethod
    def _manual_attachment(file, kind):
        try:
            content = base64.b64decode(file.content_base64, validate=True)
        except (binascii.Error, ValueError):
            fail("historical_price_manual_evidence_invalid")
        if not content or len(content) > 2 * 1024 * 1024:
            fail("historical_price_manual_evidence_size_invalid")
        sha = hashlib.sha256(content).hexdigest()
        return content, {
            "kind": kind,
            "filename": file.filename,
            "media_type": file.media_type,
            "source_name": file.source_name,
            "source_reference": file.source_reference,
            "source_observed_at": file.source_observed_at.isoformat(),
            "source_observed_at_utc": file.source_observed_at.astimezone(timezone.utc).isoformat(),
            "sha256": sha,
            "byte_length": len(content),
        }

    @staticmethod
    def _manual_fx_reference(observations, price_day):
        from steuerreport_v2.domain.historical_fx import (
            FX_POLICY_ID,
            MAX_REFERENCE_AGE_DAYS,
            select_fx_reference,
        )

        payload = [item.model_dump(mode="json") for item in observations]
        reference = select_fx_reference(payload, price_day)
        if reference is not None:
            return reference, None, FX_POLICY_ID
        if not payload:
            return None, "historical_price_fx_evidence_required", FX_POLICY_ID

        past = []
        future = False
        for row in payload:
            try:
                observed = date.fromisoformat(row["date"])
                rate = Decimal(str(row["rate"]))
            except (KeyError, TypeError, ValueError, InvalidOperation):
                return None, "historical_price_fx_evidence_invalid", FX_POLICY_ID
            if not rate.is_finite() or rate <= 0 or row.get("base") == row.get("quote"):
                return None, "historical_price_fx_evidence_invalid", FX_POLICY_ID
            if row.get("base") not in {"USD", "EUR"} or row.get("quote") not in {"USD", "EUR"}:
                return None, "historical_price_fx_evidence_invalid", FX_POLICY_ID
            if observed > price_day:
                future = True
            else:
                past.append((observed, row))
        if not past:
            reason = "historical_price_fx_future" if future else "historical_price_fx_evidence_invalid"
            return None, reason, FX_POLICY_ID
        latest_day = max(day for day, _ in past)
        if (price_day - latest_day).days > MAX_REFERENCE_AGE_DAYS:
            return None, "historical_price_fx_stale", FX_POLICY_ID
        latest = [row for day, row in past if day == latest_day]
        normalized = set()
        with localcontext() as arithmetic:
            arithmetic.prec = 60
            for row in latest:
                rate = Decimal(str(row["rate"]))
                try:
                    value = rate if row["base"] == "USD" else Decimal("1") / rate
                except DecimalException:
                    return None, "historical_price_fx_evidence_invalid", FX_POLICY_ID
                if not value.is_finite() or not 0 < value < Decimal("1e19"):
                    return None, "historical_price_fx_evidence_invalid", FX_POLICY_ID
                normalized.add(value)
        if len(normalized) > 1:
            return None, "historical_price_fx_conflict", FX_POLICY_ID
        reason = "historical_price_fx_future" if future and not any(
            (price_day - day).days <= MAX_REFERENCE_AGE_DAYS for day, _ in past
        ) else "historical_price_fx_evidence_invalid"
        return None, reason, FX_POLICY_ID

    @staticmethod
    def _manual_request_document(request, price_file, fx_file):
        payload = request.model_dump(mode="json")
        payload.pop("request_id", None)
        payload["price_evidence"].pop("content_base64", None)
        payload["price_evidence"].update(
            sha256=price_file["sha256"], byte_length=price_file["byte_length"]
        )
        if payload.get("fx_evidence") is not None:
            payload["fx_evidence"].pop("content_base64", None)
            payload["fx_evidence"].update(
                sha256=fx_file["sha256"], byte_length=fx_file["byte_length"]
            )
        return payload

    @staticmethod
    def _manual_identity_is_clear(row):
        mints = row.get("mints") or []
        if len(mints) > 1:
            return False
        basis = row.get("identity_basis")
        identity = row.get("asset_identity") or {}
        return bool(
            len(mints) == 1
            or basis in {"original_mint", "native_sol_reference", "configured_mapping"}
            or (identity.get("network") and identity.get("contract_address"))
        )

    def _existing_manual_preview(self, evidence_key, submission_sha256):
        if not self.root.exists() or self.root.is_symlink():
            return None
        for path in self.root.glob("*/preview.json"):
            if path.is_symlink():
                continue
            try:
                preview = self._json(path)
            except (ValueError, OSError, KeyError):
                continue
            if preview.get("manual_evidence_key") != evidence_key:
                continue
            if preview.get("manual_submission_sha256") != submission_sha256:
                fail("historical_price_manual_evidence_conflict")
            return self.get(preview["id"])
        return None

    def manual_preview(self, request: ManualHistoricalPricePreviewRequest):
        price_bytes, price_file = self._manual_attachment(request.price_evidence, "manual_price_original")
        fx_bytes = None
        fx_file = None
        if request.fx_evidence is not None:
            fx_bytes, fx_file = self._manual_attachment(request.fx_evidence, "manual_fx_original")

        if request.query.assets and request.asset not in request.query.assets:
            fail("historical_price_manual_need_not_found")
        query = request.query
        price_time = request.priced_at.astimezone(timezone.utc)
        now = datetime.now(timezone.utc)
        if price_time.date() != request.price_date or price_time > now:
            fail("historical_price_manual_timestamp_invalid")
        if request.price_evidence.source_observed_at.astimezone(timezone.utc) > now:
            fail("historical_price_manual_source_time_future")
        if request.fx_evidence and request.fx_evidence.source_observed_at.astimezone(timezone.utc) > now:
            fail("historical_price_manual_source_time_future")

        with self._lock(self._path("collection")), self._lock(self._directory(request.request_id)):
            directory = self._directory(request.request_id)
            plan = self._full_plan(query)
            if plan["plan_sha256"] != request.plan_sha256:
                fail("historical_price_plan_stale")
            matches = [
                row for row in plan["rows"]
                if row["asset"].upper() == request.asset
                and row["price_date"] == request.price_date.isoformat()
            ]
            if len(matches) != 1:
                fail("historical_price_manual_need_not_found")
            need = matches[0]
            if need.get("status") not in {"planned", "blocked"}:
                fail("historical_price_manual_need_not_open")
            if not self._manual_identity_is_clear(need):
                fail("historical_price_manual_identity_ambiguous")
            if need.get("status") == "blocked" and need.get("reason") != "asset_not_configured":
                fail("historical_price_manual_need_blocked")
            if datetime.fromisoformat(need["first_event_at"]).astimezone(timezone.utc) < price_time:
                fail("historical_price_manual_timestamp_after_event")

            need_sha = digest(need)
            fx_reference = None
            fx_reason = None
            fx_policy_id = None
            if request.price_currency == "USD":
                if request.fx_evidence is None:
                    fx_reason = "historical_price_fx_evidence_required"
                    from steuerreport_v2.domain.historical_fx import FX_POLICY_ID
                    fx_policy_id = FX_POLICY_ID
                elif not request.fx_observations:
                    fx_reason = "historical_price_fx_evidence_required"
                    from steuerreport_v2.domain.historical_fx import FX_POLICY_ID
                    fx_policy_id = FX_POLICY_ID
                elif any(item.source != request.fx_evidence.source_name for item in request.fx_observations):
                    fx_reason = "historical_price_fx_source_mismatch"
                    from steuerreport_v2.domain.historical_fx import FX_POLICY_ID
                    fx_policy_id = FX_POLICY_ID
                else:
                    fx_reference, fx_reason, fx_policy_id = self._manual_fx_reference(
                        request.fx_observations, request.price_date
                    )
            price_observation = {
                "raw_value": str(request.price_value),
                "raw_currency": request.price_currency,
                "unit": f"{request.price_currency} per 1 {request.asset}",
                "priced_at_original": request.priced_at.isoformat(),
                "priced_at_utc": price_time.isoformat(),
                "source_name": request.price_evidence.source_name,
                "source_reference": request.price_evidence.source_reference,
                "source_observed_at": price_file["source_observed_at"],
                "source_observed_at_utc": price_file["source_observed_at_utc"],
                "evidence_sha256": price_file["sha256"],
                "evidence_filename": price_file["filename"],
                "evidence_media_type": price_file["media_type"],
                "evidence_byte_length": price_file["byte_length"],
            }
            fx_observation = None
            if request.price_currency == "USD":
                fx_observation = {
                    "policy_id": fx_policy_id,
                    "source_name": request.fx_evidence.source_name if request.fx_evidence else None,
                    "source_reference": request.fx_evidence.source_reference if request.fx_evidence else None,
                    "source_observed_at": fx_file["source_observed_at"] if fx_file else None,
                    "source_observed_at_utc": fx_file["source_observed_at_utc"] if fx_file else None,
                    "observations": [
                        {**item.model_dump(mode="json"), "unit": f"{item.quote} per 1 {item.base}"}
                        for item in request.fx_observations
                    ],
                    "selected_reference": None if fx_reference is None else {
                        "date": fx_reference.reference_date.isoformat(),
                        "base": fx_reference.original_base,
                        "quote": fx_reference.original_quote,
                        "unit": f"{fx_reference.original_quote} per 1 {fx_reference.original_base}",
                        "raw_rate": str(fx_reference.original_rate),
                        "rate_eur_per_usd": str(fx_reference.rate_eur_per_usd),
                        "source": fx_reference.source,
                    },
                    "evidence_sha256": fx_file["sha256"] if fx_file else None,
                    "evidence_filename": fx_file["filename"] if fx_file else None,
                    "evidence_media_type": fx_file["media_type"] if fx_file else None,
                    "evidence_byte_length": fx_file["byte_length"] if fx_file else None,
                }
            manual_submission = {
                "schema": "manual-historical-price-evidence-v1",
                "need_sha256": need_sha,
                "need": need,
                "price": price_observation,
                "fx": fx_observation,
                "fx_block_reason": fx_reason,
            }
            manual_submission_sha = digest(manual_submission)
            evidence_key = digest({
                "need_sha256": need_sha,
                "price_evidence_sha256": price_file["sha256"],
                "fx_evidence_sha256": fx_file["sha256"] if fx_file else None,
            })
            request_doc = self._manual_request_document(request, price_file, fx_file)
            request_path = directory / "request.json"
            preview_path = directory / "preview.json"
            if request_path.exists():
                if self._json(request_path) != request_doc:
                    fail("historical_price_request_conflict")
                if not preview_path.exists():
                    fail("historical_price_incomplete_request")
                return self.get(request.request_id)
            previous = self._existing_manual_preview(evidence_key, manual_submission_sha)
            if previous is not None:
                return previous

            self._write(directory / "plan.json", canonical_json(plan).encode())
            self._write(self._path("evidence", price_file["sha256"] + ".body"), price_bytes)
            evidence = [price_file]
            row = {**need, "manual_evidence": price_observation}
            if fx_file is not None:
                self._write(self._path("evidence", fx_file["sha256"] + ".body"), fx_bytes)
                evidence.append(fx_file)
                row["evidence_sha256"] = [price_file["sha256"], fx_file["sha256"]]
            else:
                row["evidence_sha256"] = [price_file["sha256"]]
            prices = []
            status = "ready"
            reason = None
            eur_price = request.price_value
            if request.price_currency == "USD":
                if fx_reason:
                    status, reason = "blocked", fx_reason
                elif fx_reference is None:
                    status, reason = "blocked", "historical_price_fx_evidence_invalid"
                else:
                    with localcontext() as arithmetic:
                        arithmetic.prec = 60
                        eur_price = request.price_value * fx_reference.rate_eur_per_usd
            if status == "ready":
                unit = Decimal("0.000000000000000001")
                if not eur_price.is_finite() or eur_price <= 0 or eur_price >= Decimal("1e19"):
                    status, reason = "blocked", "historical_price_value_invalid"
                else:
                    try:
                        with localcontext() as arithmetic:
                            arithmetic.prec = 60
                            rounded = eur_price.quantize(unit)
                    except InvalidOperation:
                        status, reason = "blocked", "historical_price_manual_precision_exceeds_storage"
                if status == "ready" and request.price_currency == "EUR" and rounded != eur_price:
                    status, reason = "blocked", "historical_price_manual_precision_exceeds_storage"
                if status == "ready" and rounded <= 0:
                    status, reason = "blocked", "historical_price_manual_precision_exceeds_storage"
                if status == "ready":
                    eur_price = positive(rounded)
                    fx_sha = fx_file["sha256"] if fx_file else "direct-eur"
                    source_hash = digest({
                        "need_sha256": need_sha,
                        "price_sha256": price_file["sha256"],
                        "fx_sha256": fx_sha,
                        "raw_value": str(request.price_value),
                        "currency": request.price_currency,
                        "priced_at": price_time.isoformat(),
                    })
                    source = f"manual:historical-evidence:v1:{source_hash}"
                    price = PricePointCreate(
                        asset=request.asset,
                        price_eur=eur_price,
                        priced_at=price_time.replace(tzinfo=None),
                        source=source,
                        confidence=Decimal("0.95"),
                    )
                    prices.append(price)
                    row.update(
                        status="fetched",
                        reason=None,
                        price_eur=str(eur_price),
                        priced_at=price_time.isoformat(),
                        fx_date=fx_reference.reference_date.isoformat() if fx_reference else None,
                        source=source,
                        evidence_sha256=row["evidence_sha256"],
                        manual_fx=fx_observation,
                    )
            if status == "blocked":
                row.update(status="blocked", reason=reason, price_eur=None, priced_at=None, source=None)
            years = need.get("years", [])
            year_summary = [{
                "year": year,
                "events_count": need.get("event_year_counts", {}).get(str(year), need["event_count"]),
                "tokens_count": 1,
                "inventory_count": 1,
                "requirements_count": 1 if status == "blocked" else 0,
                "covered_count": 0 if status == "blocked" else 1,
                "fetchable_count": 0,
                "blocked_count": 1 if status == "blocked" else 0,
                "open_count": 0,
            } for year in years]
            preview = {
                "id": str(request.request_id),
                "software_version": __version__,
                "methodology": "manual-evidence-direct-eur-v1" if request.price_currency == "EUR" else f"manual-evidence-usd-fx:{fx_policy_id}",
                "time_basis": "Manuell belegter Kurszeitpunkt; UTC normalisiert, derselbe UTC-Tag und nicht nach dem ersten betroffenen Ereignis.",
                "created_at": now.isoformat(),
                "plan_sha256": plan["plan_sha256"],
                "database_revision": plan["database_revision"],
                "query": query.model_dump(mode="json"),
                "manual": True,
                "manual_evidence_key": evidence_key,
                "manual_submission_sha256": manual_submission_sha,
                "manual_submission": manual_submission,
                "manual_evidence": [price_observation, *([fx_observation] if fx_observation else [])],
                "rows": [row],
                "evidence": evidence,
                "prices": [price.model_dump(mode="json") for price in prices],
                "prices_count": len(prices),
                "requests_started": 0,
                "requirements_count": 1,
                "total_rows": 1,
                "pending_count": 0,
                "open_count": 0,
                "collection_complete": True,
                "source_events_count": need["event_count"],
                "source_event_types": {},
                "year_summary": year_summary,
                "status": status,
                "block_reason": reason,
                "writes_financial_data": False,
            }
            if prices:
                self._prepare(directory, preview, prices)
            else:
                with self.store.connect() as con:
                    preview["before_summary"] = _summary(con)
                    preview["before_valuation_summary"] = self._valuation_summary(con)
                    preview["frozen_source_sha256"] = self._source_digest(con)
                preview["canonical_events_unchanged"] = True
            self._write(request_path, canonical_json(request_doc).encode())
            preview["preview_sha256"] = digest(preview)
            self._write(preview_path, canonical_json(preview).encode())
            return self.get(request.request_id)

    def _fetch_tax_required(self, request):
        directory = self._directory(request.request_id)
        query = HistoricalPriceQuery.model_validate(request.model_dump(include=set(HistoricalPriceQuery.model_fields)))
        with self._lock(self._path("collection")), self._lock(directory):
            request_doc = request.model_dump(mode="json")
            if (directory / "request.json").exists():
                if self._json(directory / "request.json") != request_doc:
                    fail("historical_price_request_conflict")
                return self.get(request.request_id)
            plan = self._full_plan(query)
            if plan["plan_sha256"] != request.plan_sha256:
                fail("historical_price_plan_stale")
            self._write(directory / "request.json", canonical_json(request_doc).encode())
            rows, evidence, prices, fx_cache = [], [], [], {}
            available = min(query.max_requests, query.max_total_requests or query.max_requests)
            with outbound_scope(max_requests=available) as scope, managed_client(timeout=20) as client:
                for planned in plan["rows"]:
                    row = dict(planned)
                    if row["status"] != "planned":
                        rows.append(row)
                        continue
                    linked = []
                    try:
                        eur, instant, fx_date = self._quote(client, row, query, linked, fx_cache)
                        source = f"historical:v2:{query.provider}:{row['provider_id']}:day:{row['price_date']}:evidence:{digest(linked)}"
                        prices.append(PricePointCreate(asset=row["asset"], price_eur=eur, priced_at=instant, source=source, confidence=Decimal("0.95")))
                        row.update(status="fetched", price_eur=str(eur), priced_at=instant.isoformat(), fx_date=fx_date, source=source)
                    except RequestLimitError:
                        row.update(status="open", reason="request_budget_or_limiter_unavailable")
                    except HistoricalPriceError as error:
                        row.update(status="open", reason=str(error))
                    except Exception:
                        row.update(status="open", reason="historical_price_provider_unavailable")
                    row["evidence_sha256"] = [entry["sha256"] for entry in linked]
                    evidence.extend(linked)
                    rows.append(row)
                    if scope.budget.requests_started >= available:
                        break
            preview = {"id": str(request.request_id), "software_version": __version__, "methodology": METHOD,
                       "plan_sha256": plan["plan_sha256"], "created_at": datetime.now(timezone.utc).isoformat(),
                       "requests_started": scope.budget.requests_started, "rows": rows, "evidence": evidence,
                       "prices": [p.model_dump(mode="json") for p in prices], "query": query.model_dump(mode="json"),
                       "requirements_count": plan["requirements_count"], "prices_count": len(prices),
                       "database_revision": plan["database_revision"], "status": "ready" if prices else "no_prices"}
            if prices:
                self._prepare(directory, preview, prices)
            preview["preview_sha256"] = digest(preview)
            self._write(directory / "preview.json", canonical_json(preview).encode())
            return self.get(request.request_id)

    def continue_preview(self, request_id, request):
        from steuerreport_v2.contracts.historical_prices import HistoricalPriceFetch
        parent = self.get(request_id)
        if parent["preview_sha256"] != request.preview_sha256:
            fail("historical_price_preview_mismatch")
        if parent["applied"] or parent["software_version"] != __version__ or not self._uses_collection(parent["query"]):
            fail("historical_price_preview_stale")
        if str(request.request_id) == str(request_id):
            fail("historical_price_request_conflict")
        followup = HistoricalPriceFetch(**parent["query"], request_id=request.request_id,
                                       plan_sha256=parent["plan_sha256"], confirm_external_request=True)
        return self._fetch_observed(followup, parent=parent, retry_open=request.retry_open)

    @staticmethod
    def _uses_collection(query):
        return query.get("scope") == "all_observed" or query.get("strategy") == "automatic"

    def _fetch_observed(self, request, *, parent=None, retry_open=False):
        from steuerreport_v2.domain.historical_price_collection import collect_section
        directory = self._directory(request.request_id)
        query = HistoricalPriceQuery.model_validate(request.model_dump(include=set(HistoricalPriceQuery.model_fields)))
        with self._lock(self._path("collection")), self._lock(directory):
            request_doc = {**request.model_dump(mode="json"), "parent_preview_id": parent["id"] if parent else None,
                           "parent_preview_sha256": parent["preview_sha256"] if parent else None, "retry_open": retry_open}
            if (directory / "request.json").exists():
                if self._json(directory / "request.json") != request_doc:
                    fail("historical_price_request_conflict")
                if not (directory / "preview.json").exists():
                    fail("historical_price_incomplete_request")
                return self.get(request.request_id)
            if parent:
                if self._revision() != parent["database_revision"]:
                    fail("historical_price_preview_stale")
                plan = self._json(self._directory(parent["id"]) / "plan.json")
                rows = [{**row} for row in parent["rows"]]
                for row in rows:
                    if retry_open and row["status"] == "open":
                        row.update(status="pending", reason=None, lookup_stage="primary")
                if not any(row["status"] == "pending" for row in rows):
                    fail("historical_price_nothing_to_continue")
            else:
                plan = self._full_plan(query)
                if plan["plan_sha256"] != request.plan_sha256:
                    fail("historical_price_plan_stale")
                rows = [{**row, "status": "pending" if row["status"] == "planned" else row["status"]} for row in plan["rows"]]
            previous_starts = (parent or {}).get("requests_started", 0)
            available = query.max_requests if query.max_total_requests is None else min(query.max_requests, query.max_total_requests - previous_starts)
            if available <= 0:
                fail("historical_price_total_budget_exhausted")
            self._write(directory / "request.json", canonical_json(request_doc).encode())
            self._write(directory / "plan.json", canonical_json(plan).encode())
            progress_counter = 0

            def progress(values):
                nonlocal progress_counter
                progress_counter += 1
                self._write(directory / "progress" / f"{progress_counter:06d}.json",
                            canonical_json({**values, "updated_at": datetime.now(timezone.utc).isoformat()}).encode())

            progress({"phase": "Preisabruf vorbereiten", "rows_processed": sum(row["status"] != "pending" for row in rows),
                      "total_rows": len(rows), "requests_started": 0})
            rows, evidence, prices, fx_series, requests_started = collect_section(
                self, query.model_copy(update={"max_requests": available}), rows, parent, progress, positive, fail,
                client_factory=managed_client, scope_factory=outbound_scope)
            if self._revision() != plan["database_revision"]:
                fail("historical_price_plan_stale")
            preview = {"id": str(request.request_id), "software_version": __version__, "methodology": METHOD,
                       "plan_sha256": plan["plan_sha256"], "created_at": datetime.now(timezone.utc).isoformat(),
                       "requests_started": (parent or {}).get("requests_started", 0) + requests_started,
                       "section_requests_started": requests_started, "rows": rows, "evidence": evidence, "fx_series": fx_series,
                       "max_total_requests": query.max_total_requests,
                       "prices": [item.model_dump(mode="json") for item in prices], "query": query.model_dump(mode="json"),
                       "requirements_count": plan["requirements_count"], "prices_count": len(prices), "total_rows": len(rows),
                       "pending_count": sum(row["status"] == "pending" for row in rows),
                       "open_count": sum(row["status"] == "open" for row in rows),
                       "source_events_count": plan["source_events_count"], "source_event_types": plan["source_event_types"],
                       "year_summary": self._year_summary(rows, years=[item["year"] for item in plan["year_summary"]],
                           year_events={item["year"]: item["events_count"] for item in plan["year_summary"]}),
                       "parent_preview_id": parent["id"] if parent else None,
                       "database_revision": plan["database_revision"], "status": "ready" if prices else "no_prices"}
            preview["collection_complete"] = preview["pending_count"] == 0
            if prices:
                self._prepare(directory, preview, prices)
            preview["preview_sha256"] = digest(preview)
            self._write(directory / "preview.json", canonical_json(preview).encode())
            return self.get(request.request_id)

    def status(self, request_id):
        directory = self._directory(request_id)
        result = {"status": "not_found", "preview_id": str(request_id), "rows_processed": 0,
                  "total_rows": 0, "requests_started": 0, "phase": "Noch kein gestarteter Preisabruf"}
        lock = directory / "operation.lock"
        if not lock.is_file() or lock.is_symlink():
            return result
        fd = os.open(lock, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result.update(status="interrupted", phase="Abruf unterbrochen; gespeicherte Originalbelege bleiben erhalten")
            except BlockingIOError:
                result.update(status="running", phase="Preisabruf laeuft")
            for path in sorted((directory / "progress").glob("*.json"), reverse=True):
                try:
                    result.update(self._json(path))
                    break
                except (ValueError, OSError):
                    continue
            if (directory / "preview.json").is_file():
                try:
                    preview = self.get(request_id)
                    result.update(status="ready", phase="Preisvorschau gespeichert", preview_id=preview["id"])
                except json.JSONDecodeError:
                    pass
            return result
        finally:
            os.close(fd)

    def _prepare(self, directory, preview, prices):
        with self.store.exclusive_access(), self.store.connect() as con:
            if self._revision() != preview["database_revision"]:
                fail("historical_price_plan_stale")
            preview["before_summary"] = _summary(con)
            preview["before_valuation_summary"] = self._valuation_summary(con)
            preview["frozen_source_sha256"] = self._source_digest(con)
            before_tax = _tax_groups(con)
            con.execute("checkpoint")
            if shutil.disk_usage(directory).free < self.store.path.stat().st_size * 2 + 128 * 1024 * 1024:
                fail("historical_price_storage_insufficient")
            shutil.copyfile(self.store.path, directory / "calculation.prepared")
            (directory / "calculation.prepared").chmod(0o600)
        from steuerreport_v2.db.duckdb_store import DuckDbStore
        clone = DuckDbStore(directory / "calculation.prepared")
        clone.add_price_points(prices)
        pipeline = PipelineService(clone).rebuild_ledgers(replay_event_corrections=False)
        with clone.connect() as con:
            if self._source_digest(con) != preview["frozen_source_sha256"]:
                fail("historical_price_source_changed")
            preview["canonical_events_unchanged"] = True
            preview["after_summary"] = _summary(con)
            preview["after_valuation_summary"] = self._valuation_summary(con)
            preview["tax_line_deltas"] = _tax_delta(before_tax, _tax_groups(con))
            preview["review_issues_open"] = pipeline.review_issues_open
            preview["remaining_requirements"] = PriceCoverageService(clone).requirements().requirements_count
            con.execute("checkpoint")
        preview["prepared_sha256"] = hashlib.sha256((directory / "calculation.prepared").read_bytes()).hexdigest()

    @staticmethod
    def _source_digest(con):
        checksum = hashlib.sha256()
        for table in ("raw_import_batches", "raw_objects", "canonical_events", "review_decisions", "ai_correction_overrides"):
            checksum.update(table.encode())
            cursor = con.execute(f"select * from {table} order by all")
            while rows := cursor.fetchmany(1000):
                for row in rows:
                    checksum.update(canonical_json([encoded(value) for value in row]).encode())
                    checksum.update(b"\n")
        return checksum.hexdigest()

    @staticmethod
    def _valuation_summary(con):
        lots = con.execute("select count(*), coalesce(sum(cost_basis_eur_total), 0) from tax_lots").fetchone()
        flows = con.execute("select count(*), count(*) filter (where value_eur is null) from flow_ledger").fetchone()
        return {"price_points": con.execute("select count(*) from price_ledger").fetchone()[0],
                "lot_count": lots[0], "lot_cost_basis_eur": str(lots[1]),
                "flow_count": flows[0], "unvalued_flow_count": flows[1]}

    def get(self, request_id):
        directory = self._directory(request_id)
        preview = self._json(directory / "preview.json")
        if digest({k: v for k, v in preview.items() if k != "preview_sha256"}) != preview["preview_sha256"]:
            fail("historical_price_evidence_changed")
        if self._uses_collection(preview["query"]):
            plan = self._json(directory / "plan.json")
            if digest({key: value for key, value in plan.items() if key != "plan_sha256"}) != preview["plan_sha256"]:
                fail("historical_price_evidence_changed")
        for item in preview["evidence"]:
            path = self._path("evidence", item["sha256"] + ".body")
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]:
                fail("historical_price_evidence_changed")
        with self.store.connect() as con:
            applied = con.execute("select 1 from review_decisions where id=?", ["historical-price:" + str(request_id)]).fetchone() is not None
        if (directory / "applied.json").exists() and not applied:
            fail("historical_price_evidence_changed")
        return {**preview, "applied": applied}

    def evidence(self, request_id, sha):
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            fail("historical_price_not_found")
        preview = self.get(request_id)
        if not any(row["sha256"] == sha for row in preview["evidence"]):
            fail("historical_price_not_found")
        return self._path("evidence", sha + ".body").read_bytes()

    def recent(self):
        if not self.root.exists():
            return []
        results = []
        for path in sorted(self.root.glob("*/preview.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:20]:
            try:
                preview = self.get(path.parent.name)
                results.append({k: preview.get(k) for k in ("id", "created_at", "prices_count", "status", "applied", "preview_sha256", "pending_count", "open_count", "parent_preview_id", "collection_complete", "manual")})
            except (ValueError, KeyError):
                continue
        return results

    def apply(self, request_id, request):
        directory = self._directory(request_id)
        with self._lock(directory), ConnectionService(self.store)._mutation():
            preview = self.get(request_id)
            if request.preview_sha256 != preview["preview_sha256"]:
                fail("historical_price_preview_mismatch")
            if preview["applied"]:
                result = {"applied": True, "prices_count": preview["prices_count"], "decision_id": "historical-price:" + str(request_id)}
                self._write(directory / "applied.json", canonical_json(result).encode())
                return result
            if preview.get("manual") and preview["status"] != "ready":
                fail("historical_price_manual_evidence_blocked")
            if preview["status"] != "ready" or preview["software_version"] != __version__:
                fail("historical_price_preview_stale")
            if self._uses_collection(preview["query"]) and preview.get("pending_count", 0):
                fail("historical_price_collection_incomplete")
            prepared = directory / "calculation.prepared"
            if prepared.is_symlink() or hashlib.sha256(prepared.read_bytes()).hexdigest() != preview["prepared_sha256"]:
                fail("historical_price_evidence_changed")
            with self.store.connect() as con:
                decision_id = "historical-price:" + str(request_id)
                existing = con.execute("select payload_json from review_decisions where id=?", [decision_id]).fetchone()
                if existing:
                    result = {"applied": True, "prices_count": preview["prices_count"], "decision_id": decision_id}
                    self._write(directory / "applied.json", canonical_json(result).encode())
                    return result
                if self._revision() != preview["database_revision"]:
                    fail("historical_price_preview_stale")
                if not preview.get("canonical_events_unchanged") or self._source_digest(con) != preview.get("frozen_source_sha256"):
                    fail("historical_price_source_changed")
                safe = str(prepared).replace("'", "''")
                con.execute(f"attach '{safe}' as historical_prices_prepared (read_only)")
                try:
                    con.execute("begin transaction")
                    for table in DERIVED_TABLES:
                        con.execute(f"delete from {table}")
                        con.execute(f"insert into {table} select * from historical_prices_prepared.{table}")
                    if _summary(con) != preview["after_summary"]:
                        fail("reconciliation_failed")
                    if self._source_digest(con) != preview["frozen_source_sha256"]:
                        fail("historical_price_source_changed")
                    decision = ReviewDecision(decision_id=decision_id, decision_type="historical_price_import", scope="historical_prices:" + str(request_id),
                        title="Historische EUR-Preise nach Vorschau uebernommen", actor=request.actor,
                        rationale="Ausdruecklich bestaetigte Preisuebernahme und Neuberechnung; keine steuerliche Quellen-/Jahresfreigabe.",
                        evidence_ref=f"api:/api/v1/prices/historical/previews/{request_id}", payload={"preview_sha256": request.preview_sha256}, created_at=datetime.now(timezone.utc))
                    con.execute("insert into review_decisions values (?, ?, ?, ?)", [decision_id, decision.model_dump_json(), decision.created_at, None])
                    con.execute("commit")
                except Exception:
                    con.execute("rollback")
                    raise
                finally:
                    con.execute("detach historical_prices_prepared")
            result = {"applied": True, "prices_count": preview["prices_count"], "decision_id": decision_id}
            self._write(directory / "applied.json", canonical_json(result).encode())
            return result
