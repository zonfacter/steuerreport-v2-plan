"""Begrenzter lesender Originalreader fuer bereits initialisierte App-Stores."""
from contextlib import ExitStack
import hashlib
import json
import os
import stat
from uuid import UUID

from pydantic import ValidationError

from steuerreport_v2.contracts.price_import_evidence import (
    PreparedPriceBinding, PriceImportEvidenceReport, PriceImportOriginalRef,
)
from steuerreport_v2.contracts.prices import PricePoint, PricePointCreate
from steuerreport_v2.domain.historical_prices import HistoricalPriceService, digest, fail
from steuerreport_v2.domain.price_evidence import price_point_fingerprint
from steuerreport_v2.domain.price_policy import as_utc


class PriceImportEvidenceService:
    MAX_PREVIEW_BYTES = 32 * 1024 * 1024
    MAX_ORIGINAL_BYTES = 2 * 1024 * 1024
    MAX_ORIGINALS_BYTES = 6 * 1024 * 1024

    def __init__(self, store):
        self.store = store
        self.history = HistoricalPriceService(store)

    def _bytes(self, parts, limit, *, optional=False):
        try:
            with ExitStack() as stack:
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                fd = os.open(self.history.root, flags)
                stack.callback(os.close, fd)
                for part in parts[:-1]:
                    fd = os.open(part, flags, dir_fd=fd)
                    stack.callback(os.close, fd)
                file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                with os.fdopen(file_fd, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode):
                        fail("historical_price_evidence_changed")
                    if info.st_size > limit:
                        fail("historical_price_reader_limit_exceeded")
                    content = stream.read(limit + 1)
                    if len(content) > limit:
                        fail("historical_price_reader_limit_exceeded")
                    return content
        except FileNotFoundError:
            if optional:
                return None
            fail("historical_price_not_found")
        except OSError:
            fail("historical_price_evidence_changed")

    @staticmethod
    def _json(content):
        def unique(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError("duplicate_key")
                result[key] = value
            return result

        def invalid(_value):
            raise ValueError("non_finite_json")

        try:
            result = json.loads(content, object_pairs_hook=unique, parse_constant=invalid)
            if not isinstance(result, dict):
                raise ValueError("object_required")
            return result
        except (ValueError, RecursionError):
            fail("historical_price_evidence_changed")

    def _preview(self, preview_id):
        preview = self._json(self._bytes((preview_id, "preview.json"), self.MAX_PREVIEW_BYTES))
        if (preview.get("id") != preview_id or not isinstance(preview.get("preview_sha256"), str)
                or digest({k: v for k, v in preview.items() if k != "preview_sha256"}) != preview["preview_sha256"]):
            fail("historical_price_evidence_changed")
        query = preview.get("query")
        if not isinstance(query, dict):
            fail("historical_price_evidence_changed")
        if self.history._uses_collection(query):
            plan = self._json(self._bytes((preview_id, "plan.json"), self.MAX_PREVIEW_BYTES))
            if (plan.get("plan_sha256") != preview.get("plan_sha256")
                    or digest({k: v for k, v in plan.items() if k != "plan_sha256"}) != preview.get("plan_sha256")):
                fail("historical_price_evidence_changed")
        return preview

    def read(self, preview_id, price_id):
        return self._collect(preview_id, price_id)[0]

    def original(self, preview_id, price_id, sha256):
        return self.download(preview_id, price_id, sha256)[0]

    def download(self, preview_id, price_id, sha256):
        if not isinstance(sha256, str) or len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            fail("historical_price_not_found")
        report, originals = self._collect(preview_id, price_id)
        if sha256 not in originals:
            fail("historical_price_not_found")
        ref = next(item for item in report.originals if item.sha256 == sha256)
        return originals[sha256], ref.filename or f"price-original-{sha256}.body"

    def _collect(self, preview_id, price_id):
        preview_id, price_id = str(UUID(str(preview_id))), str(UUID(str(price_id)))
        try:
            with self.store.read_initialized_snapshot() as snapshot, snapshot.connect() as con:
                return self._within_snapshot(con, preview_id, price_id)
        except RuntimeError as exc:
            if str(exc) == "database_store_not_initialized":
                fail("historical_price_store_not_initialized")
            raise

    def _within_snapshot(self, con, preview_id, price_id):
        report, originals, _row = self._binding_context(con, preview_id, price_id)
        return report, originals

    def _binding_context(self, con, preview_id, price_id):
        preview = self._preview(preview_id)
        if type(preview.get("price_bindings_version")) is not int or preview["price_bindings_version"] != 1:
            fail("historical_price_binding_missing")
        bindings, prices = preview.get("price_bindings"), preview.get("prices")
        if (not isinstance(bindings, list) or not isinstance(prices, list)
                or len(bindings) > 50000 or len(bindings) != len(prices)
                or type(preview.get("prices_count")) is not int or preview["prices_count"] != len(prices)):
            fail("historical_price_binding_invalid")
        try:
            bindings = [PreparedPriceBinding.model_validate(item) for item in bindings]
        except ValidationError:
            fail("historical_price_binding_invalid")
        ids = [str(item.price_id) for item in bindings]
        if len(ids) != len(set(ids)) or price_id not in ids:
            fail("historical_price_binding_invalid")
        selected = bindings[ids.index(price_id)]
        if not self.history._applied_decision(con, preview_id, preview["preview_sha256"]):
            fail("historical_price_not_applied")
        receipt_bytes = self._bytes((preview_id, "applied.json"), 4096, optional=True)
        if receipt_bytes is not None:
            receipt = self._json(receipt_bytes)
            expected = {"applied": True, "prices_count": preview["prices_count"], "decision_id": "historical-price:" + preview_id}
            if (receipt != expected or type(receipt.get("applied")) is not bool or type(receipt.get("prices_count")) is not int):
                fail("historical_price_evidence_changed")
        row = con.execute("select price_id,asset,price_eur,priced_at,source,confidence from price_ledger where price_id=?", [price_id]).fetchone()
        if row is None:
            fail("historical_price_point_not_found")
        try:
            point = PricePoint(price_id=row[0], asset=row[1], price_eur=row[2], priced_at=as_utc(row[3]), source=row[4], confidence=row[5])
            fingerprint = price_point_fingerprint(point)
        except ValidationError:
            fail("historical_price_binding_invalid")
        if (selected.asset != point.asset or selected.price_eur != point.price_eur
                or selected.stored_reference_at != point.priced_at or selected.price_fingerprint != fingerprint):
            fail("historical_price_binding_invalid")
        try:
            expected = PricePointCreate.model_validate(prices[ids.index(price_id)])
        except ValidationError:
            fail("historical_price_binding_invalid")
        stored_input = con.execute("select cast(? as decimal(38,18))", [str(expected.price_eur)]).fetchone()[0]
        if (expected.asset != point.asset or stored_input != point.price_eur
                or as_utc(expected.priced_at) != point.priced_at or expected.source != point.source):
            fail("historical_price_binding_invalid")
        rows = preview.get("rows")
        if not isinstance(rows, list):
            fail("historical_price_binding_invalid")
        matches = []
        for candidate in rows:
            if isinstance(candidate, dict) and candidate.get("asset") == point.asset and candidate.get("source") == point.source:
                try:
                    value = PricePointCreate.model_validate({**candidate, "confidence": point.confidence})
                    if value.price_eur == expected.price_eur and as_utc(value.priced_at) == point.priced_at:
                        matches.append(candidate)
                except ValidationError:
                    continue
        if len(matches) != 1:
            fail("historical_price_binding_ambiguous")
        refs = matches[0].get("evidence_sha256")
        metadata = preview.get("evidence")
        if (not isinstance(refs, list) or not refs or len(refs) > 1000 or not isinstance(metadata, list)
                or any(not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha) for sha in refs)):
            fail("historical_price_binding_invalid")
        allowed = {item.get("sha256") for item in metadata if isinstance(item, dict) and isinstance(item.get("sha256"), str)}
        if not set(refs).issubset(allowed):
            fail("historical_price_binding_invalid")
        originals, links, total = {}, [], 0
        for sha in dict.fromkeys(refs):
            body = self._bytes(("evidence", sha + ".body"), self.MAX_ORIGINAL_BYTES)
            total += len(body)
            if total > self.MAX_ORIGINALS_BYTES:
                fail("historical_price_reader_limit_exceeded")
            if not body or hashlib.sha256(body).hexdigest() != sha:
                fail("historical_price_evidence_changed")
            originals[sha] = body
            names = [item.get("filename") for item in metadata if isinstance(item, dict) and item.get("sha256") == sha]
            name = names[0] if names and all(value == names[0] for value in names) else None
            if (not isinstance(name, str) or not 0 < len(name) <= 180 or name in {".", ".."}
                    or "/" in name or "\\" in name or any(ord(c) < 32 or ord(c) == 127 for c in name)):
                name = None
            links.append(PriceImportOriginalRef(sha256=sha, byte_length=len(body), download_url=(
                f"/api/v1/prices/historical/previews/{preview_id}/prices/{price_id}/evidence/{sha}"), filename=name))
        return PriceImportEvidenceReport(preview_id=preview_id, preview_sha256=preview["preview_sha256"], price_id=price_id,
                                         price_fingerprint=selected.price_fingerprint, asset=point.asset,
                                         price_eur=point.price_eur, stored_reference_at=point.priced_at, originals=links), originals, matches[0]
