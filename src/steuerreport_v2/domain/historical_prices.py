"""Historische EUR-Tagespreise: lokaler Plan, belegter Abruf, atomare Freigabe.

Keine V1-Datenbank, keine Fortschreibung spaeterer Kurse, keine automatische
Token-, Quellen- oder Jahresfreigabe. Originalantworten bleiben privat erhalten.
"""
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
import fcntl
import hashlib
import json
import os
import shutil
from uuid import UUID

from steuerreport_v2 import __version__
from steuerreport_v2.contracts.admin import AdminSettingWrite
from steuerreport_v2.contracts.historical_prices import HistoricalPriceQuery, PriceMapping
from steuerreport_v2.contracts.prices import PricePointCreate
from steuerreport_v2.contracts.review import ReviewDecision
from steuerreport_v2.domain.ai_changes import DERIVED_TABLES, _fingerprint, _summary, _tax_delta, _tax_groups
from steuerreport_v2.domain.connections import ConnectionService
from steuerreport_v2.domain.external_http import managed_client, outbound_scope
from steuerreport_v2.domain.external_price_backfill import ExternalPriceBackfillService
from steuerreport_v2.domain.pipeline import PipelineService
from steuerreport_v2.domain.request_limits import RequestLimitError
from steuerreport_v2.domain.valuation import PriceCoverageService
from steuerreport_v2.domain.tax_time import reporting_tax_year
from steuerreport_v2.importers.source_history_importer import canonical_json

MAPPING_PREFIX = "price.mapping."
METHOD = "historical-eur-daily-v1"


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
        result = {key: {"asset": key, "coingecko_id": row.coingecko_id, "defillama_id": row.defillama_id} for key, row in aliases.items()}
        with self.store.connect() as con:
            rows = con.execute("select value_json from admin_settings where starts_with(key, ?)", [MAPPING_PREFIX]).fetchall()
        for row in rows:
            mapping = PriceMapping.model_validate_json(row[0])
            result[mapping.asset] = mapping.model_dump()
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

    def plan(self, query):
        mappings = self.mappings()
        risks = ExternalPriceBackfillService(self.store)._token_risk_statuses()
        combined = {}
        for item in PriceCoverageService(self.store).requirements().requirements:
            if query.year is not None and query.year not in {reporting_tax_year(item.first_event_at), reporting_tax_year(item.last_event_at)} or query.assets and item.asset.upper() not in query.assets:
                continue
            key = (item.price_date.isoformat(), item.asset.upper())
            if key not in combined:
                mapping = mappings.get(key[1], {})
                identifier = mapping.get("coingecko_id") if query.provider == "coingecko" else mapping.get("defillama_id") or ("coingecko:" + mapping["coingecko_id"] if mapping.get("coingecko_id") else None)
                reason = "token_risk_spam_review" if risks.get(key[1]) == "spam_review" else "asset_not_configured" if not identifier else "future_date" if item.price_date >= datetime.now(timezone.utc).date() else None
                combined[key] = {"asset": key[1], "price_date": key[0], "event_count": 0, "provider_id": identifier,
                                 "status": "blocked" if reason else "planned", "reason": reason,
                                 "first_event_at": item.first_event_at.replace(tzinfo=timezone.utc).isoformat()}
            combined[key]["event_count"] += item.event_count
            combined[key]["first_event_at"] = min(combined[key]["first_event_at"], item.first_event_at.replace(tzinfo=timezone.utc).isoformat())
        rows = sorted(combined.values(), key=lambda row: (row["status"] != "planned", row["price_date"], row["asset"]))
        revision = self._revision()
        result = {"query": query.model_dump(mode="json"), "methodology": METHOD, "time_basis": "CoinGecko: UTC-Tagesreferenz; DefiLlama: belegter Quote vor erstem Ereignis des UTC-Tags; kein Ausfuehrungskurs",
                  "database_revision": revision, "requirements_count": len(rows), "rows": rows[:200],
                  "rows_truncated": len(rows) > 200, "events_count": sum(row["event_count"] for row in rows),
                  "fetchable_count": sum(row["status"] == "planned" for row in rows),
                  "max_requests": query.max_requests, "writes_financial_data": False}
        result["plan_sha256"] = digest({**result, "rows": rows})
        return result

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
            quotes = self._request(client, "fx", "https://api.frankfurter.dev/v2/providers/ecb/rates",
                                  {"base": "USD", "quotes": "EUR", "from": (day - timedelta(days=7)).isoformat(), "to": day.isoformat()}, evidence)
            if not isinstance(quotes, list) or not quotes:
                fail("historical_price_fx_date_invalid")
            for quote in quotes:
                if not isinstance(quote, dict) or quote.get("base") != "USD" or quote.get("quote") != "EUR" or date.fromisoformat(quote["date"]) > day:
                    fail("historical_price_fx_date_invalid")
            fx = max(quotes, key=lambda q: q["date"])
            fx_day = date.fromisoformat(fx["date"])
            if not 0 <= (day - fx_day).days <= 7:
                fail("historical_price_fx_date_invalid")
            fx_cache[day] = (positive(fx.get("rate")), fx_day.isoformat(), evidence[-1])
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
        directory = self._directory(request.request_id)
        query = HistoricalPriceQuery.model_validate(request.model_dump(include=set(HistoricalPriceQuery.model_fields)))
        with self._lock(self._path("collection")), self._lock(directory):
            request_doc = request.model_dump(mode="json")
            if (directory / "request.json").exists():
                if self._json(directory / "request.json") != request_doc:
                    fail("historical_price_request_conflict")
                return self.get(request.request_id)
            plan = self.plan(query)
            if plan["plan_sha256"] != request.plan_sha256:
                fail("historical_price_plan_stale")
            self._write(directory / "request.json", canonical_json(request_doc).encode())
            rows, evidence, prices, fx_cache = [], [], [], {}
            with outbound_scope(max_requests=query.max_requests) as scope, managed_client(timeout=20) as client:
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
                    if scope.budget.requests_started >= query.max_requests:
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

    def _prepare(self, directory, preview, prices):
        with self.store.exclusive_access(), self.store.connect() as con:
            if self._revision() != preview["database_revision"]:
                fail("historical_price_plan_stale")
            preview["before_summary"] = _summary(con)
            before_tax = _tax_groups(con)
            con.execute("checkpoint")
            if shutil.disk_usage(directory).free < self.store.path.stat().st_size * 2 + 128 * 1024 * 1024:
                fail("historical_price_storage_insufficient")
            shutil.copyfile(self.store.path, directory / "calculation.prepared")
            (directory / "calculation.prepared").chmod(0o600)
        from steuerreport_v2.db.duckdb_store import DuckDbStore
        clone = DuckDbStore(directory / "calculation.prepared")
        clone.add_price_points(prices)
        pipeline = PipelineService(clone).rebuild_all()
        with clone.connect() as con:
            preview["after_summary"] = _summary(con)
            preview["tax_line_deltas"] = _tax_delta(before_tax, _tax_groups(con))
            preview["review_issues_open"] = pipeline.review_issues_open
            preview["remaining_requirements"] = PriceCoverageService(clone).requirements().requirements_count
            con.execute("checkpoint")
        preview["prepared_sha256"] = hashlib.sha256((directory / "calculation.prepared").read_bytes()).hexdigest()

    def get(self, request_id):
        directory = self._directory(request_id)
        preview = self._json(directory / "preview.json")
        if digest({k: v for k, v in preview.items() if k != "preview_sha256"}) != preview["preview_sha256"]:
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
                results.append({k: preview.get(k) for k in ("id", "created_at", "prices_count", "status", "applied", "preview_sha256")})
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
            if preview["status"] != "ready" or preview["software_version"] != __version__:
                fail("historical_price_preview_stale")
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
                safe = str(prepared).replace("'", "''")
                con.execute(f"attach '{safe}' as historical_prices_prepared (read_only)")
                try:
                    con.execute("begin transaction")
                    for table in DERIVED_TABLES:
                        con.execute(f"delete from {table}")
                        con.execute(f"insert into {table} select * from historical_prices_prepared.{table}")
                    if _summary(con) != preview["after_summary"]:
                        fail("reconciliation_failed")
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
