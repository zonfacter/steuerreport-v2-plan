"""Gebundene menschliche Preisbestaetigung; keine Preis- oder Steuerwriter."""
from __future__ import annotations

import base64
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import os
from pathlib import Path
from uuid import UUID

from pydantic import ValidationError
from steuerreport_v2 import __version__
from steuerreport_v2.contracts import price_evidence as evidence_contract
from steuerreport_v2.domain import price_evidence as evidence_library

from steuerreport_v2.contracts.price_admissions import (
    PriceAdmissionApply, PriceAdmissionDraftRequest, PriceAdmissionFacts,
    PriceAdmissionReport, PriceAdmissionRevoke, PriceAdmissionStoredDraft,
    PriceMethodDescriptor,
)
from steuerreport_v2.contracts.price_evidence import (
    PriceEvidenceAdmission, PriceEvidenceApproval, PriceEvidenceObservation,
)
from steuerreport_v2.contracts.price_import_evidence import PriceImportOriginalRef
from steuerreport_v2.contracts.prices import PricePoint
from steuerreport_v2.contracts.review import ReviewDecision
from steuerreport_v2.domain.connections import ConnectionService
from steuerreport_v2.domain.asset_identity import AssetIdentityIndex, identity_from_payload
from steuerreport_v2.domain.historical_prices import HistoricalPriceError, digest
from steuerreport_v2.domain.price_evidence import assess_price_evidence, price_evidence_binding
from steuerreport_v2.domain.price_import_evidence import PriceImportEvidenceService
from steuerreport_v2.domain.price_policy import as_utc
from steuerreport_v2.importers.source_history_importer import canonical_json


ADMISSION_TYPE = "stichtag_price_time_admission"
REVOCATION_TYPE = "stichtag_price_time_admission_revocation"
RESERVED_TYPES = frozenset({ADMISSION_TYPE, REVOCATION_TYPE})
MAIN_PREFIX = "price-time-admission:"
REVOKE_PREFIX = "price-time-revocation:"


class PriceAdmissionError(RuntimeError):
    def __init__(self, code: str, http_status: int = 409):
        super().__init__(code)
        self.code, self.http_status = code, http_status


def fail(code, status=409):
    raise PriceAdmissionError(code, status)


def _id(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        fail("price_admission_id_invalid", 422)


def _now():
    return datetime.now(timezone.utc)


def _scope(price_id, valuation_at):
    return "price_time_admission:" + _id(price_id) + ":" + as_utc(valuation_at).isoformat(timespec="microseconds")


class PriceAdmissionService:
    MAX_RECORDS = 5000
    MAX_SCOPE_RECORDS = 200
    MAX_DRAFT_BYTES = 256 * 1024

    def __init__(self, store):
        self.store = store
        self.reader = PriceImportEvidenceService(store)

    @staticmethod
    def _validation_fingerprint():
        try:
            files = [Path(__file__), Path(evidence_contract.__file__), Path(evidence_library.__file__),
                     Path(__file__).with_name("price_import_evidence.py"),
                     Path(__file__).with_name("asset_identity.py"), Path(__file__).with_name("price_policy.py"),
                     Path(__file__).parents[1] / "contracts/price_admissions.py"]
            return digest({"policy_id": "human-price-admission", "version": 1, "software": __version__,
                           "files": {path.name + ":" + path.parent.name: hashlib.sha256(path.read_bytes()).hexdigest()
                                     for path in files}})
        except OSError:
            fail("price_admission_policy_unavailable", 503)

    @contextmanager
    def _read(self):
        try:
            with self.store.read_initialized_snapshot() as snapshot, snapshot.connect() as con:
                yield con
        except RuntimeError as exc:
            if str(exc) == "database_store_not_initialized":
                fail("price_admission_store_not_initialized")
            raise

    def _bytes(self, parts, limit, *, optional=False):
        try:
            return self.reader._bytes(parts, limit, optional=optional)
        except HistoricalPriceError as exc:
            if str(exc) == "historical_price_reader_limit_exceeded":
                fail("price_admission_read_limit")
            fail("price_admission_evidence_unavailable", 404 if str(exc).endswith("not_found") else 409)

    def _write(self, parts, content):
        # The import root already exists. Every child is opened by descriptor;
        # neither a replaced directory nor a FIFO may redirect/block a write.
        try:
            with ExitStack() as stack:
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                fd = os.open(self.reader.history.root, flags)
                stack.callback(os.close, fd)
                for part in parts[:-1]:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=fd)
                    except FileExistsError:
                        pass
                    fd = os.open(part, flags, dir_fd=fd)
                    stack.callback(os.close, fd)
                try:
                    file_fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                      0o400, dir_fd=fd)
                except FileExistsError:
                    if self._bytes(parts, max(len(content), 1)) != content:
                        fail("price_admission_artifact_conflict")
                    return
                with os.fdopen(file_fd, "wb") as stream:
                    stream.write(content)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.fsync(fd)
        except OSError:
            fail("price_admission_storage_unavailable", 503)

    @staticmethod
    def _observation(facts, captured_at):
        value = facts.observation.model_dump(mode="python")
        value["captured_at"] = captured_at
        if value["fx"] is not None:
            value["fx"]["captured_at"] = captured_at
        try:
            return PriceEvidenceObservation.model_validate(value)
        except ValidationError:
            fail("price_admission_observation_invalid", 422)

    @staticmethod
    def _point(con, price_id):
        row = con.execute("select price_id,asset,price_eur,priced_at,source,confidence from price_ledger where price_id=?",
                          [price_id]).fetchone()
        if row is None:
            fail("price_admission_point_missing")
        return PricePoint(price_id=row[0], asset=row[1], price_eur=row[2], priced_at=as_utc(row[3]),
                          source=row[4], confidence=row[5])

    @staticmethod
    def _url(preview_id, price_id):
        return f"/api/v1/prices/historical/previews/{preview_id}/prices/{price_id}"

    def _draft(self, preview_id, price_id, request_id):
        parts = ("admissions", _id(request_id), "draft.json")
        try:
            raw = self.reader._json(self._bytes(parts, self.MAX_DRAFT_BYTES))
            doc = PriceAdmissionStoredDraft.model_validate(raw)
        except (ValidationError, HistoricalPriceError):
            fail("price_admission_draft_invalid")
        if (str(doc.request_id) != _id(request_id) or str(doc.preview_id) != _id(preview_id)
                or str(doc.price_id) != _id(price_id) or doc.point.price_id != _id(price_id)
                or doc.draft_sha256 != digest({key: value for key, value in raw.items() if key != "draft_sha256"})):
            fail("price_admission_draft_changed")
        return doc

    @staticmethod
    def _approval(doc, created_at):
        return PriceEvidenceApproval(
            decision_id=MAIN_PREFIX + str(doc.request_id), binding_sha256=doc.binding_sha256,
            actor=doc.facts.actor, rationale=doc.facts.rationale, approved_at=created_at,
            acknowledge_original_verified=True, acknowledge_scope_limited=True,
        )

    def _expected_decision(self, doc, created_at):
        return ReviewDecision(
            decision_id=MAIN_PREFIX + str(doc.request_id), decision_type=ADMISSION_TYPE,
            scope=_scope(doc.price_id, doc.facts.valuation_at), title="Preiszeit und Methode menschlich bestaetigt",
            rationale=doc.facts.rationale, actor=doc.facts.actor, source="price_evidence_operator",
            affected_ids=[str(doc.price_id)],
            evidence_ref=self._url(doc.preview_id, doc.price_id) + f"/admission-previews/{doc.request_id}",
            payload={"draft_sha256": doc.draft_sha256,
                     "approval": self._approval(doc, created_at).model_dump(mode="json")},
            created_at=created_at,
        )

    @staticmethod
    def _record(row):
        if row is None:
            return None
        try:
            if not isinstance(row[1], str) or len(row[1].encode()) > 128 * 1024:
                fail("price_admission_decision_invalid")
            raw = PriceImportEvidenceService._json(row[1].encode())
            decision = ReviewDecision.model_validate(raw)
            if (row[0] != decision.decision_id or row[3] is not None or decision.updated_at is not None
                    or decision.created_at.tzinfo is None or decision.created_at != as_utc(row[2])
                    or set(raw) != set(ReviewDecision.model_fields)):
                fail("price_admission_decision_invalid")
            # Preserve JSON type differences such as true versus 1.
            if canonical_json(raw) != canonical_json(decision.model_dump(mode="json")):
                fail("price_admission_decision_invalid")
            return decision
        except (ValidationError, HistoricalPriceError, TypeError, AttributeError):
            fail("price_admission_decision_invalid")

    def _decision(self, con, doc):
        decision = self._record(con.execute("select id,payload_json,created_at,updated_at from review_decisions where id=?",
                                            [MAIN_PREFIX + str(doc.request_id)]).fetchone())
        if decision is not None and canonical_json(decision.model_dump(mode="json")) != canonical_json(
                self._expected_decision(doc, decision.created_at).model_dump(mode="json")):
            fail("price_admission_decision_invalid")
        return decision

    def _revocation(self, con, doc, decision):
        value = self._record(con.execute("select id,payload_json,created_at,updated_at from review_decisions where id=?",
                                         [REVOKE_PREFIX + str(doc.request_id)]).fetchone())
        if value is None:
            return None
        expected_payload = {"draft_sha256": doc.draft_sha256, "decision_id": MAIN_PREFIX + str(doc.request_id),
                            "acknowledge_revocation": True}
        if decision is None:
            fail("price_admission_revocation_invalid")
        expected = ReviewDecision(
            decision_id=REVOKE_PREFIX + str(doc.request_id), decision_type=REVOCATION_TYPE,
            scope=decision.scope, title="Preiszeit-Bestaetigung widerrufen", rationale=value.rationale,
            actor=value.actor, source="price_evidence_operator", affected_ids=[str(doc.price_id)],
            evidence_ref=decision.evidence_ref, payload=expected_payload, created_at=value.created_at,
        )
        if (not value.actor.strip() or not value.rationale.strip() or value.created_at < decision.created_at
                or canonical_json(value.model_dump(mode="json")) != canonical_json(expected.model_dump(mode="json"))):
            fail("price_admission_revocation_invalid")
        return value

    @staticmethod
    def _rejected(doc, reasons, *, integrity=False, decision=None):
        return PriceEvidenceAdmission(status="rejected", strict_eligible=False,
            binding_sha256=doc.binding_sha256, decision_id=decision.decision_id if decision else None,
            reason_codes=reasons, original_integrity_verified=integrity, evidence_origin="unverified")

    def _check_identity(self, identity, row, con):
        hints = row.get("asset_identity") or {}
        if not isinstance(hints, dict):
            fail("price_admission_identity_conflict")
        try:
            actual = identity_from_payload({"network": identity.network, "contract_address": identity.contract,
                                           "decimals": identity.decimals}, role="asset", source="", quantity=Decimal("0"))
            expected = identity_from_payload(hints, role="asset", source="", quantity=Decimal("0")) if hints else None
        except ValueError:
            fail("price_admission_identity_conflict")
        mints = row.get("mints") or []
        if (not isinstance(mints, list) or any(not isinstance(mint, str) for mint in mints)
                or len(set(mints)) > 1):
            fail("price_admission_identity_conflict")
        if expected and (expected.key != actual.key or expected.decimals is not None and expected.decimals != actual.decimals):
            fail("price_admission_identity_conflict")
        if mints and (actual.network != "solana" or actual.contract != mints[0]):
            fail("price_admission_identity_conflict")
        current = AssetIdentityIndex(self.store, connection=con, asset=identity.asset)
        if identity.asset in current.problems:
            fail("price_admission_identity_conflict")
        known = current.identities.get(identity.asset)
        if known and (known.key != actual.key or known.decimals is not None and known.decimals != actual.decimals):
            fail("price_admission_identity_conflict")
        if (expected or mints) and known is None:
            fail("price_admission_current_identity_missing")

    def _evaluate(self, con, doc, decision=None):
        observation = self._observation(doc.facts, doc.created_at)
        try:
            if doc.validation_policy_sha256 != self._validation_fingerprint():
                fail("price_admission_policy_changed")
            imported, originals, row = self.reader._binding_context(con, str(doc.preview_id), str(doc.price_id))
            self._check_identity(doc.facts.identity, row, con)
            if (imported.preview_sha256 != doc.facts.preview_sha256
                    or imported.price_fingerprint != doc.facts.price_fingerprint
                    or imported.originals != doc.originals):
                fail("price_admission_import_changed")
            point = self._point(con, str(doc.price_id))
            if point.model_dump(mode="json") != doc.point.model_dump(mode="json"):
                fail("price_admission_price_changed")
            required = {observation.evidence_sha256}
            if observation.fx is not None:
                required.add(observation.fx.evidence_sha256)
            if not required.issubset(originals):
                fail("price_admission_original_not_bound")
            body = self._bytes(("admissions", "originals", doc.method_original.sha256 + ".body"), 2 * 1024 * 1024)
            if len(body) != doc.method_original.byte_length or hashlib.sha256(body).hexdigest() != doc.method_original.sha256:
                fail("price_admission_method_changed")
            originals = {**originals, doc.method_original.sha256: body}
            if doc.facts.method.evidence_sha256 != doc.method_original.sha256:
                fail("price_admission_method_changed")
            binding = price_evidence_binding(point=point, identity=doc.facts.identity,
                valuation_at=doc.facts.valuation_at, observation=observation, method=doc.facts.method)
            if binding != doc.binding_sha256:
                fail("price_admission_binding_changed")
            return assess_price_evidence(point=point, identity=doc.facts.identity, valuation_at=doc.facts.valuation_at,
                observation=observation, method=doc.facts.method,
                approval=self._approval(doc, decision.created_at) if decision else None, originals=originals)
        except HistoricalPriceError:
            return self._rejected(doc, ["price_admission_import_changed"], decision=decision)
        except PriceAdmissionError as exc:
            return self._rejected(doc, [exc.code], decision=decision)
        except ValidationError:
            return self._rejected(doc, ["price_admission_inputs_invalid"], decision=decision)

    def _active_ids(self, con, documents):
        active = set()
        for doc in documents:
            decision = self._decision(con, doc)
            if decision is not None and self._revocation(con, doc, decision) is None:
                active.add(str(doc.request_id))
        return frozenset(active)

    def _report(self, con, doc, *, active_ids=None):
        decision = self._decision(con, doc)
        revoked = self._revocation(con, doc, decision)
        assessment = self._evaluate(con, doc, decision)
        if revoked is not None:
            assessment = self._rejected(doc, ["price_admission_revoked"],
                                        integrity=assessment.original_integrity_verified, decision=decision)
        if assessment.strict_eligible:
            if active_ids is None:
                active_ids = self._active_ids(con, self._scope_docs(con, str(doc.price_id), doc.facts.valuation_at))
            if active_ids != frozenset({str(doc.request_id)}):
                fail("price_admission_ambiguous")
        can_apply = decision is None and revoked is None and assessment.reason_codes == ["approval_missing"]
        status = ("revoked" if revoked else "human_approved" if assessment.strict_eligible
                  else "prepared" if can_apply else "rejected" if decision else "blocked")
        method = doc.method_original
        return PriceAdmissionReport(status=status, request_id=doc.request_id, preview_id=doc.preview_id,
            price_id=doc.price_id, draft_sha256=doc.draft_sha256, price_fingerprint=doc.facts.price_fingerprint,
            created_at=doc.created_at, valuation_at=doc.facts.valuation_at, identity=doc.facts.identity,
            validation_policy_sha256=doc.validation_policy_sha256,
            observation=self._observation(doc.facts, doc.created_at), method=doc.facts.method,
            actor=doc.facts.actor, rationale=doc.facts.rationale, assessment=assessment, can_apply=can_apply,
            decision=decision, revocation=revoked, originals=doc.originals,
            method_original=PriceImportOriginalRef(sha256=method.sha256, byte_length=method.byte_length,
                filename=method.filename, download_url=self._url(doc.preview_id, doc.price_id)
                + f"/admission-previews/{doc.request_id}/method-original"))

    def prepare(self, preview_id, price_id, request: PriceAdmissionDraftRequest):
        preview_id, price_id = _id(preview_id), _id(price_id)
        request = PriceAdmissionDraftRequest.model_validate(request.model_dump(mode="python"))
        body = base64.b64decode(request.method_original.content_base64, validate=True)
        method_sha = hashlib.sha256(body).hexdigest()
        if request.method.evidence_sha256 != method_sha:
            fail("price_admission_method_hash_mismatch", 422)
        facts = PriceAdmissionFacts.model_validate(request.model_dump(exclude={"request_id", "method_original"}))
        method = PriceMethodDescriptor(sha256=method_sha, byte_length=len(body),
            filename=request.method_original.filename, media_type=request.method_original.media_type)
        request_sha = digest({"facts": facts.model_dump(mode="json"), "method": method.model_dump(mode="json")})
        with ConnectionService(self.store)._mutation():
            existing = self._bytes(("admissions", str(request.request_id), "draft.json"),
                                   self.MAX_DRAFT_BYTES, optional=True)
            if existing is not None:
                doc = self._draft(preview_id, price_id, request.request_id)
                if doc.request_sha256 != request_sha:
                    fail("price_admission_request_conflict")
                with self._read() as con:
                    return self._report(con, doc)
            created_at = _now()
            if facts.valuation_at > created_at:
                fail("price_admission_valuation_in_future", 422)
            observation = self._observation(facts, created_at)
            with self._read() as con:
                try:
                    imported, originals, row = self.reader._binding_context(con, preview_id, price_id)
                except HistoricalPriceError:
                    fail("price_admission_import_changed")
                if imported.preview_sha256 != facts.preview_sha256 or imported.price_fingerprint != facts.price_fingerprint:
                    fail("price_admission_import_changed")
                self._check_identity(facts.identity, row, con)
                required = {observation.evidence_sha256} | ({observation.fx.evidence_sha256} if observation.fx else set())
                if not required.issubset(originals):
                    fail("price_admission_original_not_bound", 422)
                point = self._point(con, price_id)
                binding = price_evidence_binding(point=point, identity=facts.identity, valuation_at=facts.valuation_at,
                                                observation=observation, method=facts.method)
                # Also enforce the pure library's aggregate original budget before writing anything.
                try:
                    assess_price_evidence(point=point, identity=facts.identity, valuation_at=facts.valuation_at,
                        observation=observation, method=facts.method, approval=None,
                        originals={**originals, method_sha: body})
                except ValidationError:
                    fail("price_admission_inputs_invalid", 422)
            content = {"format_version": 1, "request_id": str(request.request_id), "preview_id": preview_id,
                       "validation_policy_sha256": self._validation_fingerprint(),
                       "price_id": price_id, "created_at": created_at.isoformat(), "facts": facts.model_dump(mode="json"),
                       "point": point.model_dump(mode="json"), "originals": [item.model_dump(mode="json") for item in imported.originals],
                       "method_original": method.model_dump(mode="json"), "request_sha256": request_sha,
                       "binding_sha256": binding}
            content["draft_sha256"] = digest(content)
            doc = PriceAdmissionStoredDraft.model_validate(content)
            encoded = canonical_json(content).encode()
            if len(encoded) > self.MAX_DRAFT_BYTES:
                fail("price_admission_read_limit", 422)
            self._write(("admissions", "originals", method_sha + ".body"), body)
            self._write(("admissions", str(request.request_id), "draft.json"), encoded)
            with self._read() as con:
                return self._report(con, doc)

    def get(self, preview_id, price_id, request_id):
        doc = self._draft(preview_id, price_id, request_id)
        with self._read() as con:
            return self._report(con, doc)

    def apply(self, preview_id, price_id, request_id, request: PriceAdmissionApply):
        request = PriceAdmissionApply.model_validate(request.model_dump())
        with ConnectionService(self.store)._mutation(), self.store.connect() as con:
            con.execute("begin transaction")
            try:
                doc = self._draft(preview_id, price_id, request_id)
                if request.draft_sha256 != doc.draft_sha256:
                    fail("price_admission_draft_changed")
                report = self._report(con, doc)
                if report.revocation is not None:
                    fail("price_admission_revoked")
                if report.decision is not None:
                    if not report.assessment.strict_eligible:
                        fail("price_admission_evidence_changed")
                    con.execute("commit")
                    return report
                if not report.can_apply:
                    fail("price_admission_not_applicable")
                others = self._scope_docs(con, str(doc.price_id), doc.facts.valuation_at)
                for other in others:
                    main = self._decision(con, other)
                    if main is not None and self._revocation(con, other, main) is None:
                        fail("price_admission_already_exists")
                decision = self._expected_decision(doc, _now())
                if decision.created_at < doc.created_at:
                    fail("price_admission_clock_invalid")
                if not self._evaluate(con, doc, decision).strict_eligible:
                    fail("price_admission_not_applicable")
                con.execute("insert into review_decisions values (?,?,?,?)",
                            [decision.decision_id, decision.model_dump_json(), decision.created_at, None])
                result = self._report(con, doc)
                if not result.assessment.strict_eligible:
                    fail("price_admission_evidence_changed")
                con.execute("commit")
                return result
            except Exception:
                con.execute("rollback")
                raise

    def revoke(self, preview_id, price_id, request_id, request: PriceAdmissionRevoke):
        request = PriceAdmissionRevoke.model_validate(request.model_dump())
        with ConnectionService(self.store)._mutation(), self.store.connect() as con:
            con.execute("begin transaction")
            try:
                doc = self._draft(preview_id, price_id, request_id)
                if request.draft_sha256 != doc.draft_sha256:
                    fail("price_admission_draft_changed")
                main = self._decision(con, doc)
                if main is None:
                    fail("price_admission_not_approved")
                previous = self._revocation(con, doc, main)
                if previous is not None:
                    if previous.actor != request.actor or previous.rationale != request.rationale:
                        fail("price_admission_revocation_conflict")
                else:
                    created_at = _now()
                    if created_at < main.created_at:
                        fail("price_admission_clock_invalid")
                    value = ReviewDecision(decision_id=REVOKE_PREFIX + str(doc.request_id), decision_type=REVOCATION_TYPE,
                        scope=main.scope, title="Preiszeit-Bestaetigung widerrufen", actor=request.actor,
                        rationale=request.rationale, source="price_evidence_operator", affected_ids=[str(doc.price_id)],
                        evidence_ref=main.evidence_ref, payload={"draft_sha256": doc.draft_sha256,
                            "decision_id": main.decision_id, "acknowledge_revocation": True}, created_at=created_at)
                    con.execute("insert into review_decisions values (?,?,?,?)",
                                [value.decision_id, value.model_dump_json(), value.created_at, None])
                result = self._report(con, doc)
                con.execute("commit")
                return result
            except Exception:
                con.execute("rollback")
                raise

    def method_original(self, preview_id, price_id, request_id):
        doc = self._draft(preview_id, price_id, request_id)
        data = self._bytes(("admissions", "originals", doc.method_original.sha256 + ".body"), 2 * 1024 * 1024)
        if hashlib.sha256(data).hexdigest() != doc.method_original.sha256 or len(data) != doc.method_original.byte_length:
            fail("price_admission_method_changed")
        return data, doc.method_original.filename

    def _records(self, con):
        rows = con.execute("select id,payload_json,created_at,updated_at from review_decisions "
                           "where starts_with(id,?) or starts_with(id,?) order by id limit ?",
                           [MAIN_PREFIX, REVOKE_PREFIX, self.MAX_RECORDS + 1]).fetchall()
        if len(rows) > self.MAX_RECORDS:
            fail("price_admission_read_limit")
        return [self._record(row) for row in rows]

    def _scope_docs(self, con, price_id, valuation_at, *, records=None):
        scope = _scope(price_id, valuation_at)
        documents = []
        for record in self._records(con) if records is None else records:
            if record.scope != scope or not record.decision_id.startswith(MAIN_PREFIX):
                continue
            request_id = _id(record.decision_id[len(MAIN_PREFIX):])
            # The canonical evidence reference supplies only a fixed UUID route,
            # never a filesystem path or a URL to dereference.
            parts = str(record.evidence_ref).split("/")
            if (len(parts) != 11 or parts[:6] != ["", "api", "v1", "prices", "historical", "previews"]
                    or parts[7] != "prices" or parts[9] != "admission-previews"
                    or parts[10] != request_id):
                fail("price_admission_decision_invalid")
            if _id(parts[8]) != _id(price_id):
                fail("price_admission_decision_invalid")
            doc = self._draft(_id(parts[6]), price_id, request_id)
            if _scope(doc.price_id, doc.facts.valuation_at) != scope:
                fail("price_admission_decision_invalid")
            self._decision(con, doc)
            documents.append(doc)
        if len(documents) > self.MAX_SCOPE_RECORDS:
            fail("price_admission_read_limit")
        return documents

    def _for_scope(self, con, price_id, valuation_at):
        documents = self._scope_docs(con, price_id, valuation_at)
        active_ids = self._active_ids(con, documents)
        if len(active_ids) > 1:
            fail("price_admission_ambiguous")
        reports = [self._report(con, doc, active_ids=active_ids) for doc in documents]
        active = [report for report in reports if report.revocation is None]
        if len(active) > 1:
            fail("price_admission_ambiguous")
        return active[0] if active else max(reports, key=lambda report: report.created_at, default=None)

    def read_admission(self, preview_id, price_id, valuation_at):
        preview_id, price_id = _id(preview_id), _id(price_id)
        with self._read() as con:
            result = self._for_scope(con, price_id, as_utc(valuation_at))
            if result is not None and str(result.preview_id) != preview_id:
                fail("price_admission_import_changed")
            return result

    def assess_selected(self, *, price_id, valuation_at, asset, price_eur, price_source, priced_at):
        price_id = _id(price_id)
        with self._read() as con:
            report = self._for_scope(con, price_id, as_utc(valuation_at))
            if report is None:
                return None
            doc = self._draft(report.preview_id, price_id, report.request_id)
            point = doc.point
            if (point.asset != asset or point.price_eur != price_eur or point.source != price_source
                    or priced_at is None or point.priced_at != as_utc(priced_at)):
                fail("price_admission_selected_price_changed")
            return report

    def state_fingerprint(self, valuation_at):
        instant = as_utc(valuation_at)
        suffix = ":" + instant.isoformat(timespec="microseconds")
        with self._read() as con:
            records = [record for record in self._records(con) if record.scope.endswith(suffix)]
            if not records:
                return None
            if len(records) > self.MAX_SCOPE_RECORDS * 2:
                fail("price_admission_read_limit")
            # One bounded record read per snapshot, one validation per scope.
            # Historical revocations must not multiply all-record rescans.
            by_scope = {}
            for record in records:
                by_scope.setdefault(record.scope, []).append(record)
            scope_cache = {}
            states = []
            for record in records:
                entry = {"decision": record.model_dump(mode="json")}
                if record.decision_id.startswith(MAIN_PREFIX):
                    try:
                        price_id = record.scope[len("price_time_admission:"):-len(suffix)]
                        if record.scope not in scope_cache:
                            try:
                                documents = self._scope_docs(con, _id(price_id), instant, records=by_scope[record.scope])
                                scope_cache[record.scope] = (
                                    {MAIN_PREFIX + str(doc.request_id): doc for doc in documents},
                                    self._active_ids(con, documents),
                                )
                            except PriceAdmissionError as exc:
                                scope_cache[record.scope] = exc
                        cached = scope_cache[record.scope]
                        if isinstance(cached, PriceAdmissionError):
                            fail(cached.code, cached.http_status)
                        documents, active_ids = cached
                        doc = documents.get(record.decision_id)
                        if doc is None:
                            fail("price_admission_decision_invalid")
                        entry["report"] = self._report(con, doc, active_ids=active_ids).model_dump(mode="json")
                    except (PriceAdmissionError, StopIteration) as exc:
                        entry["error"] = exc.code if isinstance(exc, PriceAdmissionError) else "price_admission_decision_invalid"
                states.append(entry)
            return digest({"policy_id": "price-admission-state", "version": 1, "valuation_at": instant.isoformat(), "states": states})
